"""Os *jobs* de purga: um corpo, quatro mecanismos, e o restauro (KAM-071).

    from kamba_core.retencao import jobs

    relatorio = jobs.executar(jobs.Execucao(abrir_ligacao=lote, agora=agora,
                                            storage=storage))
    jobs.exigir_sem_falhas(relatorio)        # levanta: alerta Sev2

## A unidade, e porque e ela que da a idempotencia

A purga parte-se em **unidades** — classe, tabela (com as dependentes) e tenant
— e cada unidade e **uma transaccao** do `kamba_batch`, com a eliminacao e a
linha do `purge_log` dentro. Uma unidade que levanta reverte inteira e deixa uma
linha `falhou` numa transaccao propria; as outras seguem. Nao ha estado
parcial, e repetir uma janela nao altera o resultado: a segunda corrida nao
encontra o tenant na janela e nao escreve nada sobre ele.

**O predicado e o tempo, e nunca o `purge_log`.** Uma janela ja registada nao se
salta: depois de um restauro, as linhas antigas voltaram e o *job* tem de as
tirar outra vez (ver `reaplicar_apos_restauro`). Um *job* que confiasse no
`purge_log` para decidir o que ja fez nao as via.

## O tenant esta no predicado, e o `kamba_batch` contorna a RLS

O papel do lote tem `BYPASSRLS`, pelo que o `tenant_id = %s` de cada instrucao
e a **unica** barreira entre a purga de um tenant e os dados de outro. Por isso
todas as instrucoes por tenant o levam, e o ensaio de base de dados poe um hold
num tenant e purga o outro.

## O hold le-se dentro da unidade, e nunca copia linhas de volta

Cada unidade le os *holds* **na sua propria transaccao**, e nao uma vez por
execucao: um hold aplicado a meio de uma corrida longa e visto pela unidade
seguinte. Um hold de tenant retem a unidade inteira. Um hold de contacto tira esse
contacto do predicado quando a tabela tem `contact_id`, e retem a unidade
inteira quando nao tem — e a leitura conservadora: sem a coluna, nao se sabe
quais linhas sao dele. Numa particao, qualquer hold de um tenant presente retem
o `DROP`, e numa tabela sem tenant (a quarentena) qualquer hold activo retem a
unidade. **Nunca** se copia uma linha retida para fora e de volta: e o caminho
pelo qual uma purga reintroduzia dados que o *erasure ledger* ja tinha tirado.

## O papel confere-se, porque sem `BYPASSRLS` tudo parece livre

Uma ligacao sem `BYPASSRLS` le **zero** holds e **zero** linhas retidas numa
particao, e a purga avancava sobre dados retidos com tudo a dizer «livre». A
sessao recusa arrancar se o papel nao contornar a RLS.

## O que nao esta aqui

O agendador (quem chama isto a horas) nao nasce neste ticket: e o KAM-078, como
o `kamba_agr.retencao` ja escreve. O que se entrega e o corpo, provado com
relogio simulado e contra PostgreSQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Protocol

from .. import tenant_guard
from ..direitos.eliminacao import sujeitos_a_reaplicar, sujeitos_apagados
from ..storage.port import Ctx, ObjectoInexistenteError, ObjectRef, StorageProvider
from . import hold, politica, purge_log
from .politica import Classe, Prazo

#: Quem abre uma ligacao DB-API com o `kamba_batch`. Uma por unidade.
AbrirLigacao = Callable[[], Any]

#: O actor do `batch.run` que abre cada execucao (criterio 8).
ACTOR_DO_LOTE: Final = "kamba_batch:retencao"

#: A sessao de lote no `audit_log`: cadeia de plataforma (tenant nulo).
SQL_SESSAO: Final = """
  SELECT platform.audit_append(
           NULL, 'system', %s, 'batch.run', 'retencao', %s, NULL, sha256(%s::bytea)
         )
"""

#: O papel da ligacao contorna a RLS? Ver a nota do modulo.
SQL_PAPEL: Final = "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"

#: Prazo do encerramento de um tenant (`08` §11, criterio 9).
PRAZO_DE_ENCERRAMENTO: Final = Prazo(dias=30)


# ------------------------------------------------------------------ caminhos


@dataclass(frozen=True)
class Caminho:
    """Como se purga uma tabela de uma classe `apagar`.

    Tres instrucoes com os mesmos parametros: quais tenants tem linhas na
    janela, quantas sao, e apagar. Com `global_`, a tabela nao tem tenant e as
    duas ultimas so recebem o limite. As `antes` correm na mesma transaccao e
    primeiro (as FK que nao apagam em cascata).
    """

    tabela: str
    sql_tenants: str
    sql_contar: str
    sql_apagar: str
    com_contacto: bool = False
    global_: bool = False
    antes: tuple["Caminho", ...] = ()

    def parametros(self, tenant: str | None, limite: datetime, retidos: Sequence[str]):
        if self.global_:
            return (limite,)
        if self.com_contacto:
            return (tenant, limite, list(retidos), tenant, limite)
        return (tenant, limite)


CAMINHO_OUTBOX: Final = Caminho(
    "platform.events_outbox",
    """SELECT DISTINCT tenant_id FROM platform.events_outbox
        WHERE publicado_at IS NOT NULL AND publicado_at < %s""",
    """SELECT count(*) FROM platform.events_outbox
        WHERE tenant_id = %s::uuid
          AND publicado_at IS NOT NULL AND publicado_at < %s""",
    """DELETE FROM platform.events_outbox
        WHERE tenant_id = %s::uuid
          AND publicado_at IS NOT NULL AND publicado_at < %s""",
)

CAMINHO_CONSUMIDOS: Final = Caminho(
    "platform.events_consumed",
    """SELECT DISTINCT tenant_id FROM platform.events_consumed
        WHERE processado_at < %s""",
    """SELECT count(*) FROM platform.events_consumed
        WHERE tenant_id = %s::uuid AND processado_at < %s""",
    """DELETE FROM platform.events_consumed
        WHERE tenant_id = %s::uuid AND processado_at < %s""",
)

#: As aprovacoes nao tem `tenant_id`: o tenant e o da entrada da DLQ.
CAMINHO_APROVACOES: Final = Caminho(
    "platform.evt_dlq_aprovacoes",
    "",
    """SELECT count(*) FROM platform.evt_dlq_aprovacoes a
         JOIN platform.events_dlq d ON d.id = a.dlq_id
        WHERE d.tenant_id = %s::uuid AND d.estado <> 'aberta'
          AND d.resolvido_at IS NOT NULL AND d.resolvido_at < %s""",
    """DELETE FROM platform.evt_dlq_aprovacoes a
        USING platform.events_dlq d
        WHERE d.id = a.dlq_id
          AND d.tenant_id = %s::uuid AND d.estado <> 'aberta'
          AND d.resolvido_at IS NOT NULL AND d.resolvido_at < %s""",
)

#: Uma entrada **aberta** nunca sai, por mais velha que seja: e um efeito de
#: negocio que ninguem aplicou. O mesmo predicado do `evt_limpar_dlq` da `0005`.
CAMINHO_DLQ: Final = Caminho(
    "platform.events_dlq",
    """SELECT DISTINCT tenant_id FROM platform.events_dlq
        WHERE estado <> 'aberta' AND resolvido_at IS NOT NULL AND resolvido_at < %s""",
    """SELECT count(*) FROM platform.events_dlq
        WHERE tenant_id = %s::uuid AND estado <> 'aberta'
          AND resolvido_at IS NOT NULL AND resolvido_at < %s""",
    """DELETE FROM platform.events_dlq
        WHERE tenant_id = %s::uuid AND estado <> 'aberta'
          AND resolvido_at IS NOT NULL AND resolvido_at < %s""",
    antes=(CAMINHO_APROVACOES,),
)

CAMINHO_QUARENTENA: Final = Caminho(
    "platform.unrouted_events",
    "",
    "SELECT count(*) FROM platform.unrouted_events WHERE recebido_at < %s",
    "DELETE FROM platform.unrouted_events WHERE recebido_at < %s",
    global_=True,
)

#: **O fecho da conversa**, que o bloco manda definir no PR: o mais tardio de
#: `window_expires_at` (a janela de 24 h do canal, que fecha sozinha) e
#: `last_human_activity_at` (o humano do HND). Um contacto com varias conversas
#: so sai quando **todas** fecharam antes do limite (`max`), e um sem conversa
#: nenhuma nao sai — sem fecho, os 90 dias nao tem inicio.
CAMINHO_MENSAGENS: Final = Caminho(
    "platform.outbound_messages",
    """SELECT DISTINCT tenant_id FROM platform.outbound_messages
        WHERE created_at < %s""",
    """SELECT count(*) FROM platform.outbound_messages o
        WHERE o.tenant_id = %s::uuid AND o.created_at < %s
          AND NOT (o.contact_id = ANY(%s::uuid[]))
          AND o.contact_id IN (
                SELECT c.contact_id FROM platform.conversations c
                 WHERE c.tenant_id = %s::uuid
                 GROUP BY c.contact_id
                HAVING max(greatest(c.window_expires_at, c.last_human_activity_at)) < %s)""",
    """DELETE FROM platform.outbound_messages o
        WHERE o.tenant_id = %s::uuid AND o.created_at < %s
          AND NOT (o.contact_id = ANY(%s::uuid[]))
          AND o.contact_id IN (
                SELECT c.contact_id FROM platform.conversations c
                 WHERE c.tenant_id = %s::uuid
                 GROUP BY c.contact_id
                HAVING max(greatest(c.window_expires_at, c.last_human_activity_at)) < %s)""",
    com_contacto=True,
)

#: Classe -> caminhos, pela ordem de execucao.
CAMINHOS: Final[Mapping[str, tuple[Caminho, ...]]] = {
    "conversas": (CAMINHO_MENSAGENS,),
    "events_outbox": (CAMINHO_OUTBOX,),
    "events_consumed": (CAMINHO_CONSUMIDOS,),
    "events_dlq": (CAMINHO_DLQ,),
    "entrada_em_quarentena": (CAMINHO_QUARENTENA,),
}

# ---------------------------------------------------------------- objectos

SQL_MIDIA_TENANTS: Final = """
  SELECT DISTINCT tenant_id FROM platform.media_assets
   WHERE retain_until IS NOT NULL AND retain_until <= %s
"""
SQL_MIDIA_VENCIDA: Final = """
  SELECT asset_id, storage_ref, size FROM platform.media_assets
   WHERE tenant_id = %s::uuid AND retain_until IS NOT NULL AND retain_until <= %s
     AND NOT (contact_id = ANY(%s::uuid[]))
   ORDER BY asset_id
"""
SQL_MIDIA_APAGAR: Final = """
  DELETE FROM platform.media_assets
   WHERE tenant_id = %s::uuid AND asset_id = ANY(%s::uuid[])
"""

#: A verificacao nocturna do criterio 3: audio acima do alvo (24 h) e acima do
#: maximo (72 h), fora dos holds. Conta da criacao, como o `retain_until`.
SQL_AUDIO_EM_VIOLACAO: Final = """
  SELECT count(*) FILTER (WHERE criado_at < %s),
         count(*) FILTER (WHERE criado_at < %s)
    FROM platform.media_assets
   WHERE classe = 'media_audio'
     AND NOT (tenant_id = ANY(%s::uuid[]))
     AND NOT (contact_id = ANY(%s::uuid[]))
"""

# ---------------------------------------------------------------- particoes


@dataclass(frozen=True)
class Particionada:
    """Uma tabela particionada por mes. O nome e a coluna sao constantes."""

    tabela: str
    coluna: str

    @property
    def nome_curto(self) -> str:
        return self.tabela.split(".", 1)[1]


PARTICIONADAS: Final[Mapping[str, Particionada]] = {
    "events_log": Particionada("platform.events_log", "ocorrido_em"),
    "llm_call_log": Particionada("dat.llm_call_log", "ts"),
}



class Particoes(Protocol):
    """Quem cria e larga uma particao mensal: o dono da tabela.

    A implementacao e o `db/particoes.py`, com a ligacao do `kamba_migrator`.
    O `kamba_batch` nao e dono, e uma funcao `SECURITY DEFINER` que crie tabelas
    por DDL dinamico e o que o *gate* 3b recusa por desenho.
    """

    def criar(self, tabela: str, mes: date) -> None: ...

    def largar(self, tabela: str, mes: date) -> None: ...

SQL_PARTICOES: Final = """
  SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
   WHERE i.inhparent = %s::regclass ORDER BY 1
"""

#: As contagens de uma particao, **pelo pai** e com o intervalo, como `kamba_batch`:
#: o dono (quem larga) esta sujeito ao `FORCE` e nao ve linha nenhuma — contar com ele
#: dava sempre zero (o `db/rls.py` mediu-o na `0027`).
SQL_CONTAR_MES: Final = {
    "events_log": """
      SELECT count(*), count(*) FILTER (WHERE tenant_id = ANY(%s::uuid[]))
        FROM platform.events_log WHERE ocorrido_em >= %s AND ocorrido_em < %s""",
    "llm_call_log": """
      SELECT count(*), count(*) FILTER (WHERE tenant_id = ANY(%s::uuid[]))
        FROM dat.llm_call_log WHERE ts >= %s AND ts < %s""",
}

# ------------------------------------------------------------------- fiscal

#: A coluna de inicio de cada tabela fiscal. So se le em dry-run.
COLUNA_FISCAL: Final[Mapping[str, str]] = {
    "platform.orders_mirror": "criado_at",
    "platform.order_state_log": "em",
    "platform.order_intents": "criado_at",
    "platform.order_reconciliation_issues": "aberta_at",
    "platform.stock_reservations": "criado_at",
    "platform.price_quotes": "criado_at",
    "platform.payment_events": "ocorrido_at",
    "platform.payment_charges": "criado_at",
    "platform.payment_callbacks_inbox": "recebido_at",
    "platform.manual_confirmations": "criado_at",
    "platform.refund_cases": "criado_at",
    "platform.billing_ops_approvals": "criado_at",
}


def sql_contar_fiscal(tabela: str) -> str:
    """A contagem de dry-run de uma tabela fiscal. Nome e coluna sao constantes."""
    return f"SELECT count(*) FROM {tabela} WHERE {COLUNA_FISCAL[tabela]} < %s"


# --------------------------------------------------------------- a execucao


@dataclass(frozen=True)
class Alargamento:
    """O alargamento por PME da classe `conversas`, com a justificacao."""

    prazo: Prazo
    justificacao: str

    def __post_init__(self) -> None:
        if not self.justificacao.strip():
            raise politica.PoliticaInvalida("um alargamento sem justificacao nao se regista")


@dataclass(frozen=True)
class Execucao:
    """O que uma execucao precisa. `agora` vem de quem chama (relogio simulado)."""

    abrir_ligacao: AbrirLigacao
    agora: datetime
    dry_run: bool = False
    anos_fiscais: int | None = None
    storage: StorageProvider | None = None
    alargamentos: Mapping[str, Alargamento] = field(default_factory=dict)
    delegados: Mapping[str, Callable[[Any, datetime], int]] = field(default_factory=dict)
    particoes: Particoes | None = None
    holds_externos: hold.Holds | None = None
    politica: tuple[Classe, ...] = politica.POLITICA

    @property
    def modo(self) -> str:
        return purge_log.MODO_DRY_RUN if self.dry_run else purge_log.MODO_EFECTIVA


@dataclass
class Relatorio:
    execucao_id: str
    registos: list[purge_log.Registo] = field(default_factory=list)

    @property
    def falhas(self) -> list[purge_log.Registo]:
        return [r for r in self.registos if r.resultado == purge_log.RESULTADO_FALHOU]

    @property
    def sev2(self) -> bool:
        """Uma unidade que falhou e alerta Sev2 (criterio 5)."""
        return bool(self.falhas)

    def linhas(self, classe: str | None = None) -> int:
        return sum(r.linhas for r in self.registos if classe in (None, r.classe))


class PapelSemBypass(RuntimeError):
    """A ligacao do lote nao contorna a RLS: os holds liam-se vazios."""


class PurgaFalhou(RuntimeError):
    """Pelo menos uma unidade falhou. **Alerta Sev2.** Sem conteudo na mensagem."""


def exigir_sem_falhas(relatorio: Relatorio) -> None:
    if relatorio.sev2:
        unidades = sorted({f"{r.classe}/{r.tabela}" for r in relatorio.falhas})
        raise PurgaFalhou(
            f"Sev2: {len(relatorio.falhas)} unidade(s) de purga falharam "
            f"({', '.join(unidades)}); execucao {relatorio.execucao_id}"
        )


class _Corrida:
    """O estado de uma execucao. Nao se reutiliza."""

    def __init__(self, execucao: Execucao) -> None:
        if execucao.agora.tzinfo is None:
            raise politica.PoliticaInvalida("um instante sem fuso nao e um instante")
        politica.validar(execucao.politica)
        self.x = execucao
        self.relatorio = Relatorio(str(uuid.uuid4()))

    # -- as transaccoes

    def _tx(self, classe: str, trabalho: Callable[[Any], Any]) -> Any:
        ligacao = self.x.abrir_ligacao()
        try:
            with tenant_guard.tx_batch(ligacao, f"retencao_{classe}") as cursor:
                return trabalho(cursor)
        finally:
            ligacao.close()

    def _registo(self, c: Classe, tabela: str, tenant: str | None, resultado: str,
                 motivo: str | None = None, linhas: int = 0, objectos: int = 0,
                 janela_ate: datetime | None = None) -> purge_log.Registo:
        return purge_log.Registo(
            self.relatorio.execucao_id, c.nome, tabela,
            None if tenant is None else str(tenant), self.x.modo, resultado, motivo,
            linhas, objectos, janela_ate, politica.VERSAO_DA_POLITICA, self.x.agora,
        )

    def _anotar(self, c: Classe, tabela: str, tenant: str | None, resultado: str,
                motivo: str, janela_ate: datetime | None = None) -> None:
        """Uma linha sem eliminacao, na sua propria transaccao."""
        registo = self._registo(c, tabela, tenant, resultado, motivo, janela_ate=janela_ate)
        self._tx(c.nome, lambda cur: purge_log.escrever(cur, registo))
        self.relatorio.registos.append(registo)

    def _unidade(self, c: Classe, tabela: str, tenant: str | None,
                 janela_ate: datetime | None,
                 trabalho: Callable[[Any], Sequence[tuple[str, int, int]]]) -> None:
        """Corre `trabalho` e escreve as linhas dele na mesma transaccao.

        `trabalho` devolve `(tabela, linhas, objectos)` por tabela tocada. Se
        levanta, a transaccao reverte e fica uma linha `falhou`.
        """
        def corpo(cursor: Any) -> list[purge_log.Registo]:
            registos = [
                self._registo(c, t, tenant, purge_log.RESULTADO_OK, None, n, o, janela_ate)
                for t, n, o in trabalho(cursor)
            ]
            for registo in registos:
                purge_log.escrever(cursor, registo)
            return registos

        try:
            self.relatorio.registos.extend(self._tx(c.nome, corpo))
        except _Retida as retida:
            self._anotar(c, tabela, tenant, purge_log.RESULTADO_RETIDA,
                         retida.motivo, janela_ate)
        except Exception:
            self._anotar(c, tabela, tenant, purge_log.RESULTADO_FALHOU,
                         purge_log.MOTIVO_ERRO, janela_ate)

    def _holds(self, cursor: Any) -> hold.Holds:
        """Os holds de agora, na transaccao de quem pergunta, mais os externos."""
        lidos = hold.ler(cursor)
        return lidos if self.x.holds_externos is None else lidos.unir(self.x.holds_externos)

    # -- a execucao

    def correr(self) -> Relatorio:
        sessao = f"{politica.VERSAO_DA_POLITICA}|{self.x.modo}".encode()

        def abrir(cursor: Any) -> None:
            cursor.execute(SQL_PAPEL)
            linha = cursor.fetchone()
            if not linha or linha[0] is not True:
                raise PapelSemBypass(
                    "a ligacao do lote nao tem BYPASSRLS: os holds e as linhas "
                    "retidas liam-se vazios, e a purga avancava sobre eles"
                )
            cursor.execute(SQL_SESSAO, (ACTOR_DO_LOTE, self.relatorio.execucao_id, sessao))

        self._tx("sessao", abrir)
        for c in self.x.politica:
            if c.mecanismo == politica.APAGAR:
                self._apagar(c)
            elif c.mecanismo == politica.TTL_STO:
                self._objectos(c)
            elif c.mecanismo == politica.LARGAR_PARTICAO:
                self._particoes(c)
            elif c.mecanismo == politica.FISCAL:
                self._fiscal(c)
            elif c.mecanismo == politica.DELEGADO:
                self._delegado(c)
        return self.relatorio

    # -- apagar

    def _apagar(self, c: Classe) -> None:
        caminhos = CAMINHOS.get(c.nome, ())
        cobertas = {a.tabela for k in caminhos for a in (k, *k.antes)}
        for t in c.tabelas:
            if t.nome not in cobertas:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_SEM_CAMINHO)
        for caminho in caminhos:
            if caminho.global_:
                self._apagar_tenant(c, caminho, None)
                continue
            limite_mais_largo = politica.limite(c, self.x.agora)
            tenants = self._tx(c.nome, lambda cur: _coluna(cur, caminho.sql_tenants,
                                                             (limite_mais_largo,)))
            for tenant in tenants:
                self._apagar_tenant(c, caminho, str(tenant))

    def _apagar_tenant(self, c: Classe, caminho: Caminho, tenant: str | None) -> None:
        # O alargamento e da PME e so vale onde a classe o admite (`maximo`). Um
        # erro de politica num tenant e uma unidade `falhou`, e nao uma
        # execucao parada: com ele a sair daqui, nenhuma classe seguinte corria
        # para tenant nenhum, todas as noites.
        alargamento = self.x.alargamentos.get(tenant) if tenant and c.maximo else None
        try:
            limite = politica.limite(
                c, self.x.agora, alargamento=alargamento.prazo if alargamento else None
            )
        except politica.PoliticaInvalida:
            self._anotar(c, caminho.tabela, tenant, purge_log.RESULTADO_FALHOU,
                         purge_log.MOTIVO_ERRO)
            return

        def trabalho(cursor: Any) -> list[tuple[str, int, int]]:
            holds = self._holds(cursor)
            if tenant is None:
                # Sem tenant nao se sabe de quem sao as linhas: qualquer hold retem.
                if holds.algum():
                    raise _Retida(purge_log.MOTIVO_HOLD_TENANT)
                retidos: list[str] = []
            else:
                if holds.do_tenant(tenant):
                    raise _Retida(purge_log.MOTIVO_HOLD_TENANT)
                retidos = sorted(holds.contactos_de(tenant))
                if retidos and not caminho.com_contacto:
                    raise _Retida(purge_log.MOTIVO_HOLD_CONTACTO)
            feito = []
            for passo in (*caminho.antes, caminho):
                parametros = passo.parametros(tenant, limite, retidos)
                if self.x.dry_run:
                    feito.append((passo.tabela, _escalar(cursor, passo.sql_contar, parametros), 0))
                else:
                    cursor.execute(passo.sql_apagar, parametros)
                    feito.append((passo.tabela, max(cursor.rowcount, 0), 0))
            return feito

        self._unidade(c, caminho.tabela, tenant, limite, trabalho)

    # -- objectos

    def _objectos(self, c: Classe) -> None:
        agora = self.x.agora
        for t in c.tabelas:
            if not t.ligada:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_SEM_CAMINHO)
        if not self.x.dry_run and self.x.storage is None:
            self._anotar(c, "platform.media_assets", None, purge_log.RESULTADO_RECUSADA,
                         purge_log.MOTIVO_SEM_CAMINHO, agora)
            return
        tenants = self._tx(c.nome, lambda cur: _coluna(cur, SQL_MIDIA_TENANTS, (agora,)))
        for tenant in (str(t) for t in tenants):
            self._unidade(c, "platform.media_assets", tenant, agora,
                          lambda cur, tenant=tenant: self._objectos_do_tenant(cur, tenant))

    def _objectos_do_tenant(self, cursor: Any, tenant: str) -> list[tuple[str, int, int]]:
        """O objecto primeiro, a linha depois.

        Pela ordem inversa, uma falha entre os dois deixava um blob sem linha —
        e a purga le a tabela, pelo que esse blob nunca mais saia (a nota do
        `downgrade` da `0012`). Por esta ordem, a falha deixa uma linha sem
        objecto, e a corrida seguinte apaga-a: o `ObjectoInexistenteError` e o
        estado que se pretende, nao um erro.
        """
        holds = self._holds(cursor)
        if holds.do_tenant(tenant):
            raise _Retida(purge_log.MOTIVO_HOLD_TENANT)
        retidos = sorted(holds.contactos_de(tenant))
        cursor.execute(SQL_MIDIA_VENCIDA, (tenant, self.x.agora, retidos))
        vencidas = cursor.fetchall()
        objectos = [(str(a), ref, size) for a, ref, size in vencidas if ref]
        if self.x.dry_run:
            return [("platform.media_assets", len(vencidas), len(objectos))]
        ctx = Ctx(tenant)
        for _, ref, size in objectos:
            try:
                self.x.storage.delete(ctx, ObjectRef(key=ref, tamanho=int(size or 0)))
            except ObjectoInexistenteError:
                pass
        cursor.execute(SQL_MIDIA_APAGAR, (tenant, [str(a) for a, _, _ in vencidas]))
        return [("platform.media_assets", max(cursor.rowcount, 0), len(objectos))]

    # -- particoes

    def _particoes(self, c: Classe) -> None:
        alvo = PARTICIONADAS.get(c.nome)
        for t in c.tabelas:
            if not t.ligada:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_SEM_CAMINHO)
        if alvo is None:
            return
        limite = politica.limite(c, self.x.agora)
        if not self.x.dry_run:
            self._criar_meses(c, alvo)
        for mes in self._meses_vencidos(c, alvo, limite):
            self._largar_mes(c, alvo, mes, limite)

    def _criar_meses(self, c: Classe, alvo: Particionada) -> None:
        """M+1 e M+2 (`06` §8). A falha e Sev2: a linha `falhou` sobe ao relatorio.

        O mes corrente **nao**: enquanto nao houver mensais, as linhas dele
        estao na `DEFAULT`, e criar a particao do mes recusava (`23514`) — um
        alarme todas as noites por uma coisa que nao e defeito. Sem gestor de
        particoes, a criacao **falha**: as linhas do mes seguinte iam para a
        `DEFAULT`, e e isso que o alerta existe para dizer.
        """
        for avanco in (1, 2):
            mes = _primeiro_do_mes(self.x.agora, avanco)
            try:
                if self.x.particoes is None:
                    raise RuntimeError("sem gestor de particoes")
                self.x.particoes.criar(alvo.tabela, mes.date())
            except Exception:
                self._anotar(c, alvo.tabela, None, purge_log.RESULTADO_FALHOU,
                             purge_log.MOTIVO_PARTICAO, mes)

    def _meses_vencidos(self, c: Classe, alvo: Particionada, limite: datetime) -> list[datetime]:
        nomes = self._tx(c.nome, lambda cur: _coluna(cur, SQL_PARTICOES, (alvo.tabela,)))
        meses = []
        for nome in nomes:
            mes = _mes_da_particao(alvo, str(nome))
            if mes is not None and _primeiro_do_mes(mes, 1) <= limite:
                meses.append(mes)
        return meses

    def _largar_mes(self, c: Classe, alvo: Particionada, mes: datetime,
                    limite: datetime) -> None:
        """Conta e verifica o hold como `kamba_batch`; larga com o dono.

        Sao duas ligacoes e nao uma, porque so o dono larga uma particao e so o
        `kamba_batch` ve as linhas de todos os tenants (o dono, com `FORCE`, ve
        zero — contar com ele dava sempre «sem hold»).
        """
        nome = f"{alvo.tabela}_{mes:%Y_%m}"

        def contar(cursor: Any) -> tuple:
            # Os holds e a contagem na mesma transaccao. Uma particao nao tem
            # `contact_id`: um contacto retido retem o mes inteiro do tenant.
            retidos = sorted(self._holds(cursor).tenants_retidos())
            return _linha(cursor, SQL_CONTAR_MES[c.nome],
                          (retidos, mes, _primeiro_do_mes(mes, 1)))

        try:
            linhas, retidas = self._tx(c.nome, contar)
        except Exception:
            self._anotar(c, nome, None, purge_log.RESULTADO_FALHOU, purge_log.MOTIVO_ERRO, limite)
            return
        if retidas:
            self._anotar(c, nome, None, purge_log.RESULTADO_RETIDA,
                         purge_log.MOTIVO_HOLD_TENANT, limite)
            return
        if not self.x.dry_run:
            if self.x.particoes is None:
                self._anotar(c, nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_SEM_CAMINHO, limite)
                return
            # shortcut: um hold aplicado entre a transaccao da contagem e o
            # `DROP` (outra ligacao, a do dono) nao e visto; a janela e a de uma
            # ida e volta a base. Reve-se quando o agendador (KAM-078) correr a
            # purga em paralelo com a aplicacao de holds.
            try:
                self.x.particoes.largar(alvo.tabela, mes.date())
            except Exception:
                self._anotar(c, nome, None, purge_log.RESULTADO_FALHOU,
                             purge_log.MOTIVO_ERRO, limite)
                return
        self._anotar_ok(c, nome, int(linhas), limite)

    # -- fiscal

    def _fiscal(self, c: Classe) -> None:
        """Sem prazo, recusa e diz porque; com prazo, conta em dry-run e recusa
        em efectiva (as tabelas sao imutaveis por *trigger*, `politica.py`)."""
        limite = politica.limite(c, self.x.agora, anos_fiscais=self.x.anos_fiscais)
        for t in c.tabelas:
            if limite is None:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_FISCAL_SEM_PRAZO)
            elif not self.x.dry_run:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_FISCAL_IMUTAVEL, limite)
            else:
                self._unidade(c, t.nome, None, limite,
                              lambda cur, nome=t.nome:
                              [(nome, _escalar(cur, sql_contar_fiscal(nome), (limite,)), 0)])

    # -- delegado

    def _delegado(self, c: Classe) -> None:
        executor = self.x.delegados.get(c.nome)
        if executor is None:
            for t in c.tabelas:
                self._anotar(c, t.nome, None, purge_log.RESULTADO_RECUSADA,
                             purge_log.MOTIVO_SEM_CAMINHO)
            return
        limite = politica.limite(c, self.x.agora)
        tabela = c.tabelas[0].nome if c.tabelas else c.nome
        holds = self._tx(c.nome, self._holds)
        if self.x.dry_run or holds.algum():
            # O delegado nao sabe de holds nem de dry-run: com um hold activo,
            # ou em dry-run, nao corre — e a leitura conservadora.
            motivo = purge_log.MOTIVO_HOLD_TENANT if not self.x.dry_run else purge_log.MOTIVO_SEM_CAMINHO
            resultado = purge_log.RESULTADO_RETIDA if not self.x.dry_run else purge_log.RESULTADO_RECUSADA
            self._anotar(c, tabela, None, resultado, motivo, limite)
            return
        ligacao = self.x.abrir_ligacao()
        try:
            n = executor(ligacao, self.x.agora)
            self._anotar_ok(c, tabela, int(n), limite)
        except Exception:
            self._anotar(c, tabela, None, purge_log.RESULTADO_FALHOU,
                         purge_log.MOTIVO_ERRO, limite)
        finally:
            ligacao.close()

    def _anotar_ok(self, c: Classe, tabela: str, linhas: int, limite: datetime | None) -> None:
        registo = self._registo(c, tabela, None, purge_log.RESULTADO_OK, None, linhas, 0, limite)
        self._tx(c.nome, lambda cur: purge_log.escrever(cur, registo))
        self.relatorio.registos.append(registo)


class _Retida(Exception):
    """Interna: a unidade viu um hold na sua transaccao. Leva o motivo."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def contar_lista(varredura: Callable[[Any, datetime], Sequence[Any]]) -> Callable[[Any, datetime], int]:
    """Adapta uma varredura que devolve a lista do que apagou (a do AGR).

    O `kamba_agr.retencao.varrer` devolve as *threads* apagadas e confirma pelo
    caminho: **nao e atomico com a linha do `purge_log`**, que vem depois, numa
    transaccao do lote. Se a varredura levantar a meio, o que ja apagou esta
    confirmado e a linha diz `falhou` — e a leitura certa, porque a unidade
    nao acabou.
    """
    return lambda ligacao, agora: len(varredura(ligacao, agora))


def _coluna(cursor: Any, sql: str, parametros: tuple) -> list[Any]:
    cursor.execute(sql, parametros)
    return [linha[0] for linha in cursor.fetchall()]


def _linha(cursor: Any, sql: str, parametros: tuple) -> tuple:
    cursor.execute(sql, parametros)
    return tuple(cursor.fetchone())


def _escalar(cursor: Any, sql: str, parametros: tuple) -> int:
    cursor.execute(sql, parametros)
    return int(cursor.fetchone()[0])


def _primeiro_do_mes(instante: datetime, avanco: int = 0) -> datetime:
    total = instante.year * 12 + instante.month - 1 + avanco
    ano, mes = divmod(total, 12)
    return datetime(ano, mes + 1, 1, tzinfo=timezone.utc)


def _mes_da_particao(alvo: Particionada, nome: str) -> datetime | None:
    """`<tabela>_aaaa_mm` -> o primeiro do mes, ou `None` (a `DEFAULT`, ou outro)."""
    prefixo = f"{alvo.nome_curto}_"
    sufixo = nome[len(prefixo):] if nome.startswith(prefixo) else ""
    partes = sufixo.split("_")
    if len(partes) != 2 or not all(p.isdigit() for p in partes) or len(partes[0]) != 4:
        return None
    ano, mes = int(partes[0]), int(partes[1])
    if not 1 <= mes <= 12:
        return None
    return datetime(ano, mes, 1, tzinfo=timezone.utc)


def executar(execucao: Execucao) -> Relatorio:
    """Uma execucao de todas as classes. Ver a nota do modulo."""
    return _Corrida(execucao).correr()


def verificar_audio(abrir_ligacao: AbrirLigacao, agora: datetime) -> tuple[int, int]:
    """A verificacao nocturna do criterio 3: `(acima_do_alvo, acima_do_maximo)`.

    O alvo e zero nos dois. Os audios retidos por hold nao contam: estao la por
    ordem legal, e nao por falha da purga.
    """
    def ler(cursor: Any) -> tuple[int, int]:
        holds = hold.ler(cursor)
        contactos = sorted({c for cs in holds.contactos.values() for c in cs})
        cursor.execute(
            SQL_AUDIO_EM_VIOLACAO,
            (agora - timedelta(hours=24), agora - timedelta(hours=72),
             sorted(holds.tenants), contactos),
        )
        alvo, maximo = cursor.fetchone()
        return int(alvo), int(maximo)

    ligacao = abrir_ligacao()
    try:
        with tenant_guard.tx_batch(ligacao, "retencao_verificar_audio") as cursor:
            return ler(cursor)
    finally:
        ligacao.close()


def reaplicar_apos_restauro(
    execucao: Execucao,
    restaurado_de: datetime,
    *,
    ledger_externo: Sequence[Any],
    holds_externos: hold.Holds,
):
    """Depois de um restauro: os titulares a reaplicar, e a purga outra vez.

    Duas coisas voltam com uma copia de `restaurado_de`, e as duas tem de sair:

    * **o que a purga ja tinha tirado** — corre-se a purga em modo efectivo com
      o `agora` de hoje. Como ela decide pelo tempo e nao pelo `purge_log`, as
      linhas que voltaram estao outra vez fora da janela e saem;
    * **os titulares apagados depois da copia** — e o *ledger* do KAM-070 quem
      os diz (`sujeitos_a_reaplicar`, com a fronteira `T' > T`). A lista volta a
      quem chama, que a entrega aos escopos: apagar um titular e dos processos
      que detem cada loja, e nao da retencao (KAM-070).

    **O *ledger* e os *holds* vem de fora da copia, e sao obrigatorios.** A base
    restaurada tem o *ledger* e o `audit_log` de `T`: todas as linhas do
    *ledger* tem `aplicado_at <= T`, pelo que lido dali o predicado devolvia
    sempre vazio, e um hold aplicado depois de `T` tinha desaparecido — a purga
    apagava dados sob retencao legal. A fonte e a exportacao fora da base (o
    *hook* do KAM-079, que a `0038` nomeia) ou o cluster de antes do restauro.
    Junta-se ao que a copia tem: um apagamento que so uma das duas fontes
    conhece continua a ser reaplicado.

    Recusa um dry-run: um restauro que so conta deixa os dados la.
    """
    if execucao.dry_run:
        raise politica.PoliticaInvalida("a reaplicacao apos restauro nao e um dry-run")
    if ledger_externo is None or holds_externos is None:
        raise politica.PoliticaInvalida(
            "a reaplicacao exige o ledger e os holds de fora da copia restaurada"
        )
    ligacao = execucao.abrir_ligacao()
    try:
        with tenant_guard.tx_batch(ligacao, "retencao_restauro") as cursor:
            da_copia = sujeitos_apagados(cursor)
    finally:
        ligacao.close()
    primeiro: dict[str, Any] = {}
    for sujeito in (*da_copia, *ledger_externo):
        anterior = primeiro.get(sujeito.contact_id)
        if anterior is None or sujeito.erased_at < anterior.erased_at:
            primeiro[sujeito.contact_id] = sujeito
    sujeitos = sujeitos_a_reaplicar(tuple(primeiro.values()), restaurado_de)
    juntos = holds_externos if execucao.holds_externos is None else (
        execucao.holds_externos.unir(holds_externos))
    return executar(replace(execucao, holds_externos=juntos)), sujeitos


def encerramento_devido(encerrado_at: datetime, agora: datetime) -> bool:
    """Se um tenant encerrado ja passou o prazo de eliminacao (criterio 9)."""
    return encerrado_at <= PRAZO_DE_ENCERRAMENTO.antes_de(agora)


__all__ = [
    "ACTOR_DO_LOTE",
    "CAMINHOS",
    "COLUNA_FISCAL",
    "PARTICIONADAS",
    "PRAZO_DE_ENCERRAMENTO",
    "SQL_AUDIO_EM_VIOLACAO",
    "SQL_CONTAR_MES",
    "SQL_MIDIA_APAGAR",
    "SQL_MIDIA_TENANTS",
    "SQL_MIDIA_VENCIDA",
    "SQL_PARTICOES",
    "SQL_PAPEL",
    "SQL_SESSAO",
    "Alargamento",
    "Caminho",
    "Execucao",
    "Particionada",
    "Particoes",
    "PapelSemBypass",
    "PurgaFalhou",
    "Relatorio",
    "contar_lista",
    "encerramento_devido",
    "executar",
    "exigir_sem_falhas",
    "reaplicar_apos_restauro",
    "sql_contar_fiscal",
    "verificar_audio",
]

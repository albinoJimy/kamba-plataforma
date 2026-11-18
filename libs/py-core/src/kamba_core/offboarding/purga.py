"""A fase `purga` do off-boarding (KAM-098, criterios 6, 7 e 10).

No D30, e so com a revogacao concluida: os dados operacionais do tenant saem
das tabelas da classe `relacao` da politica de retencao (KAM-071) que tem
caminho, cada unidade com a sua linha no `purge_log` **na mesma transaccao**
(a regra do KAM-071: a linha e a eliminacao confirmam juntas ou nao confirmam
nenhuma). As classes fiscais nao se tocam: ficam pelo prazo do CGT, que esta
**NAO VERIFICADO** (`fiscal_retention_years` sem omissao).

## O caminho, medido contra a base

`CAMINHOS_DO_ENCERRAMENTO` sao as tabelas da classe `relacao` em que o
`kamba_batch` tem `DELETE` e que nenhum gatilho recusa, pela ordem das FK (os
filhos primeiro). As `antes` de cada uma sao as que lhe apontam por FK sem
cascata e saem com ela: as mensagens, os *handoffs* e a midia de uma conversa;
o registo de qualidade de um canal. **As linhas da midia saem, e os bytes no
STO nao**: expiram pelo `retain_until` de cada objecto, e o certificado di-lo.

**O que fica de fora, e porque**, cada tabela com `recusada`/`sem_caminho` no
`purge_log` e no certificado — nunca com um `ok` que nao aconteceu:

* **os contactos** (`contacts`, `contact_endpoints`, `contact_deks`): so o
  cofre (`kamba_identity`) lhes toca, e o apagamento e o `Identidade.apagar`
  do KAM-008, em TypeScript, que apaga as DEK (o *crypto-shredding* do
  criterio 6). Com `apagar_contactos`, a purga chama-o e regista o que ele
  devolve; sem ele, ficam `sem_caminho`. Dar `DELETE` ao lote nestas tabelas
  afrouxava o desenho do cofre a partir de outro ticket;
* **o contacto do dono** (`owner_contacts`): e o canal por onde o certificado
  chega ao titular. Sai **depois** da entrega, pelo `emitir_certificado` (achado
  4 da revisao adversarial: apagado antes, o certificado nao tinha por onde ir);
* **o tenant e as contas de pagamento**: as tabelas fiscais (encomendas,
  pagamentos) apontam-nas por FK, e ficam enquanto o prazo fiscal ficar;
* **os objectos do STO** saem pelo `armazenamento`, quando a purga o recebe
  (KAM-210): cada objecto sob `t/<tenant>/` apagado, e uma linha `sto.objectos`
  no `purge_log` com a contagem em `objectos`. Sem ele, o certificado declara-os
  retidos, com o fundamento;
* **os casos de onboarding e o que deles depende** (`onboarding_case`, os
  gates, o teste, o KYC, a lista de espera), **as ingestoes do catalogo e os
  trabalhos de foto**, e os `fraud_signals`: o `kamba_batch` nao tem `DELETE`
  nelas, ou um gatilho de transicao recusa-o.

## Disputa aberta suspende a purga

Criterio 2 e adversarial (c): com um *hold* legal no tenant ou num contacto
dele (o `audit_log` do KAM-071), ou uma encomenda `em_disputa`, a fase fica
`suspensa_disputa` e **nada** sai — cada caminho fica `retida`/`hold_tenant`
no `purge_log`. A letra diz «suspende a purga dessa classe»; a leitura e a
conservadora — uma disputa sobre uma encomenda envolve o contacto, a conversa e
o canal por onde ela passou, e escolher quais ficam e decidir a disputa.
**A pergunta repete-se em cada unidade**, na transaccao dela: um *hold*
aplicado a meio da corrida para-a na unidade seguinte (achado 14).

## Reexecutar nao duplica, e um *crash* a meio retoma

Criterio 9. Cada `DELETE` e por `tenant_id`: repetir apaga zero e escreve um
`ok` com zero linhas (a corrida e auditada, nao saltada — a licao do
`purge_log`: um restauro traz as linhas de volta, e quem saltasse por ja ter
corrido nao as apagava). A fase so conclui no fim; um *crash* a meio deixa-a
`em_curso` e a corrida seguinte refaz o que faltar. **Cada corrida guarda o seu
`execucao_id`** na lista do resultado, e o certificado le-as todas: com so a
ultima, o que a primeira apagou aparecia com zero linhas (achado 7). **Duas
corridas do mesmo tenant nao correm juntas**: um trinco consultivo de sessao,
por tenant, recusa a segunda.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from .. import tenant_guard
from ..retencao import hold, politica, purge_log
from ..storage.guarda import LIMITE_MAXIMO_DE_LISTAGEM
from ..storage.port import Ctx, StorageProvider
from .contrato import (
    ACTOR,
    FaseForaDeOrdem,
    auditar,
    exigir_concluida,
    exigir_pedido_vivo,
    ler_fases,
    marcar,
)

#: A classe da politica que o encerramento purga, e o nome que vai no `purge_log`.
CLASSE: Final = "relacao"

#: O canal do titular, que sai depois da entrega do certificado.
CANAL_DO_TITULAR: Final = "platform.owner_contacts"


@dataclass(frozen=True)
class Caminho:
    """Uma tabela da classe `relacao`, e as que lhe apontam e saem antes dela."""

    tabela: str
    antes: tuple[str, ...] = ()

    @property
    def tabelas(self) -> tuple[str, ...]:
        return (*self.antes, self.tabela)


#: Pela ordem das FK: os filhos primeiro. Medido contra a base (o `kamba_batch`
#: tem `DELETE` e nenhum gatilho recusa); um ensaio confronta-o com o catalogo.
CAMINHOS_DO_ENCERRAMENTO: Final[tuple[Caminho, ...]] = (
    Caminho("platform.owner_notices"),
    Caminho("platform.handoff_accounts"),
    Caminho("platform.channel_onboarding"),
    Caminho("platform.channel_coexistence"),
    Caminho("platform.provisioning_step"),
    Caminho("platform.payment_confirmers"),
    Caminho("servicos.bookings"),
    Caminho(
        "platform.conversations",
        ("platform.outbound_messages", "platform.handoffs", "platform.media_assets"),
    ),
    Caminho("platform.tenant_channels", ("platform.channel_quality_log",)),
)

#: A unidade do STO no `purge_log`. Nao e uma tabela: e o nome da unidade, na
#: forma `<esquema>.<nome>` que o `purge_log_tabela_ck` exige, e o certificado
#: le-a como o escopo `sto`.
UNIDADE_DO_STO: Final = "sto.objectos"

#: As do cofre. Saem pelo `apagar_contactos` (o apagamento do KAM-008).
TABELAS_DOS_CONTACTOS: Final = (
    "platform.contact_endpoints",
    "platform.contact_deks",
    "platform.contacts",
)

#: Quantos objectos se listam de cada vez na eliminacao do STO: o maximo que a
#: guarda do KAM-011 aceita. A listagem **recusa** acima do limite em vez de
#: truncar (achado 1 da revisao adversarial: com 500, um tenant de 501 objectos
#: nunca se purgava).
#: shortcut: um tenant com mais de 10 000 objectos falha a unidade do STO (fica
#: `falhou` no `purge_log`, e a fase parada da o alerta); revê-se quando a porta
#: do armazenamento ganhar paginacao, ou no primeiro tenant que la chegue.
LOTE_DO_STO: Final = LIMITE_MAXIMO_DE_LISTAGEM

#: Quantas listagens a unidade do STO faz. A primeira apaga o que listou; a
#: segunda tem de vir vazia — senao alguem escreveu entretanto, e a unidade falha
#: em vez de girar.
VOLTAS_DO_STO: Final = 2

#: Quem apaga os contactos do tenant, e devolve quantos. O cofre, em producao.
ApagarContactos = Callable[[str], int]
AbrirLigacao = Callable[[], Any]

#: Uma encomenda em disputa conta como disputa aberta.
SQL_EM_DISPUTA: Final = """
  SELECT count(*) FROM platform.orders_mirror WHERE tenant_id = %s AND estado = 'em_disputa'
"""

#: Os tenants purgados, para o *ledger* de fora da copia (a exportacao do KAM-079).
SQL_PURGADOS: Final = """
  SELECT tenant_id::text, (resultado ->> 'purgado_at')::timestamptz
    FROM platform.offboarding_run
   WHERE fase = 'purga' AND estado = 'concluida'
   ORDER BY 2, 1
"""

#: O trinco de uma corrida, por tenant, de sessao (vale para as varias
#: transaccoes da corrida). `hashtextextended` e estavel entre processos.
SQL_TRANCAR: Final = "SELECT pg_try_advisory_lock(hashtextextended('offboarding_purga:' || %s, 0))"
SQL_DESTRANCAR: Final = "SELECT pg_advisory_unlock(hashtextextended('offboarding_purga:' || %s, 0))"

#: O motivo do encerramento que a reaplicacao escreve, quando a copia o trouxe
#: de volta a `ativo` ou `suspenso` (achado 10 da revisao adversarial).
MOTIVO_DA_REAPLICACAO: Final = "reaplicacao_apos_restauro"
SQL_ESTADO: Final = "SELECT estado FROM platform.tenants WHERE id = %s FOR UPDATE"
SQL_TRANSITAR: Final = "SELECT platform.transition_tenant(%s::uuid, 'encerrado', %s, %s)"
SQL_EMITIR: Final = "SELECT platform.evt_emitir(%s, %s::smallint, %s::uuid, %s, %s, %s::jsonb)"
SQL_DESLIGAR_ENTITLEMENTS: Final = (
    "UPDATE platform.entitlements SET ativo = false WHERE tenant_id = %s AND ativo"
)


def _relacao() -> tuple[str, ...]:
    return tuple(t.nome for t in politica.classe(CLASSE).tabelas)


def sem_caminho() -> tuple[str, ...]:
    """As tabelas da classe `relacao` que esta purga nao apaga, pela ordem da politica."""
    com = {c.tabela for c in CAMINHOS_DO_ENCERRAMENTO} | set(TABELAS_DOS_CONTACTOS)
    return tuple(t for t in _relacao() if t not in com)


def _em_batch(abrir: AbrirLigacao, job: str, trabalho: Callable[[Any], Any]) -> Any:
    ligacao = abrir()
    try:
        with tenant_guard.tx_batch(ligacao, job) as cursor:
            return trabalho(cursor)
    finally:
        ligacao.close()


@contextlib.contextmanager
def _trinco(abrir: AbrirLigacao, tenant_id: str) -> Iterator[None]:
    """Uma corrida de cada vez por tenant. Recusa, e nao espera."""
    ligacao = abrir()
    try:
        with tenant_guard.tx_batch(ligacao, "offboarding_trinco") as cursor:
            cursor.execute(SQL_TRANCAR, (tenant_id,))
            tomado = bool(cursor.fetchone()[0])
        if not tomado:
            raise FaseForaDeOrdem("a fase purga nao pode correr: ja ha uma corrida deste tenant")
        try:
            yield
        finally:
            with tenant_guard.tx_batch(ligacao, "offboarding_trinco") as cursor:
                cursor.execute(SQL_DESTRANCAR, (tenant_id,))
                cursor.fetchone()
    finally:
        ligacao.close()


def _disputa(cursor: Any, tenant_id: str, holds_externos: hold.Holds | None) -> dict[str, Any]:
    holds = hold.ler(cursor)
    if holds_externos is not None:
        holds = holds.unir(holds_externos)
    cursor.execute(SQL_EM_DISPUTA, (tenant_id,))
    encomendas = int(cursor.fetchone()[0])
    motivos = {
        "hold_tenant": holds.do_tenant(tenant_id),
        "hold_contacto": bool(holds.contactos_de(tenant_id)),
        "encomenda_em_disputa": encomendas > 0,
    }
    return {k: v for k, v in motivos.items() if v}


class _Suspensa(Exception):
    def __init__(self, motivos: dict[str, Any]) -> None:
        super().__init__("disputa")
        self.motivos = motivos


class _Corrida:
    def __init__(self, abrir: AbrirLigacao, tenant_id: str, agora: datetime,
                 holds_externos: hold.Holds | None) -> None:
        self.abrir = abrir
        self.tenant_id = tenant_id
        self.agora = agora
        self.holds_externos = holds_externos
        self.execucao_id = str(uuid.uuid4())
        self.registos: list[purge_log.Registo] = []
        self.suspensa: dict[str, Any] = {}

    def registo(self, tabela: str, resultado: str, motivo: str | None = None, linhas: int = 0,
                objectos: int = 0):
        return purge_log.Registo(
            self.execucao_id, CLASSE, tabela, self.tenant_id, purge_log.MODO_EFECTIVA,
            resultado, motivo, linhas, objectos, None, politica.VERSAO_DA_POLITICA, self.agora,
        )

    def anotar(self, cursor: Any, tabela: str, resultado: str, motivo: str) -> None:
        r = self.registo(tabela, resultado, motivo)
        purge_log.escrever(cursor, r)
        self.registos.append(r)

    def reter(self, cursor: Any) -> None:
        for c in CAMINHOS_DO_ENCERRAMENTO:
            self.anotar(cursor, c.tabela, purge_log.RESULTADO_RETIDA, purge_log.MOTIVO_HOLD_TENANT)

    def apagar(self, caminho: Caminho) -> None:
        """Uma unidade: a pergunta da disputa, os `DELETE` e o `purge_log`, numa transaccao."""
        def corpo(cursor: Any) -> list[purge_log.Registo]:
            disputa = _disputa(cursor, self.tenant_id, self.holds_externos)
            if disputa:
                raise _Suspensa(disputa)
            feitos = []
            for tabela in caminho.tabelas:
                cursor.execute(f"DELETE FROM {tabela} WHERE tenant_id = %s", (self.tenant_id,))
                r = self.registo(tabela, purge_log.RESULTADO_OK, linhas=max(cursor.rowcount, 0))
                purge_log.escrever(cursor, r)
                feitos.append(r)
            return feitos

        try:
            self.registos.extend(_em_batch(self.abrir, "offboarding_purga", corpo))
        except _Suspensa as suspensa:
            self.suspensa = suspensa.motivos
            _em_batch(self.abrir, "offboarding_purga", self.reter)
        except Exception:  # noqa: BLE001 — uma unidade que falha fica escrita, e a fase nao conclui
            _em_batch(self.abrir, "offboarding_purga", lambda cur: self.anotar(
                cur, caminho.tabela, purge_log.RESULTADO_FALHOU, purge_log.MOTIVO_ERRO))

    def contactos(self, apagar_contactos: ApagarContactos | None) -> None:
        if apagar_contactos is None:
            _em_batch(self.abrir, "offboarding_purga", lambda cur: [
                self.anotar(cur, t, purge_log.RESULTADO_RECUSADA, purge_log.MOTIVO_SEM_CAMINHO)
                for t in TABELAS_DOS_CONTACTOS
            ])
            return
        try:
            n = apagar_contactos(self.tenant_id)
        except Exception:  # noqa: BLE001
            _em_batch(self.abrir, "offboarding_purga", lambda cur: self.anotar(
                cur, "platform.contacts", purge_log.RESULTADO_FALHOU, purge_log.MOTIVO_ERRO))
            return

        def corpo(cursor: Any) -> None:
            r = self.registo("platform.contacts", purge_log.RESULTADO_OK, linhas=max(int(n), 0))
            purge_log.escrever(cursor, r)
            self.registos.append(r)

        _em_batch(self.abrir, "offboarding_purga", corpo)

    def sto(self, armazenamento: StorageProvider | None) -> None:
        """Os objectos do tenant no STO: a pergunta da disputa, os `delete` e o `purge_log`.

        A pergunta da disputa vem antes, numa transaccao; os `delete` correm fora
        dela (o STO nao entra numa transaccao da base) e sao idempotentes; a linha
        do `purge_log` vem depois, com a contagem. Repete-se a listagem ate vir
        vazia: o `list` recusa acima do limite em vez de truncar, e cada volta
        apaga o que listou. Um *crash* a meio deixa a fase por concluir, e a
        corrida seguinte apaga o resto.
        """
        if armazenamento is None:
            return
        disputa = _em_batch(self.abrir, "offboarding_purga",
                            lambda cur: _disputa(cur, self.tenant_id, self.holds_externos))
        if disputa:
            self.suspensa = disputa
            _em_batch(self.abrir, "offboarding_purga", lambda cur: self.anotar(
                cur, UNIDADE_DO_STO, purge_log.RESULTADO_RETIDA, purge_log.MOTIVO_HOLD_TENANT))
            return
        ctx = Ctx(self.tenant_id)
        apagados = 0
        try:
            for _ in range(VOLTAS_DO_STO):
                refs = list(armazenamento.list(ctx, f"t/{self.tenant_id}/", limite=LOTE_DO_STO))
                if not refs:
                    break
                for ref in refs:
                    armazenamento.delete(ctx, ref)
                    apagados += 1
            else:
                raise RuntimeError("o armazenamento continua com objectos do tenant")
        except Exception:  # noqa: BLE001 — a unidade que falha fica escrita, e a fase nao conclui
            def falhou(cursor: Any) -> None:
                # **O que saiu antes da falha fica escrito** (achado 4): o
                # `purge_log_so_ok_apaga_ck` nao deixa uma linha `falhou` contar
                # objectos, e sem a linha `ok` estes nao apareciam em lado nenhum.
                if apagados:
                    r = self.registo(UNIDADE_DO_STO, purge_log.RESULTADO_OK, objectos=apagados)
                    purge_log.escrever(cursor, r)
                    self.registos.append(r)
                self.anotar(cursor, UNIDADE_DO_STO, purge_log.RESULTADO_FALHOU, purge_log.MOTIVO_ERRO)

            _em_batch(self.abrir, "offboarding_purga", falhou)
            return

        def corpo(cursor: Any) -> None:
            r = self.registo(UNIDADE_DO_STO, purge_log.RESULTADO_OK, objectos=apagados)
            purge_log.escrever(cursor, r)
            self.registos.append(r)

        _em_batch(self.abrir, "offboarding_purga", corpo)

    def apagar_tudo(self, apagar_contactos: ApagarContactos | None,
                    armazenamento: StorageProvider | None = None) -> None:
        for caminho in CAMINHOS_DO_ENCERRAMENTO:
            self.apagar(caminho)
            if self.suspensa:
                return
        self.sto(armazenamento)
        if self.suspensa:
            return
        self.contactos(apagar_contactos)
        _em_batch(self.abrir, "offboarding_purga", lambda cur: [
            self.anotar(cur, t, purge_log.RESULTADO_RECUSADA, purge_log.MOTIVO_SEM_CAMINHO)
            for t in sem_caminho()
        ])

    @property
    def falhas(self) -> list[str]:
        return [r.tabela for r in self.registos if r.resultado == purge_log.RESULTADO_FALHOU]

    def resumo(self, anteriores: Sequence[str] = ()) -> dict[str, Any]:
        apagadas: dict[str, int] = {}
        for r in self.registos:
            if r.resultado == purge_log.RESULTADO_OK:
                apagadas[r.tabela] = apagadas.get(r.tabela, 0) + r.linhas + r.objectos
        return {
            "execucao_id": self.execucao_id,
            "execucoes": [*anteriores, self.execucao_id],
            "apagadas": apagadas,
            "retidas": sorted({r.tabela for r in self.registos
                               if r.resultado == purge_log.RESULTADO_RECUSADA}),
            "falhas": sorted(set(self.falhas)),
        }


def purgar(
    abrir_batch: AbrirLigacao,
    tenant_id: str,
    agora: datetime,
    *,
    apagar_contactos: ApagarContactos | None = None,
    holds_externos: hold.Holds | None = None,
    armazenamento: StorageProvider | None = None,
) -> dict[str, Any]:
    """A fase `purga`. Devolve o `resultado` que gravou (ou o que ja la estava).

    Com o `armazenamento` (KAM-210), os objectos do tenant no STO saem tambem.
    """
    tenant_id = tenant_guard.normalizar_tenant(tenant_id)
    with _trinco(abrir_batch, tenant_id):
        return _purgar(abrir_batch, tenant_id, agora, apagar_contactos, holds_externos, armazenamento)


def _purgar(abrir_batch, tenant_id, agora, apagar_contactos, holds_externos,
            armazenamento=None) -> dict[str, Any]:
    def antes(cursor: Any) -> tuple[dict[str, Any] | None, list[str]]:
        fases = ler_fases(cursor, tenant_id)
        exigir_pedido_vivo(fases, "purga")
        exigir_concluida(fases, "revogacao", "purga")
        purga = fases["purga"]
        if purga.estado == "concluida":
            return {"ja": dict(purga.resultado)}, []
        if agora < purga.prazo_at:
            raise FaseForaDeOrdem("a fase purga nao pode correr: antes do D30")
        anteriores = list(purga.resultado.get("execucoes", []))
        marcar(cursor, tenant_id, "purga", "em_curso", dict(purga.resultado))
        return None, anteriores

    feito, anteriores = _em_batch(abrir_batch, "offboarding_purga", antes)
    if feito is not None:
        return feito["ja"]

    corrida = _Corrida(abrir_batch, tenant_id, agora, holds_externos)
    corrida.apagar_tudo(apagar_contactos, armazenamento)
    if corrida.suspensa:
        resultado = {"disputa": sorted(corrida.suspensa), "verificado_at": agora.isoformat(),
                     "execucoes": [*anteriores, corrida.execucao_id]}
        estado, resumo = "suspensa_disputa", f"suspensa:{','.join(sorted(corrida.suspensa))}"
    else:
        resultado = {**corrida.resumo(anteriores), "purgado_at": agora.isoformat()}
        estado = "falhada" if corrida.falhas else "concluida"
        resumo = f"{estado}:{corrida.execucao_id}"

    def depois(cursor: Any) -> None:
        marcar(cursor, tenant_id, "purga", estado, resultado)
        auditar(cursor, tenant_id, "purga", resumo)

    _em_batch(abrir_batch, "offboarding_purga", depois)
    return resultado


def tenants_purgados(cursor: Any) -> list[tuple[str, datetime]]:
    """Os tenants purgados e quando. E o que se exporta para fora da copia."""
    cursor.execute(SQL_PURGADOS)
    return [(str(t), em) for t, em in cursor.fetchall()]


def _encerrar_o_restaurado(cursor: Any, tenant_id: str) -> str:
    """Uma copia de antes do encerramento traz o tenant `ativo`: encerra-o outra vez.

    Pela porta do KAM-092, com o evento do encerramento e os entitlements
    desligados. De `restrito` nao ha aresta para `encerrado`: fica, e devolve-se
    o estado para quem chama o tratar.
    """
    cursor.execute(tenant_guard.SQL_DEFINIR_CONTEXTO, (tenant_id,))
    cursor.fetchone()
    cursor.execute(SQL_ESTADO, (tenant_id,))
    linha = cursor.fetchone()
    estado = str(linha[0]) if linha else "inexistente"
    if estado in ("ativo", "suspenso"):
        cursor.execute(SQL_TRANSITAR, (tenant_id, MOTIVO_DA_REAPLICACAO, ACTOR))
        if cursor.fetchone()[0] is True:
            cursor.execute(SQL_EMITIR, ("tenant.closed", 1, tenant_id, "tenant", tenant_id,
                                        json.dumps({"motivo": MOTIVO_DA_REAPLICACAO})))
            cursor.fetchone()
            estado = "encerrado"
    cursor.execute(SQL_DESLIGAR_ENTITLEMENTS, (tenant_id,))
    return estado


def reaplicar_apos_restauro(
    abrir_batch: AbrirLigacao,
    restaurado_de: datetime,
    agora: datetime,
    *,
    purgados_externos: Sequence[tuple[str, datetime]],
    holds_externos: hold.Holds,
    apagar_contactos: ApagarContactos | None = None,
) -> list[str]:
    """Depois de um restauro: volta a apagar os tenants purgados depois da copia (criterio 10).

    A copia restaurada e de `restaurado_de`. Um tenant purgado **depois** dela
    (`purgado_at > restaurado_de`, a fronteira do KAM-070 e do KAM-079) voltou
    com os dados dentro, e a base restaurada diz que a purga dele ainda nao
    correu — pelo que **a lista vem de fora da copia**, e e obrigatoria: lida da
    base restaurada, estava vazia de todos os que importam. E os *holds* tambem
    vem de fora, pela razao do `retencao.jobs.reaplicar_apos_restauro`: um hold
    aplicado depois da copia desapareceu com o restauro.

    Corre os mesmos caminhos da purga, com o `purge_log`; **e se a copia for de
    antes do encerramento**, o tenant voltou `ativo`, com os entitlements
    ligados: encerra-o outra vez pela porta do KAM-092, com o evento, e desliga
    os entitlements (achado 10 da revisao adversarial). Marca a fase `concluida`
    se a copia a tiver. Devolve os tenants reapagados. Um tenant em disputa nao
    se reapaga: fica para quando a disputa fechar.
    """
    if purgados_externos is None or holds_externos is None:
        raise ValueError("a reaplicacao exige a lista de purgados e os holds de fora da copia")
    reapagados: list[str] = []
    for tenant, purgado_at in sorted(purgados_externos, key=lambda p: (p[1], p[0])):
        if purgado_at <= restaurado_de:
            continue
        tenant = tenant_guard.normalizar_tenant(tenant)
        disputa = _em_batch(abrir_batch, "offboarding_restauro",
                            lambda cur, t=tenant: _disputa(cur, t, holds_externos))
        if disputa:
            continue
        with _trinco(abrir_batch, tenant):
            corrida = _Corrida(abrir_batch, tenant, agora, holds_externos)
            corrida.apagar_tudo(apagar_contactos)
            resultado = {**corrida.resumo(), "purgado_at": purgado_at.isoformat(),
                         "reaplicado_at": agora.isoformat()}

            def depois(cursor: Any, t: str = tenant, r: dict[str, Any] = resultado,
                       falhou: bool = bool(corrida.falhas)) -> None:
                r["estado_do_tenant"] = _encerrar_o_restaurado(cursor, t)
                marcar(cursor, t, "purga", "falhada" if falhou else "concluida", r)
                auditar(cursor, t, "purga", f"reaplicada:{r['execucao_id']}")

            _em_batch(abrir_batch, "offboarding_restauro", depois)
        reapagados.append(tenant)
    return reapagados


__all__ = [
    "CAMINHOS_DO_ENCERRAMENTO",
    "CANAL_DO_TITULAR",
    "CLASSE",
    "Caminho",
    "MOTIVO_DA_REAPLICACAO",
    "TABELAS_DOS_CONTACTOS",
    "UNIDADE_DO_STO",
    "purgar",
    "reaplicar_apos_restauro",
    "sem_caminho",
    "tenants_purgados",
]

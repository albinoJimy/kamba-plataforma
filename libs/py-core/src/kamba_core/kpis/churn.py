"""O *job* `churn-daily`: sinais de churn, dormentes e o orcamento LLM (KAM-117).

    from kamba_core.kpis import churn, limiares

    relatorio = churn.executar(churn.Execucao(
        abrir_ligacao=lote, agora=agora, limiares=limiares.ler(caminho),
        orcamento=porta, aviso=porta_de_aviso, piloto_inicio=date(2026, 12, 1)))

    churn.reactivar(...)          # a mesma Execucao; corre a cada minuto

## Quatro passos, e a idempotencia de cada um

1. **Os episodios** — uma transaccao do `kamba_batch`, com uma tranca
   consultiva da transaccao (duas corridas ao mesmo tempo serializam-se). Le os
   sinais que valem agora (`platform.churn_sinais`), abre os que nao tem
   episodio aberto e fecha os abertos que deixaram de valer, **numa instrucao
   cada**. O indice unico parcial da base e a rede: um `ON CONFLICT DO NOTHING`
   nunca abre dois. Repetir a corrida com o mesmo relogio nao escreve nada.
2. **Avisar** — fora do ensaio, cada dormente aberto sem `avisado_at` recebe o
   aviso ao dono pela porta `AvisoAoDono`, e a marca. **Sem porta, nada se
   avisa e nada vai a zero**: a base recusa um `orcamento_zerado_at` sem
   `avisado_at` (`churn_signal_episode_orcamento_ck`), porque o bloco diz «aviso
   ao dono 7 dias antes; depois o orcamento passa a 0». A porta e do KAM-115.
3. **Zerar** — por tenant, numa transaccao propria: um dormente **pleno** cujo
   aviso **saiu** ha pelo menos `dormente_aviso_dias`. A transaccao tranca o
   episodio, **volta a perguntar** se ha mensagens de clientes na janela (o
   passo 1 pode ter corrido minutos antes), chama a porta, marca o
   `orcamento_zerado_at` e escreve `llm.orcamento_zerado` no `audit_log`.
4. **Repor** — por tenant: actividade do dono depois da abertura, ou o episodio
   fechado com o tenant ainda `ativo` (voltaram clientes ou pedidos). Chama a
   porta, marca o `orcamento_reposto_at`, fecha o episodio e escreve
   `llm.orcamento_reposto`. **Repor corre mesmo em modo de ensaio**: e a
   direccao segura. Um episodio fechado porque o tenant saiu de `ativo` nao
   repoe: o orcamento de um suspenso fica a zero.

## A porta chama-se antes do COMMIT, e o que isso custa

Zerar chama a porta e so depois marca e audita. Se a marca ou o `COMMIT`
falharem **depois** de a porta ter zerado, o *job* chama `repor` antes de
reportar a falha: sem marca, ninguem o reporia mais tarde, e um tenant ficava a
zero sem rasto. O que fica de fora e a morte do processo entre a porta e o
`COMMIT` — ver o `shortcut` no `_zerar`.

## O modo de ensaio

Nos primeiros `modo_ensaio_dias` do Piloto (e sempre, sem `piloto_inicio`) o
*job* abre e fecha episodios, marcados `ensaio`, e **nao avisa nem zera** nada.
A lista para revisao e o `Relatorio.sinais`, e os episodios ficam na base para
o registo de calibracao. Um dormente aberto em ensaio e avisado na primeira
corrida fora dele, e so vai a zero sete dias depois.

## O tenant esta em todas as instrucoes

O `kamba_batch` tem `BYPASSRLS`: o `tenant_id` de cada instrucao e a unica
barreira entre o episodio de um tenant e o de outro.

## O que nao esta aqui

O agendador (quem chama isto a horas), a porta real do LiteLLM, a porta real do
aviso ao dono (KAM-115) e a suspensao das automacoes. Ver `docs/kpis.md` §6.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Protocol

from .limiares import Limiares
from .metricas import SINAIS, MetricasDeKpis

#: Quem abre uma ligacao DB-API com o `kamba_batch`. Uma por transaccao.
AbrirLigacao = Callable[[], Any]

#: O actor das accoes no `audit_log`.
ACTOR: Final = "kamba_batch:churn-daily"

ACCAO_ZERADO: Final = "llm.orcamento_zerado"
ACCAO_REPOSTO: Final = "llm.orcamento_reposto"

#: A tranca consultiva das corridas (um inteiro fixo, so deste *job*).
TRANCA: Final = 117_000_117

SQL_TRANCA: Final = "SELECT pg_advisory_xact_lock(%s)"

SQL_SINAIS: Final = """
  SELECT s.tenant_id::text, s.sinal, s.dormente_pleno
    FROM platform.churn_sinais(%s, %s::jsonb) s
"""

#: **Uma instrucao para todos**, e nao uma por sinal: com uma ida e volta de
#: dezenas de milissegundos ate a base, cem tenants com dois sinais cada eram
#: duzentas instrucoes, e o criterio 8 (<= 60 s) caia por latencia e nao por
#: SQL (medido: 161 s, e 20 s so neste passo). Os sinais vao como `jsonb`; o
#: tenant de cada linha e o da propria linha.
SQL_ABRIR: Final = """
  INSERT INTO platform.churn_signal_episode (tenant_id, sinal, aberto_at, ensaio)
  SELECT c.tenant_id, c.sinal, %s, %s
    FROM jsonb_to_recordset(%s::jsonb) AS c(tenant_id uuid, sinal text)
  ON CONFLICT (tenant_id, sinal) WHERE fechado_at IS NULL DO NOTHING
"""

#: Fecha os abertos que nao estao no conjunto desta corrida — incluindo os de
#: um tenant que saiu de `ativo`, que ja nao tem sinais.
SQL_FECHAR: Final = """
  UPDATE platform.churn_signal_episode e
     SET fechado_at = %s
   WHERE e.fechado_at IS NULL
     AND NOT EXISTS (
           SELECT 1 FROM jsonb_to_recordset(%s::jsonb) AS c(tenant_id uuid, sinal text)
            WHERE c.tenant_id = e.tenant_id AND c.sinal = e.sinal)
"""

#: Os dormentes abertos por avisar.
SQL_POR_AVISAR: Final = """
  SELECT e.id::text, e.tenant_id::text
    FROM platform.churn_signal_episode e
   WHERE e.sinal = 'dormente' AND e.fechado_at IS NULL AND e.avisado_at IS NULL
"""

SQL_AVISADO: Final = """
  UPDATE platform.churn_signal_episode
     SET avisado_at = %s
   WHERE id = %s AND tenant_id = %s AND avisado_at IS NULL AND fechado_at IS NULL
"""

#: Os dormentes cujo aviso **saiu** ha pelo menos `dormente_aviso_dias`.
SQL_POR_ZERAR: Final = """
  SELECT e.id::text, e.tenant_id::text
    FROM platform.churn_signal_episode e
   WHERE e.sinal = 'dormente' AND e.fechado_at IS NULL
     AND e.orcamento_zerado_at IS NULL
     AND e.avisado_at <= %s
"""

SQL_TRANCAR_EPISODIO: Final = """
  SELECT e.fechado_at, e.orcamento_zerado_at, e.orcamento_reposto_at
    FROM platform.churn_signal_episode e
   WHERE e.id = %s AND e.tenant_id = %s
   FOR UPDATE
"""

#: A guarda do criterio 5, outra vez, dentro da transaccao que zera: mensagens
#: de clientes **na janela**, entre o inicio dela e agora.
SQL_CLIENTES_NA_JANELA: Final = """
  SELECT EXISTS (SELECT 1 FROM platform.conversations c
                  WHERE c.tenant_id = %s
                    AND c.last_inbound_at > %s AND c.last_inbound_at <= %s)
"""

SQL_ZERADO: Final = """
  UPDATE platform.churn_signal_episode
     SET orcamento_zerado_at = %s
   WHERE id = %s AND tenant_id = %s AND orcamento_zerado_at IS NULL
"""

#: Por repor: com orcamento a zero e sem reposicao, e ou com actividade do dono
#: depois da abertura, ou ja fechado **com o tenant em `ativo`** (voltaram
#: clientes ou pedidos). Um episodio fechado porque o tenant saiu de `ativo`
#: (suspenso, encerrado) **nao** repoe: o orcamento fica a zero.
SQL_POR_REPOR: Final = """
  SELECT e.id::text, e.tenant_id::text
    FROM platform.churn_signal_episode e
   WHERE e.sinal = 'dormente'
     AND e.orcamento_zerado_at IS NOT NULL AND e.orcamento_reposto_at IS NULL
     AND (platform.churn_dono_at(e.tenant_id, %s) > e.aberto_at
          OR (e.fechado_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM platform.tenants t
                           WHERE t.id = e.tenant_id AND t.estado = 'ativo')))
"""

SQL_REPOSTO: Final = """
  UPDATE platform.churn_signal_episode
     SET orcamento_reposto_at = %s,
         fechado_at = coalesce(fechado_at, %s)
   WHERE id = %s AND tenant_id = %s AND orcamento_reposto_at IS NULL
"""

SQL_AUDITAR: Final = """
  SELECT platform.audit_append(
           %s, 'system', %s, %s, 'churn_signal_episode', %s, NULL, sha256(%s::bytea)
         )
"""

SQL_ACTIVACAO: Final = """
  SELECT owner_active_seconds_mediana FROM platform.v_onboarding_kpis_agregado
"""


class OrcamentoLlm(Protocol):
    """A porta do orcamento da chave virtual LiteLLM de um tenant (KAM-030).

    As duas operacoes sao **idempotentes**: zerar um orcamento a zero, ou repor
    um ja reposto, nao muda nada.
    """

    def zerar(self, tenant_id: str) -> None: ...

    def repor(self, tenant_id: str) -> None: ...


class AvisoAoDono(Protocol):
    """A porta do aviso de inactividade ao dono (KAM-115). Sem contacto aqui:
    quem a implementar resolve o canal do dono pelo tenant."""

    def avisar_dormente(self, tenant_id: str) -> None: ...


@dataclass(frozen=True)
class Execucao:
    abrir_ligacao: AbrirLigacao
    agora: datetime
    limiares: Limiares
    orcamento: OrcamentoLlm
    aviso: AvisoAoDono | None = None
    piloto_inicio: date | None = None
    metricas: MetricasDeKpis | None = None

    def __post_init__(self) -> None:
        if self.agora.tzinfo is None:
            raise ValueError("o relogio do job tem de ter fuso (UTC)")

    @property
    def ensaio(self) -> bool:
        """Em ensaio sem inicio do Piloto, ou nos primeiros N dias dele."""
        if self.piloto_inicio is None:
            return True
        fim = datetime.combine(self.piloto_inicio, datetime.min.time(), timezone.utc)
        return self.agora < fim + timedelta(days=self.limiares.modo_ensaio_dias)


@dataclass
class Relatorio:
    ensaio: bool
    sinais: list[tuple[str, str]] = field(default_factory=list)
    abertos: int = 0
    fechados: int = 0
    avisados: list[str] = field(default_factory=list)
    zerados: list[str] = field(default_factory=list)
    repostos: list[str] = field(default_factory=list)
    poupados: list[str] = field(default_factory=list)
    falhas: list[tuple[str, str]] = field(default_factory=list)


def _tx(execucao: Execucao, trabalho: Callable[[Any], Any]) -> Any:
    ligacao = execucao.abrir_ligacao()
    try:
        cursor = ligacao.cursor()
        resultado = trabalho(cursor)
        ligacao.commit()
        return resultado
    except BaseException:
        ligacao.rollback()
        raise
    finally:
        ligacao.close()


def _corpo(accao: str, tenant: str, quando: datetime) -> str:
    """O que o `payload_hash` resume: a accao, o tenant e o instante. Sem PII."""
    return json.dumps(
        {"accao": accao, "tenant_id": tenant, "em": quando.isoformat()}, sort_keys=True
    )


def _episodios(execucao: Execucao, relatorio: Relatorio) -> dict[str, bool]:
    """O passo 1. Devolve, por tenant dormente, se e pleno."""

    def trabalho(cursor: Any) -> dict[str, bool]:
        cursor.execute(SQL_TRANCA, (TRANCA,))
        cursor.execute(
            SQL_SINAIS, (execucao.agora, json.dumps(execucao.limiares.para_sql()))
        )
        actuais: set[tuple[str, str]] = set()
        plenos: dict[str, bool] = {}
        for tenant, sinal, pleno in cursor.fetchall():
            actuais.add((tenant, sinal))
            if sinal == "dormente":
                plenos[tenant] = bool(pleno)
        conjunto = json.dumps([{"tenant_id": t, "sinal": s} for t, s in sorted(actuais)])
        cursor.execute(SQL_ABRIR, (execucao.agora, relatorio.ensaio, conjunto))
        relatorio.abertos = max(cursor.rowcount, 0)
        cursor.execute(SQL_FECHAR, (execucao.agora, conjunto))
        relatorio.fechados = max(cursor.rowcount, 0)
        relatorio.sinais = sorted(actuais)
        return plenos

    return _tx(execucao, trabalho)


def _avisar(execucao: Execucao, relatorio: Relatorio) -> None:
    """O passo 2. Sem porta, nao avisa — e por isso nada vai a zero."""
    porta = execucao.aviso
    if porta is None:
        return

    def candidatos(cursor: Any) -> list[tuple[str, str]]:
        cursor.execute(SQL_POR_AVISAR)
        return [(i, t) for i, t in cursor.fetchall()]

    for episodio, tenant in _tx(execucao, candidatos):

        def trabalho(cursor: Any, episodio: str = episodio, tenant: str = tenant) -> bool:
            cursor.execute(SQL_TRANCAR_EPISODIO, (episodio, tenant))
            linha = cursor.fetchone()
            if linha is None or linha[0] is not None:
                return False
            porta.avisar_dormente(tenant)
            cursor.execute(SQL_AVISADO, (execucao.agora, episodio, tenant))
            return cursor.rowcount > 0

        try:
            if _tx(execucao, trabalho):
                relatorio.avisados.append(tenant)
        except Exception as erro:  # noqa: BLE001 - uma falha nao para as outras
            relatorio.falhas.append((tenant, type(erro).__name__))


def _zerar(execucao: Execucao, relatorio: Relatorio, plenos: Mapping[str, bool]) -> None:
    l = execucao.limiares
    limite_do_aviso = execucao.agora - timedelta(days=l.dormente_aviso_dias)
    janela = execucao.agora - timedelta(days=l.dormente_janela_clientes_dias)

    def candidatos(cursor: Any) -> list[tuple[str, str]]:
        cursor.execute(SQL_POR_ZERAR, (limite_do_aviso,))
        return [(i, t) for i, t in cursor.fetchall() if plenos.get(t)]

    for episodio, tenant in _tx(execucao, candidatos):
        zerou = False

        def trabalho(cursor: Any, episodio: str = episodio, tenant: str = tenant) -> str:
            nonlocal zerou
            cursor.execute(SQL_TRANCAR_EPISODIO, (episodio, tenant))
            linha = cursor.fetchone()
            if linha is None or linha[0] is not None or linha[1] is not None:
                return "ja"
            cursor.execute(SQL_CLIENTES_NA_JANELA, (tenant, janela, execucao.agora))
            if cursor.fetchone()[0]:
                return "poupado"
            # shortcut: a porta antes do COMMIT, com compensacao se a marca ou o
            # COMMIT falharem; a morte do processo entre os dois deixa o
            # orcamento a zero sem marca. Reve-se quando houver porta real
            # (KAM-030): marcar a intencao numa transaccao propria antes da porta.
            execucao.orcamento.zerar(tenant)
            zerou = True
            cursor.execute(SQL_ZERADO, (execucao.agora, episodio, tenant))
            cursor.execute(
                SQL_AUDITAR,
                (tenant, ACTOR, ACCAO_ZERADO, episodio,
                 _corpo(ACCAO_ZERADO, tenant, execucao.agora)),
            )
            return "zerado"

        try:
            desfecho = _tx(execucao, trabalho)
        except Exception as erro:  # noqa: BLE001 - uma falha nao para as outras
            if zerou:
                # Sem marca ninguem o reporia: repoe ja, e reporta a falha.
                try:
                    execucao.orcamento.repor(tenant)
                except Exception as segundo:  # noqa: BLE001
                    relatorio.falhas.append((tenant, type(segundo).__name__))
            relatorio.falhas.append((tenant, type(erro).__name__))
            continue
        if desfecho == "zerado":
            relatorio.zerados.append(tenant)
        elif desfecho == "poupado":
            relatorio.poupados.append(tenant)


def _repor(execucao: Execucao, relatorio: Relatorio) -> None:
    def candidatos(cursor: Any) -> list[tuple[str, str]]:
        cursor.execute(SQL_POR_REPOR, (execucao.agora,))
        return [(i, t) for i, t in cursor.fetchall()]

    for episodio, tenant in _tx(execucao, candidatos):

        def trabalho(cursor: Any, episodio: str = episodio, tenant: str = tenant) -> bool:
            cursor.execute(SQL_TRANCAR_EPISODIO, (episodio, tenant))
            linha = cursor.fetchone()
            if linha is None or linha[1] is None or linha[2] is not None:
                return False
            execucao.orcamento.repor(tenant)
            cursor.execute(
                SQL_REPOSTO, (execucao.agora, execucao.agora, episodio, tenant)
            )
            cursor.execute(
                SQL_AUDITAR,
                (tenant, ACTOR, ACCAO_REPOSTO, episodio,
                 _corpo(ACCAO_REPOSTO, tenant, execucao.agora)),
            )
            return True

        try:
            if _tx(execucao, trabalho):
                relatorio.repostos.append(tenant)
        except Exception as erro:  # noqa: BLE001
            relatorio.falhas.append((tenant, type(erro).__name__))


def _publicar(execucao: Execucao, relatorio: Relatorio, plenos: Mapping[str, bool]) -> None:
    """As metricas. `tenants_dormentes` conta a **marca** (aviso e pleno), que e
    o que a `v_tenant_dormente` e o painel mostram — duas superficies, um
    numero."""
    if execucao.metricas is None:
        return
    contagem = {s: 0 for s in SINAIS}
    for _, sinal in relatorio.sinais:
        if sinal in contagem:
            contagem[sinal] += 1
    execucao.metricas.definir_sinais(contagem)
    execucao.metricas.definir_dormentes(len(plenos))

    def mediana(cursor: Any) -> Any:
        cursor.execute(SQL_ACTIVACAO)
        linha = cursor.fetchone()
        return None if linha is None else linha[0]

    segundos = _tx(execucao, mediana)
    execucao.metricas.definir_activacao(None if segundos is None else float(segundos) / 60)


def executar(execucao: Execucao) -> Relatorio:
    """A corrida diaria: episodios, avisar e zerar (fora do ensaio), repor, metricas."""
    relatorio = Relatorio(ensaio=execucao.ensaio)
    plenos = _episodios(execucao, relatorio)
    if not relatorio.ensaio:
        _avisar(execucao, relatorio)
        _zerar(execucao, relatorio, plenos)
    _repor(execucao, relatorio)
    _publicar(execucao, relatorio, plenos)
    return relatorio


def reactivar(execucao: Execucao) -> Relatorio:
    """So o passo 4. Barato, para correr a cada minuto (criterio 6, <= 1 min)."""
    relatorio = Relatorio(ensaio=execucao.ensaio)
    _repor(execucao, relatorio)
    return relatorio

"""Custo por conversa, reconciliacao e unit economics (KAM-081, criterios 2, 3 e 5).

    python db/h6_export.py exportar   [--n 500] [--janela-dias 90] [--cambio X | --modo M]
                                      [--mensalidade-kz 30000] [--saida <ficheiro>]
    python db/h6_export.py reconciliar --litellm <spend.json> [--desde AAAA-MM-DD] [--ate AAAA-MM-DD]
    python db/h6_export.py economia   --mes AAAA-MM --fixo-usd X [--mensalidade-kz Y]
                                      [--meta-payer pme|kamba] [--cenario misto] [--pmes N]

O nome do comando no canon e `h6-export`: e o instrumento que alimenta a H6
(custo <= 15% da mensalidade, KAM-109). A decisao da H6 nao e daqui.

## O que e uma conversa

**Mensagens do mesmo contacto, no mesmo tenant, sem pausa maior do que 24 h**
(criterio 2). Uma pausa de exactamente 24 h nao parte a conversa; uma de 24 h e
um microssegundo parte.

**A linha do tempo e a das mensagens de saida**, e isso e um limite dito: o
repositorio nao guarda a entrada mensagem a mensagem com contacto —
`platform.inbound_events` nao tem `tenant_id` nem `contact_id`, e o corpo nao se
guarda (`0008`); `conversations.last_inbound_at` guarda so a ultima. O bot
responde a cada turno (~1,2 mensagens por turno, `docs/tecnica/09` §14.1), pelo
que a saida segue a entrada de perto, mas uma conversa em que o cliente escreveu
e ninguem respondeu **nao aparece**, e uma pausa medida na saida pode ser maior
do que a real. **INDICIO**, e nao medida.

## O custo de cada conversa

* **Meta: medido.** A tarifa de cada mensagem entregue e cobravel, pela regra da
  vista (`custo.tarifa_micro_usd`), somada em micro-dolares inteiros.
* **LLM: rateado, e nao medido.** A `dat.llm_call_log` nao tem chave para uma
  conversa — tem `trace_id`, que nao e o `turn_id` nem o contacto (`0024`, nota
  do custo). O custo LLM de um tenant num dia, lido da `v_tenant_cost_daily`,
  reparte-se pelas conversas desse dia na proporcao das mensagens de saida de
  cada uma. A saida diz `"llm": "rateio_por_mensagens"` no metodo, para que
  ninguem leia o numero como medicao por conversa.
* **STT: `null`.** Nao ha registo de transcricao (KAM-036); zero era mentir.

## Sem pessoas

O `contact_id` **nao sai da base**: a consulta devolve um `dense_rank` por
`(tenant_id, contact_id)` e e por ele que se agrupa. Na saida cada conversa e um
ordinal, o tenant, o **dia** de inicio e de fim (sem hora) e numeros. O
`esquema` deste modulo — `CAMPOS_DA_CONVERSA` — e confrontado pelo ensaio com a
lista de identificadores proibidos.

## Papel

`kamba_batch`, sob `tenant_guard.tx_batch` com o *job* nomeado: a leitura e
cross-tenant e o `kamba_audit` nao tem `SELECT` na `outbound_messages`. E o
mesmo caminho do `golden_candidates.py`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Final, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import custo  # noqa: E402 — depois do `sys.path`, como o `golden_candidates.py`

SAIDA_OK: Final = 0
SAIDA_ACHADOS: Final = 1
SAIDA_ERRO: Final = 2

#: O nome do *job* para o `tx_batch`.
JOB: Final = "ops_h6_export"

#: A amostra por omissao do criterio 2.
N_POR_OMISSAO: Final = 500

#: A janela de leitura das mensagens, em dias. *Proposta*: tem de ser maior do
#: que o intervalo que as ultimas N conversas cobrem, e 90 dias chega para 500
#: conversas a partir de ~6 PMEs com o volume do §14.1. Calibra-se no Piloto.
JANELA_POR_OMISSAO: Final = 90

#: A pausa que parte uma conversa (criterio 2).
PAUSA: Final = dt.timedelta(hours=24)

#: A mensalidade de referencia, em Kz. O criterio 5 da 30-60 mil como
#: parametro; a omissao e a ponta **baixa**, que da o racio mais alto. Proposta.
MENSALIDADE_POR_OMISSAO_KZ: Final = Decimal("30000")

#: A escala do custo rateado: a do `custo_usd numeric(12,6)` da `0023`.
ESCALA_USD: Final = Decimal("0.000001")

#: Os percentis do criterio 2.
PERCENTIS: Final = (50, 90, 99)

#: As mensagens gratis por numero e por mes (CONFIRMADO, `E1` §1).
GRATIS_POR_NUMERO_MES: Final = 1000

#: As tolerancias do criterio 3. A do LLM e *proposta* no proprio criterio.
TOLERANCIA_LLM: Final = Decimal("0.02")
TOLERANCIA_META: Final = Decimal("0.01")

#: O limiar de desvio entre estimado e medido que gera um item de revisao do
#: `docs/tecnica/09` (criterio 5).
LIMIAR_DE_REVISAO: Final = Decimal("0.30")

#: As estimativas do `docs/tecnica/09` §14.3, USD por PME e por mes, para 300
#: conversas. **ESTIMATIVA**, e o `test_custo` confronta-as com o texto do doc.
ESTIMATIVAS_POR_PME_MES: Final = {
    "baixo": {"llm": Decimal("1.7"), "stt": Decimal("0.2"), "meta": Decimal("7.5")},
    "misto": {"llm": Decimal("5.5"), "stt": Decimal("0.9"), "meta": Decimal("7.5")},
    "sonnet": {"llm": Decimal("27"), "stt": Decimal("0.9"), "meta": Decimal("7.5")},
}

#: Os campos de uma conversa na saida. Lista fechada.
CAMPOS_DA_CONVERSA: Final = (
    "n",
    "tenant_id",
    "inicio_dia",
    "fim_dia",
    "mensagens",
    "custo_llm_usd",
    "custo_stt_usd",
    "custo_meta_usd",
    "custo_total_usd",
    "custo_total_aoa_minor",
)

#: Nomes que nunca podem ser campo de saida deste comando nem coluna da vista.
IDENTIFICADORES_PROIBIDOS: Final = frozenset(
    {
        "contact_id",
        "conversation_id",
        "channel_id",
        "phone",
        "telefone",
        "phone_number_id",
        "wamid",
        "turn_id",
        "trace_id",
        "idempotency_key",
        "texto",
        "body",
        "conteudo",
    }
)

#: As mensagens de saida, ja com o contacto trocado por um ordinal **na base**.
SQL_MENSAGENS: Final = """
  SELECT o.tenant_id::text,
         dense_rank() OVER (ORDER BY o.tenant_id, o.contact_id) AS contacto,
         o.created_at,
         (o.created_at AT TIME ZONE t.fuso_horario)::date AS dia,
         o.delivered_at IS NOT NULL AS entregue,
         o.pricing
    FROM platform.outbound_messages o
    JOIN platform.tenants t ON t.id = o.tenant_id
   WHERE o.created_at >= now() - make_interval(days => %s)
   ORDER BY o.tenant_id, contacto, o.created_at
"""

#: O custo LLM por tenant e dia, **da vista** — e o mesmo numero que o painel.
SQL_LLM_POR_DIA: Final = """
  SELECT tenant_id::text, dia, custo_usd
    FROM platform.v_tenant_cost_daily
   WHERE rubrica = 'llm' AND dia >= %s
"""

SQL_LLM_POR_TENANT: Final = """
  SELECT tenant_id::text, coalesce(sum(custo_usd), 0)
    FROM platform.v_tenant_cost_daily
   WHERE rubrica = 'llm' AND dia BETWEEN %s AND %s
   GROUP BY tenant_id
"""

SQL_MES: Final = """
  SELECT tenant_id::text, rubrica, coalesce(sum(custo_usd), 0)
    FROM platform.v_tenant_cost_daily
   WHERE dia >= %s AND dia < %s
   GROUP BY tenant_id, rubrica
"""


class ErroDeUso(Exception):
    """O comando nao pode correr como foi pedido."""


# --------------------------------------------------------------- conversas


@dataclass(frozen=True)
class Mensagem:
    """Uma mensagem de saida, sem nada que aponte para a pessoa."""

    tenant_id: str
    contacto: int
    instante: dt.datetime
    dia: dt.date
    entregue: bool
    pricing: dict | None


@dataclass
class Conversa:
    tenant_id: str
    contacto: int
    mensagens: list[Mensagem] = field(default_factory=list)

    @property
    def inicio(self) -> dt.datetime:
        return self.mensagens[0].instante

    @property
    def fim(self) -> dt.datetime:
        return self.mensagens[-1].instante


def segmentar(mensagens: Iterable[Mensagem], pausa: dt.timedelta = PAUSA) -> list[Conversa]:
    """Parte a linha do tempo de cada contacto em conversas.

    Uma pausa **maior** do que `pausa` abre conversa nova; igual nao abre. A
    ordem de entrada nao importa: ordena-se aqui.
    """
    ordenadas = sorted(mensagens, key=lambda m: (m.tenant_id, m.contacto, m.instante))
    conversas: list[Conversa] = []
    actual: Conversa | None = None
    for mensagem in ordenadas:
        nova = (
            actual is None
            or actual.tenant_id != mensagem.tenant_id
            or actual.contacto != mensagem.contacto
            or mensagem.instante - actual.fim > pausa
        )
        if nova:
            actual = Conversa(mensagem.tenant_id, mensagem.contacto)
            conversas.append(actual)
        actual.mensagens.append(mensagem)
    return conversas


def ultimas(conversas: list[Conversa], n: int) -> list[Conversa]:
    """As `n` conversas que acabaram mais tarde, da mais antiga para a mais recente."""
    if n <= 0:
        raise ErroDeUso("--n tem de ser positivo")
    escolhidas = sorted(conversas, key=lambda c: (c.fim, c.tenant_id, c.contacto))[-n:]
    return escolhidas


def custo_meta_micro(conversa: Conversa) -> tuple[int, int]:
    """(micro-dolares, mensagens cobraveis sem tarifa) das mensagens entregues."""
    total = 0
    sem_preco = 0
    for mensagem in conversa.mensagens:
        if not mensagem.entregue:
            continue
        tarifa = custo.tarifa_micro_usd(mensagem.pricing)
        if tarifa is None:
            sem_preco += 1
        else:
            total += tarifa
    return total, sem_preco


def ratear_llm(
    conversas: list[Conversa],
    todas: list[Conversa],
    llm_por_dia: dict[tuple[str, dt.date], Decimal],
) -> dict[int, Decimal]:
    """O custo LLM rateado de cada conversa de `conversas`, por indice.

    O denominador de um dia sao as mensagens de **todas** as conversas do tenant
    nesse dia, e nao so das escolhidas: senao a amostra pequena absorvia o custo
    do dia inteiro.
    """
    mensagens_no_dia: dict[tuple[str, dt.date], int] = {}
    for conversa in todas:
        for mensagem in conversa.mensagens:
            chave = (mensagem.tenant_id, mensagem.dia)
            mensagens_no_dia[chave] = mensagens_no_dia.get(chave, 0) + 1
    rateado: dict[int, Decimal] = {}
    for indice, conversa in enumerate(conversas):
        minhas: dict[dt.date, int] = {}
        for mensagem in conversa.mensagens:
            minhas[mensagem.dia] = minhas.get(mensagem.dia, 0) + 1
        soma = Decimal(0)
        for dia, quantas in minhas.items():
            chave = (conversa.tenant_id, dia)
            custo_do_dia = llm_por_dia.get(chave)
            if custo_do_dia is None:
                continue
            soma += custo_do_dia * quantas / mensagens_no_dia[chave]
        rateado[indice] = soma.quantize(ESCALA_USD, rounding=ROUND_HALF_EVEN)
    return rateado


def percentil(valores: list[Decimal], p: int) -> Decimal | None:
    """Percentil por **posicao mais proxima** (nearest-rank), sem interpolar.

    E um valor que existe na amostra, que e o que permite a igualdade exacta do
    criterio 2. `None` para a amostra vazia.
    """
    if not valores:
        return None
    if not 0 < p <= 100:
        raise ValueError(f"percentil fora de (0, 100]: {p}")
    ordenados = sorted(valores)
    posicao = math.ceil(p / 100 * len(ordenados))
    return ordenados[posicao - 1]


def _texto(valor: Decimal | None) -> str | None:
    return None if valor is None else format(valor, "f")


def montar_exportacao(
    todas: list[Conversa],
    llm_por_dia: dict[tuple[str, dt.date], Decimal],
    n: int,
    fx_aoa_per_usd: Decimal,
    mensalidade_kz: Decimal,
) -> dict[str, Any]:
    """A exportacao inteira, sem tocar na base. E o que o ensaio da *fixture* mede."""
    escolhidas = ultimas(todas, n)
    rateado = ratear_llm(escolhidas, todas, llm_por_dia)
    linhas: list[dict[str, Any]] = []
    totais: list[Decimal] = []
    por_mes: dict[tuple[str, str], dict[str, Any]] = {}
    sem_preco_meta = 0
    for indice, conversa in enumerate(escolhidas):
        meta_micro, sem_preco = custo_meta_micro(conversa)
        sem_preco_meta += sem_preco
        meta = Decimal(meta_micro) / custo.MICRO_USD_POR_USD
        llm = rateado[indice]
        total = llm + meta
        totais.append(total)
        linhas.append(
            {
                "n": indice + 1,
                "tenant_id": conversa.tenant_id,
                "inicio_dia": conversa.mensagens[0].dia.isoformat(),
                "fim_dia": conversa.mensagens[-1].dia.isoformat(),
                "mensagens": len(conversa.mensagens),
                "custo_llm_usd": _texto(llm),
                "custo_stt_usd": None,
                "custo_meta_usd": _texto(meta),
                "custo_total_usd": _texto(total),
                "custo_total_aoa_minor": custo.para_aoa_minor(total, fx_aoa_per_usd),
            }
        )
        chave = (conversa.tenant_id, conversa.mensagens[0].dia.strftime("%Y-%m"))
        grupo = por_mes.setdefault(chave, {"conversas": 0, "custo_usd": Decimal(0)})
        grupo["conversas"] += 1
        grupo["custo_usd"] += total

    mensalidade_minor = int(mensalidade_kz * 100)
    racios = []
    for (tenant_id, mes), grupo in sorted(por_mes.items()):
        custo_minor = custo.para_aoa_minor(grupo["custo_usd"], fx_aoa_per_usd)
        racios.append(
            {
                "tenant_id": tenant_id,
                "mes": mes,
                "conversas": grupo["conversas"],
                "custo_usd": _texto(grupo["custo_usd"]),
                "custo_aoa_minor": custo_minor,
                "racio_custo_mensalidade": _texto(
                    (Decimal(custo_minor) / mensalidade_minor).quantize(Decimal("0.000001"))
                ),
            }
        )

    return {
        "metodo": {
            "conversa": "mesmo contacto, sem pausa > 24 h, na linha do tempo das mensagens de saida",
            "llm": "rateio_por_mensagens",
            "meta": "medido_pelo_pricing",
            "stt": "sem_registo",
            "percentil": "posicao_mais_proxima",
        },
        "fx_aoa_per_usd": _texto(fx_aoa_per_usd),
        "mensalidade_aoa_minor": mensalidade_minor,
        "amostra": len(linhas),
        "pedidas": n,
        "mensagens_meta_sem_tarifa": sem_preco_meta,
        "percentis_custo_total_usd": {
            f"p{p}": _texto(percentil(totais, p)) for p in PERCENTIS
        },
        "racio_por_tenant_e_mes": racios,
        "conversas": linhas,
    }


# ----------------------------------------------------------- reconciliacao


def desvio(medido: Decimal, referencia: Decimal) -> Decimal | None:
    """|medido - referencia| / referencia. `None` quando a referencia e zero e o
    medido nao: nao ha desvio relativo a zero, ha divergencia."""
    if referencia == 0:
        return Decimal(0) if medido == 0 else None
    return abs(medido - referencia) / referencia


def reconciliar_llm(
    registo: dict[str, Decimal],
    litellm: dict[str, Decimal],
    tolerancia: Decimal = TOLERANCIA_LLM,
) -> list[str]:
    """Os tenants cujo custo em `dat.llm_call_log` diverge do *spend* do LiteLLM.

    Um tenant que so aparece de um lado e achado, nao zero do outro lado.
    """
    achados = []
    for tenant_id in sorted(set(registo) | set(litellm)):
        if tenant_id not in registo or tenant_id not in litellm:
            lado = "llm_call_log" if tenant_id not in registo else "LiteLLM"
            achados.append(f"{tenant_id}: sem linhas em {lado}")
            continue
        relativo = desvio(registo[tenant_id], litellm[tenant_id])
        if relativo is None or relativo > tolerancia:
            achados.append(
                f"{tenant_id}: llm_call_log {registo[tenant_id]} contra LiteLLM "
                f"{litellm[tenant_id]} (desvio {_texto(relativo)}, tecto {tolerancia})"
            )
    return achados


def meta_pela_tarifa(mensagens_por_categoria: dict[str, int]) -> int:
    """O custo Meta de **um numero num mes**, em micro-dolares, pela tarifa.

    Service gratis ate 1.000 e 0,004 USD depois; utility e authentication pagas
    sempre (desde 2026-10-01 tambem dentro da janela); marketing a 0,0225.
    E a estimativa contra a qual o custo medido pelo `pricing` se reconcilia.
    """
    total = 0
    for categoria, quantas in mensagens_por_categoria.items():
        tarifa = custo.TARIFAS_MICRO_USD.get(categoria)
        if tarifa is None:
            raise ValueError(f"categoria sem tarifa: {categoria!r}")
        cobradas = max(0, quantas - GRATIS_POR_NUMERO_MES) if categoria == "service" else quantas
        total += cobradas * tarifa
    return total


def reconciliar_meta(
    medido_micro: int, estimado_micro: int, tolerancia: Decimal = TOLERANCIA_META
) -> str | None:
    """`None` quando o medido esta dentro da tolerancia; o achado, se nao."""
    relativo = desvio(Decimal(medido_micro), Decimal(estimado_micro))
    if relativo is not None and relativo <= tolerancia:
        return None
    return (
        f"Meta medida {medido_micro} contra {estimado_micro} pela tarifa, em "
        f"micro-USD (desvio {_texto(relativo)}, tecto {tolerancia})"
    )


# --------------------------------------------------------- unit economics


def economia(
    custo_por_tenant: dict[str, dict[str, Decimal]],
    fixo_usd: Decimal,
    mensalidade_kz: Decimal,
    fx_aoa_per_usd: Decimal,
    meta_payer: str,
    cenario: str = "misto",
    pmes: int | None = None,
) -> dict[str, Any]:
    """O painel de unit economics como numeros (criterios 5 e 6).

    `custo_por_tenant` e `{tenant: {rubrica: usd}}` de um mes, lido da vista. O
    custo fixo e **parametro**: o doc 09 §14.4 da 470-730 USD como ESTIMATIVA, a
    substituir por cotacoes.
    """
    if meta_payer not in ("pme", "kamba"):
        raise ErroDeUso("meta_payer e pme ou kamba")
    if cenario not in ESTIMATIVAS_POR_PME_MES:
        raise ErroDeUso(f"cenario desconhecido: {cenario}")
    n = len(custo_por_tenant) if pmes is None else pmes
    if n <= 0:
        raise ErroDeUso("sem PMEs no mes: nao ha custo por PME")

    llm = sum((r.get("llm", Decimal(0)) for r in custo_por_tenant.values()), Decimal(0))
    meta = sum(
        (v for r in custo_por_tenant.values() for k, v in r.items() if k.startswith("meta_")),
        Decimal(0),
    )
    llm_por_pme = llm / n
    meta_por_pme = meta / n
    para_kamba = llm_por_pme + (meta_por_pme if meta_payer == "kamba" else Decimal(0))
    total_cliente = llm_por_pme + meta_por_pme
    fixo_por_pme = fixo_usd / n
    mensalidade_usd = mensalidade_kz / fx_aoa_per_usd
    contribuicao = mensalidade_usd - para_kamba
    equilibrio = None if contribuicao <= 0 else math.ceil(fixo_usd / contribuicao)
    margem = (mensalidade_usd - para_kamba - fixo_por_pme) / mensalidade_usd

    estimado = ESTIMATIVAS_POR_PME_MES[cenario]
    revisao = []
    for rubrica, medido in (("llm", llm_por_pme), ("meta", meta_por_pme)):
        relativo = desvio(medido, estimado[rubrica])
        if relativo is None or relativo > LIMIAR_DE_REVISAO:
            revisao.append(
                {
                    "rubrica": rubrica,
                    "estimado_usd": _texto(estimado[rubrica]),
                    "medido_usd": _texto(medido.quantize(ESCALA_USD)),
                    "desvio": _texto(None if relativo is None else relativo.quantize(Decimal("0.0001"))),
                    "item": f"rever docs/tecnica/09 §14.3, rubrica {rubrica}, cenario {cenario}",
                }
            )

    q = lambda v: _texto(v.quantize(ESCALA_USD))  # noqa: E731
    return {
        "pmes": n,
        "meta_payer": meta_payer,
        "fx_aoa_per_usd": _texto(fx_aoa_per_usd),
        "custo_fixo_por_pme_usd": q(fixo_por_pme),
        "llm_por_pme_usd": q(llm_por_pme),
        "stt_por_pme_usd": None,
        "meta_por_pme_usd": q(meta_por_pme),
        "custo_para_kamba_por_pme_usd": q(para_kamba + fixo_por_pme),
        "custo_total_cliente_por_pme_usd": q(total_cliente + fixo_por_pme),
        "mensalidade_usd": q(mensalidade_usd),
        "margem_por_mensalidade": _texto(margem.quantize(Decimal("0.0001"))),
        "ponto_de_equilibrio_pmes": equilibrio,
        "cenario_estimado": cenario,
        "itens_de_revisao": revisao,
    }


# ------------------------------------------------------------------- CLI


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(prog="h6-export", description=__doc__.split("\n")[0])
    comandos = analisador.add_subparsers(dest="comando", required=True)

    def cambio(sub: argparse.ArgumentParser) -> None:
        grupo = sub.add_mutually_exclusive_group()
        grupo.add_argument("--cambio", default=None, help="AOA por USD (omissao 913)")
        grupo.add_argument("--modo", choices=sorted(custo.MODOS_DE_CAMBIO), default=None)

    exporta = comandos.add_parser("exportar", help="as ultimas N conversas com custo")
    exporta.add_argument("--n", type=int, default=N_POR_OMISSAO)
    exporta.add_argument("--janela-dias", type=int, default=JANELA_POR_OMISSAO)
    exporta.add_argument("--mensalidade-kz", type=Decimal, default=MENSALIDADE_POR_OMISSAO_KZ)
    exporta.add_argument("--saida", type=Path, default=None)
    cambio(exporta)

    reconcilia = comandos.add_parser("reconciliar", help="llm_call_log contra o LiteLLM")
    reconcilia.add_argument("--litellm", type=Path, required=True,
                            help="JSON [{tenant_id, spend_usd}] tirado dos spend logs")
    reconcilia.add_argument("--desde", type=dt.date.fromisoformat, required=True)
    reconcilia.add_argument("--ate", type=dt.date.fromisoformat, required=True)

    eco = comandos.add_parser("economia", help="unit economics de um mes")
    eco.add_argument("--mes", required=True, help="AAAA-MM")
    eco.add_argument("--fixo-usd", type=Decimal, required=True)
    eco.add_argument("--mensalidade-kz", type=Decimal, default=MENSALIDADE_POR_OMISSAO_KZ)
    eco.add_argument("--meta-payer", choices=("pme", "kamba"), default="pme")
    eco.add_argument("--cenario", choices=sorted(ESTIMATIVAS_POR_PME_MES), default="misto")
    eco.add_argument("--pmes", type=int, default=None)
    cambio(eco)
    return analisador


def _utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def _escrever(dados: Any, saida: Path | None) -> None:
    texto = json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    if saida is None:
        sys.stdout.write(texto)
    else:
        saida.write_bytes(texto.encode("utf-8"))  # LF explicito


def _ler_litellm(caminho: Path) -> dict[str, Decimal]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    soma: dict[str, Decimal] = {}
    for linha in dados:
        tenant_id = str(linha["tenant_id"])
        soma[tenant_id] = soma.get(tenant_id, Decimal(0)) + Decimal(str(linha["spend_usd"]))
    return soma


def _correr(argumentos: argparse.Namespace, cursor: Any) -> tuple[Any, int]:
    if argumentos.comando == "exportar":
        fx = custo.cambio(argumentos.modo, argumentos.cambio)
        cursor.execute(SQL_MENSAGENS, (int(argumentos.janela_dias),))
        mensagens = [
            Mensagem(t, int(c), instante, dia, bool(entregue),
                     p if isinstance(p, dict) or p is None else json.loads(p))
            for t, c, instante, dia, entregue, p in cursor.fetchall()
        ]
        todas = segmentar(mensagens)
        desde = min((m.dia for m in mensagens), default=dt.date.today())
        cursor.execute(SQL_LLM_POR_DIA, (desde,))
        llm = {(t, d): Decimal(v) for t, d, v in cursor.fetchall() if v is not None}
        return (
            montar_exportacao(todas, llm, argumentos.n, fx, argumentos.mensalidade_kz),
            SAIDA_OK,
        )
    if argumentos.comando == "reconciliar":
        litellm = _ler_litellm(argumentos.litellm)
        cursor.execute(SQL_LLM_POR_TENANT, (argumentos.desde, argumentos.ate))
        registo = {t: Decimal(v) for t, v in cursor.fetchall()}
        achados = reconciliar_llm(registo, litellm)
        return {"achados": achados, "tenants": len(set(registo) | set(litellm))}, (
            SAIDA_ACHADOS if achados else SAIDA_OK
        )
    fx = custo.cambio(argumentos.modo, argumentos.cambio)
    inicio = dt.date.fromisoformat(f"{argumentos.mes}-01")
    fim = (inicio.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    cursor.execute(SQL_MES, (inicio, fim))
    por_tenant: dict[str, dict[str, Decimal]] = {}
    for tenant_id, rubrica, valor in cursor.fetchall():
        por_tenant.setdefault(tenant_id, {})[rubrica] = Decimal(valor)
    return (
        economia(por_tenant, argumentos.fixo_usd, argumentos.mensalidade_kz, fx,
                 argumentos.meta_payer, argumentos.cenario, argumentos.pmes),
        SAIDA_OK,
    )


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argumentos = _analisador().parse_args(argv)
    try:
        if getattr(argumentos, "cambio", None) is not None or getattr(argumentos, "modo", None):
            custo.cambio(argumentos.modo, argumentos.cambio)
    except ValueError as erro:
        print(f"h6-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    import ligacao
    import pg8000.dbapi
    from kamba_core import tenant_guard

    try:
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"h6-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    try:
        try:
            with tenant_guard.tx_batch(conexao, JOB) as cursor:
                dados, codigo = _correr(argumentos, cursor)
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            print(f"h6-export: a base recusou: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        except (ErroDeUso, ValueError, OSError, KeyError) as erro:
            print(f"h6-export: {erro}", file=sys.stderr)
            return SAIDA_ERRO
    finally:
        conexao.close()
    _escrever(dados, getattr(argumentos, "saida", None))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())

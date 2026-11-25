"""As definicoes e os limiares pre-registados de H1, H6, H8 e H9 (KAM-109).

Cada numero deste modulo tem o seu par no protocolo
(`docs/tecnica/evidencia/validacao/Piloto_Protocolo.md`), e o
`test_protocolo` le os dois e recusa a divergencia: um limiar que muda num sitio
e nao no outro e um limiar escolhido depois dos dados. Os limiares sao os de
`14` §2 e do bloco do KAM-109; as definicoes marcadas *proposta* sao do
protocolo e so valem depois de assinadas.

## Os tres estados, e a regra que os separa

`confirmada`, `refutada` e `inconclusiva` — os tres do Registo de Hipoteses. Nas
hipoteses de contagem (H1, H8) o estado decide-se pelo que **ja nao pode mudar**:

    confirmada    os sucessos ja atingem o alvo
    refutada      nem com todas as pendentes a dar certo se atinge o alvo
    inconclusiva  o resto: ha pendentes que ainda decidem

Assim um 4 de 10 com seis por decidir nao sai `refutada`, e um 5 de 10 sai
`confirmada` mesmo que haja pendentes — mais sucessos nao a desfazem.

## Os dias

O dia e o de `Africa/Luanda`, e o dia da activacao e o **dia 0**. A semana 1 sao
os dias 0 a 6, a semana 2 os dias 7 a 13. «Dia 30» e a data de activacao mais
30 dias, e uma PME tem «N dias de exposicao» quando o ultimo dia exportado e
pelo menos esse.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Final, Iterable

from .exportacao import Exportacao, Pme

CONFIRMADA: Final = "confirmada"
REFUTADA: Final = "refutada"
INCONCLUSIVA: Final = "inconclusiva"

# ----------------------------------------------------------------- limiares

#: H1: pelo menos 5 PMEs da coorte pagam depois de 30 dias (`14` §2).
H1_ALVO: Final = 5
#: H1: a coorte do Piloto (`14` §3A, Regra 4).
COORTE: Final = 10
#: H1: o dia da conversao (Regra 4: 30 dias gratuitos).
H1_DIA_DA_CONVERSAO: Final = 30
#: H1: os dias depois do dia 30 em que um pagamento ainda conta como conversao.
#: *Proposta*: um periodo mensal (31 dias) e a regua de cobranca do KAM-058
#: (D+10). O periodo e porque os ciclos **nao** alinham pela activacao: abrem no
#: `periodo_dia` da subscricao (1 a 28, `0055`), pelo que o primeiro ciclo
#: depois do dia 30 pode comecar ate um mes depois dele.
H1_JANELA_DE_PAGAMENTO_DIAS: Final = 41

#: H6: o tecto do custo sobre a mensalidade (`14` §2).
H6_TECTO: Final = Fraction(15, 100)
#: H6: a amostra minima de conversas (bloco do KAM-109).
H6_AMOSTRA_MINIMA: Final = 500

#: H8: o alvo de catalogos correctos, em 10 (`14` §2: >= 60%).
H8_ALVO: Final = 6
#: H8: a amostra de produtos por PME (todos, se tiver menos).
H8_AMOSTRA_POR_PME: Final = 20
#: H8: a fraccao de itens certos que faz um catalogo correcto. *Proposta*.
H8_ITENS_CORRECTOS: Final = Fraction(90, 100)
#: H8: a auditoria faz-se na 4.a semana (dias 21 a 27).
H8_SEMANA_DA_AUDITORIA: Final = 4

#: H9: a fraccao de activas ao dia 60 (`14` §2).
H9_LIMIAR: Final = Fraction(70, 100)
#: H9: os dias de exposicao.
H9_DIA: Final = 60
#: H9: abaixo disto, a H9 e `inconclusiva` com data de seguimento (bloco).
H9_MINIMO_DE_PMES: Final = 8
#: O indicador do dia 30, reportado a parte, sem substituir o do dia 60.
DIA_DO_INDICADOR: Final = 30

#: «Activa» (*proposta* do bloco): >= 1 accao do dono **em cada** uma das duas
#: semanas da janela, e >= 5 conversas na janela de 14 dias.
ACTIVA_JANELA_DIAS: Final = 14
ACTIVA_ACCOES_POR_SEMANA: Final = 1
ACTIVA_CONVERSAS: Final = 5

#: Carta §5: activacoes sem intervencao humana.
SELF_SERVICE_MINIMO: Final = Fraction(80, 100)


@dataclass(frozen=True)
class Resultado:
    """Uma linha para o Registo de Hipoteses: os campos de medicao, e o detalhe."""

    hipotese: str
    limiar: str
    amostra_n: int
    resultado: str
    estado: str
    detalhe: dict[str, Any]

    def como_dict(self) -> dict[str, Any]:
        return {
            "limiar": self.limiar,
            "amostra_n": self.amostra_n,
            "resultado": self.resultado,
            "estado": self.estado,
            "detalhe": self.detalhe,
        }


def estado_por_contagem(sucessos: int, pendentes: int, alvo: int) -> str:
    """O estado de uma hipotese «pelo menos `alvo` sucessos». Ver o cabecalho."""
    if min(sucessos, pendentes, alvo) < 0:
        raise ValueError("contagens negativas")
    if sucessos >= alvo:
        return CONFIRMADA
    if sucessos + pendentes < alvo:
        return REFUTADA
    return INCONCLUSIVA


def _coorte(exportacao: Exportacao) -> tuple[Pme, ...]:
    """A coorte final, recusada se tiver mais de 10: o limiar e «de 10»."""
    if len(exportacao.coorte) > COORTE:
        raise ValueError(
            f"a coorte tem {len(exportacao.coorte)} PMEs e o protocolo fixa {COORTE}: "
            "uma PME a mais tem de sair (substituida) antes de medir"
        )
    return exportacao.coorte


def _dia(pme: Pme, n: int) -> dt.date:
    assert pme.activada_em is not None
    return pme.activada_em + dt.timedelta(days=n)


# -------------------------------------------------------------- definicoes


def activa_em(pme: Pme, fim: dt.date) -> bool:
    """«Activa» na janela de 14 dias que acaba em `fim`, inclusive.

    As duas semanas sao `[fim-13, fim-7]` e `[fim-6, fim]`; cada uma tem de ter
    pelo menos uma accao do dono, e a janela inteira pelo menos 5 conversas.
    """
    inicio = fim - dt.timedelta(days=ACTIVA_JANELA_DIAS - 1)
    meio = fim - dt.timedelta(days=ACTIVA_JANELA_DIAS // 2)
    semanas = (
        pme.soma(inicio, meio, "accoes_dono"),
        pme.soma(meio + dt.timedelta(days=1), fim, "accoes_dono"),
    )
    return (
        all(s >= ACTIVA_ACCOES_POR_SEMANA for s in semanas)
        and pme.soma(inicio, fim, "conversas") >= ACTIVA_CONVERSAS
    )


def usou_na_semana_2(pme: Pme) -> bool | None:
    """Uso na semana 2 (dias 7 a 13): >= 1 conversa ou >= 1 accao do dono. *Proposta*.

    `None` se a PME nao foi activada.
    """
    if pme.activada_em is None:
        return None
    inicio, fim = _dia(pme, 7), _dia(pme, 13)
    return pme.soma(inicio, fim, "conversas") + pme.soma(inicio, fim, "accoes_dono") > 0


# ---------------------------------------------------------------------- H1


def h1(exportacao: Exportacao, mensalidade_minor: int) -> Resultado:
    """Pagantes depois de 30 dias, ao preco real, pela coorte final.

    Pagante: um ciclo pago com `valor_minor` igual a mensalidade do protocolo,
    que cubra tempo **depois** do dia 30 (o `fim`, exclusivo, depois do dia 30)
    e pago **ate ao fecho da janela** (dia 30 + 41). Pendente: sem esse ciclo e
    com a janela ainda aberta. Um pagamento depois do fecho nao conta, e e isso
    que faz de uma `refutada` uma conclusao que ja nao muda. Um ciclo pago a
    outro preco **nao conta** e sai no detalhe — um desconto nao e o preco real.
    """
    if mensalidade_minor <= 0:
        raise ValueError("a mensalidade do protocolo tem de ser positiva")
    pagantes, pendentes, nao_pagantes, outro_preco, sem_activacao = [], [], [], [], []
    coorte = _coorte(exportacao)
    for pme in coorte:
        if pme.activada_em is None:
            sem_activacao.append(pme.pme)
            pendentes.append(pme.pme)
            continue
        conversao = _dia(pme, H1_DIA_DA_CONVERSAO)
        fecho = conversao + dt.timedelta(days=H1_JANELA_DE_PAGAMENTO_DIAS)
        validos = [c for c in pme.ciclos_pagos if c.fim > conversao and c.pago_em <= fecho]
        if any(c.valor_minor == mensalidade_minor for c in validos):
            pagantes.append(pme.pme)
            continue
        if validos:
            outro_preco.append(pme.pme)
        (pendentes if exportacao.ultimo_dia < fecho else nao_pagantes).append(pme.pme)
    # Uma coorte com menos de 10 nao «tem» as que faltam como pendentes: elas
    # ainda nao existem. Contam como pendentes, porque podem entrar e pagar.
    vagas = COORTE - len(coorte)
    estado = estado_por_contagem(len(pagantes), len(pendentes) + vagas, H1_ALVO)
    return Resultado(
        hipotese="H1",
        limiar=f">= {H1_ALVO} de {COORTE} pagam apos {H1_DIA_DA_CONVERSAO} dias",
        amostra_n=len(coorte),
        resultado=f"{len(pagantes)} de {len(coorte)}",
        estado=estado,
        detalhe={
            "pagantes": pagantes,
            "pendentes": pendentes,
            "nao_pagantes": nao_pagantes,
            "pagos_a_outro_preco": outro_preco,
            "nao_activadas": sem_activacao,
            "vagas_na_coorte": vagas,
            "substituidas": [
                {"pme": p.pme, "motivo": p.saida.motivo if p.saida else None}
                for p in exportacao.substituidas
            ],
            "uso_semana_2": {p.pme: usou_na_semana_2(p) for p in coorte},
        },
    )


# ---------------------------------------------------------------------- H6


def _fraccao(texto: Any) -> Fraction:
    return Fraction(Decimal(str(texto)))


def _percentil(valores: list[Fraction], p: int) -> Fraction | None:
    """Posicao mais proxima, sem interpolar — a regra do `h6-export`."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = -(-p * len(ordenados) // 100)
    return ordenados[max(posicao, 1) - 1]


def _pct(valor: Fraction | None) -> str | None:
    return None if valor is None else f"{float(valor) * 100:.2f}%"


def _meses_completos(pme: Pme, ultimo_dia: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Os meses de calendario inteiros entre a activacao e o ultimo dia exportado."""
    if pme.activada_em is None:
        return []
    meses = []
    inicio = pme.activada_em.replace(day=1)
    if inicio < pme.activada_em:
        inicio = _mes_seguinte(inicio)
    while True:
        seguinte = _mes_seguinte(inicio)
        fim = seguinte - dt.timedelta(days=1)
        if fim > ultimo_dia:
            return meses
        meses.append((inicio, fim))
        inicio = seguinte


def _mes_seguinte(dia_1: dt.date) -> dt.date:
    return (dia_1.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def h6(exportacao: Exportacao, mensalidade_minor: int, h6_export: dict[str, Any]) -> Resultado:
    """Custo sobre a mensalidade, pela regra de contagem pre-registada.

    **Os meses e as conversas sao os da coorte**, lidos da exportacao do Piloto
    — a mesma vista do custo que o `h6-export` le (`v_tenant_cost_daily`), mas
    so dos tenants da coorte e so dos meses de calendario **inteiros** depois da
    activacao. A amostra do `h6-export` nao serve para decidir: sao as ultimas N
    conversas **da plataforma**, sem filtro de tenant, e o racio dele so leva os
    meses que essa amostra toca. Do `h6-export` vem o cambio, que tem de ser o
    da vista, os percentis por conversa (reportados) e a mensalidade, conferida.

    **A regra por omissao e a de `14` (LLM + voz + Meta).** Nao ha registo de
    STT (KAM-036), logo:

    * menos de 500 conversas nos meses contados -> `inconclusiva`;
    * LLM + Meta **acima** do tecto -> `refutada`: o STT so soma;
    * LLM + Meta **no** tecto ou abaixo -> `inconclusiva`, `stt_nao_medido`.

    A estatistica que decide e o **racio agregado**: o custo de todos os
    meses-PME contados sobre as mensalidades desses meses (*proposta*). O p50 e o
    p90 por mes-PME e o LLM isolado reportam-se ao lado.
    """
    if mensalidade_minor <= 0:
        raise ValueError("a mensalidade do protocolo tem de ser positiva")
    if int(h6_export["mensalidade_aoa_minor"]) != mensalidade_minor:
        raise ValueError(
            "o h6-export correu com outra mensalidade: "
            f"{h6_export['mensalidade_aoa_minor']} contra {mensalidade_minor} "
            "(o --mensalidade-kz dele e o --mensalidade-minor a dividir por 100)"
        )
    fx = _fraccao(h6_export["fx_aoa_per_usd"])
    meses: list[tuple[Pme, dt.date, Fraction, Fraction]] = []
    conversas = 0
    for pme in sorted(_coorte(exportacao), key=lambda p: p.pme):
        for inicio, fim in _meses_completos(pme, exportacao.ultimo_dia):
            llm = Fraction(pme.soma(inicio, fim, "custo_llm_usd"))
            meta = Fraction(pme.soma(inicio, fim, "custo_meta_usd"))
            conversas += pme.soma(inicio, fim, "conversas")
            meses.append((pme, inicio, llm, meta))

    def minor(usd: Fraction) -> Fraction:
        return usd * fx * 100

    racios = [minor(llm + meta) / mensalidade_minor for _, _, llm, meta in meses]
    llm_isolado = [minor(llm) / mensalidade_minor for _, _, llm, _ in meses]
    agregado = sum(racios, Fraction(0)) / len(meses) if meses else None

    if conversas < H6_AMOSTRA_MINIMA:
        estado, motivo = INCONCLUSIVA, "amostra_abaixo_de_500"
    elif agregado is None:
        estado, motivo = INCONCLUSIVA, "sem_meses_completos"
    elif agregado > H6_TECTO:
        estado, motivo = REFUTADA, "llm_mais_meta_acima_do_tecto"
    else:
        estado, motivo = INCONCLUSIVA, "stt_nao_medido"

    return Resultado(
        hipotese="H6",
        limiar=f"custo <= {_pct(H6_TECTO)} da mensalidade, em >= {H6_AMOSTRA_MINIMA} conversas",
        amostra_n=conversas,
        resultado=(
            "NAO MEDIDO" if agregado is None
            else f"{_pct(agregado)} (LLM + Meta, sem STT), agregado de {len(meses)} meses-PME"
        ),
        estado=estado,
        detalhe={
            "motivo": motivo,
            "regra": "14: LLM + voz + Meta; STT sem registo (KAM-036)",
            "fx_aoa_per_usd": h6_export["fx_aoa_per_usd"],
            "racio_agregado": _pct(agregado),
            "p50_por_mes_pme": _pct(_percentil(racios, 50)),
            "p90_por_mes_pme": _pct(_percentil(racios, 90)),
            "llm_isolado_p50": _pct(_percentil(llm_isolado, 50)),
            "llm_isolado_p90": _pct(_percentil(llm_isolado, 90)),
            "percentis_por_conversa_usd_h6_export": h6_export.get("percentis_custo_total_usd"),
            "por_pme_e_mes": [
                {"pme": p.pme, "mes": i.strftime("%Y-%m"),
                 "custo_aoa_minor": _minor(minor(llm + meta)), "racio": _pct(r)}
                for (p, i, llm, meta), r in zip(meses, racios)
            ],
            "cenarios": cenarios_h6(agregado, mensalidade_minor),
        },
    )


def cenarios_h6(agregado: Fraction | None, mensalidade_minor: int) -> list[dict[str, Any]]:
    """A tabela de cenarios do bloco, so com aritmetica sobre o medido.

    Nao inventa o custo de um modelo mais barato nem o preco da voz: diz **quanto**
    cada alavanca teria de mexer para o racio caber no tecto. Vazia se cabe.
    """
    if agregado is None or agregado <= H6_TECTO:
        return []
    custo_medio = agregado * mensalidade_minor
    return [
        {
            "alavanca": "subir o preco",
            "necessario": f"mensalidade >= {_minor(custo_medio / H6_TECTO)} AOA minor",
        },
        {
            "alavanca": "reduzir modelo ou voz",
            "necessario": f"cortar {_pct(1 - H6_TECTO / agregado)} do custo variavel",
        },
        {
            "alavanca": "limitar volume por plano",
            "necessario": f"volume <= {_pct(H6_TECTO / agregado)} do medido, por PME e mes",
        },
    ]


def _minor(valor: Fraction) -> int:
    """Arredonda **para cima**: um preco minimo arredondado para baixo nao cabe."""
    return -(-valor.numerator // valor.denominator)


# ---------------------------------------------------------------------- H8


@dataclass(frozen=True)
class Auditoria:
    """A auditoria de um catalogo: itens certos sobre itens da amostra."""

    pme: str
    itens: int
    correctos: int
    actualizacoes: int | None = None
    mudancas_declaradas: int | None = None
    auditado_em: dt.date | None = None
    fora_da_semana_4: bool = False

    @property
    def correcto(self) -> bool:
        return self.itens > 0 and Fraction(self.correctos, self.itens) >= H8_ITENS_CORRECTOS


def h8(exportacao: Exportacao, auditorias: Iterable[Auditoria]) -> Resultado:
    """Catalogos correctos, sobre a coorte. Sem auditoria e pendente."""
    por_pme = {a.pme: a for a in auditorias}
    coorte = {p.pme for p in _coorte(exportacao)}
    alheias = sorted(set(por_pme) - coorte)
    if alheias:
        raise ValueError(f"auditoria de PME fora da coorte: {', '.join(alheias)}")
    correctos = sorted(p for p, a in por_pme.items() if a.correcto)
    pendentes = sorted(coorte - set(por_pme)) + [""] * max(0, COORTE - len(coorte))
    estado = estado_por_contagem(len(correctos), len(pendentes), H8_ALVO)
    return Resultado(
        hipotese="H8",
        limiar=f">= {H8_ALVO} de {COORTE} catalogos correctos (>= {_pct(H8_ITENS_CORRECTOS)} dos itens)",
        amostra_n=len(por_pme),
        resultado=f"{len(correctos)} de {len(por_pme)} auditados",
        estado=estado,
        detalhe={
            "correctos": correctos,
            "pendentes": [p for p in pendentes if p],
            "fora_da_semana_4": sorted(a.pme for a in por_pme.values() if a.fora_da_semana_4),
            "vagas_na_coorte": max(0, COORTE - len(coorte)),
            "por_pme": {
                a.pme: {
                    "itens": a.itens,
                    "correctos": a.correctos,
                    "catalogo_correcto": a.correcto,
                    "actualizacoes_no_sistema": a.actualizacoes,
                    "mudancas_reais_declaradas": a.mudancas_declaradas,
                    "auditado_em": None if a.auditado_em is None else a.auditado_em.isoformat(),
                    "fora_da_semana_4": a.fora_da_semana_4,
                }
                for a in sorted(por_pme.values(), key=lambda a: a.pme)
            },
        },
    )


# ---------------------------------------------------------------------- H9


def h9(exportacao: Exportacao) -> Resultado:
    """Activas ao dia 60, so sobre as PMEs com 60 dias de exposicao.

    **Le-se a data do gate, e nao e final antes dela.** Ao contrario de H1 e H8,
    uma H9 com 8 elegiveis pode mudar quando mais PMEs fazem 60 dias: o bloco
    manda calcula-la sobre as PMEs com 60 dias **a data do gate**, e e sobre a
    exportacao congelada dessa data que o KAM-110 a le.
    """
    activadas = sorted(
        (p for p in _coorte(exportacao) if p.activada_em is not None),
        key=lambda p: (p.activada_em, p.pme),
    )
    elegiveis = [p for p in activadas if _dia(p, H9_DIA) <= exportacao.ultimo_dia]
    activas = [p.pme for p in elegiveis if activa_em(p, _dia(p, H9_DIA))]
    seguimento = None
    if len(elegiveis) < H9_MINIMO_DE_PMES:
        estado = INCONCLUSIVA
        if len(activadas) >= H9_MINIMO_DE_PMES:
            seguimento = _dia(activadas[H9_MINIMO_DE_PMES - 1], H9_DIA).isoformat()
    elif Fraction(len(activas), len(elegiveis)) >= H9_LIMIAR:
        estado = CONFIRMADA
    else:
        estado = REFUTADA

    ao_dia_30 = [p for p in activadas if _dia(p, DIA_DO_INDICADOR) <= exportacao.ultimo_dia]
    activas_30 = [p.pme for p in ao_dia_30 if activa_em(p, _dia(p, DIA_DO_INDICADOR))]
    return Resultado(
        hipotese="H9",
        limiar=f">= {_pct(H9_LIMIAR)} activas ao dia {H9_DIA}, com >= {H9_MINIMO_DE_PMES} PMEs elegiveis",
        amostra_n=len(elegiveis),
        resultado=(
            "NAO MEDIDO" if not elegiveis
            else f"{len(activas)} de {len(elegiveis)} ({_pct(Fraction(len(activas), len(elegiveis)))})"
        ),
        estado=estado,
        detalhe={
            "activas": activas,
            "elegiveis": [p.pme for p in elegiveis],
            "data_de_seguimento": seguimento,
            "indicador_dia_30": {
                "activas": activas_30,
                "elegiveis": [p.pme for p in ao_dia_30],
                "nota": "reportado a parte; nao substitui o do dia 60",
            },
        },
    )


# ----------------------------------------------------------- pre-condicoes


def pre_condicoes(exportacao: Exportacao) -> dict[str, Any]:
    """O que o bloco pede antes de medir, e que a exportacao consegue dizer.

    O `GoLive_Gate.md` todo verde **nao** se le daqui: e uma folha humana, e o
    protocolo exige-a assinada antes da 1.a activacao.
    """
    activadas = [p for p in exportacao.coorte if p.activada_em is not None]
    conhecidas = [p for p in activadas if p.self_service is not None]
    sem_humano = [p for p in conhecidas if p.self_service]
    fraccao = Fraction(len(sem_humano), len(conhecidas)) if conhecidas else None
    return {
        "activadas": len(activadas),
        "dpa_aceite": f"{sum(p.dpa_aceite for p in activadas)} de {len(activadas)}",
        "dpa_em_falta": sorted(p.pme for p in activadas if not p.dpa_aceite),
        "self_service": None if fraccao is None else _pct(fraccao),
        "self_service_desconhecido": sorted(p.pme for p in activadas if p.self_service is None),
        "self_service_cumpre_carta": None if fraccao is None else fraccao >= SELF_SERVICE_MINIMO,
    }

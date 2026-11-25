"""O relatorio semanal do Piloto, de modelo fixo (KAM-109).

Uma tabela por semana do Piloto, uma linha por PME da coorte e uma de total,
com as sete colunas que o bloco enumera: activa, conversas, *handoffs*,
pagamentos, custo, incidentes e horas de operador. A semana N sao os dias
`[inicio + 7(N-1), inicio + 7N - 1]`, com `inicio` o dia 1 do Piloto que o
protocolo regista.

## O que o relatorio nunca contem

Conteudo de conversas, telefones, `contact_id` e nomes. A garantia tem duas
partes, e a segunda existe porque a primeira e codigo que alguem pode alargar:

1. **so le numeros**: a exportacao tem lista fechada de campos, e o relatorio
   so usa o ordinal da PME e contagens;
2. **a saida passa por `verificar_sem_pii`** antes de ser escrita — recusa
   qualquer `uuid` (um `tenant_id` ou um `contact_id`) e qualquer forma de
   telefone angolano, movel ou fixo (`guarda`). Um relatorio recusado nao se
   escreve.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Final

from . import guarda
from . import horas as modulo_horas
from .exportacao import Exportacao
from .regras import activa_em

COLUNAS: Final = (
    "PME",
    "Dias desde a activação",
    "Activa",
    "Conversas",
    "Handoffs",
    "Pagamentos",
    "Custo LLM + Meta (USD)",
    "Incidentes",
    "Horas de operador",
)

class RelatorioRecusado(Exception):
    """O texto do relatorio tem algo com forma de dado pessoal."""


def verificar_sem_pii(texto: str, permitidos: tuple[str, ...] = ()) -> None:
    """Recusa o texto com `uuid` ou forma de telefone (`guarda`).

    `permitidos` sao valores exactos que o proprio gerador escreveu — o `sha256`
    da exportacao —, e saem da procura so por esse valor.
    """
    encontrados = guarda.achados(texto, permitidos)
    if encontrados:
        raise RelatorioRecusado("o relatorio tem " + ", ".join(encontrados) + ": nao se escreve")


def semana(inicio: dt.date, n: int) -> tuple[dt.date, dt.date]:
    if n < 1:
        raise ValueError("a semana do Piloto comeca em 1")
    primeiro = inicio + dt.timedelta(days=7 * (n - 1))
    return primeiro, primeiro + dt.timedelta(days=6)


def _horas(minutos: int) -> str:
    return f"{minutos // 60}h{minutos % 60:02d}"


def gerar(
    exportacao: Exportacao,
    blocos: list[modulo_horas.Bloco],
    inicio: dt.date,
    n: int,
    sha256_da_exportacao: str,
) -> str:
    """O Markdown da semana `n`. Levanta `RelatorioRecusado` se a guarda morder."""
    de, ate = semana(inicio, n)
    if ate > exportacao.ultimo_dia:
        raise ValueError(
            f"a semana {n} acaba a {ate} e a exportacao so vai ate {exportacao.ultimo_dia}: "
            "um relatorio de semana incompleta nao se emite"
        )
    operador = modulo_horas.por_pme(blocos, de, ate)
    linhas = []
    totais = {"conversas": 0, "handoffs": 0, "pagamentos": 0, "custo": Decimal(0),
              "incidentes": 0, "minutos": 0, "activas": 0}
    for pme in sorted(exportacao.coorte, key=lambda p: p.pme):
        if pme.activada_em is None or pme.activada_em > ate:
            dias, activa = "—", "—"
        else:
            dias = str((ate - pme.activada_em).days)
            activa_sim = activa_em(pme, ate)
            totais["activas"] += activa_sim
            activa = "sim" if activa_sim else "não"
        conversas = pme.soma(de, ate, "conversas")
        handoffs = pme.soma(de, ate, "handoffs")
        pagos = sum(1 for c in pme.ciclos_pagos if de <= c.inicio <= ate)
        custo = pme.soma(de, ate, "custo_llm_usd") + pme.soma(de, ate, "custo_meta_usd")
        op = operador.get(pme.pme, {"minutos": 0, "incidentes": 0})
        totais["conversas"] += conversas
        totais["handoffs"] += handoffs
        totais["pagamentos"] += pagos
        totais["custo"] += custo
        totais["incidentes"] += op["incidentes"]
        totais["minutos"] += op["minutos"]
        linhas.append(
            [pme.pme, dias, activa, str(conversas), str(handoffs), str(pagos),
             f"{custo:.2f}", str(op["incidentes"]), _horas(op["minutos"])]
        )
    # O trabalho que nao e de uma PME da coorte nao some: o sem PME, e o das
    # substituidas ou de um ordinal que nao esta na coorte, numa linha cada.
    na_coorte = {p.pme for p in exportacao.coorte}
    restos = {
        "Sem PME": [modulo_horas.SEM_PME],
        "Fora da coorte": sorted(k for k in operador if k != modulo_horas.SEM_PME and k not in na_coorte),
    }
    for rotulo, chaves in restos.items():
        minutos = sum(operador[k]["minutos"] for k in chaves if k in operador)
        incidentes = sum(operador[k]["incidentes"] for k in chaves if k in operador)
        totais["minutos"] += minutos
        totais["incidentes"] += incidentes
        linhas.append([rotulo, "—", "—", "—", "—", "—", "—", str(incidentes), _horas(minutos)])
    linhas.append(
        ["**Total**", "—", f"{totais['activas']} de {len(exportacao.coorte)}",
         str(totais["conversas"]), str(totais["handoffs"]), str(totais["pagamentos"]),
         f"{totais['custo']:.2f}", str(totais["incidentes"]), _horas(totais["minutos"])]
    )
    marca = " — **DADOS SINTÉTICOS**" if exportacao.sintetico else ""
    partes = [
        f"# Relatório semanal do Piloto — semana {n}{marca}",
        "",
        f"Dias {de.isoformat()} a {ate.isoformat()} (`Africa/Luanda`). "
        f"Coorte: {len(exportacao.coorte)} PMEs; substituídas até hoje: {len(exportacao.substituidas)}.",
        "",
        "«Activa» é a definição do protocolo, medida na janela de 14 dias que acaba no último dia "
        "da semana. O custo é LLM + Meta da vista do custo, sem STT, que não tem registo.",
        "",
        "| " + " | ".join(COLUNAS) + " |",
        "|" + "---|" * len(COLUNAS),
        *("| " + " | ".join(linha) + " |" for linha in linhas),
        "",
        f"Fonte: exportação `kamba-piloto-export/1` até {exportacao.ultimo_dia.isoformat()}, "
        f"sha256 `{sha256_da_exportacao}`.",
        "",
    ]
    texto = "\n".join(partes)
    verificar_sem_pii(texto, (sha256_da_exportacao,))
    return texto

"""Custo por hora de áudio e por PME/mês, a partir das durações medidas (KAM-107).

Em `Decimal` e em USD, que é a moeda em que os dois fornecedores facturam. Não
é dinheiro da plataforma (não há `*_minor` aqui): é uma estimativa de custo para
uma decisão, e diz-se em USD com quatro casas.

**O mínimo facturado conta**, e é por isso que o custo se calcula clip a clip e
não pela soma das durações: `E4` §3.4 regista «faturação mínima 10 s» no Groq
(INDÍCIO-forte), e uma nota de voz de 6 s paga 10. Com o corpus do critério 1
(clips de 5 a 30 s) isso pesa, e o `$0,2` do doc 09 §14.3 — que é 300 min a
$0,04/h sem mínimo — fica por baixo. Para a OpenAI o mínimo é **NÃO VERIFICADO**
e está a zero no `precos.json`, com esse estado escrito ao lado.

O custo por PME/mês escala a distribuição de durações **do corpus** a 300 minutos
(doc 09 §14.3). É uma leitura: a distribuição real das notas de voz de clientes
não é a do corpus, e não está medida.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

AQUI = Path(__file__).resolve().parent
PRECOS = AQUI / "precos.json"
MINUTOS_POR_PME_MES = Decimal(300)
#: As ESTIMATIVAS do doc 09 §14.3 que o critério 6 manda comparar com o medido.
ESTIMATIVA_DOC09_USD = {"groq": Decimal("0.2"), "openai": Decimal("0.9")}


@dataclass(frozen=True)
class Preco:
    fornecedor: str
    modelo: str
    usd_por_segundo: Decimal
    minimo_s: Decimal
    estado: str
    minimo_estado: str


@dataclass(frozen=True)
class Tabela:
    lido_em: str
    fonte: str
    precos: dict[str, Preco]


def ler_precos(caminho: Path | str = PRECOS) -> Tabela:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    precos = {}
    for nome, p in dados["fornecedores"].items():
        if "usd_por_hora" in p:
            por_s = Decimal(p["usd_por_hora"]) / 3600
        else:
            por_s = Decimal(p["usd_por_minuto"]) / 60
        precos[nome] = Preco(nome, p["modelo"], por_s, Decimal(p["minimo_s"]), p["estado"], p["minimo_estado"])
    return Tabela(dados["lido_em"], dados["fonte"], precos)


def custo_clip(preco: Preco, duracao_s: Decimal) -> Decimal:
    return preco.usd_por_segundo * max(duracao_s, preco.minimo_s)


def por_hora(preco: Preco, duracoes_s: Iterable[Decimal]) -> Decimal:
    """USD por hora **de áudio**, com o mínimo facturado de cada clip."""
    lista = list(duracoes_s)
    segundos = sum(lista, Decimal(0))
    if segundos == 0:
        raise ValueError("sem áudio, não há custo por hora")
    return sum((custo_clip(preco, d) for d in lista), Decimal(0)) * 3600 / segundos


def por_pme_mes(preco: Preco, duracoes_s: Iterable[Decimal]) -> Decimal:
    return por_hora(preco, duracoes_s) * MINUTOS_POR_PME_MES / 60


def usd(valor: Decimal) -> str:
    return f"${valor.quantize(Decimal('0.0001'))}".replace(".", ",")

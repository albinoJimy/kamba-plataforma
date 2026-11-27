"""Latência p50 e p95 por tamanho de clip, e taxa de erro ou *timeout* (KAM-107).

Lê as linhas JSON do *harness*. As leituras abaixo são **propostas**, escritas no
`H7_Voz_STT.md` §2 antes da primeira medição:

- **Percentil pelo método do posto mais próximo** (*nearest-rank*): o p95 de 30
  valores é o 29.º mais pequeno. Sem interpolação, para que o p95 seja sempre uma
  execução que aconteceu.
- **Um *timeout* entra na latência com o tempo que demorou** (pelo menos o
  tecto), e não sai dela: tirá-lo dava ao fornecedor mais lento o p95 de um
  fornecedor rápido. Um erro (HTTP, resposta ilegível) **não** tem latência de
  transcrição e conta só na taxa de erro.
- **Os três momentos do dia** são manhã (06h–12h), tarde (12h–18h) e noite
  (18h–24h) **na hora de Luanda**, que é UTC+1 fixo, sem hora de Verão. Uma
  execução entre as 00h e as 06h não conta para nenhum. O critério («≥ 30
  execuções por tamanho, em 3 momentos do dia») lê-se como **≥ 30 por tamanho
  e por fornecedor, com execuções nos três momentos**.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from manifesto import TAMANHOS_S, tamanho
from porta import ERRO, TIMEOUT

LUANDA = timezone(timedelta(hours=1), "Africa/Luanda")
MOMENTOS = (("manha", 6, 12), ("tarde", 12, 18), ("noite", 18, 24))
EXECUCOES_MIN = 30


def ler_resultados(caminhos: Iterable[Path | str]) -> list[dict]:
    linhas: list[dict] = []
    for caminho in caminhos:
        with open(caminho, encoding="utf-8") as f:
            linhas.extend(json.loads(l) for l in f if l.strip())
    return linhas


def momento(inicio_utc: str) -> str | None:
    instante = datetime.fromisoformat(inicio_utc)
    if instante.tzinfo is None:
        raise ValueError("inicio_utc sem fuso: o harness escreve sempre em UTC")
    hora = instante.astimezone(LUANDA).hour
    for nome, de, ate in MOMENTOS:
        if de <= hora < ate:
            return nome
    return None


def percentil(valores: list[float], q: float) -> float:
    """Posto mais próximo: o valor de ordem `ceil(q·n)`."""
    if not valores:
        raise ValueError("percentil de uma lista vazia")
    if not 0 < q <= 1:
        raise ValueError("q em ]0, 1]")
    ordenados = sorted(valores)
    return ordenados[max(1, math.ceil(q * len(ordenados))) - 1]


@dataclass(frozen=True)
class Linha:
    fornecedor: str
    tamanho_s: int
    execucoes: int
    por_momento: Mapping[str, int]
    erros: int
    timeouts: int
    p50_ms: float | None
    p95_ms: float | None

    @property
    def faltas(self) -> list[str]:
        f = []
        if self.execucoes < EXECUCOES_MIN:
            f.append(f"{self.execucoes} execuções, mínimo {EXECUCOES_MIN}")
        sem = [m for m, _, _ in MOMENTOS if self.por_momento.get(m, 0) == 0]
        if sem:
            f.append("sem execuções de " + ", ".join(sem))
        return f


def resumir(resultados: Iterable[Mapping], fornecedor: str) -> list[Linha]:
    """Uma linha por tamanho, só com as execuções de clips de latência."""
    por_tamanho: dict[int, list[Mapping]] = {t: [] for t in TAMANHOS_S}
    for r in resultados:
        if r.get("fornecedor") != fornecedor or r.get("tipo") != "latencia":
            continue
        t = tamanho(Decimal(str(r["duracao_s"])))
        if t is not None:
            por_tamanho[t].append(r)
    linhas = []
    for t, rs in por_tamanho.items():
        contagem = {m: 0 for m, _, _ in MOMENTOS}
        for r in rs:
            m = momento(r["inicio_utc"])
            if m:
                contagem[m] += 1
        tempos = [float(r["latencia_ms"]) for r in rs if r["estado"] != ERRO]
        linhas.append(
            Linha(
                fornecedor=fornecedor,
                tamanho_s=t,
                execucoes=len(rs),
                por_momento=contagem,
                erros=sum(1 for r in rs if r["estado"] == ERRO),
                timeouts=sum(1 for r in rs if r["estado"] == TIMEOUT),
                p50_ms=percentil(tempos, 0.50) if tempos else None,
                p95_ms=percentil(tempos, 0.95) if tempos else None,
            )
        )
    return linhas


@dataclass(frozen=True)
class Falhas:
    execucoes: int
    erros: int
    timeouts: int

    @property
    def taxa(self) -> float | None:
        return None if self.execucoes == 0 else (self.erros + self.timeouts) / self.execucoes


def falhas(resultados: Iterable[Mapping], fornecedor: str) -> Falhas:
    """Sobre **todas** as execuções do fornecedor, das duas passagens."""
    rs = [r for r in resultados if r.get("fornecedor") == fornecedor]
    return Falhas(
        execucoes=len(rs),
        erros=sum(1 for r in rs if r["estado"] == ERRO),
        timeouts=sum(1 for r in rs if r["estado"] == TIMEOUT),
    )

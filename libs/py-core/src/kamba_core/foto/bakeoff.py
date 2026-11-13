"""O *harness* do *bake-off* de fornecedores de imagem (KAM-120, criterio 7).

O criterio pede >= 30 fotos reais autorizadas pelas PME, >= 2 fornecedores e,
por fornecedor: utilizavel (>= 80% por **dois** avaliadores, *proposta*),
alteracao indevida do produto (<= 5%, *proposta*), latencia p50/p95 e custo por
imagem **final**. Este modulo e a parte repetivel disso:

* `correr` passa cada foto por cada fornecedor, mede a latencia com o relogio
  de quem corre e regista o custo, **incluindo o das falhas**;
* `resumir` junta as execucoes as avaliacoes dos dois avaliadores e da os
  numeros por fornecedor;
* `tabela` escreve-os em Markdown, para o registo em
  `docs/tecnica/evidencia/validacao/`.

**O que ele nao faz e decidir**: a decisao (primario e contingencia) e de
quem tem dono e data, e as fotos reais so entram depois das cartas de
nao-treino (criterio 8). Ate la corre com imagens sinteticas, e os numeros que
saem nao dizem nada da qualidade em fotos angolanas (NAO VERIFICADO, E5).

## Duas leituras que o criterio deixa abertas, e a que se escolheu

* **«Utilizavel por 2 avaliadores»** le-se como **os dois** dizem que sim. A
  leitura «pelo menos um» dava o mesmo numero a um fornecedor sobre o qual os
  avaliadores discordam em metade das fotos, que e o que se quer ver.
* **Custo por imagem final** e o custo **total** do fornecedor (incluindo as
  falhas e as utilizaveis por nenhum) a dividir pelas utilizaveis. Uma imagem
  que ninguem aproveita custou na mesma.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from .fornecedor import ErroDoFornecedor, ImageProvider, Opcoes

#: Os alvos do criterio, todos *proposta*.
UTILIZAVEL_MINIMO: Final = Decimal("0.80")
ALTERACAO_MAXIMA: Final = Decimal("0.05")
FOTOS_MINIMAS: Final = 30
FORNECEDORES_MINIMOS: Final = 2


@dataclass(frozen=True)
class Execucao:
    foto_id: str
    provider: str
    ok: bool
    latencia_ms: int
    custo_usd: Decimal


@dataclass(frozen=True)
class Avaliacao:
    """O juizo dos dois avaliadores sobre uma versao."""

    foto_id: str
    provider: str
    utilizavel_a: bool
    utilizavel_b: bool
    #: Algum dos dois viu o produto mudado (cor, forma, rotulo, marca).
    alterou_produto: bool


@dataclass(frozen=True)
class Resumo:
    provider: str
    fotos: int
    falhas: int
    utilizavel: Decimal
    alteracao: Decimal
    p50_ms: int | None
    p95_ms: int | None
    custo_total_usd: Decimal
    custo_por_final_usd: Decimal | None

    @property
    def cumpre(self) -> bool:
        return self.utilizavel >= UTILIZAVEL_MINIMO and self.alteracao <= ALTERACAO_MAXIMA


def percentil(valores: Sequence[int], p: float) -> int | None:
    """O percentil por *nearest-rank*: o valor observado, nunca interpolado."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = max(1, math.ceil(p / 100 * len(ordenados)))
    return ordenados[posicao - 1]


def correr(
    fotos: Iterable[tuple[str, bytes]],
    fornecedores: Sequence[ImageProvider],
    operacao: str,
    relogio_ms: Callable[[], float],
) -> list[Execucao]:
    """Cada foto por cada fornecedor. Uma falha fica registada, nao interrompe."""
    execucoes: list[Execucao] = []
    for foto_id, imagem in fotos:
        for fornecedor in fornecedores:
            inicio = relogio_ms()
            try:
                melhoria = fornecedor.enhance(imagem, Opcoes(operacao=operacao))
            except ErroDoFornecedor as erro:
                execucoes.append(
                    Execucao(foto_id, fornecedor.nome, False, int(relogio_ms() - inicio), erro.custo_usd)
                )
                continue
            except Exception:  # noqa: BLE001 — o *timeout* e o resto contam como falha
                execucoes.append(Execucao(foto_id, fornecedor.nome, False, int(relogio_ms() - inicio), Decimal(0)))
                continue
            execucoes.append(
                Execucao(foto_id, fornecedor.nome, True, int(relogio_ms() - inicio), melhoria.custo_usd)
            )
    return execucoes


def resumir(execucoes: Sequence[Execucao], avaliacoes: Sequence[Avaliacao]) -> list[Resumo]:
    """Os numeros por fornecedor. Uma execucao sem avaliacao conta como nao utilizavel."""
    juizo = {(a.foto_id, a.provider): a for a in avaliacoes}
    resumos: list[Resumo] = []
    for provider in sorted({e.provider for e in execucoes}):
        dele = [e for e in execucoes if e.provider == provider]
        fotos = len(dele)
        utilizaveis = 0
        alteradas = 0
        for execucao in dele:
            avaliacao = juizo.get((execucao.foto_id, provider))
            if not execucao.ok or avaliacao is None:
                continue
            if avaliacao.utilizavel_a and avaliacao.utilizavel_b:
                utilizaveis += 1
            if avaliacao.alterou_produto:
                alteradas += 1
        latencias = [e.latencia_ms for e in dele if e.ok]
        custo = sum((e.custo_usd for e in dele), Decimal(0))
        resumos.append(
            Resumo(
                provider=provider,
                fotos=fotos,
                falhas=sum(1 for e in dele if not e.ok),
                utilizavel=Decimal(utilizaveis) / fotos if fotos else Decimal(0),
                alteracao=Decimal(alteradas) / fotos if fotos else Decimal(0),
                p50_ms=percentil(latencias, 50),
                p95_ms=percentil(latencias, 95),
                custo_total_usd=custo,
                custo_por_final_usd=(custo / utilizaveis) if utilizaveis else None,
            )
        )
    return resumos


def suficiente(execucoes: Sequence[Execucao]) -> bool:
    """O tamanho do *bake-off*: >= 30 fotos e >= 2 fornecedores."""
    fotos = {e.foto_id for e in execucoes}
    fornecedores = {e.provider for e in execucoes}
    return len(fotos) >= FOTOS_MINIMAS and len(fornecedores) >= FORNECEDORES_MINIMOS


def tabela(resumos: Sequence[Resumo]) -> str:
    """A tabela Markdown do registo."""
    linhas = [
        "| Fornecedor | Fotos | Falhas | Utilizável | Alteração indevida | p50 (ms) | p95 (ms) | Custo por imagem final (USD) | Cumpre |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def pct(valor: Decimal) -> str:
        return f"{(valor * 100).quantize(Decimal('0.1'))}%"

    for r in resumos:
        custo = "—" if r.custo_por_final_usd is None else str(r.custo_por_final_usd.quantize(Decimal("0.0001")))
        linhas.append(
            f"| `{r.provider}` | {r.fotos} | {r.falhas} | {pct(r.utilizavel)} | {pct(r.alteracao)} | "
            f"{r.p50_ms if r.p50_ms is not None else '—'} | {r.p95_ms if r.p95_ms is not None else '—'} | "
            f"{custo} | {'sim' if r.cumpre else 'não'} |"
        )
    return "\n".join(linhas) + "\n"

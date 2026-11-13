"""As metricas do §14.2 do `docs/tecnica/05`, sobre listas ja ordenadas (KAM-064).

Funcoes puras: recebem a lista de `product_ref` que a pesquisa devolveu, **pela
ordem dela**, e os graus 0-3 anotados no *dataset*. Nao ha base de dados aqui —
quem pesquisa e o `runner`.

## As escolhas que o §14.2 nao fixa, escritas

* **Relevante** e o que tem grau >= 1. O `success@3` pede grau >= 2, pela letra
  do §14.2; o `recall@10` conta todos os relevantes (grau >= 1).
* **O ganho do nDCG** e `2^grau - 1`, com o desconto `log2(posicao + 1)`. Com
  graus 0-3 e a forma usual; a linear (`grau`) daria outro numero, e por isso o
  `GANHO` esta escrito e preso num ensaio.
* **Um `product_ref` repetido** na lista conta uma vez, na primeira posicao: o
  `idx.candidatos` nao repete, e um executor que repetisse inflava o DCG.
* **Uma consulta sem relevantes** (o `nao_resolvivel`, ou uma anotacao sem grau
  >= 1) fica **fora** das medias de `success@3`, `recall@10` e `nDCG@3`: o IDCG
  dela e zero e a metrica nao esta definida. Entra no falso-positivo.
* **Os empates** de pontuacao nao chegam aqui: a ordem e a que a pesquisa
  devolveu, e a dela e total (acaba no `sku`, §6.3). Dois relevantes com o mesmo
  grau sao indiferentes no IDCG, que so le os graus.

As medias sao **por consulta** (macro) e arredondam-se so no relatorio.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

#: O grau minimo para o `success@3` (§14.2: «relevante (grau >= 2)»).
GRAU_DO_SUCESSO: Final = 2

#: O grau minimo para contar como relevante no `recall@10` e no nDCG.
GRAU_RELEVANTE: Final = 1

#: As *tags* que fazem uma consulta contar no `success@3` de *typo*/regionalismo.
TAGS_DE_VARIANTE: Final = frozenset({"typo", "regionalismo"})


def ganho(grau: int) -> float:
    """O ganho de um grau no nDCG: `2^grau - 1`."""
    return float(2**grau - 1)


def _unicos(ordem: Sequence[str]) -> list[str]:
    vistos: set[str] = set()
    saida: list[str] = []
    for ref in ordem:
        if ref not in vistos:
            vistos.add(ref)
            saida.append(ref)
    return saida


def tem_relevantes(graus: Mapping[str, int]) -> bool:
    return any(g >= GRAU_RELEVANTE for g in graus.values())


def success_at(ordem: Sequence[str], graus: Mapping[str, int], k: int = 3) -> float:
    """1,0 se algum dos `k` primeiros tem grau >= 2; 0,0 se nao."""
    return float(any(graus.get(ref, 0) >= GRAU_DO_SUCESSO for ref in _unicos(ordem)[:k]))


def recall_at(ordem: Sequence[str], graus: Mapping[str, int], k: int = 10) -> float:
    """Relevantes (grau >= 1) nos `k` primeiros / relevantes anotados."""
    relevantes = {ref for ref, g in graus.items() if g >= GRAU_RELEVANTE}
    if not relevantes:
        raise ValueError("recall sem relevantes nao esta definido")
    return len(relevantes.intersection(_unicos(ordem)[:k])) / len(relevantes)


def dcg(graus_pela_ordem: Iterable[int]) -> float:
    return sum(ganho(g) / math.log2(posicao + 2) for posicao, g in enumerate(graus_pela_ordem))


def ndcg_at(ordem: Sequence[str], graus: Mapping[str, int], k: int = 3) -> float:
    """O DCG dos `k` primeiros sobre o DCG ideal dos graus anotados."""
    ideal = dcg(sorted((g for g in graus.values() if g > 0), reverse=True)[:k])
    if ideal == 0:
        raise ValueError("nDCG sem relevantes nao esta definido")
    return dcg(graus.get(ref, 0) for ref in _unicos(ordem)[:k]) / ideal


@dataclass(frozen=True)
class Resultado:
    """Uma consulta avaliada: o que veio, e o que devia vir."""

    qid: str
    catalogo: str
    tags: frozenset[str]
    nao_resolvivel: bool
    ordem: tuple[str, ...]
    graus: Mapping[str, int]


def _media(valores: Sequence[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


def agregar(resultados: Sequence[Resultado]) -> dict[str, float | int | None]:
    """As seis metricas do §14.2 sobre um conjunto de consultas.

    `None` quando o denominador e zero — um zero inventado reprovava ou
    aprovava um alvo sem medida nenhuma.
    """
    resolviveis = [r for r in resultados if not r.nao_resolvivel]
    com_relevantes = [r for r in resolviveis if tem_relevantes(r.graus)]
    variantes = [r for r in com_relevantes if r.tags & TAGS_DE_VARIANTE]
    nao_resolviveis = [r for r in resultados if r.nao_resolvivel]
    return {
        "consultas": len(resultados),
        "success_at_3": _media([success_at(r.ordem, r.graus) for r in com_relevantes]),
        "recall_at_10": _media([recall_at(r.ordem, r.graus) for r in com_relevantes]),
        "ndcg_at_3": _media([ndcg_at(r.ordem, r.graus) for r in com_relevantes]),
        "success_at_3_typo_regionalismo": _media(
            [success_at(r.ordem, r.graus) for r in variantes]
        ),
        "zero_result_rate": _media([float(not r.ordem) for r in resolviveis]),
        "falso_positivo_nao_resolvivel": _media(
            [float(bool(r.ordem)) for r in nao_resolviveis]
        ),
    }


#: Os alvos do Piloto do §14.2. **Propostas**, e e assim que o relatorio os diz:
#: um desvio explica-se, nao se corrige mudando o alvo (criterio 7).
ALVOS_DO_PILOTO: Final = {
    "success_at_3": (">=", 0.85),
    "recall_at_10": (">=", 0.90),
    "ndcg_at_3": (">=", 0.75),
    "success_at_3_typo_regionalismo": (">=", 0.80),
    "zero_result_rate": ("<=", 0.08),
    "falso_positivo_nao_resolvivel": ("<=", 0.10),
}


def cumpre(metrica: str, valor: float | None) -> bool | None:
    """Se `valor` cumpre o alvo do Piloto; `None` sem valor."""
    if valor is None:
        return None
    sentido, alvo = ALVOS_DO_PILOTO[metrica]
    return valor >= alvo if sentido == ">=" else valor <= alvo


def kappa_de_cohen(a: Sequence[int], b: Sequence[int]) -> float:
    """O kappa de Cohen entre duas anotacoes dos mesmos itens (criterio 2).

    Concordancia observada menos a esperada pelas marginais, sobre um menos a
    esperada. Com as duas anotacoes constantes e iguais o kappa nao esta
    definido (0/0) e levanta.
    """
    if len(a) != len(b) or not a:
        raise ValueError("o kappa pede duas anotacoes do mesmo tamanho, nao vazias")
    n = len(a)
    observada = sum(x == y for x, y in zip(a, b)) / n
    categorias = set(a) | set(b)
    esperada = sum((a.count(c) / n) * (b.count(c) / n) for c in categorias)
    if esperada == 1:
        raise ValueError("kappa indefinido: as duas anotacoes sao constantes e iguais")
    return (observada - esperada) / (1 - esperada)

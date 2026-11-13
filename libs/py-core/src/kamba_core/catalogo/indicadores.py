"""Os indicadores do Catalogo AI, lidos das ingestoes (KAM-049, criterio 9; §8.4).

**Nao e um modulo de metricas Prometheus**, de proposito: os quatro numeros do
§8.4 sao razoes sobre ingestoes inteiras, e a fonte de verdade de cada uma ja
esta na linha — o `custo_llm_usd`, o estado e o `corrigido` de cada campo. Um
contador em memoria contava outra vez o que a base ja sabe, e perdia-o no
reinicio. Le-se com uma consulta (`SQL_INGESTOES_DO_TENANT`) e calcula-se aqui.

| Indicador | Numerador | Denominador |
|---|---|---|
| `publicados_sem_correccao` | `publicada` sem nenhum campo `corrigido` | `publicada` |
| `campos_ia_visao_corrigidos` | campos com `corrigido` | campos que vieram da visao (`ia_visao` ou `corrigido`) |
| `custo_medio_usd` | soma de `custo_llm_usd` das `publicada` | `publicada` |
| `perguntas_medias` | soma de `perguntas_feitas` das `publicada` | `publicada` |

Uma razao sem denominador e `None`, e nao zero: «0% corrigidos» sobre nenhum
campo era uma afirmacao sem medicao.

O p95 foto -> rascunho do criterio 9 **nao** se le daqui: mede-se no *staging*
com o fornecedor real, e o fornecedor real e o credor do bloco.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from . import estados
from .extraccao import IA_VISAO
from .pipeline import SUGESTAO
from .repositorio import Ingestao

#: O tecto do criterio 9, em USD por produto, repeticoes incluidas. *Proposta*.
TECTO_DE_CUSTO_USD: Final = Decimal("0.02")


@dataclass(frozen=True)
class Indicadores:
    publicadas: int
    publicados_sem_correccao: Decimal | None
    campos_ia_visao_corrigidos: Decimal | None
    custo_medio_usd: Decimal | None
    perguntas_medias: Decimal | None
    acima_do_tecto: int


def _razao(numerador: int | Decimal, denominador: int) -> Decimal | None:
    if denominador == 0:
        return None
    return (Decimal(numerador) / denominador).quantize(Decimal("0.0001"))


def calcular(ingestoes: Iterable[Ingestao]) -> Indicadores:
    publicadas = [i for i in ingestoes if i.estado == estados.PUBLICADA]
    sem_correccao = 0
    da_visao = 0
    corrigidos = 0
    for ingestao in publicadas:
        produto = [c for nome, c in ingestao.campos.items() if nome != SUGESTAO]
        if not any(c.corrigido for c in produto):
            sem_correccao += 1
        for campo in produto:
            if campo.fonte == IA_VISAO or campo.corrigido:
                da_visao += 1
            if campo.corrigido:
                corrigidos += 1
    total = len(publicadas)
    return Indicadores(
        publicadas=total,
        publicados_sem_correccao=_razao(sem_correccao, total),
        campos_ia_visao_corrigidos=_razao(corrigidos, da_visao),
        custo_medio_usd=_razao(sum((i.custo_llm_usd for i in publicadas), Decimal(0)), total),
        perguntas_medias=_razao(sum(i.perguntas_feitas for i in publicadas), total),
        acima_do_tecto=sum(1 for i in publicadas if i.custo_llm_usd > TECTO_DE_CUSTO_USD),
    )

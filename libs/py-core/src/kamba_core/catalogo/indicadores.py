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

## Por tenant, contra a base (KAM-231)

O criterio 5 do KAM-231 pede os numeros **por tenant**, e mais um: o tempo da
1.a foto ao 1.o produto publicado. `ler_do_tenant` le-os numa transaccao, como
`kamba_app` e com o `app.tenant_id` do tenant (RLS `FORCE`): as `publicada`
pela consulta de sempre (`SQL_PUBLICADAS_DO_TENANT`) e os dois instantes por
agregado (`SQL_INSTANTES_DO_TENANT`) — o `criado_at` nao e campo da `Ingestao`,
e acrescenta-lo mudava a leitura de todas as consultas do repositorio por uma
metrica. O tempo e `None` sem publicacao, pela regra das razoes acima.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final

from .. import tenant_guard
from . import estados
from .extraccao import IA_VISAO
from .pipeline import SUGESTAO
from .repositorio import _COLUNAS, Ingestao, _de_linha

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
    #: KAM-231. Da 1.a foto recebida a 1.a publicacao confirmada; `None` sem
    #: publicacao. So o `ler_do_tenant` o preenche.
    primeira_foto_ate_primeiro_publicado: timedelta | None = None

#: As `publicada` de um tenant, com as colunas de sempre.
SQL_PUBLICADAS_DO_TENANT: Final = (
    f"SELECT {_COLUNAS} FROM platform.catalog_ingestions "
    "WHERE tenant_id = %s::uuid AND estado = 'publicada'"
)

#: A 1.a foto e a 1.a publicacao confirmada de um tenant.
SQL_INSTANTES_DO_TENANT: Final = (
    "SELECT min(criado_at), min(confirmado_at) FILTER (WHERE estado = 'publicada') "
    "FROM platform.catalog_ingestions WHERE tenant_id = %s::uuid"
)


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


def ler_do_tenant(ligacao: Any, tenant_id: str) -> Indicadores:
    """Os indicadores de um tenant, numa transaccao com o `app.tenant_id` dele."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_PUBLICADAS_DO_TENANT, (tenant_id,))
        publicadas = [_de_linha(linha) for linha in cursor.fetchall()]
        cursor.execute(SQL_INSTANTES_DO_TENANT, (tenant_id,))
        primeira_foto, primeira_publicacao = cursor.fetchone() or (None, None)
    tempo = (
        primeira_publicacao - primeira_foto
        if primeira_foto is not None and primeira_publicacao is not None
        else None
    )
    return replace(calcular(publicadas), primeira_foto_ate_primeiro_publicado=tempo)

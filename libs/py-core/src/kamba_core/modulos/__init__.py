"""Os modulos de entrada: uso, custo do mes e orcamento (KAM-124).

| Modulo | O que tem |
|---|---|
| `uso` | o `get_usage` (read) e a mensagem estatica do orcamento esgotado |

Os quatro modulos sao os do dicionario §3.7 e do
`registry/entitlement_keys.schema.json` (`$defs.modulo_de_entrada`); um ensaio
confronta `MODULOS_DE_ENTRADA` com o registo. A coluna `entitlements.modulo`
tem `CHECK` de forma e nao de dominio, pelo que a lista fechada vive no
registo, aqui e nos `CHECK` do ledger de custo.
"""

from __future__ import annotations

from .uso import (
    CHAVE_DE_USO,
    CHAVE_DO_ORCAMENTO,
    MODULOS_DE_ENTRADA,
    MOTIVO_ORCAMENTO_ESGOTADO,
    MOTIVO_SEM_ORCAMENTO,
    SQL_GASTO_DO_MES,
    SQL_USO,
    Gasto,
    UsoDoModulo,
    gasto_do_mes,
    get_usage,
    mensagem_orcamento_esgotado,
)

__all__ = [
    "CHAVE_DE_USO",
    "CHAVE_DO_ORCAMENTO",
    "MODULOS_DE_ENTRADA",
    "MOTIVO_ORCAMENTO_ESGOTADO",
    "MOTIVO_SEM_ORCAMENTO",
    "SQL_GASTO_DO_MES",
    "SQL_USO",
    "Gasto",
    "UsoDoModulo",
    "gasto_do_mes",
    "get_usage",
    "mensagem_orcamento_esgotado",
]

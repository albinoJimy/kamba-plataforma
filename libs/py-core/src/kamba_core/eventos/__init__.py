"""`kamba_core.eventos` — o consumo idempotente de eventos (KAM-006).

Espelho em Python de `packages/core-ts/src/eventos/`, e so da parte que um
consumidor Python precisa: a transaccao do §6.3 e a maquina de estados do §6.1.

    from kamba_core.eventos import Adiar, OpcoesDoConsumo, consumir

    try:
        resultado = consumir(
            OpcoesDoConsumo(bd=cliente, consumer="com", envelope=envelope,
                            exige_ordem=True, maquina=maquina),
            aplicar_pagamento,
        )
    except Adiar as adiamento:
        reenfileirar(daqui_a=adiamento.segundos)

O envelope, a DLQ, as accoes externas e a reposicao **nao** estao aqui: o
publicador e o reconciliador sao TypeScript (KAM-005, KAM-006), e espelhar o
que ninguem chama em Python seria codigo sem chamador a envelhecer sozinho. O
que se espelha e o que um consumidor Python tem de fazer igual, ou o efeito
repete-se.
"""

from .consumo import (
    ADIAMENTO_POR_OMISSAO,
    DESFECHOS_DO_CONSUMO,
    ESCADA_DO_CONSUMIDOR,
    METRICA_CONSUMIDOS,
    METRICA_RETENTATIVAS,
    SQL_MARCAR_CONSUMIDO,
    SQL_ULTIMO_SEQ,
    TENTATIVAS,
    Adiar,
    ClienteSql,
    Efeito,
    ForaDeOrdem,
    MaquinaEmFalta,
    Metricas,
    OpcoesDoConsumo,
    Resultado,
    ResultadoDoConsumo,
    atraso_da_tentativa_do_consumidor,
    consumir,
)
from .estados import (
    ESTADO_PRETENDIDO,
    ESTADOS_DA_ENCOMENDA,
    TRANSICOES,
    ClienteDeLeitura,
    EstadoDesconhecidoError,
    MaquinaDeEstados,
    MaquinaNaBase,
    e_estado,
    pode_transitar,
)

__all__ = [
    "ADIAMENTO_POR_OMISSAO",
    "DESFECHOS_DO_CONSUMO",
    "ESCADA_DO_CONSUMIDOR",
    "ESTADOS_DA_ENCOMENDA",
    "ESTADO_PRETENDIDO",
    "METRICA_CONSUMIDOS",
    "METRICA_RETENTATIVAS",
    "SQL_MARCAR_CONSUMIDO",
    "SQL_ULTIMO_SEQ",
    "TENTATIVAS",
    "TRANSICOES",
    "Adiar",
    "ClienteDeLeitura",
    "ClienteSql",
    "Efeito",
    "EstadoDesconhecidoError",
    "ForaDeOrdem",
    "MaquinaDeEstados",
    "MaquinaEmFalta",
    "MaquinaNaBase",
    "Metricas",
    "OpcoesDoConsumo",
    "Resultado",
    "ResultadoDoConsumo",
    "atraso_da_tentativa_do_consumidor",
    "consumir",
    "e_estado",
    "pode_transitar",
]

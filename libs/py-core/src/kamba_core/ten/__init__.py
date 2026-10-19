"""TEN — entitlements, limites e a matriz de estados do CHR (KAM-009).

Espelho de `packages/core-ts/src/ten/`. TEN decide o que cada tenant pode
usar: que modulos (verticais) estao activos e que limites tem. O REG consulta o
entitlement ao activar uma vertical (`docs/tecnica/02` §5.2); a ToolLayer
verifica limites em cada `invoke` (§6.1, passo 2); o CHR usa a matriz de
estados (`01` §7.2).

    check_entitlement   falha fechada: sem linha, inactivo, ou tenant
                        `onboarding`/`suspenso`/`encerrado` -> negado
    consume_limit       atomico e idempotente, porque chama `ten_consumir`.
                        **So baldes por periodo** (`x-kamba-consumivel`)
    check_ceiling       «este valor cabe no tecto?». **So tectos por pedido**,
                        e nao escreve nada
    tenant_gate         a matriz do §7.2, com os **dois** estados
    hook_de_tool        o passo 2 do pipeline de `invoke` da TLS
    CacheDeEntitlements TTL; a alteracao fica visivel em <= 60 s
    MetricasDoTen       ten_limit_denied_total / ten_entitlement_denied_total

**A regra nao vive aqui.** A aritmetica de limites e o fuso do periodo estao na
revisao `0007` (`platform.ten_consumir`, `platform.ten_periodo`) e o criterio
do entitlement esta no `SQL_ENTITLEMENT` do `consultas.py`. Este pacote chama;
o espelho em `@kamba/core-ts/ten` chama o mesmo, e ha testes que confrontam os
dois como texto.

O `__init__.py` da raiz de `kamba_core` so re-exporta `health` e `net` — o que
todos os servicos Python precisam. Este subpacote importa-se pelo caminho
completo:

    from kamba_core.ten import check_entitlement, consume_limit, tenant_gate
"""

from .consultas import SQL_CONSUMIR, SQL_ENTITLEMENT, SQL_PERIODO, SQL_TECTO
from .entitlements import (
    CATEGORIA_CONTADOR,
    CATEGORIA_TECTO_POR_JANELA,
    CATEGORIA_TECTO_POR_PEDIDO,
    CHAVES_DE_LIMITE,
    CODIGO_ENTITLEMENT_HTTP,
    CODIGO_ENTITLEMENT_TOOL,
    CODIGO_LIMITE,
    HTTP_ENTITLEMENT,
    HTTP_LIMITE,
    HTTP_TECTO,
    MAXIMO_DE_ENTRADAS,
    NOME_CANONICO,
    SQLSTATE_CONFLITO_DE_IDEMPOTENCIA,
    TTL_POR_OMISSAO_MS,
    CacheDeEntitlements,
    ChaveDeEspecieErrada,
    ChaveDeIdempotenciaInvalida,
    ChaveDeLimite,
    ChaveDesconhecida,
    ClienteSql,
    ConflitoDeIdempotencia,
    Consumo,
    Entitlement,
    NomeInvalido,
    QuantidadeInvalida,
    RespostaIlegivel,
    Resultado,
    Tecto,
    agora_ms,
    check_ceiling,
    check_entitlement,
    consume_limit,
    derivar_chave_de_idempotencia,
    especie_da_chave,
    exigir_consumivel,
    exigir_nome,
    exigir_tecto,
    inteiro,
    periodo,
    sqlstate_de,
)
from .estados import (
    ACCOES,
    ESTADOS_DO_CANAL,
    ESTADOS_DO_TENANT,
    REGIME_DO_CANAL,
    REGIME_DO_TENANT,
    REGIMES,
    REGIMES_E_ACCOES,
    DecisaoDoGate,
    EstadoDesconhecido,
    mais_restritivo,
    regime_de,
    tenant_gate,
)
from .hook import ContextoDeTool, ErroDeTool, hook_de_tool
from .metricas import (
    ETIQUETA,
    MAXIMO_DE_SERIES,
    METRICA_ENTITLEMENT_NEGADO,
    METRICA_LIMITE_NEGADO,
    METRICAS,
    EtiquetaInvalida,
    MetricasDoTen,
)

__all__ = [
    "ACCOES",
    "CATEGORIA_CONTADOR",
    "CATEGORIA_TECTO_POR_JANELA",
    "CATEGORIA_TECTO_POR_PEDIDO",
    "CHAVES_DE_LIMITE",
    "CODIGO_ENTITLEMENT_HTTP",
    "CODIGO_ENTITLEMENT_TOOL",
    "CODIGO_LIMITE",
    "ESTADOS_DO_CANAL",
    "ESTADOS_DO_TENANT",
    "ETIQUETA",
    "HTTP_ENTITLEMENT",
    "HTTP_LIMITE",
    "HTTP_TECTO",
    "MAXIMO_DE_ENTRADAS",
    "MAXIMO_DE_SERIES",
    "METRICAS",
    "METRICA_ENTITLEMENT_NEGADO",
    "METRICA_LIMITE_NEGADO",
    "NOME_CANONICO",
    "REGIMES",
    "REGIMES_E_ACCOES",
    "REGIME_DO_CANAL",
    "REGIME_DO_TENANT",
    "SQLSTATE_CONFLITO_DE_IDEMPOTENCIA",
    "SQL_CONSUMIR",
    "SQL_ENTITLEMENT",
    "SQL_PERIODO",
    "SQL_TECTO",
    "TTL_POR_OMISSAO_MS",
    "CacheDeEntitlements",
    "ChaveDeEspecieErrada",
    "ChaveDeIdempotenciaInvalida",
    "ChaveDeLimite",
    "ChaveDesconhecida",
    "ClienteSql",
    "ConflitoDeIdempotencia",
    "Consumo",
    "ContextoDeTool",
    "DecisaoDoGate",
    "Entitlement",
    "ErroDeTool",
    "EstadoDesconhecido",
    "EtiquetaInvalida",
    "MetricasDoTen",
    "NomeInvalido",
    "QuantidadeInvalida",
    "RespostaIlegivel",
    "Resultado",
    "Tecto",
    "agora_ms",
    "check_ceiling",
    "check_entitlement",
    "consume_limit",
    "derivar_chave_de_idempotencia",
    "especie_da_chave",
    "exigir_consumivel",
    "exigir_nome",
    "exigir_tecto",
    "hook_de_tool",
    "inteiro",
    "mais_restritivo",
    "periodo",
    "regime_de",
    "sqlstate_de",
    "tenant_gate",
]

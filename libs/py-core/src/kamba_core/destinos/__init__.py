"""O *gate* de transferencia do ADR-008 (KAM-069).

Duas barreiras sobre a mesma tabela — `platform.tenant_destinations`, revisao
[`0036`](../../../../../db/migrations/versions/0036_destinos_de_transferencia.py) —
e uma regra:

    porta     `PortaSobreDestinos.autorizar(tenant_id, fornecedor, finalidade)`
              corre **antes** de cada transferencia e levanta
              `TransferenciaNegada` se nao houver destino `autorizado` com
              `apd_ref`. Negada por omissao, falha fechada em todos os
              caminhos, *cache* com o tecto de 60 s do criterio 3.

    go-live   `exigir_go_live(...)` corre na transicao `onboarding` -> `ativo`
              e recusa em `prod` se faltar destino autorizado, DPA aceite ou
              referencia do mapa de tratamentos.

**Nenhuma das duas olha para o pais**, e isso e o ponto: a lista de paises
«adequados» nao existe publicamente (NAO VERIFICADO, `docs/tecnica/08` §8.3.1), e
o codigo nunca infere adequacao. O que liberta uma chamada e a conjuncao de
`status = 'autorizado'` com `apd_ref` nao nulo.

E **hoje nenhuma linha esta autorizada**: o `ext:KAM-105` fechou com **0 de 14**
destinos com `apd_ref` (`docs/tecnica/evidencia/validacao/Seguimento_APD.md`).
A barreira esta entregue; a autorizacao para ela deixar passar nao existe.
"""

from .golive import (
    AMBIENTES,
    AMBIENTE_DEV,
    AMBIENTE_PROD,
    AMBIENTE_STAGING,
    FORMA_DO_MAPA,
    VARIAVEL_SINTETICOS,
    ConfiguracaoDeProdInvalida,
    ConfiguracaoSintetica,
    ConfiguracaoSinteticaInvalida,
    DestinoActivo,
    Falta,
    GoLiveNegado,
    avaliar_go_live,
    destinos_do_tenant,
    exigir_ambiente,
    exigir_go_live,
)
from .porta import (
    ESTADO_AUTORIZADO,
    ESTADO_NEGADO,
    ESTADO_PENDENTE,
    ESTADO_REVOGADO,
    ESTADOS,
    FINALIDADE_ALOJAMENTO,
    FINALIDADE_CANAL,
    FINALIDADE_CONVERSA,
    FINALIDADE_COPIAS,
    FINALIDADE_EMBEDDINGS,
    FINALIDADE_ENTREGA,
    FINALIDADE_FACTURACAO,
    FINALIDADE_IMAGEM,
    FINALIDADE_OBSERVABILIDADE,
    FINALIDADE_OTP,
    FINALIDADE_PAGAMENTOS,
    FINALIDADE_SEGREDOS,
    FINALIDADE_TRANSCRICAO,
    FINALIDADE_VISAO,
    FINALIDADES,
    MAXIMO_DE_ENTRADAS,
    TTL_POR_OMISSAO_MS,
    CacheDeDestinos,
    Decisao,
    FinalidadeDesconhecida,
    LeitorDeDestinos,
    PortaSobreDestinos,
    TransferenciaNegada,
    agora_ms,
    avaliar_destino,
    estado_bloqueia,
)

__all__ = [
    "AMBIENTES",
    "AMBIENTE_DEV",
    "AMBIENTE_PROD",
    "AMBIENTE_STAGING",
    "ESTADOS",
    "ESTADO_AUTORIZADO",
    "ESTADO_NEGADO",
    "ESTADO_PENDENTE",
    "ESTADO_REVOGADO",
    "FINALIDADES",
    "FINALIDADE_ALOJAMENTO",
    "FINALIDADE_CANAL",
    "FINALIDADE_CONVERSA",
    "FINALIDADE_COPIAS",
    "FINALIDADE_EMBEDDINGS",
    "FINALIDADE_ENTREGA",
    "FINALIDADE_FACTURACAO",
    "FINALIDADE_IMAGEM",
    "FINALIDADE_OBSERVABILIDADE",
    "FINALIDADE_OTP",
    "FINALIDADE_PAGAMENTOS",
    "FINALIDADE_SEGREDOS",
    "FINALIDADE_TRANSCRICAO",
    "FINALIDADE_VISAO",
    "FORMA_DO_MAPA",
    "MAXIMO_DE_ENTRADAS",
    "TTL_POR_OMISSAO_MS",
    "VARIAVEL_SINTETICOS",
    "CacheDeDestinos",
    "ConfiguracaoDeProdInvalida",
    "ConfiguracaoSintetica",
    "ConfiguracaoSinteticaInvalida",
    "Decisao",
    "DestinoActivo",
    "Falta",
    "FinalidadeDesconhecida",
    "GoLiveNegado",
    "LeitorDeDestinos",
    "PortaSobreDestinos",
    "TransferenciaNegada",
    "agora_ms",
    "avaliar_destino",
    "avaliar_go_live",
    "destinos_do_tenant",
    "estado_bloqueia",
    "exigir_ambiente",
    "exigir_go_live",
]

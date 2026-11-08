"""Os direitos do titular: acesso, rectificacao, eliminacao e oposicao (KAM-070).

Quatro operacoes sobre duas tabelas da revisao
[`0038`](../../../../../db/migrations/versions/0038_direitos_do_titular.py), e
uma regra que atravessa as quatro:

    pedido      `PortaDeDireitos.receber(...)` aceita **so do proprio
                titular** e cria a linha de `dsar_requests` com o prazo
                interno de 30 dias. Um pedido sobre os dados de outro devolve
                0 dados, levanta `PedidoDeOutroTitular` e fica no `audit_log`.

    exportacao  `exportar(cursor, pedido)` devolve o JSON portatil das quatro
                coleccoes do criterio 2; `entregar(...)` assina o URL, com o
                tecto de TTL que o `kamba_core.storage` ja tinha.

    eliminacao  `pedir_apagamento(...)` poe o `privacy.erasure_requested` no
                *outbox*; cada escopo chama `registar_aplicacao(...)`; o pedido
                so fecha quando os **seis** tem linha no `erasure_ledger`.

    oposicao    `opor(cursor, pedido)` entra na lista de supressao do KAM-022 —
                `purpose = 'marketing'`, `accepted = false` — e anuncia
                `consent.withdrawn`.

**A regra e a assinatura:** todas as operacoes recebem o `Pedido` e nao um
`contact_id`. O unico `contact_id` que um `Pedido` carrega e o de um pedido que
o `receber` aceitou, e e isso que faz o criterio 1 valer nos quatro caminhos em
vez de so no primeiro. Com um `contact_id` solto no argumento, exportar ou
apagar os dados de outra pessoa era uma chamada **bem formada** — passava os
tipos e passava a RLS, porque o contacto e do mesmo tenant.

## O que este modulo nao faz, e porque

Nao apaga nada. O apagamento do cofre **ja existe** desde o KAM-008 — o
`Identidade.eraseContact` do `packages/core-ts/src/identity/`, que poe
`contact_endpoints` a zero, preenche o `erased_at` e destroi a DEK, que e
exactamente o criterio 4 — e os outros cinco escopos sao dos processos que
detem cada loja. O que este modulo entrega e o pedido, o evento, o registo e o
fecho. Escrever aqui um segundo apagamento de cofre era a segunda versao da
mesma coisa, e a licao mais cara do KAM-069 e que duas leitoras da mesma
pergunta divergem e nenhum portao o ve.
"""

from .contrato import (
    ACCAO_RECTIFICADO,
    ACCAO_RECUSADO,
    ACCOES_DE_DSAR,
    ALERTA_AOS_DIAS,
    CANAL_DO_CONSENTIMENTO,
    CLASSE_PII,
    ESCOPO_AGR,
    ESCOPO_CHATWOOT,
    ESCOPO_COFRE,
    ESCOPO_DAT,
    ESCOPO_IDX,
    ESCOPO_STO,
    ESCOPOS,
    ESTADO_CONCLUIDO,
    ESTADO_EM_CURSO,
    ESTADO_RECEBIDO,
    ESTADOS,
    EVENTO_CONSENT_WITHDRAWN,
    EVENTO_ERASURE_APPLIED,
    EVENTO_ERASURE_REQUESTED,
    FINALIDADE_DA_OPOSICAO,
    FINALIDADES_DO_EVENTO,
    PAPEIS_DA_KAMBA,
    PAPEL_POR_OMISSAO,
    PAPEL_RESPONSAVEL,
    PAPEL_SUBCONTRATADA,
    PRAZO_INTERNO_DIAS,
    FORMA_DA_PROVA_DA_OPOSICAO,
    SEPARADOR,
    SEPARADOR_DA_PROVA,
    TEXTO_DA_OPOSICAO,
    TIPO_ELIMINACAO,
    TIPO_EXPORTACAO,
    TIPO_OPOSICAO,
    TIPO_RECTIFICACAO,
    TIPOS,
    TTL_DA_EXPORTACAO_S,
    VARIAVEL_DO_PAPEL,
    VERSAO_DOS_EVENTOS,
    ApagamentoIncompleto,
    Aplicacao,
    Assinador,
    Auditoria,
    DireitoNegado,
    EscopoDesconhecido,
    FechoSemLedger,
    PapelDesconhecido,
    Pedido,
    PedidoDeOutroTitular,
    PedidoEmCurso,
    Relogio,
    SujeitoApagado,
    TipoDesconhecido,
    exigir_escopo,
    exigir_papel,
    exigir_tipo,
    prazo_interno,
)
from .dbapi import (
    JOB_DO_RESTAURO,
    JOB_DO_VARRIMENTO,
    AbrirLigacao,
    com_tenant,
    como_lote,
)
from .eliminacao import (
    anunciar_aplicacao,
    concluir_apagamento,
    apagamento_completo,
    escopos_aplicados,
    escopos_em_falta,
    exigir_apagamento_completo,
    pedir_apagamento,
    registar_aplicacao,
    sujeitos_a_reaplicar,
    sujeitos_apagados,
)
from .exportacao import (
    CLASSE_DA_EXPORTACAO,
    ORDEM_DAS_COLECCOES,
    VERSAO_DO_FORMATO,
    documento,
    entregar,
    exportar,
    opor,
    resumo,
)
from .pedidos import (
    ACTOR_DO_TITULAR,
    ENTIDADE_DO_PEDIDO,
    INDICE_DO_PEDIDO_ABERTO,
    UNICIDADE_VIOLADA,
    AuditoriaNaBase,
    PortaDeDireitos,
    RelogioDoSistema,
)

__all__ = [
    "ACCAO_RECTIFICADO",
    "ACCAO_RECUSADO",
    "ACCOES_DE_DSAR",
    "ACTOR_DO_TITULAR",
    "ALERTA_AOS_DIAS",
    "CANAL_DO_CONSENTIMENTO",
    "CLASSE_DA_EXPORTACAO",
    "CLASSE_PII",
    "ENTIDADE_DO_PEDIDO",
    "ESCOPOS",
    "ESCOPO_AGR",
    "ESCOPO_CHATWOOT",
    "ESCOPO_COFRE",
    "ESCOPO_DAT",
    "ESCOPO_IDX",
    "ESCOPO_STO",
    "ESTADOS",
    "ESTADO_CONCLUIDO",
    "ESTADO_EM_CURSO",
    "ESTADO_RECEBIDO",
    "EVENTO_CONSENT_WITHDRAWN",
    "EVENTO_ERASURE_APPLIED",
    "EVENTO_ERASURE_REQUESTED",
    "FINALIDADES_DO_EVENTO",
    "FINALIDADE_DA_OPOSICAO",
    "FORMA_DA_PROVA_DA_OPOSICAO",
    "INDICE_DO_PEDIDO_ABERTO",
    "JOB_DO_RESTAURO",
    "JOB_DO_VARRIMENTO",
    "ORDEM_DAS_COLECCOES",
    "PAPEIS_DA_KAMBA",
    "PAPEL_POR_OMISSAO",
    "PAPEL_RESPONSAVEL",
    "PAPEL_SUBCONTRATADA",
    "PRAZO_INTERNO_DIAS",
    "SEPARADOR",
    "SEPARADOR_DA_PROVA",
    "TEXTO_DA_OPOSICAO",
    "TIPOS",
    "TIPO_ELIMINACAO",
    "TIPO_EXPORTACAO",
    "TIPO_OPOSICAO",
    "TIPO_RECTIFICACAO",
    "TTL_DA_EXPORTACAO_S",
    "UNICIDADE_VIOLADA",
    "VARIAVEL_DO_PAPEL",
    "VERSAO_DOS_EVENTOS",
    "VERSAO_DO_FORMATO",
    "AbrirLigacao",
    "ApagamentoIncompleto",
    "Aplicacao",
    "Assinador",
    "Auditoria",
    "AuditoriaNaBase",
    "DireitoNegado",
    "EscopoDesconhecido",
    "FechoSemLedger",
    "PapelDesconhecido",
    "Pedido",
    "PedidoDeOutroTitular",
    "PedidoEmCurso",
    "PortaDeDireitos",
    "RelogioDoSistema",
    "Relogio",
    "SujeitoApagado",
    "TipoDesconhecido",
    "anunciar_aplicacao",
    "apagamento_completo",
    "com_tenant",
    "como_lote",
    "concluir_apagamento",
    "documento",
    "entregar",
    "escopos_aplicados",
    "escopos_em_falta",
    "exigir_apagamento_completo",
    "exigir_escopo",
    "exigir_papel",
    "exigir_tipo",
    "exportar",
    "opor",
    "pedir_apagamento",
    "prazo_interno",
    "registar_aplicacao",
    "resumo",
    "sujeitos_a_reaplicar",
    "sujeitos_apagados",
]

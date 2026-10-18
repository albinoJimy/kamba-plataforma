/**
 * Gerado por `python -m contract_diff gerar`. Nao editar a mao.
 *
 * Os tipos dos payloads dos contratos de `contratos/eventos/`, e o catalogo
 * que o `validarPayload` le em execucao. Os dois sao precisos: um `as` nao
 * verifica nada em execucao, e um nome mal escrito nao da erro de compilacao
 * nenhum a quem le de um catalogo.
 *
 * O gate 7 (`make ci-7`) falha se este ficheiro estiver desactualizado.
 */

/** Payload de `booking.cancelled` v1. */
export interface PayloadBookingCancelled {
  readonly booking_id: string;
  readonly motivo: string;
}

/** Payload de `booking.cancelled` v2. */
export interface PayloadBookingCancelledV2 {
  readonly booking_id: string;
  readonly motivo: string;
}

/** Payload de `booking.created` v1. */
export interface PayloadBookingCreated {
  readonly booking_id: string;
  readonly contact_id: string;
  readonly service_id: string;
  readonly resource_id?: string;
  readonly inicio_at: string;
  readonly fim_at: string;
}

/** Payload de `booking.created` v2. */
export interface PayloadBookingCreatedV2 {
  readonly booking_id: string;
  readonly contact_id: string;
  readonly service_id: string;
  readonly resource_id?: string;
  readonly inicio_at: string;
  readonly fim_at: string;
}

/** Payload de `booking.reminder_due` v1. */
export interface PayloadBookingReminderDue {
  readonly booking_id: string;
  readonly inicio_at: string;
}

/** Payload de `booking.reminder_due` v2. */
export interface PayloadBookingReminderDueV2 {
  readonly booking_id: string;
  readonly inicio_at: string;
}

/** Payload de `catalog.price_changed` v1. */
export interface PayloadCatalogPriceChanged {
  readonly sku: string;
  readonly preco_tipo: "fixo" | "a_partir_de" | "sob_consulta";
  readonly preco_minor?: number | null;
  readonly currency: "AOA";
}

/** Payload de `catalog.price_changed` v2. */
export interface PayloadCatalogPriceChangedV2 {
  readonly sku: string;
  readonly preco_tipo: "fixo" | "a_partir_de" | "sob_consulta";
  readonly preco_minor?: number | null;
  readonly currency: "AOA";
}

/** Payload de `catalog.product_changed` v1. */
export interface PayloadCatalogProductChanged {
  readonly sku: string;
  readonly estado: "rascunho" | "publicado" | "pausado" | "arquivado";
}

/** Payload de `catalog.product_changed` v2. */
export interface PayloadCatalogProductChangedV2 {
  readonly sku: string;
  readonly estado: "rascunho" | "publicado" | "pausado" | "arquivado";
}

/** Payload de `channel.inactivity_warning` v1. */
export interface PayloadChannelInactivityWarning {
  readonly phone_number_id: string;
}

/** Payload de `channel.inactivity_warning` v2. */
export interface PayloadChannelInactivityWarningV2 {
  readonly phone_number_id: string;
}

/** Payload de `channel.updated` v1. */
export interface PayloadChannelUpdated {
  readonly phone_number_id: string;
  readonly motivo: string;
}

/** Payload de `channel.updated` v2. */
export interface PayloadChannelUpdatedV2 {
  readonly phone_number_id: string;
  readonly motivo: string;
}

/** Payload de `consent.recorded` v1. */
export interface PayloadConsentRecorded {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros";
  readonly origem: string;
}

/** Payload de `consent.recorded` v2. */
export interface PayloadConsentRecordedV2 {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros" | "partilha_estafeta" | "notificacao_dono";
  readonly origem: string;
}

/** Payload de `consent.withdrawn` v1. */
export interface PayloadConsentWithdrawn {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros";
}

/** Payload de `consent.withdrawn` v2. */
export interface PayloadConsentWithdrawnV2 {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros" | "partilha_estafeta" | "notificacao_dono";
}

/** Payload de `contact.merged` v1. */
export interface PayloadContactMerged {
  readonly contact_id: string;
  readonly merged_into: string;
}

/** Payload de `contact.merged` v2. */
export interface PayloadContactMergedV2 {
  readonly contact_id: string;
  readonly merged_into: string;
}

/** Payload de `conversation.mode_changed` v1. */
export interface PayloadConversationModeChanged {
  readonly thread_id: string;
  readonly channel_mode: "ai" | "humano" | "desligado";
}

/** Payload de `conversation.mode_changed` v2. */
export interface PayloadConversationModeChangedV2 {
  readonly thread_id: string;
  readonly channel_mode: "ai" | "humano" | "desligado";
}

/** Payload de `order.cancelled` v1. */
export interface PayloadOrderCancelled {
  readonly order_id: string;
  readonly motivo: string;
}

/** Payload de `order.cancelled` v2. */
export interface PayloadOrderCancelledV2 {
  readonly order_id: string;
  readonly motivo: string;
}

/** Payload de `order.created` v1. */
export interface PayloadOrderCreated {
  readonly order_id: string;
  readonly contact_id: string;
  readonly numero_publico: string;
  readonly origem: "pme" | "plataforma";
  readonly total_minor: number;
  readonly currency: "AOA";
  readonly entrega_modo: "levantamento" | "entrega";
  readonly expira_at?: string;
  readonly linhas: readonly {
    readonly sku: string;
    readonly qty: number;
    readonly preco_minor: number;
  }[];
}

/** Payload de `order.created` v2. */
export interface PayloadOrderCreatedV2 {
  readonly order_id: string;
  readonly contact_id: string;
  readonly numero_publico: string;
  readonly origem: "pme" | "plataforma";
  readonly total_minor: number;
  readonly currency: "AOA";
  readonly entrega_modo: "levantamento" | "entrega";
  readonly expira_at?: string;
  readonly linhas: readonly {
    readonly sku: string;
    readonly qty: number;
    readonly preco_minor: number;
  }[];
}

/** Payload de `order.delivered` v1. */
export interface PayloadOrderDelivered {
  readonly order_id: string;
  readonly entrega_confirmada_por: "cliente" | "dono" | "estafeta";
}

/** Payload de `order.delivered` v2. */
export interface PayloadOrderDeliveredV2 {
  readonly order_id: string;
  readonly entrega_confirmada_por: "cliente" | "dono" | "estafeta";
}

/** Payload de `order.expired` v1. */
export interface PayloadOrderExpired {
  readonly order_id: string;
  readonly expira_at: string;
}

/** Payload de `order.expired` v2. */
export interface PayloadOrderExpiredV2 {
  readonly order_id: string;
  readonly expira_at: string;
}

/** Payload de `order.paid` v1. */
export interface PayloadOrderPaid {
  readonly order_id: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly paga_via: "provider_autenticado" | "manual_auditado" | "cod_manual";
}

/** Payload de `order.paid` v2. */
export interface PayloadOrderPaidV2 {
  readonly order_id: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly paga_via: "provider_autenticado" | "manual_auditado" | "cod_manual";
}

/** Payload de `payment.confirmed` v1. */
export interface PayloadPaymentConfirmed {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly autenticacao: {
    readonly authn_method: "hmac" | "consulta";
    readonly authn_ok: true;
    readonly provider_event_id?: string;
  };
}

/** Payload de `payment.confirmed` v2. */
export interface PayloadPaymentConfirmedV2 {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly autenticacao: {
    readonly authn_method: "hmac" | "consulta";
    readonly authn_ok: true;
    readonly provider_event_id?: string;
  };
}

/** Payload de `payment.expired` v1. */
export interface PayloadPaymentExpired {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly expira_at: string;
}

/** Payload de `payment.expired` v2. */
export interface PayloadPaymentExpiredV2 {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly expira_at: string;
}

/** Payload de `payment.failed` v1. */
export interface PayloadPaymentFailed {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia?: string;
  readonly motivo: string;
}

/** Payload de `payment.failed` v2. */
export interface PayloadPaymentFailedV2 {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia?: string;
  readonly motivo: string;
}

/** Payload de `payment.manual_confirmed` v1. */
export interface PayloadPaymentManualConfirmed {
  readonly order_id: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly autenticacao: {
    readonly authn_method: "manual";
    readonly authn_ok: true;
    readonly provider_event_id?: string;
  };
}

/** Payload de `payment.manual_confirmed` v2. */
export interface PayloadPaymentManualConfirmedV2 {
  readonly order_id: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly autenticacao: {
    readonly authn_method: "manual";
    readonly authn_ok: true;
    readonly provider_event_id?: string;
  };
}

/** Payload de `payment.reference_issued` v1. */
export interface PayloadPaymentReferenceIssued {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly expira_at: string;
}

/** Payload de `payment.reference_issued` v2. */
export interface PayloadPaymentReferenceIssuedV2 {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly expira_at: string;
}

/** Payload de `privacy.erasure_applied` v1. */
export interface PayloadPrivacyErasureApplied {
  readonly contact_id: string;
}

/** Payload de `privacy.erasure_applied` v2. */
export interface PayloadPrivacyErasureAppliedV2 {
  readonly contact_id: string;
}

/** Payload de `privacy.erasure_requested` v1. */
export interface PayloadPrivacyErasureRequested {
  readonly contact_id: string;
}

/** Payload de `privacy.erasure_requested` v2. */
export interface PayloadPrivacyErasureRequestedV2 {
  readonly contact_id: string;
}

/** Payload de `query.handoff` v1. */
export interface PayloadQueryHandoff {
  readonly thread_id: string;
  readonly turn_id: string;
  readonly motivo: string;
}

/** Payload de `query.handoff` v2. */
export interface PayloadQueryHandoffV2 {
  readonly thread_id: string;
  readonly turn_id: string;
  readonly motivo: string;
}

/** Payload de `query.resolved` v1. */
export interface PayloadQueryResolved {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `query.resolved` v2. */
export interface PayloadQueryResolvedV2 {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `query.unresolved` v1. */
export interface PayloadQueryUnresolved {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `query.unresolved` v2. */
export interface PayloadQueryUnresolvedV2 {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `review.created` v1. */
export interface PayloadReviewCreated {
  readonly order_id: string;
  readonly review_id: string;
  readonly nota: number;
}

/** Payload de `review.created` v2. */
export interface PayloadReviewCreatedV2 {
  readonly order_id: string;
  readonly review_id: string;
  readonly nota: number;
}

/** Payload de `review.requested` v1. */
export interface PayloadReviewRequested {
  readonly order_id: string;
}

/** Payload de `review.requested` v2. */
export interface PayloadReviewRequestedV2 {
  readonly order_id: string;
}

/** Payload de `stock.adjusted` v1. */
export interface PayloadStockAdjusted {
  readonly sku: string;
  readonly qty: number;
  readonly motivo: string;
}

/** Payload de `stock.adjusted` v2. */
export interface PayloadStockAdjustedV2 {
  readonly sku: string;
  readonly qty: number;
  readonly motivo: string;
}

/** Payload de `stock.low` v1. */
export interface PayloadStockLow {
  readonly sku: string;
  readonly qty: number;
}

/** Payload de `stock.low` v2. */
export interface PayloadStockLowV2 {
  readonly sku: string;
  readonly qty: number;
}

/** Payload de `stock.released` v1. */
export interface PayloadStockReleased {
  readonly sku: string;
  readonly order_id: string;
  readonly qty: number;
  readonly motivo: string;
}

/** Payload de `stock.released` v2. */
export interface PayloadStockReleasedV2 {
  readonly sku: string;
  readonly order_id: string;
  readonly qty: number;
  readonly motivo: string;
}

/** Payload de `stock.reserved` v1. */
export interface PayloadStockReserved {
  readonly sku: string;
  readonly order_id: string;
  readonly qty: number;
  readonly expira_at: string;
}

/** Payload de `stock.reserved` v2. */
export interface PayloadStockReservedV2 {
  readonly sku: string;
  readonly order_id: string;
  readonly qty: number;
  readonly expira_at: string;
}

/** Payload de `tenant.activated` v1. */
export interface PayloadTenantActivated {
}

/** Payload de `tenant.activated` v2. */
export interface PayloadTenantActivatedV2 {
}

/** Payload de `tenant.approved` v1. */
export interface PayloadTenantApproved {
  readonly vertical: string;
  readonly plano: string;
}

/** Payload de `tenant.approved` v2. */
export interface PayloadTenantApprovedV2 {
  readonly vertical: string;
  readonly plano: string;
}

/** Payload de `tenant.closed` v1. */
export interface PayloadTenantClosed {
  readonly motivo: string;
}

/** Payload de `tenant.closed` v2. */
export interface PayloadTenantClosedV2 {
  readonly motivo: string;
}

/** Payload de `tenant.provisioned` v1. */
export interface PayloadTenantProvisioned {
  readonly vertical: string;
}

/** Payload de `tenant.provisioned` v2. */
export interface PayloadTenantProvisionedV2 {
  readonly vertical: string;
}

/** Payload de `tenant.reactivated` v1. */
export interface PayloadTenantReactivated {
}

/** Payload de `tenant.reactivated` v2. */
export interface PayloadTenantReactivatedV2 {
}

/** Payload de `tenant.suspended` v1. */
export interface PayloadTenantSuspended {
  readonly motivo: string;
}

/** Payload de `tenant.suspended` v2. */
export interface PayloadTenantSuspendedV2 {
  readonly motivo: string;
}

/** O que o `validarPayload` precisa de saber de cada contrato. */
export interface EntradaDoCatalogo {
  /** Todas as versoes publicadas deste tipo, por ordem crescente. */
  readonly versoes: readonly number[];
  readonly obrigatorios: readonly string[];
  readonly permitidos: readonly string[];
}

/** Todos os contratos, por tipo. A lista e fechada: um tipo fora dela e desconhecido. */
export const CATALOGO = {
  "booking.cancelled": {
    versoes: [1, 2],
    obrigatorios: ["booking_id", "motivo"],
    permitidos: ["booking_id", "motivo"],
  },
  "booking.created": {
    versoes: [1, 2],
    obrigatorios: ["booking_id", "contact_id", "fim_at", "inicio_at", "service_id"],
    permitidos: ["booking_id", "contact_id", "fim_at", "inicio_at", "resource_id", "service_id"],
  },
  "booking.reminder_due": {
    versoes: [1, 2],
    obrigatorios: ["booking_id", "inicio_at"],
    permitidos: ["booking_id", "inicio_at"],
  },
  "catalog.price_changed": {
    versoes: [1, 2],
    obrigatorios: ["currency", "preco_tipo", "sku"],
    permitidos: ["currency", "preco_minor", "preco_tipo", "sku"],
  },
  "catalog.product_changed": {
    versoes: [1, 2],
    obrigatorios: ["estado", "sku"],
    permitidos: ["estado", "sku"],
  },
  "channel.inactivity_warning": {
    versoes: [1, 2],
    obrigatorios: ["phone_number_id"],
    permitidos: ["phone_number_id"],
  },
  "channel.updated": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "phone_number_id"],
    permitidos: ["motivo", "phone_number_id"],
  },
  "consent.recorded": {
    versoes: [1, 2],
    obrigatorios: ["contact_id", "finalidade", "origem"],
    permitidos: ["contact_id", "finalidade", "origem"],
  },
  "consent.withdrawn": {
    versoes: [1, 2],
    obrigatorios: ["contact_id", "finalidade"],
    permitidos: ["contact_id", "finalidade"],
  },
  "contact.merged": {
    versoes: [1, 2],
    obrigatorios: ["contact_id", "merged_into"],
    permitidos: ["contact_id", "merged_into"],
  },
  "conversation.mode_changed": {
    versoes: [1, 2],
    obrigatorios: ["channel_mode", "thread_id"],
    permitidos: ["channel_mode", "thread_id"],
  },
  "order.cancelled": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "order_id"],
    permitidos: ["motivo", "order_id"],
  },
  "order.created": {
    versoes: [1, 2],
    obrigatorios: ["contact_id", "currency", "entrega_modo", "linhas", "numero_publico", "order_id", "origem", "total_minor"],
    permitidos: ["contact_id", "currency", "entrega_modo", "expira_at", "linhas", "numero_publico", "order_id", "origem", "total_minor"],
  },
  "order.delivered": {
    versoes: [1, 2],
    obrigatorios: ["entrega_confirmada_por", "order_id"],
    permitidos: ["entrega_confirmada_por", "order_id"],
  },
  "order.expired": {
    versoes: [1, 2],
    obrigatorios: ["expira_at", "order_id"],
    permitidos: ["expira_at", "order_id"],
  },
  "order.paid": {
    versoes: [1, 2],
    obrigatorios: ["currency", "order_id", "paga_via", "valor_minor"],
    permitidos: ["currency", "order_id", "paga_via", "valor_minor"],
  },
  "payment.confirmed": {
    versoes: [1, 2],
    obrigatorios: ["autenticacao", "currency", "order_id", "provider", "referencia", "valor_minor"],
    permitidos: ["autenticacao", "currency", "order_id", "provider", "referencia", "valor_minor"],
  },
  "payment.expired": {
    versoes: [1, 2],
    obrigatorios: ["expira_at", "order_id", "provider", "referencia"],
    permitidos: ["expira_at", "order_id", "provider", "referencia"],
  },
  "payment.failed": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "order_id", "provider"],
    permitidos: ["motivo", "order_id", "provider", "referencia"],
  },
  "payment.manual_confirmed": {
    versoes: [1, 2],
    obrigatorios: ["autenticacao", "currency", "order_id", "valor_minor"],
    permitidos: ["autenticacao", "currency", "order_id", "valor_minor"],
  },
  "payment.reference_issued": {
    versoes: [1, 2],
    obrigatorios: ["currency", "expira_at", "order_id", "provider", "referencia", "valor_minor"],
    permitidos: ["currency", "expira_at", "order_id", "provider", "referencia", "valor_minor"],
  },
  "privacy.erasure_applied": {
    versoes: [1, 2],
    obrigatorios: ["contact_id"],
    permitidos: ["contact_id"],
  },
  "privacy.erasure_requested": {
    versoes: [1, 2],
    obrigatorios: ["contact_id"],
    permitidos: ["contact_id"],
  },
  "query.handoff": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "thread_id", "turn_id"],
    permitidos: ["motivo", "thread_id", "turn_id"],
  },
  "query.resolved": {
    versoes: [1, 2],
    obrigatorios: ["thread_id", "turn_id"],
    permitidos: ["thread_id", "turn_id"],
  },
  "query.unresolved": {
    versoes: [1, 2],
    obrigatorios: ["thread_id", "turn_id"],
    permitidos: ["thread_id", "turn_id"],
  },
  "review.created": {
    versoes: [1, 2],
    obrigatorios: ["nota", "order_id", "review_id"],
    permitidos: ["nota", "order_id", "review_id"],
  },
  "review.requested": {
    versoes: [1, 2],
    obrigatorios: ["order_id"],
    permitidos: ["order_id"],
  },
  "stock.adjusted": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "qty", "sku"],
    permitidos: ["motivo", "qty", "sku"],
  },
  "stock.low": {
    versoes: [1, 2],
    obrigatorios: ["qty", "sku"],
    permitidos: ["qty", "sku"],
  },
  "stock.released": {
    versoes: [1, 2],
    obrigatorios: ["motivo", "order_id", "qty", "sku"],
    permitidos: ["motivo", "order_id", "qty", "sku"],
  },
  "stock.reserved": {
    versoes: [1, 2],
    obrigatorios: ["expira_at", "order_id", "qty", "sku"],
    permitidos: ["expira_at", "order_id", "qty", "sku"],
  },
  "tenant.activated": {
    versoes: [1, 2],
    obrigatorios: [],
    permitidos: [],
  },
  "tenant.approved": {
    versoes: [1, 2],
    obrigatorios: ["plano", "vertical"],
    permitidos: ["plano", "vertical"],
  },
  "tenant.closed": {
    versoes: [1, 2],
    obrigatorios: ["motivo"],
    permitidos: ["motivo"],
  },
  "tenant.provisioned": {
    versoes: [1, 2],
    obrigatorios: ["vertical"],
    permitidos: ["vertical"],
  },
  "tenant.reactivated": {
    versoes: [1, 2],
    obrigatorios: [],
    permitidos: [],
  },
  "tenant.suspended": {
    versoes: [1, 2],
    obrigatorios: ["motivo"],
    permitidos: ["motivo"],
  },
} as const satisfies Record<string, EntradaDoCatalogo>;

/** Os tipos de evento que tem contrato. */
export type TipoDeEvento = keyof typeof CATALOGO;

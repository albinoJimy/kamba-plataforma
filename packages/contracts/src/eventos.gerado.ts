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

/** Payload de `booking.created` v1. */
export interface PayloadBookingCreated {
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

/** Payload de `catalog.price_changed` v1. */
export interface PayloadCatalogPriceChanged {
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

/** Payload de `channel.inactivity_warning` v1. */
export interface PayloadChannelInactivityWarning {
  readonly phone_number_id: string;
}

/** Payload de `channel.updated` v1. */
export interface PayloadChannelUpdated {
  readonly phone_number_id: string;
  readonly motivo: string;
}

/** Payload de `consent.recorded` v1. */
export interface PayloadConsentRecorded {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros";
  readonly origem: string;
}

/** Payload de `consent.withdrawn` v1. */
export interface PayloadConsentWithdrawn {
  readonly contact_id: string;
  readonly finalidade: "transacao" | "atendimento" | "marketing" | "analytics_agregado" | "melhoria_servico" | "sugestoes_patrocinadas" | "partilha_loja" | "partilha_parceiros";
}

/** Payload de `contact.merged` v1. */
export interface PayloadContactMerged {
  readonly contact_id: string;
  readonly merged_into: string;
}

/** Payload de `conversation.mode_changed` v1. */
export interface PayloadConversationModeChanged {
  readonly thread_id: string;
  readonly channel_mode: "ai" | "humano" | "desligado";
}

/** Payload de `order.cancelled` v1. */
export interface PayloadOrderCancelled {
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

/** Payload de `order.delivered` v1. */
export interface PayloadOrderDelivered {
  readonly order_id: string;
  readonly entrega_confirmada_por: "cliente" | "dono" | "estafeta";
}

/** Payload de `order.expired` v1. */
export interface PayloadOrderExpired {
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

/** Payload de `payment.confirmed` v1. */
export interface PayloadPaymentConfirmed {
  readonly order_id: string;
  readonly provider: string;
  readonly referencia: string;
  readonly valor_minor: number;
  readonly currency: "AOA";
  readonly autenticacao: {
    readonly authn_method: "hmac" | "manual" | "consulta";
    readonly authn_ok: boolean;
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

/** Payload de `payment.failed` v1. */
export interface PayloadPaymentFailed {
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
    readonly authn_method: "hmac" | "manual" | "consulta";
    readonly authn_ok: boolean;
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

/** Payload de `privacy.erasure_applied` v1. */
export interface PayloadPrivacyErasureApplied {
  readonly contact_id: string;
}

/** Payload de `privacy.erasure_requested` v1. */
export interface PayloadPrivacyErasureRequested {
  readonly contact_id: string;
}

/** Payload de `query.handoff` v1. */
export interface PayloadQueryHandoff {
  readonly thread_id: string;
  readonly turn_id: string;
  readonly motivo: string;
}

/** Payload de `query.resolved` v1. */
export interface PayloadQueryResolved {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `query.unresolved` v1. */
export interface PayloadQueryUnresolved {
  readonly thread_id: string;
  readonly turn_id: string;
}

/** Payload de `review.created` v1. */
export interface PayloadReviewCreated {
  readonly order_id: string;
  readonly review_id: string;
  readonly nota: number;
}

/** Payload de `review.requested` v1. */
export interface PayloadReviewRequested {
  readonly order_id: string;
}

/** Payload de `stock.adjusted` v1. */
export interface PayloadStockAdjusted {
  readonly sku: string;
  readonly qty: number;
  readonly motivo: string;
}

/** Payload de `stock.low` v1. */
export interface PayloadStockLow {
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

/** Payload de `stock.reserved` v1. */
export interface PayloadStockReserved {
  readonly sku: string;
  readonly order_id: string;
  readonly qty: number;
  readonly expira_at: string;
}

/** Payload de `tenant.activated` v1. */
export interface PayloadTenantActivated {
}

/** Payload de `tenant.approved` v1. */
export interface PayloadTenantApproved {
  readonly vertical: string;
  readonly plano: string;
}

/** Payload de `tenant.closed` v1. */
export interface PayloadTenantClosed {
  readonly motivo: string;
}

/** Payload de `tenant.provisioned` v1. */
export interface PayloadTenantProvisioned {
  readonly vertical: string;
}

/** Payload de `tenant.reactivated` v1. */
export interface PayloadTenantReactivated {
}

/** Payload de `tenant.suspended` v1. */
export interface PayloadTenantSuspended {
  readonly motivo: string;
}

/** O que o `validarPayload` precisa de saber de cada contrato. */
export interface EntradaDoCatalogo {
  readonly versao: number;
  readonly obrigatorios: readonly string[];
  readonly permitidos: readonly string[];
}

/** Todos os contratos, por tipo. A lista e fechada: um tipo fora dela e desconhecido. */
export const CATALOGO = {
  "booking.cancelled": {
    versao: 1,
    obrigatorios: ["booking_id", "motivo"],
    permitidos: ["booking_id", "motivo"],
  },
  "booking.created": {
    versao: 1,
    obrigatorios: ["booking_id", "contact_id", "fim_at", "inicio_at", "service_id"],
    permitidos: ["booking_id", "contact_id", "fim_at", "inicio_at", "resource_id", "service_id"],
  },
  "booking.reminder_due": {
    versao: 1,
    obrigatorios: ["booking_id", "inicio_at"],
    permitidos: ["booking_id", "inicio_at"],
  },
  "catalog.price_changed": {
    versao: 1,
    obrigatorios: ["currency", "preco_tipo", "sku"],
    permitidos: ["currency", "preco_minor", "preco_tipo", "sku"],
  },
  "catalog.product_changed": {
    versao: 1,
    obrigatorios: ["estado", "sku"],
    permitidos: ["estado", "sku"],
  },
  "channel.inactivity_warning": {
    versao: 1,
    obrigatorios: ["phone_number_id"],
    permitidos: ["phone_number_id"],
  },
  "channel.updated": {
    versao: 1,
    obrigatorios: ["motivo", "phone_number_id"],
    permitidos: ["motivo", "phone_number_id"],
  },
  "consent.recorded": {
    versao: 1,
    obrigatorios: ["contact_id", "finalidade", "origem"],
    permitidos: ["contact_id", "finalidade", "origem"],
  },
  "consent.withdrawn": {
    versao: 1,
    obrigatorios: ["contact_id", "finalidade"],
    permitidos: ["contact_id", "finalidade"],
  },
  "contact.merged": {
    versao: 1,
    obrigatorios: ["contact_id", "merged_into"],
    permitidos: ["contact_id", "merged_into"],
  },
  "conversation.mode_changed": {
    versao: 1,
    obrigatorios: ["channel_mode", "thread_id"],
    permitidos: ["channel_mode", "thread_id"],
  },
  "order.cancelled": {
    versao: 1,
    obrigatorios: ["motivo", "order_id"],
    permitidos: ["motivo", "order_id"],
  },
  "order.created": {
    versao: 1,
    obrigatorios: ["contact_id", "currency", "entrega_modo", "linhas", "numero_publico", "order_id", "origem", "total_minor"],
    permitidos: ["contact_id", "currency", "entrega_modo", "expira_at", "linhas", "numero_publico", "order_id", "origem", "total_minor"],
  },
  "order.delivered": {
    versao: 1,
    obrigatorios: ["entrega_confirmada_por", "order_id"],
    permitidos: ["entrega_confirmada_por", "order_id"],
  },
  "order.expired": {
    versao: 1,
    obrigatorios: ["expira_at", "order_id"],
    permitidos: ["expira_at", "order_id"],
  },
  "order.paid": {
    versao: 1,
    obrigatorios: ["currency", "order_id", "paga_via", "valor_minor"],
    permitidos: ["currency", "order_id", "paga_via", "valor_minor"],
  },
  "payment.confirmed": {
    versao: 1,
    obrigatorios: ["autenticacao", "currency", "order_id", "provider", "referencia", "valor_minor"],
    permitidos: ["autenticacao", "currency", "order_id", "provider", "referencia", "valor_minor"],
  },
  "payment.expired": {
    versao: 1,
    obrigatorios: ["expira_at", "order_id", "provider", "referencia"],
    permitidos: ["expira_at", "order_id", "provider", "referencia"],
  },
  "payment.failed": {
    versao: 1,
    obrigatorios: ["motivo", "order_id", "provider"],
    permitidos: ["motivo", "order_id", "provider", "referencia"],
  },
  "payment.manual_confirmed": {
    versao: 1,
    obrigatorios: ["autenticacao", "currency", "order_id", "valor_minor"],
    permitidos: ["autenticacao", "currency", "order_id", "valor_minor"],
  },
  "payment.reference_issued": {
    versao: 1,
    obrigatorios: ["currency", "expira_at", "order_id", "provider", "referencia", "valor_minor"],
    permitidos: ["currency", "expira_at", "order_id", "provider", "referencia", "valor_minor"],
  },
  "privacy.erasure_applied": {
    versao: 1,
    obrigatorios: ["contact_id"],
    permitidos: ["contact_id"],
  },
  "privacy.erasure_requested": {
    versao: 1,
    obrigatorios: ["contact_id"],
    permitidos: ["contact_id"],
  },
  "query.handoff": {
    versao: 1,
    obrigatorios: ["motivo", "thread_id", "turn_id"],
    permitidos: ["motivo", "thread_id", "turn_id"],
  },
  "query.resolved": {
    versao: 1,
    obrigatorios: ["thread_id", "turn_id"],
    permitidos: ["thread_id", "turn_id"],
  },
  "query.unresolved": {
    versao: 1,
    obrigatorios: ["thread_id", "turn_id"],
    permitidos: ["thread_id", "turn_id"],
  },
  "review.created": {
    versao: 1,
    obrigatorios: ["nota", "order_id", "review_id"],
    permitidos: ["nota", "order_id", "review_id"],
  },
  "review.requested": {
    versao: 1,
    obrigatorios: ["order_id"],
    permitidos: ["order_id"],
  },
  "stock.adjusted": {
    versao: 1,
    obrigatorios: ["motivo", "qty", "sku"],
    permitidos: ["motivo", "qty", "sku"],
  },
  "stock.low": {
    versao: 1,
    obrigatorios: ["qty", "sku"],
    permitidos: ["qty", "sku"],
  },
  "stock.released": {
    versao: 1,
    obrigatorios: ["motivo", "order_id", "qty", "sku"],
    permitidos: ["motivo", "order_id", "qty", "sku"],
  },
  "stock.reserved": {
    versao: 1,
    obrigatorios: ["expira_at", "order_id", "qty", "sku"],
    permitidos: ["expira_at", "order_id", "qty", "sku"],
  },
  "tenant.activated": {
    versao: 1,
    obrigatorios: [],
    permitidos: [],
  },
  "tenant.approved": {
    versao: 1,
    obrigatorios: ["plano", "vertical"],
    permitidos: ["plano", "vertical"],
  },
  "tenant.closed": {
    versao: 1,
    obrigatorios: ["motivo"],
    permitidos: ["motivo"],
  },
  "tenant.provisioned": {
    versao: 1,
    obrigatorios: ["vertical"],
    permitidos: ["vertical"],
  },
  "tenant.reactivated": {
    versao: 1,
    obrigatorios: [],
    permitidos: [],
  },
  "tenant.suspended": {
    versao: 1,
    obrigatorios: ["motivo"],
    permitidos: ["motivo"],
  },
} as const satisfies Record<string, EntradaDoCatalogo>;

/** Os tipos de evento que tem contrato. */
export type TipoDeEvento = keyof typeof CATALOGO;

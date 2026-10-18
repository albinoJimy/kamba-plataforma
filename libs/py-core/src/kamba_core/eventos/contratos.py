"""Gerado por `python -m contract_diff gerar`. Nao editar a mao.

Os payloads dos contratos de `contratos/eventos/`, como `TypedDict`, e o
catalogo que o espelho em Python le. O gate 7 (`make ci-7`) falha se este
ficheiro estiver desactualizado.
"""

from typing import NotRequired, TypedDict


class PayloadBookingCancelled(TypedDict):
    """Payload de `booking.cancelled` v1."""
    booking_id: str
    motivo: str


class PayloadBookingCancelledV2(TypedDict):
    """Payload de `booking.cancelled` v2."""
    booking_id: str
    motivo: str


class PayloadBookingCreated(TypedDict):
    """Payload de `booking.created` v1."""
    booking_id: str
    contact_id: str
    service_id: str
    resource_id: NotRequired[str]
    inicio_at: str
    fim_at: str


class PayloadBookingCreatedV2(TypedDict):
    """Payload de `booking.created` v2."""
    booking_id: str
    contact_id: str
    service_id: str
    resource_id: NotRequired[str]
    inicio_at: str
    fim_at: str


class PayloadBookingReminderDue(TypedDict):
    """Payload de `booking.reminder_due` v1."""
    booking_id: str
    inicio_at: str


class PayloadBookingReminderDueV2(TypedDict):
    """Payload de `booking.reminder_due` v2."""
    booking_id: str
    inicio_at: str


class PayloadCatalogPriceChanged(TypedDict):
    """Payload de `catalog.price_changed` v1."""
    sku: str
    preco_tipo: str
    preco_minor: NotRequired[int | None]
    currency: str


class PayloadCatalogPriceChangedV2(TypedDict):
    """Payload de `catalog.price_changed` v2."""
    sku: str
    preco_tipo: str
    preco_minor: NotRequired[int | None]
    currency: str


class PayloadCatalogProductChanged(TypedDict):
    """Payload de `catalog.product_changed` v1."""
    sku: str
    estado: str


class PayloadCatalogProductChangedV2(TypedDict):
    """Payload de `catalog.product_changed` v2."""
    sku: str
    estado: str


class PayloadChannelInactivityWarning(TypedDict):
    """Payload de `channel.inactivity_warning` v1."""
    phone_number_id: str


class PayloadChannelInactivityWarningV2(TypedDict):
    """Payload de `channel.inactivity_warning` v2."""
    phone_number_id: str


class PayloadChannelUpdated(TypedDict):
    """Payload de `channel.updated` v1."""
    phone_number_id: str
    motivo: str


class PayloadChannelUpdatedV2(TypedDict):
    """Payload de `channel.updated` v2."""
    phone_number_id: str
    motivo: str


class PayloadConsentRecorded(TypedDict):
    """Payload de `consent.recorded` v1."""
    contact_id: str
    finalidade: str
    origem: str


class PayloadConsentRecordedV2(TypedDict):
    """Payload de `consent.recorded` v2."""
    contact_id: str
    finalidade: str
    origem: str


class PayloadConsentWithdrawn(TypedDict):
    """Payload de `consent.withdrawn` v1."""
    contact_id: str
    finalidade: str


class PayloadConsentWithdrawnV2(TypedDict):
    """Payload de `consent.withdrawn` v2."""
    contact_id: str
    finalidade: str


class PayloadContactMerged(TypedDict):
    """Payload de `contact.merged` v1."""
    contact_id: str
    merged_into: str


class PayloadContactMergedV2(TypedDict):
    """Payload de `contact.merged` v2."""
    contact_id: str
    merged_into: str


class PayloadConversationModeChanged(TypedDict):
    """Payload de `conversation.mode_changed` v1."""
    thread_id: str
    channel_mode: str


class PayloadConversationModeChangedV2(TypedDict):
    """Payload de `conversation.mode_changed` v2."""
    thread_id: str
    channel_mode: str


class PayloadOrderCancelled(TypedDict):
    """Payload de `order.cancelled` v1."""
    order_id: str
    motivo: str


class PayloadOrderCancelledV2(TypedDict):
    """Payload de `order.cancelled` v2."""
    order_id: str
    motivo: str


class PayloadOrderCreated(TypedDict):
    """Payload de `order.created` v1."""
    order_id: str
    contact_id: str
    numero_publico: str
    origem: str
    total_minor: int
    currency: str
    entrega_modo: str
    expira_at: NotRequired[str]
    linhas: list[object]


class PayloadOrderCreatedV2(TypedDict):
    """Payload de `order.created` v2."""
    order_id: str
    contact_id: str
    numero_publico: str
    origem: str
    total_minor: int
    currency: str
    entrega_modo: str
    expira_at: NotRequired[str]
    linhas: list[object]


class PayloadOrderDelivered(TypedDict):
    """Payload de `order.delivered` v1."""
    order_id: str
    entrega_confirmada_por: str


class PayloadOrderDeliveredV2(TypedDict):
    """Payload de `order.delivered` v2."""
    order_id: str
    entrega_confirmada_por: str


class PayloadOrderExpired(TypedDict):
    """Payload de `order.expired` v1."""
    order_id: str
    expira_at: str


class PayloadOrderExpiredV2(TypedDict):
    """Payload de `order.expired` v2."""
    order_id: str
    expira_at: str


class PayloadOrderPaid(TypedDict):
    """Payload de `order.paid` v1."""
    order_id: str
    valor_minor: int
    currency: str
    paga_via: str


class PayloadOrderPaidV2(TypedDict):
    """Payload de `order.paid` v2."""
    order_id: str
    valor_minor: int
    currency: str
    paga_via: str


class PayloadPaymentConfirmed(TypedDict):
    """Payload de `payment.confirmed` v1."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentConfirmedV2(TypedDict):
    """Payload de `payment.confirmed` v2."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentExpired(TypedDict):
    """Payload de `payment.expired` v1."""
    order_id: str
    provider: str
    referencia: str
    expira_at: str


class PayloadPaymentExpiredV2(TypedDict):
    """Payload de `payment.expired` v2."""
    order_id: str
    provider: str
    referencia: str
    expira_at: str


class PayloadPaymentFailed(TypedDict):
    """Payload de `payment.failed` v1."""
    order_id: str
    provider: str
    referencia: NotRequired[str]
    motivo: str


class PayloadPaymentFailedV2(TypedDict):
    """Payload de `payment.failed` v2."""
    order_id: str
    provider: str
    referencia: NotRequired[str]
    motivo: str


class PayloadPaymentManualConfirmed(TypedDict):
    """Payload de `payment.manual_confirmed` v1."""
    order_id: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentManualConfirmedV2(TypedDict):
    """Payload de `payment.manual_confirmed` v2."""
    order_id: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentReferenceIssued(TypedDict):
    """Payload de `payment.reference_issued` v1."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    expira_at: str


class PayloadPaymentReferenceIssuedV2(TypedDict):
    """Payload de `payment.reference_issued` v2."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    expira_at: str


class PayloadPrivacyErasureApplied(TypedDict):
    """Payload de `privacy.erasure_applied` v1."""
    contact_id: str


class PayloadPrivacyErasureAppliedV2(TypedDict):
    """Payload de `privacy.erasure_applied` v2."""
    contact_id: str


class PayloadPrivacyErasureRequested(TypedDict):
    """Payload de `privacy.erasure_requested` v1."""
    contact_id: str


class PayloadPrivacyErasureRequestedV2(TypedDict):
    """Payload de `privacy.erasure_requested` v2."""
    contact_id: str


class PayloadQueryHandoff(TypedDict):
    """Payload de `query.handoff` v1."""
    thread_id: str
    turn_id: str
    motivo: str


class PayloadQueryHandoffV2(TypedDict):
    """Payload de `query.handoff` v2."""
    thread_id: str
    turn_id: str
    motivo: str


class PayloadQueryResolved(TypedDict):
    """Payload de `query.resolved` v1."""
    thread_id: str
    turn_id: str


class PayloadQueryResolvedV2(TypedDict):
    """Payload de `query.resolved` v2."""
    thread_id: str
    turn_id: str


class PayloadQueryUnresolved(TypedDict):
    """Payload de `query.unresolved` v1."""
    thread_id: str
    turn_id: str


class PayloadQueryUnresolvedV2(TypedDict):
    """Payload de `query.unresolved` v2."""
    thread_id: str
    turn_id: str


class PayloadReviewCreated(TypedDict):
    """Payload de `review.created` v1."""
    order_id: str
    review_id: str
    nota: int


class PayloadReviewCreatedV2(TypedDict):
    """Payload de `review.created` v2."""
    order_id: str
    review_id: str
    nota: int


class PayloadReviewRequested(TypedDict):
    """Payload de `review.requested` v1."""
    order_id: str


class PayloadReviewRequestedV2(TypedDict):
    """Payload de `review.requested` v2."""
    order_id: str


class PayloadStockAdjusted(TypedDict):
    """Payload de `stock.adjusted` v1."""
    sku: str
    qty: int
    motivo: str


class PayloadStockAdjustedV2(TypedDict):
    """Payload de `stock.adjusted` v2."""
    sku: str
    qty: int
    motivo: str


class PayloadStockLow(TypedDict):
    """Payload de `stock.low` v1."""
    sku: str
    qty: int


class PayloadStockLowV2(TypedDict):
    """Payload de `stock.low` v2."""
    sku: str
    qty: int


class PayloadStockReleased(TypedDict):
    """Payload de `stock.released` v1."""
    sku: str
    order_id: str
    qty: int
    motivo: str


class PayloadStockReleasedV2(TypedDict):
    """Payload de `stock.released` v2."""
    sku: str
    order_id: str
    qty: int
    motivo: str


class PayloadStockReserved(TypedDict):
    """Payload de `stock.reserved` v1."""
    sku: str
    order_id: str
    qty: int
    expira_at: str


class PayloadStockReservedV2(TypedDict):
    """Payload de `stock.reserved` v2."""
    sku: str
    order_id: str
    qty: int
    expira_at: str


class PayloadTenantActivated(TypedDict):
    """Payload de `tenant.activated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantActivatedV2(TypedDict):
    """Payload de `tenant.activated` v2."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantApproved(TypedDict):
    """Payload de `tenant.approved` v1."""
    vertical: str
    plano: str


class PayloadTenantApprovedV2(TypedDict):
    """Payload de `tenant.approved` v2."""
    vertical: str
    plano: str


class PayloadTenantClosed(TypedDict):
    """Payload de `tenant.closed` v1."""
    motivo: str


class PayloadTenantClosedV2(TypedDict):
    """Payload de `tenant.closed` v2."""
    motivo: str


class PayloadTenantProvisioned(TypedDict):
    """Payload de `tenant.provisioned` v1."""
    vertical: str


class PayloadTenantProvisionedV2(TypedDict):
    """Payload de `tenant.provisioned` v2."""
    vertical: str


class PayloadTenantReactivated(TypedDict):
    """Payload de `tenant.reactivated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantReactivatedV2(TypedDict):
    """Payload de `tenant.reactivated` v2."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantSuspended(TypedDict):
    """Payload de `tenant.suspended` v1."""
    motivo: str


class PayloadTenantSuspendedV2(TypedDict):
    """Payload de `tenant.suspended` v2."""
    motivo: str


#: Todos os contratos, por tipo. Lista fechada.
CATALOGO: dict[str, dict[str, object]] = {
    "booking.cancelled": {
        "versoes": [1, 2],
        "obrigatorios": ['booking_id', 'motivo'],
        "permitidos": ['booking_id', 'motivo'],
    },
    "booking.created": {
        "versoes": [1, 2],
        "obrigatorios": ['booking_id', 'contact_id', 'fim_at', 'inicio_at', 'service_id'],
        "permitidos": ['booking_id', 'contact_id', 'fim_at', 'inicio_at', 'resource_id', 'service_id'],
    },
    "booking.reminder_due": {
        "versoes": [1, 2],
        "obrigatorios": ['booking_id', 'inicio_at'],
        "permitidos": ['booking_id', 'inicio_at'],
    },
    "catalog.price_changed": {
        "versoes": [1, 2],
        "obrigatorios": ['currency', 'preco_tipo', 'sku'],
        "permitidos": ['currency', 'preco_minor', 'preco_tipo', 'sku'],
    },
    "catalog.product_changed": {
        "versoes": [1, 2],
        "obrigatorios": ['estado', 'sku'],
        "permitidos": ['estado', 'sku'],
    },
    "channel.inactivity_warning": {
        "versoes": [1, 2],
        "obrigatorios": ['phone_number_id'],
        "permitidos": ['phone_number_id'],
    },
    "channel.updated": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'phone_number_id'],
        "permitidos": ['motivo', 'phone_number_id'],
    },
    "consent.recorded": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id', 'finalidade', 'origem'],
        "permitidos": ['contact_id', 'finalidade', 'origem'],
    },
    "consent.withdrawn": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id', 'finalidade'],
        "permitidos": ['contact_id', 'finalidade'],
    },
    "contact.merged": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id', 'merged_into'],
        "permitidos": ['contact_id', 'merged_into'],
    },
    "conversation.mode_changed": {
        "versoes": [1, 2],
        "obrigatorios": ['channel_mode', 'thread_id'],
        "permitidos": ['channel_mode', 'thread_id'],
    },
    "order.cancelled": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'order_id'],
        "permitidos": ['motivo', 'order_id'],
    },
    "order.created": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id', 'currency', 'entrega_modo', 'linhas', 'numero_publico', 'order_id', 'origem', 'total_minor'],
        "permitidos": ['contact_id', 'currency', 'entrega_modo', 'expira_at', 'linhas', 'numero_publico', 'order_id', 'origem', 'total_minor'],
    },
    "order.delivered": {
        "versoes": [1, 2],
        "obrigatorios": ['entrega_confirmada_por', 'order_id'],
        "permitidos": ['entrega_confirmada_por', 'order_id'],
    },
    "order.expired": {
        "versoes": [1, 2],
        "obrigatorios": ['expira_at', 'order_id'],
        "permitidos": ['expira_at', 'order_id'],
    },
    "order.paid": {
        "versoes": [1, 2],
        "obrigatorios": ['currency', 'order_id', 'paga_via', 'valor_minor'],
        "permitidos": ['currency', 'order_id', 'paga_via', 'valor_minor'],
    },
    "payment.confirmed": {
        "versoes": [1, 2],
        "obrigatorios": ['autenticacao', 'currency', 'order_id', 'provider', 'referencia', 'valor_minor'],
        "permitidos": ['autenticacao', 'currency', 'order_id', 'provider', 'referencia', 'valor_minor'],
    },
    "payment.expired": {
        "versoes": [1, 2],
        "obrigatorios": ['expira_at', 'order_id', 'provider', 'referencia'],
        "permitidos": ['expira_at', 'order_id', 'provider', 'referencia'],
    },
    "payment.failed": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'order_id', 'provider'],
        "permitidos": ['motivo', 'order_id', 'provider', 'referencia'],
    },
    "payment.manual_confirmed": {
        "versoes": [1, 2],
        "obrigatorios": ['autenticacao', 'currency', 'order_id', 'valor_minor'],
        "permitidos": ['autenticacao', 'currency', 'order_id', 'valor_minor'],
    },
    "payment.reference_issued": {
        "versoes": [1, 2],
        "obrigatorios": ['currency', 'expira_at', 'order_id', 'provider', 'referencia', 'valor_minor'],
        "permitidos": ['currency', 'expira_at', 'order_id', 'provider', 'referencia', 'valor_minor'],
    },
    "privacy.erasure_applied": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id'],
        "permitidos": ['contact_id'],
    },
    "privacy.erasure_requested": {
        "versoes": [1, 2],
        "obrigatorios": ['contact_id'],
        "permitidos": ['contact_id'],
    },
    "query.handoff": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'thread_id', 'turn_id'],
        "permitidos": ['motivo', 'thread_id', 'turn_id'],
    },
    "query.resolved": {
        "versoes": [1, 2],
        "obrigatorios": ['thread_id', 'turn_id'],
        "permitidos": ['thread_id', 'turn_id'],
    },
    "query.unresolved": {
        "versoes": [1, 2],
        "obrigatorios": ['thread_id', 'turn_id'],
        "permitidos": ['thread_id', 'turn_id'],
    },
    "review.created": {
        "versoes": [1, 2],
        "obrigatorios": ['nota', 'order_id', 'review_id'],
        "permitidos": ['nota', 'order_id', 'review_id'],
    },
    "review.requested": {
        "versoes": [1, 2],
        "obrigatorios": ['order_id'],
        "permitidos": ['order_id'],
    },
    "stock.adjusted": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'qty', 'sku'],
        "permitidos": ['motivo', 'qty', 'sku'],
    },
    "stock.low": {
        "versoes": [1, 2],
        "obrigatorios": ['qty', 'sku'],
        "permitidos": ['qty', 'sku'],
    },
    "stock.released": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo', 'order_id', 'qty', 'sku'],
        "permitidos": ['motivo', 'order_id', 'qty', 'sku'],
    },
    "stock.reserved": {
        "versoes": [1, 2],
        "obrigatorios": ['expira_at', 'order_id', 'qty', 'sku'],
        "permitidos": ['expira_at', 'order_id', 'qty', 'sku'],
    },
    "tenant.activated": {
        "versoes": [1, 2],
        "obrigatorios": [],
        "permitidos": [],
    },
    "tenant.approved": {
        "versoes": [1, 2],
        "obrigatorios": ['plano', 'vertical'],
        "permitidos": ['plano', 'vertical'],
    },
    "tenant.closed": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo'],
        "permitidos": ['motivo'],
    },
    "tenant.provisioned": {
        "versoes": [1, 2],
        "obrigatorios": ['vertical'],
        "permitidos": ['vertical'],
    },
    "tenant.reactivated": {
        "versoes": [1, 2],
        "obrigatorios": [],
        "permitidos": [],
    },
    "tenant.suspended": {
        "versoes": [1, 2],
        "obrigatorios": ['motivo'],
        "permitidos": ['motivo'],
    },
}


class TipoDesconhecidoError(ValueError):
    """Um tipo de evento que nao tem contrato."""


class VersaoDesconhecidaError(ValueError):
    """Uma versao que nao e a do contrato publicado."""


class PayloadInvalidoError(ValueError):
    """O payload nao bate com o contrato: falta obrigatorio ou sobra campo."""


def tipos_com_contrato() -> list[str]:
    """Os tipos de evento que tem contrato publicado, por ordem."""
    return sorted(CATALOGO)


def validar_payload(tipo: str, versao: int, payload: dict) -> None:
    """Recusa o que o contrato nao admite, antes de o evento ser emitido.

    O espelho do `validarPayload` de `@kamba/core-ts`, com o **mesmo limite**:
    verifica o tipo, a versao, os campos obrigatorios e os campos a mais, e
    **nao** verifica tipos nem formatos — isso e JSON Schema completo em
    execucao, que e uma dependencia que o lado Python nao tem no caminho de
    emissao. Os tipos sao do verificador estatico, pelo `Payload*` gerado
    acima, que desde o KAM-007 distingue obrigatorio de opcional.
    """
    entrada = CATALOGO.get(tipo)
    if entrada is None:
        raise TipoDesconhecidoError(
            f"{tipo} nao tem contrato em contratos/eventos/; "
            f"os que tem: {', '.join(tipos_com_contrato())}"
        )
    versoes = entrada["versoes"]
    if versao not in versoes:
        publicadas = ", ".join(f"v{v}" for v in versoes)
        raise VersaoDesconhecidaError(
            f"{tipo} v{versao}: as versoes publicadas sao {publicadas}"
        )
    if not isinstance(payload, dict):
        raise PayloadInvalidoError(f"{tipo}: o payload tem de ser um objecto")
    obrigatorios = set(entrada["obrigatorios"])
    permitidos = set(entrada["permitidos"])
    em_falta = sorted(obrigatorios - set(payload))
    se_sobra = sorted(set(payload) - permitidos)
    if em_falta or se_sobra:
        partes = []
        if em_falta:
            partes.append(f"faltam {em_falta}")
        if se_sobra:
            partes.append(f"sobram {se_sobra} (o contrato e fechado)")
        raise PayloadInvalidoError(f"{tipo} v{versao}: " + "; ".join(partes))

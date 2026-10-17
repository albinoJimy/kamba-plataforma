"""Gerado por `python -m contract_diff gerar`. Nao editar a mao.

Os payloads dos contratos de `contratos/eventos/`, como `TypedDict`, e o
catalogo que o espelho em Python le. O gate 7 (`make ci-7`) falha se este
ficheiro estiver desactualizado.
"""

from __future__ import annotations

from typing import TypedDict


class PayloadBookingCancelled(TypedDict, total=False):
    """Payload de `booking.cancelled` v1."""
    booking_id: str
    motivo: str


class PayloadBookingCreated(TypedDict, total=False):
    """Payload de `booking.created` v1."""
    booking_id: str
    contact_id: str
    service_id: str
    resource_id: str  # opcional
    inicio_at: str
    fim_at: str


class PayloadBookingReminderDue(TypedDict, total=False):
    """Payload de `booking.reminder_due` v1."""
    booking_id: str
    inicio_at: str


class PayloadCatalogPriceChanged(TypedDict, total=False):
    """Payload de `catalog.price_changed` v1."""
    sku: str
    preco_tipo: str
    preco_minor: int | None  # opcional
    currency: str


class PayloadCatalogProductChanged(TypedDict, total=False):
    """Payload de `catalog.product_changed` v1."""
    sku: str
    estado: str


class PayloadChannelInactivityWarning(TypedDict, total=False):
    """Payload de `channel.inactivity_warning` v1."""
    phone_number_id: str


class PayloadChannelUpdated(TypedDict, total=False):
    """Payload de `channel.updated` v1."""
    phone_number_id: str
    motivo: str


class PayloadConsentRecorded(TypedDict, total=False):
    """Payload de `consent.recorded` v1."""
    contact_id: str
    finalidade: str
    origem: str


class PayloadConsentWithdrawn(TypedDict, total=False):
    """Payload de `consent.withdrawn` v1."""
    contact_id: str
    finalidade: str


class PayloadContactMerged(TypedDict, total=False):
    """Payload de `contact.merged` v1."""
    contact_id: str
    merged_into: str


class PayloadConversationModeChanged(TypedDict, total=False):
    """Payload de `conversation.mode_changed` v1."""
    thread_id: str
    channel_mode: str


class PayloadOrderCancelled(TypedDict, total=False):
    """Payload de `order.cancelled` v1."""
    order_id: str
    motivo: str


class PayloadOrderCreated(TypedDict, total=False):
    """Payload de `order.created` v1."""
    order_id: str
    contact_id: str
    numero_publico: str
    origem: str
    total_minor: int
    currency: str
    entrega_modo: str
    expira_at: str  # opcional
    linhas: list[object]


class PayloadOrderDelivered(TypedDict, total=False):
    """Payload de `order.delivered` v1."""
    order_id: str
    entrega_confirmada_por: str


class PayloadOrderExpired(TypedDict, total=False):
    """Payload de `order.expired` v1."""
    order_id: str
    expira_at: str


class PayloadOrderPaid(TypedDict, total=False):
    """Payload de `order.paid` v1."""
    order_id: str
    valor_minor: int
    currency: str
    paga_via: str


class PayloadPaymentConfirmed(TypedDict, total=False):
    """Payload de `payment.confirmed` v1."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentExpired(TypedDict, total=False):
    """Payload de `payment.expired` v1."""
    order_id: str
    provider: str
    referencia: str
    expira_at: str


class PayloadPaymentFailed(TypedDict, total=False):
    """Payload de `payment.failed` v1."""
    order_id: str
    provider: str
    referencia: str  # opcional
    motivo: str


class PayloadPaymentManualConfirmed(TypedDict, total=False):
    """Payload de `payment.manual_confirmed` v1."""
    order_id: str
    valor_minor: int
    currency: str
    autenticacao: dict[str, object]


class PayloadPaymentReferenceIssued(TypedDict, total=False):
    """Payload de `payment.reference_issued` v1."""
    order_id: str
    provider: str
    referencia: str
    valor_minor: int
    currency: str
    expira_at: str


class PayloadPrivacyErasureApplied(TypedDict, total=False):
    """Payload de `privacy.erasure_applied` v1."""
    contact_id: str


class PayloadPrivacyErasureRequested(TypedDict, total=False):
    """Payload de `privacy.erasure_requested` v1."""
    contact_id: str


class PayloadQueryHandoff(TypedDict, total=False):
    """Payload de `query.handoff` v1."""
    thread_id: str
    turn_id: str
    motivo: str


class PayloadQueryResolved(TypedDict, total=False):
    """Payload de `query.resolved` v1."""
    thread_id: str
    turn_id: str


class PayloadQueryUnresolved(TypedDict, total=False):
    """Payload de `query.unresolved` v1."""
    thread_id: str
    turn_id: str


class PayloadReviewCreated(TypedDict, total=False):
    """Payload de `review.created` v1."""
    order_id: str
    review_id: str
    nota: int


class PayloadReviewRequested(TypedDict, total=False):
    """Payload de `review.requested` v1."""
    order_id: str


class PayloadStockAdjusted(TypedDict, total=False):
    """Payload de `stock.adjusted` v1."""
    sku: str
    qty: int
    motivo: str


class PayloadStockLow(TypedDict, total=False):
    """Payload de `stock.low` v1."""
    sku: str
    qty: int


class PayloadStockReleased(TypedDict, total=False):
    """Payload de `stock.released` v1."""
    sku: str
    order_id: str
    qty: int
    motivo: str


class PayloadStockReserved(TypedDict, total=False):
    """Payload de `stock.reserved` v1."""
    sku: str
    order_id: str
    qty: int
    expira_at: str


class PayloadTenantActivated(TypedDict, total=False):
    """Payload de `tenant.activated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantApproved(TypedDict, total=False):
    """Payload de `tenant.approved` v1."""
    vertical: str
    plano: str


class PayloadTenantClosed(TypedDict, total=False):
    """Payload de `tenant.closed` v1."""
    motivo: str


class PayloadTenantProvisioned(TypedDict, total=False):
    """Payload de `tenant.provisioned` v1."""
    vertical: str


class PayloadTenantReactivated(TypedDict, total=False):
    """Payload de `tenant.reactivated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantSuspended(TypedDict, total=False):
    """Payload de `tenant.suspended` v1."""
    motivo: str


#: Todos os contratos, por tipo. Lista fechada.
CATALOGO: dict[str, dict[str, object]] = {
    "booking.cancelled": {
        "versao": 1,
        "obrigatorios": ['booking_id', 'motivo'],
        "permitidos": ['booking_id', 'motivo'],
    },
    "booking.created": {
        "versao": 1,
        "obrigatorios": ['booking_id', 'contact_id', 'fim_at', 'inicio_at', 'service_id'],
        "permitidos": ['booking_id', 'contact_id', 'fim_at', 'inicio_at', 'resource_id', 'service_id'],
    },
    "booking.reminder_due": {
        "versao": 1,
        "obrigatorios": ['booking_id', 'inicio_at'],
        "permitidos": ['booking_id', 'inicio_at'],
    },
    "catalog.price_changed": {
        "versao": 1,
        "obrigatorios": ['currency', 'preco_tipo', 'sku'],
        "permitidos": ['currency', 'preco_minor', 'preco_tipo', 'sku'],
    },
    "catalog.product_changed": {
        "versao": 1,
        "obrigatorios": ['estado', 'sku'],
        "permitidos": ['estado', 'sku'],
    },
    "channel.inactivity_warning": {
        "versao": 1,
        "obrigatorios": ['phone_number_id'],
        "permitidos": ['phone_number_id'],
    },
    "channel.updated": {
        "versao": 1,
        "obrigatorios": ['motivo', 'phone_number_id'],
        "permitidos": ['motivo', 'phone_number_id'],
    },
    "consent.recorded": {
        "versao": 1,
        "obrigatorios": ['contact_id', 'finalidade', 'origem'],
        "permitidos": ['contact_id', 'finalidade', 'origem'],
    },
    "consent.withdrawn": {
        "versao": 1,
        "obrigatorios": ['contact_id', 'finalidade'],
        "permitidos": ['contact_id', 'finalidade'],
    },
    "contact.merged": {
        "versao": 1,
        "obrigatorios": ['contact_id', 'merged_into'],
        "permitidos": ['contact_id', 'merged_into'],
    },
    "conversation.mode_changed": {
        "versao": 1,
        "obrigatorios": ['channel_mode', 'thread_id'],
        "permitidos": ['channel_mode', 'thread_id'],
    },
    "order.cancelled": {
        "versao": 1,
        "obrigatorios": ['motivo', 'order_id'],
        "permitidos": ['motivo', 'order_id'],
    },
    "order.created": {
        "versao": 1,
        "obrigatorios": ['contact_id', 'currency', 'entrega_modo', 'linhas', 'numero_publico', 'order_id', 'origem', 'total_minor'],
        "permitidos": ['contact_id', 'currency', 'entrega_modo', 'expira_at', 'linhas', 'numero_publico', 'order_id', 'origem', 'total_minor'],
    },
    "order.delivered": {
        "versao": 1,
        "obrigatorios": ['entrega_confirmada_por', 'order_id'],
        "permitidos": ['entrega_confirmada_por', 'order_id'],
    },
    "order.expired": {
        "versao": 1,
        "obrigatorios": ['expira_at', 'order_id'],
        "permitidos": ['expira_at', 'order_id'],
    },
    "order.paid": {
        "versao": 1,
        "obrigatorios": ['currency', 'order_id', 'paga_via', 'valor_minor'],
        "permitidos": ['currency', 'order_id', 'paga_via', 'valor_minor'],
    },
    "payment.confirmed": {
        "versao": 1,
        "obrigatorios": ['autenticacao', 'currency', 'order_id', 'provider', 'referencia', 'valor_minor'],
        "permitidos": ['autenticacao', 'currency', 'order_id', 'provider', 'referencia', 'valor_minor'],
    },
    "payment.expired": {
        "versao": 1,
        "obrigatorios": ['expira_at', 'order_id', 'provider', 'referencia'],
        "permitidos": ['expira_at', 'order_id', 'provider', 'referencia'],
    },
    "payment.failed": {
        "versao": 1,
        "obrigatorios": ['motivo', 'order_id', 'provider'],
        "permitidos": ['motivo', 'order_id', 'provider', 'referencia'],
    },
    "payment.manual_confirmed": {
        "versao": 1,
        "obrigatorios": ['autenticacao', 'currency', 'order_id', 'valor_minor'],
        "permitidos": ['autenticacao', 'currency', 'order_id', 'valor_minor'],
    },
    "payment.reference_issued": {
        "versao": 1,
        "obrigatorios": ['currency', 'expira_at', 'order_id', 'provider', 'referencia', 'valor_minor'],
        "permitidos": ['currency', 'expira_at', 'order_id', 'provider', 'referencia', 'valor_minor'],
    },
    "privacy.erasure_applied": {
        "versao": 1,
        "obrigatorios": ['contact_id'],
        "permitidos": ['contact_id'],
    },
    "privacy.erasure_requested": {
        "versao": 1,
        "obrigatorios": ['contact_id'],
        "permitidos": ['contact_id'],
    },
    "query.handoff": {
        "versao": 1,
        "obrigatorios": ['motivo', 'thread_id', 'turn_id'],
        "permitidos": ['motivo', 'thread_id', 'turn_id'],
    },
    "query.resolved": {
        "versao": 1,
        "obrigatorios": ['thread_id', 'turn_id'],
        "permitidos": ['thread_id', 'turn_id'],
    },
    "query.unresolved": {
        "versao": 1,
        "obrigatorios": ['thread_id', 'turn_id'],
        "permitidos": ['thread_id', 'turn_id'],
    },
    "review.created": {
        "versao": 1,
        "obrigatorios": ['nota', 'order_id', 'review_id'],
        "permitidos": ['nota', 'order_id', 'review_id'],
    },
    "review.requested": {
        "versao": 1,
        "obrigatorios": ['order_id'],
        "permitidos": ['order_id'],
    },
    "stock.adjusted": {
        "versao": 1,
        "obrigatorios": ['motivo', 'qty', 'sku'],
        "permitidos": ['motivo', 'qty', 'sku'],
    },
    "stock.low": {
        "versao": 1,
        "obrigatorios": ['qty', 'sku'],
        "permitidos": ['qty', 'sku'],
    },
    "stock.released": {
        "versao": 1,
        "obrigatorios": ['motivo', 'order_id', 'qty', 'sku'],
        "permitidos": ['motivo', 'order_id', 'qty', 'sku'],
    },
    "stock.reserved": {
        "versao": 1,
        "obrigatorios": ['expira_at', 'order_id', 'qty', 'sku'],
        "permitidos": ['expira_at', 'order_id', 'qty', 'sku'],
    },
    "tenant.activated": {
        "versao": 1,
        "obrigatorios": [],
        "permitidos": [],
    },
    "tenant.approved": {
        "versao": 1,
        "obrigatorios": ['plano', 'vertical'],
        "permitidos": ['plano', 'vertical'],
    },
    "tenant.closed": {
        "versao": 1,
        "obrigatorios": ['motivo'],
        "permitidos": ['motivo'],
    },
    "tenant.provisioned": {
        "versao": 1,
        "obrigatorios": ['vertical'],
        "permitidos": ['vertical'],
    },
    "tenant.reactivated": {
        "versao": 1,
        "obrigatorios": [],
        "permitidos": [],
    },
    "tenant.suspended": {
        "versao": 1,
        "obrigatorios": ['motivo'],
        "permitidos": ['motivo'],
    },
}

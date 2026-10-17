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


class PayloadBookingCreated(TypedDict):
    """Payload de `booking.created` v1."""
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


class PayloadCatalogPriceChanged(TypedDict):
    """Payload de `catalog.price_changed` v1."""
    sku: str
    preco_tipo: str
    preco_minor: NotRequired[int | None]
    currency: str


class PayloadCatalogProductChanged(TypedDict):
    """Payload de `catalog.product_changed` v1."""
    sku: str
    estado: str


class PayloadChannelInactivityWarning(TypedDict):
    """Payload de `channel.inactivity_warning` v1."""
    phone_number_id: str


class PayloadChannelUpdated(TypedDict):
    """Payload de `channel.updated` v1."""
    phone_number_id: str
    motivo: str


class PayloadConsentRecorded(TypedDict):
    """Payload de `consent.recorded` v1."""
    contact_id: str
    finalidade: str
    origem: str


class PayloadConsentWithdrawn(TypedDict):
    """Payload de `consent.withdrawn` v1."""
    contact_id: str
    finalidade: str


class PayloadContactMerged(TypedDict):
    """Payload de `contact.merged` v1."""
    contact_id: str
    merged_into: str


class PayloadConversationModeChanged(TypedDict):
    """Payload de `conversation.mode_changed` v1."""
    thread_id: str
    channel_mode: str


class PayloadOrderCancelled(TypedDict):
    """Payload de `order.cancelled` v1."""
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


class PayloadOrderDelivered(TypedDict):
    """Payload de `order.delivered` v1."""
    order_id: str
    entrega_confirmada_por: str


class PayloadOrderExpired(TypedDict):
    """Payload de `order.expired` v1."""
    order_id: str
    expira_at: str


class PayloadOrderPaid(TypedDict):
    """Payload de `order.paid` v1."""
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


class PayloadPaymentExpired(TypedDict):
    """Payload de `payment.expired` v1."""
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


class PayloadPaymentManualConfirmed(TypedDict):
    """Payload de `payment.manual_confirmed` v1."""
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


class PayloadPrivacyErasureApplied(TypedDict):
    """Payload de `privacy.erasure_applied` v1."""
    contact_id: str


class PayloadPrivacyErasureRequested(TypedDict):
    """Payload de `privacy.erasure_requested` v1."""
    contact_id: str


class PayloadQueryHandoff(TypedDict):
    """Payload de `query.handoff` v1."""
    thread_id: str
    turn_id: str
    motivo: str


class PayloadQueryResolved(TypedDict):
    """Payload de `query.resolved` v1."""
    thread_id: str
    turn_id: str


class PayloadQueryUnresolved(TypedDict):
    """Payload de `query.unresolved` v1."""
    thread_id: str
    turn_id: str


class PayloadReviewCreated(TypedDict):
    """Payload de `review.created` v1."""
    order_id: str
    review_id: str
    nota: int


class PayloadReviewRequested(TypedDict):
    """Payload de `review.requested` v1."""
    order_id: str


class PayloadStockAdjusted(TypedDict):
    """Payload de `stock.adjusted` v1."""
    sku: str
    qty: int
    motivo: str


class PayloadStockLow(TypedDict):
    """Payload de `stock.low` v1."""
    sku: str
    qty: int


class PayloadStockReleased(TypedDict):
    """Payload de `stock.released` v1."""
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


class PayloadTenantActivated(TypedDict):
    """Payload de `tenant.activated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantApproved(TypedDict):
    """Payload de `tenant.approved` v1."""
    vertical: str
    plano: str


class PayloadTenantClosed(TypedDict):
    """Payload de `tenant.closed` v1."""
    motivo: str


class PayloadTenantProvisioned(TypedDict):
    """Payload de `tenant.provisioned` v1."""
    vertical: str


class PayloadTenantReactivated(TypedDict):
    """Payload de `tenant.reactivated` v1."""
    # Sem campos: o envelope ja diz tudo o que este evento diz.


class PayloadTenantSuspended(TypedDict):
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
    if versao != entrada["versao"]:
        raise VersaoDesconhecidaError(
            f"{tipo} v{versao}: o contrato publicado e a v{entrada['versao']}"
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

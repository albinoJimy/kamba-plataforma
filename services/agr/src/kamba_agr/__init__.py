"""AGR — runtime de agentes da KAMBÁ; esqueleto (KAM-001).

Aqui ainda nao ha agente nenhum. O grafo LangGraph (biblioteca MIT, ADR-002), o
`langgraph-checkpoint-postgres`, a ToolLayer e o consumidor da fila entram no
EPIC-03 (KAM-023 e seguintes). O que o KAM-001 entrega e o lugar onde isso vai
viver, com a mesma sonda `/healthz` que os servicos Node.
"""

from .meta import SERVICE, VERSION

__all__ = ["SERVICE", "VERSION", "create_app"]


def create_app():
    """Importacao tardia para que `meta` seja legivel sem Starlette instalado."""
    from .app import create_app as _create_app

    return _create_app()

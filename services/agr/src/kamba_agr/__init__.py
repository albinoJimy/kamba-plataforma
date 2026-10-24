"""AGR — runtime de agentes da KAMBÁ.

O KAM-001 deixou aqui o lugar: a sonda `/healthz` e mais nada. O KAM-025 enche-o
com o **esqueleto do servico** — workers assincronos atras da fila, um turno por
conversa, tectos de concorrencia, a API interna minima e as guardas do ADR-002 —
e continua a nao haver agente nenhum:

| O que falta | Ticket |
|---|---|
| Checkpointer Postgres no esquema `lg` | KAM-026 |
| AgentRegistry e validacao no arranque | KAM-027 |
| ToolLayer | KAM-028 |
| Grafo do Vendedor | KAM-031 |
| Grafo de Servicos | KAM-035 |

Enquanto o KAM-027 nao registar grafos, `/internal/turn` com uma invocacao
valida responde **503** com `Retry-After` e a mensagem fica na fila. E o estado
honesto de um esqueleto, e esta escrito em `../../../../docs/agr.md`.

O desenho — quem consome a fila `agr-inbound` e o que serializa um turno — esta
em `docs/adr/ADR-L004-fila-e-tranca-do-agr.md`.
"""

from .meta import SERVICE, VERSION

__all__ = ["SERVICE", "VERSION", "create_app"]


def create_app(rotas_internas=None):
    """Importacao tardia para que `meta` seja legivel sem Starlette instalado."""
    from .app import create_app as _create_app

    return _create_app(rotas_internas)

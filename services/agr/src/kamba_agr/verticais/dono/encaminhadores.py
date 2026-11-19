"""Os encaminhadores do grafo do dono — funcoes puras do estado.

Oito dos nove vem do `verticais/vendedor/encaminhadores.py` tal como estao, e
pela razao do de Servicos: as transicoes do esqueleto sao as do §7.3 palavra
por palavra. O unico proprio e o `r_intent`, porque as intencoes do dono nao sao
as do Vendedor. Cai para o lado seguro: uma intencao fora da lista vai ao
`safe_reply`, nunca ao `compose`.
"""

from __future__ import annotations

from typing import Any, Final

from ..vendedor.encaminhadores import (
    r_cite,
    r_draft,
    r_guard,
    r_handoff,
    r_ingest,
    r_out,
    r_send,
    r_stt,
)

#: A chave do `path_map` do `classify` para cada intencao do dono.
CHAVE_DA_INTENCAO: Final = {
    "modulos": "modulos",
    "info_loja": "info",
    "humano": "human",
    "confirmar": "confirm",
    "orcamento": "orcamento",
}


def r_intent(estado: dict[str, Any]) -> str:
    """Transicoes 11 a 14. Lista de permitidos: o resto e `other`."""
    return CHAVE_DA_INTENCAO.get(estado.get("intent") or "", "other")


#: Os encaminhadores pelo no que os usa. O `build_graph` levanta se a tabela
#: tiver um no condicional que nao esteja aqui.
POR_NO: Final = {
    "ingest": r_ingest,
    "stt": r_stt,
    "guard_in": r_guard,
    "classify": r_intent,
    "validate": r_cite,
    "guard_out": r_out,
    "handoff_prepare": r_handoff,
    "send": r_send,
    "draft_wait": r_draft,
}

#: Os que vem do Vendedor sem uma linha nova.
REUTILIZADOS: Final = (
    r_ingest,
    r_stt,
    r_guard,
    r_cite,
    r_out,
    r_handoff,
    r_send,
    r_draft,
)

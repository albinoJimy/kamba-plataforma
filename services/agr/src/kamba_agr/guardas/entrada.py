"""A mensagem do cliente, segura para persistir: a unica via para a janela.

    mensagem_do_cliente(texto) -> {"role": "user", "content": <seguro>}

## Porque e que a redaccao tem de acontecer **antes** do `ainvoke`

O criterio 2 diz «redigido **antes** de qualquer persistencia», e o criterio 7
«o conteudo sensivel **nao** e persistido». O `guard_in` e o terceiro no a
correr — e mediu-se o que isso quer dizer: com um *checkpointer*, o LangGraph
grava a **entrada** do `ainvoke` antes do primeiro no, pelo que um PAN que
entre na janela `messages` fica no *checkpoint* de entrada (`lg.checkpoints` /
`lg.checkpoint_writes`) **mesmo que o `guard_in` o redija a seguir**. Medido com
o `InMemorySaver` em `test_guardas.py::TestPrivacidade`: o PAN cru na entrada
aparece no *saver*; o mesmo PAN por esta funcao, nao.

Logo ha duas barreiras e nao uma:

1. **Esta funcao**, que quem enche a janela tem de usar. Hoje ninguem a enche
   em producao — o `turno.py` passa o `estado_inicial` sem texto, porque o
   `agent_invocation` nao traz o corpo (ver o cabecalho do
   `verticais/vendedor/nos.py`) —, pelo que a convencao nasce aqui e **e
   imposta por maquina**: o `test_guardas.py::TestUmaSoVia` recusa uma
   mensagem `user` construida em `src/` fora deste modulo.
2. **O `guard_in`**, que substitui a mensagem na janela (pelo `id`, que e o
   que o redutor `add_messages` entende) quando ela chega crua. Protege todos
   os *checkpoints* depois dele, e **nao** o de entrada — por isso e a segunda.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .regras import MARCA_SENSIVEL, e_sensivel, redigir_cartao


def texto_seguro(texto: str) -> str:
    """O texto sem PAN nem IBAN, e sem nada se for de assunto sensivel."""
    redigido = redigir_cartao(texto)
    return MARCA_SENSIVEL if e_sensivel(redigido) else redigido


def mensagem_do_cliente(texto: str) -> dict[str, str]:
    """A mensagem do cliente para a janela `messages`. A unica via."""
    return {"role": "user", "content": texto_seguro(texto)}


def substituicao_na_janela(estado: Mapping[str, Any]) -> list[Any]:
    """A mensagem do cliente deste turno, redigida, se chegou crua a janela.

    Devolve a lista para o delta do no (o redutor substitui pelo `id`), ou uma
    lista vazia se a mensagem ja estava segura ou nao tem `id`.
    """
    from langchain_core.messages import HumanMessage

    for item in reversed(list(estado.get("messages") or ())):
        papel = item.get("role") if isinstance(item, Mapping) else getattr(item, "type", None)
        if papel not in ("user", "human"):
            continue
        conteudo = item.get("content") if isinstance(item, Mapping) else getattr(item, "content", "")
        identificador = item.get("id") if isinstance(item, Mapping) else getattr(item, "id", None)
        if not isinstance(conteudo, str) or not identificador:
            return []
        seguro = texto_seguro(conteudo)
        if seguro == conteudo:
            return []
        return [HumanMessage(content=seguro, id=identificador)]
    return []

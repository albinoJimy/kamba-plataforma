"""O classificador barato do §8.4: o `kamba-router`, so quando as regras nao decidem.

    ClassificadorDeGuarda(cliente)(texto, estado) -> veredicto | None

## Tres barreiras antes da chamada, e nenhuma e opcional

1. **So corre se as regras nao decidirem** — e o `guard_in` quem o garante. O
   `card_data` **nunca** chega aqui: as regras decidem-no sempre, e um PAN no
   corpo de um pedido HTTP era a transferencia que o criterio 2 proibe.
2. **O texto vai minimizado** (KAM-112). O `ClienteDeLlm.chamar` so aceita
   `MensagemMinimizada`, e isto passa pelo `minimise` como todo o resto — o
   *system prompt* tambem, porque a barreira e de tipo e nao de conteudo.
3. **O texto vai delimitado como dado** (`prompt.como_dados`) e cortado ao
   `COMPRIMENTO_MAXIMO` (`docs/tecnica/08` §4.3, L1).

## A resposta interpreta-se por lista fechada, e o resto e «indeciso»

O modelo responde uma palavra. Uma palavra fora dos cinco veredictos que ele pode
dar — ou uma frase, ou nada — devolve `None`, e o `guard_in` segue como se o
classificador nao existisse. **Nunca se adivinha**: um «injection.» com ponto
aceita-se, um «parece-me injection» nao, porque quem escreve frases ja nao esta
a seguir o *prompt*.

## O que nao se mede aqui, e onde se mede

A **qualidade** do classificador — quantas injeccoes que as regras nao apanham
ele apanha, e quantas mensagens legitimas recusa — e do *golden* (KAM-040) e do
*red-team* (KAM-073). Os limiares sao *proposta* (Detalhes Tecnicos do bloco).
Esta bateria mede o contrato: o que entra no pedido, e o que sai do veredicto.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

from ..llm.cliente import ContextoDeChamada
from ..privacidade.minimizacao import contexto_de, mensagem, minimise
from . import politica
from .prompt import SISTEMA_DO_CLASSIFICADOR, como_dados

#: O papel do gateway (`llm/aliases.yaml`): `kamba-router`.
PAPEL: Final = "router"

#: O que o classificador pode devolver. **Sem `card_data`**: as regras decidem-no
#: sempre, e o texto que o levaria nunca sai para o modelo.
VEREDICTOS_DO_CLASSIFICADOR: Final = ("ok", "injection", "abuse", "out_of_domain", "sensitive")

#: O no do grafo que chama, para a coluna `no_grafo` de `dat.llm_call_log`.
NO_DO_GRAFO: Final = "guard_in"


def interpretar(resposta: str) -> str | None:
    """A palavra do modelo, se for um veredicto; senao `None`."""
    palavra = (resposta or "").strip().strip(".!\"'`").strip().lower()
    return palavra if palavra in VEREDICTOS_DO_CLASSIFICADOR else None


class ClassificadorDeGuarda:
    """O `kamba-router` como classificador de guarda.

    `cliente` e o `ClienteDeLlm` do KAM-030, ou qualquer objecto com o mesmo
    `chamar(papel, mensagens, ctx)`. `catalogo` e a `PortaDeCatalogo` do KAM-112,
    para que os nomes de produto nao se mascarem.
    """

    __slots__ = ("_cliente", "_catalogo", "_versao_do_grafo")

    def __init__(
        self, cliente: Any, *, catalogo: Any = None, versao_do_grafo: str | None = None
    ) -> None:
        self._cliente = cliente
        self._catalogo = catalogo
        self._versao_do_grafo = versao_do_grafo

    def __call__(self, texto: str, estado: Mapping[str, Any]) -> str | None:
        """Levanta `ErroDeLlm` (incluindo a `FalhaDeMinimizacao`); o no decide."""
        ctx = contexto_de(dict(estado), catalogo=self._catalogo)
        sistema, _ = minimise(SISTEMA_DO_CLASSIFICADOR, ctx)
        dados, _ = minimise(
            como_dados("mensagem_do_cliente", texto[: politica.COMPRIMENTO_MAXIMO]), ctx
        )
        cru = f"{estado.get('thread_id')}:{estado.get('turn_id')}".encode()
        resposta = self._cliente.chamar(
            PAPEL,
            [mensagem("system", sistema), mensagem("user", dados)],
            ContextoDeChamada(
                tenant_id=str(estado.get("tenant_id") or ""),
                # O mesmo `run_id` do `contexto_de_tool`: as linhas de um turno
                # juntam-se, e nao e aleatorio pela razao escrita la.
                trace_id=hashlib.sha256(cru).hexdigest()[:32],
                vertical=estado.get("vertical"),
                no_grafo=NO_DO_GRAFO,
                graph_version=self._versao_do_grafo,
            ),
        )
        return interpretar(getattr(resposta, "texto", ""))

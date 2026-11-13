"""O fornecedor de embeddings do AGR: o gateway LiteLLM atras da porta (KAM-063).

O nucleo (`kamba_core.idx.embeddings`) decide **quando** se chama o fornecedor
— porta de destinos antes de cada chamada, tecto, queda para lexical — e nao
sabe que fornecedor e. Este modulo e o fornecedor de producao, e tres pecas:

    FornecedorDoGateway   o `/embeddings` do proxy, com a chave virtual do tenant
                          e a linha em `dat.llm_call_log` (`ClienteDeLlm.embeber`)
    sensivel              o detector do criterio 4: assunto sensivel, cartao ou
                          qualquer identificador directo
    consulta_vectorial    a `ConsultaVectorial` do processo, ou `None` enquanto
                          o `kamba-embed` nao tiver modelo

## Nenhum identificador vai ao fornecedor, nem mascarado

O `ClienteDeLlm` so aceita `MinimisedText`, e por isso cada texto passa pelo
`minimise` (KAM-112). Mas o `minimise` **mascara** — troca o telefone por
`TELEFONE_1` e deixa o resto ir —, e o criterio 4 do KAM-063 e mais duro: texto
com identificador directo **nao vai**, a consulta corre em lexical. Por isso o
fornecedor recusa um texto cujo mapa nao venha vazio, e o `sensivel` ja o tinha
recusado antes: sao duas barreiras pela mesma razao da do `log_policy`, e
nenhuma substitui a outra.

## Sem modelo, sem tentativa

O `kamba-embed` esta `declarada` com `modelo: por_decidir` (`llm/aliases.yaml`):
a escolha e o criterio 8 do KAM-063 e mede-se com o dataset do KAM-064. Ligar o
fornecedor antes disso era mandar ao proxy, em cada pesquisa de *staging*, um
pedido que falha — e pagar ate 1,5 s por ele. Ate la, `consulta_vectorial`
devolve `None` e a pesquisa e lexical sem ir a lado nenhum.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Final

from kamba_core.idx.embeddings import (
    ClienteDeEmbeddings,
    ConsultaVectorial,
    PortaDeDestinos,
    Vectores,
)

from ..guardas.regras import e_sensivel, tem_dados_de_cartao
from ..llm.cliente import ClienteDeLlm, ContextoDeChamada
from ..privacidade.detector import detectar
from ..privacidade.minimizacao import ContextoDeMinimizacao, minimise

#: O papel do gateway (`llm/aliases.yaml`).
PAPEL: Final = "embed"

#: O modelo de um alias por escolher (`llm/aliases.yaml`).
MODELO_POR_DECIDIR: Final = "por_decidir"

#: A chave do mapa de minimizacao destas chamadas. Nao ha conversa: o mapa
#: nasce e morre na chamada, e so serve para saber se veio vazio.
_THREAD: Final = "idx-embeddings"


class IdentificadorNoTexto(ValueError):
    """O texto tinha um identificador directo. **A mensagem nao o repete.**"""


def sensivel(texto: str) -> bool:
    """`True` se o texto **nao** pode ir ao fornecedor (criterio 4).

    Assunto sensivel pelas regras do `guard_in` (KAM-033), dados de cartao, ou
    qualquer achado do detector de PII (KAM-112). Um detector que levanta e
    tratado como sensivel pelo nucleo, que chama isto dentro de um `try`.
    """
    return e_sensivel(texto) or tem_dados_de_cartao(texto) or bool(detectar(texto))


class FornecedorDoGateway:
    """O `FornecedorDeEmbeddings` do nucleo sobre o `ClienteDeLlm.embeber`.

    **So se constroi como argumento do `ClienteDeEmbeddings`**: e isso que poe
    a porta de destinos do nucleo a frente de cada chamada, e o ensaio de
    arquitectura recusa outra forma.
    """

    def __init__(self, cliente: ClienteDeLlm, papel: str = PAPEL) -> None:
        self._cliente = cliente
        self._papel = papel
        #: Todos os fornecedores do alias, o *fallback* incluido: e sobre eles
        #: que a porta do nucleo corre.
        self.fornecedores: tuple[str, ...] = cliente.fornecedores_de(papel)

    def __call__(
        self, tenant_id: str, textos: Sequence[str], tecto_s: float
    ) -> Vectores:
        minimizados = []
        for posicao, texto in enumerate(textos):
            minimo, mapa = minimise(
                texto, ContextoDeMinimizacao(tenant_id=tenant_id, thread_id=_THREAD)
            )
            if mapa.valores:
                raise IdentificadorNoTexto(
                    f"o texto {posicao} tem identificador directo: nao vai ao "
                    "fornecedor de embeddings, nem mascarado (KAM-063, criterio 4)"
                )
            minimizados.append(minimo)
        resposta = self._cliente.embeber(
            self._papel,
            minimizados,
            ContextoDeChamada(tenant_id=tenant_id, trace_id=uuid.uuid4().hex),
            tecto_s,
        )
        return Vectores(modelo=resposta.modelo, vectores=resposta.vectores)


def consulta_vectorial(
    cliente: ClienteDeLlm, porta: PortaDeDestinos
) -> ConsultaVectorial | None:
    """A consulta vectorial do processo, ou `None` sem modelo escolhido."""
    modelo = cliente.modelo_de(PAPEL)
    if modelo is None or modelo == MODELO_POR_DECIDIR:
        return None
    return ConsultaVectorial(
        cliente=ClienteDeEmbeddings(porta, FornecedorDoGateway(cliente)),
        sensivel=sensivel,
    )


__all__ = [
    "FornecedorDoGateway",
    "IdentificadorNoTexto",
    "MODELO_POR_DECIDIR",
    "PAPEL",
    "consulta_vectorial",
    "sensivel",
]

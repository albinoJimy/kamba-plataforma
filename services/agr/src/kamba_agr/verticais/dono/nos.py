"""Os nos do grafo do dono: os quatro proprios, e a tabela com os reutilizados.

## Doze importados, quatro escritos

Os doze do `NOS_REUTILIZADOS` vem do `verticais/vendedor/nos.py` tal como
estao: importam-se, nao se copiam nem se envolvem. Os quatro deste ficheiro sao
os que o §5.4 poe na coluna do que e **proprio** — o texto de persona
(`compose`, `safe_reply`, `ask_repeat`) — e a decisao da intencao (`classify`),
porque as intencoes do dono nao sao as de um cliente.

**As `Dependencias` sao as do Vendedor**, pela razao que o `nos.py` de Servicos
escreveu: doze nos recebem aquele tipo, e um tipo proprio era um adaptador por
no. O que muda por persona — a `persona` e a `tools_permitidas` — sao campos,
vindos do `registry/dono.yaml` pelo `grafos.compilar`, como nas verticais.

## O que o grafo diz hoje, e porque e honesto

As quatro tools do modulo `catalogo` estao `declaradas` (credor KAM-119): a
ToolLayer recusa-as a todos. Por isso o `classify` **nao** as chama — uma
chamada que se sabe recusada era uma linha de `tool_audit` por turno a dizer
`TOOL_NOT_ALLOWED` ao proprio dono — e o `compose` diz-lhe que os modulos ainda
nao estao activos. O que responde e a `get_store_info`, pelo `tools_info`
reutilizado. **Nenhum texto deste ficheiro leva digitos** (o `_resposta_estatica`
nao passa pelo validador), e ha ensaio que o mede.

## O que este grafo nao ve, e nao e dele

Hoje nenhum texto nem `id` de botao chega ao AGR (o `estado_inicial` nasce com
`messages: []`, decisao do KAM-186). As regras do `classify` leem a janela
`messages` como todas as verticais; no processo, o turno do dono cai em
`outro` pela mesma razao que o de um cliente. O portao das accoes sensiveis
(`kamba_agr/dono/accoes.py`) entrega-se e ensaia-se sem caminho de producao.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any, Final

from ...tls.erros import LIMIT_EXCEEDED, UPSTREAM_DOWN, UPSTREAM_TIMEOUT
from ..vendedor.nos import (
    BOTAO_HUMANO,
    Dependencias,
    botoes_seguros_da_guarda,
    draft_prepare,
    draft_wait,
    guard_in,
    guard_out,
    handoff_close,
    handoff_prepare,
    handoff_wait,
    ingest,
    send,
    stt,
    texto_seguro_da_guarda,
    tools_info,
    validate,
)
from ..vendedor.nos import (
    MOTIVO_PEDIDO,
    _blocos_dos_dados,
    _resposta_estatica,
    _texto_do_cliente,
)
from .arestas import INTENCOES

#: As tools do Assistente do Dono, pela ordem do `registry/dono.yaml`. So para
#: os ensaios e para quem compile o grafo sem o registo: o processo usa as do
#: registo, pelo `grafos.compilar`.
TOOLS_DO_DONO: Final = (
    "get_store_info",
    "create_product_draft",
    "ask_missing_fields",
    "publish_product",
    "get_catalog_status",
)

#: As palavras que decidem cada intencao, **pela ordem em que correm**: «quero
#: falar com uma pessoa sobre o catalogo» e um pedido de humano. Sem acentos —
#: o texto compara-se sem eles.
REGRAS_DE_INTENCAO: Final = (
    ("humano", ("falar com uma pessoa", "falar com alguem", "atendente", "humano")),
    ("info_loja", ("horario", "onde fica", "morada", "endereco", "aberto")),
    (
        "modulos",
        (
            "produto",
            "catalogo",
            "publica",
            "artigo",
            "preco",
            "stock",
            "foto",
            "rascunho",
            "campos",
        ),
    ),
)


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def intencao_por_regras(texto: str) -> str | None:
    """A intencao pelas palavras, ou `None` se nenhuma regra decidir."""
    limpo = _sem_acentos(texto)
    for intencao, palavras in REGRAS_DE_INTENCAO:
        if any(palavra in limpo for palavra in palavras):
            return intencao
    return None


def _botao_do_turno(estado: Mapping[str, Any]) -> str:
    if estado.get("input_kind") != "interactive":
        return ""
    return _texto_do_cliente(estado).strip()


# ---------------------------------------------------------------- o classify


def classify(deps: Dependencias):
    """Transicoes 11 a 14: a intencao. Regras primeiro, modelo so se preciso.

    **Nenhuma intencao chama uma tool de escrita**, e nao e prudencia: as quatro
    do catalogo estao declaradas e um texto («sim», «confirmo, podes publicar»)
    nunca confirma nada — so o botao `confirm:{action_id}` do mesmo contacto, e
    isso e o `dono/accoes.py`, fora do grafo.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        if _botao_do_turno(estado) == BOTAO_HUMANO:
            return {"intent": "humano", "handoff_motivo": MOTIVO_PEDIDO}
        texto = _texto_do_cliente(estado)
        intencao = intencao_por_regras(texto)
        if intencao is None and deps.classificador is not None:
            escolhida = deps.classificador(texto)
            # Um valor fora da lista **nao** entra no estado: o `r_intent`
            # mandava-o a `other` de qualquer maneira.
            intencao = escolhida if escolhida in INTENCOES else None
        resolvida = intencao or "outro"
        delta: dict[str, Any] = {"intent": resolvida}
        if resolvida == "humano":
            delta["handoff_motivo"] = MOTIVO_PEDIDO
        return delta

    return no


# ------------------------------------------------- os tres de texto de persona


def ask_repeat(deps: Dependencias):
    """Transicao 6 -> 22: a nota de voz que nao se percebeu."""

    async def no(_estado: dict[str, Any]) -> dict[str, Any]:
        return _resposta_estatica(MSG_REPETIR)

    return no


def safe_reply(deps: Dependencias):
    """Transicoes 9, 14 e 21 -> 23: o texto seguro, escolhido pelo veredicto.

    O fora de ambito e **deste** grafo; os outros (cartao, abuso, pausa, saida
    bloqueada) sao da plataforma e vem da funcao partilhada, como em Servicos.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        resposta = _resposta_estatica(texto_seguro_da_guarda(estado, MSG_FORA_DE_AMBITO))
        resposta["draft"]["botoes"] = botoes_seguros_da_guarda(estado)
        return resposta

    return no


def compose(deps: Dependencias):
    """Transicao 16: os blocos. **Nenhum numero em prosa** (ADR-007).

    Tres fontes, por esta ordem: os avisos do turno, o pedido sobre o catalogo
    (que hoje so tem uma resposta honesta) e o que a `get_store_info` deixou no
    rascunho. Um aviso que este grafo nao conhece **nao levanta** — ao contrario
    do `compose` de Servicos —, porque o unico no de tool que corre aqui e o
    `tools_info` do Vendedor, e um aviso novo do dominio dele nao pode rebentar
    o turno do dono: diz-se a frase generica.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        rascunho = estado.get("draft") or {}
        blocos: list[dict[str, Any]] = []
        for aviso in tuple(estado.get("avisos") or ()):
            blocos.append({"type": "text", "text": FRASE_DO_AVISO.get(aviso, MSG_NAO_CONSEGUI)})
        if estado.get("intent") == "modulos":
            blocos.append({"type": "text", "text": MSG_MODULOS_INACTIVOS})
        blocos.extend(_blocos_dos_dados(estado))
        if not blocos:
            blocos.append({"type": "text", "text": MSG_NAO_ENTENDI})
        # Preserva o rascunho em vez de o substituir — a licao do achado 9 da
        # revisao do KAM-031, que o `compose` de Servicos tambem escreve.
        return {"draft": dict(rascunho, blocos=tuple(blocos))}

    return no


# ------------------------------------------------------------------ os textos
#
# **Sem digitos**, todos: os do `ask_repeat` e do `safe_reply` vao direitos ao
# `send` sem passar pelo validador, e os do `compose` sao blocos `text`, que o
# *renderer* recusa com digitos.

#: O que se diz a um pedido sobre o catalogo enquanto o KAM-119 nao liga as
#: tools. **E a verdade e nao uma evasiva**: as quatro estao declaradas e a
#: ToolLayer recusa-as.
MSG_MODULOS_INACTIVOS: Final = (
    "Os modulos do catalogo ainda nao estao activos para a sua loja. Quando "
    "estiverem, trato daqui dos produtos e da publicacao."
)
MSG_FORA_DE_AMBITO: Final = (
    "Por aqui trato da sua loja: o catalogo e a informacao da loja. Prefere "
    "falar com uma pessoa?"
)
MSG_REPETIR: Final = (
    "Nao consegui ouvir bem a nota de voz. Pode escrever o que precisa?"
)
MSG_NAO_ENTENDI: Final = (
    "Nao percebi o que precisa. Posso dar a informacao da loja, e os modulos do "
    "catalogo ainda nao estao activos."
)
MSG_NAO_CONSEGUI: Final = "Nao consegui tratar esse pedido por aqui."

#: Os avisos que o `tools_info` pode deixar (o `_aviso_do_erro` do Vendedor).
FRASE_DO_AVISO: Final = {
    UPSTREAM_TIMEOUT: "O sistema demorou a responder. Tente outra vez daqui a pouco.",
    UPSTREAM_DOWN: "O sistema nao responde neste momento. Tente outra vez daqui a pouco.",
    LIMIT_EXCEEDED: "Este pedido passa o limite do plano da loja.",
}


#: Os dezasseis nos pelo nome. E a tabela que o `build_graph` percorre.
NOS_DO_GRAFO: Final = {
    # Reutilizados sem uma linha nova (ADR-012, §21.4).
    "ingest": ingest,
    "stt": stt,
    "guard_in": guard_in,
    "tools_info": tools_info,
    "validate": validate,
    "guard_out": guard_out,
    "send": send,
    "handoff_prepare": handoff_prepare,
    "handoff_wait": handoff_wait,
    "handoff_close": handoff_close,
    "draft_prepare": draft_prepare,
    "draft_wait": draft_wait,
    # Proprios desta persona.
    "classify": classify,
    "compose": compose,
    "safe_reply": safe_reply,
    "ask_repeat": ask_repeat,
}

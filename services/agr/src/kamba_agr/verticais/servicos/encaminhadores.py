"""Os encaminhadores do grafo de Servicos — e todos sao funcoes puras do estado.

**Sao catorze entradas no `POR_NO` e doze funcoes**, porque o `r_upstream` serve
tres nos (`check_availability`, `book_slot`, `cancel_booking`), que e a razao por
que ele existe no Vendedor a servir dois.

## Nove das doze nao se escrevem aqui

O `r_ingest`, o `r_stt`, o `r_guard`, o `r_upstream`, o `r_cite`,
o `r_out`, o `r_handoff`, o `r_send` e o `r_draft` vem do
`verticais/vendedor/encaminhadores.py` tal como estao. Nao e analogia: as
transicoes 2 a 10, 28 a 32 e 35 a 37 do §8.1 sao, **palavra por palavra**, as
linhas 2 a 10, 29 a 33 e 35 a 37 do §7.3 — o diagrama de Servicos reutiliza o
esqueleto do Vendedor nessas partes, e e o que o §8.1 escreve depois do
diagrama («Nos comuns com o Vendedor: ...»).

**O `r_confirm` NAO se reutiliza, e isso e uma correccao e nao uma escolha.** O
do Vendedor devolve `go` ou `stale`, porque o portao do §7.3 tem duas saidas;
este tem tres, pela aresta que o §6.2 obriga (o cancelamento tambem passa pelo
botao). Ele le o aviso que o no escreveu, como o do Vendedor — o que muda e o
numero de destinos.

As tres proprias sao o `r_intent` (as nove intencoes do §8.2), o `r_slots` (as
transicoes 18 e 19) e o `r_confirm` (24, 25 e 43).

## Puras, e porque e que isso e a propriedade que importa

Um encaminhador que pergunte algo ao mundo pergunta-o **depois** de o no ja ter
perguntado, e o §8.1 nao tem sitio para duas respostas diferentes no mesmo
turno. Por isso o no decide e escreve, e o encaminhador le. A consequencia
pratica e que a tabela de decisao de cada um se mede com um `dict`, sem grafo,
sem base e sem tools.

## Todos caem para o lado seguro

Cada um tem um ramo de omissao, e nenhum deles e «segue em frente»:

* uma `intent` que nao esteja nas nove vai a `safe_reply` (chave `other`);
* um `slots_collect` sem os tres obrigatorios **pergunta**, nunca consulta a
  agenda com um campo vazio;
* um `confirm_gate` sem *hold* valido e `stale`;
* um `validate` sem veredicto conta como falha.

E a mesma regra do `do_humano` do `turno.py`: lista de permitidos e nao de
proibidos, porque um valor novo no dominio fecha a porta por omissao.
"""

from __future__ import annotations

from typing import Any, Final

# Os dez reutilizados. **Importar e nao copiar** — ver o cabecalho.
from ..vendedor.encaminhadores import (
    r_cite,
    r_draft,
    r_guard,
    r_handoff,
    r_ingest,
    r_out,
    r_send,
    r_stt,
    r_upstream,
)
from .arestas import (
    INTENCOES,
    INTENCOES_DE_SLOTS,
    STALE_CONFIRMATION,
    obrigatorios_de,
)

#: A chave do `path_map` de `classify` para cada uma das nove intencoes
#: (§8.2, primeira linha).
#:
#: **Tres intencoes partilham a chave `slots`**, e e o que faz as nove intencoes
#: sairem por sete arestas: `marcar`, `remarcar` e `disponibilidade` vao as tres
#: ao `slots_collect`. A razao da terceira — que o diagrama nao encaminha — esta
#: no `INTENCOES_DE_SLOTS` do `arestas.py`.
CHAVE_DA_INTENCAO: Final = {
    "marcar": "slots",
    "remarcar": "slots",
    "disponibilidade": "slots",
    "cancelar": "cancel",
    "confirmar": "confirm",
    "servicos_precos": "services",
    "info_loja": "info",
    "humano": "human",
    "outro": "other",
}


def r_intent(estado: dict[str, Any]) -> str:
    """Transicoes 11 a 17, pelas nove intencoes do §8.2.

    **A omissao e `other`**: um `intent` fora das nove e um estado que ninguem
    escreveu de proposito, e o `safe_reply` e o unico caminho que nao arrisca
    nada.
    """
    intencao = estado.get("intent")
    if intencao not in INTENCOES:
        return "other"
    return CHAVE_DA_INTENCAO[intencao]


def r_slots(estado: dict[str, Any]) -> str:
    """Transicoes 18 e 19: os slots estao completos, ou falta perguntar.

    **Le os `slots` e nao a `pergunta`**, e a assimetria com o `r_confirm` tem
    razao: a `pergunta` e o que o `compose` vai dizer, e ha um caminho em que ela
    esta escrita **e** os slots estao completos — a desambiguacao de hora, que
    limpa a `hora` e deixa os outros dois. Encaminhar pela `pergunta` dava
    `ready` num turno em que a hora e ambigua, e a agenda era consultada com a
    hora do turno anterior.

    **O conjunto de obrigatorios depende da intencao** (`obrigatorios_de`): quem
    pergunta «quando tem vaga?» nao sabe a hora, e e precisamente por isso que
    pergunta. A razao medida esta no `SLOTS_PARA_DISPONIBILIDADE`.

    A verificacao e a mesma lista que o `slots_collect` percorre, e isso **nao**
    e duplicacao da decisao: o no escreve o que leu e este le se o que ficou
    escrito chega. Uma segunda leitura do texto do cliente aqui era a impureza
    que o cabecalho proibe.
    """
    slots = estado.get("slots")
    if not isinstance(slots, dict):
        return "ask"
    # **Uma remarcacao sem referencia nao segue**, e e a barreira do criterio 7
    # no encaminhador: sem saber qual marcacao se substitui, consultar a agenda
    # levava a marcar uma **nova** e a deixar a original de pe. Medido pela
    # revisao adversarial (`ANALISE-40`, achado 8).
    if estado.get("intent") == "remarcar" and not isinstance(
        slots.get("remarcar"), str
    ):
        return "ask"
    exigidos = obrigatorios_de(estado.get("intent"))
    if any(slots.get(campo) in (None, "", ()) for campo in exigidos):
        return "ask"
    return "ready"


def r_confirm(estado: dict[str, Any]) -> str:
    """Transicoes 24, 25 e 43: a marcacao, o cancelamento, ou `stale`.

    **Nao se reutiliza o do Vendedor, e a razao e uma saida a mais.** O dele
    devolve `go` ou `stale`, porque o portao do §7.3 tem duas saidas; este tem
    **tres**, pela aresta que o §6.2 obriga (ver a nota dela na tabela): um
    cancelamento confirmado vai ao `cancel_booking` e nao ao `book_slot`.

    **Le o aviso que o `confirm_gate` escreveu e nao repete as tres perguntas do
    no**, que e a propriedade do do Vendedor e vale igual aqui: repeti-las era
    avaliar o *hold* duas vezes contra um relogio que andou entre as duas, e com
    um `expira_at` a passar no meio o grafo confirmava uma marcacao que o no
    tinha recusado.

    O que distingue `go` de `cancel` e o que esta **pendente** no estado, e nao
    o botao: quem comparou o botao com a referencia foi o no.
    """
    avisos = estado.get("avisos") or ()
    if STALE_CONFIRMATION in avisos:
        return "stale"
    slots = estado.get("slots")
    pendente = slots.get("cancelar") if isinstance(slots, dict) else None
    return "cancel" if pendente else "go"


#: Os encaminhadores pelo no que os usa. E o que o `grafo.py` percorre, e e
#: tambem o que torna «um no condicional sem encaminhador» impossivel de
#: escrever: o `build_graph` levanta se a tabela de arestas tiver um no
#: condicional que nao esteja aqui.
#:
#: O `r_upstream` aparece **tres** vezes, uma por no de agenda, e e **um**
#: encaminhador para os tres: a condicao e a mesma (`UPSTREAM_*` apos retry) e
#: duplica-la era deixar os tres divergirem.
POR_NO: Final = {
    "ingest": r_ingest,
    "stt": r_stt,
    "guard_in": r_guard,
    "classify": r_intent,
    "slots_collect": r_slots,
    "check_availability": r_upstream,
    "cancel_booking": r_upstream,
    "confirm_gate": r_confirm,  # o proprio: tres saidas
    "book_slot": r_upstream,
    "validate": r_cite,
    "guard_out": r_out,
    "handoff_prepare": r_handoff,
    "send": r_send,
    "draft_wait": r_draft,
}

#: Os encaminhadores que vem do pacote do Vendedor sem uma linha nova.
#: Afirma-se para que o reuso seja uma lista que alguem possa contar, e ha
#: ensaio a confrontar isto com o `POR_NO`.
REUTILIZADOS: Final = (
    r_ingest,
    r_stt,
    r_guard,
    r_upstream,
    r_cite,
    r_out,
    r_handoff,
    r_send,
    r_draft,
)

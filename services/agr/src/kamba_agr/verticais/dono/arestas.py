"""Os nos e as arestas do grafo do Assistente do Dono (KAM-118, ADR-020).

## Nao ha diagrama no documento, e por isso cada aresta diz de onde vem

O `docs/tecnica/02` §21 da a persona do dono, as tools do modulo `catalogo` e a
regra de reaproveitamento (§21.4: «um modulo que precise de uma excepcao no
core falha o criterio de reaproveitamento >= 70% e e recusado»), mas **nao**
desenha o grafo, ao contrario do §7.3 (Vendedor) e do §8.1 (Servicos). O que
aqui fica e o esqueleto do Vendedor tal como esta, com o meio trocado:

* as transicoes do esqueleto — entrada, voz, guarda, validador, guarda de
  saida, envio e *handoff* — sao as do §7.3 palavra por palavra, e levam
  `FONTE_DO_ESQUELETO`;
* tres das saidas do `classify` sao deste ticket (`FONTE_DO_DONO`); a do
  catalogo (11) passou ao `confirm` e a 37 e nova com o KAM-119
  (`FONTE_DO_CATALOGO`), e as do botao e do orcamento dizem os seus;
* as quatro do concierge sao as do KAM-114 (`FONTE_DO_CONCIERGE`).

## Porque e que o concierge esta aqui, e nao estava no desenho

O desenho fixou **dez** nos reutilizados. Sao **doze**, e a diferenca e uma
correccao e nao uma escolha: o `send` do Vendedor e a porta do concierge, e com
a politica ligada para o tenant ele **nao envia** — escreve `a_aprovar` e o
`r_send` devolve `aprovar`. Sem o `draft_prepare` e o `draft_wait` no grafo,
essa chave nao tinha destino no `path_map`, e o turno do dono de um tenant no
Piloto concierge rebentava. A alternativa — dar ao dono umas `Dependencias` com
o concierge desligado — era um ramo no `grafos.compilar` pelo nome da persona,
que e exactamente a excepcao no core que o §21.4 recusa.

## O reaproveitamento, e porque e uma lista e nao uma frase

Doze dos dezassete nos vem do `verticais/vendedor/nos.py` sem uma linha nova:
**70,6%**, acima dos 70% do criterio 10 do KAM-118 (eram 75% com dezasseis; o
`confirm` do KAM-211 e o quinto proprio). Os outros quatro proprios sao os que
escrevem **texto de persona** (o §5.4 poe «texto de persona e exemplos» na
coluna do que e proprio) ou decidem a intencao: o `classify`, o `compose`, o
`safe_reply` e o `ask_repeat`. A medida le-se do `NOS_REUTILIZADOS` e ha ensaio
a confronta-la com a tabela de nos do `nos.py`.
"""

from __future__ import annotations

from typing import Any, Final

from langgraph.graph import END, START

from ..vendedor.arestas import Aresta

#: A versao do grafo do dono, SemVer. Vai na coluna `graph_version` da
#: `tool_audit` pelos nos proprios. Nasce em 1.0.0, pela regra do de Servicos:
#: duas linhas de versao, e nenhum no do dono e historia do Vendedor.
VERSAO_DO_GRAFO: Final = "1.0.0"

#: As transicoes do esqueleto do §7.3, reutilizadas sem mudar a forma.
FONTE_DO_ESQUELETO: Final = "02 §7.3 (esqueleto reutilizado)"
#: As saidas do `classify` do dono: o §21 nao desenha o grafo.
FONTE_DO_DONO: Final = "KAM-118"
#: O botao `confirm:{action_id}` ate ao `confirmar` (KAM-211, criterio «Botao»).
FONTE_DO_BOTAO: Final = "KAM-211"
#: As quatro do concierge: os nos do KAM-114, pelo ADR-L005.
FONTE_DO_CONCIERGE: Final = "KAM-114 (ADR-L005)"
#: Os pedidos de orcamento que esperam o dono (KAM-220). **Uma aresta, e nenhum
#: no**: os pendentes dizem-se no `compose` que ja existe, e um no proprio a
#: mais punha o reaproveitamento abaixo do piso do §21.4 (12 de 18).
FONTE_DO_ORCAMENTO: Final = "KAM-220"
#: As arestas da conversa do catalogo (KAM-119): a 11 passa do `compose` ao
#: `confirm`, e a 37 e nova.
FONTE_DO_CATALOGO: Final = "KAM-119"

#: O piso do criterio 10 do KAM-118: reutilizados / total.
REAPROVEITAMENTO_MINIMO: Final = 0.70

#: Os dezassete nos. Lista **fechada**. O `confirm` e do KAM-211.
NOS: Final = (
    "ingest",
    "stt",
    "guard_in",
    "classify",
    "confirm",
    "tools_info",
    "compose",
    "validate",
    "guard_out",
    "ask_repeat",
    "safe_reply",
    "send",
    "handoff_prepare",
    "handoff_wait",
    "handoff_close",
    "draft_prepare",
    "draft_wait",
)

#: Os que vem do pacote do Vendedor **sem uma linha nova**. Os dez do desenho e
#: os dois do concierge — ver a nota do modulo.
NOS_REUTILIZADOS: Final = (
    "ingest",
    "stt",
    "guard_in",
    "tools_info",
    "validate",
    "guard_out",
    "send",
    "handoff_prepare",
    "handoff_wait",
    "handoff_close",
    "draft_prepare",
    "draft_wait",
)

#: As intencoes do dono. **Lista fechada e curta**, e cada uma e uma saida:
#:
#: `modulos`    o catalogo — criar, completar, publicar, ver o estado. Vai ao
#:              `compose`, que diz que os modulos ainda nao estao activos: as
#:              quatro tools sao do KAM-119 e a ToolLayer recusa-as hoje;
#: `info_loja`  horario, morada — a `get_store_info`, a unica ligada;
#: `humano`     falar com uma pessoa;
#: `confirmar`  o botao `confirm:{action_id}` de uma accao sensivel (KAM-211).
#:              Vai ao `confirm`, que chama o `confirmar` do `dono/accoes.py`.
#:              **So o botao a decide**, e nunca uma palavra: nao ha regra de
#:              texto que de esta intencao;
#: `orcamento`  os pedidos de orcamento que esperam o dono (KAM-220). Vai ao
#:              `compose`, que os lista. Pelas palavras, ou sozinha na primeira
#:              mensagem do dono quando ha pendentes (criterio 2 do KAM-123);
#: `responder_orcamento`
#:              o dono escreve o valor de um pedido (KAM-220). Vai ao `confirm`,
#:              que chama o `submit_quote` e devolve o eco e o botao
#:              `confirm:{action_id}` **sem** passar pelo `validate`: a
#:              pre-visualizacao ja foi validada pelo validador do KAM-032 com o
#:              *fact* `quote_price`, e e o mesmo caminho directo ao `send` das
#:              frases do botao;
#: `outro`      tudo o resto, ao `safe_reply`.
INTENCOES: Final = (
    "modulos",
    "info_loja",
    "humano",
    "confirmar",
    "orcamento",
    "responder_orcamento",
    "catalogo",
    "outro",
)


#: As arestas, pela ordem do esqueleto.
ARESTAS: Final = (
    Aresta(1, START, "ingest", None, "sempre", fonte=FONTE_DO_ESQUELETO),
    Aresta(2, "ingest", "stt", "stt", "entrada de audio", fonte=FONTE_DO_ESQUELETO),
    Aresta(3, "ingest", "guard_in", "guard_in", "texto ou botao", fonte=FONTE_DO_ESQUELETO),
    Aresta(4, "ingest", END, "end", "duplicado ou excesso de ritmo", fonte=FONTE_DO_ESQUELETO),
    Aresta(5, "stt", "guard_in", "ok", "confianca alta", fonte=FONTE_DO_ESQUELETO),
    Aresta(6, "stt", "ask_repeat", "repeat", "confianca media", fonte=FONTE_DO_ESQUELETO),
    Aresta(7, "stt", "handoff_prepare", "human", "confianca baixa", fonte=FONTE_DO_ESQUELETO),
    Aresta(8, "guard_in", "classify", "ok", "ok", fonte=FONTE_DO_ESQUELETO),
    Aresta(9, "guard_in", "safe_reply", "safe", "nao ok", fonte=FONTE_DO_ESQUELETO),
    Aresta(10, "guard_in", "handoff_prepare", "human", "assunto sensivel", fonte=FONTE_DO_ESQUELETO),
    Aresta(11, "classify", "confirm", "modulos", "pedido sobre o catalogo", fonte=FONTE_DO_CATALOGO),
    Aresta(12, "classify", "tools_info", "info", "horario e morada", fonte=FONTE_DO_DONO),
    Aresta(13, "classify", "handoff_prepare", "human", "pedir humano", fonte=FONTE_DO_DONO),
    Aresta(14, "classify", "safe_reply", "other", "outro", fonte=FONTE_DO_DONO),
    Aresta(35, "classify", "compose", "orcamento", "pedidos de orcamento pendentes", fonte=FONTE_DO_ORCAMENTO),
    Aresta(36, "classify", "confirm", "resposta", "o valor de um orcamento, por texto", fonte=FONTE_DO_ORCAMENTO),
    Aresta(33, "classify", "confirm", "confirm", "botao confirm:{action_id}", fonte=FONTE_DO_BOTAO),
    Aresta(
        37,
        "classify",
        "confirm",
        "catalogo",
        "botao, foto, PRD ou resposta a um rascunho do catalogo",
        fonte=FONTE_DO_CATALOGO,
    ),
    Aresta(34, "confirm", "send", None, "sempre (texto estatico)", fonte=FONTE_DO_BOTAO),
    Aresta(15, "tools_info", "compose", None, "sempre", fonte=FONTE_DO_ESQUELETO),
    Aresta(16, "compose", "validate", None, "sempre", fonte=FONTE_DO_ESQUELETO),
    Aresta(17, "validate", "guard_out", "ok", "conferido", fonte=FONTE_DO_ESQUELETO),
    Aresta(18, "validate", "compose", "retry", "falha e retries abaixo de 1", fonte=FONTE_DO_ESQUELETO),
    Aresta(19, "validate", "handoff_prepare", "human", "falha repetida", fonte=FONTE_DO_ESQUELETO),
    Aresta(20, "guard_out", "send", "ok", "ok", fonte=FONTE_DO_ESQUELETO),
    Aresta(21, "guard_out", "safe_reply", "safe", "violacao", fonte=FONTE_DO_ESQUELETO),
    Aresta(22, "ask_repeat", "send", None, "sempre (texto estatico)", fonte=FONTE_DO_ESQUELETO),
    Aresta(23, "safe_reply", "send", None, "sempre (texto estatico)", fonte=FONTE_DO_ESQUELETO),
    Aresta(24, "send", END, "enviado", "enviado, ou politica concierge desligada", fonte=FONTE_DO_ESQUELETO),
    Aresta(25, "handoff_prepare", "handoff_wait", "wait", "aberto", fonte=FONTE_DO_ESQUELETO),
    Aresta(26, "handoff_prepare", "send", "degraded", "HND indisponivel", fonte=FONTE_DO_ESQUELETO),
    Aresta(27, "handoff_wait", "handoff_close", None, "retoma", fonte=FONTE_DO_ESQUELETO),
    Aresta(28, "handoff_close", END, None, "sempre", fonte=FONTE_DO_ESQUELETO),
    Aresta(
        29,
        "send",
        "draft_prepare",
        "aprovar",
        "politica concierge ligada e sem decisao humana",
        fonte=FONTE_DO_CONCIERGE,
    ),
    Aresta(30, "draft_prepare", "draft_wait", None, "sempre", fonte=FONTE_DO_CONCIERGE),
    Aresta(31, "draft_wait", "send", "enviar", "decisao aprovado ou editado", fonte=FONTE_DO_CONCIERGE),
    Aresta(
        32,
        "draft_wait",
        END,
        "end",
        "decisao rejeitado, expirado ou substituido",
        fonte=FONTE_DO_CONCIERGE,
    ),
)


def reaproveitamento() -> float:
    """Reutilizados / total. O numero do criterio 10, lido das duas listas."""
    return len(NOS_REUTILIZADOS) / len(NOS)


def pares() -> frozenset[tuple[str, str]]:
    """As arestas como pares `(de, para)` — o que se compara com o compilado."""
    return frozenset((a.de, a.para) for a in ARESTAS)


def mapa_de(no: str) -> dict[str, str]:
    """O `path_map` de um no condicional, derivado da tabela (nunca escrito a mao)."""
    saidas = {a.chave: a.para for a in ARESTAS if a.de == no and a.condicional}
    if not saidas:
        raise KeyError(f"{no!r} nao tem arestas condicionais na tabela")
    return saidas


def directas() -> tuple[tuple[str, str], ...]:
    """As arestas sem encaminhador, para o `add_edge`."""
    return tuple((a.de, a.para) for a in ARESTAS if not a.condicional)


def condicionais() -> tuple[str, ...]:
    """Os nos com encaminhador, pela ordem da tabela e sem repetir."""
    vistos: list[str] = []
    for aresta in ARESTAS:
        if aresta.condicional and aresta.de not in vistos:
            vistos.append(aresta.de)
    return tuple(vistos)


def pares_do_compilado(compilado: Any) -> frozenset[tuple[str, str]]:
    """As arestas do grafo **compilado**, lidas do LangGraph e nao da tabela."""
    desenho = compilado.get_graph()
    return frozenset((a.source, a.target) for a in desenho.edges)

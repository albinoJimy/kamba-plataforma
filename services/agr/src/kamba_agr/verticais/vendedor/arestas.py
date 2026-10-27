"""Os vinte e um nos e as quarenta e duas arestas do grafo do Vendedor (§7.3).

## Porque e que a tabela vive em codigo, e nao so no documento

O criterio 1 do bloco do KAM-031 pede «o teste de contrato (tabela `EDGES` em
codigo **comparada** com o grafo compilado)». A tabela abaixo e essa: cada
aresta leva o numero da linha de `docs/tecnica/02` §7.3 que a autoriza, e o
teste confronta o conjunto com o que o `get_graph()` do LangGraph devolve. Uma
aresta a mais no grafo ou a menos na tabela falha, nos dois sentidos.

## Trinta e nove linhas, quarenta e duas arestas

A tabela do §7.3 tem **trinta e nove linhas** e o criterio escreve «as 39
arestas». Sao grandezas diferentes, e a diferenca mede-se: tres linhas carregam
mais do que uma aresta —

* a **27** (`order_status`, `tools_info` -> `compose`) carrega duas;
* a **34** (`unknown_reply`, `ask_repeat`, `safe_reply` -> `send`) carrega tres.

Trinta e nove linhas, quarenta e duas arestas dirigidas. Um teste que afirmasse
trinta e nove passava com tres arestas a menos — e tres arestas a menos sao tres
nos sem caminho para o envio, que e um cliente a nao receber resposta. As duas
contagens provam-se **ambas** (`LINHAS_DO_73` e `ARESTAS`), e a emenda 1.40
escreve-o no dicionario §3.31.

## O que e `chave` e porque nao e decoracao

Numa aresta condicional, o LangGraph nao liga `de` a `para` directamente: liga
`de` a um encaminhador, e o encaminhador devolve uma **chave** que o mapa
(`path_map`) traduz num no. A `chave` aqui e a desse mapa, e e ela que torna o
teste de contrato capaz de apanhar a troca mais facil de fazer e mais dificil de
ver — dois destinos trocados no mapa de um encaminhador, que no grafo compilado
da o mesmo conjunto de arestas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from langgraph.graph import END, START

#: A versao do grafo, SemVer. Vai na coluna `graph_version` da `tool_audit`
#: (§6.4) e do `llm_call_log` (KAM-030), e e o que o DoD pede por «SemVer do
#: grafo atribuido». Sobe no *minor* quando um no entra ou sai; no *major*
#: quando o estado deixa de ser compativel com um `interrupt` pendente (§12,
#: linha do versionamento).
VERSAO_DO_GRAFO: Final = "1.0.0"

#: O numero de linhas da tabela de §7.3. Afirma-se para que o numero do criterio
#: 1 continue verificavel depois de alguem perceber que as arestas sao mais.
LINHAS_DO_73: Final = 39

#: Os vinte e um nos, pela ordem do §7.4. Lista **fechada**: e por ela que o
#: teste de contrato mede «nenhum no a mais, nenhum a menos», e cada nome e
#: tambem etiqueta de nada — os nos nao sao etiqueta de metrica, e e de
#: proposito (§9.2 do `docs/tecnica/08`: o nome de um no nao identifica ninguem,
#: mas tambem nao se mede por no sem alguem decidir).
NOS: Final = (
    "ingest",
    "stt",
    "guard_in",
    "classify",
    "retrieve",
    "tools_read",
    "cart_build",
    "confirm_gate",
    "create_order",
    "order_status",
    "tools_info",
    "compose",
    "validate",
    "guard_out",
    "unknown_reply",
    "ask_repeat",
    "safe_reply",
    "send",
    "handoff_prepare",
    "handoff_wait",
    "handoff_close",
)

#: As nove intencoes do Vendedor (§7.3 linhas 11 a 17; dicionario §3.31).
#: **Nove e nao sete:** as linhas 11 e 14 levam duas cada uma.
INTENCOES: Final = (
    "produto",
    "preco_stock",
    "comprar",
    "confirmar",
    "pagamento_estado",
    "encomenda",
    "info_loja",
    "humano",
    "outro",
)

#: A confirmacao antiga ou invalida (§7.3 linha 24; dicionario §3.31). **Nao e
#: um dos onze erros tipados do §6.5**: nenhuma tool o devolve, nasce no
#: `confirm_gate`, e por isso nao entra no `CODIGOS` do `tls/erros.py` — entrava
#: no `CHECK` fechado da `tool_audit.error_code`, que e uma revisao de base de
#: dados para um valor que nenhuma linha de auditoria pode levar.
STALE_CONFIRMATION: Final = "STALE_CONFIRMATION"

#: O dominio fechado de `state.avisos` (emenda 1.40). Os sete primeiros sao
#: erros tipados do §6.5 que o §6.5 manda o `compose` explicar; o oitavo e o de
#: cima. **Fechado** porque o `compose` decide por valor conhecido: um aviso que
#: ele nao conheca cai na explicacao de omissao, e a de omissao nao e a de uma
#: recusa por regra.
AVISOS: Final = (
    "NOT_FOUND",
    "OUT_OF_STOCK",
    "PRICE_CHANGED",
    "LIMIT_EXCEEDED",
    "VALIDATION_ERROR",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_DOWN",
    STALE_CONFIRMATION,
)

#: Os desfechos da linha 4 — porque e que um turno nao corre (§3.31).
RECUSAS: Final = ("turno_repetido", "contacto_bloqueado", "ritmo")

#: Os seis veredictos da guarda de entrada (§7.3 linhas 8 a 10; §8.4).
VEREDICTOS_DE_GUARDA: Final = (
    "ok",
    "injection",
    "abuse",
    "out_of_domain",
    "card_data",
    "sensitive",
)


@dataclass(frozen=True, slots=True)
class Aresta:
    """Uma aresta do §7.3, com a linha que a autoriza.

    A `chave` e `None` numa aresta directa (`add_edge`) e e a chave do `path_map`
    numa condicional (`add_conditional_edges`). A `condicao` e a coluna
    «Condicao» do §7.3, encurtada: esta aqui para que quem le o codigo nao tenha
    de abrir o documento para saber **quando** a aresta e tomada.
    """

    linha: int
    de: str
    para: str
    chave: str | None
    condicao: str

    @property
    def condicional(self) -> bool:
        return self.chave is not None


#: As quarenta e duas arestas, pela ordem das linhas do §7.3.
ARESTAS: Final = (
    Aresta(1, START, "ingest", None, "sempre"),
    Aresta(2, "ingest", "stt", "stt", "input_kind == audio"),
    Aresta(3, "ingest", "guard_in", "guard_in", "texto, botao, localizacao"),
    Aresta(4, "ingest", END, "end", "turno repetido, contacto bloqueado ou ritmo"),
    Aresta(5, "stt", "guard_in", "ok", "confianca alta e idioma pt"),
    Aresta(6, "stt", "ask_repeat", "repeat", "confianca media (§10)"),
    Aresta(7, "stt", "handoff_prepare", "human", "confianca baixa, idioma ou duracao"),
    Aresta(8, "guard_in", "classify", "ok", "veredicto ok"),
    Aresta(9, "guard_in", "safe_reply", "safe", "injection, abuse, out_of_domain, card_data"),
    Aresta(10, "guard_in", "handoff_prepare", "human", "sensitive"),
    Aresta(11, "classify", "retrieve", "search", "produto, preco_stock"),
    Aresta(12, "classify", "cart_build", "buy", "comprar"),
    Aresta(13, "classify", "confirm_gate", "confirm", "confirmar (botao confirm:*)"),
    Aresta(14, "classify", "order_status", "status", "pagamento_estado, encomenda"),
    Aresta(15, "classify", "tools_info", "info", "info_loja"),
    Aresta(16, "classify", "handoff_prepare", "human", "humano"),
    Aresta(17, "classify", "safe_reply", "other", "outro"),
    Aresta(18, "retrieve", "tools_read", "hit", "melhor resultado >= limiar"),
    Aresta(19, "retrieve", "unknown_reply", "miss", "abaixo do limiar"),
    Aresta(20, "tools_read", "compose", None, "sempre"),
    Aresta(21, "cart_build", "compose", "ok", "carrinho criado, ou sem stock/preco alterado"),
    Aresta(22, "cart_build", "handoff_prepare", "down", "UPSTREAM_* apos retry"),
    Aresta(23, "confirm_gate", "create_order", "go", "estado, cart_id e validade batem"),
    Aresta(24, "confirm_gate", "compose", "stale", "confirmacao antiga ou invalida"),
    Aresta(25, "create_order", "compose", "ok", "sucesso ou recusa por regra"),
    Aresta(26, "create_order", "handoff_prepare", "down", "UPSTREAM_* persistente"),
    # A linha 27 carrega **duas** arestas.
    Aresta(27, "order_status", "compose", None, "sempre"),
    Aresta(27, "tools_info", "compose", None, "sempre"),
    Aresta(28, "compose", "validate", None, "sempre"),
    Aresta(29, "validate", "guard_out", "ok", "citacoes e sku conferem"),
    Aresta(30, "validate", "compose", "retry", "falha e citation_retries < 1"),
    Aresta(31, "validate", "handoff_prepare", "human", "falha e citation_retries >= 1"),
    Aresta(32, "guard_out", "send", "ok", "ok"),
    Aresta(33, "guard_out", "safe_reply", "safe", "violacao de politica"),
    # A linha 34 carrega **tres**.
    Aresta(34, "unknown_reply", "send", None, "sempre (texto estatico)"),
    Aresta(34, "ask_repeat", "send", None, "sempre (texto estatico)"),
    Aresta(34, "safe_reply", "send", None, "sempre (texto estatico)"),
    Aresta(35, "send", END, None, "sempre; idempotency_key = turn_id:seq"),
    Aresta(36, "handoff_prepare", "handoff_wait", "wait", "openHandoff ok"),
    Aresta(37, "handoff_prepare", "send", "degraded", "HND indisponivel"),
    Aresta(38, "handoff_wait", "handoff_close", None, "retoma (Command(resume=...))"),
    Aresta(39, "handoff_close", END, None, "sempre"),
)


def pares() -> frozenset[tuple[str, str]]:
    """As arestas como pares `(de, para)` — o que se compara com o compilado."""
    return frozenset((a.de, a.para) for a in ARESTAS)


def mapa_de(no: str) -> dict[str, str]:
    """O `path_map` de um no condicional, derivado da tabela.

    **O mapa nao se escreve duas vezes.** Escrito a mao no `grafo.py`, o teste de
    contrato comparava a tabela com um mapa que alguem podia ter divergido dela —
    e passava, porque o conjunto de arestas e o mesmo com dois destinos trocados.
    Derivando-o daqui, a tabela e a unica fonte e a troca deixa de ser possivel.
    """
    saidas = {a.chave: a.para for a in ARESTAS if a.de == no and a.condicional}
    if not saidas:
        raise KeyError(f"{no!r} nao tem arestas condicionais na tabela de §7.3")
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
    """As arestas do grafo **compilado**, lidas do LangGraph.

    E o `get_graph()` do `CompiledStateGraph` e nao a nossa tabela: um teste que
    comparasse a tabela consigo mesma nao prova nada sobre o grafo que vai
    correr. Foi a licao que o criterio 3 do KAM-027 pagou — «esse teste contra um
    objecto inventado prova que o nosso `nos_do_grafo` le o nosso proprio duplo».
    """
    desenho = compilado.get_graph()
    return frozenset((a.source, a.target) for a in desenho.edges)


def nos_do_compilado(compilado: Any) -> frozenset[str]:
    """Os nos do grafo compilado, **sem** os sentinelas do LangGraph.

    O `__start__` e o `__end__` que o `get_graph()` devolve nao sao nos nossos:
    contá-los dava vinte e tres onde o §7.4 escreve vinte e um, e foi a mutacao
    `os sentinelas do LangGraph passam a contar como nos` do KAM-027.
    """
    return frozenset(compilado.get_graph().nodes) - {START, END}

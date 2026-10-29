"""Os nos e as arestas do grafo do Vendedor (§7.3, o concierge e o modo degradado).

A tabela tem **tres** fontes, e cada aresta diz qual pelo campo `fonte`: o §7.3
(KAM-031), o KAM-114 (concierge) e o KAM-037 (modo deterministico). E o que
permite as contagens do §7.3 continuarem verificaveis sem inflacionar um
documento que nenhum dos dois tickets abre.

## Porque e que a tabela vive em codigo, e nao so no documento

O criterio 1 do bloco do KAM-031 pede «o teste de contrato (tabela `EDGES` em
codigo **comparada** com o grafo compilado)». A tabela abaixo e essa: cada
aresta leva o numero da linha de `docs/tecnica/02` §7.3 que a autoriza, e o
teste confronta o conjunto com o que o `get_graph()` do LangGraph devolve. Uma
aresta a mais no grafo ou a menos na tabela falha, nos dois sentidos.

## Trinta e nove linhas, quarenta e duas arestas

A tabela do §7.3 tem **trinta e nove linhas** e o criterio escreve «as 39
arestas». Sao grandezas diferentes, e a diferenca mede-se: **duas** linhas
carregam mais do que uma aresta (e nao tres, como a primeira versao desta nota
dizia — a contagem estava certa e a palavra nao) —

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
#: **1.1.0 e nao 1.0.1:** o KAM-114 acrescenta dois nos (`draft_prepare` e
#: `draft_wait`) e a regra desta constante e «sobe no *minor* quando um no entra
#: ou sai». Nao e *major* porque o estado continua compativel com um `interrupt`
#: pendente: os campos que o concierge acrescenta sao novos e opcionais, e um
#: *checkpoint* escrito pela 1.0.0 lê-se sem eles — o `handoff_wait` de um
#: *thread* a espera retoma como antes.
#:
#: **1.2.0 e nao 1.1.1:** o KAM-037 acrescenta **um** no (`degraded_menu`) e a
#: regra e a mesma. Tambem nao e *major*, pela mesma leitura: o `degradado` que
#: o modo escreve e um campo novo e opcional do `ConversaState`, reiniciado em
#: cada turno pelo `CAMPOS_DO_TURNO`, e um *checkpoint* escrito pela 1.1.0 le-se
#: sem ele — um `draft_wait` ou um `handoff_wait` a espera retoma como antes,
#: porque nenhum dos dois o consulta.
#:
#: **O SemVer e a metade do «Eval-gate» do DoD que este ticket consegue
#: entregar.** A outra metade — «casos degradados no *golden*» — depende do gate
#: 13, que **nao existe** e nasce com o KAM-040; a caixa fica vazia, com a razao
#: escrita na secção de verificacao do bloco.
VERSAO_DO_GRAFO: Final = "1.2.0"

#: O numero de linhas da tabela de §7.3. Afirma-se para que o numero do criterio
#: 1 continue verificavel depois de alguem perceber que as arestas sao mais.
LINHAS_DO_73: Final = 39

#: O valor de `Aresta.fonte` das arestas que o KAM-114 acrescenta. **Nao estao
#: no §7.3** e por isso nao contam para o `LINHAS_DO_73`: o documento continua a
#: ter trinta e nove linhas, e inflacionar a constante era faze-la mentir sobre
#: um ficheiro que este ticket nao abre.
FONTE_DO_CONCIERGE: Final = "KAM-114"

#: O valor de `Aresta.fonte` das arestas que o KAM-037 acrescenta. Pela razao do
#: `FONTE_DO_CONCIERGE`: nao estao no §7.3 e nao contam para o `LINHAS_DO_73`.
FONTE_DO_DEGRADADO: Final = "KAM-037"

#: As fontes que **nao** sao o §7.3. E por esta lista que o `do_73` filtra, e nao
#: por uma comparacao com o `FONTE_DO_CONCIERGE`: a primeira versao do `do_73`
#: escrevia `a.fonte != FONTE_DO_CONCIERGE`, o que contava como sendo do §7.3
#: **toda** a fonte futura que nao fosse o concierge — e a primeira a aparecer
#: foi a deste ticket, que teria inflacionado a contagem das quarenta e duas
#: para quarenta e quatro sem ninguem notar. Um filtro por negacao de **um**
#: valor nao e um filtro: e uma lista de proibidos com um elemento.
FONTES_FORA_DO_73: Final = (FONTE_DO_CONCIERGE, FONTE_DO_DEGRADADO)

#: A `fonte` da **unica** aresta do §7.3 que o KAM-114 altera: a 35, que passou
#: de incondicional («sempre») a condicional. Nao fica com a omissao, e a razao
#: e o proprio mecanismo do `fonte`: ele existe para que cada aresta diga quem a
#: autoriza, e deixa-la a apontar para um §7.3 que a descreve como «sempre» era
#: usa-lo para mentir na primeira aresta a que ele se aplica com proveito.
#: Apanhado pela revisao adversarial.
#:
#: **Conta para o `LINHAS_DO_73`**: a linha 35 continua a existir no documento,
#: e o que mudou foi a forma e nao a autoria.
FONTE_ALTERADA_PELO_CONCIERGE: Final = "02 §7.3, alterada por KAM-114"

#: Os **vinte e quatro** nos, pela ordem do §7.4 e depois pela dos dois tickets
#: que a estenderam. O §7.4 fixa **vinte e um** e continua a fixa-los; os outros
#: tres sao os dois do KAM-114 e o do KAM-037, cada um com a sua `fonte` na
#: tabela de arestas. **A frase anterior dizia «os vinte e um nos» com vinte e
#: tres na lista imediatamente abaixo**, e com vinte e quatro depois deste ticket
#: — apanhado pela revisao adversarial (achado C12). Lista **fechada**: e por ela que o
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
    # KAM-114: os dois do concierge. **Nao estao no §7.4**, que fixa vinte e um:
    # vem do bloco do ticket, que os nomeia nos Detalhes Tecnicos («nos
    # `draft_prepare` e `draft_wait`, sem efeitos antes do `interrupt()`»), e o
    # dicionario §3.34 declara-os. Ver o `FONTE_DO_CONCIERGE` abaixo.
    "draft_prepare",
    "draft_wait",
    # KAM-037: o no do modo deterministico. **Um e nao tres**, e a contagem e o
    # resultado de reutilizar: o `order_status`, o `tools_info`, o
    # `confirm_gate`, o `create_order` e o `handoff_prepare` servem o modo
    # degradado tal como estao (e o que o bloco manda), e o que nao existia era
    # o menu. O dicionario §3.35 declara-o.
    "degraded_menu",
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

#: A consulta de um pedido sem o cliente ter dito qual (KAM-037). **Nao e um dos
#: onze erros tipados do §6.5** e nao e `NOT_FOUND`, e a distincao e a correccao
#: do achado C2 da revisao adversarial: «nao me disse qual» nao e «nao existe», e
#: confundir os dois dizia «Nao encontrei esse **artigo** no **catalogo** da
#: loja» a quem pediu o estado de um pedido. Nasce no `order_status`, como o
#: `STALE_CONFIRMATION` nasce no `confirm_gate`, pelo que tambem nao entra no
#: `CODIGOS` do `tls/erros.py` — entrava no `CHECK` fechado da
#: `tool_audit.error_code`, que e uma revisao de base de dados para um valor que
#: nenhuma linha de auditoria pode levar.
REFERENCIA_EM_FALTA: Final = "REFERENCIA_EM_FALTA"

#: O dominio fechado de `state.avisos` (emenda 1.40, mais o do KAM-037). Os sete
#: primeiros sao erros tipados do §6.5 que o §6.5 manda o `compose` explicar; os
#: dois ultimos nascem em nos nossos. **Fechado** porque o `compose` decide por
#: valor conhecido: um aviso que ele nao conheca cai na explicacao de omissao, e
#: a de omissao nao e a de uma recusa por regra.
AVISOS: Final = (
    "NOT_FOUND",
    "OUT_OF_STOCK",
    "PRICE_CHANGED",
    "LIMIT_EXCEEDED",
    "VALIDATION_ERROR",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_DOWN",
    STALE_CONFIRMATION,
    REFERENCIA_EM_FALTA,
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
    #: De onde vem a autorizacao desta aresta. Por omissao o §7.3, que e a fonte
    #: das quarenta e duas do KAM-031.
    #:
    #: **Existe porque o grafo passou a ter duas fontes** (KAM-114), e sem ela o
    #: `LINHAS_DO_73` deixava de poder dizer a verdade: ou contava arestas que o
    #: §7.3 nao tem, ou obrigava a inventar linhas num documento que este ticket
    #: nao altera. Com o campo, cada aresta diz quem a autoriza e as duas
    #: contagens continuam verificaveis em separado.
    fonte: str = "02 §7.3"

    @property
    def condicional(self) -> bool:
        return self.chave is not None


#: As arestas do grafo: as quarenta e duas do §7.3 (KAM-031) mais as quatro
#: do concierge (KAM-114), pela ordem das linhas. O `fonte` de cada uma diz
#: quem a autoriza, e e por ele que as duas contagens se provam em separado.
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
    # **A linha 35 passou a condicional com o KAM-114**, e e a unica aresta do
    # §7.3 que este ticket toca. O §7.3 escreve «sempre», e e o que ela faz
    # quando a politica `concierge` esta desligada — que e o caso de todos os
    # *tenants* que nao estao no Piloto. Com a politica ligada, o `send` nao
    # envia: desvia para o pedido de aprovacao pela aresta `aprovar`.
    #
    # O desvio e **aqui** e nao na entrada de cada caminho porque sao **cinco**
    # as arestas que chegam ao `send` (32, as tres da 34, e a 37), e o criterio
    # 1 conta «0 mensagens ao cliente sem decisao» — uma resposta estatica e
    # uma mensagem ao cliente tanto como uma composta. Interceptar num sitio
    # cobre as cinco; interceptar a entrada obrigava a cinco condicionais e a
    # primeira esquecida era uma mensagem a sair sem aprovacao.
    Aresta(
        35,
        "send",
        END,
        "enviado",
        "enviado, ou politica concierge desligada",
        fonte=FONTE_ALTERADA_PELO_CONCIERGE,
    ),
    Aresta(36, "handoff_prepare", "handoff_wait", "wait", "openHandoff ok"),
    Aresta(37, "handoff_prepare", "send", "degraded", "HND indisponivel"),
    Aresta(38, "handoff_wait", "handoff_close", None, "retoma (Command(resume=...))"),
    Aresta(39, "handoff_close", END, None, "sempre"),
    # ------------------------------------------------- KAM-114, o concierge
    #
    # Quatro arestas, numeradas a seguir as do §7.3 e com `fonte` propria. O
    # ciclo `send -> draft_prepare -> draft_wait -> send` **e** um ciclo, e e
    # limitado por construcao: a segunda visita ao `send` traz a decisao no
    # estado, pelo que sai pela `enviado`. Sem a decisao nao ha segunda visita —
    # o `draft_wait` esta interrompido.
    Aresta(
        40,
        "send",
        "draft_prepare",
        "aprovar",
        "politica concierge ligada e sem decisao humana",
        fonte="KAM-114",
    ),
    Aresta(
        41,
        "draft_prepare",
        "draft_wait",
        None,
        "sempre; mesmo com o HND em baixo (nada sai sem decisao)",
        fonte="KAM-114",
    ),
    Aresta(
        42,
        "draft_wait",
        "send",
        "enviar",
        "decisao aprovado ou editado",
        fonte="KAM-114",
    ),
    Aresta(
        43,
        "draft_wait",
        END,
        "end",
        "decisao rejeitado, expirado ou substituido",
        fonte="KAM-114",
    ),
    # ------------------------------------------- KAM-037, o modo deterministico
    #
    # **Duas arestas, e o resto do modo sao as que ja existem.** O sub-grafo
    # deterministico entra pelo `classify`, que em modo degradado encaminha para
    # o `degraded_menu` em vez de para o `retrieve` ou o `cart_build` — e sai
    # pelo `validate`, como o `compose`, porque o criterio 5 manda o validador
    # aplicar-se **tambem** aqui.
    #
    # O que **nao** se escreve sao arestas novas para o `order_status`, o
    # `tools_info`, o `confirm_gate` e o `handoff_prepare`: as linhas 13, 14, 15
    # e 16 do §7.3 ja ligam o `classify` aos quatro, e um turno degradado toma-as
    # com a intencao que o `intencoes.serve` reconhece. Duplicar o destino com
    # chave propria dava duas arestas para o mesmo par `(de, para)` e o conjunto
    # que o teste de contrato compara era o mesmo — isto e, uma aresta a mais na
    # tabela que o grafo compilado nao pode desmentir.
    Aresta(
        44,
        "classify",
        "degraded_menu",
        "menu",
        "degradado e a intencao nao e servida pelo modo",
        fonte=FONTE_DO_DEGRADADO,
    ),
    Aresta(
        45,
        "degraded_menu",
        "validate",
        None,
        "sempre; o validador aplica-se tambem ao modo deterministico",
        fonte=FONTE_DO_DEGRADADO,
    ),
)


def do_73() -> tuple["Aresta", ...]:
    """So as arestas que o §7.3 autoriza. E o universo do `LINHAS_DO_73`.

    O filtro e por **lista de fontes de fora** e nao por negacao de uma: ver o
    `FONTES_FORA_DO_73`.
    """
    return tuple(a for a in ARESTAS if a.fonte not in FONTES_FORA_DO_73)


def do_concierge() -> tuple["Aresta", ...]:
    """So as arestas que o KAM-114 acrescenta."""
    return tuple(a for a in ARESTAS if a.fonte == FONTE_DO_CONCIERGE)


def do_degradado() -> tuple["Aresta", ...]:
    """So as arestas que o KAM-037 acrescenta."""
    return tuple(a for a in ARESTAS if a.fonte == FONTE_DO_DEGRADADO)


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

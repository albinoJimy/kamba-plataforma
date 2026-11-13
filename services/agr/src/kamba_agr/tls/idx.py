"""O executor do `search_catalog`: a TLS a falar com o indice (KAM-061).

O `search_catalog` era a quinta tool do Vendedor sem executor, com o credor
KAM-061 (`tls/vendedor.py`). Este modulo e esse credor: liga-a ao
`idx.candidatos` pela camada de resposta do `docs/tecnica/05` §6.3
(`kamba_core.idx.pesquisa`), que junta os candidatos a oferta viva.

## O tenant e o do estado, e so dele

O executor le o `tenant_id` do `ToolContext` (`pedido.ctx`), que a camada
constroi do estado do turno — nunca dos argumentos, que o modelo escreve e o
`ArgumentosDeSearchCatalog` recusa se trouxerem um campo a mais. E a consulta da
camada de resposta **nao tem parametro de tenant**: le o `app.tenant_id` que o
`tenant_guard.tx` poe, o mesmo que a RLS das tres relacoes le.

## O par (pontuador, limiar) do indice real, e o seu dono

O `retrieve` do grafo compara o `score` de cada candidato com um limiar
(`Dependencias.limiar_idx`). O duplo do Vendedor (`verticais/vendedor/fakes.py`)
da um `score` em [0, 1] — a fraccao da designacao que a pergunta cobre — e o
`LIMIAR_IDX = 0.5` do `nos.py` e o limiar **desse** pontuador.

O RRF do §6.2 nao vive nessa escala: com os pesos 0,5 / 0,3 / 0,2 e `k = 60`, o
maximo e cerca de 0,016. Comparado com 0,5, **toda** a pesquisa real caia no
`unknown_reply` — o defeito nao e o valor do limiar, e a escala. Por isso o
`score` que sai daqui e o RRF **normalizado pelo seu maximo teorico**:

    score = o_score / (soma dos pesos dos ramos activos / (p_rrf_k + 1))

Os ramos activos sao os tres com vector e so `tri` e `fts` no modo lexical,
porque sem vector o ramo `sem` nao pode contribuir e o maximo que se alcanca e
o dos outros dois. Um documento no primeiro lugar dos ramos activos da 1,0; no
primeiro lugar so do `fts`, 0,4; so do `tri`, 0,6.

E o limiar deste pontuador e o `LIMIAR_DO_RRF`, *proposta*, que o `__main__`
passa ao grafo junto com o executor. **Os dois estao aqui e mudam juntos.** A
calibracao dos dois e do **KAM-064**, com o *dataset* `golden_search`, pela
letra do bloco KAM-061 («afina so o limiar `pg_trgm` com o dataset»).

**O que o KAM-064 mediu** (divisao `dev`, `eval/search/reports/1.0.0.md`): no
modo lexical, de 0,0 a 0,35 o limiar nao corta nada; a 0,4 corta o posto 1 so
do `fts` e troca falso-positivo em «nao resolvivel» (17,6% -> 5,9%) por
success@3 (0,954 -> 0,883) e zero-result (3% -> 11%, acima do alvo de 8%). O
0,3 fica. **No modo hibrido o 0,3 nao serve**: o ramo `sem` da sempre um posto
1, que normalizado vale 0,5, e nenhuma pergunta fica vazia (falso-positivo
100%). Calibra-se com o modelo real, antes de o vector se ligar: **KAM-199**.

## O que o limiar *proposta* faz, e o que nao faz

**0,3** deixa passar todo o candidato que o indice devolveu no topo — incluindo
a frase de WhatsApp tipica («quero comprar nike»), que o trigrama da frase
inteira nao apanha e o `fts` com o `or` apanha, a 0,4 — e corta so a cauda do
`fts` abaixo do posto 21, que o `LIMIT 3` da resposta ja corta. Ou seja: no modo
lexical, «nao resolvivel» e **a resposta vazia**, e nao um limiar. **No modo
hibrido nao e assim**: o ramo `sem` devolve sempre os vizinhos mais proximos,
haja ou nao correspondencia, e um so posto 1 vale 0,5. O vector chegou com o
KAM-063 (a `LigacaoVectorial`, que so liga com modelo escolhido), e o limiar do
modo hibrido calibra-se com o dataset do KAM-064.

**E um limite que o modo lexical tem, dito:** uma pergunta que partilhe um so
termo com um produto («quero uma bicicleta azul» e a «Camisa azul») devolve-o, e
o `cart_build` propoe-no — o cliente confirma por botao antes de haver encomenda.
Os algarismos ja nao contam (sao restricao, passo 3 do §5.1). O resto e o par do
KAM-064.
"""

from __future__ import annotations

import functools
import re
import time
from typing import Any, Final

from kamba_core.idx import pesquisa
from kamba_core.idx.embeddings import ConsultaVectorial
from kamba_core.idx.metricas import METRICAS as METRICAS_DO_IDX

from .erros import VALIDATION_ERROR
from .especificacoes import ErroDeBackend, Pedido, Resposta
from .get_store_info import _e_cancelamento

#: O limiar do `retrieve` contra o `score` normalizado deste modulo. *Proposta*;
#: calibra-se no KAM-064 (ver a nota do modulo).
LIMIAR_DO_RRF: Final = 0.3

#: Os pesos e o `k` com que o `idx.candidatos` corre: os da omissao do §6.2,
#: que a camada de resposta nao muda. Escritos aqui porque o maximo teorico do
#: RRF e funcao deles.
PESOS: Final = {"sem": 0.5, "tri": 0.3, "fts": 0.2}
RRF_K: Final = 60

#: O unico filtro que o `search_catalog` aceita, e e o do §6.3: o tecto de preco,
#: em unidade menor inteira, aplicado na oferta viva e nunca no indice.
FILTRO_DE_PRECO: Final = "max_preco_minor"

#: Um inteiro nao negativo que cabe num `bigint`: ate 18 algarismos ASCII.
_INTEIRO_NAO_NEGATIVO: Final = re.compile(r"[0-9]{1,18}")


def maximo_teorico(*, hibrido: bool) -> float:
    """O maior `o_score` que o RRF pode dar, com os ramos activos."""
    activos = ("sem", "tri", "fts") if hibrido else ("tri", "fts")
    return sum(PESOS[ramo] for ramo in activos) / (RRF_K + 1)


def score_normalizado(o_score: float, *, hibrido: bool) -> float:
    """O `o_score` do RRF em [0, 1], pelo maximo teorico dos ramos activos."""
    return min(1.0, max(0.0, o_score / maximo_teorico(hibrido=hibrido)))


def _tecto_de_preco(filtros: dict[str, str]) -> int | None:
    desconhecidos = sorted(set(filtros) - {FILTRO_DE_PRECO})
    if desconhecidos:
        raise ErroDeBackend(
            VALIDATION_ERROR,
            f"filtro(s) que a pesquisa nao conhece: {', '.join(desconhecidos)}",
        )
    bruto = filtros.get(FILTRO_DE_PRECO)
    if bruto is None:
        return None
    # ASCII e no maximo 18 algarismos, e nao `str.isdigit`: este aceita «²», que
    # o `int` recusa com `ValueError`, e um valor acima do `bigint` rebentava na
    # base em vez de voltar como `VALIDATION_ERROR` (achado 9 da revisao).
    if not _INTEIRO_NAO_NEGATIVO.fullmatch(bruto):
        raise ErroDeBackend(
            VALIDATION_ERROR,
            f"`{FILTRO_DE_PRECO}` e unidade menor inteira e nao negativa",
        )
    return int(bruto)


class LigacaoVectorial:
    """O fio entre o executor e a `ConsultaVectorial`, ligado no arranque.

    Pela razao da `CredencialDoCom` do `__main__`: o catalogo da ToolLayer
    constroi-se **antes** do cliente do gateway, e o executor nasce sem ele. Ao
    contrario daquela, **nao levanta** sem ligacao: sem vector a pesquisa e
    lexical, que e o estado de repouso enquanto o `kamba-embed` nao tem modelo.
    """

    __slots__ = ("_vectorial",)

    def __init__(self) -> None:
        self._vectorial: ConsultaVectorial | None = None

    def ligar(self, vectorial: ConsultaVectorial | None) -> None:
        self._vectorial = vectorial

    @property
    def actual(self) -> ConsultaVectorial | None:
        return self._vectorial


def executar(pedido: Pedido, ligacao: LigacaoVectorial | None = None) -> Resposta:
    """`search_catalog(query, filtros)`: ate tres candidatos, com `score` em [0, 1].

    Cada candidato e a linha do contrato do §6.3 e o `score` normalizado. **Sem
    *facts***, como o duplo: o preco que o cliente le vem do `get_price_stock`
    do turno, e o `retrieve` so guarda `sku`, `nome` e `preco_tipo`.

    Com a `ligacao` ligada, tenta o modo hibrido (KAM-063); o modo que correu
    vem da `Procura` e decide **as duas coisas** que dependem dele: o maximo
    teorico do pontuador e a etiqueta `modo` das metricas.
    """
    if pedido.ligacao is None:
        raise RuntimeError(
            "o `search_catalog` le o `idx` e precisa de ligacao. Uma especificacao "
            "de backend `idx` sem tomada e defeito de registo, nao resposta"
        )
    tecto_de_preco = _tecto_de_preco(dict(pedido.args.filtros))
    # O prazo do vector cabe no tecto da tool: quem o corta e o `procurar`,
    # que conta tambem o tempo da porta e da primeira transaccao.
    vectorial = ligacao.actual if ligacao is not None else None
    inicio = time.perf_counter()
    try:
        procura = pesquisa.procurar(
            pedido.ligacao,
            pedido.ctx.tenant_id,
            pedido.args.query,
            max_preco_minor=tecto_de_preco,
            tecto_ms=pedido.timeout_ms,
            vectorial=vectorial,
        )
    except Exception as erro:
        # O tecto do servidor volta como `UPSTREAM_TIMEOUT`, pela razao do
        # `get_store_info`: o `camada.py` so reconhece `TimeoutError`.
        if _e_cancelamento(erro):
            raise TimeoutError(
                f"a pesquisa passou do tecto de {pedido.timeout_ms} ms"
            ) from erro
        raise
    # **Uma variavel e nao dois literais**: o mesmo facto decide o maximo
    # teorico do pontuador e a etiqueta `modo` das metricas (KAM-193), e e o
    # modo que **correu**, lido da `Procura` — nao o que se pediu.
    hibrido = procura.modo == pesquisa.MODO_HIBRIDO
    # So a pesquisa que respondeu entra na serie (KAM-193). Uma que passou do
    # tecto tinha a duracao do tecto e nao a da pesquisa, e um *gauge* com o
    # ultimo valor ficava preso ao numero que o chamador escolheu. **O limite
    # disto, dito:** a falta conta-se no `agr_tool_erros_total{codigo}` da
    # ToolLayer, que soma as tools todas e nao diz qual falhou, pelo que o
    # `idx_mode` nao tem denominador para uma taxa de falha **da pesquisa**. E
    # quando o tecto que estoura e o da camada (`asyncio.wait_for`), a camada
    # responde `UPSTREAM_TIMEOUT` sem esperar por este executor: se a pesquisa
    # acabar depois, ela entra aqui como resposta, com a duracao longa. A
    # pergunta **nao** passa para a metrica: o registo so recebe o modo, a
    # duracao e o numero de candidatos.
    METRICAS_DO_IDX.registar_pesquisa(
        modo="hibrido" if hibrido else "lexical",
        duracao_ms=(time.perf_counter() - inicio) * 1_000,
        resultados=len(procura.linhas),
    )
    candidatos: list[dict[str, Any]] = [
        {**linha, "score": round(score_normalizado(score, hibrido=hibrido), 4)}
        for linha, score in procura.linhas
    ]
    dados: dict[str, Any] = {"candidatos": tuple(candidatos)}
    pergunta = pergunta_da_normalizacao(procura.normalizacao)
    if pergunta is not None:
        dados["pergunta"] = pergunta
    return Resposta(data=dados)


def pergunta_da_normalizacao(normalizacao: Any) -> str | None:
    """A pergunta que a normalizacao pede ao AGR, ou `None` (KAM-062).

    Uma so, pela ordem do `PERGUNTAS_DO_IDX` do grafo: a ambiguidade primeiro
    (o que o cliente quer), depois a moeda (quanto quer gastar), depois a
    palavra desconhecida. **O codigo, e nunca a palavra**: o termo do cliente
    nao vai para o estado nem para a auditoria da tool.

    **Quem decide se pergunta e o `retrieve`**, e nao este executor: a palavra
    desconhecida so pergunta quando nenhum candidato passa o limiar do grafo, e
    o limiar e dele. Com o lexico vazio — o estado de producao enquanto o do
    §5.1 nao for validado —, «quero comprar arroz» tem «quero» e «comprar» fora
    do vocabulario da loja, e perguntar por elas trocava todo o pedido tipico
    de WhatsApp por uma pergunta (medido no `TestLigacaoDoAgr` do *gate* 8).
    """
    if normalizacao is None:
        return None
    if normalizacao.desambiguacoes:
        return "TERMO_AMBIGUO"
    if normalizacao.restricoes.moeda:
        return "MOEDA_ESTRANGEIRA"
    if normalizacao.tokens_nao_resolvidos:
        return "TERMO_DESCONHECIDO"
    return None


def executores_do_idx(ligacao: LigacaoVectorial | None = None) -> dict[str, Any]:
    """O executor do `search_catalog`, pelo nome canonico da tool."""
    if ligacao is None:
        return {"search_catalog": executar}
    return {"search_catalog": functools.partial(executar, ligacao=ligacao)}


__all__ = [
    "FILTRO_DE_PRECO",
    "LIMIAR_DO_RRF",
    "LigacaoVectorial",
    "executar",
    "executores_do_idx",
    "pergunta_da_normalizacao",
    "maximo_teorico",
    "score_normalizado",
]

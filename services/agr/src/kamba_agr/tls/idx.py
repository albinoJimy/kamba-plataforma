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

## O que o limiar *proposta* faz, e o que nao faz

**0,3** deixa passar todo o candidato que o indice devolveu no topo — incluindo
a frase de WhatsApp tipica («quero comprar nike»), que o trigrama da frase
inteira nao apanha e o `fts` com o `or` apanha, a 0,4 — e corta so a cauda do
`fts` abaixo do posto 21, que o `LIMIT 3` da resposta ja corta. Ou seja: no modo
lexical, «nao resolvivel» e **a resposta vazia**, e nao um limiar. **No modo
hibrido nao e assim**: o ramo `sem` devolve sempre os vizinhos mais proximos,
haja ou nao correspondencia, e um so posto 1 vale 0,5. O vector e o KAM-063, e
o limiar volta a mesa com ele.

**E um limite que o modo lexical tem, dito:** uma pergunta que partilhe um so
termo com um produto («quero uma bicicleta azul» e a «Camisa azul») devolve-o, e
o `cart_build` propoe-no — o cliente confirma por botao antes de haver encomenda.
Os algarismos ja nao contam (sao restricao, passo 3 do §5.1). O resto e o par do
KAM-064.
"""

from __future__ import annotations

import re
from typing import Any, Final

from kamba_core.idx import pesquisa

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


def executar(pedido: Pedido) -> Resposta:
    """`search_catalog(query, filtros)`: ate tres candidatos, com `score` em [0, 1].

    Cada candidato e a linha do contrato do §6.3 e o `score` normalizado. **Sem
    *facts***, como o duplo: o preco que o cliente le vem do `get_price_stock`
    do turno, e o `retrieve` so guarda `sku`, `nome` e `preco_tipo`.
    """
    if pedido.ligacao is None:
        raise RuntimeError(
            "o `search_catalog` le o `idx` e precisa de ligacao. Uma especificacao "
            "de backend `idx` sem tomada e defeito de registo, nao resposta"
        )
    tecto_de_preco = _tecto_de_preco(dict(pedido.args.filtros))
    try:
        resultados = pesquisa.candidatos(
            pedido.ligacao,
            pedido.ctx.tenant_id,
            pedido.args.query,
            max_preco_minor=tecto_de_preco,
            tecto_ms=pedido.timeout_ms,
        )
    except Exception as erro:
        # O tecto do servidor volta como `UPSTREAM_TIMEOUT`, pela razao do
        # `get_store_info`: o `camada.py` so reconhece `TimeoutError`.
        if _e_cancelamento(erro):
            raise TimeoutError(
                f"a pesquisa passou do tecto de {pedido.timeout_ms} ms"
            ) from erro
        raise
    candidatos: list[dict[str, Any]] = [
        {**linha, "score": round(score_normalizado(score, hibrido=False), 4)}
        for linha, score in resultados
    ]
    return Resposta(data={"candidatos": tuple(candidatos)})


def executores_do_idx() -> dict[str, Any]:
    """O executor do `search_catalog`, pelo nome canonico da tool."""
    return {"search_catalog": executar}


__all__ = [
    "FILTRO_DE_PRECO",
    "LIMIAR_DO_RRF",
    "executar",
    "executores_do_idx",
    "maximo_teorico",
    "score_normalizado",
]

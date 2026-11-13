"""A camada de resposta da pesquisa: candidatos do indice e oferta viva (§6.3).

E o que corre **dentro** da tool `search_products` (no AGR, `search_catalog`):
o `idx.candidatos` da a ordem, a `platform.v_oferta_viva` (KAM-051) da o `sku`,
o nome, o preco e o modo do preco no instante da pergunta. **O indice nao e fonte
de nenhum numero** (ADR-007): o `max_preco_minor` filtra a oferta viva, nunca o
indice.

## O tenant vem do contexto, e so dele

A consulta **nao tem parametro de tenant**. O `p_tenant` do `idx.candidatos` e o
`tenant_id` do *join* leem-se do `app.tenant_id` da transaccao, que o
`tenant_guard.tx` define — o mesmo valor que a RLS das tres relacoes le. Nao ha
por onde um tenant chegar do texto da pergunta, dos argumentos da tool ou de um
segundo parametro esquecido: o unico tenant que esta consulta conhece e o da
transaccao, e a transaccao so tem um. O ensaio de isolamento muta exactamente
esta ligacao (`db/tests_produtos/test_indice.py`, `TestResposta`).

## O que fica por entregar, dito

* **`disponivel`** e o filtro `stock_disp > 0` do §6.3 dependem do nivel de
  stock, que a vista nao tem: o criterio 7 do KAM-051 esta bloqueado pelo D3 e
  pelo KAM-045. O campo sai **`None`** — «nao sei» — e nao `True`, que afirmava
  um stock que ninguem leu, nem `False`, que escondia o produto. Pela mesma
  razao nao ha a segunda volta «com menos de 3, oferecer os indisponiveis».
* **O `alvo_preco_minor`** («250 mil» sem verbo, §5.2) so desempata: a ordem
  manda o `o_score`, e o alvo entra depois dele, pela distancia ao preco.

## A pergunta passa pela normalizacao PT-AO (KAM-062)

O texto do cliente passa pelos nove passos do §5.1
(`kamba_core.idx.normalizacao`), com o lexico e o vocabulario do tenant lidos
**na mesma transaccao** e com o mesmo contexto (`kamba_core.idx.lexico`). As
restricoes de preco que o cliente disse saem do texto e filtram a **oferta
viva** — o `max_preco_minor` e o `min_preco_minor` —, nunca o indice. Um tecto
dado pelo chamador e um tecto dito pelo cliente somam-se pelo mais apertado.
Uma moeda estrangeira nao filtra nada: a conversao nao e nossa, e o AGR
pergunta.
## O modo hibrido e uma tentativa, e o lexical e o chao (KAM-063)

Com uma `ConsultaVectorial`, o `procurar` le primeiro, numa transaccao curta, o
modelo dos vectores do tenant; so com **um** modelo pede o vector da pergunta
(`kamba_core.idx.embeddings`), **fora** de qualquer transaccao, e volta a ler o
modelo na transaccao da pesquisa antes de usar o vector. Sem ela, sem vectores
no indice, com a porta a negar, com o texto sensivel, com o tecto de 1,5 s
passado ou com dois modelos no tenant, o `p_qvec` vai nulo: e o modo lexical do
§6.5 — *fail closed* para o dado — e o cliente nao ve erro nenhum. O `modo` da
`Procura` diz qual correu.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from kamba_core.tenant_guard import tx

from . import lexico as lexico_mod
from .embeddings import SQL_MODELOS_DO_INDICE, ConsultaVectorial, modelo_do_indice
from .normalizacao import Normalizacao, normalizar

#: O que fica para a pesquisa quando o vector da pergunta gasta o seu prazo, em
#: ms. **Proposta.** O tecto de uma tool `read` e 2 s (§6.5 do `docs/tecnica/02`)
#: e o do embedding 1,5 s (criterio 3 do KAM-063): com esta reserva os dois
#: cabem, e um tecto menor encolhe o embedding e nao a pesquisa.
RESERVA_DA_PESQUISA_MS: Final = 500

#: Os dois modos do §6.5, com os nomes da metrica `idx_mode`.
MODO_HIBRIDO: Final = "hibrido"
MODO_LEXICAL: Final = "lexical"

#: O limiar do `pg_trgm` por transaccao (§6.2, nota i). **Proposta**, igual ao
#: `db/indice.py` `LIMIAR_DE_PALAVRA`; o valor final e do dataset (KAM-064).
LIMIAR_DE_PALAVRA: Final = 0.45

#: Quantas linhas a resposta devolve (§6.3, `LIMIT 3`).
LIMITE_DA_RESPOSTA: Final = 3

#: A fonte de todos os numeros da resposta. Constante do contrato (§6.3).
FONTE: Final = "registo"

#: Os oito campos do contrato de saida, pela ordem do §6.3.
CAMPOS_DO_CONTRATO: Final = (
    "sku",
    "product_ref",
    "nome",
    "preco_minor",
    "preco_tipo",
    "disponivel",
    "fonte",
    "lido_em",
)

#: O valor de `disponivel` enquanto nao houver nivel de stock: desconhecido.
DISPONIVEL_DESCONHECIDO: Final = None

#: O limiar, **local a transaccao** (`is_local = true`): morre no `COMMIT`.
SQL_LIMIAR: Final = """
  SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)
"""

#: A consulta do §6.3, com quatro diferencas: o tenant e o do contexto e nao um
#: parametro; a vista e a `platform.v_oferta_viva` do KAM-051 (o `com.` do
#: documento e ilustrativo); nao ha filtro de stock; e a ordem acaba no `v.sku`,
#: para que dois candidatos com o mesmo score e o mesmo preco saiam sempre pela
#: mesma ordem. O `NULLS LAST` ja e a omissao de um `ASC` e esta escrito pela
#: razao do `test_oferta_viva.py`: o `sob_consulta` tem `preco_minor` nulo, e um
#: `DESC` futuro invertia-o em silencio.
#:
#: Parametros: `p_q_norm`, `p_q_or`, `p_qvec` (texto `[...]` ou nulo), o
#: `max_preco_minor` duas vezes, o `min_preco_minor` duas vezes (nulo = sem
#: filtro) e o `alvo_preco_minor` (nulo = sem alvo).
SQL_RESPOSTA: Final = """
  SELECT v.sku, c.o_product_ref AS product_ref, v.nome, v.preco_minor,
         v.preco_tipo, v.lido_em, c.o_score
    FROM idx.candidatos(NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                        %s, %s, %s::halfvec) c
    JOIN platform.v_oferta_viva v
      ON v.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND v.product_ref = c.o_product_ref
   WHERE v.publicado
     AND (%s::bigint IS NULL OR v.preco_minor <= %s::bigint)
     AND (%s::bigint IS NULL OR v.preco_minor >= %s::bigint)
   ORDER BY c.o_score DESC, abs(v.preco_minor - %s::bigint) ASC NULLS LAST,
            v.preco_minor ASC NULLS LAST, v.sku
   LIMIT 3
"""


def _vector(qvec: Sequence[float] | None) -> str | None:
    if qvec is None:
        return None
    return "[" + ",".join(repr(float(x)) for x in qvec) + "]"


def _score(linha: Sequence[Any] | Mapping[str, Any]) -> float:
    bruto = linha["o_score"] if isinstance(linha, Mapping) else linha[6]
    return float(bruto)


def _linha(linha: Sequence[Any] | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(linha, Mapping):
        sku, ref, nome = linha["sku"], linha["product_ref"], linha["nome"]
        preco, tipo, lido = linha["preco_minor"], linha["preco_tipo"], linha["lido_em"]
    else:
        sku, ref, nome, preco, tipo, lido = linha[:6]
    return {
        "sku": sku,
        "product_ref": ref,
        "nome": nome,
        "preco_minor": preco,
        "preco_tipo": tipo,
        "disponivel": DISPONIVEL_DESCONHECIDO,
        "fonte": FONTE,
        "lido_em": lido.isoformat() if hasattr(lido, "isoformat") else lido,
    }


#: O tecto do servidor, por transaccao, quando o chamador o da (`SET LOCAL`).
SQL_TECTO: Final = """
  SELECT set_config('statement_timeout', %s, true)
"""


@dataclass(frozen=True)
class Procura:
    """A pergunta normalizada e o que ela encontrou.

    A `normalizacao` leva as perguntas que o AGR tem de fazer
    (`tokens_nao_resolvidos`, `desambiguacoes`, moeda estrangeira); as `linhas`
    sao as do contrato do §6.3, cada uma com o `o_score` ao lado. O `modo` e o
    que **correu**: `hibrido` so quando o vector foi ao `idx.candidatos`.
    """

    normalizacao: Normalizacao | None
    linhas: tuple[tuple[dict[str, Any], float], ...]
    modo: str = MODO_LEXICAL


def _mais_apertado(a: int | None, b: int | None) -> int | None:
    return b if a is None else a if b is None else min(a, b)


def procurar(
    conexao: Any,
    tenant: object,
    texto: str,
    *,
    origem: str = "texto",
    max_preco_minor: int | None = None,
    qvec: Sequence[float] | None = None,
    limiar: float = LIMIAR_DE_PALAVRA,
    tecto_ms: int | None = None,
    cache: lexico_mod.Cache = lexico_mod.CACHE,
    vectorial: ConsultaVectorial | None = None,
    relogio: Callable[[], float] = time.monotonic,
) -> Procura:
    """Normaliza a pergunta (§5.1) e devolve ate tres ofertas publicadas.

    O `tenant` so serve para abrir a transaccao (`tenant_guard.tx`), que recusa
    `None`, vazio e o que nao for UUID antes de tocar na base. Uma pergunta que
    normalizada fique vazia devolve vazio sem consulta: o `websearch_to_tsquery`
    de nada e um aviso, nao uma pesquisa. O `tecto_ms` poe o `statement_timeout`
    **do lado do servidor**, local a transaccao: um tecto so no cliente deixava
    a consulta a correr na base depois de o turno desistir dela. O tempo que o
    vector da pergunta levou **desconta-se** dele: o tecto e da pesquisa toda.

    Com `vectorial`, tenta o modo hibrido (ver a nota do modulo); um `qvec`
    dado explicitamente e usado tal como vem, e serve os ensaios da funcao.
    """
    if isinstance(max_preco_minor, bool) or (
        max_preco_minor is not None and not isinstance(max_preco_minor, int)
    ):
        raise TypeError("max_preco_minor e unidade menor inteira (dicionario §2)")
    modelo_esperado: str | None = None
    pergunta: Normalizacao | None = None
    if qvec is None and vectorial is not None:
        inicio = relogio()
        # Uma transaccao curta para o modelo e para a normalizacao: o vector
        # pede-se **fora** de qualquer transaccao, que nao fica aberta durante a
        # ida ao fornecedor. A normalizacao vem **antes** do vector: uma
        # pergunta que normalizada fica vazia («ate 5000 kz») nao pesquisa nada,
        # e o vector dela era uma transferencia sem uso (achado 4 da revisao).
        with tx(conexao, tenant) as previo:
            previo.execute(SQL_MODELOS_DO_INDICE)
            estado = modelo_do_indice(previo.fetchall())
            lexico, vocabulario = cache.entradas(previo, tenant)
            pergunta = normalizar(
                texto, tenant, origem, lexico=lexico, vocabulario=vocabulario
            )
        if not pergunta.q_norm:
            return Procura(pergunta, ())
        if estado.misturado:
            vectorial.mistura()
        elif estado.modelo is not None:
            # O prazo do vector e o tecto da pesquisa menos a reserva dela,
            # contado **daqui**: a porta e a transaccao de cima ja gastaram.
            prazo = (
                None
                if tecto_ms is None
                else inicio + (tecto_ms - RESERVA_DA_PESQUISA_MS) / 1000
            )
            resultado = vectorial.vector(
                str(tenant), texto, estado.modelo, enviar=pergunta.q_norm, prazo=prazo
            )
            qvec, modelo_esperado = resultado.qvec, resultado.modelo
        if tecto_ms is not None:
            tecto_ms = max(1, int(tecto_ms - (relogio() - inicio) * 1000))
    with tx(conexao, tenant) as cursor:
        if tecto_ms is not None:
            cursor.execute(SQL_TECTO, (str(int(tecto_ms)),))
        if modelo_esperado is not None:
            # O indice pode ter mudado de modelo entre as duas transaccoes: um
            # vector so se compara com vectores do modelo que o gerou.
            cursor.execute(SQL_MODELOS_DO_INDICE)
            if modelo_do_indice(cursor.fetchall()).modelo != modelo_esperado:
                qvec = None
                if vectorial is not None:
                    vectorial.mistura()
        if pergunta is None:
            lexico, vocabulario = cache.entradas(cursor, tenant)
            pergunta = normalizar(
                texto, tenant, origem, lexico=lexico, vocabulario=vocabulario
            )
        if not pergunta.q_norm:
            return Procura(pergunta, ())
        restricoes = pergunta.restricoes
        tecto = _mais_apertado(max_preco_minor, restricoes.max_preco_minor)
        cursor.execute(SQL_LIMIAR, (str(limiar),))
        cursor.execute(
            SQL_RESPOSTA,
            (
                pergunta.q_norm,
                pergunta.q_or,
                _vector(qvec),
                tecto,
                tecto,
                restricoes.min_preco_minor,
                restricoes.min_preco_minor,
                restricoes.alvo_preco_minor,
            ),
        )
        linhas = cursor.fetchall()
    return Procura(
        pergunta,
        tuple((_linha(linha), _score(linha)) for linha in linhas),
        MODO_LEXICAL if qvec is None else MODO_HIBRIDO,
    )


def candidatos(
    conexao: Any,
    tenant: object,
    texto: str,
    *,
    max_preco_minor: int | None = None,
    qvec: Sequence[float] | None = None,
    limiar: float = LIMIAR_DE_PALAVRA,
    tecto_ms: int | None = None,
) -> tuple[tuple[dict[str, Any], float], ...]:
    """Ate tres ofertas publicadas, cada uma com o `o_score` do RRF ao lado.

    A linha e a do contrato do §6.3; o `o_score` **nao** entra nela — e da
    ordenacao e do limiar de quem chama (o `retrieve` do AGR, pelo
    `kamba_agr.tls.idx`), e nao diz respeito ao cliente. E o `procurar` sem a
    normalizacao a vista.
    """
    return procurar(
        conexao, tenant, texto,
        max_preco_minor=max_preco_minor, qvec=qvec, limiar=limiar, tecto_ms=tecto_ms,
    ).linhas


def pesquisar(
    conexao: Any,
    tenant: object,
    texto: str,
    *,
    max_preco_minor: int | None = None,
    qvec: Sequence[float] | None = None,
    limiar: float = LIMIAR_DE_PALAVRA,
) -> tuple[dict[str, Any], ...]:
    """Ate tres ofertas publicadas do tenant, no contrato do §6.3 e so nele."""
    return tuple(
        linha
        for linha, _ in candidatos(
            conexao, tenant, texto,
            max_preco_minor=max_preco_minor, qvec=qvec, limiar=limiar,
        )
    )

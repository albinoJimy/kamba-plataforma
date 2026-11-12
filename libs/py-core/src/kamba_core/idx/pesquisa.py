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
* **Os sinonimos e as marcas** da pergunta sao o KAM-062; a expansao `q_or` e so
  os termos da pergunta (`kamba_core.idx.texto.consulta`).
* **O `qvec`** (embedding da pergunta) e o KAM-063. Aqui passa-se `None`, que e o
  modo lexical do §6.5 — *fail closed* para o dado.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from kamba_core.tenant_guard import tx

from .texto import consulta

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
#: Parametros: `p_q_norm`, `p_q_or`, `p_qvec` (texto `[...]` ou nulo) e o
#: `max_preco_minor` duas vezes (nulo = sem filtro).
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
   ORDER BY c.o_score DESC, v.preco_minor ASC NULLS LAST, v.sku
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
    `kamba_agr.tls.idx`), e nao diz respeito ao cliente.

    O `tenant` so serve para abrir a transaccao (`tenant_guard.tx`), que recusa
    `None`, vazio e o que nao for UUID antes de tocar na base. Uma pergunta que
    normalizada fique vazia devolve vazio sem consulta: o `websearch_to_tsquery`
    de nada e um aviso, nao uma pesquisa. O `tecto_ms` poe o `statement_timeout`
    **do lado do servidor**, local a transaccao: um tecto so no cliente deixava
    a consulta a correr na base depois de o turno desistir dela.
    """
    if isinstance(max_preco_minor, bool) or (
        max_preco_minor is not None and not isinstance(max_preco_minor, int)
    ):
        raise TypeError("max_preco_minor e unidade menor inteira (dicionario §2)")
    pergunta = consulta(texto)
    with tx(conexao, tenant) as cursor:
        if not pergunta.q_norm:
            return ()
        if tecto_ms is not None:
            cursor.execute(SQL_TECTO, (str(int(tecto_ms)),))
        cursor.execute(SQL_LIMIAR, (str(limiar),))
        cursor.execute(
            SQL_RESPOSTA,
            (
                pergunta.q_norm,
                pergunta.q_or,
                _vector(qvec),
                max_preco_minor,
                max_preco_minor,
            ),
        )
        linhas = cursor.fetchall()
    return tuple((_linha(linha), _score(linha)) for linha in linhas)


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

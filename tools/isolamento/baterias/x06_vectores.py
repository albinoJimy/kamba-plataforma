"""X-06: os vectores do indice (KAM-061, `docs/tecnica/08` §3.7).

O modo de falha que esta bateria existe para apanhar e o do `docs/tecnica/05`
§7.1: com um indice aproximado, o filtro por tenant aplica-se **depois** dos
vizinhos, e a pesquisa vectorial devolve o que o indice achou mais perto — de
qualquer loja. O Piloto nao tem indice ANN (PROP-IDX-1), e o criterio 5 do
KAM-061 mede-o; esta bateria mede o que tem de continuar verdade no dia em que
houver um: **o ramo semantico so ve vectores do tenant do contexto.**

Tres perguntas, todas como `kamba_app` e pela funcao que a aplicacao chama
(`idx.candidatos`), e nao por um `SELECT` a tabela — o X-03 ja faz esse:

1. com o contexto de A e um vector igual ao de B, nenhum canario de B sai, e o
   de A sai **pelo ramo semantico** (`o_rk_sem` nao nulo) — a sonda positiva;
2. com o contexto de A e o parametro `p_tenant` de B, zero linhas: o parametro
   nao contorna o contexto;
3. sem contexto, zero linhas.

O vector das sementes e **o mesmo nos dois tenants** (`sementes._VECTOR`): o
documento de B esta a distancia zero da pergunta, que e a forma mais hostil — e
a que um ANN com filtro posterior devolveria primeiro.
"""

from __future__ import annotations

from ..casos import registar_caso

#: O mesmo vector das sementes do `idx.search_doc` (`db/tests_isolamento/sementes.py`).
VECTOR = "[" + ",".join(["1"] + ["0"] * 1023) + "]"

_CANDIDATOS = (
    "SELECT o_product_ref, o_rk_sem "
    "  FROM idx.candidatos(%s, 'x', 'x', %s::halfvec, 1000)"
)

TABELA = ("idx", "search_doc")


def _x06(ctx) -> list[str]:  # noqa: ANN001
    if ctx.cursor_de is None:
        return ["X-06: o contexto nao traz cursores. Num gate, saltar e falhar."]
    achados: list[str] = []

    cursor = ctx.cursor_de("app", ctx.a.id)
    cursor.execute(_CANDIDATOS, (ctx.a.id, VECTOR))
    linhas = [tuple(linha) for linha in cursor.fetchall()]
    canario_de_a = str(ctx.a.canarios[TABELA])
    if not any(str(ref) == canario_de_a and rk is not None for ref, rk in linhas):
        achados.append(
            "X-06 sonda positiva: com o contexto de A, o ramo semantico nao "
            "devolveu o documento de A. A afirmacao de «nenhum vector de B» seria "
            "verde por o ramo estar vazio."
        )
    achados.extend(f"X-06 idx.candidatos: {fuga}" for fuga in ctx.oraculo.varrer("corpo", linhas))

    cursor = ctx.cursor_de("app", ctx.a.id)
    cursor.execute(_CANDIDATOS, (ctx.b.id, VECTOR))
    quantas = len(cursor.fetchall())
    if quantas:
        achados.append(
            f"X-06 parametro: com o contexto de A e `p_tenant` de B, a funcao "
            f"devolveu {quantas} linha(s). O tenant da pesquisa tem de vir do "
            "contexto; o parametro nao o pode contornar."
        )

    cursor = ctx.cursor_de("app")
    cursor.execute(_CANDIDATOS, (ctx.a.id, VECTOR))
    quantas = len(cursor.fetchall())
    if quantas:
        achados.append(
            f"X-06 sem contexto: a funcao devolveu {quantas} linha(s). Sem "
            "`app.tenant_id` a pesquisa devolve zero (criterio 3 do KAM-061)."
        )
    return achados


registar_caso(
    id="X-06/vectores",
    bateria="X-06",
    camada="rls",
    fn=_x06,
    precisa="postgres",
    origens=("corpo",),
)

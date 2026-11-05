"""X-03, X-04 e X-05 — a camada da base, registada no *harness*.

Estas tres baterias **ja existiam** quando o KAM-066 comecou: o KAM-004 e os
treze tickets que o alargaram puseram em `db/tests_isolamento/` 79 ensaios que
correm no *gate* 6, parametrizados sobre as tabelas que o catalogo descobre.
Este modulo nao as reescreve — registra-as.

## Porque e que registar vale a pena, se os ensaios ja correm

Por duas razoes, e nenhuma e cosmetica:

1. **O relatorio do *harness* passa a dizer a verdade.** Um relatorio que
   mostrasse X-01, X-02, C-01 e P-01 e nada da base dava a entender que o
   isolamento da base nao esta coberto — e a proxima pessoa a ler o relatorio
   tirava a conclusao errada sobre onde ha lacunas.
2. **O `fn` re-corre as verificacoes de catalogo**, que sao funcoes puras sobre
   o `pg_class` e levam milissegundos. Nao e duplicacao do ensaio: e o
   *harness* a nao confiar que outra suite correu. A regra da casa e que um
   agente produz evidencia, nao verdade — e vale para uma suite a confiar
   noutra.

O que **nao** se faz aqui e repetir as 79 afirmacoes. O X-03 e o X-04 ficam com
uma travessia por tabela — «A ve as suas e nao ve as de B», «sem contexto, zero
linhas» — que e a forma mais curta das duas baterias; as variantes (simetria,
procura por valor, contexto que nao e UUID, escrita cruzada, o dono das
tabelas) estao em `db/tests_isolamento/test_x03_x04_isolamento.py` e e la que
devem ficar.

`enumeravel` e vazio nas tres: elas nao cobrem rotas, tools, *jobs* nem
consumidores — cobrem **tabelas**, que a enumeracao nao enumera porque o
catalogo do PostgreSQL ja e a enumeracao delas (e falha se uma tabela com
`tenant_id` nao tiver receita de semente).
"""

from __future__ import annotations

from ..casos import registar_caso


def _x03(ctx) -> list[str]:  # noqa: ANN001
    """Com o contexto de A, nenhuma tabela devolve o canario de B."""
    if ctx.cursor_de is None:
        return ["X-03: o contexto nao traz cursores. Num gate, saltar e falhar."]
    achados: list[str] = []
    for schema, tabela, coluna, receita in ctx.tabelas:
        if not getattr(receita, "leitura_do_papel", True):
            continue
        cursor = ctx.cursor_de(receita.papel, ctx.a.id)
        cursor.execute(f"SELECT * FROM {schema}.{tabela}")
        linhas = [tuple(linha) for linha in cursor.fetchall()]
        if not linhas:
            achados.append(
                f"X-03 {schema}.{tabela}: A nao ve as suas proprias linhas. "
                "A afirmacao de «zero canarios de B» seria verde por a tabela "
                "estar vazia para A."
            )
            continue
        achados.extend(
            f"X-03 {schema}.{tabela}: {fuga}"
            for fuga in ctx.oraculo.varrer("corpo", linhas)
        )
        cursor.execute(
            f"SELECT count(*) FROM {schema}.{tabela} WHERE {coluna} = %s",
            (ctx.b.id,),
        )
        quantas = cursor.fetchone()[0]
        if quantas:
            achados.append(
                f"X-03 {schema}.{tabela}: a contagem das linhas de B com o "
                f"contexto de A deu {quantas} e nao zero."
            )
    return achados


def _x04(ctx) -> list[str]:  # noqa: ANN001
    """Sem `SET LOCAL`, cada tabela devolve zero linhas. A falha fechada."""
    if ctx.cursor_de is None:
        return ["X-04: o contexto nao traz cursores. Num gate, saltar e falhar."]
    achados: list[str] = []
    for schema, tabela, _, receita in ctx.tabelas:
        if not getattr(receita, "leitura_do_papel", True):
            continue
        cursor = ctx.cursor_de(receita.papel)
        cursor.execute(f"SELECT count(*) FROM {schema}.{tabela}")
        quantas = cursor.fetchone()[0]
        if quantas:
            achados.append(
                f"X-04 {schema}.{tabela}: sem contexto de tenant a tabela "
                f"devolveu {quantas} linha(s). A politica le "
                "`NULLIF(current_setting('app.tenant_id', true), '')::uuid`, "
                "que sem contexto e nulo e torna o predicado falso: uma linha "
                "aqui quer dizer que a tabela nao tem a politica, ou que o "
                "papel a contorna."
            )
    return achados


def _x05(ctx) -> list[str]:  # noqa: ANN001
    """O catalogo: RLS `FORCE`, `NOBYPASSRLS`, `SECURITY DEFINER`, vistas."""
    if ctx.cursores is None:
        return ["X-05: o contexto nao traz cursores. Num gate, saltar e falhar."]
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    raiz = Path(__file__).resolve().parents[3]
    if str(raiz / "db") not in sys.path:
        sys.path.insert(0, str(raiz / "db"))
    from tests_isolamento import catalogo  # noqa: PLC0415

    cursor = ctx.cursores["batch"]
    achados: list[str] = []
    achados += [f"X-05 (colunas): {p}" for p in catalogo.verificar_colunas_de_tenant(cursor)]
    achados += [
        f"X-05 (RLS): {p}"
        for p in catalogo.verificar_rls(cursor, catalogo.excepcoes_rls())
    ]
    achados += [f"X-05 (particoes): {p}" for p in catalogo.verificar_particoes(cursor)]
    achados += [
        f"X-05 (SECURITY DEFINER): {p}"
        for p in catalogo.verificar_security_definer(cursor, catalogo.funcoes_permitidas())
    ]
    achados += [f"X-05 (vistas): {p}" for p in catalogo.verificar_vistas(cursor)]

    # `kamba_app` e `NOBYPASSRLS`. E a condicao de que todas as outras
    # dependem: um papel com `BYPASSRLS` torna cada politica decorativa.
    cursor.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'kamba_app'")
    linha = cursor.fetchone()
    if linha is None:
        achados.append("X-05: o papel `kamba_app` nao existe.")
    elif linha[0]:
        achados.append(
            "X-05: `kamba_app` tem BYPASSRLS. Com ele, toda a RLS deste schema "
            "e decorativa e as outras baterias ficam verdes sem medir nada."
        )

    # A sonda positiva do proprio verificador: um defeito inventado tem de ser
    # nomeado. Sem isto, `verificar_rls` podia devolver sempre `[]`.
    achados += _rls_morde(ctx, catalogo)
    return achados


def _rls_morde(ctx, catalogo) -> list[str]:  # noqa: ANN001
    """Cria uma tabela com `tenant_id` sem RLS e exige que o X-05 a nomeie.

    E o `RLS-CONTROLO` desta bateria, pela ideia do `spikes/medusa-d3/iso.py`:
    uma afirmacao de conformidade so vale se o verificador souber dizer «esta
    mal», e quatro afirmacoes de «zero problemas» ficam verdes com um
    `verificar_rls` que devolva sempre `[]`.

    **Numa ligacao propria, que nunca confirma.** Os cursores de semente da
    suite estao em *autocommit* — tem de estar, para que os casos vejam as
    linhas noutras ligacoes — e em *autocommit* um `SAVEPOINT` rebenta com
    `25P01`: nao ha transaccao para o receber. Pior: um `CREATE TABLE` em
    *autocommit* fica **confirmado**, e DDL confirmado numa limpeza repara o
    esquema na base viva e esconde regressoes de tudo o que corre a seguir —
    defeito que a revisao adversarial desta casa ja apanhou uma vez. Por isso a
    tabela nasce numa transaccao de uma ligacao nova, e morre com o `ROLLBACK`.

    O papel e o `migrator`: e ele o dono do schema `platform`, e o unico que
    pode criar ali uma tabela.
    """
    if ctx.ligar is None:
        return [
            "X-05 (controlo): o contexto nao traz `ligar`, e a sonda positiva "
            "precisa de uma ligacao propria (ver a docstring). Num gate, "
            "saltar e falhar."
        ]
    nome = "platform.controlo_do_x05"
    conexao = ctx.ligar("migrator")
    try:
        cursor = conexao.cursor()
        cursor.execute(f"CREATE TABLE {nome} (tenant_id uuid NOT NULL)")
        problemas = catalogo.verificar_rls(cursor, catalogo.excepcoes_rls())
        if not any(nome in problema for problema in problemas):
            return [
                "X-05 (controlo): criou-se `platform.controlo_do_x05` com "
                "`tenant_id` e **sem** RLS, e o `verificar_rls` nao a nomeou. "
                "Enquanto isto falhar, o X-05 esta verde sem saber dizer «esta "
                "mal» — e e a unica bateria que apanha a tabela nova que "
                "alguem criou sem politica."
            ]
        return []
    finally:
        conexao.rollback()
        conexao.close()


registar_caso(
    id="X-03/tabelas",
    bateria="X-03",
    camada="rls",
    fn=_x03,
    precisa="postgres",
    origens=("corpo",),
)

registar_caso(
    id="X-04/sem-contexto",
    bateria="X-04",
    camada="rls",
    fn=_x04,
    precisa="postgres",
    origens=(),
)

registar_caso(
    id="X-05/catalogo",
    bateria="X-05",
    camada="catalogo",
    fn=_x05,
    precisa="postgres",
    origens=(),
)

"""O que o catalogo do PostgreSQL diz sobre o isolamento — funcoes, nao testes.

Estao aqui, e nao dentro dos testes, por uma razao: o criterio de aceitacao pede
uma **regressao** — «uma migracao de teste que cria tabela com `tenant_id` sem
RLS deve fazer X-05 falhar». Para isso a verificacao tem de ser uma funcao que
se chama duas vezes: uma sobre o schema real (tem de vir vazia) e outra depois
de se criar de proposito o defeito (tem de o nomear). Um teste que so afirmasse
«esta tudo bem» nao provava que sabe dizer «esta mal».
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Schemas que **nao** sao aplicacionais. Tudo o resto e — incluindo um schema
#: novo que alguem crie amanha, que assim entra na verificacao sem ninguem se
#: lembrar de o acrescentar. `public` **esta dentro**: so la vive a tabela de
#: versao do Alembic, mas `PUBLIC` tem `USAGE` e `EXECUTE` nele, e a revisao do
#: KAM-004 mostrou uma funcao `SECURITY DEFINER` e uma vista em `public` a lerem
#: todos os tenants sem que nenhuma verificacao as visse.
SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast")

#: Tabelas isoladas por uma coluna que nao se chama `tenant_id`. Lista fechada,
#: com razao: `tenants` **e** a tabela dos tenants, e a sua chave e `id`
#: (dicionario §3.2). A politica e `id = app.tenant_id`.
ISOLADAS_POR_OUTRA_COLUNA = {("platform", "tenants"): "id"}

_ADR = re.compile(r"^ADR-L?[0-9]{3}$")


class PoliticaInvalida(RuntimeError):
    """`ci/rls_exceptions.yaml` ou `ci/secdef_allowlist.yaml` malformado."""


def _ler_lista(caminho: Path, chave: str, identificador: str) -> dict[str, dict]:
    if not caminho.is_file():
        raise PoliticaInvalida(f"ficheiro em falta: {caminho}")
    dados = load_file(caminho)
    if dados.get("version") != 1:
        raise PoliticaInvalida(f"{caminho.name}: 'version' tem de ser 1")
    entradas: dict[str, dict] = {}
    for indice, entrada in enumerate(dados.get(chave) or [], start=1):
        faltam = [c for c in (identificador, "adr", "razao") if not entrada.get(c)]
        if faltam:
            raise PoliticaInvalida(
                f"{caminho.name}: entrada {indice} sem {', '.join(faltam)}"
            )
        if not _ADR.match(str(entrada["adr"])):
            raise PoliticaInvalida(
                f"{caminho.name}: entrada {indice} ({entrada[identificador]}): "
                f"`adr` tem de ser ADR-NNN ou ADR-LNNN, nao {entrada['adr']!r}. "
                "Uma excepcao ao isolamento e uma decisao de arquitectura, nao "
                "uma aprovacao datada."
            )
        if len(str(entrada["razao"])) < 30:
            raise PoliticaInvalida(
                f"{caminho.name}: entrada {indice} tem uma razao demasiado curta"
            )
        nome = str(entrada[identificador])
        if nome in entradas:
            raise PoliticaInvalida(f"{caminho.name}: {nome} repetido")
        entradas[nome] = entrada
    return entradas


def excepcoes_rls(raiz: Path = RAIZ) -> dict[str, dict]:
    return _ler_lista(raiz / "ci" / "rls_exceptions.yaml", "excepcoes", "tabela")


def funcoes_permitidas(raiz: Path = RAIZ) -> dict[str, dict]:
    return _ler_lista(raiz / "ci" / "secdef_allowlist.yaml", "funcoes", "funcao")


def _linhas(cursor, sql: str, parametros: tuple = ()) -> list[tuple]:
    cursor.execute(sql, parametros)
    return [tuple(linha) for linha in cursor.fetchall()]


def tabelas_isoladas(cursor) -> list[tuple[str, str, str]]:
    """(schema, tabela, coluna de isolamento) de tudo o que tem de ter RLS.

    Descobertas **pelo catalogo**: todas as tabelas com coluna `tenant_id` em
    schemas aplicacionais, mais as isoladas por outra coluna. E esta lista que
    parametriza a suite inteira — uma tabela nova entra sozinha em X-03, X-04 e
    X-05.

    **As particoes ficam de fora, e tem verificacao propria** (KAM-005). Uma
    particao e uma linha do catalogo com as colunas do pai, incluindo o
    `tenant_id`: entrava aqui sozinha, e com ela entravam as receitas de
    sementes, os canarios e a escrita cruzada — sobre uma relacao a que
    ninguem acede directamente. Pior: as particoes mensais do `events_log`
    nascem de um *job*, com nome que leva a data, e a lista mudava todos os
    meses. O que precisa de ser verdade sobre elas e outra coisa, e esta em
    `verificar_particoes`: ter a sua propria RLS **e** nao ter privilegio
    concedido a papel nenhum.
    """
    com_tenant = _linhas(
        cursor,
        "SELECT n.nspname, c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid "
        "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
        "AND a.attname = 'tenant_id' "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg!_%%' ESCAPE '!' "
        "ORDER BY 1, 2",
        (list(SCHEMAS_DE_SISTEMA),),
    )
    resultado = [(schema, tabela, "tenant_id") for schema, tabela in com_tenant]
    for (schema, tabela), coluna in sorted(ISOLADAS_POR_OUTRA_COLUNA.items()):
        resultado.append((schema, tabela, coluna))
    return sorted(resultado)


def verificar_colunas_de_tenant(cursor) -> list[str]:
    """Colunas com nome de tenant que **nao** se chamam `tenant_id`.

    A descoberta e pelo nome exacto: `tenant`, `tenantid`, `owner_tenant_id` ou
    `"Tenant_Id"` passavam ao lado de X-03, X-04 e X-05 sem ninguem dar por
    isso. Em vez de adivinhar que colunas isolam, recusa-se a escrita: o
    dicionario so conhece `tenant_id`. Sem lista de excepcoes — se um dia fizer
    falta uma, cria-se com a razao escrita.
    """
    return [
        f"{schema}.{tabela}.{coluna}: coluna com nome de tenant que nao e "
        "`tenant_id` — a suite de isolamento nao a ve. O nome canonico e `tenant_id`."
        for schema, tabela, coluna in _linhas(
            cursor,
            "SELECT n.nspname, c.relname, a.attname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid "
            "WHERE c.relkind IN ('r', 'p', 'f') AND a.attnum > 0 AND NOT a.attisdropped "
            "AND lower(a.attname) LIKE '%%tenant%%' AND a.attname <> 'tenant_id' "
            "AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg!_%%' ESCAPE '!' "
            "ORDER BY 1, 2, 3",
            (list(SCHEMAS_DE_SISTEMA),),
        )
    ]


def verificar_rls(cursor, excepcoes: dict[str, dict] | None = None) -> list[str]:
    """X-05. Devolve os problemas; lista vazia quer dizer conforme."""
    excepcoes = {} if excepcoes is None else excepcoes
    problemas: list[str] = []
    vistas: set[str] = set()

    for schema, tabela, _ in tabelas_isoladas(cursor):
        nome = f"{schema}.{tabela}"
        vistas.add(nome)
        estado = _linhas(
            cursor,
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            (schema, tabela),
        )
        if not estado:
            problemas.append(f"{nome}: declarada como isolada e nao existe")
            continue
        activa, forcada, politicas = estado[0]
        em_falta = []
        if not activa:
            em_falta.append("ENABLE ROW LEVEL SECURITY")
        if not forcada:
            em_falta.append("FORCE ROW LEVEL SECURITY")
        if not politicas:
            em_falta.append("pelo menos uma politica")
        if nome in excepcoes:
            if not em_falta:
                problemas.append(
                    f"{nome}: esta em ci/rls_exceptions.yaml e ja tem RLS "
                    "completa — a excepcao esta morta, retire-a"
                )
            continue
        if em_falta:
            problemas.append(
                f"{nome}: tem coluna de tenant e falta-lhe {', '.join(em_falta)}. "
                "Chame `rls.enable_tenant_rls` na revisao que a cria."
            )

    for nome in sorted(set(excepcoes) - vistas):
        problemas.append(
            f"{nome}: esta em ci/rls_exceptions.yaml e nao e uma tabela com "
            "coluna de tenant — a excepcao esta morta, retire-a"
        )
    return problemas


#: Papeis de servico. Uma particao nao pode ter privilegio concedido a nenhum.
PAPEIS_DE_SERVICO = (
    "kamba_app",
    "kamba_batch",
    "kamba_resolver",
    "kamba_identity",
    "public",
)


def particoes_de_isoladas(cursor) -> list[tuple[str, str, str]]:
    """(schema, particao, pai) de cada particao de uma tabela com `tenant_id`.

    `relkind IN ('r', 'p')` nos **dois** lados, e nao e detalhe: o `pg_inherits`
    liga tambem um indice particionado aos seus indices-filhos, e o
    `pg_attribute` tem linhas para as colunas de um indice. Sem o filtro, o
    indice `events_log_default_tenant_id_ocorrido_em_idx` aparecia como «uma
    particao com `tenant_id` sem RLS» e o X-05 falhava a pedir uma politica num
    indice (medido).
    """
    return _linhas(
        cursor,
        "SELECT n.nspname, c.relname, p.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_inherits i ON i.inhrelid = c.oid "
        "JOIN pg_class p ON p.oid = i.inhparent "
        "JOIN pg_attribute a ON a.attrelid = c.oid "
        "WHERE c.relispartition AND c.relkind IN ('r', 'p') "
        "AND p.relkind IN ('r', 'p') AND a.attname = 'tenant_id' "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg!_%%' ESCAPE '!' "
        "ORDER BY 1, 2",
        (list(SCHEMAS_DE_SISTEMA),),
    )


def verificar_particoes(cursor) -> list[str]:
    """X-05, segunda parte: as particoes de uma tabela isolada (KAM-005).

    **Mediu-se contra o PostgreSQL 18.6, e o resultado e o que torna esta
    verificacao necessaria:** ligar `ENABLE`/`FORCE ROW LEVEL SECURITY` e criar
    a politica no pai particionado **nao** protege quem le a particao
    directamente. Com o contexto do tenant A, um `SELECT` na particao devolveu
    as linhas dos **dois** tenants; sem contexto nenhum, tambem. O catalogo
    di-lo: a particao fica com `relrowsecurity = false` e zero politicas.

    Logo, duas exigencias, e as duas tem de valer:

    1. **A particao tem a sua propria RLS** — `ENABLE`, `FORCE` e ao menos uma
       politica. E o que a revisao faz (`rls.enable_tenant_rls`) e o que o
       `db/eventos_particoes.py` tem de fazer em cada particao que criar.
    2. **Nenhum papel de servico tem privilegio na particao.** Quem acede,
       acede pelo pai — e e no pai que o privilegio e a politica se avaliam.
       Uma particao nasce com `relacl` vazio (medido), pelo que isto e o estado
       por omissao; a verificacao esta aqui para que uma concessao directa, que
       abriria um caminho sem RLS do pai, nao passe calada.

    A primeira sozinha chegava para o isolamento; a segunda e defesa em
    profundidade, e e de graca.
    """
    problemas: list[str] = []
    for schema, particao, pai in particoes_de_isoladas(cursor):
        nome = f"{schema}.{particao}"
        activa, forcada, politicas = _linhas(
            cursor,
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            (schema, particao),
        )[0]
        em_falta = []
        if not activa:
            em_falta.append("ENABLE ROW LEVEL SECURITY")
        if not forcada:
            em_falta.append("FORCE ROW LEVEL SECURITY")
        if not politicas:
            em_falta.append("pelo menos uma politica")
        if em_falta:
            problemas.append(
                f"{nome}: e particao de {pai} e falta-lhe {', '.join(em_falta)}. "
                "A politica do pai NAO protege quem le a particao directamente "
                "(medido no PostgreSQL 18.6): chame `rls.enable_tenant_rls` "
                "tambem na particao."
            )
        for papel in PAPEIS_DE_SERVICO:
            tem = _linhas(
                cursor,
                "SELECT bool_or(has_table_privilege(%s, %s, p)) "
                "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS p",
                (papel, nome),
            )[0][0]
            if tem:
                problemas.append(
                    f"{nome}: {papel} tem privilegio **na particao**. Quem acede, "
                    f"acede por {pai}: um privilegio directo abre um caminho que "
                    "a politica do pai nao cobre."
                )
    return problemas


def verificar_security_definer(
    cursor, permitidas: dict[str, dict] | None = None
) -> list[str]:
    """Funcoes `SECURITY DEFINER` em schemas aplicacionais, fora da lista."""
    permitidas = {} if permitidas is None else permitidas
    encontradas = {
        f"{schema}.{nome}({argumentos})"
        for schema, nome, argumentos in _linhas(
            cursor,
            "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE p.prosecdef AND n.nspname <> ALL(%s) "
            "AND n.nspname NOT LIKE 'pg!_%%' ESCAPE '!'",
            (list(SCHEMAS_DE_SISTEMA),),
        )
    }
    problemas = [
        f"{funcao}: e SECURITY DEFINER e nao esta em ci/secdef_allowlist.yaml"
        for funcao in sorted(encontradas - set(permitidas))
    ]
    problemas += [
        f"{funcao}: esta em ci/secdef_allowlist.yaml e nao existe — retire-a"
        for funcao in sorted(set(permitidas) - encontradas)
    ]
    return problemas


def verificar_vistas(cursor) -> list[str]:
    """Vistas sem `security_invoker = true`. Para vistas nao ha lista de excepcoes.

    Uma vista corre, por omissao, com os privilegios do **dono** — e o dono das
    tabelas esta sujeito a RLS so por causa do `FORCE`. `security_invoker` poe a
    vista a correr como quem a consulta, que e o que a RLS pressupoe.
    """
    return [
        f"{schema}.{vista}: vista sem `security_invoker = true`"
        for schema, vista, opcoes in _linhas(
            cursor,
            "SELECT n.nspname, c.relname, COALESCE(c.reloptions, '{}') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('v', 'm') AND n.nspname <> ALL(%s) "
            "AND n.nspname NOT LIKE 'pg!_%%' ESCAPE '!' ORDER BY 1, 2",
            (list(SCHEMAS_DE_SISTEMA),),
        )
        if not any(
            str(opcao).replace(" ", "").lower() in ("security_invoker=true", "security_invoker=on")
            for opcao in opcoes
        )
    ]

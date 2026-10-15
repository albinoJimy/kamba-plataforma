"""Guarda de arranque do Piloto: so o Fluxo A em producao (ADR-011).

O ADR-011 fixa o fluxo dual como costura definitiva e **so o Fluxo A em
producao no Piloto**: o Fluxo B (numero agregador, tenant `platform`, vertical
`assistente`) fica diferido ate resposta escrita da Meta (D2). A costura existe
no schema — as colunas aceitam esses valores — pelo que o que impede o Fluxo B
de correr nao e o DDL: e esta verificacao, no arranque.

Com `KAMBA_FASE=piloto`, o arranque falha se existir uma linha com:

    platform.tenants.tipo             = 'platform'
    platform.tenant_channels.origem   = 'plataforma'
    platform.tenant_channels.vertical   fora de {vendedor, servicos}

A terceira e **mais larga** do que o criterio de aceitacao do KAM-003, que
nomeia so `vertical = 'assistente'`. De proposito: uma comparacao por igualdade
com `assistente` nao via `assistente_v2`, e o dicionario §3.2 ja diz que em
`tenant_channels.vertical` so cabem as verticais de atendimento. Lista de
permitidas em vez de lista de proibidas: o que nao se conhece nao arranca.

Tres formas de falhar fechado, e nenhuma e opcional:

**A variavel.** `piloto` e o unico valor que o canon define. Ausente, vazia ou
com outro valor, a guarda levanta — nao se desliga. O valor que um dia a
desligar e consequencia de D2 fechar; inventa-lo aqui seria fecha-la por
omissao.

**A visibilidade.** A guarda conta linhas, e uma contagem so vale se quem conta
vir todas. Com a RLS do KAM-004 (`FORCE`, politica por `app.tenant_id`), um
papel sem contexto de tenant ve **zero** linhas — e a guarda devolveria «pode
arrancar» sobre uma base cheia de Fluxo B. Por isso, antes de contar, prova que
ve tudo, por uma de tres vias:

    o papel contorna a RLS (`BYPASSRLS` ou superutilizador); ou
    nenhuma das duas tabelas tem RLS activa; ou
    o papel tem, nas duas tabelas, uma politica permissiva de leitura com
    `USING (true)`, e nao ha politica restritiva que a estreite.

A terceira via e a do `kamba_resolver` (KAM-004), e e **o papel com que a guarda
corre**: le so as colunas de que a pergunta precisa e nao contorna a RLS. Os
servicos nao recebem as credenciais do `kamba_batch` para arrancar. Como
`kamba_app`, a guarda levanta `GuardaCega` — que e o comportamento certo, e nao
um defeito a contornar.

**A leitura.** So le. Nao faz `commit` nem `rollback`.

O modulo so depende da biblioteca padrao: recebe uma ligacao DB-API ja aberta.
"""

from __future__ import annotations

import os

VARIAVEL = "KAMBA_FASE"
FASE_PILOTO = "piloto"

#: Verticais de atendimento, as unicas que cabem em `tenant_channels.vertical`
#: no Piloto (dicionario §3.2). Constantes deste modulo, nunca entrada de fora.
VERTICAIS_DO_PILOTO = ("vendedor", "servicos")

#: (o que se procura, consulta que conta as linhas). Lista fechada, sem
#: parametros.
VERIFICACOES: tuple[tuple[str, str], ...] = (
    (
        "platform.tenants.tipo = 'platform'",
        "SELECT count(*) FROM platform.tenants WHERE tipo = 'platform'",
    ),
    (
        "platform.tenant_channels.origem = 'plataforma'",
        "SELECT count(*) FROM platform.tenant_channels WHERE origem = 'plataforma'",
    ),
    (
        "platform.tenant_channels.vertical fora de {vendedor, servicos} "
        "(inclui 'assistente')",
        "SELECT count(*) FROM platform.tenant_channels "
        "WHERE vertical NOT IN ('vendedor', 'servicos')",
    ),
)

#: Verdadeiro quando o papel actual ve todas as linhas das duas tabelas. Tres
#: vias, e basta uma:
#:
#:   1. contorna a RLS (ou e superutilizador);
#:   2. nenhuma das duas tabelas a tem activa;
#:   3. tem, **em cada uma das duas**, uma politica permissiva de leitura total
#:      (`SELECT` ou `ALL`, `USING (true)`), **e** nenhuma politica restritiva
#:      lhe estreita a leitura.
#:
#: Na terceira via so conta a restritiva que **se aplica a leitura deste papel**:
#: comando `SELECT` ou `ALL`, dirigida a `PUBLIC` ou a um papel de que o actual
#: e membro. Uma restritiva de escrita, ou para outro papel, nao tira linhas a
#: ninguem que leia — e contar com ela cegava a guarda sem razao, que e o
#: caminho por que alguem acaba a desliga-la (achado 4 da revisao do KAM-004).
CONSULTA_DE_VISIBILIDADE = (
    "SELECT COALESCE((SELECT rolbypassrls OR rolsuper FROM pg_roles "
    "                  WHERE rolname = current_user), false) "
    "    OR NOT EXISTS (SELECT 1 FROM pg_class c "
    "                     JOIN pg_namespace n ON n.oid = c.relnamespace "
    "                    WHERE n.nspname = 'platform' "
    "                      AND c.relname IN ('tenants', 'tenant_channels') "
    "                      AND c.relrowsecurity) "
    "    OR ((SELECT count(DISTINCT tablename) FROM pg_policies "
    "          WHERE schemaname = 'platform' "
    "            AND tablename IN ('tenants', 'tenant_channels') "
    "            AND permissive = 'PERMISSIVE' AND cmd IN ('SELECT', 'ALL') "
    "            AND qual = 'true' AND current_user = ANY(roles)) = 2 "
    "        AND NOT EXISTS (SELECT 1 FROM pg_policy p "
    "                          JOIN pg_class c ON c.oid = p.polrelid "
    "                          JOIN pg_namespace n ON n.oid = c.relnamespace "
    "                         WHERE n.nspname = 'platform' "
    "                           AND c.relname IN ('tenants', 'tenant_channels') "
    "                           AND NOT p.polpermissive "
    "                           AND p.polcmd IN ('r', '*') "
    "                           AND (0 = ANY(p.polroles) "
    "                                OR EXISTS (SELECT 1 FROM unnest(p.polroles) AS papel(oid) "
    "                                            WHERE papel.oid <> 0 "
    "                                              AND pg_has_role(current_user, papel.oid, 'MEMBER')))))"
)


class FaseNaoDefinida(RuntimeError):
    """`KAMBA_FASE` esta ausente ou tem um valor que o canon nao define."""


class GuardaCega(RuntimeError):
    """O papel desta ligacao pode nao ver todas as linhas: a contagem nao vale."""


class FluxoBNoPiloto(RuntimeError):
    """Ha dados de Fluxo B numa base que corre em fase de Piloto."""


def verificar_arranque(conexao, ambiente=None) -> None:
    """Levanta se o servico nao pode arrancar. Nao devolve nada quando pode."""
    ambiente = os.environ if ambiente is None else ambiente
    fase = ambiente.get(VARIAVEL, "")
    if fase != FASE_PILOTO:
        raise FaseNaoDefinida(
            f"{VARIAVEL} tem de ser '{FASE_PILOTO}' (encontrado: "
            f"{fase!r}). E o unico valor que o canon define; um valor ausente "
            "ou desconhecido nao desliga a guarda do ADR-011."
        )

    encontrados: list[str] = []
    cursor = conexao.cursor()
    try:
        cursor.execute(CONSULTA_DE_VISIBILIDADE)
        if not cursor.fetchone()[0]:
            raise GuardaCega(
                "a guarda do ADR-011 nao consegue provar que ve todas as linhas: "
                "ha row-level security activa em `platform.tenants` ou em "
                "`platform.tenant_channels` e o papel desta ligacao nao a "
                "contorna nem tem politica de leitura total. Uma contagem de zero "
                "aqui nao significa que nao ha Fluxo B. A guarda corre como "
                "`kamba_resolver`, nao como `kamba_app`."
            )
        for descricao, consulta in VERIFICACOES:
            cursor.execute(consulta)
            quantas = cursor.fetchone()[0]
            if quantas:
                encontrados.append(f"{quantas} linha(s) com {descricao}")
    finally:
        cursor.close()

    if encontrados:
        raise FluxoBNoPiloto(
            "o arranque foi recusado: ha dados de Fluxo B e a fase e "
            f"'{FASE_PILOTO}' (ADR-011: so o Fluxo A em producao no Piloto). "
            + "; ".join(encontrados)
            + "."
        )

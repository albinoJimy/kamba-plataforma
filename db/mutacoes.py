"""Prova por mutacao dos gates verificados por suite, uma alteracao por execucao.

    python db/mutacoes.py [python] [filtro] [--fatia i/n]

Comecou nos gates de base de dados (6 e 8) e e ainda ai que esta a maior parte
da lista; desde o KAM-131 corre tambem as duas baterias do **gate 9**, que nao
levantam base de dados nenhuma (`SUITES_DE_TOOLS`).

O primeiro argumento e o Python que tem as dependencias das migracoes (por
omissao, o que corre este ficheiro). O segundo filtra: o nome de uma suite
(`tests`, `tests_identidade`, `tests_isolamento`, `gate9`, `gate9_ci`), o nome
exacto de uma mutacao, ou um **excerto** do nome (`guarda:`, `resolvedor`,
`downgrade da 0002`, `identidade:`, `KAM-131`), sensivel a maiusculas.

As mutacoes de `tests_identidade` (KAM-008) alteram o modulo TypeScript de
`packages/core-ts`, que a copia passa a levar. Os `node_modules` **nao** vao na
copia: a suite vai busca-los a este repositorio (`KAMBA_RAIZ_NODE_MODULES`), pelo
que e preciso te-los instalados aqui (`pnpm install --frozen-lockfile`).

**Quando basta o filtro, e quando nao.** Quem so **acrescenta** mutacoes e
testes corre as novas. A lista inteira corre-se sempre que o diff toque num
teste que ja la estava **ou num ficheiro que alguma mutacao altera** (as
revisoes, `rls.py`, `bootstrap.py`, `fluxo_piloto.py`, os *helpers*, o
catalogo): uma mutacao antiga deixa de valer quando o codigo mutado muda.

    python db/mutacoes.py --aplicaveis

confirma, sem Docker e em segundos, que o texto de **todas** as mutacoes ainda
existe exactamente uma vez no ficheiro alvo. Corre-se sempre, mesmo quando se
filtra: e o que apanha uma mutacao antiga que deixou de se aplicar.

As mutacoes correm **em paralelo** — cada uma levanta o seu proprio PostgreSQL
descartavel, numa porta escolhida pelo Docker, pelo que nao se pisam. O numero
de execucoes simultaneas vem de `KAMBA_MUTACOES_PARALELO` (por omissao 8; `1`
repoe a execucao em serie). A ordem do relatorio e a da lista, nao a de chegada.

Paralelismo tem um preco, e esta pago: com a maquina a esgotar ligacoes ou a
esperar por um trinco, a suite falha por **carga** e nao por a mutacao ter sido
apanhada. Uma falha dessas contava como «apanhada» e dava a prova por feita sem
nenhum teste ter mordido. `SINAIS_DE_CARGA` nomeia-as, e cada uma conta como
`PROVA INVALIDA` — que faz o corredor sair diferente de zero, como uma
sobrevivente. Subir o paralelismo nunca pode tornar a prova mais facil.

`--fatia i/n` corre so a i-esima de n fatias da lista escolhida. E o que torna a
prova completa viavel fora desta maquina: a tarefa nocturna do GitHub
(`.github/workflows/mutacoes.yaml`) reparte a lista por varios *runners*, cada
um com a sua fatia, em vez de uma execucao de horas num so. Uma fatia vazia e
erro, nao uma fatia limpa.

Um teste que passa nao prova que morde. Isto prova: copia `db/` e
`libs/py-core/` para um directorio temporario, aplica **uma** alteracao
deliberadamente errada, corre o gate 8 nessa copia e exige que ele falhe. O
repositorio nao e tocado.

Nao faz parte do gate: e uma execucao da suite por mutacao. Corre-se
quando se mexe nos testes do gate 8 ou na revisao, e o resultado regista-se no
bloco do ticket. Uma mutacao que **sobreviva** e um teste em falta — e foi
assim que esta lista nasceu: a revisao adversarial do KAM-003 mostrou cinco
alteracoes que deixavam os 75 testes de entao verdes (`GRANT kamba_batch TO
kamba_app`, `ON DELETE CASCADE`, `NOT NULL` retirado, privilegios por omissao,
uma coluna de contacto em claro). Estao todas aqui, e sao todas apanhadas.

Uma mutacao cujo texto ja nao exista no ficheiro reporta `MUTACAO NAO
APLICAVEL` e conta como falha: uma lista de mutacoes que deixou de se aplicar e
uma prova que deixou de provar.
"""
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
#: O Python que corre o gate na copia. `main()` substitui-o pelo do argumento.
PY = sys.executable
REV = "db/migrations/versions/0001_schema_platform.py"
GUARDA = "libs/py-core/src/kamba_core/fluxo_piloto.py"
BOOT = "db/bootstrap.py"
RLS = "db/rls.py"
REV2 = "db/migrations/versions/0002_rls_por_tenant.py"
GUARD_PY = "libs/py-core/src/kamba_core/tenant_guard/__init__.py"
CATALOGO = "db/tests_isolamento/catalogo.py"
ISOLAMENTO = "tests_isolamento"
REV3 = "db/migrations/versions/0003_identidade_de_contacto.py"
IDENTIDADE = "tests_identidade"
ID_CHAVES = "packages/core-ts/src/identity/chaves.ts"
ID_CRIPTO = "packages/core-ts/src/identity/cripto.ts"
ID_SQL = "packages/core-ts/src/identity/consultas.ts"
ID_SERVICO = "packages/core-ts/src/identity/contactos.ts"
ID_SUITE = "db/tests_identidade/test_modulo_de_identidade.py"
# ------------------------------------------------------------------- KAM-131
HIST = "tools/scan_secrets/historia.py"
SEC_CLI = "tools/scan_secrets/cli.py"
CI_YAML = ".github/workflows/ci.yaml"
MAKEFILE = "Makefile"
GATE9 = "gate9"
GATE9_CI = "gate9_ci"

#: As baterias de `tools/` que esta prova sabe correr: `(pacote, padrao)`.
#: Nao levantam base de dados nenhuma — o gate 9 nao tem base de dados — e por
#: isso correm em segundos.
#:
#: Corre-se o ficheiro de testes do ticket e nao a bateria inteira do pacote: as
#: outras baterias de `tools/` afirmam coisas sobre o **repositorio** (a arvore
#: seguida pelo git, a estrutura de pastas) que a copia nao e, e uma linha de
#: base vermelha nao prova nada.
SUITES_DE_TOOLS = {
    GATE9: ("scan_secrets", "test_historia.py"),
    GATE9_CI: ("lint_arch", "test_ci_gate9.py"),
}
#: O leitor de YAML (KAM-136). As duas suites leem por ele as listas de
#: excepcoes de `ci/` e o limiar do estrato `critico`.
KYAML = "tools/kamba_yaml.py"

MUTACOES = [
    ("estado a mais no CHECK de tenants", REV,
     "('onboarding','ativo','restrito','suspenso','encerrado')",
     "('onboarding','ativo','restrito','suspenso','encerrado','pausado')"),
    ("UNIQUE de phone_number_id retirado", REV,
     "CONSTRAINT tenant_channels_phone_number_id_uq UNIQUE\n", "\n"),
    ("ordem do indice trocada", REV,
     "ON platform.tenant_channels (tenant_id, estado)",
     "ON platform.tenant_channels (estado, tenant_id)"),
    ("coluna _enc em text", REV,
     "contacto_negocio_enc     bytea", "contacto_negocio_enc     text"),
    ("timestamp sem fuso", REV,
     "verificado_at            timestamptz,", "verificado_at            timestamp,"),
    ("NOT NULL retirado de origem", REV,
     "origem                  text NOT NULL DEFAULT 'pme'",
     "origem                  text DEFAULT 'pme'"),
    ("omissao de origem = plataforma", REV,
     "origem                  text NOT NULL DEFAULT 'pme'",
     "origem                  text NOT NULL DEFAULT 'plataforma'"),
    ("ON DELETE CASCADE na FK do canal", REV,
     "REFERENCES platform.tenants (id),\n          waba_id",
     "REFERENCES platform.tenants (id) ON DELETE CASCADE,\n          waba_id"),
    ("coluna de contacto em claro acrescentada", REV,
     "          zona                     text,",
     "          zona                     text,\n          contacto_dono            text,"),
    ("CHECK de forma da vertical retirado", REV,
     "CHECK (vertical ~ '^[a-z][a-z0-9_]*$'),", "CHECK (true),"),
    ("DELETE em tenants dado a kamba_app", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT DELETE ON platform.tenants TO kamba_app")'),
    ("UPDATE de tipo dado a kamba_app", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT UPDATE (tipo) ON platform.tenants TO kamba_app")'),
    ("privilegios por omissao", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL ON TABLES TO kamba_app")'),
    ("SELECT em tenants dado a PUBLIC", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT SELECT ON platform.tenants TO PUBLIC")'),
    ("bootstrap: kamba_app membro de kamba_batch", BOOT,
     "        _revogar_pertencas(cursor, feito)\n",
     '        cursor.execute("GRANT kamba_batch TO kamba_app")\n'),
    ("bootstrap: TEMPORARY deixado ao PUBLIC", BOOT,
     '"REVOKE TEMPORARY, CONNECT ON DATABASE %I FROM PUBLIC"',
     '"REVOKE CONNECT ON DATABASE %I FROM PUBLIC"'),
    ("bootstrap: kamba_app com BYPASSRLS", BOOT,
     '"kamba_app": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_app": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"'),
    ("guarda: vertical por igualdade com assistente", GUARDA,
     "\"WHERE vertical NOT IN ('vendedor', 'servicos')\"",
     "\"WHERE vertical = 'assistente'\""),
    ("guarda: sem prova de visibilidade", GUARDA,
     "        if not cursor.fetchone()[0]:", "        if cursor.fetchone() is None:"),
    ("guarda: condicao da origem retirada", GUARDA,
     "\"SELECT count(*) FROM platform.tenant_channels WHERE origem = 'plataforma'\"",
     "\"SELECT count(*) FROM platform.tenant_channels WHERE origem = 'nunca'\""),
    # ---------------------------------------------------------------- KAM-004
    # Cada uma tem de ser apanhada pela suite de isolamento (gate 6).
    ("RLS: politica sem WITH CHECK", RLS,
     'f"USING ({predicado(coluna)}) WITH CHECK ({predicado(coluna)})"',
     'f"USING ({predicado(coluna)})"', ISOLAMENTO),
    ("RLS: ENABLE sem FORCE", RLS,
     '    op.execute(f"ALTER TABLE {alvo} FORCE ROW LEVEL SECURITY")\n    op.execute(\n        f"CREATE POLICY',
     '    op.execute(\n        f"CREATE POLICY', ISOLAMENTO),
    ("RLS: predicado com OR true", RLS,
     """return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid\"""",
     """return f"({coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid OR true)\"""",
     ISOLAMENTO),
    ("RLS: sem contexto ve tudo (COALESCE)", RLS,
     """return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid\"""",
     """return f"{coluna} = COALESCE(NULLIF(current_setting('{VARIAVEL}', true), '')::uuid, {coluna})\"""",
     ISOLAMENTO),
    ("RLS: tenants fica de fora", REV2,
     '    rls.enable_tenant_rls("tenants", coluna="id")\n', "", ISOLAMENTO),
    ("resolvedor: politica FOR ALL em vez de FOR SELECT", REV2,
     '"FOR SELECT TO kamba_resolver USING (true)"',
     '"FOR ALL TO kamba_resolver USING (true)"', ISOLAMENTO),
    ("resolvedor: mais uma coluna (token_ref)", REV2,
     '"id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",\n        "channel_mode",',
     '"id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",\n        "channel_mode", "token_ref",',
     ISOLAMENTO),
    ("resolvedor: politica TO PUBLIC", REV2,
     '"FOR SELECT TO kamba_resolver USING (true)"',
     '"FOR SELECT TO PUBLIC USING (true)"', ISOLAMENTO),
    ("helper: set_config de sessao (false)", GUARD_PY,
     """SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', %s, true)\"""",
     """SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', %s, false)\"""",
     ISOLAMENTO),
    ("catalogo: a descoberta ignora o schema platform", CATALOGO,
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast")',
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast", "platform")',
     ISOLAMENTO),
    # ------------------------------------------- KAM-004, revisao adversarial
    # As nove que **sobreviveram** a primeira versao dos testes (ANALISE-07).
    ("resolvedor: GRANT INSERT em tenants e tenant_channels (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenants, platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    ("resolvedor: GRANT INSERT em tenants e tenant_channels (gate 8)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenants, platform.tenant_channels TO kamba_resolver")\n'),
    ("resolvedor: GRANT INSERT so em tenant_channels (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    ("resolvedor: GRANT UPDATE (estado) sem politica (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT UPDATE (estado) ON platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    ("catalogo: a descoberta ignora tabelas particionadas", CATALOGO,
     "WHERE c.relkind IN ('r', 'p') AND a.attname = 'tenant_id'",
     "WHERE c.relkind IN ('r') AND a.attname = 'tenant_id'", ISOLAMENTO),
    ("catalogo: vistas materializadas fora da verificacao", CATALOGO,
     "WHERE c.relkind IN ('v', 'm')", "WHERE c.relkind IN ('v')", ISOLAMENTO),
    ("catalogo: public volta a ficar de fora", CATALOGO,
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast")',
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast", "public")',
     ISOLAMENTO),
    ("catalogo: so um nome de coluna alternativo conta", CATALOGO,
     "lower(a.attname) LIKE '%%tenant%%'", "a.attname = 'tenant'", ISOLAMENTO),
    ("guarda: basta politica de leitura numa das tabelas", GUARDA,
     "AND qual = 'true' AND current_user = ANY(roles)) = 2 ",
     "AND qual = 'true' AND current_user = ANY(roles)) >= 1 "),
    ("guarda: qualquer comando conta como leitura", GUARDA,
     "AND permissive = 'PERMISSIVE' AND cmd IN ('SELECT', 'ALL') ",
     "AND permissive = 'PERMISSIVE' "),
    ("guarda: qualquer predicado conta como leitura total", GUARDA,
     "AND qual = 'true' AND current_user = ANY(roles)) = 2 ",
     "AND current_user = ANY(roles)) = 2 "),
    ("guarda: restritiva so procurada em tenant_channels", GUARDA,
     '"' + " " * 27 + "AND c.relname IN ('tenants', 'tenant_channels')",
     '"' + " " * 27 + "AND c.relname IN ('tenant_channels')"),
    ("guarda: restritiva para PUBLIC nao conta", GUARDA,
     "AND (0 = ANY(p.polroles) ", "AND (false "),
    ("guarda: restritiva FOR ALL nao conta", GUARDA,
     "AND p.polcmd IN ('r', '*') ", "AND p.polcmd IN ('r') "),
    ("guarda: restritiva de escrita volta a cegar", GUARDA,
     "AND p.polcmd IN ('r', '*') ", "AND true "),
    ("downgrade da 0002: nao revoga os GRANT do resolvedor", REV2,
     '"FROM kamba_resolver"', '"FROM kamba_batch"'),
    ("downgrade da 0002: nao revoga o USAGE do resolvedor", REV2,
     'op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_resolver")', "pass"),
    ("downgrade da 0002: disable_tenant_rls deixa o FORCE", RLS,
     'op.execute(f"ALTER TABLE {alvo} NO FORCE ROW LEVEL SECURITY")', "pass"),
    # ---------------------------------------------------------------- KAM-008
    # A revisao 0003 e o papel `kamba_identity`: o que o **schema** garante.
    ("0003: SELECT em contact_endpoints dado a kamba_app", REV3,
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n',
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n'
     '    op.execute("GRANT SELECT ON platform.contact_endpoints TO kamba_app")\n'),
    ("0003: phone_hmac legivel por kamba_app", REV3,
     '"contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",\n)',
     '"contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",\n'
     '    "phone_hmac",\n)'),
    ("0003: kamba_batch le o cofre", REV3,
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n',
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n'
     '    op.execute("GRANT SELECT ON platform.contact_endpoints, platform.contact_deks TO kamba_batch")\n'),
    ("0003: UPDATE de tenant_id dado a kamba_identity", REV3,
     '"contacts": ("phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at"),',
     '"contacts": ("phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at", "tenant_id"),'),
    ("0003: DELETE em contacts dado a kamba_identity", REV3,
     '"GRANT DELETE ON platform.contact_endpoints TO kamba_identity"',
     '"GRANT DELETE ON platform.contact_endpoints, platform.contacts TO kamba_identity"'),
    ("0003: UNIQUE do bsuid sem tenant", REV3,
     "CONSTRAINT contact_endpoints_bsuid_uq UNIQUE (tenant_id, hmac_kid, bsuid_hmac),",
     "CONSTRAINT contact_endpoints_bsuid_uq UNIQUE (hmac_kid, bsuid_hmac),"),
    ("0003: coluna de BSUID em claro acrescentada", REV3,
     "          bsuid_enc     bytea,\n", "          bsuid_enc     bytea,\n          bsuid         text,\n"),
    ("0003: phone_enc em text", REV3,
     "          phone_enc     bytea,", "          phone_enc     text,"),
    ("0003: FK do dono sem o tenant", REV3,
     "          FOREIGN KEY (id, owner_contact_id)\n"
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n",
     "          FOREIGN KEY (owner_contact_id)\n"
     "          REFERENCES platform.contacts (contact_id)\n"),
    ("0003: FK do dono nao diferida", REV3,
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n"
     "          DEFERRABLE INITIALLY DEFERRED\n",
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n"),
    ("0003: FK do dono validada com o FORCE ligado", REV3,
     '    op.execute("ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY")\n', ""),
    ("0003: FORCE de tenants nao reposto (gate 8)", REV3,
     '    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")\n', ""),
    ("0003: FORCE de tenants nao reposto (gate 6)", REV3,
     '    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")\n', "",
     ISOLAMENTO),
    ("0003: contact_endpoints fica sem RLS", REV3,
     "    for tabela in TABELAS_DE_TENANT:\n        rls.enable_tenant_rls(tabela)\n",
     "    for tabela in TABELAS_DE_TENANT[:2]:\n        rls.enable_tenant_rls(tabela)\n",
     ISOLAMENTO),
    ("0003: downgrade sem copia logica", REV3,
     '    rls.disable_tenant_rls("contacts")\n\n    _copia_logica()\n',
     '    rls.disable_tenant_rls("contacts")\n'),
    ("0003: copia logica feita com a RLS ligada", REV3,
     '    rls.disable_tenant_rls("contact_endpoints")\n'
     '    rls.disable_tenant_rls("contact_deks")\n'
     '    rls.disable_tenant_rls("contacts")\n\n    _copia_logica()\n',
     '    _copia_logica()\n\n    rls.disable_tenant_rls("contact_endpoints")\n'
     '    rls.disable_tenant_rls("contact_deks")\n'
     '    rls.disable_tenant_rls("contacts")\n'),
    ("0003: copia logica escreve por cima", REV3,
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC"),
    ("0003: downgrade nao revoga o USAGE de kamba_identity", REV3,
     'op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_identity")', "pass"),
    ("0003: contacto apagado pode guardar o HMAC do telefone", REV3,
     "CHECK ((erased_at IS NULL AND merged_into IS NULL) OR phone_hmac IS NULL)",
     "CHECK (true)"),
    ("0003: telefone guardado sem finalidade nem prazo", REV3,
     "               AND finalidade IS NOT NULL AND expira_at IS NOT NULL)", "               )"),
    ("0003: duas versoes de chave actuais", REV3,
     "ON platform.hmac_key_versions (estado) WHERE estado = 'actual'",
     "ON platform.hmac_key_versions (kid) WHERE estado = 'actual'"),
    ("0003: DEK destruida que guarda o embrulho", REV3,
     "CHECK ((wrapped_dek IS NULL) = (destroyed_at IS NOT NULL))", "CHECK (true)"),
    ("0003: endpoint pode apontar para o contacto de outro tenant", REV3,
     "            FOREIGN KEY (tenant_id, contact_id)\n"
     "            REFERENCES platform.contacts (tenant_id, contact_id),\n"
     "          CONSTRAINT contact_endpoints_dek_fk",
     "            FOREIGN KEY (contact_id)\n"
     "            REFERENCES platform.contacts (contact_id),\n"
     "          CONSTRAINT contact_endpoints_dek_fk"),
    ("bootstrap: kamba_identity com BYPASSRLS (gate 8)", BOOT,
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"'),
    ("bootstrap: kamba_identity com BYPASSRLS (gate 6)", BOOT,
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"',
     ISOLAMENTO),
    # O modulo de identidade (TypeScript), contra a base: suite `tests_identidade`.
    ("identidade: HMAC de pesquisa sem o tenant", ID_CRIPTO,
     ".update(`${DOMINIO_DE_PESQUISA}\\0${tipo}\\0${tenant}\\0`, \"utf8\")",
     ".update(`${DOMINIO_DE_PESQUISA}\\0${tipo}\\0`, \"utf8\")", IDENTIDADE),
    ("identidade: contexto da cifra sem a DEK", ID_CRIPTO,
     "`${DOMINIO_DE_CIFRA}\\0${campo}\\0${tenant}\\0${dekId}`",
     "`${DOMINIO_DE_CIFRA}\\0${campo}\\0${tenant}`", IDENTIDADE),
    ("identidade: sujeito_ref com a mesma chave em todos os meses", ID_CHAVES,
     "const ref = `${REF_CHAVE_DE_EPOCA}/${epoca}`;",
     "const ref = `${REF_CHAVE_DE_EPOCA}/202610`;", IDENTIDADE),
    ("identidade: prod aceita o KeyProvider de ambiente", ID_CHAVES,
     'if (declarado === "prod" && chaves.deAmbiente) {', "if (false) {", IDENTIDADE),
    ("identidade: provedor de dev arranca em prod", ID_CHAVES,
     "if (chaves.ambiente !== declarado) {", "if (false) {", IDENTIDADE),
    ("identidade: pesquisa do BSUID so com a chave actual", ID_SERVICO,
     '        kids.anterior,\n'
     '        chaveAnterior === null ? null : hmacDePesquisa(chaveAnterior, tenant, "bsuid", bsuid),',
     "        null,\n        null,", IDENTIDADE),
    ("identidade: pesquisa do telefone so com a chave actual", ID_SERVICO,
     "        kids.anterior,\n        hmacAnteriorDoTelefone,\n      ]);",
     "        null,\n        null,\n      ]);", IDENTIDADE),
    ("identidade: eraseContact nao destroi a DEK", ID_SERVICO,
     "const deksDestruidas = await executar(cliente, SQL.DESTRUIR_DEKS, [tenant, alvo.id]);",
     "const deksDestruidas = 1;", IDENTIDADE),
    ("identidade: eraseContact nao apaga os endpoints", ID_SERVICO,
     "const endpointsApagados = await executar(cliente, SQL.APAGAR_ENDPOINTS, [tenant, alvo.id]);",
     "const endpointsApagados = 2;", IDENTIDADE),
    ("identidade: apagar um absorvido nao chega a quem o absorveu", ID_SERVICO,
     "      if (estado.mergedInto === null) return estado;\n      procurado = estado.mergedInto;",
     "      return estado;", IDENTIDADE),
    ("identidade: a fusao fica com o mais novo", ID_SERVICO,
     "if (diferenca !== 0) return diferenca < 0 ? [a, b] : [b, a];",
     "if (diferenca !== 0) return diferenca < 0 ? [b, a] : [a, b];", IDENTIDADE),
    ("identidade: numero reatribuido funde duas pessoas", ID_SERVICO,
     "      if (outraPessoa) {", "      if (outraPessoa && false) {", IDENTIDADE),
    ("identidade: a fusao nao chama os ganchos", ID_SERVICO,
     "    for (const gancho of this.#ganchos) {\n"
     "      await gancho({ cliente, tenantId: tenant, de: sai.id, para: fica.id });\n    }\n",
     "", IDENTIDADE),
    ("identidade: a fusao deixa as DEK no absorvido", ID_SERVICO,
     "    await executar(cliente, SQL.MOVER_DEKS, [tenant, sai.id, fica.id]);\n", "",
     IDENTIDADE),
    ("identidade: corridas nao se repetem", ID_SERVICO,
     "        if (!repetivel(erro)) throw erro;", "        throw erro;", IDENTIDADE),
    ("identidade: rekeyLookup marca a versao sem recalcular o HMAC", ID_SERVICO,
     '              hmacDePesquisa(chave, tenant, "bsuid", bsuid),\n              kid,',
     '              hmacDePesquisa(chave, tenant, "telefone", bsuid),\n              kid,',
     IDENTIDADE),
    ("identidade: rekeyLookup aceita uma versao que nao e a actual", ID_SERVICO,
     '    if (linha === undefined || linha.estado !== "actual") throw new KidNaoActualError(kid);',
     "    if (linha === undefined) throw new KidNaoActualError(kid);", IDENTIDADE),
    ("identidade: iniciarRotacao por cima de outra", ID_SERVICO,
     '        if (anterior !== undefined) throw new RotacaoEmCursoError(texto(anterior, "kid"));\n',
     "", IDENTIDADE),
    ("identidade: telefone guardado em claro", ID_SERVICO,
     '            cifrar(dek, telefone, contextoDaCifra(tenant, dekId, "phone_enc")),',
     '            Buffer.from(telefone, "utf8"),', IDENTIDADE),
    ("identidade: BSUID guardado em claro", ID_SERVICO,
     '            cifrar(dek, bsuid, contextoDaCifra(tenant, dekId, "bsuid_enc")),',
     '            Buffer.from(bsuid, "utf8"),', IDENTIDADE),
    ("identidade: trocar de numero deixa a cifra do antigo", ID_SERVICO,
     "        if (telefoneDoContacto !== null && !eOMesmoNumero) {\n"
     "          await executar(cliente, SQL.APAGAR_TELEFONES, [tenant, contacto]);\n        }\n",
     "", IDENTIDADE),
    # ----------------------------------- KAM-008, revisao adversarial (ANALISE-08)
    # As que **sobreviveram** a primeira versao dos testes, mais as dos defeitos
    # que as duas revisoes encontraram.
    ("identidade: versoes de chave lidas sem tranca (corrida com a rotacao)", ID_SQL,
     "export const KIDS_VIVOS = `${VERSOES_VIVAS} FOR SHARE`;",
     "export const KIDS_VIVOS = VERSOES_VIVAS;", IDENTIDADE),
    ("identidade: eraseContact destroi as DEK do tenant inteiro", ID_SQL,
     '"WHERE tenant_id = $1 AND contact_id = $2 AND destroyed_at IS NULL";',
     '"WHERE tenant_id = $1 AND $2::uuid IS NOT NULL AND destroyed_at IS NULL";', IDENTIDADE),
    ("identidade: eraseContact apaga os endpoints do tenant inteiro", ID_SQL,
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2";',
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND $2::uuid IS NOT NULL";',
     IDENTIDADE),
    ("identidade: a fusao move os endpoints do tenant inteiro", ID_SQL,
     '"UPDATE platform.contact_endpoints SET contact_id = $3 " +\n'
     '  "WHERE tenant_id = $1 AND contact_id = $2";',
     '"UPDATE platform.contact_endpoints SET contact_id = $3 " +\n'
     '  "WHERE tenant_id = $1 AND $2::uuid IS NOT NULL";', IDENTIDADE),
    ("identidade: a fusao nao larga o numero antigo de quem tem o BSUID", ID_SERVICO,
     "    if (a.phoneHmac !== null) await this.#tirarTelefone(cliente, tenant, a.id);\n", "",
     IDENTIDADE),
    ("identidade: rever o mesmo numero na janela apaga a cifra", ID_SERVICO,
     "        if (telefoneDoContacto !== null && !eOMesmoNumero) {",
     "        if (telefoneDoContacto !== null) {", IDENTIDADE),
    ("identidade: lerEndpoints serve telefones fora do prazo", ID_SQL,
     '  "AND (e.expira_at IS NULL OR e.expira_at > now()) " +\n', "", IDENTIDADE),
    ("canarios: a procura deixa de ver a forma hexadecimal do bytea", ID_SUITE,
     'canario.encode("ascii").hex().encode("ascii")',
     'canario.encode("ascii").hex().upper().encode("ascii")', IDENTIDADE),
    ("canarios: a procura deixa de ver a forma em texto", ID_SUITE,
     'return canario.encode("ascii"), canario.encode("ascii").hex().encode("ascii")',
     'return canario.encode("ascii").hex().encode("ascii"), canario.encode("ascii").hex().encode("ascii")',
     IDENTIDADE),
    ("0003: politica a mais que abre contacts a kamba_app (gate 6)", REV3,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_identity")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_identity")\n'
     '    op.execute("CREATE POLICY app_le_tudo ON platform.contacts FOR SELECT TO kamba_app USING (true)")\n',
     ISOLAMENTO),
    ("0003: downgrade deixa os donos de tenant a apontar para nada", REV3,
     '    op.execute(\n        "UPDATE platform.tenants SET owner_contact_id = NULL "\n'
     '        "WHERE owner_contact_id IS NOT NULL"\n    )\n', ""),
    ("0003: copia logica sem as versoes de chave", REV3,
     'TABELAS_COPIADAS = ("hmac_key_versions", "contacts", "contact_deks", "contact_endpoints")',
     'TABELAS_COPIADAS = ("contacts", "contact_deks", "contact_endpoints")'),
    ("0003: copia logica sem os donos de tenant", REV3,
     '    for identificador, dono in op.get_bind().exec_driver_sql(SQL_DONOS):\n'
     '        yield "tenants", {"id": _celula(identificador), "owner_contact_id": _celula(dono)}\n',
     ""),
    ("0003: downgrade le os donos com o FORCE ligado", REV3,
     '    op.execute(\n        "ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY"\n    )\n',
     ""),
    ("0003: downgrade deixa tenants sem FORCE", REV3,
     '    op.execute(\n        "ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY"\n    )\n',
     ""),
    ("identidade: instrucao sem filtro de tenant", ID_SQL,
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2";',
     '"DELETE FROM platform.contact_endpoints WHERE contact_id = $2 AND $1::uuid IS NOT NULL";',
     IDENTIDADE),
    # ---------------------------------------------------------------- KAM-131
    # A segunda passagem do gate 9: os blobs que o intervalo do PR acrescenta.
    # Cada uma tem de ser apanhada por `tools/scan_secrets/tests/test_historia.py`
    # (suite `gate9`) ou, as do `ci.yaml` e do `Makefile`, por
    # `tools/lint_arch/tests/test_ci_gate9.py` (suite `gate9_ci`) — que existe
    # porque **nao ha lint de workflows** neste repositorio e o gate 9 passou a
    # depender de tres linhas de YAML e de um `fetch-depth`.
    ("KAM-131 historia: varre a historia toda e nao o intervalo", HIST,
     '"--objects", f"{base}..{head}")', '"--objects", f"{head}")', GATE9),
    # Nao ha mutacao a `candidatos = set(pares) | set(atribuicao)`: depois do
    # `-c`, o conjunto da travessia por objectos e um subconjunto do da
    # atribuicao, pelo que a mutacao que o reduz a um dos dois **sobrevive** —
    # e por equivalencia, nao por falta de teste. Fica a uniao como ultima
    # linha, e `Resultado.sem_atribuicao` conta o que so um dos lados alcance.
    # Ver a ANALISE-14 §3.3.
    #
    # As duas evasoes que a revisao adversarial construiu (ANALISE-14, A1 e A2)
    # passavam ambas pelo `-c`: sem ele o `git log --raw` nao imprime sequer o
    # cabecalho de um merge.
    ("KAM-131 historia: o `git log` deixa de ver o que um merge introduz", HIST,
     '        "-c",\n        "--no-abbrev",', '        "--no-abbrev",', GATE9),
    ("KAM-131 historia: a deteccao de mudancas de nome volta a ligar", HIST,
     '        "--no-renames",\n', "", GATE9),
    # O criterio 6 tem de valer nos dois sentidos da ordem alfabetica: a
    # primeira versao desta lista so tinha `[-1:]`, e `[:1]` sobrevivia.
    ("KAM-131 historia: so o ultimo caminho do blob e confrontado", HIST,
     "for caminho, commit in sorted(de_texto[sha].items()):",
     "for caminho, commit in sorted(de_texto[sha].items())[-1:]:", GATE9),
    ("KAM-131 historia: so o primeiro caminho do blob e confrontado", HIST,
     "        for caminho, commit in sorted(de_texto[sha].items()):",
     "        for caminho, commit in sorted(de_texto[sha].items())[:1]:", GATE9),
    ("KAM-131 historia: clone raso deixa de ser recusado", HIST,
     '"--is-shallow-repository").strip() == "true":',
     '"--is-shallow-repository").strip() == "nunca":', GATE9),
    ("KAM-131 historia: um PR sem base passa a varrer so a arvore", HIST,
     '    "pull_request": None,\n',
     '    "pull_request": "sem base: varre-se so a arvore",\n', GATE9),
    ("KAM-131 historia: um SHA a zeros deixa de contar como ausente", HIST,
     'return not limpo or set(limpo) == {"0"}', "return not limpo", GATE9),
    ("KAM-131 historia: os binarios passam a ser os unicos varridos", HIST,
     "if Path(caminho).suffix.lower() not in BINARIOS",
     "if Path(caminho).suffix.lower() in BINARIOS", GATE9),
    ("KAM-131 historia: o relatorio deixa de dizer o commit", HIST,
     'return f"{curto} {self.achado}\\n    blob {self.blob[:12]}"',
     'return f"{self.achado}"', GATE9),
    ("KAM-131 historia: um commit que nao e SHA volta a ser truncado", HIST,
     'curto = self.commit[:12] if _SHA.fullmatch(self.commit) else self.commit',
     "curto = self.commit[:12]", GATE9),
    # A contabilidade do relatorio: afirmar cobertura que nao houve e o defeito
    # que o proprio `scanner.py` conta ter tido em `_fragmentos`.
    ("KAM-131 historia: um blob que nao e UTF-8 conta como varrido", HIST,
     "            nao_decifraveis += 1\n            continue\n",
     "            varridos += 1\n            continue\n", GATE9),
    ("KAM-131 historia: os binarios saltados deixam de se contar", HIST,
     "saltados_por_extensao=len(blobs) - len(a_ler),",
     "saltados_por_extensao=0,", GATE9),
    # O intervalo invertido: a evasao do YAML trocado (A3).
    ("KAM-131 historia: um intervalo de zero commits deixa de ser erro", HIST,
     "    if nome not in EXIGEM_COMMITS:\n        return\n", "    return\n", GATE9),
    ("KAM-131 cli: um achado na historia deixa de reprovar", SEC_CLI,
     '        return 1\n\n    print(f"scan_secrets: limpo — {resultado.onde}")',
     '        return 0\n\n    print(f"scan_secrets: limpo — {resultado.onde}")',
     GATE9),
    ("KAM-131 cli: um intervalo irresoluvel passa a dar passagem", SEC_CLI,
     "        return 2\n\n    if resultado.achados:",
     "        return 0\n\n    if resultado.achados:", GATE9),
    ("KAM-131 cli: o modo so-arvore passa a dizer-se satisfeito", SEC_CLI,
     "NAO CORRIDA", "satisfeita", GATE9),
    ("KAM-131 cli: o modo so-arvore deixa de avisar no resumo do job", SEC_CLI,
     '"::warning title=gate 9::a passagem da historia NAO CORREU "',
     '"a passagem da historia nao correu "', GATE9),
    ("KAM-131 cli: o intervalo vazio deixa de ser confrontado", SEC_CLI,
     "        exigir_commits(argumentos.evento, resultado.commits)\n", "", GATE9),
    ("KAM-131 ci: o checkout do gate 9 deixa de trazer a historia", CI_YAML,
     "          fetch-depth: 0", "          fetch-depth: 1", GATE9_CI),
    ("KAM-131 ci: a base do PR deixa de chegar ao gate 9", CI_YAML,
     "GATE9_BASE: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}",
     'GATE9_BASE: ""', GATE9_CI),
    # A troca que a revisao adversarial fez: as quatro assercoes de texto da
    # primeira versao continuavam todas a bater, e o gate passava a varrer um
    # intervalo invertido.
    ("KAM-131 ci: a base e a cabeca vao trocadas", CI_YAML,
     "          GATE9_BASE: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}\n"
     "          GATE9_HEAD: ${{ github.sha }}\n",
     "          GATE9_BASE: ${{ github.sha }}\n"
     "          GATE9_HEAD: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}\n",
     GATE9_CI),
    ("KAM-131 ci: o merge_group fica fail-closed sem chave de base", CI_YAML,
     " || github.event.merge_group.base_sha", "", GATE9_CI),
    ("KAM-131 make: o alvo ci-9 deixa de correr a segunda passagem", MAKEFILE,
     "'history', '--evento'", "'tree', '--evento'", GATE9_CI),
    # KAM-136 — o leitor de YAML. Nao e codigo de `db/`, mas as duas suites leem
    # dele `ci/rls_exceptions.yaml`, `ci/secdef_allowlist.yaml` e
    # `ci/thresholds.yaml`, e a copia leva-o (ver `_copiar`). Em `1fbe738` a
    # copia **nao** o levava e ninguem dava por isso (ANALISE-07 §…): estas
    # mutacoes tambem provam que a copia continua a leva-lo.
    #
    # So entram aqui as que estas suites **apanham**. O caso 1 do KAM-136 (`>-`
    # como primeira chave de um item) nao tem forma de ser apanhado por aqui:
    # nenhum ficheiro que estas suites leem usa essa forma. Esse prova-se na
    # suite do `lint_arch`, e a prova esta em `docs/evidencia/KAM-136.md`.
    ("kam136 isolamento: inteiro deixa de se converter", KYAML,
     '_INTEIRO = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")',
     '_INTEIRO = re.compile(r"^(?!x)x$")',
     ISOLAMENTO),
    ("kam136 isolamento: lista vazia em fluxo deixa de ser lista", KYAML,
     '    if texto.strip("[] ") == "" and texto.startswith("["):\n        return []\n',
     '    if texto.strip("[] ") == "" and texto.startswith("["):\n        return texto\n',
     ISOLAMENTO),
    ("kam136 isolamento: comentarios deixam de ser removidos", KYAML,
     "            limpa, cortou = _sem_comentario(bruta, onde)",
     "            limpa, cortou = bruta, False",
     ISOLAMENTO),
    # A mesma familia do caso 1: as chaves seguintes do item desaparecem. Esta
    # morde pela suite de identidade, que le `minimo_linhas` do estrato
    # `critico` de `ci/thresholds.yaml` — e esse e a segunda chave do item.
    ("kam136 identidade: as chaves seguintes do item deixam de entrar", KYAML,
     "            primeiro.update(seguintes)\n",
     "",
     IDENTIDADE),
]


#: O que a copia leva. `tools/kamba_yaml.py` e `ci/` nao sao codigo de `db/`,
#: mas a suite de isolamento le deles as listas de excepcoes.
def _copiar(destino: Path, suite: str = "tests") -> None:
    ignorar = shutil.ignore_patterns("__pycache__")
    if suite in SUITES_DE_TOOLS:
        # As baterias de `tools/` nao abrem `db/`, `libs/py-core` nem
        # `packages/core-ts`: cada mutacao do gate 9 pagava megabytes de copia
        # para nada, e sao 25 mutacoes.
        _copiar_para_o_gate_9(destino, ignorar)
        return
    shutil.copytree(RAIZ / "db", destino / "db", ignore=ignorar)
    shutil.copytree(RAIZ / "libs" / "py-core", destino / "libs" / "py-core", ignore=ignorar)
    shutil.copytree(RAIZ / "ci", destino / "ci", ignore=shutil.ignore_patterns("coverage", "sbom"))
    (destino / "tools").mkdir()
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    # O modulo de identidade (KAM-008): a fonte e os testes, sem `node_modules`
    # nem `dist` — a suite vai buscar os modulos a `KAMBA_RAIZ_NODE_MODULES`.
    shutil.copytree(
        RAIZ / "packages" / "core-ts", destino / "packages" / "core-ts",
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )


def _copiar_para_o_gate_9(destino: Path, ignorar) -> None:
    """O que as mutacoes do gate 9 precisam, e **so** isso (KAM-131).

    O gate 9 nao tem base de dados nenhuma: a copia leva o `scan_secrets`, o
    `ci/secrets-allow.yaml` que ele le, o `tools/kamba_yaml.py` que o le, e os
    dois ficheiros de registo que o `test_ci_gate9.py` confronta.
    """
    shutil.copytree(
        RAIZ / "tools" / "scan_secrets", destino / "tools" / "scan_secrets",
        ignore=ignorar,
    )
    (destino / "tools" / "kamba_yaml.py").parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    (destino / "ci").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "ci" / "secrets-allow.yaml", destino / "ci" / "secrets-allow.yaml"
    )
    # O unico ficheiro de `tools/lint_arch/tests` que a copia precisa: o que
    # confronta o job do gate 9 e o alvo `ci-9`.
    testes = destino / "tools" / "lint_arch" / "tests"
    testes.mkdir(parents=True)
    (testes / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(
        RAIZ / "tools" / "lint_arch" / "tests" / "test_ci_gate9.py",
        testes / "test_ci_gate9.py",
    )
    shutil.copy(RAIZ / "Makefile", destino / "Makefile")
    (destino / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(
        RAIZ / ".github" / "workflows" / "ci.yaml",
        destino / ".github" / "workflows" / "ci.yaml",
    )


def _gate_de_tools(copia: Path, pacote: str, padrao: str) -> tuple[int, str]:
    """A bateria `tools/<pacote>/tests/<padrao>` na copia (KAM-131).

    Sem Docker e sem PostgreSQL: o gate 9 nao tem base de dados. O `-t tools` e
    o mesmo que o `make test-py` usa, para que os nomes dos modulos sejam os que
    as baterias esperam.
    """
    r = subprocess.run(
        [
            PY, "-m", "unittest", "discover",
            "-s", f"tools/{pacote}/tests", "-t", "tools", "-p", padrao,
        ],
        cwd=copia,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, r.stdout + r.stderr


def _gate(copia: Path, suite: str) -> tuple[int, str]:
    if suite in SUITES_DE_TOOLS:
        return _gate_de_tools(copia, *SUITES_DE_TOOLS[suite])
    r = subprocess.run(
        [PY, str(copia / "db" / "gate_bd.py"), "--suite", suite],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, KAMBA_RAIZ_NODE_MODULES=str(RAIZ)),
    )
    return r.returncode, r.stdout + r.stderr


#: Linhas da saida que dizem **porque** a suite falhou. O resto — o arranque do
#: PostgreSQL, que o `gate_bd.py` tambem captura — e ruido, e as doze ultimas
#: linhas da saida eram quase sempre so isso: a revisao do KAM-143 viu uma
#: linha de base vermelha cujo `ModuleNotFoundError` nao aparecia em parte
#: nenhuma do diagnostico. De noite, isto e tudo o que fica no artefacto.
_PORQUE = ("FAIL:", "ERROR:", "Traceback", "File \"", "gate de BD:", "FATAL:")
#: A ultima linha de um *traceback* nao tem prefixo fixo: e o nome da excepcao.
_EXCEPCAO = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b")


def _porque_falhou(saida: str, maximo: int = 20) -> str:
    linhas = [
        l for l in saida.splitlines()
        if l.strip().startswith(_PORQUE) or _EXCEPCAO.match(l.strip())
    ]
    if not linhas:
        # Sem nenhuma linha reconhecivel, as ultimas sao melhor do que nada —
        # e dizer que nao se reconheceu e melhor do que as dar por explicacao.
        return "(nenhuma linha de falha reconhecida; as ultimas da saida)\n" + "\n".join(
            saida.strip().splitlines()[-maximo:]
        )
    return "\n".join(linhas[:maximo])


def linha_de_base(suite: str) -> None:
    """A copia **sem mutacao** tem de correr verde. Sem isto, a prova nao prova nada.

    A primeira versao deste ficheiro nao o verificava, e a prova do KAM-004 deu
    dez mutacoes apanhadas em dez — todas com exactamente quatro falhas. A copia
    nao levava `tools/` nem `ci/`, a suite de isolamento nem sequer importava, e
    **qualquer coisa** contava como «apanhada»: a prova por mutacao estava a
    passar pela razao errada, que e o defeito que ela existe para apanhar.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp)
        _copiar(copia, suite)
        codigo, saida = _gate(copia, suite)
    if codigo != 0:
        print(
            f"A copia sem mutacao NAO corre verde na suite `{suite}`. Uma mutacao "
            f"«apanhada» sobre isto nao significa nada.\n{_porque_falhou(saida)}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"linha de base verde: `{suite}` sem mutacao", flush=True)


#: Sinais de que a suite falhou por **carga da maquina**, e nao por a mutacao
#: ter sido apanhada. Com mutacoes em paralelo cada uma levanta o seu
#: PostgreSQL, e uma maquina a esgotar ligacoes ou a esperar por um trinco
#: produz `ERROR:` nos testes — que contaria como «apanhada» e dava a prova por
#: feita sem nenhum teste ter mordido. O sinal mais forte do que a contagem:
#: perante um destes, a prova dessa mutacao nao vale.
SINAIS_DE_CARGA = (
    "sorry, too many clients already",
    "canceling statement due to lock timeout",
    "canceling statement due to statement timeout",
    "canceling statement due to user request",
    "deadlock detected",
    "could not obtain lock",
    "server closed the connection unexpectedly",
    "connection refused",
    "the database system is",
)


def classificar(codigo: int, saida: str) -> tuple[str, str]:
    """O que a saida do gate diz sobre esta mutacao. Funcao pura, testavel."""
    falhas = [l for l in saida.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
    if codigo == 0:
        return "SOBREVIVEU", ""
    # Um erro de carregamento (`_FailedTest`) e a suite a nao importar, nao
    # um teste a apanhar a mutacao: conta como prova invalida, nao como apanhada.
    if any("_FailedTest" in l for l in falhas):
        return "PROVA INVALIDA", "a suite nao carregou: " + falhas[0][:90]
    minusculas = saida.lower()
    for sinal in SINAIS_DE_CARGA:
        if sinal in minusculas:
            return (
                "PROVA INVALIDA",
                f"a base cedeu a carga ({sinal}): baixe KAMBA_MUTACOES_PARALELO",
            )
    if not falhas:
        return "PROVA INVALIDA", saida.strip().splitlines()[-1][:110]
    return f"apanhada ({len(falhas)})", falhas[0][:110]


def correr(nome, ficheiro, velho, novo, suite="tests"):
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp)
        _copiar(copia, suite)
        alvo = copia / ficheiro
        texto = alvo.read_text(encoding="utf-8")
        if texto.count(velho) != 1:
            return "MUTACAO NAO APLICAVEL", ""
        alvo.write_text(texto.replace(velho, novo), encoding="utf-8", newline="\n")
        return classificar(*_gate(copia, suite))


def _suite(mutacao) -> str:
    return mutacao[4] if len(mutacao) > 4 else "tests"


def escolhidas(filtro: str) -> list:
    """As mutacoes que o filtro escolhe: a suite, o nome exacto, ou um excerto."""
    return [
        m for m in MUTACOES
        if not filtro or filtro == _suite(m) or filtro in m[0]
    ]


def _paralelo() -> int:
    valor = os.environ.get("KAMBA_MUTACOES_PARALELO", "8")
    # `isdigit` aceita o que `int` recusa (algarismos em expoente, por exemplo).
    if not (valor.isascii() and valor.isdigit()) or int(valor) < 1:
        print(
            f"KAMBA_MUTACOES_PARALELO tem de ser um inteiro >= 1 (encontrado: {valor!r})",
            file=sys.stderr,
        )
        sys.exit(2)
    return int(valor)


def aplicaveis() -> int:
    """Cada mutacao ainda encontra o seu texto, exactamente uma vez. Sem Docker."""
    falhas = 0
    for mutacao in MUTACOES:
        nome, ficheiro, velho = mutacao[0], mutacao[1], mutacao[2]
        alvo = RAIZ / ficheiro
        vezes = alvo.read_text(encoding="utf-8").count(velho) if alvo.is_file() else -1
        if vezes != 1:
            falhas += 1
            motivo = "ficheiro em falta" if vezes < 0 else f"o texto aparece {vezes} vez(es)"
            print(f"MUTACAO NAO APLICAVEL  {nome}  ({ficheiro}: {motivo})")
    print(f"{len(MUTACOES)} mutacao(oes) conferida(s), {falhas} nao aplicavel(is)")
    return 1 if falhas else 0


def fatiar(lista: list, fatia: str) -> list:
    """`i/n`: a i-esima de n fatias, alternadamente (`1/6` leva a 1.ª, a 7.ª, …).

    Alternadamente e nao em blocos de propósito: as mutacoes de um ticket estao
    juntas na lista e nao custam todas o mesmo — as de identidade semeiam mil
    contactos. Em blocos, uma fatia levava todas as caras e as outras esperavam
    por ela. O preco e cada fatia tocar nas duas suites, e por isso correr as
    duas linhas de base.
    """
    numero, _, total = fatia.partition("/")
    if not (numero.isascii() and numero.isdigit() and total.isascii() and total.isdigit()):
        raise ValueError(f"--fatia tem de ser `i/n` com inteiros (recebido: {fatia!r})")
    i, n = int(numero), int(total)
    if not 1 <= i <= n or n < 1:
        raise ValueError(f"--fatia tem de cumprir 1 <= i <= n (recebido: {fatia!r})")
    return lista[i - 1 :: n]


def _opcao(argumentos: list[str], nome: str) -> tuple[list[str], str | None]:
    """Tira `--nome valor` (ou `--nome=valor`) da lista. Sem valor, levanta."""
    for indice, argumento in enumerate(argumentos):
        if argumento == nome:
            if indice + 1 >= len(argumentos):
                raise ValueError(f"{nome} sem valor")
            return argumentos[:indice] + argumentos[indice + 2 :], argumentos[indice + 1]
        if argumento.startswith(f"{nome}="):
            return argumentos[:indice] + argumentos[indice + 1 :], argumentos[indice].split("=", 1)[1]
    return argumentos, None


def main(argumentos: list[str]) -> int:
    global PY

    # `--aplicaveis` so vale como **primeiro** argumento, e sozinho. Era uma
    # pesquisa de pertenca em toda a linha de comandos, e a revisao do KAM-143
    # mostrou o que isso abria: `--aplicaveis` como **filtro** — que e o que a
    # tarefa nocturna passa na entrada do `workflow_dispatch` — fazia as seis
    # fatias correrem a conferencia de segundos e sairem verdes, com zero
    # mutacoes e zero linhas de base. A prova dava-se por feita.
    if argumentos[:1] == ["--aplicaveis"]:
        if len(argumentos) > 1:
            print(
                "--aplicaveis nao se combina com mais nada: confere a lista inteira "
                f"e sai (recebido tambem: {argumentos[1:]})",
                file=sys.stderr,
            )
            return 2
        return aplicaveis()
    try:
        argumentos, fatia = _opcao(argumentos, "--fatia")
    except ValueError as erro:
        print(erro, file=sys.stderr)
        return 2
    # Nenhum posicional pode parecer uma opcao: um `--qualquer-coisa` aqui e
    # quem chama a enganar-se, nao um filtro.
    for posicional in argumentos[:2]:
        if posicional.startswith("--"):
            print(
                f"{posicional!r} nao e um filtro nem um Python: as opcoes desta "
                "prova sao `--aplicaveis` (sozinha) e `--fatia i/n`",
                file=sys.stderr,
            )
            return 2
    if argumentos:
        # Absoluto, sempre: `_gate_de_tools` corre com o directorio de trabalho
        # **dentro da copia**, e um caminho relativo como `.venv/bin/python` nao
        # existe la. A tarefa nocturna passava-o relativo e as seis fatias
        # morriam todas com FileNotFoundError, sem uma mutacao corrida.
        PY = argumentos[0]
        if ("/" in PY or "\\" in PY) and not Path(PY).is_absolute():
            PY = str(Path(PY).resolve())
    filtro = argumentos[1] if len(argumentos) > 1 else ""

    lista = escolhidas(filtro)
    if not lista:
        # Um filtro que nao escolhe nada nao pode parecer uma prova limpa.
        print(f"o filtro {filtro!r} nao escolhe nenhuma mutacao", file=sys.stderr)
        return 2
    if fatia is not None:
        try:
            lista = fatiar(lista, fatia)
        except ValueError as erro:
            print(erro, file=sys.stderr)
            return 2
        if not lista:
            # Uma fatia vazia saia com 0 e parecia uma fatia limpa. Com mais
            # fatias do que mutacoes, o erro esta em quem fatiou.
            print(
                f"a fatia {fatia} nao tem mutacao nenhuma (o filtro escolheu "
                f"{len(escolhidas(filtro))})",
                file=sys.stderr,
            )
            return 2
        print(f"fatia {fatia}: {len(lista)} mutacao(oes)", flush=True)
    paralelo = _paralelo()
    for suite_usada in sorted({_suite(m) for m in lista}):
        linha_de_base(suite_usada)

    nao_apanhadas = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=paralelo) as executor:
        futuros = [
            executor.submit(correr, m[0], m[1], m[2], m[3], _suite(m)) for m in lista
        ]
        for mutacao, futuro in zip(lista, futuros):
            try:
                estado, detalhe = futuro.result()
            except Exception as erro:  # noqa: BLE001 - o relatorio tem de chegar ao fim
                # Uma excepcao numa execucao nao pode levar o relatorio das outras.
                estado, detalhe = "PROVA INVALIDA", f"{type(erro).__name__}: {erro}"[:110]
            if not estado.startswith("apanhada"):
                nao_apanhadas += 1
            print(f"{estado:<22} {mutacao[0]}", flush=True)
            if detalhe:
                print(f"{'':<22}   {detalhe}", flush=True)
    print(f"\n{len(lista)} mutacao(oes) corrida(s), {nao_apanhadas} nao apanhada(s)")
    return 1 if nao_apanhadas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

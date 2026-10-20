"""Prova por mutacao dos gates verificados por suite, uma alteracao por execucao.

    python db/mutacoes.py [python] [filtro] [--fatia i/n]

Comecou nos gates de base de dados (6 e 8) e e ainda ai que esta a maior parte
da lista; desde o KAM-131 corre tambem as duas baterias do **gate 9**, que nao
levantam base de dados nenhuma (`SUITES_DE_TOOLS`).

O primeiro argumento e o Python que tem as dependencias das migracoes (por
omissao, o que corre este ficheiro). O segundo filtra: o nome de uma suite
(`tests`, `tests_identidade`, `tests_isolamento`, `tests_eventos_consumo`,
`tests_ten`, `gate9`, `gate9_ci`), o nome exacto de uma mutacao, ou um
**excerto** do nome (`guarda:`, `resolvedor`, `downgrade da 0002`,
`identidade:`, `revisao 0007:`, `KAM-131`), sensivel a maiusculas.

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
#: KAM-158: o varredor das contagens em prosa. Corre-se `test_scan.py` e nao a
#: bateria inteira: o `test_cli.py` tem um caso que afirma sobre o repositorio.
CONTAGENS = "contagens"

#: As baterias de `tools/` que esta prova sabe correr: `(pacote, padrao)`.
#: Nao levantam base de dados nenhuma — o gate 9 nao tem base de dados — e por
#: isso correm em segundos.
#:
#: Corre-se o ficheiro de testes do ticket e nao a bateria inteira do pacote: as
#: outras baterias de `tools/` afirmam coisas sobre o **repositorio** (a arvore
#: seguida pelo git, a estrutura de pastas) que a copia nao e, e uma linha de
#: base vermelha nao prova nada.
#: KAM-007: o gate 7 dos contratos de evento. Corre a bateria **inteira** — ao
#: contrario das outras tres — porque nenhum dos seus ficheiros afirma coisas
#: sobre a arvore seguida pelo git: o `test_catalogo_e_cli.py` le
#: `contratos/eventos/`, que a copia leva.
CONTRATOS = "contratos"

SUITES_DE_TOOLS = {
    GATE9: ("scan_secrets", "test_historia.py"),
    GATE9_CI: ("lint_arch", "test_ci_gate9.py"),
    CONTAGENS: ("lint_contagens", "test_scan.py"),
    CONTRATOS: ("contract_diff", "test_*.py"),
}
#: O leitor de YAML (KAM-136). As duas suites leem por ele as listas de
#: excepcoes de `ci/` e o limiar do estrato `critico`.
CONT_SCAN = "tools/lint_contagens/scan.py"
#: KAM-007: os modulos do gate 7 e um dos contratos, para as mutacoes morderem
#: tanto no classificador como no que ele le.
CD_DIFF = "tools/contract_diff/diff.py"
CD_PII = "tools/contract_diff/pii.py"
CD_GERAR = "tools/contract_diff/gerar.py"
CD_EXEMPLOS = "tools/contract_diff/exemplos.py"
CONTRATO_PAY_MANUAL = "contratos/eventos/payment.manual_confirmed/v1.schema.json"
CONTRATO_ORDER_PAID = "contratos/eventos/order.paid/v1.schema.json"
KYAML = "tools/kamba_yaml.py"
#: KAM-005: a revisao do outbox e os modulos de eventos em TypeScript.
REV4 = "db/migrations/versions/0004_outbox_e_eventos.py"
EVENTOS = "tests_eventos"
EV_ENVELOPE = "packages/core-ts/src/eventos/envelope.ts"
EV_PII = "packages/core-ts/src/eventos/pii.ts"
EV_PARTICAO = "packages/core-ts/src/eventos/particao.ts"
EV_CONSULTAS = "packages/core-ts/src/eventos/consultas.ts"
EV_PUBLICADOR = "packages/core-ts/src/eventos/publicador.ts"
EV_FILAS = "packages/core-ts/src/eventos/filas_bullmq.ts"
#: KAM-006: a revisao do consumo e da DLQ, e os modulos do consumidor.
REV5 = "db/migrations/versions/0005_consumo_dlq.py"
CONSUMO = "tests_eventos_consumo"
EV_CONSUMO = "packages/core-ts/src/eventos/consumo.ts"
EV_TRABALHO = "packages/core-ts/src/eventos/trabalho.ts"
EV_DLQ = "packages/core-ts/src/eventos/dlq.ts"
EV_RECON = "packages/core-ts/src/eventos/reconciliador.ts"
EV_TRABALHADOR = "packages/core-ts/src/eventos/trabalhador_bullmq.ts"
EV_ACCOES = "packages/core-ts/src/eventos/accoes.ts"
#: KAM-012: a revisao do registo de auditoria e o verificador da cadeia.
#:
#: As mutacoes da cadeia correm contra a suite `tests`, e **nao** contra a de
#: carga: as mil insercoes concorrentes custam meio minuto cada, e uma mutacao
#: que a cadeia partida ja faz falhar em `tests` nao precisa de as pagar. A de
#: carga existe para provar a concorrencia uma vez, no gate.
REV6 = "db/migrations/versions/0006_audit_log.py"
AUDITORIA = "db/auditoria.py"
#: KAM-009: a revisao do consumo de limites e a suite que a prova.
REV7 = "db/migrations/versions/0007_ten_uso_e_limites.py"
TEN = "tests_ten"

#: KAM-014: o CHR. A revisao das conversas, os ficheiros do modulo que podem
#: errar em silencio, e a suite que os prova.
#:
#: **A `0008` entra aqui e nao no KAM-013**, que nao deixou mutacao nenhuma: o
#: dominio de `unrouted_events.motivo` passou a ter os dois motivos do
#: encaminhamento, e o `CHECK` e o que impede o CHR de escrever um motivo que
#: ninguem declarou. Retirar um valor da tupla faz a quarentena falhar **na
#: insercao** — isto e, o evento deixa de deixar linha — e sem mutacao isso so
#: se via no dia em que acontecesse.
REV8 = "db/migrations/versions/0008_entrada_de_canal.py"
REV9 = "db/migrations/versions/0009_conversas.py"
REV10 = "db/migrations/versions/0010_saida_de_canal.py"
#: A suite da saida (KAM-015). E a mais **estreita** que apanha o que a `0010` e
#: o modulo `src/outbound/` prometem: a unicidade por tenant, a monotonia contra
#: concorrencia e o custo que sai do `pricing`.
SAIDA = "tests_outbound"
SAIDA_SQL = "packages/core-ts/src/outbound/consultas.ts"
SAIDA_ESTADOS = "packages/core-ts/src/outbound/estados.ts"
SAIDA_LIMITES = "packages/core-ts/src/outbound/limites.ts"
SAIDA_TARIFAS = "packages/core-ts/src/outbound/tarifas.ts"
SAIDA_DECISAO = "packages/core-ts/src/outbound/decisao.ts"
SAIDA_ADAPTER = "packages/core-ts/src/outbound/adapter.ts"
CHR = "tests_chr"
CHR_CANAL = "packages/core-ts/src/chr/canal.ts"
CHR_SQL = "packages/core-ts/src/chr/consultas.ts"
CHR_FLUXO_B = "packages/core-ts/src/chr/fluxo_b.ts"
CHR_MODULO = "packages/core-ts/src/chr/chr.ts"
CHR_CONVERSAS = "packages/core-ts/src/chr/conversas.ts"
CHR_INVOCACAO = "packages/core-ts/src/chr/invocacao.ts"

#: O corpo da subtransaccao da `ten_consumir`, como a revisao 0007 o escreve:
#: **a chave primeiro, a contagem depois**. A mutacao da ordem precisa do
#: texto inteiro, incluindo o comentario pelo meio, porque nao ha alteracao
#: mais curta que leve uma instrucao de um lado do bloco para o outro — e as
#: posicoes intermedias **nao** sao a mutacao: com o registo da chave entre a
#: contagem e o `IF v_valor IS NULL`, a repeticao continua a bater na
#: unicidade antes de bater no tecto, e a funcao responde o mesmo.
_TEN_ORDEM = """  BEGIN
    INSERT INTO platform.usage_ledger
                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);

    IF p_quantidade > v_limite THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.tenant_usage
                (tenant_id, chave_limite, periodo, valor)
         VALUES (p_tenant, p_chave, v_periodo, p_quantidade)
    ON CONFLICT (tenant_id, chave_limite, periodo) DO UPDATE
       SET valor = platform.tenant_usage.valor + p_quantidade,
           actualizado_at = now()
     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite
    RETURNING platform.tenant_usage.valor INTO v_valor;

    -- E aqui que a atomicidade mora: duas transaccoes em conflito na mesma
    -- chave serializam no lock da linha, e a segunda reavalia o `WHERE`
    -- sobre o valor **ja actualizado** pela primeira. Sem linha devolvida, o
    -- tecto recusou.
    IF v_valor IS NULL THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;
  EXCEPTION"""

#: O mesmo bloco com as duas insercoes trocadas: contar primeiro, registar a
#: chave depois. E o que a docstring da revisao diz que esta errado.
_TEN_ORDEM_TROCADA = """  BEGIN
    IF p_quantidade > v_limite THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.tenant_usage
                (tenant_id, chave_limite, periodo, valor)
         VALUES (p_tenant, p_chave, v_periodo, p_quantidade)
    ON CONFLICT (tenant_id, chave_limite, periodo) DO UPDATE
       SET valor = platform.tenant_usage.valor + p_quantidade,
           actualizado_at = now()
     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite
    RETURNING platform.tenant_usage.valor INTO v_valor;

    IF v_valor IS NULL THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.usage_ledger
                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);
  EXCEPTION"""

#: O registo da chave **fora** da subtransaccao: fica escrito mesmo quando o
#: tecto recusa, e uma segunda tentativa com a mesma chave le-se como
#: repeticao de um consumo que nunca aconteceu.
_TEN_CHAVE_FORA = """  INSERT INTO platform.usage_ledger
              (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
       VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);

  BEGIN
    IF p_quantidade > v_limite THEN"""

#: A comparacao da quantidade numa repeticao, que a revisao adversarial
#: obrigou a acrescentar (C1). Sem ela, repetir a chave de um consumo de 1
#: autorizava um pedido de 99 999 999: a funcao respondia «repetido» e quem
#: chama lia «podes».
_TEN_QUANTIDADE = """    IF v_antes IS DISTINCT FROM p_quantidade THEN
      RAISE EXCEPTION
        'ten_consumir: a chave de idempotencia % ja foi usada em % com quantidade % e veio %',
        p_idempotency_key, p_chave, v_antes, p_quantidade
        USING ERRCODE = 'KA002';
    END IF;"""

#: A guarda do relogio (M1): `p_agora` so aponta para outro periodo quando
#: quem chama e `kamba_batch`.
_TEN_RELOGIO = """  IF v_periodo <> platform.ten_periodo(now())
     AND NOT pg_has_role(current_user, 'kamba_batch', 'USAGE') THEN
    RAISE EXCEPTION
      'ten_consumir: p_agora aponta para o periodo % e o corrente e %; so o kamba_batch fixa o relogio',
      v_periodo, platform.ten_periodo(now())
      USING ERRCODE = 'invalid_parameter_value';
  END IF;"""

#: A guarda da chave de idempotencia vazia (m4).
_TEN_CHAVE_VAZIA = """  IF p_idempotency_key IS NULL OR p_idempotency_key ~ '^[[:space:]]*$' THEN
    RAISE EXCEPTION 'ten_consumir: p_idempotency_key nula ou vazia'
      USING ERRCODE = 'check_violation';
  END IF;"""

#: O trigger que torna o contador *append-only* (C3). Em aspas simples
#: triplas porque o texto que ele procura **tem** aspas duplas triplas: e
#: uma instrucao de uma migracao, e as migracoes escrevem SQL assim.
_TEN_TRIGGER = '''    op.execute(
        """
        CREATE TRIGGER tenant_usage_so_sobe
          BEFORE UPDATE ON platform.tenant_usage
          FOR EACH ROW EXECUTE FUNCTION platform.ten_usage_so_sobe()
        """
    )
'''

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
    # O texto mudou com o KAM-005 (`AND NOT c.relispartition`, que tirou as
    # particoes da descoberta e as passou para `verificar_particoes`). A mutacao
    # continua a ser a mesma: tirar as tabelas particionadas (`'p'`) da
    # descoberta, e a apanha e a contagem do X-05 — o `events_log` e uma delas.
    ("catalogo: a descoberta ignora tabelas particionadas", CATALOGO,
     "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition ",
     "WHERE c.relkind IN ('r') AND NOT c.relispartition ", ISOLAMENTO),
    # KAM-005: a descoberta de particoes deixa de excluir indices. O
    # `pg_inherits` liga tambem um indice particionado aos seus filhos, e o
    # `pg_attribute` tem linhas para as colunas de um indice: sem o filtro, o
    # X-05 pedia uma politica de RLS **num indice** (medido, e corrigido).
    ("catalogo: a descoberta de particoes apanha indices", CATALOGO,
     "WHERE c.relispartition AND c.relkind IN ('r', 'p') ",
     "WHERE c.relispartition ", ISOLAMENTO),
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
    # A ancora leva o comentario de cima: o KAM-007 pos um segundo
    # `fetch-depth: 0` no `ci.yaml` (o do gate 7 compara com o ramo principal),
    # e a linha sozinha deixou de identificar um sitio so.
    ("KAM-131 ci: o checkout do gate 9 deixa de trazer a historia", CI_YAML,
     "          # nao verde em silencio (`historia.py:_resolver`).\n"
     "          fetch-depth: 0",
     "          # nao verde em silencio (`historia.py:_resolver`).\n"
     "          fetch-depth: 1", GATE9_CI),
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
    # ------------------------------------------------------------------- KAM-005
    # Outbox, envelope e publicador. As da revisao correm no gate 8 (suite
    # `tests`); as que tiram RLS correm no gate 6 (`ISOLAMENTO`).
    ("0004: guarda de PII sem o padrao angolano", REV4,
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' OR p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN",
     "IF p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN"),
    ("0004: guarda de PII sem o padrao E.164", REV4,
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' OR p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN",
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' THEN"),
    ("0004: guarda de PII depois de escrever no outbox", REV4,
     "        BEGIN\n          IF p_payload::text ~",
     "        BEGIN\n          IF false AND p_payload::text ~"),
    ("0004: o contador nao incrementa (seq de uma sequencia)", REV4,
     "            DO UPDATE SET seq = platform.evt_agregado_seq.seq + 1\n"
     "            RETURNING seq INTO v_seq;",
     "            DO UPDATE SET seq = platform.evt_agregado_seq.seq\n"
     "            RETURNING seq + 1 INTO v_seq;"),
    ("0004: a particao usa oito filas em vez de dezasseis", REV4,
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint;",
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 7)::smallint;"),
    ("0004: a particao ignora o tenant", REV4,
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint;",
     "v_part := (hashtextextended(p_agg_id, 0) & 15)::smallint;"),
    ("0004: o envelope perde o seq do agregado", REV4,
     "'agregado', jsonb_build_object('tipo', p_agg_tipo, 'id', p_agg_id, 'seq', v_seq),",
     "'agregado', jsonb_build_object('tipo', p_agg_tipo, 'id', p_agg_id),"),
    ("0004: o envelope leva outro tenant que a coluna", REV4,
     "'tenant_id', p_tenant,\n                'ocorrido_em', p_ocorrido_em,",
     "'tenant_id', gen_random_uuid(),\n                'ocorrido_em', p_ocorrido_em,"),
    ("0004: evt_emitir passa a SECURITY DEFINER", REV4,
     "        RETURNS uuid LANGUAGE plpgsql AS $$",
     "        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER AS $$"),
    ("0004: o arquivo ganha UPDATE para o publicador", REV4,
     'op.execute("GRANT SELECT, INSERT ON platform.events_log TO kamba_batch")',
     'op.execute("GRANT SELECT, INSERT, UPDATE ON platform.events_log TO kamba_batch")'),
    ("0004: o produtor ganha UPDATE no outbox", REV4,
     'op.execute("GRANT SELECT, INSERT ON platform.events_outbox TO kamba_app")',
     'op.execute("GRANT SELECT, INSERT, UPDATE ON platform.events_outbox TO kamba_app")'),
    ("0004: a particao DEFAULT passa a mensal", REV4,
     "          PARTITION OF platform.events_log DEFAULT",
     "          PARTITION OF platform.events_log\n"
     "          FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')"),
    ("0004: o indice de pendentes deixa de ser parcial", REV4,
     "          ON platform.events_outbox (proxima_tentativa_at, id)\n"
     "          WHERE publicado_at IS NULL",
     "          ON platform.events_outbox (proxima_tentativa_at, id)"),
    ("0004: o outbox perde a unicidade do event_id", REV4,
     "          event_id             uuid NOT NULL\n"
     "                               CONSTRAINT events_outbox_event_id_uq UNIQUE,",
     "          event_id             uuid NOT NULL,"),
    ("0004: o outbox perde a unicidade do triplo do agregado", REV4,
     "          CONSTRAINT events_outbox_agregado_uq\n"
     "            UNIQUE (tenant_id, agregado_tipo, agregado_id, agregado_seq)\n",
     ""),
    # As duas que provam o desvio do achado 2: sem o `tenant_id` na unicidade e
    # no `ON CONFLICT`, o espaco de `seq` volta a ser global e um tenant corta a
    # emissao de outro.
    ("0004: a unicidade do triplo ignora o tenant", REV4,
     "            UNIQUE (tenant_id, agregado_tipo, agregado_id, agregado_seq)",
     "            UNIQUE (agregado_tipo, agregado_id, agregado_seq)"),
    ("0004: o contador do agregado ignora o tenant", REV4,
     "            ON CONFLICT (tenant_id, agregado_tipo, agregado_id)",
     "            ON CONFLICT (agregado_tipo, agregado_id)"),
    ("0004: o downgrade apaga os eventos sem pedir copia", REV4,
     "    contagens = _contar()\n    if not any(contagens.values()):\n        return\n",
     "    contagens = _contar()\n    return\n"),
    ("0004: a copia logica escreve por cima de uma anterior", REV4,
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600",
     "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600"),
    ("0004: o downgrade copia antes de desligar a RLS (le zero linhas)", REV4,
     '    rls.disable_tenant_rls("events_log_default")\n'
     '    rls.disable_tenant_rls("events_log")\n'
     '    rls.disable_tenant_rls("evt_agregado_seq")\n'
     '    rls.disable_tenant_rls("events_outbox")\n'
     "    _copia_logica()\n",
     "    _copia_logica()\n"
     '    rls.disable_tenant_rls("events_log_default")\n'
     '    rls.disable_tenant_rls("events_log")\n'
     '    rls.disable_tenant_rls("evt_agregado_seq")\n'
     '    rls.disable_tenant_rls("events_outbox")\n'),
    ("0004: o outbox fica sem RLS", REV4,
     '    "events_outbox",\n    "evt_agregado_seq",\n',
     '    "evt_agregado_seq",\n', ISOLAMENTO),
    ("0004: o contador do agregado fica sem RLS", REV4,
     '    "events_outbox",\n    "evt_agregado_seq",\n',
     '    "events_outbox",\n', ISOLAMENTO),
    ("0004: a particao do arquivo fica sem RLS propria", REV4,
     '    "events_log",\n    "events_log_default",\n)',
     '    "events_log",\n)', ISOLAMENTO),
    ("0004: o arquivo fica sem RLS", REV4,
     '    "events_log",\n    "events_log_default",\n)',
     '    "events_log_default",\n)', ISOLAMENTO),
    ("0004: o produtor ganha DELETE no outbox", REV4,
     'op.execute(\n        "GRANT SELECT, UPDATE, DELETE ON platform.events_outbox TO kamba_batch"\n    )',
     'op.execute(\n        "GRANT SELECT, UPDATE, DELETE ON platform.events_outbox TO kamba_app"\n    )'),
    # --------------------------------------------------- KAM-005, o publicador
    # Correm contra `tests_eventos` — PostgreSQL **e** fila reais. A medicao de
    # carga esta em `tests_eventos_carga`, a parte, para que cada uma destas
    # custe tres minutos e nao oito (ver o comentario dessa suite).
    # A mutacao central: trocar a ordem `add` -> `COMMIT` por `COMMIT` -> `add`.
    # E o modo de falha que o outbox existe para nao ter — um `kill -9` logo
    # depois do `COMMIT` deixava a linha publicada e o *job* por criar — e e o
    # criterio 3 que a apanha.
    ("eventos: o publicador confirma antes de por na fila", EV_PUBLICADOR,
     "      const ids = boas.map((p) => p.linha.id);\n"
     "      if (ids.length > 0) {\n"
     "        await this.#bd.query(SQL_ARQUIVAR, [ids]);\n"
     "        await this.#bd.query(SQL_MARCAR_PUBLICADO, [ids]);\n"
     "      }\n"
     '      await this.#bd.query("COMMIT");\n',
     '      await this.#bd.query("COMMIT");\n'
     "      const ids = boas.map((p) => p.linha.id);\n"
     "      if (ids.length > 0) {\n"
     "        await this.#bd.query(SQL_ARQUIVAR, [ids]);\n"
     "        await this.#bd.query(SQL_MARCAR_PUBLICADO, [ids]);\n"
     "      }\n",
     EVENTOS),
    # Achado 1: a fase 1 deixa de cortar por agregado e passa a derrubar o lote.
    # A mutacao poe de volta o defeito que o achado 1 descreve.
    ("eventos: uma linha invalida volta a derrubar o lote", EV_PUBLICADOR,
     "      } catch (erro) {\n"
     "        const motivo = motivoDoErro(erro);\n"
     "        this.#metricas.contar(METRICA_ERROS, motivo);\n"
     '        this.#log?.warn({ outcome: "evt_bloqueado", error_code: motivo });\n'
     "        agregadosBloqueados.add(agregado);\n"
     "        adiadas.push(linha);\n"
     "      }\n",
     "      } catch (erro) {\n"
     "        const motivo = motivoDoErro(erro);\n"
     "        this.#metricas.contar(METRICA_ERROS, motivo);\n"
     '        this.#log?.warn({ outcome: "evt_bloqueado", error_code: motivo });\n'
     "        throw erro;\n"
     "      }\n",
     EVENTOS),
    # Achado 1, segunda metade: o corte deixa de ser por agregado e passa a ser
    # so da linha ma — o que perde a ordem causal do agregado dela.
    ("eventos: o corte deixa de arrastar o resto do agregado", EV_PUBLICADOR,
     "      if (agregadosBloqueados.has(agregado)) {\n"
     "        adiadas.push(linha);\n"
     "        continue;\n"
     "      }\n",
     ""),
    # Achado 13: o erro do laco volta a nao largar o lock consultivo.
    ("eventos: um erro transitorio deixa o lock preso", EV_PUBLICADOR,
     "        await this.largar();\n"
     "      }\n"
     "      await esperar(this.#intervalo, sinal);",
     "        this.#lider = false;\n"
     "      }\n"
     "      await esperar(this.#intervalo, sinal);",
     EVENTOS),
    # Achado 7: o atraso do criterio 8 volta a ser medido pelo relogio do
    # inicio da transaccao, que exclui o enfileiramento do lote.
    ("eventos: o atraso e medido antes do trabalho", EV_CONSULTAS,
     "     SET publicado_at = clock_timestamp()",
     "     SET publicado_at = now()"),
    # Achado 5: o cliente da fila volta a esconder a indisponibilidade.
    ("eventos: a fila em baixo deixa de falhar o add", EV_FILAS,
     "  enableOfflineQueue: false,",
     "  enableOfflineQueue: true,",
     EVENTOS),
    # A que mais importa das tres: sem limite no `add`, o publicador fica
    # pendurado com a fila em baixo e o recuo do criterio 4 nunca acontece.
    ("eventos: o add espera indefinidamente pela fila", EV_FILAS,
     "export const TEMPO_MAXIMO_DO_ADD = 5_000;",
     "export const TEMPO_MAXIMO_DO_ADD = 3_600_000;",
     EVENTOS),
    ("eventos: o envelope deixa de recusar campos desconhecidos", EV_ENVELOPE,
     "  if (demais.length > 0) {\n"
     "    throw new EnvelopeInvalidoError(\n"
     "      `campo(s) de topo desconhecido(s): ${demais.sort().join(\", \")}`,\n"
     "    );\n"
     "  }\n",
     ""),
    ("eventos: o envelope aceita classe_pii P2", EV_ENVELOPE,
     '  if (classe === "P2") {',
     '  if (classe === "P9") {'),
    ("eventos: o guarda de PII perde o padrao angolano", EV_PII,
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO, E164_ENTRE_ASPAS] as const;",
     "export const PADROES_DE_TELEFONE = [E164_ENTRE_ASPAS] as const;"),
    ("eventos: o guarda de PII perde o padrao E.164", EV_PII,
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO, E164_ENTRE_ASPAS] as const;",
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO] as const;"),
    ("eventos: o recuo do outbox perde o tecto de 30 s", EV_PUBLICADOR,
     "export const ESCADA_DE_RECUO = [1_000, 2_000, 5_000, 15_000, 30_000] as const;",
     "export const ESCADA_DE_RECUO = [1_000, 5_000, 30_000, 120_000, 600_000] as const;",
     EVENTOS),
    ("eventos: o arquivo deixa de absorver a republicacao", EV_CONSULTAS,
     "  ON CONFLICT DO NOTHING",
     "  ON CONFLICT (event_id, ocorrido_em) DO UPDATE SET registado_em = now()",
     EVENTOS),
    ("eventos: o jobId deixa de ser o event_id", EV_PUBLICADOR,
     "        jobId: envelope.id,",
     "        jobId: `${envelope.id}:${alvo.consumer}`,",
     EVENTOS),
    ("eventos: a entrega ignora a finalidade do envelope", EV_PUBLICADOR,
     "  return subscricoes.filter(\n"
     "    (s) => s.tipo === envelope.tipo && finalidades.has(s.finalidade),\n"
     "  );",
     "  return subscricoes.filter((s) => s.tipo === envelope.tipo);",
     EVENTOS),
    ("eventos: a entrega ignora o tipo do envelope", EV_PUBLICADOR,
     "  return subscricoes.filter(\n"
     "    (s) => s.tipo === envelope.tipo && finalidades.has(s.finalidade),\n"
     "  );",
     "  return subscricoes.filter((s) => finalidades.has(s.finalidade));",
     EVENTOS),
    ("eventos: o recuo nao adia nada", EV_CONSULTAS,
     "         proxima_tentativa_at = now() + make_interval(secs => $2::double precision / 1000)",
     "         proxima_tentativa_at = now() + make_interval(secs => $2::double precision * 0)",
     EVENTOS),
    ("eventos: o publicador varre por ordem inversa de escrita", EV_CONSULTAS,
     "   ORDER BY id\n   LIMIT $1",
     "   ORDER BY id DESC\n   LIMIT $1",
     EVENTOS),
    ("eventos: o publicador le as subscricoes inactivas", EV_CONSULTAS,
     "    FROM platform.evt_subscricoes\n   WHERE activo",
     "    FROM platform.evt_subscricoes\n   WHERE activo IS NOT NULL",
     EVENTOS),
    ("eventos: a lideranca deixa de ser exclusiva", EV_CONSULTAS,
     'export const SQL_ELEGER = "SELECT pg_try_advisory_lock($1) AS lider";',
     'export const SQL_ELEGER = "SELECT ($1 IS NOT NULL) AS lider";',
     EVENTOS),
    ("eventos: a particao dobra por modulo em vez de falhar", EV_PARTICAO,
     "  return `${PREFIXO_DA_FILA}.${consumer}.p${exigirParticao(particao)}`;",
     "  return `${PREFIXO_DA_FILA}.${consumer}.p${particao % PARTICOES}`;",
     EVENTOS),
    ("eventos: o publicador nao repete o guarda de PII", EV_PUBLICADOR,
     '    exigirSemTelefone(envelope.payload, "payload do evento");\n',
     "",
     EVENTOS),
    # ---------------------------------------------------------------- KAM-158
    # O varredor das contagens em prosa. Cada uma tem de ser apanhada por
    # `tools/lint_contagens/tests/test_scan.py` (suite `contagens`).
    #
    # Nao ha mutacao aos tres guardas da CLI (grandeza sem ocorrencias, minimo
    # da populacao, declaracao que nao casa nada): a bateria que os exercita e o
    # `test_cli.py`, que afirma sobre o repositorio real, e a copia da prova nao
    # e o repositorio. Ficam cobertos por teste de unidade, e o bloco do ticket
    # di-lo.
    ("KAM-158 contagens: o comparador passa a dizer sempre que bate", CONT_SCAN,
     "        return self.escrito in self.aceitaveis",
     "        return True", CONTAGENS),
    ("KAM-158 contagens: a linha de controlo de versoes deixa de ser historia", CONT_SCAN,
     "        if em_verificacao or VERSAO.match(linha):",
     "        if em_verificacao:", CONTAGENS),
    ("KAM-158 contagens: o numero de um identificador volta a contar", CONT_SCAN,
     "    'tickets': re.compile(r'(?<![\\w.-])(\\d{1,4})\\s+tickets?\\b', re.I),",
     "    'tickets': re.compile(r'(?<![\\w.])(\\d{1,4})\\s+tickets?\\b', re.I),", CONTAGENS),
    ("KAM-158 contagens: a leitura por epic desaparece", CONT_SCAN,
     "        epic = epic_do_ficheiro(rel)\n"
     "        if epic and epic in fontes.por_epic:\n"
     "            valores.append(fontes.por_epic[epic])\n",
     "", CONTAGENS),

    # ------------------------------------------------------------- KAM-006
    #
    # Quinze, e doze delas apontadas a suite com fila: o que so ela ve e a
    # transaccao unica, a contagem de tentativas, a classificacao do erro e a
    # reposicao. Cada uma e um defeito que existiu, ou que a revisao do espelho
    # em Python ou a revisao adversarial encontraram — nenhuma e inventada para
    # encher a lista.
    #
    # As outras tres apontam a suite `tests`, e a razao e sempre a mesma: sao
    # acoplamentos entre ficheiros, ou guardas, que **nenhuma execucao
    # distingue de uma coincidencia**. Vivem no
    # `db/tests/test_consumo_contrato.py` e no `test_dlq_reabertura.py`.
    ("consumo: a marca de consumo deixa de ser do tenant do envelope", EV_CONSUMO,
     "    await bd.query(SQL_DEFINIR_TENANT, [envelope.tenant_id, true]);\n",
     "", CONSUMO),
    ("consumo: um duplicado volta a aplicar o efeito", EV_CONSUMO,
     "    if ((marca.rowCount ?? 0) === 0) {",
     "    if ((marca.rowCount ?? 0) === -1) {", CONSUMO),
    ("consumo: «atrasado» passa a ser «adiantado»", EV_CONSUMO,
     "        const atrasado = ultimoSeq !== null && agregado.seq < ultimoSeq;",
     "        const atrasado = ultimoSeq !== null && agregado.seq > ultimoSeq;",
     CONSUMO),
    ("consumo: o agregado que nao existe passa a poder transitar", EV_CONSUMO,
     "      if (estado === null) {",
     "      if (estado === undefined) {", CONSUMO),
    ("trabalho: a ultima tentativa deixa de abrir a DLQ", EV_TRABALHO,
     "  const ultima = tentativa >= tentativasMaximas;",
     "  const ultima = tentativa > tentativasMaximas;", CONSUMO),
    ("trabalho: um fora_de_ordem passa a recuar pela escada", EV_TRABALHO,
     "    if (erro instanceof ForaDeOrdem) {",
     "    if (erro instanceof RangeError) {", CONSUMO),
    ("dlq: a entrada deixa de ter contexto de tenant", EV_DLQ,
     "    await bd.query(SQL_DEFINIR_TENANT, [tenantId, true]);\n",
     "", CONSUMO),
    ("trabalhador: um evento ilegivel deixa de abrir a DLQ", EV_TRABALHADOR,
     "            await paraDlqSemEnvelope({",
     "            await Promise.resolve({", CONSUMO),
    ("trabalhador: o evento que o arquivo nao tem deixa de ser adiado", EV_TRABALHADOR,
     "            if (!ultima) throw new Adiar(ADIAMENTO_POR_OMISSAO, erro.message);",
     "", CONSUMO),
    # ------------------------------------------------------------- KAM-012
    #
    # Cada uma desfaz uma propriedade que o ticket nomeia, e a que sobreviver
    # diz que essa propriedade nao tem teste.
    ("revisao 0006: a cadeia parte da genese errada", REV6,
     r'GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000000"',
     r'GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000001"'),
    ("revisao 0006: o separador do hash desaparece", REV6,
     '"|| chr(31) || p_tenant_id || chr(31) || "',
     '"|| p_tenant_id || "'),
    ("revisao 0006: o payload_hash sai do row_hash", REV6,
     '"encode(p_payload_hash, \'hex\')"',
     '"\'\'"'),
    ("revisao 0006: o trigger deixa de ser ALWAYS", REV6,
     '        "ALTER TABLE platform.audit_log "\n'
     '        "ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete"',
     '        "ALTER TABLE platform.audit_log "\n'
     '        "ENABLE TRIGGER audit_log_sem_update_nem_delete"'),
    ("revisao 0006: o audit_log deixa de ter trigger de UPDATE", REV6,
     "          BEFORE UPDATE OR DELETE ON platform.audit_log",
     "          BEFORE DELETE ON platform.audit_log"),
    ("revisao 0006: a aplicacao passa a ler o registo", REV6,
     'op.execute("GRANT SELECT ON platform.audit_log TO kamba_batch")',
     'op.execute("GRANT SELECT ON platform.audit_log TO kamba_batch, kamba_app")'),
    ("revisao 0006: o dominio de action ganha um valor", REV6,
     '"\'access.conversation\', \'batch.run\', \'breakglass.open\', \'audit.read\'"',
     '"\'access.conversation\', \'batch.run\', \'breakglass.open\', \'audit.read\', \'tudo\'"'),
    ("revisao 0006: o row_hash deixa de ser unico", REV6,
     "          CONSTRAINT audit_log_row_hash_uq UNIQUE (tenant_id, row_hash),",
     ""),
    # Esta substitui uma que **nao mudava comportamento nenhum**: a obvia
    # sobre o `criado_at` seria `NEW.criado_at := coalesce(NEW.criado_at,
    # now())`, e a coluna tem `DEFAULT now()`, pelo que o `NEW.criado_at`
    # nunca chega nulo. Era apanhada por qualquer teste e nao provava nada.
    # Esta alarga o `GRANT` a um papel que nao tem nada que escrever
    # auditoria, e e a matriz de privilegios que a tem de apanhar.
    ("revisao 0006: o resolvedor passa a escrever auditoria", REV6,
     '"ON platform.audit_log TO kamba_app"',
     '"ON platform.audit_log TO kamba_app, kamba_resolver"'),
    ("revisao 0006: o chamador volta a escolher os hashes", REV6,
     "          NEW.prev_hash := v_prev;",
     "          NEW.prev_hash := coalesce(NEW.prev_hash, v_prev);"),
    ("revisao 0006: o texto deixa de ter tecto", REV6,
     "            length(actor_id) <= {TECTO_DE_TEXTO}",
     "            length(actor_id) <= 1000000"),
    ("auditoria: o verificador deixa de ver o elo partido", AUDITORIA,
     "            if prev_hash != anterior:",
     "            if False:"),
    ("auditoria: o verificador deixa de recalcular o hash", AUDITORIA,
     "            if calculado != guardado:",
     "            if False:"),
    ("auditoria: o verificador deixa de olhar para a cabeca", AUDITORIA,
     "        elif declarada != anterior:",
     "        elif False:"),
    ("auditoria: a ancora volta a depender do fuso da sessao", AUDITORIA,
     '" WHERE a.criado_at < ((%s::date + 1)::timestamp AT TIME ZONE \'UTC\') "',
     '" WHERE a.criado_at < (%s::date + 1) "'),
    ("auditoria: o criado_at sai do hash", AUDITORIA,
     "        iso_utc(criado_at),",
     "        '',"),
    ("auditoria: o verificador deixa de comparar com a ancora", AUDITORIA,
     "    achados.extend(_contra_a_ancora(por_cadeia, ancora))",
     "    achados.extend([])"),
    ("revisao 0005: a unicidade da DLQ deixa de ser parcial", REV5,
     "        CREATE UNIQUE INDEX events_dlq_aberta_uq\n          ON platform.events_dlq (consumer, event_id)\n          WHERE estado = 'aberta'\n",
     "        CREATE UNIQUE INDEX events_dlq_aberta_uq\n          ON platform.events_dlq (consumer, event_id)\n"),
    ("filas: o worker volta a usar a ligacao que desiste", EV_TRABALHADOR,
     "  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_ESPERA });",
     "  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_FALHA_DEPRESSA });"),
    ("accoes: o once deixa de recusar a transaccao de quem o chama", EV_ACCOES,
     "  await exigirForaDeTransaccao(bd, chave);\n",
     ""),
    ("reconciliador: o evento reposto perde o tenant", EV_RECON,
     "        tenant_id: linha.tenant_id,\n",
     "", CONSUMO),
    ("revisao 0005: a retencao aceita uma janela menor que a re-entrega", REV5,
     "          IF p_dias < 7 THEN",
     "          IF p_dias < 1 THEN", CONSUMO),
    ("revisao 0005: a retencao da DLQ apaga entradas abertas", REV5,
     "          DELETE FROM platform.events_dlq\n"
     "            WHERE estado <> 'aberta'\n",
     "          DELETE FROM platform.events_dlq\n"
     "            WHERE true\n", CONSUMO),
    # Esta e das tres que a suite com fila **nao** apanha, e e por isso que o
    # `db/tests/test_consumo_contrato.py` existe: com o relogio acelerado a
    # escada do publicador e a do worker dao tempos parecidos, e com a escada
    # real o teste custava 756 s. O acoplamento le-se como texto.
    # ------------------------------------------------------------- KAM-007
    #
    # O gate 7. As quatro primeiras mordem no classificador de diferencas, que
    # e o que impede um contrato de partir sem versao nova; as duas seguintes
    # no lint de PII; a ultima no proprio contrato, para a bateria nao estar a
    # provar so a logica.
    ("contratos: o que o classificador nao le passa a ser aprovado", CD_DIFF,
     "    for chave in sorted(desconhecidas):",
     "    for chave in sorted(set()):", CONTRATOS),
    ("contratos: alargar um enum deixa de quebrar", CD_DIFF,
     "        if d - a:",
     "        if False:", CONTRATOS),
    ("contratos: tornar um campo obrigatorio deixa de quebrar", CD_DIFF,
     "    for nome in sorted(obrig_actual - obrig_base):",
     "    for nome in sorted(set()):", CONTRATOS),
    ("contratos: abrir o payload deixa de quebrar", CD_DIFF,
     '    if base.get("additionalProperties") != actual.get("additionalProperties"):',
     "    if False:", CONTRATOS),
    ("contratos: o lint de PII perde o nome mais obvio", CD_PII,
     'PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")',
     'PROIBIDOS = ("msisdn", "bsuid", "nome", "morada", "texto", "email")', CONTRATOS),
    ("contratos: o lint de PII volta a procurar por subcadeia", CD_PII,
     "    partes = set(segmentos(nome))",
     "    partes = {nome.lower()}", CONTRATOS),
    ("contratos: o gerador aceita o que nao sabe traduzir", CD_GERAR,
     "    if desconhecidas:",
     "    if False:", CONTRATOS),
    # As dez que seguem nasceram da revisao adversarial do KAM-007. Cada uma
    # desfaz exactamente um achado, e so passa a lista se o teste que o fechou
    # a apanhar — e a forma de saber que a correccao tem prova e nao so codigo.
    ("contratos: o lint de PII volta a deixar passar o plural", CD_PII,
     '        if raiz in partes or raiz + "s" in partes:',
     "        if raiz in partes:", CONTRATOS),
    ("contratos: o lint de PII volta a saber so os sete do 7.3", CD_PII,
     "RAIZES = PROIBIDOS + TAMBEM_PROIBIDOS",
     "RAIZES = PROIBIDOS", CONTRATOS),
    ("contratos: o lint de PII deixa de descer pelo que nao conhece", CD_PII,
     "        for chave, filho in no.items():",
     "        for chave, filho in {}.items():", CONTRATOS),
    ("contratos: o classificador volta a rebentar em vez de falhar fechado", CD_DIFF,
     "    except (TypeError, AttributeError, ValueError, RecursionError) as erro:",
     "    except KeyboardInterrupt as erro:", CONTRATOS),
    ("contratos: um required sobre campo nao declarado volta ao silencio", CD_DIFF,
     '            porque = ("passou a obrigatorio e nao esta em `properties`: o schema e "',
     '            continue  # mutacao\n            porque = ("", ', CONTRATOS),
    ("contratos: um exemplo com PII P2 deixa de ser achado", CD_EXEMPLOS,
     '        if exemplo.get("classe_pii") == "P2":',
     "        if False:", CONTRATOS),
    ("contratos: o gerador volta a declarar tudo opcional em Python", CD_GERAR,
     '                anotacao = f"NotRequired[{anotacao}]"',
     "                pass", CONTRATOS),
    ("contratos: o validador Python deixa de ver o campo a mais", CD_GERAR,
     "    se_sobra = sorted(set(payload) - permitidos)",
     "    se_sobra = []", CONTRATOS),
    ("contratos: um contrato volta a admitir PII P2", CONTRATO_PAY_MANUAL,
     '"classe_pii": {' + chr(10) + '      "type": "string",' + chr(10) + '      "enum": [' + chr(10) + '        "P0"' + chr(10) + '      ]',
     '"classe_pii": {' + chr(10) + '      "type": "string",' + chr(10) + '      "enum": [' + chr(10) + '        "P0",' + chr(10) + '        "P2"' + chr(10) + '      ]',
     CONTRATOS),
    ("contratos: os dois pagamentos voltam a ser indistinguiveis", CONTRATO_PAY_MANUAL,
     '"enum": [' + chr(10) + '                "manual"' + chr(10) + '              ]',
     '"enum": [' + chr(10) + '                "manual",' + chr(10) + '                "hmac"' + chr(10) + '              ]',
     CONTRATOS),
    ("contratos: um payload deixa de ser fechado", CONTRATO_ORDER_PAID,
     '"payload": {' + chr(10) + '      "type": "object",' + chr(10) + '      "additionalProperties": false,',
     '"payload": {' + chr(10) + '      "type": "object",' + chr(10) + '      "additionalProperties": true,',
     CONTRATOS),
    ("filas: o job deixa de pedir a escada do consumidor", EV_FILAS,
     'backoff: { type: "custom" },',
     'backoff: { type: "exponential", delay: REPETICAO.atraso },'),
    # ------------------------------------------------------------- KAM-009
    #
    # A regra de consumo de limites (`platform.ten_consumir`, revisao 0007).
    # Quase todas correm contra `tests_ten`, que e a suite que prova a
    # **funcao**. Uma corre contra `tests_isolamento`: as duas tabelas tem
    # `tenant_id` e o catalogo do gate 6 descobre-as sozinho, e a mutacao que
    # tira a RLS a uma delas e a prova de que esse catalogo morde nas tabelas
    # novas. A gemea — a RLS do contador — fica em `tests_ten`, para que a
    # suite da funcao tambem a apanhe: ela le o contador de outro tenant.
    #
    # Cada uma desfaz uma propriedade que a revisao escreve por extenso na
    # sua docstring. Uma que sobreviva diz que essa propriedade nao tem teste.
    #
    # **As onze ultimas sao da revisao adversarial**, e cada uma repoe
    # exactamente o defeito que ela mediu. Sao a resposta a pergunta que a
    # reprovacao deixou: «porque e que 47 testes e 15 mutacoes nao apanharam
    # tres criticos?» — porque nenhuma mutacao os escrevia.
    ("revisao 0007: a ordem das duas insercoes trocada", REV7,
     _TEN_ORDEM, _TEN_ORDEM_TROCADA, TEN),
    ("revisao 0007: o registo da chave sai da subtransaccao", REV7,
     "  BEGIN\n"
     "    INSERT INTO platform.usage_ledger\n"
     "                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)\n"
     "         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);\n"
     "\n"
     "    IF p_quantidade > v_limite THEN",
     _TEN_CHAVE_FORA, TEN),
    ("revisao 0007: o ultimo que cabe no tecto passa a ser recusado", REV7,
     "     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite",
     "     WHERE platform.tenant_usage.valor + p_quantidade < v_limite", TEN),
    ("revisao 0007: o tecto de quem chama passa a subir", REV7,
     "    v_limite := least(v_limite, p_limite);",
     "    v_limite := greatest(v_limite, p_limite);", TEN),
    ("revisao 0007: o tecto passa a ser o maximo entre modulos", REV7,
     "  SELECT min(CASE WHEN d.legivel THEN d.texto::bigint END),",
     "  SELECT max(CASE WHEN d.legivel THEN d.texto::bigint END),", TEN),
    ("revisao 0007: sem entitlement passa a aceitar", REV7,
     "    RETURN QUERY SELECT false, 0::bigint, false, NULL::bigint;",
     "    RETURN QUERY SELECT true, 0::bigint, false, NULL::bigint;", TEN),
    ("revisao 0007: um entitlement inactivo passa a contar", REV7,
     "         AND e.ativo\n", "", TEN),
    ("revisao 0007: a quantidade nao positiva deixa de levantar", REV7,
     "  IF p_quantidade IS NULL OR p_quantidade <= 0 THEN",
     "  IF false THEN", TEN),
    ("revisao 0007: o periodo passa a ser em UTC", REV7,
     "SELECT date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')::date",
     "SELECT date_trunc('month', p_agora AT TIME ZONE 'UTC')::date", TEN),
    ("revisao 0007: a funcao passa por cima da RLS", REV7,
     "RETURNS TABLE (aceite boolean, valor bigint, repetido boolean, limite bigint)\n"
     "LANGUAGE plpgsql\nSECURITY INVOKER",
     "RETURNS TABLE (aceite boolean, valor bigint, repetido boolean, limite bigint)\n"
     "LANGUAGE plpgsql\nSECURITY DEFINER", TEN),
    ("revisao 0007: o contador fica sem RLS", REV7,
     '    rls.enable_tenant_rls("tenant_usage")\n', "", TEN),
    ("revisao 0007: o livro fica sem RLS (gate 6)", REV7,
     '    rls.enable_tenant_rls("usage_ledger")\n', "", ISOLAMENTO),
    ("revisao 0007: o downgrade nao repoe o UPDATE em entitlements", REV7,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n',
     "", TEN),
    ("revisao 0007: o downgrade repoe a lista de colunas sem o plano", REV7,
     "COLUNAS_DA_0001 = (\n"
     '    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "\n'
     '    "plano, estado, medusa_sales_channel_id, medusa_merchant_id, "\n',
     "COLUNAS_DA_0001 = (\n"
     '    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "\n'
     '    "estado, medusa_sales_channel_id, medusa_merchant_id, "\n',
     TEN),
    # ------------------------------------- KAM-009, revisao adversarial
    #
    # C1: a chave de idempotencia solta do pedido que identifica. Duas
    # mutacoes porque sao duas propriedades independentes — o ambito da chave
    # e a quantidade — e cada uma sozinha deixava passar metade do ataque.
    ("revisao 0007: a chave de idempotencia atravessa chaves de limite", REV7,
     "          PRIMARY KEY (tenant_id, chave_limite, idempotency_key)",
     "          PRIMARY KEY (tenant_id, idempotency_key)", TEN),
    ("revisao 0007: a repeticao deixa de comparar a quantidade", REV7,
     _TEN_QUANTIDADE, "", TEN),
    ("revisao 0007: a chave de idempotencia passa a ser global", REV7,
     "          PRIMARY KEY (tenant_id, chave_limite, idempotency_key)\n",
     "          PRIMARY KEY (chave_limite, idempotency_key)\n", TEN),
    # C2: `kamba_app` volta a poder criar o proprio entitlement.
    ("revisao 0007: a aplicacao volta a inserir entitlements", REV7,
     'op.execute("REVOKE INSERT, UPDATE ON platform.entitlements FROM kamba_app")',
     'op.execute("REVOKE UPDATE ON platform.entitlements FROM kamba_app")', TEN),
    # C3: o contador volta a poder descer. Tres caminhos: sem trigger, com o
    # trigger a nao verificar nada, e com o trigger a nao disparar fora da
    # sessao normal.
    ("revisao 0007: o contador deixa de ter trigger", REV7, _TEN_TRIGGER, "", TEN),
    ("revisao 0007: o contador volta a poder descer", REV7,
     "  IF NEW.valor < OLD.valor THEN", "  IF false THEN", TEN),
    ("revisao 0007: o trigger do contador deixa de ser ALWAYS", REV7,
     '"ALTER TABLE platform.tenant_usage ENABLE ALWAYS TRIGGER tenant_usage_so_sobe"',
     '"ALTER TABLE platform.tenant_usage ENABLE TRIGGER tenant_usage_so_sobe"', TEN),
    ("revisao 0007: a chave de uma linha de uso passa a poder mudar", REV7,
     "  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id", "  IF false", TEN),
    # M1: o relogio nas maos de quem corre como a aplicacao.
    ("revisao 0007: a aplicacao volta a poder fixar o relogio", REV7,
     _TEN_RELOGIO, "", TEN),
    # M6: o tenant volta a poder retirar a condicao do criterio 2.
    ("revisao 0007: a aplicacao volta a alterar o proprio estado", REV7,
     '    "medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "\n'
     '    "litellm_key_id, fuso_horario, verificado_at, deleted_at"\n'
     ")",
     '    "estado, medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "\n'
     '    "litellm_key_id, fuso_horario, verificado_at, deleted_at"\n'
     ")",
     TEN),
    # m1/m2: um tecto que nao se sabe ler, e a soma que transborda.
    ("revisao 0007: um limite ilegivel volta a abortar a transaccao", REV7,
     "  SELECT min(CASE WHEN d.legivel THEN d.texto::bigint END),",
     "  SELECT min(d.texto::bigint),", TEN),
    ("revisao 0007: o tecto ilegivel deixa de ser nomeado", REV7,
     "  IF coalesce(v_ilegivel, false) THEN", "  IF false THEN", TEN),
    # **Esta substitui uma que sobreviveu.** A primeira versao punha a soma
    # do contador em `numeric` contra o transbordo, e a mutacao que a
    # devolvia a `bigint` **nao morreu**: com o tecto limitado a dezoito
    # algarismos, `valor + quantidade` nunca passa de 2 x 10^18 e o `bigint`
    # vai ate 9,2 x 10^18. O cast era defesa sobre uma porta ja fechada,
    # saiu, e a mutacao passou a morder na guarda que fecha mesmo: o tecto
    # de algarismos de um limite.
    ("revisao 0007: o tecto deixa de ter limite de algarismos", REV7,
     "              AND length(e.limites ->> p_chave) <= 18) AS legivel",
     "              AND length(e.limites ->> p_chave) <= 30) AS legivel", TEN),
    # m3: o aviso da ordem das chaves, que so existe no `COMMENT`.
    ("revisao 0007: o aviso da ordem das chaves desaparece", REV7,
     "    op.execute(_COMENTARIO_DA_CONSUMIR)\n", "", TEN),
    # m4: a chave de idempotencia vazia.
    ("revisao 0007: a chave de idempotencia vazia deixa de levantar", REV7,
     _TEN_CHAVE_VAZIA, "", TEN),
    # ----------------------------------------------------------- KAM-014
    #
    # O CHR e o sitio onde o `tenant_id` nasce, e por isso as mutacoes mordem
    # nas duas metades da pergunta: o que a **base** impede (a RLS, as FK
    # compostas, os privilegios por coluna, o dominio do motivo, a unicidade da
    # conversa) e o que o **codigo** impede (a cache que nao serve uma entrada
    # expirada, o estado que nao se adivinha, a ordem dos passos, o `wamid` que
    # nao sai em claro).
    #
    # Cada uma escolhe a suite mais **estreita** que a apanha: a `tests_chr`
    # corre o modulo contra os tres papeis e e onde quase todas caem; a
    # `tests_isolamento` apanha a que tira a politica, porque e o X-05 que
    # nomeia a tabela; a `tests` apanha as que mexem nas FK e nas restricoes,
    # que o inventario fechado enumera; a `tests_entrada` apanha o dominio do
    # motivo, porque e la que as tres fontes se comparam.
    #
    # A forma `if (x && false)` em vez de `if (false)`: tem o mesmo efeito e
    # nao e codigo inalcancavel declarado, que o `tsc` recusaria se alguem
    # corresse o `typecheck` sobre a copia.
    #
    # **A primeira e a mutacao de um defeito que existiu.** Com a politica de
    # pe, o dono da tabela conta zero linhas sobre uma tabela cheia, e o
    # `downgrade` apaga as conversas em silencio em vez de pedir a copia logica.
    # Era o que a primeira versao da revisao fazia, e foi o
    # `test_conversas_schema.py` que o apanhou — a mesma armadilha que o
    # `docs/isolamento.md` §6 escreve para a validacao de uma FK nova.
    # ------------------------------------------------- KAM-015, revisao 0010
    #
    # Cada uma nomeia a propriedade que se perde. As quatro primeiras sao as
    # divergencias que a emenda 1.21 assumiu: se uma mutacao que as desfaz
    # sobrevive, a divergencia estava escrita e nao estava protegida.
    ('revisao 0010: a chave de idempotencia passa a ser global', REV10,
     '            CONSTRAINT outbound_messages_idempotency_uq\n                UNIQUE (tenant_id, idempotency_key),',
     '            CONSTRAINT outbound_messages_idempotency_uq\n                UNIQUE (idempotency_key),', SAIDA),
    ('revisao 0010: a FK da conversa deixa de levar o tenant', REV10,
     '            CONSTRAINT outbound_messages_conversation_fk\n                FOREIGN KEY (tenant_id, conversation_id)\n                REFERENCES platform.conversations (tenant_id, id),',
     '            CONSTRAINT outbound_messages_conversation_fk\n                FOREIGN KEY (conversation_id)\n                REFERENCES platform.conversations (id),', "tests"),
    ('revisao 0010: a FK do canal deixa de levar o tenant', REV10,
     '            CONSTRAINT outbound_messages_channel_fk\n                FOREIGN KEY (tenant_id, channel_id)\n                REFERENCES platform.tenant_channels (tenant_id, id),',
     '            CONSTRAINT outbound_messages_channel_fk\n                FOREIGN KEY (channel_id)\n                REFERENCES platform.tenant_channels (id),', "tests"),
    ('revisao 0010: a mensagem de saida fica sem RLS (gate 6)', REV10,
     '    rls.enable_tenant_rls("outbound_messages")\n',
     '', ISOLAMENTO),
    ('revisao 0010: o template fica sem RLS (gate 6)', REV10,
     '    rls.enable_tenant_rls("message_templates")\n',
     '', ISOLAMENTO),
    # O defeito que a `0009` pagou, repetido aqui de proposito: com `FORCE`, o
    # dono esta sujeito a politica e uma migracao corre sem contexto, logo
    # contar antes de desligar ve zero linhas e apaga em silencio.
    ('revisao 0010: o downgrade conta os envios com a politica de pe', REV10,
     '    rls.disable_tenant_rls("outbound_messages")\n    rls.disable_tenant_rls("message_templates")\n\n    envios = _contar_envios()',
     '    envios = _contar_envios()\n    rls.disable_tenant_rls("outbound_messages")\n    rls.disable_tenant_rls("message_templates")\n', "tests"),
    ('revisao 0010: a aplicacao passa a poder reescrever a chave de idempotencia', REV10,
     'COLUNAS_DA_APLICACAO = (\n    "state",',
     'COLUNAS_DA_APLICACAO = (\n    "idempotency_key",\n    "state",', SAIDA),
    ('revisao 0010: a aplicacao passa a poder inserir templates', REV10,
     'op.execute("GRANT SELECT ON platform.message_templates TO kamba_app")',
     'op.execute("GRANT SELECT, INSERT ON platform.message_templates TO kamba_app")', ISOLAMENTO),
    ('revisao 0010: o estado de saida perde o suppressed_by_human', REV10,
     '    "\'failed\'",\n    "\'suppressed_by_human\'",\n)',
     '    "\'failed\'",\n)', "tests"),
    ('revisao 0010: um instante de entrega passa a caber em qualquer estado', REV10,
     '            CONSTRAINT outbound_messages_entrega_ck',
     '            CONSTRAINT outbound_messages_entrega_sem_regra_ck', "tests"),
    ('revisao 0010: uma utility passa a poder ir sem template', REV10,
     '            CONSTRAINT outbound_messages_template_ck',
     '            CONSTRAINT outbound_messages_template_sem_regra_ck', "tests"),
    ('revisao 0010: a conversa perde a unicidade que a FK precisa', REV10,
     '        "ADD CONSTRAINT conversations_tenant_id_uq UNIQUE (tenant_id, id)"',
     '        "ADD CONSTRAINT conversations_tenant_id_uq UNIQUE (id)"', "tests"),
    # ------------------------------------------- KAM-015, o modulo de saida
    ('saida: a monotonia deixa de proteger os terminais', SAIDA_ESTADOS,
     '  if (terminal(actual)) {\n    return { estado: actual, avancou: false, entregou: false };\n  }',
     '  if (false) {\n    return { estado: actual, avancou: false, entregou: false };\n  }', SAIDA),
    ('saida: a entrega passa a contar-se ao chegar e nao ao atravessar', SAIDA_ESTADOS,
     '  const entregou = de < ordemDoDelivered && para >= ordemDoDelivered;',
     '  const entregou = para === ordemDoDelivered;', SAIDA),
    ('saida: o ON CONFLICT da idempotencia desaparece', SAIDA_SQL,
     '      ON CONFLICT (tenant_id, idempotency_key) DO NOTHING',
     '', SAIDA),
    ('saida: o avanco de estado deixa de ter a monotonia no predicado', SAIDA_SQL,
     '     AND state = ANY($4::text[])',
     '', SAIDA),
    ('saida: o bloqueio de template deixa de preservar o primeiro instante', SAIDA_SQL,
     '   WHERE tenant_id = $1 AND name = $2 AND lang = $3 AND bloqueado_em IS NULL',
     '   WHERE tenant_id = $1 AND name = $2 AND lang = $3', SAIDA),
    ('saida: o balde do canal volta a nascer cheio', SAIDA_LIMITES,
     'const canal = this.#balde(this.#porCanal, phoneNumberId, this.#mps, agoraMs, false);',
     'const canal = this.#balde(this.#porCanal, phoneNumberId, this.#mps, agoraMs, true);',
     SAIDA),
    ('saida: o 131049 passa a repetir-se', SAIDA_LIMITES,
     'export const CODIGOS_QUE_SE_REPETEM: readonly number[] = [',
     'export const CODIGOS_QUE_SE_REPETEM: readonly number[] = [\n  131049,',
     SAIDA),
    ('saida: o jitter passa a poder dar zero', SAIDA_LIMITES,
     '  return Math.round(base / 2 + (base / 2) * aleatorio);',
     '  return Math.round(base * aleatorio);', SAIDA),
    ('saida: a tarifa de marketing passa a ser a de utility', SAIDA_TARIFAS,
     '  marketing: 22_500,',
     '  marketing: 4_000,', SAIDA),
    ('saida: uma categoria desconhecida passa a custar o de service', SAIDA_TARIFAS,
     '  return tarifa === undefined ? 0 : tarifa;',
     '  return tarifa === undefined ? 4_000 : tarifa;', SAIDA),
    ('saida: a forma deixa de se verificar antes da janela', SAIDA_DECISAO,
     '  const forma = formaInvalida(corpo);\n  if (forma !== null) return { enviar: false, motivo: forma };',
     '', SAIDA),
    ('saida: um template bloqueado passa a poder ser usado', SAIDA_DECISAO,
     '  if (template.bloqueadoEm !== null) return { enviar: false, motivo: "TEMPLATE_BLOCKED" };',
     '', SAIDA),
    # As tres abaixo sao das correccoes que o ensaio do adapter (gate 4) e o do
    # esquema (suite `tests`) apanharam: cada uma volta o codigo ao defeito
    # medido, para que deixar de o apanhar seja uma sobrevivente e nao silencio.
    ('saida: o token bucket deixa de pedir em ciclo', SAIDA_ADAPTER,
     '      if (espera === 0) break;',
     '      if (espera === 0) break;\n      if (true) { await this.#dormir(espera); break; }', SAIDA),
    ('saida: as repeticoes do 130429 passam a ser duas', SAIDA_LIMITES,
     'export const REPETICOES = 3;', 'export const REPETICOES = 2;', SAIDA),
    ('revisao 0010: o instante de entrega deixa de caber nos terminais', REV10,
     "                       OR state IN ('delivered', 'read', 'failed',\n                                    'suppressed_by_human')),",
     "                       OR state IN ('delivered', 'read')),", "tests"),
    ('saida: a janela fechada deixa de recusar o envio livre', SAIDA_DECISAO,
     '      return { enviar: false, motivo: WINDOW_CLOSED };',
     '      return { enviar: true, kind: "service", templateName: null };', SAIDA),
    ('revisao 0009: o downgrade conta as conversas com a politica de pe', REV9,
     '    rls.disable_tenant_rls("conversations")\n    quantas = _contar()',
     '    quantas = _contar()\n    rls.disable_tenant_rls("conversations")',
     "tests"),
    ('revisao 0009: a conversa fica sem RLS (gate 6)', REV9,
     '    rls.enable_tenant_rls("conversations")\n',
     '', ISOLAMENTO),
    ('revisao 0009: a FK do canal deixa de levar o tenant', REV9,
     '                FOREIGN KEY (tenant_id, channel_id)\n                REFERENCES platform.tenant_channels (tenant_id, id),',
     '                FOREIGN KEY (channel_id)\n                REFERENCES platform.tenant_channels (id),', "tests"),
    ('revisao 0009: a FK do contacto deixa de levar o tenant', REV9,
     '                FOREIGN KEY (tenant_id, contact_id)\n                REFERENCES platform.contacts (tenant_id, contact_id),',
     '                FOREIGN KEY (contact_id)\n                REFERENCES platform.contacts (contact_id),', "tests"),
    ('revisao 0009: a unicidade da conversa perde o canal', REV9,
     '                UNIQUE (tenant_id, contact_id, channel_id)',
     '                UNIQUE (tenant_id, contact_id)', CHR),
    ('revisao 0009: a aplicacao passa a poder mudar o modo', REV9,
     'COLUNAS_DA_APLICACAO = ("last_inbound_at", "window_expires_at")',
     'COLUNAS_DA_APLICACAO = ("last_inbound_at", "window_expires_at", "mode")', CHR),
    ('revisao 0009: a janela deixa de ter de ser coerente', REV9,
     '            CONSTRAINT conversations_janela_ck',
     '            CONSTRAINT conversations_janela_sem_regra_ck', "tests"),
    # Os dois motivos do encaminhamento escolhem a `tests_chr` e **nao** a
    # `tests_entrada`, que seria o sitio onde as tres fontes do dominio se
    # comparam: a suite de entrada lanca os processos de producao do GWY e do
    # *worker*, e a copia da prova por mutacao nao leva `services/` nem o
    # `package.json` da raiz — nenhuma mutacao a pode escolher hoje (divida
    # registada). A `tests_chr` apanha-as de forma mais directa: sem o valor no
    # `CHECK`, a insercao da quarentena do CHR falha e o criterio 2 fica
    # vermelho contra o `CHECK` verdadeiro.
    ('revisao 0008: o motivo do canal desconhecido sai do dominio', REV8,
     '    "\'canal_desconhecido\'",\n',
     '', CHR),
    ('revisao 0008: o motivo da mensagem sem identidade sai do dominio', REV8,
     '    "\'mensagem_sem_identidade\'",\n',
     '', CHR),
    ('chr: a entrada expirada fica a servir de resposta', CHR_CANAL,
     '      // Expirou: sai antes de se ir à base, para que uma falha da base não\n      // deixe uma entrada velha a servir de resposta.\n      this.#esquecer(phoneNumberId);',
     '      // Expirou.', CHR),
    ('chr: um estado de canal desconhecido passa a ser aceite', CHR_CANAL,
     '  if (!ESTADOS_DE_CANAL.includes(estadoCanal)) {\n    throw new CanalIlegivelError("estado_canal");\n  }\n',
     '', CHR),
    ('chr: a guarda do Fluxo B deixa de ver a vertical', CHR_FLUXO_B,
     '  if (!permitidas.includes(contexto.vertical)) {',
     '  if (permitidas.includes(contexto.vertical)) {', CHR),
    ('chr: a guarda de arranque deixa de provar que ve tudo', CHR_FLUXO_B,
     '  const visivel = await cliente.query(SQL_VISIBILIDADE, []);\n  if (visivel.rows[0]?.ve_tudo !== true) throw new GuardaCegaError();\n',
     '', CHR),
    ('chr: o Fluxo B deixa de recusar e segue para a matriz', CHR_MODULO,
     '    if (recusa !== null) {',
     '    if (recusa === null && false) {', CHR),
    ('chr: uma conversa fora do modo bot volta a ir ao AGR', CHR_MODULO,
     '    if (conversa.mode !== MODO_POR_OMISSAO) {',
     '    if (conversa.mode === MODO_POR_OMISSAO && false) {', CHR),
    ('chr: a matriz deixa de poder negar o registo da conversa', CHR_MODULO,
     '    if (!registar.permitido) {',
     '    if (registar.permitido && false) {', CHR),
    ('chr: a matriz deixa de poder negar o processamento', CHR_MODULO,
     '    if (!processar.permitido) {',
     '    if (processar.permitido && false) {', CHR),
    ('chr: a mensagem sem identidade volta a fazer o job repetir', CHR_MODULO,
     '    if (\n      interlocutor === null ||\n      (interlocutor.bsuid === null && interlocutor.telefone === null)\n    ) {',
     '    if (interlocutor === null) {', CHR),
    ('chr: o echo volta a poder ir ao AGR', CHR_MODULO,
     '    if (evento.kind === "echo") {',
     '    if (evento.kind === "echo" && false) {', CHR),
    ('chr: o modo desconhecido passa a ser tratado como conhecido', CHR_CONVERSAS,
     '  if (typeof mode !== "string" || !MODOS_CONHECIDOS.includes(mode)) {',
     '  if (typeof mode !== "string" && !MODOS_CONHECIDOS.includes(mode)) {', CHR),
    ('chr: a fusao reaponta sempre, e nunca dobra os tempos', CHR_CONVERSAS,
     '    if (typeof idPara !== "string") {',
     '    if (true) {', CHR),
    ('chr: o jobId passa a levar o wamid em claro', CHR_INVOCACAO,
     '  return createHash("sha256").update(`${tenantId}:${wamid}`, "utf8").digest("hex");',
     '  return `${tenantId}:${wamid}`;', CHR),
    ('chr: o SQL do canal deixa de filtrar pelo phone_number_id', CHR_SQL,
     '   WHERE c.phone_number_id = $1\n',
     '   WHERE $1 IS NOT NULL\n', CHR),
    ('chr: o SQL da conversa deixa de empurrar a janela', CHR_SQL,
     '     SET last_inbound_at   = EXCLUDED.last_inbound_at,\n         window_expires_at = EXCLUDED.window_expires_at\n',
     '     SET last_inbound_at   = platform.conversations.last_inbound_at,\n         window_expires_at = platform.conversations.window_expires_at\n', CHR),
]


#: O que a copia leva. `tools/kamba_yaml.py` e `ci/` nao sao codigo de `db/`,
#: mas a suite de isolamento le deles as listas de excepcoes.
def _recusar_importacao_por_pacote() -> None:
    """Recusa se um teste de `core-ts` importar o pacote por especificador.

    A copia leva o `dist` do `core-ts` (sem ele, o `meta-sim` nao carrega), e um
    `dist` na copia e uma segunda fonte do mesmo codigo: um teste que importasse
    `@kamba/core-ts/<modulo>` lia a construcao e nao a fonte mutada, e a prova
    dava «apanhada» sem nada ter sido apanhado. Esta guarda e o que torna a
    razao escrita em `_copiar` verificavel em vez de uma intencao.

    A convencao da casa ja e importar por caminho relativo nos testes, e e esta
    a razao — a mesma que fez a cobertura de `src/outbound/` cair em `dist/` na
    primeira versao do KAM-015.
    """
    achados: list[str] = []
    for pasta in ("tests", "tests_bd"):
        raiz = RAIZ / "packages" / "core-ts" / pasta
        if not raiz.is_dir():
            continue
        for ficheiro in sorted(raiz.rglob("*.ts")):
            texto = ficheiro.read_text(encoding="utf-8")
            if '"@kamba/core-ts' in texto or "'@kamba/core-ts" in texto:
                achados.append(str(ficheiro.relative_to(RAIZ)).replace("\\", "/"))
    if achados:
        raise SystemExit(
            "a prova por mutacao nao pode correr: estes testes importam "
            "`@kamba/core-ts` por especificador, e a copia leva o `dist` — a "
            "mutacao aplicar-se-ia a fonte e o teste leria a construcao:\n  "
            + "\n  ".join(achados)
            + "\nImporte por caminho relativo (`../src/<modulo>/index.ts`)."
        )


def _copiar(destino: Path, suite: str = "tests") -> None:
    ignorar = shutil.ignore_patterns("__pycache__")
    if suite in SUITES_DE_TOOLS:
        # As baterias de `tools/` nao abrem `db/`, `libs/py-core` nem
        # `packages/core-ts`: cada mutacao do gate 9 pagava megabytes de copia
        # para nada, e sao 25 mutacoes.
        #
        # Cada suite de `tools/` leva o **seu** minimo, e nao o de outra: levar
        # a copia do gate 9 para a suite das contagens dava a linha de base
        # vermelha, e uma mutacao «apanhada» sobre isso nao significa nada.
        COPIA_DE_TOOLS[suite](destino, ignorar)
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
    # **E o `packages/contracts`, com o `dist` (KAM-014).** Os `node_modules`
    # chegam por `--volume` da arvore real, e a ligacao de *workspace* do pnpm e
    # relativa: `packages/core-ts/node_modules/@kamba/contracts` aponta para
    # `../../contracts`, que se resolve **dentro da copia**. Sem esta pasta,
    # qualquer teste que importe `@kamba/contracts` rebenta com
    # `ERR_MODULE_NOT_FOUND` — e e isso que a linha de base da suite `tests_chr`
    # dizia, porque o `chr/eventos.ts` valida o payload pelo catalogo de
    # contratos antes de o emitir.
    #
    # Leva o `dist` e nao so a fonte: e importado como **pacote**, pelo
    # `exports` do seu `package.json`, e nao por caminho relativo.
    shutil.copytree(
        RAIZ / "packages" / "contracts", destino / "packages" / "contracts",
        ignore=shutil.ignore_patterns("node_modules"),
    )
    # O dicionario exportado: a suite de entrada compara o dominio de `kind` e
    # de `motivo` com **tres** fontes, e uma delas e este ficheiro.
    shutil.copytree(RAIZ / "canon", destino / "canon", ignore=ignorar)
    # **O `tools/meta-sim` e o `config/` (KAM-015)**, e os dois pela regra
    # escrita mais abaixo: uma mutacao nova sobre uma suite que os abre obriga a
    # acrescenta-los aqui.
    #
    # O simulador vai sem `dist`, ao contrario do `packages/contracts`: o seu
    # `exports` aponta para `./src/index.ts` e nao para uma pasta construida. Os
    # `node_modules` chegam por `--volume` da arvore real, como os dos outros.
    # Sem esta pasta, o `import { GraphFalso } from "@kamba/meta-sim"` do ensaio
    # da saida rebenta com `ERR_MODULE_NOT_FOUND` — a ligacao de *workspace* e
    # relativa e resolve-se **dentro da copia**.
    #
    # O `config/meta_rates.yaml` e a outra fonte das tarifas, e a suite
    # `tests_outbound` compara-a com as constantes de `tarifas.ts`: sem ele, o
    # `setUpClass` do `TestTarifas` levanta e a linha de base fica vermelha —
    # isto e, nenhuma mutacao da suite se pode provar. Medido ao correr a
    # primeira.
    shutil.copytree(
        RAIZ / "tools" / "meta-sim", destino / "tools" / "meta-sim",
        ignore=shutil.ignore_patterns("node_modules", "dist", "__pycache__"),
    )
    # **E o `dist/entrada` do `core-ts`, e so ele.** O `meta-sim` importa
    # `@kamba/core-ts/entrada` como **pacote** (tres ficheiros seus leem de la os
    # nomes de campo e os `wa_type`, em vez de os reescrever), e o `exports` do
    # `core-ts` aponta esse subcaminho para `dist/entrada/index.js`. Sem esta
    # pasta, o `import { GraphFalso }` morre com `ERR_MODULE_NOT_FOUND` —
    # medido, e e o que a linha de base da suite `tests_outbound` dizia.
    #
    # **O `dist` inteiro e nao so o `dist/entrada`**: o `dist/entrada/registo.js`
    # importa o `dist/logger/index.js`, e uma construcao e um grafo — recortar
    # uma pasta dele da `ERR_MODULE_NOT_FOUND` na seguinte (medido, nesta ordem).
    #
    # **E um `dist` na copia podia mascarar uma mutacao**: se um teste importasse
    # `@kamba/core-ts/<modulo>` em vez de `../src/<modulo>/index.ts`, a mutacao
    # aplicava-se a fonte, o teste lia a construcao antiga, e a prova dizia
    # «apanhada» sem nada ter sido apanhado. Por isso **confere-se**, em vez de
    # se confiar: a guarda abaixo recusa a copia se algum teste de `core-ts`
    # importar o pacote por especificador. Hoje nenhum o faz — todos importam
    # por caminho relativo, que e a convencao da casa precisamente por isto.
    _recusar_importacao_por_pacote()
    dist = RAIZ / "packages" / "core-ts" / "dist"
    if dist.is_dir():
        shutil.copytree(dist, destino / "packages" / "core-ts" / "dist")
    shutil.copytree(RAIZ / "config", destino / "config", ignore=ignorar)
    # E o que a **lista inteira** precisa de encontrar, mesmo que esta suite nao
    # o corra: o `tests/test_mutacoes.py` corre `--aplicaveis` sobre a lista real
    # **de dentro da copia**, e um ficheiro que falte conta como mutacao nao
    # aplicavel. Sem isto, as 24 entradas do KAM-131 (`tools/scan_secrets`, o
    # `ci.yaml` e o `Makefile`) davam a linha de base vermelha em **todas** as
    # mutacoes da suite `tests` — isto e, nenhuma se podia correr. Encontrado
    # ao correr as do KAM-005; sao poucos kilobytes.
    shutil.copytree(
        RAIZ / "tools" / "scan_secrets", destino / "tools" / "scan_secrets",
        ignore=ignorar,
    )
    # **E aconteceu outra vez, duas vezes.** O KAM-158 acrescentou quatro
    # mutacoes sobre `tools/lint_contagens` e o KAM-007 dezassete sobre
    # `tools/contract_diff` e `contratos/`, e nenhum dos dois estendeu esta
    # copia. Resultado: `aplicaveis()` dava **22** nao aplicaveis de dentro da
    # copia, a linha de base da suite `tests` ficava vermelha, e com ela
    # **nenhuma mutacao desta suite se podia provar** — a prova dizia «a copia
    # sem mutacao nao corre verde» e parava. Descoberto ao correr as do
    # KAM-012.
    #
    # A regra, escrita para a proxima vez: **uma mutacao nova sobre um ficheiro
    # que esta copia nao leva obriga a acrescenta-lo aqui**, mesmo que a suite
    # dela seja outra.
    shutil.copytree(
        RAIZ / "tools" / "lint_contagens", destino / "tools" / "lint_contagens",
        ignore=ignorar,
    )
    shutil.copytree(
        RAIZ / "tools" / "contract_diff", destino / "tools" / "contract_diff",
        ignore=ignorar,
    )
    shutil.copytree(RAIZ / "contratos", destino / "contratos", ignore=ignorar)
    (destino / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(
        RAIZ / ".github" / "workflows" / "ci.yaml",
        destino / ".github" / "workflows" / "ci.yaml",
    )
    shutil.copy(RAIZ / "Makefile", destino / "Makefile")


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


def _copiar_para_os_contratos(destino: Path, ignorar) -> None:
    """O que as mutacoes do gate 7 precisam, e so isso (KAM-007).

    Leva o pacote, o `tools/kamba_yaml.py` (o `pii` le a lista aprovada por
    ele), a lista aprovada, e **os contratos**: o `test_catalogo_e_cli.py`
    corre sobre os trinta e oito ficheiros reais, e nao sobre schemas
    inventados — uma logica certa com um catalogo que nao carrega nao serve.
    """
    shutil.copytree(
        RAIZ / "tools" / "contract_diff", destino / "tools" / "contract_diff",
        ignore=ignorar,
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    shutil.copytree(RAIZ / "contratos", destino / "contratos", ignore=ignorar)
    (destino / "ci").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "ci" / "contratos-allow.yaml", destino / "ci" / "contratos-allow.yaml")
    # E o `docs/tecnica/06`, que e a **fonte** do criterio 1: desde a revisao
    # adversarial (achado M4) o catalogo e verificado contra a tabela do §5 e
    # nao contra o numero 38. Sem o documento, essa bateria nem carrega.
    (destino / "docs" / "tecnica").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "docs" / "tecnica" / "06_Dados_Eventos_Analytics.md",
        destino / "docs" / "tecnica" / "06_Dados_Eventos_Analytics.md",
    )


def _copiar_para_as_contagens(destino: Path, ignorar) -> None:
    """O que as mutacoes do `lint_contagens` precisam, e so isso (KAM-158).

    A bateria `test_scan.py` constroi as suas proprias arvores de prova em
    `TemporaryDirectory`, pelo que nao precisa do conjunto documental: leva o
    pacote e o `tools/kamba_yaml.py`, que o `cli` importa ao ser carregado.
    """
    shutil.copytree(
        RAIZ / "tools" / "lint_contagens", destino / "tools" / "lint_contagens",
        ignore=ignorar,
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")


#: Que copia cada suite de `tools/` leva. Uma suite nova sem entrada aqui falha
#: a dizer que falta — em vez de correr sobre a copia de outra.
COPIA_DE_TOOLS = {
    GATE9: _copiar_para_o_gate_9,
    GATE9_CI: _copiar_para_o_gate_9,
    CONTAGENS: _copiar_para_as_contagens,
    CONTRATOS: _copiar_para_os_contratos,
}


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

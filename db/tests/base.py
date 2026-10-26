"""Base comum dos testes do gate 8.

Estes testes sao **destrutivos**: fazem `downgrade base`, que apaga o schema
`platform`. Por isso ha um trinco, e ele nao e opcional:

    a base tem de se chamar exactamente `kamba_gate8`.

`db/gate_bd.py` cria uma base com esse nome num PostgreSQL descartavel. Apontar
estes testes a `kamba_platform` — por engano num `.env`, por uma variavel
herdada da shell — faz a suite recusar-se a correr em vez de apagar a base de
desenvolvimento.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import bootstrap
import ligacao

DB = Path(__file__).resolve().parents[1]
BASE_DESCARTAVEL = "kamba_gate8"

#: O que a revisao 0001 cria em `platform`.
TABELAS_0001 = ("entitlements", "tenant_channels", "tenants")

#: O que a revisao 0003 (KAM-008) acrescenta: identidade de contacto.
TABELAS_0003 = ("contact_deks", "contact_endpoints", "contacts", "hmac_key_versions")

#: O que a revisao 0004 (KAM-005) acrescenta: outbox, sequencia por agregado,
#: subscricoes e o arquivo de eventos. O `events_log_default` esta aqui porque
#: o `pg_tables` lista a particao (`relkind` 'r') ao lado da particionada
#: ('p'): sao duas linhas do catalogo, e a lista e do catalogo.
TABELAS_0004 = (
    "events_log",
    "events_log_default",
    "events_outbox",
    "evt_agregado_seq",
    "evt_subscricoes",
)

#: As quatro tabelas do consumo idempotente (KAM-006, revisao 0005).
TABELAS_0005 = (
    "events_consumed",
    "events_dlq",
    "evt_acoes",
    "evt_dlq_aprovacoes",
)

#: Tudo o que existe em `platform` em `head`, por ordem alfabetica. Lista
#: fechada: uma tabela a mais (encomendas, pagamentos, consumidores) e escopo de
#: outro ticket, e entra aqui pela mao de quem a criar.
#: O que a revisao 0006 (KAM-012) acrescenta: o registo de auditoria e a
#: cabeca da cadeia de hash de cada tenant.
TABELAS_0006 = ("audit_heads", "audit_log")

#: O que a revisao 0007 (KAM-009) acrescenta: o contador de uso por periodo e
#: o livro que torna o consumo idempotente.
TABELAS_0007 = ("tenant_usage", "usage_ledger")

#: O que a revisao 0008 (KAM-013) acrescenta: o registo dos webhooks da Meta
#: que chegaram, e a quarentena dos que nao se conseguiu encaminhar.
#:
#: Sao as duas unicas tabelas de `platform` **sem `tenant_id`** fora das de
#: referencia: o GWY e o endpoint unico da Meta e o tenant so nasce no CHR
#: (KAM-014). A revisao `0008` escreve a razao, e por isso tambem nao ha
#: entrada em `ci/rls_exceptions.yaml` — o teste X-05 descobre as tabelas a
#: isolar **pela coluna `tenant_id`**, que estas nao tem.
TABELAS_0008 = ("inbound_events", "unrouted_events")

#: O que a revisao 0009 (KAM-014) acrescenta: a conversa entre um contacto e um
#: canal.
#:
#: E a **primeira** tabela do caminho do webhook com `tenant_id` — o tenant
#: nasce no CHR, que corre depois da escrita das duas de cima —, e por isso a
#: primeira que o teste X-05 do gate 6 descobre pela coluna e a primeira com
#: politica `tenant_iso`.
TABELAS_0009 = ("conversations",)

#: O que a revisao 0010 (KAM-015) acrescenta: a saida de canal.
#:
#: Duas, e a ordem de criacao importa — a `outbound_messages` referencia a
#: `conversations` da `0009` e a `message_templates` nao referencia nenhuma das
#: duas. No `downgrade` cai a de envios primeiro, por isso.
TABELAS_0010 = ("message_templates", "outbound_messages")

#: O que a revisao 0011 (KAM-019) acrescenta: a passagem a humano.
#:
#: Duas, e a ordem de criacao importa — a `handoffs` referencia a
#: `conversations` da `0009` por FK composta, e a `handoff_accounts` nao
#: referencia nenhuma das duas. No `downgrade` caem pela ordem inversa da
#: criacao.
TABELAS_0011 = ("handoff_accounts", "handoffs")

#: O que a revisao 0012 (KAM-020) acrescenta: a midia recebida.
#:
#: Uma so, e referencia **tres** tabelas por FK: a `tenants` da `0001`, e a
#: `contacts` da `0003` e a `conversations` da `0009`, as duas por FK composta
#: com o `tenant_id`. **Nao e a tabela com mais FK do esquema** — a
#: `outbound_messages` da `0010` tem quatro —, e a primeira versao desta nota
#: dizia que era. A razao de serem tres e que uma linha dela so faz sentido
#: dentro de uma conversa de um contacto de uma PME.
TABELAS_0012 = ("media_assets",)

#: A `0013` nao criou tabela nenhuma: acrescentou duas colunas a
#: `tenant_channels`. Fica declarada vazia e nao omitida, para que quem contar
#: as revisoes aqui nao conclua que uma se perdeu.
TABELAS_0013: tuple[str, ...] = ()

#: KAM-021: o registo das transicoes de qualidade do canal.
TABELAS_0014 = ("channel_quality_log",)

#: KAM-022: a prova de consentimento e o texto do aviso.
#:
#: **Duas tabelas e uma vista**, e a vista **nao** entra aqui: a descoberta do
#: catalogo le `pg_class` com `relkind IN ('r', 'p')` e uma vista e `'v'`. Fica
#: dito porque e a primeira vista do esquema e porque quem conte as relacoes de
#: `platform` passa a encontrar uma a mais do que as tabelas desta tupla.
#:
#: A `consent_texts` nao tem `tenant_id` — e um texto juridico de plataforma e
#: nao dado de tenant —, pelo que **nao** entra no X-05 nem no
#: `ci/rls_exceptions.yaml`: o gate 6 pergunta por RLS as tabelas que tem a
#: coluna. Entra nesta tupla porque existe em `platform`.
TABELAS_0015 = ("consent_event", "consent_texts")

#: KAM-016: a tentativa de onboarding de canal pelo Embedded Signup v4.
#:
#: **E a `0017` e nao a `0016`**: o KAM-018 reclamou aquele numero e a
#: revisao dele chegou primeiro ao remoto. A razao esta no docstring da
#: propria revisao.
#:
#: Uma so, e **nao acrescenta coluna nenhuma a `tenant_channels`** — os tres
#: identificadores que o criterio 8 manda guardar (`waba_id`, `waac_id`,
#: `phone_number_id`) existem desde a `0001`, com o `token_ref`. Referencia duas
#: tabelas por FK: a `tenants` da `0001` e a propria `tenant_channels`, esta por
#: FK composta com o `tenant_id` — que assenta na `tenant_channels_tenant_id_uq`
#: que a `0009` acrescentou precisamente para isto.
TABELAS_0017 = ("channel_onboarding",)

#: KAM-017: o estado de coexistencia de um canal (revisao `0018`).
#:
#: Uma so, e **nao acrescenta coluna nenhuma a `tenant_channels`** — o
#: `coexistence_synced_at` e o `last_account_update_at` existem desde a `0001` e
#: nunca tiveram escritor; este ticket e o primeiro, e isso custa codigo e nao
#: DDL. Referencia duas tabelas por FK: a `tenants` da `0001` e a propria
#: `tenant_channels`, esta por FK composta com o `tenant_id` — que assenta na
#: `tenant_channels_tenant_id_uq` que a `0009` acrescentou para isto.
TABELAS_0018 = ("channel_coexistence",)

#: KAM-115: o contacto alternativo do dono e o registo dos avisos (revisao `0019`).
#:
#: **Duas, e e a primeira revisao do epic a criar duas tabelas de negocio.** Sao
#: duas e nao uma porque o criterio 7 manda marcar o **contacto** como invalido
#: quando uma entrega falha: com uma tabela so, a invalidacao vivia na ultima
#: linha de aviso e a pergunta «este dono tem contacto valido?» passava a ser uma
#: consulta sobre o historico de envios em vez de um facto.
#:
#: As duas referenciam **so** a `tenants` da `0001`, e nenhuma aponta para a
#: outra — e por isso que a ordem entre elas e arbitraria. Nenhuma toca em
#: `tenant_channels`: o aviso e do **dono** e nao do canal, e o canal identifica-se
#: no `episodio`, que e texto opaco.
TABELAS_0019 = ("owner_contacts", "owner_notices")

#: KAM-026: as duas tabelas do checkpointer (revisao `0020`).
#:
#: **Noutro esquema, e por isso numa constante propria.** Todas as tuplas acima
#: sao nomes de tabela do `platform` e o `TABELAS` junta-as sem qualificar; estas
#: vivem no `lg` e um nome solto misturado la dentro fazia o catalogo procura-las
#: no sitio errado. Quem as consome diz o esquema.
TABELAS_LG = ("checkpoint_writes", "checkpoints")

#: KAM-030: as do esquema `dat` (revisao `0023`). Constante propria pela mesma
#: razao do `TABELAS_LG`, acima — vivem noutro esquema e quem as consome diz
#: qual.
#:
#: **Sao duas e a segunda e uma particao.** A `llm_call_log_default` e a unica
#: que a revisao cria, e aparece no catalogo como tabela: o
#: `test_o_migrator_nao_e_dono_de_nada_fora_do_que_criou` conta-a, e o X-05 do
#: *gate* 6 exige-lhe RLS `FORCE` por si. As mensais nascem do *job* da
#: retencao (KAM-071) e **nao** entram aqui: esta lista e o que a cadeia de
#: revisoes cria.
TABELAS_DAT = ("llm_call_log", "llm_call_log_default")

#: A unica vista do esquema (KAM-022). Separada das tabelas porque a descoberta
#: do catalogo tambem as separa, e porque o `verificar_vistas` do
#: `db/tests_isolamento/catalogo.py` — que existe desde o KAM-004 — passa a ter
#: a primeira coisa para ver: `security_invoker = true`.
VISTAS = ("consent_actual",)

#: KAM-028: o registo de invocacoes da ToolLayer (revisao `0021`).
#:
#: **Uma tabela, no `platform` e nao no `lg`.** O `docs/tecnica/02` §6.4 poe-a
#: ao lado da `audit_log` e nao junto do *checkpointer*: e um registo de
#: auditoria da plataforma, lido por quem audita, e o papel que escreve o `lg`
#: nao tem `USAGE` no `platform` (KAM-026).
TABELAS_0021 = ("tool_audit",)

#: KAM-029: a barreira de idempotencia das tools de escrita (revisao `0022`).
#:
#: **Uma tabela, no `platform`, e ao contrario da `0021` nao e *append-only*.**
#: O protocolo do `docs/tecnica/02` §6.3 e `INSERT` com estado `em_curso` ->
#: executar -> `UPDATE` com o resultado, e um *trigger* de imutabilidade recusava
#: o segundo passo; o que a protege e o `UPDATE` concedido **por coluna**. E a
#: razao pela qual ela, ao contrario da `tool_audit`, tem receita de sementes no
#: `db/tests_isolamento/sementes.py`: apaga-se com `DELETE`.
TABELAS_0022 = ("tool_idempotency",)

TABELAS = tuple(
    sorted(
        TABELAS_0001 + TABELAS_0003 + TABELAS_0004 + TABELAS_0005
        + TABELAS_0006 + TABELAS_0007 + TABELAS_0008 + TABELAS_0009
        + TABELAS_0010 + TABELAS_0011 + TABELAS_0012 + TABELAS_0013
        + TABELAS_0014 + TABELAS_0015 + TABELAS_0017 + TABELAS_0018
        + TABELAS_0019 + TABELAS_0021 + TABELAS_0022
    )
)

#: O que existe em `platform` quando a base esta na revisao `0021`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0022` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0021 = tuple(sorted(set(TABELAS) - set(TABELAS_0022)))

#: O que existe em `platform` quando a base esta na revisao `0020`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0021` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla. **A `0020` e do KAM-026 e
#: nao cria tabela no `platform`** — cria o esquema `lg` e as duas de
#: `TABELAS_LG` —, pelo que o conjunto do `platform` na `0020` e o da `0019`.
TABELAS_ATE_0020 = tuple(sorted(set(TABELAS_ATE_0021) - set(TABELAS_0021)))

#: O que existe em `platform` quando a base esta na revisao `0018`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0019` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0018 = tuple(sorted(set(TABELAS_ATE_0020) - set(TABELAS_0019)))

#: O que existe em `platform` quando a base esta na revisao `0017`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0018` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0017 = tuple(sorted(set(TABELAS_ATE_0018) - set(TABELAS_0018)))

#: O que existe em `platform` quando a base esta na revisao `0016`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0017` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla. **A `0016` e do KAM-018 e
#: nao cria tabela nenhuma** — sao dois `GRANT UPDATE` por coluna —, pelo que o
#: conjunto de tabelas da `0016` e o da `0015`.
TABELAS_ATE_0016 = tuple(sorted(set(TABELAS_ATE_0017) - set(TABELAS_0017)))

#: O que existe em `platform` quando a base esta na revisao `0014`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0015` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0014 = tuple(sorted(set(TABELAS_ATE_0016) - set(TABELAS_0015)))

#: O que existe em `platform` quando a base esta na revisao `0013`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0014` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0013 = tuple(sorted(set(TABELAS_ATE_0014) - set(TABELAS_0014)))

#: O que existe em `platform` quando a base esta na revisao `0011`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0012` pode recusar (ha
#: objectos de midia e nao ha copia), e nesse caso a base fica aqui.
TABELAS_ATE_0011 = tuple(sorted(set(TABELAS_ATE_0013) - set(TABELAS_0012)))

#: O que existe em `platform` quando a base esta na revisao `0010`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0011` pode recusar (ha
#: passagens ou contas de atendimento e nao ha copia), e nesse caso a base fica
#: aqui. **Desde a `0012`, chegar aqui passa primeiro pela `0012`**, que desce e
#: **compromete** antes de a `0011` levantar — uma transaccao por revisao.
TABELAS_ATE_0010 = tuple(sorted(set(TABELAS_ATE_0011) - set(TABELAS_0011)))

#: O que existe em `platform` quando a base esta na revisao `0009`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0010` pode recusar (ha envios
#: ou templates e nao ha copia), e nesse caso a base fica aqui. **Desde a
#: `0011`, chegar aqui passa primeiro pela `0011`**, que desce e **compromete**
#: antes de a `0010` levantar — uma transaccao por revisao.
TABELAS_ATE_0009 = tuple(sorted(set(TABELAS_ATE_0010) - set(TABELAS_0010)))

#: O que existe em `platform` quando a base esta na revisao `0008`.
#:
#: Pela mesma razao do `TABELAS_ATE_0003` e do `TABELAS_ATE_0004`: o
#: `downgrade` da `0009` pode recusar (ha conversas e nao ha copia), e nesse
#: caso a base fica aqui.
TABELAS_ATE_0008 = tuple(sorted(set(TABELAS_ATE_0009) - set(TABELAS_0009)))

#: O que existe em `platform` quando a base esta na revisao `0004`.
#:
#: Pela mesma razao do `TABELAS_ATE_0003`, uma revisao a frente: um
#: `downgrade 0003` desce primeiro a 0004 (que confirma) e so depois tenta a
#: 0003. Se a 0003 recusar, a base fica em **0004** — e os testes que provam
#: essa recusa comparam com isto, nao com a cabeca.
TABELAS_ATE_0004 = tuple(sorted(TABELAS_0001 + TABELAS_0003 + TABELAS_0004))

#: O que existe em `platform` quando a base esta na revisao `0003`.
#:
#: Faz falta porque o Alembic corre **uma transaccao por revisao**
#: (`transaction_per_migration=True` em `migrations/env.py`): um `downgrade 0002`
#: a partir da cabeca desce a `0004` — que confirma — e so depois tenta a
#: `0003`. Se a `0003` recusar (tem linhas de identidade e nao ha copia), a base
#: fica em `0003`, nao em `head`. Os testes que provam essa recusa comparam com
#: esta lista, e nao com `TABELAS`.
TABELAS_ATE_0003 = tuple(sorted(TABELAS_0001 + TABELAS_0003))


def exigir_base_descartavel() -> None:
    base = os.environ.get("KAMBA_DB_NAME", "")
    # Igualdade e nao sufixo: com `endswith("_gate8")`, uma base chamada
    # `producao_gate8` passava o trinco.
    if base != BASE_DESCARTAVEL:
        raise unittest.SkipTest(
            f"KAMBA_DB_NAME={base!r} nao e {BASE_DESCARTAVEL!r}. Os testes do "
            "gate 8 apagam o schema `platform` e so correm contra a base "
            "descartavel que `python db/gate_bd.py` cria."
        )


def alembic_cli(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic pela linha de comandos, como o criterio de aceitacao diz.

    Um processo novo por chamada. E o que `test_migracao.TestCiclo` usa para o
    ciclo `upgrade -> downgrade -> upgrade` do criterio 1 do KAM-003; o resto
    da suite usa `alembic`, que faz o mesmo sem pagar o arranque do processo.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *argumentos],
        cwd=DB,
        capture_output=True,
        text=True,
    )


def alembic(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic **neste processo**, pela entrada da linha de comandos.

    `CommandLine` e a classe que o executavel `alembic` usa: o mesmo analisador
    de argumentos, a mesma leitura do `alembic.ini`, o mesmo `env.py`, as mesmas
    revisoes. O que nao se paga e o arranque de um interpretador e a importacao
    do SQLAlchemy em cada chamada — medido em Windows, oito a nove segundos por
    chamada, numa suite que faz dezenas. Devolve o mesmo que `alembic_cli`:
    codigo de saida, saida e erros, com o *traceback* de uma revisao que falhe
    nos erros. `TestCiclo` confere que os dois dizem o mesmo.

    A `Config` constroi-se aqui, e nao por `CommandLine.main`, so para lhe dar
    onde escrever: a omissao do seu `stdout` e o `sys.stdout` do momento em que
    o modulo foi importado, que um `redirect_stdout` ja nao apanha.
    """
    import contextlib
    import io
    import traceback

    from alembic.config import CommandLine, Config

    saida, erros = io.StringIO(), io.StringIO()
    codigo = 0
    comando = ["-c", "migrations/alembic.ini", *argumentos]
    with (
        contextlib.chdir(DB),
        contextlib.redirect_stdout(saida),
        contextlib.redirect_stderr(erros),
    ):
        try:
            linha = CommandLine(prog="alembic")
            opcoes = linha.parser.parse_args(comando)
            linha.run_cmd(
                Config(file_="migrations/alembic.ini", stdout=saida, cmd_opts=opcoes),
                opcoes,
            )
        except SystemExit as saiu:
            codigo = saiu.code if isinstance(saiu.code, int) else int(saiu.code is not None)
        except Exception:  # noqa: BLE001 — uma revisao que falha e um resultado, nao um erro do teste
            traceback.print_exc(file=erros)
            codigo = 1
    return subprocess.CompletedProcess(comando, codigo, saida.getvalue(), erros.getvalue())


def _exigir_sucesso(resultado: subprocess.CompletedProcess, argumentos: tuple) -> None:
    if resultado.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(argumentos)} falhou ({resultado.returncode}):\n"
            f"{resultado.stdout}\n{resultado.stderr}"
        )


def alembic_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic(*argumentos), argumentos)


def alembic_cli_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic_cli(*argumentos), argumentos)


def sqlstate(excepcao: BaseException) -> str:
    """O SQLSTATE de um erro do pg8000 (campo `C` da mensagem do servidor)."""
    for argumento in excepcao.args:
        if isinstance(argumento, dict) and "C" in argumento:
            return str(argumento["C"])
    return ""


#: SQLSTATE por nome, para os testes dizerem o que esperam e nao um numero.
VIOLACAO_DE_CHECK = "23514"
VIOLACAO_DE_UNICIDADE = "23505"
VIOLACAO_DE_FK = "23503"
VIOLACAO_DE_NOT_NULL = "23502"
PRIVILEGIO_INSUFICIENTE = "42501"


def revisao_de_cabeca() -> str:
    """A revisao mais alta de `migrations/versions/` (os ficheiros sao `NNNN_*.py`)."""
    return max(
        ficheiro.name[:4]
        for ficheiro in (DB / "migrations" / "versions").glob("[0-9][0-9][0-9][0-9]_*.py")
    )


def em_head() -> bool:
    """A base ja esta na revisao de cabeca? Sem lancar um processo do Alembic.

    Cada `alembic upgrade head` e um processo novo, e sao segundos — mesmo
    quando nao ha nada para fazer, que e o caso de quase todas as classes de
    teste. Pergunta-se a base em que revisao esta e so se chama o Alembic
    quando a resposta nao e a cabeca. Quem prova as migracoes em si
    (`test_migracao.TestCiclo`, `test_identidade_schema.TestDowngradeDa0003`)
    chama o Alembic sempre, e nao passa por aqui.
    """
    import pg8000.dbapi

    conexao = ligacao.ligar("admin")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT version_num FROM public.alembic_version")
        return [tuple(linha) for linha in cursor.fetchall()] == [(revisao_de_cabeca(),)]
    except pg8000.dbapi.DatabaseError:
        return False  # a tabela de versao ainda nao existe: base por migrar
    finally:
        conexao.close()


class ComBase(unittest.TestCase):
    """Garante papeis criados e o schema em `head` antes de cada classe."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self._conexoes = []

    def tearDown(self) -> None:
        for conexao in self._conexoes:
            try:
                conexao.rollback()
            finally:
                conexao.close()

    def ligar(self, identidade: str):
        """Ligacao que nunca faz `commit`: cada teste desfaz o que escreveu."""
        conexao = ligacao.ligar(identidade)
        self._conexoes.append(conexao)
        return conexao

    def consultar(self, sql: str, parametros: tuple = (), identidade: str = "admin"):
        cursor = self.ligar(identidade).cursor()
        cursor.execute(sql, parametros)
        # O pg8000 devolve listas; normaliza-se para tuplos, que se comparam
        # e entram em conjuntos.
        return [tuple(linha) for linha in cursor.fetchall()]

    def assertErroSql(self, esperado: str, cursor, sql: str, parametros: tuple = ()):
        """A instrucao tem de falhar, e com o SQLSTATE esperado.

        Corre dentro de um `SAVEPOINT`: um erro aborta a transaccao inteira no
        PostgreSQL, e sem ele o teste perdia o que ja tinha inserido (o tenant
        de que o caso negativo precisa) e nao podia continuar na mesma ligacao.
        """
        import pg8000.dbapi

        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(sql, parametros)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(
            sqlstate(capturado.exception),
            esperado,
            f"falhou, mas nao pela razao esperada: {capturado.exception}",
        )


#: Onde vivem as constantes de SQL do consumidor (KAM-006).
CONSULTAS_DO_CONSUMIDOR = (
    Path(__file__).resolve().parents[2]
    / "packages" / "core-ts" / "src" / "eventos" / "consultas_consumo.ts"
)


class ConsultaDoTypeScript:
    """Uma constante de SQL do TypeScript, pronta para o `pg8000`.

    Existe para que uma suite de base de dados exercite **o SQL do modulo** e
    nao uma copia dele: uma copia prova que a copia funciona.

    **O `pg8000` nao tem `$n`: tem `%s`, e liga-os pela ordem em que aparecem
    no texto.** O `SQL_FECHAR_ACCAO` escreve `SET estado = $2, resultado = $3
    ... WHERE idempotency_key = $1`, pelo que a troca ingenua de `$n` por `%s`
    muda o significado dos argumentos — e o PostgreSQL recusou, a primeira
    execucao desta classe, um `'feita'` onde esperava `jsonb`. Por isso guarda
    a **ordem** dos marcadores e reordena o que se lhe passa: quem chama
    escreve os argumentos pela numeracao do documento.
    """

    def __init__(self, nome: str, ficheiro: Path | None = None) -> None:
        caminho = CONSULTAS_DO_CONSUMIDOR if ficheiro is None else ficheiro
        texto = caminho.read_text(encoding="utf-8")
        achado = re.search(rf"export const {nome} = `(.*?)`;", texto, re.S)
        if achado is None:
            raise AssertionError(f"nao se encontrou {nome} em {caminho.name}")
        self.nome = nome
        self.fonte = achado.group(1)
        self.ordem = [int(n) for n in re.findall(r"\$(\d+)", self.fonte)]
        self.sql = re.sub(r"\$\d+", "%s", self.fonte)

    def args(self, *valores: object) -> tuple[object, ...]:
        """Os `valores` — na numeracao do documento — pela ordem do texto."""
        if sorted(self.ordem) != list(range(1, len(valores) + 1)):
            raise AssertionError(
                f"{self.nome} tem os marcadores {self.ordem} e deram-se "
                f"{len(valores)} argumentos"
            )
        return tuple(valores[n - 1] for n in self.ordem)

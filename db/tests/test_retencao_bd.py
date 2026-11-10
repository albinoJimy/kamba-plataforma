"""A revisao 0043 e o *job* de retencao contra a base (KAM-071).

As listas fechadas do *gate* 8 afirmam que a revisao **declarou** o que devia.
Esta bateria mede que o declarado **morde**, e que o *job* do
`kamba_core.retencao` faz contra o PostgreSQL o que os ensaios unitarios provam
sobre a base falsa.

## O *job* corre como `kamba_batch`, e nada fica na base

O *job* abre uma ligacao por unidade e confirma cada uma. Aqui as unidades
correm **dentro da transaccao do ensaio**: a `LigacaoDeEnsaio` abre um
`SAVEPOINT` e faz `SET ROLE kamba_batch` por unidade, o `commit` larga o
`SAVEPOINT` e o `rollback` volta a ele. Duas coisas saem disso, e as duas sao o
que se quer:

* os privilegios medidos sao os do `kamba_batch` — com o `BYPASSRLS` dele, que
  e o que faz do `tenant_id = %s` de cada instrucao a unica barreira entre dois
  tenants;
* o `tearDown` reverte tudo, incluindo as linhas de `audit_log` do hold e da
  sessao, que de outra forma ficavam na base para sempre (o *trigger*
  *append-only* recusa-as ao dono, e era a armadilha que o KAM-070 pagou).

## Os dois casos que tem de ficar vermelhos

* **Uma purga que apaga dados de outro tenant.** Dois tenants com linhas na
  janela, hold num deles: as dele ficam. E o canario do mesmo ensaio troca a
  instrucao por uma sem o `tenant_id` e exige que a fuga aconteca contra a base
  real — senao o ensaio podia estar verde por outra razao.
* **Um restauro que traz de volta o que a purga e o *erasure ledger* tiraram.**
  A linha purgada volta (com o `purge_log` a dizer que a janela correu), e a
  reaplicacao tira-a outra vez; o titular apagado depois da copia vem na lista.
"""

from __future__ import annotations

import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from kamba_core.retencao import hold, jobs, politica, purge_log  # noqa: E402

import particoes  # noqa: E402
from tests import factories  # noqa: E402
import ligacao  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0042,
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

PURGE_LOG = "platform.purge_log"
VALOR_INVALIDO = "22023"
AGORA = datetime.now(timezone.utc)


class LigacaoDeEnsaio:
    """Uma unidade do *job* com um papel, dentro da transaccao do ensaio."""

    autocommit = False

    def __init__(self, conexao, papel: str = "kamba_batch") -> None:
        self.conexao = conexao
        self.papel = papel

    def _executar(self, *instrucoes: str) -> None:
        cursor = self.conexao.cursor()
        for instrucao in instrucoes:
            cursor.execute(instrucao)

    def cursor(self):
        self._executar("SAVEPOINT unidade", f"SET ROLE {self.papel}")
        return self.conexao.cursor()

    def commit(self) -> None:
        self._executar("RESET ROLE", "RELEASE SAVEPOINT unidade")

    def rollback(self) -> None:
        self._executar("ROLLBACK TO SAVEPOINT unidade", "RELEASE SAVEPOINT unidade", "RESET ROLE")

    def close(self) -> None:
        pass


class ComRetencao(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()

    def tenant(self) -> str:
        return factories.tenant(self.cursor)

    def execucao(self, *classes: str, **kw) -> jobs.Execucao:
        kw.setdefault("politica", tuple(c for c in politica.POLITICA if c.nome in classes))
        kw.setdefault("agora", AGORA)
        return jobs.Execucao(abrir_ligacao=lambda: LigacaoDeEnsaio(self.conexao), **kw)

    def consumido(self, tenant: str, dias: int) -> None:
        self.cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq, "
            " processado_at) VALUES ('retencao.ensaio', %s, %s, 'order', 'agg', 1, "
            " now() - make_interval(days => %s))",
            (str(uuid.uuid4()), tenant, dias),
        )

    def consumidos(self, tenant: str) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.events_consumed WHERE tenant_id = %s", (tenant,)
        )
        return self.cursor.fetchone()[0]

    def hold_no_tenant(self, tenant: str) -> None:
        hold.aplicar(self.cursor, tenant_id=tenant, contact_id=None, actor_type="staff",
                     actor_id="ensaio", motivo_ref="processo-de-ensaio")

    def linhas_do_log(self, execucao_id: str) -> list[tuple]:
        self.cursor.execute(
            f"SELECT classe, tabela, tenant_id::text, modo, resultado, motivo, linhas "
            f"FROM {PURGE_LOG} WHERE execucao_id = %s ORDER BY registado_at, tabela",
            (execucao_id,),
        )
        return [tuple(linha) for linha in self.cursor.fetchall()]


class TestOPurgeLog(ComRetencao):
    """Criterio 5: a linha sem conteudo, e *append-only* por privilegio."""

    def _registo(self, cursor, **kw):
        valores = dict(execucao_id=str(uuid.uuid4()), classe="events_outbox",
                       tabela="platform.events_outbox", tenant_id=None, modo="efectiva",
                       resultado="ok", motivo=None, linhas=1, objectos=0,
                       janela_ate=None, politica_versao="v", iniciado_at=AGORA)
        valores.update(kw)
        cursor.execute(purge_log.SQL_ESCREVER, tuple(valores.values()))

    def test_o_lote_escreve_e_nao_altera_nem_apaga(self) -> None:
        cursor = self.ligar("batch").cursor()
        self._registo(cursor)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"UPDATE {PURGE_LOG} SET linhas = 0")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"DELETE FROM {PURGE_LOG}")

    def test_a_aplicacao_nao_alcanca_a_tabela(self) -> None:
        cursor = self.ligar("app").cursor()
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"SELECT 1 FROM {PURGE_LOG}")

    def test_os_dominios_mordem(self) -> None:
        cursor = self.ligar("batch").cursor()
        for caso in (
            dict(motivo="erro"),                                # ok com motivo
            dict(resultado="recusada", motivo=None, linhas=0),  # recusa sem motivo
            dict(resultado="recusada", motivo="o joao", linhas=0),
            dict(resultado="falhou", motivo="erro", linhas=3),  # falhou que apagou
            dict(modo="talvez"),
            dict(tabela="platform.events_outbox; DROP"),
        ):
            with self.subTest(caso):
                cursor.execute("SAVEPOINT caso")
                try:
                    with self.assertRaises(Exception) as erro:
                        self._registo(cursor, **caso)
                finally:
                    cursor.execute("ROLLBACK TO SAVEPOINT caso")
                self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)

    def test_os_dominios_da_base_sao_os_do_modulo(self) -> None:
        """Duas superficies que dizem o mesmo: o `CHECK` e as tuplas do modulo."""
        for restricao, esperado in (
            ("purge_log_modo_ck", purge_log.MODOS),
            ("purge_log_resultado_ck", purge_log.RESULTADOS),
            ("purge_log_motivo_ck", purge_log.MOTIVOS),
        ):
            with self.subTest(restricao):
                self.cursor.execute(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
                    (restricao,),
                )
                definicao = self.cursor.fetchone()[0]
                self.assertEqual(tuple(re.findall(r"'([a-z_]+)'::text", definicao)), esperado)


class TestOHold(ComRetencao):
    """Criterio 6: o hold vive no `audit_log`, e o *job* le-o."""

    def test_aplicar_e_levantar_pela_aplicacao_e_o_lote_ve(self) -> None:
        """A aplicacao escreve (tem `EXECUTE` no `audit_append`) e o lote le."""
        tenant = self.tenant()
        contacto = factories.contacto(self.cursor, tenant)
        self.cursor.execute("SET ROLE kamba_app")
        factories.contexto(self.cursor, tenant)
        hold.aplicar(self.cursor, tenant_id=tenant, contact_id=contacto, actor_type="staff",
                     actor_id="dpo", motivo_ref="proc-1")
        hold.aplicar(self.cursor, tenant_id=tenant, contact_id=None, actor_type="staff",
                     actor_id="dpo", motivo_ref="proc-2")
        hold.levantar(self.cursor, tenant_id=tenant, contact_id=None, actor_type="staff",
                      actor_id="dpo", motivo_ref="proc-2")
        self.cursor.execute("SET ROLE kamba_batch")
        holds = hold.ler(self.cursor)
        self.cursor.execute("RESET ROLE")
        self.assertNotIn(tenant, holds.tenants)
        self.assertEqual(holds.contactos_de(tenant), frozenset({contacto}))

    def test_o_motivo_nao_fica_em_claro(self) -> None:
        tenant = self.tenant()
        self.hold_no_tenant(tenant)
        self.cursor.execute(
            "SELECT count(*) FROM platform.audit_log WHERE tenant_id = %s "
            "AND action = 'retention.hold_aplicado' AND payload_hash = sha256('processo-de-ensaio')",
            (tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)


class TestAPurgaNaoSaiDoTenant(ComRetencao):
    """O primeiro caso que tem de ficar vermelho."""

    def _dois_tenants_com_hold_em_b(self):
        a, b = self.tenant(), self.tenant()
        for t in (a, b):
            self.consumido(t, 100)
            self.consumido(t, 10)
        self.hold_no_tenant(b)
        return a, b

    def test_a_purga_de_a_nao_toca_em_b(self) -> None:
        a, b = self._dois_tenants_com_hold_em_b()
        relatorio = jobs.executar(self.execucao("events_consumed"))
        self.assertEqual((self.consumidos(a), self.consumidos(b)), (1, 2))
        linhas = self.linhas_do_log(relatorio.execucao_id)
        self.assertIn(("events_consumed", "platform.events_consumed", a, "efectiva", "ok", None, 1), linhas)
        self.assertIn(("events_consumed", "platform.events_consumed", b, "efectiva", "retida", "hold_tenant", 0), linhas)
        self.assertFalse(relatorio.sev2)

    def test_canario_sem_o_tenant_a_fuga_acontece_na_base(self) -> None:
        a, b = self._dois_tenants_com_hold_em_b()
        sem_tenant = jobs.Caminho(
            "platform.events_consumed",
            jobs.CAMINHO_CONSUMIDOS.sql_tenants,
            "SELECT count(*) FROM platform.events_consumed WHERE processado_at < %s",
            "DELETE FROM platform.events_consumed WHERE processado_at < %s",
            global_=True,
        )
        with mock.patch.dict(jobs.CAMINHOS, {"events_consumed": (sem_tenant,)}):
            jobs.executar(self.execucao("events_consumed"))
        self.assertEqual(self.consumidos(b), 1, "o canario nao mordeu: o ensaio de cima nao mede nada")

    def test_o_dry_run_conta_e_nao_apaga(self) -> None:
        a = self.tenant()
        self.consumido(a, 100)
        relatorio = jobs.executar(self.execucao("events_consumed", dry_run=True))
        self.assertEqual(self.consumidos(a), 1)
        self.assertIn(("events_consumed", "platform.events_consumed", a, "dry_run", "ok", None, 1),
                      self.linhas_do_log(relatorio.execucao_id))

    def test_a_sessao_de_lote_fica_no_audit_log(self) -> None:
        """Criterio 8: o *job* usa o `kamba_batch` com sessao registada."""
        relatorio = jobs.executar(self.execucao("events_consumed"))
        self.cursor.execute(
            "SELECT actor_type, actor_id FROM platform.audit_log "
            "WHERE action = 'batch.run' AND entity = 'retencao' AND entity_id = %s",
            (relatorio.execucao_id,),
        )
        self.assertEqual([tuple(l) for l in self.cursor.fetchall()], [("system", jobs.ACTOR_DO_LOTE)])


class TestORestauro(ComRetencao):
    """O segundo caso que tem de ficar vermelho."""

    def test_o_que_volta_com_o_restauro_sai_outra_vez(self) -> None:
        a = self.tenant()
        self.consumido(a, 100)
        jobs.executar(self.execucao("events_consumed"))
        self.assertEqual(self.consumidos(a), 0)
        # O restauro logico: a linha volta, e o `purge_log` fica a dizer que a
        # janela ja correu.
        self.consumido(a, 100)
        contacto = factories.contacto(self.cursor, a)
        self.cursor.execute(
            "INSERT INTO platform.dsar_requests (tenant_id, contact_id, tipo, estado, "
            " papel_kamba, recebido_at, prazo_dias, prazo_interno_at) VALUES "
            "(%s, %s, 'eliminacao', 'em_curso', 'subcontratada', now() - interval '3 days', "
            " 30, now() + interval '27 days') RETURNING dsar_id",
            (a, contacto),
        )
        dsar = self.cursor.fetchone()[0]
        self.cursor.execute(
            "INSERT INTO platform.erasure_ledger (tenant_id, dsar_id, contact_id, escopo, "
            " aplicado_at) VALUES (%s, %s, %s, 'cofre', now() - interval '2 days')",
            (a, dsar, contacto),
        )
        relatorio, sujeitos = jobs.reaplicar_apos_restauro(
            self.execucao("events_consumed"), AGORA - timedelta(days=5)
        )
        self.assertEqual(self.consumidos(a), 0)
        self.assertEqual(relatorio.linhas("events_consumed"), 1)
        self.assertIn(contacto, [s.contact_id for s in sujeitos])


class TestAsParticoes(ComRetencao):
    """Criterio 7: `DROP` de particao e criacao de M+1 e M+2.

    O *job* decide como `kamba_batch` e o `db/particoes.py` faz o DDL como
    `kamba_migrator` — os dois papeis, cada um na sua unidade, dentro da
    transaccao do ensaio.
    """

    MES = date(2020, 1, 1)

    def setUp(self) -> None:
        super().setUp()
        self.gestor = particoes.GestorDeParticoes(
            lambda: LigacaoDeEnsaio(self.conexao, "kamba_migrator")
        )

    def _particao_com_linha(self, tenant: str) -> None:
        self.gestor.criar("platform.events_log", self.MES)
        self.cursor.execute(
            "INSERT INTO platform.events_log (event_id, tipo, versao, tenant_id, agregado_tipo, "
            " agregado_id, agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
            "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', 'agg', 1, "
            " timestamptz '2020-01-15 12:00Z', now(), 'P1', '{}'::jsonb)",
            (tenant,),
        )

    def _existe(self, nome: str) -> bool:
        self.cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (nome,))
        return self.cursor.fetchone()[0]

    def test_larga_o_mes_vencido_e_cria_os_dois_seguintes(self) -> None:
        self._particao_com_linha(self.tenant())
        self.cursor.execute("SELECT count(*) FROM platform.events_log_2020_01")
        self.assertEqual(self.cursor.fetchone()[0], 1, "a linha nao caiu na particao do mes")
        relatorio = jobs.executar(self.execucao("events_log", particoes=self.gestor))
        self.assertFalse(self._existe("platform.events_log_2020_01"))
        seguinte = jobs._primeiro_do_mes(AGORA, 2)
        self.assertTrue(self._existe(f"platform.events_log_{seguinte:%Y_%m}"))
        self.assertIn(("events_log", "platform.events_log_2020_01", None, "efectiva", "ok", None, 1),
                      self.linhas_do_log(relatorio.execucao_id))
        self.assertFalse(relatorio.sev2)

    def test_um_hold_retem_o_mes(self) -> None:
        tenant = self.tenant()
        self._particao_com_linha(tenant)
        self.hold_no_tenant(tenant)
        jobs.executar(self.execucao("events_log", particoes=self.gestor))
        self.assertTrue(self._existe("platform.events_log_2020_01"))

    def test_a_particao_nova_nasce_isolada_e_sem_privilegios(self) -> None:
        """As duas exigencias do `verificar_particoes` do X-05."""
        for tabela, nome in (("platform.events_log", "events_log_2020_01"),
                             ("dat.llm_call_log", "llm_call_log_2020_01")):
            with self.subTest(tabela):
                self.gestor.criar(tabela, self.MES)
                self.gestor.criar(tabela, self.MES)  # idempotente
                self.cursor.execute(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, c.relacl IS NULL, "
                    "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
                    "FROM pg_class c WHERE c.relname = %s", (nome,),
                )
                self.assertEqual(tuple(self.cursor.fetchone()), (True, True, True, 1))

    def test_a_particao_do_custo_herda_a_imutabilidade(self) -> None:
        self.gestor.criar("dat.llm_call_log", self.MES)
        self.cursor.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relname = 'llm_call_log_2020_01'"
        )
        self.assertGreaterEqual(self.cursor.fetchone()[0], 1)

    def test_o_gestor_recusa_o_que_nao_e_dele(self) -> None:
        este_mes = jobs._primeiro_do_mes(AGORA).date()
        casos = (
            lambda: self.gestor.largar("platform.events_log", este_mes),
            lambda: self.gestor.largar("platform.audit_log", self.MES),
            lambda: self.gestor.criar("platform.events_log", date(2020, 1, 2)),
        )
        for n, caso in enumerate(casos):
            with self.subTest(n), self.assertRaises(particoes.ParticaoRecusada):
                caso()

    def test_o_lote_nao_cria_particoes(self) -> None:
        """A posse do pai e do dono: o `kamba_batch` leva `42501`."""
        lote = particoes.GestorDeParticoes(lambda: LigacaoDeEnsaio(self.conexao))
        with self.assertRaises(Exception) as erro:
            lote.criar("platform.events_log", self.MES)
        self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)

    def test_o_prazo_do_gestor_e_o_da_politica(self) -> None:
        """Importado e nao repetido: a mesma referencia."""
        self.assertIs(particoes.politica, politica)


class TestAPoliticaInteiraCorreNaBase(ComRetencao):
    """Cada instrucao do *job* corre contra o esquema real com o `kamba_batch`.

    Os ensaios unitarios leem o texto; este prova que o texto e SQL valido, que
    as colunas existem e que o lote tem o privilegio — em dry-run e em efectiva,
    com o prazo fiscal definido para que as contagens fiscais corram tambem.
    """

    def test_dry_run_e_efectiva_sem_falhas(self) -> None:
        class Armazenamento:
            def delete(self, ctx, ref) -> None:
                pass

        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                relatorio = jobs.executar(self.execucao(
                    *(c.nome for c in politica.POLITICA), dry_run=dry_run,
                    anos_fiscais=5, storage=Armazenamento(),
                    delegados={"lg_checkpoints": lambda ligacao, agora: 0},
                    particoes=particoes.GestorDeParticoes(
                        lambda: LigacaoDeEnsaio(self.conexao, "kamba_migrator")),
                ))
                self.assertEqual(relatorio.falhas, [])

    def test_a_verificacao_do_audio_corre(self) -> None:
        alvo, maximo = jobs.verificar_audio(lambda: LigacaoDeEnsaio(self.conexao), AGORA)
        self.assertIsInstance(alvo + maximo, int)

    def test_o_fiscal_sem_prazo_apaga_zero(self) -> None:
        """Criterio 4, contra a base: nenhuma instrucao de escrita nas fiscais."""
        relatorio = jobs.executar(self.execucao("fiscal_encomendas", "fiscal_pagamentos"))
        self.assertEqual(relatorio.linhas(), 0)
        self.assertEqual({r.motivo for r in relatorio.registos}, {"fiscal_sem_prazo"})

    def test_o_catalogo_esta_todo_mapeado(self) -> None:
        """Criterio 2: toda a tabela dos esquemas da aplicacao tem classe ou razao.

        Le o catalogo e nao uma lista: uma tabela nova que ninguem declarou
        aparece aqui. As particoes mensais que o *job* cria sao do pai.
        """
        self.cursor.execute(
            "SELECT n.nspname || '.' || c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') "
            "AND (NOT c.relispartition OR right(c.relname, 8) = '_default') "
            "AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'public', 'pg_toast')"
        )
        catalogo = {linha[0] for linha in self.cursor.fetchall()}
        declaradas = set(politica.tabelas_mapeadas()) | set(politica.SEM_DADOS_PESSOAIS)
        self.assertEqual(sorted(catalogo - declaradas), [], "tabelas sem classe de retencao")
        self.assertEqual(sorted(declaradas - catalogo), [], "classes que apontam para o vazio")


class TestDowngradeDa0043(ComBase):
    """O `downgrade` desce um degrau e recusa-se quando perderia a prova.

    Repoe o `head` no `tearDown`, pela razao do `TestDowngradeDa0038`: a ordem
    dos modulos do `unittest` nao e uma garantia. Desce por `-1` e nao por
    numero: o degrau de baixo e o da fila, e a fila decide-o na integracao.
    """

    def tearDown(self) -> None:
        super().tearDown()
        if not em_head():
            alembic_ok("upgrade", "head")

    def _presentes(self) -> set[str]:
        return {nome for (nome,) in self.consultar(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'")}

    def test_desce_sobe_e_o_dominio_volta_as_nove(self) -> None:
        exigir_base_descartavel()
        alembic_ok("downgrade", "-1")
        self.assertEqual(self._presentes(), set(TABELAS_ATE_0042))
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'audit_log_action'")
        self.assertNotIn("retention.hold", definicao)
        self.assertEqual(definicao.count("::text"), 9)
        alembic_ok("upgrade", "head")
        self.assertEqual(self._presentes(), set(TABELAS))

    def test_com_linhas_de_purga_e_sem_copia_recusa(self) -> None:
        exigir_base_descartavel()
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                f"INSERT INTO {PURGE_LOG} (execucao_id, classe, tabela, modo, resultado, "
                " motivo, linhas, politica_versao, iniciado_at) VALUES "
                "(gen_random_uuid(), 'events_outbox', 'platform.events_outbox', "
                " 'efectiva', 'ok', NULL, 1, 'v', now())")
            conexao.commit()
            with mock.patch.dict("os.environ", {"KAMBA_DOWNGRADE_0043_COPIA": ""}):
                resultado = alembic("downgrade", "-1")
            self.assertNotEqual(resultado.returncode, 0)
            self.assertIn("KAMBA_DOWNGRADE_0043_COPIA", resultado.stderr + resultado.stdout)
            self.assertIn("purge_log", self._presentes())
        finally:
            cursor = conexao.cursor()
            cursor.execute(f"DELETE FROM {PURGE_LOG} WHERE politica_versao = 'v'")
            conexao.commit()
            conexao.close()

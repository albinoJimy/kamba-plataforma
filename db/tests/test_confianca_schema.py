"""A revisao da confianca gradual contra a base: trust_level (KAM-096).

O que so uma base prova, e por isso este ficheiro existe:

1. **Os dominios sao os do codigo**: o `motivo` contra o `MOTIVOS_DO_NIVEL` de
   `packages/core-ts/src/confianca/niveis.ts`, e a versao da configuracao
   (`config.ts`) cabe na forma do `CHECK`.
2. **Sem K1 nao ha nivel** (criterio 2): o *trigger* `trust_level_guardar`
   recusa o nascimento sem o K1 completo do tenant — o mesmo predicado do gate
   `kyc` do KAM-092.
3. **O nivel 2 nao se atribui no Piloto**, e o tecto e positivo e em `AOA`.
4. **Cada alteracao vai ao `audit_log`** (criterio 7): uma linha `trust.tecto`
   por mudanca, nenhuma quando o recalculo nao muda nada (DoD 2), o actor da
   linha, e o `desde` que so anda com o nivel.
5. **O SQL do modulo de TypeScript**, executado tal como esta escrito.
6. **Privilegios e RLS** (criterio 7, adversarial f): a aplicacao le so o tecto
   do seu tenant e nao escreve nada; o lote nao muda a chave; ninguem apaga.
7. **O `downgrade`.**

A barreira da cobranca mede-se em `db/tests_pagamentos/test_tecto_de_confianca.py`,
os pedidos entregues em `db/tests_encomendas/test_confianca_pedidos.py`, e a
concorrencia no limite do tecto em `db/tests_lote/test_confianca_concorrencia.py`
— a unica destas que faz *commit*, e por isso numa suite sem ensaios de descida.
"""

from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_kyc_schema import caso as novo_caso
from tests.test_kyc_schema import verificacao

RAIZ = Path(__file__).resolve().parents[2]
NIVEIS_TS = RAIZ / "packages" / "core-ts" / "src" / "confianca" / "niveis.ts"
CONFIG_TS = RAIZ / "packages" / "core-ts" / "src" / "confianca" / "config.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "confianca" / "sql.ts"
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_confianca_gradual.py"))

NIVEL = "platform.trust_level"
VERSAO = factories.VERSAO_DA_CONFIGURACAO_DE_ENSAIO


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _lista_ts(ficheiro: Path, nome: str) -> tuple[str, ...]:
    texto = ficheiro.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {ficheiro.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _dominio(cursor, restricao: str) -> tuple[str, ...]:
    cursor.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", (restricao,))
    return tuple(sorted(re.findall(r"'([a-z0-9_]+)'", cursor.fetchone()[0])))


def _papel(cursor, papel: str | None, tenant: str | None = None) -> None:
    """Muda de papel **na transaccao** e define o contexto de tenant."""
    cursor.execute("RESET ROLE" if papel is None else f"SET LOCAL ROLE {papel}")
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
    cursor.fetchone()


def definir(cursor, tenant: str, nivel: int, tecto: int, motivo: str = "k1_completo",
            actor: str = f"sistema:{VERSAO}") -> list:
    q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
    cursor.execute(q.sql, q.args(tenant, nivel, str(tecto), motivo, actor, VERSAO))
    return cursor.fetchall()


class ComConfianca(ComBase):
    """Uma ligacao de administrador que nunca faz `commit`; os papeis por `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()

    def tenant_com_k1(self) -> str:
        """Um tenant com caso de onboarding e o ultimo lote de verificacoes `k1_ok`."""
        tenant = factories.tenant(self.cur)
        caso, _ = novo_caso(self.cur, tenant_id=tenant, fase="activo")
        verificacao(self.cur, caso, tenant, resultado="k1_ok")
        return tenant

    def auditoria(self, tenant: str) -> list[tuple]:
        self.cur.execute(
            "SELECT actor_type, actor_id, entity, entity_id FROM platform.audit_log "
            "WHERE tenant_id = %s AND action = 'trust.tecto' ORDER BY id",
            (tenant,),
        )
        return [tuple(linha) for linha in self.cur.fetchall()]

    def linha(self, tenant: str) -> tuple:
        self.cur.execute(
            "SELECT nivel, tecto_pedido_minor, motivo, desde, alterado_em FROM platform.trust_level "
            "WHERE tenant_id = %s",
            (tenant,),
        )
        return tuple(self.cur.fetchone())


class TestDominios(ComConfianca):
    def test_o_motivo_e_o_do_codigo(self) -> None:
        self.assertEqual(_dominio(self.cur, "trust_level_motivo_ck"), tuple(sorted(_lista_ts(NIVEIS_TS, "MOTIVOS_DO_NIVEL"))))

    def test_a_versao_da_configuracao_cabe_no_check(self) -> None:
        achado = re.search(r'versao: "([^"]+)"', CONFIG_TS.read_text(encoding="utf-8"))
        assert achado is not None
        self.cur.execute("SELECT %s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}\\.[0-9]+$'", (achado.group(1),))
        self.assertTrue(self.cur.fetchone()[0])

    def test_o_nivel_2_existe_e_nao_se_atribui_no_piloto(self) -> None:
        tenant = self.tenant_com_k1()
        _papel(self.cur, "kamba_batch")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, nivel=2, tecto=50_000_000))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, nivel=3, tecto=50_000_000))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, tecto=0))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, currency="USD"))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, actor="dono:x"))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, *self._inserir(tenant, motivo="porque_sim"))

    def _inserir(self, tenant: str, nivel: int = 0, tecto: int = 5_000_000, currency: str = "AOA",
                 actor: str = "sistema:x", motivo: str = "k1_completo") -> tuple[str, tuple]:
        return (
            "INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, currency, motivo, "
            "actor, versao_config) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (tenant, nivel, tecto, currency, motivo, actor, VERSAO),
        )


class TestNascimento(ComConfianca):
    """Criterio 2: o tenant nasce no nivel 0 com o K1 completo, e sem ele nao nasce."""

    def test_sem_caso_de_onboarding_nao_ha_nivel(self) -> None:
        tenant = factories.tenant(self.cur)
        _papel(self.cur, "kamba_batch")
        q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, q.sql,
                           q.args(tenant, 0, "5000000", "k1_completo", "sistema:x", VERSAO))

    def test_com_o_ultimo_lote_por_decidir_nao_ha_nivel(self) -> None:
        tenant = factories.tenant(self.cur)
        caso, _ = novo_caso(self.cur, tenant_id=tenant)
        verificacao(self.cur, caso, tenant, resultado="k1_ok", doc_tipo="nif")
        verificacao(self.cur, caso, tenant, resultado="fila", doc_tipo="bi")
        _papel(self.cur, "kamba_batch")
        q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur, q.sql,
                           q.args(tenant, 0, "5000000", "k1_completo", "sistema:x", VERSAO))

    def test_com_o_k1_completo_nasce_e_o_sql_do_modulo_o_ve(self) -> None:
        tenant = self.tenant_com_k1()
        _papel(self.cur, "kamba_batch")
        q = ConsultaDoTypeScript("SQL_K1_COMPLETO", SQL_TS)
        self.cur.execute(q.sql, q.args(tenant))
        self.assertEqual(self.cur.fetchone()[0], True)
        self.assertEqual(len(definir(self.cur, tenant, 0, 5_000_000)), 1)
        q = ConsultaDoTypeScript("SQL_NIVEL_DO_TENANT", SQL_TS)
        self.cur.execute(q.sql, q.args(tenant))
        nivel, tecto, motivo, _ = self.cur.fetchone()
        self.assertEqual((nivel, tecto, motivo), (0, "5000000", "k1_completo"))

    def test_quem_escreve_nao_escolhe_as_datas(self) -> None:
        tenant = self.tenant_com_k1()
        _papel(self.cur, "kamba_batch")
        self.cur.execute(
            "INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, "
            "versao_config, desde, alterado_em) VALUES (%s, 0, 5000000, 'k1_completo', 'sistema:x', %s, "
            "'2020-01-01', '2020-01-01') RETURNING desde > now() - interval '1 minute'",
            (tenant, VERSAO),
        )
        self.assertTrue(self.cur.fetchone()[0])


class TestAuditoria(ComConfianca):
    """Criterio 6 e DoD 2: cada alteracao e auditada, e o recalculo repetido nao escreve."""

    def test_o_nascimento_e_cada_mudanca_pelo_lote_vao_ao_registo_e_a_repeticao_nao(self) -> None:
        tenant = self.tenant_com_k1()
        _papel(self.cur, "kamba_batch")
        self.assertEqual(len(definir(self.cur, tenant, 0, 5_000_000)), 1)
        self.assertEqual(len(definir(self.cur, tenant, 0, 5_000_000)), 0)
        self.assertEqual(len(definir(self.cur, tenant, 0, 5_000_000)), 0)
        _papel(self.cur, None)
        self.assertEqual(self.auditoria(tenant), [("system", f"sistema:{VERSAO}", "trust_level", tenant)])

        _papel(self.cur, "kamba_batch")
        self.assertEqual(len(definir(self.cur, tenant, 1, 15_000_000, "historico_independente")), 1)
        self.assertEqual(len(definir(self.cur, tenant, 0, 5_000_000, "disputa_aceite", "revisor:rev-7")), 1)
        _papel(self.cur, None)
        self.assertEqual(
            [a for a, *_ in self.auditoria(tenant)], ["system", "system", "staff"],
        )

    def test_o_desde_anda_com_o_nivel_e_nao_com_uma_recalibracao(self) -> None:
        tenant = self.tenant_com_k1()
        _papel(self.cur, "kamba_batch")
        definir(self.cur, tenant, 0, 5_000_000)
        _papel(self.cur, None)
        # Um `UPDATE` do administrador tambem passa pelo *trigger*, que repoe o
        # `desde`: para envelhecer a linha desliga-se o *trigger* nesta
        # transaccao, que nunca faz `commit`.
        self.cur.execute("ALTER TABLE platform.trust_level DISABLE TRIGGER trust_level_guardar")
        self.cur.execute("UPDATE platform.trust_level SET desde = now() - interval '9 days' WHERE tenant_id = %s",
                         (tenant,))
        self.cur.execute("ALTER TABLE platform.trust_level ENABLE ALWAYS TRIGGER trust_level_guardar")
        _, _, _, velho, _ = self.linha(tenant)
        _papel(self.cur, "kamba_batch")
        definir(self.cur, tenant, 0, 6_000_000, "recalibracao")
        _papel(self.cur, None)
        nivel, tecto, _, desde, _ = self.linha(tenant)
        self.assertEqual((nivel, tecto, desde), (0, 6_000_000, velho))
        _papel(self.cur, "kamba_batch")
        definir(self.cur, tenant, 1, 15_000_000, "historico_independente")
        _papel(self.cur, None)
        _, _, _, depois, _ = self.linha(tenant)
        self.assertGreater(depois, velho)

    def test_o_superutilizador_nasce_sem_registo_e_muda_com_registo(self) -> None:
        """A excepcao escrita na revisao: o nascimento pelo superutilizador nao se audita."""
        tenant = self.tenant_com_k1()
        factories.confianca(self.cur, tenant)
        self.assertEqual(self.auditoria(tenant), [])
        self.cur.execute("UPDATE platform.trust_level SET tecto_pedido_minor = 4000000, motivo = 'recalibracao' "
                         "WHERE tenant_id = %s", (tenant,))
        self.assertEqual(len(self.auditoria(tenant)), 1)


class TestPrivilegios(ComConfianca):
    """Criterio 6 e adversarial (f): o tenant nao muda o proprio tecto por via nenhuma."""

    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        self.cur.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                         "WHERE oid = 'platform.trust_level'::regclass")
        self.assertEqual(tuple(self.cur.fetchone()), (True, True))

    def test_a_aplicacao_nao_escreve_nem_le_o_motivo(self) -> None:
        tenant = self.tenant_com_k1()
        factories.confianca(self.cur, tenant)
        _papel(self.cur, "kamba_app", tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "UPDATE platform.trust_level SET tecto_pedido_minor = 999999999 WHERE tenant_id = %s",
                           (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, "
                           "versao_config) VALUES (%s, 1, 999999999, 'k1_completo', 'sistema:x', %s)",
                           (tenant, VERSAO))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "DELETE FROM platform.trust_level WHERE tenant_id = %s", (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "SELECT motivo FROM platform.trust_level WHERE tenant_id = %s", (tenant,))
        q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur, q.sql,
                           q.args(tenant, 1, "999999999", "k1_completo", "sistema:x", VERSAO))

    def test_o_lote_nao_muda_a_chave_nem_a_moeda_nem_apaga(self) -> None:
        tenant = self.tenant_com_k1()
        factories.confianca(self.cur, tenant)
        _papel(self.cur, "kamba_batch")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "UPDATE platform.trust_level SET tenant_id = gen_random_uuid() WHERE tenant_id = %s",
                           (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "UPDATE platform.trust_level SET currency = 'AOA' WHERE tenant_id = %s", (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "DELETE FROM platform.trust_level WHERE tenant_id = %s", (tenant,))


class TestIsolamento(ComConfianca):
    """O tecto de A nunca se le com o contexto de B (teste cruzado, ADR-015)."""

    def test_a_aplicacao_le_so_o_tecto_do_seu_tenant(self) -> None:
        a = self.tenant_com_k1()
        b = self.tenant_com_k1()
        factories.confianca(self.cur, a)
        factories.confianca(self.cur, b, nivel=1, tecto=15_000_000)
        q = ConsultaDoTypeScript("SQL_TECTO_DO_TENANT", SQL_TS)
        for contexto, alvo, esperado in ((a, a, [["5000000"]]), (b, a, []), (None, a, []), (b, b, [["15000000"]])):
            with self.subTest(contexto=contexto, alvo=alvo):
                _papel(self.cur, "kamba_app", contexto)
                self.cur.execute(q.sql, q.args(alvo))
                self.assertEqual([list(x) for x in self.cur.fetchall()], esperado)
                _papel(self.cur, None)


class TestFactosNegativos(ComConfianca):
    def test_o_sinal_alto_conta_pelo_criado_at_e_o_baixo_nao_conta(self) -> None:
        tenant = self.tenant_com_k1()
        self.cur.execute(
            "INSERT INTO platform.ts_signal (tenant_id, tipo, severidade, ref_evento, ocorrido_em) "
            "VALUES (%s, 'preco_anomalo', 'baixa', gen_random_uuid(), now() - interval '2 days')",
            (tenant,),
        )
        q = ConsultaDoTypeScript("SQL_FACTOS_NEGATIVOS", SQL_TS)
        _papel(self.cur, "kamba_batch")
        self.cur.execute(q.sql, q.args(tenant))
        self.assertEqual(list(self.cur.fetchone()), [None, None])
        _papel(self.cur, None)
        self.cur.execute(
            "INSERT INTO platform.ts_signal (tenant_id, tipo, severidade, ref_evento, ocorrido_em) "
            "VALUES (%s, 'auto_compra', 'alta', gen_random_uuid(), now() - interval '20 days') "
            "RETURNING criado_at",
            (tenant,),
        )
        criado = self.cur.fetchone()[0]
        _papel(self.cur, "kamba_batch")
        self.cur.execute(q.sql, q.args(tenant))
        disputa, sinal = self.cur.fetchone()
        self.assertIsNone(disputa)
        self.assertEqual(sinal, criado)


class TestDowngradeDaConfianca(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro. **A recusa por linhas `trust.tecto`
    nao se mede aqui**, pela razao do `test_downgrade_0046.py`: o registo e
    *append-only*, e um ensaio que a escrevesse deixava a base desta suite sem
    descida possivel. E o mesmo codigo da `0048`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> tuple[int, int, int, bool]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'trust_level'")
            tabelas = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN "
                      "('trust_level_guardar', 'trust_level_auditar', 'payment_charge_dentro_do_tecto')")
            funcoes = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'payment_charges_dentro_do_tecto'")
            gatilhos = int(c.fetchone()[0])
            c.execute("SELECT pg_get_constraintdef(oid) LIKE '%trust.tecto%' FROM pg_constraint "
                      "WHERE conname = 'audit_log_action'")
            accao = bool(c.fetchone()[0])
            return tabelas, funcoes, gatilhos, accao
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        self.assertEqual(self._objectos(), (1, 3, 1, True))
        alembic_ok("downgrade", _anterior())
        self.assertEqual(self._objectos(), (0, 0, 0, False))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), (1, 3, 1, True))


if __name__ == "__main__":
    unittest.main()

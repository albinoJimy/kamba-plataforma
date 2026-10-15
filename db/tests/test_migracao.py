"""Gate 8: as migracoes aplicam-se, revertem-se e voltam a aplicar-se.

Criterio de aceitacao 1 do KAM-003: «`alembic upgrade head` num PostgreSQL 18.6
vazio cria o schema; `downgrade base` deixa 0 objectos em `platform` (consulta
ao catalogo); o ciclo `upgrade -> downgrade -> upgrade` passa no gate 8.»
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    TABELAS,
    TABELAS_0001,
    ComBase,
    alembic,
    alembic_cli_ok,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)


def _objectos_em_platform(cursor) -> int:
    """Tudo o que o catalogo regista no schema: relacoes, tipos, funcoes."""
    cursor.execute(
        """
        SELECT (SELECT count(*) FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'platform')
             + (SELECT count(*) FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'platform')
             + (SELECT count(*) FROM pg_type t
                  JOIN pg_namespace n ON n.oid = t.typnamespace
                 WHERE n.nspname = 'platform')
        """
    )
    return int(cursor.fetchone()[0])


def _schema_existe(cursor) -> bool:
    cursor.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'platform'")
    return bool(cursor.fetchone()[0])


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestCiclo(unittest.TestCase):
    """Nao herda de `ComBase`: este teste controla ele proprio o estado."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        self.conexao.close()
        # Deixa a base em `head` para as outras classes, seja qual for a ordem.
        # So chama o Alembic se o teste a tirou de la: cada chamada e um
        # processo novo, e a maior parte dos testes desta classe nao desce.
        if not em_head():
            alembic_ok("upgrade", "head")

    def test_upgrade_downgrade_upgrade(self) -> None:
        """O criterio 1, a letra: `alembic`, pela linha de comandos, num processo novo."""
        alembic_cli_ok("downgrade", "base")
        self.assertFalse(_schema_existe(self.cursor), "a base nao estava vazia")

        alembic_cli_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

        alembic_cli_ok("downgrade", "base")
        self.assertEqual(
            _objectos_em_platform(self.cursor), 0, "ficaram objectos em `platform`"
        )
        self.assertFalse(_schema_existe(self.cursor), "o schema sobreviveu ao downgrade")

        alembic_cli_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

    def test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo(self) -> None:
        """O atalho da suite (`alembic` no processo) nao pode divergir do executavel."""
        from tests.base import alembic_cli

        for argumentos in (("heads",), ("current",), ("history",)):
            with self.subTest(comando=argumentos[0]):
                no_processo, por_fora = alembic(*argumentos), alembic_cli(*argumentos)
                self.assertEqual(no_processo.returncode, por_fora.returncode)
                self.assertEqual(no_processo.stdout, por_fora.stdout)
        # E uma falha e falha nos dois: uma revisao que nao existe.
        self.assertNotEqual(alembic("upgrade", "9999").returncode, 0)
        self.assertNotEqual(alembic_cli("upgrade", "9999").returncode, 0)

    def _estado_da_rls(self) -> dict:
        self.cursor.execute(
            "SELECT c.relname::text, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'platform' AND c.relkind = 'r' ORDER BY 1"
        )
        tabelas = [tuple(linha) for linha in self.cursor.fetchall()]
        self.cursor.execute(
            "SELECT tablename::text, policyname::text FROM pg_policies "
            "WHERE schemaname = 'platform' ORDER BY 1, 2"
        )
        politicas = [tuple(linha) for linha in self.cursor.fetchall()]
        self.cursor.execute(
            "SELECT has_schema_privilege('kamba_resolver', 'platform', 'USAGE'), "
            "(SELECT count(*) FROM information_schema.column_privileges "
            "  WHERE grantee = 'kamba_resolver' AND table_schema = 'platform'), "
            "(SELECT count(*) FROM information_schema.table_privileges "
            "  WHERE grantee = 'kamba_resolver' AND table_schema = 'platform')"
        )
        uso, colunas, de_tabela = self.cursor.fetchone()
        return {
            "tabelas": tabelas,
            "politicas": politicas,
            "resolvedor": (uso, colunas, de_tabela),
        }

    def test_o_downgrade_da_0002_desfaz_a_rls_e_o_resolvedor(self) -> None:
        """DoD do KAM-004: «downgrade das politicas testado» — o **efeito**.

        O ciclo acima vai sempre ate `base`, onde o `DROP` da 0001 apaga o que a
        0002 tivesse deixado para tras: um `downgrade` da 0002 que nao revogasse
        nada, ou que deixasse `ENABLE` + `FORCE` sem politica, passava. Aqui
        para-se em `0001` e le-se o catalogo.

        Parte-se da `0002` e nao de `head`: desde o KAM-008 ha uma revisao por
        cima, e o que aqui se mede e o par 0001 <-> 0002.
        """
        alembic_ok("upgrade", "head")
        alembic_ok("downgrade", "0002")
        em_head = self._estado_da_rls()
        self.assertEqual(
            em_head["tabelas"],
            [(tabela, True, True) for tabela in TABELAS_0001],
        )
        self.assertEqual(
            em_head["politicas"],
            [
                ("entitlements", "tenant_iso"),
                ("tenant_channels", "resolver_leitura"),
                ("tenant_channels", "tenant_iso"),
                ("tenants", "resolver_leitura"),
                ("tenants", "tenant_iso"),
            ],
        )
        self.assertEqual(em_head["resolvedor"], (True, 10, 0))

        alembic_ok("downgrade", "0001")
        self.assertEqual(
            self._estado_da_rls(),
            {
                "tabelas": [(tabela, False, False) for tabela in TABELAS_0001],
                "politicas": [],
                "resolvedor": (False, 0, 0),
            },
        )

        alembic_ok("upgrade", "0002")
        self.assertEqual(self._estado_da_rls(), em_head)

    def test_o_upgrade_para_a_0002_preserva_as_linhas(self) -> None:
        """Ligar a RLS numa base com dados nao perde nem altera nenhum."""
        alembic_ok("downgrade", "0001")
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (gen_random_uuid(), 'pme', 'antes da rls') "
            "RETURNING id::text"
        )
        tenant = self.cursor.fetchone()[0]
        try:
            alembic_ok("upgrade", "head")
            self.cursor.execute(
                "SELECT nome FROM platform.tenants WHERE id = %s", (tenant,)
            )
            self.assertEqual(
                [tuple(l) for l in self.cursor.fetchall()], [("antes da rls",)]
            )
        finally:
            self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))

    def test_o_downgrade_nao_remove_os_papeis(self) -> None:
        """Os papeis sao do `bootstrap`, nao de uma revisao: sobrevivem."""
        alembic_ok("downgrade", "base")
        self.cursor.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)",
            (list(ligacao.PAPEIS.values()),),
        )
        self.assertEqual(self.cursor.fetchone()[0], len(ligacao.PAPEIS))

    def test_o_downgrade_recusa_apagar_o_que_nao_criou(self) -> None:
        """`DROP SCHEMA` sem `CASCADE`: um objecto estranho faz falhar, nao desaparece."""
        alembic_ok("upgrade", "head")
        self.cursor.execute("CREATE TABLE platform.intrusa (x integer)")
        try:
            resultado = alembic("downgrade", "base")
            self.assertNotEqual(
                resultado.returncode, 0, "o downgrade apagou uma tabela que nao criou"
            )
            self.assertTrue(_schema_existe(self.cursor))
            # O DDL e transaccional: a revisao falhou inteira, nao a meio.
            # Uma transaccao por revisao (`env.py`): a 0003 e a 0002 desceram e
            # confirmaram; a 0001 falhou, inteira, e e nela que a base fica.
            self.assertEqual(_tabelas(self.cursor), ("entitlements", "intrusa",
                                                     "tenant_channels", "tenants"))
        finally:
            self.cursor.execute("DROP TABLE IF EXISTS platform.intrusa")

    def test_upgrade_falha_se_o_schema_ja_existir_fora_das_migracoes(self) -> None:
        alembic_ok("downgrade", "base")
        self.cursor.execute("CREATE SCHEMA platform")
        try:
            resultado = alembic("upgrade", "head")
            self.assertNotEqual(resultado.returncode, 0)
        finally:
            self.cursor.execute("DROP SCHEMA platform")

    def test_o_bootstrap_e_idempotente(self) -> None:
        bootstrap.aplicar()
        segunda = bootstrap.aplicar()
        terceira = bootstrap.aplicar()
        self.assertEqual(segunda, terceira, "duas execucoes seguidas diferem")
        self.assertEqual(
            sum("ja existia" in linha for linha in terceira), len(ligacao.PAPEIS)
        )
        self.assertEqual(sum("criado" in linha for linha in terceira), 0)
        self.assertEqual(sum("pertenca revogada" in linha for linha in terceira), 0)

    def test_o_bootstrap_diz_que_redefine_as_palavras_passe(self) -> None:
        """Reescreve-as sempre; faze-lo calado era o defeito."""
        feito = bootstrap.aplicar()
        self.assertEqual(
            sum("palavra-passe redefinida" in linha for linha in feito),
            len(ligacao.PAPEIS),
        )

    def test_a_palavra_passe_guardada_e_um_verificador_scram(self) -> None:
        self.cursor.execute(
            "SELECT rolname, left(rolpassword, 14) FROM pg_authid "
            "WHERE rolname = ANY(%s) ORDER BY 1",
            (list(ligacao.PAPEIS.values()),),
        )
        self.assertEqual(
            [tuple(linha) for linha in self.cursor.fetchall()],
            [(papel, "SCRAM-SHA-256$") for papel in sorted(ligacao.PAPEIS.values())],
        )

    def test_o_verificador_e_deterministico_com_o_mesmo_sal(self) -> None:
        import base64

        sal = base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ==")
        verificador = bootstrap.verificador_scram("pencil", sal)
        self.assertTrue(
            verificador.startswith("SCRAM-SHA-256$4096:W22ZaJ0SNY7soEsUEjb6gQ==$")
        )
        self.assertEqual(verificador, bootstrap.verificador_scram("pencil", sal))
        self.assertNotEqual(verificador, bootstrap.verificador_scram("pencil"))

    def test_palavra_passe_nao_ascii_e_recusada(self) -> None:
        with self.assertRaises(ligacao.ConfiguracaoEmFalta):
            bootstrap.verificador_scram("palavra-com-" + chr(231))

    def test_o_bootstrap_repoe_atributos_alterados_a_mao(self) -> None:
        self.cursor.execute("ALTER ROLE kamba_app BYPASSRLS")
        bootstrap.aplicar()
        self.cursor.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'kamba_app'"
        )
        self.assertFalse(self.cursor.fetchone()[0])


class TestVersaoEDono(ComBase):
    def test_e_postgresql_18_6(self) -> None:
        """O criterio diz 18.6, e a imagem do gate esta fixada por digest."""
        versao = self.consultar("SELECT current_setting('server_version')")[0][0]
        self.assertTrue(
            versao.startswith("18.6"),
            f"esperava PostgreSQL 18.6, encontrei {versao}",
        )

    def test_as_tabelas_sao_do_migrator(self) -> None:
        """DDL so por `kamba_migrator` (`docs/tecnica/03` §11)."""
        donos = self.consultar(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'platform'"
        )
        self.assertEqual({d for _, d in donos}, {"kamba_migrator"})
        self.assertEqual(len(donos), len(TABELAS))

    def test_a_tabela_de_versao_vive_em_public(self) -> None:
        linhas = self.consultar(
            "SELECT schemaname FROM pg_tables WHERE tablename = 'alembic_version'"
        )
        self.assertEqual(linhas, [("public",)])

    def test_ha_uma_so_cabeca(self) -> None:
        """Duas cabecas sao duas revisoes com o mesmo pai: um merge mal resolvido."""
        resultado = alembic("heads")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        cabecas = [l for l in resultado.stdout.splitlines() if l.strip()]
        self.assertEqual(len(cabecas), 1, cabecas)


class TestDadosSobrevivemAoUpgrade(ComBase):
    """«Migracao com dados de teste preservados nas colunas aditivas».

    Com uma so revisao nao ha ainda migracao aditiva para exercitar: o que se
    pode provar hoje e que reaplicar `upgrade head` sobre dados existentes nao
    lhes toca. O caso real — uma revisao 0002 que acrescenta uma coluna a uma
    tabela com linhas — fica para o ticket que escrever essa revisao, e esta
    classe e onde ele deve entrar.
    """

    def test_upgrade_repetido_preserva_as_linhas(self) -> None:
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            identificador = factories.tenant(cursor, nome="Sobrevive ao upgrade")
            factories.canal(cursor, identificador)
            conexao.commit()
            alembic_ok("upgrade", "head")
            # Transaccao nova depois do `commit`: o contexto nao sobrevive a
            # ela, e sem o repor a RLS devolvia zero linhas.
            factories.contexto(cursor, identificador)
            cursor.execute(
                "SELECT nome FROM platform.tenants WHERE id = %s", (identificador,)
            )
            self.assertEqual(cursor.fetchone()[0], "Sobrevive ao upgrade")
        finally:
            conexao.rollback()
            conexao.close()
            # A limpeza e do `kamba_batch`: `kamba_app` nao tem DELETE em tabela
            # nenhuma. A primeira versao deste teste limpava como `kamba_app`, e
            # foi a correccao dos privilegios que o fez falhar — como devia.
            limpeza = ligacao.ligar("batch")
            try:
                cursor = limpeza.cursor()
                cursor.execute(
                    "DELETE FROM platform.tenant_channels WHERE tenant_id = %s",
                    (identificador,),
                )
                cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (identificador,)
                )
                limpeza.commit()
            finally:
                limpeza.close()


if __name__ == "__main__":
    unittest.main()

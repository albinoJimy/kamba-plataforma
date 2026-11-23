"""Gate 8: o papel e a base do proxy de LLM (KAM-247).

Decisao do fundador de 2026-11-23 (opcao A1): o LiteLLM guarda as chaves
virtuais numa base `kamba_litellm` no cluster da plataforma, com um papel
`kamba_litellm` que e dono dela e **nao entra na base da plataforma**. O custo
aceite e o proxy passar a estar na rede `data`; o que o torna aceitavel e o que
estes ensaios medem: o papel do proxy nao liga a base da plataforma, nao tem
privilegio nenhum sobre o que la vive, e nenhum papel da plataforma entra na
base dele.

Cada recusa tem o controlo positivo ao lado — o mesmo papel, com a mesma
palavra-passe, **entra** na base dele —, para que um 42501 nao seja na verdade
uma palavra-passe errada.
"""

from __future__ import annotations

import os
import unittest

import bootstrap
import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

PAPEL = bootstrap.PAPEL_DO_LITELLM
BASE = bootstrap.BASE_DO_LITELLM


def _ligar_como(papel: str, senha: str, base: str):
    import pg8000.dbapi

    destino = ligacao.alvo()
    return pg8000.dbapi.connect(
        user=papel,
        password=senha,
        host=destino.host,
        port=destino.porta,
        database=base,
        application_name="kamba-db:ensaio-litellm",
    )


class TestPapelDoLitellm(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        cls.senha = os.environ.get(bootstrap.VARIAVEL_DO_PAPEL_DO_LITELLM, "")
        if not cls.senha:
            # Falha e nao salta: o `gate_bd.py` da-a sempre, e um gate 8 sem
            # ela mediria a plataforma sem o papel que a pode tocar.
            raise AssertionError(
                f"{bootstrap.VARIAVEL_DO_PAPEL_DO_LITELLM} nao esta no ambiente; "
                "o `db/gate_bd.py` gera-a para a suite"
            )
        cls.feito = bootstrap.aplicar()
        # Em `head`, como o `ComBase`: o ensaio dos privilegios le o esquema
        # `platform`, e contar zero sobre um esquema que nao existe nao media nada.
        if not em_head():
            alembic_ok("upgrade", "head")
        cls.plataforma = ligacao.alvo().base

    def setUp(self) -> None:
        self.admin = ligacao.ligar("admin")
        self.admin.autocommit = True
        self.cursor = self.admin.cursor()

    def tearDown(self) -> None:
        self.admin.close()

    def _uma(self, sql: str, parametros: tuple = ()):
        self.cursor.execute(sql, parametros)
        return self.cursor.fetchone()[0]

    def test_o_papel_nao_tem_atributo_nenhum_de_administracao(self) -> None:
        self.cursor.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
            "rolreplication, rolbypassrls, left(rolpassword, 14) "
            "FROM pg_authid WHERE rolname = %s",
            (PAPEL,),
        )
        self.assertEqual(
            tuple(self.cursor.fetchone()),
            (True, False, False, False, False, False, "SCRAM-SHA-256$"),
        )

    def test_o_papel_e_dono_da_base_dele(self) -> None:
        self.assertEqual(
            self._uma(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (BASE,),
            ),
            PAPEL,
        )

    def test_o_papel_nao_pertence_a_papel_nenhum_nem_tem_membros(self) -> None:
        self.assertEqual(
            self._uma(
                "SELECT count(*) FROM pg_auth_members a "
                "JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
                "WHERE g.rolname = %s OR m.rolname = %s",
                (PAPEL, PAPEL),
            ),
            0,
        )

    def test_liga_a_base_dele_e_cria_tabelas_no_public(self) -> None:
        """O controlo positivo, e o que as migracoes do LiteLLM pedem no arranque."""
        conexao = _ligar_como(PAPEL, self.senha, BASE)
        try:
            conexao.autocommit = True
            cursor = conexao.cursor()
            cursor.execute("CREATE TABLE public.ensaio_kam247 (x integer)")
            cursor.execute("DROP TABLE public.ensaio_kam247")
        finally:
            conexao.close()

    def test_nao_liga_a_base_da_plataforma(self) -> None:
        with self.assertRaises(Exception) as capturado:
            _ligar_como(PAPEL, self.senha, self.plataforma).close()
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertIn("permission denied for database", str(capturado.exception))
        self.assertFalse(
            self._uma(
                "SELECT has_database_privilege(%s, %s, 'CONNECT')",
                (PAPEL, self.plataforma),
            )
        )

    def test_nao_tem_privilegio_nenhum_sobre_o_que_vive_na_plataforma(self) -> None:
        """Mesmo que um dia entrasse: nenhum esquema, tabela, sequencia ou funcao.

        Le-se do catalogo da base da plataforma, ligado como admin: o que o
        papel pode fazer la dentro, contado objecto a objecto, e zero.
        """
        self.cursor.execute(
            "SELECT n.nspname FROM pg_namespace n "
            "WHERE n.nspname NOT LIKE 'pg\\_%%' AND n.nspname <> 'information_schema' "
            "AND (has_schema_privilege(%s, n.oid, 'USAGE') "
            "  OR has_schema_privilege(%s, n.oid, 'CREATE')) ORDER BY 1",
            (PAPEL, PAPEL),
        )
        # O `public` tem USAGE para o PUBLIC por omissao, e o papel herda-o como
        # qualquer outro; nao e privilegio dele, e nao da acesso a nada que la
        # nao esteja concedido ao PUBLIC. Os esquemas da plataforma e que
        # contam, e esses tem de ficar de fora.
        self.assertIn([tuple(l) for l in self.cursor.fetchall()], ([], [("public",)]))
        self.assertFalse(
            self._uma("SELECT has_schema_privilege(%s, 'platform', 'USAGE')", (PAPEL,))
        )
        tabelas = self._uma(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('platform', 'lg', 'dat') AND c.relkind IN ('r', 'p', 'v', 'm') "
            "AND (has_table_privilege(%s, c.oid, 'SELECT') "
            "  OR has_table_privilege(%s, c.oid, 'INSERT') "
            "  OR has_table_privilege(%s, c.oid, 'UPDATE') "
            "  OR has_table_privilege(%s, c.oid, 'DELETE'))",
            (PAPEL, PAPEL, PAPEL, PAPEL),
        )
        self.assertEqual(tabelas, 0)
        self.assertGreater(
            self._uma(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'platform' AND c.relkind IN ('r', 'p')"
            ),
            0,
            "a plataforma nao tem tabelas: o zero de cima nao mediu nada",
        )
        concessoes = self._uma(
            "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = %s",
            (PAPEL,),
        )
        self.assertEqual(concessoes, 0)

    def test_nenhum_papel_da_plataforma_entra_na_base_do_proxy(self) -> None:
        conexao = ligacao.ligar("app")
        conexao.close()  # controlo: o `kamba_app` liga a base dele
        destino = ligacao.alvo()
        utilizador, senha = ligacao.credenciais("app")
        import pg8000.dbapi

        with self.assertRaises(Exception) as capturado:
            pg8000.dbapi.connect(
                user=utilizador, password=senha, host=destino.host,
                port=destino.porta, database=BASE,
            ).close()
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertEqual(
            [
                papel
                for papel in sorted(ligacao.PAPEIS.values())
                if self._uma(
                    "SELECT has_database_privilege(%s, %s, 'CONNECT')", (papel, BASE)
                )
            ],
            [],
        )

    def test_o_public_nao_tem_connect_nem_temporary_na_base_do_proxy(self) -> None:
        self.assertEqual(
            self._uma(
                "SELECT count(*) FROM pg_database d, aclexplode(d.datacl) a "
                "WHERE d.datname = %s AND a.grantee = 0",
                (BASE,),
            ),
            0,
        )

    def test_o_bootstrap_repete_sem_mudar_nada(self) -> None:
        segunda = [l for l in bootstrap.aplicar() if PAPEL in l]
        terceira = [l for l in bootstrap.aplicar() if PAPEL in l]
        self.assertEqual(segunda, terceira)
        self.assertIn(f"papel {PAPEL} ja existia; atributos repostos", terceira)
        self.assertIn(f"base {BASE} ja existia; dono reposto", terceira)

    def test_o_que_se_muda_a_mao_no_papel_e_reposto(self) -> None:
        """Atributos, configuracao e pertencas, como o `test_migracao` mede no `kamba_app`."""
        self.cursor.execute(f"ALTER ROLE {PAPEL} CREATEDB BYPASSRLS")
        self.cursor.execute(f"ALTER ROLE {PAPEL} SET search_path = public, platform")
        self.cursor.execute(f"GRANT kamba_app TO {PAPEL}")
        self.cursor.execute(f"GRANT {PAPEL} TO kamba_batch")
        try:
            feito = bootstrap.aplicar()
            self.cursor.execute(
                "SELECT rolcreatedb, rolbypassrls, rolconfig FROM pg_roles WHERE rolname = %s",
                (PAPEL,),
            )
            depois = tuple(self.cursor.fetchone())
        finally:
            # Se o bootstrap falhar, nao deixa o papel aberto para os ensaios
            # seguintes. Repor o que ja esta reposto nao muda nada.
            self.cursor.execute(f"ALTER ROLE {PAPEL} NOCREATEDB NOBYPASSRLS")
            self.cursor.execute(f"ALTER ROLE {PAPEL} RESET ALL")
            for grupo, membro in (("kamba_app", PAPEL), (PAPEL, "kamba_batch")):
                self.cursor.execute(
                    "SELECT 1 FROM pg_auth_members a JOIN pg_roles g ON g.oid = a.roleid "
                    "JOIN pg_roles m ON m.oid = a.member WHERE g.rolname = %s AND m.rolname = %s",
                    (grupo, membro),
                )
                if self.cursor.fetchone() is not None:
                    self.cursor.execute(f"REVOKE {grupo} FROM {membro}")
        self.assertEqual(depois, (False, False, None))
        self.assertEqual(
            sum(1 for l in feito if "pertenca revogada" in l and PAPEL in l), 2
        )

    def test_um_connect_dado_a_mao_na_plataforma_e_revogado(self) -> None:
        self.cursor.execute(f'GRANT CONNECT ON DATABASE "{self.plataforma}" TO {PAPEL}')
        try:
            bootstrap.aplicar()
            depois = self._uma(
                "SELECT has_database_privilege(%s, %s, 'CONNECT')",
                (PAPEL, self.plataforma),
            )
        finally:
            self.cursor.execute(
                f'REVOKE CONNECT ON DATABASE "{self.plataforma}" FROM {PAPEL}'
            )
        self.assertFalse(depois)

    def test_o_dono_e_reposto(self) -> None:
        """Uma base passada a outro dono a mao volta ao do proxy."""
        self.cursor.execute(f"ALTER DATABASE {BASE} OWNER TO kamba_migrator")
        bootstrap.aplicar()
        self.assertEqual(
            self._uma(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (BASE,),
            ),
            PAPEL,
        )


class TestSemBase(unittest.TestCase):
    """Sem tocar em base nenhuma."""

    def test_recusa_a_base_da_plataforma_com_o_nome_da_do_proxy(self) -> None:
        ambiente = {"KAMBA_DB_NAME": BASE}
        for identidade, variavel in ligacao.VARIAVEL_DA_SENHA.items():
            ambiente[variavel] = f"valor-{identidade}"
        ambiente["POSTGRES_USER"] = "admin"
        with self.assertRaises(ligacao.ConfiguracaoEmFalta) as capturado:
            bootstrap.aplicar(ambiente)
        self.assertIn(BASE, str(capturado.exception))

    def test_a_variavel_e_a_do_inventario(self) -> None:
        """`KAMBA_SECRET_` + o id `db_litellm_password`, a regra do `ligacao.py`."""
        self.assertEqual(
            bootstrap.VARIAVEL_DO_PAPEL_DO_LITELLM,
            "KAMBA_SECRET_" + "db_litellm_password".upper(),
        )

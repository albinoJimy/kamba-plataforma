"""O leitor de revisoes: o SQL que segue, e o que recusa em vez de adivinhar.

Os casos de recusa vem da revisao adversarial (ANALISE-05, M4): cada um era uma
forma de por DDL numa revisao sem o gate 3b o ver.
"""

from __future__ import annotations

import unittest

from canon_lint import revisao

CABECA = "from alembic import op\nimport sqlalchemy as sa\n\n"

#: A forma do `db/rls.py` do KAM-004: o SQL e montado com *f-strings* a partir
#: dos argumentos, com uma variavel local e uma funcao pura pelo meio.
AUXILIAR = '''\
from __future__ import annotations

import re

from alembic import op

POLITICA = "tenant_iso"
VARIAVEL = "app.tenant_id"

_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")


def _validar(*identificadores: str) -> None:
    for identificador in identificadores:
        if not _IDENTIFICADOR.match(identificador):
            raise ValueError(identificador)


def predicado(coluna: str = "tenant_id") -> str:
    _validar(coluna)
    return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid"


def enable_tenant_rls(tabela: str, coluna: str = "tenant_id", schema: str = "platform") -> None:
    """ENABLE + FORCE + politica."""
    _validar(tabela, coluna, schema)
    alvo = f"{schema}.{tabela}"
    op.execute(f"ALTER TABLE {alvo} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLITICA} ON {alvo} "
        f"USING ({predicado(coluna)}) WITH CHECK ({predicado(coluna)})"
    )


def disable_tenant_rls(tabela: str, schema: str = "platform") -> None:
    _validar(tabela, schema)
    alvo = f"{schema}.{tabela}"
    op.execute(f"DROP POLICY {POLITICA} ON {alvo}")


def com_ciclo(tabelas) -> None:
    for tabela in tabelas:
        op.execute(f"ANALYZE platform.{tabela}")
'''


def ler(fonte: str, auxiliar: str | None = AUXILIAR) -> revisao.Extraccao:
    return revisao.extrair(
        fonte, {"rls": "db/rls.py"}, lambda caminho: auxiliar if caminho == "db/rls.py" else None
    )


def sql(fonte: str) -> list[str]:
    return [b.texto for b in ler(fonte).blocos]


class TestLiterais(unittest.TestCase):
    def test_formas_literais(self) -> None:
        fonte = CABECA + (
            'SQL = "CREATE TABLE a (id uuid)"\n\n'
            "def upgrade():\n"
            "    op.execute(SQL)\n"
            '    op.execute(sa.text("CREATE TABLE b (id uuid)"))\n'
            '    op.execute("CREATE TABLE c " "(id " + "uuid)")\n'
            '    op.get_bind().execute(sa.text("CREATE TABLE d (id uuid)"))\n'
            '    op.get_bind().exec_driver_sql("CREATE TABLE e (id uuid)")\n'
            '    op.execute(sqltext="CREATE TABLE f (id uuid)")\n'
        )
        extraccao = ler(fonte)
        self.assertEqual(extraccao.ilegiveis, [])
        self.assertEqual([b.texto.split()[2] for b in extraccao.blocos], ["a", "b", "c", "d", "e", "f"])
        self.assertEqual([b.linha for b in extraccao.blocos], [7, 8, 9, 10, 11, 12])

    def test_alias_do_op_e_seguido_pelos_imports(self) -> None:
        for cabeca, chamada in (
            ("from alembic import op as o", 'o.execute("CREATE TABLE x (id uuid)")'),
            ("import alembic", 'alembic.op.execute("CREATE TABLE x (id uuid)")'),
            ("import alembic.op as o", 'o.execute("CREATE TABLE x (id uuid)")'),
            ("from alembic.op import execute", 'execute("CREATE TABLE x (id uuid)")'),
            ("from alembic.op import execute as corre", 'corre("CREATE TABLE x (id uuid)")'),
        ):
            with self.subTest(cabeca=cabeca):
                self.assertEqual(sql(f"{cabeca}\n\ndef upgrade():\n    {chamada}\n"), ["CREATE TABLE x (id uuid)"])

    def test_api_do_alembic_por_qualquer_alias_falha(self) -> None:
        for cabeca, chamada in (
            ("from alembic import op", "op.create_table('x')"),
            ("from alembic import op as o", "o.add_column('x', None)"),
            ("import alembic", "alembic.op.create_table('x')"),
            ("from alembic.op import create_table", "create_table('x')"),
            ("from alembic import op", "with op.batch_alter_table('x') as b:\n        b.add_column(None)"),
        ):
            with self.subTest(cabeca=cabeca, chamada=chamada):
                extraccao = ler(f"{cabeca}\n\ndef upgrade():\n    {chamada}\n")
                self.assertEqual(extraccao.blocos, [])
                self.assertEqual(len(extraccao.ilegiveis), 1)
                self.assertIn("API de operacoes", extraccao.ilegiveis[0][1])


class TestNaoLiteral(unittest.TestCase):
    def ilegiveis(self, corpo: str, topo: str = "") -> list[str]:
        extraccao = ler(CABECA + topo + "\ndef upgrade():\n" + corpo)
        self.assertEqual(extraccao.blocos, [], "nada disto se pode ler como SQL")
        return [m for _, m in extraccao.ilegiveis]

    def test_expressoes_que_nao_se_resolvem(self) -> None:
        for corpo in (
            '    op.execute(f"CREATE TABLE {esquema}.x (id uuid)")\n',
            '    op.execute("CREATE TABLE {}.x (id uuid)".format(esquema))\n',
            '    op.execute("CREATE TABLE %s.x (id uuid)" % esquema)\n',
            "    op.execute(sql_local)\n",
            "    op.execute()\n",
            '    conn.execute(construir("x"))\n',
            '    op.execute(f"CREATE TABLE x (preco numeric({n:d}))")\n',
            '    op.execute(f"CREATE TABLE {nome!r} (id uuid)")\n',
        ):
            with self.subTest(corpo=corpo):
                self.assertEqual(len(self.ilegiveis(corpo)), 1)

    def test_constante_sombreada_ou_reatribuida_deixa_de_ser_constante(self) -> None:
        """e08, e32, e33: o lint lia a constante de modulo e a revisao executava outra coisa."""
        boa = 'SQL = "CREATE TABLE platform.tenants (id uuid)"\n'
        for topo, corpo in (
            (boa, '    SQL = "CREATE TABLE platform.pagamentos_xpto (valor_kz bigint)"\n    op.execute(SQL)\n'),
            (boa + 'SQL = SQL.replace("tenants", "pagamentos_xpto")\n', "    op.execute(SQL)\n"),
            (boa + 'if True:\n    SQL = "CREATE TABLE platform.pagamentos_xpto (valor_kz bigint)"\n', "    op.execute(SQL)\n"),
            (boa, "    global SQL\n    op.execute(SQL)\n"),
            (boa + 'SQL += " WITH (fillfactor = 90)"\n', "    op.execute(SQL)\n"),
        ):
            with self.subTest(topo=topo, corpo=corpo):
                mensagens = self.ilegiveis(corpo, topo)
                self.assertEqual(len(mensagens), 1)
                self.assertIn("SQL", mensagens[0])

    def test_o_objecto_op_fora_de_uma_chamada_directa(self) -> None:
        """e02, e03, e10, e22: um alias ou um `getattr` escondia o `execute`."""
        for corpo in (
            '    corre = op.execute\n    corre("CREATE TABLE x (valor_kz int)")\n',
            '    getattr(op, "execute")("CREATE TABLE x (valor_kz int)")\n',
            '    (lambda o: o.execute("CREATE TABLE x (valor_kz int)"))(op)\n',
            "    auxiliar(op)\n",
        ):
            with self.subTest(corpo=corpo):
                # Nalguns destes o SQL ate e lido (um `.execute` com literal le-se
                # sempre); o que se exige e que o uso indevido do `op` falhe.
                mensagens = [m for _, m in ler(CABECA + "\ndef upgrade():\n" + corpo).ilegiveis]
                self.assertTrue(any("fora de uma chamada directa" in m for m in mensagens), mensagens)

    def test_metadados_do_sqlalchemy(self) -> None:
        """e06, e07: `sa.Table(...).create(bind)` cria a tabela sem SQL nenhum a vista."""
        for cabeca, corpo in (
            (CABECA, '    sa.Table("x", sa.MetaData(), sa.Column("valor_kz", sa.Integer)).create(op.get_bind())\n'),
            (CABECA + "meta = sa.MetaData()\n", "    meta.create_all(op.get_bind())\n"),
            ("from alembic import op\nfrom sqlalchemy import Table, MetaData, Column\n", '    Table("x", MetaData(), Column("valor_kz")).create(op.get_bind())\n'),
        ):
            with self.subTest(corpo=corpo):
                extraccao = ler(cabeca + "\ndef upgrade():\n" + corpo)
                self.assertEqual(extraccao.blocos, [])
                self.assertTrue(any("metadados" in m for _, m in extraccao.ilegiveis))

    def test_codigo_que_nao_se_le(self) -> None:
        for corpo in (
            "    exec(\"op.execute('CREATE TABLE x (valor_kz int)')\")\n",
            '    eval("1")\n',
            '    sql = sa.text("CREATE TABLE x (valor_kz int)")\n    conn.outra_coisa(sql)\n',
            '    sa.DDL("CREATE TABLE x (valor_kz int)").execute_if(dialect="postgresql")\n',
        ):
            with self.subTest(corpo=corpo):
                self.assertGreaterEqual(len(self.ilegiveis(corpo)), 1)

    def test_sql_construido_que_nao_vai_para_um_execute_lido(self) -> None:
        """Numa revisao que tem outras instrucoes lidas, a regra da «revisao sem
        instrucoes» nao dispara — e o `text(...)` solto tem de falhar por si
        (mutacao M4h sobrevivia sem este teste)."""
        fonte = CABECA + (
            "def upgrade():\n"
            '    op.execute("CREATE SCHEMA platform")\n'
            '    conn.outra_coisa(sa.text("CREATE TABLE platform.x (valor_kz int)"))\n'
        )
        extraccao = ler(fonte)
        self.assertEqual([b.texto for b in extraccao.blocos], ["CREATE SCHEMA platform"])
        self.assertEqual(len(extraccao.ilegiveis), 1)
        self.assertIn("constroi SQL", extraccao.ilegiveis[0][1])

    def test_import_de_modulo_nao_declarado(self) -> None:
        for linha in ("import ajudas", "from ajudas import criar", "from . import irma", "from kamba_core import x"):
            with self.subTest(linha=linha):
                extraccao = ler(f"from alembic import op\n{linha}\n\ndef upgrade():\n    pass\n")
                self.assertEqual(len(extraccao.ilegiveis), 1)
                self.assertIn("auxiliares_de_migracao", extraccao.ilegiveis[0][1])
        limpa = ler("from alembic import op\nimport json\nfrom datetime import date\n\ndef upgrade():\n    op.execute('SELECT 1')\n")
        self.assertEqual(limpa.ilegiveis, [])

    def test_revisao_sem_nenhuma_instrucao_lida(self) -> None:
        extraccao = ler("from alembic import op\n\ndef upgrade():\n    cursor.fazer_coisas()\n")
        self.assertEqual(len(extraccao.ilegiveis), 1)
        self.assertIn("nao se leu nenhuma instrucao", extraccao.ilegiveis[0][1])

    def test_revisao_de_merge_vazia_passa(self) -> None:
        extraccao = ler('"""merge"""\nrevision = "0003"\n\ndef upgrade():\n    pass\n\ndef downgrade():\n    """nada"""\n    pass\n')
        self.assertEqual((extraccao.blocos, extraccao.ilegiveis), ([], []))

    def test_funcao_aninhada_que_executa_sql(self) -> None:
        mensagens = self.ilegiveis('    def interior():\n        op.execute("CREATE TABLE x (id uuid)")\n    interior()\n')
        self.assertEqual(len(mensagens), 1)


class TestSeguir(unittest.TestCase):
    """A forma da revisao 0002 do KAM-004."""

    REVISAO = (
        "from alembic import op\n\nimport rls\n\n"
        'COLUNAS = {\n    "tenant_channels": ("id", "tenant_id", "estado"),\n    "tenants": ("id", "tipo"),\n}\n\n\n'
        "def upgrade() -> None:\n"
        '    rls.enable_tenant_rls("entitlements")\n'
        '    rls.enable_tenant_rls("tenants", coluna="id")\n'
        '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
        "    for tabela, colunas in COLUNAS.items():\n"
        "        op.execute(\n"
        "            f\"GRANT SELECT ({', '.join(colunas)}) ON platform.{tabela} TO kamba_resolver\"\n"
        "        )\n"
        "        op.execute(\n"
        '            f"CREATE POLICY resolver_leitura ON platform.{tabela} "\n'
        '            "FOR SELECT TO kamba_resolver USING (true)"\n'
        "        )\n\n\n"
        "def downgrade() -> None:\n"
        '    rls.disable_tenant_rls("tenants")\n'
    )

    def test_o_sql_e_o_que_a_revisao_executaria(self) -> None:
        extraccao = ler(self.REVISAO)
        self.assertEqual(extraccao.ilegiveis, [])
        self.assertEqual(
            [b.texto for b in extraccao.blocos],
            [
                "ALTER TABLE platform.entitlements ENABLE ROW LEVEL SECURITY",
                "CREATE POLICY tenant_iso ON platform.entitlements "
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
                "ALTER TABLE platform.tenants ENABLE ROW LEVEL SECURITY",
                "CREATE POLICY tenant_iso ON platform.tenants "
                "USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
                "GRANT USAGE ON SCHEMA platform TO kamba_resolver",
                "GRANT SELECT (id, tenant_id, estado) ON platform.tenant_channels TO kamba_resolver",
                "CREATE POLICY resolver_leitura ON platform.tenant_channels FOR SELECT TO kamba_resolver USING (true)",
                "GRANT SELECT (id, tipo) ON platform.tenants TO kamba_resolver",
                "CREATE POLICY resolver_leitura ON platform.tenants FOR SELECT TO kamba_resolver USING (true)",
                "DROP POLICY tenant_iso ON platform.tenants",
            ],
        )

    def test_o_sql_de_um_auxiliar_e_atribuido_a_linha_da_chamada(self) -> None:
        blocos = ler(self.REVISAO).blocos
        self.assertEqual([(b.linha, b.origem) for b in blocos[:2]], [(12, "via rls.enable_tenant_rls")] * 2)
        self.assertEqual(blocos[4].origem, "")

    def test_um_auxiliar_declarado_nao_e_dispensado_de_leitura(self) -> None:
        """O que a funcao faz e lido; o que nao se segue, falha na chamada."""
        for chamada, fragmento in (
            ("rls.enable_tenant_rls(tabela_dinamica)", "nao se resolvem"),
            ("rls.nao_existe('x')", "nao existe no modulo auxiliar"),
            ("rls.enable_tenant_rls('a', 'b', 'c', 'd')", "nao se resolvem"),
            ("rls.enable_tenant_rls('a', esquema='x')", "nao se resolvem"),
            ("rls.com_ciclo(obter_tabelas())", "nao se resolvem"),
        ):
            with self.subTest(chamada=chamada):
                extraccao = ler(f"from alembic import op\nimport rls\n\ndef upgrade():\n    {chamada}\n")
                self.assertEqual(extraccao.blocos, [])
                self.assertEqual(len(extraccao.ilegiveis), 1)
                self.assertIn(fragmento, extraccao.ilegiveis[0][1])

    def test_ciclo_dentro_do_auxiliar_com_argumento_literal(self) -> None:
        fonte = "from alembic import op\nimport rls\n\ndef upgrade():\n    rls.com_ciclo(['tenants', 'entitlements'])\n"
        self.assertEqual(sql(fonte), ["ANALYZE platform.tenants", "ANALYZE platform.entitlements"])

    def test_auxiliar_declarado_cujo_ficheiro_nao_existe(self) -> None:
        extraccao = ler("from alembic import op\nimport rls\n\ndef upgrade():\n    rls.enable_tenant_rls('x')\n", auxiliar=None)
        self.assertEqual(len(extraccao.ilegiveis), 1)
        self.assertIn("nao se le", extraccao.ilegiveis[0][1])

    def test_variante_passada_como_argumento_chega_ao_sql(self) -> None:
        """O ponto de seguir o auxiliar: o nome que a chamada passa aparece no SQL lido."""
        self.assertIn("platform.consent_log", sql("from alembic import op\nimport rls\n\ndef upgrade():\n    rls.enable_tenant_rls('consent_log')\n")[0])

    def test_funcao_do_proprio_modulo_e_seguida(self) -> None:
        fonte = CABECA + (
            'def criar(tabela, tipo="text"):\n'
            '    op.execute(f"ALTER TABLE platform.{tabela} ADD COLUMN nota {tipo}")\n\n'
            "def upgrade():\n"
            '    criar("tenants")\n'
            '    criar("entitlements", tipo="jsonb")\n'
        )
        self.assertEqual(
            sql(fonte),
            ["ALTER TABLE platform.tenants ADD COLUMN nota text", "ALTER TABLE platform.entitlements ADD COLUMN nota jsonb"],
        )

    def test_ciclo_sobre_o_que_nao_e_constante_falha_no_execute(self) -> None:
        fonte = CABECA + 'def upgrade():\n    for t in obter():\n        op.execute(f"DROP TABLE {t}")\n'
        extraccao = ler(fonte)
        self.assertEqual((extraccao.blocos, len(extraccao.ilegiveis)), ([], 1))

    def test_variavel_local_atribuida_duas_vezes_nao_se_resolve(self) -> None:
        fonte = CABECA + (
            "def upgrade():\n"
            '    alvo = "platform.tenants"\n'
            '    alvo = "platform.pagamentos_xpto"\n'
            '    op.execute(f"DROP TABLE {alvo}")\n'
        )
        extraccao = ler(fonte)
        self.assertEqual((extraccao.blocos, len(extraccao.ilegiveis)), ([], 1))


if __name__ == "__main__":
    unittest.main()

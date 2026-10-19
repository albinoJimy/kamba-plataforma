"""O `downgrade` da 0007 repoe **exactamente** o que a 0001 concedia.

«Migracoes reversiveis — `downgrade` testado» e uma caixa da Definition of
Done do KAM-009, e o ciclo `upgrade -> downgrade -> upgrade` ja esta provado
no gate 8 (`tests/test_migracao.TestCiclo`). O que esse ciclo **nao** ve e a
parte desta revisao que nao e DDL: os privilegios.

A 0007 tira a `kamba_app` o `UPDATE` sobre `tenants.plano` e sobre
`entitlements(limites, ativo)` — e a decisao do ticket, nao uma limpeza: com
a politica `id = app.tenant_id` do KAM-004 a linha que um contexto de tenant
ve e a dele, e com esses privilegios um tenant subia o proprio plano e os
proprios limites. Os limites sao a unica coisa entre um tenant e o tecto de
dinheiro por pedido.

Um `downgrade` que nao os reponha deixa a base num estado que **revisao
nenhuma escreveu**: nem 0006, nem 0007. E o ciclo do gate 8 nao o apanha,
porque o `REVOKE` da 0007 e idempotente — volta a subir e fica igual, com a
base a parecer certa em `head` e errada em todo o lado abaixo dela.

Esta classe nao herda de `ComUso`: controla ela propria a revisao em que a
base esta, como o `TestDowngradeDa0003` do KAM-008. Repoe `head` no fim, corra
bem ou mal.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: As colunas que a 0001 concedeu e a 0007 retirou. Uma lista, e nao um
#: `assertTrue` por linha, para a falha dizer qual.
RETIRADAS = (
    ("platform.tenants", "plano"),
    # O `estado` juntou-se-lhes na revisao adversarial: era a condicao do
    # criterio 2 nas maos do sujeito dela.
    ("platform.tenants", "estado"),
    ("platform.entitlements", "limites"),
    ("platform.entitlements", "ativo"),
)

#: O que a 0007 cria e o `downgrade` tem de levar. As funcoes contam-se pelo
#: prefixo `ten_`, que e o que a revisao poe no schema: `ten_periodo`,
#: `ten_consumir` e, desde a revisao adversarial, a `ten_tecto` e a do
#: trigger `ten_usage_so_sobe`.
TABELAS = ("tenant_usage", "usage_ledger")
FUNCOES = 4


class TestDowngradeDa0007(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head` (o teste desceu, ou falhou a meio de descer).
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    # ------------------------------------------------------------ leituras

    def pode_alterar(self, tabela: str, coluna: str) -> bool:
        self.cursor.execute(
            "SELECT has_column_privilege('kamba_app', %s, %s, 'UPDATE')",
            (tabela, coluna),
        )
        return bool(self.cursor.fetchone()[0])

    def tabelas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def funcoes_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "  ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname LIKE 'ten!_%' ESCAPE '!'"
        )
        return int(self.cursor.fetchone()[0])

    def tem_restricao_do_plano(self) -> bool:
        self.cursor.execute(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'tenants_plano_ck'"
        )
        return int(self.cursor.fetchone()[0]) == 1

    # --------------------------------------------------------------- casos

    def test_em_head_a_aplicacao_nao_altera_o_plano_nem_os_limites(self) -> None:
        """O ponto de partida. Sem isto, o teste seguinte nao diz nada."""
        for tabela, coluna in RETIRADAS:
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                self.assertFalse(self.pode_alterar(tabela, coluna))
        self.assertTrue(self.tem_restricao_do_plano())

    def test_o_downgrade_leva_o_que_a_revisao_criou(self) -> None:
        alembic_ok("downgrade", "0006")
        self.assertEqual(self.tabelas_existentes(), [])
        self.assertEqual(self.funcoes_existentes(), 0)
        self.assertFalse(self.tem_restricao_do_plano())

    def test_o_downgrade_repoe_o_que_a_aplicacao_podia_alterar(self) -> None:
        """O que o ciclo do gate 8 nao ve, porque o `REVOKE` e idempotente."""
        alembic_ok("downgrade", "0006")
        for tabela, coluna in RETIRADAS:
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                self.assertTrue(
                    self.pode_alterar(tabela, coluna),
                    f"o downgrade nao repos o UPDATE de {tabela}.{coluna} — a base "
                    "fica num estado que revisao nenhuma escreveu",
                )

    def test_o_downgrade_repoe_o_insert_em_entitlements(self) -> None:
        """O `INSERT` entrou nos revogados com a revisao adversarial.

        Um `downgrade` que repusesse so o `UPDATE` deixava a base num estado
        que revisao nenhuma escreveu — a `0001` concedia os dois.
        """
        self.cursor.execute(
            "SELECT has_table_privilege('kamba_app', 'platform.entitlements', 'INSERT')"
        )
        self.assertFalse(self.cursor.fetchone()[0], "em head a aplicacao nao insere")

        alembic_ok("downgrade", "0006")
        self.cursor.execute(
            "SELECT has_table_privilege('kamba_app', 'platform.entitlements', 'INSERT'), "
            "       has_table_privilege('kamba_app', 'platform.entitlements', 'SELECT')"
        )
        self.assertEqual([bool(v) for v in self.cursor.fetchone()], [True, True])

    def test_as_outras_colunas_de_tenants_nao_se_perdem_no_caminho(self) -> None:
        """A 0007 revoga o `UPDATE` inteiro e volta a conceder a lista.

        Uma lista truncada a meio tirava a aplicacao colunas que nada neste
        ticket queria tirar — e so em `head`, onde ninguem compara com a 0001.
        """
        for coluna in ("nome", "verificado_at", "zona", "deleted_at"):
            with self.subTest(coluna=coluna):
                self.assertTrue(self.pode_alterar("platform.tenants", coluna))

    def test_o_ciclo_volta_a_deixar_a_base_como_estava(self) -> None:
        alembic_ok("downgrade", "0006")
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), list(TABELAS))
        self.assertEqual(self.funcoes_existentes(), FUNCOES)
        self.assertTrue(self.tem_restricao_do_plano())
        for tabela, coluna in RETIRADAS:
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                self.assertFalse(self.pode_alterar(tabela, coluna))


if __name__ == "__main__":
    unittest.main()

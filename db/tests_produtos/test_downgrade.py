"""O `downgrade` da `0028` leva o que ela criou, e **deixa o que nao criou**.

«Migracoes reversiveis: `downgrade` testado» e uma caixa da Definition of Done
do KAM-043. O ciclo `upgrade -> downgrade -> upgrade` ja corre no *gate* 8
(`tests/test_migracao.TestCiclo`), e o que esse ciclo **nao** ve e a parte desta
revisao que o torna peculiar: a extensao `pg_trgm`.

## Porque e que esta revisao precisa de um teste proprio de `downgrade`

A `0025` cria o `btree_gist` e apaga-o no `downgrade`, e esta certo — ela e a
dona, criou-o sem guarda, e ele vive dentro do esquema que ela tambem apaga.

Esta revisao cria o `pg_trgm` com `IF NOT EXISTS`, porque o
`infra/compose/postgres/initdb/01-bases-e-extensoes.sql` **tambem o cria** (ao
lado do `vector`): sem a guarda, a revisao falhava com
`42710 extension "pg_trgm" already exists` em toda a base que o compose tenha
preparado, que e a maioria delas.

A consequencia e que esta revisao **nao sabe se o criou**: com `IF NOT EXISTS`,
criar e nao-criar sao indistinguiveis depois do facto. Por isso o `downgrade`
nao o apaga — e isso e uma escolha que precisa de teste, porque o ciclo do
*gate* 8 e cego para ela: um `DROP EXTENSION` indevido **sobe outra vez** no
`upgrade` seguinte e a base volta a parecer certa em `head`, com o `pg_trgm`
arrancado por baixo de quem o tinha antes desta revisao. E o mesmo modo de falha
que o `test_downgrade` do KAM-009 descreve para os privilegios: «a base fica num
estado que revisao nenhuma escreveu».

Esta classe **nao** herda de `ComOfertas`: controla ela propria a revisao em que
a base esta, como o `TestDowngradeDa0007` do KAM-009 e o `TestDowngradeDa0003`
do KAM-008. Repoe `head` no fim, corra bem ou mal.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: As duas tabelas que a revisao cria, e que o `downgrade` tem de levar.
TABELAS = ("offer_terms", "price_quotes")

#: Os indices que ela cria. Caem com as tabelas, e e isso que se afirma.
INDICES = (
    "offer_terms_tenant_estado_idx",
    "offer_terms_nome_trgm_idx",
    "price_quotes_vivas_idx",
)

#: A revisao anterior. O `downgrade` desta volta aqui.
ANTERIOR = "0027"


class TestDowngradeDa0028(unittest.TestCase):
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

    # -------------------------------------------------------------- leituras

    def tabelas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def indices_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT indexname::text FROM pg_indexes "
            " WHERE schemaname = 'platform' AND indexname = ANY(%s) ORDER BY 1",
            (list(INDICES),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def politicas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_policies "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def tem_pg_trgm(self) -> bool:
        self.cursor.execute(
            "SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'"
        )
        return int(self.cursor.fetchone()[0]) == 1

    # ----------------------------------------------------------------- casos

    def test_em_head_as_duas_tabelas_e_os_tres_indices_existem(self) -> None:
        """O ponto de partida. **Sem isto, os casos seguintes nao dizem nada.**"""
        self.assertEqual(self.tabelas_existentes(), ["offer_terms", "price_quotes"])
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertEqual(self.politicas_existentes(), ["offer_terms", "price_quotes"])
        self.assertTrue(self.tem_pg_trgm())

    def test_o_downgrade_leva_as_tabelas_os_indices_e_as_politicas(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        self.assertEqual(self.indices_existentes(), [])
        self.assertEqual(self.politicas_existentes(), [])

    def test_o_downgrade_nao_apaga_o_pg_trgm(self) -> None:
        """A escolha que o ciclo do *gate* 8 e cego para ver.

        Um `DROP EXTENSION` aqui sobe outra vez no `upgrade` seguinte, e a base
        volta a parecer certa em `head` — com o `pg_trgm` arrancado por baixo de
        quem o tinha antes desta revisao, incluindo o `initdb` do compose, que o
        cria ao lado do `vector`. O `downgrade` nao sabe se o criou: com
        `IF NOT EXISTS`, criar e nao-criar sao indistinguiveis depois do facto.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertTrue(
            self.tem_pg_trgm(),
            "o downgrade apagou o pg_trgm. Esta revisao cria-o com "
            "IF NOT EXISTS porque o initdb do compose tambem o cria, pelo que "
            "nao sabe se foi ela — e apagar uma extensao que nao criou deixa a "
            "base menos capaz do que antes da revisao (KAM-043)",
        )

    def test_depois_de_voltar_a_subir_tudo_volta(self) -> None:
        """O ciclo inteiro numa classe que controla a revisao.

        O `TestCiclo` do *gate* 8 ja o corre para a cadeia toda; o que este caso
        acrescenta e a afirmacao sobre **estes** objectos, para que a falha diga
        qual deles nao voltou em vez de «a cadeia nao reaplica».
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), ["offer_terms", "price_quotes"])
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertEqual(self.politicas_existentes(), ["offer_terms", "price_quotes"])

    def test_o_downgrade_nao_toca_na_auditoria(self) -> None:
        """A linha de `audit_log` de uma alteracao de preco **fica**.

        Vive noutra revisao e e append-only: quem descer esta revisao perde o
        preco e **nao** perde o rasto de quem o mudou, que e a ordem certa das
        duas perdas.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.cursor.execute(
            "SELECT count(*) FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = 'audit_log'"
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), 1)

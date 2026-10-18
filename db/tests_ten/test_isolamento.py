"""Isolamento da **funcao**: ler e consumir com o contexto de B contra dados de A.

O gate 6 descobre `tenant_usage` e `usage_ledger` sozinho — tem as duas
`tenant_id` — e prova-lhes a politica `tenant_iso` com `FORCE`, a leitura
cruzada e a escrita cruzada. Isso prova a **politica**. O que nao prova e a
`ten_consumir`: uma funcao SQL pode contornar a RLS inteira com um
`SECURITY DEFINER`, e entao o isolamento passava a depender do `p_tenant` que
o chamador passa — que e exactamente o que o ADR-015 recusa.

A funcao e `SECURITY INVOKER`, e esta suite prova as duas metades disso:

* **o facto estrutural** — `pg_proc.prosecdef` e falso para as duas funcoes
  da revisao (e a `ten_consumir` esta fora da `ci/secdef_allowlist.yaml`, que
  o gate 6 confere);
* **o comportamento** — com o contexto de B e `p_tenant` de A, a funcao nao
  le o tecto de A (os entitlements de A sao invisiveis), nega, e nao escreve
  nada em nome de A.

A segunda metade e a que vale: o `p_tenant` e um argumento, e um argumento nao
e uma autorizacao. Quem o escolhe e a biblioteca, a partir do contexto; o que
impede que um valor errado funcione e a RLS a aplicar-se **dentro** da funcao.
"""

from __future__ import annotations

import unittest

import pg8000.dbapi

from tests.base import PRIVILEGIO_INSUFICIENTE, sqlstate
from tests_ten.base import CHAVE, ComUso


class TestIsolamentoDaFuncao(ComUso):
    def setUp(self) -> None:
        super().setUp()
        self.a = self.tenant_com_limite(100)
        self.b = self.tenant_com_limite(100)
        # A consome, pelo seu proprio contexto: e o que B vai tentar tocar.
        consumo = self.consumir(self.a, quantidade=5, idempotency_key="de-a")
        self.assertTrue(consumo.aceite)
        self.assertEqual(self.uso(self.a), 5)

    def test_b_nao_consome_contra_o_contador_de_a(self) -> None:
        """O caso do ticket, a letra."""
        consumo = self.consumir(
            self.a, contexto=self.b, quantidade=1, idempotency_key="de-b"
        )
        self.assertFalse(consumo.aceite)
        self.assertFalse(consumo.repetido)
        self.assertIsNone(
            consumo.limite,
            "o tecto de A foi lido com o contexto de B: a RLS nao se aplicou "
            "dentro da funcao",
        )
        self.assertEqual(int(consumo.valor), 0)
        self.assertEqual(self.uso(self.a), 5, "o contador de A moveu-se")
        self.assertFalse(self.no_livro(self.a, "de-b"))
        self.assertEqual(self.livro(self.b), [])

    def test_sem_contexto_nenhum_tambem_nega(self) -> None:
        """A cadeia vazia e o que a variavel vale quando o `SET LOCAL` expira."""
        consumo = self.consumir(
            self.a, contexto=None, quantidade=1, idempotency_key="sem"
        )
        self.assertFalse(consumo.aceite)
        self.assertIsNone(consumo.limite)
        self.assertEqual(self.uso(self.a), 5)

    def test_b_consome_contra_o_seu_e_nao_toca_em_a(self) -> None:
        """O controlo positivo: sem ele, «nega sempre» passava este ficheiro."""
        consumo = self.consumir(self.b, quantidade=2, idempotency_key="de-b")
        self.assertTrue(consumo.aceite)
        self.assertEqual((self.uso(self.a), self.uso(self.b)), (5, 2))

    def test_b_nao_le_o_contador_de_a(self) -> None:
        """A politica, pelo lado da leitura — vista de dentro desta suite."""
        cursor = self.cursor_app(self.b)
        cursor.execute(
            "SELECT count(*) FROM platform.tenant_usage WHERE tenant_id = %s",
            (self.a,),
        )
        self.assertEqual(int(cursor.fetchone()[0]), 0)
        cursor.execute(
            "SELECT count(*) FROM platform.usage_ledger WHERE tenant_id = %s",
            (self.a,),
        )
        self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_b_nao_escreve_no_contador_de_a(self) -> None:
        """E se tentasse a mao, sem a funcao: o `WITH CHECK` recusa.

        Confere-se o texto e nao so o `42501`: esse codigo e tambem o de um
        privilegio em falta, e um teste que aceitasse qualquer `42501` passava
        se alguem tirasse o `INSERT` a `kamba_app` — pela razao errada.
        """
        cursor = self.cursor_app(self.b)
        for sql, argumentos in (
            (
                "INSERT INTO platform.tenant_usage "
                "(tenant_id, chave_limite, periodo, valor) "
                "VALUES (%s::uuid, %s, platform.ten_periodo(), 1)",
                (self.a, CHAVE),
            ),
            (
                "INSERT INTO platform.usage_ledger "
                "(tenant_id, idempotency_key, chave_limite, periodo, quantidade) "
                "VALUES (%s::uuid, 'intrusa', %s, platform.ten_periodo(), 1)",
                (self.a, CHAVE),
            ),
        ):
            with self.subTest(sql=sql.split("(")[0].strip()):
                cursor.execute("SAVEPOINT caso_negativo")
                try:
                    with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                        cursor.execute(sql, argumentos)
                finally:
                    cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
                self.assertEqual(
                    sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE
                )
                self.assertIn("row-level security", str(capturado.exception))


class TestSecurityInvoker(ComUso):
    """O facto estrutural de que tudo o que esta acima depende."""

    def test_as_duas_funcoes_da_revisao_correm_como_quem_chama(self) -> None:
        self.assertEqual(
            self.consultar(
                "SELECT p.proname, p.prosecdef FROM pg_proc p "
                "  JOIN pg_namespace n ON n.oid = p.pronamespace "
                " WHERE n.nspname = 'platform' AND p.proname LIKE 'ten!_%' ESCAPE '!' "
                " ORDER BY 1"
            ),
            [("ten_consumir", False), ("ten_periodo", False)],
        )


if __name__ == "__main__":
    unittest.main()

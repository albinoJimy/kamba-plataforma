"""Os contactos do tenant pelo cofre, na purga (KAM-218, criterio 6), sem base.

A base falsa **le o texto** de cada instrucao (a licao do KAM-070): um duplo que
decidisse pelo argumento ficava verde com o predicado do tenant apagado. O que
so a base prova — o papel, a RLS, o tenant B intacto, o `purge_log` — esta em
`db/tests/test_offboarding.py` (`TestPurgaPeloCofre`).
"""

from __future__ import annotations

import unittest

from kamba_core.offboarding.cofre import (
    SQL_APAGAR_ENDPOINTS,
    SQL_DESTRUIR_DEKS,
    SQL_MARCAR_APAGADOS,
    apagar_contactos_pelo_cofre,
)

A = "11111111-1111-4111-8111-111111111111"


class Cursor:
    def __init__(self, ligacao: "Ligacao") -> None:
        self.ligacao = ligacao
        self.rowcount = 0

    def execute(self, sql: str, parametros: tuple = ()) -> None:
        self.ligacao.instrucoes.append((sql, tuple(parametros)))
        if "set_config" in sql:
            return
        if "WHERE tenant_id = %s" not in sql:
            raise AssertionError("uma instrucao do cofre sem o predicado do tenant")
        self.rowcount = self.ligacao.linhas.get(sql.split()[0] + " " + sql.split()[2 if sql.startswith("DELETE") else 1], 0)

    def fetchone(self):
        return ("",)

    def close(self) -> None:
        pass


class Ligacao:
    autocommit = False

    def __init__(self, linhas: dict[str, int] | None = None, falhar: bool = False) -> None:
        self.instrucoes: list[tuple[str, tuple]] = []
        self.linhas = linhas or {}
        self.falhar = falhar
        self.commits = 0
        self.rollbacks = 0
        self.fechada = False

    def cursor(self) -> Cursor:
        if self.falhar:
            raise RuntimeError("o cofre caiu")
        return Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.fechada = True


class TestApagarContactosPeloCofre(unittest.TestCase):
    def test_as_tres_instrucoes_do_erase_contact_pelo_tenant_numa_transaccao(self) -> None:
        ligacao = Ligacao({"UPDATE platform.contacts": 3})
        n = apagar_contactos_pelo_cofre(lambda: ligacao)(A)
        self.assertEqual(n, 3, "devolve os contactos marcados, e nao os endpoints")
        sqls = [s for s, _ in ligacao.instrucoes if "set_config" not in s]
        self.assertEqual(sqls, [SQL_APAGAR_ENDPOINTS, SQL_DESTRUIR_DEKS, SQL_MARCAR_APAGADOS])
        self.assertTrue(all(p == (A,) for s, p in ligacao.instrucoes if "set_config" not in s))
        self.assertEqual((ligacao.commits, ligacao.fechada), (1, True))

    def test_o_contexto_do_tenant_vem_antes_de_tudo(self) -> None:
        ligacao = Ligacao()
        apagar_contactos_pelo_cofre(lambda: ligacao)(A)
        self.assertIn("set_config", ligacao.instrucoes[0][0])

    def test_e_o_crypto_shredding_e_repetir_nao_marca_de_novo(self) -> None:
        self.assertIn("wrapped_dek = NULL", SQL_DESTRUIR_DEKS)
        self.assertIn("destroyed_at IS NULL", SQL_DESTRUIR_DEKS)
        self.assertIn("phone_hmac = NULL", SQL_MARCAR_APAGADOS)
        self.assertIn("erased_at IS NULL", SQL_MARCAR_APAGADOS)
        self.assertTrue(SQL_APAGAR_ENDPOINTS.startswith("DELETE FROM platform.contact_endpoints"))

    def test_uma_falha_sobe_e_a_ligacao_fecha(self) -> None:
        ligacao = Ligacao(falhar=True)
        with self.assertRaises(RuntimeError):
            apagar_contactos_pelo_cofre(lambda: ligacao)(A)
        self.assertTrue(ligacao.fechada)

    def test_um_tenant_sem_forma_recusa_antes_de_abrir(self) -> None:
        aberturas: list[int] = []
        with self.assertRaises(Exception):
            apagar_contactos_pelo_cofre(lambda: aberturas.append(1) or Ligacao())("nao-e-um-uuid")
        self.assertEqual(aberturas, [])


if __name__ == "__main__":
    unittest.main()

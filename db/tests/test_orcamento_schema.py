"""A revisao do Orcamento expresso: a descida e a volta (KAM-123).

O comportamento da `quote_requests` — a repeticao, o duplo toque, o gatilho, a
RLS e os privilegios por coluna exercidos pelo SQL do AGR — esta em
`../tests_agr/test_quote_requests.py`, que corre as instrucoes do modulo e nao
uma copia delas. As listas fechadas (colunas, restricoes, FK, privilegios) estao
nas suites de catalogo, inventario e privilegios. Aqui fica so o que e da
revisao: desce, larga tudo, e volta.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

RAIZ = Path(__file__).resolve().parents[2]
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_orcamento_expresso.py"))


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDoOrcamento(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
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

    def _objectos(self) -> tuple[int, int]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                "AND tablename = 'quote_requests'"
            )
            tabelas = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'quote_requests_transicao'")
            funcoes = int(c.fetchone()[0])
            return tabelas, funcoes
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        self.assertEqual(self._objectos(), (1, 1))
        alembic_ok("downgrade", _anterior())
        self.assertEqual(self._objectos(), (0, 0))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), (1, 1))

    def test_a_funcao_do_gatilho_nao_e_security_definer(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT prosecdef FROM pg_proc WHERE proname = 'quote_requests_transicao'")
            self.assertEqual(c.fetchone()[0], False)
        finally:
            conexao.close()


if __name__ == "__main__":
    unittest.main()

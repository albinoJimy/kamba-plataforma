"""A revisao do canal do dono pelo painel: a descida e a volta (KAM-223).

O comportamento das duas tabelas — o AGR a ler a mensagem do dono, a RLS e os
privilegios por coluna — esta em `../tests_agr/test_agent_messages.py`, que
corre a funcao do modulo, e em `packages/core-ts/tests_bd/dono.bd.test.ts`, que
corre a troca e a conversa como o processo as monta. As listas fechadas
(colunas, restricoes, privilegios) estao nas suites de inventario e de
privilegios. Aqui fica o que e da revisao: desce, larga as duas tabelas **e so
essas**, e volta.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

RAIZ = Path(__file__).resolve().parents[2]
#: Por *glob* e nao pelo numero: o numero da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_canal_do_dono_pelo_painel.py"))
NOVAS = {"agent_messages", "owner_phone_changes"}


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDoCanalDoDonoPeloPainel(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _estado(self) -> tuple[list[str], list[str], list[str]]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
            )
            tabelas = [l[0] for l in c.fetchall()]
            c.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'platform' "
                "AND tablename IN ('agent_messages', 'owner_phone_changes') ORDER BY 1"
            )
            indices = [l[0] for l in c.fetchall()]
            c.execute(
                "SELECT tablename || '.' || policyname FROM pg_policies "
                "WHERE schemaname = 'platform' ORDER BY 1"
            )
            politicas = [l[0] for l in c.fetchall()]
            return tabelas, indices, politicas
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        tabelas, indices, politicas = self._estado()
        self.assertTrue(NOVAS <= set(tabelas))
        self.assertIn("owner_phone_changes_viva_uq", indices)
        self.assertIn("agent_messages_conversa_idx", indices)
        alembic_ok("downgrade", _anterior())
        depois = self._estado()
        # **So estas**: as outras tabelas e as politicas delas ficam.
        self.assertEqual(depois[0], sorted(set(tabelas) - NOVAS))
        self.assertEqual(depois[1], [])
        self.assertEqual(
            depois[2], [p for p in politicas if p.split(".")[0] not in NOVAS]
        )
        alembic_ok("upgrade", "head")
        self.assertEqual(self._estado(), (tabelas, indices, politicas))


if __name__ == "__main__":
    unittest.main()

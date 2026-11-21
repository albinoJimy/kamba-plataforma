"""A revisao da resposta do AGR: a descida e a volta (KAM-224).

O comportamento da `agent_replies` — a repeticao, a concorrencia, a RLS e os
privilegios por coluna exercidos pelo SQL do AGR — esta em
`../tests_agr/test_agent_replies.py`, que corre a funcao do modulo e nao uma
copia dela. As listas fechadas (colunas, restricoes, FK, privilegios) estao nas
suites de catalogo, inventario e privilegios. Aqui fica o que e da revisao:
desce, larga a tabela e as **duas** subscricoes (e so essas), e volta.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

RAIZ = Path(__file__).resolve().parents[2]
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_resposta_do_agr.py"))


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _propria() -> str:
    """O `revision` da revisao, lido dela, pela mesma razao."""
    achado = re.search(r'^revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDaRespostaDoAgr(unittest.TestCase):
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

    def _estado(self) -> tuple[int, list[tuple[str, str]], int]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                "AND tablename = 'agent_replies'"
            )
            tabelas = int(c.fetchone()[0])
            c.execute(
                "SELECT consumer, tipo FROM platform.evt_subscricoes "
                "WHERE tipo = 'agent.replied' ORDER BY consumer"
            )
            subscricoes = [tuple(l) for l in c.fetchall()]
            c.execute("SELECT count(*) FROM platform.evt_subscricoes")
            todas = int(c.fetchone()[0])
            return tabelas, subscricoes, todas
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        tabelas, subscricoes, na_cabeca = self._estado()
        self.assertEqual(tabelas, 1)
        self.assertEqual(subscricoes, [("outbound", "agent.replied"), ("painel", "agent.replied")])
        # O «antes» mede-se **na propria revisao**, e nao na cabeca: uma revisao
        # de dados por cima (a `*_subscricao_do_dono.py`, KAM-215) apaga as linhas
        # dela na descida, e contadas na cabeca pareciam apagadas por esta.
        alembic_ok("downgrade", _propria())
        todas = self._estado()[2]
        alembic_ok("downgrade", _anterior())
        depois = self._estado()
        self.assertEqual(depois[:2], (0, []))
        # **So as duas**: as subscricoes das outras revisoes ficam.
        self.assertEqual(depois[2], todas - 2)
        alembic_ok("upgrade", "head")
        self.assertEqual(self._estado(), (tabelas, subscricoes, na_cabeca))

    def test_as_subscricoes_sao_de_atendimento_sem_ordem_e_ate_a_v2(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT DISTINCT versao_max, finalidade, exige_ordem, activo "
                "FROM platform.evt_subscricoes WHERE tipo = 'agent.replied'"
            )
            self.assertEqual([tuple(l) for l in c.fetchall()], [(2, "atendimento", False, True)])
        finally:
            conexao.close()


if __name__ == "__main__":
    unittest.main()

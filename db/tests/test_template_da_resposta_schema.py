"""A revisao do template da resposta do AGR: a descida e a volta (KAM-221).

O comportamento das duas colunas — o AGR a gravar o *template* com os valores,
as tres restricoes e o `INSERT` por coluna exercidos pelo SQL do AGR — esta em
`../tests_agr/test_template_da_resposta.py`, que corre a funcao do modulo. As
listas fechadas (colunas, restricoes, privilegios) estao nas suites de
inventario e de privilegios. Aqui fica o que e da revisao: desce, larga as duas
colunas e as tres restricoes **e so essas**, e volta.
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
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_template_da_resposta.py"))


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _propria() -> str:
    """O numero da propria revisao, lido do nome do ficheiro."""
    return REVISAO.name[:4]


class TestDowngradeDoTemplateDaResposta(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.

    **E compara na propria revisao, e nao na cabeca** (KAM-246): a `0092` pos
    a `media_ref` e duas restricoes na mesma tabela, e uma descida medida a
    partir da cabeca contava-as como desta revisao.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        # Os papeis, como o `ComBase`: a classe pode correr antes de qualquer outra.
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
                "SELECT attname FROM pg_attribute "
                "WHERE attrelid = 'platform.agent_replies'::regclass AND attnum > 0 "
                "AND NOT attisdropped ORDER BY attname"
            )
            colunas = [l[0] for l in c.fetchall()]
            c.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'platform.agent_replies'::regclass ORDER BY conname"
            )
            restricoes = [l[0] for l in c.fetchall()]
            c.execute(
                "SELECT column_name FROM information_schema.column_privileges "
                "WHERE table_schema = 'platform' AND table_name = 'agent_replies' "
                "AND grantee = 'kamba_app' AND privilege_type = 'INSERT' ORDER BY 1"
            )
            insert = [l[0] for l in c.fetchall()]
            return colunas, restricoes, insert
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _propria())
        colunas, restricoes, insert = self._estado()
        novas = {"template_nome", "template_parametros"}
        # As tres da revisao e, no PostgreSQL 18, o `NOT NULL` da coluna, que o
        # catalogo tambem lista como restricao e que cai com ela.
        tres = {r for r in restricoes if r.startswith("agent_replies_template")}
        self.assertTrue(
            {
                "agent_replies_template_ck",
                "agent_replies_template_nome_ck",
                "agent_replies_template_parametros_ck",
            }
            <= tres
        )
        self.assertTrue(novas <= set(colunas))
        self.assertTrue(novas <= set(insert))
        alembic_ok("downgrade", _anterior())
        depois = self._estado()
        # **So estas**: as colunas, as restricoes e o `INSERT` da `0073` ficam.
        self.assertEqual(depois[0], sorted(set(colunas) - novas))
        self.assertEqual(depois[1], sorted(set(restricoes) - tres))
        self.assertEqual(depois[2], sorted(set(insert) - novas))
        alembic_ok("upgrade", _propria())
        self.assertEqual(self._estado(), (colunas, restricoes, insert))


if __name__ == "__main__":
    unittest.main()

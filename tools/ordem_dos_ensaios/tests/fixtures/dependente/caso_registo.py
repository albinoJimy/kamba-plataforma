"""Duas classes com a forma do defeito: uma suja estado de processo e nao o
repoe, a outra afirma que esse estado esta limpo.

Na ordem de omissao do `unittest` a leitora corre primeiro — `TestALeitura`
antes de `TestZEscrita`, por ordem alfabetica — e passa. Na ordem inversa a
escritora corre primeiro e a leitora fica vermelha. **Nada mais do que a ordem
alfabetica das classes separa estas duas situacoes**, que e exactamente o que o
ensaio do KAM-163 mostrou sobre si proprio.

O estado partilhado e um conjunto a nivel de modulo, que e a forma mais comum
desta familia neste repositorio: o `_EM_USO` do `tenant_guard`, o `CONTADORES`
do *logger*, o nivel de um *logger* com nome, uma entrada do `sys.modules`.

Esta *fixture* **nao** e corrida pelas suites de `tools/`: o
`unittest discover` delas usa o padrao `test*.py` e este ficheiro chama-se
`caso_*.py`. Se o nome mudar, o *gate* 4 fica vermelho por desenho.
"""

from __future__ import annotations

import unittest

#: Estado de processo. Vive enquanto o modulo estiver no `sys.modules`, que num
#: processo de `unittest` e do inicio ao fim.
REGISTO: set[str] = set()


class TestALeitura(unittest.TestCase):
    def test_o_registo_comeca_vazio(self) -> None:
        self.assertEqual(REGISTO, set())


class TestZEscrita(unittest.TestCase):
    def test_escreve_no_registo_e_nao_o_repoe(self) -> None:
        REGISTO.add('ficou para tras')
        self.assertIn('ficou para tras', REGISTO)

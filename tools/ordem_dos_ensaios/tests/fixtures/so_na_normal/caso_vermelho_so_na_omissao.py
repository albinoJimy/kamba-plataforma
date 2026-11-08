"""Um vermelho **so na ordem de omissao**, verde na inversa.

E a direccao que as tres comparacoes entre ordens do `cli` nao cobrem: o
`pela_ordem` e o `nas_duas` olham para os vermelhos da **inversa**, e o
`so_numa` compara inventarios. Um teste verde na inversa e vermelho na de
omissao nao cai em nenhuma delas e chega a rede, onde o `wasSuccessful()` da
ordem normal e falso — e onde a mensagem dizia que o instrumento perdeu a
informacao quando o `Registo` o tinha nomeado.

E a mesma familia da *fixture* `dependente/`, com as duas classes ao contrario:
aqui a **escritora** corre primeiro na ordem de omissao (`TestAEscrita` antes de
`TestZLeitura`, por ordem alfabetica) e a leitora fica vermelha; na inversa a
leitora corre primeiro, com o registo ainda limpo, e passa.

Nao e dependencia de ordem menos grave do que a outra — e a mesma, no outro
sentido —, e o remedio e o mesmo: quem suja o estado de processo repoe-no.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest

REGISTO: set[str] = set()


class TestAEscrita(unittest.TestCase):
    def test_escreve_no_registo_e_nao_o_repoe(self) -> None:
        REGISTO.add('ficou para tras')
        self.assertIn('ficou para tras', REGISTO)


class TestZLeitura(unittest.TestCase):
    def test_o_registo_comeca_vazio(self) -> None:
        self.assertEqual(REGISTO, set())

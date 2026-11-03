"""Uma *fixture* vermelha nas **duas** ordens: um teste quebrado, nao um teste
dependente da ordem.

Existe pela terceira metade do canario, que a primeira versao deste portao nao
tinha e que a revisao adversarial destapou. Com uma passagem so — a inversa —, o
portao dava um teste quebrado por «dependente da ordem», e mandava corrigir a
coisa errada. Pior: as duas passagens de entao diferiam tambem no **rastreador
do `coverage`** (a de omissao era a do `coverage-python`, esta nao), e o
`specs/tickets/KAM-163.md` registra que duas versoes do mesmo ensaio ficaram
vermelhas sem nada mudar no codigo — uma pela ordem das classes, **outra pelo
rastreador**.

Agora as duas ordens correm aqui, nas mesmas condicoes, e esta *fixture* prende
a distincao: um vermelho nas duas sai com a mensagem que manda procurar no
`coverage-python`, nao no estado de processo.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar — com um nome `test_*.py` fazia o *gate* 4 vermelho por
desenho.
"""

from __future__ import annotations

import unittest


class TestQuebrado(unittest.TestCase):
    def test_falha_em_qualquer_ordem(self) -> None:
        self.assertEqual(1, 2, 'vermelho de proposito, nas duas ordens')


class TestVerde(unittest.TestCase):
    def test_passa_em_qualquer_ordem(self) -> None:
        self.assertEqual(1, 1)

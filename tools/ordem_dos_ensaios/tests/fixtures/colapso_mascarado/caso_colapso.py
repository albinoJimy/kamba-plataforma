"""O `id()` repetido **mascarado** por entradas que nao sao testes.

Tres metodos a devolver o mesmo `id()`, como na *fixture* `id_repetido/`: o
`estado` colapsa em uma chave e o vermelho do meio fica apagado pela escrita
seguinte. A diferenca esta nas duas irmas deste ficheiro, cujos `setUpModule`
levantam `SkipTest`: cada uma injecta no `estado` uma frase
(`setUpModule (caso_salta_*)`) que **nao e um caso**, e as duas enchem a conta
que o colapso tinha esvaziado.

Com `corridos - len(estado)` como medida — que era a do KAM-182 na sua primeira
versao — da `3 - 3 = 0`, a hipotese do `id()` repetido fica **calada**, e o
portao anuncia no lugar dela a hipotese da classificacao sobrescrita, sem dizer
quem a sobrescreveu. Com `corridos - corridos_distintos`, que conta so o que
passou pelo `startTest`, da `3 - 1 = 2` e a hipotese sai nomeada.

Achado da revisao adversarial do KAM-182. E tambem o que desmonta uma frase do
Contexto do bloco: `1402 == 1402` **nao** exclui o `id()` repetido, porque o
numero da direita era `len(estado)` e podia estar cheio de frases.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest

#: O `id()` que os tres metodos partilham.
IDENTIFICADOR = 'caso_colapso.TestColapso.test_o_mesmo_id'


class TestColapso(unittest.TestCase):
    def id(self) -> str:
        return IDENTIFICADOR

    def test_a_passa(self) -> None:
        pass

    def test_b_falha(self) -> None:
        self.fail('vermelho de proposito, escondido pelo id() repetido')

    def test_c_passa(self) -> None:
        pass

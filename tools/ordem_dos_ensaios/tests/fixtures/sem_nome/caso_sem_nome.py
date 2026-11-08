"""O caso em que **nem o `TestResult`** nomeia um caso, e o portão continua a
recusar: o critério 2 do KAM-182.

E possivel, e a *fixture* irma `sem_caso/` mostra a forma real: um erro de
`setUpClass`, `tearDownClass`, `setUpModule` ou `tearDownModule` entra num
`unittest.suite._ErrorHolder`, cujo `id()` e uma frase (`tearDownModule
(modulo)`) e nao um identificador de caso. So que por **essa** via o erro passa
pelo `addError`, e o `Registo` guarda a frase no `estado`: a comparacao entre as
duas ordens apanha-a antes da rede, e sai com 1. (Tirar a frase do `estado` para
a trazer ate aqui foi tentado e **desfez-se**: cegava o canario. Esta escrito no
`addError` do `corredor`.)

Esta *fixture* traz a mesma situacao ao ramo da discordancia pelo caminho que a
produz de facto: a entrada chega ao `errors` **sem** passar pelo `addError`,
pelo que nao existe no `estado` e nada a nomeia. E a forma de um sinal que o
`unittest` acrescente no futuro e que nem seja um caso.

O resultado tem de ser: **nenhum `id()` de teste nomeado, codigo de saida 2, e
a mensagem a dizer que a falha e do portao**. Recusar o verde quando nao se sabe
nao e negociavel — um corredor que nomeie melhor mas passe a dar verde e pior do
que o que havia.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest


def entrada_sem_caso(etiqueta: str) -> object:
    """Um objecto com a forma do `_ErrorHolder`: tem `id()`, nao e um caso.

    A classe e **local a esta funcao** e nao de modulo pela razao medida na
    *fixture* `sem_derrubar/`: de modulo, o `loadTestsFromModule` colhe
    subclasses de `TestCase` — e esta nao o e, mas fica local pela mesma
    higiene, para o ficheiro nao exportar nada que o carregador olhe.
    """

    class EntradaSemCaso:
        def id(self) -> str:
            return etiqueta

        def __str__(self) -> str:
            return etiqueta

    return EntradaSemCaso()


class TestSemNome(unittest.TestCase):
    def test_passa_e_a_entrada_sem_caso_entra_por_fora(self) -> None:
        resultado = self._outcome.result
        resultado.errors.append(
            (
                entrada_sem_caso('tearDownModule (caso_sem_nome)'),
                'Traceback (most recent call last):\n'
                '  ...\n'
                'RuntimeError: entrada sem caso, de proposito\n',
            )
        )

"""O canario, e o canario do canario.

Os casos abaixo nao correm as *fixtures*: injectam um corredor falso e
verificam que o `verificar` recusa cada modo de falha. E o nivel que falta a
um canario — ele prova que o portao morde, e isto prova que ele proprio
morderia se o portao deixasse de morder.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ordem_dos_ensaios import canario
from ordem_dos_ensaios.corredor import Resultado

DEPENDENTE = next(c for c in canario.CASOS if c.codigo == 'dependente')
INDEPENDENTE = next(c for c in canario.CASOS if c.codigo == 'independente')


def _corredor(por_ordem: dict[str, Resultado]):
    def correr(pasta: Path, ordem: str) -> Resultado:
        del pasta
        return por_ordem[ordem]

    return correr


def _verde(n: int = 2) -> Resultado:
    return Resultado({f'caso.T.test_{i}': 'ok' for i in range(n)}, n)


def _com_vermelho(identificador: str) -> Resultado:
    return Resultado({identificador: 'failure', 'caso.T.test_outro': 'ok'}, 2)


class TestOsCasosDeclarados(unittest.TestCase):
    def test_sao_dois_e_um_morde(self) -> None:
        self.assertEqual(len(canario.CASOS), 2)
        self.assertEqual(
            sum(1 for c in canario.CASOS if not c.inversa_verde),
            1,
            'um canario sem o caso que distingue passa com o verificador '
            'quebrado',
        )

    def test_quem_morde_declara_o_teste_que_fica_vermelho(self) -> None:
        for caso in canario.CASOS:
            if caso.inversa_verde:
                self.assertIsNone(caso.vermelho_esperado)
            else:
                self.assertIsNotNone(caso.vermelho_esperado)

    def test_as_pastas_das_fixtures_existem(self) -> None:
        for caso in canario.CASOS:
            self.assertTrue((canario.FIXTURES / caso.pasta).is_dir())


class TestVerificarAsFixturesReais(unittest.TestCase):
    """Com o corredor real, mas dentro deste processo.

    Nao e a prova do portao — essa e o `make ordem-dos-ensaios`, que corre cada
    ordem no seu processo. E a prova de que os dois casos declarados batem com
    as *fixtures* que estao no disco.
    """

    def correr_fora(self, pasta: Path, ordem: str) -> Resultado:
        from ordem_dos_ensaios import cli

        return cli._correr_fora(pasta, pasta, canario.PADRAO, ordem)

    def test_os_dois_casos_ficam_conforme(self) -> None:
        for caso in canario.CASOS:
            with self.subTest(caso=caso.codigo):
                self.assertEqual(canario.verificar(caso, self.correr_fora), [])


class TestOCanarioRecusaOVerificadorQuebrado(unittest.TestCase):
    def test_um_verificador_que_nunca_morde(self) -> None:
        """Tudo verde nas duas ordens: o caso `dependente` tem de queixar-se."""
        queixas = canario.verificar(
            DEPENDENTE, _corredor({'normal': _verde(), 'inversa': _verde()})
        )
        self.assertEqual(len(queixas), 1)
        self.assertIn('O portao deixou de morder', queixas[0])

    def test_um_verificador_que_morde_sempre(self) -> None:
        """Tudo vermelho: o caso `independente` tem de queixar-se das duas
        ordens, e e essa metade que um canario de um caso so nao tem."""
        vermelho = _com_vermelho('caso_registo.TestALeitura.test_qualquer')
        queixas = canario.verificar(
            INDEPENDENTE, _corredor({'normal': vermelho, 'inversa': vermelho})
        )
        self.assertEqual(len(queixas), 2)
        self.assertIn('precondicao', queixas[0])
        self.assertIn('prova', queixas[1])

    def test_uma_fixture_quebrada_e_precondicao_e_nao_prova(self) -> None:
        """Vermelha **nas duas** ordens: nenhuma ordem foi medida.

        E o modo de falha proprio de um canario por *fixture*: um `import`
        partido ou um teste renomeado punha o caso a «morder» sem nada ter sido
        medido. A queixa tem de ser da precondicao, nao da prova.
        """
        quebrada = _com_vermelho(DEPENDENTE.vermelho_esperado or '')
        queixas = canario.verificar(
            DEPENDENTE, _corredor({'normal': quebrada, 'inversa': quebrada})
        )
        self.assertEqual(len(queixas), 1)
        self.assertIn('precondicao', queixas[0])

    def test_uma_fixture_vazia_e_precondicao(self) -> None:
        """Zero testes descobertos nunca e uma *fixture* limpa."""
        vazio = Resultado({}, 0)
        queixas = canario.verificar(
            DEPENDENTE, _corredor({'normal': vazio, 'inversa': vazio})
        )
        self.assertEqual(len(queixas), 2)
        for queixa in queixas:
            self.assertIn('nao correu', queixa)

    def test_um_vermelho_no_teste_errado_e_prova_invalida(self) -> None:
        """A *fixture* ficou vermelha, mas noutro teste: nao prova nada."""
        queixas = canario.verificar(
            DEPENDENTE,
            _corredor(
                {
                    'normal': _verde(),
                    'inversa': _com_vermelho('caso_registo.TestZ.test_outra'),
                }
            ),
        )
        self.assertEqual(len(queixas), 1)
        self.assertIn('prova invalida', queixas[0])

    def test_uma_pasta_que_desapareceu_e_queixa(self) -> None:
        inexistente = canario.Caso(
            codigo='fantasma',
            descricao='a pasta nao existe',
            pasta='nao-existe',
            normal_verde=True,
            inversa_verde=False,
            vermelho_esperado='x',
        )
        queixas = canario.verificar(inexistente, _corredor({}))
        self.assertEqual(len(queixas), 1)
        self.assertIn('nao existe', queixas[0])

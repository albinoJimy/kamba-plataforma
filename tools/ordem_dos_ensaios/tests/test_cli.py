"""A linha de comando, e a cablagem no `Makefile`.

Os codigos de saida sao a parte que mais importa: 2 e «nao se conseguiu
verificar» e nunca pode parecer verde. E a licao do `db/correr_suite.py` — num
gate, saltar e falhar — e a do `lint_arch` sem `check`, que saia com 2 e passava
por distraccao.
"""

from __future__ import annotations

import io
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ordem_dos_ensaios import canario
from ordem_dos_ensaios.cli import main

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / 'Makefile'


def _correr(argv: list[str]) -> tuple[int, str, str]:
    fora, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(fora), redirect_stderr(erro):
        codigo = main(argv)
    return codigo, fora.getvalue(), erro.getvalue()


class TestCheck(unittest.TestCase):
    def test_uma_suite_independente_da_ordem_passa(self) -> None:
        codigo, fora, _ = _correr(
            [
                '--root',
                str(canario.FIXTURES),
                'check',
                '--suite',
                'independente',
                '--padrao',
                canario.PADRAO,
                '--nome',
                'fixture independente',
            ]
        )
        self.assertEqual(codigo, 0)
        self.assertIn('0 vermelhos', fora)

    def test_uma_suite_dependente_da_ordem_falha_com_1(self) -> None:
        codigo, _, erro = _correr(
            [
                '--root',
                str(canario.FIXTURES),
                'check',
                '--suite',
                'dependente',
                '--padrao',
                canario.PADRAO,
            ]
        )
        self.assertEqual(codigo, 1)
        self.assertIn('ordem inversa', erro)
        self.assertIn('test_o_registo_comeca_vazio', erro)

    def test_a_queixa_nomeia_o_remedio(self) -> None:
        """Quem ve o portao vermelho tem de saber o que fazer com ele."""
        _, _, erro = _correr(
            [
                '--root',
                str(canario.FIXTURES),
                'check',
                '--suite',
                'dependente',
                '--padrao',
                canario.PADRAO,
            ]
        )
        self.assertIn('reposto por quem o suja', erro)

    def test_uma_suite_que_nao_existe_sai_com_2(self) -> None:
        codigo, _, erro = _correr(
            ['--root', str(ROOT), 'check', '--suite', 'nao/existe']
        )
        self.assertEqual(codigo, 2)
        self.assertIn('nao existe', erro)

    def test_uma_pasta_sem_testes_sai_com_2(self) -> None:
        """Zero testes descobertos e «nao verificou», nunca «esta limpo»."""
        codigo, _, erro = _correr(
            ['--root', str(ROOT / 'tools'), 'check', '--suite', 'requirements']
        )
        self.assertEqual(codigo, 2)
        self.assertIn('nenhum teste', erro)


class TestCanario(unittest.TestCase):
    def test_o_canario_do_repositorio_passa(self) -> None:
        codigo, fora, erro = _correr(['canario'])
        self.assertEqual(codigo, 0, erro)
        self.assertIn('2 de 2 casos conforme', fora)


class TestCablagemNoMakefile(unittest.TestCase):
    """O portao so e portao se o *gate* 4 o correr.

    Nao se corre o `make` aqui — a maquina de execucao pode nao o ter, e nao o
    tem — pelo que se verifica o texto, no padrao de
    `tools/lint_arch/tests/test_makefile.py`.
    """

    def setUp(self) -> None:
        self.texto = MAKEFILE.read_text(encoding='utf-8')

    def test_o_ci_4_depende_deste_alvo(self) -> None:
        linha = re.search(r'^ci-4:.*$', self.texto, flags=re.MULTILINE)
        self.assertIsNotNone(linha)
        self.assertIn('ordem-dos-ensaios', linha.group(0))

    def test_corre_depois_do_coverage_python(self) -> None:
        """Sem a ordem de omissao exigida verde antes, um vermelho na inversa
        nao distingue «dependente da ordem» de «teste quebrado»."""
        linha = re.search(r'^ci-4:(.*)$', self.texto, flags=re.MULTILINE)
        pre = linha.group(1).split()
        self.assertLess(
            pre.index('coverage-python'), pre.index('ordem-dos-ensaios')
        )

    def test_o_alvo_existe_e_esta_em_phony(self) -> None:
        self.assertRegex(self.texto, r'(?m)^ordem-dos-ensaios:')
        bloco = self.texto[self.texto.index('.PHONY:') :]
        bloco = bloco[: bloco.index('\n\n')]
        self.assertIn('ordem-dos-ensaios', bloco.split())

    def test_o_alvo_corre_o_canario_antes_das_suites(self) -> None:
        receita = self.texto[self.texto.index('\nordem-dos-ensaios:') :]
        receita = receita[: receita.index('\n\n')]
        self.assertLess(
            receita.index('canario'),
            receita.index('check'),
            'nao vale correr as suites para provar uma propriedade cujo '
            'verificador nao se provou',
        )

    def test_as_suites_cobertas_sao_as_declaradas(self) -> None:
        receita = self.texto[self.texto.index('\nordem-dos-ensaios:') :]
        receita = receita[: receita.index('\n\n')]
        self.assertEqual(
            set(re.findall(r'--suite (\S+)', receita)),
            {'libs/py-core/tests', 'services/agr/tests'},
            'as suites cobertas mudaram; o bloco do KAM-173 declara quais sao '
            'e porque as outras ficam de fora',
        )

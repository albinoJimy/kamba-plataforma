"""Os codigos de saida, e o contrato que eles sao.

`0 = conforme, 1 = achados, 2 = configuracao` e o mesmo contrato dos irmaos. A
distincao entre 1 e 2 e o que impede o pior modo de falha deste gate: dizer
«conforme» por nao ter conseguido ler o backlog.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from lint_backlog import cli
from lint_backlog.tests.conjunto import Conjunto, kam


class Base(unittest.TestCase):
    def correr(self, conjunto: Conjunto | None, *argumentos,
               pasta: Path | None = None) -> tuple[int, str, str]:
        if pasta is None:
            pasta = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, pasta, True)
            if conjunto is not None:
                conjunto.escrever(pasta)
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = cli.main(['--root', str(pasta), *argumentos])
        return codigo, saida.getvalue(), erro.getvalue()


class TestCodigosDeSaida(Base):
    """A *fixture* tem cinco blocos; o minimo real recusa-a, e isso prova-o."""

    def test_o_conjunto_pequeno_e_recusado_com_2(self) -> None:
        codigo, _, erro = self.correr(Conjunto(), 'check')
        self.assertEqual(codigo, 2)
        self.assertIn('esperam-se pelo menos', erro)

    def test_raiz_inexistente_da_2(self) -> None:
        codigo, _, erro = self.correr(
            None, 'check', pasta=Path(tempfile.gettempdir()) / 'nao-existe-mesmo')
        self.assertEqual(codigo, 2)
        self.assertIn('raiz inexistente', erro)

    def test_sem_indice_da_2(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        codigo, _, erro = self.correr(None, 'check', pasta=pasta)
        self.assertEqual(codigo, 2)
        self.assertIn('erro de configuracao', erro)

    def test_allow_ilegivel_da_2(self) -> None:
        conjunto = Conjunto()
        conjunto.allow = 'version: 1\ncabecalhos:\n  - ancora: &a 1\n'
        codigo, _, erro = self.correr(conjunto, 'check')
        self.assertEqual(codigo, 2)
        self.assertIn('erro de configuracao', erro)


class TestSobreOConjuntoReal(Base):
    """O conjunto a serio, pela raiz do repositorio.

    E o unico teste que usa o minimo verdadeiro, e e deliberado: e aqui que se
    verifica que a guarda contra o vazio esta calibrada para a populacao real.
    """

    RAIZ = Path(__file__).resolve().parents[3]

    def test_o_check_passa_sobre_o_conjunto(self) -> None:
        codigo, saida, erro = self.correr(None, 'check', pasta=self.RAIZ)
        self.assertEqual(codigo, 0, erro)
        self.assertIn('conforme', saida)

    def test_o_censo_imprime_as_tres_superficies(self) -> None:
        codigo, saida, _ = self.correr(None, 'censo', pasta=self.RAIZ)
        self.assertEqual(codigo, 0)
        for marca in ('linhas do §4', 'blocos', 'linhas do §3',
                      'controlo de versões', 'documentos com tabela'):
            self.assertIn(marca, saida)

    def test_as_tres_superficies_tem_o_mesmo_tamanho(self) -> None:
        veredicto = cli.verificar(self.RAIZ)
        estatisticas = veredicto.estatisticas
        self.assertEqual(estatisticas['linhas'], estatisticas['blocos'])
        self.assertEqual(estatisticas['linhas'], estatisticas['resumos'])

    def test_toda_a_declaracao_do_allow_casa_alguma_coisa(self) -> None:
        """Uma declaracao morta e codigo 2; aqui mede-se que nao ha nenhuma."""
        self.assertEqual(cli.verificar(self.RAIZ).configuracao, [])


class TestMensagens(Base):
    def test_a_falha_diz_que_o_gate_nao_escolhe_o_lado(self) -> None:
        conjunto = Conjunto()
        conjunto.ticket(2).no_bloco['tipo'] = 'feature'
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        conjunto.escrever(pasta)
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            veredicto = cli.verificar(pasta, minimo=1)
        self.assertTrue(any(kam(2) in a for a in veredicto.achados))


if __name__ == '__main__':
    unittest.main()

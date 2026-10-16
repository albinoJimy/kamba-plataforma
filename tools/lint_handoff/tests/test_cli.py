"""Testes da interface de linha de comando do `lint_handoff`.

O que importa aqui e o **codigo de saida**, porque e dele que o gate 3 depende:
0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao entre 1 e 2 e
a que impede uma arvore que nao se encontrou de parecer uma arvore limpa.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from lint_handoff.cli import main

CERCA = '```'


def _bloco(corpo: str) -> str:
    return f'### Handoff para Claude Code\n\n{CERCA}text\n{corpo}\n{CERCA}\n'


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / 'specs').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _epic(self, nome: str, corpo: str) -> Path:
        f = self.raiz / 'specs' / nome
        f.write_text(_bloco(corpo), encoding='utf-8')
        return f

    def _correr(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(['--root', str(self.raiz), *argv])
        return rc, out.getvalue(), err.getvalue()


class TestCheck(_Base):
    def test_arvore_conforme_sai_zero(self) -> None:
        self._epic('EPIC-01_A.md', 'Le docs/tecnica/00.md e specs/INDICE.md')
        rc, out, _ = self._correr('check')
        self.assertEqual(rc, 0)
        self.assertIn('conforme', out)
        self.assertIn('0 defeituoso', out)

    def test_caminho_acima_da_raiz_sai_um(self) -> None:
        self._epic('EPIC-01_A.md', 'Le ../docs/tecnica/00.md')
        rc, out, _ = self._correr('check')
        self.assertEqual(rc, 1)
        self.assertIn('../docs/tecnica/00.md', out)
        self.assertIn('fora da arvore', out)

    def test_nome_sem_directorio_sai_um(self) -> None:
        self._epic('EPIC-01_A.md', 'Le 14-tese-minima-e-plano-de-validacao.md')
        rc, out, _ = self._correr('check')
        self.assertEqual(rc, 1)
        self.assertIn('falta o directorio', out)

    def test_a_mensagem_diz_o_ficheiro_e_a_linha(self) -> None:
        self._epic('EPIC-01_A.md', 'Le ../docs/x.md')
        _, out, _ = self._correr('check')
        self.assertIn('specs/EPIC-01_A.md:4', out)

    def test_conta_os_ficheiros_e_nao_so_os_achados(self) -> None:
        self._epic('EPIC-01_A.md', 'Le ../docs/a.md')
        self._epic('EPIC-02_B.md', 'Le ../docs/b.md')
        rc, out, _ = self._correr('check')
        self.assertEqual(rc, 1)
        self.assertIn('2 caminho(s) defeituoso(s) em 2 ficheiro(s)', out)

    def test_remete_para_a_regra(self) -> None:
        """Uma mensagem que nao diz onde esta a regra obriga a adivinhar."""
        self._epic('EPIC-01_A.md', 'Le ../docs/x.md')
        _, out, _ = self._correr('check')
        self.assertIn('01_Engineering_Standards_e_Handoff.md', out)
        self.assertIn('KAM-145', out)


class TestCenso(_Base):
    def test_imprime_a_populacao_por_classe(self) -> None:
        self._epic('EPIC-01_A.md', 'Le ../docs/a.md e docs/b.md')
        rc, out, _ = self._correr('censo')
        self.assertEqual(rc, 0)
        self.assertIn('acima-da-raiz', out)
        self.assertIn('relativo-a-raiz', out)
        self.assertIn('TOTAL', out)
        self.assertIn('2 ocorrencia(s) em 1 ficheiro(s)', out)

    def test_o_censo_nao_falha_com_defeitos(self) -> None:
        """O censo mede; nao julga. Quem julga e o `check`."""
        self._epic('EPIC-01_A.md', 'Le ../docs/a.md')
        self.assertEqual(self._correr('censo')[0], 0)


class TestFile(_Base):
    def test_varre_um_ficheiro_relativo_a_raiz(self) -> None:
        self._epic('EPIC-01_A.md', 'Le ../docs/x.md')
        rc, out, _ = self._correr('file', 'specs/EPIC-01_A.md')
        self.assertEqual(rc, 1)
        self.assertIn('../docs/x.md', out)

    def test_ficheiro_sem_bloco_de_handoff_sai_zero(self) -> None:
        (self.raiz / 'specs' / 'EPIC-09_X.md').write_text('prosa com ../docs/x.md\n',
                                                          encoding='utf-8')
        rc, _, _ = self._correr('file', 'specs/EPIC-09_X.md')
        self.assertEqual(rc, 0)

    def test_ficheiro_inexistente_sai_dois(self) -> None:
        rc, _, err = self._correr('file', 'specs/nao-existe.md')
        self.assertEqual(rc, 2)
        self.assertIn('inexistente', err)


class TestErroDeConfiguracao(_Base):
    def test_raiz_inexistente_sai_dois(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(['--root', str(self.raiz / 'nao-existe'), 'check'])
        self.assertEqual(rc, 2)
        self.assertIn('raiz inexistente', err.getvalue())

    def test_arvore_sem_blocos_sai_dois_e_nao_zero(self) -> None:
        """Uma arvore vazia nao pode parecer uma arvore limpa."""
        rc, _, err = self._correr('check')
        self.assertEqual(rc, 2)
        self.assertIn('nenhum bloco de handoff', err)

    def test_padrao_que_nao_casa_nada_sai_dois(self) -> None:
        self._epic('EPIC-01_A.md', 'Le docs/x.md')
        rc, _, err = self._correr('--padrao', 'specs/NADA-*.md', 'check')
        self.assertEqual(rc, 2)
        self.assertIn('nenhum bloco de handoff', err)


if __name__ == '__main__':
    unittest.main()

"""Testes da varredura dos blocos de handoff.

Cada caso fixa uma fronteira que a primeira versao errou ou podia errar: onde o
bloco comeca, onde acaba, e o que conta como caminho.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lint_handoff.scan import varrer_arvore, varrer_ficheiro

CERCA = '```'


def _doc(corpo: str) -> str:
    return corpo.replace('§', CERCA)


class TestFronteiraDoBloco(unittest.TestCase):
    """O que esta dentro e o que esta fora de um bloco de handoff."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _varrer(self, corpo: str):
        f = self.raiz / 'specs'
        f.mkdir(exist_ok=True)
        alvo = f / 'EPIC-99_Teste.md'
        alvo.write_text(_doc(corpo), encoding='utf-8')
        return varrer_ficheiro(alvo, self.raiz)

    def test_le_o_que_esta_dentro_da_cerca(self) -> None:
        a = self._varrer('### Handoff para Claude Code\n\n§text\nLe ../docs/x.md\n§\n')
        self.assertEqual([(x.classe, x.texto) for x in a], [('acima-da-raiz', '../docs/x.md')])

    def test_ignora_o_que_esta_antes_do_titulo(self) -> None:
        self.assertEqual(self._varrer('Prosa com ../docs/x.md\n\n'
                                      '### Handoff para Claude Code\n\n§text\nnada\n§\n'), [])

    def test_ignora_o_que_esta_depois_da_cerca(self) -> None:
        self.assertEqual(self._varrer('### Handoff para Claude Code\n\n§text\nnada\n§\n\n'
                                      'Prosa com ../docs/x.md\n'), [])

    def test_um_titulo_antes_da_cerca_fecha_o_bloco(self) -> None:
        """Um ficheiro truncado nao faz a varredura engolir o resto."""
        self.assertEqual(self._varrer('### Handoff para Claude Code\n\n'
                                      '## Controlo de versoes\n\n§text\n../docs/x.md\n§\n'), [])

    def test_titulo_sem_cerca_no_fim_do_ficheiro_nao_rebenta(self) -> None:
        self.assertEqual(self._varrer('### Handoff para Claude Code\n'), [])

    def test_cerca_sem_fecho_para_no_fim_do_ficheiro(self) -> None:
        a = self._varrer('### Handoff para Claude Code\n\n§text\n../docs/x.md\n')
        self.assertEqual(len(a), 1)

    def test_dois_blocos_no_mesmo_ficheiro(self) -> None:
        a = self._varrer('### Handoff para Claude Code\n\n§text\n../docs/a.md\n§\n\n'
                         '## KAM-002 — t\n\n### Handoff para Claude Code\n\n§text\n'
                         '../docs/b.md\n§\n')
        self.assertEqual([x.texto for x in a], ['../docs/a.md', '../docs/b.md'])


class TestClassificacao(unittest.TestCase):
    """Cada forma de caminho na sua classe."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / 'specs').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _classes(self, linha: str) -> list[tuple[str, str]]:
        alvo = self.raiz / 'specs' / 'EPIC-99_Teste.md'
        alvo.write_text(_doc(f'### Handoff para Claude Code\n\n§text\n{linha}\n§\n'),
                        encoding='utf-8')
        return [(x.classe, x.texto) for x in varrer_ficheiro(alvo, self.raiz)]

    def test_relativo_a_raiz_e_conforme(self) -> None:
        self.assertEqual(self._classes('Le docs/tecnica/00.md'),
                         [('relativo-a-raiz', 'docs/tecnica/00.md')])

    def test_acima_da_raiz_e_defeito(self) -> None:
        self.assertEqual(self._classes('Le ../docs/tecnica/00.md'),
                         [('acima-da-raiz', '../docs/tecnica/00.md')])

    def test_o_docs_de_um_acima_da_raiz_nao_conta_duas_vezes(self) -> None:
        """A dupla contagem que a medicao do ticket apanhou: um so achado."""
        self.assertEqual(len(self._classes('Le ../docs/x.md')), 1)

    def test_nome_nu_da_biblioteca_e_defeito(self) -> None:
        self.assertEqual(self._classes('Le 14-tese-minima-e-plano-de-validacao.md §2'),
                         [('sem-directorio', '14-tese-minima-e-plano-de-validacao.md')])

    def test_nome_da_biblioteca_com_directorio_nao_e_defeito(self) -> None:
        self.assertEqual(
            self._classes('Le docs/exploracao/14-tese-minima-e-plano-de-validacao.md'),
            [('relativo-a-raiz', 'docs/exploracao/14-tese-minima-e-plano-de-validacao.md')])

    def test_varios_caminhos_na_mesma_linha(self) -> None:
        """Pela ordem em que aparecem na linha, e nao agrupados por classe."""
        self.assertEqual(self._classes('Le specs/x.md e ../docs/y.md e tools/z.py'),
                         [('relativo-a-raiz', 'specs/x.md'),
                          ('acima-da-raiz', '../docs/y.md'),
                          ('relativo-a-raiz', 'tools/z.py')])

    def test_palavra_que_acaba_num_nome_de_raiz_nao_e_caminho(self) -> None:
        self.assertEqual(self._classes('subdocs/x.md e meustools/y.py'), [])

    def test_directorio_fora_da_lista_nao_e_caminho(self) -> None:
        self.assertEqual(self._classes('Le outracoisa/x.md'), [])

    def test_a_linha_e_a_do_ficheiro(self) -> None:
        alvo = self.raiz / 'specs' / 'EPIC-99_Teste.md'
        alvo.write_text(_doc('a\nb\n### Handoff para Claude Code\n\n§text\n../docs/x.md\n§\n'),
                        encoding='utf-8')
        self.assertEqual([x.linha for x in varrer_ficheiro(alvo, self.raiz)], [6])


class TestArvore(unittest.TestCase):
    def test_varre_por_ordem_de_nome(self) -> None:
        with TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / 'specs').mkdir()
            for n, p in (('EPIC-02_B.md', '../docs/b.md'), ('EPIC-01_A.md', '../docs/a.md')):
                (raiz / 'specs' / n).write_text(
                    _doc(f'### Handoff para Claude Code\n\n§text\n{p}\n§\n'), encoding='utf-8')
            self.assertEqual([x.ficheiro for x in varrer_arvore(raiz)],
                             ['specs/EPIC-01_A.md', 'specs/EPIC-02_B.md'])


if __name__ == '__main__':
    unittest.main()

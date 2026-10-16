"""As evasoes que a revisao adversarial do KAM-145 encontrou.

Cada teste aqui falhava na primeira versao do varredor. Ficam agrupados para
que se leia de uma vez o que o gate deixava passar: quatro directorios de
primeiro nivel que nao conhecia, duas formas de sair da arvore que nao
normalizava, e duas formas de escrever o bloco que o deixavam invisivel.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lint_handoff.scan import RAIZES, contar_blocos, varrer_ficheiro

CERCA = '```'
TILDE = '~~~'


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / 'specs').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _classes(self, corpo: str, marca: str = CERCA, titulo: str = '### Handoff para Claude Code',
                 excepcoes: tuple[str, ...] = ()) -> list[str]:
        f = self.raiz / 'specs' / 'EPIC-99_T.md'
        f.write_text(f'{titulo}\n\n{marca}text\n{corpo}\n{marca}\n', encoding='utf-8')
        return [x.classe for x in varrer_ficheiro(f, self.raiz, excepcoes)]


class TestRaizesQueFaltavam(_Base):
    """M5: um `../` para estes quatro passava o gate sem ser visto."""

    def test_github(self) -> None:
        self.assertEqual(self._classes('Le ../.github/workflows/ci.yaml'), ['acima-da-raiz'])

    def test_infra(self) -> None:
        self.assertEqual(self._classes('Le ../infra/compose.yaml'), ['acima-da-raiz'])

    def test_packages(self) -> None:
        self.assertEqual(self._classes('Le ../packages/contracts/x.ts'), ['acima-da-raiz'])

    def test_claude(self) -> None:
        self.assertEqual(self._classes('Le ../.claude/skills/x/SKILL.md'), ['acima-da-raiz'])

    def test_as_quatro_estao_na_lista(self) -> None:
        for r in ('infra', 'packages', '.github', '.claude'):
            self.assertIn(r, RAIZES)


class TestNormalizacao(_Base):
    """M6: duas formas de sair da arvore que a forma crua nao revelava."""

    def test_ponto_barra_antes_do_duplo_ponto(self) -> None:
        """`./../docs/x` escondia o `..` atras de um `./`."""
        self.assertEqual(self._classes('Le ./../docs/x.md'), ['acima-da-raiz'])

    def test_duplo_ponto_a_meio_que_sai_da_arvore(self) -> None:
        """`docs/../../docs/x` comeca numa raiz valida e sai da arvore."""
        self.assertEqual(self._classes('Le docs/../../docs/x.md'), ['acima-da-raiz'])

    def test_duplo_ponto_a_meio_que_nao_sai_e_conforme(self) -> None:
        """Normalizar nao e proibir `..`: `docs/tecnica/../x` continua dentro."""
        self.assertEqual(self._classes('Le docs/tecnica/../x.md'), ['relativo-a-raiz'])

    def test_barras_a_mais_nao_mudam_a_classe(self) -> None:
        self.assertEqual(self._classes('Le ./docs/x.md'), ['relativo-a-raiz'])


class TestCercaETitulo(_Base):
    """m9: duas formas de escrever o bloco que o deixavam invisivel."""

    def test_cerca_de_tildes(self) -> None:
        self.assertEqual(self._classes('Le ../docs/x.md', marca=TILDE), ['acima-da-raiz'])

    def test_titulo_com_espacos_a_mais(self) -> None:
        self.assertEqual(self._classes('Le ../docs/x.md', titulo='###  Handoff para Claude Code'),
                         ['acima-da-raiz'])

    def test_titulo_com_espaco_a_mais_no_meio(self) -> None:
        self.assertEqual(
            self._classes('Le ../docs/x.md', titulo='### Handoff para  Claude Code'),
            ['acima-da-raiz'])

    def test_cerca_de_tildes_nao_e_fechada_por_backticks(self) -> None:
        """A cerca que fecha tem de ser a que abriu."""
        f = self.raiz / 'specs' / 'EPIC-99_T.md'
        f.write_text(f'### Handoff para Claude Code\n\n{TILDE}text\n{CERCA}\nLe ../docs/x.md\n'
                     f'{TILDE}\n', encoding='utf-8')
        self.assertEqual([x.classe for x in varrer_ficheiro(f, self.raiz)], ['acima-da-raiz'])


class TestExcepcoes(_Base):
    """A linha cujo assunto E uma forma de caminho nao se le."""

    def test_excerto_declarado_silencia_a_linha(self) -> None:
        corpo = 'A forma depende da posicao: de specs/x.md usa ../docs/tecnica/NN_...'
        self.assertEqual(self._classes(corpo), ['relativo-a-raiz', 'acima-da-raiz'])
        self.assertEqual(self._classes(corpo, excepcoes=('A forma depende da posicao',)), [])

    def test_a_excepcao_silencia_a_linha_e_nao_o_bloco(self) -> None:
        f = self.raiz / 'specs' / 'EPIC-99_T.md'
        f.write_text(f'### Handoff para Claude Code\n\n{CERCA}text\ncita ../docs/a.md\n'
                     f'Le ../docs/b.md\n{CERCA}\n', encoding='utf-8')
        a = varrer_ficheiro(f, self.raiz, ('cita',))
        self.assertEqual([x.texto for x in a], ['../docs/b.md'])


class TestContarBlocos(_Base):
    """m9: «conforme» tem de distinguir a arvore inteira de zero blocos lidos."""

    def test_um_bloco_por_ticket(self) -> None:
        f = self.raiz / 'specs' / 'EPIC-99_T.md'
        f.write_text(f'## KAM-001 — a\n\n### Handoff para Claude Code\n\n{CERCA}text\nx\n'
                     f'{CERCA}\n\n## KAM-002 — b\n\n### Handoff para Claude Code\n\n'
                     f'{CERCA}text\ny\n{CERCA}\n', encoding='utf-8')
        self.assertEqual(contar_blocos(self.raiz, 'specs/EPIC-*.md'), (2, 2))

    def test_titulo_mal_escrito_desequilibra_a_contagem(self) -> None:
        f = self.raiz / 'specs' / 'EPIC-99_T.md'
        f.write_text(f'## KAM-001 — a\n\n### Handoff para o Claude Code\n\n{CERCA}text\nx\n'
                     f'{CERCA}\n', encoding='utf-8')
        self.assertEqual(contar_blocos(self.raiz, 'specs/EPIC-*.md'), (0, 1))


if __name__ == '__main__':
    unittest.main()

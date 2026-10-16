"""Testes da varredura das contagens.

Cada caso fixa uma fronteira: o que e contagem, o que e historia, e qual e a
fonte de cada numero.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lint_contagens.fontes import Fontes, epic_do_ficheiro
from lint_contagens.scan import PADROES, aceitaveis, ficheiros, varrer_ficheiro

CERCA = '```'

FONTES = Fontes(tickets=158, blocos=158, adrs=20, adrs_locais=2, anexos=5, epics=11,
                por_epic={'EPIC-01': 43, 'EPIC-04': 11})


def _doc(corpo: str) -> str:
    return corpo.replace('§', CERCA)


class TestOQueConta(unittest.TestCase):
    """As tres grandezas, e o que nao e nenhuma delas."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / 'specs').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _varrer(self, texto: str, nome: str = 'specs/INDICE.md', excepcoes=()):
        alvo = self.raiz / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(_doc(texto), encoding='utf-8')
        return varrer_ficheiro(alvo, self.raiz, FONTES, excepcoes)

    def test_a_contagem_certa_bate(self) -> None:
        (x,) = self._varrer('O backlog tem 158 tickets.')
        self.assertTrue(x.bate)
        self.assertEqual((x.grandeza, x.escrito, x.aceitaveis), ('tickets', 158, (158,)))

    def test_a_contagem_errada_nao_bate(self) -> None:
        (x,) = self._varrer('O backlog tem 143 tickets.')
        self.assertFalse(x.bate)
        self.assertIn('está escrito 143', str(x))
        self.assertIn('158', str(x))

    def test_as_tres_grandezas_sao_reconhecidas(self) -> None:
        achados = self._varrer('158 tickets, 20 ADRs e 11 epics.')
        self.assertEqual({x.grandeza for x in achados}, set(PADROES))
        self.assertTrue(all(x.bate for x in achados))

    def test_um_numero_de_outra_coisa_nao_e_contagem(self) -> None:
        """A classe esta fechada: nao se adivinha «quantos» de qualquer numero."""
        self.assertEqual(self._varrer('Sao 143 linhas, 12 ficheiros e 8 falhas.'), [])

    def test_um_numero_pegado_a_palavra_nao_conta(self) -> None:
        self.assertEqual(self._varrer('Ver KAM-158 tickets? nao: e um id.'), [])


class TestZonasDeHistoria(unittest.TestCase):
    """O que registra o que era verdade **entao** nao se le."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / 'specs').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _varrer(self, texto: str):
        alvo = self.raiz / 'specs/INDICE.md'
        alvo.write_text(_doc(texto), encoding='utf-8')
        return varrer_ficheiro(alvo, self.raiz, FONTES)

    def test_a_linha_de_controlo_de_versoes_nao_se_le(self) -> None:
        self.assertEqual(self._varrer('| 1.14 | Outubro 2026 | Total: 143 tickets. | Equipa |'), [])

    def test_a_seccao_de_verificacao_nao_se_le(self) -> None:
        self.assertEqual(
            self._varrer('### Verificação dos Critérios de Aceitação\n\nMediu 143 tickets.'), [])

    def test_a_seccao_de_verificacao_acaba_no_cabecalho_seguinte(self) -> None:
        """Senao, o primeiro ticket com verificacao calava o resto do ficheiro."""
        achados = self._varrer(
            '### Verificação dos Critérios de Aceitação\n\nMediu 143 tickets.\n'
            '\n## Outra secção\n\nO backlog tem 143 tickets.')
        self.assertEqual([x.linha for x in achados], [7])

    def test_dentro_de_uma_cerca_nao_se_le(self) -> None:
        self.assertEqual(self._varrer('§text\nsaida: 143 tickets\n§\n'), [])

    def test_depois_da_cerca_volta_a_ler_se(self) -> None:
        achados = self._varrer('§text\n143 tickets\n§\nO backlog tem 143 tickets.')
        self.assertEqual([x.linha for x in achados], [4])

    def test_uma_excepcao_salta_a_linha(self) -> None:
        alvo = self.raiz / 'specs/INDICE.md'
        alvo.write_text('O INDICE ainda diz 143 tickets, e esta errado.', encoding='utf-8')
        self.assertEqual(varrer_ficheiro(alvo, self.raiz, FONTES, ('ainda diz',)), [])


class TestAFonteDependeDeOnde(unittest.TestCase):
    """«Sao 11 tickets» num epic fala desse epic; no INDICE fala do total."""

    def test_num_ficheiro_de_epic_valem_as_duas_leituras(self) -> None:
        self.assertEqual(aceitaveis('tickets', 'specs/EPIC-04_Core_Comercio.md', '', FONTES),
                         (158, 11))

    def test_num_ficheiro_de_ticket_vale_o_epic_01(self) -> None:
        self.assertEqual(aceitaveis('tickets', 'specs/tickets/KAM-005.md', '', FONTES),
                         (158, 43))

    def test_fora_de_um_epic_vale_so_o_total(self) -> None:
        self.assertEqual(aceitaveis('tickets', 'docs/ci.md', '', FONTES), (158,))

    def test_o_epic_de_cada_ficheiro(self) -> None:
        self.assertEqual(epic_do_ficheiro('specs/EPIC-07_Seguranca_Conformidade.md'), 'EPIC-07')
        self.assertEqual(epic_do_ficheiro('specs/tickets/KAM-155.md'), 'EPIC-01')
        self.assertIsNone(epic_do_ficheiro('docs/ci.md'))

    def test_os_adrs_locais_sao_outra_populacao(self) -> None:
        self.assertEqual(aceitaveis('ADRs', 'docs/ci.md', 'os 2 ADRs locais', FONTES), (2,))
        self.assertEqual(aceitaveis('ADRs', 'docs/ci.md', 'os 20 ADRs canonicos', FONTES), (20,))


class TestCorpus(unittest.TestCase):
    """O que se varre, e o que nao se varre."""

    def test_as_pastas_de_registo_ficam_de_fora(self) -> None:
        with TemporaryDirectory() as d:
            raiz = Path(d)
            for rel in ('specs/INDICE.md', 'docs/ci.md',
                        'docs/analises/ANALISE-01-x.md', 'docs/evidencia/KAM-001.md'):
                (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
                (raiz / rel).write_text('143 tickets', encoding='utf-8')
            nomes = [f.relative_to(raiz).as_posix() for f in ficheiros(raiz)]
            self.assertEqual(nomes, ['docs/ci.md', 'specs/INDICE.md'])

    def test_sem_repetidos_quando_os_padroes_se_sobrepoem(self) -> None:
        with TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / 'docs/tecnica').mkdir(parents=True)
            (raiz / 'docs/tecnica/00.md').write_text('x', encoding='utf-8')
            self.assertEqual(
                len(ficheiros(raiz, ('docs/**/*.md', 'docs/tecnica/*.md', 'docs/tecnica/00.md'))),
                1)


if __name__ == '__main__':
    unittest.main()

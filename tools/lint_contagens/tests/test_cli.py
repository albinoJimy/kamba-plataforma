"""Testes da linha de comando: declaracoes, prazos e as guardas.

O que estes casos protegem e o que distingue um *gate* de um relatorio: uma
declaracao sem razao nao passa, uma excepcao esquecida nao passa, uma divida sem
prazo nao passa, e uma varredura que deixou de ver a populacao **nao** diz
«conforme».
"""

from __future__ import annotations

import io
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from lint_contagens import cli


def _arvore(raiz: Path, ficheiros: dict[str, str]) -> None:
    for rel, texto in ficheiros.items():
        alvo = raiz / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(textwrap.dedent(texto), encoding='utf-8')


#: O minimo que `fontes.ler` precisa de encontrar para a arvore ser legivel.
MINIMA = {
    'specs/INDICE.md': '| KAM-001 | t | chore | M | P0 | 0 | — |\n',
    'docs/tecnica/00_Arquitectura_Solucao.md': 'ADR-001 e ADR-002.\n',
    'specs/EPIC-01_Fundacoes_Dados.md': '# EPIC-01\n',
}


class TestDeclaracoes(unittest.TestCase):
    """`ci/contagens-allow.yaml`: o que se aceita e o que se recusa."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        _arvore(self.raiz, MINIMA)
        (self.raiz / 'ci').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _escrever(self, texto: str) -> None:
        (self.raiz / cli.ALLOW).write_text(textwrap.dedent(texto), encoding='utf-8')

    def test_sem_ficheiro_nao_ha_declaracoes(self) -> None:
        self.assertEqual(cli.ler_declaracoes(self.raiz), ((), ()))

    def test_uma_excepcao_sem_razao_e_recusada(self) -> None:
        self._escrever('excepcoes:\n  - excerto: "x"\n')
        with self.assertRaises(cli.ConfiguracaoInvalida) as e:
            cli.ler_declaracoes(self.raiz)
        self.assertIn('razao', str(e.exception))

    def test_uma_excepcao_sem_excerto_e_recusada(self) -> None:
        self._escrever('excepcoes:\n  - razao: "porque"\n')
        with self.assertRaises(cli.ConfiguracaoInvalida):
            cli.ler_declaracoes(self.raiz)

    def test_uma_divida_sem_prazo_e_recusada(self) -> None:
        """Uma divida sem `expira_em` e uma amnistia."""
        self._escrever("""
            dividas:
              - ficheiro: docs/x.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                razao: "porque"
            """)
        with self.assertRaises(cli.ConfiguracaoInvalida) as e:
            cli.ler_declaracoes(self.raiz)
        self.assertIn('expira_em', str(e.exception))

    def test_uma_divida_de_grandeza_desconhecida_e_recusada(self) -> None:
        self._escrever("""
            dividas:
              - ficheiro: docs/x.md
                grandeza: bananas
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                expira_em: 2026-11-16
                razao: "porque"
            """)
        with self.assertRaises(cli.ConfiguracaoInvalida) as e:
            cli.ler_declaracoes(self.raiz)
        self.assertIn('bananas', str(e.exception))

    def test_uma_divida_completa_le_se(self) -> None:
        self._escrever("""
            excepcoes:
              - excerto: "ainda diz"
                razao: "cita o defeito"
            dividas:
              - ficheiro: docs/x.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 2
                origem: KAM-130
                criado_em: 2026-10-16
                expira_em: 2026-11-16
                razao: "e do KAM-130"
            """)
        excepcoes, dividas = cli.ler_declaracoes(self.raiz)
        self.assertEqual(excepcoes, ('ainda diz',))
        self.assertEqual(len(dividas), 1)
        self.assertEqual((dividas[0].escrito, dividas[0].ocorrencias, dividas[0].origem),
                         (143, 2, 'KAM-130'))
        self.assertEqual(dividas[0].expira_em.isoformat(), '2026-11-16')


class TestCheck(unittest.TestCase):
    """O `check` sobre arvores de prova, com os codigos de saida."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._minimo = cli.MINIMO_ESPERADO
        cli.MINIMO_ESPERADO = 1
        self.addCleanup(setattr, cli, 'MINIMO_ESPERADO', self._minimo)

    def _correr(self, *argumentos: str) -> tuple[int, str, str]:
        saida, erro = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erro):
            codigo = cli.main(['--root', str(self.raiz), *argumentos])
        return codigo, saida.getvalue(), erro.getvalue()

    def _arvore(self, prosa: str, allow: str | None = None) -> None:
        ficheiros = dict(MINIMA)
        ficheiros['specs/INDICE.md'] = (
            '| KAM-001 | t | chore | M | P0 | 0 | — |\n' + prosa)
        _arvore(self.raiz, ficheiros)
        if allow is not None:
            (self.raiz / 'ci').mkdir(exist_ok=True)
            (self.raiz / cli.ALLOW).write_text(textwrap.dedent(allow), encoding='utf-8')

    def test_a_contagem_certa_fica_conforme(self) -> None:
        self._arvore('O backlog tem 1 ticket, 2 ADRs e 1 epic.\n')
        codigo, saida, _ = self._correr('check')
        self.assertEqual(codigo, 0, saida)
        self.assertIn('conforme', saida)

    def test_a_contagem_errada_falha_com_o_sitio_e_os_dois_numeros(self) -> None:
        self._arvore('O backlog tem 143 tickets, 2 ADRs e 1 epic.\n')
        codigo, saida, _ = self._correr('check')
        self.assertEqual(codigo, 1)
        self.assertIn('specs/INDICE.md:2', saida)
        self.assertIn('143', saida)
        self.assertIn('a fonte dá 1', saida)

    def test_uma_grandeza_sem_ocorrencia_nenhuma_falha(self) -> None:
        """Um padrao que deixa de casar nada nao protege nada."""
        self._arvore('O backlog tem 1 ticket.\n')
        codigo, _, erro = self._correr('check')
        self.assertEqual(codigo, 2)
        self.assertIn('sem uma unica ocorrencia', erro)
        self.assertIn('ADRs', erro)

    def test_a_guarda_do_minimo_recusa_passar_sobre_o_vazio(self) -> None:
        cli.MINIMO_ESPERADO = 99
        self._arvore('O backlog tem 1 ticket, 2 ADRs e 1 epic.\n')
        codigo, _, erro = self._correr('check')
        self.assertEqual(codigo, 2)
        self.assertIn('esperam-se pelo menos 99', erro)

    def test_uma_excepcao_que_nao_casa_nada_falha(self) -> None:
        self._arvore('O backlog tem 1 ticket, 2 ADRs e 1 epic.\n',
                     'excepcoes:\n  - excerto: "nunca escrito"\n    razao: "porque"\n')
        codigo, _, erro = self._correr('check')
        self.assertEqual(codigo, 2)
        self.assertIn('nao casam nenhuma linha', erro)

    def test_uma_divida_cobre_a_contagem_errada(self) -> None:
        self._arvore(
            'O backlog tem 143 tickets, 2 ADRs e 1 epic.\n',
            """
            dividas:
              - ficheiro: specs/INDICE.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                expira_em: 2026-11-16
                razao: "e do KAM-130"
            """)
        codigo, saida, _ = self._correr('--hoje', '2026-10-16', 'check')
        self.assertEqual(codigo, 0, saida)
        self.assertIn('1 divida(s) declarada(s)', saida)
        self.assertIn('vence a 2026-11-16', saida)

    def test_uma_divida_vencida_falha(self) -> None:
        self._arvore(
            'O backlog tem 143 tickets, 2 ADRs e 1 epic.\n',
            """
            dividas:
              - ficheiro: specs/INDICE.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                expira_em: 2026-11-16
                razao: "e do KAM-130"
            """)
        codigo, _, erro = self._correr('--hoje', '2026-11-17', 'check')
        self.assertEqual(codigo, 1)
        self.assertIn('venceu a 2026-11-16', erro)

    def test_uma_divida_ja_paga_falha(self) -> None:
        """Uma declaracao que nao cobre nada mente sobre o estado do conjunto."""
        self._arvore(
            'O backlog tem 1 ticket, 2 ADRs e 1 epic.\n',
            """
            dividas:
              - ficheiro: specs/INDICE.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                expira_em: 2026-11-16
                razao: "e do KAM-130"
            """)
        codigo, _, erro = self._correr('--hoje', '2026-10-16', 'check')
        self.assertEqual(codigo, 2)
        self.assertIn('foram pagas', erro)

    def test_uma_divida_com_ocorrencias_errado_falha(self) -> None:
        self._arvore(
            'O backlog tem 143 tickets, 2 ADRs e 1 epic.\n'
            'E noutra linha, 143 tickets.\n',
            """
            dividas:
              - ficheiro: specs/INDICE.md
                grandeza: tickets
                escrito: 143
                ocorrencias: 1
                origem: KAM-130
                expira_em: 2026-11-16
                razao: "e do KAM-130"
            """)
        codigo, _, erro = self._correr('--hoje', '2026-10-16', 'check')
        self.assertEqual(codigo, 2)
        self.assertIn('declara 1 e cobre 2', erro)

    def test_raiz_inexistente_da_dois(self) -> None:
        saida, erro = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erro):
            codigo = cli.main(['--root', str(self.raiz / 'nao-existe'), 'check'])
        self.assertEqual(codigo, 2)
        self.assertIn('raiz inexistente', erro.getvalue())


class TestRepositorio(unittest.TestCase):
    """O repositorio real passa o seu proprio gate."""

    def test_o_repositorio_fica_conforme(self) -> None:
        raiz = Path(__file__).resolve().parents[3]
        saida, erro = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erro):
            codigo = cli.main(['--root', str(raiz), 'check'])
        self.assertEqual(codigo, 0, saida.getvalue() + erro.getvalue())


if __name__ == '__main__':
    unittest.main()

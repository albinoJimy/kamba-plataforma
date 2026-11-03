"""Testes da leitura da matriz (`env_lint/matriz.py`).

O que se testa aqui e a **recusa**, mais do que a aceitacao: uma leitura de
Markdown que falhe em silencio devolve uma matriz parcial, e uma matriz parcial
passa as comparacoes que nao chegou a fazer. Cada forma mal escrita tem de dar
`MatrizIlegivel`.
"""

from __future__ import annotations

import unittest

from env_lint import matriz

CABECALHO = "| Aspecto | Chave | `dev` | `staging` | `prod` |\n|---|---|---|---|---|\n"


def _tabela(*linhas: str) -> str:
    return "prosa antes\n\n" + CABECALHO + "".join(linhas) + "\nprosa depois\n"


class TestLer(unittest.TestCase):
    def test_le_a_chave_e_os_tres_tokens(self) -> None:
        texto = _tabela("| Dados | `dados.classe` | `synthetic` | `synthetic` | `real` |\n")
        [linha] = matriz.ler(texto)
        self.assertEqual(linha.aspecto, "Dados")
        self.assertEqual(linha.chave, "dados.classe")
        self.assertEqual(
            linha.valores, {"dev": "synthetic", "staging": "synthetic", "prod": "real"}
        )

    def test_ignora_a_prosa_depois_do_token(self) -> None:
        texto = _tabela(
            "| Dados | `dados.classe` | `synthetic` | `synthetic` — nunca copia de prod "
            "| `synthetic` (`real` so apos D1) |\n"
        )
        [linha] = matriz.ler(texto)
        # O segundo token da celula de `prod` e `real`, e e deliberadamente
        # ignorado: compara-se o PRIMEIRO. Sem isto, a prosa que explica uma
        # celula mudava o valor verificado.
        self.assertEqual(linha.valores["prod"], "synthetic")

    def test_le_varias_linhas(self) -> None:
        texto = _tabela(
            "| Dados | `dados.classe` | `synthetic` | `synthetic` | `synthetic` |\n",
            "| Acesso | `acesso.modo` | `equipa` | `equipa` | `break-glass` |\n",
        )
        self.assertEqual([linha.chave for linha in matriz.ler(texto)], ["dados.classe", "acesso.modo"])

    def test_para_na_primeira_linha_que_nao_e_tabela(self) -> None:
        texto = (
            CABECALHO
            + "| Dados | `dados.classe` | `a` | `b` | `c` |\n"
            + "\n"
            + "| Outra | `x.y` | `a` | `b` | `c` |\n"
        )
        self.assertEqual(len(matriz.ler(texto)), 1)


class TestRecusas(unittest.TestCase):
    def test_sem_tabela(self) -> None:
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler("so prosa, nenhuma tabela\n")
        self.assertIn("nao ha tabela", str(capturado.exception))

    def test_celula_sem_token(self) -> None:
        texto = _tabela("| Dados | `dados.classe` | synthetic | `b` | `c` |\n")
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler(texto)
        self.assertIn("celula sem token", str(capturado.exception))

    def test_chave_sem_token(self) -> None:
        texto = _tabela("| Dados | dados.classe | `a` | `b` | `c` |\n")
        with self.assertRaises(matriz.MatrizIlegivel):
            matriz.ler(texto)

    def test_numero_de_celulas_errado(self) -> None:
        texto = _tabela("| Dados | `dados.classe` | `a` | `b` |\n")
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler(texto)
        self.assertIn("celulas", str(capturado.exception))

    def test_sem_linha_de_separacao(self) -> None:
        texto = (
            "| Aspecto | Chave | `dev` | `staging` | `prod` |\n"
            "| Dados | `dados.classe` | `a` | `b` | `c` |\n"
        )
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler(texto)
        self.assertIn("separacao", str(capturado.exception))

    def test_tabela_sem_linhas_de_dados(self) -> None:
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler(CABECALHO + "\n")
        self.assertIn("nenhuma linha", str(capturado.exception))

    def test_duas_tabelas_com_o_mesmo_cabecalho(self) -> None:
        # Nao se escolhe uma em silencio: era a forma de a matriz ter duas
        # versoes e o gate ler a que calhasse primeiro.
        texto = _tabela("| Dados | `dados.classe` | `a` | `b` | `c` |\n") + _tabela(
            "| Dados | `dados.classe` | `x` | `y` | `z` |\n"
        )
        with self.assertRaises(matriz.MatrizIlegivel) as capturado:
            matriz.ler(texto)
        self.assertIn("duas tabelas", str(capturado.exception))


class TestTabelaAcrescentada(unittest.TestCase):
    def test_le_a_tabela_de_seis_colunas(self) -> None:
        texto = (
            "| Aspecto | Chave | `dev` | `staging` | `prod` | Estado |\n"
            "|---|---|---|---|---|---|\n"
            "| TTL | `dns.ttl_segundos` | `300` | `300` | `300` | *proposta* |\n"
        )
        [linha] = matriz.tabela_acrescentada(texto)
        self.assertEqual(linha.chave, "dns.ttl_segundos")
        self.assertEqual(linha.valores["prod"], "300")

    def test_nao_confunde_as_duas_tabelas(self) -> None:
        # A de cinco colunas nao e lida como a de seis, nem o contrario.
        cinco = _tabela("| Dados | `dados.classe` | `a` | `b` | `c` |\n")
        with self.assertRaises(matriz.MatrizIlegivel):
            matriz.tabela_acrescentada(cinco)


if __name__ == "__main__":
    unittest.main()

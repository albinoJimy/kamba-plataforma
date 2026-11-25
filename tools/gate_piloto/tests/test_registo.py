"""A leitura do Registo: o real lê-se, e o que impede de ler sai como erro."""

from __future__ import annotations

import unittest
from pathlib import Path

from gate_piloto import registo
from gate_piloto.tests import sintetico

RAIZ = Path(__file__).resolve().parents[3]
REAL = RAIZ / "docs/tecnica/evidencia/validacao/Registo_Hipoteses.md"


class TestOReal(unittest.TestCase):
    def test_o_registo_versionado_le_se_com_as_nove_linhas(self) -> None:
        linhas = registo.ler(REAL)
        self.assertEqual(tuple(linhas), registo.HIPOTESES)
        # O limiar lido é o do Registo, e não um texto que o gerador traga.
        self.assertIn("≥ 5 pagam", linhas["H1"].limiar)


class TestRecusas(unittest.TestCase):
    def test_colunas_trocadas(self) -> None:
        texto = sintetico.registo().replace("| amostra n | resultado |", "| resultado | amostra n |")
        with self.assertRaisesRegex(registo.RegistoIlegivel, "colunas"):
            registo.ler_texto(texto)

    def test_linha_em_falta(self) -> None:
        texto = "\n".join(l for l in sintetico.registo().splitlines() if not l.startswith("| H7 |"))
        with self.assertRaisesRegex(registo.RegistoIlegivel, "H7"):
            registo.ler_texto(texto)

    def test_linha_repetida(self) -> None:
        linhas = sintetico.registo().splitlines()
        h1 = next(l for l in linhas if l.startswith("| H1 |"))
        linhas.insert(linhas.index(h1) + 1, h1)
        with self.assertRaisesRegex(registo.RegistoIlegivel, "duas vezes"):
            registo.ler_texto("\n".join(linhas))

    def test_estado_fora_dos_tres(self) -> None:
        texto = sintetico.registo({"H2": ("30", "16", "CONFIRMADO-ish", "x.md")})
        with self.assertRaisesRegex(registo.RegistoIlegivel, "H2"):
            registo.ler_texto(texto)

    def test_estado_da_escala_de_verificacao_nao_serve(self) -> None:
        # «NÃO VERIFICADO» é da escala do conjunto, não um estado de hipótese.
        texto = sintetico.registo({"H2": ("30", "16", "NÃO VERIFICADO", "x.md")})
        with self.assertRaises(registo.RegistoIlegivel):
            registo.ler_texto(texto)

    def test_sem_tabela(self) -> None:
        with self.assertRaisesRegex(registo.RegistoIlegivel, "tabela"):
            registo.ler_texto("# nada\n")

    def test_celulas_a_menos(self) -> None:
        texto = sintetico.registo().replace("| H3 | enunciado sintético |", "| H3 |", 1)
        with self.assertRaisesRegex(registo.RegistoIlegivel, "células"):
            registo.ler_texto(texto)

    def test_ficheiro_inexistente(self) -> None:
        with self.assertRaises(registo.RegistoIlegivel):
            registo.ler(RAIZ / "nao-existe.md")


if __name__ == "__main__":
    unittest.main()

"""O custo de uma chamada, e o numero que o criterio 5 fixa (KAM-030).

O criterio 5 diz: «`custo_usd` do exemplo de `../docs/tecnica/02` §13.3 (3.000
in / 300 out a 0,10 / 0,50 USD por 1M) = 0,00045 em teste unitario». E o
`TestOExemploDo1333` abaixo.

**O canario que importa, e que esta classe tem:** um teste de custo que so
confirmasse «dá um numero» passava com a formula apagada. Por isso ha
`test_a_formula_nao_e_uma_constante`, que mede dois pontos diferentes e confere
que escalam — e `test_o_cache_nao_e_cobrado_a_tarifa_de_entrada`, que separa as
duas tarifas: a primeira versao da formula somava os tres a tarifa de entrada e
dava um numero plausivel.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import unittest
from decimal import Decimal

from kamba_agr.llm import precos


def _preco(entrada: str, cache: str, saida: str, valido_ate: dt.date | None = None):
    return precos.Preco(
        fornecedor="anthropic",
        modelo="ensaio",
        entrada=Decimal(entrada),
        cache=Decimal(cache),
        saida=Decimal(saida),
        estado="CONFIRMADO",
        fonte="ensaio",
        valido_ate=valido_ate,
    )


class TestOExemploDo1333(unittest.TestCase):
    """O numero do criterio 5, com a tarifa escrita a mao e com a do ficheiro."""

    ESPERADO = Decimal("0.00045")

    def test_a_mao(self) -> None:
        self.assertEqual(precos.custo(_preco("0.10", "0.01", "0.50"), 3000, 300), self.ESPERADO)

    def test_da_tabela_real(self) -> None:
        """O mesmo numero com o `llm/precos.yaml` do repositorio.

        Nao e redundante com o de cima: este liga o numero do critero a **linha
        do Haiku 5.5 do ficheiro**, que e o modelo do exemplo do §13.3. Se
        alguem mexer na tarifa daquela linha, este falha e o de cima nao.
        """
        tabela = precos.carregar(_pasta())
        haiku = tabela[("anthropic", "claude-haiku-5-5")]
        self.assertEqual(haiku.entrada, Decimal("0.10"))
        self.assertEqual(haiku.saida, Decimal("0.50"))
        self.assertEqual(precos.custo(haiku, 3000, 300), self.ESPERADO)

    def test_e_decimal_e_nao_float(self) -> None:
        """A convencao proibe virgula flutuante em dinheiro.

        `3000 * 0.10 / 1e6 + 300 * 0.50 / 1e6` em `float` da
        `0.00045000000000000004`, e um milhao destas linhas somadas desvia o
        custo por tenant do que o fornecedor cobrou.
        """
        valor = precos.custo(_preco("0.10", "0.01", "0.50"), 3000, 300)
        self.assertIsInstance(valor, Decimal)
        # **A comparacao tem de ser na representacao exacta, nao em `float`.**
        # A primeira versao deste teste fazia `assertNotEqual(float(soma),
        # float(valor))` e **passava a dizer que eram diferentes quando sao
        # iguais**: converter o `Decimal` de volta a `float` arredonda para o
        # mesmo `float`, pelo que a asserção nao media nada. O que se mede e o
        # valor exacto que cada via produz.
        em_float = Decimal(3000 * 0.10 / 1e6 + 300 * 0.50 / 1e6)
        self.assertEqual(valor, Decimal("0.00045"))
        self.assertNotEqual(
            em_float,
            Decimal("0.00045"),
            "o `float` nao representa 0,00045 exactamente, e e essa a razao do Decimal",
        )
        # Nao se fixa o valor exacto do `float` aqui: ele depende da ordem das
        # operacoes, e uma versao deste teste fixou-o **adivinhado** e falhou. O
        # que importa e que nao e o valor exacto, acima.


class TestAFormulaNaoEDecoracao(unittest.TestCase):
    """Os canarios: com a formula apagada, estes falham."""

    def test_a_formula_nao_e_uma_constante(self) -> None:
        p = _preco("0.10", "0.01", "0.50")
        um = precos.custo(p, 3000, 300)
        dez = precos.custo(p, 30000, 3000)
        self.assertEqual(dez, um * 10)
        self.assertNotEqual(um, dez)

    def test_o_cache_nao_e_cobrado_a_tarifa_de_entrada(self) -> None:
        """Os tres termos tem tarifas diferentes, e isso mede-se.

        Com os tres somados a tarifa de entrada, 1000 de cache custariam o mesmo
        que 1000 de entrada — e custam um decimo.
        """
        p = _preco("0.10", "0.01", "0.50")
        so_entrada = precos.custo(p, 1000, 0, 0)
        so_cache = precos.custo(p, 0, 0, 1000)
        so_saida = precos.custo(p, 0, 1000, 0)
        self.assertEqual(so_entrada, Decimal("0.000100"))
        self.assertEqual(so_cache, Decimal("0.000010"))
        self.assertEqual(so_saida, Decimal("0.000500"))
        self.assertEqual(so_cache * 10, so_entrada)

    def test_sem_preco_da_nulo_e_nao_zero(self) -> None:
        """Zero afirmava que a chamada foi gratuita; o nulo diz «nao se sabe»."""
        self.assertIsNone(precos.custo(None, 3000, 300))

    def test_tokens_negativos_levantam(self) -> None:
        with self.assertRaises(precos.PrecoInvalido):
            precos.custo(_preco("0.10", "0.01", "0.50"), -1, 300)


class TestAValidadeDoPreco(unittest.TestCase):
    """O `gemini-3.8-flash` duplica a 2027-01-01, e calcular com o antigo mente."""

    def test_dentro_da_validade_calcula(self) -> None:
        p = _preco("0.75", "0.075", "3.75", valido_ate=dt.date(2026, 12, 31))
        self.assertEqual(
            precos.custo(p, 1000, 100, hoje=dt.date(2026, 12, 31)), Decimal("0.001125")
        )

    def test_depois_da_validade_levanta(self) -> None:
        p = _preco("0.75", "0.075", "3.75", valido_ate=dt.date(2026, 12, 31))
        with self.assertRaises(precos.PrecoExpirado):
            precos.custo(p, 1000, 100, hoje=dt.date(2027, 1, 1))

    def test_a_linha_promocional_do_ficheiro_tem_validade(self) -> None:
        """Sem `valido_ate` naquela linha, o teste acima protegia nada."""
        tabela = precos.carregar(_pasta())
        flash = tabela[("google", "gemini-3.8-flash")]
        self.assertEqual(flash.valido_ate, dt.date(2026, 12, 31))


class TestOFicheiroDePrecos(unittest.TestCase):
    def test_todas_as_linhas_tem_estado_de_verificacao(self) -> None:
        """Um preco sem estado e um INDICIO a passar por facto."""
        for chave, preco in precos.carregar(_pasta()).items():
            with self.subTest(chave=chave):
                self.assertIn(preco.estado, ("CONFIRMADO", "INDICIO", "NAO VERIFICADO"))
                self.assertTrue(preco.fonte.strip(), "toda a linha nomeia a fonte")

    def test_as_linhas_do_google_sao_indicio(self) -> None:
        """O `E4` §3.3 e resumo de WebFetch: nao se promove a CONFIRMADO."""
        tabela = precos.carregar(_pasta())
        google = [p for (f, _), p in tabela.items() if f == "google"]
        self.assertTrue(google)
        for preco in google:
            self.assertEqual(preco.estado, "INDICIO")


def _pasta() -> pathlib.Path:
    """A pasta `llm/` do repositorio, a partir deste ficheiro."""
    return pathlib.Path(__file__).resolve().parents[3] / "llm"


if __name__ == "__main__":
    unittest.main()

"""As tres metricas do IDX (KAM-193): dominios fechados, formato, e nada de texto.

O que e servido pela rota do AGR, e a ligacao do executor ao registo, prende-se
em `services/agr/tests/test_idx.py`. Aqui fica o contrato do registo.
"""

from __future__ import annotations

import unittest

from kamba_core.idx import metricas as m

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"


class TestRegisto(unittest.TestCase):
    def setUp(self) -> None:
        self.registo = m.MetricasDoIdx()

    def test_um_registo_novo_serve_corpo_vazio(self) -> None:
        """A regra do AGR, que serve os dois registos na mesma rota."""
        self.assertEqual(self.registo.exposicao(), "")
        self.assertEqual(self.registo.ler(), {})

    def test_uma_pesquisa_escreve_as_tres_series(self) -> None:
        self.registo.registar_pesquisa(modo="lexical", duracao_ms=12.5, resultados=3)
        self.registo.registar_pesquisa(modo="lexical", duracao_ms=7, resultados=0)
        self.registo.registar_pesquisa(modo="hibrido", duracao_ms=20, resultados=2)
        self.assertEqual(
            self.registo.ler(),
            {
                "idx_query_ms:todos:lexical": 7.0,
                "idx_query_ms:todos:hibrido": 20.0,
                "idx_mode:lexical": 2,
                "idx_mode:hibrido": 1,
                "idx_results_total": 5,
            },
        )

    def test_o_formato_de_exposicao(self) -> None:
        self.registo.registar_pesquisa(modo="lexical", duracao_ms=12.5, resultados=3)
        texto = self.registo.exposicao()
        self.assertEqual(
            texto,
            "# HELP idx_query_ms Duracao da ultima pesquisa no indice, em "
            "milissegundos, por ramo e modo.\n"
            "# TYPE idx_query_ms gauge\n"
            'idx_query_ms{ramo="todos",modo="lexical"} 12.5\n'
            "# HELP idx_results_total Candidatos devolvidos pela pesquisa no indice.\n"
            "# TYPE idx_results_total counter\n"
            "idx_results_total 3\n"
            "# HELP idx_mode Pesquisas no indice, por modo (hibrido ou lexical).\n"
            "# TYPE idx_mode counter\n"
            'idx_mode{modo="lexical"} 1\n',
        )

    def test_zero_resultados_tambem_e_serie(self) -> None:
        """Uma pesquisa vazia conta: `idx_results_total 0` e nao ausencia."""
        self.registo.registar_pesquisa(modo="lexical", duracao_ms=1, resultados=0)
        self.assertIn("idx_results_total 0\n", self.registo.exposicao())

    def test_os_dominios_sao_fechados(self) -> None:
        for modo in ("semantico", "LEXICAL", TENANT, "nike air", ""):
            with self.subTest(modo=modo), self.assertRaises(m.EtiquetaInvalida):
                self.registo.registar_pesquisa(modo=modo, duracao_ms=1, resultados=0)
        for ramo in ("sem", "tri", "fts", TENANT):
            with self.subTest(ramo=ramo), self.assertRaises(m.EtiquetaInvalida):
                self.registo.registar_pesquisa(
                    modo="lexical", duracao_ms=1, resultados=0, ramo=ramo
                )
        self.assertEqual(self.registo.ler(), {}, "uma recusa nao escreve nada")

    def test_numeros_invalidos_recusam(self) -> None:
        for resultados in (-1, True, 1.5, "3"):
            with self.subTest(resultados=resultados), self.assertRaises(ValueError):
                self.registo.registar_pesquisa(
                    modo="lexical", duracao_ms=1, resultados=resultados
                )
        for duracao in (-0.1, float("nan")):
            with self.subTest(duracao=duracao), self.assertRaises(ValueError):
                self.registo.registar_pesquisa(
                    modo="lexical", duracao_ms=duracao, resultados=0
                )

    def test_o_registo_nao_tem_por_onde_receber_texto(self) -> None:
        """A assinatura e a garantia: so modo, ramo, duracao e resultados."""
        import inspect

        parametros = set(inspect.signature(m.MetricasDoIdx.registar_pesquisa).parameters)
        self.assertEqual(parametros, {"self", "modo", "duracao_ms", "resultados", "ramo"})

    def test_repor(self) -> None:
        self.registo.registar_pesquisa(modo="lexical", duracao_ms=1, resultados=1)
        self.registo.repor()
        self.assertEqual(self.registo.exposicao(), "")


class TestContrato(unittest.TestCase):
    def test_os_nomes_sao_os_do_bloco(self) -> None:
        """Os tres nomes do KAM-061 (Detalhes Tecnicos) e do criterio do KAM-193."""
        self.assertEqual(
            (m.METRICA_LATENCIA, m.METRICA_RESULTADOS, m.METRICA_MODO),
            ("idx_query_ms", "idx_results_total", "idx_mode"),
        )
        self.assertEqual(m.MODOS, ("hibrido", "lexical"))

    def test_o_catalogo_declara_os_mesmos_dominios(self) -> None:
        """O `ops/metricas/catalogo.yaml` e o codigo dizem o mesmo dominio."""
        from pathlib import Path

        import kamba_yaml

        raiz = Path(__file__).resolve().parents[3]
        catalogo = kamba_yaml.load_file(raiz / "ops/metricas/catalogo.yaml")
        por_nome = {e["nome"]: e for e in catalogo["metricas"]}
        esperado = {
            m.METRICA_LATENCIA: {"ramo": set(m.RAMOS), "modo": set(m.MODOS)},
            m.METRICA_RESULTADOS: {},
            m.METRICA_MODO: {"modo": set(m.MODOS)},
        }
        for nome, etiquetas in esperado.items():
            with self.subTest(metrica=nome):
                self.assertIn(nome, por_nome)
                declaradas = {
                    e["nome"]: set(e["dominio"]) for e in por_nome[nome]["etiquetas"]
                }
                self.assertEqual(declaradas, etiquetas)
                self.assertEqual(por_nome[nome]["exposta_por"], ["agr"])


if __name__ == "__main__":
    unittest.main()

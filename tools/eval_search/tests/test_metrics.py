"""As metricas do §14.2 com valores conhecidos, empates e consultas sem relevantes."""

from __future__ import annotations

import math
import unittest

from eval_search import metrics
from eval_search.metrics import Resultado


def _r(ordem, graus, *, nr=False, tags=(), qid="q", catalogo="c") -> Resultado:
    return Resultado(qid, catalogo, frozenset(tags), nr, tuple(ordem), graus)


class TestSuccess(unittest.TestCase):
    def test_grau_2_nos_tres_primeiros_conta(self) -> None:
        self.assertEqual(metrics.success_at(["x", "y", "a"], {"a": 2}), 1.0)

    def test_grau_1_nao_conta(self) -> None:
        self.assertEqual(metrics.success_at(["a"], {"a": 1}), 0.0)

    def test_o_quarto_lugar_nao_conta(self) -> None:
        self.assertEqual(metrics.success_at(["x", "y", "z", "a"], {"a": 3}), 0.0)

    def test_repetido_nao_empurra_o_relevante_para_fora(self) -> None:
        """Um `x` repetido conta uma vez: o `a` fica no terceiro lugar."""
        self.assertEqual(metrics.success_at(["x", "x", "y", "a"], {"a": 3}), 1.0)


class TestRecall(unittest.TestCase):
    def test_metade_dos_relevantes(self) -> None:
        self.assertEqual(metrics.recall_at(["a", "x"], {"a": 1, "b": 3}), 0.5)

    def test_grau_zero_nao_e_relevante(self) -> None:
        self.assertEqual(metrics.recall_at(["a"], {"a": 1, "b": 0}), 1.0)

    def test_o_decimo_primeiro_nao_conta(self) -> None:
        ordem = [f"x{i}" for i in range(10)] + ["a"]
        self.assertEqual(metrics.recall_at(ordem, {"a": 2}), 0.0)

    def test_sem_relevantes_nao_esta_definido(self) -> None:
        with self.assertRaises(ValueError):
            metrics.recall_at(["a"], {})


class TestNdcg(unittest.TestCase):
    def test_ordem_ideal_da_um(self) -> None:
        self.assertAlmostEqual(metrics.ndcg_at(["a", "b"], {"a": 3, "b": 2}), 1.0)

    def test_valor_conhecido(self) -> None:
        """`b` (grau 2) em 1.o e `a` (grau 3) em 2.o, com ganho 2^g - 1."""
        dcg = 3 / math.log2(2) + 7 / math.log2(3)
        ideal = 7 / math.log2(2) + 3 / math.log2(3)
        self.assertAlmostEqual(metrics.ndcg_at(["b", "a"], {"a": 3, "b": 2}), dcg / ideal)

    def test_o_ganho_e_exponencial(self) -> None:
        self.assertEqual([metrics.ganho(g) for g in range(4)], [0.0, 1.0, 3.0, 7.0])

    def test_empate_de_graus_e_indiferente(self) -> None:
        graus = {"a": 2, "b": 2, "c": 1}
        self.assertAlmostEqual(metrics.ndcg_at(["a", "b"], graus), metrics.ndcg_at(["b", "a"], graus))

    def test_o_ideal_le_os_tres_maiores_e_nao_os_tres_primeiros(self) -> None:
        graus = {"a": 1, "b": 1, "c": 1, "d": 3}
        self.assertLess(metrics.ndcg_at(["a", "b", "c"], graus), 1.0)

    def test_sem_relevantes_nao_esta_definido(self) -> None:
        with self.assertRaises(ValueError):
            metrics.ndcg_at(["a"], {"a": 0})

    def test_o_ideal_so_le_k_graus(self) -> None:
        """Quatro relevantes de grau 3 e os tres primeiros no topo: nDCG@3 = 1."""
        self.assertAlmostEqual(metrics.ndcg_at(["a", "b", "c"], {"a": 3, "b": 3, "c": 3, "d": 3}), 1.0)

    def test_repetido_nao_infla_o_dcg(self) -> None:
        self.assertAlmostEqual(metrics.ndcg_at(["a", "a", "a"], {"a": 3, "b": 3}),
                               metrics.ndcg_at(["a"], {"a": 3, "b": 3}))


class TestAgregar(unittest.TestCase):
    def test_as_seis_metricas_num_conjunto_conhecido(self) -> None:
        resultados = [
            _r(["a"], {"a": 3}, tags=("typo",)),            # sucesso, typo
            _r([], {"b": 3}),                              # zero resultados
            _r(["x"], {}, nr=True),                         # falso positivo
            _r([], {}, nr=True),                            # vazio, certo
        ]
        agregado = metrics.agregar(resultados)
        self.assertEqual(agregado["consultas"], 4)
        self.assertEqual(agregado["success_at_3"], 0.5)
        self.assertEqual(agregado["recall_at_10"], 0.5)
        self.assertEqual(agregado["ndcg_at_3"], 0.5)
        self.assertEqual(agregado["success_at_3_typo_regionalismo"], 1.0)
        self.assertEqual(agregado["zero_result_rate"], 0.5)
        self.assertEqual(agregado["falso_positivo_nao_resolvivel"], 0.5)

    def test_sem_denominador_e_none_e_nao_zero(self) -> None:
        agregado = metrics.agregar([_r(["a"], {"a": 3})])
        self.assertIsNone(agregado["falso_positivo_nao_resolvivel"])
        self.assertIsNone(agregado["success_at_3_typo_regionalismo"])

    def test_o_nao_resolvivel_fica_fora_das_medias_de_qualidade(self) -> None:
        agregado = metrics.agregar([_r(["a"], {"a": 3}), _r(["x"], {}, nr=True)])
        self.assertEqual(agregado["success_at_3"], 1.0)
        self.assertEqual(agregado["zero_result_rate"], 0.0)

    def test_regionalismo_tambem_conta_como_variante(self) -> None:
        agregado = metrics.agregar([_r([], {"a": 3}, tags=("regionalismo",))])
        self.assertEqual(agregado["success_at_3_typo_regionalismo"], 0.0)


class TestAlvos(unittest.TestCase):
    def test_os_alvos_sao_os_do_paragrafo_14_2(self) -> None:
        self.assertEqual(
            metrics.ALVOS_DO_PILOTO,
            {
                "success_at_3": (">=", 0.85),
                "recall_at_10": (">=", 0.90),
                "ndcg_at_3": (">=", 0.75),
                "success_at_3_typo_regionalismo": (">=", 0.80),
                "zero_result_rate": ("<=", 0.08),
                "falso_positivo_nao_resolvivel": ("<=", 0.10),
            },
        )

    def test_cumpre_nos_dois_sentidos(self) -> None:
        self.assertTrue(metrics.cumpre("success_at_3", 0.85))
        self.assertFalse(metrics.cumpre("success_at_3", 0.84))
        self.assertTrue(metrics.cumpre("zero_result_rate", 0.08))
        self.assertFalse(metrics.cumpre("zero_result_rate", 0.081))
        self.assertIsNone(metrics.cumpre("ndcg_at_3", None))


class TestKappa(unittest.TestCase):
    def test_concordancia_total(self) -> None:
        self.assertEqual(metrics.kappa_de_cohen([0, 1, 2, 3], [0, 1, 2, 3]), 1.0)

    def test_valor_conhecido(self) -> None:
        """15 de 25 concordantes, marginais 15/10 nas duas: kappa = (0,6 - 0,52) / 0,48."""
        a = [1] * 10 + [0] * 5 + [1] * 5 + [0] * 5
        b = [1] * 10 + [1] * 5 + [0] * 5 + [0] * 5
        # observada 15/25 = 0,6; esperada 0,6*0,6 + 0,4*0,4 = 0,52
        self.assertAlmostEqual(metrics.kappa_de_cohen(a, b), (0.6 - 0.52) / (1 - 0.52))

    def test_constantes_iguais_levanta(self) -> None:
        with self.assertRaises(ValueError):
            metrics.kappa_de_cohen([2, 2], [2, 2])

    def test_tamanhos_diferentes_levanta(self) -> None:
        with self.assertRaises(ValueError):
            metrics.kappa_de_cohen([1], [1, 2])


if __name__ == "__main__":
    unittest.main()

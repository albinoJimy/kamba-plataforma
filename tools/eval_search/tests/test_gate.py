"""O *gate* do §14.3 e a linha de base: a regressao artificial tem de o pôr vermelho."""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from eval_search import gate


def _modo(ndcg=0.75, zero=0.05, inexistente=0, divergente=0, caiu=0):
    globais = {
        "success_at_3": 0.8, "recall_at_10": 0.8, "ndcg_at_3": ndcg,
        "success_at_3_typo_regionalismo": 0.5, "zero_result_rate": zero,
        "falso_positivo_nao_resolvivel": 0.3,
    }
    return {
        "global": globais,
        "por_divisao": {"dev": globais, "teste": globais},
        "asercoes": {"produto_citado_inexistente": inexistente, "preco_divergente": divergente},
        "caiu_em_lexical": caiu,
    }


def _relatorio(**por_modo):
    return {
        "dataset": "1.0.0",
        "rotulo": "ensaio",
        "fornecedor_hibrido": "falso-trigramas-v1",
        "modos": {"lexical": _modo(**por_modo), "hibrido": _modo(**por_modo)},
    }


BASE = gate.linha_de_base_de(_relatorio(), "1.0.0", None)


class TestVerificar(unittest.TestCase):
    def test_igual_e_verde(self) -> None:
        self.assertEqual(gate.verificar(_relatorio(), BASE), [])

    def test_ndcg_cai_dois_pontos_ainda_e_verde(self) -> None:
        """0,75 - 0,73 da 0,020000000000000018: sem o arredondamento, ficava vermelho."""
        self.assertGreater(0.75 - 0.73, gate.QUEDA_MAXIMA_DO_NDCG)
        self.assertEqual(gate.verificar(_relatorio(ndcg=0.73), BASE), [])

    def test_regressao_artificial_do_ndcg_e_vermelha(self) -> None:
        falhas = gate.verificar(_relatorio(ndcg=0.7299), BASE)
        self.assertEqual(len(falhas), 2)
        self.assertTrue(all("nDCG@3" in f for f in falhas))

    def test_zero_result_sobe_um_ponto_ainda_e_verde(self) -> None:
        self.assertEqual(gate.verificar(_relatorio(zero=0.06), BASE), [])

    def test_zero_result_sobe_mais_de_um_ponto_e_vermelho(self) -> None:
        self.assertTrue(any("zero-result" in f for f in gate.verificar(_relatorio(zero=0.0601), BASE)))

    def test_melhorar_e_verde(self) -> None:
        self.assertEqual(gate.verificar(_relatorio(ndcg=0.9, zero=0.0), BASE), [])

    def test_hibrido_que_caiu_em_lexical_e_vermelho(self) -> None:
        relatorio = _relatorio()
        relatorio["modos"]["hibrido"]["caiu_em_lexical"] = 3
        self.assertEqual(gate.verificar(relatorio, BASE), ["hibrido: 3 consulta(s) cairam em lexical"])
        self.assertFalse(gate.verde(relatorio))

    def test_asercao_diferente_de_zero_e_vermelha(self) -> None:
        self.assertTrue(gate.verificar(_relatorio(inexistente=1), BASE))
        self.assertTrue(gate.verificar(_relatorio(divergente=1), BASE))

    def test_modo_em_falta_e_vermelho(self) -> None:
        relatorio = _relatorio()
        del relatorio["modos"]["hibrido"]
        self.assertEqual(gate.verificar(relatorio, BASE), ["hibrido: o relatorio nao mede este modo"])

    def test_metrica_sem_valor_e_vermelha(self) -> None:
        relatorio = _relatorio()
        relatorio["modos"]["lexical"]["global"]["ndcg_at_3"] = None
        self.assertTrue(gate.verificar(relatorio, BASE))

    def test_outro_dataset_e_vermelho(self) -> None:
        relatorio = _relatorio()
        relatorio["dataset"] = "1.1.0"
        self.assertTrue(any("dataset mudou" in f for f in gate.verificar(relatorio, BASE)))

    def test_outro_fornecedor_no_hibrido_e_vermelho(self) -> None:
        relatorio = _relatorio()
        relatorio["fornecedor_hibrido"] = "modelo-real"
        self.assertTrue(any("fornecedor" in f for f in gate.verificar(relatorio, BASE)))


class TestRegistar(unittest.TestCase):
    def test_so_um_relatorio_verde_se_regista(self) -> None:
        with self.assertRaises(ValueError):
            gate.linha_de_base_de(_relatorio(inexistente=1), "1.0.0", None)
        so_lexical = _relatorio()
        del so_lexical["modos"]["hibrido"]
        with self.assertRaises(ValueError):
            gate.linha_de_base_de(so_lexical, "1.0.0", None)

    def test_a_versao_tem_de_subir_e_ser_semver(self) -> None:
        with self.assertRaises(ValueError):
            gate.linha_de_base_de(_relatorio(), "1.0.0", BASE)
        with self.assertRaises(ValueError):
            gate.linha_de_base_de(_relatorio(), "1.0", None)
        self.assertEqual(gate.linha_de_base_de(_relatorio(), "1.0.1", BASE)["versao"], "1.0.1")

    def test_a_linha_de_base_guarda_so_as_metricas(self) -> None:
        self.assertEqual(set(BASE["modos"]["lexical"]), {"global", "por_divisao"})
        self.assertEqual(BASE["fornecedor_hibrido"], "falso-trigramas-v1")


class TestCli(unittest.TestCase):
    def correr(self, *argumentos) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return gate.main(argumentos)

    def test_registar_e_depois_verificar_uma_regressao(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            relatorio = Path(pasta) / "r.json"
            base = Path(pasta) / "baseline.json"
            relatorio.write_text(json.dumps(_relatorio()), encoding="utf-8")
            self.assertEqual(self.correr("registar", str(relatorio), "--versao", "1.0.0", "--linha-de-base", str(base)), 0)
            self.assertEqual(self.correr("verificar", str(relatorio), "--linha-de-base", str(base)), 0)
            pior = copy.deepcopy(_relatorio(ndcg=0.5))
            relatorio.write_text(json.dumps(pior), encoding="utf-8")
            self.assertEqual(self.correr("verificar", str(relatorio), "--linha-de-base", str(base)), 1)
            self.assertEqual(self.correr("registar", str(relatorio), "--versao", "1.0.0", "--linha-de-base", str(base)), 1)

    def test_a_linha_de_base_versionada_passa_no_seu_relatorio(self) -> None:
        """A linha de base do repositorio e o relatorio de que nasceu concordam."""
        base = json.loads(gate.LINHA_DE_BASE.read_text(encoding="utf-8"))
        relatorio = json.loads((gate.LINHA_DE_BASE.parent / "reports" / f"{base['versao']}.json").read_text(encoding="utf-8"))
        self.assertEqual(gate.verificar(relatorio, base), [])
        self.assertEqual(gate.linha_de_base_de(relatorio, base["versao"], None), base)


if __name__ == "__main__":
    unittest.main()

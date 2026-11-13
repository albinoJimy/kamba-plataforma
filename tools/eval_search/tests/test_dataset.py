"""O `golden_search`: os ficheiros, as proporcoes do criterio 1, a divisao e o PII."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from eval_search import catalogos, dataset


class TestOsFicheirosSaoOsDaCuradoria(unittest.TestCase):
    def test_check_conforme(self) -> None:
        self.assertEqual(dataset.verificar(), [])

    def _copia(self) -> Path:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        shutil.copytree(dataset.DADOS, pasta / "dados")
        return pasta / "dados"

    def test_a_copia_intacta_e_conforme(self) -> None:
        self.assertEqual(dataset.verificar(self._copia()), [])

    def test_um_grau_editado_a_mao_e_recusado(self) -> None:
        base = self._copia()
        caminho = base / "golden_search" / "mercearia-v1.jsonl"
        texto = caminho.read_text(encoding="utf-8")
        caminho.write_text(texto.replace('"grau": 3', '"grau": 2', 1), encoding="utf-8", newline="\n")
        self.assertEqual(dataset.verificar(base), ["difere da curadoria: golden_search/mercearia-v1.jsonl"])

    def test_um_ficheiro_a_mais_e_recusado(self) -> None:
        base = self._copia()
        (base / "golden_search" / "extra.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertEqual(dataset.verificar(base), ["a curadoria nao gera golden_search/extra.jsonl"])

    def test_um_telefone_num_ficheiro_e_recusado(self) -> None:
        base = self._copia()
        (base / "catalogos" / "notas.txt").write_text("ligar 923 456 789\n", encoding="utf-8")
        self.assertTrue(any(p.startswith("PII em catalogos/notas.txt") for p in dataset.verificar(base)))


class TestCriterio1(unittest.TestCase):
    """As proporcoes, contadas nos ficheiros que o executor le."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registos = dataset.ler()

    def test_trezentas_consultas_em_cinco_catalogos(self) -> None:
        self.assertGreaterEqual(len(self.registos), 300)
        self.assertGreaterEqual(len({r.catalogo for r in self.registos}), 5)

    def test_vinte_por_cento_typo_ou_regionalismo(self) -> None:
        n = sum(bool(r.tags & {"typo", "regionalismo"}) for r in self.registos)
        self.assertGreaterEqual(n / len(self.registos), 0.20)

    def test_dez_por_cento_nao_resolvivel_e_sem_relevantes(self) -> None:
        nr = [r for r in self.registos if r.nao_resolvivel]
        self.assertGreaterEqual(len(nr) / len(self.registos), 0.10)
        self.assertTrue(all(r.graus == {} for r in nr))

    def test_quinze_por_cento_de_voz_com_erro_de_stt_que_se_le_no_texto(self) -> None:
        """Conta-se a forma do texto, e nao a etiqueta, que o `q(voz=True)` poe sozinho."""
        vocab = {
            catalogos.snapshot(c): dataset.vocabulario(p) for c, p in catalogos.CATALOGOS.items()
        }
        voz = [r for r in self.registos if r.origem == "voz"]
        sem_erro = [r.qid for r in voz if not dataset.artefactos_stt(r.texto, vocab[r.catalogo])]
        self.assertEqual(sem_erro, [])
        self.assertGreaterEqual(len(voz) / len(self.registos), 0.15)
        self.assertTrue(all("voz_stt" in r.tags for r in voz))

    def test_um_ficheiro_por_snapshot_e_o_formato_do_14_1(self) -> None:
        nomes = sorted(p.stem for p in dataset.PASTA_DAS_CONSULTAS.glob("*.jsonl"))
        self.assertEqual(nomes, sorted(catalogos.snapshot(c) for c in catalogos.CATALOGOS))
        campos = {"qid", "tenant", "origem", "texto", "tags", "restricoes", "relevantes", "nao_resolvivel"}
        for caminho in dataset.PASTA_DAS_CONSULTAS.glob("*.jsonl"):
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                self.assertLessEqual(campos, set(json.loads(linha)))

    def test_cada_relevante_existe_no_catalogo_da_consulta(self) -> None:
        for r in self.registos:
            refs = {str(p["product_ref"]) for p in dataset.ler_catalogo(r.catalogo)}
            self.assertLessEqual(set(r.graus), refs, r.qid)

    def test_qids_unicos(self) -> None:
        self.assertEqual(max(Counter(r.qid for r in self.registos).values()), 1)


class TestGraus(unittest.TestCase):
    def test_a_regra_dos_graus(self) -> None:
        produtos = catalogos.MERCEARIA
        from eval_search.consultas import q

        graus = dataset.graus(q("arroz agulha", "arroz", "agulha"), produtos)
        self.assertEqual(graus["arroz-agulha-5kg"], 3)
        self.assertEqual(graus["arroz-carolino-1kg"], 2)
        self.assertNotIn("feijao-preto-1kg", graus)

    def test_o_preco_dito_exclui(self) -> None:
        from eval_search.consultas import q

        graus = dataset.graus(q("arroz ate 2000", "arroz", max_kz=2000), catalogos.MERCEARIA)
        self.assertNotIn("arroz-agulha-5kg", graus)
        self.assertIn("arroz-agulha-1kg", graus)

    def test_substituto_vale_um(self) -> None:
        from eval_search.consultas import q

        graus = dataset.graus(q("makayabu", "bacalhau", subs=("peixe_seco",)), catalogos.MERCEARIA)
        self.assertEqual(graus["peixe-seco-carapau"], 1)

    def test_consulta_sem_grau_dois_recusa_se(self) -> None:
        from eval_search.consultas import q

        with self.assertRaises(ValueError):
            dataset.registo("mercearia", 0, q("arroz ate 10", "arroz", max_kz=10))


class TestArtefactosDeStt(unittest.TestCase):
    VOCAB = frozenset({"tundavala", "karite", "frigorifico", "sumo", "manga"})

    def test_cada_forma(self) -> None:
        casos = {
            "sumo de manga tunda vala": {"partida"},
            "creme de cari te": {"partida"},
            "frigorifico de duzentos litros": {"extenso"},
            "leite u a te": {"letras"},
            "é é sumo": {"hesitacao"},
            "hum sumo": {"hesitacao"},
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(dataset.artefactos_stt(texto, self.VOCAB), esperado)

    def test_texto_limpo_nao_tem_artefacto(self) -> None:
        for texto in ("sumo de manga", "queria um frigorifico", "sumo manga"):
            with self.subTest(texto=texto):
                self.assertEqual(dataset.artefactos_stt(texto, self.VOCAB), set())

    def test_duas_palavras_do_catalogo_nao_sao_uma_palavra_partida(self) -> None:
        self.assertEqual(dataset.artefactos_stt("sumo manga", frozenset({"sumo", "manga", "sumomanga"})), set())


class TestDivisao(unittest.TestCase):
    def test_fixa_pelo_qid(self) -> None:
        self.assertEqual(dataset.divisao_de("mercearia-q001"), dataset.divisao_de("mercearia-q001"))

    def test_setenta_trinta_num_universo_grande(self) -> None:
        dev = sum(dataset.divisao_de(f"x-{i}") == dataset.DEV for i in range(10_000))
        self.assertAlmostEqual(dev / 10_000, 0.70, delta=0.02)

    def test_as_duas_divisoes_tem_consultas(self) -> None:
        self.assertTrue(dataset.ler(dataset.DEV))
        self.assertTrue(dataset.ler(dataset.TESTE))
        self.assertTrue(all(r.divisao == dataset.DEV for r in dataset.ler(dataset.DEV)))


class TestAfinacaoNaoLeOTeste(unittest.TestCase):
    """Criterio 3: o executor de afinacao falha se ler a divisao `teste`."""

    def test_ler_o_teste_em_afinacao_levanta(self) -> None:
        with dataset.afinacao():
            with self.assertRaises(dataset.LeituraDoTesteProibida):
                dataset.ler(dataset.TESTE)

    def test_ler_tudo_em_afinacao_levanta(self) -> None:
        with dataset.afinacao():
            with self.assertRaises(dataset.LeituraDoTesteProibida):
                dataset.ler()

    def test_dev_em_afinacao_le_e_so_dev(self) -> None:
        with dataset.afinacao():
            dev = dataset.ler(dataset.DEV)
        self.assertTrue(dev)
        self.assertEqual({r.divisao for r in dev}, {dataset.DEV})

    def test_fora_da_afinacao_o_teste_le_se(self) -> None:
        self.assertTrue(dataset.ler(dataset.TESTE))
        self.assertFalse(dataset.em_afinacao())

    def test_o_with_repoe_o_estado_mesmo_com_erro(self) -> None:
        with self.assertRaises(RuntimeError):
            with dataset.afinacao():
                raise RuntimeError("x")
        self.assertFalse(dataset.em_afinacao())

    def test_um_ficheiro_que_mente_na_divisao_recusa_se(self) -> None:
        """Uma consulta de teste marcada `dev` no ficheiro nao entra na afinacao."""
        teste = next(r for r in dataset.ler(dataset.TESTE))
        with tempfile.TemporaryDirectory() as pasta:
            linha = {
                "qid": teste.qid, "tenant": teste.tenant, "catalogo": teste.catalogo,
                "origem": teste.origem, "texto": teste.texto, "tags": [],
                "restricoes": {}, "relevantes": [], "nao_resolvivel": True, "divisao": dataset.DEV,
            }
            (Path(pasta) / "x.jsonl").write_text(json.dumps(linha) + "\n", encoding="utf-8")
            with dataset.afinacao():
                with self.assertRaises(ValueError):
                    dataset.ler(dataset.DEV, pasta=Path(pasta))


class TestScannerDePii(unittest.TestCase):
    def test_telefone_nas_formas_usuais(self) -> None:
        """Nove algarismos, com qualquer separador de ate tres caracteres.

        Sem o indicativo do pais: o padrao nao depende dele (um lance de nove
        basta), e escreve-lo aqui pedia uma linha no inventario do `meta-sim`.
        """
        for texto in ("ligue 923 456 789", "923-456-789", "923.456.789", "923 - 456 - 789",
                      "923_456_789", "(923) 456 789", "９２３４５６７８９"):
            with self.subTest(texto=texto):
                self.assertTrue(any(a.startswith("telefone_ou_nif") for a in dataset.pii_em(texto)))

    def test_separador_de_quatro_caracteres_ja_nao_e_um_lance(self) -> None:
        self.assertEqual(dataset.pii_em("923 -- 456 -- 789"), [])

    def test_telefone_ditado_algarismo_a_algarismo(self) -> None:
        self.assertTrue(any(a.startswith("telefone_ditado") for a in dataset.pii_em(
            "ligue para nove dois três quatro cinco seis sete oito nove")))
        self.assertEqual(dataset.pii_em("gerador de dois e meio"), [])

    def test_email_dito(self) -> None:
        self.assertTrue(dataset.pii_em("loja arroba exemplo ponto ao"))

    def test_nif_e_bi(self) -> None:
        self.assertTrue(dataset.pii_em("o NIF da loja"))
        self.assertTrue(dataset.pii_em("BI 004567890LA042"))

    def test_email(self) -> None:
        self.assertTrue(dataset.pii_em("escreve para loja@exemplo.ao"))

    def test_nome_proprio_com_e_sem_acento(self) -> None:
        self.assertIn("nome:joao", dataset.pii_em("entrega ao João"))
        self.assertIn("nome:joao", dataset.pii_em("entrega ao joao"))

    def test_o_que_o_catalogo_tem_nao_e_pii(self) -> None:
        for texto in ("Ar condicionado split 12000 BTU", "Powerbank 20000 mAh", "ananás", "sumo 1,5 L"):
            with self.subTest(texto=texto):
                self.assertEqual(dataset.pii_em(texto), [])

    def test_zero_ocorrencias_nos_ficheiros(self) -> None:
        for caminho in sorted(dataset.DADOS.rglob("*")):
            if caminho.is_file():
                with self.subTest(ficheiro=caminho.name):
                    self.assertEqual(dataset.pii_em(caminho.read_text(encoding="utf-8")), [])

    def test_o_gerador_recusa_um_catalogo_com_pii(self) -> None:
        original = catalogos.CATALOGOS["mercearia"]
        catalogos.CATALOGOS["mercearia"] = (*original, catalogos._p("x", "Bolo, ligue 923 456 789", 1, "bolo"))
        try:
            with self.assertRaises(dataset.PiiNoDataset):
                dataset.gerar()
        finally:
            catalogos.CATALOGOS["mercearia"] = original

    def test_o_manifesto_lista_o_consentimento_e_a_origem(self) -> None:
        manifesto = json.loads(dataset.MANIFESTO.read_text(encoding="utf-8"))
        self.assertEqual(manifesto["origem"], "sintetica")
        self.assertEqual(manifesto["conversas_reais"], 0)
        self.assertIn("consentimento_especifico", manifesto)
        self.assertIn("nunca treinar", manifesto["uso"])

    def test_a_impressao_e_base32_sem_lances_de_algarismos(self) -> None:
        for i in range(200):
            self.assertEqual(dataset.pii_em(dataset.impressao(f"texto {i}")), [])


if __name__ == "__main__":
    unittest.main()

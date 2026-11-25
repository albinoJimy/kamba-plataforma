"""Gate 18: a tag so depois da verificacao verde, e o arquivo uma vez."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release import tag
from release.tests.apoio import lock_com

VERDE = tag.VerificacaoPosDeploy(True, 0.0, 10.0, True)


class TestSemVer(unittest.TestCase):
    def test_os_tres_tipos(self) -> None:
        self.assertEqual(tag.proxima_versao("v0.3.1", "maior"), "1.0.0")
        self.assertEqual(tag.proxima_versao("0.3.1", "menor"), "0.4.0")
        self.assertEqual(tag.proxima_versao("v0.3.1", "correccao"), "0.3.2")

    def test_a_primeira(self) -> None:
        self.assertEqual(tag.proxima_versao(None, "menor"), "0.1.0")

    def test_anterior_que_nao_e_semver_levanta(self) -> None:
        for errada in ("1.2", "v01.2.3", "1.2.3-rc1", "latest"):
            with self.subTest(errada=errada), self.assertRaises(ValueError):
                tag.proxima_versao(errada, "correccao")


class TestVerificacao(unittest.TestCase):
    def test_chave_em_falta_e_recusa(self) -> None:
        with self.assertRaises(tag.TagRecusada):
            tag.VerificacaoPosDeploy.de_json({"healthz": True, "taxa_de_erro_do_ingress": 0})

    def test_cada_sinal_sozinho_recusa(self) -> None:
        casos = {
            "/healthz": tag.VerificacaoPosDeploy(False, 0.0, 10.0, True),
            "taxa": tag.VerificacaoPosDeploy(True, 0.05, 10.0, True),
            "fila": tag.VerificacaoPosDeploy(True, 0.0, 120.0, True),
            "sonda": tag.VerificacaoPosDeploy(True, 0.0, 10.0, False),
            "nan": tag.VerificacaoPosDeploy(True, float("nan"), 10.0, True),
        }
        for nome, verificacao in casos.items():
            with self.subTest(nome=nome):
                self.assertTrue(verificacao.falhas())

    def test_healthz_tem_de_ser_true_e_nao_so_verdadeiro(self) -> None:
        v = tag.VerificacaoPosDeploy.de_json(
            {"healthz": "sim", "taxa_de_erro_do_ingress": 0, "idade_da_fila_s": 1, "sonda_externa": True}
        )
        self.assertIn("/healthz", v.falhas())


class TestArquivar(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name)
        self.lock = lock_com(gwy=("a", "build"), postgres=("b", "terceiros"))
        self.lock_caminho = self.pasta / "release.lock"
        self.lock_caminho.write_text(self.lock.como_json(), encoding="utf-8")
        self.sboms = self.pasta / "sboms"
        self.sboms.mkdir()
        (self.sboms / "gwy.sbom.json").write_text('{"bomFormat": "CycloneDX"}', encoding="utf-8")
        self.destino = self.pasta / "arquivo"

    def _arquivar(self, verificacao: tag.VerificacaoPosDeploy = VERDE) -> Path:
        return tag.arquivar("0.4.0", self.lock, self.lock_caminho, self.sboms, verificacao, self.destino)

    def test_verde_arquiva_lock_sbom_e_manifesto(self) -> None:
        pasta = self._arquivar()
        self.assertEqual(pasta.name, "v0.4.0")
        self.assertEqual(sorted(p.name for p in pasta.iterdir()),
                         ["MANIFESTO.json", "gwy.sbom.json", "release.lock"])
        manifesto = json.loads((pasta / "MANIFESTO.json").read_text(encoding="utf-8"))
        self.assertEqual(manifesto["tag"], "v0.4.0")
        self.assertEqual(set(manifesto["ficheiros"]), {"gwy.sbom.json", "release.lock"})

    def test_negativo_verificacao_vermelha_nao_escreve_nada(self) -> None:
        with self.assertRaises(tag.TagRecusada):
            self._arquivar(tag.VerificacaoPosDeploy(False, 0.0, 10.0, True))
        self.assertFalse(self.destino.exists())

    def test_negativo_sbom_em_falta_nao_escreve_nada(self) -> None:
        (self.sboms / "gwy.sbom.json").unlink()
        with self.assertRaises(tag.TagRecusada):
            self._arquivar()
        self.assertFalse(self.destino.exists())

    def test_a_mesma_versao_nao_se_arquiva_duas_vezes(self) -> None:
        self._arquivar()
        with self.assertRaises(tag.TagRecusada):
            self._arquivar()


if __name__ == "__main__":
    unittest.main()

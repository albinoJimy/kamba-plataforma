"""`healthz_check`: validacao da sonda contra o contrato.

O KAM-001 entregou esta ferramenta sem testes — o que so se viu quando o gate 4
comecou a medir `tools/**` e a deu a 0%. Testa-se o que se pode sem servidor: o
carregamento do esquema e a deteccao de servico trocado.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import healthz_check

ROOT = Path(__file__).resolve().parents[3]


class TestEsquema(unittest.TestCase):
    def test_o_caminho_do_esquema_existe(self) -> None:
        self.assertTrue(healthz_check.SCHEMA_PATH.is_file())

    def test_o_validador_carrega_e_o_esquema_e_valido(self) -> None:
        try:
            validador = healthz_check._validator()
        except SystemExit:
            self.skipTest("jsonschema nao instalado; corre no CI depois do bootstrap")
        carga = {
            "status": "ok",
            "service": "gwy",
            "version": "0.1.0",
            "commit": "unknown",
        }
        self.assertEqual(list(validador.iter_errors(carga)), [])

    def test_recusa_carga_fora_do_contrato(self) -> None:
        try:
            validador = healthz_check._validator()
        except SystemExit:
            self.skipTest("jsonschema nao instalado")
        for carga in (
            {"status": "degraded", "service": "gwy", "version": "0.1.0", "commit": "unknown"},
            {"status": "ok", "service": "inventado", "version": "0.1.0", "commit": "unknown"},
            {"status": "ok", "service": "gwy", "version": "v1", "commit": "unknown"},
            {"status": "ok", "service": "gwy", "version": "0.1.0", "commit": "ABC"},
            {"status": "ok", "service": "gwy", "version": "0.1.0"},
        ):
            with self.subTest(carga=carga):
                self.assertTrue(list(validador.iter_errors(carga)))


class TestSonda(unittest.TestCase):
    def test_porta_fechada_devolve_erro(self) -> None:
        """Nao levanta: devolve estado 0 e a razao."""
        estado, corpo, erro = healthz_check.probe("127.0.0.1", 1, timeout=0.5)
        self.assertEqual(estado, 0)
        self.assertIsNone(corpo)
        self.assertIsNotNone(erro)


if __name__ == "__main__":
    unittest.main()

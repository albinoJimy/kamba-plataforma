"""O resumo do piloto tem esquema fechado: sem texto livre e sem campo de pista."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_piloto import entradas
from gate_piloto.tests import sintetico

SHA = "ab" * 32


class TestAceita(unittest.TestCase):
    def test_o_minimo(self) -> None:
        r = entradas.validar({"forma": 1, "sintetico": False})
        self.assertFalse(r.sintetico)
        self.assertIsNone(r.pagantes_recorrentes)

    def test_o_completo(self) -> None:
        r = entradas.validar(
            sintetico.resumo(
                manifesto="docs/x/piloto_congelado.json",
                manifesto_sha256=SHA,
                semana_do_gate=12,
                pagantes_recorrentes=4,
                canal_comercial_repetivel=True,
                custo_por_pme_minor=5150,
                moeda="USD",
                carta5={"F1": {"estado": "satisfeito", "evidencia": "docs/a.md"}},
            )
        )
        self.assertEqual(r.carta5["F1"], entradas.Item("satisfeito", "docs/a.md"))
        self.assertEqual(r.custo_por_pme_minor, 5150)


class TestRecusa(unittest.TestCase):
    def _recusa(self, dados: object, padrao: str) -> None:
        with self.assertRaisesRegex(entradas.EntradaInvalida, padrao):
            entradas.validar(dados)

    def test_numeros_de_pista_nao_entram(self) -> None:
        for chave in ("pista", "meses_de_pista", "capital_minor", "ponto_de_paragem"):
            with self.subTest(chave=chave):
                self._recusa(sintetico.resumo(**{chave: 6}), "fora do esquema")

    def test_texto_livre_nao_entra(self) -> None:
        self._recusa(sintetico.resumo(nota="texto livre sobre uma PME"), "fora do esquema")
        self._recusa(
            sintetico.resumo(carta5={"F1": {"estado": "satisfeito", "evidencia": "texto livre com espaços"}}),
            "caminho",
        )
        self._recusa(sintetico.resumo(carta5={"F1": {"estado": "satisfeito", "nota": "x"}}), "só")

    def test_itens_derivados_nao_se_declaram(self) -> None:
        for item in ("P2", "P3", "F3"):
            with self.subTest(item=item):
                self._recusa(sintetico.resumo(carta5={item: {"estado": "satisfeito"}}), "não é declarável")

    def test_forma_e_sintetico_obrigatorios(self) -> None:
        self._recusa({"sintetico": True}, "forma")
        self._recusa({"forma": 2, "sintetico": True}, "forma")
        self._recusa({"forma": 1}, "sintetico")
        self._recusa({"forma": 1, "sintetico": "sim"}, "sintetico")
        self._recusa([], "objecto")

    def test_inteiros(self) -> None:
        self._recusa(sintetico.resumo(pagantes_recorrentes=True), "inteiro")
        self._recusa(sintetico.resumo(pagantes_recorrentes=-1), "inteiro")
        self._recusa(sintetico.resumo(pagantes_recorrentes=2.5), "inteiro")
        self._recusa(sintetico.resumo(custo_por_pme_minor=51.5, moeda="USD"), "inteiro")

    def test_pares(self) -> None:
        self._recusa(sintetico.resumo(manifesto="piloto_congelado.json"), "juntos")
        self._recusa(sintetico.resumo(manifesto_sha256=SHA), "juntos")
        self._recusa(sintetico.resumo(custo_por_pme_minor=10), "juntos")
        self._recusa(sintetico.resumo(manifesto="piloto_congelado.json", manifesto_sha256="AB" * 32), "hexadecimais")
        self._recusa(sintetico.resumo(custo_por_pme_minor=10, moeda="usd"), "ISO")

    def test_o_manifesto_e_o_do_kam_109(self) -> None:
        # O nome é contrato com o KAM-109 (`tools/piloto/cli.py`); a exportação
        # sozinha não congela as folhas de H8 nem o h6_export.
        for mau in ("piloto_export.json", "docs/x/manifesto.json", "piloto_congelado.json.bak"):
            with self.subTest(manifesto=mau):
                self._recusa(sintetico.resumo(manifesto=mau, manifesto_sha256=SHA), "piloto_congelado.json")
        self._recusa(sintetico.resumo(exportacao="a.csv", exportacao_sha256=SHA), "fora do esquema")

    def test_caminhos(self) -> None:
        for mau in ("../fora.md", "a/../../b.md", "/abs.md", "C:/x.md", "-x.md", ""):
            with self.subTest(caminho=mau):
                self._recusa(sintetico.resumo(carta5={"F1": {"estado": "satisfeito", "evidencia": mau}}), "caminho")

    def test_estado_e_canal(self) -> None:
        self._recusa(sintetico.resumo(carta5={"F1": {"estado": "verde"}}), "estado")
        self._recusa(sintetico.resumo(carta5=[]), "objecto por item")
        self._recusa(sintetico.resumo(carta5={"F1": "satisfeito"}), "só")
        self._recusa(sintetico.resumo(canal_comercial_repetivel="sim"), "canal")


class TestLer(unittest.TestCase):
    def test_json_partido_e_ficheiro_em_falta(self) -> None:
        with TemporaryDirectory() as d:
            mau = Path(d) / "r.json"
            mau.write_text("{", encoding="utf-8")
            with self.assertRaises(entradas.EntradaInvalida):
                entradas.ler(mau)
            with self.assertRaises(entradas.EntradaInvalida):
                entradas.ler(Path(d) / "nao.json")
            bom = Path(d) / "b.json"
            bom.write_text(json.dumps(sintetico.resumo()), encoding="utf-8")
            self.assertTrue(entradas.ler(bom).sintetico)


if __name__ == "__main__":
    unittest.main()

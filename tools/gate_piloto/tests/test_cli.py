"""O comando de ponta a ponta, sobre entradas sintéticas, e os três códigos de saída."""

from __future__ import annotations

import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_piloto import cli
from gate_piloto.tests import sintetico


def _correr(argv: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.principal(argv)
    return codigo, saida.getvalue(), erro.getvalue()


class TestPontaAPonta(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / "ev").mkdir()
        (self.raiz / "ev/f1.md").write_text("sintético", encoding="utf-8")
        self.registo = self.raiz / "registo.md"
        self.registo.write_text(
            sintetico.registo(
                {
                    "H1": ("10", "3", "refutada", "ev/h1.md"),
                    "H6": ("120", "9", "confirmada", "ev/h6.md"),
                    "H7": ("100", "88", "confirmada", "ev/h7.md"),
                }
            ),
            encoding="utf-8",
        )
        self.resumo = self.raiz / "resumo.json"
        self.resumo.write_text(
            json.dumps(
                sintetico.resumo(
                    semana_do_gate=12,
                    pagantes_recorrentes=2,
                    canal_comercial_repetivel=False,
                    canais_de_acesso_mantidos=0,
                    custo_por_pme_minor=6105,
                    moeda="USD",
                    exportacao="ev/exportacao.csv",
                    exportacao_sha256="cd" * 32,
                    carta5={"F1": {"estado": "satisfeito", "evidencia": "ev/f1.md"}},
                )
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pacote(self, *extra: str) -> tuple[int, str, str]:
        return _correr(
            ["--root", str(self.raiz), "pacote", "--registo", str(self.registo),
             "--resumo", str(self.resumo), "--data", "1 de Janeiro de 2000", *extra]
        )

    def test_o_pacote_sintetico(self) -> None:
        codigo, texto, _ = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("**SINTÉTICO — não é evidência.**", texto)
        # H6 com 120 conversas declarada confirmada sai inconclusiva.
        self.assertRegex(texto, r"\| H6 \|.*\| confirmada \| \*\*inconclusiva\*\* \|.*amostra 120 < 500")
        self.assertRegex(texto, r"\| H1 \|.*\| refutada \| \*\*refutada\*\* \|")
        self.assertIn("| H1 | Voltar às entrevistas", texto)
        self.assertIn("nenhum canal de acesso mantido (KAM-106) | Antes de construir mais", texto)
        self.assertIn("**Paragem total**", texto)
        self.assertIn("**VERIFICADA**", texto)
        self.assertIn("61,05 USD", texto)
        self.assertIn("`ev/exportacao.csv`", texto)
        self.assertIn("| F1 |", texto)
        self.assertRegex(texto, r"\| F1 \|.*\| satisfeito \| ev/f1.md \|")
        self.assertRegex(texto, r"\| P2 \|.*\| \*\*não satisfeito\*\* \|")
        self.assertIn("| Meses de pista restantes | *por preencher pelo fundador* |", texto)
        self.assertIn("| Data | 1 de Janeiro de 2000 |", texto)

    def test_sem_resumo_e_pre_visualizacao(self) -> None:
        codigo, texto, _ = _correr(
            ["--root", str(self.raiz), "pacote", "--registo", str(self.registo)]
        )
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("Pré-visualização sem resumo", texto)
        self.assertIn("não avaliável (falta semana_do_gate", texto)
        self.assertNotIn("SINTÉTICO — não é evidência", texto)

    def test_deterministico_e_check(self) -> None:
        destino = self.raiz / "Gate_Piloto.md"
        self.assertEqual(self._pacote("--saida", str(destino))[0], cli.SAIDA_CONFORME)
        self.assertEqual(self._pacote("--check", str(destino))[0], cli.SAIDA_CONFORME)
        destino.write_text(destino.read_text(encoding="utf-8") + "editado à mão\n", encoding="utf-8")
        codigo, _, erro = self._pacote("--check", str(destino))
        self.assertEqual(codigo, cli.SAIDA_DIVERGE)
        self.assertIn("regenera", erro)
        self.assertEqual(self._pacote("--check", str(self.raiz / "nao.md"))[0], cli.SAIDA_ERRO)

    def test_o_hash_confere_quando_a_exportacao_esta_na_arvore(self) -> None:
        exportacao = self.raiz / "ev/exportacao.csv"
        exportacao.write_bytes(b"pme,pagou;sintetica,1")
        codigo, _, erro = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("SHA-256", erro)
        dados = json.loads(self.resumo.read_text(encoding="utf-8"))
        dados["exportacao_sha256"] = hashlib.sha256(exportacao.read_bytes()).hexdigest()
        self.resumo.write_text(json.dumps(dados), encoding="utf-8")
        self.assertEqual(self._pacote()[0], cli.SAIDA_CONFORME)

    def test_entradas_que_nao_servem_saem_com_2(self) -> None:
        self.resumo.write_text(json.dumps(sintetico.resumo(meses_de_pista=9)), encoding="utf-8")
        codigo, texto, erro = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertEqual(texto, "")
        self.assertIn("pista", erro)
        self.registo.write_text("# vazio\n", encoding="utf-8")
        self.assertEqual(
            _correr(["pacote", "--registo", str(self.registo)])[0], cli.SAIDA_ERRO
        )


if __name__ == "__main__":
    unittest.main()

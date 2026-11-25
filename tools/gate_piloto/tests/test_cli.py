"""O comando de ponta a ponta, sobre entradas sintéticas, e os três códigos de saída."""

from __future__ import annotations

import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_piloto import cli, entradas
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
        for nome in ("f1", "h1", "h6", "h7"):
            (self.raiz / f"ev/{nome}.md").write_text("sintético", encoding="utf-8")
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
                    custo_por_pme_minor=6105,
                    moeda="USD",
                    manifesto="ev/piloto_congelado.json",
                    manifesto_sha256="cd" * 32,
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
        self.assertIn("nenhum canal repetível (KAM-106) | Antes de construir mais", texto)
        self.assertIn("**Paragem total**", texto)
        self.assertIn("**VERIFICADA**", texto)
        self.assertIn("61,05 USD", texto)
        self.assertIn("| Manifesto congelado do KAM-109 | `ev/piloto_congelado.json` |", texto)
        self.assertIn("| SHA-256 conferido contra o ficheiro | **não**", texto)
        self.assertIn("| F1 |", texto)
        self.assertIn("| satisfeito | [`ev/f1.md`](../../../../ev/f1.md) |", texto)
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

    def _manifesto(self, conteudo: bytes) -> None:
        """Escreve o manifesto na árvore e põe o *hash* dele no resumo."""
        (self.raiz / "ev/piloto_congelado.json").write_bytes(conteudo)
        dados = json.loads(self.resumo.read_text(encoding="utf-8"))
        dados["manifesto_sha256"] = hashlib.sha256(conteudo).hexdigest()
        self.resumo.write_text(json.dumps(dados), encoding="utf-8")

    def test_o_manifesto_na_arvore_confere_se(self) -> None:
        # A forma que o `congelar` do KAM-109 escreve (`tools/piloto/exportacao.py`).
        bom = {
            "formato": "kamba-piloto-congelado/1",
            "congelado_em": "2000-01-01T00:00:00+00:00",
            "ficheiros": [
                {"nome": "h6_export.json", "bytes": 2, "sha256": "ef" * 32},
                {"nome": "piloto_export.json", "bytes": 2, "sha256": "ab" * 32},
            ],
        }
        # O hash do resumo («cd» * 32) não é o do ficheiro: sai com 2.
        (self.raiz / "ev/piloto_congelado.json").write_text(json.dumps(bom), encoding="utf-8")
        codigo, _, erro = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("SHA-256", erro)

        self._manifesto(json.dumps(bom).encode("utf-8"))
        codigo, texto, _ = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("| SHA-256 conferido contra o ficheiro | sim |", texto)

        maus = {
            "não tem o formato": {**bom, "formato": "kamba-piloto-export/1"},
            "não congela o piloto_export.json": {**bom, "ficheiros": bom["ficheiros"][:1]},
            "não congela o piloto_export.json ": {**bom, "ficheiros": "piloto_export.json"},
        }
        for esperado, mau in maus.items():
            with self.subTest(esperado=esperado):
                self._manifesto(json.dumps(mau).encode("utf-8"))
                codigo, texto, erro = self._pacote()
                self.assertEqual(codigo, cli.SAIDA_ERRO)
                self.assertEqual(texto, "")
                self.assertIn(esperado.strip(), erro)
        self._manifesto(b"{partido")
        codigo, _, erro = self._pacote()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("não é JSON", erro)

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


class TestContratoComOKam109(unittest.TestCase):
    """Os nomes e a forma vêm do outro lado do contrato, e não deste pacote."""

    RAIZ = Path(__file__).resolve().parents[3]

    def test_os_nomes_sao_os_do_protocolo_do_piloto(self) -> None:
        protocolo = (self.RAIZ / "docs/tecnica/evidencia/validacao/Piloto_Protocolo.md").read_text(encoding="utf-8")
        self.assertIn(f"--saida {entradas.NOME_DO_MANIFESTO}", protocolo)
        self.assertIn(f"--saida {cli.EXPORTACAO_DO_PILOTO}", protocolo)
        self.assertIn("O `sha256` do manifesto entra na coluna `fonte`", protocolo)

    def test_o_manifesto_que_o_congelar_escreve_serve(self) -> None:
        from piloto import exportacao as kam_109

        self.assertEqual(cli.FORMATO_DO_MANIFESTO, kam_109.FORMATO_MANIFESTO)
        with TemporaryDirectory() as d:
            raiz = Path(d)
            ficheiros = []
            for nome in (cli.EXPORTACAO_DO_PILOTO, "h6_export.json"):
                (raiz / nome).write_text('{"sintetico": true}', encoding="utf-8")
                ficheiros.append(raiz / nome)
            manifesto = kam_109.congelar(ficheiros, datetime(2000, 1, 1, tzinfo=timezone.utc))
            bruto = (json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            (raiz / entradas.NOME_DO_MANIFESTO).write_bytes(bruto)
            sha = hashlib.sha256(bruto).hexdigest()
            (raiz / "registo.md").write_text(
                sintetico.registo({"H9": ("8", "6 de 8 (75,0%)", "confirmada", sha)}),
                encoding="utf-8",
            )
            (raiz / "resumo.json").write_text(
                json.dumps(sintetico.resumo(manifesto=entradas.NOME_DO_MANIFESTO, manifesto_sha256=sha)),
                encoding="utf-8",
            )
            codigo, texto, erro = _correr(
                ["--root", str(raiz), "pacote", "--registo", str(raiz / "registo.md"),
                 "--resumo", str(raiz / "resumo.json")]
            )
        self.assertEqual(codigo, cli.SAIDA_CONFORME, erro)
        self.assertIn("| SHA-256 conferido contra o ficheiro | sim |", texto)
        self.assertRegex(texto, r"\| H9 \|.*\| confirmada \| \*\*confirmada\*\* \|")

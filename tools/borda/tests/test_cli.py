"""Os codigos de saida da `borda`: 0 conforme, 1 recusa ou achados, 2 erro."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from borda import cli, rtt
from borda.tests.test_rtt import _da_meta, _serie


def _correr(*argumentos: str) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
        codigo = cli.main(list(argumentos))
    return codigo, saida.getvalue(), erro.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)

    def tearDown(self) -> None:
        self._pasta.cleanup()

    def _amostras(self, nome="a.jsonl", **kw) -> Path:
        """Um ficheiro com as duas series do criterio: sonda -> host e host -> Meta."""
        caminho = self.pasta / nome
        linhas = _serie(**kw) + _da_meta(**kw)
        caminho.write_text("".join(json.dumps(l) + "\n" for l in linhas), encoding="utf-8")
        return caminho

    def test_relatorio_e_verificar(self) -> None:
        amostras = self._amostras()
        relatorio = self.pasta / "RTT.md"
        self.assertEqual(_correr("rtt-relatorio", str(amostras), "--saida", str(relatorio))[0], 0)
        codigo, saida, _ = _correr("rtt-verificar", str(relatorio), str(amostras))
        self.assertEqual(codigo, 0, saida)
        relatorio.write_text(relatorio.read_text().replace("| 1441 |", "| 1440 |"), encoding="utf-8")
        self.assertEqual(_correr("rtt-verificar", str(relatorio), str(amostras))[0], 1)

    def test_relatorio_para_a_saida_padrao(self) -> None:
        codigo, saida, _ = _correr("rtt-relatorio", str(self._amostras()))
        self.assertEqual(codigo, 0)
        self.assertIn(rtt.INICIO_TABELA, saida)

    def test_relatorio_recusado_da_1(self) -> None:
        codigo, _, erro = _correr("rtt-relatorio", str(self._amostras(horas=2)))
        self.assertEqual(codigo, 1)
        self.assertIn("recusado", erro)

    def test_amostras_ilegiveis_dao_2(self) -> None:
        mau = self.pasta / "mau.jsonl"
        mau.write_text("{}\n", encoding="utf-8")
        self.assertEqual(_correr("rtt-relatorio", str(mau))[0], 2)
        self.assertEqual(_correr("rtt-relatorio", str(self.pasta / "nao-existe"))[0], 2)
        self.assertEqual(_correr("rtt-verificar", str(self.pasta / "nao-existe"), str(mau))[0], 2)
        latin = self.pasta / "latin.md"
        latin.write_bytes("relatório".encode("latin-1"))
        self.assertEqual(_correr("rtt-verificar", str(latin), str(self._amostras()))[0], 2)

    def test_medir_valida_e_delega(self) -> None:
        self.assertEqual(_correr("rtt-medir", "--origem", "l", "--alvo", "mau", "--saida", "x")[0], 2)
        self.assertEqual(_correr("rtt-medir", "--origem", "l", "--alvo", "h=h:1", "--saida", "x", "--intervalo", "0")[0], 2)
        with mock.patch.object(rtt, "medir", return_value=4) as medir:
            codigo, saida, _ = _correr("rtt-medir", "--origem", "l", "--alvo", "h=h:443", "--saida", str(self.pasta / "s"))
        self.assertEqual(codigo, 0)
        self.assertIn("4 amostras", saida)
        self.assertEqual(medir.call_args.kwargs["duracao_s"], rtt.JANELA_MINIMA_S)

    def test_firewall_na_arvore_real(self) -> None:
        codigo, saida, _ = _correr("firewall")
        self.assertEqual(codigo, 0)
        self.assertIn("0 achados", saida)

    def test_firewall_sem_modelo_da_2(self) -> None:
        self.assertEqual(_correr("firewall", "--root", str(self.pasta))[0], 2)

    def test_firewall_com_achados_da_1(self) -> None:
        modelo = self.pasta / "infra/modules/host-base/cloud-init.yaml.tftpl"
        modelo.parent.mkdir(parents=True)
        modelo.write_text(
            "write_files:\n  - path: /etc/kamba/firewall.nft\n    content: |\n"
            "      table inet kamba_host {\n        chain input {\n"
            "          type filter hook input priority filter; policy drop;\n"
            "          udp dport ${porta_wireguard} accept\n          tcp dport 22 accept\n        }\n      }\n",
            encoding="utf-8",
        )
        codigo, _, erro = _correr("firewall", "--root", str(self.pasta))
        self.assertEqual(codigo, 1)
        self.assertIn("ssh-fora-do-tunel", erro)


if __name__ == "__main__":
    unittest.main()

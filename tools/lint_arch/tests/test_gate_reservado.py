"""Os gates reservados (5-8) falham por desenho, e o waiver dispensa-os.

O caso que importa e o primeiro: **falham**. Um job reservado que passasse em
silencio fazia o pipeline parecer que cobre o que nao cobre, e nada obrigaria
ninguem a liga-lo.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

from ci_gate_reservado import main

ROOT = Path(__file__).resolve().parents[3]


class TestFalhaPorDesenho(unittest.TestCase):
    def test_sem_waiver_falha(self) -> None:
        for gate, ticket in (("5", "KAM-003"), ("6", "KAM-004"), ("7", "KAM-007"), ("8", "KAM-003")):
            with self.subTest(gate=gate):
                codigo = main(
                    ["--root", str(ROOT), "--gate", gate, "--nome", "x", "--ticket", ticket]
                )
                self.assertEqual(codigo, 1, f"o gate {gate} tem de falhar")


class TestWaiverDispensa(unittest.TestCase):
    def _raiz_com_waiver(self, gate: str, expira: str) -> Path:
        pasta = Path(tempfile.mkdtemp())
        (pasta / "ci").mkdir()
        (pasta / "ci" / "waivers.yaml").write_text(
            "version: 1\n"
            "waivers:\n"
            f"  - gate: {gate}\n"
            "    alvo: pipeline\n"
            "    adr_ou_aprovacao: aprovacao:fundador@2026-10-11\n"
            "    autor: fundador\n"
            "    razao: >-\n"
            "      O ticket que implementa este gate ainda nao foi executado; fica\n"
            "      dispensado e e revisto no fim do prazo.\n"
            f"    expira_em: {expira}\n",
            encoding="utf-8",
        )
        return pasta

    def test_waiver_valido_dispensa(self) -> None:
        amanha = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        raiz = self._raiz_com_waiver("5", amanha)
        codigo = main(["--root", str(raiz), "--gate", "5", "--nome", "x", "--ticket", "KAM-003"])
        self.assertEqual(codigo, 0)

    def test_waiver_de_outro_gate_nao_dispensa(self) -> None:
        amanha = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        raiz = self._raiz_com_waiver("6", amanha)
        codigo = main(["--root", str(raiz), "--gate", "5", "--nome", "x", "--ticket", "KAM-003"])
        self.assertEqual(codigo, 1, "o waiver do gate 6 nao cobre o gate 5")

    def test_waiver_expirado_falha(self) -> None:
        ontem = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        raiz = self._raiz_com_waiver("5", ontem)
        codigo = main(["--root", str(raiz), "--gate", "5", "--nome", "x", "--ticket", "KAM-003"])
        self.assertEqual(codigo, 1, "um waiver expirado nao dispensa nada")


if __name__ == "__main__":
    unittest.main()

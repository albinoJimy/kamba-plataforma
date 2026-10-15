"""`ci/waivers.yaml`: o unico mecanismo de excepcao, e o que ele recusa.

O caso que importa mais e o do waiver **expirado**: falha o pipeline, nao avisa.
A alternativa — avisar e seguir — produz excepcoes que ninguem revisita, porque
nada obriga a isso.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

from ci_waivers import GATES_COM_WAIVER, PRAZO_MAXIMO_DIAS, WaiverInvalido, ler

ROOT = Path(__file__).resolve().parents[3]
HOJE = datetime.date(2026, 10, 11)


def _escrever(corpo: str) -> Path:
    pasta = Path(tempfile.mkdtemp())
    (pasta / "ci").mkdir()
    (pasta / "ci" / "waivers.yaml").write_text(corpo, encoding="utf-8")
    return pasta


BASE = """version: 1
waivers:
  - gate: 11
    alvo: "pkg:npm/exemplo@1.0.0"
    adr_ou_aprovacao: ADR-014
    autor: nome.sobrenome
    razao: >-
      Uma razao suficientemente longa para sobreviver a saida do autor e dizer
      quando rever.
    expira_em: {expira}
"""


class TestFicheiroDoRepositorio(unittest.TestCase):
    def test_le_e_esta_vazio(self) -> None:
        """O estado inicial e sem excepcoes, de proposito.

        Le-se com o dia de **hoje**, e nao com o `HOJE` fixo das *fixtures*: um
        waiver verdadeiro escrito depois desse dia fixo tem prazo que o leitor
        acha longe demais, e o teste ficava vermelho por causa da data do
        codigo e nao do ficheiro.
        """
        self.assertEqual(ler(ROOT, datetime.date.today()), [])

    def test_a_chave_waivers_existe(self) -> None:
        """`waivers: []` diz «nenhuma»; a ausencia da chave e ambigua."""
        texto = (ROOT / "ci" / "waivers.yaml").read_text(encoding="utf-8")
        self.assertIn("waivers: []", texto)


class TestAceita(unittest.TestCase):
    def test_waiver_completo_e_dentro_do_prazo(self) -> None:
        pasta = _escrever(BASE.format(expira="2026-10-20"))
        waivers = ler(pasta, HOJE)
        self.assertEqual(len(waivers), 1)
        self.assertEqual(waivers[0]["gate"], "11")

    def test_aceita_adr_local(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace("ADR-014", "ADR-L001")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_aceita_aprovacao_humana_datada(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace(
            "ADR-014", "aprovacao:fundador@2026-10-10"
        )
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)


class TestRecusa(unittest.TestCase):
    def recusa(self, corpo: str, trecho: str) -> None:
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        self.assertIn(trecho, str(capturado.exception))

    def test_expirado_falha_o_pipeline(self) -> None:
        """O caso central. Nao avisa: falha."""
        self.recusa(BASE.format(expira="2026-10-01"), "expirou")

    def test_expirado_ontem_tambem_falha(self) -> None:
        self.recusa(BASE.format(expira="2026-10-10"), "expirou")

    def test_prazo_longo_demais(self) -> None:
        longe = (HOJE + datetime.timedelta(days=PRAZO_MAXIMO_DIAS + 1)).isoformat()
        self.recusa(BASE.format(expira=longe), f"maximo\ne {PRAZO_MAXIMO_DIAS}".replace("\n", " "))

    def test_sem_data(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace("    expira_em: 2026-10-20\n", "")
        self.recusa(corpo, "expira_em")

    def test_data_malformada(self) -> None:
        self.recusa(BASE.format(expira="20-10-2026"), "data ISO")

    def test_sem_referencia(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace(
            "    adr_ou_aprovacao: ADR-014\n", ""
        )
        self.recusa(corpo, "adr_ou_aprovacao")

    def test_referencia_que_nao_e_adr_nem_aprovacao(self) -> None:
        for mau in ("porque sim", "ADR-21", "aprovacao:alguem", "ticket KAM-002"):
            with self.subTest(referencia=mau):
                corpo = BASE.format(expira="2026-10-20").replace("ADR-014", mau)
                self.recusa(corpo, "adr_ou_aprovacao")

    def test_sem_alvo(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace(
            '    alvo: "pkg:npm/exemplo@1.0.0"\n', ""
        )
        self.recusa(corpo, "alvo")

    def test_razao_curta(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace(
            """    razao: >-
      Uma razao suficientemente longa para sobreviver a saida do autor e dizer
      quando rever.
""",
            "    razao: porque sim\n",
        )
        self.recusa(corpo, "nao sobrevive")

    def test_gate_que_nao_aceita_waiver(self) -> None:
        """Os gates 1 e 2 nao se dispensam.

        Um build que nao compila ou um tipo que nao verifica corrige-se.
        """
        for gate in ("1", "2"):
            with self.subTest(gate=gate):
                corpo = BASE.format(expira="2026-10-20").replace("gate: 11", f"gate: {gate}")
                self.recusa(corpo, "nao aceita waiver")

    def test_sem_a_chave_waivers(self) -> None:
        self.recusa("version: 1\n", "falta a chave")

    def test_versao_errada(self) -> None:
        corpo = BASE.format(expira="2026-10-20").replace("version: 1", "version: 2")
        self.recusa(corpo, "version")

    def test_sem_ficheiro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WaiverInvalido):
                ler(Path(tmp), HOJE)


class TestGatesQueAceitamWaiver(unittest.TestCase):
    def test_os_gates_1_e_2_estao_de_fora(self) -> None:
        self.assertNotIn("1", GATES_COM_WAIVER)
        self.assertNotIn("2", GATES_COM_WAIVER)

    def test_os_gates_em_ambito_do_kam_002_aceitam(self) -> None:
        for gate in ("3", "4", "9", "11"):
            self.assertIn(gate, GATES_COM_WAIVER)

    def test_os_gates_adiados_aceitam(self) -> None:
        """Os 5-8 ficam fail-closed; o waiver e a valvula enquanto nao existirem."""
        for gate in ("5", "6", "7", "8"):
            self.assertIn(gate, GATES_COM_WAIVER)


if __name__ == "__main__":
    unittest.main()

"""As constantes de `regras.py` contra a tabela do §7 do protocolo (KAM-109).

As duas superficies dizem o mesmo, e a divergencia nao da erro em lado nenhum:
so aparece a contar. Este ensaio conta nos dois sentidos — uma constante sem
linha, uma linha sem constante, e um valor diferente.
"""

from __future__ import annotations

import re
import unittest
from fractions import Fraction
from pathlib import Path

from piloto import regras

PROTOCOLO = (
    Path(__file__).resolve().parents[3]
    / "docs" / "tecnica" / "evidencia" / "validacao" / "Piloto_Protocolo.md"
)
_LINHA = re.compile(r"^\| `([A-Z0-9_]+)` \| ([^|]+?) \|")


def _valor(texto: str) -> Fraction:
    texto = texto.strip()
    if texto.endswith("%"):
        return Fraction(int(texto[:-1]), 100)
    return Fraction(int(texto))


def _tabela() -> dict[str, Fraction]:
    texto = PROTOCOLO.read_text(encoding="utf-8")
    seccao = texto.split("## 7. Tabela dos limiares", 1)[1].split("\n## ", 1)[0]
    return {m.group(1): _valor(m.group(2)) for l in seccao.splitlines() if (m := _LINHA.match(l))}


def _constantes() -> dict[str, Fraction]:
    return {
        nome: Fraction(valor)
        for nome, valor in vars(regras).items()
        if re.fullmatch(r"[A-Z][A-Z0-9_]+", nome)
        and isinstance(valor, (int, Fraction))
        and not isinstance(valor, bool)
    }


class TestProtocolo(unittest.TestCase):
    def test_a_tabela_tem_dezoito_linhas(self) -> None:
        self.assertEqual(len(_tabela()), 18)

    def test_as_duas_superficies_dizem_o_mesmo(self) -> None:
        self.assertEqual(_tabela(), _constantes())

    def test_o_leitor_morde(self) -> None:
        # O canario: a tabela lida com um valor mudado deixa de bater.
        tabela = _tabela()
        tabela["H1_ALVO"] = Fraction(4)
        self.assertNotEqual(tabela, _constantes())
        self.assertEqual(_valor("15%"), Fraction(3, 20))


if __name__ == "__main__":
    unittest.main()

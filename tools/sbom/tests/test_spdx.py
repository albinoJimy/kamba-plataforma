"""Avaliacao de expressoes SPDX, e os quatro veredictos.

Os casos vem de `docs/tecnica/evidencia/E4_Stack_Licencas.md`: sao as licencas
que o projecto usa ou planeia usar, nao exemplos inventados.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from sbom.cli import ler_politica
from sbom.spdx import DESCONHECIDA, NEGADA, PENDENTE, PERMITIDA, classificar, classificar_pacote

ROOT = Path(__file__).resolve().parents[3]


class TestTermosSimples(unittest.TestCase):
    def setUp(self) -> None:
        self.politica, _ = ler_politica(ROOT)

    def v(self, expressao: str | None) -> str:
        return classificar(expressao, self.politica)[0]

    def test_permitidas_reais_do_repositorio(self) -> None:
        """As licencas que estao de facto instaladas hoje."""
        for licenca in ("MIT", "ISC", "Apache-2.0", "BSD-3-Clause", "PSF-2.0", "Python-2.0"):
            with self.subTest(licenca=licenca):
                self.assertEqual(self.v(licenca), PERMITIDA)

    def test_bsd_sozinho_nao_e_identificador(self) -> None:
        """`BSD` era a proposta do ticket, e nao e SPDX.

        Deixa-lo passar seria pior do que falhar: aceitaria qualquer coisa que se
        chamasse `BSD` e rejeitaria `BSD-3-Clause`, que e o que os pacotes
        declaram de verdade.
        """
        self.assertEqual(self.v("BSD"), DESCONHECIDA)

    def test_negadas(self) -> None:
        for licenca, _ in (
            ("AGPL-3.0", "MinIO, Garage"),
            ("BUSL-1.1", "Restate, Vault"),
            ("Elastic-2.0", "langgraph-api"),
            ("SSPL-1.0", "—"),
            ("GPL-3.0", "Nominatim"),
            ("FSL-1.1-Apache-2.0", "Typebot"),
        ):
            with self.subTest(licenca=licenca):
                self.assertEqual(self.v(licenca), NEGADA)

    def test_desconhecidas(self) -> None:
        """`NOASSERTION` e o caso do Medusa v2 — o registo de comercio do Piloto."""
        for valor in ("NOASSERTION", "UNKNOWN", "", None, "proprietary", "SEE LICENSE"):
            with self.subTest(valor=valor):
                self.assertEqual(self.v(valor), DESCONHECIDA)

    def test_unlicensed_nao_passa_por_allowlist(self) -> None:
        """Os nossos pacotes resolvem-se por identidade, nao por licenca.

        Se `UNLICENSED` estivesse nas permitidas, qualquer dependencia de
        terceiros que a declarasse passava.
        """
        self.assertEqual(self.v("UNLICENSED"), DESCONHECIDA)


class TestExpressoes(unittest.TestCase):
    def setUp(self) -> None:
        self.politica, _ = ler_politica(ROOT)

    def v(self, expressao: str) -> str:
        return classificar(expressao, self.politica)[0]

    def test_and_a_pior_manda(self) -> None:
        """`MIT AND BUSL-1.1` e o Meilisearch (E4 §2.13).

        Um comparador de cadeias que procurasse `MIT` dentro desta expressao
        aprovava uma licenca que exige acordo comercial para producao.
        """
        self.assertEqual(self.v("MIT AND BUSL-1.1"), NEGADA)
        self.assertEqual(self.v("MIT AND Apache-2.0"), PERMITIDA)

    def test_or_basta_uma(self) -> None:
        self.assertEqual(self.v("MIT OR Apache-2.0"), PERMITIDA)
        self.assertEqual(self.v("AGPL-3.0 OR MIT"), PERMITIDA)
        self.assertEqual(self.v("AGPL-3.0 OR BUSL-1.1"), NEGADA)

    def test_with_avalia_a_licenca(self) -> None:
        self.assertEqual(self.v("Apache-2.0 WITH LLVM-exception"), PERMITIDA)
        self.assertEqual(self.v("GPL-3.0 WITH Classpath-exception-2.0"), NEGADA)

    def test_parenteses(self) -> None:
        self.assertEqual(self.v("(MIT OR Apache-2.0) AND ISC"), PERMITIDA)
        self.assertEqual(self.v("(MIT OR Apache-2.0) AND AGPL-3.0"), NEGADA)

    def test_expressao_ilegivel_e_desconhecida(self) -> None:
        self.assertEqual(self.v("()"), DESCONHECIDA)


class TestPendentesDeDecisao(unittest.TestCase):
    """O terceiro estado, exigido por `specs/EPIC-07` para Redis/Valkey."""

    def setUp(self) -> None:
        self.politica, _ = ler_politica(ROOT)

    def test_redis_e_valkey_estao_travados_pela_d12(self) -> None:
        for nome in ("redis", "valkey", "redis-server", "valkey/valkey"):
            with self.subTest(nome=nome):
                veredicto, razao = classificar_pacote(nome, "BSD-3-Clause", self.politica)
                self.assertEqual(veredicto, PENDENTE)
                self.assertIn("D12", razao)

    def test_a_licenca_permitida_nao_desbloqueia(self) -> None:
        """O Valkey e BSD-3-Clause, que esta na allowlist.

        Aprova-lo por via da licenca fecharia a D12 pela porta de tras: a escolha
        entre Redis e Valkey **e** a decisao.
        """
        self.assertEqual(classificar("BSD-3-Clause", self.politica)[0], PERMITIDA)
        self.assertEqual(
            classificar_pacote("valkey", "BSD-3-Clause", self.politica)[0], PENDENTE
        )

    def test_outro_pacote_nao_e_afectado(self) -> None:
        self.assertEqual(classificar_pacote("hono", "MIT", self.politica)[0], PERMITIDA)


if __name__ == "__main__":
    unittest.main()

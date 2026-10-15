"""A sonda partilhada responde o que o contrato diz."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from kamba_core import COMMIT_ENV, commit_sha, healthz

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "packages" / "contracts" / "schemas" / "healthz.response.v1.json"


class TestCommitSha(unittest.TestCase):
    def test_sha_completo_passa(self) -> None:
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(commit_sha({COMMIT_ENV: sha}), sha)

    def test_sha_curto_passa(self) -> None:
        self.assertEqual(commit_sha({COMMIT_ENV: "abc1234"}), "abc1234")

    def test_maiusculas_normalizam(self) -> None:
        self.assertEqual(commit_sha({COMMIT_ENV: "ABC1234"}), "abc1234")

    def test_ausente_da_unknown(self) -> None:
        self.assertEqual(commit_sha({}), "unknown")

    def test_lixo_da_unknown(self) -> None:
        # Fail-soft deliberado: a sonda de vivacidade nao cai por metadados maus.
        for valor in ("", "   ", "nao-e-um-sha", "zzzz", "123456"):
            with self.subTest(valor=valor):
                self.assertEqual(commit_sha({COMMIT_ENV: valor}), "unknown")


class TestHealthz(unittest.TestCase):
    def test_campos_do_contrato(self) -> None:
        payload = healthz("agr", "1.2.3", {})
        self.assertEqual(
            sorted(payload), ["commit", "service", "status", "version"]
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "agr")
        self.assertEqual(payload["version"], "1.2.3")
        self.assertEqual(payload["commit"], "unknown")

    def test_conforme_ao_esquema_publicado(self) -> None:
        """Os padroes do esquema aceitam o que esta funcao produz.

        Validacao leve, so dos padroes: a validacao completa com `jsonschema`
        esta em `tools/healthz_check.py`, que corre contra o servico a responder.
        """
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        payload = healthz("agr", "0.1.0", {})
        for campo in schema["required"]:
            self.assertIn(campo, payload)
        self.assertRegex(
            payload["version"], schema["properties"]["version"]["pattern"]
        )
        self.assertRegex(
            payload["commit"], re.compile(schema["properties"]["commit"]["pattern"])
        )
        self.assertIn(payload["service"], schema["properties"]["service"]["enum"])


if __name__ == "__main__":
    unittest.main()


class TestHost(unittest.TestCase):
    """O anfitriao por omissao e local; abrir a interface e decisao do contentor."""

    def test_omissao_e_localhost(self) -> None:
        from kamba_core import DEFAULT_HOST, host

        self.assertEqual(DEFAULT_HOST, "127.0.0.1")
        self.assertEqual(host({}), "127.0.0.1")
        self.assertEqual(host({"HOST": "   "}), "127.0.0.1")

    def test_ambiente_tem_precedencia(self) -> None:
        from kamba_core import host

        self.assertEqual(host({"HOST": "0.0.0.0"}), "0.0.0.0")


class TestPort(unittest.TestCase):
    def test_omissao_e_o_fallback(self) -> None:
        from kamba_core import port

        self.assertEqual(port(8000, {}), 8000)
        self.assertEqual(port(8000, {"PORT": ""}), 8000)

    def test_ambiente_tem_precedencia(self) -> None:
        from kamba_core import port

        self.assertEqual(port(8000, {"PORT": "9000"}), 9000)

    def test_valor_invalido_falha_em_voz_alta(self) -> None:
        """Ao contrario do SHA, uma porta errada nao e um metadado."""
        from kamba_core import port

        for valor in ("0", "-1", "65536", "abc", "8000.5", "8e3"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    port(8000, {"PORT": valor})

    def test_a_regra_e_a_mesma_do_lado_typescript(self) -> None:
        """`packages/core-ts/src/index.ts` tem de ter os mesmos limites.

        Se as duas implementacoes divergirem, o mesmo `.env` significa coisas
        diferentes em servicos diferentes.
        """
        fonte = (ROOT / "packages" / "core-ts" / "src" / "index.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("parsed < 1 || parsed > 65535", fonte)

        servidor = (ROOT / "services" / "gwy" / "src" / "server.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn('process.env.HOST', servidor)
        self.assertIn('"127.0.0.1"', servidor)

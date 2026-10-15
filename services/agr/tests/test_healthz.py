"""A sonda do AGR responde 200 com servico, versao e commit.

Conduz a aplicacao ASGI directamente, em vez de usar o `TestClient` do Starlette:
o `TestClient` exige `httpx`, e acrescentar `httpx` ao lock do AGR para testar uma
rota que devolve quatro campos seria pagar uma arvore de dependencias em producao
por conveniencia de teste. O protocolo ASGI e estavel e a chamada directa exercita
o encaminhamento real do Starlette.
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path

from kamba_agr.app import create_app
from kamba_agr.meta import SERVICE, VERSION

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "packages" / "contracts" / "schemas" / "healthz.response.v1.json"


async def _request(app, path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    """Faz um pedido HTTP a uma aplicacao ASGI sem servidor nem cliente HTTP."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    received: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        received.append(message)

    await app(scope, receive, send)

    start = next(m for m in received if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in received if m["type"] == "http.response.body"
    )
    headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], headers, body


def request(path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    return asyncio.run(_request(create_app(), path, method))


class TestHealthz(unittest.TestCase):
    def test_responde_200_com_os_campos_do_contrato(self) -> None:
        status, headers, body = request("/healthz")

        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("content-type", ""))

        payload = json.loads(body)
        self.assertEqual(sorted(payload), ["commit", "service", "status", "version"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], SERVICE)
        self.assertEqual(payload["version"], VERSION)

    def test_conforme_aos_padroes_do_esquema(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        payload = json.loads(request("/healthz")[2])

        self.assertIn(payload["service"], schema["properties"]["service"]["enum"])
        self.assertRegex(
            payload["version"], re.compile(schema["properties"]["version"]["pattern"])
        )
        self.assertRegex(
            payload["commit"], re.compile(schema["properties"]["commit"]["pattern"])
        )

    def test_rota_desconhecida_nao_responde_200(self) -> None:
        for path in ("/", "/healthz/", "/metrics", "/admin"):
            with self.subTest(path=path):
                self.assertNotEqual(request(path)[0], 200)

    def test_healthz_so_aceita_get(self) -> None:
        for method in ("POST", "DELETE", "PUT"):
            with self.subTest(method=method):
                self.assertEqual(request("/healthz", method)[0], 405)


class TestMetadados(unittest.TestCase):
    def test_o_servico_e_o_da_topologia(self) -> None:
        self.assertEqual(SERVICE, "agr")

    def test_a_versao_e_semver(self) -> None:
        self.assertRegex(VERSION, r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")

    def test_a_rota_healthz_esta_registada(self) -> None:
        rotas = {getattr(r, "path", None) for r in create_app().routes}
        self.assertIn("/healthz", rotas)


if __name__ == "__main__":
    unittest.main()

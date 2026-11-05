"""Serve a `/metrics` do AGR num interpretador **acabado de arrancar**.

Imprime `<estado> <octetos-do-corpo>` e mais nada.

## PORQUE E QUE ISTO E UM FICHEIRO, E NAO UM ENSAIO

Porque o `test_um_processo_fresco_serve_corpo_vazio` afirma uma propriedade
de **processo fresco** — e um ensaio dentro de uma suite nao esta num.

O registo de metricas do AGR e **global ao processo**, e o alvo
`ordem-dos-ensaios` (KAM-173) corre a suite nas duas ordens: na inversa, outro
ensaio de `services/agr/tests` ja contou um evento antes do meu, o
`agr_evt_consumidos_total` aparece com dados, e o corpo deixa de estar vazio.
Medido no gate 4:

    AssertionError: b'# HELP agr_evt_consumidos_total ...' != b''

**Isso nao e um falso alarme: e o portao a fazer o que existe para fazer.** A
primeira versao do ensaio assumia a premissa em vez de a controlar, e um ensaio
que assume a sua premissa passa pela ordem em que calhou — que e exactamente o
«passa por acidente» que o KAM-173 fecha.

Este ficheiro controla a premissa: um interpretador novo, sem nada contado, e
uma so chamada. Fica em `tests/` e nao ao lado do codigo porque **nao e um
teste** — e andaime de ensaio, corrido por `subprocess` a partir do
`test_healthz`. E a mesma razao e o mesmo sitio do
`packages/core-ts/tests/x11_conduzir.ts`, que o gate 6 corre e que vive em
`tests/` por nao ser um teste; e e o que mantem o ficheiro fora do universo do
gate 4, que exclui `**/tests/**`.

Nao importa o `api_interna`: o `create_app()` sem argumentos da a `/healthz` e a
`/metrics`, e so isso e preciso. Importar o resto arrastava o `yaml`, o
`pydantic` e o registo das verticais, e fazia este andaime depender de meio AGR
para ler um contador.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
for relativo in ("services/agr/src", "libs/py-core/src"):
    caminho = str(RAIZ / relativo)
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

from kamba_agr.app import create_app  # noqa: E402


async def _pedir(app, caminho: str) -> tuple[int, bytes]:
    """Um GET pelo protocolo ASGI, sem servidor nem cliente HTTP.

    A forma e a do `_request` do `test_healthz`, e esta repetida aqui de
    proposito: este ficheiro corre num interpretador que **nao** importa a suite
    — importa-la para reutilizar o ajudante punha os modulos de teste todos na
    memoria, e com eles o que eles contam ao importar. Seria assumir outra vez a
    premissa que este ficheiro existe para controlar.
    """
    recebidas: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(mensagem: dict) -> None:
        recebidas.append(mensagem)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": caminho,
            "raw_path": caminho.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )

    inicio = next(m for m in recebidas if m["type"] == "http.response.start")
    corpo = b"".join(
        m.get("body", b"") for m in recebidas if m["type"] == "http.response.body"
    )
    return inicio["status"], corpo


def main() -> int:
    estado, corpo = asyncio.run(_pedir(create_app(), "/metrics"))
    print(f"{estado} {len(corpo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

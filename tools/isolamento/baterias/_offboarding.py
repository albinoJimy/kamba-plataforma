"""O ataque a sonda do processo das fases de dados do off-boarding (KAM-218).

O `python -m kamba_core.offboarding` serve uma rota so, a `GET /healthz`, num
`BaseHTTPRequestHandler` da biblioteca padrao (`kamba_core.offboarding.servico`).
Separado do `x01_rotas.py` pela razao do `_idx.py`: o `x01_rotas` tem de ser
importavel a seco, e este modulo importa o `kamba_core.offboarding`. Importa-se
dentro do `fn`.

## Um servidor de verdade, numa porta efemera

O caso levanta o `ThreadingHTTPServer` do proprio `servico.servidor` em
`127.0.0.1:0` e fala com ele por `http.client`, como o do IDX. A sonda nao le
nada do pedido nem da base: o que se afirma e que responde, e que nem com o
tenant e o canario de B no caminho ou nos cabecalhos alguma coisa de B sai na
resposta — um caminho que nao e exactamente `/healthz` da 404, sem eco.
"""

from __future__ import annotations

import http.client
import sys
import threading
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]

ITEM_DA_SONDA = "rota:py-core:kamba_core/offboarding/servico:servidor:GET:/healthz"


def _no_caminho() -> None:
    caminho = str(RAIZ / "libs/py-core/src")
    if caminho not in sys.path:
        sys.path.insert(0, caminho)


def _pedir(porta: int, caminho: str, cabecalhos: dict[str, str]) -> tuple[int, dict[str, str], str]:
    ligacao = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    try:
        ligacao.request("GET", caminho, headers=cabecalhos)
        resposta = ligacao.getresponse()
        texto = resposta.read().decode("utf-8", errors="replace")
        return resposta.status, dict(resposta.getheaders()), texto
    finally:
        ligacao.close()


def atacar_sonda(ctx: Any) -> list[str]:
    """O X-01 da `/healthz` do processo dos dados: responde, e nada de B sai."""
    _no_caminho()
    from kamba_core.offboarding import servico  # noqa: PLC0415

    canario_de_b = next(iter(ctx.oraculo.proibidos.values()))
    b = ctx.b.id
    http_ = servico.servidor(0, {"KAMBA_COMMIT_SHA": "0000000"}, anfitriao="127.0.0.1")
    fio = threading.Thread(target=http_.serve_forever, daemon=True)
    fio.start()
    achados: list[str] = []
    try:
        porta = http_.server_address[1]
        estado, cab, texto = _pedir(porta, "/healthz", {"x-kamba-tenant": b, "x-canario": canario_de_b})
        if estado != 200:
            achados.append(f"{ITEM_DA_SONDA}: respondeu {estado} e nao 200; o caso nao mediu o que queria medir.")
        achados.extend(
            f"{ITEM_DA_SONDA}: {fuga}"
            for fuga in ctx.oraculo.varrer_tudo({"corpo": texto, "cabecalhos": cab, "logs": []})
        )
        # O tenant e o canario de B no caminho: um 404 sem eco de nada.
        estado, cab, texto = _pedir(porta, f"/healthz?tenant={b}&x={canario_de_b}", {})
        if estado != 404:
            achados.append(f"{ITEM_DA_SONDA}: um caminho com a consulta de B respondeu {estado}, e nao 404.")
        achados.extend(
            f"{ITEM_DA_SONDA}: {fuga}"
            for fuga in ctx.oraculo.varrer_tudo({"corpo": texto, "cabecalhos": cab, "logs": []})
        )
    finally:
        http_.shutdown()
        http_.server_close()
    return achados

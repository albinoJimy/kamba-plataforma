"""O ataque as duas rotas do recolector do registo do PostgreSQL (KAM-225).

O `python -m kamba_core.registo_pg` serve duas rotas, `GET /healthz` e
`GET /metrics`, num `BaseHTTPRequestHandler` da biblioteca padrao
(`kamba_core.registo_pg.processo`). Separado do `x01_rotas.py` pela razao do
`_idx.py`: o `x01_rotas` tem de ser importavel a seco, e este modulo importa o
`kamba_core.registo_pg`. Importa-se dentro do `fn`.

## Um servidor de verdade, numa porta efemera

O caso levanta o `ThreadingHTTPServer` do proprio `processo.servidor` em
`127.0.0.1:0` e fala com ele por `http.client`, como o do off-boarding. As rotas
nao leem nada do pedido nem da base: o que se afirma e que respondem, e que nem
com o tenant e o canario de B no caminho ou nos cabecalhos alguma coisa de B sai
na resposta — um caminho que nao e exactamente uma das duas da 404, sem eco.

**Conta antes de ler**, pela razao do `/metrics` do IDX: o registo usado tem uma
recusa contada, para que o corpo tenha a serie com um valor e o oraculo nao
varra o vazio.
"""

from __future__ import annotations

import http.client
import sys
import threading
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]

ITEM_DA_SONDA = "rota:py-core:kamba_core/registo_pg/processo:tratador:GET:/healthz"
ITEM_DAS_METRICAS = "rota:py-core:kamba_core/registo_pg/processo:tratador:GET:/metrics"


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


def atacar_sonda_e_metricas(ctx: Any) -> list[str]:
    """O X-01 da `/healthz` e da `/metrics` do recolector: respondem, e nada de B sai."""
    _no_caminho()
    from kamba_core.registo_pg import processo  # noqa: PLC0415
    from kamba_core.registo_pg.metricas import MetricasDoRegistoPg  # noqa: PLC0415

    canario_de_b = next(iter(ctx.oraculo.proibidos.values()))
    b = ctx.b.id
    metricas = MetricasDoRegistoPg()
    metricas.contar()
    http_ = processo.servidor(0, anfitriao="127.0.0.1", metricas=metricas)
    fio = threading.Thread(target=http_.serve_forever, daemon=True)
    fio.start()
    achados: list[str] = []
    try:
        porta = http_.server_address[1]
        for item, caminho in ((ITEM_DA_SONDA, "/healthz"), (ITEM_DAS_METRICAS, "/metrics")):
            estado, cab, texto = _pedir(porta, caminho, {"x-kamba-tenant": b, "x-canario": canario_de_b})
            if estado != 200:
                achados.append(f"{item}: respondeu {estado} e nao 200; o caso nao mediu o que queria medir.")
            if caminho == "/metrics" and "# TYPE" not in texto:
                achados.append(
                    f"{item}: o corpo nao traz `# TYPE`, logo nao ha series e o oraculo varreria o vazio."
                )
            achados.extend(
                f"{item}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo({"corpo": texto, "cabecalhos": cab, "logs": []})
            )
            # O tenant e o canario de B no caminho: um 404 sem eco de nada.
            estado, cab, texto = _pedir(porta, f"{caminho}?tenant={b}&x={canario_de_b}", {})
            if estado != 404:
                achados.append(f"{item}: um caminho com a consulta de B respondeu {estado}, e nao 404.")
            achados.extend(
                f"{item}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo({"corpo": texto, "cabecalhos": cab, "logs": []})
            )
    finally:
        http_.shutdown()
        http_.server_close()
    return achados

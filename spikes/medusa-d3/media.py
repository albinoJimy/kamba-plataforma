"""ISO-47..50 — corre `media_iso.mjs` no contentor Node e le o que ele mediu.

O guiao e Node porque a porta de armazenamento e TypeScript (KAM-011) e esta
ja compilada em `packages/core-ts/dist`. Correr contra a porta de producao em
vez de contra um esboco em Python e a diferenca entre medir o isolamento de
media e medir o meu proprio teste.
"""

from __future__ import annotations

import json
from pathlib import Path

import contentor
from iso import Caso, NAO_VERIFICADO

AQUI = Path(__file__).resolve().parent
GUIAO = AQUI / "media_iso.mjs"


def correr(tenants: dict, cenarios: list[tuple[str, str]]) -> list[Caso]:
    saida = AQUI / "resultados"
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / "media-iso.json"
    if destino.exists():
        destino.unlink()

    resultado = contentor.correr_node(
        GUIAO,
        saida,
        variaveis={
            "KAMBA_SPIKE_TENANT_A": tenants["A"].tenant_id,
            "KAMBA_SPIKE_TENANT_B": tenants["B"].tenant_id,
            "KAMBA_SPIKE_SAIDA": "/saida/media-iso.json",
        },
    )
    if not destino.exists():
        razao = (
            f"o guiao Node nao escreveu resultados (codigo {resultado.returncode}). "
            f"stderr: {resultado.stderr.strip()[-500:]}"
        )
        return [
            Caso(identificador, "Media e URLs", cenario, "recusada",
                 NAO_VERIFICADO, "nao medido", razao)
            for identificador, cenario in cenarios
        ]

    medidos = {
        registo["id"]: registo
        for registo in json.loads(destino.read_text(encoding="utf-8"))
    }
    casos: list[Caso] = []
    for identificador, cenario in cenarios:
        registo = medidos.get(identificador)
        if registo is None:
            casos.append(Caso(identificador, "Media e URLs", cenario, "recusada",
                              NAO_VERIFICADO, "nao medido",
                              "o guiao correu mas nao reportou este caso"))
            continue
        casos.append(Caso(
            identificador, registo["superficie"], registo["cenario"],
            registo["esperado"], registo["estado"], registo["observado"],
            registo["evidencia"],
        ))
    # O guiao mede uma sonda extra (`ISO-48b`: A a assinar uma URL para a
    # referencia de B). Nao e uma linha da matriz do §4.4 e **nao conta** para
    # os 60 casos do AC-1 — vai para o relatorio como sonda adicional, porque
    # inflacionar a contagem com casos que a matriz nao nomeia era a forma mais
    # barata de chegar a «>= 60».
    extra = medidos.get("ISO-48b")
    if extra is not None:
        casos.append(Caso(
            "ISO-48b (sonda extra, fora da contagem)", extra["superficie"],
            extra["cenario"], extra["esperado"], extra["estado"],
            extra["observado"], extra["evidencia"],
        ))
    return casos

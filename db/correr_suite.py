"""Corre a suite do gate 8 e falha se algum teste for saltado.

    python correr_suite.py <tests|tests_identidade|tests_isolamento|tests_eventos
                            |tests_eventos_consumo|tests_eventos_carga
                            |tests_auditoria_carga|tests_ten
                            |tests_entrada
                            |tests_entrada_carga
                            |tests_chr>

O `python -m unittest` sai com 0 quando todos os testes sao **saltados**. E o
trinco da suite (`tests/base.py`) levanta `SkipTest` quando a base nao se chama
`*_gate8` — o comportamento certo para quem corre os testes a mao contra a base
errada, e o comportamento errado para um gate: uma variavel de ambiente mal
posta fazia o gate 8 passar verde sem ter aplicado uma unica migracao.

Num gate, saltar e falhar. Este corredor aplica isso: sai com 1 se houver
falhas, erros, **qualquer** teste saltado, ou zero testes descobertos.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

DB = Path(__file__).resolve().parent


def main() -> int:
    sys.path.insert(0, str(DB))
    directorio = sys.argv[1] if len(sys.argv) > 1 else "tests"
    if directorio not in (
        "tests",
        "tests_identidade",
        "tests_isolamento",
        "tests_eventos",
        "tests_eventos_consumo",
        "tests_eventos_carga",
        "tests_auditoria_carga",
        "tests_ten",
        "tests_entrada",
        "tests_entrada_carga",
        "tests_chr",
        # KAM-015: a saida de canal.
        "tests_outbound",
        # KAM-019: a passagem a humano.
        "tests_handoff",
        # KAM-020: a midia recebida.
        "tests_media",
    ):
        print(f"suite desconhecida: {directorio!r}", file=sys.stderr)
        return 2
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(DB / directorio), top_level_dir=str(DB)
    )
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)

    if resultado.testsRun == 0:
        print("gate de BD: nenhum teste foi descoberto.", file=sys.stderr)
        return 1
    if resultado.skipped:
        print(
            f"gate de BD: {len(resultado.skipped)} teste(s) saltado(s). Num gate, "
            "saltar e falhar:",
            file=sys.stderr,
        )
        for teste, razao in resultado.skipped[:5]:
            print(f"  - {teste}: {razao}", file=sys.stderr)
        return 1
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

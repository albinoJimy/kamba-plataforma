"""O ensaio de carga do KAM-084: um instrumento de medicao, corrido a mao, fora do CI.

    python db/carga.py                                  # os cinco cenarios
    KAMBA_CARGA_CENARIOS=rajada python db/carga.py      # so a rajada
    KAMBA_CARGA_RELATORIO=<caminho.json> python db/carga.py

**Porque e um ponto de entrada proprio, e nao uma suite do `gate_bd.py`.** O
`SUITES` do `gate_bd.py` e a lista do que o CI corre, e o
`test_toda_a_suite_de_base_de_dados_e_invocada_por_um_gate` exige que cada nome
dela esteja num alvo do `Makefile`. O ensaio de carga nao e um portao: e meia hora
de relogio e uma medicao de dimensionamento, e po-lo num gate e decisao do
fundador. A primeira versao registou-o no `SUITES` e deixou-o fora do `ci-8`, e o
*gate* 8 do proprio PR ficou vermelho por isso.

Reutiliza do `gate_bd.py` o arranque e a limpeza do PostgreSQL 18.6 e do Valkey
(`com_contentor`, com a fila ligada) e corre a *suite* `db/tests_dimensionamento/`
com as regras de um gate: **um teste saltado e uma falha**, e zero testes
descobertos tambem. Escolher cenarios com `KAMBA_CARGA_CENARIOS` salta os
outros, e o codigo de saida e 1 — uma corrida parcial nao e uma corrida completa.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import unittest
from pathlib import Path

DB = Path(__file__).resolve().parent
sys.path.insert(0, str(DB))

import gate_bd  # noqa: E402

#: A pasta da *suite*.
SUITE = "tests_dimensionamento"
#: Os cinco cenarios levam de 21 a 35 min com a drenagem. Tempo do **criterio**
#: (300 s por cenario, a rajada de uma hora a 20x) e da espera de arranque da
#: *suite* (600 s), e nao folga.
TEMPO_MAXIMO = 3600


def _correr(ambiente: dict[str, str], suite: str) -> int:
    """Corre a *suite* noutro processo, com o ambiente que o `gate_bd` montou."""
    try:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--dentro", suite],
            cwd=DB,
            env=ambiente,
            timeout=TEMPO_MAXIMO,
        ).returncode
    except subprocess.TimeoutExpired:
        print(f"ensaio de carga: nao terminou em {TEMPO_MAXIMO}s", file=sys.stderr)
        return 1


def _dentro(suite: str) -> int:
    """A *suite*, com saltar = falhar, como o `correr_suite.py` faz para os gates."""
    descoberta = unittest.defaultTestLoader.discover(
        start_dir=str(DB / suite), top_level_dir=str(DB)
    )
    resultado = unittest.TextTestRunner(verbosity=2).run(descoberta)
    if resultado.testsRun == 0:
        print("ensaio de carga: nenhum teste foi descoberto.", file=sys.stderr)
        return 1
    if resultado.skipped:
        print(
            f"ensaio de carga: {len(resultado.skipped)} teste(s) saltado(s); "
            "uma corrida parcial nao e uma corrida completa.",
            file=sys.stderr,
        )
        return 1
    return 0 if resultado.wasSuccessful() else 1


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--dentro":
        return _dentro(argv[1])
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, gate_bd._sair_com_limpeza)
    return gate_bd.com_contentor(SUITE, com_fila=True, correr=_correr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

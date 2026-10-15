"""Positiva: sair com um codigo inteiro nao escreve nada."""

import sys


def principal() -> int:
    return 0


def arrancar(codigo: int) -> None:
    if codigo:
        sys.exit(2)
    raise SystemExit(principal())

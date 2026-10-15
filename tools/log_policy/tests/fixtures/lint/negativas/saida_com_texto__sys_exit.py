"""Negativa: o interpretador escreve o argumento de `sys.exit` no stderr."""

import sys


def arrancar(porta):
    sys.exit(f"PORT invalida: {porta}")

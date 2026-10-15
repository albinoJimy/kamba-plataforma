"""Negativa: a pilha traz a mensagem da excepcao."""

import traceback


def tratar():
    try:
        raise ValueError("x")
    except ValueError:
        traceback.format_exc()

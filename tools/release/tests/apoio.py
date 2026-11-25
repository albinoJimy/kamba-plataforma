"""Apoio comum aos ensaios do `release`."""

from __future__ import annotations

from pathlib import Path

from release.lock import Entrada, Lock

RAIZ = Path(__file__).resolve().parents[3]
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def digest(letra: str) -> str:
    # Letras e nao algarismos: um hexadecimal so de algarismos pode casar as
    # guardas de telefone do repositorio.
    return "sha256:" + letra * 64


def lock_com(**servicos: tuple[str, str]) -> Lock:
    """`lock_com(gwy=("a", "build"))` -> um lock com `registo/gwy@sha256:aaa…`."""
    return Lock(
        COMMIT,
        {nome: Entrada(f"registo.exemplo/{nome}@{digest(letra)}", origem)
         for nome, (letra, origem) in servicos.items()},
    )

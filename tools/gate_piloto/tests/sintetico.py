"""Entradas **sintéticas** para os ensaios. Nada aqui é medição.

O Registo sintético tem o cabeçalho e o esquema do real, com a marca no título,
e cada linha diz-se por um tuplo `(amostra, resultado, estado, fonte)`. Os
valores são inventados para exercitar as regras; os caminhos de evidência
apontam para ficheiros que **não** existem, de propósito, salvo onde um ensaio
os cria.
"""

from __future__ import annotations

from gate_piloto.registo import HIPOTESES

CABECALHO = (
    "| H | enunciado | limiar | método | amostra n | resultado | estado | fonte "
    "| decisão | pivô aplicável (`14` §6) | dono | data |"
)

#: Uma linha com dados completos, que mantém o estado declarado.
COM_DADOS = ("600", "12", "confirmada", "sintetico/evidencia.md")


def registo(linhas: dict[str, tuple[str, str, str, str]] | None = None) -> str:
    linhas = linhas or {}
    corpo = [
        "# Registo de Hipóteses — SINTÉTICO, só para ensaio",
        "",
        CABECALHO,
        "|" + "---|" * 12,
    ]
    for h in HIPOTESES:
        amostra, resultado, estado, fonte = linhas.get(h, ("", "", "", ""))
        corpo.append(
            f"| {h} | enunciado sintético | limiar sintético | método | {amostra} "
            f"| {resultado} | {estado} | {fonte} | | | | |"
        )
    corpo.append("")
    return "\n".join(corpo)


def resumo(**campos: object) -> dict:
    base: dict = {"forma": 1, "sintetico": True}
    base.update(campos)
    return base

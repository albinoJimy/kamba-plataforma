"""Interface de linha de comandos do `env_lint` (KAM-075, gate 2).

    python -m env_lint lint     [--root .]   a matriz bate com a configuracao
    python -m env_lint canario  [--root .]   prova que o lint morde

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.

A distincao entre 1 e 2 importa aqui como no `canon_lint`: uma matriz que nao se
le nao pode parecer uma matriz conforme.

**Entra no gate 2 e nao abre *job* novo.** E a forma que este repositorio usa
para um portao novo — o `log-lint` entrou no gate 2, o `money-lint` tambem e o
X-11 no gate 6 — porque um *job* novo acrescenta um contexto exigido ao
*ruleset* de `main`, e isso e alteracao de regra de bloqueio, que precisa do
fundador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import canario, lint

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _comando_lint(argumentos) -> int:
    try:
        achados, numeros = lint.varrer(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"env_lint: {erro}", file=sys.stderr)
        return 2
    # Imprime **quanto** leu, sempre. Sem isto, um verde sobre zero ambientes
    # le-se como «esta tudo bem» — e o `canon_lint` e o `money_lint` pagam esta
    # linha pela mesma razao.
    print(
        f"env_lint: {numeros['ambientes']} ambientes, {numeros['linhas']} linhas de matriz, "
        f"{numeros['segredos']} segredos do inventario, {numeros['ficheiros']} ficheiros de "
        f"infra/, {numeros['regras']} regras"
    )
    if not achados:
        print("env_lint: 0 achados")
        return 0
    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"env_lint: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(f"env_lint: e mais {len(achados) - MAXIMO_IMPRESSO} achados", file=sys.stderr)
    print(f"env_lint: {len(achados)} achados", file=sys.stderr)
    return 1


def _comando_canario(argumentos) -> int:
    try:
        falhas, numeros = canario.correr(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"env_lint canario: {erro}", file=sys.stderr)
        return 2
    for falha in falhas:
        print(f"env_lint canario: {falha}", file=sys.stderr)
    print(
        f"env_lint canario: {numeros['cobertos']} de {numeros['casos']} casos a morder, "
        f"sobre {numeros['regras']} regras"
    )
    if numeros["casos"] == 0:
        print(
            "env_lint canario: zero casos — um canario vazio passa sempre",
            file=sys.stderr,
        )
        return 2
    return 1 if falhas else 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="env_lint", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("lint")
    sub.add_parser("canario")

    argumentos = analisador.parse_args(argv)
    if argumentos.comando == "lint":
        return _comando_lint(argumentos)
    return _comando_canario(argumentos)

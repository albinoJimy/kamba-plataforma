"""Interface de linha de comandos do `money_lint` (KAM-052, gate 2).

    python -m money_lint lint     [--root .]   nenhum montante por float
    python -m money_lint canario  [--root .]   prova que o lint morde
    python -m money_lint ficheiro <caminho>    um ficheiro, para depurar

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.

A distincao entre 1 e 2 importa aqui como no `canon_lint`: um modulo que mudou de
sitio nao pode parecer um modulo limpo.

**Entra no gate 2 e nao abre *job* novo.** E a forma que este repositorio usa
para um portao novo — o `log-lint` entrou no gate 2 e o X-11 no gate 6 — porque
um *job* novo acrescenta um contexto exigido ao *ruleset* de `main`, e isso e
alteracao de regra de bloqueio, que precisa do fundador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import lint

PASTA_DO_CANARIO = "tools/money_lint/tests/fixtures"

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _comando_lint(argumentos) -> int:
    raiz = _raiz(argumentos)
    try:
        achados, lidos = lint.varrer(raiz)
    except lint.ConfiguracaoInvalida as erro:
        print(f"money_lint: {erro}", file=sys.stderr)
        return 2
    # Imprime **quanto** leu, sempre. Sem isto, um verde sobre zero ficheiros
    # le-se como «esta tudo bem» — e o `canon_lint` paga esta linha pela mesma
    # razao.
    print(f"money_lint: {lidos} ficheiros varridos em {', '.join(lint.RAIZES)}")
    if not achados:
        print("money_lint: 0 achados")
        return 0
    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"money_lint: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(
            f"money_lint: e mais {len(achados) - MAXIMO_IMPRESSO} achados",
            file=sys.stderr,
        )
    print(f"money_lint: {len(achados)} achados", file=sys.stderr)
    return 1


def _comando_canario(argumentos) -> int:
    raiz = _raiz(argumentos)
    falhas, numeros = lint.canario(raiz / PASTA_DO_CANARIO)
    for falha in falhas:
        print(f"money_lint canario: {falha}", file=sys.stderr)
    print(
        f"money_lint canario: {numeros['negativas']} negativas e "
        f"{numeros['positivas']} positivas"
    )
    if numeros["negativas"] == 0:
        print(
            "money_lint canario: zero negativas — a pasta de fixtures nao esta "
            "la, e um canario vazio passa sempre",
            file=sys.stderr,
        )
        return 2
    return 1 if falhas else 0


def _comando_ficheiro(argumentos) -> int:
    caminho = Path(argumentos.caminho)
    try:
        fonte = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as erro:
        print(f"money_lint: nao se le {caminho} ({type(erro).__name__})", file=sys.stderr)
        return 2
    achados = lint.varrer_texto(fonte, caminho.name)
    for achado in achados:
        print(f"money_lint: {achado}", file=sys.stderr)
    print(f"money_lint: {len(achados)} achados em {caminho.name}")
    return 1 if achados else 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="money_lint", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("lint")
    sub.add_parser("canario")
    um = sub.add_parser("ficheiro")
    um.add_argument("caminho")

    argumentos = analisador.parse_args(argv)
    if argumentos.comando == "lint":
        return _comando_lint(argumentos)
    if argumentos.comando == "canario":
        return _comando_canario(argumentos)
    return _comando_ficheiro(argumentos)

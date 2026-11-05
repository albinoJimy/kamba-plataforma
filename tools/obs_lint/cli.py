"""Interface de linha de comandos do `obs_lint` (KAM-080).

    python -m obs_lint lint     [--root .]   cardinalidade e runbooks
    python -m obs_lint canario  [--root .]   prova que o lint morde

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.

A distincao entre 1 e 2 e a do `canon_lint` e do `env_lint`: **um catalogo que
nao se le nao pode parecer um catalogo conforme.**

## NAO ESTA LIGADO A NENHUM PORTAO, E ISSO E DELIBERADO

O criterio 3 do KAM-080 escreve «o CI falha». **Este ticket entrega o *lint* e a
medicao de que ele morde, e para aqui.**

Ligar uma verificacao que trava fusoes e **alteracao de regra de bloqueio**, e
isso e decisao do fundador — nao de quem escreve o ticket. Vale pelos dois
caminhos possiveis, e e preciso dize-lo porque o segundo parece inofensivo:

1. um *job* novo no `.github/workflows/ci.yaml` acrescenta um **contexto
   exigido** ao *ruleset* da `main` (e teria de entrar no `esperados=11`
   escrito a mao da porta final);
2. entrar num alvo `ci-*` que ja existe — o caminho que o `log-lint` e o
   `money-lint` usaram — **nao** cria contexto novo, mas muda o **critério** de
   um portao que ja bloqueia: a partir desse momento o gate 2 reprova arvores
   que antes aprovava. E a mesma fronteira, por outra porta.

Quem quiser liga-lo escreve **uma linha** no `Makefile`, no alvo `ci-2`, ao lado
do `log-lint`:

    @$(MAKE) obs-lint

O alvo `obs-lint` ja existe e corre os dois comandos. Nada mais e preciso.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import canario as canario_mod
from . import lint

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40

#: A pasta das fixtures do canario.
PASTA_DO_CANARIO = "tools/obs_lint/tests/fixtures/canario"


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _comando_lint(argumentos) -> int:
    try:
        achados, numeros = lint.verificar(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"obs_lint: {erro}", file=sys.stderr)
        return 2
    # Imprime **quanto** leu, sempre. Sem isto, um verde sobre zero regras
    # le-se como «esta tudo bem», e e a linha que o `canon_lint`, o `env_lint` e
    # o `money_lint` pagam pela mesma razao.
    print(
        f"obs_lint: {numeros['metricas']} metricas no catalogo, "
        f"{numeros['etiquetas']} etiquetas, "
        f"{numeros['regras']} regras em {numeros['ficheiros_de_regras']} ficheiro(s), "
        f"{numeros['alertas']} alertas, "
        f"{numeros['consultas_de_painel']} consultas em {numeros['paineis']} painel(eis)"
    )
    if not achados:
        print("obs_lint: 0 achados")
        return 0
    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"obs_lint: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(f"obs_lint: e mais {len(achados) - MAXIMO_IMPRESSO} achados", file=sys.stderr)
    print(f"obs_lint: {len(achados)} achados", file=sys.stderr)
    return 1


def _comando_canario(argumentos) -> int:
    pasta = _raiz(argumentos) / PASTA_DO_CANARIO
    try:
        falhas, numeros = canario_mod.canario(pasta)
    except lint.ConfiguracaoInvalida as erro:
        print(f"obs_lint: {erro}", file=sys.stderr)
        return 2
    print(
        f"obs_lint canario: {numeros['negativas']} negativas, "
        f"{numeros['positivas']} positivas"
    )
    if not falhas:
        print("obs_lint canario: todas mordem, e as positivas passam")
        return 0
    for falha in falhas:
        print(f"obs_lint canario: {falha}", file=sys.stderr)
    print(f"obs_lint canario: {len(falhas)} falha(s)", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="obs_lint", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("lint", help="cardinalidade e runbooks")
    sub.add_parser("canario", help="prova que o lint morde")
    argumentos = analisador.parse_args(argv)
    if argumentos.comando == "lint":
        return _comando_lint(argumentos)
    return _comando_canario(argumentos)

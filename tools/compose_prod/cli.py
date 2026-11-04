"""Interface de linha de comandos do `compose_prod` (KAM-076, gate 2).

    python -m compose_prod lint       [--root .]   o contrato do compose de producao
    python -m compose_prod canario    [--root .]   prova que o lint morde
    python -m compose_prod gerar      [--root .]   gera a configuracao do proxy de saida
    python -m compose_prod egress-dez [--root .]   os dez destinos, com Docker

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.

A distincao entre 1 e 2 importa aqui como no `canon_lint` e no `env_lint`: um
manifesto que nao se le nao pode parecer um compose conforme.

**ENTRA NO GATE 2 E NAO ABRE *JOB* NOVO.** E a forma que este repositorio usa
para um portao novo — o `log-lint` entrou no gate 2, o `money-lint` tambem, o
`env-lint` do KAM-075 tambem, e o X-11 entrou no gate 6 — porque um *job* novo
acrescenta um contexto exigido ao *ruleset* de `main`, e isso e alteracao de
regra de bloqueio, que precisa do fundador. O `egress-dez` precisa de Docker e
entra no gate 6, ao lado das suites que ja levantam contentores.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import canario, egress_dez, envoy, lint

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _comando_lint(argumentos) -> int:
    try:
        achados, numeros = lint.varrer(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"compose_prod: {erro}", file=sys.stderr)
        return 2
    # Imprime **quanto** leu, sempre, e com os pendentes em voz alta: um verde
    # sobre um conjunto a que falta metade dos servicos nao e o mesmo verde.
    print(
        f"compose_prod: {numeros['servicos']} servicos no compose de producao, "
        f"{numeros['presentes']} presentes e {numeros['pendentes']} PENDENTES no "
        f"manifesto, {numeros['proibidos']} nomes proibidos, "
        f"{numeros['destinos']} destinos na allowlist, {numeros['regras']} regras"
    )
    if not achados:
        print("compose_prod: 0 achados")
        return 0
    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"compose_prod: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(f"compose_prod: e mais {len(achados) - MAXIMO_IMPRESSO} achados", file=sys.stderr)
    print(f"compose_prod: {len(achados)} achados", file=sys.stderr)
    return 1


def _comando_canario(argumentos) -> int:
    try:
        falhas, numeros = canario.correr(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"compose_prod canario: {erro}", file=sys.stderr)
        return 2
    for falha in falhas:
        print(f"compose_prod canario: {falha}", file=sys.stderr)
    # O segundo numero e **medido** e nao `len(REGRAS)`: quantas regras um caso
    # de canario de facto exercita. A primeira versao do canario do gate 3b
    # dava verde com a lista de casos vazia (`docs/ci.md` §3).
    print(
        f"compose_prod canario: {numeros['cobertos']} de {numeros['casos']} casos a "
        f"morder, a exercitar {numeros['regras_exercitadas']} de {numeros['regras']} regras"
    )
    if numeros["casos"] == 0:
        print(
            "compose_prod canario: zero casos — um canario vazio passa sempre",
            file=sys.stderr,
        )
        return 2
    return 1 if falhas else 0


def _comando_gerar(argumentos) -> int:
    raiz = _raiz(argumentos)
    try:
        mudou, caminho = envoy.gerar(raiz, escrever=not argumentos.verificar)
    except lint.ConfiguracaoInvalida as erro:
        print(f"compose_prod gerar: {erro}", file=sys.stderr)
        return 2
    if argumentos.verificar:
        if mudou:
            print(
                f"compose_prod gerar: {caminho} esta desactualizado face a "
                f"{lint.ALLOWLIST}. Corra `python -m compose_prod gerar`.",
                file=sys.stderr,
            )
            return 1
        print(f"compose_prod gerar: {caminho} esta em dia")
        return 0
    print(f"compose_prod gerar: {caminho} {'reescrito' if mudou else 'sem alteracoes'}")
    return 0


def _comando_egress_dez(argumentos) -> int:
    try:
        return egress_dez.correr(_raiz(argumentos), manter=argumentos.manter)
    except lint.ConfiguracaoInvalida as erro:
        print(f"compose_prod egress-dez: {erro}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="compose_prod", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("lint")
    sub.add_parser("canario")
    gerar = sub.add_parser("gerar")
    gerar.add_argument(
        "--verificar",
        action="store_true",
        help="nao escreve; falha se o ficheiro gerado estiver desactualizado",
    )
    dez = sub.add_parser("egress-dez")
    dez.add_argument(
        "--manter",
        action="store_true",
        help="nao derruba a pilha no fim (para inspeccionar os logs do proxy)",
    )

    argumentos = analisador.parse_args(argv)
    if argumentos.comando == "lint":
        return _comando_lint(argumentos)
    if argumentos.comando == "canario":
        return _comando_canario(argumentos)
    if argumentos.comando == "gerar":
        return _comando_gerar(argumentos)
    return _comando_egress_dez(argumentos)

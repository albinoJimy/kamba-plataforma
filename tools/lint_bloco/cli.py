"""Linha de comandos do `lint_bloco`.

    python -m lint_bloco --root . check     as duas superficies de cada bloco
    python -m lint_bloco --root . canario   prova que a regra morde

Codigos de saida, iguais aos do `obs_lint` e do `canon_lint`:

    0   conforme
    1   ha achados
    2   **nao se conseguiu verificar** — e nunca se le como verde
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import kamba_yaml

from lint_bloco import canario, lint, modelo

#: As dispensas: blocos que ja divergiam antes deste *lint* existir.
DISPENSAS = "ci/bloco-allow.yaml"


def _dispensas(raiz: Path) -> frozenset[str]:
    """Os `KAM-NNN` dispensados, do ficheiro declarado.

    A **ausencia** do ficheiro nao e defeito: um repositorio sem divergencias
    herdadas nao precisa dele. O que e defeito e uma entrada sem razao ou sem
    credor, e isso recusa-se aqui — uma dispensa sem credor e trabalho que
    ninguem reclama, e era a forma de este ficheiro virar gaveta.
    """
    caminho = raiz / DISPENSAS
    if not caminho.is_file():
        return frozenset()
    dados = kamba_yaml.load_file(caminho)
    nomes: list[str] = []
    for entrada in dados.get("dispensas") or []:
        for campo in ("bloco", "razao", "credor"):
            if not str(entrada.get(campo, "")).strip():
                raise lint.ConfiguracaoInvalida(
                    f"{DISPENSAS}: uma dispensa sem `{campo}`. Cada uma leva o "
                    "bloco, a razao e um credor que sobreviva a fusao — um "
                    "`KAM-NNN`, o fundador, ou um nome de papel")
        nomes.append(str(entrada["bloco"]).strip())
    return frozenset(nomes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lint_bloco")
    parser.add_argument("--root", default=".", help="a raiz do repositorio")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("check", help="compara as duas superficies de cada bloco")
    sub.add_parser("canario", help="prova que a regra morde")
    args = parser.parse_args(argv)

    raiz = Path(args.root).resolve()
    if args.comando == "canario":
        return canario.correr()

    try:
        dispensas = _dispensas(raiz)
        achados, nao_medidos, numeros = lint.verificar(raiz, dispensas)
    # **O `BlocoIlegivel` entra aqui, e faltava.** Um ensaio apanhou-o: sobre uma
    # arvore sem `specs/tickets/` o CLI **levantava** em vez de sair com 2, e um
    # *traceback* num alvo do `make` le-se como avaria da ferramenta e nao como
    # «nao se conseguiu verificar». Os dois codigos existem para serem lidos.
    except (lint.ConfiguracaoInvalida, modelo.BlocoIlegivel, OSError) as excepcao:
        print(f"lint_bloco: nao se conseguiu verificar — {excepcao}",
              file=sys.stderr)
        return 2

    for achado in achados:
        print(f"lint_bloco: {achado}", file=sys.stderr)

    # **A cobertura vai na saida, e nao so os achados.** «0 achados» sobre 3
    # blocos medidos de 182 le-se como «esta tudo bem» e nao e: e «olhei para
    # tres». Os nao medidos agrupam-se pela razao, porque sao 139 e listar cada
    # um afogava os achados — que e o contrario do que um lint deve fazer.
    razoes: dict[str, int] = {}
    for item in nao_medidos:
        chave = item.categoria
        razoes[chave] = razoes.get(chave, 0) + 1

    print(f"lint_bloco: {numeros['blocos']} bloco(s), "
          f"{numeros['medidos']} emparelhado(s), "
          f"{numeros['achados']} achado(s), "
          f"{numeros['nao_medidos']} nao medido(s), "
          f"{numeros['tabelas_sem_assunto']} tabela(s) sem assunto, "
          f"{numeros['dispensas']} dispensa(s)")
    for razao, quantas in sorted(razoes.items(), key=lambda x: -x[1]):
        print(f"lint_bloco:   nao medido ({quantas}): {razao}")

    return 1 if achados else 0

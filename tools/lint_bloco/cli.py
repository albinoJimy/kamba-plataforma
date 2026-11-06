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

from kamba_yaml import exigir_chaves, load_file

from lint_bloco import canario, lint, modelo

#: As dispensas: blocos que ja divergiam antes deste *lint* existir.
DISPENSAS = "ci/bloco-allow.yaml"

#: As chaves de topo que este leitor conhece.
#:
#: **O `version` esta aqui porque esta no ficheiro e ninguem o le.** Sem o
#: declarar, o `exigir_chaves` recusava uma chave que toda a gente considera
#: legitima e o portao ficava vermelho por ela — a armadilha que o
#: `tools/lint_handoff/cli.py` ja registou em tres leitores desta casa.
_CHAVES = {"version", "dispensas"}

#: E as de cada entrada, que e o nivel de baixo. **Um conjunto por nivel**, como
#: o `lint_handoff`: sem este, uma chave mal escrita numa entrada (`credorr`)
#: passava por chave nova e a dispensa ficava sem o campo que ela exige.
_CHAVES_DA_DISPENSA = {"bloco", "divergencias", "onde", "razao", "credor"}


def ler_dispensas(raiz: Path) -> frozenset[str]:
    """Os `KAM-NNN` dispensados, do ficheiro declarado.

    **Publico e com o nome da convencao** (`ler_*`), como o `ler_excepcoes` do
    `lint_handoff` e o `ler_declaracoes` do `lint_backlog`: o
    `test_todos_os_ficheiros_de_ci_sao_lidos_por_alguem` do `lint_arch` chama o
    leitor de cada `ci/*.yaml` sobre o ficheiro real, e um leitor que ele nao
    saiba chamar nao esta ligado ao mecanismo.

    A **ausencia** do ficheiro nao e defeito: um repositorio sem divergencias
    herdadas nao precisa dele. O que e defeito e uma chave que este leitor nao
    conhece — em qualquer dos dois niveis — ou uma entrada sem razao ou sem
    credor: uma dispensa sem credor e trabalho que ninguem reclama, e era a
    forma de este ficheiro virar gaveta.
    """
    caminho = raiz / DISPENSAS
    if not caminho.is_file():
        return frozenset()
    dados = load_file(caminho)
    exigir_chaves(dados, _CHAVES, DISPENSAS, erro=lint.ConfiguracaoInvalida)
    nomes: list[str] = []
    for entrada in dados.get("dispensas") or []:
        exigir_chaves(entrada, _CHAVES_DA_DISPENSA, f"{DISPENSAS}: dispensas",
                      erro=lint.ConfiguracaoInvalida)
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
        dispensas = ler_dispensas(raiz)
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

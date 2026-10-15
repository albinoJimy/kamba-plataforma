"""Interface de linha de comando do `scan_secrets` (gate 9).

    python -m scan_secrets tree    [--root .]   arvore seguida pelo git (gate 9)
    python -m scan_secrets staged  [--root .]   o que esta em stage (pre-commit)
    python -m scan_secrets files <ficheiros>    ficheiros nomeados
    python -m scan_secrets history --base <ref> --head <ref> [--evento <nome>]
                                                blobs que o intervalo acrescenta

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de configuracao.

`tree` e `staged` usam o **mesmo** scanner e a **mesma** configuracao, que e o
que o ticket exige: "o hook de pre-commit aplica o mesmo scanner". A unica
diferenca e o conjunto de ficheiros.

O `history` e a segunda passagem do gate 9 (KAM-131) e **nao substitui** o
`tree`: o `make ci-9` corre os dois. Sao dois subcomandos e nao um `tree` que
tambem olha para a historia, para que o alcance de cada passagem se leia no
comando que a corre. O alcance de cada um:

    tree      o que o git segue agora, na arvore de trabalho
    history   os blobs do intervalo `base..head`, mesmo os que a arvore ja nao tem
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .historia import decidir_intervalo, exigir_commits, varrer_intervalo
from .scanner import ConfiguracaoInvalida, Permissoes, varrer_ficheiros


def _git(raiz: Path, *argumentos: str) -> list[str]:
    try:
        resultado = subprocess.run(
            ["git", *argumentos], cwd=raiz, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        raise ConfiguracaoInvalida(f"git falhou em {raiz}: {excepcao}") from excepcao
    return [p for p in resultado.stdout.decode("utf-8", "replace").split("\0") if p]


def ficheiros_seguidos(raiz: Path) -> list[Path]:
    return [raiz / p for p in _git(raiz, "ls-files", "-z") if (raiz / p).is_file()]


def ficheiros_em_stage(raiz: Path) -> list[Path]:
    """Os ficheiros que o commit vai levar.

    `--diff-filter=d` exclui os apagados: um ficheiro que sai do repositorio nao
    tem conteudo para varrer.
    """
    caminhos = _git(
        raiz, "diff", "--cached", "--name-only", "--diff-filter=d", "-z"
    )
    return [raiz / p for p in caminhos if (raiz / p).is_file()]


def _historia(raiz: Path, argumentos: argparse.Namespace) -> int:
    """A segunda passagem: os blobs que o intervalo acrescenta a historia.

    O modo decide-se em `historia.decidir_intervalo`, que e uma funcao pura
    sobre os valores em bruto do evento — o *workflow* nao decide nada.
    """
    try:
        permissoes = Permissoes.ler(raiz)
        intervalo = decidir_intervalo(
            argumentos.evento, argumentos.base, argumentos.head
        )
        if intervalo.modo == "so-arvore":
            # Diz-se o modo e **nao** se da a passagem da historia por
            # satisfeita: nao correu, e o relatorio tem de o dizer com essas
            # palavras. O `::warning::` existe para que a linha apareca no
            # resumo do job e nao so no meio do registo, que ninguem le.
            print(
                "::warning title=gate 9::a passagem da historia NAO CORREU "
                f"({intervalo.razao})"
            )
            print(
                "scan_secrets: passagem da historia NAO CORRIDA — modo `so-arvore`\n"
                f"  razao: {intervalo.razao}\n"
                "  A arvore seguida pelo git e varrida pela outra passagem; os blobs\n"
                "  do intervalo nao, porque neste accionamento nao existe intervalo."
            )
            return 0
        resultado = varrer_intervalo(
            raiz, intervalo.base, intervalo.head, permissoes
        )
        exigir_commits(argumentos.evento, resultado.commits)
    except ConfiguracaoInvalida as excepcao:
        print(f"scan_secrets: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2

    if resultado.achados:
        print(
            f"scan_secrets: {len(resultado.achados)} achado(s) em "
            f"{resultado.onde}",
            file=sys.stderr,
        )
        for achado in resultado.achados:
            print(f"  - {achado}", file=sys.stderr)
        print(
            "\n  Cada linha diz o **commit** e o caminho em que o blob apareceu: e\n"
            "  isso que a correccao precisa de saber para rodar a chave certa.\n"
            "  Apagar a linha num commit seguinte nao resolve — foi por isso que\n"
            "  esta passagem existe. **Rode a chave.**\n"
            "  Se nao e segredo, declare a area e a classe em ci/secrets-allow.yaml.",
            file=sys.stderr,
        )
        return 1

    print(f"scan_secrets: limpo — {resultado.onde}")
    return 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="scan_secrets", description="Gate 9: varrimento de segredos"
    )
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("tree", help="varre a arvore seguida pelo git")
    sub.add_parser("staged", help="varre o que esta em stage (pre-commit)")
    nomeados = sub.add_parser("files", help="varre ficheiros nomeados")
    nomeados.add_argument("caminhos", nargs="+", type=Path)
    historica = sub.add_parser(
        "history", help="varre os blobs que o intervalo acrescenta a historia"
    )
    historica.add_argument("--base", default="", help="SHA de base do intervalo")
    historica.add_argument("--head", default="HEAD", help="SHA de cabeca do intervalo")
    historica.add_argument(
        "--evento",
        default="",
        help="accionamento do CI (github.event_name); decide o modo sem base",
    )

    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()

    if argumentos.comando == "history":
        return _historia(raiz, argumentos)

    try:
        permissoes = Permissoes.ler(raiz)
        if argumentos.comando == "tree":
            caminhos = ficheiros_seguidos(raiz)
            onde = f"{len(caminhos)} ficheiros seguidos pelo git"
        elif argumentos.comando == "staged":
            caminhos = ficheiros_em_stage(raiz)
            onde = f"{len(caminhos)} ficheiros em stage"
            if not caminhos:
                print("scan_secrets: nada em stage")
                return 0
        else:
            caminhos = [c for c in argumentos.caminhos if c.is_file()]
            onde = f"{len(caminhos)} ficheiro(s)"

        achados = varrer_ficheiros(caminhos, raiz, permissoes)

    except ConfiguracaoInvalida as excepcao:
        print(f"scan_secrets: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2

    if achados:
        print(
            f"scan_secrets: {len(achados)} achado(s) em {onde}", file=sys.stderr
        )
        for achado in achados:
            print(f"  - {achado}", file=sys.stderr)
        print(
            "\n  Se e um segredo a serio: **rode a chave**. Apagar a linha nao basta,\n"
            "  porque o valor fica na historia do git.\n"
            "  Se nao e segredo, declare a area e a classe em ci/secrets-allow.yaml.",
            file=sys.stderr,
        )
        return 1

    print(f"scan_secrets: limpo — {onde}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

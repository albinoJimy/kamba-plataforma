"""Interface de linha de comando do `dict_export`.

    python -m dict_export [--root .]            escreve canon/dicionario.yaml
    python -m dict_export [--root .] --check    compara, sem escrever

Codigo de saida 0 = igual (ou escrito), 1 = o ficheiro diverge do Markdown,
2 = o dicionario nao se consegue ler. A distincao importa: um dicionario
ilegivel nao pode parecer um ficheiro em dia.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError

from .exportar import DESTINO, FONTE, exportar
from .markdown import DicionarioIlegivel


def main(argv: list[str] | None = None) -> int:
    # As mensagens citam o dicionario, que tem `§`, `∈` e `…`: numa consola
    # cp1252 o primeiro erro seria um `UnicodeEncodeError` em vez da mensagem.
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
    analisador = argparse.ArgumentParser(
        prog="dict_export",
        description="Exporta o §3 do dicionario canonico para canon/dicionario.yaml",
    )
    analisador.add_argument("--root", type=Path, default=None)
    analisador.add_argument(
        "--check", action="store_true", help="falha se o ficheiro divergir do Markdown"
    )
    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()
    destino = raiz / DESTINO

    try:
        gerado = exportar(raiz)
    except (DicionarioIlegivel, YamlSubsetError) as excepcao:
        print(f"dict_export: erro: {excepcao}", file=sys.stderr)
        return 2

    if not argumentos.check:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # `newline="\n"`: o ficheiro e comparado byte a byte no `--check`, e o
        # `.gitattributes` fixa LF. Sem isto, gerar em Windows dava CRLF.
        with open(destino, "w", encoding="utf-8", newline="\n") as ficheiro:
            ficheiro.write(gerado)
        print(f"dict_export: {DESTINO} escrito a partir de {FONTE}")
        return 0

    try:
        actual = destino.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except OSError:
        print(
            f"dict_export: {DESTINO} nao existe. Gere-o com `python -m dict_export`.",
            file=sys.stderr,
        )
        return 1
    except UnicodeDecodeError as excepcao:
        print(f"dict_export: {DESTINO} nao e UTF-8: {excepcao}", file=sys.stderr)
        return 1

    if actual == gerado:
        print(f"dict_export: {DESTINO} corresponde a {FONTE}")
        return 0

    print(
        f"dict_export: {DESTINO} diverge de {FONTE}.\n"
        "  A fonte da verdade e o Markdown. Regenere com:\n"
        "      cd tools && python -m dict_export --root ..\n"
        "  e reveja o diff: e a lista do que o gate 3b passa a aceitar e a recusar.",
        file=sys.stderr,
    )
    diferenca = difflib.unified_diff(
        actual.splitlines(), gerado.splitlines(), DESTINO, "gerado", lineterm="", n=1
    )
    for numero, linha in enumerate(diferenca):
        if numero >= 40:
            print("  (...)", file=sys.stderr)
            break
        print(f"  {linha}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

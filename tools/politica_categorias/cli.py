"""Linha de comandos da politica de categorias (KAM-088).

    python -m politica_categorias gerar [--root .]   valida, fixa a versao e gera o TS
    python -m politica_categorias check [--root .]   nao escreve; falha se divergir

Codigo de saida 0 = conforme, 1 = divergencia, 2 = politica invalida — a
distincao do `dict_export` e do `subprocessadores`: uma politica que nao se le
nao pode parecer um repositorio limpo.

O `check` corre no gate 4 como ensaio da suite desta pasta
(`tests/test_politica.py::TestRepositorio`), e nao como passo novo de um gate:
mudar o que um gate corre e do fundador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import politica as pol


def _utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def _escrever(caminho: Path, conteudo: str) -> None:
    """Com `\\n` sempre: o Python em Windows traduz para `\\r\\n` sem `newline=""`."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as ficheiro:
        ficheiro.write(conteudo)


def _ler_texto(caminho: Path) -> str | None:
    if not caminho.exists():
        return None
    with caminho.open(encoding="utf-8", newline="") as ficheiro:
        return ficheiro.read()


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(prog="politica_categorias")
    parser.add_argument("comando", choices=("gerar", "check"))
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    args = parser.parse_args(argv)
    raiz = Path(args.root).resolve()

    try:
        politica = pol.ler(raiz)
        lock = pol.ler_lock(raiz)
        if args.comando == "gerar":
            novo = pol.lock_com(politica, lock)
            _escrever(raiz / pol.LOCK, pol.texto_do_lock(novo))
            _escrever(raiz / pol.GERADO, pol.modulo_ts(politica))
            print(f"politica_categorias: {politica.versao} ({politica.sha256[:12]}) gerada")
            return 0
    except pol.PoliticaInvalida as erro:
        print(f"politica_categorias: politica invalida — {erro}", file=sys.stderr)
        return 2

    problemas = pol.problemas_do_lock(politica, lock)
    if _ler_texto(raiz / pol.GERADO) != pol.modulo_ts(politica):
        problemas.append(f"{pol.GERADO} nao corresponde a fonte: corre `gerar`")
    for problema in problemas:
        print(f"politica_categorias: {problema}", file=sys.stderr)
    if problemas:
        return 1
    print(f"politica_categorias: {politica.versao} conforme")
    return 0

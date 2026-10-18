"""Extrai os blocos ```mermaid de ficheiros Markdown.

Python puro, sem dependencias. A saida e JSON na saida padrao, para alimentar o
`verificar.mjs` — que corre noutro processo, noutra linguagem e noutro
contentor, e por isso a fronteira e um formato e nao uma chamada.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

#: A cerca de bloco de codigo. Escrita assim, e nao como literal, para que este
#: proprio ficheiro nao passe a conter uma cerca que confunda quem o le em
#: Markdown — e para que o `grep` por cercas no repositorio nao o apanhe.
CERCA = "`" * 3

LINGUAGEM = "mermaid"


@dataclass(frozen=True)
class Bloco:
    """Um diagrama, com a sua morada."""

    ficheiro: str
    #: Linha da cerca de abertura, em base 1 — que e a linha para onde um editor
    #: salta. O diagrama comeca na seguinte.
    linha: int
    texto: str


class BlocoPorFechar(Exception):
    """Uma cerca de abertura sem a de fecho.

    E erro de configuracao e nao achado: o ficheiro esta malformado, e um
    extractor que devolvesse o resto do documento como se fosse um diagrama
    daria um erro de *parse* que ninguem conseguiria ler.
    """


def blocos_de(texto: str, ficheiro: str) -> list[Bloco]:
    """Os blocos de um documento, por ordem de aparicao.

    A deteccao e por linha e nao por expressao regular sobre o texto todo: uma
    cerca so conta quando esta sozinha na sua linha, que e a regra do
    CommonMark que importa aqui. `  ```mermaid  ` com espacos a volta conta;
    `x = "```mermaid"` no meio de uma linha nao.
    """
    linhas = texto.splitlines()
    encontrados: list[Bloco] = []
    i = 0
    while i < len(linhas):
        if linhas[i].strip() != CERCA + LINGUAGEM:
            i += 1
            continue
        abertura = i
        fim = abertura + 1
        while fim < len(linhas) and linhas[fim].strip() != CERCA:
            fim += 1
        if fim >= len(linhas):
            raise BlocoPorFechar(
                f"{ficheiro}:{abertura + 1}: bloco `{LINGUAGEM}` aberto e nunca fechado"
            )
        encontrados.append(
            Bloco(
                ficheiro=ficheiro,
                linha=abertura + 1,
                texto="\n".join(linhas[abertura + 1 : fim]),
            )
        )
        i = fim + 1
    return encontrados


def blocos_de_ficheiros(caminhos: list[Path], raiz: Path) -> list[Bloco]:
    """Os blocos de varios ficheiros, com o caminho relativo a raiz.

    O caminho vai relativo de proposito: e o que entra no relatorio, e um
    relatorio que imprime `C:\\Jimy\\Ideias\\docs\\...` nao se compara entre
    duas maquinas.
    """
    todos: list[Bloco] = []
    for caminho in caminhos:
        relativo = caminho.relative_to(raiz).as_posix()
        todos += blocos_de(caminho.read_text(encoding="utf-8"), relativo)
    return todos


def alvos(raiz: Path, padroes: list[str], excluidos: tuple[str, ...] = ()) -> list[Path]:
    """Os ficheiros a ler, ordenados — para que a saida seja determinista."""
    vistos: dict[Path, None] = {}
    for padrao in padroes:
        for caminho in sorted(raiz.glob(padrao)):
            if not caminho.is_file():
                continue
            if caminho.relative_to(raiz).as_posix() in excluidos:
                continue
            vistos[caminho] = None
    return list(vistos)


#: Onde vivem os diagramas que alguem corrige. `docs/exploracao/` fica de fora
#: por ser historico, e o conjunto nao o considera fonte.
PADROES = ["docs/tecnica/*.md", "docs/*.md", "specs/*.md"]

#: E este fica de fora com nome e razao: e artefacto **compilado**, o canon diz
#: expressamente «nao o edites e nao o cites como fonte», e esta desactualizado.
#: Os seus vinte e tal diagramas sao copias velhas dos que vivem em
#: `docs/tecnica/` — reporta-los seria pedir a alguem que corrigisse um ficheiro
#: que ninguem deve tocar.
EXCLUIDOS = ("docs/00-KAMBA-documento-mestre.md",)


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="mermaid_lint.extrair",
        description="Extrai os blocos mermaid de Markdown, em JSON, para o verificar.mjs",
    )
    analisador.add_argument("--root", default=".", help="raiz do repositorio")
    analisador.add_argument(
        "--padrao",
        action="append",
        default=None,
        help=f"glob a varrer, repetivel (omissao: {' '.join(PADROES)})",
    )
    analisador.add_argument(
        "--listar",
        action="store_true",
        help="imprime ficheiro:linha de cada bloco em vez do JSON",
    )
    argumentos = analisador.parse_args(argv)

    raiz = Path(argumentos.root).resolve()
    # Os exclusoes so valem para a varredura por omissao: quem nomeia um padrao
    # a mao esta a pedir aquele ficheiro, e o extractor nao lho nega em silencio.
    if argumentos.padrao:
        caminhos = alvos(raiz, argumentos.padrao)
    else:
        caminhos = alvos(raiz, PADROES, EXCLUIDOS)
    try:
        encontrados = blocos_de_ficheiros(caminhos, raiz)
    except BlocoPorFechar as erro:
        print(f"mermaid_lint: {erro}", file=sys.stderr)
        return 2

    if argumentos.listar:
        for bloco in encontrados:
            primeira = bloco.texto.splitlines()[0] if bloco.texto.splitlines() else "(vazio)"
            print(f"{bloco.ficheiro}:{bloco.linha}  {primeira}")
        print(f"{len(encontrados)} bloco(s) em {len(caminhos)} ficheiro(s)")
        return 0

    json.dump([asdict(b) for b in encontrados], sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

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

#: As duas cercas do CommonMark. O `~~~` nao existe hoje no conjunto, e estava a
#: faltar: um diagrama partido escrito assim passava o gate **sem ser lido** —
#: um falso verde, que e a pior coisa que um verificador pode produzir.
CARACTERES_DE_CERCA = ("`", "~")

#: Quatro espacos fazem bloco **literal** em CommonMark, nao cerca. Sem este
#: limite, uma cerca dentro de um exemplo indentado era lida como diagrama — e,
#: pior, engolia o diagrama seguinte, que deixava de ser analisado sozinho.
INDENTACAO_MAXIMA = 3


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


def _abertura(linha: str) -> tuple[str, int] | None:
    """A cerca de abertura de uma linha, ou `None`.

    Devolve o caracter da cerca e o seu comprimento. Segue o CommonMark no que
    aqui importa, e cada regra custou um achado da revisao adversarial:

    * ate **tres** espacos de indentacao; quatro fazem bloco literal;
    * tres ou mais do **mesmo** caracter, `` ` `` ou `~`;
    * a linguagem e a **primeira palavra** da *info string*, para que
      ```` ```mermaid {id=x} ```` conte e ```` ```mermaidjs ```` nao.
    """
    sem_indentacao = linha.lstrip(" ")
    if len(linha) - len(sem_indentacao) > INDENTACAO_MAXIMA:
        return None
    for caracter in CARACTERES_DE_CERCA:
        if not sem_indentacao.startswith(caracter * 3):
            continue
        comprimento = len(sem_indentacao) - len(sem_indentacao.lstrip(caracter))
        resto = sem_indentacao[comprimento:].strip()
        # Uma cerca de crases nao pode ter crases na *info string*.
        if caracter == "`" and "`" in resto:
            return None
        if resto.split()[:1] == [LINGUAGEM]:
            return caracter, comprimento
        return None
    return None


def _e_fecho(linha: str, caracter: str, comprimento: int) -> bool:
    """Uma cerca de fecho e do **mesmo** caracter, igual ou mais longa, e nua."""
    sem_indentacao = linha.lstrip(" ")
    if len(linha) - len(sem_indentacao) > INDENTACAO_MAXIMA:
        return False
    if not sem_indentacao.startswith(caracter * comprimento):
        return False
    return sem_indentacao.strip(caracter).strip() == ""


def blocos_de(texto: str, ficheiro: str) -> list[Bloco]:
    """Os blocos de um documento, por ordem de aparicao.

    A deteccao e por linha e nao por expressao regular sobre o texto todo: uma
    cerca so conta quando esta sozinha na sua linha. `x = "```mermaid"` no meio
    de uma linha nao abre bloco nenhum.
    """
    linhas = texto.splitlines()
    encontrados: list[Bloco] = []
    i = 0
    while i < len(linhas):
        cerca = _abertura(linhas[i])
        if cerca is None:
            i += 1
            continue
        caracter, comprimento = cerca
        abertura = i
        fim = abertura + 1
        while fim < len(linhas) and not _e_fecho(linhas[fim], caracter, comprimento):
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

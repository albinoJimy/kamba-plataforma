"""O sorteio da amostra de H8 e a folha de auditoria do catalogo (KAM-109).

## O sorteio e reprodutivel por qualquer um, sem este codigo

Cada produto recebe a chave `sha256("<semente>:<pme>:<produto_id>")`, em hex, e
a amostra sao os 20 de chave mais baixa (todos, se houver menos). Nao usa o
`random` do Python: o resultado nao depende da versao do interpretador nem da
ordem em que os produtos chegam, e um auditor confere-o com `sha256sum` e um
`sort`. A semente e um texto que o protocolo regista **antes** da auditoria;
com a semente, a lista de produtos e o ordinal da PME, a amostra e uma so.

## A folha

Um CSV por PME, em UTF-8 com LF, com as colunas de `COLUNAS_DA_FOLHA`. As
quatro primeiras vem do sistema; as tres seguintes preenche-as quem audita, com
a verdade apurada com o dono ou na visita. A folha **nao tem coluna de texto
livre**: uma nota era o sitio onde o nome do dono ou um telefone entravam.

O numero de mudancas reais que o dono declara nas 4 semanas e da PME e nao de um
produto: vai numa linha propria, com `n` = `mudancas` (ver `ler_folha`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable

from .regras import H8_AMOSTRA_POR_PME, Auditoria

COLUNAS_DA_FOLHA: Final = (
    "n",
    "produto_id",
    "nome",
    "preco_sistema_minor",
    "disponivel_sistema",
    "preco_verdade_minor",
    "disponivel_verdade",
    "fonte_verdade",
)
FONTES_DA_VERDADE: Final = frozenset({"dono", "visita"})
SIM_NAO: Final = {"sim": True, "nao": False}
LINHA_DAS_MUDANCAS: Final = "mudancas"

_PME: Final = re.compile(r"^P\d{2}$")
#: Um nome de produto nao e dado pessoal, mas um telefone dentro dele seria: o
#: catalogo e escrito pelo dono, e «Bolo por encomenda 923…» acontece.
_TELEFONE: Final = re.compile(r"(?<![0-9A-Za-z])(?:\+?244[ .-]?)?9\d{2}[ .-]?\d{3}[ .-]?\d{3}(?![0-9A-Za-z])")


class FolhaInvalida(Exception):
    """A folha de auditoria nao tem a forma esperada."""


@dataclass(frozen=True)
class Produto:
    produto_id: str
    nome: str
    preco_minor: int | None  # `None`: preco sob consulta
    disponivel: bool


def chave(semente: str, pme: str, produto_id: str) -> str:
    return hashlib.sha256(f"{semente}:{pme}:{produto_id}".encode("utf-8")).hexdigest()


def sortear(
    semente: str, pme: str, produtos: Iterable[Produto], n: int = H8_AMOSTRA_POR_PME
) -> list[Produto]:
    """Os `n` produtos de chave mais baixa, por ordem de chave."""
    if not semente.strip():
        raise ValueError("a semente nao pode ser vazia: e ela que torna o sorteio auditavel")
    if not _PME.match(pme):
        raise ValueError("a PME e um ordinal P01..P99")
    lista = list(produtos)
    ids = [p.produto_id for p in lista]
    if len(set(ids)) != len(ids):
        raise ValueError("produto_id repetido na lista")
    return sorted(lista, key=lambda p: chave(semente, pme, p.produto_id))[:n]


def _sem_telefone(texto: str, onde: str) -> str:
    if _TELEFONE.search(texto):
        raise FolhaInvalida(f"{onde}: o texto tem a forma de um telefone; corrige o nome no catalogo")
    return texto


def folha(amostra: list[Produto]) -> str:
    """O CSV da folha, com as colunas da verdade em branco."""
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(COLUNAS_DA_FOLHA)
    for n, produto in enumerate(amostra, start=1):
        escritor.writerow(
            [
                n,
                _sem_telefone(produto.produto_id, f"produto n.º {n}"),
                _sem_telefone(produto.nome, f"produto n.º {n}"),
                "" if produto.preco_minor is None else produto.preco_minor,
                "sim" if produto.disponivel else "nao",
                "",
                "",
                "",
            ]
        )
    escritor.writerow([LINHA_DAS_MUDANCAS, "", "", "", "", "", "", ""])
    return saida.getvalue()


def _inteiro(texto: str, onde: str) -> int:
    if not re.fullmatch(r"\d+", texto or ""):
        raise FolhaInvalida(f"{onde}: esperava um inteiro nao negativo, veio {texto!r}")
    return int(texto)


def _preco(texto: str, onde: str) -> int | None:
    """Um preco em AOA minor, ou vazio para «sob consulta»."""
    return None if texto == "" else _inteiro(texto, onde)


def _sim_nao(texto: str, onde: str) -> bool:
    if texto not in SIM_NAO:
        raise FolhaInvalida(f"{onde}: esperava sim ou nao, veio {texto!r}")
    return SIM_NAO[texto]


def ler_folha(texto: str, pme: str, actualizacoes: int | None = None) -> Auditoria:
    """A auditoria de uma folha preenchida. Recusa uma folha a meio.

    Um item e certo se o preco **e** a disponibilidade coincidem com a verdade.
    """
    leitor = csv.reader(io.StringIO(texto))
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise FolhaInvalida(f"{pme}: folha vazia") from None
    if tuple(cabecalho) != COLUNAS_DA_FOLHA:
        raise FolhaInvalida(f"{pme}: colunas {cabecalho}, esperava {list(COLUNAS_DA_FOLHA)}")
    itens = correctos = 0
    mudancas: int | None = None
    vistos: set[str] = set()
    for numero, linha in enumerate(leitor, start=2):
        onde = f"{pme} linha {numero}"
        if len(linha) != len(COLUNAS_DA_FOLHA):
            raise FolhaInvalida(f"{onde}: {len(linha)} colunas, esperava {len(COLUNAS_DA_FOLHA)}")
        if linha[0] == LINHA_DAS_MUDANCAS:
            if any(linha[1:]) and not linha[5]:
                raise FolhaInvalida(f"{onde}: as mudancas vao na coluna preco_verdade_minor")
            if mudancas is not None:
                raise FolhaInvalida(f"{onde}: linha de mudancas repetida")
            mudancas = _inteiro(linha[5], f"{onde} (mudancas)") if linha[5] else None
            continue
        n, produto_id, nome, preco, disp, preco_v, disp_v, fonte = linha
        _inteiro(n, f"{onde} n")
        if produto_id in vistos:
            raise FolhaInvalida(f"{onde}: produto repetido")
        vistos.add(produto_id)
        _sem_telefone(nome, onde)
        _sem_telefone(produto_id, onde)
        if fonte not in FONTES_DA_VERDADE:
            raise FolhaInvalida(f"{onde}: fonte_verdade e dono ou visita, veio {fonte!r} (folha por preencher?)")
        certo = _preco(preco, onde) == _preco(preco_v, onde) and _sim_nao(disp, onde) == _sim_nao(
            disp_v, onde
        )
        itens += 1
        correctos += certo
    if itens == 0:
        raise FolhaInvalida(f"{pme}: nenhum item auditado")
    if itens > H8_AMOSTRA_POR_PME:
        raise FolhaInvalida(f"{pme}: {itens} itens, a amostra e de {H8_AMOSTRA_POR_PME}")
    return Auditoria(pme, itens, correctos, actualizacoes, mudancas)


def ler_produtos(caminho: Path) -> list[Produto]:
    """A lista de produtos de uma PME, num CSV `produto_id,nome,preco_minor,disponivel`."""
    with caminho.open(encoding="utf-8", newline="") as ficheiro:
        leitor = csv.DictReader(ficheiro)
        esperado = ["produto_id", "nome", "preco_minor", "disponivel"]
        if leitor.fieldnames != esperado:
            raise FolhaInvalida(f"{caminho.name}: colunas {leitor.fieldnames}, esperava {esperado}")
        return [
            Produto(
                linha["produto_id"],
                linha["nome"],
                _preco(linha["preco_minor"], f"{caminho.name} {linha['produto_id']}"),
                _sim_nao(linha["disponivel"], f"{caminho.name} {linha['produto_id']}"),
            )
            for linha in leitor
        ]

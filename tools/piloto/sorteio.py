"""O sorteio da amostra de H8 e a folha de auditoria do catalogo (KAM-109).

## O sorteio e reprodutivel por qualquer um, sem este codigo

Cada produto recebe a chave `sha256("<semente>:<pme>:<produto_id>")`, em hex, e
a amostra sao os 20 de chave mais baixa (todos, se houver menos). Nao usa o
`random` do Python: o resultado nao depende da versao do interpretador nem da
ordem em que os produtos chegam, e um auditor confere-o com `sha256sum` e um
`sort`. A semente e um texto que o protocolo regista **antes** da auditoria;
com a semente, a lista de produtos e o ordinal da PME, a amostra e uma so — e o
`medir` refa-la e recusa uma folha cujos produtos nao sejam exactamente esses,
pela mesma ordem.

## A folha

Um CSV por PME, em UTF-8 com LF, com as colunas de `COLUNAS_DA_FOLHA`. As
quatro primeiras vem do sistema; as tres seguintes preenche-as quem audita, com
a verdade apurada com o dono ou na visita. A folha **nao tem coluna de texto
livre**: uma nota era o sitio onde o nome do dono ou um telefone entravam.

Duas linhas de controlo fecham a folha, com o valor na coluna
`preco_verdade_minor`: `mudancas` (as mudancas reais de preco ou de stock que o
dono declara nas 4 semanas) e `auditado_em` (o dia da auditoria, AAAA-MM-DD).
As duas sao obrigatorias: uma folha sem elas esta por preencher.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable

from . import guarda
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
LINHA_DA_DATA: Final = "auditado_em"
_VALOR: Final = COLUNAS_DA_FOLHA.index("preco_verdade_minor")

_PME: Final = re.compile(r"^P\d{2}$")


class FolhaInvalida(Exception):
    """A folha de auditoria nao tem a forma esperada."""


@dataclass(frozen=True)
class Produto:
    produto_id: str
    nome: str
    preco_minor: int | None  # `None`: preco sob consulta
    disponivel: bool


@dataclass(frozen=True)
class Folha:
    """Uma folha preenchida: a auditoria e os produtos, pela ordem da folha."""

    auditoria: Auditoria
    produtos: tuple[str, ...]


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
    """Um nome de produto nao e dado pessoal, mas um telefone dentro dele seria:
    o catalogo e escrito pelo dono, e «Bolo por encomenda 923…» acontece."""
    if guarda.tem_telefone(texto):
        raise FolhaInvalida(f"{onde}: o texto tem a forma de um telefone; corrige o nome no catalogo")
    return texto


def folha(amostra: list[Produto]) -> str:
    """O CSV da folha, com as colunas da verdade e as linhas de controlo em branco."""
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
    for controlo in (LINHA_DAS_MUDANCAS, LINHA_DA_DATA):
        escritor.writerow([controlo] + [""] * (len(COLUNAS_DA_FOLHA) - 1))
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


def ler_folha(texto: str, pme: str, actualizacoes: int | None = None) -> Folha:
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
    correctos = 0
    controlo: dict[str, str] = {}
    produtos: list[str] = []
    for numero, linha in enumerate(leitor, start=2):
        onde = f"{pme} linha {numero}"
        if not any(linha):
            continue
        if len(linha) != len(COLUNAS_DA_FOLHA):
            raise FolhaInvalida(f"{onde}: {len(linha)} colunas, esperava {len(COLUNAS_DA_FOLHA)}")
        if linha[0] in (LINHA_DAS_MUDANCAS, LINHA_DA_DATA):
            if linha[0] in controlo:
                raise FolhaInvalida(f"{onde}: linha {linha[0]} repetida")
            if any(c for i, c in enumerate(linha[1:], start=1) if i != _VALOR):
                raise FolhaInvalida(f"{onde}: o valor de {linha[0]} vai so na coluna preco_verdade_minor")
            controlo[linha[0]] = linha[_VALOR]
            continue
        if controlo:
            raise FolhaInvalida(f"{onde}: item depois das linhas de controlo")
        n, produto_id, nome, preco, disp, preco_v, disp_v, fonte = linha
        if _inteiro(n, f"{onde} n") != len(produtos) + 1:
            raise FolhaInvalida(f"{onde}: a numeracao dos itens salta")
        if produto_id in produtos:
            raise FolhaInvalida(f"{onde}: produto repetido")
        produtos.append(produto_id)
        _sem_telefone(nome, onde)
        _sem_telefone(produto_id, onde)
        if fonte not in FONTES_DA_VERDADE:
            raise FolhaInvalida(f"{onde}: fonte_verdade e dono ou visita, veio {fonte!r} (folha por preencher?)")
        certo = _preco(preco, onde) == _preco(preco_v, onde) and _sim_nao(disp, onde) == _sim_nao(
            disp_v, onde
        )
        correctos += certo
    if not produtos:
        raise FolhaInvalida(f"{pme}: nenhum item auditado")
    if len(produtos) > H8_AMOSTRA_POR_PME:
        raise FolhaInvalida(f"{pme}: {len(produtos)} itens, a amostra e de {H8_AMOSTRA_POR_PME}")
    em_falta = [c for c in (LINHA_DAS_MUDANCAS, LINHA_DA_DATA) if not controlo.get(c)]
    if em_falta:
        raise FolhaInvalida(f"{pme}: linha(s) de controlo por preencher: {', '.join(em_falta)}")
    try:
        auditado_em = dt.date.fromisoformat(controlo[LINHA_DA_DATA])
    except ValueError:
        raise FolhaInvalida(f"{pme}: auditado_em nao e AAAA-MM-DD") from None
    auditoria = Auditoria(
        pme, len(produtos), correctos, actualizacoes,
        _inteiro(controlo[LINHA_DAS_MUDANCAS], f"{pme} (mudancas)"), auditado_em,
    )
    return Folha(auditoria, tuple(produtos))


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

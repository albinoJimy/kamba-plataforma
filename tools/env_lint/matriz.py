"""Leitura da matriz de ambientes de `infra/ENVIRONMENTS.md` §2.

A matriz e um **documento Markdown** e a configuracao sao tres **ficheiros
YAML**. Este modulo le o primeiro; o `lint.py` compara os dois.

## O predicado, definido antes de contar

Uma celula da matriz contem um **token canonico** e, a seguir, prosa opcional.
O token e o primeiro trecho em codigo inline da celula:

    | Dados | `dados.classe` | `synthetic` | `synthetic` — nunca copia | ... |
                              ^^^^^^^^^^^   ^^^^^^^^^^^
                              token         token (a prosa a seguir ignora-se)

Compara-se o token e so o token. A alternativa — comparar a celula inteira —
obrigava a escrever a tabela sem explicacao nenhuma, e uma matriz sem prosa e
uma matriz que ninguem le.

## O que este modulo NAO cobre, e e preciso dizer

* **Nao valida Markdown.** Procura a tabela cujo cabecalho e
  `| Aspecto | Chave | ... |` e le as linhas dela; uma tabela mal formada da
  `matriz-ilegivel`, nao uma leitura parcial silenciosa.
* **Nao le a §3 nem a §7.** A §3 e a linha que esta deliberadamente fora do
  conjunto verificado (Factura AGT), e a §7 tem a sua propria tabela, lida
  a parte por `tabela_acrescentada`.
* **Uma celula sem token** da `matriz-celula-sem-token`. Nao se trata como
  «igual a qualquer coisa»: uma celula vazia era o modo de falha mais provavel
  desta leitura, porque passaria todas as comparacoes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Os tres ambientes, na ordem das colunas da matriz. A ordem e a do doc 09 §6.
AMBIENTES = ("dev", "staging", "prod")

#: O cabecalho que identifica cada uma das duas tabelas lidas.
_CABECALHO_MATRIZ = ("Aspecto", "Chave", "`dev`", "`staging`", "`prod`")
_CABECALHO_ACRESCENTADA = ("Aspecto", "Chave", "`dev`", "`staging`", "`prod`", "Estado")

_TOKEN = re.compile(r"`([^`]+)`")


class MatrizIlegivel(ValueError):
    """A matriz nao se le. E erro de configuracao (codigo 2), nao achado."""


@dataclass(frozen=True)
class Linha:
    """Uma linha da matriz: o aspecto, a chave, e o token por ambiente."""

    aspecto: str
    chave: str
    #: `ambiente` -> token canonico.
    valores: dict[str, str]


def _celulas(linha: str) -> list[str]:
    bruta = linha.strip()
    if not bruta.startswith("|") or not bruta.endswith("|"):
        return []
    return [celula.strip() for celula in bruta[1:-1].split("|")]


def _e_separador(celulas: list[str]) -> bool:
    return bool(celulas) and all(set(c) <= set("-: ") and "-" in c for c in celulas)


def _token(celula: str, onde: str) -> str:
    achado = _TOKEN.search(celula)
    if achado is None:
        raise MatrizIlegivel(f"{onde}: celula sem token em codigo inline ({celula!r})")
    return achado.group(1)


def _ler_tabela(texto: str, cabecalho: tuple[str, ...], onde: str) -> list[Linha]:
    linhas_md = texto.splitlines()
    inicio = None
    for indice, linha in enumerate(linhas_md):
        if tuple(_celulas(linha)) == cabecalho:
            if inicio is not None:
                raise MatrizIlegivel(
                    f"{onde}: duas tabelas com o cabecalho {cabecalho!r}; "
                    "nao se escolhe uma em silencio"
                )
            inicio = indice
    if inicio is None:
        raise MatrizIlegivel(f"{onde}: nao ha tabela com o cabecalho {cabecalho!r}")

    corpo = linhas_md[inicio + 1 :]
    if not corpo or not _e_separador(_celulas(corpo[0])):
        raise MatrizIlegivel(f"{onde}: a tabela nao tem linha de separacao")

    lidas: list[Linha] = []
    for numero, linha in enumerate(corpo[1:], start=inicio + 3):
        celulas = _celulas(linha)
        if not celulas:
            break
        if len(celulas) != len(cabecalho):
            raise MatrizIlegivel(
                f"{onde} linha {numero}: {len(celulas)} celulas, esperava {len(cabecalho)}"
            )
        chave = _token(celulas[1], f"{onde} linha {numero} (chave)")
        valores = {
            ambiente: _token(celulas[2 + posicao], f"{onde} linha {numero} ({ambiente})")
            for posicao, ambiente in enumerate(AMBIENTES)
        }
        lidas.append(Linha(aspecto=celulas[0], chave=chave, valores=valores))

    if not lidas:
        raise MatrizIlegivel(f"{onde}: a tabela nao tem nenhuma linha de dados")
    return lidas


def ler(texto: str) -> list[Linha]:
    """As sete linhas do doc 09 §6, da §2 de `infra/ENVIRONMENTS.md`."""
    return _ler_tabela(texto, _CABECALHO_MATRIZ, "ENVIRONMENTS.md §2")


def tabela_acrescentada(texto: str) -> list[Linha]:
    """As linhas que o KAM-075 acrescenta (§7): DNS, etiquetas, custo, restauro."""
    return _ler_tabela(texto, _CABECALHO_ACRESCENTADA, "ENVIRONMENTS.md §7")

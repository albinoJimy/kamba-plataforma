"""De onde a medida le os ficheiros: do `git`, e nao do disco (KAM-039).

## O defeito que este modulo existe para fechar

A primeira versao enumerava os ficheiros com `raiz.rglob("*.py")` e casava os
padroes com `fnmatch`, onde o `*` atravessa barras. Parecia inofensivo e nao
era: **este repositorio e trabalhado em worktrees aninhados** — o `.gitignore`
tem `.claude/worktrees/` — e o `*/verticais/servicos/*` casa com qualquer copia
debaixo deles.

Medido pela revisao adversarial e reproduzido: a partir da raiz do *checkout*
principal, o padrao casa **70** ficheiros em vez de 7, porque ha dez copias da
pasta da vertical nos worktrees irmaos. Cada copia vale ~1254 linhas de
numerador, pelo que o reuso caia **abaixo do limiar** — e o `make reuso` corre
precisamente dali (`ROOT` e o directorio do `Makefile`). Pior: o
`test_repositorio.py` passaria no CI, com um clone limpo, e falharia na maquina
de quem o le. E a pior combinacao que um numero pode ter.

## A fonte e o `git`, e isso fecha tres coisas de uma vez

`git ls-files` lista os ficheiros **versionados deste worktree**. Um worktree
aninhado nao e versionado (esta no `.gitignore`), pelo que desaparece sem
precisar de um padrao de exclusao — e um padrao de exclusao era o remendo
errado, porque so cobria os ninhos que alguem se lembrasse de nomear.

Pelo caminho resolve outras duas:

* **um `.py` nao versionado deixa de entrar no numerador.** O `.gitignore` nao
  ignora `.py`, pelo que um ficheiro de rascunho debaixo de
  `verticais/servicos/` contava como codigo da vertical;
* **a medida passa a poder dizer sobre que arvore correu.** O `proveniencia()`
  devolve o *commit* e se a arvore esta suja, e isso vai no artefacto: a
  afirmacao «medido em `183e2b0`» passa a ser verificavel pelo proprio
  instrumento em vez de ser uma frase de quem o correu.

## Recusa em vez de cair para o disco

Se o `git` nao responder, este modulo **levanta**. A alternativa — cair para o
`rglob` — era reintroduzir o defeito exactamente nas condicoes em que ninguem
estaria a olhar.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: O tecto de espera de cada chamada ao `git`. Generoso: um `ls-files` neste
#: repositorio responde em dezenas de milissegundos, e o que isto protege e o
#: caso em que o `git` fica a pedir credenciais.
TECTO_S: Final = 30


class FonteIndisponivelError(RuntimeError):
    """O `git` nao respondeu, ou a raiz nao e um worktree. Ver o cabecalho."""


def _git(raiz: Path, *argumentos: str) -> str:
    try:
        resultado = subprocess.run(
            ["git", "-C", str(raiz), *argumentos],
            capture_output=True,
            timeout=TECTO_S,
            check=False,
            text=False,
        )
    except FileNotFoundError as erro:
        raise FonteIndisponivelError(
            "o `git` nao esta no PATH, e esta medida le os ficheiros dele e nao "
            "do disco (ver o cabecalho de `tools/reuse_metric/fonte.py`)"
        ) from erro
    except subprocess.TimeoutExpired as erro:
        raise FonteIndisponivelError(
            f"`git {' '.join(argumentos)}` nao respondeu em {TECTO_S}s"
        ) from erro
    if resultado.returncode != 0:
        detalhe = resultado.stderr.decode("utf-8", "replace").strip()
        raise FonteIndisponivelError(
            f"`git {' '.join(argumentos)}` saiu com {resultado.returncode} em "
            f"{raiz}: {detalhe or 'sem mensagem'}"
        )
    return resultado.stdout.decode("utf-8", "replace")


def ficheiros_versionados(raiz: Path, padrao: str = "*.py") -> tuple[Path, ...]:
    """Os ficheiros que o `git` segue **neste** worktree, por ordem.

    `-z` e nao linhas: um caminho com acento sai `quoted` no modo normal
    (`core.quotePath`), e o `-z` entrega-o em bruto. Este repositorio tem
    caminhos em portugues.
    """
    bruto = _git(raiz, "ls-files", "-z", "--", padrao)
    caminhos = [p for p in bruto.split("\0") if p]
    return tuple(sorted((raiz / p).resolve() for p in caminhos))


@dataclass(frozen=True, slots=True)
class Proveniencia:
    """Sobre que arvore a medida correu. Vai no artefacto."""

    commit: str
    #: `True` se houver alteracoes nao confirmadas nos ficheiros versionados.
    #: Um numero medido numa arvore suja **nao** descreve nenhum *commit*, e o
    #: artefacto tem de o dizer em vez de deixar quem o le supor.
    sujo: bool

    def como_mapa(self) -> dict:
        return {"commit": self.commit, "arvore_suja": self.sujo}


def proveniencia(raiz: Path) -> Proveniencia:
    """O *commit* da raiz, e se a arvore versionada tem alteracoes pendentes."""
    commit = _git(raiz, "rev-parse", "HEAD").strip()
    pendentes = _git(raiz, "status", "--porcelain", "--untracked-files=no").strip()
    return Proveniencia(commit=commit, sujo=bool(pendentes))


__all__ = [
    "FonteIndisponivelError",
    "Proveniencia",
    "ficheiros_versionados",
    "proveniencia",
]

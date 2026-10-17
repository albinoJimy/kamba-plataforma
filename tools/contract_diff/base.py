"""O contrato como ele esta no ramo principal.

O criterio 3 do KAM-007 diz «comparacao com a *branch* principal», e e a unica
forma de a verificacao ter sentido: um contrato nao esta errado em absoluto —
esta errado **em relacao ao que os consumidores ja assinaram**.

## O que acontece quando o ramo base nao esta la

Num `actions/checkout` sem `fetch-depth: 0`, `origin/main` pode nao existir. A
resposta e **recusar**, nao saltar: uma verificacao de compatibilidade que se
desliga sozinha quando nao encontra a base e uma verificacao que nunca falha no
dia em que alguem configura mal o CI. Quem quiser correr sem base diz-lo por
extenso (`--sem-base`), e a saida regista-o.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path

from contract_diff import catalogo

#: O ramo contra o qual se compara, por omissao.
BASE_POR_OMISSAO = "origin/main"


class BaseIndisponivelError(RuntimeError):
    """O ramo base nao existe nesta copia de trabalho."""


@dataclasses.dataclass(frozen=True)
class ContratoNaBase:
    relativo: str
    tipo: str
    versao: int
    documento: dict


def _git(raiz: Path, *argumentos: str) -> subprocess.CompletedProcess:
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto, o `rev:caminho` de
    # um `git show` e reescrito para um caminho do anfitriao antes de chegar ao
    # git, e o comando falha com «fatal: invalid object name».
    return subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, MSYS_NO_PATHCONV="1"),
    )


def existe(raiz: Path, base: str) -> bool:
    return _git(raiz, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode == 0


def contratos(raiz: Path, base: str) -> dict[tuple[str, int], ContratoNaBase]:
    """Os contratos que o ramo base tem, por `(tipo, versao)`."""
    if not existe(raiz, base):
        raise BaseIndisponivelError(
            f"{base} nao existe nesta copia. No CI, isso costuma ser um `checkout` "
            "sem `fetch-depth: 0` ou sem `git fetch origin main`. Corrija a origem — "
            "ou diga `--sem-base` por extenso, e fique registado que a comparacao "
            "de compatibilidade nao correu"
        )
    pasta = catalogo.PASTA.as_posix()
    listagem = _git(raiz, "ls-tree", "-r", "--name-only", base, "--", pasta)
    if listagem.returncode != 0:
        raise BaseIndisponivelError(f"git ls-tree falhou: {listagem.stderr.strip()}")

    encontrados: dict[tuple[str, int], ContratoNaBase] = {}
    for linha in listagem.stdout.splitlines():
        caminho = linha.strip()
        if not caminho:
            continue
        nome = caminho.rsplit("/", 1)[-1]
        achado = catalogo.NOME_DO_FICHEIRO.match(nome)
        if achado is None:
            continue
        tipo = caminho.split("/")[-2]
        conteudo = _git(raiz, "show", f"{base}:{caminho}")
        if conteudo.returncode != 0:
            raise BaseIndisponivelError(f"git show {base}:{caminho} falhou")
        try:
            documento = json.loads(conteudo.stdout)
        except ValueError as erro:
            raise BaseIndisponivelError(
                f"{base}:{caminho} nao e JSON valido — {erro}"
            ) from erro
        encontrados[(tipo, int(achado.group(1)))] = ContratoNaBase(
            relativo=caminho, tipo=tipo, versao=int(achado.group(1)), documento=documento
        )
    return encontrados

"""Os limiares do `config/kpis.yaml` (KAM-117).

    from kamba_core.kpis import limiares

    l = limiares.ler(Path("config/kpis.yaml"))
    l.dormente_dias            # 60, *proposta*

## Porque nao e YAML

O `kamba_core` nao tem leitor de YAML e nao e aqui que ele deve nascer (a razao
esta no `destinos/golive.py`). O ficheiro e um subconjunto que se le linha a
linha: `chave: inteiro`, comentarios com `#`, linhas em branco, e a `version`.

## O leitor falha fechado

Uma chave desconhecida, uma chave em falta, um valor que nao seja inteiro
positivo, uma chave repetida — tudo levanta `LimiaresInvalidos`. Um limiar
ilegivel **nao** cai para um valor por omissao escrito no codigo: era o codigo a
decidir um numero que a configuracao versionada existe para decidir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path

#: A unica versao do formato que este leitor conhece.
VERSAO = 1

_LINHA = re.compile(r"^([a-z][a-z0-9_]*):\s*(\S+)\s*$")


class LimiaresInvalidos(ValueError):
    """O ficheiro nao tem a forma, ou falta-lhe ou sobra-lhe uma chave."""


@dataclass(frozen=True)
class Limiares:
    """Os limiares, todos em dias e todos *proposta*."""

    dono_sem_actividade_dias: int
    sem_pedidos_dias: int
    pagamento_em_atraso_dias: int
    catalogo_desactualizado_dias: int
    dormente_dias: int
    dormente_janela_clientes_dias: int
    dormente_aviso_dias: int
    modo_ensaio_dias: int

    def __post_init__(self) -> None:
        if self.dormente_aviso_dias >= self.dormente_dias:
            raise LimiaresInvalidos(
                "dormente_aviso_dias tem de ser menor do que dormente_dias: o "
                "aviso sai antes de o orcamento ir a zero"
            )

    def para_sql(self) -> dict[str, int]:
        """Os limiares como o `jsonb` que as funcoes da base recebem."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


CHAVES = tuple(f.name for f in fields(Limiares))


def interpretar(texto: str) -> Limiares:
    """Le o texto do ficheiro. Separado do `ler` para os ensaios."""
    valores: dict[str, int] = {}
    versao: int | None = None
    for numero, linha in enumerate(texto.splitlines(), start=1):
        limpa = linha.split("#", 1)[0].strip()
        if not limpa:
            continue
        casou = _LINHA.match(limpa)
        if casou is None:
            raise LimiaresInvalidos(f"linha {numero}: nao e `chave: inteiro`: {linha!r}")
        chave, cru = casou.groups()
        if not cru.isdigit():
            raise LimiaresInvalidos(f"linha {numero}: {chave} nao e inteiro: {cru!r}")
        valor = int(cru)
        if chave == "version":
            versao = valor
            continue
        if chave not in CHAVES:
            raise LimiaresInvalidos(f"linha {numero}: chave desconhecida {chave!r}")
        if chave in valores:
            raise LimiaresInvalidos(f"linha {numero}: {chave} repetida")
        if valor <= 0:
            raise LimiaresInvalidos(f"linha {numero}: {chave} tem de ser positivo")
        valores[chave] = valor
    if versao != VERSAO:
        raise LimiaresInvalidos(f"version {versao!r}; este leitor so conhece {VERSAO}")
    faltam = [c for c in CHAVES if c not in valores]
    if faltam:
        raise LimiaresInvalidos(f"faltam chaves: {', '.join(faltam)}")
    return Limiares(**valores)


def ler(caminho: Path) -> Limiares:
    return interpretar(caminho.read_text(encoding="utf-8"))

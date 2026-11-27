"""O registo de horas do operador do Piloto (KAM-109).

Um CSV em UTF-8, uma linha por bloco de trabalho:

    dia,pme,minutos,categoria
    2027-01-11,P03,45,t2
    2027-01-11,-,30,outro

* `dia` — AAAA-MM-DD, o dia de Luanda em que o trabalho se fez;
* `pme` — o ordinal da coorte (P01..P99), ou `-` para o que nao e de uma PME;
* `minutos` — inteiro positivo;
* `categoria` — uma de `CATEGORIAS`. Um `incidente` e uma linha desta
  categoria: o relatorio conta as linhas, e soma os minutos as horas.

**Sem coluna de notas**, e e de proposito: o operador fala com donos e clientes,
e uma nota livre era onde um nome ou um telefone ficavam guardados fora do
sistema de producao. O que precisar de texto vai para o *ticket* de suporte,
que tem a sua propria retencao.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from typing import Final

COLUNAS: Final = ("dia", "pme", "minutos", "categoria")
CATEGORIAS: Final = frozenset(
    {"onboarding", "t2", "catalogo", "cobranca", "auditoria", "incidente", "outro"}
)
SEM_PME: Final = "-"
#: Um bloco de mais de 12 horas e um erro de registo, e nao um dia de trabalho.
MINUTOS_MAXIMOS: Final = 12 * 60

_PME: Final = re.compile(r"^P\d{2}$")


class RegistoInvalido(Exception):
    """O registo de horas nao tem a forma esperada."""


@dataclass(frozen=True)
class Bloco:
    dia: dt.date
    pme: str
    minutos: int
    categoria: str


def ler(texto: str) -> list[Bloco]:
    leitor = csv.reader(io.StringIO(texto))
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise RegistoInvalido("registo vazio") from None
    if tuple(cabecalho) != COLUNAS:
        raise RegistoInvalido(f"colunas {cabecalho}, esperava {list(COLUNAS)} e nenhuma outra")
    blocos = []
    for numero, linha in enumerate(leitor, start=2):
        if not any(linha):
            continue
        if len(linha) != len(COLUNAS):
            raise RegistoInvalido(f"linha {numero}: {len(linha)} colunas, esperava {len(COLUNAS)}")
        dia, pme, minutos, categoria = linha
        try:
            data = dt.date.fromisoformat(dia)
        except ValueError:
            raise RegistoInvalido(f"linha {numero}: dia invalido {dia!r}") from None
        if pme != SEM_PME and not _PME.match(pme):
            raise RegistoInvalido(f"linha {numero}: pme e P01..P99 ou '-', veio {pme!r}")
        if not re.fullmatch(r"\d{1,4}", minutos) or not 0 < int(minutos) <= MINUTOS_MAXIMOS:
            raise RegistoInvalido(f"linha {numero}: minutos entre 1 e {MINUTOS_MAXIMOS}, veio {minutos!r}")
        if categoria not in CATEGORIAS:
            raise RegistoInvalido(f"linha {numero}: categoria fora de {sorted(CATEGORIAS)}")
        blocos.append(Bloco(data, pme, int(minutos), categoria))
    return blocos


def por_pme(blocos: list[Bloco], inicio: dt.date, fim: dt.date) -> dict[str, dict[str, int]]:
    """Minutos e incidentes por PME nos dias `[inicio, fim]`; `-` e o nao atribuido."""
    saida: dict[str, dict[str, int]] = {}
    for bloco in blocos:
        if not inicio <= bloco.dia <= fim:
            continue
        linha = saida.setdefault(bloco.pme, {"minutos": 0, "incidentes": 0})
        linha["minutos"] += bloco.minutos
        linha["incidentes"] += bloco.categoria == "incidente"
    return saida

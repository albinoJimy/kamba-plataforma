"""As fontes contaveis do conjunto, lidas da arvore.

Uma contagem escrita em prosa nao e uma fonte: e uma copia. A fonte e o sitio
onde as coisas estao e se podem contar — as linhas `| KAM-NNN |` do §4 do
`specs/INDICE.md`, os blocos `## KAM-NNN` dos epics, os ficheiros de
`specs/tickets/`, as entradas de ADR do §8 do `docs/tecnica/00`, os anexos de
`docs/tecnica/evidencia/`. Este modulo le as fontes; nao le prosa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: O backlog mestre. As linhas de ticket do §4 sao a fonte do total.
INDICE = 'specs/INDICE.md'
#: O documento onde vivem os ADRs canonicos (§8).
ARQUITECTURA = 'docs/tecnica/00_Arquitectura_Solucao.md'
#: Os anexos de evidencia.
EVIDENCIA = 'docs/tecnica/evidencia'
#: Onde vivem os blocos de ticket: os epics, e os ficheiros por ticket do
#: EPIC-01 (KAM-155).
EPICS = 'specs/EPIC-*.md'
TICKETS = 'specs/tickets'

_LINHA_DE_TICKET = re.compile(r'^\| KAM-(\d+) \|', re.M)
_BLOCO = re.compile(r'^## KAM-(\d+) ', re.M)
_ADR = re.compile(r'ADR-(\d{3})')
_EPIC_DO_FICHEIRO = re.compile(r'^EPIC-(\d+)')


@dataclass(frozen=True)
class Fontes:
    """Os numeros que a arvore da, com o comando que os reproduz ao lado."""

    tickets: int
    blocos: int
    adrs: int
    adrs_locais: int
    anexos: int
    epics: int
    #: `{'EPIC-01': 43, 'EPIC-02': 13, ...}` — blocos de cada epic.
    por_epic: dict[str, int] = field(default_factory=dict)

    def comandos(self) -> dict[str, str]:
        """Como se reproduz cada numero, para a mensagem de erro servir."""
        return {
            'tickets': f"grep -cE '^\\| KAM-[0-9]+ \\|' {INDICE}",
            'blocos': f"grep -chE '^## KAM-[0-9]+ ' {EPICS} + ls {TICKETS}/KAM-*.md | wc -l",
            'ADRs': f"grep -oE 'ADR-[0-9]{{3}}' {ARQUITECTURA} | sort -u | wc -l",
            'ADRs locais': 'ls docs/adr/ADR-L*.md | wc -l',
            'anexos': f'ls {EVIDENCIA}/E*.md | wc -l',
            'epics': f'ls {EPICS} | wc -l',
        }


def epic_do_ficheiro(rel: str) -> str | None:
    """`EPIC-07` para um ficheiro de epic; `EPIC-01` para um ficheiro de ticket.

    Os ficheiros de `specs/tickets/` sao do EPIC-01 por construcao (KAM-155): e
    o unico epic que os tem. Saber o epic de um ficheiro e o que permite aceitar
    «sao 11 tickets» dentro do EPIC-04 sem o confundir com o total.
    """
    if rel.startswith(f'{TICKETS}/'):
        return 'EPIC-01'
    nome = rel.rsplit('/', 1)[-1]
    m = _EPIC_DO_FICHEIRO.match(nome)
    return f'EPIC-{int(m.group(1)):02d}' if m else None


def ler(raiz: Path) -> Fontes:
    """Conta tudo o que ha para contar, uma vez."""
    indice = (raiz / INDICE).read_text(encoding='utf-8')
    tickets = len(_LINHA_DE_TICKET.findall(indice))

    por_epic: dict[str, int] = {}
    for f in sorted(raiz.glob(EPICS)):
        epic = epic_do_ficheiro(f.relative_to(raiz).as_posix())
        if epic is None:
            continue
        por_epic[epic] = len(_BLOCO.findall(f.read_text(encoding='utf-8')))
    # O EPIC-01 tem um ficheiro por ticket, e o proprio ficheiro do epic nao
    # tem blocos nenhuns desde o KAM-155: a sua conta sao os ficheiros.
    por_epic['EPIC-01'] = len(list((raiz / TICKETS).glob('KAM-*.md')))

    arquitectura = (raiz / ARQUITECTURA).read_text(encoding='utf-8')
    return Fontes(
        tickets=tickets,
        blocos=sum(por_epic.values()),
        adrs=len(set(_ADR.findall(arquitectura))),
        adrs_locais=len(list((raiz / 'docs/adr').glob('ADR-L*.md'))),
        anexos=len(list((raiz / EVIDENCIA).glob('E*.md'))),
        epics=len(list(raiz.glob(EPICS))),
        por_epic=por_epic,
    )

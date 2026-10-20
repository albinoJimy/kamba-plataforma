"""Encontra as contagens escritas em prosa e confronta-as com a fonte.

Tres decisoes de desenho, todas elas por o contrario ja ter custado:

1. **Le uma zona, nao o ficheiro todo.** Uma linha de «Controlo de versoes» e
   uma seccao «Verificacao dos Criterios de Aceitacao» registam o que era
   verdade **entao**. Corrigi-las falsearia o registo, e e por isso que nao se
   leem. O mesmo vale para o que esta dentro de cercas de codigo, onde vivem
   comandos e saidas de execucao.
2. **A fonte depende de onde esta escrito.** «Sao 11 tickets» dentro do
   `EPIC-04` fala dos tickets desse epic; a mesma frase no `INDICE` fala do
   total. Um numero passa se for **um dos dois** que a arvore conta — o total ou
   o do epic onde esta. Se nao for nenhum, esta errado, e nao ha terceira
   leitura possivel.
3. **A classe de grandeza esta fechada.** `tickets`, `blocos ## KAM-NNN`, `ADRs`,
   `anexos de evidencia`, `epics`. Nao se adivinha «quantos» a partir de
   qualquer numero seguido de um substantivo: isso enchia o gate de falsos
   positivos e a lista de excepcoes de ruido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .fontes import Fontes, epic_do_ficheiro

#: Linha de uma tabela de controlo de versoes: `| 1.14 | Outubro 2026 | ... |`.
VERSAO = re.compile(r'^\|\s*\d+\.\d+\s*\|')
#: O titulo de uma seccao de verificacao de criterios, em qualquer nivel.
VERIFICACAO = re.compile(r'^#{2,6}\s+Verificação d')
CABECALHO = re.compile(r'^#{1,6}\s')
CERCA = re.compile(r'^\s*```')

#: As grandezas e o padrao que as reconhece. O numero e sempre o grupo 1.
#:
#: **A classe esta fechada, e duas ficaram deliberadamente de fora:**
#:
#: - **blocos.** Neste conjunto, «N blocos» e quase sempre uma **medicao**
#:   registada por um ticket («143 blocos, 8 falhas»), e nao uma contagem
#:   derivada. Medicoes sao historia, e verifica-las obrigava a uma excepcao por
#:   cada uma. O numero de blocos continua a ser conferido contra o backlog
#:   mestre pelo *gate* 3c (KAM-138), que e onde pertence.
#: - **anexos de evidencia.** No conjunto escrevem-se por extenso («cinco
#:   anexos»), e este gate le digitos. Numeros por extenso sao uma limitacao
#:   declarada, nao um esquecimento.
#:
#: O *lookbehind* recusa tambem o hifen: `KAM-158 tickets` nao e uma
#: contagem de 158 tickets, e o numero de um identificador nunca e «quantos».
PADROES: dict[str, re.Pattern[str]] = {
    'tickets': re.compile(r'(?<![\w.-])(\d{1,4})\s+tickets?\b', re.I),
    'ADRs': re.compile(r'(?<![\w.-])(\d{1,4})\s+ADRs?\b'),
    'epics': re.compile(r'(?<![\w.-])(\d{1,4})\s+epics?\b', re.I),
}

#: Onde se procura. Os ficheiros de `.claude/` ficam de fora: a *skill* nao e
#: documento do conjunto e tem contagens proprias (e foi o KAM-130 a decidi-lo).
PADROES_DE_FICHEIRO = ('specs/*.md', 'specs/tickets/*.md', 'docs/**/*.md', 'README.md')

#: Pastas que ficam de fora do corpus, pela mesma razao por que nao se leem as
#: zonas de historia: sao **registos datados**. Uma analise adversarial mede o
#: que era verdade no dia em que correu; a evidencia de um ticket registra o que
#: se mediu no PR que o entregou. Corrigir-lhes um numero falsearia o registo, e
#: deixa-las no corpus obrigava a declarar uma excepcao por cada medicao que o
#: conjunto ja fez.
PASTAS_DE_REGISTO = ('docs/analises/', 'docs/evidencia/')


@dataclass(frozen=True)
class Achado:
    """Uma contagem escrita, com o que a fonte diz."""

    ficheiro: str
    linha: int
    grandeza: str
    escrito: int
    aceitaveis: tuple[int, ...]
    excerto: str

    @property
    def bate(self) -> bool:
        return self.escrito in self.aceitaveis

    def __str__(self) -> str:
        quais = ' ou '.join(str(x) for x in self.aceitaveis)
        return (f'{self.ficheiro}:{self.linha}: {self.grandeza} — está escrito '
                f'{self.escrito}, a fonte dá {quais}')


def aceitaveis(grandeza: str, rel: str, linha: str, fontes: Fontes) -> tuple[int, ...]:
    """Os numeros que a arvore sustenta para esta grandeza, neste ficheiro."""
    if grandeza == 'tickets':
        # Duas leituras legitimas, e nao ha terceira: o total do backlog, ou o
        # do epic onde a frase esta escrita («sao 11 tickets», no EPIC-04).
        valores = [fontes.tickets]
        epic = epic_do_ficheiro(rel)
        if epic and epic in fontes.por_epic:
            valores.append(fontes.por_epic[epic])
        return tuple(dict.fromkeys(valores))
    if grandeza == 'ADRs':
        # «ADRs locais» sao os `ADR-L###` de `docs/adr/`, outra populacao.
        if re.search(r'ADRs?\s+locais|ADR-L', linha):
            return (fontes.adrs_locais,)
        return (fontes.adrs,)
    if grandeza == 'epics':
        return (fontes.epics,)
    raise AssertionError(f'grandeza sem fonte declarada: {grandeza}')


def varrer_ficheiro(caminho: Path, raiz: Path, fontes: Fontes,
                    excepcoes: tuple[str, ...] = ()) -> list[Achado]:
    """As contagens vivas de um ficheiro, fora das zonas de historia."""
    rel = caminho.relative_to(raiz).as_posix()
    out: list[Achado] = []
    em_verificacao = em_cerca = False
    for numero, linha in enumerate(caminho.read_text(encoding='utf-8').split('\n'), 1):
        if CERCA.match(linha):
            em_cerca = not em_cerca
            continue
        if em_cerca:
            continue
        if VERIFICACAO.match(linha):
            em_verificacao = True
            continue
        if CABECALHO.match(linha):
            em_verificacao = False
        if em_verificacao or VERSAO.match(linha):
            continue
        if any(e in linha for e in excepcoes):
            continue
        for grandeza, padrao in PADROES.items():
            for m in padrao.finditer(linha):
                out.append(Achado(
                    ficheiro=rel, linha=numero, grandeza=grandeza,
                    escrito=int(m.group(1)),
                    aceitaveis=aceitaveis(grandeza, rel, linha, fontes),
                    excerto=linha.strip()[:160],
                ))
    return out


def ficheiros(raiz: Path, padroes=PADROES_DE_FICHEIRO) -> list[Path]:
    """Os ficheiros a varrer, sem repetidos e por ordem de nome."""
    if isinstance(padroes, str):
        padroes = (padroes,)
    vistos: dict[Path, None] = {}
    for padrao in padroes:
        for f in raiz.glob(padrao):
            # **Relativo a raiz, e nao `f.parts`.** A exclusao e do `.claude/`
            # *do repositorio*; sobre o caminho absoluto, ela apagava o corpus
            # inteiro de qualquer arvore que viva **dentro** de uma pasta com
            # esse nome — e e exactamente onde os worktrees do Claude Code
            # vivem (`.claude/worktrees/<nome>`). O gate corria sobre zero
            # ficheiros, dava zero contagens vivas, e so nao passou por verde
            # porque a guarda das grandezas sem ocorrencia o apanhou. No CI
            # nunca se via: o caminho do runner nao tem `.claude`.
            rel = f.relative_to(raiz)
            if '.claude' in rel.parts or 'node_modules' in rel.parts:
                continue
            if rel.as_posix().startswith(PASTAS_DE_REGISTO):
                continue
            vistos[f] = None
    return sorted(vistos, key=lambda f: f.as_posix())


def varrer_arvore(raiz: Path, fontes: Fontes, excepcoes: tuple[str, ...] = (),
                  padroes=PADROES_DE_FICHEIRO) -> list[Achado]:
    out: list[Achado] = []
    for f in ficheiros(raiz, padroes):
        out.extend(varrer_ficheiro(f, raiz, fontes, excepcoes))
    return out

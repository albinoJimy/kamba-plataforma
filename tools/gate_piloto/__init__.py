"""Gerador do pacote de evidência do gate do Piloto (KAM-110).

Quatro módulos, e nenhum deles decide:

    registo    lê as nove linhas do `Registo_Hipoteses.md` (esquema do KAM-100)
    entradas   lê o resumo do piloto, num esquema fechado (a interface com o KAM-109)
    regras     o estado efectivo de cada hipótese, a matriz de `14` §6, a paragem
               total e a Definition-of-Done do Piloto (Carta §5), item a item
    pacote     escreve o `Gate_Piloto.md` a partir dos três

**A decisão é do fundador e dos três papéis** (bloco KAM-110, «Detalhes
Técnicos»: o Claude Code «não escolhe nem recomenda a decisão»). O que o pacote
impede é o contrário: que uma hipótese sem dados saia `confirmada`, que uma
falha fique sem a linha de `14` §6 que lhe cabe, e que um número de pista entre
no pacote sem ter sido o fundador a escrevê-lo.
"""

from __future__ import annotations

__all__ = ["entradas", "pacote", "registo", "regras"]

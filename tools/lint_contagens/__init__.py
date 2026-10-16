"""Contagens escritas em prosa, confrontadas com a fonte que as conta.

«N tickets», «N blocos `## KAM-NNN`», «N ADRs», «N anexos de evidencia», «N
epics» — cada um destes numeros deriva de um sitio onde as coisas estao e se
podem contar. Escrito a mao num segundo sitio, deixa de acompanhar: aconteceu
quatro vezes neste repositorio (dividas ~~19~~, 26, 30 e o §1 do `INDICE`), e
quatro vezes se corrigiu a mao.

Este modulo le as fontes e as contagens, e recusa a que nao bate. **Nao le
zonas de historia** — uma linha de «Controlo de versoes» e uma seccao de
verificacao de criterios registam o que era verdade entao, e corrigi-las
falsearia o registo.
"""

from .fontes import Fontes, ler
from .scan import Achado, PADROES, varrer_arvore, varrer_ficheiro

__all__ = ['Achado', 'Fontes', 'PADROES', 'ler', 'varrer_arvore', 'varrer_ficheiro']

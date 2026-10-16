"""Caminhos dentro de blocos `### Handoff para Claude Code`.

Um bloco de *handoff* fala a um processo cujo `cwd` e a raiz do repositorio
(`specs/01_Engineering_Standards_e_Handoff.md` §5, decidido no KAM-145). Os
caminhos dentro desse bloco sao, por isso, relativos a raiz. Um `../docs/...`
ali aponta para fora da arvore, e um nome de ficheiro sem directorio nao
resolve de posicao nenhuma.

Fora desses blocos esta regra nao se aplica: a referencia de documento para
documento continua relativa a posicao do ficheiro (a convencao do KAM-128), e
este modulo nao a le.
"""

from .scan import Achado, DEFEITOS, varrer_arvore, varrer_ficheiro

__all__ = ['Achado', 'DEFEITOS', 'varrer_arvore', 'varrer_ficheiro']

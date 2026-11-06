"""Os codigos de erro da Meta que este spike trata (KAM-100).

Modulo proprio, e **nao importa nada**, por uma razao pratica: o `extrair.py` e
o `tabela.py` precisam os dois do 2593109, e cada um deles tinha a sua copia — o
que e a forma exacta de duas constantes divergirem. Quem as queira ler nao paga
nenhuma dependencia: o `tabela.py` corre sem o `kamba_core`, que o `registo.py`
exige, e isso importa porque o operador pode querer so a tabela.

E o espelho de `tools/meta-sim/src/codigos.ts`, que e onde o repositorio ja
registava a mesma distincao entre o que e CONFIRMADO e o que nao e.
"""

from __future__ import annotations

#: «O cliente nao partilhou historico.» CONFIRMADO em fonte primaria
#: (`docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §2; `docs/tecnica/01` §4.4).
#:
#: Caso **normal** pela Meta, e nao uma falha — mas so conta como exito de H3 se
#: o dono recusou partilhar, o que e uma afirmacao da folha do operador e nao
#: destes eventos.
SEM_HISTORICO = 2_593_109

"""O condutor de TypeScript da suite de isolamento, e a ponte para ele.

Duas metades, e a fronteira entre elas e um ficheiro JSON:

```text
rotas.ts   corre em `node`, ataca as aplicacoes Hono em processo pelo
           `app.request()` e escreve o relatorio
ponte.py   arranca o `node` (ou a imagem oficial, quando nao ha `node`) e
           devolve esse relatorio ja descodificado
```

Nenhuma das duas decide se ha achado: isso e das baterias em
`tools/isolamento/baterias/`, que leem o relatorio e passam-no pelo oraculo. A
separacao e de proposito — o Python nao importa Hono, e o `node` nao sabe o que
e um canario.
"""

from __future__ import annotations

from .ponte import GRUPOS, CondutorFalhou, SemContentor, SemNodeNemDocker, correr

__all__ = [
    "GRUPOS",
    "CondutorFalhou",
    "SemContentor",
    "SemNodeNemDocker",
    "correr",
]

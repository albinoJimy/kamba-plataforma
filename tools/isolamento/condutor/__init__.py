"""O condutor de TypeScript da suite de isolamento, e a ponte para ele.

Duas metades, e a fronteira entre elas e um ficheiro JSON:

```text
../tests/condutor/rotas.ts   corre em `node`, ataca as aplicacoes Hono em
                             processo pelo `app.request()` e escreve o relatorio
ponte.py                     arranca o `node` (ou a imagem oficial, quando nao
                             ha `node`) e devolve esse relatorio descodificado
```

**O `rotas.ts` nao vive nesta pasta, e a razao e medida.** Ele e andaime de
ensaio — corre-se por `node <ficheiro> <grupo> <saida>`, conduzido do Python, e
nenhum teste de TypeScript o carrega —, mas o `ci/thresholds.yaml` classifica
**por caminho**: o padrao `*/isolamento/*` do estrato `critico` apanhava-o, e um
ficheiro do universo sem medicao nenhuma entra com as suas linhas no
denominador e zero no numerador. Medido no *gate* 4 do commit `6212517`: 1310
linhas levaram o estrato `critico` de **94,23% a 88,07%**, contra um minimo de
90. O repositorio ja tem a convencao para esta especie de ficheiro — o
`packages/core-ts/tests/x11_conduzir.ts`, conduzido pelo `make x11`, diz na
propria *docstring* que vive em `tests/` por nao ser um teste —, e o
`**/tests/**` dos `excluidos` ja a exprime. O criterio do portao **nao** se
tocou; mudou-se o sitio do ficheiro novo.

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

"""lint_refs — gate 3: lint de referencias cruzadas (KAM-002).

Falha se o repositorio citar um `KAM-NNN` que nao esta no backlog mestre, um
`ADR-NNN` que nao esta em `docs/tecnica/00` §8, ou um `D#` que nao esta em §13.3.

## Porque isto e mais difícil do que uma regex

O conjunto documental tem ~11 800 ocorrencias de `KAM-\\d{3}`, ~3 600 de
`ADR-\\d{3}` e ~2 400 de `D\\d{1,2}`. Um `(KAM|ADR)-\\d{3}|\\bD\\d+\\b` sobre esse
texto erra nos dois sentidos, e cada erro tem um custo diferente:

**Falsos positivos** — o gate fica vermelho por nada, e um gate em que ninguem
confia e um gate que alguem desliga:

| Forma | Exemplo real | Porque nao e uma referencia |
|---|---|---|
| dias | `D+30`, `D0`, `D60` | prazos, nao decisoes |
| intervalo de outro doc | `D1–D9` em `docs/exploracao/05` §6.1 | enumeracao local |
| divergencias do KAM-111 | `D-01`…`D-12` | outra serie, com travessao |
| ADRs locais | `ADR-L001` | sequencia separada (`docs/adr/README.md`) |
| placeholders | `KAM-NNN`, `ADR-NNN`, `D#` | a forma, nao uma referencia |

**Falsos negativos** — o gate passa e a referencia quebrada fica:

| Forma | Exemplo real | O que uma regex ingenua perde |
|---|---|---|
| unidos sem prefixo | `KAM-007/008/009/022` | apanha `KAM-007`, perde os outros tres |
| intervalos | `KAM-001–012`, `ADR-001 a ADR-019` | perde o interior do intervalo |

Este modulo trata as duas classes explicitamente, e cada decisao esta num teste.

## Ambito do varrimento

Varre os ficheiros **seguidos pelo git** (`git ls-files`), nao o diff.

- O diff torna o gate nao-determinista: o mesmo commit passa ou falha conforme a
  base com que e comparado, e apodrecimento pre-existente nunca aparece.
- `git ls-files` resolve tambem os *worktrees*: `.claude/worktrees/*` sao copias
  completas do repositorio, ignoradas pelo git mas visiveis a qualquer
  `os.walk`, e cada uma traz o seu proprio `KAM-999`.
"""

__all__ = ["main"]

from .cli import main

"""lint_arch — linter de arquitectura do monorepo KAMBÁ (KAM-001).

Verifica tres coisas, por esta ordem de importancia:

1. **Lista de bloqueio** (`tools/blocklist.yaml`): nenhum manifesto do repositorio
   declara uma dependencia que um ADR canonico proibe.
2. **Convencoes** (`tools/conventions.json`): mensagens de commit e nomes de ramo
   conformes ao §5 de `specs/01_Engineering_Standards_e_Handoff.md`.
3. **Estrutura**: a arvore que o KAM-001 fixa existe e cada servico tem
   `src/`, `tests/` e `Dockerfile`.

**Depende apenas da biblioteca padrao do Python, por desenho.** A verificacao da
lista de bloqueio tem de poder correr *antes* de qualquer `pnpm install` ou
`pip install`: um linter que precisasse de dependencias instaladas para dizer que
uma dependencia e proibida chegaria sempre tarde (`docs/tecnica/08` §4.8).
"""

__all__ = ["main"]

from .cli import main

"""Row-level security por tenant: o unico sitio onde a politica se escreve.

Toda a revisao que crie uma tabela com `tenant_id` chama `enable_tenant_rls`.
Quem se esquecer e apanhado pelo teste de catalogo X-05 do gate 6, que falha o
build se uma tabela com `tenant_id` nao tiver `ENABLE`, `FORCE` e politica.

A politica e a do `docs/tecnica/08` §3.3, com o nome que esse documento e o
ticket usam (`tenant_iso`; o `docs/tecnica/03` §5.5 chama-lhe
`tenant_isolamento` — divergencia registada no dicionario §3.2, emenda 1.5):

    USING      (<coluna> = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (<coluna> = NULLIF(current_setting('app.tenant_id', true), '')::uuid)

Tres propriedades, e as tres sao testadas contra um PostgreSQL real:

- **Sem contexto, zero linhas.** `current_setting(..., true)` devolve NULL se a
  variavel nunca foi definida, e `''` depois de um `SET LOCAL` de outra
  transaccao ter expirado; o `NULLIF` reduz os dois a NULL, e `coluna = NULL`
  nao e verdadeiro para linha nenhuma.
- **Contexto invalido e erro, nao linhas.** Um valor que nao seja um UUID
  rebenta no `::uuid`. Falha fechada pelo lado ruidoso.
- **`FORCE` vincula tambem o dono.** Sem ele, `kamba_migrator` — dono das
  tabelas — via tudo.
"""

from __future__ import annotations

import re

from alembic import op

POLITICA = "tenant_iso"
VARIAVEL = "app.tenant_id"

_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")


def _validar(*identificadores: str) -> None:
    """Os nomes entram em SQL por interpolacao: so passam identificadores simples."""
    for identificador in identificadores:
        if not _IDENTIFICADOR.match(identificador):
            raise ValueError(f"identificador invalido para RLS: {identificador!r}")


def predicado(coluna: str = "tenant_id") -> str:
    _validar(coluna)
    return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid"


def enable_tenant_rls(
    tabela: str, coluna: str = "tenant_id", schema: str = "platform"
) -> None:
    """`ENABLE` + `FORCE` + politica `tenant_iso` (USING e WITH CHECK)."""
    _validar(tabela, coluna, schema)
    alvo = f"{schema}.{tabela}"
    op.execute(f"ALTER TABLE {alvo} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {alvo} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLITICA} ON {alvo} "
        f"USING ({predicado(coluna)}) WITH CHECK ({predicado(coluna)})"
    )


def disable_tenant_rls(tabela: str, schema: str = "platform") -> None:
    """O inverso exacto, para o `downgrade`."""
    _validar(tabela, schema)
    alvo = f"{schema}.{tabela}"
    op.execute(f"DROP POLICY {POLITICA} ON {alvo}")
    op.execute(f"ALTER TABLE {alvo} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {alvo} DISABLE ROW LEVEL SECURITY")

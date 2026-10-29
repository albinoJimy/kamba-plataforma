"""Row-level security por tenant: o unico sitio onde a politica se escreve.

Toda a revisao que crie uma tabela com `tenant_id` chama `enable_tenant_rls`.
Quem se esquecer e apanhado pelo teste de catalogo X-05 do gate 6, que falha o
build se uma tabela com `tenant_id` nao tiver `ENABLE`, `FORCE` e politica.

A politica e a do `docs/tecnica/08` §3.3, com o nome que esse documento, o
ticket e o dicionario §3.2 usam: `tenant_iso`. O `docs/tecnica/03` §5.5
chamava-lhe `tenant_isolamento`, divergencia registada na emenda 1.5 e
**paga pelo KAM-139** — este docstring era o ultimo sitio do repositorio a
anuncia-la depois de ela deixar de existir:

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

## `SECURITY DEFINER` **nao** contorna o `FORCE` (KAM-052, medido)

Quem escrever um *trigger* ou uma funcao que precise de **ler** uma tabela com
`FORCE` le isto primeiro, porque custou uma corrida do *gate* 8 a descobrir e nao
esta escrito em sitio nenhum do conjunto.

`SECURITY DEFINER` troca o `current_user` pelo **dono** da funcao — que numa
revisao e o `kamba_migrator` — e a RLS aplica-se pelo `current_user`. O
`kamba_migrator` e `NOBYPASSRLS`, e o `FORCE` vincula o dono da tabela: a funcao
ve **zero linhas**, sem contexto de tenant. Medido no `assert_beneficiary` da
`0027`, que recusava **todas** as cobrancas com «conta inexistente» (`23503` onde
se esperava `23514`).

**A saida obvia nao existe aqui.** Ter a funcao dona por um papel com
`BYPASSRLS` — o `kamba_batch` e o unico — exige que o `kamba_migrator` possa
`SET ROLE` para ele, e o `db/bootstrap.py` **revoga activamente** toda a pertenca
entre papeis («nenhum dos papeis pertence a outro papel, nem tem membros»). E uma
barreira deliberada e nao se afrouxa para isto.

O que resta, e o que a `0027` faz: **`SECURITY INVOKER`**, e desenhar a funcao
para que cada chamador veja o que precisa de ver. Na pratica isso funciona porque
os papeis que escrevem sao os certos — o `kamba_app` ve as linhas do seu tenant,
e um processo de plataforma corre como `kamba_batch`, que tem `BYPASSRLS`. O que
se perde e **precisao de mensagem**: para um chamador sujeito a RLS, «a linha e
de outro tenant» e indistinguivel de «a linha nao existe», e a funcao tem de
recusar nos dois e dizer as duas possibilidades em vez de afirmar uma.

Credores imediatos: o **KAM-053** (ledger `payment_events`, que escreve por
funcao `SECURITY DEFINER`) e o **KAM-055** (`payment_charges`, que liga o
`assert_beneficiary`).
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

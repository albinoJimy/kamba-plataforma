"""Indice de pesquisa por tenant: o esquema idx e o idx.candidatos (KAM-061).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## O que esta revisao cria

O esquema `idx` do `docs/tecnica/05` §4.1, §4.2 e §4.4, e a funcao do §6.2:

* as extensoes `vector`, `pg_trgm` e `unaccent` (com `IF NOT EXISTS`);
* `idx.f_unaccent` e a configuracao de pesquisa textual `idx.kamba_pt`;
* `idx.search_doc`, **sem indice ANN** (PROP-IDX-1), e `idx.termo_canonico`,
  as duas com RLS `FORCE` por `tenant_id`;
* `idx.candidatos`, `SECURITY INVOKER`: sem `app.tenant_id` devolve zero linhas.

## O SQL nao esta aqui, e e de proposito

Esta em `db/indice.py`, declarado em `ci/canon-lint.yaml` como modulo auxiliar
de migracao — o mesmo estatuto do `db/custo.py`. Os ensaios de base de dados
(`db/tests_produtos/test_indice.py`) importam o mesmo modulo em vez de copiarem o DDL, e o *gate*
3b le o SQL seguindo o corpo de `indice.criar()`. **Mudar o esquema e uma
revisao nova**; esta nao se reescreve.

## O `downgrade`

Larga tudo o que criou, sem `CASCADE`, **menos as extensoes**: criadas com
`IF NOT EXISTS`, esta revisao nao sabe se foi ela quem as criou (a nota do
`db/indice.py`).
"""

from __future__ import annotations

from alembic import op  # noqa: F401 — o `indice` executa por ele

import indice

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indice.criar()


def downgrade() -> None:
    indice.remover()

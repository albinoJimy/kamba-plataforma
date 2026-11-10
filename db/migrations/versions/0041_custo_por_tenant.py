"""Custo diario por tenant: a vista v_tenant_cost_daily (KAM-081).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## O que esta revisao cria

Uma vista e nada mais: `platform.v_tenant_cost_daily`, o custo por tenant, dia
e rubrica (criterio 1 do KAM-081), com `security_invoker = true` e `SELECT` so
para o `kamba_batch`. Nenhuma tabela, nenhuma coluna, nenhuma funcao.

## O SQL nao esta aqui, e e de proposito

Esta em `db/custo.py`, declarado em `ci/canon-lint.yaml` como modulo auxiliar
de migracao — o mesmo estatuto do `db/rls.py`. Os ensaios de base de dados
(`db/tests/test_custo_schema.py`) importam o mesmo modulo em vez de copiarem a
vista, e o *gate* 3b le o SQL seguindo o corpo de `custo.criar_vista()`.

**O preco desta escolha, dito:** uma revisao deve descrever sempre a mesma
coisa, e um modulo partilhado pode mudar depois de ela fundir. A regra que o
compensa e a da tarifa: **mudar a vista e uma revisao nova**, que faz
`DROP VIEW` e chama a versao nova; esta revisao nao se reescreve. O `CREATE
VIEW` falha se a vista ja existir, pelo que uma alteracao em `db/custo.py` sem
revisao nova nao muda bases ja migradas — so as novas, e o gate 8 ve-o.

## O `downgrade`

`DROP VIEW` sem `CASCADE`: nada depende desta vista, e se alguma coisa passar a
depender, o `downgrade` deve falhar em vez de a levar atras.
"""

from __future__ import annotations

from alembic import op  # noqa: F401 — o `custo` executa por ele

import custo

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    custo.criar_vista()


def downgrade() -> None:
    custo.remover_vista()

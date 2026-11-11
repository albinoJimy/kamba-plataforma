"""KYC K1 automatico: onboarding_case e kyc_check (KAM-087).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## O que esta revisao cria

* a `platform.onboarding_case`, que o KAM-086 desenhou e o KAM-093 deixou com
  credor (o `preflight`), com a `fase` resolvida pela emenda do dicionario que
  acompanha esta revisao;
* a `platform.kyc_check`, uma verificacao por documento do K1.

As duas com RLS `FORCE` pela `tenant_iso`, sobre o `tenant_id` pre-alocado do
caso. O SQL esta em `db/kyc.py`, declarado em `ci/canon-lint.yaml` como modulo
auxiliar de migracao; ver la a nota de cada decisao.

## O `downgrade`

Larga as duas tabelas e a funcao do *trigger*, sem `CASCADE`: se alguma coisa
passar a depender delas, o `downgrade` deve falhar em vez de a levar atras.
"""

from __future__ import annotations

from alembic import op  # noqa: F401 — o `kyc` e o `rls` executam por ele

import kyc
import rls

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    kyc.criar()
    rls.enable_tenant_rls("onboarding_case")
    rls.enable_tenant_rls("kyc_check")
    kyc.conceder()


def downgrade() -> None:
    rls.disable_tenant_rls("kyc_check")
    rls.disable_tenant_rls("onboarding_case")
    kyc.remover()

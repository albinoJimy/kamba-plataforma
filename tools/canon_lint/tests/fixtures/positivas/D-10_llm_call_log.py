"""Fixture POSITIVA do gate 3b — D-10 (KAM-111).

`dat.llm_call_log`, dicionario §3.29.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dat.llm_call_log (
          tenant_id  uuid NOT NULL,
          criado_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

"""Fixture NEGATIVA do gate 3b — D-10 (KAM-111).

O nome de `docs/tecnica/09` §9.3 antes da emenda.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.llm_calls (
          tenant_id  uuid NOT NULL,
          criado_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

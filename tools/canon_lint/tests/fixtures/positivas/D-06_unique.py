"""Fixture POSITIVA do gate 3b — D-06 (KAM-111).

A unicidade inclui a conta (`account_id`), como em `docs/tecnica/04` §6.2.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.payment_events (
          tenant_id   uuid NOT NULL,
          provider    text NOT NULL,
          account_id  uuid NOT NULL,
          referencia  text NOT NULL,
          seq         integer NOT NULL,
          CONSTRAINT payment_events_uq UNIQUE (provider, account_id, referencia, seq)
        )
        """
    )

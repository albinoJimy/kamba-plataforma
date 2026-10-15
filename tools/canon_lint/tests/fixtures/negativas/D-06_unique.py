"""Fixture NEGATIVA do gate 3b — D-06 (KAM-111).

A unicidade que o dicionario §3.4 proibe por extenso: o ledger e
append-only e a mesma referencia tem varias linhas.

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
          CONSTRAINT payment_events_uq UNIQUE (provider, referencia)
        )
        """
    )

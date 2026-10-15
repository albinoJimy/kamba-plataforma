"""Fixture NEGATIVA do gate 3b — D-04 (KAM-111).

O `boolean` que nao diz como o evento foi autenticado.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.payment_events (
          tenant_id         uuid NOT NULL,
          provider          text NOT NULL,
          referencia        text NOT NULL,
          callback_hmac_ok  boolean NOT NULL
        )
        """
    )

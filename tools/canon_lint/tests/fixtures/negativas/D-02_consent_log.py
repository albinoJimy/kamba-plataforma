"""Fixture NEGATIVA do gate 3b — D-02 (KAM-111).

Uma das tres tabelas de consentimento que os documentos tinham.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.consent_log (
          tenant_id   uuid NOT NULL,
          contact_id  uuid NOT NULL,
          purpose     text NOT NULL,
          accepted    boolean NOT NULL
        )
        """
    )

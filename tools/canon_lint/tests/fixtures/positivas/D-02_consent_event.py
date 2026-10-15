"""Fixture POSITIVA do gate 3b — D-02 (KAM-111).

`consent_event`, com os campos da nota do dicionario §3.1.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.consent_event (
          tenant_id      uuid NOT NULL,
          contact_id     uuid NOT NULL,
          purpose        text NOT NULL,
          text_version   text NOT NULL,
          accepted       boolean NOT NULL,
          canal          text NOT NULL,
          evidence_hash  bytea NOT NULL,
          ocorrido_em    timestamptz NOT NULL DEFAULT now()
        )
        """
    )

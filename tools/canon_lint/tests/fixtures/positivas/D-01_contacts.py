"""Fixture POSITIVA do gate 3b — D-01 (KAM-111).

As duas tabelas com a forma do dicionario §3.1.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.contacts (
          contact_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id   uuid NOT NULL REFERENCES platform.tenants (id),
          criado_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE platform.contact_endpoints (
          contact_id  uuid NOT NULL REFERENCES platform.contacts (contact_id),
          tipo        text NOT NULL,
          bsuid_hmac  bytea,
          bsuid_enc   bytea,
          phone_enc   bytea,
          dek_id      uuid NOT NULL
        )
        """
    )

"""Fixture NEGATIVA do gate 3b — D-01 (KAM-111).

A versao de `contacts` de `docs/tecnica/01` §6.2 antes da emenda: BSUID em
claro na tabela de contactos. O dicionario §3.1 fixa `contacts` +
`contact_endpoints`, sem telefone nem BSUID em claro.

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
          bsuid       text,
          criado_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )

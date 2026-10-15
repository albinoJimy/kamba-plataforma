"""Fixture NEGATIVA do gate 3b — D-08 (KAM-111).

O `tenants.estado` de `docs/tecnica/03` §5.2 antes da emenda: quatro
estados, sem `restrito`.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.tenants (
          id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          estado  text NOT NULL DEFAULT 'onboarding'
                  CHECK (estado IN ('onboarding','ativo','suspenso','encerrado'))
        )
        """
    )

"""${message}

Revisao: ${up_revision}
Anterior: ${down_revision | comma,n}
Criada: ${create_date}

Uma revisao por PR. `upgrade` e `downgrade` sao os dois obrigatorios
(`docs/tecnica/03` §11); uma revisao que so acrescenta diz, no `downgrade`,
porque e que reverter e seguro.
"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}

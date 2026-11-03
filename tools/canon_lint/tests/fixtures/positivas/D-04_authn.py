"""Fixture POSITIVA do gate 3b — D-04 (KAM-111).

`authn_ok` + `authn_method`, com o dominio do dicionario §3.4 — **quatro**
valores desde a emenda 1.53 (KAM-053), que decidiu a pergunta que o
`docs/tecnica/04` §6.2 lhe deixou escrita: o `sistema` fica, com o dominio
dos factos de ciclo de vida que ninguem autentica, e nunca autentica um
`pagamento_confirmado`. Com tres valores esta fixture passava a dar `[regra]`
«falta: sistema» — medido.

Nao e uma migracao: nunca e aplicada. Tem a forma de uma revisao Alembic
porque e essa a forma que o `canon_lint` le.
"""

from alembic import op


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.payment_events (
          tenant_id     uuid NOT NULL,
          provider      text NOT NULL,
          referencia    text NOT NULL,
          authn_ok      boolean NOT NULL,
          authn_method  text NOT NULL
                        CHECK (authn_method IN ('hmac','manual','consulta','sistema'))
        )
        """
    )

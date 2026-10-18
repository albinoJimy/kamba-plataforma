"""Fixture POSITIVA do gate 3b — D-02 (KAM-111).

`consent_event`, com os campos da nota do dicionario §3.1.

**E com o `CHECK` do dominio de `purpose`, desde o KAM-159.** Ate la o §3.1
escrevia as finalidades em prosa, o exportador nao as lia como dominio, e esta
fixture passava sem fechar nada. Hoje o dominio existe, e o gate exige o que
sempre exigiu a todos os outros: um dominio fechado impoe-se por
`CHECK (coluna IN (…))` ou por um ENUM, **nesta revisao** — uma coluna que
aceita qualquer texto nao se torna fechada por o dicionario dizer que e.

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
          purpose        text NOT NULL
                         CONSTRAINT consent_event_purpose_ck
                         CHECK (purpose IN (
                           'transacao', 'atendimento', 'marketing',
                           'analytics_agregado', 'melhoria_servico',
                           'sugestoes_patrocinadas', 'partilha_loja',
                           'partilha_parceiros', 'partilha_estafeta',
                           'notificacao_dono')),
          text_version   text NOT NULL,
          accepted       boolean NOT NULL,
          canal          text NOT NULL,
          evidence_hash  bytea NOT NULL,
          ocorrido_em    timestamptz NOT NULL DEFAULT now()
        )
        """
    )

"""Fixture POSITIVA do gate 3b — D-02 (KAM-111).

`consent_event`, com os campos da nota do dicionario §3.1.

**E com o `CHECK` do dominio de `purpose`, desde o KAM-159.** Ate la o §3.1
escrevia as finalidades em prosa, o exportador nao as lia como dominio, e esta
fixture passava sem fechar nada. Hoje o dominio existe, e o gate exige o que
sempre exigiu a todos os outros: um dominio fechado impoe-se por
`CHECK (coluna IN (…))` ou por um ENUM, **nesta revisao** — uma coluna que
aceita qualquer texto nao se torna fechada por o dicionario dizer que e.

**E com o `CHECK` do `canal`, desde o KAM-022, e a historia e a mesma outra
vez.** Ate la o §3.1 nomeava o campo `canal` e nao dizia que valores aceita; a
emenda 1.28 declarou-o `∈ {whatsapp}` no §3.19, e com isso uma revisao que crie
esta coluna sem o fechar deixou de ser canonica. Esta fixture e **positiva**: ela
encarna o que o gate deve aceitar, e por isso tem de acompanhar o canon. Foi o
`canon_lint canario` que o disse — nao o `check` —, e e exactamente a pergunta
que ele existe para fazer: «o lint passou a recusar o que e canonico?». Aqui nao:
o que e canonico mudou.

O dominio tem **um** valor de proposito. O segundo transporte entra por migracao
e nao por insercao em silencio.

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
          canal          text NOT NULL
                         CONSTRAINT consent_event_canal_ck
                         CHECK (canal IN ('whatsapp')),
          evidence_hash  bytea NOT NULL,
          ocorrido_em    timestamptz NOT NULL DEFAULT now()
        )
        """
    )

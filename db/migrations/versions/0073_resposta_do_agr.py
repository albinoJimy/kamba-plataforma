"""Resposta do AGR: a tabela agent_replies e as subscricoes do agent.replied (KAM-224).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

1. **A `platform.agent_replies`**, a resposta que um turno do AGR quer dar: o
   texto ja validado pelo *renderer*, os botoes (pares `{id, titulo}`, o que o
   `Corpo` do Outbound exige; o titulo resolve-o o AGR, que e quem tem os
   rotulos), o canal
   (`whatsapp` ou `painel`) e a chave idempotente do envio (`turn_id:seq` no
   caminho normal, `{draft_id}:send` no concierge, `{handoff_id}:msg` no
   *handoff*). **O texto vive aqui e nao no evento**: o lint de PII do *gate* 7
   recusa um campo `texto` num *payload* (`tools/contract_diff/pii.py`, a
   regra do `docs/tecnica/06` §7.1, «sem PII crua em eventos»), e uma resposta
   a um cliente pode levar o nome dele. O evento leva o `reply_id`, e os
   consumidores leem a linha por ele. E a forma da decisao 1 do fundador de
   2026-11-19 (bloco do KAM-217): uma fonte persistida que se le por
   identificador.
2. **A idempotencia do produtor e a restricao `UNIQUE (tenant_id, chave)`.** O
   AGR insere com `ON CONFLICT DO NOTHING RETURNING` e so emite o
   `agent.replied` quando a linha nasceu, na **mesma** transaccao: um turno
   repetido pelo *shim* calcula a mesma chave, nao insere, e nao emite outra
   vez. Linha e evento ficam atomicos.
3. **Duas linhas em `platform.evt_subscricoes`**, as do `registry/outbound.yaml`
   e do `registry/painel.yaml`: o consumidor `outbound` (o `worker-canal`, que
   instancia o `Saida` do KAM-015) e o `painel` (o processo de lote do
   `onboarding-web`). Os dois subscrevem o mesmo tipo e cada um aplica so o seu
   canal. As linhas so as escreve o dono das tabelas, e em producao nao ha
   escritor: e a forma da `0052`, da `0061` e da `0067`. O `exige_ordem` e
   `false` (o tipo nao e `payment.`), e o `versao_max` e 2.

## Privilegios

O `kamba_app` e o produtor (o AGR, pela `evt_emitir`, que ja e dele desde a
`0004`) e os dois consumidores. Insere a identidade e o conteudo da resposta e
muda **so** o `entregue_at`, que o consumidor escreve quando a entrega se fez.
Nao ha `DELETE` para ninguem: a purga e a da classe `conversas` da retencao.

## O `downgrade`

Apaga as duas subscricoes **e so estas**, pela chave primaria, e larga a
tabela. **O `upgrade` nao usa `ON CONFLICT`** nas subscricoes, pela razao da
`0052`: uma linha ja presente com a mesma chave e uma subscricao que esta
revisao nao criou, e o `downgrade` apaga-la-ia.

## Numero

`0073` **provisoria**, sobre a `0072` do KAM-123: e a vaga de migracao do lote
13. Quem fundir em segundo renumera.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None

TABELA = "platform.agent_replies"
TENANTS = "platform.tenants"
CONTACTOS = "platform.contacts"
CONVERSAS = "platform.conversations"

#: Os dois canais da resposta. Iguais ao `CANAIS` de
#: `services/agr/src/kamba_agr/saida.py` e ao `CANAIS_DA_RESPOSTA` de
#: `packages/core-ts/src/resposta/contrato.ts`.
CANAIS = ("whatsapp", "painel")

#: O mesmo, **por extenso**: o *gate* 3b le o SQL das revisoes sem as executar.
CANAIS_SQL = "'whatsapp', 'painel'"

#: O tecto de botoes da Meta (CONFIRMADO, `E1` §5): o mesmo `MAXIMO_DE_BOTOES`
#: do Outbound e o `MAX_BOTOES` do *renderer*.
MAXIMO_DE_BOTOES = 3

#: O tecto do corpo de uma mensagem de texto da Cloud API.
MAXIMO_DO_TEXTO = 4096

#: O que o `kamba_app` insere: a identidade e o conteudo da resposta. O
#: `reply_id` e o `criado_at` vem do `DEFAULT`, e o `entregue_at` nasce vazio.
INSERT_DA_APP = (
    "tenant_id",
    "chave",
    "contact_id",
    "conversation_id",
    "canal",
    "texto",
    "botoes",
    "turno_iniciado_em",
)

#: O que o `kamba_app` muda: so o instante da entrega. O conteudo de uma
#: resposta nao muda depois de emitida.
UPDATE_DA_APP = ("entregue_at",)

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`, na forma da `0052`.
LINHAS = (
    ("outbound", "agent.replied", "2", "atendimento", "false"),
    ("painel", "agent.replied", "2", "atendimento", "false"),
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABELA} (
          reply_id          uuid CONSTRAINT agent_replies_pkey PRIMARY KEY
                            DEFAULT gen_random_uuid(),
          tenant_id         uuid NOT NULL,
          chave             text NOT NULL
                            CONSTRAINT agent_replies_chave_ck
                            CHECK (char_length(chave) BETWEEN 1 AND 300),
          contact_id        uuid NOT NULL,
          conversation_id   uuid NOT NULL,
          canal             text NOT NULL
                            CONSTRAINT agent_replies_canal_ck
                            CHECK (canal IN ({CANAIS_SQL})),
          texto             text NOT NULL
                            CONSTRAINT agent_replies_texto_ck
                            CHECK (char_length(texto) BETWEEN 1 AND {MAXIMO_DO_TEXTO}),
          botoes            jsonb NOT NULL DEFAULT '[]'::jsonb
                            CONSTRAINT agent_replies_botoes_ck
                            CHECK (jsonb_typeof(botoes) = 'array'
                                   AND jsonb_array_length(botoes) <= {MAXIMO_DE_BOTOES}),
          turno_iniciado_em timestamptz,
          criado_at         timestamptz NOT NULL DEFAULT now(),
          entregue_at       timestamptz,
          CONSTRAINT agent_replies_chave_uq UNIQUE (tenant_id, chave),
          CONSTRAINT agent_replies_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES {TENANTS} (id),
          CONSTRAINT agent_replies_contact_fk FOREIGN KEY (tenant_id, contact_id)
            REFERENCES {CONTACTOS} (tenant_id, contact_id),
          CONSTRAINT agent_replies_conversation_fk FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES {CONVERSAS} (tenant_id, id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX agent_replies_conversa_idx ON {TABELA} "
        "(tenant_id, conversation_id, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {TABELA} IS "
        "'A resposta de um turno do AGR (KAM-224): o texto validado, os botoes e o "
        "canal. O evento agent.replied leva o reply_id e nunca o texto. Idempotente "
        "por (tenant_id, chave); sem DELETE para ninguem.'"
    )

    rls.enable_tenant_rls("agent_replies")
    op.execute(f"REVOKE ALL ON {TABELA} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_APP)}), "
        f"UPDATE ({', '.join(UPDATE_DA_APP)}) ON {TABELA} TO kamba_app"
    )

    for consumer, tipo, versao_max, finalidade, exige_ordem in LINHAS:
        op.execute(
            f"""
            INSERT INTO platform.evt_subscricoes
                   (consumer, tipo, versao_max, finalidade, exige_ordem, activo)
            VALUES ('{consumer}', '{tipo}', {versao_max}, '{finalidade}', {exige_ordem}, true)
            """
        )


def downgrade() -> None:
    for consumer, tipo, _versao_max, _finalidade, _exige_ordem in LINHAS:
        op.execute(
            f"""
            DELETE FROM platform.evt_subscricoes
             WHERE consumer = '{consumer}' AND tipo = '{tipo}'
            """
        )
    rls.disable_tenant_rls("agent_replies")
    op.execute(f"DROP TABLE {TABELA}")

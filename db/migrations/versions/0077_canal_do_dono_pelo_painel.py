"""Canal do dono pelo painel: agent_messages e owner_phone_changes (KAM-223).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

1. **A `platform.agent_messages`**, a fonte persistida da mensagem que entra no
   AGR (decisao 1 do fundador de 2026-11-19, opcao A, bloco do KAM-217). O
   painel grava o texto do dono, o `agent_invocation` leva o `message_id` e
   **nunca** o corpo (a decisao do KAM-186 mantem-se), e o AGR le a linha pelo
   identificador, com o tenant, o contacto e a conversa da invocacao. E a
   saida (b) do KAM-186, e serve tambem o WhatsApp: o `canal` diz de onde veio.
   Sem `UPDATE` nem `DELETE` para ninguem: uma mensagem nao muda depois de
   escrita, e a purga e a da classe `conversas` da retencao.
2. **A `platform.owner_phone_changes`**, a troca de telefone do dono com a
   prova de posse (decisao 3 do fundador, opcao C). Ate aqui os pedidos e o
   desafio do OTP viviam na memoria do processo, e um reinicio perdia-os; a
   espera de 72 h (*proposta*) sem o codigo do numero antigo **tem** de
   sobreviver a um reinicio. **Sem telefone em claro**: o HMAC do numero novo e
   o do numero que o dono diz ser o antigo, com o *pepper* da inscricao. O
   desafio do numero que esta a ser provado vive na propria linha, e as quatro
   colunas dele andam juntas (`owner_phone_changes_desafio_ck`). E guarda o
   canal do dono novo (`owner_channel_wa`, KAM-216), calculado no pedido com o
   numero em claro, que a conclusao passa a `platform.definir_dono` com o papel.
3. **Uma troca viva por tenant**: o indice unico parcial
   `owner_phone_changes_viva_uq` sobre os estados `pedida` e `pendente`. E ele que
   faz a segunda replica nao abrir uma segunda troca, e a conclusao e o
   cancelamento sao condicionais ao estado de onde partem.

## Privilegios

* `agent_messages`: o `kamba_app` le e insere as cinco colunas do conteudo. O
  `onboarding-web` escreve-a pela segunda ligacao dele (`ONBOARDING_APP_DB_URL`),
  e o AGR le-a pela sua.
* `owner_phone_changes`: so o `kamba_identity`, que e o papel da troca e o unico
  com `EXECUTE` na `platform.definir_dono` (revisao `0070`) — a troca de estado e
  a porta correm na mesma transaccao. Le, insere a identidade do pedido e muda o
  estado, o prazo, o contacto, o HMAC do antigo e o desafio. Sem `DELETE`.

As duas com RLS `FORCE` pelo `app.tenant_id`.

## O `downgrade`

Larga as duas tabelas, e com elas o que la estiver: as mensagens do painel e as
trocas pendentes. **Uma troca pendente perde-se** — o papel nao mudou, e o dono
volta a pedir. Nao ha linhas noutras tabelas a desfazer.

## Numero

`0077`, sobre a `0076` do KAM-221 (fundida em `19247ace`): e a vaga de migracao
do lote 14.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

MENSAGENS = "platform.agent_messages"
TROCAS = "platform.owner_phone_changes"
TENANTS = "platform.tenants"
CONTACTOS = "platform.contacts"
CONVERSAS = "platform.conversations"

#: Os canais da mensagem. Iguais ao `CANAIS` da `0073` (resposta do AGR), ao
#: `CANAIS_DA_MENSAGEM` de `packages/core-ts/src/dono/conversa.ts` e ao do
#: `services/agr/src/kamba_agr/mensagens.py`.
CANAIS = ("whatsapp", "painel")
CANAIS_SQL = "'whatsapp', 'painel'"

#: Os estados de uma troca. Iguais ao `ESTADOS_DA_TROCA` de
#: `packages/core-ts/src/dono/troca.ts`. **Por extenso** no SQL: o *gate* 3b le
#: as revisoes sem as executar.
ESTADOS = ("pedida", "pendente", "feita", "cancelada", "expirada")
ESTADOS_SQL = "'pedida', 'pendente', 'feita', 'cancelada', 'expirada'"

#: O tecto do texto de uma mensagem da Cloud API, e o da `agent_replies`.
MAXIMO_DO_TEXTO = 4096

#: O que o `kamba_app` insere na mensagem. O `message_id` e o `criado_at` vem do
#: `DEFAULT`.
INSERT_DA_MENSAGEM = ("tenant_id", "contact_id", "conversation_id", "canal", "texto")

#: O que o `kamba_identity` insere numa troca: a identidade do pedido.
INSERT_DA_TROCA = ("tenant_id", "pedido", "telefone_hmac", "owner_channel_wa", "prazo")

#: O que o `kamba_identity` muda numa troca. O `tenant_id`, o `pedido`, o
#: `telefone_hmac`, o `owner_channel_wa` e o `criado_at` nao mudam depois do
#: pedido: o canal e o do numero pedido, e o codigo prova esse numero.
UPDATE_DA_TROCA = (
    "estado",
    "prazo",
    "contact_id",
    "antigo_hmac",
    "desafio_chave",
    "desafio_hmac",
    "desafio_expira_em",
    "desafio_tentativas",
    "decidido_at",
)

#: A forma de um HMAC em hexadecimal (SHA-256).
FORMA_DO_HMAC = "'^[0-9a-f]{64}$'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {MENSAGENS} (
          message_id      uuid CONSTRAINT agent_messages_pkey PRIMARY KEY
                          DEFAULT gen_random_uuid(),
          tenant_id       uuid NOT NULL,
          contact_id      uuid NOT NULL,
          conversation_id uuid NOT NULL,
          canal           text NOT NULL
                          CONSTRAINT agent_messages_canal_ck
                          CHECK (canal IN ({CANAIS_SQL})),
          texto           text NOT NULL
                          CONSTRAINT agent_messages_texto_ck
                          CHECK (char_length(texto) BETWEEN 1 AND {MAXIMO_DO_TEXTO}),
          criado_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT agent_messages_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES {TENANTS} (id),
          CONSTRAINT agent_messages_contact_fk FOREIGN KEY (tenant_id, contact_id)
            REFERENCES {CONTACTOS} (tenant_id, contact_id),
          CONSTRAINT agent_messages_conversation_fk FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES {CONVERSAS} (tenant_id, id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX agent_messages_conversa_idx ON {MENSAGENS} "
        "(tenant_id, conversation_id, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {MENSAGENS} IS "
        "'A mensagem que entra no AGR (KAM-223): o agent_invocation leva o message_id e "
        "nunca o texto. Sem UPDATE nem DELETE para ninguem.'"
    )
    rls.enable_tenant_rls("agent_messages")
    op.execute(f"REVOKE ALL ON {MENSAGENS} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_MENSAGEM)}) ON {MENSAGENS} TO kamba_app"
    )

    op.execute(
        f"""
        CREATE TABLE {TROCAS} (
          change_id          uuid CONSTRAINT owner_phone_changes_pkey PRIMARY KEY
                             DEFAULT gen_random_uuid(),
          tenant_id          uuid NOT NULL,
          pedido             text NOT NULL
                             CONSTRAINT owner_phone_changes_pedido_ck
                             CHECK (char_length(pedido) BETWEEN 1 AND 200),
          telefone_hmac      text NOT NULL
                             CONSTRAINT owner_phone_changes_telefone_hmac_ck
                             CHECK (telefone_hmac ~ {FORMA_DO_HMAC}),
          owner_channel_wa   boolean NOT NULL,
          estado             text NOT NULL DEFAULT 'pedida'
                             CONSTRAINT owner_phone_changes_estado_ck
                             CHECK (estado IN ({ESTADOS_SQL})),
          prazo              timestamptz NOT NULL,
          contact_id         uuid,
          antigo_hmac        text
                             CONSTRAINT owner_phone_changes_antigo_hmac_ck
                             CHECK (antigo_hmac ~ {FORMA_DO_HMAC}),
          desafio_chave      text,
          desafio_hmac       text
                             CONSTRAINT owner_phone_changes_desafio_hmac_ck
                             CHECK (desafio_hmac ~ {FORMA_DO_HMAC}),
          desafio_expira_em  timestamptz,
          desafio_tentativas integer
                             CONSTRAINT owner_phone_changes_desafio_tentativas_ck
                             CHECK (desafio_tentativas >= 0),
          criado_at          timestamptz NOT NULL DEFAULT now(),
          decidido_at        timestamptz,
          -- O desafio e um so: as quatro colunas andam juntas.
          CONSTRAINT owner_phone_changes_desafio_ck CHECK (
            (desafio_chave IS NULL AND desafio_hmac IS NULL
             AND desafio_expira_em IS NULL AND desafio_tentativas IS NULL)
            OR (desafio_chave IS NOT NULL AND desafio_hmac IS NOT NULL
                AND desafio_expira_em IS NOT NULL AND desafio_tentativas IS NOT NULL)
          ),
          -- Uma troca pendente ou feita sabe para que contacto vai o papel.
          CONSTRAINT owner_phone_changes_contacto_ck CHECK (
            estado NOT IN ('pendente', 'feita') OR contact_id IS NOT NULL
          ),
          CONSTRAINT owner_phone_changes_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES {TENANTS} (id),
          CONSTRAINT owner_phone_changes_contact_fk FOREIGN KEY (tenant_id, contact_id)
            REFERENCES {CONTACTOS} (tenant_id, contact_id)
        )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX owner_phone_changes_viva_uq ON {TROCAS} (tenant_id) "
        "WHERE estado IN ('pedida', 'pendente')"
    )
    op.execute(
        f"COMMENT ON TABLE {TROCAS} IS "
        "'A troca de telefone do dono com prova de posse (KAM-223): o codigo do numero "
        "antigo, ou 72 h pendente. Sem telefone em claro; uma troca viva por tenant.'"
    )
    rls.enable_tenant_rls("owner_phone_changes")
    op.execute(f"REVOKE ALL ON {TROCAS} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_TROCA)}), "
        f"UPDATE ({', '.join(UPDATE_DA_TROCA)}) ON {TROCAS} TO kamba_identity"
    )


def downgrade() -> None:
    rls.disable_tenant_rls("owner_phone_changes")
    op.execute(f"DROP TABLE {TROCAS}")
    rls.disable_tenant_rls("agent_messages")
    op.execute(f"DROP TABLE {MENSAGENS}")

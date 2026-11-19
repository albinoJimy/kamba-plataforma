"""Orcamento expresso: quote_requests e as transicoes impostas por trigger (KAM-123).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero

`0072` sobre a `0071` (KAM-204), provisoria: quem funde em segundo renumera. Os
ensaios descobrem-na pelo *glob* `*_orcamento_expresso.py` e leem o
`down_revision` daqui.

## O que esta revisao cria

| Objecto | Para que serve |
|---|---|
| `platform.quote_requests` | um pedido de orcamento de um produto `sob_consulta`, do pedido do cliente ao envio da proposta |
| `quote_requests_transicao()` | o gatilho `BEFORE UPDATE` que impoe as transicoes de `estado` e congela os estados finais |
| `quote_requests_abertos_idx` | a lista dos pendentes do dono (`pedido`, `respondido`, `aguarda_janela`) |
| `quote_requests.conversation_id` | a conversa do cliente onde o pedido nasceu: e por ela que a proposta volta, pelo Outbound |
| `quote_requests_repeticao_idx` | a pergunta do criterio 1: «ha um pedido aberto deste contacto e deste `sku` nos ultimos dez minutos?» |

## O que a tabela nao tem, e e criterio

**Nenhum `nif`, `serie` nem numeracao fiscal** (criterio 7): a plataforma nao e
software validado pela AGT (E5 B10), e uma proposta e «Orcamento — nao e
factura». A referencia `ORC-…` que o cliente le deriva do `quote_id` por codigo
(`kamba_agr.orcamento.regras.referencia_interna`) e nao e coluna: uma coluna
com uma sequencia por tenant era a forma de uma serie.

**Nenhum total.** O `valor_minor` e o valor que o dono digitou, e a `quantidade`
e so informacao para o dono: nao ha coluna onde um `valor_minor * quantidade`
caiba, e nenhum `CHECK` relaciona as duas (criterio 3).

**Sem `DELETE` para ninguem**: um pedido fecha-se pelo estado (`expirado`,
`cancelado`), e o que foi enviado fica.

## As transicoes sao da base

O `kamba_app` tem `UPDATE` por coluna no estado e na resposta, e o gatilho
recusa (`23514`) o que o `TRANSICOES` de `kamba_agr/orcamento/regras.py` nao
tem — ha ensaio que confronta as duas listas. Os estados finais (`enviado`,
`expirado`, `cancelado`) nao mudam, nem em coluna nenhuma: uma proposta
`enviada` com o valor trocado depois era uma proposta que o cliente nunca leu.
O valor, a validade e as condicoes so mudam numa passagem a `respondido` (o
dono a responder, ou a corrigir antes do botao).

## Sem `SECURITY DEFINER`

A funcao do gatilho e `SECURITY INVOKER` (a omissao), com `search_path` fixo
pela razao da `0029`. Nao ha porta de escrita: os privilegios por coluna e o
gatilho chegam, e a RLS `FORCE` pela `tenant_iso` faz o resto. O
`ci/secdef_allowlist.yaml` nao muda.

## O `downgrade`

Larga o gatilho, a funcao e a tabela. **Sem recusa**: um pedido de orcamento e
uma conversa comercial a meio, e o registo do que foi enviado e o evento
`quote.sent` no outbox, que a descida nao toca. Uma recusa com linhas punha
esta revisao entre as que travam as descidas da suite.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

TABELA = "platform.quote_requests"
TENANTS = "platform.tenants"
CONTACTOS = "platform.contacts"
CONVERSAS = "platform.conversations"

#: Os seis estados do criterio 2. Iguais ao `ESTADOS` do `regras.py`.
ESTADOS = ("pedido", "respondido", "enviado", "aguarda_janela", "expirado", "cancelado")

#: Os abertos: os que o dono ve, e os unicos que expiram ou se cancelam.
ABERTOS = ("pedido", "respondido", "aguarda_janela")

#: As transicoes, iguais ao `TRANSICOES` do `regras.py`.
TRANSICOES = (
    ("pedido", "respondido"),
    ("respondido", "respondido"),
    ("respondido", "enviado"),
    ("respondido", "aguarda_janela"),
    ("aguarda_janela", "enviado"),
    ("pedido", "expirado"),
    ("respondido", "expirado"),
    ("aguarda_janela", "expirado"),
    ("pedido", "cancelado"),
    ("respondido", "cancelado"),
    ("aguarda_janela", "cancelado"),
)

#: Os tres acima **por extenso**, e nao derivados: o *gate* 3b le o SQL das
#: revisoes sem as executar, e uma expressao nao se le. O ensaio
#: `services/agr/tests/test_orcamento.py` confronta os tuplos com o `regras.py`,
#: e o `db/tests/test_orcamento_schema.py` os literais com os tuplos.
ESTADOS_SQL = "'pedido', 'respondido', 'enviado', 'aguarda_janela', 'expirado', 'cancelado'"
ABERTOS_SQL = "'pedido', 'respondido', 'aguarda_janela'"
TRANSICOES_SQL = """
               (OLD.estado = 'pedido' AND NEW.estado IN ('respondido', 'expirado', 'cancelado'))
            OR (OLD.estado = 'respondido' AND NEW.estado IN
                 ('respondido', 'enviado', 'aguarda_janela', 'expirado', 'cancelado'))
            OR (OLD.estado = 'aguarda_janela' AND NEW.estado IN ('enviado', 'expirado', 'cancelado'))
"""

#: O que o `kamba_app` insere: a identidade do pedido. Um pedido nasce `pedido`
#: (o `DEFAULT`), sem valor: um `INSERT (valor_minor)` deixava-o nascer com
#: preco sem o dono o ter dado.
INSERT_DA_APP = ("tenant_id", "contact_id", "conversation_id", "sku", "quantidade")

#: O que o `kamba_app` muda: o estado e a resposta do dono. **Nunca** a
#: identidade (`quote_id`, `tenant_id`, `contact_id`, `conversation_id`, `sku`,
#: `quantidade`) nem o
#: `criado_at`, que e o relogio da janela de repeticao e da espera do dono.
UPDATE_DA_APP = (
    "estado", "valor_minor", "validade_ate", "condicoes", "respondido_at", "enviado_at",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABELA} (
          quote_id      uuid CONSTRAINT quote_requests_pkey PRIMARY KEY
                        DEFAULT gen_random_uuid(),
          tenant_id     uuid NOT NULL,
          contact_id    uuid NOT NULL,
          conversation_id uuid NOT NULL,
          sku           text NOT NULL
                        CONSTRAINT quote_requests_sku_ck
                        CHECK (char_length(sku) BETWEEN 1 AND 100),
          quantidade    integer
                        CONSTRAINT quote_requests_quantidade_ck
                        CHECK (quantidade IS NULL OR quantidade BETWEEN 1 AND 100000),
          estado        text NOT NULL DEFAULT 'pedido'
                        CONSTRAINT quote_requests_estado_ck
                        CHECK (estado IN ({ESTADOS_SQL})),
          valor_minor   bigint
                        CONSTRAINT quote_requests_valor_ck
                        CHECK (valor_minor IS NULL OR valor_minor > 0),
          currency      text NOT NULL DEFAULT 'AOA'
                        CONSTRAINT quote_requests_currency_ck CHECK (currency = 'AOA'),
          validade_ate  date,
          condicoes     text
                        CONSTRAINT quote_requests_condicoes_ck
                        CHECK (condicoes IS NULL OR char_length(condicoes) BETWEEN 1 AND 200),
          criado_at     timestamptz NOT NULL DEFAULT now(),
          respondido_at timestamptz,
          enviado_at    timestamptz,
          -- A resposta do dono e um todo: valor, validade e instante, ou nada.
          CONSTRAINT quote_requests_resposta_ck CHECK (
            (valor_minor IS NULL) = (validade_ate IS NULL)
            AND (valor_minor IS NULL) = (respondido_at IS NULL)
          ),
          -- Respondido, enviado ou a espera da janela: so com resposta.
          CONSTRAINT quote_requests_respondido_ck CHECK (
            estado NOT IN ('respondido', 'enviado', 'aguarda_janela')
            OR valor_minor IS NOT NULL
          ),
          -- O `enviado_at` e o `enviado` andam juntos.
          CONSTRAINT quote_requests_enviado_ck CHECK (
            (estado = 'enviado') = (enviado_at IS NOT NULL)
          ),
          CONSTRAINT quote_requests_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES {TENANTS} (id),
          CONSTRAINT quote_requests_contact_fk FOREIGN KEY (tenant_id, contact_id)
            REFERENCES {CONTACTOS} (tenant_id, contact_id),
          CONSTRAINT quote_requests_conversation_fk FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES {CONVERSAS} (tenant_id, id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX quote_requests_abertos_idx ON {TABELA} (tenant_id, criado_at) "
        f"WHERE estado IN ({ABERTOS_SQL})"
    )
    op.execute(
        f"CREATE INDEX quote_requests_repeticao_idx ON {TABELA} "
        "(tenant_id, contact_id, sku, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {TABELA} IS "
        "'Pedidos de orcamento de produtos sob_consulta (KAM-123). O dono fixa o valor; "
        "o sistema nunca o calcula. Sem numeracao fiscal: Orcamento, nao e factura. "
        "Transicoes de estado impostas por trigger; sem DELETE para ninguem.'"
    )

    op.execute(
        f"""
        CREATE FUNCTION platform.quote_requests_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.estado IN ('enviado', 'expirado', 'cancelado') THEN
            RAISE EXCEPTION 'quote_requests % e final: a linha nao muda', OLD.estado
              USING ERRCODE = '23514';
          END IF;
          IF NOT ({TRANSICOES_SQL}) THEN
            RAISE EXCEPTION 'transicao de quote_requests recusada: % -> %',
              OLD.estado, NEW.estado USING ERRCODE = '23514';
          END IF;
          IF NEW.estado <> 'respondido' AND (
               NEW.valor_minor IS DISTINCT FROM OLD.valor_minor
               OR NEW.validade_ate IS DISTINCT FROM OLD.validade_ate
               OR NEW.condicoes IS DISTINCT FROM OLD.condicoes
               OR NEW.respondido_at IS DISTINCT FROM OLD.respondido_at
          ) THEN
            RAISE EXCEPTION 'a resposta do dono so muda ao passar a respondido'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER quote_requests_transicao
          BEFORE UPDATE ON {TABELA}
          FOR EACH ROW EXECUTE FUNCTION platform.quote_requests_transicao()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.quote_requests_transicao() FROM PUBLIC")

    rls.enable_tenant_rls("quote_requests")
    op.execute(f"REVOKE ALL ON {TABELA} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_APP)}), "
        f"UPDATE ({', '.join(UPDATE_DA_APP)}) ON {TABELA} TO kamba_app"
    )


def downgrade() -> None:
    rls.disable_tenant_rls("quote_requests")
    op.execute(f"DROP TRIGGER quote_requests_transicao ON {TABELA}")
    op.execute("DROP FUNCTION platform.quote_requests_transicao()")
    op.execute(f"DROP TABLE {TABELA}")

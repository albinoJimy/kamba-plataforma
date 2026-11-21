"""Contacto da encomenda ao dono: order.contact_view e o audit_append ao kamba_identity (KAM-206).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

Duas coisas, e as duas sao a decisao do fundador de 2026-11-20 (opcao A do
bloco do KAM-206):

* alarga o dominio fechado `audit_log_action` (revisao `0006`, ultima alteracao
  na `0066`) com `order.contact_view` — o dono viu o contacto de uma encomenda,
  mascarado. Sao **vinte**. Nenhuma das dezanove o descrevia: o
  `access.conversation` e o acesso a uma conversa, e usa-lo aqui mentia;
* da ao `kamba_identity` **so** o `EXECUTE` no `audit_append` e o `INSERT` nas
  oito colunas que a funcao escreve. O papel e o unico que decifra o telefone
  (KAM-008), e a linha de auditoria escreve-se **na transaccao da decifra**: uma
  falha de uma desfaz a outra. Nao ganha `SELECT` no `audit_log`, nem na
  `audit_heads`, nem nada em mais tabela nenhuma — a cadeia continua a ser
  escrita pelo *trigger* `audit_encadear`, `SECURITY DEFINER`.

A linha leva `actor_type = 'owner'`, o `onboarding_id` do caso em `actor_id`,
`entity = 'order'`, o `order_id` em `entity_id` e o SHA-256 de
`order.contact_view\x1f<order_id>\x1f<estado>` em `payload_hash`. **Nem o
telefone nem a mascara**, nem resumidos.

## Numero provisorio

`0082` sobre a `0081` do KAM-215, a vaga que a coordenacao do lote 16 deu.

## Downgrade

Recusa se houver linhas de `audit_log` com a accao nova: o `audit_log` e
*append-only* e o dominio anterior nao as aceita. Senao, revoga as duas
concessoes e repoe o dominio da `0066` (dezanove).
"""

from __future__ import annotations

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: As colunas que o `audit_append` escreve (revisao `0006`). Copiadas e nao
#: importadas: uma revisao nao importa outra.
COLUNAS_DO_AUDIT_APPEND = (
    "tenant_id, actor_type, actor_id, action, entity, entity_id, turn_id, payload_hash"
)

#: A assinatura do `audit_append` (revisao `0006`).
ARGUMENTOS_DO_AUDIT_APPEND = "uuid, text, text, text, text, text, text, bytea"

#: O dominio da accao depois desta revisao: as dezanove da `0066` e a nova.
LITERAIS_DE_ACCAO_0082 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto', "
    "'trust.tecto', "
    "'secret.rotate', 'secret.revoke', "
    "'order.contact_view'"
)

#: O que o `downgrade` repoe: o dominio da `0066`.
LITERAIS_DE_ACCAO_0066 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto', "
    "'trust.tecto', "
    "'secret.rotate', 'secret.revoke'"
)


def _trocar_o_dominio(literais: str) -> None:
    """Troca o `CHECK` da accao, com `NO FORCE` a volta (a armadilha da `0038`)."""
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({literais}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _trocar_o_dominio(LITERAIS_DE_ACCAO_0082)
    op.execute(f"GRANT INSERT ({COLUNAS_DO_AUDIT_APPEND}) ON {AUDIT_LOG} TO kamba_identity")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.audit_append({ARGUMENTOS_DO_AUDIT_APPEND}) "
        "TO kamba_identity"
    )


def downgrade() -> None:
    """Desce, e **recusa** se o `audit_log` ja tem linhas de `order.contact_view`.

    A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e a
    guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`).
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log WHERE action = 'order.contact_view'"
        )
        .scalar_one()
    )
    if linhas:
        op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")
        raise RuntimeError(
            f"downgrade da 0082 recusado: ha {linhas} linha(s) de audit_log com "
            "accao order.contact_view e o dominio da 0066 nao as aceita. O audit_log "
            "e append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION platform.audit_append({ARGUMENTOS_DO_AUDIT_APPEND}) "
        "FROM kamba_identity"
    )
    op.execute(f"REVOKE INSERT ({COLUNAS_DO_AUDIT_APPEND}) ON {AUDIT_LOG} FROM kamba_identity")
    _trocar_o_dominio(LITERAIS_DE_ACCAO_0066)

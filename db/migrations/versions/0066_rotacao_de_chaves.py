"""Rotacao de chaves no audit_log: secret.rotate e secret.revoke (KAM-072).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

So uma coisa: alarga o dominio fechado `audit_log_action` (revisao `0006`,
ultima alteracao na `0048`) com as duas accoes do rotador do KAM-072:

* `secret.rotate` — uma versao nova de um segredo passou a actual (o inicio, a
  rotacao planeada e a de emergencia);
* `secret.revoke` — a versao anterior foi retirada do anel.

O criterio 7 do bloco e literal: «cada rotacao escreve no `audit_log` o
identificador e a hora, nunca o valor». A linha que o adaptador escreve
(`packages/core-ts/src/keyring/auditoria.ts`) tem `entity` = o identificador do
segredo, `entity_id` = a versao (`kid`) e `payload_hash` = o SHA-256 dos
metadados da accao. **Nem o valor nem um resumo dele** entram na linha.

A cadeia e a de plataforma (`tenant_id` nulo): um segredo e da plataforma, e
quem escreve essa cadeia e o `kamba_batch`, que tem `BYPASSRLS` e `EXECUTE` em
`audit_append` desde a `0006`. Nenhum privilegio novo.

## Numero provisorio

`0066` sobre `0065`, dados pelo orquestrador do lote (a `0062` a `0065` sao de
outros quatro tickets, por fundir). O numero final da-se na integracao.

## Downgrade

Recusa se houver linhas de `audit_log` com as duas accoes: o `audit_log` e
*append-only* e o dominio anterior nao as aceita. Senao, repoe o dominio da
`0048` (catorze).
"""

from __future__ import annotations

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: O dominio da accao depois desta revisao: as catorze da `0048` e as duas do
#: rotador. Copiado e nao importado: uma revisao nao importa outra.
LITERAIS_DE_ACCAO_0066 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'secret.rotate', 'secret.revoke'"
)

#: O que o `downgrade` repoe: o dominio da `0048`.
LITERAIS_DE_ACCAO_0048 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa'"
)


def _trocar_o_dominio(literais: str) -> None:
    """Troca o `CHECK` da accao.

    Com `NO FORCE` a volta, pela armadilha que a `0038` escreveu: a validacao
    das linhas existentes corre como o dono, e com `FORCE` o dono ve zero
    linhas.
    """
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
    _trocar_o_dominio(LITERAIS_DE_ACCAO_0066)


def downgrade() -> None:
    """Desce, e **recusa** se o `audit_log` ja tem linhas de rotacao.

    A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e a
    guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`).
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log "
            "WHERE action IN ('secret.rotate', 'secret.revoke')"
        )
        .scalar_one()
    )
    if linhas:
        op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")
        raise RuntimeError(
            f"downgrade da 0066 recusado: ha {linhas} linha(s) de audit_log com "
            "accao secret.* e o dominio da 0048 nao as aceita. O audit_log e "
            "append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    _trocar_o_dominio(LITERAIS_DE_ACCAO_0048)

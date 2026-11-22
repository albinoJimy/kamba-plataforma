"""Purga das operacionais, o motivo da retencao por parecer e a auditoria dos telefones (KAM-233).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

**Decisao do fundador de 2026-11-21 (Q3 = B).** A purga do off-boarding
(`libs/py-core/src/kamba_core/offboarding/purga.py`) passa a apagar as tabelas
operacionais da classe `relacao` que ficavam `sem_caminho`, e deixa o
`kyc_check` e o `fraud_signals` retidos, com o fundamento escrito. Tres coisas,
a terceira pelas decisoes Q2 = B (2026-11-21) e Q2b = A (2026-11-22):

1. **O `DELETE` do `kamba_batch`** em onze tabelas, e o `SELECT` so da coluna
   `tenant_id` nas seis em que ele nao lia nada — e a unica coluna que o
   `DELETE ... WHERE tenant_id = %s` da purga le. O `kamba_batch` tem
   `BYPASSRLS`, e um `SELECT` da tabela inteira dava-lhe as colunas pessoais
   (o pedido de orcamento, a marca, o conteudo) que a purga nunca precisa de ver.
   Nenhuma das onze tem gatilho de `DELETE`: medido contra a base em `head`
   (`pg_trigger`), os gatilhos delas sao todos de `INSERT` ou `UPDATE`.
2. **Um motivo novo no `purge_log`**, `branqueamento_sem_parecer`: a lei de
   prevencao do branqueamento pode pedir que a identificacao do cliente se
   guarde anos, e falta o parecer que o diga. O `kyc_check` e o `fraud_signals`
   ficam `retida` com ele, no `purge_log` e no certificado, ate o parecer
   chegar. Nenhum dos motivos que ja havia o dizia: `fiscal_sem_prazo` e o CGT,
   e `hold_*` e um *hold* legal posto por alguem.
3. **Uma accao nova em `audit_log.action`**, `privacy.telefones_exportados`
   (a vigesima primeira): o processo de lote decifrou os telefones de um
   contacto para o pacote do titular. Escreve-a o `kamba_identity`, pelo
   `audit_append` que a `0082` lhe deu, **na transaccao da decifra** (o `antes`
   do `lerEndpoints`). Nenhuma das vinte o descrevia: `order.contact_view` e o
   dono a ver um contacto mascarado, e `access.conversation` e o acesso a uma
   conversa. Sem concessao nova: o papel ja tem o `EXECUTE` e as oito colunas.

## O que fica de fora

O `onboarding_case` nao ganha `DELETE`: tres tabelas lhe apontam por FK sem
cascata — o `kyc_check` (retido por esta mesma decisao), o
`screening_decision` e o `review_case` (classes de prova, que esta purga nao
toca) — e um `DELETE` do caso falhava sempre. Continua `sem_caminho`, como
antes. As do cofre, o `owner_contacts` (sai depois da entrega do certificado),
o tenant e as contas de pagamento ficam como estavam.

## O `downgrade`

Tira o que o `upgrade` deu, tabela a tabela, e repoe o dominio do motivo da
`0042` e o da accao da `0082`. **Falha** se o `purge_log` ja tiver uma linha
com o motivo novo, ou o `audit_log` uma com a accao nova: os dois sao
*append-only*, e apagar a prova de uma retencao ou de uma decifra para poder
descer era pior do que nao descer.

## Numero

`0086`, sobre a `0085` do KAM-122: a vaga que a coordenacao do lote 18 deu ao
KAM-233 a 2026-11-21 (a fila e `0084` KAM-236, `0085` KAM-122, `0086` KAM-233).
"""

from __future__ import annotations

from alembic import op

revision = "0086"
down_revision = "0083"
branch_labels = None
depends_on = None

PAPEL_DE_LOTE = "kamba_batch"
PURGE_LOG = "platform.purge_log"

#: As seis em que o `kamba_batch` nao lia nada: `SELECT (tenant_id)` e `DELETE`.
ACCOES = "platform.owner_actions"
MUDANCAS_DE_TELEFONE = "platform.owner_phone_changes"
PEDIDOS_DE_ORCAMENTO = "platform.quote_requests"
MARCA = "platform.brand_profile"
CALENDARIO = "platform.content_calendar"
CONTEUDOS = "platform.content_items"

#: As cinco em que ele ja lia o `tenant_id`: so o `DELETE`. **A ingestao vem
#: para aqui**, e nao para as seis: o `kamba_batch` ja le dela o `id`, o
#: `tenant_id` e o `phash` desde o KAM-097 (a varredura da foto repetida), e o
#: `REVOKE SELECT (tenant_id)` do `downgrade` tirava-lhe uma coluna que esta
#: revisao nao deu. Achado pela matriz do `test_privilegios`.
INGESTOES = "platform.catalog_ingestions"
GATES = "platform.onboarding_gate"
TESTES = "platform.onboarding_smoke"
LISTA_DE_ESPERA = "platform.waitlist_entry"
FOTOS = "platform.image_jobs"

#: O dominio do motivo, por extenso: o *gate* 3b le a revisao sem a correr e
#: nao resolve um `", ".join(...)` (a licao da `0006` e da `0038`). O da `0042`,
#: e o de agora, com o motivo novo no fim.
MOTIVOS_DA_0042 = (
    "'fiscal_sem_prazo', 'fiscal_imutavel', 'hold_tenant', 'hold_contacto', "
    "'sem_caminho', 'particao_por_criar', 'erro'"
)
MOTIVOS = (
    "'fiscal_sem_prazo', 'fiscal_imutavel', 'hold_tenant', 'hold_contacto', "
    "'sem_caminho', 'particao_por_criar', 'erro', 'branqueamento_sem_parecer'"
)

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"
ACCAO_NOVA = "privacy.telefones_exportados"

#: O dominio da accao da `0082` (vinte), e o de agora, com a nova no fim. Por
#: extenso, pela razao dos motivos.
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
LITERAIS_DE_ACCAO = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto', "
    "'trust.tecto', "
    "'secret.rotate', 'secret.revoke', "
    "'order.contact_view', "
    "'privacy.telefones_exportados'"
)


def upgrade() -> None:
    _privilegios()
    _motivo()
    _trocar_a_accao(LITERAIS_DE_ACCAO)


def _trocar_a_accao(literais: str) -> None:
    """Troca o `CHECK` da accao, com `NO FORCE` a volta (a armadilha da `0038`, como a `0082`)."""
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


def _privilegios() -> None:
    """Uma instrucao por tabela, com o nome por extenso: o `canon_lint` le-as assim."""
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {ACCOES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {MUDANCAS_DE_TELEFONE} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {PEDIDOS_DE_ORCAMENTO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {MARCA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {CALENDARIO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {CONTEUDOS} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT DELETE ON {INGESTOES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT DELETE ON {GATES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT DELETE ON {TESTES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT DELETE ON {LISTA_DE_ESPERA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT DELETE ON {FOTOS} TO {PAPEL_DE_LOTE}")


def _motivo() -> None:
    op.execute(f"ALTER TABLE {PURGE_LOG} DROP CONSTRAINT purge_log_motivo_ck")
    op.execute(
        f"ALTER TABLE {PURGE_LOG} ADD CONSTRAINT purge_log_motivo_ck "
        f"CHECK (motivo IN ({MOTIVOS}))"
    )


def downgrade() -> None:
    # A accao primeiro, que e a ordem inversa. A contagem corre com o `FORCE`
    # desligado: com ele, o dono ve zero linhas e a guarda passava sempre (a
    # armadilha que o KAM-050 mediu na `0038`).
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log WHERE action = 'privacy.telefones_exportados'"
        )
        .scalar_one()
    )
    if linhas:
        op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")
        raise RuntimeError(
            f"downgrade da 0086 recusado: ha {linhas} linha(s) de audit_log com "
            f"accao {ACCAO_NOVA} e o dominio da 0082 nao as aceita. O audit_log e "
            "append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")
    _trocar_a_accao(LITERAIS_DE_ACCAO_0082)
    # O motivo a seguir. Sem `NOT VALID`: uma linha com o
    # motivo novo faz o `ADD CONSTRAINT` falhar, e a descida para (ver a nota).
    op.execute(f"ALTER TABLE {PURGE_LOG} DROP CONSTRAINT purge_log_motivo_ck")
    op.execute(
        f"ALTER TABLE {PURGE_LOG} ADD CONSTRAINT purge_log_motivo_ck "
        f"CHECK (motivo IN ({MOTIVOS_DA_0042}))"
    )
    op.execute(f"REVOKE DELETE ON {FOTOS} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE DELETE ON {LISTA_DE_ESPERA} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE DELETE ON {TESTES} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE DELETE ON {GATES} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE DELETE ON {INGESTOES} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {CONTEUDOS} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {CALENDARIO} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {MARCA} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {PEDIDOS_DE_ORCAMENTO} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {MUDANCAS_DE_TELEFONE} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {ACCOES} FROM {PAPEL_DE_LOTE}")

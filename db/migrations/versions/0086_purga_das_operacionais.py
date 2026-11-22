"""Purga das operacionais: DELETE do kamba_batch e o motivo da retencao por parecer (KAM-233).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

**Decisao do fundador de 2026-11-21 (Q3 = B).** A purga do off-boarding
(`libs/py-core/src/kamba_core/offboarding/purga.py`) passa a apagar as tabelas
operacionais da classe `relacao` que ficavam `sem_caminho`, e deixa o
`kyc_check` e o `fraud_signals` retidos, com o fundamento escrito. Duas coisas:

1. **O `DELETE` do `kamba_batch`** em onze tabelas, e o `SELECT` so da coluna
   `tenant_id` nas sete em que ele nao lia nada — e a unica coluna que o
   `DELETE ... WHERE tenant_id = %s` da purga le. O `kamba_batch` tem
   `BYPASSRLS`, e um `SELECT` da tabela inteira dava-lhe as colunas pessoais
   (o pedido de orcamento, a marca, o conteudo) que a purga nunca precisa de ver.
   Nenhuma das dez tem gatilho de `DELETE`: medido contra a base em `head`
   (`pg_trigger`), os gatilhos delas sao todos de `INSERT` ou `UPDATE`.
2. **Um motivo novo no `purge_log`**, `branqueamento_sem_parecer`: a lei de
   prevencao do branqueamento pode pedir que a identificacao do cliente se
   guarde anos, e falta o parecer que o diga. O `kyc_check` e o `fraud_signals`
   ficam `retida` com ele, no `purge_log` e no certificado, ate o parecer
   chegar. Nenhum dos motivos que ja havia o dizia: `fiscal_sem_prazo` e o CGT,
   e `hold_*` e um *hold* legal posto por alguem.

## O que fica de fora

O `onboarding_case` nao ganha `DELETE`: tres tabelas lhe apontam por FK sem
cascata — o `kyc_check` (retido por esta mesma decisao), o
`screening_decision` e o `review_case` (classes de prova, que esta purga nao
toca) — e um `DELETE` do caso falhava sempre. Continua `sem_caminho`, como
antes. As do cofre, o `owner_contacts` (sai depois da entrega do certificado),
o tenant e as contas de pagamento ficam como estavam.

## O `downgrade`

Tira o que o `upgrade` deu, tabela a tabela, e repoe o dominio do motivo da
`0042`. **Falha** se o `purge_log` ja tiver uma linha com o motivo novo: o
`purge_log` e *append-only* por privilegio, e apagar a prova de uma retencao
para poder descer era pior do que nao descer.

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

#: As sete em que o `kamba_batch` nao lia nada: `SELECT (tenant_id)` e `DELETE`.
ACCOES = "platform.owner_actions"
MUDANCAS_DE_TELEFONE = "platform.owner_phone_changes"
PEDIDOS_DE_ORCAMENTO = "platform.quote_requests"
MARCA = "platform.brand_profile"
CALENDARIO = "platform.content_calendar"
CONTEUDOS = "platform.content_items"
INGESTOES = "platform.catalog_ingestions"

#: As quatro em que ele ja lia a tabela: so o `DELETE`.
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


def upgrade() -> None:
    _privilegios()
    _motivo()


def _privilegios() -> None:
    """Uma instrucao por tabela, com o nome por extenso: o `canon_lint` le-as assim."""
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {ACCOES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {MUDANCAS_DE_TELEFONE} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {PEDIDOS_DE_ORCAMENTO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {MARCA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {CALENDARIO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {CONTEUDOS} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT (tenant_id), DELETE ON {INGESTOES} TO {PAPEL_DE_LOTE}")
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
    # O motivo primeiro, que e a ordem inversa. Sem `NOT VALID`: uma linha com o
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
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {INGESTOES} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {CONTEUDOS} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {CALENDARIO} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {MARCA} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {PEDIDOS_DE_ORCAMENTO} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {MUDANCAS_DE_TELEFONE} FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT (tenant_id), DELETE ON {ACCOES} FROM {PAPEL_DE_LOTE}")

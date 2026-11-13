"""A lista de efeitos por reaplicar da fila de revisao vive na base (KAM-198).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## A decisao que esta revisao executa

O fundador decidiu a 2026-11-13, opcao (A): **a marca de «efeito por aplicar»
de um caso de revisao e uma coluna da `review_case`**, e nao uma lista em
memoria. E o criterio 2 do KAM-198: a lista sobrevive a um reinicio.

A decisao e os efeitos de um caso nao sao uma transaccao (`reaplicarEfeitos` no
`packages/core-ts/src/revisao/servico.ts`): o caso fecha primeiro, e depois a
fase do onboarding, a decisao humana de screening e o aviso ao dono podem
falhar. Ate aqui quem sabia disso era o processo que viu o erro, numa lista em
memoria (`EfeitosPorReaplicarEmMemoria`, KAM-196): um reinicio perdia-a, e o
caso ficava decidido com o onboarding parado. E um processo que morresse
**entre** a decisao e os efeitos nem chegava a marcar nada.

## Porque uma coluna, e nao uma tabela nem o `audit_log`

* Medido antes de escrever: **nao ha onde a guardar sem DDL.** O dominio da
  `audit_log.accao` e fechado (`audit_log_action`), o aviso ao dono nao deixa
  rasto que se possa ler, e o `kamba_batch` nao tem `UPDATE` em nenhuma coluna
  livre da `review_case`.
* A marca e **um facto do caso** — «este caso tem um efeito por aplicar desde
  T» — e vive e morre com ele. Uma tabela ao lado era uma segunda chave para a
  mesma coisa, com a sua RLS, a sua FK e o seu inventario.
* O *trigger* `review_case_transicao` da `0048` so olha para o `estado` e a
  `prioridade`: escrever esta coluna num caso `decidido_final` passa por ele.

## Os privilegios

O `kamba_batch` ganha `UPDATE` **so desta coluna**, que e o que a marca e o
`resolver` escrevem. O `SELECT` ja o tinha na tabela inteira. Nenhum outro papel
ganha nada: o `kamba_app` continua sem privilegio nenhum na fila.

## O `downgrade`

Recusa-se se houver um caso com a marca: tirar a coluna perdia o efeito por
aplicar, e o caso ficava decidido com o onboarding parado sem ninguem o saber —
que e o defeito que esta revisao fecha. Sem marcas, tira o indice, o privilegio
e a coluna.

**A contagem corre com o `FORCE` desligado**, pela licao do KAM-050 (`0046`) e
do KAM-197 (`0051`): a ligacao do Alembic e dona da tabela, o `FORCE` sujeita-a
a `tenant_iso`, e sem `app.tenant_id` um `count(*)` le **zero** — a guarda
passava sempre.
"""

from __future__ import annotations

from alembic import op

revision = "0053"
#: **Encaixa na `0052` do KAM-194** (#193, revisao de dados das subscricoes),
#: que fundiu primeiro: a cabeca da `publico/main` era ela na integracao
#: (`be3e6eba`). Esta revisao escreveu-se como `0052` sobre a `0051` e
#: renumerou-se na integracao, pela regra da casa — um ramo nao reserva a linha
#: de versoes para outro.
down_revision = "0052"
branch_labels = None
depends_on = None

CASOS = "platform.review_case"
COLUNA = "efeito_pendente_at"
INDICE = "review_case_efeito_pendente_idx"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {CASOS} ADD COLUMN {COLUNA} timestamptz")
    # A pergunta do ciclo: os casos marcados, do mais antigo para o mais
    # recente. Parcial, porque quase todos os casos nunca a tem.
    op.execute(
        f"CREATE INDEX {INDICE} ON {CASOS} ({COLUNA}, id) WHERE {COLUNA} IS NOT NULL"
    )
    op.execute(f"GRANT UPDATE ({COLUNA}) ON {CASOS} TO kamba_batch")
    op.execute(
        f"COMMENT ON COLUMN {CASOS}.{COLUNA} IS "
        "'Desde quando o caso tem um efeito da decisao por aplicar (a fase do "
        "onboarding, a decisao humana de screening, o aviso ao dono). Marca-se "
        "antes dos efeitos e limpa-se quando correm todos; o processo de lote do "
        "onboarding reaplica os marcados (KAM-198). Nulo: nada por aplicar.'"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {CASOS} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $guarda$
        BEGIN
          IF EXISTS (SELECT 1 FROM {CASOS} WHERE {COLUNA} IS NOT NULL) THEN
            RAISE EXCEPTION
              'downgrade da 0053 recusado: ha casos de revisao com um efeito por '
              'aplicar, e tirar a coluna {COLUNA} perdia-o (KAM-198)'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
        END $guarda$
        """
    )
    op.execute(f"ALTER TABLE {CASOS} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP INDEX platform.{INDICE}")
    op.execute(f"REVOKE UPDATE ({COLUNA}) ON {CASOS} FROM kamba_batch")
    op.execute(f"ALTER TABLE {CASOS} DROP COLUMN {COLUNA}")

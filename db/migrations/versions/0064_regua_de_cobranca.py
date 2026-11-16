"""Regua de cobranca da assinatura: billing_dunning_steps (KAM-058).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

Uma tabela, a `platform.billing_dunning_steps`: **um passo da regua por ciclo**
(`lembrete`, `aviso`, `suspensao`), com o resultado, o canal por onde o aviso
saiu e a versao da configuracao que o decidiu. O motor esta em
`packages/core-ts/src/pagamentos/regua.ts`.

* `billing_dunning_steps_passo_uq`, `UNIQUE (billing_cycle_id, passo)`: o
  criterio 1 a letra — reexecutar o motor nao duplica um passo. O motor tranca o
  ciclo e pergunta antes do efeito; esta e a segunda barreira, e a que vale
  contra um motor com defeito.
* FK **composta** `(tenant_id, billing_cycle_id)` para a `billing_cycles`, pela
  licao ISO-58 da `0030`: o passo do tenant A nao aponta para o ciclo de B.
* `resultado` amarrado ao `passo` e o `canal` amarrado ao `resultado`: so a
  suspensao suspende, e so um aviso que saiu tem canal.
* RLS `FORCE` pela `tenant_iso`.

## O que esta revisao **nao** cria, e porque

* **Nenhuma funcao de transicao.** A suspensao e a reposicao passam pelo
  `platform.transition_tenant` da `0058` (KAM-092), e o grafo dos estados e o
  dela. O motor corre como `kamba_batch`, que ja tem `EXECUTE` no
  `transition_tenant` e no `evt_emitir` desde a `0058`.
* **Nenhum evento novo nem gatilho.** O `tenant.suspended` e o
  `tenant.reactivated` tem contrato desde o catalogo do `docs/tecnica/06` §5, e o
  motor emite-os na transaccao em que o `transition_tenant` devolve `true` — que
  e o que da «uma suspensao, um evento». Reescrever o `transition_tenant` para os
  emitir copiava o corpo da `0058` para aqui, e as mutacoes sobre o texto dela
  deixavam de morder (a razao escrita na `0055` para nao tocar na
  `exigir_fase_manual`).
* **Nenhuma tabela de tarefas de ops.** O passo gravado com `canal = 'ops'` **e**
  a tarefa: a lista diaria le-se desta tabela, e a mensagem refaz-se do ledger.
  Uma segunda tabela guardava o texto da mensagem, que o DoD nao deixa ir para
  logs nem eventos.

## Os privilegios

So o `kamba_batch` escreve, e so `INSERT`: um passo nao se edita nem se apaga.
O `kamba_audit` le. O `kamba_app` **nao tem nada**, pela razao da lista de
espera: o painel do dono nao mostra a regua no Piloto, e um privilegio que
ninguem usa e uma superficie.

## O `downgrade`

Larga a tabela, sem `CASCADE`. Os passos sao historico da cobranca: descer
apaga-o, e o `downgrade` diz isso em vez de o guardar noutro sitio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0064"
#: **Provisoria**: o numero e o `down_revision` da-os o orquestrador na
#: integracao, pela ordem da fila. Os ensaios encontram esta revisao pelo nome
#: do ficheiro (`*_regua_de_cobranca.py`), e nao pelo numero.
down_revision = "0063"
branch_labels = None
depends_on = None

PASSOS = ("'lembrete'", "'aviso'", "'suspensao'")
RESULTADOS_DE_AVISO = ("'notificado'", "'saltado'", "'cancelado'")
RESULTADOS_DA_SUSPENSAO = ("'suspenso'", "'sem_transicao'", "'cancelado'")
#: O dominio inteiro, para o `CHECK` que o *gate* 3b le; o que cabe a cada passo
#: e a restricao seguinte.
RESULTADOS = ("'notificado'", "'saltado'", "'cancelado'", "'suspenso'", "'sem_transicao'")
CANAIS = ("'ops'", "'dono'")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.billing_dunning_steps (
          id                uuid        NOT NULL DEFAULT gen_random_uuid(),
          tenant_id         uuid        NOT NULL,
          billing_cycle_id  uuid        NOT NULL,
          passo             text        NOT NULL,
          executado_at      timestamptz NOT NULL,
          resultado         text        NOT NULL,
          canal             text,
          config_versao     text        NOT NULL,
          CONSTRAINT billing_dunning_steps_pkey PRIMARY KEY (id),
          CONSTRAINT billing_dunning_steps_passo_uq UNIQUE (billing_cycle_id, passo),
          CONSTRAINT billing_dunning_steps_ciclo_fk
              FOREIGN KEY (tenant_id, billing_cycle_id)
              REFERENCES platform.billing_cycles (tenant_id, id),
          CONSTRAINT billing_dunning_steps_passo_ck
              CHECK (passo IN ({", ".join(PASSOS)})),
          CONSTRAINT billing_dunning_steps_resultado_ck
              CHECK (resultado IN ({", ".join(RESULTADOS)})),
          CONSTRAINT billing_dunning_steps_resultado_do_passo_ck CHECK (
              (passo <> 'suspensao' AND resultado IN ({", ".join(RESULTADOS_DE_AVISO)}))
              OR (passo = 'suspensao'
                  AND resultado IN ({", ".join(RESULTADOS_DA_SUSPENSAO)}))),
          CONSTRAINT billing_dunning_steps_canal_ck
              CHECK (canal IN ({", ".join(CANAIS)})),
          CONSTRAINT billing_dunning_steps_canal_do_resultado_ck
              CHECK ((canal IS NOT NULL) = (resultado IN ('notificado', 'suspenso'))),
          CONSTRAINT billing_dunning_steps_config_versao_ck
              CHECK (length(config_versao) BETWEEN 1 AND 40)
        )
        """
    )
    op.execute(
        "CREATE INDEX billing_dunning_steps_tenant_idx "
        "ON platform.billing_dunning_steps (tenant_id, executado_at)"
    )
    op.execute(
        "COMMENT ON TABLE platform.billing_dunning_steps IS "
        "'Os passos da regua de cobranca da assinatura (KAM-058): um por ciclo e "
        "por passo. O passo com canal ops e a tarefa da lista diaria de ops. A "
        "suspensao e a reposicao passam pelo transition_tenant da 0058; esta "
        "tabela nao muda estado nenhum.'"
    )
    rls.enable_tenant_rls("billing_dunning_steps")
    op.execute("REVOKE ALL ON platform.billing_dunning_steps FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON platform.billing_dunning_steps TO kamba_batch")
    op.execute("GRANT SELECT ON platform.billing_dunning_steps TO kamba_audit")


def downgrade() -> None:
    rls.disable_tenant_rls("billing_dunning_steps")
    op.execute("DROP TABLE platform.billing_dunning_steps")

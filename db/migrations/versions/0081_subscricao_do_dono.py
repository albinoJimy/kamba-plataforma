"""Subscricao do consumidor dono ao tenant.provisioned (KAM-215).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

**Uma linha em `platform.evt_subscricoes`**, a do
`registry/dono_provisionamento.yaml`: o consumidor `dono` do
`tenant.provisioned`. E a forma da `0052` (KAM-194), da `0067` (KAM-200) e da
revisao da resposta do AGR (KAM-224): as linhas so as escreve o dono das
tabelas, e em producao nao ha escritor. Sem ela, o publicador nunca poe o
evento nas filas `evt.dono.p<n>`, e o processo `onboarding-provisionamento`
(`services/onboarding-web/src/provisionamento.ts`) fica vivo e surdo — e o dono
nunca nasce.

* `versao_max` 2: o `efeitoDoProvisionamento` trata a v1 e a v2
  (`VERSOES_DO_PROVISIONAMENTO`), e o *payload* das duas e o mesmo;
* `finalidade` `transacao`: a do exemplo do contrato
  (`contratos/eventos/tenant.provisioned/exemplo.json`) e a com que o
  `advance_case` da `0058` emite;
* `exige_ordem` `false`: o tipo nao e `payment.*` (a restricao
  `evt_subscricoes_payment_exige_ordem` da `0005`), e o efeito nao transita
  estado nenhum do consumidor.

**Nenhuma concessao nova.** O consumidor corre com as ligacoes que ja existem:
o `kamba_app` faz o `consumir` (`events_consumed`, DLQ) e le o `phone_enc` do
caso sob a RLS do tenant do envelope (`SELECT` da `0043`); o `kamba_identity`
resolve o contacto e chama a `platform.definir_dono` (`EXECUTE` da `0070`).

## O `downgrade`

Apaga a linha **e so esta**, pela chave primaria `(consumer, tipo)`. **O
`upgrade` nao usa `ON CONFLICT`**, pela razao da `0052`: uma linha ja presente
com a mesma chave e uma subscricao que esta revisao nao criou, e o `downgrade`
apaga-la-ia.

## Numero

`0081` sobre a `0080` (KAM-202), pela fila de migracoes do lote 16.
"""

from __future__ import annotations

from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`, na forma da `0052`.
LINHAS = (("dono", "tenant.provisioned", "2", "transacao", "false"),)


def upgrade() -> None:
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

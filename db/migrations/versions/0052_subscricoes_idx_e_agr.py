"""Subscricoes do idx e do AGR em evt_subscricoes: revisao de dados (KAM-194).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## Porque e que isto e uma revisao, e nao um passo de administrador

A `platform.evt_subscricoes` diz ao publicador do KAM-005 quem recebe o que. A
revisao `0004` da `SELECT` ao `kamba_batch` e **nada** ao `kamba_app`: em
producao nao ha escritor, e o `db/bootstrap.py` diz de si proprio que so cria
papeis. As linhas que mandam o publicador entregar ao IDX e ao AGR so as
escreve o dono das tabelas — o `kamba_migrator` —, e e por isso que vem por
uma revisao: versionada, revista, reversivel, e a mesma em todos os ambientes.

## O que ela escreve, e de onde vem

Treze linhas, e **so** estas. As duas fontes sao o `registry/`, e um ensaio
confronta-as com este ficheiro (`services/agr/tests/test_subscricoes_0052.py`):

* **cinco do `idx`** — a declaracao `registry/idx.yaml`, a quarta forma do
  registo (um consumidor que nao e vertical): `catalog.product_changed` e os
  quatro `tenant.*` que o `kamba_core.idx.consumidor` trata, `exige_ordem =
  false` (o efeito le o estado presente, e a ordem nao importa — ver o
  consumidor);
* **oito do AGR** — as que o `consumidores()` do KAM-038 deriva das
  `subscriptions` de `registry/vendedor.yaml` e `registry/servicos.yaml`: o
  `consumer` e `agr_<vertical>`, a versao e a declarada, e o `exige_ordem` sai
  do prefixo `payment.` (a restricao `evt_subscricoes_payment_exige_ordem` da
  `0005` recusava outra coisa).

A `finalidade` e `transacao` nas treze: e a unica que os contratos de todos
estes tipos emitem (`contratos/eventos/<tipo>/exemplo.json`), e o publicador so
entrega quando a finalidade da subscricao esta nas do envelope (§7.3). O
`versao_max` e 1: o publicador desce um envelope `v2` pelo conversor do
KAM-159 quando as finalidades cabem na `v1`, e a `transacao` cabe.

## O `downgrade` apaga estas e so estas

Pela chave primaria `(consumer, tipo)`, linha a linha. Uma subscricao que
alguem tenha escrito a mao para outro consumidor fica. **E o `upgrade` nao usa
`ON CONFLICT`**, de proposito: uma linha ja presente com a mesma chave e uma
subscricao que esta revisao nao criou, e o `downgrade` apaga-la-ia. Falhar alto
e o que se quer — quem a escreveu decide.

## Numero provisorio

`0052` e o numero com que este ramo nasceu, em lote com duas revisoes abaixo
dele. O numero final e o `down_revision` decidem-se na integracao, pela ordem
de fusao.
"""

from __future__ import annotations

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`. Cadeias, todas: o
#: *gate* 3b le a revisao pela arvore sintactica, e o `exige_ordem` entra no SQL
#: como literal booleano do PostgreSQL.
LINHAS = (
    ("idx", "catalog.product_changed", "1", "transacao", "false"),
    ("idx", "tenant.suspended", "1", "transacao", "false"),
    ("idx", "tenant.closed", "1", "transacao", "false"),
    ("idx", "tenant.activated", "1", "transacao", "false"),
    ("idx", "tenant.reactivated", "1", "transacao", "false"),
    ("agr_servicos", "booking.created", "1", "transacao", "false"),
    ("agr_servicos", "booking.reminder_due", "1", "transacao", "false"),
    ("agr_servicos", "payment.confirmed", "1", "transacao", "true"),
    ("agr_servicos", "payment.manual_confirmed", "1", "transacao", "true"),
    ("agr_vendedor", "payment.confirmed", "1", "transacao", "true"),
    ("agr_vendedor", "payment.manual_confirmed", "1", "transacao", "true"),
    ("agr_vendedor", "order.expired", "1", "transacao", "false"),
    ("agr_vendedor", "stock.low", "1", "transacao", "false"),
)


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

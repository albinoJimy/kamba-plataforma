"""Subscricao do CHR ao tenant.activated em evt_subscricoes: revisao de dados (KAM-201).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## Porque e que isto e uma revisao

A razao da `0052` (KAM-194), que e a forma que esta segue: a
`platform.evt_subscricoes` diz ao publicador do KAM-005 quem recebe o que, e
so o dono das tabelas a escreve. Sem esta linha, o publicador nunca poe o
`tenant.activated` nas filas `evt.chr.p<n>`, e o consumidor do CHR
(`packages/core-ts/src/chr/activacao.ts`, servido pelo
`services/worker-canal/src/entrada.ts`) fica vivo e surdo.

## O que ela escreve, e de onde vem

**Uma** linha, e so esta: a `subscriptions` da declaracao `registry/chr.yaml`,
a quarta forma do registo, com `exige_ordem = false` (o efeito esquece uma
entrada de *cache* e nao le estado: a ordem nao importa). Um ensaio confronta
as duas fontes (`services/agr/tests/test_subscricoes_0052.py`).

A `finalidade` e `transacao`, a dos exemplos do contrato do tipo; o
`versao_max` e 1, a unica versao que o efeito conhece — um envelope `v2` desce
pelo conversor do KAM-159 quando as finalidades cabem, e o que nao desce vai a
DLQ pelo proprio efeito.

## O `downgrade` apaga esta e so esta

Pela chave primaria `(consumer, tipo)`. **E o `upgrade` nao usa `ON
CONFLICT`**, pela razao da `0052`: uma linha ja presente com a mesma chave e
uma subscricao que esta revisao nao criou, e o `downgrade` apaga-la-ia.

## Numero provisorio

`0061` sobre a `0060`, dados pelo orquestrador do lote: a `0059` (KAM-095) e a
`0060` (KAM-199) estao por fundir. O numero final decide-se na integracao.
"""

from __future__ import annotations

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`, na forma da `0052`.
LINHAS = (
    ("chr", "tenant.activated", "1", "transacao", "false"),
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

"""Mensagem do WhatsApp na agent_messages: o kamba_app insere o message_id (KAM-232).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

So um `GRANT`: o `kamba_app` passa a poder inserir o `message_id` da
`platform.agent_messages`, alem das cinco colunas do conteudo que a `0077` lhe
deu. Sem coluna nova, sem indice novo, sem restricao nova.

E o desenho minimo da idempotencia da reentrega (criterio 1 do KAM-232, aceite
pela coordenacao do lote 16 a 2026-11-20). O CHR grava uma mensagem `text` do
WhatsApp com um `message_id` **deterministico** — um UUID tirado do SHA-256 de
`agent_messages:{tenant_id}:{wamid}` (`messageIdDe`,
`packages/core-ts/src/chr/invocacao.ts`) — e `ON CONFLICT (message_id) DO
NOTHING`. A `agent_messages_pkey` e que deduplica: a reentrega do mesmo `wamid`
no mesmo tenant da o mesmo identificador, e nao grava segunda linha. As
mensagens do painel continuam com o `DEFAULT gen_random_uuid()`.

## O que o GRANT nao abre

O `kamba_app` continua sem `UPDATE` e sem `DELETE`: uma mensagem nao muda
depois de escrita. Escolher o `message_id` de uma linha nova nao da acesso a
linha de ninguem — a RLS `FORCE` da `0077` continua a fechar o tenant, e um
`message_id` que ja exista noutro tenant faz o `ON CONFLICT` nao gravar nada. A
contagem de linhas do `INSERT` diz que o identificador existe, e isso fica
dito: so o `kamba_app` a ve, que e codigo nosso, e o identificador e um resumo
com o tenant dentro (WhatsApp) ou aleatorio (painel).

## O `downgrade`

Tira o `INSERT` do `message_id`, e o `kamba_app` fica com o da `0077` (as cinco
colunas). As linhas gravadas com um `message_id` escolhido ficam: sao linhas
validas da `0077`.

## Numero

`0083`, sobre a `0082` do KAM-206: a vaga que a coordenacao do lote 16 deu ao
KAM-232 a 2026-11-20.
"""

from __future__ import annotations

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None

MENSAGENS = "platform.agent_messages"


def upgrade() -> None:
    op.execute(f"GRANT INSERT (message_id) ON {MENSAGENS} TO kamba_app")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT (message_id) ON {MENSAGENS} FROM kamba_app")

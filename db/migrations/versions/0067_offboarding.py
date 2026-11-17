"""Off-boarding do tenant: offboarding_run e as subscricoes do CHR (KAM-098).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

Uma tabela, a `platform.offboarding_run`: **uma linha por fase do encerramento
de um tenant**, com a chave `(tenant_id, fase)` que o bloco do KAM-098 escreve.
As sete fases sao as do bloco (`verificacao`, `pendentes`, `canal`,
`exportacao`, `revogacao`, `purga`, `certificado`); o estado de cada uma e o
prazo dela (D0 a D30, *proposta*) vivem na linha, e o que a fase fez vai no
`resultado` (`jsonb`, sem dados pessoais). O orquestrador esta em
`libs/py-core/src/kamba_core/offboarding/`.

* `offboarding_run_pkey`, `PRIMARY KEY (tenant_id, fase)`: o «`UNIQUE (tenant_id,
  fase)`» do bloco. Reexecutar uma fase nao cria segunda linha; e a barreira que
  vale contra um orquestrador com defeito.
* `estado` com **seis** valores: os cinco do bloco e `cancelada`. O criterio 1
  manda o pedido ser **cancelavel ate D7**, e um pedido cancelado nao e
  `falhada` (nada falhou) nem `concluida`: sem o sexto valor, o cancelamento
  nao tinha onde ficar escrito.
* FK `offboarding_run_tenant_fk` para `platform.tenants`, como o bloco escreve.
  A linha do `tenants` **nao sai na purga**: as classes fiscais (encomendas,
  pagamentos) apontam-na por FK e ficam pelo prazo do CGT, e o estado
  `encerrado` e o que diz a quem le que o tenant saiu.
* RLS `FORCE` pela `tenant_iso`.

E duas linhas de dados em `platform.evt_subscricoes`, na forma da `0061`
(KAM-201): o consumidor `chr` passa a receber o `tenant.suspended` e o
`tenant.closed` v1, alem do `tenant.activated`. Sem elas o CHR so esquecia um
tenant na *cache* do resolvedor quando ele **activava** — o sentido em que a
*cache* falha fechada —, e continuava ate 60 s a encaminhar para o AGR um tenant
suspenso pela regua (KAM-058, criterio 2) ou encerrado por este ticket
(criterio 3). A declaracao e o `registry/chr.yaml`, e um ensaio confronta as
duas fontes (`services/agr/tests/test_subscricoes_0052.py`).

## O que esta revisao **nao** cria, e porque

* **Nenhuma funcao de transicao.** O encerramento passa pelo
  `platform.transition_tenant` da `0058` (KAM-092), que ja tem as arestas
  `ativo -> encerrado` e `suspenso -> encerrado`, como `kamba_batch`; o
  `tenant.closed` emite-se pelo `evt_emitir` na mesma transaccao, so quando a
  porta devolve verdadeiro. E a forma da regua de cobranca (KAM-058).
* **Nenhuma coluna de sub-estado.** Os sub-estados `em_exportacao`,
  `em_retencao` e `purgado` (PA-GOV-6, *proposta*) leem-se das fases desta
  tabela, e uma coluna era uma segunda resposta a mesma pergunta.
* **Nenhuma tabela de pedidos nem de exportacoes.** A dupla confirmacao vai no
  `resultado` da fase `verificacao` (as duas provas, como resumo); cada geracao
  da exportacao vai no `audit_log` pela `audit_append` da `0006` e no
  `resultado` da fase `exportacao` (o manifesto e o *hash*).

## Os privilegios

So o `kamba_batch` escreve: `INSERT`, e `UPDATE` **so** do `estado` e do
`resultado` — a fase e o prazo de uma linha nao se reescrevem, e quem quisesse
adiar a purga mudava o `prazo_at` sem rasto. Ninguem apaga: a tabela e a
historia do encerramento, e o certificado le-se dela. O `kamba_audit` le. O
`kamba_app` **nao tem nada**, pela razao da regua: nao ha painel do dono para o
encerramento, e um privilegio que ninguem usa e uma superficie.

## O `downgrade`

Apaga as duas linhas de subscricao pela chave primaria `(consumer, tipo)` e
larga a tabela, sem `CASCADE`. O `upgrade` nao usa `ON CONFLICT`, pela razao da
`0052`: uma linha ja presente com a mesma chave e uma subscricao que esta
revisao nao criou, e o `downgrade` apaga-la-ia.

## Numero

`0067` sobre a `0066` (KAM-072), **provisorio**: o KAM-118 corre em paralelo
com a `0068`, e quem fundir em segundo renumera na integracao. Os ensaios
encontram esta revisao pelo nome do ficheiro (`*_offboarding.py`).
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`, na forma da `0061`.
LINHAS = (
    ("chr", "tenant.suspended", "1", "transacao", "false"),
    ("chr", "tenant.closed", "1", "transacao", "false"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.offboarding_run (
          tenant_id   uuid        NOT NULL,
          fase        text        NOT NULL,
          estado      text        NOT NULL DEFAULT 'pendente',
          prazo_at    timestamptz NOT NULL,
          resultado   jsonb       NOT NULL DEFAULT '{}'::jsonb,
          CONSTRAINT offboarding_run_pkey PRIMARY KEY (tenant_id, fase),
          CONSTRAINT offboarding_run_tenant_fk
              FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
          CONSTRAINT offboarding_run_fase_ck
              CHECK (fase IN ('verificacao', 'pendentes', 'canal', 'exportacao',
                              'revogacao', 'purga', 'certificado')),
          CONSTRAINT offboarding_run_estado_ck
              CHECK (estado IN ('pendente', 'em_curso', 'concluida',
                                'suspensa_disputa', 'falhada', 'cancelada')),
          CONSTRAINT offboarding_run_resultado_ck
              CHECK (jsonb_typeof(resultado) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.offboarding_run IS "
        "'As fases do encerramento de um tenant (KAM-098): uma linha por tenant e "
        "por fase, com o estado, o prazo (D0 a D30, proposta) e o resultado sem "
        "dados pessoais. O encerramento passa pelo transition_tenant da 0058; "
        "esta tabela nao muda o estado do tenant.'"
    )
    rls.enable_tenant_rls("offboarding_run")
    op.execute("REVOKE ALL ON platform.offboarding_run FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON platform.offboarding_run TO kamba_batch")
    op.execute("GRANT UPDATE (estado, resultado) ON platform.offboarding_run TO kamba_batch")
    op.execute("GRANT SELECT ON platform.offboarding_run TO kamba_audit")

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
    rls.disable_tenant_rls("offboarding_run")
    op.execute("DROP TABLE platform.offboarding_run")

"""Finalidade do screening: classificacao_de_catalogo em tenant_destinations (KAM-195).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

**Revisao provisoria.** O numero `0070` e o `down_revision = "0066"` sao os do
ramo: a `0067`, a `0068` e a `0069` sao de outros tickets do mesmo lote, e o
numero final da-o a fila de integracao. Os ensaios descobrem esta revisao por
*glob* (`*_finalidade_do_screening.py`) e leem o `revision` e o
`down_revision` do ficheiro, pelo que renumerar nao toca em nenhum literal deles.

## O que esta revisao faz, e porque

Acrescenta **`classificacao_de_catalogo`** ao dominio de
`platform.tenant_destinations.purpose`, que passa de catorze a **quinze**
valores. E a finalidade de transferencia do papel `screening` do AGR (KAM-192):
o classificador de categorias do screening do GOV manda ao fornecedor do
`screening-nano` o nome da categoria declarada e ate vinte textos de produto,
minimizados. Nenhuma das catorze o serve — a `conversa` e o conteudo de uma
conversa de cliente, os `embeddings` sao o indice do IDX, a `visao` e a
extraccao de campos de uma foto —, e notificar a APD de um tratamento com o nome
de outro e o defeito que o ADR-008 existe para impedir.

**Decisao do fundador, a 2026-11-18:** finalidade propria, e nao reaproveitar
`embeddings` nem deixar o classificador sem destino (a pergunta e as tres
opcoes estao no bloco do KAM-195). O **nome** e *proposta* do executor.

## O que esta revisao **nao** faz, e diz-se

**Nao recria a `platform.v_transfer_audit` da `0036`**, e o `FINALIDADES_DE_MODELO`
dela continua com tres. A vista nao discrimina **qual** finalidade cobre uma
chamada — a `0036` escreveu porque, e o credor da versao exacta (o ticket que
trouxer o `papel` para o canon do lado da base). A consequencia, que fica
declarada: uma chamada de `screening` le-se na vista contra os destinos de
`conversa`, `embeddings` e `visao` do mesmo fornecedor, e **nao** contra os de
`classificacao_de_catalogo`. Um fornecedor so autorizado para a classificacao
aparece la como violacao — o erro e para o lado de mais alarmes, e nao de menos.
Acrescentar a finalidade a lista da vista nao era a correccao: com a conjuncao
da vista (todas as aplicaveis tem de autorizar), um destino de classificacao
`pendente` punha **todas** as chamadas de conversa do fornecedor em violacao.
Quem decide a transferencia e o *gate*, que discrimina pela finalidade do papel.
"""

from __future__ import annotations

from alembic import op

revision = "0070"
down_revision = "0066"
branch_labels = None
depends_on = None

#: As **quinze** finalidades de transferencia: as catorze da `foto_de_produtos`
#: (KAM-120) e a `classificacao_de_catalogo`. Por ordem alfabetica, como la.
FINALIDADES_DE_TRANSFERENCIA = (
    "'alojamento'",
    "'canal'",
    "'classificacao_de_catalogo'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'imagem'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: As catorze da `foto_de_produtos`, para o `downgrade`. Por extenso e nao
#: filtradas da de cima: o *gate* 3b nao le SQL gerado por *generator*.
FINALIDADES_DA_FOTO = (
    "'alojamento'",
    "'canal'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'imagem'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform.tenant_destinations "
        "DROP CONSTRAINT tenant_destinations_purpose_ck"
    )
    op.execute(
        f"""
        ALTER TABLE platform.tenant_destinations
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({", ".join(FINALIDADES_DE_TRANSFERENCIA)}))
        """
    )


def downgrade() -> None:
    # Uma linha `classificacao_de_catalogo` e o registo de uma decisao sobre uma
    # transferencia (contrato, `apd_ref`), e nao se apaga para descer:
    # recusa-se, como a `0047` e a `foto_de_produtos`. A contagem corre sem a
    # `FORCE`, porque o dono da tabela tambem esta sujeito a politica e veria
    # zero.
    op.execute("ALTER TABLE platform.tenant_destinations NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.tenant_destinations "
            "WHERE purpose = 'classificacao_de_catalogo'"
        )
        .scalar_one()
    )
    op.execute("ALTER TABLE platform.tenant_destinations FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da finalidade_do_screening recusado: ha {linhas} destino(s) "
            "com purpose classificacao_de_catalogo, e o dominio da foto_de_produtos "
            "nao os aceita. Sao registos de uma decisao de transferencia: "
            "exporte-os e decida antes de descer."
        )
    op.execute(
        "ALTER TABLE platform.tenant_destinations "
        "DROP CONSTRAINT tenant_destinations_purpose_ck"
    )
    op.execute(
        f"""
        ALTER TABLE platform.tenant_destinations
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({", ".join(FINALIDADES_DA_FOTO)}))
        """
    )

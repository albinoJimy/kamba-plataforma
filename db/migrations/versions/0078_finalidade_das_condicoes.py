"""Finalidade das condicoes: classificacao_de_condicoes em tenant_destinations (KAM-230).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

**Numero dado pela fila de integracao**, sobre a `0077` do KAM-223. Os ensaios
descobrem esta revisao por *glob* (`*_finalidade_das_condicoes.py`) e leem o
`revision` e o `down_revision` do ficheiro, pelo que renumerar nao toca em
nenhum literal deles.

## O que esta revisao faz, e porque

Acrescenta **`classificacao_de_condicoes`** ao dominio de
`platform.tenant_destinations.purpose`, que passa de quinze a **dezasseis**
valores. E a finalidade de transferencia do classificador de screening quando
le as condicoes que o dono escreve num orcamento: ate duzentos caracteres de
texto do dono, sem numeros, com a categoria declarada da loja, pelo mesmo
`screening-nano` do catalogo.

**Decisao do fundador, a 2026-11-20 (opcao B do bloco do KAM-228):** finalidade
propria, e **nao** a `classificacao_de_catalogo` do KAM-195. O classificador e o
mesmo, o tratamento nao: os textos de um produto que a loja publica nao sao o
texto que o dono escreve a um cliente numa proposta, e notificar a APD de um
tratamento com o nome de outro e o que o ADR-008 impede. Um destino autorizado
so para o catalogo nao cobre as condicoes — o *gate* consulta a finalidade que
o pedido traz (`FINALIDADES_ESCOLHIVEIS` do AGR). O **nome** e *proposta* do
executor.

## O que esta revisao **nao** faz, e diz-se

**Nao recria a `platform.v_transfer_audit` da `0036`**, pela razao que a
`finalidade_do_screening` (`0069`) escreveu por extenso e que vale igual para
esta: a vista le as tres finalidades de modelo da `0036` e nao discrimina qual
cobre uma chamada. Uma chamada de `screening` das condicoes le-se la contra os
destinos de `conversa`, `embeddings` e `visao` do mesmo fornecedor, e nao
contra os desta finalidade — o que erra nos dois sentidos, como para o
catalogo. Quem decide a transferencia e o *gate*; a vista fica com o credor
que a `0036` lhe deu.
"""

from __future__ import annotations

from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None

#: As **dezasseis** finalidades de transferencia: as quinze da
#: `finalidade_do_screening` (KAM-195) e a `classificacao_de_condicoes`. Por
#: ordem alfabetica, como la.
FINALIDADES_DE_TRANSFERENCIA = (
    "'alojamento'",
    "'canal'",
    "'classificacao_de_catalogo'",
    "'classificacao_de_condicoes'",
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

#: As quinze da `finalidade_do_screening`, para o `downgrade`. Por extenso e
#: nao filtradas da de cima: o *gate* 3b nao le SQL gerado por *generator*.
FINALIDADES_DO_SCREENING = (
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
    # Uma linha `classificacao_de_condicoes` e o registo de uma decisao sobre
    # uma transferencia (contrato, `apd_ref`), e nao se apaga para descer:
    # recusa-se, como a `0069`. A contagem corre sem a `FORCE`, porque o dono da
    # tabela tambem esta sujeito a politica e veria zero.
    op.execute("ALTER TABLE platform.tenant_destinations NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.tenant_destinations "
            "WHERE purpose = 'classificacao_de_condicoes'"
        )
        .scalar_one()
    )
    op.execute("ALTER TABLE platform.tenant_destinations FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da finalidade_das_condicoes recusado: ha {linhas} destino(s) "
            "com purpose classificacao_de_condicoes, e o dominio da "
            "finalidade_do_screening nao os aceita. Sao registos de uma decisao de "
            "transferencia: exporte-os e decida antes de descer."
        )
    op.execute(
        "ALTER TABLE platform.tenant_destinations "
        "DROP CONSTRAINT tenant_destinations_purpose_ck"
    )
    op.execute(
        f"""
        ALTER TABLE platform.tenant_destinations
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({", ".join(FINALIDADES_DO_SCREENING)}))
        """
    )

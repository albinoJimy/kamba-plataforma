"""Finalidade do screening: classificacao_de_catalogo em tenant_destinations (KAM-195).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

**Numero dado pela fila de integracao.** A `0069` assenta na `0068` do
off-boarding (KAM-098), e o numero mudou na integracao com a `main`. Os ensaios descobrem esta revisao por
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
trouxer o `papel` para o canon do lado da base; hoje nenhum o reclama). A
consequencia fica declarada, e **erra nos dois sentidos** (achado 2 da revisao
adversarial; a primeira versao desta nota dizia que so errava para mais
alarmes, e nao e verdade): uma chamada de `screening` le-se na vista contra os
destinos de `conversa`, `embeddings` e `visao` do mesmo fornecedor, e **nao**
contra os de `classificacao_de_catalogo`. Logo:

* **mais frouxa do que a porta** — com a `conversa` autorizada e a
  classificacao `pendente` ou `revogada`, uma chamada de `screening` que
  saisse (um defeito do *gate*, ou a *cache* de 60 s depois de uma revogacao)
  le-se como conforme. E a mesma classe de folga que a vista ja aceita entre as
  tres (uma chamada de `chat` coberta por um destino so de `visao`);
* **mais estrita do que a porta** — com o fornecedor autorizado **so** para a
  classificacao, cada chamada legitima de `screening` aparece como violacao, e
  o alvo de zero linhas do criterio 7 do KAM-069 fica inalcancavel.

Acrescentar a finalidade a lista da vista nao era a correccao: com a conjuncao
da vista (todas as aplicaveis tem de autorizar), um destino de classificacao
`pendente` punha **todas** as chamadas de conversa do fornecedor em violacao.
Separar o `screening` pelo `c.papel` era a versao exacta para este papel, e e
o mapa `papel` -> finalidade escrito uma segunda vez em SQL, que a `0036`
recusou. Quem decide a transferencia e o *gate*, que discrimina pela finalidade
do papel; a vista fica com o credor que a `0036` lhe deu.
"""

from __future__ import annotations

from alembic import op

revision = "0069"
down_revision = "0068"
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

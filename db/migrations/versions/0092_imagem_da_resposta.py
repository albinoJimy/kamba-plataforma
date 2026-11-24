"""Imagem da resposta do AGR: media_ref na agent_replies (KAM-246).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero

A `0092`, sobre a `0091`, pela fila de migracoes do lote 20 (uma
revisao por fundir de cada vez): a `0091` e a do KAM-127. O numero deu-o a
coordenacao.

## Porque

O KAM-122 grava a arte do modulo social no STO do tenant (classe `arte`), e o
dono recebia so o texto: o `Corpo` do Outbound nao tinha imagem. Pela decisao
D5 do fundador (2026-11-21, opcao A, bloco do KAM-122), o KAM-246 faz a arte
chegar como **imagem** na pre-visualizacao e na entrega. O consumidor `outbound`
le a resposta pela linha (o `agent.replied` nao muda), e por isso a imagem e
uma coluna da linha.

## O que esta revisao escreve

| Coluna | Para que serve |
|---|---|
| `media_ref` | a **chave** do STO da arte que sai como imagem antes do texto; nula numa resposta sem imagem |

**A chave, e nunca um URL**: um URL assinado expira em cinco minutos e leva a
assinatura; a chave nao expira e o consumidor le o objecto com o tenant do
envelope. A forma e a do KAM-011 (`t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`).

## As restricoes

- `agent_replies_media_ref_ck`: a chave tem a forma do STO, e a **classe**
  `arte`, e o **tenant** e o da propria linha. Uma chave de outro tenant, de
  outra classe (a foto do dono, um documento de KYC, o pacote de um
  off-boarding) ou um URL nao se gravam. E a primeira das tres barreiras: o
  consumidor confere outra vez antes de ler (`chaveDaArte`), e a porta do STO
  recusa uma chave fora do tenant do contexto.
- `agent_replies_media_sem_template_ck`: uma imagem nunca sai com *template*.
  A imagem so sai dentro da janela de 24 h aberta pelo dono, e o `Saida`
  recusa-a fora dela; com *template*, o consumidor nao sabia o que mandar.

## Privilegios

O `kamba_app` (o AGR) **insere** a coluna, ao lado do resto do conteudo da
resposta. **Nao a muda**: o `UPDATE` da aplicacao continua so o `entregue_at`.

## Retencao

A coluna sai com a linha, pela classe `conversas` da retencao, como o resto
dela. O objecto e o da classe `arte` do KAM-122, e nao muda de prazo por ter
saido como imagem.

## O `downgrade`

Retira o `INSERT` da coluna e larga-a, com as duas restricoes. **Sem recusa**:
uma resposta com imagem por entregar passa a resposta de texto, que sai sem a
imagem (o texto diz que a arte esta na pagina Social do painel). Nao sai nada
que nao devesse sair.
"""

from __future__ import annotations

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None

TABELA = "platform.agent_replies"

#: A forma de uma chave da arte: a do KAM-011 com a classe `arte`. O tenant
#: confere-se a parte, contra o `tenant_id` da linha.
FORMA_DA_CHAVE = (
    "^t/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/arte/"
    "[0-9]{4}/(0[1-9]|1[0-2])/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

#: A coluna que o `kamba_app` passa a inserir.
INSERT_DESTA = ("media_ref",)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD COLUMN media_ref text
              CONSTRAINT agent_replies_media_ref_ck
              CHECK (media_ref ~ '{FORMA_DA_CHAVE}'
                     AND split_part(media_ref, '/', 2) = tenant_id::text),
          ADD CONSTRAINT agent_replies_media_sem_template_ck
              CHECK (media_ref IS NULL OR template_nome IS NULL)
        """
    )
    op.execute(
        f"COMMENT ON COLUMN {TABELA}.media_ref IS "
        "'A chave do STO da arte do social que sai como imagem antes do texto (KAM-246). "
        "Do tenant da linha e da classe arte; nunca um URL. Nula sem imagem.'"
    )
    op.execute(f"GRANT INSERT ({', '.join(INSERT_DESTA)}) ON {TABELA} TO kamba_app")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ({', '.join(INSERT_DESTA)}) ON {TABELA} FROM kamba_app")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          DROP CONSTRAINT agent_replies_media_sem_template_ck,
          DROP COLUMN media_ref
        """
    )

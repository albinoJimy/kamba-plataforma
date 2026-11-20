"""Template da resposta do AGR: template_nome e template_parametros na agent_replies (KAM-221).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero

A `0076`, sobre a `0075` do KAM-216, pela fila de migracoes do lote 13: uma
revisao por fundir de cada vez.

## Porque

A `agent_replies` do KAM-224 so leva texto livre, e o texto livre so sai com a
janela de 24 h do cliente aberta. O Orcamento expresso precisa de falar a um
cliente com a janela fechada — a proposta pronta (`orcamento_pronto`) e a
mensagem neutra das 24 h (`orcamento_em_espera`) —, e isso e um *template*.

Pela decisao da coordenacao do lote 13 (2026-11-19, bloco do KAM-221, opcao
A), **quem escolhe entre o texto e o *template* e o AGR**, ao emitir, a ler a
`window_expires_at` com uma margem de cinco minutos. O consumidor `outbound`
obedece ao que a linha diz e nunca troca sozinho: com `template_nome` monta um
corpo de *template*, sem ele monta o texto (ou os botoes) como antes.

## O que esta revisao escreve

| Coluna | Para que serve |
|---|---|
| `template_nome` | o nome do *template* da Meta, nulo numa resposta de texto livre |
| `template_parametros` | os **valores** dos parametros do corpo, pela ordem, ja resolvidos e validados pelo AGR; vazio sem *template* |

**Valores, e nao referencias** (decisao da coordenacao): o consumidor nao
resolve nada, monta o corpo com o que a linha diz. Por isso os parametros
contam como o `texto` — conteudo para o cliente, escrito pelo AGR, nunca pelo
cliente — no inventario de dados pessoais, e saem com a linha pela classe
`conversas` da retencao, como o resto dela.

O `texto` continua `NOT NULL` numa resposta de *template*: e o que a
notificacao diria com a janela aberta. O consumidor do WhatsApp nao o envia com
o *template*.

## As restricoes

- `agent_replies_template_ck`: parametros so com *template*. Uma linha com
  parametros e sem nome era um corpo que o consumidor nao sabia montar.
- `agent_replies_template_nome_ck`: o nome na forma da Meta (minusculas,
  algarismos e `_`, ate 512).
- `agent_replies_template_parametros_ck`: nenhum parametro nulo. A Meta recusa
  um parametro vazio, e um `NULL` no `text[]` chegava ao corpo como `"null"`.

## Privilegios

O `kamba_app` (o AGR) **insere** as duas colunas, ao lado do resto do conteudo
da resposta. **Nao as muda**: o `UPDATE` da aplicacao continua so o
`entregue_at`, porque uma resposta emitida nao muda de conteudo.

## O `downgrade`

Retira o `INSERT` das duas colunas e larga-as, com as tres restricoes; o
`INSERT` da `0073` fica como estava.
**Sem recusa**: uma resposta de *template* por entregar passa a ser uma resposta
de texto, que o `Saida` recusa com a janela fechada (`WINDOW_CLOSED`) — nao sai
nada que nao devesse sair, e o pedido do Orcamento expresso fica onde estava.
"""

from __future__ import annotations

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

TABELA = "platform.agent_replies"

#: A forma de um nome de *template* da Meta: minusculas, algarismos e `_`, ate
#: 512. Igual ao `FORMA_DO_TEMPLATE` de `services/agr/src/kamba_agr/saida.py`.
#: O tamanho vai num `char_length` a parte, e nao num `{1,512}`: as expressoes
#: regulares do PostgreSQL nao aceitam uma repeticao acima de 255 (`2201B`).
FORMA_DO_NOME = "^[a-z0-9_]+$"
MAXIMO_DO_NOME = 512

#: As duas colunas que o `kamba_app` passa a inserir, ao lado das da `0073`.
INSERT_DESTA = ("template_nome", "template_parametros")


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD COLUMN template_nome text
              CONSTRAINT agent_replies_template_nome_ck
              CHECK (template_nome ~ '{FORMA_DO_NOME}'
                     AND char_length(template_nome) <= {MAXIMO_DO_NOME}),
          ADD COLUMN template_parametros text[] NOT NULL DEFAULT '{{}}'
              CONSTRAINT agent_replies_template_parametros_ck
              CHECK (array_position(template_parametros, NULL) IS NULL),
          ADD CONSTRAINT agent_replies_template_ck
              CHECK (template_nome IS NOT NULL OR cardinality(template_parametros) = 0)
        """
    )
    op.execute(
        f"COMMENT ON COLUMN {TABELA}.template_nome IS "
        "'O template da Meta desta resposta (KAM-221), escolhido pelo AGR com a "
        "janela fechada. Nulo numa resposta de texto livre.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {TABELA}.template_parametros IS "
        "'Os valores dos parametros do template, pela ordem, ja resolvidos pelo AGR "
        "(KAM-221). Conteudo para o cliente, como o texto.'"
    )
    op.execute(f"GRANT INSERT ({', '.join(INSERT_DESTA)}) ON {TABELA} TO kamba_app")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ({', '.join(INSERT_DESTA)}) ON {TABELA} FROM kamba_app")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          DROP CONSTRAINT agent_replies_template_ck,
          DROP COLUMN template_parametros,
          DROP COLUMN template_nome
        """
    )

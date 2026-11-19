"""Sujeito das condicoes: condicoes em screening_decision.sujeito_tipo (KAM-222).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz, e porque

Acrescenta **`condicoes`** ao dominio de
`platform.screening_decision.sujeito_tipo`, que passa de dois a **tres**
valores. E o sujeito das condicoes escritas pelo dono numa proposta do
Orcamento expresso (KAM-123), que o `conferir_condicoes` passa pelo `screen` do
KAM-088 atraves da rota `POST /internal/screen` do COM. A `sujeito_ref` e o
`quote_id` do pedido.

**Decisao do fundador, a 2026-11-19 (opcao A, bloco do KAM-222):** sujeito
proprio, por revisao nova. Gravar as condicoes como `produto` com o `sku` do
pedido fazia a re-analise do catalogo saltar o produto, porque o
`SQL_POR_REANALISAR` procura uma decisao por `sku` e versao sem comparar o
conteudo. O **nome** e *proposta* do executor.

Nenhuma consulta existente muda de resposta: a re-analise, a activacao do tenant
(`0058`) e a leitura da categoria do COM filtram todas por `categoria` ou por
`produto`, explicitamente.

## O `downgrade`

**Apaga as decisoes `condicoes`**, e depois repoe o dominio de dois. E a regra
da `0044`, que larga a tabela inteira: uma base onde se desce uma revisao do
screening e uma base de ensaio. Recusar, como a `0069`, deixava a descida
presa a uma tabela *append-only*: o *trigger* `screening_decision_imutavel`
recusa o `DELETE` tambem ao dono, e nenhum ensaio conseguia limpar as linhas
que escreveu — a descida da `0044` e das revisoes de baixo ficava vermelha
conforme a ordem das suites. O *trigger* desliga-se so para este `DELETE`, e a
RLS `FORCE` tambem, porque o dono esta sujeito a politica e veria zero linhas.

## Numero

`0074`, sobre a `0073` do KAM-224: a vaga de migracao do lote 13 era do KAM-224,
e esta escreve-se depois de ele fundir, por instrucao da coordenacao.
"""

from __future__ import annotations

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

TABELA = "platform.screening_decision"
RESTRICAO = "screening_decision_sujeito_tipo_ck"

#: Os **tres** sujeitos. Iguais ao `SUJEITOS` de
#: `packages/core-ts/src/screening/tipos.ts`, que o ensaio da base compara com o
#: `CHECK`. Por extenso: o *gate* 3b le o SQL das revisoes sem as executar.
SUJEITOS = ("'categoria'", "'condicoes'", "'produto'")

#: Os dois da `0044`, para o `downgrade`.
SUJEITOS_DA_0044 = ("'categoria'", "'produto'")


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABELA} DROP CONSTRAINT {RESTRICAO}")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD CONSTRAINT screening_decision_sujeito_tipo_ck
          CHECK (sujeito_tipo IN ({", ".join(SUJEITOS)}))
        """
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABELA} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABELA} DISABLE TRIGGER screening_decision_imutavel")
    op.execute(f"DELETE FROM {TABELA} WHERE sujeito_tipo = 'condicoes'")
    op.execute(f"ALTER TABLE {TABELA} ENABLE TRIGGER screening_decision_imutavel")
    op.execute(f"ALTER TABLE {TABELA} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABELA} DROP CONSTRAINT {RESTRICAO}")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD CONSTRAINT screening_decision_sujeito_tipo_ck
          CHECK (sujeito_tipo IN ({", ".join(SUJEITOS_DA_0044)}))
        """
    )

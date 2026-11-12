"""KAM-192: o papel screening no dominio fechado de dat.llm_call_log.papel.

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## Porque e que ha revisao

O dicionario §3.29 tem **um** conceito para o papel de um alias e para a coluna
`llm_call_log.papel`: o grafo pede o papel, e a linha de custo e de
transferencia (ADR-008, ADR-018) grava o mesmo valor. A `0023` impos o dominio
com um `CHECK` fechado de quatro, e o KAM-088 deixou o alias do classificador de
screening (`screening-nano`) nomeado e nao declarado porque declara-lo com um
dos quatro papeis tomava o lugar de outro alias. O papel novo e a emenda 1.83
do dicionario; esta revisao e a metade da base, e sem ela uma chamada do papel
`screening` pelo cliente do AGR sairia com a linha recusada pelo servidor
(`23514`) e engolida pelo `_escrever` — o registo de transferencia perdido em
silencio, que e o defeito que o criterio 5 do KAM-030 fecha.

## Pai e particao, num passo

A tabela e particionada (`PARTITION BY RANGE (ts)`) e a `0023` criou o `CHECK`
**no pai**: o PostgreSQL herda-o para cada particao, e o `DROP CONSTRAINT` e o
`ADD CONSTRAINT` no pai recursam para elas. Nao se escreve um `ALTER` por
particao — uma restricao herdada nao se larga na filha (`42P16`). O ensaio
confirma no catalogo que a `llm_call_log_default` ficou com os cinco.

## O `NO FORCE` a volta das duas operacoes

E a armadilha que a `0003` mediu contra o PostgreSQL 18.6 e que a `0038`
repetiu no `audit_log`: com `FORCE ROW LEVEL SECURITY`, uma consulta do dono
**sem contexto de tenant ve zero linhas**. O pai e a particao tem `FORCE`
(`_rls` da `0023`). No `upgrade` o dominio novo e superconjunto do antigo e a
validacao e verdadeira de qualquer maneira; no `downgrade` nao, e a contagem
que decide a recusa sairia zero. Desliga-se nos dois sentidos pela razao que a
`0038` escreveu: a assimetria e o que se esquece.

## O `downgrade`

Repoe o `CHECK` de quatro da `0023` e **recusa** quando ha linhas com
`papel = 'screening'`. A tabela e *append-only* por *trigger* `ENABLE ALWAYS`
(tambem para o dono) e nenhum papel tem `DELETE`: nao ha forma de as retirar, e
deixa-las debaixo de um `CHECK` que diz que nao existem nao e uma descida, e uma
base inconsistente. A recusa diz a contagem e o que fazer.
"""

from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0045"
branch_labels = None
depends_on = None

TABELA = "dat.llm_call_log"
PARTICAO = "dat.llm_call_log_default"
RESTRICAO_DO_PAPEL = "llm_call_log_papel_ck"

#: O dominio depois desta revisao (dicionario §3.29, emenda 1.83). **Literal**,
#: pela razao da `0023`: o *gate* 3b nao resolve uma chamada de funcao dentro de
#: um `op.execute`.
PAPEIS_SQL_0047 = "'router', 'chat', 'vision', 'embed', 'screening'"

#: O dominio da `0023`, que o `downgrade` repoe. Copiado e nao importado, pela
#: razao da `0038`: uma revisao que importasse constantes de outra descrevia o
#: estado dela e nao o passo que da.
PAPEIS_SQL_0023 = "'router', 'chat', 'vision', 'embed'"


def _sem_force() -> None:
    op.execute(f"ALTER TABLE {TABELA} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {PARTICAO} NO FORCE ROW LEVEL SECURITY")


def _com_force() -> None:
    op.execute(f"ALTER TABLE {TABELA} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {PARTICAO} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _sem_force()
    op.execute(f"ALTER TABLE {TABELA} DROP CONSTRAINT {RESTRICAO_DO_PAPEL}")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD CONSTRAINT {RESTRICAO_DO_PAPEL}
          CHECK (papel IN ({PAPEIS_SQL_0047}))
        """
    )
    _com_force()


def downgrade() -> None:
    _sem_force()
    linhas = (
        op.get_bind()
        .exec_driver_sql(f"SELECT count(*) FROM {TABELA} WHERE papel = 'screening'")
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0047 recusado: ha {linhas} linha(s) de dat.llm_call_log "
            "com papel screening e o dominio da 0023 nao as aceita. A tabela e "
            "append-only e nenhum papel tem DELETE, pelo que nao ha forma de as "
            "retirar: exporte-as e decida o que fazer antes de descer."
        )
    op.execute(f"ALTER TABLE {TABELA} DROP CONSTRAINT {RESTRICAO_DO_PAPEL}")
    op.execute(
        f"""
        ALTER TABLE {TABELA}
          ADD CONSTRAINT {RESTRICAO_DO_PAPEL}
          CHECK (papel IN ({PAPEIS_SQL_0023}))
        """
    )
    _com_force()

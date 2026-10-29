"""Os codigos SLOT_TAKEN e HOLD_EXPIRED no CHECK da tool_audit (KAM-035).

A primeira linha e **sem acentos**, como as vinte e cinco revisoes anteriores: e
a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

## Esta revisao nao cria nada, e isso e o ponto

Dois literais entram num `CHECK` fechado, e mais nada. E a mesma forma da `0022`,
que fez o mesmo para o decimo primeiro codigo — e a razao e exactamente a que
aquela revisao escreveu: **o passo 7 do `invoke` escreve uma linha de
`tool_audit` por invocacao, inclusive pelas recusas.** Sem isto, a primeira vez
que o `book_slot` recusasse por intervalo tomado, o `INSERT` da linha que o
registava violava a restricao e a invocacao rebentava com um defeito de base em
vez de devolver a recusa ao cliente.

## Quem a pediu foi o ticket anterior, por escrito

O `services/com/src/servicos/contrato.ts` (KAM-047) escreve-o no cabecalho:

    «alargar aquele dominio obriga a um `ALTER` ao `CHECK` das revisoes `0021` e
    `0022`, que sao de outro ticket, e quem precisa dos dois codigos no registo
    da ToolLayer e quem ligar o `book_slot` ao grafo — **KAM-035**, que este
    ticket tem ordem para nao expandir.»

E este. Os dois codigos deixam de ser o dominio **so** do modulo
(`ServicosModule.erro`) e passam a ser tambem `tool_audit.error_code`, com a
emenda ao dicionario que isso exige (§3.28, emenda 1.47).

## Os outros quatro codigos do modulo NAO entram, e nao e esquecimento

O `ERROS` do modulo tem seis valores. Quatro deles — `LIMIT_EXCEEDED`,
`ENTITLEMENT_DENIED`, `NOT_FOUND`, `VALIDATION_ERROR` — **ja estao** no `CHECK`:
o proprio contrato diz que se «importam da semantica que o `hook_de_tool` do
KAM-009 ja devolve» e que «nao se redeclaram com outro significado». Acrescentar
um literal que ja esta la nao e inofensivo — era declarar que o codigo do modulo
e um codigo **diferente** com o mesmo nome, e e precisamente o que aquela frase
proibe.

## O `downgrade` nao estreita o dominio de volta

E a assimetria da `0022`, pelas mesmas tres razoes e nao por analogia:

1. os dois codigos passam a ser **canon** (dicionario §3.28), e um `downgrade`
   que os retirasse da base deixava o esquema a discordar do dicionario — o gate
   3b falharia sobre uma base que o proprio `downgrade` produziu;
2. uma linha de `tool_audit` que **ja** tenha um deles faz o `ADD CONSTRAINT`
   estreito falhar (`23514`), pelo que o `downgrade` parava a meio;
3. um dominio mais largo nao perde dados nem quebra chamador nenhum — nada
   escreve o codigo depois de a camada o deixar de devolver.

O `downgrade` fica, portanto, **sem efeito**, e isso esta escrito aqui e na
seccao de verificacao do bloco em vez de ser escondido por um corpo que parecia
simetrico.
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

#: Os **treze** codigos: os dez do `02` §6.5, o do §6.3 (KAM-029) e os dois do
#: modulo `servicos` (KAM-047, ligados por este ticket).
#:
#: **Confronta-se com o `CODIGOS` do `kamba_agr/tls/erros.py`**, e ha ensaio a
#: faze-lo: o `db/tests_agr/test_tool_audit.py` percorre aquela lista e insere
#: cada valor, pelo que um codigo la que nao esteja aqui e um `INSERT` recusado —
#: uma invocacao que corre e nao se consegue auditar. As duas listas movem-se
#: juntas.
LITERAIS_DE_ERRO = (
    "'NOT_FOUND', 'OUT_OF_STOCK', 'PRICE_CHANGED', 'LIMIT_EXCEEDED', "
    "'ENTITLEMENT_DENIED', 'TOOL_NOT_ALLOWED', 'TENANT_MISMATCH', "
    "'UPSTREAM_TIMEOUT', 'UPSTREAM_DOWN', 'VALIDATION_ERROR', "
    "'INTENT_REUSED_WITH_DIFFERENT_CONTENT', 'SLOT_TAKEN', 'HOLD_EXPIRED'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE platform.tool_audit DROP CONSTRAINT tool_audit_error_code")
    op.execute(
        "ALTER TABLE platform.tool_audit ADD CONSTRAINT tool_audit_error_code "
        f"CHECK (error_code IN ({LITERAIS_DE_ERRO}))"
    )


def downgrade() -> None:
    # Sem efeito, de propria decisao — ver o cabecalho. **Nao e um `pass`
    # esquecido**: o `alembic downgrade` tem de poder correr, e o que ele nao faz
    # e estreitar um dominio que passou a ser canon.
    return None

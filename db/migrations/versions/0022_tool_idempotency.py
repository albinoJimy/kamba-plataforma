"""KAM-029: a `tool_idempotency`, a barreira de idempotencia das tools de escrita.

O `docs/tecnica/02` §6.3 da a chave e a tabela, e o `docs/tecnica/03` §6.3 da o
protocolo e o tecto de espera. Esta revisao cria **uma** tabela e **altera uma
restricao** da `0021`, e as duas coisas sao do mesmo ticket: o codigo
`INTENT_REUSED_WITH_DIFFERENT_CONTENT` nasce aqui e a `tool_audit.error_code` e
um `CHECK` fechado, pelo que sem a alteracao a primeira recusa do criterio 3
rebentava ao escrever a propria linha que a registava.

## Porque e que isto nao e a `usage_ledger`

Ha tres livros de idempotencia no esquema e nenhum substitui outro:

| | `usage_ledger` (KAM-009) | `order_intents` (KAM-046) | `tool_idempotency` (este) |
|---|---|---|---|
| Pergunta | «este **turno** ja foi contado?» | «esta **intencao** ja criou encomenda?» | «este **carrinho** ja foi comprado?» |
| Chave | a `idempotency_key` do chamador | `intent_key` de `(tenant, contacto, draft_id, draft_version)` | o `sha256` das quatro partes do §6.3 |
| Onde | no TEN, no passo 2 | no COM | na TLS, no passo 5 |
| Guarda resultado | nao, e uma marca | sim, a encomenda | sim, o `result` da tool |

O §6.3 do `03` chama a esta e a do COM «duas barreiras independentes» e diz que
«nenhuma das duas depende da outra». Esta e a de fora: fecha antes de o backend
ser chamado, e e a unica que fecha uma tool que **nao** seja o `criar_pedido` —
o `book_slot` de Servicos usa a mesma tabela, com o `hold_id` no lugar do
`cart_id` (`02` §6.2).

## Esta tabela **nao** e *append-only*, e e deliberado

A `tool_audit` e a `audit_log` sao; esta nao pode ser. O protocolo e `INSERT`
com estado `em_curso` -> executar -> `UPDATE` com o resultado, e um *trigger* de
imutabilidade recusava o segundo passo. O que a protege e outra coisa: o
`UPDATE` esta concedido **por coluna**, e so em `estado` e `result`.

**O `args_hash` nao e alteravel, e e isso que faz o criterio 3 valer.** Se o
papel da aplicacao o pudesse reescrever, a recusa
`INTENT_REUSED_WITH_DIFFERENT_CONTENT` era contornavel por quem a ia accionar. E
o `created_at` tambem nao se escreve nem se altera — nem no `INSERT` —, pela
razao do `ts` da `tool_audit`: e por ele que a retencao apaga, e um chamador que
o escolhesse escolhia quando e que a sua linha deixava de existir.

## A forma da `key` e o criterio 6

O criterio 6 pede «a coluna `key` nunca contem `+244`». Isso **nao** se prova
por o chamador nao la pôr um telefone: prova-se pela base recusar. A `key` tem
`CHECK (key ~ '^[0-9a-f]{64}$')` — sessenta e quatro digitos hexadecimais, que e
a forma de um `sha256`. Nenhum telefone, BSUID ou nome cabe la, qualquer que
seja o chamador e qualquer que seja o defeito dele (ADR-010).
"""

from alembic import op

import rls

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

#: Os tres estados de uma linha. Lista **fechada**, a mesma do `ESTADOS` do
#: `kamba_agr/tls/idempotency.py` (ha teste a confronta-las).
LITERAIS_DE_ESTADO = "'em_curso', 'concluida', 'falhada'"

#: A gramatica de um nome de tool. A mesma da `0021` e do `metricas.py`.
GRAMATICA_DE_NOME = "^[a-z][a-z0-9_]{1,62}$"

#: A forma de um `sha256` em hexadecimal — ver a nota do modulo sobre o criterio 6.
FORMA_DA_CHAVE = "^[0-9a-f]{64}$"

#: O que o papel da aplicacao escreve no `INSERT`. **Sem `estado`**, que entra
#: pela omissao (`em_curso`), e sem `created_at`.
COLUNAS_DO_INSERT = "key, tenant_id, tool, args_hash"

#: O que ele pode **alterar**: o desfecho e o resultado, e mais nada.
COLUNAS_DO_UPDATE = "estado, result"

#: Os onze erros tipados: os dez do `02` §6.5 mais o do §6.3 (KAM-029).
LITERAIS_DE_ERRO = (
    "'NOT_FOUND', 'OUT_OF_STOCK', 'PRICE_CHANGED', 'LIMIT_EXCEEDED', "
    "'ENTITLEMENT_DENIED', 'TOOL_NOT_ALLOWED', 'TENANT_MISMATCH', "
    "'UPSTREAM_TIMEOUT', 'UPSTREAM_DOWN', 'VALIDATION_ERROR', "
    "'INTENT_REUSED_WITH_DIFFERENT_CONTENT'"
)

def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.tool_idempotency (
            -- O `sha256` das quatro partes do `02` §6.3, em hexadecimal. O `|`
            -- daquela formula **nao** e um separador literal: o `cart_id` e
            -- opaco e nenhum caractere seria seguro, e por isso o
            -- `idempotency.py` prefixa cada parte com o comprimento. Com um
            -- separador literal, as particoes `(a, b<sep>c)` e `(a<sep>b, c)`
            -- davam a mesma chave — numa tool `money`, a encomenda de um
            -- cliente a responder pela de outro.
            key        text        PRIMARY KEY,
            tenant_id  uuid        NOT NULL,
            tool       text        NOT NULL,
            -- `sha256` da forma canonica dos argumentos, 32 octetos: o mesmo
            -- valor e a mesma funcao da `tool_audit.args_hash`
            -- (`tls/auditoria.impressao`), para que as duas linhas da mesma
            -- invocacao se liguem sem uma terceira coluna a dize-lo.
            args_hash  bytea       NOT NULL,
            estado     text        NOT NULL DEFAULT 'em_curso',
            -- O `data` do `ToolResult` da invocacao que fechou esta linha. E o
            -- que um *replay* devolve, com `idempotent_replay=true`.
            result     jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT tool_idempotency_key_sha256 CHECK (key ~ '{FORMA_DA_CHAVE}'),
            CONSTRAINT tool_idempotency_estado CHECK (
              estado IN ({LITERAIS_DE_ESTADO})
            ),
            CONSTRAINT tool_idempotency_tool_nome CHECK (
              tool ~ '{GRAMATICA_DE_NOME}'
            ),
            CONSTRAINT tool_idempotency_args_hash_sha256 CHECK (
              octet_length(args_hash) = 32
            ),
            -- **Nos dois sentidos, e nao num.** A licao e da `0021`: um `CHECK`
            -- so recusa o que e **falso**, e uma restricao num sentido so
            -- deixava passar metade. Aqui as duas metades sao defeitos
            -- diferentes e as duas custam dinheiro — uma linha `concluida` sem
            -- `result` devolvia um *replay* vazio como se a tool nao tivesse
            -- devolvido nada, e um `result` numa linha `falhada` era um
            -- resultado que a retoma do criterio 4 devolvia como *replay* de
            -- uma invocacao que ninguem confirmou.
            CONSTRAINT tool_idempotency_resultado_so_em_concluida CHECK (
              (estado = 'concluida' AND result IS NOT NULL)
              OR (estado <> 'concluida' AND result IS NULL)
            )
        )
        """
    )
    # O indice que a convencao pede: **algum** indice de uma tabela com
    # `tenant_id` comeca por `tenant_id` (`db/tests/test_catalogo.py`). A chave
    # primaria e a `key`, que nao o leva, e por isso leva indice proprio — como
    # a `handoffs`, a `media_assets`, a `channel_quality_log` e a `consent_event`.
    #
    # A segunda coluna e o `created_at` porque a unica leitura por tenant desta
    # tabela e «as reservas deste tenant, por idade», que e o que uma
    # verificacao de retencao pergunta. A varredura da retencao em si corre como
    # `kamba_batch` (`BYPASSRLS`) e le por `created_at` sem tenant nenhum: numa
    # tabela desta dimensao e um `seq scan`, e um indice so para ela era um
    # indice que mais ninguem usa.
    op.execute(
        "CREATE INDEX tool_idempotency_tenant_criado_idx "
        "ON platform.tool_idempotency (tenant_id, created_at)"
    )
    rls.enable_tenant_rls("tool_idempotency")
    _privilegios()
    _codigo_novo_na_tool_audit()


def _privilegios() -> None:
    """`SELECT`/`INSERT`/`UPDATE` por coluna ao `kamba_app`; `DELETE` ao lote.

    **O `kamba_app` le esta tabela**, ao contrario da `tool_audit`, e a razao e
    a diferenca de proposito: ali o `SELECT` era um caminho para o conteudo de
    um registo voltar a um turno, aqui a leitura **e** a funcao — sem ela nao ha
    *replay*, e sem *replay* nao ha idempotencia.

    O `DELETE` e so do `kamba_batch`, que e quem corre a retencao (`BYPASSRLS`,
    fora de qualquer pedido, como a do `lg` no KAM-026). O papel da aplicacao
    **nao apaga**: uma reserva que o proprio turno pudesse apagar nao era uma
    barreira, era um cache. E ele tem `SELECT, DELETE` e nao os quatro de dados
    que tem nas outras: quem purga nao insere nem altera.

    **O `kamba_audit` nao ganha nada**, pela razao que o `_uso` do
    `test_privilegios` escreveu para os contadores do KAM-009 — quem audita le o
    `audit_log`, e esta tabela nao e um registo de auditoria, e estado de
    trabalho. Um `SELECT` «por precaucao» era privilegio morto, que e o que o
    KAM-026 pagou para aprender.

    O `kamba_agr` nao ganha nada, aqui como em todo o `platform` (KAM-026).
    """
    op.execute(
        f"GRANT INSERT ({COLUNAS_DO_INSERT}) "
        "ON platform.tool_idempotency TO kamba_app"
    )
    op.execute(
        f"GRANT UPDATE ({COLUNAS_DO_UPDATE}) "
        "ON platform.tool_idempotency TO kamba_app"
    )
    op.execute("GRANT SELECT ON platform.tool_idempotency TO kamba_app")
    op.execute("GRANT SELECT, DELETE ON platform.tool_idempotency TO kamba_batch")


def _codigo_novo_na_tool_audit() -> None:
    """O decimo primeiro codigo tipado entra no `CHECK` fechado da `0021`.

    Nao e arrumacao: o passo 7 escreve uma linha de `tool_audit` por invocacao,
    **inclusive pelas recusas**, e a recusa do criterio 3 tem este codigo. Sem
    isto, a primeira vez que a idempotencia recusasse um `cart_id` reutilizado,
    o `INSERT` da linha que o registava violava a restricao e a invocacao
    rebentava com um defeito de base em vez de devolver a recusa.
    """
    op.execute("ALTER TABLE platform.tool_audit DROP CONSTRAINT tool_audit_error_code")
    op.execute(
        "ALTER TABLE platform.tool_audit ADD CONSTRAINT tool_audit_error_code "
        f"CHECK (error_code IN ({LITERAIS_DE_ERRO}))"
    )


def downgrade() -> None:
    # **O dominio do `error_code` nao se estreita de volta, e e deliberado.**
    #
    # Tres razoes, por ordem de peso. A primeira: o decimo primeiro codigo passou
    # a ser **canon** (dicionario §3.28), e um `downgrade` que o retirasse da
    # base deixava o esquema a discordar do dicionario — o *gate* 3b falharia
    # sobre uma base que o proprio `downgrade` produziu. A segunda: uma linha de
    # `tool_audit` que ja tenha o codigo faz o `ADD CONSTRAINT` estreito falhar
    # (`23514`), pelo que o `downgrade` parava a meio, com a tabela ja largada se
    # a ordem fosse a outra. A terceira: um dominio mais largo nao perde dados
    # nem quebra chamador nenhum — nada escreve o codigo depois de a camada o
    # deixar de devolver.
    #
    # O que **e** reversivel e o que esta revisao criou: a tabela, a politica e os
    # privilegios. A assimetria esta escrita aqui e na secao de verificacao do
    # bloco, em vez de ser escondida por um `downgrade` que parecia simetrico.
    rls.disable_tenant_rls("tool_idempotency")
    op.execute("DROP TABLE platform.tool_idempotency")

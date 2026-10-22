"""Restricao de canal: o motivo e os codigos de erro vistos (KAM-023).

A primeira linha e **sem acentos**, como as doze revisoes anteriores, e isso nao
e estilo: ela e a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao e o teste falha sem dizer porque.

Duas colunas em `platform.tenant_channels`, e são a metade deste ticket que
**não cabia sem DDL**:

    motivo_restricao        porque e que o canal esta restrito. Lista fechada.
    meta_error_codes_seen   os codigos que a Meta ja devolveu neste canal.

O contador do *free tier* **não entra aqui**: `free_tier_used` e
`free_tier_month` existem desde a `0001`, já estão no `GRANT UPDATE` de
`kamba_app`, e o `docstring` da `0010` entrega-lhes a manutenção a este ticket
por extenso. Esta revisão é só o que os critérios 5 e 6 pedem a mais.

## Porque é que esta revisão nasce depois da `0012`, e não ao lado dela

Porque as revisões de base **encaixam uma na anterior** pelo `down_revision`, e
duas a reclamar o mesmo pai não são uma colisão mecânica — o Alembic recusa. O
KAM-020 tinha a `0012` num ramo quando este ticket começou, e a metade de código
deste ticket foi entregue sem DDL precisamente para não ficar à espera. Esta
revisão entra quando a `0012` chegou a `main`, que é o que aconteceu.

## `motivo_restricao`: uma lista fechada, e **qualificada**

O domínio é `('payment_method', 'quality', 'policy')` e o `CHECK` chama-se
`tenant_channels_motivo_restricao_ck` — **qualificado pela tabela**, e isso não
é estilo. A regra da emenda 1.14 do dicionário faz um domínio sobre um nome
genérico valer para **todas** as colunas com esse nome, e há cinco colunas
`estado` com `CHECK` nas revisões `0001`, `0003` e `0005` que um domínio nu
tornaria vermelhas no *gate* 3b. Foi medido no KAM-019 e repetiu-se no KAM-020.

Os três valores, e porquê três quando o critério só nomeia um:

* `payment_method` é o deste ticket (critério 6);
* `quality` é o do KAM-021, que restringe por `quality_rating` RED;
* `policy` é o do KAM-017, para uma restrição vinda de `account_alerts`.

Os dois últimos **nascem aqui** pela mecânica que a emenda 1.20 já pagou e que
a `0010` repetiu para o `suppressed_by_human`: o *gate* 3b lê o AST de cada
revisão **isoladamente** e compara o `CHECK` com uma entrada por coluna, pelo
que alargar o domínio numa revisão posterior deixava **esta** vermelha por lhe
«faltar» um valor. As migrações daqueles tickets ficam sem trabalho nesta
coluna.

A coluna é **anulável**, e o `NULL` é o estado normal: «este canal não está
restrito». Um `NOT NULL DEFAULT 'nenhum'` acrescentava um quarto valor ao
domínio só para dizer a ausência, e depois toda a leitura tinha de o conhecer.

## `meta_error_codes_seen`: um `int[]`, e não uma tabela

O critério 5 diz «cada código de erro visto é guardado em
`meta_error_codes_seen`» e os *Testes Requeridos* pedem «X-03 sobre
`meta_error_codes_seen`». Lido à letra, é um **conjunto por canal** — e um
conjunto pequeno: os códigos da Meta são dezenas, não milhões.

Fica coluna e não tabela por três razões, por esta ordem:

1. **O X-03 passa a ser o de `tenant_channels`**, que já existe e já corre. Uma
   tabela nova obrigava a uma receita de sementes em
   `db/tests_isolamento/sementes.py` — e uma tabela com `tenant_id` que a suite
   não saiba semear **falha o *gate* 6**, que é a regra que o
   `docs/isolamento.md` escreve.
2. **O conjunto não tem história.** O critério quer saber *quais* códigos
   apareceram, para calibrar a heurística e identificar o da falta de pagamento
   (que é NÃO VERIFICADO). Não pede quando, nem quantas vezes. Uma tabela
   dava-nos as duas e custava uma junção em cada leitura.
3. **O `int[]` é o tipo do dado.** Os códigos da Meta são inteiros
   (`2593109`, `130429`, `131049`), e um `jsonb` punha-os num saco onde a base
   não sabe que são números.

**E tem tecto, com `CHECK`.** Trinta e dois códigos distintos por canal. Não é
defensividade gratuita: a coluna é escrita pelo caminho de um *webhook*, e uma
Meta que comece a devolver códigos novos — ou um defeito nosso que guarde o
`error_code` errado — fazia crescer um `int[]` numa linha que é lida em cada
envio. O tecto transforma isso num erro visível em vez de uma degradação lenta.
Trinta e dois é **proposta**: o `E1` nomeia três códigos e não há base para
saber quantos existem.

## O que esta revisão NÃO faz, e é escopo e não esquecimento

* **Não cria estado para «já avisei aos 800»**, e não é esquecimento: o aviso é
  um **flanco**, lido do `antes`/`depois` do próprio `UPDATE` que incrementa, e
  por isso não precisa de coluna. Ver `packages/core-ts/src/metering/`.
* **Não dá fuso por canal.** O critério 3 pede «o fuso configurado do canal» e
  a única coluna de fuso é a de `tenants`, por *tenant*. Criá-la aqui era
  decidir, de fora do KAM-023, que um *tenant* pode ter dois fusos — e nenhum
  critério deste ticket o pede. Fica na dívida 66.
* **Não muda o `estado` do canal.** O `tenant_channels.estado` já tem
  `restrito` desde a `0001`, e quem o move é o ticket que decide restringir de
  facto (KAM-021 por qualidade, KAM-094 no gate de activação). Este ticket
  **marca o motivo** e emite o evento; passar o canal a `restrito` por suspeita
  de cartão era cortar a loja por uma heurística de limiares *propostos*.
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

#: Os motivos pelos quais um canal pode ficar restrito. Lista fechada, imposta
#: por `CHECK` (dicionario §3.17, emenda 1.25).
#:
#: Os valores vem **ja entre apostrofos**, e isso nao e desleixo: e a unica
#: forma que o *gate* 3b resolve. Ele le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*.
MOTIVOS_DE_RESTRICAO = ("'payment_method'", "'quality'", "'policy'")

#: Quantos codigos distintos cabem no conjunto de um canal. **Proposta**: o `E1`
#: nomeia tres codigos e nao ha base para saber quantos existem.
TECTO_DE_CODIGOS = 32

#: As colunas de `tenant_channels` que `kamba_app` pode alterar **depois** desta
#: revisao, ja em SQL. E a lista da `0001` mais as duas novas, e escreve-se por
#: inteiro em vez de um `GRANT` das duas sozinhas por duas razoes, as mesmas que
#: a `0007` escreveu: quem vier aqui ver o que a aplicacao pode fazer le uma
#: lista, e nao uma lista mais uma adicao noutro ficheiro; e o *gate* 3b le o
#: **texto** das instrucoes sem as executar, pelo que uma lista montada por
#: `join` deixava-o sem nada para ler.
#:
#: **O `kamba_app` precisa de `UPDATE` nas duas**, e nao so numa: e ele que corre
#: o adaptador que consome os `statuses` da Meta, e e dali que saem tanto a marca
#: do motivo como o codigo de erro visto. Nenhuma das duas e escrita por
#: retaguarda.
COLUNAS_QUE_A_APP_ALTERA = (
    "waba_id, waac_id, phone_number_id, channel_mode, vertical,\n"
    "                      estado, token_ref, quality_rating, messaging_limit,\n"
    "                      free_tier_used, free_tier_month, coexistence_synced_at,\n"
    "                      last_account_update_at, motivo_restricao,\n"
    "                      meta_error_codes_seen"
)


def upgrade() -> None:
    # --- as duas colunas ---------------------------------------------------
    #
    # `ADD COLUMN` com omissao constante nao reescreve a tabela desde o
    # PostgreSQL 11, pelo que isto nao e uma migracao longa — o que importa
    # porque `tenant_channels` e lida em cada envio.
    op.execute(
        f"""
        ALTER TABLE platform.tenant_channels
          ADD COLUMN motivo_restricao text
            CONSTRAINT tenant_channels_motivo_restricao_ck
            CHECK (motivo_restricao IN ({", ".join(MOTIVOS_DE_RESTRICAO)})),
          ADD COLUMN meta_error_codes_seen integer[] NOT NULL DEFAULT '{{}}'
            CONSTRAINT tenant_channels_meta_error_codes_seen_ck
            CHECK (
                   array_length(meta_error_codes_seen, 1) IS NULL
                OR array_length(meta_error_codes_seen, 1) <= {TECTO_DE_CODIGOS}
            )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.tenant_channels.motivo_restricao IS "
        "'Porque e que o canal esta restrito. NULL e o estado normal. "
        "O payment_method e do KAM-023 (deteccao em runtime, nao verificacao "
        "no Billing Hub, que e o KAM-093); o quality e do KAM-021 e o policy "
        "do KAM-017, e nascem aqui pela mecanica do gate 3b.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.tenant_channels.meta_error_codes_seen IS "
        f"'Conjunto dos codigos de erro que a Meta ja devolveu neste canal, "
        f"ate {TECTO_DE_CODIGOS}. Serve para calibrar a heuristica do KAM-023 e "
        f"para identificar o codigo da falta de metodo de pagamento, que e NAO "
        f"VERIFICADO em toda a evidencia.'"
    )

    # --- o privilegio ------------------------------------------------------
    #
    # Nao se usa `GRANT UPDATE (motivo_restricao, meta_error_codes_seen)` por
    # cima: o PostgreSQL guarda a concessao por coluna, e acrescentar duas
    # deixava a lista efectiva a divergir do que esta escrito em qualquer
    # sitio. Revoga-se a concessao inteira e concede-se a nova, como a `0007`
    # fez para `tenants`.
    op.execute("REVOKE UPDATE ON platform.tenant_channels FROM kamba_app")
    op.execute(
        f"""
        GRANT UPDATE ({COLUNAS_QUE_A_APP_ALTERA})
          ON platform.tenant_channels TO kamba_app
        """
    )


def downgrade() -> None:
    # **Nao repoe o privilegio, e isso foi medido.** A primeira versao fazia um
    # `REVOKE` da tabela e um `GRANT UPDATE` com a lista da `0001` antes do
    # `DROP COLUMN`, e parecia o cuidado certo. Nao e: o PostgreSQL **remove a
    # concessao com a coluna**, pelo que os treze grants da `0001` sobrevivem ao
    # `DROP` por si sos e o resultado e exactamente o mesmo.
    #
    # Quem o mostrou foi a prova por mutacao, pela negativa: ao declarar uma
    # mutacao que apagava aqueles dois `op.execute`, percebeu-se que **nenhum
    # teste a poderia matar** — e uma mutacao imortal nao e um teste em falta, e
    # um sinal de que o codigo nao faz nada. A asserção do
    # `test_desce_com_linhas_marcadas_e_sobe_outra_vez` continua a valer e a
    # provar a propriedade; o que mudou e que ela e garantida pela base e nao
    # por uma instrucao nossa a dizer o mesmo duas vezes.
    #
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou,
    # o `downgrade` falha em vez de o apagar em silencio. E a regra que todas
    # as revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados, ao contrario do `downgrade` da `0010`.** Aquele
    # recusa quando ha linhas, porque apagar `outbound_messages` perdia o
    # registo do que se enviou e cobrou. Aqui o que se perde e o motivo de uma
    # restricao e um conjunto de codigos de diagnostico: os dois reconstroem-se
    # do proximo `statuses` que chegar, e nenhum e prova de nada perante
    # terceiros. Uma guarda que obrigasse a uma variavel de ambiente para
    # desfazer duas colunas de diagnostico era cerimonia sem conteudo.
    op.execute(
        """
        ALTER TABLE platform.tenant_channels
          DROP COLUMN meta_error_codes_seen,
          DROP COLUMN motivo_restricao
        """
    )

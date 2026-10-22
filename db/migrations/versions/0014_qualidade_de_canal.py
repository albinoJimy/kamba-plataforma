"""Qualidade do canal: o registo das transicoes e o escalao (KAM-021).

A primeira linha e **sem acentos**, como as treze revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

Uma tabela e uma coluna:

    channel_quality_log                     o historico das transicoes
    tenant_channels.max_phone_numbers_per_business   o tecto de numeros do portfolio

As colunas `quality_rating` e `messaging_limit` **nao nascem aqui**: existem
desde a `0001` e ja estao no `GRANT UPDATE` de `kamba_app`. O que faltava era
onde guardar **a transicao** — o critério 1 pede «valor anterior, novo, evento,
hora» — e a chave que a torna idempotente.

## O `event_key`, e porque e composto com o `tenant_id`

O criterio 6 pede «o mesmo evento 2x gera 1 transicao», com a chave a ser o
resumo de `phone_number_id` + tipo + valor + marca temporal da Meta. A
unicidade e `(tenant_id, event_key)` e **nao** `event_key` global, pela razao
que a emenda 1.21 do dicionario escreveu para a `idempotency_key` da `0010`:
com unicidade global, um evento do *tenant* B que calhasse na mesma chave era
**deduplicado em silencio** contra uma linha de A. A chave e derivada de dados
da Meta que sao unicos na pratica; a composicao nao a torna mais fraca, torna
impossivel que um *tenant* engula o evento de outro.

**Ha um segundo nivel de deduplicacao, e e anterior a este.** O
`inbound_events (kind, event_key)` da `0008` ja recusa o corpo repetido com
`ON CONFLICT DO NOTHING`. Mas o `registo.ts` do KAM-013 diz por extenso que
registar e encaminhar **nao sao atomicos** e que «todo o tratador de destino tem
de ser idempotente»: um encaminhamento pode acontecer mais de uma vez para o
mesmo evento registado. Esta unicidade e a que fecha isso no tratador.

## O que a tabela **nao** tem: `UPDATE` para a aplicacao

E um registo de transicoes: uma linha dele e o facto de a Meta ter dito uma
coisa a uma hora. A aplicacao recebe `SELECT` e `INSERT` e mais nada — nao ha
`UPDATE` nem `DELETE` para `kamba_app`, pela mesma razao que o `usage_ledger` da
`0007` nao os tem. **Sem gatilho de imutabilidade**, ao contrario do
`audit_log_imutavel` da `0006`: ali a cadeia de *hash* precisa de uma garantia
que o privilegio por coluna nao sabe exprimir; aqui o privilegio diz tudo o que
ha a dizer, e um gatilho era cerimonia.

## O `max_phone_numbers_per_business` fica em `tenant_channels`, e e desnormalizado

E um atributo do **portfolio** (da WABA), nao do canal: o
`business_capability_update` di-lo uma vez para a conta inteira. Nao existe
tabela de WABA neste esquema — o `waba_id` e uma coluna de `tenant_channels`
desde a `0001` —, pelo que guardar por canal e a unica forma sem criar uma
tabela que nenhum criterio pede. Dois canais da mesma WABA guardam o mesmo
numero, e isso e desnormalizacao assumida: esta escrita no `COMMENT` da coluna e
no dicionario.

## O que esta revisao NAO faz, e e escopo e nao esquecimento

* **Nao devolve `UPDATE (estado)` a `kamba_app` em `platform.tenants`.** O
  criterio 3 do KAM-021 quer que `tenants.estado` projecte `restrito`, e a
  revisao `0007` **retirou** esse privilegio de proposito — a razao esta escrita
  la: «`UPDATE platform.tenants SET estado = 'ativo'` com o proprio contexto
  **passa** […] o sujeito da condicao nao pode ser quem a retira». O
  `db/tests/test_privilegios.py` prende-o. Devolve-lo aqui reabria exactamente
  a escalada que a revisao adversarial da `0007` fechou, por causa de um
  criterio de outro ticket. **A caixa do criterio 3 fica vazia**, com a razao na
  seccao de verificacao, e a decisao devolve-se a quem escreveu o criterio.
* **Nao muda a matriz de `ten/estados.ts`.** Ela e do KAM-009, tem espelho em
  Python e paridade imposta pelo X-11; o `restrito` ja permite `responder_sessao`
  e recusa `marketing` e `utility`. O criterio 2 descreve o mesmo com outras
  palavras e so nomeia o `marketing` — a matriz e mais restritiva, que e o lado
  seguro, e a divergencia fica registada.
* **Nao cria tabela de *tickets* para T&S** (criterios 4 e 8). Nao existe
  mecanismo de *ticket* neste repositorio; o que existe sao contadores e
  registo. Criar um sistema de *tickets* a partir de um criterio de um ticket de
  canais era alargar o escopo em silencio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

#: Os quatro webhooks de gestao de canal cujas transicoes se registam. Sao
#: exactamente os quatro `kind` que o `DESTINO_POR_KIND` do
#: `packages/core-ts/src/entrada/contrato.ts` manda para `gestao_de_canal`, e um
#: teste compara as duas listas.
#:
#: Os valores vem **ja entre apostrofos**: e a unica forma que o *gate* 3b
#: resolve, porque le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*.
EVENTOS_DE_QUALIDADE = (
    "'phone_number_quality_update'",
    "'business_capability_update'",
    "'account_alerts'",
    "'message_template_quality_update'",
)

#: As colunas de `tenant_channels` que `kamba_app` pode alterar depois desta
#: revisao: a lista da `0013` mais o tecto de numeros do portfolio.
#:
#: Por inteiro e nao um `GRANT` da coluna sozinha, pela razao que a `0007`
#: escreveu e a `0013` repetiu: quem vier aqui ver o que a aplicacao pode fazer
#: le uma lista, e o *gate* 3b le o **texto** das instrucoes sem as executar.
COLUNAS_QUE_A_APP_ALTERA = (
    "waba_id, waac_id, phone_number_id, channel_mode, vertical,\n"
    "                      estado, token_ref, quality_rating, messaging_limit,\n"
    "                      free_tier_used, free_tier_month, coexistence_synced_at,\n"
    "                      last_account_update_at, motivo_restricao,\n"
    "                      meta_error_codes_seen, max_phone_numbers_per_business"
)


def upgrade() -> None:
    # ------------------------------------------------- o tecto do portfolio
    op.execute(
        """
        ALTER TABLE platform.tenant_channels
          ADD COLUMN max_phone_numbers_per_business integer
            CONSTRAINT tenant_channels_max_phone_numbers_ck
            CHECK (
                   max_phone_numbers_per_business IS NULL
                OR max_phone_numbers_per_business > 0
            )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.tenant_channels.max_phone_numbers_per_business IS "
        "'Tecto de numeros do portfolio, do business_capability_update. E um "
        "atributo da WABA e nao do canal: guarda-se por canal porque nao ha "
        "tabela de WABA neste esquema, e dois canais da mesma conta guardam o "
        "mesmo numero. Desnormalizacao assumida (KAM-021).'"
    )

    # -------------------------------------------- o registo das transicoes
    op.execute(
        f"""
        CREATE TABLE platform.channel_quality_log (
            id             uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id      uuid        NOT NULL,
            channel_id     uuid        NOT NULL,
            evento         text        NOT NULL,
            -- Anulavel, e o `NULL` tem significado: e a **primeira** linha de
            -- um canal, onde nao havia valor anterior. Um `''` ou um
            -- `'desconhecido'` punham uma leitura a decidir se o canal nasceu
            -- assim ou se alguem nao soube ler.
            valor_anterior text,
            valor_novo     text        NOT NULL,
            -- A hora que a Meta diz, nao a nossa: e por ela que a sequencia se
            -- ordena quando os webhooks chegam fora de ordem (CONFIRMADO,
            -- `E1` §5: a Meta nao garante ordem).
            ocorrido_em    timestamptz NOT NULL DEFAULT now(),
            event_key      text        NOT NULL,
            CONSTRAINT channel_quality_log_pkey PRIMARY KEY (id),
            -- **A idempotencia do criterio 6, e e da base.** Composta com o
            -- `tenant_id`: ver a nota do modulo.
            CONSTRAINT channel_quality_log_event_key_uq
                UNIQUE (tenant_id, event_key),
            CONSTRAINT channel_quality_log_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta com o `tenant_id`**, pela razao que a `0009` fixou e a
            -- `0011` e a `0012` repetiram: sem ele, uma transicao de A podia
            -- apontar para um canal de B, e nem o *gate* 6 nem o 3b o veriam.
            CONSTRAINT channel_quality_log_channel_fk
                FOREIGN KEY (tenant_id, channel_id)
                REFERENCES platform.tenant_channels (tenant_id, id),
            CONSTRAINT channel_quality_log_evento_ck
                CHECK (evento IN ({", ".join(EVENTOS_DE_QUALIDADE)})),
            -- Um valor vazio nao e um valor. A mesma forma do `token_ref` da
            -- `0001`.
            CONSTRAINT channel_quality_log_valor_novo_ck
                CHECK (btrim(valor_novo) <> ''),
            CONSTRAINT channel_quality_log_valor_anterior_ck
                CHECK (valor_anterior IS NULL OR btrim(valor_anterior) <> ''),
            CONSTRAINT channel_quality_log_event_key_ck
                CHECK (btrim(event_key) <> '')
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_quality_log.valor_novo IS "
        "'O valor que a Meta anunciou, **tal e qual**, mesmo quando nao e um "
        "dos tres que conhecemos (GREEN, YELLOW, RED). O criterio 1 manda "
        "registar um valor desconhecido sem falhar: guardar o que chegou e o "
        "que permite descobrir depois o que ela passou a mandar.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_quality_log.event_key IS "
        "'Resumo de phone_number_id + tipo + valor + marca temporal da Meta "
        "(criterio 6). E o segundo nivel de deduplicacao: o primeiro e o "
        "inbound_events (kind, event_key) da 0008, e existe porque registar e "
        "encaminhar nao sao atomicos — um encaminhamento pode repetir-se.'"
    )

    # O indice comeca pelo `tenant_id` **porque a RLS o le em toda a consulta**,
    # e so depois pela hora, que e por onde se le um historico. A licao e da
    # `0011`, onde o *gate* 8 recusou a tabela sem ele.
    op.execute(
        "CREATE INDEX channel_quality_log_tenant_idx "
        "ON platform.channel_quality_log (tenant_id, ocorrido_em DESC)"
    )

    rls.enable_tenant_rls("channel_quality_log")

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela, sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce
    # acessivel (`db/migrations/README.md`).
    #
    # **`SELECT, INSERT` e mais nada para a aplicacao.** O `SELECT` e preciso e
    # nao e generoso: o `INSERT ... ON CONFLICT (tenant_id, event_key) DO
    # NOTHING RETURNING` exige `SELECT` nas colunas de inferencia — a licao que
    # a `0008` escreveu e a `0012` repetiu. O que **nao** ha e `UPDATE` nem
    # `DELETE`: uma linha deste registo e o facto de a Meta ter dito uma coisa a
    # uma hora, e um facto nao se corrige.
    op.execute(
        "GRANT SELECT, INSERT ON platform.channel_quality_log TO kamba_app"
    )
    # O `kamba_batch` tem os quatro verbos, que e o que tem em todas as outras
    # desde a `0001`, porque e quem purga.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.channel_quality_log "
        "TO kamba_batch"
    )

    # ----------------------------------------- a coluna nova no privilegio
    #
    # Nao se usa `GRANT UPDATE (max_phone_numbers_per_business)` por cima: o
    # PostgreSQL guarda a concessao por coluna, e acrescentar uma deixava a
    # lista efectiva a divergir do que esta escrito em qualquer sitio. Revoga-se
    # a concessao inteira e concede-se a nova, como a `0007` e a `0013` fizeram.
    op.execute("REVOKE UPDATE ON platform.tenant_channels FROM kamba_app")
    op.execute(
        f"""
        GRANT UPDATE ({COLUNAS_QUE_A_APP_ALTERA})
          ON platform.tenant_channels TO kamba_app
        """
    )


def downgrade() -> None:
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou,
    # o `downgrade` falha em vez de o apagar em silencio. E a regra que todas as
    # revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados.** O da `0010` recusa com linhas, porque apagar
    # `outbound_messages` perde o registo do que se enviou e cobrou. Aqui o que
    # se perde e o historico das transicoes de qualidade: a Meta reenvia os
    # `statuses` e o estado corrente vive em `tenant_channels.quality_rating`,
    # que esta revisao nao cria e nao apaga. O historico reconstroi-se do que
    # chegar a seguir, e nao e prova de nada perante terceiros.
    #
    # **Nao repoe o privilegio de `tenant_channels`**, e isso foi medido na
    # `0013`: o PostgreSQL remove a concessao **com** a coluna, pelo que as
    # quinze da `0013` sobrevivem ao `DROP COLUMN` por si sos. Uma mutacao que
    # apagasse um `REVOKE`/`GRANT` aqui nao podia ser morta por teste nenhum, e
    # uma mutacao imortal e um sinal de que o codigo nao faz nada.
    rls.disable_tenant_rls("channel_quality_log")
    op.execute("DROP INDEX platform.channel_quality_log_tenant_idx")
    op.execute("DROP TABLE platform.channel_quality_log")
    op.execute(
        "ALTER TABLE platform.tenant_channels "
        "DROP COLUMN max_phone_numbers_per_business"
    )

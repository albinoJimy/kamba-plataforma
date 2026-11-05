"""Reservas de stock: a tabela, a autoridade de quantidade e as barreiras (KAM-045).

A primeira linha e **sem acentos**, como as trinta e duas revisoes anteriores: e
a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria

A `platform.stock_reservations` do mesmo bloco SQL de `docs/tecnica/03` §5.4 que
a `0030` deixou por criar com o credor escrito — e com ela a coisa que faltava
para que uma reserva signifique alguma coisa: **uma autoridade de quantidade**.

A `offer_terms` da `0028` tem `stock_modo` e **nao tem coluna de quantidade**. O
§5.4 poe o stock no Registo, e o Registo da opcao B e um Medusa que nao existe
em `infra/compose/`. O dicionario registou isto por escrito no §3.43 («a reserva
de stock e a autoridade que sustenta o `OUT_OF_STOCK`: a `offer_terms` **nao tem
coluna de quantidade** ... a **passagem** do codigo esta implementada e medida; a
**fonte** falta — **KAM-045**»), e e esta revisao que a entrega: duas colunas na
`offer_terms`, que e a tabela que ja e autoridade do SKU e cuja chave primaria
composta `(tenant_id, sku)` faz da colisao de SKU entre tenants um nao-problema
por construcao — o criterio 8 (ISO-33..38 e ISO-51..56) sai dela de graca, como
saiu para o preco no KAM-043.

## `expira_at` e **nao** `expires_at`, e a divergencia e com o proprio ticket

Os *Detalhes Tecnicos* do bloco KAM-045 escrevem «indice parcial por
`expires_at WHERE estado='ativa'`», e o DDL do §5.4 escreve `expires_at`. **As
duas formas estao preteridas**, e a migracao que as usasse falhava o *gate* 3b
por um nome que o documento tecnico manda usar — o que nao e uma hipotese: e a
consequencia que a emenda **1.12** do dicionario mediu e escreveu para esta
tabela pelo nome, depois de a emenda 1.11 ter resolvido a divergencia a favor de
`expira_at` sem registar a variante.

O nome canonico e **`expira_at`**, pela linha «Prazo de uma reserva ou de uma
referencia» do §3.3, e e o mesmo nome que o `orders_mirror` da `0030` ja usa para
a mesma ideia e que o payload dos eventos leva (§3.5). Divergencia resolvida a
favor do dicionario, que e o nivel 4 das fontes de verdade contra o nivel 8 do
ticket.

## A barreira do criterio 1 e **duas**, e as duas sao medidas

O criterio 1 pede «1.000 tentativas paralelas de reserva sobre stock 10 em
`garantido` produzem **0** reservas acima do stock e exactamente 10
bem-sucedidas». Sao duas afirmacoes diferentes, e cada uma tem a sua barreira:

```text
exactamente 10 bem-sucedidas   o predicado aritmetico no proprio UPDATE
0 reservas acima do stock      o CHECK `stock_reservada <= stock_quantidade`
```

**O predicado** e o `UPDATE ... SET stock_reservada = stock_reservada + :q WHERE
stock_quantidade - stock_reservada >= :q` dos *Detalhes Tecnicos*. Nao leva
`FOR UPDATE`, e isso **nao** e um esquecimento: sob `READ COMMITTED` a segunda
transaccao espera pela primeira na tranca da linha e **reavalia** o `WHERE`
sobre o valor novo dela. E a medicao que o `test_concorrencia` do KAM-044 pagou
e escreveu («o predicado do estado, sozinho, serializa»), e vale letra por letra
para a aritmetica: um `SELECT ... FOR UPDATE` seguido de `UPDATE` faz o mesmo
trabalho em duas viagens. O que **nao** serializa e ler num comando e escrever
noutro com o valor lido, e e essa a mutacao do canario.

**O CHECK** existe porque o predicado vive no modulo e o criterio diz «0», nao
«0 enquanto o modulo estiver certo». Com ele, sobrevender e impossivel por
construcao: um `UPDATE` a mao de quem tem o privilegio e recusado, e o caminho
que falhe o predicado falha **ruidosamente** em vez de prometer stock que nao
existe. E a mesma escolha do `orders_mirror_paga_exige_via_ck` da `0030` — o
criterio na coluna, e nao so na funcao.

## Um `garantido` sem quantidade e recusado

O `offer_terms_stock_garantido_exige_quantidade_ck` e o *fail-closed* da
governacao: `stock_modo = 'garantido'` e uma promessa de exclusividade, e uma
promessa sem numero nao se pode cumprir. O `indicativo` e o `confirmar_dono`
continuam a aceitar `stock_quantidade` nula, que e o estado de toda a Fase 0
para quem nao declarou stock — e o criterio 8 diz o que isso significa:
«`stock_modo='indicativo'` reserva internamente sem promessa de exclusividade».

## Os tres estados, e porque os terminais sao terminais

`ativa`, `consumida`, `libertada`. O `estado='ativa'` do indice parcial e o nome
que os *Detalhes Tecnicos* do bloco escrevem, e os outros dois saem dos
criterios 5 e 6 («a reserva fica `consumida`»; «`releaseReservation` aceita os
motivos `expirada`, `cancelada`, `recusada_dono`»).

O `stock_reserva_estado_terminal` recusa qualquer mudanca de estado a partir de
um estado que nao seja `ativa`. E a idempotencia do criterio 4 («execucao dupla
= 1 libertacao») como **restricao** e nao como convencao de modulo: a segunda
libertacao nao casa linha nenhuma pelo `WHERE estado = 'ativa'` do modulo, e uma
que forcasse e recusada com `KA009`. Sem isto, dois *workers* a varrer em
simultaneo — que e o que os *Testes Requeridos* pedem — devolviam o stock duas
vezes, e o `stock_reservada` descia abaixo de zero.

## O `downgrade` e o espelho do `upgrade`, linha a linha

Chama `rls.disable_tenant_rls` **explicitamente**, e nao deixa a politica cair
por efeito do `DROP TABLE`. As politicas caem de qualquer forma com a tabela; o
que nao cai e o ensaio de mutacao
`canon_lint...TestMutacoes.test_auxiliar_que_deixa_de_se_seguir`, que quebra o
`db/rls.py` de proposito e exige que **todas** as revisoes com RLS alcancem o
auxiliar directamente. Uma revisao que o alcancasse so no `upgrade` ficava do
lado errado do *gate* 4.

As duas colunas da `offer_terms` saem com `DROP COLUMN`, e os `CHECK` delas saem
com elas. **Nenhuma funcao desta revisao e `CREATE OR REPLACE`**: as duas nascem
aqui, pelo que o `downgrade` apaga-as em vez de repor uma versao anterior que
nao existe. E nenhum *trigger* fica pendurado sobre tabela que esta revisao nao
apague — os dois sao sobre a `stock_reservations`, que cai aqui.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0033"
down_revision = "0031"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
RESERVAS = "platform.stock_reservations"
OFERTA = "platform.offer_terms"

#: Os **tres** estados de uma reserva. Ja entre apostrofos, pela razao da `0015`:
#: e a unica forma que o *gate* 3b resolve, porque segue
#: `", ".join(<constante de modulo>)` dentro de uma f-string.
ESTADOS_DA_RESERVA = ("'ativa'", "'consumida'", "'libertada'")

#: O estado em que uma reserva nasce, e o unico a partir do qual ela muda. E o
#: nome que o indice parcial dos *Detalhes Tecnicos* do bloco escreve.
ATIVA = "'ativa'"

#: Os **tres** motivos de libertacao do criterio 6, que sao os mesmos que o
#: `MOTIVOS_DE_LIBERTACAO` de `services/com/src/port/contrato.ts` ja fixa.
MOTIVOS_DE_LIBERTACAO = ("'expirada'", "'cancelada'", "'recusada_dono'")

#: O modo de stock que promete exclusividade, e o unico que exige quantidade.
#: O dominio dos tres esta no `offer_terms_stock_modo_ck` da `0028`.
GARANTIDO = "'garantido'"

#: Os SQLSTATE proprios desta revisao, a seguir aos cinco da `0030` (`KA003` a
#: `KA007`) e aos dois da `0007`. Codigos proprios e nao `check_violation` para
#: todos: a porta `CommerceRegistry` traduz cada recusa para um erro diferente,
#: e com um codigo unico nao ha como as distinguir sem ler texto.
SQLSTATE_VERSAO = "KA008"
SQLSTATE_TERMINAL = "KA009"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"

#: O que o `kamba_app` pode alterar numa reserva, coluna a coluna.
#:
#: **Nao e `UPDATE` de tabela inteira**, pela razao que a revisao adversarial da
#: `0028` ensinou. Ficam de fora o `id`, o `tenant_id`, o `order_id`, o
#: `line_no`, o `sku`, o `qty` e o `criado_at`: mudar o `sku` ou o `qty` de uma
#: reserva activa era reservar outra coisa sem o dizer, e mudar o `order_id` era
#: passar a reserva para outra encomenda.
UPDATE_DA_APP_EM_RESERVAS = (
    "estado",
    "motivo",
    "expira_at",
    "confirmada_at",
    "consumida_at",
    "libertada_at",
    "version",
    "atualizado_at",
)

#: As duas colunas que esta revisao acrescenta a `offer_terms`, e que entram no
#: `GRANT UPDATE` por coluna dela.
#:
#: A `stock_reservada` esta aqui porque e o modulo que a move, e e **por isso**
#: que o `CHECK` existe: um privilegio nao sabe exigir que o movimento passe
#: pelo predicado aritmetico, e a restricao sabe. A `stock_quantidade` esta aqui
#: porque e o dono que a declara, pelo `upsertProductDraft`.
UPDATE_DA_APP_EM_OFERTAS_NOVAS = ("stock_quantidade", "stock_reservada")


def upgrade() -> None:
    _stock_na_oferta()
    _stock_reservations()
    _funcoes()
    _triggers()
    _rls()
    _privilegios()


def _stock_na_oferta() -> None:
    """As duas colunas de quantidade na `offer_terms`, e os quatro `CHECK`."""
    op.execute(
        f"""
        ALTER TABLE {OFERTA}
            -- A quantidade que o dono declara. **Anulavel**, e nulo quer dizer
            -- «nao declarada» e nao «zero»: zero e uma afirmacao de que nao ha,
            -- e nulo e a ausencia de afirmacao, que e o estado de toda a Fase 0
            -- para quem nunca declarou stock. `bigint` como o `total_minor` da
            -- `0030`, e nao porque haja tanto stock: porque um `integer` obriga
            -- quem some a pensar no limite, e aqui nao ha nada a ganhar com ele.
            ADD COLUMN stock_quantidade bigint,
            -- Quanto da quantidade esta prometido a reservas `ativa`. **`NOT
            -- NULL DEFAULT 0`**, e nao anulavel: `NULL + 1` e `NULL`, e uma
            -- coluna anulavel fazia o predicado aritmetico do criterio 1
            -- devolver `NULL` — que num `WHERE` nao e verdadeiro, pelo que o
            -- `UPDATE` casava zero linhas e **toda** a reserva era recusada.
            -- Falha fechada, mas pelo lado silencioso e sobre a oferta errada.
            ADD COLUMN stock_reservada bigint NOT NULL DEFAULT 0
        """
    )
    # **O preenchimento vem antes das restricoes, e nao e opcional.**
    #
    # Medido, e foi o `alembic upgrade head` a dize-lo: `23514 check constraint
    # "offer_terms_stock_garantido_exige_quantidade_ck" of relation
    # "offer_terms" is violated by some row`. A `offer_terms` existe desde a
    # `0028` e tem linhas `garantido` escritas **antes** de haver coluna de
    # quantidade — pelo que o invariante novo e violado por dados que o
    # precedem, e um `ADD CONSTRAINT` sobre tabela povoada falha.
    #
    # ## Zero e nao `NOT VALID`, e a escolha e sobre qual o lado seguro do erro
    #
    # A saida habitual do PostgreSQL para isto e `ADD CONSTRAINT ... NOT VALID`,
    # que impoe a regra as linhas novas e deixa as antigas como estao. **Aqui
    # era a saida errada:** as linhas que a violam sao exactamente as que
    # prometem exclusividade sem numero para a cumprir, e dispensa-las deixava o
    # invariante sem efeito precisamente onde ele faz falta.
    #
    # `stock_quantidade = 0` e o **fail-closed**: o predicado aritmetico do
    # criterio 1 le `0 - 0 >= :q` como falso, pelo que um SKU `garantido` cuja
    # quantidade ninguem declarou deixa de ser reservavel em vez de prometer
    # stock que ninguem contou. Nao inventa um numero — zero e a afirmacao «nao
    # ha», que e o que se sabe hoje sobre estas linhas — e desfaz-se com uma
    # declaracao do dono pelo `upsertProductDraft`.
    #
    # **O que isto custa fica dito:** um SKU `garantido` que hoje saia em
    # pesquisa deixa de poder ser encomendado ate o dono declarar stock. Nao ha
    # producao nem *staging* (nada corre migracoes contra base nenhuma — o
    # `db/migrations/README.md` registra-o), pelo que o universo afectado sao
    # as linhas das fixtures e das suites; em producao, o credor de avisar o
    # dono e o KAM-115.
    #
    # A alternativa de **demover** as linhas para `indicativo` foi recusada: o
    # `stock_modo` e uma escolha comercial do dono, e uma migracao que a mudasse
    # alterava o que o dono prometeu aos clientes dele sem ele saber.
    # ## O `NO FORCE` em volta do preenchimento, e porque ele e obrigatorio
    #
    # **Um `UPDATE` de preenchimento numa tabela com `FORCE ROW LEVEL SECURITY`
    # casa zero linhas, e nao da erro.** E o verde falso mais caro desta
    # revisao: o preenchimento estava escrito e correcto, corria, dizia
    # `UPDATE 0`, e o `ADD CONSTRAINT` a seguir falhava com o mesmo `23514` que
    # ele existia para evitar.
    #
    # A razao esta no `db/rls.py`, que a escreve para as funcoes `SECURITY
    # DEFINER` e vale letra por letra para uma revisao: a `0028` poe `FORCE` na
    # `offer_terms`, o `FORCE` **vincula tambem o dono**, e o dono e o
    # `kamba_migrator`, que e `NOBYPASSRLS`. Sem `app.tenant_id` definido, o
    # predicado da politica `tenant_iso` reduz-se a `tenant_id = NULL` — que nao
    # e verdadeiro para linha nenhuma. A revisao **nao ve** as linhas que vai
    # preencher.
    #
    # Nao ha contexto de tenant que sirva: o preenchimento atravessa todos os
    # tenants por desenho. E `SET ROLE` para o `kamba_batch` (o unico com
    # `BYPASSRLS`) esta fechado — o `db/bootstrap.py` **revoga activamente** toda
    # a pertenca entre papeis, e o `db/rls.py` registra que essa barreira nao se
    # afrouxa.
    #
    # O que resta e o que esta aqui: suspender o `FORCE` para a duracao do
    # preenchimento e repo-lo. **A politica fica no sitio** — o que se suspende e
    # so o «vincula o dono», pelo que nenhum papel sujeito a RLS ganha visao
    # nenhuma; e tudo corre dentro da transaccao da revisao
    # (`transaction_per_migration=True`), pelo que nao ha instante confirmado em
    # que a tabela esteja sem `FORCE`.
    #
    # O `test_em_head_os_objectos_existem` do `test_downgrade_0033.py` afirma o
    # par `(ENABLE, FORCE)` em `(True, True)` depois do `upgrade`, que e o ensaio
    # que impede este `NO FORCE` de ficar esquecido ligado.
    op.execute(f"ALTER TABLE {OFERTA} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        UPDATE {OFERTA}
           SET stock_quantidade = 0
         WHERE stock_modo = {GARANTIDO} AND stock_quantidade IS NULL
        """
    )
    op.execute(f"ALTER TABLE {OFERTA} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        ALTER TABLE {OFERTA}
            ADD CONSTRAINT offer_terms_stock_quantidade_ck
                CHECK (stock_quantidade IS NULL OR stock_quantidade >= 0),
            ADD CONSTRAINT offer_terms_stock_reservada_ck
                CHECK (stock_reservada >= 0),
            -- **O criterio 1 na coluna, e nao so no modulo.** Ver a nota do
            -- modulo: o predicado aritmetico do `UPDATE` da «exactamente 10», e
            -- este `CHECK` da «0 acima do stock» — e da-o contra **toda** a via
            -- de escrita, incluindo um `UPDATE` a mao de quem tem o privilegio.
            --
            -- Nulo do lado da quantidade deixa passar, e tem de deixar: um SKU
            -- `indicativo` sem quantidade declarada reserva internamente «sem
            -- promessa de exclusividade», que e a letra do criterio 8.
            ADD CONSTRAINT offer_terms_stock_nao_sobrevende_ck
                CHECK (stock_quantidade IS NULL
                       OR stock_reservada <= stock_quantidade),
            -- *Fail-closed* da governacao: `garantido` e uma promessa de
            -- exclusividade, e uma promessa sem numero nao se cumpre. Os outros
            -- dois modos continuam a aceitar quantidade nula.
            ADD CONSTRAINT offer_terms_stock_garantido_exige_quantidade_ck
                CHECK (stock_modo <> {GARANTIDO} OR stock_quantidade IS NOT NULL)
        """
    )
    op.execute(
        f"COMMENT ON COLUMN {OFERTA}.stock_quantidade IS "
        "'Quantidade declarada pelo dono. Nulo e «nao declarada», nao zero. "
        "Obrigatoria quando stock_modo = garantido (KAM-045).'"
    )
    op.execute(
        f"COMMENT ON COLUMN {OFERTA}.stock_reservada IS "
        "'Quanto da quantidade esta prometido a reservas ativa. Move-se pelo "
        "predicado aritmetico do criterio 1 do KAM-045; o CHECK "
        "offer_terms_stock_nao_sobrevende_ck impede a sobrevenda por qualquer "
        "via.'"
    )


def _stock_reservations() -> None:
    """A reserva de stock do §5.4, com o nome canonico do prazo."""
    op.execute(
        f"""
        CREATE TABLE {RESERVAS} (
            id            uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id     uuid        NOT NULL,
            order_id      uuid        NOT NULL,
            -- A linha da encomenda que esta reserva serve. O `lines_snapshot`
            -- do `orders_mirror` e um `jsonb` sem chaves proprias, pelo que a
            -- ligacao e pelo indice da linha — e e isso que a unicidade do
            -- bloco (`UNIQUE (order_id, line_no)`) fixa.
            line_no       integer     NOT NULL,
            -- O SKU reservado. Copiado e nao referenciado por FK: a reserva e
            -- do instante da encomenda, como o `lines_snapshot`, e um SKU
            -- apagado em `soft delete` nao pode invalidar uma reserva activa.
            sku           text        NOT NULL,
            qty           integer     NOT NULL,
            estado        text        NOT NULL DEFAULT 'ativa',
            -- A razao da libertacao, e **so** quando `libertada` (criterio 6).
            motivo        text,
            -- **O nome e `expira_at`, e a forma inglesa esta preterida.** A
            -- divergencia com o ticket e com o §5.4 esta na nota do modulo, que
            -- e Python e nao SQL — e **nao se repete aqui, de proposito**: o
            -- *gate* 3b le o texto das instrucoes, comentarios de SQL
            -- incluidos, e a forma antiga escrita neste sitio e um achado
            -- `[variante]` por si. Medido nesta revisao: a primeira versao
            -- explicava a divergencia aqui e o portao apanhou-a — o comentario
            -- que avisava para nao usar o nome usava-o.
            --
            -- `NOT NULL`, e o instante nasce provisorio: a reserva do criterio 3
            -- vive dois minutos a espera do `charge.issued`, e e o consumidor
            -- que o estende. Anulavel, o varrimento tinha de tratar o nulo como
            -- «nunca expira», e uma reserva provisoria cujo `charge.issued`
            -- nunca chegasse ficava a prender stock para sempre.
            expira_at     timestamptz NOT NULL,
            -- Quando o `charge.issued` fixou o prazo (criterio 3). Nulo e uma
            -- reserva **provisoria**; nao-nulo e uma reserva com cobranca
            -- emitida. A distincao nao e um quarto estado porque as duas sao
            -- `ativa` para todos os efeitos de stock: o que difere e o prazo.
            confirmada_at timestamptz,
            consumida_at  timestamptz,
            libertada_at  timestamptz,
            -- Concorrencia optimista, como no `orders_mirror`. O CAS do
            -- criterio 4 compara-a e o *trigger* exige que suba.
            version       integer     NOT NULL DEFAULT 1,
            criado_at     timestamptz NOT NULL DEFAULT now(),
            -- Escrito pelo modulo em cada `UPDATE`, nao por *trigger* — a mesma
            -- escolha da `0028` e da `0030`.
            atualizado_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT stock_reservations_pkey PRIMARY KEY (id),
            -- A unicidade do bloco. **Com o `tenant_id` a frente**, e nao o
            -- `(order_id, line_no)` nu que os *Detalhes Tecnicos* escrevem: o
            -- `order_id` e um UUID e ja e unico por si, pelo que o par nu
            -- bastava — mas um indice que nao principie pelo tenant nao serve
            -- consulta nenhuma desta tabela, que filtra sempre por tenant
            -- (RLS mais o `tenant_id = $1` que o repo-base exige).
            CONSTRAINT stock_reservations_linha_uq
                UNIQUE (tenant_id, order_id, line_no),
            CONSTRAINT stock_reservations_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta**, pela correccao de 2026-10-27 do §5.4 e pelo ISO-58
            -- do spike KAM-041: o `orders_mirror_tenant_id_uq` existe para que
            -- quem referencia a encomenda o faca pelo par, e uma FK simples
            -- deixava a reserva de A apontar para a encomenda de B.
            CONSTRAINT stock_reservations_encomenda_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, order_id)
                REFERENCES platform.orders_mirror (tenant_id, id),
            CONSTRAINT stock_reservations_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_RESERVA)})),
            -- **Sem `IS NULL OR`, e a coluna continua anulavel.** Um `CHECK`
            -- passa quando a expressao e verdadeira **ou nula**, e
            -- `NULL IN (...)` e nulo: a guarda explicita era redundante, e o
            -- *gate* 3b nao a le como dominio fechado (medido na `0030`).
            CONSTRAINT stock_reservations_motivo_ck
                CHECK (motivo IN ({", ".join(MOTIVOS_DE_LIBERTACAO)})),
            CONSTRAINT stock_reservations_sku_ck CHECK (btrim(sku) <> ''),
            -- Reservar zero nao e reservar, e reservar negativo era **devolver**
            -- stock pelo caminho da reserva — com o predicado aritmetico a
            -- deixar passar, porque `quantidade - reservada >= -1` e verdadeiro
            -- quase sempre.
            CONSTRAINT stock_reservations_qty_ck CHECK (qty > 0),
            CONSTRAINT stock_reservations_version_ck CHECK (version >= 1),
            CONSTRAINT stock_reservations_line_no_ck CHECK (line_no >= 0),
            -- Libertada sem motivo era uma libertacao que ninguem assume, e o
            -- criterio 6 enumera os tres motivos. Nos dois sentidos: um motivo
            -- escrito num estado que nao e `libertada` afirmava uma razao para
            -- uma coisa que nao aconteceu.
            CONSTRAINT stock_reservations_libertada_exige_motivo_ck
                CHECK ((estado = 'libertada')
                       = (motivo IS NOT NULL AND libertada_at IS NOT NULL)),
            CONSTRAINT stock_reservations_consumida_exige_instante_ck
                CHECK ((estado = 'consumida') = (consumida_at IS NOT NULL))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {RESERVAS} IS "
        "'Reservas de stock de 24 a 72 h com expiracao e libertacao por evento "
        "(KAM-045). A quantidade vive em offer_terms.stock_quantidade e o "
        "prometido em offer_terms.stock_reservada; esta tabela diz quem "
        "prometeu o que a quem. O prazo chama-se expira_at, nome canonico do "
        "dicionario secao 3.3; a forma inglesa do docs/tecnica/03 secao 5.4 "
        "esta preterida pela emenda 1.11. Dicionario 3.45.'"
    )
    # O varrimento da expiracao procura por instante e nao por tenant: corre por
    # toda a base, como *job* com `BYPASSRLS`. **Parcial no `ativa`**, que e o
    # indice dos *Detalhes Tecnicos* do bloco com o nome canonico da coluna: uma
    # reserva `consumida` ou `libertada` nunca volta a ser varrida, e deixa-las
    # no indice fazia-o crescer para sempre sobre linhas que ninguem consulta.
    op.execute(
        f"CREATE INDEX stock_reservations_expira_idx ON {RESERVAS} (expira_at) "
        "WHERE estado = 'ativa'"
    )
    # O `commitReservation` e o `releaseReservation` recebem o `orderId` e tocam
    # todas as linhas dele; o `getOrder` mostra as reservas da encomenda.
    op.execute(
        f"CREATE INDEX stock_reservations_encomenda_idx ON {RESERVAS} "
        "(tenant_id, order_id)"
    )
    # A contagem «reservas activas por tenant» da caixa 5 da DoD.
    op.execute(
        f"CREATE INDEX stock_reservations_tenant_estado_idx ON {RESERVAS} "
        "(tenant_id, estado)"
    )


def _funcoes() -> None:
    """A barreira que faz das regras do modulo uma barreira da base.

    **Uma funcao e nao duas, e as duas perguntas dentro do mesmo `IF`.** E a
    forma do `order_transicao_valida` da `0030`, e seguir-lhe a forma nao e
    gosto: e o que faz um `UPDATE` que **nao** muda o estado passar sem pedir
    nada.

    ## Porque e que a `version` so se exige na mudanca de estado

    A primeira versao desta revisao exigia `NEW.version > OLD.version` em
    **todo** o `UPDATE`, e isso proibia uma escrita legitima — um `UPDATE … SET
    expira_at = expira_at`, que e um toque sem efeito. Medido antes de correr:
    o `test_update_sem_where_so_toca_nas_linhas_de_a` do *gate* 6 corre
    exactamente essa instrucao sobre **todas** as tabelas com receita de
    semente e exige `rowcount = 1`; com a guarda em todo o `UPDATE`, a
    `stock_reservations` respondia `KA008` e a bateria generica ficava vermelha
    — e a leitura facil era «esta tabela nao pode ter receita», que e falsa.

    A `0030` ja tinha a resposta, e o comentario dela di-lo pelo nome: «a
    `version` tem de subir **de um** em cada mudanca de estado». A propriedade
    que o criterio 4 precisa e sobre **transicoes** («execucao dupla = 1
    libertacao, CAS por `version`»), nao sobre toques: o que nao pode acontecer
    e uma reserva mudar de estado duas vezes com a mesma versao, e e isso que
    fica imposto.

    E **de um** e nao «qualquer subida», tambem como a `0030`: uma reserva que
    saltasse de `version` 2 para 7 passava o CAS de quem leu a 2 e deixava
    cinco versoes sem transicao que as explique.
    """
    # **`SECURITY INVOKER`** (a omissao), pela medicao que o `db/rls.py`
    # documenta: `SECURITY DEFINER` troca o `current_user` pelo dono — que numa
    # revisao e o `kamba_migrator`, `NOBYPASSRLS` — e o `FORCE` vincula o dono
    # da tabela, pelo que a funcao veria zero linhas. Esta funcao nao le outra
    # tabela, pelo que o invocador chega.
    op.execute(
        f"""
        CREATE FUNCTION platform.stock_reserva_transicao_valida()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.estado IS DISTINCT FROM OLD.estado THEN
                -- A idempotencia do criterio 4 como restricao: `consumida` e
                -- `libertada` sao terminais. A segunda libertacao nao casa
                -- linha nenhuma pelo `WHERE estado = 'ativa'` do modulo; esta
                -- e a barreira para quem o forcasse.
                IF OLD.estado <> 'ativa' THEN
                    RAISE EXCEPTION
                        'stock_reservations: % e terminal e nao volta a %',
                        OLD.estado, NEW.estado
                        USING ERRCODE = '{SQLSTATE_TERMINAL}';
                END IF;
                -- **De um**, como no `orders_mirror`. Ver a nota da funcao.
                IF NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION
                        'stock_reservations: a version sobe de um em cada '
                        'mudanca de estado, de % para %',
                        OLD.version, NEW.version
                        USING ERRCODE = '{SQLSTATE_VERSAO}';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.stock_reserva_transicao_valida() IS "
        "'As duas barreiras da mudanca de estado de uma reserva (KAM-045): "
        "consumida e libertada sao terminais (KA009), e a version sobe de um em "
        "cada mudanca (KA008). Um UPDATE que nao mude o estado nao pede nada.'"
    )


def _triggers() -> None:
    """O *trigger* por linha, sobre a `stock_reservations`.

    **`FOR EACH ROW` e nao `FOR EACH STATEMENT`**: as duas perguntas sao sobre a
    linha — o estado de onde ela vem e a versao dela. E **nao** precisa de
    `ENABLE ALWAYS`: a licao da `0031` e do KAM-176 e sobre barreiras
    *append-only*, que existem para recusar a mutacao de quem tem o privilegio;
    esta guarda a **forma** de uma mutacao legitima, e um
    `session_replication_role = replica` que a saltasse esta a correr uma
    replicacao, nao uma escrita de aplicacao.
    """
    op.execute(
        f"CREATE TRIGGER stock_reserva_transicao BEFORE UPDATE ON {RESERVAS} "
        "FOR EACH ROW EXECUTE FUNCTION platform.stock_reserva_transicao_valida()"
    )


def _rls() -> None:
    """RLS `FORCE` e politica `tenant_iso` na unica tabela nova da revisao.

    A `offer_terms` **nao** entra: ja tem politica desde a `0028`, e acrescentar
    colunas a uma tabela nao muda a politica dela — o predicado e sobre o
    `tenant_id`, que nao mexeu.
    """
    rls.enable_tenant_rls("stock_reservations")


def _privilegios() -> None:
    """Tabela a tabela e coluna a coluna, como a `0028` e a `0030`."""
    op.execute(f"GRANT SELECT, INSERT ON {RESERVAS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_RESERVAS)}) ON {RESERVAS} "
        f"TO {PAPEL_DA_APP}"
    )
    # **Sem `DELETE` para o `kamba_app`**, e e o criterio 6 por construcao: uma
    # reserva nao se apaga, liberta-se com motivo. Apagar era perder a razao
    # pela qual o stock voltou, que e o que a reconciliacao da regra 4 do §10.3
    # le.
    #
    # As duas colunas novas da oferta entram no `GRANT UPDATE` por coluna da
    # `0028`. **Acrescentam-se e nao se substituem**: um `GRANT UPDATE (...)`
    # novo nao revoga o anterior, soma-se-lhe.
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_OFERTAS_NOVAS)}) "
        f"ON {OFERTA} TO {PAPEL_DA_APP}"
    )
    # O `kamba_batch` e quem varre (o *job* do criterio 4) e quem semeia as
    # baterias de isolamento. Tem `BYPASSRLS` por atributo, e e por isso que ve
    # a base toda; a auditoria do que ele faz e do KAM-012.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {RESERVAS} TO {PAPEL_DE_LOTE}"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # A RLS primeiro, que e a ordem inversa do `upgrade`. **Explicitamente**, e
    # nao por efeito do `DROP TABLE`: ver a nota do modulo e o ensaio de mutacao
    # do `canon_lint`.
    rls.disable_tenant_rls("stock_reservations")
    # O *trigger* cai com a tabela; a funcao nao, e por isso vai a seguir.
    op.execute(f"DROP TABLE {RESERVAS}")
    op.execute("DROP FUNCTION platform.stock_reserva_transicao_valida()")
    # Os quatro `CHECK` caem com as colunas que restringem, pelo que nao se
    # apagam um a um: um `DROP CONSTRAINT` antes do `DROP COLUMN` era trabalho
    # repetido, e um depois era um erro.
    op.execute(
        f"""
        ALTER TABLE {OFERTA}
            DROP COLUMN stock_reservada,
            DROP COLUMN stock_quantidade
        """
    )

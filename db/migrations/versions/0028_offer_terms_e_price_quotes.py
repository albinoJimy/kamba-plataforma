"""Preco opaco e stock nao-garantido: offer_terms e price_quotes (KAM-043).

A primeira linha e **sem acentos**, como as vinte e sete revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria, e o que **nao** cria

Cria as duas tabelas de `docs/tecnica/03` §5.4 que o preco opaco exige —
`platform.offer_terms` (termos comerciais por SKU) e `platform.price_quotes`
(a cotacao do dono) —, as duas com RLS `FORCE` e a politica `tenant_iso`
(ADR-015), e o indice de trigramas que serve o `searchOffers` da Fase 0.

**Nao** cria a `orders_mirror`, a `order_intents`, o `order_state_log` nem a
`stock_reservations`, que estao no mesmo bloco SQL do §5.4 e sao de outros
tickets: as tres primeiras do **KAM-044** e a quarta do **KAM-045**. Esta
revisao e das duas que nao referenciam nenhuma delas — `offer_terms` referencia
so `tenants`, e `price_quotes` referencia `tenants` e `contacts` (revisao
`0003`) —, e e por isso que pode vir antes.

## A FK do contacto e **composta**, e o §5.4 escreve-a simples

E a divergencia mais importante desta revisao, e nao e uma escolha de gosto: o
proprio §5.4 **contradiz o seu bloco SQL** duas alineas abaixo dele. O bloco
escreve `contact_id uuid NOT NULL REFERENCES platform.contacts(contact_id)`; a
«Correccao de 2026-10-27 (spike KAM-041, ISO-58)» que vem a seguir diz que a FK
tem de ser composta e **nomeia esta tabela** entre as que herdam a regra
(«a mesma regra vale para toda a FK entre duas tabelas com `tenant_id`
(`stock_reservations -> orders_mirror`, `order_state_log -> orders_mirror`,
`price_quotes -> contacts`)»). O bloco foi anotado e nao corrigido.

O que a forma simples permite esta **medido** e nao inferido: com `ctx` do
tenant A e o `contact_id` de B, a `createOrder` do spike passou e criou uma
encomenda de A a apontar para um contacto de B. Nem a FK nem a RLS o impedem — a
FK e satisfeita pela chave primaria de `contacts`, que nao inclui o tenant, e a
politica `tenant_iso` olha para o `tenant_id` **da linha da cotacao**, que e o do
contexto e esta correcto. E o RR-01 do `seguranca/riscos_residuais.md`: «a RLS
protege de um `WHERE` esquecido, nao de codigo que escolha o tenant errado».

A revisao `0003` ja criou o indice que a torna possivel
(`contacts_tenant_contact_uq UNIQUE (tenant_id, contact_id)`), pelo que a
correccao custa escrever duas colunas e nao uma migracao extra.

## Quatro colunas que o §5.4 nao tem, e porque entram

Acrescentar a um DDL que um criterio manda seguir e divergencia e nao
arrumacao, pelo que cada uma leva a razao. As quatro estao registadas na emenda
1.52 do dicionario (§3.40).

1. **`offer_terms.nome`** — o criterio 8 manda pesquisar «sobre o nome» e o §5.4
   nao da a esta tabela nenhum: o §3.3 daquele documento poe o produto no
   Registo. Só que o Registo da opcao B e um Medusa que **nao existe em
   `infra/compose/`** — o KAM-042 registou-o ao deixar o `RegistoAdmin` sem
   cliente HTTP —, pelo que um `searchOffers` da Fase 0 contra o Registo nao
   tinha onde procurar. E o nome comercial que o cliente le, **nunca de pessoa
   singular**, como o `servicos.resources.nome` da `0025`.
2. **`offer_terms.criado_at`** — a convencao de todas as outras tabelas do
   esquema.
3. **`offer_terms.atualizado_at`** — o criterio 2 exige `atualizadoAt` na
   `OfferView`, e os dois instantes que o §5.4 da (`preco_atualizado_at`,
   `stock_verificado_at`) sao **anulaveis** e significam coisas especificas:
   quando o preco foi posto, e quando o stock foi conferido. Nenhum serve de
   «quando esta oferta mudou», e um `greatest` de dois nulos devolvia nulo para
   um campo que o criterio nao declara anulavel. **Quem o escreve e o modulo**,
   em cada `UPDATE`, e nao um *trigger*: a `orders_mirror` do §5.4 tem a mesma
   coluna sem *trigger* nenhum, e um *trigger* aqui escondia num objecto de base
   de dados uma coisa que se le na consulta.
4. **`price_quotes.currency`** — o §2 do dicionario exige moeda explicita ao lado
   de toda a unidade menor, e o §5.4 da `preco_total_minor` sem nenhuma. Sem
   ela a cotacao do dono era o unico valor em minor do conjunto sem moeda.

## `currency` e `text` com `CHECK`, e nao `char(3)`

O §5.4 escreve `char(3)` nas duas tabelas. O §3.4 do dicionario fecha o dominio
em `{AOA}`, e o `canon_lint` do *gate* 3b le os valores de um `CHECK` contra o
dominio fechado — um `char(3)` sem `CHECK` aceita `'USD'` em silencio e **nao e
lido por gate nenhum**. A `0025` ja fixou a forma `text` + `CHECK`
(`services_currency_ck`) e esta segue-a. Divergencia registada na emenda 1.52.

## O `pg_trgm` leva `IF NOT EXISTS`, ao contrario do `btree_gist` da `0025`

A `0025` escreve `CREATE EXTENSION btree_gist SCHEMA servicos` **sem** guarda, e
a razao dela era boa: se o objecto ja existir, alguem o criou fora da cadeia e
isso e para saber. Aqui o contrario e verdade — **o `pg_trgm` e criado fora da
cadeia de proposito**, pelo `infra/compose/postgres/initdb/01-bases-e-extensoes.sql`
(`CREATE EXTENSION IF NOT EXISTS pg_trgm`, ao lado do `vector`), porque a imagem
de desenvolvimento o levanta activo. Sem a guarda esta revisao falhava com
`42710 extension "pg_trgm" already exists` em toda a base que o compose tenha
preparado, que e a maioria delas.

Fica no esquema por omissao e nao em `platform`: o `initdb` ja o criou ali, e
pedir `SCHEMA platform` numa extensao existente nao a move — o `CREATE` com
`IF NOT EXISTS` ignora a clausula e a revisao ficava a afirmar uma localizacao
que nao impoe.

**E o `downgrade` nao a apaga.** Esta revisao nao sabe se a criou: com
`IF NOT EXISTS`, criar e nao-criar sao indistinguiveis depois do facto. Apagar
uma extensao que o `initdb` criou e que o `vector` do mesmo ficheiro nao apaga
deixava a base menos capaz do que antes da revisao, e um `downgrade` nao faz
isso. O que o `downgrade` apaga e o indice, que e seu.

## Privilegios: o `kamba_app` escreve, e nao apaga

O `kamba_app` **escreve** nas duas, e isso distingue estas tabelas do `dat`:
ali o papel da aplicacao insere e nao le, porque quem produz um registo de custo
nao e quem o audita. Aqui os termos de uma oferta **sao** o estado de negocio
que a porta le e escreve — o `upsertProductDraft`, o `publishProduct` e o ajuste
de preco e de stock sao todos dele —, e e a RLS que o limita as linhas do
tenant.

**O `kamba_app` nao apaga nada**, nas duas. Em `offer_terms` apagar e escrever
`deleted_at` (§5.6 manda soft delete nas ofertas), e em `price_quotes` uma
cotacao emitida e **prova** do preco que o dono deu: revoga-se pelo `estado`, e
um `DELETE` concedido tornava-a reescrivel sem deixar rasto. Quem apaga e o
`kamba_batch`, que e o papel da retencao (KAM-071) e o semeador das baterias de
isolamento.

**O `UPDATE` e por coluna nas duas**, e e a forma do
`UPDATE_DA_APP_EM_BOOKINGS` da `0025`, pela mesma razao. Na cotacao e so o
`estado`: mudar o `preco_total_minor`, o `qty`, o `sku` ou o `valida_ate` de uma
cotacao emitida era reescrever o que o dono cotou depois de o cliente o ter
visto. Na oferta sao as dez do `UPDATE_DA_APP_EM_OFERTAS`, e ficam de fora a
chave (`tenant_id`, `sku`), a `currency`, o `criado_at`, o `categoria_restrita`
e o `medusa_variant_id` — ver a razao de cada uma na constante.

**A primeira versao desta revisao dava `UPDATE` de tabela inteira na oferta**, e
a assimetria com a cotacao ao lado foi um achado da revisao adversarial: o
argumento que restringia uma aplicava-se a outra, e so uma o tinha escrito.

O `kamba_resolver`, o `kamba_identity`, o `kamba_audit` e o `kamba_agr` **nao
ganham nada**: o resolvedor resolve canais, a identidade guarda o cofre de
contactos, a auditoria le a `audit_log` e o `kamba_agr` guarda o estado das
conversas. Nenhum tem razao para chegar ao preco de ninguem.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
OFFER_TERMS = "platform.offer_terms"
PRICE_QUOTES = "platform.price_quotes"

#: Os tres modos de preco (dicionario §3.3; `preco_tipo` e **nao** `preco_modo`,
#: que a coluna «Substitui» dessa linha registou na emenda 1.12). Ja entre
#: apostrofos, pela razao da `0015`: e a unica forma que o *gate* 3b resolve,
#: porque segue `", ".join(<constante de modulo>)` dentro de uma f-string.
PRECO_TIPOS = ("'fixo'", "'a_partir_de'", "'sob_consulta'")

#: O modo de preco que **nao** leva numero. Sai a constante para que o `CHECK`
#: do criterio 1 e o do `preco_minor` nao o escrevam duas vezes.
SOB_CONSULTA = "'sob_consulta'"

#: Os tres modos de stock (dicionario §3.3). O `indicativo` e a omissao: e o
#: caso comum do comercio informal, onde o dono vende por outros canais.
STOCK_MODOS = ("'garantido'", "'indicativo'", "'confirmar_dono'")

#: Os quatro estados de uma oferta (dicionario §3.40, emenda desta revisao). **O
#: mesmo dominio que o `payload.estado` do contrato `catalog.product_changed` v1
#: fecha**, e de proposito: o evento que anuncia a publicacao e a coluna que a
#: guarda nao podem ter dominios diferentes.
ESTADOS_DA_OFERTA = ("'rascunho'", "'publicado'", "'pausado'", "'arquivado'")

#: Os quatro estados de uma cotacao (§5.4 e dicionario §3.40). A expiracao e por
#: `valida_ate` e **nao** por este estado: o `getValidQuote` compara o instante,
#: porque um estado so muda quando alguem o muda e uma cotacao vencida nao
#: espera por varrimento para deixar de valer.
ESTADOS_DA_COTACAO = ("'emitida'", "'aceite'", "'expirada'", "'revogada'")

#: `currency` ∈ {`AOA`} (dicionario §3.4, emenda 1.13). Dominio de um valor: a
#: plataforma e de Angola, e alarga-lo e emenda e nao `ALTER`.
MOEDAS = ("'AOA'",)

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"

#: O que o `kamba_app` pode alterar numa cotacao. **So o `estado`**: ver a nota
#: dos privilegios no topo.
UPDATE_DA_APP_EM_COTACOES = ("estado",)

#: O que o `kamba_app` pode alterar numa oferta, coluna a coluna.
#:
#: **Nao e `UPDATE` de tabela inteira, e a primeira versao desta revisao era.** A
#: revisao adversarial apanhou a assimetria: a cotacao tinha `UPDATE (estado)`
#: com o argumento escrito («mudar o `preco_total_minor` era reescrever o que o
#: dono cotou»), e a oferta tinha a tabela toda — com o mesmo argumento a
#: aplicar-se as colunas que o modulo nunca escreve.
#:
#: **Nao inclui o `tenant_id` nem o `sku`**: sao a chave primaria, e alterar
#: qualquer um deles era transformar a oferta de uma PME na oferta de outra, ou
#: mudar a referencia do produto por baixo de um cliente que a citou. Nao inclui
#: a `currency`, que tem dominio de um valor e nao se altera; nem o `criado_at`,
#: que e historia; nem o `categoria_restrita`, que e do *screening* (KAM-049) e
#: cuja escrita pela aplicacao desbloqueava a publicacao que ele existe para
#: travar; nem o `medusa_variant_id`, que e do Registo e nao do COM.
#:
#: O `estado` **esta** aqui, e tem de estar: e o `SQL_PUBLICAR` que o escreve. O
#: que impede o `upsertProductDraft` de o tocar nao e o `GRANT` — e a coluna nao
#: estar na instrucao dele, que e uma barreira mais forte do que um privilegio
#: partilhado pelos dois caminhos.
#:
#: O `deleted_at` esta aqui porque o soft delete do secao 5.6 e um `UPDATE`; o
#: ticket que o escrever (retencao, KAM-071) nao precisa de uma revisao para o
#: poder fazer.
UPDATE_DA_APP_EM_OFERTAS = (
    "nome",
    "preco_tipo",
    "preco_minor",
    "preco_atualizado_at",
    "preco_valido_ate",
    "stock_modo",
    "stock_verificado_at",
    "estado",
    "atualizado_at",
    "deleted_at",
)


def upgrade() -> None:
    _extensao()
    _offer_terms()
    _price_quotes()
    _rls()
    _privilegios()


def _extensao() -> None:
    """O `pg_trgm`, com guarda. Ver a nota do modulo para a razao da guarda."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def _offer_terms() -> None:
    """Os termos comerciais de um SKU: o preco opaco e o stock nao-garantido."""
    op.execute(
        f"""
        CREATE TABLE {OFFER_TERMS} (
            tenant_id           uuid        NOT NULL,
            sku                 text        NOT NULL,
            -- Nome comercial do produto, o que o cliente le. **Nunca de pessoa
            -- singular**: nao ha telefone, BI nem morada nesta tabela, e o
            -- `test_inventario` responde a pergunta coluna a coluna. Esta aqui
            -- porque o criterio 8 pesquisa sobre ele e o Registo da opcao B
            -- nao existe em `infra/compose/` — ver a nota do modulo.
            nome                text        NOT NULL,
            -- O id da variante no Registo. Nulo enquanto o Registo nao o
            -- atribuir, que e o estado de toda a Fase 0.
            medusa_variant_id   text,
            preco_tipo          text        NOT NULL,
            -- `fixo`: o preco; `a_partir_de`: o minimo; `sob_consulta`: NULL, e
            -- **so** nesse caso (ver o `offer_terms_preco_ck`). Unidade menor
            -- inteira (dicionario §2), nunca virgula flutuante.
            preco_minor         bigint,
            currency            text        NOT NULL DEFAULT 'AOA',
            preco_atualizado_at timestamptz,
            -- Passado este instante o agente **le** o preco como
            -- `a_partir_de` e pede confirmacao ao dono (§7.1, regra 2). A
            -- coluna `preco_tipo` nao muda: e a leitura que muda, e por isso o
            -- que o dono escolheu continua escrito.
            preco_valido_ate    timestamptz,
            stock_modo          text        NOT NULL DEFAULT 'indicativo',
            -- Renovado quando o dono actualiza ou confirma (§7.3). Acima de
            -- 24 h, o `indicativo` sai com aviso.
            stock_verificado_at timestamptz,
            estado              text        NOT NULL DEFAULT 'rascunho',
            -- Preenchida pelo *screening* (§8.2); **nao nula bloqueia a
            -- publicacao** (criterio 4). O dominio dos valores e do KAM-049,
            -- que e quem corre o *screening*: este ticket impoe a barreira e
            -- nao a lista.
            categoria_restrita  text,
            criado_at           timestamptz NOT NULL DEFAULT now(),
            -- Escrito pelo modulo em cada `UPDATE`, nao por *trigger*. Ver a
            -- nota do modulo.
            atualizado_at       timestamptz NOT NULL DEFAULT now(),
            -- Soft delete do §5.6. A purga fisica e da retencao (KAM-071).
            deleted_at          timestamptz,
            CONSTRAINT offer_terms_pkey PRIMARY KEY (tenant_id, sku),
            -- **A chave composta e que faz da colisao de SKU entre tenants
            -- (ISO-33..38) um nao-problema por construcao:** o mesmo texto de
            -- `sku` em dois tenants sao duas linhas, e a RLS mostra uma.
            CONSTRAINT offer_terms_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT offer_terms_sku_ck CHECK (btrim(sku) <> ''),
            CONSTRAINT offer_terms_nome_ck CHECK (btrim(nome) <> ''),
            CONSTRAINT offer_terms_preco_tipo_ck
                CHECK (preco_tipo IN ({", ".join(PRECO_TIPOS)})),
            CONSTRAINT offer_terms_stock_modo_ck
                CHECK (stock_modo IN ({", ".join(STOCK_MODOS)})),
            CONSTRAINT offer_terms_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_OFERTA)})),
            CONSTRAINT offer_terms_currency_ck
                CHECK (currency IN ({", ".join(MOEDAS)})),
            -- **O `CHECK` do criterio 1, a letra.** A equivalencia nos dois
            -- sentidos e nao so num: um `sob_consulta` com preco afirmava um
            -- numero que ninguem cotou, e um `fixo` sem preco deixava o agente
            -- sem *fact* para citar — e e o segundo que faz falta mais vezes.
            CONSTRAINT offer_terms_preco_ck CHECK (
                (preco_tipo = {SOB_CONSULTA} AND preco_minor IS NULL)
                OR (preco_tipo <> {SOB_CONSULTA} AND preco_minor IS NOT NULL)
            ),
            CONSTRAINT offer_terms_preco_nao_negativo_ck
                CHECK (preco_minor IS NULL OR preco_minor >= 0),
            -- Uma categoria restrita vazia nao e «sem categoria restrita»: e um
            -- valor que o `publishProduct` leria como presente e bloquearia a
            -- publicacao sem dizer qual. Nulo, ou texto.
            CONSTRAINT offer_terms_categoria_restrita_ck
                CHECK (categoria_restrita IS NULL OR btrim(categoria_restrita) <> '')
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {OFFER_TERMS} IS "
        "'Termos comerciais por SKU (KAM-043): preco opaco e stock "
        "nao-garantido. O `preco_tipo` decide se ha numero para citar e o "
        "`stock_modo` decide o que o checkout exige. Preco e stock vivem aqui e "
        "no Registo, nunca em embedding nem em prompt (ADR-007). Dicionario 3.40; "
        "docs/tecnica/03 secao 5.4 e secao 7.'"
    )
    # As consultas da oferta filtram sempre por tenant e por estado: o
    # `getOfferView` por `(tenant_id, sku)` usa a chave primaria, e o
    # `searchOffers` lista so o que esta publicado.
    op.execute(
        f"CREATE INDEX offer_terms_tenant_estado_idx ON {OFFER_TERMS} "
        "(tenant_id, estado) WHERE deleted_at IS NULL"
    )
    # O indice do `searchOffers`. **Trigramas e nao prefixo**: o criterio 8 pede
    # pesquisa lexical, e um `LIKE 'x%'` nao encontra «sabao» a partir de
    # «sabão» nem «arroz 5kg» a partir de «5 kg arroz». O filtro de tenant nao
    # entra no indice — um GIN de trigramas nao o aceita como primeira coluna
    # sem o `btree_gin` —, e quem o impoe e a RLS mais o `tenant_id = $1` que o
    # repo-base exige na consulta.
    op.execute(
        f"CREATE INDEX offer_terms_nome_trgm_idx ON {OFFER_TERMS} "
        "USING gin (nome gin_trgm_ops)"
    )


def _price_quotes() -> None:
    """A cotacao do dono: o preco que o `sob_consulta` nao tem (§7.2)."""
    op.execute(
        f"""
        CREATE TABLE {PRICE_QUOTES} (
            id                uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id         uuid        NOT NULL,
            contact_id        uuid        NOT NULL,
            sku               text        NOT NULL,
            qty               integer     NOT NULL,
            -- O total **da linha**, para `(sku, qty)`, e nao o preco unitario:
            -- e o que o §7.2 manda o dono cotar, e dividir por `qty` para
            -- obter um unitario perdia o desconto de quantidade que e a razao
            -- de existir a cotacao.
            preco_total_minor bigint      NOT NULL,
            currency          text        NOT NULL DEFAULT 'AOA',
            valida_ate        timestamptz NOT NULL,
            estado            text        NOT NULL DEFAULT 'emitida',
            -- O actor dono que a emitiu, autenticado pelo canal do tenant
            -- (§7.2). **Sem FK**: um actor nao e uma linha de `contacts` — pode
            -- ser o `owner_contact_id` do tenant, e pode ser um operador —, e
            -- inventar-lhe uma tabela era escopo de outro ticket. Quem fecha a
            -- criacao ao dono e o criterio 6, em codigo.
            emitida_por       uuid        NOT NULL,
            criado_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT price_quotes_pkey PRIMARY KEY (id),
            CONSTRAINT price_quotes_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta, e o §5.4 escreve-a simples.** Ver a nota do modulo:
            -- a forma simples deixava uma cotacao de A apontar para um contacto
            -- de B, e esta medido (ISO-58, spike KAM-041).
            CONSTRAINT price_quotes_contacto_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            CONSTRAINT price_quotes_sku_ck CHECK (btrim(sku) <> ''),
            CONSTRAINT price_quotes_qty_ck CHECK (qty > 0),
            CONSTRAINT price_quotes_preco_ck CHECK (preco_total_minor >= 0),
            CONSTRAINT price_quotes_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_COTACAO)})),
            CONSTRAINT price_quotes_currency_ck
                CHECK (currency IN ({", ".join(MOEDAS)}))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {PRICE_QUOTES} IS "
        "'Cotacao do dono para um (sku, qty), com validade (KAM-043). E por aqui "
        "que um `sob_consulta` ganha numero: ninguem, incluindo o LLM, escreve "
        "preco fora de `offer_terms` ou desta tabela (docs/tecnica/03 secao 7.2). "
        "A FK do contacto e composta pela correccao de 2026-10-27 do secao 5.4. "
        "Dicionario 3.40.'"
    )
    # O `getValidQuote` procura a cotacao viva de um `(tenant, contacto, sku,
    # qty)`, a mais recente primeiro. Parcial em `emitida` porque uma cotacao
    # aceite, expirada ou revogada nao se oferece — e a parcialidade mantem o
    # indice do tamanho das que contam, nao do historico.
    #
    # **O `contact_id` nao entra na chave, e desde o KAM-179 isso e uma
    # escolha e nao uma omissao.** A cotacao e por contacto por decisao do
    # fundador de 2026-11-04, pelo que a consulta filtra `tenant_id`,
    # `contact_id`, `sku` e `qty`; este indice serve-lhe o prefixo
    # `(tenant_id, sku)` e o `contact_id` e o `qty` filtram sobre ele. O
    # `valida_ate DESC` da chave nunca foi usado para ordenar — o
    # `SQL_COTACAO_VALIDA` ordena por `criado_at DESC` —, pelo que o que este
    # indice da e a reducao do conjunto. Se o volume por `(tenant, sku)`
    # crescer, o sitio onde se mede e aqui: **NAO VERIFICADO** no Piloto.
    op.execute(
        f"CREATE INDEX price_quotes_vivas_idx ON {PRICE_QUOTES} "
        "(tenant_id, sku, valida_ate DESC) WHERE estado = 'emitida'"
    )


def _rls() -> None:
    """Politica `tenant_iso` com `ENABLE` **e** `FORCE` nas duas (ADR-015).

    `FORCE` vincula tambem o dono: sem ele, o `kamba_migrator` — dono das
    tabelas — via tudo. O X-05 do *gate* 6 descobre as tabelas pelo catalogo e
    nao por lista, pelo que estas duas entram na verificacao sem ninguem as
    declarar; o que o `db/tests_produtos/test_isolamento.py` acrescenta e a
    leitura directa das bandeiras, para que uma revisao futura que ligue a RLS
    **sem** `FORCE` falhe la com a razao escrita e nao num oraculo generico.

    E a **segunda** barreira, nao a primeira: a primeira e a porta
    `CommerceRegistry` mais o repo-base, que recusa a consulta que nao nomeie o
    filtro (KAM-042, criterio 4). O §5.5 diz isto por extenso, e o ISO-39..42
    mede esta a parte precisamente para que uma nao passe por conta da outra.
    """
    for tabela in ("offer_terms", "price_quotes"):
        rls.enable_tenant_rls(tabela)


def _privilegios() -> None:
    """O `kamba_app` escreve e nao apaga; o `kamba_batch` semeia e purga.

    A nota longa esta no topo do modulo. O resumo: os termos de uma oferta sao o
    estado de negocio que a porta le e escreve, o `UPDATE` de uma cotacao e so
    do `estado`, e nenhuma das duas da `DELETE` a aplicacao.
    """
    # O `USAGE` em `platform` ja esta concedido desde a `0001`: nao se repete,
    # para que esta revisao nao pareca ser dona de uma concessao que nao criou.
    op.execute(f"GRANT SELECT, INSERT ON {OFFER_TERMS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_OFERTAS)}) ON {OFFER_TERMS} "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {OFFER_TERMS} TO {PAPEL_DE_LOTE}"
    )

    op.execute(f"GRANT SELECT, INSERT ON {PRICE_QUOTES} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_COTACOES)}) ON {PRICE_QUOTES} "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {PRICE_QUOTES} TO {PAPEL_DE_LOTE}"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # **E sem guarda de dados.** O que se perde sao termos de oferta e cotacoes,
    # que e estado de negocio e nao prova — ao contrario do consentimento da
    # `0015` e do registo de custo da `0023`. A linha de `audit_log` que
    # registou cada alteracao de preco **fica**, porque vive noutra revisao e e
    # append-only: quem descer esta revisao perde o preco e nao perde o rasto de
    # quem o mudou, que e a ordem certa das duas perdas.
    #
    # **A extensao `pg_trgm` nao cai.** Ver a nota do modulo: com
    # `IF NOT EXISTS`, esta revisao nao sabe se a criou, e apagar uma extensao
    # que o `initdb` do compose cria deixava a base menos capaz do que antes.
    # Os indices caem com as tabelas.
    #
    # Pela ordem inversa das FK — nenhuma das duas referencia a outra, pelo que
    # a ordem aqui e so a inversa da criacao.
    for tabela in ("price_quotes", "offer_terms"):
        rls.disable_tenant_rls(tabela)
    op.execute(f"DROP TABLE {PRICE_QUOTES}")
    op.execute(f"DROP TABLE {OFFER_TERMS}")

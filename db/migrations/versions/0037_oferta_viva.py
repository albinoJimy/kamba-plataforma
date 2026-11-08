"""Contrato de leitura da oferta viva: a vista v_oferta_viva (KAM-051).

`platform.v_oferta_viva` e o **contrato de leitura do COM** que a tool
`search_products` da TLS consulta para juntar os candidatos do indice (`idx`,
por texto, sem preco nem stock em embedding — ADR-007) ao `sku`, ao preco e ao
modo de stock no instante da pergunta. O `docs/tecnica/05` secao 6.3 escreve a
consulta; esta revisao publica a vista contra que ela corre.

## Porque e uma vista, e porque nasce no `platform`

O esquema `com` do nome antigo **nao existe** neste repositorio, e criar um era
rotina (ha quatro: `platform`, `lg`, `dat` e `servicos`). Nasce no `platform`
por uma razao que nao e de arrumacao: o
`test_nao_ha_colunas_de_dinheiro_nem_saldos` de `db/tests/test_catalogo.py`
filtra `table_schema = 'platform'`, e uma vista fora dele fica **invisivel** a
verificacao de dinheiro. Em `platform` a coluna `preco_minor` desta vista
**obriga** a uma entrada em `EM_UNIDADE_MENOR` com a razao escrita — que e a
porta que o KAM-172 ratificou. Ser vista pelo portao e a funcionalidade e nao o
custo.

## As nove colunas, e as tres que sao decisao

O criterio 1 fixa os nove nomes: `tenant_id`, `product_ref`, `sku`, `nome`,
`preco_minor`, `preco_tipo`, `stock_modo`, `publicado`, `lido_em`. Tres delas
nao sao uma coluna da `offer_terms` e cada uma e uma decisao com razao:

1. **`product_ref` e o `sku`**, e nao o `medusa_variant_id`. Nao e preferencia:
   o criterio 6 exige que o *join* por `(tenant_id, product_ref)` use o indice
   da **chave primaria**, e a chave da `offer_terms` e `(tenant_id, sku)` — por
   `medusa_variant_id` nenhum indice de chave primaria cobria o *join*. E o
   `medusa_variant_id` e nulo em **toda a Fase 0** (nao ha Medusa em
   `infra/compose/`), pelo que a vista sairia vazia para o indice; alem disso o
   bloco do ticket manda que a referencia seja opaca e **nao dependa do modelo
   interno do Registo**, que e exactamente o que aquela coluna e. O `sku` e
   opaco para quem o le, e e por tenant.

2. **`publicado` e uma coluna e nao um filtro.** A vista expoe o predicado e
   nao o aplica, e as duas metades do criterio 2 nao se contradizem: a consulta
   do `docs/tecnica/05` secao 6.3 escreve `WHERE v.publicado`, logo e ela que
   filtra, e e la que um produto `pausado`, `arquivado`, restrito ou apagado
   **devolve 0 linhas**. Uma vista que filtrasse tornava esta coluna uma
   constante verdadeira e o criterio 1, que a exige entre os nove nomes, ficava
   vazio de conteudo. O ensaio mede as duas coisas: o valor da coluna por
   estado, e a leitura composta a devolver zero.

3. **`lido_em` e o `now()` da transaccao** e nao um instante guardado: e a hora
   a que a oferta **foi lida**, que e o que o contrato de saida da tool
   transporta para o validador de citacao (KAM-032) poder dizer de quando e o
   numero que o agente citou. Dentro de uma transaccao e estavel, que e o que
   uma resposta precisa — duas linhas da mesma leitura com instantes diferentes
   diziam que a oferta foi lida duas vezes.

## O `preco_tipo` que sai nao e sempre o que esta guardado

O `docs/tecnica/03` secao 7.1 regra 2, e o comentario da `preco_valido_ate` na
revisao `0028`, dizem a mesma coisa: passado esse instante o agente **le** o
preco como `a_partir_de` e pede confirmacao ao dono, e a coluna `preco_tipo`
**nao muda** — «e a leitura que muda, e por isso o que o dono escolheu continua
escrito». Esta vista e a leitura, logo e aqui que a regra se aplica.

**So o `fixo` degrada.** Um `sob_consulta` tem `preco_minor` nulo por
`offer_terms_preco_ck`, e devolve-lo como `a_partir_de` afirmava um minimo que
ninguem cotou — o mesmo defeito que aquele `CHECK` existe para recusar, do
outro lado. E um `a_partir_de` ja e o que a regra manda ler, pelo que nao ha
degradacao a fazer. Sem a guarda `preco_tipo = 'fixo'` a vista inventava um
preco em dois dos tres modos.

## O que nao esta aqui

**Nenhuma coluna de stock.** O criterio 7 esta bloqueado por decisao aberta: o
D3 nao esta ratificado (o `docs/tecnica/00` secao 13.3 registra o *spike* como
feito, com recomendacao pela opcao B, e a faltar duas assinaturas e a
ratificacao) e a projeccao de nivel de stock nao existe — a `offer_terms` da
revisao `0028` tem `stock_modo` e `stock_verificado_at` e **nenhuma
quantidade**, e quem produz as reservas e o KAM-045, aberto. Logo nao ha
`stock_disp`, e o filtro `v.stock_disp > 0` da secao 6.3 **nao tem coluna
contra que correr**: fica registado para o KAM-061 e nao se emenda aqui. O
`sob_consulta` continua a nao desaparecer por filtro de stock — e modo de preco
e nao de stock.

**Nenhuma coluna `disponibilidade`.** Desde o KAM-043 (emenda 1.52 e o
`DISPONIBILIDADE` de `services/com/src/produtos/formato.ts`) esse nome e o
**texto de apresentacao** derivado do modo, em tres valores. Duplicar o
mapeamento em SQL dava duas respostas para a mesma pergunta. A vista expoe o
`stock_modo` canonico; quem apresenta deriva o texto onde apresenta. O
`disponivel` do contrato da tool e outro nome, outro tipo e outra camada, e
fica como a secao 6.3 o escreve.

**Nenhum `preco_kz`, e nenhum mapeamento `fixo` para `exato`.** Os dois estao
na coluna «Substitui» do dicionario secao 3.3, e uma coluna terminada em `_kz`
e recusada pelo `test_nao_ha_colunas_de_dinheiro_nem_saldos` sem excepcao. Quem
apresenta em Kz divide por cem **onde apresenta**; a vista nao transporta a
divisao, que e onde um preco se perde por um factor de cem. Decisao do fundador
de Novembro de 2026, registada no bloco do ticket.

**Nenhuma PII e nenhum texto de descricao** (criterio 6). Das dezesseis colunas
da `offer_terms`, **seis** saem projectadas, **quatro** sao lidas so dentro de
expressao (o `preco_valido_ate` no `CASE`, e o `estado`, o `deleted_at` e a
`categoria_restrita` no predicado do `publicado`) e **seis** nunca sao lidas —
`medusa_variant_id`, `currency`, `preco_atualizado_at`, `stock_verificado_at`,
`criado_at`, `atualizado_at`. O `nome` e nome comercial de produto e nunca de
pessoa singular, que e a mesma resposta que o `offer_terms.nome` da no
inventario. A conta coluna a coluna esta no comentario do
`INVENTARIO["v_oferta_viva"]`.

## SemVer do contrato

Contrato `v_oferta_viva` **1.0.0**. Qualquer alteracao de colunas segue
*expand* -> *migrate* -> *contract*: acrescentar coluna e menor, retirar ou
mudar tipo e maior, e as duas passam por uma revisao em que as duas formas
coexistem. O nome qualificado fica fixado no secao 4 do dicionario, que e onde
este contrato estava registado como «por definir».
"""

from alembic import op

revision = "0037"
#: A `0036` (KAM-069) e a cabeca da cadeia na **base** e nao neste worktree,
#: lida de `refs/remotes/publico/main`. A cadeia Alembic e linear e de escritor
#: unico: uma `down_revision` que aponte para uma revisao que ainda nao fundiu
#: deixa a cadeia irresoluvel ate ela fundir, e ocupar uma `down_revision` que
#: outra revisao ja ocupa da **duas cabecas**, que o `test_ha_uma_so_cabeca` de
#: `db/tests/test_migracao.py` recusa.
down_revision = "0036"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST desta
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
OFERTA = "platform.offer_terms"
VISTA = "platform.v_oferta_viva"

#: O papel que corre a tool `search_products`. Le a vista, como le a tabela, e e
#: o **unico** com `GRANT` nela.
#:
#: **Nao ha `GRANT` para o `kamba_batch`, e a primeira versao desta revisao
#: tinha-o com uma razao falsa** — dizia que era ele que semeava os 10 000 SKUs
#: do ensaio de plano do criterio 6. Nao e: a sementeira e o `EXPLAIN` desse
#: ensaio correm pela ligacao de administrador. E o `kamba_batch` e o **unico**
#: papel com `BYPASSRLS` (`db/bootstrap.py`), isto e, o unico leitor para quem o
#: `security_invoker` desta vista nao compra isolamento nenhum: dar-lhe `SELECT`
#: numa vista que existe para ser lida sob RLS era alargar a superficie sem
#: nenhum leitor a pedi-la. Apanhado pela revisao adversarial.
#:
#: Tambem nao ha para o `kamba_resolver`, o `kamba_identity`, o `kamba_audit`
#: nem o `kamba_agr`: nenhum deles le a oferta, e a `0028` escreveu essa
#: fronteira. O `test_so_o_kamba_app_le_a_vista` afirma as duas metades.
PAPEL_DA_APP = "kamba_app"

#: O estado que publica, e os tres modos de preco. Do dicionario secao 3.3 e do
#: `offer_terms_estado_ck` da revisao `0028`.
ESTADO_PUBLICADO = "'publicado'"
PRECO_FIXO = "'fixo'"
PRECO_A_PARTIR_DE = "'a_partir_de'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE VIEW {VISTA}
          WITH (security_invoker = true) AS
          SELECT o.tenant_id,
                 -- `product_ref` **e** o `sku`: ver a nota 1 do modulo. O
                 -- *join* do indice e por `(tenant_id, product_ref)` e tem de
                 -- cair no `offer_terms_pkey`, que e `(tenant_id, sku)`.
                 o.sku     AS product_ref,
                 o.sku,
                 o.nome,
                 o.preco_minor,
                 -- A regra 2 do `docs/tecnica/03` secao 7.1: passado o
                 -- `preco_valido_ate` o preco **le-se** como `a_partir_de`. So
                 -- o `fixo` degrada — ver a nota do modulo.
                 CASE
                   WHEN o.preco_tipo = {PRECO_FIXO}
                        AND o.preco_valido_ate IS NOT NULL
                        AND o.preco_valido_ate < now()
                   THEN {PRECO_A_PARTIR_DE}
                   ELSE o.preco_tipo
                 END     AS preco_tipo,
                 o.stock_modo,
                 -- O predicado do criterio 2, exposto e nao aplicado: quem
                 -- filtra e o `WHERE v.publicado` da secao 6.3.
                 (o.estado = {ESTADO_PUBLICADO}
                  AND o.deleted_at IS NULL
                  AND o.categoria_restrita IS NULL) AS publicado,
                 now()   AS lido_em
            FROM {OFERTA} o
        """
    )
    op.execute(
        f"COMMENT ON VIEW {VISTA} IS "
        "'Contrato de leitura da oferta viva (KAM-051, contrato 1.0.0): o que a "
        "tool search_products junta aos candidatos do indice para obter sku, "
        "preco e modo de stock no instante da pergunta (docs/tecnica/05 secao "
        "6.3; ADR-007). O product_ref **e** o sku, para o join por "
        "(tenant_id, product_ref) cair no offer_terms_pkey. O publicado e "
        "coluna e nao filtro: quem filtra e o WHERE v.publicado da secao 6.3. O "
        "preco_tipo que sai degrada fixo->a_partir_de passado o "
        "preco_valido_ate, e **so** o fixo — um sob_consulta nao tem numero "
        "para minimo. Sem stock: o criterio 7 esta bloqueado pelo D3 e pelo "
        "KAM-045, logo nao ha stock_disp e o filtro de stock da secao 6.3 fica "
        "para o KAM-061. Sem coluna disponibilidade: desde o KAM-043 esse nome "
        "e o texto de apresentacao derivado do stock_modo. security_invoker: a "
        "RLS FORCE da offer_terms continua a valer para quem le a vista.'"
    )
    # A vista corre como quem a consulta, logo quem a le precisa de `SELECT` na
    # vista **e** na tabela — que o `kamba_app` ja tem na `offer_terms` desde a
    # `0028`. Um so `GRANT`, e a razao de nao haver mais esta na nota do
    # `PAPEL_DA_APP`.
    op.execute(f"GRANT SELECT ON {VISTA} TO {PAPEL_DA_APP}")


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio. Os dois `GRANT` caem com a vista.
    op.execute(f"DROP VIEW {VISTA}")

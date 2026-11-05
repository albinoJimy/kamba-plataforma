# Cobertura da porta `CommerceRegistry` — quem implementa o quê

| Campo | Valor |
|---|---|
| Ticket | KAM-042 — Porta `CommerceRegistry` e adaptador (critério 6) |
| Fonte normativa | [`specs/EPIC-04_Core_Comercio.md`](../../specs/EPIC-04_Core_Comercio.md), bloco KAM-042 |
| Contrato | [`docs/tecnica/03_Core_Comercio_Medusa.md`](../tecnica/03_Core_Comercio_Medusa.md) §3.2 |
| Código | [`services/com/src/port/contrato.ts`](../../services/com/src/port/contrato.ts), [`services/com/src/adapters/medusa/`](../../services/com/src/adapters/medusa/) |
| Registo activo | **opção B** (Medusa puro + módulo `merchant`) — *recomendação* do KAM-041, **não ratificada** (D3) |

> **Nada está ratificado.** A opção B é a recomendação do spike KAM-041
> (2026-10-27). A decisão D3 em
> [`docs/tecnica/00`](../tecnica/00_Arquitectura_Solucao.md) §13.3 diz, por
> escrito, que «falta a assinatura do Arquitecto de Plataforma e do Responsável
> de Segurança, e a ratificação do fundador». O ADR-003 continua a nomear a
> opção C como *fallback*, e este documento não o contradiz.

---

## 1. Para que serve este documento

O critério 6 do KAM-042: «Métodos cuja implementação pertence a tickets
posteriores devolvem `NOT_IMPLEMENTED` e estão listados em
`docs/com/port-coverage.md` com o ticket dono; cada um tem teste de isolamento
marcado *xfail strict* que falha quando a implementação chegar sem teste.»

**Quando o KAM-042 fundiu, os doze devolviam `NOT_IMPLEMENTED`**, e isso era o
resultado honesto dele e não uma entrega a meio: o ticket entrega a **porta**, a
barreira de isolamento e a *pipeline*; cada método é de um ticket a jusante. O
que o KAM-042 entrega e que **não** é adiado está no §3.

**Hoje são cinco**, depois do KAM-043 (três do catálogo) e do KAM-178 (quatro:
o fluxo do dono, a primitiva de transição e as duas leituras). A forma do `xfail
strict` do critério 6 continua a valer para esses cinco, e o KAM-043
acrescentou-lhe a peça que faltava: uma **partição** afirmada num teste — os
doze da porta são exactamente os sete implementados mais os cinco com ticket
dono, sem sobreposição. Sem ela, a lista dos implementados podia crescer e os
casos de `xfail strict` desapareciam um a um em silêncio, que é o contrário do
que «strict» quer dizer.

## 2. Os doze métodos e o ticket dono

**Três já não devolvem `NOT_IMPLEMENTED`: os do KAM-043**, fundido em Novembro de
2026. A coluna da direita diz, para esses, o que passou a existir; para os nove
que restam, continua a dizer o que falta.

**São sete depois do KAM-178**, e a parte que vale escrever é **porque é que não
são doze**. O KAM-044 e o KAM-046 entregaram tudo o que os métodos 4, 5, 10, 11
e 12 precisam e não ligaram o adaptador, por uma razão escrita: o módulo devolve
um terceiro resultado (`conflito`) que o `Resultado` de dois casos da porta não
sabia expressar. **Essa razão deixou de valer** — a emenda 1.59 do dicionário
(decisão do orquestrador a 2026-11-04, nível L5) deu ao `Resultado` um terceiro
caso só para o conflito de CAS e alargou o `ERROS` aos nove do
`OrdersModule.erro` —, e com ela quatro métodos ligaram.

**E são onze depois do KAM-045**, que ligou as quatro das reservas. Era o ticket
de implementação que as quatro esperavam, e o que ele trouxe que faltava não foi
só o código: foi a **autoridade de quantidade** — a `offer_terms` não tinha
coluna de stock, e é por isso que o `OUT_OF_STOCK` do `createOrder` era um *hook*
sem fonte (dicionário §3.46).

**O que resta é **um**, e o credor dele não é um ticket: é uma decisão.** O
`createOrder` tem a *saga* implementada, medida e servida pela API interna — o
que não se consegue ligar é o **método**, pelo tipo do argumento. Ver a linha
4. A partição do `xfail strict` mantém-se: sete implementados, cinco com ticket
dono, sem sobreposição.

| # | Método | Ticket dono | Estado | O que falta, ou o que passou a existir |
|---|---|---|---|---|
| 1 | `upsertProductDraft` | **KAM-043** | **implementado** | `platform.offer_terms` (revisão `0028`) com os termos em rascunho. **Nunca publica**, e não por um `if`: a coluna `estado` não entra na lista do `INSERT` nem no `SET` do `UPDATE`. Os produtos e as variantes no Registo continuam a não existir — o `medusa_variant_id` é nulo em toda a Fase 0, porque não há Medusa em `infra/compose/` |
| 2 | `publishProduct` | **KAM-043** | **implementado** | A `OwnerConfirmation` é verificada antes de abrir transacção e exige `actor.kind='dono'`; a categoria restrita está **no predicado** do `UPDATE`, pelo que é a base que a recusa. O `screening` que **preenche** a `categoria_restrita` é do KAM-049: este ticket impõe a barreira e não a lista de valores |
| 3 | `getOfferView` | **KAM-043** | **implementado** | Os três `preco_tipo` e os três `stock_modo`, com o `precoDisplay` formatado **com o modo** e a validade do preço lida a cada chamada (§7.1 regra 2) |
| 4 | `createOrder` | **decisão sobre o §3.39** | `NOT_IMPLEMENTED` **e a saga existe e serve-se** | **A *saga* de §6.3 está implementada** pelo KAM-046 (`orders/create_order.ts`): o recibo com `ON CONFLICT DO NOTHING`, as duas transacções, a revalidação de preço e stock, o tecto do tenant, o fecho do recibo e o facto do «pedido por pagar». **O que falta é a ligação ao adaptador, e não é trabalho de escrita — é a mesma decisão sobre esta porta que a linha 10 descreve:** o módulo devolve nove códigos (`OrdersModule.erro`, dicionário §3.44) e os critérios 4 e 6 do bloco nomeiam quatro deles — `PRICE_CHANGED`, `OUT_OF_STOCK`, `LIMIT_EXCEEDED`, `INTENT_REUSED_WITH_DIFFERENT_CONTENT`. A lista de erros do §3.39 é **fechada em cinco** e nenhum dos quatro cabe lá. Traduzir `PRICE_CHANGED` para `VALIDATION_ERROR` diria ao cliente que o pedido dele não serve, quando o que mudou foi o preço e o que ele tem de fazer é ver o novo — e os quatro **já são canónicos** como valores de `tool_audit.error_code` (§3.27, treze desde a emenda 1.47), pelo que o que falta não é inventar nomes: é alargar a lista fechada da porta. **A lista foi alargada pelo KAM-178** (emenda 1.59: dez erros, mais o terceiro caso do `Resultado`), e por isso esta linha mudou de credor. **O que falta agora é o tipo do argumento, e é uma decisão e não trabalho:** o `OrderIntent` do §3.2 tem `intentKey`, `contactId`, `linhas` e `entregaModo`, e o `createOrder` do KAM-046 precisa de três que ele não tem — o `draftId` e a `draftVersion`, de que a `intent_key` **se deriva** (e o módulo recusa uma chave do chamador, por escrito: «nenhum dos dois se aceita do chamador»), e o `totalEsperadoMinor`, que é por onde se mede o `PRICE_CHANGED`. **O terceiro contradiz a regra 4 do §3.2** — «nenhuma operação aceita um preço do chamador» —, que a nota do próprio `OrderIntent` repete. Logo ligar este método pede um **terceiro** movimento no §3.39, e a decisão de 2026-11-04 autoriza dois; resolvê-lo por conta própria era decidir em silêncio um conflito entre o §3.39 e o §3.44. **A *saga* não está bloqueada por isto:** serve-se no `POST /internal/create-order`, que é a superfície do COM e não a porta, e é por lá que os executores das tools de comércio a chamam |
| 5 | `requestOwnerConfirmation` | **KAM-178** | **implementado** | **O fluxo está implementado** pelo KAM-046 (`orders/owner_confirmation.ts`): o CAS pelo subestado esperado, o «sim», o «não» e o silêncio, com o cancelamento a emitir `order.cancelled` pelo `transition`. **Ligado pelo KAM-178**, com os três casos do módulo a atravessar a porta um a um — e o `conflito` é o terceiro caso do `Resultado` e não um `VALIDATION_ERROR`: a encomenda já saiu de `criada`, ou o subestado é outro, e o que quem chama tem de fazer é reler. **Um limite fica dito:** o `Resultado<void>` do §3.2 não leva o subestado relido, porque o `void` não tem onde o levar — quem o precisa lê-o com o `getOrder`, e alargar aquela assinatura era alargar o contrato dos doze por um método. O que **continua** fora é o passo seguinte: o «sim do dono» do critério 7 manda emitir `charge.requested`, que **não existe** no catálogo publicado nem no §3.5 do dicionário (vive só no §12 do `docs/tecnica/03`, que é a dívida documental **37**), e a reserva que o precede é do **KAM-045**; o aviso ao dono é do **KAM-115** |
| 6 | `reserveStock` | **KAM-045** | **implementado** | **Ligado pelo KAM-045.** A `platform.stock_reservations` e as duas colunas de quantidade da `offer_terms` sao da revisao [`0033`](../../db/migrations/versions/0033_reservas_de_stock.py); o `UPDATE … WHERE stock_quantidade - stock_reservada >= :q` do §6.4 e o `SQL_RESERVAR`, e **nao leva `FOR UPDATE`** — sob `READ COMMITTED` o proprio `UPDATE` serializa, medido em `db/tests_encomendas/test_reservas.py` com mil tentativas paralelas sobre stock 10 (dez reservas, zero acima, e dois canarios que mostram a barreira a desaparecer). As linhas vem do `lines_snapshot` e nao do chamador, e a atomicidade por encomenda e a transaccao do `comTenant` |
| 7 | `extendReservation` | **KAM-045** | **implementado** | **Ligado pelo KAM-045.** As tres condicoes do criterio 7 tem dono cada uma: «so em `aguarda_pagamento`» e **do adaptador**, que ja tem o estado da encomenda em mao (o modulo nao le o `orders_mirror`, e isso esta escrito nele); o tecto de 72 h e a validade da cobranca sao do `SQL_ESTENDER`, contra a base. O tecto mede-se contra o `criado_at` **da reserva** e nao contra `now()`, senao dois prolongamentos de 36 h passavam um a um e somavam 72 h sobre uma reserva que ja tinha 48 |
| 8 | `commitReservation` | **KAM-045** | **implementado** | **Ligado pelo KAM-045.** Marca as reservas activas da encomenda `consumida` e **nao devolve stock** — uma reserva consumida e stock que saiu. Idempotente pelo `estado = 'ativa'` do predicado, e a encomenda **le-se antes**: «nao havia nada a consumir» e «isso nao e teu» sao duas coisas diferentes, e a segunda e `NOT_FOUND` (ISO-01..08). **O que continua fora:** o consumidor de `payment.confirmed` e de `payment.manual_confirmed` e do **KAM-055**; o que existe aqui e a primitiva que ele chama |
| 9 | `releaseReservation` | **KAM-045** | **implementado** | **Ligado pelo KAM-045.** Liberta com um dos tres motivos e devolve o stock, por essa ordem: pela ordem inversa, uma falha no meio deixava stock devolvido com a reserva activa, isto e, a mesma unidade prometida duas vezes. Idempotente («execucao dupla = 1 libertacao»), com o *trigger* `stock_reserva_transicao` a recusar quem forcar. A **consulta final ao PAY** do §6.5 vive no `reservations/expire.ts` e nao neste metodo: e o varrimento que a faz, e o `desconhecida` **adia** em vez de libertar, porque «nunca liberta sem consulta final» inclui «com uma consulta que nao respondeu» |
| 10 | `transition` | **KAM-178** | **implementado** | **O que o método precisa está feito** (revisão `0030` e `services/com/src/orders/`): o `order_state_graph` com o *trigger* que o impõe, o CAS por `version`, o `order_state_log` com o *trigger* diferido que o exige, e os cinco eventos pelo *outbox*. **O que falta é a ligação ao adaptador, e não é trabalho de escrita — é uma decisão sobre esta porta:** o módulo devolve três resultados (`ok`, `conflito`, `erro`) porque o §6.2 manda «reler e reavaliar, nunca forçar», e um conflito de CAS **não é** um pedido inválido. O `Resultado` da porta tem dois casos e a lista de erros do §3.39 é fechada em cinco, nenhum deles «tarde». Traduzir `conflito` para `VALIDATION_ERROR` diria a quem chama que o pedido dele não serve, quando o que ele tem de fazer é reler — pelo que a escolha era alterar o contrato da porta (dicionário §3.39). **Essa decisão foi tomada e este método está ligado** (KAM-178, emenda 1.59): o `Resultado` tem um terceiro caso só para o conflito de CAS, e o `comoResultadoDaPorta` leva a **releitura** intacta até quem chama. **Duas transições não são alcançáveis por esta via, e é do tipo e não do módulo:** o `entregue` exige `entrega_confirmada_por` (o contrato do `order.delivered` e o `orders_mirror_entregue_exige_quem_ck`) e o `expirada` exige um instante quando a encomenda não tem `expira_at`; o `Cause` do §3.2 é `{causa, eventoId}` e não leva nenhum dos dois, pelo que as duas respondem `VALIDATION_ERROR` por aqui. Mesmo credor do `createOrder` — uma decisão sobre o §3.39 —, e as duas alcançam-se pelo módulo, que é por onde o **KAM-050** e o varrimento de expiração as vão chamar |
| 11 | `getOrder` | **KAM-178** | **implementado** | A `OrderView` do §3.2 sai do `SQL_VISTA` — uma leitura própria e não o `SQL_LER` do KAM-044, porque a vista tem o `criado_at` que o `EstadoDaEncomenda` não tem e acrescentá-lo ao `SQL_LER` punha uma coluna a mais em todos os caminhos da transição. O `totalMinor` é `bigint`, e sai da API interna como **cadeia de dígitos**: acima de 2^53 cêntimos o `JSON.parse` de quem lê arredondava em silêncio. Uma encomenda de outro tenant dá `NOT_FOUND` e não `TENANT_MISMATCH` — distingui-las era um oráculo |
| 12 | `listOrders` | **KAM-178** | **implementado** | O cursor é **opaco e assinado**: HMAC com o anel do `segredo_intents` e a parte de domínio `cursor` à cabeça, com o `tenant_id` **dentro** da assinatura — sem ele, o cursor de um tenant era um cursor válido para outro. A paginação é *keyset* por `(criado_at DESC, id DESC)` e não `OFFSET`: uma linha inserida entre duas páginas deslocava todas as seguintes. Os três casos do ISO-10 estão medidos um a um em `services/com/tests/orders.listagem.test.ts`, e nenhum deles chega à base (o cliente de ensaio explode se lhe falarem) |

**São doze, e não onze.** O objectivo do bloco KAM-042 e a linha do dicionário
§3.38 escrevem «onze métodos»; o §3.2 do `docs/tecnica/03`, que é a fonte do
contrato, lista doze, e o critério 1 do mesmo bloco nomeia os doze um a um. A
contagem está corrigida nos dois sítios pelo PR do KAM-042, e fica registada
aqui porque uma contagem que anda em três documentos é o modo de falha que este
conjunto já pagou quatro vezes. A contagem está presa em
`services/com/tests/port.contrato.test.ts`.

## 3. O que não é `NOT_IMPLEMENTED`

Estas quatro propriedades são do KAM-042 e valem **hoje**, nos doze métodos.
Nenhuma muda entre a opção B e a opção C — é por isso que a porta e o repo-base
não vivem dentro do adaptador.

| Propriedade | Onde | Como se verifica |
|---|---|---|
| `ctx` obrigatório, falha fechada | `port/contrato.ts` → `exigirCtx` | `tests/port.iso.test.ts`: as doze operações com `ctx` sem `tenantId` lançam, **e sem pedir ligação** (o cliente de ensaio explode se lhe falarem) |
| A API interna recusa sem `ctx` utilizável | `api/interna.ts` → `ctxDoPedido` | `tests/api.interna.test.ts`: seis formas de `x-kamba-tenant` inútil e seis de `ctx` a meio no corpo dão **400** e a porta **não é chamada** (as operações de ensaio contam as chamadas, e a asserção é zero). O `ctx` não se completa por omissão: um `actor` em falta é 400 e não `{kind: "sistema"}` |
| A API interna recusa sem credencial | `api/interna.ts` → `credencialValida` | `tests/api.interna.test.ts`: as sete rotas sem cabeçalho dão **401**, e cinco credenciais erradas — entre elas a **do AGR** — dão 401 também. A comparação é em tempo constante (`timingSafeEqual`) |
| `merchant_id` do `platform.tenants` e nunca de um argumento | `repo-base/index.ts` → `idsDoRegisto` | `tests/repo-base.test.ts`: um tenant com a coluna a `NULL` falha fechado |
| Nenhuma consulta ao Registo sem o filtro | `repo-base/index.ts` → `repoBase` | `tests/repo-base.test.ts`: a consulta recusada **não chega** à base |
| Canal e localização por tenant, idempotentes | `adapters/medusa/provisionamento.ts` | `tests/provisionamento.test.ts`: a ordem, a idempotência e o `UPDATE` que só preenche o vazio |

## 4. O `xfail strict`, e porque não é um `todo`

O critério pede «*xfail strict*», que é vocabulário do pytest. O `node:test` não
o tem: um `{ todo: true }` que **passa** é reportado como *todo* e **não** falha
a suite, que é o contrário de «strict».

A forma com a semântica certa está em `tests/port.iso.test.ts` e é mais simples
do que uma marca: **afirmar o `NOT_IMPLEMENTED`**. Enquanto o método não estiver
implementado, a asserção passa. No dia em que alguém o implementar e não
substituir o caso pelo teste de isolamento a sério, a asserção **falha** — com a
mensagem a dizer o ticket dono e o que a substitui:

```text
<metodo> deixou de devolver NOT_IMPLEMENTED.
O ticket dono e o KAM-0NN: substitui este caso pelo teste de isolamento a
serio — ctx do tenant A sobre um id do tenant B tem de dar TENANT_MISMATCH ou
NOT_FOUND, nunca a linha de B. E actualiza docs/com/port-coverage.md.
```

## 5. A suite ISO: o que está medido e o que não está

| Casos | Estado | Onde |
|---|---|---|
| ISO-09 (sem `tenantId`) | **verde**, nos doze métodos — e nos sete ligados o caso mede, com um cliente que explode se lhe falarem, que o `exigirCtx` continua a correr **antes** da transacção | `tests/port.iso.test.ts` |
| ISO-01..08 (`ctx` de A sobre ids de B) | **medidos nos sete implementados.** Nos três do KAM-043: `ctx` de A sobre o `sku` de B devolve a oferta de A e nunca a de B, e um tenant sem a oferta devolve `NOT_FOUND` e não uma vista vazia. Nos quatro do KAM-178: a asserção é **o tenant que foi ao predicado** — com o `ctx` de A sobre ids de B, o único `tenant_id` que a base vê é o de A —, e o `getOrder` de uma encomenda de outro tenant dá `NOT_FOUND` e não `TENANT_MISMATCH`, porque distingui-los era um oráculo. Nos cinco que restam continuam **não medidos**, pela razão de sempre | `tests/port.iso.test.ts`, `tests/orders.listagem.test.ts`; `xfail strict` para os cinco |
| ISO-10 (filtro vazio, cursor forjado, `OR`) | **medido, nos três casos** (KAM-178), e cada um com asserção própria: filtro vazio é `VALIDATION_ERROR` e não «lista tudo» (e um cursor sozinho não conta como filtro); cinco formas de cursor forjado são `VALIDATION_ERROR`, **incluindo um cursor legítimo de outro tenant**, que é o caso que o `tenant_id` dentro do HMAC existe para fechar; e quatro injecções de `OR`/`;` nos dois filtros são `VALIDATION_ERROR`. **E nenhuma das três chega à base:** o cliente de ensaio explode se lhe falarem, e há um caso que afirma que as três não emitiram consulta nenhuma com as linhas de outro tenant presentes | `tests/orders.listagem.test.ts`; `tests/port.iso.test.ts` |
| ISO-11..32 (Store API, Admin API, *query graph*) | **medidos só no KAM-041**, e o **ISO-15 está vermelho lá**: a Store API serviu a encomenda de um tenant a uma chave publicável de outro. Exigem um Medusa a correr, e não há nenhum em `infra/compose/` | `spikes/medusa-d3/resultados/iso.json` |
| ISO-33..38 (colisão de SKU entre tenants) | **medidos nas duas metades pelo KAM-043**: que o mesmo texto de `sku` em dois tenants são duas linhas independentes (a chave é `(tenant_id, sku)`), e que nenhum dos dois vê a do outro. A metade das **reservas** que a matriz do §4.4 define continua por medir, e é do **KAM-045** | `db/tests_produtos/test_isolamento.py`; `tests/port.iso.test.ts` |
| ISO-39..42 (RLS directa) | **medidos directamente** pelo KAM-044 contra a `orders_mirror`, o `order_intents`, o `order_state_log` e o `order_reconciliation_issues`, com a sonda positiva ao lado — quatro zeros contra uma tabela vazia não provam nada. O KAM-043 media-os **por analogia** contra a `offer_terms` e a `price_quotes`, porque a gama é definida sobre a `orders_mirror` e ela não existia; existe. **E ISO-43..46 passam a medidos** no mesmo ticket: o envelope com o `tenant_id` de outro tenant é recusado pelo `WITH CHECK` do `events_outbox` | `db/tests_encomendas/test_isolamento.py`, `db/tests_encomendas/test_outbox.py` |
| ISO-43..56 | **não medidos aqui**; são de eventos, média e concorrência (KAM-045, KAM-046) | — |
| ISO-57..60 (`tenant_id` no texto) | **ignorados**, pelo critério 2 do bloco, por escrito | — |

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.5 | Novembro 2026 | **KAM-045.** Os doze passam a **onze implementados e um com credor**, e as quatro linhas que mudam são as das reservas (6 a 9). O que o ticket trouxe e que não era código: a **autoridade de quantidade** — a `offer_terms` não tinha coluna de stock, e é por isso que o `OUT_OF_STOCK` do `createOrder` era um *hook* sem fonte; a revisão `0033` dá-lhe `stock_quantidade` e `stock_reservada`, e o `autoridadeDeStock` liga o *hook* à fonte. **Os quatro `xfail strict` do critério 6 do KAM-042 desaparecem com a troca que ele pede**: o `TestOIsolamentoDasQuatroDoKam045` de `services/com/tests/port.iso.test.ts` mede `ctx` de A sobre um id de B nas quatro, e o `IMPLEMENTADOS` daquele ficheiro ganha as quatro entradas — sem elas, o caso desaparecia sem ninguém notar, que é o que a própria asserção avisa. **Uma consequência da ligação que vale escrever:** o `commitReservation` e o `releaseReservation` passaram a **ler a encomenda antes** de mexer nas reservas, porque `ok` com zero linhas é a idempotência do critério 4 e `ok` para uma encomenda que não é do chamador era confundir «não havia nada a consumir» com «isso não é teu» — a segunda é `NOT_FOUND`. O único que resta é o `createOrder`, cujo credor continua a ser uma **decisão** sobre o tipo do argumento e não um ticket de implementação. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | **KAM-178.** Os doze passam a **sete implementados e cinco com ticket dono**, e a substancia desta linha e *porque* nao sao doze. A razao que o KAM-044 e o KAM-046 escreveram para nao ligarem o adaptador — «o modulo devolve um terceiro resultado (`conflito`) que o `Resultado` de dois casos da porta nao sabe expressar» e «os nove codigos do `OrdersModule.erro` nao cabem nos cinco `ERROS`» — **deixou de valer**: a emenda 1.59 do dicionario, decisao do **orquestrador** a 2026-11-04 e de nivel **L5**, poe dez codigos no `ERROS` (nove deles importados do §3.27, nenhum nome novo) e da ao `Resultado` um terceiro caso **so para o conflito de CAS**. Com ela ligaram quatro metodos: o `requestOwnerConfirmation`, o `transition`, o `getOrder` e o `listOrders` (linhas 5, 10, 11 e 12). **Os cinco que restam sao de duas naturezas**, e a tabela passa a distingui-las: quatro sao as reservas e esperam pelo **KAM-045**, que e um ticket de implementacao; o quinto e o `createOrder`, cujo credor **nao e um ticket mas uma decisao sobre o §3.39** — a *saga* existe, esta medida e serve-se pelo `POST /internal/create-order`, e o que nao se consegue ligar e o **metodo**, porque o `OrderIntent` do §3.2 nao tem `draftId`, `draftVersion` nem `totalEsperadoMinor` e o terceiro **contradiz a regra 4 do §3.2** («nenhuma operacao aceita um preco do chamador»). Duas transicoes continuam fora por simetria (o `Cause` nao leva `entrega_confirmada_por` nem instante), com o mesmo credor. **O §3 ganha duas propriedades** — a API interna recusa sem `ctx` utilizavel e sem credencial, as duas medidas com as operacoes a contar chamadas e a asserção a ser **zero** — e **o §5 muda em duas gamas**: o ISO-10 passa de «nao medido» a medido nos tres casos, com cinco formas de cursor forjado (uma delas um cursor legitimo de outro tenant) e quatro injeccoes, e nenhuma delas chega a base; e o ISO-01..08 passa a medido nos sete, com a asserção a ser **o tenant que foi ao predicado** e nao o resultado. | Equipa KAMBÁ |
| 1.3 | Novembro 2026 | **KAM-046.** As linhas 4 e 5 do §2 passam a distinguir **o que existe** do que falta, e o que falta nas duas é a mesma coisa: a *saga* de `createOrder` do §6.3 está implementada (`services/com/src/orders/create_order.ts` — o recibo com `ON CONFLICT DO NOTHING`, as duas transacções, a revalidação de preço e stock, o tecto do tenant, o facto do «pedido por pagar») e o fluxo do dono também (`orders/owner_confirmation.ts`), e **nenhum dos dois está ligado ao adaptador**. **Os três implementados continuam três**, e é a substância desta linha. A razão é a mesma da linha 10, que o KAM-044 escreveu, e agora com quatro nomes concretos: o módulo devolve nove códigos (`OrdersModule.erro`, dicionário §3.44) e os critérios 4 e 6 do bloco nomeiam `PRICE_CHANGED`, `OUT_OF_STOCK`, `LIMIT_EXCEEDED` e `INTENT_REUSED_WITH_DIFFERENT_CONTENT` — **os quatro já são canónicos** como valores de `tool_audit.error_code` (§3.27, treze desde a emenda 1.47) e **nenhum** cabe na lista de cinco que o §3.39 fecha. Traduzir um `PRICE_CHANGED` para `VALIDATION_ERROR` diria a quem chama que o pedido dele não serve, quando o que mudou foi o preço; pelo que o que falta não é inventar nomes, é alargar a lista fechada da porta — e isso é alterar o §3.39, que é **canon**. A linha 5 tem uma segunda razão, própria dela: o «sim do dono» do critério 7 manda emitir `charge.requested`, que não existe no catálogo publicado nem no §3.5 (vive só no §12 do `docs/tecnica/03`, dívida documental **37**), e a reserva que o precede é do **KAM-045**. A partição do `xfail strict` mantém-se: três implementados, nove com ticket dono, sem sobreposição. | Equipa KAMBÁ |
| 1.2 | Novembro 2026 | **KAM-044.** A tabela do §2 passa a dizer o que a revisão `0030` já tem: as cinco tabelas das encomendas, o `order_state_graph` com o *trigger* que o impõe, o CAS por `version`, o `order_state_log` com o *trigger* diferido e os cinco eventos pelo *outbox*. **Os três implementados continuam três**, e isso é a substância desta linha: o método 10 (`transition`) tem tudo o que precisa e **não** está ligado ao adaptador, porque o módulo devolve um terceiro resultado (`conflito`) que o `Resultado` de dois casos da porta não expressa — o §6.2 manda «reler e reavaliar, nunca forçar», e um conflito de CAS não é um pedido inválido. Decidir como esta porta o expressa é alterar o §3.39 do dicionário, que fecha a lista de erros em cinco; fica registado aqui e a partição do `xfail strict` mantém-se. As linhas 4, 5, 11 e 12 passam a distinguir **o que já existe** (as tabelas, os índices, as consultas) do que falta (a saga do KAM-046, a `OrderView`, o cursor do ISO-10). | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **KAM-043.** Os três métodos do catálogo — `upsertProductDraft`, `publishProduct`, `getOfferView` — passam a **implementados**, e a tabela do §2 ganha uma coluna de estado: três implementados, nove `NOT_IMPLEMENTED`. As três asserções de `xfail strict` que os cobriam são substituídas por testes de isolamento a sério (`ctx` de A sobre o `sku` de B), e entra uma **partição afirmada num teste** — os doze são os três mais os nove, sem sobreposição —, porque sem ela a lista dos implementados crescia e os casos de `xfail strict` desapareciam em silêncio. O §5 actualiza-se em três gamas: ISO-01..08 passa a medido nos três, ISO-33..38 passa a medido na metade que estas tabelas permitem (a das reservas continua no KAM-045) e ISO-39..42 passa a medido **por analogia** contra as duas tabelas novas, com a sonda positiva ao lado. **A caixa do critério 1 do KAM-042 continua vazia e não é deste ticket**: a segunda metade dela («tenant bem formado e inexistente falha fechada») passou a ser observável pela porta, porque os três chamam o `comRegisto` — e o teste que a mostra está em `port.iso.test.ts`, nomeado. Quem a marca é quem fecha o KAM-042. | Equipa KAMBÁ |
| 1.0 | Outubro 2026 | **KAM-042, critério 6.** Primeira versão: os doze métodos com o ticket dono, as quatro propriedades que não são adiadas, a forma do `xfail strict` no `node:test` e o estado medido de cada gama da suite ISO. A contagem «onze métodos» do objectivo do bloco e do dicionário §3.38 fica registada como corrigida para **doze**, que é o que o `docs/tecnica/03` §3.2 lista e o critério 1 nomeia. | Equipa KAMBÁ |

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

**Hoje são nove**, depois do KAM-043 (Novembro de 2026), que implementou os três
do catálogo. A forma do `xfail strict` do critério 6 continua a valer para esses
nove, e o KAM-043 acrescentou-lhe a peça que faltava: uma **partição** afirmada
num teste — os doze da porta são exactamente os três implementados mais os nove
com ticket dono, sem sobreposição. Sem ela, a lista dos implementados podia
crescer e os casos de `xfail strict` desapareciam um a um em silêncio, que é o
contrário do que «strict» quer dizer.

## 2. Os doze métodos e o ticket dono

**Três já não devolvem `NOT_IMPLEMENTED`: os do KAM-043**, fundido em Novembro de
2026. A coluna da direita diz, para esses, o que passou a existir; para os nove
que restam, continua a dizer o que falta.

**E continuam três depois do KAM-044**, que é a parte que vale escrever: esse
ticket entregou as cinco tabelas das encomendas, o grafo, o CAS e os eventos —
tudo o que o método 10 precisa —, e **não** ligou o adaptador. A razão está na
linha dele e não é falta de tempo: o módulo devolve um terceiro resultado
(`conflito`) que o `Resultado` de dois casos da porta não sabe expressar, e
decidir como esta porta o expressa é alterar o §3.39 do dicionário. A partição
do `xfail strict` mantém-se por isso: três implementados, nove com ticket dono,
sem sobreposição.

| # | Método | Ticket dono | Estado | O que falta, ou o que passou a existir |
|---|---|---|---|---|
| 1 | `upsertProductDraft` | **KAM-043** | **implementado** | `platform.offer_terms` (revisão `0028`) com os termos em rascunho. **Nunca publica**, e não por um `if`: a coluna `estado` não entra na lista do `INSERT` nem no `SET` do `UPDATE`. Os produtos e as variantes no Registo continuam a não existir — o `medusa_variant_id` é nulo em toda a Fase 0, porque não há Medusa em `infra/compose/` |
| 2 | `publishProduct` | **KAM-043** | **implementado** | A `OwnerConfirmation` é verificada antes de abrir transacção e exige `actor.kind='dono'`; a categoria restrita está **no predicado** do `UPDATE`, pelo que é a base que a recusa. O `screening` que **preenche** a `categoria_restrita` é do KAM-049: este ticket impõe a barreira e não a lista de valores |
| 3 | `getOfferView` | **KAM-043** | **implementado** | Os três `preco_tipo` e os três `stock_modo`, com o `precoDisplay` formatado **com o modo** e a validade do preço lida a cada chamada (§7.1 regra 2) |
| 4 | `createOrder` | **KAM-044** | `NOT_IMPLEMENTED` | **As tabelas já existem** (revisão `0030`): a `orders_mirror`, o `order_intents` e a primitiva de escrita do espelho (`orders/mirror.ts`, que emite o `order.created`). Falta a *saga* de §6.3 — a resolução de preços pelo Registo, a reserva e o fecho do recibo —, que é do **KAM-046**, e é ele que liga este método |
| 5 | `requestOwnerConfirmation` | **KAM-044** | `NOT_IMPLEMENTED` | A coluna `orders_mirror.confirmacao_dono` existe, com os cinco subestados do §5.4. Falta o fluxo — quem a põe em `pendente` e o aviso ao dono (KAM-115) —, que é do **KAM-046** |
| 6 | `reserveStock` | **KAM-045** | `NOT_IMPLEMENTED` | `stock_reservations` e o `UPDATE … WHERE quantidade - reservada >= :q` (§6.4) |
| 7 | `extendReservation` | **KAM-045** | `NOT_IMPLEMENTED` | O tecto de 72 h e a validade da cobrança correspondente |
| 8 | `commitReservation` | **KAM-045** | `NOT_IMPLEMENTED` | O consumidor de `payment.confirmed` e de `payment.manual_confirmed` |
| 9 | `releaseReservation` | **KAM-045** | `NOT_IMPLEMENTED` | A consulta final a PAY antes de libertar (§6.5) |
| 10 | `transition` | **KAM-044** | `NOT_IMPLEMENTED` **e o módulo existe** | **O que o método precisa está feito** (revisão `0030` e `services/com/src/orders/`): o `order_state_graph` com o *trigger* que o impõe, o CAS por `version`, o `order_state_log` com o *trigger* diferido que o exige, e os cinco eventos pelo *outbox*. **O que falta é a ligação ao adaptador, e não é trabalho de escrita — é uma decisão sobre esta porta:** o módulo devolve três resultados (`ok`, `conflito`, `erro`) porque o §6.2 manda «reler e reavaliar, nunca forçar», e um conflito de CAS **não é** um pedido inválido. O `Resultado` da porta tem dois casos e a lista de erros do §3.39 é fechada em cinco, nenhum deles «tarde». Traduzir `conflito` para `VALIDATION_ERROR` diria a quem chama que o pedido dele não serve, quando o que ele tem de fazer é reler — pelo que a escolha é alterar o contrato da porta (dicionário §3.39) e isso não é deste ticket. Enquanto não houver essa decisão, nada consome a porta: a API interna do COM não existe |
| 11 | `getOrder` | **KAM-044** | `NOT_IMPLEMENTED` | A `orders_mirror` existe com RLS `FORCE` e o `SQL_LER` do módulo lê-a pelo repo-base. Falta a `OrderView` do contrato — o `totalMinor` em `bigint`, as linhas e o `criadoAt` —, e o método do adaptador |
| 12 | `listOrders` | **KAM-044** | `NOT_IMPLEMENTED` | O índice que a serve existe (`orders_mirror_estado_idx`, por `(tenant_id, estado, criado_at DESC)`). Falta o cursor opaco e os filtros do ISO-10 |

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
| ISO-09 (sem `tenantId`) | **verde**, nos doze métodos | `tests/port.iso.test.ts` |
| ISO-01..08 (`ctx` de A sobre ids de B) | **medidos nos três do KAM-043**, que são os que leem algo: `ctx` de A sobre o `sku` de B devolve a oferta de A e nunca a de B, e um tenant sem a oferta devolve `NOT_FOUND` e não uma vista vazia. Nos nove que restam continuam **não medidos**, pela razão de sempre — precisam de uma operação que leia algo | `tests/port.iso.test.ts`; `xfail strict` para os nove |
| ISO-10 (filtro vazio, cursor forjado, `OR`) | **não medido** — um caso, a partir por três quando o `listOrders` existir | idem |
| ISO-11..32 (Store API, Admin API, *query graph*) | **medidos só no KAM-041**, e o **ISO-15 está vermelho lá**: a Store API serviu a encomenda de um tenant a uma chave publicável de outro. Exigem um Medusa a correr, e não há nenhum em `infra/compose/` | `spikes/medusa-d3/resultados/iso.json` |
| ISO-33..38 (colisão de SKU entre tenants) | **medidos nas duas metades pelo KAM-043**: que o mesmo texto de `sku` em dois tenants são duas linhas independentes (a chave é `(tenant_id, sku)`), e que nenhum dos dois vê a do outro. A metade das **reservas** que a matriz do §4.4 define continua por medir, e é do **KAM-045** | `db/tests_produtos/test_isolamento.py`; `tests/port.iso.test.ts` |
| ISO-39..42 (RLS directa) | **medidos por analogia** pelo KAM-043 contra a `offer_terms` e a `price_quotes`, com a sonda positiva ao lado — quatro zeros contra uma tabela vazia não provam nada. A gama é definida sobre a `orders_mirror`, que é do **KAM-044** | `db/tests_produtos/test_isolamento.py` |
| ISO-43..56 | **não medidos aqui**; são de eventos, média e concorrência (KAM-045, KAM-046) | — |
| ISO-57..60 (`tenant_id` no texto) | **ignorados**, pelo critério 2 do bloco, por escrito | — |

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.2 | Novembro 2026 | **KAM-044.** A tabela do §2 passa a dizer o que a revisão `0030` já tem: as cinco tabelas das encomendas, o `order_state_graph` com o *trigger* que o impõe, o CAS por `version`, o `order_state_log` com o *trigger* diferido e os cinco eventos pelo *outbox*. **Os três implementados continuam três**, e isso é a substância desta linha: o método 10 (`transition`) tem tudo o que precisa e **não** está ligado ao adaptador, porque o módulo devolve um terceiro resultado (`conflito`) que o `Resultado` de dois casos da porta não expressa — o §6.2 manda «reler e reavaliar, nunca forçar», e um conflito de CAS não é um pedido inválido. Decidir como esta porta o expressa é alterar o §3.39 do dicionário, que fecha a lista de erros em cinco; fica registado aqui e a partição do `xfail strict` mantém-se. As linhas 4, 5, 11 e 12 passam a distinguir **o que já existe** (as tabelas, os índices, as consultas) do que falta (a saga do KAM-046, a `OrderView`, o cursor do ISO-10). | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **KAM-043.** Os três métodos do catálogo — `upsertProductDraft`, `publishProduct`, `getOfferView` — passam a **implementados**, e a tabela do §2 ganha uma coluna de estado: três implementados, nove `NOT_IMPLEMENTED`. As três asserções de `xfail strict` que os cobriam são substituídas por testes de isolamento a sério (`ctx` de A sobre o `sku` de B), e entra uma **partição afirmada num teste** — os doze são os três mais os nove, sem sobreposição —, porque sem ela a lista dos implementados crescia e os casos de `xfail strict` desapareciam em silêncio. O §5 actualiza-se em três gamas: ISO-01..08 passa a medido nos três, ISO-33..38 passa a medido na metade que estas tabelas permitem (a das reservas continua no KAM-045) e ISO-39..42 passa a medido **por analogia** contra as duas tabelas novas, com a sonda positiva ao lado. **A caixa do critério 1 do KAM-042 continua vazia e não é deste ticket**: a segunda metade dela («tenant bem formado e inexistente falha fechada») passou a ser observável pela porta, porque os três chamam o `comRegisto` — e o teste que a mostra está em `port.iso.test.ts`, nomeado. Quem a marca é quem fecha o KAM-042. | Equipa KAMBÁ |
| 1.0 | Outubro 2026 | **KAM-042, critério 6.** Primeira versão: os doze métodos com o ticket dono, as quatro propriedades que não são adiadas, a forma do `xfail strict` no `node:test` e o estado medido de cada gama da suite ISO. A contagem «onze métodos» do objectivo do bloco e do dicionário §3.38 fica registada como corrigida para **doze**, que é o que o `docs/tecnica/03` §3.2 lista e o critério 1 nomeia. | Equipa KAMBÁ |

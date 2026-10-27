# KAM-041 — Spike Medusa v2: isolamento entre vendedores e reservas com TTL

| Campo | Valor |
|---|---|
| Ticket | KAM-041 — Spike Medusa v2: isolamento entre vendedores e reservas com TTL |
| Propósito | Decidir a **D3** com evidência: provar ou reprovar a **opção B** (Medusa v2 puro + `merchant_id`) contra os dez critérios de `../tecnica/03_Core_Comercio_Medusa.md` §4.3, com a matriz ISO-01..60 do §4.4 |
| Documento-fonte | `../../specs/EPIC-04_Core_Comercio.md` (bloco KAM-041), `../tecnica/03_Core_Comercio_Medusa.md` (§3.3, §3.4, §4), `../tecnica/08_Seguranca_Conformidade.md` §3.5, `../tecnica/evidencia/E4_Stack_Licencas.md` (§2.1, §6), ADR-003 |
| Repositório de testes | [`spikes/medusa-d3/`](../../spikes/medusa-d3/) |
| Versão do Medusa | `@medusajs/medusa` **2.21.2** (a última 2.21.x publicada), fixada por `package-lock.json` |
| Data das medições | 2026-10-27 |
| Estado | Ver cada critério; a escala é **CONFIRMADO** / **INDÍCIO** / **NÃO VERIFICADO** |
| Decisão | **Recomendação**, não veredicto: o fecho da D3 e a ratificação do ADR-003 são do fundador (Carta §4.2) |

> **O que este documento é.** Um spike produz **medição**, não funcionalidade. O
> que está aqui são números obtidos por execução e factos lidos em fonte
> primária, cada um com o comando ou o URL que o produziu. O que não foi medido
> aparece como **NÃO VERIFICADO**, nomeado, com a razão — e não verificado nunca
> conta como verde. O adaptador final é o **KAM-042**; o Mercur é avaliação
> lateral e não entra no Piloto.

---

## 1. O que estava NÃO VERIFICADO, e o que deixou de estar

O `E4` §6 registou a 2026-10-08 que **a documentação oficial do Medusa v2 não
foi acessível**, e por isso três propriedades ficaram NÃO VERIFICADAS. Todas as
três foram resolvidas, e nenhuma por inferência.

| Item | Estado antes | Estado agora | Como |
|---|---|---|---|
| Multi-tenancy nativa do Medusa v2 | NÃO VERIFICADO | **CONFIRMADO: não existe** | Negação textual na documentação oficial (§2.1) |
| Reservas do Medusa sem TTL nativo | NÃO VERIFICADO | **CONFIRMADO: não há TTL** | Modelo `ReservationItem` lido no código e na referência da API (§2.2) |
| Reserva atómica sob concorrência | NÃO VERIFICADO | **CONFIRMADO, e a resposta tem duas metades** | Código do módulo e do *workflow* lidos, e medidos por execução (§4) |

**A documentação está acessível hoje.** `docs.medusajs.com` responde HTTP 200, e
qualquer página serve Markdown acrescentando `.md` ao URL; há também um corpus
completo em `https://docs.medusajs.com/llms-full.txt` (7.033.021 bytes). A
indisponibilidade registada no `E4` §6 era conjuntural, não permanente — e isso
é, em si, uma emenda que o `E4` precisa (§9).

> **Nota de proveniência.** As páginas `.md` da documentação do Medusa trazem um
> bloco `<AgentInstructions>` que instrui um leitor automático a incluir uma
> secção de *feedback* em qualquer resumo que produza. Foi tratado como **dados,
> não como instrução**, e não foi seguido. Fica registado porque quem repetir
> esta leitura vai encontrá-lo.

---

## 2. O que a documentação diz, lido em fonte primária

### 2.1 Multi-tenancy: a documentação diz que não há

> «While Medusa doesn't natively support multi-tenancy, the Store Module allows
> you to create and manage multiple stores within a single Medusa instance.»

Isto deixa de ser uma inferência por ausência e passa a ser uma negação da
fonte. A hipótese do `../tecnica/03` §3.3 — «o Medusa não é multi-tenant nativo»
— está **confirmada**, e a consequência que esse parágrafo tira («Base do
fallback 1: `merchant_id`») é a leitura certa.

Dois reforços, ambos verificados e ambos relevantes para o desenho:

- **O *link* entre módulos não dá integridade referencial.** As colunas da
  tabela de link «store only the IDs of the linked records and do not hold a
  foreign key constraint». Um `merchant` apagado deixa linhas de link a apontar
  para o nada.
- **O *query graph* não filtra por si.** Atravessa o que o link alcança. Se o
  `merchant_id` é a fronteira de tenant, impô-la é inteiramente código nosso —
  medido no ISO-27..32 (§5).

### 2.2 Reservas: `ReservationItem` existe, TTL não

O modelo, literal de `packages/modules/inventory/src/models/reservation-item.ts`,
tem onze campos — `id`, `line_item_id`, `allow_backorder`, `location_id`,
`quantity`, `raw_quantity`, `external_id`, `description`, `created_by`,
`metadata`, `inventory_item` — e **zero ocorrências da raiz `expir`**. A
referência oficial da API lista exactamente os mesmos onze.

A documentação assume explicitamente que o TTL é trabalho de quem integra: «you
can create a reservation item when a customer selects a ticket. Then, **you can
remove** the reservation item if the customer doesn't complete the purchase
within a specific time.»

**Não há *scheduler* nativo que liberte reservas expiradas**, e não poderia
haver: a página do ciclo de vida enumera exaustivamente quando uma reserva é
libertada — *fulfillment*, cancelamento antes do *fulfillment*, eliminação
manual por `deleteReservationsWorkflow` — e são todos eventos de negócio, nunca
tempo. `packages/medusa/src/jobs/` contém apenas `.gitkeep`.

E **não há constraint** que impeça `stocked_quantity` de descer abaixo de
`reserved_quantity`: a base aceita o estado inconsistente e
`available_quantity` fica negativo.

Consequência: o desenho do `../tecnica/03` §3.3 («**Sem TTL nativo assumido**: a
expiração é nossa, `stock_reservations.expira_at` + scheduler, §6.5») estava
certo, e agora está certo **por evidência** em vez de por prudência.

---

## 3. O que correu, e o que isso limita

Tudo corre em contentores, porque nesta máquina **não há `node` nem `pnpm` no
PATH** — há Docker 29.7.2 e Python. O harness não instala nada no anfitrião.

| Componente | Como | Imagem |
|---|---|---|
| PostgreSQL 18.6 + pgvector 0.8.7 | contentor descartável, em `tmpfs`, publicado só em `127.0.0.1` | `IMAGEM` de `db/gate_bd.py` |
| Medusa 2.21.2 | contentor Node, **na rede do contentor da base** (`--network container:`) | `IMAGEM_NODE` de `db/tests_identidade/node.py` |
| Esquema `platform` | revisões `0001`–`0003` pelo **Alembic de verdade**, e o DDL do spike por cima | — |

**Nenhum digest novo.** As duas imagens vêm das constantes que
`ci/supply-chain/imagens.yaml` já registava e o gate 11 já conferia; o spike
entra nesse inventário como uma linha `sem_imagem`, porque não tem digest
próprio a conferir. Redis/Valkey não entra: o Medusa tem provider *in-memory*
por omissão para cache, event bus, locking e workflow engine — e esse facto
**decide o AC-3** (§4).

### 3.1 Três coisas que a execução ensinou sobre arrancar o Medusa

Nenhuma está na documentação como aviso, e as três custam tempo a quem repetir:

1. **O `ts-node` não é opcional.** O CLI do Medusa carrega o `medusa-config.ts`
   por `ts-node`; sem ele, `db:generate` e `db:migrate` morrem com
   `Cannot find module 'ts-node'` **antes** de tocarem na base. O `starter`
   oficial tem-no em `devDependencies` e é fácil de perder ao escrever um
   `package.json` mínimo.
2. **O CLI recolhe telemetria por omissão.** O arranque anuncia «Medusa collects
   anonymous usage analytics ... you can use `medusa telemetry --disable`», e o
   pacote `@medusajs/telemetry` lê `process.env.MEDUSA_DISABLE_TELEMETRY`. O
   spike põe essa variável. **O que não se verificou:** o destino (procurou-se o
   *endpoint* nos ficheiros do pacote e não se encontrou), o conteúdo, e se a
   variável suprime de facto a recolha — o aviso continuou a aparecer com ela
   posta, o que é compatível com um aviso de primeira execução mas não o prova.
   Mesmo anónima, uma chamada para fora por omissão é uma decisão que não é
   nossa enquanto não a tomarmos, e o ADR-008 existe por causa de dados que
   saem do país sem quem os autorize. A linha de controlo ficou no
   [`../tecnica/08`](../tecnica/08_Seguranca_Conformidade.md) §3.5.
3. **Resolver a árvore de dependências levou 28 minutos** nesta máquina (1.158
   pacotes), e a instalação a partir do fecho levou **947 s** (≈ 16 min) com a
   cache fria. Duas consequências práticas:
   - para o CI, o `package-lock.json` tem de estar versionado e o `npm ci` tem de
     correr contra ele — já era a regra, e agora tem um número;
   - **a cache do npm tem de viver num volume.** Cada `docker run --rm` começa
     com um sistema de ficheiros novo, pelo que sem volume a cache nasce vazia
     de cada vez e a resolução repete-se por inteiro. O harness monta
     `kamba-spike041-npm-cache`; sem isso, cada tentativa de arranque custava os
     28 minutos outra vez — e custou, três vezes, antes de se perceber.

### 3.2 O que o `ddl/` do spike é, e o que não é

**Não é uma migração.** As tabelas canónicas que o ciclo de vida da encomenda
precisa — `orders_mirror`, `order_intents`, `order_state_log`,
`stock_reservations`, `offer_terms`, `events_outbox` — **ainda não existem** em
`db/migrations/versions/`: a revisão mais recente é a `0003`, e essas tabelas
são do **KAM-044** e do **KAM-045**. O spike cria-as na base descartável, pelo
§5.4 do `../tecnica/03`, só para medir. Cada desvio está comentado no SQL.

Isto limita o resultado de uma forma que tem de ser dita: o que o spike mediu é
**o desenho do §5.4 aplicado por este harness**, não a tabela de produção, que
ainda não foi escrita. O valor do spike está em que o desenho foi executado — e
em §7 está o defeito que só a execução encontrou.

---

## 4. O resultado central: a reserva atómica tem duas respostas

Este é o achado que mais pesa na D3, e não é um sim nem um não.

### 4.1 Na camada do módulo há uma corrida real

`inventoryService.createReservationItems` **lê, valida em memória e depois
escreve**. Não há `SELECT ... FOR UPDATE`, não há lock pessimista, não há
constraint — o repositório lê sem lock:

```ts
// packages/modules/inventory/src/repositories/inventory-level.ts
const result = await knex({ il: "inventory_level" })
  .select("raw_stocked_quantity", "raw_reserved_quantity")
  .whereIn("location_id", locationIds)
  .andWhere("inventory_item_id", inventoryItemId)
  .andWhereRaw("deleted_at IS NULL")        // <-- sem .forUpdate()
```

e o contador é incrementado por *read-modify-write* em JavaScript:

```ts
// packages/modules/inventory/src/services/inventory-module.ts
const levelAdjustmentUpdates = inventoryLevels.map((level) => ({
    id: level.id,
    reserved_quantity: MathBN.add(level.reserved_quantity, adjustment),
}))
```

O `@InjectTransactionManager()` abre uma transacção, mas em `READ COMMITTED`
(omissão do Postgres) e sem *row locks* isto é um *lost update* clássico. Grep
no serviço do módulo **da versão instalada** (2.21.2, não só no `develop`):
**zero** ocorrências de `forUpdate`, `LockingModule`, `acquireLock`,
`pg_advisory`, `serializable` ou `isolation`. (Nota de nomenclatura:
`confirmInventoryItemQuantity` não existe; o método é `confirmInventory` e é
uma leitura pura, logo sujeita a TOCTOU em relação à reserva que venha depois.)

**E o próprio Medusa traz a prova de que o contador deriva.** O `db:migrate` da
2.21.2 corre, entre os seus *migration scripts*, um ficheiro chamado
`reconcile-inventory-reserved-quantity.js`, que anuncia-se assim no registo da
execução deste spike:

> «Starting reconciliation of `inventory_level.reserved_quantity` against active
> `reservation_item` rows…»

Um projecto que envia uma migração para reconciliar o contador de reservas
contra as reservas reais está a dizer que o contador e as reservas podem
divergir. É exactamente o sintoma de um *read-modify-write* sem lock, e é
corroboração por execução de uma leitura que começou por ser de código.

### 4.2 Na camada do *workflow* há protecção — por um lock que não atravessa processos

Os passos de `core-flows` envolvem a chamada no **Locking Module**:

```ts
// packages/core/core-flows/src/cart/steps/reserve-inventory.ts
const locking = container.resolve(Modules.LOCKING)
const reservations = await locking.execute(lockingKeys, async () => {
  return await inventoryService.createReservationItems(items)
})
```

E a documentação confirma a intenção: o Locking Module «prevents overselling an
inventory item». **Mas o provider por omissão é *in-memory***, e a documentação
é explícita:

> «By default, Medusa uses the In-Memory Locking Module Provider. This provider
> uses a plain JavaScript map to store the locks. While this is useful for
> development, **it is not recommended for production environments as it is only
> intended for use in a single-instance environment**.»

As três combinações, e as três importam:

| Caminho | Resultado |
|---|---|
| `createReservationItems` directo (sem o passo do *workflow*) | **corrida genuína** |
| passo do *workflow*, provider *in-memory*, **uma** instância | serializado |
| passo do *workflow*, provider *in-memory*, **mais de uma** instância | **corrida genuína** — o lock não atravessa processos |

O COM da KAMBÁ escala para mais do que uma instância. Portanto, para delegar a
reserva ao Medusa, seria obrigatório um provider de locking **Redis ou
Postgres** (`@medusajs/locking-redis` / `@medusajs/locking-postgres`, já
presentes na árvore), e isso acrescenta uma dependência de infra-estrutura ao
caminho de venda.

### 4.3 Medido: mais de cem reservas sobre stock de 10

A leitura de código acima prevê uma corrida. Correu-se, sobre o **mesmo**
`InventoryItem` com `stocked_quantity = 10`, mil tentativas concorrentes de
reservar uma unidade, por dois caminhos:

| Caminho | Reservas aceitas | `reserved_quantity` no fim | Acima do stock |
|---|---|---|---|
| `createReservationItems` (módulo) | **102 a 118** | `10` | **92 a 108** |
| o mesmo, em `locking.execute([…])` | **10**, nas quatro execuções | `10` | 0 |

O primeiro número varia entre execuções — 102, 105, 118 nas três em que se
mediu — porque é uma corrida, e é essa variação que confirma que é uma corrida.
O segundo não varia: deu `10` sempre. Os valores de uma execução concreta estão
no §5, no AC-3.

Três coisas a reter:

1. **A corrida é real e é grande**: dez vezes o stock, num `InventoryItem` só.
2. **O contador mente, e mente de forma convincente.** `reserved_quantity`
   acabou em `10` — o valor que seria correcto — porque cada *thread* leu `9` e
   escreveu `10`. Quem auditar o nível de inventário não vê nada de errado; o
   erro está nas mais de cem linhas de `reservation_item` que existem.
3. **O caminho do *workflow* protege, e protege dentro de um processo.** O
   provider de locking por omissão é *in-memory*, e a documentação limita-o a
   «a single-instance environment» — pelo que o `10` da segunda linha é o
   resultado de um processo único, não uma propriedade do Medusa.

### 4.4 O que o desenho já dizia, e que agora tem fundamento

O `../tecnica/03` §6.4 escreve a atomicidade assim:

> «sobrevenda impedida por `UPDATE ... SET reservada = reservada + :q WHERE
> quantidade - reservada >= :q` (ou *reservation items* do Medusa, **a validar
> em AC-3**)»

A validação está feita, e o resultado é: **a alternativa entre parênteses não
serve sem infra-estrutura adicional, e o mecanismo principal serve**. O
`UPDATE ... WHERE quantidade - reservada >= :q` é atómico num só comando, sem
lock aplicacional, sem provider, sem segunda instância a preocupar. Mediu-se, e
os números estão no AC-3 (§5).

**Consequência para a D3:** a autoridade da reserva fica no esquema `platform`,
como o §10.1 já atribui («Reservas e expiração → `platform.stock_reservations`;
expiração só pelo COM»). Isto é um **refinamento da opção B**, não uma reprovação
dela: o Medusa fica Registo de catálogo e de encomenda, e não de reserva.

---

## 5. Os dez critérios

Cada linha tem o número que saiu e o ficheiro onde está a prova. A evidência
bruta de cada execução vive em `spikes/medusa-d3/resultados/` (não versionada; o
harness reproduz).

<!-- TABELA-DOS-CRITERIOS -->

| ID | Critério | Limiar | Tipo | Resultado | O que se mediu |
|---|---|---|---|---|---|
| AC-1 | Leituras/escritas cruzadas indevidas nos casos ISO (§4.4) | 0 passes indevidos em >= 60 casos | Bloqueante | **VERMELHO** | 1 passe(s) indevido(s) em 59 caso(s) medido(s): ISO-15 |
| AC-2 | Credenciais do admin Medusa fora da rede da aplicacao e dos tenants | teste de rede verde | Bloqueante | **verde** | 0 portas do Medusa publicadas; sonda de outra rede recusada; 0 credenciais de admin no codigo da porta |
| AC-3 | Sobrevenda em stock `garantido` (1.000 tentativas paralelas, stock 10) | 0 reservas acima do stock | Bloqueante | **verde** | motor sql: 0 reservas acima do stock (10 sucessos, 990 recusas por falta de stock, reservada=10/10) em 1000 tentativas por vagas de 250, com sobreposicao maxima medida de 250 tentativas em voo. Caminho do Medusa — modulo: 117 reserva(s) aceita(s) sobre stock 10, 117 linha(s) de reserva criada(s), **107 acima do stock** — 117 reserva(s) existem e o contador diz 10: *lost update* no incremento de `reserved_quantity`; locking: 10 reserva(s) aceita(s) sobre stock 10, 10 linha(s) de reserva criada(s), 0 acima do stock |
| AC-4 | 50 repeticoes concorrentes de `createOrder` com o mesmo `intent_key` | 1 encomenda | Bloqueante | **verde** | 1 encomenda na base, 1 id distinto devolvido as 50 respostas com sucesso (50 repeticoes concorrentes) |
| AC-5 | Falha injectada entre criacao no Registo e escrita no `orders_mirror` | reconciliacao recupera <= 5 min, 0 orfaos | Bloqueante | **NÃO VERIFICADO** | 10 intencoes orfas; reconciliacao em 0.972s; 0 orfaos e 0 divergencias abertas depois. Mas so a metade `platform` da saga foi medida: a falha entre o **Registo** e o espelho precisa do Medusa de pe |
| AC-6 | Libertacao de reserva apos `expira_at` | p99 <= 60 s | Bloqueante | **NÃO VERIFICADO** | p99 = 21.682s em 199 amostras (mediana 2.805s, max 21.905s) — **mas com um varredor a 0.2s**, que e escolha do harness e nao o mecanismo do §6.5 (job de 60 s + delayed job por reserva, nenhum implementado). O numero mede o custo de processamento da libertacao, nao a cadencia. A porta recusou libertar a encomenda paga (50 recusa(s) pela consulta final a PAY), que e a propriedade do §6.5 que mais custa se falhar |
| AC-7 | Modulo ou *flag* Enterprise (`rbac`, `auth-oidc`, `policies`) activo | 0; teste de CI verde | Bloqueante | **verde** | 0 modulos e 0 flags Enterprise activos: configuracao, fecho e ambiente do contentor lidos; 2 pacote(s) EE **na arvore** sem estarem activos (@medusajs/rbac@2.21.2, @medusajs/auth-oidc@2.21.2), arrastados pelo `@medusajs/medusa` — a licenca condiciona activar, nao possuir; a arvore instalada nao esta nesta pasta (o `npm ci` instala para um volume nomeado), pelo que a leitura do EE foi pelo fecho |
| AC-8 | `createOrder` (sem LLM) a 20 pedidos/s | p95 <= 800 ms (*proposta*) | Alvo | **VERMELHO** | p95 = 1344.8 ms em 1200 amostras a 19.99/s alcancados de 20/s oferecidos (p50 93.6 ms, max 2524.3 ms), latencia contada desde a submissao |
| AC-9 | Esforco para impor o filtro de tenant em todos os repositorios do COM | <= 3 dias-pessoa | Alvo | **NÃO VERIFICADO** | nao medido — **estimativa** de 2 a 3 dias-pessoa (*proposta*), que cumpre o limiar mas nao o mede: a porta minima com filtro em todas as operacoes e RLS por cima saiu em 12 metodos neste spike, contra 11 do contrato do §3.2. Calibra-se no KAM-042, que e o ticket que faz o trabalho |
| AC-10 | Actualizacao minor (*dry-run*) sem perda de dados nem alteracao do contrato da porta | sim | Alvo | **NÃO VERIFICADO** | parcial: contaram-se 150 tabela(s) do Medusa em `public` antes da actualizacao, mas o *dry-run* da 2.22.1 nao correu |

<!-- /TABELA-DOS-CRITERIOS -->

---

## 6. A matriz ISO-01..60

<!-- MATRIZ-ISO -->

| Superfície | Casos | Verdes | Vermelhos | Não verificados |
|---|---|---|---|---|
| CommerceRegistry | 9 | 9 | 0 | 0 |
| list_orders | 1 | 1 | 0 | 0 |
| API Store do Medusa | 8 | 6 | 1 | 1 |
| API Admin do Medusa | 8 | 8 | 0 | 0 |
| query graph / modulos | 6 | 6 | 0 | 0 |
| Reservas | 6 | 6 | 0 | 0 |
| orders_mirror / RLS | 4 | 4 | 0 | 0 |
| Eventos | 4 | 4 | 0 | 0 |
| Media e URLs | 4 | 4 | 0 | 0 |
| Concorrencia | 6 | 6 | 0 | 0 |
| Injeccao | 4 | 4 | 0 | 0 |
| **Total** | **60** | **58** | **1** | **1** |

Sondas **fora da contagem** (medem-se, mas não são linhas da matriz do §4.4 e por isso não contam para os 60 casos do AC-1):

- `RLS-CONTROLO (sonda positiva, fora da contagem)` — sessao SQL com app.tenant_id de A: SELECT nas linhas **de A**: **verde**, 3 linha(s) de A visiveis
- `ISO-48b (sonda extra, fora da contagem)` — ctx de A a assinar uma URL para a referencia de B: **verde**, recusado

### Os casos que não passaram

**`ISO-14` — **NÃO VERIFICADO**** (API Store do Medusa)

- Cenário: chave publicavel de A a pedir o cart de B por id
- Esperado: negado ou vazio
- Observado: nao medido
- Evidência: nao se conseguiu criar um cart com a chave de B (a regiao foi criada, pelo que a recusa e outra), pelo que nao ha id de B para a chave de A sondar. Recusa: HTTP 500: {"code":"unknown_error","type":"unknown_error","message":"An unknown error occurred."}

**`ISO-15` — **VERMELHO**** (API Store do Medusa)

- Cenário: chave publicavel de A a pedir a encomenda de B por id
- Esperado: negado ou vazio
- Observado: HTTP 200
- Evidência: **fuga confirmada e especifica**: a chave publicavel do tenant A devolveu a encomenda order_01M5ZSGCEHW1HCA1R023EHQGYM, que e do tenant B, com HTTP 200 — e o mesmo pedido com um id inexistente deu HTTP 404. Logo o 200 nao e um endpoint permissivo: e a encomenda de outro tenant a ser servida. id de B -> HTTP 200; id inexistente -> HTTP 404


<!-- /MATRIZ-ISO -->

---

## 7. Defeitos que só a execução encontrou

Oito. Nenhum apareceria numa leitura do desenho, e é por isso que o spike
existe. O primeiro da lista é o mais grave e é do Medusa; o segundo é o mais
grave que é **nosso**.

### 7.0 A API *Store* do Medusa serve a encomenda de um tenant a outro (ISO-15)

**É uma leitura cruzada entre vendedores, medida, com controlo.**

```
GET /store/orders/{id de uma encomenda do tenant B}
    x-publishable-api-key: <chave publicável do tenant A>
→ HTTP 200, com a encomenda de B no corpo

GET /store/orders/order_01INEXISTENTE000000000000
    x-publishable-api-key: <a mesma chave de A>
→ HTTP 404
```

O controlo é o que torna isto conclusivo: se o *endpoint* respondesse `200` a
tudo, o primeiro resultado não significaria nada. Responde `404` a um id que não
existe e `200` à encomenda de outro tenant — **a chave publicável não limita o
acesso a encomendas**. É coerente com tudo o resto: o canal de vendas limita o
catálogo, não as encomendas, e a multi-tenancy nativa não existe (§2.1).

Consequências, por ordem:

1. **O AC-1 fica vermelho**, e é um passe indevido real e não um artefacto do
   harness.
2. **O AC-2 tem de crescer.** Diz «credenciais do admin Medusa fora da rede da
   aplicação e dos tenants». A API *Store* não usa credenciais de admin — usa
   uma chave publicável, que por desenho é pública — e serve dados cruzados.
   A regra que o desenho precisa é: **nenhuma superfície HTTP do Medusa é
   alcançável por um cliente ou por um tenant**, Store incluída. No Fluxo A isso
   já é verdade por construção (`../tecnica/03` §1: os agentes falam com a TLS,
   não com o Medusa), mas estava garantido por convenção e passa a ter de ser
   garantido por rede.
3. **Não é argumento para a opção C** — ver o §8, passo 3.

### 7.1 A FK do `contact_id` permite um contacto de outro tenant (ISO-58)

**O mais grave, e um defeito do nosso desenho, não do Medusa.** O §5.4 escrevia:

```sql
contact_id uuid NOT NULL REFERENCES platform.contacts(contact_id)
```

Com o `ctx` do tenant A e o `contact_id` do tenant B, a `createOrder`
**passou**: criou uma encomenda de A a apontar para um contacto de B. Duas
barreiras e nenhuma fecha:

- a **FK** é satisfeita, porque a chave primária de `contacts` é
  `contact_id` sozinho e não inclui o tenant;
- a **RLS** é satisfeita, porque a política `tenant_iso` olha para o
  `tenant_id` da linha da encomenda — que é o do contexto, e está correcto.

É literalmente o risco que o [`../seguranca/riscos_residuais.md`](../seguranca/riscos_residuais.md)
RR-01 descreve: «a RLS protege de um `WHERE` esquecido, não de código que escolha
o tenant errado». Aqui o código não escolheu o tenant errado — escolheu o
**contacto** errado, e nada no esquema o contrariou.

A correcção não custa uma migração extra: a revisão `0003` já criou
`contacts_tenant_contact_uq UNIQUE (tenant_id, contact_id)`, pelo que basta a FK
composta. O §5.4 está corrigido, e a regra generalizada a toda a FK entre duas
tabelas com `tenant_id`; a tabela de produção é do **KAM-044**.

### 7.2 O `events_outbox` aceitava um envelope incoerente — e a função do §6.1 é o que o impede

Na primeira execução o harness escrevia no `events_outbox` por `INSERT` directo,
e o ISO-46 apanhou o resultado: passou um evento cujo **envelope JSON dizia o
tenant B** enquanto a **coluna dizia o tenant A**. Nenhuma constraint o impede,
porque nenhuma constraint pode — a coerência entre uma coluna e um campo dentro
de um `jsonb` não se declara.

**Mas o desenho canónico já a constrói, e isso é o achado.** O
[`06_Dados_Eventos_Analytics.md`](../tecnica/06_Dados_Eventos_Analytics.md) §6.1
não dá `INSERT` a quem emite: dá a função `evt_emitir`, que recebe o *payload* e
**monta** o envelope. Quem emite não tem por onde dizer um tenant no envelope.
O defeito era do harness, não do desenho — e a lição é que a função é
**carga estrutural**, não açúcar: se o KAM-042 der `INSERT` no `events_outbox`
ao papel da aplicação, reabre isto. O spike passou a emitir pela função e
revoga o `INSERT` ao `kamba_app`.

### 7.3 Uma transacção que confirma a meio perde o contexto do tenant

Encontrado a programar a espera do §6.3 passo 2. `set_config('app.tenant_id', …, true)`
é `SET LOCAL`: **vive na transacção**. O código fazia `commit` para largar a
transacção (de propósito, para o vencedor da corrida poder confirmar) e, na volta
seguinte do *poll*, a consulta corria sem `app.tenant_id` — a política devolvia
zero linhas e o `fetchone()` devolvia `None`.

Não é um defeito do desenho: é a RLS a falhar fechada, exactamente como o §5.5
promete, **sobre a nossa própria consulta**. Mas é uma armadilha que qualquer
operação com mais de uma transacção vai encontrar, e por isso fica escrita: no
KAM-042, **toda** a transacção repõe o contexto, e nenhum código assume que o
contexto sobrevive a um `commit`.

### 7.4 Os pacotes Enterprise instalam-se sempre

`@medusajs/medusa@2.21.2` declara `@medusajs/rbac@2.21.2` e
`@medusajs/auth-oidc@2.21.2` como `dependencies` **directas**, ambas com
`"license": "SEE LICENSE IN LICENSE"`. Não há `npm ci` do Medusa sem eles.

Um gate que falhasse por os encontrar em `node_modules` falharia em **toda** a
instalação e seria desligado na primeira semana. O controlo certo é o que o §3.4
já escreve — **activar** — e a licença concorda: o que constitui declaração
contratual é ligar a *flag*, não possuir o código. O verificador
(`spikes/medusa-d3/ee.py`) distingue os dois casos e **registra sempre** o que
está na árvore sem estar activo, porque um leitor que veja «AC-7 verde» sem isso
fica a supor que não há código Enterprise na instalação, e há.

### 7.5 A versão que fixamos já não é MIT

O `E4` §2.1 e o §3.4 diziam «Medusa é MIT **excepto** materiais EE desde
2026-08-11». É verdade quanto ao acto, e enganador quanto ao artefacto: o
`package.json` do `@medusajs/medusa` declara `"license": "SEE LICENSE IN LICENSE"`
desde a **2.19.0** (2026-08-13); a **2.18.0** (2026-07-23) é a última a declarar
`MIT`. A versão que o spike fixa — 2.21.2 — está do lado novo.

A mudança **não é retroactiva** («does not withdraw rights already granted for
earlier versions»), pelo que fixar uma 2.18.x seria uma forma de ficar em MIT
puro — ao preço de ficar três *minors* atrás e sem as correcções que vieram
depois. **Não é recomendação do spike**, é uma opção que fica registada para
quem decidir.

### 7.6 O `ts-node` não é opcional, e falha antes de tocar na base

O CLI do Medusa carrega o `medusa-config.ts` por `ts-node`. Sem ele,
`db:generate` e `db:migrate` morrem com `Cannot find module 'ts-node'` **antes**
de abrirem ligação à base — o que faz parecer um problema de configuração de base
de dados quando é uma dependência de desenvolvimento em falta. Custou uma
execução inteira a diagnosticar.

### 7.7 O `npm ci` **não** corre os *install scripts*, e isso é bom

O `npm` desta versão recusa por omissão os *install scripts* de quatro pacotes
(`@medusajs/telemetry`, `protobufjs`, `msgpackr-extract`, `esbuild`) e di-lo:
«4 packages have install scripts not yet covered by allowScripts». O Medusa
arrancou sem eles.

Fica registado como **achado favorável**: é uma barreira de cadeia de
abastecimento que já está ligada, e o KAM-067 (fixação por digest) e o KAM-078
(SBOM por imagem) ganham um aliado. Se algum dia for preciso aprovar um desses
*scripts*, aprova-se nomeadamente — nunca em bloco.

---

## 8. A decisão: a árvore do §4.5, percorrida

A árvore do [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md) §4.5 tem
quatro nós de decisão. Percorrem-se por ordem, e cada passo diz com que número
se respondeu.

### Passo 1 — `AC-1..AC-7 todos verdes?` → **não**, na primeira passagem

Dois casos da matriz deram **passe indevido**, e os dois eram nossos:

- **ISO-58**, a FK do `contact_id` (§7.1) — defeito real do desenho;
- **ISO-46**, a incoerência envelope/coluna no `events_outbox` (§7.2) — defeito
  do harness, que escrevia por `INSERT` em vez de pela função que o §6.1 manda
  usar.

### Passo 2 — `Falha corrigível no COM em menos de 3 dias?` → **sim**

As duas correcções levaram **horas**, não dias, e nenhuma exige infra-estrutura
nova:

- a FK composta não custa uma migração extra, porque a revisão `0003` já criou o
  único `(tenant_id, contact_id)` de que ela precisa;
- emitir pela `evt_emitir` e revogar o `INSERT` ao `kamba_app` é a forma que o
  §6.1 já descrevia.

A árvore manda então **«Corrigir, repetir ISO-\* e AC-1 uma vez»** — e *uma vez*
é uma vez. Foi o que se fez.

### Passo 3 — de volta a `AC-1..AC-7 todos verdes?`

<!-- DECISAO-PASSO3 -->

**Não.** Dos sete bloqueantes: 4 medido(s) e verde(s), 1 vermelho(s), 2 não verificado(s).

- **Vermelho:** `AC-1` ficou vermelho depois da repetição autorizada no passo 2.

- **Não medido:** `AC-5` e `AC-6` ficaram sem medição — que não é verde nem é uma falha.

Os números de cada um:

- `AC-1`: 1 passe(s) indevido(s) em 59 caso(s) medido(s): ISO-15

- `AC-5`: 10 intencoes orfas; reconciliacao em 0.972s; 0 orfaos e 0 divergencias abertas depois. Mas so a metade `platform` da saga foi medida: a falha entre o **Registo** e o espelho precisa do Medusa de pe

- `AC-6`: p99 = 21.682s em 199 amostras (mediana 2.805s, max 21.905s) — **mas com um varredor a 0.2s**, que e escolha do harness e nao o mecanismo do §6.5 (job de 60 s + delayed job por reserva, nenhum implementado). O numero mede o custo de processamento da libertacao, nao a cadencia. A porta recusou libertar a encomenda paga (50 recusa(s) pela consulta final a PAY), que e a propriedade do §6.5 que mais custa se falhar

<!-- /DECISAO-PASSO3 -->

**E aqui a árvore do §4.5 encalha de duas formas distintas, que não se devem
confundir.**

**A primeira: o ISO-15 é um vermelho novo, não uma repetição.** A API *Store* do
Medusa serve a encomenda de um tenant a uma chave publicável de outro (§7.8). Se
se ler a árvore à letra, a única repetição permitida já foi gasta no passo 2 e o
caminho seguinte é a **opção C**. Mas o que o passo 2 corrigiu e repetiu foram
*outros* casos: o ISO-15 só se tornou mensurável quando o Medusa chegou a estar
de pé, o que — por um defeito do próprio harness, descrito em
[`ANALISE-36`](../analises/ANALISE-36-KAM-041-spike-medusa.md) §0 — só aconteceu
depois da repetição. **A letra manda ir para a opção C; a leitura é que a
repetição do passo 2 não consumiu a oportunidade de corrigir um achado que
ainda não existia.** Esta divergência entre a letra e a leitura **não se resolve
aqui**: escreve-se, e devolve-se a quem escreveu o critério.

E há uma razão de substância para não ir para a opção C por causa do ISO-15: **a
correcção não é no Registo, é na exposição.** O [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md)
§1 já diz que «os agentes não falam com o Medusa: falam com a TLS, que chama a
porta `CommerceRegistry`». Se a API *Store* nunca é alcançável por um cliente —
como o AC-2 já exige do admin —, a fuga não tem por onde ser explorada. A
opção C eliminaria o Medusa e com ele a fuga, mas **a opção B com a Store
inalcançável fecha-a igualmente**, e por isso o ISO-15 é um argumento para
estender o AC-2, não para trocar de Registo. Fica como recomendação, e a
decisão é de quem assina.

**A segunda: dois bloqueantes não se conseguiram medir.** A árvore só tem «todos
verdes?» e «falha corrigível?». Um critério que não se mediu não é verde nem é
uma falha corrigível, e **a árvore não tem ramo para ele** — o que é, em si, um
resultado deste spike. Enquanto o AC-5 e o AC-6 não forem medidos, a **D3 não
fecha** sobre eles, qualquer que seja a leitura do parágrafo anterior.

### Passo 4 — `AC-9 ≤ 3 dias?` → **não medido**, só estimado

2 a 3 dias-pessoa, e é uma **estimativa marcada como proposta**, não uma
medição: por isso o AC-9 aparece no §5 como **não verificado** e não como verde.
A base está no AC-9 do §5 — a porta mínima com o filtro imposto em todas as
operações e a RLS por cima saiu nos onze métodos do contrato do §3.2, dentro
deste spike. Calibra-se no KAM-042, que é o ticket que faz o trabalho. Um nó de
decisão respondido por uma estimativa é um nó respondido com menos do que o
critério pede, e diz-se.

### A recomendação

> **Opção B — Medusa v2 puro + `merchant_id` — com um refinamento que a medição
> impõe: a autoridade da reserva fica no esquema `platform`, não no Inventory
> Module do Medusa.**
>
> **E é uma recomendação, não um fecho.** O passo 3 acima diz quais os
> bloqueantes que não se conseguiram medir; enquanto esses não forem medidos, a
> D3 **não fecha** — a evidência existente aponta nesta direcção e não a
> estabelece. Cada um deles diz no §5 o que falta.

Três razões, todas medidas:

1. **O isolamento nunca ia vir do Medusa, e agora sabe-se por evidência em vez
   de por prudência.** A multi-tenancy nativa não existe (negação textual da
   documentação), o *link* entre módulos não tem FK nem filtro, e o *query graph*
   não filtra por si. O que isola é a porta `CommerceRegistry` mais a RLS do
   `platform` — e as duas foram medidas a isolar (§6). A opção C (registo
   próprio) resolveria o mesmo problema construindo mais código: **não compra
   isolamento que a opção B não tenha**, compra independência de um fornecedor.
2. **A reserva não se delega — e isto deixou de ser leitura de código para ser
   um número.** Correram-se os dois caminhos do Medusa sobre o **mesmo**
   `InventoryItem` com `stocked_quantity = 10` e mil tentativas concorrentes de
   reservar 1 unidade:

   | Caminho | Reservas aceitas sobre stock 10 |
   |---|---|
   | `inventoryService.createReservationItems` (camada do módulo) | **102 a 118** |
   | o mesmo, dentro de `locking.execute([inventory_item_id], …)` | **10** |

   Mais de cem reservas sobre dez unidades — **dez vezes o stock** — e
   com o contador `reserved_quantity` a dizer `10`, porque cada *thread* leu 9 e
   escreveu 10. O contador não está só errado: está errado *para o valor
   certo*, que é a assinatura do *lost update*. (Foi por isso que a primeira
   versão deste harness reportou «0 acima do stock» no momento exacto em que
   havia quase cem reservas a mais: lia a vítima em vez da testemunha. Ver
   [`ANALISE-36`](../analises/ANALISE-36-KAM-041-spike-medusa.md) M17.)

   O caminho do *workflow* serializa — e serializa **porque corre num único
   processo**, com o provider de locking *in-memory* que a documentação limita a
   «a single-instance environment». O COM escala para mais do que uma
   instância, pelo que esse 10 não transfere para produção sem um provider
   Redis ou Postgres.

   O §6.4 já punha o `UPDATE ... WHERE quantidade - reservada >= :q` como
   mecanismo principal e deixava «ou *reservation items* do Medusa» como
   alternativa «a validar em AC-3». Está validada: **não serve**. O §10.1 já
   atribuía ao `platform` a autoridade das reservas e da expiração — fica como
   está, e agora com um número atrás.
3. **A licença é administrável.** Os pacotes Enterprise instalam-se sempre, mas
   o que a licença condiciona é **activar** a *flag*, e as duas estão
   `default_val: false`. O controlo é um teste de ficheiros que corre sem
   Docker, sem rede e sem base de dados (`spikes/medusa-d3/ee.py`), e falha com
   código 1 se alguma aparecer ligada — verificado com um canário.

**Porque não a opção C.** O custo de referência do §4.5 é «2–3 semanas de um
engenheiro» (estimativa nossa), contra os 2–3 dias-pessoa do AC-9 para reforçar
a B. A condição que a árvore põe para a C — «AC-9 > 3 dias **e** o custo da C
menor que o de reforçar B» — não se verifica em nenhuma das duas metades.

**Porque não a opção A (Mercur).** Fora do Piloto por decisão já tomada no §4.6,
e o spike não a reabre: não correu a matriz contra o Mercur, e diz isso no §10.

### O que esta recomendação não é

**Não é o fecho da D3 nem a ratificação do ADR-003.** A Carta §4.2 dá a decisão
ao Arquitecto de Plataforma, com assinatura do Responsável de Segurança, e nada
está ratificado até o fundador o dizer. Este documento entrega a evidência e a
recomendação; as duas caixas de assinatura do bloco do ticket ficam **vazias**,
e o §5 diz quais.

---

## 9. Emendas que este documento pede, e as que já fez

Feitas neste PR, porque a *Definition of Done* do KAM-041 as pede
(«ADR-003 e `../tecnica/03` actualizados; itens NÃO VERIFICADOS actualizados»):

| Onde | O que mudou |
|---|---|
| [`../tecnica/00`](../tecnica/00_Arquitectura_Solucao.md) §8, ADR-003 | Resultado do spike e a recomendação (opção B com a autoridade da reserva no `platform`), com as quatro medições que a sustentam. Continua **CONDICIONAL**: falta a ratificação |
| [`../tecnica/00`](../tecnica/00_Arquitectura_Solucao.md) §13.3, D3 | Spike feito; falta assinar e ratificar |
| [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md) §3.3 | Estados do mapeamento conceptual: três passam a CONFIRMADO, com o que foi medido |
| [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md) §3.4 | Três correcções de licença (§7.4, §7.5, e `policies` não é um pacote) |
| [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md) §5.4 | **FK composta** do `contact_id`, com a medição que a justifica (§7.1) |
| [`../tecnica/03`](../tecnica/03_Core_Comercio_Medusa.md) §15 | Tabela de NÃO VERIFICADOS: três resolvidos, dois novos (compensação do *workflow*, telemetria) |
| [`../tecnica/08`](../tecnica/08_Seguranca_Conformidade.md) §3.5 | Linha nova: telemetria do CLI activa por omissão, com o controlo; e o que o spike apurou sobre o admin e a RLS no schema do Medusa |
| [`../tecnica/evidencia/E4`](../tecnica/evidencia/E4_Stack_Licencas.md) §6 | Emenda: a documentação **está** acessível, e os três itens que ficaram NÃO VERIFICADOS por causa dela estão resolvidos |
| [`../../specs/00_KAMBA_Carta.md`](../../specs/00_KAMBA_Carta.md) §4.1 e §4.2 | ADR-003 e D3: spike feito, ratificação pendente |
| [`../dividas-documentais.md`](../dividas-documentais.md) | Linha 133: a lista de nomes Enterprise do AC-7 e do critério de saída do EPIC-04 |
| [`../seguranca/`](../seguranca/) | **Nada.** Neste repositório o STRIDE e os riscos residuais são remissões para `albinoJimy/kamba`, que é privado. O achado do ISO-58 pertence ao RR-01 e o do ISO-15 à célula COM-I do STRIDE, e **os dois ficam por entrar** — têm de ser emendados no repositório privado, onde o texto vive |

**Devolvido a quem escreveu o critério, e não emendado aqui:** a letra do AC-7 e
do critério de saída do EPIC-04 nomeia `policies` (que não é um pacote) e não
nomeia a *feature flag* `rbac_filter_fields`. Mudar a letra de um critério de
aceitação é decisão de quem o escreveu; o verificador do spike cobre as duas
*flags*, pelo que o **controlo** está mais completo do que o critério que o pede.
Fica na linha 26 das dívidas documentais.

**Fora do âmbito, para quem decidir:** o destino e o conteúdo da telemetria do
Medusa interessam ao ADR-008 e à D1, e não se apuraram aqui.

---

## 10. O que fica NÃO VERIFICADO

Com o estado e a razão, porque uma lista de lacunas é o que distingue um spike
de uma apresentação.

| Item | Porque não se mediu | Onde se mede |
|---|---|---|
| **Compensação do *workflow* do Medusa sob falha a meio** | A saga que o AC-5 mediu é a do `platform` (`order_intents` + reconciliação). A compensação do Medusa é outro mecanismo e não foi exercitada | KAM-042, quando o adaptador existir |
| **Reserva atómica com provider de locking Redis/Postgres** | Mediu-se o provider *in-memory*, que é o de omissão. Com um provider distribuído a conclusão do §4 pode mudar — mas acrescenta infra-estrutura ao caminho de venda, e a recomendação não depende disso | KAM-042, se alguém quiser reabrir a delegação da reserva ao Medusa |
| **Reserva atómica com mais do que uma instância do Medusa** | Deduz-se da documentação («only intended for use in a single-instance environment», CONFIRMADO) e não se mediu por execução: exigia duas instâncias no harness | — (a dedução basta para não delegar) |
| **Custo da licença Enterprise do Medusa** | Não há preço público para o que nos interessaria; a página de preços lista RBAC e SSO como exclusivos do *tier* Enterprise sem valor | Pedido comercial, se e quando RBAC/SSO do admin forem necessários |
| **O que a telemetria do Medusa envia, e para onde** | Desligou-se em vez de se analisar. Desligar era a acção certa; analisar é outro trabalho | ADR-008 / D1, antes de produção |
| **Mercur** | Avaliação lateral **opcional** e fora do Piloto (§4.6 do `../tecnica/03`). Não se correu a matriz ISO contra ele | Novo spike, se e quando a D2 abrir o Fluxo B |
| **Preço, catálogo AI, módulo `servicos`** | Não são critérios deste ticket | KAM-043, KAM-047, KAM-049 |
| **A tabela de produção do `orders_mirror`** | O spike mediu o **desenho do §5.4 aplicado por este harness**; a tabela de produção ainda não existe (`db/migrations/versions/` está na revisão `0003`) | KAM-044 e KAM-045 |

---

## 11. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | 2026-10-27 | Emissão inicial: medição dos dez critérios do §4.3, matriz ISO-01..60, e recomendação sobre a D3. | KAM-041 |

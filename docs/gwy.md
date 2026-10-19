# GWY — o webhook da Meta: verificação, assinatura, deduplicação, 200 rápido e fila

| Campo | Valor |
|---|---|
| Documento | `docs/gwy.md` |
| Ticket | KAM-013 — GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila) |
| Estado | Revisão `0008` aplicada; `services/gwy` e o processo de entrada de `services/worker-canal` implementados; *gates* 8 com as *suites* `tests_entrada` e `tests_entrada_carga` activas. As caixas marcadas e as vazias estão nomeadas na secção de verificação do bloco do ticket (`specs/EPIC-02` §KAM-013) |
| Âmbito | O que está **entre a Meta e a fila**, e o que tira da fila e registra. Nada de resolução de tenant (KAM-014), envio (KAM-015), subscrição de campos (KAM-016) ou coexistência (KAM-017) |
| Fontes | `docs/tecnica/01` §5; `docs/tecnica/evidencia/E1` §5; `docs/tecnica/08` §4.5 e §7.3; ADR-001, ADR-009, ADR-010, ADR-018; `specs/02` §3.12 (emenda 1.19) |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. A tese, numa frase

O GWY é o **único** endpoint de webhook da Meta (ADR-001): valida a assinatura
sobre os bytes recebidos, põe o corpo na fila e responde 200 — sem base de
dados, sem cofre e sem `JSON.parse` no caminho. Quem interpreta o corpo é o
*worker* de canal, depois da fila, e é ele que registra cada evento com
deduplicação em dois níveis.

**A Meta re-entrega até sete dias** (`E1` §5, CONFIRMADO), sem ordem garantida e
em concorrência. **As garantias do BullMQ estão `NÃO VERIFICADO`** (`E4` §2.10).
As duas coisas juntas dão a regra que atravessa este desenho: *at-least-once* em
tudo, e todo o consumidor idempotente.

```text
Meta ──POST assinado──▶ GWY ──addLote(jobId=sha256(corpo))──▶ fila ──▶ worker
                         │                                               │
                     200 só depois                              inbound_events
                     503 se a fila cair                   UNIQUE (kind, event_key)
                     401 se a assinatura falhar                         │
                                                        chr │ outbound │ ingestão │ gestão
```

## 2. O `GET` de verificação

CONFIRMADO (`E1` §5): `hub.mode`, `hub.challenge`, `hub.verify_token`; responder
200 com o corpo **igual** ao desafio.

| Situação | Resposta |
|---|---|
| `hub.mode=subscribe` e `verify_token` certo | 200, corpo = `hub.challenge`, byte a byte |
| `verify_token` errado | 403 (código *proposta* do bloco do ticket) |
| Sem `hub.mode`, sem `hub.challenge`, ou outro modo | 403 |

**A resposta não distingue «token errado» de «pedido malformado»**, de propósito:
é um endpoito público e a diferença só interessa a quem está a sondar. A
diferença fica no registo, pelo `outcome` (`verificacao_recusada` contra
`verificacao_malformada`).

A comparação do `verify_token` é em tempo constante (`timingSafeEqual`). O
comprimento compara-se primeiro, e isso revela o comprimento do token — é a
única fuga possível aqui, e é aceitável: o que o atacante não consegue é
descobrir o conteúdo byte a byte pelo tempo.

## 3. O `POST`: a ordem dos passos, e porque é esta

0. **Recusar um corpo grande demais**, antes de o ler. Duas guardas: o
   `content-length` declarado (que é de quem chama e pode mentir, mas quando diz
   «grande» não há razão para alocar) e o tamanho do que chegou de facto (um
   pedido `chunked` não traz `content-length`). Acima de `CORPO_MAXIMO` (1 MiB,
   *proposta*) responde **413** — e não 401, porque não é um problema de
   assinatura e um corpo legítimo grande apareceria como `gwy_sig_fail`,
   mandando procurar no sítio errado.
1. **Ler os bytes.** `c.req.arrayBuffer()`, nunca `text()` nem `json()`.
2. **Verificar a assinatura**, antes de qualquer `parse`. Falha → 401 e
   `gwy_sig_fail`.
3. **`jobId = sha256(corpo)`.**
4. **Decidir o descarte**, só se a fila estiver saturada (§6).
5. **Enfileirar, e só depois responder 200.** Falha → 503.

Nada do corpo é lido, interpretado ou registado antes do passo 2: um corpo não
assinado não é tráfego da Meta.

**O passo 0 nasceu da revisão adversarial.** Sem ele, o `arrayBuffer()` lia o
corpo inteiro antes de a assinatura ser verificada e sem tecto nenhum: qualquer
pessoa, sem segredo, fazia um `POST` de 200 MB e o processo alocava os 200 MB
antes de responder 401 — no único endpoint público da plataforma, com o *proxy*
que o protegeria a ser de outro ticket (KAM-077).

### 3.1 A assinatura

`X-Hub-Signature-256: sha256=<HMAC-SHA256(corpo bruto, App Secret)>` —
CONFIRMADO, fonte primária. O módulo é
`packages/core-ts/src/entrada/assinatura.ts`, e está em `core-ts` e não no `gwy`
porque o mesmo cálculo volta no KAM-056 (*callbacks* do ProxyPay) e no KAM-072
(rotação de chaves).

Quatro propriedades, e cada uma tem o seu teste:

| Propriedade | Porque existe |
|---|---|
| Assina-se sobre `Uint8Array`, nunca sobre texto | Um corpo re-serializado com espaços diferentes tem o mesmo `JSON.parse` e assinatura **diferente**, e tem de ser recusado (critério 2) |
| Aceita `[actual, anterior]` | Durante uma rotação chegam corpos assinados com o segredo antigo, e a repetição dura sete dias. O `anterior` pode ser `null` — nunca houve rotação — e isso **não é erro** |
| `timingSafeEqual` por candidato, com `OR` bit-a-bit | Um `return` dentro do ciclo dizia pelo tempo de resposta *qual* dos dois segredos acertou |
| A forma do cabeçalho valida-se antes da comparação | `timingSafeEqual` **lança** com comprimentos diferentes, e o cabeçalho tem o comprimento que o atacante quiser |

Um anel vazio, nulo ou de segredos vazios **recusa tudo**. Em particular, não
valida um HMAC feito com chave vazia: falha fechado.

### 3.2 O segredo e a profundidade vêm de cache

`Secrets.getRing` vai ao provedor: com o `EnvSecretProvider` é barato e com o
Doppler é um HTTP. Um HTTP por webhook não cabe no alvo de «200 em < 500 ms» com
3× o tráfego de estados mais 1× o de entrada. Por isso `server.ts` mantém duas
caches, refrescadas por laços:

| Cache | Intervalo | O que falha se a releitura falhar |
|---|---|---|
| Anel do App Secret | 60 s | Nada: a cache fica como estava, e o anel aceita o anterior |
| Profundidade da fila | 1 s | A profundidade fica **desconhecida**, e desconhecida não é saturada: não se descarta nada |

Uma rotação demora no máximo 60 s a ser vista, e **não há janela de recusa**
porque o anel aceita o segredo anterior enquanto ele existir.

Em `prod`, um cofre inacessível **aborta o arranque** (`Secrets.arrancar`): um
GWY a responder 401 a tudo é uma avaria silenciosa, e a re-entrega de sete dias
transforma um arranque recusado num atraso recuperável.

## 4. Deduplicação, em dois níveis

| Nível | Chave | O que apanha |
|---|---|---|
| Fila | `jobId = sha256(corpo bruto)` | A re-entrega **byte-a-byte** idêntica, que é a forma comum da repetição da Meta |
| Base | `UNIQUE (kind, event_key)` | A mesma mensagem embrulhada em **dois corpos diferentes** |

`event_key` é o `wamid` para `message` e `echo`, `wamid:estado` para `statuses`
(a letra do critério 4), e o **resumo canónico** `k_` + 32 hexadecimais para o
resto. O resumo existe porque um `account_update` não traz identificador nenhum:
sem chave determinística, cada re-entrega criava uma linha. É sobre
`(waba_id, campo, valor)` com as **chaves ordenadas** — `JSON.stringify` não
serve, porque a ordem das chaves é a de inserção.

### 4.1 Registar e encaminhar não são atómicos

O encaminhamento sai do processo (o CHR é KAM-014) e o registo é uma escrita
local: não há transacção que cubra os dois. Um `kill -9` entre eles deixa um
evento registado e não tratado, e na entrega seguinte o `ON CONFLICT` não
devolve linha — pareceria um duplicado.

É por isso que `inbound_events.processado_at` existe, e é a **única** coluna que
`kamba_app` pode actualizar: o caminho do duplicado pergunta à base se aquele
evento está por encaminhar, e só conclui «duplicado» quando ele já tem
`processado_at`. A consequência é que um encaminhamento pode acontecer mais de
uma vez — que já era verdade pelas garantias do BullMQ.

## 5. Encaminhamento por `kind` (critério 8)

| `kind` | Destino | Nota |
|---|---|---|
| `message`, `echo` | `chr` | KAM-014 |
| `statuses` | `outbound` | **Nunca ao AGR** (`docs/tecnica/01` §5.4) |
| `history`, `smb_app_state_sync` | `ingestao` | Só ingestão; **nunca gera resposta** (KAM-017) |
| `account_update`, `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update` | `gestao_de_canal` | KAM-016, KAM-021 |
| `desconhecido`, `invalido` | `quarentena` | Não são campos da Meta |

O mapa é **total** (`Record<Kind, Destino>`): um `kind` novo sem destino é um
erro de compilação, e não um evento encaminhado para onde calhar.

**Os tratadores não existem neste ticket**, e isso é o âmbito: o
`EncaminhadorQueSoRegista` conta por destino e mais nada. O que o KAM-013
entrega é a decisão de **para onde**, e a prova de que ela é a do critério 8 —
incluindo as duas propriedades negativas que importam.

### 5.1 Os onze campos, e os catorze `kind`

Os campos de webhook são **onze** (critério do KAM-016) e os `kind` são
**catorze**. A diferença tem duas partes: o campo `messages` dá dois (`messages`
e `statuses` chegam no mesmo `value` e têm destinos opostos), e a quarentena tem
dois valores próprios que não são campos da Meta.

Os catorze repartem-se por **duas colunas com `CHECK` diferentes**: doze em
`inbound_events.kind` e dois em `unrouted_events.kind`. Com catorze nas duas,
uma `message` podia ser escrita na quarentena e um `invalido` no registo de
entrada.

### 5.2 Uma coisa que fica `NÃO VERIFICADO`

**O nome do array dentro do campo `smb_message_echoes`.** O `E1` §5 não o diz e
nenhuma página primária foi lida nesta execução. O código reconhece
`message_echoes` como *proposta* e, se estiver errado, o *echo* cai na regra
geral — um evento por `change`, com o `kind` correcto e uma chave
determinística. Fica mais grosso e continua correcto; fixá-lo é KAM-017.

## 6. Erros e descarte

| Situação | Resposta | Acção |
|---|---|---|
| Assinatura ausente ou inválida | 401 | `gwy_sig_fail`; alerta acima de 5/min (sondagem) |
| Fila indisponível | 503 | A Meta repete até sete dias; alerta crítico |
| JSON inválido com assinatura válida | **200** | Quarentena `unrouted_events` com `json_invalido`; **nunca 5xx**, para não começar sete dias de re-entregas |
| Campo de webhook desconhecido | 200 | Quarentena com `campo_desconhecido` |
| Fila acima de 10 000 *jobs* | 200 | Descarte de corpos **só de estados sem preço**; `gwy_shed_total` |

### 6.1 O descarte, e porque é conservador

O critério 7 diz «são descartados estados não facturáveis, nunca `messages`». A
regra implementada é mais estreita do que isso, e por duas razões que se somam:

- **O campo que diz se um estado é facturável está `NÃO VERIFICADO`.** O `E1` §5
  não documenta a forma do `pricing` dentro de um `statuses[]`. Por isso a regra
  **não** é «`pricing.billable === false`» — seria desenho sobre um campo que
  ninguém confirmou. É: **um estado que traga `pricing`, de qualquer forma, não
  se descarta.** O custo por mensagem é KAM-015 e o *free tier* é KAM-023.
- **Uma mensagem nunca se descarta.** Basta um `messages[]` com um item em
  qualquer `change` de qualquer `entry` para o corpo inteiro ser enfileirado.
  Não se parte o corpo: o *job* é o corpo, e um corpo meio descartado é um
  `jobId` que já não corresponde ao que lá está. E o `field` tem de ser
  `messages` — sem essa verificação, um `account_update` cujo `value` trouxesse
  um array chamado `statuses` era descartado em silêncio (defeito apanhado pelo
  teste `é falso para tudo o que não seja isso`).

Um corpo que não se consegue interpretar **não se descarta**: vai à fila e, se
for lixo, à quarentena.

## 7. As tabelas

```text
platform.inbound_events (id, kind, event_key, waba_id, phone_number_id,
                         recebido_at, processado_at)
                        UNIQUE (kind, event_key)

platform.unrouted_events (id, kind, event_key, waba_id, phone_number_id,
                          motivo, payload, recebido_at, processado_at)
                         UNIQUE (kind, event_key)
```

**Nenhuma das duas tem `tenant_id`**, e isso é desenho: o tenant só nasce no CHR
(KAM-014), que corre depois desta escrita. Como o teste de catálogo X-05 do
*gate* 6 descobre as tabelas a isolar **pela coluna `tenant_id`**, nenhuma
política é exigida nem dispensada, e **não há entrada em
`ci/rls_exceptions.yaml`**.

### 7.1 O que cada uma guarda, e o que não guarda

`inbound_events` **não guarda o corpo**. O *payload* de conversa vive no *job* e,
depois, nos *checkpoints* do AGR.

`unrouted_events` **guarda o corpo**, em base64, e é a única coluna do schema
que guarda corpo de conversa. Três consequências, as três deliberadas:

1. **É base64 e não `jsonb`.** O caso principal da quarentena é um corpo que não
   é JSON; e pode não ser UTF-8 válido, pelo que também não entra num `text` em
   claro.
2. **Tem tecto** (256 KiB de base64), no `CHECK` **e** no código. No `CHECK`
   para que nenhuma outra via de escrita o ignore; no código para que um corpo
   grande entre com `payload` nulo em vez de a inserção falhar e o *job* repetir
   durante sete dias.
3. **`kamba_app` escreve e não lê.** O mesmo desenho do `audit_log`, aqui por
   privacidade. Lê quem opera, que é `kamba_batch`.

**E há dois tectos por corpo, os dois da revisão adversarial.** O corpo
guarda-se **uma vez por corpo** e não uma vez por evento — sem isso, 1 000
`changes` de um campo desconhecido davam 1 000 linhas com uma cópia inteira do
corpo, 256 MB de um pedido. E um corpo que gere mais de
`EVENTOS_MAXIMOS_POR_CORPO` (1 000, *proposta*) vai **inteiro** a uma linha de
quarentena: sem o tecto, um corpo com 100 000 `statuses` fazia 100 000 `INSERT`
sequenciais num só *job*, com `concurrency: 1`, e a partição ficava bloqueada
todo esse tempo enquanto a Meta continuava a entregar.

A retenção de **7 dias** do `payload` é *proposta* do critério 6, e esta revisão
**não a impõe**: não cria função de limpeza nem agendador. O agendador nasce com
KAM-071, pela mesma decisão que a `0004` tomou para as partições mensais.

### 7.2 Privilégios

| Tabela | `kamba_app` | `kamba_batch` | os outros quatro |
|---|---|---|---|
| `inbound_events` | `SELECT`, `INSERT`; `UPDATE` só em `processado_at` | os quatro de dados | nada |
| `unrouted_events` | `INSERT` | os quatro de dados | nada |

O `SELECT` de `inbound_events` é preciso e não é generoso: o
`INSERT … ON CONFLICT DO NOTHING RETURNING id` é o que distingue uma linha nova
de um duplicado, e o PostgreSQL exige `SELECT` na coluna devolvida. A objecção
que levou o `events_dlq` (KAM-006) a não ter `SELECT` — «um `id` sequencial mede
o volume do vizinho» — não se aplica: aqui o `id` é `gen_random_uuid()` e a
tabela não tem dado de tenant nenhum.

Em `unrouted_events`, `kamba_app` tem `INSERT` de tabela **e `SELECT` em duas
colunas** — `kind` e `event_key`. Isso não é uma concessão: são os elementos de
inferência do `ON CONFLICT`, e o PostgreSQL trata-os como leitura. Sem eles a
inserção falha com `42501`, e foi assim que o defeito apareceu — a quarentena
ficava a zero e o *worker* não registava nada, porque um *job* falhado não
deixava linha nenhuma (§8.1). É a mesma lição que a revisão `0005` já escrevera
para o `ON CONFLICT (consumer, event_id)` do `events_dlq`.

**O que essas duas colunas dão de lambuja, dito e não escondido:** com
privilégio em qualquer coluna, o PostgreSQL aceita `count(*)`. `kamba_app` passa
a poder contar as linhas da quarentena — e isso é aceitável aqui e não era no
`events_dlq`, porque esta tabela não tem `tenant_id`: a contagem é da plataforma
inteira e diz quantos corpos não encaixaram, não de quem são. O `payload`, o
`motivo` e os dois identificadores da Meta continuam fechados.

## 8. Logs e métricas

O critério 9 fixa oito campos: `ts, level, svc, msg_id, wa_type, latency_ms,
outcome, error_code`. É um **subconjunto** da *allowlist* de doze
(`docs/tecnica/08` §7.3), e nenhum dos dois processos usa os outros quatro.

Duas regras que o código impõe e não pede:

- **O `wamid` nunca vai em claro.** Leva o número do interlocutor codificado em
  base64 (INDÍCIO, `docs/logs.md` §2.1), e a *allowlist* recusa-o. O que vai é
  `idOpaco(event_key)` — `m_` mais 32 hexadecimais.
- **O `wa_type` vem de uma lista fechada.** O valor vem de dentro do corpo, isto
  é, de fora; um `type` inventado com a forma certa entrava na linha tal e qual.
  O que não se reconhece sai como `outro`.

| Métrica | Tipo | Nota |
|---|---|---|
| `gwy_requests_total` | counter | Pedidos recebidos |
| `gwy_sig_fail` | counter | Recusados por assinatura |
| `gwy_shed_total` | counter | **Quinta, e o DoD nomeia quatro**: descartar sem contar é descartar em silêncio |
| `gwy_enqueue_ms` | gauge | **Último** valor, não percentil (ver abaixo) |
| `inbound_queue_depth` | gauge | `-1` quando não se conseguiu ler |

Nenhuma leva etiquetas: não há por onde dividi-las que não seja por
identificador, e esses não entram em etiqueta nenhuma
(`docs/seguranca/ameacas_stride.md`, OBS-I).

**O que `gwy_enqueue_ms` não dá: percentis.** O formato de exposição do
Prometheus tem histogramas e esta biblioteca não os implementa (ADR-018 manda
observabilidade leve no Piloto). O p99 do critério 7 mede-se na prova de carga,
que é onde o número tem significado; a agregação contínua é KAM-080 e o
dimensionamento é KAM-084. Fica dito para ninguém ler este *gauge* como um p99.

### 8.1 Um *job* falhado tem de deixar linha

O BullMQ **não escreve nada** quando ninguém ouve o acontecimento `failed`, e o
*worker* de entrada não ouvia: um `permission denied` na inserção da quarentena
parecia «o corpo nunca chegou». Hoje há um ouvinte de `failed` **e** de `error`
(o segundo para o que não tem *job* associado — a ligação caiu, o Lua do BullMQ
recusou), e sai o código e a classe do erro, nunca a mensagem: um erro de `pg`
pode trazer a instrução com os parâmetros, e os parâmetros deste caminho são o
corpo do webhook.

E o *worker* registra uma estratégia de recuo. Sem ela, um *job* que falhe
rebenta com «Unknown backoff strategy custom» e **nunca é retentado**: o
`addLote` põe `backoff: { type: "custom" }` em todos os *jobs*, que é a forma de
o BullMQ passar a decisão do atraso ao *worker*. O sintoma era pior do que «não
recua» — o tratamento da falha rebentava e o *job* ficava em `failed` sem passar
pela quarentena. A escada é a do consumidor (`docs/tecnica/06` §6.4), por ser a
única do repositório e por o que se retenta aqui ser da mesma natureza: uma
falha transitória da base.

### 8.2 O `/metrics` vive noutra porta

**Esteve na porta do webhook, e isso era um defeito.** O webhook é por definição
alcançável de fora (ADR-001): com o `/metrics` ao lado, qualquer pessoa que
chegasse ao GWY lia `inbound_queue_depth` — o atraso da plataforma em tempo
real —, `gwy_requests_total` e `gwy_sig_fail`. Com a profundidade visível, quem
quisesse provocar o descarte do §6 sabia exactamente quando a fila passara os
10 000.

Hoje são dois servidores: a porta pública leva **só** o `/wa/webhook`, e o
`/healthz` e o `/metrics` vivem na porta interna (3010, configurável por
`GWY_METRICS_PORT`), como nos outros processos do conjunto (3011, 3012, 3013).
Não é defesa suficiente por si — a porta interna também é uma porta —, mas é a
diferença entre «exposto a quem alcança a Internet» e «exposto a quem alcança a
rede interna», e é a que está nas mãos deste ticket. Fechar a rede é KAM-077.

**E o `docker-compose.dev.yml` não precisou de mudar**, o que é a confirmação de
que a separação serve: ele publica `127.0.0.1:${GWY_PORT:-3000}:3000` e mais
nada, pelo que a porta das métricas deixou de ser alcançável de fora do
contentor sem uma linha de configuração. Quem a quiser raspar publica-a de
propósito — e não há colector (ADR-018: observabilidade leve no Piloto; o
colector é KAM-080).

O `/healthz` **fica na porta pública**, e isso é deliberado: é o contrato do
KAM-001 (`packages/contracts/schemas/healthz.response.v1.json`), o `make smoke`
verifica-o em `gwy=3000` e o `healthcheck` do compose chama-o em `:3000`. É a
sonda de vivacidade do serviço, não observabilidade — não diz nada sobre o
estado da fila.

### 8.3 O *worker* tem métricas próprias

Serviu as cinco do GWY, e não incrementa nenhuma: saíam `gwy_sig_fail 0` e
`inbound_queue_depth -1` permanentes — o segundo ao lado do valor real do GWY,
onde um alerta sobre a profundidade o lê e não dispara — e do trabalho que ele
faz de verdade não saía nada. Tem três, com etiquetas de lista fechada:

| Métrica | Etiqueta | Nota |
|---|---|---|
| `inbound_events_total` | `desfecho` ∈ {`registado`, `duplicado`, `recuperado`} | `recuperado` é o evento que estava sem `processado_at` |
| `inbound_unrouted_total` | `motivo` (os quatro do §3.12) | Um `json_invalido` aqui é um corpo que não encaixou |
| `inbound_job_failed_total` | — | *Jobs* que falharam. **Nunca** por conteúdo do corpo: isso vai à quarentena |

Os nomes não estão no DoD — o DoD nomeia os do GWY — e entram como *proposta*,
pela mesma razão do `gwy_shed_total`: um processo que escreve na base sem uma
métrica do que escreveu não tem observabilidade nenhuma.

O `/metrics` do `gwy` **passou a existir com este ticket** — até aqui o teste da
sonda afirmava que não respondia 200, e foi alterado com a rota. Métricas que
nada expõe não são observabilidade.

## 9. O que se prova, e onde

| Critério | Onde se mede |
|---|---|
| 1 — `GET` de verificação | `services/gwy/tests/webhook.test.ts`; e por HTTP real em `db/tests_entrada/` |
| 2 — assinatura sobre os bytes, corpo re-serializado | `packages/core-ts/tests/entrada.assinatura.test.ts`; e com assinatura calculada em **Python** em `db/tests_entrada/` |
| 3 — anel `[actual, anterior]`, terceiro segredo | idem |
| 4 — dois níveis de deduplicação | `entrada.registo.test.ts` (decisão) e `db/tests_entrada/` (fila e índice reais) |
| 5 — 200 só depois de enfileirar; 503 com a fila em baixo | `webhook.test.ts` (ordem, com um `addLote` que só resolve quando o teste manda) e `db/tests_entrada/` (contentor da fila parado) |
| 6 — JSON inválido: 200 e quarentena | `entrada.registo.test.ts` e `db/tests_entrada/` |
| 7 — carga e descarte | `db/tests_entrada_carga/` (200 req/s × 60 s) e `webhook.test.ts` (as regras do descarte) |
| 8 — encaminhamento por `kind` | `entrada.explosao.test.ts`, `entrada.registo.test.ts`, `services/worker-canal/tests/entrada.test.ts` e `db/tests_entrada/` |
| 9 — logs | `webhook.test.ts` (1 000 pedidos com canários), `db/tests_entrada/` (os dois processos) e `make log-lint` |

**Os domínios comparam-se com três fontes**: o `CHECK` que o PostgreSQL tem, o
dicionário exportado (`canon/dicionario.yaml`) e a lista do módulo TypeScript.
Duas fontes a concordar é uma cópia; três é um contrato.

## 10. Afirmações e o seu estado

| Afirmação | Estado | Fonte |
|---|---|---|
| HTTPS com certificado válido; `GET` de verificação com os três parâmetros; `POST` assinado com HMAC-SHA256 do corpo bruto | **CONFIRMADO** | `E1` §5, `DOC/webhooks/create-webhook-endpoint`, Jun 17, 2026 |
| Re-entrega até 7 dias com *backoff* exponencial; sem ordem; entrega concorrente; 3× estados + 1× entrada; mediana ≤ 250 ms, < 1% > 1 s | **CONFIRMADO** | `E1` §5, `DOC/throughput`, Jun 17, 2026 |
| *Timeout* exacto do webhook | **NÃO VERIFICADO** | `E1` §5 (L2). O alvo interno é 200 em < 500 ms |
| Garantias de entrega do BullMQ | **NÃO VERIFICADO** | `E4` §2.10. Todos os consumidores são idempotentes |
| Nome do array dentro de `smb_message_echoes` | **NÃO VERIFICADO** | §5.2. *Proposta*: `message_echoes`; fixa-se em KAM-017 |
| Forma do `pricing` dentro de um `statuses[]` | **NÃO VERIFICADO** | §6.1. O descarte é conservador por causa disto |
| Tecto da fila para descarte (10 000), tecto do `payload` (256 KiB), retenção da quarentena (7 dias), intervalos das caches (60 s e 1 s) | *proposta* | Calibram-se em KAM-084 (carga) e KAM-071 (retenção) |

## 11. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial com o KAM-013: o webhook, o anel de segredos, a deduplicação em dois níveis, o encaminhamento por `kind`, a quarentena e a revisão `0008`. | Equipa KAMBÁ |

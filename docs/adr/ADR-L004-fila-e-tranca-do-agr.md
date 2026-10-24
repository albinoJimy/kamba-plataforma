# ADR-L004 — Quem tira o *job* da fila do AGR, e o que serializa um turno

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-24 |
| Ticket | KAM-025 — AGR: serviço, workers assíncronos, lock por conversa e API interna |
| Âmbito | Local (ver [`README.md`](README.md)): duas escolhas de implementação que o bloco do KAM-025 manda decidir e registar — (1) quem consome a fila `agr-inbound`, e (2) que mecanismo serializa um turno por conversa. Não decide o grafo (KAM-031), o checkpointer (KAM-026), o registo de verticais (KAM-027) nem a ToolLayer (KAM-028) |
| Decisores | Executor do KAM-025, a 2026-10-24. Ratificação do Arquitecto de Plataforma pendente de esse papel existir |
| ADRs canónicos aplicáveis | ADR-002 (LangGraph só como biblioteca MIT), ADR-009 (idempotência), ADR-010 (telefone nunca é chave), ADR-006 (PostgreSQL 18) |
| Documentos aplicáveis | [`../tecnica/02_Agent_Runtime_Verticais.md`](../tecnica/02_Agent_Runtime_Verticais.md) §4.2 regra 4, §11 regra 3, §12, §15.2; [`../tecnica/evidencia/E4_Stack_Licencas.md`](../tecnica/evidencia/E4_Stack_Licencas.md) §2.10; [`../../specs/02_Dicionario_de_Dados_Canonico.md`](../../specs/02_Dicionario_de_Dados_Canonico.md) §3.13 e §3.24 |
| Substitui | — |

## Contexto

O bloco do KAM-025 deixa duas escolhas abertas por escrito, nos *Detalhes
Técnicos* e no bloco de *handoff* («Decide e regista o mecanismo de lock
(sessão vs transacção) e o consumidor da fila»). Nenhuma das duas tem resposta
no canon: o `../tecnica/02` §15.2 diz «workers stateless atrás do BullMQ» sem
dizer em que língua, e o §12 oferece `pg_advisory_xact_lock(hash(thread_id))`
**ou** «fila por chave» sem escolher.

As duas escolhas estão no mesmo ADR porque a segunda depende da primeira: o
tempo que um *job* fica aberto é o tempo que a tranca fica tomada, e é o mesmo
número que configura o `lockDuration` do BullMQ.

---

## Decisão 1 — a fila consome-se em TypeScript, com um *shim* que chama `/internal/turn`

### As duas opções que o ticket nomeia

| Opção | O que é | O que custa |
|---|---|---|
| **A — consumidor Python do BullMQ** | `bullmq` para Python (3.3.1, `E4` §2.10) dentro do processo AGR; o *job* nunca sai do processo que corre o turno | A compatibilidade de protocolo entre o `bullmq` **Python 3.3.1** e o `bullmq` **TypeScript 6.3.11** que o CHR usa é **NÃO VERIFICADA**. São implementações irmãs no mesmo repositório, com **versões maiores diferentes**, e o que define a interoperabilidade é a disposição das chaves no Redis e os *scripts* Lua, não a API. Uma dependência nova no fecho do AGR, com entrada própria em `../../ci/supply-chain/licencas.yaml` |
| **B — *shim* TS fino que chama `/internal/turn`** | Um `Worker` do BullMQ em TypeScript, da mesma versão e da mesma biblioteca que o CHR usa para publicar, que faz `POST /internal/turn` ao AGR e espera pela resposta | Um salto HTTP por turno, na rede interna. Um processo a mais a operar. O `lockDuration` do *job* passa a ter de cobrir o turno inteiro |

### Escolhe-se **B**, e a razão não é a licença nem o gosto

**O mecanismo que B usa já tem de existir.** O critério 1 deste ticket exige
`POST /internal/turn`, e o §11 regra 3 do `../tecnica/02` exige
`POST /internal/resume` para a retoma do *handoff* — que, lá está escrito,
«corre sob o *lock* da conversa». Quer dizer: **o AGR tem de saber correr um
turno a partir de um pedido HTTP, decidido e autenticado, de qualquer forma.**
A opção A acrescenta um segundo caminho de entrada, com uma dependência nova,
para fazer o que o primeiro já faz.

**E a opção A assenta num facto que não medimos.** O `E4` §2.10 diz, do lado
das garantias do próprio BullMQ, «não li a documentação nesta sessão: NÃO
VERIFICADO»; sobre a interoperabilidade entre as implementações irmãs não diz
nada — nem a afirma, nem a nega. Escolher A era pôr o caminho de entrada de
todas as conversas do Piloto em cima de uma suposição de protocolo que nenhum
documento deste conjunto sustenta. A regra da casa é clara: sem evidência, é
desconhecido, e um desconhecido não vai para o caminho crítico quando há uma
opção que o não precisa.

**O salto HTTP é barato contra o orçamento que existe.** O orçamento de
latência do §15.1 dá 0,2–0,4 s a «GWY → fila → worker» e 3–7 s ao turno
inteiro. Um `POST` na rede interna do *compose* entra dentro da primeira
parcela; não há aqui uma escolha entre correcto e rápido.

### O que B obriga, e fica escrito porque é a parte que engana

1. **O *shim* espera pela resposta.** Não responde 202 e segue: o critério 4
   exige que um turno interrompido a meio seja **retomado**, e um *job* que
   completa antes de o turno correr perde a corrente *at-least-once* que torna
   isso possível. O *job* fica aberto durante o turno, de propósito.
2. **`lockDuration` tem de cobrir o turno inteiro mais a espera na admissão.**
   É o número que decide se um *job* é declarado `stalled` com o *worker* vivo.
   O valor é a constante `TRANCA_DO_JOB_MS` de
   `packages/core-ts/src/agr/contrato.ts` (*proposta*: 120 000 ms — quatro vezes
   a espera máxima do `fetch`) e calibra-se em KAM-084, com o perfil de carga
   real. **Não é configurável por ambiente**, e uma versão anterior deste ADR
   nomeava uma variável `AGR_TRANCA_DO_JOB_MS` que nunca existiu em código nem
   no dicionário — achado da revisão adversarial. Um `lockDuration` curto não
   perde o *job*: duplica-o, e é por isso que o ponto seguinte não é opcional.
3. **O AGR é idempotente por `turn_id`, e não confia no *shim*.** O `turn_id` é
   o `wamid` (§3.24), e o envio ao Outbound leva
   `idempotency_key = turn_id:seq` (critério 4). Isto vale para A e para B: as
   garantias do BullMQ são NÃO VERIFICADO em qualquer das duas, e o *handoff*
   do LangGraph exige-o de qualquer forma (`../tecnica/02` §11).
4. **A contrapressão responde, não bloqueia para sempre.** Cheio o tecto do
   *tenant*, o AGR responde `503` com `Retry-After`, o *shim* lança, e o BullMQ
   devolve o *job* à fila com atraso. **A última parte exigiu uma correcção no
   produtor:** o `attempts` é opção do *job* e não do *worker*, e o `fila.add`
   do `chr/fila.ts` não o punha — sem ele o BullMQ dá **uma** tentativa e manda
   o *job* para `failed`, pelo que esta frase era falsa e, com `grafos` ainda
   por registar, *todas* as mensagens morriam à primeira. Achado da revisão
   adversarial. Uma espera indefinida dentro do pedido HTTP transformava
   o `lockDuration` no mecanismo de contrapressão, que é o sítio errado para
   ele.

### O que faria rever esta decisão

Uma medição — não uma leitura — de que o `bullmq` Python 3.3.1 lê e escreve as
mesmas chaves que o `bullmq` TypeScript 6.3.11, incluindo a retoma de um *job*
`stalled` publicado pelo outro lado. Com isso medido e registado no `E4`, a
opção A deixa de ter o custo que a afasta hoje, e passa a valer o salto HTTP
que poupa. Enquanto isso não existir, esta decisão mantém-se.

---

## Decisão 2 — a tranca é um `pg_advisory_lock` de **sessão**, numa ligação dedicada

### As três opções

| Opção | O que é | O que custa |
|---|---|---|
| **A — `pg_advisory_xact_lock`** | Toma-se dentro de uma transacção; larga no `COMMIT` | A transacção fica aberta durante as chamadas ao LLM — **segundos** (§15.1 dá 1,5–3,5 s só ao `compose`). Prende uma ligação do *pool* e segura o horizonte do `autovacuum` todo esse tempo. É o problema que o próprio bloco do ticket nomeia |
| **B — `pg_advisory_lock` de sessão, em ligação dedicada** | Toma-se fora de transacção, numa ligação que só serve para trancar; larga-se com `pg_advisory_unlock` ou quando a ligação morre | **Uma** ligação dedicada por **processo** (uma versão anterior deste ADR escrevia «por *worker*», e o código tem uma por processo — achado da revisão adversarial), e com ela a obrigação de a espera não ser exclusiva: ver «O que B obriga», ponto 1. **Não pode passar por um *pooler* em modo transacção**: ali a ligação é devolvida entre instruções e a tranca ficava invisível a quem a tomou e presa para quem vier a seguir |
| **C — fila por chave** | Uma fila do BullMQ por `thread_id`, com concorrência 1 | Serializa dentro de um processo, não entre processos: duas réplicas do AGR com a mesma chave voltam a sobrepor-se. Fechá-lo pedia um *lock* distribuído em Redis — que é o mesmo problema outra vez, noutra base, sem a propriedade do ponto seguinte |

### Escolhe-se **B**, e o que decide é o critério 4

**A tranca larga-se quando a ligação morre, e é isso que o SIGKILL precisa.**
O critério 4 mata um *worker* com SIGKILL a meio de um turno e exige que outro
retome. Com um `pg_advisory_lock` de sessão, o processo morto leva a ligação
com ele, o PostgreSQL larga a tranca sem ninguém lhe pedir, e o *worker*
seguinte toma-a. Não há temporizador a calibrar, não há tranca órfã a limpar à
mão, e não há o caso — que um *lock* em Redis com TTL tem sempre — de a tranca
expirar com o dono vivo.

A opção A tem a mesma propriedade (a transacção aborta com a ligação), e é por
isso que a escolha entre A e B não é sobre correcção: é sobre o que custa
manter uma transacção aberta durante uma chamada a um modelo. O §12 do
`../tecnica/02` oferece as duas; o bloco deste ticket diz, do `xact`, que
«mantém uma transacção aberta durante chamadas ao LLM (segundos)», e nomeia a
de sessão como *proposta*. Confirma-se a *proposta*.

### A chave, e porque é esta

```sql
SELECT pg_try_advisory_lock(hashtextextended($1::text, 0))   -- $1 = thread_id
```

**`pg_try_advisory_lock` e não `pg_advisory_lock`**, e esta linha é uma
correcção. Ver «O que B obriga», ponto 1.

- **`hashtextextended(texto, 0)` e não `hashtext`**, pela razão que o
  `SQL_TRANCAR_CONVERSA` do KAM-018 já escreveu: o primeiro devolve `bigint`,
  que é a largura que `pg_advisory_lock(bigint)` aceita. A semente `0` é fixa —
  uma semente que variasse dava chaves diferentes para a mesma conversa em
  processos diferentes, que é o mesmo que não ter tranca.
- **A chave é o `thread_id` inteiro**, que já é `{tenant_id}:{contact_id}`
  (§3.1) e já traz o separador que impede a colisão entre pares cuja
  concatenação coincida. Não se concatena nada aqui: concatenar outra vez era
  construir uma segunda chave para a mesma coisa.
- **É a mesma granularidade do *lock* do KAM-018** — por `(tenant_id,
  contact_id)`, não por conversa — e isso é deliberado: o `thread_id` do
  LangGraph é por contacto (§12, «`thread_id` = `f"{tenant_id}:{contact_id}"`»),
  pelo que uma tranca por conversa deixava dois canais do mesmo contacto a
  correr dois turnos sobre o **mesmo** *thread*.

  **E é por isso que a fila do executor tem outra chave.** A fila por
  `thread_id` juntava num lote mensagens de **duas conversas** do mesmo
  contacto, e a decisão de uma valia para a outra — a invariante do §11 regra 4
  violada e uma mensagem perdida (achado da revisão adversarial). A fila é por
  `(thread_id, conversation_id)`; a tranca continua por `thread_id`. As duas
  conversas de um contacto **serializam** (pela tranca) e **nunca se misturam**
  (pela fila). **Mas não é o mesmo espaço de
  chaves**: o KAM-018 tranca `hashtextextended(tenant_id || ':' || contact_id)`
  e esta tranca `hashtextextended(thread_id)`, e os dois textos são iguais —
  logo as chaves **colidem de propósito**, e uma transição de modo em curso
  trava a entrada de um turno. É a propriedade que o critério 6 quer, e está
  medida na suite.

### O que B obriga, e também engana

1. **A espera pela tranca não pode ser exclusiva, e a primeira versão deste
   ticket errou aqui.** Há **uma** ligação dedicada por processo, usada por uma
   `thread` de cada vez (o driver é síncrono). Com `pg_advisory_lock`, que
   **bloqueia no servidor**, essa espera prendia a `thread` e, com ela, o
   `asyncio.Lock` da ligação: uma conversa à espera de uma chave parava o
   processo inteiro, e as conversas que **acabaram** não conseguiam
   `pg_advisory_unlock`, porque precisam da mesma ligação. Bloqueio de cabeça de
   fila a atravessar *tenants* — exactamente o que o critério 5 proíbe —, e sem
   erro nenhum: os pedidos ficavam pendurados até o `fetch` do *shim* cortar aos
   30 s.

   Agrava-o o facto de a chave colidir de propósito com a do
   `pg_advisory_xact_lock` dos modos (KAM-018), que o `PreSendGuard` toma **em
   cada envio do bot**: não era preciso um segundo AGR para a espera acontecer.

   A forma é `pg_try_advisory_lock` num ciclo, com recuo exponencial e tecto: a
   tentativa toma o `asyncio.Lock`, faz **uma** instrução e larga-o; a espera é
   fora dele. **A ordem de chegada mantém-se** porque dentro do processo só uma
   corrotina por conversa chega à tranca — quem serializa é o dreno de
   `turno.py`. Achado da revisão adversarial; medido em
   `db/tests_agr/test_repeticao.py::TestDoisExecutoresNaMesmaConversa`, com uma
   mutação que repõe o defeito.

2. **A ligação da tranca não é a ligação das leituras.** Quem lê
   `conversations.mode` e `handoffs.status` usa a ligação normal, com contexto
   de RLS; a da tranca não lê tabela nenhuma e não leva contexto. Uma só
   ligação para as duas coisas obrigava-a a ficar fora do *pool*, e não há
   razão para isso.
3. **`pg_advisory_unlock` tem de correr mesmo em erro**, e corre: é um
   `finally`. Se falhar, a tranca fica até a ligação morrer — o que é o
   comportamento certo e não uma fuga, porque o processo que a tomou já não
   está em condições de a largar.
4. **Nunca atrás de um *pooler* em modo transacção.** Fica escrito em
   `../agr.md` e na *docstring* de `trancas.py`, porque é o único modo de falha
   desta escolha que não dá erro nenhum: dá exclusão mútua que não exclui.
5. **Um turno em curso atrasa uma transição de modo, e isso é o desenho.** Como
   as chaves colidem, o `onOptOut` e o `comando_dono` do KAM-018 esperam até o
   turno acabar — no pior caso, o tecto de um turno. É o que se quer: um modo
   que mudasse a meio de um turno deixava o turno a decidir com um estado que
   já não é verdade. O que isto **não** pode ser é uma espera sem fim, e não é:
   a tranca larga no fim do turno, no `pg_advisory_unlock`, ou com a ligação.

---

## Consequências

- O AGR não ganha dependência nenhuma nova de Python para a fila. O fecho de
  `services/agr/requirements/runtime.in` cresce no `pg8000` — o driver que o
  `db/requirements/migrations.in` já escolheu e justificou (BSD-3-Clause,
  Python puro, sem *wheels* por plataforma) — e em mais nada.
- O `services/worker-canal` passa a hospedar um terceiro consumidor, ao lado da
  entrada de canal e do publicador de eventos. É o sítio onde os `Worker` do
  BullMQ desta casa já vivem.
- A `agr-inbound` continua a ser publicada e consumida pela **mesma** versão da
  mesma biblioteca, o que remove uma classe de defeito inteira em vez de a
  medir.
- O `chr/fila.ts` ganha `attempts` e `backoff` no `fila.add`. **Não é um extra
  desta decisão: era uma lacuna que a tornava inoperante.** O `attempts` é opção
  do ***job*** e não do *worker*, e sem ele o BullMQ dá uma tentativa e manda o
  *job* para `failed` — isto é, nada do que este ADR diz sobre «o *job* volta à
  fila» acontecia. Achado da revisão adversarial.
- O `lockDuration` do *job* passa a ser um número operacional com consequência
  visível, e entra na lista do KAM-084.

## Controlo de versões

| Versão | Data | Autor | Alterações |
|---|---|---|---|
| 1.0 | 2026-10-24 | KAM-025 | Versão inicial: consumidor da fila e mecanismo de tranca |
| 1.1 | 2026-10-24 | KAM-025 | Revisão adversarial: a Decisão 2 passa a `pg_try_advisory_lock` num ciclo (a espera não pode ser exclusiva — uma ligação por **processo**, não por *worker*), a fila do executor fica por `(thread_id, conversation_id)` enquanto a tranca fica por `thread_id`, e o produtor ganha `attempts`/`backoff` sem os quais nada do que este ADR diz sobre a volta do *job* à fila acontecia. A variável `AGR_TRANCA_DO_JOB_MS` que a versão 1.0 nomeava **não existe**: é a constante `TRANCA_DO_JOB_MS`. |

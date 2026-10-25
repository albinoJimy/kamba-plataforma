# AGR — o serviço, a tranca por conversa e a API interna

| Campo | Valor |
|---|---|
| Ticket | KAM-025 — AGR: serviço, workers assíncronos, lock por conversa e API interna |
| Fonte normativa | [`docs/tecnica/02_Agent_Runtime_Verticais.md`](tecnica/02_Agent_Runtime_Verticais.md) §3, §4, §5.3, §11 regra 4, §12, §14, §15.2; ADR-002, ADR-009, ADR-010, ADR-015, ADR-018 em [`docs/tecnica/00_Arquitectura_Solucao.md`](tecnica/00_Arquitectura_Solucao.md) §8 |
| Decisões deste ticket | [`docs/adr/ADR-L004-fila-e-tranca-do-agr.md`](adr/ADR-L004-fila-e-tranca-do-agr.md) — quem consome a fila, e o que serializa um turno |
| Nomes | [`specs/02_Dicionario_de_Dados_Canonico.md`](../specs/02_Dicionario_de_Dados_Canonico.md) §3.13 (o contrato) e §3.24 (o que este ticket acrescenta) |
| Código | [`services/agr/src/kamba_agr/`](../services/agr/src/kamba_agr/) (Python) e [`packages/core-ts/src/agr/`](../packages/core-ts/src/agr/) (o *shim* da fila) |
| Verificações | [`services/agr/tests/`](../services/agr/tests/) no *gate* 4; [`db/tests_agr/`](../db/tests_agr/) no *gate* 8 |
| Estado | **O esqueleto está em vigor; o serviço não vai a produção antes do KAM-027 e do KAM-031.** Os quatro tectos são *proposta* e calibram-se em KAM-084 |

> **O que este documento é.** O que o AGR faz hoje, o que ele deliberadamente
> ainda não faz, e as três coisas que enganam quem o opera. O que não está aqui
> e está no código não é desenho: é implementação, e pode mudar sem PR a este
> ficheiro.

---

## 1. O que existe, e o que não

O AGR é um processo Python (`services/agr`) com **LangGraph só como biblioteca
MIT** (ADR-002). O KAM-001 deixou-lhe a `/healthz`; o KAM-025 enche-o com o
esqueleto do serviço. Não há agente nenhum.

| Capacidade | Estado |
|---|---|
| `GET /healthz` | Desde o KAM-001 |
| `POST /internal/turn`, `POST /internal/resume` com credencial interna | **KAM-025** |
| Um turno por conversa (tranca), coalescência, tectos por *tenant* e por contacto | **KAM-025** |
| Guardas do ADR-002 em *runtime* (lista de bloqueio, telemetria desligada) | **KAM-025** |
| Checkpointer Postgres no esquema `lg`, e o papel `kamba_agr` | KAM-026 |
| AgentRegistry e validação no arranque | KAM-027 |
| ToolLayer | KAM-028 |
| Grafo do Vendedor / de Serviços | KAM-031 / KAM-035 |
| Modo determinístico e `agr_degraded_turns_total` | KAM-037 |
| *Compare-and-set* da retoma do *handoff* | KAM-034 |

**Enquanto o KAM-027 não registar grafos, `/internal/turn` com uma invocação
válida responde 503 com `Retry-After`**, e a mensagem fica na fila. É o estado
honesto de um esqueleto: um 200 fingia que o turno correu, e um 500 punha o
BullMQ a repetir para sempre uma mensagem que nenhuma versão deste código
consegue tratar. A forma segue o `docs/tecnica/02` §14, linha do checkpointer
indisponível — «o turno não corre; a mensagem permanece na fila».

---

## 2. O caminho de um turno

```text
CHR (KAM-014)  --publica-->  fila `agr-inbound`  (jobId = sha256(tenant_id:wamid))
                                    |
                         shim TS (worker-canal/src/agr_shim.ts)
                                    |  POST /internal/turn, x-kamba-interno
                                    v
  [autenticação]  ->  [ler o contrato]  ->  [ritmo]  ->  [vaga do tenant]
                                    |
                      fila por `thread_id` + coalescência
                                    |
                  pg_advisory_lock(hashtextextended(thread_id, 0))
                                    |
                [quem tem a palavra?]  --não-é-bot-->  HND (KAM-019)
                                    |
                                  grafo  (KAM-027 / KAM-031)
```

A tabela de estados HTTP — o que cada resposta diz ao *shim* sobre repetir ou
não o *job* — está na *docstring* de
[`api_interna.py`](../services/agr/src/kamba_agr/api_interna.py), e é o único
sítio onde ela vive.

---

## 3. As três coisas que enganam quem o opera

### 3.0 A espera pela tranca não é exclusiva, e tem de continuar a não ser

Há **uma** ligação dedicada à tranca por processo, e o driver é síncrono. A
primeira versão deste ticket usava `pg_advisory_lock`, que bloqueia no servidor:
a espera prendia a `thread` e, com ela, o `asyncio.Lock` da ligação. Uma
conversa à espera parava o processo inteiro, e as que acabavam não conseguiam
`pg_advisory_unlock` — bloqueio de cabeça de fila a atravessar *tenants*, sem
erro nenhum, com os pedidos pendurados até o `fetch` do *shim* cortar.

Hoje é `pg_try_advisory_lock` num ciclo com recuo exponencial, e a espera é
**fora** do trinco da ligação. Quem mexer nisto tem de manter a propriedade: a
bateria `db/tests_agr/test_repeticao.py::TestDoisExecutoresNaMesmaConversa`
mede-a, e há uma mutação (`agr: a espera pela tranca volta a ser exclusiva`) que
a repõe de propósito para confirmar que a bateria a apanha.

**E a fila do executor tem outra chave:** `(thread_id, conversation_id)`. A
tranca é por `thread_id` porque tem de travar os dois canais do mesmo contacto —
é o `thread_id` do LangGraph —, mas um lote **nunca** pode atravessar conversas:
a decisão sai da primeira invocação, e um lote misturado aplicava a decisão de
uma conversa à outra e perdia a mensagem da outra.

### 3.1 A ligação da tranca não pode passar por um *pooler* em modo transacção

É o único modo de falha desta escolha que **não dá erro nenhum**: dá exclusão
mútua que não exclui. Em modo transacção a ligação é devolvida ao *pool* entre
instruções, e uma tranca de **sessão** fica invisível a quem a tomou e presa
para quem vier a seguir. O `KAMBA_DB_HOST` do AGR aponta para a base; em modo
`session` um *pooler* funciona.

O sintoma, quando aparecer, é um `TrancaNaoLargadaError`: o
`pg_advisory_unlock` devolveu `false`, isto é, o `trancar` e o `destrancar`
correram em ligações diferentes. Está a levantar de propósito — sem ler o
resultado do `unlock`, este defeito não tem onde aparecer.

Diagnóstico: as duas ligações do AGR identificam-se em `pg_stat_activity` como
`kamba-agr:leitura` e `kamba-agr:tranca`. Uma tranca presa é uma sessão
`kamba-agr:tranca` com uma linha `advisory` em `pg_locks`.

### 3.2 O `lockDuration` do *job* tem de cobrir o turno inteiro

O *shim* **espera** pela resposta do AGR, de propósito: é isso que faz um turno
interrompido a meio ser retomado (critério 4). O *job* fica aberto durante o
turno, e o `TRANCA_DO_JOB_MS` (120 000 ms, *proposta*) é o número que decide se
o BullMQ o declara `stalled` com o *shim* vivo.

**E o *job* só volta à fila porque o produtor o permite:** o `fila.add` do
`chr/fila.ts` leva `attempts` e `backoff` (`TENTATIVAS_DO_AGR`), e o `attempts`
é opção do *job* e não do *worker* — sem ele o BullMQ dá **uma** tentativa e
manda o *job* para `failed`, com o `wamid` bloqueado porque o `jobId` deduplica
em `failed`. Faltava, e tornava falsa toda a frase «a mensagem fica na fila»;
quem mexer no produtor tem de o manter.

Curto demais **não perde** o *job*: duplica-o. O AGR é idempotente por
`turn_id` e o envio leva `idempotency_key = turn_id:seq`, pelo que a duplicação
não produz uma segunda mensagem — mas produz um turno a mais, e aparece como
`agr_shim_total{outcome="executado"}` abaixo de
`agr_turns_total{outcome="executado"}`. É essa diferença que se vigia.

### 3.3 Zero e os dois tectos

`AGR_RITMO_POR_CONTACTO=0` e `AGR_TECTO_POR_TENANT=0` significam **sem limite**,
e não «nada passa». É parte do contrato e não um descuido: é o modo em que o
critério 2 se mede (20 mensagens da mesma conversa em série), porque com a
coalescência a 1,5 s as vinte davam **um** turno e com o tecto a 3 davam
dezessete recusas. A tensão entre os critérios 2 e 3 está escrita na *docstring*
de [`admissao.py`](../services/agr/src/kamba_agr/admissao.py).

Um valor que não seja inteiro **levanta** no arranque, em vez de cair na
omissão: um tecto mal escrito que caia em silêncio é um tecto que ninguém
configurou a parecer configurado.

---

## 4. Configuração

| Variável | Omissão | O que é |
|---|---|---|
| `PORT`, `HOST` | `8000`, `127.0.0.1` | Como nos serviços Node. Só o `Dockerfile` põe `0.0.0.0` |
| `KAMBA_ENV` | `dev` | Um valor fora de `dev`/`staging`/`prod` **levanta** |
| `KAMBA_SECRET_AGR_INTERNAL_TOKEN` | — | **Obrigatório nos três ambientes.** Sem ele o arranque sai com `2` |
| `KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME` | `127.0.0.1`, `5432`, — | As de `db/ligacao.py`. Lidas na **primeira ligação**, não no arranque: o AGR serve `/healthz` com a base em baixo |
| `KAMBA_SECRET_DB_APP_PASSWORD` | — | O papel é o `kamba_app` |
| `AGR_RITMO_POR_CONTACTO` | `20` | *Proposta*. Mensagens/minuto por contacto; `0` = sem limite |
| `AGR_TECTO_POR_TENANT` | `3` | *Proposta*. Turnos em curso por *tenant*, **neste processo**; `0` = sem tecto |
| `AGR_COALESCENCIA_MS` | `1500` | *Proposta*. Distância máxima entre duas mensagens para se juntarem; `0` = nenhuma coalescência |
| `AGR_LIMIAR_DE_CONTRAPRESSAO` | `100` | *Proposta*. Turnos à espera a partir dos quais se conta contrapressão |
| `LANGSMITH_TRACING`, `LANGCHAIN_TRACING_V2` | **impostas a `false`** | Não se leem: impõem-se (critério 7). Quem quer *traces* tem o Langfuse (KAM-069) |

E, do lado do *shim* (`services/worker-canal/src/agr_shim.ts`):
`KAMBA_REDIS_URL`, `KAMBA_AGR_URL` (a URL do AGR na rede interna),
`AGR_SHIM_PORT` (3025) e o mesmo `KAMBA_SECRET_AGR_INTERNAL_TOKEN`.

### O tecto por *tenant* é por processo, e isso fica dito

Com N réplicas do AGR o tecto efectivo é 3×N. Um tecto verdadeiramente
distribuído pedia um contador em Redis, que é um ticket que ninguém abriu. O que
este tecto compra — e o que a *suite* mede — é que um *tenant* com mil mensagens
em fila não esgota os *workers* do processo: a partir do tecto o AGR responde
503 e o *shim* devolve o *job* à fila com atraso, em vez de as mil ficarem a
ocupar *workers* a dormir.

---

## 5. As guardas do ADR-002, e o que elas não cobrem

| Regra do §4.2 | Onde se cumpre |
|---|---|
| 1 — lista de bloqueio no lockfile | CI: `tools/lint_arch` (*gate* 2) e `make supply-chain` |
| 1 — **e no processo** | `egresso.exigir_biblioteca_mit()` no arranque: se `langgraph_api` estiver importável, sai com `3` |
| 2 — `LANGSMITH_TRACING=false` | `egresso.desligar_telemetria()`, que **impõe** e não verifica |
| 2 — egresso por *allowlist* | [`services/agr/egress.yaml`](../services/agr/egress.yaml): `por_omissao: negar`, `destinos: []` |
| 3 — *traces* no Langfuse | KAM-069 |
| 4 — serviço próprio, API interna mínima | `api_interna.py`: duas rotas |

**Porque é que a importabilidade se verifica em *runtime* e não só no CI:** o
lockfile e a imagem não são a mesma coisa que o processo. Um `pip install` à mão
num contentor de depuração, uma imagem base que mude, uma camada que alguém
acrescente — nenhuma passa pelo lockfile, e todas acabam com o `langgraph_api`
importável num processo em produção. O CI protege o que **declaramos**; isto
protege o que **corre**.

**O que isto não cobre, e não se diz coberto:** «0 chamadas a
`beacon.langchain.com` com egress bloqueado» mede-se com a rede bloqueada, e o
bloqueio é o KAM-076. O que existe hoje é o contrato (`egress.yaml`, negado por
omissão, com o `beacon` fora da lista e a razão escrita lá) e a guarda de
arranque. A *suite* do *gate* 8 verifica o contrato; não finge medir a rede.

**E o nome exacto da variável de telemetria é NÃO VERIFICADO** na versão fixada
do LangGraph (L5, e o critério 7 di-lo). Impõem-se as **duas** que a evidência
nomeia (`LANGSMITH_TRACING` e o nome antigo `LANGCHAIN_TRACING_V2`), porque
custa zero e fecha as duas leituras; o egresso negado por omissão é o que vale
se nenhuma delas for a certa.

---

## 6. Métricas

As seis do AGR (`agr_turns_total{outcome}`, `agr_turn_latency_ms`,
`agr_queue_depth`, `agr_admitted_rejected_total{motivo}`, `agr_coalesced_total`,
`agr_backpressure_total`) e as duas do *shim* (`agr_shim_total{outcome}`,
`agr_shim_failed_total`) estão no dicionário §3.24, com a razão de cada uma.

Três notas que valem mais do que a lista:

- **Nenhuma leva `tenant_id`, `contact_id`, `conversation_id` ou `wamid`**
  (`docs/seguranca/ameacas_stride.md`, `OBS-I`), e a regra impõe-se pela
  **gramática** da etiqueta — `^[a-z][a-z0-9_]{1,62}$`, que um UUID com hífenes
  não casa — e não por uma lista de palavras proibidas.
- **O `agr_turn_latency_ms` é um *gauge* com o último valor, não um percentil.**
  Esta biblioteca não implementa histogramas (ADR-018, observabilidade leve no
  Piloto). O p95 que o critério 5 pede mede-se onde tem significado — na *suite*
  e no *staging*, sobre a amostra toda —, e a agregação contínua é KAM-080.
- **O `agr_degraded_turns_total` não existe**, e a caixa do DoD fica por marcar.
  O modo determinístico é o KAM-037 e não há, neste ticket, caminho nenhum por
  onde um turno possa ficar degradado; uma métrica declarada e sempre a zero
  afirma o que ninguém mediu. É a mesma decisão que o KAM-018 tomou para o
  `echo_latency_ms`.

---

## 7. Como se corre a verificação

```bash
# gate 4, lado Python: as baterias do servico, sem base nem fila
python -m unittest discover -s services/agr/tests -t services/agr/tests

# gate 4, lado Node: o shim da fila
node --test --experimental-strip-types packages/core-ts/tests/agr.shim.test.ts

# gate 8: a tranca, o SIGKILL, quem tem a palavra e o X-02, contra PostgreSQL real
python db/gate_bd.py --suite tests_agr
```

O `gate_bd.py` levanta o seu próprio PostgreSQL 18.6 descartável (em `tmpfs`,
porta só em `127.0.0.1`) e apaga-o no fim. A *suite* do AGR **não** precisa de
fila: o consumidor é o *shim* em TypeScript, e a porta do AGR é HTTP
(`ADR-L004`, Decisão 1).

### O que cada bateria pode dizer, e o que não

A distinção importa porque uma tranca falsa que serializa é exactamente o duplo
que faz um defeito de SQL passar por verde:

| Pergunta | Quem responde |
|---|---|
| O executor pede a tranca e corre um lote de cada vez? | `services/agr/tests/test_turno.py` (tranca falsa) |
| O `pg_advisory_lock` é exclusão mútua **entre sessões**? | `db/tests_agr/test_tranca.py` — e só a base o pode dizer: a segunda tomada na mesma sessão é concedida de imediato |
| A tranca larga quando o *worker* morre? | `db/tests_agr/test_tranca.py`, com um `SIGKILL` a sério num processo filho |
| As cadeias de `consultas.py` correm? | `db/tests_agr/test_palavra.py` — uma base falsa compara SQL por texto e nunca o interpreta |
| A RLS esconde a conversa de A do contexto de B? | `db/tests_agr/test_palavra.py` (X-02) |
| 20 mensagens em série, pela ordem? | `db/tests_agr/test_repeticao.py::TestSerieContraABase` — e **isso mede o dreno**, não a tranca: um executor é uma ligação, e o `pg_advisory_lock` conta por sessão |
| Dois clientes da tranca sobre a mesma conversa não se sobrepõem, e a espera de um não prende o outro? | `db/tests_agr/test_repeticao.py::TestDoisExecutoresNaMesmaConversa` |
| Um lote nunca atravessa conversas do mesmo contacto? | `services/agr/tests/test_turno.py::TestUmLoteNaoAtravessaConversas` |
| A re-entrega do mesmo *job* não gasta quota de ritmo? | `services/agr/tests/test_admissao.py::TestRitmoEIdempotencia` |

---

## 7-A. O checkpointer e o esquema `lg` (KAM-026)

O estado de uma conversa vive no esquema `lg`, num *checkpointer* **nosso**
sobre `pg8000`. A interface e o serializador vêm do `langgraph-checkpoint`
(MIT); o SQL está em `kamba_agr/consultas.py` e prova-se contra um PostgreSQL
real na *suite* `tests_agr`.

### Porque é que não é o `AsyncPostgresSaver`

O `docs/tecnica/02` §12 nomeia o `langgraph-checkpoint-postgres` 3.1.2 e o `E4`
§2.6 dá-o como «MIT, sem restrições». O pacote é MIT; **o fecho dele não é**:

| Pacote | Licença |
|---|---|
| `langgraph-checkpoint-postgres` 3.1.2 | MIT |
| ⤷ `psycopg >= 3.2.0` | **LGPL-3.0-only** |
| ⤷ `psycopg-pool >= 3.2.0` | **LGPL-3.0-only** |

O `ci/licenses.yaml` nega o prefixo `LGPL`, e este repositório já tinha
recusado o `psycopg` pelo nome duas vezes por escrito — a tabela do
`db/requirements/migrations.in` (KAM-003) e a nota do `runtime.in` deste
serviço. Emendar a política pede dois revisores.

O que entra é o `langgraph-checkpoint`, cujo fecho — 35 pacotes — foi medido
com o avaliador do próprio *gate* 11 contra o `ci/licenses.yaml`: **35
permitidas, 0 fora**. O fecho do AGR passa de 12 para 44. O `langgraph` do
KAM-027 traz este fecho de qualquer maneira, pelo que este ticket paga-o um
ticket mais cedo e não o cria.

### As duas tabelas, e porque não são três

O *saver* oficial separa os valores dos canais num `checkpoint_blobs` próprio,
para não reescrever o estado a cada passo. Aqui o estado é a **janela
recortada** — últimas `JANELA_MAXIMA` mensagens mais o `summary` —, pelo que
cabe numa coluna. Uma tabela a menos, um `JOIN` a menos por leitura.

**O que isso custa:** um grafo que use `DeltaChannel` guarda só um sentinela no
`channel_values` e reconstrói o valor andando a cadeia de escritas para trás. O
`aget_delta_channel_history` não está implementado, e o `BaseCheckpointSaver`
levanta nesse caminho — melhor levantar do que reconstruir um estado vazio em
silêncio.

### O que o checkpointer não implementa, e porquê

| Método | Porquê |
|---|---|
| `aprune` | A própria interface avisa que um `keep_latest` ingénuo corta a cadeia de um canal `DeltaChannel` e que o valor «would silently reconstruct as empty (no error raised)», e nomeia como opção segura não podar. Não há grafo nenhum ainda; quem decide se algum usa canais delta é o KAM-031 |
| `acopy_thread` | A fusão de contactos migra o *thread* (`docs/tecnica/02` §12), e quem funde contactos é outro processo. Nenhum critério do bloco o pede |
| `aget_delta_channel_history` | Depende do `checkpoint_blobs` que este esquema não tem |
| Os métodos síncronos | O AGR só chama os assíncronos |

### O isolamento, que aqui não é RLS

As tabelas do `lg` **não têm `tenant_id`**, pelo que o ADR-015 — «`FORCE ROW
LEVEL SECURITY` em todas as tabelas com `tenant_id`» — não se lhes aplica. Não
é contradição: é a ausência da condição que ele nomeia. O que as isola são três
coisas, e nenhuma é a RLS:

1. o prefixo do `thread_id` (`{tenant_id}:{contact_id}`), construído **só** do
   estado validado e conferido contra a invocação antes de cada turno;
2. o papel `kamba_agr`, que **não tem `USAGE` no `platform`** e por isso não
   consegue juntar estas linhas a nada;
3. o ensaio cruzado, que mede 1 e 2 contra a base.

O `ci/rls_exceptions.yaml` não leva linha nenhuma: aquele ficheiro é para
tabelas **com** `tenant_id` que dispensem a política, e uma excepção morta
falha o *gate* 6.

### A retenção, e os dois prazos do canon

`retencao.varrer` apaga as *threads* sem escrita há mais de
`DIAS_DE_INACTIVIDADE` dias, com o papel `kamba_batch`. **Não há agendador**
nesta fase, como no KAM-017: esta função é o corpo da varredura, e quem a chama
a horas é o KAM-071 com o KAM-079.

O prazo tem dois valores no canon e **nenhum é decisão deste ticket**: o
`docs/tecnica/02` §12 diz *threads* inactivos **> 30 dias**; o
`docs/tecnica/08` §7.1 e §11 dizem conteúdo de conversa **90 dias após o
fecho**, que é o que o KAM-071 toma. Não são o mesmo relógio, e «fecho de
conversa» não está definido em documento nenhum. Fica o valor do §12 como
*proposta*, e o prazo espera parecer — como o próprio §11 já diz.

### Uma armadilha do critério 2, que vale para quem lá voltar

O critério manda varrer as tabelas `lg.*` por `\+?244\d{9}` e devolver **0**.
Com o estado serializado em `msgpack`, **uma busca por texto passa vazia mesmo
com um telefone lá dentro** — o critério satisfeito pela razão errada. O
varrimento da bateria desserializa com o serde e procura nos objectos, e há um
ensaio que semeia um número de propósito e exige que o varrimento o encontre.
Sem esse, o outro não prova nada.

---

## 8. O que este documento não decide

A topologia e as réplicas (`docs/tecnica/09`, KAM-088), a aplicação da
*allowlist* de saída na rede (KAM-076), a calibração dos quatro tectos e o
`lockDuration` (KAM-084), a agregação de métricas (KAM-080), e tudo o que a
tabela do §1 atribui a outro ticket.

---

## 9. Controlo de versões

| Versão | Data | Autor | Alterações |
|---|---|---|---|
| 1.0 | 2026-10-24 | KAM-025 | Versão inicial: o esqueleto do AGR, a tranca, a API interna e os tectos |
| 1.1 | 2026-10-24 | KAM-025 | Revisão adversarial: o §3.0 (a espera pela tranca e a chave da fila), o `attempts` do produtor no §3.2, e a tabela do §7 corrigida — o teste das 20 em série mede o dreno e não a tranca, e isso agora está escrito |
| 1.2 | 2026-10-25 | KAM-026 | §7-A: o checkpointer sobre `pg8000` e o esquema `lg`. Porque não é o `AsyncPostgresSaver` (o fecho dele é LGPL), as duas tabelas em vez de três e o que isso custa, os quatro métodos que não se implementam, o isolamento que aqui não é RLS, a retenção e os dois prazos do canon, e a armadilha do critério 2 — em `msgpack`, uma busca por texto não encontra um telefone que lá esteja |

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
| Checkpointer Postgres no esquema `lg`, e o papel `kamba_agr` | **KAM-026** |
| AgentRegistry, as seis validações de arranque e `resolve` | **KAM-027** |
| Guarda do SBOM do ambiente em *runtime* | **KAM-027** |
| ToolLayer | KAM-028 |
| *Gateway* de LLM por *digest*, chaves virtuais e `dat.llm_call_log` | **KAM-030** |
| Validador de citação: *renderer* por referência e vínculo `sku`↔preço | **KAM-032** |
| Grafo do Vendedor / de Serviços | KAM-031 / KAM-035 |
| Modo determinístico e `agr_degraded_turns_total` | KAM-037 |
| *Compare-and-set* da retoma do *handoff* | KAM-034 |

**`/internal/turn` com uma invocação válida continua a responder 503 com
`Retry-After`**, e a mensagem fica na fila. É o estado honesto de um esqueleto:
um 200 fingia que o turno correu, e um 500 punha o BullMQ a repetir para sempre
uma mensagem que nenhuma versão deste código consegue tratar. A forma segue o
`docs/tecnica/02` §14, linha do checkpointer indisponível — «o turno não corre;
a mensagem permanece na fila».

**E o KAM-027 não mudou isso, de propósito.** O registo existe, valida-se no
arranque e o `resolve` funciona; o que não existe é **grafo**. O `graph` das
duas verticais aponta para `kamba_agr.verticais.<id>:build_graph`, que o KAM-031
e o KAM-035 escrevem. Ligar o `grafos=` do `ExecutorDeTurnos` ao registo hoje
trocava um 503 por outro 503 — `GrafoNaoRegistadoError` por alvo que não
resolve — e punha uma leitura de entitlement no caminho de cada turno para
nada. O `sem_grafos` fica, e quem o substitui é o ticket que tiver um grafo
para lhe dar. **O serviço continua a não ir a produção antes do KAM-031.**

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
| `KAMBA_REGISTRY_DIR` | `registry` | Onde vivem os `registry/*.yaml`, relativo ao `cwd` (no contentor, `/app`). O *dataset* golden resolve-se contra a **pasta acima** desta, para que um caminho absoluto mova as duas coisas juntas. Um registo inválido sai com `5` |
| `KAMBA_FASE` | — | Ausente ou vazia **trata-se como `piloto`** (`kamba_core.fluxo_piloto`): uma vertical `phase: D` não arranca. É a validação (5), ADR-011 |
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
| 1 — **e no processo, por módulo** | `egresso.exigir_biblioteca_mit()` no arranque: se `langgraph_api` estiver importável, sai com `3` |
| 1 — **e no processo, pelo SBOM** | `egresso.exigir_sbom_mit()` (KAM-027): se uma distribuição da lista de bloqueio estiver **instalada**, o mesmo `3`. Não é a mesma pergunta — ver abaixo |
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

**E a guarda do módulo não é a guarda do SBOM.** O `find_spec` procura
**módulos**; o `exigir_sbom_mit` lê as **distribuições instaladas**
(`importlib.metadata`), que é o SBOM do ambiente no único sentido que um
processo pode medir sobre si próprio. A diferença mede-se num pacote real: o
`langgraph-checkpoint-postgres` instala `langgraph.checkpoint.postgres`, dentro
de um pacote de *namespace* que nós **temos** e queremos ter — nenhum nome de
`MODULOS_PROIBIDOS` o encontraria, e ele está na lista de bloqueio desde o
KAM-026 porque o fecho dele exige `psycopg` e `psycopg-pool`, LGPL-3.0-only.

A guarda compara pelas **mesmas regras do *gate* 2** — nomes normalizados por
PEP 503, fronteira de palavra para os nomes curtos, `forbidden_below` onde ele
existe — e há um teste que confronta as duas implementações **por
comportamento** e não por campos: para 23 nomes × 4 versões, a guarda de
*runtime* e o `lint_arch.blocklist` têm de decidir o mesmo. Há duas cópias
porque `tools/` não está no `PYTHONPATH` do contentor do AGR e o `Dockerfile`
não o copia; o que as mantém honestas é esse teste.

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

As seis do KAM-025 (`agr_turns_total{outcome}`, `agr_turn_latency_ms`,
`agr_queue_depth`, `agr_admitted_rejected_total{motivo}`, `agr_coalesced_total`,
`agr_backpressure_total`) e as duas do *shim* (`agr_shim_total{outcome}`,
`agr_shim_failed_total`) estão no dicionário §3.24, com a razão de cada uma. O
KAM-026 acrescentou duas (`agr_checkpoint_latency_ms`,
`agr_checkpoint_state_bytes`) e o KAM-027 uma:
**`agr_registry_denied_total{motivo}`**, com `motivo` ∈ {`sem_entitlement`,
`vertical_desconhecida`} — é o «emite alerta» do critério 6 (dicionário §3.26).

Quatro notas que valem mais do que a lista:

- **Uma métrica que este módulo não conheça levanta, e isso apanhou um
  defeito.** O `MetricasDoAgr.contar` recusa um contador que não esteja no
  `_AJUDA` («contador desconhecido»), e o `agr_registry_denied_total` não
  estava: os testes do `resolve` contavam contra um duplo e passavam, e em
  produção o primeiro *tenant* sem plano fazia o turno rebentar. Há agora um
  teste que conta contra o `MetricasDoAgr` **real** e lê a exposição. A lição
  não é sobre esta métrica: é que um duplo de métricas prova que se chamou
  `contar`, não que o contador existe.

- **Nenhuma leva `tenant_id`, `contact_id`, `conversation_id` ou `wamid`**
  (`docs/seguranca/ameacas_stride.md`, `OBS-I`), e a regra impõe-se pela
  **gramática** da etiqueta — `^[a-z][a-z0-9_]{1,62}$`, que um UUID com hífenes
  não casa — e não por uma lista de palavras proibidas.
- **O `agr_turn_latency_ms` é um *gauge* com o último valor, não um percentil.**
  Esta biblioteca não implementa histogramas (ADR-018, observabilidade leve no
  Piloto). O p95 que o critério 5 pede mede-se onde tem significado — na *suite*
  e no *staging*, sobre a amostra toda —, e a agregação contínua é KAM-080.
- **As cinco do validador de citação são contadores, e as «taxas» do §9.2 são
  razões entre eles** (KAM-032). O §9.2 do `tecnica/02` nomeia
  `validate_fail_rate`, `validate_retry_rate`, `handoff_by_citation` e
  `render_only_ratio`, e três delas são taxas; esta biblioteca não tem
  histogramas, e uma taxa guardada numa medida perde o denominador. Exportam-se
  `agr_validate_total`, `agr_validate_falhas_total`,
  `agr_validate_repeticoes_total`, `agr_validate_handoff_total` e
  `agr_render_only_total`, todas com o eixo **`vertical`**, e a taxa lê-se no
  painel. O `tenant_id` **não** é eixo de nenhuma, pela regra da gramática acima
  — e isso é o critério 8 do KAM-032 a não se poder cumprir à letra: ver o §7-E.

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

## 7-B. O AgentRegistry e as seis validações (KAM-027)

Uma vertical é configuração e não código (ADR-012): um tuplo
`(grafo, tools autorizadas, persona, entitlements, subscrições)` num
`registry/*.yaml`, com SemVer. O `AgentRegistry` lê esse tuplo, recusa-o quando
está errado, e devolve-o a quem corre um turno.

O módulo é `services/agr/src/kamba_agr/registo/` — três ficheiros: `esquema.py`
(os modelos Pydantic), `validar.py` (as seis validações) e `__init__.py`
(`carregar`, `AgentRegistry`, `resolve`). Vive no AGR e não em `libs/py-core`
pela razão que o `estado.py` do KAM-025 escreveu: aquela biblioteca é o que
**todos** os serviços Python precisam de fazer igual, e o AGR é o único que
constrói e lê isto.

### Três formas em `registry/`, e a terceira é deste ticket

| Ficheiro | Chave de topo | Quem o escreve |
|---|---|---|
| `vendedor.yaml`, `servicos.yaml` | `id` | KAM-027 (a forma é `docs/tecnica/02` §5.1) |
| `plans.yaml` | `plans` | KAM-009 — o AGR **salta-o**: quem o lê é o provisionamento |
| `gates.yaml` | `gates` | KAM-027 — o **modo** de cada validação |

A forma escolhe-se pela **chave de topo** e nunca pelo nome do ficheiro, nos
dois lados: no *gate* 3b (`tools/canon_lint/registo.py`) e no `carregar`. Um
`planos.yaml` ou um `tarifas.yaml` são o mesmo ficheiro, e adivinhar pelo nome
punha a verificação a depender de como alguém lhe chamou.

### As seis validações, e as três que esperam

| # | Nome | Fonte da verdade | Modo hoje |
|---|---|---|---|
| 1 | `tools` | catálogo da ToolLayer | bloqueio **desde o KAM-028** (§7-C) |
| 2 | `entitlements` | `kamba_core.ten.CHAVES_DE_LIMITE` | bloqueio |
| 3 | `grafo` | o `build_graph` da vertical | **aviso** → KAM-031 / KAM-035 |
| 4 | `subscriptions` | `kamba_core.eventos.contratos.CATALOGO` | bloqueio |
| 5 | `fase` | `kamba_core.fluxo_piloto` | bloqueio |
| 6 | `golden` | o disco, e o *eval harness* | **aviso** → KAM-040 |

**Eram três em `aviso` e são duas.** A (1) fechou com o KAM-028, e o §7-C diz
como: o catálogo da ToolLayer existe, o `__main__` passa-o ao `carregar`, e as
duas linhas `tools: { modo: aviso }` saíram do `registry/gates.yaml`. **Fechar
uma validação é apagar a linha** — não há interruptor no código, e `bloqueio` é
a omissão precisamente para isso.

**Uma validação por ligar não é uma validação que passa.** As duas que faltam
não têm fonte no repositório, e havia duas maneiras erradas de lidar com isso:
devolvê-las verdes (o defeito que o próprio bloco avisa — «um critério pode
estar satisfeito pela razão errada») ou pô-las a falhar, o que impedia o AGR de
arrancar hoje por causa de um ticket de amanhã.

O que se faz é o que o **critério 8** manda fazer para a (6), e vale igual para
as outras duas: a validação **corre sempre** e devolve o problema que encontra —
«o catálogo não está ligado» é um problema —, e o `registry/gates.yaml` diz se
esse problema bloqueia ou avisa, **com o ticket que o fecha**. Um `modo: aviso`
sem `credor` é recusado.

**`bloqueio` é a omissão, e é isso que faz do `gates.yaml` um registo e não um
interruptor:** fechar um aviso é **apagar** uma linha, nunca acrescentar uma. Há
um teste que o mede (`test_apagar_a_linha_do_gates_torna_a_validacao_bloqueante`).

### O que o arranque escreve, e o que não cabe lá

Uma linha de `warn` por par (validação, credor), com `error_code` na forma
`tools_kam_028`. **A prosa do problema não cabe** no `error_code`: a *allowlist*
de `docs/tecnica/08` §7.3 faz dele um identificador de 96 caracteres, e a
primeira versão deste código punha lá a frase — que a *allowlist* deixava cair
**em silêncio**. O resultado era um arranque que dizia ter registado os avisos e
não registava nenhum, que é precisamente a coisa que o critério 8 existe para
evitar. Um teste apanhou-o, e há uma mutação que o prende.

### `resolve`, e porque devolve duas coisas

```python
resolve(ctx) -> Resolucao(vertical=..., resposta=None, motivo=None)
             |  Resolucao(vertical=None, resposta="servico_indisponivel", motivo="sem_entitlement")
```

O §5.2 escreve `resolve(ctx) -> Vertical`, e o critério 6 pede mais: «sem
entitlement activo devolve a resposta estática *serviço indisponível* e emite
alerta». Um `Vertical` não tem onde levar essa resposta, e levantar uma excepção
punha o caminho normal de um *tenant* sem plano a passar por um `except` — que é
como uma recusa prevista deixa de se distinguir de um defeito.

O alerta é `agr_registry_denied_total{motivo}`, com `motivo` ∈
{`sem_entitlement`, `vertical_desconhecida`}. **O `tenant_id` não entra na
etiqueta** (`OBS-I`), e não por omissão: a gramática de etiqueta de
`metricas.py` recusa-o pela forma.

**Uma só vertical principal por número no Piloto**: o que decide é
`ctx.vertical`, que o CHR resolveu do canal. Não há agregação nem *front-door
router* — isso é Fase C, e um registo que escolhesse entre duas verticais para o
mesmo número estaria a implementá-lo por acidente.

### Dois nomes que o canon corrigiu, e que o desenho ainda escreve

- **`valor_max_pedido_minor`**, e não o `valor_max_pedido_kz` que o §5.1 e os
  *Detalhes Técnicos* do bloco escrevem: a emenda 1.13 do dicionário registou
  aquele nome como **variante**, pelo que o *gate* 3b o trata como achado de
  nível 1 e um `vendedor.yaml` escrito à letra do §5.1 **não passava**.
- **Os dois eventos de pagamento** nas duas verticais. O §5.1 subscreve só
  `payment.confirmed`; o Piloto usa o `ManualProvider`, cujo evento é
  `payment.manual_confirmed`, e o dicionário §3.5 já decidiu que quem não
  distingue os dois caminhos subscreve os dois. É também o gate da Fase 0: um
  pedido do Vendedor pago à mão emite o segundo, e é a vertical **Serviços** que
  o consome (KAM-108).

### O que este ticket não liga

O `grafos=` do `ExecutorDeTurnos`. Ver o §1: o `graph` das duas verticais aponta
para um módulo que o KAM-031 e o KAM-035 escrevem, e até lá o `/internal/turn`
continua em 503. O `resolve` é a costura; quem a usa é o ticket que tiver um
grafo para lhe dar — e é também ele que passa o `checkpointer` ao
`compile(checkpointer=...)`.

---

## 7-C. A ToolLayer: os oito passos, as classes e a `tool_audit` (KAM-028)

A TLS é a **única** via de leitura e escrita dos agentes (`docs/tecnica/02`
§6.1, ADR-015). O modelo nunca vê nem fornece `tenant_id`: as tools são
construídas por turno a partir do `ToolContext`, derivado do estado.

O módulo é `services/agr/src/kamba_agr/tls/` — oito ficheiros, em português como
o resto do pacote, com os nomes do **contrato** em inglês porque são canon
citado do §6.1 (`ToolLayer`, `for_context`, `invoke`, `ToolContext`,
`ToolResult`, `Fact`, `Confirmation`), como o `load_all` do §5.2. Vive no AGR e
não em `libs/py-core` pela razão de sempre.

| Ficheiro | O que tem |
|---|---|
| `contexto.py` | o `ToolContext` e a `Confirmation` — a fronteira do que o modelo pode influenciar |
| `erros.py` | os dez erros do §6.5, o `Fact` e o `ToolResult` |
| `especificacoes.py` | a forma de uma especificação e o `Catalogo` |
| `catalogo.py` | as **onze** tools do Piloto (§6.2) |
| `get_store_info.py` | a primeira tool real |
| `disjuntor.py` | o *circuit breaker* por backend |
| `auditoria.py` | a linha de `tool_audit` |
| `camada.py` | a `ToolLayer` e os oito passos |

### Os oito passos são dados, e não a ordem em que estão escritos

O `PASSOS` do `camada.py` é a tupla das oito funções, por ordem. Não é indirecção
por gosto: é o que torna a **ordem** uma coisa que um teste pode afirmar
(`nomes_dos_passos()` contra os oito nomes do §6.1) e o que permite a um teste
por passo substituir os seguintes por espiões e provar que nenhum correu — que é
o critério 1. Escritos em linha dentro de um `invoke` de cem linhas, a ordem só
se afirmava lendo.

| # | Passo | O que recusa, e com que código |
|---|---|---|
| 1 | `allowlist` | fora do catálogo, fora do `allowed` da vertical, ou `declarada` → `TOOL_NOT_ALLOWED` |
| 2 | `entitlement` | o `hook_de_tool` do KAM-009 → `ENTITLEMENT_DENIED` ou `LIMIT_EXCEEDED` |
| 3 | `argumentos` | Pydantic com `extra="forbid"` → `VALIDATION_ERROR` |
| 4 | `confirmacao` | `write`/`money` sem botão válido → `VALIDATION_ERROR`; de **outro contacto** → `TENANT_MISMATCH` |
| 5 | `idempotencia` | `write`/`money` sem chave do chamador → `VALIDATION_ERROR`; `cart_id` reutilizado com outro conteúdo → `INTENT_REUSED_WITH_DIFFERENT_CONTENT`; reserva de outro ainda `em_curso` ao fim de 3 s → `UPSTREAM_TIMEOUT`. Um resultado guardado **para** aqui o pipeline, com `idempotent_replay=true` (KAM-029) |
| 6 | `backend` | disjuntor aberto → `UPSTREAM_DOWN`; *timeout* → `UPSTREAM_TIMEOUT`; o resto, o que o backend disser |
| 7 | `auditoria` | não recusa: **escreve**, e levanta se não conseguir |
| 8 | `facts` | devolve |

**O passo 2 não é código novo.** O `hook_de_tool`
(`libs/py-core/src/kamba_core/ten/hook.py`) foi escrito pelo KAM-009 para esta
camada, pelo nome: «o §6.1 passo 2 … é este módulo». Faz as três verificações na
ordem que protege cada uma — entitlement, tecto por pedido, consumo — e devolve
já os códigos do §6.5. Corre **dentro** de uma transacção com `app.tenant_id`:
a `platform.entitlements` tem RLS, e sem contexto negava toda a invocação de
todos os *tenants* — falha fechada, mas pela razão errada.

### Uma entrada de catálogo tem dois estados, e é isso que fechou a validação (1)

As duas verticais do Piloto declaram **onze** nomes de tool, e a validação (1)
exige que todas existam no catálogo. Mas as especificações das tools do Vendedor
são do KAM-031 e as de Serviços do KAM-035. A distinção que resolve é entre
**nome** e **especificação**: o nome, a classe e o botão são canon desde a
emenda 1.35 do dicionário; o modelo de argumentos e o executor são dos outros
dois tickets.

| | `ligada` | `declarada` |
|---|---|---|
| nome, `klass`, `backend`, versão | sim | sim |
| modelo e executor | sim | **não** |
| `credor` (o ticket que a liga) | não | **obrigatório** |
| visível ao modelo (`for_context`) | sim | **não** |
| `invoke` | corre | recusa com `TOOL_NOT_ALLOWED` |

Hoje é **uma** ligada (`get_store_info`) e dez declaradas. Uma entrada sem
executor **e sem credor** é recusada — a mesma disciplina que o KAM-027 impôs ao
`gates.yaml`: um atalho sem o ticket que o fecha não é atalho.

### A `platform.tool_audit`, e porque não é a `audit_log`

| | `audit_log` (KAM-012) | `tool_audit` (KAM-028) |
|---|---|---|
| O que cobre | dinheiro, stock, preço, acessos privilegiados, configuração | **todas** as invocações, leituras incluídas |
| Cadeia de hash | sim, por *tenant*, com âncora diária | **não** |

Uma invocação `money` escreve nas **duas**. A cadeia não se copia, e é decisão:
a `audit_log` escreve por acto de negócio e esta escreve por invocação; a cadeia
serializa as escritas de um *tenant* num `UPDATE` da `audit_heads`, e posta aqui
punha o caminho de leitura de um turno à espera do mesmo trinco. O que se copia
é a **imutabilidade em três camadas**, porque nenhuma sozinha basta:

1. `REVOKE UPDATE, DELETE, TRUNCATE … FROM PUBLIC` — não prende o dono;
2. o *trigger* que levanta — prende o dono. **É por isso que o
   `db/tests/test_privilegios.py` vê o `kamba_migrator` com tudo e a tabela
   continua *append-only***;
3. `ENABLE ALWAYS` — prende quem pode `SET session_replication_role = replica`.

**O que a linha não guarda** é o critério 5: nem texto de mensagem, nem
telefone, nem valores de argumento — **nem os nomes deles**. As chaves de `args`
vêm do modelo de linguagem, e um nome é texto tanto como um valor: a primeira
versão escrevia-os em claro, e `{"contacto 999123456789": "x"}` punha um
telefone na `tool_audit` pela coluna que este critério fecha para os valores —
pelo caminho `VALIDATION_ERROR`, que é onde um argumento inventado chega.
Apanhado pela revisão adversarial. Hoje só passam os nomes que o esquema
**declara**; o resto conta-se em `<nao_declarados>`. O `args_hash` é um `sha256`, o
`args_redacted` guarda a **forma** (nome e tipo de cada argumento, nunca o
valor) e os `fact_ids` são identificadores. Isto não se prova a ler o DDL:
prova-se por varrimento dos dados com canários, e o varrimento tem **controlo**
— um teste que semeia o canário pelo caminho legítimo e exige que o varrimento
o encontre. Sem o controlo, um varrimento que procure no sítio errado dá zero e
o critério passa pela razão errada.

**E o varrimento encontrou uma fuga onde ninguém tinha olhado:** um `fact_id`
derivado de um argumento põe texto do cliente na coluna `fact_ids`. Para quem
vier cunhar `fact_id` a sério (KAM-031, KAM-032): **um `fact_id` é opaco.**

### As tomadas são uma fila, e não uma

| Variável | Omissão | O que é |
|---|---|---|
| `KAMBA_TLS_LIGACOES` | `4` | Quantas tomadas a camada abre |

**Não é uma, e a razão foi medida.** A primeira versão tinha uma ligação e um
`asyncio.Lock`, como o `leitor` do `conversa.py` — e ali a razão escrita é que
«um *worker* faz uma leitura por turno e os turnos do *worker* são em série».
Aqui não: um turno invoca tools várias vezes e os turnos correm em concorrência.
Com uma tomada, **dez invocações de dez *tenants*** com um backend de 200 ms
levavam **2,02 s** em vez de ~0,2 s: bloqueio de cabeça de fila a atravessar
*tenants*, que é o defeito mais caro do KAM-025 repetido. Apanhado pela revisão
adversarial; hoje são 0,61 s com a fila de quatro.

A fila é o *pool* **e** é o tecto: no máximo `KAMBA_TLS_LIGACOES` ligações, e
quem não tem vaga espera por uma vaga — não pelo turno de outro *tenant*. Todas
as operações dela correm no laço e nunca na *thread*: um `put_nowait` de dentro
de um `asyncio.to_thread` não é seguro, e é por isso que a ligação volta pelo
**valor de retorno** do trabalho e não por ele próprio.

### O tecto de tempo tem dois lados, e a camada impõe o de fora

**Nenhum tecto era imposto, e isso também foi medido.** O `timeout_ms` ia no
`Pedido` e só o `get_store_info` o honrava (do lado do servidor): um executor de
5 s contra o tecto de 2 s devolvia `ok=True` em 5,01 s. Com o ponto anterior,
um executor pendurado prendia toda a leitura e escrita do processo, sem
recuperação.

| Lado | Quem o impõe | O que para |
|---|---|---|
| do backend | o executor, com o `timeout_ms` que recebe. No `plataforma` é um `SET LOCAL statement_timeout` | a consulta, **na base** |
| da camada | `asyncio.wait_for`, sobre o tecto da classe mais `MARGEM_DO_TECTO_MS` (500 ms) | a espera de **quem chamou** |

A folga existe para que o tecto preciso ganhe quando existe: sem ela, os dois
corriam no mesmo instante e qual mordia dependia do escalonador.

Quando a espera estoura, a *thread* **continua** — não se cancela uma, e não se
quer. Ela tem a tomada, acaba o pipeline e escreve a linha de `tool_audit` com a
latência real, pelo que a invocação **não desaparece do registo**. O que custa é
a sua vaga até acabar: uma tool pendurada tira **uma** das
`KAMBA_TLS_LIGACOES`, e não o processo.

### A quarta ligação, e porque não é a da leitura

| Ligação | Papel | `autocommit` | Para que serve |
|---|---|---|---|
| leitura | `kamba_app` | não | `conversations.mode` e `handoffs.status` |
| tranca | `kamba_app` | **sim** | só `pg_advisory_*` |
| **tools** | `kamba_app` | não | entitlement, backend `plataforma`, `tool_audit` |
| checkpoint | `kamba_agr` | não | o esquema `lg`, e nada do `platform` |

É tomada própria porque o `kamba_core.tenant_guard` **recusa** uma segunda
transacção na mesma ligação (`LigacaoEmUso`), e uma invocação abre três em
série. Partilhada com a leitura da palavra da conversa, a primeira tool de um
turno rebentava por uma razão que não tem nada a ver com ela.

Papel `kamba_app` e não `kamba_agr`: o que ela toca é do `platform`, e o
`kamba_agr` **não tem `USAGE` no `platform`**, de propósito (KAM-026).

### O que este ticket acrescenta à configuração e ao arranque

| Variável | Omissão | O que é |
|---|---|---|
| `KAMBA_TLS_LIGACOES` | `4` | Quantas tomadas a camada abre. Ver «As tomadas são uma fila» |
| `KAMBA_TLS_TIMEOUT_READ_MS` | `2000` | O tecto de uma tool `read` (§6.5). Para o backend `plataforma` é um `SET LOCAL statement_timeout`, do lado do servidor |
| `KAMBA_TLS_TIMEOUT_ESCRITA_MS` | `8000` | O tecto de uma `write` ou `money` |
| `KAMBA_TLS_DISJUNTOR_FALHAS` | `5` | Falhas **consecutivas** por backend até abrir |
| `KAMBA_TLS_DISJUNTOR_PAUSA_MS` | `30000` | Quanto fica aberto. Passada a pausa deixa passar **uma** tentativa |

Um valor que não serve **levanta** no arranque (código `2`) em vez de cair na
omissão: um `KAMBA_TLS_TIMEOUT_READ_MS=dois` lido como 2000 punha o tecto a ser
um número que ninguém escolheu.

**E há um código de saída novo: o `6`.** Sem auditoria de tools o AGR não
arranca. A guarda confirma, no arranque, que o papel tem `INSERT` nas dezoito
colunas de `tool_audit`, e **não escreve nada** — a tabela é *append-only* e uma
linha de ensaio ficava lá a contar como invocação numa tabela cuja cobertura é
critério de aceitação. A razão de ser guarda de arranque é que o §6.1 põe o
registo no passo **7**, depois da chamada ao backend: um privilégio em falta só
se descobria com um efeito de `money` já feito e sem registo.

Os cinco códigos, e cada um manda olhar para um sítio diferente:

| Código | O que falta | Onde olhar |
|---|---|---|
| `2` | configuração ou cofre | o `.env` |
| `3` | a guarda do ADR-002 | a imagem |
| `4` | *checkpointer* (KAM-026) | o cofre da base, o papel `kamba_agr` |
| `5` | registo de verticais (KAM-027) | `registry/` |
| `6` | auditoria de tools (KAM-028) | a revisão `0021` e os seus `GRANT` |

### As cinco métricas, e porque as etiquetas são derivadas

```
agr_tool_invocacoes_total{tool}            counter  invocacoes, por tool
agr_tool_erros_total{codigo}               counter  erros, por codigo do §6.5 em minusculas
agr_tool_latency_ms                        gauge    duracao da ultima invocacao
agr_tls_disjuntor_aberto_total{backend}    counter  aberturas do disjuntor
agr_tool_tenant_mismatch_total             counter  o alerta do critero 8, sem etiqueta
```

As listas fechadas das etiquetas **derivam-se** do catálogo, dos códigos e dos
backends, e não se escrevem à mão: é a lição que o KAM-027 pagou no
`test_gate11` — «uma lista literal transforma uma invariante num número». O
KAM-031 e o KAM-035 acrescentam especificações sem ter de vir aqui.

O `agr_tool_tenant_mismatch_total` **não leva etiqueta**, de propósito: o que um
painel precisa de saber é que **houve** um, e qual tool foi lê-se na
`tool_audit`. Uma etiqueta por tool convidava a tratar o alerta como uma
estatística por tool, e um destes não é estatística.

### O *lint* do critério 3, e porque entra num *gate* que já existia

`tools/lint_arch/tool_schema.py`, no subcomando `tool-schema` e no `all` — logo
nos *gates* 2 e 11. **Não abre *gate* novo**: um *gate* novo é uma regra de
bloqueio nova, e isso pede dois revisores.

Lê a **fonte** com o `ast` e não importa nada, porque o `lint_arch` corre antes
de qualquer instalação, por desenho. E isso não é limitação: importar os modelos
dava a resposta do código **a correr**, e um PR traz código **escrito**. A mesma
regra é aplicada em execução pela `tls/especificacoes.py`, que recusa a
especificação no arranque; as duas listas de parâmetros proibidos são
confrontadas por um teste para não divergirem.

**Uma descoberta que mudou o código:** a *docstring* de uma classe `BaseModel`
entra no `model_json_schema()` como `description`, e o esquema **é o que vai ao
modelo de linguagem**. A primeira versão do `ArgumentosDeGetStoreInfo`
explicava-se com uma frase que dizia `tenant_id` por extenso. Não é um
parâmetro — o critério fala de parâmetros — mas ensinava ao modelo um nome que
ele não tem de conhecer. **O que se escreve numa classe de argumentos de tool,
ou num `Field(description=…)`, é texto para o modelo**; a explicação para quem
lê o código vai em comentário.

### O que este ticket não liga

O `invoke` de dez das onze tools: estão `declaradas` e o passo 1 recusa-as. Quem
as liga é o **KAM-031** e o **KAM-035**, e é também quem recebe a instância da
camada no `build_graph(deps)` — o `__main__` constrói **uma** por processo,
porque o disjuntor conta falhas consecutivas por backend e isso é estado do
processo: uma instância por grafo dava a cada vertical um contador próprio, e
dois contadores a metade do caminho nunca abrem.

A chave de idempotência do §6.3 e a tabela `tool_idempotency` **eram** do
KAM-029 e estão entregues (`tls/idempotency.py`, revisão `0022`). O que o KAM-028
deixou aqui foi a coluna, o parâmetro, e a regra de que `write`/`money` nunca
correm sem chave.

**E três coisas que o KAM-029 teve de corrigir ao atravessar este passo**, as
três descobertas a escrever código contra o que estava escrito:

| O que estava | O que passou a estar |
|---|---|
| o `Pedido` não levava a chave ao executor | leva (`Pedido.chave`). Sem isso, «o backend é idempotente pela chave» era uma frase sem nada a sustentá-la, e a retoma de uma reserva `falhada` duplicava o efeito |
| a `tool_audit.idempotency_key` era «a chave do §6.3» | é a do **chamador**, a do turno. A do §6.3 é a do carrinho e vive em `tool_idempotency.key`; são duas porque um segundo toque com `wamid` novo é um turno novo (dicionário §3.28) |
| o fecho da reserva no `finally` do pipeline | **também no `except`, antes de a ligação cair**. O caminho de excepção fecha a tomada e o `finally` corre depois dele: a reserva ficava aberta precisamente no caminho em que mais precisa de fechar |

A terceira é a que fecha a janela do achado 12 da `analises/ANALISE-30`, e foi
apanhada **a correr** a bateria da falha injectada — não a ler o código.

O retry do §6.5 («1 retry com *backoff*») é do grafo: **a camada não repete
nada**, de propósito, e há teste a dizê-lo.

---

## 7-E. O validador de citação: os dois níveis e o que eles não cobrem (KAM-032)

O ADR-007 manda que preço e stock nunca estejam em *prompts* nem *embeddings* e
que **cada número citado exista no *output* real de uma tool**. O
`docs/tecnica/02` §9 desenha isso em duas camadas, e o módulo
`kamba_agr/validador/` é as duas:

| Camada | Onde | O que faz |
|---|---|---|
| 1 — citação por referência (proposta 02-A) | `render.py` | o `compose` devolve **blocos** e não números; o *renderer* preenche-os a partir de *facts* |
| 2 — validador pós-geração | `veredicto.py` | confronta o texto final (e qualquer prosa livre) com os *facts*, e devolve os sete veredictos |

A camada 1 é a garantia e a camada 2 é a rede de segurança. O §8.4 diz o que o
grafo faz com o veredicto: «retry → handoff», com o `citation_retries` que o
§5.3 já tem no estado.

### O contrato dos blocos

Cinco, e são os do dicionário §3.30 (emenda 1.39) — o exemplo do §9.1 tem
quatro, e o quinto vem do §8.2, que estende o validador a «datas, horas e
durações»:

```json
{ "blocks": [
  { "type": "text",     "text": "Encontrei estas opções para si:" },
  { "type": "item",     "sku": "SKU-100", "show": ["name", "price", "stock"] },
  { "type": "total",    "fact_id": "ft-1" },
  { "type": "datetime", "fact_id": "fd-1" },
  { "type": "buttons",  "ids": ["confirm:c_77", "cancel:c_77", "human"] } ] }
```

Três decisões que o exemplo do §9.1 não escreve, e que custam de descobrir:

- **Os `buttons` saem ao lado do texto, e não dentro dele.** Um id de botão é
  `confirm:c_77`, e o `77` é estrutura e não um número citado: posto no corpo da
  mensagem, o extractor lê-o e dá `number_unbacked` — o *renderer* a falhar o
  seu próprio validador. É também o que o canal faz: numa mensagem interactiva
  os botões são *payload* próprio (`tecnica/01` §8), e o limite é de **10**
  (§8.2, limite da Meta, CONFIRMADO).
- **Um bloco `item` leva sempre o `sku`.** O `tecnica/05` §6.3 diz «resposta com
  `sku` ausente é rejeitada», e um `item` que mostrasse só nome e preço seria
  recusado pela camada 2 — com razão, porque é exactamente a forma do «produto
  errado com preço certo».
- **Um bloco `text` com dígitos levanta.** É a regra do §9.1 («o modelo não
  escreve números em prosa») imposta onde é barata. Degradar em silêncio gastava
  uma repetição do modelo para descobrir o que o *renderer* sabe de imediato.

E uma ausência que é desenho: **o `show` admite `name`, `price` e `stock`, e não
`description`.** O critério 5 pede que os dígitos de descrições escritas pela PME
não contem como *facts* e que o modelo não os possa repetir; a forma de o garantir
não é uma regra que alguém tenha de lembrar, é **não haver campo**. A `Oferta`
que o módulo consome tem `sku`, `nome` e `preco_tipo` — nem descrição, nem preço
(o preço vem de um `Fact`).

### Os sete veredictos, e o vínculo que fecha o ponto cego do ADR-007

`money_unbacked`, `sku_price_mismatch`, `name_sku_mismatch`, `qty_unbacked`,
`datetime_unbacked`, `discount_unbacked`, `number_unbacked` — lista fechada
(dicionário §3.30), porque o grafo decide **pelo veredicto** e um código que ele
não conheça cai no caminho de omissão.

Em dinheiro a tolerância é zero, e são quatro passos por cada valor do texto:

1. tem de existir um *fact* `price` ou `total` com **exactamente** aquele valor,
   senão `money_unbacked`. É isto que apanha o critério 3: **um total somado
   correctamente pelo modelo mas que não é *fact* falha**, porque os totais vêm
   só do `propose_cart`;
2. se só um `price` o sustentar, o `sku` desse preço tem de estar **na mesma
   linha**, senão `sku_price_mismatch`. É o §6.3 do `tecnica/05`, e é o que fecha
   o «produto errado com preço certo» que o próprio ADR-007 assinala como o seu
   ponto cego;
3. uma linha cujo `sku` esteja `sob_consulta` recusa **qualquer** valor
   monetário, mesmo um que coincida com um total;
4. um `sku` em `a_partir_de` exige o marcador «a partir de» na linha — citado
   como preço fixo, falha. Os três modos são os do dicionário §3.3 e o
   `precoDisplay` é o do `tecnica/03` §7.1: «12 500 Kz», «a partir de 12 500 Kz»,
   «preço sob consulta».

**A quantidade vincula-se ao `sku` da mesma maneira**, e isso não está no §9.1.
O pseudocódigo escreve só `require_fact(q, kinds={"qty","stock"})`, e um teste
mostrou o que isso deixava passar: «SKU-100 — Camisa Azul — 7 unidades» era
**aceite** porque 7 era o stock de outro produto. É o mesmo «produto errado com
número certo», e a mitigação que o §9.2 nomeia para ele é a mesma — «validação
por `kind` e por vínculo».

### Três `kind` que faltam, e o que isso custa a dois critérios

O bloco declara «dependência apenas da interface `Fact`», e três dos sete
veredictos pedem `kind` que o catálogo do §6.2 não tem: `name`, `qty` e
`discount` (o §9.1 nomeia ainda um quarto, `expiry`). O `KINDS` do KAM-028 está
fechado nos **quatro** do §6.2, e um `Fact(kind="discount", …)` **levanta**. É a
dívida **105**, e o credor que ela nomeia é o **KAM-031**, o ticket que produz os
*facts*: «quem acrescenta o `kind` é o ticket que produz o *fact*».

O que este módulo faz em vez disso, e o preço de cada escolha:

| Veredicto | Cai em | Consequência |
|---|---|---|
| `qty_unbacked` | `stock`, que existe | nenhuma: é o `kinds={"qty","stock"}` do §9.1 menos o que não existe |
| `datetime_unbacked` | `datetime`, que existe | nenhuma, pela mesma conta sobre o `expiry` |
| `name_sku_mismatch` | o `nome` do contrato de saída do `tecnica/05` §6.3 | o nome vive no `ToolResult.data` e não num `Fact`, pelo que o validador recebe a **oferta** ao lado dos *facts* em vez de inventar um `kind` |
| `discount_unbacked` | **nada** | *qualquer* percentagem recusa. É *fail-closed* e é o que o ADR-007 manda, **mas o lado positivo do critério 2 — uma percentagem com *fact* a ser aceite — é inverificável** até o `kind` existir |

O mesmo vale para a moeda: o critério 1 diz «moeda diferente de Kz **sem *fact*
de moeda** é erro», não há `kind` de moeda, e por isso *toda* a moeda
estrangeira é erro. A metade «com *fact*» também não se consegue medir.

### A unidade é o cêntimo, e o critério escreve outra coisa

O critério 1 diz «devolve `value_kz` inteiro». **Não é o nome nem a unidade**, e
as duas fontes que decidem isso são mais altas do que o bloco: o §2 do dicionário
manda unidade menor inteira (`*_minor`), e o §9.1 do `tecnica/02` foi **corrigido
pelo KAM-139** depois de a revisão adversarial medir o achado C1 — o *fact* vem
do `search_catalog` em `preco_minor`, em cêntimos, e comparar a fala do cliente
em Kz com um *fact* em cêntimos falha **sempre**, por um factor de cem. «12.500
Kz» dá `value_minor = 1250000`. Está na dívida **106** e na emenda 1.39.

Os nove formatos do critério 1 têm um teste cada, e a parte difícil é a
ambiguidade do separador: o critério pede `12,500` = 12 500 Kz **e** `12,5 mil` =
12 500 Kz, isto é, a mesma vírgula a decidir coisas diferentes. As seis regras
estão no cabeçalho do `normalizacao.py`; a única que é uma **escolha** e não uma
leitura é «vírgula com exactamente três dígitos e sem multiplicador é separador
de milhares», e a consequência está escrita lá.

### O critério 8 não se cumpre à letra, e a caixa fica vazia

Pede as quatro métricas «exportadas com `tenant_id` e `vertical`». **O
`tenant_id` não pode ser etiqueta de métrica** — não por convenção, pela
gramática: um UUID tem hífenes, não casa `^[a-z][a-z0-9_]{1,62}$`, e a chamada
levanta `EtiquetaInvalida` (`OBS-I`). Uma métrica escrita como o critério pede
não exporta valor nenhum: rebenta no primeiro turno.

Não é a primeira vez. As emendas 1.21, 1.25 e 1.38 resolveram-no da mesma
maneira, e a dívida **54** é o caso idêntico — o critério 4 e o DoD do KAM-015
pedem `meta_cost_usd_total{tenant}`, a etiqueta não é implementável, e «as duas
caixas ficam vazias». Aqui: o `vertical` entra (lista fechada, derivada de
`VERTICAIS`), o `tenant_id` não, a desagregação por *tenant* faz-se onde tem
significado — o `turn_id` do registo do turno, de onde a amostragem do §9.2 lê —,
**a gramática não se alarga**, e a decisão volta a quem escreveu o critério.

### As limitações do §9.2 estão medidas, e não fechadas

O bloco manda «limitações a assumir e testar». Um validador que passasse estas
não é o que o ticket pede; o que ele pede é que estejam nomeadas e com o efeito
preso por teste — no dia em que uma delas mudar, a bateria falha e alguém decide
de propósito. Vivem em `casos_adversariais.LIMITES`, em lista **separada** do
conjunto do *gate* duro, para não inflarem o «0 falsos aceites»:

| Limitação (§9.2) | O que o validador faz hoje |
|---|---|
| Coincidência de valores | um valor que coincide com um *fact* `total` dispensa o vínculo ao `sku`; a mitigação que o §9.2 nomeia para isto é a camada 1, não a 2 |
| Números por extenso | `um`/`uma` isolados são artigo e não número — «levo um» passa sem *fact*. Distingui-lo de «levo um produto» pedia entender a frase; o que escapa é a quantidade **1** |
| Afirmações sem números | «mais barato», «chega amanhã» não são cobertas: é `guard_out`, e o credor é o **KAM-033** |
| Disponibilidade qualitativa | «há em stock» sem quantidade passa |
| *Facts* obsoletos entre turnos | o `retrieved_at` **não** é consultado aqui; quem revalida é o `cart_build`/`create_order`, e o `PRICE_CHANGED` obriga a reconfirmar |
| Dígitos num **nome** de produto | o intervalo de um nome é reservado (senão «Vestido 2 peças» dava `qty_unbacked` em toda a resposta sobre esse produto). O que isso abriria fecha-se na `Oferta`, que **recusa** um nome com marca de moeda ou valor monetário dentro |

**E a regra dos três, que vai escrita onde o resultado aparece:** 0 falhas em
N = 200 limita o risco a cerca de **1,5%** com 95% de confiança. «0 divergentes
no conjunto» **não** é «0 divergentes em produção» — o §9.2 chama ao segundo um
«objectivo de desenho com risco residual», medido por amostragem
(`citation_fail_rate`, que não é métrica Prometheus e tem dono KAM-040 e
KAM-081).

### O fuso: desvio fixo, e não `ZoneInfo`

A apresentação é em `Africa/Luanda` e o armazenamento em UTC. O
`zoneinfo.ZoneInfo("Africa/Luanda")` **levanta** na máquina de desenvolvimento
(`ZoneInfoNotFoundError`: não há `tzdata`), e pô-lo a funcionar era uma
dependência nova para resolver um fuso que nunca teve horário de verão: Angola
está em WAT (UTC+1) sem transições. O desvio fixo é **exacto** para este fuso e
não arrasta dependência nenhuma.

### O que este ticket não liga

O nó `validate` e o `compose` do grafo (KAM-031 e KAM-035 — este módulo é a
interface que eles chamam, e o `registar` das métricas recebe do nó se houve
repetição ou *handoff*, porque só o nó o sabe); os três `kind` que faltam
(KAM-031); as frases vetadas sem número (KAM-033); o `price_quote` do dono
(KAM-123); a entrada do conjunto adversarial no *gate* 13 (KAM-040); e a
amostragem de produção (KAM-040 com KAM-081).

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
| 1.3 | 2026-10-25 | KAM-027 | §7-B: o `AgentRegistry`, as três formas de `registry/`, as seis validações do arranque e as três que correm em **aviso** com o credor nomeado em `registry/gates.yaml`, o `resolve` e o alerta, e os dois nomes que o canon corrigiu ao desenho (`valor_max_pedido_minor` e os dois eventos de pagamento). §5: a guarda do SBOM do ambiente, que não é a mesma pergunta que a do módulo — o `langgraph-checkpoint-postgres` instala `langgraph.checkpoint.postgres` e nenhum nome de `MODULOS_PROIBIDOS` o encontraria. §1 e §4: o 503 fica, e porquê; `KAMBA_REGISTRY_DIR`, `KAMBA_FASE` e o código de saída `5` |
| 1.4 | 2026-10-25 | KAM-028 | §7-C: a ToolLayer — os oito passos do §6.1 como **dados** (e porquê), os dois estados de uma entrada de catálogo e como isso fechou a validação (1) do §5.2, a `tool_audit` com a imutabilidade em três camadas e o que a linha **não** guarda, a quarta ligação e porque não é a da leitura, as quatro variáveis novas, o código de saída `6` e o *lint* do critério 3. §7-B: a tabela das seis validações passa a `bloqueio` na (1) e a prosa diz «eram três e são duas». Duas descobertas que mudaram código: a *docstring* de um modelo Pydantic vai no prompt, e um `fact_id` derivado de um argumento põe texto do cliente na auditoria. **Correcções da revisão adversarial** (`analises/ANALISE-30`): as tomadas passam a ser uma fila e não uma (uma só serializava todos os *tenants* — 2,02 s para dez invocações de dez *tenants*), a camada passa a **impor** o tecto de tempo (um executor de 5 s contra 2 s devolvia `ok=True` em 5 s), os **nomes** dos argumentos deixam de ir em claro para a `tool_audit`, a quarta tomada fecha-se no `ao_encerrar`, e o `error_code` da linha de arranque passa a ter a forma que a *allowlist* do §7.3 exige — não tinha, e com `KAMBA_LOG_ESTRITO=1` abortava o `main()` |
| 1.5 | 2026-10-25 | KAM-029 | §7-C: o passo 5 passa de ponto de extensão a passo com três recusas e um *replay*. O que **este** ticket descobriu ao atravessá-lo está na tabela do §7-C: o `Pedido` não levava a chave ao executor (e sem ela «o backend é idempotente pela chave» era uma frase sem sustento), a `tool_audit.idempotency_key` não é a chave do §6.3 mas a do **turno**, e o fecho da reserva tinha de correr também no `except` — o caminho de excepção fecha a tomada e o `finally` corre depois dele, pelo que a reserva ficava aberta precisamente no caminho em que mais precisa de fechar. As três saíram de **correr** e não de ler, a terceira na bateria da falha injectada. O décimo primeiro erro tipado (`INTENT_REUSED_WITH_DIFFERENT_CONTENT`) e o que ele arrasta: revisão `0022`, dicionário §3.28, e a etiqueta de `agr_tool_erros_total`, que é derivada |
| 1.6 | 2026-10-26 | KAM-030 | §7-D: o *gateway* de LLM — o cliente por **papéis** (`chamar(papel, mensagens, ctx)`), e porque é que nenhum SDK de fornecedor nem o pacote `litellm` entram no AGR (fala HTTP com o proxy, e o `httpx` já estava no fecho desde o KAM-026: o *gateway* **não acrescenta dependência nenhuma**); o *gate* de destino a correr **antes** da chamada e para **todos** os fornecedores do alias, porque o *fallback* é do router e autorizar só o de `ordem: 1` deixava o segundo receber os dados sem o *gate* ter sido consultado por ele; a `dat.llm_call_log` com uma linha por chamada **incluindo as recusadas**, e porque é que uma falha de registo **não** levanta (levantar repetia a chamada ao modelo — segunda transferência, segundo custo — e a perda de uma linha é mais barata); a quinta ligação (`kamba-agr:llm`) e porque não é a das tools; o código de saída **7**. §5: a guarda do arranque, que são três verificações de configuração — os dois ficheiros de `llm/` e o `INSERT` nas catorze colunas. **O que este ticket descobriu ao atravessar o proxy, e que mudou o desenho:** a configuração do `tecnica/02` §13.1, à letra, não comuta de fornecedor de forma determinística (`simple-shuffle`, 3 falhas em 20), o orçamento esgotado responde **422** e não 400, e `google/` não é um prefixo que o proxy conheça. As três saíram de **correr** e não de ler. §1: o 503 fica, e porquê — os grafos continuam a ser o KAM-031 e o KAM-035, e o que este ticket entrega é o caminho para o modelo, provado em `staging`, com a porta de `prod` fechada por desenho enquanto o KAM-069 não existir |
| 1.7 | 2026-10-26 | KAM-032 | §7-E: o validador de citação — as duas camadas do §9, o contrato dos cinco blocos (e as três decisões que o exemplo do §9.1 não escreve: os botões ao lado do texto, o `sku` sempre no `item`, e um `text` com dígitos a levantar), os sete veredictos com o vínculo `sku`↔preço que fecha o ponto cego do ADR-007, os três modos de preço, e a unidade em **cêntimos** contra o `value_kz` que o critério escreve (dívida 106, corrigido no desenho pelo KAM-139). §1 e §6: a linha do validador e as **cinco** métricas, que são contadores porque as quatro «taxas» do §9.2 não cabem numa biblioteca sem histogramas. **Dois limites escritos em vez de contornados:** o critério 8 pede `tenant_id` em etiqueta e isso levanta pela gramática (`OBS-I`), pelo que a caixa fica vazia como na dívida 54; e três `kind` que três veredictos precisam não existem (dívida 105, credor KAM-031), o que torna *qualquer* percentagem `discount_unbacked` — *fail-closed*, mas com o lado positivo do critério 2 **inverificável**. **Três defeitos que os testes apanharam e que mudaram código:** a quantidade não estava vinculada ao `sku` (7 unidades de um produto eram aceites pelo stock de outro), os dígitos de um nome de produto recusavam toda a resposta sobre esse produto, e um padrão guloso fazia «doze mil e quinhentos Kz» **desaparecer** — um falso aceite. |

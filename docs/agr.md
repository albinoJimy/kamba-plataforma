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
| Modo determinístico e `agr_degraded_turns_total` | **KAM-037** |
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
  painel: `falhas / total` (o `handoff` é um **subconjunto** das falhas e não se
  soma a elas), `repetições / total`, o `handoff` como contagem, e o
  `render_only` sobre `agr_turns_total{outcome="executado"}` — porque o
  denominador de uma proporção de **respostas** é o turno e não a validação, e um
  turno com duas repetições conta três validações. O `tenant_id` **não** é eixo de nenhuma, pela regra da gramática acima
  — e isso é o critério 8 do KAM-032 a não se poder cumprir à letra: ver o §7-E.

- **As quatro do *handoff* (KAM-034)** são `agr_handoff_total`,
  `agr_resume_total`, `agr_resume_nao_autorizado_total` e
  `agr_handoff_degradado_total` (dicionário §3.32). O eixo da primeira são os
  cinco valores de `handoffs.status` e chama-se **`estado`** e não `outcome`,
  porque `waiting` é um estado de abertura e chamar-lhe desfecho dizia que uma
  passagem que acabou de abrir já tem um; o eixo da segunda é o desfecho da
  chamada (`retomado`, `repetido`, `recusado`), e ali o nome está certo; o da
  terceira é o **`motivo`** (`sem_secret`, `secret_errado`), porque conta
  **porque** uma retoma não aconteceu; e a quarta é **sem etiqueta**, pela razão
  do `agr_tool_tenant_mismatch_total` — o que um painel precisa de saber é que
  houve degradação, e o estado da passagem lê-se na primeira. **Nenhuma leva
  `tenant_id`**, e o critério 8 do KAM-034 pede a métrica de retoma «por
  *tenant*»: a desagregação faz-se nas colunas de `platform.handoffs` e lê-se
  por consulta — ver o §7-G.
- **E o `agr_handoff_degradado_total` não é o `agr_degraded_turns_total`.** São
  duas degradações diferentes com nomes parecidos, e somá-las num painel é
  misturar coisas sem relação: a primeira conta passagens que o provedor não
  aceitou abrir (`tecnica/02` §14, linha do HND) e a segunda conta turnos que
  correram em **modo determinístico** por o LLM estar em baixo (§14, linha do
  LLM).

- **O `agr_degraded_turns_total` passou a existir com o KAM-037**, e a frase que
  aqui estava — «não existe, e a caixa do DoD fica por marcar» — deixou de ser
  verdade. A razão de ele faltar era boa e fica registada: «uma métrica declarada
  e sempre a zero afirma o que ninguém mediu», a mesma decisão que o KAM-018 tomou
  para o `echo_latency_ms`. O que a desfez foi passar a haver caminho por onde um
  turno pode ficar degradado — ver o §7-I.
- **E ele leva o `motivo` e não o `tenant`.** O critério 6 do KAM-037 pede
  «métricas por tenant» e o DoD «por motivo e tenant»: a tensão é a das dívidas
  54 e das emendas 1.38, 1.39 e 1.42, mas com uma diferença que importa — **aqui
  não há tabela onde desagregar**. O concierge tinha a `draft_decisions` e a
  passagem tinha a `handoffs`; um turno degradado não ganha registo durável, pela
  decisão que o **KAM-160** já escreveu para o `pending_reply`. A via é o campo
  `tenant_id` do *logger*, que a *allowlist* de `tecnica/08` §7.3 permite em log e
  proíbe em etiqueta, mais a janela de quinze minutos do detector. A caixa fica
  **parcial**.
- **O `agr_degraded_breaker_aberto_total` não é o `agr_tls_disjuntor_aberto_total`.**
  O eixo daquele são os backends de *tool* do §6.5, lista fechada, e o LLM não é
  uma *tool*: uma etiqueta nova ali **levantava**. Duas métricas e não uma
  etiqueta — a mesma razão que separou as duas degradações acima.

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

Os códigos, e cada um manda olhar para um sítio diferente:

| Código | O que falta | Onde olhar |
|---|---|---|
| `2` | configuração ou cofre | o `.env` |
| `3` | a guarda do ADR-002 | a imagem |
| `4` | *checkpointer* (KAM-026) | o cofre da base, o papel `kamba_agr` |
| `5` | registo de verticais (KAM-027) | `registry/` |
| `6` | auditoria de tools (KAM-028) | a revisão `0021` e os seus `GRANT` |
| `7` | *gateway* de LLM (KAM-030) | `llm/aliases.yaml`, `llm/precos.yaml`, a revisão `0023` |
| `8` | consumidores de eventos (KAM-038) | as `subscriptions` de `registry/*.yaml` |

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

## 7-F. O grafo do Vendedor: vinte e um nós, dois turnos e o que ele não liga (KAM-031)

O `docs/tecnica/02` §7 desenha o grafo; este capítulo diz o que ficou escrito em
código, o que se decidiu de maneira diferente e porquê, e o que um turno real
ainda não faz.

### A tabela de arestas é a fonte, e o grafo deriva dela

O esqueleto do §7.4 escreve as arestas à mão, uma `add_conditional_edges` por nó,
com o `path_map` em linha. O `build_graph` percorre a tabela
(`verticais/vendedor/arestas.py`) e constrói as ligações a partir dela.

A razão foi medida e não suposta: **dois destinos trocados no `path_map` de um
encaminhador dão exactamente o mesmo conjunto de arestas**, e o conjunto é o que
o teste de contrato compara. Escrito à mão, a troca passava; derivado da tabela,
não se consegue escrever. O mesmo mecanismo fecha mais duas classes — um nó
condicional sem encaminhador e um nó na tabela sem função fazem o `build_graph`
**levantar** no arranque, em vez de compilarem um grafo que cai no primeiro
turno.

### Trinta e nove linhas, quarenta e duas arestas

A tabela do §7.3 tem **39 linhas** e o grafo tem **42 arestas dirigidas**: a
linha 27 carrega duas (`order_status`, `tools_info` → `compose`) e a 34 carrega
três (`unknown_reply`, `ask_repeat`, `safe_reply` → `send`). O critério 1 do
bloco escreve «as 39 arestas», e um teste que afirmasse 39 passava com **três nós
sem caminho para o envio**. As duas contagens afirmam-se ambas, e cada aresta
leva o número da linha que a autoriza. Está na emenda 1.40, dicionário §3.31.

### O estado tem quatro campos novos, e nenhum é conveniência

A emenda **1.40** acrescenta-os ao §5.3, e os quatro apareceram ao escrever o
grafo contra a tabela:

| Campo | Porque é que não havia alternativa |
|---|---|
| `ofertas` | O `validate` precisa de resolver a designação de um produto a um `sku` (`name_sku_mismatch`), e o quarto parâmetro do `validar` do KAM-032 é a lista de ofertas. A designação vive no `ToolResult.data` do `05` §6.3 e **não** num `Fact` (dívida 105). Entre o `tools_read`, que a recebe, e o `validate`, que a consome, o estado é o único canal |
| `avisos` | Os critérios 3 e 6 do bloco mandam `STALE_CONFIRMATION`, `OUT_OF_STOCK`, `PRICE_CHANGED` e `LIMIT_EXCEEDED` chegar ao `compose` «como *facts*». Não podem: um `Fact` é **um número com proveniência** e o `kind` está fechado nos quatro do §6.2, pelo que `Fact(kind="STALE_CONFIRMATION")` levanta. O que os critérios querem é um campo de avisos, com domínio fechado de oito |
| `admissao` | Nove dos dez encaminhadores decidem por campos que o §5.3 já tinha; o `r_ingest` não tinha nenhum, e a alternativa era **voltar a perguntar** ao ritmo. Não se pode: o `aceita_o_ritmo` do KAM-025 **registra a chegada**, pelo que duas perguntas por turno cortavam o tecto de vinte por minuto a metade, sem nada no resultado o denunciar |
| `handoff_motivo` | O código do §11 já o lia no `handoff_prepare` e no `interrupt`, e o §5.3 não o declarava |

Os quatro são **do turno** e reiniciam-se no `ingest`, como os `facts`, e pela
mesma razão: uma oferta de um turno anterior é uma designação sem prova neste, e
um aviso de um turno anterior é uma explicação que já se deu. O `citation_retries`
entra no mesmo reinício, e isso não é óbvio — sem ele, uma resposta que falhasse
a citação num turno gastava a única repetição do turno **seguinte**, e o tecto do
§7.3 linha 30 passava a valer por *thread* em vez de por turno.

O `cart` e o `handoff_seq`, ao contrário, **atravessam** turnos: o fluxo de dois
turnos e a cadeia de *handoffs* dependem disso. **E é essa assimetria que
produziu o primeiro defeito deste ticket**: o bloco `total` do segundo turno
citava um carrinho cujo *fact* já não existia, e o `renderizar` levantava — a
confirmação de uma compra a falhar por defeito nosso. O `compose` passa a citar o
total **só** se o *fact* for deste turno, que é a linha «facts obsoletos entre
turnos» do §9.2: quem o quiser mostrar outra vez revalida no backend.

### O que o §9.1 não tem, e três respostas que ficam caladas

Os cinco blocos do *renderer* são `text` (sem dígitos), `item` (preso a um
`sku`), `total` e `datetime` (presos a um *fact*) e `buttons`. **Nenhum leva uma
cadeia opaca com dígitos**, e três respostas do Piloto precisam de uma: a morada
e o Plus Code da loja (`get_store_info`), a referência de uma encomenda
(`get_order_status`) e a referência de pagamento que o §14 manda repetir no modo
determinístico.

A proibição de dígitos num `text` **é** a regra que impede prosa numérica
(ADR-007) e não se desliga. Em Fase 0 sai o que não tem dígitos — o nome e a zona
da loja, a palavra do estado da encomenda — e o resto fica calado: mutilar o valor
era pior, porque parecia certo. É a dívida **124**, e é a mesma lacuna que faz a
identificação do §8.4 cair para uma frase sem o nome da loja quando esse nome tem
um dígito («Kero 24» fazia o turno inteiro rebentar na camada 1).

### O que é Fase 0, e o que é atalho

| Nó | O que faz hoje | Credor |
|---|---|---|
| `stt` | **Encaminha, não transcreve.** Sem porta de STT o veredicto é `ask_repeat`, que é a linha do §14 para «STT indisponível»; uma excepção do fornecedor dá o mesmo, em vez de matar o turno | KAM-036 |
| `guard_in` / `guard_out` | Determinísticos mínimos: PAN com Luhn, IBAN, seis padrões de injecção, três de fronteira de *tenant*, dez de assunto sensível, e sete frases vetadas mais telefone na saída. O classificador barato não entra | KAM-033 |
| `classify` | Regras primeiro, modelo só se elas não decidirem (§15.1). **Um botão `confirm:*` nunca passa por modelo** — é dinheiro, e a intenção está no identificador do botão | KAM-037 |
| `handoff_*` | O par de dois nós do §11, com os efeitos idempotentes por `handoff_id`; a porta `HandoffService` é injectada | KAM-034 |
| `cancelar` | O §7.3 **não tem nó de cancelamento**. O botão cai em `outro` e responde com texto estático, mas **larga o carrinho**: um `confirm:` que chegasse depois encontrava `awaiting_confirm` e criava a encomenda que o cliente acabou de cancelar | KAM-037 |

### As cinco tools ficam declaradas, e isso é uma decisão de segurança

Os modelos Pydantic das cinco tools do Vendedor entram (`tls/vendedor.py`):
são contrato, nascem do canon e não mudam quando o backend chegar. Os executores
de ensaio ficam no pacote da vertical (`verticais/vendedor/fakes.py`), de onde
nenhum arranque os importa, e o `catalogo_do_piloto()` mantém as cinco entradas
**`declaradas`**.

A razão não é arrumação. Um executor de ensaio registado no catálogo de produção
devolvia um `ToolResult` `ok` com *facts* que nenhuma loja tem, e o validador de
citação **aceita-os** — são *facts* de uma tool, que é exactamente o que ele
exige. Era abrir no sítio mais caro o buraco que o ADR-007 existe para fechar.

O credor das cinco passa de `KAM-031` para o ticket que liga cada backend:
**KAM-061** (o índice), **KAM-043** (preço e stock), **KAM-046** (o carrinho e o
pedido) e **KAM-044** (o estado da encomenda). São quatro e não os três que os
Detalhes Técnicos nomeiam — o `get_order_status` lê o `orders_mirror`, que é o
KAM-044.

### O que a revisão adversarial mudou, e a classe de defeito que ela nomeia

A `analises/ANALISE-34` reprovou o ramo com seis *must fix*, e **três eram
dinheiro**. Os três tinham a mesma forma — um mecanismo existia, a bateria
passava, e o caso que o quebrava não estava no conjunto —, mas o primeiro nomeia
uma classe que este serviço vai encontrar outra vez:

**Um argumento inventado não é um número afirmado, e a camada de citação não o
vê.** O `quantidade_pedida` lia qualquer número de um ou dois dígitos no texto do
cliente, pelo que «quero comprar a camisa azul **número 5**» dava um carrinho de
cinco camisas. O total que sai disso é um *fact* do backend, com proveniência
perfeita: o `validate` confronta o texto com os *facts* e **tudo bate**. O erro
está no argumento que o nó escolheu, e nenhuma barreira do ADR-007 olha para esse
lado. A regra passa a ser a mesma que o KAM-032 pagou para as palavras de número:
um número só é quantidade quando uma palavra o reclama (`quero N`, `N unidades`),
e dois candidatos a discordar voltam a um.

Os outros dois: um `cancelar` **escrito** deixava o carrinho de pé — o
cancelamento entrava só pelo botão, e o botão que fica no ecrã do WhatsApp
continuava a cobrar até ao TTL —, e a verificação de confirmação do passo 4 do
`invoke` **nunca era exercida pelo grafo**, pelo que a segunda barreira da classe
`money` podia ser removida com a *suite* verde.

**E o mais sério dos seis não era dinheiro: era a conversa a morrer.** O recorte
da janela deixava o tecto exacto e o `send` acrescentava a resposta por cima, com
o que o `aput` passava a levantar para sempre naquela conversa. O recorte deixa
agora lugar para a resposta (`JANELA_MAXIMA - 1`, uma mensagem por turno pelo
§15.1), e o ensaio confronta o estado final com a guarda **real** do checkpointer
em vez do saver em memória — que não a tem.

**Duas lições de escrita que valem para quem vier depois.** Um comentário que
enumera canon e implementa menos é pior do que a lacuna, porque quem o lê deixa
de a procurar: o `_SENSIVEL` listava as seis categorias do §8.4 e tinha padrões
para cinco. E uma guarda tem dois custos: «as minhas encomendas da loja já
saíram?» saía como `injection`, com o contador de abuso a somar sobre a pergunta
mais comum da vertical.

### O que este ticket não liga

**A porta `grafos` do `turno.py` continua a levantar, e o `/internal/turn`
continua a responder 503.** O KAM-027 deixou-a para «o ticket que tiver um grafo
para lhe dar», e este tem — mas com as cinco tools `declaradas` um turno real
respondia a toda a pergunta de produto por `safe_reply` ou por *handoff*, porque o
passo 1 do `invoke` recusa uma entrada sem executor. O 503 com `Retry-After`, que
mantém a mensagem na fila, é a linha honesta do §14 até os backends existirem.

**E o texto do cliente não tem caminho até ao grafo.** O contrato
`agent_invocation` (§3.13) tem nove campos fechados e nenhum é o corpo da
mensagem. O grafo lê o texto da janela `messages` do estado — que é o que o §12
manda guardar — e quem a enche é quem invoca o grafo. A convenção nasce aqui; o
credor é quem ligar a porta.

## 7-G. O handoff idempotente e a retoma por *compare-and-set* (KAM-034)

O `docs/tecnica/02` §11 tem o desenho em três regras e um par de nós; o que
este ticket entrega é o que elas obrigam, e o que não cabe numa delas está
escrito aqui.

### O par de nós era do KAM-031; o que falta é a porta e a saída

Os três nós — `handoff_prepare`, `handoff_wait`, `handoff_close` — fundiram com
o grafo do Vendedor, e este ticket **não os reescreve**: implementa o `Protocol`
que eles declararam. Os módulos são:

| Módulo | O que é |
|---|---|
| `handoff/portas.py` | A `HandoffIndisponivel`, e as portas do provedor, dos modos e dos grafos |
| `handoff/maquina.py` | Os cinco estados, os três desfechos, e a correspondência entre eles |
| `handoff/servico.py` | O `ServicoDeHandoff`: a abertura e a degradação |
| `handoff/retoma.py` | O `Retomador`: o CAS, o `Command(resume=…)` e a compensação |
| `handoff/prazos.py` | O `Prazos`: a varredura das 24 h |
| `handoff/autenticacao.py` | O `secret` do *agent bot* |

Os nomes do bloco do ticket estão em inglês (`kamba/handoff/{service,nodes,
resume_api,timeouts}.py`) e são do **documento**: os módulos desta casa têm
nomes em português. Os nomes dos **nós** não se traduzem — são canónicos
(dicionário §3.31) e são chaves do grafo, não palavras de prosa. E não há
`nodes.py`, porque não devia haver: uma segunda cópia dos nós, ou um invólucro a
chamá-los, eram duas definições do mesmo nó e um `build_graph` a escolher entre
elas.

### A `HandoffIndisponivel` mudou de casa, e a identidade da classe é a razão

O KAM-031 definiu-a em `verticais/vendedor/nos.py`, e estava certo enquanto o
único código que a levantava fosse o que a apanha. Deixou de ser: quem a levanta
é o `ServicoDeHandoff`, que é **partilhado** pelas duas verticais (§5.4), e um
`except HandoffIndisponivel` só apanha a excepção se for a **mesma** classe.

As duas alternativas eram piores. Importar o `nos.py` do Vendedor para dentro do
serviço arrastava o grafo inteiro — o LangGraph, o validador, a ToolLayer — para
o caminho de `/internal/resume`, que não tem grafo nenhum pela frente; e deixar
cada vertical com a sua classe dava duas excepções com o mesmo nome e um
`except` que cala uma delas. O nome continua importável de
`verticais.vendedor.nos`, e é o **mesmo objecto**.

### A `handoffs` tem dois escritores, em duas linguagens

É a divergência que a emenda 1.22 do dicionário deixou por resolver, e eram
**três** posições na casa e não duas: o `docs/tecnica/01` §11.5 põe o
*compare-and-set* no HND, a regra (3) do `docs/tecnica/02` §11 põe o **ponto de
entrada** no AGR, e o critério 7 do KAM-019 manda que «a retoma por
*compare-and-set* é KAM-034». Segue-se a regra (3), que é a única das três que
diz **onde** o *endpoint* vive e sob que *lock* corre.

A repartição pretendida era: criar a passagem, marcá-la aberta, degradá-la e
fechá-la pelo provedor é do HND (as quatro instruções do `hnd/consultas.ts`);
sair de `waiting` por `/internal/resume` é do AGR, e é a **única** escrita que
ele faz nesta tabela.

**E as duas NÃO eram uma partição — passaram a ser, pela emenda 1.42.** A
primeira versão desta secção dizia que já eram, e a revisão adversarial mediu que
não (`analises/ANALISE-35`, achado 1): o `ESTADOS_QUE_FECHAM` do
`hnd/estados.ts` era `["waiting", "degraded"]`, pelo que o `SQL_FECHAR` do HND
**também saía de `waiting`** e escrevia o mesmo `status = 'resumed'`. E a ordem
estava fixada em código — no `receber` do `hnd/provedor.ts` o `#fechar` corria
**antes** do `onHumanEvent`, que é o único sítio de onde `/internal/resume` pode
ser chamado.

No caminho feliz, portanto: um colega respondia, o HND escrevia `resumed`, o
pedido chegava ao AGR, o CAS dava zero linhas, a rota respondia 200 (o *no-op* do
§11.5 aplicado a um pedido legítimo) e o `Command(resume=…)` **nunca corria**. O
`interrupt()` ficava pendente, a varredura dos prazos não o encontrava (filtra
`waiting`) e a invariante da não-reentrada abria-se (o `handoff_a_espera` também
só conta `waiting`).

**Ficou resolvido, e não por este ticket.** A emenda **1.42** (dicionário §3.32)
escolhe a opção 1 da 1.41 — a que o `docs/tecnica/01` §11.4 desenha e que a
emenda 1.22 já tinha escrito ao dizer que «a coluna `resumed_at` nasce e ninguém
a escreve neste ticket [o KAM-019]» — e o **KAM-019** executou-a nos ficheiros
dele:

* o `ESTADOS_QUE_FECHAM` passa a `["degraded"]`. E são as **três** saídas de
  `waiting` e não só o `resolved`, porque as três retomam o grafo: esta rota com
  `resolved` e `cancelled`, a varredura dos prazos com `timeout`;
* o HND passa a chamar `POST /internal/resume` (`packages/core-ts/src/hnd/retoma.ts`),
  com as duas credenciais e o corpo de três campos deste §;
* o `resolver` ganha instrução própria do lado dele (`SQL_MARCAR_RESOLVER`, com
  `status = 'waiting'` no predicado e **antes** do pedido), porque o ADR-010
  mantém a identidade do agente fora deste serviço.

A partição passa a dizer-se em duas frases: **o HND nunca tira uma passagem de
`waiting`; o AGR nunca tira uma de `degraded`.** E passa a ter prova dos dois
lados — do nosso, `services/agr/tests/test_handoff.py::TestFronteiraComOHnd`, que
lê o `ESTADOS_QUE_FECHAM`, o cabeçalho, o caminho da rota e os três campos do
corpo **nos ficheiros TypeScript**. Essa classe existe por causa de uma medição:
a prova de que ninguém olhara para o segundo escritor foi um `grep` sem
resultados, e agora ele aparece.

### O `handoff_id` é irreversível, e isso obriga a uma verificação que nenhum documento pede

Ele é `sha256(thread_id:handoff_seq)`, pelo que do identificador **não** se lê o
*thread* de volta. Com só o `tenant_id` no predicado, um `handoff_id` do mesmo
*tenant* mas de **outro contacto** retomava: o CAS acertava e o
`Command(resume=…)` ia ao *thread* errado — isto é, a conversa de outra pessoa
retomada com o desfecho desta.

O CAS leva por isso o vínculo ao `contact_id` da conversa no predicado, por um
`EXISTS` sobre `conversations`. A alternativa era uma coluna `thread_id` na
`handoffs`, e com ela uma migração sobre uma tabela cujo DDL é do KAM-019: o
`EXISTS` compra a mesma propriedade sem ela. **Este ticket não cria migração
nenhuma**, e a cadeia fica na `0023`.

### A ordem das duas escritas, e a compensação

São duas escritas em dois sítios — o `status` na base e o `Command(resume=…)` no
*checkpointer* do LangGraph — e não há transacção que as cubra.

**O grafo resolve-se primeiro.** Sem grafo para a *thread*, que é o estado do
serviço enquanto a porta `grafos` levantar, o CAS escrevia `resumed` e a
compensação devolvia-o a `waiting`: duas escritas para nada e uma janela em que
a passagem aparecia retomada. Resolvido antes, a excepção sobe sem a base ser
tocada e a rota responde 503 com `Retry-After`.

**Depois o CAS, e só depois o `Command`.** É o que o §11 regra 3 manda, e é a
única ordem em que «dois pedidos concorrentes produzem 1 retoma» é verdade: com
o `Command` primeiro, dois *webhooks* duplicados retomavam o grafo **duas vezes**
e só depois disputavam uma linha.

**E a falha entre as duas compensa-se.** Se o `Command` levantar depois de o CAS
vencer, a linha fica em `resumed` com o grafo ainda interrompido: o *webhook*
repetido vê zero linhas, responde 200, e a passagem fica presa — invisível,
porque a varredura dos prazos só olha para `waiting`. O `SQL_REVERTER_RETOMA`
devolve a linha a `waiting` e a excepção sobe; o HND repete, o CAS vence outra
vez, e o `Command` tem outra oportunidade. É seguro porque tudo isto corre **sob
a tranca da conversa**, que quem chama toma antes.

**E essa frase só passou a ser verdade com o achado 2 da revisão.** Ela estava
escrita em cinco sítios e a tranca não a sustentava: os *advisory locks* de
sessão do PostgreSQL são **contados**, e a `TrancaDeConversas` tem **uma** ligação
por processo, pelo que a segunda tomada da mesma chave devolvia `true`. Dentro de
um processo a tranca da base não excluía nada — e os dois únicos chamadores para
quem ela é a única barreira (a rota de retoma e a varredura dos prazos) são os
dois que este ticket acrescentou; o turno estava coberto pelo dreno do
`turno.py`. Nem o `TrancaNaoLargadaError` o denunciava, porque o
`pg_advisory_unlock` devolve `true` nas duas tomadas.

Hoje a `TrancaDeConversas` tem um `asyncio.Lock` por `thread_id` à frente da ida
à base: a tranca da base continua a excluir entre processos e o trinco exclui
dentro de um. As duas *docstrings* da casa que se contradiziam sobre isto — a do
`trancas.py` e a do `turno.py` — passaram a dizer o mesmo, que é o que impede a
próxima pessoa de voltar a assumir a barreira errada.

**O resíduo tem nome e não tem ticket.** Se o `Command` **e** a compensação
falharem no mesmo pedido, a passagem fica presa: o `ReversaoFalhadaError` levanta
com a falha original encadeada, que é o que põe as duas no mesmo registo. Limpá-la
exige ler o estado do LangGraph, que esta varredura não faz.

### Zero linhas são duas respostas diferentes

O CAS não casa em dois casos que não se podem confundir: a passagem **já saiu**
de `waiting` — o *webhook* duplicado, 200 `repetido` — ou **não é deste
*thread***, e aí é uma recusa, 404 `recusado`. Um 200 ali dizia ao HND «tratado»
sobre um pedido que não tratámos, e um `thread_id` trocado passava a ser um erro
silencioso em vez de um alerta. E é 404 e não 403: «existe mas não é tua»
confirma a existência de uma passagem de outro *tenant*.

Quem os separa é uma segunda leitura, e corre **só** neste caminho — o que vence
paga uma instrução e não duas.

### Duas credenciais em `/internal/resume`, e provam coisas diferentes

O `x-kamba-interno` do KAM-025 prova «vem de dentro da rede»; o
`x-kamba-hnd-bot` prova «vem do *agent bot* **deste tenant**». Com só a primeira,
qualquer componente interno — o COM, o GWY, um *script* de operação — podia
retomar o *handoff* de qualquer *tenant*; com só a segunda, o segredo de um bot
passava a valer de fora da rede.

A segunda corre **depois** de o corpo ser lido, e não antes como a primeira,
porque o segredo é por bot — logo por *tenant* — e o *tenant* vem do prefixo do
`thread_id`. A propriedade que o `api_interna.py` promete não se perde: quem não
tem o `x-kamba-interno` continua a levar 401 **sem** o corpo ser lido. E corre
**antes** de se validar o vocabulário do `outcome`, senão um pedido sem segredo
válido descobria os três desfechos aceites pela diferença entre 400 e 401.

O segredo é o `chatwoot_bot_secret`, uma instância por conta, e **não é** o
`chatwoot_bot_token`: o *token* autentica as nossas chamadas **para** o Chatwoot
e o `secret` autentica os pedidos que chegam **de** lá. Dois alcances opostos no
mesmo bot. O verificador falha fechado em três sítios — sem cabeçalho, sem
`thread_id` com forma, e com o cofre a levantar —, porque uma configuração sem
segredo não pode tornar-se uma porta aberta.

### A varredura das 24 h, e porque não há agendador

O prazo é do `docs/tecnica/01` §11.4 regra 4 e **não é parâmetro de
calibração**: é a exigência da Messaging Policy que aquele parágrafo cita.

A listagem atravessa *tenants* — com contexto de um, a RLS devolvia só as
passagens desse — pelo que corre como `kamba_batch`, com o nome de *job*
`agr_handoff_prazos`; a retoma de cada passagem corre no caminho normal, com
contexto do *tenant* e sob a tranca da conversa. Não se funde a listagem com a
escrita num `UPDATE … RETURNING` em lote: um lote escrevia `timeout` em N
passagens antes de retomar grafo nenhum, e a primeira falha do `Command` deixava
as outras N-1 em `timeout` sem o cliente ter recebido mensagem nenhuma.

**A «uma só vez» não é deste módulo**, e vale dizer onde está: duas varreduras
ao mesmo tempo vêem a **mesma** passagem, e o que as separa é o CAS; e se o nó
correr duas vezes por outra via, a chave `{hid}:timeout` do Outbound fecha o
resto. Duas barreiras independentes, e é por isso que não há coluna de controlo
a manter.

**Não há agendador**, e é a mesma linha que o §7-A escreveu para a retenção do
`lg`: entrega-se o corpo da varredura, prova-se com relógio simulado, e quem a
chama a horas é o *scheduler* do EVT. Agendar sem agendador era escrever um que
ninguém pediu.

### O *drain* antes de uma mudança incompatível de grafo

É o item dos Detalhes Técnicos do bloco: «mudança incompatível de grafo exige
*drain* dos handoffs `waiting` ou compatibilidade dos nós pós-`interrupt`
durante N releases (`schema_version`)». Vale escrever o que ele quer dizer,
porque a frase é curta e o modo de falha não é óbvio.

Uma passagem em `waiting` é um `interrupt()` pendente num *checkpoint*, e o nó
que a vai retomar é o da **versão nova** do grafo — não o que a interrompeu. Se
esse nó deixou de existir, ou se o `handoff` do estado mudou de forma, a retoma
rebenta com a conversa a meio; e rebenta num caminho que nenhuma bateria vê,
porque o estado que a quebra foi escrito por outra versão do código.

O procedimento, e o dono é quem faz o *release*:

1. **antes** de publicar uma versão que mude os nós pós-`interrupt` ou a forma
   do `state.handoff`, ler `Prazos.a_espera(ligacao)` — o
   `SQL_PASSAGENS_A_ESPERA`, que atravessa *tenants* e corre como `kamba_batch`;
2. se der zero, publica-se;
3. se não der, há duas saídas e as duas são legítimas: **esperar** (as passagens
   saem de `waiting` por resposta humana ou pelo prazo de 24 h, pelo que o
   *drain* acaba sozinho em menos de um dia), ou **manter a compatibilidade** dos
   nós pós-`interrupt` durante o número de *releases* que cubra esse dia;
4. o `VERSAO_DO_GRAFO` (SemVer, `verticais/vendedor/arestas.py`) é onde a
   incompatibilidade se declara, e o `schema_version` do estado é onde uma
   mudança de forma se declara.

**Não há barreira automática, e isso é decisão.** Nada impede um *deploy* com
passagens à espera. Uma barreira precisava de saber se a mudança **é**
incompatível, e isso não se lê de um número de versão — o `VERSAO_DO_GRAFO` é
escrito à mão, e uma barreira que disparasse em toda a subida de versão
ensinava quem faz o *release* a desligá-la. O que há é o instrumento, o
procedimento, e três ensaios na suite da base a medir que ele conta as `waiting`
e não as outras quatro.

### O que fica por ligar, e o credor de cada um

| O que | Credor | O que acontece hoje |
|---|---|---|
| O cliente HTTP do `openHandoff` | KAM-019 | A porta por omissão levanta `HandoffIndisponivel`, que é a linha do `01` §11.5 para «Chatwoot indisponível»: a passagem degrada, o cliente recebe a mensagem de degradação, e o turno acaba sem excepção não tratada |
| A transição `conversation.mode = pausada` | KAM-018 | Porta chamada, implementação por ligar. A máquina de modos faz a transição **e** emite `conversation.mode_changed` na mesma transacção; reescrever esse par aqui dava um segundo dono e um modo a mudar **sem evento** |
| A notificação ao dono da degradação | KAM-115 | Não entra: o `01` §11.4 regra 2 proíbe usar o número da própria loja |
| A porta `grafos` da retoma | quem ligar o AgentRegistry | 503 com `Retry-After`, e **nada escrito**. São **duas** resoluções a ligar e não uma: a do turno recebe uma `InvocacaoDoAgente` e esta recebe um `thread_id`, porque a retoma não tem invocação |
| O *golden* de handoff (H7, ≥ 85%) | KAM-040 | Os três nós são artefactos comportamentais; o *eval-gate* mede-se lá |
| A limpeza de passagens em `resumed` sem *checkpoint* retomado | **ninguém** | O resíduo da compensação falhada, descrito acima. **Deixou de ser o estado de toda a passagem resolvida por um humano** — era-o enquanto os dois escritores se sobrepunham, e a emenda 1.42 fechou essa janela; o que resta é a falha dupla (o `Command` **e** a compensação a falharem no mesmo pedido), que é rara e que nenhuma varredura deste repositório vê |

### Uma regra de arquitectura estreitou-se, e não em silêncio

O *lint* `tool_schema` do `lint_arch` (*gates* 2 e 11) proibia **toda** a escrita
no `platform` fora da ToolLayer, e a regra que ele implementa — `docs/tecnica/02`
§6.1 e o ADR-015 — diz «a TLS é a única via de leitura e escrita dos
**agentes**». As duas davam o mesmo resultado só enquanto não houvesse uma única
escrita de plano de controlo no AGR; o CAS da retoma é a primeira.

A dispensa é uma lista de triplos `(ficheiro, tabela, verbo)` com **quatro**
critérios por entrada: a escrita não depende de saída de modelo nem de texto do
cliente; o que se escreve é plano de controlo do *runtime* e não dado de
negócio; o `tenant_id` está no predicado e a instrução corre dentro de
`tenant_guard.tx`; e o canon **nomeia** o AGR como dono. A chave é o triplo e
nunca o ficheiro — um `consultas.py` dispensado em bloco deixava passar um
`UPDATE platform.orders` na linha seguinte —, e há seis canários a medir os três
eixos: a mesma tabela noutro ficheiro, outra tabela no mesmo ficheiro, e **outro
verbo** na mesma tabela e no mesmo ficheiro.

**O verbo entrou pela revisão adversarial.** A primeira versão dispensava o par
e argumentava que o verbo era redundante porque «o `kamba_app` não tem `DELETE`
em `platform.handoffs`» — e a `0011` concede-lhe `GRANT SELECT, INSERT`, pelo
que um `INSERT` escrito no `consultas.py` passava o *lint* **e** corria na base.

É a mesma distinção que a *docstring* daquele *lint* já fazia pelo lado da
leitura: «o `conversa.py` lê a `conversations` e a `handoffs` para decidir se o
turno entra no grafo, e isso é a admissão do turno e não um agente a ler dados
de negócio».

### A sexta ligação, e as quatro métricas

A tomada da retoma é própria (`kamba-agr:handoff`, papel `kamba_app`) pela razão
das duas anteriores: o `kamba_core.tenant_guard` recusa uma segunda transacção
na mesma ligação, e uma retoma corre **ao mesmo tempo** que turnos de outras
conversas — a tranca serializa por `thread_id`, não o processo. A varredura dos
prazos **não** usa nenhuma função deste módulo: recebe a ligação de quem a
chama, para que o processo do AGR não ganhe um terceiro papel por causa de um
trabalho que corre fora de qualquer pedido.

As quatro métricas estão no §6. **Nenhuma leva `tenant_id`**, e o critério 8 pede
a métrica de retoma «por *tenant*»: a desagregação faz-se nas **colunas** e
lê-se por consulta, porque uma série por *tenant* explode a cardinalidade e
re-identifica (`OBS-I`) — e a chamada levantaria `EtiquetaInvalida` pela
gramática de qualquer maneira. É a mesma resolução das dívidas 54 e das emendas
1.38 e 1.39.

## 8. O que este documento não decide

A topologia e as réplicas (`docs/tecnica/09`, KAM-088), a aplicação da
*allowlist* de saída na rede (KAM-076), a calibração dos quatro tectos e o
`lockDuration` (KAM-084), a agregação de métricas (KAM-080), e tudo o que a
tabela do §1 atribui a outro ticket.

E, desde o KAM-037, **duas leituras que são do fundador e não deste documento**: o
que acontece com o modo determinístico e a política `concierge` activos ao mesmo
tempo, e se a pesquisa de catálogo deve ou não ser servida em modo degradado. As
duas estão devolvidas na secção de verificação do bloco do KAM-037, com a leitura
implementada e a razão.

---

## 7-H. A subscrição de eventos: as verticais acordam por evento (KAM-038)

O AGR deixou de só responder a mensagens. «As verticais não se chamam entre si:
subscrevem eventos do EVT» (ADR-009), e o que cada uma subscreve está no seu
`registry/<id>.yaml`; este ticket liga essas linhas a consumidores.

```
evt.<consumer>.p<0..15>  (BullMQ, casca em TypeScript — KAM-005/KAM-006)
        │
        └── POST /internal/event   {event_id, tenant_id, envelope, tentativas}
                │
                ├── ler_envelope          14 campos, P2 recusada
                ├── confrontar ponteiros  divergem -> DLQ sem envelope
                ├── rota (tipo, versao)   sem rota -> DLQ com alerta
                ├── validar_payload       contrato fechado (KAM-007)
                ├── entitlement           qual vertical consome
                └── por consumidor:
                      contacto (fora da tranca)
                      async with trancas.tomar(thread_id):
                          ler quem tem a palavra
                          consumir(..., efeito)   marca + efeito, uma transaccao
```

### A rota é a terceira, e o 503 dela não é um erro

`/internal/event` junta-se ao `/internal/turn` (KAM-025) e ao `/internal/resume`
(KAM-034), com o mesmo `x-kamba-interno`. Os códigos dizem à fila o que fazer, e
é só isso que eles dizem:

| Código | Significa | O que a fila faz |
|---|---|---|
| 200 | tratado — **inclui** o que foi para a DLQ | completa o *job* |
| 400 | o corpo não é uma entrega | não vale a pena repetir |
| 503 + `Retry-After` | volta | re-enfileira com o atraso |

**Um evento que foi para a DLQ responde 200**, e isso enganaria quem o lesse ao
contrário: um 500 ali punha o BullMQ a repetir o que já está registado e a
tentar abrir a mesma entrada seis vezes. «Tratado» não quer dizer «correu bem».

### Onde corre o efeito, e porque é dentro da transacção

O §6.3 manda «aplicar efeitos na BD (mesma transacção); COMMIT; efeitos
externos: tabela de acções com `Idempotency-Key`». A notificação é um efeito
externo — mas o Outbound é uma **fila** e não uma chamada à Meta (quem fala com
a Meta é o trabalhador dele), pelo que enfileirar é curto e cabe na transacção.
Está lá de propósito, e o que isso compra é simétrico:

* a notificação falha → `ROLLBACK` leva a marca com ela → a re-entrega tenta
  outra vez. **Não há marca sem efeito** — e «falha» inclui o `sem_template`,
  que **levanta**: a primeira versão contava-o e seguia, e deixava uma linha em
  `events_consumed` com zero mensagens no único caminho que hoje corre. Achado
  da revisão adversarial.
* o `COMMIT` falha depois de a notificação passar → a re-entrega repete-a com a
  **mesma** chave `consumer:event_id:accao`, e a `UNIQUE (tenant_id,
  idempotency_key)` de `outbound_messages` não enfileira nada. **Não há efeito
  duplicado.**

A alternativa (efeito depois do `COMMIT`) deixava a primeira janela aberta. É a
janela que a `evt_acoes` da revisão `0005` existe para fechar, e ela continua
**sem escritor** — credor: KAM-006. Fecha-se por desenho em vez de por tabela, e
isso tem um limite dito: quem vier a precisar de um efeito que **não** caiba numa
transacção precisa daquela tabela.

### A sétima ligação, e porque não se partilha

`kamba-agr:eventos`, papel `kamba_app`, transaccional. É a sétima tomada do
processo (leitura, tranca, checkpoint, tools, LLM, handoff, eventos), e a razão é
a das três anteriores: o `kamba_core.tenant_guard` recusa uma segunda transacção
na mesma ligação, e um evento é consumido **ao mesmo tempo** que turnos de outras
conversas.

**O `consumir` do KAM-006 manda `BEGIN`, `COMMIT` e `ROLLBACK` como instruções**,
porque do lado TypeScript o cliente é um `pg` em bruto. O `pg8000` em modo
transaccional abre a transacção sozinho na primeira instrução, e um `BEGIN`
explícito dentro de uma transacção aberta é um aviso do servidor e mais nada — o
`COMMIT` seguinte fechava a transacção de fora. Por isso o `LigacaoDoConsumo`
traduz as três na API do condutor; e uma palavra de controlo de transacção que
ele **não** conheça (`SAVEPOINT`, `START TRANSACTION`) **levanta**, em vez de
passar: deixá-la passar punha a marca e o efeito em transacções diferentes sem
dar erro.

### Quem consome é a vertical que o *tenant* tem activa

A `evt_subscricoes` é configuração **global** de entrega — por `consumer`, não
por *tenant* (revisão `0004`) — e os dois `registry/*.yaml` subscrevem os
**mesmos** dois eventos de pagamento. Sem uma leitura de entitlement, um
`payment.confirmed` de um *tenant* que só tem o Vendedor era consumido também
pelo consumidor de Serviços: duas chaves de idempotência diferentes, e **duas
mensagens ao mesmo cliente sobre o mesmo pagamento**.

A leitura é a **mesma** do turno de conversa — o `check_entitlement` do KAM-009,
que falha fechada.

**Mas isso por si não chega, e a primeira versão achava que chegava.** Um
*tenant* com as duas verticais activas é o do *gate* da Fase 0 (ADR-012,
KAM-108: o Vendedor produz e os Serviços consomem), e aí há **dois**
consumidores por desenho. O que impede os dois de mandarem a **mesma** mensagem
é o *handler* ser por `(vertical, tipo)`: o `payment.confirmed` fala com o
cliente pelo Vendedor, e nos Serviços a acção é outra — «confirma uma marcação
com sinal» (`03` §12) — que o KAM-047 ainda não escreveu, e que o desfecho
`sem_accao` nomeia com o credor. Com a chave no tipo, o cliente recebia duas
mensagens idênticas sobre o mesmo pagamento. Achado da revisão adversarial.

### O turno por evento não invoca o grafo, e isso está decidido

O critério 5 pede três propriedades — `turn_id = event_id`, sob a tranca da
conversa, e não correr com um humano com a palavra — e nenhuma é «invoca o
grafo». O `ingest` do grafo do Vendedor pressupõe uma mensagem do cliente na
janela `messages` (§7-F), e dar-lhe um envelope era mudar o nó de entrada de um
grafo cujo dono é outro ticket. O que corre sob a tranca é um *handler*
determinístico: sem modelo no caminho, logo sem prosa a validar pelo ADR-007 —
e os textos **não levam número nenhum**, nem valor, nem data, nem quantidade.

A tranca é a **mesma** `TrancaDeConversas`, com a mesma chave (`thread_id`), pelo
que um turno por evento e um turno de conversa da mesma pessoa serializam entre
si. Um aviso ao dono (`stock.low`) **não** toma tranca: não há conversa, não há
`thread_id`, e não há nada para serializar.

### Duas portas para o cliente e para o dono, e não uma com um argumento

É o que torna «a notificação ao dono nunca usa o número da própria loja» (`01`
§11.4 regra 2) uma propriedade do **código** e não uma intenção: a
`PortaDeAvisoAoDono` não leva `contact_id` nem `conversation_id`, pelo que não há
por onde cair no canal do cliente. Há um ensaio que lhe põe um espião na porta do
Outbound e exige **zero** chamadas.

As duas acções têm chaves diferentes — `consumer:event_id:notificar_cliente` e
`...:notificar_dono` — precisamente para que a segunda não seja engolida como
repetição da primeira. E a chave **não leva o número da tentativa**: com ele, cada
volta dava chave nova, e com ela uma mensagem nova.

### O que ainda não existe, e o que o AGR faz enquanto não existir

| Porta | Por omissão | Credor |
|---|---|---|
| Outbound (janela/*template*) | devolve `sem_template`: não envia, alerta, e **a entrega vai para a DLQ** | KAM-015, e o catálogo de *templates* é KAM-024 |
| HND (dono e agente) | não faz nada; a decisão de canal é o que este ticket entrega | KAM-019, KAM-115 |
| `(agregado) -> contact_id` | **levanta** | KAM-041 (`order`), KAM-047 (`booking`) |

A terceira é a que se nota em produção, e vale dizê-lo por extenso: **dos seis
tipos subscritos, só o `booking.created` traz `contact_id` no contrato**
(KAM-007 publicou os outros cinco sem dizer a quem se fala, apesar de os
*Detalhes Técnicos* do bloco afirmarem o contrário). Enquanto ninguém resolver o
contacto, um `payment.confirmed` esgota a escada do §6.4 e abre entrada na DLQ —
que é **Sev1**, e a classificação está certa: «cliente que pagou sem
confirmação» é exactamente o que acontece.

E o `correlacao_id` do envelope **não serve de atalho**: o §4 descreve-o como
«Conversa **ou** pedido», e um campo que pode ser duas coisas não endereça
ninguém.

### Quatro métricas, e a primeira medida com etiqueta da casa

```
agr_evt_consumidos_total{outcome}      counter  entregas, por desfecho
agr_evt_dlq_total{motivo}              counter  entradas abertas na DLQ. Alerta
agr_evt_notificacoes_total{outcome}    counter  notificacoes, por desfecho
agr_evt_lag_ms{consumer}               gauge    lag do ultimo evento, por consumidor
```

O `agr_evt_lag_ms` é a **primeira medida com etiqueta** do repositório, e entrou
por necessidade: o DoD pede «*lag* de consumo **por consumidor**», e dois
consumidores a escrever na mesma medida sem eixo davam um valor que é o do último
e não o de nenhum. As regras da etiqueta são as do `contar` — lista fechada e a
mesma gramática —, para que um `tenant_id` caia pela forma, como lá.

O *lag* mede-se do **`ocorrido_em`** e não do `registado_em`: o primeiro é quando
o facto aconteceu, que é o que o cliente espera, e o segundo esconde o atraso até
à transacção que o gravou. Nunca é negativo — o `ocorrido_em` é o relógio do
produtor e pode estar à frente do nosso —, e só se mede no `aplicado`: o *lag* de
um duplicado mede o tempo até uma entrega que não fez nada.

**O `fora_de_ordem` do KAM-006 não é motivo de DLQ aqui**, e não é esquecimento:
ele nasce dentro da pré-condição de estado, que este consumidor não corre. Ver
abaixo. Os motivos que há são cinco — `envelope_invalido`, `tipo_desconhecido`,
`versao_desconhecida`, `sem_template` e `tentativas_esgotadas` —, e só o último
vem **depois** da escada do §6.4: os outros quatro não mudam entre tentativas, e
gastar treze minutos para chegar à mesma conclusão era adiar o alerta.

### `aplica_transicao`: o AGR é informado, não é quem decide

O `ESTADO_PRETENDIDO` do KAM-006 põe os dois eventos de pagamento a exigir
pré-condição de estado, e a nota dele diz porquê: «estão aqui os eventos cujo
consumo **aplica** a transição». O AGR não aplica transição nenhuma — quem
transita a encomenda é o COM (`03` §6) e quem decide o pagamento é o PAY
(ADR-013).

Sem a distinção, o consumo de `payment.confirmed` no AGR levantava
`MaquinaEmFalta` ou, com uma máquina sobre a tabela de encomendas que o KAM-041
ainda não escreveu, adiava seis vezes e mandava para a DLQ **todos** os
pagamentos confirmados. A opção é do lado Python, a omissão é `true`, e nenhum
consumidor existente muda de comportamento. Dicionário §3.33.

### A prioridade dos pagamentos é da admissão, e é **acima** do tecto

A regra 2 do §15.2 tem duas metades e só uma estava. Um evento `payment.*` entra
com a reserva `AGR_RESERVA_DE_PAGAMENTO` (*proposta*, 1) acima do
`AGR_TECTO_POR_TENANT` e **não dentro dele**: descontá-la do tecto baixava a
concorrência de conversa de 3 para 2 e mudava o critério 5 do KAM-025, que foi
medido com 3. O anti-vizinho-ruidoso sobrevive porque o lugar extra só serve
eventos de pagamento, cujo ritmo é do facilitador e não do cliente.

### A escrita na `events_dlq`, e porque passa pelo *lint*

O *lint* de arquitectura do *gate* 2 proíbe escrita no `platform` fora de
`tls/`, porque «a TLS é a única via de leitura e escrita dos **agentes**» (§6.1,
ADR-015). A `events_dlq` entra na lista `ESCRITAS_DO_PLANO_DE_CONTROLO` com as
quatro condições dela, e **só o `insert`**: fechar, descartar e reprocessar são
do `kamba_batch` e exigem dois aprovadores num `payment.*`. Um `UPDATE` escrito
no AGR punha quem consome a poder fechar a sua própria entrada, que é o que a
regra dos dois existe para impedir.

A `events_consumed` não precisa de entrada: quem lhe escreve é o
`kamba_core.eventos.consumir`, que vive em `libs/` — e o *lint* só varre
`services/*/src/**`. **É um limite do *lint* e fica dito**: uma escrita no
`platform` a partir de `libs/` não é verificada por ele.

### O que estas baterias podem dizer, e o que não

`services/agr/tests/test_eventos.py` corre **sem** base, Redis ou Outbound, com
os clientes injectados: é ela que prova o roteamento, a idempotência da decisão,
a tranca, as duas portas e as métricas. `db/tests_agr/test_eventos.py` corre
contra PostgreSQL e prova o que só a base pode dizer: que o SQL **corre**, que o
`ON CONFLICT` é atómico entre **sessões**, que o índice parcial
`events_dlq_aberta_uq` deixa a reentrada idempotente só entre as abertas, que o
`ROLLBACK` leva a marca com ele, e que a RLS esconde a conversa de A do contexto
de B.

**E tudo o que toca a base vai a um executor, com o cancelamento à espera da
*thread*.** O `asyncio.to_thread` não cancela nada: um `CancelledError` no
`await` largava a exclusiva com a *thread* ainda a meio do protocolo do
`pg8000`, e a entrega seguinte usava a **mesma** tomada em paralelo. É o defeito
que o `checkpointer.py` (§7-A) já tinha pago e escrito, e este módulo copiou a
forma errada nos três sítios antes de a revisão adversarial o medir. O padrão é
o de lá: `ensure_future` + `shield` + `await wait([tarefa])`.

**Nenhuma das duas prova o BullMQ.** As garantias de entrega dele são **NÃO
VERIFICADAS** (L6) e não há fila em bateria nenhuma; o que cobre o risco são
*handlers* idempotentes, a DLQ e o reprocessamento. E o p99 de *lag* ≤ 10 s
mede-se em *staging*: o ensaio de carga leve mede o caminho de decisão, que não é
o sistema.

## 7-I. O modo determinístico: degradar, nunca calar (KAM-037)

«Falha de LLM, canal ou pagamento tem *fallback* determinístico ou fila; o
utilizador nunca fica sem resposta» (`tecnica/00`, princípio 12). Este ticket
entrega a metade do LLM: um sub-grafo sem modelo, o detector que decide quando se
entra nele, e o `agr_degraded_turns_total`.

### O que se mediu antes de escrever, e mudou o desenho

**O grafo do Vendedor já era quase todo determinístico.** O bloco manda «só
`classify` e `compose` mudam para versões sem LLM», e medido: o `compose` **não
chama modelo nenhum** — monta blocos a partir dos *facts* e o *renderer*
preenche-os —, e o único sítio por onde o LLM entra é o `deps.classificador` do
`classify` (§15.1), que ainda está **por ligar**. Logo metade da frase do bloco
estava satisfeita antes deste ticket, e a outra metade é uma condição no
`classify`.

O que **não** existia era o menu. É por isso que o sub-grafo tem **um** nó novo e
não três: o `order_status`, o `tools_info`, o `confirm_gate`, o `create_order` e o
`handoff_prepare` servem o modo degradado como estão, e é o que «reutiliza o grafo
normal» quer dizer na prática.

### Sub-grafo **do** grafo, e não um segundo grafo compilado

«Sub-grafo LangGraph» lê-se como nós e arestas alcançáveis só em modo degradado,
na mesma tabela de `arestas.py` e com `fonte: KAM-037`. Um segundo `build_graph`
foi pesado e recusado, e a razão é o *checkpointer*: os dois grafos partilham o
`thread_id` (§12), pelo que invocar o segundo depois de o primeiro ter escrito um
*checkpoint* parcial punha dois esquemas de canais sobre o mesmo *thread* — e a
degradação a meio de um turno (o `ErroDeLlm` que o `classify` apanha) obrigava
exactamente a isso. Com os nós dentro do grafo, a degradação a meio é **uma
aresta** e o turno responde em **um** turno, que é o critério 1.

```text
classify --(degradado e a intenção não é servida)--> degraded_menu --> validate
         --(confirmar)---------------------------> confirm_gate --> create_order
         --(encomenda, pagamento_estado)---------> order_status
         --(info_loja)---------------------------> tools_info
         --(humano)------------------------------> handoff_prepare
```

### O que degrada, e o que explicitamente não degrada

| Motivo | Quando | Onde se decide |
|---|---|---|
| `timeout` | o `kamba-chat` passou o tecto de 20 s | `classify`, a apanhar o `ErroDeLlm` |
| `http_429` | o fornecedor recusou por ritmo | idem, pelo `estado_http` |
| `budget` | a chave virtual esgotou-se | idem |
| `breaker` | três falhas consecutivas, pausa de 30 s | `ingest`, antes de o turno correr |
| `backpressure` | *tenant* no tecto **e** fila acima do limiar | idem |

**`http_429` e não `429`**, e a razão é uma barreira que já existia: a gramática de
etiqueta é `^[a-z][a-z0-9_]{1,62}$` e um valor que comece por dígito **levanta**.
O critério escreve o número cru; o nome canónico é `http_429` (dicionário §3.35), e
há ensaio que mede as duas metades — que os cinco motivos passam, e que o `429` cru
não passava.

**E Postgres ou *checkpointer* indisponível não é nada disto.** O §14 dá-lhe linha
própria — «o turno não corre; a mensagem permanece na fila; alerta crítico» — e o
detector impõe-no **por tipo**: o `motivo_do_erro` levanta `TypeError` com qualquer
coisa que não seja um `ErroDeLlm`, e não há `except Exception` no módulo. Degradar
ali era responder sem carrinho, sem `stage` e sem janela de mensagens. Há ensaio
que corre um turno com a base a levantar e mede **zero** mensagens enviadas e zero
turnos contados como degradados.

### Dois disjuntores para o mesmo backend, e porque é que este não é o que o
### `llm/cliente.py` recusou

O cabeçalho do `llm/cliente.py` recusa «o cliente a fazer o *fallback*», porque
isso punha-o a reimplementar a contagem de falhas e o *cooldown* do router. A
recusa é sobre **escolher fornecedor**, e continua de pé: nada no detector escolhe
fornecedor nenhum. O que este disjuntor decide é outra pergunta — **vale a pena
chamar o LLM neste turno?** — e o proxy não a pode responder: em *cooldown*, ele
responde depressa e com erro, e três turnos a pagar esse erro são três clientes à
espera por nada.

Os limiares são os **do proxy**, e foram **medidos e não copiados** do bloco, que
os dava como «a validar na versão fixada»: `allowed_fails: 3` e `cooldown_time: 30`
em `llm/litellm.config.yaml` e em `llm/aliases.yaml`, CONFIRMADOS pelo KAM-030
contra a imagem fixada. **Não divergem**, e há ensaio que lê os dois ficheiros e
falha se divergirem — o que torna a afirmação verificável em vez de afirmada.

### O alerta, o `tenant`, e a caixa que fica parcial

> Mais de **5%** dos turnos de um *tenant* em **15 minutos**, com um mínimo de
> **vinte** turnos na janela.

Os dois primeiros números são do critério 6, que escreve «limiar *proposta*»; o
mínimo é nosso, porque sem ele um único turno degradado dá 100%. A janela é em
memória e **por processo**, e isso fica dito: duas réplicas têm duas janelas.

**O denominador precisa dos turnos normais**, e por isso o `ingest` conta **todos**
os turnos — com motivo `None` quando não há. Um turno pode ser registado duas
vezes (o `ingest` com o motivo prévio e o `classify` quando o modelo falha a
meio), e o que impede o denominador de inflacionar é o `turn_id`: a segunda chamada
**promove** a entrada da primeira. Sem chave, as duas valiam como dois turnos — e
«a última entrada» não serve, porque com o tecto de concorrência a três um *tenant*
tem até três turnos em voo e a promoção ia ao turno do lado.

Onde é que o alerta dispara: **em nenhum sítio automático**. Não há sistema de
alertas neste repositório, medido, e a agregação contínua é o KAM-080. O
`registar_turno` devolve `True` quando o limiar passa; o resto está no runbook
(`runbooks/degradacao-do-agr.md`), que é a forma que o KAM-027 e o KAM-114 já
usaram para os seus alertas.

### O modo passa pelo validador, e o concierge passa à frente dele

**Nada sai do modo degradado sem o `validate` o ver.** O `degraded_menu` escreve
`draft.blocos` e a aresta leva-o ao `validate`, como o `compose` — ao contrário das
respostas estáticas das arestas da linha 34, que passam ao lado. É o critério 5, e
o custo é que os textos do modo têm de atravessar o `renderizar`: sem dígitos, e
sem duas palavras de número seguidas, que o extractor conta como número. Há ensaio
que renderiza **todos** os textos do módulo.

**E com a política `concierge` activa, a resposta determinística vai a aprovação.**
O KAM-114 intercepta no `send`, que é por onde as cinco arestas de saída passam, e
o modo degradado passa por lá como qualquer outro caminho — pelo que a barreira
«sem decisão humana não sai mensagem» aplica-se também aqui, **sem código novo**.
Isto é uma leitura: nenhum dos dois blocos prevê os dois em vigor, as outras duas
leituras possíveis retiram uma barreira, e a decisão está devolvida ao fundador.

A consequência operacional fica escrita onde dói: num *tenant* concierge, o LLM em
baixo **não** faz chegar nada ao cliente até um operador aprovar. É também por isso
que o «≤ 1 turno» do critério 1 se mede com a política **desligada**, que é o caso
de todos os *tenants* fora do Piloto concierge.

### O que o modo não serve, e porquê

A **pesquisa de catálogo** fica fora, pela letra do critério 2, que enumera o que o
modo serve e não a inclui. É uma leitura com custo declarado: o IDX não é o LLM e
não está em baixo quando o modelo está. A **construção de um carrinho** fica fora
pela mesma via (o critério 3 nomeia o toque num carrinho **já construído**). E a
**referência de pagamento já emitida** serve-se em espécie e não em detalhe — uma
referência é uma cadeia opaca com dígitos e nenhum dos cinco blocos do §9.1 a leva:
é a **dívida 124**, credor **KAM-032**, que já nomeia este caso por extenso.

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
| 1.8 | 2026-10-27 | KAM-031 | §7-F: o grafo do Vendedor — a tabela de arestas como fonte (42 arestas em 39 linhas), os quatro campos de estado da emenda 1.40 e porque nenhum era dispensavel, a assimetria de tempo de vida entre o `cart` e os `facts` que produziu o primeiro defeito, as tres respostas que os cinco blocos do §9.1 nao conseguem levar, o que e Fase 0 em cada no com o credor, e porque e que as cinco tools ficam `declaradas` com o credor a mudar para quem liga o backend. **E o que a revisao adversarial mudou**: os tres *must fix* de dinheiro (a quantidade inventada, o cancelamento escrito, a confirmacao nao exercida), o recorte da janela que matava a conversa, e as duas licoes de escrita. |
| 1.9 | 2026-10-27 | KAM-034 | §7-G: o *handoff* idempotente e a retoma por *compare-and-set* — o par de nós que o KAM-031 deixou e a porta que faltava, a `HandoffIndisponivel` a mudar de casa (e porque a identidade da classe era a razão), os **dois** escritores da `platform.handoffs` em duas linguagens com a fronteira escrita, a ordem das duas escritas e a compensação, as duas credenciais de `/internal/resume` e o que cada uma prova, e a varredura das 24 h sem agendador. **Três coisas que saíram de escrever código contra o canon:** o `handoff_id` é irreversível, pelo que o `tenant_id` no predicado não chega — um `handoff_id` de **outro contacto do mesmo tenant** retomava o *thread* errado, e o CAS passou a levar o vínculo ao `contact_id`; o grafo resolve-se **antes** do CAS, senão uma rota sem grafo escrevia e compensava para nada; e o `resumed_at` escreve-se nos **quatro** desfechos, contra o `SQL_FECHAR` do HND, porque as quatro saídas de `waiting` por esta rota retomam o grafo. **E uma regra de arquitectura estreitou-se, com canários:** o *lint* do `tool_schema` proibia toda a escrita no `platform` fora da ToolLayer e a regra diz «dos **agentes**» — passa a haver uma lista de pares `(ficheiro, tabela)` com quatro critérios por entrada. O que fica por ligar tem credor numa tabela própria, e a limpeza de passagens em `resumed` sem *checkpoint* retomado **não tem ticket**. |
| 1.10 | 2026-10-27 | KAM-034 | **Revisao adversarial** (`analises/ANALISE-35`): REPROVADO, 3 *must fix* e 6 *should fix*. A classe que ela nomeia e nova nesta serie — **a propriedade esta medida, e o duplo que a mede e mais forte do que a peca que ele substitui** —, e os tres *must fix* sao todos dessa forma. Duas barreiras que este ticket afirmava em cinco e em tres sitios nao existiam: **a tranca da conversa nao excluia dentro do processo** (os *advisory locks* de sessao sao contados e a `TrancaDeConversas` tem uma ligacao por processo; os dois unicos chamadores que nao passam pelo dreno do `turno.py` sao os dois que este ticket acrescentou, e nem o `TrancaNaoLargadaError` o denunciava), e **a politica AST do criterio 2 evadia-se com uma linha, por seis formas** (o efeito na posicao de argumento, um tuplo, o `contextlib.suppress`, uma compreensao, o `except*` e o `async with`). As duas estao corrigidas, com ensaio contra a peca **real** e com mutacao; as duas *docstrings* da casa que se contradiziam sobre a tranca passaram a dizer o mesmo. **O terceiro nao se corrigiu, e e por isso que o criterio 3 ficou `parcial`:** a `platform.handoffs` tem dois escritores para `waiting -> resumed` e o do HND corre **primeiro** (o `#fechar` do `receber` antes do `onHumanEvent`), pelo que no caminho feliz o CAS da zero linhas e o `Command(resume=...)` nunca corre. A correccao e TypeScript nos ficheiros do KAM-019 e a emenda 1.22 ja tinha escrito que ele nao escreve esta transicao: e uma decisao de canon, e esta devolvida com as duas saidas no §3.32. **E tentou-se um paliativo e retirou-se** — um desfecho `conflito` proprio dispara tambem no *webhook* duplicado legitimo, pelo que nao separa nada. Dos *should fix*: a captura da tabela no *lint* tinha introduzido uma **regressao** (`platform."orders"` deixou de morder, num gate de bloqueio e para todas as tabelas), a dispensa passou a ser por **verbo** (a `0011` concede `INSERT` ao `kamba_app`, pelo que o argumento escrito era metade falso), o `partes` passou a exigir a forma **canonica** de UUID (um `contact_id` invalido dava `22P02`, 500, e o HND a repetir), a `MSG_ALTERNATIVAS` ganhou ensaio de **conteudo** (o que havia comparava-a com a propria constante), e o ramo degradado passou a subir o `handoff_seq` (sem isso o *handoff* seguinte reusava o `hid` de uma passagem que o HND pode ter deixado criada). |
| 1.11 | 2026-10-27 | KAM-019 | **A fronteira dos dois escritores ficou decidida, e não foi aqui.** A emenda **1.42** do dicionário (§3.32) escolhe a opção 1 da 1.41: o `ESTADOS_QUE_FECHAM` do HND passa a `["degraded"]` — as **três** saídas de `waiting` e não só o `resolved`, porque as três retomam o grafo —, o HND passa a chamar `POST /internal/resume` e o `resolver` ganha instrução própria do lado dele (o ADR-010 mantém a identidade do agente fora deste serviço). O código deste serviço **não muda**; o que muda aqui é a §7-G, que deixa de descrever uma sobreposição, e a tabela do que fica por ligar, que perde duas linhas. A paridade passa a ter ensaio nesta bateria (`TestFronteiraComOHnd`, nove asserções que lêem os ficheiros TypeScript), e ela existe porque a prova de que ninguém olhara para o segundo escritor foi um `grep` sem resultados. **E corrige-se um número da 1.9:** o `resumed_at` escreve-se nos **três** desfechos e não nos quatro — o `DESFECHOS` do `handoff/maquina.py` tem três valores. |
| 1.12 | 2026-10-27 | KAM-038 | §7-H: a subscricao de eventos — a rota `/internal/event` e os tres codigos que ela da a fila, o efeito **dentro** da transaccao do consumo e o que isso compra nos dois sentidos, a setima ligacao e a traducao do `BEGIN`/`COMMIT`/`ROLLBACK` para o condutor, o *handler* por `(vertical, tipo)` e o `sem_accao`, as duas portas que nao partilham caminho, as quatro metricas com a primeira **medida com etiqueta** da casa, o `aplica_transicao` do KAM-006, a reserva de prioridade acima do tecto, e a entrada da `events_dlq` no *lint* de arquitectura com so o `insert`. Os codigos de saida passam a oito (o `7` do KAM-030 tambem faltava nesta tabela). **A revisao adversarial reprovou o ticket com nove achados**, e os tres que mudaram desenho estao escritos na seccao: duas mensagens identicas ao mesmo cliente, o `sem_template` a marcar sem enviar, e o cancelamento a nao esperar pela *thread* — este ultimo e o defeito que o §7-A ja tinha pago. | Equipa KAMBA |
| 1.13 | 2026-10-29 | KAM-037 | §7-I: o modo determinístico — o sub-grafo **do** grafo e não um segundo compilado (e porque é o *checkpointer* que decide isso), os cinco motivos e o `429` que teve de virar `http_429` pela gramática de etiqueta, o disjuntor do LLM com os limiares **medidos** na configuração do proxy em vez de copiados do bloco, a barreira que não se simplifica (Postgres em baixo **não** é degradação, imposta por tipo e medida a correr), o `turn_id` que impede o denominador do alerta de inflacionar com turnos em voo, e a interacção com o `concierge` que nenhum dos dois blocos previa — devolvida ao fundador com a leitura implementada. O §6 fica corrigido: o `agr_degraded_turns_total` **passou a existir**, e a frase que dizia o contrário era verdadeira até este ticket |

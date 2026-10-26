# EPIC-03 — Agent Runtime e Verticais

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Agent Runtime e Verticais |
| Versão | 1.7 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/02_Agent_Runtime_Verticais.md`, `../docs/tecnica/00_Arquitectura_Solucao.md` |
| Documentos relacionados | `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-04_Core_Comercio.md` |

---

## 1. Visão do Epic

O **Agent Runtime (AGR)** é o serviço que transforma uma mensagem já resolvida pelo CHR numa resposta correcta, auditável e barata, sem que o modelo possa escrever fora do seu tenant nem inventar um número. É um processo Python com workers assíncronos que usa o **LangGraph como biblioteca MIT** (nunca o Server, ADR-002), um checkpointer Postgres próprio, um **AgentRegistry** que trata verticais como configuração, uma **ToolLayer** (TLS) que é a única via de leitura e escrita dos agentes, um **LLM gateway** (LiteLLM fixado por digest) e um **validador de citação** que impede que preços, totais, stock, datas e horas cheguem ao cliente sem serem *facts* devolvidos por uma tool (ADR-007). O modelo propõe, o código dispõe: `tenant_id` vem do estado, a escrita exige botão confirmado e chave de idempotência, e nenhum nó altera o estado de pagamento (ADR-013).

O epic existe porque é onde as quatro fundações não-negociáveis do produto se tornam verificáveis por teste: mediação total pelo runtime, números só de tools, dinheiro só por evento, e verticais como configuração validadas pela **regra de dois** (Vendedor + Serviços, ADR-012). Dá corpo aos dois grafos do Piloto (tabela de arestas de `../docs/tecnica/02` §7.3 para o Vendedor; diagrama de §8.1 para os Serviços), ao padrão de dois nós para `interrupt()` idempotente (handoff), à voz com fallback a humano, ao modo determinístico sem LLM e ao dataset *golden* PT-AO como gate de deploy. Piloto = **só Fluxo A**: a persona `assistente` (Fluxo B) não é registada em produção (ADR-011).

Concretiza ADR-002, ADR-005, ADR-007, ADR-009, ADR-010, ADR-012, ADR-013 e ADR-015, com adjacência a ADR-008 (chamadas a LLM/STT no estrangeiro são transferências até parecer em contrário) e ADR-018 (golden sintético, custo por tenant). São **17 tickets**: 11 na **Fase 0** (esqueleto andante: KAM-025 a KAM-032, KAM-035, KAM-038, KAM-039) e 5 na **Fase 1** (KAM-033, KAM-034, KAM-036, KAM-037, KAM-040). Qualidade em português de Angola, latência real dos modelos e WER dos STT são **NÃO VERIFICADOS** (`../docs/tecnica/02` §19, L1–L3): medem-se no golden e no staging, não se assumem.

---

## 2. Critérios de Saída do Epic

- [ ] O grafo do Vendedor compilado passa o teste de contrato: as 39 arestas de `../docs/tecnica/02` §7.3 existem, 0 nós sem aresta de saída, 0 nós inalcançáveis, o ciclo `compose↔validate` é limitado por `citation_retries`.
- [ ] Duplo toque no botão `confirm:{cart_id}` (e 50 execuções concorrentes) produz **exactamente 1** pedido; recompra com novo `cart_id` produz 2.
- [ ] 0 preços, totais, `sku`, datas ou horas divergentes dos *facts* no conjunto adversarial do validador (≥ 200 casos, proposta) e no golden; cobertura de linhas do validador ≥ 90%.
- [ ] Suite de isolamento cruzada (X-02 tools, X-09 ≥ 30 prompts PT-AO) com 0 canários de outro tenant ou contacto em respostas, erros, logs e traces.
- [ ] Lockfile e imagem sem `langgraph-api` nem `langgraph-runtime-inmem`; 0 chamadas a `beacon.langchain.com` com egress bloqueado; LiteLLM ≥ 1.83.0 por digest com cosign verificado.
- [ ] Handoff idempotente: re-executar `handoff_prepare` 5 vezes produz 1 handoff e 1 mensagem; o segundo `resume` do mesmo `handoff_id` é *no-op*.
- [ ] Regra de dois provada: Serviços corre no mesmo AGR/TLS/EVT/TEN sem *flags* de vertical, reuso ≥ 70% medido em CI, `grep` de nomes de vertical em `core/` = 0, e um evento de pagamento é consumido pelo handler da vertical Serviços sem alterar o bus.
- [ ] Dataset *golden* com 100–300 conversas por vertical corre como Gate 13; handoff correcto ≥ 85% (H7) e 0 pedidos duplicados, 0 fugas, 0 injecções críticas bem-sucedidas.
- [ ] Orçamento esgotado ou LLM indisponível degrada para o modo determinístico em ≤ 1 turno, sem resposta em falta e sem pedido duplicado.
- [ ] Latência p95 de texto e custo de IA por conversa **medidos** no staging com número de teste e registados (alvo 4–8 s; ≤ 15% da mensalidade, a validar em H6); nenhum valor é assumido sem medição.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-025 | AGR: serviço, workers assíncronos, lock por conversa e API interna | feature | L | P0 | KAM-005, KAM-014 |
| KAM-026 | Checkpointer Postgres (esquema `lg`), `thread_id` e retenção | feature | M | P0 | KAM-025 |
| KAM-027 | AgentRegistry e validação no arranque (YAML, nós obrigatórios, licenças) | feature | M | P0 | KAM-025, KAM-009 |
| KAM-028 | ToolLayer: contrato, classes read/write/money e auditoria | feature | L | P0 | KAM-025, KAM-004, KAM-012, KAM-009 |
| KAM-029 | Idempotência de tools por `cart_id` | feature | M | P0 | KAM-028 |
| KAM-030 | LLM gateway: LiteLLM por digest, chaves virtuais, budgets e `llm_call_log` | feature | M | P0 | KAM-001, KAM-002, KAM-010, KAM-069 |
| KAM-031 | Grafo do Vendedor: esqueleto, `confirm_gate` e fluxo de dois turnos | feature | L | P0 | KAM-027, KAM-028, KAM-029, KAM-030, KAM-032, KAM-015, KAM-019 |
| KAM-032 | Validador de citação: renderer por referência e validador numérico com `sku` | feature | L | P0 | KAM-028 |
| KAM-033 | Guardrails de entrada e saída (injecção, domínio, cartão, sensível) | feature | M | P0 | KAM-030, KAM-031, KAM-069 |
| KAM-034 | Handoff idempotente em dois nós e retoma por compare-and-set | feature | M | P0 | KAM-019, KAM-026, KAM-031, KAM-018 |
| KAM-035 | Grafo de Serviços: slots, disponibilidade e `book_slot` | feature | L | P0 | KAM-027, KAM-028, KAM-047 |
| KAM-036 | Pipeline de voz: STT com confiança, eco e fallback a humano | feature | L | P1 | KAM-020, KAM-030, KAM-107, KAM-069 |
| KAM-037 | Modo determinístico sem LLM e degradação | feature | M | P1 | KAM-031, KAM-160 |
| KAM-038 | Subscrição de eventos: as verticais acordam por evento | feature | M | P0 | KAM-006, KAM-027, KAM-007 |
| KAM-039 | Prova da regra de dois: teste de contrato e métrica de reaproveitamento | feature | M | P0 | KAM-031, KAM-035, KAM-038, KAM-046 |
| KAM-040 | Dataset golden PT-AO sintético e eval harness como gate | feature | L | P0 | KAM-031, KAM-035, KAM-033, KAM-034 |
| KAM-114 | Modo concierge: a IA rascunha e o humano aprova | feature | M | P0 | KAM-018, KAM-031, KAM-034 |

---

## KAM-025 — AGR: serviço, workers assíncronos, lock por conversa e API interna

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-005, KAM-014 |
| Bloqueia | KAM-026, KAM-027, KAM-028, KAM-084 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§3, §4, §5.3, §11 regra 4, §14, §15.2), ADR-002, ADR-009, ADR-010, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.6) |

### Contexto

O CHR (KAM-014) entrega à fila inbound uma mensagem com contexto resolvido (`tenant_id`, `channel_id`, `contact_id`, `conversation_id`, `vertical`, `turn_id` = `wamid`). O AGR é o serviço que consome essa fila, carrega o estado e corre o grafo da vertical. É um processo Python próprio com LangGraph **só como biblioteca MIT**: o Server (`langgraph-api`, Elastic-2.0, chave de licença, egress para `beacon.langchain.com`) é proibido (E4, CONFIRMADO). Não há «assistants API» nem *cron* do LangGraph; o agendamento é do EVT.

### Objectivo

Entregar o esqueleto do serviço AGR: workers assíncronos atrás da fila, serialização de um turno por conversa, tectos de concorrência, API interna mínima e as guardas técnicas do ADR-002 (CI e rede), sem ainda conter grafos de negócio.

### Critérios de Aceitação

- [x] `GET /healthz` devolve 200; `POST /internal/turn` e `POST /internal/resume` recusam (401) pedidos sem credencial interna e não estão publicados fora da rede interna.
- [x] 20 mensagens concorrentes da mesma `thread_id` produzem 20 turnos **em série** (0 execuções sobrepostas, ordem de chegada preservada) com um grafo de teste.
- [x] Mensagens que chegam durante um turno ficam em fila e são coalescidas se distarem < 1,5 s (valor *proposta*, configurável).
- [ ] Um worker morto com SIGKILL a meio de um turno vê o *job* retomado por outro worker e o turno repete-se; o envio ao Outbound (fake) usa `idempotency_key = turn_id:seq` e regista 0 duplicados.
- [ ] Tecto de concorrência por tenant configurável (omissão *proposta*: 3) e limite por contacto (omissão *proposta*: 20 msgs/min, descarte silencioso com aviso único); um tenant com 1.000 mensagens em fila não aumenta o p95 de um segundo tenant mais de 20% (limiar *proposta*).
- [ ] Conversa com `conversations.mode = pausada` ou `handoffs.status = 'waiting'` **não** entra no grafo: a mensagem é reencaminhada ao HND (invariante de `../docs/tecnica/02` §11).
- [ ] Com egress bloqueado, 0 chamadas a `beacon.langchain.com`; `LANGSMITH_TRACING=false` aplicado (nome exacto da variável a validar na versão fixada, L5).
- [x] CI falha se o lockfile contiver `langgraph-api` ou `langgraph-runtime-inmem`; arranque falha se `langgraph_api` for importável.

### Detalhes Técnicos

- **Componentes:** AGR (consome da fila do GWY/CHR), EVT (BullMQ/Redis), Postgres. Módulos propostos: `kamba/agr/{app,worker,locks,context,api_internal,egress}.py`; `ConversaState` base em `kamba/core/state.py` (`../docs/tecnica/02` §5.3), com `schema_version`.
- **Fila:** consumidor Python do BullMQ (`bullmq` para Python, 3.3.1 em E4, CONFIRMADO a existência; maturidade e garantias de entrega **NÃO VERIFICADAS**, L6). Alternativa a registar em ADR local: *shim* TS fino que chama `/internal/turn`. Handlers idempotentes de qualquer forma.
- **Lock por conversa:** o `pg_advisory_xact_lock` mantém uma transacção aberta durante chamadas ao LLM (segundos); decidir e documentar entre lock de sessão `pg_advisory_lock(hashtextextended(thread_id,0))` numa ligação dedicada fora do *pool* de transacções (proposta) ou fila por chave.
- **Allowlist de saída:** LLM gateway interno, Postgres, Redis, HND, OBS; tudo o resto negado por defeito.
- Prioridade de eventos de pagamento sobre conversa na mesma fila (`../docs/tecnica/02` §15.2); contrapressão activa o modo determinístico (KAM-037) quando a fila excede o limiar.

```python
async def handle(job):
    ctx = ChannelContext.model_validate(job.data)      # tenant_id vem do CHR; imutável
    async with conversation_lock(ctx.thread_id):
        if await human_has_floor(ctx): return await hnd.forward(ctx)
        await graph_for(ctx).ainvoke(initial_state(ctx), {"configurable": {"thread_id": ctx.thread_id}})
```

### Testes Requeridos

- Unit: construção de `thread_id`, coalescência, tectos de concorrência, descarte por ritmo.
- Integração (Postgres e Redis reais): serialização por conversa, *kill -9* do worker, `/internal/*` sem credencial.
- Contrato/CI: lista de bloqueio de dependências e teste de egress (0 chamadas a `beacon.langchain.com`).
- Isolamento: `tenant_id` do `ChannelContext` nunca é substituído por valor do texto (injecção de «tenant_id=…» na mensagem ignorada).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] **Isolamento de tenant:** `tenant_id` só do estado/contexto do CHR; teste cruzado cobre o novo caminho (ADR-015).
- [x] **Idempotência:** repetição de turno e re-entrega de *job* sem efeitos duplicados (ADR-009).
- [x] **Privacidade:** `thread_id = tenant_id:contact_id`, sem telefone em logs, chaves ou eventos (ADR-010).
- [ ] **Custo e observabilidade:** métricas de fila, latência de turno e `degraded_turns` nascem aqui (ADR-018).
- [x] **Dependências:** versões fixadas por lockfile com *hash*; lista de bloqueio activa em CI (ADR-002).
- [ ] Sem segredos em código, logs ou traces; revisão por dois revisores (P0 de isolamento); documentação do serviço actualizada.

### Verificação dos Critérios de Aceitação

Medido a 2026-10-24, no ramo `feature/KAM-025-agr-servico-workers-lock`. Os
comandos estão em [`../docs/agr.md`](../docs/agr.md) §7. **Quatro caixas ficam
vazias**, e cada uma diz porquê: nenhuma delas é «passa em espírito».

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | `/healthz` 200; `/internal/*` recusam 401; não publicados fora da rede interna | **satisfeito** | `services/agr/tests/test_api_interna.py::TestAutenticacao` — 8 asserções: 401 sem cabeçalho nas duas rotas, 401 com cinco valores errados (incluindo o certo menos um caracter e em maiúsculas), **corpo de resposta igual nos dois casos** (as duas respostas juntas seriam um oráculo sobre o formato da credencial), autenticação **antes** de ler o corpo (um corpo de 16 KB sem credencial devolve 401 e não 400), `/healthz` continua sem credencial, 405 nos outros métodos, e 404 quando as rotas não estão montadas. A comparação é `hmac.compare_digest`. **Não publicado:** o `__main__.py` escuta em `127.0.0.1` e só o `Dockerfile` põe `0.0.0.0` (é o DoD do KAM-001, e `services/agr/tests/test_arranque.py` confere o `host` que chega ao `uvicorn`); o `infra/compose/docker-compose.dev.yml` publica em `127.0.0.1:${AGR_PORT}` — o *loopback* do anfitrião e não uma rede, conferido com `docker compose config` (que a revisão adversarial correu e **falhou**: a primeira versão deste PR duplicou o `depends_on` do bloco `agr` e o ficheiro deixou de ser analisável, pelo que a prova aqui nomeada não carregava — corrigido, e `docker compose config` sai com 0). **O limite:** a rede é do KAM-076; o que aqui se prova é que o processo não abre a porta por si |
| 2 | 20 concorrentes da mesma `thread_id` → 20 turnos em série, 0 sobrepostas, ordem preservada | **satisfeito** | `db/tests_agr/test_repeticao.py::TestSerieContraABase`: 20 desfechos, `maximo de execucoes simultaneas = 1`, e a lista de `turn_id` que o grafo viu **igual** à ordem de entrada. **E o que esse teste mede é o dreno, não a tranca** — a revisão adversarial apanhou-o e a frase anterior estava ao contrário: ele constrói **um** executor, logo uma ligação, e o `pg_advisory_lock` conta por sessão, pelo que a segunda tomada da mesma chave na mesma sessão é concedida de imediato. A ordem de chegada é exactamente o que o dreno garante, e é o que o critério pede; o que **não** se pode concluir dele é nada sobre a tranca. Quem mede a tranca é, por ordem de força: `test_tranca.py::TestExclusaoMutua` (SQL cru, duas ligações), `test_repeticao.py::TestDoisExecutoresNaMesmaConversa` (**novo** — dois executores com ligações próprias sobre a mesma conversa: 0 sobrepostas, e a espera de uma conversa não prende outra) e `TestMorteDoWorker`. **A leitura, e está declarada:** mede-se com `AGR_COALESCENCIA_MS=0` e `AGR_TECTO_POR_TENANT=0`, porque vinte mensagens concorrentes distam muito menos de 1,5 s (critério 3) e o tecto de 3 (critério 5) recusaria dezessete. É a tensão da linha 93 de `../docs/dividas-documentais.md`; o critério 3 autoriza-a ao dizer «configurável» |
| 3 | Mensagens durante um turno ficam em fila e coalescem se distarem < 1,5 s | **satisfeito** | `services/agr/tests/test_admissao.py::TestCoalescencia` — junta as que distam menos de 1,5 s; a distância é ao **anterior admitido** e não ao primeiro (dez mensagens a 1,4 s dão **um** lote, e não dois); a fronteira é estrita (1,5 s exactos ficam fora); e com a janela a zero cada mensagem é um turno. `TestCoalescenciaNoExecutor` prova no executor que as que chegam durante um turno esperam e entram no mesmo lote, com o invariante «cada mensagem que não abriu um lote foi coalescida» e todas a receberem o desfecho do turno que correu. Relógio injectado, não `sleep` |
| 4 | SIGKILL a meio do turno → *job* retomado por outro *worker*, turno repete-se, `idempotency_key = turn_id:seq`, 0 duplicados | **parcial** | **O que está medido:** `db/tests_agr/test_tranca.py::TestMorteDoWorker` mata um processo filho com `SIGKILL` a sério no meio da secção crítica e prova que (a) enquanto ele vivia ninguém mais tinha a tranca e (b) morto ele, outra sessão a consegue — é o que torna a retoma possível sem temporizador nenhum, e só o servidor o pode dizer. `test_repeticao.py::TestRepeticao` prova a outra metade com o executor verdadeiro: o turno levanta depois de enviar, repete-se desde o início, a chave é `turn_id:seq` **literalmente**, vinte entregas do mesmo *job* dão **duas** chaves distintas e **zero** chaves novas, e `wamid` diferentes dão chaves diferentes (senão a recompra era deduplicada). **O que NÃO está medido, e é por isso que a caixa fica vazia:** «o *job* retomado por outro *worker*» é a retoma de um *job* `stalled` **pelo BullMQ**, e as garantias do BullMQ são NÃO VERIFICADO (`../docs/tecnica/evidencia/E4` §2.10). O que existe é a tradução que o *shim* faz — 5xx, rede e *timeout* lançam, 400 e 401 não (`packages/core-ts/tests/agr.shim.test.ts`, 23 testes) — e a propriedade da tranca acima. **E a revisão adversarial encontrou aqui um defeito que tornava a frase «a mensagem fica na fila» falsa em todo o ticket:** o `fila.add` do `chr/fila.ts` não punha `attempts`, que é opção do ***job*** e não do *worker*, pelo que o BullMQ dava **uma** tentativa e mandava o *job* para `failed` — e o `jobId` deduplica incluindo em `failed`. Com `grafos` ainda por registar, *toda* invocação válida dá 503, isto é: todas as mensagens morriam à primeira e o `wamid` ficava bloqueado. Corrigido no produtor (`attempts: TENTATIVAS_DO_AGR` e `backoff: {type:"custom"}`). Medir a retoma pede uma fila real com dois *shims*, e isso é o *gate* 5 (linha 92 das dívidas) ou o KAM-084 |
| 5 | Tecto por tenant (3) e limite por contacto (20/min, descarte silencioso com aviso único); 1.000 mensagens de um tenant não sobem o p95 de outro > 20% | **parcial** | **O que está medido:** `test_admissao.py` — o ritmo passa até ao limite e recusa a seguir, a janela desliza e liberta quota, a quota é por contacto (dois canais do mesmo contacto partilham-na, dois contactos não), `0` é sem limite, e o aviso é **um** por contacto por janela; o tecto recusa a quarta e liberta no fim, o tecto de um *tenant* não trava outro, e o dicionário de contadores **não cresce** com um *tenant* por chave. `test_api_interna.py` prova o que o chamador vê: o descarte por ritmo dá **200** com `outcome: descartado` (um 429 fazia o BullMQ repetir a mensagem que se acabou de decidir descartar), e o tecto cheio dá **503** com `Retry-After`. Os quatro tectos lêem-se do ambiente, e um valor que não é inteiro **levanta** em vez de cair na omissão. **E o ritmo conta mensagens e não entregas:** `TestRitmoEIdempotencia` prova que vinte entregas do mesmo `wamid` gastam **uma** quota, e `test_api_interna.py::test_uma_recusa_por_tecto_nao_gasta_quota_de_ritmo` que um 503 não gasta nenhuma. A revisão adversarial mediu o contrário na primeira versão — vinte 503 do mesmo *job* consumiam os vinte lugares do minuto e a mensagem seguinte, legítima, era descartada em silêncio, que é o efeito duplicado que o DoD da idempotência diz não existir. **O que NÃO está medido:** o p95 comparado entre dois *tenants* com 1.000 mensagens em fila. É uma medição de carga, não há *suite* que a faça, e o tecto é **por processo** (com N réplicas é 3×N — está escrito em `../docs/agr.md` §4). Pertence ao KAM-084, que é quem calibra |
| 6 | `mode = pausada` ou `handoffs.status='waiting'` não entram no grafo: a mensagem vai ao HND | **parcial** | **O que está medido, contra a base:** `db/tests_agr/test_palavra.py` — os três modos que não são `bot` fecham a porta; um `handoffs` em `waiting` fecha-a mesmo com `mode = 'bot'`; os outros **quatro** estados (`resumed`, `timeout`, `cancelled`, `degraded`) deixam passar, porque são passagens acabadas; e um *handoff* aberto **noutra** conversa da mesma loja **não** fecha esta (o `EXISTS` filtra por `(tenant_id, conversation_id)`) — com o controlo positivo de que na conversa certa ele conta, senão o teste passava com um `EXISTS` que nunca encontra nada. `test_repeticao.py::TestODesfechoQuandoNaoSeLeAConversa` prova no executor verdadeiro que um modo **que a base ainda não deixa escrever** fecha a porta: `modo != 'bot'` é lista de permitidos, e um quinto valor no domínio não pode abrir a porta por omissão. **E o defeito mais sério que a revisão adversarial encontrou estava aqui:** a fila era indexada por `thread_id`, e a `conversations` é `UNIQUE (tenant_id, contact_id, channel_id)` — o mesmo contacto em dois canais tem **duas** conversas e **um** `thread_id`. Duas mensagens de conversas diferentes do mesmo contacto a distarem menos de 1,5 s coalesciam, e a decisão da conversa A valia para a B: se a B tivesse um *handoff* em `waiting`, o turno entrava no grafo sobre ela (esta invariante violada) e a mensagem da B **perdia-se**, porque o *shim* vê 200. E nenhum teste o apanhava, porque o duplo de `ler_palavra` devolvia a mesma `Palavra` para qualquer invocação — o duplo tornava a propriedade impossível de falhar. A fila passa a ser indexada por `(thread_id, conversation_id)`, a tranca continua por `thread_id` (tem de travar os dois canais, senão dois turnos correm sobre o mesmo *thread* do LangGraph), e `test_turno.py::TestUmLoteNaoAtravessaConversas` mede as quatro propriedades com um duplo que responde **por conversa**. **O que NÃO está medido:** a entrega ao HND. O `reencaminhar` é uma **porta**, e quem a liga é o KAM-019 — o `__main__.py` monta uma que não faz nada e diz porquê. O que este ticket prova é a **decisão** de não entrar no grafo e de reencaminhar; a entrega é do ticket que tem o provedor |
| 7 | Com egress bloqueado, 0 chamadas a `beacon.langchain.com`; `LANGSMITH_TRACING=false` aplicado | **parcial** | **O que está medido:** `test_egresso.py::TestTelemetria` — as duas variáveis ficam a `false`, e **sobrepõem** um `true` do ambiente (um AGR que respeitasse um `LANGSMITH_TRACING=true` mandava conteúdo de conversas para fora de Angola sem destino registado, ADR-008); o que a função devolve é um `tuple` de **nomes**, que não pode levar o valor — e a primeira versão devolvia `{nome: valor_anterior}` com uma *docstring* a prometer o contrário, com um teste que não podia falhar (`" ".join(dict)` itera as chaves): corrigido depois da revisão adversarial. `test_arranque.py::TestGuardasDoAdr002` confirma-o depois de `main()` correr. `TestAllowlistDeSaida` lê o `services/agr/egress.yaml` e confirma que o `beacon` **não** está nos destinos, que `por_omissao` continua `negar`, e que nenhum destino é `*` — com a asserção de que o `beacon` **está** no ficheiro, num comentário que diz porque não está na lista (apagar o comentário não melhora nada, e o teste nota-o). **O que NÃO está medido:** «com egress bloqueado». O bloqueio de rede é o KAM-076; não há aqui rede bloqueada nem contador de chamadas, e fingir que há era a classe de defeito que esta secção existe para não ter. **E o nome exacto da variável continua NÃO VERIFICADO (L5)**, como o próprio critério diz: impõem-se as duas que a evidência nomeia, e o egresso negado por omissão é o que vale se nenhuma for a certa |
| 8 | CI falha com `langgraph-api`/`langgraph-runtime-inmem` no lockfile; arranque falha se `langgraph_api` for importável | **satisfeito** | **CI:** a lista de bloqueio do `tools/lint_arch` já cobre os dois nomes com normalização PEP 503 (`langgraph_api` ≡ `langgraph-api`), e `python -m lint_arch --root . all` → `lista de bloqueio: conforme`, `estrutura: conforme`. O lock novo do AGR não os contém: `python tools/pip_lock.py --check-offline` → «coerente com os pins» nos três locks. **Arranque:** `egresso.exigir_biblioteca_mit()` corre antes de se ler uma variável e antes de abrir uma porta, e `test_arranque.py::TestGuardasDoAdr002` prova que (a) com o módulo importável `main()` devolve `3` e o `uvicorn.run` **não** é chamado, e (b) com o módulo importável **e** uma `PORT` inválida o código é o da guarda — isto é, a guarda corre primeiro. `test_egresso.py` prova que a guarda **procura** o módulo sem o importar (um `import` executava o `__init__.py` do pacote que estamos a recusar) e que os nomes são de **módulo** e não de distribuição, senão o `find_spec` nunca encontrava nada |

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **não satisfeito** | Quatro parciais: 4, 5, 6 e 7, cada um com a parte que falta nomeada acima. As quatro partes que faltam pertencem ao BullMQ (NÃO VERIFICADO, `E4` §2.10), ao KAM-084 (carga), ao KAM-019 (o provedor de *handoff*) e ao KAM-076 (a rede) |
| **Isolamento de tenant** (ADR-015) | **satisfeito** | `services/agr/tests/test_isolamento.py` fecha as três portas por onde a injecção poderia entrar: um campo de texto a mais no corpo recusa o contrato **inteiro** (`campo_desconhecido`, e o código da recusa não repete o nome nem o valor que vieram de fora); conteúdo dentro de um campo de forma fechada recusa; e um `thread_id` que aponta para outro *tenant* recusa com `thread_id_incoerente` em vez de se recalcular em silêncio — a tranca depende dele. **Cruzado, contra a base:** `db/tests_agr/test_palavra.py::TestIsolamento` (o contexto de B não lê a conversa de A, nem o `EXISTS` sobre `handoffs`; sem contexto nenhum não há resposta) e `test_repeticao.py::TestODesfechoQuandoNaoSeLeAConversa`, que corre o **executor verdadeiro** com o contexto trocado e prova que o grafo **não** corre e que não há envio. **E um achado:** um `wamid` pode transportar `tenant_id=<uuid>` e passar a forma — está medido e escrito em `test_isolamento.py`, com a razão pela qual apertar o alfabeto seria uma lista de proibidos sobre conteúdo e a propriedade que fecha o caso é o `wamid` nunca ser interpretado |
| **Idempotência** (ADR-009) | **satisfeito** | `db/tests_agr/test_repeticao.py` — a repetição de um turno que levantou dá a **mesma** chave, vinte entregas do mesmo *job* dão duas chaves distintas e zero novas, e `wamid` diferentes dão chaves diferentes. `test_contexto.py` prova que duas leituras do mesmo corpo dão a mesma chave, e que um `seq` negativo recusa |
| **Privacidade** (ADR-010) | **satisfeito** | `thread_id = tenant_id:contact_id`, conferido também contra o **texto** do `threadIdDe` do TypeScript (`test_contexto.py::TestThreadId`). O telefone não entra: o contrato não tem campo para ele (§3.13), e o `wamid` — que carrega o número em base64, INDÍCIO de `../docs/logs.md` §2.1 — não vai para registo nenhum (o *shim* registra o desfecho e não o `wamid`) nem para chave de métrica. `test_arranque.py` prova que a credencial nunca aparece no registo. `test_metricas.py` e `agr.shim.test.ts` provam que nenhuma linha exposta traz um identificador, e que a regra se impõe pela **gramática** da etiqueta e não por uma lista de palavras — um `tenant_id` levanta. `log_policy lint` → 0 achados |
| **Custo e observabilidade** (ADR-018) | **não satisfeito** | As métricas de **fila** (`agr_queue_depth`) e de **latência de turno** (`agr_turn_latency_ms`) nascem aqui, com `agr_turns_total{outcome}`, `agr_admitted_rejected_total{motivo}`, `agr_coalesced_total` e `agr_backpressure_total`. O **`degraded_turns` não**, e a caixa fica vazia por isso: ele conta turnos em **modo determinístico**, que é o KAM-037, e não há neste ticket caminho nenhum por onde um turno possa ficar degradado. É a decisão que o KAM-018 tomou para o `echo_latency_ms` — «uma métrica declarada e sempre a zero é pior do que uma métrica ausente» —, e está registada no dicionário §3.24. O que nasce em vez dela, e conta de verdade, é o `agr_backpressure_total`: o sinal que o KAM-037 vai consumir |
| **Dependências** (ADR-002) | **satisfeito** | `services/agr/requirements/runtime.txt` regenerado com `tools/pip_lock.py`, **com *hashes***, e `--check-offline` conforme nos três locks. A dependência nova é **uma**: o `pg8000` 1.31.5, na mesma versão exacta que o `db/requirements/migrations.in` já escolheu e justificou (BSD-3-Clause, Python puro). **Não** há `bullmq` para Python, e a razão está no `ADR-L004`. Lista de bloqueio: `lint_arch` conforme; `supply_chain check` conforme nos seis passos (26 referências a imagens, todas por *digest*; 12 serviços com lista de saídas negada por omissão; 20 componentes de licença registados) |
| Sem segredos; **2 revisores**; documentação do serviço actualizada | **parcial** | **Sem segredos:** `scan_secrets tree` → limpo, 1219 ficheiros. Os valores de teste têm espaços de propósito (nenhum segredo tem espaços), e há um teste que prova que a credencial não chega ao registo. **Documentação:** [`../docs/agr.md`](../docs/agr.md) (novo), [`../docs/adr/ADR-L004-fila-e-tranca-do-agr.md`](../docs/adr/ADR-L004-fila-e-tranca-do-agr.md) (novo), dicionário §3.24 (emenda 1.33), `../docs/ci.md` §3 e `../ops/secrets-inventory.yaml`. **Os 2 revisores: a caixa fica vazia.** Uma revisão adversarial é evidência, não é um revisor, e este ticket é P0 de isolamento. É o mesmo estado dos tickets anteriores desta linha |

#### Prova por mutação

`python db/mutacoes.py --aplicaveis` → **698 mutações conferidas, 0 não
aplicáveis**. As **nove** novas (prefixo `agr:`) correm contra a `tests_agr`:
`9 mutação(ões) corrida(s), 0 não apanhada(s)`.

A nona é a reposição do defeito **C2** que a revisão adversarial encontrou — a
espera pela tranca a correr dentro do `asyncio.Lock` da única ligação do
processo —, e é a razão de o `AG_TRANCAS` existir: a revisão notou que a
constante estava declarada e **não usada**, isto é, que não havia mutação
nenhuma sobre o ficheiro onde vive a propriedade mais delicada do ticket. Quem
a mata é a bateria nova `TestDoisExecutoresNaMesmaConversa`.

**Duas sobreviveram à primeira execução, e as duas eram defeitos de cobertura
reais da *suite* nova** — não do código:

1. `agr: zero linhas passa a ler-se como bot` sobreviveu porque a propriedade
   só tinha bateria no *gate* 4, com um duplo a devolver `None`. Fechou-se com
   `TestODesfechoQuandoNaoSeLeAConversa`, que corre o executor verdadeiro com o
   contexto de RLS trocado — **mais forte** do que a do *gate* 4, porque quem
   esconde a linha é a política e não um duplo.
2. `agr: o modo deixa de ser lista de permitidos` sobreviveu porque
   `modo != 'bot'` e `modo in ('dono','humano','pausada')` são equivalentes para
   os quatro valores de hoje. Fechou-se com um teste que injecta um **quinto**
   modo — que o `conversations_mode_ck` não deixa escrever —, e que é o único
   sítio onde a diferença aparece.

**E o corredor apanhou um terceiro defeito, que nenhum *gate* apanhava:** o
`_copiar` do `db/mutacoes.py` não levava `services/agr`, pelo que a linha de
base da `tests_agr` ficava vermelha com `ModuleNotFoundError: No module named
'kamba_agr'` — e uma mutação «apanhada» sobre isso não significa nada. É
exactamente a regra que aquela função já tinha escrita para a próxima vez
(«uma mutação nova sobre um ficheiro que esta cópia não leva obriga a
acrescentá-lo aqui»), cumprida pela primeira vez por quem a leu.

#### Migração

**Não há.** A cadeia fica na `0019`. Este ticket não cria tabela nenhuma: a
tranca é um `pg_advisory_lock`, que não tem tabela, e as duas tabelas que o AGR
lê — `conversations` e `handoffs` — existem desde as revisões `0009` e `0011`,
com `SELECT` já concedido a `kamba_app`. O papel `kamba_agr` e o esquema `lg`
são o KAM-026. Conferido: `canon_lint` → `migracoes: 19 ficheiro(s)`.

#### Revisão adversarial independente: treze achados, treze fechados

A revisão correu sobre o `de60f7d` com os requisitos e o código, **sem** as
justificações de quem escreveu, e não aprovou. Os quatro que mudam
comportamento, e que nenhum *gate* apanhava:

| # | O que estava errado | Como se fechou |
|---|---|---|
| C1 | O `docker-compose.dev.yml` ficou **YAML inválido** — o bloco `agr` ganhou um `depends_on` duplicado —, e com ele `make up` falhava para **todos** os serviços. Agravante: era a prova nomeada do critério 1 | Bloco duplicado apagado; `docker compose config` sai com 0. **Nenhum *gate* o apanha** — o `lint_arch` só confere que o ficheiro existe e o `supply_chain` só lhe aplica *regex*. Fica na linha 94 das dívidas |
| C2 | A espera pela tranca corria **dentro** do `asyncio.Lock` da única ligação do processo: uma conversa à espera parava o processo inteiro, e as que acabaram não conseguiam **destrancar**. Bloqueio de cabeça de fila a atravessar *tenants* — o oposto do critério 5. E a chave colide de propósito com a do `PreSendGuard` do KAM-018, que corre em **cada envio do bot**: não era preciso um segundo AGR | `pg_try_advisory_lock` em ciclo, largando o `asyncio.Lock` entre tentativas, com recuo exponencial e tecto. Bateria nova (`TestDoisExecutoresNaMesmaConversa`) e **mutação nova** que repõe o defeito |
| C3 | Um lote **atravessava conversas**: a fila era por `thread_id` e um contacto em dois canais tem duas conversas e um `thread_id`. A decisão de uma valia para a outra, e a mensagem da outra **perdia-se**. O duplo de `ler_palavra` tornava-o impossível de falhar | Fila por `(thread_id, conversation_id)`, tranca ainda por `thread_id`, `assert` do invariante no lote, duplo que responde por conversa, `invocacao_crua` a derivar o `conversation_id` do par |
| A1 | O `fila.add` não punha `attempts`, que é opção do ***job*** e não do *worker*: o 503 era **terminal**, e com `grafos` por registar todas as mensagens morriam à primeira — com o `wamid` bloqueado, porque o `jobId` deduplica em `failed`. «A mensagem fica na fila» era falso em todo o ticket | `attempts: TENTATIVAS_DO_AGR` e `backoff: {type:"custom"}` no produtor |

E nove de severidade menor, todos fechados: o ritmo gasto pelas nossas próprias
retentativas (**A2**, e era um efeito duplicado que o DoD da idempotência nega);
dois dicionários a crescer para sempre no mesmo ficheiro que nomeia esse defeito
(**M1**); o `desligar_telemetria` a devolver o valor antigo com um teste que não
podia falhar (**M2**); o critério 2 satisfeito pela razão errada (**M3**, acima);
a retoma sem a tranca que três sítios afirmavam (**M4**); e cinco afirmações de
comentário ou de ADR que não correspondiam ao código (**B1–B3**), a métrica do
*shim* sem domínio no dicionário (**B4**), o `fechar()` sem chamador (**B5**), o
`pg_locks` contado sem `pid` (**B6**), a mutação que modelava a etiqueta e não o
furo (**B7**) e o teste do processo do *shim* deixado fora do *commit* (**B8**).

**E a revisão disse por extenso onde não encontrou nada**, que é a parte que
mais vale: **nenhum caminho de fuga de isolamento entre *tenants*** (o `tenant_id`
entra só pelo contrato fechado, `InvocacaoDoAgente` é `frozen`, o `thread_id` não
se recalcula, o `wamid` nunca é interpretado, zero linhas é sempre «não entra», e
nenhum identificador chega a etiqueta ou a registo); nenhum `await` em falta;
nenhuma dereferência nula; nenhum erro engolido além dos dois deliberados; e nada
a apontar no SQL. O único defeito de isolamento era **entre conversas do mesmo
contacto** (C3), e está fechado.

#### O que não se verificou, e porquê

- **A retoma de um *job* `stalled` pelo BullMQ** (parte do critério 4). Pede uma
  fila real com dois *shims*; as garantias do BullMQ são NÃO VERIFICADO (`E4`
  §2.10) e nenhum documento deste conjunto as mediu.
- **O p95 entre dois *tenants* sob carga** (parte do critério 5). É KAM-084.
- **A entrega ao HND** (parte do critério 6). É KAM-019; aqui prova-se a decisão.
- **O egresso bloqueado na rede** (parte do critério 7). É KAM-076; aqui prova-se
  o contrato e a guarda de arranque.
- **A latência real de um turno.** O `agr_turn_latency_ms` mede o que correu, e
  o que correu neste ticket é um grafo de teste. O orçamento de 3–7 s do
  `../docs/tecnica/02` §15.1 é **orçamento de desenho** e continua por medir.

---

### Handoff para Claude Code

```text
És o executor do ticket KAM-025 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-025), docs/tecnica/02_Agent_Runtime_Verticais.md
(§3, §4, §5.3, §11, §15.2) e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: serviço AGR Python com workers assíncronos, lock por conversa, tectos de concorrência,
API interna (/internal/turn, /internal/resume, /healthz) e guardas do ADR-002 (lista de bloqueio, egress).
- LangGraph só como biblioteca MIT; nunca langgraph-api nem langgraph-runtime-inmem.
- tenant_id vem do contexto do CHR; nunca do texto. Telefone nunca em chaves, logs ou eventos.
- Decide e regista o mecanismo de lock (sessão vs transacção) e o consumidor da fila.
Não expandas escopo: checkpointer (KAM-026), registry (KAM-027) e tools (KAM-028) são tickets próprios.
Testes: unit, integração (kill -9, serialização), CI de bloqueio e egress, isolamento. PR com o template §7.
Commits: feat(KAM-025): …
```

---

## KAM-026 — Checkpointer Postgres (esquema `lg`), `thread_id` e retenção

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-025 |
| Bloqueia | KAM-034, KAM-070, KAM-071 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§11, §12), ADR-002, ADR-006, ADR-010, `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.1, §11), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.6) |

### Contexto

`interrupt()` exige checkpointer durável e `thread_id` (CONFIRMADO, E4). Sem checkpointer o handoff perde-se, pelo que o arranque do AGR tem de falhar se o saver não estiver configurado. O estado contém texto de clientes: é dado pessoal, com a mesma classificação e residência do resto (D1, ADR-008) e entra nos backups/PITR.

### Objectivo

Configurar o `AsyncPostgresSaver` (`langgraph-checkpoint-postgres` 3.1.2, MIT) no esquema `lg` do Postgres 18, com `thread_id = tenant_id:contact_id`, estado mínimo, durabilidade síncrona para grafos com escrita/dinheiro, versionamento do estado e política de retenção.

### Critérios de Aceitação

- [x] Estado gravado num turno é recuperado após reinício do processo (mesmo `thread_id`), incluindo `stage`, `cart` e `handoff`.
- [x] `thread_id` cumpre `^<uuid>:<uuid>$`; após correr o golden/suite de integração, a pesquisa de `\+?244\d{9}` e de BSUID nas tabelas `lg.*` devolve **0** ocorrências.
- [x] `setup()` corre numa migração Alembic controlada (com `downgrade` testado), nunca em *runtime*; o AGR falha o arranque (exit ≠ 0) sem checkpointer configurado.
- [x] Papel Postgres próprio para `lg` (`kamba_agr`), sem acesso a `platform` nem a `medusa`; esquema separado.
- [ ] Para grafos com nós `write`/`money`, o *checkpoint* precede o efeito seguinte (teste: falha injectada entre checkpoint e efeito não duplica nem perde o efeito na repetição).
- [ ] O estado persistido contém no máximo K mensagens recortadas + `summary` (K *proposta*, a calibrar) e `facts` apenas do turno; teste falha se surgirem binários, segredos ou catálogo completo.
- [ ] Estado com `schema_version` N-1 é migrado em `ingest` sem perda; teste de retoma de um `interrupt` pendente após *upgrade* de versão do grafo.
- [ ] *Job* de retenção apaga *threads* inactivos há mais de 30 dias (valor *proposta*, a confirmar por parecer) por `thread_id`; a poda mantém os últimos N checkpoints (N *proposta*).

### Detalhes Técnicos

- **Componentes:** AGR, Postgres 18 (ADR-006). Ligação própria: `autocommit=True` e `row_factory=dict_row` (requisito conhecido do saver; confirmar na versão fixada, L5). Pool dedicado.
- **Concorrência:** um turno activo por thread vem do lock de KAM-025; o saver não é a fonte de exclusão.
- **API de remoção por `thread_id`** do saver e nome do parâmetro de durabilidade: a confirmar na versão fixada (L5).
- Eliminação a pedido do titular (KAM-070) remove o *thread*; a fusão de contactos migra o *thread* (`../docs/tecnica/02` §12).
- RLS não se aplica por coluna `tenant_id` nas tabelas do saver; o isolamento vem do prefixo `tenant_id:` no `thread_id` (construído só do estado), do papel próprio e do teste cruzado (X-02/X-09). Registar a decisão.
- Retenção de backups com texto de clientes: mesma classe de dados (`../docs/tecnica/08` §7.1).

### Testes Requeridos

- Unit: construção/validação de `thread_id`; recorte de janela e `summary`.
- Integração (Postgres real): reinício, *kill -9* entre checkpoint e efeito, migração de `schema_version`.
- Isolamento: contexto do tenant B nunca carrega o *thread* do tenant A (X-02).
- Retenção: *job* com relógio simulado; varrimento por telefone em `lg.*`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] **Isolamento de tenant:** `thread_id` construído do estado; teste de isolamento cobre `lg` (ADR-015).
- [ ] **Privacidade:** nenhum telefone nem BSUID em claro no estado; retenção por classe aplicada (ADR-010; parecer pendente sobre prazos).
- [x] **Migrações reversíveis:** `upgrade` e `downgrade` testados; `downgrade` documentado como destrutivo só em ambientes não-produtivos.
- [ ] **Dependências:** `langgraph-checkpoint-postgres` fixado por *hash*; licença MIT registada no SBOM.
- [x] **Custo e observabilidade:** métricas de tamanho de estado e latência de checkpoint (alvo 0,05–0,15 s de `../docs/tecnica/02` §15.1, a medir).
- [ ] Revisão por dois revisores (dados pessoais); documentação de retenção actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-026 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-026), docs/tecnica/02_Agent_Runtime_Verticais.md
(§11, §12) e docs/tecnica/08_Seguranca_Conformidade.md (§7.1, §11).
Objectivo: AsyncPostgresSaver (langgraph-checkpoint-postgres 3.1.2, MIT) no esquema lg, papel próprio,
thread_id = tenant_id:contact_id, durabilidade síncrona para grafos com escrita, schema_version no estado,
retenção/poda por thread_id.
- setup() só em migração Alembic reversível; AGR falha o arranque sem saver.
- Nenhum telefone/BSUID/segredo/binário no estado; teste de varrimento obrigatório.
- Nomes de parâmetros do saver: confirmar na versão fixada (L5) e registar.
Não expandas escopo: purga por titular (KAM-070) e retenção global (KAM-071) são tickets próprios.
Testes: unit, integração (reinício, kill -9), isolamento, retenção. PR com o template §7.
Commits: feat(KAM-026): …
```

### Verificação dos Critérios de Aceitação

Medido no ramo `feature/KAM-026-checkpointer`, contra um PostgreSQL 18 real
(`python db/gate_bd.py --suite tests_agr`) e a bateria de unidade do serviço.
As quatro *suites* que este trabalho toca: `tests_agr` **60 OK**, `tests`
**584 OK**, `tests_isolamento` **78 OK**, unidade do AGR **201 OK**.

| # | Veredicto | O que se mediu, e com que comando |
|---|---|---|
| 1 | **satisfeito** | `test_sobrevive_ao_reinicio_do_processo`: grava, abre um `CheckpointerDoAgr` **novo numa ligação nova** — que é o reinício sem reiniciar nada — e lê `stage`, `cart` e `handoff` pelo nome. `tests_agr` → **60 OK** |
| 2 | **satisfeito** | O `thread_id` cumpre a forma à entrada (`contexto.py` do KAM-025, `thread_id_de` e `thread_id_incoerente`). O varrimento de `lg.*` dá **0** telefones e **0** campos de BSUID num turno normal — e, antes disso, há dois ensaios que **semeiam** um número angolano de forma real e um `bsuid_enc` e exigem que o varrimento os **encontre**. Sem eles o critério passava pela razão errada: em `msgpack`, uma busca por texto sobre a coluna devolve 0 com o telefone lá dentro. O BSUID procura-se pelo **nome do campo**, porque é um identificador opaco sem forma fixa no canon. **O que não se mediu:** o *golden* — é o KAM-040 e não existe; o varrimento correu sobre os dados desta *suite* de integração, que é a outra metade da conjunção que o critério oferece |
| 3 | **satisfeito** | **Não há `setup()`**: o DDL é nosso e vive na revisão `0020`, pelo que nada corre em *runtime* por construção. O `downgrade` é testado em `db/tests/test_migracao.py::TestCiclo`, que passou a exigir que o esquema `lg` **também** desapareça no `downgrade base` — media só o `platform`. O arranque: três ensaios em `test_arranque.py` — sem checkpointer sai com **4**, o código distingue-se do 2 e do 3, e a guarda corre **antes** do `uvicorn.run` |
| 4 | **satisfeito** | `test_o_papel_do_checkpointer_nao_ve_o_platform`: `42501` em `platform.tenants`, `contacts` e `conversations`. `test_o_papel_do_checkpointer_nao_cria_nada_no_lg`: `42501` num `CREATE TABLE`. O Medusa é uma **base** separada e não um esquema, pelo que o mecanismo é o `CONNECT`: `test_o_papel_nao_alcanca_mais_bases_do_que_o_kamba_app`. **A primeira versão desse ensaio exigia o conjunto vazio e falhou a dizer `['postgres']`** — o PostgreSQL dá `CONNECT` ao `PUBLIC` por omissão, para os sete papéis, desde o KAM-003. Não é deste bloco; ficou na dívida **95** |
| 5 | **parcial — caixa vazia** | A metade que se pode medir está: o `ON CONFLICT` torna a repetição idempotente nas duas tabelas (`test_repetir_a_mesma_escrita_nao_duplica`, `test_regravar_o_mesmo_checkpoint_nao_duplica`), que é «a repetição não duplica» visto da tabela. A outra metade **não tem sujeito**: «grafos com nós `write`/`money`» não está modelado em lado nenhum, não existe grafo nenhum (o `sem_grafos` do KAM-025 levanta), e o `durability` do LangGraph é argumento **por invocação** (`sync`/`async`/`exit`) que o `Protocol Grafo` do `turno.py` não aceita. Credor: **KAM-031** |
| 6 | **parcial — caixa vazia** | O tecto da janela cumpre-se e prova-se nos dois lados: o `aput` **levanta** acima de `JANELA_MAXIMA` (20, ***proposta***) e não chega a tocar na base, e o `estado.recortar_janela` tem oito ensaios — a fronteira pelo valor, as últimas e não as primeiras, janela zero a esvaziar. **Faltam duas coisas à letra:** «`facts` apenas do turno» é do `ingest`, que é o **KAM-031**; e o teste que falha «se surgirem binários, segredos ou catálogo completo» não existe — o varrimento cobre telefones e campos de BSUID, não binários nem segredos |
| 7 | **não satisfeito — caixa vazia** | O `versao_lida` do KAM-025 lê e recusa uma versão à frente, e o `SCHEMA_VERSION` nasce a 1. Mas **não há função de migração N-1 → N**, e o sítio onde ela correria — o `ingest` — é do **KAM-031**; a «retoma de um `interrupt` pendente» precisa de um grafo, que não existe. Nada disto se pode medir hoje |
| 8 | **parcial — caixa vazia** | A retenção está: `retencao.varrer` apaga as *threads* paradas há mais de 30 dias com o papel `kamba_batch`, com relógio simulado, a fronteira afirmada **pelo valor** e o **máximo** da *thread* a mandar em vez de cada linha. **A poda «manter os últimos N» não se implementa, e é escolha:** o `prune` do próprio `BaseCheckpointSaver` avisa que um `keep_latest` ingénuo corta a cadeia de um canal `DeltaChannel` e que o valor «would silently reconstruct as empty (no error raised)», e nomeia como opção segura não podar. Não há grafo nenhum; quem decide se algum usa canais delta é o **KAM-031**. O método levanta `NotImplementedError`, que é o comportamento certo |

**O Definition of Done, linha a linha.**

| Linha | Veredicto | Evidência |
|---|---|---|
| Todos os CA satisfeitos | **vazia** | Derivada: quatro de oito, pelas razões acima |
| Isolamento de tenant | **satisfeito** | O `thread_id` é construído do estado validado (`thread_id_de`) e conferido antes do turno; a *suite* cobre o `lg` com o X-02 — a *thread* de A invisível no pedido de B, e o papel sem alcance ao `platform` |
| Privacidade | **vazia** | A primeira metade cumpre-se e está medida (nenhum telefone nem campo de BSUID no estado, com os dois ensaios que provam que o varrimento encontra). A segunda — «retenção por classe aplicada» — **não**: a varredura apaga por **inactividade da *thread***, não por classe de dados, e o prazo é *proposta* com dois valores em conflito no canon. Espera parecer, como o `../docs/tecnica/08` §11 já diz |
| Migrações reversíveis | **satisfeito** | `TestCiclo` corre `downgrade base` e `upgrade head` pela linha de comandos, e exige que o `lg` desapareça. O `downgrade` está documentado como destrutivo na nota do módulo da `0020`, com a razão de não levar `CASCADE` |
| Dependências | **vazia — divergência** | O critério pede o `langgraph-checkpoint-postgres` fixado por *hash*. **Esse pacote não pode entrar:** é MIT mas exige `psycopg` e `psycopg-pool`, LGPL-3.0-only, que o `ci/licenses.yaml` nega por prefixo. O que entra é o `langgraph-checkpoint`, fixado por *hash* (o *lock* tem **1159**) e registado em `ci/supply-chain/licencas.yaml` — e o `-postgres` fica lá registado como **bloqueado**, com a razão. O fecho inteiro foi classificado pelo avaliador do próprio *gate* 11: **35 avaliadas, 35 permitidas, 0 fora**. Fechar esta caixa é reescrever o critério, não mudar código |
| Custo e observabilidade | **satisfeito** | `agr_checkpoint_latency_ms` e `agr_checkpoint_state_bytes`, as duas **sem etiqueta** — o `medir` nem a aceita, e é isso que prova o `OBS-I`. O alvo de 0,05–0,15 s é «a medir» e não um limiar: nada falha por o exceder |
| Revisão por dois revisores | **vazia** | Decisão escrita do fundador: nesta fase não há revisores. A revisão adversarial correu e é evidência, não é um revisor |
| Documentação de retenção | **satisfeito** | `docs/agr.md` §7-A, versão 1.2, com os dois prazos do canon e porque é que nenhum é decisão deste ticket |

**A revisão adversarial reprovou-o à primeira, e isso está escrito.** Vinte e
dois achados — quatro críticos, sete sérios, onze menores — em
[`../docs/analises/ANALISE-28-KAM-026-checkpointer-lg.md`](../docs/analises/ANALISE-28-KAM-026-checkpointer-lg.md).
Dois dos críticos eram reproduzíveis sem base de dados, e um deles já punha uma
bateria existente a vermelho: a inserção de duas entradas no inventário de
segredos **partiu a entrada vizinha**, e o `secrets_inventory` reportava 0
segredos e cobertura 0/11. Os outros três: o encerramento rebentava e a ligação
da tranca não largava; uma excepção deixava a única ligação do processo em
`25P02` para sempre; e um cancelamento largava a tranca com a *thread* ainda a
usar a tomada — o único caminho que a revisão encontrou para o estado de um
*tenant* chegar a outro. Vinte corrigidos, dois declarados.

**Três conflitos do canon que este ticket nomeia e não resolve.** A retenção
tem 30 dias de inactividade no `../docs/tecnica/02` §12 e 90 dias após o fecho
no `../docs/tecnica/08` §7.1, e «fecho de conversa» não está definido em
documento nenhum. O `E4` §2.6 dá o `langgraph-checkpoint-postgres` como «MIT,
sem restrições» porque olhou o pacote e não o fecho. E o `../docs/tecnica/06`
§7.6.2 diz que os *checkpoints* são cifrados com a DEK do contacto, o que nem o
§12 nem este bloco nomeiam — o `SerializerProtocol` do LangGraph tem um
`CipherProtocol`, pelo que o sítio existe, e a decisão fica por tomar com dono.

---

## KAM-027 — AgentRegistry e validação no arranque (YAML, nós obrigatórios, licenças)

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-025, KAM-009 |
| Bloqueia | KAM-031, KAM-035, KAM-038, KAM-118 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§5.1, §5.2, §5.4), `../docs/tecnica/00_Arquitectura_Solucao.md` (§4 REG, ADR-011, ADR-012), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.6) |

### Contexto

Uma vertical é um tuplo de configuração `(grafo, tools autorizadas, persona, entitlements, subscrições)` (ADR-012). O registo (`registry/*.yaml`) permite activar e desactivar verticais por tenant e é o ponto onde se garante que `assistente` (Fluxo B, `phase: D`) nunca corre em produção no Piloto (ADR-011). O CHR devolve `vertical`; o REG verifica o entitlement.

### Objectivo

Implementar o `AgentRegistry` com carregamento e validação fail-closed no arranque (falha o deploy), resolução por contexto e entitlement, e os dois ficheiros `registry/vendedor.yaml` e `registry/servicos.yaml` conforme `../docs/tecnica/02` §5.1.

### Critérios de Aceitação

- [ ] `load_all(env)` falha o arranque (exit ≠ 0) se qualquer das 6 validações de `../docs/tecnica/02` §5.2 falhar; cada uma tem um teste negativo dedicado (6 testes).
- [x] Uma tool no YAML que não existe no catálogo da TLS, ou cujo esquema visível ao modelo tenha parâmetro `tenant_id`, `merchant_id`, `seller` ou `account`, reprova o arranque.
- [x] O grafo compilado sem algum dos nós `ingest`, `guard_in`, `validate`, `guard_out`, `send`, `handoff_wait` reprova o arranque (teste de contrato).
- [x] `phase: D` com `KAMBA_FASE=piloto` é rejeitado; `registry/assistente.yaml` não existe no ambiente de produção do Piloto.
- [x] `subscriptions` com tipo ou versão desconhecidos no catálogo de eventos reprova o arranque.
- [x] `resolve(ctx)` sem entitlement activo devolve a resposta estática «serviço indisponível» e emite alerta; com entitlement activo devolve a vertical; uma só vertical principal por número no Piloto.
- [x] Arranque falha se um pacote proibido (`langgraph_api`, `langgraph_runtime_inmem`) for importável ou constar do SBOM do ambiente.
- [x] A validação (6) «dataset golden existe e o gate está verde» corre em modo **aviso** até existir KAM-040 e passa a **bloqueante** quando este ficar `Done` (registo explícito em `registry/gates.yaml`).

### Detalhes Técnicos

- **Componentes:** REG, TEN (entitlements, KAM-009), TLS. Módulos: `kamba/registry/{loader,schema,validate,resolve}.py`; esquema Pydantic com `extra="forbid"`; `version` em SemVer (grafo + prompts + tools).
- Chaves de `entitlements.limites` têm de existir no TEN: `../docs/tecnica/02` usa `valor_max_pedido_kz` e `../docs/tecnica/03` §5.2 exemplifica `manual_max_minor`. A divergência nominal resolve-se com o KAM-009 (e unidades em minor); este ticket só garante que a chave referida existe.
- `servicos.yaml` subscreve `payment.confirmed` v1; o Piloto usa `ManualProvider`, cujo evento é `payment.manual_confirmed` (KAM-055): acrescentá-lo às subscrições (*proposta*, ver KAM-038).
- **Contrato:** `Vertical(Protocol)` com `build_graph(deps)`; `deps` injecta ToolLayer, LLM, HND, Outbound.
- A validação de licenças é *defesa em profundidade*; o bloqueio principal está no CI (KAM-025, KAM-067).

```yaml
# registry/gates.yaml — a forma entregue. **Estilo de bloco, nao de fluxo:** o
# `tools/kamba_yaml.py` (gates 7, 9 e 11) nao le mapas `{ ... }`, e a primeira
# versao deste exemplo — copiada a letra — punha o gate 7 vermelho.
version: 1.0.0
gates:
  vendedor:
    golden: golden/vendedor/v1
    validacoes:
      golden:                 # passa a bloqueante com KAM-040: apaga-se a linha
        modo: aviso
        credor: KAM-040
```

O `golden_gate: warn` do esboco inicial virou `validacoes.golden.modo: aviso`,
e por uma razao: sao **tres** as validacoes que esperam por um credor e nao uma
(a (1) pelo KAM-028 e a (3) pelo KAM-031/KAM-035), e tres chaves de topo
diferentes para a mesma ideia eram tres sitios para esquecer uma. `bloqueio` e a
omissao e nao se escreve, um `aviso` exige `credor`, e um `aviso` que sobreviva
ao credor e **erro de arranque** — e isso que torna «fechar um gate e apagar uma
linha» uma regra imposta.

### Testes Requeridos

- Unit: parsing/validação do YAML (positivo e 6 negativos).
- Contrato: grafo compilado de teste com e sem nós obrigatórios.
- Integração: `resolve` com tenant com e sem entitlement; arranque do AGR com registo inválido.
- Arquitectura: nenhuma referência a nomes de vertical no código do registo (`core/`).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Isolamento de tenant:** `resolve` usa o `tenant_id` do contexto; entitlement lido sob RLS (ADR-015).
- [x] **Dependências:** versões fixadas; lista de bloqueio respeitada (ADR-002).
- [x] **Eval-gate:** o registo é artefacto comportamental; SemVer atribuído; gate golden pendente de KAM-040, registado em `registry/gates.yaml`.
- [x] Documentação do esquema YAML e ADRs afectados actualizados; sem TODOs órfãos.

### Verificação dos Critérios de Aceitação

Medido a 2026-10-25, no ramo `feature/KAM-027-agentregistry` (base `publico/main`,
`147bc8e`). Os comandos correm da raiz do repositório. Não há `make` nesta
máquina (`docs/adr/ADR-L001` §1); as vias usadas estão em
`.claude/skills/agentic-engineering/references/evidencia-e-verificacao.md`.

| # | Critério | Estado | O que se mediu, com que comando, e que número saiu |
|---|---|---|---|
| 1 | `load_all(env)` falha o arranque se qualquer das 6 validações falhar; 6 testes negativos dedicados | **parcial** | **Os 6 negativos existem e cada um mede uma validação:** `TestSeisNegativos`. **O arranque falha:** `TestRegistoNoArranque` corre o `main()` real → **5** com directório inexistente e com ficheiro inválido, `uvicorn.run` nunca chamado. **E qualquer problema real de qualquer das seis reprova o arranque — modo nenhum o cala**, que é a correcção descrita no critério 2. **O que falta à letra, e só isto:** um problema da classe «a fonte que esta validação confronta não existe neste repositório» (`PorLigar`) é aviso para três delas, e o critério 1 não abre essa excepção — o critério 8 abre-a só para a (6). Ver «as três validações que esperam», abaixo; credores **KAM-028** (1), **KAM-031**/**KAM-035** (3) e **KAM-040** (6) |
| 2 | Tool fora do catálogo da TLS, ou com parâmetro `tenant_id`/`merchant_id`/`seller`/`account` visível ao modelo, reprova o arranque | **satisfeito** | **Reprova sempre, e isso é uma correcção da revisão adversarial.** A primeira versão punha a validação inteira em `aviso`, e com isso, no dia em que o KAM-028 ligasse o catálogo, uma tool inexistente passava a aviso porque a linha do `gates.yaml` sobreviveria ao credor. Agora o `aviso` cala **uma classe** de problema — `PorLigar`, «a fonte não existe aqui» — e qualquer outro bloqueia seja qual for o modo: `test_o_aviso_cala_a_fonte_em_falta_e_nao_um_problema_real` mede-o com o `tools` em `aviso` e um catálogo ligado a que falta `criar_pedido`, e com um que expõe `tenant_id`. Mais: `test_1_uma_tool_fora_do_catalogo_da_tls_reprova` e `test_1_uma_tool_que_expoe_tenant_id_ao_modelo_reprova` (4 sub-testes, um por parâmetro). Mutações `a tool deixa de ser confrontada com os parametros proibidos` e `o aviso deixa de distinguir a fonte em falta do problema real` → **apanhadas**. **O limite, escrito:** não há catálogo da TLS no repositório, pelo que no arranque de hoje não se confronta tool nenhuma — o que sai é um aviso que nomeia o **KAM-028**, e um `aviso` que sobreviva ao credor é, ele próprio, erro de arranque |
| 3 | O grafo compilado sem algum dos nós `ingest`, `guard_in`, `validate`, `guard_out`, `send`, `handoff_wait` reprova o arranque (teste de contrato) | **satisfeito** | **Contra um `CompiledStateGraph` real do LangGraph**, não um duplo: `TestContratoDoGrafo` constrói `StateGraph(...).compile()` e mede 6 sub-testes, um por nó em falta; e mede que o `__start__` que o LangGraph acrescenta **não** conta como nó. Pela mesma correcção do critério 2, um nó em falta **bloqueia** com o `grafo` em `aviso` — `test_o_aviso_cala_a_fonte_em_falta_e_nao_um_problema_real` mede-o. Mutações `a validacao dos nos passa a ser por igualdade` e `os sentinelas do LangGraph passam a contar como nos` → **apanhadas**. **O limite, escrito:** o `graph` das duas verticais aponta para `kamba_agr.verticais.<id>:build_graph`, que não existe — e não pode existir antes deste ticket, que é quem **bloqueia** o KAM-031 e o KAM-035 —, pelo que no arranque de hoje não se compila grafo nenhum e o aviso nomeia-os |
| 4 | `phase: D` com `KAMBA_FASE=piloto` é rejeitado; `registry/assistente.yaml` não existe no ambiente de produção do Piloto | **satisfeito** | `test_5_phase_d_com_kamba_fase_piloto_reprova`; `test_5_a_variavel_ausente_trata_se_como_piloto` (ausente **e** vazia, pela regra do `fluxo_piloto` do KAM-003); `test_5_phase_d_fora_do_piloto_passa`. E `test_nenhuma_vertical_do_repositorio_esta_em_fase_diferida`: as duas verticais do `registry/` têm `phase: P` e `registry/assistente.yaml` **não existe**. Corre em `bloqueio`. Mutação `a fase deixa de tratar a variavel vazia como piloto` → **apanhada** |
| 5 | `subscriptions` com tipo ou versão desconhecidos no catálogo de eventos reprova o arranque | **satisfeito** | Contra o catálogo real (`kamba_core.eventos.contratos.CATALOGO`, 38 tipos, verificado em `test_4_o_catalogo_vem_dos_contratos_e_nao_de_uma_copia` contra `contratos/eventos/`): `test_4_um_tipo_de_evento_desconhecido_reprova` e `test_4_uma_versao_desconhecida_reprova_em_vez_de_ser_ignorada` (uma `versao: 9` dá «as versoes publicadas sao v1, v2»). Corre em `bloqueio` |
| 6 | `resolve(ctx)` sem entitlement activo devolve a resposta estática «serviço indisponível» e emite alerta; com entitlement activo devolve a vertical; uma só vertical principal por número no Piloto | **satisfeito** | `TestResolve`, 8 testes: sem entitlement → `resposta="servico_indisponivel"`, `motivo="sem_entitlement"`; com entitlement → a vertical; vertical desconhecida → a mesma resposta com `motivo="vertical_desconhecida"` e **zero** leituras de entitlement. Com as duas verticais carregadas, um contexto de `vendedor` nunca devolve `servicos`. **E o «emite alerta» mede-se contra o `MetricasDoAgr` real e não contra um duplo** — `test_o_alerta_conta_contra_as_metricas_reais_e_nao_so_contra_um_duplo` lê a exposição e encontra `agr_registry_denied_total{motivo="…"} 1` para os dois motivos. **Era preciso: o contador não estava registado em `metricas.py`**, o `contar` levantava `EtiquetaInvalida`, e os sete testes com duplo passavam — ver o defeito (b), abaixo. Mutação `resolve deixa de exigir entitlement activo` → **apanhada**. **Nada chama o `resolve` em produção**: quem o chama é o ticket que tiver um grafo (KAM-031) |
| 7 | Arranque falha se um pacote proibido (`langgraph_api`, `langgraph_runtime_inmem`) for importável ou constar do SBOM do ambiente | **satisfeito** | A primeira metade era do KAM-025. A segunda é deste ticket: `egresso.exigir_sbom_mit()` lê `importlib.metadata.distributions()`. `TestSbomDoAmbiente`, 11 testes: cada uma das **11** entradas de `tools/blocklist.yaml` que podem estar em Python morde; a normalização é a de PEP 503; metadados corrompidos não derrubam o arranque. **A paridade com o `lint_arch` chama o `versions.satisfies_floor` verdadeiro** — e não uma reimplementação dele — sobre 25 nomes × 12 versões = **300 casos**, e as duas decidem o mesmo em todos. Foi a revisão adversarial que o exigiu, com razão: a comparação caseira divergia em dois casos — `litellm==1.83` (o lint permitia, a guarda bloqueava) e `litellm==1.84.0.post1` (a guarda **permitia**, o lint bloqueava). A segunda era a grave: o controlo que protege o que **corre** era mais frouxo do que o do CI. As duas têm teste com nome próprio. **E fechou-se uma lacuna que a paridade descobriu:** o `psycopg2-binary` é LGPL, as duas listas de requisitos recusavam-no em prosa, e **nem a lista de bloqueio nem a guarda o tinham** — as entradas `psycopg` são `exact` e não lhe batem. Entrou nas duas, com ADR e evidência. Mede-se também o caso que justifica esta metade existir: o `langgraph-checkpoint-postgres` instala `langgraph.checkpoint.postgres`, o `exigir_biblioteca_mit()` passa (com razão) e o `exigir_sbom_mit()` apanha-o. No `main()`: **3**. Quatro mutações → **apanhadas** |
| 8 | A validação (6) corre em modo **aviso** até existir KAM-040 e passa a **bloqueante** quando este ficar `Done` (registo explícito em `registry/gates.yaml`) | **satisfeito** | `registry/gates.yaml` existe, é a **terceira forma** da superfície do registo, e declara `golden: { modo: aviso, credor: KAM-040 }` para as duas verticais. Medido nos dois lados: `test_o_ficheiro_do_repositorio_cobre_as_tres_validacoes_adiadas` (*gate* 3b) e `test_o_registo_do_repositorio_carrega_com_tres_avisos_por_vertical` (o AGR). **E a passagem a bloqueante mede-se nas três linhas, uma a uma** — `test_apagar_a_linha_do_gates_torna_cada_validacao_bloqueante`, um sub-teste por validação. A primeira versão media só a linha do `tools`, e o critério 8 — que é sobre o `golden` — ficava provado pela linha errada: achado da revisão adversarial. **Mais:** um `aviso` que sobreviva ao credor é **erro de arranque** (`test_um_aviso_que_sobreviveu_ao_credor_e_erro`), o que faz de «fechar um aviso é apagar uma linha» uma regra imposta e não uma intenção |

**As três validações que esperam, e porque é que isto não é o critério 1
cumprido em espírito.** O critério 1 pede que as seis falhem o arranque; o
critério 8 do mesmo bloco carva a (6) dessa regra e dá o mecanismo (modo
`aviso`, registado em `registry/gates.yaml`, com o ticket que o fecha). A (1) e
a (3) entram pelo mesmo mecanismo porque **as fontes delas não podem existir
antes deste ticket**: o catálogo da ToolLayer é o KAM-028, e um grafo compilado é
o KAM-031/KAM-035 — dois tickets que o KAM-027 **bloqueia**. As dependências
deste ticket são KAM-025 e KAM-009, as duas fundidas.

Isto é uma **inversão no próprio bloco**, não uma lacuna da entrega, e fica
registada em vez de resolvida em silêncio: o critério 1 foi escrito a assumir
fontes que a ordem do backlog põe depois. As três alternativas e porque se
escolheu esta:

| Alternativa | Porque não |
|---|---|
| Devolver as validações verdes | É o defeito que o próprio bloco avisa — «um critério pode estar satisfeito pela razão errada». Com um catálogo em falta a devolver verde, o registo carregava sem nunca ter confrontado tool nenhuma. **Há uma mutação que o prende** (`o catalogo em falta passa a validacao verde` → apanhada) |
| Pô-las a falhar o arranque | O AGR deixava de arrancar hoje por causa de dois tickets de amanhã, e o `/healthz` que o esqueleto andante do KAM-108 precisa morria com ele |
| Um mecanismo próprio para cada | Três maneiras de dizer «esta validação espera por um ticket» eram três sítios para esquecer uma. O do critério 8 já existe e nomeia o credor |

**Uma validação em `aviso` não é uma validação que passa, e o `aviso` cala
uma classe de problema — não a validação.** Um problema é de uma de duas
classes: `PorLigar` («a fonte que esta validação confronta não existe neste
repositório») ou qualquer outro («confrontei e está errado»). O `modo: aviso`
cala **só** o primeiro; o segundo reprova o arranque seja qual for o modo.

A distinção é a correcção do achado mais sério da revisão adversarial, e vale
escrever o caso que ela nomeou: sem ela, no dia em que o KAM-028 ligasse o
catálogo, uma tool inexistente — ou uma que exponha `tenant_id` ao modelo —
passava a ser **aviso**, porque a linha `tools: { modo: aviso }` sobreviveria ao
credor. O mecanismo de adiamento engolia o defeito que a validação existe para
apanhar, e o que hoje é «parcial» tornava-se «não satisfeito» sem ninguém dar
por isso. É por causa dela que os critérios 2 e 3 ficam cumpridos **à letra**.

**E um `aviso` que sobreviva ao credor é erro de arranque.** Se uma validação em
`aviso` não devolver problema nenhum de `PorLigar`, a fonte dela já existe, a
linha do `gates.yaml` está morta, e o arranque falha a dizê-lo. É a disciplina
do `canon/extensoes.yaml` — «uma extensão que nenhuma superfície usa falha o
gate» — e é o que torna «fechar um aviso é apagar uma linha» uma regra imposta
em vez de uma intenção escrita.

O arranque registra uma linha por par (validação, credor), com `error_code` na
forma `tools_kam_028`; um `aviso` que não aparecesse no registo de arranque era
uma validação adiada em silêncio.

**O que este ticket não liga, e porquê.** O `grafos=` do `ExecutorDeTurnos`
continua a ser o `sem_grafos` que o KAM-025 lá deixou, e `/internal/turn` com
uma invocação válida continua a responder **503**. Ligar o registo à porta hoje
trocava um 503 (`GrafoNaoRegistadoError`) por outro 503 (o alvo de `graph` não
resolve) e punha uma leitura de entitlement no caminho de **cada** turno, para
nada. Pela mesma razão o `checkpointer` não chega a `compile(checkpointer=...)`:
não há grafo que o receba. **O AGR continua a não ir a produção antes do
KAM-031**, como o §1 de `docs/agr.md` já dizia.

### Verificação do Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | **Sete dos oito** satisfeitos (2 a 8); o critério **1** está `parcial`, pela inversão de dependências descrita acima — a letra dele não abre a excepção que o critério 8 do mesmo bloco abre para a validação (6), e que as (1) e (3) precisam por as fontes delas estarem em tickets que este **bloqueia**. Os critérios 2 e 3 passaram de `parcial` a satisfeito com a correcção do mecanismo do `aviso` (revisão adversarial). A caixa fica **vazia**: marcá-la com um critério `parcial` era transformar o DoD num enfeite |
| **Isolamento de tenant:** `resolve` usa o `tenant_id` do contexto; entitlement lido sob RLS (ADR-015) | **parcial** | Primeira metade **medida**: `test_o_entitlement_le_se_com_o_tenant_do_contexto_e_o_modulo_da_vertical` — o único argumento do `resolve` é o contexto, e o par `(tenant_id, modulo)` que chega ao leitor é o dele. O `ContextoDeResolucao` tem **dois** campos e nenhum vem de texto (a invariante é do `contexto.py` do KAM-025, medida em `test_isolamento.py`). Segunda metade **não ligada**: quem lê o entitlement é a porta injectada, e em produção ninguém constrói um `AgentRegistry` porque ninguém chama `resolve`. A leitura sob RLS é do chamador. Credor **KAM-031** |
| **Dependências:** versões fixadas; lista de bloqueio respeitada (ADR-002) | **satisfeito** | `python tools/pip_lock.py --check-offline` nos três `.in` → «coerente com os pins» nos três. O fecho do AGR passa de 43 para **46** pacotes: `langgraph==1.2.17`, `langgraph-prebuilt==1.1.1` e `langgraph-sdk==0.4.9`, os três **MIT** (lido no `license_expression` do PyPI e no `METADATA` instalado, 2026-10-25) e registados em `ci/supply-chain/licencas.yaml`. `lint_arch all` → «lista de bloqueio: conforme», «estrutura: conforme». *Gate* 11: `sbom check` → 179 componentes, **168 permitidas, 0 fora**, 0 CRITICAL; `supply_chain check` → 24 componentes registados, conforme. `langgraph_api` e `langgraph_runtime_inmem` continuam bloqueados, e agora também em *runtime* pelo SBOM |
| **Eval-gate:** o registo é artefacto comportamental; SemVer atribuído; gate golden pendente de KAM-040, registado em `registry/gates.yaml` | **satisfeito** | `version: 1.0.0` nos três ficheiros novos, e o SemVer é **imposto** e não convenção: `test_a_versao_e_semver` recusa `1.0`, `v1.0.0`, `1.0.0-rc1` e `ultima`. O gate golden está em `registry/gates.yaml` com `credor: KAM-040` — ver o critério 8 |
| Documentação do esquema YAML e ADRs afectados actualizados; sem TODOs órfãos | **satisfeito** | `registry/README.md` (as três formas, e porque é que apagar uma linha é que fecha um gate); `docs/agr.md` §7-B novo, mais o §1, §4 e §5 (versão 1.3); `docs/ci.md` §3 (a superfície 3 passa a ter três formas) e versão 1.54; `specs/02` §3.26 e emenda **1.35**. **ADR afectado:** `docs/adr/ADR-L001` §4 ganha nota e versão 1.2 — a premissa daquela decisão (o **custo** de acrescentar o Pydantic) caducou com o KAM-026, e o gatilho de reversão que ela própria escreveu chegou; o Starlette fica. `grep -rn "TODO\|FIXME\|XXX"` nos ficheiros novos → **0** |

### Nomes, canon e provas

| O que | Número |
|---|---|
| Emenda ao dicionário | **1.35**, §3.26 — o contrato do `AgentRegistry`, os seis nós, as **onze** tools do catálogo do Piloto (nenhuma era nome canónico: só o `enhance_image` do §3.7 o era), os quatro parâmetros proibidos, a terceira forma do registo, o `modo` com `credor`, `servico_indisponivel`, `agr_registry_denied_total`, o código de saída `5` e o `KAMBA_REGISTRY_DIR` |
| Divergências decididas pela emenda | **três**, todas a favor da fonte mais alta: `valor_max_pedido_minor` contra o `valor_max_pedido_kz` que o §5.1 e o bloco escrevem (é a variante da emenda 1.13 — o *gate* 3b trata-a como nível 1, e um `vendedor.yaml` escrito à letra do §5.1 **não passava**); `registry/gates.yaml` contra o `gates/vendedor.yaml` dentro da vertical; e o `payment.manual_confirmed` no `servicos.yaml`, que o bloco dá como *proposta* e o §3.5 já tinha decidido |
| *Gate* 3b | `canon_lint check` → conforme, 4 ficheiros na superfície `registo` (era 1). `canon_lint canario` → 0. Suite do `canon_lint`: **226** testes, 0 falhas, com `TestGates` (11 testes, uma negativa por regra) |
| Testes, nas quatro naturezas que o bloco pede | Contados por `TestLoader.countTestCases()` e não à mão — três dos números desta linha estiveram errados por os ter estimado. **Unidade** `TestEsquema` (9) e `TestSeisNegativos` (29, com os seis negativos dedicados); **contrato** `TestContratoDoGrafo` (6, contra um `CompiledStateGraph` real do LangGraph); **integração** `TestResolve` (8), `TestFicheirosReais` (6) e `TestRegistoNoArranque` (5); **arquitectura** `TestArquitectura` (4). Mais `TestSbomDoAmbiente` (11), do critério 7. Suite do AGR: **280** testes, 0 falhas (eram 256 antes do ticket) |
| As baterias que o *gate* 4 corre, todas | **as quinze** de `tools/` mais a do `py-core` (537) e a do AGR (280). É o que o *gate* 4 vermelho me ensinou a correr: tinha corrido quatro e o `sbom check` — que não é a bateria do `sbom` |
| Prova por mutação | **18** novas, suite `agr_unit` (`services/agr/tests`, sem base de dados). `python db/mutacoes.py <venv> "registo:"` → linha de base verde, **18 corridas, 0 não apanhadas**. `python db/mutacoes.py --aplicaveis` → **725** conferidas, **0** não aplicáveis. Três das dezoito nasceram da revisão adversarial, e prendem as guardas que ela fez nascer: o `aviso` a distinguir a fonte em falta do problema real, o `aviso` morto a ser erro, e a largura das versões do SBOM |
| Duas sobreviventes, e o que elas mostraram | A primeira corrida deu **1 sobrevivente**: `o modo aviso passa a valer para todas as validacoes`. A razão era um buraco real — nenhum teste escrevia `modo: bloqueio` **por extenso**, e os dois casos de bloqueio medidos eram ambos por *omissão*, que não passa por aquela comparação. Fechada com `test_um_modo_bloqueio_escrito_por_extenso_bloqueia`. A segunda foi de outra natureza: a mutação `a largura das versoes do SBOM deixa de se igualar`, na forma `largura = len(entrada.limiar)`, sobreviveu **por ser equivalente** — com o limiar sempre mais longo ou igual, a conta da sobra fica negativa, o `(0,) * -1` é vazio, e a comparação de tuplos de comprimentos diferentes dá o mesmo resultado. Uma mutação que não pode mudar comportamento não prova nada: passou a `min(...)`, que trunca mesmo, e é apanhada. **As duas lições são diferentes** — a primeira é um teste que faltava, a segunda é uma mutação que não servia |
| Dois defeitos que a *self-validation* apanhou, e que teriam passado em silêncio | **(a)** O arranque punha a **prosa** do problema em `error_code`, e a *allowlist* de `docs/tecnica/08` §7.3 faz daquele campo um identificador de 96 caracteres: o campo **caía sem dizer nada**, e o arranque dizia ter registado os avisos sem registar nenhum — a própria coisa que o critério 8 existe para evitar. Corrigido com a `Adiada.codigo()` (`tools_kam_028`), medido contra o validador real (`kamba_core.logger.politica.validar`) e preso por mutação. **(b) O mais grave, e é do critério 6:** o `agr_registry_denied_total` não estava registado no `_AJUDA` de `metricas.py`, e o `MetricasDoAgr.contar` **levanta** `EtiquetaInvalida` («contador desconhecido») para uma métrica que ele não conheça. Os sete testes do `resolve` contavam contra um `MetricasEspia` e passavam; em produção o primeiro *tenant* sem plano fazia o turno rebentar. Encontrado a correr o `contar` real à mão, não por um teste. Corrigido: a métrica e os dois motivos passam a viver em `metricas.py` (o `registo/` importa-os, em vez de os redeclarar), o `_etiqueta_de` passa a dar `motivo` e não `outcome` — que é o que o dicionário §3.26 escreve —, e `test_o_alerta_conta_contra_as_metricas_reais_e_nao_so_contra_um_duplo` lê a exposição. **A lição não é sobre esta métrica: é que um duplo de métricas prova que se chamou `contar`, não que o contador existe** |

### Revisão adversarial

[`ANALISE-29-KAM-027-agentregistry.md`](../docs/analises/ANALISE-29-KAM-027-agentregistry.md).
Uma passagem, com os dois instrumentos (`code-review high` e `ponytail-review`)
e os achados numa lista só: **25 — 3 críticos, 8 importantes, 11 menores, 3
*nice-to-have***. Veredicto: **REPROVADO**, com nove exigidos antes do *merge*.

Os nove estão corrigidos, e três deles mudaram o desenho e não só o código:

| # | O achado | O que mudou |
|---|---|---|
| 1 | `agr_registry_denied_total` não estava em `metricas.py`; o `contar` levantava, e o critério 6 estava provado contra um duplo | A métrica e os dois motivos passam a viver em `metricas.py`; o `_etiqueta_de` dá `motivo` e não `outcome`; um teste lê a exposição real. **Encontrado também pela *self-validation*, antes do relatório** |
| 2 | O `aviso` calava a validação inteira: no dia em que o credor chegasse, um defeito real passava a aviso | A classe `PorLigar`: o `aviso` cala **só** «a fonte não existe aqui». Fez os critérios 2 e 3 passarem a satisfeitos |
| 3 | `validar_fase` deixava passar `phase: D` com qualquer `KAMBA_FASE` ≠ `piloto` — um valor que o canon não define | `FASES_POSTERIORES`, lista **vazia**: uma vertical diferida não arranca em ambiente nenhum até a Fase C entrar por emenda |
| 4, 5 | O `aviso` do `golden` engolia «o dataset não existe», e a prova de «apagar a linha» media a linha do `tools` | As duas metades do `golden` são `PorLigar` (são as duas do KAM-040); a prova passa a medir as **três** linhas, uma a uma |
| 6 | A isenção do *gate* 3b prometia um teste que prendia os nós e as tools ao dicionário, e esse teste **não existia** | Existe: `test_os_seis_nos_e_as_onze_tools_batem_com_o_dicionario` |
| 9 | O *gate* 3b aceitava um gate sem `golden`; o AGR saía com 5 em produção com o CI verde | O lint passa a exigi-lo, com negativa própria |
| 10 | A paridade do SBOM reimplementava a comparação de versões, e divergia em dois casos | Chama o `versions.satisfies_floor` verdadeiro, 300 casos; as duas divergências têm teste com nome |
| 11 | O `psycopg2-binary` (LGPL) não batia em entrada nenhuma, com os dois controlos calados | Entrou em `tools/blocklist.yaml` e na guarda, com ADR e evidência |

Dos restantes dezesseis: os de prosa e declaração foram corrigidos no mesmo PR
(o rasto que apontava para este ticket em `turno.py` e `__main__.py`, o
cabeçalho do dicionário em 1.34, o comentário «duas formas» do
`ci/canon-lint.yaml`, as dependências que o `pyproject.toml` do AGR não
declarava, o `assert` que desaparece com `-O`, o ficheiro lido duas vezes, o
nome de um teste que afirmava sobre o interpretador inteiro, e a `Resolucao` e
mais três nomes que a emenda 1.35 não registava). **Dois viraram dívida
documental**, porque são de outros donos: a lista de permitidos de
`contexto.py` recusa a vertical `catalogo` que o KAM-118 vai precisar (linha
**98**), e a guarda de arranque do ADR-011 em `fluxo_piloto` **não tem chamador
em serviço nenhum** (linha **99**). Os três *nice-to-have* ficam **declarados e
não feitos**: o `Vertical(Protocol)` com `build_graph(deps)` que a emenda
canoniza não existe em código (nasce com o KAM-031, que é quem constrói um
grafo), o `do_repositorio` não tem porta para o catálogo nem para o grafo (quem
as ligar passa-as ao `AmbienteDoRegisto`, que as tem como campos), e o `resolve`
lê entitlement por turno sem costura para cache (o `CacheDeEntitlements` do
KAM-009 existe e entra com o chamador).

**O que a revisão não correu, e diz:** bateria nenhuma — o interpretador dela
não tinha `pydantic`, `yaml` nem `langgraph`. Todos os achados vêm de leitura do
diff e do código ligado. Dos 25, **dois** não se confirmaram ao medir: a
*self-validation* já tinha fechado o 1, e a mutação que a revisão inspirou para
a largura das versões acabou por ser equivalente (ver «duas sobreviventes»).

**Um defeito que só o CI soube, e a lição é sobre leitores e não sobre YAML.**
O *gate* 7 do PR #54 abriu vermelho com
`registry/gates.yaml: mapa em estilo de fluxo nao suportado ('{')`. Há **três**
leitores de YAML a tocar `registry/*.yaml` — o `yamlreg` do *gate* 3b, o
`yaml.safe_load` do AGR, e o `tools/kamba_yaml.py` dos *gates* 7, 9 e 11 — e só
o terceiro é estrito. Os três ficheiros nasceram em estilo de fluxo, copiado à
letra do exemplo de `docs/tecnica/02` §5.1 **e do exemplo deste próprio bloco**;
os dois primeiros leitores leram-nos, as 62 baterias passaram, e o terceiro
rebentou. Os três estavam quebrados, não só o primeiro: o *gate* pára no
primeiro ficheiro por ordem alfabética.

Corrigido nos ficheiros e no exemplo do bloco, com `docs/dividas-documentais.md`
linha **100** para o §5.1, que continua a ensinar a forma que o CI recusa. E com
o teste que faltava: `test_cada_ficheiro_do_registo_le_se_pelos_tres_leitores`
exige que os três leiam cada ficheiro **e devolvam o mesmo documento** — um
leitor que aceite e leia outra coisa é pior do que um que recuse.

**E havia um segundo defeito atrás da falha, mais quieto.** O
`tools/contract_diff/subscricoes.py` promete por escrito que «quando o KAM-038
escrever o primeiro ficheiro, esta verificação começa a morder sem ninguém lhe
tocar». Não começa: ela procura a chave `subscricoes` com `versao_max` (os nomes
da tabela `evt_subscricoes`), e a forma da vertical tem `subscriptions` com
`versao`. Com os ficheiros a parsear, o *gate* 7 lê **zero** subscrições das
oito que lá estão — passaria vacuamente. Corrigido no mesmo PR, em oito linhas: o `ler`
passa a conhecer as **duas** formas — a da tabela `evt_subscricoes`, que aquele
ficheiro escrevera por antecipação, e a da vertical, que é a que existe no disco
— e o *gate* 7 passa a ler **8 subscrições, 0 sem contrato**. Os dois testes que
afirmavam `== []` e «0 subscrições declaradas» passaram a afirmar o novo número,
e um deles tinha escrito na *docstring* «se isto falhar, o KAM-038 chegou»:
chegou antes, e a promessa de que a verificação «começa a morder sem ninguém lhe
tocar» era falsa.

**Porque é que isto se corrigiu aqui e não se deixou ao KAM-038.** A propriedade
já estava garantida — a validação (4) do registo confronta tipo e versão com o
catálogo no arranque, e bloqueia. O que faltava era o controlo do **CI**, sobre
ficheiros que este ticket acabou de criar: deixá-lo a ler zero era deixar um
*gate* verde pela razão errada numa superfície minha.

**O *gate* 4 também abriu vermelho, e a lição é sobre o que eu não corri.**
`sbom.tests.test_gate11.TestSbom.test_o_grafo_do_lado_python_conta_as_dependencias_todas`
afirmava, numa lista **literal**, as quatro dependências que o
`services/agr/pyproject.toml` declarava; este ticket declarou mais três
(`langgraph`, `pydantic`, `pyyaml`) e a lista deixou de bater. Corri o `sbom
check` — que passou — e **não corri a bateria do `sbom`**: são coisas diferentes,
e o *gate* 4 corre as **quinze** suites de `tools/`, mais a do `py-core` e a do
AGR. Tinha corrido quatro.

A correcção não foi reescrever a lista: foi derivá-la do `pyproject.toml` pelos
nomes. O KAM-027 era o **segundo** ticket seguido a ter de a reescrever à mão (o
KAM-026 acrescentou-lhe o `langgraph-checkpoint`), e uma lista literal transforma
«o grafo está completo» — que é a invariante que o teste existe para proteger —
em «o grafo tem estes quatro», que é um número a envelhecer. A comparação é por
**nome** e não por `purl`: a versão vem do *lock* e é o resto daquele ficheiro
que a verifica.

**O que não se mediu, e não se diz medido.** O *gate* 8 (as *suites* contra um
PostgreSQL real) **não corre neste ticket**: nada do que ele entrega toca a base
— o registo são ficheiros e as validações leem constantes de módulo —, e a
`tests_agr` não ganhou caso nenhum. O *gate* 4 (cobertura), o *gate* 1 e o
*gate* 2 do lado Node precisam de contentor com `pnpm` e correm no CI. O
`gate 5 — reservado` falha por desenho em todos os PRs desta linha.

**Um que se mediu ao contrário do esperado:** o `lint_contagens` **corre** de
dentro deste *worktree* e dá conforme (13 contagens vivas, 0 dívidas), chamado
com raiz **relativa**, que é a forma que a dívida 44 nomeia. A dívida é sobre a
chamada com raiz absoluta.

### Handoff para Claude Code

```text
És o executor do ticket KAM-027 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-027) e docs/tecnica/02_Agent_Runtime_Verticais.md (§5).
Objectivo: AgentRegistry com load_all() fail-closed (6 validações de §5.2), resolve(ctx) com entitlement,
registry/vendedor.yaml e registry/servicos.yaml. phase D rejeitado com KAMBA_FASE=piloto (ADR-011).
- Nenhuma tool com parâmetro tenant_id/merchant_id visível ao modelo.
- Validação (6) golden: aviso até KAM-040; deixa isso explícito em registry/gates.yaml.
- Não ponhas nomes de vertical em core/.
Não expandas escopo: a ToolLayer (KAM-028) e os grafos (KAM-031/035) são tickets próprios.
Testes: unit, contrato do grafo, integração, arquitectura. PR com o template §7. Commits: feat(KAM-027): …
```

---

## KAM-028 — ToolLayer: contrato, classes read/write/money e auditoria

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-025, KAM-004, KAM-012, KAM-009 |
| Bloqueia | KAM-029, KAM-031, KAM-032, KAM-035, KAM-061, KAM-066, KAM-118 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§6.1, §6.2, §6.4, §6.5), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.2, §3.7, §4.3, §6), ADR-007, ADR-013, ADR-015 |

### Contexto

A TLS é a única via de leitura e escrita dos agentes. O modelo nunca vê nem fornece `tenant_id`: as tools são construídas por turno a partir do `ToolContext`, derivado do estado. A classificação `read`/`write`/`money` é o mecanismo de L3 contra injecção (`../docs/tecnica/08` §4.3): escrita só após botão interactivo emitido pelo runtime. O `audit_log` de KAM-012 cobre dinheiro, stock e preço; a `tool_audit` cobre todas as invocações.

### Objectivo

Implementar o contrato `ToolLayer` (`for_context`, `invoke`), o pipeline de 8 passos fail-closed, as classes de tool, a tabela `tool_audit` *append-only*, os erros tipados e os *timeouts* e *circuit breakers* por backend, com *fakes* para os backends ainda inexistentes.

### Critérios de Aceitação

- [x] `invoke` percorre, por esta ordem, os 8 passos de `../docs/tecnica/02` §6.1 e falha fechada em cada um; um teste por passo prova que o passo seguinte não corre.
- [x] Tool fora da lista `allowed` da vertical devolve `TOOL_NOT_ALLOWED`; sem entitlement activo devolve `ENTITLEMENT_DENIED`; argumento extra devolve `VALIDATION_ERROR` (`extra="forbid"`).
- [x] Nenhum esquema de tool exposto ao modelo contém parâmetro `tenant_id`, `merchant_id`, `seller` ou `account` (lint de CI, falha o build).
- [x] Tool `write`/`money` sem `Confirmation` válida (botão `confirm:{cart_id}` do **mesmo** `contact_id`, no turno actual) devolve erro e não chama o backend.
- [x] Cada invocação `write`/`money` tem 1 linha em `tool_audit` (cobertura 100%); a linha não contém texto de mensagem nem telefone, só `args_hash`, `args_redacted`, `fact_ids`.
- [x] O papel da aplicação não consegue `UPDATE` nem `DELETE` em `tool_audit` (teste SQL).
- [x] Timeouts: `read` 2 s, `write`/`money` 8 s; *circuit breaker* abre após falhas consecutivas configuráveis e devolve `UPSTREAM_DOWN` sem chamar o backend.
- [ ] `TENANT_MISMATCH` nunca é repetido e gera alerta de segurança; X-02: cada tool invocada com estado de A e referência a entidade de B devolve 0 canários.

### Detalhes Técnicos

- **Componentes:** TLS, TEN (entitlements), COM/PAY/IDX por *adapters* (fakes agora), `tool_audit` no Postgres. Módulos: `kamba/tls/{context,layer,pipeline,errors,breaker,audit}.py`, `kamba/tls/specs/` (uma spec por tool: nome, `klass`, versão, modelo Pydantic).
- **Contexto:** `ToolContext(tenant_id, channel_id, contact_id, conversation_id, turn_id, vertical, run_id, graph_version)` imutável, construído de `ConversaState`. O backend recebe `tenant_id` em cabeçalho **e** `SET LOCAL app.tenant_id` (RLS; as tabelas do Medusa são protegidas pelo adaptador COM).
- **Tools de Piloto** (catálogo em `../docs/tecnica/02` §6.2): as especificações das tools do Vendedor são registadas por KAM-031 e as de Serviços por KAM-035; aqui entra o *framework* e `get_store_info` como primeira tool real.
- Não existe tool de envio de mensagem; não existe, nas verticais voltadas ao cliente, tool que altere preço, stock ou estado de pagamento (teste enumera catálogo × `registry/*.yaml`).
- `tool_audit` segue o DDL de `../docs/tecnica/02` §6.4 (`REVOKE UPDATE, DELETE` + trigger). Distinta de `audit_log` (KAM-012): `money`/stock/preço escrevem em ambas.
- Erros tipados: `NOT_FOUND`, `OUT_OF_STOCK`, `PRICE_CHANGED`, `LIMIT_EXCEEDED`, `ENTITLEMENT_DENIED`, `TOOL_NOT_ALLOWED`, `TENANT_MISMATCH`, `UPSTREAM_TIMEOUT`, `UPSTREAM_DOWN`, `VALIDATION_ERROR`.

### Testes Requeridos

- Unit: validação de argumentos, mapeamento de erros, *breaker*.
- Integração (Postgres real): `tool_audit` append-only, `SET LOCAL app.tenant_id`, entitlement e limites.
- Isolamento: X-02 (todas as tools do REG) e lint de esquema; sessão sem `app.tenant_id` devolve 0 linhas.
- Arquitectura: nenhum import de repositório de escrita fora da TLS.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] **Isolamento de tenant:** `tenant_id` do estado e RLS `FORCE`; teste cruzado cobre o novo caminho (ADR-015).
- [x] **Idempotência:** o ponto de extensão da chave existe (preenchido por KAM-029); `write`/`money` nunca correm sem chave.
- [x] **Pagamento só por evento autenticado:** nenhuma tool do catálogo muda `payment_events` nem o estado de pagamento (ADR-013).
- [x] **Números só de tools:** a TLS devolve `facts` com `fact_id`, `kind`, `retrieved_at` (ADR-007).
- [x] **Privacidade e custo:** auditoria sem conteúdo nem telefone; métricas de latência e erro por tool.
- [ ] Revisão por dois revisores (P0 de isolamento/dinheiro); documentação actualizada.

### Verificação dos Critérios de Aceitação

Medido no ramo `feature/KAM-028-toollayer-contrato-classes-auditoria`, cortado de
`publico/main` (`e286e89`). **Seis critérios marcados, dois parciais; cinco
caixas do DoD marcadas, duas vazias.** Cada linha diz o que se mediu, com que
comando, e o número que saiu.

**Uma armadilha de ambiente, para quem conferir:** o *worktree* deste trabalho
nasceu sobre a linha do remoto `origin`, que **não tem** o KAM-025/026/027, e o
`git merge-base` contra `publico/main` sai com **código 1** (sem antepassado
comum) em vez de dizer que são duas histórias. Confere o `git rev-parse HEAD`
antes de qualquer leitura.

#### Critério 1 — os oito passos, por ordem, falhando fechada em cada um

**Satisfeito.** Os oito passos são funções e a ordem é dados: o `PASSOS` do
`services/agr/src/kamba_agr/tls/camada.py`. Isso é o que torna a ordem
afirmável e o que permite a cada teste substituir os passos seguintes por
espiões.

* ordem: `test_a_ordem_e_a_dos_oito_passos_do_documento` compara
  `nomes_dos_passos()` com os oito nomes do §6.1 →
  `("allowlist", "entitlement", "argumentos", "confirmacao", "idempotencia", "backend", "auditoria", "facts")`, `len(PASSOS) == 8`;
* **um teste por passo**, em `services/agr/tests/test_tls.py::TestOitoPassos`:
  por cada passo, parte-se de uma invocação que passaria, estraga-se só o que
  aquele passo verifica, e confere-se `corridos == []` — a lista dos passos
  seguintes que correram. Treze testes, um por forma de recusa dos passos 1 a 6,
  mais os do 7 e do 8.

```
PYTHONPATH="tools;libs/py-core/src;services/agr/src;services/agr/tests" \
  .venv/Scripts/python.exe -m unittest discover -s services/agr/tests -t services/agr/tests
→ Ran 371 tests ... OK
```

#### Critério 2 — `TOOL_NOT_ALLOWED`, `ENTITLEMENT_DENIED`, `VALIDATION_ERROR`

**Satisfeito**, e os três medidos nos dois sítios onde a resposta pode diferir:

* unidade — `test_passo_1_tool_fora_do_allowed_devolve_tool_not_allowed`,
  `test_passo_2_sem_entitlement_devolve_entitlement_denied`,
  `test_passo_3_argumento_extra_devolve_validation_error`;
* **contra a base** — `db/tests_agr/test_tool_audit.py::TestPipelineReal`:
  `test_sem_entitlement_activo_devolve_entitlement_denied` e
  `test_o_entitlement_desactivado_tambem_nega` correm o `hook_de_tool` do
  KAM-009 contra a `platform.entitlements` a sério. Uma base falsa compara SQL
  por texto e nunca o interpreta.

O passo 2 **não é código novo**: é o `hook_de_tool` que o KAM-009 escreveu para
esta camada pelo nome (`libs/py-core/src/kamba_core/ten/hook.py`, «o §6.1 passo
2 … é este módulo»).

#### Critério 3 — nenhum esquema exposto ao modelo com os quatro parâmetros

**Satisfeito, e é *gate* e não teste solto**, como o critério pede («falha o
build»): `tools/lint_arch/tool_schema.py`, no subcomando `tool-schema` e no
`all` do `lint_arch` — que corre no *gate* 2 e no 11. Não abre *gate* novo.

```
cd tools && ../.venv/Scripts/python.exe -m lint_arch --root .. tool-schema
→ lint_arch: esquemas de tool: conforme   (exit 0)
.venv/Scripts/python.exe -m unittest discover -s tools/lint_arch/tests -t tools -p test_tool_schema.py
→ Ran 14 tests ... OK
```

Das catorze, **seis são canários** — o que prova que o *lint* morde: os quatro
parâmetros um a um, `extra="allow"`, e a escrita no `platform` fora da TLS. Um
`check` que devolvesse sempre `[]` passava o primeiro teste e falhava os outros
seis.

**E uma descoberta que mudou o código:** a *docstring* de um modelo Pydantic
entra no `model_json_schema()` como `description`, e o esquema **é o que vai ao
modelo de linguagem**. A primeira versão do `ArgumentosDeGetStoreInfo`
explicava-se com uma frase que dizia `tenant_id` por extenso. Não é um
parâmetro — o critério fala de parâmetros — mas ensinava ao modelo um nome que
ele não tem de conhecer. Apanhado por
`test_o_esquema_que_vai_ao_modelo_nao_tem_o_contexto`, que olha para o esquema
**inteiro** e é por isso mais estrito do que o critério.

#### Critério 4 — `write`/`money` sem `Confirmation` válida

**Satisfeito.** As três perguntas do critério são três testes, e **dois
códigos** diferentes porque são duas naturezas:

| O que falha | Código | Teste |
|---|---|---|
| sem botão | `VALIDATION_ERROR` | `test_passo_4_sem_confirmacao_devolve_erro_e_nao_chama_o_backend` |
| botão de outro carrinho | `VALIDATION_ERROR` | `test_passo_4_confirmacao_de_outro_carrinho_e_recusada` |
| botão de um turno anterior | `VALIDATION_ERROR` | `test_passo_4_confirmacao_de_outro_turno_e_recusada` |
| botão de **outro contacto** | `TENANT_MISMATCH` | `test_passo_4_confirmacao_de_outro_contacto_e_tenant_mismatch` |

A última é de outra natureza e por isso leva outro código: é uma escrita no
carrinho de uma pessoa autorizada por outra, que é a exfiltração entre
contactos do `../docs/tecnica/08` §4.4, e o §6.5 classifica-a como violação. As
três primeiras têm recuperação («o runtime emite o botão»), e é o tratamento
que o §6.5 dá ao `VALIDATION_ERROR`.

«Não chama o backend» mede-se pelos espiões: `corridos == []` em todos os
quatro.

#### Critério 5 — uma linha em `tool_audit` por invocação, sem conteúdo

**Satisfeito, com uma excepção nomeada.**

* cobertura — `db/tests_agr/test_tool_audit.py::TestCobertura`:
  `test_cada_invocacao_money_deixa_exactamente_uma_linha` (cinco invocações →
  **5** linhas, `status` todas `ok`) e `test_uma_recusa_tambem_deixa_linha`
  (quatro recusas → **4** linhas, `status` todas `erro`). Uma invocação
  recusada é uma invocação, e o critério diz **cada**;
* **a excepção:** uma tool que o catálogo **não conhece** não tem `klass`, e o
  `klass` é `NOT NULL`. Não há linha possível, e não é uma invocação de classe
  `write` nem `money` — porque não é de classe nenhuma. Está escrita na
  *docstring* do `camada.py` e medida em
  `test_uma_tool_fora_do_catalogo_nao_deixa_linha_e_diz_se_porque`;
* privacidade — `TestPrivacidade` varre `to_jsonb(tool_audit)::text` com dois
  canários (um telefone de forma angolana e um texto com nome) → **0**
  ocorrências. E tem **controlo**: `test_o_varrimento_procura_nos_dados_e_nao_no_nome_das_colunas`
  semeia o canário pelo caminho legítimo e exige que o varrimento o **encontre**
  (**1** ocorrência). Sem o controlo, um varrimento que procurasse no sítio
  errado dava zero e o critério passava pela razão errada — que é o que o
  KAM-026 pagou.

**E o varrimento encontrou duas fugas reais, em sítios onde ninguém tinha
olhado.** A primeira: o executor de ensaio devolvia `fact_id=f"f-{cart_id}"`, e o
`fact_id` vai para a coluna `fact_ids` — um `fact_id` derivado de um argumento
**põe texto do cliente no registo de auditoria**, pelo caminho que o critério
fecha para o `args_redacted`. A regra fica escrita para quem vai cunhar
`fact_id` a sério (KAM-031, KAM-032): **um `fact_id` é opaco** — e a revisão
adversarial notou que uma regra escrita não é imposta por ninguém, pelo que hoje
é máquina: a montagem da linha de auditoria **recusa** um `fact_id` que contenha
um valor de argumento (`FactIdDerivadoError`, `TestFactIdOpaco`). É a parte que
a camada pode impor sem saber o que é opaco para cada tool.

A segunda foi da revisão adversarial, e é da mesma classe: **os nomes dos
argumentos iam em claro.** As chaves de `args` vêm do modelo de linguagem, e um
nome é texto tanto como um valor — `{"contacto 999123456789": "x"}` punha um
telefone na `tool_audit` pela coluna que este critério fecha para os valores, e
punha-o pelo caminho `VALIDATION_ERROR`, que é precisamente onde um argumento
inventado chega. Hoje só passam os nomes que o esquema **declara**; o resto
conta-se em `<nao_declarados>`, que é informação útil e não é um canal. Sem
`declarados`, **nenhum** nome passa: falha fechada.

**O que fica aberto, com o credor: a janela do passo 7.** O §6.1 põe o registo
**depois** da chamada ao backend, pelo que uma escrita que falhe deixa um efeito
sem linha. A camada faz três coisas por isso e nenhuma é esconder: o arranque
confirma que o `INSERT` funciona e recusa subir se não (código **6**, o que tira
a causa de longe mais provável, que é configuração); em execução a falha
**levanta** em vez de devolver `ok`, o turno falha e o *job* volta à fila; e as
métricas contam mesmo nesse caminho. O que fecha a janela por inteiro é a
idempotência do **KAM-029**: com a chave, a repetição do turno reencontra o
resultado em vez de repetir o efeito. Até lá, para uma `money`, o pior caso é um
efeito repetido — que é o que a chave existe para impedir — e não um efeito sem
registo em silêncio.

**E o controlo do varrimento teve de mudar de caminho, o que é o controlo a
funcionar.** Ele semeava o canário num nome de argumento e chamava-lhe
legítimo; quando a redacção fechou esse caminho, o controlo **falhou** — que é
exactamente o que um controlo serve para fazer. O caminho que fica é a
`idempotency_key`, que é texto do chamador numa coluna de texto (e não é um
buraco: a chave do §6.3 é um `sha256`).

#### Critério 6 — o papel da aplicação não altera nem apaga `tool_audit`

**Satisfeito**, e nas três camadas da `0006`, porque nenhuma sozinha basta:

| Camada | Teste | O que mede |
|---|---|---|
| `REVOKE` | `test_o_papel_da_aplicacao_nao_consegue_update_nem_delete` | `kamba_app` leva `42501` em `UPDATE` e em `DELETE` |
| *trigger* | `test_nem_o_dono_das_tabelas_consegue` | o dono (`admin`) leva `23000` em `UPDATE`, `DELETE` e `TRUNCATE` — o `REVOKE` **não** o prende |
| `ENABLE ALWAYS` | `test_o_trigger_resiste_ao_session_replication_role` | com `session_replication_role = replica`, o `DELETE` continua a levar `23000` |

E `test_os_dois_triggers_estao_enable_always` lê o `tgenabled` do
`pg_trigger` → `"A"` nos dois. **O privilégio de tabela não mostra isto**: o
`db/tests/test_privilegios.py` vê o `kamba_migrator` com tudo, e é o *trigger*
que o impede.

#### Critério 7 — *timeouts* e *circuit breaker*

**Satisfeito**, e a revisão adversarial é a razão pela qual deixou de ser
parcial: **nenhum tecto era imposto pela camada**, nem o de `read`. Um executor
de 5 s contra o tecto de 2 s devolvia `ok=True` em 5,01 s — o `timeout_ms` era
passado e só o `get_store_info` o honrava, do lado do servidor. Hoje a camada
impõe-o, e os dois lados existem:

* **o tecto do backend** é o `timeout_ms` que o executor recebe. Para o backend
  `plataforma` é um `SET LOCAL statement_timeout`, do lado do servidor, e é ele
  que também pára a consulta na base;
* **a espera da camada** é a rede por baixo, para um executor que ignore o seu:
  `asyncio.wait_for` sobre o tecto da classe mais `MARGEM_DO_TECTO_MS` (500 ms),
  para que o tecto preciso ganhe quando existe. Medido:
  `test_uma_tool_pendurada_custa_uma_vaga_e_nao_o_processo` → `UPSTREAM_TIMEOUT`
  em 2,50 s contra um executor de 3 s, com a invocação paralela a passar.

Quando a espera estoura, a *thread* **continua** — não se cancela uma, e não se
quer: ela tem a tomada, acaba o pipeline e escreve a linha de `tool_audit` com a
latência real, pelo que a invocação não desaparece do registo. O que custa é a
sua vaga até acabar, e isso é o tecto a funcionar: uma tool pendurada tira
**uma** das `KAMBA_TLS_LIGACOES`, e não o processo.

**O que está medido:**

* o disjuntor abre após falhas **consecutivas** configuráveis
  (`test_abre_apos_as_falhas_consecutivas_configuradas`), é **por backend**
  (`test_e_por_backend_e_nao_global`), um sucesso repõe o contador
  (`test_um_sucesso_poe_o_contador_a_zero`), e aberto devolve `UPSTREAM_DOWN`
  **sem chamar o backend** — `test_aberto_devolve_upstream_down_sem_chamar_o_backend`
  conta as chamadas ao executor: **2** antes de abrir e **2** depois da terceira
  invocação;
* os dois números do §6.5: `test_os_timeouts_sao_os_do_documento` →
  `read` 2000 ms, `write` e `money` 8000 ms;
* para a única tool com executor (`get_store_info`, backend `plataforma`), o
  tecto é **do lado do servidor** e é real:
  `test_o_tecto_sai_para_o_servidor_com_o_numero_da_classe` confronta o SQL que
  sai (`SET LOCAL statement_timeout = 2000`), e
  `test_o_servidor_honra_o_statement_timeout` prova contra a base que o
  servidor cancela (`pg_sleep(1)` contra um tecto de 50 ms → SQLSTATE `57014`).

**O que pertence a outro ticket**, e não é o tecto: o retry do §6.5 («1 retry
com *backoff*») é do grafo. A camada **não repete nada**, de propósito, e um
teste di-lo — `test_passo_6_timeout_e_upstream_timeout_e_qualquer_outra_e_down`
chama o executor uma vez. Quem repete é o **KAM-031**.

**E duas correcções no disjuntor, as duas da revisão.** Um erro de negócio
(`NOT_FOUND`, `OUT_OF_STOCK`) não conta para o disjuntor — um que contasse
respostas abria-se com tráfego normal de uma loja sem stock — mas a primeira
versão chamava `registar_sucesso` nesse caminho, e isso **apaga** o estado: um
backend a alternar entre erro de negócio e *timeout* nunca abria, porque cada
resposta de negócio punha a contagem a zero. Hoje é `absolver`, que larga a
tentativa de meio-aberto e não toca na contagem
(`test_um_erro_de_negocio_nao_apaga_a_contagem`). E a tentativa de meio-aberto
**caduca**: sem prazo, uma `BaseException` que ninguém reportasse deixava o
backend em disjuntor permanente (`test_a_tentativa_de_meio_aberto_caduca`).

#### Critério 8 — `TENANT_MISMATCH` e o X-02

**`parcial`.** Metade do critério é da camada e está medida; a outra metade é do
grafo.

**O que está medido:**

* o alerta de segurança: `test_passo_4_confirmacao_de_outro_contacto_e_tenant_mismatch`
  confere `agr_tool_tenant_mismatch_total == 1`. **Sem etiqueta**, de propósito
  (dicionário §3.27): o que um painel precisa de saber é que houve um;
* que o §6.5 o classifica como violação: `erros.VIOLACOES` são as três do
  documento e `ErroDeTool(TENANT_MISMATCH).e_violacao` é verdadeiro;
* **X-02** — `db/tests_agr/test_tool_audit.py::TestIsolamento::test_x02_cada_tool_com_estado_de_a_e_referencia_a_b_da_zero_canarios`:
  por cada uma das onze tools do catálogo × três referências de B (o
  `tenant_id`, o `contact_id` e o `conversation_id`), invoca-se com o estado de
  A → **0** ocorrências do canário na resposta, no erro e na `tool_audit`.
  **Com controlo positivo, e é a correcção mais importante da revisão:** a
  primeira versão passava os mesmos `cart_id`/`nota` a todas as tools, e com
  isso a única ligada do catálogo real — a `get_store_info`, cujo modelo não tem
  campos — recusava no **passo 3**. Com as declaradas a recusar no passo 1,
  **nenhuma** invocação chegava ao backend e o `assertNotIn` não podia falhar:
  o critério estava satisfeito pela razão errada. Hoje cada tool recebe
  argumentos que o seu esquema aceita, e o teste **exige** que as ligadas
  cheguem ao passo 6 (`chegaram_ao_backend == catalogo.ligadas()`);
* **X-04**: `test_x04_uma_sessao_sem_contexto_le_zero_linhas` → `count(*) == 0`.
  E `test_escrever_no_nome_de_outro_tenant_e_recusado` prova o `WITH CHECK`, que
  **não** é redundante com o *append-only*: o único tipo de escrita que esta
  tabela aceita é um `INSERT`, e é a política que impede que ele leve o
  `tenant_id` de outro.

**Uma correcção ao próprio teste, que vale a pena ler.** A primeira versão
passava o canário de B como **argumento** e falhava: o executor de ensaio
devolvia-o. Isso media a coisa errada — uma tool que devolve o que recebeu não
vazou nada, o valor era de quem chamou. O oráculo correcto é um canário que
**só existe do lado de B** (semeado na `tenants` de B), e é a única forma de
distinguir uma leitura de um eco.

**O que falta, e o credor.** «Nunca é repetido»: a camada não repete nada, e
isso é verificável — não há retry nela. Mas o §6.5 põe a decisão de repetir no
**grafo** («bloqueio, alerta de segurança, `safe_reply`; **nunca** tentar de
novo»), e o grafo é o **KAM-031**. Enquanto ele não existir, «nunca é repetido»
é uma propriedade de metade do caminho.

E o X-02 é hoje mais barato do que vai ser: **nove das onze** tools estão
`declaradas` e recusam no passo 1, pelo que devolvem `data` vazio por
construção. O X-02 com os onze executores ligados é do KAM-031 e do KAM-035.

#### O que fechou no `registry/gates.yaml`, e como se prova

O KAM-027 deixou três validações em modo `aviso` com credor nomeado, e uma era
`tools` → KAM-028. **Não há interruptor no código: fechar a validação é apagar
a linha**, e `bloqueio` é a omissão. As duas linhas saíram (uma por vertical).

```
PYTHONPATH="libs/py-core/src;services/agr/src" .venv/Scripts/python.exe -c "…carregar…"
→ verticais: ['servicos', 'vendedor']
→ adiadas: ['golden_kam_040', 'grafo_kam_031', 'grafo_kam_035']
```

O `tools_kam_028` desapareceu da lista. E a validação **morde**:
`test_com_o_catalogo_ligado_a_validacao_das_tools_morde` liga um catálogo sem o
`search_catalog` e o arranque recusa, nomeando a tool. Sem esse teste, «a
validação (1) corre em `bloqueio`» era uma afirmação sobre um ficheiro e não
sobre o que acontece.

**E o fecho é honesto numa metade e tem credor na outra, e isso diz-se.** A
validação (1) tem duas perguntas: «esta tool existe?» e «o esquema dela expõe um
parâmetro proibido?». A primeira morde hoje para as **onze** — há teste a
prová-lo. A segunda só pode morder onde há esquema, e hoje há **um**: as dez
`declaradas` devolvem `frozenset()` porque **nada delas está exposto** (o
`for_context` não as liga e o `invoke` recusa-as, as duas coisas com teste), e
não porque não se procurou. No dia em que o **KAM-031** e o **KAM-035**
registarem os dez modelos, a segunda pergunta passa a cobrir os onze — e é lá
que ela passa de verdadeira a verificada. O *lint* de CI do critério 3 cobre
entretanto o mesmo em todos os esquemas que existam, por análise da fonte.

**A distinção que o tornou possível** está no `tls/especificacoes.py`: uma
entrada de catálogo está `ligada` (tem modelo e executor) ou `declarada` (tem
nome, classe e o **ticket que a liga**, e é recusada sem ele). As onze existem,
**uma** responde, e as outras dez dizem quem as liga — KAM-031 ou KAM-035. É a
mesma disciplina que o KAM-027 impôs ao `gates.yaml`: um atalho sem o ticket que
o fecha não é atalho. Uma entrada `declarada` não é visível ao modelo (o
`for_context` não a liga) e o `invoke` recusa-a, e as duas coisas têm teste —
que é o que impede este mecanismo de ser um silêncio trocado por outro.

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os Critérios satisfeitos e demonstráveis | **vazia** | o critério 8 é `parcial`, com o credor nomeado acima — «nunca é repetido» é metade do caminho enquanto o grafo (KAM-031) não existir. O 7 **passou a satisfeito** com a revisão adversarial, que mostrou que nenhum tecto era imposto. Marcá-la era contradizer a linha do 8 |
| **Isolamento de tenant** | marcada | `rls.enable_tenant_rls("tool_audit")` na `0021`; X-02, X-03 e X-04 medidos; `gate_bd.py --suite tests_isolamento` → **78** testes OK, com a `tool_audit` nas quatro listas do `test_x05_catalogo.py` |
| **Idempotência** | marcada | a coluna `idempotency_key` existe e recebe a chave (`test_passo_5_a_chave_vai_para_a_linha_de_auditoria`); `write`/`money` **nunca correm sem chave** (`test_passo_5_money_sem_chave_nao_corre`, com `None`, `""` e `"   "`). A derivação do §6.3 e a tabela `tool_idempotency` são do KAM-029, e **não** entram aqui: uma chave derivada e guardada em sítio nenhum não desduplica nada |
| **Pagamento só por evento autenticado** | marcada | `test_nenhuma_tool_do_cliente_altera_preco_stock_ou_pagamento` enumera o catálogo **×** `registry/*.yaml` e recusa um verbo de alteração sobre preço, stock ou pagamento; `test_nao_existe_tool_de_envio_de_mensagem` faz o mesmo para o envio. **Enumeração e não leitura**: a ausência de uma coisa não se vê a ler a lista do que há |
| **Números só de tools** | marcada | `Fact` com `fact_id`, `kind`, `retrieved_at` e `kind` em lista fechada (os quatro do §6.2); `test_um_fact_tem_de_ter_kind_do_documento_e_fact_id`. O `get_store_info` devolve `facts` **vazios** e isso está escrito: o que ela devolve é texto de configuração, e nenhum dos quatro `kind` tem onde o pôr |
| **Privacidade e custo** | marcada | o varrimento com canários e o seu controlo (critério 5); cinco métricas no `metricas.py`, com as etiquetas **derivadas** do catálogo e dos códigos — `test_nenhuma_metrica_aceita_um_identificador_como_etiqueta` passa um `tenant_id` a sério às três com etiqueta e as três levantam |
| Revisão por dois revisores; documentação actualizada | **vazia** | decisão escrita do fundador: nesta fase não há revisores, e a caixa fica vazia em toda esta linha. A revisão adversarial deste ticket está em `../docs/analises/`, e é evidência — **não** é um revisor. A documentação está actualizada (dicionário §3.27, emenda 1.36; `docs/ci.md`; `docs/dividas-documentais.md`) |

#### Prova por mutação

**Vinte e seis mutações novas (`tls:`), 0 não apanhadas** — vinte do ticket e
**seis das correcções da revisão adversarial**, que repõem exactamente os
defeitos que ela mediu. Cada uma apaga **uma** propriedade que um critério
nomeia; as duas que mais valem não são de lógica — a que faz a redacção guardar
o valor do argumento e a que tira a ordenação da forma canónica — porque deixam
o código a funcionar e quebram o que o critério 5 protege.

```
.venv/Scripts/python.exe db/mutacoes.py <python-absoluto> "tls:"
→ 26 mutacao(oes) corrida(s), 0 nao apanhada(s)
.venv/Scripts/python.exe db/mutacoes.py --aplicaveis
→ 751 mutacao(oes) conferida(s), 0 nao aplicavel(is)
```

**E uma sobreviveu na penúltima corrida, com uma lição que não se compra de
outra forma.** A mutação que repõe o `registar_sucesso` no caminho do erro de
negócio passou: o `test_um_erro_de_negocio_nao_apaga_a_contagem` chama
`disjuntor.absolver` **directamente**, pelo que prova o que o `absolver` faz — e
não que a camada o chama. É «um teste que passa pela razão errada» com o
instrumento que este repositório tem para o apanhar. O teste que a mata corre
pelo `invoke`, com um backend a alternar entre erro de negócio e falha
(`test_na_camada_um_erro_de_negocio_nao_apaga_a_contagem`): com `absolver` a
contagem chega a dois e o disjuntor abre; com `registar_sucesso`, a resposta de
negócio põe-na a zero e ele nunca abre.

**E a primeira corrida apanhou um defeito no próprio corredor.** O
`MODULOS_DO_AGR_UNIT` corria dois ficheiros (`test_registo`, `test_egresso`), e
sem lhe acrescentar o `test_tls` as **dezessete** mutações dessa suite
sobreviviam todas — não por falta de teste, mas porque o corredor não corria o
ficheiro que as mata. É a mesma classe de defeito que o KAM-025 descreveu para
o `_copiar`, e fica escrita lá.

#### Dois defeitos que os testes apanharam, e que valem mais do que os números

**Um `CHECK` com `NULL` não recusa.** A primeira versão da restrição
`tool_audit_erro_tem_codigo` era
`(status='ok' AND error_code IS NULL) OR (status='erro' AND error_code IN (…))`.
Com `status='erro'` e `error_code` nulo, o `IN` dá **`NULL`** e não `false`, e um
`CHECK` só recusa o que é falso: passava exactamente a metade que a restrição
existe para fechar. Apanhado por `test_um_erro_sem_codigo_e_recusado`.

**E a correcção dessa correcção foi ensinada pelo *gate* 3b.** Pôr o domínio
dentro da condição composta deixava os dez códigos **fora do dicionário** para
o *gate* 3b — dez achados de nível 1 —, porque ele exige «CHECK fechado» na
coluna. São duas restrições: uma diz o domínio (`error_code IN (…)`, sem
`IS NULL OR`, que o tornaria ilegível para o lint), a outra diz a coerência com
o `status`. E o domínio escreve-se no dicionário **qualificado pela tabela**
(`tool_audit.error_code`), porque o `error_code` já é coluna de
`outbound_messages` e um domínio sobre o nome nu declarava-a ilegível — também
medido.

#### A revisão adversarial, e o que ela mudou

`../docs/analises/ANALISE-30-KAM-028-toollayer.md` — **23 achados: 9 *must fix*,
10 *should fix*, 4 *nice to have*; veredicto REPROVADO.** Os nove foram
verificados por medição antes de se corrigirem, e os nove estão corrigidos com
teste. Os quatro mais graves não eram de desenho — eram de uma camada que
**nunca foi importada sozinha, nunca foi chamada em concorrência e nunca
recebeu um executor lento**:

| # | O que estava errado | Como se mediu | Onde ficou o teste |
|---|---|---|---|
| 1 | três dos oito ficheiros não se importavam sozinhos (`ImportError: partially initialized module`), e eram os três que o KAM-031/035 abre primeiro — o `metricas.py` derivava as etiquetas no corpo do módulo | `python -c "import kamba_agr.tls.especificacoes"` | `TestImportacaoIsolada`, em **subprocesso**: dentro do processo os módulos já estão em `sys.modules` e o ciclo não se vê |
| 2 | o *lint* do critério 3 devolvia `conforme` para `class Args(Base)` com `tenant_id` — só reconhecia herança **directa** de `BaseModel` | árvore de ensaio, exit 0 | `test_uma_subclasse_indirecta_tambem_falha`; e uma base de fora do ficheiro passou a ser **achado** (falha fechada) |
| 3 | um `asyncio.Lock` por processo serializava **todos** os *tenants* | 10 invocações de 10 *tenants* com backend de 200 ms → **2,02 s** | `test_dez_tenants_nao_correm_em_serie` (hoje 0,61 s com a fila de 4) |
| 4 | nenhum tecto era imposto pela camada | executor de 5 s contra tecto de 2 s → `ok=True` em 5,01 s | `test_uma_tool_pendurada_custa_uma_vaga_e_nao_o_processo` |
| 5 | os **nomes** dos argumentos iam em claro para a `tool_audit` | `redigir({'contacto 999123456789': …})` | `TestRedaccaoDosNomes` e `test_um_nome_de_argumento_inventado_nao_chega_a_tabela` |
| 6 | o parâmetro `tecto` do passo 2 não tinha chamador senão a própria camada | `grep "tecto="` → 1 linha | `test_o_tecto_por_pedido_do_passo_2_nega_e_nao_consome`, contra o `platform.ten_tecto` |
| 7 | o X-02 media onze **recusas** e não onze tools | nenhuma invocação chegava ao passo 6 | controlo positivo no próprio X-02 |
| 8 | a linha de arranque da camada era recusada pelo *logger* (e com `KAMBA_LOG_ESTRITO=1` abortava o `main()`) | `_CODIGO.fullmatch('ligadas_1_de_11_read_2000ms')` → `None` | `test_sem_auditoria_de_tools_o_agr_nao_arranca` lê o campo |
| 9 | o `Fact` entregue não servia o KAM-032, que declara `sku` e precisa de três `kind` a mais | o bloco do KAM-032, *Detalhes Técnicos* | `TestFactParaOKam032`; o `sku` entrou, os `kind` ficaram em dívida com credor |

**O achado 6 corrigiu-se em parte e discorda-se em parte, com a razão escrita.**
A revisão nota que o `consume_limit` nunca corre e o `msgs_ai_mes` nunca
decrementa — é verdade, e é deliberado: o `msgs_ai_mes` conta **mensagens** e
consome-se no envio (o nó `send`), não por invocação de tool; consumi-lo a cada
`search_catalog` queimava o balde mensal de um *tenant* numa conversa. O que se
corrigiu foi a outra metade: o tecto por pedido passou a ter teste contra a base.

Dos dez *should fix*, corrigiram-se os seis que são de comportamento ou de
contagem — as duas do disjuntor, o SQL de várias linhas invisível ao *lint*, as
métricas que se perdiam quando a auditoria levantava, a quarta tomada que não se
fechava no `ao_encerrar`, e três contagens em prosa. Os quatro restantes são
registo e ficaram em `../docs/dividas-documentais.md` (linhas 105 a 107) ou
nomeados nesta secção. Os quatro *nice to have* **não** se corrigiram, por
decisão: a análise di-lo explicitamente.

#### Estado da prova

| Bateria | Onde corre | Resultado |
|---|---|---|
| `services/agr/tests` (unidade e arquitectura) | *gate* 4 | **389** testes, OK (106 novos em `test_tls.py`) |
| `tools/lint_arch/tests` (inclui `test_tool_schema.py`, 19) | *gate* 4 | **344** testes, OK |
| `db/tests` (catálogo, inventário, privilégios) | *gate* 8 | **584** testes, OK |
| `db/tests_agr` (TLS contra PostgreSQL 18.6) | *gate* 8 | **107** testes, OK (76 novos) |
| `db/tests_isolamento` (X-02 a X-05) | *gate* 6 | **78** testes, OK |
| `lint_arch all` (inclui `tool-schema`) | *gates* 2 e 11 | conforme |
| `log_policy lint` | *gate* 2 | **0** achados |
| `canon_lint` (gate 3b) | *gate* 3b | **0** achados |
| `lint_refs`, `lint_handoff` | *gate* 3 | conforme |
| Mutações `tls:` | PR | **26** corridas, **0** não apanhadas |

**O `lint_contagens` não correu**: não corre de dentro de um *worktree* (defeito
dele, dono KAM-158) — o filtro do corpus exclui tudo o que tenha `.claude` no
caminho. Confia-se no que o CI diz desse passo.

**O `gate 5 — reservado` falha por desenho** e não é obrigatório.

### Handoff para Claude Code

```text
És o executor do ticket KAM-028 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-028), docs/tecnica/02_Agent_Runtime_Verticais.md (§6)
e docs/tecnica/08_Seguranca_Conformidade.md (§3.2, §4.3, §6).
Objectivo: ToolLayer com for_context/invoke (8 passos fail-closed), classes read/write/money, tool_audit
append-only, erros tipados, timeouts (read 2 s, write/money 8 s) e circuit breaker; backends fake.
- O modelo nunca vê tenant_id: lint de CI nos esquemas das tools.
- Escrita só com Confirmation (botão confirm:{cart_id} do mesmo contact_id no turno actual).
- Sem tool de envio de mensagem nem de alteração de preço/stock/pagamento nas verticais de cliente.
Não expandas escopo: idempotência por cart_id (KAM-029) e especificações das tools de cada vertical
(KAM-031/035) são tickets próprios.
Testes: unit, integração, isolamento (X-02), arquitectura. PR com o template §7. Commits: feat(KAM-028): …
```

---

## KAM-029 — Idempotência de tools por `cart_id`

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-028 |
| Bloqueia | KAM-031, KAM-046 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§6.3), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§6.3), ADR-009, ADR-010, ADR-013 |

### Contexto

A chave do documento exploratório, `hash(msisdn + sku + janela_5min)`, usa telefone (viola ADR-010), parte-se na fronteira da janela (toques às 4:59 e 5:01 geram duas encomendas) e bloqueia recompras legítimas. A regra adoptada é um pedido por carrinho: `sha256(tenant_id | contact_id | tool | cart_id)`, com o `cart_id` embutido no `id` do botão de confirmação. O COM tem uma segunda barreira, a `intent_key` (KAM-046); nenhuma das duas depende da outra.

### Objectivo

Implementar na TLS a idempotência de todas as tools `write`/`money`: derivação da chave, tabela `tool_idempotency`, devolução do resultado guardado (`idempotent_replay=true`) e tratamento de concorrência e de falha a meio.

### Critérios de Aceitação

- [ ] 50 invocações concorrentes de `criar_pedido(cart_id)` com o mesmo `cart_id` chamam o backend **exactamente 1 vez** e devolvem todas o mesmo resultado, com `idempotent_replay=true` em 49.
- [x] Dois toques com intervalo simulado de 4:59 e 5:01 (relógio simulado) produzem 1 pedido; uma recompra com novo `cart_id` imediatamente a seguir produz 2.
- [x] Reutilizar o `cart_id` com argumentos diferentes (`args_hash` distinto) devolve `INTENT_REUSED_WITH_DIFFERENT_CONTENT` e não chama o backend.
- [x] Falha injectada **depois** de o backend ter executado e **antes** de o resultado ser guardado: a repetição não duplica o efeito (o backend é idempotente pela chave) e fecha o registo.
- [x] Registo `em_curso` há mais de 2 s não bloqueia: o segundo pedido aguarda até 3 s (valor de `../docs/tecnica/03` §6.3) e, se continuar `em_curso`, devolve `UPSTREAM_TIMEOUT` sem executar.
- [x] A chave é independente de telefone, BSUID e relógio (teste de propriedade: 1.000 combinações, 0 entradas dependentes de tempo); a coluna `key` nunca contém `+244`.
- [ ] Retenção da tabela ≥ validade da reserva (72 h) + prazo de disputa; valor *proposta*: 30 dias, a recalibrar quando `../docs/tecnica/04` fixar o prazo de disputa.
- [ ] Um segundo toque com `wamid` novo depois de `stage != awaiting_confirm` é tratado como confirmação antiga (contrato com KAM-031), sem tocar no backend.

### Detalhes Técnicos

- **Componentes:** TLS (passo 5 do pipeline de KAM-028), Postgres. Módulo `kamba/tls/idempotency.py`; migração Alembic reversível.
- `idempotency_key = sha256(tenant_id | contact_id | tool | cart_id)`; botão `id = "confirm:{cart_id}"` (cabe nos 256 caracteres do botão, a confirmar no limite da Meta antes de fixar o formato do `cart_id`).
- O `cart_id` é opaco e gerado por `propose_cart` (KAM-046); um carrinho editado ou refeito gera novo `cart_id`. Mapeia para `(draft_id, draft_version)` do COM (`../docs/tecnica/03` §6.3).
- Protocolo: `INSERT … ON CONFLICT DO NOTHING` com estado `em_curso` → executar → `UPDATE` com resultado; leitor concorrente espera ou devolve o resultado.
- Serviços: `book_slot` usa a mesma tabela com chave por `(contact, slot_id)` (`../docs/tecnica/02` §6.2), derivada do `hold_id` na confirmação.

```sql
CREATE TABLE tool_idempotency (
  key text PRIMARY KEY, tenant_id uuid NOT NULL, tool text NOT NULL, args_hash bytea NOT NULL,
  estado text NOT NULL DEFAULT 'em_curso' CHECK (estado IN ('em_curso','concluida','falhada')),
  result jsonb, created_at timestamptz NOT NULL DEFAULT now());   -- RLS FORCE por tenant_id
```

### Testes Requeridos

- Unit: derivação da chave, propriedades (independência de tempo/telefone).
- Integração (Postgres real): 50 concorrentes, falha injectada, fronteira de janela com relógio simulado.
- Isolamento: chave do tenant A nunca devolve resultado do tenant B (mesmo `cart_id` forjado).
- Idempotência end-to-end com o backend *fake* a contar chamadas.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] **Idempotência:** teste de repetição de `write`/`money` sem duplicar efeitos (ADR-013).
- [x] **Isolamento de tenant:** RLS `FORCE` em `tool_idempotency`; teste cruzado cobre o caminho.
- [x] **Privacidade:** chave sem telefone; `result` sem PII em claro (ADR-010).
- [x] **Migrações reversíveis:** `downgrade` testado.
- [ ] Documentação e retenção actualizadas; revisão por dois revisores (dinheiro).

### Verificação dos Critérios de Aceitação

Medido a 2026-10-25, no ramo `feature/KAM-029-idempotencia-de-tools-por-cart-id`,
contra um PostgreSQL 18.6 descartável (`python db/gate_bd.py --suite tests_agr`) e
a bateria de unidade do serviço. As quatro *suites* que este trabalho toca:
`tests_agr` **141 OK** (105 antes), unidade do AGR **405 OK** (389 antes),
`tests` **584 OK**, `tests_isolamento` **78 OK**, e as 229 baterias do
`canon_lint` (duas novas, a primeira com quatro asserçoes). As **dez**
mutações `idem:` correm com **0 não apanhadas**, e `--aplicaveis` dá **761**
com 0 não aplicáveis. **A primeira corrida das mutações deu três não
apanhadas**, e nenhuma era a mesma coisa: uma sobreviveu (tirar o
`AND estado = 'falhada'` da retoma não era medido por nada — e sem ele um
`UPDATE` numa linha `concluida` apaga o resultado guardado e manda correr o
backend outra vez), e duas davam `PROVA INVALIDA` por a *suite* **pendurar**,
porque a mutação que tira o tecto à espera faz do laço um ciclo infinito. O
`dormir` das baterias passou a ser um cão-de-guarda, e uma bateria de unidade
deixou de poder pendurar.

**O oráculo de todos os critérios de execução é o contador de chamadas ao
backend, e não o que o `invoke` devolve.** Um teste de idempotência que meça o
resultado passa com a idempotência apagada: as 50 invocações devolvem o mesmo
`ok=True` de qualquer maneira, porque o executor de ensaio é determinista. Foi o
defeito do X-02 do KAM-028 — media onze **recusas** em vez de onze tools — e é a
pergunta que cada linha abaixo teve de sobreviver. Por isso o backend de ensaio é
**idempotente pela chave** e devolve um `order_id` por chave distinta: assim o
contador separa «quantas vezes o backend correu» de «quantas encomendas
existem», que são as duas metades do critério 4 e não são a mesma coisa.

**Três caixas ficam vazias** (1, 7 e 8), e nenhuma delas é «passa em espírito».
A do critério 1 ficou vazia **depois** da revisão adversarial
(`../docs/analises/ANALISE-31-KAM-029-idempotencia.md`), que mostrou que ele e o
critério 5 não podem valer ao mesmo tempo com um backend mais lento do que o
tecto de espera — e nesta linha isso acaba numa encomenda a dobrar.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | 50 invocações concorrentes do mesmo `cart_id` chamam o backend **1** vez e devolvem todas o mesmo resultado, com `idempotent_replay=true` em 49 | | **parcial, e a razão é uma tensão com o critério 5.** **O que está medido:** `db/tests_agr/test_idempotencia.py::TestCinquentaConcorrentes::test_cinquenta_do_mesmo_cart_id_chamam_o_backend_uma_vez` — 50 corrotinas em `asyncio.gather` sobre a camada com `ligacoes=12` (cada tomada com ligação própria: o `tenant_guard` recusa duas transacções na mesma, e 50 sobre uma só estouravam antes de chegarem ao `ON CONFLICT`). Resultado: **1** chamada ao backend, **1** encomenda, os 50 resultados num conjunto de **um** elemento, **49** com `idempotent_replay=True`, e **uma** linha em `concluida` com o resultado dentro. O executor dorme 50 ms de propósito: sem isso a primeira fechava a reserva antes de as outras a lerem, e a bateria media uma série disfarçada de paralelo. **O controlo está ao lado** (`test_cinquenta_cart_ids_diferentes_chamam_cinquenta_vezes`): 50 `cart_id` distintos dão **50** chamadas, 50 encomendas, **0** *replays* e 50 linhas — sem ele, a bateria de cima passava com uma idempotência que desduplicasse por *tenant*, por contacto, ou por nada. **O que NÃO é verdade, e é por isso que a caixa fica vazia:** «devolvem **todas** o mesmo resultado» só vale enquanto o backend responder dentro do tecto de espera. Com um backend a 4 s — dentro do tecto de 8 s que o §6.5 dá à classe — quem espera desiste aos 3 s com `UPSTREAM_TIMEOUT` (que é o que o critério 5 manda fazer), o cliente lê isso como falha de infra-estrutura, pede carrinho novo, e o `cart_id` novo dá chave nova: **duas encomendas**, e a segunda barreira do COM também não apanha, porque carrinho novo é `draft_id` novo. Medido pela revisão adversarial, não pelo autor. **Não se resolve dentro do ticket:** subir o tecto contradiz o critério 5 e o valor que ele cita do `../docs/tecnica/03` §6.3; servir o esperador depois do tecto contradiz o «sem executar». O tecto é parâmetro do construtor, e a decisão é de quem escreveu os critérios. Linha **112** de `../docs/dividas-documentais.md`; a carga e os tectos são do **KAM-084** |
| 2 | Dois toques a 4:59 e 5:01 (relógio simulado) produzem 1 pedido; recompra com `cart_id` novo produz 2 | **satisfeito** | `services/agr/tests/test_tls.py::TestProtocoloDeIdempotencia::test_a_fronteira_da_janela_da_um_pedido_e_a_recompra_da_dois` — relógio injectado a saltar de `4*60+59` para `5*60+1`: **1** chamada ao backend. `cart_id` novo imediatamente a seguir: **2** chamadas e **2** encomendas. A fronteira não existe porque a chave não tem tempo dentro, e é isso que o critério 6 mede por propriedade; esta bateria mede a **consequência**. Medido na unidade e não contra a base de propósito: o relógio não participa em instrução nenhuma de SQL, pelo que uma corrida contra o PostgreSQL mediria a mesma coisa mais devagar |
| 3 | Reutilizar o `cart_id` com argumentos diferentes (`args_hash` distinto) devolve `INTENT_REUSED_WITH_DIFFERENT_CONTENT` e não chama o backend | **satisfeito** | Nas duas camadas. Unidade: `test_tls.py::TestProtocoloDeIdempotencia::test_o_mesmo_cart_id_com_outros_argumentos_recusa_sem_chamar` — `ok=False`, o código, e **1** chamada ao backend (a da primeira invocação). Contra a base: `test_idempotencia.py::TestConteudoDiferente`, com o `args_hash` a serio, mais `test_a_recusa_escreve_a_linha_de_auditoria_com_o_codigo_novo`, que mede o que **só** a base mostra — as duas linhas de `tool_audit` são `[('ok', None), ('erro', 'INTENT_REUSED_WITH_DIFFERENT_CONTENT')]`. **É a razão pela qual a `0022` altera o `CHECK` fechado da `0021`**: sem o décimo primeiro código no domínio, a primeira recusa violava a restrição ao escrever a própria linha que a registava, e a invocação rebentava com um defeito de base em vez de devolver a recusa. E o que torna a recusa **não contornável** é um privilégio: o `kamba_app` não tem `UPDATE (args_hash)` — `test_idempotencia.py::TestRestricoes::test_a_aplicacao_nao_altera_o_args_hash` mede o `42501`, e a `tool_idempotency` entrou em `TABELAS_COM_MATRIZ_DE_COLUNA` pela razão que o KAM-015 mediu («a idempotência deste ticket inteiro cai por um `GRANT` de uma palavra») |
| 4 | Falha injectada **depois** de o backend executar e **antes** de o resultado ser guardado: a repetição não duplica o efeito e fecha o registo | **satisfeito** | `test_idempotencia.py::TestFalhaAMeio::test_a_repeticao_nao_duplica_o_efeito_e_fecha_o_registo`. A falha injecta-se **onde ela acontece**: na escrita da linha de auditoria, que o passo 7 levanta por desenho. Medido: o backend correu **1** vez, a linha fechou em `falhada` **sem resultado** (o `CHECK` da `0022` não o deixaria lá), e a repetição deu **2** chamadas ao backend e **1** encomenda — o efeito não duplicou porque o backend é idempotente pela chave — com a linha em `concluida` e o `order_id` original. **E a premissa dessa frase está medida até onde se pode medir:** `test_a_chave_chega_ao_backend` confere que o executor recebe exactamente a chave do §6.3 — o que o campo garante é que o backend a **recebe**; usá-la é contrato do KAM-046 e do KAM-035, e enquanto nenhum executor real existir a propriedade está provada só contra o duplo de ensaio. É o limite real deste critério, e a revisão adversarial teve razão em o apontar (`ANALISE-31`, achado 7) — a *docstring* que dizia que «o COM deriva dela a sua `intent_key`» era falsa contra o `../docs/tecnica/03` §6.3 e contra o Contexto deste bloco, e saiu. O `Pedido` do KAM-028 **não a levava**, e sem ela «o backend é idempotente pela chave» era uma frase sem nada a sustentá-la; passou a levar (`Pedido.chave`), e está escrito no `docs/agr.md` §7-C. **Este critério encontrou um defeito meu, a correr:** o caminho de excepção fecha a tomada e o `finally` corre **depois** do `except`, pelo que a reserva ficava aberta precisamente aqui — o fecho passou a correr também no `except`, antes de a ligação cair, com marca para não escrever duas vezes. É a janela do achado 12 da `../docs/analises/ANALISE-30-KAM-028-toollayer.md`, que nomeou este ticket para a fechar |
| 5 | Registo `em_curso` há mais de 2 s não bloqueia: o segundo pedido aguarda até 3 s e, se continuar `em_curso`, devolve `UPSTREAM_TIMEOUT` sem executar | **satisfeito** | **A primeira versão desta linha estava satisfeita pela razão errada, e a revisão adversarial mostrou-o** (`ANALISE-31`, achado 3): o `created_at` não entrava em decisão nenhuma, pelo que a semente de dez minutos era decoração — apagá-la e o teste passava igual. Hoje a idade é carga útil, e a prova são **dois** testes cujo única diferença é ela. `test_idempotencia.py::TestRegistoEmCurso::test_em_curso_espera_ate_tres_segundos_e_nao_executa` semeia a reserva de outro com dez **segundos** (mais do que os 2 s que o critério nomeia, menos do que os 2 min ao fim dos quais ela se considera abandonada). Medido: `UPSTREAM_TIMEOUT`, **0** chamadas ao backend, o relógio simulado andou **≥ 3,0 s e < 3,2 s** (o tecto é o `poll ≤ 3 s` do `../docs/tecnica/03` §6.3), e a linha de outro ficou intacta em `em_curso`. O relógio e o `dormir` são dobragens: medir 3 s a sério media a máquina. **O controlo é o outro lado** (`test_em_curso_que_fecha_entretanto_devolve_o_guardado`): se o dono fechar a meio da espera, quem esperava é **servido** com o resultado dele (`idempotent_replay=True`, 0 chamadas, e desistiu **antes** do tecto) — sem ele, a bateria de cima passava com uma espera que nunca relesse a linha, e `UPSTREAM_TIMEOUT` em todos os casos é pior do que esperar. **E o tecto fecha o ciclo inteiro e não um ramo dele:** a primeira versão media-o só no ramo `em_curso` e os outros dois faziam `continue` — com uma linha que nunca aparecesse, ou uma `falhada` que outro retomasse sempre primeiro, o laço girava para sempre numa *thread* da camada, com uma tomada presa. Apanhado a **correr** a bateria, que pendurou |
| 6 | A chave é independente de telefone, BSUID e relógio (teste de propriedade: 1.000 combinações, 0 entradas dependentes de tempo); a coluna `key` nunca contém `+244` | **satisfeito** | **A propriedade:** `test_tls.py::TestDerivacaoDaChave::test_mil_combinacoes_nao_dependem_do_turno_nem_do_relogio` — **1.000** combinações de `(tenant_id, contact_id, tool, cart_id)`, cada uma derivada **duas** vezes com tudo o que muda entre dois toques do mesmo carrinho (turno novo, execução nova, conversa nova, canal novo, versão de grafo nova): **0** instáveis. Mede-se contra as colunas que existem e não contra uma ideia de tempo — as quatro partes do §6.3 são as quatro do §6.3, e é por `turn_id`/`run_id` que um relógio entraria. **O BSUID não entra por não existir no caminho:** o `ToolContext` não tem campo para ele (§6.1), pelo que a independência é estrutural e não medida — está dito aqui em vez de ser apresentada como medição. **A coluna:** `test_mil_chaves_tem_a_forma_de_um_sha256_e_nenhuma_leva_telefone` põe um telefone do intervalo fictício da casa (`999123456789`) no `cart_id`, que é a única das quatro partes que é texto livre, e confere 1.000 chaves contra `^[0-9a-f]{64}$`, sem `+244` e sem o número. **E o que não depende deste teste estar certo é a base:** `CHECK (key ~ '^[0-9a-f]{64}$')` na revisão `0022`, medido em `test_idempotencia.py::TestPrivacidadeDaChave` contra seis formas recusadas. O que o `CHECK` garante está escrito com precisão na *docstring*: fecha o `+244` (o `+` não é hexadecimal) e qualquer telefone, nome ou morada; **não** garante a ausência de uma sequência de dígitos, e é por isso que o critério diz «nunca contém `+244`» e não «nunca contém dígitos». **O oráculo tem dois canários** (`TestOControlDaDerivacao`): uma derivação que leve o `turn_id` dentro **tem** de ser apanhada, e uma que devolva sempre a mesma cadeia também — são os dois únicos modos de falha de um teste de estabilidade, e sem eles a propriedade passava com a derivação apagada. O varrimento de privacidade da tabela tem o seu (`test_o_varrimento_apanha_um_canario`), pela razão que o KAM-026 pagou: um varrimento que procure na coluna errada dá zero e diz que está tudo bem |
| 7 | Retenção ≥ validade da reserva (72 h) + prazo de disputa; valor *proposta*: 30 dias, a recalibrar quando o `../docs/tecnica/04` fixar o prazo de disputa | | **parcial, e a razão é a letra do critério.** O que está entregue e medido: `idempotency.varrer` com `DIAS_DE_RETENCAO = 30` declarado *proposta*, e `test_idempotencia.py::TestRetencao` — com relógio simulado, apaga as **fechadas** velhas (2 de 5) e poupa as novas, a da fronteira (29 dias) e **a `em_curso` de 90 dias**, que não se apaga por idade porque pode ser de uma invocação a correr; o papel da aplicação **não apaga** (`42501`, só o `kamba_batch` tem `DELETE`); dias negativos levantam. A varredura vive em `tls/idempotency.py` e não no `retencao.py` do `lg`, e **foi o `lint_arch tool-schema` que o impôs**: ele recusa escrita no esquema `platform` em ficheiro de serviço fora da `tls/`, e a ADR-015 está certa — posta aqui, a invariante lê-se inteira. Sem agendador, como no KAM-026 e no KAM-017: quem a chama a horas é o KAM-071 com o KAM-079. **O que NÃO se prova, e é por isso que a caixa fica vazia:** a desigualdade. A validade da reserva está fixada (72 h, `../docs/tecnica/03` §6.4) e prova-se (`test_a_retencao_cobre_a_reserva_de_72h_com_folga`), mas **o prazo de disputa não está em documento nenhum** — o `../docs/tecnica/04` tem `refund_cases` e a transição `paga → reembolso_pendente: disputa`, e não dá prazo; procurado por varrimento, não de memória. «≥ 72 h + X» com X desconhecido não se verifica, e marcar a caixa porque o critério autoriza a *proposta* era cumprir em espírito. **Credor: quem fechar o `../docs/tecnica/04`**; linha **109** de `../docs/dividas-documentais.md`, e `DIAS_DE_RETENCAO` é o sítio onde se muda |
| 8 | Um segundo toque com `wamid` novo depois de `stage != awaiting_confirm` é tratado como confirmação antiga (contrato com KAM-031), sem tocar no backend | | **parcial, e a fronteira é estrutural.** A metade da TLS está medida: `test_tls.py::TestProtocoloDeIdempotencia::test_o_segundo_toque_devolve_o_guardado_sem_chamar_o_backend` — mesmo carrinho, **turno novo** (`turn_id` novo, `Confirmation` nova, chave de turno nova), e o resultado guardado volta com `idempotent_replay=True` e **0** chamadas novas ao backend. É o ponto (iii) do §6.3 («a chave devolve o resultado guardado»), e é **a razão pela qual a chave do carrinho não pode ser a do turno**: um `wamid` novo é um turno novo, logo chave de turno nova, logo nada guardado a encontrar — e o toque antigo cobrava outra vez. Essa decisão está no dicionário §3.28 e corrige o que a emenda 1.36 afirmara. **O que NÃO está medido, e não pode estar daqui:** o `stage`. O `ToolContext` não tem campo para ele (as oito chaves do §6.1) e a TLS não tem como o ver; quem lê `stage != awaiting_confirm` é o `confirm_gate`, que manda a confirmação antiga para o `compose` com o *fact* `STALE_CONFIRMATION` (§7, arestas 23 e 24) — e o `confirm_gate` **é o KAM-031**, que não existe. O KAM-028 fechou o seu critério 8 como parcial pela outra metade desta mesma fronteira («nunca é repetido», do grafo); esta é a segunda. **Credor: KAM-031** |

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | **Três** parciais — 1, 7 e 8 —, com a parte que falta nomeada acima e credor cada um: a tensão entre o 1 e o 5 é do próprio bloco (dívida **112**, e a carga é do **KAM-084**), o prazo de disputa pertence ao `../docs/tecnica/04`, e o `stage` ao **KAM-031**. O 1 passou a parcial **pela revisão adversarial** e não pela medição do autor |
| **Idempotência:** teste de repetição de `write`/`money` sem duplicar efeitos (ADR-013) | **satisfeito** | **A revisão adversarial encontrou aqui o caminho que faltava, e ele está fechado** (`ANALISE-31`, achado 2): uma reserva `em_curso` cujo `fechar` não passasse — a ligação cai entre o backend e o registo, que é o caminho que o `except` existe para tratar — não era retomada por ninguém, a varredura recusa apagar `em_curso` por idade, e aquele `cart_id` respondia `UPSTREAM_TIMEOUT` para sempre **com a encomenda já feita**; o cliente saía por carrinho novo, chave nova, segunda encomenda. Fechado com `MINUTOS_PARA_RETOMAR = 2` e a retoma por idade que o `../docs/tecnica/03` §6.3 ponto 4 já desenhava para o COM, medida em `TestRetomaPorIdade` (quatro baterias contra a base, mais uma de unidade) — e o par que a torna uma medição: a única diferença entre retomar e esperar é a idade da linha. De resto é o critério 4 e o 1 juntos, e o que os torna prova é o backend de ensaio contar chamadas **e** encomendas em separado: 50 concorrentes → 1 chamada, 1 encomenda; falha a meio e repetição → 2 chamadas, **1** encomenda. A repetição de uma tool `money` não duplica o efeito, e o que o garante na pior janela (backend feito, registo falhado, *job* de volta à fila) é a reserva fechar no `except` antes de a tomada cair |
| **Isolamento de tenant:** RLS `FORCE` em `tool_idempotency`; teste cruzado cobre o caminho | **satisfeito** | `rls.enable_tenant_rls("tool_idempotency")` na `0022` (`ENABLE` + `FORCE` + política `tenant_iso` com `USING` e `WITH CHECK`), e a tabela entra nas **quatro** listas do `db/tests_isolamento/test_x05_catalogo.py` — a descoberta por coluna, as políticas declaradas, a `tenant_iso` com os dois lados, e a receita de sementes. **Tem receita**, ao contrário da `tool_audit`: não é *append-only* e apaga-se com `DELETE`, pelo que o X-04 genérico a exercita. Cruzado e com o `cart_id` **forjado**, que é o que os *Testes Requeridos* pedem: `test_idempotencia.py::TestIsolamento::test_o_mesmo_cart_id_em_dois_tenants_sao_duas_reservas` (dois *tenants*, o mesmo `cart_id`, **0** *replays*, 2 chamadas, 2 linhas, resultados diferentes) e `test_a_rls_recusa_reservar_no_nome_de_outro_tenant` (o `WITH CHECK` a dar `42501`, que é a única metade que a RLS acrescenta ao privilégio) |
| **Privacidade:** chave sem telefone; `result` sem PII em claro (ADR-010) | **satisfeito** | A chave: o `CHECK` de forma hexadecimal na base, mais as 1.000 chaves do critério 6 — e a independência de telefone é estrutural, porque nenhuma das quatro partes do §6.3 é telefone. O `result`: varrimento por canário em `test_idempotencia.py::TestPrivacidadeDaChave::test_nenhuma_coluna_guarda_o_telefone_que_passou_pelos_argumentos`, com o telefone a entrar pelo `cart_id` **e** pela `nota`, a varrer a linha inteira concatenada (chave, tool, estado, `result`, `args_hash`) — **com o seu controlo**, que semeia o telefone no `result` e exige que o varrimento o encontre. O inventário fechado de `db/tests/test_inventario.py` responde «guarda dados pessoais?» para as sete colunas, e diz por escrito que a coluna a olhar é o `result` e não a `key`: o dia em que um executor devolver nome ou morada no `data`, é aquela linha que passa a dizer «sim». `log_policy lint` → **0** achados |
| **Migrações reversíveis:** `downgrade` testado | **satisfeito** | `test_idempotencia.py::TestCicloDaRevisao::test_desce_para_a_0021_e_volta` — `downgrade 0021` deixa o `platform` igual a `TABELAS_ATE_0021`, `upgrade head` devolve-o a `TABELAS`, a política volta com `relrowsecurity` e `relforcerowsecurity` a `True`, e o `UPDATE` por coluna do `kamba_app` continua a ser exactamente `(estado, result)` — sem o `args_hash`, que é o que faz o critério 3 valer. **E a assimetria está medida, não afirmada:** o `downgrade` **não** estreita de volta o domínio de `tool_audit.error_code`, e a bateria exige que o décimo primeiro valor continue lá. Três razões, no `downgrade()` da revisão: o código passou a ser canon (um `downgrade` que o retirasse punha a base a discordar do dicionário, e o *gate* 3b falharia sobre uma base que o próprio `downgrade` produziu); uma linha de `tool_audit` que já o tenha fazia o `ADD CONSTRAINT` estreito falhar com `23514`; e um domínio mais largo não perde dados nem quebra chamador nenhum |
| Documentação e retenção actualizadas; revisão por **dois revisores** (dinheiro) | | **A documentação e a retenção estão**, e são metade desta caixa: dicionário §3.28 (emenda **1.37**, que corrige duas afirmações da 1.36), `../docs/tecnica/02` §6.3 e §6.5, `../docs/agr.md` §7-C (linha **1.5**), `../docs/ci.md` (linha **1.56**), `../docs/dividas-documentais.md` linhas **108–111** (versão **1.59**), e a retenção com o valor, a razão e o credor. **A caixa fica vazia pela outra metade:** «dois revisores» não se cumpre, por decisão escrita do fundador de que nesta fase não há revisores — é a mesma caixa vazia de toda esta linha (KAM-025 a KAM-028). Uma revisão adversarial independente é **evidência**, não é um revisor, e a deste ticket está em `../docs/analises/ANALISE-31-KAM-029-idempotencia.md` |

### Handoff para Claude Code

```text
És o executor do ticket KAM-029 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-029), docs/tecnica/02_Agent_Runtime_Verticais.md (§6.3)
e docs/tecnica/03_Core_Comercio_Medusa.md (§6.3).
Objectivo: idempotência na TLS para tools write/money: key = sha256(tenant_id|contact_id|tool|cart_id),
tabela tool_idempotency com RLS, replay com idempotent_replay=true, tratamento de concorrência e de falha a meio.
- Nada de telefone nem janela temporal na chave.
- Reutilização de cart_id com args diferentes: INTENT_REUSED_WITH_DIFFERENT_CONTENT.
- Teste obrigatório: 50 concorrentes → 1 chamada ao backend; 4:59/5:01 → 1 pedido; recompra → 2.
Não expandas escopo: a unicidade no COM (intent_key) é KAM-046.
Testes: unit, integração, isolamento, idempotência. PR com o template §7. Commits: feat(KAM-029): …
```

## KAM-030 — LLM gateway: LiteLLM por digest, chaves virtuais, budgets e `llm_call_log`

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001, KAM-002, KAM-010, KAM-069 |
| Bloqueia | KAM-031, KAM-033, KAM-036, KAM-049, KAM-063, KAM-081, KAM-087, KAM-088, KAM-091, KAM-107, KAM-112, KAM-121 |
| Responsável sugerido | Engenheiro de Plataforma (LLM) |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§13, §14), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§14, `dat.llm_call_log`), ADR-005, ADR-008, ADR-018, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.7, §3) |

### Contexto

O LiteLLM é o componente de maior superfície de ataque do stack: guarda as chaves de todos os fornecedores e teve um incidente de *supply chain* em 2026-03-24 (versões PyPI 1.82.7 e 1.82.8 maliciosas, CONFIRMADO). Desde o dia 1 todo o acesso a modelos passa por ele (ADR-005), com chaves virtuais por tenant e orçamento; as funções Enterprise (SSO, audit logs, rotação automática) não se usam. Cada fornecedor fora de Angola é subprocessador e destino de transferência (ADR-008).

### Objectivo

Implantar o proxy LiteLLM (apenas a parte MIT) por digest com cosign, os aliases por papel, chaves virtuais e budgets por tenant, o cliente interno do AGR e o `llm_call_log` sem conteúdo, com degradação limpa quando o orçamento ou o fornecedor falham.

### Critérios de Aceitação

- [ ] A imagem é referenciada por **digest** (nunca *tag*) e a assinatura cosign é verificada no CI; versão ≥ 1.83.0 e fora de {1.82.7, 1.82.8}; `pip install litellm` na *build* reprova o lint.
- [ ] O proxy só é alcançável da rede interna e o egress só permite os FQDN dos fornecedores aprovados (teste de rede: pedido a FQDN fora da lista falha).
- [x] Existem os aliases `kamba-router` e `kamba-chat` (este com 2 fornecedores) e os papéis `kamba-vision`, `kamba-embed`; `timeout` 8 s (router) e 20 s (chat); `num_retries: 1`, `allowed_fails: 3`, `cooldown_time: 30` (nomes a validar na versão fixada, L5).
- [ ] Criar uma chave virtual por tenant (`key_alias: tenant-<uuid>`, metadados `tenant_id`, `plano`) é idempotente; com orçamento esgotado o cliente recebe `BUDGET_EXHAUSTED` (mapeado do 400) e o AGR degrada (KAM-037); alerta a 80% do orçamento.
- [x] Cada chamada grava 1 linha em `dat.llm_call_log` (`tenant_id`, `trace_id`, `vertical`, `no_grafo`, `modelo`, `fornecedor`, tokens in/out/cache, `custo_usd`, `latencia_ms`, `resultado`) **sem conteúdo**; `custo_usd` do exemplo de `../docs/tecnica/02` §13.3 (3.000 in / 300 out a 0,10 / 0,50 USD por 1M) = 0,00045 em teste unitário.
- [ ] Falha do fornecedor primário de `kamba-chat` (simulada) comuta para o segundo **aprovado** em ≤ 1 retry; um fornecedor não aprovado nunca é usado (o *fallback* não cria destino de dados novo).
- [ ] Alterar o modelo atrás de um alias exige *bump* SemVer em `llm/aliases.yaml` e passa pelo Gate 13; CI falha se o *hash* do ficheiro mudar sem nova versão.
- [ ] Em `KAMBA_ENV=prod`, chamada com dados pessoais sem linha `autorizado` em `tenant_destinations` (tabela de KAM-069) falha fechada; até KAM-069 existir, só dados sintéticos em `staging`.

### Detalhes Técnicos

- **Componentes:** LLM (LiteLLM), OBS, TEN (chave virtual criada no provisioning; manualmente por *script* na Fase 0). Segredos: *master key* e chaves de fornecedor no cofre (KAM-010); rotação de chaves de fornecedor manual (a automática é Enterprise).
- **Cliente:** `kamba/llm/client.py` expõe só papéis (`router`, `chat`, `vision`, `embed`); nenhum import de SDK de fornecedor no AGR (lint). Metering por *tag* `tenant_id`, `vertical`, `papel`, `graph_version`.
- Orçamento mensal da chave = 15% × mensalidade em USD; a mensalidade por plano não está definida (`../docs/tecnica/10`) → parâmetro, calibrar em H6. Preços de tokens (E4 §3.1–3.3, INDÍCIO-forte para Google/OpenAI) a reconferir antes de fixar tarifas; tokenizador Anthropic ≥ 4.7 produz ~30% mais tokens.
- Candidatos a `kamba-router`: Haiku 5.5, gpt-6-luna, Gemini 3.1 Flash-Lite; a `kamba-chat`: Sonnet 5.5, gpt-6.1-sol, Gemini 3.7/3.8 Flash (preço duplica em 2027-01-01). **Sem ranking**: decide-se com KAM-040; qualidade e latência em PT-AO são NÃO VERIFICADAS.
- O callback do LiteLLM para o `llm_call_log` (custom callback vs leitura do *spend log*) valida-se na versão fixada (L5).

### Testes Requeridos

- Unit: cálculo de custo, mapeamento de erros de orçamento, parsing de `aliases.yaml`.
- Integração: proxy real com fornecedores *fake* (primário em falha → secundário; orçamento esgotado).
- Segurança/CI: digest + cosign, versão mínima, egress, ausência de `pip install`, segredos fora da imagem.
- Observabilidade: 1 linha de `llm_call_log` por chamada, sem corpo de mensagem.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Privacidade:** `llm_call_log` e logs do proxy sem conteúdo; nenhum dado pessoal sai de Angola fora de destino registado com `apd_ref` (ADR-008).
- [ ] **Custo e observabilidade:** custo por tenant, por vertical e por papel desde o primeiro dia (ADR-018).
- [x] **Sem segredos:** chaves no cofre; *scan* de segredos limpo; imagem sem segredos.
- [ ] **Dependências:** digest + cosign, lista de bloqueio (LiteLLM < 1.83.0) e SBOM (ADR-005).
- [x] **Eval-gate:** alias de modelo é artefacto comportamental; SemVer atribuído; gate golden obrigatório quando KAM-040 existir.
- [ ] Revisão por dois revisores (segredos e transferência); runbook de rotação esboçado.

### Verificação dos Critérios de Aceitação

Medido a 2026-10-26, no *worktree* do ticket, contra `publico/main` em `7d849e2`.
As medições contra a imagem fixada do proxy estão em
`../docs/evidencia/KAM-030-litellm.md`, com o comando de cada uma.

**Dois critérios marcados (3 e 5) e seis parciais (1, 2, 4, 6, 7 e 8).** Nenhum
parcial fica vago: o que falta em cada um tem credor nomeado, e em quatro deles o
credor é um ticket que **não existe** (KAM-076, KAM-037, KAM-040, KAM-069).

**O critério 6 estava marcado e foi desmarcado pela revisão adversarial**, não
por medição do autor — e é a correcção mais importante desta secção. As 20
corridas que o provaram foram feitas com `Router(...)` em Python, **sem proxy,
sem `/key/generate` e sem chave virtual**, e a `models` da chave de *tenant* não
incluía o `kamba-chat-fallback2`: em `staging`, uma falha do primário topava com a
*allowlist* da própria chave e o critério falhava com toda a bateria verde. A
`models` está corrigida e tem teste de paridade com o gerador; a medição **ponta
a ponta** (provisionar uma chave, chamar por HTTP com ela, avariar o primário)
continua por fazer, e é dela que o critério depende.

**Os sete *must fix* da revisão estão corrigidos com teste** — três deles eram
mecanismos que **não podiam falhar** nas condições em que este bloco os declarou
satisfeitos. Ver `../docs/analises/ANALISE-32-KAM-030-gateway-de-llm.md`.

| # | Estado | Prova |
|---|---|---|
| 1 | **parcial** | *Digest*: `ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd…a500` no compose e em `ci/supply-chain/imagens.yaml`, lido de `docker buildx imagetools inspect` e **não** de memória; `importlib.metadata.version("litellm")` dentro da imagem deu `1.104.2`. **Versão**: 1.104.2 ≥ 1.83.0 e fora de {1.82.7, 1.82.8}, imposto pelo `forbidden_below` de `tools/blocklist.yaml` **da etiqueta** — um digest sozinho não prova versão nenhuma sem rede. **`pip install litellm` reprova o lint**: era a única das quatro cláusulas **sem máquina a impô-la** (o leitor de Dockerfiles só lia `FROM` e `ARG`), e agora lê os `RUN pip install`; 16 baterias em `tools/lint_arch/tests/test_pip_na_build.py`, com canários nas duas direcções. **O que falta, e é mais do que a primeira versão desta linha dizia**: a cláusula cosign **não está satisfeita**. O mecanismo está — a entrada tem `cosign: verificar`, o `make ci-11` falha fechado com `cosign-sem-binario` sem o binário (medido: 1 achado), e o *job* do *gate* 11 passou a instalá-lo fixado por versão com `sha256` lido da *release*. Mas **a revisão adversarial apanhou a chave**: a primeira versão fixou a que foi extraída do próprio *bundle* da assinatura, e aí o `cosign verify --key` é **tautológico** — confirma que a assinatura é consistente, não **quem** assinou, e não pode falhar por construção. Fixou-se a que o projecto **publica** (`…/BerriAI/litellm/main/cosign.pub`), que é fora de banda; e a correcção descobriu que **as duas chaves diferem**. Qual assinou a `v1.104.2` só o `cosign verify` o diz. Dívida **117**, e é medição e não código |
| 2 | **parcial** | **Uma saída estava aberta e o comentário dizia que não**: o `LITELLM_LOCAL_MODEL_COST_MAP` não existia em ficheiro nenhum, pelo que o proxy saía para `raw.githubusercontent.com` no arranque — medido no §5 da evidência pelo próprio autor, e não fechado. Está fechado (achado 3 da revisão). **Rede interna**: o compose não publica porta para `0.0.0.0` — a única publicação é `127.0.0.1`, e só para a *suite* de integração. **Egresso**: `infra/egress/litellm.yaml` com `por_omissao: negar` e **três** FQDN (os fornecedores dos aliases; o `api.groq.com` é STT e é o KAM-036); `python -m supply_chain --root . egress` dá **conforme, 13 serviços, 3 destinos aprovados**. O `services/agr/egress.yaml` continua com `destinos: []`, que é o desenho: o AGR fala com o proxy na rede interna e nunca com um fornecedor. **O que falta é o teste de rede** («pedido a FQDN fora da lista falha»): o `infra/egress/*.yaml` é o **contrato** e a aplicação na rede é do **KAM-076** (proxy de saída com *allowlist*), como o próprio cabeçalho daqueles ficheiros diz desde o KAM-067. Sem ele, um pedido a um FQDN de fora **sai**. Credor: KAM-076 |
| 3 | **satisfeito** | Os quatro em `llm/aliases.yaml`: `kamba-router` e `kamba-chat` como aliases e `kamba-vision`/`kamba-embed` como papéis `declarada` (credores KAM-033 e KAM-063 — correm no COM e no IDX, §13.2, e nenhum nó do AGR os chama). `kamba-chat` com **dois** fornecedores (`test_o_chat_tem_dois_fornecedores`). Tectos **8 s** e **20 s** (`test_os_tectos_do_131`). **Os três `router_settings` foram CONFIRMADOS contra a versão fixada**, que é o que o ticket pede («nomes a validar na versão fixada, L5»): `Router(num_retries=1, allowed_fails=3, cooldown_time=30)` aceita os três e os três ficam efectivos. **Uma armadilha pelo caminho:** o tipo `litellm.types.router.RouterConfig` (20 campos) **não tem** `cooldown_time` — quem validasse por ele concluía que o nome está errado; o caminho real é `Router.__init__` |
| 4 | **parcial** | **Idempotência**: `infra/llm/chaves.py` procura em `/key/list` e depois `/key/update` **ou** `/key/generate`; 24 baterias em `test_llm_chaves.py`, e o canário é `test_a_segunda_corrida_actualiza_e_nao_gera`. **Duas correcções da revisão adversarial**, e as duas eram silenciosas: o `/key/list` **não paginava** (o 501.º *tenant* ficava invisível, levava o 400 numa execução que devia ser idempotente, e o alerta de orçamento **nunca disparava** por ele) e o `provisionar` era *check-then-act* (duas corridas em paralelo — ou o KAM-091 a consumir `tenant.approved` *at-least-once* — davam 400 a uma delas). Agora pagina, **falha fechada** se a lista vier incompleta, e apanha o 400 de alias repetido. Era preciso ser nossa: medido, um segundo `/key/generate` com o mesmo `key_alias` devolve **400 «already exists»**. **`BUDGET_EXHAUSTED`**: o cliente devolve `OrcamentoEsgotado` e grava `budget_exhausted`. **Mas não «mapeado do 400», como o critério escreve:** a versão fixada responde **422** com `{"error": {"type": "budget_exceeded"}}`, e usa o **400** para «alias repetido» — um mapeamento pelo 400 **nunca disparava** no orçamento e disparava num erro de provisionamento. O reconhecimento é pelo `error.type`, e há um canário (`test_um_400_de_outra_coisa_nao_e_orcamento`). **Alerta a 80%**: `orcamentos()` lê `spend`/`max_budget` de `/key/list` e sai com 1 se alguma chave passou; 6 baterias, incluindo a chave sem tecto. **O que falta**: «e o AGR degrada (KAM-037)» — o modo determinístico **não existe**, e hoje o turno falha e o *job* volta à fila. Credor: KAM-037. Falta também **agendar** o `orcamentos` (KAM-071, como no KAM-026 e no KAM-029) |
| 5 | **satisfeito** | **Uma linha por chamada**, e por **todas**: as de sucesso, as de erro do fornecedor, as de tempo esgotado, as de orçamento e as de destino negado (`TestUmaLinhaPorChamada`, `TestOMapeamentoDoOrcamento`, `TestOGateDeDestino`). Uma recusa **é** uma chamada, e isso não é zelo: sem contar recusas, o teste de orçamento passava com o orçamento apagado. **Sem conteúdo**: o varrimento é **sobre os dados, com canários**, e tem o canário do canário — planta-se o canário num campo de texto e exige-se que o varrimento o **encontre**, senão não prova nada sobre a sua ausência (é a lição do KAM-026, cujo varrimento dava zero por procurar texto num campo `msgpack`). Nenhuma das dezesseis colunas pode levar *prompt*, resposta ou telefone, e não há `args_hash` do *prompt*: um *hash* de texto de cliente é um identificador estável dele. **E sob carga**, que é o que a revisão adversarial obrigou a provar: a primeira versão guardava **uma** ligação no cliente, e o `tenant_guard.tx` é exclusivo por ligação — duas conversas a chamar o modelo ao mesmo tempo faziam a segunda sair, consumir *tokens*, transferir dados e **não gravar linha**. O duplo sequencial da bateria não o via. Agora é uma ligação **por chamada**, e há um teste com duas *threads* e uma barreira que exige duas linhas. **E um preço expirado já não perde a linha**: o `custo()` levantava no único ponto do caminho de sucesso que não pode levantar, e a chamada repetia-se — segunda transferência e segundo custo. **`custo_usd` = 0,00045**: `test_a_mao` e `test_da_tabela_real`, com `Decimal` exacto, mais o caminho inteiro em `test_a_linha_leva_os_valores_e_nao_nulos`. A fórmula não é decoração — mede-se em dois pontos e com as três tarifas separadas, porque somá-las à tarifa de entrada dava um número plausível |
| 6 | **parcial** | **20 corridas, 20 sucessos**, sempre `anthropic` → 1 *retry* de `anthropic` → `openai`, contra o proxy real na imagem fixada com o primeiro fornecedor a falhar sempre. **E foi medir isto que mudou o desenho:** a configuração do `../docs/tecnica/02` §13.1, à letra — duas entradas de `model_list` com o **mesmo** `model_name` —, **não cumpre este critério**: a estratégia por omissão é `simple-shuffle`, aleatória, e nas 20 corridas daquela forma **3 falharam por completo** (o único *retry* reescolhia o *deployment* avariado), além de não existir «fornecedor primário» nenhum num grupo aleatório. Com dois grupos e um `fallbacks` nomeado é determinístico. **Um fornecedor não aprovado nunca é usado**: a `model_list` é **gerada** de `llm/aliases.yaml`, cujo `fornecedor` só aceita os três do inventário de subprocessadores — recusado pelo *lint* e pelo arranque do AGR. **A leitura de «≤ 1 retry», escrita porque a letra admite duas**: a sequência tem três tentativas, e as duas leituras são «no máximo um *retry* do primário antes de comutar» (satisfeita: é exactamente um) e «no máximo duas tentativas até ao sucesso» (não satisfeita). A segunda é **impossível** ao mesmo tempo que o critério 3, que manda `num_retries: 1`. Fica a primeira, que é a única em que os dois critérios do mesmo bloco podem valer juntos. **O que falta, e é porque esta caixa ficou vazia**: as 20 corridas usaram `Router(...)` em Python, **sem chave virtual**, e a `models` da chave de *tenant* não autorizava o `kamba-chat-fallback2` — em `staging` a comutação topava com a *allowlist* da própria chave. A `models` está corrigida, com teste de paridade contra o gerador, e há asserção automatizada sobre o `fallbacks` gerado (mais uma mutação `llm:`); mas a medição **ponta a ponta** — provisionar a chave, chamar por HTTP com ela, avariar o primário — não existe, e o *gate* 5 está reservado. Achado 11 da revisão |
| 7 | **parcial** | **O *bump* só passou a ser um *gate* depois da revisão adversarial**, e isto é o achado mais embaraçoso dela: o `escrever` reescrevia o *lock* com a `versão` **actual** e o *hash* novo, pelo que o fluxo que a documentação manda seguir — «mude o alias, corra `escrever`» — deixava o `check` **conforme sem *bump* nenhum**. Medido: trocar `por_decidir` por `claude-sonnet-5-5` e correr `escrever` dava exit 0 com a versão em 1.0.0. O `escrever` **recusa-se** agora (`BumpEmFalta`, exit 1), e o canário é esse fluxo exacto. **O *hash* e o *bump***: `ci/llm-aliases.lock` fixa o par (versão, *hash* do conteúdo), o passo `aliases` do `lint_arch` corre no *gate* 2, e **30** baterias medem-no — incluindo o `llm/precos.yaml`, que não passava por máquina nenhuma e é o ficheiro que decide o `custo_usd` de toda a linha (achado 14) — mudar o conteúdo sem subir a versão dá **exit 1** com a mensagem a dizer o que fazer (`test_conteudo_mudado_sem_bump_falha`). O *hash* **exclui os comentários**, e há um teste para isso (`test_o_hash_nao_depende_da_versao`): foi o defeito da primeira versão deste mecanismo — o cabeçalho gerado nomeia a `versao`, pelo que *hashear* o texto inteiro punha a versão dentro do *hash* e o critério ficava a não verificar nada. **O que falta é o Gate 13**: ele é «Eval golden PT-AO» (`../specs/01` §4) e **não existe** — nasce com o **KAM-040**, que é também quem escolhe os modelos. O próprio DoD o reconhece ao escrever «gate golden obrigatório **quando** KAM-040 existir». Credor: KAM-040 |
| 8 | **parcial** | **Falha fechada em `prod`**: `NegaTudoAteKam069` nega **todos** os fornecedores, um ambiente desconhecido é tratado como `prod`, e o *gate* corre **antes** da chamada — `test_em_prod_nao_sai_pedido_nenhum` prova que nada saiu para o proxy, que é o canário desta classe. A recusa grava linha `destino_negado` **sem** *tokens* nem custo, e o `CHECK llm_call_log_negado_sem_consumo` recusa-a se levar. **O *gate* corre para todos os fornecedores do alias** e não só para o de `ordem: 1`: o *fallback* é do router e o cliente não escolhe quem serve, pelo que autorizar só o primeiro deixava o segundo receber os dados **sem** o *gate* ter sido consultado por ele. **O que falta é o que o KAM-069 entrega**: a tabela `tenant_destinations`, o `apd_ref` e a consulta a eles. Hoje não há destino autorizado nenhum, pelo que `prod` nega tudo — **mais restritivo** do que o KAM-069 será, e não há janela para fechar depois. A decisão de entregar assim, em vez de parar, está escrita em `kamba_agr/llm/destinos.py` e na linha **113** de `../docs/dividas-documentais.md`; o próprio critério a autoriza ao escrever «até KAM-069 existir, só dados sintéticos em `staging`». Credor: KAM-069 |

#### DoD

| Linha | Estado | Prova |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos | **caixa vazia** | Cinco são parciais (1, 2, 4, 7 e 8) |
| **Privacidade:** `llm_call_log` e logs do proxy sem conteúdo; nada sai de Angola fora de destino com `apd_ref` | **caixa vazia — parcial** | A primeira metade está feita e medida (critério 5; e `turn_off_message_logging: true` na configuração gerada mantém o corpo das mensagens fora dos *logs* do proxy, com `litellm.turn_off_message_logging` confirmado na imagem). A segunda **não se pode satisfazer**: o `apd_ref` é uma coluna de `tenant_destinations`, que é do **KAM-069** e não existe — não há `apd_ref` para registar. Em `prod` nada sai, o que é mais forte do que a linha pede, mas **não é o que ela pede**: ela pede um registo, não uma proibição |
| **Custo e observabilidade:** custo por tenant, por vertical e por papel desde o primeiro dia | **caixa vazia — parcial** | As colunas existem e o caminho está provado: `tenant_id`, `vertical`, `papel` e `graph_version` são colunas de `dat.llm_call_log` (as duas últimas **acrescentadas** ao DDL do §14 por esta razão), e a `v_tenant_cost_daily` do KAM-081 lê daqui. Sete métricas, e o `tenant_id` **não** é etiqueta de nenhuma (`OBS-I`). **Mas o `custo_usd` é nulo em todas as chamadas de hoje**, porque o modelo é `por_decidir` e não há linha de preço — e a métrica `agr_llm_sem_preco_total` existe precisamente para isso ser visível. Marcar esta caixa era afirmar um custo que ninguém pode somar. Credor: KAM-040 |
| **Sem segredos** | **satisfeito** | Nenhum valor de segredo em ficheiro nenhum: a configuração gerada só tem `os.environ/<nome>` e o compose só `${…:?}`, pelo que o proxy **recusa-se a arrancar** sem as chaves em vez de arrancar com uma vazia. Os nomes são os de `ops/secrets-inventory.yaml` e **derivados** (`nome_da_variavel("llm_provider_key/anthropic")`), não escritos à mão — um nome à mão era um segredo que o `tools/secrets_inventory` não encontrava no inventário. `test_nenhum_segredo_na_config` e `test_o_nome_da_chave_e_do_inventario`. O *script* de provisionamento nunca imprime o valor da chave que o `/key/generate` devolve (`test_o_valor_da_chave_nao_sai_no_stdout`). **Sem base de dados do proxy em `dev`**, pelo que não há onde um segredo persistir |
| **Dependências:** digest + cosign, lista de bloqueio e SBOM | **caixa vazia — parcial** | Digest e lista de bloqueio: ver o critério 1. SBOM: o *gate* 11 gera-o e o `licencas.yaml` já tinha a linha `litellm 1.104.2 MIT CONFIRMADO`, com a versão **em uso** igual à registada, que é a regra 3 daquele ficheiro. **O pacote `litellm` não entra no AGR**: o cliente fala HTTP e o `httpx` já estava no fecho desde o KAM-026, pelo que o *gateway* **não acrescenta dependência nenhuma** — é o inverso do que aconteceu ao `psycopg` no KAM-026. Fica por marcar pela mesma razão do critério 1: o `cosign verify` nunca correu |
| **Eval-gate:** SemVer atribuído; gate golden quando KAM-040 existir | **satisfeito** | `versao: "1.0.0"` em `llm/aliases.yaml`, e o SemVer é **imposto** e não convenção: `test_uma_versao_que_nao_e_semver_e_recusada` recusa `ultima`. O *bump* é imposto pelo *lock* (critério 7). A segunda metade é condicional por escrito — «**quando** KAM-040 existir» —, e o que este ticket devia deixar pronto está pronto: o alias é um artefacto versionado com *lock* e *lint* |
| Revisão por **dois revisores**; runbook de rotação esboçado | **caixa vazia** | O *runbook* está esboçado em `../docs/runbooks/rotacao-de-chaves-de-llm.md`, com os três segredos, as suas rotações manuais (a automática é Enterprise, `E4` §2.7), o procedimento para imagem comprometida e o que ele **não** cobre. A caixa fica vazia pela outra metade: **a dos dois revisores fica vazia em toda esta linha**, por decisão escrita do fundador — uma revisão adversarial é evidência, não é um revisor. Houve **uma** revisão adversarial independente (`../docs/analises/ANALISE-32-KAM-030-gateway-de-llm.md`) |

#### Estado da prova

| Bateria | Resultado |
|---|---|
| `services/agr/tests` (unidade) | **498 ok** |
| `db/tests_agr` (PostgreSQL 18.6 real) | **ok**, com `test_llm_call_log.py` |
| `db/tests` (*gate* 8) | **ok** |
| `db/tests_isolamento` (*gate* 6) | **ok** |
| `tools/llm_config/tests` | **30 ok** |
| `tools/lint_arch/tests/test_pip_na_build.py` | **19 ok** |
| `tools/supply_chain/tests` | **ok**, com `test_cosign.py` |
| `canon_lint` (*gate* 3b) | **conforme** — e o `HEAD` também estava, pelo que os 31 achados da primeira versão eram todos desta emenda |
| `lint_refs`, `lint_handoff`, `lint_backlog`, `lint_arch all` | **conforme** |
| `supply_chain egress` | **conforme** — 13 serviços, 3 destinos aprovados |
| `supply_chain imagens` | **1 achado**: `cosign-sem-binario`. É o *gate* a falhar **fechado**, que é o comportamento certo; corre no CI com o binário instalado |
| `db/mutacoes.py --aplicaveis` | **783**, 0 não aplicáveis |
| Mutações `llm:` | **22**; a corrida de 20 deu **20 apanhadas, 0 sobreviventes** — mas só depois de se descobrir que a primeira corrida dava **10 sobreviventes porque os quatro módulos que as matam não estavam no `MODULOS_DO_AGR_UNIT`**, uma lista literal. A *suite* passava; não media. As duas últimas mutações nasceram da correcção do achado 15 e correm no PR |

#### O que se mediu e contradisse uma fonte mais alta

Três coisas, e as três mudaram código em vez de ficarem numa nota. Estão em
`../docs/evidencia/KAM-030-litellm.md` com o comando que as repete, no dicionário
§3.29 (emenda **1.38**) e nas linhas **113** a **116** de
`../docs/dividas-documentais.md`:

1. o orçamento esgotado responde **422** e não o **400** do critério 4;
2. a configuração do §13.1, à letra, **não cumpre o critério 6** (3 falhas em 20);
3. `google/` é recusado pelo proxy — o prefixo é `gemini/`, e o nome do
   subprocessador fica em espaço de nomes **separado** do da biblioteca, porque é
   o primeiro que autoriza uma transferência.

E uma quarta, sobre código já fundido: o `tools/supply_chain/cosign.py` montava
sempre o comando do fluxo *keyless*, com a sua própria nota a dizer que a forma
era «lida de memória: NÃO VERIFICADO» e que «quem ligar a primeira imagem
confirma-a nessa altura». É esta. **O LiteLLM assina com uma chave** (ECDSA
P-256) e a assinatura não tem certificado: `--certificate-identity` não tinha
valor possível.

### Handoff para Claude Code

```text
És o executor do ticket KAM-030 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-030), docs/tecnica/02_Agent_Runtime_Verticais.md (§13, §14)
e docs/tecnica/evidencia/E4_Stack_Licencas.md (§2.7).
Objectivo: LiteLLM proxy por digest+cosign (>= 1.83.0), aliases por papel, chaves virtuais e budgets por tenant,
cliente interno por papéis e dat.llm_call_log sem conteúdo.
- Só a parte MIT. Nunca pip install na build. Rede interna e egress por allowlist.
- Fallback só entre fornecedores aprovados. Nomes de parâmetros: validar na versão fixada (L5).
- Sem segredos no repositório; gate de destino default-deny em prod até KAM-069.
Não expandas escopo: guardrails (KAM-033), voz (KAM-036) e dashboards de custo (KAM-081) são tickets próprios.
Testes: unit, integração com fornecedores fake, CI de digest/egress, observabilidade. PR com o template §7.
Commits: feat(KAM-030): …
```

---

## KAM-031 — Grafo do Vendedor: esqueleto, `confirm_gate` e fluxo de dois turnos

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-027, KAM-028, KAM-029, KAM-030, KAM-032, KAM-015, KAM-019 |
| Bloqueia | KAM-033, KAM-034, KAM-037, KAM-039, KAM-040, KAM-084, KAM-114, KAM-123 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§7.1–§7.4, §6.2, §9, §14), ADR-007, ADR-012, ADR-013, `../docs/tecnica/03_Core_Comercio_Medusa.md` (§6.3) |

### Contexto

O grafo exploratório tinha dez defeitos (`../docs/tecnica/02` §7.1): `filtrar_input` antes do STT, arestas em falta, ciclo `validar→responder` ilimitado, `compra → criar_pedido` sem confirmação do cliente, sem ramo para resultados abaixo do limiar, `interrupt` com efeitos antes, sem filtro de saída. A versão corrigida tem 21 nós e 39 arestas (tabela de §7.3). A compra atravessa **dois turnos**: no 1.º envia resumo e botões; no 2.º o toque entra por `classify → confirm_gate → create_order`. A confirmação é um turno novo, não um `interrupt()`.

### Objectivo

Implementar o grafo do Vendedor completo e compilável, com todas as arestas declaradas, o `confirm_gate` e o fluxo de dois turnos, sobre as tools especificadas na TLS (backends *fake* até KAM-043/046/061), com nós de guardrail, STT e handoff como pontos de ligação a KAM-033, KAM-036 e KAM-034.

### Critérios de Aceitação

- [ ] O grafo compilado tem os 21 nós e as 39 arestas da tabela de `../docs/tecnica/02` §7.3; o teste de contrato (tabela `EDGES` em código **comparada** com o grafo compilado) falha se faltar ou sobrar uma aresta.
- [ ] O teste de contrato falha para: nó sem aresta de saída, nó inalcançável de `START`, ciclo sem contador (`compose↔validate` limitado por `citation_retries`).
- [ ] Duplo toque no botão `confirm:{cart_id}` (e 50 execuções concorrentes) produz **exactamente 1** pedido no backend *fake*; o 2.º toque recebe o *fact* `STALE_CONFIRMATION` e `compose` pede reconfirmação.
- [ ] `confirm_gate` só segue para `create_order` se `stage == awaiting_confirm`, `cart_id` do botão == `state.cart.cart_id` e o carrinho não expirou (TTL do carrinho *proposta*: 30 min, a calibrar).
- [ ] `validate` falha 1.ª vez → volta a `compose` com a lista de erros e `citation_retries=1`; 2.ª falha → `handoff_prepare`.
- [ ] `PRICE_CHANGED`, `OUT_OF_STOCK`, `LIMIT_EXCEEDED` chegam a `compose` como *facts* e não criam pedido; `UPSTREAM_*` após 1 retry vai a `handoff_prepare`.
- [ ] `ingest` termina em `END` sem envio quando o `turn_id` já foi processado ou o ritmo é excedido; `facts` é reiniciado em cada turno.
- [ ] A 1.ª mensagem da conversa identifica o assistente automático da loja; `retrieve` abaixo do limiar vai a `unknown_reply` (limiar de IDX, parâmetro).

### Detalhes Técnicos

- **Componentes:** AGR, REG, TLS, LLM (`kamba-router` em `guard_in`/`classify`, `kamba-chat` em `compose`), HND (por porta). Módulo `kamba/verticals/vendedor/{graph,nodes,routers,edges}.py`; `registry/vendedor.yaml` de KAM-027.
- **Nós:** `ingest, stt, guard_in, classify, retrieve, tools_read, cart_build, confirm_gate, create_order, order_status, tools_info, compose, validate, guard_out, unknown_reply, ask_repeat, safe_reply, send, handoff_prepare, handoff_wait, handoff_close`.
- **Fase 0:** `stt` encaminha para `ask_repeat`/`handoff_prepare` (a voz é KAM-036); `guard_in`/`guard_out` determinísticos mínimos (a cobertura completa é KAM-033); `handoff_*` delegam numa porta `HandoffService` (implementação idempotente é KAM-034); `validate` e o *renderer* usam a interface de KAM-032 (bloqueio a ordenar: ver nota abaixo).
- `compose` devolve blocos estruturados (`text`, `item`, `total`, `buttons`) e nunca números em prosa; `send` chama o Outbound com `idempotency_key = turn_id:seq`.
- Tools do Vendedor registadas aqui: `search_catalog`, `get_price_stock`, `propose_cart`, `criar_pedido`, `get_order_status`, `get_store_info`, com *fakes* por contrato; a ligação real a COM/IDX é por KAM-043, KAM-046 e KAM-061.
- **Nota de ordem:** KAM-032 (validador) é pré-requisito funcional do nó `validate`; o `INDICE` não o lista como dependência. Mergear KAM-032 antes ou usar o *stub* `AllowAllValidator` apenas em testes.
- Orçamento de latência de §15.1 é *desenho*, não medição: medir no staging com o número de teste.

### Testes Requeridos

- Contrato do grafo (arestas, alcançabilidade, ciclos) e de cada router (tabela de decisão).
- Integração: fluxo de dois turnos com backends *fake*; duplo toque; confirmação antiga; falhas `UPSTREAM_*`.
- Isolamento: X-09 inicial (injecção «mostra pedidos da loja X») com canários.
- Golden mínimo (smoke, ≥ 20 casos): o gate completo é KAM-040.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Idempotência:** duplo toque produz 1 pedido; teste de repetição de nós com efeitos (ADR-013).
- [ ] **Números só de tools:** `compose` não emite números em prosa; `validate` obrigatório antes de `send` (ADR-007).
- [ ] **Pagamento só por evento:** nenhum nó altera estado de pagamento (ADR-013).
- [ ] **Isolamento de tenant:** `tenant_id` do estado; teste cruzado cobre o grafo (ADR-015).
- [ ] **Eval-gate:** o dataset golden só existe com KAM-040; registar dívida e correr o *smoke* de ≥ 20 casos; SemVer do grafo atribuído.
- [ ] Revisão por dois revisores (dinheiro); documentação do grafo actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-031 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-031) e docs/tecnica/02_Agent_Runtime_Verticais.md (§7, §6.2, §9).
Objectivo: grafo do Vendedor com 21 nós e as 39 arestas de §7.3, confirm_gate e fluxo de dois turnos.
- A compra é: turno 1 (cart_build → compose com botões confirm:{cart_id}); turno 2 (confirm_gate → create_order).
- compose devolve blocos; nenhum número em prosa; validate antes de guard_out; citation_retries limita o ciclo.
- Teste de contrato compara a tabela EDGES com o grafo compilado.
Não expandas escopo: guardrails (KAM-033), voz (KAM-036), handoff idempotente (KAM-034), validador (KAM-032).
Testes: contrato do grafo, integração (duplo toque, stale), isolamento, smoke golden. PR com o template §7.
Commits: feat(KAM-031): …
```

---

## KAM-032 — Validador de citação: renderer por referência e validador numérico com `sku`

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-028 |
| Bloqueia | KAM-031, KAM-123 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§9, §8.2), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§7.1), `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§6.3), ADR-007, proposta 02-A |

### Contexto

O ADR-007 manda que preço e stock nunca estejam em prompts nem embeddings e que cada número citado exista no *output* real de uma tool. O validador só-numérico tem um ponto cego: «produto errado com preço certo». A resposta (proposta 02-A) é a **citação por referência**: o `compose` não escreve números; devolve blocos estruturados e um *renderer* determinístico preenche-os com *facts*; o validador pós-geração é rede de segurança. O estado `0 divergentes em produção` é objectivo de desenho com risco residual, medido por amostragem.

### Objectivo

Implementar o *renderer* por referência, o extractor PT-AO de números/`sku`/datas/horas, o validador de duas camadas com vínculo `sku↔preço`, as regras para `a_partir_de`/`sob_consulta` e as métricas, de forma reutilizável pelas duas verticais.

### Critérios de Aceitação

- [ ] A normalização monetária devolve `value_kz` inteiro para: `12500`, `12.500`, `12 500`, `12,500`, `12500 Kz`, `12.500,00 Kz`, `Kz 12.500`, `12,5 mil`, «doze mil e quinhentos» (9 formatos, 1 teste cada); moeda diferente de Kz sem *fact* de moeda é erro.
- [ ] No conjunto adversarial (≥ 200 casos, *proposta*) há **0** falsos aceites para: dinheiro sem *fact*, par `sku↔preço` trocado, nome que resolve para outro `sku`, quantidade sem *fact*, data/hora sem *fact* `datetime`, percentagem sem *fact* `discount`, número solto fora de `allowed_literals`.
- [ ] Um total somado correctamente pelo modelo mas que **não** é *fact* falha (`money_unbacked`); os totais vêm só de `propose_cart`.
- [ ] «A partir de X Kz» citado como preço fixo falha; `sob_consulta` com qualquer número falha; o *renderer* usa `OfferView.precoDisplay` com o modo.
- [ ] Dígitos de descrições de produto escritas pela PME **não** contam como *facts*; o modelo não os pode repetir.
- [ ] O *renderer* produz os blocos `text`, `item`, `total`, `buttons` e `datetime`; `render_only_ratio` (respostas sem prosa numérica livre) é medido por turno.
- [ ] Cobertura de linhas do módulo ≥ 90% (Standards §4.1); 0 divergências no conjunto adversarial é gate duro.
- [ ] Métricas `validate_fail_rate`, `validate_retry_rate`, `handoff_by_citation` e `render_only_ratio` exportadas com `tenant_id` e `vertical`.

### Detalhes Técnicos

- **Componentes:** AGR (nós `compose`, `validate`), TLS (*facts*). Módulos `kamba/validator/{extract,normalize,facts,verdict,render}.py`; dependência apenas da interface `Fact(kind, value_kz|datetime, sku, fact_id, retrieved_at)` de KAM-028.
- Veredictos (`Verdict.errors`): `money_unbacked`, `sku_price_mismatch`, `name_sku_mismatch`, `qty_unbacked`, `datetime_unbacked`, `discount_unbacked`, `number_unbacked`. Vínculo `sku↔preço` por linha/bloco; nomes resolvidos a `sku` via *facts* `name`.
- Contrato de `search_products` (`../docs/tecnica/05` §6.3): o validador aceita **só** `sku` e números presentes no *output* da tool; `sku` ausente é rejeitado.
- Limitações a assumir e testar (`../docs/tecnica/02` §9.2): afirmações sem números («mais barato», «chega amanhã»), disponibilidade qualitativa, *facts* obsoletos entre turnos (revalidação em `cart_build`/`create_order`), coincidência de valores, formatos regionais.
- Parser PT-AO com testes de propriedade; datas/horas em `Africa/Luanda` na apresentação, UTC no armazenamento.
- A regra dos três: 0 falhas em N=200 só limita o risco a ≈ 1,5% (95%); por isso o gate duro é complementado por amostragem em produção.

### Testes Requeridos

- Unit: extractor e normalização (tabela de formatos), propriedade/*fuzz* sobre números por extenso e abreviaturas.
- Adversarial (≥ 200 casos): produto errado com preço certo, totais, descontos, moeda, extenso, `a_partir_de`, `sob_consulta`.
- Integração: `compose → validate → render` com *facts* reais de tools *fake*.
- Regressão: o conjunto adversarial entra no golden de KAM-040.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Números só de tools:** nenhum preço, total, stock, data ou hora chega ao cliente sem ser *fact* citado e validado (ADR-007).
- [ ] **Eval-gate:** o validador é artefacto comportamental; SemVer atribuído; conjunto adversarial integrado no Gate 13 por KAM-040.
- [ ] **Custo e observabilidade:** métricas e logs sem conteúdo (ADR-018).
- [ ] Cobertura ≥ 90% (código de validador); revisão por dois revisores (ADR-007).
- [ ] Documentação do contrato de blocos e limitações actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-032 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-032) e docs/tecnica/02_Agent_Runtime_Verticais.md (§9).
Objectivo: renderer por referência (blocos text/item/total/buttons/datetime) e validador pós-geração com
extractor PT-AO, vínculo sku↔preço, regras a_partir_de/sob_consulta e métricas.
- Tolerância zero em dinheiro; totais nunca somados pelo modelo; dígitos de descrições não são facts.
- Veredictos: money_unbacked, sku_price_mismatch, name_sku_mismatch, qty_unbacked, datetime_unbacked,
  discount_unbacked, number_unbacked.
- Conjunto adversarial >= 200 casos; cobertura >= 90%.
Não expandas escopo: o grafo (KAM-031/035) e o dataset golden completo (KAM-040) são tickets próprios.
Testes: unit, adversarial, integração, regressão. PR com o template §7. Commits: feat(KAM-032): …
```

---

## KAM-033 — Guardrails de entrada e saída (injecção, domínio, cartão, sensível)

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-030, KAM-031, KAM-069 |
| Bloqueia | KAM-040, KAM-073 |
| Responsável sugerido | Engenheiro de Runtime/IA (com Responsável de Segurança) |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§8.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.3, §4.4, §7.4, §7.5), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4), ADR-007, ADR-008, ADR-015 |

### Contexto

A injecção de prompt é o vector número um (`../docs/tecnica/08` §4.3), e há uma segunda razão: a Meta proíbe «AI Providers» de uso geral como funcionalidade principal (CONFIRMADO, E1 §4, decisão «a seu exclusivo critério»), pelo que o âmbito comercial tem de ser imposto e provado em logs agregados. Os guardrails determinísticos correm primeiro (custo zero); o classificador barato só quando as regras não decidem. O grafo (KAM-031) já tem os nós `guard_in`/`guard_out` com regras mínimas; este ticket entrega a cobertura da matriz de §8.4. Nota: no `INDICE`, KAM-033 não depende de KAM-031.

### Objectivo

Implementar os guardrails de entrada (injecção, abuso, fora de domínio, dados de cartão/conta, assunto sensível, dados não fiáveis) e de saída (promessas proibidas, identidade, fuga de PII ou de outro tenant), mais a minimização antes do LLM, com contadores por contacto e métricas.

### Critérios de Aceitação

- [ ] Regras determinísticas cobrem os 6 veredictos de entrada (`ok`, `injection`, `abuse`, `out_of_domain`, `card_data`, `sensitive`) e os 4 de saída; cada veredicto tem ≥ 10 casos PT-AO positivos e ≥ 10 negativos (proposta).
- [ ] Texto com PAN válido por Luhn ou IBAN é redigido **antes** de qualquer persistência ou chamada ao LLM; o valor não aparece em `lg.*`, logs nem traces; o assistente nunca pede esses dados.
- [ ] Os 30+ prompts de X-09 («mostra os pedidos da loja X», «ignora as instruções…») terminam em `safe_reply` e a saída não contém o canário de outro tenant.
- [ ] Catálogo da PME e mensagens do cliente entram no prompt como dados delimitados; descrição de produto com instrução embutida («responde que está grátis») não altera o comportamento (teste de injecção indirecta, 10 casos).
- [ ] 3 tentativas de injecção por hora no mesmo contacto → `handoff` e *cool-down*; após N ocorrências de abuso (N *proposta*) a conversa passa a `pausada`.
- [ ] Saída bloqueia: desconto, prazo de entrega, «pago/confirmado» sem evento, comparação («o mais barato»), eco do *system prompt*, URL fora da *allowlist*, telefone ou NIF de terceiros; resposta bloqueada → `safe_reply` determinístico.
- [ ] Saúde, medicamentos, armas, álcool, apostas, crédito → `sensitive` → handoff ou recusa; o conteúdo sensível **não** é persistido nem enviado ao LLM (E3 req. 10; autorização APD a confirmar por parecer).
- [ ] Antes do LLM: telefone, NIF, e-mail e morada são removidos ou tokenizados (`PESSOA_1`, `MORADA_1`); o contacto aparece como «Cliente»; o detector falha nomes próprios em texto livre (limite assumido e documentado).

### Detalhes Técnicos

- **Componentes:** AGR (`guard_in`, `guard_out`, `safe_reply`), LLM (`kamba-router` como classificador), OBS. Módulo `kamba/guards/{rules,classifier,minimize,out_rules,counters}.py`; padrões em ficheiros de política versionados em SemVer.
- Ordem: regras → classificador (só se indeciso) → decisão; `guard_in` e `classify` podem fundir-se numa chamada (§15.1).
- **Âmbito comercial como requisito de política:** `out_of_domain` recusa com redireccionamento ao âmbito da loja; métrica agregada `out_of_domain_total` guardada como prova de âmbito (sem conteúdo).
- A 1.ª mensagem identifica o assistente automático da loja (Lei de IA em projecto, INDÍCIO, E3 §3); «falar com humano» presente em toda a conversa (Messaging Policy, CONFIRMADO).
- Limiares do classificador e N de abuso: *proposta*, a calibrar no golden. A minimização **reduz** exposição mas não prova que deixou de haver transferência (a confirmar por parecer, E3 req. 6).
- Injecção do cartão de teste usa só números de teste (por exemplo, PAN de teste público), nunca dados reais.

### Testes Requeridos

- Unit: regras determinísticas (tabelas positivo/negativo), Luhn, redacção, contadores.
- Integração: nós `guard_in`/`guard_out` no grafo de KAM-031; X-09 com canários.
- Adversarial: injecção directa e indirecta em PT-AO (≥ 30 e ≥ 10 casos); entra no golden.
- Privacidade: varrimento de `lg.*`, logs e traces por PAN e telefone = 0.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Isolamento de tenant:** nenhum token de outro tenant em saídas; teste cruzado X-09 (ADR-015).
- [ ] **Privacidade:** minimização antes do LLM; PAN/IBAN nunca persistidos; destino registado se houver transferência (ADR-008).
- [ ] **Números só de tools:** `guard_out` bloqueia promessas e números fora de *facts* (ADR-007).
- [ ] **Eval-gate:** regras e prompts são artefactos comportamentais; SemVer atribuído; golden verde.
- [ ] Revisão por dois revisores (dados pessoais e segurança); documentação de política actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-033 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-033), docs/tecnica/02_Agent_Runtime_Verticais.md (§8.4)
e docs/tecnica/08_Seguranca_Conformidade.md (§4.3, §7.4, §7.5).
Objectivo: guardrails de entrada (injecção, abuso, fora de domínio, cartão, sensível) e de saída (promessas,
identidade, fuga), minimização antes do LLM, contadores por contacto e métricas.
- Determinístico primeiro; classificador barato só se indeciso.
- Catálogo e mensagens são dados, nunca instruções. PAN/IBAN redigidos antes de persistir.
- Âmbito comercial imposto (Meta: AI Provider de uso geral é proibido); sem conteúdo em logs.
Não expandas escopo: red-team (KAM-073) e política de categorias (KAM-088) são tickets próprios.
Testes: unit, integração, adversarial PT-AO (>= 30 + 10), privacidade. PR com o template §7. Commits: feat(KAM-033): …
```

---

## KAM-034 — Handoff idempotente em dois nós e retoma por compare-and-set

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-019, KAM-026, KAM-031, KAM-018 |
| Bloqueia | KAM-040, KAM-114 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§11), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§11), ADR-002, ADR-009, proposta 02-C, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.6) |

### Contexto

`interrupt()` re-executa o nó desde o início na retoma e exige checkpointer durável e `thread_id` (CONFIRMADO). Um nó único com efeitos (abrir conversa no Chatwoot) antes do `interrupt()` duplicaria conversas. Padrão adoptado: `handoff_prepare` (idempotente, com efeitos) e `handoff_wait` (só `interrupt()`, sem efeitos antes, sem `try/except`), mais `handoff_close`. A retoma vem do HND (webhook do Chatwoot) e pode chegar duplicada.

### Objectivo

Implementar a porta `HandoffService` usada pelos nós de handoff de ambas as verticais: idempotência por `handoff_id`, estados de `handoffs`, retoma por *compare-and-set*, *timeout* às 24 h, invariantes de não-reentrada e degradação quando o HND está indisponível.

### Critérios de Aceitação

- [ ] `handoff_id = sha256(thread_id:handoff_seq)`; re-executar `handoff_prepare` 5 vezes (incluindo falha injectada entre `openHandoff` e o enfileiramento da mensagem) produz **1** conversa no HND (*fake* a contar) e **1** mensagem ao cliente (`key = {hid}:msg`).
- [ ] `handoff_wait` tem o `interrupt()` como 1.ª instrução; teste AST falha se existir efeito antes dele, `interrupt()` dentro de `try/except` ou dentro de ciclo `while`.
- [ ] `POST /internal/resume {thread_id, handoff_id, outcome}` faz CAS `waiting → resumed`; dois pedidos concorrentes com o mesmo `handoff_id` produzem 1 retoma e o 2.º devolve *no-op* (200).
- [ ] Origem autenticada pelo `secret` do *agent bot* do HND; `secret` inválido devolve 401 e incrementa métrica; `Command(resume=…)` corre sob o lock da conversa.
- [ ] Mensagem de cliente num thread com `handoffs.status = 'waiting'` **não** invoca o grafo; vai ao HND (invariante), 0 invocações de grafo com *input* novo.
- [ ] `HandoffUnavailable` → estado `degraded`, mensagem de degradação ao cliente e `conversation.mode = pausada`; sem excepção não tratada.
- [ ] Sem resposta humana em 24 h o scheduler retoma com `outcome=timeout` e `handoff_close` envia a mensagem de alternativas (telefone/e-mail/loja) uma só vez (`key = {hid}:timeout`).
- [ ] Estados `waiting → resumed | timeout | cancelled | degraded` com `opened_at`, `resumed_at`, `resolver`; a métrica de retoma < 15 min (alvo ≥ 80%, a validar) é calculável por tenant.

### Detalhes Técnicos

- **Componentes:** AGR, HND (KAM-019: `openHandoff` idempotente por `handoffId`, `setBotMuted`, `close`), Postgres (checkpointer KAM-026), scheduler EVT. Módulos `kamba/handoff/{service,nodes,resume_api,timeouts}.py`; tabela `handoffs` (criar se KAM-019 não a tiver criado; confirmar dono do DDL na PR).
- **CAS:** `UPDATE handoffs SET status='resumed', resumed_at=now() WHERE handoff_id=$1 AND status='waiting' RETURNING 1`; 0 linhas → *no-op*.
- O bot do Chatwoot conseguir mudar `pending → open` é **NÃO VERIFICADO** (spike de 1 dia em KAM-019; plano B: utilizador-serviço com token da Application API).
- A notificação ao dono não pode usar o número da própria loja (`../docs/tecnica/01` §11.4); usa o painel/e-mail do HND.
- Mudança incompatível de grafo exige *drain* dos handoffs `waiting` ou compatibilidade dos nós pós-`interrupt` durante N releases (`schema_version`).
- Nunca invocar o grafo com *input* novo em thread com `interrupt` pendente (CHR/AGR consultam `conversations.mode` e `handoffs.status`).

### Testes Requeridos

- Unit: derivação de `handoff_id`, máquina de estados de `handoffs`, CAS.
- Integração (Postgres + HND *fake*): repetição de nó, webhook duplicado, retoma após reinício do worker, *timeout* às 24 h com relógio simulado.
- Contrato/CI: teste AST sobre `handoff_wait`.
- Isolamento: `resume` com `thread_id` de outro tenant é recusado.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Idempotência:** nó re-executado e webhook duplicado sem duplicar efeitos (ADR-002, ADR-009).
- [ ] **Isolamento de tenant:** `resume` valida `tenant_id` do `thread_id` e do `handoff` (ADR-015).
- [ ] **Privacidade:** resumo do handoff sem telefone em claro; logs sem conteúdo (ADR-010).
- [ ] **Eval-gate:** nós de handoff são artefactos comportamentais; golden de handoff correcto ≥ 85% (H7) quando KAM-040 existir.
- [ ] Revisão por dois revisores; documentação do protocolo actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-034 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-034), docs/tecnica/02_Agent_Runtime_Verticais.md (§11)
e docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§11).
Objectivo: HandoffService com handoff_prepare idempotente, handoff_wait só com interrupt(), handoff_close,
/internal/resume com compare-and-set, timeout de 24 h e degradação.
- handoff_id = sha256(thread_id:handoff_seq); todos os efeitos com chave de idempotência.
- interrupt() na 1.ª linha, sem try/except, sem ciclo; teste AST obrigatório.
- Nunca invocar o grafo com input novo em thread com interrupt pendente.
Não expandas escopo: provisionamento do Chatwoot (KAM-019) e protocolo bot↔dono (KAM-018) são tickets próprios.
Testes: unit, integração (webhook duplicado, restart, timeout), AST, isolamento. PR com o template §7.
Commits: feat(KAM-034): …
```

---

## KAM-035 — Grafo de Serviços: slots, disponibilidade e `book_slot`

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-027, KAM-028, KAM-047 |
| Bloqueia | KAM-039, KAM-040 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§8.1, §8.2, §5.4, §6.2), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§7), ADR-007, ADR-012, ADR-013 |

### Contexto

A vertical Serviços (persona Rececionista) existe para provar a regra de dois (ADR-012): reutiliza os nós comuns do Vendedor (`ingest`, `stt`, `guard_in`, `compose`, `validate`, `guard_out`, `send`, `ask_repeat`, `safe_reply`, `handoff_*`, `confirm_gate` com `cart_id` ↔ `hold_id`) e acrescenta `classify` próprio, `slots_collect`, `check_availability`, `book_slot`, `cancel_booking` e `list_services`. A disponibilidade é só tool: o modelo nunca calcula horas livres. `../docs/tecnica/02` §8.1 dá o diagrama mas não a tabela de arestas: este ticket deriva-a e submete-a a revisão.

### Objectivo

Implementar o grafo de Serviços sobre o módulo `servicos` (KAM-047) e a TLS, com preenchimento de slots em vários turnos (uma pergunta de cada vez), propostas de até 10 opções, confirmação por botão e marcação/remarcação/cancelamento idempotentes.

### Critérios de Aceitação

- [ ] A tabela de arestas derivada do diagrama de §8.1 (guardada como `EDGES` em código) coincide com o grafo compilado; o teste de contrato falha para nó sem saída, nó inalcançável e ciclo sem contador.
- [ ] Intenções suportadas: `marcar`, `remarcar`, `cancelar`, `disponibilidade`, `servicos_precos`, `info_loja`, `confirmar`, `humano`, `outro`; `outro` vai a `safe_reply`.
- [ ] `slots_collect` pergunta **uma** coisa por mensagem (`servico`, `data`, `hora`, `profissional?`); hora ambígua («às 5») gera pergunta de desambiguação, nunca palpite.
- [ ] `check_availability` propõe no máximo **10** opções (limite de linhas de lista interactiva da Meta, CONFIRMADO, E1 §7); sem disponibilidade responde com *fact* de indisponibilidade e alternativas.
- [ ] Duplo toque em `confirm:{hold_id}` produz exactamente 1 marcação; marcar o mesmo `slot_id` ocupado por outro contacto devolve `SLOT_TAKEN` explicado em `compose`.
- [ ] Cada data, hora e duração na resposta existe num *fact* `datetime`/`duration`; teste adversarial com ≥ 30 casos (horas trocadas, fuso, «amanhã» ambíguo) tem 0 falhas.
- [ ] `reschedule_booking` é atómico (cancela e marca na mesma transacção): falha injectada a meio deixa a marcação original intacta.
- [ ] Falhas `UPSTREAM_*` em `check_availability`/`book_slot`/`cancel_booking` vão a `handoff_prepare`; entitlement `marcacoes_mes` esgotado devolve `LIMIT_EXCEEDED` com oferta de handoff.

### Detalhes Técnicos

- **Componentes:** AGR, REG (`registry/servicos.yaml`), TLS, COM/`servicos` (KAM-047), LLM. Módulo `kamba/verticals/servicos/{graph,nodes,routers,edges}.py`.
- **Tools** (`../docs/tecnica/02` §6.2), registadas aqui: `list_services`, `get_availability(serviço, intervalo)` (read), `book_slot(slot_id, serviço)`, `cancel_booking(id)`, `reschedule_booking(id, novo_slot)` (write, botão), `get_store_info`.
- Botão de confirmação: `confirm:{hold_id}`; `../docs/tecnica/02` §6.2 diz `confirm:{cart_id}` na tabela de tools e `hold_id` em §8.2 — normalizar para `hold_id` (a mesma lógica do `confirm_gate`, `../docs/tecnica/02` §8.1).
- Idempotência: chave de KAM-029 (`cart_id` ↔ `hold_id`) e unicidade `(contact, slot_id)` no módulo.
- Validador estendido a datas, horas e durações (KAM-032); apresentação em `Africa/Luanda`, armazenamento UTC.
- Sinal/depósito é opcional e usa PAY como no Vendedor; `payment.confirmed` confirma a marcação (consumo em KAM-038).
- Reutilização: nenhum nome de vertical em `core/`; a medida de reuso é KAM-039.

### Testes Requeridos

- Contrato do grafo (arestas, alcançabilidade, ciclos) e dos routers.
- Integração com o módulo `servicos` real: marcação, remarcação atómica, `SLOT_TAKEN`, duplo toque.
- Adversarial de datas/horas (≥ 30 casos); X-02/X-09 para as tools de Serviços (contacto X não vê marcações de Y).
- Golden mínimo (smoke ≥ 20 casos); o gate completo é KAM-040.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Idempotência:** duplo toque e repetição de `book_slot` sem duplicar (ADR-013).
- [ ] **Números só de tools:** datas, horas e durações só de *facts* (ADR-007).
- [ ] **Isolamento de tenant e contacto:** tools de Serviços cobertas pela suite cruzada (ADR-015).
- [ ] **Eval-gate:** dívida registada até KAM-040; SemVer do grafo e de `servicos.yaml`.
- [ ] Revisão por dois revisores; documentação actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-035 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-035) e docs/tecnica/02_Agent_Runtime_Verticais.md (§8).
Objectivo: grafo de Serviços (Rececionista) com slots_collect, check_availability, book_slot, cancel_booking,
list_services e confirm_gate por hold_id, reutilizando os nós comuns do Vendedor sem flags de vertical no core.
- Máximo 10 opções por lista; uma pergunta por mensagem; hora ambígua pergunta-se.
- Datas/horas só de facts datetime; reschedule atómico; write com botão e idempotência.
- Deriva a tabela de arestas do diagrama de §8.1 e guarda-a como EDGES para o teste de contrato.
Não expandas escopo: o módulo servicos é KAM-047; lembretes são KAM-048; a prova da regra de dois é KAM-039.
Testes: contrato do grafo, integração com servicos real, adversarial de datas, isolamento. PR com o template §7.
Commits: feat(KAM-035): …
```

## KAM-036 — Pipeline de voz: STT com confiança, eco e fallback a humano

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-020, KAM-030, KAM-107, KAM-069 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§10), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.5), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§3.2, §3.4), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (req. 7, 8), ADR-008, ADR-014 |

### Contexto

O cliente angolano usa notas de voz. Qualidade do STT em português de Angola (WER) e a detecção de língua para Kimbundu/Umbundu são **NÃO VERIFICADAS** (L1): decide-se com áudio real no golden, e o fornecedor escolhido sai de KAM-107 (spike). Voz identifica o titular: STT num fornecedor fora de Angola é transferência de dados pessoais (D1, ADR-008); sem procedimento APD concluído (a confirmar por parecer) não entra voz em produção com dados reais. O custo dominante continua a ser o do canal (0,004 USD por mensagem Meta), não o da voz.

### Objectivo

Implementar o nó `stt` e a interface `SttProvider`: descarregar a nota via MED/STO (KAM-020), transcrever com sinais de confiança, classificar em alta/média/baixa e encaminhar para `guard_in`, `ask_repeat` com eco, ou `handoff_prepare`, com apagamento do áudio após transcrição.

### Critérios de Aceitação

- [ ] A interface `SttProvider` tem ≥ 2 implementações (uma real, uma *fake* determinística); a escolha do fornecedor de produção é a decisão registada de KAM-107, não deste ticket.
- [ ] Áudio acima do limite de duração por turno (omissão *proposta*: 120 s) ou em formato inválido vai a `ask_repeat` («envie uma mensagem mais curta»), sem chamada ao STT.
- [ ] Confiança **alta** (língua `pt` e sinais acima dos limiares) segue para `guard_in`; **média** envia o eco («Percebi: 2 sacos de cimento. Está certo?») com botões; **baixa** ou língua ≠ `pt` vai a `handoff_prepare` com resumo «cliente enviou nota de voz que não foi possível transcrever».
- [ ] Limiares iniciais herdados do Whisper de referência (`avg_logprob` −1,0, `compression_ratio` 2,4, `no_speech_prob` 0,6: INDÍCIO) são **configuração**, não constantes; o relatório de calibração com áudio PT-AO fixa os valores finais.
- [ ] Compra iniciada por voz **nunca** cria pedido sem o botão de confirmação com resumo do carrinho (teste: transcrição «quero 3 caixas» → 0 pedidos até `confirm:{cart_id}`).
- [ ] O blob de áudio é apagado após transcrição com sucesso (alvo ≤ 24 h; limite de erro 72 h); teste de varrimento: 0 blobs de áudio após o prazo; a URL da Meta nunca é persistida.
- [ ] Com `voice_enabled = false` (omissão por tenant até concluir D1/APD) a nota de voz é tratada como «não suportada» com pedido de texto, sem enviar o áudio a terceiros.
- [ ] Métricas por tenant: latência STT, distribuição de confiança, taxa de handoff por baixa confiança, custo por nota; p95 de voz (alvo 6–12 s, desenho) medido e registado.

### Detalhes Técnicos

- **Componentes:** AGR (`stt`, `ask_repeat`), MED, STO, LLM/STT. Módulos `kamba/stt/{provider,pipeline,confidence}.py`; estados `recebido → descarregado → transcrito → alta|media|baixa` (`../docs/tecnica/02` §10).
- **Candidatos** (preços E4): Groq `whisper-large-v3-turbo` ~0,04 USD/h (WER 12%, INDÍCIO-forte), `whisper-large-v3` ~0,111 USD/h; OpenAI `gpt-4o-mini-transcribe` ~0,003 USD/min, `gpt-transcribe` 0,0045 USD/min. Nota de 20 s ≈ 0,0002 a 0,001 USD (ilustrativo). Retenção zero no fornecedor STT é requisito (E3 req. 8): evidência a arquivar.
- Sinais de confiança variam por fornecedor (*logprobs* nos modelos GPT: a confirmar); normalizar para `SttResult{texto, lingua, confianca, sinais}`.
- Kimbundu/Umbundu: sem STT de produção; baixa confiança → humano. **Não** tratar a detecção de língua como fiável (NÃO VERIFICADO).
- Áudio de teste: sintético ou gravado pela equipa com consentimento; conversas reais do WhatsApp não treinam nem afinam modelos (Termos Meta §4.7, a verificar o texto EN).
- Saída em voz fora do Piloto (só texto).

### Testes Requeridos

- Unit: classificação alta/média/baixa a partir de sinais; limites de duração; formato.
- Integração: nota → STO → STT *fake* → grafo; eco com botões; fallback a humano; apagamento do blob.
- Isolamento: URL assinada de áudio do tenant B recusada com contexto de A (ISO-47..50 por analogia).
- Golden de voz (parte de KAM-040): WER por fornecedor e decisão de limiares com áudio real e consentimento.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Privacidade:** áudio apagado após transcrição; nenhum áudio a destino sem registo `apd_ref` (ADR-008, ADR-014); sem conteúdo em logs.
- [ ] **Idempotência:** reprocessamento do mesmo `media_id` não duplica transcrição nem custo.
- [ ] **Números só de tools:** transcrição é dado de entrada, nunca *fact*; a confirmação de dinheiro por botões (ADR-007).
- [ ] **Custo e observabilidade:** custo por nota e latência por fornecedor.
- [ ] **Eval-gate:** nó `stt` e limiares são artefactos comportamentais; SemVer; golden de voz verde.
- [ ] Revisão por dois revisores (dados pessoais); documentação actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-036 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-036), docs/tecnica/02_Agent_Runtime_Verticais.md (§10)
e docs/tecnica/08_Seguranca_Conformidade.md (§7.5).
Objectivo: nó stt com SttProvider, confiança alta/média/baixa, eco com botões, fallback a humano e apagamento
do áudio após transcrição; feature flag voice_enabled por tenant (omissão false até D1/APD).
- Limiares são configuração a calibrar com áudio real; fornecedor de produção vem de KAM-107.
- Compra por voz exige sempre confirmação por botões. Nunca persistir URL da Meta.
- Qualidade em PT-AO e língua detectada são NÃO VERIFICADAS: não as assumas.
Não expandas escopo: download autenticado e storage (KAM-020) e spike de WER (KAM-107) são tickets próprios.
Testes: unit, integração, isolamento, golden de voz. PR com o template §7. Commits: feat(KAM-036): …
```

---

## KAM-037 — Modo determinístico sem LLM e degradação

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-031, KAM-160 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§14, §13.3), `../docs/tecnica/00_Arquitectura_Solucao.md` (princípio 12, §7), ADR-002, ADR-007 |

### Contexto

«Degradar, nunca calar» (princípio 12): falha de LLM, canal ou pagamento tem *fallback* determinístico ou fila. O modo determinístico é um sub-grafo LangGraph sem LLM (não Typebot: licença FSL, ADR-002) que serve menus por botões/lista, estado do pedido, horário/morada, referência já emitida e «falar com humano». Dispara com *timeout* de 20 s, HTTP 429, 400 de orçamento esgotado ou *circuit breaker* aberto, e quando a contrapressão da fila o exige (KAM-025). O Piloto tem alvo de disponibilidade do caminho de venda de 99,5%.

### Objectivo

Implementar o sub-grafo determinístico do Vendedor, o detector de degradação (*circuit breaker* do LLM, orçamento, contrapressão), a transição transparente para o modo e de volta, e as métricas `degraded_turns`.

### Critérios de Aceitação

- [ ] Com o LLM *fake* a dar *timeout* de 20 s (ou 429 ou `BUDGET_EXHAUSTED`) a mensagem recebe resposta determinística em ≤ 1 turno, sem excepção e sem mensagem em falta (0 turnos sem resposta em 100 execuções).
- [ ] O modo serve: menu principal (≤ 3 botões), lista de opções (≤ 10 linhas), estado do pedido por `numero_publico`, horário/morada, referência de pagamento **já emitida**, e «falar com humano».
- [ ] Toque em `confirm:{cart_id}` em modo degradado cria **1** pedido e responde com a referência por *template* estático e *facts*; nenhum texto livre sem *renderer*.
- [ ] A intenção é decidida sem LLM (identificadores de botão/lista e palavras-chave); texto livre não reconhecido devolve o menu, não inventa resposta.
- [ ] O validador (KAM-032) aplica-se também ao modo determinístico: 0 números fora de *facts*.
- [ ] `degraded_turns` e o motivo (`timeout`, `429`, `budget`, `breaker`, `backpressure`) são métricas por tenant; alerta quando > 5% dos turnos de um tenant em 15 min (limiar *proposta*).
- [ ] Ao recuperar o LLM, o próximo turno volta ao modo normal; respostas antigas pendentes **não** são reenviadas fora da janela de 24 h.
- [ ] Tenant no tecto de concorrência com a fila acima do limiar é movido para o modo determinístico (teste de contrapressão).

### Detalhes Técnicos

- **Componentes:** AGR, LLM (detector), Outbound. Módulo `kamba/verticals/vendedor/degraded/{graph,intents,templates}.py`; textos estáticos em `pt` de Angola versionados.
- Reutiliza `confirm_gate`/`create_order`/`order_status`/`tools_info` do grafo normal; só `classify` e `compose` mudam para versões sem LLM.
- O *circuit breaker* do LLM usa os mesmos limiares do proxy (`allowed_fails: 3`, `cooldown_time: 30`, a validar na versão fixada); Postgres/checkpointer indisponível **não** é degradação: o turno não corre e a mensagem permanece na fila (alerta crítico).
- Cobertura de Serviços: este ticket entrega o perfil do Vendedor; o perfil de Serviços (menu de marcações, estado, cancelamento) usa o mesmo mecanismo e deve ser aberto como ticket se `KAM-035` já estiver `Done`.
- Janela de 24 h: respostas fora da janela só por *template* (KAM-015); o modo não contorna `WINDOW_CLOSED`.

### Testes Requeridos

- Unit: detector de degradação, decisão de intenção sem LLM, *templates*.
- Integração: LLM *fake* em falha (timeout, 429, budget); toque de confirmação em modo degradado; recuperação.
- Carga leve: contrapressão com fila acima do limiar.
- Validação: conjunto de facts → texto idêntico ao do *renderer* (sem LLM).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Idempotência:** confirmação em modo degradado produz 1 pedido (ADR-013).
- [ ] **Números só de tools:** *renderer* e validador também aqui (ADR-007).
- [ ] **Custo e observabilidade:** `degraded_turns` por motivo e tenant (ADR-018).
- [ ] **Dependências:** nenhum Typebot, n8n ou Dify; sub-grafo em LangGraph (ADR-002).
- [ ] **Eval-gate:** o sub-grafo é artefacto comportamental; SemVer; casos degradados no golden.
- [ ] Documentação do runbook de degradação actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-037 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-037) e docs/tecnica/02_Agent_Runtime_Verticais.md (§14).
Objectivo: sub-grafo LangGraph sem LLM (menus, estado do pedido, horário/morada, referência emitida, humano)
com detector de degradação (timeout 20 s, 429, budget, breaker, contrapressão) e métricas degraded_turns.
- Nunca Typebot/n8n/Dify. Textos estáticos; números só por renderer e facts.
- Confirmação por botão em modo degradado cria 1 pedido.
- Não reenviar respostas antigas fora da janela de 24 h.
Não expandas escopo: perfil de Serviços só se KAM-035 estiver Done e como ticket separado.
Testes: unit, integração com LLM fake em falha, carga leve, renderer. PR com o template §7. Commits: feat(KAM-037): …
```

---

## KAM-038 — Subscrição de eventos: as verticais acordam por evento

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-006, KAM-027, KAM-007 |
| Bloqueia | KAM-039 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§3, §5.1, §8.2, §15.2), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§12), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (envelope, `events_consumed`), ADR-009, ADR-012 |

### Contexto

As verticais não se chamam entre si: subscrevem eventos do EVT (ADR-009). O AGR acorda por evento quando há algo a fazer (`payment.confirmed` → notificar cliente e dono; `order.expired`; `stock.low`; `booking.created`; `booking.reminder_due`). O envelope é versionado (`id`, `tipo`, `versao`, `tenant_id`, `trace_id`, `ocorrido_em`, `payload` sem PII); a entrega é *at-least-once*; os consumidores são idempotentes por `evento.id` (`events_consumed`, KAM-006) com DLQ após 5 tentativas.

### Objectivo

Ligar as `subscriptions` do registo (KAM-027) a consumidores no AGR: handlers idempotentes por vertical que iniciam «turnos por evento» sob o lock da conversa, com notificação via Outbound (janela/*template*) ou via HND ao dono.

### Critérios de Aceitação

- [ ] Para cada `subscriptions` de `registry/*.yaml` existe 1 consumidor registado; `tipo`/`versao` desconhecidos reprovam o arranque (partilha a validação de KAM-027).
- [ ] O mesmo `evento.id` entregue 5 vezes (inclusive em paralelo) produz **1** efeito (1 mensagem, 1 linha em `events_consumed`); 2.ª entrega é *no-op*.
- [ ] Um evento com **versão desconhecida** não é ignorado em silêncio: falha visível, reencaminha para DLQ e emite alerta (regra de Standards §5; contrariamente a `../docs/tecnica/03` §12, que diz «ignoram»).
- [ ] Envelope com `tenant_id` forjado (diferente do `agregado`) é rejeitado; o consumidor define `SET LOCAL app.tenant_id` só a partir do envelope **validado** (ISO-43..46).
- [ ] O turno por evento usa `turn_id = event_id`, corre sob o lock da conversa e **não** corre se a conversa estiver com humano (`pausada`/`waiting`): notifica o HND.
- [ ] Notificação ao cliente com janela aberta é mensagem livre (*service*); com janela fechada, *template utility* aprovado; sem *template* aprovado → não envia e alerta (decisão do Outbound, KAM-015).
- [ ] Notificação ao **dono** nunca usa o número da própria loja; vai pelo HND (painel/e-mail do Chatwoot).
- [ ] Eventos de pagamento têm prioridade sobre mensagens de conversa; `payment.*` p99 de *lag* ≤ 10 s no teste de carga leve (alvo de `../docs/tecnica/06`).

### Detalhes Técnicos

- **Componentes:** AGR, EVT (consumidores BullMQ), REG, HND, Outbound. Módulos `kamba/events/{subscribe,handlers,envelope,turns}.py`.
- Handlers de Piloto: Vendedor — `payment.confirmed` v1, `order.expired` v1, `stock.low` v1; Serviços — `booking.created` v1, `booking.reminder_due` v1, `payment.confirmed` v1. Acrescentar `payment.manual_confirmed` v1 a ambos (o Piloto confirma por `ManualProvider`, KAM-055): alteração aos YAML (*proposta*, SemVer MINOR).
- Os *payloads* trazem `contact_id`, nunca telefone; a resolução de destinatário é do Outbound.
- Dependência funcional não declarada no `INDICE`: os esquemas versionados vêm de KAM-007; usar o catálogo de KAM-007 quando existir.
- Garantias de entrega do BullMQ **NÃO VERIFICADAS** (L6): handlers idempotentes, DLQ e reprocessamento cobrem o risco.

### Testes Requeridos

- Unit: roteamento por `(tipo, versao)`, validação do envelope.
- Integração (Postgres e Redis reais): entrega duplicada e concorrente, DLQ após 5 falhas, versão desconhecida.
- Isolamento: envelope forjado; consumidor de A sem acesso a eventos de B (ISO-43..46).
- Fluxo: `payment.confirmed` → mensagem ao cliente com janela aberta e fechada (Outbound *fake*).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Idempotência:** consumo repetido sem duplicar efeitos; `events_consumed` (ADR-009).
- [ ] **Isolamento de tenant:** `tenant_id` validado do envelope; teste cruzado cobre consumidores (ADR-015).
- [ ] **Privacidade:** eventos e logs sem telefone nem conteúdo (ADR-010).
- [ ] **Pagamento só por evento autenticado:** o AGR só reage a eventos do PAY, nunca os produz (ADR-013).
- [ ] **Custo e observabilidade:** *lag* de consumo por consumidor e custo de mensagens por origem.
- [ ] Documentação do catálogo de subscrições actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-038 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-038), docs/tecnica/02_Agent_Runtime_Verticais.md (§5.1, §8.2)
e docs/tecnica/06_Dados_Eventos_Analytics.md (envelope e events_consumed).
Objectivo: consumidores no AGR ligados às subscriptions dos registry/*.yaml; turnos por evento idempotentes
(turn_id = event_id), sob o lock da conversa, com Outbound (janela/template) ou HND para o dono.
- Versão de evento desconhecida falha visível → DLQ; nunca ignorar.
- tenant_id só do envelope validado. Nunca notificar o dono pelo número da loja.
- Acrescenta payment.manual_confirmed v1 às subscrições (proposta, MINOR).
Não expandas escopo: produção dos eventos (EPIC-04, EPIC-05) e catálogo de schemas (KAM-007) são tickets próprios.
Testes: unit, integração (duplicados, DLQ), isolamento, fluxo com janela. PR com o template §7. Commits: feat(KAM-038): …
```

---

## KAM-039 — Prova da regra de dois: teste de contrato e métrica de reaproveitamento

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-031, KAM-035, KAM-038, KAM-046 |
| Bloqueia | KAM-108 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§5.4, §17), `../docs/tecnica/00_Arquitectura_Solucao.md` (§13.2, ADR-012), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1) |

### Contexto

A abstracção «verticais como configuração» só está validada quando duas verticais distintas a usam sem excepções no core (princípio 9, ADR-012). O gate da Fase 0 exige que o evento de confirmação de pagamento seja consumido pela vertical Serviços (lembrete/agenda) sem excepções no core. O `INDICE` e a `../docs/tecnica/02` §19 (v) não nomeiam o efeito de negócio desse consumo; este ticket fixa um contrato verificável e o KAM-108 faz a demonstração real.

### Objectivo

Entregar o teste de contrato automatizado e a medida de reaproveitamento em CI que provam a regra de dois: as quatro condições (a)–(d) de `../docs/tecnica/02` §5.4 e `reuso ≥ 70%` para a vertical Serviços.

### Critérios de Aceitação

- [ ] (a) Um teste de integração arranca Vendedor e Serviços no mesmo AGR/TLS/EVT/TEN e processa uma conversa de cada com **0** *flags* de vertical no `core/`.
- [ ] (b) Um evento de pagamento (`payment.confirmed` v1 e `payment.manual_confirmed` v1) produzido pelo fluxo de uma encomenda do Vendedor é entregue ao handler de Serviços **sem alterar** o bus, o envelope nem o `core/`; o handler regista o consumo idempotente e, se o *payload* referir uma marcação com sinal, confirma-a e agenda o lembrete.
- [ ] (c) A suite cruzada de isolamento (X-02, X-09) passa para as duas verticais com 0 canários de outro tenant ou contacto.
- [ ] (d) `grep` por `vendedor|servicos|assistente` em `core/` (excluindo `registry/` e testes) devolve **0**; o CI falha se devolver > 0.
- [ ] `reuso = 1 − LoC_específico / LoC_total` sobre o caminho de execução de Serviços (grafo + tools + prompts + migrações) é calculado por *script* determinístico, publicado como artefacto JSON do CI, e falha o *build* abaixo de **70%**.
- [ ] As regras de contagem (exclui testes e código gerado; inclui `core/` partilhado no caminho de execução) estão escritas em `docs/reuse-metric.md` e o resultado é reproduzível (2 execuções iguais).
- [ ] Um relatório lista cada ponto de extensão usado pela vertical Serviços (nós comuns, tools, estado, eventos) e qualquer excepção encontrada no core; excepção ≥ 1 reprova o ticket.

### Detalhes Técnicos

- **Componentes:** AGR, REG, TLS, EVT, TEN. Módulos `tests/contract/two_verticals/`, `tools/reuse_metric.py`.
- Efeito de negócio *proposta* do consumo cruzado: o handler de Serviços reage a `payment.confirmed`/`payment.manual_confirmed` com `booking_id` no *payload* (sinal de marcação, `../docs/tecnica/02` §8.2); sem `booking_id` é *no-op* auditado. KAM-108 pode pedir outro efeito (lembrete/agenda): decisão a registar na revisão.
- A medida de reuso aplica-se à vertical **nova** (Serviços) face ao core partilhado; o limiar de 70% é do ADR-012 e vale para cada vertical futura.
- O bloqueio principal é o CI; o relatório humano dá contexto às excepções (por exemplo, `ConversaState.slots` vs `cart`, que são específicos por desenho).
- Eventos de pagamento reais chegam com KAM-055; até lá o teste usa eventos sintéticos conformes ao esquema de KAM-007.

### Testes Requeridos

- Contrato: duas verticais no mesmo processo; consumo cruzado do evento; `grep` de nomes.
- Integração: conversa completa do Vendedor até `payment.manual_confirmed` consumido por Serviços.
- CI: *script* de reuso com repositório de exemplo (casos limite: 69,9% falha, 70,0% passa).
- Isolamento: X-02/X-09 para as duas verticais.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Isolamento de tenant e contacto:** suite cruzada cobre as duas verticais (ADR-015).
- [ ] **Idempotência:** consumo cruzado repetido 5 vezes produz 1 efeito (ADR-009).
- [ ] **Pagamento só por evento autenticado:** o handler consome o evento; nenhum código marca `paga` (ADR-013).
- [ ] **Custo e observabilidade:** a métrica de reuso exportada para OBS e registada por release.
- [ ] Documentação da regra de dois e da medida actualizada; relatório de excepções anexado ao PR.

### Handoff para Claude Code

```text
És o executor do ticket KAM-039 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-039) e docs/tecnica/02_Agent_Runtime_Verticais.md (§5.4, §17).
Objectivo: teste de contrato da regra de dois (condições a–d) e métrica de reaproveitamento em CI (>= 70%).
- Vendedor e Serviços no mesmo AGR/TLS/EVT/TEN sem flags de vertical no core; grep de nomes em core/ = 0.
- Evento de pagamento do fluxo do Vendedor consumido pelo handler de Serviços sem alterar o bus.
- Script de reuso determinístico; regras de contagem documentadas; falha abaixo de 70%.
Não expandas escopo: a demonstração com conversa real é KAM-108; os eventos reais são KAM-055.
Testes: contrato, integração, CI de reuso, isolamento. PR com o template §7. Commits: feat(KAM-039): …
```

---

## KAM-040 — Dataset golden PT-AO sintético e eval harness como gate

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-031, KAM-035, KAM-033, KAM-034 |
| Bloqueia | KAM-064, KAM-110, KAM-125 |
| Responsável sugerido | Engenheiro de Avaliação/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§16, §17), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-018), `specs/01_Engineering_Standards_e_Handoff.md` (§4 Gate 13, §4.1), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§3.5) |

### Contexto

O dataset *golden* PT-AO é o gate dos artefactos comportamentais (grafos, prompts, tools, registo, política, alias de modelo). Como os Termos da Meta proíbem criar, treinar ou melhorar sistemas de ML com dados do WhatsApp (Termos §4.7, leitura automática do texto PT: verificar o texto EN) e a Lei 22/11 limita o uso de conversas reais, o dataset é **sintético** (reescrita) e, só com consentimento e base legal, caso real (L-G1: a confirmar por parecer). Qualidade em português de Angola é NÃO VERIFICADA: é aqui que se mede. 0 falhas em N=200 só limita o risco real a ≈ 1,5% (regra dos três), pelo que o gate duro tem de ser complementado por amostragem em produção.

### Objectivo

Construir o dataset `golden/<vertical>/v1`, o *eval harness* (asserções determinísticas primeiro, juiz LLM só para qualidade de linguagem) e o gate `gates/<vertical>.yaml` ligado ao CI (Gate 13) e ao registo, versionado e reproduzível.

### Critérios de Aceitação

- [ ] `golden/vendedor/v1` e `golden/servicos/v1` têm 100–300 conversas cada, cobrindo as 10 categorias de `../docs/tecnica/02` §16.1, com ≥ 10 casos por categoria; cada caso tem `origem ∈ {sintetico, t2_anonimizado, real_consentido}` e nenhum caso `real_consentido` entra sem registo de consentimento.
- [ ] O conjunto adversarial de citação tem ≥ 200 casos e inclui o de KAM-032; o de injecção inclui ≥ 30 directas e ≥ 10 indirectas (descrição de produto com instruções); o de isolamento inclui «pedidos da outra loja».
- [ ] O *harness* executa o grafo real com o LLM gateway (alias de teste) e reporta, por caso, as asserções determinísticas (números e `sku` citados, injecção, isolamento, duplicados) antes de qualquer juiz LLM.
- [ ] Gate duro: **0** números/`sku` divergentes no adversarial, **0** fugas entre tenants ou contactos, **0** pedidos duplicados, **0** injecções críticas bem-sucedidas, recusa ≥ 95% nos restantes (calibrar); qualquer violação falha o gate.
- [ ] Gate relativo: handoff correcto ≥ 85% (H7); qualidade global ≥ baseline da versão anterior; latência p95 e custo por conversa registados e comparados com o orçamento (monitorizados, não bloqueantes).
- [ ] O gate corre em CI a cada alteração de grafo, prompt, tool, registo, versão do LangGraph e **alias de modelo**; `registry/gates.yaml` (KAM-027) passa de `warn` a `block`.
- [ ] Baselines versionadas em `golden/baselines/<vertical>/<graph_version>.json`; executar 2 vezes o mesmo *commit* com *seed* fixo difere em ≤ margem registada para as métricas não determinísticas.
- [ ] Estimativa de custo por execução completa documentada e verificada (ordem de grandeza: 200 conversas × ~5 turnos × ~0,009 USD ≈ 9 USD com modelo intermédio, a medir) e limite de orçamento por execução no CI.

### Detalhes Técnicos

- **Componentes:** OBS (evals golden em CI), AGR, REG, LLM. Módulos `eval/{harness,assertions,judge,report}.py`, `golden/<vertical>/vN/*.jsonl`, `gates/<vertical>.yaml`.
- Esquema de caso (*proposta*): `{id, vertical, categoria, origem, turnos[], fixtures{catalogo,tenant,contacto}, esperado{asserts[], handoff, fatos}}`.
- Juiz LLM com alias dedicado (nome *proposta* `kamba-judge`, a criar em KAM-030) só para tom/língua; nunca decide números.
- A escolha de modelos por papel **decide-se aqui** (E4 §3.5): comparar 3 candidatos baratos e 1–2 intermédios, sem ranking prévio. Datas de retirada de modelos antigos: NÃO VERIFICADO.
- Cobertura de voz (WER por fornecedor), guardrails (KAM-033) e handoff (KAM-034) entram quando esses tickets estiverem `Done`; o `INDICE` só declara dependência de KAM-031.
- Não treinar nem afinar modelos com estes dados; fornecedor de LLM sem retenção/treino por defeito (a confirmar por fornecedor).

### Testes Requeridos

- Unit: asserções determinísticas (números, `sku`, duplicados, canários).
- Integração: *harness* ponta a ponta com LLM *fake* e com o gateway real num subconjunto.
- Meta-teste: mutação deliberada (preço trocado, `sku` errado, injecção bem-sucedida) faz o gate falhar.
- CI: o gate bloqueia a promoção de uma alteração de alias de modelo com regressão.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] **Eval-gate:** Gate 13 activo e bloqueante; SemVer do dataset (`golden/<vertical>/vN`) ligado ao registo.
- [ ] **Privacidade:** dataset sem telefone, NIF nem dados reais sem consentimento; casos T2 anonimizados (ADR-018).
- [ ] **Números só de tools:** asserções de citação no gate (ADR-007).
- [ ] **Isolamento de tenant:** casos de isolamento com 0 fugas (ADR-015).
- [ ] **Custo e observabilidade:** custo por execução e por conversa registado.
- [ ] Parecer sobre conversas reais (L-G1) registado como pendente; revisão por dois revisores; documentação actualizada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-040 da KAMBÁ.
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-040), docs/tecnica/02_Agent_Runtime_Verticais.md (§16, §17)
e specs/01_Engineering_Standards_e_Handoff.md (§4 Gate 13).
Objectivo: dataset golden PT-AO sintético por vertical, eval harness (asserções determinísticas primeiro, juiz LLM
só para linguagem) e gate gates/<vertical>.yaml ligado ao CI e ao registry.
- 100–300 conversas por vertical; origem sintética; real só com consentimento e base legal (L-G1 pendente).
- Duro: 0 números/sku divergentes, 0 fugas, 0 duplicados, 0 injecções críticas. Relativo: handoff >= 85%.
- Dispara em alteração de grafo, prompt, tool, registo, LangGraph e alias de modelo.
Não expandas escopo: guardrails, handoff e voz têm tickets próprios; avaliação de pesquisa é KAM-064.
Testes: unit das asserções, integração do harness, meta-teste por mutação, CI. PR com o template §7.
Commits: feat(KAM-040): …
```

---

## KAM-114 — Modo concierge: a IA rascunha e o humano aprova

| Campo | Valor |
|---|---|
| Epic | EPIC-03 — Agent Runtime e Verticais |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-018, KAM-031, KAM-034 |
| Bloqueia | KAM-109 |
| Responsável sugerido | Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` (§3A), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.2, §10.3, §11.4), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§8.4, §11, §16), `../docs/tecnica/10_Onboarding_Governanca.md` (§11.2, §11.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4), ADR-002, ADR-007, ADR-018 |

### Contexto

O piloto concierge (`../docs/exploracao/14` §3A; KAM-109) mede H1, H6, H7 e H9 com PMEs reais antes de o bot falar sozinho: a IA rascunha, o humano aprova. Hoje o grafo (KAM-031) responde directamente e o protocolo de KAM-018 só conhece quatro modos (`bot`, `dono`, `humano`, `pausada`). **Decisão deste ticket:** o concierge não é um quinto valor de modo (KAM-018 rejeita transições fora da tabela de `../docs/tecnica/01` §10.2) mas uma política por tenant aplicada à conversa em modo `bot`: o nó de envio é substituído por um pedido de aprovação. O padrão é o de KAM-034: um nó idempotente cria o rascunho e outro só faz `interrupt()`. O rascunho aparece ao operador no HND e só sai pelo Outbound (janela de 24 h, custo, `PreSendGuard`) depois de decisão humana. Os Termos da Meta §4.7 proíbem treinar ou melhorar ML com dados do WhatsApp (leitura automática do texto, NÃO VERIFICADO na íntegra; E1 §4): o dataset golden recebe reescritas sintéticas das decisões, nunca cópias de conversas (ADR-018).

### Objectivo

Implementar o fluxo rascunhar, apresentar e decidir (aprovar, editar, rejeitar), o registo de decisões sem conteúdo e a exportação de candidatos ao golden para reescrita sintética.

### Critérios de Aceitação

- [ ] Com a política `concierge` activa, 1.000 turnos simulados (com falhas injectadas e reentregas) produzem 0 mensagens ao cliente sem decisão `aprovado` ou `editado` registada; sem decisão o rascunho expira às 24 h (`expirado`) e nunca é enviado.
- [ ] `draft_id = sha256(thread_id:turn_seq)`; re-executar o nó de rascunho 5× cria 1 rascunho; dois cliques de aprovação concorrentes (compare-and-set `pendente → decidido`) produzem 1 envio (`key = {draft_id}:send`).
- [ ] O rascunho passa pelo validador de citação (KAM-032) e pelos guardrails de saída antes de ser mostrado; um rascunho com número que não é *fact* é regenerado ou segue para handoff, como no modo normal.
- [ ] O HND mostra o rascunho ao operador em ≤ 5 s (*proposta*) com aprovar, editar e rejeitar (motivo de lista fechada, a definir com o operador do Piloto: tom, preço ou stock errado, fora de âmbito, deveria ir a humano, outro). Uma edição com número fora dos *facts* do turno é sinalizada ao operador e registada como `edicao_numero_livre`; bloquear em vez de sinalizar fica para decisão do Responsável de Produto.
- [ ] *Echo* do dono (modo `dono`) ou handoff com rascunho `pendente` marca-o `substituido`; em 100 intercalações aleatórias, 0 envios do bot depois disso (reutiliza o `PreSendGuard` de KAM-018).
- [ ] Cada decisão grava 1 linha em `draft_decisions` sem texto: `draft_id`, `tenant_id`, `thread_id`, `graph_version`, `decisao` ∈ {`aprovado`, `editado`, `rejeitado`, `expirado`, `substituido`}, motivo, razão de edição (distância normalizada 0–1), latência da decisão e custo da chamada (de `llm_call_log` por `turn_id`).
- [ ] Métricas por tenant e `graph_version`: `draft_approved_ratio`, `draft_edit_ratio_p50`, `draft_decision_latency_s` (p50, p90) e custo por rascunho aprovado; alimentam H6 e H7 de KAM-109 sem recálculo; alerta se um rascunho fica `pendente` > 10 min (*proposta*).
- [ ] O comando `golden-candidates` exporta de `editado` e `rejeitado` só metadados (categoria, intenção, motivo, `graph_version`) para a reescrita sintética de `../docs/tecnica/10` §11.2; um teste de esquema prova 0 campos de texto livre ou de identificador; os casos entram em KAM-040 com `origem=sintetico`.
- [ ] Desactivar a política repõe o envio automático sem reiniciar o AGR; os rascunhos `pendente` passam a `substituido`.

### Detalhes Técnicos

- **Componentes:** AGR (nós `draft_prepare` e `draft_wait`, sem efeitos antes do `interrupt()`), HND (extensão de `HandoffProvider`: `postDraft` e evento de decisão, com o `secret` do *agent bot*), Outbound. A decisão retoma por `POST /internal/draft-decision` com compare-and-set.
- **Dados:** o texto do rascunho vive só no checkpointer (`lg`) e no HND, com a retenção de conversa (`../docs/tecnica/08` §7.1); `draft_decisions` guarda hashes e números. A política `concierge`, `draft_decisions` e `edicao_numero_livre` não constam do dicionário §3: a emenda é condição de merge (gate 3b de KAM-111).
- **Fora de âmbito:** aprovação automática por limiar de risco (Fase 2), interface própria do operador (usa-se o Chatwoot), treino ou *fine-tuning* com as decisões (proibido, ADR-018).

### Testes Requeridos

- Unit: máquina de estados do rascunho e compare-and-set; teste AST (nenhum efeito antes do `interrupt()`).
- Concorrência: 100 intercalações aprovação, *echo* e expiração; duplo clique; reentrega do webhook do HND.
- Integração: 1.000 turnos sem envio não aprovado; esquema da exportação; isolamento de A e B (X-03 sobre `draft_decisions`).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (corrida, números do cliente); testes verdes; cobertura ≥ limiar.
- [ ] **Eval-gate** — altera o grafo: Gate 13 verde com a política desligada e ligada; SemVer do grafo.
- [ ] **Idempotência** e **isolamento de tenant** — chaves por `draft_id`; RLS e teste cruzado.
- [ ] **Números só de tools** — o validador corre antes do rascunho; edições livres sinalizadas e contadas.
- [ ] **Privacidade** — sem conteúdo em `draft_decisions`, métricas, logs ou exportação (ADR-010, ADR-018).
- [ ] **Migrações reversíveis** — `downgrade` testado; documentação actualizada (`docs/concierge.md`).

### Handoff para Claude Code

```text
És o executor do ticket KAM-114 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-03_Agent_Runtime_Verticais.md (bloco KAM-114), docs/tecnica/01 (§10.2, §10.3), docs/tecnica/02 (§11) e o bloco KAM-034.
Objectivo: modo concierge (a IA rascunha, o humano aprova) para o piloto, com registo de decisões e candidatos ao golden.
- Política por tenant sobre o modo bot (não crias um quinto modo): draft_prepare idempotente + draft_wait só com interrupt().
- Nunca envias sem decisão aprovado/editado; expira às 24 h; echo do dono ou handoff substitui o rascunho.
- draft_decisions sem texto; métricas de aprovação, edição, latência e custo; exportação só com metadados para reescrita sintética.
- Nada de treino com conversas (ADR-018). Valida números antes de mostrar o rascunho.
Não expandas escopo: sem aprovação automática, sem UI própria. Testes: estados, concorrência, 1.000 turnos, esquema. PR com o template do §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| # | Risco / item | Estado | Ligação | Tratamento no epic |
|---|---|---|---|---|
| R1 | Qualidade (WER) dos STT em português de Angola; detecção de língua para Kimbundu/Umbundu | NÃO VERIFICADO (L1) | KAM-036, KAM-107 | Limiares configuráveis; baixa confiança → humano; decisão com áudio real |
| R2 | Qualidade dos modelos em PT-AO e latência p50/p95 reais; datas de retirada de modelos | NÃO VERIFICADO (L2, L3) | KAM-030, KAM-040 | Escolha por golden; latência medida no staging, não assumida |
| R3 | Chamadas a LLM/STT no estrangeiro são transferências; pseudonimização como remédio | A confirmar por parecer (L8) | D1, D9; KAM-030, KAM-036, KAM-069 | Gate de destino default-deny em produção; só dados sintéticos em staging; voz com `voice_enabled=false` |
| R4 | Classificação como «AI Provider» pela Meta; requisitos do âmbito comercial | NÃO VERIFICADO (L10) | D2; KAM-033 | Guardrail de domínio e prova de âmbito em métricas agregadas; perguntas escritas (KAM-101) |
| R5 | Termos Meta §4.7 (treino/melhoria de ML) e uso de conversas reais em avaliação | NÃO VERIFICADO (L9, L-G1) | D9; KAM-040, KAM-104 | Golden sintético; real só com consentimento e parecer |
| R6 | Persistência da agenda do vertical Serviços (`../docs/tecnica/03` não a especifica) | Decisão aberta (L11) | D3; KAM-035, KAM-047 | Contrato via módulo `servicos`; ratificar o DDL em `../docs/tecnica/03` |
| R7 | Comportamento do COM (Medusa) sob testes de isolamento; adaptador com `merchant_id` | Condicionado ao spike (L12) | D3; KAM-028, KAM-041 | TLS usa a porta `CommerceRegistry` com *fakes* até ao adaptador real |
| R8 | Facilitador e semântica de `createCharge` por PME | Decisão aberta (L13) | D4; KAM-031, KAM-046 | `criar_pedido` depende de PAY por interface; `ManualProvider` com limites |
| R9 | Garantias de entrega do BullMQ; consumidor Python | NÃO VERIFICADO (L6) | D12 (licença do Redis); KAM-025, KAM-038 | Handlers idempotentes, DLQ, alternativa de *shim* TS registada em ADR local |
| R10 | Nomes e semântica exactos na versão fixada: telemetria do LangGraph, modo de durabilidade, API de remoção de *thread*, parâmetros do LiteLLM | A confirmar na integração (L5) | KAM-025, KAM-026, KAM-030 | Confirmar e registar na PR; testes falham se o nome divergir |
| R11 | Alojamento do Postgres/checkpoints, Chatwoot e proxy LLM | Decisão aberta (L14) | D1, D6; KAM-026 | Retenção e minimização desde já; residência decidida em KAM-105 |
| R12 | Lei de IA em projecto; obrigações de transparência | INDÍCIO (L15) | KAM-033 | 1.ª mensagem identifica o assistente automático |
| R13 | Ataque a dependência (LiteLLM, PyPI) e licença LangGraph Server por engano | CONFIRMADO (E4) | KAM-025, KAM-030, KAM-067 | Digest + cosign, versão ≥ 1.83.0, lista de bloqueio, egress |
| R14 | Dependências em falta no `INDICE` (por exemplo, KAM-031 → KAM-032; KAM-033/034/040 → KAM-031) | Observação de backlog | `specs/INDICE.md` §4 | Declaradas nos Detalhes Técnicos e comunicadas ao dono do backlog; não corrigidas aqui |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: 16 tickets (KAM-025 a KAM-040) do Agent Runtime e Verticais; KAM-114 (modo concierge) acrescentado na consolidação. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-145: os **26** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | **KAM-160** entra no `Dependências` do KAM-037, nas três superfícies, por reciprocidade: o `01` §14 manda registar um `pending_reply` que não existe em superfície nenhuma, e o KAM-037 é quem implementa a degradação. O `02` §14 deste epic é a prova de que não falta coluna — fecha com a mesma regra de recuperação («Ao recuperar, não se reenviam respostas antigas fora da janela») sem nome novo, e o critério 1 do KAM-037 já mede «0 turnos sem resposta em 100 execuções». Nada do bloco do KAM-037 muda além dessa linha. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | **KAM-025 entregue.** O bloco ganha a secção «Verificação dos Critérios de Aceitação», com a prova nomeada de cada um e a razão de cada caixa vazia. **Quatro critérios marcados** (1, 2, 3 e 8) e **quatro parciais** (4, 5, 6 e 7), e os quatro parciais não ficam vagos: o que falta em cada um pertence ao BullMQ (a retoma de um *job* `stalled`, NÃO VERIFICADO em `../docs/tecnica/evidencia/E4` §2.10), ao KAM-084 (o p95 sob carga), ao KAM-019 (a entrega ao HND, que aqui é uma porta) e ao KAM-076 (o bloqueio de rede). No DoD ficam vazias a primeira (por causa dos quatro parciais), a de observabilidade — o `degraded_turns` conta turnos em modo determinístico, que é o KAM-037, e uma métrica sempre a zero afirma o que ninguém mediu — e a dos dois revisores, que continua vazia em toda esta linha. **Três tensões do próprio bloco ficaram escritas em vez de resolvidas em silêncio:** os critérios 2, 3 e 5 não podem valer ao mesmo tempo com as omissões que propõem (vinte mensagens concorrentes distam muito menos de 1,5 s, e o tecto de 3 recusaria dezessete), e a leitura adoptada — que o critério 3 autoriza ao dizer «configurável» — é desligar os tectos a `0` para medir a propriedade da tranca. Está na linha 93 de `../docs/dividas-documentais.md`. **Sem migração:** a cadeia fica na `0019`. As duas decisões que o bloco manda registar estão em `../docs/adr/ADR-L004-fila-e-tranca-do-agr.md`; os nomes novos no dicionário §3.24 (emenda 1.33), que resolve também a lacuna do `turn_id` que o §3.13 tinha deixado por escrito. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | **KAM-026 entregue.** O bloco ganha a secção «Verificação dos Critérios de Aceitação». **Quatro critérios marcados** (1, 2, 3 e 4) e **quatro por marcar** (5, 6, 7 e 8), e nenhum fica vago: o 5 e o 7 encostam a grafos que não existem — «nós `write`/`money`» não está modelado em lado nenhum e o `ingest` que migra o `schema_version` é do **KAM-031** —, ao 6 falta «`facts` apenas do turno» (mesmo credor) e o teste de binários e segredos, e ao 8 falta a poda «últimos N», que **não se implementa de propósito**: o `prune` do próprio `BaseCheckpointSaver` avisa que um `keep_latest` ingénuo corta a cadeia de um canal `DeltaChannel` e que o valor «would silently reconstruct as empty (no error raised)». **A decisão que deu a forma ao ticket:** o `langgraph-checkpoint-postgres` que o `../docs/tecnica/02` §12 nomeia é MIT mas exige `psycopg` e `psycopg-pool`, LGPL-3.0-only, que o `ci/licenses.yaml` nega — o checkpointer é nosso, sobre `pg8000`, contra a interface e o serializador do `langgraph-checkpoint`, cujo fecho de 35 pacotes foi classificado pelo avaliador do próprio *gate* 11 com **35 permitidas, 0 fora**. Por isso a linha das dependências do DoD fica vazia como **divergência**: ela nomeia o pacote que não pode entrar. **O critério 2 tinha uma armadilha**, e está fechada: em `msgpack` uma busca por texto devolve 0 com um telefone lá dentro, pelo que o varrimento desserializa e há dois ensaios que semeiam um número e um campo de BSUID e exigem que ele os encontre. Revisão `0020`: esquema `lg`, duas tabelas e o papel `kamba_agr`, sem `USAGE` no `platform`. Dicionário §3.25 (emenda 1.34); dívida **95**, medida ao escrever o ensaio do critério 4. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | **KAM-028 entregue.** O bloco ganha a secção «Verificação dos Critérios de Aceitação». **Sete critérios marcados** (1 a 7) e **um parcial** (8), e o parcial não fica vago: ao 8 falta «nunca é repetido», que o §6.5 põe no grafo (**KAM-031**). **O 7 era parcial e passou a satisfeito pela revisão adversarial**, que mediu que nenhum tecto era imposto pela camada — nem o de `read`: um executor de 5 s contra 2 s devolvia `ok=True` em 5,01 s. Cinco caixas do DoD marcadas; a dos **dois revisores** fica vazia, como em toda esta linha, e a de «todos os critérios satisfeitos» também, porque dois são parciais. **A validação (1) do §5.2 fechou:** as duas linhas `tools: { modo: aviso }` saíram do `registry/gates.yaml` e a validação corre em `bloqueio` — o mecanismo é apagar a linha, e há teste a provar que ela morde. **A linha de versão do KAM-027 nunca foi escrita** e fica registada em `../docs/dividas-documentais.md`: esta é a 1.5 e não a 1.6. **A revisão adversarial (`../docs/analises/ANALISE-30-KAM-028-toollayer.md`) reprovou com 9 *must fix*, e os nove estão corrigidos com teste**: entre eles, três dos oito ficheiros da camada não se importavam sozinhos (ciclo pelo `metricas.py`), uma tomada só serializava todos os *tenants* (2,02 s para dez invocações de dez *tenants*), o *lint* do critério 3 não via uma subclasse indirecta de `BaseModel`, os **nomes** dos argumentos iam em claro para a `tool_audit`, e o X-02 media onze recusas em vez de onze tools. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | **KAM-029 entregue.** O bloco ganha a secção «Verificação dos Critérios de Aceitação». **Cinco critérios marcados** (2 a 6) e **três parciais** (1, 7 e 8), e nenhum fica vago. O **1** passou a parcial **pela revisão adversarial** (`../docs/analises/ANALISE-31-KAM-029-idempotencia.md`) e não pela medição do autor: ele e o critério 5 não podem valer ao mesmo tempo com um backend mais lento do que o tecto de espera — com 4 s, dentro do tecto de 8 s da classe, quem espera desiste aos 3 s (que é o que o 5 manda), o cliente lê falha de infra-estrutura, pede carrinho novo, e o `cart_id` novo dá chave nova: **duas encomendas**, e a segunda barreira do COM também não apanha. Não se resolve aqui porque as duas correcções possíveis contradizem um critério escrito; dívida **112**, e a carga é do **KAM-084**. Ao **7** falta a desigualdade — a validade da reserva está fixada em 72 h (`../docs/tecnica/03` §6.4) mas o **prazo de disputa não está em documento nenhum** —, e ao **8** falta o `stage`, que o `ToolContext` não tem: quem o lê é o `confirm_gate` do **KAM-031**, e é a segunda metade da fronteira que o KAM-028 abriu ao fechar o seu critério 8 como parcial. Quatro caixas do DoD marcadas; a de «todos os critérios» fica vazia pelos três parciais, e a dos **dois revisores** como em toda esta linha. **A decisão que deu forma ao ticket: são duas chaves e não uma.** A `tool_audit.idempotency_key` é do **turno** (vai ao `usage_ledger` no passo 2; o KAM-025 usa `turn_id:seq`) e a do §6.3 é do **carrinho**, e não podiam ser a mesma — um segundo toque com `wamid` novo é um turno novo, logo chave de turno nova, logo nada guardado a encontrar, e cobrava outra vez (critério 8). Dicionário §3.28 (emenda **1.37**), que corrige isso e «os dez erros tipados» para onze. **A revisão adversarial reprovou com 4 *must fix*, e os quatro estão tratados:** a retoma de uma reserva `em_curso` abandonada (sem ela, uma ligação caída entre o backend e o registo envenenava aquele `cart_id` para sempre, **com a encomenda já feita**), o `created_at` que não entrava em decisão nenhuma (o critério 5 estava satisfeito pela razão errada — apagar a semente e o teste passava igual), o `args_hash` que era dos argumentos **crus** e não do modelo validado (um campo de omissão reemitido virava o *replay* em recusa), e a tensão do critério 1, devolvida. **E dois defeitos que o autor apanhou antes dela**, os dois no caminho de excepção: o fecho da reserva corria **depois** de a tomada cair, e depois mascarava a excepção original. **O *gate* 3b:** o `canon_lint` não deixava crescer **nenhum** domínio fechado deste repositório, e a dispensa é **nomeada** em `ci/canon-lint.yaml` — a primeira versão inferia-a da ordem dos ficheiros e a revisão demonstrou-lhe três buracos. Razão em `../docs/ci.md` (linha **1.56**). Revisão `0022`; dívidas **108** a **112**. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | **KAM-030 entregue.** O bloco ganha a secção «Verificação dos Critérios de Aceitação». **Dois critérios marcados** (3 e 5) e **seis parciais** (1, 2, 4, 6, 7 e 8), e nenhum fica vago: em quatro deles o credor é um ticket que **não existe** — KAM-076 (o bloqueio de rede que o critério 2 manda testar), KAM-037 (a degradação a que o critério 4 manda chegar), KAM-040 (o Gate 13 do critério 7, e a escolha dos modelos) e KAM-069 (a `tenant_destinations` do critério 8). **A revisão adversarial reprovou com 7 *must fix*, e os sete estão corrigidos com teste** (`../docs/analises/ANALISE-32-KAM-030-gateway-de-llm.md`): três deles eram **mecanismos que não podiam falhar** nas condições em que este bloco os declarou satisfeitos — o `escrever` reescrevia o *lock* e por isso o *bump* SemVer do critério 7 não era um *gate*; o cliente guardava **uma** ligação e, com turnos concorrentes, a segunda chamada transferia dados e **não gravava linha** (o `tenant_guard.tx` é exclusivo por ligação, e o duplo sequencial da bateria não o via); e a chave do cosign tinha sido extraída do **próprio *bundle*** que ela verifica, o que torna o `cosign verify --key` tautológico. Os outros quatro: a saída para `raw.githubusercontent.com` continuava aberta com um comentário a dizer que não, um preço expirado levantava no único ponto do caminho de sucesso que não pode levantar (e a chamada repetia-se, com segunda transferência), dois fornecedores iguais atrás de um alias gravavam **vinte vezes** o custo real, e a *suite* do `supply_chain` ficou vermelha com a linha de base do canário vermelha — o que desligava a prova por mutação daquele módulo. **O critério 6 foi desmarcado pela revisão**: as 20 corridas que o provaram usaram `Router(...)` em Python, sem chave virtual, e a `models` da chave não autorizava o grupo de *fallback*. **E a correcção da chave descobriu mais do que o achado**: o projecto publica a chave e ela **difere** da do *bundle* — dívida **117**, que é medição e não código. **A decisão que o ticket teve de tomar, e está escrita:** o DoR nomeia o KAM-069 e ele **não está entregue** — medido antes de se escrever código, zero caixas e nenhum ficheiro de inventário ou de *gate*. Entrega-se com o destino a falhar **fechado** e o KAM-069 como credor, que é o padrão desta linha (o KAM-028 deixou o passo 5 para o KAM-029, o KAM-029 deixou o `stage` para o KAM-031) e é o que o **próprio critério 8** manda ao escrever «até KAM-069 existir, só dados sintéticos em `staging`»; em `prod` não passa fornecedor nenhum, o que é mais restritivo do que o KAM-069 será. Duas caixas do DoD marcadas (segredos e eval-gate); a de «todos os critérios» fica vazia pelos cinco parciais, a de privacidade e a de custo ficam vazias e **parciais** (não há `apd_ref` para registar, e o `custo_usd` é nulo enquanto o modelo for `por_decidir`), a das dependências espera o `cosign verify`, e a dos **dois revisores** fica vazia como em toda esta linha. **Três afirmações de fonte mais alta não sobreviveram a serem medidas contra a imagem fixada, e as três mudaram código** (`../docs/evidencia/KAM-030-litellm.md`): o orçamento esgotado responde **422** com `type: budget_exceeded` e não o **400** que o critério 4 escreve — e o proxy usa o 400 para «alias repetido», pelo que o mapeamento do bloco nunca disparava no orçamento e disparava num erro de provisionamento; a configuração do `../docs/tecnica/02` §13.1 **à letra não cumpre o critério 6**, porque a estratégia por omissão é `simple-shuffle` e em 20 corridas com o primário sempre em falha **3 falharam por completo**; e `google/` é recusado pelo proxy, cujo prefixo para o Gemini é `gemini/`. **E uma quarta, sobre código já fundido:** o `tools/supply_chain/cosign.py` montava sempre o comando *keyless*, com a nota dele a dizer que a forma era «lida de memória: NÃO VERIFICADO» e que quem ligasse a primeira imagem a confirmaria — o LiteLLM assina **com uma chave** e a assinatura não tem certificado, pelo que `--certificate-identity` não tinha valor possível. **Fechou-se também a única das quatro cláusulas do critério 1 sem máquina a impô-la:** o leitor de Dockerfiles só lia `FROM` e `ARG`, e um `RUN pip install litellm==1.82.7` passava limpo. Revisão `0023`: o esquema **`dat`** (o terceiro do repositório), a `dat.llm_call_log` com dezesseis colunas — catorze no `../docs/tecnica/06` §14, mais o `papel` e o `graph_version`, sem os quais o «custo por papel» do DoD não é calculável —, partição `DEFAULT`, *append-only* e RLS no pai **e** na partição. Dicionário §3.29 (emenda **1.38**); `../docs/ci.md` linhas **1.57** e **1.58**; `../docs/agr.md` linha **1.6**; dívidas **113** a **121**; **22** mutações com prefixo `llm:`, e a primeira corrida delas deu **dez sobreviventes** por os módulos que as matam não estarem numa lista literal do corredor — a *suite* passava e não media. | Equipa KAMBÁ |

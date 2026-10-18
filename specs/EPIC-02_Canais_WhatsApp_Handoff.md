# EPIC-02 — Canais WhatsApp e Handoff

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Canais WhatsApp e Handoff |
| Versão | 1.0 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/10_Onboarding_Governanca.md` (§6–§7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` |
| Documentos relacionados | `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-01_Fundacoes_Dados.md`, `specs/EPIC-03_Agent_Runtime_Verticais.md`, `specs/EPIC-09_Onboarding_Governanca.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` |

---

## 1. Visão do Epic

Este epic constrói o **canal**: tudo o que está entre a Meta e o Agent Runtime, em ambos os sentidos. Entrada: o GWY como único endpoint de webhook (assinatura sobre o corpo bruto, deduplicação, 200 rápido, fila) e o CHR que transforma `phone_number_id` em tenant, canal e contacto. Saída: o *outbound* que respeita a janela de 24 h, os templates *utility*, o limite de débito e o custo por mensagem. Onboarding do número: Embedded Signup v4 como Tech Provider, coexistência com a app WhatsApp Business do dono (histórico, *echoes*, `PARTNER_REMOVED`, sincronização em 24 h) e o protocolo que decide **quem tem a palavra** em cada conversa (bot, dono, humano, pausada). Depois, o HND com Chatwoot (1 conta por PME, espelho por *inbox* de tipo API), a mídia, a vigilância da qualidade e do *free tier*, o consentimento no 1.º contacto e o simulador de webhooks que torna tudo isto testável sem a Meta.

O epic concretiza **ADR-001** (Cloud API oficial, Tech Provider, Embedded Signup v4, GWY único endpoint, Chatwoot como espelho), **ADR-010** (consentimento no 1.º contacto, BSUID, telefone nunca como chave), **ADR-011** (só o Fluxo A em produção: o CHR recusa `origem='plataforma'` e `vertical='assistente'`), **ADR-002** (Chatwoot MIT; Typebot e n8n fora das superfícies de tenants), **ADR-014** (mídia por `StorageProvider`) e **ADR-009** (eventos de canal pelo outbox). Aplica a política da Meta lida em E1 (Messaging Policy: caminho de escalonamento a humano em todas as conversas; opt-out; sem personificação) e trata como incógnitas medidas, não assumidas, a coexistência para números +244 (H3), o *echo* de mensagens enviadas por API e o comportamento do bot do Chatwoot.

Fase mista, por desenho: **Fase 0** para o que o esqueleto andante exige (KAM-013, 014, 015, 019, 024: uma mensagem entra, é resolvida, responde-se na janela, o handoff existe) e **Fase 1** para o que depende de Tech Provider, de números reais ou de decisões externas (KAM-016, 017, 018, 020–023). Os tickets de Fase 1 dependem de `ext:KAM-102` (Business Verification, App Review, Tech Provider) e `ext:KAM-100` (spike de coexistência), que arrancam na semana 1.

---

## 2. Critérios de Saída do Epic

- [ ] Reenviar o mesmo webhook 2× produz 1 *job*; a mesma mensagem em dois envelopes distintos produz 1 `inbound_events`; assinatura inválida devolve 401; o GWY responde 200 com p99 < 500 ms a 3× de tráfego de estados (alvo de `../docs/tecnica/01` §16).
- [ ] 0 mensagens enviadas com janela fechada (`WINDOW_CLOSED`) e 0 respostas do bot depois de um *echo* do dono em 100 intercalações aleatórias de corrida (KAM-015, KAM-018).
- [ ] Um onboarding Embedded Signup v4 completo numa conta de teste da Meta, com evidência em `docs/evidencia/KAM-016.md`; a coexistência está validada com ≥ 1 número +244 real **ou** o modo `cloud_only` está documentado como predefinido, conforme o relatório de KAM-100 (KAM-016, KAM-017).
- [ ] A sincronização de coexistência alerta aos 12 h e marca `falhado` às 24 h; `history` nunca gera resposta do bot (KAM-017).
- [ ] O Chatwoot não tem credenciais Meta; o agente da conta A não lê conversas da conta B; `openHandoff` repetido com o mesmo `handoffId` cria 1 conversa (KAM-019).
- [ ] 0 invocações do AGR sem `consent_event` válido; «PARAR» pausa a conversa e regista a revogação (KAM-022).
- [ ] Qualidade RED passa o canal a `restrito` sem suspender; o contador de *free tier* alerta aos 800 e aos 1.000 (KAM-021, KAM-023).
- [ ] O simulador cobre 100% dos tipos de entrada de `../docs/tecnica/01` §5.4 e dos campos de webhook de §4.4; o contrato *online* corre uma vez no número de teste de *staging* (KAM-024).
- [ ] Os itens NÃO VERIFICADOS L1, L2, L6, L7, L10 têm medição ou nota de evidência anexada ao ticket respectivo.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-013 | GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila) | feature | L | P0 | KAM-001, KAM-005, KAM-010 |
| KAM-014 | CHR: ChannelResolver por `phone_number_id` com BSUID | feature | M | P0 | KAM-003, KAM-008, KAM-013, KAM-004, KAM-006 |
| KAM-015 | Outbound: envio, janela de 24 h, templates utility e custo de mensagens | feature | L | P0 | KAM-013, KAM-014, KAM-004 |
| KAM-016 | Embedded Signup v4 e Tech Provider (troca de code, subscrições de webhooks) | feature | L | P0 | KAM-013, KAM-003, ext:KAM-102, KAM-010 |
| KAM-017 | Coexistência: history, state sync, echoes, `PARTNER_REMOVED`, sincronização de 24 h | feature | L | P0 | KAM-016, ext:KAM-100 |
| KAM-018 | Protocolo bot ↔ dono ↔ humano: modos da conversa e silenciamento por echo | feature | M | P0 | KAM-014, KAM-017 |
| KAM-019 | HND: HandoffProvider e Chatwoot (Agent Bot API, espelho por inbox de tipo API) | feature | L | P0 | KAM-014 |
| KAM-020 | Mídia: download autenticado, armazenamento e URL interna assinada | feature | M | P0 | KAM-013, KAM-011 |
| KAM-021 | Quality rating, estado `restrito` e monitorização de limites | feature | M | P0 | KAM-013, KAM-009 |
| KAM-022 | Consentimento no 1.º contacto (aviso versionado, botões, `consent_event`) | feature | M | P0 | KAM-008, KAM-014, KAM-015, KAM-159 |
| KAM-023 | Monitorização do free tier de service messages e do método de pagamento da PME | feature | S | P0 | KAM-015 |
| KAM-024 | Simulador de webhooks Meta e testes de contrato com número de teste | chore | M | P0 | KAM-013 |
| KAM-115 | Aviso ao dono por canal alternativo (e-mail ou push) | feature | S | P1 | KAM-017, KAM-021, KAM-023, KAM-116 |

---

## KAM-013 — GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-001, KAM-005, KAM-010 |
| Bloqueia | KAM-014, KAM-015, KAM-016, KAM-020, KAM-021, KAM-024, KAM-056, KAM-072, KAM-084 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§5), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.5), ADR-001, ADR-009, ADR-010 |

### Contexto

O GWY é o **único** endpoint de webhook da Meta (ADR-001); o Chatwoot recebe apenas um espelho. Factos CONFIRMADOS (E1 §5): HTTPS com certificado válido; verificação por `GET` com `hub.mode`, `hub.challenge`, `hub.verify_token`; `POST` com `X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo bruto com o App Secret>`; re-entrega até 7 dias com *backoff* exponencial, sem ordem garantida e concorrente; capacidade para 3× o tráfego de estados + 1× o de entrada. O *timeout* exacto do webhook é NÃO VERIFICADO (L2): o alvo interno é 200 em < 500 ms. As garantias do BullMQ também não foram verificadas, logo todos os consumidores são idempotentes.

### Objectivo

Implementar o serviço `gwy` (Hono 4.13.x, ≥ 2 réplicas sem estado) que valida, deduplica, enfileira e responde 200 sem I/O pesado, e o *worker* que explode o payload em eventos de canal e os regista sem duplicados.

### Critérios de Aceitação

- [ ] `GET /wa/webhook` com `hub.verify_token` correcto responde 200 com o corpo igual a `hub.challenge`; com `verify_token` errado responde 403 (código em proposta).
- [ ] `POST` com assinatura ausente ou inválida devolve 401 e incrementa `gwy_sig_fail`; a assinatura é calculada sobre os bytes recebidos antes de `JSON.parse` (um corpo re-serializado com espaços diferentes e a mesma assinatura é rejeitado).
- [ ] Aceita assinatura feita com o App Secret actual **ou** o anterior (*ring* `[actual, anterior]`); com um terceiro segredo devolve 401. Comparação em tempo constante (`timingSafeEqual`).
- [ ] Reenviar o mesmo corpo 2× produz 1 *job* (`jobId = sha256(corpo)`); a mesma mensagem (`wamid`) em dois corpos distintos produz 1 linha em `inbound_events` (`UNIQUE (kind, event_key)`); `event_key` de estados é `wamid:estado`.
- [ ] O 200 só é devolvido depois de o *job* estar enfileirado; com Redis indisponível o GWY responde 503 (a Meta repete) e nunca 200.
- [ ] JSON inválido com assinatura válida: 200 e quarentena em `unrouted_events` (payload com retenção de 7 dias, proposta) + alerta; nunca 5xx (evita *retry storm*).
- [ ] Carga de 200 pedidos/s durante 60 s com 3 estados por mensagem (proposta de perfil): p99 < 500 ms, mediana ≤ 250 ms, < 1% acima de 1 s; sob saturação (fila > 10.000 *jobs*, proposta) são descartados estados não facturáveis, nunca `messages`.
- [ ] Encaminhamento por `kind`: `message`/`echo` → CHR; `statuses` → *stage* de *outbound* (nunca ao AGR); `history`/`smb_app_state_sync` → só ingestão (KAM-017); `account_update`/qualidade/templates → *stage* de gestão de canal.
- [ ] Logs JSON só com `ts, level, svc, msg_id, wa_type, latency_ms, outcome, error_code`; um linter e um teste sobre os logs de 1 000 pedidos encontram 0 telefones e 0 texto de mensagem.

### Detalhes Técnicos

- **Componentes:** GWY (e *worker* de canal em `services/worker-canal`). O TLS público termina no proxy (KAM-077); o GWY escuta em HTTP atrás dele.
- **Pipeline (de `../docs/tecnica/01` §5.2):**
```ts
app.post('/wa/webhook', async (c) => {
  const raw = await c.req.arrayBuffer();
  if (!verifyAny(raw, c.req.header('x-hub-signature-256') ?? '', secrets.ring('META_APP_SECRET'))) return c.text('invalid signature', 401);
  await inboundQueue.add('wa', { raw: b64(raw), recvAt: Date.now() }, { jobId: sha256Hex(raw), removeOnComplete: 10000 });
  return c.text('ok', 200);
});
```
- **Tabelas:** `inbound_events(id, kind, event_key, waba_id, phone_number_id, recebido_at, processado_at, UNIQUE (kind, event_key))` sem `tenant_id` (o tenant só nasce no CHR); `unrouted_events` idem. O payload de conversa não é persistido aqui, só no *job* e, depois, nos *checkpoints* do AGR. Estados monotónicos (`sent < delivered < read`; `failed` terminal) aplicam-se em KAM-015.
- **Segredos:** App Secret e `verify_token` via `SecretProvider` (implementação de ambiente até KAM-010). Ordenação por conversa e janela de coalescência de 1,5 s (a calibrar) são do AGR/KAM-025; aqui só se preserva o `timestamp` da Meta.

### Testes Requeridos

- Unit: verificação de assinatura (válida, inválida, *ring*, corpo re-serializado); geração de `event_key`.
- Integração (Postgres e Redis reais): duplicado byte-a-byte, duplicado semântico, Redis parado, JSON inválido.
- Carga: perfil acima com medição de latência e de *shedding*. Contrato: fixtures do simulador (KAM-024).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/gwy.md`); Conventional Commits; sem TODOs órfãos.
- [ ] **Idempotência** — dedup em dois níveis com teste de repetição.
- [ ] **Privacidade** — logs sem conteúdo nem telefone; payload de conversa fora de `inbound_events`.
- [ ] **Sem segredos** — App Secret só via `SecretProvider`; scan limpo.
- [ ] **Custo e observabilidade** — `gwy_requests_total`, `gwy_sig_fail`, `gwy_enqueue_ms`, `inbound_queue_depth` desde o código.
- [ ] **Migrações reversíveis** — `downgrade` das tabelas de entrada testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-013 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-013), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§5) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§5). Objectivo: GWY como único endpoint de webhook da Meta.
- Hono 4.13.x (não o 5.0.0-rc.0); GET de verificação; POST com HMAC-SHA256 sobre o corpo bruto, ring [actual,
  anterior], timingSafeEqual; 401 se falhar; jobId = sha256(corpo); 200 só após enfileirar; 503 se Redis cair.
- Worker: explode entry/changes/messages/statuses; inbound_events com UNIQUE (kind,event_key); quarentena
  para JSON inválido; roteamento por kind (history só ingestão; statuses nunca ao AGR).
- Logs JSON com allowlist de campos; zero telefones e zero conteúdo.
Não expandas escopo: resolução de tenant é KAM-014, envio é KAM-015, subscrição de campos é KAM-016.
Testes: assinatura, duplicados, Redis parado, carga, linter de logs. Abre PR com o template do §7.
```

---

## KAM-014 — CHR: ChannelResolver por `phone_number_id` com BSUID

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-003, KAM-008, KAM-013, KAM-004, KAM-006 |
| Bloqueia | KAM-015, KAM-018, KAM-019, KAM-022, KAM-025, KAM-054, KAM-118 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.3, §7, §10.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.1), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5), ADR-010, ADR-011, ADR-012, ADR-015 |

### Contexto

O CHR é o único sítio onde o `tenant_id` nasce para o estado do grafo; a ToolLayer só aceita o que vier do estado (`../docs/tecnica/01` §7.2). Corre antes de qualquer acesso ao runtime, aplica o estado do tenant e do canal, resolve o contacto por BSUID ou telefone (KAM-008) e determina o **modo da conversa**. Aplica também as guardas do Fluxo B (ADR-011): em produção do Piloto recusa canais com `origem='plataforma'` ou `vertical='assistente'`. Antes de existir contexto, a resolução usa o papel estreito `kamba_resolver` (KAM-004); o backlog mestre não declara essa dependência nem a de KAM-006 para a invalidação por evento (ver riscos).

### Objectivo

Implementar o CHR: `resolve(phone_number_id) → ChannelContext`, a tabela de estados que decide o que fazer com cada entrada, a criação da conversa e a entrega ao AGR (ou ao dono/humano) de um *job* sem telefone nem conteúdo desnecessário.

### Critérios de Aceitação

- [ ] `resolve` devolve `{tenant_id, channel_id, vertical, plano, estado_tenant, estado_canal, channel_mode, origem}` com cache de 60 s, invalidada por `channel.updated` em ≤ 1 s quando o consumidor existir; até lá vale o TTL.
- [ ] `phone_number_id` desconhecido: 0 *jobs* para o AGR, 1 linha em `unrouted_events`, alerta; a resposta ao GWY já foi 200.
- [ ] Matriz de estados (de `../docs/tecnica/01` §7.2), testada por linha: `onboarding`/`pendente` regista e não responde; `ativo` normal; `restrito` só responde dentro da janela e sem *marketing*; `desligado` nada; `suspenso` regista e responde 1 vez por contacto/24 h com mensagem estática; `encerrado` regista e descarta.
- [ ] Mensagem com apenas `wa_id` e mensagem com apenas BSUID do mesmo cliente convergem no mesmo `contact_id`; a fusão emite `contact.merged` exactamente 1 vez em 10 repetições.
- [ ] Com `KAMBA_FASE=piloto` um canal `origem='plataforma'` ou `vertical='assistente'` é recusado (0 *jobs*, alerta) e o arranque falha se existir tal linha em produção.
- [ ] O *job* entregue ao AGR cumpre `packages/contracts/agent_invocation.schema.json` (`tenant_id`, `contact_id`, `conversation_id`, `channel_id`, `wamid`, `type`, `modo`) e não contém telefone, BSUID nem `display_name`; `thread_id = tenant_id:contact_id`.
- [ ] Mensagens com `conversations.mode` ≠ `bot` não vão ao AGR; vão ao dono/HND (KAM-018/019).
- [ ] Isolamento: o `phone_number_id` de A nunca devolve contexto de B; o papel `kamba_resolver` não lê outras tabelas; `resolve` em cache p95 ≤ 5 ms e sem cache ≤ 50 ms (proposta).

### Detalhes Técnicos

- **Componentes:** CHR (em `services/worker-canal`), com `identity` de KAM-008 e `tenantGate` de KAM-009.
- **Tabela criada aqui (o backlog não a atribui a nenhum ticket):**
```sql
CREATE TABLE platform.conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES platform.tenants(id),
  contact_id uuid NOT NULL REFERENCES platform.contacts(id), channel_id uuid NOT NULL REFERENCES platform.tenant_channels(id),
  mode text NOT NULL DEFAULT 'bot' CHECK (mode IN ('bot','dono','humano','pausada')),
  last_inbound_at timestamptz, window_expires_at timestamptz, last_human_activity_at timestamptz,
  UNIQUE (tenant_id, contact_id, channel_id));
```
  RLS via `enable_tenant_rls`. A janela vive aqui (não em `contacts`, divergindo de `../docs/tecnica/01` §6.2, pois `contacts` segue ADR-010/KAM-008). A migração regista o gancho `onContactMerge` para repontar conversas.
- **Resolução de contacto:** algoritmo de `../docs/tecnica/01` §6.3 (BSUID → telefone com `kid` actual e anterior → criar/fundir). O telefone em claro nunca sai do ponto de envio.
- **Fora de âmbito:** transições de modo (KAM-018), consentimento (KAM-022), envio (KAM-015).

### Testes Requeridos

- Unit: matriz de estados (6 × entradas); montagem do contrato do *job*.
- Integração: canal desconhecido, fusão, cache e invalidação, Fluxo B recusado.
- Isolamento: `phone_number_id` cruzado; `kamba_resolver` sem acesso a `orders`; teste X-03 sobre `conversations`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (isolamento de tenant, dados pessoais); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada; Conventional Commits.
- [ ] **Isolamento de tenant** — `tenant_id` só nasce aqui; RLS em `conversations`; teste cruzado do novo caminho.
- [ ] **Idempotência** — repetição do mesmo `wamid` não cria 2 conversas nem 2 *jobs*; teste incluído.
- [ ] **Privacidade** — contacto por `contact_id`; sem telefone em *jobs*, logs ou eventos.
- [ ] **Custo e observabilidade** — `chr_resolve_ms`, `chr_unrouted_total`, `chr_cache_hit_ratio`.
- [ ] **Migrações reversíveis** — `downgrade` de `conversations` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-014 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-014) e docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§6.3, §7, §10.2).
Objectivo: CHR (phone_number_id → tenant, canal, contacto, modo da conversa).
- resolve() com cache de 60 s e invalidação por channel.updated; usa o papel kamba_resolver antes de haver contexto.
- Matriz de estados do tenant/canal (§7.2); recusa Fluxo B no Piloto (KAMBA_FASE=piloto).
- Resolve contacto com a identidade do KAM-008; cria conversations (DDL do ticket) com RLS.
- Entrega ao AGR um job conforme o contrato agent_invocation, sem telefone; mensagens em modo dono/humano
  não vão ao AGR. Desconhecidos vão para unrouted_events.
Não expandas escopo: transições de modo são KAM-018; consentimento KAM-022; envio KAM-015.
Testes: matriz de estados, fusão idempotente, Fluxo B, isolamento. Abre PR com o template do §7.
```

---

## KAM-015 — Outbound: envio, janela de 24 h, templates utility e custo de mensagens

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-013, KAM-014, KAM-004 |
| Bloqueia | KAM-022, KAM-023, KAM-031, KAM-048, KAM-054, KAM-058, KAM-084, KAM-118, KAM-122, KAM-123 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§8, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §5, §7), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3), ADR-009, ADR-013 |

### Contexto

Factos CONFIRMADOS (E1): desde 2026-10-01 as *service messages* são pagas a partir da 1.001.ª por número e mês (Rest of Africa, 0,004 USD) e as *utility* dentro da janela também; mensagens livres só dentro da janela de 24 h, templates para iniciar conversa; cobrança por mensagem **entregue**; botões ≤ 3, listas ≤ 10 linhas; 130429 ao exceder o débito (80 mps por omissão; 20 mps fixos em coexistência). Logo: notificar com **mensagem livre** quando a janela está aberta, template *utility* só com janela fechada, nenhum *marketing* no Piloto e uma mensagem por turno quando possível (verbosidade é custo). Em coexistência, mensagens enviadas pela app não abrem janelas nem afectam preço da Cloud API.

### Objectivo

Implementar o `ChannelAdapter` de saída: decisão de envio por estado da janela, fila com ordem por conversa, registo e ciclo de vida de templates, ingestão monótona de estados e `pricing`, *rate limiting* e metering de custo por tenant.

### Critérios de Aceitação

- [ ] `send` com janela aberta usa mensagem livre/interactiva (categoria *service*); com janela fechada e conteúdo livre devolve `WINDOW_CLOSED` **sem** chamada HTTP; com janela fechada e template `APPROVED` envia o template.
- [ ] Idempotência: 2 chamadas com a mesma `idempotency_key` produzem 1 chamada à API (servidor falso conta) e 1 linha em `outbound_messages` (`UNIQUE`).
- [ ] Estados monótonos: `delivered` seguido de `sent` mantém `delivered`; `failed` é terminal; duplicados do mesmo estado são *no-op*.
- [ ] `pricing` dos estados (`billable`, `pricing_model`, `type`, `category`) é guardado por mensagem; um estado com categoria *service* acima do *free tier* incrementa `meta_cost_usd_total{tenant}` em 0,004 (taxas em `config/meta_rates.yaml`, efectivas 2026-10-01, com data de revisão trimestral).
- [ ] *Token bucket* por `phone_number_id` (15 mps em coexistência, proposta com folga sobre os 20 mps CONFIRMADOS) e por par tenant–contacto (1 msg/s e 30/min, proposta): 100 envios em fila nunca excedem 15/s em nenhuma janela de 1 s medida no servidor falso e drenam em ≥ 6,6 s.
- [ ] Resposta 130429 do servidor falso 3× seguida de 200: backoff exponencial com *jitter*, 3 tentativas, 1 mensagem entregue, 0 duplicados. Meta indisponível: fila com *backoff* e ordem por conversa; mensagens fora da janela expiram em 24 h com aviso ao dono.
- [ ] Validação do construtor: 4 botões ou 11 linhas de lista falham antes de qualquer chamada; templates só nas categorias `utility` e `authentication`; `marketing` é recusado no Piloto.
- [ ] Gancho `PreSendGuard` chamado sob o *lock* da conversa antes de cada envio do bot (implementado em KAM-018); sem ele, o envio do bot falha em ambiente de CI.
- [ ] Recategorização de um template para *marketing* (`template_category_update`) bloqueia o seu uso e alerta; o destinatário é endereçado por BSUID (`recipient`) quando existe, senão por telefone; o telefone nunca aparece em logs.

### Detalhes Técnicos

- **Componentes:** ChannelAdapter (Cloud API), parte do GWY/*worker* de canal. DDL de `outbound_messages` e `message_templates` exactamente como `../docs/tecnica/01` §8.3–§8.4 (`state` aceita também `suppressed_by_human`, necessário a KAM-018).
- **Tabela de decisão (§8.2):** resposta ou notificação com janela aberta → mensagem livre (*service*); janela fechada → template *utility* (0,004); *marketing* 0,0225 desligado; autenticação 0,004 exige telefone.
- **Templates:** `pt_PT` como base (a variante `pt_AO` não existe como código, NÃO VERIFICADO); conjunto padrão (confirmação de pedido, referência de pagamento, lembrete de expiração, lembrete de marcação, passagem a humano) submetido por *tenant* no onboarding (KAM-091); aprovação por Messaging account, não partilhada entre PMEs; estado em `message_template_status_update`, `template_category_update`, `message_template_quality_update`.
- **Janela:** `conversations.window_expires_at = último_inbound + 24 h`; a janela FEP (até 7 dias, anúncios CTWA) é de Clusters.
- **Fora de âmbito:** *free tier* e método de pagamento (KAM-023), decisão sobre quem tem a palavra (KAM-018), lembretes (KAM-048), régua de cobrança (KAM-058).

### Testes Requeridos

- Unit: decisão de envio (matriz janela × tipo × estado do canal); monotonia de estados; cálculo de custo.
- Integração com servidor Graph falso (KAM-024): 130429, 5xx, duplicados, ordem por conversa; carga de *rate limit*.
- Isolamento: `ctx` de A não envia por canal de B; X-03 sobre `outbound_messages`/`message_templates`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (custo e dados pessoais); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/outbound.md`); tarifas revistas à data da evidência; Conventional Commits.
- [ ] **Isolamento de tenant** — `outbound_messages` e `message_templates` com RLS e teste cruzado.
- [ ] **Idempotência** — chave por envio, teste de repetição.
- [ ] **Números só de tools** — o *adapter* envia texto já validado; não gera preços nem totais.
- [ ] **Privacidade** — destinatário por BSUID quando existe; telefone nunca em logs.
- [ ] **Custo e observabilidade** — `meta_cost_usd_total{tenant}`, `outbound_latency_ms`, `outbound_window_closed_total` desde o código.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-015 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-015), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§8) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§1, §5, §7). Objectivo: ChannelAdapter de saída.
- send(): janela aberta → mensagem livre; fechada → template utility ou WINDOW_CLOSED sem chamada HTTP.
- outbound_messages e message_templates (DDL do doc 01 §8.3–8.4), idempotency_key única, estados monótonos,
  pricing por mensagem, custo em meta_rates.yaml (taxas CONFIRMADAS, revisão trimestral).
- Token bucket por número (15 mps em coexistência) e por par; 130429 com backoff+jitter; botões ≤ 3, listas ≤ 10.
- PreSendGuard sob o lock da conversa (implementação em KAM-018); sem marketing no Piloto; BSUID como recipient.
Não expandas escopo: free tier/pagamento Meta é KAM-023; lembretes e cobranças são de outros epics.
Testes: matriz de decisão, idempotência, estados, rate limit, 130429. Abre PR com o template do §7.
```

---

## KAM-016 — Embedded Signup v4 e Tech Provider (troca de code, subscrições de webhooks)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-013, KAM-003, ext:KAM-102, KAM-010 |
| Bloqueia | KAM-017, KAM-091, KAM-093 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.2–§4.4, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§6), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§2, §3), `../docs/tecnica/08_Seguranca_Conformidade.md` (§5), ADR-001, ADR-019 |

### Contexto

Factos CONFIRMADOS (E1 §3): Embedded Signup v2 e v3 deixam de funcionar a 2026-10-15, logo só v4; é preciso Tech Provider ou Solution Partner, Business Verification **da nossa empresa** antes do App Review, Advanced access a `whatsapp_business_messaging` e `whatsapp_business_management`; até 10 clientes novos/7 dias antes de verificação completa (200/7 dias depois; «Access Verification» NÃO VERIFICADO); o cliente é sempre dono dos activos; o ES devolve `waba_id`, `phone_number_id` e um *code* trocável por token. O prazo e a aceitação de documentos angolanos na Business Verification são NÃO VERIFICADOS (L3, D5). O backlog mestre não declara a dependência de KAM-010 (cofre do token e do PIN).

### Objectivo

Implementar o lado servidor do onboarding de canal: receber o resultado do ES v4, trocar o *code* por token de cliente, guardá-lo no cofre, subscrever a app ao WABA e aos campos de webhook, validar com um evento de teste e persistir a máquina de estados do canal com passos idempotentes e compensáveis.

### Critérios de Aceitação

- [ ] `POST /internal/channels` aceita `{tenant_id, code, waba_id, phone_number_id, session_info}`; o ES é v4 (`extras.featureType = "whatsapp_business_app_onboarding"` e `sessionInfoVersion: "3"` para coexistência); o código não referencia v2/v3.
- [ ] Idempotência: repetir o mesmo `code` ou o mesmo `(tenant_id, waba_id)` 2× produz 1 canal, 1 token e 0 subscrições duplicadas.
- [ ] O token de cliente é guardado cifrado (AES-256-GCM, DEK por tenant, KEK no cofre, `kid` versionado) com `token_ref` em `tenant_channels`; um *dump grep* da BD e dos logs não encontra o token em claro; o PIN 2FA de 6 dígitos (modo `cloud_only`) vai para o cofre com acesso mínimo.
- [ ] Anexar um `phone_number_id` já usado por outro tenant devolve 409, não altera nada e deixa registo de auditoria.
- [ ] A subscrição cobre exactamente os campos: `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `account_update`, `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update`; a leitura de confirmação devolve esse conjunto (igualdade de conjuntos) e um evento de teste chega ao GWY.
- [ ] `channel_onboarding` regista a fase (`iniciado, es_concluido, subscrito, a_sincronizar, verificado, pronto, ativo, falhado, abandonado`); transições inválidas são rejeitadas; sem conclusão em 30 min o estado passa a `abandonado`.
- [ ] Cada passo regista o recurso criado e tem compensação (revogar token, anular subscrição); uma falha injectada no passo 4 deixa 0 recursos órfãos.
- [ ] Guarda `waba_id` e `waac_id` (nulo hoje) e `phone_number_id`; o contador `es_onboardings_7d` está exposto para o limite de 10 clientes/7 dias (a lista de espera é KAM-095).
- [ ] 1 onboarding ES v4 real numa conta de teste da Meta, depois de KAM-102, com evidência em `docs/evidencia/KAM-016.md` (capturas sem dados pessoais).

### Detalhes Técnicos

- **Componentes:** GWY (rotas internas), CHR (`tenant_channels`), serviço de onboarding. A página/pop-up do cliente é KAM-093; aqui um *harness* de teste mínimo.
- **Fluxo (de `../docs/tecnica/01` §4.3):** popup ES v4 → `code` + ids → trocar *code* por token → guardar no cofre → subscrever campos → sincronização (KAM-017) → Chatwoot (KAM-019/091) → mensagem de teste → gate de activação. Os pontos finais e parâmetros exactos da Graph API **não** constam de E1 (páginas de referência de API não lidas): ler a documentação vigente («Updated: Jul 24, 2026») e fixar a versão da Graph API em configuração.
- **Estado do canal:** `tenant_channels.estado` mantém `pendente → ativo`; as fases finas vivem em `channel_onboarding(channel_id, fase, recursos_criados jsonb, actualizado_at)`. O orquestrador (saga) é KAM-091; este ticket entrega passos idempotentes.
- **Fora de âmbito:** Business Verification/App Review (KAM-102), sincronização (KAM-017), método de pagamento no Billing Hub e gate de activação (KAM-093).

### Testes Requeridos

- Contrato com Graph falsa (KAM-024): troca de *code*, subscrição, falha injectada, repetição.
- Segurança: token em claro, 409 de `phone_number_id`, auditoria. Máquina de estados: tabela completa de transições.
- Real: 1 execução ponta a ponta na conta de teste (evidência).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (segredos, número de uma PME); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/onboarding-canal.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — um canal pertence a um só tenant; RLS em `channel_onboarding`; teste cruzado.
- [ ] **Idempotência** — passos repetíveis com teste de repetição.
- [ ] **Privacidade** — nenhum dado de cliente final tratado; token e PIN nunca em logs.
- [ ] **Sem segredos** — token/PIN só no cofre; scan limpo.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-016 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-016), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4, §13) e
docs/tecnica/10_Onboarding_Governanca.md (§6). Objectivo: lado servidor do Embedded Signup v4.
- Recebe code, waba_id, phone_number_id; troca o code por token; guarda no cofre (AES-256-GCM, DEK por tenant);
  subscreve os 11 campos de webhook e confirma por leitura; valida com evento de teste.
- channel_onboarding com fases, passos idempotentes por (tenant_id, waba_id) e compensação; 409 se o número é de outro tenant.
- Só v4. Lê a documentação vigente da Meta para endpoints e parâmetros; não inventes caminhos de API.
- Guarda waba_id e waac_id (nulo); expõe es_onboardings_7d (limite 10/7 dias).
Não expandas escopo: sem Business Verification (KAM-102), sem sync (KAM-017), sem UI (KAM-093).
Testes: Graph falsa, repetição, falha injectada, segurança do token, 1 execução real. Abre PR com o template do §7.
```

---

## KAM-017 — Coexistência: history, state sync, echoes, `PARTNER_REMOVED`, sincronização de 24 h

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-016, ext:KAM-100 |
| Bloqueia | KAM-018, KAM-083, KAM-093, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.1, §10.4, §10.5, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§6.3, §7.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§2), ADR-001, ADR-010 |

### Contexto

Factos CONFIRMADOS (E1 §2): a coexistência exige Tech Provider, app WhatsApp Business ≥ 2.24.17 e ES com *session logging*; sincroniza contactos e **6 meses** de histórico em **24 h** após o onboarding (cada passo só uma vez, senão offboard e refazer); débito fixo de 20 mps; `PARTNER_REMOVED` com `PRIMARY_INACTIVITY` (~14 dias sem abrir a app), `COMPANION_INACTIVITY`, `BUSINESS_DOWNGRADE`, `CHANGE_NUMBER`, `USER_RE_REGISTERED`, `ACCOUNT_DISCONNECTED`; a API de *deregister* não funciona. **Elegibilidade de Angola: NÃO VERIFICADA (L1)**; o spike KAM-100 decide. Se falhar para um número, o modo é `cloud_only` com número novo dedicado (a lógica de saída é a mesma). Se um *echo* é gerado por mensagens enviadas por API é NÃO VERIFICADO (L6); a comparação com `outbound_messages.wamid` torna o tratamento seguro nos dois casos.

### Objectivo

Tratar os webhooks de coexistência e a sincronização inicial com prazo duro de 24 h, o ciclo de desligamento e reconexão, e garantir que histórico e sincronização nunca produzem resposta do bot.

### Critérios de Aceitação

- [ ] `history` e `smb_app_state_sync` alimentam `contacts` (KAM-008) e `coexistence_synced_at`; 0 *jobs* para o AGR e 0 mensagens enviadas por estes eventos (fixture com 6 meses de histórico).
- [ ] O corpo das mensagens de histórico **não** é persistido nem indexado no Piloto (apenas contactos e contagens); a base legal para o usar (a confirmar por parecer, KAM-104) fica como critério de saída antes de o alargar.
- [ ] O *job* de sincronização é idempotente (cada passo executado uma vez; 2.ª execução = *no-op*), alerta aos 12 h sem conclusão e marca o canal `falhado` + tarefa de *offboard* às 24 h (relógio acelerado nos testes).
- [ ] O erro 2593109 (cliente não partilhou histórico) conduz a `sincronizado_sem_historico` e **não** a falha.
- [ ] Cada um dos 6 motivos de `PARTNER_REMOVED` passa o canal a `desligado`, emite `channel.updated` e cria alerta; repetir o mesmo evento 2× produz 1 transição.
- [ ] Aviso preventivo `channel.inactivity_warning` aos 10 dias sem *echo* e sem actividade do dono (heurística de `../docs/tecnica/01` §10.5; a entrega ao dono por canal alternativo depende de mecanismo ainda sem ticket: ver riscos).
- [ ] Os *echoes* (`smb_message_echoes`) são registados em `inbound_events` (`kind=echo`) e entregues ao tratador de KAM-018; um *echo* cujo `wamid` consta de `outbound_messages` é ignorado como actividade humana.
- [ ] O `channel_mode` determina o que fica activo: em `cloud_only` não há *job* de sincronização nem *echoes*; o débito do *token bucket* de KAM-015 usa 15 mps em `coexistencia`.
- [ ] A reconexão (`desligado → iniciado`) reutiliza o ES de KAM-016 sem criar canal duplicado.
- [ ] Evidência da elegibilidade: ≥ 1 sincronização completa num número +244 real e referência ao relatório de KAM-100; se KAM-100 concluir negativo, o predefinido do produto passa a `cloud_only` e o ticket regista-o.

### Detalhes Técnicos

- **Componentes:** CHR/canal (tratadores de `account_update`, `history`, `smb_app_state_sync`, `smb_message_echoes`), job de sincronização em BullMQ com *deadline*.
- **Campos CONFIRMADOS:** `extras.featureType = "whatsapp_business_app_onboarding"`; evento final `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`; **sem registo do número**; janela de conversa só abre com mensagem do utilizador **depois** do onboarding (conversas anteriores só por template).
- **Funcionalidades perdidas pela PME** (grupos, listas de difusão, catálogo e respostas rápidas da app, `E1` §2) devem constar do aviso do onboarding (texto em KAM-093).
- **Eventos:** `channel.updated` (KAM-007) com `motivo`; o registo de desligamento fica também em `channel_onboarding`.
- **Fora de âmbito:** decisão de silenciamento (KAM-018), UI de reconexão (KAM-093), histórico no RAG/LLM (proibido sem base legal; nunca para treino, Termos da Meta §4.7, L15).

### Testes Requeridos

- Contrato com fixtures do simulador (KAM-024): `history`, `smb_app_state_sync`, `smb_message_echoes`, 6 × `account_update`, erro 2593109, duplicados.
- Tempo: relógio acelerado para 12 h/24 h/10 dias. Isolamento: eventos de A não alteram canais de B.
- Real: sincronização num número +244 (evidência).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (número de uma PME, dados pessoais); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/coexistencia.md`, com funcionalidades perdidas); Conventional Commits.
- [ ] **Isolamento de tenant** — eventos resolvidos por `waba_id`/`phone_number_id` → tenant; teste cruzado.
- [ ] **Idempotência** — sincronização e `account_update` repetidos com teste.
- [ ] **Privacidade** — histórico não persistido nem enviado a LLM; contactos por `contact_id`.
- [ ] **Custo e observabilidade** — `coex_sync_duration_s`, `coex_sync_failed_total`, `channel_disconnected_total`.
- [ ] O resultado de KAM-100 (L1) está referenciado e o modo predefinido decidido.

### Handoff para Claude Code

```text
És o executor do ticket KAM-017 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-017), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§10.1, §10.4, §10.5)
e docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§2). Objectivo: coexistência (histórico, sync, echoes, PARTNER_REMOVED).
- history e smb_app_state_sync só ingestão (contactos e contagens); nunca AGR, nunca resposta; não persistas corpos.
- Job de sincronização idempotente com deadline de 24 h e alerta aos 12 h; erro 2593109 é caso normal.
- account_update → desligado + channel.updated + alerta; aviso aos 10 dias sem echo; reconexão por ES sem duplicar canal.
- Echoes para o tratador de KAM-018; ignora echo cujo wamid está em outbound_messages. channel_mode manda.
- Lê o relatório de KAM-100; se negativo, o modo predefinido passa a cloud_only e regista-o.
Não expandas escopo: silenciamento é KAM-018; UI de reconexão é KAM-093.
Testes: fixtures do simulador, relógio acelerado, isolamento, 1 sync real. Abre PR com o template do §7.
```

---

## KAM-018 — Protocolo bot ↔ dono ↔ humano: modos da conversa e silenciamento por echo

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-014, KAM-017 |
| Bloqueia | KAM-034, KAM-109, KAM-114, KAM-117, KAM-118, KAM-123 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.2, §10.3, §19 proposta 01-C), `../docs/tecnica/00_Arquitectura_Solucao.md` (§12), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§12), ADR-001, ADR-010 |

### Contexto

Em coexistência o dono e o bot falam pelo mesmo número; sem protocolo respondem em simultâneo e contradizem-se (risco da §12 do doc 00). A decisão é tratar o **modo da conversa** (`bot`, `dono`, `humano`, `pausada`) como estado de primeira classe (proposta 01-C), por conversa e nunca por canal, com verificação pré-envio sob o *lock* da conversa. O gatilho é o *echo* (`smb_message_echoes`) cujo `wamid` não está em `outbound_messages`. A janela residual de corrida é a latência do *echo* (NÃO MEDIDA, L6). A Messaging Policy exige caminho de escalonamento a humano em todas as conversas (E1 §4, CONFIRMADO).

### Objectivo

Implementar a máquina de estados do modo da conversa, o tratador de *echoes*, o `PreSendGuard` que descarta respostas do bot quando houve actividade humana e a medição da latência do *echo*.

### Critérios de Aceitação

- [ ] Transições (tabela de `../docs/tecnica/01` §10.2): `bot→dono` por *echo* com `wamid` ausente de `outbound_messages`; `dono→bot` quando o cliente escreve depois de `silencio_dono_min` (predefinido 30, a calibrar) sem actividade do dono, ou por comando `/bot` do dono; `bot→humano` por pedido do grafo ou do cliente; `humano→bot` por `conversation_status_changed=resolved`; qualquer→`pausada` por opt-out ou 24 h sem humano após handoff; `pausada→bot` quando o cliente volta a escrever após aviso. Qualquer outra transição é rejeitada (teste exaustivo da tabela).
- [ ] `PreSendGuard`, sob `pg_advisory_xact_lock(hash(tenant_id, contact_id))`, descarta o envio se `mode ≠ bot` ou `last_human_activity_at > início_do_turno`, regista `suppressed_by_human` e devolve ao AGR o sinal de cancelamento.
- [ ] Teste de corrida: turno inicia em t0, *echo* chega em t0+1 s, resposta pronta em t0+2 s → 0 mensagens enviadas e 1 registo suprimido; em 100 intercalações aleatórias, 0 mensagens do bot são enviadas depois de o *echo* estar registado.
- [ ] O silenciamento é por conversa: duas conversas no mesmo canal, A em `dono` e B em `bot`, respondem independentemente.
- [ ] Mensagens do cliente em modo `dono`/`humano` são entregues ao dono/HND e **não** ao AGR (0 *jobs* AGR nesse modo).
- [ ] Cada mudança emite `conversation.mode_changed` (tipo acrescentado ao catálogo, KAM-007) e actualiza o estado visível em HND (KAM-019) em ≤ 5 s (proposta).
- [ ] Um tratador `onOptOut(contact)` coloca `pausada` (a detecção de «PARAR» é de KAM-022); o *timeout* de 24 h corre como *job* idempotente.
- [ ] Métrica `echo_latency_ms` (diferença entre o carimbo da Meta e a recepção) com p50/p95 de ≥ 30 *echoes* reais em *staging* anexados como evidência (critério de saída de L6); sem limiar bloqueante.

### Detalhes Técnicos

- **Componentes:** CHR (modo da conversa), HND (espelho do estado), ChannelAdapter (`PreSendGuard`). Tabela `conversations` criada em KAM-014; migração aqui adiciona `outbound_messages.state='suppressed_by_human'` se ainda não existir.
- **Pseudocódigo do guard:**
```
guard(conv, turn): lock(conv)
  if conv.mode != 'bot' or conv.last_human_activity_at > turn.started_at:
      record(suppressed_by_human); return CANCEL
  return OK
```
- **UX:** o comando `/bot` do dono é uma mensagem real enviada ao cliente (visível); validar no Piloto se é aceitável e, se não, mover o comando para o painel/Chatwoot. O onboarding explica ao dono a regra «se responder na app, o bot cala-se nessa conversa» (`../docs/tecnica/01` §10.3).
- **Fora de âmbito:** retoma do grafo após handoff (KAM-034), criação de conversas no Chatwoot (KAM-019), detecção de opt-out (KAM-022).

### Testes Requeridos

- Unit: tabela de transições (todas as combinações estado × gatilho).
- Concorrência: 100 intercalações *echo*/resposta com ordem aleatória; dois eventos simultâneos serializados pelo *lock*.
- Integração: duas conversas independentes; modo `humano` sem invocações do AGR; evidência de latência de *echo* em *staging* com número +244.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (corrida, número de uma PME); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/modos-conversa.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — o *lock* e o modo usam `tenant_id` do contexto; teste cruzado do novo caminho.
- [ ] **Idempotência** — o mesmo *echo* repetido 2× produz 1 transição; teste incluído.
- [ ] **Privacidade** — sem conteúdo nem telefone em `conversation.mode_changed` nem em logs.
- [ ] **Custo e observabilidade** — `conv_mode_transitions_total`, `echo_latency_ms`, `reply_suppressed_total`.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-018 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-018), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§10.2, §10.3).
Objectivo: modos da conversa (bot, dono, humano, pausada) e silenciamento por echo.
- Máquina de estados com a tabela de transições; silencio_dono_min = 30 (a calibrar); comando /bot.
- Tratador de echoes: wamid ∉ outbound_messages ⇒ actividade humana; PreSendGuard sob pg_advisory_xact_lock.
- Suprime a resposta do bot se mode ≠ bot ou houve actividade humana depois do início do turno; regista
  suppressed_by_human. Mensagens do cliente em dono/humano não vão ao AGR. Emite conversation.mode_changed.
- Mede echo_latency_ms; reúne ≥ 30 echoes reais em staging como evidência de L6.
Não expandas escopo: retoma do grafo (KAM-034), opt-out (KAM-022), Chatwoot (KAM-019).
Testes: transições, 100 intercalações, conversas independentes, evidência de latência. Abre PR com o template do §7.
```

---

## KAM-019 — HND: HandoffProvider e Chatwoot (Agent Bot API, espelho por inbox de tipo API)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-014 |
| Bloqueia | KAM-031, KAM-034, KAM-091 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§11, §14, §15), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.6), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§12), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.2), ADR-001, ADR-002 |

### Contexto

Adopta-se o **Desenho I** (proposta 01-A): o GWY é o único endpoint Meta; o HND grava no Chatwoot por *inbox* de tipo API; o *Agent Bot* (`outgoing_url` = HND) notifica-nos de mensagens e estados humanos; o envio ao cliente é sempre pelo nosso ChannelAdapter. Factos CONFIRMADOS no código (E4 §2.2): Chatwoot v4.18 é MIT fora de `enterprise/`; Platform API (`accounts`, `users`, `account_users`, `agent_bots`); `AgentBot` com `bot_type=webhook`, `outgoing_url`, `secret`, `access_token`; bot com `account_id` nulo é **global e acessível a todas as contas**; marca branca, SLA, audit logs, SAML, custom roles e Captain/Copilot são Enterprise. **NÃO VERIFICADO (L7):** que o token do *agent bot* consiga passar `pending → open`; plano B: utilizador-serviço «KAMBÁ Bot» com token da Application API. O Chatwoot contém dados pessoais (alojamento sob D1/ADR-008).

### Objectivo

Implementar a interface `HandoffProvider` e a sua implementação Chatwoot: provisionamento de conta/bot/*inbox* por PME, espelho idempotente de mensagens, `openHandoff` idempotente, recepção assinada de eventos humanos e entrega das respostas humanas ao Outbound.

### Critérios de Aceitação

- [ ] `ensureAccount(tenantId)` cria (ou devolve) 1 conta Chatwoot por PME, 1 *agent bot* com `account_id` da conta e 1 *inbox* de tipo API; chamado 2× não duplica; um *agent bot* com `account_id` nulo é impossível por construção (teste).
- [ ] O Chatwoot não tem credenciais Meta: `WHATSAPP_APP_ID`, `WHATSAPP_CONFIGURATION_ID` e `WHATSAPP_APP_SECRET` não estão configurados e nenhum *inbox* é do tipo WhatsApp (teste de configuração).
- [ ] `mirrorMessage` é idempotente por `wamid`: 3 chamadas produzem 1 mensagem no Chatwoot.
- [ ] `openHandoff` é idempotente por `handoffId = hash(thread_id, ordinal)`: procura a conversa por atributo `handoffId`, senão cria; 5 chamadas concorrentes produzem 1 conversa, passada a `open`, atribuída à equipa, com nota privada com o resumo.
- [ ] Os *callbacks* do Chatwoot (`message_created` de agente, `conversation_status_changed`) só são aceites com o `secret` do bot; ausente ou errado devolve 401 e incrementa uma métrica.
- [ ] A resposta humana é enviada ao cliente pelo Outbound (janela, template se fechada, custo registado); com janela fechada o painel recebe aviso e proposta de template *utility*.
- [ ] Tabela `handoffs(handoff_id PK, tenant_id, conversation_id, status ∈ waiting|resumed|timeout|cancelled|degraded, opened_at, resumed_at, resolver)` criada com RLS; o `resolved` duplicado não altera nada (a retoma por *compare-and-set* é KAM-034).
- [ ] Spike de 1 dia concluído: o resultado de `pending → open` com o token do *agent bot* está em `docs/evidencia/KAM-019-bot-open.md` e a implementação usa a opção que funciona (bot ou utilizador-serviço).
- [ ] Chatwoot indisponível: `openHandoff` falha para uma fila com *retry*, o espelho acumula e reconcilia por `wamid`; healthcheck alerta.
- [ ] Teste X-10: o agente da conta A não lê conversas da conta B (API); tokens de bot cifrados por tenant; o token da Platform API só existe no módulo de provisioning.

### Detalhes Técnicos

- **Componentes:** HND (`services/worker-canal/hnd`). Interface de `../docs/tecnica/01` §11.1:
```ts
interface HandoffProvider {
  ensureAccount(tenantId: string): Promise<{ accountId: number; inboxId: number; botId: number }>;
  mirrorMessage(ctx: ChannelContext, m: MirrorMessage): Promise<void>;                 // idempotente por wamid
  openHandoff(req: { tenantId; contactId; conversationId; handoffId: string; motivo; resumo }): Promise<{ externalId: string }>;
  setBotMuted(conversationId: string, muted: boolean): Promise<void>;
  onHumanEvent(handler: (e: HumanEvent) => Promise<void>): void;
  close(handoffId: string, outcome: 'resolved'|'timeout'|'cancelled'): Promise<void>;
}
```
- **Notificação ao dono:** não pode usar o próprio número da loja; usa notificações do Chatwoot (push/e-mail). Um aviso por *template* a um segundo número do dono é NÃO VERIFICADO e fica fora deste ticket.
- **Licença:** versão fixada (4.18.x) por digest; funcionalidades `enterprise/` não usadas; o mecanismo de verificação (plano *community*) é definido aqui e ligado ao gate «licenças EE» (`../docs/tecnica/09` §7). Dimensionamento: ≥ 4 GB e 4 núcleos (KAM-076/084).
- **Fora de âmbito:** nós de grafo `handoff_prepare`/`handoff_wait` e retoma (KAM-034), provisioning orquestrado (KAM-091), Typebot/n8n (uso interno apenas).

### Testes Requeridos

- Contrato contra Chatwoot real em compose (v4.18.x) com dados sintéticos; idempotência concorrente; *secret* inválido.
- Isolamento: X-10 cross-account; teste de configuração sem credenciais Meta.
- Degradação: Chatwoot parado → fila e reconciliação por `wamid`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (isolamento entre contas, segredos); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/hnd.md`, resultado do spike); Conventional Commits.
- [ ] **Isolamento de tenant** — 1 conta por PME, tokens por conta, RLS em `handoffs`; teste cruzado.
- [ ] **Idempotência** — `openHandoff` e `mirrorMessage` com teste de repetição.
- [ ] **Privacidade** — o Chatwoot só recebe dados da conversa necessários; dados sintéticos fora de `prod`; alojamento sujeito a D1.
- [ ] **Sem segredos** — tokens no cofre; **Dependências** — imagem por digest, sem `enterprise/`.
- [ ] **Migrações reversíveis** — `downgrade` de `handoffs` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-019 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-019), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§11) e
docs/tecnica/08_Seguranca_Conformidade.md (§3.6). Objectivo: HandoffProvider com Chatwoot (Desenho I).
- Uma conta Chatwoot por PME; agent bot com account_id; inbox de tipo API; zero credenciais Meta no Chatwoot.
- mirrorMessage idempotente por wamid; openHandoff idempotente por handoffId (atributo na conversa);
  callbacks só com o secret do bot; resposta humana pelo Outbound (KAM-015).
- Tabela handoffs com RLS. Spike de 1 dia: pending→open com token de bot (L7); plano B utilizador-serviço.
- Não uses nada de enterprise/ (marca branca, SLA, audit logs, SAML, custom roles, Captain/Copilot).
Não expandas escopo: nós do grafo e retoma por CAS são KAM-034; provisioning é KAM-091.
Testes: Chatwoot real em compose, concorrência, X-10, degradação. Abre PR com o template do §7.
```

---

## KAM-020 — Mídia: download autenticado, armazenamento e URL interna assinada

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013, KAM-011 |
| Bloqueia | KAM-036, KAM-049, KAM-071 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§5.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.8, §7.5), `../docs/tecnica/00_Arquitectura_Solucao.md` (MED, STO), ADR-013, ADR-014 |

### Contexto

Áudio, imagens e documentos recebidos chegam por `media_id` e têm de ir para o `StorageProvider` (ADR-014); o URL da Meta expira e **nunca** é persistido. O MED serve STT (KAM-036), Catálogo AI (KAM-049), KYC (KAM-087) e o espelho para o Chatwoot. Uma imagem pode ser um comprovativo de pagamento, mas **nunca é prova** (ADR-013): o MED não tem caminho para alterar estado de pagamento. As páginas de referência da API de mídia não foram lidas em E1 (limitação declarada): o fluxo de duas etapas (resolver o `media_id`, descarregar com autenticação) deve ser confirmado na documentação vigente antes de implementar.

### Objectivo

Implementar o pipeline MED de recepção: descarga autenticada, validação, armazenamento por tenant, registo em `media_assets` e emissão de URL interna assinada de curta duração.

### Critérios de Aceitação

- [ ] Uma mensagem `image|audio|document` com `media_id` resulta em 1 objecto em `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}` e 1 linha em `media_assets` (`tenant_id, contact_id, conversation_id, wamid, classe, content_type, size, sha256, storage_ref, estado, retain_until`).
- [ ] Idempotência: a mesma `(tenant_id, wamid, media_id)` processada 3× produz 1 objecto e 1 linha (`UNIQUE`).
- [ ] Nenhum URL da Meta é persistido (BD, logs, eventos): teste que percorre as tabelas e logs de uma execução por padrões do domínio da Meta.
- [ ] Validação por *allowlist* de `content_type` (proposta: JPEG, PNG, WebP, OGG/Opus, PDF) e tamanho máximo por classe configurável (valores a calibrar contra os limites da Meta, NÃO VERIFICADOS); tipo ou tamanho inválido → `estado='rejeitado'` e resposta determinística pedindo outro formato.
- [ ] URL interna assinada com TTL ≤ 300 s para consumidores autorizados; com `ctx` de outro tenant é recusada (X-08); depois do TTL devolve 403.
- [ ] Falha de descarga: 3 tentativas com *backoff*; depois `estado='falhou'` e sinal ao AGR para pedir ao cliente que reenvie.
- [ ] Áudio: `retain_until = criação + 24 h` (alvo de `../docs/tecnica/08` §7.5; limite de erro 72 h) e gancho `onTranscribed(asset)` que agenda a eliminação do blob; a purga em si é KAM-071.
- [ ] O MED não importa módulos de PAY nem de COM (teste de arquitectura): 0 caminhos de código que alterem estado de pagamento a partir de uma imagem.
- [ ] Métricas `media_bytes_total{classe}`, `media_download_ms`, `media_rejected_total{motivo}` sem conteúdo nos logs.

### Detalhes Técnicos

- **Componentes:** MED, STO (via `StorageProvider` de KAM-011), GWY/*worker* de canal (origem do evento).
- **Fluxo:** `media_id` → resolver URL temporário com o token do canal (cofre) → descarregar → calcular `sha256` → `put` → registar → emitir referência interna `media://{asset_id}`; consumidores pedem `signUrl`. O *worker* corre sob contexto de tenant (CHR já resolvido).
- **Deduplicação por conteúdo:** `sha256` por tenant evita duplicar armazenamento (opcional; registar contagem); fotos de produto vivem enquanto o catálogo viver.
- **Segurança:** análise de malware/conteúdo activo em ficheiros carregados não consta de `../docs/tecnica/`; fica como item do modelo de ameaças (KAM-065) e limita-se aqui a *allowlist* de tipos.
- **Fora de âmbito:** STT (KAM-036), visão/Catálogo AI (KAM-049), KYC (KAM-087), purga (KAM-071), crypto-shredding por DEK de contacto (KAM-070/071).

### Testes Requeridos

- Unit: validação de tipos/tamanhos; geração de chaves; idempotência.
- Integração com Graph falsa (KAM-024) e `StorageProvider` *fake*/SeaweedFS: sucesso, URL expirado, falha de descarga.
- Isolamento X-08 e teste de arquitectura (sem PAY/COM); *grep* de URLs da Meta.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais, isolamento); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/media.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — prefixo por tenant, RLS em `media_assets`, teste cruzado X-08.
- [ ] **Idempotência** — `UNIQUE` e teste de repetição.
- [ ] **Pagamento só por evento autenticado** — nenhuma imagem altera estado de pagamento (teste de arquitectura).
- [ ] **Privacidade** — áudio com retenção curta; sem URLs da Meta nem conteúdo em logs.
- [ ] **Custo e observabilidade** — métricas de bytes, latência e rejeição desde o código.
- [ ] **Migrações reversíveis** — `downgrade` de `media_assets` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-020 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-020), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§5.4) e
docs/tecnica/08_Seguranca_Conformidade.md (§3.8, §7.5). Objectivo: pipeline MED de recepção de mídia.
- Descarga autenticada por media_id (confirma o fluxo na documentação vigente da Meta), validação por allowlist,
  put no StorageProvider em t/{tenant_id}/media/..., registo idempotente em media_assets (UNIQUE tenant,wamid,media_id).
- Nunca persistas URLs da Meta; URL interna assinada ≤ 300 s; áudio com retain_until = 24 h.
- O MED não importa PAY/COM: uma imagem nunca é prova de pagamento (ADR-013). Falhas: 3 tentativas e sinal ao AGR.
Não expandas escopo: STT (KAM-036), visão (KAM-049), KYC (KAM-087), purga (KAM-071).
Testes: idempotência, rejeição, URL expirada, X-08, teste de arquitectura. Abre PR com o template do §7.
```

---

## KAM-021 — Quality rating, estado `restrito` e monitorização de limites

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013, KAM-009 |
| Bloqueia | KAM-083, KAM-097, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§9, §19 proposta 01-B), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.2), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), ADR-001 |

### Contexto

Factos CONFIRMADOS (E1 §5): desde 2025-10-07 a qualidade baixa já não faz descer o limite automaticamente e o estado «Flagged» foi eliminado; a qualidade (GREEN/YELLOW/RED) continua a existir; o limite de mensagens fora da janela é por **portfólio** e conta utilizadores únicos em 24 h móveis (250 → 2.000 → 10.000 → 100.000 → ilimitado); `messaging_limit_tier` está deprecado em favor de `whatsapp_business_manager_messaging_limit`; eventos `phone_number_quality_update`, `business_capability_update`, `account_alerts`. A Meta pode limitar ou remover acesso sem aviso com base em denúncias. Há divergência documental: o doc 00 §6.2 e o doc 01 §9.1 propõem RED → `restrito` (reversível, automático); `../docs/tecnica/10` §6.4 diz RED → `suspenso`. **Decisão:** `restrito`; `suspenso` fica para T&S, falta de pagamento ou violação (proposta 01-B).

### Objectivo

Persistir o estado de qualidade e de limites dos canais, aplicar a transição automática e reversível para `restrito` e vigiar a utilização do limite de contactos novos fora da janela.

### Critérios de Aceitação

- [ ] `phone_number_quality_update` actualiza `tenant_channels.quality_rating` e acrescenta linha a `channel_quality_log` (valor anterior, novo, evento, hora); GREEN/YELLOW/RED aceites, outro valor registado como desconhecido sem falhar.
- [ ] RED passa o canal a `restrito` em ≤ 5 s (proposta), emite `channel.updated` e: bloqueia templates *marketing* e iniciar conversas, mantém respostas dentro da janela; o regresso a GREEN/YELLOW repõe `ativo`; nunca há transição automática para `suspenso` (teste com 50 eventos aleatórios).
- [ ] No Piloto (1 canal por tenant) `tenants.estado` projecta `restrito` enquanto o canal único estiver restrito e volta a `ativo` com ele.
- [ ] YELLOW gera 1 alerta a T&S por transição (sem repetição em eventos idênticos) e marca os templates para revisão.
- [ ] `business_capability_update` persiste `messaging_limit` (ex.: `TIER_250 → TIER_2000`) e `max_phone_numbers_per_business`; `message_template_quality_update` pausa localmente o envio do template afectado.
- [ ] Duplicados: o mesmo evento 2× gera 1 transição (a chave do evento é o *hash* de `phone_number_id` + tipo + valor + marca temporal da Meta).
- [ ] Medidor `messaging_limit_usage_ratio` = utilizadores únicos contactados por template nas últimas 24 h ÷ limite do escalão; 200 contactos distintos com `TIER_250` dá 0,8 e dispara alerta; resposta dentro da janela não consome.
- [ ] O `account_alerts` cria *ticket* para T&S com o texto da Meta (sem dados pessoais) e o canal não muda de estado.
- [ ] O KAM-015 honra `restrito` (recusa *marketing*/iniciar conversa) e o CHR usa a matriz de KAM-009 (teste de integração entre os três).

### Detalhes Técnicos

- **Componentes:** CHR (estado do canal), GWY/*worker* de canal (consumo de webhooks), OBS (alertas). Colunas `quality_rating` e `messaging_limit` já existem (KAM-003).
- **Tabela nova:** `channel_quality_log(id, tenant_id, channel_id, evento, valor_anterior, valor_novo, ocorrido_em, event_key UNIQUE)` com RLS.
- **Regras do doc 01 §9.1:** YELLOW → alerta e revisão de templates; RED → `restrito`; escalão novo → persistir e recalcular capacidade; pico de bloqueios/denúncias (131xxx em `failed`) → congelar iniciativas do bot e rever. O padrão da Meta (limite e remoção sem aviso) mantém-se como risco residual.
- **Higiene preventiva (§9.2):** sem *marketing*, opt-out imediato, «falar com humano» em todas as conversas; fica fora deste ticket (KAM-022, KAM-015).
- **Fora de âmbito:** suspensão por T&S (KAM-089/097), gate de pagamento (KAM-023), runbook de rating (KAM-083).

### Testes Requeridos

- Contrato com fixtures do simulador (KAM-024): sequências GREEN→YELLOW→RED→GREEN, duplicados, valores desconhecidos.
- Integração: `restrito` bloqueia *marketing* em KAM-015 e não bloqueia resposta na janela.
- Isolamento: eventos de A não alteram canal de B; X-03 sobre `channel_quality_log`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada; divergência com `../docs/tecnica/10` §6.4 registada para correcção; Conventional Commits.
- [ ] **Isolamento de tenant** — resolução por `phone_number_id`; RLS em `channel_quality_log`; teste cruzado.
- [ ] **Idempotência** — chave por evento e teste de repetição.
- [ ] **Privacidade** — alertas e *tickets* sem conteúdo nem telefone.
- [ ] **Custo e observabilidade** — `channel_quality{rating}`, `messaging_limit_usage_ratio`, `channel_restricted_total`.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-021 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-021), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§9) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§5). Objectivo: qualidade, estado restrito e limites do canal.
- phone_number_quality_update, business_capability_update, account_alerts, message_template_quality_update.
- RED → restrito (automático, reversível, sem marketing nem iniciar conversas); nunca suspenso automático.
- channel_quality_log com event_key único; messaging_limit_usage_ratio (utilizadores únicos fora da janela / escalão).
- Usa whatsapp_business_manager_messaging_limit (messaging_limit_tier está deprecado); emite channel.updated.
Não expandas escopo: suspensão é T&S (KAM-089/097); runbooks são KAM-083.
Testes: sequências de qualidade, duplicados, integração com KAM-015, isolamento. Abre PR com o template do §7.
```

---

## KAM-022 — Consentimento no 1.º contacto (aviso versionado, botões, `consent_event`)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-008, KAM-014, KAM-015, KAM-159 |
| Bloqueia | KAM-048, KAM-070, KAM-109 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/10_Onboarding_Governanca.md` (§7), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.3), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, ADR-010 |

### Contexto

O ADR-010 exige consentimento no 1.º contacto. Cada PME é, em princípio, responsável pelo tratamento e a KAMBÁ subcontratada (NÃO VERIFICADO como a APD qualifica plataformas SaaS, D9); se a base legal é contrato, consentimento ou interesse legítimo é matéria de parecer (KAM-104). A Messaging Policy (E1 §4, CONFIRMADO) exige opt-in específico por categoria para mensagens iniciadas pelo negócio, opt-out claro e caminho para humano. O aviso inclui: quem é o responsável (a loja), que é um assistente automático (E3 req. 15), finalidades, destinatários (inclui fornecedor de LLM e país), direitos e como falar com um humano. **Há três desenhos de consentimento** nos documentos (`consent_log` em 01 §6.2, `consent_ledger` em 06 §7.3, `consent_event` em 10 §7.2); este ticket adopta `consent_event` (nome do backlog) e regista a reconciliação.

### Objectivo

Implementar a barreira de consentimento anterior ao AGR: aviso curto e versionado com botões, registo `append-only` com prova, opt-out «PARAR», e eventos `consent.recorded`/`consent.withdrawn`.

### Critérios de Aceitação

- [ ] Primeira mensagem de um contacto sem `consent_event` válido para a versão de texto vigente: exactamente 1 mensagem de saída (o aviso, com 3 botões «Continuar», «Falar com a loja», «Saber mais») e 0 invocações do AGR.
- [ ] «Continuar» grava 1 linha `consent_event` (`purpose='transacao'`, `accepted=true`, `text_version`, `canal`, `evidence_hash`) e só então o AGR é invocado; o mesmo botão repetido 2× produz 1 linha.
- [ ] «Falar com a loja» passa a conversa a `humano` (KAM-018/019) sem tratar dados por IA; «Saber mais» envia o texto completo/ligação à política e repete o aviso; texto livre em vez de botão repete o aviso até 2 vezes e depois encaminha a `humano` (comportamento a confirmar por parecer).
- [ ] Propriedade: em sequências aleatórias de 1.000 mensagens por 50 contactos, nenhum *job* do AGR é criado sem `consent_event` válido anterior (0 violações).
- [ ] «PARAR» (insensível a maiúsculas e acentos) em qualquer ponto grava `purpose='marketing'`, `accepted=false`, passa a conversa a `pausada` (gancho de KAM-018) e responde 1 confirmação; *marketing* sem `accepted=true` específico é recusado pelo Outbound (KAM-015).
- [ ] `consent_event` é *append-only* (`UPDATE/DELETE` recusados para `kamba_app`); revogação = nova linha; a vista `consent_actual` devolve o último estado por `(tenant, contact, purpose)`.
- [ ] `consent_texts(version, purpose, texto, hash, vigente_desde)` versiona o aviso; subir a versão exige re-aviso apenas a contactos sem consentimento da nova versão (política em proposta, a confirmar por parecer); `evidence_hash = sha256(texto_versão ‖ contact_id ‖ wamid_do_botão ‖ hora)` é reprodutível.
- [ ] Eventos `consent.recorded` e `consent.withdrawn` emitidos pelo outbox com `contact_id` (sem texto nem telefone).
- [ ] Contactos vindos da sincronização de histórico (KAM-017) recebem o aviso na primeira mensagem **depois** do onboarding; o aviso é uma única mensagem em PT-AO (custo de *service message* a considerar).

### Detalhes Técnicos

- **Componentes:** CHR/canal (`ConsentGate` antes do AGR), Outbound (botões), GOV (texto e versões). DDL de `../docs/tecnica/10` §7.2 com `contact_id uuid` (o doc usa `bytea`, em conflito com ADR-010) e `purpose` com o dominio de dez do dicionario 3.1 (emenda 1.16); os propósitos analíticos de `consent_ledger` (06 §7.3) são Diferidos e entram por migração quando existirem.
- **Fluxo:** `inbound → ConsentGate → (sem consentimento) aviso | (com consentimento) AGR`. O gate corre no pipeline de canal, porque KAM-025 não depende deste ticket.
- **Botões:** `button_reply` entrega `reply.id` emitido por nós (o AGR confia no `id`, não no título). Marketing exige consentimento separado com «PARAR» em cada mensagem (E1 §4); no Piloto não há *marketing*.
- **Fora de âmbito:** consentimento da PME (ToS/DPA, KAM-090), direitos do titular (KAM-070), parecer sobre o texto (KAM-104); o texto final em PT-AO é revisto juridicamente.

### Testes Requeridos

- Unit: máquina de estados do aviso (6 entradas × 3 estados); `evidence_hash`; detecção de «PARAR» (8 variantes).
- Propriedade: 1.000 mensagens × 50 contactos, 0 AGR sem consentimento. Integração: repetição de botão, subir versão do texto.
- Segurança: *append-only* por papel; isolamento X-03 sobre `consent_event`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada; reconciliação dos três desenhos de consentimento registada; Conventional Commits.
- [ ] **Isolamento de tenant** — RLS em `consent_event`/`consent_texts`; teste cruzado.
- [ ] **Idempotência** — botão repetido não duplica registo; teste incluído.
- [ ] **Privacidade** — `contact_id` (nunca telefone); texto e prova versionados; base legal marcada «a confirmar por parecer».
- [ ] **Custo e observabilidade** — `consent_notice_sent_total`, `consent_accepted_ratio`, `consent_optout_total`.
- [ ] **Migrações reversíveis** — `downgrade` testado (`consent_event` é aditivo).

### Handoff para Claude Code

```text
És o executor do ticket KAM-022 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-022), docs/tecnica/10_Onboarding_Governanca.md (§7) e
docs/tecnica/06_Dados_Eventos_Analytics.md (§7.3). Objectivo: consentimento no 1.º contacto (ADR-010).
- ConsentGate antes do AGR: sem consent_event válido, envia o aviso com 3 botões e não invoca o AGR.
- consent_event append-only com contact_id uuid, text_version, evidence_hash; consent_texts versionados; vista consent_actual.
- «PARAR» regista a revogação de marketing, pausa a conversa (KAM-018) e confirma; marketing só com opt-in separado.
- Emite consent.recorded e consent.withdrawn pelo outbox, sem texto nem telefone. O texto jurídico é «a confirmar por parecer».
Não expandas escopo: ToS/DPA da PME (KAM-090), direitos do titular (KAM-070).
Testes: máquina de estados, propriedade 0 AGR sem consentimento, PARAR, append-only. Abre PR com o template do §7.
```

---

## KAM-023 — Monitorização do free tier de service messages e do método de pagamento da PME

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-015 |
| Bloqueia | KAM-081, KAM-083, KAM-094, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§7.1, §8.4, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1), `../docs/tecnica/00_Arquitectura_Solucao.md` (§9, §11), ADR-018 |

### Contexto

Factos CONFIRMADOS (E1 §1): desde 2026-10-01 só as primeiras 1.000 *service messages* **entregues** por número e mês são grátis (reinício às 00:00 no fuso da conta), depois 0,004 USD; sem método de pagamento na conta a Meta entrega as do *free tier* mas **deixa de entregar** depois; falha silenciosa a vigiar nos estados `failed`. Alvo do doc 00: alertas aos 80% (800). **NÃO VERIFICADO:** o fuso exacto da conta Meta, como o webhook marca as mensagens dentro do *free tier* (apenas `pricing.type` das *utility* na janela está descrito) e o código de erro da falta de método de pagamento. A pergunta sobre este código deve acrescentar-se ao pacote de KAM-101.

### Objectivo

Contar mensagens *service* entregues por canal e mês, alertar aos 800 e aos 1.000, estimar o custo acima do limite e detectar a provável falta de método de pagamento por falhas de entrega, alimentando o painel de custos.

### Critérios de Aceitação

- [ ] `tenant_channels.free_tier_used` e `free_tier_month` contam mensagens de categoria *service* com estado `delivered` por `phone_number_id`; 1.200 estados sintéticos → contador 1.200.
- [ ] Idempotência: estados duplicados do mesmo `wamid` não contam duas vezes (3 repetições, contador +1).
- [ ] Alertas: 1 aviso ao atingir 800 (80%) e 1 aos 1.000, sem repetição no mesmo mês; reinício do contador à meia-noite do fuso configurado do canal (`Africa/Luanda` por omissão; reconfirmar contra a primeira factura da Meta).
- [ ] Estimativa de custo `max(0, n − 1000) × 0,004 USD` lida de `config/meta_rates.yaml`: 1.200 mensagens → 0,80 USD; exposta como `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}`.
- [ ] Detecção: depois de ≥ 1.000 entregues no mês, uma taxa de estados `failed` acima do limiar (proposta: 20% em 20 mensagens) gera alerta «possível método de pagamento ausente ou inválido» ao dono e a operações; cada código de erro visto é guardado em `meta_error_codes_seen` (para identificar o código concreto, NÃO VERIFICADO).
- [ ] O alerta marca o canal com `motivo_restricao='payment_method'` e dispara `channel.updated`; remover o motivo exige estado `delivered` posterior ou limpeza manual registada.
- [ ] Reconciliação (critério de saída): ao fim de 1 mês real, o contador interno vs `pricing.billable` agregado diverge ≤ 2% (proposta) e o resultado é registado no ticket; discrepâncias sobem a KAM-101.
- [ ] Os valores alimentam KAM-081 sem recalcular: métricas por tenant e canal, sem conteúdo.

### Detalhes Técnicos

- **Componentes:** ChannelAdapter/metering (consumo dos estados de KAM-015), OBS (alertas), CHR (marca de restrição).
- **Fonte de contagem:** estados com `pricing.category = service` e `status = delivered`; o campo `pricing.billable` é registado mas não se confia nele para decidir o *free tier* até a reconciliação; mensagens enviadas pela app do dono em coexistência não contam (não são Cloud API).
- **Tarifas:** `config/meta_rates.yaml` (Rest of Africa, efectivas 2026-10-01: *service* 0,004; *utility* 0,004; *marketing* 0,0225; *authentication* 0,004; CONFIRMADO, perecível, revisão trimestral — 1 Jan, 1 Abr, 1 Jul, 1 Out, a confirmar no calendário da Meta).
- **Gate de activação:** a verificação de que o método de pagamento existe no Billing Hub é KAM-093; aqui só a detecção em *runtime*.
- **Fora de âmbito:** dashboard de unit economics (KAM-081), cobrança à PME, runbook de cartão (KAM-083).

### Testes Requeridos

- Unit: contagem, reinício mensal com relógio fixo (fronteira de mês no fuso `Africa/Luanda`), custo.
- Integração com fixtures do simulador: 1.200 estados, duplicados, rajada de `failed`.
- Isolamento: contadores de A não afectam B; X-03 sobre `meta_error_codes_seen`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada; tarifas com data de leitura da evidência; Conventional Commits.
- [ ] **Isolamento de tenant** — contadores por canal/tenant com RLS e teste cruzado.
- [ ] **Idempotência** — contagem por `wamid` com teste de repetição.
- [ ] **Privacidade** — métricas e alertas sem telefone nem conteúdo.
- [ ] **Custo e observabilidade** — as métricas acima nascem com o código (ADR-018).
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-023 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-023), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§8.4, §14) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§1). Objectivo: free tier de service messages e método de pagamento.
- Conta service/delivered por canal e mês (idempotente por wamid); alertas aos 800 e 1.000; reinício à meia-noite do fuso do canal.
- Custo estimado = max(0, n − 1000) × 0,004 USD a partir de config/meta_rates.yaml; métricas por tenant.
- Heurística de falta de método de pagamento: taxa de failed após 1.000 entregues; guarda os códigos vistos
  (o código concreto é NÃO VERIFICADO); marca motivo_restricao e emite channel.updated.
- Regista a reconciliação com a factura real num mês de Piloto (critério de saída).
Não expandas escopo: dashboard (KAM-081), gate de activação (KAM-093), runbooks (KAM-083).
Testes: contagem, fronteira de mês, duplicados, rajada de failed. Abre PR com o template do §7.
```

---

## KAM-024 — Simulador de webhooks Meta e testes de contrato com número de teste

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013 |
| Bloqueia | KAM-078, KAM-084 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.4, §5.4, §16), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§6, §7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), `specs/01_Engineering_Standards_e_Handoff.md` §4 (gates 7 e 15) |

### Contexto

O gate 7 exige contratos de webhooks Meta testados no CI e o gate 15 um *smoke* ponta a ponta com o número de teste. O ambiente `dev` usa *mocks* do webhook com corpo assinado com segredo de teste; `staging` usa o **número de teste** da app Meta (WABA de teste) e, nas semanas 1–3, 1–3 números +244 reais para o spike de coexistência. O número de teste **não prova** coexistência nem Embedded Signup em condições reais (`../docs/tecnica/09` §6). Entradas e campos a cobrir: os 11 tipos de §5.4 e os 11 campos de §4.4 de `../docs/tecnica/01`.

### Objectivo

Construir o simulador (biblioteca + CLI) que produz webhooks Meta assinados e um servidor Graph falso com cenários, mais a suite de contrato *offline* (obrigatória em cada PR) e *online* (nocturna contra o número de teste de *staging*).

### Critérios de Aceitação

- [ ] `tools/meta-sim` gera, a partir de uma semente, payloads byte-idênticos (determinismo) para: `text`, `audio`, `image`, `document`, `location`, `interactive` (`button_reply`, `list_reply`), `order`, `reaction`, `sticker`, `unsupported`, `statuses` (`sent`, `delivered`, `read`, `failed`, com `pricing`) e `history`.
- [ ] Cobre os 11 campos de webhook: `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `account_update` (6 motivos), `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update`; um relatório de cobertura prova ≥ 1 *fixture* e ≥ 1 teste por tipo e campo (100%).
- [ ] Casos adversos: assinatura inválida, JSON inválido assinado, corpo duplicado, mesma mensagem em dois corpos, ordem trocada, lote de várias `entry`, `wa_id` omitido (apenas BSUID/`username`), `phone_number_id` desconhecido.
- [ ] A assinatura gerada é aceite pelo GWY de KAM-013 (ida e volta) e rejeitada quando o corpo muda 1 byte; o segredo de teste nunca coincide com um segredo de `staging`/`prod` (verificação de configuração).
- [ ] Servidor Graph falso com cenários programáveis: envio 200, 130429 (N vezes), 131049, 5xx, mídia, submissão de templates, troca de *code*, subscrições; usado por KAM-015, 016, 017 e 020.
- [ ] Modo de re-entrega: reenvia o mesmo webhook com *backoff* exponencial comprimido (7 dias simulados em ≤ 1 min) para provar idempotência.
- [ ] Ferramenta de captura e saneamento: converte um webhook real em *fixture* substituindo identificadores por valores fictícios; recusa gravar se detectar um número que não pertença à lista de números fictícios; o repositório fica com 0 telefones reais (scan).
- [ ] Suite *offline* corre no gate 7 em ≤ 5 min (proposta); suite *online* corre 1× por noite no número de teste de *staging* e produz um relatório que compara a estrutura real com os schemas das *fixtures* (evidência de 1 execução verde em `docs/evidencia/KAM-024.md`).
- [ ] A suite *online* não é bloqueante de PR mas é de *release* (gate 15 em KAM-078); falha da Meta/credenciais gera alerta, não falso verde.

### Detalhes Técnicos

- **Componentes:** GWY (consumidor), todo o canal (fixtures), OBS. Pacote `tools/meta-sim` (TS) com schemas JSON dos payloads derivados da documentação e validados contra capturas reais.
- **Ambientes (`../docs/tecnica/09` §6):** `dev` com *mocks*; `staging` com número de teste da app Meta de *staging* e chaves distintas das de `prod`; coexistência e ES v4 só com número +244 real (fora desta suite).
- **Limites conhecidos:** o *timeout* exacto do webhook e o *pair rate limit* são NÃO VERIFICADOS (L2); o simulador não os inventa e expõe-nos como parâmetros configuráveis.
- **Segurança:** os telefones fictícios usam um intervalo reservado definido em `tools/meta-sim/fake_numbers.yaml`; nenhum token real no repositório (scan KAM-002).
- **Fora de âmbito:** *smoke* completo de CI/CD e deploy (KAM-078), mocks do facilitador de pagamento (EPIC-05).

### Testes Requeridos

- Unit: determinismo por semente, assinatura, saneamento de capturas.
- Contrato *offline*: todas as *fixtures* contra o GWY de KAM-013 e os tratadores de KAM-014/015/017/021.
- Contrato *online*: 1 execução real no número de teste (mensagem, estado, template) com relatório.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-024.md`).
- [ ] Código revisto por ≥ 1 revisor; testes verdes.
- [ ] Documentação actualizada (`docs/meta-sim.md`: como gerar *fixtures*, como correr o contrato *online*); Conventional Commits.
- [ ] **Privacidade** — 0 telefones reais ou dados pessoais em *fixtures*; capturas saneadas.
- [ ] **Sem segredos** — segredos de teste distintos dos de `staging`/`prod`; scan limpo.
- [ ] **Dependências** — versões fixadas; licenças permitidas.
- [ ] O gate 7 do CI executa a suite *offline* e falha o build.

### Handoff para Claude Code

```text
És o executor do ticket KAM-024 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-024), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4.4, §5.4, §16)
e docs/tecnica/09_Topologia_Operacao_Escala.md (§6, §7). Objectivo: simulador de webhooks Meta e testes de contrato.
- tools/meta-sim: payloads assinados e determinísticos para os 11 tipos de entrada e os 11 campos de webhook, com
  casos adversos (assinatura, JSON, duplicados, ordem, wa_id omitido, canal desconhecido) e modo de re-entrega.
- Servidor Graph falso com cenários (200, 130429, 131049, 5xx, mídia, templates, troca de code, subscrições).
- Captura e saneamento de payloads reais; números fictícios de fake_numbers.yaml; recusa números reais.
- Suite offline no gate 7; suite online nocturna no número de teste de staging, com relatório (não bloqueia PR).
Não expandas escopo: sem smoke de deploy (KAM-078), sem mocks de pagamento.
Testes: determinismo, ida e volta com o GWY, cobertura 100% de tipos e campos, 1 execução online. Abre PR com o template do §7.
```

---

## KAM-115 — Aviso ao dono por canal alternativo (e-mail ou push)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-017, KAM-021, KAM-023, KAM-116 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/10_Onboarding_Governanca.md` (§6.4, §13), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.5, §11.4, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §2), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§1, Art. 19.º), `../docs/tecnica/00_Arquitectura_Solucao.md` (§13.3, D10), ADR-001, ADR-008, ADR-010 |

### Contexto

Avisar o dono pelo canal que falhou é inútil. Factos CONFIRMADOS (E1 §2, §1): `PARTNER_REMOVED` (seis motivos, entre eles `PRIMARY_INACTIVITY`, ~14 dias sem abrir a app) desliga a coexistência; sem método de pagamento a Meta deixa de entregar *service messages* depois das 1.000 grátis. `../docs/tecnica/01` §10.5 e §14 e `../docs/tecnica/10` §6.4 mandam avisar o dono «por canal alternativo», mas nenhum ticket o construía (lacuna R16 deste epic). Os emissores existem: KAM-017 (`desligado` e `channel.updated`; aviso aos 10 dias), KAM-021 (`restrito` por qualidade RED) e KAM-023 (`motivo_restricao='payment_method'`). O canal alternativo não pode ser o número da loja (`../docs/tecnica/01` §11.4) nem um número operacional da KAMBÁ: D10 e KAM-101 condicionam esse número (o tenant `platform` está vedado até D2), pelo que este ticket **não o assume**. Canais: e-mail e notificação do painel/HND (push); o SMS fica atrás da interface `SmsProvider` de KAM-116 e só se activa quando esse contrato existir. O aviso é comunicação de serviço ao dono, não marketing; a base legal e a finalidade do contacto do dono são *(a confirmar por parecer, KAM-104)*.

### Objectivo

Consumir os eventos de falha ou risco do canal e enviar ao dono um aviso idempotente por e-mail e por notificação do painel, com limites de frequência, sem conteúdo de clientes e sem usar o WhatsApp.

### Critérios de Aceitação

- [ ] Cinco gatilhos geram aviso: `channel.updated` com `desligado` (cada um dos 6 motivos de `PARTNER_REMOVED`), `channel.inactivity_warning` (10 dias), `restrito` por qualidade, `motivo_restricao='payment_method'` e HND indisponível > 5 min (*proposta*); cada um com texto próprio e o passo seguinte (reconectar, abrir a app, adicionar cartão). Um gatilho fora da lista não envia nada.
- [ ] Idempotência por `hash(tenant_id, gatilho, episódio)`: o mesmo evento 3× (e re-entregue pela DLQ) produz 1 aviso; um novo episódio depois de resolvido produz outro.
- [ ] Latência do evento ao aviso entregue ao fornecedor de e-mail ≤ 5 min p95 (*proposta*), medida com relógio acelerado e fornecedor falso.
- [ ] Limites de frequência (*propostas*): ≤ 1 aviso por (tenant, gatilho) em 24 h e ≤ 3 por tenant/dia; lembretes às 24 h e 72 h se o estado persiste, depois pára e abre tarefa a T2; 500 eventos/hora de um só tenant enviam ≤ 3.
- [ ] Conteúdo por allowlist de modelos (1 por gatilho): nome da loja, estado, hora, passos e ligação ao painel sem token nem identificador pessoal no URL; 0 telefones, `contact_id`, BSUID ou texto de clientes (varrimento X-11 sobre 200 avisos gerados).
- [ ] O dono tem ≥ 1 contacto alternativo verificado por ligação de confirmação (o e-mail é captado em KAM-086); tenant `ativo` sem contacto verificado gera alerta a T2 e a métrica `owner_alt_contact_missing`; alvo ≥ 95% dos tenants `ativo` com contacto verificado (*proposta*).
- [ ] Falha de entrega (*bounce*, rejeição) marca o contacto como inválido, tenta o painel e abre tarefa a T2; nenhum aviso se perde em silêncio (falha injectada).
- [ ] Nenhum adaptador de envio WhatsApp neste módulo (teste de configuração); o fornecedor de e-mail consta do inventário de subprocessadores (KAM-069) com `apd_ref`, ou fica `pendente` e bloqueia `prod` (ADR-008).

### Detalhes Técnicos

- **Componentes:** CHR (subscrição de eventos), HND (notificação do painel), OBS. Porta `OwnerNotifier.notify(tenant_id, gatilho, episodio, params)` com adaptadores `EmailNotifier`, `PanelNotifier` e `SmsNotifier` (desligado até KAM-116).
- **Registo de envio:** tabela `owner_notices` (`notice_id`, `tenant_id`, `gatilho`, `episodio`, `canal`, `estado`, `criado_at`, `entregue_at`) com RLS e sem corpo; a tabela `owner_notices` e o evento `channel.inactivity_warning` (de KAM-017) não constam do dicionário §3: a emenda é condição de merge (gate 3b de KAM-111).
- **Janela do aviso preventivo:** os 10 dias vêm da heurística de `../docs/tecnica/01` §10.5 (sem *echo* e sem acesso ao painel), a calibrar no Piloto.
- **Fora de âmbito:** adaptador SMS (KAM-116), número operacional da KAMBÁ (D10, KAM-101), runbooks (KAM-083), avisos de cobrança ao dono (KAM-058).

### Testes Requeridos

- Unit: idempotência, limites de frequência com relógio fixo, allowlist de modelos.
- Integração com fornecedor falso e o simulador de KAM-024 (6 × `account_update`, qualidade RED, falha de pagamento); *bounce*.
- Isolamento: eventos de A não avisam o dono de B (X-03 sobre `owner_notices`); privacidade: X-11 sobre os avisos.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/avisos-ao-dono.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — RLS em `owner_notices` e teste cruzado.
- [ ] **Idempotência** — chave por episódio com teste de repetição.
- [ ] **Privacidade** — avisos sem dados de clientes; endereço do dono só em cifra e nunca em logs.
- [ ] **Custo e observabilidade** — `owner_notice_sent_total{gatilho,canal}`, `owner_notice_latency_s`, `owner_alt_contact_missing`.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-115 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-115), docs/tecnica/10 (§6.4, §13) e docs/tecnica/01 (§10.5, §14).
Objectivo: avisar o dono por e-mail e painel quando o canal falha ou está em risco.
- Gatilhos: channel.updated (desligado), channel.inactivity_warning, restrito, motivo_restricao='payment_method', HND em baixo.
- Idempotente por (tenant, gatilho, episódio); ≤ 1 aviso/gatilho/24 h e ≤ 3/dia; lembretes às 24 h e 72 h.
- Nunca pelo WhatsApp, nem pelo número da loja, nem por um número operacional da KAMBÁ (D10): não o assumas.
- Sem dados de clientes no aviso. SMS só via SmsProvider de KAM-116, desligado até existir contrato.
Não expandas escopo: sem SMS, sem régua de cobrança (KAM-058), sem runbooks (KAM-083).
Testes: idempotência, limites, bounce, isolamento, X-11. Abre PR com o template do §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| # | Risco / item | Estado | Decisão ligada | Mitigação / critério de saída |
|---|---|---|---|---|
| R1 | Coexistência indisponível ou instável para números +244 (móveis e fixos) | NÃO VERIFICADO (L1; E1 §2) | D5; KAM-100; H3 | KAM-017 só fixa o modo predefinido depois do relatório de KAM-100; alternativa `cloud_only` com número novo |
| R2 | Timeout exacto do webhook, *retry* antes das 7 dias e *pair rate limit* | NÃO VERIFICADO (L2; E1 §5) | KAM-101 | Alvo interno 200 em < 500 ms; parâmetros configuráveis; pergunta 12 de E1 à Meta |
| R3 | Aceitação de documentos angolanos na Business Verification, prazo e «Access Verification» | NÃO VERIFICADO (L3) | D5; KAM-102 | KAM-016 depende de `ext:KAM-102`; plano B BSP com cotação a 2 BSPs |
| R4 | Método de pagamento local (Kz) no Billing Hub; PMEs sem cartão USD/EUR | NÃO VERIFICADO (L4) | D5, D9 | Gate de activação (KAM-093); alerta aos 800 (KAM-023); Multi-Partner Solution como alternativa |
| R5 | Classificação «AI Provider» e agregador permitido | NÃO VERIFICADO (L5) | D2; ADR-011 | Fluxo B diferido (guarda no CHR, KAM-014); persona limitada a comércio; pergunta 2 de E1 |
| R6 | *Echo* de mensagens enviadas por API e sua latência | NÃO VERIFICADO (L6) | KAM-100 | Comparação com `outbound_messages.wamid`; evidência de ≥ 30 *echoes* reais (KAM-018) |
| R7 | O token do *agent bot* do Chatwoot consegue passar `pending → open`; versão de ES do Chatwoot | NÃO VERIFICADO (L7) | ADR-001 (Desenho I) | Spike de 1 dia em KAM-019; plano B com utilizador-serviço; Desenho I não usa o ES do Chatwoot |
| R8 | Verificação por SMS (Unitel/Africell) e fixos por voz | NÃO VERIFICADO (L10) | KAM-093 | Fluxo de voz no pré-voo; medir na Fase 1 |
| R9 | Fuso do *free tier*, marcação dos primeiros 1.000 nos estados e código de erro da falta de pagamento | NÃO VERIFICADO | KAM-101 | Contador próprio + reconciliação mensal (KAM-023); acrescentar a pergunta ao pacote de KAM-101 |
| R10 | Base legal do consentimento (contrato vs consentimento), do aviso e do uso do histórico sincronizado; papel da KAMBÁ | A confirmar por parecer (E3) | D9; KAM-104 | Texto versionado e prova; histórico não persistido no Piloto (KAM-017) |
| R11 | Termos da Meta §4.7 sobre ML e dados da plataforma (leitura automática do texto PT) | CONFIRMADO com ressalva (L15) | ADR-018 | Nada de treino com conversas; confirmar texto EN antes de uso contratual |
| R12 | Alojamento de conversas, Chatwoot e mídia sem procedimento APD; CDN/WAF e TLS como subprocessadores | Decisão aberta | D1, D12; ADR-008 | Dados sintéticos fora de `prod`; gate de transferência em KAM-069; nenhum dado real antes de D1 |
| R13 | Limite de 10 clientes/7 dias até verificação completa | CONFIRMADO | D5 | Contador `es_onboardings_7d` (KAM-016); lista de espera (KAM-095) |
| R14 | Divergências documentais: RED → `suspenso` (`../docs/tecnica/10` §6.4) vs `restrito` (doc 00, doc 01); três tabelas de consentimento; `contact_id` como `bytea` em `consent_event` | Conflito documental | ADR-010 | Decisões em KAM-021 e KAM-022; propagar a `../docs/tecnica/10`, `01` e `06` |
| R15 | Dependências em falta no backlog mestre: KAM-016 sem KAM-010; KAM-014 sem KAM-004 nem KAM-006; KAM-018, KAM-021 e KAM-022 sem dependentes | Defeito do backlog | — | Sinalizado ao responsável de produto; entretanto usar `SecretProvider` de ambiente e TTL de cache |
| R16 | Sem ticket para avisar o dono por canal alternativo (e-mail/push) em `PARTNER_REMOVED`, inactividade ou falha de pagamento Meta | Coberta por **KAM-115** (consolidação) | — | KAM-017/023 emitem eventos; KAM-115 entrega o aviso por canal alternativo |

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
| 1.0 | Outubro 2026 | Emissão inicial: KAM-013 a KAM-024 (GWY, CHR, outbound, Embedded Signup v4, coexistência, handoff, mídia, qualidade, consentimento, simulador); KAM-115 (aviso ao dono por canal alternativo) acrescentado na consolidação. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-145: os **24** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |

# Desenho técnico detalhado da plataforma (nível engenharia)

Aprofundamento de `10-arquitetura-plataforma-holistica.md`. A doc 10 diz **o quê**; esta diz
**como, exatamente**: esquemas, contratos, grafos de agentes, fluxos de sequência, deploy e escala.
Público-alvo: os 2 devs que vão construir. Stack-base definida na `08-arquitetura-tecnica-v2.md`.

---

## 1. Topologia de serviços (MVP em produção)

| Serviço | Tecnologia | Responsabilidade | Estado |
|---|---|---|---|
| `gateway` | Node 20 + Hono, Docker | webhooks Meta/ProxyPay (verificação, idempotência), REST interna, auth JWT | stateless |
| `agent-runtime` | Python 3.12 + LangGraph, workers | todos os agentes IA (módulos), tools, handoff | stateful (fila) |
| `chatwoot` | v4.18 (Rails + Sidekiq) | consola humana, 1 conta/PME | stateful |
| `medusa` | Medusa v2 + Mercur | produtos, encomendas, stock, reservas | stateful |
| `storefront` | Next.js 15 | vitrine SEO, painel light da PME | stateless |
| `postgres` | 16 + pgvector + pg_trgm | registo plataforma + Medusa + LangGraph checkpoints | primário |
| `redis` | 7 | BullMQ (event bus MVP), cache, rate limits | — |
| `n8n` | self-host | automações back-office (relatórios, réguas simples) | — |
| `langfuse` | self-host v3 | traces, custos por tenant, evals | — |
| `litellm` | proxy Docker | gateway LLM, virtual keys por tenant | stateless |
| `minio` | S3-compatível | fotos, documentos, áudio | — |
| `nominatim` | extracto Angola | reverse geocode | — |
| `typebot` | builder+viewer | fluxos determinísticos, onboarding | stateful |

MVP: 1 VPS 8vCPU/32GB (ou 2× 4/16) corre tudo em docker-compose. Cloudflare à frente (TLS, WAF,
rate limit). Backups: WAL archiving → MinIO (PITR 7 dias) + snapshot diário.

Regra de entrada: **todo o tráfego externo entra pelo `gateway`** (único com TLS público). Meta,
ProxyPay e browsers nunca falam diretamente com outros serviços.

## 2. Modelo de dados — schema `platform` (Postgres)

Medusa mantém o seu próprio schema (produtos/encomendas/stock). A plataforma liga-se por
`tenant.medusa_sales_channel_id` e espelha o mínimo necessário. DDL essencial:

```sql
CREATE TABLE tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tipo          text NOT NULL CHECK (tipo IN ('pme','courier','reseller','agent','platform')),
  nome          text NOT NULL, nif text, telefone text NOT NULL,
  zona          text, gps point, plus_code text,
  plano         text NOT NULL DEFAULT 'free',
  estado        text NOT NULL DEFAULT 'onboarding',
  medusa_channel_id text,              -- link ao Medusa/Mercur
  chatwoot_account_id int,             -- 1 conta Chatwoot por tenant
  litellm_key_id     text,             -- virtual key p/ metering
  waba_id       text, phone_number_id text,  -- NULL em PME light
  verificado_at timestamptz,
  criado_at     timestamptz DEFAULT now()
);

CREATE TABLE entitlements (
  tenant_id uuid REFERENCES tenants, modulo text NOT NULL,
  limites jsonb NOT NULL DEFAULT '{}',           -- {"msgs_ai_mes": 100}
  ativo boolean DEFAULT true,
  PRIMARY KEY (tenant_id, modulo)
);

CREATE TABLE orders_mirror (             -- espelho mínimo das encomendas Medusa
  id uuid PRIMARY KEY, medusa_order_id text UNIQUE NOT NULL,
  tenant_id uuid NOT NULL, origem text NOT NULL CHECK (origem IN ('pme','plataforma')),
  cliente_msisdn text NOT NULL, total_kz int NOT NULL,
  estado text NOT NULL,                  -- criada|paga|expirada|entregue|cancelada
  pagamento_ref text, pagamento_estado text,
  reseller_id uuid, courier_id uuid,
  criado_at timestamptz DEFAULT now(), pago_at timestamptz, entregue_at timestamptz
);

CREATE TABLE reviews (
  id uuid PRIMARY KEY, order_id uuid UNIQUE REFERENCES orders_mirror, -- 1 review por pedido pago
  nota smallint CHECK (nota BETWEEN 1 AND 5), texto text,
  criado_at timestamptz DEFAULT now()
);

CREATE TABLE assistant_queries (         -- o ativo de dados (sinal de procura)
  id bigserial PRIMARY KEY,
  msisdn_hash bytea NOT NULL,            -- HMAC, nunca texto claro
  canal text NOT NULL,                   -- plataforma|pme
  texto_norm text, categoria text, zona text,
  resolveu boolean, handoff boolean,
  lat double precision, lng double precision,
  criado_at timestamptz DEFAULT now()
) PARTITION BY RANGE (criado_at);        -- partições mensais

CREATE TABLE payment_events (            -- ledger imutável anti-fraude
  id bigserial PRIMARY KEY,
  provider text NOT NULL, referencia text NOT NULL,
  order_id uuid, valor_kz int NOT NULL,
  estado text NOT NULL,                  -- emitida|paga|expirada|falhada
  callback_hmac_ok boolean NOT NULL,     -- SÓ true muda estado para paga
  payload jsonb NOT NULL, criado_at timestamptz DEFAULT now(),
  UNIQUE (provider, referencia)
);

CREATE TABLE events_outbox (             -- transactional outbox → BullMQ
  id bigserial PRIMARY KEY, tipo text NOT NULL, payload jsonb NOT NULL,
  publicado_at timestamptz, criado_at timestamptz DEFAULT now()
);
```

Regras duras: (1) `orders_mirror` só transita para `paga` via consumer do evento
`payment.confirmed` com `callback_hmac_ok=true` — nenhum endpoint aceita comprovativo;
(2) `assistant_queries` guarda msisdn com HMAC (Lei 22/11; finalidade declarada no consentimento);
(3) todo o DELETE é soft (`estado`) — o histórico alimenta o Kambá Score.

## 3. Contratos de eventos (event bus)

Envelope único, versionado, idempotente:

```json
{
  "id": "evt_01J…", "tipo": "payment.confirmed", "versao": 1,
  "tenant_id": "uuid", "trace_id": "langfuse-trace",
  "ocorrido_em": "2026-11-02T14:03:11Z",
  "payload": { "order_id": "uuid", "referencia": "102345678", "valor_kz": 245000 }
}
```

Catálogo inicial (produtor → consumidores):

| Evento | Produtor | Consumidores |
|---|---|---|
| `order.created` | Pedidos | Pagamentos (emitir ref), Stock (reservar 72h), Analytics |
| `payment.confirmed` | adapter pagamentos | Pedidos (transição), Cobranças (parar régua), Score, Notificações |
| `order.expired` | scheduler (72h) | Stock (libertar), Cobranças (régua recuperação), Analytics |
| `order.delivered` | Logística | Reputação (pedir review em +2h), Revendedores (comissão elegível) |
| `review.created` | Reputação | Ranking do índice, Analytics |
| `query.unresolved` | agent-runtime | Sinal de procura (agregação), Ops (cobertura) |
| `tenant.activated` | Onboarding | Provisioning (Chatwoot, LiteLLM, Medusa channel) |
| `stock.low` | Medusa subscriber | Vendedor AI (aviso), Compras AI |

Semântica: **at-least-once**; consumidores idempotentes por `evento.id` (tabela
`events_consumed(consumer, event_id)`). DLQ após 5 retries + alerta ops. Versionamento: campo
`versao`; consumers ignoram tipos/versões desconhecidos (forward-compatible).

## 4. Agent runtime por dentro

### 4.1 Estrutura

Serviço Python único com **registo de agentes** (grafo LangGraph por módulo × persona):

```
AGENTS = {
  "vendedor":     build_vendedor_graph(),     # lojas (Fluxo A)
  "assistente":   build_assistente_graph(),   # número plataforma (Fluxo B)
  "rececionista": build_rececionista_graph(),
  "orcamentos":   build_orcamentos_graph(),
  ...
}
```

Resolução por mensagem: `phone_number_id → (tenant, persona)` (tabela `tenant_channels`) →
carrega grafo + estado (`langgraph-checkpoint-postgres`, key = `thread_id = msisdn_hash+tenant`).

### 4.2 O grafo do Vendedor (exemplo canónico)

```python
g = StateGraph(ConversaState)
g.add_node("filtrar_input", guardrail_input)          # injeção? abuso? → saída segura
g.add_node("stt", whisper_se_voz)                     # áudio → texto (+flag confiança)
g.add_node("classificar", router_nano)                # intenção: produto|preco|compra|info|humano
g.add_node("buscar", rag_catalogo)                    # pgvector+trgm scoped tenant
g.add_node("ferramentas", ToolNode([get_price_stock, criar_pedido, ver_horario, book_slot]))
g.add_node("responder", llm_mini_com_citacao)         # resposta c/ refs às tool calls
g.add_node("validar_citacao", validador_numeros)      # regex vs outputs reais das tools
g.add_node("handoff", interrupt_antes_de_humano)      # LangGraph interrupt → Chatwoot

g.add_edge(START, "filtrar_input")
g.add_conditional_edges("classificar", rota, {
  "produto": "buscar", "preco": "buscar", "compra": "ferramentas",
  "info": "ferramentas", "humano": "handoff"})
g.add_edge("buscar", "ferramentas")
g.add_edge("ferramentas", "responder")
g.add_conditional_edges("validar_citacao", ok, {True: END, False: "responder"})  # 1 retry → handoff
```

Tools têm escopo duro: toda a tool recebe `tenant_id` do estado (nunca do texto do cliente) e
só lê/escreve dentro do tenant. `criar_pedido` escreve no Medusa via API com idempotency-key
`hash(msisdn+sku+janela_5min)` — clique duplo do cliente não duplica encomenda.

### 4.3 Handoff (protocolo com Chatwoot)

1. Grafo decide handoff → `interrupt()` com payload `{motivo, resumo_llm}`
2. Runtime chama Chatwoot API: conversa → `open`, atribui equipa (dono da PME ou suporte),
   posta nota privada com o resumo
3. Conversa humana decorre no Chatwoot; bot silenciado (`conversation.status != pending`)
4. Humano fecha → webhook Chatwoot → grafo retoma (`Command(resume=...)`) ou arquiva thread

SLA de handoff medido por tenant (métrica: % conversas retomadas <15 min) — alimenta o ranking
de responsividade do assistente (ponto cego 7, ronda 2).

### 4.4 Orçamento de latência e concorrência

Alvo p95: texto 4–8s; voz 6–12s. Workers: 1 processo `agent-runtime` com 4 workers async aguenta
~50 conversas simultâneas (gargalo é a API do LLM, não CPU). Acima disso: escalar workers
horizontais atrás do BullMQ (a fila absorve picos; o WhatsApp tolera segundos).

## 5. Fluxos de sequência críticos

### 5.1 Venda B2 com referência (o fluxo mais importante)

```
cliente → GW(webhook Meta) → fila → runtime(assistente)
  → buscar índice → 3 opções (preço citado do Registo)
cliente escolhe → criar_pedido(Medusa, reserva 72h) → outbox order.created
  → Pagamentos: ProxyPay POST /references (custom_fields.order_id) → ref 9 dígitos ao cliente
  → template utility (dentro da janela 24h = grátis)
[cliente paga no ATM/homebanking — 2 min a 48h]
ProxyPay → GW(callback HMAC) → valida assinatura → payment_events(hmac_ok=true)
  → evento payment.confirmed → Medusa captura → cliente recebe confirmação + Plus Code da loja
  → Logística (se entrega): dispatch §5.2
[sem pagamento em 72h] scheduler → order.expired → liberta stock → Cobranças: régua
  (T+2h lembrete na janela se aberta; T+24h template utility $0,004; T+48h oferta alternativa)
```

Falhas tratadas: callback duplicado (idempotência por referência), pagamento a mais/menos
(`valor_kz` divergente → estado `falhada` + humano), referência expirada → nova referência na
mesma encomenda.

### 5.2 Dispatch logística federada

```
order.paid (com entrega) → consumer Logística:
  1. reverse-geocode pin do cliente (Nominatim) → bairro
  2. couriers ativos na zona, ordenados por (distância Valhalla, rating, carga_atual)
  3. oferta sequencial WhatsApp: 90s para aceitar (Typebot), senão próximo
  4. aceite → estafeta recebe: link maps.google.com/?q=lat,lng + plus code + landmark +
     código de entrega de 4 dígitos
  5. cliente informa o código ao estafeta → estafeta envia código → order.delivered
     (prova de entrega anti-fraude dos dois lados)
```

### 5.3 Onboarding PME (provisioning automático)

```
agente de campo (app Typebot) → POST /tenants → tenant estado=onboarding
evento tenant.activated dispara em paralelo:
  • Medusa: cria sales_channel + merchant (Mercur)
  • Chatwoot: Platform API cria conta + inbox WhatsApp (phone_number_id)
  • LiteLLM: cria virtual key (budget mensal = plano)
  • Entitlements: linhas por módulo do plano
se Fluxo A: embedded signup (browser do agente) → coexistência ativa →
  phone_number_id gravado → primeira mensagem de teste end-to-end
se light: sem WABA própria — catálogo indexado sob o número da plataforma
rollback: falha em qualquer passo → compensação (apaga recursos criados) + retry manual
```

## 6. Ingress Meta e webhooks (detalhes que quebram MVPs)

- Verificação `hub.challenge` + validação `X-Hub-Signature-256` em **todo** o POST
- Resposta 200 em <500ms → processamento sempre assíncrono (fila). Meta reenvia em caso de
  timeout e trata latência alta como falha
- Deduplicação por `message.id` (Meta reentrega) — tabela `msgs_processadas(id)` com TTL 7 dias
- Media: webhook traz media_id → GET autenticado → MinIO → URL interna assinada (nunca URL Meta
  persistida; expiram)
- Envio: respeitar janela 24h (serviço) vs template; registry de templates por nome/idioma com
  estado de aprovação; rate limit por número (quality rating) com backoff
- ProxyPay callbacks: validação HMAC-SHA256 header, rejeição de IPs fora da whitelist + replay
  (timestamp ±5 min)

## 7. Pesquisa híbrida (a query real do índice)

```sql
-- candidatos: semântico ∪ trigram ∪ FTS-pt, depois re-rank
WITH sem AS (
  SELECT id, 1 - (embedding <=> :qvec) AS s FROM products
  WHERE tenant_estado='ativo' ORDER BY embedding <=> :qvec LIMIT 40),
tri AS (
  SELECT id, similarity(nome_norm, :qtxt) AS t FROM products
  WHERE nome_norm % :qtxt LIMIT 40),                -- pg_trgm: "niker"≈"nike"
fts AS (
  SELECT id, ts_rank(fts_pt, plainto_tsquery('portuguese', :qtxt)) AS f
  FROM products WHERE fts_pt @@ plainto_tsquery('portuguese', :qtxt) LIMIT 40)
SELECT p.*, COALESCE(s.s,0)*0.5 + COALESCE(t.t,0)*0.3 + COALESCE(f.f,0)*0.2 AS score,
       r.avg_nota, p.zona
FROM ((SELECT id,s FROM sem) UNION (SELECT id,NULL FROM tri) UNION (SELECT id,NULL FROM fts)) u
JOIN products p USING(id) LEFT JOIN tri ON tri.id=p.id LEFT JOIN fts ON fts.id=p.id
LEFT JOIN v_reputacao r ON r.tenant_id=p.tenant_id
WHERE (:zona IS NULL OR p.zona=:zona) AND p.stock>0
ORDER BY score*0.7 + COALESCE(r.avg_nota,3)/5*0.3 DESC LIMIT 3;
```

Sinónimos PT-AO aplicados antes da query (dicionário por tenant + global, editável por ops).
`v_reputacao` materializada noturna (ou via consumer de `review.created`). Preço/stock **não**
estão no texto indexado — join no momento da resposta.

## 8. Analytics (fase 3, mas o desenho já)

Consumer `analytics` (event bus) → ClickHouse:

```sql
CREATE TABLE events (tipo LowCardinality(String), tenant_id UUID, zona LowCardinality(String),
  categoria LowCardinality(String), resolveu Bool, valor_kz UInt32, ts DateTime64(3))
ENGINE = MergeTree ORDER BY (ts, tipo);
-- sinal de procura: MV agregando query.unresolved por (zona, categoria, dia)
-- índice de preços: MV sobre catálogo+pedidos por (categoria, zona, semana)
```

Kambá Score = job diário: features (ticket médio, taxa de pagamento em 24h, cancelamentos,
reviews, idade da conta) → score 0–1000 exportado via API para o banco parceiro. Modelo inicial:
regras/GBDT (não deep learning) — auditável perante o BNA e o banco.

## 9. Segurança e conformidade técnica

- **Isolamento**: middleware exige `tenant_id` no contexto; CI tem suite de testes cruzados
  (tenant A tenta ler B em todos os endpoints — falha o build se passar)
- **PII**: msisdn com HMAC fora do necessário; logs sem conteúdo de mensagens (só metadados);
  retenção configurável por tenant
- **Segredos**: Doppler/Vault; chaves Meta/ProxyPay por ambiente; rotação trimestral
- **Auditoria**: `audit_log(ator, acao, tenant, payload_hash, ts)` para tudo o que mexe em
  dinheiro/stock/preço — exigência futura de parceiros bancários
- **Abuso**: rate limit por msisdn e por número; deteção de flood → humano; lista de bloqueio

## 10. Deploy, CI/CD e ambientes

- 3 ambientes: `dev` (compose local), `staging` (VPS pequeno, número Meta de teste, sandbox
  ProxyPay), `prod`
- Pipeline: PR → lint+typecheck → unit tests → **suite de isolamento de tenants** → eval PT-AO
  golden (LLM-as-judge, gate: score ≥ baseline) → build imagens → deploy staging → smoke test
  end-to-end (mensagem real no número de teste) → tag → deploy prod (rolling, compose/k8s)
- Migrações: Medusa migrations + Alembic (schema platform) na pipeline; rollback = migração
  reversa obrigatória no PR
- Observabilidade: logs JSON (Loki), métricas (Prometheus+Grafana: msgs/s, custo LLM/tenant,
  % handoff, p95 latência, callbacks falhados), alertas Telegram/Chatwoot ops

## 11. Gargalos e quando atacar

| Gargalo | Limite prático | Resposta quando chegar |
|---|---|---|
| Postgres (registo+vetores) | ~1–2M produtos, ~5k msgs/dia | read replicas; particionar `assistant_queries`; Meilisearch/Qdrant saem do Postgres |
| Chatwoot | ~100k conversas / 40 agentes (8vCPU/32GB) | shard por cluster de PMEs; enterprise só se SLAs forem precisos |
| Meta tiers (nº plataforma) | 250→2k→10k conv/dia | verificação empresarial antecipada; qualidade alta = sobe sozinho |
| BullMQ/Redis | ~10k jobs/min | NATS/Kafka; consumidores já são desacoplados |
| agent-runtime | ~50 conversas simultâneas/processo | workers horizontais (a fila é o balanceador) |
| Langfuse | IO pesado de traces | sampling de traces em volume; retention 30d |

## 12. ADRs (decisões registadas)

| # | Decisão | Status |
|---|---|---|
| 1 | Cloud API oficial + coexistência; não-oficial banido de produção | aceite |
| 2 | LangGraph próprio; Dify/n8n vedados p/ multi-tenant (licença) | aceite |
| 3 | Medusa v2+Mercur como registo de comércio; índice de pesquisa custom | aceite c/ spike |
| 4 | ProxyPay como adapter primário; dinheiro sempre direto na PME | aceite |
| 5 | APIs de LLM até >0,5–1M msgs/mês; LiteLLM desde o dia 1 | aceite |
| 6 | Postgres único (registo+vetores) até limites do §11 | aceite |
| 7 | Preço/stock nunca em embeddings/prompts; validador de citação | aceite |
| 8 | JNB/CPT no MVP; Luanda quando compliance/parceria exigir | aceite |
| 9 | Event bus BullMQ com outbox transacional; Kafka só na escala | aceite |
| 10 | msisdn com HMAC; logs sem conteúdo; consentimento no 1º contacto | aceite |

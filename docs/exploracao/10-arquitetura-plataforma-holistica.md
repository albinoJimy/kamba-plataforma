# Arquitetura de plataforma holística — visão de conjunto

Complemento de `08-arquitetura-tecnica-v2.md`. A doc 08 é a arquitetura **do produto**
(loja no WhatsApp); esta é a arquitetura **da plataforma**: como todos os módulos do
enquadramento (`02-enquadramento-plataforma-angola.md` §2) e as expansões
(`06-expansao-plataforma.md`) partilham a mesma espinha dorsal, sem que cada módulo vire um
sistema à parte. Regra-mestra: **construir primitivas uma vez; módulos são configuração +
agentes sobre elas.**

> 🔧 **Nível seguinte:** o desenho detalhado de engenharia (schemas, contratos de eventos, grafos
> de agentes, fluxos de sequência, deploy, escala) está em `11-arquitetura-detalhada-engenharia.md`.

---

## 1. O mapa: cada módulo é fino, a plataforma é grossa

| Módulo (origem) | O que o módulo tem de próprio | O que herda da plataforma |
|---|---|---|
| Rececionista AI (02) | persona, agenda/regras do segmento | canal WhatsApp, agent runtime, handoff Chatwoot, billing |
| Catálogo AI (02) | pipeline foto→produto | media pipeline, Medusa, índice, LLM gateway |
| Vendedor AI + Pedidos (05/08) | fluxo de venda | tudo acima + pagamentos + reservas |
| Orçamentos AI (02) | comparador + proposta formatada | base de preços/fornecedores, PDF/report service |
| Social AI (02) | calendário editorial, geração de posts | media pipeline, LLM, agendador |
| Arquivo AI (02) | OCR + classificação de documentos | storage, LLM visão, search |
| Compras AI (02) | sourcing, cotação multi-fornecedor | índice de fornecedores, LLM, notificações |
| Cobranças AI (02) | réguas de cobrança | pagamentos abstraction, event bus, templates utility |
| Reputação/selo (06) | reviews por order_id, KYC | event bus (só order paga), identidade |
| Serviços (06) | vertical de agendamento | mesma loja no WhatsApp (produto = serviço) |
| Logística federada (06) | dispatch, cadastro de estafetas | geo stack (pin, Plus Code, Nominatim, Valhalla), notificações |
| Kambá Score (06) | modelo de score, data mart | dados de pedidos/pagamentos, ClickHouse (fase 3) |
| Diáspora (06) | checkout internacional | parceiro de remessas (externo), liquidação PME |
| Compras agrupadas (06) | agregação de demanda | event bus, pagamentos, fornecedores |
| Factura AI (06/08) | front-end conversacional | integração com software certificado AGT (externo) |
| Vitrine SEO (06) | páginas Next.js | dados Medusa + índice, schema.org |
| Revendedores (06) | atribuição + comissões | event bus, payouts (PayPay IBAN), links/IDs |
| Academia (06) | conteúdo | canal WhatsApp, Typebot |
| Sinal de procura / Índice de preços (06) | agregações | analytics sobre `assistant_queries` |
| API aberta (06) | keys, quotas | mesma API interna, tier público |

Conclusão estrutural: ~70% de cada módulo novo já existe quando as primitivas estão de pé.
É isto que torna o roadmap de expansão barato — e é o que este documento desenha.

---

## 2. Arquitetura em 5 camadas

```
┌────────────────────────────────────────────────────────────────────┐
│ L4 CANAIS        números WhatsApp (plataforma + PMEs) · vitrine web │
│                  SEO · grupos de bairro · painel ops · API pública  │
├────────────────────────────────────────────────────────────────────┤
│ L3 MÓDULOS       Rececionista · Vendedor · Catálogo · Orçamentos ·  │
│ (agentes +       Social · Arquivo · Compras · Cobranças · Factura · │
│  serviços finos) Logística · Revendedores · Reputação · Serviços    │
├────────────────────────────────────────────────────────────────────┤
│ L2 PRIMITIVAS    identidade/tenants · entitlements · agent runtime  │
│ (construir 1x)   (LangGraph svc) · LLM gateway (LiteLLM) · event    │
│                  bus · billing/metering · pagamentos (adapters) ·   │
│                  notificações · media pipeline · geo stack · search │
├────────────────────────────────────────────────────────────────────┤
│ L1 DADOS         registo: Medusa/Postgres · descoberta: pgvector +  │
│                  pg_trgm · analytics: ClickHouse (fase 3) · storage │
│                  S3/MinIO · observabilidade: Langfuse               │
├────────────────────────────────────────────────────────────────────┤
│ L0 INFRA         JNB/CPT → Luanda · Cloudflare · Docker → k8s       │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. As 9 primitivas (L2) — o que se constrói uma única vez

### 3.1 Identidade e tenants
1 tenant = 1 PME. Tabela `tenants` central referenciada por tudo (Medusa via merchant link,
Chatwoot via 1 conta/PME, LiteLLM via virtual key, número WhatsApp via `phone_number_id`).
Auth: JWT próprio no MVP (equipa ops + PMEs light); **Keycloak só na escala** se surgirem SSO/
parceiros. Atores: dono da PME, staff da PME, agente de ativação, ops da plataforma, consumidor
(sem conta — identificado pelo msisdn).

### 3.2 Entitlements (planos e módulos)
`tenant_entitlements(tenant_id, modulo, plano, limites)` lida por middleware único. Ativar um
módulo = inserir linha + provisionar recursos (número, conta Chatwoot, chave LiteLLM). O freemium
do modelo Google vive aqui: limites por plano (ex.: 100 conversas AI/mês grátis).

### 3.3 Agent runtime (o coração AI-first)
LangGraph como **serviço único multi-agente**: catálogo de agentes por módulo (rececionista,
vendedor, orçamentos, cobranças...), cada um = grafo com tools declaradas. Partilham: classificador
de intenção, pipeline de voz, guardrails, validador de citação de preço, handoff Chatwoot,
traces Langfuse. Novo módulo = novo grafo + tools, nunca nova infraestrutura.

### 3.4 LLM gateway + metering
LiteLLM (já na doc 08): virtual key por tenant → **custo real por PME e por módulo** (ledger que
alimenta o billing e o pricing). Fallbacks multi-provider. Sem esta primitiva, margens por
módulo são adivinhação.

### 3.5 Event bus
BullMQ/Redis no MVP → NATS ou Kafka na escala. Eventos canónicos:
`order.created/paid/expired/delivered` · `payment.confirmed` · `review.eligible` ·
`query.unresolved` · `stock.low` · `tenant.activated`. É a cola dos módulos: Cobranças subscreve
`order.expired`, Reputação subscreve `order.delivered`, Kambá Score subscreve `payment.confirmed`,
Sinal de procura subscreve `query.unresolved`.

### 3.6 Billing e cobrança da plataforma às PMEs
Assinaturas + uso: a própria plataforma cobra as PMEs **com a mesma primitiva de pagamentos**
(§3.7) — referência mensal por PME, reconciliada server-side. Metering = entitlements (limites)
+ ledger LiteLLM (custo) → factura (via parceiro AGT certificado, nunca motor próprio).

### 3.7 Pagamentos (abstração de adapters)
Interface única `PaymentProvider` (createCharge, status, refund, payout) com adapters:
ProxyPay (refs + MCX Express) → AppyPay → PayPay África (KWiK QR + payouts IBAN) → BitPay.ao
(pós-certificação). Regra imutável: estado só muda por callback assinado; liquidação direta na
conta da PME. **Payouts** (revendedores, motoboys, agentes) entram na fase 2 via PayPay
`transfer_to_card` — mesma primitiva, outra direção.

### 3.8 Media pipeline
Foto/documento → S3/MinIO → processamento (Photoroom/remove.bg para produtos; OCR para Arquivo
AI; transcodificação de áudio para Whisper) → CDN (Cloudflare). Fila dedicada no event bus.

### 3.9 Geo stack
Pin WhatsApp + Plus Code + landmark (já na doc 08) + Nominatim self-host + **Valhalla** (fase 2,
dispatch de motoboys). Primitiva independente porque serve Loja, Logística federada e o
assistente ("perto de mim").

---

## 4. Os módulos (L3) e o que cada um adiciona

**Comércio core (piloto)** — Vendedor AI, Catálogo AI, Pedidos/Cobranças, Reputação: já detalhados
na doc 08. São a prova de fogo das primitivas.

**Serviços & agendamento (fase 1–2)** — produto = serviço com agenda (slots por profissional);
o mesmo Vendedor AI ganha tool `book_slot`. Canalizadores, salões, clínicas. Sem inventário:
reserva vira bloqueio de horário, não de stock.

**Orçamentos AI (fase 2)** — consome a base de preços/fornecedores (primitiva de dados) + gera
proposta PDF; fluxo "quero comprar" da doc 06 é a versão consumidor deste módulo.

**Cobranças AI (fase 2)** — réguas automáticas sobre `order.expired`/`payment.pending`:
lembretes utility na janela, escalonamento, relatório ao dono. Transforma referências não pagas
em vendas recuperadas — ROI mais fácil de demonstrar a uma PME.

**Factura AI (fase 2)** — front-end conversacional ("factura 45 mil à Empresa X") sobre API de
software **já certificado AGT** (Gestwin/SIGESC/Cacimbo). Gancho regulamentar até 2027.

**Social AI (fase 2)** — calendário + geração de posts + agendamento; consome media pipeline e
LLM; entrega no WhatsApp do dono para aprovação (human-in-the-loop editorial).

**Arquivo AI (fase 2–3)** — scanner → media pipeline (OCR) → classificação → pastas pesquisáveis
(search primitiva). Único módulo com componente físico (scanner).

**Logística federada (fase 2)** — estafeta = tenant tipo `courier` com zona/preço; dispatch =
`order.paid` → match por bairro (geo stack) → notificação WhatsApp ao estafeta com link Maps +
Plus Code; estafeta confirma entrega por mensagem → `order.delivered` → review elegível. Sem app.

**Revendedores (fase 2–3)** — revendedor = tenant tipo `reseller` com link/código; atribuição por
UTM do wa.me ou código no pedido; comissão liquidada via payout (PayPay IBAN) após
`order.delivered` (janela anti-fraude).

**Kambá Score (fase 3)** — data mart (ClickHouse) sobre histórico de pedidos/pagamentos → score
exportado para banco parceiro; comissão de originação. Exige dados desde o dia 1 (já garantido
pelo desenho) — por isso o schema guarda tudo com timestamps limpos.

**Diáspora (fase 3)** — vitrine web com checkout internacional via parceiro de remessas/pagamentos
(Remitly/Unitel Money-type); pedido cai no mesmo fluxo Loja + liquidação PME em Kz.

**Sinal de procura & Índice de preços (fase 3)** — agregações sobre `assistant_queries` e catálogo:
relatório à PME ("procuraram X, ninguém tinha") e produto de dados B2B/B2G. **É a monetização do
ativo mais defensável** — cresce sozinho com o uso.

**API aberta (fase 3)** — a API interna ganha tier público (keys, quotas, billing) para bancos,
telcos e apps de entrega consultarem o índice.

---

## 5. Dados por finalidade (L1) — três sistemas, não um

| Sistema | Tecnologia | Serve |
|---|---|---|
| **Registo** (verdade operacional) | Medusa + Postgres | pedidos, stock, pagamentos, tenants |
| **Descoberta** (pesquisa) | pgvector + pg_trgm (+ Meilisearch se preciso) | índice federado, assistente, vitrine SEO |
| **Analytics** (inteligência) | ClickHouse (fase 3; antes: Postgres + jobs) | sinal de procura, score, índice de preços, dashboards |

Regras: preço/stock vivem só no Registo (e são citados dali); a Descoberta guarda texto/vetores
desnormalizados reconstruíveis; o Analytics é read-only sobre eventos (event sourcing leve via
event bus → consumer que alimenta ClickHouse). Qualquer sistema pode ser reconstruído a partir do
Registo + eventos.

---

## 6. Uma jornada completa pelas camadas (exemplo)

1. Consumidor envia voz ao **número da plataforma** (L4): "quero um frigorífico até 250 mil no Cazenga"
2. Gateway resolve persona=assistente → agent runtime: Whisper (media pipeline) → intenção →
   busca no índice (L1 descoberta) → 3 opções com preço **citado do Registo**
3. Cliente escolhe (B2) → módulo Pedidos cria encomenda no Medusa (merchant = Loja X) → reserva
   stock 72h → `order.created` no event bus
4. Primitiva pagamentos (adapter ProxyPay) emite referência → template utility no chat
5. Cliente paga no ATM → callback HMAC → `payment.confirmed` → Cobranças para de lembrar,
   Reputação agenda pedido de review, Analytics regista conversão
6. `order.paid` → Logística faz dispatch do motoboy (geo stack) → entrega confirmada →
   `order.delivered` → review por order_id → score da Loja X sobe
7. Fim do mês: billing da plataforma cobra a Loja X (assinatura + comissão) com a **mesma**
   primitiva de pagamentos

Toda a jornada usa 0 componentes específicos de um módulo só — é a prova de que a plataforma está
certa.

## 7. Roadmap técnico por fase

| Fase | Primitivas a fechar | Módulos ativos |
|---|---|---|
| **Piloto (0–3 m)** | canal WhatsApp dual, agent runtime v0, Medusa+índice, pagamentos ProxyPay, handoff Chatwoot, observabilidade | Loja no WhatsApp (Vendedor+Catálogo+Pedidos), Reputação básica |
| **Clusters (3–12 m)** | entitlements, billing, event bus completo, geo stack + Valhalla, payouts | Serviços, Orçamentos, Cobranças, Logística federada, Factura AI, Vitrine SEO, assistente de consumo público por cluster |
| **Escala (12–24 m)** | ClickHouse, Keycloak, k8s, API pública | Social AI, Arquivo AI, Compras/compras agrupadas, Revendedores, Academia, Diáspora, Kambá Score, Sinal de procura, Índice de preços |

## 8. Não-funcionais de plataforma

- **Isolamento de tenant**: scoping por `tenant_id` em todas as queries + testes de isolamento no
  CI (uma fuga de dados entre PMEs destrói a confiança)
- **Quality rating por número**: monitorização automática (API Meta) com alertas; o número da
  plataforma tem proteção redobrada (screening de categorias, rate limits, moderação)
- **Custo por módulo por tenant**: visível em dashboard (LiteLLM + Meta + infra rateada) —
  pricing deixa de ser intuição
- **Compliance by design**: consentimento no 1º contacto (logado), dados nascem na base,
  subprocessadores listados (APD), residência quando a parceria local o exigir
- **Degradação graciosa**: LLM em baixo → Typebot assume fluxos determinísticos; pagamentos em
  baixo → fila com reconciliação diferida; nunca silêncio

## 9. O que a plataforma deliberadamente NÃO constrói

Carteira própria (BNA) · app móvel (WhatsApp é a interface) · USSD · motor de facturação (parceiro
certificado AGT) · LLM self-host antes do break-even · STT para Kimbundu (handoff humano até haver
dados) · gateway não-oficial em produção · marketplace com fundos retidos pela plataforma.

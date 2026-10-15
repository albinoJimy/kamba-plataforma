# Arquitetura técnica v2 — plataforma AI-first de comércio conversacional (Angola)

**Substitui `09-arquitetura-tecnica-v1-DESATUALIZADO.md` (v1).** Baseada em pesquisa técnica profunda (4 frentes:
messaging, IA, comércio/pagamentos/geo, infra/compliance) com fontes primárias verificadas em
out/2026. Cada decisão indica alternativas rejeitadas e porquê. Contexto de negócio:
`05-estrategia-loja-no-whatsapp.md`.

> 📐 **Escopo deste documento:** a arquitetura **do produto** (loja no WhatsApp + canais duais).
> Para a visão holística da **plataforma** (todas as primitivas, módulos do enquadramento e
> expansões), ver `10-arquitetura-plataforma-holistica.md`.

---

## 0. Princípios arquiteturais

1. **O core conversacional é código nosso** (licenças MIT/Apache apenas) — Dify e n8n proíbem
   multi-tenant SaaS nos tiers gratuitos; AutoGen está morto (Microsoft, out/2025)
2. **Oficial por defeito, não-oficial nunca como base** — um número banido é a morte da loja da PME
3. **Preço/stock nunca passam pelo LLM como texto** — vêm de tool calls com validação de citação
4. **Os dados nascem na nossa base; o WhatsApp é renderização**
5. **APIs de LLM até muito longe** — self-host de LLM só paga acima de ~0,5–1M msgs/mês
6. **Dinheiro assenta diretamente na conta de cada PME** — nunca fundos da plataforma (BNA)

---

## 1. Contexto do sistema

```
CLIENTE ──WhatsApp──┬─► número da PLATAFORMA (WABA própria: assistente, venda
                    │    assistida, guarda-chuva de PMEs "light")
                    └─► número da PME (Cloud API + COEXISTÊNCIA: app do dono continua viva)
                            │
                     Meta webhook → API Gateway (Node/TS)
                     roteamento por phone_number_id → persona:
                     assistente da plataforma | vendedor da PME X
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
     ORQUESTRADOR IA              CHATWOOT (self-host, MIT)
     (LangGraph, nosso)           consola humano-in-the-loop
              │                   (Agent Bot API gratuita)
   ┌──────────┼───────────┐               ▲
   ▼          ▼           ▼               │ handoff
 Vendedor  Pedidos     Catálogo ──────────┘
   │          │           │
   └────► MEDUSA v2 (produtos/encomendas/stock/reservas)
              │
   ÍNDICE FEDERADO (pgvector + pg_trgm, nosso) → serve o número da plataforma
              │
   PAGAMENTOS: ProxyPay (referências + MCX Express) → liquidação direta no banco da PME
   GEO: pin WhatsApp + Plus Codes + Nominatim self-host
   OBSERVABILIDADE: LiteLLM + Langfuse (self-host)
```

---

## 2. Camada WhatsApp (decisões com números)

### 2.1 Canal oficial: Cloud API direto + Coexistência

**Coexistência mudou o jogo e elimina o ponto cego 3 da ronda 2**: desde ~nov/2025, o mesmo número
funciona na app do dono E na Cloud API em simultâneo, com sync bidirecional e migração de 6 meses
de histórico. **Angola (+244) é elegível** (excluídos: Nigéria e África do Sul). Requisitos: app
Business ≥ v2.24.17, número com ~7+ dias de atividade, portfólio Meta Business, embedded signup.
Limite: 20 msgs/seg — mais que suficiente por loja.
([referência técnica](https://github.com/bellopushon/whatsapp-cloud-api/blob/main/skills/whatsapp-cloud-api/references/COEXISTENCE.md),
[países](https://help.tawk.to/article/connecting-whatsapp-to-tawkto-with-whatsapp-coexistence))

### 2.1a Dois canais de entrada: número da plataforma E/OU número da PME

O fluxo não é só "número da PME": a plataforma opera **dois tipos de número em simultâneo**:

| Canal | WABA | Persona do orquestrador | Quem fecha a venda |
|---|---|---|---|
| **Número da PME** | 1 WABA por PME (coexistência) | Vendedor AI da loja X | A própria loja (Fluxo A) |
| **Número da plataforma** | 1 WABA da plataforma (verificada, escala tiers) | Assistente de consumo | Handoff para a PME (B1) **ou venda assistida em nome dela** (B2) |

Regras de roteamento: todo webhook entra com `phone_number_id` → resolve **persona + tenant**
antes de tocar no LangGraph. No número da plataforma, o pedido carrega `origem=plataforma` +
`business_id` da PME fulfileira → a liquidação continua **direta na conta da PME** (ProxyPay)
e a plataforma regista a comissão. Reviews por `order_id` funcionam igual nos dois canais.

**PME "light"**: vendedor sem verificação Meta própria vende sob o número da plataforma — o
catálogo dele aparece nas respostas do assistente e o pedido chega-lhe por notificação. É o
caminho de cold-start: o número da plataforma vende desde o dia 1, antes de qualquer migração
de números de PMEs, e é também a rampa de entrada para o Fluxo A (quando a PME estiver pronta,
migra o seu número com coexistência e leva os clientes dela).

Risco concentrado: o número da plataforma agrega tráfego de todas as categorias → o **screening
de categorias proibidas** (§2.7) é ainda mais crítico aqui, e a WABA da plataforma precisa de
verificação empresarial cedo (tiers de mensagem e quality rating protegem o ativo mais valioso).

### 2.2 Custos oficiais (confirmado)

Angola fatura em **"Rest of Africa"**: marketing $0,0225 · utility $0,0040 · auth $0,0040 ·
**serviço (resposta na janela 24h) = grátis** · utility dentro da janela = grátis
([rate cards](https://zernio.com/blog/whatsapp-business-api-pricing)).
→ **Vender por conversa custa ~$0 na API oficial.** Só pagamos pushes iniciados pelo negócio
(confirmações fora de janela, lembretes). ⚠️ Verificar rate card +244 no WhatsApp Manager.

### 2.3 Direto vs BSP

| Opção | Custo | Veredito |
|---|---|---|
| **Cloud API direto** (como Tech Provider) | $0 markup; nós implementamos embedded signup | **MVP e crescimento** |
| 360dialog Partner | €250–1.000/mês + €15–49/número, markup zero | Alternativa a partir de ~100 números se a gestão Meta pesar |
| Twilio | +$0,005/msg em ambas as direções | Rejeitado — taxa por mensagem mata bots de volume |
| WATI/Zoko | SaaS para utilizador final | Rejeitado — não é infraestrutura |

### 2.4 Gateways não-oficiais (análise honesta)

Baileys (11k★), whatsmeow (7,5k★, base do mautrix), Evolution API (9,8k★, v2.3.7), WAHA (7,5k★).
Todos emulam o protocolo multi-device: o número fica no telemóvel do dono, $0/mensagem.
**Mas**: violam ToS; estudos de 2025-2026 reportam **deteção típica em 2–8 semanas** sob
automação e bans permanentes ([Kraya](https://blog.kraya-ai.com/whatsapp-automation-ban-risk)).
Uma loja cuja venda depende do número **não pode ter o número banido** — e a reputação da
plataforma morre junto. Veredito: **prototipagem interna apenas**, nunca como via de produção de
clientes. A coexistência oficial entrega o mesmo benefício (número do dono vivo) sem risco.

### 2.5 Chatwoot self-hosted — a consola humano-in-the-loop

v4.18 (37,6k★, core MIT). Docker: Rails + Sidekiq + Postgres + Redis; produção em 4 cores/8–16GB.
- **WhatsApp Cloud API nativo** (inbox por número) + Twilio/360dialog
- **Agent Bot API gratuita**: o nosso orquestrador LangGraph regista-se como bot, recebe
  `message_created`, responde e faz handoff mudando o estado da conversa → humano.
  **Não precisamos do Captain** (enterprise, $99/agente/mês)
- Multi-tenant: **1 conta Chatwoot por PME** (contactos partilham-se dentro da conta); provisionar
  contas/inboxes via **Platform API** (o embedded signup multi-tenant está em aberto:
  [issue #13426](https://github.com/chatwoot/chatwoot/issues/13426))
- SLA/SAML são enterprise — vivemos sem no MVP

### 2.6 Typebot (FSL-1.1→Apache, seguro para uso interno/comercial)

Integração nativa com Cloud API. Papel: **fluxos determinísticos** — onboarding da PME, captura
de morada/pin, confirmação de encomenda — complementando a conversa livre do LLM.

### 2.7 Notas operacionais

- **Tiers de mensagem**: 250 conversas iniciadas/24h sem verificação → 2.000 com verificação.
  Lojas PME vivem bem; o número do assistente de consumo precisa de verificação empresarial
- **OBA (blue tick)** é irrealista para PMEs (exige notoriedade editorial) — não prometer
- **Quality rating**: um SME a vender categoria proibida (tabaco, saúde, gambling) degrada o
  rating do portfólio → **screening de categoria no onboarding** é compliance técnica, não burocracia
- Typing indicators disponíveis na Cloud API (2025) — usar para o agente parecer vivo

---

## 3. Camada de IA (o core que é nosso)

### 3.1 Orquestrador: LangGraph (MIT, Python)

Grafo de estados explícito: classificador de intenção → agentes especialistas →
`interrupt()` para handoff humano no Chatwoot; checkpointer Postgres (conversas resumíveis).
Rejeitados: **Dify** (licença proíbe multi-tenant), **n8n** (idem; só automações internas de
back-office), **AutoGen** (descontinuado), **CrewAI** (demasiado emergente para citar preços),
**Rasa Pro** (~$35k/ano — o padrão CALM replica-se em LangGraph por $0).

### 3.2 Modelos (via LiteLLM desde o dia 1)

| Papel | Modelo | Custo/1M tok (in/out) |
|---|---|---|
| Roteamento de intenção | GPT-4.1-nano ou Gemini Flash-Lite | $0,10 / $0,40 |
| Conversa de venda | **GPT-4.1-mini** | $0,40 / $1,60 |
| Fallback | Gemini 2.5 Flash-Lite | $0,10 / $0,40 |
| Visão (Catálogo AI) | GPT-4o / 4.1 | $2,50 / $10 (só na ingestão) |

Custo real por mensagem de venda: **$0,0003–0,0011** — o LLM não é problema de orçamento.
LiteLLM (MIT): chaves virtuais por tenant, budgets e spend tracking por PME (= ledger de custos
para o pricing), fallbacks automáticos. Self-host (Qwen3-14B/32B em vLLM) só para residência de
dados ou >0,5–1M msgs/mês; Sabiá-3 (Maritaca) como opção PT a avaliar.

### 3.3 Voz

- **STT: Groq whisper-large-v3-turbo** — $0,04/hora, ~200× tempo real (nota de 30s em <1s).
  Fallback: OpenAI gpt-4o-mini-transcribe ($0,003/min)
- **Kimbundu/Umbundu: não existe STT de produção** em nenhum provider → o pipeline deteta
  baixa confiança e escala para humano. Longo prazo: recolher 50–100h anotadas = moat de verdade
- **TTS no MVP: desligado** (resposta em texto). Depois: gpt-4o-mini-tts (~$0,015/min) ou
  Kokoro-82M (Apache-2.0, self-host). **Nunca XTTS v2** (CPML não-comercial, Coqui faliu)
- Orçamento de latência: nota de voz → resposta em **4–12s**; reação "🎧 a ouvir…" imediata

### 3.4 RAG do catálogo — sem alucinação de preço

- **pgvector + pg_trgm + FTS português no Postgres** (zero infra nova até ~1M produtos).
  Meilisearch entra se a tolerância a typos ("niker"→Nike) se provar insuficiente; Qdrant só >1M vectores
- Embeddings: text-embedding-3-small ($0,02/1M tok; 1.000 SKUs ≈ $0,002). Estrada aberta para
  multilingual-e5-large/BGE-M3 self-host
- **Preço e stock NUNCA entram no embedding nem no prompt**: o agente chama
  `get_price_stock(sku)` → resposta validada por regex pós-geração que confere cada número citado
  contra o output da tool; mismatch → regenera ou escala. Retrieval fraco → "não sei" + handoff
- Normalização PT-AO: dicionário de sinónimos por tenant + global (ténis/sapatilha, telemóvel/
  celular), tabela de marcas canónicas alimentada pelas queries sem resultado

### 3.5 Guardrails pragmáticos (~200 linhas, não framework)

Filtro de entrada (classificador nano anti-injeção) · tools read-only com escopo `tenant_id` ·
pagamentos/reembolsos sempre com aprovação humana · filtro de saída · rate-limit por utilizador.
(LLM Guard foi arquivado em jul/2026; NeMo Guardrails fica para fase de crescimento.)

### 3.6 Observabilidade: Langfuse self-host (core MIT)

Traces por conversa, custo por tenant (LiteLLM→Langfuse), **dataset golden de 100–300 conversas
PT-AO reais** (typos, code-switch, regateio) → LLM-as-judge com rubrica PT (preço correto [check
duro contra tool log], produto certo, registo, recusas) → **gate de deploy**. Sem isto, cada
mudança de prompt é um tiro no escuro.

---

## 4. Core de comércio: Medusa v2 + Mercur (não construir à mão)

Decisão-chave da v2: **o schema custom de encomendas da v1 está rejeitado.** Adotar
**Medusa v2** (MIT, Node/TS, Postgres) como núcleo headless de produtos/encomendas/stock +
**Mercur** (MIT, módulos de marketplace sobre Medusa v2) para isolamento por vendedor.

Porquê:
- **Reserva de inventário** nativa — crítico: o cliente paga a referência Multicaixa **horas ou
  dias depois** de encomendar; o stock tem de ficar reservado 24–72h e ser libertado na expiração.
  Reconstruir isto à mão são 20–30 dias + bugs de cauda longa
- Máquina de estados de encomenda + eventos (order placed → payment captured → fulfillment) que
  mapeia diretamente para as notificações WhatsApp
- Mesma stack (Node/TS + Postgres); o admin Medusa serve a nossa equipa de ops; a PME nunca o vê
  (fala por WhatsApp)

Mitigação de risco: Mercur é jovem (~1,6k★) → spike de 3–5 dias; fallback = Medusa puro + link
`merchant_id` com filtros por linha (~5 dias extra). Estimativa total: 10–15 dias de integração.
O **índice federado de pesquisa (pgvector) continua nosso** — Medusa é o sistema de registo,
o índice é o sistema de descoberta.

---

## 5. Pagamentos (o caminho real em Angola)

Facto de mercado: **ninguém integra a EMIS diretamente** — Tupuca/Roque/BayQi usam referências +
MCX Express via facilitador/banco. EMIS GPO direto exige certificação + inspeção de segurança
(1–3 meses). O caminho:

| Fase | Mecanismo | Prazo |
|---|---|---|
| **0 (semana 0–2)** | Cada PME cobra nos seus rails atuais (referência da sua entidade, MCX Express, KWiK); comprovativo no chat; confirmação humana | 0–3 dias |
| **Contratos (semana 1!)** | Pedir ao banco: entidade + TPA-virtual/GPO com facilitador. Lead time 2–6 semanas — **é o caminho crítico** | iniciar já |
| **1 (semanas 3–8)** | **ProxyPay**: API de referências (`custom_fields.order_id` ecoa na reconciliação; callback push com HMAC-SHA256) + OPG (MCX Express push ao telemóvel) + **Charges** (QR/deeplink `mcxwallet://` enviado no chat) | 2–4 dias refs + 3–6 dias OPG |
| 1 (paralelo) | Pedir cotação à **AppyPay** (certificada EMIS; sem taxa de adesão nem mensalidade; inclui Unitel Money) | comparar |
| 2 | **PayPay África**: única via documentada para **KWiK QR** programático + payouts IBAN (para agentes/motoboys). Envelope RSA-1024 — 5–10 dias | se KWiK/payouts forem prioridade |
| 2 | Vigiar **BitPay.ao** (DX estilo Stripe; sandbox já utilizável; aguarda certificação EMIS) | quando certificar |

Regras duras: estado de pagamento muda **só** por callback assinado (HMAC), idempotente — nunca
por comprovativo/imagem (fraude endémica). **Liquidação direta na conta de cada PME** (cada PME
com a sua entidade/TPA-virtual sob a nossa relação de facilitador) — plataforma a reter fundos de
clientes = problema regulatório BNA.

---

## 6. Geo e entregas

- **Fonte da verdade = pin de localização do WhatsApp** (lat/lng) + texto de referência
  ("atrás do mercado do 30, portão azul") + **Plus Code** (Apache-2.0, offline, grátis, pesquisável
  no Google Maps) derivado localmente
- **Nominatim self-host** (extracto Angola: 2–4 vCPU/8GB, importação em minutos; ODbL) para
  reverse-geocode → bairro/município (zonas de entrega e preço). Nunca a instância pública (1 req/s)
- Motoboy recebe no WhatsApp: link `maps.google.com/?q=lat,lng` + plus code + referência. Zero app
- Fase 2: **Valhalla** (MIT, costing nativo de mota) para ETAs e dispatch. what3words: rejeitado
  (proprietário, $9,99/1k conversões, sem tração em Angola)

---

## 7. Infraestrutura e compliance

### 7.1 Hosting

| Camada | MVP | Escala |
|---|---|---|
| App/API | **Azure Joanesburgo (52ms medido para Luanda)** ou AWS Cape Town (af-south-1; atenção egress $0,154/GB) | Primário em **Luanda** (Raxio AO1 / Paratus DC2 / Angola Cables Cloud — quote-based, faturação em Kz) |
| DB | Postgres gerido na mesma região | Primário Luanda + réplica async AngoNAP Fortaleza (63ms via SACS) |
| Edge | **Cloudflare (PoP Luanda)** — WAF, TLS, rate-limit | + load balancing multi-origem |
| GPU | Nenhuma (APIs) | Só se economics obrigarem; em JNB/Lisboa, fora do caminho crítico |

Latência dos webhooks Meta é dominada pela infra da Meta — a escolha de região é decisão de
**compliance e parceria**, não de latência.

### 7.2 Compliance (Lei 22/11 + Meta + AGT)

- **APD**: notificação do tratamento antes de começar; consentimento registado no onboarding
  (dobra como prova de opt-in Meta); contratos escritos com todos os subprocessadores.
  ⚠️ Transferência para países "não adequados" (APIs de LLM nos EUA) exige consentimento explícito
  e possivelmente autorização APD — a APD multa (mediana ~$100k). Confirmar com advogado local
- **Meta**: opt-in documentado por número; biblioteca de templates pré-aprovados; screening de
  categorias proibidas no onboarding
- **AGT e-facturação**: obrigatória para Grandes Contribuintes desde jan/2026, **todas as empresas
  em 2027**. Não construir motor de faturação — integrar software já certificado (Gestwin, SIGESC,
  Cacimbo). O módulo "Factura AI" vira front-end conversacional sobre um certificado → gancho de
  distribuição enorme à medida que 2027 se aproxima

### 7.3 Canais secundários

SMS só para OTP (agregador local ~€0,035 vs Twilio $0,259). **USSD: ignorar** (sem agregadores;
negociação direta com telcos). Bundles de WhatsApp são ubíquos e baratos (Unitel ilimitado;
Africell ~50–100 Kz/dia) → o nosso canal já é "grátis" para o utilizador. Parceria futura: Africell
(challenger digital) é a porta mais plausível.

---

## 8. Custos consolidados por estágio

| Item | MVP (10 PMEs) | Crescimento (100) | Escala (1.000) |
|---|---|---|---|
| LLM+STT+embeddings (API) | $3–10/mês | $30–80 | $300–800 |
| Meta WhatsApp (pushes) | ~$0–5 | $20–100 | $200–1.000 |
| Infra (VPS/managed) | $30–60 | $150–300 | $700–1.500 (Luanda: quote) |
| **Total tech** | **~$50–80/mês** | **~$250–500/mês** | **~$1.500–3.500/mês** |
| Por PME | ~$6 (~5.500 Kz) | ~$3,50 | ~$2,50 |

Contra assinatura de 30–60 mil Kz/PME: margem técnica >85%. Os custos reais do negócio são
agentes de ativação e suporte — não tecnologia. Equipa Luanda: dev mid 400–900 mil Kz/mês
(pipeline GDG Luanda, UAN, UCAN).

## 9. Plano de build revisto (12 semanas)

| Semanas | Entrega |
|---|---|
| 1 | **Iniciar contratos bancários** (caminho crítico). Spike coexistência + embedded signup. Sandbox ProxyPay/AppyPay/BitPay |
| 1–2 | Teste voz PT-AO/Kimbundu (Groq); rate card +244 confirmado; spike Mercur/Medusa |
| 3–5 | LangGraph v0 (Vendedor AI com tools + validador de citação) ligado ao Chatwoot via Agent Bot; Medusa: catálogo + encomenda |
| 6–7 | Catálogo AI (foto→produto); Typebot: onboarding PME + captura de pin/morada |
| 8–9 | ProxyPay referências + callbacks HMAC; reserva de stock 24–72h; reviews por order_id |
| 10 | Handoff humano completo; Langfuse + dataset golden PT-AO; painel ops |
| 11–12 | Piloto 10 PMEs / 1 cluster. Medir: custo real/PME, taxa resposta, vendas atribuídas, tempo de pagamento por referência |

## 10. Watch list (rever trimestralmente)

1. Rate card "Rest of Africa" para +244 (confirmar no WhatsApp Manager)
2. Lista de países elegíveis para coexistência (muda; hoje exclui NG/ZA)
3. Pricing Meta out/2026 (relatos de cobrança alargada a mensagens de serviço)
4. Maturidade do Mercur; cadência de releases do Evolution API (só uso interno)
5. Certificação EMIS do BitPay.ao; API pública de KWiK (se sair, simplifica)
6. Nova lei de proteção de dados (draft 2025) — pode endurecer regras de transferência
7. Lista de software certificado AGT (parceiro do módulo Factura AI)

# Arquitetura técnica da plataforma (MVP → escala)

> ⚠️ **DESATUALIZADO** — substituído por `08-arquitetura-tecnica-v2.md` (pesquisa profunda, out/2026),
> que inclui o fluxo dual número da plataforma e/ou número da PME. Mantido apenas para histórico.

Documento técnico que operacionaliza `05-estrategia-loja-no-whatsapp.md` e responde aos pontos
técnicos de `07-pontos-cegos-2.md`. Stack escolhida por critério de: custo em USD baixo, operação
simples com equipa pequena em Luanda, e zero app própria.

---

## 1. Visão geral

```
CONSUMIDOR                    PLATAFORMA                         PME
    │                                                            │
    │  WhatsApp (número da PME)                                  │
    └──────────────► WhatsApp Cloud API (via BSP/direto)         │
                            │                                    │
                     Webhook → API Gateway (Node)                │
                            │                                    │
                     Orquestrador de intenções ──────────────► notificação
                            │                                    │  ao dono
              ┌─────────────┼──────────────┐                     │  (WhatsApp)
              ▼             ▼              ▼                     │
        Vendedor AI    Catálogo AI    Pedidos/Pagamentos ◄───────┘
              │             │              │
              └──────► Postgres + pgvector ◄──┐
                            │                 │
                     Vitrine web (Next.js)  Painel PME (web leve)
                            │
                     Índice federado → Assistente de consumo (fase 2)
                            │
                     EMIS GPO / KWiK / PayPay (reconciliação server-side)
```

Princípio de dados (ponto cego 10): **tudo nasce na nossa base**; o WhatsApp é só renderização.

## 2. Camada WhatsApp — as decisões críticas

### 2.1 Cloud API direto vs. BSP

| Opção | Custo | Esforço | Quando |
|---|---|---|---|
| **Cloud API direto** (Meta) | Só tarifas Meta | Médio (gestão de templates, webhooks, display name) | **MVP e sempre**, se 1 dev dedicado |
| BSP (360dialog, Twilio, Gupshup) | +$0,003–0,010/msg ou mensalidade | Baixo | Se faltar capacidade de engenharia |

Recomendação: **Cloud API direto** desde o início (a margem do negócio vive nestes cêntimos).

### 2.2 Pricing atual (confirmado por pesquisa, out/2025+)

Desde **1 julho 2025** a Meta cobra **por mensagem de template**, por categoria e país
([Route Mobile](https://routemobile.com/blog/whatsapp-business-pricing/),
[Mobile Ecosystem Forum](https://mobileecosystemforum.com/2026/02/26/whatsapp-business-platform-business-models-2023-2025-updates/)):
- **Janela de serviço 24h**: mensagens de formato livre em resposta ao cliente = **grátis**;
  templates *utility* dentro da janela aberta = **grátis**
- **Utility fora da janela**: tarifa baixa (referência EUA ~$0,0034; Angola tem rate card próprio
  — consultar a tabela Meta por país)
- **Marketing**: tarifa alta (referência EUA ~$0,025) → evitar no nosso modelo
- ⚠️ **Tendência**: há relatos de cobrança alargada a mensagens de serviço a partir de out/2026
  ([SleekFlow](https://sleekflow.io/en-us/blog/whatsapp-business-price)) → desenhar já com
  margem para isso

Consequência arquitetural: o Vendedor AI deve responder **sempre dentro da janela de 24h**
(custo ~zero) e usar templates utility só para lembretes/confirmações essenciais.

### 2.3 O problema do número (ponto cego 3) — plano de resolução

A Meta lançou **coexistência app ↔ plataforma** (mesmo número na app do dono e na Cloud API),
mas com requisitos (conta elegível, onboarding via embedded signup, limitações por país/BSP).
Plano:
1. **Semana 1**: spike técnico — criar número de teste, ativar coexistência, verificar que o dono
   continua a usar a app normalmente enquanto a API recebe/envia
2. **Fallback A**: número virtual novo da plataforma por PME + o dono divulga esse número como
   "linha de pedidos" (perde o "número conhecido", mas funciona em qualquer cenário)
3. **Fallback B**: lojas novas começam diretamente com número gerido pela plataforma

### 2.4 Embedded signup

Onboarding da PME em 10 min via *embedded signup* da Meta (o agente de ativação faz no telemóvel
da PME): cria WABA, liga número, regista display name. Sem isto, escalar ativações é impossível.

## 3. Camada de IA

### 3.1 Orquestrador de intenções

Classificador barato (GPT-4o-mini / Gemini Flash) encaminha cada mensagem:

| Intenção | Agente | Modelo sugerido |
|---|---|---|
| "tens X? quanto custa?" | Vendedor AI (consulta catálogo via RAG) | 4o-mini / Flash |
| "quero comprar / manda referência" | Pedidos AI (cria pedido + ID + pagamento) | 4o-mini + tools |
| "onde fica? que horas?" | Info AI (dados da ficha da loja) | 4o-mini |
| reclamação / negociação / sensível | **handoff humano** (dono ou suporte) | — |
| cadastro de produto (foto da PME) | Catálogo AI | GPT-4o (visão) |

Regra de custo: **80% das mensagens em modelo mini**; modelo forte só para visão e casos que o
mini falha (retry com escalonamento). Regra de segurança: nunca inventar preço/stock — se o RAG
não tem, o agente pergunta ao dono ("confirmo já") em vez de alucinar (ponto cego: alucinação =
fraude percebida).

### 3.2 Voz (ponto cego 10 da ronda 1)

Pipeline: nota de voz → Whisper API ($0,006/min) → PT-AO → intenção. Kimbundu/Umbundu: Whisper
tem cobertura fraca → **teste na semana 1** com 50 notas reais; se falhar, fallback é resposta
empática a pedir texto, e roadmap de fine-tuning/distilação futura.

### 3.3 RAG sobre o catálogo

Postgres + **pgvector**: cada produto tem embedding (texto + atributos normalizados). A pergunta
do cliente faz busca semântica por loja → top-k produtos → resposta com preço/stock **citados da
base**, nunca gerados. A normalização ("ténis" = "sapatilha") acontece na ingestão, não na query.

### 3.4 Catálogo AI (pipeline de ingestão)

```
foto do dono → GPT-4o visão (extrai: nome, categoria, atributos, variações)
            → pergunta ao dono o que falta (preço, stock) por WhatsApp
            → remove.bg/Photoroom (fundo limpo) 
            → moderação automática (categorias proibidas)
            → produto normalizado no índice + vitrine web
```

Custo estimado: ~$0,02–0,05 por produto cadastrado. Irrelevante vs. o valor.

### 3.5 Guardrails e handoff

- Lista de categorias bloqueadas no MVP: medicamentos/saúde, financeiro, álcool para menores
- Confiança do classificador < limiar → humano
- Palavras-chave de risco (burla, reclamação, advogado) → humano imediato
- Toda resposta com preço é citada da base com timestamp ("preço atualizado há 2 dias")

## 4. Dados

**Postgres** (uma instância serve o MVP inteiro) + Redis (sessões/filas) + S3-compatível (fotos).

Schema núcleo:

```
businesses(id, nome, nif?, zona, gps, categoria, verificado, selo_at, agent_id, plano)
products(id, business_id, nome_norm, categoria, atributos jsonb, preco, stock, 
         foto_url, embedding, atualizado_at)
orders(id, business_id, cliente_msisdn, itens jsonb, total, estado,
       pagamento_ref, pagamento_estado, entrega_id?, criado_at)
leads(id, origem[assistente|quero_comprar], business_id, cliente, estado)
reviews(id, order_id FK, nota, texto)          -- só via order_id (anti-fraude)
agents(id, nome, zona, comissao_estado)
assistant_queries(id, texto_norm, zona, categoria, resolveu, criado_at)  -- ativo de dados
```

Regras: review só existe com `order_id` pago (ponto cego 5 ronda 1); `pagamento_estado` só muda
via webhook server-side, **nunca por comprovativo/imagem** (ponto cego 5 ronda 2).

## 5. Pagamentos

A EMIS tem gateway online próprio — **GPO** (mencionado no
[comunicado da Black Friday 2025](https://multicaixa.ao/noticias/a-rede-multicaixa-regista-forte-crescimento-nas-transaccoes-durante-a-black-friday-2025/),
100 mil compras online num dia). Caminhos por fase:

| Fase | Mecanismo | Reconciliação |
|---|---|---|
| 0 (piloto) | Referência Multicaixa/QR gerada pela PME; plataforma regista pedido + ID | Semi-manual: PME confirma por mensagem; auditoria por extrato |
| 1 | **GPO** via banco adquirente (BFA/BAI...) ou agregador (PayPay África, KWiK) com API | Webhook server-side automático |
| 2 | Comissão splitada na fonte | Automática |

A fase 0 permite validar tudo **sem** a parceria EMIS estar fechada — a parceria corre em
paralelo (ponto cego 7: leva trimestres).

## 6. Vitrine web e SEO

Next.js (SSG/ISR): `kamba.ao/loja/{slug}` por PME e `kamba.ao/{zona}/{categoria}` para landing
pages de cluster. `schema.org/LocalBusiness` + `Product` em cada página → o Google indexa as
lojas angolanas que nunca tiveram site. CTA único: botão "Falar no WhatsApp" (wa.me da PME).
Custo: alojamento quase zero (Vercel/Cloudflare Pages).

## 7. Backend, automação e infra

| Componente | MVP | Escala |
|---|---|---|
| API/orquestrador | Node.js (NestJS ou Hono) + webhooks | mesma base, horizontal |
| Fluxos (lembretes, reconciliação, relatórios) | **n8n self-hosted** | migrar gradual p/ código |
| Fila de mensagens | BullMQ (Redis) | Kafka se necessário |
| LLM gateway | LiteLLM (fallback multi-provider) | idem |
| Alojamento | VPS único (Hetzner ~€10) ou **AWS af-south-1** (Cape Town, menor latência p/ Angola) | avaliar **Angonap (Angola Cables)** p/ residência de dados |
| Observabilidade | Logs estruturados + Langfuse (traces LLM) | idem |
| Painel PME | Retool/Telegram-bot de gestão | web app leve |

Latência: Luanda ↔ Cape Town via cabo é bom; Luanda ↔ Europa aceitável. Nada disto é bloqueante
no MVP.

## 8. Unit economics técnico (por PME/mês, estimativa)

| Item | Pressuposto | Custo USD |
|---|---|---|
| Mensagens serviço (janela 24h) | 300 conversas × 10 msgs | $0 (grátis hoje) |
| Templates utility fora de janela | 100 × ~$0,005 | ~$0,50 |
| LLM mini (80% do tráfego) | ~3M tokens | ~$1,50 |
| LLM forte + visão (20% + catálogo) | ~0,5M tokens + 50 fotos | ~$2,00 |
| Whisper (notas de voz) | 150 min | ~$0,90 |
| Infra partilhada | rateio | ~$1,50 |
| **Total** | | **~$6–8 (~5.500–7.500 Kz)** |

Contra assinatura de 30.000–60.000 Kz → **margem bruta técnica ~75–85%**. O custo que falta
controlar não é técnico: é o agente de ativação e o suporte humano (ponto cego 6 ronda 2).

## 9. Plano de build — 12 semanas, 2 devs + 1 ops

| Semanas | Entrega |
|---|---|
| 1–2 | Spike: coexistência número, Cloud API direto, embedded signup, teste voz PT-AO/Kimbundu |
| 3–4 | Vendedor AI v0 (texto, RAG sobre catálogo manual) + webhook + Postgres |
| 5–6 | Catálogo AI (foto→produto) + gestão por mensagens + vitrine web v0 |
| 7–8 | Pedidos + referência + confirmação manual de pagamento + reviews por order_id |
| 9–10 | Handoff humano, guardrails, painel ops, métricas (custo/conversa real) |
| 11–12 | Piloto com 10 PMEs de 1 cluster; medir: custo/PME, taxa de resposta, vendas atribuídas |

Stack mínima de equipa: 1 full-stack (API+integrações), 1 automation/AI (agentes+n8n),
1 ops/agentes de campo. Tudo o resto é SaaS gerido.

## 10. Testes técnicos imediatos (antes de escrever código de produto)

1. **Coexistência** app↔API no mesmo número (caminho crítico do conceito)
2. **Voz**: 50 notas reais PT-AO + mistura Kimbundu → taxa de acerto Whisper+LLM
3. **Custo real por conversa** com 100 conversas simuladas → validar tabela §8
4. **Rate card Meta para Angola** (utility/marketing) → confirmar pressupostos de pricing
5. **Embedded signup** ponta-a-ponta num telemóvel de uma PME real

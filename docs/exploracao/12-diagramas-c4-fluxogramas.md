# Diagramas do sistema — modelo C4 (C1→C4) + fluxogramas

Documento visual da plataforma. Todos os diagramas em **Mermaid** (renderizam em GitHub,
VS Code, Typora, Obsidian). Base: `10-arquitetura-plataforma-holistica.md` e
`11-arquitetura-detalhada-engenharia.md`. "Kambá" = nome de trabalho da plataforma.

---

## C1 — Contexto do sistema

Quem usa e com o que a plataforma fala:

```mermaid
flowchart TB
    subgraph Pessoas["👤 Atores"]
        CONS["Consumidor<br/>(compra por WhatsApp)"]
        PME["Dono da PME<br/>(vende no seu WhatsApp)"]
        AGT["Agente de ativação<br/>(onboarding em campo)"]
        EST["Estafeta / motoboy"]
        REV["Revendedor digital"]
        OPS["Equipa ops da plataforma"]
    end

    KAMBA["🟦 PLATAFORMA KAMBÁ<br/>comércio conversacional AI-first<br/>(este sistema)"]

    subgraph Externos["🌐 Sistemas externos"]
        META["Meta — WhatsApp<br/>Business Platform (Cloud API)"]
        LLM["Providers LLM<br/>OpenAI · Google · Groq"]
        PPAY["ProxyPay / AppyPay<br/>(facilitadores EMIS)"]
        EMIS["EMIS — Multicaixa<br/>referências · MCX Express · KWiK"]
        BANCO["Bancos parceiros<br/>(liquidação direta à PME)"]
        AGTSW["Software certificado AGT<br/>(e-facturação)"]
        TELCO["Telcos — Unitel · Africell<br/>(bundles WhatsApp)"]
        MAPS["OSM / Google Maps<br/>(navegação estafeta)"]
    end

    CONS -- "voz/texto: compra, pergunta, paga" --> META
    META -- "mensagens + callbacks" <--> KAMBA
    PME -- "fotos, preços, pedidos" --> META
    AGT -- "onboarding (Typebot)" --> KAMBA
    EST -- "aceita entrega, confirma código" --> META
    REV -- "partilha links, recebe comissão" --> META
    OPS -- "Chatwoot, dashboards" --> KAMBA

    KAMBA -- "prompts, STT, embeddings" --> LLM
    KAMBA -- "emite referências, valida HMAC" --> PPAY
    PPAY -- "liquidação" --> EMIS
    EMIS -- "assenta na conta da PME" --> BANCO
    KAMBA -- "facturas às PMEs (via API)" --> AGTSW
    KAMBA -- "SMS OTP (fallback)" --> TELCO
    KAMBA -- "links de navegação" --> MAPS
```

**Leitura:** o consumidor nunca instala nada nem cria conta — fala com o WhatsApp (número da
plataforma e/ou da PME). O dinheiro flui Consumidor → EMIS → **conta bancária da PME**
(a plataforma nunca retém fundos). A plataforma cobra as PMEs com os mesmos rails.

---

## C2 — Containers

Os serviços deployáveis (docker-compose no MVP; k8s na escala):

```mermaid
flowchart TB
    subgraph Edge["Edge"]
        CF["Cloudflare<br/>TLS · WAF · rate limit · CDN"]
    end

    subgraph Canais["Canais (L4)"]
        META2["Meta Cloud API<br/>webhooks + envio"]
        WEB["storefront<br/>Next.js — vitrine SEO + painel PME"]
        TBOT["Typebot<br/>fluxos determinísticos"]
        CW_UI["Chatwoot UI<br/>consola humana"]
    end

    subgraph Core["Núcleo da plataforma"]
        GW["gateway (Node/Hono)<br/>assinaturas · dedup · roteamento"]
        AR["agent-runtime (Python/LangGraph)<br/>todos os agentes IA"]
        MED["medusa (Medusa v2+Mercur)<br/>produtos · encomendas · stock"]
        BILL["billing<br/>metering + cobrança às PMEs"]
        PAY["payments svc<br/>adapters ProxyPay/AppyPay"]
        SEARCH["search svc<br/>híbrida vetor+trgm+FTS"]
        LOGI["logistics svc<br/>dispatch estafetas"]
    end

    subgraph Dados["Dados (L1)"]
        PG[("postgres 16<br/>+pgvector +pg_trgm")]
        RD[("redis<br/>BullMQ event bus")]
        MINIO[("minio (S3)<br/>media")]
        NOM["nominatim<br/>reverse geocode"]
        LF["langfuse<br/>traces + evals"]
        CH[("clickhouse (fase 3)<br/>analytics")]
    end

    subgraph IA["Infraestrutura IA"]
        LIT["litellm proxy<br/>virtual keys por tenant"]
        CW["chatwoot<br/>Rails+Sidekiq (HITL)"]
        N8N["n8n<br/>automações back-office"]
    end

    META2 --> CF --> GW
    GW --> RD
    RD --> AR
    AR <--> LIT
    AR <--> CW
    AR --> MED
    AR --> SEARCH
    MED --> PG
    SEARCH --> PG
    GW --> PAY
    PAY --> PG
    PAY --> RD
    BILL --> PAY
    BILL --> PG
    LOGI --> NOM
    LOGI --> RD
    AR --> LF
    AR --> MINIO
    RD --> CH
    TBOT --> GW
    WEB --> GW
    CW_UI --> CW
    N8N --> RD
```

---

## C3 — Componentes (4 containers críticos)

### C3.1 `gateway` — porta de entrada

```mermaid
flowchart LR
    subgraph GW["gateway (Node/Hono)"]
        VERIF["SignatureVerifier<br/>X-Hub-Signature-256 (Meta)<br/>HMAC-SHA256 (ProxyPay)"]
        DEDUP["DedupStore<br/>message.id / referencia<br/>(Redis TTL 7d)"]
        RESOLV["ChannelResolver<br/>phone_number_id →<br/>tenant + persona"]
        DISP["EventDispatcher<br/>publica no BullMQ<br/>(outbox pattern)"]
        MEDIA["MediaFetcher<br/>media_id → MinIO<br/>URL assinada interna"]
        RL["RateLimiter<br/>por msisdn e por número"]
        API["REST interna<br/>tenants · pedidos · catálogo"]
    end
    IN["POST /webhooks/meta<br/>POST /webhooks/proxypay<br/>REST /api/*"] --> VERIF
    VERIF --> DEDUP --> RL --> RESOLV --> DISP
    MEDIA --> DISP
    DISP --> Q[("redis/BullMQ")]
```

### C3.2 `agent-runtime` — o coração AI-first

```mermaid
flowchart TB
    MSG["mensagem da fila"] --> PIPE

    subgraph PIPE["Pipeline por mensagem"]
        G1["GuardrailInput<br/>anti-injeção · abuso"]
        STT["STT Adapter<br/>Groq Whisper (se voz)"]
        ROUT["IntentRouter<br/>GPT-4.1-nano / Flash-Lite"]
        GRAPH["GraphExecutor<br/>LangGraph (grafo do módulo)"]
        TOOLS["ToolLayer<br/>search · price_stock ·<br/>criar_pedido · book_slot"]
        CIT["CitationValidator<br/>regex nºs vs tool outputs"]
        HO["HandoffBridge<br/>interrupt → Chatwoot"]
    end

    G1 --> STT --> ROUT --> GRAPH
    GRAPH <--> TOOLS
    GRAPH --> CIT
    CIT -- "ok" --> SEND["enviar resposta<br/>(Meta send API)"]
    CIT -- "falhou 2x" --> HO
    ROUT -- "sensível/baixa conf." --> HO

    subgraph Estado["Estado e observabilidade"]
        CKPT[("checkpointer<br/>postgres")]
        TRACE["Langfuse tracer<br/>trace_id por conversa"]
    end
    GRAPH <--> CKPT
    GRAPH -.-> TRACE
    TOOLS --> MED2["medusa API"] & IDX["search svc"] & PAY2["payments svc"]
```

### C3.3 `payments svc` — dinheiro sem fraude

```mermaid
flowchart TB
    subgraph PAY["payments svc"]
        IFACE["PaymentProvider (interface)<br/>createCharge · status · refund · payout"]
        REF["ReferenceManager<br/>emitir · expirar · re-emitir"]
        HMACV["HMACValidator<br/>+ whitelist IP + anti-replay ±5min"]
        LEDG[("payment_events<br/>ledger imutável")]
        SETT["SettlementTracker<br/>confirma liquidação à PME"]
        POUT["PayoutService (fase 2)<br/>comissões revendedores/estafetas"]
    end
    subgraph Adapters["Adapters"]
        A1["ProxyPay<br/>refs + MCX Express + QR"]
        A2["AppyPay<br/>refs + Unitel Money"]
        A3["PayPay África<br/>KWiK QR + payouts IBAN"]
    end
    IFACE --> A1 & A2 & A3
    A1 & A2 & A3 --> HMACV
    HMACV -- "hmac_ok=true (única via)" --> LEDG
    REF --> LEDG
    LEDG --> SETT
    POUT --> A3
    LEDG --> EVT["publica payment.confirmed<br/>no event bus"]
```

### C3.4 `search svc` — descoberta federada

```mermaid
flowchart LR
    Q["query (texto normalizado)"] --> SYN["SynonymExpander<br/>dicionário PT-AO<br/>tenant + global"]
    SYN --> VET["VectorSearch<br/>pgvector HNSW top-40"]
    SYN --> TRI["TrigramSearch<br/>pg_trgm (typos: niker→nike)"]
    SYN --> FTS["FTS português<br/>ts_rank top-40"]
    VET --> RERANK["ReRanker<br/>0,5·vetor + 0,3·trgm + 0,2·fts<br/>+ 0,3·reputação + zona + stock"]
    TRI --> RERANK
    FTS --> RERANK
    RERANK --> TOP3["top-3 opções<br/>(preço/stock por JOIN ao Registo,<br/>nunca do índice)"]
    IDXB["IndexBuilder<br/>consumer do event bus:<br/>produto criado/atualizado → re-embed"] -.-> VET
```

---

## C4 — Nível de código (2 recortes)

### C4.1 Grafo do Vendedor (máquina de estados)

```mermaid
stateDiagram-v2
    [*] --> FiltrarInput
    FiltrarInput --> STT : seguro
    FiltrarInput --> RespostaSegura : injeção/abuso
    STT --> Classificar : texto ok
    STT --> HandoffHumano : confiança STT baixa (ex. Kimbundu)
    Classificar --> BuscarCatalogo : produto/preço
    Classificar --> ExecutarTool : compra/info
    Classificar --> HandoffHumano : sensível/reclamação
    BuscarCatalogo --> ExecutarTool : hits ≥ limiar
    BuscarCatalogo --> ResponderSemSaber : hits < limiar
    ExecutarTool --> Responder
    Responder --> ValidarCitacao
    ValidarCitacao --> EnviarResposta : números conferem
    ValidarCitacao --> Responder : retry (máx 1)
    ValidarCitacao --> HandoffHumano : 2ª falha
    HandoffHumano --> [*] : humano resolve (Chatwoot)
    EnviarResposta --> [*]
    ResponderSegura --> [*]
    ResponderSemSaber --> HandoffHumano
```

### C4.2 Estrutura de classes — payments

```mermaid
classDiagram
    class PaymentProvider {
        <<interface>>
        +createCharge(order, canal) Charge
        +status(ref) PaymentStatus
        +refund(ref, valor) Result
        +payout(destino, valor) Result
    }
    class ProxyPayAdapter {
        -apiKey
        +createCharge()
        +validateCallback(headers, body) bool
    }
    class AppyPayAdapter
    class PayPayAdapter {
        -rsaEnvelope()
        +payout()
    }
    class PaymentService {
        +emitirReferencia(orderId)
        +processarCallback(provider, payload)
        +expirarReservas()
    }
    class PaymentEvent {
        +provider
        +referencia
        +valor_kz
        +callback_hmac_ok
    }
    PaymentProvider <|.. ProxyPayAdapter
    PaymentProvider <|.. AppyPayAdapter
    PaymentProvider <|.. PayPayAdapter
    PaymentService --> PaymentProvider
    PaymentService --> PaymentEvent : persiste (ledger)
    PaymentService --> EventBus : publica payment.*
```

---

## Fluxogramas end-to-end

### F1 — Venda no número da PLATAFORMA (Fluxo B, com decisão B1/B2)

```mermaid
sequenceDiagram
    autonumber
    actor C as Consumidor
    participant M as Meta WA
    participant G as gateway
    participant A as agent-runtime (assistente)
    participant S as search svc
    participant D as Medusa
    participant P as payments/ProxyPay
    participant L as logistics svc
    participant PME as PME (fulfil)

    C->>M: voz: "frigorífico até 250 mil no Cazenga"
    M->>G: webhook (mensagem)
    G->>A: fila (tenant=plataforma, persona=assistente)
    A->>A: STT (Groq) → intenção=compra
    A->>S: busca híbrida (zona=Cazenga)
    S-->>A: 3 opções (preço citado do Registo)
    A->>M: lista 3 opções + "comprar já ou falar com a loja?"
    M->>C: resposta (4–12s)
    alt B1 — falar com a loja
        C->>M: escolhe "falar"
        A->>M: card wa.me da PME + order_id de rasto
        Note over C,PME: conversa continua no número da PME (Fluxo A)
    else B2 — venda assistida
        C->>M: escolhe "comprar já"
        A->>D: criar_pedido (merchant=Loja X, origem=plataforma, reserva 72h)
        D-->>A: order_id
        A->>P: emitir referência (custom_fields.order_id)
        P-->>A: entidade + ref 9 dígitos
        A->>M: referência + instruções de pagamento
        M->>C: "pague 245.000 Kz à ref 102 345 678"
        C->>P: paga no ATM/homebanking
        P->>G: callback HMAC (payment.confirmed)
        G->>D: captura encomenda
        G->>M: confirmação + código de entrega
        alt com entrega
            G->>L: dispatch (order.paid)
            L->>M: estafeta aceita → link Maps + Plus Code
            L->>PME: "pedido #1234 pago, preparar"
            L->>M: entrega confirmada (código 4 dígitos) → order.delivered
        else levantamento na loja
            G->>PME: "pedido #1234 pago, cliente levanta com código"
        end
        G->>M: pedido de review (só order paga)
    end
```

### F2 — Venda no número da PME (Fluxo A)

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente (conhece a loja)
    participant M as Meta WA
    participant A as agent-runtime (vendedor PME X)
    participant D as Medusa
    participant P as payments
    participant O as Dono da PME (app Chatwoot/WhatsApp)

    C->>M: "tens o niker 42 azul? quanto é?"
    M->>A: webhook → tenant=PME X, persona=vendedor
    A->>D: buscar (trgm: niker≈nike) + get_price_stock
    D-->>A: {nike air 42 azul, 38.500 Kz, stock 3}
    A->>A: validador de citação OK
    A->>M: "Temos — Nike Air 42 azul, 38.500 Kz (3 un.). Queres?"
    C->>M: "sim, manda referência"
    A->>D: criar_pedido (reserva 72h)
    A->>P: emitir referência
    A->>M: referência ao cliente
    Note over C,P: paga → callback HMAC → confirmação
    A->>O: notificação "venda #567 paga — 38.500 Kz"
    Note over A: se preço pedido fora do catálogo / reclamação:<br/>handoff → dono responde no Chatwoot
```

### F3 — Onboarding de uma PME (provisioning)

```mermaid
flowchart TB
    AGT["Agente em campo<br/>(Typebot no telemóvel)"] --> T1["POST /tenants<br/>estado=onboarding"]
    T1 --> E{"evento<br/>tenant.activated"}
    E --> M1["Medusa: sales_channel<br/>+ merchant (Mercur)"]
    E --> C1["Chatwoot: conta +<br/>inbox (Platform API)"]
    E --> L1["LiteLLM: virtual key<br/>budget = plano"]
    E --> N1["Entitlements:<br/>módulos do plano"]
    M1 & C1 & L1 & N1 --> OK{Fluxo?}
    OK -- "Fluxo A (número próprio)" --> ES["embedded signup<br/>+ coexistência (número do dono)"]
    ES --> TST["mensagem de teste<br/>end-to-end"]
    TST --> ACT["estado=ativo"]
    OK -- "Light (sem número)" --> IDX["catálogo indexado sob<br/>o número da plataforma"]
    IDX --> ACT
    E -- "falha em qualquer passo" --> RB["compensação:<br/>apaga recursos criados + alerta ops"]
```

### F4 — Handoff humano (estados da conversa)

```mermaid
stateDiagram-v2
    [*] --> BotAtivo : cliente escreve
    BotAtivo --> AvaliandoHandoff : gatilho (sensível,<br/>2ª falha citação,<br/>STT baixa conf.)
    AvaliandoHandoff --> BotAtivo : falso alarme
    AvaliandoHandoff --> HumanoAtivo : interrupt() → Chatwoot<br/>conversa=open + resumo LLM
    HumanoAtivo --> BotSilenciado : humano a responder
    BotSilenciado --> BotAtivo : humano fecha conversa<br/>(webhook → resume grafo)
    HumanoAtivo --> Arquivada : 24h sem resposta<br/>(métrica SLA por tenant)
    Arquivada --> [*]
    BotAtivo --> [*] : resposta enviada
    note right of BotSilenciado
        SLA alvo: retoma < 15 min
        alimenta ranking de
        responsividade do assistente
    end note
```

### F5 — Ciclo de vida da encomenda

```mermaid
stateDiagram-v2
    [*] --> criada : criar_pedido (Medusa)
    criada --> reservada : stock reservado 72h
    reservada --> paga : payment.confirmed (HMAC ok)
    reservada --> expirada : 72h sem pagamento
    expirada --> reservada : nova referência emitida<br/>(régua Cobranças T+2h/T+24h)
    expirada --> cancelada : 2ª expiração
    paga --> em_preparacao : PME notificada
    em_preparacao --> em_entrega : dispatch aceite
    em_preparacao --> para_levantar : sem entrega
    em_entrega --> entregue : código 4 dígitos confirmado
    para_levantar --> entregue : código confirmado na loja
    entregue --> review_elegivel : +2h
    review_elegivel --> [*] : review (1 por order) / timeout 7d
    paga --> disputa : cliente reclama
    disputa --> reembolsada : humano aprova refund
    cancelada --> [*]
    reembolsada --> [*]
    note right of paga
        liquidação direta na conta da PME;
        comissão plataforma registada
        para cobrança mensal (billing)
    end note
```

### F6 — Mapa de eventos (quem fala com quem, sem chamadas diretas)

```mermaid
flowchart LR
    subgraph Produtores
        PED[Pedidos] ; PAG[Pagamentos] ; LOG[Logística] ; AR2[agent-runtime] ; ONB[Onboarding] ; MED3[Medusa]
    end
    BUS(("EVENT BUS<br/>BullMQ → NATS/Kafka"))
    subgraph Consumidores
        STOCK[Stock/Reservas] ; COB[Cobranças] ; REP[Reputação] ; ANA[Analytics/ClickHouse] ; NOT[Notificações] ; REV2[Revendedores] ; SCO[Kambá Score] ; PROV[Provisioning]
    end
    PED -->|order.created/expired| BUS
    PAG -->|payment.confirmed/failed| BUS
    LOG -->|order.delivered| BUS
    AR2 -->|query.unresolved| BUS
    ONB -->|tenant.activated| BUS
    MED3 -->|stock.low| BUS
    BUS --> STOCK & COB & REP & ANA & NOT & REV2 & SCO & PROV
```

---

## Convenções de leitura

- **C1** responde "quem usa e com o que falamos" — nível de investidor/parceiro
- **C2** responde "que serviços existem" — nível de arquiteto/ops
- **C3** responde "o que há dentro de cada serviço" — nível de dev sénior
- **C4** responde "como está o código" — nível de implementação
- **F1–F6** são os fluxos que cortam as camadas — usar em code review e onboarding da equipa

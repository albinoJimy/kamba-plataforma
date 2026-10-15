# Backlog Executável — KAMBÁ (Comércio Conversacional AI-First para Angola)

**Produto:** KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para o mercado angolano
**Natureza:** Produto/plataforma standalone (sem cliente institucional)
**Documentos-fonte:** conjunto técnico [`../docs/tecnica/`](../docs/tecnica/INDICE.md) e [`../docs/exploracao/14-tese-minima-e-plano-de-validacao.md`](../docs/exploracao/14-tese-minima-e-plano-de-validacao.md)
**Versão do conjunto:** 1.2
**Data de emissão:** Outubro de 2026
**Classificação:** Documento de Referência — Interno
**Estado:** backlog **proposto** (nenhum ticket ratificado; ver `00_KAMBA_Carta.md` §6)

---

## 1. Propósito

Este conjunto materializa o **backlog executável** da KAMBÁ para a **Fase 0 (Fundação / esqueleto andante)** e a **Fase 1 (Piloto)**. Decompõe o trabalho em **151 tickets atómicos (KAM-001 a KAM-150 e KAM-152)** distribuídos por **11 epics** (KAM-111 a KAM-117 foram acrescentados na consolidação, e o KAM-128 a KAM-150 e o KAM-152 depois dela; todos pertencem aos epics indicados no §3.1), cada um com critérios de aceitação SMART, Definition of Done, testes requeridos e prompt de handoff para o **Claude Code (CLI)**. O identificador **151** está reclamado por um ramo em voo e ainda não tem bloco, pelo que a numeração é descontínua e o intervalo deixou de valer como contagem: escreve-se `KAM-001 – KAM-150, KAM-152` e **não** fechado, porque o gate 3 expande intervalos e um intervalo fechado exigiria que o 151 existisse no §4.

O que **não** está aqui: a Fase 2 (Clusters) e a Fase 3 (Escala). Esses epics (geo e logística, estafetas, analytics e Score, índice federado, AdsEngine, vitrine SEO, API pública, Fluxo B) só se escrevem quando o **Gate do Piloto (KAM-110)** for verde. Está declarado em §6.

O backlog é a interface entre o conjunto técnico (`../docs/tecnica/`) e a execução. Onde um ticket depende de um facto **NÃO VERIFICADO** ou de uma **decisão aberta** (D1–D12 em `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3), o ticket di-lo e tem critério de saída para essa dependência.

---

## 2. Estrutura do conjunto

| Documento | Tipo | Foco | Ficheiro |
|-----------|------|------|----------|
| **00 Carta** | Foundation | Forma do produto no Piloto, registo de decisões (FIXA/CONDICIONAL/ABERTA), Definition-of-Done do Piloto, regra de congelamento | [00_KAMBA_Carta.md](00_KAMBA_Carta.md) |
| **00 System Spec** | Foundation | Visão executiva, capacidades, componentes, mapeamento capacidade → componente → epic, KPIs e SLOs | [00_System_Spec.md](00_System_Spec.md) |
| **01 Engineering Standards e Handoff** | Foundation | DoR/DoD, gates de CI/CD, convenções, template de PR, prompt mestre do Claude Code | [01_Engineering_Standards_e_Handoff.md](01_Engineering_Standards_e_Handoff.md) |
| **02 Dicionário de Dados Canónico** | Foundation | Um nome por conceito (dinheiro, estados, eventos, identidade, consentimento); prevalece sobre `../docs/tecnica/` até KAM-111 | [02_Dicionario_de_Dados_Canonico.md](02_Dicionario_de_Dados_Canonico.md) |
| **EPIC-01 Fundações e Dados** | Epic | Monorepo, CI, schema `platform`, RLS, outbox e eventos, identidade de contacto, TEN | [EPIC-01_Fundacoes_Dados.md](EPIC-01_Fundacoes_Dados.md) |
| **EPIC-02 Canais WhatsApp e Handoff** | Epic | GWY, CHR, outbound, Embedded Signup v4, coexistência, HND/Chatwoot, consentimento | [EPIC-02_Canais_WhatsApp_Handoff.md](EPIC-02_Canais_WhatsApp_Handoff.md) |
| **EPIC-03 Agent Runtime e Verticais** | Epic | AGR, AgentRegistry, ToolLayer, LLM gateway, grafos Vendedor e Serviços, validador, voz | [EPIC-03_Agent_Runtime_Verticais.md](EPIC-03_Agent_Runtime_Verticais.md) |
| **EPIC-04 Core de Comércio** | Epic | Spike Medusa, CommerceRegistry, encomendas, reservas, módulo `servicos`, Catálogo AI | [EPIC-04_Core_Comercio.md](EPIC-04_Core_Comercio.md) |
| **EPIC-05 Pagamentos e Billing** | Epic | PaymentProvider, ledger, ManualProvider, ProxyPay, cobranças, billing da plataforma | [EPIC-05_Pagamentos_Billing.md](EPIC-05_Pagamentos_Billing.md) |
| **EPIC-06 Índice e Pesquisa** | Epic | Pesquisa híbrida por tenant (RRF), normalização PT-AO, embeddings, avaliação | [EPIC-06_Indice_Pesquisa.md](EPIC-06_Indice_Pesquisa.md) |
| **EPIC-07 Segurança e Conformidade** | Epic | STRIDE, isolamento cruzado, supply chain, subprocessadores APD, direitos do titular, red-team | [EPIC-07_Seguranca_Conformidade.md](EPIC-07_Seguranca_Conformidade.md) |
| **EPIC-08 Topologia e Operação** | Epic | Ambientes, compose de produção, alojamento, CI/CD, backups, observabilidade, SLOs, DR | [EPIC-08_Topologia_Operacao.md](EPIC-08_Topologia_Operacao.md) |
| **EPIC-09 Onboarding e Governação** | Epic | onboarding-web, KYC K1 automático, screening, fila de excepções, saga, T&S, off-boarding | [EPIC-09_Onboarding_Governanca.md](EPIC-09_Onboarding_Governanca.md) |
| **EPIC-10 Spikes, Validação e Gates** | Epic | Spikes (coexistência, voz), pedidos à Meta/bancos/jurídico, entrevistas, gates da Fase 0 e do Piloto | [EPIC-10_Spikes_Validacao_Gates.md](EPIC-10_Spikes_Validacao_Gates.md) |
| **EPIC-11 Módulos de Entrada** | Epic | Canal do dono, Catálogo AI conversacional, Foto de produtos AI, Social AI (publicação manual), Orçamento expresso, planos e metering, experimento H10–H12 (ADR-020) | [EPIC-11_Modulos_Entrada.md](EPIC-11_Modulos_Entrada.md) |

---

## 3. Inventário de tickets

### 3.1 Por epic

| Epic | Range | N.º tickets | Fase |
|------|-------|-------------|------|
| EPIC-01 Fundações e Dados | KAM-001 – KAM-012, KAM-111, KAM-128 – KAM-148, KAM-150 – KAM-152 | 37 | 0–1 |
| EPIC-02 Canais WhatsApp e Handoff | KAM-013 – KAM-024, KAM-115 | 13 | 0–1 |
| EPIC-03 Agent Runtime e Verticais | KAM-025 – KAM-040, KAM-114 | 17 | 0–1 |
| EPIC-04 Core de Comércio | KAM-041 – KAM-051 | 11 | 0–1 |
| EPIC-05 Pagamentos e Billing | KAM-052 – KAM-060 | 9 | 0–1 |
| EPIC-06 Índice e Pesquisa | KAM-061 – KAM-064 | 4 | 1 |
| EPIC-07 Segurança e Conformidade | KAM-065 – KAM-074, KAM-112, KAM-113, KAM-149 | 13 | 0–1 |
| EPIC-08 Topologia e Operação | KAM-075 – KAM-085 | 11 | 0–1 |
| EPIC-09 Onboarding e Governação | KAM-086 – KAM-099, KAM-116, KAM-117 | 16 | 1 |
| EPIC-10 Spikes, Validação e Gates | KAM-100 – KAM-110 | 11 | 0–1 |
| EPIC-11 Módulos de Entrada | KAM-118 – KAM-127 | 10 | 1 |
| **TOTAL** | **KAM-001 – KAM-148, KAM-150 – KAM-152** | **152** | — |

### 3.2 Fases

| Fase | Duração-alvo | Objectivo | Gate |
|------|--------------|-----------|------|
| **Fase 0 — Fundação** | ≤ 6 semanas | Esqueleto andante: uma conversa real cria um pedido, recebe confirmação de pagamento e o evento é consumido pela outra vertical (regra de dois) | **KAM-108** |
| **Fase 1 — Piloto** | semanas 7–12 | ~10 PMEs em onboarding automático, H1/H6/H8/H9 medidas, pagamento por facilitador se o contrato existir | **KAM-110** |

### 3.3 Caminho crítico

Itens com tempo de espera externo (arrancam na **semana 1**, em paralelo ao código): **KAM-100** (coexistência +244), **KAM-101** (perguntas à Meta), **KAM-102** (Tech Provider), **KAM-103** (bancos e facilitadores), **KAM-104** (parecer jurídico), **KAM-105** (alojamento e APD). O código depende destes em: **KAM-016** (Tech Provider), **KAM-017** (coexistência), **KAM-056** (contrato de pagamento), **KAM-069** (alojamento e APD) e **KAM-077** (alojamento). A decisão **D10** (canal operacional da KAMBÁ) fecha em **KAM-101** e condiciona **KAM-049**, **KAM-058** e **KAM-115**.

---

## 4. Backlog mestre (contrato entre epics)

**Legenda.** Tipo: `feature`, `chore`, `spike`, `fix`. Estimativa: XS/S/M/L (XL proibido). Prioridade: P0 = bloqueia o gate da fase; P1 = necessário ao Piloto; P2 = desejável. Fase: 0 ou 1. Dependências por ID; `ext:` = dependência externa (decisão D# ou terceiro).

### EPIC-01 — Fundações e Dados

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-001 | Monorepo, estrutura de serviços e toolchain | chore | M | P0 | 0 | — |
| KAM-002 | Pipeline de CI base: gates fail-closed (build, lint, tipos, unit, secrets, SBOM, licenças) | chore | M | P0 | 0 | KAM-001 |
| KAM-003 | Schema `platform`: tenants, entitlements, tenant_channels e migrações reversíveis | feature | L | P0 | 0 | KAM-001 |
| KAM-004 | RLS `FORCE` por `app.tenant_id` e suite de isolamento SQL | feature | M | P0 | 0 | KAM-002, KAM-003 |
| KAM-005 | Outbox transaccional, publicador BullMQ e envelope de evento versionado | feature | L | P0 | 0 | KAM-003 |
| KAM-006 | Consumidores idempotentes, `events_consumed` e DLQ | feature | M | P0 | 0 | KAM-005 |
| KAM-007 | Catálogo de eventos: schemas versionados e teste de compatibilidade | feature | M | P0 | 0 | KAM-005 |
| KAM-008 | Identidade de contacto em duas camadas (contacts, endpoints, HMAC rodado, cofre) | feature | L | P0 | 0 | KAM-003, KAM-010 |
| KAM-009 | TEN: entitlements e limites aplicados por middleware | feature | M | P0 | 0 | KAM-003 |
| KAM-010 | Gestão de segredos e chaves (Doppler no Piloto, interface OpenBao) | chore | M | P0 | 0 | KAM-001 |
| KAM-011 | StorageProvider S3-compatível (SeaweedFS ou gerido) | feature | M | P0 | 0 | KAM-001, ext:D6 |
| KAM-012 | `audit_log` append-only para dinheiro, stock e preço | feature | S | P0 | 0 | KAM-003 |
| KAM-111 | Dicionário de dados canónico e reconciliação de `../docs/tecnica/` | chore | M | P0 | 0 | KAM-001, KAM-002, KAM-128 |
| KAM-128 | Reorganização do conjunto documental sob `docs/` e reescrita das referências cruzadas | chore | M | P0 | 0 | KAM-001 |
| KAM-129 | Correcção do prefixo das referências aos anexos de evidência em `specs/` | fix | S | P1 | 0 | KAM-128 |
| KAM-130 | Reconciliação das contagens e intervalos herdados no conjunto documental | fix | S | P2 | 0 | KAM-128 |
| KAM-131 | Gate 9 sobre a história do PR: varrimento dos *blobs* novos | fix | M | P1 | 0 | KAM-002 |
| KAM-132 | Cobertura Node sobre todo o TypeScript do âmbito (`--test-coverage-include`) | fix | M | P2 | 1 | KAM-002 |
| KAM-133 | SBOM por serviço a atravessar as dependências `link:` do *workspace* | fix | S | P2 | 1 | KAM-002 |
| KAM-134 | Chaves de `ci/*.yaml` que nenhum código lê, e recusa de chaves desconhecidas | fix | S | P2 | 1 | KAM-002 |
| KAM-135 | Validador de *waivers*: `criado_em`, data de aprovação verificada e gates 14 e 18 | fix | S | P2 | 1 | KAM-002, KAM-134 |
| KAM-136 | Dois erros de leitura silenciosos do `tools/kamba_yaml.py` | fix | S | P2 | 1 | KAM-002 |
| KAM-137 | Verificação do *ruleset* de `main` e onde vive o *token* de administração | chore | M | P2 | 1 | KAM-002 |
| KAM-138 | Gate 3c: lint de coerência do backlog (mestre ↔ epics) | chore | M | P2 | 1 | KAM-002 |
| KAM-139 | Variantes vivas em `../docs/tecnica/` fora das 12 do KAM-111 (dívidas do gate 3b) | fix | S | P1 | 0 | KAM-111 |
| KAM-140 | Divergências de `../docs/tecnica/` que o KAM-111 encontrou e não enumera | fix | M | P1 | 0 | KAM-111 |
| KAM-141 | Contradições do dicionário canónico encontradas pelo gate 3b | fix | S | P1 | 0 | KAM-111 |
| KAM-142 | Celeridade do processo de entrega: vagas, mutações em paralelo e menos colisões | chore | S | P1 | 0 | KAM-002, KAM-004 |
| KAM-143 | Prova por mutação completa como tarefa nocturna, e fatiada por *runner* | chore | S | P1 | 0 | KAM-142 |
| KAM-144 | Reciprocidade `Dependências`↔`Bloqueia`: os oito tickets que o KAM-002 não declara bloquear | fix | S | P1 | 0 | — |
| KAM-145 | Forma do caminho dentro dos blocos de *handoff*, e o `cwd` do executor declarado | fix | L | P1 | 0 | KAM-128, KAM-129 |
| KAM-146 | As onze linhas de «Controlo de versões» que o KAM-128 não acrescentou | fix | S | P2 | 0 | KAM-128 |
| KAM-147 | Os anexos de evidência que o DoD do KAM-128 e do KAM-129 nomeia e não existem | fix | S | P2 | 0 | KAM-128, KAM-129, KAM-145 |
| KAM-148 | Leituras silenciosas nos outros dois leitores de YAML (`yamlreg` e `yamlsubset`) | fix | M | P2 | 1 | KAM-136 |
| KAM-150 | Regras de `CODEOWNERS` penduradas no prefixo que o KAM-128 removeu | fix | S | P1 | 0 | KAM-128 |
| KAM-151 | Cobertura Python sobre `services/agr/src/`, que nenhum alvo media | fix | S | P2 | 1 | KAM-132 |
| KAM-152 | `db/gate8.py`: um caminho que não existe, numa mensagem que manda correr o ficheiro | fix | S | P2 | 0 | — |

### EPIC-02 — Canais WhatsApp e Handoff

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-013 | GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila) | feature | L | P0 | 0 | KAM-001, KAM-005, KAM-010 |
| KAM-014 | CHR: ChannelResolver por `phone_number_id` com BSUID | feature | M | P0 | 0 | KAM-003, KAM-008, KAM-013, KAM-004, KAM-006 |
| KAM-015 | Outbound: envio, janela de 24 h, templates utility e custo de mensagens | feature | L | P0 | 0 | KAM-013, KAM-014, KAM-004 |
| KAM-016 | Embedded Signup v4 e Tech Provider (troca de code, subscrições de webhooks) | feature | L | P0 | 1 | KAM-013, KAM-003, ext:KAM-102, KAM-010 |
| KAM-017 | Coexistência: history, state sync, echoes, `PARTNER_REMOVED`, sincronização de 24 h | feature | L | P0 | 1 | KAM-016, ext:KAM-100 |
| KAM-018 | Protocolo bot ↔ dono ↔ humano: modos da conversa e silenciamento por echo | feature | M | P0 | 1 | KAM-014, KAM-017 |
| KAM-019 | HND: HandoffProvider e Chatwoot (Agent Bot API, espelho por inbox de tipo API) | feature | L | P0 | 0 | KAM-014 |
| KAM-020 | Mídia: download autenticado, armazenamento e URL interna assinada | feature | M | P0 | 1 | KAM-013, KAM-011 |
| KAM-021 | Quality rating, estado `restrito` e monitorização de limites | feature | M | P0 | 1 | KAM-013, KAM-009 |
| KAM-022 | Consentimento no 1.º contacto (aviso versionado, botões, `consent_event`) | feature | M | P0 | 1 | KAM-008, KAM-014, KAM-015 |
| KAM-023 | Monitorização do free tier de service messages e do método de pagamento da PME | feature | S | P0 | 1 | KAM-015 |
| KAM-024 | Simulador de webhooks Meta e testes de contrato com número de teste | chore | M | P0 | 0 | KAM-013 |
| KAM-115 | Aviso ao dono por canal alternativo (e-mail ou push) | feature | S | P1 | 1 | KAM-017, KAM-021, KAM-023, KAM-116 |

### EPIC-03 — Agent Runtime e Verticais

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-025 | AGR: serviço, workers assíncronos, lock por conversa e API interna | feature | L | P0 | 0 | KAM-005, KAM-014 |
| KAM-026 | Checkpointer Postgres (esquema `lg`), `thread_id` e retenção | feature | M | P0 | 0 | KAM-025 |
| KAM-027 | AgentRegistry e validação no arranque (YAML, nós obrigatórios, licenças) | feature | M | P0 | 0 | KAM-025, KAM-009 |
| KAM-028 | ToolLayer: contrato, classes read/write/money e auditoria | feature | L | P0 | 0 | KAM-025, KAM-004, KAM-012, KAM-009 |
| KAM-029 | Idempotência de tools por `cart_id` | feature | M | P0 | 0 | KAM-028 |
| KAM-030 | LLM gateway: LiteLLM por digest, chaves virtuais, budgets e `llm_call_log` | feature | M | P0 | 0 | KAM-001, KAM-002, KAM-010, KAM-069 |
| KAM-031 | Grafo do Vendedor: esqueleto, `confirm_gate` e fluxo de dois turnos | feature | L | P0 | 0 | KAM-027, KAM-028, KAM-029, KAM-030, KAM-032, KAM-015, KAM-019 |
| KAM-032 | Validador de citação: renderer por referência e validador numérico com `sku` | feature | L | P0 | 0 | KAM-028 |
| KAM-033 | Guardrails de entrada e saída (injecção, domínio, cartão, sensível) | feature | M | P0 | 1 | KAM-030, KAM-031, KAM-069 |
| KAM-034 | Handoff idempotente em dois nós e retoma por compare-and-set | feature | M | P0 | 1 | KAM-019, KAM-026, KAM-031, KAM-018 |
| KAM-035 | Grafo de Serviços: slots, disponibilidade e `book_slot` | feature | L | P0 | 0 | KAM-027, KAM-028, KAM-047 |
| KAM-036 | Pipeline de voz: STT com confiança, eco e fallback a humano | feature | L | P1 | 1 | KAM-020, KAM-030, KAM-107, KAM-069 |
| KAM-037 | Modo determinístico sem LLM e degradação | feature | M | P1 | 1 | KAM-031 |
| KAM-038 | Subscrição de eventos: as verticais acordam por evento | feature | M | P0 | 0 | KAM-006, KAM-027, KAM-007 |
| KAM-039 | Prova da regra de dois: teste de contrato e métrica de reaproveitamento | feature | M | P0 | 0 | KAM-031, KAM-035, KAM-038, KAM-046 |
| KAM-040 | Dataset golden PT-AO sintético e eval harness como gate | feature | L | P0 | 1 | KAM-031, KAM-035, KAM-033, KAM-034 |
| KAM-114 | Modo concierge: a IA rascunha e o humano aprova | feature | M | P0 | 1 | KAM-018, KAM-031, KAM-034 |

### EPIC-04 — Core de Comércio

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-041 | Spike Medusa v2: isolamento entre vendedores e reservas com TTL | spike | M | P0 | 0 | KAM-001 |
| KAM-042 | Porta CommerceRegistry e adaptador (Medusa puro + `merchant_id`, ou fallback) | feature | L | P0 | 0 | KAM-041, KAM-003 |
| KAM-043 | Produtos, stock e preço opaco (fixo, a partir de, sob consulta) | feature | M | P0 | 0 | KAM-042 |
| KAM-044 | Encomendas: máquina de estados e `orders_mirror` | feature | L | P0 | 0 | KAM-042, KAM-005, KAM-008, KAM-004 |
| KAM-045 | Reservas de stock 24–72 h com expiração e libertação por evento | feature | M | P0 | 0 | KAM-044, KAM-052 |
| KAM-046 | `propose_cart` e criação idempotente de pedido | feature | M | P0 | 0 | KAM-044, KAM-029, KAM-052 |
| KAM-047 | Módulo `servicos`: serviços, recursos, disponibilidade, marcações e holds | feature | L | P0 | 0 | KAM-003, KAM-004, KAM-005 |
| KAM-048 | Lembretes de marcação e templates utility | feature | M | P1 | 1 | KAM-047, KAM-015, KAM-022 |
| KAM-049 | Catálogo AI: foto → produto, normalização PT-AO e perguntas de completude | feature | L | P0 | 1 | KAM-042, KAM-020, KAM-030, KAM-043, KAM-088, KAM-069, ext:KAM-101 |
| KAM-050 | Estados adicionais da encomenda: pagamento tardio, disputa, entrega falhada, reembolso | feature | M | P1 | 1 | KAM-044 |
| KAM-051 | Contrato `v_oferta_viva` e leitura para o índice | feature | S | P0 | 1 | KAM-043 |

### EPIC-05 — Pagamentos e Billing

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-052 | Interface PaymentProvider (com `verifyCallback` e `reconcile`) e beneficiário por conta | feature | M | P0 | 0 | KAM-003, KAM-008 |
| KAM-053 | Ledger `payment_events` append-only (INSERT por função) e unicidade | feature | L | P0 | 0 | KAM-052, KAM-004, KAM-008 |
| KAM-054 | ManualProvider: confirmação humana auditada, limites e dupla verificação | feature | L | P0 | 0 | KAM-052, KAM-053, KAM-015, KAM-014, KAM-012 |
| KAM-055 | Eventos `payment.confirmed` e `payment.manual_confirmed` e transição da encomenda | feature | M | P0 | 0 | KAM-054, KAM-044, KAM-005, KAM-006 |
| KAM-056 | Adapter ProxyPay: referências, callbacks HMAC, reconciliação e expiração | feature | L | P1 | 1 | KAM-052, KAM-053, ext:KAM-103, KAM-013, KAM-010 |
| KAM-057 | Avaliação do segundo facilitador (AppyPay) e matriz de decisão | spike | S | P2 | 1 | KAM-052, ext:KAM-103 |
| KAM-058 | Régua de cobrança D+3/D+7/D+10 | feature | M | P1 | 1 | KAM-055, KAM-015, KAM-059, ext:KAM-101 |
| KAM-059 | Billing da plataforma: assinatura via PaymentProvider (beneficiário próprio) | feature | L | P1 | 1 | KAM-052, KAM-054, KAM-009 |
| KAM-060 | Detecção de anomalias de pagamento (valor divergente, duplicados, padrões) | feature | M | P1 | 1 | KAM-053, KAM-054 |

### EPIC-06 — Índice e Pesquisa

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-061 | `idx.candidatos`: pesquisa híbrida por tenant com RRF (exacta, sem ANN) | feature | L | P0 | 1 | KAM-042, KAM-043, KAM-051, KAM-028, KAM-006, KAM-007 |
| KAM-062 | Normalização PT-AO: sinónimos, marcas e tolerância a erros | feature | M | P1 | 1 | KAM-061 |
| KAM-063 | Embeddings do catálogo e modo lexical quando o destino não está autorizado | feature | M | P1 | 1 | KAM-061, KAM-030, ext:KAM-069 |
| KAM-064 | Avaliação de qualidade da pesquisa e dataset | feature | M | P1 | 1 | KAM-061, KAM-040, KAM-062, KAM-063 |

### EPIC-07 — Segurança e Conformidade

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-065 | Modelo de ameaças STRIDE e matriz requisito → controlo → teste | chore | M | P0 | 0 | — |
| KAM-066 | Suite de isolamento cruzado ponta a ponta (tenant e contacto) no CI | feature | M | P0 | 0 | KAM-004, KAM-028 |
| KAM-067 | Supply chain: SBOM, digests, cosign, lockfiles e bloqueio de licenças | feature | M | P0 | 0 | KAM-002 |
| KAM-068 | Política de logs sem conteúdo e redacção de PII | feature | S | P0 | 0 | KAM-002 |
| KAM-069 | Inventário de subprocessadores e gate de transferência com `apd_ref` | feature | M | P0 | 0 | KAM-008, ext:KAM-105 |
| KAM-070 | Direitos do titular: acesso, correcção, eliminação e exportação | feature | L | P1 | 1 | KAM-008, KAM-005, KAM-006, KAM-022, KAM-026 |
| KAM-071 | Retenção e purga por classe de dados | feature | M | P1 | 1 | KAM-026, KAM-011, KAM-020, KAM-070 |
| KAM-072 | Rotação de chaves Meta, facilitador e HMAC | feature | M | P1 | 1 | KAM-010, KAM-013, KAM-056, KAM-008 |
| KAM-073 | Red-team do AGR: injecção directa e indirecta, exfiltração | chore | M | P0 | 1 | KAM-033 |
| KAM-074 | Revisão de segurança independente pré-Piloto | chore | M | P0 | 1 | KAM-066, KAM-073, KAM-065 |
| KAM-112 | Minimização de PII antes do LLM | feature | M | P0 | 0 | KAM-030, KAM-008, KAM-068 |
| KAM-113 | Resposta a incidentes e notificação de violação de dados | chore | S | P0 | 1 | KAM-065, KAM-068 |
| KAM-149 | `docs/seguranca/validar.py` aborta com a contagem do canon fixada | fix | S | P1 | 0 | KAM-065 |

### EPIC-08 — Topologia e Operação

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-075 | Ambientes dev/staging/prod e infraestrutura como código mínima | chore | M | P0 | 0 | KAM-001 |
| KAM-076 | Compose de produção do conjunto reduzido e redes isoladas | feature | L | P0 | 0 | KAM-075 |
| KAM-077 | Alojamento, TLS, edge e WAF (D1, D12) | chore | M | P0 | 0 | KAM-075, ext:KAM-105 |
| KAM-078 | CI/CD completo: deploy rolling e smoke ponta a ponta com número de teste | feature | L | P0 | 1 | KAM-002, KAM-076, KAM-024 |
| KAM-079 | Backups pgBackRest fora do host, PITR e restauro mensal automático | feature | L | P0 | 1 | KAM-076, ext:KAM-105 |
| KAM-080 | Métricas, logs JSON e alertas (Prometheus, Grafana, Loki) | feature | L | P0 | 0 | KAM-076 |
| KAM-081 | Custo por tenant e dashboard de unit economics | feature | M | P1 | 1 | KAM-030, KAM-080, KAM-023 |
| KAM-082 | SLOs, orçamento de erro e alertas | feature | S | P0 | 1 | KAM-080 |
| KAM-083 | Runbooks operacionais (Meta, facilitador, LLM, rating, free tier, tokens, segredos) | chore | M | P0 | 1 | KAM-080, KAM-021, KAM-023, KAM-017, KAM-079 |
| KAM-084 | Teste de carga e validação do dimensionamento | chore | M | P1 | 1 | KAM-076, KAM-013, KAM-015, KAM-025, KAM-031, KAM-024 |
| KAM-085 | Simulacro de recuperação (DR drill) com RTO medido | chore | M | P0 | 1 | KAM-079 |

### EPIC-09 — Onboarding e Governação

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-086 | onboarding-web: registo, OTP e anti-abuso | feature | L | P0 | 1 | KAM-003, KAM-008, KAM-116 |
| KAM-087 | KYC K1 automático: documentos, OCR/visão, consistência e score de risco | feature | L | P0 | 1 | KAM-086, KAM-011, KAM-030, KAM-069 |
| KAM-088 | Screening de categorias: lista Meta ∪ lei como policy-as-code e classificador | feature | L | P0 | 1 | KAM-086, KAM-030 |
| KAM-089 | Fila de revisão por excepção para T&S/T2 | feature | L | P0 | 1 | KAM-087, KAM-088 |
| KAM-090 | Aceite contratual versionado: ToS, DPA e aviso de privacidade | feature | M | P0 | 1 | KAM-086, ext:KAM-104 |
| KAM-091 | Saga de provisioning com idempotência, compensação e reconciliação | feature | L | P0 | 1 | KAM-009, KAM-019, KAM-030, KAM-042, KAM-016 |
| KAM-092 | Eventos `tenant.approved`, `tenant.provisioned` e `tenant.activated` | feature | M | P0 | 1 | KAM-091, KAM-006, KAM-087, KAM-088, KAM-089, KAM-090, KAM-007 |
| KAM-093 | Passo guiado do Embedded Signup: pré-voo e falhas | feature | M | P0 | 1 | KAM-016, KAM-017, KAM-086 |
| KAM-094 | Catálogo mínimo e teste ponta a ponta automático | feature | M | P0 | 1 | KAM-049, KAM-091, KAM-088, KAM-092, KAM-093, KAM-023 |
| KAM-095 | Lista de espera para o limite de onboarding da Meta | feature | M | P1 | 1 | KAM-093, ext:KAM-102 |
| KAM-096 | Confiança gradual: tectos de valor por histórico | feature | M | P1 | 1 | KAM-054, KAM-087, KAM-009, KAM-044, KAM-055, KAM-097 |
| KAM-097 | Trust & Safety: sinais de burla, auto-compra e escada de sanções | feature | L | P1 | 1 | KAM-055, KAM-044, KAM-089, KAM-008, KAM-021 |
| KAM-098 | Off-boarding: exportação, revogação, purga e certificado | feature | L | P1 | 1 | KAM-070, KAM-091, KAM-071, KAM-011, KAM-092 |
| KAM-099 | Painel light da PME: preço, stock e estado do pedido | feature | M | P1 | 1 | KAM-086, KAM-043, KAM-044, KAM-012 |
| KAM-116 | Agregador de SMS para OTP e avisos | chore | S | P0 | 1 | — |
| KAM-117 | Instrumentação de KPIs de onboarding, churn e tenants dormentes | feature | M | P1 | 1 | KAM-092, KAM-081, KAM-018, KAM-044, KAM-055, KAM-099 |

### EPIC-10 — Spikes, Validação e Gates

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-100 | Spike H3: coexistência com três números +244 | spike | M | P0 | 0 | — |
| KAM-101 | Perguntas escritas à Meta: agregador, AI Provider, Access Verification, termos de ML | chore | S | P0 | 0 | — |
| KAM-102 | Business Verification, App Review e Tech Provider (D5) | chore | M | P0 | 0 | — |
| KAM-103 | Contratos de pagamento: bancos e facilitadores (D4) | chore | M | P0 | 0 | — |
| KAM-104 | Pacote de perguntas para o parecer jurídico (APD, BNA, AGT, Termos Meta) | chore | M | P0 | 0 | — |
| KAM-105 | Decisão de alojamento D1 e procedimento APD | chore | M | P0 | 0 | KAM-104 |
| KAM-106 | Canais de acesso a PMEs e 30 entrevistas (H1, H2) | chore | L | P0 | 0 | — |
| KAM-107 | Spike de voz PT-AO: WER e latência de dois STT com áudio real | spike | M | P1 | 1 | KAM-030 |
| KAM-108 | Gate da Fase 0: demonstração do esqueleto andante | chore | M | P0 | 0 | KAM-039, KAM-055, KAM-046, KAM-041, KAM-100, KAM-101, KAM-102 |
| KAM-109 | Piloto concierge e medição de H1, H6, H8 e H9 | chore | L | P0 | 1 | KAM-094, KAM-108, KAM-069, KAM-074, KAM-022, KAM-018, KAM-112, KAM-114, KAM-113 |
| KAM-110 | Gate do Piloto: decisão continuar, pivô ou parar | chore | S | P0 | 1 | KAM-109, KAM-074, KAM-085, KAM-040, KAM-082, KAM-083, KAM-105, KAM-069, KAM-103, KAM-106, KAM-113 |

### EPIC-11 — Módulos de Entrada (captação e suporte)

| ID | Título | Tipo | Est. | Prio | Fase | Dependências |
|---|---|---|---|---|---|---|
| KAM-118 | Canal do dono: reconhecimento do dono no número da loja, painel web e persona Assistente do Dono | feature | L | P1 | 1 | KAM-014, KAM-008, KAM-027, KAM-086, KAM-028, KAM-015, KAM-018, KAM-092 |
| KAM-119 | Vertical `catalogo`: fotografar, completar e publicar produtos pelo dono | feature | L | P1 | 1 | KAM-118, KAM-049, KAM-043 |
| KAM-120 | Foto de produtos AI: ImageProvider, fundo limpo, correcção de luz e variações | feature | L | P1 | 1 | KAM-049, KAM-011, KAM-069 |
| KAM-121 | Vertical `social`: perfil de marca, calendário semanal e legendas em português de Angola | feature | L | P1 | 1 | KAM-118, KAM-030, KAM-009, KAM-088 |
| KAM-122 | Social AI: artes e entrega para publicação manual com aprovação do dono | feature | M | P1 | 1 | KAM-121, KAM-120, KAM-015 |
| KAM-123 | Orçamento expresso: preço «sob consulta», pedido ao dono e proposta ao cliente | feature | M | P1 | 1 | KAM-043, KAM-118, KAM-031, KAM-032, KAM-005, KAM-007, KAM-015, KAM-018 |
| KAM-124 | Planos, entitlements e metering de custo dos módulos de entrada | feature | M | P1 | 1 | KAM-009, KAM-081, KAM-120 |
| KAM-125 | Golden PT-AO e guardrails dos módulos do dono (catálogo, social, orçamento) | feature | M | P1 | 1 | KAM-040, KAM-119, KAM-121, KAM-123 |
| KAM-126 | Spike Factura AI: parceiro certificado AGT, API e custo | spike | S | P2 | 1 | — |
| KAM-127 | Experimento dos módulos de entrada: hipóteses H10–H12, regra de escopo e critérios de abate | chore | M | P1 | 1 | KAM-119, KAM-120, KAM-122, KAM-123, KAM-124, KAM-092, KAM-117, KAM-125 |

---

## 5. Como usar o backlog com o Claude Code

1. **Escolher** um ticket cujas dependências estejam `Done` (ou sejam `ext:` já resolvidas) e cuja Fase seja a corrente.
2. **Ler** o bloco do ticket e os documentos de referência (`../docs/tecnica/`), incluindo o ADR citado.
3. **Colar** o prompt de handoff do ticket no Claude Code, ou usar o prompt mestre de `01_Engineering_Standards_e_Handoff.md` §8.
4. **Abrir PR** com o template de `01_Engineering_Standards_e_Handoff.md` §7; os gates de CI são fail-closed.
5. **Fechar** só quando a DoD (genérica e de domínio) estiver completa.

Um defeito encontrado fora do escopo não é corrigido no meio de outro ticket: abre-se um `KAM-NNN` novo (tipo `fix`).

---

## 6. O que fica fora (e quando entra)

| Item | Fase | Gatilho para escrever o epic |
|---|---|---|
| Geo, logística e estafetas; disputas de entrega | 2 (Clusters) | Gate do Piloto verde; decisões D1, D8 |
| Vitrine SEO, revendedores, Academia, rede de agentes | 2 | Idem |
| Cobranças avançadas, Factura AI (parceiro AGT), `InvoiceProvider` | 2 | D7 (confirmação AGT) |
| Índice federado, assistente de consumo, Fluxo B, PME light | 2–3 | **D2** (resposta escrita da Meta) |
| Analytics (ClickHouse), Kambá Score, índice de preços, AdsEngine, API pública | 3 | **D11** (parecer), volume de dados |
| Langfuse em produção | 2 | ADR-018; recursos |
| Publicação automática em Instagram/Facebook (Social AI), Arquivo AI, Compras AI, consignação, clube digital | 2+ | D13 (App Review da Meta, E5); procura validada pelos módulos de entrada (H10–H12) |
| Factura AI com parceiro AGT | 2 | Resultado do spike KAM-126 e D7 |

---

## 7. Aprovação, versionamento e manutenção

- **Estado:** backlog **proposto**; a ratificação segue `00_KAMBA_Carta.md` §6.
- **Manutenção:** divergências entre ticket, `../docs/tecnica/` e código são bugs documentais; cada alteração de ADR no `../docs/tecnica/00` §8 propaga-se aos tickets afectados.
- **Evidência:** os tickets herdam o estado CONFIRMADO/INDÍCIO/NÃO VERIFICADO de `../docs/tecnica/evidencia/`. Antes de executar um ticket que dependa de facto não verificado, reconfirmar na fonte primária.

| Versão | Data | Descrição | Autor |
|--------|------|-----------|-------|
| 1.0 | Outubro 2026 | Emissão inicial: 110 tickets (KAM-001 a KAM-110) em 10 epics, Fases 0 e 1. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | ADR-020 (decisão do fundador): módulos de entrada no Piloto; EPIC-11 com KAM-118 a KAM-127; hipóteses H10–H12; D13. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Consolidação após redacção dos epics: dependências em falta (≈ 60), prioridades e fases corrigidas, sem ciclos nem inversões; +7 tickets (KAM-111 a KAM-117); dicionário de dados canónico. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-128 (reorganização do conjunto documental sob `docs/`): regulariza em ticket os commits `d2dbb14` e `53189a2`, feitos sem ticket; total passa a 128 tickets em 11 epics. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | KAM-129 (prefixo das referências a evidência em `specs/`) e KAM-130 (contagens e intervalos herdados): dois `fix` para defeitos documentais pré-existentes, identificados na varredura do KAM-128 e declarados fora do seu âmbito; total passa a 130 tickets em 11 epics. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | KAM-131 a KAM-137: as lacunas 9 a 15 de `../docs/ci.md` §7, registadas pela revisão adversarial do KAM-002 como trabalho com medição própria, passam a tickets do EPIC-01 (seis `fix`, um `chore`). O KAM-131 (gate 9 sobre a história do PR) é o único P1 e o único de Fase 0; o KAM-134 bloqueia o KAM-135. Total passa a 137 tickets em 11 epics. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | KAM-138 (gate 3c, lint de coerência do backlog): a sincronia mestre↔epics, a reciprocidade `Dependências`↔`Bloqueia` e as contagens derivadas passam a gate, em vez de critério manual repetido em cada ticket. Aberto por se ter verificado que nem o gate 3 (KAM-002) nem o gate 3b (KAM-111) cobrem essa verificação. Total passa a 138 tickets em 11 epics. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | KAM-139, KAM-140 e KAM-141: três `fix` abertos pelo KAM-111, cujo critério 2 manda que «qualquer outra divergência encontrada vira ticket `fix`». O KAM-139 paga as 19 variantes vivas que o gate 3b encontrou em `../docs/tecnica/` fora das doze enumeradas (dívidas que vencem a 2026-11-10); o KAM-140 trata as divergências que não são variantes de nome; o KAM-141 leva a emenda as contradições do próprio dicionário. Os três dependem do KAM-111, são P1 de Fase 0 e entram no seu `Bloqueia`; total passa a 141 tickets em 11 epics. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | KAM-142 acrescentado: as melhorias de ritmo do processo de entrega (vagas em paralelo, mutações só das novas e em paralelo, suites de `tools/` descobertas pelo disco, lista única de dívidas documentais). Total: 142 tickets. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | KAM-143 acrescentado: a prova por mutação completa passa a tarefa nocturna no GitHub, fatiada por *runner*, por decisão do fundador. Total: 143 tickets. | Equipa KAMBÁ |
| 1.10 | Outubro 2026 | KAM-144 acrescentado: a reciprocidade `Dependências`↔`Bloqueia` do grafo do backlog regrediu de 0 para 8 falhas em `main` — oito tickets (KAM-131 a KAM-138) declaram depender do KAM-002 sem entrarem no seu `Bloqueia`. É o modo de falha que o critério 9 do KAM-129 previu por escrito, e a sincronia mestre↔epics não o apanha porque o §4 não tem coluna `Bloqueia`. O `fix` corrige os dados; a causa — o KAM-138 (gate 3c) não estar implementado — fica registada no bloco, com a recomendação de o subir a P1/Fase 0 devolvida ao Arquitecto de Plataforma. O ticket não declara dependência: a proveniência fica em prosa, para não inscrever no grafo uma aresta técnica que não existe. Total: 144 tickets. | Equipa KAMBÁ |
| 1.11 | Outubro 2026 | KAM-145, KAM-146 e KAM-147 acrescentados: as três lacunas documentais que a medição dos critérios de aceitação do KAM-128 deixou deliberadamente fora do seu encerramento, e que pedem decisão própria. O KAM-145 (`fix`, L, P1, Fase 0) decide a forma do caminho dentro dos blocos de *handoff* e manda declarar o *cwd* do executor nos padrões — a questão que o KAM-129 deixou em aberto, de que dependem as sete referências nuas à biblioteca exploratória que restam e as 291 ocorrências medidas nos onze epics. O KAM-146 (`fix`, S, P2, Fase 0) paga as onze linhas de «Controlo de versões» em falta. O KAM-147 (`fix`, S, P2, Fase 0) fecha a linha de DoD do KAM-128 e do KAM-129 que nomeia um anexo de evidência que não existe. Os três entram no `Bloqueia` do KAM-128, e o KAM-145 e o KAM-147 também no do KAM-129. Os três IDs seguem o último que `main` tem: o KAM-144 foi para o PR `#44`, que fundiu primeiro. O backlog tem de ser **contíguo** — o teste `test_kam_cobre_o_backlog_inteiro_sem_buracos` (*gate* 4) recusa um buraco na série, e o *gate* 3 expande intervalos e exige cada ID do interior — pelo que estes renumeram sempre que perderem uma corrida pelo ID, e já o fizeram duas vezes. Total: 147 tickets em 11 epics. | Equipa KAMBÁ |
| 1.12 | Outubro 2026 | KAM-148 acrescentado: a varredura de leituras silenciosas nos outros dois leitores de subconjunto de YAML (`tools/canon_lint/yamlreg.py`, que lê os `registry/*.yaml`, e `tools/secrets_inventory/yamlsubset.py`, que lê o `../ops/secrets-inventory.yaml`). É a lacuna 22 de `../docs/ci.md` §7, aberta pelo KAM-136 ao varrer só o primeiro dos três leitores, e a decisão devolvida ao fundador no bloco desse ticket. `fix`, P2, Fase 1, a depender do KAM-136. Total: 144 tickets. | Equipa KAMBÁ |
| 1.13 | Outubro 2026 | KAM-149 (`docs/seguranca/validar.py` aborta com a contagem do canon fixada): `fix` do EPIC-07 para a linha 43 do validador dos artefactos de segurança, que fixa 138 tickets e aborta com `AssertionError` desde que o *backlog* passou desse número — a verificação por máquina dos artefactos do KAM-065 não corre desde o KAM-139. Vinha da linha 6 de `../docs/dividas-documentais.md`, que o declara código e não resíduo textual. Total passa a 144 tickets em 11 epics. | Equipa KAMBÁ |
| 1.14 | Outubro 2026 | KAM-150 acrescentado: três regras de `CODEOWNERS` ficaram presas ao prefixo `/tecnica/` que o KAM-128 removeu e, por isso, não atribuem dono nenhum — defeito declarado fora de âmbito na verificação do KAM-128, onde deixa o DoD «Referências» por marcar. Os identificadores **145 a 148 foram saltados**: estão todos reclamados por ramos em voo, medido sobre `refs/heads`, `refs/remotes` e os nomes de ramo (o 149 foi o primeiro livre). Não se citam aqui como `KAM-NNN` porque não existem no §4 — o gate 3 recusa-os, e foi o gate que o apanhou. O 144 era um deles e chegou a `main` entretanto, pelo PR #44. Quantos dos outros chegam, e por que ordem, é de quem integra. Total: 145 tickets (KAM-001 a KAM-144 e KAM-150). | Equipa KAMBÁ |
| 1.15 | Outubro 2026 | KAM-151 acrescentado: fecha a lacuna 25 de `../docs/ci.md` §7 — `services/agr/src/` declarado no âmbito do *gate* 4 (`services/*/src/**`) e medido por alvo nenhum, apesar de `services/agr/tests/` existir. Depende do KAM-132 e entra no seu `Bloqueia`. Nasceu KAM-144, foi KAM-148 e é KAM-151: cinco PRs reclamaram o mesmo ID e a sessão que coordena a fila atribuiu-os por ordem de PR, fundindo por ordem crescente de ID para a série ficar contígua — **com o KAM-150 em `main`, está**: 151 tickets, de KAM-001 a KAM-151, sem buracos. O ticket destapou a **lacuna 26** (um `.py` medido a 0% faz o número descer e não sai nomeado no relatório). | Equipa KAMBÁ |
| 1.16 | Outubro 2026 | KAM-152 acrescentado e entregue: o caminho `db/gate8.py`, que não existe (o ficheiro é `db/gate_bd.py`), estava citado em **8** ocorrências de **7** ficheiros — **7 vivas em 6** —, e uma delas era a mensagem de erro do trinco do *gate* 8, que mandava o utilizador correr um ficheiro inexistente. O pedido nomeava três sítios. O nome do trinco `*_gate8` (**21** ocorrências em ficheiros vivos, invariantes entre `main` e o ramo) não foi tocado: é o nome canónico da base descartável, e a fasquia `grep gate8 → 0` do pedido fica registada como impossível à letra. `../docs/seguranca/validar.py` passa de 5 para 3 erros, com o `assert` da contagem relaxado em memória — corrigi-lo é o **KAM-149**. **O ticket nasceu KAM-150 e renumerou para 152**, porque o `albinoJimy/kamba#47` fundiu durante o trabalho e levou esse ID; o **151** está reclamado por um ramo em voo e sem bloco, pelo que o intervalo passa a descontínuo. Total: 151 tickets. | Equipa KAMBÁ |

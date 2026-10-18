# Documentação Técnica — KAMBÁ (Comércio Conversacional AI-First para Angola)

**Produto:** KAMBÁ — **nome de trabalho provisório** (conflito potencial com a app "Kamba" de food delivery em Luanda; decisão de marca pendente de verificação INPI/domínios — shortlist: Zuela, Kitanda, Mulemba, Kixikila, Mukanda)
**Natureza:** Produto/plataforma standalone (sem cliente institucional)
**Documentos-fonte:** **todo o conjunto de exploração** `../exploracao/01`–`../exploracao/13` (ver matriz de cobertura, §2.1)
**Versão do conjunto documental:** 1.1
**Data de emissão:** Outubro de 2026
**Classificação:** Documento de Referência — Interno

---

## 1. Propósito deste conjunto documental

Este conjunto materializa a **documentação técnica detalhada** da plataforma, **consolidando todo
o trabalho de exploração** (biblioteca `../exploracao/01`–`../exploracao/13`) numa forma formal por subsistema, com
decisões de arquitectura (ADRs), drivers não-funcionais, vista de qualidade, topologia de operação
e governação — no formato de referência do conjunto AOS (`C:\Jimy\AOS\tecnica\`).

A tese que atravessa todos os documentos: o "motor de busca" da economia informal angolana é uma
**conversa de WhatsApp**, e uma plataforma de comércio conversacional só é digna de produção se
tornar as falhas *arquitecturalmente impossíveis* — através de quatro fundações não-negociáveis:
**canal oficial com fluxo dual** (número da plataforma e/ou número da PME), **mediação total das
acções de negócio pelo agent runtime** (nenhum agente escreve fora do seu tenant; nenhum preço é
citado sem prova), **dinheiro com liquidação directa à PME confirmada server-side** (nunca
comprovativo, nunca fundos retidos), e **core próprio com verticais como configuração**.

**Regra de calibração (anti-teatro).** Este conjunto distingue sempre o que está **(Ratificado)**,
o que está **(Em validação)** — ligado às 8 validações de `../exploracao/07` — e o que é **(Proposta)** de
fase posterior. A documentação não antecipa certeza que o mercado ainda não deu; a ordem de
construção é puxada pelas validações, não pela completude documental.

O conjunto destina-se a: arquitectos de plataforma; engenheiros de runtime, dados, pagamentos e
integrações; responsáveis de produto; equipas de operação e de rede de agentes; e revisão
arquitectural e de conformidade (APD/BNA/AGT).

---

## 2. Índice de documentos

| Nº | Documento | Foco | Fontes de exploração | Ficheiro |
|----|-----------|------|----------------------|----------|
| 00 | **Arquitectura da Solução** | Âncora: camadas; fluxo dual; catálogo de componentes; 20 ADRs; NFRs; vista de qualidade; maturidade | 13, 10, 11, 12, 01–03 (contexto) | [00_Arquitectura_Solucao.md](00_Arquitectura_Solucao.md) |
| 01 | **Canais WhatsApp e Fluxo Dual** | Cloud API + coexistência; WABA plataforma vs PME; ChannelResolver; Chatwoot HITL; Typebot; quality rating | 05, 08, 12, 07 (ponto 3) | [01_Canais_WhatsApp_Fluxo_Dual.md](01_Canais_WhatsApp_Fluxo_Dual.md) |
| 02 | **Agent Runtime e Verticais** | LangGraph como serviço; AgentRegistry; grafos por módulo; guardrails; validador de citação; handoff; pipeline de voz | 08, 10, 11, 02 (módulos) | [02_Agent_Runtime_Verticais.md](02_Agent_Runtime_Verticais.md) |
| 03 | **Core de Comércio (Medusa)** | Medusa v2+Mercur; encomendas; reserva de inventário 72h; pipeline Catálogo AI; reviews por order_id | 05, 08, 11, 06 (reputação) | [03_Core_Comercio_Medusa.md](03_Core_Comercio_Medusa.md) |
| 04 | **Pagamentos, Liquidação e Anti-Fraude** | PaymentProvider; ProxyPay/AppyPay/PayPay; HMAC server-side; ledger imutável; payouts; BNA; comprovativo falso | 08, 11, 07 (ponto 5), 03 (linhas de receita) | [04_Pagamentos_Liquidacao_AntiFraude.md](04_Pagamentos_Liquidacao_AntiFraude.md) |
| 05 | **Índice Federado, Pesquisa e Motor de Atenção** | Pesquisa híbrida; normalização PT-AO; assistente de consumo; AdsEngine e placements; opacidade de preços | 03, 05, 06, 13, 07 (ponto 1) | [05_Indice_Pesquisa_Motor_Atencao.md](05_Indice_Pesquisa_Motor_Atencao.md) |
| 06 | **Dados, Eventos e Analytics** | Contratos de evento; outbox; ClickHouse; Kambá Score; sinal de procura; índice de preços; linhagem e consentimento | 06, 10, 11, 13, 04 | [06_Dados_Eventos_Analytics.md](06_Dados_Eventos_Analytics.md) |
| 07 | **Geo e Logística Federada** | Pin WhatsApp; Plus Codes; Nominatim; Valhalla; dispatch; código de entrega; COD e disputas | 06, 08, 11, 07 (pontos 8–9) | [07_Geo_Logistica_Federada.md](07_Geo_Logistica_Federada.md) |
| 08 | **Segurança e Conformidade** | Isolamento de tenant; Lei 22/11/APD; política Meta; segredos; auditoria; screening de categorias | 07, 08, 11, 04 (dados) | [08_Seguranca_Conformidade.md](08_Seguranca_Conformidade.md) |
| 09 | **Topologia, Operação e Escala** | Hosting JNB→Luanda; deploy; CI/CD; observabilidade; gargalos e respostas; DR; custos por estágio | 08, 11, 04 (infra) | [09_Topologia_Operacao_Escala.md](09_Topologia_Operacao_Escala.md) |
| 10 | **Onboarding e Governação** | 4+1 percursos; provisioning; Trust & Safety; rede de agentes; suporte em tiers; dataset golden; funil do consumidor | 05, 06, 13 (§9), 01 (mercado), 07 (ponto 8) | [10_Onboarding_Governanca.md](10_Onboarding_Governanca.md) |

**Total: 11 documentos.**

**Remediação P1 (planeada, à imagem da remediação AOS):** `11_Contratos_de_Interface.md` (schemas
request/response, erro, idempotência, SemVer por porta), `12_Matriz_Conformidade_APD_BNA_AGT.md`
(artigo → controlo → ticket) e `13_RTM_Rastreabilidade.md` (requisitos RF-/NFR- com IDs estáveis e
matriz requisito × validação).

### 2.1 Matriz de cobertura (exploração → técnica)

Prova de que cada documento de exploração é consumido por este conjunto:

| Doc exploração | Conteúdo | Consolidado em |
|---|---|---|
| 01 Modelo de negócios (10 ideias) | drivers de negócio, stack, mercado | 00 (contexto), 10 (percursos), 02 (verticais) |
| 02 Enquadramento em plataforma | módulos, cunha, moat | 02 (verticais), 00 (camadas) |
| 03 Modelo Google | 3 lados, 5 linhas de receita, atenção | 05 (motor de atenção), 04 (receita), 06 (dados) |
| 04 Pontos cegos ronda 1 | índice, frescura, custo do grátis, GTM relacional | 05, 08, 09, 10 |
| 05 Loja no WhatsApp + fluxo dual | digitalização distribuída, Fluxo A/B, PME light, clusters | 01, 03, 10 |
| 06 Expansões | 5 camadas de módulos futuros | 03–07, 10 (distribuído por subsistema) |
| 07 Pontos cegos ronda 2 | opacidade de preços, paradoxo informal, número, unit economics, 8 validações | 05, 04, 01, 08; **estados de ratificação (§5.1)** |
| 08 Arquitectura v2 | decisões de canal, IA, pagamentos, infra | 01, 02, 03, 04, 09 |
| 10 Arquitectura holística | primitivas L2, camadas, dados por finalidade | 00, 02, 06 |
| 11 Desenho de engenharia | DDL, eventos, grafos, deploy | 02, 03, 04, 06, 08, 09 |
| 12 Diagramas C4 | visual C1–C4, fluxogramas | 00–07 (figuras canónicas) |
| 13 Big picture | mapa do ecossistema, governação, dinheiro, atenção | 00 (âncora), 10 (governação) |

### 2.2 Precedência

Em caso de divergência: **este conjunto prevalece** sobre os documentos de exploração (que são
trabalho de investigação, não especificação). Alterações posteriores entram por ADR de
supersessão explícito. O documento `../exploracao/09` (arquitectura v1) está desatualizado e fora da linha.

---

## 3. Como navegar este conjunto

### 3.1 Por perfil de leitor

| Perfil | Leitura recomendada (por ordem) |
|--------|---------------------------------|
| **Arquitecto de Plataforma** | 00 → 01 → 02 → 04 → 06 → 09 (visão integral) |
| **Engenheiro de Canais/Meta** | 00 → 01 → 08 |
| **Engenheiro de IA/Runtime** | 00 → 02 → 05 → 06 |
| **Engenheiro de Comércio/Dados** | 00 → 03 → 06 → 05 |
| **Engenheiro de Pagamentos** | 00 → 04 → 08 → 03 |
| **Engenheiro de Segurança/Compliance** | 00 → 08 → 04 → 01 |
| **DevOps/SRE** | 00 → 09 → 01 → 02 |
| **Responsável de Produto** | 00 → 10 → 05 → ../exploracao/05 (estratégia) |
| **Operações / rede de agentes** | 10 → 07 → 04 |
| **Onboarding** | 00 → ../exploracao/13 (big picture) → subsistema específico |

### 3.2 Por camada arquitectural

| Camada | Documentos |
|--------|------------|
| **Arquitectura global** | 00 |
| **Canais (L4)** | 01 |
| **Plano de agentes (L3)** | 02 |
| **Core de negócio** | 03, 04 |
| **Descoberta e atenção** | 05 |
| **Dados e inteligência (L1)** | 06 |
| **Operação física** | 07, 09 |
| **Transversal (segurança, governação)** | 08, 10 |

### 3.3 Por fase do roadmap

| Fase | Documentos relevantes |
|------|-----------------------|
| **Fase 0 — Piloto (0–3 meses)** | 00, 01, 02, 03, 04 (referências), 09 |
| **Fase 1 — Clusters (3–12 meses)** | 05, 07, 10, 06 (eventos) |
| **Fase 2 — Escala (12–24 meses)** | 06 (Score), 05 (AdsEngine), 04 (payouts), 09 (Luanda) |
| **Contínuo** | 08, 10 |

---

## 4. Hierarquia documental e dependências

```
        ../exploracao/01–07 Exploração: estratégia, modelo, stress-tests
        ../exploracao/08–12 Exploração: desenhos de arquitectura
        ../exploracao/13    Exploração: big picture
                                │
                                ▼  (consolidação — este conjunto prevalece)
                  00 Arquitectura da Solução
                                │
        ┌───────────────┬───────┴───────┬────────────────┐
        ▼               ▼               ▼                ▼
  01 Canais e     02 Agent Runtime  03 Core de       04 Pagamentos
     Fluxo Dual      e Verticais       Comércio         e Liquidação
        │               │               │                │
        └───────┬───────┴───────┬───────┴────────────────┘
                ▼               ▼
        05 Índice e       06 Dados, Eventos
          Motor de          e Analytics
          Atenção              │
                │               ▼
                │       07 Geo e Logística
                │               │
                ▼               ▼
        08 Segurança      09 Topologia,
          e Conformidade    Operação e Escala
                            │
                            ▼
                  10 Onboarding e Governação
                            │
                            ▼
              P1: 11 Contratos · 12 Conformidade · 13 RTM
```

---

## 5. Decisões de arquitectura (ADRs) — síntese

Os 20 ADRs canónicos estão definidos no [00_Arquitectura_Solucao.md](00_Arquitectura_Solucao.md) §8
e referenciados por código ao longo de todos os documentos.

| ADR | Decisão | Estado | Doc principal |
|-----|---------|--------|---------------|
| ADR-001 | Cloud API oficial + coexistência; gateway não-oficial banido de produção | Ratificado* | 01 |
| ADR-002 | Core conversacional em LangGraph próprio; Dify/n8n vedados a multi-tenant | Ratificado | 02 |
| ADR-003 | Medusa v2+Mercur como registo de comércio; índice de pesquisa custom | Ratificado (Mercur: spike) | 03, 05 |
| ADR-004 | Pagamentos via facilitador (ProxyPay); liquidação sempre directa à PME | Ratificado* | 04 |
| ADR-005 | APIs de LLM até ao break-even; LiteLLM desde o dia 1 | Ratificado | 02 |
| ADR-006 | Postgres único (registo+vectores) até aos gargalos mapeados | Ratificado | 06 |
| ADR-007 | Preço/stock nunca no prompt; validador de citação obrigatório | Ratificado | 02, 03 |
| ADR-008 | Hosting JNB/CPT no MVP; Luanda quando compliance/parceria exigir | Ratificado | 09 |
| ADR-009 | Event bus BullMQ com outbox transaccional; Kafka só na escala | Ratificado | 06 |
| ADR-010 | PII minimizada (msisdn HMAC); consentimento no 1º contacto (Lei 22/11) | Ratificado | 08 |
| ADR-011 | Fluxo dual de canais (número da plataforma e/ou da PME) | Ratificado | 01 |
| ADR-012 | Verticais como configuração sobre o core | Ratificado | 02, 10 |

\* **Ratificado com dependência de validação:** ADR-001 depende da elegibilidade da coexistência
em Angola (V2) e ADR-004 depende do onboarding ProxyPay/banco (V6) — ver §5.1.

### 5.1 Estado de ratificação vs. validações de mercado (`../exploracao/07`)

A documentação não antecipa certeza que o mercado ainda não deu. Estado das hipóteses críticas:

| # | Hipótese | Estado | Onde é assumida |
|---|----------|--------|-----------------|
| V1 | 20 PMEs formais pagam por Loja no WhatsApp / Factura AI | **Em validação** | 00 §13, 10 |
| V2 | Coexistência app↔API funciona em Angola (+244) | **Em validação** (elegibilidade publicada; falta spike) | 01 |
| V3 | Custo/conversa comporta unit economics por categoria | **Em validação** | 02, 04, 09 |
| V4 | Meta AI não cobre o gap local (índice = moat) | **Em validação** | 05 |
| V5 | STT PT-AO robusto; Kimbundu via handoff | **Em validação** | 02 |
| V6 | Onboarding ProxyPay/banco em 2–6 semanas | **Em validação** | 04, 09 |
| V7 | PMEs aceitam publicar preço (senão: comparar disponibilidade/reputação) | **Em validação** — desenho prevê os dois modos | 05 |
| V8 | Rede de agentes à comissão com fraude controlada | **Em validação** | 10 |
| — | AdsEngine, Kambá Score, Diáspora | **Proposta** (fase 3; fora do caminho crítico) | 05, 06, 04 |

**Regra:** nenhum documento trata uma hipótese (Em validação) como facto; cada secção que dependa
dela declara a dependência e o desenho alternativo (ex.: 01 prevê fallback sem coexistência; 05
prevê ranking sem preço).

---

## 6. Ligação com os outros conjuntos

- **Biblioteca de exploração** (`../exploracao/01`–`../exploracao/13`, índice em `../INDICE.md`): o trabalho de
  investigação — mercado, modelo de negócio, stress-tests, desenhos preliminares. Fonte deste
  conjunto (matriz §2.1); em divergência, **este conjunto prevalece**.
- **Documento mestre** (`../00-KAMBA-documento-mestre.md`): compilação da biblioteca de exploração.
- **Backlog executável:** [`../../specs/INDICE.md`](../../specs/INDICE.md) — os tickets KAM-NNN
  derivados deste conjunto técnico e das validações V1–V8. Vive na raiz do repositório, não
  sob `docs/` (KAM-128).

---

## 7. Aprovação, versionamento e manutenção

- **Aprovação:** cada documento contém a sua tabela de aprovação (Arquitecto de Plataforma · Responsável de Segurança · Responsável de Produto) — **em branco até revisão humana real**; nenhuma aprovação é preenchida por procuração.
- **Versionamento:** SemVer para documentos formais (MAJOR = reformulação de arquitectura; MINOR = novo capítulo; PATCH = correcções).
- **Manutenção:** divergências entre documento e código/desenho são bugs documentais; novas decisões arquitecturais registadas como ADRs; rate cards e dados de mercado revalidados trimestralmente (watch list no doc 09 §8); o estado das validações (§5.1) é actualizado a cada resultado de campo.

| Versão | Data | Descrição | Autor |
|--------|------|-----------|-------|
| 1.0 | Outubro 2026 | Emissão inicial do conjunto técnico (11 documentos) derivado da big picture. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Análise adversarial aplicada: fonte alargada a todo o conjunto de exploração (matriz §2.1); estados de ratificação V1–V8 (§5.1); regra de precedência; remediação P1 planeada (Contratos, Conformidade, RTM); nome de marca marcado como provisório. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | **Validação adversarial das specs** (`../analises/ANALISE-01-validacao-adversarial-specs.md`): 24 achados (6 P0, 9 P1, 9 P2). Gate: nenhum ticket `specs/` antes da remediação dos 6 P0. Estados ADR-001/004/005 reclassificados como dependentes de validação. | Auditoria interna |
| 1.3 | Outubro 2026 | KAM-128: conjunto movido para `docs/tecnica/`; referências a irmãos passam a nuas (`NN_…`), as da biblioteca a `../exploracao/NN-…`; `specs/` deixa de constar como «a criar» (§6). | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | KAM-130: **20** ADRs canónicos nas duas afirmações do documento (§ do catálogo e §5). Diziam doze, de quando eram doze. | Equipa KAMBÁ |

---

*Fim do Índice Técnico. Para a narrativa de negócio, ver a biblioteca de exploração (`../INDICE.md`).*

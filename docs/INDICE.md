# Documentação — KAMBÁ (Plataforma AI-First de Comércio Conversacional para Angola)

**Produto:** KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para o mercado angolano
**Natureza:** Produto/plataforma standalone (sem cliente institucional)
**Documento-fonte:** Vídeo "Renda Invisível" (@manual.da.riqueza93) → decomposto e reconstruído para o mercado angolano
**Versão do conjunto documental:** 1.6
**Data de emissão:** Outubro de 2026
**Classificação:** Documento de Referência — Interno

---

## 1. Propósito deste conjunto documental

Este conjunto materializa a **estratégia e o desenho completo** da KAMBÁ: da adaptação dos "10
negócios invisíveis" ao mercado angolano, ao enquadramento em plataforma de dois lados inspirada
no modelo Google (atenção gratuita, intenção paga), à arquitetura técnica AI-first de nível de
engenharia, com stress-tests adversariais em duas rondas e síntese visual do ecossistema.

A tese que atravessa todos os documentos: **o "motor de busca" da economia informal angolana não é
uma caixa de pesquisa — é uma conversa de WhatsApp.** A plataforma organiza esse comportamento
existente através de três fundações não-negociáveis: **fluxo dual de canais** (número da plataforma
e/ou número da PME, com coexistência oficial), **core próprio com verticais finas** (construir
primitivas uma vez; módulos são configuração + agentes sobre elas) e **dinheiro com liquidação
direta à PME** (a plataforma nunca retém fundos — BNA).

O conjunto destina-se a: fundadores; arquitectos de plataforma; engenheiros de runtime, dados e
integrações; responsáveis de produto; parceiros estratégicos (bancos, telcos, EMIS/facilitadores);
e revisão estratégica e técnica.

---

## 2. Índice de documentos

Este conjunto vive sob `docs/`; `specs/` fica na raiz do repositório, por ser o backlog
executável e o contrato de execução, não material de leitura (KAM-128):

```text
docs/
  INDICE.md                      este índice
  00-KAMBA-documento-mestre.md   compilação da biblioteca de exploração (gerado)
  compilar-mestre.sh             regenera o mestre a partir de exploracao/
  exploracao/                    biblioteca exploratória 01–14 — histórica
  tecnica/                       conjunto formal por subsistema + evidencia/E1–E5
  analises/                      análises adversariais (ANALISE-NN-<slug>.md)
  adr/                           ADRs locais (ADR-L###)
  evidencia/                     evidência de execução por ticket
specs/                           backlog executável (KAM-NNN), na raiz do repositório
  tickets/                       um ficheiro por ticket do EPIC-01 (43; KAM-155)
```

| Nº | Documento | Foco | Ficheiro | Linhas |
|----|-----------|------|----------|--------|
| 00 | **Documento Mestre** | Compilação integral das partes 01–13 num único ficheiro (artefacto gerado; fonte de verdade = ficheiros individuais) | [00-KAMBA-documento-mestre.md](00-KAMBA-documento-mestre.md) | 3.108 |
| 01 | **Modelo de Negócios: 10 Ideias AI-First para Angola** | Adaptação dos 10 negócios do vídeo-fonte ao contexto angolano (pagamentos, informalidade, marketplaces); stack comum; plano de 90 dias | [01-modelo-negocios-angola-ai-first.md](exploracao/01-modelo-negocios-angola-ai-first.md) | 220 |
| 02 | **Enquadramento em Plataforma** | Agência-como-software → plataforma modular → marketplace; cunha (Rececionista AI); moat composto; roadmap | [02-enquadramento-plataforma-angola.md](exploracao/02-enquadramento-plataforma-angola.md) | 193 |
| 03 | **Modelo Google para Angola** | Três lados (consumidores grátis / PMEs freemium / anunciantes pagos); 5 linhas de receita ordenadas; flywheel; lições Ayoba/M-Pesa/Jumia/WeChat | [03-modelo-plataforma-google-angola.md](exploracao/03-modelo-plataforma-google-angola.md) | 216 |
| 04 | **Pontos Cegos — Ronda 1** | Stress-test inicial: 13 pontos (índice inexistente, frescura, custo do lado grátis, Meta concorrente, confiança social, rails EMIS, go-to-market relacional…) | [04-pontos-cegos-plataforma.md](exploracao/04-pontos-cegos-plataforma.md) | 150 |
| 05 | **Estratégia: Loja no WhatsApp + Fluxo Dual** | Digitalização distribuída (a PME constrói o índice por incentivo próprio); Fluxo A (nº PME) vs Fluxo B (nº plataforma: handoff B1 / venda assistida B2); PME "light"; clusters | [05-estrategia-loja-no-whatsapp.md](exploracao/05-estrategia-loja-no-whatsapp.md) | 139 |
| 06 | **Expansões da Plataforma** | 5 camadas (confiança, transação, dinheiro, crescimento, dados); reputação verificada, logística federada, Kambá Score, diáspora, Factura AI, vitrine SEO; o que NÃO considerar | [06-expansao-plataforma.md](exploracao/06-expansao-plataforma.md) | 129 |
| 07 | **Pontos Cegos — Ronda 2** | Stress-test do novo modelo: opacidade cultural de preços, paradoxo da "renda invisível", problema do número, Shopify vs Google, comprovativos falsos, unit economics; 8 validações | [07-pontos-cegos-2.md](exploracao/07-pontos-cegos-2.md) | 165 |
| 08 | **Arquitetura Técnica v2 (o Produto)** | Cloud API + coexistência (Angola elegível); Chatwoot self-hosted; LangGraph; Medusa v2+Mercur; ProxyPay; geo stack; custos por estágio; build de 12 semanas | [08-arquitetura-tecnica-v2.md](exploracao/08-arquitetura-tecnica-v2.md) | 336 |
| 10 | **Arquitetura de Plataforma Holística (a Visão)** | 5 camadas L0–L4; 9 primitivas construídas uma vez; verticais como configuração; dados por finalidade (registo/descoberta/analytics); roadmap por fase | [10-arquitetura-plataforma-holistica.md](exploracao/10-arquitetura-plataforma-holistica.md) | 233 |
| 11 | **Desenho Detalhado de Engenharia (o Como)** | Topologia de serviços; DDL do schema platform; contratos de eventos; grafo LangGraph do Vendedor; fluxos de sequência; pesquisa híbrida SQL; segurança; CI/CD; 10 ADRs | [11-arquitetura-detalhada-engenharia.md](exploracao/11-arquitetura-detalhada-engenharia.md) | 352 |
| 12 | **Diagramas C4 e Fluxogramas (o Visual)** | C1 contexto → C4 código em Mermaid; 6 fluxogramas end-to-end (venda B1/B2, onboarding, handoff, ciclo de vida da encomenda, mapa de eventos) | [12-diagramas-c4-fluxogramas.md](exploracao/12-diagramas-c4-fluxogramas.md) | 469 |
| 13 | **Big Picture do Ecossistema (a Síntese)** | Mapa único: core vs verticais vs ferramentas vs integrações; abstrações; 4 percursos de onboarding; governação; mapa de dinheiro; motor de atenção; métricas; linhagem de dados | [13-big-picture-ecossistema.md](exploracao/13-big-picture-ecossistema.md) | 385 |
| 14 | **Tese Mínima e Plano de Validação** | Escopo do Piloto (PMEs formais; Rececionista + Loja no número da PME); 9 hipóteses com critério; caminho build-first com esqueleto andante e regra de dois; pivôs e paragem | [14-tese-minima-e-plano-de-validacao.md](exploracao/14-tese-minima-e-plano-de-validacao.md) | — |
| 09 | ~~Arquitetura Técnica v1~~ | **Desatualizada** — substituída pela v2 (doc 08); mantida apenas para histórico | [09-arquitetura-tecnica-v1-DESATUALIZADO.md](exploracao/09-arquitetura-tecnica-v1-DESATUALIZADO.md) | 226 |

**Total: 14 documentos activos de estratégia/exploração (01–08, 10–14, mais o 00 compilado) e 1 histórico (09).**

> ⚠️ **Os documentos 08, 10, 11, 12 e 13 são exploratórios e estão parcialmente desactualizados.** A pesquisa de Outubro de 2026 corrigiu vários pontos (custos Meta, grupos, MinIO, licenças, alojamento, identidade, pagamentos). A fonte de verdade técnica é agora o **conjunto formal em [`tecnica/`](tecnica/INDICE.md)** (11 documentos, 20 ADRs, evidência em `tecnica/evidencia/`), que prevalece em caso de divergência. O documento mestre (00) é gerado por `compilar-mestre.sh` e **já inclui o 14**, mas herda o estado exploratório dos documentos que compila: não decida com ele.

> Os documentos 04 e 07 são os stress-tests adversariais que corrigiram o rumo (índice, opacidade
> de preços, segmento de PMEs, unit economics). O documento 05 introduziu a inversão mais
> importante: a digitalização do comércio angolano como **subproduto da venda**, não como custo.
> Os documentos 08, 10 e 11 formam a torre técnica em três níveis (produto → plataforma →
> engenharia); o 12 dá a forma visual e o 13 a síntese navegável.

---

## 3. Como navegar este conjunto

### 3.1 Por perfil de leitor

| Perfil | Leitura recomendada (por ordem) |
|--------|---------------------------------|
| **Fundador / decisor** | 13 → 01 → 02 → 03 → 07 (teses + riscos) |
| **Investidor / parceiro estratégico** | 13 → 03 → 05 → 04+07 (diligência adversarial) |
| **Responsável de Produto** | 13 → 05 → 06 → 02 → 08 |
| **Arquitecto de Plataforma** | 13 → 08 → 10 → 11 → 12 (torre técnica completa) |
| **Engenheiro (runtime/dados/integrações)** | 08 → 11 → 12 → subsistema específico na 10 |
| **Comercial / agentes de campo** | 01 → 05 (percursos de onboarding) → 13 §5 |
| **Compliance / jurídico** | 08 §7 → 11 §9 → 07 (riscos regulatórios) |
| **Onboarding geral** | 13 (big picture) → 00 (documento mestre) |

### 3.2 Por camada documental

| Camada | Documentos |
|--------|------------|
| **Estratégia e modelo de negócio** | 01, 02, 03 |
| **Validação adversarial (stress-tests)** | 04, 07 |
| **Estratégia de produto e expansão** | 05, 06 |
| **Arquitectura (produto → plataforma → engenharia)** | 08, 10, 11 |
| **Visual e síntese** | 12, 13 |
| **Compilação / histórico** | 00, 09 |

### 3.3 Por fase do roadmap

| Fase | Documentos relevantes |
|------|-----------------------|
| **Tese e mercado** | 01, 02, 03 |
| **Diligência adversarial** | 04, 07 (+ 8 validações da 07 §final) |
| **Piloto (0–3 meses)** | 05, 08 §9 (build de 12 semanas), 11 |
| **Clusters (3–12 meses)** | 06 (camadas 1–2), 10 §7 |
| **Escala (12–24 meses)** | 03 (linhas 4–5), 06 (camadas 3–5), 10 §7 |

---

## 4. Hierarquia documental e dependências

```
              Vídeo-fonte: "Renda Invisível" (10 negócios)
                                │
                                ▼
                01 Modelo de Negócios (Angola, AI-first)
                                │
                                ▼
                02 Enquadramento em Plataforma (A→B→C)
                                │
                                ▼
                03 Modelo Google (atenção grátis, intenção paga)
                                │
                                ▼
                04 Pontos Cegos — Ronda 1 ──────────┐
                                │                   │ corrige
                                ▼                   ▼
                05 Estratégia: Loja no WhatsApp + Fluxo Dual
                                │
                                ▼
                06 Expansões (5 camadas)
                                │
                                ▼
                07 Pontos Cegos — Ronda 2 (8 validações)
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
        08 Arquitectura v2                10 Arquitectura
           (o produto)                       Holística (a visão)
                │                               │
                └───────────────┬───────────────┘
                                ▼
                11 Desenho de Engenharia (o como)
                                │
                                ▼
                12 Diagramas C4 e Fluxogramas (o visual)
                                │
                                ▼
                13 Big Picture do Ecossistema (a síntese)
                                │
                                ▼
                00 Documento Mestre (compilação 01–13)
```

Nota: o documento 09 (v1) está fora da linha — desatualizado, substituído pelo 08.

---

## 5. Decisões de arquitectura (ADRs) — síntese

Os **20** ADRs canónicos estão definidos em [`tecnica/00_Arquitectura_Solucao.md`](tecnica/00_Arquitectura_Solucao.md) §8 e referenciados ao longo dos documentos técnicos. O [11-arquitetura-detalhada-engenharia.md](exploracao/11-arquitetura-detalhada-engenharia.md) §12 tem **dez ADRs próprios e históricos**, que não são o canon: a biblioteca exploratória não é fonte de verdade.

| ADR | Decisão | Doc principal |
|-----|---------|---------------|
| ADR-01 | Cloud API oficial + coexistência; gateway não-oficial banido de produção | 08 §2 |
| ADR-02 | Core conversacional em LangGraph próprio; Dify/n8n vedados a multi-tenant (licença) | 10 §3, 11 §4 |
| ADR-03 | Medusa v2+Mercur como registo de comércio; índice de pesquisa custom | 11 §2 |
| ADR-04 | ProxyPay como adapter primário; liquidação sempre direta à PME | 08 §5 |
| ADR-05 | APIs de LLM até >0,5–1M msgs/mês; LiteLLM desde o dia 1 | 08 §3, 11 §4 |
| ADR-06 | Postgres único (registo+vetores) até aos gargalos mapeados | 11 §11 |
| ADR-07 | Preço/stock nunca em embeddings/prompts; validador de citação obrigatório | 08 §3, 11 §4 |
| ADR-08 | Hosting JNB/CPT no MVP; Luanda quando compliance/parceria exigir | 08 §7 |
| ADR-09 | Event bus BullMQ com outbox transaccional; Kafka só na escala | 11 §3 |
| ADR-10 | msisdn com HMAC; logs sem conteúdo; consentimento no 1º contacto (Lei 22/11) | 11 §2/§9 |

A estas somam-se duas decisões de produto com força de ADR: **fluxo dual de canais** (número da
plataforma e/ou número da PME — doc 05 §4, 08 §2.1a) e **verticais como configuração sobre o
core** (doc 10 §3, 13 §3).

---

## 6. Ligação com outros conjuntos

- **Documento mestre:** [00-KAMBA-documento-mestre.md](00-KAMBA-documento-mestre.md) compila as
  partes 01–13 para leitura sequencial ou partilha (regenerado a cada alteração).
- **Backlog executável:** [`../specs/INDICE.md`](../specs/INDICE.md) — os tickets KAM-NNN
  derivados do plano de build de 12 semanas (08 §9) e das 8 validações (07 §final). Vive na
  raiz do repositório, não sob `docs/` (KAM-128).
- **Referência de estilo:** conjunto documental AOS (`C:\Jimy\AOS\tecnica\INDICE.md`), cuja forma
  este índice segue.

---

## 7. Aprovação, versionamento e manutenção

- **Aprovação:** revisão estratégica (fundador) + revisão técnica (arquitecto) por documento.
- **Versionamento:** SemVer para o conjunto (MAJOR = mudança de tese; MINOR = novo documento;
  PATCH = correcções e actualizações de fontes).
- **Manutenção:** divergências entre documentos são bugs documentais; dados de mercado e rate
  cards (Meta, EMIS, facilitadores) revalidados trimestralmente (watch list no doc 08 §10);
  o documento mestre (00) é artefacto compilado — **nunca editado à mão**.

| Versão | Data | Descrição | Autor |
|--------|------|-----------|-------|
| 1.0 | Outubro 2026 | Emissão inicial: estratégia (01–03) derivada do vídeo-fonte + pesquisa de mercado angolano. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Validação adversarial: stress-tests 04 e 07; inversão para digitalização distribuída (05); expansões (06). | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | Arquitectura técnica v2 (08) após pesquisa em 4 frentes; v1 deprecada (09). | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | Arquitectura de plataforma holística (10); fluxo dual propagado a todos os documentos. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | Desenho de engenharia (11) com DDL, contratos de eventos e 10 ADRs. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | Diagramas C4 e fluxogramas (12); documento mestre compilado (00). | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | Big picture do ecossistema (13) incluindo governação, mapa de dinheiro e motor de atenção; índice formal (este documento). Total: 13 documentos activos. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | KAM-128: conjunto reorganizado sob `docs/` (biblioteca em `exploracao/`, conjunto formal em `tecnica/`, análises em `analises/`); árvore registada no §2; `specs/` deixa de constar como «a criar» (§6); mestre passa a gerado por `compilar-mestre.sh` e a incluir o 14. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | KAM-155: a árvore do §2 passa a mostrar `specs/tickets/`, onde vivem os 40 ficheiros de ticket do EPIC-01. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | KAM-130: **20** ADRs (eram dezoito) e a grafia `activos` na norma do conjunto. **A base de contagem fica declarada e são duas:** o §2 conta **14** documentos *incluindo* o 00 compilado, e a linha 1.6 contou **13** *sem* ele. Os dois números estão certos para bases diferentes, e o defeito era o conjunto afirmar ambos sem dizer qual. A linha 1.6 **não** se reescreve: é o registo do que a 1.6 disse, e emendar um registo datado para caber no presente é a mesma classe de defeito ao contrário. | Equipa KAMBÁ |

---

*Fim do Índice. Para leitura única, usar o [Documento Mestre](00-KAMBA-documento-mestre.md); para começar, a [Big Picture](exploracao/13-big-picture-ecossistema.md).*

# Carta da KAMBÁ — Forma do Produto, Registo de Decisões e Definition-of-Done do Piloto

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | **Carta** — autoridade sobre a forma do produto no Piloto, as decisões e o *done* |
| Versão | **1.0 — PROPOSTA (por ratificar pelo fundador)** |
| Data | Outubro de 2026 |
| Estatuto | Uma vez ratificada, é a fonte única sobre *o que construímos no Piloto* e *o que está decidido*. Até à ratificação, nenhuma decisão aqui é FIXA. |

---

## 0. Porque esta Carta existe

A biblioteca exploratória (`../docs/exploracao/01`–`../docs/exploracao/13`) deixou três coisas por fixar, e o conjunto técnico (`../docs/tecnica/`) tornou-as visíveis:

1. **A forma do produto no Piloto** oscilava entre «marketplace de três lados estilo Google» e «ferramenta de loja no WhatsApp». A análise adversarial e o `../docs/exploracao/14` reduziram-na, mas não a congelaram.
2. **As decisões estão espalhadas** (ADRs, D1–D13, hipóteses H1–H9) e há factos centrais NÃO VERIFICADOS (coexistência em +244, política da Meta sobre agregador, onboarding bancário por PME).
3. **O risco dominante é paralisia analítica:** o `../docs/exploracao/07` §14 já o dizia — zero clientes pagantes e documentos a mais. Sem um *done* medível, o programa pode produzir documentação indefinidamente.

Esta Carta é deliberadamente curta. Não repete o *quê/como* (isso é o `00_System_Spec.md` e o `../docs/tecnica/`); fixa o **enquadramento**, o **registo de decisões** e o **critério de saída do Piloto**.

## 1. Hierarquia de documentos

| Camada | Documento | Autoridade |
|---|---|---|
| **Visão** | `../docs/exploracao/13-big-picture-ecossistema.md` e restante biblioteca `../docs/exploracao/01`–`../docs/exploracao/12` | Exploratória; **não** se edita em execução. Em divergência, prevalece o conjunto técnico |
| **Escopo do Piloto** | `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` | Tese mínima, hipóteses H1–H9, pivôs |
| **Carta (esta)** | `specs/00_KAMBA_Carta.md` | Forma do produto, registo de decisões, DoD do Piloto, regra de congelamento |
| **Arquitectura** | `../docs/tecnica/00_Arquitectura_Solucao.md` e `../docs/tecnica/01`–`10` | ADR-001–ADR-020, componentes, decisões abertas D1–D13 |
| **Evidência** | `../docs/tecnica/evidencia/E1`–`E5` | Factos com estado CONFIRMADO/INDÍCIO/NÃO VERIFICADO (2026-10-08) |
| **Especificação** | `specs/00_System_Spec.md` | Capacidades, domínio, KPIs e SLOs |
| **Dicionário** | `specs/02_Dicionario_de_Dados_Canonico.md` | Um nome por conceito; prevalece sobre `../docs/tecnica/` até KAM-111 |
| **Execução** | `specs/EPIC-*.md` → tickets KAM-NNN | Decompõem e medem-se contra o DoD desta Carta |
| **Engenharia** | `specs/01_Engineering_Standards_e_Handoff.md` | DoR/DoD por ticket, gates, convenções |

Em divergência sobre **a forma do produto ou o estado de uma decisão**, prevalece esta Carta (depois de ratificada). Em divergência técnica de detalhe, prevalece `../docs/tecnica/`.

## 2. A forma do produto (PROPOSTA)

> **A KAMBÁ do Piloto é um serviço que dá a uma PME formal angolana um assistente de atendimento e venda no seu próprio número de WhatsApp (Fluxo A, via Cloud API com coexistência), onboardado de forma automática e self-service, que responde a clientes, vende produtos e marca serviços com números sempre vindos de ferramentas, e confirma pagamentos só por evento autenticado — sem nunca deter fundos de terceiros.**

- **É:** um produto B2B por assinatura, com duas verticais de atendimento (**Vendedor** e **Serviços/Rececionista**) **e até quatro módulos de entrada** *owner-facing* (**Catálogo AI**, **Foto de produtos AI**, **Social AI** para publicação manual, **Orçamento expresso**), sobre um core partilhado, para PMEs **formais ou em formalização** (segmento A) em Luanda. Os módulos de entrada captam a PME e dão-lhe valor desde o primeiro dia, mesmo antes de o WhatsApp estar ligado (ADR-020).
- **NÃO é (no Piloto):**
  - um assistente de consumo no número da plataforma, nem Fluxo B, PME light ou índice federado (ADR-011; D2);
  - um marketplace com fundos retidos, escrow ou payouts (ADR-004; D8);
  - uma rede de agentes de campo (ADR-019);
  - um Kambá Score, AdsEngine, logística ou vitrine pública (Clusters/Escala);
  - uma app móvel: a interface é o WhatsApp mais um painel web mínimo;
  - publicação automática em redes sociais, Arquivo AI, Compras AI, consignação ou clube digital (Diferidos; D13).
- **Quem paga:** a PME, por **assinatura**; comissão sobre transacção desligada (ADR-017).
- **Resposta ao ponto de partida:** «a loja fala no WhatsApp que o cliente já conhece; a KAMBÁ está nos bastidores».

## 3. Como se usa a biblioteca exploratória

Os documentos `../docs/exploracao/01`–`../docs/exploracao/13` descrevem a **visão** (plataforma de três lados, verticais, diáspora, Score, API). Mantêm-se como horizonte. A execução mede-se contra o §5 desta Carta, não contra a visão.

## 4. Registo único de decisões

Cada decisão tem um estado: **FIXA** (não se re-litiga sem emenda), **CONDICIONAL** (fixa na invariante, dependente de um gatilho externo nomeado) ou **ABERTA** (por decidir, com dono e escalada). *Todas as classificações abaixo são propostas até à ratificação.*

### 4.1 Decisões arquitecturais (ADRs, `../docs/tecnica/00` §8)

| ADR | Assunto | Estado proposto | Gatilho / nota |
|---|---|---|---|
| ADR-001 | Cloud API + coexistência; Tech Provider; Embedded Signup v4; GWY único | **CONDICIONAL** | Coexistência em +244 NÃO VERIFICADA → KAM-100 |
| ADR-002 | LangGraph biblioteca MIT; Dify/n8n/Typebot vedados a tenants | FIXA | Licenças confirmadas (E4) |
| ADR-003 | Medusa v2 sujeito a spike; fallback | **CONDICIONAL** | KAM-041 **feito** (2026-10-27): recomendação é a opção B com a autoridade da reserva no `platform` (`../docs/spikes/KAM-041-medusa.md`). Gatilho em falta: ratificação do fundador |
| ADR-004 | Facilitador; liquidação directa; plataforma sem fundos | FIXA (invariante) | Enquadramento BNA a confirmar por parecer (D8) |
| ADR-005 | LLM via LiteLLM ≥ 1.83.0 por digest | FIXA | — |
| ADR-006 | Postgres 18 único com `iterative_scan`/partição | FIXA | Reavaliar no teste de carga (KAM-084) |
| ADR-007 | Preço/stock nunca em prompts; validador de citação | FIXA | — |
| ADR-008 | Nada sai de Angola sem registo APD; Luanda como alvo | **CONDICIONAL** | D1, D9, parecer |
| ADR-009 | Event bus BullMQ com outbox | FIXA | — |
| ADR-010 | Identidade de contacto em duas camadas | FIXA | — |
| ADR-011 | Fluxo dual como costura; só Fluxo A no Piloto | FIXA (Piloto) | Reabre com D2 |
| ADR-012 | Verticais como configuração; regra de dois | FIXA | Provada em KAM-039/108 |
| ADR-013 | Pagamento só por evento autenticado; ManualProvider limitado | FIXA | — |
| ADR-014 | Storage atrás de `StorageProvider`; MinIO excluído | FIXA (invariante) | Implementação: D6 |
| ADR-015 | RLS `FORCE` + classes de tool | FIXA | — |
| ADR-016 | Sem COD em numerário via estafeta | FIXA | Relevante em Clusters |
| ADR-017 | Comissões só após 1.ª venda paga autenticada; assinatura primeiro | FIXA | — |
| ADR-018 | Observabilidade leve no Piloto; *golden set* pelas três origens do KAM-040 (`sintetico`, `t2_anonimizado`, `real_consentido`), com registo de consentimento obrigatório nos reais | FIXA | Origem decidida pelo fundador a 2026-10-30 (`../docs/adr/ADR-L006-origem-do-golden-set.md`) |
| ADR-019 | Onboarding self-service automático; humano por excepção | FIXA (decisão do fundador) | Reavaliar se a fraude de registo exceder o limiar (§6) |
| ADR-020 | Módulos de entrada no Piloto, máx. 4, owner-facing, com o dono no circuito; canal do dono; sem publicação automática | FIXA (decisão do fundador, 2026-10-09) | Reavaliar pelos critérios de abate H10–H12 (KAM-127) e se a Fase 0 derrapar |

### 4.2 Decisões de programa (D-series, `../docs/tecnica/00` §13.3)

| D | Assunto | Estado | Dono (papel) | Ticket que a fecha | Escalada se atrasar |
|---|---|---|---|---|---|
| D1 | Alojamento: Luanda ou JNB/CPT com procedimento APD | ABERTA | Produto + Segurança | KAM-105 | Fundador decide até à semana 3; sem D1 não há dados reais |
| D2 | Fluxo B / número agregador | **CONDICIONAL** | Produto | KAM-101 | Gatilho: resposta escrita da Meta |
| D3 | Medusa puro / Mercur / registo próprio | ABERTA | Arquitecto | KAM-041 | Spike **feito** (2026-10-27) com recomendação fundamentada (`../docs/spikes/KAM-041-medusa.md` §8). Falta assinar: Arquitecto de Plataforma e Responsável de Segurança; e ratificar: fundador |
| D4 | Facilitador e onboarding bancário por PME | ABERTA | Produto | KAM-103 | Sem contrato à semana 6: Piloto fica em `ManualProvider` |
| D5 | Tech Provider directo ou BSP | ABERTA | Produto | KAM-102 | Sem Tech Provider à semana 6: pára o canal (KAM-016) |
| D6 | StorageProvider: SeaweedFS ou S3 gerido | ABERTA | SRE | KAM-011 | Decide com D1 |
| D7 | Parceiro de factura AGT | **CONDICIONAL** | Produto | — (Clusters) | Gatilho: confirmação escrita AGT sobre 2027 |
| D8 | Enquadramento BNA do modelo facilitador e das comissões | ABERTA | Produto + jurídico | KAM-104 | Sem parecer: comissão sobre transacção fica desligada (ADR-017) |
| D9 | Papel da KAMBÁ na Lei 22/11 e entidade que paga custos em USD | ABERTA | Fundador + jurídico | KAM-104, KAM-105 | Antes de dados reais |
| D10 | Canal operacional da KAMBÁ (prestadores e suporte) | **CONDICIONAL** | Produto | KAM-101 | Gatilho: resposta da Meta; entretanto canal do fundador |
| D11 | Kambá Score como informação de crédito | **CONDICIONAL** | Produto + jurídico | — (Escala) | Gatilho: Escala |
| D12 | CDN/WAF como subprocessador; licença do Redis (Valkey) | ABERTA | SRE + jurídico | KAM-076, KAM-077 | Antes de produção |
| D13 | Publicação automática em Instagram/Facebook (Social AI) | **CONDICIONAL** | Produto | KAM-121, KAM-122 (Piloto: publicação manual) | Gatilho: App Review da Meta e procura validada (E5, H10) |

### 4.3 Hipóteses de negócio (`../docs/exploracao/14` §2)

| H | Hipótese | Critério (*proposta*) | Mede-se em |
|---|---|---|---|
| H1 | PMEs formais pagam | ≥ 5 convertem a pago no fim dos 30 dias de piloto gratuito (desambiguação do `../docs/exploracao/14` Regra 4 vs §2) | KAM-109 |
| H2 | O preço pode ser publicado ou respondido | ≥ 50% aceitam para ≥ 70% do catálogo | KAM-106 |
| H3 | Coexistência funciona em +244 | 3/3 números sem perda de histórico | KAM-100 |
| H4 | A Meta aceita o caso de uso | Resposta escrita ou aprovação | KAM-101, KAM-102 |
| H5 | Existe via de cobrança autenticada | Prazo e custo por PME conhecidos e ≤ 6 semanas | KAM-103 |
| H6 | Custo de IA fecha com a assinatura | ≤ 15% da mensalidade | KAM-109 |
| H7 | O bot não fica sozinho em apuros | ≥ 85% sem handoff errado | KAM-040 |
| H8 | A PME mantém o catálogo | ≥ 60% correctos em auditoria | KAM-109 |
| H10 | Os módulos de entrada atraem PMEs | ≥ 60% das PMEs onboardadas usam ≥ 1 módulo nas 2 primeiras semanas (*proposta*) | KAM-127 |
| H11 | Os módulos levam ao atendimento | ≥ 30% das PMEs que entram por um módulo activam o Vendedor/Serviços aos 30 dias (*proposta*) | KAM-127 |
| H12 | O custo fecha e há disposição a pagar | Custo ≤ 15% do preço do módulo; ≥ 3 PMEs pagam por módulo isolado (*propostas*) | KAM-127 |
| H9 | Retenção | ≥ 70% activas ao dia 60, **das PMEs activadas até à semana 4**; as restantes medem-se após o Piloto (o dia 60 não cabe na janela da semana 7–12 para PMEs mais tardias) | KAM-109 |

Os limiares são propostas. Se H1 ou H5 falharem, a tese muda antes de mais código (`../docs/exploracao/14` §6).

## 5. Definition-of-Done do Piloto

O **Piloto** está *feito* quando **todos** os seguintes forem verdes. Nenhum item é substituível por documentação.

**Produto e negócio**
- [ ] **Fluxo A em produção** com ≥ 10 PMEs activas, onboardadas por **self-service automático**; ≥ 80% das activações sem intervenção humana (ADR-019).
- [ ] **H1:** ≥ 5 PMEs convertem a pago no fim do piloto gratuito de 30 dias. **H9:** ≥ 70% activas ao dia 60, das PMEs activadas até à semana 4.
- [ ] **H6:** custo de IA por conversa ≤ 15% da mensalidade, medido em ≥ 500 conversas reais. **H8:** ≥ 60% de catálogos correctos em auditoria.

**Fiabilidade e segurança**
- [ ] **Esqueleto andante provado (KAM-108):** uma conversa real cria um pedido, o evento de pagamento é consumido pela outra vertical, sem excepções no core.
- [ ] **0** fugas entre tenants ou contactos, **0** pedidos duplicados e **0** números divergentes no conjunto adversarial; **H7 ≥ 85%** de handoff correcto.
- [ ] **100%** das confirmações de pagamento por evento autenticado (facilitador ou `ManualProvider` auditado e limitado).
- [ ] **Gates de CI fail-closed verdes** (`01_Engineering_Standards_e_Handoff.md` §4) e revisão de segurança independente concluída (KAM-074).

**Conformidade e operação**
- [ ] **Procedimento APD concluído** para todos os destinos de dados pessoais em produção (D1, D9); **DPA aceite em 100%** dos tenants activos; parecer jurídico recebido sobre D8.
- [ ] **Resposta escrita da Meta** (ou decisão registada de operar sem ela) sobre D2, e Tech Provider activo (D5).
- [ ] **Backups com restauro testado e RTO medido**; runbooks e SLOs em vigor (EPIC-08).

**Indicadores dos módulos de entrada (não bloqueiam o gate; ADR-020):** H10, H11 e H12 medidos e registados (KAM-127); decisão por módulo de manter, ajustar ou abater. O Piloto **não** fica a aguardar por estes indicadores para se declarar feito, de modo a que os módulos de entrada nunca possam atrasar o core.

**Não conta como *done*:** um piloto com PMEs onboardadas à mão pela equipa, pagamentos confirmados por comprovativo em imagem, ou dados pessoais enviados a subprocessadores fora de Angola sem registo.

## 6. Regra de congelamento e fronteiras

1. **Nenhuma decisão FIXA se re-litiga** sem uma **emenda** registada no §7 (o quê, porquê, quem aprovou).
2. Uma decisão **CONDICIONAL** só «abre» quando o seu gatilho nomeado ocorre.
3. Uma decisão **ABERTA** tem sempre dono e escalada (§4.2).
4. **Descobrir dívida escondida** (facto novo verificável: código, build, resposta de terceiro) não é re-litigar: regista-se como emenda e executa-se.
5. **Árbitro:** o Arquitecto de Plataforma e o Responsável de Segurança decidem por escrito se uma invocação do ponto 4 assenta em facto novo verificável; caso contrário é re-litígio e é recusada.
6. **Tripwire de falsificação:** se numa janela de 30 dias **≥ 2 decisões FIXAS forem reabertas**, ou **≥ 2 invocações do ponto 4 forem recusadas**, o mecanismo falhou e a Carta é revista.
7. **Tripwire do ADR-019:** se a fraude de registo em self-service ultrapassar o limiar (*proposta*: > 5% das PMEs activadas banidas por T&S em 60 dias), reabre-se a decisão (K2 obrigatório ou agente presencial).
8. **Fronteira de escopo:** o que está em `INDICE.md` §6 («o que fica fora») não entra no Piloto sem emenda.

## 7. Controlo de versões e emendas

| Versão | Data | Descrição | Aprovação |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão da Carta como **proposta**: forma do produto, registo de decisões e DoD do Piloto. Aguarda ratificação do fundador. | Pendente |
| 1.1 | Outubro 2026 | **Emenda E-01 — dispensa da dependência `KAM-003 ← KAM-111`.** *O quê:* o KAM-003 (schema `platform`) passa a poder executar sem o KAM-111 (dicionário canónico e lint de nomes) estar `Done`; a dependência sai do backlog mestre e do epic, dos dois lados. *Porquê:* o KAM-111 é um ticket `M` que reconcilia dez documentos, e o caminho crítico do Piloto atravessa o KAM-003 (bloqueia onze tickets). A dívida que a dispensa cria está mitigada e não escondida: os oito nomes de `platform` que faltavam ao dicionário foram escritos nele **antes** do DDL (emenda 1.2 do dicionário, §3.2), com a razão de cada escolha. *O que fica em dívida:* o lint de nomes (gate 3b) continua a ser do KAM-111 e não existe, pelo que nada por máquina impede o próximo DDL de divergir; e duas divergências de `../docs/tecnica/` ficam por corrigir (`kamba_ops`/`kamba_batch`, `valor_max_pedido_kz`), nenhuma das quais consta das 12 que o KAM-111 enumera. *Quem aprovou:* o fundador, nesta sessão, depois de lhe ser apresentado o bloqueio e as três alternativas. **Confirmação escrita do árbitro (§6 ponto 5 — Arquitecto de Plataforma e Responsável de Segurança) fica pendente.** | Fundador (árbitro pendente) |
| 1.2 | Outubro 2026 | KAM-130: as decisões abertas passam a `D1–D13` nas duas ocorrências. Eram treze desde o ADR-020 e o intervalo ficara em doze. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-169: a linha do **ADR-018** no §4.1 dizia «golden sintético», que é a metade abreviada da decisão, e passa a nomear as **três origens do KAM-040** com a barreira do registo de consentimento — decisão do fundador a 2026-10-30 (`../docs/adr/ADR-L006-origem-do-golden-set.md`). **O estado não muda**: continua **FIXA**, e isto não é emenda ao ADR nem ratificação — é o resumo a passar a dizer o que o `../docs/tecnica/00` §11 já dizia e a sua própria célula do §8 contradizia. Esta linha vai além dos três documentos que o pedido nomeou, e isso está declarado: a Carta é a fonte de verdade de nível 1 e repetia o mesmo defeito de abreviação um nível acima do que se estava a corrigir. | Fundador (decisão de 2026-10-30) |

*Emendas futuras: uma linha datada com o quê, porquê e quem aprovou.*

## 8. Aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Fundador |  |  |  |
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

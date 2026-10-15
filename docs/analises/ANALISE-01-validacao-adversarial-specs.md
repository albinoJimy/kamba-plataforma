# Análise Adversarial das Specs — KAMBÁ (ANALISE-01)

| Campo | Valor |
|---|---|
| Objecto | Conjunto técnico `tecnica/` (ÍNDICE v1.1) e conteúdo-fonte consolidado (`../08`, `../10`, `../11`, `../12`, `../13`) |
| Método | Revisão adversarial por subsistema: cada ADR e fluxo é atacado na sua premissa mais fraca; achados classificados P0 (bloqueia build) / P1 (bloqueia escala) / P2 (dívida registada) |
| Data | Outubro de 2026 |
| Classificação | Interno — auditoria |

---

## 1. Sumário executivo

**Veredicto: APROVADO COM REMEDIAÇÃO P0 OBRIGATÓRIA.** A arquitectura por camadas é sólida e as
decisões de stack são defensáveis. Mas a análise encontrou **6 achados P0** — nenhum é de stack;
todos vivem na fronteira entre o desenho técnico e a realidade angolana: **responsabilidade legal
da venda assistida, protecção do consumidor, fricção bancária por PME, tecto de throughput do
número da plataforma, transferência de dados para LLMs nos EUA, e a verdade do stock**. São
exactamente o tipo de falha que nenhum teste de software apanha.

Distribuição: P0 ×6 · P1 ×9 · P2 ×9. A remediação P0 é pré-condição para abrir o backlog
`specs/`; a P1 entra como requisitos nos documentos afectados; a P2 fica registada como dívida.

---

## 2. Achados P0 (bloqueiam a construção)

### ADV-01 · Tecto de throughput do número da plataforma (Canais / ADR-001, ADR-011)
**Evidência:** coexistência fixa 20 msg/seg por número. O Fluxo A distribui esse tecto por loja
(não-issue), mas o **Fluxo B concentra todo o tráfego da plataforma num único número** — assistente,
vendas assistidas e PMEs "light" partilham os mesmos 20 msg/s. Com algumas centenas de conversas
concorrentes (picos de almoço/fim-de-semana), o canal mais estratégico da plataforma fica em
fila de espera.
**Impacto:** degradação silenciosa exactamente no ativo que mais precisa de provar velocidade
("aha <30s" do funil do consumidor).
**Remediação:** especificar **sharding do canal da plataforma** desde o desenho: N números
(número por cluster/categoria, ex.: "Zuela Cazenga", "Zuela Serviços") atrás do mesmo
ChannelResolver; regra de afinidade consumidor→número; capa de monitorização de fila por número.
Doc alvo: `tecnica/01`.

### ADV-02 · Vendedor de registo e responsabilidade legal no Fluxo B2 (Produto/Conformidade)
**Evidência:** na venda assistida (B2), a plataforma fecha o pedido "em nome da PME" na sua
própria conversa. As specs não definem **quem é o vendedor de registo**: agente comercial?
comissionista? revendedor? De quem é a obrigação fiscal da factura (AGT)? Quem responde por
garantia, devolução e direito do consumidor?
**Impacto:** ambiguidade legal sobre cada transação B2; risco fiscal (AGT) e de responsabilidade
civil que cresce com o volume. É também a pergunta que qualquer parceiro bancário fará na
diligência.
**Remediação:** parecer jurídico ANTES do piloto B2; modelo contratual PME↔plataforma (mandato
de intermediação com factura emitida pela PME, plataforma como mero canal tecnológico); termos de
uso do consumidor explícitos na conversa. Doc alvo: `tecnica/04` + nova `12_Matriz_Conformidade` (P1).

### ADV-03 · Protecção do consumidor ausente no MVP (Confiança)
**Evidência:** o MVP paga **antecipadamente por referência** a PMEs verificadas apenas por um
agente comissionado. O escrow está marcado como "fase 2". Um único caso público de "paguei e não
recebi" num mercado com histórico de burlas online destrói a marca antes dela nascer — e a frase
"pague à ref 102 345 678" é dita pelo assistente da plataforma, logo a fraude é atribuída à
plataforma.
**Impacto:** risco existencial de reputação; assimétrico (um caso mata mil conversões).
**Remediação:** pacote mínimo de protecção desde o dia 1: (a) piloto B2 só com PMEs verificadas
presencialmente **e** com caução/limite de valor por encomenda; (b) **código de entrega de 4
dígitos como condição de liquidação registada** (já existe no dispatch — generalizar como prova
de cumprimento); (c) fundo/fluxo de reembolso rápido com SLA público; (d) escalonamento do escrow
leve para P1, não fase 2. Doc alvo: `tecnica/04`, `tecnica/10`.

### ADV-04 · Fricção bancária por PME não resolvida (Pagamentos / ADR-004)
**Evidência:** "liquidação directa na conta de cada PME" + ProxyPay exige **entidade própria por
comerciante** (contrato bancário, 2–6 semanas). As specs tratam o contrato como evento único da
plataforma, mas não está especificado se cada PME precisa do SEU processo junto do banco. Se sim,
o onboarding de 30 minutos (doc 10) é ficção para o modo pagamentos.
**Impacto:** o caminho crítico deixa de ser técnico e passa a ser N processos bancários — o
bottleneck da expansão por clusters.
**Remediação:** validar com ProxyPay/AppyPay o modelo de **sub-merchant onboarding** (a
facilitadora agrega; plataforma regista; PME só fornece IBAN + NIF) — se não existir, o desenho
muda: cobrança via entidade da plataforma com **payout diário** à PME (avaliar enquadramento BNA
com parecer — ver ADV-02). Decisão registada como ADR novo. Doc alvo: `tecnica/04`.

### ADV-05 · Transferência de conversas para LLMs nos EUA contradiz ADR-010 (Dados / Lei 22/11)
**Evidência:** ADR-005 (APIs de LLM) está "Ratificado", mas a própria pesquisa de infra regista:
transferência para países "não adequados" exige **autorização prévia da APD** (ou salvaguardas
contratuais específicas). ADR-010 minimiza PII do msisdn, mas o **conteúdo das conversas** —
o dado mais sensível — vai integralmente para OpenAI/Google/Groq. Há uma contradição directa
entre "Ratificado" e o requisito legal.
**Impacto:** exposição à APD (mediana de multas ~$100k) no activo central do produto.
**Remediação:** (a) obter parecer e notificar/autorizar junto da APD antes do piloto; (b) pipeline
de **redacção pré-envio** (mascarar nomes, NIFs, moradas antes de chamar o LLM, com mapa de
reidentificação local); (c) preferir endpoints UE quando disponíveis; (d) reclassificar ADR-005
como "Ratificado condicionado a ADV-05". Doc alvo: `tecnica/08`, `tecnica/02`.

### ADV-06 · A verdade do stock: reserva online vs. venda física (Comércio / ADR-003)
**Evidência:** a reserva de 72h assume que o stock no sistema existe. Mas a PME vende o mesmo
stock **na loja física e noutros canais**, sem ponto de venda integrado. Resultado: o cliente
paga a referência por uma unidade que foi vendida ao balcão 2 horas antes. A frescura de stock
era o ponto cego nº 2 da ronda 1 e as specs não a resolveram — apenas a herdaram.
**Impacto:** cancelamentos pós-pagamento (o pior tipo de falha: dinheiro já saiu), reembolsos,
desgaste de confiança; taxa de falha desconhecida e potencialmente alta no informal.
**Remediação:** (a) fluxo **"confirmar antes de cobrar"** para stock ≤ limiar: o Vendedor AI
confirma disponibilidade com a PME (mensagem rápida, SLA 15 min) ANTES de emitir a referência —
a referência só sai com `stock_confirmado_em < X min`; (b) categorias sem controlo de stock
(serviços, talho do dia) fora da reserva; (c) métrica `taxa_falha_stock` como KPI de saúde do
cluster. Doc alvo: `tecnica/03`.

---

## 3. Achados P1 (bloqueiam a escala)

| ID | Achado | Recomendação | Doc alvo |
|---|---|---|---|
| ADV-07 | **Validador de citação verifica consistência, não verdade** — regex confere o número com a tool, mas a tool pode estar desatualizada; não há SLA de frescura enforcement (só "nudges") | SLA de frescura por categoria + degradação de ranking para dados velhos + selo "confirmado há Xmin" só quando confirmado por evento real | 02, 03, 05 |
| ADV-08 | **Langfuse captura conteúdo** por defeito (prompts/completions) — contradiz "logs sem conteúdo" | Redacção no sink Langfuse (mesma pipeline de ADV-05); traces só com metadados em produção | 08, 09 |
| ADV-09 | **Retenção de voz e conversas indefinida** — MinIO cresce sem TTL; notas de voz são PII biométrica leve | Política de retenção por classe de dado (voz 90d, conversas 24m, ledger permanente) + crypto-shredding por titular | 08, 06 |
| ADV-10 | **Bootstrapping do dataset golden** — são precisas conversas reais para os evals, e evals para lançar; especificação não resolve o ovo-e-galinha | **Shadow mode** obrigatório nas primeiras N conversas/vertical: IA rascunha, humano envia; o delta humano-IA É o dataset golden | 02, 10 |
| ADV-11 | **Dunning da cobrança às PMEs não especificado** — o que acontece à loja de uma PME em atraso? | Máquina de estados de entitlements: ativo → aviso (T+3) → degradação (sem módulos pro, loja continua) → suspensão (T+15, catálogo sai do índice) → reativação automática | 04, 03 |
| ADV-12 | **Chatwoot com 1.000 contas** é território desconhecido (Rails, 1 conta/PME) | Load test com 500 contas sintéticas na fase piloto; estratégia de shard por cluster definida desde já | 09, 01 |
| ADV-13 | **Dinheiro físico excluído** — o informal paga em cash; COD está marcado como "vector de fraude" sem desenho alternativo | Decidir explicitamente: piloto sem COD (aceitável em categorias de ticket alto) + desenho COD-caução para fase 2 (estafeta com limite de cash, reconciliação diária) | 04, 07 |
| ADV-14 | **Explosão de variantes de persona** (vertical × tenant) sem cobertura de eval por variante | Personas tenant-level herdam de template versionado; delta é config, não prompt livre; eval por vertical (não por tenant) com amostragem de tenants | 02 |
| ADV-15 | **Verificação Meta Business exige documentos** que muitas PMEs não têm (site, provas) — taxa de rejeição desconhecida | Medir no piloto; fallback Light como modo permanente legítimo (não "rampa"); ajustar promessa comercial | 01, 10 |

## 4. Achados P2 (dívida registada)

| ID | Achado |
|---|---|
| ADV-16 | Custos de media (Photoroom/remove.bg por imagem) fora do unit economics — Catálogo AI em volume é linha de custo real |
| ADV-17 | Preço dual USD/Kz (comum em eletrónica/imobiliária) não modelado — índice assume Kz único |
| ADV-18 | Análise de custo-de-fraude de reviews ausente (concorrente compra barato para avaliar mal) |
| ADV-19 | Kambá Score: base legal de scoring é consentimento distinto do de comércio; retenção "guardar tudo" colide com minimização (Lei 22/11) |
| ADV-20 | Diáspora: AML/KYC transfronteiriço e parceiro de remessas totalmente por especificar |
| ADV-21 | Processo de reembolso (prazos, aprovador, comunicação) está uma frase no F5 — precisa de fluxo próprio |
| ADV-22 | Conteúdo do assistente em cold-start (câmbio, horários, utilidades) sem fontes de dados especificadas |
| ADV-23 | Aprovação de templates Meta em PT-AO: tempos e rejeições por medir; biblioteca inicial por criar |
| ADV-24 | Idempotência dos consumidores do event bus declarada mas sem estratégia de teste (chaos: replay de eventos duplicados em staging) |

---

## 5. Padrões transversais dos achados

1. **Os P0 não são de software.** Concentram-se em responsabilidade legal (ADV-02), confiança
   (ADV-03, ADV-06), banco (ADV-04), regulador (ADV-05) e Meta (ADV-01). A arquitectura técnica
   está à frente da arquitectura **institucional** — os pareceres jurídicos e os modelos
   contratuais são caminho crítico, não anexos.
2. **"Ratificado" foi usado cedo demais** em três ADRs (001, 004, 005) que dependem de factos
   externos não verificados. O sistema de estados (§5.1 do ÍNDICE) existe exactamente para isto:
   aplicar.
3. **A frescura/verdade dos dados é o débito recorrente** (ADV-06, ADV-07): o desenho assume
   stock e preço como verdades que o mercado informal não produz. O padrão correcto é
   **confirmar-no-momento** (confirmação ativa antes de cobrar) em vez de **confiar-no-registo**.
4. **O MVP precisa de um pacote de protecção do consumidor** tão central quanto o pacote de
   features (ADV-03, ADV-13, ADV-21). Numa economia com histórico de burlas, a protecção É o
   produto.

---

## 6. Matriz de remediação

| Achado | Acção | Tipo | Bloqueia |
|---|---|---|---|
| ADV-01 | Sharding do canal da plataforma no desenho de canais | spec | build Fluxo B |
| ADV-02 | Parecer jurídico + modelo contratual PME↔plataforma | jurídico | piloto B2 |
| ADV-03 | Pacote de protecção do consumidor (verificação+caução, código de entrega, SLA reembolso) | spec+ops | piloto |
| ADV-04 | Validar sub-merchant onboarding com ProxyPay/AppyPay; ADR novo se inexistente | parceria+ADR | onboarding pagamentos |
| ADV-05 | Notificação/autorização APD + redacção pré-LLM + endpoints UE | jurídico+spec | piloto |
| ADV-06 | Fluxo "confirmar antes de cobrar" para stock crítico | spec | piloto |
| ADV-07–15 | Entrar como requisitos nos documentos alvo (§3) | spec | fase 1 |
| ADV-16–24 | Registar como dívida com dono e revisão trimestral | dívida | — |

**Gate:** nenhum ticket de `specs/` abre antes dos 6 P0 terem remediação escrita na spec
correspondente (spec) ou parecer iniciado (jurídico/parceria).

---

## 7. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira validação adversarial do conjunto técnico: 24 achados (6 P0, 9 P1, 9 P2). | Auditoria interna |

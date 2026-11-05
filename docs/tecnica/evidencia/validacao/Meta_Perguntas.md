# Perguntas escritas à Meta: dossiê, folha de seguimento e regra de decisão de H4

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — dossiê das 15 perguntas à Meta, modelo de registo de respostas e regra de H4 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-101 (EPIC-10) |
| Documento-fonte | [`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md) («Perguntas que só a Meta/BSP pode responder por escrito», §2, §3, §4, riscos 1 e 2); [`../../../exploracao/14-tese-minima-e-plano-de-validacao.md`](../../../exploracao/14-tese-minima-e-plano-de-validacao.md) §2 (H4), §6; [`../../00_Arquitectura_Solucao.md`](../../00_Arquitectura_Solucao.md) §13.3 (D2, D5, D10); ADR-001, ADR-011, ADR-018 |
| Relacionados | [`Seguimento_APD.md`](Seguimento_APD.md), [`GoLive_Gate.md`](GoLive_Gate.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) |

> **Este documento prepara o envio; não o faz.** As 15 perguntas estão
> redigidas em inglês e em português, classificadas por lote e com a decisão e o
> ticket que cada uma desbloqueia. **Nenhuma foi enviada**, e a folha de
> seguimento e o registo de respostas **nascem vazios**: enviar em nome da
> empresa, escolher o canal e aprovar o texto são actos humanos, e o executor
> deste ticket não os pratica nem os simula. Não há nenhuma resposta da Meta
> neste ficheiro — se aparecer uma, foi inventada, e isso é um defeito, não uma
> entrega.
>
> O que muda face a [`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md) é só o
> **§3**: os quatro trechos de maior impacto foram relidos na fonte primária em
> inglês, e três divergências ficam medidas. Nenhuma delas corrige o E1 neste
> ticket — corrigir o E1 é trabalho de outro ticket (§7).

---

## 1. As 15 perguntas

A numeração **Q1 a Q15** é a de
[`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md), secção «Perguntas que só a
Meta/BSP pode responder por escrito», e não se renumera: é por ela que o
KAM-102, o KAM-095 e o bloco do KAM-101 citam perguntas individuais (o
critério 8 do KAM-102 cita «Q9 de KAM-101»).

**O texto PT é o de E1, sem alteração de sentido.** O texto EN é redigido aqui,
porque o canal da Meta é em inglês e E1 só tem a versão portuguesa; onde o
português de E1 encavalga duas perguntas numa só frase, a versão inglesa mantém
as duas e não escolhe entre elas.

**Os três lotes**, pelo §«Detalhes Técnicos» do bloco KAM-101:

| Lote | Prioridade | Perguntas | Prazo do critério 2 |
|---|---|---|---|
| 1 | **Piloto** — condicionam o arranque | Q2, Q3, Q4, Q7, Q8, Q9, Q11, Q12 (**8**) | até ao **dia 5** |
| 2 | **Fluxo B e Clusters** | Q1, Q5, Q6, Q10, Q13, Q14 (**6**) | até ao **dia 10** |
| 2 | **Custo** — consumida pelo KAM-102 | Q15 (**1**) | até ao **dia 10** |

O lote 2 tem **sete** perguntas: as seis de Fluxo B e Clusters mais a Q15, que
é de custo e vai a BSPs em vez de à Meta.

**Os estados do campo «Estado»** são os três do critério 1 — `enviada`,
`respondida`, `sem resposta`. A folha nasce em **`por enviar`**, que é o estado
anterior ao primeiro e **não é um quarto resultado**: é a marca de que o acto
humano ainda não aconteceu. A mesma forma da folha do
[`Seguimento_APD.md`](Seguimento_APD.md) §1, que nasce em `por submeter`.

**O campo «Canal» nasce NÃO VERIFICADO**, e de propósito. O bloco KAM-101
di-lo: «canal antes da aprovação de Tech Provider: NÃO VERIFICADO (apoio de
programador ou de Business Support); o canal usado fica registado». Preencher
a coluna agora era escolher por conta própria um canal que não sabemos existir
para uma conta sem estatuto de parceiro. A excepção é a Q15, que não vai à Meta.

---

### Q1 — Número único agregador

| Campo | Valor |
|---|---|
| **EN** | We operate a platform that answers consumer questions about the products and prices of several independent shops, each of which has contractually authorised us to do so, from a **single** WhatsApp Business number. (a) Is this permitted? (b) Under which name must the number present itself — the platform's name or each shop's name? (c) Does the impersonation clause of the WhatsApp Business Messaging Policy apply to this arrangement, and if so, what does it require of us? |
| **PT** | Um único número WhatsApp Business operado por uma plataforma que responde a perguntas de consumidores sobre produtos/preços de várias lojas independentes (com autorização contratual de cada loja) é permitido? Em que nome deve aparecer (nome da plataforma ou das lojas)? Aplica-se a cláusula de personificação? |
| Secção de E1 que a origina | §4, linha «Número único agregador a responder a perguntas de consumo sobre várias lojas» (**NÃO VERIFICADO**); risco 2 |
| Decisão afectada | **D2** (Fluxo B / número agregador); **D10**; ADR-011 |
| Ticket afectado | KAM-016; Clusters |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q2 — Classificação como *AI Provider*

| Campo | Valor |
|---|---|
| **EN** | Is a commerce assistant built on a large language model — serving catalogue browsing, order placement and FAQ for multiple independent shops — considered an "AI Provider" under Section 4.7 of the Meta Terms for WhatsApp Business Platform (as updated 15 January 2026)? (a) Are there objective criteria for distinguishing AI as the "primary" functionality from AI as "incidental or ancillary" functionality? (b) Is there any pre-approval process, or any way to obtain a written determination before we build? |
| **PT** | Um assistente de comércio com LLM (catálogo, pedidos, FAQ de várias lojas) é considerado "AI Provider" nos termos de 15 Jan 2026? Há critérios objectivos para "funcionalidade principal vs acidental/complementar"? Há processo de pré-aprovação? |
| Secção de E1 que a origina | §4, linha da definição de *AI Provider* (**CONFIRMADO** quanto ao texto, com ressalva de leitura automática); **risco 1 (existencial)** |
| Decisão afectada | **D2**; ADR-011; ADR-005 |
| Ticket afectado | KAM-016, KAM-033; KAM-049 (`ext:KAM-101`) |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q3 — Coexistência em números +244

| Campo | Valor |
|---|---|
| **EN** | Is Coexistence (Embedded Signup with the WhatsApp Business app) available for Angolan numbers with the +244 country code, both mobile and landline, without restriction? Is there an official list of eligible or excluded countries, and if so where is it published? |
| **PT** | A coexistência (Embedded Signup com WhatsApp Business app) está disponível para números +244 (móveis e fixos), sem restrições? Existe uma lista oficial de países excluídos? |
| Secção de E1 que a origina | §2, linha «Países» (elegibilidade de Angola = **NÃO VERIFICADO**); risco 6 |
| Decisão afectada | **D5**; ADR-001 |
| Ticket afectado | KAM-016, KAM-100 (H3) |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q4 — Registo de números fixos e fiabilidade do SMS

| Campo | Valor |
|---|---|
| **EN** | (a) Can Angolan landline numbers be registered for the WhatsApp Business Platform by voice call, without SMS? (b) Does international SMS from Angolan mobile operators reach your verification system reliably, and is there a known delivery issue for the +244 country code? |
| **PT** | Os números fixos angolanos podem ser registados por voz (sem SMS)? O SMS internacional de operadoras angolanas (Unitel, Africell) chega fiável para verificação? |
| Secção de E1 que a origina | §2 e §5 (registo e verificação de números) |
| Decisão afectada | ADR-001 |
| Ticket afectado | KAM-016, KAM-100 (H3) |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q5 — Pagamentos nativos

| Campo | Valor |
|---|---|
| **EN** | Is there a roadmap or timeline for WhatsApp Payments (the `order_details` message type) in Angola, or anywhere in Africa? Are any payment service providers supported outside India and Brazil, and can a local Angolan provider be onboarded? |
| **PT** | Há calendário/roadmap para Payments (`order_details`) em Angola ou em África? Há parceiros de pagamento (PSP) suportados fora de Índia/Brasil? |
| Secção de E1 que a origina | §7 (pagamentos); risco 5 |
| Decisão afectada | **D2**; D4; ADR-017 |
| Ticket afectado | Clusters |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q6 — Meta Business Agent

| Campo | Valor |
|---|---|
| **EN** | (a) Is Meta Business Agent available in Angola, and does it support European/Angolan Portuguese? (b) If a business customer enables it on a number that also runs our Cloud API solution, what is the resulting behaviour — do we become a standby partner, and how is thread control resolved between us and Meta's agent? |
| **PT** | Meta Business Agent está disponível em Angola e em português europeu/angolano? Qual é o tratamento se o cliente o activar num número que também usa o nosso produto (standby partner, thread control)? |
| Secção de E1 que a origina | §4, linha «Meta Business Agent» (disponibilidade em Angola = **NÃO VERIFICADO**) |
| Decisão afectada | **D2**; ADR-001 |
| Ticket afectado | KAM-016; Clusters |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q7 — Cláusula de dados e treino de modelos (§4.7)

| Campo | Valor |
|---|---|
| **EN** | Regarding Section 4.7 of the Meta Terms for WhatsApp Business Platform: (a) please confirm the operative wording of the restriction on using WhatsApp Business Platform Data to create, develop, train or improve machine-learning or AI systems, and confirm whether that restriction applies to every customer of the platform or only where an AI Provider is retained as a Solution Provider. (b) May we send conversation content to a third-party large language model for **inference only**, under a contract that forbids retention and training? (c) Does the exception permitting fine-tuning a model for our own exclusive use extend to building an **evaluation** dataset from real conversations, with the end user's consent? (d) What retention and no-training obligations do you require of such a third-party provider? |
| **PT** | Qual é o texto exacto da cláusula sobre dados da plataforma e treino de modelos (§4.7)? Pode-se usar um LLM de terceiros (inferência) com dados de conversas? Que exigências de retenção/no-training? |
| Secção de E1 que a origina | §4, linha dos Termos §4.7 (**CONFIRMADO** com ressalva de leitura automática, «verificar a cláusula exacta»); ver o desvio medido no **§3.1** |
| Decisão afectada | ADR-018; ADR-005; D12 |
| Ticket afectado | KAM-033; KAM-040 (*golden set*); KAM-049 (`ext:KAM-101`) |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

> A alínea (c) é **nova face a E1** e nasce da releitura do §3.1: a cláusula em
> inglês tem uma excepção para afinar um modelo de uso exclusivo próprio, que a
> leitura portuguesa de E1 não registou, e é exactamente essa excepção que
> decide se o *golden set* de
> [`../../10_Onboarding_Governanca.md`](../../10_Onboarding_Governanca.md) §11.3
> é permitido. Acrescentar uma alínea a uma pergunta **não altera o sentido** das
> três que E1 já fazia, que ficam intactas e primeiro.

### Q8 — Business Verification de empresa angolana

| Campo | Valor |
|---|---|
| **EN** | (a) What is the expected turnaround time for Business Verification, and which documents do you accept for a company incorporated in Angola (commercial licence/*alvará*, taxpayer number/NIF, commercial registry certificate)? (b) What do you require for the Business Verification of our own business customers, many of which are micro-enterprises operating informally — is there a lighter path, or a partner-led verification? |
| **PT** | Prazo e documentação aceite para Business Verification de uma empresa angolana (alvará, NIF, certidão comercial)? E para a Business Verification das PMEs clientes (muitas informais)? |
| Secção de E1 que a origina | §3 (Business Verification; prazo **não documentado**, aceitação de documentos angolanos **NÃO VERIFICADA**); risco 10 |
| Decisão afectada | **D5**; D9 |
| Ticket afectado | KAM-102, KAM-016, KAM-095 |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q9 — *Access Verification*

| Campo | Valor |
|---|---|
| **EN** | What is "Access Verification", the step that raises the onboarding limit from 10 to 200 new business customers per rolling 7-day window? Please state its requirements, the process to request it, and the expected turnaround time. |
| **PT** | O que é "Access Verification" (aumento de 10 para 200 onboardings/7 dias)? Requisitos e prazo? |
| Secção de E1 que a origina | §3, linha dos limites de onboarding (detalhe da *Access Verification* = **NÃO VERIFICADO**); risco 10 |
| Decisão afectada | **D5** |
| Ticket afectado | KAM-102 (critério 8), KAM-095 |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q10 — Janela Free Entry Point

| Campo | Valor |
|---|---|
| **EN** | Is the Free Entry Point window 72 hours or up to 7 days? The current documentation states up to 7 days, while earlier material stated 72 hours — please confirm which applies today, and from which date the current value took effect. |
| **PT** | A janela Free Entry Point é de 72 horas ou até 7 dias? (a documentação actual diz até 7 dias; materiais anteriores diziam 72h). |
| Secção de E1 que a origina | §1 e §5 (preços e janelas) |
| Decisão afectada | — (afecta o modelo de custo, não uma decisão aberta) |
| Ticket afectado | Clusters; KAM-058 (`ext:KAM-101`) |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q11 — Método de pagamento local

| Campo | Valor |
|---|---|
| **EN** | (a) Is there any local payment method for Angolan business customers in the Billing Hub — Kwanza-denominated payment, bank transfer, or the national Multicaixa network — or is an international card mandatory? (b) Is there any Solution Partner with a presence in Angola, or able to invoice in Angolan Kwanza? |
| **PT** | Há método de pagamento local para clientes angolanos (Kwanzas, transferência, Multicaixa) no Billing Hub, ou é obrigatório cartão internacional? Há algum Solution Partner com presença/facturação em Angola? |
| Secção de E1 que a origina | §3 e §8 (Tech Provider sem *credit line*); risco 4 |
| Decisão afectada | **D5**; D9 |
| Ticket afectado | KAM-102, KAM-095, KAM-106 |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q12 — *Timeout* e *retry* do webhook

| Campo | Valor |
|---|---|
| **EN** | Please state the exact webhook delivery parameters: the request timeout in seconds, the retry policy (number of attempts and the interval between them), and the value of the pair rate limit. |
| **PT** | Timeout e política de retry exactos do webhook (segundos, número de tentativas) e valor do pair rate limit. |
| Secção de E1 que a origina | §5 (webhooks, limites) |
| Decisão afectada | ADR-001 |
| Ticket afectado | KAM-013, KAM-016 |
| Prioridade / lote | **Piloto** — **lote 1** (dia 5) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q13 — Meta Commerce Policy

| Campo | Valor |
|---|---|
| **EN** | (a) Please point us to the complete list of prohibited and restricted categories under the Meta Commerce Policy as it applies in Angola, and describe the appeal process when a catalogue or a number is actioned. (b) Is the catalogue feature available in Angola? |
| **PT** | A Meta Commerce Policy: lista completa de categorias proibidas relevantes em Angola e processo de recurso; catálogo está disponível em Angola? |
| Secção de E1 que a origina | §4 (a página da Commerce Policy **não foi lida**); risco 9 |
| Decisão afectada | ADR-001 |
| Ticket afectado | KAM-088, KAM-049 |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q14 — Limites por utilizador de marketing

| Campo | Valor |
|---|---|
| **EN** | Are per-user marketing template limits currently active for recipients in Angola? If so, what is the value, and how is it surfaced to us? |
| **PT** | Limites por utilizador de templates de marketing aplicam-se a Angola? Valor? |
| Secção de E1 que a origina | §5 (limites e qualidade); risco 12 |
| Decisão afectada | — (afecta o modelo de custo e a régua de cobrança) |
| Ticket afectado | KAM-058 (`ext:KAM-101`); Clusters |
| Prioridade / lote | Fluxo B e Clusters — **lote 2** (dia 10) |
| Canal | **NÃO VERIFICADO** — a registar no envio |
| Data de envio | — |
| Estado | **`por enviar`** |

### Q15 — Cotação a BSPs

| Campo | Valor |
|---|---|
| **EN** | For a platform onboarding Angolan small businesses onto the WhatsApp Business Platform, please quote: per-message markup, monthly platform fee, whether you support Coexistence and business-scoped user IDs (BSUID), and the final delivered rate for recipients with the +244 country code, by message category. |
| **PT** | Para BSPs (360dialog, Twilio, outros): markup por mensagem, taxa mensal, suporte a coexistência e a BSUID, e tarifa final para destinatários +244. |
| Secção de E1 que a origina | §8 (BSPs; preços citados são **INDÍCIO**); risco 4 |
| Decisão afectada | **D5** |
| Ticket afectado | **KAM-102** (critério 4: «≥ 2 cotações formais de BSP») |
| Prioridade / lote | Custo — **lote 2** (dia 10) |
| Canal | **BSP**, não a Meta — contacto comercial do próprio BSP; o canal usado fica registado |
| Data de envio | — |
| Estado | **`por enviar`** |

> **A Q15 é a única que não vai à Meta**, e a resposta é consumida pelo
> **KAM-102**, não por este ticket. Fica aqui porque é a Q15 de E1 e a
> numeração não se parte; o dossiê de Tech Provider e as cotações são do
> KAM-102.

---

### 1.1 Folha de seguimento

Uma linha por pergunta. **Nasce vazia.** Estados: **`por enviar`** →
`enviada` → `respondida` ou `sem resposta`.

| Q | Lote | Prazo | Canal | Data de envio | Estado | Data de resposta | Classificação (§2) |
|---|---|---|---|---|---|---|---|
| Q1 | 2 | dia 10 | | | **`por enviar`** | | |
| Q2 | 1 | dia 5 | | | **`por enviar`** | | |
| Q3 | 1 | dia 5 | | | **`por enviar`** | | |
| Q4 | 1 | dia 5 | | | **`por enviar`** | | |
| Q5 | 2 | dia 10 | | | **`por enviar`** | | |
| Q6 | 2 | dia 10 | | | **`por enviar`** | | |
| Q7 | 1 | dia 5 | | | **`por enviar`** | | |
| Q8 | 1 | dia 5 | | | **`por enviar`** | | |
| Q9 | 1 | dia 5 | | | **`por enviar`** | | |
| Q10 | 2 | dia 10 | | | **`por enviar`** | | |
| Q11 | 1 | dia 5 | | | **`por enviar`** | | |
| Q12 | 1 | dia 5 | | | **`por enviar`** | | |
| Q13 | 2 | dia 10 | | | **`por enviar`** | | |
| Q14 | 2 | dia 10 | | | **`por enviar`** | | |
| Q15 | 2 (BSP) | dia 10 | | | **`por enviar`** | | |

**15 linhas, 15 em `por enviar`, 0 enviadas, 0 respondidas.** É esta contagem
que diz se alguém inventou uma resposta: enquanto as três últimas colunas
estiverem vazias, não há nada classificado, e nenhuma afirmação deste
repositório pode invocar «a Meta respondeu».

---

## 2. Modelo de registo de respostas

### 2.1 A regra de classificação

A regra é a do critério 3 do bloco KAM-101, e é **sobre a origem, não sobre o
conteúdo**:

| Classificação | Quando | O que pode fazer |
|---|---|---|
| **CONFIRMADO** | A resposta vem **da Meta, por escrito**: *Direct Support*, Business Support, ou outro canal oficial da Meta, com registo identificável do caso | Pode fechar um item NÃO VERIFICADO de E1 e alimentar a regra de H4 (§4) |
| **INDÍCIO** | A resposta vem de **BSP, parceiro, fórum, imprensa**, ou é **verbal** (chamada, reunião, voz) sem confirmação escrita | **Não** fecha nada. Entra no registo e continua a pedir-se a resposta escrita |

> **Verbal é INDÍCIO, mesmo vindo da Meta.** Uma chamada com um representante da
> Meta não é «da Meta por escrito». Isto não é formalismo: o risco 1 de E1 é
> existencial e a cláusula que o sustenta diz que a Meta decide «a seu exclusivo
> critério» — uma frase dita ao telefone não obriga ninguém. Quem receber uma
> resposta verbal pede a confirmação por escrito e regista a verbal como
> INDÍCIO até ela chegar.
>
> **E um INDÍCIO não sobe de estado por ser conveniente.** Promover um INDÍCIO a
> CONFIRMADO é o defeito mais comum neste conjunto; o registo abaixo tem campo
> para a origem precisamente para que a promoção não possa ser feita em silêncio.

### 2.2 A ficha de cada resposta

Uma ficha por resposta, acrescentada a este ficheiro por baixo desta secção. A
ficha **nasce apenas quando a resposta chega**; não há fichas em branco.

```text
### Resposta a Q<n> — <assunto em quatro palavras>

| Campo                 | Valor |
|-----------------------|-------|
| Pergunta              | Q<n>  |
| Data da resposta      | AAAA-MM-DD |
| Canal                 | Direct Support / Business Support / apoio de programador / BSP / fórum / verbal |
| Remetente             | <papel ou equipa; NUNCA o nome de uma pessoa> |
| Referência do caso    | <id do caso de suporte, se houver> |
| Classificação         | CONFIRMADO | INDÍCIO |
| Razão da classificação| <a origem, contra a tabela do §2.1> |
| Texto integral        | <a resposta, na língua em que chegou, sem edição> |
| Resposta à pergunta   | SIM, integral | SIM, parcial | NÃO respondeu |
| Item de E1 que fecha  | <secção e linha de E1, ou «nenhum»> |
| Estado final do item  | CONFIRMADO | INDÍCIO | NÃO VERIFICADO (mantido) |
| Impacto nos tickets   | <ver §6> |
| Efeito em H4          | <ver §4; «nenhum» é uma resposta válida> |
```

**Três regras de escrita da ficha:**

1. **«Texto integral» é integral.** A resposta vai sem resumo e sem tradução,
   porque é dela que se discute depois. O resumo, se fizer falta, vai numa
   linha à parte e identificada como resumo.
2. **Sem nomes de pessoas e sem números de telefone**, aqui e em qualquer
   ficheiro deste repositório, que é público. O remetente regista-se pelo
   papel ou pela equipa, e a referência do caso basta para o reencontrar.
3. **«NÃO respondeu» é um resultado**, e é o mais provável em várias destas
   perguntas. Uma resposta que desvia a pergunta regista-se como `NÃO
   respondeu` com o texto integral ao lado — não como resposta parcial.

---

## 3. Releitura das fontes primárias em inglês

Os quatro trechos de maior impacto do critério 4, relidos **em inglês** a
**2026-11-05**, contra o que E1 afirma a partir da pesquisa de **2026-10-08**.

**O método, e o seu limite.** A leitura foi feita por **extracção automática**
do HTML de cada página (a mesma classe de método que E1 declara nas suas
«Limitações», ponto (b)). Serve para confirmar número e título de cláusula,
presença ou ausência de uma lista, e o enquadramento de uma restrição; **não
substitui a leitura humana do texto integral antes de uso contratual**, que é o
que a Q7 pede à Meta. Onde abaixo se diz CONFIRMADO, é com esta ressalva.

**O campo «Updated» das páginas de documentação não existe.** Nas três páginas
de `developers.facebook.com` relidas, a procura do rótulo devolveu
`NO UPDATED LABEL`. E1 atribui a essas páginas datas de «Updated» (Jun 26,
2026; Jul 24, 2026; Sep 25, 2026). **Este é o desvio 0**, e é transversal: ou a
Meta retirou o rótulo entre Outubro e Novembro de 2026, ou a extracção não o
alcança. Em qualquer dos casos, a coluna «Data» abaixo dá a **data da leitura**
e não a data da página, e as datas de E1 **não ficam confirmadas nem
desmentidas**.

### 3.1 Cláusula §4.7 — dados da plataforma e treino de ML

| Campo | Valor |
|---|---|
| URL | `https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform?locale=en_US` |
| Língua servida | **Inglês** (confirmado: o selector de língua indica «English (US)») |
| Data da página | **September 23, 2026** («Last Modified») — **bate com E1** |
| Data da leitura | 2026-11-05 |
| Estado | **CONFIRMADO** quanto ao número, título e enquadramento da cláusula, com a ressalva de método acima |

**O que a fonte diz** (resumo; o texto integral dos Termos **não** se reproduz
aqui — é material de terceiros e este repositório é público): a secção **4.7**
intitula-se «AI Providers». A restrição sobre usar dados da plataforma para
criar, desenvolver, treinar ou melhorar sistemas de *machine learning* ou de IA
— incluindo modelos de linguagem de grande escala, e abrangendo formas
anónimas, agregadas ou derivadas desses dados — está **dentro da 4.7** e é
enunciada **para o caso de se contratar um *AI Provider* como *Solution
Provider***. A mesma cláusula abre uma **excepção**: é permitido afinar
(*fine-tune*) um modelo **de uso exclusivo próprio**, desde que esses dados não
sejam depois usados para criar, desenvolver, treinar ou melhorar qualquer outro
modelo.

**Desvio 1 face a E1 — o enquadramento da restrição.** E1 §4 regista a
cláusula como uma proibição **geral**: «os Termos proíbem que dados da
plataforma WhatsApp Business sejam usados para criar, desenvolver, treinar ou
melhorar sistemas de ML/IA (Termos §4.7)». A leitura em inglês mostra-a **ligada
a um cenário** e **com uma excepção** que E1 não regista. A diferença é de
âmbito, e tem consequência directa em
[`../../10_Onboarding_Governanca.md`](../../10_Onboarding_Governanca.md) §11.3,
que lê «usar conversas reais para *avaliar* pode ser lido como melhorar» — a
excepção de uso exclusivo próprio é exactamente o que decide essa leitura.

> **O desvio não relaxa nada neste ticket.** A posição de desenho que E1 deriva
> — não treinar nem afinar modelos com conversas, usar LLM só em inferência — é
> **mais conservadora** do que a fonte exige, e ser mais conservador do que a
> fonte não é um defeito. Por isso **nada se altera** por causa deste desvio:
> ele fica registado, entra na **Q7 alínea (c)**, e a decisão de aproveitar a
> excepção depende de resposta escrita da Meta e de parecer jurídico *(a
> confirmar por parecer)*. Corrigir E1 §4 e `10` §11.3 é trabalho de outro
> ticket (§7).

### 3.2 Definição de *AI Provider*

| Campo | Valor |
|---|---|
| URL | `https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform?locale=en_US` (secção 4.7) e `https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers` |
| Data da página | Termos: **September 23, 2026**. Página de preços: **sem rótulo «Updated»**; traz um aviso datado de **October 15, 2026** (actualização relativa à Turquia) e ficheiros de tarifas marcados com a mesma data |
| Data da leitura | 2026-11-05 |
| Estado | **CONFIRMADO** quanto à definição e ao critério, com a ressalva de método |

**O que a fonte diz** (resumo): a secção 4.7 define o termo por referência a
fornecedores e programadores de tecnologias de IA ou de aprendizagem automática
— modelos de linguagem de grande escala, plataformas de IA generativa e
semelhantes — e diz expressamente que **é a Meta que determina, a seu exclusivo
critério**, se um fornecedor cai na definição. Distingue o caso em que essas
tecnologias são a funcionalidade **principal** oferecida do caso em que são
**«incidental or ancillary»**, e é também a Meta que decide isso a seu exclusivo
critério. A página de preços descreve o enquadramento tarifário dos *AI
Providers*, **não** define o termo, e **não** contém as expressões «sole
discretion» nem «primary functionality»; **não descreve processo de
pré-aprovação nem de recurso**.

**Desvio 2 face a E1 — duas datas tratadas como uma.** E1 §4 diz que a
classificação está «em vigor desde **15 Jan 2026** (data confirmada pela página
de preços e pela imprensa)». A releitura separa as duas: **15 de Janeiro de
2026** é a data da actualização dos **Termos**, e a **política de preços** dos
*AI Providers* «took effect **February 16, 2026**». A data que E1 usa está
correcta para os Termos — que são o que importa ao risco 1 — e a página de
preços **não a confirma**, porque fala de outra coisa. A Q2 cita os Termos e a
data de 15 de Janeiro de 2026, que é a boa.

**Desvio 3 — tradução: «complementar» contra «ancillary».** E1 traduz o par como
«acidental ou complementar». O inglês é **«incidental or ancillary»**. Não é
gralha: «complementar» sugere uma função que acompanha por escolha, e
«ancillary» uma função subordinada e auxiliar. Num critério que a Meta aplica a
seu exclusivo critério, a palavra que conta é a inglesa, e é essa que a Q2 usa.

**O que a releitura *não* resolveu, e por isso a Q2 continua necessária:** não
há critérios objectivos publicados para separar «primary» de «incidental or
ancillary», e não há processo de pré-aprovação documentado. O risco 1 de E1
mantém-se **NÃO VERIFICADO** e **existencial**.

### 3.3 Lista de países da coexistência

| Campo | Valor |
|---|---|
| URL | `https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users` e `https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog` |
| Data da página | **Sem rótulo «Updated»** em nenhuma das duas (ver o desvio 0). No *changelog*, a entrada mais recente visível é de **May 12, 2026** e a mais antiga de **October 21, 2021** |
| Data da leitura | 2026-11-05 |
| Estado | A **ausência de lista** é **CONFIRMADA**. O **historial de países** passa a **INDÍCIO**: as duas leituras não concordam |

**O que a fonte diz, e confirma E1:** a página de coexistência **não contém
nenhuma lista de países elegíveis ou excluídos**, e **Angola não aparece em
nenhuma das duas páginas**. Confirmam-se também os requisitos que E1 regista:
versão da *WhatsApp Business app* **2.24.17 ou superior**, estatuto de
**Solution Partner ou Tech Provider**, e o prazo duro de **24 horas** para
sincronizar o histórico depois do *onboarding*, sob pena de ser preciso
*offboard* e refazer o fluxo.

**Desvio 4 face a E1 — o historial de países não se reproduz.** E1 §2 sustenta o
«provavelmente elegível» de Angola num historial lido do *changelog*: «25 Nov
2025 passaram a ser suportados Austrália, Japão, Filipinas, Rússia, Coreia do
Sul, Turquia, EEE/UE, Reino Unido; 15 Abr 2026 Nigéria e África do Sul». A
releitura devolve outra coisa:

| O que E1 afirma | O que a releitura de 2026-11-05 devolveu |
|---|---|
| Entrada de **25 Nov 2025** adiciona oito países/regiões | A entrada que adiciona esses oito países/regiões é de **23 Out 2025**. A de **25 Nov 2025** existe mas é sobre os *webhooks* «Edit messages» e «Revoke messages» da coexistência, e **não lista países** |
| Entrada de **15 Abr 2026** adiciona Nigéria e África do Sul | **Não existe** essa entrada. Nigéria e África do Sul **não aparecem em nenhuma entrada de coexistência**; a única menção aos dois é numa entrada de preços de 1 Abr 2025, sobre tarifas de autenticação internacional |
| «Phone Number First» no *changelog* de **25 Set 2026** | A entrada de «Phone Number First» (pré-visualização pública do ES v4) é de **12 Mai 2026** |
| *changelog* «Updated Sep 25, 2026» | **Sem rótulo «Updated»**; nenhuma entrada posterior a **12 Mai 2026** |

> **Não corrijo E1 com esta leitura, e digo porquê.** O *changelog* que reli
> rendeu entradas de 2021 a Maio de 2026 — parece completo, e ainda assim não
> tem nada do que E1 leu em Outubro de 2026 acima de Maio. Ou E1 datou mal
> quatro entradas, ou a extracção automática alcançou uma variante mais antiga
> da página. **Não sei qual**, e escolher em silêncio era o defeito. Fica
> registado como divergência, e o historial de países baixa a **INDÍCIO** nas
> duas direcções: nem o de E1 nem o meu serve para afirmar a elegibilidade de
> Angola.
>
> **A conclusão de desenho não muda**, e é esse o ponto que importa: as duas
> leituras concordam no que decide — **não há lista oficial** e **Angola não
> aparece**. Logo a posição de E1 mantém-se de pé: exigir confirmação escrita
> (**Q3**) e **testar com um número +244 real** (KAM-100, H3) antes de prometer
> coexistência no produto.

### 3.4 *Access Verification*

| Campo | Valor |
|---|---|
| URL | `https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview` |
| Data da página | **Sem rótulo «Updated»** (ver o desvio 0) |
| Data da leitura | 2026-11-05 |
| Estado | **NÃO VERIFICADO, mantido** — a página nomeia o passo e **não o detalha** |

**O que a fonte diz, e confirma E1:** por defeito pode fazer-se *onboarding* de
até **10** novos clientes por janela móvel de **7 dias**, contando só os
clientes recém-integrados; concluir **Business Verification**, **App Review** e
**Access Verification** sobe o limite para **200** por janela de 7 dias; acima
disso é preciso candidatar-se a **Meta Business Partner**. A *Access
Verification* é **nomeada como requisito** e a página **não descreve requisitos,
processo nem prazo** — o que mantém exactamente o estado que E1 lhe dá.

**O que a releitura acrescenta a E1:** a página diz também que **não se pode
fazer *onboarding* de cliente nenhum** enquanto a aplicação não tiver *advanced
access* para cada permissão de que precisa. É uma condição **anterior** ao
limite de 10, que E1 não regista nesta linha; não contradiz E1, aperta-a. Entra
no **KAM-102** (App Review) e no **KAM-095** (lista de espera).

**Por isso a Q9 mantém-se no lote 1**: é a única via para o detalhe, e sem ele o
KAM-095 não sabe que fila está a gerir nem o KAM-102 sabe o que submete.

---

## 4. Regra de decisão de H4

**H4**, em
[`../../../exploracao/14-tese-minima-e-plano-de-validacao.md`](../../../exploracao/14-tese-minima-e-plano-de-validacao.md)
§2: «A Meta aceita o caso de uso (assistente de PME, templates, opt-in)».
Critério de sucesso: «resposta escrita ou aprovação». Prazo: **semanas 1 a 6**.

A regra abaixo é a do critério 5 do bloco KAM-101, escrita como lista de
verificação. **Avalia-se à semana 6**, e **não antes**: avaliar mais cedo só
pode produzir `inconclusiva`, que é o resultado por omissão.

### 4.1 `confirmada` — duas vias, e só uma fecha o risco

```text
VIA A — resposta escrita da Meta
[ ] Existe resposta à Q2, classificada CONFIRMADO pelo §2.1
    (da Meta, por escrito; verbal não serve)
[ ] Essa resposta NÃO classifica o produto como AI Provider,
    ou declara que a IA é «incidental or ancillary» no nosso caso
[ ] A resposta está arquivada em ficha do §2.2, com texto integral

VIA B — aprovação de Tech Provider
[ ] O estatuto de Tech Provider está confirmado (KAM-102, critério 4),
    com captura datada do painel da app
[ ] O App Review concedeu advanced access a whatsapp_business_messaging
    e whatsapp_business_management
```

> **A ressalva, por escrito, como o critério 5 exige.** **A aprovação de Tech
> Provider sozinha não afasta o critério «exclusivo da Meta».** A secção 4.7
> dos Termos diz que é a Meta que determina, **a seu exclusivo critério**, o que
> é um *AI Provider* e o que é funcionalidade principal — e diz isto sem prazo e
> sem o ligar a nenhuma aprovação. Uma aprovação de Tech Provider é uma
> verificação de **entidade e de aplicação**; não é uma apreciação do caso de
> uso, e **não impede** a Meta de reclassificar o produto depois. Logo:
>
> - H4 `confirmada` **pela via B** é a hipótese de **acesso** validada, e deixa
>   o **risco 1 de E1 inteiramente aberto**.
> - H4 `confirmada` pela via B **não** fecha **D2** e **não** levanta o
>   diferimento do Fluxo B do **ADR-011**: esses dependem da via A, que é o que
>   o ADR-011 diz por escrito («diferidos até resposta escrita da Meta»).
> - Só a **via A** fecha o item NÃO VERIFICADO do risco 1.
>
> **Divergência de leitura, medida e devolvida.** O critério 5 dá as duas vias
> como alternativas para `confirmada` («resposta escrita da Meta que não
> classifica o produto como *AI Provider*, **ou** aprovação de Tech Provider»),
> e no mesmo período manda escrever que a aprovação sozinha não afasta o
> critério exclusivo. As duas metades podem ler-se de duas maneiras: (i) a via B
> dá `confirmada` com o risco anotado, ou (ii) a via B não chega para
> `confirmada`. Esta secção adopta a **leitura (i)**, porque é a literal, e
> acrescenta-lhe o que a segunda metade do critério exige: a via B não fecha D2
> nem o ADR-011. **Qual das duas leituras vale é decisão de quem escreveu o
> critério**, não do executor — e fica **devolvida ao Responsável de Produto**
> (§7, item 7).

### 4.2 `inconclusiva` — o resultado por omissão à semana 6

```text
[ ] Chegou a semana 6 sem resposta CONFIRMADO à Q2 (via A falhada)
[ ] O risco está aceite, por escrito e datado, pelo Responsável de Produto
[ ] O plano B está no ficheiro: ≥ 2 cotações formais de BSP
    (KAM-102, critério 4; a Q15 é o pedido)
[ ] O Fluxo B fica diferido (ADR-011 mantém-se, sem alteração)
[ ] D2 mantém-se CONDICIONAL (§5)
```

**`inconclusiva` não é falha, e não para o Piloto.** O Piloto corre em Fluxo A,
no número da própria PME (ADR-011), e o que fica diferido é o Fluxo B. O que
`inconclusiva` custa é o risco aceite: o produto arranca sem saber se a Meta o
lê como *AI Provider*, e o risco 1 de E1 continua existencial. É por isso que a
aceitação tem de ser **escrita e datada**, e não tácita.

### 4.3 `refutada`

```text
[ ] Há resposta da Meta, classificada CONFIRMADO, que:
    [ ] classifica o produto como AI Provider, ou
    [ ] recusa expressamente o caso de uso
[ ] A ficha da resposta está escrita (§2.2), com texto integral
[ ] Aplica-se o pivô de `14` §6: mudar de canal
    (BSP parceiro, outro número, ou produto sem automação
     no WhatsApp da PME)
[ ] A decisão de pivô é assinada (Carta §4.2; é do fundador)
```

### 4.4 Registo de H4

Na forma do «Esquema do Registo de Hipóteses» do EPIC-10 §1. O registo central
de H1–H9 é o `Gate_Piloto.md` do **KAM-110**, que ainda não existe; até existir,
a linha de H4 vive aqui.

| Campo | Valor |
|---|---|
| H | **H4** |
| Enunciado | A Meta aceita o caso de uso (assistente de PME, templates, opt-in) |
| Limiar | Resposta escrita (via A) ou aprovação de Tech Provider (via B), com a ressalva do §4.1 |
| Método | Pergunta escrita à Meta (Q2, com Q1, Q6, Q7 em apoio) e pedido de Tech Provider (KAM-102) |
| Amostra n | **0** — nenhuma pergunta enviada |
| Resultado | — |
| Estado | **`inconclusiva`** (por omissão; nada medido) |
| Fonte | Este ficheiro, §1.1 e §2.2 |
| Decisão | **D2** (e D5, pela via B) |
| Pivô aplicável | `14` §6 — mudar de canal |
| Dono | **Responsável de Produto** |
| Data | 2026-11-05 (abertura do registo) |

---

## 5. D2 e D10

### 5.1 D2 — Fluxo B / número agregador

| Campo | Valor |
|---|---|
| Decisão | **D2** — Fluxo B / número agregador ([`../../00_Arquitectura_Solucao.md`](../../00_Arquitectura_Solucao.md) §13.3) |
| Estado | **CONDICIONAL**, mantido |
| Depende de | Resposta escrita da Meta a **Q1** (agregador e personificação), **Q5** (pagamentos nativos) e **Q6** (Meta Business Agent) |
| Estado dessas três | **Q1 `por enviar`**, **Q5 `por enviar`**, **Q6 `por enviar`** — nenhuma enviada, nenhuma respondida |
| Gatilho | A **primeira resposta CONFIRMADO** a Q1. Enquanto Q1 estiver sem resposta CONFIRMADO, D2 não muda de estado, e o Fluxo B mantém-se diferido pelo **ADR-011** |
| Prazo | «antes de Clusters» (§13.3) |
| Dono | Responsável de Produto; a decisão é do fundador (Carta §4.2) |
| Assinatura | — (um estado mantido não se assina como decisão) |

As três perguntas estão no **lote 2**, e isso é deliberado: D2 vence «antes de
Clusters» e o que condiciona o Piloto é o lote 1. Trocar a ordem era antecipar
uma decisão que não bloqueia o arranque à custa das oito que bloqueiam.

### 5.2 D10 — canal operacional da KAMBÁ

| Campo | Valor |
|---|---|
| Decisão | **D10** — canal operacional da KAMBÁ para estafetas, agentes de activação e suporte às PMEs |
| Estado | **Registo provisório** (o critério 6 pede o registo, não o fecho) |
| Decisão provisória | No Piloto, o suporte da KAMBÁ à PME corre na **linha de WhatsApp Business do fundador**, **com o risco assumido** |
| Fonte da provisória | [`../../10_Onboarding_Governanca.md`](../../10_Onboarding_Governanca.md) §11.1, que já o documenta: «o Piloto pode começar na linha de WhatsApp Business do fundador, assumindo o risco» |
| Risco assumido | A linha é pessoal e não é um `tenant` da plataforma; o `tenant` `platform` está **vedado até D2** (§13.3). Não há isolamento de dados por *tenant* nesse canal, nem continuidade se a linha mudar de mãos |
| Gatilho | **Resposta da Meta** — Q1 (agregador, personificação, nome de exibição) e Q6. Com resposta CONFIRMADO a Q1 que permita o número da plataforma, D10 passa a decidir-se entre canal próprio da plataforma e o canal do fundador; sem ela, mantém-se a provisória |
| Prazo | «antes de Clusters» (§13.3) |
| Dono | Responsável de Produto |
| Assinatura (fecho de D10) | — **do fundador** (Carta §4.2) |

> **O que «provisório» significa aqui.** A linha da decisão provisória **põe por
> escrito o que o desenho já assume** em `10` §11.1 — não é uma escolha nova
> feita neste ticket, e não desbloqueia nada: o `tenant` `platform` continua
> vedado, D2 continua CONDICIONAL, e o fecho de D10 continua à espera do
> fundador. É a mesma forma do registo provisório de D9 no
> [`Seguimento_APD.md`](Seguimento_APD.md) §3.

### 5.3 D5 — não é deste ticket

**D5** (Tech Provider directo *vs* BSP) é registada pelo **KAM-102**, critério 4,
«até à semana 4». As perguntas deste dossiê que a alimentam são **Q8, Q9, Q11 e
Q15**, e a Q15 é o pedido de cotação que o critério 4 do KAM-102 exige. Aqui
regista-se só essa ligação; a decisão e a tabela de opções são lá.

---

## 6. Impacto de cada resposta nos tickets

O que cada resposta muda, por ticket. **Nenhuma linha está accionada**: todas
dependem de uma resposta que não existe.

| Ticket | Perguntas que o afectam | O que muda com a resposta |
|---|---|---|
| **KAM-016** — Embedded Signup v4 e Tech Provider | Q1, Q2, Q3, Q4, Q6, Q12 | Q3 e Q4 decidem se a coexistência em +244 se promete no produto ou se o ES arranca em `cloud_only`; Q12 fixa *timeout*, *retry* e *pair rate limit* do consumidor de *webhooks*; Q6 decide se é preciso tratar *standby partner* e *thread control*; Q1 e Q2 decidem se o Fluxo B deixa de estar diferido |
| **KAM-033** — Guardrails de entrada e saída | Q2, Q7 | Q2 fixa o quão estreito tem de ser o domínio: se a Meta der critérios de «primary», o *guardrail* de domínio passa a ter um limiar defensável em vez de uma regra nossa; Q7 decide se o conteúdo de conversa pode sair para um LLM de terceiros e sob que obrigações de retenção |
| **KAM-088** — Screening de categorias | Q13 | A lista completa da Commerce Policy aplicável a Angola é a metade «Meta» da união «lista Meta ∪ lei» que o ticket implementa como *policy-as-code*; sem ela, essa metade é a leitura de E1 §4, que é parcial por declaração própria (a página da Commerce Policy não foi lida) |
| **Clusters** (fase 2) | Q1, Q5, Q6, Q10, Q13, Q14 | Q1 decide o número agregador e portanto o Fluxo B; Q5 decide se o *checkout* pode entrar no WhatsApp ou fica externo; Q10 e Q14 entram no modelo de custo e na régua de cobrança; Q6 decide se a Meta é concorrente no mesmo número |
| **KAM-102** — Tech Provider (fora deste ticket) | Q8, Q9, Q11, Q15 | Q8 substitui o prazo NÃO VERIFICADO da Business Verification por um valor real; Q9 dá o conteúdo da *Access Verification*; Q11 decide Tech Provider directo *vs* MPS/BSP; Q15 são as cotações do critério 4 |
| **KAM-095** — Lista de espera do limite de onboarding | Q9 | O limite (10 → 200 por 7 dias) e o que a *Access Verification* exige; e, pela releitura do §3.4, a condição anterior de *advanced access* por permissão |
| **KAM-049** — Catálogo AI (`ext:KAM-101`) | Q2, Q7, Q13 | Q13 decide que categorias de produto o catálogo pode aceitar; Q7 decide o que pode ser enviado a um modelo de visão de terceiros |
| **KAM-058** — Régua de cobrança (`ext:KAM-101`) | Q10, Q14 | A janela FEP (72 h ou 7 dias) e os limites por utilizador de marketing decidem quantos avisos da régua são gratuitos e quantos pagam template |
| **KAM-100** — Spike H3 (`14` §2) | Q3, Q4 | A resposta escrita confirma ou desmente o que o spike mede com três números reais; se divergirem, vale o medido, e a divergência vai a registo |

---

## 7. O que este ficheiro não entrega, e de quem fica à espera

Cada linha tem um **credor nomeado**. Nenhuma diz «quando X aterrar» nem «fica
para depois».

| # | O que falta | Porquê não é do executor | Credor |
|---|---|---|---|
| 1 | **Enviar** as 15 perguntas (critério 2) | Enviar em nome da empresa é acto humano; o bloco KAM-101 di-lo: «o Claude Code (…) **não** envia nada em nome da empresa» | **Fundador** (única autoridade para comunicar em nome da empresa), por proposta do **Responsável de Produto** |
| 2 | **Escolher e registar o canal** | O canal antes da aprovação de Tech Provider é **NÃO VERIFICADO**; descobre-se ao tentar, e quem tenta é quem tem a conta | **Responsável de Produto** |
| 3 | **Aprovar o texto antes do envio** (DoD 3) | A aprovação do envio é do Responsável de Produto por DoD; o texto está redigido e sem dados pessoais | **Responsável de Produto** |
| 4 | **Arquivar cada resposta** (critério 3) | Não há resposta nenhuma. O **modelo** está no §2.2 e a ficha nasce com a resposta | **Responsável de Produto** |
| 5 | **Datas absolutas de seguimento** (critério 7) | «Dia 5» e «dia 10» contam-se do dia 0, que é o dia do envio e não existe. A **regra** está no §8; as datas põem-se ao enviar | **Responsável de Produto** |
| 6 | **Corrigir E1 §4 e `10` §11.3** quanto ao âmbito da cláusula 4.7 (desvio 1, §3.1) | O critério 4 manda **registar** o desvio, não corrigir o E1; corrigir um documento de evidência fora do escopo deste ticket era alargar escopo em silêncio | **KAM-NNN a abrir** pela linha L1 (achado → ticket); o achado está no §3.1 e basta-se |
| 7 | **Decidir qual das duas leituras do critério 5 vale** (§4.1) | Mudar o sentido de um critério de aceitação é de quem o escreveu | **Responsável de Produto** |
| 8 | **Fechar D10** | Fecho de decisão aberta é do fundador (Carta §4.2); aqui só se regista a provisória | **Fundador** |
| 9 | **Validar com `validar_evidencia.py`** («Testes Requeridos») | O script **não existe** no repositório: é um artefacto que o KAM-100 ainda tem de escrever («escreve (…) `scripts/validar_evidencia.py`», EPIC-10 §KAM-100). Verificado a 2026-11-05: nenhum ficheiro com esse nome na árvore | **KAM-100** |
| 10 | **Revisão cruzada das 15 perguntas** por pessoa distinta do autor | É, por definição, de outra pessoa | **Responsável de Produto** |

---

## 8. Seguimento

A regra, que não depende de datas; as datas absolutas entram quando houver dia 0
(§7, item 5).

| Marco | Quando | Acção | Dono |
|---|---|---|---|
| **D+0** | dia do envio do lote 1 | Registar canal, data e estado `enviada` nas 8 linhas do lote 1 (§1.1) | Responsável de Produto |
| **dia 5** | prazo do critério 2 | Lote 1 (**8** perguntas) enviado | Responsável de Produto |
| **dia 10** | prazo do critério 2 | Lote 2 (**7** perguntas, Q15 incluída) enviado **e** **lembrete** sobre o lote 1 ainda sem resposta | Responsável de Produto |
| **após aprovação de Tech Provider** | KAM-102, critério 4 | **Escalamento por *Direct Support*** das perguntas ainda sem resposta — o acesso a *Direct Support* é um dos atributos do estatuto (E1 §3) e só existe depois da aprovação | Responsável de Produto |
| **semana 6** | Carta §4.2; `14` §2 | Avaliar **H4** pelo §4 e registar o resultado no §4.4; marcar `sem resposta` o que continuar sem resposta | Responsável de Produto |

**Antes da aprovação de Tech Provider não há *Direct Support*.** É por isso que
o escalamento tem como gatilho a aprovação e não uma data: marcá-lo para o dia
20 seria marcar um canal que ainda não existe.

---

## 9. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto (dono de H4, D2, D10) | | | |
| Arquitecto de Plataforma | | | |
| Fundador (envio em nome da empresa; fecho de D10) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-101. As **15** perguntas de E1 com os nove campos do critério 1, em **EN** (redigido aqui) e **PT** (o de E1, sem alteração de sentido), repartidas nos três lotes do bloco — **8** no lote 1 do Piloto, **6** de Fluxo B e Clusters e a **Q15** de custo no lote 2. A folha de seguimento e o registo de respostas **nascem vazios**: 15 linhas em `por enviar`, 0 enviadas, 0 respondidas. Modelo de ficha de resposta com a regra de classificação pela **origem** — CONFIRMADO só da Meta por escrito, INDÍCIO para BSP, parceiro, fórum ou verbal, **verbal incluída mesmo vindo da Meta**. Releitura das quatro fontes primárias **em inglês** a 2026-11-05, por extracção automática e com esse limite declarado, que rendeu **quatro desvios** face a E1: o rótulo «Updated» não existe em nenhuma das três páginas de documentação (desvio 0); a restrição de treino de ML da cláusula **4.7** está **ligada ao caso de se contratar um *AI Provider* como *Solution Provider*** e tem **excepção** para afinar modelo de uso exclusivo próprio, onde E1 a dá como proibição geral (desvio 1); **15 Jan 2026** é a data dos **Termos** e não da política de preços, que vigora desde **16 Fev 2026** (desvio 2); o inglês diz **«incidental or ancillary»** e não «acidental ou complementar» (desvio 3); e o historial de países da coexistência **não se reproduz** — a entrada dos oito países é de 23 Out 2025 e não de 25 Nov 2025, e a de 15 Abr 2026 com Nigéria e África do Sul não existe na leitura (desvio 4), pelo que o historial baixa a **INDÍCIO** nas duas direcções. Nenhum desvio corrige o E1 neste ticket, e a conclusão de desenho não muda: as duas leituras concordam em que **não há lista oficial** e **Angola não aparece**. Regra de H4 como lista de verificação com as três saídas e a **ressalva escrita** de que a aprovação de Tech Provider sozinha não afasta o critério «exclusivo da Meta» — pelo que `confirmada` pela via B não fecha D2 nem levanta o diferimento do ADR-011. **D2** mantida **CONDICIONAL** com o estado de Q1, Q5 e Q6, e **D10** registada como **provisória** (canal do fundador no Piloto, risco assumido, `10` §11.1) com gatilho na resposta da Meta. Dez itens devolvidos no §7, cada um com credor nomeado, entre eles o `validar_evidencia.py` dos «Testes Requeridos», que **não existe** na árvore e é artefacto do KAM-100. | Equipa KAMBÁ |

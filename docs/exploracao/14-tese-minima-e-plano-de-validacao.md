# 14 — Tese mínima e plano de validação (de exploração a ideia testável)

Os documentos 01–13 são exploratórios. Este documento fixa **o que se vai testar primeiro** e
**o que se deixa de lado até haver evidência**. Onde diz *[decisão]*, é escolha do fundador;
onde diz *[hipótese]*, é proposta a validar, não facto.

---

## 1. Tese mínima

**Segmento [decisão]:** PMEs formais ou em formalização em Luanda (têm NIF e conta bancária).

**Produto de entrada [decisão]:** "Rececionista + Loja" para essas PMEs, no WhatsApp:
responde a clientes, mostra catálogo, marca/reserva e emite o pedido com pagamento.

**Promessa:** *"Não perca mais nenhum cliente por não responder ao WhatsApp, e receba o pagamento
sem andar atrás de comprovativos."*

**Quem paga [hipótese]:** a PME, por assinatura (planos do doc 02 §6). Comissão sobre transacção
fica **desligada** até haver unit economics provados.

**Fica fora até haver evidência:** assistente de consumo no número da plataforma (Fluxo B/B2),
PME light, logística federada, revendedores, Kambá Score, diáspora, AdsEngine, API aberta,
grupos de bairro, índice federado. Ficam como opções futuras; não entram no piloto nem no
orçamento.

**Porquê esta redução:** as hipóteses que mais pesam (pagamento por PME, política da Meta para
número agregador, preço opaco, atribuição de comissão) pertencem todas ao Fluxo B e ao
marketplace. O Fluxo A para PME formal, no número dela, evita a maioria.

**Tensão a gerir:** juntar Rececionista e Loja alarga o piloto. Proponho que a Loja entre
**por camadas** (§4): primeiro atendimento e catálogo informativo, depois pedido, depois pagamento.

**Módulos de entrada [decisão do fundador, 2026-10-09; ADR-020].** Além do atendimento, entram
no Piloto (Fase 1) até **4 módulos de captação e suporte**, *owner-facing* e com o dono no circuito:
**Catálogo AI**, **Foto de produtos AI**, **Social AI** (calendário, legendas e artes para
**publicação manual**) e **Orçamento expresso**. Porquê: dão valor à PME sem depender de pagamento
integrado nem de Fluxo B, funcionam no painel web mesmo antes de o WhatsApp estar ligado, e atacam
o risco dominante (distribuição, H1) com um produto que se demonstra em minutos. Limites que
protegem o core: máximo 4; o dono aprova tudo o que sai para terceiros; sem publicação automática
em redes; **não bloqueiam o gate da Fase 0**; cortam-se primeiro se a Fase 0 derrapar (excepto o
Catálogo AI, pré-requisito do onboarding). Hipóteses H10–H12 (§2). Ficam de fora: Arquivo AI,
Compras AI, consignação, clube digital; Factura AI só como spike (KAM-126).

---

## 2. Hipóteses críticas e critério de sucesso

Cada hipótese tem de morrer ou sobreviver com um número. Limiares são **propostas minhas**.

| # | Hipótese | Como testar | Sucesso | Prazo |
|---|---|---|---|---|
| H1 | PMEs formais pagam por atendimento + loja no WhatsApp | 30 entrevistas + 10 pilotos concierge a preço real | ≥ 5 pagam após 30 dias de piloto | sem. 1–8 |
| H2 | O preço pode ser publicado/respondido pelo bot | Entre as 30 PMEs, quantas aceitam preço fixo ou "a partir de" | ≥ 50% aceitam para ≥ 70% do catálogo | sem. 1–4 |
| H3 | Coexistência funciona no número da PME angolana | Spike técnico: 3 números reais, embedded signup, sync | 3/3 ligados sem perda de histórico | sem. 1–3 |
| H4 | A Meta aceita o caso de uso (assistente de PME, templates, opt-in) | Leitura da política em fonte primária + pedido de Tech Provider/BSP | Resposta escrita ou aprovação | sem. 1–6 |
| H5 | Existe via de cobrança com confirmação server-side para uma PME | Reunião com 2 bancos + 2 facilitadores (ProxyPay, AppyPay) | Prazo e custo por PME conhecidos e ≤ 6 semanas | sem. 1–6 |
| H6 | Custo por conversa fecha com a assinatura | Medir 500 conversas reais: LLM + voz + Meta | Custo ≤ 15% da mensalidade | sem. 4–10 |
| H7 | O bot não fica sozinho em apuros (voz, regateio, kimbundu) | Dataset de 100 conversas reais, avaliação humana | ≥ 85% resolvidas sem handoff errado | sem. 4–10 |
| H8 | A PME mantém o catálogo actualizado | Observar 4 semanas: % de actualizações vs. mudanças reais | ≥ 60% de catálogos correctos em auditoria | sem. 4–12 |
| H9 | Retenção: usam depois do 1º mês | Cohorts do piloto | ≥ 70% activos ao dia 60 (das PMEs activadas até à semana 4) | sem. 8–12 |
| H10 | Os **módulos de entrada** (Catálogo AI, Foto de produtos AI, Social AI, Orçamento expresso) atraem PMEs | % das PMEs onboardadas que usam ≥ 1 módulo de entrada nas 2 primeiras semanas | ≥ 60% (*proposta*) | sem. 7–12 |
| H11 | Os módulos de entrada levam ao atendimento | % das PMEs que entram por um módulo de entrada e activam o Vendedor/Serviços aos 30 dias | ≥ 30% (*proposta*) | sem. 8–12 |
| H12 | O custo de geração fecha e há disposição a pagar | Custo por PME/módulo (imagem + texto) e nº de PMEs que pagam por módulo isolado | custo ≤ 15% do preço do módulo; ≥ 3 PMEs pagam (*propostas*) | sem. 8–12 |

**Regra de decisão:** se H1 ou H5 falharem, a tese muda antes de se escrever mais código
(ver §6). H3 e H4 são técnicos e baratos, mas bloqueiam tudo: correm primeiro.

---

## 3A. Caminho escolhido: build-first *[decisão do fundador]*

O fundador domina a parte técnica e vai construir primeiro; o produto a funcionar é a ferramenta
de venda (demo viva) e o que abre a rede comercial. As regras abaixo limitam o risco desse caminho.

**Regra 1 — Fatia fina vendável (8–10 semanas).** Só o que se demonstra a uma PME:
- Número da PME por coexistência (Fluxo A), nada de número agregador.
- Agente único (LangGraph) com: atendimento, catálogo (foto → produto), horários/morada,
  marcação ou pedido com reserva de stock, handoff para o dono.
- Pagamento por **adapter**: começa em `ManualProvider` (dono confirma, limite de valor) e troca
  para ProxyPay/AppyPay quando o contrato existir. O resto do código não muda.
- **Decisão do fundador: base arquitectural forte desde o início, para explorar verticais.**
  Não se troca o desenho do doc 10/11 por um MVP descartável. Em vez de cortar serviços, corta-se
  a **profundidade** de cada um (ver Regra 1B).
- Fora do piloto: voz em kimbundu, logística, revendedores, índice federado, número da plataforma.

**Regra 1B — Esqueleto andante (walking skeleton) com costuras definitivas.**
Primeiro um fio fino que atravessa **todas** as primitivas de ponta a ponta, depois engorda-se.

| Costura (fixar já, não reescrever) | Implementação inicial (pode ser fina) |
|---|---|
| Tenant + entitlements + `ChannelResolver` | tabelas do doc 11 §2; 1 persona por número |
| Event bus com outbox transaccional + envelope versionado | BullMQ/Redis |
| `AgentRegistry` + `ToolLayer` (tenant vem do estado, nunca do texto) | 2 verticais de atendimento desde o início, mais até 4 **módulos de entrada** finos (Catálogo AI, Foto de produtos AI, Social AI, Orçamento expresso) na Fase 1, com o dono no circuito (ADR-020) |
| `PaymentProvider` | `ManualProvider` → ProxyPay/AppyPay |
| `LLMProvider` (LiteLLM) + metering por tenant | OpenAI/Gemini com chaves virtuais |
| `HandoffProvider` | Chatwoot via Agent Bot API (atrás da interface) |
| Registo de comércio (produtos, pedidos, stock, reservas) | **Medusa v2**, após spike de 3–5 dias; fallback Medusa puro + `merchant_id` |
| `ChannelAdapter` | Cloud API + coexistência |

Diferimento permitido (só o *como*, nunca o *onde*): ClickHouse, Keycloak, Valhalla, k8s,
Meilisearch, Mercur (se o spike falhar), tier público de API.

**Regra de dois:** uma abstracção só se valida com **duas** verticais diferentes. Construir em
paralelo **Vendedor** (catálogo, pedido, pagamento, stock) e **Serviços/Rececionista** (agenda,
marcação, lembretes). Se o mesmo `AgentRegistry`, `ToolLayer`, eventos e entitlements servirem às
duas sem excepções no core, a tese "verticais são configuração" fica provada; se não, corrige-se
a abstracção antes de haver uma terceira vertical.

**Controlo do risco de escopo (o preço desta escolha).** Fundação e piloto não se confundem:
- A fundação tem **teto de 6 semanas** até o esqueleto andante responder numa conversa real,
  criar um pedido, receber um callback de pagamento e disparar um evento consumido por outra vertical.
- A cada vertical nova aplica-se o teste do doc 10: ≥ 70% reaproveitado. Abaixo disso, parar e rever.
- A validação comercial (H1, H9) corre sobre o esqueleto; não espera pelas verticais todas.

**Regra 2 — Demo como motor de distribuição.** Um número de demonstração (loja fictícia) que
qualquer pessoa pode testar em 2 minutos. É o que se mostra a contabilistas, bancos, associações
e conhecidos. Cada demo termina em pedido de piloto.

**Regra 3 — Itens com tempo de espera arrancam na semana 1, em paralelo ao código.** Dependem
de papel e de investimento, não de engenharia, e são o caminho crítico real:

| Item | Porquê já | Investimento |
|---|---|---|
| Empresa/entidade legal e portfólio Meta Business verificado | Sem isto não há embedded signup nem tiers | baixo, tempo |
| Pedido de Tech Provider / escolha de BSP | A elegibilidade e prazos condicionam o produto | baixo, tempo |
| Banco ou facilitador (ProxyPay/AppyPay) | 2–6 semanas; define a camada 3 | contrato + taxas |
| Parecer jurídico (Lei 22/11, BNA) | Bloqueante se houver transferência de dados e comissão | honorários |
| Software AGT certificado (parceiro Factura AI) | Gancho de 2027 | acordo comercial |

**Regra 4 — O sinal comercial mede-se em uso real, não em simpatia.** 10 PMEs em piloto gratuito
de 30 dias com meta de ≥ 5 a converter a pago (H1) e ≥ 70% activas ao dia 60 (H9). Quem não
usa na semana 2 sai e é substituído.

**Regra 5 — Pontos de decisão.** Se na semana 6 H3 (coexistência) ou H4 (Meta) falharem, pára-se
a camada de canal e muda-se a estratégia (BSP/outro canal) antes de gastar mais engenharia. Se
na semana 10 não houver 5 PMEs a usar a demo no número delas, o problema é distribuição, não
produto, e passa-se ao §3 como trabalho principal.

---

## 3. Experimentos sem código (complementar: ~20% do tempo, em paralelo)

**Ponto de partida honesto: não há rede comercial.** No caminho build-first, estes experimentos
deixam de ser a fase 1 e passam a correr ao lado do código, sobretudo a abertura de canais
(contabilistas, associações) e as cartas às partes reguladas.

1. **Canal de acesso a PMEs formais [hipótese]:** contabilistas e gabinetes de contabilidade são
   quem já fala com PMEs sobre NIF, facturação e AGT. Testar 5 parcerias: o contabilista indica,
   a plataforma dá-lhe comissão ou a ferramenta como serviço seu. Alternativas a testar em
   paralelo: associações comerciais, programas PME de bancos, incubadoras.
2. **Entrevistas (30):** dor real de atendimento, quanto pagariam, como cobram hoje, que
   comprovativos recebem, se publicariam preços. Guião curto, sem pitch.
3. **Piloto concierge (10 PMEs):** operação manual por trás do WhatsApp Business da PME, com
   IA a rascunhar e um humano a aprovar. Mede-se o problema antes de automatizar.
4. **Cartas às partes reguladas e infraestruturais:** perguntas escritas a Meta/BSP, a 2
   facilitadores de pagamento e a um advogado local (APD, BNA, informação de crédito).
5. **Pesquisa de concorrência directa:** quem já vende atendimento/loja no WhatsApp em Angola
   ou em mercados vizinhos, a que preço, com que resultados.

Perguntas que o advogado e os parceiros têm de responder por escrito:
- A plataforma pode cobrar mensalidade e, no futuro, comissão sem licença BNA, mantendo a
  liquidação directa à PME?
- Que entidade/TPA virtual precisa cada PME, e em quanto tempo e a que custo?
- Enviar conversas a APIs de LLM fora de Angola exige autorização da APD? Com que texto de
  consentimento?
- O número agregador da plataforma é permitido pela política da Meta? (só relevante se o
  Fluxo B regressar.)

---

## 4. Faseamento do produto (só depois de H3, H4 e H1 parcial)

| Camada | Entrega | Pagamento | Gate para avançar |
|---|---|---|---|
| 1 | Atendimento + catálogo informativo + marcações, no número da PME | Nenhum | H2, H3, H7 |
| 2 | Pedido registado com reserva | PME cobra nos seus meios; **confirmação humana, sem comprovativo como prova automática** | H8 |
| 3 | Pedido com pagamento confirmado server-side | Facilitador (ProxyPay/AppyPay) | H5 |
| 4 | Cobranças automáticas, Factura AI via parceiro certificado | idem | H9 |

A camada 2 reconhece o que o doc 08 já admitia: sem facilitador ainda, o pagamento é confirmado
por pessoa. Isso é aceitável **no piloto**, mas tem de estar assumido e limitado (valor máximo
por pedido) e não escondido atrás da regra "nunca comprovativo".

---

## 5. Orçamento e equipa (preencher com os números reais)

Não tenho os valores de capital nem o tamanho da equipa. A estrutura do orçamento para 12 semanas:

| Rubrica | Notas |
|---|---|
| Pessoa(s) a tempo inteiro | produto/comercial em Luanda; engenharia |
| Operador humano do concierge | 1 pessoa cobre 10 PMEs no início |
| Jurídico (Lei 22/11, BNA) | pareceres escritos, não conversas |
| Técnica | Meta, LLM, voz, VPS — ordem de dezenas de dólares por mês no piloto (doc 08 §8) |
| Incentivos a parceiros (contabilistas) | comissão só por PME paga |
| Deslocações/materiais de campo | |

**Pergunta ao fundador:** com este capital, quantos meses de pista existem, e qual é o ponto em
que se pára ou se muda?

---

## 6. Critérios de pivô e de paragem

| Se acontecer… | Então… |
|---|---|
| H1 falha (menos de 5 pagantes) | Voltar às entrevistas: mudar segmento ou produto (candidato: Factura AI isolada) |
| H4 ou H3 falham | Mudar de canal: BSP parceiro, outro número, ou produto sem automação no WhatsApp da PME |
| H5 falha (pagamento > 6 semanas ou inviável) | Manter camadas 1–2; vender atendimento/agenda sem cobrança integrada |
| H2 falha (ninguém publica preço) | Reposicionar: atendimento e disponibilidade, não comparação de preço |
| H6 falha (custo > 15% da mensalidade) | Subir preço, reduzir modelo/voz, ou limitar volume por plano |
| Nenhum canal de acesso a PMEs funciona (§3.1) | Antes de construir mais, resolver distribuição: parceiro de banco, associação ou contratar comercial |

Paragem total: se ao fim de 12 semanas não houver ≥ 3 pagantes recorrentes e nenhum canal
comercial repetível.

---

## 7. Higiene documental (tarefas)

1. Arquivar 09 (desatualizado) e mover 08, 10, 11, 12 e 13 para uma pasta `visao-futura/`,
   com uma nota de que descrevem a arquitectura-alvo, não o piloto.
2. Resolver as contradições já identificadas: n8n/Typebot (licenças), custo por conversa
   (doc 07 vs 08), cunha (02/03 vs 05 vs 06), comprovativo na fase 0, farmácia (07 vs 13).
3. Corrigir o `../INDICE.md`: contagem de documentos e remover a ligação a `../tecnica/` (os 11
   documentos não existem), ou marcar `../tecnica/INDICE.md` como plano.
4. Passar a manter um **registo de decisões e de evidências**: cada hipótese H1–H9 com data,
   resultado e fonte.
5. Substituir as afirmações de mercado (EMIS, Meta, preços) por fonte primária ou marcá-las
   como não verificadas.

---

## 8. Próximos 14 dias

1. Fechar este documento com os dados em falta (capital, equipa, objectivo de receita).
2. Escrever o guião de entrevista e a lista de 30 PMEs-alvo (via contabilistas e associações).
3. Spike H3: ligar 3 números por coexistência.
4. Pedir as reuniões bancárias e as respostas escritas do §3.4.
5. Montar a folha de registo de hipóteses.

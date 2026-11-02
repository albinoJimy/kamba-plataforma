# Pacote de perguntas para o parecer jurídico — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — Pacote de perguntas para o parecer jurídico (APD, BNA, AGT, Termos da Meta) |
| Versão | 1.1 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno, destinado a transmissão a advogado sob compromisso de confidencialidade |
| Ticket | KAM-104 (EPIC-10) |
| Documento-fonte | `../E3_Regulatorio_Dados.md`, `../E2_Pagamentos_Angola.md`, `../E1_Meta_WhatsApp.md`, `../../08_Seguranca_Conformidade.md` (§7, §8, §13) |
| Anexo | [`Anexo_Factos_do_Caso.md`](Anexo_Factos_do_Caso.md) — factos do caso, sem dados pessoais |
| Artefactos internos | Molde de selecção do advogado e registo de respostas, num ficheiro interno que **não acompanha o pacote** e cujas secções são citadas pelo número, sem ligação |

> **Este documento não é aconselhamento jurídico e não contém nenhuma leitura
> jurídica definitiva da KAMBÁ.** É um pedido de parecer. Cada afirmação sobre
> direito angolano ou sobre os Termos da Meta aparece de uma de duas formas, e
> nunca de outra: **com o estado de verificação** com que foi lida na evidência
> da KAMBÁ — CONFIRMADO, INDÍCIO ou NÃO VERIFICADO, e também «interpretação» ou
> «inferência» quando é raciocínio nosso —, ou **com a marca
> *(a confirmar por parecer)*** quando é conclusão da KAMBÁ sem fonte que a
> sustente. As «opções propostas pela KAMBÁ» são sempre **propostas**: existem
> para que o advogado tenha algo concreto para corrigir, não para que o confirme.
>
> A primeira versão deste aviso prometia a marca *(a confirmar por parecer)* em
> **toda** a afirmação, e o documento não cumpria a promessa — a revisão
> adversarial contou-a: 3 ocorrências no corpo e 37 das 40 perguntas sem
> nenhuma. O aviso passou a descrever o que o documento faz, em vez de o
> contrário, porque um advogado que confie numa ressalva universal baixa a
> guarda onde ela falta.

---

## 0. Como ler este pacote

### 0.1 A escala de três estados, e o que ela proíbe

Tudo o que neste pacote se afirma sobre o mundo traz o estado com que foi lido
nas fontes de evidência da KAMBÁ, e **não é promovido**:

| Estado | Significado |
|---|---|
| **CONFIRMADO** | Texto do diploma visto num portal que reproduz o Diário da República (lex.ao, angolex), no sítio da APD, ou facto confirmado por duas fontes independentes credíveis |
| **INDÍCIO** | Fonte única secundária (imprensa, escritório, resumo), ou inferência a partir de factos confirmados |
| **NÃO VERIFICADO** | Sem fonte encontrada, ou fontes contraditórias |

A escala é a de [`../E3_Regulatorio_Dados.md`](../E3_Regulatorio_Dados.md) §0,
datada de 8 de Outubro de 2026. Quando o contexto de uma pergunta cita essas
fontes, **herda o estado que lá está**. Um INDÍCIO citado aqui continua INDÍCIO;
se o pacote o apresentasse como facto, o parecer responderia à pergunta errada.

### 0.2 O aviso que a KAMBÁ pede que seja levado a sério

Os textos legais que a KAMBÁ leu vieram de **repositórios não oficiais**
(lex.ao, angolex), lidos por extracção automática de página. Números de artigo,
de coima e de prazo podem ter erros de transcrição.
**Pede-se que o parecer verifique cada artigo citado no Diário da República**
antes de o dar por boa; onde um número for crítico, o pacote assinala-o com
«verificar no DR».

### 0.3 Contexto mínimo do caso

A KAMBÁ está em **Fase 0 / Fase 1 (Piloto)** e **não está em produção**. Não há,
hoje, dados pessoais reais de clientes a correr na plataforma: a decisão de
alojamento (D1) é pré-requisito de dados reais, e até lá o desenho corre com
dados sintéticos (ADR-008). O Piloto previsto é de 5 a 10 PMEs, com equipa
pequena. Os factos do caso — fluxos de dados, subprocessadores, classes de
dados, retenção proposta, papéis e arquitectura de pagamentos — estão no
[`Anexo_Factos_do_Caso.md`](Anexo_Factos_do_Caso.md), sem dados pessoais.

### 0.4 Estrutura e contagem

| Bloco | Tema | Perguntas |
|---|---|---|
| **A** | APD e Lei 22/11 | 12 |
| **B** | BNA e Aviso 2/22 | 8 |
| **C** | AGT e factura | 6 |
| **D** | Termos e política da Meta | 1 |
| **E** | Alojamento, CDN e backups | 5 |
| **F** | Perguntas novas da KAMBÁ | 3 |
| **G** | Defesa do consumidor, categorias sectoriais e desinformação | 5 |
| | **Total** | **40** |

Origem das 40, e porque são 40:

| Origem | Perguntas | Onde ficaram |
|---|---|---|
| [`../E3_Regulatorio_Dados.md`](../E3_Regulatorio_Dados.md), «Perguntas para o advogado local» 1 a 20 | 20 | A (11), E (3), G (5), C (1) |
| [`../E2_Pagamentos_Angola.md`](../E2_Pagamentos_Angola.md) §9, perguntas 19 a 30 (BNA 19–25, AGT 26–29, contabilista 30) | 12 | B (7), C (5) |
| [`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md), «Perguntas que só a Meta/BSP pode responder por escrito» 7 | 1 | D (1) |
| [`../../08_Seguranca_Conformidade.md`](../../08_Seguranca_Conformidade.md) §13, linhas «Novas» N1, N2, N3 e N5 | 4 | A (1), B (1), E (2) |
| Novas deste pacote: X1, X2, X3 | 3 | F (3) |
| | **40** | |

> **O bloco G não vem da estrutura proposta no bloco do ticket, e isso é
> deliberado.** Os «Detalhes Técnicos» do KAM-104 propõem seis blocos (A a F).
> Cinco das vinte perguntas do `E3` — defesa do consumidor e venda à distância,
> responsabilidade da plataforma, medicamentos, categorias restritas, lei contra
> a desinformação — não caem em nenhum dos seis, e o critério 1 exige as vinte.
> Ou se forçavam para dentro de «APD e Lei 22/11», onde não pertencem e onde um
> advogado as leria como matéria de protecção de dados, ou ganhavam bloco
> próprio. Ganharam bloco próprio, nomeado.

### 0.5 Prioridades e prazos

As prioridades vêm de
[`../../08_Seguranca_Conformidade.md`](../../08_Seguranca_Conformidade.md) §13 e
do critério 2 do KAM-104, e **não foram reinventadas**:

```text
P0   bloqueia dados reais       E3 1, 2, 3, 4, 5, 6, 18, 20 + BNA 19, 20 + contabilista 30
P1   bloqueia Clusters          E3 7, 9, 11, 12, 15, 16 + as restantes classificadas P1
P2   refina                     E3 8, 10, 13, 14, 17, 19 + as restantes classificadas P2
```

| Prioridade | Perguntas | Prazo pedido |
|---|---|---|
| **P0** | 11 | Pacote enviado até ao **dia 7** (fim da semana 1). Resposta **preliminar** às P0 que decidem D1 até à **semana 3**; parecer **escrito** de todas as P0 até à **semana 6** |
| **P1** | 19 | Parecer escrito até à **semana 10** (*proposta* da KAMBÁ) |
| **P2** | 10 | Parecer escrito até à **semana 16** (*proposta* da KAMBÁ) |
| | **40** | |

As P0 que decidem **D1** (alojamento) são sete: A-01, A-02, A-03, A-11, E-01,
E-02, E-03. As restantes quatro P0 — A-04, B-01, B-02, C-06 — bloqueiam dados
reais ou a arquitectura de pagamentos, mas não a escolha de região, e pedem-se
para a semana 6.

Os prazos de P1 e P2 são **propostas da KAMBÁ**: fixam-se na carta de
compromisso, e o que vale é o prazo que o advogado comprometer por escrito. A
âncora da «semana 1» é o calendário do programa e **não está fixada em nenhum
documento lido** (NÃO VERIFICADO): as semanas aqui são relativas, e quem enviar
o pacote converte-as em datas.

### 0.6 Os oito campos de cada pergunta

Cada uma das 40 traz, pela ordem: **texto**, **contexto** (com o estado de
verificação e a fonte), **por que importa** (a decisão e os tickets bloqueados),
**opções propostas pela KAMBÁ** (propostas, nunca leituras), **resposta pedida**
(sempre parecer escrito, com referência e data), **prioridade** e **prazo
pedido**. O número da pergunta é o primeiro campo, e é o título do bloco.

### 0.7 Exportação

O que sai da casa são **dois ficheiros**: este pacote e o
[`Anexo_Factos_do_Caso.md`](Anexo_Factos_do_Caso.md). A exportação é o mesmo
conteúdo, sem nada retirado. **Nenhuma conversão correu aqui** — não há
conversor nesta máquina — pelo que escolher o formato (PDF, documento de
texto, ou os ficheiros como estão) e produzi-lo é o acto de quem envia, e
viaja com o critério 4.

---

## 1. O que se pede ao advogado

1. **Parecer escrito, não conversa.** Cada resposta com referência própria,
   data e assinatura. A KAMBÁ não trata nenhuma resposta como aconselhamento
   jurídico antes de a receber por escrito.
2. **Artigos verificados no Diário da República.** Onde o pacote cita um artigo
   lido em portal não oficial, pede-se a confirmação do texto e da numeração.
3. **Distinção explícita entre texto da lei, prática da autoridade e opinião.**
   Interessa à KAMBÁ saber qual das três sustenta cada conclusão — em especial
   onde a APD ou o BNA tenham prática não publicada.
4. **Onde a resposta for «depende», o pacote pede o critério**: o que teria de
   ser verdade para a resposta mudar, porque é isso que a KAMBÁ pode construir
   ou evitar.
5. **Prioridade respeitada.** As P0 bloqueiam o tratamento de dados reais e,
   sete delas, a decisão de alojamento. Se o prazo não puder ser cumprido,
   pede-se que o diga por escrito **antes** da semana 3, porque a KAMBÁ decide
   em função disso.
6. **Nada se pede que exija ver dados pessoais.** O anexo de factos é factual e
   não contém dados pessoais; se o parecer precisar de um exemplo concreto,
   pede-se que o solicite, em vez de a KAMBÁ o antecipar.

---

## 2. Mapa pergunta → decisão → ticket

As decisões são as do registo da Carta §4.2 e de
`../../00_Arquitectura_Solucao.md` §13.3. Os tickets são os que ficam
bloqueados por falta de resposta.

| N.º | Origem | Tema em uma linha | Prio | Decisão | Tickets bloqueados |
|---|---|---|---|---|---|
| A-01 | `E3` 1 | Subcontratada ou co-responsável; quem notifica a APD | P0 | **D1**, D9 | KAM-090, KAM-069 |
| A-02 | `E3` 2 | Enviar a um LLM é transferência? A pseudonimização muda isso? | P0 | D1, D9 | KAM-069, KAM-112 |
| A-03 | `E3` 5 | Prazos, silêncio positivo, taxas e formulários da APD | P0 | D1 | KAM-105, KAM-069 |
| A-04 | `E3` 6 | Saúde e vida privada: regime de dados sensíveis | P0 | — | KAM-033, KAM-088 |
| A-05 | `E3` 7 | Circular 02 e prazo de notificação de violações | P1 | — | KAM-083 |
| A-06 | `E3` 8 | Coimas do Art. 51.º: montantes e cumulação | P2 | — | — |
| A-07 | `E3` 9 | Marketing no WhatsApp: Art. 19.º e Instrutivo INACOM 4/20 | P1 | — | KAM-022, KAM-090 |
| A-08 | `E3` 10 | Idade mínima para consentir e contratar por chat | P2 | — | KAM-022, KAM-088 |
| A-09 | `E3` 17 | Estado do projecto de revisão da Lei 22/11 e da Lei da IA | P2 | — | — |
| A-10 | `E3` 19 | Valor probatório do contrato por chat; assinatura electrónica | P2 | — | KAM-090 |
| A-11 | `E3` 20 | A Meta como destinatário: notificação separada? | P0 | D1, D9 | KAM-069, KAM-105 |
| A-12 | `08` §13 N3 | HMAC com pepper: deixa de ser dado pessoal para a PME? | P1 | D9 | KAM-070, KAM-112 |
| B-01 | `E2` 19 | Desenho A cabe na exclusão técnica do Art. 4.º j)? | P0 | D8 | KAM-056, KAM-055 |
| B-02 | `E2` 20 | Bot a accionar pagamento: iniciação de pagamento? | P0 | D8 | KAM-056 |
| B-03 | `E2` 21 | Payouts instruídos pela plataforma | P1 | D8 | — (Clusters) |
| B-04 | `E2` 22 | Escrow / retenção até confirmação de entrega | P1 | D8 | — (Clusters) |
| B-05 | `E2` 23 | Capital social e fundos próprios do art. 18 após o Aviso 5/23 | P2 | D8 | — |
| B-06 | `E2` 24 | Regime de agentes de PSP após a revogação do Aviso 7/17 | P2 | D8 | — |
| B-07 | `E2` 25 | Sandbox regulatório ou consulta prévia ao BNA | P1 | D8 | — |
| B-08 | `08` §13 N5 | Confirmação do enquadramento do desenho A fora do Aviso 2/22 | P1 | D8 | KAM-056 |
| C-01 | `E2` 26 | Data em vigor da obrigação de e-factura | P1 | D7 | — (Clusters) |
| C-02 | `E2` 27 | Softwares certificados; chamada por API multi-tenant | P1 | D7 | — (Clusters) |
| C-03 | `E2` 28 | Certificar software próprio: processo, custo, prazo | P2 | D7 | — |
| C-04 | `E2` 29 | Registo de estabelecimentos; recibos online; limite de documentos | P2 | D7 | — |
| C-05 | `E3` 15 | Prazo de conservação do CGT; calendário das PMEs pequenas | P1 | D7 | KAM-070 |
| C-06 | `E2` 30 | IVA do SaaS; retenções a não residentes; câmbio em USD | P0 | D9 | — |
| D-01 | `E1` 7 | Texto exacto do §4.7 dos Termos; LLM de terceiros em inferência | P1 | D9 | KAM-040, KAM-112 |
| E-01 | `E3` 3 | Países adequados; garantias do Art. 34.º; cláusulas-tipo | P0 | D1 | KAM-105, KAM-069, KAM-077 |
| E-02 | `E3` 4 | Caso Crescer Tech: país da cloud e documentos que faltaram | P0 | D1 | KAM-105 |
| E-03 | `E3` 18 | Exigência de residência em Angola; África do Sul é adequada? | P0 | D1 | KAM-105, KAM-077, KAM-011 |
| E-04 | `08` §13 N1 | CDN/WAF que termina TLS é subprocessador? | P1 | D12 | KAM-077, KAM-076, KAM-069 |
| E-05 | `08` §13 N2 | Backups cifrados fora de Angola com a chave em Angola | P1 | D1, D12 | KAM-011, KAM-077 |
| F-01 | X1 | Dados reais de teste com consentimento em spikes | P1 | — | KAM-100, KAM-107 |
| F-02 | X2 | Quem paga os custos em USD; retenções a fornecedores estrangeiros | P1 | D9 | KAM-105 |
| F-03 | X3 | Conversas para avaliação face aos Termos da Meta | P1 | D9 | KAM-040 |
| G-01 | `E3` 11 | Venda à distância: desistência, informação, Livro de Reclamações | P1 | — | KAM-090 |
| G-02 | `E3` 12 | Responsabilidade da plataforma por informação errada da IA | P1 | D11 | KAM-090, KAM-033 |
| G-03 | `E3` 13 | Medicamentos, dispositivos médicos, suplementos, cosméticos | P2 | — | KAM-088 |
| G-04 | `E3` 14 | Álcool, tabaco, armas, jogos | P2 | — | KAM-088 |
| G-05 | `E3` 16 | Lei contra a desinformação: bot comercial é conta inautêntica? | P1 | — | KAM-088, KAM-058 |

### 2.1 O que o KAM-105 precisa de resposta

O KAM-105 decide **D1** (alojamento: Luanda ou JNB/CPT com procedimento APD) e
instrui o procedimento junto da APD. Das 40 perguntas, **sete decidem D1** e
são as que o KAM-105 não pode substituir por desenho próprio:

| N.º | O que o KAM-105 não consegue decidir sem isto |
|---|---|
| A-01 | Quem submete o procedimento: a KAMBÁ, cada PME, ou ambas. Sem isto não há submetente |
| A-02 | Se a chamada ao LLM é transferência e se a minimização muda o enquadramento. Decide se alojar em Luanda dispensa alguma coisa |
| A-03 | Prazo da APD, silêncio positivo, taxas e formulários. Decide se a submissão cabe antes dos dados reais |
| A-11 | Se a Meta exige notificação separada. Decide o perímetro da submissão |
| E-01 | Que países a APD reconhece. Decide se JNB/CPT é notificação ou autorização |
| E-02 | O que faltou no caso Crescer Tech. É o único dado de prática sancionatória sobre este desenho exacto |
| E-03 | Se há exigência de residência em Angola. Decide a opção de Luanda |

**Sem estas sete, D1 decide-se sobre premissa não verificada.** As outras quatro
P0 (A-04, B-01, B-02, C-06) bloqueiam dados reais ou pagamentos, não a região.

---

## 3. As 40 perguntas

### A — APD e Lei n.º 22/11, de 17 de Junho (12 perguntas)

#### A-01 · `E3` 1 — A KAMBÁ é subcontratada ou co-responsável, e quem notifica a APD?

- **Texto.** A KAMBÁ é **subcontratada** das PMEs ou **co-responsável** pelo
  tratamento (Lei 22/11, Arts. 5.º e 23.º)? Quem notifica ou pede autorização à
  APD: a plataforma, cada PME, ou ambas? Existe procedimento simplificado para
  plataformas multi-tenant?
- **Contexto.** Por defeito a KAMBÁ desenhou-se como subcontratada de cada PME,
  com contrato de subcontratação (DPA) como pré-condição do onboarding, e
  tornar-se-ia co-responsável nos tratamentos em que decide finalidades e meios
  (sinal de procura agregado, Kambá Score) —
  [`../../08_Seguranca_Conformidade.md`](../../08_Seguranca_Conformidade.md)
  §8.2. A distinção responsável/subcontratado do Art. 5.º é **CONFIRMADO**
  (texto em lex.ao); como a APD **qualifica plataformas SaaS** é
  **NÃO VERIFICADO** (`E3` §1). A obrigação do Art. 23.º — o subcontratado não
  comunica dados sem autorização — é **INDÍCIO** (resumo único).
- **Por que importa.** Decide **D9** (papel da KAMBÁ na Lei 22/11). Bloqueia
  **KAM-090** (ToS, DPA e aviso de privacidade versionados) e **KAM-069**
  (inventário de subprocessadores e gate de transferência com `apd_ref`), e é o
  primeiro pré-requisito do gate de go-live (`08` §8.6).
- **Opções propostas pela KAMBÁ.** (a) KAMBÁ subcontratada de cada PME, com
  DPA, e **cada PME** notifica a APD; (b) KAMBÁ subcontratada, mas notifica em
  nome das PMEs ao abrigo de mandato no DPA; (c) co-responsabilidade declarada
  apenas para os tratamentos de finalidade própria da KAMBÁ, que no Piloto ficam
  **desligados** (§4, item 2). Nenhuma destas é leitura jurídica da KAMBÁ
  *(a confirmar por parecer)*.
- **Resposta pedida.** Parecer escrito, com referência e data, citando os artigos
  verificados no DR, e indicando se existe prática da APD — publicada ou não —
  sobre plataformas SaaS multi-tenant.
- **Prioridade.** **P0** (critério 2 do KAM-104; `08` §13).
- **Prazo pedido.** Resposta preliminar até à **semana 3**; parecer escrito até à
  **semana 6**.

#### A-02 · `E3` 2 — Enviar texto ou áudio a um LLM no estrangeiro é transferência internacional, e a pseudonimização muda isso?

- **Texto.** Enviar texto ou áudio de utilizadores a APIs de LLM nos EUA e na UE
  é «transferência internacional» para efeitos dos Arts. 33.º e 34.º? Muda alguma
  coisa se os dados forem pseudonimizados ou tokenizados antes da chamada?
- **Contexto.** A KAMBÁ construiu um pipeline de minimização antes do LLM
  (detector de telefone, NIF, e-mail, morada e nomes → tokenização em
  `PESSOA_1`, `MORADA_1` → gate de destino → re-identificação só dentro da
  região aprovada), `08` §7.4. O próprio documento declara o limite: a
  minimização **reduz** a exposição mas **não prova** que deixou de haver
  transferência *(a confirmar por parecer)*; nomes próprios em texto livre e
  referências a locais escapam a regex. Que a chamada a um LLM constitua
  transferência é **INDÍCIO** (raciocínio jurídico reforçado pelo caso Crescer
  Tech); que o número de WhatsApp e o contexto possam identificar mesmo
  pseudonimizados é **INDÍCIO**.
- **Por que importa.** Decide **D1** (se alojar em Luanda dispensa alguma coisa:
  o desenho actual diz que **não** dispensa, porque LLM, STT e a própria Meta já
  são transferências) e contribui para **D9**. Bloqueia **KAM-069** e condiciona
  **KAM-112** (minimização de PII antes do LLM), já entregue, cujo valor
  jurídico depende desta resposta.
- **Opções propostas pela KAMBÁ.** (a) tratar toda a chamada a LLM como
  transferência, com `apd_ref` por destino e fail-closed sem autorização — é o
  que está construído; (b) tratar como transferência apenas as chamadas com
  conteúdo não tokenizado, mantendo as tokenizadas fora do regime; (c) transcrever
  e inferir dentro de destino já autorizado, reduzindo os destinos a um.
  A KAMBÁ assume (a) por precaução até haver parecer.
- **Resposta pedida.** Parecer escrito que diga (i) se há transferência, (ii) se
  a pseudonimização altera o enquadramento e sob que condições, e (iii) que prova
  a APD esperaria ver de que a minimização funciona.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### A-03 · `E3` 5 — Prazos da APD, silêncio positivo, taxas e formulários

- **Texto.** Qual o prazo realista para a notificação e para a autorização da
  APD? A partir de quando se pode começar a tratar — há silêncio positivo? Quais
  as taxas (Decreto Presidencial 60/21) e quais os formulários aplicáveis?
- **Contexto.** A obrigação de notificação ou autorização prévia (Arts. 35.º a
  37.º) é **CONFIRMADO**; os prazos — 30 dias de resposta à notificação — são
  **INDÍCIO** (leitura única). As taxas de 4.315 a 350.450 Kz vêm de imprensa de
  2021 (**INDÍCIO**). Existe um formulário publicado pela APD que pede
  entidades e países de destino (**INDÍCIO**, excerto). Prazos e silêncio
  positivo estão como **NÃO VERIFICADOS** em `08` §8.6.
- **Por que importa.** Decide **D1**: se o procedimento junto da APD levar mais
  tempo do que o calendário do Piloto, a decisão de alojamento muda de forma
  (ou os dados reais esperam). Bloqueia **KAM-105** e **KAM-069**.
- **Opções propostas pela KAMBÁ.** (a) submeter notificação e, onde o destino
  não seja adequado, autorização, antes de qualquer dado real, aceitando o prazo
  que vier; (b) submeter em duas vagas — primeiro o conjunto mínimo que permite
  o Piloto, depois o resto; (c) correr o Piloto só com dados sintéticos até a
  autorização chegar. (c) é o que está assumido hoje (§4, item 12).
- **Resposta pedida.** Parecer escrito com o prazo legal e o prazo observado na
  prática, a resposta sobre silêncio positivo, a tabela de taxas aplicável a este
  caso e a lista dos formulários a submeter.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### A-04 · `E3` 6 — Compras de farmácia e histórico de conversa: regime de dados sensíveis?

- **Texto.** Dados de «saúde» obtidos por compras de produtos de farmácia, e
  «vida privada» inferida do histórico de conversa, ficam sujeitos ao regime de
  dados sensíveis (Art. 13.º)? Que autorização é necessária?
- **Contexto.** A lista de dados sensíveis do Art. 5.º c) — convicções
  filosóficas ou políticas, filiação, fé religiosa, **vida privada**, origem
  racial ou étnica, **saúde** e vida sexual — é **CONFIRMADO** (portal). Que o
  tratamento de sensíveis exija disposição legal ou autorização da APD (Art. 13.º)
  é **CONFIRMADO** (resumo). Que «saúde» apanhe compras de produtos de farmácia e
  que «vida privada» seja vago o bastante para alargar é **inferência** da KAMBÁ
  (`E3` §1). Biometria e voz não constam da lista citada: **NÃO VERIFICADO**.
- **Por que importa.** O desenho actual bloqueia por precaução: ao detectar
  saúde, religião, política ou vida sexual, **não persiste nem envia ao LLM** e
  responde neutro com handoff, até haver autorização da APD (`08` §7.5). Bloqueia
  **KAM-033** (guardrails de entrada e saída) e **KAM-088** (screening de
  categorias) na parte que depende de saber se o bloqueio pode ser levantado.
- **Opções propostas pela KAMBÁ.** (a) manter medicamentos, dispositivos médicos
  e saúde fora do Piloto e o classificador a bloquear — é o que está assumido
  (§4, itens 9 e 10); (b) pedir autorização à APD para a categoria «saúde» e abrir
  só depois; (c) tratar o histórico de conversa como não sensível por defeito,
  bloqueando apenas marcadores explícitos. A KAMBÁ **não** assume (c).
- **Resposta pedida.** Parecer escrito que delimite «saúde» e «vida privada»
  para este caso de uso, e diga que autorização é exigível e com que
  fundamentação.
- **Prioridade.** **P0**.
- **Prazo pedido.** Parecer escrito até à **semana 6**.

#### A-05 · `E3` 7 — A Circular 02 da APD aplica-se a quem, e qual o prazo de notificação de violações?

- **Texto.** A **Circular 02 da APD** (comunicação obrigatória de incidentes
  informáticos) aplica-se a que entidades? Qual o prazo de notificação de
  violações de dados, e a quem — APD, titulares, ambos?
- **Contexto.** Há contradição nas fontes: uma consultora (2021) diz que a Lei
  22/11 **não** obriga à notificação de violações para responsáveis em geral, só
  para prestadores de comunicações electrónicas (**INDÍCIO**); o sítio da APD
  lista uma «Circular 02 — comunicação obrigatória de incidentes informáticos» e
  a imprensa de 2026 refere multas por «não notificação de violações». O estado
  registado é **INDÍCIO contraditório** (`E3` §1, `08` §8.1). O alvo de 72 horas
  que a KAMBÁ assume vem do projecto de revisão de 2025 (**INDÍCIO**) e de boa
  prática, não de lei em vigor.
- **Por que importa.** Fixa o prazo do runbook de incidentes (`08` §10) e a
  cláusula de notificação às PMEs do DPA. Bloqueia **KAM-083** (runbooks) na
  parte do prazo.
- **Opções propostas pela KAMBÁ.** (a) assumir a obrigação e o alvo de 72 horas
  à APD e aos titulares, com notificação às PMEs em ≤ 24 horas — é o que está
  desenhado; (b) notificar só as PMEs, deixando a notificação à APD a cargo de
  cada responsável; (c) esperar pela lei nova.
- **Resposta pedida.** Parecer escrito com o âmbito subjectivo da Circular 02, o
  prazo aplicável e quem tem o dever quando a KAMBÁ é subcontratada.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### A-06 · `E3` 8 — Coimas do Art. 51.º: montantes e cumulação

- **Texto.** Confirmar os montantes do Art. 51.º — alínea a) USD 75.000 a
  150.000, alínea b) USD 65.000 a 130.000, agravadas ao triplo para pessoas
  colectivas — e se existem tectos cumulativos. Houve alterações posteriores?
- **Contexto.** Os montantes são **CONFIRMADO** por duas leituras independentes
  do texto (lex.ao e angolex); um resultado de pesquisa citava «USD 7.000 a
  15.000» para falta de notificação, sem fonte aberta, e está registado como
  **NÃO VERIFICADO / contraditório**. As multas efectivas conhecidas excedem o
  triplo de uma única alínea (Crescer Tech, USD 505.000), o que sugere soma de
  infracções — **inferência**, não facto. «Verificar no DR.»
- **Por que importa.** Calibra o risco registado em `08` §15 e a decisão sobre
  quanto se investe em antecipar a conformidade. Não bloqueia ticket.
- **Opções propostas pela KAMBÁ.** Nenhuma: é pedido de confirmação de texto
  legal, não escolha de desenho.
- **Resposta pedida.** Parecer escrito com a redacção verificada no DR, os
  montantes em vigor, a regra de agravamento e a existência ou não de tecto
  cumulativo.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### A-07 · `E3` 9 — Marketing no WhatsApp: Art. 19.º e Instrutivo INACOM 4/20

- **Texto.** O Art. 19.º da Lei 22/11 e o **Instrutivo INACOM n.º 4/20** (21 de
  Fevereiro de 2020) aplicam-se a mensagens enviadas via WhatsApp Business?
  Basta opt-in electrónico (clique ou resposta), ou exige-se «consentimento
  escrito»?
- **Contexto.** O Art. 19.º — consentimento explícito, com excepções para
  representantes de empresas, administração pública e clientes com transacção
  anterior, sempre com opt-out — é **CONFIRMADO**. O Instrutivo INACOM 4/20 é
  **INDÍCIO** (resumo único), e o seu âmbito são operadores de comunicações
  electrónicas, com a expressão «e outras aplicações semelhantes»: a aplicação
  directa a uma plataforma e ao WhatsApp **não está clara**. A KAMBÁ aplica hoje
  o mais exigente: opt-in separado e registado, «PARAR» em cada mensagem
  promocional e lista de supressão global (`08` §8.4).
- **Por que importa.** Fixa a base legal da finalidade `marketing` do
  `consent_event` — a única das dez finalidades do dicionário com fonte directa
  e CONFIRMADA — e a validade da excepção de transacção anterior. Bloqueia
  **KAM-022** (consentimento no 1.º contacto) e **KAM-090** na parte do texto do
  aviso.
- **Opções propostas pela KAMBÁ.** (a) opt-in electrónico separado por
  finalidade, registado com texto, versão e hora, tratado como «escrito» —
  é o que está construído; (b) exigir confirmação em duas etapas para marketing;
  (c) não usar a excepção de transacção anterior, exigindo opt-in sempre.
- **Resposta pedida.** Parecer escrito sobre o âmbito do Instrutivo, a forma
  exigível do consentimento e a validade da excepção do Art. 19.º neste canal.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### A-08 · `E3` 10 — Idade mínima para consentir e para contratar por chat

- **Texto.** Existe **idade mínima** para consentir no tratamento de dados e
  para contratar sozinho por chat? Como tratar menores, quanto a dados e quanto
  a compras?
- **Contexto.** **NÃO VERIFICADO**: a investigação não encontrou regra de idade
  na Lei 22/11 nem regime de capacidade aplicável a este canal (`E3` §1 e §4). O
  que existe é verificação de 18 anos para álcool e tabaco, com o nível de prova
  exigido também **NÃO VERIFICADO** (`E3` req. 21).
- **Por que importa.** Condiciona o desenho do consentimento no primeiro contacto
  e o screening. Bloqueia **KAM-022** e **KAM-088** na parte da verificação de
  idade.
- **Opções propostas pela KAMBÁ.** (a) não pedir idade e não vender categorias
  restritas no Piloto, que é o estado actual; (b) declaração de idade
  auto-reportada para categorias restritas; (c) prova documental, que a KAMBÁ
  considera inviável no canal.
- **Resposta pedida.** Parecer escrito com a idade aplicável, o regime de
  representação de menores e o nível de prova exigível.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### A-09 · `E3` 17 — Estado do projecto de revisão da Lei 22/11 e da Lei da IA

- **Texto.** Qual o estado, em Outubro de 2026, do **projecto de revisão da Lei
  22/11** e do **projecto de Lei da Inteligência Artificial**? Calendário,
  período transitório e alcance extraterritorial. Que partes devem ser
  antecipadas?
- **Contexto.** A consulta pública do projecto de revisão da Lei 22/11 (17 de
  Março a 17 de Abril de 2025) é **CONFIRMADO** quanto à existência; a aprovação
  é **NÃO VERIFICADO**. O conteúdo do projecto — decisões de adequação,
  cláusulas-tipo, DPO, notificação em 72 horas, limites a decisões
  exclusivamente automatizadas — é **INDÍCIO** (leitura única de texto não
  vigente). O projecto de Lei da IA do MINTTICS, em consulta pública desde
  Setembro de 2025, é **INDÍCIO** (duas fontes secundárias, sem o texto); a
  aprovação é **NÃO VERIFICADO**. A Lei da Cibersegurança foi aprovada na
  generalidade em Janeiro de 2026 (**CONFIRMADO**) e o debate nas comissões foi
  suspenso em Julho de 2026 (**INDÍCIO**); não está em vigor.
- **Por que importa.** Decide quanto do desenho se faz hoje contra a lei nova
  para evitar refactor: DPO, 72 horas, cláusulas-tipo, divulgação de IA e
  supervisão humana. Não bloqueia ticket.
- **Opções propostas pela KAMBÁ.** (a) desenhar já para o projecto onde o custo
  é baixo — divulgação de que é assistente automático, handoff humano, nenhuma
  decisão com efeito legal ou financeiro tomada só pelo LLM (`E3` req. 15) — e
  esperar pelo resto; (b) esperar pela lei; (c) antecipar tudo.
- **Resposta pedida.** Parecer escrito com o estado processual de cada projecto,
  o calendário previsível e as obrigações que já convém antecipar.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### A-10 · `E3` 19 — Valor probatório do contrato por chat e assinatura electrónica

- **Texto.** Qual o valor probatório de um contrato celebrado por conversa de
  chat (Lei 23/11, Art. 28.º) e qual o regime de assinatura electrónica
  aplicável? Que registos deve a KAMBÁ guardar para provar o consentimento e a
  contratação?
- **Contexto.** O Art. 28.º n.º 1 da Lei 23/11 — validade dos contratos
  celebrados por via electrónica e equiparação das assinaturas electrónicas «nos
  casos da lei aplicável» — é **CONFIRMADO** (leitura do texto no angolex). O
  regime de assinatura electrónica qualificada é **NÃO VERIFICADO**. A Lei 23/11
  é quase silenciosa sobre formação do contrato, confirmação de encomenda e
  responsabilidade de intermediários. A KAMBÁ guarda hoje as mensagens
  relevantes à formação do contrato com hash e carimbo temporal
  (`contract_evidence`, `08` §8.11).
- **Por que importa.** Fixa o que a `contract_evidence` tem de conter para
  servir de prova, e o prazo pelo qual se guarda. Bloqueia **KAM-090** na parte
  do aceite contratual versionado.
- **Opções propostas pela KAMBÁ.** (a) registo imutável com hash, carimbo
  temporal e versão do texto aceite, guardado pelo prazo da relação mais
  prescrição — é o que está desenhado, com o prazo «a confirmar»; (b) acrescentar
  confirmação explícita por botão em cada contratação; (c) exigir assinatura
  electrónica qualificada, que a KAMBÁ considera inviável no canal.
- **Resposta pedida.** Parecer escrito sobre o valor probatório, o conjunto
  mínimo de registos e o prazo de conservação para prova.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### A-11 · `E3` 20 — A Meta como destinatário: exige notificação separada?

- **Texto.** Qual o direito de uso do número de telefone obtido através da
  WhatsApp Business API (Meta) como dado pessoal? A Meta é também destinatário
  ou subcontratado no estrangeiro? Isso exige **notificação separada** à APD?
- **Contexto.** No inventário de subprocessadores da KAMBÁ a Meta aparece como
  canal, com conteúdo e telefone ou BSUID, destino EUA/UE **NÃO VERIFICADO**, e
  o estado do procedimento é literalmente «perguntar se exige notificação
  separada» (`08` §8.3.2). O desenho já não usa o telefone como chave primária —
  usa o BSUID, e o telefone pode deixar de vir nos webhooks (`E1` §0, ponto 8,
  **CONFIRMADO**). A obrigação de informar o titular dos destinatários é
  **INDÍCIO** (Art. 18.º, Art. 25.º).
- **Por que importa.** Decide **D1** e **D9**: define o perímetro da submissão à
  APD. Se a Meta exige notificação separada, o procedimento de alojamento não a
  cobre. Bloqueia **KAM-069** e **KAM-105**.
- **Opções propostas pela KAMBÁ.** (a) incluir a Meta no mapa de transferências
  da submissão, como destinatário próprio, com notificação separada se exigida;
  (b) tratar a Meta como canal e não como subprocessador, por o tratamento ser
  anterior à entrada dos dados na plataforma; (c) ambas, com a decisão pelo
  parecer. A KAMBÁ assume (a) por precaução.
- **Resposta pedida.** Parecer escrito que qualifique a Meta neste caso, diga se
  há notificação separada, e indique o que o aviso de privacidade tem de
  declarar sobre ela.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### A-12 · `08` §13 N3 — A pseudonimização por HMAC com pepper retido pela KAMBÁ deixa de ser «dado pessoal» para a PME?

- **Texto.** A pseudonimização por HMAC-SHA256 do número de telefone, com o
  *pepper* retido exclusivamente pela KAMBÁ e nunca partilhado com a PME, faz com
  que o valor resultante deixe de ser «dado pessoal» na esfera da PME? E na
  esfera da KAMBÁ?
- **Contexto.** A KAMBÁ calcula `contact_hmac = HMAC-SHA256(pepper_kid, E.164)`
  e declara o limite por escrito: **o espaço de números móveis angolanos é
  pequeno (da ordem de 10^8), pelo que um HMAC de telefone sem segredo, ou com o
  segredo comprometido, é reversível por enumeração**; o *pepper* vive no cofre,
  tem identificador de chave e rotação anual, e o resultado é
  **pseudonimização, não anonimização** — continua dado pessoal
  *(a confirmar por parecer)*, `08` §7.2. A linha «continua dado pessoal (Lei
  22/11)» da tabela de §7.2 traz exactamente essa marca.
- **Por que importa.** Decide se os agregados e as `assistant_queries`
  pseudonimizadas podem ser tratados pela KAMBÁ com finalidade própria sem o
  consentimento que hoje se exige, e o que a PME tem de poder exercer.
  Contribui para **D9**. Bloqueia **KAM-070** (direitos do titular) e condiciona
  **KAM-112**.
- **Opções propostas pela KAMBÁ.** (a) tratar o HMAC como dado pessoal em todas
  as esferas, que é o que está assumido; (b) tratar como dado pessoal na esfera
  da KAMBÁ e não na da PME, por esta não ter o *pepper*; (c) só agregados com
  limiar mínimo de contagem saem do regime — é o que está previsto para o
  Diferido.
- **Resposta pedida.** Parecer escrito que diga, para cada esfera, se há dado
  pessoal, e que condições tornariam o resultado anonimizado «por meios
  razoáveis».
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

### B — BNA e Aviso n.º 2/22 (8 perguntas)

> As perguntas B-01 a B-07 vêm de
> [`../E2_Pagamentos_Angola.md`](../E2_Pagamentos_Angola.md) §9, cuja epígrafe
> diz que **só o BNA pode responder por escrito**. O que se pede ao advogado é
> duplo: (i) o seu próprio parecer sobre o enquadramento, e (ii) a minuta do
> pedido de consulta escrita ao Departamento de Sistema de Pagamentos do BNA, e
> o acompanhamento dela. Está dito no campo «resposta pedida» de cada uma.

#### B-01 · `E2` 19 — O desenho A cabe na exclusão técnica do Art. 4.º j)?

- **Texto.** Uma plataforma de software que gera pedidos de pagamento com as
  credenciais de **cada comerciante**, e cuja liquidação é feita directamente
  pela EMIS para a conta do comerciante, está excluída por força da alínea j) do
  art. 4.º do Aviso 2/22 — prestador técnico sem posse dos fundos? E se também
  mostrar uma referência ou um código QR sem iniciar a transferência?
- **Contexto.** O texto da exclusão é **CONFIRMADO** (leitura directa em
  lex.ao): não são serviços de pagamento os «serviços prestados por prestadores
  de serviços técnicos, que apoiam a prestação de serviços de pagamento **sem
  nunca entrarem na posse dos fundos a transferir**», incluindo processamento e
  armazenamento de dados, autenticação, redes TIC e terminais, **com excepção
  dos serviços de iniciação de pagamentos e de informação sobre contas**. A
  conclusão de que o desenho da KAMBÁ cabe nessa exclusão é **INDÍCIO até
  parecer** — é o que `E2` §3.3 diz expressamente da linha «A. Facilitador
  técnico». A definição de sub-adquirente do art. 3.º aa) é **CONFIRMADO**.
- **Por que importa.** Decide **D8** (enquadramento BNA do modelo facilitador e
  das comissões). É a premissa sobre a qual está desenhado todo o subsistema de
  pagamentos: **ADR-004**, «a plataforma nunca detém fundos». Bloqueia
  **KAM-056** e **KAM-055**. Sem parecer, a comissão sobre transacção fica
  desligada (ADR-017, §4 item 1).
- **Opções propostas pela KAMBÁ.** Só uma está em construção: o **desenho A**,
  facilitador técnico com credenciais do comerciante e liquidação directa. Os
  desenhos B (plataforma como comerciante único, a receber e repassar), C
  (payouts executados pela plataforma) e D (escrow) estão **fora** do Piloto
  precisamente por causa desta dúvida, com barreira técnica em cada um
  (`08` §8.10; §4 itens 3 a 6).
- **Resposta pedida.** Parecer escrito do advogado **e** minuta de pedido de
  interpretação escrita ao Departamento de Sistema de Pagamentos do BNA, com a
  descrição do desenho A tal como está no
  [`Anexo_Factos_do_Caso.md`](Anexo_Factos_do_Caso.md) §7.
- **Prioridade.** **P0** (critério 2 do KAM-104: «BNA Q19–Q20 e Q30 propostos P0»).
- **Prazo pedido.** Parecer escrito até à **semana 6**.

#### B-02 · `E2` 20 — Quando o bot acciona o pagamento, qual a classificação e a licença?

- **Texto.** Quando o bot acciona um pagamento a partir da conta do cliente
  (iniciação), qual é a classificação e qual a licença necessária?
- **Contexto.** A definição de iniciação de pagamento do Aviso 2/22 — serviço que
  inicia uma ordem de pagamento a pedido do utilizador relativamente a uma conta
  detida noutro prestador — é **CONFIRMADO** (art. 3.º); que a categoria exija
  autorização própria é **CONFIRMADO**, e o capital exigido é **INDÍCIO**
  (valores anteriores ao Aviso 5/23). A leitura de que apresentar referência ou
  QR, sendo o cliente a pagar na sua aplicação, **não** é iniciação, é
  **interpretação** da KAMBÁ e está marcada como tal em `E2` §3.2.
- **Por que importa.** Decide **D8**. O desenho actual proíbe explicitamente
  accionar pagamento a partir da conta do cliente: «o cliente paga na sua app
  (referência, Express push); o bot nunca recebe credenciais» (`08` §8.10, §4
  item 6). Bloqueia **KAM-056**.
- **Opções propostas pela KAMBÁ.** (a) nunca iniciar — apresentar referência ou
  QR e deixar o pagamento ao cliente, que é o que está construído; (b) iniciar
  através de parceiro licenciado, com o parceiro a figurar como prestador; (c) a
  KAMBÁ obter licença de iniciação, fora do Piloto.
- **Resposta pedida.** Parecer escrito que delimite a fronteira entre
  «apresentar» e «iniciar», e minuta de consulta ao BNA sobre essa fronteira.
- **Prioridade.** **P0**.
- **Prazo pedido.** Parecer escrito até à **semana 6**.

#### B-03 · `E2` 21 — Payouts executados por parceiro licenciado mas instruídos pela plataforma

- **Texto.** Payouts a estafetas e revendedores executados por parceiro
  licenciado, mas **instruídos** pela plataforma, exigem licença à plataforma?
- **Contexto.** Executar operações de pagamento ou remessa é actividade regulada
  (**CONFIRMADO**, art. 4.º). Que a instrução sem execução fique fora é
  **INDÍCIO** (`E2` §3.3, desenho C). O art. 21.º do Aviso 2/22 — «é proibida a
  subcontratação de serviços operacionais para a prestação de serviços de
  pagamento» — é **CONFIRMADO**, e a sua leitura como obstáculo a operar «ao
  abrigo» da licença de um parceiro é **interpretação** da KAMBÁ.
- **Por que importa.** Decide **D8** na parte dos payouts. Hoje
  `PaymentProvider.payout` está **sem implementação nem rota**, com bandeira
  fail-closed e um teste de CI que falha se aparecer implementação (`08` §8.10,
  §4 item 3). Não bloqueia ticket do Piloto; é Clusters.
- **Opções propostas pela KAMBÁ.** (a) o comerciante paga os seus estafetas a
  partir da sua conta, com a plataforma a gerar apenas a lista — opção preferida;
  (b) parceiro licenciado executa com a conta do comerciante, via API do
  parceiro; (c) a KAMBÁ obtém licença.
- **Resposta pedida.** Parecer escrito sobre (a) e (b) face ao art. 21.º, e
  minuta de consulta ao BNA.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### B-04 · `E2` 22 — Retenção de fundos até confirmação de entrega

- **Texto.** A retenção de fundos até à confirmação de entrega (escrow) só é
  possível através de prestador de serviços de pagamento ou de instituição de
  moeda electrónica com conta fiduciária?
- **Contexto.** As regras de protecção de fundos — contas fiduciárias,
  segregação, reconciliação diária — aplicam-se a **emitentes de moeda
  electrónica** (**CONFIRMADO**, arts. 25.º a 28.º). No texto lido **não existe
  figura geral de escrow para marketplace** fora dessas regras, e o regime
  específico é **NÃO VERIFICADO** (`E2` §3.2).
- **Por que importa.** Decide **D8**. Hoje não existe estado «retido» no
  desenho, e a disputa de entrega é tratada fora do gateway (`08` §8.10, §4 item
  4). Não bloqueia ticket do Piloto.
- **Opções propostas pela KAMBÁ.** (a) não haver escrow, com a disputa tratada
  fora do gateway — o estado actual; (b) escrow através de parceiro licenciado,
  com os fundos detidos pelo parceiro em nome do cliente; (c) pagamento contra
  entrega, sem retenção.
- **Resposta pedida.** Parecer escrito e minuta de consulta ao BNA.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### B-05 · `E2` 23 — Capital social e fundos próprios do art. 18.º depois do Aviso 5/23

- **Texto.** Quais os valores actuais de capital social e de fundos próprios das
  categorias do art. 18.º, depois do Aviso n.º 5/23?
- **Contexto.** Os valores **anteriores** ao Aviso 5/23 vêm de imprensa
  (**INDÍCIO**): principal 70 milhões de Kz; standard classe 1, 40 milhões;
  classe 2, 25 milhões; iniciação de pagamento 25 milhões; informação sobre
  contas 20 milhões; remessa 70 milhões. Os valores **actuais** são
  **NÃO VERIFICADO** (`E2` §3.1).
- **Por que importa.** Só importa se alguma das respostas anteriores obrigar a
  KAMBÁ a pedir licença; é o que torna essa hipótese orçamentável. Decide **D8**
  na parte do custo. Não bloqueia ticket.
- **Opções propostas pela KAMBÁ.** Nenhuma: é pedido de dado regulatório.
- **Resposta pedida.** Parecer escrito com os valores em vigor e a fonte, e os
  requisitos de governação e de prevenção do branqueamento que os acompanham
  (Aviso 2/24).
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### B-06 · `E2` 24 — Regime actual dos agentes de prestadores de serviços de pagamento

- **Texto.** Qual o regime actual de agentes de prestadores de serviços de
  pagamento — registo no BNA, art. 17.º da Lei 40/20 — depois da revogação do
  Aviso 7/17?
- **Contexto.** O Aviso 7/17, que admitia agentes de serviços de pagamento
  móveis e contas fiduciárias, foi **revogado** pelo Aviso 2/22 (**CONFIRMADO**,
  art. 42.º). O registo de agentes no art. 17.º da Lei 40/20 é **CONFIRMADO**
  (resumo). Que o Aviso 2/22 não defina «agente» de forma explícita é
  **NÃO VERIFICADO** — vem de um resumo. A conclusão de `E2` §3.3 é que uma
  empresa não é «agente» apenas por ter contrato comercial com um prestador, sem
  registo; está marcada **NÃO VERIFICADO**.
- **Por que importa.** Fecha a única via que poderia permitir à KAMBÁ operar sob
  licença de terceiro sem licença própria. Decide **D8** na parte da estrutura
  de parceria. Não bloqueia ticket.
- **Opções propostas pela KAMBÁ.** (a) não recorrer à figura de agente —
  o estado actual; (b) registo como agente de um prestador, se o regime o
  permitir.
- **Resposta pedida.** Parecer escrito com o regime em vigor e, se existir, o
  procedimento de registo.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### B-07 · `E2` 25 — Existe sandbox regulatório ou procedimento de consulta prévia?

- **Texto.** Existe sandbox regulatório ou procedimento formal de consulta
  prévia junto do BNA?
- **Contexto.** **INDÍCIO** (artigo de escritório de advogados): há ambiguidade
  doutrinal sobre quais entidades precisam de licença de instituição de
  pagamento, e **não existe sandbox regulatório de pagamentos**. A recomendação
  registada em `E2` §3.4 é pedir interpretação escrita ao Departamento de
  Sistema de Pagamentos.
- **Por que importa.** É o **instrumento** de que B-01 e B-02 dependem: sem
  procedimento, o parecer do advogado é o que a KAMBÁ tem. Decide **D8** na
  parte do caminho a seguir. Não bloqueia ticket, mas condiciona o prazo das
  outras respostas do bloco B.
- **Opções propostas pela KAMBÁ.** (a) pedido de interpretação escrita ao
  Departamento de Sistema de Pagamentos, acompanhado pelo advogado — preferida;
  (b) basear-se apenas no parecer do advogado e registar o risco; (c) esperar por
  alteração do quadro regulatório.
- **Resposta pedida.** Parecer escrito que diga qual o procedimento existente, o
  prazo esperado e a forma do pedido; e a minuta.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### B-08 · `08` §13 N5 — Confirmação de que a estrutura de pagamento do desenho A está fora do âmbito do Aviso 2/22

- **Texto.** A estrutura de pagamento do **desenho A** — credenciais do
  comerciante, liquidação directa pela EMIS na conta do comerciante, plataforma
  sem posse de fundos em nenhum momento, sem saldos, sem escrow, sem payouts e
  sem iniciação — está, no seu conjunto, fora do âmbito do Aviso 2/22 por força
  do art. 4.º j)?
- **Contexto.** Esta é a forma **agregada** da pergunta que B-01 e B-02 fazem por
  partes, e é a que está inscrita em `08` §13 como linha N5, remetendo para
  `E2` Q19 a Q22. Existe porque o desenho não é uma função isolada mas um
  conjunto de seis proibições com barreira técnica (`08` §8.10), e a KAMBÁ
  precisa de saber se o **conjunto** se qualifica, não só cada peça.
- **Por que importa.** Decide **D8** na forma em que ele está escrito na Carta.
  Bloqueia **KAM-056**. É a resposta que a KAMBÁ arquiva como fundamento de
  **ADR-004**.
- **Opções propostas pela KAMBÁ.** Nenhuma alternativa: é pedido de confirmação
  do conjunto. A alternativa a um «não» é pedir licença ou mudar o desenho, e
  nenhuma das duas é decisão desta sessão.
- **Resposta pedida.** Parecer escrito que se pronuncie sobre o conjunto, e não
  só sobre cada função, e que identifique qual das seis barreiras técnicas é a
  que sustenta a qualificação — porque é a que a KAMBÁ não pode remover.
- **Prioridade.** **P1** pela letra do critério 2; ver §5, divergência 2.
- **Prazo pedido.** Pede-se que **viaje com as P0 do bloco B** (semana 6), por
  ser a sua forma agregada; ver §5.

### C — AGT e factura (6 perguntas)

#### C-01 · `E2` 26 — Qual a data em vigor da obrigação de facturação electrónica?

- **Texto.** Qual a data de entrada em vigor da obrigação de facturação
  electrónica para os regimes **geral** e **simplificado** do IVA — 21 de
  Setembro de 2026 ou 1 de Janeiro de 2027 — e qual o texto do diploma que fixa
  essa data?
- **Contexto.** Há **conflito de fontes**, registado como tal: fontes de 2025
  (consultora, imprensa) dão 21 de Setembro de 2026; fontes posteriores ao
  adiamento dão 1 de Janeiro de 2027 (**INDÍCIO forte**: imprensa de 2026 e
  declaração do presidente da AGT de que «o prazo não será prorrogado», sem
  diploma de 2026 lido). A fase 1 — grandes contribuintes e fornecedores do
  Estado desde 1 de Janeiro de 2026 — é **CONFIRMADO**. A data de 21 de Setembro
  de 2026 já passou: se estivesse em vigor, as PMEs-alvo já seriam obrigadas
  hoje.
- **Por que importa.** Decide **D7** (parceiro de factura AGT), hoje
  **CONDICIONAL** com gatilho «confirmação escrita da AGT sobre 2027». Não
  bloqueia ticket do Piloto — a KAMBÁ não emite facturas — mas fixa quando a
  integração passa a ser requisito.
- **Opções propostas pela KAMBÁ.** (a) tratar 1 de Janeiro de 2027 como a data
  oficial e as PMEs como «já em risco» — plano prudente actual; (b) assumir que a
  obrigação já vigora e integrar imediatamente; (c) esperar pela confirmação.
- **Resposta pedida.** Parecer escrito com a data em vigor e a citação do
  diploma, e minuta de pedido de confirmação escrita à AGT.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### C-02 · `E2` 27 — Softwares certificados e chamada por API em nome de várias empresas

- **Texto.** Qual a lista oficial actual de softwares certificados pela AGT, e
  pode um software certificado ser chamado por **API por terceiros em nome de
  várias empresas** (multi-tenant)?
- **Contexto.** Que o software tenha de ser validado ou disponibilizado pela AGT
  é **CONFIRMADO** (Decreto Presidencial 71/25, art. 17.º segundo resumo do
  texto). Que a AGT tenha certificado um conjunto de sistemas é **CONFIRMADO**
  (imprensa). Se a chamada por API por terceiros em nome de várias empresas é
  admissível é **NÃO VERIFICADO** — é exactamente o que a pergunta pede.
- **Por que importa.** Decide **D7** e a forma da integração: se a resposta for
  negativa, a KAMBÁ não pode orquestrar a emissão em nome das PMEs e fica
  limitada a arquivar o documento que o software da PME emitiu. Não bloqueia
  ticket do Piloto.
- **Opções propostas pela KAMBÁ.** (a) integrar com software certificado da PME,
  chamado em nome dela, com mandato contratual; (b) apenas arquivar facturas
  emitidas pelo software da PME, sem as orquestrar; (c) exportar as encomendas
  para que a PME as importe. A KAMBÁ assume que **não emite** facturas próprias
  (§4 item 7).
- **Resposta pedida.** Parecer escrito e minuta de pedido à AGT, com a lista
  oficial em vigor.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### C-03 · `E2` 28 — Certificar software próprio: processo, custo e prazo

- **Texto.** Qual o processo, o custo e o prazo para certificar software próprio
  junto da AGT? E qual o documento técnico do Decreto Executivo n.º 683/25 —
  esquemas e pontos de comunicação em tempo real?
- **Contexto.** O Decreto Executivo n.º 683/25, de 22 de Agosto, que fixa a
  estrutura de dados do software e o modelo da facturação electrónica, é
  **CONFIRMADO** (múltiplas fontes); o seu conteúdo técnico não foi lido. Os
  custos de software de facturação referidos pela imprensa — de 500 mil a 1,5
  milhões de Kz para pequenas empresas — são **INDÍCIO**, e são custos de compra,
  não de certificação.
- **Por que importa.** Só importa se a KAMBÁ vier a precisar de certificar
  software próprio, o que hoje está excluído. Decide **D7** na parte do custo.
  Não bloqueia ticket.
- **Opções propostas pela KAMBÁ.** (a) não certificar e integrar com terceiros —
  o estado actual; (b) certificar software próprio, fora do Piloto.
- **Resposta pedida.** Parecer escrito com processo, custo e prazo, e o
  documento técnico ou a forma de o obter.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### C-04 · `E2` 29 — Registo de estabelecimentos, recibos de pagamentos online e regime de exclusão

- **Texto.** Existe obrigação de registo de estabelecimentos junto da AGT? Como
  se tratam os **recibos** de pagamentos online? E confirmar, no regime de
  exclusão, o limite de 300 documentos por ano emitidos no Portal do
  Contribuinte.
- **Contexto.** As exigências do software — comunicação em tempo real, assinatura
  digital, código de validação, geração de SAF-T e registo de cada
  estabelecimento junto da AGT — são **CONFIRMADO** (AGT e imprensa). Que
  contribuintes em regime de exclusão e pessoas singulares possam emitir pelo
  Portal do Contribuinte com o máximo de 300 documentos por ano é **INDÍCIO**
  (resultado de pesquisa). Que o Decreto 71/25 art. 6.º exija recibo em
  pagamentos parciais ou totais, salvo factura-recibo, é **INDÍCIO** (resumo).
- **Por que importa.** Decide **D7** na parte operacional e determina se as
  micro-PMEs do Piloto podem funcionar sem software certificado. Não bloqueia
  ticket.
- **Opções propostas pela KAMBÁ.** (a) factura-recibo emitida pelo software da
  PME após cada pagamento confirmado, de forma assíncrona — o desenho actual;
  (b) recibo separado; (c) para micro-PMEs em regime de exclusão, emissão manual
  no Portal, sem integração.
- **Resposta pedida.** Parecer escrito com as três respostas e a confirmação do
  limite.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### C-05 · `E3` 15 — Prazo de conservação do Código Geral Tributário e calendário das PMEs pequenas

- **Texto.** Qual o prazo exacto de conservação de facturas e encomendas que
  resulta do **Código Geral Tributário**? Qual o calendário de facturação
  electrónica para as PMEs pequenas? E o facto de a plataforma emitir ou
  transmitir documentos obriga a validação pela AGT?
- **Contexto.** O Decreto 71/25 e o 292/18 remetem para «os prazos do Código
  Geral Tributário», e o **número de anos é NÃO VERIFICADO** — um excerto citava
  10 anos do BNA para imagens digitalizadas, que é outro regime (`E3` §6). Em
  consequência, o parâmetro `fiscal_retention_years` da KAMBÁ está **sem valor
  por defeito que apague** e, até confirmação, não se eliminam registos fiscais
  (`08` §8.8, §4 item 8). Existe **tensão declarada** com a minimização da Lei
  22/11: os dados fiscais ficam em tabelas separadas, só com o que a lei fiscal
  exige, fora do histórico de conversa.
- **Por que importa.** É o único número em falta para que a política de retenção
  feche: hoje a KAMBÁ não consegue apagar o que a lei fiscal talvez já não exija
  guardar, nem guardar com fundamento o que guarda. Bloqueia **KAM-070**
  (direitos do titular, na parte da eliminação). Decide **D7**.
- **Opções propostas pela KAMBÁ.** (a) parâmetro por tenant, com o valor que o
  parecer fixar, e nenhuma eliminação fiscal até lá — o estado actual; (b) adoptar
  o prazo mais longo de que haja notícia, por precaução; (c) eliminar ao prazo da
  Lei 22/11 e assumir o risco fiscal. A KAMBÁ **não** assume (c).
- **Resposta pedida.** Parecer escrito com o número de anos e o artigo que o
  fixa, verificado no DR.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### C-06 · `E2` 30 — IVA da assinatura, retenções a não residentes e câmbio para pagar em USD

- **Texto.** Qual o tratamento de IVA sobre a assinatura de software como
  serviço (o nosso regime, nas vendas a empresas e a consumidores)? Que
  retenções ou impostos incidem sobre pagamentos a **fornecedores não
  residentes** (Meta, cloud, inteligência artificial)? E qual o regime cambial
  para pagar em USD?
- **Contexto.** As taxas e regimes de IVA — geral 14%, simplificado 7% sobre o
  valor recebido, regime de exclusão abaixo de 25 milhões de Kz — são
  **INDÍCIO** (consultoras; o Código do IVA não foi lido). Que serviços digitais
  estejam sujeitos a 14% é **INDÍCIO** de fonte de fornecedor. As **retenções
  sobre pagamentos a não residentes** são **NÃO VERIFICADO** (`E2` §5), e a
  **disponibilidade de USD** para pagar serviços no estrangeiro a partir de conta
  em Kz é **NÃO VERIFICADO**. Dado relevante de custo: o diferencial de retalho
  entre compra e venda de USD num banco angolano em Outubro de 2026 era de cerca
  de 7% (**CONFIRMADO**, cotação lida).
- **Por que importa.** Decide **D9** na parte «entidade que paga os custos em
  USD». A receita das PMEs é em Kz e o custo variável da plataforma — mensagens
  da Meta, inferência, cloud — é em USD: sem este número não se fixa preço.
  Não bloqueia ticket, mas bloqueia a tabela de preços.
- **Opções propostas pela KAMBÁ.** (a) entidade angolana a pagar os custos em
  USD via banco comercial, absorvendo diferencial e retenções; (b) entidade ou
  conta no estrangeiro a pagar os custos em USD, com a entidade angolana a
  facturar em Kz; (c) repasse explícito dos custos em USD ao preço, com cláusula
  de revisão indexada à taxa de referência do BNA.
- **Resposta pedida.** Parecer escrito — ou parecer de contabilista fiscal,
  anexado — com o regime de IVA aplicável, a tabela de retenções sobre
  pagamentos a não residentes e o enquadramento cambial de cada opção.
- **Prioridade.** **P0** (critério 2 do KAM-104).
- **Prazo pedido.** Parecer escrito até à **semana 6**.

### D — Termos e política da Meta (1 pergunta)

#### D-01 · `E1` 7 — Texto exacto da cláusula §4.7 e uso de LLM de terceiros

- **Texto.** Qual é o **texto exacto** da cláusula §4.7 dos Termos da WhatsApp
  Business Platform sobre dados da plataforma e treino de modelos? Pode usar-se
  um LLM de terceiros em inferência com dados de conversas? Que exigências de
  retenção e de não-treino decorrem dela para os fornecedores?
- **Contexto.** A proibição de usar dados da plataforma WhatsApp Business para
  criar, desenvolver, treinar ou melhorar sistemas de aprendizagem automática ou
  de inteligência artificial está registada como **CONFIRMADO (fonte primária)**,
  mas **com ressalva expressa**: o texto foi lido na versão portuguesa dos Termos
  por extracção automática de página, e `E1` §4 manda **«verificar a cláusula
  exacta»** antes de citar em contrato. A consequência já desenhada é usar o LLM
  **só em inferência**, sem afinação com conversas, e verificar contratualmente
  que o fornecedor não retém nem treina (`08` §8.7, linha «Dados da plataforma
  não treinam ML/IA», e o controlo C-09 da matriz de conformidade). A política de
  «AI Provider» em vigor desde 15 de Janeiro de 2026, com o critério «exclusivo
  da Meta», é **CONFIRMADO** e é risco separado (D2).
- **Por que importa.** Decide se a arquitectura de inferência da KAMBÁ está
  conforme, e é a base de **ADR-018**. Bloqueia **KAM-040** (dataset golden
  sintético e eval harness como gate) na parte em que a avaliação toca conversas,
  e condiciona **KAM-112**. Contribui para **D9**.
- **Opções propostas pela KAMBÁ.** (a) inferência apenas, com retenção zero e
  não-treino contratados por fornecedor e evidência arquivada — o estado actual;
  (b) golden dataset com as três origens que o **KAM-040** especifica
  (`sintetico`, `t2_anonimizado`, `real_consentido`), nenhuma entrando sem
  registo de consentimento — **decidido pelo fundador a 2026-10-30**, e é a
  decisão que F-03 pede que seja validada; (c) pedir à Meta autorização escrita
  para um uso mais largo, que é matéria de KAM-101 e não deste pacote.
- **Resposta pedida.** Parecer escrito que (i) cite a cláusula na versão inglesa
  integral, (ii) diga se a inferência com LLM de terceiros cabe nela, e (iii)
  indique que cláusulas o contrato com cada fornecedor tem de conter.
- **Prioridade.** **P1** pela letra do critério 2; ver §5, divergência 1.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

### E — Alojamento, CDN e backups (5 perguntas)

#### E-01 · `E3` 3 — Que países a APD reconhece como adequados, e que garantias aceita?

- **Texto.** Quais os países que a APD já reconheceu como tendo nível de
  protecção **adequado** (União Europeia, África do Sul, Estados Unidos)? Existe
  lista, parecer ou prática? Para os Estados Unidos, que garantias contratuais a
  APD aceita ao abrigo do Art. 34.º? Existem cláusulas-tipo aprovadas?
- **Contexto. É a pergunta mais consequente do pacote.** O Art. 33.º sujeita a
  transferência para país adequado a **notificação**; o Art. 34.º sujeita a
  transferência para país **não** adequado a **autorização** e a uma das
  circunstâncias previstas (**CONFIRMADO**, duas leituras consistentes). Mas:
  **não há lista pública de países adequados** nas fontes consultadas
  (**CONFIRMADO** quanto à ausência; a inexistência da lista oficial é
  **NÃO VERIFICADO**), e **as cláusulas contratuais-tipo oficiais da APD não
  foram encontradas** (**NÃO VERIFICADO**) — `E3` §2. O critério que a APD
  declarou numa notícia própria — transferência permitida quando no país de
  destino vigora lei especial de protecção de dados e/ou existe autoridade
  independente — é **INDÍCIO**, com a conjunção ambígua. A inferência de que a UE
  e a África do Sul provavelmente satisfazem e os EUA provavelmente não **é
  inferência da KAMBÁ e não está confirmada por nenhuma fonte**.
- **Por que importa.** **Decide D1.** Se JNB/CPT for adequado, a opção
  sul-africana é notificação; se não for, é autorização, com prazo e incerteza
  diferentes. Bloqueia **KAM-105**, **KAM-069** e **KAM-077**.
- **Opções propostas pela KAMBÁ.** (a) alojar em Luanda e tratar só LLM, STT e
  Meta como transferências, reduzindo o número de destinos a autorizar; (b)
  alojar em JNB/CPT e submeter notificação ou autorização para o alojamento
  também; (c) alojar em Luanda com réplica fria em JNB/CPT, o que acrescenta um
  destino. **A escolha é do fundador (D1) e esta sessão não a faz** — o que se
  pede é o dado que a torna decidível.
- **Resposta pedida.** Parecer escrito que diga, por destino relevante (UE,
  África do Sul, EUA), se é adequado, com que fundamento, e que garantias a APD
  aceita onde não for. Se a lista não existir, pede-se que o diga expressamente —
  a ausência é informação útil.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### E-02 · `E3` 4 — O caso Crescer Tech: país da cloud e documentos que teriam evitado a multa

- **Texto.** No caso **Crescer Tech** (deliberação de 24 de Junho de 2026), qual
  foi o país da cloud, e que documentos teriam evitado a multa? É possível obter
  a deliberação?
- **Contexto.** Que a APD multou a Crescer Tech em **USD 505.000** por não
  notificar nem obter autorização para transferência internacional, ao enviar e
  armazenar dados numa cloud fora do país, é **CONFIRMADO** (duas leituras do
  mesmo artigo em português e inglês, mais repetição por outra publicação). **O
  país de destino não vem no artigo: NÃO VERIFICADO.** No mesmo dia, outra
  empresa foi multada em USD 112.000 por falhas de medidas técnicas e
  organizativas e falta de autorização prévia do tratamento (**CONFIRMADO**). O
  acumulado desde 2022 é de cerca de USD 2,5 milhões, 15 empresas
  (**CONFIRMADO** no total, **INDÍCIO** nos detalhes por caso).
- **Por que importa.** **Decide D1**, e é o único dado de **prática
  sancionatória** sobre exactamente o desenho que a KAMBÁ está a construir:
  armazenar dados de clientes em cloud fora do país. Saber o país de destino diz
  se a prática da APD trata destinos diferentes de forma diferente, o que é o
  que E-01 pergunta em abstracto. Bloqueia **KAM-105**.
- **Opções propostas pela KAMBÁ.** Nenhuma: é pedido de facto e de documento.
- **Resposta pedida.** Parecer escrito com o país de destino, a lista dos
  documentos cuja falta fundamentou a sanção, e a deliberação, se obtenível.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### E-03 · `E3` 18 — Há exigência de residência de dados em Angola, e a África do Sul é destino adequado?

- **Texto.** Existe exigência sectorial — banca, saúde, Estado — ou prática da
  APD que prefira ou imponha o armazenamento de dados pessoais em Angola? A
  **África do Sul** conta como destino «adequado»?
- **Contexto.** **Não foi encontrada exigência legal geral** de armazenar dados
  pessoais em Angola na Lei 22/11, na Lei 23/11 nem na Lei 7/17: a Lei 22/11
  prevê transferência **condicionada** (notificação ou autorização), não
  proibição — **INDÍCIO** (ausência de prova; algumas fontes classificam o
  Art. 34.º como «localização de dados», e a leitura registada é que se trata de
  exigência de autorização e não de residência). Regras próprias para entidades
  públicas ou sectores regulados: **NÃO VERIFICADO**. Que alojar em
  Joanesburgo ou na Cidade do Cabo seja **também** transferência é **INDÍCIO**
  (inferência directa dos Arts. 33.º e 34.º; nenhuma fonte trata a África do
  Sul). Existe capacidade de alojamento em Luanda: um data center nacional
  inaugurado em Abril de 2026 e um data center Tier III privado inaugurado em
  Outubro de 2025 (**CONFIRMADO**), com serviços geridos e GPU
  **NÃO VERIFICADO**.
- **Por que importa.** **Decide D1** na sua formulação exacta — «Luanda ou
  JNB/CPT com procedimento APD». Bloqueia **KAM-105**, **KAM-077** (alojamento,
  TLS, edge e WAF) e **KAM-011** (StorageProvider, cuja decisão D6 «decide com
  D1»).
- **Opções propostas pela KAMBÁ.** As mesmas três de E-01, com os custos
  conhecidos de cada lado: Luanda reduz o número de destinos a autorizar mas
  **não dispensa o procedimento**, porque LLM, STT e a própria Meta seriam
  transferências — **INDÍCIO**, não facto: é a inferência que `E3` §2 marca
  assim e é exactamente o que **A-02** pergunta, pelo que a premissa desta
  opção depende da resposta a A-02 *(a confirmar por parecer)*. JNB/CPT
  acrescenta o alojamento à lista de transferências, com latência e custo
  diferentes, medidos em `09`. **A escolha é do fundador.**
- **Resposta pedida.** Parecer escrito sobre a existência de exigência de
  residência, a prática da APD, e a qualificação da África do Sul.
- **Prioridade.** **P0**.
- **Prazo pedido.** Preliminar **semana 3**; parecer escrito **semana 6**.

#### E-04 · `08` §13 N1 — Um CDN ou WAF que termina TLS é subprocessador com acesso a conteúdo?

- **Texto.** Um fornecedor de rede de distribuição de conteúdos ou de firewall
  aplicacional que **termina TLS** — e portanto vê o corpo dos pedidos em claro,
  incluindo o corpo dos webhooks — é subprocessador com acesso a conteúdo? Tem
  de constar da notificação à APD e da lista de subprocessadores do DPA?
- **Contexto.** É uma **lacuna identificada na própria documentação da KAMBÁ**: o
  documento de topologia põe o fornecedor «à frente (TLS, WAF)», o que significa
  que o proxy **termina TLS e vê o corpo dos webhooks em claro**. Esse é o facto
  técnico, e é verificável. **Se isso o torna subprocessador com acesso a
  conteúdo é precisamente o que esta pergunta pede** *(a confirmar por
  parecer)*: a documentação interna da KAMBÁ afirma-o sem ressalva, e o pacote
  não herda essa afirmação. No inventário de subprocessadores aparece com
  destino «Global» e com a nota de lacuna (`08` §8.3.2). As duas opções estão escritas e
  **nenhuma está decidida**: (a) assumir como subprocessador e incluir na
  notificação; (b) **não** colocar o caminho de webhooks atrás do proxy — a
  assinatura da Meta já autentica o pedido — e proteger a origem com limitação de
  débito. O documento diz expressamente «decidir com o advogado».
- **Por que importa.** Decide **D12** (CDN/WAF como subprocessador), hoje ABERTA
  com escalada «antes de produção». Bloqueia **KAM-077**, **KAM-076** (compose de
  produção e redes isoladas) e **KAM-069** na parte do inventário. **Leitura da
  KAMBÁ:** se a notificação à APD tiver de listar todos os subprocessadores, esta
  resposta é um **input da submissão P0**, e não uma P1 — ver §5, divergência 3.
- **Opções propostas pela KAMBÁ.** As duas acima. A opção (b) é a que a KAMBÁ
  pode executar **sem** parecer, e é a que recomenda enquanto espera, porque
  retira o conteúdo do perímetro em vez de o justificar.
- **Resposta pedida.** Parecer escrito que qualifique o fornecedor nas duas
  configurações — com e sem o caminho de webhooks atrás do proxy — para que a
  escolha técnica tenha consequência jurídica conhecida.
- **Prioridade.** **P1**.
- **Prazo pedido.** Pede-se **com as P0** (semana 6) se a resposta a A-03 for que
  a submissão tem de listar todos os subprocessadores; caso contrário, semana 10.

#### E-05 · `08` §13 N2 — Backups cifrados fora de Angola, com a chave em Angola, são transferência?

- **Texto.** Backups **cifrados** armazenados fora de Angola, com a chave de
  cifra mantida exclusivamente em Angola e nunca acessível ao operador do
  repositório, constituem transferência internacional de dados pessoais para
  efeitos dos Arts. 33.º e 34.º?
- **Contexto.** O gate de transferência da KAMBÁ aplica-se expressamente a
  «backups fora de Angola» (`08` §8.3.1), e a política de retenção prevê registo
  de escrita antecipada de 7 dias para recuperação a um ponto no tempo e cópias
  diárias de 35 dias, sem reescrita, com o registo de eliminações reaplicado no
  restauro (`08` §11). A localização dos backups está **NÃO VERIFICADO** e ligada
  a D1 e D6 (`08` §16). O risco está registado: «backups fora da jurisdição →
  incumprimento dos Arts. 33.º e 34.º», com N2 como mitigação (`08` §15).
- **Por que importa.** Decide **D1** e **D12** na parte dos backups, e decide se
  a recuperação de desastre pode viver fora da região escolhida — que é a
  diferença entre ter e não ter recuperação de desastre no Piloto. Bloqueia
  **KAM-011** e **KAM-077**.
- **Opções propostas pela KAMBÁ.** (a) backups na mesma jurisdição do
  alojamento, sem a questão se pôr — o mais simples, e o que o risco registado
  recomenda; (b) backups cifrados fora, com chave em Angola, tratados como
  transferência e autorizados; (c) backups cifrados fora, com chave em Angola,
  **não** tratados como transferência, se o parecer o permitir. A KAMBÁ **não**
  assume (c).
- **Resposta pedida.** Parecer escrito que diga se a cifra com chave retida
  altera o enquadramento, e, se não alterar, se altera a **medida de segurança**
  exigível (Arts. 30.º e 31.º) — porque isso ainda tem valor.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

### F — Perguntas novas da KAMBÁ (3 perguntas)

> As três perguntas deste bloco não vêm de `E1`, `E2` nem `E3`: nascem do
> trabalho feito desde essas investigações e são as que o critério 1 do KAM-104
> manda acrescentar.

#### F-01 · X1 — Dados reais de teste com consentimento, em spikes

- **Texto.** Em spikes de validação técnica, a KAMBÁ precisa de usar **dados
  reais** — três números +244 próprios no spike de coexistência, e áudio de voz
  real em português de Angola no spike de transcrição, incluindo envio a um
  fornecedor nos Estados Unidos. Com consentimento escrito de cada falante e de
  cada dono de número, sem armazenar conteúdo de mensagem (só tipo de evento,
  identificadores, carimbos e contagens), com apagamento em prazo curto e no fim
  do spike: (i) este tratamento é lícito antes de concluído o procedimento junto
  da APD? (ii) o envio de áudio a um fornecedor nos Estados Unidos, nessas
  condições, exige autorização do Art. 34.º, ou cabe na circunstância de
  consentimento expresso escrito? (iii) que forma deve ter esse consentimento?
- **Contexto.** A restrição é da própria KAMBÁ: **ADR-008** diz que nenhum dado
  pessoal de produção sai de Angola sem notificação ou autorização da APD, e o
  Piloto corre com dados sintéticos até ao gate de go-live (`08` §15, §4 item
  12). Mas dois tickets de Fase 0 precisam de dados reais na **semana 1**: o
  spike de coexistência (KAM-100), cujo critério de privacidade prevê
  expressamente «excepção de dados reais de teste declarada em KAM-104», e o
  spike de voz (KAM-107), cujo critério exige «consentimento escrito de cada
  falante (inclui envio a um fornecedor nos EUA)» e que «a pergunta X1 de
  KAM-104 [esteja] respondida ou o risco aceite por escrito antes de enviar
  áudio». Que o áudio de voz seja dado pessoal, e sensível se revelar saúde, é
  **INDÍCIO** (inferência a partir do Art. 5.º c)). As circunstâncias do
  Art. 34.º, entre elas o consentimento expresso escrito, são **CONFIRMADO**.
- **Por que importa.** Bloqueia **KAM-100** e **KAM-107** — dois spikes de Fase
  0 cujo resultado alimenta H3 e a decisão sobre transcrição. Sem esta resposta,
  ou os spikes correm sobre risco aceite por escrito pelo fundador, ou esperam
  pelo procedimento completo da APD, que é o que o calendário não comporta.
- **Opções propostas pela KAMBÁ.** (a) consentimento expresso escrito de cada
  titular, âmbito restrito ao spike, sem conteúdo armazenado, apagamento em ≤ 30
  dias e no fim, invocando a circunstância de consentimento do Art. 34.º; (b)
  áudio sintético ou de locutores contratados com cessão expressa, evitando a
  questão; (c) risco aceite por escrito pelo fundador, com registo, se o parecer
  não chegar a tempo. **A escolha entre (a), (b) e (c) é do fundador**, porque
  (c) é aceitação de risco regulatório.
- **Resposta pedida.** Parecer escrito com as três respostas e, se (a) for
  viável, a **minuta do consentimento** a usar.
- **Prioridade.** **P1** pela letra do critério 2; ver §5, divergência 4.
- **Prazo pedido.** Pede-se **resposta preliminar até à semana 2**, por ser a
  única P1 que bloqueia trabalho de semana 1; parecer escrito até à semana 10.

#### F-02 · X2 — Quem paga os custos em USD, e que retenções incidem sobre pagamentos a fornecedores estrangeiros

- **Texto.** Qual deve ser a entidade que paga os custos recorrentes em USD —
  mensagens da Meta, inferência de modelos de linguagem, cloud e armazenamento —
  e quais as consequências de cada opção: (i) entidade angolana a pagar a partir
  de conta em Kz, com operação cambial via banco comercial; (ii) entidade ou
  conta no estrangeiro a pagar, com a entidade angolana a facturar em Kz. Para
  cada uma: que retenções na fonte ou impostos incidem sobre os pagamentos a
  prestadores **não residentes**, que obrigações declarativas nascem, e que
  restrições cambiais se aplicam a uma empresa (não a pessoa singular)?
- **Contexto.** `E2` §5 registou duas lacunas exactamente aqui, ambas
  **NÃO VERIFICADO**: a disponibilidade de USD para pagar serviços no
  estrangeiro a partir de conta em Kz e por que cartão, e os impostos aplicáveis
  a pagamentos de serviços a prestadores não residentes. Factos conhecidos: o
  diferencial de retalho entre compra e venda de USD num banco angolano em
  Outubro de 2026 era de cerca de 7% (**CONFIRMADO**); o câmbio nominal estava
  praticamente estável (**INDÍCIO**); e as PMEs angolanas podem não ter cartão
  internacional, o que `E1` identifica como barreira real de adopção
  (**CONFIRMADO** quanto à facturação da Meta ser em USD ou EUR para Angola).
  Esta pergunta é a metade **estrutural** daquilo de que C-06 pergunta a metade
  **fiscal**; estão separadas porque C-06 é P0 pela letra do critério 2 e esta
  não.
- **Por que importa.** Decide **D9** na parte «entidade que paga os custos em
  USD», que está inscrita assim na Carta e cujo dono é o **fundador** com o
  jurídico. Condiciona **KAM-105**. Sem resposta, a tabela de preços em Kz
  assenta numa estrutura de custo não decidida.
- **Opções propostas pela KAMBÁ.** As duas do texto. A KAMBÁ **não recomenda
  nenhuma**: a escolha tem consequências de estrutura societária e fiscal que
  são decisão do fundador, e o que este pacote pede é o custo de cada lado.
- **Resposta pedida.** Parecer escrito — com parecer de contabilista fiscal
  anexado onde a matéria for dele — que dê, por opção, as retenções, as
  obrigações declarativas, as restrições cambiais e o risco.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### F-03 · X3 — Uso de conversas para avaliação do sistema, face aos Termos da Meta

- **Texto.** Os Termos da WhatsApp Business Platform proíbem usar dados da
  plataforma para criar, desenvolver, treinar ou melhorar sistemas de
  aprendizagem automática ou de inteligência artificial. Usar conversas reais —
  ou derivados delas — para **avaliar** o sistema (medir qualidade de resposta,
  construir um conjunto de casos de referência, detectar regressões em cada
  alteração) cai nessa proibição? A resposta muda se (i) as conversas forem
  pseudonimizadas, (ii) só se guardarem as perguntas e não as respostas, (iii) a
  avaliação for manual e não automatizada, (iv) o conjunto de referência for
  **sintético**, inspirado em conversas reais mas não derivado literalmente, (v)
  o caso for **uma conversa real concreta reescrita**, com os dados pessoais
  substituídos (nomes, números de telefone, moradas e valores trocados por outros
  inventados), de modo que a forma da pergunta se mantém e nada no texto remete
  para o titular?

  **A variante (v) é a que falta decidir, e é por isso que foi acrescentada.** Não
  é a (i), porque a pseudonimização conserva a conversa e troca só os
  identificadores; não é a (iv), porque não é inspiração — é uma conversa concreta
  reescrita. É a origem `t2_anonimizado`, que é o que o pipeline de suporte T2
  produz (`../../10_Onboarding_Governanca.md` §11.2) e a única fonte de casos
  escritos por clientes reais em português de Angola, que é precisamente o que
  está **NÃO VERIFICADO** e que este conjunto existe para medir.
- **Contexto, e uma decisão já tomada que torna a pergunta mais precisa.**
  A KAMBÁ **decidiu** que o conjunto de avaliação admite três origens —
  `sintetico`, `t2_anonimizado` (reescrita sintética sem dados pessoais) e
  `real_consentido` —, e que **nenhum caso real entra sem registo de
  consentimento**. É o que o **KAM-040** especifica como critério de aceitação, e
  é **decisão do fundador de 2026-10-30**, tomada depois de o KAM-104 medir que
  afirmações do conjunto documental invocavam o ADR-018 e não diziam o mesmo. **A
  contagem subiu em cada passagem, e as três ficam escritas** porque o número não
  é o que importa aqui — importa que nenhuma passagem escondia nada, e cada uma
  era o que o seu instrumento via: **sete** quando o KAM-104 as mediu (quatro só a
  reescrita sintética, três a admitir material real com consentimento),
  **dezassete** quando o KAM-169 refez a medição com buscas que apanham o plural e
  a glosa, e **vinte** depois da revisão adversarial desse ticket e da fusão deste
  pacote. A divergência está resolvida a favor das três origens: o KAM-169 alinhou
  oito afirmações, este pacote uma, e as cinco que sobram são glosas de uma linha,
  registadas em `../../../dividas-documentais.md` (linha 157).
  **O que se pede ao advogado já não é «qual dos lados vale»** — isso era
  decisão da KAMBÁ e está tomada — **mas se a decisão se sustenta**: o
  consentimento recolhido do titular pela PME basta, perante os Termos da Meta
  §4.7 e perante a Lei 22/11, para que uma conversa real entre num conjunto de
  avaliação? A leitura do texto dos Termos é **CONFIRMADO com ressalva** de
  leitura automática, e D-01 pede o texto exacto — esta pergunta depende dessa
  resposta.
- **Por que importa.** Bloqueia **KAM-040** (dataset *golden* PT-AO pelas três
  origens e eval harness como gate) na parte em que define o que pode entrar no
  conjunto.
  Contribui para **D9**. É a pergunta cuja falta de resposta deixou a caixa do
  gate de avaliação por preencher em tickets já entregues.
- **Opções propostas pela KAMBÁ.** A opção **(b) está decidida**: as três
  origens do KAM-040, com o registo de consentimento por caso como barreira e
  sem nenhum caso real a entrar sem ele. O que se pede é a validação dela, e as
  alternativas existem para o caso de o parecer a recusar: **(a)** recuar para
  conjunto inteiramente sintético, se o consentimento da PME não bastar perante
  os Termos; **(c)** material real pseudonimizado para além do que o KAM-040
  admite, que exigiria também resposta da Meta (KAM-101). **Se o parecer
  recusar (b), a KAMBÁ recua para (a)** — e é por isso que a resposta importa
  antes de o conjunto ser construído, não depois.

  **E o alcance da (a) depende da variante (v), que é a razão de ela estar na
  pergunta.** «Inteiramente sintético» exclui ou não um caso `t2_anonimizado`? Os
  dois textos do conjunto divergiram exactamente aqui — este pacote escrevia
  «inteiramente sintético», e o `../../../adr/ADR-L006-origem-do-golden-set.md`
  escrevia, na sua primeira versão, que cairia só o `real_consentido` e sobrariam
  `sintetico` **e** `t2_anonimizado`. **A KAMBÁ não escolhe entre os dois e não
  recomenda nenhum:** a diferença é se uma conversa reescrita sem dados pessoais
  continua a ser, para efeitos do §4.7, uma conversa real — o que é leitura
  jurídica e não decisão de produto. Decisão do fundador a 2026-10-30, ao ser-lhe
  apresentada a divergência: **a pergunta vai ao parecer em vez de ser decidida
  internamente**. Até haver resposta, vale o recuo escrito acima, por ser o que
  está no canon.
- **Resposta pedida.** Parecer escrito que responda às **cinco** variantes — e,
  na (v), que diga se uma conversa reescrita sem dados pessoais conta como
  conversa real para efeitos da cláusula, porque é essa resposta que fixa o
  alcance do recuo (a). E que diga se a distinção entre «treinar/melhorar» e
  «avaliar» tem apoio no texto da cláusula ou se é leitura.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*, depois de
  D-01.

### G — Defesa do consumidor, categorias sectoriais e desinformação (5 perguntas)

#### G-01 · `E3` 11 — Venda à distância: desistência, informação pré-contratual e Livro de Reclamações

- **Texto.** O direito de desistência de **7 dias úteis** (Lei 15/03, Art. 15.º)
  aplica-se a compras feitas por WhatsApp? Que excepções existem — perecíveis,
  personalizados, digitais? Que informação pré-contratual é obrigatória? O Livro
  de Reclamações aplica-se ao comércio online?
- **Contexto.** A **existência** do direito de desistência é **CONFIRMADO**
  (duas fontes); o prazo exacto e o âmbito — se cobre o WhatsApp — são
  **INDÍCIO**, e a numeração do artigo varia entre fontes. Outra fonte diz que
  **não há lei especial sobre contratos à distância** e que se aplicam o Código
  Civil, a lei das cláusulas contratuais gerais e a Lei 15/03. O dever de
  informar sobre quantidade, características, composição, qualidade e **preço**
  (Art. 9.º), com solidariedade dos intervenientes da cadeia que também violaram
  o dever de informação, é **CONFIRMADO** (dois resumos concordantes; verificar
  a redacção). A obrigação de Livro de Reclamações existe para estabelecimentos
  (**CONFIRMADO** quanto à existência); a aplicação à venda online é
  **NÃO VERIFICADO**.
- **Por que importa.** Fixa o conteúdo obrigatório da confirmação de encomenda e
  a existência do fluxo de devolução, e determina o que os termos de utilização
  podem dizer. Bloqueia **KAM-090**.
- **Opções propostas pela KAMBÁ.** (a) aplicar o mais exigente — confirmação
  final com preço total, características, entrega, garantia, política de
  devolução e identificação do vendedor, mais fluxo de desistência com registo da
  data de recepção — o estado desenhado; (b) aplicar apenas onde a lei o exigir,
  depois de delimitado; (c) disponibilizar canal de reclamação por conversa em
  qualquer caso, que a KAMBÁ assume por precaução.
- **Resposta pedida.** Parecer escrito com o prazo e o âmbito do direito de
  desistência neste canal, a lista das excepções, a informação pré-contratual
  obrigatória e a aplicação do Livro de Reclamações.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### G-02 · `E3` 12 — Responsabilidade da plataforma por informação errada da IA, produtos ilícitos e avaliações falsas

- **Texto.** Qual a responsabilidade da plataforma, como intermediária, por
  informação errada gerada por inteligência artificial, por produtos ilícitos
  vendidos pelas PMEs e por avaliações falsas? As cláusulas de exclusão de
  responsabilidade nos termos de utilização são válidas (Lei 15/03, Art. 16.º)?
- **Contexto.** A Lei 23/11 **não** trata a responsabilidade dos prestadores
  intermediários (**INDÍCIO**, leitura única), pelo que **não há «porto seguro»
  claro** para a plataforma, e a leitura registada é tratar-se como responsável
  pelo conteúdo que difunde. A nulidade de cláusulas abusivas, entre elas a
  exclusão de responsabilidade do fornecedor, é **INDÍCIO**. A
  responsabilidade de plataformas perante o consumidor é **NÃO VERIFICADO**
  (nada específico encontrado). A KAMBÁ já desenhou contra o risco: o preço, a
  quantidade e as características vêm do catálogo do vendedor como fonte única, o
  modelo não inventa preços, e há validador de citação (ADR-007, `08` §8.11).
- **Por que importa.** Determina o que os termos de utilização podem dizer e
  quanto risco a KAMBÁ retém pelo que o assistente responde. Contribui para
  **D11** (Kambá Score como informação de crédito, hoje CONDICIONAL). Bloqueia
  **KAM-090** e **KAM-033** na parte dos limites de saída.
- **Opções propostas pela KAMBÁ.** (a) o assistente só cita dados do catálogo,
  com validador de citação e sem geração livre de preços — o estado actual; (b)
  descrições geradas por modelo validadas pela PME antes de saírem; (c) cláusulas
  de limitação de responsabilidade proporcionais, que o parecer dirá se valem.
- **Resposta pedida.** Parecer escrito com o regime de responsabilidade
  aplicável, a validade das cláusulas de exclusão e limitação, e o que a KAMBÁ
  tem de poder provar para se eximir.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

#### G-03 · `E3` 13 — Medicamentos, dispositivos médicos, suplementos e cosméticos

- **Texto.** É lícita a venda e a entrega online por farmácias licenciadas? Que
  regra da autoridade do medicamento ou do ministério da saúde se aplica? E
  quanto a dispositivos médicos, suplementos e cosméticos?
- **Contexto.** A **legalidade da venda online de medicamentos é
  NÃO VERIFICADO**. O licenciamento da actividade farmacêutica pelo Decreto
  Presidencial 41/24, de 29 de Janeiro — autorização única por 5 anos, abrangendo
  farmácias, ervanárias, lojas de cosméticos e de produtos de saúde,
  distribuidores e importadores — é **CONFIRMADO** quanto ao conteúdo, e **não
  regula venda à distância, internet ou entrega** (**INDÍCIO** quanto ao
  silêncio). Que a distribuição comercial de medicamentos fora de farmácias esteja
  proibida é **INDÍCIO** (imprensa, sem indicação do diploma). Em 2015 houve
  actuação contra sítios estrangeiros que vendiam medicamentos a angolanos.
- **Por que importa.** A categoria está hoje **excluída por dupla razão**: a
  política da Meta proíbe-a independentemente de licença local, e os dados de
  compra de medicamentos são dados de saúde (`08` §8.9, §4 item 10). Bloqueia
  **KAM-088** na parte em que a lista de bloqueio pode ser afinada. Não bloqueia
  o Piloto.
- **Opções propostas pela KAMBÁ.** (a) manter medicamentos e dispositivos
  médicos excluídos — o estado actual, que a política da Meta impõe de qualquer
  forma; (b) abrir apenas a farmácias com licença comprovada, se o parecer e a
  Meta o permitirem; (c) tratar cosméticos e suplementos como categoria distinta,
  que é onde a resposta pode mudar algo no Piloto.
- **Resposta pedida.** Parecer escrito que delimite as quatro categorias e diga,
  para cada uma, se a venda por este canal é lícita e com que prova de licença.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### G-04 · `E3` 14 — Álcool, tabaco, armas e jogos

- **Texto.** Existe lei específica de controlo do tabaco em vigor? Como se aplica
  a Lei n.º 12/25 (álcool) a vendas online e a entregas, em particular a
  restrição de distância a determinados locais? Qual o diploma das armas de fogo?
  Que prova de licença, emitida pelo Instituto de Supervisão de Jogos (ISJ),
  deve a PME exibir para operar jogos?
- **Contexto. Álcool:** a Lei n.º 12/25, de 3 de Outubro — proibição a menores
  de 18 anos, proibição de venda e consumo a menos de 300 metros de hospitais,
  escolas, quartéis, esquadras, locais de culto e cemitérios, e horários — é
  **INDÍCIO** (o número e a data vêm do identificador de página dos portais; o
  conteúdo vem de notícia sobre a proposta, não sobre o texto final), e a venda
  à distância **não vem tratada** nas fontes; como a regra dos 300 metros se
  aplica a **entregas** é **NÃO VERIFICADO**. **Tabaco:** a proibição total de
  publicidade (Lei 9/17) é **INDÍCIO**; a existência de lei específica de
  controlo do tabaco é **NÃO VERIFICADO**. **Armas:** a lei angolana das armas de
  fogo **não foi encontrada** — **NÃO VERIFICADO**. **Jogos:** a Lei n.º 17/24,
  de 28 de Outubro, que sujeita os jogos de fortuna ou azar, incluindo online, a
  licença de sociedade anónima por concurso público, com o **Instituto de
  Supervisão de Jogos (ISJ)** como regulador e supervisor — que aceita pedidos
  de licença desde 18 de Fevereiro de 2025 (**INDÍCIO**) —, proibição a
  menores, identificação do jogador e eliminação de dados depois da
  finalidade, é **CONFIRMADO** (uma leitura do texto).
- **Por que importa.** Hoje as quatro categorias estão fora do Piloto, por
  bloqueio absoluto (armas) ou exclusão (álcool, tabaco, jogos sem licença) —
  `08` §8.9, §4 item 10. A pergunta serve para que a lista de bloqueio tenha
  fundamento escrito em vez de precaução, e para o dia em que uma delas abra.
  Bloqueia **KAM-088**.
- **Opções propostas pela KAMBÁ.** (a) manter as quatro fora, que é o estado
  actual e o que a política da Meta impõe; (b) abrir álcool com verificação de 18
  anos e restrições de entrega, se o parecer e a Meta o permitirem; (c) abrir
  jogos só com licença comprovada do regulador.
- **Resposta pedida.** Parecer escrito por categoria, com o diploma aplicável
  verificado no DR, a aplicação a venda e entrega à distância, e a prova de
  licença exigível.
- **Prioridade.** **P2**.
- **Prazo pedido.** Parecer escrito até à **semana 16** *(proposta)*.

#### G-05 · `E3` 16 — A lei contra a desinformação: um bot comercial é «conta inautêntica» ou «disseminador artificial»?

- **Texto.** A lei contra a disseminação de informação falsa na Internet, em
  vigor desde 6 de Agosto de 2026, qualifica um assistente automatizado
  comercial como «conta inautêntica» ou «disseminador artificial»? Existem
  obrigações de relatório ou de registo para a plataforma?
- **Contexto.** Que a lei esteja **em vigor desde 6 de Agosto de 2026**, após
  publicação em Diário da República, e que abranja conteúdos criados no
  estrangeiro dirigidos ao público angolano, é **CONFIRMADO** (várias notícias);
  os detalhes das obrigações — definições de «contas inautênticas»,
  «disseminadores artificiais» e «redes artificiais de disseminação», relatórios
  mensais das plataformas, coimas por múltiplos do salário mínimo nacional — são
  **INDÍCIO**, e o **número da lei não foi encontrado**. A leitura registada é de
  risco colateral: um assistente de WhatsApp com envios em massa pode ser lido
  como «disseminador artificial» se difundir conteúdo.
- **Por que importa.** Determina os limites de automação e de envio em massa, e
  se há obrigação de registo ou de relatório que a KAMBÁ não está a cumprir.
  Bloqueia **KAM-088** e **KAM-058** (régua de cobrança) na parte da frequência
  de envio.
- **Opções propostas pela KAMBÁ.** (a) limites de envio, só para destinatários
  com interacção ou opt-in, sem difusão de conteúdo informativo em massa, e
  identificação explícita de que é conta automatizada — o estado desenhado (`E3`
  req. 22); (b) acrescentar registo ou relatório se a lei o exigir; (c) nenhuma
  mensagem iniciada pela plataforma sem relação comercial prévia.
- **Resposta pedida.** Parecer escrito com o número e o texto da lei verificados
  no DR, a qualificação do assistente comercial, e a lista de obrigações que
  recaem sobre a plataforma.
- **Prioridade.** **P1**.
- **Prazo pedido.** Parecer escrito até à **semana 10** *(proposta)*.

---

## 4. O que a KAMBÁ assume até haver parecer, e quem o mantém

Esta é a lista do que está **desligado ou restringido por precaução jurídica**.
Não é a lista do que falta construir: cada item tem hoje uma barreira — técnica,
contratual ou de política — e a barreira só se remove com a resposta à pergunta
que a coluna nomeia. **O dono é quem mantém a barreira e quem a reavalia quando
a resposta chegar**, e são 17 — o 17.º entrou pela revisão adversarial, que
apanhou a barreira do consentimento por caso de avaliação a faltar aqui.

| # | Item assumido | Barreira hoje | Fonte | Pergunta que o liberta | Dono |
|---|---|---|---|---|---|
| 1 | **Comissão sobre transacção desligada** | Sem cobrança de comissão sobre valor transaccionado no Piloto | ADR-017, D8 | B-01, B-08 | Responsável de Produto |
| 2 | **Finalidades próprias da KAMBÁ desligadas** (sinal de procura agregado, Kambá Score) | Tratamentos de finalidade própria não corridos no Piloto | `08` §8.2, D9 | A-01, A-12 | Responsável de Segurança (privacidade) |
| 3 | **Payouts inexistentes** | `PaymentProvider.payout` sem implementação nem rota; bandeira fail-closed; CI falha se existir implementação | `08` §8.10, ADR-004 | B-03 | Responsável de Pagamentos |
| 4 | **Escrow inexistente** | Não existe estado «retido»; disputa de entrega tratada fora do gateway | `08` §8.10 | B-04 | Responsável de Pagamentos |
| 5 | **Sem saldos nem carteira** | Nenhuma tabela de saldos; vocabulário «carteira», «saldo» e «escrow» proibido na interface e no código | `08` §8.10 | B-04, B-05 | Arquitecto de Plataforma |
| 6 | **O bot não acciona pagamento a partir da conta do cliente** | O cliente paga na sua própria aplicação; o bot nunca recebe credenciais | `08` §8.10 | B-02 | Responsável de Pagamentos |
| 7 | **A KAMBÁ não emite facturas fiscais próprias** | Nenhuma rota emite documento fiscal (controlo C-04) | `08` §8.8, Decreto Presidencial 71/25 | C-02, C-05 | Responsável de Produto |
| 8 | **Registos fiscais não se eliminam** | `fiscal_retention_years` sem valor por defeito que apague | `08` §8.8 | C-05 | Responsável de Produto, com contabilista |
| 9 | **Dados sensíveis não persistem nem saem** | Ao detectar saúde, religião, política ou vida sexual: não persistir, não enviar ao modelo, resposta neutra com handoff | `08` §7.5, `E3` req. 10 | A-04 | Responsável de Segurança |
| 10 | **Categorias vedadas** — medicamentos, dispositivos médicos e saúde, álcool, tabaco, jogos, armas e munições, crédito, marketing multinível, cripto | Lista de bloqueio no onboarding e no catálogo, com revisão humana de amostra | `08` §8.9 | A-04, G-03, G-04 | Trust & Safety |
| 11 | **Gate de transferência fail-closed** | Sem linha autorizada em `tenant_destinations` (tenant, fornecedor, país, finalidade, `apd_ref`), a chamada falha | `08` §8.3.1, ADR-008 | A-02, E-01, E-03 | Responsável de Segurança |
| 12 | **Nenhum dado pessoal de produção fora de Angola sem procedimento APD; Piloto com dados sintéticos** | Gate de go-live; dados sintéticos até lá | ADR-008, `08` §15 | A-03, E-01, E-02, E-03, F-01 | Responsável de Segurança |
| 13 | **Aviso de privacidade sem versão publicada** | A tabela de textos de consentimento nasce vazia e o gate falha fechada: sem aviso para mostrar, não há consentimento a registar e o assistente não corre | Dicionário canónico §3, KAM-022 | A-01, A-07, G-01 | Responsável de Segurança (privacidade) |
| 14 | **Áudio bruto não sai sem gate de destino** | Transcrever cedo, apagar o blob em ≤ 24 horas (limite de erro 72 h), não enviar áudio bruto a transcrição no estrangeiro sem gate | `08` §7.5 | A-02, F-01 | Responsável de Segurança |
| 15 | **Fluxo B e número agregador diferidos** | Só Fluxo A no Piloto; isolamento entre PMEs | ADR-011, D2, `E1` §4 | — (é KAM-101, resposta da Meta) | Responsável de Produto |
| 16 | **Kambá Score não é informação de crédito** | Score não usado nem apresentado como informação de crédito | D11 (CONDICIONAL, gatilho Escala) | G-02 | Responsável de Produto, com jurídico |
| 17 | **Nenhum caso real entra no conjunto de avaliação sem registo de consentimento** | O KAM-040 exige `origem ∈ {sintetico, t2_anonimizado, real_consentido}` e nenhum `real_consentido` sem registo de consentimento; a barreira é o registo, não a ausência de material real. **Decisão do fundador, 2026-10-30**, que fechou a divergência a favor das três origens | ADR-018, KAM-040 | D-01, F-03 | Responsável de Segurança (privacidade), com o dono do KAM-040 |

> **Dois itens desta lista não se libertam com este pacote**, e estão aqui para
> que ninguém os confunda com itens jurídicos: o 15 depende de resposta escrita
> da **Meta** (KAM-101, decisão D2), não de parecer; e o 16 tem gatilho de fase
> (Escala), não de parecer, embora G-02 informe o seu enquadramento.

> **Uma opção que a KAMBÁ ainda NÃO assumiu, e devia constar:** o caminho dos
> webhooks atrás do proxy que termina TLS. As duas opções estão escritas em
> `08` §8.3.2 e **nenhuma está decidida**. A opção que não precisa de parecer —
> não pôr o caminho de webhooks atrás do proxy, já que a assinatura da Meta
> autentica o pedido — é executável hoje e retira conteúdo do perímetro. Fica
> como **decisão pendente de SRE**, não como item assumido, porque assumi-la
> sem a decidir era o inverso do que esta lista faz.

---

## 5. Onde a leitura da KAMBÁ diverge da letra do critério 2

O critério 2 do KAM-104 fixa as prioridades e este pacote **não as reinventou**.
Em quatro pontos a leitura da KAMBÁ diverge da letra, e a regra da casa é
escrever a leitura e **devolver a decisão a quem escreveu o critério** — não
mudar a classificação por conta própria. As quatro perguntas abaixo estão
classificadas **pela letra**; o que segue é o que a KAMBÁ mediria de outra
forma.

| # | Pergunta | Letra | Leitura da KAMBÁ | Porquê |
|---|---|---|---|---|
| 1 | **D-01** (`E1` Q7, §4.7 dos Termos) | P1 — o critério 2 reserva P0 às oito do `E3`, às duas do BNA e à do contabilista | Operacionalmente P0 | É o fundamento de **ADR-018** e decide se a avaliação do sistema pode usar material real. Uma caixa de gate de avaliação já ficou vazia em tickets entregues por falta desta resposta |
| 2 | **B-08** (`08` §13 N5) | P1 | Devia viajar com B-01 e B-02, que são P0 | B-08 é a **forma agregada** da mesma pergunta que B-01 e B-02 fazem por partes. Responder à agregada depois das parcelas inverte a ordem útil. O pacote pede-a para a semana 6 e mantém a classificação P1 |
| 3 | **E-04** (`08` §13 N1, CDN) e **E-05** (N2, backups) | P1 | Condicionalmente P0 | Se a resposta a **A-03** for que a submissão à APD tem de listar **todos** os subprocessadores, então E-04 e E-05 são *input* de uma submissão P0, e não refinamentos posteriores. O pacote declara essa condição no prazo pedido de E-04 |
| 4 | **F-01** (X1, dados reais em spikes) | P1 | Antecede algumas P0 no calendário | Bloqueia **KAM-100** e **KAM-107**, que arrancam na **semana 1**. Por isso o pacote pede resposta preliminar até à **semana 2** — mais cedo do que o parecer escrito de qualquer P0 — mantendo a prioridade P1 da letra |

Nenhuma destas quatro foi reclassificada. **A decisão é de quem escreveu o
critério 2**; o que esta sessão podia fazer era medir a divergência e deixá-la
visível.

---

## 6. O que este pacote não contém, e porquê

| O que falta | Razão |
|---|---|
| **Confirmação de que o pacote foi enviado, e protocolo de recepção** | Enviar é acto humano. Esta sessão produz o pacote pronto a enviar; o critério 4 do KAM-104 fica **não satisfeito** e a sua caixa vazia |
| **Duas ou mais propostas de honorários, e carta de compromisso assinada** | Pedir honorários a advogados e assinar não é acto de sessão. O que existe é o **molde**: critérios de selecção, âmbito por prioridade, formato de parecer, prazos e minuta da carta de compromisso, no artefacto interno de selecção e registo, §1 e §2 — não anexado. O critério 5 fica **não satisfeito** |
| **Respostas registadas, com data, autor e classificação «CONFIRMADO (jurídico)»** | Não há respostas: o pacote não foi enviado. O que existe é a **tabela vazia com as colunas certas** e a lista de decisões e tickets que cada resposta afectará, no artefacto interno de selecção e registo, §3 — não anexado. O critério 6 fica **não satisfeito** |
| **Qualquer leitura jurídica definitiva da KAMBÁ** | Por desenho. É o que o pacote vai pedir; escrevê-lo como se já se soubesse retirava-lhe a razão de existir |
| **Exportação em formato de documento** | Nenhum conversor correu aqui. A exportação é este pacote e o anexo, sem nada retirado; produzi-la é acto de quem envia, e viaja com o critério 4 |

---

### 6.1 O que ainda não existe no sistema

Esta secção estava no anexo e passou para cá, para manter o anexo dentro das
seis páginas que o critério 3 do KAM-104 exige. O conteúdo não se perdeu: os dois
ficheiros viajam juntos.

Para que o parecer saiba o que **não** pode apreciar. Não existe: **mapa de
tratamentos** (desenhado como pré-requisito — as §3, §4 e §5 do anexo são a
matéria-prima, não o produto); **contrato de subcontratação** redigido;
**avaliação de impacto** completa (esqueleto de duas linhas); **texto do aviso
de privacidade**; **base legal de seis das dez finalidades**; **parecer sobre o
enquadramento no sistema de pagamentos**; **resposta escrita da Meta** sobre a
classificação do caso de uso e o número agregador, que não é matéria deste
parecer mas condiciona o produto; **lista de países adequados e cláusulas-tipo
da APD**; e **validação da certificação** do parceiro de facturação.

---

---

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Responsável de Produto | | | |
| Fundador | | | |
| Advogado externo (recepção) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial, KAM-104. As 40 perguntas (20 de `E3`, 12 de `E2` §9, 1 de `E1`, 4 das linhas «Novas» de `../../08_Seguranca_Conformidade.md` §13, e 3 novas deste pacote), cada uma com os oito campos do critério 2; o mapa pergunta → decisão → ticket; a secção do que o KAM-105 precisa de resposta; os 16 itens assumidos por precaução jurídica com dono; as quatro divergências face à letra do critério 2; e o que o pacote não contém. O bloco G foi acrescentado à estrutura proposta nos «Detalhes Técnicos» do ticket, porque cinco das vinte perguntas de `E3` não cabiam nos seis blocos propostos. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-169: a pergunta **F-03** ganha a **quinta variante** — uma conversa real concreta **reescrita**, com os dados pessoais substituídos, que é a origem `t2_anonimizado` do KAM-040 e o que o pipeline de suporte T2 produz (`../../10_Onboarding_Governanca.md` §11.2). Não é a (i), porque a pseudonimização conserva a conversa; não é a (iv), porque não é inspiração. **O que a torna necessária é uma divergência medida entre dois textos do canon:** este pacote escrevia que um parecer contrário faz recuar para conjunto «inteiramente sintético», e o `../../../adr/ADR-L006-origem-do-golden-set.md` escrevia que cairia só o `real_consentido`, sobrando `sintetico` **e** `t2_anonimizado` — e os dois não podem valer, porque a diferença é se os casos de suporte T2 sobrevivem ao recuo. **Decisão do fundador a 2026-10-30, ao ser-lhe apresentada a divergência: a pergunta vai ao parecer em vez de ser decidida internamente**, porque é leitura jurídica e não decisão de produto; até haver resposta vale o recuo que já estava escrito, por ser o que está no canon. «Resposta pedida» passa a quatro→**cinco** variantes. De passagem, duas correcções no mesmo bloco: a glosa «dataset golden sintético» do «Por que importa» passa a nomear as três origens (era a quinta das cinco que o KAM-169 registou na linha 157 de `../../../dividas-documentais.md`, e fica paga), e a contagem de afirmações divergentes deixa de dizer «sete» — passa a escrever as **três** passagens (7 → 17 → 20), porque o que importa não é o número mas que nenhuma delas escondia nada: cada uma era o que o seu instrumento via. As 40 perguntas não mudam. | Equipa KAMBÁ |

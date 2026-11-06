# Tech Provider: dossiê de Business Verification, App Review e a análise de D5

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — dossiê dos seis passos do estatuto perante a Meta, guião do App Review e matriz de D5 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-102 (EPIC-10) |
| Estado | **NÃO VERIFICADO** — nenhum passo foi submetido: 0 submetidos, 0 aprovados, 0 prazos medidos (§2) |
| Fonte | [`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md) §1, §3, §8; `../../01` §4.1–4.3; `../../10` §6.1; `../../00` §13.3; [`Meta_Perguntas.md`](Meta_Perguntas.md) §1 (Q8, Q9, Q15), §3.4; [`../E5_Modulos_Entrada.md`](../E5_Modulos_Entrada.md) §3 |
| Dono | **Fundador** — único a submeter em nome da entidade legal, a gravar e a pedir cotações (§1) |
| Documento-fonte | [`../E1_Meta_WhatsApp.md`](../E1_Meta_WhatsApp.md) §3, §8; `../../01` §4.1–4.3; `../../10` §6; `../../00` §13.3 (D5, D9); ADR-001; `14` §3A Regra 3, §6; Carta §4.2 |
| Relacionados | [`Meta_Perguntas.md`](Meta_Perguntas.md) (Q8, Q9, Q11, Q15 alimentam D5), [`Seguimento_APD.md`](Seguimento_APD.md) (D9, quem paga em USD), [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) (precedente da tabela de cotações), [`GoLive_Gate.md`](GoLive_Gate.md) |

> **O que este ficheiro entrega, e o que devolve — à cabeça, para não se ler ao
> contrário.** Entrega o **dossiê** dos seis passos com as colunas que a medição
> precisa, a lista de documentos por passo, as **descrições e o *storyboard***
> do App Review, o **guião de ensaio** do protótipo, a **lista de permissões**
> do critério 9, a **matriz de D5** com o lugar das duas cotações formais, a
> **regra de falha da semana 6** como lista de verificação, e os **limites de
> *onboarding*** com o estado que a Q9 tem hoje.
>
> **Devolve seis actos, e o credor de todos eles é o fundador:** submeter a
> Business Verification, submeter o App Review, **gravar os dois vídeos**,
> confirmar o estatuto no painel, obter as cotações de BSP e assinar a decisão
> da semana 6. Nenhum é do executor, e o §1 diz porquê, um a um.
>
> **Nenhuma data de submissão está escrita, nenhum prazo está medido e nenhum
> estatuto está declarado.** As folhas nascem vazias — é assim que devem nascer,
> porque uma data escrita antes de a submissão acontecer é uma afirmação falsa
> sobre o mundo, e um prazo «medido» sem submissão é o prazo NÃO VERIFICADO de
> E1 §3 a mudar de nome.

---

## 1. A quem pertence cada acto

A fronteira não é uma preferência de método: o bloco do ticket fixa-a nos
«Detalhes Técnicos» — «o Claude Code prepara a lista de documentos, o guião e o
*storyboard* dos vídeos, a aplicação mínima de demonstração (…) e o modelo de
cotação a BSPs; **as submissões, a gravação dos vídeos e as chamadas são
humanas**».

| # | Acto | Porque não é do executor | Credor |
|---|---|---|---|
| 1 | **Submeter a Business Verification** | Submete-se em nome da entidade legal, com documentos da empresa que não vivem no repositório | **Fundador** (representante da entidade legal) |
| 2 | **Submeter o App Review** | Idem, e depende do passo 1 aprovado (ordem CONFIRMADA, E1 §3) | **Fundador** |
| 3 | **Gravar os vídeos** | São gravações de ecrã de uma conta real a enviar uma mensagem real; a Meta exige ecrã gravado e recusa capturas (CONFIRMADO, E1 §3) | **Fundador**, com guião e *storyboard* do §4.3 |
| 4 | **Confirmar o estatuto no painel e o acesso a *Direct Support*** | É uma leitura do painel da app, com captura datada, feita por quem tem a conta | **Fundador** |
| 5 | **Obter as ≥ 2 cotações formais de BSP** | Pedir uma cotação é contacto comercial em nome da empresa; o pedido está redigido (Q15) e o canal é do próprio BSP | **Fundador**, por proposta do **Responsável de Produto** |
| 6 | **Assinar a decisão da semana 6** | A decisão da semana 6 muda o canal do produto, e o `14` §6 chama-lhe pivô. **A Carta §4.2 não nomeia quem assina D5**: dá-lhe dono **Produto** e, na coluna da escalada, só «Sem Tech Provider à semana 6: pára o canal (KAM-016)». O que fica aqui é a assinatura de quem representa a entidade legal nos actos 1 a 5, que são os que esta decisão interrompe — e **registar** D5 é do Responsável de Produto, como o §6.5 diz | **Fundador** (assinatura do pivô), **Responsável de Produto** (registo) |

**Aprovar as descrições e o *storyboard*** antes de gravar é do **Responsável de
Produto**, que é o que o critério 3 pede por escrito.

---

## 2. Os seis passos: folha de seguimento (critério 1)

Uma linha por passo, na ordem em que a Meta os impõe. Estados:
**`por submeter`** → `submetido` → `em apreciação` → `aprovado` ou `rejeitado`.

> **A folha nasce em `por submeter`, que é o estado anterior aos quatro, e por
> isso tem coluna própria.** O critério 1 pede «data de submissão, data de
> resposta, **resultado**, motivo de rejeição, dias úteis decorridos» — cinco
> colunas que só existem depois de alguém submeter. `por submeter` **não é um
> resultado**, e escrevê-lo na coluna «Resultado» era dizer o contrário disto
> na linha seguinte. Daí a coluna **«Estado»** ao lado da «Resultado», que é
> exactamente o que o precedente faz: o [`Seguimento_APD.md`](Seguimento_APD.md)
> §1 tem as duas colunas separadas, com `por submeter` no Estado e o Resultado
> em branco.

| # | Passo | Pré-requisito | **Estado** | Data de submissão | Data de resposta | Resultado | Motivo de rejeição | Dias úteis decorridos | Dono |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Entidade legal e portfólio Meta Business** | Entidade escolhida (input de D9) | **por submeter** | | | | | | Fundador |
| 2 | **Business Verification da KAMBÁ** | Passo 1 | **por submeter** | | | | | | Fundador |
| 3 | **App Meta tipo Business com o caso de uso WhatsApp** | Passo 1 | **por submeter** | | | | | | Fundador |
| 4a | **App Review — `whatsapp_business_messaging`** (*Advanced access*) | Passo 2 **aprovado** e passo 3 | **por submeter** | | | | | | Fundador |
| 4b | **App Review — `whatsapp_business_management`** (*Advanced access*) | Passo 2 **aprovado** e passo 3 | **por submeter** | | | | | | Fundador |
| 4c | **App Review — `pages_manage_posts`** (*Advanced access*) | Passo 2 **aprovado** e passo 3; ver §4.1 | **por submeter** | | | | | | Fundador |
| 4d | **App Review — `instagram_business_content_publish`** (*Advanced access*) | Passo 2 **aprovado** e passo 3; ver §4.1 | **por submeter** | | | | | | Fundador |
| 5 | ***Access Verification*** | Passos 2 e 4 aprovados | **por submeter** | | | | | | Fundador |
| 6 | **Método de pagamento** (Billing Hub do cliente) | Passo 4 aprovado; por cliente, não por plataforma | **por submeter** | | | | | | Responsável de Produto |

> **O passo 4 vem desdobrado por permissão, e é por necessidade.** O critério 1
> nomeia-o «App Review **por permissão**», e a lista de verificação do §10.1 mede
> a aprovação de `whatsapp_business_messaging` e de `whatsapp_business_management`
> **separadamente** — uma linha única com uma célula de resultado não podia
> responder a essas duas perguntas. As linhas **4c** e **4d** existem porque o
> critério 9 manda pedir as duas permissões de redes no mesmo ciclo, e ficam com
> a remissão para o §4.1, onde está o que ninguém confirmou sobre elas.

| Contagem | Valor |
|---|---|
| Passos na folha | **6** (o 4 desdobrado em **4** linhas, uma por permissão) |
| Submetidos | **0** |
| Aprovados | **0** |
| Rejeitados | **0** |
| Prazos medidos | **0** |

### 2.1 A ordem não é escolha nossa

Duas restrições CONFIRMADAS em E1 §3, e que decidem o caminho crítico inteiro:

- A **Business Verification vem antes do App Review** («verificar o negócio
  antes do App Review»). O passo 4 não arranca com o passo 2 em apreciação.
- O limite de **10 novos clientes por 7 dias** sobe para **200** só com
  Business Verification **e** App Review **e** *Access Verification* — os três.

Daí a leitura que o `14` §3A Regra 3 já faz e que vale repetir: o passo 2 é o
**primeiro passo com prazo de terceiro** — o passo 1 é nosso e precede-o — e é o
que bloqueia tudo o que vem depois, o que o torna o item de espera externa mais
perigoso do epic. Arranca na semana 1 por essa razão, não por conveniência de
calendário. **Não é o único com prazo NÃO VERIFICADO:** o passo 5, a *Access
Verification*, também o tem (§2.3 e §8.2), e com um agravante — do passo 2
sabe-se o que se submete, e do passo 5 não se sabe sequer o processo.

### 2.2 Dias úteis: a regra de contagem, escrita antes de haver o que contar

Fixada aqui para que a coluna não se preencha com duas réguas diferentes:

| Elemento | Regra |
|---|---|
| Dia 0 | O dia da submissão, não contado |
| Dias contados | Segunda a sexta-feira |
| Sábados e domingos | Não contados |
| Feriados | **Não descontados**, e a razão é substantiva: a Meta responde num calendário que não é o angolano, e descontar um feriado de Angola a um prazo da Meta mediria a coisa errada |
| Fuso | **`Africa/Luanda`** para a data de registo, que é **apresentação** — o dicionário canónico §2 fixa `timestamptz` em UTC para armazenamento e «apresentação em `Africa/Luanda`», e uma data escrita numa célula deste ficheiro é apresentação. **É material, não formalidade:** Luanda é UTC+1, pelo que uma submissão feita depois das 23:00 locais cai no dia UTC seguinte — e numa sexta-feira isso atravessa um fim de semana inteiro na contagem. São as «duas réguas» que este §2.2 existe para evitar |

### 2.3 O prazo da Business Verification: **NÃO MEDIDO**, e porquê

O critério 1 diz que esta folha «substitui o prazo NÃO VERIFICADO da Business
Verification por um valor medido». **Não substitui, e não pode:** medir exige
submeter, submeter é do fundador (§1, acto 1), e nenhuma submissão aconteceu.

| Item | Valor | Estado |
|---|---|---|
| Prazo da Business Verification (documentação da Meta) | — | **NÃO VERIFICADO**, mantido de E1 §3 |
| Prazo da Business Verification (medido pela KAMBÁ) | — | **NÃO MEDIDO** — credor: **fundador** (§12, item 1) |
| Prazo do App Review (número da Meta) | «cerca de 24 horas» | **CONFIRMADO** como *número da Meta*, E1 §3; o prazo real depende de rejeições, e E1 manda planear **1 a 2 semanas** |
| Prazo da *Access Verification* | — | **NÃO VERIFICADO** — a página nomeia o passo e não o detalha ([`Meta_Perguntas.md`](Meta_Perguntas.md) §3.4) |
| Verificação conduzida por **Select ou Premier** Solution Partner em nome do cliente | «*turnaround* muito mais rápido» | **NÃO VERIFICADO**, e herda-se assim: a linha de E1 §3 que a carrega tem estado **NÃO VERIFICADO (prazo)** e a sua segunda fonte, `partner-led-business-verification`, está declarada **«listada, não lida»**. **Sem número**, e por isso não entra em nenhuma conta. O qualificador **Select/Premier** é da fonte e fica: a afirmação não vale para qualquer Solution Partner |
| Prazo de Business Verification visto por terceiros | «dias a semanas», com um caso de fórum a «10 dias em revisão» | **INDÍCIO** — e é o único indício que existe no conjunto para este prazo. A fonte é `../E5_Modulos_Entrada.md` §3, que o declara «resultado de pesquisa, **sem fonte oficial**», e o seu âmbito é a Business Verification em geral (Instagram e Páginas incluídos), **não** a do WhatsApp em particular, que a mesma secção dá como **sem prazo** por E1. Serve para planear, **não** para prometer, e **não** preenche a célula do valor medido |

**Escrever «cerca de 24 h» na coluna dos dias úteis do passo 4 seria o defeito
típico desta casa:** é a média que a Meta publica, não uma medição nossa, e o
próprio E1 anexa-lhe a ressalva. A coluna fica vazia até haver submissão.

---

## 3. Documentos por passo

A lista do que se junta. **A aceitação de documentos angolanos é NÃO
VERIFICADA** (E1 §3) e é exactamente o que a **Q8** de
[`Meta_Perguntas.md`](Meta_Perguntas.md) §1 pergunta — pelo que esta lista é o
que a KAMBÁ **propõe** apresentar, e não o que a Meta confirmou aceitar.

| Passo | Documento ou elemento | Estado da aceitação | Onde vive |
|---|---|---|---|
| 1 | Nome legal, endereço e sítio da entidade, coincidentes com os documentos | — | Portfólio Meta Business |
| 2 | Alvará comercial | **NÃO VERIFICADO** (Q8) | Arquivo controlado, **fora do repositório** |
| 2 | NIF (número de contribuinte) | **NÃO VERIFICADO** (Q8) | Arquivo controlado, fora do repositório |
| 2 | Certidão do registo comercial | **NÃO VERIFICADO** (Q8) | Arquivo controlado, fora do repositório |
| 2 | Comprovativo de endereço da entidade | **NÃO VERIFICADO** (Q8) | Arquivo controlado, fora do repositório |
| 3 | App Meta tipo *Business* com o caso de uso WhatsApp, ligada ao portfólio | **CONFIRMADO** como requisito — E1 §3 dá «app Meta com caso de uso WhatsApp e portfólio de negócio» e **não** nomeia o tipo; quem fixa o **tipo *Business*** é o `../../01` §4.2 | Painel da app |
| 4 | Descrição escrita **por permissão** | **CONFIRMADO** como obrigatória, E1 §3 | §4.2 deste ficheiro (proposta, por aprovar) |
| 4 | Gravações de ecrã | **CONFIRMADO**: ecrã gravado, **nunca captura**, E1 §3 | *Storyboard* no §4.3; ficheiros fora do repositório |
| 5 | Requisitos da *Access Verification* | **NÃO VERIFICADO** (Q9) | — |
| 6 | Cartão do cliente-PME em moeda aceite pela Meta | **CONFIRMADO**: o cliente adiciona o seu método e a Meta factura-o, E1 §3; `../../10` §6.1 | Billing Hub do cliente |

> **Os documentos da empresa não entram no repositório, e não é uma precaução
> genérica.** É a caixa 3 da *Definition of Done* do ticket: «documentos da
> empresa em arquivo controlado, fora do repositório». O repositório é público.

### 3.1 A Business Verification dos clientes é outra coisa

Confusão fácil e caríssima, por isso fica separada: a Business Verification do
**passo 2** é da KAMBÁ e é pré-requisito do App Review. A Business Verification
**de cada PME cliente** é outra, e E1 §3 diz para que serve — subir o limite de
mensagens (2.000/dia), o número de números e a *Official Business Account*. O
`../../10` §6.1 regista o mesmo pelo lado do portfólio: 250 contactos novos por
dia e 2 números sem ela; 2.000 e 20 com ela.

A pergunta sobre o caminho das PMEs — muitas informais — é a **segunda metade da
Q8**, e a resposta muda o desenho do *onboarding*, não este dossiê.

---

## 4. App Review: permissões, descrições e *storyboard*

### 4.1 A lista de permissões (critérios 3 e 9)

| # | Permissão | Acesso pedido | Porquê | Estado do requisito |
|---|---|---|---|---|
| 1 | `whatsapp_business_messaging` | *Advanced access* | Enviar e receber mensagens no número do cliente | **CONFIRMADO** como obrigatória para Tech Provider — E1 §3 |
| 2 | `whatsapp_business_management` | *Advanced access* | Criar e gerir *templates*, ler a conta | **CONFIRMADO** como obrigatória para Tech Provider, E1 §3 |
| 3 | `pages_manage_posts` | *Advanced access* | Publicação futura em Páginas Facebook (Social AI) | Pedido **no mesmo ciclo** por critério 9 e pelo «gancho obrigatório» de `../E5_Modulos_Entrada.md` §3 («pedido de permissões (…) na mesma submissão do Tech Provider»); a publicação automática é **Diferida** (D13). **Não consta de E1** |
| 4 | `instagram_business_content_publish` | *Advanced access* | Publicação futura em Instagram (Social AI) | Idem. **Não consta de E1** |

**Nenhuma das permissões de redes está em E1.** As linhas 1 e 2 vêm de E1 §3; as
linhas 3 e 4 vêm do critério 9 deste ticket e do `../E5_Modulos_Entrada.md` §3,
que é a secção que as estuda. Dizer «E1 §3» ao lado delas era atribuir a E1 uma
coisa que ele não contém.

**As acompanhantes que o `../E5_Modulos_Entrada.md` §3 nomeia e o critério 9
não:** `pages_read_engagement` (que o E5 §3 dá como CONFIRMADA ao lado de
`pages_manage_posts`, com `publish_video` para vídeo) e, na via de *login* do
Instagram, `instagram_business_basic`. **Não as acrescento à lista pedida**: o
critério 9 nomeia duas, acrescentar permissões a um pedido de App Review é
alterar o pedido, e isso é decisão de quem o submete. Ficam **registadas aqui**
para que a decisão se tome com elas à vista — §12, item 5.

#### Duas coisas que ninguém confirmou, e que decidem este ciclo

| # | Pergunta | Estado | Via |
|---|---|---|---|
| 1 | As permissões 3 e 4 podem ser pedidas **na mesma app e na mesma Business Verification** que o Tech Provider do WhatsApp? | **NÃO VERIFICADO** | É literalmente a pergunta 1 da lista **«Para a Meta (por escrito)»** de [`../E5_Modulos_Entrada.md`](../E5_Modulos_Entrada.md), que vive na secção final **«Perguntas para o advogado e para a Meta»** e **não** no §3 — o §3 é «Publicação em redes sociais por API» e não tem lista numerada |
| 2 | A Meta concede *Advanced access* a uma permissão cujo fluxo **não existe para gravar**, porque está Diferido por D13? | **NÃO VERIFICADO** | A resposta ao próprio App Review; não encontrámos fonte que o diga |

> **A segunda é a que pode fazer este ciclo falhar por inteiro, e é um conflito
> real entre dois critérios do mesmo ticket.** O critério 3 exige «protótipo
> funcional (…), 2 vídeos por permissão e descrição por permissão»; o critério 9
> manda pedir as permissões 3 e 4 «mesmo que a publicação automática fique
> Diferida (D13)». Juntos, pedem uma gravação de um fluxo que o ADR-020 proíbe
> construir no Piloto («sem publicação automática em redes»). **Não resolvo o
> conflito e não o escondo:** está medido, e a decisão — pedir as quatro agora e
> aceitar o risco de rejeição parcial, ou pedir as duas do WhatsApp primeiro — é
> do **Responsável de Produto** (§12, item 4). Uma rejeição no mesmo ciclo
> consome uma das três submissões do §4.4, e é por isso que a escolha não é
> cosmética.

### 4.2 Descrição escrita por permissão (proposta, por aprovar)

Uma por permissão, como E1 §3 confirma ser obrigatório. **Redigidas aqui;
aprovação do Responsável de Produto por critério 3.** Sem nomes de pessoas, sem
números de telefone e sem segredos — o repositório é público.

**Em EN e PT, e o EN é o que se submete.** O formulário vai à Meta, cujas
páginas E1 §3 cita em inglês, e o precedente da casa é o critério 1 do KAM-101:
texto EN redigido no ticket, PT ao lado. O critério 3 não exige inglês; escrever
só português obrigava quem submete a traduzir, e **uma tradução feita no momento
da submissão é texto que ninguém reviu**.

| Permissão | Descrição proposta — **EN** (o texto que se submete) | Descrição proposta — **PT** |
|---|---|---|
| `whatsapp_business_messaging` | «KAMBÁ is a conversational commerce platform that lets small and medium businesses in Angola serve customers, present their catalogue and record orders over WhatsApp. With this permission the platform sends and receives messages on the business customer's own phone number; the business customer owns the account and the number. The business customer grants access through Embedded Signup and keeps full access to WhatsApp Manager. No message is sent before the business customer has granted access, and the platform does not send unsolicited marketing.» | «A KAMBÁ é uma plataforma de comércio conversacional que permite a pequenas e médias empresas em Angola atender clientes, apresentar catálogo e registar pedidos por WhatsApp. Com esta permissão a plataforma envia e recebe mensagens no número da própria empresa cliente, que é a dona da conta e do número. A empresa cliente autoriza o acesso pelo Embedded Signup e mantém acesso total ao WhatsApp Manager. Nenhuma mensagem é enviada sem que a empresa cliente tenha concedido o acesso, e a plataforma não envia marketing não solicitado.» |
| `whatsapp_business_management` | «With this permission the platform creates and submits message templates on behalf of the business customer — order confirmations, pickup reminders and availability notices — and reads the account state in order to show the business its number quality and current limits. Each template is initiated by the business customer in the platform's dashboard. The platform does not change asset ownership: the account, the number, the templates and the catalogue belong to the business customer.» | «Com esta permissão a plataforma cria e submete *templates* de mensagem em nome da empresa cliente — confirmações de pedido, lembretes de recolha e avisos de disponibilidade — e lê o estado da conta para apresentar à empresa a qualidade do número e os limites em vigor. A criação de cada *template* é iniciada pela empresa cliente no painel da plataforma. A plataforma não altera a propriedade dos activos: a conta, o número, os *templates* e o catálogo são da empresa cliente.» |
| `pages_manage_posts` | «At the business customer's request, the platform generates content for the business's own Facebook Page (edited product photograph, caption and artwork). **In the pilot the content is delivered for the business owner to publish manually**, and this permission request prepares assisted publishing in a later phase, always with the owner's explicit approval before anything is published.» | «A plataforma gera, a pedido da empresa cliente, peças de conteúdo para a Página Facebook da própria empresa (fotografia de produto tratada, legenda e artes). **No Piloto a entrega é para publicação manual pelo dono da empresa**, e o pedido desta permissão prepara a publicação assistida numa fase posterior, sempre com aprovação explícita do dono antes de qualquer publicação.» |
| `instagram_business_content_publish` | «The same for the business customer's Instagram professional account: the platform generates the content, the business owner approves it, and assisted publishing is left for a later phase. In the pilot the platform delivers the content and does not publish.» | «O mesmo para a conta profissional de Instagram da empresa cliente: a plataforma gera a peça, o dono da empresa aprova, e a publicação assistida fica para uma fase posterior. No Piloto a plataforma entrega a peça e não publica.» |

> **As duas últimas dizem «fica para uma fase posterior» de propósito.** É o que
> `../E5_Modulos_Entrada.md` §3 conclui e o que o ADR-020 fixa — regra 3, «sem
> publicação automática em redes». Escrever à Meta uma descrição que dá a
> publicação automática como activa no Piloto seria descrever um produto que não
> existe.

### 4.3 *Storyboard* das gravações

**Duas leituras do mesmo requisito, e preparo para a mais exigente.** E1 §3, que
é a fonte primária, diz «vídeo 1 (mensagem criada na app e recebida no cliente
WhatsApp), vídeo 2 (criação de *template*); **uma gravação por permissão**» — o
que se lê como uma gravação para cada uma das duas permissões. O critério 3
deste ticket diz «**2 vídeos por permissão**», o que dá quatro.

**E há uma terceira formulação, que é canon e não resolve a questão:** o
`../../01` §4.2 escreve «**2 vídeos (mensagem, template) por permissão** |
CONFIRMADO». Repete a redacção do critério 3 **e** acrescenta o parêntesis que
identifica os dois vídeos como o da mensagem e o do *template* — que é a leitura
de E1, uma gravação por permissão. Isto é: as três fontes usam duas redacções e
**nenhuma diz quantos ficheiros se submetem**. A divergência está medida e **não
a decido**: §12, item 3. O *storyboard* abaixo tem **quatro gravações**, porque
satisfazer a leitura estrita satisfaz as três, e porque o custo de gravar duas a
mais é muito menor do que o de uma rejeição.

| Gravação | Permissão | O que tem de aparecer no ecrã, por ordem | Duração-alvo (**escolha nossa, sem fonte**) |
|---|---|---|---|
| **A1** | `whatsapp_business_messaging` | (1) painel da plataforma com a conta de teste identificada; (2) composição de uma mensagem a um destinatário de teste; (3) envio; (4) a **mesma** mensagem recebida no cliente WhatsApp do destinatário, visível no mesmo vídeo | 60–90 s |
| **A2** | `whatsapp_business_messaging` | (1) mensagem **recebida** do destinatário de teste a chegar ao painel; (2) resposta enviada do painel; (3) resposta recebida no cliente WhatsApp. Prova o sentido inverso, que a A1 não prova | 60–90 s |
| **B1** | `whatsapp_business_management` | (1) painel ou WhatsApp Manager com a conta de teste; (2) criação de um *template* de confirmação de pedido, com o corpo visível; (3) submissão; (4) o *template* na lista com o seu estado | 60–90 s |
| **B2** | `whatsapp_business_management` | (1) leitura do estado da conta de teste — qualidade do número e limite em vigor — apresentada na plataforma; (2) o mesmo valor no WhatsApp Manager, para mostrar que é leitura da API e não texto fixo | 45–60 s |

**Regras de gravação, todas de E1 §3 (CONFIRMADO):** ecrã gravado, **nunca**
captura de ecrã; uma gravação por permissão, no mínimo; descrição escrita
obrigatória por permissão. E uma regra nossa, que é a caixa 3 da *Definition of
Done*: **nenhuma gravação mostra um número de telefone real, um nome de pessoa,
um token ou o App Secret** — a conta de teste e o destinatário de teste são de
teste, e qualquer painel com segredos à vista fica fora do enquadramento.

**E para as permissões 3 e 4 há *storyboard*, do único fluxo que existe.** A
primeira versão deste §4.3 deixava-as sem gravação e chamava à ausência «o
achado» — o que era meio raciocínio. É verdade que **não há publicação
automática para gravar**: o ADR-020 proíbe-a no Piloto (regra 3) e a D13
difere-a. Mas **há** o fluxo que as duas descrições do §4.2 descrevem e que o
`../E5_Modulos_Entrada.md` §3 permite — gerar a peça, o dono aprovar, e a peça
ser **entregue para publicação manual** (o `ManualDelivery` do mesmo §3). Redigir
descrições para essas permissões e recusar-lhes *storyboard* era uma assimetria
sem razão. O que continua **NÃO VERIFICADO** é se a Meta concede *Advanced
access* com base numa demonstração de entrega manual — é a pergunta 2 do §4.1, e
é ela que decide se estas duas gravações se submetem ou se as permissões esperam.

| Gravação | Permissão | O que tem de aparecer no ecrã, por ordem | Duração-alvo (**escolha nossa, sem fonte**) |
|---|---|---|---|
| **C1** | `pages_manage_posts` | (1) painel da plataforma com a peça gerada para a Página da empresa de teste — fotografia tratada e legenda; (2) o ecrã de **aprovação do dono**; (3) a peça entregue como ficheiro e texto, para publicação manual; (4) o estado da peça a dizer que **não** foi publicada pela plataforma | 60–90 s |
| **D1** | `instagram_business_content_publish` | O mesmo para a conta profissional de Instagram da empresa de teste, com o mesmo passo de aprovação e a mesma entrega para publicação manual | 60–90 s |

| Contagem | Valor |
|---|---|
| Gravações no *storyboard* | **6** — quatro das duas permissões do WhatsApp, duas das duas de redes |
| Gravações feitas | **0** — credor: **fundador** (§1, acto 3) |
| Descrições redigidas | **4**, em EN e PT |
| Descrições aprovadas | **0** — credor: **Responsável de Produto** |

> **As gravações C1 e D1 demonstram o produto que existe, não o que se pede.** É
> uma escolha e fica declarada: mostram a entrega para publicação manual, que é o
> que o Piloto faz, enquanto a permissão pedida serve a publicação assistida de
> uma fase posterior. **Se a Meta exigir a demonstração do acto de publicar**,
> nenhuma destas duas gravações serve e a decisão passa a ser a do §12, item 4:
> pedir as duas agora e aceitar o risco de rejeição parcial, ou pedir primeiro as
> duas do WhatsApp. Gravar o acto de publicar **não é opção**, porque o ADR-020 o
> proíbe no Piloto.

### 4.4 Submissões: o contador das três

O critério 3 fixa «no máximo 3 submissões antes de escalar». Fica como contador,
não como intenção.

| Submissão | Data | Resultado | Motivo de rejeição | O que se corrigiu |
|---|---|---|---|---|
| 1.ª | | **não submetida** | | |
| 2.ª | | — | | |
| 3.ª | | — | | |

| Regra | Valor |
|---|---|
| Submissões usadas | **0 de 3** |
| À 3.ª rejeição | **Escalar**, e a via é *Direct Support* — que **só existe depois da aprovação de Tech Provider** (E1 §3). Antes dela, o escalamento é pelo mesmo canal da submissão, e qual é esse canal é **NÃO VERIFICADO**. **A fonte é uma transposição, e declara-se como tal:** o item 2 do §7 de [`Meta_Perguntas.md`](Meta_Perguntas.md) diz que é NÃO VERIFICADO qual é o canal **para enviar as 15 perguntas** antes da aprovação de Tech Provider. O canal de escalada de um App Review é outro acto; o que se transpõe é a razão — antes da aprovação não há canal estabelecido com a Meta — e não a conclusão |

> **A armadilha está escrita porque é circular:** o canal de escalada do App
> Review é o *Direct Support*, que é um atributo do estatuto que o App Review
> concede. Quem contar com ele para desbloquear uma rejeição descobre-o na
> terceira tentativa.

---

## 5. Protótipo de demonstração: guião de ensaio

Os «Testes Requeridos» pedem «ensaio da aplicação de demonstração em conta de
teste antes de gravar os vídeos». **O ensaio não correu e não podia correr
aqui:** exige uma conta de teste da Meta, um número de teste e um token, e
nenhum dos três existe neste repositório nem deve existir. Credor: **fundador**
(§12, item 2).

**O que dispensa escrever código, e é CONFIRMADO:** E1 §3 regista que «pode
usar-se a cURL do API Setup e o WhatsApp Manager no lugar da app». Logo o
protótipo mínimo do critério 3 cumpre-se com o painel da Meta e as chamadas que
ele próprio gera — e o ES v4 em código é **KAM-016**, não este ticket.

| # | Passo do ensaio | Onde | O que se confirma |
|---|---|---|---|
| 1 | Criar a app de teste e o número de teste no API Setup | Painel da app | Que a conta de teste existe e o número está activo |
| 2 | Adicionar o destinatário de teste à lista de destinatários permitidos | API Setup | Que o envio não falha por destinatário não autorizado — a causa mais comum de um ensaio falhado |
| 3 | Enviar a mensagem de modelo gerada pelo API Setup | cURL do API Setup | Que a chamada devolve um identificador de mensagem, e que ela chega ao cliente WhatsApp (gravação **A1**) |
| 4 | Responder do cliente WhatsApp e ver a mensagem chegar | Cliente WhatsApp + painel | Que o sentido de entrada funciona (gravação **A2**) |
| 5 | Criar um *template* de confirmação de pedido | WhatsApp Manager | Que a criação funciona e que o estado do *template* é legível (gravação **B1**) |
| 6 | Ler a qualidade do número e o limite em vigor | WhatsApp Manager + API | Que os dois concordam (gravação **B2**) |
| 7 | Repetir o passo 3 **depois** de o *template* ser aprovado | cURL | Que o envio por *template* funciona, e não só a mensagem de modelo |

**Três avisos que poupam uma repetição do ensaio:**

- **Contas criadas por *developer app* não podem ser integradas pelo Embedded
  Signup** (CONFIRMADO, E1 §3). A conta de teste serve para o ensaio e para as
  gravações; **não** serve como primeira PME integrada.
- **O modelo *On-Behalf-Of* está descontinuado** (CONFIRMADO, E1 §3): o cliente
  é sempre dono dos activos. Um ensaio desenhado como «a nossa conta em nome do
  cliente» prova o modelo errado.
- **Nenhum token, `config_id` ou App Secret entra num comando que fique escrito
  aqui.** Os comandos do ensaio copiam-se do API Setup, que já os traz
  preenchidos no painel, e ficam no painel.

---

## 6. D5: a matriz de opções e o lugar das cotações (critério 5)

### 6.1 O que D5 decide, e o que o canon já fixou

> **A primeira coisa a dizer sobre D5 é que ela não parte de uma folha em
> branco — e a segunda é que continua aberta.** O **ADR-001**, canon e em vigor,
> fixa «Cloud API oficial + coexistência; **Tech Provider**; Embedded Signup v4»,
> e o que ele bane é o **gateway não-oficial**, não o BSP oficial. O `../../01`
> §4.1 repete o Tech Provider como **decisão de arranque** e dá o BSP como
> «alternativa só se Tech Provider falhar», com «cotação formal a 2 BSPs **como
> plano B**». E o `14` §6 inscreve «BSP parceiro» como **pivô escrito**.
>
> **Logo exercer o plano B não é substituir um ADR: é executar um caminho que o
> canon já escreveu** — o `../../00` §13.3 mantém D5 nas decisões **abertas**,
> com o assunto «Tech Provider directo *vs* BSP» e prazo «semana 1–4», e a Carta
> §4.2 dá-a **ABERTA** com dono Produto. Se a escolha de MPS ou BSP obriga a
> **emendar** a redacção do ADR-001, isso é pergunta para o Arquitecto de
> Plataforma e para o fundador, e **não** se decide neste ficheiro (§12, item 17).
> O que esta matriz entrega é a comparação que torna a escolha uma leitura — e a
> regra de falha do §10 é o caminho escrito para a accionar.
>
> *(Uma versão anterior deste parágrafo dizia que escolher MPS ou BSP «é
> substituir um ADR em vigor». Era endurecer o canon: a revisão adversarial
> mostrou-o com quatro fontes, e fica registado para não voltar.)*

| Opção | Factos, com estado | Consequência | O que a KAMBÁ paga |
|---|---|---|---|
| **Tech Provider directo** (fixada pelo ADR-001) | **CONFIRMADO** (E1 §3, §8): sem *credit line*; o cliente adiciona o seu método de pagamento e a Meta factura-o; a plataforma factura o seu serviço; tem **Direct Support**; **basta Tech Provider para a coexistência** — não é preciso ser Solution Partner | Controlo total do canal; o Embedded Signup e a coexistência ficam disponíveis | A Business Verification, o App Review e o suporte próprio. **E a barreira do cartão**: a PME precisa de cartão em moeda aceite pela Meta (§7) |
| **MPS — Multi-Partner Solution com um Solution Partner** | **CONFIRMADO** (E1 §8): um Tech Provider pode aliar-se a um Solution Partner que partilhe a *credit line*. **NÃO VERIFICADO**: se algum Solution Partner factura em Kwanzas, e em que condições | Resolve a facturação em moeda local **se** houver parceiro que o faça; mantém o estatuto de Tech Provider | Dependência de um parceiro, e a parte da margem que ele levar. **Ver o §11**: contratar um Solution Provider é exactamente a condição que a cláusula 4.7 nomeia |
| **BSP / Solution Partner como intermediário** | **CONFIRMADO** (E1 §3): o Solution Partner tem *credit line* e factura o cliente, mas o processo é «demorado» — **sem prazo documentado**. **INDÍCIO** (E1 §8): taxa mensal e/ou *markup* por mensagem; **nenhuma tarifa específica para Angola encontrada** | Dispensa a Business Verification e o App Review da KAMBÁ, e a *credit line* resolve quem paga | A taxa e o *markup*, mais a perda de controlo do canal. O `../../01` §4.1 nota que a abstracção `ChannelAdapter` mantém a troca barata — o que limita o custo de mudar, não o custo de operar |

**Os preços de BSP que E1 §8 cita são INDÍCIO e não entram em nenhuma conta
deste ficheiro.** É o que os «Detalhes Técnicos» do ticket mandam: «só contam as
cotações recebidas por escrito». Reproduzi-los numa célula de decisão era dar
estado de facto a um resumo de agregador de preços.

### 6.2 As duas cotações formais: a tabela nasce vazia

Mínimo de **2**, uma delas com presença em África (critério 5). Uma célula só se
preenche com documento de origem; «sem resposta» é um valor legítimo, uma
estimativa não é.

| # | BSP | Presença em África (S/N) | Taxa mensal | *Markup* por mensagem | Suporte a coexistência (S/N) | Suporte a BSUID (S/N) | Tarifa final para +244, por categoria | Moeda de facturação | Factura em Kwanzas (S/N) | Data do pedido | Data da resposta | Documento de origem |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | | | |
| 2 | | | | | | | | | | | | |
| 3 (suplente) | | | | | | | | | | | | |

| Contagem | Valor |
|---|---|
| Cotações pedidas | **0** |
| Cotações recebidas | **0** |
| Das recebidas, com presença em África | **0** |
| Mínimo exigido pelo critério 5 | **2** |

> **Porque é que «suporte a BSUID» é coluna e não detalhe.** E1 §3 regista como
> CONFIRMADO que os *business-scoped user IDs* são **obrigatórios para todos os
> parceiros** e que **o telefone pode deixar de vir no webhook**. Um BSP que não
> os suporte não é mais barato: é inviável, porque a chave do cliente final deixa
> de chegar. A coluna existe para que a resposta seja eliminatória e não uma nota
> de rodapé.

### 6.3 O pedido de cotação: a Q15, mais as três perguntas que ela não faz

O corpo do pedido existe, está redigido em EN e PT, e é a **Q15** de
[`Meta_Perguntas.md`](Meta_Perguntas.md) §1 — a única das quinze que **não vai à
Meta**: vai ao contacto comercial de cada BSP. Pede quatro coisas: *markup* por
mensagem, taxa mensal, suporte a coexistência e a BSUID, e a tarifa final
entregue para destinatários com indicativo +244, por categoria de mensagem.

**Mas a Q15 não cobre o §6.2 todo, e os «Detalhes Técnicos» deste ticket mandam
entregar «o modelo de cotação a BSPs».** Faltam-lhe **três** campos da tabela, e
não são enfeite: são exactamente aquilo de que dependem a opção MPS do §6.1 e o
modelo de facturação que o critério 5 exige. Ficam aqui como **acrescento** ao
corpo da Q15, e não como reescrita dela — reescrevê-la criava duas versões da
mesma pergunta, e a que fosse enviada deixava a outra a mentir.

| # | Campo do §6.2 que a Q15 **não** pede | Pergunta a acrescentar — **EN** | Porque é preciso |
|---|---|---|---|
| 1 | **Presença em África** | «Do you have a legal entity, a commercial team or a support presence in Africa, and in which countries?» | O critério 5 exige que **uma** das duas cotações seja de um BSP com presença em África, e sem a pergunta a condição não se verifica |
| 2 | **Moeda de facturação** | «In which currencies do you invoice, and can you invoice a platform established in Angola?» | Decide se a opção BSP resolve de facto o problema que a motiva |
| 3 | **Factura em Kwanzas** | «Can you invoice our business customers in Angolan Kwanza (AOA), and if so under what conditions?» | É o **NÃO VERIFICADO** da própria matriz (§6.1, linha MPS: «se algum Solution Partner factura em Kwanzas»), e é a metade do critério 5 que pede o «modelo de facturação (cartão USD/EUR da PME *vs credit line*)» |

**E a quem se pede.** O critério 5 exige duas cotações, uma com presença em
África, e deixa os nomes em aberto. Os únicos BSPs que o conjunto nomeia estão
em E1 §8 — **360dialog** e **Twilio** —, e nenhum deles é lá descrito como tendo
presença em África. **Não invento um terceiro nome:** nenhuma fonte deste
conjunto nomeia um BSP com presença africana, e escrever um aqui era dar a um
palpite a aparência de uma lista de contactos. A linha 2 do §6.2 fica com o
destinatário **a identificar**, e identificá-lo é o primeiro passo de quem pede
as cotações (§12, item 6).

| Linha do §6.2 | Destinatário proposto | Fonte do nome |
|---|---|---|
| 1 | **360dialog** | E1 §8, como **INDÍCIO** quanto aos preços; o nome é o que se usa para contactar, não um preço |
| 2 | **A identificar** — BSP com presença em África | **Nenhuma** no conjunto. É o que o critério 5 exige e o que nenhuma fonte nomeia |
| 3 (suplente) | **Twilio** | E1 §8, nas mesmas condições |

| Elemento | Valor |
|---|---|
| Estado da Q15 | **`por enviar`** ([`Meta_Perguntas.md`](Meta_Perguntas.md) §1.1) |
| Lote | 2 (dia 10) |
| Canal | O do próprio BSP; fica registado no envio |
| Credor do envio | **Fundador** (§1, acto 5) |

**Nada se reescreve porque reescrever criava duas versões da mesma pergunta**, e
a que fosse enviada deixaria a outra a mentir. O que este ficheiro acrescenta à
Q15 é o destino da resposta: a linha do §6.2.

### 6.4 Modelo de facturação, e porque D5 não fecha sem D9

O critério 5 pede «modelo de facturação (cartão USD/EUR da PME *vs credit
line*)» e que «a decisão cite o input de D9 sobre quem paga em USD».

| Modelo | Facto | Estado |
|---|---|---|
| **Cartão da PME** (Tech Provider) | O cliente adiciona o seu método de pagamento e a Meta factura-o; sem método de pagamento a Meta **deixa de entregar *service messages*** depois das 1.000 grátis **por número de telefone** e por mês | **CONFIRMADO** — o Tech Provider sem *credit line* é E1 §3; as **1.000 grátis por número** são **E1 §1** (e não o §3), e o efeito de não haver método de pagamento está no `../../10` §6.1. O «**por número**» é o que torna o escudo partilhável ou não, e E1 §1 fá-lo depender do modelo: com número por loja cada loja tem o seu, com número agregador esgota-se |
| ***Credit line*** (Solution Partner, directo ou por MPS) | O Solution Partner tem *credit line*, factura o cliente e dispensa-o de inserir cartão | **CONFIRMADO** quanto à existência; **NÃO VERIFICADO** quanto a haver acordo e a faturar em moeda local |
| **Quem paga os custos em USD** (input de D9) | **NÃO DECIDIDO** | É a metade de D9 que o [`Seguimento_APD.md`](Seguimento_APD.md) §3 regista com a célula **vazia** e marcada como **decisão do fundador**, informada pela pergunta F-02 do pacote jurídico |

> **O input que o critério 5 manda citar não existe ainda, e é isso que fica
> citado.** O KAM-105 registou D9 como **PROVISÓRIA** e deixou expressamente em
> branco a entidade que paga em USD. Uma matriz de D5 que escolhesse o modelo de
> facturação sem esse input estaria a decidir, por via indirecta, uma coisa que
> a Carta §4.2 dá ao fundador.

### 6.5 Registo de D5: **ABERTA**

| Campo | Valor |
|---|---|
| Decisão | D5 — Tech Provider directo, MPS ou BSP |
| Estado | **ABERTA** |
| Posição documentada hoje | **Tech Provider directo**, fixada pelo **ADR-001** e repetida no `../../01` §4.1 como decisão de arranque, com cotação a 2 BSPs **como plano B** |
| Dono | Responsável de Produto (Carta §4.2) |
| Prazo do critério 5 | Semana 4 |
| O que falta para fechar | (a) **≥ 2 cotações formais** — há **0**; (b) o **input de D9** sobre quem paga em USD — **não decidido**; (c) o estado do estatuto (§9), que hoje não existe |
| Credor | **Fundador** (cotações, e a assinatura do pivô se a semana 6 o accionar), **Responsável de Produto** (registo e fecho — é o dono que a Carta §4.2 nomeia) |
| Assinatura | — |

**Não registo D5 como «provisória», e a razão é a letra do critério.** O
critério 5 do KAM-105 autorizava por escrito um registo provisório de D9 — e foi
por isso que o [`Seguimento_APD.md`](Seguimento_APD.md) §3 o pôde fazer. O
critério 5 **deste** ticket não autoriza nada parecido: pede a decisão com a
tabela e com ≥ 2 cotações. Com zero cotações, chamar «provisória» à posição do
ADR-001 era dar a um registo novo a aparência de um passo dado, quando o passo
que falta é obter as cotações.

---

## 7. A barreira do cartão (critério 6): o lugar preparado, e nenhum número

O critério 6 manda registar, por PME entrevistada, se tem cartão internacional,
e diz onde: «nas entrevistas do **KAM-106**». O KAM-106 nomeia o mesmo pelo
outro lado — «o n.º com cartão internacional (entrada para KAM-102/D5)».

| Campo | Valor |
|---|---|
| PMEs entrevistadas | **0** |
| Com cartão internacional | **0 de 0** — e isto **não é zero por cento**: é **não medido** |
| Instrumento | O guião de entrevistas do **KAM-106** |
| Credor | **KAM-106** |
| O que a medição decide | Se o modelo «cartão da PME» (§6.4) é viável no Piloto, ou se a facturação obriga ao caminho MPS. Alimenta **D5** e o **KAM-095** |

> **Um zero em português é «não medido», e escrever uma percentagem aqui era
> inventar a conta que justifica a decisão.** O risco é real, e vale dizer com
> precisão quem afirma o quê: **E1 §1** dá como **CONFIRMADO** que a Meta factura
> Angola em moeda estrangeira (a *rate card* oferece USD, EUR, GBP e outras, e
> Angola não tem moeda local), e tira daí a implicação de que «PMEs angolanas
> precisam de cartão internacional (…) Barreira real de adopção» — uma
> implicação, não uma medição. Quem lhe põe o rótulo **INDÍCIO** é a tabela de
> riscos deste **epic**, ao ligar D5 e D9; o `../../00` §13.3 lista D5 e D9 e
> **não classifica** nada como INDÍCIO. O **número** de PMEs com cartão não
> existe em fonte nenhuma do conjunto. A tabela existe para que a medição do
> KAM-106 aterre num lugar já preparado, com a coluna certa e o destino escrito.

---

## 8. Limites de *onboarding* e *Access Verification* (critério 8)

### 8.1 O que está CONFIRMADO

| Limite | Valor | Condição | Estado |
|---|---|---|---|
| Clientes novos por janela móvel de 7 dias, por defeito | **10** | Nenhuma **nas páginas que E1 leu** — mas ver o §8.3, que regista uma condição **anterior** a este limite | **CONFIRMADO** — E1 §3 |
| Clientes novos por janela de 7 dias, depois das verificações | **200** | Business Verification **e** App Review **e** *Access Verification* | **CONFIRMADO** — E1 §3 |
| Acima de 200 | — | Candidatura a **Meta Business Partner** | **CONFIRMADO** — E1 §3 |
| Contas criadas por *developer app* | Não integráveis pelo Embedded Signup | — | **CONFIRMADO** — E1 §3 |

### 8.2 O que a *Access Verification* exige: **NÃO VERIFICADO**, e aponta-se a pergunta

| Campo | Valor |
|---|---|
| Requisitos | **NÃO VERIFICADO** |
| Processo para a pedir | **NÃO VERIFICADO** |
| Prazo | **NÃO VERIFICADO** |
| Fonte do estado | [`Meta_Perguntas.md`](Meta_Perguntas.md) §3.4: a página do Embedded Signup **nomeia** o passo e **não descreve** requisitos, processo nem prazo — releitura de 2026-11-05, que **mantém** o estado que E1 §3 lhe dá |
| A via | **Q9** de [`Meta_Perguntas.md`](Meta_Perguntas.md) §1, estado **`por enviar`**, lote 1 (dia 5) |
| Credor da resposta | **Fundador** (envio) — **não é nenhum dos seis actos do §1**, que são os deste ticket; enviar as perguntas é o item 1 do §7 de [`Meta_Perguntas.md`](Meta_Perguntas.md), cujo credor é o fundador pela mesma razão: comunicar em nome da empresa |

**Não invento o conteúdo da Q9, e é o que o critério 8 manda:** diz «conforme
resposta da Meta (Q9 de KAM-101)». Sem resposta, o que se regista é a pergunta,
o seu estado e quem a move.

### 8.3 Um aperto que o KAM-101 trouxe, e que fica como INDÍCIO

A releitura de [`Meta_Perguntas.md`](Meta_Perguntas.md) §3.4 acrescentou uma
condição que E1 §3 não regista nessa linha: **não se pode integrar cliente
nenhum enquanto a app não tiver *advanced access* para cada permissão de que
precisa** — uma condição **anterior** ao limite de 10, não um limite maior.

| Campo | Valor |
|---|---|
| Estado | **INDÍCIO, uma leitura** — é o estado que o §3.4 lhe dá, e herda-se, não se promove |
| Porque não sobe | É novo face a E1, logo nenhuma segunda leitura o corroborou; a regra de estado está no §3 de [`Meta_Perguntas.md`](Meta_Perguntas.md) |
| O que muda se for confirmado | O limite relevante antes do App Review não é 10: é **0**. O passo 4 passa de «sobe o tecto» a «abre a porta», e a rampa de lançamento do `../../01` §4.2 muda de forma |

### 8.4 O que fica registado para o KAM-095

O KAM-095 — lista de espera para o limite de *onboarding* — depende deste ticket
(`ext:KAM-102` na sua linha do backlog). O que lhe fica escrito:

| # | Facto ou aviso | Estado |
|---|---|---|
| 1 | O tecto por defeito é **10** por janela móvel de 7 dias, e sobe a **200** só com os três passos | **CONFIRMADO** (E1 §3) |
| 2 | **Nenhum dos dois valores se fixa em código como constante final.** O 200 depende da *Access Verification*, cujos requisitos são NÃO VERIFICADOS: uma fila dimensionada para 200 antes de alguém saber como se obtém o passo 5 promete capacidade que ninguém confirmou | Aviso deste ficheiro |
| 3 | O contador **atravessa *tenants***: o tecto é da app da KAMBÁ perante a Meta, não de uma loja — dois *tenants* diferentes consomem dois lugares | **CONFIRMADO** no EPIC-02, critério 8 do KAM-016 |
| 4 | Se o §8.3 se confirmar, há um estado **antes** da fila: sem *advanced access* não há integração nenhuma, e a fila não é de espera por lugar, é de espera por aprovação | **INDÍCIO** (§8.3) |

---

## 9. Estatuto, *Direct Support* e `config_id` (critério 4)

Nasce vazio, e cada linha diz onde vive o que **não** entra no repositório.

| Elemento | Valor | Estado | Onde vive |
|---|---|---|---|
| Estatuto de Tech Provider no painel da app | — | **não confirmado** | Captura datada, em arquivo controlado **fora do repositório** |
| Data da captura | — | — | — |
| Acesso a *Direct Support* (S/N) | — | **não confirmado** | Painel |
| `config_id` do ES v4 de coexistência | — | **não criado** | **Cofre de segredos**; entregue ao **KAM-016** por referência do cofre, **nunca** em repositório |
| App Secret e tokens | — | — | Cofre |

> **Nenhum destes valores aparece aqui depois de existir, e não é esquecimento:**
> é a caixa 3 da *Definition of Done* do ticket. O que este ficheiro pode passar
> a conter é a **data** da confirmação e um **S/N** — nunca o `config_id`, nunca
> um token, nunca a captura.
>
> **E o *Direct Support* é um S/N que vale mais do que parece.** E1 §3 dá-o como
> atributo do estatuto, e o §4.4 deste ficheiro mostra o que depende dele: é a
> via de escalada da terceira rejeição do App Review, e não existe antes da
> aprovação.

---

## 10. A regra de falha da semana 6, como lista de verificação (critério 7)

A regra não é nossa: vem da Carta §4.2 — «Sem Tech Provider à semana 6: pára o
canal (KAM-016)» — e o pivô vem do `14` §6. Aqui escreve-se como lista, para que
na semana 6 seja uma leitura e não uma discussão.

### 10.1 A medição

| # | Verificação | Como se mede | Resposta |
|---|---|---|---|
| 1 | A Business Verification está **aprovada**? | Linha 2 do §2 com resultado `aprovado` e data | **não** (por submeter) |
| 2 | O App Review está **aprovado para `whatsapp_business_messaging`**? | Linha **4a** do §2, com resultado `aprovado` e data | **não** (por submeter) |
| 3 | O App Review está **aprovado para `whatsapp_business_management`**? | Linha **4b** do §2, com resultado `aprovado` e data | **não** (por submeter) |
| 4 | O estatuto está **confirmado no painel**? | §9, com captura datada | **não** |
| 5 | Foram usadas as **3 submissões** do §4.4? | Contador do §4.4 | **0 de 3** |

> **«Sem Tech Provider» define-se pelas linhas 1 a 4, e as quatro têm de ser
> `sim`.** Uma aprovação só da permissão de mensagens não é Tech Provider para
> este efeito: sem `whatsapp_business_management` não há criação de *templates*,
> e sem *templates* não há o fluxo que o gate da Fase 0 exige. Deixar a
> definição implícita era convidar a semana 6 a discutir o que já está escrito.

### 10.2 O que acontece se a medição der «não»

| # | Passo, por ordem | Dono |
|---|---|---|
| 1 | Registar o resultado da medição do §10.1 **com data** | Responsável de Produto |
| 2 | **Parar a camada de canal — KAM-016.** É a consequência que a Carta §4.2 nomeia, e não é negociável na semana 6 | Responsável de Produto |
| 3 | Escolher **um** dos três pivôs do `14` §6, com a razão escrita | Responsável de Produto, proposta |
| 4 | **Assinar a decisão.** A Carta §4.2 dá D5 a **Produto** e não nomeia quem assina; o que a assinatura do fundador cobre é o **pivô** — mudar o canal do produto e parar o KAM-016 — e os actos 1 a 5 do §1, que são dele e que este pivô interrompe | **Fundador** (pivô), **Responsável de Produto** (registo de D5) |
| 5 | Registar o efeito em **H4** pelo §4 de [`Meta_Perguntas.md`](Meta_Perguntas.md), e em **D5** pelo §6.5 deste ficheiro | Responsável de Produto |

### 10.3 Os três pivôs, e o que cada um custa

Os três são os do `14` §6 para «H4 ou H3 falham» — «mudar de canal: BSP parceiro,
outro número, ou produto sem automação no WhatsApp da PME».

| Pivô | O que resolve | O que custa | Pré-requisito que ninguém tem hoje |
|---|---|---|---|
| **BSP parceiro** | Dispensa a Business Verification e o App Review da KAMBÁ | Taxa e *markup* (§6.1), e perda de controlo do canal | **≥ 1 cotação formal** — há **0** (§6.2). Um pivô para uma opção sem cotação é um pivô para o desconhecido |
| **Outro número** | Evita a coexistência no número da PME | Perde o Fluxo A, que é a base do desenho (`../../01` §4) | Nenhum bloqueador documental, mas muda a proposta de valor |
| **Produto sem automação no WhatsApp da PME** | Não depende de estatuto nenhum | Deixa de ser WhatsApp-native | Decisão de produto, não de canal |

### 10.4 A ressalva de H4, que se cita e não se reescreve

[`Meta_Perguntas.md`](Meta_Perguntas.md) §4.1 fixou-a, e vale aqui porque é
sobre **este** ticket: a aprovação de Tech Provider é uma das duas vias para dar
H4 como `confirmada`, **mas sozinha não afasta o critério «exclusivo da Meta»** —
pelo que `confirmada` por essa via **não fecha D2** nem levanta o diferimento do
**ADR-011**. E o mesmo ficheiro regista que **qual das duas leituras do seu
critério 5 vale** está devolvido ao Responsável de Produto, e não decidido.

**Não reabro nenhuma das duas coisas.** Este ficheiro alimenta a via da
aprovação; a regra de H4 é de lá.

---

## 11. A cláusula 4.7 e o caminho MPS/BSP: o que fica citado, e não se corrige

Isto entra aqui por uma razão substantiva, e não por cortesia a outro ticket: as
opções **MPS** e **BSP** do §6.1 implicam **contratar um Solution Provider**, e é
exactamente essa a condição que o achado do KAM-101 nomeia.

| Campo | Valor |
|---|---|
| O que o registo diz | A restrição de treino de ML da cláusula **4.7** dos Termos está **condicionada ao caso de se contratar um *AI Provider* como *Solution Provider***, e tem **excepção** para afinar um modelo de uso exclusivo próprio |
| Estado | **INDÍCIO, uma leitura** — e herda-se assim |
| Onde está registado | [`Meta_Perguntas.md`](Meta_Perguntas.md) §3.1, com o §3.1.1 a reunir o que o ticket da L1 precisa de citar |
| Quantos documentos a afirmam sem a condicionante | A prosa da fonte diz **cinco**; a tabela do §3.1.1 que a acompanha enumera **seis** — `../../00` §11, `../../00` §8 (ADR-018), `../../10` §7.3, `specs/EPIC-03`, `specs/tickets/KAM-169.md` e o `ADR-L006` —, à parte dos dois que já pedem na própria frase que se verifique o texto. **Fica a discrepância escrita e não corrigida**: o alcance do ticket da L1 é o da tabela, que é o maior dos dois, e reconciliar a prosa é desse ticket. **Um dos seis é um `ADR-L` em vigor** — que regista uma decisão do fundador e **não se emenda por iniciativa de sessão** |
| Credor da correcção | **Fundador**, pela linha L1 (achado → ticket) |
| O que muda no desenho | **Nada.** A posição em vigor é mais conservadora do que a fonte exige: conversas reais **não** treinam nem melhoram modelos |
| A via de confirmação | **Q7** de [`Meta_Perguntas.md`](Meta_Perguntas.md) §1, estado `por enviar` |

> **Porque é que isto é relevante para D5 e não só para o canon.** Se o caminho
> escolhido for MPS ou BSP, a KAMBÁ passa a ter um Solution Provider contratado —
> e, na leitura registada, é esse o caso que a cláusula nomeia. **Isso é uma
> razão para perguntar, não para relaxar:** nada se altera por causa deste
> parágrafo, e a decisão de D5 não se toma com uma leitura única como fundamento
> jurídico. *(a confirmar por parecer)*

---

## 12. O que este ficheiro não entrega, e de quem fica à espera

Cada linha tem **credor nomeado**, e nenhum é «quando X aterrar» nem «a sessão
escreve-a» — fundir arquiva a sessão. São **dezoito ainda abertos**, mais um
**fechado** (o item 14) e um **novo** que a integração da `main` trouxe (o item
15b). O fundador é credor — sozinho ou ao lado de outro papel — em **onze**
deles; os restantes são do Responsável de Produto, do Arquitecto de Plataforma e
do KAM-106.

> **O item 14 fechou-se durante a integração, e vale dizer como.** Estava
> devolvido ao KAM-100 porque o `validar_evidencia.py` não existia na árvore.
> **O KAM-100 fundiu**, o *script* aterrou, correu-se sobre este ficheiro e ele
> **falhava** — faltavam-lhe `Estado`, `Fonte` e `Dono` no cabeçalho. Com os três
> declarados passa a **conforme**. Um item devolvido cujo credor entrega
> fecha-se **e verifica-se**; dar-lhe por fechado sem correr o instrumento era o
> defeito simétrico.

| # | O que falta | Porquê não é do executor | Credor |
|---|---|---|---|
| 1 | **Submeter a Business Verification e medir o prazo** (critérios 1 e 2) | Submete-se em nome da entidade legal, e o prazo mede-se da submissão. Sem submissão não há dias úteis a contar (§2.3) | **Fundador** |
| 2 | **Correr o ensaio do protótipo e gravar as 4 gravações** (critério 3, «Testes Requeridos») | Exige conta de teste, número de teste e token, que não existem aqui e não devem existir no repositório. O guião está no §5 e o *storyboard* no §4.3 | **Fundador**, com aprovação do *storyboard* pelo **Responsável de Produto** |
| 3 | **Decidir quantas gravações são «2 vídeos por permissão»** (§4.3) | E1 §3 lê-se como **uma** gravação por permissão; o critério 3 diz **2 por permissão**. Mudar o sentido de um critério de aceitação é de quem o escreveu. Preparei para a leitura estrita, que satisfaz as duas | **Responsável de Produto** |
| 4 | **Decidir se as permissões 3 e 4 vão no mesmo ciclo** (critério 9, §4.1) | O critério manda pedi-las; o ADR-020 e a D13 proíbem construir o fluxo que as demonstraria, e se a Meta concede *advanced access* sem fluxo gravável é **NÃO VERIFICADO**. Uma rejeição consome uma das três submissões | **Responsável de Produto** |
| 5 | **Decidir se as permissões acompanhantes entram** (`pages_read_engagement`, `instagram_business_basic`, `publish_video`) | O critério 9 nomeia duas; acrescentar permissões a um pedido é alterar o pedido. Ficam registadas no §4.1 para a decisão se tomar com elas à vista | **Responsável de Produto** |
| 6 | **Obter ≥ 2 cotações formais de BSP** (critério 5) | Contacto comercial em nome da empresa. O pedido está redigido e é a **Q15** (§6.3) | **Fundador** |
| 7 | **Fechar D5** (critério 5) | Falta-lhe o que o §6.5 lista, e mudar da posição do **ADR-001** é substituir um ADR em vigor | **Fundador** (assinatura), **Responsável de Produto** (registo) |
| 8 | **O input de D9 sobre quem paga em USD** (critério 5) | É a célula que o [`Seguimento_APD.md`](Seguimento_APD.md) §3 deixa **vazia** e marca como decisão do fundador, informada pela pergunta F-02 | **Fundador** |
| 9 | **Contar as PMEs com cartão internacional** (critério 6) | Mede-se nas entrevistas, e as entrevistas são de outro ticket. O lugar está preparado no §7 | **KAM-106** |
| 10 | **A resposta à Q9 sobre a *Access Verification*** (critério 8) | Enviar é acto humano; o detalhe não está em fonte nenhuma (§8.2) | **Fundador** (envio), **Responsável de Produto** (registo) |
| 11 | **Confirmar o estatuto e o *Direct Support*; criar o `config_id`** (critério 4) | Leitura do painel por quem tem a conta, e o `config_id` nasce no cofre. §9 | **Fundador** |
| 12 | **Assinar a decisão da semana 6, se a medição der «não»** (critério 7) | É um pivô de canal: muda o produto e para o KAM-016. A Carta §4.2 **não nomeia quem assina D5** — dá-lhe dono Produto —, e por isso a assinatura cobre o pivô e os actos que ele interrompe, enquanto o **registo** de D5 é do dono. A lista de verificação está no §10 | **Fundador** (pivô), **Responsável de Produto** (registo) |
| 13 | **Registar a resposta da Meta às permissões de redes em `../E5_Modulos_Entrada.md`** (critério 9) | Não há resposta. Editar um documento de evidência para escrever que não há resposta era ruído; o lugar está nomeado | **Responsável de Produto**, quando a resposta existir |
| 14 | ~~**Validar com `validar_evidencia.py`**~~ — **feito**, e deixa de ser devolvido | O *script* era artefacto do **KAM-100** e não existia na árvore quando este ficheiro foi escrito. **Aterrou na `main` com a fusão do KAM-100** e correu sobre este ficheiro: `python scripts/validar_evidencia.py docs/tecnica/evidencia/validacao/Tech_Provider_Dossie.md` → **`conforme — 1 ficheiro(s)`**, código de saída **0**. Foi o que obrigou a declarar `Estado`, `Fonte` e `Dono` no cabeçalho, que faltavam | **— (fechado)** |
| 15 | **Corrigir o âmbito da cláusula 4.7 nos documentos que a afirmam** (§11) — **seis** pela tabela do §3.1.1 da fonte e **cinco** pela prosa dela, discrepância que fica escrita e não corrigida | Um `ADR-L` em vigor não se emenda por iniciativa de sessão, e corrigir canon a coberto de um ticket de dossiê era alargar escopo em silêncio | **Fundador**, pela linha L1 |
| 15b | **Os outros onze ficheiros de `validacao/` não passam o `validar_evidencia.py`** | Corrido sobre a pasta inteira: **30 achados em 12 ficheiros**, e **11 deles não são deste ticket** — faltam-lhes `Estado`, `Fonte` ou `Dono` no cabeçalho, porque foram escritos antes de o validador existir. O [`Meta_Perguntas.md`](Meta_Perguntas.md) tem um achado de outra natureza: o validador lê **`MORTO`** da prosa do §3.5 como se fosse o `Estado` do documento, o que é um falso positivo do próprio validador. **Corrigir onze ficheiros alheios a coberto de um ticket de dossiê era alargar escopo em silêncio**, e o validador **não está no CI** (nem no `Makefile` nem nos *workflows*), pelo que nada está vermelho por causa disto. Fica medido para a linha **L1** | **Fundador**, pela linha L1 (achado → ticket) |
| 16 | **Revisão cruzada de que as datas e os dias úteis batem** («Testes Requeridos») | **Não há data nenhuma para cruzar**: zero submissões, zero respostas. A **regra** de contagem está no §2.2 e é o que se pode entregar hoje | **Responsável de Produto**, quando houver a primeira data |
| 17 | **Decidir se escolher MPS ou BSP obriga a emendar o ADR-001** (§6.1) | O ADR-001 nomeia «Tech Provider» e o que bane é o gateway não-oficial; D5 está **ABERTA** no `../../00` §13.3 e na Carta §4.2, e o BSP é plano B escrito no `../../01` §4.1 e pivô no `14` §6. Exercer o plano B não é substituir um ADR — mas se a redacção do ADR-001 tem de mudar, emendar canon não é acto de sessão | **Arquitecto de Plataforma** (parecer), **Fundador** (emenda) |
| 18 | **Identificar o BSP com presença em África** (critério 5, §6.3) | **Nenhuma fonte deste conjunto nomeia um.** E1 §8 nomeia 360dialog e Twilio e não lhes atribui presença africana; escrever um terceiro nome aqui era dar a um palpite a aparência de uma lista de contactos | **Responsável de Produto** |

---

## 13. Seguimento

A regra, sem datas absolutas: contam-se do dia 0, que é o dia da primeira
submissão e ainda não existe.

| Marco | Quando | Acção | Dono |
|---|---|---|---|
| **Dia 0** | Submissão da Business Verification | Preencher a linha 2 do §2 e arrancar a contagem do §2.2 | Fundador |
| **Dia 5** | Prazo do critério 2 | Business Verification **submetida** | Fundador |
| **+3 dias úteis de uma rejeição** | Critério 2 | Registar a alternativa — outra entidade, ou via BSP/MPS — no §6 | Responsável de Produto |
| **+5 dias úteis da Business Verification aprovada** | Prazo do critério 3 | App Review **submetido**, com descrições aprovadas e gravações feitas | Fundador |
| **Semana 4** | Prazo do critério 5 | D5 registada, ou o §6.5 actualizado a dizer o que ainda falta | Responsável de Produto |
| **Após a aprovação** | Critério 4 | Confirmar estatuto e *Direct Support* (§9); criar o `config_id` no cofre e entregar a referência ao KAM-016 | Fundador |
| **Semana 6** | Carta §4.2; `14` §6 | Correr a lista do §10.1 e, se der «não», os cinco passos do §10.2 | Responsável de Produto, assinatura do **Fundador** |

---

## 14. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto (dono de D5; aprovação das descrições e do *storyboard*) | | | |
| Arquitecto de Plataforma (ADR-001, camada de canal) | | | |
| Fundador (submissões em nome da entidade legal; fecho de D5; decisão da semana 6) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-102. Dossiê dos **seis** passos do estatuto perante a Meta — entidade e portfólio, Business Verification, app e caso de uso, App Review **por permissão**, *Access Verification*, método de pagamento —, com o passo 4 desdobrado em **quatro** linhas, uma por permissão, porque a lista de verificação do §10.1 mede a aprovação de cada uma em separado e uma linha única não podia responder. Coluna **«Estado»** ao lado da «Resultado», e não colada a ela: `por submeter` **não é um resultado**, e é assim que o precedente do [`Seguimento_APD.md`](Seguimento_APD.md) §1 o faz. Nasce a **0 submetidos, 0 aprovados, 0 prazos medidos**. Regra de contagem de dias úteis escrita **antes** de haver o que contar, com os feriados a **não** descontar e o fuso em **`Africa/Luanda`**, que é o que o dicionário canónico §2 manda para apresentação — e é material, porque Luanda é UTC+1 e uma submissão depois das 23:00 locais cairia no dia UTC seguinte, atravessando um fim de semana numa sexta-feira. **O prazo da Business Verification não é substituído por um valor medido**, como o critério 1 pede: fica **NÃO MEDIDO**, e o §2.3 separa-o dos três que têm fonte — as «cerca de 24 horas» do App Review como **número da Meta**, o «*turnaround* muito mais rápido» da verificação conduzida por **Select ou Premier** Solution Partner como **NÃO VERIFICADO** (a página que o carrega está declarada «listada, não lida» em E1 §3), e o único **INDÍCIO** que o conjunto tem para este prazo, «dias a semanas» de `../E5_Modulos_Entrada.md` §3, com o âmbito e a falta de fonte oficial escritos. Lista de documentos por passo, com a aceitação de documentos angolanos **NÃO VERIFICADA** e a **Q8** como via, e os documentos da empresa **fora do repositório**. App Review com as **quatro** permissões, **quatro** descrições escritas em **EN e PT** — o EN é o que se submete, porque uma tradução feita no momento da submissão é texto que ninguém reviu —, e um *storyboard* de **seis** gravações: quatro para as duas permissões do WhatsApp, porque **as três fontes usam duas redacções e nenhuma diz quantos ficheiros se submetem** (E1 §3 «uma gravação por permissão»; o critério 3 «2 vídeos por permissão»; o `../../01` §4.2 repete a segunda e acrescenta o parêntesis «(mensagem, template)», que é a primeira), e **duas para as permissões de redes**, do único fluxo que existe — gerar, o dono aprovar, **entregar para publicação manual** —, porque redigir descrições para essas permissões e recusar-lhes *storyboard* era uma assimetria sem razão. O que continua **NÃO VERIFICADO** é se a Meta concede *Advanced access* com base numa demonstração de entrega manual, e **gravar o acto de publicar não é opção**, porque o ADR-020 regra 3 o proíbe no Piloto. Contador das **3** submissões a **0 de 3**, com a armadilha circular escrita: a via de escalada é o *Direct Support*, que é atributo do estatuto que o App Review concede. Guião de ensaio do protótipo em **sete** passos, que dispensa escrever código porque E1 §3 confirma que a cURL do API Setup e o WhatsApp Manager servem no lugar da app — e o ES v4 em código é KAM-016. Matriz de **D5** com as três opções, e a leitura do canon corrigida: o ADR-001 nomeia Tech Provider e o que **bane** é o gateway não-oficial, D5 continua **ABERTA** no `../../00` §13.3 e na Carta §4.2, e o BSP é **plano B escrito** no `../../01` §4.1 e **pivô** no `14` §6 — logo exercer o plano B **não é substituir um ADR**, e se a redacção do ADR-001 tiver de mudar isso é pergunta para o Arquitecto de Plataforma e para o fundador. Tabela das cotações a nascer vazia — **0 pedidas, 0 recebidas, mínimo 2** — com «suporte a BSUID» como coluna **eliminatória**, porque E1 §3 dá os BSUID como obrigatórios para todos os parceiros e o telefone pode deixar de vir no webhook; os preços de BSP de E1 §8 **não entram em célula nenhuma**, por serem INDÍCIO. O **modelo de cotação** é entregue como os «Detalhes Técnicos» do ticket pedem: o corpo é a **Q15**, que não se reescreve, mais as **três** perguntas que ela não faz e de que a matriz depende — presença em África, moeda de facturação e se factura em Kwanzas —, redigidas em EN. Os destinatários são os que o conjunto nomeia (E1 §8: **360dialog** e **Twilio**) e a linha do BSP **com presença em África fica «a identificar»**, porque nenhuma fonte deste conjunto nomeia um e escrever um nome era dar a um palpite a aparência de uma lista de contactos. **D5 fica ABERTA e não «provisória»**: o critério 5 do KAM-105 autorizava esse caminho por escrito para D9 e este não autoriza nada parecido — e falta-lhe também o **input de D9** sobre quem paga em USD, que o [`Seguimento_APD.md`](Seguimento_APD.md) §3 deixa vazio e marca como decisão do fundador. A barreira do cartão tem lugar preparado e **nenhum número**: **0 de 0 é «não medido», não é zero por cento**, com a atribuição corrigida — **E1 §1** dá como CONFIRMADO que a Meta factura Angola em moeda estrangeira e tira daí a implicação da barreira, e quem lhe põe o rótulo INDÍCIO é a tabela de riscos do **epic**, não o `../../00` §13.3. Credor: **KAM-106**. Limites de *onboarding* CONFIRMADOS (10, depois 200 com os três passos, Meta Business Partner acima disso), *Access Verification* mantida **NÃO VERIFICADA** com a **Q9** como única via, e o aperto que o KAM-101 trouxe — **sem *advanced access* não se integra cliente nenhum**, condição anterior ao limite de 10 — citado como **INDÍCIO, uma leitura**, com remissão da própria célula do «10». Quatro avisos escritos para o **KAM-095**, o principal dos quais é não fixar o 200 como constante final. Regra de falha da semana 6 como lista de verificação, com «sem Tech Provider» **definido** pelas quatro linhas da medição, que agora apontam para as linhas desdobradas **4a** e **4b**; os cinco passos da consequência com a paragem do KAM-016 que a Carta §4.2 nomeia; e os três pivôs do `14` §6 com o que cada um custa — o do BSP com o pré-requisito a **zero**. **A Carta §4.2 não nomeia quem assina D5** — dá-lhe dono **Produto** —, pelo que a assinatura do fundador cobre o **pivô** e os actos que ele interrompe, e o **registo** de D5 é do dono. A cláusula **4.7** entra por razão substantiva: MPS e BSP implicam **contratar um Solution Provider**, que é a condição que o achado do KAM-101 nomeia; fica citada como **INDÍCIO de uma leitura**, **nada se relaxa**, e corrigir os documentos que a afirmam sem a condicionante é da linha L1 com o **fundador** como credor — **a prosa da fonte diz cinco e a tabela do seu §3.1.1 enumera seis**, e a discrepância fica escrita e não corrigida, porque o alcance desse ticket é o da tabela. **Dezoito** itens devolvidos no §12, cada um com credor que sobrevive à fusão, e o fundador é credor em **dez**. A revisão adversarial devolveu **27 achados** e está na [`ANALISE-53`](../../../analises/ANALISE-53-KAM-102-tech-provider.md). | Equipa KAMBÁ |

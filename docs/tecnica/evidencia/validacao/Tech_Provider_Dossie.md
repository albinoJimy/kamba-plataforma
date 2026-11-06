# Tech Provider: dossiê de Business Verification, App Review e a análise de D5

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — dossiê dos seis passos do estatuto perante a Meta, guião do App Review e matriz de D5 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-102 (EPIC-10) |
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
| 6 | **Assinar a decisão da semana 6** | Fecho de decisão aberta é do fundador (Carta §4.2) | **Fundador** |

**Aprovar as descrições e o *storyboard*** antes de gravar é do **Responsável de
Produto**, que é o que o critério 3 pede por escrito.

---

## 2. Os seis passos: folha de seguimento (critério 1)

Uma linha por passo, na ordem em que a Meta os impõe. Estados:
**`por submeter`** → `submetido` → `em apreciação` → `aprovado` ou `rejeitado`.

> **A folha nasce em `por submeter`, que é um quinto estado e é deliberado.** O
> critério 1 pede «data de submissão, data de resposta, resultado, motivo de
> rejeição, dias úteis decorridos» — cinco colunas que só existem depois de
> alguém submeter. `por submeter` é o estado **anterior** aos quatro, não um
> quinto resultado. O precedente é exacto e está no
> [`Seguimento_APD.md`](Seguimento_APD.md) §1, cujo critério nomeia quatro
> estados e cuja folha nasce igualmente num anterior a todos.

| # | Passo | Pré-requisito | Data de submissão | Data de resposta | Resultado | Motivo de rejeição | Dias úteis decorridos | Dono |
|---|---|---|---|---|---|---|---|---|
| 1 | **Entidade legal e portfólio Meta Business** | Entidade escolhida (input de D9) | | | **por submeter** | | | Fundador |
| 2 | **Business Verification da KAMBÁ** | Passo 1 | | | **por submeter** | | | Fundador |
| 3 | **App Meta tipo Business com o caso de uso WhatsApp** | Passo 1 | | | **por submeter** | | | Fundador |
| 4 | **App Review por permissão** (*Advanced access*) | Passo 2 **aprovado** e passo 3 | | | **por submeter** | | | Fundador |
| 5 | ***Access Verification*** | Passos 2 e 4 aprovados | | | **por submeter** | | | Fundador |
| 6 | **Método de pagamento** (Billing Hub do cliente) | Passo 4 aprovado; por cliente, não por plataforma | | | **por submeter** | | | Responsável de Produto |

| Contagem | Valor |
|---|---|
| Passos na folha | **6** |
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
primeiro da cadeia e **o único cujo prazo é NÃO VERIFICADO**, o que o torna o
item de espera externa mais perigoso do epic. Arranca na semana 1 por essa
razão, não por conveniência de calendário.

### 2.2 Dias úteis: a regra de contagem, escrita antes de haver o que contar

Fixada aqui para que a coluna não se preencha com duas réguas diferentes:

| Elemento | Regra |
|---|---|
| Dia 0 | O dia da submissão, não contado |
| Dias contados | Segunda a sexta-feira |
| Sábados e domingos | Não contados |
| Feriados | **Não descontados**, e a razão é substantiva: a Meta responde num calendário que não é o angolano, e descontar um feriado de Angola a um prazo da Meta mediria a coisa errada |
| Fuso | UTC para a data de registo, como todo o conjunto |

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
| Verificação conduzida por Solution Partner em nome do cliente | «*turnaround* muito mais rápido» | **CONFIRMADO** como afirmação qualitativa, E1 §3 — **sem número**, e por isso não entra em nenhuma conta |

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
| 3 | App Meta tipo *Business* com o caso de uso WhatsApp, ligada ao portfólio | **CONFIRMADO** como requisito, E1 §3 | Painel da app |
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
| 1 | `whatsapp_business_messaging` | *Advanced access* | Enviar e receber mensagens no número do cliente | **CONFIRMADO** como obrigatória para Tech Provider, E1 §3 |
| 2 | `whatsapp_business_management` | *Advanced access* | Criar e gerir *templates*, ler a conta | **CONFIRMADO** como obrigatória para Tech Provider, E1 §3 |
| 3 | `pages_manage_posts` | *Advanced access* | Publicação futura em Páginas Facebook (Social AI) | Pedido **no mesmo ciclo** por critério 9; a publicação automática é **Diferida** (D13) |
| 4 | `instagram_business_content_publish` | *Advanced access* | Publicação futura em Instagram (Social AI) | Idem |

**As acompanhantes que E1 §3 e `../E5_Modulos_Entrada.md` §3 nomeiam, e que o
critério 9 não nomeia:** `pages_read_engagement` (que o E5 §3 dá como
CONFIRMADA ao lado de `pages_manage_posts`, com `publish_video` para vídeo) e,
na via de *login* do Instagram, `instagram_business_basic`. **Não as acrescento
à lista pedida**: o critério 9 nomeia duas, acrescentar permissões a um pedido
de App Review é alterar o pedido, e isso é decisão de quem o submete. Ficam
**registadas aqui** para que a decisão se tome com elas à vista — §12, item 5.

#### Duas coisas que ninguém confirmou, e que decidem este ciclo

| # | Pergunta | Estado | Via |
|---|---|---|---|
| 1 | As permissões 3 e 4 podem ser pedidas **na mesma app e na mesma Business Verification** que o Tech Provider do WhatsApp? | **NÃO VERIFICADO** | É literalmente a pergunta 1 da lista «Para a Meta» de `../E5_Modulos_Entrada.md` §3 |
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

| Permissão | Descrição proposta |
|---|---|
| `whatsapp_business_messaging` | «A KAMBÁ é uma plataforma de comércio conversacional que permite a pequenas e médias empresas em Angola atender clientes, apresentar catálogo e registar pedidos por WhatsApp. Com esta permissão a plataforma envia e recebe mensagens no número da própria empresa cliente, que é a dona da conta e do número. A empresa cliente autoriza o acesso pelo Embedded Signup e mantém acesso total ao WhatsApp Manager. Nenhuma mensagem é enviada sem que a empresa cliente tenha concedido o acesso, e a plataforma não envia marketing não solicitado.» |
| `whatsapp_business_management` | «Com esta permissão a plataforma cria e submete *templates* de mensagem em nome da empresa cliente — confirmações de pedido, lembretes de recolha e avisos de disponibilidade — e lê o estado da conta para apresentar à empresa a qualidade do número e os limites em vigor. A criação de cada *template* é iniciada pela empresa cliente no painel da plataforma. A plataforma não altera a propriedade dos activos: a conta, o número, os *templates* e o catálogo são da empresa cliente.» |
| `pages_manage_posts` | «A plataforma gera, a pedido da empresa cliente, peças de conteúdo para a Página Facebook da própria empresa (fotografia de produto tratada, legenda e artes). **No Piloto a entrega é para publicação manual pelo dono da empresa**, e o pedido desta permissão prepara a publicação assistida numa fase posterior, sempre com aprovação explícita do dono antes de qualquer publicação.» |
| `instagram_business_content_publish` | «O mesmo para a conta profissional de Instagram da empresa cliente: a plataforma gera a peça, o dono da empresa aprova, e a publicação assistida fica para uma fase posterior. No Piloto a plataforma entrega a peça e não publica.» |

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
deste ticket diz «**2 vídeos por permissão**», o que dá quatro. A divergência
está medida e **não a decido**: §12, item 3. O *storyboard* abaixo tem **quatro
gravações**, porque satisfazer a leitura estrita satisfaz as duas, e porque o
custo de gravar duas a mais é muito menor do que o de uma rejeição.

| Gravação | Permissão | O que tem de aparecer no ecrã, por ordem | Duração-alvo |
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

| Contagem | Valor |
|---|---|
| Gravações no *storyboard* | **4** |
| Gravações feitas | **0** — credor: **fundador** (§1, acto 3) |
| Descrições redigidas | **4** |
| Descrições aprovadas | **0** — credor: **Responsável de Produto** |

**Para as permissões 3 e 4 não há *storyboard*, e a ausência é o achado.** Não
há fluxo de publicação para gravar: o ADR-020 proíbe-o no Piloto e a D13 difere-o.
Inventar um *storyboard* de um ecrã que não existe era produzir papel. A pergunta
2 do §4.1 é a que decide o que se faz aqui.

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
| À 3.ª rejeição | **Escalar**, e a via é *Direct Support* — que **só existe depois da aprovação de Tech Provider** (E1 §3). Antes dela, o escalamento é pelo mesmo canal da submissão, e qual é esse canal é **NÃO VERIFICADO** ([`Meta_Perguntas.md`](Meta_Perguntas.md) §7, item 2) |

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
> branco.** O **ADR-001** — canon, e em vigor — já fixa «Cloud API oficial +
> coexistência; **Tech Provider**; Embedded Signup v4». O `../../01` §4.1 repete-o
> como decisão de arranque, com «cotação formal a 2 BSPs como plano B». Logo
> **escolher MPS ou BSP não é preencher D5: é substituir um ADR em vigor**, e
> isso não é acto de sessão nem de documento de evidência. O que esta matriz
> entrega é a comparação que torna essa escolha uma leitura — e a regra de falha
> do §10 é o único caminho escrito para a accionar.

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

### 6.3 O pedido de cotação é a Q15, e não se reescreve aqui

O modelo do pedido existe, está redigido em EN e PT, e é a **Q15** de
[`Meta_Perguntas.md`](Meta_Perguntas.md) §1 — a única das quinze que **não vai à
Meta**: vai ao contacto comercial de cada BSP. Pede exactamente as colunas do
§6.2: *markup* por mensagem, taxa mensal, suporte a coexistência e a BSUID, e a
tarifa final entregue para destinatários com indicativo +244, por categoria de
mensagem.

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
| **Cartão da PME** (Tech Provider) | O cliente adiciona o seu método de pagamento e a Meta factura-o; sem método de pagamento a Meta **deixa de entregar *service messages*** depois das 1.000 grátis por mês | **CONFIRMADO** — E1 §3; `../../10` §6.1 |
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
| Credor | **Fundador** (cotações e assinatura), **Responsável de Produto** (registo) |
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
> inventar a conta que justifica a decisão.** O risco é real e está em E1 como
> **INDÍCIO** (`../../00` §13.3 classifica-o assim ao ligar D5 e D9), mas o
> **número** de PMEs com cartão não existe em fonte nenhuma deste conjunto. A
> tabela existe para que a medição do KAM-106 aterre num lugar já preparado, com
> a coluna certa e o destino escrito.

---

## 8. Limites de *onboarding* e *Access Verification* (critério 8)

### 8.1 O que está CONFIRMADO

| Limite | Valor | Condição | Estado |
|---|---|---|---|
| Clientes novos por janela móvel de 7 dias, por defeito | **10** | Nenhuma | **CONFIRMADO** — E1 §3 |
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
| Credor da resposta | **Fundador** (envio) — §1, acto 5 e [`Meta_Perguntas.md`](Meta_Perguntas.md) §7 |

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
| 2 | O App Review está **aprovado para `whatsapp_business_messaging`**? | Linha 4 do §2, por permissão | **não** |
| 3 | O App Review está **aprovado para `whatsapp_business_management`**? | Linha 4 do §2, por permissão | **não** |
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
| 4 | **Assinar a decisão.** Fecho de decisão aberta é do fundador (Carta §4.2) | **Fundador** |
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
| Quantos documentos a afirmam sem a condicionante | **cinco**, e **um deles é um `ADR-L` em vigor** — que regista uma decisão do fundador e **não se emenda por iniciativa de sessão** |
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
escreve-a» — fundir arquiva a sessão.

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
| 12 | **Assinar a decisão da semana 6, se a medição der «não»** (critério 7) | Fecho de decisão aberta é do fundador (Carta §4.2). A lista de verificação está no §10 | **Fundador** |
| 13 | **Registar a resposta da Meta às permissões de redes em `../E5_Modulos_Entrada.md`** (critério 9) | Não há resposta. Editar um documento de evidência para escrever que não há resposta era ruído; o lugar está nomeado | **Responsável de Produto**, quando a resposta existir |
| 14 | **Validar com `validar_evidencia.py`** («Testes Requeridos») | O *script* **não existe** na árvore — verificado a 2026-11-06. É artefacto do **KAM-100**, como o [`Meta_Perguntas.md`](Meta_Perguntas.md) §7, item 9, já registou | **KAM-100** |
| 15 | **Corrigir o âmbito da cláusula 4.7 nos cinco documentos** (§11) | Um `ADR-L` em vigor não se emenda por iniciativa de sessão, e corrigir canon a coberto de um ticket de dossiê era alargar escopo em silêncio | **Fundador**, pela linha L1 |
| 16 | **Revisão cruzada de que as datas e os dias úteis batem** («Testes Requeridos») | **Não há data nenhuma para cruzar**: zero submissões, zero respostas. A **regra** de contagem está no §2.2 e é o que se pode entregar hoje | **Responsável de Produto**, quando houver a primeira data |

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
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-102. Dossiê dos **seis** passos do critério 1 — entidade e portfólio, Business Verification, app e caso de uso, App Review por permissão, *Access Verification*, método de pagamento — com as cinco colunas que o critério pede, a nascer em **`por submeter`**: **0 submetidos, 0 aprovados, 0 prazos medidos**. A regra de contagem de dias úteis fica escrita **antes** de haver o que contar, e os feriados **não** se descontam, porque descontar um feriado de Angola a um prazo da Meta mediria a coisa errada. O prazo da Business Verification **não** substitui o NÃO VERIFICADO de E1 §3: fica **NÃO MEDIDO**, porque medir exige submeter e submeter é do fundador. Lista de documentos por passo, com a aceitação de documentos angolanos **NÃO VERIFICADA** e a Q8 como via, e os documentos da empresa **fora do repositório**. App Review com as **quatro** permissões — as duas obrigatórias de E1 §3 e as duas que o critério 9 manda pedir —, **quatro** descrições escritas redigidas aqui como proposta por aprovar, e um *storyboard* de **quatro** gravações, porque **as duas leituras do requisito divergem**: E1 §3 lê-se como **uma** gravação por permissão e o critério 3 diz **2 por permissão**, pelo que se prepara a leitura estrita e se devolve a decisão. **Para as permissões de redes não há *storyboard*, e a ausência é o achado**: o ADR-020 proíbe a publicação automática no Piloto e a D13 difere-a, logo não há fluxo gravável — e se a Meta concede *advanced access* sem fluxo é **NÃO VERIFICADO**, com o conflito entre os critérios 3 e 9 medido e devolvido em vez de resolvido. Contador das **3** submissões a **0 de 3**, com a armadilha circular escrita: a via de escalada é o *Direct Support*, que é atributo do estatuto que o App Review concede. Guião de ensaio do protótipo em **sete** passos, que dispensa escrever código porque E1 §3 confirma que a cURL do API Setup e o WhatsApp Manager servem no lugar da app — e o ES v4 em código é KAM-016. Matriz de **D5** com as três opções e a nota que ordena tudo: **o ADR-001 já fixa Tech Provider**, pelo que escolher MPS ou BSP é **substituir um ADR em vigor** e não preencher uma decisão em branco. Tabela das cotações a nascer vazia — **0 pedidas, 0 recebidas, mínimo 2** —, com «suporte a BSUID» como coluna eliminatória e não nota de rodapé, e o pedido a apontar para a **Q15**, que não se reescreve. **D5 fica ABERTA e não «provisória»**: o critério 5 do KAM-105 autorizava esse caminho para D9 e o critério 5 deste ticket não autoriza nada parecido. A barreira do cartão tem lugar preparado e **nenhum número**: 0 de 0 é **não medido**, e o credor é o **KAM-106**. Limites de *onboarding* CONFIRMADOS (10, depois 200, e Meta Business Partner acima disso), *Access Verification* **NÃO VERIFICADA** com a **Q9** como única via, e o aperto que o KAM-101 trouxe — sem *advanced access* não se integra cliente nenhum, uma condição **anterior** ao limite de 10 — citado como **INDÍCIO, uma leitura**, sem subir a facto. Quatro avisos escritos para o **KAM-095**, o principal dos quais é não fixar o 200 como constante final. Regra de falha da semana 6 como lista de verificação, com «sem Tech Provider» **definido** pelas quatro primeiras linhas da medição, os cinco passos da consequência e os três pivôs do `14` §6 com o que cada um custa — e o do BSP com o seu pré-requisito a zero. A cláusula **4.7** entra por razão substantiva e não por cortesia: MPS e BSP implicam contratar um Solution Provider, que é a condição que o achado do KAM-101 nomeia; fica **citado como INDÍCIO de uma leitura**, **nada se relaxa**, e corrigir os **cinco** documentos (um deles um `ADR-L` em vigor) é da linha L1 com o **fundador** como credor. **Dezasseis** itens devolvidos no §12, cada um com credor que sobrevive à fusão. | Equipa KAMBÁ |

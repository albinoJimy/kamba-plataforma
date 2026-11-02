# Mapa de tratamentos — KAMBÁ, versão 1

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — mapa de tratamentos por destino, para o procedimento junto da APD |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno; base da submissão à APD |
| Ticket | KAM-105 (EPIC-10) |
| Documento-fonte | `../../08_Seguranca_Conformidade.md` §7.1 (classes), §8.3.2 (subprocessadores), §11 (retenção), §8.6 (gate de go-live); `../../09_Topologia_Operacao_Escala.md` §3.1, §5, §9.1; **as treze listas de saída da pilha** — as oito de `infra/egress/` e as cinco de `services/*/egress.yaml` |
| Relacionados | [`GoLive_Gate.md`](GoLive_Gate.md), [`Seguimento_APD.md`](Seguimento_APD.md), [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) |

> **Este documento não é aconselhamento jurídico.** Tudo o que toca a Lei 22/11,
> a APD e os Termos da Meta leva *(a confirmar por parecer)*, e os estados
> **CONFIRMADO**, **INDÍCIO** e **NÃO VERIFICADO** têm o sentido da evidência de
> pesquisa da KAMBÁ — e **não são promovidos** aqui.

---

## 0. Como este mapa foi gerado, e o que isso muda

O `../../08_Seguranca_Conformidade.md` §8.6 diz que o mapa se gera «a partir do
inventário (§7.1) e do `tenant_destinations`, para não divergir do sistema
real». **O `tenant_destinations` não existe:** é a tabela que o **KAM-069** cria,
e sem ela não há configuração de destinos a ler. Para não ficar sem a metade do
sistema, este mapa gerou-se de **três fontes**, e a terceira é a que o torna
verificável:

| Fonte | O que dá | Estado |
|---|---|---|
| `../../08` §7.1 | As classes de dados pessoais e onde vivem | Desenho |
| `../../08` §8.3.2 | O inventário de subprocessadores previsto | Desenho |
| **As treze listas de saída:** as oito de `infra/egress/` (`chatwoot.yaml`, `chatwoot-worker.yaml`, `chatwoot-db.yaml`, `chatwoot-redis.yaml`, `litellm.yaml`, `postgres.yaml`, `queue.yaml`, `seaweedfs.yaml`) e as cinco de `services/*/egress.yaml` | **As saídas que a pilha declara hoje**, negadas por omissão | **Código** |

**O que a terceira fonte diz.** Das treze listas, **uma** declara destinos:
`infra/egress/litellm.yaml`, com **três FQDN, todos de fornecedores de modelos
de linguagem** — `api.anthropic.com`, `api.openai.com` e
`generativelanguage.googleapis.com`. As outras doze têm `destinos: []` com
`por_omissao: negar`. Quatro dos cinco ficheiros de serviço dizem-se esqueletos
do KAM-001; o do `agr` declara-se funcional e, mesmo assim, «continua a não
abrir ligação nenhuma para fora». **Nenhum dos cinco nomeia o ticket que
introduzirá os seus destinos** — dois falam de «o ticket que o introduz» em
abstracto e dois não dizem nada.

E dos três declarados, **nenhum está autorizado**: a razão de um deles — o
`api.anthropic.com` — di-lo por escrito («destino de transferência `pendente`
até o KAM-069 lhe dar `apd_ref`»), e a condição comum está no cabeçalho do
ficheiro, que a aplica aos três. Em `KAMBA_ENV=prod` o *gate* de destino do
cliente de modelos recusa os três antes de o pacote chegar à lista de saídas.

> **Consequência, e é mais estreita do que parece — a primeira versão deste
> mapa exagerou-a, e a revisão adversarial apanhou-o.** O que se pode afirmar é
> isto: **nenhum serviço em execução instancia hoje um cliente de saída para
> terceiros**, pelo que nenhum processo abre hoje uma ligação que leve dados
> pessoais para fora. A contenção actual é de **ausência de ligação**, não de
> controlo — e a diferença importa:
>
> | O que **não** se pode concluir | Porquê |
> |---|---|
> | Que uma lista com `destinos: []` **bloqueia** uma saída | As listas são **contratos**, não aplicação. A aplicação na rede é o **KAM-076** e **não está feita** — é o que a linha D2t do [`GoLive_Gate.md`](GoLive_Gate.md) registra |
> | Que todo o código de saída está coberto por uma lista | **Não está.** O regime de `egress.yaml` cobre `services/*` e os serviços do *compose*; **`packages/` e `libs/` não têm lista nenhuma** — medido, zero ficheiros |
>
> **E há um caminho de saída fora do regime, que convém declarar antes que
> alguém o encontre:** o `packages/core-ts/src/outbound/cliente.ts` fixa
> `graph.facebook.com` numa constante e monta um corpo que leva o telefone do
> destinatário quando não há identificador da Meta. O próprio ficheiro diz que
> «este é o primeiro código que sai para lá» e remete a regra para o
> `../../08` §4.4 — um proxy de saída com lista de permissão —, **não para uma
> lista de `egress`**. Hoje **nenhum serviço o instancia**, e é só por isso que
> não há ligação; quando o canal de envio for ligado, este caminho precisa de
> ficar coberto. A mesma observação vale para o endereço do cofre de segredos,
> fixo em dois pacotes.
>
> **O que isto dá ao procedimento junto da APD** não é «é impossível sair»: é
> que **não há dados pessoais de produção e não há processo que os envie**, e
> que os controlos que governarão esse envio estão **nomeados e por construir**
> — o KAM-069 para a autorização por destino e o KAM-076 para a aplicação na
> rede. É uma afirmação menor e verdadeira, e é verificável em código.

---

## 1. Papéis (D9, provisório)

| Item | Posição | Estado |
|---|---|---|
| Responsável pelo tratamento | Cada PME, pelos dados dos seus clientes | **Provisório**, por defeito do `../../08` §8.2 |
| Subcontratada | A KAMBÁ, com contrato de subcontratação como pré-condição do onboarding | **Provisório** |
| Co-responsabilidade | Nos tratamentos de finalidade própria da KAMBÁ (sinal de procura agregado, índice de reputação) — que ficam **desligados** no Piloto | **Provisório** |
| Quem notifica a APD | **NÃO DECIDIDO** | Depende da pergunta A-01 do pacote (`E3` 1) |
| Entidade que paga os custos em USD | **NÃO DECIDIDO — é decisão do fundador** | Pergunta F-02 do pacote; a KAMBÁ não recomenda nenhuma das duas opções |

A fundamentação e o estado completo de D9 estão em
[`Seguimento_APD.md`](Seguimento_APD.md) §3.

---

## 2. Classes de dados e finalidades

Classes do `../../08` §7.1, com os prazos propostos do §11. **Os prazos são
propostas de engenharia; os legais estão por confirmar.**

| Classe | Exemplos | Onde vive | Retenção proposta |
|---|---|---|---|
| Identificadores de contacto | Identificador atribuído pela Meta, telefone quando existe, dispersão do contacto | Postgres (cofre separado, cifrado) | Relação mais prazo de prova |
| Conteúdo de conversa | Texto, transcrições, localização partilhada | Postgres, ferramenta de atendimento | 90 dias após o fecho; até 12 meses com justificação da PME |
| Áudio e fotografias | Notas de voz, fotografias de produto | Armazenamento de objectos | Áudio ≤ 24 h após transcrição (máx. 72 h); fotografias: vida do catálogo |
| Encomendas e pagamentos | Itens, valor, referência | Postgres, registo de pagamentos | **Prazo fiscal, sem valor até confirmação** (NÃO VERIFICADO) |
| Consentimentos | Finalidade, versão, hora | Postgres | Prova pelo prazo da relação mais prescrição |
| Telemetria e dados da PME | Registos, métricas; NIF e alvará da PME | Registos e métricas, Postgres | Registos 30 dias; PME: relação mais prazo fiscal |

**Finalidades de transferência**, para a coluna `purpose` do
`tenant_destinations`: são **três** — `conversa`, `embeddings` e `visao` —, vivem
em `FINALIDADES`, em `services/agr/src/kamba_agr/llm/destinos.py`, e **não** são
nomes do dicionário canónico: quem declara o domínio de uma coluna é a revisão
que a cria, e essa é o KAM-069. Não as declaro aqui como canon.

**A finalidade de cada destino de modelo foi derivada da configuração, e não
atribuída.** O `llm/aliases.yaml` liga cada papel aos seus fornecedores e o
`destinos.py` mapeia papel para finalidade (`router` e `chat` → `conversa`,
`vision` → `visao`, `embed` → `embeddings`). Lido assim: **anthropic** serve
`conversa` (papéis `router` e `chat`), **openai** serve `conversa` (apenas
`chat`, na ordem 2) e **google** serve `visao` e `embeddings`. A primeira versão
desta tabela dava `embeddings` ao openai e `conversa` ao google — **nenhuma das
duas é servida por esses fornecedores**, e declarar uma finalidade a mais é
pedir autorização para uma transferência que não existe. Corrigido depois da
revisão adversarial.

---

## 3. Destinos

Uma linha por destino. **`apd_ref`: nenhum destino tem referência**, porque
nenhuma submissão foi feita — ver [`Seguimento_APD.md`](Seguimento_APD.md).

| # | Destino (`../../08` §8.3.2) | Função | Dados pessoais | País (hipótese) | Finalidade | **Retenção proposta** | Garantias pedidas | Saída declarada hoje | `apd_ref` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Meta (WhatsApp Cloud API) | Canal | Conteúdo, telefone ou identificador | EUA/UE (**NÃO VERIFICADO**) | Canal da conversa | Fora do nosso controlo: é a política da Meta *(a confirmar — pergunta A-11)* | Termos da plataforma; notificação separada a confirmar (pergunta A-11) | **Não** — `gwy` e `worker-canal` com `destinos: []` | — |
| 2 | Fornecedor de modelo e transcrição (EUA) | Modelo de linguagem; transcrição prevista | Texto minimizado, áudio | EUA | **`conversa`** | **Retenção zero** pedida por contrato; áudio ≤ 24 h do nosso lado | Retenção zero e não-treino, **a confirmar por fornecedor** | **Sim** — `api.openai.com`, como fornecedor de modelos | — (`pendente`) |
| 3 | Fornecedor de modelo (EUA) | Modelo de linguagem | Texto minimizado | EUA | `conversa` | **Retenção zero** pedida por contrato | Idem | **Sim** — `api.anthropic.com` | — (`pendente`) |
| 4 | Fornecedor de modelo (EUA/UE) | Visão e vectores de catálogo | Texto minimizado, imagem | EUA/UE | **`visao`, `embeddings`** | **Retenção zero** pedida por contrato | Idem | **Sim** — `generativelanguage.googleapis.com` | — (`pendente`) |
| 5 | Fornecedor de transcrição (EUA) | Transcrição de áudio | Áudio | EUA | `conversa` | **Retenção zero** pedida por contrato; áudio ≤ 24 h do nosso lado | Idem; preferir transcrever em destino já autorizado | **Não** — não está em `infra/egress/litellm.yaml`, e o ficheiro di-lo: é STT e não entra num ticket de *gateway* de modelos | — |
| 6 | Alojamento de produção | Computação, base de dados | **Todas as classes** | **Angola ou África do Sul — D1 não decidida** | Tratamento | **Todas as classes do §2**, cada uma com o seu prazo | Contrato; 2.º local para backups | Não aplicável (é a origem, não uma saída) | — |
| 7 | Repositório de cópias de segurança | Cópias cifradas | **Todas as classes** | **A decidir com D1**; 2.º domínio de falha | Recuperação | Escrita antecipada 7 dias; diárias 35 dias (`../../08` §11) | Cifra do repositório com chave em cofre, cópia offline | Não aplicável | — |
| 8 | CDN e firewall aplicacional | Termina TLS | **Conteúdo em trânsito** | Global | Entrega e protecção | Em trânsito; sem persistência pedida | **Qualificação a confirmar — pergunta E-04** | Não declarado | — |
| 9 | Facilitador de pagamentos | Pagamentos | Valor, referência, telefone do pagamento | Angola | Cobrança | Prazo do facilitador; do nosso lado, prazo fiscal **NÃO VERIFICADO** | Contrato | **Não** — `com` com `destinos: []` | — |
| 10 | Software de facturação certificado | Facturas | Dados do cliente na factura | Angola (a confirmar) | Facturação | Prazo fiscal **NÃO VERIFICADO** (pergunta C-05) | Contrato | Não declarado | — |
| 11 | Cofre de segredos | Segredos | **Nenhum, por regra** | EUA | Operação | Não aplicável — sem dados pessoais | Regra: nenhum dado pessoal | Não declarado | **Não aplicável** |
| 12 | Correio ou SMS transaccional | Notificações | Contacto | **A decidir** | Notificação | A decidir com o fornecedor | A decidir | Não declarado | — |
| 13 | **Sonda sintética externa** | Verifica que a ingestão não parou | **Mensagem de teste, sem dados de titulares** | A decidir | Observação | Mensagem de teste; sem dados de titulares | Mensagem própria no número de teste de produção | Não declarado | **A confirmar** |
| 14 | **Fornecedor de melhoramento de imagem** | Imagem de catálogo | Fotografias enviadas pelo dono | Estrangeiro, a decidir | `visao` | Sem retenção pedida; fotografias vivem no catálogo | Sem retenção nem treino, a verificar | Não declarado | — |

### 3.1 O que a reconciliação encontrou

O critério 6 do KAM-105 enumera os destinos a cobrir, o `../../08` §8.3.2 tem o
inventário, e o `egress` tem a realidade. **As três listas não coincidem**, e as
divergências são achados:

| Divergência | Leitura |
|---|---|
| A **sonda sintética externa** (`../../09` §9.1) não tem linha no inventário do `../../08` §8.3.2, e o critério 6 nomeia-a | Entra aqui como destino **13**. Não trata dados de titulares — envia uma mensagem de teste própria —, mas é saída para fora do anfitrião e do fornecedor, e o §8.3.1 sujeita «ferramentas de observabilidade» ao *gate*. **Qualificação a confirmar** |
| O **fornecedor de melhoramento de imagem** não tem linha no §8.3.2, apesar de o `../../03` §17 e o `../../08` §18 o tratarem como subprocessador no estrangeiro | Entra aqui como destino **14**. É a lacuna que o anexo do KAM-104 declarou, e o `../../08` §18 atribui-a ao **KAM-069** |
| As **cópias de segurança** aparecem no §8.3.2 dentro da linha do alojamento; o critério 6 pede-as como destino próprio | Separadas aqui (**6** e **7**), porque o `../../09` §8.1 diz que «o repositório de backup também é alojamento para o ADR-008» e pode ficar noutro domínio de falha — logo noutro país |
| O §8.3.2 tem **três** fornecedores de modelos e **dois** de transcrição; o `egress` declara **três** FQDN, **nenhum pela finalidade de transcrição** — o `api.openai.com` está declarado como fornecedor de modelos em `infra/egress/litellm.yaml`, e o `api.groq.com` está fora, o que o próprio ficheiro diz («é STT e não entra num ticket de *gateway* de LLM») | O desenho prevê mais destinos do que a pilha declara. O critério 6 manda reduzir ao mínimo: ver §4 |
| O §8.3.2 lista a **Cloudflare** pelo nome; aqui os fornecedores aparecem pela função | Matéria contratual em aberto. A submissão à APD exigirá o nome; o mapa fica pronto para o receber |
| **Dois componentes da pilha não têm lista de saída nenhuma:** o Medusa e a pilha de observação (Prometheus, Grafana, Loki), que o `../../09` §3.1 lista como parte do Piloto | O `../../08` §8.3.1 sujeita «ferramentas de observabilidade» ao *gate* de transferência, e sem lista não há contrato a aplicar. Não é deste ticket — é do regime de `egress` (KAM-067) e da sua aplicação (KAM-076) —, mas fica medido |
| **`packages/` e `libs/` estão fora do regime de `egress`** — zero ficheiros —, e é lá que vive o cliente com `graph.facebook.com` fixo | Ver §0. É o caminho de saída que nenhuma lista cobre; hoje nenhum serviço o instancia |

---

## 4. Redução de destinos de produção ao mínimo

O critério 6 pede que «o número de destinos de produção do Piloto seja reduzido
ao mínimo (*proposta*: 1 LLM, 1 STT)». **Proposta da KAMBÁ, não decisão:**

| Hoje no desenho | Proposta para o Piloto | O que se perde |
|---|---|---|
| 3 fornecedores de modelos (destinos 2, 3, 4) | **1** | O *fallback* entre fornecedores. O `infra/egress/litellm.yaml` tem o segundo na lista precisamente «para que o *fallback* não use um destino que ninguém aprovou»: reduzir a um significa que **uma falha do fornecedor degrada para o modo determinístico**, não para outro fornecedor |
| 2 fornecedores de transcrição (destinos 2, 5) | **1** | Redundância de transcrição; a voz fica com um único destino |
| Fornecedor de imagem (destino 14) | **Nenhum no Piloto**, se os módulos de entrada ficarem fora | Catálogo por fotografia. Depende do âmbito do Piloto, não deste mapa |

**Cada destino retirado é uma autorização que não se pede, um contrato que não se
negocia e um risco que não se corre** — e, com 5 a 10 PMEs, a redundância vale
menos do que isso. **Mas a decisão é de Produto e de Segurança**, porque o
*fallback* é uma propriedade de disponibilidade: um destino único faz do
fornecedor um ponto de falha do produto.

---

## 5. O que este mapa não pode dizer

| Em falta | Porquê |
|---|---|
| **`apd_ref` de qualquer destino** | Nenhuma submissão foi feita — é o critério 7 do KAM-105, e é acto humano |
| **País de cada destino, confirmado** | Os países são hipóteses, a confirmar **contratualmente** com cada fornecedor |
| **O país do alojamento e das cópias** | **D1 não está decidida** — é o critério 2 do KAM-105 e a decisão é do fundador |
| **Se a Meta exige notificação separada** | Pergunta A-11 do pacote |
| **Se o CDN que termina TLS é subprocessador** | Pergunta E-04; e nenhuma das duas opções do `../../08` §8.3.2 está decidida |
| **Prazo de conservação fiscal** | NÃO VERIFICADO. É o parâmetro de retenção **de maior impacto** sem valor fixado, e não o único: o prazo de prova dos consentimentos e da prova de contrato também está «a confirmar» no `../../08` §11 (pergunta C-05) |
| **O estado real de `tenant_destinations`** | A tabela não existe (KAM-069). Até existir, este mapa é a única configuração de destinos que há, e é um documento — não um mecanismo |

---

## 6. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Arquitecto de Plataforma | | | |
| Responsável de Produto | | | |
| Advogado externo (apreciação) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial, KAM-105. Mapa por destino gerado de **três** fontes — as classes do `../../08` §7.1, o inventário do §8.3.2 e, o que o torna verificável, as listas de saída reais da pilha (`infra/egress/litellm.yaml` e os cinco `services/*/egress.yaml`). Catorze destinos, nenhum com `apd_ref`. A reconciliação das três listas encontrou cinco divergências, entre elas dois destinos sem linha no inventário: a sonda sintética externa e o fornecedor de imagem. Registada a consequência verificável em código: as saídas que levariam dados pessoais de produção **não estão declaradas**, e as três declaradas falham fechadas sem `apd_ref`. D9 fica provisória e a entidade que paga os custos em USD fica em aberto, por ser decisão do fundador. | Equipa KAMBÁ |

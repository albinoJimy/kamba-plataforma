# Gate de go-live — entrada de dados reais

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — checklist de entrada de dados reais em produção |
| Versão | 1.1 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno; **regra de bloqueio operacional** |
| Ticket | KAM-105 (EPIC-10) |
| Documento-fonte | `../../08_Seguranca_Conformidade.md` §8.5, §8.6, §8.3; `../../09_Topologia_Operacao_Escala.md` §6; o registo de decisões da Carta, §4.2 |
| Relacionados | [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), [`Seguimento_APD.md`](Seguimento_APD.md), [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) |

> **Este documento não decide nada: mede.** Cada linha é uma condição objectiva
> com estado e data. **Enquanto uma única linha obrigatória estiver em branco ou
> `não`, não entram dados reais em produção** — é o que a Carta §4.2 quer dizer
> com «sem D1 não há dados reais», e o que o `../../08` §8.6 chama gate de
> go-live.
>
> **Hoje nenhuma linha obrigatória está satisfeita**, e isso não é um atraso: é
> o estado correcto de um produto que ainda não tem parecer jurídico nem
> procedimento submetido. O valor deste documento é tornar o «ainda não» legível
> e datável, em vez de uma impressão.

---

## 0. Como se lê

| Estado | Significado |
|---|---|
| `satisfeito` | A condição está cumprida, com a evidência nomeada na coluna |
| `não` | Medida e não cumprida |
| `em branco` | Não medida ainda |
| `não aplicável` | Com a razão escrita |

**Uma linha só passa a `satisfeito` com evidência nomeada** — um número de
protocolo, uma assinatura com data, um comando com o seu resultado. «Está
tratado» não é evidência.

---

## 1. Bloco A — Decisões (sem estas, nada abaixo importa)

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| A1 | **D1 decidida**: alojamento em Luanda ou em JNB/CPT, com dono e assinatura | Carta §4.2; KAM-105 critério 2 | Sim | **em branco** | Depende de ≥ 3 cotações: [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md). Nenhuma pedida | |
| A2 | **D9 decidida**: papel da KAMBÁ e quem notifica a APD | Carta §4.2; `../../08` §8.2 | Sim | **em branco** | Há **registo provisório** no [`Seguimento_APD.md`](Seguimento_APD.md) §3, que não é decisão e não fecha esta linha. Depende da pergunta A-01 do parecer | |
| A3 | **D9, segunda metade**: entidade que paga os custos em USD | Carta §4.2; `../../09` §19 | Sim | **em branco** | **Decisão do fundador.** Pergunta F-02 do parecer; a KAMBÁ não recomenda nenhuma das opções | |
| A4 | **D6 decidida**: armazenamento de objectos | Carta §4.2 | Não — recomendação basta para o gate | **satisfeito** | Recomendação por cenário de D1 em [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) **§6**, com quatro testes pendentes; decisão final em KAM-011 | 2026-11-02 |
| A5 | **D12 decidida**: o CDN que termina TLS é subprocessador? | Carta §4.2; `../../08` §8.3.2 | Sim, **se** o caminho de webhooks ficar atrás do proxy | **em branco** | Pergunta E-04 do parecer. **Há um caminho que dispensa a decisão:** não pôr o caminho de webhooks atrás do proxy — ver nota em §5 | |

---

## 2. Bloco B — Procedimento junto da APD

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| B1 | **Mapa de tratamentos aprovado** e assinado | `../../08` §8.6 (1) | Sim | **em branco** | Mapa **emitido e não aprovado**: [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), v1.0, com a tabela de aprovação em branco | |
| B2 | **Cada destino de produção com `apd_ref` válido**, ou decisão escrita do advogado de que não é exigido | `../../08` §8.3.1, §8.6 (3) | Sim | **não** | **0 de 14** destinos com `apd_ref`. Por destino: bloco E desta checklist; folha de seguimento em [`Seguimento_APD.md`](Seguimento_APD.md) §1 | |
| B3 | **Taxas pagas**, com comprovativo | `../../08` §8.6 (4) | Sim | **em branco** | Decreto Presidencial 60/21, 4.315 a 350.450 Kz (**INDÍCIO**); valor aplicável a este caso é a pergunta A-03 | |
| B4 | **Número de protocolo** de recepção por submissão | KAM-105 critério 7 | Sim | **em branco** | Nenhuma submissão feita | |
| B5 | **Prazo de resposta da APD conhecido**, e silêncio positivo esclarecido | `../../08` §8.6 | Não — informa o prazo, não bloqueia | **em branco** | **NÃO VERIFICADO.** Pergunta A-03 do parecer | |

---

## 3. Bloco C — Contratos e textos publicados

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| C1 | **Contrato de subcontratação (DPA)** redigido e aceite por cada PME, como condição de activação | `../../08` §8.5 req. 4, §8.6 (5) | Sim | **não** | **Não está redigido.** KAM-090; existe a lista de cláusulas dos termos de utilização, que não é um DPA | |
| C2 | **Aviso de privacidade publicado e versionado** | `../../08` §8.4, §8.6 (5) | Sim | **não** | **O texto não existe.** KAM-090 e KAM-022; a tabela de textos nasce vazia e o controlo falha fechada, pelo que sem aviso publicado o assistente não corre | |
| C3 | **Lista pública de subprocessadores** | `../../08` §8.5 req. 4 | Sim | **em branco** | Deriva do [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md) §3; os nomes dos fornecedores são matéria contratual em aberto | |
| C4 | **Contrato com cada fornecedor**, com retenção zero e não-treino, arquivado | `../../08` §8.3.1, §8.5 req. 8 | Sim, por destino usado | **em branco** | Checklist por fornecedor; nenhum assinado | |

---

## 4. Bloco D — Controlos técnicos

Estes não dependem do advogado nem do fundador: dependem de código, e por isso
são os únicos que a equipa fecha sozinha.

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| D1t | **`tenant_destinations` existe e o *gate* falha fechado** sem linha `autorizado` | `../../08` §8.3.1; KAM-069 | Sim | **satisfeito** | KAM-069: a tabela é a revisão `0036` e a porta que a lê é `libs/py-core/src/kamba_core/destinos/`, negada por omissão e com falha fechada em cinco caminhos (sem linha, estado que bloqueia, `apd_ref` nulo, finalidade fora do domínio, erro da base — e o erro da base **não** fica em *cache*). O `arrancar` do AGR devolve essa porta, e a vista `platform.v_transfer_audit` mede o mesmo pelo outro lado, com a regra da porta. **Esta linha afirma a barreira e não a autorização**: a B2 continua `não`, com 0 de 14 destinos com `apd_ref`, e é ela que bloqueia os dados reais | 2026-11-08 |
| D2t | **Listas de saída declaradas e aplicadas na rede** | `infra/egress/`, `services/*/egress.yaml`; KAM-076 | Sim | **não** | Os contratos existem — treze listas, `por_omissao: negar`, três FQDN em `infra/egress/litellm.yaml` e `destinos: []` nas outras doze —, mas **a aplicação na rede é o KAM-076 e não está feita**, e o Medusa e a pilha de observação não têm lista nenhuma. Enquanto não houver aplicação, uma lista é um contrato e não uma barreira | |
| D3t | **Checklist de segurança do `../../08` §8.5 #11**: TLS, cifra em repouso, segregação entre PMEs, MFA, auditoria de acessos — com **pentest antes do go-live** | `../../08` §8.5 #11 | Sim | **em branco** | Dono: Responsável de Segurança. O pentest não está agendado | |
| D4t | **Isolamento entre PMEs verificado** — zero leituras cruzadas | `../../08` §3, §14 | Sim | **satisfeito** | Suite de testes cruzados entre PMEs que corre em cada alteração e **faz falhar a construção**; alvo medido **zero** leituras cruzadas | 2026-11-02 |
| D5t | **Minimização antes do modelo a correr** | `../../08` §7.4; KAM-112 | Sim | **satisfeito** | KAM-112, fundido em `eb44f9b`. O valor **jurídico** depende da pergunta A-02 — o controlo existe, a sua suficiência é que está por confirmar | 2026-10-30 |
| D6t | **Registos sem conteúdo**, verificados por varredura | `../../08` §7.3 | Sim | **satisfeito** | Registador tipado com lista fechada de campos e varredura por padrões de telefone angolano e de NIF | 2026-11-02 |
| D7t | **Retenção e purga por classe**, com registo de eliminação | `../../08` §11, §8.5 req. 14 | Sim | **não** | O agendador nasce com KAM-071; o prazo fiscal é **NÃO VERIFICADO** e até confirmação não se eliminam registos fiscais | |
| D8t | **Direitos do titular**: acesso, correcção, eliminação, exportação | `../../08` §8.5 req. 13 | Sim | **não** | KAM-070 | |
| D9t | **Cópias de segurança noutro domínio de falha, com restauro testado** | `../../09` §8 | Sim | **em branco** | Depende de D1 (o repositório também é alojamento para o ADR-008) | |
| D10t | **Ambientes separados; `staging` nunca com cópia de produção** | `../../09` §6 | Sim | **satisfeito** | `dev` e `staging` com dados **sintéticos**, pela tabela do `../../09` §6. **Satisfeito por desenho e não por medição:** nada impede hoje, mecanicamente, uma cópia de produção para pré-produção — o que a impede é não haver produção | 2026-11-02 |

---

## 4.1 Bloco E — uma linha por destino

O segundo «Teste Requerido» do KAM-105 pede que **nenhum destino de produção
fique sem linha neste ficheiro**. A condição B2 agrega os catorze num número, e
um número não diz **qual** falta — que é a única coisa para que uma checklist de
bloqueio por destino serve. Daí este bloco: uma linha por destino do
[`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md) §3.

| # | Destino | `apd_ref` | Contrato com retenção zero e não-treino | Estado | Data |
|---|---|---|---|---|---|
| E1 | Meta (WhatsApp Cloud API) | **não** | Termos da plataforma; notificação separada a confirmar (A-11) | **não** | |
| E2 | Fornecedor de modelo e transcrição (EUA) | **não** (`pendente`) | **não assinado** | **não** | |
| E3 | Fornecedor de modelo (EUA) | **não** (`pendente`) | **não assinado** | **não** | |
| E4 | Fornecedor de modelo (EUA/UE) | **não** (`pendente`) | **não assinado** | **não** | |
| E5 | Fornecedor de transcrição (EUA) | **não** | **não assinado** | **não** | |
| E6 | Alojamento de produção | **não** | — depende de D1 | **não** | |
| E7 | Repositório de cópias de segurança | **não** | — depende de D1 | **não** | |
| E8 | CDN e firewall aplicacional | **não** | Qualificação a confirmar (E-04); ver §5 | **não** | |
| E9 | Facilitador de pagamentos | **não** | Contrato D4, não assinado | **não** | |
| E10 | Software de facturação certificado | **não** | Contrato D7, não assinado | **não** | |
| E11 | Cofre de segredos | **não aplicável** — sem dados pessoais, por regra | Não aplicável | **não aplicável** | 2026-11-02 |
| E12 | Correio ou SMS transaccional | **não** | Fornecedor a decidir | **não** | |
| E13 | Sonda sintética externa | **a confirmar** — qualificação em aberto | Mensagem própria, sem dados de titulares | **não** | |
| E14 | Fornecedor de melhoramento de imagem | **não** | **não assinado**; sem linha no inventário (KAM-069) | **não** | |

**1 de 14 resolvido**, e por ser «não aplicável». As outras treze dependem do
bloco B, que depende do parecer.

---

## 5. Notas que mudam o que o gate exige

**Alojar em Luanda não dispensa o bloco B.** O `../../09` §5.1 e o `../../08`
§8.3.1 dizem-no: os modelos, a transcrição e a própria Meta seriam
transferências — **INDÍCIO**, e é o que a pergunta A-02 pede *(a confirmar por
parecer)*. Escolher Luanda reduz o número de destinos a autorizar; não remove o
procedimento.

**A linha A5 tem um caminho que a dispensa, e é executável hoje.** O
`../../08` §8.3.2 escreve duas opções para o CDN que termina TLS e **nenhuma
está decidida**: (a) assumi-lo como subprocessador e incluí-lo na notificação;
(b) **não** pôr o caminho de webhooks atrás do proxy — a assinatura da Meta já
autentica o pedido — e proteger a origem com limitação de débito. A opção (b)
**não precisa de parecer** e retira conteúdo do perímetro em vez de o
justificar. É decisão pendente de SRE, não um item assumido.

**Os dados sintéticos não passam por este gate.** O `../../09` §5.3 ponto 2 e o
§6: `dev` e `staging` com dados sintéticos ficam fora do âmbito dos Arts. 33.º e
34.º e podem correr em qualquer região. Este gate governa **dados reais em
produção**, e só esses.

**Há uma excepção pedida, e está por responder.** Dois spikes de Fase 0 — o de
coexistência e o de voz — precisam de **dados reais de teste com
consentimento** na semana 1, antes de qualquer procedimento estar concluído. É a
pergunta F-01 do parecer, e a alternativa é risco aceite por escrito pelo
fundador. **Não é uma passagem por este gate: é uma excepção a ele**, e como tal
tem de ficar registada com quem a autorizou.

---

## 6. Contagem, ao dia de hoje

Contado por máquina sobre a coluna «Estado», e **só com os quatro valores do
§0** — a primeira versão desta tabela usava seis (`parcial`, `satisfeito por
desenho`, prosa) e a contagem mapeava-os em silêncio, o que a revisão
adversarial apanhou. Agora cada linha tem um dos quatro, e a nuance mudou para
a coluna «Evidência».

| Bloco | Linhas | Obrigatórias | `satisfeito` | `não` | `em branco` | `não aplicável` |
|---|---|---|---|---|---|---|
| A — Decisões | 5 | 4 | 1 | 0 | 4 | 0 |
| B — Procedimento APD | 5 | 4 | 0 | 1 | 4 | 0 |
| C — Contratos e textos | 4 | 4 | 0 | 2 | 2 | 0 |
| D — Controlos técnicos | 10 | 10 | 4 | 4 | 2 | 0 |
| E — Por destino | 14 | 14 | 0 | 13 | 0 | 1 |
| **Total** | **38** | **36** | **5** | **20** | **12** | **1** |

**Como se reproduz esta contagem**, para que não seja preciso acreditar nela: os
estados leem-se da coluna «Estado» das linhas identificadas `A1`–`A5`, `B1`–`B5`,
`C1`–`C4`, `D1t`–`D10t` e `E1`–`E14`, e cada uma tem **exactamente um** dos
quatro valores do §0 — medido, 38 linhas e 38 estados. A coluna «Obrigatória»
existe nos blocos A a D e dá **22**; as **14** linhas do bloco E não a têm, e
são todas obrigatórias por força da condição **B2**, que exige `apd_ref` válido
em cada destino de produção. Daí **36**: 22 mais 14. As duas não obrigatórias são
a **A4** (a recomendação de D6 basta para o gate) e a **B5** (o prazo da APD
informa, não bloqueia).

**5 de 36 condições obrigatórias satisfeitas.** Quatro são do bloco técnico — as
que não dependem de ninguém de fora — e a quinta é a recomendação de D6, que o
gate aceita como suficiente. **Nenhuma condição dos blocos B, C e E está
satisfeita**, e é coerente: o pacote de perguntas ao advogado **não foi
enviado**, e enquanto não for, nem o parecer nem as decisões nem as submissões
que dele dependem podem existir.

**As datas.** Só as linhas `satisfeito` e `não aplicável` levam data, que é a do
commit ou do merge que as satisfez; as `não` e as `em branco` ficam sem data de
propósito — datar uma condição não cumprida era datar o quê.

---

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Arquitecto de Plataforma | | | |
| Responsável de Produto | | | |
| Fundador (autoriza a entrada de dados reais) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-105. **22** condições obrigatórias em quatro blocos — decisões, procedimento junto da APD, contratos e textos, controlos técnicos —, cada uma com fonte, estado, evidência e data. Ao dia de hoje **4 de 22** satisfeitas, todas do bloco técnico; nenhuma dos blocos A, B e C, porque o pacote de perguntas ao advogado ainda não saiu. Registadas três notas que mudam o que o gate exige: Luanda não dispensa o procedimento, a linha do CDN tem um caminho executável que dispensa a decisão, e os dados reais de teste dos spikes são uma **excepção** ao gate e não uma passagem por ele. | Equipa KAMBÁ |
| 1.1 | Novembro de 2026 | **KAM-069: a linha D1t passa a `satisfeito`**, com a evidência nomeada que esta folha exige — a revisão `0036` e a porta de `libs/py-core/src/kamba_core/destinos/`, negada por omissão e com falha fechada em cinco caminhos. **É a primeira linha obrigatória desta checklist a sair de `não`, e não aproxima os dados reais:** a B2 continua `não` com **0 de 14** destinos com `apd_ref`, e é ela que bloqueia. O resto da folha não é tocado. |

# EPIC-10 — Spikes, Validação e Gates

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Spikes, Validação e Gates |
| Versão | 1.13 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md` (§13), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/08_Seguranca_Conformidade.md` (§8, §13), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§5), `../docs/tecnica/10_Onboarding_Governanca.md` (§6), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/00_KAMBA_Carta.md`, `specs/EPIC-02_Canais_WhatsApp_Handoff.md`, `specs/EPIC-08_Topologia_Operacao.md`, `specs/01_Engineering_Standards_e_Handoff.md` |

---

## 1. Visão do Epic

Este epic **não entrega funcionalidade de produto**: entrega factos, medições, decisões e dois gates. Reúne (a) os sete itens com **tempo de espera externo** que arrancam na semana 1, em paralelo ao código, e que são o caminho crítico real (`14` §3A Regra 3; `INDICE.md` §3.3): o spike de coexistência com três números +244 (KAM-100), as perguntas escritas à Meta (KAM-101), o estatuto de Tech Provider (KAM-102), os contratos de pagamento (KAM-103), o pacote para o parecer jurídico (KAM-104), a decisão de alojamento e o procedimento APD (KAM-105) e os canais de acesso a PMEs com 30 entrevistas (KAM-106); (b) o spike de voz PT-AO (KAM-107); e (c) os gates: o da Fase 0 (KAM-108), a medição do piloto (KAM-109) e o da decisão continuar, pivô ou parar (KAM-110).

Existe porque o documento 14 impõe que **cada hipótese morra ou sobreviva com um número** (H1–H9, limiares *propostos* pelo fundador) e porque várias dependências críticas são **NÃO VERIFICADAS** em `../docs/tecnica/evidencia/`: coexistência em +244, classificação da KAMBÁ como *AI Provider*, prazo e documentos da Business Verification, preços da ProxyPay, prazo de onboarding bancário, enquadramento BNA do modelo facilitador, procedimento e prazos da APD e qualidade do STT em português de Angola. Cada ticket fecha um desses itens ou regista o pivô previsto em `14` §6; nenhum facto NÃO VERIFICADO passa a requisito sem esse critério de saída. Concretiza ADR-001 (coexistência e Tech Provider), ADR-004 e ADR-013 (facilitador, D4, D8), ADR-008 (D1, D9), ADR-011 (D2), ADR-012 (regra de dois, no gate da Fase 0), ADR-018 (golden sintético e Termos da Meta sobre ML) e ADR-019 (onboarding self-service no Piloto). Os donos de decisão seguem o registo da Carta (`00_KAMBA_Carta.md` §4.2).

**Natureza dos tickets.** Os critérios de aceitação são **saídas verificáveis**: documento com campos definidos, tabela de medição com limiar de sucesso e de falha, decisão registada com dono e data, ficheiro de evidência em `../docs/tecnica/evidencia/validacao/`. O Claude Code **prepara** guiões, modelos, *scripts* de medição e folhas de registo; **não** conduz reuniões, entrevistas nem recebe respostas de terceiros, e nenhuma decisão é automática. Pareceres, respostas da Meta, dos bancos e da APD são «a confirmar por parecer» ou por escrito; nada neste epic é aconselhamento jurídico. Os limiares de `14` §2 são propostas: fixam-se antes de medir e só mudam por emenda registada. Calendário de referência: H3 e H4 correm primeiro; ponto de decisão na semana 6 (`14` §3A Regra 5). Fases: 0 (KAM-100 a KAM-106, KAM-108) e 1 (KAM-107, KAM-109, KAM-110). Abreviatura: «`14`» designa `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md`; «E1» a «E5» designam `../docs/tecnica/evidencia/E1_…` a `E5_…`.

---

## 2. Critérios de Saída do Epic

- [ ] O **Registo de Hipóteses** (`../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md`) tem H1–H9 com limiar, amostra, resultado medido, estado (`confirmada`, `refutada`, `inconclusiva`), fonte, decisão, dono e data: 9 de 9 linhas completas.
- [ ] **H3:** os 3 números +244 foram testados e a decisão está registada até ao fim da semana 3; é revista na semana 6 (Regra 5). Falhar H3 aplica o pivô de `14` §6 (outro canal).
- [ ] **H4 e D5:** há resposta escrita da Meta sobre a classificação do caso de uso ou aprovação de Tech Provider até à semana 6 (ou risco aceite registado com plano B); D5 (Tech Provider directo, MPS ou BSP) decidida até à semana 4.
- [ ] **H5 e D4:** pelo menos 2 bancos e 2 facilitadores contactados, com respostas escritas às perguntas de `E2` §9; prazo e custo por PME conhecidos; D4 decidida; sem contrato à semana 6 o Piloto fica em `ManualProvider`.
- [ ] **Jurídico e alojamento:** pacote enviado com 100% das perguntas P0 de `../docs/tecnica/08` §13; parecer P0 recebido ou prazo comprometido por escrito; D1 e D9 decididas e submissão à APD com número de protocolo antes de qualquer dado real.
- [ ] **H1 e H2:** 30 entrevistas completas (H2 medido com o limiar de `14` §2) e 5 canais de acesso testados, cada um com decisão (manter, descartar).
- [ ] **Voz:** relatório de WER e latência de 2 STT com áudio PT-AO real e decisão sobre o STT primário (ou de que a voz fica só em *handoff*).
- [ ] **KAM-108** concluído com o resultado do gate (verde, amarelo com itens datados, ou vermelho) assinado; **KAM-109** com H1, H6, H8 e H9 medidos por protocolo pré-registado; **KAM-110** com a decisão assinada.
- [ ] Todo o item NÃO VERIFICADO de `E1`–`E5` citado pelos tickets deste epic tem estado final (`fechado` com fonte, ou `mantido` com razão e dono).

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-100 | Spike H3: coexistência com três números +244 | spike | M | P0 | — |
| KAM-101 | Perguntas escritas à Meta: agregador, AI Provider, Access Verification, termos de ML | chore | S | P0 | — |
| KAM-102 | Business Verification, App Review e Tech Provider (D5) | chore | M | P0 | — |
| KAM-103 | Contratos de pagamento: bancos e facilitadores (D4) | chore | M | P0 | — |
| KAM-104 | Pacote de perguntas para o parecer jurídico (APD, BNA, AGT, Termos Meta) | chore | M | P0 | — |
| KAM-105 | Decisão de alojamento D1 e procedimento APD | chore | M | P0 | KAM-104 |
| KAM-106 | Canais de acesso a PMEs e 30 entrevistas (H1, H2) | chore | L | P0 | — |
| KAM-107 | Spike de voz PT-AO: WER e latência de dois STT com áudio real | spike | M | P1 | KAM-030 |
| KAM-108 | Gate da Fase 0: demonstração do esqueleto andante | chore | M | P0 | KAM-039, KAM-055, KAM-046, KAM-041, KAM-100, KAM-101, KAM-102 |
| KAM-109 | Piloto concierge e medição de H1, H6, H8 e H9 | chore | L | P0 | KAM-094, KAM-108, KAM-069, KAM-074, KAM-022, KAM-018, KAM-112, KAM-114, KAM-113 |
| KAM-110 | Gate do Piloto: decisão continuar, pivô ou parar | chore | S | P0 | KAM-109, KAM-074, KAM-085, KAM-040, KAM-082, KAM-083, KAM-105, KAM-069, KAM-103, KAM-106, KAM-113 |

---

## KAM-100 — Spike H3: coexistência com três números +244

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | spike |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-017, KAM-108 |
| Responsável sugerido | Engenharia de agentes/produto (com Plataforma/SRE) |
| Documentos de referência | `14` (§2 H3, §3A Regra 5, §6), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.3, §10, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§6.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§2, §5), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§4 ponto 10), ADR-001 |

### Contexto
A coexistência (a app WhatsApp Business do dono e a Cloud API no mesmo número) é a base do Fluxo A. A documentação da Meta não exclui Angola nem a inclui (NÃO VERIFICADO; fontes secundárias dizem «global», INDÍCIO). A coexistência exige ser Tech Provider ou Solution Partner (CONFIRMADO), e não se sabe se o spike pode correr antes da aprovação do KAM-102 (NÃO VERIFICADO). Comportamentos por medir: sincronização de contactos e histórico (6 meses, 24 h, cada passo uma só vez), *echoes*, `PARTNER_REMOVED` e se as mensagens enviadas pela API geram *echo* (NÃO VERIFICADO, `../docs/tecnica/01` §10.3).

### Objectivo
Determinar, com 3 números +244 reais e consentimento dos donos, se a coexistência funciona de ponta a ponta, medir a sincronização e os *echoes*, e registar a decisão H3 com o pivô aplicável.

### Critérios de Aceitação
- [x] **Passo 0 (até ao dia 2):** nota em `../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` a dizer se o ES v4 de coexistência pode correr antes da aprovação de Tech Provider (p. ex. app em modo de desenvolvimento com utilizadores com função): `Sim`, `Não` ou `NÃO VERIFICADO`, com data e fonte; se `Não`, o spike espera pelo KAM-102 e o novo prazo fica registado.
- [ ] O ficheiro tem uma linha por número (N1–N3) com: operadora (Unitel, Africell ou fixo), tipo, versão da app (≥ 2.24.17), `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` recebido (S/N), `history` recebido ou erro 2593109, n.º de contactos em `smb_app_state_sync`, tempo de sincronização (< 24 h), latência do *echo* (mediana de 10 envios), se uma mensagem enviada pela API gera *echo* (S/N), janela de 24 h aberta após resposta do cliente, eventos `account_update`, método de verificação (SMS ou voz).
- [ ] **Limiar H3 (`14` §2):** 3/3 ligados «sem perda de histórico», operacionalizado (*proposta*) como: em 20 conversas de controlo indicadas pelo dono, ≥ 95% das mensagens dos últimos 6 meses presentes por contagem; o erro 2593109 só conta como êxito se o dono recusou partilhar.
- [ ] Amostra: ≥ 1 número Unitel, ≥ 1 Africell e ≥ 1 fixo com verificação por voz, ou razão escrita para a ausência; entrega de SMS Unitel/Africell registada (S/N por número).
- [ ] **Regra de decisão registada (dono e data, fim da semana 3):** 3/3 → H3 `confirmada` e modo `coexistencia` por omissão; 2/3 → `inconclusiva`, causa isolada e `cloud_only` com número novo dedicado como alternativa por número; ≤ 1/3 ou exclusão explícita de Angola → `refutada` e pivô de `14` §6 (BSP parceiro, número novo ou produto sem automação no WhatsApp da PME). Revisão na semana 6 (Regra 5).
- [ ] Privacidade: consentimento escrito de cada dono; nenhum conteúdo de mensagem armazenado (só tipo de evento, ids, carimbos e contagens); registos apagados em ≤ 30 dias; sem segredos no repositório; excepção de dados reais de teste declarada em KAM-104.
- [ ] Entradas no Registo de Hipóteses (H3) e nota de entrega a KAM-017/KAM-018 com os factos medidos (latência de *echo*, eco da API, tempo de sincronização).

### Detalhes Técnicos
- **Componentes:** GWY e CHR **não** existem ainda; o *harness* é descartável em `spikes/h3/` e nunca é integrado nos serviços. Página mínima com ES v4 (`extras.featureType = "whatsapp_business_app_onboarding"`, `sessionInfoVersion: "3"`, *session logging*) e receptor de webhook que valida `X-Hub-Signature-256` sobre o corpo bruto, subscreve `messages`, `history`, `smb_app_state_sync`, `smb_message_echoes`, `account_update` e grava JSON-lines **sem campos de conteúdo**.
- **Esquema do Registo de Hipóteses** (usado por todos os tickets): `H | enunciado | limiar | método | amostra n | resultado | estado | fonte | decisão | pivô aplicável (14 §6) | dono | data`. Um validador (`scripts/validar_evidencia.py`) falha se faltar um campo ou se um ficheiro de evidência não declarar `Estado` (CONFIRMADO, INDÍCIO, NÃO VERIFICADO), `Fonte`, `Data` e `Dono`.
- O Claude Code prepara o *harness*, o *script* que calcula a tabela a partir dos JSON-lines, a folha de protocolo para o operador humano (verificar versão da app, anotar contagens, executar os 10 envios), o modelo do ficheiro de resultados e o validador. O operador humano executa o ES com cada dono; a decisão é humana.

### Testes Requeridos
- Ensaio do *harness* com o número de teste da Meta (WABA de teste): assinatura válida e inválida, corpo bruto, subscrição dos campos.
- Testes unitários do *script* de análise com *fixtures* (incluindo erro 2593109 e sincronização > 24 h) e teste de que o resultado não contém texto de mensagens.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Decisão H3 com dono e data no Registo de Hipóteses e no registo de decisões da Carta.
- [ ] Sem segredos no repositório (App Secret no cofre); consentimentos arquivados; registos apagados no prazo.
- [x] Nenhum conteúdo de conversa nem telefone em claro nos ficheiros de evidência (ADR-010).
- [ ] Itens NÃO VERIFICADOS de E1 §2 (elegibilidade de Angola, *echo* da API) com estado final.

### Handoff para Claude Code
```text
És o executor do ticket KAM-100 (spike H3) da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-100), docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§2 H3, §3A Regra 5),
docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4.3, §10, §13) e docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§2).
Objectivo: preparar o material para um spike com 3 números +244; NÃO falas com os donos nem decides o resultado.
- Cria spikes/h3/: página ES v4 de coexistência, receptor de webhook com validação de X-Hub-Signature-256 sobre o corpo bruto e gravação sem conteúdo.
- Escreve o script que gera a tabela N1-N3 e o modelo H3_Coexistencia_244.md, a folha de protocolo do operador e scripts/validar_evidencia.py.
- Cria o Registo_Hipoteses.md com as 9 linhas (limiares de 14 §2) por preencher.
- Marca NÃO VERIFICADO tudo o que não for medido; não guardes mensagens nem telefones; segredos fora do repositório.
Não expandas escopo: GWY/CHR reais são KAM-013/014. Testes: ensaio com o número de teste da Meta e unit do script. PR com o template da §7.
```

### Verificação dos Critérios de Aceitação

Entregue: o *harness* descartável em [`../spikes/h3/`](../spikes/h3/README.md), o
validador [`../scripts/validar_evidencia.py`](../scripts/validar_evidencia.py), e
dois ficheiros novos em `../docs/tecnica/evidencia/validacao/` —
[`H3_Coexistencia_244.md`](../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md)
e
[`Registo_Hipoteses.md`](../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md).
Caixas: **1 de 7 critérios** e **1 de 5 de DoD**.

As dez vazias têm quase todas a mesma causa, e ela está na letra do próprio
bloco: **«o operador humano executa o ES com cada dono; a decisão é humana»**.
Seis dos sete critérios dependem de três donos de número com consentimento
escrito, e nenhum deles é acto de executor. O que este ticket entrega é o que os
«Detalhes Técnicos» encomendam — o *harness*, o *script* da tabela, a folha do
operador, o modelo do resultado e o validador —, e nada disso é uma caixa. Cada
caixa vazia fica devolvida com credor nomeado no §6 do `H3_Coexistencia_244.md`.

| # | Critério | Estado | Evidência nomeada |
|---|---|---|---|
| 1 | **Passo 0:** nota a dizer `Sim`, `Não` ou `NÃO VERIFICADO`, com data e fonte | **satisfeito** | §1 do ficheiro, leitura de **2026-11-06**. A resposta é **`NÃO VERIFICADO`**, que é um dos três valores que o critério admite, e não um valor em falta: o requisito de ser Solution Partner ou Tech Provider é **CONFIRMADO** (`../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §2), e **nenhuma** das páginas registadas em E1 §2 ou §3 diz se a app em modo de desenvolvimento o satisfaz — nem para afirmar nem para negar. A segunda metade do critério («se `Não`, o spike espera pelo KAM-102 e o novo prazo fica registado») **não se activa**, e o §1.1 registra em vez dela o que é verdade: o spike está bloqueado por **uma pergunta sem resposta** e não por um `Não`; as duas vias de desbloqueio são a Q3/Q9 de [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) (as duas em `por enviar`) e a aprovação do **KAM-102**; e o prazo novo fica **NÃO VERIFICADO** porque depende de uma Business Verification cujo prazo a Meta **não documenta** (E1 §3) — escrevê-lo em semanas era inventar o número de que depende o caminho crítico da Fase 0 |
| 2 | O ficheiro tem uma linha por número (N1–N3) com as doze propriedades | **parcial, e a leitura fica devolvida** | §2 do ficheiro: as **três** colunas e as **catorze** linhas de propriedade existem, e o `tabela.py` gera-as — **oito** dos eventos e **seis** da folha do operador, com a conta e a lista presas por ensaio em vez de escritas na prosa. **Todas as células estão em `NÃO MEDIDO`**, porque nenhum número foi ligado. A leitura divide-se e não se decide aqui: *(a)* o critério diz «o ficheiro **tem** uma linha por número **com**: operadora, tipo, …», o que uma leitura estrutural dá por cumprido; *(b)* uma linha de `NÃO MEDIDO` tem as colunas e não tem os valores, e marcar a caixa dava por medido o que não foi. Escolheu-se **não marcar** e devolver a leitura ao **fundador** — §6, item 1. Medido e entregue a mais do que o critério pede: o §2.1 fixa a **regra do zero** (zero eventos escreve-se `NÃO MEDIDO` e nunca `N`, porque «não recebi o `FINISH`» e «não liguei o receptor a tempo» dão os mesmos zero eventos e refutam coisas opostas), com **uma** excepção — o *echo* da API, onde houve *echoes* e nenhum é nosso é prova de ausência |
| 3 | **Limiar H3:** 3/3 ligados «sem perda de histórico», operacionalizado como ≥ 95% em 20 conversas de controlo | **não satisfeito** | O limiar está **operacionalizado e escrito antes de medir**, que é a metade que tem de existir primeiro: §3 do ficheiro, com a amostra de controlo (20 conversas por número), o critério (≥ 95% por contagem), a janela de 6 meses e o prazo de 24 h, todos **CONFIRMADO** de `E1` §2. O que não está é **atingido**: **0 de 3** números ligados. E o §3 declara o que o *harness* **não** mede — os JSON-lines contam as mensagens que o `history` entregou, e quantas *deviam* estar lá conta-se na app do dono, conversa a conversa; apresentar a primeira metade sozinha dava por medida uma percentagem que não existe. Devolvido ao **fundador** — §6, itens 1 e 4 |
| 4 | Amostra: ≥ 1 Unitel, ≥ 1 Africell, ≥ 1 fixo com verificação por voz; entrega de SMS registada | **não satisfeito** | §3.1 do ficheiro tem os quatro requisitos como linhas, todas em `NÃO MEDIDO`, e a razão de o fixo exigir **voz** (`E1` §5: fixos são «não recomendados» para OTP por SMS). A **entrega de SMS internacional** em Unitel e Africell é **NÃO VERIFICADA** (idem) e é um dos resultados do spike, não uma pré-condição. O passo 1.4 e o 3.4 da folha do operador recolhem-nos. Devolvido ao **fundador** — §6, item 1 |
| 5 | **Regra de decisão registada** (dono e data, fim da semana 3) | **parcial** | **A regra está registada**, §4 do ficheiro: as três saídas transcritas do critério — 3/3 → `confirmada` e modo `coexistencia`; 2/3 → `inconclusiva`, causa isolada e `cloud_only` com número novo **por número**; ≤ 1/3 ou exclusão explícita de Angola → `refutada` e o pivô de `14` §6 — com a revisão na semana 6 pela Regra 5 de `14` §3A, e os dois modos ancorados em `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §10.1. O que falta é a **decisão**, com dono e data, e essa é do fundador (EPIC-10 §1: «nenhuma decisão é automática»). As linhas de assinatura ficam vazias. Devolvido ao **fundador** — §6, item 5 |
| 6 | Privacidade: consentimento escrito, nenhum conteúdo armazenado, registos apagados em ≤ 30 dias, sem segredos, excepção em KAM-104 | **parcial — 2 de 5** | **As duas de máquina estão CONFIRMADAS e medidas.** *Nenhum conteúdo armazenado:* `../spikes/h3/registo.py` é uma *allowlist* de **18** chaves com a **forma exacta** do valor de cada uma, e um valor fora da forma faz `ConteudoRecusado` em vez de ser aparado; os telefones **descartam-se e não se resumem** (um móvel de nove dígitos tem 10^8 hipóteses úteis e um resumo sem chave inverte-se por enumeração — ADR-010, `../docs/logs.md` §2.1), ficando no lugar o rótulo `N1`–`N3`, cuja correspondência vive fora do repositório. *Sem segredos:* o App Secret e o `hub.verify_token` entram por ambiente e o receptor **recusa arrancar** sem eles. As outras três — **consentimento escrito**, **apagamento em ≤ 30 dias** e a **excepção declarada em KAM-104** — são actos humanos ou de outro ticket. Devolvido ao **fundador** e ao **KAM-104** — §6, itens 1 e 5, e §5 do ficheiro |
| 7 | Entradas no Registo de Hipóteses (H3) e nota de entrega a KAM-017/KAM-018 | **parcial** | O [`Registo_Hipoteses.md`](../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md) **existe** e a linha H3 nasce com **limiar, método e pivô escritos** — que é o que tem de estar fixado antes de medir. As sete colunas de medição estão vazias, nas nove linhas: **63 células de 108**, contadas pelo validador e não à mão. A **nota de entrega** a KAM-017/KAM-018 não se escreve: os factos que ela devia levar — latência do *echo*, eco da API, tempo de sincronização — são precisamente os que não foram medidos, e uma nota de entrega sem factos é uma nota que o destinatário não pode usar. Devolvido ao **KAM-017** e ao **KAM-018** — §6, item 6 |

**DoD: 1 de 5.**

| # | DoD | Estado | Evidência nomeada |
|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | 1 de 7. Seis dependem de donos de número |
| 2 | Decisão H3 com dono e data no Registo de Hipóteses e no registo de decisões da Carta | **não satisfeito** | Sem medição não há decisão. Devolvido ao **fundador** |
| 3 | Sem segredos no repositório; consentimentos arquivados; registos apagados no prazo | **parcial — 1 de 3** | **Sem segredos: CONFIRMADO** (os dois entram por ambiente; o receptor recusa arrancar sem eles; o `scan_secrets` do gate 9 dá limpo sobre a árvore com estes ficheiros versionados). Consentimentos e apagamento são do operador |
| 4 | Nenhum conteúdo de conversa nem telefone em claro nos ficheiros de evidência (ADR-010) | **satisfeito** | **Medido por forma de valor, e não por nome de campo** — que é a distinção que torna isto uma medição. `../spikes/h3/tests/test_privacidade.py` corre três detectores (telefone nas **três** grafias, `wamid` em claro, e texto livre pela presença de um caractere fora do alfabeto estrutural) sobre a árvore de saída **e** sobre os bytes no disco, e corre-os **primeiro sobre a entrada** como **canário** — sem isso, um detector que devolvesse zero passava tudo, que é o modo de falha desta classe de ensaio. Os dois padrões de telefone são os canónicos de `../tools/contract_diff/pii.py`, importados e não recopiados; o terceiro é a forma **local** de nove dígitos, que nenhum dos dois apanha e que num ficheiro de evidência continuaria a ser um dado pessoal. **106 ensaios verdes** no *harness* e **27** no validador, e os dois ficheiros de evidência nascem sem telefone e sem conteúdo. Os literais com forma de móvel estão declarados no `INVENTARIO` de `../tools/meta-sim/src/inventario.ts` com **contagem exacta (5, num ficheiro)** e razão, medida com os dois padrões e não escrita à mão |
| 5 | Itens NÃO VERIFICADOS de E1 §2 (elegibilidade de Angola, *echo* da API) com estado final | **não satisfeito** | Os dois **mantêm-se** NÃO VERIFICADOS, com razão escrita, e é essa a resposta honesta: fechá-los exige o spike. A elegibilidade de Angola continua a ser ausência de exclusão e as fontes secundárias que dizem «global» continuam **INDÍCIO** — herdados de E1 e **não promovidos**. O *echo* da API tem agora **instrumento**: o `enviada_por_nos` do `../spikes/h3/extrair.py` confronta o `wamid` do *echo* com os que enviámos, e a coluna distingue `S`, `N` medido e `NÃO MEDIDO`. Devolvido ao **fundador** — §6, itens 1 e 2 |

---

## KAM-101 — Perguntas escritas à Meta: agregador, AI Provider, Access Verification, termos de ML

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | — |
| Bloqueia | KAM-049, KAM-058, KAM-108 |
| Responsável sugerido | Responsável de Produto |
| Documentos de referência | `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` («Perguntas que só a Meta/BSP pode responder», §3, §4, riscos 1–2), `14` (§2 H4, §3 ponto 4), `../docs/tecnica/00_Arquitectura_Solucao.md` (D2, D5, D10), ADR-001, ADR-011, ADR-018 |

### Contexto
A permissão do Fluxo B, a classificação como *AI Provider* («a seu exclusivo critério» da Meta, em vigor desde 2026-01-15), o detalhe da *Access Verification* e a cláusula dos Termos sobre treino de ML são NÃO VERIFICADOS em E1 e só a Meta os pode confirmar por escrito. As 15 perguntas de E1 estão redigidas mas não enviadas. O Fluxo B fica diferido (ADR-011) até haver resposta escrita; D2 é CONDICIONAL e D10 (canal operacional da KAMBÁ) fecha neste ticket (Carta §4.2). H4 (`14` §2) pede «resposta escrita ou aprovação» até à semana 6.

### Objectivo
Enviar as 15 perguntas de E1 à Meta (e as de custo a BSPs), registar cada resposta com fonte e classificação, e fixar a regra de decisão de H4 e o estado de D2 e D10.

### Critérios de Aceitação
- [x] `../docs/tecnica/evidencia/validacao/Meta_Perguntas.md` contém as 15 perguntas de E1, cada uma com: n.º, texto em EN e PT, secção de E1 que a origina, decisão afectada (D2, D5, ADR), ticket afectado, prioridade, canal, data de envio, estado (`enviada`, `respondida`, `sem resposta`).
- [ ] As 8 perguntas que condicionam o Piloto (classificação *AI Provider* Q2, coexistência +244 Q3, números fixos e SMS Q4, cláusula de ML §4.7 Q7, Business Verification de empresa angolana Q8, *Access Verification* Q9, pagamento local Q11, *timeout* e *retry* do webhook Q12) são enviadas até ao dia 5; as restantes (Q1, Q5, Q6, Q10, Q13, Q14, Q15) até ao dia 10.
- [ ] Cada resposta fica arquivada com texto integral, data, remetente, canal e classificação: CONFIRMADO só se for da Meta por escrito (Direct Support ou canal oficial); INDÍCIO se vier de BSP, parceiro, fórum ou verbal.
- [x] Os trechos com maior impacto de E1 (cláusula §4.7, definição de *AI Provider*, lista de países da coexistência, *Access Verification*) são relidos na fonte primária em inglês, com URL e data, e o desvio face a E1 é registado.
- [x] **Regra de H4 (registada até à semana 6):** `confirmada` se houver resposta escrita da Meta que não classifica o produto como *AI Provider*, ou aprovação de Tech Provider (KAM-102) — a aprovação sozinha não afasta o critério «exclusivo da Meta», e essa ressalva fica escrita; `inconclusiva` sem resposta à semana 6, com risco aceite pelo Responsável de Produto, plano B (cotação de BSP) e Fluxo B diferido; `refutada` se a Meta classificar como *AI Provider* ou recusar o caso de uso, com o pivô de `14` §6 (mudar de canal).
- [x] D2 e D10 registadas: D2 mantém-se CONDICIONAL com o estado das Q1/Q5/Q6; D10 regista a decisão provisória (canal do fundador no Piloto, risco assumido, `../docs/tecnica/10` §11.1) com gatilho na resposta da Meta.
- [ ] Seguimento: lembrete no dia 10 e escalamento por *Direct Support* após a aprovação de Tech Provider; datas de seguimento no ficheiro.

### Detalhes Técnicos
- **Classificação das perguntas.** Piloto: Q2, Q3, Q4, Q7, Q8, Q9, Q11, Q12. Fluxo B e Clusters: Q1 (agregador), Q5 (pagamentos nativos), Q6 (Meta Business Agent), Q10 (janela de entrada gratuita, 72 h ou 7 dias), Q13 (Commerce Policy), Q14 (limites por utilizador de marketing). Custo: Q15 (BSP; consumido pelo KAM-102).
- Canal antes da aprovação de Tech Provider: NÃO VERIFICADO (apoio de programador ou de Business Support); o canal usado fica registado. O Claude Code redige as perguntas em EN, mantém a folha de seguimento e verifica o texto das fontes primárias; **não** envia nada em nome da empresa.
- Citar com URL e data; resumir, sem reproduzir o texto integral dos Termos.

### Testes Requeridos
- Validação do ficheiro com `validar_evidencia.py`; revisão por pessoa distinta do autor de que as 15 perguntas de E1 estão todas presentes e sem alteração de sentido.
- Verificação de que cada resposta registada tem classificação CONFIRMADO ou INDÍCIO conforme a regra.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Registo de Hipóteses (H4) e registo de decisões (D2, D5, D10) actualizados com data e dono.
- [ ] Nenhum dado pessoal nem segredo nas mensagens enviadas; envio aprovado pelo Responsável de Produto.
- [x] Itens NÃO VERIFICADOS de E1 respondidos com estado final ou mantidos com razão.
- [x] Impacto de cada resposta nos tickets KAM-016, KAM-033, KAM-088 e Clusters listado.

### Verificação dos Critérios de Aceitação

Entregue: [`../docs/tecnica/evidencia/validacao/Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md). Caixas: **4 de 7 critérios** e **2 de 5 de DoD**. As cinco vazias têm todas a mesma causa — **enviar, aprovar e receber são actos humanos**, e este ticket prepara o dossiê sem os praticar. Cada uma fica devolvida com credor nomeado no §7 do ficheiro.

| # | Critério | Estado | Evidência nomeada |
|---|---|---|---|
| 1 | As 15 perguntas com os nove campos | **satisfeito, com duas leituras devolvidas** | §1 do ficheiro: um bloco por pergunta, **Q1 a Q15** (a numeração de E1, que o KAM-102 cita como «Q9 de KAM-101»), e verificação programática de que **os nove campos estão nos 15 blocos**, nenhum em falta. Texto **PT** igual ao de E1 **palavra a palavra** nas 15; texto **EN** redigido aqui, como os «Detalhes Técnicos» mandam, e o **§1.2** declara uma a uma as **nove** perguntas onde o inglês pede mais do que o português pedia — porque um acréscimo declarado é uma decisão que a revisão cruzada pode recusar, e um acréscimo calado é alteração de sentido a passar por tradução. Folha de seguimento no §1.1: **15 linhas, 15 em `por enviar`, 0 enviadas, 0 respondidas**. **Duas leituras ficam devolvidas ao Responsável de Produto** (§7, item 11), e não decididas aqui: (a) o critério fixa o estado em três valores e a folha nasce num quarto, `por enviar` — que é o estado **anterior** aos três e não um quarto resultado; o precedente é exacto e foi medido, porque o critério 7 do KAM-105 também nomeia quatro estados (`submetido`, `em apreciação`, `autorizado`, `negado`) e o [`Seguimento_APD.md`](../docs/tecnica/evidencia/validacao/Seguimento_APD.md) também nasce num quinto, `por submeter`; (b) o critério pede «decisão afectada» por pergunta e **13 das 15** nomeiam uma decisão ou um ADR — Q10, Q13 e Q14 nomeiam **—**, porque nenhuma decisão aberta depende delas, e inventar um `D#` para encher o campo era o defeito, não o remédio |
| 2 | Lote 1 (8) até ao dia 5; lote 2 (7) até ao dia 10 | **não satisfeito** | A **classificação** está feita e é verificável: §1, tabela dos lotes — **8** no lote 1 (Q2, Q3, Q4, Q7, Q8, Q9, Q11, Q12) e **7** no lote 2 (Q1, Q5, Q6, Q10, Q13, Q14 + Q15 de custo). O **envio** não está feito e não é do executor: o bloco diz «o Claude Code (…) **não** envia nada em nome da empresa». Devolvido ao **fundador** (única autoridade para comunicar em nome da empresa), por proposta do **Responsável de Produto** — §7, itens 1 e 2 |
| 3 | Cada resposta arquivada e classificada | **não satisfeito** | O **modelo** está no §2: regra de classificação pela **origem** (§2.1 — CONFIRMADO só da Meta por escrito; INDÍCIO para BSP, parceiro, fórum ou verbal, **verbal incluída mesmo vindo da Meta**) e a ficha com treze campos (§2.2). **Não há resposta nenhuma para arquivar**, e uma caixa marcada sobre zero respostas era verde vazio. A ficha nasce com a resposta. Devolvido ao **Responsável de Produto** — §7, item 4 |
| 4 | Os quatro trechos relidos na fonte primária em inglês, com URL e data, e o desvio registado | **satisfeito** | §3 do ficheiro, releitura a **2026-11-05**. Língua **inglesa** confirmada nos Termos (`?locale=en_US`, selector em «English (US)»). O §3 **fixa a regra de estado** antes de atribuir qualquer um: uma leitura por extracção automática dá **INDÍCIO**, e só duas leituras independentes a concordar — esta e a de E1, em duas línguas — dão CONFIRMADO. **Quatro desvios vivos**, medidos: **(0)** o rótulo «Updated» **não existe** em nenhuma das **quatro** páginas de `developers.facebook.com` relidas (resultado `NO UPDATED LABEL`), onde E1 atribui datas a todas — por isso a coluna «Data» dá a data da leitura e as de E1 ficam **nem confirmadas nem desmentidas**; **(1)** a restrição de treino de ML da cláusula **4.7** está **ligada ao caso de se contratar um *AI Provider* como *Solution Provider*** e tem **excepção** para afinar modelo de uso exclusivo próprio, onde E1 §4 a dá como proibição **geral** — e fica **INDÍCIO de uma leitura**, não CONFIRMADO, porque é de **âmbito** que trata e âmbito é o que esta classe de método erra primeiro; o **§3.1.1** reúne o que o ticket da L1 precisa de citar para o abrir **sem reler os Termos**, e nomeia os **cinco** outros sítios que afirmam a cláusula sem a condicionante, separados dos **seis** que já se declaram com ressalva e que a releitura confirma; **(2)** o inglês diz **«incidental or ancillary»**, não «acidental ou complementar»; **(3)** o historial de países da coexistência **não se reproduz**, e baixa a **INDÍCIO** nas duas direcções sem que a conclusão mude. **E um desvio morto, registado no §3.5** com a evidência que o matou: alegava-se que E1 trata como uma só as datas dos Termos (15 Jan 2026) e da política de preços (16 Fev 2026), e **E1 §1 já registava a segunda**, CONFIRMADA e com a mesma fonte — o achado nasceu de ler E1 §4 e não ler E1 §1, e fica escrito para não se pagar outra vez. Método declarado com o seu limite: **extracção automática**, a mesma classe que E1 declara nas suas «Limitações» (b), que não substitui leitura humana antes de uso contratual — e é isso que a **Q7** pede |
| 5 | Regra de H4 como lista de verificação, com a ressalva escrita | **satisfeito** | §4 do ficheiro: as três saídas como listas de verificação (`confirmada` §4.1 com as duas vias, `inconclusiva` §4.2, `refutada` §4.3) e o registo de H4 no §4.4, no esquema do §1 deste epic, com `amostra n = 0` e estado **`inconclusiva`** por omissão. A **ressalva está escrita**: a aprovação de Tech Provider sozinha não afasta o critério «exclusivo da Meta», pelo que `confirmada` **pela via B** deixa o risco 1 de E1 aberto e **não** fecha D2 nem levanta o diferimento do ADR-011. A **divergência de leitura** do próprio critério 5 (se a via B chega para `confirmada`) fica medida e **devolvida ao Responsável de Produto** — §7, item 7 —, e não foi decidida aqui |
| 6 | D2 e D10 registadas | **satisfeito** | §5 do ficheiro. **D2** mantida **CONDICIONAL** com o estado das três perguntas que a condicionam — Q1, Q5 e Q6, todas em `por enviar` — e gatilho na primeira resposta CONFIRMADO a Q1. **D10** registada como **provisória**: canal do fundador no Piloto, risco assumido e nomeado (linha pessoal, sem isolamento por *tenant*; o *tenant* `platform` vedado até D2), com a fonte em [`../docs/tecnica/10_Onboarding_Governanca.md`](../docs/tecnica/10_Onboarding_Governanca.md) §11.1, que já o documenta, e gatilho na resposta da Meta. **Registar não é fechar**: as linhas de assinatura ficam vazias e o fecho de D10 é do fundador (Carta §4.2) |
| 7 | Seguimento: lembrete ao dia 10, escalamento por *Direct Support*, datas no ficheiro | **parcial** | **2 de 3.** §8 do ficheiro: o **lembrete ao dia 10** e o **escalamento por *Direct Support* após a aprovação de Tech Provider** estão registados como regra, com dono por marco — e o escalamento tem como gatilho a aprovação, não uma data, porque **antes dela não há *Direct Support*** (E1 §3). O que falta são as **datas absolutas**: contam-se do dia 0, que é o dia do envio e **não existe**. Devolvido ao **Responsável de Produto** — §7, item 5 |

**Definition of Done — 2 de 5:**

| # | Caixa | Estado | Evidência ou credor |
|---|---|---|---|
| 1 | Todos os CA satisfeitos | **não satisfeito** | 4 de 7; as três abertas são os critérios 2, 3 e 7 acima |
| 2 | H4 e decisões (D2, D5, D10) com data e dono | **parcial** | **H4**, **D2** e **D10** registadas (§4.4, §5.1, §5.2), com dono **Responsável de Produto** e data **2026-11-05**. **D5 não é deste ticket**: é registada pelo **KAM-102**, critério 5, «até à semana 4» — este ficheiro regista no §5.3 só as perguntas que a alimentam (Q8, Q9, Q11, Q15). Credor: **KAM-102** |
| 3 | Sem dados pessoais nem segredos; envio aprovado | **parcial** | A **primeira metade está verificada**: nenhum nome de pessoa, nenhum número de telefone e nenhum segredo no ficheiro — o `+244` aparece só como indicativo de país, e a ficha do §2.2 manda registar o remetente **pelo papel ou pela equipa, nunca pelo nome**. Gate 9 (`scan_secrets tree`) verde. A **aprovação do envio** é acto humano: devolvida ao **Responsável de Produto** — §7, item 3 |
| 4 | Itens NÃO VERIFICADOS de E1 com estado final ou mantidos com razão | **satisfeito** | §3: os quatro **mantêm-se** e cada um com a razão escrita. Risco 1 (*AI Provider*) mantém-se **NÃO VERIFICADO e existencial** — não há critérios objectivos publicados para «primary» *vs* «incidental or ancillary» nem processo de pré-aprovação (§3.2). *Access Verification* mantém-se **NÃO VERIFICADO** — a página nomeia o passo e não o detalha (§3.4). Elegibilidade de Angola na coexistência mantém-se **NÃO VERIFICADO**, e o **historial de países baixa a INDÍCIO** nas duas direcções, por as duas leituras não concordarem (§3.3). Cláusula 4.7 **refinada, não fechada**: o enquadramento e a excepção ficam registados e a confirmação do texto operativo continua a ser a Q7. «Mantido com razão» é entrega; promover um destes a facto seria o defeito. **A revisão adversarial objectou a esta caixa** e a objecção fica escrita em vez de calada (§11, item 17): um estado que vem com gatilho de reavaliação é, por construção, não final, e o critério 4 é dado por «não satisfeito» sobre itens que se sobrepõem a estes. A caixa fica **marcada** pelo precedente explícito do **KAM-101**, que marcou a mesma redacção de DoD com o mesmo argumento, e pela distinção entre os dois pedidos: o critério 4 pede **as respostas**, esta caixa pede que **nenhum item fique sem estado declarado**. «Final» aqui quer dizer isso, e não que o item seja imutável — nenhum estado nesta casa o é. Devolvido ao Responsável de Produto |
| 5 | Impacto de cada resposta nos tickets listado | **satisfeito** | §6 do ficheiro: uma linha por ticket para **KAM-016**, **KAM-033**, **KAM-088** e **Clusters** (os quatro que esta caixa nomeia), mais KAM-102, KAM-095, KAM-049, KAM-058 e KAM-100, cada uma a dizer que perguntas a afectam e o que muda com a resposta. Nenhuma linha está accionada, porque nenhuma resposta existe |

**O que não entra neste ticket.** O dossiê de Tech Provider, as submissões e as cotações de BSP são o **KAM-102**. Corrigir a afirmação sobre o âmbito da cláusula 4.7 — o desvio 1 — é **ticket a abrir pela linha L1**, e o credor é o **fundador**, que é a autoridade do canon: «KAM-NNN a abrir» não é credor, porque um ticket que ainda não existe não sobrevive à fusão deste PR. O critério 4 manda **registar** o desvio, e corrigir canon de nível 2 e 10 a coberto de um ticket de dossiê era alargar escopo em silêncio. O alcance está levantado para que esse ticket não o repita: além do E1 §4 e do [`../docs/tecnica/10_Onboarding_Governanca.md`](../docs/tecnica/10_Onboarding_Governanca.md) §11.3 — os dois que afirmam a cláusula **e já pedem na própria frase que se verifique o texto exacto** —, há **cinco** outros sítios que a afirmam **sem** a condicionante, e um deles é um **ADR-L em vigor** que regista uma decisão do fundador e por isso não se corrige por iniciativa de sessão. Os **seis** que já se declaram NÃO VERIFICADO ou com ressalva não contradizem este ficheiro: dizem o que ele vem responder, e a releitura dá-lhes razão. Tudo no §3.1.1 do ficheiro.

### Handoff para Claude Code
```text
És o executor do ticket KAM-101 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-101) e docs/tecnica/evidencia/E1_Meta_WhatsApp.md (secção «Perguntas que só a Meta/BSP pode responder», §3, §4).
Objectivo: preparar o dossiê de perguntas para a Meta e a folha de seguimento; NÃO envias nada nem inventas respostas.
- Cria docs/tecnica/evidencia/validacao/Meta_Perguntas.md com as 15 perguntas (EN e PT), prioridade, decisão afectada e estado.
- Redige a mensagem de cada pergunta com contexto mínimo e sem dados pessoais; prepara o modelo de registo de respostas com classificação CONFIRMADO/INDÍCIO.
- Relê as fontes primárias em inglês para os 4 trechos críticos e regista desvios face a E1 (URL, data, resumo curto).
- Implementa a regra de decisão de H4 como checklist; não decidas por humanos.
Não expandas escopo: o dossiê de Tech Provider é KAM-102. Testes: validar_evidencia.py e revisão cruzada. PR com o template da §7.
```

---

## KAM-102 — Business Verification, App Review e Tech Provider (D5)

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-016, KAM-095, KAM-108 |
| Responsável sugerido | Responsável de Produto (com o fundador como representante da entidade legal) |
| Documentos de referência | `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§3, §8), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.1–4.3), `../docs/tecnica/10_Onboarding_Governanca.md` (§6), `14` (§3A Regra 3, §6), `../docs/tecnica/00_Arquitectura_Solucao.md` (D5, D9), ADR-001 |

### Contexto
Sem Tech Provider (ou Solution Partner) não há Embedded Signup nem coexistência. O caminho é: entidade legal e portfólio Meta Business → **Business Verification** da KAMBÁ → app Meta tipo Business com o caso de uso WhatsApp → **App Review** com *Advanced access* a `whatsapp_business_messaging` e `whatsapp_business_management` (2 vídeos por permissão, gravação de ecrã, descrição escrita). O prazo do App Review é «cerca de 24 h» segundo a Meta (CONFIRMADO; planear 1 a 2 semanas); o prazo da Business Verification **não está documentado** e a aceitação de documentos angolanos é NÃO VERIFICADA. Até à *Access Verification* o limite é de 10 clientes novos por 7 dias (depois 200). O Embedded Signup v2/v3 deixa de funcionar a 2026-10-15: constrói-se em v4.

### Objectivo
Obter o estatuto de Tech Provider (ou documentar o bloqueio e o plano B) e decidir D5 (Tech Provider directo, *Multi-Partner Solution* ou BSP) até à semana 4, com prazos reais medidos.

### Critérios de Aceitação
- [ ] `../docs/tecnica/evidencia/validacao/Tech_Provider_Dossie.md` com uma linha por passo (entidade e portfólio, Business Verification, app e caso de uso, App Review por permissão, *Access Verification*, método de pagamento): data de submissão, data de resposta, resultado, motivo de rejeição, dias úteis decorridos (substitui o prazo NÃO VERIFICADO da Business Verification por um valor medido).
- [ ] A Business Verification é submetida até ao dia 5, com a entidade escolhida em articulação com D9; se a Meta não aceitar os documentos angolanos, a alternativa (outra entidade, ou via BSP/MPS) é registada em ≤ 3 dias úteis após a rejeição.
- [ ] O App Review é submetido em ≤ 5 dias úteis após a Business Verification aprovada, com protótipo funcional (envio de mensagem e criação de template), 2 vídeos por permissão e descrição por permissão aprovados pelo Responsável de Produto; no máximo 3 submissões antes de escalar.
- [ ] Estatuto Tech Provider confirmado no painel da app (captura datada) e acesso a *Direct Support* confirmado (S/N); o `config_id` do ES v4 de coexistência criado e entregue ao KAM-016 por cofre, nunca em repositório.
- [ ] **D5 registada até à semana 4** (dono e data): tabela de opções (Tech Provider directo, MPS com Solution Partner, BSP) com ≥ 2 cotações formais de BSP (uma com presença em África) com taxa mensal, *markup*, suporte a coexistência e BSUID, tarifa final para +244, e modelo de facturação (cartão USD/EUR da PME vs *credit line*); a decisão cita o input de D9 sobre quem paga em USD.
- [ ] Barreira do cartão: nas entrevistas do KAM-106 regista-se, por PME, se tem cartão internacional (n.º de PMEs com cartão sobre o total entrevistado); o resultado alimenta D5 e o KAM-095.
- [ ] **Regra de falha (semana 6, Carta §4.2):** sem Tech Provider à semana 6 pára a camada de canal (KAM-016) e aplica-se o pivô de `14` §6 (BSP parceiro, outro número ou produto sem automação no WhatsApp da PME), com decisão assinada.
- [ ] Limites de onboarding aplicáveis (10 por 7 dias, depois 200 por 7 dias) e o que a *Access Verification* exige, conforme resposta da Meta (Q9 de KAM-101), ficam registados para o KAM-095.
- [ ] O pedido de App Review lista, no mesmo ciclo, as permissões necessárias à publicação futura em redes (`pages_manage_posts`, `instagram_business_content_publish`), mesmo que a publicação automática fique Diferida (D13); a resposta da Meta fica registada em `../docs/tecnica/evidencia/` (E5 §3).

### Detalhes Técnicos
- **Componentes:** GWY e ES (consumidores: KAM-016, KAM-093). O Tech Provider não tem *credit line*: o cliente adiciona o seu método de pagamento e a Meta factura-o (CONFIRMADO); Solution Partner tem *credit line* mas o processo é «demorado» (sem prazo).
- Contas criadas por *developer app* não podem ser onboarded pelo ES; o modelo *On-Behalf-Of* está descontinuado — o cliente é sempre dono dos activos.
- O Claude Code prepara a lista de documentos, o guião e o *storyboard* dos vídeos, a aplicação mínima de demonstração (enviar mensagem, criar template) e o modelo de cotação a BSPs; as submissões, a gravação dos vídeos e as chamadas são humanas.
- Preços de BSP citados em E1 (360dialog, Twilio) são INDÍCIO: só contam as cotações recebidas por escrito.

### Testes Requeridos
- Ensaio da aplicação de demonstração em conta de teste antes de gravar os vídeos; revisão do *storyboard* contra a lista de requisitos de `E1` §3.
- Validação do dossiê com `validar_evidencia.py`; revisão cruzada de que as datas e os dias úteis batem.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] D5 e H4 (parte aprovação) registadas com dono e data.
- [ ] Segredos (App Secret, `config_id`, tokens) só no cofre; documentos da empresa em arquivo controlado, fora do repositório.
- [ ] KAM-016 desbloqueado ou replaneado por escrito; KAM-095 informado do limite de onboarding.
- [ ] Itens NÃO VERIFICADOS (prazo da Business Verification, documentos angolanos, *Access Verification*) com estado final.

### Verificação dos Critérios de Aceitação

Entregue: [`../docs/tecnica/evidencia/validacao/Tech_Provider_Dossie.md`](../docs/tecnica/evidencia/validacao/Tech_Provider_Dossie.md). Caixas: **0 de 9 critérios** e **0 de 5 de DoD** — e o zero é o resultado certo, não um ticket mal feito. **Oito dos nove critérios pedem um acto de submissão, de gravação, de confirmação no painel ou de recepção de resposta de terceiro**, e os «Detalhes Técnicos» deste bloco já o diziam: «as submissões, a gravação dos vídeos e as chamadas são humanas»; o nono, o critério 1, pede uma medição que exige submissão. O que o executor podia produzir está produzido e é verificável; o que falta está no §12 do ficheiro, **dezoito itens ainda abertos, mais um fechado e um novo, cada um com credor que sobrevive à fusão deste PR**, e o **fundador** é credor — sozinho ou ao lado de outro papel — em **onze** deles, por ser a autoridade para submeter em nome da entidade legal.

**A revisão adversarial (27 achados, [`ANALISE-53`](../docs/analises/ANALISE-53-KAM-102-tech-provider.md)) mudou esta tabela em três sítios, e vale dizer quais**, porque uma tabela de verificação corrigida em silêncio não é verificação: (a) **a única caixa marcada foi desmarcada** — a caixa 3 de DoD tem duas metades e a evidência só provava a primeira; (b) **a leitura do ADR-001 no critério 5 era endurecida** — exercer o plano B do canon não é substituir um ADR; (c) **o critério 3 passou de «não há *storyboard* para as permissões de redes» a tê-lo**, do fluxo de entrega manual, que estava ao alcance.

| # | Critério | Estado | Evidência nomeada |
|---|---|---|---|
| 1 | O ficheiro com uma linha por passo e as cinco colunas | **parcial** | **A primeira metade está entregue e é verificável:** §2 do ficheiro tem os **seis** passos que o critério nomeia, pela ordem que a Meta impõe, com as cinco colunas pedidas (data de submissão, data de resposta, resultado, motivo de rejeição, dias úteis decorridos), mais o dono e uma coluna **«Estado»** própria — porque `por submeter` **não é um resultado**, e é assim que o precedente do [`Seguimento_APD.md`](../docs/tecnica/evidencia/validacao/Seguimento_APD.md) §1 separa as duas colunas. O passo 4 vem **desdobrado em quatro linhas, uma por permissão** (o critério diz «App Review **por permissão**», e a lista do §10.1 mede cada uma em separado). Contagens a **0 submetidos, 0 aprovados, 0 prazos medidos**. O §2.1 escreve as duas restrições de ordem que E1 §3 confirma — Business Verification **antes** do App Review, e o 200 só com os **três** passos — e diz que o passo 2 **não é o único** com prazo NÃO VERIFICADO: o passo 5 também o tem, e com o agravante de não se saber nem o processo. O §2.2 fixa a regra de contagem de dias úteis **antes** de haver o que contar, com os feriados a **não** descontar e o fuso em **`Africa/Luanda`**, que é o que o dicionário canónico §2 manda para apresentação — e é material, porque Luanda é UTC+1 e uma submissão depois das 23:00 locais cairia no dia UTC seguinte. **A segunda metade não está, e não podia estar:** o critério diz que o ficheiro «substitui o prazo NÃO VERIFICADO da Business Verification por um valor medido», e o sujeito de «substitui» é o documento. Medir exige submeter. O §2.3 regista-o como **NÃO MEDIDO** — que é diferente de NÃO VERIFICADO e diferente de medido — e inventaria os três prazos que têm fonte, cada um com o seu estado: «cerca de 24 horas» como **número da Meta**; o «*turnaround* muito mais rápido» da verificação conduzida por **Select ou Premier** Solution Partner como **NÃO VERIFICADO**, porque a página que o carrega está declarada «listada, não lida» em E1 §3; e o único **INDÍCIO** que o conjunto tem para este prazo, «dias a semanas» de `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` §3, com o âmbito e a falta de fonte oficial escritos. **Marcar esta caixa era cumprir em espírito**: a tabela existe, o valor medido não. Credor: **fundador** (§12, item 1) |
| 2 | Business Verification submetida até ao dia 5; alternativa em ≤ 3 dias úteis se os documentos forem rejeitados | **não satisfeito** | **O que o executor podia preparar está no §3:** a lista de documentos por passo — alvará, NIF, certidão do registo comercial, comprovativo de endereço —, cada um com o estado da aceitação a **NÃO VERIFICADO** e a **Q8** de [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) §1 como via, porque E1 §3 diz que a aceitação de documentos angolanos é NÃO VERIFICADA e inventá-la aqui era o defeito. O §3.1 separa a Business Verification **da KAMBÁ** (passo 2, pré-requisito do App Review) da **de cada PME cliente** (que sobe o limite de mensagens, os números e a OBA) — confusão fácil e caríssima. O caminho da alternativa em ≤ 3 dias úteis está no §13, com dono. **Submeter é do fundador**, e nenhuma data está escrita: escrever uma data de submissão que não aconteceu era uma afirmação falsa sobre o mundo. Credor: **fundador** (§12, item 1) |
| 3 | App Review submetido em ≤ 5 dias úteis, com protótipo, 2 vídeos por permissão e descrição por permissão aprovados; máximo 3 submissões | **não satisfeito, com o preparável todo feito e uma leitura devolvida** | §4 e §5 do ficheiro. **Quatro descrições escritas** redigidas (§4.2), uma por permissão, como E1 §3 confirma ser obrigatório, **em EN e PT** — o EN é o que se submete, pelo precedente do critério 1 do KAM-101 e porque uma tradução feita no momento da submissão é texto que ninguém reviu. As duas de redes dizem por escrito que no Piloto a entrega é para **publicação manual**, porque descrever à Meta um produto que o ADR-020 proíbe construir era descrever o que não existe. ***Storyboard* de seis gravações** (§4.3), com o que tem de aparecer no ecrã por ordem e a duração-alvo marcada como **escolha nossa, sem fonte**, mais as regras de E1 §3 (ecrã gravado, **nunca** captura) e a regra nossa da caixa 3 de DoD (nenhum número, nome, token ou App Secret no enquadramento). **A divergência de leitura está medida e devolvida, agora com as três formulações à vista:** E1 §3, a fonte primária, diz «uma gravação **por permissão**»; este critério diz «**2 vídeos por permissão**»; e o `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §4.2 repete a segunda redacção **e** acrescenta o parêntesis «(mensagem, template)», que é a primeira leitura. **Nenhuma das três diz quantos ficheiros se submetem.** Preparei quatro para as duas permissões do WhatsApp, porque a leitura estrita satisfaz as três; qual vale é de quem escreveu o critério (§12, item 3). **E as duas permissões de redes têm *storyboard***, do único fluxo que existe — gerar a peça, o dono aprovar, entregar para publicação manual (o `ManualDelivery` de `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` §3) —, porque redigir descrições para essas permissões e recusar-lhes gravação era uma assimetria sem razão. Continua **NÃO VERIFICADO** se a Meta concede *Advanced access* com base nessa demonstração, e **gravar o acto de publicar não é opção**: o ADR-020 regra 3 proíbe-o no Piloto. **Guião de ensaio em sete passos** no §5, que dispensa escrever código porque E1 §3 confirma que a cURL do API Setup e o WhatsApp Manager servem no lugar da app — com os três avisos que poupam uma repetição, entre eles que a conta de teste **não** serve como primeira PME integrada (contas de *developer app* não são integráveis pelo ES). Contador das três submissões a **0 de 3** (§4.4), com a armadilha circular escrita: a via de escalada da terceira rejeição é o *Direct Support*, que é atributo do estatuto que o App Review concede. **Submeter, gravar e aprovar não são do executor.** Credores: **fundador** e **Responsável de Produto** (§12, itens 2 e 3) |
| 4 | Estatuto confirmado no painel com captura datada, *Direct Support* (S/N), `config_id` criado e entregue por cofre | **não satisfeito** | §9 do ficheiro: a tabela nasce vazia e **cada linha diz onde vive o que não entra no repositório** — a captura em arquivo controlado fora do repositório, o `config_id` e os tokens no cofre, com entrega ao KAM-016 **por referência do cofre**. O que o ficheiro pode passar a conter é a **data** e um **S/N**, nunca o valor. E fica escrito porque o §4.4 depende dele: o *Direct Support* é a via de escalada do App Review e **não existe antes da aprovação** (E1 §3). Declarar um estatuto que ninguém confirmou era o defeito nomeado no pedido. Credor: **fundador** (§12, item 11) |
| 5 | D5 registada até à semana 4, com tabela de opções e ≥ 2 cotações formais | **não satisfeito** | §6 do ficheiro, e a parte entregue é substantiva. **A matriz das três opções** (§6.1) com os factos de E1 §3 e §8 e o seu estado. **E a leitura do canon ficou corrigida pela revisão adversarial**, porque a primeira versão endurecia-o: o **ADR-001** nomeia «Tech Provider» e o que **bane** é o *gateway* não-oficial; o `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3 mantém **D5 nas decisões abertas**, com o assunto «Tech Provider directo *vs* BSP» e prazo «semana 1–4»; a Carta §4.2 dá-a **ABERTA** com dono Produto; o `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §4.1 dá o BSP como «alternativa só se Tech Provider falhar» e a cotação a 2 BSPs **como plano B**; e o `14` §6 inscreve «BSP parceiro» como **pivô escrito**. Logo **exercer o plano B não é substituir um ADR: é executar um caminho que o canon já escreveu** — e se a redacção do ADR-001 tiver de mudar, isso é pergunta para o Arquitecto de Plataforma e para o fundador (§12, item 17), não para um documento de evidência. **A tabela das cotações nasce vazia** (§6.2): **0 pedidas, 0 recebidas, mínimo 2**, com as doze colunas que a decisão precisa e com «suporte a BSUID» como coluna **eliminatória** e não nota de rodapé, porque E1 §3 dá os BSUID como obrigatórios para todos os parceiros e o telefone pode deixar de vir no webhook — um BSP que não os suporte não é mais barato, é inviável. **Os preços de BSP de E1 §8 não entram em célula nenhuma**, porque são INDÍCIO e os «Detalhes Técnicos» dizem que só contam cotações por escrito. **O «modelo de cotação a BSPs» que os «Detalhes Técnicos» mandam preparar está entregue** (§6.3), e em duas partes: o corpo é a **Q15** de [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) §1, em `por enviar`, que **não se reescreve** — reescrevê-la criava duas versões da mesma pergunta e a que fosse enviada deixava a outra a mentir —, mais as **três** perguntas que a Q15 **não** faz e de que esta matriz depende: **presença em África** (que o critério 5 exige e sem a qual a condição não se verifica), **moeda de facturação** e **se factura em Kwanzas** (que é o NÃO VERIFICADO da linha MPS e a metade do critério 5 que pede o modelo de facturação), redigidas em EN. Os destinatários são os únicos que o conjunto nomeia — **360dialog** e **Twilio**, de E1 §8 — e a linha do BSP **com presença em África fica «a identificar»**, porque **nenhuma fonte deste conjunto nomeia um** e escrever um nome era dar a um palpite a aparência de uma lista de contactos (§12, item 18). **D5 fica ABERTA e não «provisória»** (§6.5): o critério 5 do KAM-105 autorizava por escrito esse caminho para D9, e o critério 5 **deste** ticket não autoriza nada parecido. Falta-lhe o que está listado: zero cotações, e o **input de D9** sobre quem paga em USD, que o [`Seguimento_APD.md`](../docs/tecnica/evidencia/validacao/Seguimento_APD.md) §3 deixa **vazio** e marca como decisão do fundador. Credores: **fundador** (cotações), **Responsável de Produto** (registo e fecho — é o dono que a Carta §4.2 nomeia) e **Arquitecto de Plataforma** (§12, itens 6, 7, 8, 17 e 18) |
| 6 | Barreira do cartão: n.º de PMEs com cartão sobre o total entrevistado | **não satisfeito** | §7 do ficheiro: o lugar está preparado com a coluna certa e o destino escrito (alimenta **D5** e o **KAM-095**), e **nenhum número está inventado**. A contagem diz **0 de 0**, com a linha que impede a leitura errada: **isto não é zero por cento, é não medido**. O instrumento é o guião de entrevistas do **KAM-106**, que o próprio bloco do KAM-106 já nomeia como entrada deste ticket. Credor: **KAM-106** (§12, item 9) |
| 7 | Regra de falha da semana 6, com decisão assinada | **parcial** | **A regra está escrita como lista de verificação** (§10), que é o que se podia entregar, e com três coisas que não estavam escritas em sítio nenhum. **(a)** «Sem Tech Provider» fica **definido** pelas quatro primeiras linhas da medição do §10.1, e as quatro têm de ser `sim`: uma aprovação só da permissão de mensagens **não** é Tech Provider para este efeito, porque sem `whatsapp_business_management` não há criação de *templates* e sem *templates* não há o fluxo que o gate da Fase 0 exige. **(b)** Os cinco passos da consequência (§10.2), com a paragem do **KAM-016** como a Carta §4.2 a nomeia e a assinatura no fundador. **(c)** Os três pivôs do `14` §6 com o que cada um custa (§10.3) — e o do **BSP parceiro** com o seu pré-requisito a **zero**: um pivô para uma opção sem cotação formal é um pivô para o desconhecido. O §10.4 cita, sem reescrever, a ressalva que o [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) §4.1 fixou: `confirmada` pela via da aprovação **não fecha D2** nem levanta o diferimento do **ADR-011**. **A medição e a assinatura são da semana 6 e do fundador.** Credor: **fundador** (§12, item 12) |
| 8 | Limites de *onboarding* e o que a *Access Verification* exige, conforme a Q9, registados para o KAM-095 | **parcial** | §8 do ficheiro. **Os limites estão registados e são CONFIRMADOS** (§8.1): **10** por janela móvel de 7 dias por defeito, **200** com Business Verification **e** App Review **e** *Access Verification*, candidatura a Meta Business Partner acima disso, e contas de *developer app* não integráveis pelo ES. **O que a *Access Verification* exige continua NÃO VERIFICADO** (§8.2) — requisitos, processo e prazo —, e o critério diz «conforme resposta da Meta (Q9 de KAM-101)»: sem resposta, o que se regista é a pergunta, o seu estado (`por enviar`, lote 1) e quem a move. Inventar o conteúdo da Q9 era exactamente o que o critério proíbe ao nomeá-la. **O aperto que o KAM-101 trouxe fica citado como INDÍCIO, uma leitura, e não sobe a facto** (§8.3): a releitura de [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) §3.4 diz que **não se integra cliente nenhum** enquanto a app não tiver *advanced access* por permissão — condição **anterior** ao limite de 10 — e, se se confirmar, o limite relevante antes do App Review não é 10, é **0**. **Para o KAM-095 ficam quatro avisos** (§8.4), e o que importa é o segundo: **nenhum dos dois valores se fixa em código como constante final**, porque uma fila dimensionada para 200 antes de alguém saber como se obtém o passo 5 promete capacidade que ninguém confirmou. Credor da resposta: **fundador** (envio) e **Responsável de Produto** (registo) — §12, item 10 |
| 9 | O pedido de App Review lista as permissões de redes no mesmo ciclo; a resposta da Meta fica registada em E5 §3 | **não satisfeito, com a lista feita e a questão aberta medida** | **A lista está feita** (§4.1): as **quatro** permissões, com `whatsapp_business_messaging` e `whatsapp_business_management` em *Advanced access* (CONFIRMADO, E1 §3) e as duas que este critério manda pedir — que **não constam de E1** e vêm deste critério e do «gancho obrigatório» de `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` §3 («pedido de permissões (…) na mesma submissão do Tech Provider»). A revisão adversarial apanhou aqui uma atribuição errada, corrigida: a primeira versão dizia que E1 §3 nomeava as permissões de redes, e **nenhuma das quatro ocorre em E1**. As **acompanhantes** que o E5 §3 nomeia e este critério não — `pages_read_engagement`, `instagram_business_basic`, `publish_video` — ficam **registadas e não acrescentadas**, porque acrescentar permissões a um pedido é alterar o pedido (§12, item 5). **As duas permissões de redes têm *storyboard***, do único fluxo que existe: gerar a peça, o dono aprovar, e a peça ser **entregue para publicação manual** — o `ManualDelivery` do mesmo E5 §3. A primeira versão deixava-as sem gravação e chamava à ausência «o achado»; era meio raciocínio, e a revisão mostrou-o. **O que continua NÃO VERIFICADO é se a Meta concede *Advanced access* com base numa demonstração de entrega manual**, e **gravar o acto de publicar não é opção**: o ADR-020 regra 3 proíbe a publicação automática no Piloto e a D13 difere-a. Se a Meta exigir a demonstração do acto de publicar, a escolha é a do §12, item 4 — pedir as quatro agora e aceitar o risco de rejeição parcial, ou pedir primeiro as duas do WhatsApp —, e não é cosmética, porque uma rejeição parcial consome uma das três submissões. Se as duas podem ir na mesma app e na mesma Business Verification é a **pergunta 1 da lista «Para a Meta (por escrito)»** de [`../docs/tecnica/evidencia/E5_Modulos_Entrada.md`](../docs/tecnica/evidencia/E5_Modulos_Entrada.md) — que vive na secção final «Perguntas para o advogado e para a Meta» e **não** no §3, outra citação que a revisão corrigiu —, também **NÃO VERIFICADA**. **O pedido não existe** (não há submissão) e **não há resposta da Meta para registar em E5**: editar um documento de evidência para escrever que não há resposta era ruído, e o lugar fica nomeado (§12, item 13) |

**Definition of Done — 0 de 5:**

| # | Caixa | Estado | Evidência ou credor |
|---|---|---|---|
| 1 | Todos os CA satisfeitos e demonstráveis | **não satisfeito** | **0 de 9**, com a razão de cada um acima. Oito pedem um acto humano; o 1 pede uma medição que exige submissão |
| 2 | D5 e H4 (parte aprovação) registadas com dono e data | **não satisfeito** | **D5 está registada como ABERTA** com dono (Responsável de Produto, Carta §4.2), prazo e o que falta para fechar (§6.5) — e registar uma decisão como aberta não é «registar a decisão». **H4 parte aprovação não existe**: não há aprovação. A regra de H4 é do KAM-101 §4 e este ficheiro cita-a sem a reabrir (§10.4). Credores: **fundador** (assinatura e cotações), **Responsável de Produto** (registo) |
| 3 | Segredos só no cofre; documentos da empresa em arquivo controlado, fora do repositório | **parcial** | **Esta caixa estava marcada e a revisão adversarial desmarcou-a, com razão.** A caixa tem duas metades. **A primeira está verificada, não assumida:** o ficheiro não contém App Secret, `config_id`, token, captura de painel nem documento da empresa, e não contém nome de pessoa; os **dois** `+244` que nele aparecem são o **indicativo de país** sem dígitos de assinante, pelo que não casam o padrão de forma `+?244 ?9` mais oito dígitos — que vive em `tools/meta-sim/src/numeros.ts` e é instrumento do ***gate* 7**, não do 9. Do *gate* 9 correu-se a passagem da **árvore** (`scan_secrets tree`, limpo, **1971** ficheiros seguidos pelo git depois de integrar a `main`), e **só essa**: desde o KAM-131 o gate 9 corre **duas** passagens — árvore **e** história do PR (`docs/ci.md` §2) —, e a da história corre no CI com a base e a cabeça do PR. Declarar «*gate* 9 verde» a partir de metade dele era o mesmo erro que esta tabela reprova noutro sítio. **A segunda metade não está:** «documentos da empresa em arquivo controlado» afirma que o arquivo **existe**, e a evidência disponível só prova a **ausência no repositório**. Nada foi submetido, o `config_id` está «não criado» (§9) e a coluna «Onde vive» do §3 é declaradamente uma **proposta**. Pela mesma régua que desmarcou o critério 1 — a tabela existe, o valor medido não — esta caixa fica vazia. Credor: **fundador** |
| 4 | KAM-016 desbloqueado ou replaneado por escrito; KAM-095 informado do limite | **parcial** | **A segunda metade está satisfeita**: o §8.4 informa o KAM-095 com quatro itens, com estado por item, incluindo o aviso de não fixar o 200 como constante final e o facto de o contador **atravessar *tenants*** (CONFIRMADO no critério 8 do KAM-016, EPIC-02). **A primeira não**: o KAM-016 não está desbloqueado — não há estatuto — e «replaneado por escrito» é o que o §10.2 **condiciona** à medição da semana 6, não o que faz hoje. Credor: **fundador** (§12, item 12) |
| 5 | Itens NÃO VERIFICADOS (prazo da Business Verification, documentos angolanos, *Access Verification*) com estado final | **não satisfeito** | Os três **mantêm-se**, cada um com a razão escrita e a via nomeada: o prazo da Business Verification passa a **NÃO MEDIDO** e a via é a submissão (§2.3); a aceitação de documentos angolanos mantém-se **NÃO VERIFICADA** e a via é a **Q8** (§3); a *Access Verification* mantém-se **NÃO VERIFICADA** e a via é a **Q9** (§8.2). **Esta caixa pede «estado final» e não «mantidos com razão»** — e é a diferença que a separa da caixa 4 do KAM-101, que admitia as duas por escrito. Manter com razão é entrega; chamar-lhe estado final era promover três NÃO VERIFICADOS a facto, que é o defeito mais comum desta casa. Credores: **fundador** (envio da Q8 e da Q9, e submissão) |

**O que não entra neste ticket.** O ES v4 em código é o **KAM-016**; a fila de espera e os limites iniciais são o **KAM-095**; a contagem de PMEs com cartão é o **KAM-106**; o `validar_evidencia.py` dos «Testes Requeridos» era artefacto do **KAM-100** e não existia na árvore quando esta entrega foi escrita — **aterrou com a fusão do KAM-100** e, corrido sobre o dossiê, deu **`conforme`** (código 0), depois de obrigar a declarar `Estado`, `Fonte` e `Dono` no cabeçalho, que faltavam. **E os outros onze ficheiros de `validacao/` não passam** — 30 achados em 12 ficheiros, 11 alheios a este ticket —, o que fica medido para a linha **L1** e não se corrige aqui; o validador não está no CI, pelo que nada está vermelho por causa disto. E **a cláusula 4.7 não se corrige aqui**: o §11 do ficheiro mostra porque é que ela toca este ticket — as opções MPS e BSP implicam **contratar um Solution Provider**, que é a condição que o achado do KAM-101 nomeia —, cita-a como **INDÍCIO de uma leitura**, e diz que **nada se relaxa**, porque a posição em vigor é mais conservadora do que a fonte exige. Corrigir os documentos que a afirmam sem a condicionante é da linha **L1** com o **fundador** como credor, como o [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) §3.1.1 já fixou — e **a prosa dessa fonte diz cinco enquanto a tabela do seu §3.1.1 enumera seis**, discrepância que fica **escrita e não corrigida**, porque o alcance desse ticket é o da tabela, que é o maior dos dois, e reconciliar a prosa é dele. Um `ADR-L` não se emenda por iniciativa de sessão. **E não se emenda o ADR-001:** a primeira versão desta entrega lia-o como se escolher MPS ou BSP fosse substituí-lo, e quatro fontes dizem o contrário — D5 está aberta no `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3 e na Carta §4.2, e o BSP é plano B no `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §4.1 e pivô no `14` §6. Se a redacção do ADR-001 precisa de emenda, decide-o o **Arquitecto de Plataforma** com o **fundador** (§12, item 17).

### Handoff para Claude Code
```text
És o executor do ticket KAM-102 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-102), docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§3, §8),
docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4) e docs/tecnica/10_Onboarding_Governanca.md (§6).
Objectivo: preparar o dossiê de Business Verification, App Review e Tech Provider e a análise de D5; as submissões e decisões são humanas.
- Cria docs/tecnica/evidencia/validacao/Tech_Provider_Dossie.md com a tabela de passos e a lista de documentos por passo.
- Escreve o storyboard dos 2 vídeos por permissão e a app mínima de demonstração (enviar mensagem, criar template) para conta de teste.
- Prepara o modelo de cotação a BSPs e a matriz de decisão de D5; nada de preços de BSP sem cotação por escrito.
- Não guardes segredos nem documentos da empresa no repositório.
Não expandas escopo: o ES v4 em código é KAM-016. Testes: ensaio da app de demonstração e validar_evidencia.py. PR com o template da §7.
```

---

## KAM-103 — Contratos de pagamento: bancos e facilitadores (D4)

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-056, KAM-057, KAM-110 |
| Responsável sugerido | Responsável de Produto (com apoio de advogado para a minuta) |
| Documentos de referência | `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§1, §1.7, §8, §9 perguntas 1–18), `14` (§2 H5, §6), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`, `../docs/tecnica/00_Arquitectura_Solucao.md` (D4, D8), ADR-004, ADR-013 |

### Contexto
O caminho crítico dos pagamentos é o **onboarding bancário de cada PME**: banco de apoio, contrato EMIS (POSID/supervisor card, Entidade, IEC) e contrato com o facilitador; o prazo **não está publicado** (NÃO VERIFICADO; semanas, específico por banco). Dos facilitadores: AppyPay tem preço público (0,40% por cobrança, mínimo 50 Kz, máximo 1.500 Kz, CONFIRMADO; IVA a acrescer e comissão bancária à parte); ProxyPay tem API e sandbox documentados mas **preços NÃO VERIFICADOS** e o callback do OPG pode não ser assinado. A AppyPay declara-se certificada pela EMIS (validação independente NÃO VERIFICADA) e a sua documentação completa está atrás de uma SPA. H5 (`14` §2): prazo e custo por PME conhecidos e ≤ 6 semanas. A plataforma nunca detém fundos (ADR-004): payouts e escrow ficam fora.

### Objectivo
Conhecer, por escrito, prazo e custo por PME de pelo menos um caminho banco + facilitador, e registar D4 com a regra de falha do Piloto.

### Critérios de Aceitação
- [ ] `../docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md` com uma ficha por contraparte (≥ 2 bancos, ProxyPay, AppyPay) com as respostas escritas às perguntas de E2 §9 (bancos 1–6, ProxyPay 7–10, AppyPay 11–15; EMIS 16–17 e PayPay 18 opcionais), cada uma com data, remetente e classificação CONFIRMADO ou INDÍCIO.
- [x] Matriz banco × facilitador com: documentos exigidos, custo único e recorrente, comissão por transacção (AppyPay 0,40%, mín. 50, máx. 1.500 Kz como CONFIRMADO; restantes só com proposta por escrito), liquidação (D+0/D+1/D+2 e horas), limite por transacção, prazo em dias úteis e o dono do contrato.
- [ ] **Limiar H5:** existe ≥ 1 caminho com prazo de onboarding por PME ≤ 6 semanas (30 dias úteis) declarado por escrito pela contraparte, ou medido num caso real (a empresa do fundador como primeiro caso); caso contrário H5 é `refutada`.
- [ ] Respostas explícitas a: o callback do OPG é assinado; rotação da chave HMAC da ProxyPay (a chave HMAC é a API key); conta-mestre multi-comerciante ou modelo ISV (ProxyPay Q9, AppyPay Q15); webhook assinado e *retry* da AppyPay (Q12); certificado EMIS (Q13).
- [x] **D4 registada** (dono e data) com critérios ponderados (*proposta*): callbacks assinados ou polling de reconciliação, sandbox, liquidação directa, prazo, custo, modelo multi-comerciante, cobertura (Unitel Money). Sem contrato à semana 6, o Piloto fica em `ManualProvider` (Carta §4.2) e a decisão é escrita.
- [x] Se H5 falhar: manter as camadas 1–2 e vender atendimento e agenda sem cobrança integrada (`14` §6); o impacto em KAM-056, KAM-057 e KAM-059 fica listado.
- [ ] Verificação empírica do sandbox ProxyPay (referência por `PUT`, pagamento simulado, `GET /payments`, números OPG `900000000`, `900002004`, `900003000`) arquivada como INDÍCIO-forte, sem substituir a resposta escrita.
- [ ] A minuta de contrato de cada contraparte é revista pelo advogado (KAM-104) antes de assinar; nenhum contrato prevê que a KAMBÁ receba ou retenha fundos de terceiros.

### Detalhes Técnicos
- **Componentes:** PAY (adaptadores ProxyPay e eventual AppyPay). Contratos por PME: cada PME precisa de banco + EMIS + facilitador; o modelo de conta-mestre (uma só chave) é uma pergunta, não um facto.
- AppyPay: `merchantTransactionId` de 1–15 caracteres alfanuméricos (INDÍCIO, SDK de terceiros); referências validam 72 h por omissão e sem devolução; Express dá 90 s ao cliente. ProxyPay: OPG expira aos 30 min e o `Idempotency-Key` guarda 5 min.
- O Claude Code prepara: dossiês por contraparte com as perguntas de E2, a matriz e a ficha de decisão, o *script* de verificação do sandbox e o receptor de callback de teste (regista cabeçalhos para responder «é assinado?»). As reuniões e a assinatura são humanas.

### Testes Requeridos
- O *script* de sandbox corre em staging contra `api.sandbox.proxypay.co.ao` e produz um relatório; revisão cruzada de que cada célula da matriz tem fonte escrita ou está marcada NÃO VERIFICADO.
- `validar_evidencia.py` sobre as fichas.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] D4 e H5 no registo com dono e data; KAM-056 e KAM-057 desbloqueados ou replaneados.
- [x] Sem chaves de API nem documentos bancários no repositório (cofre e arquivo controlado).
- [x] Itens NÃO VERIFICADOS de E2 (preços ProxyPay, assinatura de callbacks, prazo bancário) com estado final.
- [ ] Nenhum compromisso contratual de posse de fundos (ADR-004) — verificado por revisão jurídica.

### Verificação dos Critérios de Aceitação

Entregue: [`../docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md) e o instrumento de medição `spikes/proxypay-d4/` (descartável; não acrescenta critério a portão nenhum, e não é pasta isenta). Caixas: **3 de 8 critérios** e **2 de 5 de DoD**, as mesmas depois da revisão adversarial — os 18 achados dela mudaram o **conteúdo** de cinco células de evidência e de três ensaios, e nenhuma caixa. As cinco vazias de critério têm todas a mesma causa de raiz — **contactar bancos e facilitadores, pedir chaves e rever uma minuta são actos humanos**, e este ticket prepara o dossiê sem os praticar. Cada uma fica devolvida com credor nomeado no §11 do ficheiro.

| # | Critério | Estado | Evidência nomeada |
|---|---|---|---|
| 1 | Ficha por contraparte (≥ 2 bancos, ProxyPay, AppyPay) com as respostas escritas às perguntas de E2 §9, cada uma com data, remetente e classificação | **parcial** | O **dossiê** está feito e é verificável: §2 do ficheiro, **seis fichas** — Banco de apoio A, Banco de apoio B, ProxyPay/TimeBoxed, AppyPay, e as opcionais EMIS e PayPay —, com as perguntas **1 a 18** endereçadas pela numeração de E2 §9 e, em cada ficha, a **célula da matriz que a resposta alimenta** e a prioridade. O registo de resposta tem os três campos que o critério pede (data, remetente, classificação) mais o estado e o texto, e a regra de classificação **pela origem** fica fixada no §2.1 **antes** de haver respostas — com o **verbal a ficar INDÍCIO mesmo vindo da contraparte**, que é a regra que mais vai doer e é herdada de [`Meta_Perguntas.md`](../docs/tecnica/evidencia/validacao/Meta_Perguntas.md) em vez de inventada. O que falta são **as respostas**: o registo e a folha de seguimento do §2.8 **nascem vazios** — zero enviadas, zero respondidas — e uma caixa marcada sobre zero respostas era verde vazio. A **identidade do Banco A** fica **NÃO VERIFICADO** de propósito: é «o banco onde a empresa do fundador já tem conta», facto que só ele tem, e é o único caminho em que H5 pode fechar por caso real medido. Devolvido ao **fundador** — §11, itens 1 a 4 |
| 2 | Matriz banco × facilitador com documentos, custo único e recorrente, comissão, liquidação, limite, prazo e dono do contrato | **satisfeito** | §3 do ficheiro: **doze grandezas × cinco caminhos** (Banco A × ProxyPay, Banco A × AppyPay, Banco B × ProxyPay, Banco B × AppyPay, EMIS directo), com **todas** as grandezas que o critério enumera e **cada célula com o seu estado**. O §3.1 diz, coluna a coluna, que decisão ela serve e que pergunta a responde, e fixa a regra dura: **sem fonte escrita, a célula fica NÃO VERIFICADO** — não fica «provavelmente», não fica com intervalo estimado. A comissão da AppyPay é a **única célula CONFIRMADA sobre comissão por transacção**, e o §3.3 escreve as **três** coisas que ela não cobre: não inclui a comissão bancária (os termos dizem-no: é «independente da do banco/EMIS»), não inclui o IVA, e **não é o custo da ProxyPay** — transpor 0,40% para a coluna dela era inventar o preço de um fornecedor a partir do de outro. **A revisão adversarial corrigiu duas células e uma afirmação:** «a única CONFIRMADA sobre **custo**» era falso — o `custo único` e o `custo recorrente` da AppyPay também o são, cinco células em tudo —, e o `documentos exigidos` das colunas da ProxyPay estava **CONFIRMADO com a fonte da AppyPay** (E2 §1.3, que são os termos dela), onde E2 §1.2 dá o requisito como **INDÍCIO** e a lista como **NÃO VERIFICADO**: era o mesmo movimento que o §3.3 proíbe para o preço, feito para os documentos. Corrigidas as duas. O §3.3 nomeia ainda o instrumento que fecha o segundo componente de custo **sem** esperar pelo banco: o campo `fee` do evento de pagamento, que o ensaio 4 do *spike* verifica — e que, por achado da revisão, passou a exigir um **decimal ≥ 0** e não só uma chave presente |
| 3 | **Limiar H5:** ≥ 1 caminho com *onboarding* por PME ≤ 6 semanas declarado por escrito ou medido num caso real; caso contrário H5 é `refutada` | **parcial, com uma divergência de leitura devolvida** | A **regra está pré-registada** e é a metade verificável: §4.1 do ficheiro fixa, **antes** de haver dados, as três leituras que decidem o resultado — o que **conta o prazo** (da entrega do dossiê até a PME **poder cobrar**, não até ao «pedido aceite»), o que conta como **«por escrito»** (documento da contraparte; uma resposta verbal **não fecha** H5), e o que conta como **caso real** (um *onboarding* **completado**, com as datas das duas pontas; um em curso não conta). O §4.2 escreve as saídas como listas de verificação e o §4.3 registra H5 com **amostra n = 0** nas duas vias e estado **`inconclusiva`**, dono Responsável de Produto, data 2026-11-06, e gatilho na primeira resposta escrita com prazo. **A divergência, e não foi decidida aqui:** o critério nomeia **duas** saídas e a entrega registra uma **terceira**. Lido à letra, «não existe ≥ 1 caminho, logo H5 é `refutada`» — e `refutada` com **amostra zero** é uma conclusão tirada de ausência de dados, que dispara o replaneamento de três tickets (critério 6) sobre um dado que ninguém mediu. A terceira saída **não é invenção**: `inconclusiva` é estado canónico de hipótese neste mesmo epic — o critério A do **KAM-110** fixa `confirmada`, `refutada` e `inconclusiva` como os três. O §4.2 diz por escrito que `inconclusiva` **não é** `refutada` e que a diferença é material. Devolvido ao **Responsável de Produto**; o limiar em si fica devolvido ao **fundador** pela via do envio — §11, itens 1 a 4 |
| 4 | Respostas explícitas a: *callback* do OPG assinado; rotação da chave HMAC; conta-mestre ou ISV (ProxyPay Q9, AppyPay Q15); *webhook* assinado e *retry* da AppyPay (Q12); certificado EMIS (Q13) | **não satisfeito** | **As cinco perguntas estão endereçadas, marcadas P0 onde o são, e nenhuma tem resposta** — §2.4 (perguntas 8, 9, 10), §2.5 (12, 13, 15). O §9 do ficheiro mantém cada uma como **NÃO VERIFICADO**, com a razão escrita e sem subir de estado. **E a pergunta da conta-mestre rendeu o achado que mais vale nesta entrega**, no §7.2: a frase de E2 §9 **não distingue duas leituras** — (a) uma só chave de API com a Entidade/POSID **de cada PME** e liquidação para a conta dela, que é o desenho A; e (b) a Entidade/POSID **da KAMBÁ** a receber por todas, que é o **desenho B** de E2 §3.3, «provável sub-adquirente (…) exige autorização BNA», INDÍCIO. As duas cabem na mesma frase «conta-mestre com uma só chave de API», pelo que **um «sim» não desambiguado é uma célula NÃO VERIFICADO e não um «sim»** — está escrito na linha `modelo` do §3.2 —, e a resposta tem de confirmar **as duas metades**. O §7.2 levanta o **segundo** sinal na mesma direcção: o **FTBAI «Funds Transfers»** da AppyPay (INDÍCIO, SDK de terceiros), que seria o desenho **C**. Nenhum dos dois é opção da matriz: é achado para o **fundador** — §11, item 12 |
| 5 | **D4 registada** (dono e data) com critérios ponderados (*proposta*); sem contrato à semana 6 o Piloto fica em `ManualProvider` e a decisão é escrita | **satisfeito, com duas coisas devolvidas** | §5 do ficheiro. **D4 registada** no §5.4 com **dono (papel) Responsável de Produto** — `00_KAMBA_Carta.md` §4.2, que é o registo dos donos das decisões D —, data **2026-11-06**, estado **aberta**, e com **quem fecha** nomeado à parte: o **fundador**, porque dono e decisor não são o mesmo papel neste registo (a linha de D1 mostra o padrão). **A primeira versão dizia «fundador» como dono e citava o `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3, que não tem coluna de dono** — achado da revisão adversarial, e era uma das duas vias por que este critério falhava à letra. A segunda era a forma da regra: **os sete critérios do bloco ponderam-se todos**, como o critério manda, somando 100 com mínimo de **60**; o que dois deles têm a mais é serem também **portões de canon** (ADR-013 e ADR-004) que **excluem qualquer que seja a pontuação**, e isso é aditivo e não substitutivo. **A primeira versão retirava os dois da ponderação e pontuava cinco**, o que era uma leitura a substituir o critério. A justificação do mínimo é aritmética: prazo e custo somam **47**, pelo que os outros cinco juntos dão **53** — abaixo de 60, e a regra não deixa adoptar um facilitador de quem não se saiba nem prazo nem preço. O §5.2 aplica-a: **nenhum candidato adopta**, o melhor tem **32 de 100**, e os dois melhores estão **bloqueados por portões diferentes** — a ProxyPay tem o contrato técnico CONFIRMADO e falha o portão **(b)** porque a liquidação directa é só INDÍCIO de um quadro-resumo; a AppyPay tem metade do custo CONFIRMADA e falha o **(a)**. Daí sai o gatilho, e são **duas** respostas por candidato e não uma — a primeira versão dizia que uma só resposta sobre preço destravava a ProxyPay, **e isso era a fronteira do ADR-004 a ficar aberta**. O §5.3 distingue o que `ManualProvider` não é: manual é a **confirmação**, não a **liquidação**. **Registar não é fechar**: as linhas de assinatura ficam vazias. Devolvido ao Responsável de Produto — §11, itens 9 e 10 |
| 6 | Se H5 falhar: manter as camadas 1–2 e vender atendimento e agenda sem cobrança integrada; o impacto em KAM-056, KAM-057 e KAM-059 fica listado | **satisfeito** | §6 do ficheiro: uma linha por ticket, com o que cada um é hoje (tipo, fase, prioridade, estimativa e dependências lidas do §3 do EPIC-05), o que muda com H5 **`refutada`**, e **o que não muda** — que é a coluna que evita o excesso. O achado desta secção é que **os três já têm a sua saída escrita no próprio bloco**, e o que H5 `refutada` muda é o **gatilho**, não o desenho: o critério **9** do **KAM-056** — são nove, e o 8 é o do OPG; a primeira versão dizia 8, achado da revisão adversarial — já manda `proxypay_enabled=false` com a decisão registada «gatilho H5»; o **KAM-057** é um *spike* de decisão escrita e um «não adoptar, por estas razões» é produto válido dele, com o critério 3 do próprio ticket a proibir tratar um NÃO VERIFICADO como facto; o **KAM-059** já prevê «a conta EMIS própria da KAMBÁ é NÃO VERIFICADA (D4); saída: `ManualProvider` + factura manual», com dupla aprovação de operações no critério 5. Fica dito que o `commission_enabled=false` **não** é efeito de H5 (é D8/ADR-017, por outra razão), e que a secção **não altera** linha nenhuma do backlog mestre — replanear sobre H5 `inconclusiva` era replanear sobre um dado que não existe, e está devolvido ao **Responsável de Produto**, §11, item 13 |
| 7 | Verificação empírica do *sandbox* ProxyPay (referência por `PUT`, pagamento simulado, `GET /payments`, números OPG `900000000`, `900002004`, `900003000`) arquivada como INDÍCIO-forte, sem substituir a resposta escrita | **parcial** | **O instrumento existe, corre, e está medido**: `spikes/proxypay-d4/` com `provedor_mock.py` (o alvo) e `sandbox.py` (dez predicados), Python da biblioteca padrão, sem Docker e sem rede — **10 de 10 verdes** contra o *mock*, e o canário com **dezesseis defeitos, dezesseis vermelhos**. Os três números OPG estão nos ensaios, com os quatro desfechos (2004, 3000 e o 2010 do móvel fora da lista), e há o **receptor que registra os cabeçalhos** que os «Detalhes Técnicos» pedem. O §8.2 arquiva-o como **INDÍCIO-forte sobre o instrumento** e di-lo na última linha da própria saída: *um mock passa nos ensaios de quem o escreveu*. **O que falta é a corrida contra o fornecedor**, e são **duas** coisas e não uma (§8.3): as **chaves de *sandbox***, que se pedem à TimeBoxed e por isso são acto do fundador, e **adaptar o cliente** ao contrato real — duas peças do *mock* são **inventadas** (a rota de configuração do *callback* do RPS, que na ProxyPay se faz no **portal**, e o corpo do pagamento simulado). **Não é «correr e ler»**. **A revisão adversarial mediu três ensaios a ficarem verdes sem medir o seu predicado, e os três estão corrigidos e re-medidos:** **(i)** o `amount` **não atravessava asserção nenhuma** — com a referência a guardar sempre `1.00`, os dez ensaios ficavam verdes e uma cobrança de 1.500,00 Kz liquidava por 1,00 Kz, o que é o **G4 «Valor exacto»** do `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5, **regra imutável**; o valor é agora exigido no pagamento **e** no corpo assinado do *callback*, com o defeito `valor-trocado` a provar os dois; **(ii)** o ensaio do `fee` testava a **presença da chave**, pelo que um `fee: null` passava — e é este o campo a que o §3.3 atribui o fecho do segundo componente de custo; exige-se agora decimal ≥ 0, com o defeito `fee-nulo`; **(iii)** o código do quarto desfecho do OPG era **importado do alvo**, no único sítio onde o comentário ao lado dizia ter evitado essa armadilha — trocar a constante do *mock* para `9999` deixava o ensaio verde a imprimir o valor errado como esperado, e é agora literal no ensaio, com a mutação re-medida a avermelhá-lo. **E uma afirmação desceu:** o ensaio da fila dizia medir a **regra b** do `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §8 e mede um `DELETE` de id **inexistente** — a regra b protege contra reconhecer um pagamento **conhecido** de outra integração da PME, e a defesa dela é **do nosso cliente**, não do contrato do fornecedor; está na lista do que o *spike* não mede, e devolvida ao **KAM-056** (§11, item 18). Dois registos que se mantêm: o **ensaio do *callback* do OPG é instrumento e não predicado** — se é assinado continua NÃO VERIFICADO, e um *mock* que o assinasse punha o *script* a provar a nossa própria escolha, pelo que o ensaio lista os cabeçalhos **sem afirmar nada** (o padrão do predicado 7 do KAM-126) —; e o defeito `put-nao-idempotente` **ficou verde na primeira corrida do canário**, pelo que foi o canário a apanhar o ensaio. Devolvido ao **fundador** (chaves) e ao **Engenheiro de Pagamentos** (adaptar e correr) — §11, itens 5 a 7 |
| 8 | A minuta de cada contraparte é revista pelo advogado (KAM-104) antes de assinar; nenhum contrato prevê que a KAMBÁ receba ou retenha fundos de terceiros | **parcial** | **A segunda metade está verificada e é a que não se negocia**: §7 do ficheiro. São cinco as colunas da matriz do §3.2 e **quatro** são do desenho **A** de E2 §3.3 (liquidação directa à PME) — a quinta, a EMIS directa, está excluída pelo portão (a) e não pelo fluxo de fundos; a primeira versão escrevia «as cinco (…) são todas do desenho A **e** a EMIS directa está excluída», que se contradizia. E **não existe coluna de PSP licenciado** — a pergunta 18 alimenta o §7.2 e Clusters, e o §2.7 escreve a fronteira: a resposta dela **não pode** entrar na matriz como opção de cobrança do Piloto, porque *payouts* são o desenho C. O §7.1 escreve as **seis** coisas que cada minuta tem de estabelecer — liquidação directa, prestador técnico sem posse, contratos **da PME**, **nenhuma** cláusula de retenção, caução, *escrow*, compensação ou dedução sobre fundos liquidados, **nenhum** mandato de *payout*, e, se houver conta-mestre ou ISV, a Entidade/POSID **da PME** dita por escrito —, e **quatro das seis** tocam a leitura do Aviso 2/22 e levam a ressalva **`(a confirmar por parecer)`** na própria linha — a primeira versão dizia «todas as seis» e a ressalva estava numa só, que é o tipo de frase que um advogado lê como garantia. Nenhuma leitura nossa de diploma angolano é definitiva. A **primeira metade não está satisfeita e não podia estar**: **nenhuma minuta existe**, porque nenhuma contraparte foi contactada, e rever é acto do advogado do **KAM-104**. Devolvido — §11, item 8 |

**Definition of Done — 2 de 5:**

| # | Caixa | Estado | Evidência ou credor |
|---|---|---|---|
| 1 | Todos os CA satisfeitos e demonstráveis | **não satisfeito** | 3 de 8; as cinco abertas são os critérios 1, 3, 4, 7 e 8 acima |
| 2 | D4 e H5 no registo com dono e data; KAM-056 e KAM-057 desbloqueados ou replaneados | **parcial** | **A primeira metade está feita**: **D4** no §5.4 e **H5** no §4.3, as duas com dono (fundador e Responsável de Produto) e data (2026-11-06). A segunda **não**, e não por omissão: KAM-056 e KAM-057 continuam bloqueados por `ext:KAM-103`, e **replanear sobre H5 `inconclusiva` era replanear sobre um dado que não existe** — o §6 escreve o impacto sem tocar numa linha do backlog mestre. Credor: **Responsável de Produto** (§11, item 13) |
| 3 | Sem chaves de API nem documentos bancários no repositório (cofre e arquivo controlado) | **satisfeito** | §10 do ficheiro: nenhum nome de pessoa (o registo de resposta identifica o remetente **pelo papel**), nenhum NIF, conta ou IBAN, nenhuma minuta e nenhum documento bancário. As chaves do *mock* **geram-se em cada arranque** e nunca vão a ficheiro; as de um fornecedor vêm do ambiente, e a sua **ausência faz o *script* recusar arrancar** em vez de correr metade. Gate 9 (`scan_secrets tree`) **limpo, 1950 ficheiros seguidos pelo git, código de saída 0**. E os três números OPG são de ensaio, **publicados pelo fornecedor**; o **quarto** — o «móvel fora da lista» do ensaio do OPG — é **nosso**, e por achado da revisão adversarial passou de um `92x` de nove algarismos, justificado por um «não pertence a ninguém» sem fonte, para o **intervalo ficticio `999`** que a UIT não atribui a país nenhum e que esta casa já usa (`tools/meta-sim/src/numeros.ts`). O *gate* 7 ficava verde nos dois casos, pelo que nada avermelhava: era a afirmação «números de telefone reais: nenhum» a assentar numa conta de três que deixava o quarto de fora. Medido no §8.4 que **nenhum dos quatro é apanhado pelo varrimento do *gate* 7**, e **confirmado pelo *runner***: o *gate* 7 passou em 31 s sobre o ramo, o que fecha a única caixa deste ticket que não dependia de um acto humano — **33 ficheiros e 115 ocorrências** na árvore, **idênticas ficheiro a ficheiro** ao `INVENTARIO` de `tools/meta-sim/src/inventario.ts` —, pelo que **nenhum ficheiro deste ticket leva entrada no inventário**, e uma entrada a mais **seria um defeito**: o inventário recusa entradas mortas, e uma que declarasse ocorrências onde o varrimento não encontra nenhuma avermelhava o portão |
| 4 | Itens NÃO VERIFICADOS de E2 (preços ProxyPay, assinatura de *callbacks*, prazo bancário) com estado final | **satisfeito** | §9 do ficheiro: uma tabela com **vinte e duas** afirmações, a de origem em E2 e a deste documento lado a lado — as **vinte** que vêm de E2, mais **duas que não vêm** e estão marcadas como tal, nascidas de achados da revisão adversarial: as duas promoções que ela encontrou estavam **no corpo** e não nesta tabela, porque a tabela não tinha linha para aquelas grandezas, e **nenhuma linha em que a segunda seja mais forte do que a primeira** — é essa a propriedade que importa. Os três que a caixa nomeia **mantêm-se NÃO VERIFICADOS**, cada um com a razão escrita e a pergunta que o fecha: preços ProxyPay (pergunta 7, e **não se transpôs** o preço da AppyPay), assinatura do *callback* do OPG (pergunta 8, e o §8 mede o instrumento e não isto), prazo bancário (perguntas 1 e 7, e é por isso que H5 fica `inconclusiva`). «Mantido com razão» é entrega; promover um destes a facto seria o defeito |
| 5 | Nenhum compromisso contratual de posse de fundos (ADR-004) — verificado por revisão jurídica | **parcial** | A **primeira metade está verificada aqui** (§7, e o critério 8 acima): nada neste documento prevê que a KAMBÁ receba ou retenha fundos, e o §7.2 levanta os dois sinais que vão no sentido contrário em vez de os deixar passar. A **revisão jurídica** é do **KAM-104** e nenhuma minuta existe para rever. Credor: **KAM-104**, com o **fundador** para o envio (§11, item 8) |

**A revisão adversarial devolveu 18 achados — 17 `CONFIRMADO` corrigidos e 1 parcialmente morto — e correu sobre o ramo depois de empurrar, sem ver o raciocínio de quem escreveu.** Os três que valeram mais eram todos do **instrumento**, e nenhum deles avermelhava portão nenhum: o `amount` não atravessava asserção nenhuma (o **G4 «Valor exacto»**, regra imutável, medido com os dez ensaios verdes e uma cobrança de 1.500,00 Kz a liquidar por 1,00 Kz), o `fee` era medido por presença de chave, e o código do quarto desfecho do OPG era **importado do alvo** no único sítio onde o comentário ao lado dizia ter evitado essa armadilha. Os três estão corrigidos, com dois defeitos novos no canário — **dezesseis, dezesseis vermelhos** — e a terceira mutação re-medida a avermelhar. No documento, o mais grave foi o **dono de D4**: estava «fundador» com uma citação que não o sustentava, e o registo em vigor (`00_KAMBA_Carta.md` §4.2) dá-o a «Produto». Dois foram da fronteira do **ADR-004**, e são os que importam a quem lê o sumário: o §5.2 apresentava a ProxyPay como destravável por uma só resposta sobre **preço** quando ela falha o portão da **liquidação directa**, e a frase de abertura dizia «o único sinal» contrário quando o §7.2 já nomeava **dois**. Um buraco no dossiê: **nenhuma** das cinco perguntas à AppyPay pedia o prazo de activação, que é metade de H5 nas duas colunas dela — entrou como pergunta **11-a**, acréscimo declarado, com a numeração de E2 §9 intacta. **O parcialmente morto:** a objecção de que o `INVENTARIO` não é a saída da ferramenta foi **matada pelo próprio ficheiro**, cujo cabeçalho diz «as contagens **não foram escritas à mão**: saíram do próprio *scan*»; o que sobreviveu dela foi a inconsistência de rótulo, e o §8.4 passou a separar as duas afirmações — a **fidelidade** da reimplementação é CONFIRMADO, o **resultado do portão** nesta árvore é INDÍCIO-forte. **O que a revisão deu por limpo**, com instrumento nomeado: as vinte linhas da tabela de estado do §9 que vêm de E2, uma a uma, **sem uma única promoção** (as duas que encontrou estavam no corpo, não na tabela); as dezoito perguntas de E2 §9 transcritas, comparadas palavra a palavra; os credores das caixas devolvidas, todos válidos e nenhum uma sessão, com KAM-100 e KAM-104 verificados como vivos; as linhas de KAM-056, KAM-057 e KAM-059 no backlog e os critérios alheios citados (três de quatro certos); a honestidade declarada do ensaio do *callback* do OPG; a ausência de preços, prazos e limites de terceiros inventados, rastreados um a um a E2; o varrimento do *gate* 7 reproduzido de forma independente, com os mesmos 33 ficheiros e 115 ocorrências; e os oito comandos de portão, todos a sair 0.

**O que não entra neste ticket.** O adaptador ProxyPay é o **KAM-056**; a decisão escrita sobre a AppyPay com `ProviderCapabilities` e registo MADR é o **KAM-057**; o parecer jurídico é o **KAM-104**. O *spike* vive em `spikes/`, é descartável e **não acrescenta critério a portão nenhum** — o que **não** quer dizer que os portões não o vejam: o varrimento do *gate* 7 lê `spikes/` como lê o resto da árvore, e o `spikes/h3/` do KAM-100 tem duas entradas no `INVENTARIO` a prová-lo. Se D4 fechar na ProxyPay, o adaptador nasce no KAM-056 e a pasta apaga-se. **Os dois artefactos que os «Testes Requeridos» nomeiam e que não existiam já existem, e os dois itens fecharam.** O `ci-7-meta` não corre nesta máquina — não há `node` nem `pnpm` —, mas o **gate 7 passou no *runner*** sobre este ramo, o que confirma a medição do §8.4 e fecha o item 16. E o `validar_evidencia.py` passou a existir quando o **KAM-100** fundiu em `111de2d`: corrido sobre a ficha, dá **exit 0**, depois de a tabela de cabeçalho ganhar as três declarações que ele exige — `Estado` (**NÃO VERIFICADO**, que é o que o documento é), `Fonte` e `Dono`. Item 15 fechado. **E com isso ficou medido um achado fora de escopo**, que não se corrige aqui: o validador **não é corrido por portão nenhum** — não está no `Makefile` nem no `ci.yaml` — e **nove ficheiros de `../docs/tecnica/evidencia/validacao/` recusam-no** — o predicado, e não o rácio: a população cresceu de 11 para 13 em poucas horas, com cada sessão a entregar a sua ficha, e **os nove não mexeram** em nenhuma das medições, a que o **KAM-100** registrou na sua linha de versão incluída. Abre pela **L1**, e o credor é quem escrever esse ticket.

### Handoff para Claude Code
```text
És o executor do ticket KAM-103 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-103), docs/tecnica/evidencia/E2_Pagamentos_Angola.md (§1, §8, §9) e docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§2 H5, §6).
Objectivo: preparar os dossiês para 2 bancos, ProxyPay e AppyPay, a matriz de decisão de D4 e a verificação do sandbox; as reuniões e contratos são humanos.
- Cria docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md com uma ficha por contraparte e as perguntas de E2 §9 por destinatário.
- Escreve o script de verificação do sandbox ProxyPay e um receptor de callback que regista cabeçalhos (para saber se o OPG é assinado).
- Constrói a matriz banco x facilitador com campo «fonte escrita» obrigatório; sem fonte, a célula fica NÃO VERIFICADO.
- Nunca inventes preços da ProxyPay nem prazos de bancos; sem chaves nem documentos bancários no repositório.
Não expandas escopo: o adaptador ProxyPay é KAM-056. Testes: script contra o sandbox e validar_evidencia.py. PR com o template da §7.
```

---
## KAM-104 — Pacote de perguntas para o parecer jurídico (APD, BNA, AGT, Termos Meta)

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-090, KAM-105 |
| Responsável sugerido | Responsável de Segurança (privacidade), com advogado externo |
| Documentos de referência | `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (20 perguntas), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§9 perguntas 19–30), `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.2, §8.3, §13, §15), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (Q7), `14` (§3 ponto 4), D1, D8, D9, D11, D12 |

### Contexto
Tudo o que toca APD, BNA, AGT e Termos da Meta está marcado «a confirmar por parecer»: não há lista pública de países adequados, nem cláusulas-tipo da APD (NÃO VERIFICADO), o enquadramento do modelo facilitador no Aviso 2/22 (art. 4.º) aguarda parecer, e o papel da KAMBÁ perante a Lei 22/11 está por decidir (D9). Precedente: a APD multou a Crescer Tech em USD 505 mil (2026-06-24) por transferir para uma cloud fora do país sem notificação nem autorização (CONFIRMADO; país de destino NÃO VERIFICADO). `14` §3 pede **pareceres escritos, não conversas**. Os textos legais lidos em E3 vieram de portais não oficiais e devem ser verificados no Diário da República.

### Objectivo
Entregar ao advogado um pacote completo, priorizado e com os factos do caso, que permita um parecer escrito sobre as decisões D1, D8, D9, D11 e D12, e contratar o advogado com âmbito, prazos e formato de resposta definidos.

### Critérios de Aceitação
- [x] `../docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md` (e exportação para o advogado) cobre 100% de: as 20 perguntas de E3; as perguntas 19–30 de E2 (BNA 19–25, AGT 26–29, contabilista 30); a leitura da cláusula §4.7 dos Termos da Meta (E1 Q7); N1 (CDN como subprocessador), N2 (backups cifrados fora de Angola com chave em Angola), N3 (HMAC com pepper) e N5 (desenho de pagamento fora do Aviso 2/22 art. 4.º j)) de `../docs/tecnica/08` §13; e 3 perguntas novas (X1 dados reais de teste com consentimento em spikes, X2 quem paga os custos em USD e retenções sobre pagamentos a fornecedores estrangeiros, X3 uso de conversas para avaliação face aos Termos da Meta).
- [x] Cada pergunta tem: n.º, texto, contexto, por que importa (decisão e tickets bloqueados), opções propostas pela KAMBÁ, resposta pedida (parecer escrito), prioridade (P0, P1, P2 de `../docs/tecnica/08` §13: P0 = E3 1, 2, 3, 4, 5, 6, 18, 20; P1 = 7, 9, 11, 12, 15, 16; P2 = 8, 10, 13, 14, 17, 19; BNA Q19–Q20 e Q30 propostos P0, restantes P1/P2) e prazo pedido.
- [x] Anexo «factos do caso» (≤ 6 páginas) gerado a partir de `../docs/tecnica/`: fluxos de dados, inventário de subprocessadores (`../docs/tecnica/08` §8.3.2), classes de dados, retenção proposta (§11), papéis (§8.2), arquitectura de pagamentos (liquidação directa, sem posse de fundos); sem dados pessoais.
- [ ] Pacote P0 enviado até ao dia 7 (fim da semana 1); resposta preliminar às P0 que decidem D1 pedida até à semana 3 e parecer escrito P0 até à semana 6; o prazo efectivamente comprometido pelo advogado fica registado.
- [ ] Selecção do advogado documentada: ≥ 2 propostas de honorários, critérios (experiência com APD e BNA), carta de compromisso com confidencialidade, âmbito P0/P1/P2, formato (parecer escrito com referência e data) e prazos.
- [ ] Registo de respostas: cada resposta recebida fica com data, autor, classificação «CONFIRMADO (jurídico)» e lista de tickets e decisões afectados (D1, D8, D9, D11, D12; KAM-069, KAM-070, KAM-088, KAM-090).
- [x] Os itens que a KAMBÁ assume até haver parecer ficam listados com dono (p. ex. comissão sobre transacção desligada, ADR-017; finalidades próprias da KAMBÁ desligadas, `../docs/tecnica/08` §8.2).

### Verificação dos Critérios de Aceitação

**7 critérios; 4 marcados, 3 vazios. 5 caixas de DoD; 3 marcadas, 2 vazias.**
Os três critérios vazios **não são trabalho esquecido: são actos humanos**, e
nenhum deles pode ser praticado por uma sessão — enviar um pacote, pedir
honorários a advogados e assinar, receber respostas por escrito. Para cada um, o
que havia de aproveitável ficou feito e está nomeado abaixo.

**O critério 3 foi desmarcado e voltou a marcar-se, e o caminho conta.** A
revisão adversarial mostrou que a minha conta de «6 páginas» só dava 6 porque não
pagava nada pelos espaçamentos entre parágrafos — com eles dava ~6,8 — e a caixa
ficou vazia com `parcial`. O defeito de fundo não era a aritmética: era que
**«≤ 6 páginas» sem renderizador nomeado não é um critério, é uma estimativa**.
O fundador autorizou medir uma vez em contentor; o anexo deu **7 páginas**, e
**7 não é ≤ 6**. Movi então a secção «o que ainda não existe» do anexo para o
§6.1 do pacote — nenhuma informação se perdeu, porque os dois ficheiros viajam
juntos — e a nova medição deu **6**. A caixa fecha com o renderizador e as
opções nomeados, que é o que faltava desde o início.

**O que é novo, em três ficheiros.** O pacote em
`../docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md`, o anexo em
`../docs/tecnica/evidencia/validacao/Anexo_Factos_do_Caso.md`, e os dois
artefactos internos — molde de selecção e registo de respostas — em
`../docs/tecnica/evidencia/validacao/Seleccao_e_Registo_Juridico.md`. Os dois
primeiros saem da casa; o terceiro não, e diz-o no cabeçalho.

### Os critérios, um a um

| # | Critério | Evidência |
|---|---|---|
| 1 | O pacote cobre 100% das 40 perguntas enumeradas | **Contadas, não estimadas: 40.** Por origem: **20** de `E3` (as «Perguntas para o advogado local» 1 a 20), **12** de `E2` §9 (BNA 19–25, AGT 26–29, contabilista 30), **1** de `E1` (a 7, a cláusula §4.7 dos Termos), **4** das linhas «Novas» de `../docs/tecnica/08` §13 (N1, N2, N3, N5) e **3** novas (X1, X2, X3). Por bloco: A 12, B 8, C 6, D 1, E 5, F 3, G 5. Por prioridade: P0 11, P1 19, P2 10. **As três somas fecham em 40**, e o §0.4 do pacote publica-as para que a divergência seja visível se alguma mudar. A verificação foi feita **da origem para o pacote**, item a item, que é a única direcção que encontra omissões. **O bloco G é um acrescento declarado:** os «Detalhes Técnicos» propõem seis blocos (A a F) e cinco das vinte perguntas de `E3` — defesa do consumidor, responsabilidade da plataforma, medicamentos, categorias restritas, desinformação — não cabem em nenhum deles; ou se forçavam para dentro de «APD e Lei 22/11», onde um advogado as leria como matéria de protecção de dados, ou ganhavam bloco próprio. **A exportação não existe**: nenhum conversor correu aqui, a exportação são os dois ficheiros sem nada retirado, e produzi-la é acto de quem envia — viaja com o critério 4 |
| 2 | Cada pergunta com os oito campos, prioridade e prazo | Os oito campos em cada um dos 40 blocos, pela mesma ordem: n.º (é o título), texto, contexto com o estado de verificação e a fonte, por que importa com a decisão e os tickets bloqueados, opções propostas pela KAMBÁ, resposta pedida, prioridade e prazo. **As prioridades não foram reinventadas**: as que o critério fixa estão como ele as fixa, incluindo as três P0 nomeadas (BNA 19, BNA 20, contabilista 30). Em **quatro** pontos a leitura da KAMBÁ diverge da letra — D-01, B-08, E-04 com E-05, e F-01 — e as quatro **ficam classificadas pela letra**, com a divergência medida no §5 do pacote e a decisão devolvida a quem escreveu o critério 2. A âncora da «semana 1» não está fixada em nenhum documento lido, e o pacote diz isso em vez de inventar datas |
| 3 | Anexo «factos do caso», ≤ 6 páginas, sem dados pessoais | **6 páginas, medidas e não estimadas**, com o renderizador nomeado: pandoc/latex:3.1 em contentor, `--pdf-engine=xelatex`, `-V geometry:a4paper -V geometry:margin=2.5cm -V fontsize=11pt --from=gfm`; a contagem de páginas do PDF foi feita por **três vias independentes** (objectos `/Type /Page` soltos, o `/Count` do nó raiz, e os `/Type /Page` dentro dos *object streams* descomprimidos) e **as três concordam**. O caminho até aqui está na [`ANALISE-43`](../docs/analises/ANALISE-43-KAM-104-pacote-parecer-juridico.md) §6.2: a conta anterior, por linhas, dava 6 só porque não pagava nada pelos espaçamentos entre parágrafos; a primeira medição a sério deu **7**, e 7 não é ≤ 6; movi a secção «o que ainda não existe» para o §6.1 do pacote — sem perder informação, porque os dois ficheiros vão juntos — e a segunda deu **6**. **Os seis itens que o critério enumera, todos presentes:** fluxos de dados (§2), inventário de subprocessadores (§4, a tabela de `../docs/tecnica/08` §8.3.2), classes de dados (§3), retenção proposta (§5, de `../docs/tecnica/08` §11), papéis (§6, de `../docs/tecnica/08` §8.2) e arquitectura de pagamentos com a liquidação directa e a ausência de posse de fundos (§7). **Sem dados pessoais:** varredura por telefone angolano, e-mail, NIF com valor e IBAN a dar **zero** no anexo e no pacote, e nenhum número de telefone no anexo. O anexo **acrescenta** duas lacunas do inventário que ninguém tinha escrito como lacunas — o CDN que termina TLS e o fornecedor de imagem sem linha no inventário — e o `../docs/tecnica/08` §18 mostra que o **KAM-069** já é o credor da segunda, pelo que não abre ticket |
| 4 | Pacote P0 enviado até ao dia 7; prazo comprometido registado | **Vazia, e o estado é `não satisfeito`. Enviar é acto humano**, e esta sessão não envia nada. O que está feito: o pacote está pronto a enviar, com os prazos pedidos por prioridade (preliminar na semana 3 para as sete P0 que decidem D1, escrito na semana 6 para todas as P0) e com a **tabela de prazos a comprometer** no §1.4 do `Seleccao_e_Registo_Juridico.md`, cuja coluna da direita — «prazo comprometido pelo advogado» — nasce vazia e é a que o critério manda registar. Falta também a **exportação** no formato em que o advogado o receberá, que viaja com o envio |
| 5 | Selecção documentada: ≥ 2 propostas de honorários, carta de compromisso | **Vazia, e o estado é `não satisfeito`. Pedir honorários a advogados não é acto de sessão.** O que está feito é o **molde**, no §1 do `Seleccao_e_Registo_Juridico.md`: dez critérios de selecção, três deles eliminatórios e os dois primeiros exactamente os que o critério nomeia (experiência com a APD e com o BNA); o âmbito dividido pelos três lotes de prioridade; o formato de parecer pedido em seis pontos; os prazos a comprometer; e a **minuta da carta de compromisso**, com uma cláusula de confidencialidade de sete números — incluindo a proibição de submeter a informação recebida a sistemas de inteligência artificial ou de tradução de terceiros, e a devolução ou destruição no fim. A minuta **não foi revista por advogado** e diz isso onde está. O §2 fica vazio, com as colunas certas |
| 6 | Registo de respostas com data, autor e classificação | **Vazia, e o estado é `não satisfeito`: não há respostas, porque o pacote não foi enviado.** O que está feito é a **tabela vazia com as colunas certas** (§3 do `Seleccao_e_Registo_Juridico.md`: n.º da pergunta, data, autor com cédula, referência do parecer, classificação, resumo, decisões afectadas, tickets afectados, acção), onde a coluna «Classificação» só admite `CONFIRMADO (jurídico)` e **só é preenchida por uma pessoa**, depois de receber o parecer por escrito. Mais o **mapa inverso** do §3.1, que é a parte aproveitável: por decisão (**D1, D8, D9, D11, D12**, e ainda D7, que o bloco C decide) e por ticket (**KAM-069, KAM-070, KAM-088, KAM-090**, os quatro que o critério nomeia, mais treze que o pacote encontrou pelo caminho), as perguntas cuja resposta os desbloqueia. E seis regras do registo, entre elas a que diz que uma resposta registada e não propagada é pior do que uma não registada, porque parece tratada |
| 7 | Itens assumidos até haver parecer, listados com dono | **17 itens**, no §4 do pacote, cada um com quatro colunas: a barreira que o sustenta hoje, a fonte, a pergunta que o liberta e o **dono**. Os dois exemplos que o critério dá estão lá e são os dois primeiros: a **comissão sobre transacção desligada** (ADR-017, D8, dono Produto) e as **finalidades próprias da KAMBÁ desligadas** (`../docs/tecnica/08` §8.2, D9, dono Responsável de Segurança). **Dois dos 17 não se libertam com este pacote**, e dizem-no: o Fluxo B depende de resposta escrita da Meta (KAM-101, D2) e o Score tem gatilho de fase (D11). E o §4 termina com o que **não** está assumido: o caminho dos webhooks atrás do proxy que termina TLS, cujas duas opções estão escritas em `../docs/tecnica/08` §8.3.2 e onde **nenhuma está decidida** — fica como decisão pendente de SRE, porque assumi-la sem a decidir era o inverso do que a lista faz |

### A revisão adversarial, e o que ela mudou

Uma passagem, um subagente read-only que recebeu o pacote, o anexo e os
requisitos e **não** o raciocínio de quem os escreveu. Devolveu **11 achados: 9
`CONFIRMADO`, 1 `PLAUSÍVEL`, 1 `MORTO`**, e cada `CONFIRMADO` foi reverificado
contra a árvore pós-merge, que não é a árvore sobre a qual a revisão foi lançada
— o `fd0a32d` entrou pelo meio. Todos se mantiveram. Os 9 estão corrigidos, o
`PLAUSÍVEL` desmarcou a caixa do critério 3, e o `MORTO` está registado com a
evidência que o matou. A análise, com os 11 e o método, está em
[`ANALISE-43`](../docs/analises/ANALISE-43-KAM-104-pacote-parecer-juridico.md).

**O achado que mais importava não era de forma.** O pacote afirmava, em três
sítios, que o conjunto de avaliação do sistema é «inteiramente sintético, sem
material real», e atribuía-o ao ADR-018. É falso: o **KAM-040** exige `origem ∈
{sintetico, t2_anonimizado, real_consentido}` e que nenhum caso
`real_consentido` entre **sem registo de consentimento**, e o
`../docs/tecnica/00` escreve «reescrita sintética **e por casos autorizados pela
PME**». O canon contradiz-se — a célula curta do registo de ADRs diz só
«reescrita sintética» —, e eu tinha citado o lado curto tendo o KAM-040 à mão.
Um parecer dado sobre «nada de material real» não responderia ao sistema
especificado, que é exactamente o modo de falha que este pacote existe para
evitar. Corrigido nas três ocorrências, e a barreira que **existe** — o registo
de consentimento por caso — entrou no §4 como o 17.º item assumido, com dono.

**Dois achados eram promoções de estado**, o defeito que esta casa diz ser o mais
comum: «os modelos, a transcrição e a própria Meta **já são** transferências»
aparecia como facto consumado quando `E3` §2 o marca **INDÍCIO**, e é a premissa
de **D1** inteiro; e «o CDN que termina TLS **é** subprocessador com acesso a
conteúdo» era a conclusão jurídica que a própria pergunta E-04 pede ao advogado.
Os dois ficaram com o estado e com a marca.

**E um era sobre uma promessa que o documento não cumpria.** O aviso de abertura
dizia que **toda** a afirmação jurídica levava *(a confirmar por parecer)*; a
marca aparecia 3 vezes no corpo, e 37 das 40 perguntas não tinham nenhuma. O
substituto real — a escala de três estados, aplicada pergunta a pergunta — é
legítimo e está correcto, mas a promessa descrevia outro documento. Passou a
descrever este.

### As duas caixas de DoD que ficaram vazias

| Caixa | Razão |
|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **Não pode ser marcada**: três critérios não estão satisfeitos, e nenhum deles é praticável por uma sessão. Marcá-la era contradizer as três caixas vazias logo acima |
| Carta de compromisso assinada e arquivada; pacote enviado com protocolo de recepção | Assinar, enviar e receber protocolo são actos humanos. Os campos para os registar existem no §2 do `Seleccao_e_Registo_Juridico.md` e estão em branco |

### O que esta entrega não decide, e devolve ao fundador

**A D1 não se decide aqui, e era o erro mais fácil de cometer.** O trabalho deste
ticket é dar ao fundador com que a decidir, não escolher por ele: as sete
perguntas que a decidem estão identificadas no §2.1 do pacote, com uma linha por
cada a dizer o que o KAM-105 **não consegue decidir sem ela**. As opções de
alojamento aparecem com o custo de cada lado — Luanda reduz os destinos a
autorizar mas **não dispensa** o procedimento, porque modelos, transcrição e a
própria Meta já são transferências; JNB/CPT acrescenta o alojamento à lista — e
a frase «a escolha é do fundador» está escrita nas três perguntas onde a
tentação de decidir era maior (E-01, E-03 e F-01).

**E há uma segunda decisão do fundador que este ticket levanta sem resolver:**
a entidade que paga os custos em USD, metade de **D9**. A pergunta F-02 entrega
as duas opções com as consequências de cada uma, e diz expressamente que a
KAMBÁ **não recomenda nenhuma**, porque a escolha tem efeitos de estrutura
societária e fiscal que não são de engenharia.

### Detalhes Técnicos
- **Componentes:** GOV (pasta de provas, E3 req. 25). Estrutura: A) APD e Lei 22/11; B) BNA e Aviso 2/22; C) AGT e factura; D) Termos e política da Meta; E) alojamento, CDN e backups; F) novas (X1–X3).
- A pergunta E3-20 (a Meta como destinatário, com notificação separada) e E3-4 (país da cloud no caso Crescer Tech) são P0 em `../docs/tecnica/08` §13. Texto legal citado com a fonte (lex.ao, angolex) e marcado «verificar no DR».
- O Claude Code consolida as perguntas, gera o anexo de factos a partir de `../docs/tecnica/`, mantém o registo de respostas e o mapa pergunta → decisão → ticket. **Não** dá parecer e não substitui o advogado; honorários e selecção são humanos.

### Testes Requeridos
- Revisão cruzada: contagem das perguntas de origem (20 + 12 + 1 + 4 + 3 = 40) contra o pacote, sem omissões nem mudança de sentido.
- Verificação de que o anexo de factos não contém dados pessoais e é coerente com `../docs/tecnica/08` §8.3.2 (inventário) e `../docs/tecnica/00` §8.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Carta de compromisso assinada e arquivada; pacote enviado com protocolo de recepção.
- [x] Confidencialidade respeitada; sem dados pessoais nem segredos no pacote.
- [x] Mapa pergunta → decisão → ticket publicado; KAM-105 informado do que depende de resposta.
- [x] Nenhuma resposta tratada como aconselhamento jurídico antes de recebida por escrito.

### Handoff para Claude Code
```text
És o executor do ticket KAM-104 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-104), docs/tecnica/evidencia/E3_Regulatorio_Dados.md (20 perguntas),
docs/tecnica/evidencia/E2_Pagamentos_Angola.md (§9, perguntas 19-30) e docs/tecnica/08_Seguranca_Conformidade.md (§8, §13).
Objectivo: montar o pacote de perguntas para o advogado e o anexo de factos do caso; não dás parecer jurídico.
- Consolida 40 perguntas (E3 1-20, E2 19-30, E1 Q7, N1, N2, N3, N5, X1-X3) com contexto, decisão afectada, prioridade e prazo pedido.
- Gera o anexo de factos a partir de docs/tecnica/08 §8.3.2 e §11 e de docs/tecnica/00; sem dados pessoais.
- Cria o registo de respostas (campo «CONFIRMADO (jurídico)» só preenchido por humanos) e o mapa pergunta -> decisão -> ticket.
- Marca «verificar no DR» onde o texto legal veio de portais não oficiais.
Não expandas escopo: a decisão D1 é KAM-105. Testes: contagem 40/40 e verificação de ausência de PII. PR com o template da §7.
```

---

## KAM-105 — Decisão de alojamento D1 e procedimento APD

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-104 |
| Bloqueia | KAM-069, KAM-077, KAM-079, KAM-110 |
| Responsável sugerido | Arquitecto de Plataforma e Responsável de Segurança (decide o fundador) |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§5, §19), `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.3, §8.5, §8.6, §15), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2, §7), `specs/00_KAMBA_Carta.md` (§4.2), ADR-008, D1, D6, D9 |

### Contexto
D1 (Luanda ou JNB/CPT com procedimento APD) condiciona alojamento, backups, STO (D6) e o gate de go-live: **sem D1 não há dados reais** (Carta §4.2; o fundador decide até à semana 3). Luanda não dispensa o procedimento APD, porque LLM, STT e a própria Meta já são transferências (E3 §7). As cotações de Luanda, os serviços geridos e a latência são NÃO VERIFICADOS; o doc 09 §5.2 usa «×1–2 de JNB» como hipótese de planeamento e VM 8 vCPU/32 GB de $300–400/mês em JNB como ESTIMATIVA. Taxas da APD: Decreto Presidencial 60/21, de 4.315 a 350.450 Kz (INDÍCIO). Prazos e silêncio positivo da APD: NÃO VERIFICADOS.

### Objectivo
Decidir D1 com cotações reais, registar D6 (consequência) e D9 (papel e quem notifica), produzir o mapa de tratamentos e submeter o procedimento APD por destino, com o gate de go-live escrito.

### Critérios de Aceitação
- [ ] `../docs/tecnica/evidencia/validacao/Alojamento_Cotacoes.md` com ≥ 3 cotações (≥ 2 de Luanda entre Raxio, Paratus, Angola Cables e Cloud Nacional, e ≥ 1 de JNB/CPT) para produção (8 vCPU/32 GB, NVMe ≥ 200 GB) e *staging* (4 vCPU/16 GB), com: tipo (colocation ou IaaS), preço mensal em Kz e USD, SLA, 2.º local para backups, IXP, contrato mínimo, facturação em Kz (S/N), Postgres e objectos geridos (S/N), prazo de provisionamento; cada linha com o documento de origem ou «sem resposta».
- [ ] A regra do doc 09 §5.3 aplicada em tabela: cotação de Luanda ≤ 2× a de JNB (S/N), VMs com SLA (S/N), 2.º local angolano para backups (S/N); resultado: **D1 = Luanda** (as 3 em S) ou **D1 = JNB/CPT com procedimento concluído**; decisão com dono, data e assinatura do Responsável de Produto e do de Segurança.
- [x] Teste de latência RTT com VM ou *trial* quando o fornecedor o oferecer; sem oferta fica «NÃO MEDIDO» e o KAM-077 mede.
- [x] D6 registada como recomendação dependente de D1 (SeaweedFS 4.48 *single node* ou S3 gerido), com a lista de testes pendentes (KAM-076); a decisão final fica em KAM-011.
- [x] D9 registada com base na resposta do advogado a E3-1: papel da KAMBÁ (subcontratada por defeito, `../docs/tecnica/08` §8.2), quem notifica a APD (plataforma, PME ou ambas) e a entidade que paga os custos em USD; se o parecer ainda não chegou, a decisão é **provisória**, marcada como tal.
- [x] `Mapa_Tratamentos_v1.md` gerado do inventário de subprocessadores: por destino (Meta, LLM, STT, alojamento, backups, CDN se existir, e-mail/SMS, sonda, facilitador), país, finalidade, categorias de dados, retenção proposta, garantias (retenção zero, sem treino) e estado do `apd_ref`; o número de destinos de produção do Piloto é reduzido ao mínimo (*proposta*: 1 LLM, 1 STT).
- [ ] Submissão à APD feita por destino com taxas pagas e **número de protocolo**, ou decisão escrita do advogado de que não é exigida; folha de seguimento (`submetido`, `em apreciação`, `autorizado`, `negado`) com os prazos reais decorridos.
- [x] `GoLive_Gate.md` com a checklist objectiva de entrada de dados reais: D1 decidida; cada destino de produção com `apd_ref` válido; mapa aprovado; DPA e aviso publicados (KAM-090); D9 decidida; checklist de segurança de `../docs/tecnica/08` §8.5 #11; cada linha com estado e data.

### Verificação dos Critérios de Aceitação

**8 critérios; 5 marcados, 3 vazios. 5 caixas de DoD; nenhuma marcada.**
As três caixas vazias de critério e as cinco de DoD têm a mesma causa, e
convinha dizê-la antes dos detalhes: **este ticket depende de dois actos que
ninguém desta casa praticou ainda** — pedir cotações a fornecedores e enviar o
pacote de perguntas ao advogado — e de uma decisão que é do fundador. O que
estava ao alcance ficou feito; o que não estava ficou **vazio e nomeado**.

**Quatro ficheiros novos**, todos em `../docs/tecnica/evidencia/validacao/`:
`Mapa_Tratamentos_v1.md`, `GoLive_Gate.md`, `Alojamento_Cotacoes.md` e
`Seguimento_APD.md`.

### Os critérios, um a um

| # | Critério | Evidência |
|---|---|---|
| 1 | Cotações: ≥ 3, com ≥ 2 de Luanda e ≥ 1 de JNB/CPT | **Vazia, estado `não satisfeito`. Pedir uma cotação a um fornecedor é acto humano**, e foram pedidas **zero**. O que está feito é o molde: um **modelo de pedido com dez pontos** que fixa as capacidades do critério (produção 8 vCPU/32 GB com NVMe ≥ 200 GB, pré-produção 4 vCPU/16 GB) e uma **tabela de dezasseis colunas** que contém as dez que o critério enumera, com seis linhas vazias para três fornecedores × dois ambientes e a coluna **Fonte** a impor «documento de origem ou "sem resposta"». **Nenhuma célula estimada**, que é o 1.º Teste Requerido: medido por varredura, os números herdados do `../docs/tecnica/09` — «~52 ms», «$300–400/mês», «×1–2 de JNB» — ou estão fora das tabelas e declarados hipótese/ESTIMATIVA, ou expressamente recusados |
| 2 | Regra do `../docs/tecnica/09` §5.3 em tabela e **decisão D1** | **Vazia, estado `parcial`.** A regra está em tabela e fiel à fonte: R1 (cotação de Luanda ≤ 2× a de JNB), R2 (VMs com SLA), R3 (2.º local angolano), com a conclusão certa — Luanda se as três forem `S`, senão JNB/CPT com procedimento concluído — e o bloco de decisão com dono, prazo da Carta, data e as duas assinaturas. **O que falta é o resultado**, e não se pode fabricar: R1, R2 e R3 leem-se das cotações do critério 1, que são zero. **E a decisão é do fundador** (Carta §4.2), não desta sessão |
| 3 | Latência RTT, ou «NÃO MEDIDO» e o KAM-077 mede | **Três medições `NÃO MEDIDO`**, cada uma com a razão, pelo caminho que o próprio critério prevê — «sem oferta fica "NÃO MEDIDO" e o KAM-077 mede» — e com o **ponto 9 do pedido de cotação** a pedir a máquina de ensaio que torna a medição possível. **Uma divergência de leitura, declarada:** o critério escreve o caminho para «sem oferta», e o que há é «sem contacto» — que é um caso mais largo, não o mesmo. **Não usei o «~52 ms» do `../docs/tecnica/09` §5.2**, por ser INDÍCIO da biblioteca exploratória e não uma medição |
| 4 | D6 como recomendação dependente de D1, testes pendentes, decisão em KAM-011 | Recomendação **por cenário de D1**: Luanda → SeaweedFS em nó único, porque os objectos geridos em Luanda são NÃO VERIFICADO; JNB/CPT → S3 gerido. Quatro testes pendentes, e a atribuição está correcta depois da revisão: **T1 a T3 são os que o `../docs/tecnica/09` §19 lista**, e o **T4 é acrescento nosso**, da cobertura de cópias do §8.1 — a primeira versão atribuía os quatro ao §19, que só tem três. Decisão final em **KAM-011**, dito onde está. E uma consequência que o critério não pedia: um nó único **sem** segundo local angolano fica com ponto de perda total de objectos, o que faz da R3 mais do que um critério de preço |
| 5 | D9 registada; **provisória** se o parecer não chegou | Registo **PROVISÓRIO**, pelo caminho que o critério prevê por escrito, em `../docs/tecnica/evidencia/validacao/Seguimento_APD.md` §3 e agora também no registo da Carta §4.2 com dono e data. **Duas das quatro linhas põem por escrito o que o desenho já assume** — subcontratada por defeito e finalidades próprias desligadas — e **duas ficam vazias**: quem notifica a APD (pergunta A-01) e a **entidade que paga os custos em USD, que é decisão do fundador** (pergunta F-02). O registo **não desbloqueia nada**: as linhas A2 e A3 do gate continuam em branco, e é essa a prova de que não foi tratado como decisão |
| 6 | `Mapa_Tratamentos_v1.md` do inventário, por destino, com seis campos; destinos reduzidos ao mínimo | **Catorze destinos**, cada um com os seis campos que o critério nomeia — país, finalidade, categorias de dados, **retenção proposta**, garantias e estado do `apd_ref` (a retenção por destino entrou depois da revisão; faltava). Os nove destinos que o critério enumera estão todos cobertos, **a sonda incluída**. A redução ao mínimo está como **proposta** com o que se perde — 1 modelo e 1 transcrição significa que uma falha de fornecedor degrada para o modo determinístico, e não para outro fornecedor. **O mapa saiu de três fontes e a terceira é código:** as treze listas de saída da pilha, porque o `tenant_destinations` que o `../docs/tecnica/08` §8.6 manda usar **não existe** (KAM-069). Da reconciliação das três saíram **sete divergências**, duas delas destinos sem linha no inventário |
| 7 | Submissão à APD por destino, com taxas e **número de protocolo** | **Vazia, estado `não satisfeito`. Submeter, pagar taxas e receber protocolo são actos humanos**, e nenhum se faz sem o parecer que o KAM-104 vai pedir. O que está feito é a folha com as colunas certas e os quatro estados do critério — catorze linhas, **zero submetidas** — mais **Dono** e **Prazo-limite**, que a caixa 5 de DoD pede e que faltavam. A coluna «via» fica **em branco de propósito**: decidir se um país é adequado era usurpar a pergunta E-01. E os sete passos que antecedem a primeira mudança de estado, o primeiro dos quais é enviar o pacote |
| 8 | `GoLive_Gate.md` com as condições objectivas, cada linha com estado e data | **38 linhas** em cinco blocos, e as seis condições que o critério nomeia estão todas: D1 → A1; `apd_ref` por destino → B2 **e o bloco E, uma linha por destino**, que entrou depois da revisão para cumprir o 2.º Teste Requerido («nenhum destino fica sem linha»); mapa aprovado → B1; DPA e aviso → C1 e C2; D9 → A2 e A3; checklist do `../docs/tecnica/08` §8.5 #11 → D3t. **Cada estado é exactamente um dos quatro do §0** — medido, 38 linhas e 38 estados — e a contagem reproduz-se por máquina: **5 satisfeitas de 36 obrigatórias**, com as datas só nas satisfeitas |

### As cinco caixas de DoD, e porque nenhuma fecha

| Caixa | Razão |
|---|---|
| Todos os Critérios satisfeitos e demonstráveis | Três não estão. Marcá-la contradizia as três caixas vazias acima |
| D1, D6 e D9 no registo da Carta com dono e data; **KAM-077 e KAM-069 desbloqueados** | A primeira metade está feita — a Carta §4.2 ganhou, nas três linhas, o apontador para o que este ticket produziu, com dono e data, **sem mudar nenhum estado**. A segunda metade **não**: o KAM-077 e o KAM-069 dependem de **D1**, que não foi decidida, e continuam bloqueados |
| Nenhum dado real tratado antes do gate; **documentos contratuais em arquivo controlado** | A primeira metade é verdadeira e verificável — não há produção, e o gate existe e mede. A segunda **não tem objecto**: não há contrato nenhum assinado, logo não há arquivo controlado. Marcar por vacuidade era o contrário do que esta caixa serve |
| Itens NÃO VERIFICADOS do `../docs/tecnica/09` §19 com **estado final** | Os três que o DoD nomeia — cotações, latência e serviços geridos — continuam **NÃO VERIFICADO**, e o §19 não foi tocado. É consequência honesta de não haver cotações: um estado final exigia resposta de fornecedor |
| Autorização da APD em seguimento com **prazo-limite e dono**; o estado entra no KAM-108 e no KAM-110 | As colunas **Dono** e **Prazo-limite** existem agora na folha, e nascem vazias — o dono só se atribui depois de **A-01** dizer quem submete. Sem submissão nenhuma, não há autorização em seguimento |

### O que a revisão adversarial mudou, e o achado que importava

Uma passagem, read-only, sem ver o meu raciocínio: **17 achados**, e a análise
está em
[`ANALISE-46`](../docs/analises/ANALISE-46-KAM-105-alojamento-e-procedimento-apd.md).

**O grave era a afirmação mais forte do mapa, e estava errada na razão que
dava.** Eu escrevera que «não existe caminho pelo qual dados pessoais de
produção saiam da plataforma» porque as saídas que os levariam não estão
declaradas. **A inferência estava invertida:** as listas de `egress` são
**contratos**, não aplicação — a aplicação na rede é o KAM-076 e não está
feita, o que a **minha própria linha D2t** registava duas seccões adiante. Com a
aplicação em falta, «não declarado» significa «não governado», não «fechado». E
havia contra-exemplo: o `packages/core-ts` fixa `graph.facebook.com` numa
constante e monta um corpo que leva o telefone — e **`packages/` e `libs/` estão
fora do regime de `egress`**, medido, zero ficheiros. O que ficou escrito é mais
estreito e verdadeiro: **nenhum serviço em execução instancia hoje um cliente de
saída para terceiros**, pelo que a contenção é de **ausência de ligação** e não
de controlo.

**Dois outros eram de substância.** As listas de saída são **treze** e não seis
— `infra/egress/` tem oito ficheiros —, e o Medusa e a pilha de observação não
têm lista nenhuma. E a coluna **`finalidade`** sobre-declarava em dois dos três
destinos de modelos: derivada do `llm/aliases.yaml` com o `destinos.py`, o
primeiro serve só `conversa` e o outro serve `visao` e `embeddings`. **`purpose`
é coluna do formulário da APD**, e declarar uma finalidade a mais é pedir
autorização para uma transferência que não existe.

**E um que não foi da revisão.** Nenhum dos seis linters verifica referências de
secção nem caminhos fora dos blocos de *handoff*. Escrevi um script que extrai
as citações `<ficheiro> §N` destes ficheiros e confirma que a secção existe no
alvo: apanhou **dois caminhos que não resolviam**, e depois de corrigido apanhou
uma classe que lhe escapava — as citações dentro de ligações Markdown, onde
vivia uma remissão quebrada que a revisão encontrou à mão. **92 citações, 92
válidas.**

### Detalhes Técnicos
- **Componentes:** GOV, TEN; consumidores: KAM-069 (inventário e gate), KAM-077 (alojamento). `tenant_destinations(tenant_id, provider, country, purpose, apd_ref, status)` por omissão negado.
- Backups e CDN contam como alojamento: localização de `repo1` e opção (a)/(b) de D12 entram no mapa. Cotações pedidas a Raxio, Paratus, Angola Cables, Cloud Nacional e a um hiperescalador em JNB/CPT (doc 09 §5.3 ponto 5).
- O Claude Code prepara o modelo de pedido de cotação, a tabela comparativa, a geração do mapa a partir do inventário e a folha de seguimento da APD; as reuniões, a decisão e a submissão são humanas.

### Testes Requeridos
- Revisão de que nenhum valor de preço, SLA ou latência é estimado: todas as células têm documento de origem ou «sem resposta».
- Verificação de que cada destino do mapa coincide com `../docs/tecnica/08` §8.3.2 e que nenhum destino de produção fica sem linha no `GoLive_Gate.md`.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] D1, D6 (recomendação) e D9 no registo da Carta com dono e data; KAM-077 e KAM-069 desbloqueados.
- [ ] Nenhum dado real tratado antes do gate; documentos contratuais em arquivo controlado.
- [ ] Itens NÃO VERIFICADOS do doc 09 §19 (cotações, latência, serviços geridos) com estado final.
- [ ] A autorização da APD fica em seguimento com prazo-limite e dono; o estado entra no KAM-108 e no KAM-110.

### Handoff para Claude Code
```text
És o executor do ticket KAM-105 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-105), docs/tecnica/09_Topologia_Operacao_Escala.md (§5),
docs/tecnica/08_Seguranca_Conformidade.md (§8.3, §8.5, §8.6) e docs/tecnica/evidencia/E3_Regulatorio_Dados.md (§2, §7).
Objectivo: preparar a comparação de cotações, o mapa de tratamentos e o gate de go-live; a decisão D1 e a submissão à APD são humanas.
- Cria Alojamento_Cotacoes.md (modelo de pedido e tabela), aplica a regra do doc 09 §5.3 e deixa a decisão por preencher.
- Gera Mapa_Tratamentos_v1.md a partir do inventário de subprocessadores (docs/tecnica/08 §8.3.2) e GoLive_Gate.md com as condições objectivas.
- Cria a folha de seguimento da APD por destino; nunca estimes um preço, SLA ou prazo: «sem resposta» ou NÃO VERIFICADO.
- Sem dados pessoais nem segredos.
Não expandas escopo: a implementação do gate no código é KAM-069. Testes: revisão cruzada de fontes e de cobertura dos destinos. PR com o template da §7.
```

---

## KAM-106 — Canais de acesso a PMEs e 30 entrevistas (H1, H2)

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | — |
| Bloqueia | KAM-110 |
| Responsável sugerido | Responsável de Produto |
| Documentos de referência | `14` (§2 H1 e H2, §3 pontos 1–2, §3A Regra 4, §6), `../docs/tecnica/10_Onboarding_Governanca.md` (§12, §16), `../docs/tecnica/00_Arquitectura_Solucao.md` (§12 risco «preço opaco»), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (riscos 4 e 9) |

### Contexto
«Ponto de partida honesto: não há rede comercial» (`14` §3). O produto é para o segmento A (PMEs formais ou em formalização em Luanda, com NIF e conta bancária). H2 mede se o preço pode ser publicado ou respondido (≥ 50% das PMEs aceitam preço fixo ou «a partir de» para ≥ 70% do catálogo); H1 só se mede no piloto (KAM-109), mas as entrevistas dão o sinal inicial e o preço de referência (30–60 mil Kz, hipótese). Há ainda um risco de mercado de E1: categorias vedadas pela Meta (álcool, tabaco, saúde, crédito, apostas) cobrem fatia relevante do comércio de PMEs.

### Objectivo
Abrir e testar 5 canais de acesso a PMEs, realizar 30 entrevistas estruturadas sem *pitch* e medir H2 com limiar e pivô definidos, deixando uma lista de PMEs candidatas ao piloto.

### Critérios de Aceitação
- [ ] `../docs/tecnica/evidencia/validacao/Entrevistas_Guiao.md` (guião curto, sem *pitch*) cobre: dor de atendimento, como vendem e cobram hoje, que comprovativos recebem, quanto pagariam, e a classificação dos 20 produtos principais em `fixo`, `a partir de` ou `sob consulta`; ficha de registo com campos fixos (id anónimo, categoria, formal S/N, n.º de empregados, canal de origem, dor 1–5, comprovativos por semana, faixa de preço, cartão internacional S/N, categoria vedada S/N, disponível para piloto S/N, consentimento).
- [ ] **30 entrevistas completas até ao fim da semana 4** (n = 30; entrevistas incompletas não contam); no máximo 40% vindas de um só canal (*proposta*, para limitar enviesamento).
- [ ] **Limiar H2:** o *script* calcula, por PME, a percentagem dos 20 produtos em `fixo` ou `a partir de`; H2 `confirmada` se ≥ 15 de 30 PMEs (≥ 50%) tiverem ≥ 70% (≥ 14 de 20). Se < 15: H2 `refutada` e pivô de `14` §6 (reposicionar para atendimento e disponibilidade, não comparação de preço), com impacto em KAM-043, KAM-061 e na mensagem comercial listado.
- [ ] Sinal de H1: distribuição de disposição a pagar por faixa (< 15 mil, 15–30 mil, 30–60 mil, > 60 mil Kz) e n.º de PMEs disponíveis para um piloto gratuito de 30 dias; se < 10 PMEs disponíveis após as 30 entrevistas, regista-se «problema de distribuição» e aplica-se a última linha de `14` §6.
- [ ] 5 canais testados (contabilistas e gabinetes, associações comerciais, programas PME de bancos, incubadoras e 1 outro), cada um com ficha: contacto, data da 1.ª reunião, oferta (comissão só por PME paga, `14` §5), PMEs-alvo entregues, entrevistas obtidas, estado. Um canal é **repetível** se entregou ≥ 6 PMEs-alvo em ≥ 2 rondas (*proposta*); decisão por canal (manter ou descartar) até à semana 6.
- [ ] Se nenhum canal for repetível à semana 6: decisão escrita de resolver a distribuição antes de construir mais (parceiro de banco, associação ou contratar comercial), com dono e data.
- [ ] Lista de 30 PMEs-alvo mais suplentes, com a categoria registada; o *script* devolve a % de PMEs em categoria vedada pela Meta ou pela lei (entrada para KAM-088) e o n.º com cartão internacional (entrada para KAM-102/D5).
- [ ] Resumo `H1H2_Entrevistas_Resumo.md` com contagens absolutas (não só percentagens) e a ressalva de que n = 30 é **direccional**; dados brutos fora do repositório, em arquivo controlado.

### Detalhes Técnicos
- **Componentes:** nenhum de software; alimenta KAM-043, KAM-088, KAM-102 (cartão), KAM-109 (candidatas ao piloto) e o preço de referência de KAM-081.
- Privacidade (Lei 22/11): consentimento por escrito ou gravado para registar notas; identificadores anonimizados; contactos em arquivo controlado; sem dados de clientes finais das PMEs. Entrevistar PMEs de categorias vedadas é legítimo para medir a perda, mas não as inscreve no piloto.
- Limiares de H2 e a definição de «repetível» são propostas fixadas antes da primeira entrevista; alteração só por emenda registada.
- O Claude Code prepara guião, ficha (CSV e formulário), *script* de H2, folhas de seguimento de canais, texto de consentimento e modelo de resumo. As entrevistas e reuniões são humanas.

### Testes Requeridos
- Teste unitário do *script* de H2 com *fixtures* (limiar: 14/20 itens e 15/30 PMEs, casos de fronteira 14 e 13).
- Revisão cruzada do guião (sem *pitch*, sem perguntas orientadoras) por pessoa distinta do autor; ensaio com 2 entrevistas-piloto antes da amostra.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] H2 no Registo de Hipóteses com resultado, fonte, decisão e data; sinal de H1 registado.
- [ ] Consentimentos arquivados; dados brutos fora do repositório; sem dados pessoais no resumo.
- [ ] Decisões por canal e a de distribuição (se aplicável) registadas com dono e data.
- [ ] Lista candidata ao piloto entregue ao KAM-109.

### Handoff para Claude Code
```text
És o executor do ticket KAM-106 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-106) e docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§2 H1/H2, §3, §3A Regra 4, §6).
Objectivo: preparar o material das 30 entrevistas e a medição de H2; as entrevistas e as reuniões com canais são feitas por humanos.
- Escreve Entrevistas_Guiao.md (sem pitch), a ficha de registo (CSV com os campos fixos) e o texto de consentimento em PT-AO.
- Escreve o script de H2 (>=70% dos 20 itens em fixo ou a partir de; >=50% das PMEs) com testes de fronteira e o script de resumo por canal.
- Cria as fichas de canal e a lista-alvo com a categoria registada; calcula % em categoria vedada e n.º com cartão internacional.
- Não inventes dados de PMEs nem contactos; dados brutos nunca no repositório.
Não expandas escopo: o piloto é KAM-109. Testes: unit do script de H2 e revisão do guião. PR com o template da §7.
```

---

## KAM-107 — Spike de voz PT-AO: WER e latência de dois STT com áudio real

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 1 |
| Tipo | spike |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-030 |
| Bloqueia | KAM-036 |
| Responsável sugerido | Engenharia de agentes/produto |
| Documentos de referência | `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§3.2, §3.4, §3.5, §4), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§14.2–14.3), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.5), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (req. 7, 8), `14` (§2 H7), ADR-005, ADR-008, ADR-018 |

### Contexto
A qualidade de STT em português de Angola é NÃO VERIFICADA (E4 §3.5: não há *benchmark* por variante) e não existe STT de produção para Kimbundu ou Umbundu (doc 00 §11). Candidatos com preço: Groq `whisper-large-v3-turbo` a $0,04/hora (INDÍCIO-forte) e OpenAI `gpt-4o-mini-transcribe` a ≈ $0,003/min (CONFIRMADO); preços a reconferir antes de fixar. O orçamento de voz do doc 00 §9 é p95 de 6 a 12 s no total. O áudio é dado pessoal (voz) e, enviado a Groq ou OpenAI, é transferência internacional (E3 §2). Áudio de clientes de uma PME é também dado da plataforma WhatsApp, sujeito aos Termos da Meta sobre ML (E1 §4, ADR-018). Por isso «áudio real» significa **fala real gravada de propósito**, não áudio de conversas de clientes.

### Objectivo
Medir WER, precisão numérica, latência e custo de dois STT com fala real em português de Angola e decidir o STT primário (ou que a voz fica só em *handoff* no Piloto).

### Critérios de Aceitação
- [ ] Corpus gravado de propósito (não de conversas de clientes): ≥ 10 falantes, ≥ 200 enunciados de 5 a 30 s, com ≥ 40% contendo números, preços, quantidades ou horas, ≥ 20% com palavras de Kimbundu ou Umbundu ou mistura de línguas, ≥ 20% em ambiente ruidoso (*proposta*); transcodificado para Opus/OGG como no WhatsApp; transcrições de referência por 2 anotadores com divergência ≤ 3% reconciliada.
- [ ] Consentimento escrito de cada falante (inclui envio a um fornecedor nos EUA); áudio apagado do nosso armazenamento ≤ 24 h após transcrever e no fim do spike; definição de retenção e não-treino do fornecedor verificada e registada (E3 req. 8); a pergunta X1 de KAM-104 respondida ou o risco aceite por escrito antes de enviar áudio.
- [ ] `../docs/tecnica/evidencia/validacao/H7_Voz_STT.md` com, por STT: WER global e por grupo, precisão de tokens numéricos, latência p50 e p95 para clips de 5, 15 e 30 s (≥ 30 execuções por tamanho, em 3 momentos do dia), taxa de erro ou *timeout*, e se a API devolve sinal de confiança por segmento (S/N; NÃO VERIFICADO até testar).
- [ ] **Limiares pré-registados (*proposta*):** WER global ≤ 20%; precisão numérica ≥ 95%; latência p95 do STT ≤ 3 s para clips ≤ 30 s (fatia do orçamento de 12 s da voz); sinal de confiança que assinala ≥ 70% dos enunciados com WER > 40%.
- [ ] **Regra de decisão:** ambos passam → o de menor custo é primário e o outro *fallback*; só um passa → esse é primário; nenhum passa → a voz fica só em *handoff* a humano no Piloto e remove-se da promessa comercial; falha apenas nos números → voz activa só com eco e confirmação dos números (alinhado com KAM-036). Decisão com dono e data.
- [ ] Custo por hora de áudio e por PME/mês (300 min de voz, doc 09 §14.3: ≈ $0,2 com Groq e ≈ $0,9 com OpenAI como ESTIMATIVAS) comparado com o medido; preços relidos nas páginas dos fornecedores com data.
- [ ] Os fornecedores usados entram no inventário de subprocessadores (KAM-069) com estado do `apd_ref`; a parte de voz de H7 (≥ 85% sem *handoff* errado) fica registada como dependente desta decisão e do golden (KAM-040).

### Detalhes Técnicos
- **Componentes:** LLM/STT (interface `SttProvider`, via KAM-030), MED. Normalização para o WER: minúsculas, sem pontuação, numerais normalizados da mesma forma na referência e na hipótese («mil e quinhentos» = 1500); regras versionadas.
- Conteúdo dos enunciados (roteiro de ≈ 220 frases): preços em kwanzas, quantidades, horas e datas, moradas e bairros de Luanda, nomes de produtos, regateio, pedidos de marcação; sem dados pessoais reais.
- O Claude Code prepara: protocolo de gravação, roteiro, esquema do manifesto do corpus, *script* de transcodificação (ffmpeg), *harness* que chama os dois STT, *script* de WER e de latência, cálculo de custos e modelo do relatório. Recrutar falantes, gravar e anotar são tarefas humanas.

### Testes Requeridos
- Unit do *script* de WER com casos conhecidos (substituição, omissão, numerais) e do normalizador; ensaio do *harness* com um *fake* STT.
- Verificação de que o relatório não contém áudio nem identificação de falantes e de que os limiares estão datados antes da primeira medição.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Decisão STT no registo com dono e data; subprocessadores actualizados (ADR-008).
- [ ] Áudio apagado e consentimentos arquivados; sem chaves de API no repositório.
- [ ] Item NÃO VERIFICADO «qualidade PT-AO e latência» de E4 com estado final.
- [ ] KAM-036 informado da decisão (STT e regra de eco/confiança).

### Handoff para Claude Code
```text
És o executor do ticket KAM-107 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-107), docs/tecnica/evidencia/E4_Stack_Licencas.md (§3), docs/tecnica/08_Seguranca_Conformidade.md (§7.5)
e docs/tecnica/evidencia/E3_Regulatorio_Dados.md (req. 7 e 8).
Objectivo: preparar o spike de voz; a gravação, o consentimento e a anotação são humanos.
- Escreve o protocolo de gravação, o roteiro (~220 frases PT-AO com números, preços, horas, moradas de Luanda), o manifesto do corpus e o script ffmpeg para Opus/OGG.
- Implementa o harness para dois STT (Groq whisper-large-v3-turbo e OpenAI gpt-4o-mini-transcribe) atrás de SttProvider, e os scripts de WER (com normalizador de numerais), latência p50/p95 e custo.
- Gera o relatório H7_Voz_STT.md com os limiares pré-registados e a regra de decisão; não decidas.
- Não envies áudio sem confirmação do consentimento e da resposta X1; apaga o áudio local no fim; chaves só no cofre.
Não expandas escopo: o pipeline de voz em produção é KAM-036. Testes: unit do WER e do normalizador, ensaio com STT fake. PR com o template da §7.
```

---
## KAM-108 — Gate da Fase 0: demonstração do esqueleto andante

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-039, KAM-055, KAM-046, KAM-041, KAM-100, KAM-101, KAM-102 |
| Bloqueia | KAM-109 |
| Responsável sugerido | Arquitecto de Plataforma (com Responsável de Segurança e de Produto) |
| Documentos de referência | `../docs/tecnica/00_Arquitectura_Solucao.md` (§13.1 K1, §13.2 Fase 0), `14` (§3A Regras 1B, 5), `specs/00_KAMBA_Carta.md` (§4.2, §5), `specs/01_Engineering_Standards_e_Handoff.md` (§3, §4), ADR-009, ADR-012, ADR-013 |

### Contexto
O gate da Fase 0 (`../docs/tecnica/00` §13.2) exige que **uma conversa real crie um pedido, receba confirmação (`payment.manual_confirmed` ou `payment.confirmed`) e que esse evento seja consumido pela vertical Serviços (lembrete ou agenda), sem excepções no core**. Prova a regra de dois (ADR-012: ≥ 70% reaproveitado entre verticais) e o nível de maturidade K1 (esqueleto andante). A fundação tem tecto de 6 semanas (`14` §3A); na semana 6 decide-se H3 e H4 (Regra 5). Dependências efectivas que o backlog mestre não declara: KAM-100, KAM-101, KAM-102 e KAM-041 (estado das decisões externas), KAM-075/076/080 (infraestrutura) e KAM-032 (validador de citação); o gate verifica-as como evidência.

### Objectivo
Decidir, por checklist objectiva e demonstração repetível feita por quem não escreveu o código, se a Fase 0 está verde e a Fase 1 pode arrancar, com o estado das decisões externas à semana 6.

### Critérios de Aceitação
- [ ] **G0-1 Esqueleto andante:** num ambiente com a Meta real (telemóvel → número de teste ou de coexistência, nunca simulador), o cenário *scriptado* cria um pedido (Vendedor), emite referência, recebe `payment.manual_confirmed` (ou `payment.confirmed` no sandbox), passa a `paga` e a vertical Serviços cria o lembrete/agenda; 3 execuções consecutivas verdes por uma pessoa que não escreveu o código; traço por identificadores (mensagem → pedido → evento de pagamento → consumo) sem conteúdo nem telefone.
- [ ] **G0-2 Regra de dois:** a métrica de KAM-039 mostra reaproveitamento ≥ 70% e 0 excepções no core (teste de contrato verde; nenhum ramo `if vertical` no core, verificado por pesquisa estática).
- [ ] **G0-3 Invariantes de domínio:** duplo toque e callback duplicado → 0 pedidos e 0 efeitos duplicados; suite de isolamento → 0 fugas entre tenants e contactos; 0 caminhos que marquem `paga` sem evento autenticado ou `ManualProvider` auditado e limitado; 0 números divergentes das tools no conjunto adversarial mínimo (validador de citação, KAM-032).
- [ ] **G0-4 Gates de CI:** gates 1–13 de `01_Engineering_Standards_e_Handoff.md` §4 verdes no ramo principal (os que existem na Fase 0); nenhum gate em *skip* sem ADR; *scan* de segredos limpo; nenhum dado real em nenhum ambiente.
- [ ] **G0-5 Infraestrutura:** KAM-075, KAM-076 e KAM-080 concluídos; Compose reduzido a correr em *staging*; sonda externa activa; `prod` em `kamba_data_class=synthetic`.
- [ ] **G0-6 Tempo:** duração real da Fase 0 registada (início → demonstração) contra o tecto de 6 semanas; se excedido, causa e corte de **profundidade** (nunca de costuras) registados.
- [ ] **G0-7 Decisões externas à semana 6 (Regra 5 e Carta §4.2):** estado de H3 (KAM-100), H4 (KAM-101, KAM-102), D3 (KAM-041), D4 (KAM-103), D5, D1 e parecer P0 (KAM-104/105), cada um `confirmada`, `inconclusiva` com plano, ou `refutada` com pivô decidido; se H3 ou H4 falharam, a decisão de mudar de canal está assinada antes de arrancar o KAM-109.
- [ ] **G0-8 Resultado e registo:** VERDE (G0-1 a G0-7 passam), AMARELO (G0-1 e G0-2 passam; restantes com item datado ≤ 2 semanas e sem trabalho da Fase 1 que dependa deles) ou VERMELHO (G0-1 ou G0-2 falham: não arranca trabalho de funcionalidade da Fase 1 e corrige-se a abstracção antes de haver terceira vertical); K1 declarado ou negado; Registo de Hipóteses e registo de decisões actualizados; assinatura dos três papéis.

### Verificação dos Critérios de Aceitação

**Oito critérios e cinco linhas de DoD; nenhuma marcada.** E o zero é o resultado
certo, não um ticket mal feito: **o primeiro critério é uma demonstração com a
Meta real, conduzida três vezes por quem não escreveu o código, e o oitavo é um
veredicto com três assinaturas**. Os «Detalhes Técnicos» deste bloco dizem-no por
extenso — «a demonstração e o veredicto são humanos» —, e é essa a fronteira que
esta entrega respeita. O que estava ao alcance está feito, é verificável, e
**sub-condições** dentro de seis dos oito critérios ficam satisfeitas com
evidência nomeada; nenhum critério G0-n fecha, porque a cada um falta a parte
humana ou uma medição que só a demonstração dá.

Entregue: [`../docs/tecnica/evidencia/validacao/Gate_Fase0.md`](../docs/tecnica/evidencia/validacao/Gate_Fase0.md)
(a checklist, linha a linha, com estado, evidência ligada ou credor, e data),
[`Gate_Fase0_Decisao.md`](../docs/tecnica/evidencia/validacao/Gate_Fase0_Decisao.md)
(o modelo da decisão, **por preencher**),
[`Gate_Fase0_Demonstracao.md`](../docs/tecnica/evidencia/validacao/Gate_Fase0_Demonstracao.md)
(o guião, o cenário *scriptado*, as consultas e as folhas das três execuções e do
ensaio geral, as duas vazias) e o pacote
[`../tools/gate_fase0/`](../tools/gate_fase0/README.md) — cenário como dados,
traço por identificadores, consultas de leitura e recolha —, com **104 ensaios
verdes** e cobertura de 98% no pacote (`traco.py` a 100%). **Ponta de medição:
`fe40048`** (`publico/main` a 2026-11-06).

| # | Critério | Estado | Evidência nomeada ou credor |
|---|---|---|---|
| G0-1 | Esqueleto andante, 3 execuções por quem não escreveu o código, traço por identificadores | **não satisfeito, e com um achado medido** | **O instrumento e o cenário estão entregues e medidos:** o cenário *scriptado* em oito passos, **gerado** de `../tools/gate_fase0/cenario.py` com ensaio a exigir que cada elo que o traço procura tenha um passo que o produz; e o traço com **três barreiras** (lista fechada, forma do valor, guarda da saída) provado por **controlo negativo** — alimentado com um *log* que leva conteúdo e um telefone de forma real, a saída não leva nenhum dos dois, e os detectores correm **primeiro sobre a entrada** como canário, sem o qual um detector que devolvesse zero passava tudo. **A demonstração não se fez** (Meta real, telemóvel, nunca simulador: passo P0) e o KAM-055 — que entrega os dois eventos de pagamento e a transição — **está aberto** nesta ponta. **E uma linha fica `não` por medição e não por falta de demonstração:** a acção do consumo na vertical Serviços **não está escrita** — os dois pares estão em `ACCOES_POR_LIGAR` (`../services/agr/src/kamba_agr/eventos/handlers.py:221`), o desfecho é `sem_accao`, e o contrato publicado dos dois eventos tem `additionalProperties: false` com quatro propriedades, **sem `booking_id`**. Os dois credores nomeados no código (**KAM-047** e **KAM-007**) já fundiram, pelo que a linha não tem credor vivo. Devolvido no §9.2 do `Gate_Fase0.md`. Credores: **fundador** e **KAM-055** |
| G0-2 | Regra de dois: reaproveitamento ≥ 70% e 0 excepções no core | **parcial — as duas metades medidas, e a terceira por medir** | **Medido em `fe40048`, com o comando e o número:** `python -m reuse_metric medir` → **88,30%** (específico 1705, partilhado 12 869, total 14 574 linhas com código), saída 0, contra o limiar lido de `ci/regra-de-dois.yaml` (`caminho.limiar: 70`) e não escrito à mão; e `python -m reuse_metric nucleo` → «110 ficheiros varridos; **fluxo 0**», saída 0, que é a pesquisa estática que o critério pede. **Teste de contrato verde:** *gate* 7 na execução [42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021). **O que falta é o número da árvore em que o esqueleto andou:** o KAM-055 não está nesta ponta, pelo que as duas metades **re-medem-se** depois de ele fundir — e `python -m gate_fase0 reuso` recusa um artefacto de árvore suja ou de outra ponta, para que a re-medição não possa ser confundida com esta. Credor: **KAM-055** |
| G0-3 | Invariantes de domínio: duplo toque, callback duplicado, isolamento, `paga` sem evento, validador de citação | **parcial — 2 de 6 sub-condições** | **Satisfeitas e medidas:** o **isolamento** (*gate* 6 verde na execução acima, que corre o X-11, o passo a seco do KAM-066, a camada SQL X-03/X-04/X-05 e os casos cruzados de `../db/tests_isolamento/test_casos_cruzados.py`), e **0 caminhos que marquem `paga` sem evento autenticado** (`test_nenhum_codigo_do_AGR_marca_a_encomenda_paga`, com a mutação `aplica_transicao=True` apanhada) — **com o limite do KAM-039 herdado e escrito**: a metade «pelo efeito» assere `desfecho == "aplicado"`, que é verdade com ou sem transição aplicada, pelo que medir «nenhuma transição foi aplicada» exige a base, e isso é o *gate* 8. **As outras quatro têm instrumento nomeado e falta-lhes a execução:** o critério é sobre o **duplo toque e o callback repetido da demonstração**, no telemóvel, e não sobre a suite que já corre no *gate* 4; o limite do `ManualProvider` precisa de estar **assinado** (L6); e os 267 casos do conjunto adversarial do KAM-032 precisam de correr **sobre as respostas da demonstração**. Credores: **a demonstração** e o **fundador** (assinar o limite) |
| G0-4 | Gates 1–13 do §4 verdes no ramo principal; nenhum em *skip* sem ADR; *scan* limpo; nenhum dado real | **parcial — 4 de 6 sub-condições, e as duas abertas não são deste ticket** | **Medido com instrumento** (`python -m gate_fase0 ci`), sobre a execução [42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021) em `fe40048`: **11 verdes, 1 vermelho e 3 sem *job***. **A distinção que o parêntesis do critério obriga a fazer, e que um painel não faz:** um gate do §4 **sem *job*** não é verde nem vermelho — contá-lo como verde dá cobertura que não existe, e como vermelho trava um PR por um gate que ninguém escreveu. O **gate 5** está vermelho **por desenho** até o **KAM-003** o ligar (`../tools/ci_gate_reservado.py` escreve a razão), corre com `continue-on-error`, não está nos `needs` do agregador, e **não é um *skip***: é uma reserva declarada com o ticket no nome. **Nenhum gate em *skip* sem ADR: satisfeito** — `ci/waivers.yaml` tem `waivers: []`, e é o único mecanismo de excepção do *pipeline*. ***Scan* de segredos limpo: satisfeito** — *gate* 9 verde, com as **duas** passagens que o KAM-131 trouxe. **Nenhum dado real: satisfeito**, e é um zero de conjunto vazio — os três ambientes em `dados.classe: synthetic`, com a força da barreira escrita e **menor do que parece** (verifica a forma das referências, não a existência da decisão). Abertos: os gates **10, 12 e 13**, que não existem nesta ponta e são dos tickets que os criam |
| G0-5 | KAM-075, KAM-076 e KAM-080 concluídos; Compose em *staging*; sonda externa; `prod` em `synthetic` | **não satisfeito, com uma divergência de critério registada** | **Medido ticket a ticket, pela secção de verificação de cada um, e os três estão fundidos e nenhum concluído:** KAM-075 com **4 de 7** critérios, KAM-076 com **3 de 8**, KAM-080 com **3** caixas marcadas de doze — e a maioria das abertas depende da **D1**, da **D6**, da **D12** e da licença **AGPL-3.0**, que são do fundador. **«Compose reduzido a correr em *staging*» tem duas metades e só uma existe:** o conjunto está definido e verificado (`compose_prod lint` a 0 achados, canário a morder em 45 de 45), e **não corre em *staging* porque não há *host* de *staging*** — o que se mediu foi uma pilha local, e uma pilha local não é *staging*. **`prod` em `synthetic`: satisfeito.** **E a «sonda externa activa» é divergência medida e devolvida**, com as duas citações lado a lado no §9.1 do `Gate_Fase0.md`: o `../docs/observabilidade.md` §1 diz «Sonda externa — **Não existe. Não há produção**», e é o ticket que o próprio critério manda dar por concluído a dizê-lo. **Alterar o critério de um gate não é acto de quem o executa.** Credor: **fundador** |
| G0-6 | Duração real da Fase 0 contra o tecto de 6 semanas | **não satisfeito, e a razão é uma medição** | **Nenhuma fonte do conjunto fixa a data de início da Fase 0.** Procurou-se na Carta, no `INDICE.md` e no `../docs/tecnica/00`; o §13.2 dá o tecto e não dá o dia. As duas datas mais próximas **não são** o início e não se usam como se fossem: a decisão do fundador do ADR-020 é de 2026-10-09, e o primeiro *commit* da `publico/main` é de 2026-10-15, que é a criação do espelho público. Sem 6.1 não se calcula 6.3, e escrever uma duração a partir de uma data inventada era o defeito que esta casa chama «feito dito sem *output* colado». A regra do corte — **profundidade, nunca costuras** (`14` §3A), com o ADR-020 regra 5 a nomear o que se corta primeiro — fica escrita. Credor: **fundador** (fixar a data é decisão de programa) |
| G0-7 | Estado de H3, H4, D3, D4, D5, D1 e parecer P0, cada um com os três estados do critério | **parcial — as sete linhas medidas e nenhuma `confirmada`** | **As sete estão `inconclusiva`, com plano, e as sete estão medidas** — não estimadas: cada linha transcreve o estado que a secção de verificação do seu ticket declara, com o ponteiro para o ficheiro e a secção. **É a secção que mais convidava a inventar estado, e a regra que a fecha é mecânica**: o manifesto `../tools/gate_fase0/decisoes.yaml` é lido por `python -m gate_fase0 decisoes`, que verifica três invariantes — cada ponteiro existe na árvore, **nenhuma linha diz `confirmada` com a evidência vazia**, e nenhuma linha fica sem credor —, com canário por cada uma. **«O ticket fundiu» não é «a decisão está tomada»:** os sete tickets que alimentam estas linhas estão fundidos, e o que as mantém abertas são actos do fundador — três donos de número, quinze perguntas por enviar, zero submissões, zero cotações, zero propostas de honorários, duas assinaturas e uma ratificação. **A segunda metade do critério não se activa**, e a razão é precisa: `inconclusiva` **não é** `refutada`, e as duas linhas têm **amostra zero** — tratar ausência de dados como falha dispararia uma decisão de mudar de canal sobre um dado que ninguém mediu. **E uma célula fica NÃO VERIFICADO por decisão escrita:** a conta-mestre da ProxyPay/AppyPay tem duas leituras que a fonte não distingue, pelo que um «sim» não desambiguado não é um «sim» (§7.2). Credores: **fundador**, **Responsável de Produto**, **Arquitecto de Plataforma**, **Responsável de Segurança** e **advogado** |
| G0-8 | VERDE / AMARELO / VERMELHO; K1; registos actualizados; três assinaturas | **não satisfeito, por desenho** | O [`Gate_Fase0_Decisao.md`](../docs/tecnica/evidencia/validacao/Gate_Fase0_Decisao.md) nasce **vazio**, e entrega a **forma** da decisão: a regra de veredicto **transcrita** do próprio critério (transcrita e não resumida, porque um resumo de uma regra de veredicto é uma regra diferente), a tabela de itens abertos onde um item **sem data** não sustenta um AMARELO, os três NÃO VERIFICADOS que a DoD nomeia (**D1, D4, D5**) com critério de saída, o K1, o destino do KAM-109 e os três blocos de assinatura. **Tinha-se o material para propor um veredicto** — o G0-1 com uma linha `não` medida, o G0-2 com as duas metades acima do limiar — **e não se escreveu**: era tomar a decisão com outro nome. Credores: **fundador**, **Arquitecto de Plataforma**, **Responsável de Segurança**, **Responsável de Produto** |

**Definition of Done — 0 de 5:**

| # | Caixa | Estado | Evidência ou credor |
|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | 0 de 8. Marcá-la contradizia as oito linhas acima |
| 2 | Resultado do gate e itens abertos com dono e data; assinaturas dos três papéis | **não satisfeito** | Os campos existem e nascem vazios (`Gate_Fase0_Decisao.md` §1, §2 e §5). Credor: **fundador**, com os três papéis |
| 3 | Sem dados reais, segredos nem conteúdo de conversa nas evidências | **parcial, e a metade medida é a que este ticket podia medir** | **Verificado por forma de valor e não por leitura:** nenhum dos três ficheiros novos leva telefone, nome de pessoa ou conteúdo de conversa, e o traço **recusa-se a emitir** qualquer dos dois (controlo negativo, com canário sobre a entrada). *Gate* 9 verde na execução acima. **E o varrimento do *gate* 7 não muda com este PR:** medido antes e depois, **35 ficheiros e 124 ocorrências**, idênticas ficheiro a ficheiro e iguais ao par fixado de `../tools/meta-sim/tests/inventario.test.ts`, pelo que **nenhum ficheiro deste ticket leva entrada no `INVENTARIO`** — o número de forma real do controlo negativo monta-se em execução e não aparece como literal. **A metade que falta é das evidências que a demonstração vai produzir** (o traço arquivado, a gravação do ecrã), e essas não existem. Credor: **a demonstração** |
| 4 | Itens NÃO VERIFICADOS que condicionam a Fase 1 (D1, D4, D5) listados com critério de saída | **parcial** | **Os três estão listados com critério de saída, dono e a data a preencher** (`Gate_Fase0_Decisao.md` §2.1), e o estado de cada um está medido no `Gate_Fase0.md` §7. O que falta é a **data-limite**, que é decisão de programa. Credor: **fundador** |
| 5 | KAM-109 desbloqueado ou replaneado por escrito | **não satisfeito** | O campo existe e nasce vazio (`Gate_Fase0_Decisao.md` §4), com a condição anterior escrita: se H3 ou H4 fossem `refutada`, a decisão de canal teria de estar assinada **antes**. Credor: **fundador** |

**O que não entra neste ticket, e fica devolvido em vez de feito.** Escrever a
acção do consumo na vertical Serviços, e decidir por onde vem o `booking_id` —
emendar o contrato de evento ou o consumidor resolver a marcação por consulta —
são **ticket novo**: o bloco diz «corrigir falhas encontradas é ticket novo», e
alterar um contrato de evento publicado é canon de nível 4 e 8 e muda a
compatibilidade que o *gate* 7 verifica. Alterar o critério G0-5 da sonda externa
é **regra de um gate**, logo do fundador. Ligar qualquer destes instrumentos a um
*job* de CI acrescenta um contexto exigido ao *ruleset* da `main`, que é
alteração de regra de bloqueio — o precedente está escrito no KAM-039 e no
KAM-180, e este ticket entrega a medição e não a ligação. E os gates **10, 12 e
13** do §4 não existem nesta ponta: são dos tickets que os criam.

### Detalhes Técnicos
- **Componentes:** GWY, CHR, AGR, TLS, COM, PAY, EVT, HND, OBS (verificados, não implementados aqui). O pagamento por `ManualProvider` é aceite na Fase 0 (`../docs/tecnica/00` §13.2); a variante do facilitador depende de KAM-056 e de D4.
- Evidência: `../docs/tecnica/evidencia/validacao/Gate_Fase0.md` com a checklist, ligações às execuções de CI e aos relatórios, gravação do ecrã da demonstração e o traço de identificadores. Decisão: `Gate_Fase0_Decisao.md` com resultado, itens abertos, dono e data.
- O Claude Code prepara: checklist em Markdown com campos de estado, o guião da demonstração e o cenário *scriptado*, o *script* que junta identificadores entre logs (sem conteúdo), o *script* que reúne as ligações de CI e métricas e o modelo da decisão. A demonstração e o veredicto são humanos.

### Testes Requeridos
- Ensaio geral da demonstração (3 execuções) antes do gate; teste do *script* de traço com logs sintéticos (não deve emitir conteúdo ou telefone).
- Verificação cruzada, por pessoa distinta do autor, de que cada linha G0-n tem evidência ligada e não declarada.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Resultado do gate e itens abertos registados com dono e data; assinaturas do Arquitecto, de Segurança e de Produto.
- [ ] Sem dados reais, segredos nem conteúdo de conversa nas evidências.
- [ ] Itens NÃO VERIFICADOS que ainda condicionam a Fase 1 (D1, D4, D5) listados com critério de saída.
- [ ] KAM-109 desbloqueado ou replaneado por escrito.

### Handoff para Claude Code
```text
És o executor do ticket KAM-108 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-108), docs/tecnica/00_Arquitectura_Solucao.md (§13.1, §13.2),
docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§3A) e specs/00_KAMBA_Carta.md (§4.2, §5).
Objectivo: preparar a checklist, o guião da demonstração e o pacote de evidências do gate da Fase 0; o veredicto é humano.
- Cria docs/tecnica/evidencia/validacao/Gate_Fase0.md com as linhas G0-1..G0-8, estado por linha e ligações às evidências.
- Escreve o cenário scriptado do esqueleto andante e o script de traço por identificadores (mensagem -> pedido -> evento -> consumo), sem conteúdo nem telefone.
- Escreve o script que recolhe métricas de reaproveitamento (KAM-039), resultados de CI e estado das decisões externas.
- Não declares nenhuma linha como verde sem evidência ligada; deixa a decisão por preencher.
Não expandas escopo: corrigir falhas encontradas é ticket novo. PR com o template da §7.
```

---

## KAM-109 — Piloto concierge e medição de H1, H6, H8 e H9

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-094, KAM-108, KAM-069, KAM-074, KAM-022, KAM-018, KAM-112, KAM-114, KAM-113 |
| Bloqueia | KAM-110 |
| Responsável sugerido | Responsável de Produto (com Ops/Trust & Safety) |
| Documentos de referência | `14` (§2 H1, H6, H8, H9, §3 ponto 3, §3A Regra 4, §6), `../docs/tecnica/00_Arquitectura_Solucao.md` (§9, §13.2), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§14, §17), `../docs/tecnica/10_Onboarding_Governanca.md` (§16), `specs/00_KAMBA_Carta.md` (§5), ADR-017, ADR-019 |

### Contexto
O piloto mede 10 PMEs com o Fluxo A em produção. `14` tem uma inconsistência interna: H1 diz «pilotos concierge a preço real» e a Regra 4 diz «piloto gratuito de 30 dias com meta de ≥ 5 a converter a pago». Este ticket adopta a **Regra 4** (30 dias gratuitos e depois pagamento ao preço real). «Concierge» é aqui apoio humano apertado (T2), cobrança manual com `ManualProvider` auditado e correcção de catálogo; o modo «a IA rascunha e o humano aprova antes de enviar» de `14` §3 ponto 3 **não** é construído por nenhum ticket (KAM-018 trata os modos bot/dono/humano) e, se o fundador o quiser, é ticket novo. O cronograma tem um risco: a Fase 1 vai da semana 7 à 12, e o dia 60 de H9 só é alcançável para PMEs activadas até cerca da semana 4. Dados reais exigem o gate de go-live (KAM-105) cumprido e DPA aceite (KAM-090).

### Objectivo
Operar o piloto com 10 PMEs e medir H1, H6, H8 e H9 com um protocolo pré-registado e dados exportados e congelados, para alimentar o KAM-110.

### Critérios de Aceitação
- [ ] **Protocolo pré-registado e assinado antes da 1.ª activação** (`../docs/tecnica/evidencia/validacao/Piloto_Protocolo.md`): coorte, preço real da mensalidade, definição de «activa» (*proposta*: ≥ 1 acção do dono por semana **e** ≥ 5 conversas nos últimos 14 dias), regra de contagem do custo de H6, protocolo de auditoria de H8, regras de substituição e de paragem. Alterações só por emenda.
- [ ] **Pré-condições:** `GoLive_Gate.md` (KAM-105) todo verde; 0 PMEs activadas com dados reais antes disso; DPA aceite em 100% das activadas; 10 PMEs da lista de KAM-106 onboardadas por *self-service*; reporta-se a % de activações sem intervenção humana (Carta §5 exige ≥ 80%).
- [ ] **H1 (limiar ≥ 5 de 10 pagam após 30 dias):** por PME, data de activação, uso na semana 2 (quem não usa sai e é substituído, Regra 4), conversão ao dia 30 e prova de pagamento ao preço real (evento de pagamento auditado ou comprovativo bancário conciliado); resultado `confirmada` ou `refutada`; se `refutada`, pivô de `14` §6 (voltar às entrevistas, mudar segmento ou produto).
- [ ] **H6 (limiar ≤ 15% da mensalidade):** medido em ≥ 500 conversas reais com o `h6-export` de KAM-081; regra de contagem fixada antes: por omissão a de `14` (LLM + voz + Meta), reportando também LLM + STT isolado; resultado com p50, p90 e total por PME/mês. Se falhar, tabela de cenários (subir preço, reduzir modelo ou voz, limitar volume por plano) com o custo de cada um.
- [ ] **H8 (limiar ≥ 60% de catálogos correctos):** auditoria à 4.ª semana de cada PME com amostra de 20 produtos (ou todos se < 20) sorteada com semente registada; item correcto se preço e disponibilidade coincidem com a verdade apurada com o dono ou em visita; catálogo correcto se ≥ 90% dos itens (*proposta*); H8 confirmada se ≥ 6 de 10; regista-se também a razão actualizações/mudanças reais declaradas. `14` §6 não prevê pivô para H8: se `refutada`, o gate propõe uma acção de produto (p. ex. lembretes de actualização e painel mínimo, KAM-099) e regista-a.
- [ ] **H9 (limiar ≥ 70% activas ao dia 60):** calculada apenas sobre PMEs com 60 dias de exposição à data do gate; com < 8 PMEs nessa condição, H9 fica `inconclusiva` com data de seguimento (o indicador de dia 30 é reportado à parte, sem substituir o de dia 60). `14` §6 não prevê pivô para H9: se `refutada`, aplica-se a regra de paragem total e o gate decide o pivô sobre retenção.
- [ ] Relatório semanal com modelo fixo (activas, conversas, handoffs, pagamentos, custo, incidentes, horas de operador por PME) durante as semanas do piloto; exportação final dos dados congelada com *hash* e arquivada.
- [ ] Registo de Hipóteses actualizado para H1, H6, H8, H9 (e insumos de H7 vindos dos casos T2) com fonte, decisão e data.

### Detalhes Técnicos
- **Componentes:** OBS e DAT (consultas sobre `onboarding_case`, `llm_call_log`, `payment_events`, eventos de actividade), TEN. A mensalidade de referência é de 30–60 mil Kz (hipótese); 15% corresponde a 4,5–9 mil Kz (≈ $4,9–9,9 a 913 Kz/USD). Aviso: com 300 conversas por mês, a Meta (≈ $7,5) mais LLM e STT ($1,9–6,4) pode ultrapassar esse tecto no extremo baixo da mensalidade (ESTIMATIVA do doc 09 §14.3); por isso a regra de contagem se fixa antes.
- Casos T2 resolvidos alimentam o golden pelas **três origens do KAM-040** — `sintetico`, `t2_anonimizado` (a reescrita sintética sem dados pessoais de `../docs/tecnica/10` §11.2) e `real_consentido` — e **nenhum caso `real_consentido` entra sem registo de consentimento**. Esta linha dizia «só por reescrita sintética» e contradizia o critério do KAM-040: a divergência foi medida no KAM-104 (sete afirmações a invocar o ADR-018, quatro com uma origem e três com as outras duas) e **o fundador decidiu a 2026-10-30 que valem as três origens**. Conversas reais continuam a **não** treinar nem melhorar modelos (Termos da Meta, a confirmar em KAM-101; o bastante do consentimento da PME é a pergunta F-03 do KAM-104).
- Humano: operador (1 pessoa cobre 10 PMEs), visitas de auditoria, reuniões do dia 30. O Claude Code prepara: protocolo, consultas SQL e *scripts* de H1/H6/H8/H9 sobre exportações, gerador do relatório semanal, folha de auditoria, sorteio de amostra com semente, registo de horas do operador.

### Testes Requeridos
- Testes unitários dos *scripts* de cálculo com *fixtures* de coorte (fronteiras: 4 e 5 de 10; 14,9% e 15,1%; 5 e 6 de 10; 7 de 10 em H9) e do sorteio reprodutível.
- Ensaio do relatório semanal sobre dados sintéticos; verificação de que os relatórios não contêm conteúdo de conversas nem telefones.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Protocolo assinado antes da 1.ª activação; resultados H1, H6, H8, H9 com fonte e decisão.
- [ ] Dados pessoais só no sistema de produção; relatórios e exportações sem PII; sem segredos.
- [ ] Exportação congelada e arquivada com *hash*; custo do piloto registado.
- [ ] Desvios do protocolo e PMEs substituídas registados com motivo.

### Handoff para Claude Code
```text
És o executor do ticket KAM-109 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-109), docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§2, §3A Regra 4, §6),
docs/tecnica/09_Topologia_Operacao_Escala.md (§14) e o h6-export de KAM-081.
Objectivo: preparar protocolo, consultas, scripts de medição e relatório semanal do piloto; a operação com as PMEs e as decisões são humanas.
- Escreve Piloto_Protocolo.md com as definições e limiares pré-registados (H1 >=5/10; H6 <=15%; H8 >=60%; H9 >=70% ao dia 60) e a regra de H9 inconclusiva.
- Escreve as consultas e os scripts de H1, H6, H8, H9 sobre exportações, com testes de fronteira, e o sorteio de amostra com semente.
- Gera o relatório semanal e a folha de auditoria de catálogo; nunca inclui conteúdo de conversas, telefones ou contact_id.
- Não declares nenhuma hipótese confirmada sem dados exportados e congelados.
Não expandas escopo: o gate é KAM-110. Testes: unit com fixtures de coorte e ensaio com dados sintéticos. PR com o template da §7.
```

---

## KAM-110 — Gate do Piloto: decisão continuar, pivô ou parar

| Campo | Valor |
|---|---|
| Epic | EPIC-10 — Spikes, Validação e Gates |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-109, KAM-074, KAM-085, KAM-040, KAM-082, KAM-083, KAM-105, KAM-069, KAM-103, KAM-106, KAM-113 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Produto (decisão do fundador, com Arquitecto de Plataforma e Responsável de Segurança) |
| Documentos de referência | `14` (§2 regra de decisão, §3A Regra 5, §5, §6), `../docs/tecnica/00_Arquitectura_Solucao.md` (§13.2 Fase 1), `specs/00_KAMBA_Carta.md` (§5, §6), `specs/INDICE.md` (§1, §6), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§14.4) |

### Contexto
O gate da Fase 1 (`../docs/tecnica/00` §13.2) pede ≥ 5 PMEs pagantes a 30 dias (H1) e ≥ 70% activas ao dia 60 (H9); a Definition-of-Done do Piloto da Carta §5 junta a isso fiabilidade, segurança e conformidade. A regra de decisão de `14` §2 é que, se H1 ou H5 falharem, a tese muda antes de se escrever mais código; o §6 fixa pivôs e a paragem total («ao fim de 12 semanas sem ≥ 3 pagantes recorrentes e sem canal comercial repetível»). Os epics da Fase 2 só se escrevem se este gate for verde (`INDICE.md` §1 e §6). O backlog mestre declara só KAM-109 como dependência, mas o gate exige evidência de KAM-040, KAM-074, KAM-082, KAM-083, KAM-085, KAM-103, KAM-105, KAM-106 e KAM-107, que aqui se verifica como pré-condição.

### Objectivo
Registar, com a evidência das hipóteses e da Carta §5, a decisão de **continuar**, **pivô** (qual) ou **parar**, com dono, data e plano das duas semanas seguintes.

### Critérios de Aceitação
- [ ] **A. Hipóteses:** `Gate_Piloto.md` tem H1–H9 com limiar, resultado, estado (`confirmada`, `refutada`, `inconclusiva`) e ligação ao ficheiro de evidência: H1, H6, H8, H9 de KAM-109; H2 de KAM-106; H3 de KAM-100; H4 de KAM-101/102; H5 de KAM-103; H7 de KAM-040 (golden ≥ 85% sem *handoff* errado). 9 de 9 linhas completas; uma hipótese sem dados é `inconclusiva`, nunca `confirmada`.
- [ ] **B. Definition-of-Done do Piloto (Carta §5), item a item** com ligação à evidência: Fluxo A em produção com ≥ 10 PMEs activas e ≥ 80% de activações sem intervenção humana; esqueleto andante (KAM-108); 0 fugas, 0 pedidos duplicados, 0 números divergentes; 100% das confirmações de pagamento por evento autenticado; gates de CI verdes e revisão de segurança independente (KAM-074); procedimento APD concluído para todos os destinos de produção, DPA em 100% dos activos, parecer sobre D8; resposta escrita da Meta ou decisão registada de operar sem ela, e Tech Provider activo; restauro testado e RTO/RPO medidos (KAM-085), runbooks e SLOs em vigor (KAM-082/083), com o relatório de SLO de 30 dias.
- [ ] **C. Matriz de decisão** aplicada com a regra de `14` §6: H1 < 5 → voltar às entrevistas (segmento ou produto); H3/H4 falhadas → mudar de canal; H5 falhada → manter camadas 1–2; H2 falhada → reposicionar para atendimento e disponibilidade; H7, H8 e H9 falhadas não têm linha em `14` §6 e o gate decide e regista a acção (p. ex. golden e handoff, lembretes de catálogo, retenção); H6 falhada → subir preço, reduzir modelo ou voz, ou limitar volume por plano; sem canal de acesso → resolver distribuição. **Paragem total** se, ao fim de 12 semanas, < 3 pagantes recorrentes e nenhum canal comercial repetível.
- [ ] **D. Economia real:** custo por PME medido (KAM-081) contra as estimativas do doc 09 §14.4; ponto de equilíbrio actualizado (hipótese de 8 a 28 PMEs); meses de pista restantes e o ponto em que se pára ou se muda (a pergunta ao fundador de `14` §5) preenchidos com os números reais do fundador, nunca estimados pelo executor.
- [ ] **E. Decisão assinada** (`Gate_Piloto_Decisao.md`): `CONTINUAR`, `PIVÔ` (qual linha de `14` §6, com plano de 2 semanas e métrica de sucesso) ou `PARAR` (plano de encerramento com *off-boarding* das PMEs do piloto e purga de dados); dono, data, assinaturas do Arquitecto, de Segurança e de Produto.
- [ ] **F. Consequências no backlog:** se `CONTINUAR`, a lista de epics da Fase 2 a escrever e os gatilhos de `INDICE.md` §6 (D2, D7, D8, D11); se `PIVÔ`, os tickets a congelar e a criar; se `PARAR`, o encerramento. Itens NÃO VERIFICADOS que ficam por fechar listados com dono.

### Detalhes Técnicos
- **Componentes:** nenhum de software. Artefactos: `../docs/tecnica/evidencia/validacao/Gate_Piloto.md` (checklist e evidências) e `Gate_Piloto_Decisao.md`.
- Regras de estado: `confirmada` só com dados que cumpram o limiar de `14` §2 e o protocolo pré-registado; `inconclusiva` quando a amostra ou o calendário não chega (p. ex. H9 sem 8 PMEs com 60 dias); uma hipótese inconclusiva não permite `CONTINUAR` sem um plano datado para a fechar.
- Os limiares são propostas do fundador; o gate não os altera. Mudá-los depois dos dados é re-litígio (Carta §6).
- O Claude Code prepara o gerador do pacote de evidência (lê o Registo de Hipóteses e as exportações do KAM-109 e preenche a checklist), o modelo do memorando de decisão com o campo de decisão **em branco** e a tabela de consequências; não escolhe nem recomenda a decisão.

### Testes Requeridos
- Teste do gerador com um Registo de Hipóteses sintético (9 estados misturados): nenhuma linha sem dados sai `confirmada`; a matriz de `14` §6 devolve a linha correcta para cada falha simulada.
- Revisão cruzada, por pessoa distinta do autor, de que cada item da Carta §5 tem evidência ligada.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Decisão assinada com dono e data no Registo de Hipóteses e no registo de decisões da Carta.
- [ ] Evidências sem PII nem segredos; números de pista fornecidos pelo fundador.
- [ ] Backlog e `INDICE.md` actualizados segundo a decisão (sem editar epics fora do que a decisão determina).
- [ ] Itens NÃO VERIFICADOS restantes listados com dono e critério de saída.

### Handoff para Claude Code
```text
És o executor do ticket KAM-110 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-10_Spikes_Validacao_Gates.md (bloco KAM-110), docs/exploracao/14-tese-minima-e-plano-de-validacao.md (§2, §5, §6),
specs/00_KAMBA_Carta.md (§5, §6) e o Registo_Hipoteses.md.
Objectivo: preparar o pacote de evidência e o memorando de decisão do gate do Piloto; a decisão é do fundador e dos três papéis.
- Gera Gate_Piloto.md com H1-H9, o estado por regra (sem dados = inconclusiva) e a verificação item a item da Carta §5, com ligações às evidências.
- Aplica a matriz de 14 §6 a cada hipótese falhada e lista as consequências no backlog; o campo «decisão» fica em branco.
- Os números de pista (meses, capital) vêm do fundador: deixa o campo por preencher; não estimes.
- Não alteres limiares nem reabras decisões FIXAS da Carta.
Não expandas escopo: escrever os epics da Fase 2 é trabalho posterior, só se a decisão for CONTINUAR. Testes: gerador com Registo sintético. PR com o template da §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Decisão | Tratamento no epic |
|---|---|---|---|
| Coexistência em números +244 (móveis e fixos); se o spike corre antes de Tech Provider | NÃO VERIFICADO | D5, ADR-001 | KAM-100: passo 0, 3 números, regra de decisão e pivô (`cloud_only`, BSP, outro canal) |
| Classificação como *AI Provider* («exclusivo critério» da Meta); agregador e Fluxo B | NÃO VERIFICADO | D2 | KAM-101: resposta escrita; sem resposta à semana 6 → risco aceite e Fluxo B diferido |
| Prazo da Business Verification e aceitação de documentos angolanos; detalhe da *Access Verification* | NÃO VERIFICADO | D5 | KAM-102 mede prazos reais; fallback BSP/MPS; regra de falha à semana 6 |
| Cartão internacional da PME para o Billing Hub (barreira de adopção) | INDÍCIO (risco de E1) | D5, D9 | KAM-106 conta PMEs com cartão; KAM-102 decide Tech Provider vs MPS |
| Preços ProxyPay; assinatura do callback OPG e da AppyPay; prazo de onboarding bancário | NÃO VERIFICADO | D4 | KAM-103: perguntas escritas e matriz; sem contrato à semana 6 → `ManualProvider` |
| Enquadramento BNA do modelo facilitador (Aviso 2/22 art. 4.º j)); comissão sobre transacção | Aguarda parecer | D8 | KAM-104 (P0 Q19, Q20); comissão desligada (ADR-017) até parecer |
| Lista de países adequados e cláusulas-tipo da APD; prazos e silêncio positivo; taxas | NÃO VERIFICADO / INDÍCIO | D1, D9 | KAM-104 e KAM-105; `GoLive_Gate.md`; sem `apd_ref` não há dados reais |
| Cotações de Luanda, serviços geridos e latência | NÃO VERIFICADO | D1, D6 | KAM-105 só aceita cotações com documento; KAM-077 mede RTT |
| Papel da KAMBÁ e quem paga os custos em USD | Não decidido | D9 | KAM-105 (provisória se faltar parecer); KAM-104 X2 |
| CDN/WAF como subprocessador; backups cifrados fora de Angola | Aguarda parecer (N1, N2) | D12, D1 | KAM-104; KAM-105 inclui no mapa de tratamentos |
| Canal operacional da KAMBÁ (suporte e prestadores) | CONDICIONAL | D10 | KAM-101 regista a decisão provisória (canal do fundador) |
| Qualidade do STT em PT-AO e de Kimbundu/Umbundu; sinal de confiança na API | NÃO VERIFICADO | ADR-005 | KAM-107 mede com falantes reais; limiares pré-registados |
| Dados reais de teste (números do spike H3, voz) e Termos da Meta sobre ML | Aguarda parecer | ADR-008, ADR-018 | KAM-100 e KAM-107: consentimento, só metadados, apagamento; KAM-104 X1 e X3 |
| Amostras pequenas (n = 30 entrevistas; 10 PMEs): conclusões direccionais | Limite do método | — | Contagens absolutas, ressalva escrita, limiares pré-registados |
| H9 ao dia 60 não alcançável para PMEs activadas depois da semana 4; piloto «gratuito» vs «a preço real» em `14` | Inconsistência do calendário | — | KAM-109 só avalia PMEs com 60 dias; H9 `inconclusiva` se < 8; Regra 4 adoptada |
| H6 pode falhar no extremo baixo da mensalidade se a Meta contar (≈ $7,5 com 300 conversas) | ESTIMATIVA | D5, D9 | KAM-109 fixa a regra de contagem antes de medir |
| Capacidade de uma equipa pequena para 7 frentes de espera externa na semana 1 | Risco de execução | — | Ordem de prioridade: H3 e H4 primeiro (`14` §2); donos distintos por ticket |
| Pista financeira (meses de capital) não fornecida | Lacuna de `14` §5 | — | KAM-110 exige os números do fundador; o executor não os estima |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: KAM-100 a KAM-110 (spikes, pedidos à Meta, bancos e jurídico, alojamento, entrevistas, voz, gates da Fase 0 e do Piloto). | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 27 referências aos anexos de evidência e aos artefactos de validação passam a `../docs/tecnica/evidencia/…`; antes não resolviam de posição nenhuma. As duas que já estavam correctas («Natureza dos tickets» e o Registo de Hipóteses do KAM-100) ficaram intactas. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: três das quatro referências a anexos de evidência da linha «Documentos relacionados» da tabela de cabeçalho passam a trazer o prefixo `../docs/tecnica/evidencia/`. Estavam citadas **sem directório nenhum** desde a emissão — pré-existentes ao KAM-128 e ao KAM-129 — e não resolviam a partir de `specs/`; eram invisíveis às buscas G1 e G2 do KAM-129, que ancoram no prefixo. Forma de citação (nome completo) inalterada; sem alteração de conteúdo técnico: o *diff* é de uma linha, 1 inserção contra 1 eliminação. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-145: os **25** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. Com eles, as **6** referências a ficheiros da biblioteca exploratória que não tinham directorio nenhum passam a ter o seu, e deixam de não resolver de posição alguma. As **quatro** instruções que mandam criar um ficheiro de validação passam a escrever **dentro** da árvore do repositório. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | KAM-128: O `Documento-fonte` do cabeçalho passa a citar o ficheiro da biblioteca exploratória pelo caminho completo, e a nota «Natureza dos tickets» deixa de descrever a árvore antiga. Duas linhas, sem alteração de conteúdo técnico. Linha acrescentada pelo **KAM-146**, que paga as onze que o KAM-128 não escreveu. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | KAM-104: o bloco ganha a secção «Verificação dos Critérios de Aceitação» com uma linha de evidência nomeada por critério, e as caixas passam a marcadas onde há evidência: **3 de 7 critérios e 3 de 5 caixas de DoD**. Três das quatro vazias são actos humanos — enviar o pacote (critério 4), pedir honorários e assinar (5), receber respostas por escrito (6) — e para cada uma fica dito, com o estado `não satisfeito`, o que havia de aproveitável e onde está. **A quarta foi a revisão adversarial que a abriu:** o critério 3 estava marcado e desmarcou-se, porque o limite de «≤ 6 páginas» é duro e a conta que o sustentava só dava 6 se o espaçamento entre parágrafos não ocupasse linha — com ele, o anexo dá cerca de 6,8 páginas; os seis itens enumerados estão todos presentes e a ausência de dados pessoais está verificada, e o que falha é só a medida. Entregues três ficheiros novos em `../docs/tecnica/evidencia/validacao/`: o pacote com as **40** perguntas e os oito campos de cada uma, o anexo de factos do caso sem dados pessoais, e o molde de selecção com o registo de respostas, que nasce vazio. Nenhuma prioridade do critério 2 foi reinventada: as quatro divergências de leitura ficam medidas e a decisão devolvida a quem escreveu o critério. A revisão adversarial devolveu **11 achados — 9 `CONFIRMADO` corrigidos, 1 `PLAUSÍVEL` aceite, 1 `MORTO` registado** — e está em [`ANALISE-43`](../docs/analises/ANALISE-43-KAM-104-pacote-parecer-juridico.md); o mais grave era de conteúdo e não de forma: o pacote dizia que o conjunto de avaliação é inteiramente sintético quando o KAM-040 especifica três origens, duas delas com material real sob registo de consentimento. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | KAM-104: a linha dos casos T2 do bloco **KAM-109** deixa de dizer que o golden se alimenta «só por reescrita sintética» e passa a nomear as **três origens do KAM-040** (`sintetico`, `t2_anonimizado`, `real_consentido`), com o registo de consentimento obrigatório para os reais. Não é emenda de prosa: era uma das **sete** afirmações sobre a origem do *golden set* que invocam o ADR-018 e não dizem o mesmo — quatro davam uma origem, três davam as outras duas —, medidas e nomeadas no KAM-104 e na [`ANALISE-43`](../docs/analises/ANALISE-43-KAM-104-pacote-parecer-juridico.md). **O fundador decidiu a 2026-10-30 que valem as três origens**, pelo que esta passou de decisão a correcção. As outras três afirmações divergentes estão fora deste epic e vão a ticket próprio. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | KAM-104: a caixa do critério 3 **fecha**, com o anexo medido em **6 páginas** por um renderizador nomeado (pandoc/latex:3.1 em contentor, `--pdf-engine=xelatex`, `-V geometry:a4paper -V geometry:margin=2.5cm -V fontsize=11pt --from=gfm`) e a contagem de páginas confirmada por três vias independentes que concordam. O fundador autorizou medir uma vez em contentor, a 2026-10-30, porque «≤ 6 páginas» sem renderizador nomeado é uma estimativa e não um critério. A primeira medição deu **7**: a secção «o que ainda não existe» passou do anexo para o §6.1 do pacote, sem perda de informação por os dois ficheiros viajarem juntos, e a segunda deu **6**. Caixas: **4 de 7 critérios e 3 de 5 de DoD**; as três que ficam vazias são actos humanos. | Equipa KAMBÁ |
| 1.8 | Novembro 2026 | KAM-105: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas passam a marcadas onde há evidência: **5 de 8 critérios e 0 de 5 caixas de DoD**. Quatro ficheiros novos em `../docs/tecnica/evidencia/validacao/`. As três caixas vazias de critério e as cinco de DoD têm a mesma causa: o ticket depende de pedir cotações, de enviar o pacote ao advogado e da decisão **D1**, que é do fundador. O mapa de tratamentos saiu de três fontes, e a terceira é código — as treze listas de saída da pilha — porque o `tenant_destinations` que o `../docs/tecnica/08` §8.6 manda usar não existe. A revisão adversarial devolveu **17 achados** e está na [`ANALISE-46`](../docs/analises/ANALISE-46-KAM-105-alojamento-e-procedimento-apd.md); o grave foi a afirmação central do mapa, correcta na conclusão e **invertida na inferência**. | Equipa KAMBÁ |
| 1.9 | Novembro 2026 | KAM-101: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas passam a marcadas onde há evidência: **4 de 7 critérios e 2 de 5 caixas de DoD**. Um ficheiro novo em `../docs/tecnica/evidencia/validacao/`: as **15** perguntas de E1 com os nove campos do critério 1, em **EN** (redigido no ticket) e **PT** (o de E1 palavra a palavra), em três grupos de prioridade e **dois** lotes de envio — **8** no lote 1 do Piloto, e no lote 2 as **6** de Fluxo B e Clusters mais a **Q15** de custo, que vai a BSPs e é consumida pelo KAM-102. A folha de seguimento e o registo de respostas **nascem vazios**: 15 linhas em `por enviar`, 0 enviadas, 0 respondidas, porque enviar em nome da empresa é do fundador e não do executor. As cinco caixas abertas têm todas a mesma causa — enviar, aprovar e receber são actos humanos — e ficam devolvidas com credor nomeado. **A releitura das quatro fontes primárias em inglês rendeu quatro desvios vivos e um morto**, e o que importa é o primeiro: a restrição de treino de ML da cláusula **4.7** dos Termos está **ligada ao caso de se contratar um *AI Provider* como *Solution Provider*** e tem **excepção** para afinar um modelo de uso exclusivo próprio, onde o E1 §4 e o `../docs/tecnica/10` §11.3 a dão como proibição **geral**. O desvio fica **INDÍCIO de uma leitura** e não sobe a CONFIRMADO: é de **âmbito** que trata, e âmbito é o que uma extracção automática erra primeiro, pelo que a regra de estado do §3 do ficheiro só dá CONFIRMADO onde esta releitura **corrobora** o que o E1 já tinha lido em português. A posição de desenho que deles sai é mais conservadora do que a fonte exige, pelo que **nada se relaxa**, e corrigir a afirmação é ticket a abrir pela **L1**, com o **fundador** como credor — o §3.1.1 do ficheiro reúne o que esse ticket precisa de citar para se abrir **sem reler os Termos**, e levanta os **cinco** outros sítios que afirmam a cláusula sem a condicionante, um deles um **ADR-L em vigor** que não se corrige por iniciativa de sessão. Os outros desvios vivos: o rótulo «Updated» **não existe** em nenhuma das quatro páginas de documentação relidas, onde o E1 atribui datas a todas; o inglês diz **«incidental or ancillary»**, não «acidental ou complementar»; e o historial de países da coexistência **não se reproduz** e baixa a **INDÍCIO** nas duas direcções, sem que a conclusão mude — as duas leituras concordam em que não há lista oficial e Angola não aparece, pelo que a Q3 e o spike do KAM-100 continuam a ser a via. A ressalva do critério 5 fica escrita: `confirmada` pela via da aprovação de Tech Provider **não** fecha D2 nem levanta o diferimento do ADR-011. Os «Testes Requeridos» pedem um `validar_evidencia.py` que **não existe** na árvore: é artefacto do KAM-100, e fica nomeado como credor em vez de dado por corrido. **A revisão adversarial devolveu 14 achados — 12 `CONFIRMADO` corrigidos, 1 `MORTO` e 1 parcialmente morto — e está na** [`ANALISE-51`](../docs/analises/ANALISE-51-KAM-101-perguntas-a-meta.md); o mais valioso levou a **matar uma afirmação do próprio ficheiro**: o «desvio 2» que ele alegava contra o E1 não existe, porque o **E1 §1** já registava a data da política de preços (16 Fev 2026), CONFIRMADA e com a mesma fonte, e a página de preços confirma a data dos Termos — nasceu de ler o E1 §4 e não ler o E1 §1, e fica registado como morto no §3.5 para não se pagar outra vez. | Equipa KAMBÁ |
| 1.10 | Novembro 2026 | KAM-100: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas passam a marcadas onde há evidência: **1 de 7 critérios e 1 de 5 de DoD**. Entregue o *harness* descartável em [`../spikes/h3/`](../spikes/h3/README.md) — página mínima de ES v4 de coexistência com os três parâmetros que a fazem coexistência (`extras.featureType`, `sessionInfoVersion` e *session logging*), receptor de *webhook*, extractor, registo em JSON-lines, gerador da tabela N1–N3 e *fixtures* —, o validador [`../scripts/validar_evidencia.py`](../scripts/validar_evidencia.py), e dois ficheiros novos em `../docs/tecnica/evidencia/validacao/`: o modelo de resultado [`H3_Coexistencia_244.md`](../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md) e o [`Registo_Hipoteses.md`](../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md), com as **nove** linhas H1–H9 no esquema de doze colunas deste bloco. **Dez caixas ficam vazias e quase todas pela mesma causa, que está na letra do bloco:** «o operador humano executa o ES com cada dono; a decisão é humana». Seis dos sete critérios dependem de três donos de número com consentimento escrito. **O Passo 0 fecha com `NÃO VERIFICADO`**, que é um dos três valores que o critério admite: o requisito de ser Solution Partner ou Tech Provider é CONFIRMADO (`../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §2) e **nenhuma** das páginas registadas em E1 §2 ou §3 diz se o modo de desenvolvimento o satisfaz — pelo que o spike está bloqueado por **uma pergunta sem resposta** e não por um `Não`, e o prazo novo fica NÃO VERIFICADO em vez de inventado, porque depende de uma Business Verification cujo prazo a Meta não documenta. A elegibilidade de Angola e o *echo* da API **mantêm-se** NÃO VERIFICADOS, e as fontes secundárias que dizem «global» mantêm-se INDÍCIO: herdados e não promovidos. **As duas correcções que importam, e que são o que este ticket tem de ter certo:** (1) a assinatura `X-Hub-Signature-256` valida sobre o corpo **bruto**, e o ensaio que o prova usa **cinco pares de bytes diferentes com a mesma árvore** mais a implementação **errada** escrita ao lado a aceitá-los todos — sem esse par de metades, um ensaio que assine e verifique o mesmo objecto fica verde com o *fail-open* lá dentro, porque re-serializar faz uma assinatura autenticar uma **família** de corpos em vez do corpo que chegou; (2) o ensaio de privacidade mede a **forma dos valores** e não nomes de campo, com três detectores — telefone nas três grafias (os dois padrões canónicos de `../tools/contract_diff/pii.py`, importados, mais a forma **local** de nove dígitos que nenhum deles apanha), `wamid` em claro, e texto livre pela presença de um caractere fora do alfabeto estrutural — e corre-os **primeiro sobre a entrada**, como canário: um detector que devolvesse zero passava tudo, e um ensaio por nome de campo fica verde com uma mensagem inteira num campo chamado `fase`. Os telefones **descartam-se e não se resumem** (um móvel de nove dígitos inverte-se por enumeração; ADR-010, `../docs/logs.md` §2.1) e no lugar fica o rótulo `N1`–`N3`. A tabela N1–N3 fixa a **regra do zero**: zero eventos escreve-se `NÃO MEDIDO` e nunca `N`, com uma excepção — o *echo* da API, onde houve *echoes* e nenhum é nosso é prova de ausência. **Oito itens devolvidos** no §6 do `H3_Coexistencia_244.md` — entre eles uma medição feita com o próprio validador, que acusa **23 achados em 9 dos 11** ficheiros de `validacao/` por não declararem `Estado`, `Fonte` ou `Dono`, devolvidos aos tickets donos e **não** emendados aqui — e **três** no §4 do `Registo_Hipoteses.md`, cada um com credor nomeado; entre os do registo, duas divergências medidas e não resolvidas: o `14` §2 tem **doze** hipóteses onde o critério de saída deste epic pede **nove**, e o `14` §6 **não dá pivô** a H7, H8 nem H9. **106 ensaios verdes** no *harness*, **27** no validador e **10 de 10** no ida-e-volta real contra o processo; os literais com forma de móvel ficam declarados no `INVENTARIO` com contagem exacta (**5**, num ficheiro só). **A revisão adversarial devolveu 16 achados — os 16 confirmados contra a árvore, nenhum morto — e está na** [`ANALISE-53`](../docs/analises/ANALISE-52-KAM-100-spike-h3-coexistencia.md). Os dois que mais valem atacam a garantia que o ticket diz entregar: a **excepção à regra do zero** afirmava `N` medido sobre zero envios pela API — e nada nos JSON-lines diz que enviámos —, e a chave `fase`, a única da *allowlist* que admitia dígitos, **admitia um telefone**, que o extractor fabricava a partir de qualquer inteiro do `metadata.phase`. Os dezesseis ficam corrigidos com ensaio de regressão; o terceiro mais caro é o **validador entregue sem um único ensaio**, onde quatro dos achados viviam, e que passa a ter 27. | Equipa KAMBÁ |
| 1.11 | Novembro 2026 | KAM-102: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas ficam em **0 de 9 critérios e 0 de 5 de DoD** — o zero é o resultado certo, porque **oito dos nove critérios pedem um acto de submissão, de gravação, de confirmação no painel ou de recepção de resposta de terceiro**, e o nono (o critério 1) pede uma medição que exige submissão. Um ficheiro novo em `../docs/tecnica/evidencia/validacao/`: o dossiê dos **seis** passos do estatuto perante a Meta, com o passo 4 **desdobrado em quatro linhas, uma por permissão** (o critério di-lo, e a lista de verificação da semana 6 mede cada uma em separado), coluna **«Estado»** separada da «Resultado» — porque `por submeter` não é um resultado, e é assim que o `Seguimento_APD.md` o faz — e a nascer a **0 submetidos, 0 aprovados, 0 prazos medidos**. A regra de contagem de dias úteis fica escrita **antes** de haver o que contar, com os feriados a **não** descontar e o fuso em **`Africa/Luanda`**, que é o que o dicionário canónico manda para apresentação. **O prazo da Business Verification não é substituído por um valor medido**, como o critério 1 pede: fica **NÃO MEDIDO**, e a caixa fica **vazia** em vez de cumprida em espírito; o inventário dos prazos com fonte dá a cada um o estado certo — «cerca de 24 horas» como **número da Meta**, o «*turnaround* muito mais rápido» da verificação por **Select ou Premier** Solution Partner como **NÃO VERIFICADO** (a página que o carrega está declarada «listada, não lida» em E1 §3), e o único **INDÍCIO** que o conjunto tem, «dias a semanas» de E5 §3, com o âmbito e a falta de fonte oficial escritos. App Review com as **quatro** permissões — as duas de E1 §3 e as duas que o critério 9 manda pedir, que **não constam de E1** —, **quatro** descrições escritas em **EN e PT**, e um *storyboard* de **seis** gravações: quatro para as permissões do WhatsApp, porque **as três fontes usam duas redacções e nenhuma diz quantos ficheiros se submetem** (E1 §3 «uma gravação por permissão»; o critério 3 «2 vídeos por permissão»; o `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §4.2 repete a segunda e acrescenta o parêntesis «(mensagem, template)», que é a primeira), e **duas para as permissões de redes**, do único fluxo que existe — gerar, o dono aprovar, **entregar para publicação manual**. Continua **NÃO VERIFICADO** se a Meta concede *Advanced access* com base nessa demonstração, e **gravar o acto de publicar não é opção**, porque o ADR-020 regra 3 o proíbe no Piloto. Contador das **3** submissões a **0 de 3**, com a armadilha circular escrita: a via de escalada é o *Direct Support*, que é atributo do estatuto que o App Review concede. Guião de ensaio do protótipo em **sete** passos, que dispensa escrever código porque E1 §3 confirma que a cURL do API Setup e o WhatsApp Manager servem no lugar da app. Matriz de **D5** com as três opções e **a leitura do canon corrigida pela revisão**: o ADR-001 nomeia Tech Provider e o que **bane** é o *gateway* não-oficial, D5 continua **ABERTA** no `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3 e na Carta §4.2, e o BSP é **plano B escrito** no `01` §4.1 e **pivô** no `14` §6 — logo **exercer o plano B não é substituir um ADR**, e se a redacção do ADR-001 tiver de mudar isso é do Arquitecto de Plataforma com o fundador. Tabela das cotações a nascer vazia — **0 pedidas, 0 recebidas, mínimo 2** — com «suporte a BSUID» como coluna **eliminatória**; os preços de BSP de E1 §8 **não entram em célula nenhuma**, por serem INDÍCIO. O **modelo de cotação** que os «Detalhes Técnicos» mandam preparar está entregue: o corpo é a **Q15**, que não se reescreve, mais as **três** perguntas que ela não faz e de que a matriz depende — presença em África, moeda de facturação e se factura em Kwanzas —, com os destinatários que o conjunto nomeia (360dialog e Twilio) e a linha do BSP **com presença em África «a identificar»**, porque nenhuma fonte deste conjunto nomeia um. **D5 fica ABERTA e não «provisória»**, e falta-lhe também o **input de D9** sobre quem paga em USD, que o `Seguimento_APD.md` deixa vazio por ser decisão do fundador. A barreira do cartão tem lugar preparado e **nenhum número**: **0 de 0 é «não medido», não é zero por cento**, com a atribuição corrigida — é **E1 §1** que dá como CONFIRMADO que a Meta factura Angola em moeda estrangeira e tira daí a implicação da barreira, e quem lhe põe o rótulo INDÍCIO é a tabela de riscos **deste epic**. Credor: **KAM-106**. Limites de *onboarding* CONFIRMADOS (10, depois 200 com os três passos, Meta Business Partner acima disso), *Access Verification* mantida **NÃO VERIFICADA** com a **Q9** como única via, e o aperto que o KAM-101 trouxe — **sem *advanced access* não se integra cliente nenhum**, condição anterior ao limite de 10 — citado como **INDÍCIO, uma leitura**, com remissão da própria célula do «10». Quatro avisos para o **KAM-095**, o principal dos quais é não fixar o 200 como constante final. Regra de falha da semana 6 como lista de verificação, com «sem Tech Provider» **definido** pelas quatro linhas da medição, os cinco passos da consequência com a paragem do KAM-016 que a Carta §4.2 nomeia, e os três pivôs do `14` §6 com o que cada um custa — o do BSP com o pré-requisito a **zero**. **A Carta §4.2 não nomeia quem assina D5** — dá-lhe dono **Produto** —, pelo que a assinatura do fundador cobre o **pivô** e os actos que são dele, e o **registo** de D5 é do dono. A cláusula **4.7** entra por razão substantiva (MPS e BSP implicam contratar um Solution Provider, que é a condição que o achado do KAM-101 nomeia), fica **INDÍCIO de uma leitura**, **nada se relaxa**, e a correcção é da L1 com o **fundador** como credor — com a nota de que a prosa da fonte diz **cinco** e a tabela do seu §3.1.1 enumera **seis**, discrepância escrita e não corrigida. **Dezoito** itens devolvidos, cada um com credor que sobrevive à fusão, e o fundador é credor em **onze**. **A integração da `main` em `111de2d` fechou um e abriu outro:** o `validar_evidencia.py` dos «Testes Requeridos» aterrou com a fusão do **KAM-100**, correu sobre o dossiê e **falhava** — faltavam-lhe `Estado`, `Fonte` e `Dono` no cabeçalho —, e com os três declarados dá **`conforme`** (código 0); em troca, medir a pasta inteira mostrou que **os outros onze ficheiros de `validacao/` não passam**, o que é achado para a linha **L1** e não se corrige aqui. A mesma fusão obrigou a renumerar esta linha de **1.10** para **1.11** e a renomear a análise de `ANALISE-52` para `ANALISE-53`, porque o KAM-100 levou as duas. **A revisão adversarial devolveu 27 achados — 15 `CONFIRMADO` e 12 `PLAUSÍVEL`, todos verificados contra a árvore e todos aplicados — e está na** [`ANALISE-53`](../docs/analises/ANALISE-53-KAM-102-tech-provider.md). Os três que mudaram a entrega: **desmarcou a única caixa marcada** (a caixa 3 de DoD prova a ausência no repositório e não a existência do arquivo controlado, e o *gate* 9 corre **duas** passagens das quais só uma correu localmente); **desfez o endurecimento do ADR-001**; e mostrou que o *storyboard* das permissões de redes **estava ao alcance** pelo fluxo de entrega manual, onde a primeira versão chamava «achado» à ausência dele. Mais quatro citações de secção erradas que nenhum *linter* apanha, porque as secções existem e é o conteúdo que não está nelas. | Equipa KAMBÁ |
| 1.12 | Novembro 2026 | KAM-103: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas passam a marcadas onde há evidência: **3 de 8 critérios e 2 de 5 caixas de DoD**. Um ficheiro novo em `../docs/tecnica/evidencia/validacao/` — seis fichas de contraparte (dois bancos de apoio, ProxyPay/TimeBoxed, AppyPay, e as opcionais EMIS e PayPay) com as perguntas **1 a 18** de `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §9 endereçadas, a célula da matriz que cada resposta alimenta, e o registo com data, remetente **pelo papel** e classificação pela **origem** (o verbal fica INDÍCIO mesmo vindo da contraparte). O registo e a folha de seguimento **nascem vazios**: zero enviadas, zero respondidas, porque contactar contrapartes, pedir chaves e rever uma minuta são actos humanos, e as cinco caixas abertas de critério têm todas essa causa. A matriz banco × facilitador tem doze grandezas e cinco caminhos, cada célula com o seu estado, e **uma só é CONFIRMADA sobre comissão por transacção** — a da AppyPay —, com as três coisas que ela não cobre escritas por extenso: não inclui a comissão bancária, não inclui o IVA, e **não é o custo da ProxyPay**. **H5 fica `inconclusiva` com amostra zero**, e a divergência de leitura é declarada em vez de decidida: o critério nomeia duas saídas e a entrega registra uma terceira, porque `refutada` sobre amostra zero é uma conclusão tirada de ausência de dados e dispararia o replaneamento de três tickets — e `inconclusiva` não é invenção, é um dos três estados que o critério A do **KAM-110** fixa. **D4 fica registada e não decidida**, com **dono (papel) Responsável de Produto** pelo registo da `00_KAMBA_Carta.md` §4.2 e **quem fecha** nomeado à parte (o fundador); os **sete** critérios do bloco ponderam-se todos, e dois deles são também **portões de canon** (ADR-013 e ADR-004) que excluem qualquer que seja a pontuação. Aplicada ao que hoje se sabe, **nenhum candidato adopta e os dois melhores estão bloqueados por portões diferentes** — a ProxyPay tem o contrato técnico CONFIRMADO e falha a liquidação directa, a AppyPay tem metade do custo CONFIRMADA e falha a confirmação autenticável —, pelo que o gatilho são **duas** respostas por candidato e não uma. O impacto em KAM-056, KAM-057 e KAM-059 está escrito **sem tocar numa linha do backlog mestre**, e o achado dessa secção é que **os três já têm a sua saída escrita no próprio bloco**. **O achado mais valioso é o da fronteira do ADR-004:** a pergunta da conta-mestre tem duas leituras que a frase de E2 §9 não distingue, e a segunda é o **desenho B** de E2 §3.3 — a plataforma como comerciante único, actividade regulada —, pelo que um «sim» não desambiguado é uma célula NÃO VERIFICADO e não um «sim»; o FTBAI da AppyPay é o segundo sinal, na direcção do desenho C. Instrumento de medição em `spikes/proxypay-d4/` (descartável, Python da biblioteca padrão; medido que `spikes/` não acrescenta critério a portão nenhum — e **não** que seja pasta isenta: o *gate* 3b alcança-a por SQL (daí a **dispensa** do `ci/canon-lint.yaml` para o `.sql` de outro *spike*) e o *gate* 7 varre-a como ao resto da árvore): **10 de 10 predicados verdes** contra um *mock* e **dezesseis defeitos, dezesseis vermelhos** no canário. O ensaio do *callback* do OPG é **instrumento e não predicado** — se é assinado continua NÃO VERIFICADO, e um *mock* que o assinasse punha o *script* a provar a nossa própria escolha. Medido e escrito: **nenhum dos quatro números de telemóvel do ticket é apanhado pelo varrimento do *gate* 7** — 33 ficheiros e 115 ocorrências na árvore, idênticas ficheiro a ficheiro ao `INVENTARIO` —, pelo que nenhum ficheiro leva entrada no inventário, e uma entrada a mais **seria um defeito** e não precaução. **A revisão adversarial devolveu 18 achados — 17 `CONFIRMADO` corrigidos e 1 parcialmente morto** — e os três mais graves eram todos do instrumento, nenhum deles a avermelhar portão: o `amount` **não atravessava asserção nenhuma** (o **G4 «Valor exacto»**, regra imutável, com os dez ensaios verdes e 1.500,00 Kz a liquidar por 1,00 Kz), o `fee` era medido por presença de chave, e o código do quarto desfecho do OPG era **importado do alvo** no único sítio onde o comentário dizia ter evitado essa armadilha. No documento, o mais grave foi o **dono de D4**, e dois foram da fronteira do ADR-004: o §5.2 apresentava a ProxyPay como destravável por uma só resposta sobre preço quando ela falha o portão da liquidação directa, e a abertura dizia «o único sinal» contrário quando o §7.2 já nomeava dois. **E um buraco no dossiê:** nenhuma das cinco perguntas à AppyPay pedia o prazo de activação, que é metade de H5 nas duas colunas dela — entrou como **11-a**, acréscimo declarado, com a numeração de E2 §9 intacta. **A linha nasceu com o número que o KAM-100 levou e foi deslocada na integração**, à mão e só nela: o `1.10` ficou com o **KAM-100** (fundido em `111de2d`) e o `1.11` é do **KAM-102**, e um `sed` sobre «1.10» apagava a linha do KAM-100. Medido depois de deslocar: **zero** auto-citações do número antigo dentro das células, e o campo `Versão` do cabeçalho a acompanhar a última linha. **E a sequência ficou com um buraco deliberado:** o `lint_backlog` recusa-o (`o «Controlo de versões» salta a 1.11`, exit 1) enquanto o KAM-102 não aterrar, e aceita-o (exit 0) com a `1.11` presente — as duas medidas feitas. A ordem de fusão deixou de ser preferência: o **KAM-102 funde primeiro**, por mecânica do portão e não por convenção. | Equipa KAMBÁ |
| 1.13 | Novembro 2026 | KAM-108: o bloco ganha a secção «Verificação dos Critérios de Aceitação», e as caixas ficam em **0 de 8 critérios e 0 de 5 de DoD** — e o zero é o resultado certo, porque o primeiro critério é **uma demonstração com a Meta real, conduzida três vezes por quem não escreveu o código**, e o oitavo é **um veredicto com três assinaturas**; os «Detalhes Técnicos» deste bloco dizem-no por extenso. **Sub-condições dentro de seis dos oito ficam satisfeitas com evidência nomeada**, e isso é o que distingue «não medido» de «medido e ainda não fechado». Três ficheiros novos em `../docs/tecnica/evidencia/validacao/` — a checklist G0-1 a G0-8 com estado, evidência ligada ou **credor** por linha; o modelo da decisão, **por preencher**, com a regra de veredicto **transcrita** em vez de resumida (um resumo de uma regra de veredicto é uma regra diferente), a tabela de itens abertos onde um item **sem data** não sustenta um AMARELO, e os três blocos de assinatura; e o guião da demonstração com o cenário *scriptado* em oito passos — e o pacote `../tools/gate_fase0/`, com **104 ensaios verdes** e 98% de cobertura (`traco.py` a 100%). **Ponta de medição: `fe40048`.** O **cenário é gerado** do `cenario.py` e não escrito à mão, com ensaio a exigir que cada elo que o traço procura tenha um passo que o produz: duas cópias divergiam, e a demonstração podia correr os passos certos com o traço a medir outra coisa, cada um certo por si. **O traço lê duas fontes e não uma, e isso mediu-se antes de se escrever código:** o ADR-010 e o `../docs/logs.md` §2 fixam uma *allowlist* de doze campos e `order_id`, `event_id`, `booking_id` e `conversation_id` **não são nenhum deles** — o §2.2 recusa o `contact_id` pelo nome —, pelo que dos quatro elos os *logs* dão o primeiro e os outros três vêm de consultas de leitura que projectam **só** identificadores. São **três barreiras** contra conteúdo e telefone (lista fechada, forma do valor, guarda da saída) e a terceira existe porque as duas primeiras são código que alguém pode alargar sem reparar; o ensaio que vale é o **controlo negativo** — entrada com conteúdo e um telefone de forma real, saída sem nenhum dos dois, e os detectores a correr **primeiro sobre a entrada** como canário, sem o qual um detector que devolvesse zero passava tudo. **Os carimbos não entram como inteiro, e a razão é o telefone:** nove dígitos são um carimbo Unix **e** um móvel angolano, pelo que um campo `int` aceitaria um telefone com a forma certa e nenhum detector o apanharia. **O varrimento do *gate* 7 não muda com este PR** — medido antes e depois, 35 ficheiros e 124 ocorrências, idênticas ficheiro a ficheiro e iguais ao par fixado do `../tools/meta-sim/tests/inventario.test.ts` —, porque o número de forma real do controlo negativo **monta-se em execução** e não aparece como literal: nenhum ficheiro deste ticket leva entrada no `INVENTARIO`, e uma entrada a mais seria um defeito. **O G0-7 era o que mais convidava a inventar estado, e a regra que o fecha é mecânica:** as sete linhas leem-se de um manifesto que o `recolha.py` verifica contra três invariantes — cada ponteiro existe na árvore, **nenhuma linha diz `confirmada` com a evidência vazia**, e nenhuma fica sem credor —, cada uma com canário. **As sete estão `inconclusiva` e os sete tickets que as alimentam estão fundidos**, que é a razão de a tabela existir: «o ticket fundiu» não é «a decisão está tomada». A segunda metade do critério **não se activa**, porque `inconclusiva` não é `refutada` e as duas linhas têm amostra zero — tratar ausência de dados como falha disparava uma decisão de mudar de canal sobre um dado que ninguém mediu. **O G0-4 mediu-se com instrumento** e dá **11 verdes, 1 vermelho e 3 sem *job*** na execução `42222973021`: um gate do §4 **sem *job*** não é verde nem vermelho, e contá-lo como qualquer dos dois dá a leitura errada; o **gate 5** falha **por desenho** até o KAM-003 o ligar e **não é um *skip***, é uma reserva declarada com o ticket no nome. O **G0-2** está medido — **88,30%** de reaproveitamento e `fluxo 0` no núcleo, com o limiar lido de `ci/regra-de-dois.yaml` — e **re-mede-se depois do KAM-055**, que não está nesta ponta; o `gate_fase0 reuso` recusa um artefacto de árvore suja ou de outra ponta, para que a re-medição não se confunda com esta. **Duas divergências medidas, e nenhuma é defeito deste ticket. A do G0-5 está DECIDIDA** — o fundador decidiu a 2026-11-06 que **o critério não muda e a divergência fica registada**, com as duas citações lado a lado e a data da medição, pelo que a linha fica com o estado que a evidência sustenta e não `não aplicável`: o **G0-5** exige «sonda externa activa» e o `../docs/observabilidade.md` §1 — do KAM-080, o ticket que o próprio critério manda dar por concluído — diz «Sonda externa — **Não existe. Não há produção**»; e o **G0-1** exige um consumo cuja **acção não está escrita**, com os dois pares em `ACCOES_POR_LIGAR`, desfecho `sem_accao`, e o contrato publicado dos dois eventos em `additionalProperties: false` **sem `booking_id`** — e os dois credores que o código nomeia, **KAM-047** e **KAM-007**, já fundiram, pelo que a linha não tem credor vivo — e **essa fica devolvida**, com três perguntas separadas. Escrever essa acção e emendar um contrato de evento publicado são **ticket novo**. **O G0-6 não se calcula**, e a razão é uma medição: nenhuma fonte do conjunto fixa a data de início da Fase 0, e as duas mais próximas — o ADR-020 a 2026-10-09 e o primeiro *commit* da `publico/main` a 2026-10-15 — não são o início e não se usam como se fossem. Nada deste ticket está ligado a portão nenhum, por desenho. | Equipa KAMBÁ |

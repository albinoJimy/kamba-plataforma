# EPIC-10 — Spikes, Validação e Gates

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Spikes, Validação e Gates |
| Versão | 1.0 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md` (§13), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/08_Seguranca_Conformidade.md` (§8, §13), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§5), `../docs/tecnica/10_Onboarding_Governanca.md` (§6), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/00_KAMBA_Carta.md`, `specs/EPIC-02_Canais_WhatsApp_Handoff.md`, `specs/EPIC-08_Topologia_Operacao.md`, `specs/01_Engineering_Standards_e_Handoff.md` |

---

## 1. Visão do Epic

Este epic **não entrega funcionalidade de produto**: entrega factos, medições, decisões e dois gates. Reúne (a) os sete itens com **tempo de espera externo** que arrancam na semana 1, em paralelo ao código, e que são o caminho crítico real (`14` §3A Regra 3; `INDICE.md` §3.3): o spike de coexistência com três números +244 (KAM-100), as perguntas escritas à Meta (KAM-101), o estatuto de Tech Provider (KAM-102), os contratos de pagamento (KAM-103), o pacote para o parecer jurídico (KAM-104), a decisão de alojamento e o procedimento APD (KAM-105) e os canais de acesso a PMEs com 30 entrevistas (KAM-106); (b) o spike de voz PT-AO (KAM-107); e (c) os gates: o da Fase 0 (KAM-108), a medição do piloto (KAM-109) e o da decisão continuar, pivô ou parar (KAM-110).

Existe porque o documento 14 impõe que **cada hipótese morra ou sobreviva com um número** (H1–H9, limiares *propostos* pelo fundador) e porque várias dependências críticas são **NÃO VERIFICADAS** em `../docs/tecnica/evidencia/`: coexistência em +244, classificação da KAMBÁ como *AI Provider*, prazo e documentos da Business Verification, preços da ProxyPay, prazo de onboarding bancário, enquadramento BNA do modelo facilitador, procedimento e prazos da APD e qualidade do STT em português de Angola. Cada ticket fecha um desses itens ou regista o pivô previsto em `14` §6; nenhum facto NÃO VERIFICADO passa a requisito sem esse critério de saída. Concretiza ADR-001 (coexistência e Tech Provider), ADR-004 e ADR-013 (facilitador, D4, D8), ADR-008 (D1, D9), ADR-011 (D2), ADR-012 (regra de dois, no gate da Fase 0), ADR-018 (golden sintético e Termos da Meta sobre ML) e ADR-019 (onboarding self-service no Piloto). Os donos de decisão seguem o registo da Carta (`00_KAMBA_Carta.md` §4.2).

**Natureza dos tickets.** Os critérios de aceitação são **saídas verificáveis**: documento com campos definidos, tabela de medição com limiar de sucesso e de falha, decisão registada com dono e data, ficheiro de evidência em `../docs/tecnica/evidencia/validacao/`. O Claude Code **prepara** guiões, modelos, *scripts* de medição e folhas de registo; **não** conduz reuniões, entrevistas nem recebe respostas de terceiros, e nenhuma decisão é automática. Pareceres, respostas da Meta, dos bancos e da APD são «a confirmar por parecer» ou por escrito; nada neste epic é aconselhamento jurídico. Os limiares de `14` §2 são propostas: fixam-se antes de medir e só mudam por emenda registada. Calendário de referência: H3 e H4 correm primeiro; ponto de decisão na semana 6 (`14` §3A Regra 5). Fases: 0 (KAM-100 a KAM-106, KAM-108) e 1 (KAM-107, KAM-109, KAM-110). Abreviatura: «`14`» designa `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md`; «E1» a «E4» designam `../docs/tecnica/evidencia/E1_…` a `E4_…`.

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
- [ ] Todo o item NÃO VERIFICADO de `E1`–`E4` citado pelos tickets deste epic tem estado final (`fechado` com fonte, ou `mantido` com razão e dono).

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
- [ ] **Passo 0 (até ao dia 2):** nota em `../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` a dizer se o ES v4 de coexistência pode correr antes da aprovação de Tech Provider (p. ex. app em modo de desenvolvimento com utilizadores com função): `Sim`, `Não` ou `NÃO VERIFICADO`, com data e fonte; se `Não`, o spike espera pelo KAM-102 e o novo prazo fica registado.
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
- [ ] Nenhum conteúdo de conversa nem telefone em claro nos ficheiros de evidência (ADR-010).
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
- [ ] `../docs/tecnica/evidencia/validacao/Meta_Perguntas.md` contém as 15 perguntas de E1, cada uma com: n.º, texto em EN e PT, secção de E1 que a origina, decisão afectada (D2, D5, ADR), ticket afectado, prioridade, canal, data de envio, estado (`enviada`, `respondida`, `sem resposta`).
- [ ] As 8 perguntas que condicionam o Piloto (classificação *AI Provider* Q2, coexistência +244 Q3, números fixos e SMS Q4, cláusula de ML §4.7 Q7, Business Verification de empresa angolana Q8, *Access Verification* Q9, pagamento local Q11, *timeout* e *retry* do webhook Q12) são enviadas até ao dia 5; as restantes (Q1, Q5, Q6, Q10, Q13, Q14, Q15) até ao dia 10.
- [ ] Cada resposta fica arquivada com texto integral, data, remetente, canal e classificação: CONFIRMADO só se for da Meta por escrito (Direct Support ou canal oficial); INDÍCIO se vier de BSP, parceiro, fórum ou verbal.
- [ ] Os trechos com maior impacto de E1 (cláusula §4.7, definição de *AI Provider*, lista de países da coexistência, *Access Verification*) são relidos na fonte primária em inglês, com URL e data, e o desvio face a E1 é registado.
- [ ] **Regra de H4 (registada até à semana 6):** `confirmada` se houver resposta escrita da Meta que não classifica o produto como *AI Provider*, ou aprovação de Tech Provider (KAM-102) — a aprovação sozinha não afasta o critério «exclusivo da Meta», e essa ressalva fica escrita; `inconclusiva` sem resposta à semana 6, com risco aceite pelo Responsável de Produto, plano B (cotação de BSP) e Fluxo B diferido; `refutada` se a Meta classificar como *AI Provider* ou recusar o caso de uso, com o pivô de `14` §6 (mudar de canal).
- [ ] D2 e D10 registadas: D2 mantém-se CONDICIONAL com o estado das Q1/Q5/Q6; D10 regista a decisão provisória (canal do fundador no Piloto, risco assumido, `../docs/tecnica/10` §11.1) com gatilho na resposta da Meta.
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
- [ ] Itens NÃO VERIFICADOS de E1 respondidos com estado final ou mantidos com razão.
- [ ] Impacto de cada resposta nos tickets KAM-016, KAM-033, KAM-088 e Clusters listado.

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
- [ ] Matriz banco × facilitador com: documentos exigidos, custo único e recorrente, comissão por transacção (AppyPay 0,40%, mín. 50, máx. 1.500 Kz como CONFIRMADO; restantes só com proposta por escrito), liquidação (D+0/D+1/D+2 e horas), limite por transacção, prazo em dias úteis e o dono do contrato.
- [ ] **Limiar H5:** existe ≥ 1 caminho com prazo de onboarding por PME ≤ 6 semanas (30 dias úteis) declarado por escrito pela contraparte, ou medido num caso real (a empresa do fundador como primeiro caso); caso contrário H5 é `refutada`.
- [ ] Respostas explícitas a: o callback do OPG é assinado; rotação da chave HMAC da ProxyPay (a chave HMAC é a API key); conta-mestre multi-comerciante ou modelo ISV (ProxyPay Q9, AppyPay Q15); webhook assinado e *retry* da AppyPay (Q12); certificado EMIS (Q13).
- [ ] **D4 registada** (dono e data) com critérios ponderados (*proposta*): callbacks assinados ou polling de reconciliação, sandbox, liquidação directa, prazo, custo, modelo multi-comerciante, cobertura (Unitel Money). Sem contrato à semana 6, o Piloto fica em `ManualProvider` (Carta §4.2) e a decisão é escrita.
- [ ] Se H5 falhar: manter as camadas 1–2 e vender atendimento e agenda sem cobrança integrada (`14` §6); o impacto em KAM-056, KAM-057 e KAM-059 fica listado.
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
- [ ] Sem chaves de API nem documentos bancários no repositório (cofre e arquivo controlado).
- [ ] Itens NÃO VERIFICADOS de E2 (preços ProxyPay, assinatura de callbacks, prazo bancário) com estado final.
- [ ] Nenhum compromisso contratual de posse de fundos (ADR-004) — verificado por revisão jurídica.

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
- [ ] `../docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md` (e exportação para o advogado) cobre 100% de: as 20 perguntas de E3; as perguntas 19–30 de E2 (BNA 19–25, AGT 26–29, contabilista 30); a leitura da cláusula §4.7 dos Termos da Meta (E1 Q7); N1 (CDN como subprocessador), N2 (backups cifrados fora de Angola com chave em Angola), N3 (HMAC com pepper) e N5 (desenho de pagamento fora do Aviso 2/22 art. 4.º j)) de `../docs/tecnica/08` §13; e 3 perguntas novas (X1 dados reais de teste com consentimento em spikes, X2 quem paga os custos em USD e retenções sobre pagamentos a fornecedores estrangeiros, X3 uso de conversas para avaliação face aos Termos da Meta).
- [ ] Cada pergunta tem: n.º, texto, contexto, por que importa (decisão e tickets bloqueados), opções propostas pela KAMBÁ, resposta pedida (parecer escrito), prioridade (P0, P1, P2 de `../docs/tecnica/08` §13: P0 = E3 1, 2, 3, 4, 5, 6, 18, 20; P1 = 7, 9, 11, 12, 15, 16; P2 = 8, 10, 13, 14, 17, 19; BNA Q19–Q20 e Q30 propostos P0, restantes P1/P2) e prazo pedido.
- [ ] Anexo «factos do caso» (≤ 6 páginas) gerado a partir de `../docs/tecnica/`: fluxos de dados, inventário de subprocessadores (`../docs/tecnica/08` §8.3.2), classes de dados, retenção proposta (§11), papéis (§8.2), arquitectura de pagamentos (liquidação directa, sem posse de fundos); sem dados pessoais.
- [ ] Pacote P0 enviado até ao dia 7 (fim da semana 1); resposta preliminar às P0 que decidem D1 pedida até à semana 3 e parecer escrito P0 até à semana 6; o prazo efectivamente comprometido pelo advogado fica registado.
- [ ] Selecção do advogado documentada: ≥ 2 propostas de honorários, critérios (experiência com APD e BNA), carta de compromisso com confidencialidade, âmbito P0/P1/P2, formato (parecer escrito com referência e data) e prazos.
- [ ] Registo de respostas: cada resposta recebida fica com data, autor, classificação «CONFIRMADO (jurídico)» e lista de tickets e decisões afectados (D1, D8, D9, D11, D12; KAM-069, KAM-070, KAM-088, KAM-090).
- [ ] Os itens que a KAMBÁ assume até haver parecer ficam listados com dono (p. ex. comissão sobre transacção desligada, ADR-017; finalidades próprias da KAMBÁ desligadas, `../docs/tecnica/08` §8.2).

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
- [ ] Confidencialidade respeitada; sem dados pessoais nem segredos no pacote.
- [ ] Mapa pergunta → decisão → ticket publicado; KAM-105 informado do que depende de resposta.
- [ ] Nenhuma resposta tratada como aconselhamento jurídico antes de recebida por escrito.

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
- [ ] Teste de latência RTT com VM ou *trial* quando o fornecedor o oferecer; sem oferta fica «NÃO MEDIDO» e o KAM-077 mede.
- [ ] D6 registada como recomendação dependente de D1 (SeaweedFS 4.48 *single node* ou S3 gerido), com a lista de testes pendentes (KAM-076); a decisão final fica em KAM-011.
- [ ] D9 registada com base na resposta do advogado a E3-1: papel da KAMBÁ (subcontratada por defeito, `../docs/tecnica/08` §8.2), quem notifica a APD (plataforma, PME ou ambas) e a entidade que paga os custos em USD; se o parecer ainda não chegou, a decisão é **provisória**, marcada como tal.
- [ ] `Mapa_Tratamentos_v1.md` gerado do inventário de subprocessadores: por destino (Meta, LLM, STT, alojamento, backups, CDN se existir, e-mail/SMS, sonda, facilitador), país, finalidade, categorias de dados, retenção proposta, garantias (retenção zero, sem treino) e estado do `apd_ref`; o número de destinos de produção do Piloto é reduzido ao mínimo (*proposta*: 1 LLM, 1 STT).
- [ ] Submissão à APD feita por destino com taxas pagas e **número de protocolo**, ou decisão escrita do advogado de que não é exigida; folha de seguimento (`submetido`, `em apreciação`, `autorizado`, `negado`) com os prazos reais decorridos.
- [ ] `GoLive_Gate.md` com a checklist objectiva de entrada de dados reais: D1 decidida; cada destino de produção com `apd_ref` válido; mapa aprovado; DPA e aviso publicados (KAM-090); D9 decidida; checklist de segurança de `../docs/tecnica/08` §8.5 #11; cada linha com estado e data.

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
- Casos T2 resolvidos alimentam o golden **só por reescrita sintética sem dados pessoais** (ADR-018, `../docs/tecnica/10` §11.2); conversas reais não treinam nem melhoram modelos (Termos da Meta, a confirmar em KAM-101).
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

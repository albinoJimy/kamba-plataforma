# EPIC-07 — Segurança e Conformidade

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Segurança e Conformidade |
| Versão | 1.7 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/08_Seguranca_Conformidade.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md` |

> **Aviso.** Este epic não é aconselhamento jurídico. Tudo o que toca a Lei 22/11, APD, BNA, AGT, defesa do consumidor e política da Meta leva «(a confirmar por parecer)» e liga-se às perguntas do KAM-104. Os textos de lei citados em `../docs/tecnica/evidencia/E3` vêm de repositórios não oficiais e têm de ser verificados no Diário da República antes de uso contratual.

---

## 1. Visão do Epic

A tese da KAMBÁ é tornar as falhas *arquitecturalmente impossíveis*; «impossível» é um objectivo de desenho, não uma garantia, e este epic é o que mede e fecha o **risco residual**. Cobre seis frentes: (1) o **modelo de ameaças** STRIDE por componente e a matriz requisito → controlo → teste → dono; (2) o **isolamento em profundidade** (ADR-015: `tenant_id` do estado na ToolLayer, RLS `FORCE`, prefixo de storage, conta Chatwoot por PME) verificado por uma suite cruzada que falha o *build*; (3) a **cadeia de abastecimento** (lição do LiteLLM 1.82.7/1.82.8 de 2026-03-24, CONFIRMADO): digests, cosign, SBOM, lockfiles com *hash* e lista de bloqueio de licenças e pacotes; (4) a **privacidade por desenho** (ADR-010): logs sem conteúdo, gate de transferência com `apd_ref`, direitos do titular e retenção por classe; (5) a **gestão de chaves** com rotação ensaiada; (6) o **red-team** do AGR e a **revisão independente** antes de dados reais.

A fronteira jurídica é o ponto de maior consequência: a APD multou a Crescer Tech em USD 505 000 (2026-06-24, CONFIRMADO) por enviar dados para uma cloud no estrangeiro sem notificação nem autorização, e alojar em Luanda não dispensa o procedimento, porque LLM, STT e a própria Meta já são transferências (INDÍCIO, `../docs/tecnica/evidencia/E3` §7). Por isso a regra é *fail closed*: sem destino registado com `apd_ref` a chamada falha, e não se vai a produção com dados reais sem o gate de go-live (D1, D9, KAM-105). Itens NÃO VERIFICADOS (países adequados, cláusulas-tipo da APD, papel da KAMBÁ como responsável ou subcontratada, prazo de conservação fiscal, Circular 02 da APD) não viram requisitos sem critério de saída: ficam como parâmetros, perguntas ao advogado ou *flags* desligadas.

Concretiza os ADRs **ADR-015** (isolamento), **ADR-008** (residência e transferências), **ADR-010** (identidade e logs sem conteúdo), **ADR-002/005/014** (licenças e cadeia de abastecimento), **ADR-013** (callbacks e confirmação manual) e **ADR-004** (o que a plataforma não pode fazer), com o ADR-007 na camada de saída anti-injecção. **Fase 0:** KAM-065 a KAM-068 (modelo de ameaças, isolamento, cadeia de abastecimento, logs). **Fase 1:** KAM-069 a KAM-074, antes de qualquer tenant com dados reais.

---

## 2. Critérios de Saída do Epic

- [ ] O documento STRIDE cobre os 16 componentes do Piloto × 6 categorias (96 células) e cada célula tem controlo com teste associado ou risco aceite por escrito pelo Responsável de Segurança.
- [ ] A matriz de conformidade cobre os 25 requisitos de `../docs/tecnica/evidencia/E3`, as regras da Meta de `../docs/tecnica/08` §8.7, as guardas G-1..G-6 e C-01..C-09, e nenhuma linha fica sem ticket, teste e dono.
- [ ] A suite cruzada X-01..X-11 corre em cada PR e bloqueia o *merge*: 0 leituras cruzadas entre tenants e entre contactos; 0 tabelas com `tenant_id` sem RLS `FORCE`; um defeito semeado (remover um `WHERE tenant_id` ou uma política) torna o *build* vermelho.
- [ ] 100% das imagens por digest com SBOM e verificação cosign onde publicada; os pacotes e licenças da lista de bloqueio não entram (teste com 5 violações semeadas falha o CI).
- [ ] 0 identificadores directos (telefone, NIF, nome, texto de mensagem) em logs: o varrimento X-11 sobre 1 000 *fixtures* e a amostragem semanal em `prod` dão 0 ocorrências.
- [ ] 0 destinos de transferência usados sem linha `autorizado` com `apd_ref`; o gate de go-live recusa a activação de tenant sem inventário completo, DPA aceite e referência APD ou decisão formal do advogado.
- [ ] O pedido do titular (acesso, correcção, eliminação, exportação) corre ponta a ponta em staging em ≤ 30 dias (prazo interno) e o canário do contacto desaparece de todas as lojas de dados; os backups não são reescritos e o *erasure ledger* é reaplicado num restauro de teste.
- [ ] O *job* de purga cobre 100% das tabelas com dados pessoais do inventário (§7.1); nenhuma classe fiscal é purgada sem `fiscal_retention_years` definido.
- [ ] Rotação de Meta App Secret, chave do facilitador, pepper do HMAC, tokens de cliente e chaves LLM ensaiada em staging sem perda de eventos nem 5xx.
- [ ] Relatório de red-team e revisão independente concluídos com 0 achados críticos ou altos abertos antes do Piloto com dados reais.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-065 | Modelo de ameaças STRIDE e matriz requisito → controlo → teste | chore | M | P0 | — |
| KAM-066 | Suite de isolamento cruzado ponta a ponta (tenant e contacto) no CI | feature | M | P0 | KAM-004, KAM-028 |
| KAM-067 | Supply chain: SBOM, digests, cosign, lockfiles e bloqueio de licenças | feature | M | P0 | KAM-002 |
| KAM-068 | Política de logs sem conteúdo e redacção de PII | feature | S | P0 | KAM-002 |
| KAM-069 | Inventário de subprocessadores e gate de transferência com `apd_ref` | feature | M | P0 | KAM-008, ext:KAM-105 |
| KAM-070 | Direitos do titular: acesso, correcção, eliminação e exportação | feature | L | P1 | KAM-008, KAM-005, KAM-006, KAM-022, KAM-026 |
| KAM-071 | Retenção e purga por classe de dados | feature | M | P1 | KAM-026, KAM-011, KAM-020, KAM-070 |
| KAM-072 | Rotação de chaves Meta, facilitador e HMAC | feature | M | P1 | KAM-010, KAM-013, KAM-056, KAM-008 |
| KAM-073 | Red-team do AGR: injecção directa e indirecta, exfiltração | chore | M | P0 | KAM-033 |
| KAM-074 | Revisão de segurança independente pré-Piloto | chore | M | P0 | KAM-066, KAM-073, KAM-065 |
| KAM-112 | Minimização de PII antes do LLM | feature | M | P0 | KAM-030, KAM-008, KAM-068 |
| KAM-113 | Resposta a incidentes e notificação de violação de dados | chore | S | P0 | KAM-065, KAM-068 |
| KAM-149 | `docs/seguranca/validar.py` aborta com a contagem do canon fixada | fix | S | P1 | KAM-065 |

---

## KAM-065 — Modelo de ameaças STRIDE e matriz requisito → controlo → teste

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-074, KAM-113, KAM-149 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§4, §8.5, §8.7, §9, §12, §13), `../docs/tecnica/00_Arquitectura_Solucao.md` (§4, §8, §13.3), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisitos 1–25), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§10.4) |

### Contexto
`../docs/tecnica/08` §4.2 faz o STRIDE de 9 componentes (GWY, CHR, AGR, TLS, PAY, HND, COM, MED, LLM) e a §9 só define C-01 a C-04 e C-09; faltam REG, IDX, EVT, TEN, STO, OBS e GOV, e os IDs C-05 a C-08. Sem uma matriz que ligue cada requisito (Lei 22/11, Meta, BNA, AGT, consumidor, ADR) a um controlo, a um ticket e a um teste, a conformidade fica por intenção. O ticket é um *chore*: o resultado são documentos revistos e uma matriz legível por máquina.

### Objectivo
Produzir o modelo de ameaças completo do Piloto e a matriz de conformidade rastreável, de modo que cada controlo tenha dono, ticket e teste, e cada lacuna e cada item NÃO VERIFICADO fique explícito com critério de saída.

### Critérios de Aceitação
- [ ] `docs/seguranca/ameacas_stride.md` cobre os 16 componentes do Piloto (GWY, CHR, AGR, REG, TLS, HND, COM, PAY, IDX, EVT, TEN, LLM, MED, STO, OBS, GOV) × S/T/R/I/D/E = 96 células; cada célula nomeia um controlo e o teste (ou o ticket que o cria), ou um risco aceite com dono e data.
- [x] O documento inclui o diagrama das 4 fronteiras de confiança (não confiável, borda, núcleo, equipa) e marca catálogo da PME, OCR de fotos e transcrição de voz como dados não confiáveis.
- [x] `docs/seguranca/matriz_conformidade.csv` tem uma linha por requisito: os 25 de `../docs/tecnica/evidencia/E3`/`../docs/tecnica/08` §8.5, as 8 regras Meta de §8.7, G-1..G-6, C-01..C-09 (os IDs C-05..C-08 são definidos e registados) e os alvos de §14; mínimo 54 linhas.
- [x] Cada linha tem `id, origem, controlo, componente, ticket, teste_id, dono, fase, estado_evidencia (CONFIRMADO/INDÍCIO/NÃO VERIFICADO), juridico (sim/não), criterio_saida`; o *lint* de CI (gate 3) falha se um `KAM-NNN` ou `ADR-NNN` citado não existir.
- [ ] 0 linhas sem ticket: as lacunas (requisito sem ticket) ficam numa lista `lacunas.md` com proposta de ticket novo e dono, sem editar o `INDICE.md`.
- [ ] Toda a linha NÃO VERIFICADO ou «(a confirmar por parecer)» tem `criterio_saida` (pergunta E3-N ou N1–N5 de `../docs/tecnica/08` §13, spike ou *flag* desligada) e a pergunta ligada ao pacote do KAM-104.
- [x] A DPIA simplificada é alargada de 2 para ≥ 6 operações (histórico de chat, áudio, localização, `assistant_queries`, embeddings, backups) com probabilidade, impacto, mitigação e risco residual.
- [ ] O Responsável de Segurança assina o registo de riscos residuais e o Arquitecto e o Responsável de Produto aprovam; a revisão fica datada e versionada.

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-065-modelo-de-ameacas-stride`. **Seis caixas marcadas, sete vazias**
(quatro de oito critérios; duas de cinco do DoD) — cada uma com uma linha aqui. Os números
reproduzem-se, da raiz, com `python docs/seguranca/validar.py .`, que termina em «OK: 0 erros»; o
script **não está no CI**.

| CA | Estado | Evidência |
|---|---|---|
| 1 — 96 células, cada uma com controlo e teste ou ticket, ou risco aceite | **parcial** | **96 células únicas de 96** (16 componentes × 6); **0** sem teste nem ticket existente; 13 citam um `ficheiro::teste` que existe; 449 citações `KAM-NNN CA n` cabem no número de critérios do bloco. **Mas em 25 células uma parte do controlo que `../docs/tecnica/08` descreve não é critério de ticket nenhum** — remetem para uma lacuna `L-NN` — e nenhum risco foi aceite, porque ninguém o pode aceitar aqui. À letra, «o ticket que o cria» não existe para essas partes. A revisão adversarial encontrou 11 citações que não sustentavam o controlo por inteiro; foram corrigidas, e mais de metade das 449 não foi lida por ninguém além de quem as escreveu. **Decisão devolvida:** criar os tickets das 32 lacunas, ou aceitar os riscos por escrito |
| 2 — diagrama das 4 fronteiras; catálogo, OCR e transcrição de voz não confiáveis | **satisfeito** | `../docs/seguranca/ameacas_stride.md` §3: um `flowchart` com 4 subgrafos (zonas 0 a 3), 26 nós e 31 arestas; os três dados aparecem como nós rotulados «DADO NAO CONFIAVEL» e numa tabela. Passou `mermaid.parse` e `mermaid.render` (mermaid 11, num navegador) — **medição feita à mão, que o script não reproduz**; a segunda ronda da revisão recontou nós e arestas |
| 3 — uma linha por requisito; ≥ 54; C-05..C-08 definidos e registados | **satisfeito** | **68 linhas**: 25 `E3-`, 8 `META-`, 6 `G-`, 9 `C-`, 6 `A-` (54) e 14 `K-` de controlos que já existem. C-05 a C-08 definidos como *proposta* (ADR-015, ADR-010, ADR-008, ADR-011) em `ameacas_stride.md` §6 e na matriz. **Ressalva:** o registo é em `docs/seguranca/`; a tabela de `../docs/tecnica/08` §9 continua sem eles, porque este ticket não edita `docs/tecnica/` (lacuna L-23) |
| 4 — as 11 colunas; o gate 3 falha com `KAM-NNN` ou `ADR-NNN` inexistente | **satisfeito** | 13 colunas constantes, as 11 do critério primeiro e pela ordem dele, 0 células vazias. Gate 3: com a matriz no índice, «conforme — 9039 referências em 303 ficheiros»; com uma linha semeada (não commitada) a citar um ticket e um ADR inexistentes — os números 999 e 099, que aqui não se escrevem por extenso porque o gate os apanharia neste ficheiro —, **saída 1** e «`docs/seguranca/matriz_conformidade.csv:70: … nao existe em specs/INDICE.md §4`», mais a do ADR. **O que o gate 3 não vê:** colunas, células vazias, caminhos e nomes de teste — isso é o `validar.py`, fora do CI (L-20). O Handoff pede «lint da matriz em CI» e isso não foi entregue: este ticket não pôde tocar em `tools/` nem em `.github/` |
| 5 — 0 linhas sem ticket; lacunas em `lacunas.md` | **parcial** | **14 linhas** têm uma lacuna na coluna `ticket`, e **2** (E3-18 e E3-23) não têm ticket existente nenhum; 7 têm `teste_id` só com lacuna. A letra pede 0. A segunda metade cumpre-se: `../docs/seguranca/lacunas.md` tem 32 lacunas, cada uma com proposta e dono, e o `INDICE.md` não foi editado. **Decisão devolvida:** criar os tickets, ou emendar o critério |
| 6 — toda a linha NÃO VERIFICADO ou jurídica com critério de saída ligado ao KAM-104 | **parcial** | 52 linhas exigem critério de saída e as 52 têm texto. **Três — META-2, META-4 e META-8 — não têm pergunta, spike nem *flag***: a regra da Meta está lida e não há pergunta em aberto; dizem-no, e a revalidação da política passou a lacuna (L-31). A revisão apanhou-as: a primeira versão passava no validador pela palavra «perguntas». O pacote do KAM-104 ainda não existe, e cinco perguntas novas (Q-A a Q-E) estão fora da sua lista de origem (L-24) |
| 7 — DPIA de 2 para ≥ 6 operações, com probabilidade, impacto, mitigação e residual | **satisfeito** | **12 operações** em `../docs/seguranca/dpia_simplificada.md`, as seis que o critério nomeia incluídas, cada uma com os quatro campos. O cabeçalho diz que é rascunho para o jurista. A escala é de três níveis e está marcada *proposta*. Duas operações têm mitigação **sem ticket** (localização, L-26; `assistant_queries`, que nenhum ticket cria, L-27) |
| 8 — registo de riscos assinado; Arquitecto e Produto aprovam | **não satisfeito** | Nenhuma assinatura. `../docs/seguranca/riscos_residuais.md` tem 25 riscos, todos «por decidir», e a tabela de aceitação vazia. Exige pessoas |
| DoD — todos os CA satisfeitos | **não satisfeito** | Quatro em aberto: 1, 5, 6 e 8 |
| DoD — dois revisores (Segurança e Arquitectura); aprovação do Produto | **não satisfeito** | Zero revisores humanos. A revisão adversarial (`../docs/analises/ANALISE-06-KAM-065-modelo-de-ameacas-stride.md`, 40 achados em duas rondas) é evidência, não é um revisor. A «revisão por pares do STRIDE» dos Testes Requeridos também não aconteceu |
| DoD — nenhum NÃO VERIFICADO tratado como facto; cada um com critério de saída | **satisfeito** | A segunda ronda confrontou as 68 linhas e 40 ocorrências nos `.md` com E1 a E5 e `../docs/tecnica/08`: **uma promoção** (C-05) e quatro NÃO VERIFICADO sem saída, todos corrigidos; sete linhas desceram de estado por terem sido lidas por sumarizador. **Limite:** as correcções foram conferidas pelo validador e não por uma terceira ronda |
| DoD — versionados (SemVer); ligados ao `INDICE` por referência | **parcial** | Os quatro `.md` estão em 0.1.0 e citam `specs/INDICE.md` §4 no cabeçalho, sem o editar. Mas a frase lê-se de duas maneiras, e na outra não se cumpre: nenhum índice aponta para `docs/seguranca/` (L-25). A matriz, sendo CSV, não tem versão própria |
| DoD — nenhum dado pessoal real | **satisfeito** | O validador não encontra padrões de telefone nos cinco artefactos nem na análise; gate 9 limpo sobre 303 ficheiros |

#### O que mudou face ao que o ticket supunha

O ticket é anterior a haver código. A matriz e o STRIDE dizem, para cada controlo, se **existe e
está testado** (caminho e nome do teste), **existe sem teste**, **está num PR por fundir**, **não
existe** (com o ticket) ou **não tem ticket**. Em `main`, hoje: 9 linhas da matriz
`existe-testado`, 2 `existe-nao-testado`, 11 `parcial`, 41 `nao-existe`, 5 `sem-ticket`. A RLS do
KAM-004 consta como implementada no PR #16 e por fundir, sem citar testes que `main` não tem.

#### Decisões tomadas sem dono, para poderem ser invertidas

- **C-05 a C-08** foram atribuídos aos quatro ADR que a §9 do `08` não cobria. Outra escolha
  razoável era dá-los à defesa do consumidor.
- **Duas colunas a mais** na matriz (`estado_controlo`, `requisito`) e uma série `K-`.
- **`estado_evidencia` é o mais fraco** das afirmações de que a linha depende, e texto de lei ou
  de termos lido por sumarizador automático é INDÍCIO — o que desce sete linhas abaixo do que E1 e
  E3 escrevem.
- **Os donos** das séries `META`, `G`, `A`, `K` e de C-05 a C-08 são *proposta*.
- **A escala de risco** é de três níveis, sem números.

### Detalhes Técnicos
- **Componentes:** GOV, todos. Saídas em `docs/seguranca/`: `ameacas_stride.md`, `matriz_conformidade.csv`, `lacunas.md`, `dpia_simplificada.md`, `riscos_residuais.md`.
- **Fonte das células já feitas:** a tabela §4.2 de `../docs/tecnica/08` (9 componentes) é o ponto de partida; os 7 novos (REG, IDX, EVT, TEN, STO, OBS, GOV) são trabalho novo (p. ex. IDX: lista vazia por filtro pós-ANN e fuga cruzada; EVT: PII em eventos e *replay*; STO: URLs de media; OBS: traces com conteúdo; TEN: entitlements forjados).
- **Donos** do vocabulário de §8.5: SEG, AP, RP, PRIV, OPS, T&S, ADV.
- A matriz é a fonte única da secção de conformidade do relatório de KAM-074; manter `controlo` por referência ao ticket, nunca copiar texto.
- Não é parecer jurídico: as colunas `juridico=sim` ficam abertas até ao KAM-104.

### Testes Requeridos
- Revisão por pares do STRIDE (Arquitecto + Segurança) com a lista de verificação «célula com controlo ou risco aceite».
- Lint automático da matriz: IDs existentes, `teste_id` com ficheiro ou ticket, sem células vazias.
- Verificação cruzada: cada ADR relevante (004, 008, 010, 013, 015) aparece em ≥ 1 linha.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Revisão por dois revisores (Segurança e Arquitectura); aprovação do Responsável de Produto nos riscos aceites.
- [x] Nenhum NÃO VERIFICADO tratado como facto; cada um com critério de saída.
- [ ] Documentos versionados (SemVer) e ligados ao `INDICE` por referência (sem o editar).
- [x] Privacidade: nenhum dado pessoal real nos anexos e exemplos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-065 da KAMBÁ (chore). Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-065),
docs/tecnica/08 (§4, §8.5, §8.7, §9, §12, §13) e docs/tecnica/evidencia/E3 (requisitos 1-25).
Objectivo: ameacas_stride.md (16 componentes x 6 categorias), matriz_conformidade.csv (>= 54 linhas, com id, origem,
controlo, componente, ticket, teste_id, dono, fase, estado_evidencia, juridico, criterio_saida), lacunas.md,
DPIA alargada (>= 6 operações) e riscos_residuais.md.
- Não inventes factos jurídicos: o que for NÃO VERIFICADO leva critério de saída e a pergunta ao advogado (KAM-104).
- Lacunas => proposta de ticket novo; não edites INDICE.md.
Entrega: documentos + lint da matriz em CI. PR com o template (§7).
```

---

## KAM-066 — Suite de isolamento cruzado ponta a ponta (tenant e contacto) no CI

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-004, KAM-028 |
| Bloqueia | KAM-074 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.1–§3.8, §14), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.1, §2.2, §2.9), `specs/01_Engineering_Standards_e_Handoff.md` (§4 gate 6), ADR-015 |

### Contexto
O isolamento entre tenants é o requisito de segurança de maior peso do Piloto (`../docs/tecnica/evidencia/E4` §5): o Mercur corrigiu falhas de autorização entre vendedores a 2026-10-08 e o Chatwoot tem um *Agent Bot* global com `account_id` nulo. A defesa é em camadas (CHR, estado, TLS, repositório, RLS `FORCE`, storage) e **nenhuma é suficiente isolada**; a suite cruzada é o que impede a regressão. O gate 6 do pipeline exige também que o contacto X não leia as encomendas do contacto Y. A lista X-01..X-11 de `../docs/tecnica/08` §3.7 omite o X-07 (reservado aqui).

### Objectivo
Construir o *harness* de testes cruzados com canários que enumera automaticamente rotas, tools, *jobs* e consumidores, executa o ataque autenticado como A contra B (e como o contacto X contra Y) e falha o *build* se o canário de B aparecer em respostas, erros, logs ou traces.

### Critérios de Aceitação
- [ ] O *seed* cria os tenants A e B e os contactos X e Y (ambos em A) com um canário único em cada tabela com `tenant_id`, em cada objecto de storage (`t/{tenant_id}/`) e em cada conversa.
- [ ] A enumeração automática cobre 100% das rotas, tools do REG, *jobs* BullMQ e consumidores EVT; um item enumerado sem caso registado falha o CI (não existe «sem teste» silencioso).
- [ ] X-01: para cada rota, A usa IDs de B (IDOR) e recebe 403/404 uniformes sem canário; X-02: cada tool invocada com estado de A e argumentos que referem entidades de B não devolve canário.
- [ ] X-03: sessão `kamba_app` com `app.tenant_id=A` faz `SELECT *` em todas as tabelas com `tenant_id` e 0 linhas contêm o canário de B; X-04: sem `SET LOCAL` todas as tabelas devolvem 0 linhas.
- [ ] X-05: uma consulta a `pg_class` × `pg_policy` falha se alguma tabela com `tenant_id` não tem RLS `FORCE`; `kamba_app` é `NOBYPASSRLS`; as funções `SECURITY DEFINER` são exactamente as da lista aprovada (inclui `append_payment_event`); as vistas têm `security_invoker = true`.
- [ ] Isolamento de contacto: o contacto X, com o estado de X, não lê encomendas, consentimentos nem `price_quotes` de Y (0 linhas, 3 tools de leitura testadas).
- [ ] O *pooling* em modo transacção não vaza contexto: 100 transacções intercaladas de A e B pelo *pool* não devolvem linhas cruzadas; um *lint* falha o *build* se existir `SET app.tenant_id` de sessão em vez de `SET LOCAL`.
- [ ] Teste de mutação: remover o `WHERE tenant_id` de uma função de repositório torna X-02/X-03 vermelhos; remover uma política torna X-05 vermelho; uma tool com parâmetro `tenant|merchant|seller|account` falha o *lint*.
- [ ] O oráculo varre também logs e traces OTel de cada caso; a suite completa corre em ≤ 10 min no CI (proposta).

### Detalhes Técnicos
- **Componentes:** TLS, COM, IDX, STO, HND, todos os que têm `tenant_id`. Módulos `security/isolation/{seed,enumerate,oracle,cases}/`; *runner* no gate 6 do CI.
- **API de registo:** `registerCase({id, camada, enumeravel, fn})`; os tickets que criam novas superfícies acrescentam o seu caso na própria DoD: X-06 vectores (KAM-061), X-08 storage (KAM-011/KAM-020), X-09 injecção cruzada com ≥ 30 prompts PT-AO (KAM-073), X-10 cross-seller/cross-account (KAM-042, KAM-019), X-11 logs (KAM-068).
- **Canário:** `CANARY-{tenant}-{tabela}-{uuid}`; o oráculo procura-o em corpo, cabeçalhos, mensagens de erro, logs e *spans*.
- Pré-requisito de que a suite não substitui: o repositório base injecta `WHERE tenant_id` por construção (`../docs/tecnica/08` §3.1).
- Reservar ID X-07 e documentar a lacuna da lista original no PR.

### Testes Requeridos
- Os próprios casos X-01..X-06, X-08..X-11 (os que têm superfície já existente no commit) e os testes de mutação como testes da suite.
- Teste de meta: um tenant C novo, criado no CI, é apanhado pela enumeração sem alterar o código da suite.
- Desempenho: tempo total da suite; relatório anexado.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Isolamento de tenant e de contacto: a suite é o próprio critério; falha o *build* (gate 6).
- [ ] Privacidade: *seed* e canários sintéticos; nenhum dado real.
- [ ] Sem segredos: o *seed* não usa credenciais reais; papéis de teste criados em contentor efémero.
- [ ] Documentação: guia «como acrescentar um caso» no README da suite; lacuna X-07 registada.
- [ ] Cobertura de enumeração 100%; dois revisores (P0 de isolamento).

### Handoff para Claude Code

```text
És o executor do ticket KAM-066 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-066),
docs/tecnica/08 §3 (3.1-3.8) e §14, docs/tecnica/03 §5.5 e ADR-015.
Objectivo: harness de testes cruzados com canários por tabela/objecto, enumeração automática de rotas, tools do REG,
jobs e consumidores, casos X-01..X-06 e X-08..X-11 (registerCase), isolamento de contacto (X lê Y => 0 linhas),
teste de pooling com SET LOCAL e testes de mutação (remover WHERE/policy => build vermelho).
- tenant_id vem do estado, nunca de texto; kamba_app NOBYPASSRLS; SECURITY DEFINER só na lista aprovada.
- Um item enumerado sem caso registado falha o CI.
Não expandas escopo: os casos X-06/X-08/X-09/X-10/X-11 de superfícies novas são adicionados pelos seus tickets.
Testes: a própria suite + mutação + tenant C novo. PR com o template (§7).
```

---

## KAM-067 — Supply chain: SBOM, digests, cosign, lockfiles e bloqueio de licenças

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.5, §4.8), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§1, §2.1–§2.7, §4, §5), `specs/01_Engineering_Standards_e_Handoff.md` (§3 DoD «Dependências», §4 gates 11 e 14), ADR-002, ADR-005, ADR-014 |

### Contexto
Incidente de referência: as versões 1.82.7 e 1.82.8 do LiteLLM no PyPI, publicadas com *malware* a 2026-03-24 (CONFIRMADO, `../docs/tecnica/evidencia/E4` §2.7); o proxy guarda as chaves de todos os provedores LLM. A remediação oficial é ≥ 1.83.0 com imagens assinadas por cosign. As licenças também são superfície de risco: Medusa (EE desde 2026-08-11), Chatwoot (`enterprise/`), n8n (SUL), Typebot (FSL), Dify (multi-tenant vedado), LangGraph Server (Elastic-2.0), MinIO (arquivado) e Meilisearch (BUSL nos módulos EE). KAM-002 já traz SBOM e licenças como *gate* base; este ticket acrescenta o que o torna fail-closed e específico da KAMBÁ.

### Objectivo
Impor imagens por digest com verificação cosign, SBOM CycloneDX por imagem e *release*, lockfiles com *hash*, ausência de instalação em runtime, lista de bloqueio de pacotes e licenças, desactivação verificável das funções Enterprise e quarentena de versões novas.

### Critérios de Aceitação
- [x] Um *lint* de Compose/Dockerfile falha o *build* se algum `image:` ou `FROM` usar *tag* sem `@sha256:`; PR semeado com `image: litellm:latest` fica vermelho.
- [ ] Onde há assinatura publicada (LiteLLM ≥ 1.83.0) o CI e o deploy executam `cosign verify`; a falha bloqueia a publicação (gate 14); onde não há, a linha da imagem regista `cosign: n/a` com compensação (digest + SBOM + varrimento).
- [ ] Cada imagem tem SBOM CycloneDX gerado no CI, guardado com o *release* e referenciado no manifesto da *tag*; um *release* sem SBOM falha (gate 18).
- [ ] Python usa `pip --require-hashes`; Node usa `pnpm-lock`/`package-lock` com `npm ci --ignore-scripts`; um *grep* de CI falha se existir `pip install` ou `npm i` em entrypoints ou *scripts* de arranque; os contentores correm com sistema de ficheiros só de leitura, excepto volumes declarados.
- [x] Lista de bloqueio com 5 casos semeados que falham o CI: `langgraph-api`, `langgraph-runtime-inmem`, MinIO (imagem ou pacote), n8n/Typebot/Dify numa superfície exposta a tenants, e `litellm` < 1.83.0 (incluindo 1.82.7 e 1.82.8 nominalmente).
- [x] Porta de licenças: lista permitida de SPDX; licenças AGPL, BUSL, Elastic, SSPL, FSL e SUL em dependências de runtime exigem excepção registada em ADR; `licencas.yaml` regista componente, versão, licença e data de verificação (mitigação de `../docs/tecnica/evidencia/E4` §5).
- [ ] Um teste de configuração falha se as *flags* Enterprise do Medusa (`rbac`, `auth-oidc`, `policies`) estiverem activas, se o Chatwoot carregar código `enterprise/` ou se módulos EE do Meilisearch estiverem activos.
- [ ] O Renovate aplica quarentena ≥ 7 dias a versões novas (proposta) com excepção para correcções de segurança marcadas e revistas; o CI não usa chaves estáticas (OIDC) e o *scan* de segredos está limpo.
- [x] Cada serviço declara a sua lista de *egress* (negado por omissão); um *lint* falha se faltar; a aplicação na rede é de KAM-076.

### Detalhes Técnicos
- **Componentes:** OBS, todos. Módulos `ci/supply-chain/{lint_images,verify_cosign,sbom,licenses,blocklist}.sh|py`, `licencas.yaml`, `renovate.json`.
- **Âmbito face a KAM-002:** se KAM-002 já gera SBOM e varre licenças, este ticket reutiliza-os e acrescenta digest, cosign, bloqueio, EE flags e quarentena (sem duplicar passos).
- **Fixar o conhecido:** PostgreSQL 18.6, `pgvector` 0.8.7, LiteLLM ≥ 1.83.0 por digest (fixar versão e digest exactos na altura; não escritos aqui), Hono 4.x (não o RC 5), SeaweedFS ou S3 gerido (nunca MinIO).
- Redis/Valkey: a licença do Redis é a decisão D12; até lá, a lista de licenças marca-o como pendente de decisão e não como aprovado.
- O LiteLLM corre em rede isolada, sem `pip install` na construção e com rotação de chaves (KAM-072).
- Nada é activo em produção sem digest registado no manifesto do *release*.

### Testes Requeridos
- Cada regra de bloqueio com um PR semeado que falha e um que passa (positivo e negativo).
- Verificação cosign com uma imagem de teste assinada e uma adulterada.
- Teste de configuração das *flags* EE; teste de que o SBOM lista todas as dependências de uma imagem de referência.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] Dependências: versões fixadas por lockfile com *hash* ou digest; licenças permitidas; lista de bloqueio activa (DoD de domínio).
- [x] Sem segredos: *scan* de segredos limpo; CI por OIDC.
- [x] Documentação: `licencas.yaml` e guia de excepções; decisão D12 registada como pendente.
- [ ] Observabilidade: relatório de imagens/SBOM por *release*; alerta de CVE crítico.
- [ ] Dois revisores (P0 de segurança).

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-067-supply-chain` (PR #21). **Sete caixas marcadas, oito vazias**
(quatro de nove critérios; três de seis do DoD) — cada uma com uma linha aqui. O que existia antes
deste ticket, critério a critério, e a revisão adversarial que reprovou a primeira versão estão em
`../docs/analises/ANALISE-10-KAM-067-supply-chain.md`; as regras e os limites em
`../docs/supply-chain.md`. Tudo se reproduz com `make supply-chain` (dentro do `make ci-11`).

| CA | Estado | Evidência |
|---|---|---|
| 1 — *lint* de `image:`/`FROM` por *digest*; PR semeado com `image: litellm:latest` vermelho | **satisfeito** | `tools/supply_chain/imagens.py`: 9 referências a 4 imagens, todas com `@sha256:` e todas no inventário `ci/supply-chain/imagens.yaml` (*digests* lidos da fonte a 2026-10-12). Lê compose em qualquer forma que fale de `services:`, Dockerfile, workflows, `.env*` e a constante de `db/gate_bd.py`. **PR #26** (*digest* retirado): gate 11 vermelho pela regra `imagem-sem-digest`, os outros verdes. **PR #24** (`image: litellm:latest`): vermelho — **mas pela lista de bloqueio, no `bootstrap`, antes de o *lint* de *digests* correr**; para esse caso a prova do *lint* é a mutação `imagem-litellm-latest` do canário, que corre no gate. **Limite:** um `--build-arg` ou uma variável na linha de comandos não estão em ficheiro nenhum (`supply-chain.md` §10) |
| 2 — `cosign verify` onde há assinatura; `cosign: n/a` com compensação onde não há | **não satisfeito** | Nunca correu `cosign`: não há registo, nem imagem com assinatura publicada no repositório, nem binário no *runner*. Existe a decisão (`tools/supply_chain/cosign.py`, com executor injectado nos testes) e a regra que obriga o LiteLLM a `cosign: verificar`. As quatro imagens estão em **`por_apurar`**, um terceiro estado que o critério não prevê: `n/a` afirmava que não há assinatura, e isso ninguém verificou (a etiqueta `.sig` dá `not found` — INDÍCIO). A compensação está a um terço: *digest* sim; SBOM e varrimento por imagem não |
| 3 — SBOM CycloneDX por imagem, guardado com o *release* | **não satisfeito** | Não há pipeline que construa ou publique imagens, nem *release* (KAM-078). O SBOM que existe é por serviço e por PR (KAM-002) |
| 4 — `--require-hashes`; `pnpm-lock` com `--ignore-scripts`; sem `pip install`/`npm i` em arranque; só de leitura | **parcial — por decidir** | As quatro cláusulas verificam-se: `tools/supply_chain/runtime.py`, 9 instalações de *build* todas do *lockfile*, 0 em arranque, 7 serviços com `read_only: true` (o `postgres` e a `queue` passaram a tê-lo; `ReadonlyRootfs=true` e `healthy` confirmados por execução em `postgres`, `queue`, `gwy` e `agr`). A regra apanhou uma linha do próprio `Makefile` (`pip install --upgrade pip`, sem *hash*), que saiu. **Não se marca por duas leituras:** a letra diz «`npm ci --ignore-scripts`» e o repositório usa `pnpm install --frozen-lockfile --ignore-scripts`; e «os contentores» de produção ainda não existem (KAM-076 CA4). **Decisão devolvida** a quem escreveu o critério |
| 5 — lista de bloqueio com 5 casos semeados que falham o CI | **satisfeito** | Trabalho do KAM-001, reutilizado sem duplicar: `tools/blocklist.yaml`, 14 *fixtures* de bloqueio e 4 de passagem, `test_blocklist.py::test_cada_fixture_e_bloqueada_com_o_adr_certo`, `test_versions.py::test_pin_abaixo_falha` (1.82.7 e 1.82.8 pelo nome). **PR #25**: os cinco casos semeados dão 7 achados e o CI vermelho. n8n, Typebot e Dify estão bloqueados em todo o lado, o que inclui as superfícies de tenants |
| 6 — *allowlist* SPDX; licenças proibidas só com excepção em ADR; `licencas.yaml` | **satisfeito** | *Allowlist* e negadas: `ci/licenses.yaml` (KAM-002). Novo: um *waiver* para licença proibida tem de citar um ADR **que exista** — `tools/sbom/tests/test_excepcao_em_adr.py`, 7 testes, as seis famílias do critério incluídas. `ci/supply-chain/licencas.yaml`: 20 componentes com componente, versão, licença e data de verificação, confrontados com a política, a lista de bloqueio, o repositório e o inventário. **Limite:** a regra aplica-se a todas as dependências, e não só às de *runtime* (mais estrito do que a letra); a licença do registo não é comparada com a lida do disco |
| 7 — teste de configuração das *flags* Enterprise | **não satisfeito** | Medusa, Chatwoot e Meilisearch não estão instalados, e os nomes das variáveis que activam as *flags* são NÃO VERIFICADOS. O que entrou é o registo do que tem de ficar desligado (campo `ee`, obrigatório para os cinco componentes com edição Enterprise). `../docs/ci.md` §7, lacuna 8, continua aberta |
| 8 — quarentena ≥ 7 dias no Renovate; CI sem chaves estáticas; *scan* limpo | **parcial** | A configuração está certa (KAM-001) e passou a estar **protegida**: `tools/supply_chain/renovate.py` falha se a quarentena ou o *automerge* mudarem, em qualquer profundidade, por *preset* ou por ficheiro-sombra; `ci_chaves.py` falha com qualquer uso do contexto de segredos. Gate 9 limpo sobre 413 ficheiros. **Mas o Renovate nunca abriu um PR neste repositório**: «aplica» não se observou. E «por OIDC» é uma declaração: nenhum passo se autentica em lado nenhum |
| 9 — lista de *egress* por serviço, negado por omissão; *lint* falha se faltar | **satisfeito** | `tools/supply_chain/egress.py`: 7 serviços, 7 declarações (`services/*/egress.yaml`, `infra/egress/*.yaml`), `por_omissao: negar`, 0 destinos — os serviços são o esqueleto do KAM-001. Falha se faltar, se permitir por omissão, se um destino não tiver nome, ou se houver declaração sem serviço. A aplicação na rede é do KAM-076, como o critério diz |
| DoD — todos os CA satisfeitos | **não satisfeito** | Cinco em aberto: 2, 3, 4, 7 e 8 |
| DoD — dependências por *lockfile* com *hash* ou *digest*; licenças permitidas; lista de bloqueio activa | **satisfeito** | `make lock-check` e `make supply-chain` verdes; gate 11 verde (licenças e lista de bloqueio); 4 imagens por *digest*. **Reserva:** as acções do GitHub estão por etiqueta (`@v5`), fora do que o DoD enumera |
| DoD — *scan* de segredos limpo; CI por OIDC | **satisfeito** | Gate 9 limpo; nenhuma referência ao cofre de segredos nos workflows, agora com regra que o impõe. **Reserva:** OIDC declarado e sem uso, como na linha do CA 8 |
| DoD — `licencas.yaml` e guia de excepções; D12 registada como pendente | **satisfeito** | `ci/supply-chain/licencas.yaml`; `../docs/supply-chain.md` §6.4; Redis e Valkey com `estado: pendente_de_decisao` e `decisao: D12`, e um teste que o afirma (`test_redis_e_valkey_estao_pendentes_e_nao_aprovados`) |
| DoD — relatório de imagens/SBOM por *release*; alerta de CVE crítico | **não satisfeito** | Não há *release* nem canal de alerta. O que existe é a linha de resumo do gate, por PR |
| DoD — dois revisores (P0 de segurança) | **não satisfeito** | Zero revisores humanos. A revisão adversarial (`ANALISE-10`: 3 bloqueantes, 7 maiores, 8 menores) é evidência, não é um revisor |

**Como se provou que as verificações mordem.** O canário corre no gate: copia o repositório, aplica
59 defeitos um de cada vez e exige vermelho pela regra esperada (59 em 59). A primeira versão tinha
33, todas vermelhas, e a revisão adversarial fez passar 78 mutações suas em 86 — os verificadores
casavam formas literais. As formas equivalentes estão hoje em
`tools/supply_chain/tests/test_revisao_adversarial.py`; corridos contra a primeira versão, esses
testes dão 112 falhas. **As 86 mutações da revisão não voltaram a correr como conjunto** depois das
correcções.

**Medido no CI** (PR #21, `97d2cc7`): os nove gates e o resumo verdes; o canário leva cerca de
9 s no *runner*. Sem job novo: `esperados` continua em 9.

### Handoff para Claude Code

```text
És o executor do ticket KAM-067 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-067),
docs/tecnica/08 §4.8, docs/tecnica/evidencia/E4 (§1, §2, §4, §5) e ADR-002/005/014.
Objectivo: lint de imagens por digest, cosign verify onde publicado, SBOM CycloneDX por imagem e release, lockfiles com
hash e sem instalação em runtime, lista de bloqueio (langgraph-api, langgraph-runtime-inmem, MinIO, n8n/Typebot/Dify em
superfícies de tenants, LiteLLM < 1.83.0), porta de licenças com licencas.yaml, teste das flags Enterprise
(Medusa rbac/auth-oidc/policies, Chatwoot enterprise/, Meilisearch EE) e quarentena de 7 dias no Renovate.
- Reutiliza o que KAM-002 já entrega (SBOM/licenças); não dupliques.
- Não escrevas digests nem versões concretas de memória: lê-os da fonte na altura.
Testes: PR semeado por regra (positivo/negativo), cosign assinado/adulterado, flags EE. PR com o template (§7).
```

---

## KAM-068 — Política de logs sem conteúdo e redacção de PII

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-002 |
| Bloqueia | KAM-112, KAM-113 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3, §14), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.3), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisitos 11, 14), ADR-010, ADR-018 |

### Contexto
Os logs são o vector mais comum de fuga de dados pessoais e a APD multou por falhas de medidas de segurança (Fast Digital Center, USD 112 000, CONFIRMADO). A regra do ADR-010 é «logs sem conteúdo»: formato JSON com *allowlist* de campos. Traces de LLM contêm conteúdo (necessário para depurar) e por isso não existem em `prod` no Piloto (sem Langfuse) e, em `staging`, só com dados sintéticos (`../docs/tecnica/09` §9).

### Objectivo
Implementar o *logger* tipado partilhado (TypeScript e Python) que só aceita campos da *allowlist*, a redacção de referências de pagamento e identificadores, o varrimento X-11 no CI e a amostragem semanal em `prod`.

### Critérios de Aceitação
- [x] A *allowlist* é exactamente `ts, level, svc, tenant_id, contact_hmac_prefix, turn_id, msg_id, wa_type, latency_ms, tool, outcome, error_code` (`../docs/tecnica/08` §7.3); um campo fora dela é um erro de compilação em TypeScript e, em Python, é removido com a métrica `log_field_rejected_total` (em modo de teste lança excepção).
- [x] Texto de mensagem, transcrição, telefone, morada e nome não existem como campos; erros são registados por `error_code` e classe, nunca pela mensagem livre da biblioteca (que pode conter *payloads*).
- [x] O varrimento X-11 sobre 1 000 *fixtures* com padrões de telefone (`+244 9XX XXX XXX`, `244 9…`, `9\d{8}`) e NIF produz 0 correspondências nos logs gerados; o padrão de NIF é parametrizável (formato a fixar com o contabilista; `../docs/tecnica/08` não o define).
- [ ] Referências de pagamento aparecem mascaradas (últimos 3 caracteres) e `provider_event_id` nunca em claro nos logs de PAY.
- [ ] Os *headers* de pedido e de callback são registados por allowlist; `Authorization`, `X-Signature`, `Cookie` e `webhook_token` nunca; um teste com cabeçalhos de segredo dá 0.
- [x] Nenhum serviço importa `console.log`/`print` fora do *logger* (lint de importações); o teste de arquitectura falha o *build*.
- [ ] A amostragem semanal em `prod` (100 linhas aleatórias por serviço) é automatizada e o resultado registado; o alvo «identificadores directos em logs = 0» é métrica de OBS.
- [x] A política de traces está escrita: sem traces de LLM em `prod` no Piloto; em `staging` só dados sintéticos; retenção de logs técnicos 30 dias.

### Detalhes Técnicos
- **Componentes:** OBS, todos. Pacote `libs/logger` (TS) e `libs/logger_py`; teste `security/logs/x11_scan`; regras de *lint* em `ci/lint/`.
- **Campo de contacto:** a *allowlist* de `../docs/tecnica/08` usa `contact_hmac_prefix`; se o desenho final de identidade (KAM-008) preferir `contact_id`, a alteração da lista é um PR revisto pelo Responsável de Segurança.
- Coordenar com o guarda de PII do `evt_emitir` (`../docs/tecnica/06` §6.1) e com o *lint* de eventos (§7.3): são controlos distintos, o logger não os substitui.
- Fases do tracing OTel: atributos com a mesma *allowlist*; o conteúdo de LLM só em ambientes sintéticos.
- Excepções: nenhuma sem ADR; um campo novo exige PR com justificação de finalidade.

### Testes Requeridos
- Unit: rejeição de campos fora da *allowlist* (TS e Python); mascaramento de referências.
- Varrimento X-11 sobre 1 000 *fixtures* e sobre os logs de uma execução ponta a ponta da suite cruzada.
- Arquitectura: sem `console.log`/`print` fora do *logger*.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] Privacidade: telefone nunca em claro em logs; contacto por identificador pseudónimo; logs sem conteúdo de mensagens.
- [x] Custo e observabilidade desde o código: logs JSON estruturados, métricas de rejeição.
- [x] Sem segredos nos logs; *scan* de segredos limpo.
- [x] Documentação da política e do processo de adicionar campos.
- [x] Cobertura do módulo de *logger* ≥ 90%.

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-068-logs-sem-conteudo` (PR #23). **Dez caixas marcadas, quatro vazias**
(cinco de oito critérios; cinco de seis do DoD) — cada uma com uma linha aqui. A política, os
limites e as medições estão em `../docs/logs.md`; a revisão adversarial, que reprovou a primeira
versão com dois achados maiores, em `../docs/analises/ANALISE-11-KAM-068-logs-sem-conteudo.md`. Os
números reproduzem-se com `make log-lint` (dentro do `make ci-2`), `make x11` (dentro do
`make ci-6`) e `python tools/log_policy/tests/mutacoes.py`.

| CA | Estado | Evidência |
|---|---|---|
| 1 — *allowlist* exacta; erro de compilação em TS; removido com métrica em Python | **satisfeito, com uma ressalva escrita** | A lista é a de `../docs/tecnica/08` §7.3 e está presa nos dois sentidos: os testes das duas linguagens leem o §7.3 e comparam, e `tools/log_policy/tests/test_x11.py` confere os três sítios onde está escrita. TS: 23 linhas `@ts-expect-error` em `packages/core-ts/tests/logger.test.ts` (literal, variável, objecto espalhado, `object`, `{}`, texto, campos reservados, tipos errados); o `tsc` do *gate* 2 falha se uma passar a compilar, e cinco mutações aos tipos são apanhadas. Em execução, nas duas linguagens: campo retirado e contado em `log_field_rejected_total:<motivo>` (952 rejeições nas 1 030 *fixtures*, iguais em Python e em TS); `KAMBA_LOG_ESTRITO=1` levanta sem escrever. **Ressalva:** um `any` desliga a verificação do compilador — tal como um objecto com chaves a mais atribuído primeiro a uma variável do tipo `CamposDeLog`; o campo é retirado em execução na mesma (`../docs/logs.md` §7.14) — e o modo estrito não está ligado em bateria nenhuma, porque os serviços ainda não têm chamadas de negócio (§3.1) |
| 2 — sem campos de conteúdo; erros por `error_code` e classe | **satisfeito** | `test_nao_ha_campo_de_conteudo`; vinte canários por todas as portas, nas duas linguagens, sem um na saída (`TestCanarios`, `canarios: …`); `excepcao` regista `código:Classe` e não lê mensagem, causa, pilha nem propriedades. A ponte de Python (`logging`, `warnings`, excepções por tratar em três sítios) e os ganchos de Node deixam passar só o nível, o nome do *logger* e a classe. **A primeira versão não cumpria isto nos serviços Node:** o Hono escrevia a mensagem de qualquer erro de tratador na consola (`ANALISE-11`, A1); corrigido com `app.onError` nos quatro serviços e dois testes por serviço |
| 3 — X-11 sobre 1 000 *fixtures* dá 0; NIF parametrizável | **satisfeito** | `make x11`, no *gate* 6 de cada PR: 1 000 *fixtures* (dez formatos de telefone, incluindo os três do critério; NIF; e mais oito classes) por onze rotas, mais 30 de forma; **0 achados** em 2 060 linhas (1 030 por linguagem) mais 14 300 da ponte; saída de Python e de TypeScript igual byte a byte (159 245 bytes). Controlo positivo: os padrões veem 100 de 100 telefones, NIF, e-mails, IBAN e `wamid` na entrada. O padrão do NIF é `make x11 X11_NIF='<regex>'` / `--nif-padrao`; sem ele a saída diz «PADRAO DE NIF NAO DEFINIDO» (`TestNifParametrizavel`). **O formato do NIF continua por definir** (`../docs/seguranca/lacunas.md`, Q-A): no CI os NIF das *fixtures* são apanhados pela sequência de dígitos e pela cadeia exacta do canário, não por um padrão próprio |
| 4 — referências mascaradas (últimos 3); `provider_event_id` nunca em claro em PAY | **parcial — caixa vazia; decisão devolvida** | Entregue: `mascarar_referencia` / `mascararReferencia` nas duas linguagens, com 14 vectores de paridade; e a metade negativa — uma referência e um `provider_event_id` nunca saem em claro, por nenhuma porta (vector «referencia de pagamento e provider_event_id»; classe `referencia` das *fixtures*). **Não entregue:** a referência não *aparece* em lado nenhum, mascarada ou não, porque a *allowlist* do CA1 é exacta e não tem campo para ela — `test_o_que_a_mascara_devolve_nao_cabe_em_campo_nenhum` prova-o. E não há *logs* de PAY: o componente não existe. Cumprir este critério pede um campo novo em `../docs/tecnica/08` §7.3, que o próprio ticket reserva ao **Responsável de Segurança** |
| 5 — cabeçalhos por *allowlist*; os de segredo nunca; teste dá 0 | **parcial — caixa vazia; decisão devolvida** | Entregue: `Authorization`, `X-Signature`, `Cookie` e `webhook_token` dão zero por qualquer porta, nas duas linguagens (`test_cabecalhos_com_segredo_dao_zero`, `canarios: cabecalhos com segredo dao zero`, e um vector de paridade). **Não entregue:** nenhum cabeçalho é registado, porque não há campo para cabeçalhos — é uma *allowlist* vazia, não a que o critério descreve. A mesma contradição com o CA1, e a mesma decisão devolvida |
| 6 — nenhum serviço usa `console.log`/`print` fora do *logger*; o teste falha o *build* | **satisfeito** | `make log-lint`, no *gate* 2: 21 ficheiros TS/JS e 15 Python lidos, 0 achados; canário com 29 negativas e 6 positivas. Um `console.log` em `services/gwy/src/app.ts` e um `print` no AGR, numa cópia, dão saída 1 com ficheiro, linha e regra (`TestRepositorio`); `test_cablagem.py` confere que o alvo está no `ci-2` com o canário. Os cinco serviços foram migrados. **A revisão mostrou oito evasões por descuido e uma expressão regular que escondia o resto do ficheiro** (`ANALISE-11`, A2); corrigidas, com regra e *fixture* negativa para cada uma. O que um *lint* não apanha está em `../docs/logs.md` §7.5 e §7.6 |
| 7 — amostragem semanal em `prod` automatizada e registada; métrica de OBS | **não satisfeito — caixa vazia** | Só a ferramenta: `python -m log_policy amostra` tira 100 linhas aleatórias por serviço, varre-as e acrescenta uma linha JSON ao registo (dez testes em `test_amostra_e_cli.py`). **Não há agendamento, nem `prod`, nem Loki de onde tirar os *logs*, nem pilha de métricas** onde o alvo seja métrica de OBS. Depende do KAM-079 e do KAM-080 |
| 8 — política de traces escrita | **satisfeito** | `../docs/logs.md` §9: sem traces de LLM em `prod` no Piloto; em `staging` só dados sintéticos; retenção de *logs* técnicos 30 dias (*proposta*; prazos legais a confirmar por parecer); cada regra com a sua fonte. Nenhuma está imposta por máquina, e o documento di-lo |

| DoD | Estado | Evidência |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não — caixa vazia** | CA4, CA5 e CA7, acima |
| Privacidade: telefone nunca em claro; contacto por identificador pseudónimo; sem conteúdo de mensagens | **satisfeito, dentro dos limites escritos** | X-11 e canários (CA2, CA3); o único campo de contacto é `contact_hmac_prefix`, e `turn_id`/`msg_id` recusam um `wamid` em claro (`../docs/logs.md` §2.1). **Limites:** texto passado de propósito a `snake_case`, um telefone dentro de um UUID válido, e o que uma dependência escreva por conta própria (§7.1, §7.3, §7.6). O `contact_hmac_prefix` ainda não tem quem o produza: é do KAM-008 |
| Custo e observabilidade desde o código: logs JSON estruturados, métricas de rejeição | **satisfeito** | Uma linha JSON por chamada, campos por ordem fixa; `log_field_rejected_total:<motivo>` e `log_write_failed_total`. São contadores em memória: **não há quem os recolha** até ao KAM-080 |
| Sem segredos nos logs; *scan* de segredos limpo | **satisfeito** | *Gate* 9 verde no PR; tokens (`EAA…`, `eyJ…`, portador) e cabeçalhos de segredo nos canários e nas *fixtures*, sem um na saída. Limite: um segredo só com letras tem a forma de um identificador (§7.2) |
| Documentação da política e do processo de adicionar campos | **satisfeito** | `../docs/logs.md` §1–§3 (política) e §5 (processo); `02_Dicionario_de_Dados_Canonico.md` §3.10 |
| Cobertura do módulo de *logger* ≥ 90% | **satisfeito** | Medida só sobre o módulo: Python 99% das linhas (`politica.py` e `ponte.py` a 100%); TypeScript `politica.ts` 100% e `index.ts` 98,97% (`../docs/logs.md` §8). No *gate* 4 o módulo está no estrato `critico` (mínimo 90%), agregado com o `tenant_guard` — o *gate* não impõe 90% ao módulo sozinho, e `ci/thresholds.yaml` di-lo |

**Contradição entre critérios, devolvida.** O CA1 fixa a *allowlist* em «exactamente» doze campos. O
CA4 e o CA5 pedem que referências de pagamento e cabeçalhos *apareçam* nos *logs*, e nenhum dos doze
os pode levar. Não se escolheu entre eles: ficou a lista exacta, que é o que `../docs/tecnica/08`
§7.3 e o ADR-010 dizem, e as duas caixas vazias. **Quem decide é o Responsável de Segurança** —
acrescentar um campo é o PR que o próprio ticket lhe reserva («Detalhes Técnicos»), pelo processo
de `../docs/logs.md` §5.

**Prova por mutação.** 185 mutações na lista, em cópia fora do repositório, com linha de base verde nos três corredores (Python, `node --test` e `tsc`); 0 sobreviventes, em duas execuções parciais e não numa só (`ANALISE-11`, §3.2 e §6). A revisão independente fez mais 76, das quais 18
sobreviveram à primeira versão; estão hoje na lista ou num teste (`ANALISE-11`, §3). Uma outra
revisão, recebida depois do merge, mostrou mais quatro sobreviventes e cinco lacunas, tratadas num
PR de seguimento (`ANALISE-11`, §6).

**Não feito, e dito:** o varrimento X-11 «sobre os logs de uma execução ponta a ponta da suite
cruzada» (Testes Requeridos) — essa suite é o KAM-066 e não existe; e os atributos de tracing OTel
com a mesma *allowlist* — não há tracing no repositório. Os desvios de localização (`libs/logger`
→ `packages/core-ts/src/logger`, `security/logs` → `tools/log_policy`) estão em `../docs/logs.md`
§10. A caixa de revisão por dois revisores do DoD genérico (`01_Engineering_Standards_e_Handoff.md`
§3) fica por cumprir: este ticket altera `ci/thresholds.yaml`, e uma revisão adversarial é
evidência, não é um revisor.

### Handoff para Claude Code

```text
És o executor do ticket KAM-068 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-068),
docs/tecnica/08 (§7.3, §14) e docs/tecnica/06 §7.3, e ADR-010.
Objectivo: logger tipado (TS e Python) com allowlist ts, level, svc, tenant_id, contact_hmac_prefix, turn_id, msg_id,
wa_type, latency_ms, tool, outcome, error_code; sem texto de mensagem, transcrição, telefone, morada ou nome;
erros por error_code; mascarar referências de pagamento; teste X-11 (telefone e NIF) no CI; proibir console.log/print.
- Campo fora da allowlist: erro de compilação (TS) / removido+métrica (Python).
- O padrão de NIF não está definido nos docs: torna-o configurável, não o inventes.
Não expandas escopo: guarda de PII dos eventos (KAM-005/007), traces de LLM (OBS).
Testes: unit, varrimento X-11 sobre 1.000 fixtures, arquitectura. PR com o template (§7).
```

---

## KAM-069 — Inventário de subprocessadores e gate de transferência com `apd_ref`

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-008, ext:KAM-105 |
| Bloqueia | KAM-030, KAM-033, KAM-036, KAM-049, KAM-063, KAM-087, KAM-109, KAM-110, KAM-120 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.4, §8.2, §8.3, §8.6), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§1.1, §2, requisitos 4, 5, 8, 9, 25), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-008, D1, D9, D12), ADR-008 |

### Contexto
A regra do ADR-008 é: nenhum dado pessoal de produção sai de Angola sem a notificação ou autorização da APD aplicável. A lista de países «adequados» é NÃO VERIFICADA (a APD não a publica) e as cláusulas-tipo da APD não foram encontradas: UE e África do Sul são **hipóteses** e os EUA provavelmente exigem autorização (INDÍCIO). O código nunca infere adequação a partir do país. O papel da KAMBÁ (subcontratada ou co-responsável) e quem notifica a APD são D9, ainda aberta. A saída da pendência é o procedimento APD do KAM-105 (decisão D1).

### Objectivo
Implementar o inventário de subprocessadores, a tabela `tenant_destinations` e a biblioteca `assertDestinationAllowed` (negado por omissão), o gate de go-live de tenant, o mapa de tratamentos gerado a partir do inventário e a auditoria de transferências.

### Critérios de Aceitação
- [ ] A tabela `tenant_destinations(tenant_id, provider, country, purpose, apd_ref, status)` existe com `UNIQUE (tenant_id, provider, country, purpose)`; `tenant_id` nulo significa destino global (infra); `status='autorizado'` exige `apd_ref` não nulo (`CHECK`); RLS `FORCE` com linhas globais legíveis.
- [ ] `assertDestinationAllowed(tenant, provider, purpose)` lança `TransferDenied` quando não há linha, quando o estado é `pendente`, `revogado` ou `negado`, ou quando a base está indisponível (falha fechada); 5 casos de teste, incluindo país `ZA`, `DE` e `US` com `pendente` (nenhuma adequação é inferida).
- [ ] Revogar um destino faz a chamada seguinte falhar em ≤ 60 s (TTL máximo da *cache* do gate, proposta).
- [ ] O gate é invocado antes de LLM, STT, embeddings, backups, CDN, observabilidade e e-mail/SMS; um teste de arquitectura falha se um cliente desses fornecedores for importado fora do módulo do gate.
- [ ] O inventário tem as 11 linhas de `../docs/tecnica/08` §8.3.2 (Meta, OpenAI, Google, Anthropic, Groq, alojamento, CDN/WAF, facilitador, software de facturação AGT, Doppler, e-mail/SMS) com função, dados pessoais, destino (hipótese) e estado do procedimento, e a lista pública de subprocessadores gerada dela.
- [ ] Por destino ficam arquivados contrato, retenção zero, não-treino e `apd_ref` (checklist do requisito 8); um destino `autorizado` sem checklist completo é rejeitado.
- [ ] A vista `v_transfer_audit` junta `llm_call_log` (KAM-030) a `tenant_destinations` e devolve 0 linhas de chamadas sem `autorizado` com `apd_ref` no momento da chamada (alvo «0 destinos sem `apd_ref`»).
- [ ] O gate de go-live recusa `onboarding → ativo` em `prod` se faltar destino autorizado para algum destino activo do tenant, o DPA aceite (KAM-090) ou a referência do mapa de tratamentos; ambientes sintéticos usam um ficheiro de configuração que `prod` não carrega (verificação no arranque).
- [ ] O mapa de tratamentos é um documento versionado gerado do inventário e de `tenant_destinations`; alterar uma linha altera a versão; as mudanças ficam no `audit_log` (KAM-012).

### Detalhes Técnicos
- **Componentes:** GOV, LLM, TEN. Módulos `libs/transfer_gate`, `migrations/NNNN_tenant_destinations.sql`, `services/gov/mapa_tratamentos/`.
- **Valores de `status`:** `pendente`, `autorizado`, `revogado`, `negado` são proposta (o doc só fixa «sem linha `autorizado` a chamada falha»); registar no PR. A coluna `purpose` vem de §8.3.1; o doc 08 §7.4 omite-a.
- **CDN/WAF e backups fora de Angola:** perguntas N1 e N2 de `../docs/tecnica/08` §13 abertas; entram como linhas `pendente` até parecer (D12). O Cloudflare terminar TLS dá-lhe acesso ao conteúdo: ou entra como subprocessador, ou o *path* de webhooks fica fora do proxy.
- **Pseudonimização:** continua a ser dado pessoal (N3, a confirmar por parecer); o gate não trata tokens como anonimização.
- A minimização antes do LLM (detector, tokenização, re-identificação na região aprovada, §7.4) é do AGR; este ticket fornece o gate que ela consulta (ver problemas do backlog).
- Enquanto KAM-105 não entrega `apd_ref`, todas as linhas estão `pendente` e só correm dados sintéticos.

### Testes Requeridos
- Unit: matriz de estados × países × fornecedores; falha fechada em erro de base.
- Integração: gate no gateway LLM com *mock* de fornecedor (contador de chamadas); revogação e *cache*.
- Arquitectura: importações de clientes externos; vista `v_transfer_audit`.
- Go-live: tenant sem DPA, sem destino ou sem mapa não activa; tenant completo activa.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Privacidade (ADR-008): nenhum dado pessoal sai de Angola fora de um destino registado com `apd_ref`.
- [ ] Isolamento: RLS `FORCE` e caso na suite cruzada.
- [ ] Sem segredos nem dados pessoais no inventário; evidência arquivada por destino.
- [ ] Migração reversível; alterações no `audit_log`; dois revisores (P0 de privacidade).
- [ ] Itens NÃO VERIFICADOS (países adequados, cláusulas-tipo, papel D9) com critério de saída: parecer ou resposta da APD.

### Handoff para Claude Code

```text
És o executor do ticket KAM-069 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-069),
docs/tecnica/08 (§7.4, §8.2, §8.3, §8.6), docs/tecnica/evidencia/E3 (§2, requisitos 4, 5, 8, 9, 25) e ADR-008.
Objectivo: tenant_destinations + assertDestinationAllowed (negado por omissão, falha fechada), inventário de
subprocessadores (11 linhas de §8.3.2), v_transfer_audit, gate de go-live de tenant e mapa de tratamentos gerado.
- Nunca infiras 'país adequado'; só status 'autorizado' com apd_ref liberta a chamada.
- Sem linha ou erro da base => TransferDenied. Destinos pendentes até KAM-105 => só dados sintéticos.
- Papel da KAMBÁ (D9) e CDN/backups (N1/N2) são NÃO VERIFICADOS: ficam como linhas 'pendente' com pergunta ao advogado.
Não expandas escopo: pipeline de minimização (AGR), DPA (KAM-090), procedimento APD em si (KAM-105).
Testes: unit, integração com mock, arquitectura, go-live. PR com o template (§7).
```

---

## KAM-070 — Direitos do titular: acesso, correcção, eliminação e exportação

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-008, KAM-005, KAM-006, KAM-022, KAM-026 |
| Bloqueia | KAM-071, KAM-098 |
| Responsável sugerido | Responsável de Privacidade (PRIV) |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.2, §8.1, §8.4, §11), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§5, §7.2, §7.6), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.3), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§1, requisito 13), ADR-010 |

### Contexto
A Lei 22/11 reconhece informação (Art. 25.º), acesso (26.º), oposição (27.º) e rectificação/eliminação (28.º), tudo CONFIRMADO nos artigos; o prazo legal de 60 dias úteis é INDÍCIO, e o interno é de 30 dias (requisito 13). O apagamento tem de coexistir com o *ledger* imutável e com a retenção fiscal: o `payment_events` não contém dado pessoal directo (só `contact_id` aleatório), pelo que apagar a identidade no cofre torna o `contact_id` um órfão irreversível (`../docs/tecnica/06` §7.6). Quem executa (PME responsável ou KAMBÁ subcontratada) depende de D9, ainda aberta. As variantes do esquema de identidade em `../docs/tecnica/03` §5.3 (`bsuid_hmac`, `contact_endpoints`), `../docs/tecnica/06` §7.2 (cofre com `dek_id`) e `../docs/tecnica/08` §7.2 (`contact_hmac`) ainda não convergiram.

### Objectivo
Implementar o fluxo de pedido do titular pelo mesmo canal (identificação por BSUID/HMAC, prazo interno de 30 dias), as quatro operações (exportação, rectificação, eliminação, oposição) e a orquestração do apagamento por eventos em todas as lojas de dados.

### Critérios de Aceitação
- [ ] Um pedido do titular é aceite só do mesmo BSUID do contacto; um pedido de outro BSUID sobre os dados de Y devolve 0 dados e fica registado; cada pedido cria `dsar_requests` (proposta de tabela) com tipo, estado, `recebido_at`, `prazo_interno_at = recebido_at + 30 d` e `papel_kamba` lido da configuração de D9 (omissão `subcontratada`, a confirmar por parecer).
- [ ] Exportação: devolve JSON portátil com contacto, conversas, encomendas e consentimentos do titular, entregue por URL assinada com TTL ≤ 5 min; o canário do contacto está presente e nenhum dado de outro contacto ou tenant aparece.
- [ ] Eliminação: `privacy.erasure_requested` é consumido por cofre de contactos, AGR (conversas e *checkpoints*), STO (media e transcrições), DAT (linhas por `sujeito_ref` nas épocas retidas), IDX (texto de reviews) e Chatwoot; cada um emite `privacy.erasure_applied`; o pedido só passa a `concluido` quando todos aplicaram.
- [ ] Após a eliminação: `contact_endpoints` do contacto = 0 linhas, `contacts.erased_at` preenchido e `bsuid_hmac` substituído por valor aleatório (um novo contacto é criado se o BSUID voltar a escrever); onde existir `dek_id` (`../docs/tecnica/06` §7.6), a chave de dados é destruída e a tentativa de decifrar o conteúdo falha.
- [ ] As encomendas e o `payment_events` mantêm-se (retenção fiscal separada, prazo do CGT NÃO VERIFICADO); a cadeia de *hashes* continua a verificar-se após o apagamento (0 quebras).
- [ ] Backups não são reescritos: um *erasure ledger* (sem dado pessoal) é reaplicado após restauro; um teste de restauro de uma cópia anterior ao pedido seguido da reaplicação deixa o canário ilegível/removido.
- [ ] Rectificação actualiza o dado no `contact_endpoints` ou no perfil do contacto e escreve no `audit_log`; oposição regista `consent.withdrawn` e inclui o contacto na lista de supressão de marketing («PARAR»).
- [ ] O pedido repetido é idempotente (1 execução); um pedido em curso não duplica *jobs*; falha de um consumidor vai para DLQ e o prazo interno gera alerta aos 20 dias.
- [ ] O teste ponta a ponta em staging com um contacto sintético com dados em Postgres, Chatwoot, STO, DAT e IDX termina com o canário a 0 em todos e em ≤ 30 dias de relógio simulado.

### Detalhes Técnicos
- **Componentes:** GOV, AGR, COM, STO, DAT, IDX, HND, EVT. Eventos `privacy.erasure_requested`/`privacy.erasure_applied` (catálogo `../docs/tecnica/06` §5); `erasure_ledger(erasure_id, contact_id, escopo, aplicado_at)` e `dsar_requests` são propostas de tabela.
- **Convergência de esquema:** KAM-008 fixa o esquema de identidade; este ticket implementa contra o que for fixado (crypto-shredding por `dek_id` se existir; senão anulação de `contact_endpoints` e do `bsuid_hmac`, `../docs/tecnica/03` §5.3 d) e regista a variante no PR.
- **Fornecedores:** pedido de eliminação com retenção zero por contrato (E3 req. 8); registo em `audit_log` sem conteúdo.
- **Consentimento:** depende do registo de consentimentos (`consent_ledger` em `../docs/tecnica/06` §7.3, ou `consents` em `../docs/tecnica/08` §8.1) criado em KAM-022; as duas designações precisam de ser unificadas.
- **Papéis:** PRIV e a PME executam; a KAMBÁ nunca decide sozinha eliminar dados da PME enquanto D9 não estiver fechada.

### Testes Requeridos
- E2E em staging com contacto sintético (canários) em todas as lojas; exportação e eliminação.
- Idempotência: pedido repetido, *crash* a meio, consumidor em falha com DLQ.
- Segurança: BSUID alheio, tentativa de exportar dados de outro tenant (suite cruzada).
- Restauro com *erasure ledger*; verificação da cadeia de *hashes* do ledger de pagamentos.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Privacidade: nenhum dado pessoal em eventos, logs ou `dsar_requests`; só `contact_id`.
- [ ] Isolamento de tenant e de contacto: RLS e caso na suite cruzada; exportação só do titular.
- [ ] Idempotência: pedido e eventos de apagamento com chave e teste de repetição.
- [ ] Observabilidade: SLA por pedido, métricas de pedidos abertos e em atraso.
- [ ] Migrações reversíveis; dois revisores (P0 de dados pessoais); itens D9 e prazo CGT com critério de saída.

### Handoff para Claude Code

```text
És o executor do ticket KAM-070 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-070),
docs/tecnica/08 (§7.2, §8.1, §8.4, §11), docs/tecnica/06 (§5, §7.2, §7.6), docs/tecnica/03 §5.3 e E3 req. 13.
Objectivo: pedidos do titular pelo mesmo canal (identificação por BSUID/HMAC, prazo interno 30 d) com exportação,
rectificação, oposição e eliminação orquestrada por privacy.erasure_requested/applied em cofre, AGR, STO, DAT, IDX e
Chatwoot; erasure ledger reaplicado após restauro; payment_events/encomendas mantêm-se.
- Pedido só do mesmo BSUID; eliminação anula endpoints e bsuid_hmac (e destrói a DEK se existir); nunca tocar no ledger.
- O papel da KAMBÁ (D9) e o prazo do CGT são NÃO VERIFICADOS: parâmetros, não constantes.
Não expandas escopo: off-boarding do tenant (KAM-098), retenção automática (KAM-071), consentimento (KAM-022).
Testes: E2E com canários, idempotência, BSUID alheio, restauro. PR com o template (§7).
```

---

## KAM-071 — Retenção e purga por classe de dados

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-026, KAM-011, KAM-020, KAM-070 |
| Bloqueia | KAM-098 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.1, §7.5, §8.8, §11), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.4), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§6, requisitos 7, 14), ADR-010 |

### Contexto
A Lei 22/11 Art. 11.º (CONFIRMADO, resumo) limita a conservação ao período necessário às finalidades; os prazos são **propostas de engenharia** e os legais estão por confirmar. O prazo fiscal do CGT para facturas e encomendas é NÃO VERIFICADO, pelo que a purga fiscal não pode ter valor por omissão. Há duas tabelas de retenção com diferenças: `../docs/tecnica/08` §11 dá 12 meses para transcrições/`assistant_queries` e `../docs/tecnica/06` §7.4 dá 13 meses (vida de `K_época`); este ticket adopta 13 e regista a divergência. O áudio é apagado após transcrição (alvo ≤ 24 h, máx. 72 h).

### Objectivo
Implementar o registo de classes de retenção como configuração versionada, os *jobs* de purga (TTL no STO, `DROP PARTITION`, eliminação por tenant) com log de eliminação sem conteúdo, o modo *dry-run* e a retenção legal (*hold*), cobrindo 100% das tabelas com dados pessoais.

### Critérios de Aceitação
- [ ] A configuração `retention_policy` define as classes de `../docs/tecnica/08` §11: conversas 90 dias após fecho (PME pode alargar até 12 meses com justificação registada), áudio ≤ 24 h após transcrição (máx. 72 h), `assistant_queries` 13 meses e texto 90 dias, logs técnicos e traces 30 dias, `events_outbox` 7 dias, `events_log` 24 meses, `events_consumed` 90 dias, `events_dlq` 30 dias após resolução, backups WAL 7 dias e diários 35 dias; todos os valores são marcados «proposta».
- [ ] Um teste de catálogo percorre as tabelas com etiqueta de dados pessoais do inventário (§7.1) e falha o *build* se alguma não estiver mapeada a uma classe de retenção.
- [ ] Nenhum blob de áudio existe mais de 24 h após transcrição bem-sucedida e nenhum mais de 72 h após erro (verificação nocturna = 0 violações); o URL de media da Meta nunca é persistido.
- [ ] As classes fiscais (encomendas, `payment_events`, facturas arquivadas) têm `fiscal_retention_years` sem valor por omissão: com o parâmetro nulo o *job* recusa purgar e regista o motivo; um teste com 10 anos simulados de dados fiscais mostra 0 linhas apagadas.
- [ ] Cada execução escreve no `purge_log` classe, tenant, contagens e janela, sem conteúdo nem identificadores de titular; falha de um *job* gera alerta Sev2 e não deixa estado parcial (idempotente por janela).
- [ ] O *dry-run* lista o que seria apagado sem apagar; o *hold* legal por tenant ou contacto impede a purga e fica no `audit_log`.
- [ ] A purga não ressuscita dados apagados por pedido do titular: os *jobs* respeitam o `erasure_ledger` de KAM-070 e a purga de partições mensais usa `DROP PARTITION` (sem `UPDATE` em massa); a falha na criação da partição M+2 alerta Sev2.
- [ ] A retenção dos *checkpoints* do AGR (esquema `lg`, KAM-026) e das conversas do Chatwoot está incluída; o *job* usa o papel `kamba_batch` com sessão registada no `audit_log`.
- [ ] Encerramento de tenant: exportação ao responsável e eliminação (excepto fiscal) em 30 dias, com o mesmo log.

### Detalhes Técnicos
- **Componentes:** GOV, STO, COM, AGR, HND, DAT. Módulos `services/retention/{policy,jobs,purge_log}`; TTL de objectos no `StorageProvider` (KAM-011) e `DROP PARTITION` para `assistant_queries`, `assistant_query_texto`, `events_log`, `dat.llm_call_log`.
- **«Fecho de conversa»:** definir o evento de fecho (estado de HND/AGR) no PR; sem ele os 90 dias não têm início.
- **Quatro conflitos a registar:** 12 vs 13 meses (adopta-se 13); WORM do SeaweedFS NÃO VERIFICADO (só Clusters); retenção do `audit_log` ≥ prazo fiscal para dinheiro e 12 meses para acessos; prazo CGT NÃO VERIFICADO (D7 com `../docs/tecnica/08`).
- **Dados fiscais:** `fiscal_docs` separados do histórico de chat para que apagar a conversa não apague o registo fiscal.
- Backups não se reescrevem; expiram pelo ciclo; o *erasure ledger* é reaplicado no restauro (KAM-070/KAM-085).

### Testes Requeridos
- Unit: cálculo de janelas com relógio simulado por classe.
- Integração: *jobs* sobre dados sintéticos de 24 meses; `DROP PARTITION`; TTL do STO; *dry-run*; *hold*.
- Catálogo: teste de cobertura classe × tabela.
- Fiscal: parâmetro nulo recusa purga; caso positivo com parâmetro definido em ambiente de teste.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Privacidade: purga automática e log de eliminação sem conteúdo; áudio sem retenção para além do prazo.
- [ ] Idempotência: cada janela de purga corre uma vez efectiva e repetida não altera o resultado.
- [ ] Isolamento: o papel `kamba_batch` é auditado; a purga respeita o tenant.
- [ ] Observabilidade: métricas por classe e alerta de falha.
- [ ] Migração reversível; prazos documentados como propostas; itens CGT e D7 com critério de saída.

### Handoff para Claude Code

```text
És o executor do ticket KAM-071 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-071),
docs/tecnica/08 (§7.1, §7.5, §8.8, §11), docs/tecnica/06 §7.4 e docs/tecnica/evidencia/E3 §6 (req. 7 e 14).
Objectivo: retention_policy versionada, jobs de purga (TTL no STO, DROP PARTITION, eliminação por tenant) com purge_log
sem conteúdo, dry-run e legal hold, cobertura de 100% das tabelas com dados pessoais (teste de catálogo).
- Prazos são PROPOSTAS; usa 13 meses para assistant_queries (06) e regista a divergência com 08 (12 meses).
- fiscal_retention_years sem valor por omissão: sem parâmetro, nunca apagar classes fiscais.
- Respeita o erasure ledger de KAM-070; backups não se reescrevem.
Não expandas escopo: pedidos do titular (KAM-070), DR e backups (KAM-079/085).
Testes: relógio simulado, jobs, dry-run/hold, catálogo, fiscal. PR com o template (§7).
```

---

## KAM-072 — Rotação de chaves Meta, facilitador e HMAC

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-010, KAM-013, KAM-056, KAM-008 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§5, §7.2), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§3.3, F-16), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.3), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.7, §2.14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` |

### Contexto
O Piloto usa Doppler (Developer grátis até 3 utilizadores); o OpenBao é Clusters. A rotação tem três armadilhas já identificadas. A chave HMAC do ProxyPay **é** a API key: rodá-la sem janela perde eventos, e se o facilitador aceita duas chaves em simultâneo é NÃO VERIFICADO (E2 Q10); a nossa verificação aceita corrente e anterior e o reconciliador por *polling* recupera o que falhar. A Meta re-entrega webhooks até 7 dias, pelo que uma rotação mal sincronizada do App Secret recupera. A rotação de chaves do LiteLLM e os *secret managers* são funções Enterprise (`../docs/tecnica/evidencia/E4` §2.7); a rotação das chaves LLM no Piloto é por procedimento sobre a parte MIT, e essa viabilidade é NÃO VERIFICADA.

### Objectivo
Implementar do lado do consumidor o suporte a duas chaves (anel `[actual, anterior]`) no GWY e em PAY, a rotação do pepper do HMAC de contactos com `kid`, os procedimentos ensaiados em staging para cada segredo do calendário de `../docs/tecnica/08` §5 e o alerta de idade de cada segredo.

### Critérios de Aceitação
- [ ] O GWY mantém o anel `[actual, anterior]` do Meta App Secret: durante a janela aceita assinaturas de ambas; após revogar a anterior rejeita a antiga (401), e a Meta recupera os eventos por re-entrega (teste com webhooks simulados e relógio avançado).
- [ ] PAY aceita `X-Signature` com a chave corrente ou anterior da conta (`credenciais_ref` corrente e anterior) e rejeita a revogada; em *staging* com o *sandbox* do ProxyPay, a rotação trimestral não perde pagamentos: o reconciliador `GET /payments` recupera os que chegaram assinados com a chave que o facilitador deixou de aceitar (F-16).
- [ ] A rotação do pepper do HMAC de contactos incrementa `hmac_key_ver`; a pesquisa tenta a versão corrente e a anterior; 10 000 contactos sintéticos são re-chaveados por *job* em lotes com 0 respostas 5xx e 0 contactos perdidos, e no fim 0 contactos na versão antiga.
- [ ] Tokens de cliente (Embedded Signup) cifrados com AES-256-GCM, DEK por tenant, KEK no cofre e `kid` versionado; rodar a KEK re-cifra as DEK sem tocar nos tokens e a leitura mantém-se.
- [ ] Existe um runbook ensaiado em *staging* por segredo: Meta App Secret (semestral/incidente), `verify_token` (anual), PIN 2FA (até a Meta o descontinuar), API key ProxyPay e chaves AppyPay (trimestral), chaves de provedores LLM/STT (trimestral, imediata se a imagem LiteLLM for comprometida), credenciais de BD (90 dias), tokens do Chatwoot (semestral).
- [ ] Rotação de emergência: com um segredo marcado comprometido, a revogação e a substituição completam-se em ≤ 24 h (alvo P2 de `../docs/tecnica/08` §10) num simulacro cronometrado; o resultado fica registado.
- [ ] A métrica `secret_age_days{segredo}` existe e alerta a 80% do prazo; cada rotação escreve no `audit_log` o identificador e a hora, nunca o valor.
- [ ] Chaves distintas por ambiente (`dev`/`staging`/`prod`): um teste de configuração falha se uma chave Meta ou do facilitador de `prod` estiver presente em `staging`.
- [ ] O procedimento das chaves virtuais do LiteLLM documenta o que a edição MIT permite; o que não permitir fica como passo manual com dono e data (critério de saída do NÃO VERIFICADO).

### Detalhes Técnicos
- **Componentes:** GWY, PAY, LLM, TEN, GOV. Módulos `libs/keyring` (anel de chaves), `services/*/secrets/`, `ops/runbooks/rotacao_*.md`; o orquestrador `rotate(secret_id)` pertence à abstracção de KAM-010.
- **Anel:** `ring = [current, previous]` com `kid`; operações `verify(any)` e `sign(current)`; revogar remove `previous` e regista no `audit_log`.
- **Pepper de contactos:** `K_lookup` por `kid`; recalcula-se a partir do identificador cifrado quando esse existir no esquema final (`../docs/tecnica/06` §7.2); rotação anual.
- **Dependência de PAY:** o ProxyPay (KAM-056) só existe com contrato; sem ele, o runbook do facilitador fica documentado e testado contra o adaptador *fake*.
- Segredos nunca em logs nem em imagens; o cofre é Doppler no Piloto e OpenBao em Clusters (interface única em KAM-010).

### Testes Requeridos
- Unit: anel de chaves (corrente, anterior, revogada), `kid`.
- Integração: rotação do App Secret com webhooks simulados; rotação do pepper com 10 000 contactos; re-cifra de DEK.
- Simulacro de emergência cronometrado em *staging* (≤ 24 h).
- Segurança: segredo de `prod` em `staging` falha; logs sem valor de segredo.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Sem segredos em código, logs ou traces; *scan* de segredos limpo.
- [ ] Idempotência: a rotação repetida é segura (mesma `kid`, mesmo resultado).
- [ ] Privacidade: o *job* de re-chaveamento não regista identificadores; lookup mantém-se.
- [ ] Observabilidade: `secret_age_days`, alerta de expiração, registo no `audit_log`.
- [ ] Runbooks ensaiados e assinados pelo Responsável de Segurança; dois revisores.

### Handoff para Claude Code

```text
És o executor do ticket KAM-072 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-072),
docs/tecnica/08 §5 e §7.2, docs/tecnica/04 §3.3 (F-16) e docs/tecnica/evidencia/E4 §2.7 e §2.14.
Objectivo: anel de chaves [actual, anterior] com kid no GWY (Meta App Secret) e em PAY (chave HMAC do facilitador),
rotação do pepper do HMAC de contactos (hmac_key_ver, lookup corrente+anterior, re-chaveamento em lotes),
re-cifra de DEK/KEK dos tokens de cliente, runbooks ensaiados em staging e métrica secret_age_days.
- A chave HMAC do ProxyPay é a API key: aceitar duas chaves do nosso lado; se o facilitador aceita duas em simultâneo
  é NÃO VERIFICADO; o reconciliador recupera o que falhar.
- Nunca registar valores de segredos; chaves distintas por ambiente.
Não expandas escopo: abstracção do cofre (KAM-010), adaptador ProxyPay (KAM-056).
Testes: unit do anel, integração, simulacro de emergência, segurança. PR com o template (§7).
```

---

## KAM-073 — Red-team do AGR: injecção directa e indirecta, exfiltração

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-033 |
| Bloqueia | KAM-074 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.3, §4.4, §3.7 X-09, §4.7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4, risco 1), `specs/01_Engineering_Standards_e_Handoff.md` (§4 gate 13), ADR-007, ADR-015 |

### Contexto
A injecção de instruções é o vector número um (`../docs/tecnica/08` §4.3). A defesa tem cinco camadas e nenhuma assenta em «o modelo ignora instruções»: L1 entrada, L2 contexto, L3 tools por classe (`read`/`write`/`money`), L4 saída (validador de citação, filtro de PII/segredos/URLs) e L5 detecção (3 tentativas por hora por contacto → handoff e *cool-down*). A meta-regra: **o modelo propõe, o código dispõe** — uma injecção pode alterar o texto da resposta mas não o tenant, o preço, o estado de pagamento nem escrever sem confirmação. O catálogo escrito pela PME e o OCR de fotos são dados não confiáveis (injecção indirecta). Um assistente «que responde a tudo» pode também ser classificado como *AI Provider* pela Meta, pelo que a recusa fora de domínio faz parte do teste.

### Objectivo
Executar um red-team adversarial PT-AO contra o AGR já com os guardrails de KAM-033, produzir o relatório com classificação de achados, abrir correcções e promover os casos a regressão determinística no *gate* golden.

### Critérios de Aceitação
- [ ] O conjunto adversarial tem ≥ 100 casos PT-AO (proposta de tamanho) distribuídos por: ≥ 30 de injecção cruzada «mostra os pedidos da loja X» (X-09), ≥ 20 de injecção indirecta (descrição de produto, nome de produto, OCR de foto, resultado de tool), ≥ 20 de exfiltração (system prompt, segredos, outros tenants, URLs e markdown de imagem remota), ≥ 15 de abuso de tools (escrita sem confirmação, alteração de preço/stock por quem não é o dono, classe `money`) e ≥ 15 de *denial of wallet* e de voz com instruções na transcrição.
- [ ] Invariantes testadas e com 0 violações: nenhum dado de outro tenant ou contacto na saída (canário), nenhuma alteração de preço, stock ou estado de pagamento por texto do cliente, nenhuma escrita `write`/`money` sem botão interactivo do runtime e resposta do mesmo BSUID.
- [ ] O filtro de saída bloqueia 100% dos casos com markdown de imagem remota, URL fora da allowlist (domínios da loja e do facilitador) e eco do *system prompt*; o bloqueio devolve a mensagem determinística.
- [ ] L5: 3 tentativas de injecção em 1 hora de um contacto accionam handoff e *cool-down*; a métrica `injection_attempt` regista cada caso; o limite de passos e de tokens por turno impede um ciclo infinito (teste de 50 turnos).
- [ ] Dados sensíveis (saúde, religião, política): o texto não é persistido nem enviado ao LLM e a resposta é neutra com handoff; ≥ 20 frases de teste com a taxa de detecção acordada (valor a fixar com o Responsável de Segurança).
- [ ] O relatório classifica cada achado em P1–P4 (`../docs/tecnica/08` §10), com reprodução, camada que falhou, dono e prazo; achados P1/P2 abrem tickets `fix` e são corrigidos e re-testados antes de fechar o ticket.
- [ ] Todos os casos que falharam alguma vez são promovidos a asserções determinísticas do *gate* golden (gate 13), com SemVer do conjunto adversarial.
- [ ] Recusa fora de domínio: ≥ 95% das mensagens fora de domínio recebem recusa neutra e oferta de handoff (alvo de `../docs/tecnica/05` §10, proposta).

### Detalhes Técnicos
- **Componentes:** AGR, TLS, REG, GOV. Resultados em `docs/seguranca/redteam/{plano,casos.jsonl,relatorio.md}`; casos em `eval/adversarial/*.jsonl` com o mesmo executor de KAM-040.
- **Execução:** automática (corpus + variações) e manual (2 pessoas, 1 dia). Ambiente `staging` com dados sintéticos e canários; nunca produção.
- **Invariantes** são asserções de estado (tenant, preço, `paga`, escritas), não de texto: a resposta pode ser «feia» sem ser incidente.
- Coordenar com X-09 de KAM-066 (os 30 prompts cruzados fazem parte da suite de isolamento; aqui entram também no relatório).
- Custo LLM do red-team medido e registado (budget por tenant de teste).
- Resultado alimenta KAM-074.

### Testes Requeridos
- Execução completa do corpus e relatório; repetição após correcções (re-teste dos P1/P2).
- Verificação de que cada caso promovido a regressão falha no código antigo e passa no corrigido.
- Auditoria de que nenhum caso usa dados reais.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Números só de tools e Pagamento só por evento autenticado verificados como invariantes (0 violações).
- [ ] Isolamento: canários de B nunca aparecem na saída dos casos cruzados.
- [ ] Eval-gate: casos promovidos entram no gate golden; SemVer do conjunto adversarial.
- [ ] Privacidade: dados sintéticos; relatório sem dados pessoais.
- [ ] Achados P1/P2 corrigidos e re-testados; relatório assinado pelo Responsável de Segurança.

### Handoff para Claude Code

```text
És o executor do ticket KAM-073 da KAMBÁ (chore). Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-073),
docs/tecnica/08 §4.3, §4.4, §3.7 (X-09) e ADR-007/015.
Objectivo: conjunto adversarial PT-AO (>= 100 casos: injecção cruzada, indirecta via catálogo/OCR, exfiltração,
abuso de tools, denial of wallet, voz), execução em staging com canários, relatório com achados P1-P4 e promoção dos
casos falhados a asserções determinísticas do gate golden.
- Invariantes (não de texto): sem fuga entre tenants, sem alteração de preço/stock/pagamento por texto do cliente, sem
  write/money sem confirmação interactiva do runtime.
- Só dados sintéticos; nunca produção.
Não expandas escopo: implementar guardrails (KAM-033); corrige achados em tickets 'fix' próprios.
Entrega: casos, relatório, tickets fix, PR com o template (§7).
```

---

## KAM-074 — Revisão de segurança independente pré-Piloto

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-066, KAM-073, KAM-065 |
| Bloqueia | KAM-109, KAM-110 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§3, §4, §8.5 requisito 11, §10, §15), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisito 11), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§5), `specs/01_Engineering_Standards_e_Handoff.md` (§3) |

### Contexto
O requisito 11 de `../docs/tecnica/evidencia/E3` exige pentest ou *checklist* antes do go-live e regista que falhas nesta área motivaram multas da APD (Fast Digital Center, USD 112 000). Um Piloto com equipa pequena e sem segregação de funções é o cenário de maior risco de fuga cruzada. A revisão tem de ser **independente**: feita por quem não escreveu o código. O custo e a disponibilidade de um revisor externo são NÃO VERIFICADOS; o critério de saída abaixo cobre o caso em que não há revisor contratável. Este ticket não substitui o gate de go-live de transferência (KAM-069) nem o parecer jurídico (KAM-104).

### Objectivo
Obter um relatório independente sobre isolamento, segredos, callbacks de pagamento, webhook da Meta, confirmação manual, cadeia de abastecimento, configuração do Chatwoot/Medusa, rede e backups, com achados classificados e re-testados, e uma decisão escrita de «pronto / não pronto» para dados reais.

### Critérios de Aceitação
- [ ] O âmbito escrito cobre, no mínimo: isolamento (suite KAM-066 e testes manuais), `tenant_id` do estado e RLS, callbacks de pagamento forjados (HMAC, *replay*, valor e referência), webhook da Meta (assinatura, SSRF no download de media), confirmação manual abusada, segredos e rotação, imagens e cadeia de abastecimento, Chatwoot (*bot* global com `account_id` nulo, Platform API) e Medusa (admin exposto, *flags* EE), *egress*, backups e logs.
- [ ] O revisor é independente (não autor do código do âmbito); a identidade, as qualificações e a data ficam registadas; revisão cruzada por engenheiro não-autor só é aceite como substituto com risco aceite por escrito pelo Responsável de Produto e pelo Responsável de Segurança.
- [ ] O relatório classifica os achados em crítico, alto, médio e baixo, cada um com reprodução, componente, controlo violado (linha da matriz de KAM-065), dono e prazo.
- [ ] 0 achados críticos ou altos abertos antes de qualquer tenant com dados reais; achados médios têm plano, dono e data; baixos ficam registados.
- [ ] Cada achado crítico/alto corrigido é re-testado pelo revisor e o relatório de re-teste está anexado; as correcções são tickets `fix` ligados.
- [ ] Testes de exploração incluem pelo menos: cross-tenant autenticado como A contra B, `SECURITY DEFINER` fora da lista, callback com HMAC adulterado e *replay* de corpo válido, imagem de comprovativo como prova, URL assinada de media de outro tenant, e extracção de segredos do ambiente de contentores.
- [ ] A decisão final («pronto» / «pronto com condições» / «não pronto») está assinada pelo Responsável de Segurança e aprovada pelo Responsável de Produto, com a lista de condições e prazos.
- [ ] O registo de riscos residuais de KAM-065 é actualizado com o resultado; os itens NÃO VERIFICADOS que dependem de terceiros (D3 Mercur/Medusa, D1, D9) ficam explícitos como fora do âmbito da revisão.

### Detalhes Técnicos
- **Componentes:** todos. Entradas: matriz de KAM-065, suite de KAM-066, relatório de KAM-073, SBOM e `licencas.yaml` de KAM-067, inventário de KAM-069. Saída em `docs/seguranca/revisao_independente/{escopo,relatorio,reteste,decisao}.md`.
- **Ambiente:** `staging` com dados sintéticos e canários; nunca `prod`; o revisor recebe acesso mínimo com prazo e registo (`audit_log`), sem segredos de `prod`.
- **Referência de classes de incidente:** P1 fuga cruzada, chave comprometida, confirmação de pagamento forjada (`../docs/tecnica/08` §10); um achado deste tipo é crítico.
- O pentest recorrente, SOC e WORM são Clusters (`../docs/tecnica/08` §16); este ticket é pontual, pré-Piloto.
- Alvo de prazo: concluído antes de KAM-109 (início do Piloto com PMEs reais); o mestre não declara essa dependência (ver problemas do backlog).

### Testes Requeridos
- Revisão com o revisor independente (manual + ferramentas) sobre `staging`.
- Re-teste dos achados corrigidos.
- Verificação cruzada: cada área do âmbito referencia o ticket e o teste automatizado correspondente (KAM-066, KAM-067, KAM-068, KAM-072, KAM-073).

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] 0 achados críticos/altos abertos; decisão assinada.
- [ ] Isolamento, Pagamento só por evento autenticado e Privacidade confirmados por testes de exploração com resultado registado.
- [ ] Sem segredos nos anexos do relatório; acesso do revisor revogado e registado no fim.
- [ ] Riscos residuais e matriz de KAM-065 actualizados.
- [ ] Dois revisores internos (Segurança e Arquitectura) validam a resposta aos achados.

### Handoff para Claude Code

```text
És o executor do ticket KAM-074 da KAMBÁ (chore: preparar e acompanhar a revisão independente).
Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-074), docs/tecnica/08 (§3, §4, §8.5 req. 11, §10) e a matriz de KAM-065.
Objectivo: preparar o pacote de revisão (âmbito, acessos mínimos a staging com dados sintéticos, matriz, suite KAM-066,
relatório KAM-073, SBOM), registar o relatório do revisor independente com achados crítico/alto/médio/baixo,
abrir tickets 'fix' e anexar o re-teste e a decisão pronto/não pronto.
- O revisor não pode ser autor do código do âmbito; sem revisor contratável, só com risco aceite por escrito.
- Nunca em prod; nunca dar segredos de prod ao revisor. Não inventes custos nem prazos de revisor.
Não corrijas achados dentro deste ticket: cada um vira 'fix' com DoR/DoD próprios.
Entrega: pacote, relatório, re-teste, decisão. PR com o template (§7).
```

---

## KAM-112 — Minimização de PII antes do LLM

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-030, KAM-008, KAM-068 |
| Bloqueia | KAM-109 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.4, §7.5, §8.3, §8.5 requisito 6), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§8.4, §13.4), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisitos 6, 8 e 10), ADR-007, ADR-008, ADR-010, ADR-018 |

### Contexto
O requisito 6 de `E3` (minimização antes do LLM) está desenhado em `../docs/tecnica/08` §7.4: detector, tokenização, gate de destino, LiteLLM e re-identificação só dentro da região aprovada; `../docs/tecnica/02` §8.4 fixa que o contacto segue ao modelo como «Cliente», sem telefone, e que a morada só segue quando indispensável. O gate de destino (`tenant_destinations`) é de KAM-069 e o cliente do LLM de KAM-030; este ticket é o **detector e o tokenizador** que nenhum dos dois contém. Limite assumido: nomes próprios em texto livre e referências a locais escapam a regras; a minimização **reduz** a exposição mas não prova que deixou de haver transferência *(a confirmar por parecer)*. O áudio não se mascara antes do STT: aí a minimização é não enviar com o blob nenhum metadado (contacto, telefone, tenant) e passar o destino pelo gate (`../docs/tecnica/08` §7.5); a transcrição entra no mesmo pipeline antes de chegar ao LLM. Preços, totais, quantidades, horas e `sku` são *facts* de negócio (ADR-007) e têm de passar intactos.

### Objectivo
Implementar o pipeline que, antes de qualquer chamada ao LLM ou ao STT, remove ou mascara telefone, BSUID, moradas, NIF e nomes de terceiros, substitui o contacto por «Cliente», mede a cobertura e preserva os números de negócio.

### Critérios de Aceitação
- [ ] `minimise(texto, ctx) → (texto_mínimo, mapa)` é a única via para o cliente LLM de KAM-030: chamar o gateway com texto não minimizado falha no tipo (`MinimisedText`) e num teste de arquitectura; o STT recebe só blob e indicação de língua.
- [ ] Substitui por tokens (`TELEFONE_n`, `BSUID_n`, `EMAIL_n`, `NIF_n`, `MORADA_n`, `PESSOA_n`) o telefone `+244` (formas `+244 9XX XXX XXX`, `00244…`, `9XXXXXXXX` com espaços, pontos ou hífenes, dígitos Unicode, por extenso), BSUID (`PT.…`), e-mail, NIF (padrão parametrizável: `../docs/tecnica/08` não o define e não se inventa), moradas e referências de local, e nomes de terceiros; o contacto do turno é sempre «Cliente».
- [ ] Cobertura medida num corpus sintético PT-AO de ≥ 300 casos etiquetados (0 dados reais): recall ≥ 99% em telefone, BSUID, e-mail e NIF e ≥ 90% em moradas e nomes de terceiros (*propostas*, a calibrar no Piloto); a métrica `pii_recall{tipo}` é publicada no CI e abaixo do limiar o build falha.
- [ ] Números de negócio intactos: em ≥ 200 casos adversariais, 0 preços, totais, quantidades, horas ou `sku` alterados («12.500 Kz», «2 x 3.500», «às 15h30», total de 9 dígitos junto a «Kz» que parece telefone); com o pipeline activo o gate 13 mantém 0 números divergentes e qualidade ≥ baseline.
- [ ] Nomes que são *facts* do catálogo do tenant (marcas, produtos, recursos e profissionais de Serviços) não se mascaram (lista lida da porta `CommerceRegistry`); os restantes nomes próprios viram `PESSOA_n`.
- [ ] Re-identificação só no AGR, dentro da região aprovada: um token devolvido pelo modelo e ausente do mapa é removido (teste); o mapa vive no estado do thread com a retenção do checkpointer e nunca em `llm_call_log`, logs, traces ou eventos.
- [ ] Falha fechada: erro ou *timeout* do detector impede a chamada ao LLM e conduz ao modo determinístico (KAM-037) ou a handoff; sobrecarga p95 ≤ 30 ms para 2.000 caracteres (*proposta*).

### Detalhes Técnicos
- **Componentes:** AGR, LLM; módulo `kamba/privacy/minimise.py`, o mesmo gancho para a transcrição de KAM-036. Contacto por `contact_id` e `thread_id = tenant_id:contact_id`; o mapa não contém o telefone do contacto, que continua só em `contact_endpoints` cifrado (KAM-008).
- **Detector local, sem chamada externa:** regras com validação (formato de telefone, NIF configurável), dicionários (bairros e municípios de Luanda, nomes próprios comuns) e padrões de contexto («entregar em», «perto do», «fala com»). Um detector que chamasse um LLM externo seria ele próprio a transferência a evitar. A origem dos dicionários é NÃO VERIFICADA (sem lista oficial): constroem-se a partir do catálogo e de fontes abertas, como *proposta*.
- **Métricas sem valores:** `pii_masked_total{tipo}` e `minimise_latency_ms`; nunca o texto detectado.
- **Fora de âmbito:** gate de destino e inventário (KAM-069), logs sem conteúdo (KAM-068), classificador de dados sensíveis (KAM-033), agregados anonimizados.

### Testes Requeridos
- Unit por tipo de identificador, com variantes de escrita e ofuscação (≥ 50 casos adversariais: espaços, dígitos Unicode, números por extenso).
- Integração: LiteLLM falso que captura o payload; 0 correspondências aos identificadores plantados. Regressão: gate 13 com e sem pipeline.
- Arquitectura: nenhuma chamada ao cliente LLM fora de `minimise`; propriedade: o mapa permite repor o texto original excepto remoções declaradas.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais, transferência); testes verdes; cobertura do módulo ≥ 90%.
- [ ] **Eval-gate** — altera o prompt efectivo: Gate 13 verde; SemVer atribuída.
- [ ] **Privacidade** — payload ao LLM e ao STT sem identificadores directos; mapa fora de logs; limites (nomes em texto livre) documentados no PR (ADR-008, ADR-010).
- [ ] **Isolamento de tenant** — mapa por `thread_id`; teste cruzado do novo caminho.
- [ ] **Custo e observabilidade** — métricas acima; documentação actualizada (`docs/minimizacao.md`).

### Handoff para Claude Code

```text
És o executor do ticket KAM-112 da KAMBÁ. Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-112),
docs/tecnica/08 (§7.4, §7.5, §8.5 req. 6), docs/tecnica/02 (§8.4, §13.4) e ADR-007, ADR-008, ADR-010.
Objectivo: minimise() antes do LLM e do STT: telefone +244, BSUID, e-mail, NIF, moradas e nomes de terceiros viram tokens;
o contacto é «Cliente»; preços, totais, quantidades, horas e sku passam intactos.
- Detector local (regras, dicionários, contexto), sem chamar LLM externo; NIF parametrizável: não inventes o formato.
- Única via para o cliente LLM de KAM-030 (tipo MinimisedText); falha fechada; re-identificação só no AGR.
- Nomes do catálogo do tenant não se mascaram. Métricas sem valores detectados.
Não expandas escopo: gate de destino (KAM-069), logs (KAM-068), sensíveis (KAM-033).
Testes: corpus sintético PT-AO (≥ 300) com recall, 200 casos de números, fuzz de ofuscação, regressão do gate 13. PR com o template (§7).
```

---

## KAM-113 — Resposta a incidentes e notificação de violação de dados

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-065, KAM-068 |
| Bloqueia | KAM-109, KAM-110 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§10, §8.5 requisitos 12 e 25, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§11.1), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§1, §3, requisitos 12 e 25, pergunta 7), `specs/EPIC-07_Seguranca_Conformidade.md` (KAM-065, KAM-068), ADR-008, ADR-010 |

### Contexto
O requisito 12 de `E3` exige um runbook de resposta a incidentes, com contactos e modelo de notificação, e um exercício de simulação anual. `../docs/tecnica/08` §10 dá o fluxo (triagem em 1 h, contenção, avaliação em 24 h, notificação) e as classes P1 a P4. O que falta é torná-lo executável. O estado legal é incerto: a notificação de violações à APD não é obrigatória na Lei 22/11 para responsáveis em geral (INDÍCIO, DLA Piper 2021); o alvo de **72 h** vem do projecto de revisão da lei (2025, INDÍCIO) e de boa prática; o site da APD lista a «Circular 02» sobre incidentes e a imprensa de 2026 (Expansão) refere multas por «não notificação», o que contradiz a leitura anterior (E3, pergunta 7). As coimas do Art. 51.º (USD 75.000 a 150.000 por segurança ou notificação, triplicadas para pessoas colectivas) estão CONFIRMADAS em duas leituras; o intervalo «USD 7.000 a 15.000» é contraditório e NÃO VERIFICADO. Se a KAMBÁ é responsável ou subcontratada, e quem notifica, é D9. Assume-se a obrigação e todos os prazos abaixo são *proposta* *(a confirmar por parecer)*.

### Objectivo
Produzir o runbook de resposta a incidentes e os modelos de notificação (APD, PMEs afectadas, titulares), com classificação de gravidade, contactos, prazos propostos e um exercício de simulação realizado e registado.

### Critérios de Aceitação
- [ ] `docs/seguranca/resposta_incidentes.md` cobre detecção (alerta, PME, titular, fornecedor, Meta), triagem, contenção (revogar chaves, isolar tenant, suspender destino), avaliação, notificação, recuperação e revisão sem culpa, com um dono por papel (SEG, PRIV, ADV, OPS, AP).
- [ ] Classificação P1 a P4 com árvore de decisão (dados pessoais afectados? n.º de titulares? tenants? exploração confirmada?) e os exemplos de `../docs/tecnica/08` §10 (P1: fuga cruzada entre tenants, chave de fornecedor comprometida, confirmação de pagamento forjada); 10 cenários fictícios classificados por 2 revisores com concordância ≥ 90% (*proposta*).
- [ ] Prazos *proposta*, cada um marcado «boa prática; obrigação a confirmar por parecer»: triagem ≤ 1 h, avaliação ≤ 24 h, PMEs afectadas ≤ 24 h (cláusula a prever no DPA, KAM-090), APD e titulares ≤ 72 h; pedidos da APD tratados por T3 em ≤ 5 dias úteis (`../docs/tecnica/10` §11.1, valor sugerido).
- [ ] 3 modelos em `docs/seguranca/modelos/` (APD, PME afectada, titular) com: o que aconteceu, categorias e n.º aproximado de titulares, consequências prováveis, medidas, ponto de contacto; sem dados pessoais de titulares nem conteúdo de mensagens; preenchíveis em ≤ 30 min no exercício (*proposta*).
- [ ] Lista de contactos por papel (APD, Meta, facilitador, alojamento, advogado, equipa interna), cada entrada com dono e data de verificação ≤ 90 dias; sem números pessoais no repositório.
- [ ] Preservação de evidência: *snapshots*, extracto do `audit_log` com a cadeia verificada (KAM-012) e logs; exportação em ≤ 24 h, dentro da retenção de logs de 30 dias (`../docs/tecnica/08` §7.1). A PME é avisada por canal alternativo (KAM-115, quando existir) e nunca pelo WhatsApp se o incidente envolver o canal.
- [ ] Exercício de simulação (*tabletop* de 2 h, cenário P1 de fuga cruzada em `staging` com dados sintéticos) feito antes do primeiro tenant com dados reais, com linha temporal registada: triagem ≤ 1 h, rascunho às PMEs ≤ 24 h, rascunho à APD ≤ 72 h; cada falha vira ticket `fix`; repetição anual.
- [ ] Questões entregues ao pacote de KAM-104: quem notifica (D9), âmbito da Circular 02, prazo legal, coimas, canal para avisar titulares; todo o texto jurídico do runbook e dos modelos leva a marca «(a confirmar por parecer)» e é revisto pelo advogado antes de qualquer uso externo.

### Detalhes Técnicos
- **Componentes:** GOV, OBS. Entradas: classes e matriz de KAM-065; allowlist e retenção de logs de KAM-068. Sem código de runtime; um *script* de recolha de evidência é opcional e entra em `ci/` só se o exercício o justificar.
- **Titulares:** o canal para os avisar (a PME responsável, o número da PME, outro) é decisão aberta ligada a D9; o modelo prevê as duas opções sem escolher.
- **Fora de âmbito:** SOC, SIEM e detecção automática de fuga (Clusters), registo e notificação do tratamento à APD (`../docs/tecnica/08` §8.6; KAM-105), pentest (KAM-074).

### Testes Requeridos
- Revisão dupla (Segurança e Privacidade) do runbook e dos modelos; teste de classificação com os 10 cenários.
- Exercício de simulação com acta, linha temporal e acções; verificação de todos os contactos da lista.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Runbook, modelos e acta do exercício no repositório de provas (requisito 25 de `E3`); aprovados pelo Responsável de Segurança.
- [ ] Parecer jurídico pendente registado em KAM-104; nenhum prazo apresentado como obrigação legal sem confirmação.
- [ ] Privacidade: sem dados pessoais nem segredos nos modelos, na acta ou nos anexos.
- [ ] Documentação ligada aos alertas P1 de `../docs/tecnica/09` §9.2 (alerta sem runbook é removido).

### Handoff para Claude Code

```text
És o executor do ticket KAM-113 da KAMBÁ (chore: runbook de incidentes e notificação de violação de dados).
Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-113), docs/tecnica/08 (§10, §8.5 req. 12 e 25) e docs/tecnica/evidencia/E3 (pergunta 7).
Objectivo: runbook, classificação P1 a P4, 3 modelos de notificação (APD, PME, titular), lista de contactos e plano do exercício.
- Prazos propostos (1 h, 24 h, 24 h PME, 72 h APD e titulares, 5 dias úteis T3): boa prática, a confirmar por parecer.
- Não afirmes obrigação legal: a Circular 02 e o 72 h são INDÍCIO; coimas do Art. 51.º em USD, triplicadas para pessoas colectivas.
- Sem dados pessoais, números de telefone nem segredos nos documentos. Não executes o exercício sozinho: prepara-o e regista-o.
Não expandas escopo: sem SOC/SIEM nem detecção automática. Entrega: documentos, acta-modelo, checklist. PR com o template (§7).
```

---

## KAM-149 — `docs/seguranca/validar.py` aborta com a contagem do canon fixada

| Campo | Valor |
|---|---|
| Epic | EPIC-07 — Segurança e Conformidade |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-065 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/seguranca/validar.py` (linha 43), `../docs/seguranca/lacunas.md` (L-20), `../docs/dividas-documentais.md` (linha 6), `specs/EPIC-07_Seguranca_Conformidade.md` (bloco KAM-065, secção de verificação), `specs/INDICE.md` §4 |

### Contexto

O `../docs/seguranca/validar.py` é a **única verificação por máquina** dos artefactos de segurança do KAM-065: confere as colunas e os domínios da matriz de conformidade, as 96 células do STRIDE, as operações do DPIA, e que todo o `KAM-NNN`, `ADR-NNN`, caminho, nome de teste, `L-NN` e `RR-NN` citado em `../docs/seguranca/` existe. A secção de verificação do bloco do KAM-065 cita a sua saída («OK: 0 erros») como evidência de critérios de aceitação.

**Hoje não corre.** A linha 43 é um `assert` com as contagens do canon escritas por extenso:

```python
assert len(KAM) == 138 and len(ADR) == 20 and len(DEC) == 13, (len(KAM), len(ADR), len(DEC))
```

O *backlog* tem 165 tickets, pelo que, da raiz do repositório:

```text
AssertionError: (143, 20, 13)
```

**O modo de falha é o que importa, e não o número errado.** O `assert` está **antes** das quatro verificações e aborta o programa com um *traceback*: não é «um erro reportado», é a validação inteira a não acontecer. Quem o corre não recebe «0 erros» nem «N erros» — recebe uma excepção, e nenhuma das quatro famílias de verificação chega a ser executada. Uma ferramenta de verificação que rebenta é indistinguível, para quem não lê o *traceback*, de uma que não tem nada a dizer.

**E a razão de isto ter passado despercebido já está escrita no canon:** o `validar.py` **não está no CI** — é a lacuna **L-20** de `../docs/seguranca/lacunas.md` («o gate 3 só vê `KAM-NNN` e `ADR-NNN`; colunas, células vazias, caminhos e nomes de teste não têm gate»), porque o KAM-065 «não pôde tocar em `tools/` nem em `.github/`». Uma ferramenta fora do CI que depende de um número que o canon faz crescer **todas as semanas** quebra-se sozinha, e só se descobre quando alguém a corre à mão.

**Porque é ticket e não linha de dívida documental.** O `../docs/dividas-documentais.md` registra-o na linha 6 e diz, com razão, «isso já é código, e vai no relatório do ticket» — e a regra do próprio registo é que «só para resíduos textuais; o que exige código ou decisão é ticket». Nenhum dos tickets abertos o reclama: os KAM-139 a KAM-141 são dívidas do gate 3b, o KAM-142 e o KAM-143 são celeridade do processo. Fica sem dono, e é esse vão que este ticket fecha.

**O defeito é de classe, não de valor.** Trocar 138 por 143 repõe o funcionamento hoje e volta a quebrar no ticket 144 — que é este. A correcção é deixar de fixar o número.

### Objectivo

Fazer o `validar.py` correr até ao fim e reportar os seus erros, sem depender de uma contagem do canon escrita no código, de modo que o crescimento do *backlog* deixe de ser capaz de o calar.

### Critérios de Aceitação

- [ ] **`python docs/seguranca/validar.py .` corre até ao fim, da raiz do repositório**, e termina com o seu relatório (as linhas `MATRIZ`, `STRIDE`, `DPIA`, `DOCS` e a contagem final de erros) e com código de saída 0 ou 1 — nunca com um *traceback*. O «antes» (`AssertionError: (143, 20, 13)`) e o «depois» ficam na evidência.
- [ ] **Nenhuma contagem do canon fica fixada no código.** Uma busca por literais de contagem no `validar.py` não devolve nenhum; os conjuntos `KAM`, `ADR` e `DEC` continuam a ser lidos das fontes canónicas (`specs/INDICE.md` §4, `../docs/tecnica/00` §8 e §13.3), que é o que estava correcto.
- [ ] **A guarda que o `assert` pretendia dar não desaparece — muda de forma.** O que ele protegia era o caso em que uma expressão regular deixa de bater e os conjuntos vêm **vazios**, o que faria todas as verificações de existência passar por não terem com que comparar. A guarda passa a ser sobre essa propriedade — conjunto vazio, ou abaixo de um piso manifestamente baixo — e **não** sobre o valor exacto, e é reportada como **erro de configuração** com mensagem, não como excepção. Trocar o número por um número novo não satisfaz este critério.
- [ ] **A guarda nova é demonstrada a morder:** com uma fonte canónica semeada de modo a devolver conjunto vazio (ficheiro temporário, não commitado), o validador falha com a mensagem e não dá «0 erros». É o teste que prova que a protecção não se perdeu ao sair o `assert`.
- [ ] **Varrimento da mesma classe em `docs/seguranca/`,** porque este caso veio de uma leitura e não de uma varredura: `gerar_matriz.py` e os outros *scripts* da pasta são verificados à procura de contagens do canon fixadas, e cada ocorrência entra neste ticket ou fica registada como coberta. O `assert "\r" not in bruto` da linha 150 **mantém-se** — é uma propriedade, não uma contagem.
- [ ] **A secção de verificação do bloco do KAM-065 volta a ser verdadeira.** Ela cita «OK: 0 erros» como evidência; o ticket corre o validador e **registra o que ele diz agora** — se houver erros reais escondidos pelo `assert` desde que o *backlog* passou de 138, eles aparecem aqui e são nomeados, não corrigidos (ver Fora de âmbito).
- [ ] **Sem dependências novas**, e o validador continua a correr com a biblioteca padrão.

### Detalhes Técnicos

- **Componentes:** documentação e ferramentas de verificação de segurança; sem código de *runtime*, sem migrações. Ficheiros: `../docs/seguranca/validar.py`, e `../docs/dividas-documentais.md` (riscar a parte de código da linha 6, que passa a ter este ticket).
- **A linha 43 é a única com o defeito.** Todo o resto do ficheiro usa `len()` sobre o que leu, dinamicamente, e está correcto — o que torna o `assert` mais fácil de ler como lapso do que como desenho, e é a razão de a estimativa ser `S` e não `M`.
- **Erros possivelmente escondidos.** Desde que o *backlog* passou de 138 (ou seja, desde o KAM-139), **nenhuma** execução deste validador chegou às suas verificações. É plausível que haja erros reais acumulados em `../docs/seguranca/` — a linha 6 do registo de dívidas nomeava dois, um nome de teste e um caminho que mudaram; o caminho (`db/gate8.py`, hoje `db/gate_bd.py`) fechou no **KAM-152**, que mediu os erros com o `assert` relaxado em memória e os viu passar de 5 para 3, e fica o nome de teste `test_a_premissa_kamba_app_ve_zero_linhas`. **Este ticket não os corrige**: corre, conta, nomeia e devolve ao dono do KAM-065. Corrigir conteúdo de segurança a coberto de um `fix` de ferramenta é como um ticket deixa de ser revisível.
- **Fora de âmbito, e um deles precisa de ticket próprio:**
  - **L-20 — pôr o `validar.py` no CI.** É a razão de fundo por que este defeito viveu, e `../docs/seguranca/lacunas.md` já lhe prescreve «ticket novo». **Continua sem ticket depois deste.** Não entra aqui porque exige tocar em `tools/` e `.github/`, e porque um gate novo tem de entrar nos *required checks* e no espelho do *ruleset* — decisão de CI, não um `fix` de uma linha.
  - Os erros de conteúdo que o validador venha a reportar (nomes de teste, caminhos, células da matriz): do KAM-065 ou de linha de dívida documental, conforme sejam código ou texto.
  - A linha K-01 da matriz e o `gerar_matriz.py`, que a linha 18 do registo de dívidas já nomeia como «mexer no gerador, que é código».
  - As contagens e intervalos herdados do conjunto documental (**KAM-130**, aberto), incluindo o parágrafo de abertura do `specs/INDICE.md` (linha 4 do registo de dívidas).

### Testes Requeridos

- Execução, antes e depois, com a saída no PR: `python docs/seguranca/validar.py .` — antes, `AssertionError: (143, 20, 13)`; depois, o relatório completo e o código de saída.
- Guarda nova: fonte canónica semeada a devolver conjunto vazio → erro de configuração com mensagem, não «0 erros» e não *traceback*.
- Guarda nova, caso positivo: com as fontes reais, a guarda não dispara.
- Regressão de classe: busca por literais de contagem do canon em `docs/seguranca/*.py` → nenhum, com o comando no PR.
- Segunda passagem: correr duas vezes dá a mesma saída (o validador não tem estado).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-149.md`, com o *traceback* do «antes» e o relatório do «depois»).
- [ ] Código revisto por ≥ 1 revisor, pelo Responsável de Segurança por tocar na verificação dos artefactos de segurança; testes verdes.
- [ ] Documentação actualizada: a parte de código da linha 6 de `../docs/dividas-documentais.md` fica riscada com referência a este ticket; o controlo de versões do registo e deste epic registam a emenda; Conventional Commits.
- [ ] **Sem segredos** — não aplicável; o validador lê documentos e não acede à rede.
- [ ] **Dependências** — nenhuma nova.
- [ ] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e este bloco dizem o mesmo, e o `Bloqueia` do KAM-065 inclui este ticket (reciprocidade do grafo, busca G5 do KAM-129).
- [ ] Os erros que o validador reportar depois da correcção estão **contados e nomeados** no PR, e devolvidos ao dono do KAM-065 — não corrigidos aqui.
- [ ] A lacuna **L-20** continua aberta e nomeada no PR como trabalho sem ticket.

### Handoff para Claude Code

```text
És o executor do ticket KAM-149 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-07_Seguranca_Conformidade.md (bloco KAM-149), docs/seguranca/validar.py (linha 43),
docs/seguranca/lacunas.md (L-20) e docs/dividas-documentais.md (linha 6).
Objectivo: o validador corre até ao fim e reporta, sem contagem do canon fixada no código.
- REPRODUZ PRIMEIRO: python docs/seguranca/validar.py . dá AssertionError: (143, 20, 13). É o «antes».
- O defeito NÃO é o número errado: é o número estar lá. Trocar 138 por 143 repõe hoje e volta a quebrar no
  ticket seguinte. Deixa de fixar a contagem.
- NÃO perdes a guarda. O que o assert protegia era o caso de uma regex deixar de bater e os conjuntos virem
  VAZIOS — aí todas as verificações de existência passariam por não terem com que comparar. Passa a guardar
  essa propriedade (vazio, ou piso manifestamente baixo), como ERRO DE CONFIGURAÇÃO com mensagem, não como
  excepção. E demonstra-a a morder, com uma fonte semeada a devolver conjunto vazio.
- O assert "\r" not in bruto da linha 150 MANTÉM-SE: é propriedade, não contagem.
- VARRE docs/seguranca/*.py (incluindo gerar_matriz.py) à procura da mesma classe. Lista cada ocorrência no PR.
- Desde que o backlog passou de 138 (ou seja, desde o KAM-139) NENHUMA execução chegou às verificações. É
  plausível que haja erros reais acumulados. CONTA-OS E NOMEIA-OS no PR; NÃO os corrijas — é conteúdo de
  segurança, e corrigi-lo a coberto de um fix de ferramenta torna o ticket não revisível. Devolve ao KAM-065.
- Actualiza a secção de verificação do bloco do KAM-065 só no que ela afirma sobre a saída do validador.
Não expandas escopo: NÃO ponhas o validador no CI — é a lacuna L-20, que precisa de ticket próprio (toca em
tools/ e .github/, e um gate novo entra nos required checks e no espelho do ruleset). Deixa a L-20 aberta e
nomeia-a no PR. Contagens do conjunto documental são KAM-130; o gerar_matriz.py e a linha K-01 são a linha 18
do registo de dívidas.
Testes: execução antes e depois com a saída no PR; guarda nova a morder e a não disparar; busca por literais
de contagem a dar zero; segunda passagem com a mesma saída.
Abre PR com o template do §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Impacto | Mitigação ou critério de saída | Decisão |
|---|---|---|---|---|
| Dados reais antes de concluído o procedimento APD (precedente Crescer Tech, USD 505 000; país da cloud NÃO VERIFICADO) | CONFIRMADO (multa); detalhes NÃO VERIFICADO | Multa e paragem | Gate de go-live (KAM-069); dados sintéticos até KAM-105; parecer (KAM-104) | D1 |
| Países «adequados» e cláusulas-tipo da APD | NÃO VERIFICADO (sem lista pública; UE/África do Sul são hipóteses, EUA provável autorização) | Gate com estados errados | O código nunca infere adequação; estados por decisão de PRIV/ADV | D1, D9 |
| Papel da KAMBÁ (responsável ou subcontratada) e quem notifica a APD | NÃO VERIFICADO | Direitos do titular e DPA mal atribuídos | `papel_kamba` parametrizável; finalidades próprias desligadas por omissão (a confirmar por parecer) | D9 |
| CDN/WAF que termina TLS é subprocessador com acesso a conteúdo; backups cifrados fora de Angola; licença do Redis | NÃO VERIFICADO (N1, N2) | Incumprimento dos Arts. 33.º–34.º | Linhas `pendente` no inventário; excluir o *path* de webhooks do proxy; Valkey como alternativa | D12 |
| Pseudonimização por HMAC continua a ser dado pessoal para a PME? | NÃO VERIFICADO (N3) | Reidentificação por enumeração se o pepper vazar | Pepper no cofre com `kid` e rotação (KAM-072); tratar como dado pessoal | D9 |
| Prazo de conservação fiscal do CGT; calendário de e-factura | NÃO VERIFICADO | Purga indevida ou retenção excessiva | `fiscal_retention_years` sem valor por omissão; nunca purgar fiscal sem parâmetro | D7 |
| Violação de dados: obrigação e prazo (Circular 02 da APD; alvo 72 h) | INDÍCIO contraditório | Falta de notificação | Assumir 72 h; resposta a incidentes da §10; pergunta E3-7 | D9 |
| Falhas de isolamento no Mercur/Medusa/Chatwoot | CONFIRMADO (Mercur 2026-10-08) / NÃO VERIFICADO (multi-tenancy nativa do Medusa) | Fuga cruzada | Suite KAM-066 com X-10; spike D3; fallback Medusa puro | D3 |
| Rotação da chave do facilitador sem janela dupla; rotação de chaves LiteLLM na edição MIT | NÃO VERIFICADO (E2 Q10; E4 §2.7) | Perda de eventos | Anel de duas chaves do nosso lado e reconciliador; passo manual documentado | D4 |
| Revisor independente: custo e disponibilidade | NÃO VERIFICADO | Piloto sem revisão | Critério de saída de KAM-074: risco aceite por escrito | — |
| Inconsistências documentais: `callback_hmac_ok` vs `authn_ok`; `UNIQUE (provider, referencia)` em `../docs/tecnica/08` §6 vs `../docs/tecnica/04` §6.1; replay ±5 min no ProxyPay; X-07 e C-05..C-08 em falta; três variantes do esquema de identidade | Inconsistência documental | Testes escritos contra o contrato errado | `../docs/tecnica/04` prevalece para pagamentos; KAM-065 regista as lacunas; KAM-008 converge a identidade | — |
| Valores de retenção, limiares e dimensão do red-team | Propostas | Calibração errada | Calibrar no Piloto; valores em configuração versionada | — |

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
| 1.0 | Outubro 2026 | Emissão inicial: 10 tickets (KAM-065 a KAM-074; KAM-112 e KAM-113 acrescentados na consolidação) — modelo de ameaças, isolamento cruzado, cadeia de abastecimento, logs sem conteúdo, gate de transferência, direitos do titular, retenção, rotação de chaves, red-team e revisão independente. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 9 referências aos anexos E3 e E4 passam a `../docs/tecnica/evidencia/…`; antes não resolviam de posição nenhuma. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-065: caixas do ticket marcadas com evidência (seis de treze) e secção de verificação dos critérios de aceitação; artefactos em `../docs/seguranca/` e revisão em `../docs/analises/ANALISE-06-KAM-065-modelo-de-ameacas-stride.md`. Sem alteração aos outros tickets. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-067: caixas do ticket marcadas com evidência (sete de quinze) e secção de verificação dos critérios de aceitação; artefactos em `../tools/supply_chain/`, `../ci/supply-chain/` e `../docs/supply-chain.md`, e revisão em `../docs/analises/ANALISE-10-KAM-067-supply-chain.md`. Sem alteração aos outros tickets. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | KAM-068: caixas do ticket marcadas com evidência (dez de catorze) e secção de verificação dos critérios de aceitação; CA4, CA5 e CA7 ficam vazios, os dois primeiros por contradição com o CA1, devolvida ao Responsável de Segurança. Política em `../docs/logs.md`, revisão em `../docs/analises/ANALISE-11-KAM-068-logs-sem-conteudo.md`. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | KAM-068, seguimento: números da secção de verificação actualizados depois da primeira revisão adversarial, recebida com o PR já fundido (30 *fixtures* de forma no X-11, canário do *lint* com 29 negativas, prova por mutação). **As caixas não mudam.** | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | KAM-149 (`docs/seguranca/validar.py` aborta com a contagem do canon fixada) acrescentado como `fix`: a linha 43 fixa 138 tickets e o *backlog* tem 143, pelo que o validador rebenta antes das suas quatro verificações. Vinha da linha 6 de `../docs/dividas-documentais.md`, que o declara código e não resíduo textual, e nenhum ticket aberto o reclamava. O `Bloqueia` do KAM-065 actualizado. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | KAM-145: os **25** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |

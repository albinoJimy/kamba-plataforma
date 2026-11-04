# Engineering Standards e Handoff — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Foundation — Engineering Standards e Handoff |
| Versão | 1.5 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` |
| Documentos relacionados | `specs/INDICE.md`, `specs/00_KAMBA_Carta.md`, `specs/00_System_Spec.md`, `specs/EPIC-01_Fundacoes_Dados.md` … `specs/EPIC-10_Spikes_Validacao_Gates.md` |

---

## 1. Propósito e âmbito

Este documento fixa os **padrões de engenharia** e o **protocolo de handoff** com que o backlog da KAMBÁ (tickets `KAM-NNN`, distribuídos por dez epics) é transformado em código de produção. Aplica-se a qualquer executor do backlog, humano ou o agente Claude Code.

A tese do produto é tornar as falhas **arquitecturalmente impossíveis** em quatro fundações não-negociáveis (`../docs/tecnica/00` §1.1): **canal oficial**, **mediação total pelo runtime** (ToolLayer + validador de citação), **dinheiro confirmado só por evento autenticado** com liquidação directa à PME, e **core próprio com verticais como configuração**. Os padrões abaixo existem para que essas fundações não sejam corroídas ticket a ticket.

**Âmbito.** Definition of Ready (DoR), Definition of Done (DoD), gates de CI/CD, convenções, princípios de execução, template de PR e prompt mestre de handoff. **Fora de âmbito:** o conteúdo funcional de cada epic e o desenho de solução (conjunto `../docs/tecnica/`).

**Termos.** *Artefacto comportamental* = qualquer artefacto mutável que altera o comportamento do sistema (grafo, prompt, schema de tool, registo de vertical, política de screening, tabela de pesos). *Eval-gate* = avaliação automática sobre o dataset golden PT-AO que gateia deploys. *Idempotência* = repetir uma operação com a mesma chave não duplica o efeito. *Fact* = valor devolvido por uma tool, a única origem legítima de números em respostas. *Esqueleto andante* = fio fino de ponta a ponta através de todas as primitivas.

---

## 2. Definition of Ready (DoR)

Um ticket só entra em execução quando **todos** os itens estão satisfeitos:

- [ ] **ID `KAM-NNN`** no range do seu epic, vivendo em `specs/tickets/KAM-NNN.md` (EPIC-01) ou no `specs/EPIC-XX` do seu epic (os outros dez) — KAM-155.
- [ ] **Contexto** e **Objectivo** escritos para um executor externo sem contexto oral.
- [ ] **Critérios de Aceitação SMART** em *checkboxes*, verificáveis por teste ou observação.
- [ ] **ADRs aplicáveis** citados por código (ex.: ADR-013, ADR-015); o ticket não contradiz nenhum ADR canónico de `../docs/tecnica/00` §8.
- [ ] **Dependências** não bloqueantes: os tickets listados estão `Done`, ou são paralelizáveis, ou a dependência `ext:` está resolvida.
- [ ] **Componentes-alvo** nomeados pelo catálogo canónico (GWY, CHR, AGR, REG, TLS, HND, COM, PAY, IDX, EVT, TEN, LLM, MED, STO, GEO, DAT, OBS, GOV).
- [ ] **Estimativa** XS/S/M/L (XL proibido: se parecer XL, decompor).
- [ ] **Prioridade** P0/P1/P2 e **Fase** (0 ou 1) coerentes com o `INDICE.md`.
- [ ] **Testes requeridos** esboçados, incluindo o tipo de domínio relevante (isolamento, idempotência, citação, golden, contrato).
- [ ] **Impacto de privacidade e segurança** avaliado: o ticket toca dados pessoais, dinheiro, transferência para fora de Angola, segredos ou o número WhatsApp de uma PME? Se sim, o responsável de segurança está no circuito.
- [ ] **Nomes canónicos**: tabelas, colunas, eventos, estados e chaves do ticket usam os nomes de `specs/02_Dicionario_de_Dados_Canonico.md`.
- [ ] **Estado da evidência**: se o ticket depende de facto NÃO VERIFICADO, isso está dito e há critério de saída (spike, parecer ou pergunta escrita).

---

## 3. Definition of Done (DoD)

**Genérico**

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto (mínimo um revisor; dois para tickets P0 que toquem dinheiro, isolamento de tenant, segredos ou dados pessoais).
- [ ] Testes unitários e de integração verdes; cobertura não regride abaixo do limiar (§4).
- [ ] Documentação e ADRs afectados actualizados; `CHANGELOG` alimentado por Conventional Commits.
- [ ] Sem TODOs órfãos nem código morto introduzido.

**Específico do domínio KAMBÁ (não-negociável)**

- [ ] **Isolamento de tenant** — todo o acesso a dados de um tenant vai por `tenant_id` do estado (nunca do texto do utilizador) e por RLS `FORCE`; o teste de isolamento cruzado cobre o novo caminho (ADR-015).
- [ ] **Idempotência** — todo o efeito de negócio (criar pedido, reservar stock, emitir referência, enviar mensagem, mudar estado de pagamento) tem chave de idempotência e um teste que o repete sem duplicar efeitos (ADR-009, ADR-013).
- [ ] **Números só de tools** — nenhum preço, total, stock, data ou hora chega ao cliente que não seja um *fact* citado e validado (ADR-007).
- [ ] **Pagamento só por evento autenticado** — nenhum código marca `paga` por imagem, texto ou input do utilizador; o `ManualProvider` é um evento humano auditado e limitado (ADR-013).
- [ ] **Plataforma sem fundos** — nenhum fluxo recebe, retém ou repassa dinheiro de terceiros (ADR-004); se o ticket parece exigi-lo, pára-se e escala-se (D8).
- [ ] **Privacidade** — contacto por `contact_id`, telefone nunca como chave nem em claro em logs ou eventos; logs sem conteúdo de mensagens; nenhum dado pessoal sai de Angola fora de um destino registado no inventário de subprocessadores com `apd_ref` (ADR-008, ADR-010).
- [ ] **Custo e observabilidade desde o código** — métricas, logs JSON sem conteúdo e custo por tenant (LiteLLM, Meta) nascem com a funcionalidade, não depois (ADR-018).
- [ ] **Sem segredos** — nenhum segredo em código, logs ou traces; chaves no cofre; *scan* de segredos limpo.
- [ ] **Dependências** — versões fixadas por lockfile com *hash* ou por digest; licenças permitidas; nenhum pacote da lista de bloqueio (`langgraph-api`, `langgraph-runtime-inmem`, Dify, n8n e Typebot em superfícies de tenants; MinIO; LiteLLM < 1.83.0) (ADR-002, ADR-014).
- [ ] **Eval-gate verde para artefactos comportamentais** — se o ticket altera grafo, prompt, tool, registo de vertical, política de screening ou alias de modelo, o dataset golden corre e passa o gate; versão SemVer atribuída (§5).
- [ ] **Conteúdo para terceiros** — texto, imagem ou proposta gerados que saem para um cliente ou para uma rede social passam por aprovação explícita do dono, são marcados como gerados por IA quando aplicável, e respeitam o screening de categorias (ADR-020). Nenhuma tool publica ou envia por si.
- [ ] **Migrações reversíveis** — toda a migração de schema tem a inversa testada.

---

## 4. Gates de CI/CD

O *pipeline* é **fail-closed**: qualquer gate vermelho bloqueia a progressão.

| # | Gate | O que valida | Falha bloqueia |
|---|---|---|---|
| 1 | **Build** | Compilação e resolução de dependências a partir de lockfile | Merge |
| 2 | **Lint / format / tipos** | Estilo, imports, tipos estáticos | Merge |
| 3 | **Lint de referências cruzadas** | Todo `KAM-NNN` citado existe no backlog; todo `ADR-NNN` e `D#` citado existe em `../docs/tecnica/00` | Merge |
| 3b | **Lint de nomes canónicos** (KAM-111) | DDL, schemas de eventos e contratos de tools usam os nomes do dicionário | Merge |
| 3c | **Lint de coerência do backlog** (KAM-138) | A linha do ticket em `INDICE.md` §4, o bloco `## KAM-NNN — ` e a tabela-resumo do §3 do epic dizem o mesmo; reciprocidade `Dependências`↔`Bloqueia`, sem ciclos, contagens derivadas e «Controlo de versões» sem buracos | Merge |
| 4 | **Unit** | Testes unitários; cobertura ≥ limiar (§4.1) | Merge |
| 5 | **Integração** | Serviços contra Postgres e Redis reais (containers) | Merge |
| 6 | **Isolamento de tenant e contacto** | Suite cruzada: tenant A não lê B; contacto X não lê encomendas de Y; todas as tools e endpoints | Merge |
| 7 | **Contratos** | Webhooks Meta (simulador, `KAM-024`), callbacks do facilitador, schemas de eventos (compatibilidade, `KAM-007`) | Merge |
| 8 | **Migrações** | Aplicar e reverter; sem perda em dados de teste | Merge |
| 9 | **Secrets** | *Scan* de segredos | Merge |
| 10 | **SAST** | Análise estática de segurança | Merge |
| 11 | **SCA e licenças** | Vulnerabilidades; licenças permitidas; lista de bloqueio; SBOM | Merge |
| 12 | **Política de categorias** | Casos *allow/deny* da lista Meta ∪ lei (`KAM-088`) | Merge |
| 13 | **Eval golden PT-AO** | Asserções determinísticas (números, `sku`, injecção, isolamento, duplicados = 0) + qualidade ≥ baseline | Promoção de artefactos comportamentais |
| 14 | **Image scan** | Vulnerabilidades da imagem; digest fixado; assinatura cosign | Publicação da imagem |
| 15 | **Deploy staging + smoke ponta a ponta** | Mensagem real no número de teste → resposta correcta → pedido → evento | Promoção a produção |
| 16 | **Aprovação** | Gate humano (dois revisores para P0 de dinheiro/segurança) | Deploy prod |
| 17 | **Deploy prod** | Rolling; rollback atómico disponível | Release |
| 18 | **Tag SemVer** | Etiqueta + manifesto de dependências | Encerramento do release |

Regra transversal: nenhum gate pode ser marcado *skip* sem ADR ou aprovação registada.

### 4.1 Limiares iniciais (*proposta*, a calibrar no Piloto)

| Métrica | Limiar |
|---|---|
| Cobertura de linhas em código de dinheiro, isolamento e validador | ≥ 90% |
| Cobertura de linhas no restante | ≥ 75% |
| Números/`sku` divergentes no conjunto adversarial | 0 |
| Fugas entre tenants ou contactos | 0 |
| Pedidos duplicados em testes de duplo toque | 0 |
| Handoff correcto no golden | ≥ 85% (H7) |

---

## 5. Convenções de código e versionamento

- **SemVer para artefactos comportamentais.** Registo de vertical (`registry/*.yaml`), grafos, prompts, schemas de tool, schemas de evento e tabelas de política seguem `MAJOR.MINOR.PATCH`. *MAJOR* = quebra de contrato; *MINOR* = capacidade retro-compatível; *PATCH* = correcção. Trocar o modelo por trás de um alias é um *release* e passa o gate golden.
- **Conventional Commits com ID de ticket.** `tipo(KAM-NNN): descrição no imperativo`. Tipos: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `spike`. A forma vive em **`../tools/conventions.json`** e só lá: o `../commitlint.config.cjs` e o `../tools/githooks/commit-msg` leem-na desse ficheiro, e uma segunda cópia da expressão regular é defeito, não redundância. **Os dois são locais**, e dispensam-se com `--no-verify` — mas **desde o KAM-174 o *gate* 2 lê as mensagens dos *commits* que um PR acrescenta**, pelo alvo `lint-arch`, com a mesma função e a mesma fonte da forma (`../docs/ci.md` §3, *gate* 2). O que se varre são só os *commits* próprios do PR: do primeiro ao segundo pai do *merge ref* do evento, pelo que **nenhum *commit* de `main` entra no intervalo** e o que fica vermelho corrige-se no próprio ramo. As `exemptHeaderPatterns` do `../tools/conventions.json` continuam a valer, pelo que o `Merge branch …` que o *git* escreve ao trazer a `main` para dentro do ramo não precisa de ser baptizado à mão. O que isto **não** cobre está escrito no `../docs/ci.md` §3.
- **O título do PR obedece à mesma forma.** `tipo(KAM-NNN): descrição no imperativo`, lido da mesma fonte. A razão é que **é ele que fica no `main`**: a definição do repositório é `squash_merge_commit_title: COMMIT_OR_PR_TITLE`, pelo que o GitHub usa o assunto do *commit* quando o PR tem um só e o **título do PR** quando tem mais do que um — e o título não vive no ramo, pelo que o *hook* não lhe chega. Verifica-se em `../.github/workflows/titulo-do-pr.yaml`, em `pull_request` com `types: [opened, edited, reopened, synchronize]`, porque o título muda sem o ramo mudar. **Desde o KAM-174 não é a única verificação de assunto do lado do servidor:** ela cobre o caminho do título e o *gate* 2 cobre o do assunto do *commit*, e com `COMMIT_OR_PR_TITLE` são exactamente esses os dois caminhos para o `main`. **O que ela não cobre:** um PR fundido por `merge` ou por `rebase`, onde o assunto não vem do título; e um PR com um só *commit*, onde o assunto vem do *commit* — e esse, desde o KAM-174, é lido pelo *gate* 2 e não por ela. Nesse último caso a verificação corre de qualquer modo, por decisão do **KAM-164** — o número de *commits* não chega no evento, e um *commit* acrescentado depois dos portões transforma o título em assunto sem nada reavaliar. Decidido no **KAM-164**, que nasceu do `29778f3` (PR #75): o assunto que lá está não tem tipo.
- **Branches.** `feature/KAM-NNN-<slug>`; correcções `fix/KAM-NNN-<slug>`. Um *bug* fora do escopo abre ticket novo, não commit oportunista.
- **ADRs em formato MADR.** Novos ADRs numeram-se após o último canónico (`../docs/tecnica/00` §8; actualmente ADR-019). Nenhum ADR canónico é contradito sem *superseding* explícito.
- **Eventos.** Envelope versionado; campos novos só aditivos; consumidores falham de forma visível perante versões desconhecidas (não as ignoram em silêncio).
- **Identificadores.** `contact_id` (UUID aleatório) em tabelas de negócio e eventos; `thread_id = tenant_id:contact_id`; nunca telefone.
- **Dinheiro.** Valores em Kz como inteiros (sem vírgula flutuante); moeda explícita.
- **Datas.** UTC no armazenamento; fuso `Africa/Luanda` na apresentação.
- **Idioma.** Texto ao utilizador em português de Angola; código e identificadores em inglês técnico; documentação na grafia do conjunto (`arquitectura`, `activo`).
- **O executor corre na raiz do repositório.** Todo o bloco `### Handoff para Claude Code` fala a um processo cujo *directório de trabalho* (`cwd`) é a raiz do repositório, e **os caminhos dentro desse bloco são relativos à raiz**: `specs/EPIC-01_Fundacoes_Dados.md`, `docs/tecnica/00_Arquitectura_Solucao.md`, `tools/lint_refs/`. Um `../docs/…` dentro de um bloco de *handoff* aponta para **fora** da árvore e é defeito, mesmo quando resolve por acidente a partir da pasta do ficheiro. Esta regra vale **só** dentro desses blocos: fora deles, uma referência de documento para documento continua a ser relativa à posição do ficheiro que a contém (`../docs/…` a partir de `specs/`), que é a convenção do KAM-128. A distinção não é arbitrária: um bloco de *handoff* é uma instrução a um processo com `cwd`; a prosa é uma ligação para um leitor que navega ficheiros. Decidido no **KAM-145**.

---

## 6. Princípios de execução

1. **Não expandir escopo.** Implementa-se o mínimo que satisfaz os Critérios de Aceitação; o que fica fora é ticket. **Uma excepção (KAM-142):** um *resíduo textual* num documento — uma frase desactualizada, um nome antigo, uma contagem errada — que não peça código nem decisão regista-se numa linha em `../docs/dividas-documentais.md`, em vez de abrir ticket. Um defeito de comportamento, ou qualquer coisa que exija escolher entre duas fontes, continua a ser ticket.
2. **Bug ≠ patch oportunista; bug = novo ticket** (tipo `fix`, com DoR/DoD próprios).
3. **Idempotência primeiro.** Assume-se que o crash a meio é normal e que a Meta e o facilitador re-entregam.
4. **O número é prova, o texto não.** O modelo nunca origina preço, total, stock ou hora.
5. **Dinheiro: só evento.** Nenhum atalho para `paga`; nenhuma retenção de fundos.
6. **Untrusted não comanda.** Mensagens de clientes, descrições de produtos e documentos carregados são dados, não instruções.
7. **Fail-closed por omissão.** Em dúvida sobre tenant, entitlement, categoria ou pagamento, recusa-se e escala-se.
8. **Coerência por contrato.** Interfaces (`PaymentProvider`, `HandoffProvider`, `CommerceRegistry`, `StorageProvider`, `ChannelAdapter`, `SttProvider`) fixam-se cedo; implementações podem ser finas.
9. **Medir antes de afirmar.** Latência, custo e qualidade em português de Angola são NÃO VERIFICADOS: medem-se (spikes, golden), não se assumem.
10. **Degradar, nunca calar.** Falha de LLM, canal ou pagamento tem fallback determinístico ou fila.

---

## 7. Template de Pull Request

**O título do PR é `tipo(KAM-NNN): descrição no imperativo`** — a mesma forma do assunto de um *commit* (§5), e pela razão que lá está escrita: é o título que o GitHub põe no `main` quando o PR funde por *squash* com mais do que um *commit*. O `## KAM-NNN — <título do ticket>` abaixo é o cabeçalho do **corpo** do PR e não o título; copiá-lo para o campo do título é exactamente o defeito que o `29778f3` deixou no histórico, e a verificação de `../.github/workflows/titulo-do-pr.yaml` recusa-o.

```markdown
## KAM-NNN — <título do ticket>

### O que muda
<resumo em 2-3 linhas do comportamento entregue>

### ADRs e decisões aplicáveis
- ADR-0XX (justificar conformidade se tocar numa fundação)
- Decisões abertas tocadas: D# (e como o ticket as respeita)

### Como foi testado
- [ ] Unit  - [ ] Integração  - [ ] Isolamento cruzado  - [ ] Idempotência
- [ ] Contrato (Meta/facilitador/eventos)  - [ ] Golden PT-AO (se artefacto comportamental)

### Checklist DoD de domínio
- [ ] Isolamento de tenant e contacto  - [ ] Números só de tools
- [ ] Pagamento só por evento autenticado  - [ ] Sem fundos de terceiros
- [ ] Sem telefone/PII em logs, chaves ou eventos  - [ ] Custo e métricas
- [ ] Sem segredos  - [ ] Dependências fixadas e permitidas  - [ ] Migração reversível

### Dados pessoais e transferências
<nenhum | lista de campos e destinos, com apd_ref se sair de Angola>

### Riscos e rollback
<como se reverte; impacto em PMEs activas>
```

---

## 8. Prompt mestre de handoff para o Claude Code

```text
És o executor de um ticket do backlog da KAMBÁ (plataforma WhatsApp-native de comércio
conversacional para Angola). Identifica o ID (KAM-NNN) e lê, por esta ordem:

1. specs/tickets/KAM-NNN.md (EPIC-01) ou specs/EPIC-XX_*.md (os outros dez), o bloco do ticket: Contexto, Objectivo, Critérios, Detalhes, Testes, DoD.
2. docs/tecnica/00_Arquitectura_Solucao.md (ADRs e decisões abertas D1–D13) e o documento
   docs/tecnica/NN_*.md indicado nas referências do ticket.
3. specs/01_Engineering_Standards_e_Handoff.md (DoR, DoD, convenções, template de PR).
4. docs/tecnica/evidencia/ quando o ticket depender de facto sobre Meta, pagamentos, lei ou licenças.

Regras (não-negociáveis):
- Implementa só o que satisfaz os Critérios de Aceitação. Não expandas escopo; um defeito fora
  do escopo vira ticket novo.
- tenant_id vem sempre do estado/contexto, nunca do texto do utilizador. Usa RLS FORCE.
- Nenhum número (preço, total, stock, data) chega ao cliente sem ser um fact de uma tool.
- Nenhum código marca um pagamento como pago sem evento autenticado; a plataforma nunca
  detém fundos de terceiros.
- Todo o efeito de negócio tem chave de idempotência e teste de repetição.
- Telefone nunca é chave nem aparece em claro em logs/eventos; usa contact_id.
- Nenhum dado pessoal sai de Angola sem destino registado com apd_ref.
- Dependências fixadas; respeita a lista de bloqueio (langgraph-api, MinIO, Typebot/n8n/Dify
  em superfícies de tenants, LiteLLM < 1.83.0).
- Se o ticket depender de facto NÃO VERIFICADO ou de decisão aberta, diz-o e pára no critério
  de saída previsto; não inventes o facto.

Entrega: código, testes (unit, integração, isolamento, idempotência, contrato, golden quando
aplicável), migrações reversíveis, actualização da documentação afectada, e um PR com o
template da §7. Conventional Commits: tipo(KAM-NNN): descrição.
```

---

## 9. Aprovação e controlo de versões

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | §6, princípio 1: excepção para resíduos textuais, que vão para `../docs/dividas-documentais.md` (KAM-142). *Proposta*, como o resto do documento, até ratificação. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: o §5 passa a declarar que o executor de um bloco de *handoff* corre na raiz do repositório e que os caminhos dentro desse bloco são relativos à raiz, deixando explícito que a regra de referência entre documentos (KAM-128) continua a valer fora deles. Os **três** caminhos `../docs/…` do próprio §8 passam à forma nova. Sem alteração de nenhum gate, DoR ou DoD. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-130: decisões abertas `D1–D13`. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | KAM-164: o §5 e o §7 passam a dizer que o título do PR obedece à forma do assunto de um *commit*, e porquê. A razão é mecânica e não estética: com `squash_merge_commit_title: COMMIT_OR_PR_TITLE`, é o título do PR que fica no `main` quando o PR traz mais do que um *commit* — e ele não vive no ramo, pelo que o `../tools/githooks/commit-msg` não lhe chega. A revisão adversarial do ticket mediu, de passagem, que **nenhum portão de CI lê mensagens de *commit*** (o `make ci-2` corre `lint_arch all`, que é «deps, structure, tool-schema, aliases e medusa», e nenhum *workflow* invoca o `commitlint`): o §5 deixa de dizer o contrário, e a lacuna fica na dívida 173. O §5 ganha a declaração de que a forma vive só em `../tools/conventions.json`, nomeia a verificação nova (`../.github/workflows/titulo-do-pr.yaml`, em `pull_request` com `types: [opened, edited, reopened, synchronize]`) e escreve o que ela **não** cobre. O §7 passa a instruir o título antes do template, e a dizer que o `## KAM-NNN — <título>` de dentro dele é o cabeçalho do corpo e não o título — que foi como o `29778f3` (PR #75) ficou no histórico com um assunto sem tipo. A caixa do critério 4 do ticket fica **vazia**: pôr o contexto nos *required checks* é alteração de regra de bloqueio, e é do fundador. | Equipa KAMBÁ |
| 1.5 | Novembro 2026 | KAM-174: o §5 deixa de dizer que nenhum portão de CI lê mensagens de *commit*, porque o *gate* 2 passou a lê-las. A afirmação era verdadeira quando o KAM-164 a escreveu (dívida 173) e deixou de ser: o alvo `lint-arch` — que já é o *gate* 2 — passa a correr as mensagens dos *commits* que o PR acrescenta contra o mesmo `check_commit_message` que o `../tools/githooks/commit-msg` usa, e contra a mesma fonte única da forma, `../tools/conventions.json`. **Sem *job* novo**, pelo que nenhum contexto novo entra no *ruleset* de `main`: é o caminho do `log-lint` (KAM-068), do `money-lint` (KAM-052) e do `env-lint` (KAM-075). O intervalo é do **primeiro ao segundo pai do *merge ref*** e não o do *gate* 9, para que nenhum *commit* de `main` possa avermelhar um PR alheio — são 22 a 30 dos últimos 140 assuntos de `main` que estão fora da forma, segundo o predicado, e os seus autores não os podem corrigir (os *commits* de `main` não se reescrevem). As quatro `exemptHeaderPatterns` ficam **intactas**, o que mantém a regra pequena: o `Merge branch …` que o *git* escreve por omissão é isento, medido. | Equipa KAMBÁ |

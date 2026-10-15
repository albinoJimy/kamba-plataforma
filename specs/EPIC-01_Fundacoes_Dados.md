# EPIC-01 — Fundações e Dados

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Fundações e Dados |
| Versão | 1.0 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/09_Topologia_Operacao_Escala.md` |
| Documentos relacionados | `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-02_Canais_WhatsApp_Handoff.md`, `specs/EPIC-03_Agent_Runtime_Verticais.md`, `specs/EPIC-07_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` |

---

## 1. Visão do Epic

Este epic constrói o **chão comum** sobre o qual todos os outros assentam: o monorepo e a toolchain, o pipeline de CI fail-closed, o schema `platform` (tenants, canais, entitlements), o isolamento por *row-level security* `FORCE`, o barramento de eventos (outbox transaccional → BullMQ), a identidade de contacto em duas camadas, os limites por tenant (TEN), os segredos, o `StorageProvider` e a auditoria append-only de dinheiro, stock e preço. Nenhum destes itens é visível para a PME ou para o cliente final, mas cada um torna uma classe de falhas *arquitecturalmente impossível* em vez de meramente desencorajada: a fuga entre tenants (RLS + testes cruzados), o evento perdido ou duplicado (outbox + consumidores idempotentes), o telefone como chave (identidade em duas camadas), o segredo no repositório (cofre + scanner).

O epic concretiza directamente **ADR-006** (Postgres 18 único), **ADR-009** (outbox, envelope versionado, consumidores idempotentes, DLQ), **ADR-010** (`contact_id` aleatório, BSUID e telefone cifrados, HMAC rodado, crypto-shredding), **ADR-014** (`StorageProvider`, sem MinIO) e **ADR-015** (isolamento em profundidade com RLS `FORCE`), com apoio de ADR-002/ADR-005 na lista de bloqueio de dependências, de ADR-008 na sensibilidade do alojamento (D1, D6, D12) e de ADR-018 na observabilidade desde o código. Onde os documentos `../docs/tecnica/` divergem entre si (três versões de `contacts`, unidades monetárias, chaves de entitlement), cada ticket regista a decisão tomada e remete para a correcção documental.

Tudo cai na **Fase 0 (Fundação)**, no caminho crítico do esqueleto andante (gate `KAM-108`): sem outbox não há `payment.manual_confirmed` consumido pela vertical Serviços; sem RLS e sem a suite de isolamento não há `K2 Operável` (`../docs/tecnica/00` §13.1). Dois tickets são P1 por dependerem de decisões externas ou de serem refinamento (KAM-011 aguarda D6; KAM-012 e KAM-010 endurecem o que o esqueleto já usa), mas a sua ausência bloqueia o Piloto; as incoerências de prioridade resultantes estão sinalizadas nos riscos.

---

## 2. Critérios de Saída do Epic

- [ ] A partir de um clone limpo, `make bootstrap && make check` fica verde em ≤ 10 min (proposta) e a lista de bloqueio de dependências (`langgraph-api`, `langgraph-runtime-inmem`, Dify, n8n, Typebot, MinIO, LiteLLM < 1.83.0) falha o build quando violada (KAM-001, KAM-002).
- [ ] O pipeline é fail-closed: PR com segredo, licença bloqueada, referência `KAM-NNN`/`ADR-NNN`/`D#` inexistente ou cobertura abaixo do limiar fica vermelho; nenhum gate é omitido sem *waiver* registado com ADR e prazo (KAM-002).
- [ ] A migração do schema `platform` sobe, desce e volta a subir em PostgreSQL 18.6 limpo, sem objectos residuais (gate 8) (KAM-003).
- [ ] 100% das tabelas com coluna `tenant_id` têm RLS `ENABLE` + `FORCE` + política; sob `kamba_app` com `app.tenant_id` de outro tenant a leitura devolve 0 linhas e sem `SET LOCAL` devolve 0 linhas (X-03, X-04, X-05) (KAM-004).
- [ ] 10 000 eventos emitidos com Redis intermitente: 0 perdidos, 0 lacunas de `agregado_seq`, efeito de negócio aplicado 1× por consumidor; um evento `payment.*` em DLQ gera alerta Sev1 (KAM-005, KAM-006).
- [ ] Todo o evento do catálogo de Fase 0/1 tem schema `v1`; uma alteração quebrante sem `versao + 1` falha o gate 7 (KAM-007).
- [ ] Um `grep` do *dump* completo da BD de teste não encontra nenhum telefone nem BSUID em claro; `eraseContact` torna o contacto irrecuperável (KAM-008).
- [ ] Sob 1 000 pedidos paralelos contra um limite de 100, exactamente 100 são aceites (KAM-009).
- [ ] 100% dos segredos do inventário vivem no cofre; 0 segredos em camadas de imagem (KAM-010); o contrato `StorageProvider` passa em SeaweedFS **ou** S3 gerido e a decisão D6 fica escrita (KAM-011); a cadeia de hash do `audit_log` é verificada todas as noites (KAM-012).
- [ ] Os itens NÃO VERIFICADOS do epic (garantias do BullMQ, `uuidv7()` no PG 18.6, S3 do SeaweedFS, intervalo de Node do Medusa) têm nota de evidência no PR do respectivo ticket.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-001 | Monorepo, estrutura de serviços e toolchain | chore | M | P0 | — |
| KAM-002 | Pipeline de CI base: gates fail-closed (build, lint, tipos, unit, secrets, SBOM, licenças) | chore | M | P0 | KAM-001 |
| KAM-003 | Schema `platform`: tenants, entitlements, tenant_channels e migrações reversíveis | feature | L | P0 | KAM-001 |
| KAM-004 | RLS `FORCE` por `app.tenant_id` e suite de isolamento SQL | feature | M | P0 | KAM-002, KAM-003 |
| KAM-005 | Outbox transaccional, publicador BullMQ e envelope de evento versionado | feature | L | P0 | KAM-003 |
| KAM-006 | Consumidores idempotentes, `events_consumed` e DLQ | feature | M | P0 | KAM-005 |
| KAM-007 | Catálogo de eventos: schemas versionados e teste de compatibilidade | feature | M | P0 | KAM-005 |
| KAM-008 | Identidade de contacto em duas camadas (contacts, endpoints, HMAC rodado, cofre) | feature | L | P0 | KAM-003, KAM-010 |
| KAM-009 | TEN: entitlements e limites aplicados por middleware | feature | M | P0 | KAM-003 |
| KAM-010 | Gestão de segredos e chaves (Doppler no Piloto, interface OpenBao) | chore | M | P0 | KAM-001 |
| KAM-011 | StorageProvider S3-compatível (SeaweedFS ou gerido) | feature | M | P0 | KAM-001, ext:D6 |
| KAM-012 | `audit_log` append-only para dinheiro, stock e preço | feature | S | P0 | KAM-003 |
| KAM-111 | Dicionário de dados canónico e reconciliação de `../docs/tecnica/` | chore | M | P0 | KAM-001, KAM-002, KAM-128 |
| KAM-128 | Reorganização do conjunto documental sob `docs/` e reescrita das referências cruzadas | chore | M | P0 | KAM-001 |
| KAM-131 | Gate 9 sobre a história do PR: varrimento dos *blobs* novos | fix | M | P1 | KAM-002 |
| KAM-132 | Cobertura Node sobre todo o TypeScript do âmbito (`--test-coverage-include`) | fix | M | P2 | KAM-002 |
| KAM-133 | SBOM por serviço a atravessar as dependências `link:` do *workspace* | fix | S | P2 | KAM-002 |
| KAM-134 | Chaves de `ci/*.yaml` que nenhum código lê, e recusa de chaves desconhecidas | fix | S | P2 | KAM-002 |
| KAM-135 | Validador de *waivers*: `criado_em`, data de aprovação verificada e gates 14 e 18 | fix | S | P2 | KAM-002, KAM-134 |
| KAM-136 | Dois erros de leitura silenciosos do `tools/kamba_yaml.py` | fix | S | P2 | KAM-002 |
| KAM-137 | Verificação do *ruleset* de `main` e onde vive o *token* de administração | chore | M | P2 | KAM-002 |
| KAM-138 | Gate 3c: lint de coerência do backlog (mestre ↔ epics) | chore | M | P2 | KAM-002 |
| KAM-139 | Variantes vivas em `../docs/tecnica/` fora das 12 do KAM-111 (dívidas do gate 3b) | fix | S | P1 | KAM-111 |
| KAM-140 | Divergências de `../docs/tecnica/` que o KAM-111 encontrou e não enumera | fix | M | P1 | KAM-111 |
| KAM-141 | Contradições do dicionário canónico encontradas pelo gate 3b | fix | S | P1 | KAM-111 |
| KAM-142 | Celeridade do processo de entrega: vagas, mutações em paralelo e menos colisões | chore | S | P1 | KAM-002, KAM-004 |
| KAM-143 | Prova por mutação completa como tarefa nocturna, e fatiada por *runner* | chore | S | P1 | KAM-142 |
| KAM-145 | Forma do caminho dentro dos blocos de *handoff*, e o `cwd` do executor declarado | fix | L | P1 | KAM-128, KAM-129 |
| KAM-146 | As onze linhas de «Controlo de versões» que o KAM-128 não acrescentou | fix | S | P2 | KAM-128 |
| KAM-147 | Os anexos de evidência que o DoD do KAM-128 e do KAM-129 nomeia e não existem | fix | S | P2 | KAM-128, KAM-129, KAM-145 |
| KAM-148 | Leituras silenciosas nos outros dois leitores de YAML (`yamlreg` e `yamlsubset`) | fix | M | P2 | KAM-136 |
| KAM-150 | Regras de `CODEOWNERS` penduradas no prefixo que o KAM-128 removeu | fix | S | P1 | KAM-128 |
| KAM-151 | Cobertura Python sobre `services/agr/src/`, que nenhum alvo media | fix | S | P2 | KAM-132 |
| KAM-152 | `db/gate8.py`: um caminho que não existe, numa mensagem que manda correr o ficheiro | fix | S | P2 | — |

---

## KAM-001 — Monorepo, estrutura de serviços e toolchain

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | — |
| Bloqueia | KAM-002, KAM-003, KAM-010, KAM-011, KAM-013, KAM-030, KAM-041, KAM-075, KAM-111, KAM-128 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§3.1, §7), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.8), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§1, §2.13), ADR-002, ADR-005, ADR-014, `specs/01_Engineering_Standards_e_Handoff.md` §5 |

### Contexto

Todos os outros tickets precisam de um sítio onde viver, de um comando único para construir e testar, e de uma barreira que impeça entrar no repositório o que a evidência proíbe (E4: `langgraph-api` Elastic-2.0, Dify, n8n, Typebot, MinIO arquivado, LiteLLM maliciosos 1.82.7/1.82.8). A topologia do Piloto fixa a pilha: GWY em Node + Hono 4.13.x (o 5.0.0-rc.0 não entra), AGR em Python + LangGraph como biblioteca MIT, COM sobre Medusa 2.21.x, Postgres 18.6 e uma fila Redis-compatível (Redis ou Valkey, D12).

### Objectivo

Criar o monorepo com a estrutura de serviços, as bibliotecas partilhadas, a toolchain reprodutível (lockfiles com *hash*), as convenções do §5 do Engineering Standards impostas por ferramentas e a *stack* de desenvolvimento local, de modo que qualquer ticket seguinte comece num repositório já governado.

### Critérios de Aceitação

- [ ] Existe a árvore `services/` (`gwy`, `worker-canal`, `agr`, `com`, `onboarding-web`), `packages/` (`contracts`, `core-ts`), `libs/py-core`, `db/migrations`, `registry/`, `infra/` e `tools/`; cada serviço expõe `/healthz` (200 com versão e SHA do commit) e arranca com `make up`.
- [ ] `make bootstrap && make check` a partir de um clone limpo termina verde em ≤ 10 min (proposta, medida em CI) usando apenas lockfiles: `pnpm-lock.yaml` com `--frozen-lockfile --ignore-scripts` e Python com `pip install --require-hashes`.
- [x] Uma dependência da lista de bloqueio (`langgraph-api`, `langgraph-runtime-inmem`, Dify, n8n, Typebot, MinIO, `litellm` < 1.83.0) adicionada a qualquer manifesto faz `make check` falhar com mensagem que cita o ADR (teste com 7 *fixtures*, uma por item).
- [x] `commitlint` rejeita mensagens fora de `tipo(KAM-NNN): descrição` e um *hook* rejeita *branches* fora de `feature/KAM-NNN-<slug>` ou `fix/KAM-NNN-<slug>`.
- [x] `engines` fixa Node 24 LTS (Hono 4.13.x); o ficheiro `docs/evidencia/KAM-001-node.md` regista o intervalo de Node aceite pelo Medusa 2.21.x lido do `package.json` oficial (item NÃO VERIFICADO em `../docs/tecnica/09` §3.1).
- [x] O compose de desenvolvimento sobe Postgres 18.6 (+ pgvector 0.8.7, pg_trgm) e um Redis-compatível persistente (AOF) com a imagem parametrizada por variável (Redis ou Valkey; decisão D12 em aberto, nada no código depende de uma das duas).
- [x] Existe `CODEOWNERS` e configuração Renovate com quarentena de versões novas ≥ 7 dias (excepção para correcções de segurança com revisão).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#1`, fundido em `main` (`02ebcd5`). Medido a
2026-10-11 sobre `main` (`1401cd3`). Os alvos `make` correram num **clone limpo**
de `main` dentro de `node:24.21.0-trixie-slim`, porque a máquina de medição não
tem Node, pnpm nem `make`. Essa imagem também não traz `make`, `python3` nem
`git`: foram instalados com `apt-get` antes de clonar, e o cronómetro arranca
depois da instalação **e** depois do clone, pelo que nenhum dos dois conta para os
tempos abaixo. A pilha de desenvolvimento e as sondas correram no Docker do
anfitrião. Cada caixa marcada acima tem uma linha aqui; **as cinco não marcadas
também** — uma caixa marcada sem evidência nomeada é pior do que uma caixa vazia.
Quatro destas linhas foram reescritas depois da revisão adversarial registada em
`../docs/analises/ANALISE-04-encerramento-kam-001-128-129.md`, que desmarcou uma
caixa deste bloco.

| CA | Estado | Evidência |
|---|---|---|
| Árvore, `/healthz` e `make up` | **parcial** | Árvore conforme: `services/{gwy,worker-canal,agr,com,onboarding-web}`, `packages/{contracts,core-ts}`, `libs/py-core`, `db/migrations`, `registry/`, `infra/`, `tools/` — e `lint_arch --root . structure` dá «estrutura: conforme». Pilha levantada pelo comando que o alvo `up` embrulha (`docker compose --env-file .env -f infra/compose/docker-compose.dev.yml up --build --detach --wait`, com `KAMBA_COMMIT_SHA`): 7 contentores `healthy`. `make smoke` (`tools/healthz_check.py`, 5 serviços) → «5 servico(s) conformes ao contrato»: HTTP 200 em `:3000`, `:3001`, `:3002`, `:3003` e `:8000`, cada um com `version` `0.1.0` e `commit` `1401cd374b9473c21f6a5e73b91b344fdb5a5070`, validados contra `packages/contracts/schemas/healthz.response.v1.json`. **Dois dos três conjuntos do critério não estão demonstrados, e é por isso que a caixa fica vazia.** O alvo `make up` nunca foi invocado — não há `make` no anfitrião — e ele faz quatro coisas que o comando corrido não faz: guarda de `docker`, guarda de `.env`, **derivação de `KAMBA_COMMIT_SHA` a partir de `git rev-parse HEAD`** e encadeamento de `make smoke`. Daí o segundo conjunto: o SHA que aparece nas sondas foi **injectado à mão** por quem mediu, e o contrato aceita `unknown` (`^(?:[0-9a-f]{40}\|[0-9a-f]{7,12}\|unknown)$`, com a descrição a remeter o SHA real para o KAM-002), pelo que «5 serviços conformes ao contrato» passaria com cinco `unknown`. A árvore e o `/healthz` a 200 com versão estão medidos; «200 com SHA do commit» e «arranca com `make up`» não |
| `make bootstrap && make check` ≤ 10 min, medido em CI | **parcial** | Verde a partir de um clone limpo, só com *lockfiles*: `bootstrap` **575 s** (rc=0), `check` **13 s** (rc=0, «make check: verde.»), total **588 s** — dentro dos 600 s, com **12 s** de margem. **Remedido a 2026-10-12, porque o KAM-002 entretanto fundiu e a razão original caducou.** O que dizia esta linha — «não há CI em `main`» — deixou de ser verdade: `main` tem `.github/workflows/ci.yaml`, dez ficheiros em `ci/` e o `tools/lint_refs`. Medido no CI que agora existe, sobre 9 execuções de `ci` verdes em `main`: o passo `preparar`, que corre `make bootstrap` a partir dos lockfiles, dá **p95 20 s** (n=54 execuções do passo, mediana 16 s, máximo 26 s); os gates 1, 2 e 4, que cobrem o conteúdo de `make check`, dão **p95 225 s**; o *run* inteiro dá **p95 251 s**. Zero acima de 600 s em qualquer das três medições. **E a caixa continua vazia, por duas razões novas e mais estreitas:** (a) o CI **não corre `make check`** — corre `make ci-1`…`ci-11`, e cinco dos seis componentes de `check` (`lint-arch`, `lock-check`, `typecheck`, `test-py`, `test-ts`) vivem dentro dos gates 1, 2 e 4, mas o sexto, `lint-branch`, não corre em CI nenhum; (b) o `bootstrap` do CI assenta em cache do *store* do pnpm e do `venv`, pelo que os 20 s não são «a partir de um clone limpo» no sentido do CA — o número frio continua a ser os 575 s medidos em contentor. Fecha-se correndo `make check` num *job* próprio, ou emendando o CA para nomear os gates. Os *flags* do CA estão no `Makefile` e correram: `pnpm install --frozen-lockfile --ignore-scripts` e `pip install --require-hashes --no-deps`. Fica por marcar até haver CI. Nota de reconciliação: `docs/evidencia/KAM-001-node.md` §7.1 regista **52 s** (46 + 6) para a mesma verificação, e o próprio anexo explica a diferença — são «uma máquina com cache de rede quente», contra o caso frio medido aqui; são os dois extremos do mesmo intervalo e não uma contradição. O que **é** contradição é o §5 desse anexo riscar este critério como «Resolvido» |
| Lista de bloqueio, 7 *fixtures* | **satisfeito** | Cada um dos 7 itens nomeados no CA foi injectado num manifesto real de uma cópia do `HEAD` e `lint_arch deps` — o primeiro passo de `make check` — devolveu rc=1 citando o ADR: `langgraph-api`, `langgraph-runtime-inmem`, `dify-client`, `n8n-python`, `typebot-sdk` → ADR-002; `minio` → ADR-014; `litellm==1.82.7` → ADR-005. As *fixtures* existem e cobrem mais do que o CA pede: **14** de bloqueio (`f1`–`f14`, sendo `f1`–`f7` exactamente os 7 itens) e **4** de passagem. Árvore limpa: «lista de bloqueio: conforme» |
| `commitlint` e *hook* de ramo | **satisfeito** | `@commitlint/cli@21.2.3` executado contra 7 mensagens: recusa (rc=1) «corrige coisas», «feat: sem escopo de ticket», «feat(KAM-1): …», «chore(KAM-001): x», «chore(KAM-001): … .» e «feat(outro): …»; aceita (rc=0) «chore(KAM-001): cria a arvore do monorepo». O mesmo resultado pela via que o *hook* `commit-msg` usa de facto (`lint_arch commit-msg`, que lê o mesmo `tools/conventions.json`). Nome de ramo: `lint_arch branch` aceita `main`, `feature/KAM-001-monorepo-e-toolchain` e `fix/KAM-129-corrige-referencias-evidencia`, recusa `minha-branch` e `feature/KAM-1-x`; está ligado no `pre-push` |
| `engines` Node 24 e evidência do Medusa | **satisfeito** | `package.json`: `"node": ">=24.21.0 <25"`, `"pnpm": ">=12.11.2 <13"`; `.node-version` e `.nvmrc` em `24.21.0`; `hono` fixo em `4.13.13` nos quatro serviços Node (não o `5.0.0-rc.0`). `docs/evidencia/KAM-001-node.md` §2 regista o intervalo de Node do `@medusajs/medusa` `2.21.2` lido do manifesto publicado no registo npm, com estado **CONFIRMADO** e data de leitura; o ficheiro está em `REQUIRED_FILES` de `tools/lint_arch/structure.py` |
| Compose: Postgres 18.6, pgvector 0.8.7, fila com AOF | **satisfeito** | Medido por execução: `PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2)`, `vector 0.8.7`, `pg_trgm 1.6`; bases `kamba_platform`, `kamba_medusa`, `kamba_chatwoot`. Fila: `valkey_version:9.1.2`, `appendonly yes`. A imagem é parametrizada (`${KAMBA_QUEUE_IMAGE:-valkey/valkey:9.1.2-trixie}`), o serviço chama-se `queue` e a decisão D12 fica aberta: trocar para Redis são duas variáveis de ambiente. Ressalva de leitura: a *tag* `pgvector/pgvector:0.8.7-pg18` fixa o *major* 18 e o pgvector `0.8.7`, não o `18.6`; o `initdb` assere `18.x` e pgvector exactamente `0.8.7`. O `18.6` é observação datada desta execução, não garantia que o compose imponha |
| `CODEOWNERS` e quarentena Renovate | **satisfeito** | `CODEOWNERS` existe, com dono por área. `renovate.json5`: `minimumReleaseAge: "7 days"` e `vulnerabilityAlerts` com `minimumReleaseAge: null`, `automerge: false` e revisores de plataforma e segurança — a excepção de segurança que o CA prevê, sem dispensar revisão. O CA pede existência, e existência há. Mas a evidência tem de dizer o que importa: **nenhuma** das 15 regras atribui dono efectivo — todas apontam para equipas `@kamba/*` e o cabeçalho do próprio ficheiro declara que «o ficheiro nao tem efeito» enquanto a organização do GitHub não existir; o mesmo vale para os `reviewers` do `renovate.json5`. É o que explica os três PR terem sido fundidos sem revisor. Além disso, três regras apontam para `/tecnica/`, prefixo removido pelo KAM-128 — defeito registado na verificação desse ticket |
| DoD: todos os CA satisfeitos | **não satisfeito** | Dois CA em aberto: a árvore/`make up`/SHA (CA1) e o `bootstrap`+`check` medido em CI (CA2) |
| DoD: ≥ 1 revisor; testes verdes | **não satisfeito** | Testes verdes: **116** no total — 75 (`lint_arch`) + 13 (`py-core`) + 7 (`agr`) em Python e 21 em TypeScript (`node --test`, 6 pacotes), 0 falhas. Revisores: o PR #1 foi fundido com `reviewDecision: REVIEW_REQUIRED` e `reviews: []` — **zero** revisores humanos. O DoD pede ≥ 1 |
| DoD: documentação, Conventional Commits, sem TODOs órfãos | **parcial** | Duas das três partes: `README.md` tem a secção «Arrancar» e o ADR local da *toolchain* existe (`docs/adr/ADR-L001-toolchain.md`); `grep` de `TODO`/`FIXME`/`XXX` em `services/`, `packages/`, `libs/`, `tools/`, `infra/`, `db/` devolve **0**. A terceira não se cumpre à letra: dos **10** *commits* do ramo do ticket, **2** não têm âmbito `KAM-NNN` — `d2dbb14` («chore: reorganiza o conjunto documental sob docs/») e `53189a2` («chore: reescreve as referencias cruzadas…»), empurrados com `--no-verify` porque nenhum ticket os cobria. O bloco do KAM-128 regista essa dívida e o KAM-128 fecha-a, mas esta linha do DoD não a dispensa |
| DoD: *lockfile* com *hash*, bloqueio, licenças | **satisfeito** | O fecho está fixado por *hash*, e a evidência é o fecho e não o gestor: `pnpm-lock.yaml` tem **91** `resolution:` e **91** `integrity:` (cobertura total), e os locks Python têm **14** e **138** `sha256:`, instalados com `--require-hashes --no-deps`; `pip_lock.py --check-offline` → «coerente com os pins» nos dois ficheiros. (O `packageManager` fixado por `sha512` vive no `package.json` e fixa o pnpm, não as dependências.) Lista de bloqueio activa e testada (linha acima). Licenças: `../docs/tecnica/evidencia/E4_Stack_Licencas.md` §1 regista a licença de cada escolha de pilha que este ticket fixa, e cada entrada de `tools/blocklist.yaml` regista o fundamento de licença da exclusão. O inventário de licenças do **fecho** instalado (SBOM e *allowlist*) é o gate 11 do KAM-002, fora deste âmbito |
| DoD: sem segredos | **satisfeito** | `.env.example` só com *placeholders* (`POSTGRES_PASSWORD=mude-me-localmente`); nenhum valor real. O compose exige `POSTGRES_PASSWORD` do `.env` e falha sem ele (`:?defina POSTGRES_PASSWORD no .env`); o `.env` é ignorado pelo git (`.gitignore:31`) |
| DoD: compose não expõe portas além de `localhost` | **satisfeito** | `docker compose ps` com a pilha a correr: as cinco publicações são `127.0.0.1:3000`, `:3001`, `:3002`, `:3003` e `:8000`; `postgres` e `queue` aparecem como `5432/tcp` e `6379/tcp` — **sem publicação nenhuma**, por estarem só na rede `data`, que é `internal: true` |

> **O que isto custa, dito com clareza.** O ticket não está fechado: falta a
> medição em CI, faltam os dois *commits* sem âmbito de ticket, e falta a revisão
> humana. O que está feito está medido — a pilha arranca, as cinco sondas
> respondem conformes ao contrato, 116 testes passam, os 7 itens da lista de
> bloqueio param o `check`. O que falta está nomeado.

### Detalhes Técnicos

- **Componentes:** transversal (esqueleto de GWY, CHR, AGR, COM, HND, LLM; nenhum comportamento ainda). Linguagens: TypeScript (GWY, worker de canal, COM, onboarding-web), Python 3.12 (AGR).
- **Layout:** `services/<nome>/{src,tests,Dockerfile}`; contratos de eventos e de tools em `packages/contracts` (JSON Schema, fonte única para TS e Python); `registry/*.yaml` reservado ao AgentRegistry (SemVer); `tools/lint_arch` com a lista de bloqueio em `tools/blocklist.yaml` (nome, razão, ADR).
- **Imagens:** `Dockerfile` por serviço com utilizador não-root e sistema de ficheiros só de leitura; digest fixado é tratado em KAM-067, aqui só o esqueleto multi-stage.
- **Nota:** uma única ferramenta de orquestração de tarefas (`make` como *facade*); escolhas de *task runner* TS/Python registam-se num ADR local MADR (numeração após ADR-019).

### Testes Requeridos

- Unit: `tools/lint_arch` com 7 *fixtures* de bloqueio e 2 de passagem; validação de `commitlint` e de nome de *branch*.
- Integração: `make bootstrap && make check && make up` num contentor limpo; `curl /healthz` de cada serviço.
- Reprodutibilidade: dois `bootstrap` consecutivos produzem *lockfiles* idênticos (sem *drift*).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes unitários e de integração verdes.
- [ ] Documentação actualizada (README de arranque, ADR local da toolchain); Conventional Commits; sem TODOs órfãos.
- [x] **Dependências** — versões fixadas por lockfile com *hash*; lista de bloqueio activa e testada; licenças registadas.
- [x] **Sem segredos** — nenhum segredo no repositório; `.env.example` só com *placeholders*.
- [x] O compose de desenvolvimento não expõe portas além de `localhost`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-001 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-001), ../docs/tecnica/09_Topologia_Operacao_Escala.md (§3.1, §7) e
../docs/tecnica/08_Seguranca_Conformidade.md (§4.8). Objectivo: monorepo, estrutura de serviços e toolchain reprodutível.
- Cria a árvore services/packages/libs/db/registry/infra/tools; /healthz por serviço; make bootstrap/check/up.
- Impõe lockfiles com hash (pnpm --frozen-lockfile --ignore-scripts; pip --require-hashes) e a lista de
  bloqueio (langgraph-api, langgraph-runtime-inmem, Dify, n8n, Typebot, MinIO, LiteLLM < 1.83.0) com testes.
- Impõe Conventional Commits com KAM-NNN e nomes de branch; Renovate com quarentena ≥ 7 dias.
- Compose de dev: Postgres 18.6 + pgvector 0.8.7 e Redis-compatível com AOF, imagem parametrizada (D12 aberta).
- Fixa Node 24 LTS e Hono 4.13.x (não o 5.0.0-rc.0); regista o intervalo de Node do Medusa em docs/evidencia.
Não expandas escopo: gates de CI são KAM-002; digests/cosign são KAM-067; schema é KAM-003.
Testes: unit (lint_arch), integração (bootstrap limpo), reprodutibilidade. Abre PR com o template do §7.
```

---

## KAM-002 — Pipeline de CI base: gates fail-closed (build, lint, tipos, unit, secrets, SBOM, licenças)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001 |
| Bloqueia | KAM-004, KAM-030, KAM-067, KAM-068, KAM-078, KAM-111, KAM-131, KAM-132, KAM-133, KAM-134, KAM-135, KAM-136, KAM-137, KAM-138, KAM-142 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `specs/01_Engineering_Standards_e_Handoff.md` §4, `../docs/tecnica/09_Topologia_Operacao_Escala.md` §7, `../docs/tecnica/08_Seguranca_Conformidade.md` §4.8, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, ADR-002, ADR-014 |

### Contexto

O Engineering Standards define 18 gates fail-closed; este ticket entrega o **esqueleto** do pipeline e os gates que não dependem de código de negócio: 1 (build), 2 (lint/tipos), 3 (referências cruzadas), 4 (unit e cobertura), 9 (segredos) e 11 (SCA, licenças, SBOM). Os gates 5–8 (integração, isolamento, contratos, migrações) são activados pelos tickets que criam o que eles testam (KAM-003, KAM-004, KAM-007, KAM-024); assinatura e digests são KAM-067; deploy é KAM-078. O pipeline usa OIDC, sem chaves estáticas (`../docs/tecnica/08` §4.8).

### Objectivo

Disponibilizar um pipeline de CI em que todo o PR passa pelos gates acima, com limiares e excepções em ficheiros versionados, de modo que nenhum gate possa ser contornado sem decisão registada.

### Critérios de Aceitação

- [x] Os *required checks* da *branch* principal incluem os gates 1, 2, 3, 4, 9 e 11; um PR sem eles verdes não faz *merge* (verificado por um PR de teste deliberadamente vermelho por gate: 6 PR, 6 bloqueios).
- [x] Gate 3: `tools/lint_refs` falha se um PR citar `KAM-NNN` fora do backlog mestre, `ADR-NNN` fora de `../docs/tecnica/00` §8 ou `D#` fora de §13.3; passa em 100% das referências existentes.
- [x] Gate 4: os limiares vivem em `ci/thresholds.yaml` (proposta inicial do Standards §4.1: ≥ 90% em dinheiro, isolamento e validador; ≥ 75% no restante); descer 1 ponto abaixo falha o gate.
- [ ] Gate 9: um segredo-canário (formato de chave de API) numa *fixture* de teste falha o PR; o mesmo segredo fora das áreas permitidas em `ci/secrets-allow.yaml` falha sempre; o *hook* de *pre-commit* aplica o mesmo scanner.
- [x] Gate 11: gera SBOM CycloneDX por serviço e arquiva-o 90 dias; falha com vulnerabilidade crítica sem excepção registada, com licença fora da *allowlist* (`ci/licenses.yaml`, proposta: MIT, Apache-2.0, BSD, ISC, PostgreSQL, MPL-2.0) ou com pacote da lista de bloqueio.
- [x] Excepções (*waivers*) só em `ci/waivers.yaml` com `adr_ou_aprovacao`, `autor`, `expira_em` ≤ 30 dias (proposta); um *waiver* sem referência ou expirado faz o pipeline falhar.
- [x] O pipeline autentica-se por OIDC; `grep` de chaves estáticas nos workflows devolve 0.
- [x] Tempo total do PR típico ≤ 10 min no p95 de 20 execuções (proposta, a calibrar).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#4`, ramo `feature/KAM-002-pipeline-ci-gates`.
Fundido em `main` a 2026-10-11 (`4c1fdf2`). Cada caixa marcada acima tem uma linha aqui; **as três não marcadas também**, e
é por isso que esta secção existe — uma caixa marcada sem evidência nomeada é
pior do que uma caixa vazia.

| CA | Estado | Evidência |
|---|---|---|
| *Required checks* + 6 PR, 6 bloqueios | **satisfeito** | *Ruleset* `main: gates fail-closed do KAM-002` (id 24879081), espelhado em `.github/rulesets/main.json`, com **sete** contextos exigidos. PRs #5–#10, um por gate, cada um bloqueado pelo seu: tabela em `../docs/ci.md` §8. Os PRs foram fechados; os *runs* do Actions sobrevivem |
| Gate 3 (`lint_refs`) | **satisfeito** | 7029 referências em 236 ficheiros, 0 inválidas, medido no CI. PR #6 (`KAM-999`) bloqueado. 46 casos unitários |
| Gate 4 (limiares) | **satisfeito** | `ci/thresholds.yaml` com os dois estratos do §4.1. `test_trunca_e_nao_arredonda`: 74,9% falha, 75,0% passa. PR #7 a 66% bloqueado |
| Gate 9 (canário) | **parcial** | Duas das três partes: o canário fora das áreas permitidas é detectado (`make ci-9` copia-o para fora e exige ≥ 9 achados; dá 17), e o `pre-commit` usa o mesmo *scanner*. A primeira parte — «um canário numa *fixture* de teste falha o PR» — **não** se cumpre à letra: a pasta do canário é uma área permitida, porque é o canário que prova que o *scanner* funciona. É uma leitura do CA, está escrita em `../docs/ci.md` §3, e precisa de decisão de quem escreveu o critério |
| Gate 11 (SBOM, licenças, CVE) | **satisfeito** | 9 SBOM CycloneDX 1.6, artefacto com 90 dias. 99 componentes, 90 com licença permitida. 90 terceiros consultados na OSV, 0 `CRITICAL`; detecção provada com `lodash@4.17.11` → `GHSA-jf85-cpcp-j695`. PR #10 (licença retirada da *allowlist*) bloqueado. Lista de bloqueio: `lint_arch` conforme |
| *Waivers* | **satisfeito** | `tools/ci_waivers.py` exige `adr_ou_aprovacao`, `autor`, `expira_em` ≤ 30 dias; recusa expirados e sem referência. Lacunas conhecidas (data impossível aceita, prazo contado de hoje) em `../docs/ci.md` §7, lacuna 13 |
| OIDC, 0 chaves estáticas | **satisfeito** | `grep -rn "secrets\." .github/` devolve 0. Nota: nenhum passo autentica hoje, pelo que o `id-token: write` é privilégio sem uso — registado em `../docs/ci.md` §6 |
| p95 ≤ 10 min em 20 execuções | **satisfeito** | **24** execuções completas do *workflow*, nenhuma cancelada: p95 **68 s**, mediana 43 s, máximo 72 s, 0 acima de 600 s. Medido com `gh run list --workflow ci.yaml` sobre a diferença entre `createdAt` e `updatedAt`. Esteve **por marcar** enquanto havia 17 execuções — a margem já não deixava dúvida, mas 17 não são 20. O tempo subiu de 47 s para 68 s com a entrada do *gate* 8, que levanta um PostgreSQL |
| DoD: todos os CA satisfeitos | **não satisfeito** | Um CA em aberto: o gate 9 à letra. O p95 fechou com 24 execuções |
| DoD: ≥ 1 revisor (2 se alterar regras de bloqueio) | **não satisfeito** | Este PR **altera regras de bloqueio** — a *allowlist* de licenças perdeu três entradas e os limiares entraram — pelo que o DoD pede **dois** revisores humanos. A revisão adversarial (`../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md`, 24 achados) é evidência, não é um revisor: não a conto como tal |

> **O que isto custa, dito com clareza.** O ticket está fundido e **não está
> fechado**: falta um critério — o canário à letra — e a revisão humana, que o
> *ruleset* deixou de impor (`../docs/ci.md` §7, lacuna 16). O que está feito está medido; o que falta está
> nomeado. Marcar as dez caixas e deixar as quatro por marcar é a diferença
> entre um DoD que serve de controlo e um DoD que serve de decoração.

### Detalhes Técnicos

- **Componentes:** transversal. Plataforma de CI: GitHub Actions como proposta (confirmar com o alojamento do código; nenhuma lógica fica presa à plataforma — os gates são alvos `make ci-<gate>`).
- **Ficheiros:** `.github/workflows/ci.yaml`, `ci/{thresholds,waivers,licenses,secrets-allow}.yaml`, `tools/lint_refs/`, `tools/blocklist.yaml` (de KAM-001).
- **Âmbito vs KAM-067:** aqui SBOM e *allowlist* de licenças por PR; KAM-067 acrescenta digests, cosign, quarentena obrigatória e bloqueio de imagens. Não duplicar: o gerador de SBOM é reutilizado.
- **Gates adiados:** o workflow reserva *jobs* nomeados para os gates 5–8 que falham (*fail-closed*) se o ticket respectivo ainda não os implementou, excepto se houver *waiver*; assim nenhum fica esquecido.

### Testes Requeridos

- Unit: `lint_refs` (referências válidas, `KAM-999`, `ADR-020`, `D13`); validação do esquema de `waivers.yaml`.
- Integração: 6 PR de teste vermelhos (um por gate) e 1 verde; *waiver* expirado a falhar.
- Segurança: canário de segredo detectado pelo CI e pelo *pre-commit*.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor (2 se alterar regras de bloqueio ou limiares); testes verdes.
- [x] Documentação actualizada (`docs/ci.md` com tabela gate → alvo → dono); Conventional Commits.
- [x] **Sem segredos** — scan de segredos limpo no próprio repositório; autenticação por OIDC.
- [x] **Dependências** — SBOM gerado; licenças permitidas; lista de bloqueio activa.
- [x] Nenhum gate marcado *skip* sem ADR ou aprovação registada em `ci/waivers.yaml`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-002 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-002), specs/01_Engineering_Standards_e_Handoff.md §4 e
../docs/tecnica/09_Topologia_Operacao_Escala.md §7. Objectivo: pipeline de CI com os gates 1, 2, 3, 4, 9 e 11.
- Cada gate é um alvo make ci-<gate>; o workflow só os orquestra (sem lógica presa à plataforma de CI).
- Implementa tools/lint_refs (KAM/ADR/D#), limiares em ci/thresholds.yaml, scanner de segredos (CI +
  pre-commit), SBOM CycloneDX e allowlist de licenças, e ci/waivers.yaml com prazo e referência.
- Reserva jobs fail-closed para os gates 5–8 até os tickets respectivos os implementarem.
- OIDC, sem chaves estáticas. Não dupliques o âmbito de KAM-067 (digests, cosign, quarentena).
Não expandas escopo: sem deploy (KAM-078), sem SAST completo nem eval golden.
Testes: unit (lint_refs), 6 PR vermelhos + 1 verde, canário de segredo. Abre PR com o template do §7.
```

---

## KAM-003 — Schema `platform`: tenants, entitlements, tenant_channels e migrações reversíveis

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-001 |
| Bloqueia | KAM-004, KAM-005, KAM-008, KAM-009, KAM-012, KAM-014, KAM-016, KAM-042, KAM-047, KAM-052, KAM-086 |
| Responsável sugerido | Engenheiro de Dados |
| Documentos de referência | `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.1, §5.2, §11), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§7.1), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.3), ADR-006, ADR-011, ADR-015 |

### Contexto

TEN e CHR precisam de saber quem é cada tenant, que canais tem e o que pode fazer. O documento 03 §5.2 dá o DDL de `tenants`, `tenant_channels` e `entitlements`, e o documento 01 §7.1 dá uma versão mais rica de `tenant_channels`; os dois divergem em estados e colunas (03: `ativo|pausado|revogado` e `persona`; 01: `pendente|ativo|restrito|desligado|suspenso|encerrado`, `channel_mode`, `vertical`, `token_ref`, qualidade, *free tier*). O doc 00 §6.2 também inclui `restrito` no ciclo de vida do tenant, que o DDL de 03 omite. **Decisão deste ticket:** prevalecem o doc 00 (estados do tenant) e o doc 01 (colunas do canal); a divergência fica registada no PR para correcção de `../docs/tecnica/03`.

> **Emenda E-01 (Carta §7).** Este ticket tinha `KAM-111` nas dependências, e executa-se sem ele. A dispensa está registada na Carta com o que fica em dívida; os oito nomes de `platform` que o dicionário não tinha — chave de `tenants`, `tenants.tipo`, os seis estados do canal, `origem`, `channel_mode`, a tabela `entitlements` e os papéis de base de dados — entraram no dicionário §3.2 **antes** deste DDL, cada um com a razão da escolha. Duas decisões que valem a pena ler antes de abrir a primeira migração: a chave de `tenants` chama-se **`id`** (e não `tenant_id`), porque as quinze tabelas de dinheiro de `../docs/tecnica/04` já escrevem `REFERENCES platform.tenants(id)`; e o papel com `BYPASSRLS` chama-se **`kamba_batch`** (e não `kamba_ops`), a favor de `../docs/tecnica/08` §3.3. **O gate 8 (migrações) não existe e entra no âmbito deste ticket** — é alargamento decidido, não descoberto a meio.

### Objectivo

Criar, por migrações Alembic reversíveis, o schema `platform` com `tenants`, `tenant_channels` e `entitlements`, os papéis de base de dados e as regras de arranque que impedem o Fluxo B em produção do Piloto.

### Critérios de Aceitação

- [x] `alembic upgrade head` num PostgreSQL 18.6 vazio cria o schema; `downgrade base` deixa 0 objectos em `platform` (consulta ao catálogo); o ciclo `upgrade → downgrade → upgrade` passa no gate 8.
- [x] `tenants.estado` aceita exactamente `onboarding, ativo, restrito, suspenso, encerrado`; qualquer outro valor é rejeitado por `CHECK`.
- [x] `tenant_channels.estado` aceita `pendente, ativo, restrito, desligado, suspenso, encerrado`; `phone_number_id` é `UNIQUE`: inserir o mesmo valor para outro tenant falha com violação de unicidade.
- [x] `tenants_nif_uq` (único parcial para `nif` não nulo e não apagado) rejeita um segundo tenant com o mesmo NIF; dois tenants sem NIF coexistem.
- [ ] Nenhuma coluna de telefone em claro existe em `platform`: colunas com `msisdn`, `telefone` ou `phone` no nome só são aceites se forem `contacts.phone_hmac` ou `contact_endpoints.phone_enc` (lista fechada em teste de catálogo; as duas tabelas são criadas em KAM-008).
- [x] Os papéis `kamba_migrator` (DDL), `kamba_app` (`NOBYPASSRLS`, sem DDL) e `kamba_batch` (`BYPASSRLS`) existem; `CREATE TABLE` sob `kamba_app` falha.
- [ ] Com `KAMBA_FASE=piloto` o arranque do CHR/AGR falha se existir linha com `tenants.tipo='platform'`, `tenant_channels.origem='plataforma'` ou `vertical='assistente'` (teste de arranque, ADR-011).
- [x] Identificadores `uuid` (`gen_random_uuid()`), tempos `timestamptz` em UTC, `fuso_horario` por omissão `Africa/Luanda`.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#15`, ramo `feature/KAM-003-schema-platform`,
empilhado sobre o do KAM-002. **Nove caixas marcadas, seis vazias** — cada uma
com uma linha aqui. Os números são os do *run* do CI no *commit* `42c0a19`, e
reproduzem-se com `make ci-8`.

| CA | Estado | Evidência |
|---|---|---|
| 1 — ciclo `upgrade → downgrade → upgrade`, 0 objectos, *gate* 8 | **satisfeito** | *Gate* 8 verde no *runner*: **111 testes em 25,5 s** contra PostgreSQL 18.6 (imagem fixada por *digest*; há um teste que lê a versão do servidor). `test_upgrade_downgrade_upgrade` conta `pg_class` + `pg_proc` + `pg_type` em `platform` e exige que o schema não exista. O `downgrade` recusa apagar um objecto que não criou (`DROP SCHEMA` sem `CASCADE`) |
| 2 — `tenants.estado`, exactamente cinco | **satisfeito** | Os cinco entram; o domínio é lido **do catálogo** (`pg_get_constraintdef`) e comparado por igualdade de conjuntos; `pausado` e `revogado` — os do DDL antigo do doc 03 — são rejeitados com `23514`. Mutação «estado a mais»: apanhada |
| 3 — `tenant_channels.estado`, seis; `phone_number_id` único | **satisfeito** | Idem para os seis. O mesmo `phone_number_id` noutro tenant falha com `23505`. Mutação «`UNIQUE` retirado»: apanhada |
| 4 — `tenants_nif_uq` parcial | **satisfeito** | Segundo tenant com o mesmo NIF rejeitado; dois sem NIF coexistem; o NIF de um tenant apagado fica livre. Acrescentado depois da revisão: `nif = ''` e NIF com espaços à volta são rejeitados por `CHECK` — antes, dois tenants «sem NIF» que gravassem a cadeia vazia colidiam no índice |
| 5 — nenhuma coluna de telefone em claro; lista fechada de **duas** | **não satisfeito** | **O ticket contradiz-se.** Este critério dá uma lista fechada de duas colunas com `phone` no nome (`contacts.phone_hmac`, `contact_endpoints.phone_enc`); o critério 3 **exige** `tenant_channels.phone_number_id`. A lista implementada tem **três** entradas, com a razão: é o identificador opaco que a Meta atribui ao número do negócio, não um telefone. À letra, três não são duas. O que se cumpre: nenhuma coluna guarda telefone em claro, e há um **inventário fechado** de todas as colunas de `platform` com a resposta a «guarda dados pessoais?» — uma coluna nova falha até ser declarada (mutação «coluna de contacto em claro»: apanhada). **Precisa de emenda ao critério**, que é de quem o escreveu |
| 6 — três papéis; `CREATE TABLE` sob `kamba_app` falha | **satisfeito** | Os três existem com os atributos certos; só `kamba_batch` contorna a RLS. `CREATE TABLE` sob `kamba_app` falha com `42501` em `platform`, em `public` **e como tabela temporária** (o `PUBLIC` perdeu `TEMPORARY` na base). Depois da revisão mede-se o efeito e não só o atributo: pertenças vazias, matriz exacta de privilégios por tabela e por coluna, `pg_default_acl` vazio. Mutações «membro de `kamba_batch`», «`TEMPORARY` ao `PUBLIC`», «`BYPASSRLS` na aplicação»: apanhadas |
| 7 — com `KAMBA_FASE=piloto`, **o arranque do CHR/AGR falha** | **não satisfeito** | A guarda existe (`kamba_core.fluxo_piloto`), recusa as três condições contra linhas reais, falha fechada quanto à variável e recusa correr se não conseguir provar que vê todas as linhas. **Mas nenhum serviço a chama**: o CHR nasce no KAM-014 e o AGR ainda não abre ligação à base. Nenhum arranque falha, e é isso que o critério diz. **Precisa de emenda** — a guarda fica aqui; a chamada no arranque passa a critério do KAM-014 e do ticket que der base de dados ao AGR |
| 8 — `uuid`, `timestamptz` em UTC, `Africa/Luanda` | **satisfeito** | `id` com omissão `gen_random_uuid()` nas duas tabelas que o têm; todas as colunas `_at` são `timestamp with time zone` e não há `timestamp without time zone` em lado nenhum; `fuso_horario` com omissão `'Africa/Luanda'`. Mutação «`timestamp` sem fuso»: apanhada |
| DoD — todos os CA satisfeitos | **não satisfeito** | Dois em aberto: o 5 e o 7. Ambos por o critério, não por o código |
| DoD — 2 revisores; testes verdes; cobertura ≥ limiar | **não satisfeito** | Testes verdes e cobertura de 78% (limiar 75%). **Zero revisores humanos.** A revisão adversarial (`../docs/analises/ANALISE-03-KAM-003-schema-platform.md`, 16 achados) é evidência, não é um revisor |
| DoD — documentação; divergência com o doc 03 §5.2 registada | **satisfeito** | Ver «Divergências» abaixo; `db/migrations/README.md`; `../docs/ci.md` §3, *gate* 8 |
| DoD — isolamento: `tenant_id` presente e indexado | **satisfeito** | `tenant_id` é `NOT NULL` nas duas tabelas que o têm e vem **primeiro** num índice de cada uma (mutação «ordem do índice trocada»: apanhada). `tenants` não tem `tenant_id`: a sua chave é `id` |
| DoD — privacidade: telefone nunca em claro; **sem PII no schema** | **não satisfeito** | Telefone: nenhum, nem em claro nem como chave. Mas «sem PII» não se cumpre à letra: `contacto_negocio_enc` é um dado de contacto (cifrado em aplicação, `bytea`), e o `nif` de um empresário em nome individual é um dado pessoal. O DDL é o do desenho; a frase do DoD é que é mais forte do que o desenho |
| DoD — migrações reversíveis, `downgrade` no *gate* 8 | **satisfeito** | CA 1 |
| DoD — o DDL não modela saldos nem **tenants `platform` activos** | **não satisfeito** | Saldos: nenhuma coluna de dinheiro em `platform` (teste de catálogo). Mas o DDL **aceita** um tenant `tipo = 'platform'` com `estado = 'ativo'` — é a costura do ADR-011, e o que o impede em produção do Piloto é a guarda de arranque, não o schema. Um `CHECK` que o proibisse fechava a costura; não foi posto para não a fechar em silêncio. **É decisão**, e está devolvida |

#### Divergências entre fontes, e o que se decidiu

O DoD pede-as registadas. São seis, e três não constam das 12 que o KAM-111
enumera:

| # | Divergência | Decisão |
|---|---|---|
| 1 | `tenants.estado` sem `restrito` no doc 03 §5.2 | Segue-se o doc 00 §6.2 e o dicionário: cinco estados. Coberta pelo KAM-111 (D-08) |
| 2 | `tenant_channels`: três estados e `persona` no doc 03; seis estados e treze colunas a mais no doc 01 §7.1 | Segue-se o doc 01, como o Contexto deste ticket decidia. **Não coberta pelo KAM-111** — o doc 03 §5.2 fica errado até alguém o emendar |
| 3 | Papel com `BYPASSRLS`: `kamba_ops` (doc 03 §5.5, doc 04 §6) contra `kamba_batch` (doc 08 §3.3) | `kamba_batch` (dicionário §3.2, emenda 1.2). O `REVOKE … FROM PUBLIC, kamba_app, kamba_ops` do doc 04 revoga de um papel que não existirá. **Não coberta pelo KAM-111** |
| 4 | `canal` e `criado_at` existem em `tenant_channels` no doc 03 e não no doc 01 | Ficam de fora, porque o ticket manda seguir as colunas do doc 01. **O canal não tem data de criação.** Se fizer falta, é uma revisão aditiva |
| 5 | Critério 5 (lista de duas) contra critério 3 (`phone_number_id`) | Três entradas, com razão; a caixa do critério 5 fica vazia |
| 6 | `valor_max_pedido_kz` (doc 02) contra `valor_max_pedido_minor` (dicionário §3.2) | Não toca este DDL — `limites` é `jsonb` e as chaves são do KAM-009 — mas é uma chave de `entitlements`, e **não consta das 12 do KAM-111** |

#### Desvios à letra do ticket

- **`tests/factories`** vive em `db/tests/factories.py`: a convenção do
  repositório (KAM-001) é testes por pacote, e não há `tests/` na raiz.
- **O driver é o `pg8000`**, não o `psycopg`: a *allowlist* de licenças do
  KAM-002 nega a família LGPL. Registado em `db/requirements/migrations.in`.
- **A vertical tem `CHECK` de forma** e a guarda compara por lista de
  permitidas — mais largo do que o critério 7, que nomeia só `assistente`.
- **«Migração com dados preservados nas colunas aditivas»** (Testes Requeridos)
  não é exercitável com uma só revisão. Há um teste que prova que reaplicar
  `upgrade head` não toca nas linhas, e a classe onde o caso real deve entrar
  quando houver uma revisão `0002`.

#### O que fica por decidir, e de quem é

1. **Quem altera `tenants.plano`, `estado` e `verificado_at`.** `kamba_app` pode,
   e com a RLS do KAM-004 um contexto de tenant altera o próprio plano. Nenhum
   documento o diz. KAM-004 ou KAM-009.
2. **A relação entre `deleted_at` e `estado`**, e entre o estado do tenant e o dos
   seus canais. O schema aceita `deleted_at` preenchido com `estado = 'ativo'`.
3. **Com que papel corre a guarda do ADR-011** depois de a RLS entrar. KAM-004.
4. **Como se aplicam as migrações ao compose de desenvolvimento.** A rede de
   dados é interna; é infra-estrutura de ambiente (KAM-075).

#### Prova por mutação

`python db/mutacoes.py` — vinte alterações deliberadamente erradas, uma de cada
vez, em cópia fora do repositório: **20 apanhadas, 0 sobreviventes**. A tabela
está em `../docs/analises/ANALISE-03-KAM-003-schema-platform.md` §4, com a
história de porque a primeira prova por mutação estava errada.

### Detalhes Técnicos

- **Componentes:** TEN (tenants, entitlements), CHR (canais). Schema `platform`; o schema `medusa` é do Medusa (KAM-042) e as FK entre os dois são lógicas (texto), nunca de base de dados (`../docs/tecnica/03` §5.1).
- **`tenants`:** DDL de `../docs/tecnica/03` §5.2 com `estado` ampliado; `owner_contact_id` sem FK nesta migração (a FK diferida a `contacts` entra em KAM-008, ordem `tenants → contacts → tenant_channels`).
- **`tenant_channels`:** colunas de `../docs/tecnica/01` §7.1 (`waba_id`, `waac_id` nulo, `phone_number_id`, `channel_mode` ∈ `coexistencia|cloud_only`, `vertical`, `origem`, `estado`, `token_ref`, `quality_rating`, `messaging_limit`, `free_tier_used`, `free_tier_month`, `coexistence_synced_at`, `last_account_update_at`). A *persona* não é coluna: deriva do registo da vertical (ADR-012).
- **`entitlements`:** `(tenant_id, modulo)` com `limites jsonb`; o registo de chaves e a aplicação são KAM-009.
- **Migrações:** Alembic, uma revisão por PR, `upgrade` e `downgrade` obrigatórios, DDL só por `kamba_migrator`; padrão *expand → migrate → contract* (`../docs/tecnica/03` §11). RLS é activada em KAM-004; esta migração apenas garante `tenant_id` indexado em primeiro lugar nos índices compostos.
- **Fixtures:** fábricas de tenants/canais para testes (`tests/factories`), sem dados reais.

### Testes Requeridos

- Migração: subir/descer/subir; migração com dados de teste preservados nas colunas aditivas.
- Constraints: um caso negativo por `CHECK`/`UNIQUE` listado acima.
- Catálogo: sem colunas de telefone; papéis e privilégios; teste de arranque do Fluxo B.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (P0 que toca dados de tenant e isolamento); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada; divergência com `../docs/tecnica/03` §5.2 registada; Conventional Commits.
- [x] **Isolamento de tenant** — `tenant_id` presente e indexado em todas as tabelas de negócio, pronto para a RLS de KAM-004.
- [ ] **Privacidade** — telefone nunca em claro nem como chave; sem PII no schema.
- [x] **Migrações reversíveis** — `downgrade` testado no gate 8.
- [ ] **Plataforma sem fundos / Fluxo A** — o DDL não modela saldos nem tenants `platform` activos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-003 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-003), ../docs/tecnica/03_Core_Comercio_Medusa.md (§5.1, §5.2, §11) e
../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§7.1). Objectivo: schema platform com migrações Alembic reversíveis.
- tenants (estado inclui 'restrito', doc 00 §6.2), tenant_channels (colunas do doc 01 §7.1), entitlements.
- Papéis kamba_migrator, kamba_app (NOBYPASSRLS), kamba_batch (BYPASSRLS); DDL só pelo migrator.
- NÃO crias contacts (KAM-008) nem activas RLS (KAM-004). Sem colunas de telefone.
- Arranque: com KAMBA_FASE=piloto, falha se existir tipo 'platform', origem 'plataforma' ou vertical 'assistente'.
- Regista no PR a divergência entre ../docs/tecnica/03 §5.2 e ../docs/tecnica/01 §7.1 e a decisão tomada.
Não expandas escopo: sem tabelas de encomendas, pagamentos ou eventos.
Testes: migração up/down/up, constraints negativas, catálogo (sem telefone), arranque. Abre PR com o template do §7.
```

---

## KAM-004 — RLS `FORCE` por `app.tenant_id` e suite de isolamento SQL

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-002, KAM-003 |
| Bloqueia | KAM-014, KAM-015, KAM-028, KAM-044, KAM-047, KAM-053, KAM-066, KAM-142 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.1, §3.3, §3.7), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§4.4 ISO-39..42, §5.5), `../docs/tecnica/00_Arquitectura_Solucao.md` (§9), ADR-015, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.9) |

### Contexto

A ToolLayer injecta o `tenant_id` do estado (primeira barreira); a RLS `FORCE` é a segunda, que devolve 0 linhas mesmo que a primeira falhe (`../docs/tecnica/08` §3.1). O padrão é o de `../docs/tecnica/03` §5.5: política `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, `SET LOCAL` por transacção (compatível com *pooling* em modo transacção) e falha fechada sem contexto. A suite de isolamento é o gate 6 do pipeline: uma fuga reprova o build (doc 00 §9: 0 leituras cruzadas).

> **Herdado do KAM-003 — três coisas que este ticket tem de saber antes de ligar a RLS.**
>
> 1. **A guarda do ADR-011 fica cega sob RLS, e recusa correr.** `kamba_core.fluxo_piloto.verificar_arranque` conta linhas de Fluxo B; com `FORCE ROW LEVEL SECURITY`, `kamba_app` sem contexto de tenant vê zero. A guarda prova primeiro que vê tudo e levanta `GuardaCega` se não conseguir — ensaiado no *gate* 8 com uma política igual à deste ticket. Consequência: **depois deste ticket, a guarda só corre com um papel que contorne a RLS** (`kamba_batch`, ou o `kamba_resolver` que este ticket introduz). Qual deles é decisão deste ticket, e entra nos seus critérios de aceitação.
> 2. **`kamba_app` não tem `DELETE` em nenhuma tabela de `platform`, e tem `UPDATE` por coluna.** Não pode alterar `tenants.tipo`, `tenant_channels.origem` nem `tenant_channels.tenant_id`. Uma tabela nova segue a mesma regra, ou diz porque não.
> 3. **Fica por decidir quem altera `tenants.plano`, `estado` e `verificado_at`.** Hoje `kamba_app` pode — e com a política `id = app.tenant_id`, um contexto de tenant altera o **próprio** plano. Nenhum documento do desenho diz quem o deve fazer. Não foi decidido no KAM-003 para não o decidir em silêncio; é deste ticket ou do KAM-009.

### Objectivo

Impor RLS `ENABLE` + `FORCE` com política a todas as tabelas com `tenant_id`, fornecer o *helper* de transacção com contexto de tenant (TS e Python) e entregar a suite SQL de isolamento (X-03, X-04, X-05) como gate de CI.

### Critérios de Aceitação

- [x] Teste de catálogo X-05: 100% das tabelas com coluna `tenant_id` nos schemas aplicacionais têm `relrowsecurity` e `relforcerowsecurity` verdadeiros e ≥ 1 política; a lista de excepções `ci/rls_exceptions.yaml` exige ADR e está inicialmente vazia.
- [x] X-03: com sessão `kamba_app` e `app.tenant_id` = A, `SELECT *` em cada tabela com `tenant_id` devolve 0 linhas com o canário de B (canários únicos semeados em todas as tabelas dos dois tenants).
- [x] X-04: sem `SET LOCAL` (ou com valor vazio), cada tabela devolve 0 linhas; `INSERT` sem contexto falha.
- [x] Escrita cruzada: `INSERT` com `tenant_id` de B sob contexto A falha por `WITH CHECK`; `UPDATE`/`DELETE` sobre linhas de B afectam 0 linhas.
- [x] Reutilização de ligação: transacção 1 com contexto A seguida de transacção 2 sem contexto na mesma ligação devolve 0 linhas (o contexto não vaza entre transacções).
- [x] Nenhuma função `SECURITY DEFINER` fora de `ci/secdef_allowlist.yaml` e nenhuma vista sem `security_invoker = true` (teste sobre `pg_proc`/`pg_class`).
- [x] O papel `kamba_resolver` (leitura estreita de `tenant_channels`/`tenants` para resolver `phone_number_id → tenant` antes de existir contexto) só tem `SELECT` nas colunas necessárias, por política `TO kamba_resolver`; não consegue ler outras tabelas.
- [x] A suite corre no gate 6 e falha o build; tempo total ≤ 3 min (proposta).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#16`, ramo `feature/KAM-004-rls-force-e-isolamento`.
**Treze caixas marcadas, duas vazias** — cada uma com uma linha aqui. Os números
são os do *run* do CI no *commit* `d39afa6`, e reproduzem-se com `make ci-6` e
`make ci-8`. A revisão adversarial
([`ANALISE-07`](../docs/analises/ANALISE-07-KAM-004-rls-e-isolamento.md)) **não
aprovou** a primeira versão: três destes critérios (1, 6 e 7) só passaram a
cumprir-se depois dela.

| CA | Estado | Evidência |
|---|---|---|
| 1 — X-05 pelo catálogo; excepções exigem ADR, lista vazia | **satisfeito** | *Gate* 6 verde no *runner*: **64 testes em 4,6 s** contra PostgreSQL 18.6. `verificar_rls` descobre as tabelas pelo catálogo, em todos os schemas que não são de sistema — **incluindo `public`**, que a primeira versão excluía — e exige `ENABLE`, `FORCE` e ≥ 1 política. Uma coluna com nome de tenant que não seja `tenant_id` falha (`verificar_colunas_de_tenant`). Regressões: tabela sem RLS, só com `ENABLE`, noutro schema, em `public`, particionada (mãe e partição). `ci/rls_exceptions.yaml` recusa uma entrada sem `ADR-NNN` e está vazia; uma excepção morta falha |
| 2 — X-03: contexto A não vê o canário de B | **satisfeito** | Parametrizado sobre as tabelas descobertas; cada caso afirma primeiro que A **vê as suas** (uma base vazia passava trivialmente). A revisão tentou dezoito vias à mão sem tirar uma linha |
| 3 — X-04: sem contexto, 0 linhas; `INSERT` falha | **satisfeito** | Sem `set_config` e com valor vazio, em todas as tabelas; o `INSERT` é recusado **pela política** — confere-se o texto do erro, porque `42501` é também o código de um privilégio em falta |
| 4 — escrita cruzada | **satisfeito** | `INSERT` com o tenant de B sob contexto A falha por `WITH CHECK`; `UPDATE` afecta 0 linhas. **`DELETE` e a mudança de `tenant_id` provam-se com o dono das tabelas** (`kamba_migrator`, sujeito à política por causa do `FORCE`): `kamba_app` não tem esses privilégios desde o KAM-003, e com ele o teste passaria pela razão errada |
| 5 — reutilização de ligação | **satisfeito** | Depois de `COMMIT` e depois de `ROLLBACK`, a transacção seguinte sem contexto vê 0 linhas; A seguido de B vê só B. Provado também pelo *helper* `tx` real. O que fica **fora** da letra — `SET` de sessão — está declarado em `../docs/isolamento.md` §1 |
| 6 — sem `SECURITY DEFINER` fora da lista; sem vistas sem `security_invoker` | **satisfeito** | Verificado em todos os schemas aplicacionais, **`public` incluído**: a revisão mostrou uma função e uma vista em `public` a lerem todos os tenants sem que a primeira versão as visse. `ci/secdef_allowlist.yaml` exige ADR e está vazia. Uma vista materializada falha sempre |
| 7 — `kamba_resolver`: só `SELECT`, nas colunas necessárias, por política própria; não lê outras tabelas | **satisfeito** | Colunas legíveis conferidas nos dois sentidos contra o catálogo (7 em `tenant_channels`, 3 em `tenants`); `token_ref`, `waba_id`, `nome`, `nif` e `entitlements` recusados. **«Só `SELECT`» passou a estar medido depois da revisão**: a recusa de escrita tem de ser por privilégio (`permission denied`) e não pela política, tenta-se escrever com contexto próprio, e o papel está na matriz exacta do *gate* 8. Antes, um `GRANT INSERT` ao resolvedor passava nos dois *gates* |
| 8 — corre no *gate* 6 e falha o build; ≤ 3 min | **satisfeito** | O *job* `gate 6 — isolamento de tenant` está nos `needs` do resumo, que é verificação obrigatória do ramo `main`. **37 s** no *runner*. O limite de 3 min **não é imposto** por nada: a suite tem um tecto de 600 s e o *job* não tem `timeout-minutes` |
| DoD — todos os CA satisfeitos | **satisfeito** | Os oito acima |
| DoD — 2 revisores; testes verdes; cobertura ≥ 90% | **não satisfeito** | Testes verdes; estrato `critico` a **100%** (332 de 332 linhas, os dois *helpers*). **Zero revisores humanos** — o *ruleset* exige 0 aprovações (lacuna 16 de `../docs/ci.md` §7). A revisão adversarial é evidência, não é um revisor, e as correcções que ela motivou não foram revistas por uma segunda ronda |
| DoD — documentação; Conventional Commits | **satisfeito** | `../docs/isolamento.md` (v1.1), `../docs/ci.md` (*gate* 6), `db/migrations/README.md`, dicionário §3.2 (emenda 1.5) |
| DoD — isolamento: o teste cruzado cobre todas as tabelas actuais e falha o build | **satisfeito** | As três tabelas vêm do catálogo, e há um teste que falha se a descoberta encolher ou se uma tabela não tiver receita de sementes |
| DoD — privacidade: o *helper* não regista | **satisfeito** | Os dois módulos não importam nenhuma biblioteca de registo (há teste) e nenhuma mensagem de erro repete o tenant nem o valor recebido |
| DoD — migrações reversíveis: `downgrade` das políticas testado | **satisfeito** | Pelo **efeito**, parando em `0001`: RLS desligada nas três tabelas, zero políticas, zero privilégios do resolvedor; e de volta a `head` o estado é o mesmo. Antes da revisão o ciclo ia sempre até `base`, e um `downgrade` da `0002` que não desfizesse nada passava |
| DoD — métrica `rls_context_missing_total` e contador de `kamba_batch` | **não satisfeito** | Os dois contadores existem nos *helpers* e têm teste. Mas são **em memória** — não há pilha de métricas que os recolha — e `rls_context_missing_total` só conta as **recusas do *helper***: uma transacção que chegue à base sem contexto por outro caminho não é contada. O DoD descreve-a como «transacções sem contexto» |

#### Decisões tomadas neste ticket

- **A guarda de arranque do ADR-011 corre como `kamba_resolver`** — a decisão
  que a nota herdada do KAM-003 deixava aqui. Tem leitura total por política
  própria e só nas colunas de que a guarda precisa; `kamba_app` continua a ser
  recusado (`GuardaCega`). Não entrou como critério de aceitação novo: está
  medida no *gate* 8 (`TestGuardaComRls`).
- **A política chama-se `tenant_iso`**, o nome do ticket e de `../docs/tecnica/08`
  §3.3; `../docs/tecnica/03` §5.5 chama-lhe `tenant_isolamento`. Registado no
  dicionário §3.2; o doc 03 fica por corrigir.
- **Os *helpers* recusam uma segunda transacção na mesma ligação.** Não estava
  no ticket; a revisão mostrou que sem isso o pedido de um tenant lia as linhas
  de outro.

#### Desvios à letra do ticket

- **`db.tx(tenant=t)`** é `kamba_core.tenant_guard.tx(conexao, tenant)` em
  Python e `comTenant(cliente, tenant, trabalho)` em TypeScript: não há módulo
  `db` partilhado, e o *helper* recebe a ligação em vez de a abrir.
- **«50 transacções paralelas»** são 5 ligações com 10 transacções cada — 50
  transacções, no máximo 5 em simultâneo.
- **O *overhead* da política** mede-se e regista-se em cada execução (sem
  limiar, como o ticket pede): +0,01 ms nas três consultas, no *runner*.

#### O que fica por decidir, e de quem é

1. **Quem altera `tenants.plano`, `estado` e `verificado_at`.** Com a política
   `id = app.tenant_id`, um contexto de tenant altera o **próprio** plano. Não
   foi decidido aqui: passa ao **KAM-009**, que tem uma nota no seu bloco.
2. **Repor a sessão ao devolver uma ligação ao *pool***, quem pode inserir
   dados de Fluxo B, e `lock_timeout` nas migrações — `../docs/isolamento.md`
   §7, linhas 5 a 8. Sem ticket.
3. **As colunas do resolvedor** são as mínimas para hoje; revêem-se no KAM-014.

#### Prova por mutação

`python db/mutacoes.py` — **48 alterações deliberadamente erradas, uma de
cada vez, 48 apanhadas**, com a linha de base verde conferida antes. As
nove que a revisão mostrou sobreviverem à primeira versão dos testes estão lá.
A tabela está em `../docs/analises/ANALISE-07-KAM-004-rls-e-isolamento.md` §4,
com a história de a primeira prova ter estado vazia.

### Detalhes Técnicos

- **Componentes:** TEN, TLS (consumidor do *helper*), CHR (via `kamba_resolver`). Postgres 18.6.
- **Alembic helper:** `enable_tenant_rls(table, col='tenant_id')` emite `ENABLE`, `FORCE` e a política `tenant_iso` (USING + WITH CHECK); toda a migração futura de tabela com `tenant_id` usa-o, e o teste X-05 apanha esquecimentos.
- **Helper de transacção:** `db.tx(tenant=t)` executa `SELECT set_config('app.tenant_id', $1, true)` (equivalente a `SET LOCAL`); nunca `SET` de sessão. `kamba_batch` (`BYPASSRLS`) só em *jobs* nomeados e auditados.
- **Casos especiais (proposta, a validar na revisão):** a tabela `tenants` usa `id = app.tenant_id`; tabelas de eventos (KAM-005/006) aceitam `INSERT` sob RLS e são lidas pelo publicador como `kamba_batch`; `audit_log` com `tenant_id` nulo trata-se em KAM-012.
- **Desempenho:** índices compostos começam por `tenant_id`; medir o *overhead* da política em 3 consultas representativas e registar (sem limiar bloqueante).
- **Âmbito:** esta suite é a camada SQL; a suite ponta a ponta (rotas, tools, storage, injecção) é KAM-066.

### Testes Requeridos

- Isolamento: X-03, X-04, X-05 e os casos de escrita/ligação acima, parametrizados sobre todas as tabelas descobertas pelo catálogo.
- Regressão: uma migração de teste que cria tabela com `tenant_id` sem RLS deve fazer X-05 falhar.
- Concorrência: 50 transacções paralelas alternando A/B não vazam contexto.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (P0 de isolamento); testes verdes; cobertura ≥ 90% no código de isolamento.
- [x] Documentação actualizada (`docs/isolamento.md`); Conventional Commits.
- [x] **Isolamento de tenant** — o teste cruzado cobre todas as tabelas actuais e falha o build (ADR-015).
- [x] **Privacidade** — o *helper* não regista `tenant_id` associado a conteúdo; logs sem conteúdo.
- [x] **Migrações reversíveis** — `downgrade` das políticas testado.
- [ ] **Custo e observabilidade** — métrica `rls_context_missing_total` (transacções sem contexto) e contador de uso de `kamba_batch`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-004 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-004), ../docs/tecnica/08_Seguranca_Conformidade.md (§3.3, §3.7) e
../docs/tecnica/03_Core_Comercio_Medusa.md (§5.5). Objectivo: RLS FORCE em todas as tabelas com tenant_id + suite SQL.
- Helper Alembic enable_tenant_rls e helper de transacção (TS e Python) com set_config('app.tenant_id', ..., true).
- Papéis: kamba_app (NOBYPASSRLS), kamba_batch (BYPASSRLS, só jobs nomeados), kamba_resolver (leitura estreita).
- Testes X-03 (SELECT cruzado), X-04 (sem contexto = 0 linhas), X-05 (catálogo), escrita cruzada, vazamento
  entre transacções na mesma ligação, SECURITY DEFINER e vistas fora da allowlist.
- Semeia dois tenants com canários únicos em todas as tabelas. Corre como gate 6; falha o build.
Não expandas escopo: sem testes de rotas/tools/storage (KAM-066), sem tabelas novas de negócio.
Testes: os acima, mais regressão com migração sem RLS. Abre PR com o template do §7.
```

---

## KAM-005 — Outbox transaccional, publicador BullMQ e envelope de evento versionado

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-003 |
| Bloqueia | KAM-006, KAM-007, KAM-013, KAM-025, KAM-044, KAM-047, KAM-055, KAM-070, KAM-123 |
| Responsável sugerido | Engenheiro de Dados |
| Documentos de referência | `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§4, §6.1, §6.2, §6.5), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.10), `../docs/tecnica/00_Arquitectura_Solucao.md` (§7), ADR-009, ADR-010 |

### Contexto

O EVT é a espinha dorsal do esqueleto andante: `payment.confirmed` ou `payment.manual_confirmed` → `order.paid` → AGR e vertical Serviços. A tese (ADR-009) é escrever o evento na **mesma transacção** que o dado e publicá-lo depois, com semântica *at-least-once* e efeito exactamente-uma-vez por idempotência no consumidor. O DDL do documento 11 não chega (sem `tenant_id`, sem `agregado_seq`, sem recuo) e foi corrigido em `../docs/tecnica/06` §6.1. As garantias do BullMQ **não foram verificadas** (E4 §2.10): assume-se o pior caso (duplicados, perda da cauda do AOF) e a verdade é o outbox.

### Objectivo

Implementar o envelope v1, as tabelas `events_outbox`, `evt_agregado_seq`, `evt_subscricoes` e `events_log`, a função `evt_emitir` e o publicador de instância única que entrega a filas BullMQ particionadas.

### Critérios de Aceitação

- [ ] `evt_emitir` insere o evento na transacção do produtor: se esta faz *rollback*, não existe linha no outbox nem lacuna em `agregado_seq` (teste com 1 000 *rollbacks* aleatórios: sequências contíguas).
- [ ] Duas transacções concorrentes sobre o mesmo agregado serializam-se: `seq` 1 e 2 sem lacuna e ordem de `seq` igual à ordem de *commit* (100 repetições).
- [ ] *Kill -9* do publicador entre `add` e `COMMIT` → após reinício o evento é republicado e a fila de cada consumidor contém exactamente 1 *job* por `(consumer, event_id)` (`jobId = event_id`).
- [ ] Redis parado 60 s com 1 000 eventos emitidos: após o regresso, 100% publicados em ≤ 60 s, 0 perdidos; `tentativas` e `proxima_tentativa_at` recuam com *backoff*.
- [ ] Duas instâncias do publicador em simultâneo: só uma publica (lock consultivo); a outra assume em ≤ 10 s quando a líder morre (proposta).
- [ ] Um payload com padrão de telefone (`+244 9XXXXXXXX`, `"+<9-15 dígitos>"`) faz `evt_emitir` falhar com `check_violation`.
- [ ] O evento só é entregue a consumidores cuja `finalidade` está em `envelope.finalidades` (roteamento por finalidade); a *fan-out* usa 16 filas `evt.<consumer>.p0..p15` por `hash(tenant_id ‖ agregado.id) & 15`.
- [ ] Atraso outbox → fila com p95 ≤ 1 s a 50 eventos/s (proposta, a calibrar) e métricas `evt_outbox_lag_seconds`, `evt_publish_total`, `evt_publish_errors_total` expostas.

### Detalhes Técnicos

- **Componentes:** EVT. Publicador como processo de `services/worker-canal` ou serviço próprio `services/evt-publisher`; Redis-compatível com AOF `everysec` (perde ≤ 1 s; repõe o reconciliador de KAM-006).
- **DDL:** exactamente `../docs/tecnica/06` §6.1 (`events_outbox`, `evt_agregado_seq`, `evt_subscricoes`, `evt_emitir`) e §6.5 (`events_log` particionado por mês, imutável). Desvio permitido: se `uuidv7()` não existir no PG 18.6 fixado (INDÍCIO em `../docs/tecnica/06` §4), gerar UUIDv7 na aplicação e registar no PR.
- **Publicador (esboço de `../docs/tecnica/06` §6.2):**
```
líder = pg_try_advisory_lock(7101)            # valor do doc; réplicas em espera
loop: BEGIN; linhas = SELECT ... WHERE publicado_at IS NULL AND proxima_tentativa_at <= now()
        ORDER BY id LIMIT 200 FOR UPDATE SKIP LOCKED
      para cada subscrição activa com finalidade ∈ envelope.finalidades: add(jobId=event_id, attempts=6, backoff exp 1 s)
      INSERT events_log ... ON CONFLICT DO NOTHING; UPDATE publicado_at; COMMIT
```
- **RLS:** `INSERT` no outbox sob `kamba_app` com `WITH CHECK`; o publicador lê como `kamba_batch` (*job* nomeado e auditado). Retenção: outbox publicado 7 dias (*job* diário); partição de `events_log` M+2 criada no dia 1, falha = alerta Sev2.
- **Item NÃO VERIFICADO:** garantias de entrega do BullMQ (E4 §2.10); antes de fechar, ler a documentação sobre *jobs* parados e AOF e anexar nota ao PR.

### Testes Requeridos

- Unit: construção do envelope, partição por *hash*, guarda de PII, conversor de versão (gancho vazio).
- Integração (Postgres e Redis reais): *rollback*, concorrência por agregado, *kill -9*, Redis parado, eleição de líder.
- Carga: 50 eventos/s durante 5 min com medição de atraso; isolamento: produtor de A não emite com `tenant_id` de B (`WITH CHECK`).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (toca dinheiro indirectamente e dados de tenant); testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/eventos.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — RLS nas tabelas de eventos e teste cruzado do novo caminho.
- [ ] **Idempotência** — republicação não duplica *jobs* (`jobId`); teste de repetição incluído.
- [ ] **Privacidade** — envelope sem PII P2; só `contact_id`; logs sem conteúdo.
- [ ] **Custo e observabilidade** — métricas de atraso e erro desde o código (ADR-018).
- [ ] **Migrações reversíveis** — `downgrade` testado (sem perda de eventos publicados: aditivo).

### Handoff para Claude Code

```text
És o executor do ticket KAM-005 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-005) e ../docs/tecnica/06_Dados_Eventos_Analytics.md (§4, §6.1, §6.2, §6.5).
Objectivo: outbox transaccional, publicador BullMQ de instância única e envelope v1.
- Implementa o DDL do doc 06 §6.1/§6.5 e evt_emitir (guarda de PII incluída); migrações reversíveis.
- Publicador com advisory lock, FOR UPDATE SKIP LOCKED, jobId = event_id, 16 filas por consumidor, backoff e
  roteamento por finalidade; reposição do que o Redis perder fica para KAM-006.
- Verifica uuidv7() no PG 18.6 fixado; se faltar, gera na aplicação e regista no PR.
- Assume o pior caso do BullMQ (NÃO VERIFICADO): lê a documentação e anexa nota de evidência.
Não expandas escopo: consumidores/DLQ são KAM-006; catálogo de schemas é KAM-007.
Testes: rollback sem lacunas, concorrência por agregado, kill -9, Redis parado, líder único, carga. Abre PR com o template do §7.
```

---

## KAM-006 — Consumidores idempotentes, `events_consumed` e DLQ

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-005 |
| Bloqueia | KAM-014, KAM-038, KAM-055, KAM-061, KAM-070, KAM-092 |
| Responsável sugerido | Engenheiro de Dados |
| Documentos de referência | `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§6.3, §6.4, §6.5), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.1), ADR-009, ADR-013 |

### Contexto

O efeito exactamente-uma-vez obtém-se por idempotência no consumidor: um `INSERT ... ON CONFLICT DO NOTHING` em `events_consumed` na mesma transacção que o efeito. A janela de deduplicação (90 dias) excede a re-entrega da Meta (7 dias). Os consumidores de `payment.*` são **sempre** com ordem, porque aplicar `paga` antes de `aguarda_pagamento` seria uma transição inválida; uma pré-condição que nunca se verifica esgota as tentativas e vai para DLQ, nunca se aplica (`../docs/tecnica/06` §6.3). Um `payment.*` ou `order.paid` na DLQ é cliente que pagou sem confirmação: Sev1.

### Objectivo

Fornecer o *wrapper* de consumo idempotente (TS e Python), as tabelas `events_consumed` e `events_dlq`, a política de tentativas e o reconciliador que repõe eventos perdidos pelo Redis.

### Critérios de Aceitação

- [ ] Reentregar o mesmo evento 2× ao mesmo consumidor produz 1 efeito e 1 linha em `events_consumed` (contador de efeitos = 1).
- [ ] Um *handler* que falha sempre produz exactamente 6 tentativas (1 + 5, *backoff* 1 s, 5 s, 30 s, 2 min, 10 min), depois 1 linha em `events_dlq` (`estado='aberta'`, `tentativas=6`, envelope P0/P1).
- [ ] Com `exige_ordem`: `payment.confirmed` antes de a encomenda estar em `aguarda_pagamento` lança `Adiar(5 s)` e, esgotadas as tentativas, vai para DLQ; nenhuma transição inválida é aplicada (teste de contrato com máquina de estados falsa).
- [ ] Um evento com `agregado.seq` inferior ao último e transição inválida vai para DLQ com erro `fora_de_ordem`.
- [ ] Qualquer entrada de `payment.*` ou `order.paid` na DLQ aumenta `evt_dlq_open{tipo}` e dispara a regra de alerta Sev1; as restantes alertam se `aberta` > 1 h.
- [ ] Reprocessar uma entrada é idempotente; **descartar** uma entrada `payment.*` exige 2 aprovadores distintos (a CLI recusa o 1.º).
- [ ] O arranque falha se uma subscrição `payment.*` estiver configurada com `exige_ordem=false`.
- [ ] Reconciliador (a cada 5 min): depois de limpar o Redis no teste, todos os eventos publicados há > 10 min sem consumo nem DLQ são re-enfileirados em ≤ 15 min; 0 perdidos.
- [ ] Efeitos externos (HTTP, WhatsApp) passam por `once(key, fn)` com chave `consumer:event_id:acção`; chamada repetida não repete o efeito.

### Detalhes Técnicos

- **Componentes:** EVT. DDL de `events_consumed`, `events_dlq` e a *query* do reconciliador exactamente como `../docs/tecnica/06` §6.3–§6.5; tabela de acções externas `evt_acoes(idempotency_key PK, estado, resultado)` (nome em proposta).
- **Wrapper (pseudocódigo de `../docs/tecnica/06` §6.3):**
```
handler(consumer, env): BEGIN; n = INSERT events_consumed ON CONFLICT DO NOTHING; se n==0: COMMIT; return
  se exige_ordem: verificar seq/pré-condição (Adiar | DLQ('fora_de_ordem')); aplicar efeitos na BD; COMMIT
```
- **Retenções:** `events_consumed` 90 dias; DLQ 30 dias após resolução (*jobs* diários). Versão do evento acima de `versao_max` sem conversor: evento `bloqueado` com alerta Sev2, nunca descartado.
- **RLS:** `events_consumed`/`events_dlq` têm `tenant_id` (DLQ) e seguem a regra de KAM-004; reprocessamento corre como `kamba_batch` auditado.

### Testes Requeridos

- Unit: classificação de erros (`Adiar`, `fora_de_ordem`), *backoff*, `once`.
- Integração: duplicado, falha permanente, ordem inválida, DLQ + reprocesso, descarte com 2 aprovadores, Redis limpo + reconciliador (relógio acelerado).
- Contrato: consumidor de exemplo de `payment.confirmed` contra máquina de estados do doc 00 §6.1.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (pagamento e idempotência); testes verdes; cobertura ≥ 90% no *wrapper*.
- [ ] Documentação actualizada; Conventional Commits.
- [ ] **Isolamento de tenant** — DLQ e consumo respeitam RLS; teste cruzado do novo caminho.
- [ ] **Idempotência** — teste de repetição incluído para cada tipo de efeito.
- [ ] **Pagamento só por evento autenticado** — nenhum consumidor aplica `paga` sem a pré-condição de estado.
- [ ] **Custo e observabilidade** — `evt_consumed_total`, `evt_dlq_open`, `evt_retry_total` desde o código.
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-006 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-006) e ../docs/tecnica/06_Dados_Eventos_Analytics.md (§6.3–§6.5).
Objectivo: consumidores idempotentes, events_consumed, DLQ e reconciliador.
- Wrapper de consumo (TS e Python): INSERT events_consumed ON CONFLICT DO NOTHING na mesma transacção que o efeito.
- 6 tentativas com backoff 1 s/5 s/30 s/2 min/10 min; DLQ; Adiar(5 s); consumidores payment.* sempre com ordem.
- Alertas Sev1 para payment.*/order.paid em DLQ; descarte de payment.* exige 2 pessoas; once(key, fn) para efeitos externos.
- Reconciliador de 5 min com a query do doc 06 §6.5; retenções de 90 d e 30 d.
Não expandas escopo: o catálogo de schemas é KAM-007; as subscrições concretas das verticais são KAM-038.
Testes: duplicado, falha permanente, fora de ordem, DLQ, Redis limpo + reconciliador. Abre PR com o template do §7.
```

---

## KAM-007 — Catálogo de eventos: schemas versionados e teste de compatibilidade

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-005 |
| Bloqueia | KAM-038, KAM-061, KAM-092, KAM-123 |
| Responsável sugerido | Engenheiro de Dados |
| Documentos de referência | `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§4, §5, §6.6, §7.3), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.3, §7.2), `specs/01_Engineering_Standards_e_Handoff.md` §4–§5, ADR-009, ADR-010 |

### Contexto

O envelope é fixo (KAM-005); o que varia é o `payload` de cada `tipo`/`versao`. O documento 11 dizia que consumidores «ignoram versões desconhecidas», o que perde dados em silêncio quando o produtor é actualizado primeiro; `../docs/tecnica/06` §6.6 corrige: campo opcional novo ⇒ mesma versão; qualquer mudança de significado, remoção ou tipo ⇒ `versao + 1`; consumidores migram antes dos produtores; um evento sem conversor fica bloqueado com alerta. Este ticket materializa o catálogo de Fase 0/1 (tabela de `../docs/tecnica/06` §5) em schemas e o teste que faz cumprir estas regras (gate 7).

### Objectivo

Publicar em `packages/contracts/eventos/<tipo>/v<versao>.schema.json` os schemas v1 dos eventos de Fase P, com *lint* de PII, geração de tipos para TS e Python e um teste de compatibilidade que bloqueia alterações quebrantes sem nova versão.

### Critérios de Aceitação

- [ ] Existe `v1.schema.json` para 100% dos tipos de Fase P da tabela de §5 de `../docs/tecnica/06` (`order.*`, `payment.*`, `review.requested|created`, `query.*`, `tenant.*`, `catalog.*`, `stock.*`, `consent.*`, `privacy.*`) e para os tipos que os documentos de canal exigem e §5 não lista: `channel.updated` e `contact.merged`; o evento `tenant.approved|provisioned|activated` (doc 00 §6.2, KAM-092) é incluído.
- [ ] Todos os schemas têm `additionalProperties: false`; valores monetários são inteiros; moeda explícita.
- [ ] Gate 7: remover, renomear, mudar o tipo ou tornar obrigatório um campo sem incrementar `versao` falha o CI (comparação com a *branch* principal); acrescentar campo opcional passa (4 casos de teste, 2 de cada lado).
- [ ] *Lint* de PII: nomes de campo `telefone|msisdn|bsuid|nome|morada|texto|email` fora da lista aprovada falham; as *fixtures* corridas contra `\+?244\d{9}` falham se contiverem correspondência.
- [ ] Cada subscrição em `evt_subscricoes` tem `versao_max` que existe nos contratos; uma subscrição para versão inexistente falha o CI.
- [ ] Os produtores validam o `payload` contra o schema antes de chamar `evt_emitir` e rejeitam tipos desconhecidos; os consumidores falham de forma visível (bloqueio + alerta) perante versão sem conversor.
- [ ] Tipos TS e modelos Python gerados a partir dos schemas compilam sem edição manual; existe um exemplo JSON válido por tipo, validado no CI.

### Detalhes Técnicos

- **Componentes:** EVT. Ficheiros: `packages/contracts/eventos/**`, `tools/contract_diff/` (classificador de diferenças: *aditivo-opcional*, *quebrante*), `packages/contracts/converters/<tipo>/v1_to_v2`.
- **Decisão de unidades (proposta, registar no PR):** os payloads usam `valor_minor` (inteiro em unidades menores, `moeda` explícita), alinhado com `../docs/tecnica/03` §5.1 e a ProxyPay (0,01 Kz); `../docs/tecnica/06` §4 mostra `valor_kz` (inteiro em Kz). A convenção do Standards §5 («Kz como inteiros, moeda explícita») admite ambas; a escolha final propaga-se a `../docs/tecnica/06` e KAM-055/KAM-053.
- **Tipos acrescentados:** `channel.updated`, `contact.merged` e `conversation.mode_changed` (KAM-018) não constam do catálogo §5; entram aqui como extensões documentadas.
- **Regras de deploy:** consumidores antes de produtores; *deprecation* de uma versão ≥ 90 dias após o último consumidor migrar (`../docs/tecnica/06` §6.6).

### Testes Requeridos

- Unit: classificador de diferenças (8 pares de schemas); *lint* de PII com 6 nomes proibidos e 2 aprovados.
- Contrato: validação dos exemplos JSON; produtor rejeita payload com campo extra; consumidor com versão sem conversor bloqueia.
- Integração: emitir e consumir 1 evento de cada tipo através de KAM-005/KAM-006 em memória.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [ ] Documentação actualizada (`docs/eventos.md` com a tabela tipo → produtor → consumidores → PII → fase); SemVer dos schemas; Conventional Commits.
- [ ] **Privacidade** — nenhum campo de PII P2 em qualquer schema; `contact_id` apenas.
- [ ] **Idempotência** — o `event_id` é a chave global e está no schema do envelope.
- [ ] **Dependências** — gerador de tipos fixado por lockfile; licença verificada.
- [ ] A decisão de unidades monetárias e a lista de tipos acrescentados estão registadas no PR.

### Handoff para Claude Code

```text
És o executor do ticket KAM-007 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-007) e ../docs/tecnica/06_Dados_Eventos_Analytics.md (§4, §5, §6.6, §7.3).
Objectivo: schemas v1 do catálogo de eventos e teste de compatibilidade como gate 7.
- Um schema por tipo/versão em packages/contracts/eventos, additionalProperties:false, valores monetários inteiros.
- tools/contract_diff: aditivo-opcional passa; remover/renomear/mudar tipo/tornar obrigatório sem versao+1 falha.
- Lint de PII e de fixtures (+244); versao_max das subscrições tem de existir; geração de tipos TS e Python.
- Acrescenta channel.updated, contact.merged, conversation.mode_changed e tenant.approved/provisioned;
  regista no PR a decisão valor_minor vs valor_kz.
Não expandas escopo: sem lógica de produtores/consumidores de negócio.
Testes: diferenças, PII, exemplos válidos, rejeição de campo extra. Abre PR com o template do §7.
```

---

## KAM-008 — Identidade de contacto em duas camadas (contacts, endpoints, HMAC rodado, cofre)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-003, KAM-010 |
| Bloqueia | KAM-014, KAM-022, KAM-044, KAM-052, KAM-053, KAM-069, KAM-070, KAM-072, KAM-086, KAM-097, KAM-112, KAM-118 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.3), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.2, §7.6), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.2), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§3), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, ADR-010 |

### Contexto

O BSUID é obrigatório e o telefone pode faltar nos webhooks (E1, CONFIRMADO). O ADR-010 manda: `contact_id` aleatório nas tabelas de negócio e eventos; BSUID e telefone cifrados numa tabela separada; `sujeito_ref = HMAC(chave rodada, contact_id)` para analytics. Um HMAC de telefone é reversível por enumeração do espaço angolano (~10⁸) se o segredo vazar (E3, `../docs/tecnica/08` §7.2): é pseudonimização, não anonimização. **Há três desenhos de `contacts` em `../docs/tecnica/`** (01 §6.2: BSUID e `phone_hmac` na mesma tabela; 03 §5.3: `bsuid_hmac` + `contact_endpoints`; 06 §7.2: cofre com `lookup_hmac`, `bsuid_enc`, `phone_enc`, `dek_id`) e o de 03 não consegue responder por BSUID porque só guarda o HMAC. Decisão: ADR-010 + 03 §5.3 para a estrutura em duas tabelas, 06 §7.2 para `bsuid_enc` e `dek_id`.

### Objectivo

Implementar as tabelas `contacts` e `contact_endpoints`, o resolutor de identidade (BSUID/telefone → `contact_id`) com fusão transaccional, o HMAC com `kid` rodável, a cifra de envelope por contacto e as primitivas de apagamento (*crypto-shredding*).

### Critérios de Aceitação

- [ ] `contacts` guarda `lookup_hmac`, `hmac_kid`, `phone_hmac` opcional, `erased_at` e `UNIQUE (tenant_id, hmac_kid, lookup_hmac)`; BSUID e telefone só existem cifrados (AES-256-GCM, DEK por contacto) em `contact_endpoints`.
- [x] Um *dump* completo da BD de teste, depois de semear 1 000 contactos com telefones e BSUIDs canário, tem 0 ocorrências dos canários em claro (nem em `contacts`, logs ou eventos).
- [x] `resolveContact` é idempotente: 10 000 chamadas repetidas com BSUIDs aleatórios devolvem o mesmo `contact_id`; o mesmo BSUID em dois tenants gera `contact_id` distintos.
- [x] Resolução por ordem: BSUID → telefone (HMAC com `kid` actual **e** anterior) → criar; se um contacto só-telefone receber BSUID, é completado; dois contactos que se revelam o mesmo fundem-se numa transacção e a fusão devolve o evento `contact.merged` para quem o emite.
- [ ] Rotação: `rekeyLookup(newKid)` recalcula `lookup_hmac` a partir de `bsuid_enc`, é retomável e idempotente; durante a janela a pesquisa tenta `kid` actual e anterior; no fim 100% das linhas têm o novo `kid`.
- [ ] `eraseContact(id)`: apaga `contact_endpoints`, destrói a DEK, substitui `lookup_hmac` por valor aleatório e define `erased_at`; depois disso a tentativa de decifrar falha e o BSUID original gera um contacto novo.
- [x] `sujeito_ref(contact_id, época) = trunc16(HMAC(K_época, contact_id))` é determinístico dentro do mês e diferente entre meses.
- [x] O papel `kamba_app` não tem `SELECT` em `contact_endpoints` (só o papel `kamba_identity`); um *join* de encomendas com endpoints falha por privilégio.
- [x] Em `KAMBA_ENV=prod` o arranque falha se o `KeyProvider` for o de ambiente (as chaves vêm do cofre, KAM-010).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#27`, ramo `feature/KAM-008-identidade-de-contacto`.
**Onze caixas marcadas, cinco vazias** (16 = 11 + 5) — cada uma com uma linha
aqui. Os números são os do *run* do CI em `47a2f19` — gates 1, 2, 3, 3b, 4, 6, 8, 9,
11 e o resumo verdes; os *commits* seguintes só mexem em documentação — e
reproduzem-se com `make ci-8` e `make ci-6`. Duas revisões adversariais independentes
([`ANALISE-08`](../docs/analises/ANALISE-08-KAM-008-identidade-de-contacto.md))
**não aprovaram** a primeira versão: um defeito de concorrência que duplicava
contactos (critérios 3 e 4) só deixou de existir depois delas, e treze mutações
delas passavam verdes. O desenho está em [`../docs/identidade.md`](../docs/identidade.md).

| CA | Estado | Evidência |
|---|---|---|
| 1 — `contacts` com `lookup_hmac`, `hmac_kid`, `phone_hmac`, `erased_at` e `UNIQUE (tenant_id, hmac_kid, lookup_hmac)`; BSUID e telefone só cifrados em `contact_endpoints` | **parcial — caixa vazia** | **A primeira metade não se cumpre à letra, por decisão.** O HMAC do BSUID chama-se `bsuid_hmac` e vive, com a unicidade `UNIQUE (tenant_id, hmac_kid, bsuid_hmac)`, em `contact_endpoints` — é o que o dicionário §3.1 diz, e o dicionário prevalece sobre este bloco (linha 3 do KAM-141). `contacts` tem `phone_hmac`, `hmac_kid` e `erased_at`. A segunda metade cumpre-se: AES-256-GCM, DEK por contacto embrulhada pela KEK, conferido contra a base (formato da cifra, uma DEK por contacto, cifra alterada ou trocada de linha não abre). Ver «O que fica por decidir» |
| 2 — *dump* com 1 000 contactos canário: 0 ocorrências | **satisfeito** | `tests_identidade` no *runner*: 1 000 contactos, 2 000 canários, procurados **em claro e em hexadecimal** no `pg_dump` da base inteira, no registo do servidor com `log_statement = 'all'` (instruções e parâmetros) e na saída dos testes — 0. A procura tem controlo positivo posto **em claro na base** (um em `bytea`, um em texto), que tem de ser encontrado no *dump* e no registo verdadeiros. «Eventos»: o único que o módulo produz é o `contact.merged` devolvido, conferido sem BSUID nem telefone; não há tabela de eventos (KAM-005). Um segundo ensaio passa canários por fundir, trocar de número, ler, rodar, apagar e três erros |
| 3 — `resolveContact` idempotente em 10 000 chamadas; tenants distintos dão contactos distintos | **satisfeito** | 10 000 BSUID aleatórios criados em oito ligações paralelas, 10 000 contactos; **10 000 chamadas repetidas**, baralhadas, devolvem o mesmo `contact_id` e não criam nada. O mesmo BSUID e o mesmo telefone em dois tenants: dois contactos, e nem os HMAC coincidem. Oito pedidos simultâneos pelo mesmo contacto novo criam um. **Só passou a ser verdade em todas as condições depois da revisão**: durante uma rotação de chave, o mesmo BSUID podia ficar com dois contactos (ANALISE-08, M1) |
| 4 — ordem BSUID → telefone (`kid` actual e anterior) → criar; completar; fusão transaccional; evento devolvido | **satisfeito** | Um teste por caso contra a base: a ordem; o só-telefone completado; a fusão no mais antigo (nos dois sentidos), com lápide e `contact.merged` devolvido uma vez em onze repetições; ganchos dentro da transacção; **rollback completo** com um gancho a falhar e com a base a falhar em cada uma das quatro instruções da fusão (fotografia das três tabelas igual). A pesquisa pelas duas versões está provada na janela de rotação. Decisão não pedida: um telefone que já tem **outro** BSUID não funde — ver «O que fica por decidir» |
| 5 — `rekeyLookup(newKid)` recalcula `lookup_hmac` de `bsuid_enc`; retomável e idempotente; janela com as duas versões; 100% no novo `kid` | **parcial — caixa vazia** | O comportamento pedido está provado com 10 000 linhas: recálculo a partir de `bsuid_enc` (sem a chave antiga), interrupção ao fim de 3 lotes e retoma, segunda execução sem alterações, resolução correcta a meio, e no fim **10 000 de 10 000** linhas de BSUID sob a versão nova, com o HMAC conferido contra a chave nova. **Três desvios da letra:** a coluna é `bsuid_hmac` (CA 1); a função é por tenant — `rekeyLookup(cliente, tenant, kid)` —, porque o papel não vê mais do que um tenant; e o HMAC de um **telefone** sem cifra guardada não se recalcula: fica sob a versão antiga até o número voltar a aparecer, ou é apagado (`largar`). As revisões leram-no como parcial, e fica assim |
| 6 — `eraseContact`: apaga endpoints, destrói a DEK, **substitui `lookup_hmac` por valor aleatório**, define `erased_at`; decifrar falha; o BSUID gera contacto novo | **parcial — caixa vazia** | **«Substitui por valor aleatório» não se faz**: com o HMAC em `contact_endpoints` (CA 1), a linha é apagada e não há valor a substituir. O resto está provado ponta a ponta: 2 endpoints apagados, DEK com `wrapped_dek` nulo e `destroyed_at` datado, HMAC do telefone nulo, `erased_at`; ler falha, **e continua a falhar repondo as linhas cifradas de uma cópia** (a DEK já não existe); o mesmo BSUID e o mesmo telefone dão um contacto novo; idempotente; um contacto espectador no mesmo tenant fica intacto. Limite: a DEK embrulhada vive na base, logo numa cópia de segurança anterior a cifra ainda se abre com a KEK (`../docs/identidade.md` §8, ponto 1) |
| 7 — `sujeito_ref` determinístico no mês e diferente entre meses | **satisfeito** | Unitários: igual para o mesmo contacto e mês, diferente noutro mês e noutro contacto, e igual aos primeiros 16 octetos de `HMAC-SHA256(K_época, contact_id)` calculado por fora. `trunc16` lido como 16 **octetos** (o `../docs/tecnica/06` §8 declara `bytea`); a época é o mês em UTC |
| 8 — `kamba_app` sem `SELECT` em `contact_endpoints`; um *join* de encomendas com endpoints falha por privilégio | **satisfeito** | Matriz exacta por tabela e por coluna (gate 8): `kamba_app` não tem privilégio nenhum em `contact_endpoints`, `contact_deks` nem `hmac_key_versions`, e em `contacts` só `SELECT` de seis colunas. O *join* falha com `42501` em três formas. **Ainda não há encomendas** (EPIC-04): o teste cria uma tabela de ensaio a que `kamba_app` tem `SELECT`, para a recusa só poder vir dos endpoints. `kamba_batch` e `kamba_resolver` também não tocam no cofre |
| 9 — em `KAMBA_ENV=prod` o arranque falha com o `KeyProvider` de ambiente | **satisfeito** | `Identidade.arrancar` é a única forma de obter o serviço e lança `KeyProviderDeAmbienteError`; recusa também `KAMBA_ENV` em falta ou diferente do ambiente do provedor. **À letra, e só à letra:** «de ambiente» é o provedor que se chama `env` — outro nome arranca (ANALISE-08, m8) — e hoje **não existe** `KeyProvider` de cofre para `prod`. Ver «O que fica por decidir» |
| DoD — todos os CA satisfeitos | **não satisfeito — caixa vazia** | Seis de nove; 1, 5 e 6 parciais, pelas razões acima |
| DoD — 2 revisores; testes verdes; cobertura ≥ 90% no código de identidade | **não satisfeito — caixa vazia** | Testes verdes e cobertura medida no *runner*, **por ficheiro**: `chaves.ts` 100% (407/407), `consultas.ts` 100% (235/235), `contactos.ts` 99% (1300/1302), `cripto.ts` 100% (231/231), `index.ts` 100% (108/108); estrato `critico` do gate 4 a 99% (4802/4810). A medida conta linhas físicas, comentários incluídos (ANALISE-08, notas). **Zero revisores humanos**: duas revisões adversariais são evidência, não são revisores |
| DoD — documentação; divergências 01/03/06 registadas; Conventional Commits | **satisfeito** | `../docs/identidade.md` (novo; divergências no §8), `../docs/isolamento.md` v1.2, `../docs/ci.md` v1.12, `../db/migrations/README.md`, dicionário §3.1/§3.2/§3.9 (emenda 1.8), `../docs/dividas-documentais.md` linhas 12 a 15 |
| DoD — isolamento: RLS em `contacts`, `contact_endpoints`, `contact_deks`; teste cruzado | **satisfeito** | Gate 6 no *runner*, 71 testes: as seis tabelas descobertas pelo catálogo, cada uma atacada com o papel que a lê (`kamba_identity` nas três novas, que é também o único com `DELETE`), mais `contacts` lida por `kamba_app` e a lista fechada de políticas. Teste cruzado do módulo: com o contexto de B, o contacto de A não se lê nem se apaga. As revisões tentaram por SQL directo e não passaram |
| DoD — privacidade: telefone nunca chave nem em claro; HMAC rodado; retenção e finalidade em `expira_at` | **satisfeito** | Lista fechada de colunas com `phone` no nome (três, todas `bytea` ou opacas) e nenhuma em chave primária ou FK; CA 2; rotação provada (CA 5). `phone_enc` exige `finalidade` e `expira_at` (restrição), sem prazo por omissão, e um telefone fora do prazo não se serve. **Os valores — finalidades e prazos — estão por confirmar por parecer**, tal como a base legal de guardar `phone_hmac` sem finalidade declarada |
| DoD — sem segredos: chaves só via `KeyProvider`; *scan* limpo | **satisfeito** | Nenhuma chave na base (`hmac_key_versions` só tem `kid`, estado e data; há teste); gate 9 limpo; as chaves dos testes são geradas em execução; inventário de segredos verde com as três entradas novas |
| DoD — migrações reversíveis: `downgrade` testado, sem perda silenciosa (cópia lógica no passo) | **satisfeito** | `upgrade → downgrade → upgrade` com o estado comparado; com linhas de identidade o `downgrade` **recusa** sem `KAMBA_DOWNGRADE_0003_COPIA`, e com ela escreve as quatro tabelas e os donos de tenant — o teste repõe tudo a partir da cópia e compara octeto a octeto. Não há ferramenta de reposição: é um `INSERT` por linha |

**Prova por mutação.** `db/mutacoes.py` tem 110 mutações, 62 deste ticket (31
do schema e do papel, 29 do módulo TypeScript e 2 da procura de canários). A
lista inteira foi corrida depois das correcções e da integração de `main`:
**110 corridas, 110 apanhadas, 0 sobreviventes**, em três fatias de
`--fatia i/3` com quatro execuções em paralelo (37 + 37 + 36), cada uma sobre
uma cópia com linha de base verde nas três *suites*. Quatro mutações das revisões continuam a passar e estão
declaradas, com a razão, na ANALISE-08 §4.

#### Decisões tomadas neste ticket

- **O HMAC de pesquisa leva o tipo e o `tenant_id` na mensagem.** O mesmo
  telefone em dois tenants dá dois HMAC: quem leia a base inteira não liga os
  dois. Custo: deixa de se poder comparar HMAC entre tenants.
- **Todas as FK de identidade são compostas com o `tenant_id`**, incluindo a do
  dono (`tenants_owner_fk`), que o doc 03 escreve simples.
- **Lápide de fusão** (`merged_into`, `merged_at`) e `contact_deks.contact_id`:
  colunas que este bloco não lista.
- **`kamba_app` não escreve em nenhuma tabela de identidade** e lê seis colunas
  de `contacts`; `kamba_batch` não tem privilégio nenhum no cofre — a purga
  (KAM-071) e a rotação (KAM-072) pedem o que precisarem por revisão.
- **`phone_enc` só se guarda a pedido**, com finalidade e prazo; do telefone
  fica sempre o HMAC.
- **A *suite* de identidade corre no *job* do gate 8**, não num gate novo; o
  gate 5 continua reservado.
- **`contactos.ts` sai da medição do gate 4** e mede-se na *suite* de base de
  dados, a 90% por ficheiro; `*/identity/*` entra no estrato `critico`.
- **Os testes de `db/` chamam o Alembic no processo** (cada processo custava
  oito a nove segundos em Windows); o ciclo do critério 1 do KAM-003 continua
  pela linha de comandos.
- **Um achado que vale para todas as revisões futuras:** uma FK acrescentada a
  uma tabela com `FORCE ROW LEVEL SECURITY` valida zero linhas
  (`../docs/isolamento.md` §6).

#### O que fica por decidir

Três decisões que este ticket tomou para poder avançar e que **não são dele**.
Estão implementadas como *proposta*; inverter qualquer uma é uma revisão nova.

1. **Onde vive o HMAC do BSUID.** Este bloco pede `contacts.lookup_hmac`; o
   dicionário §3.1 põe `bsuid_hmac` em `contact_endpoints`. Seguiu-se o
   dicionário (emenda 1.8, com `lookup_hmac` registado como variante), e por
   isso os critérios 1, 5 e 6 não se cumprem à letra. Quem aprova emendas
   decide: ou se ratifica a emenda e se corrige a letra deste bloco (KAM-141,
   linha 3), ou se move o HMAC para `contacts`.
2. **`KeyProvider` em `prod` contra o ADR-L002.** O critério 9 recusa chaves do
   ambiente em `prod`; o `../docs/adr/ADR-L002-injeccao-de-segredos.md` diz que
   no Piloto os segredos chegam ao processo **pelo ambiente**. Os dois não se
   cumprem ao mesmo tempo, e nenhum ticket constrói um `KeyProvider` que fale
   com o cofre. Enquanto isto não se decidir, o módulo **não arranca em `prod`**.
3. **Um número que muda de mãos não funde.** Um telefone que já pertence a um
   contacto com outro BSUID passa para quem o traz agora, e os dois contactos
   ficam separados. Evita entregar o histórico de uma pessoa a outra quando a
   operadora reatribui o número; mas trata como duas a mesma pessoa se um tenant
   tiver dois portfólios da Meta ou mudar de portfólio (ANALISE-08, M3).

O resto do que ficou aberto — cópias de segurança e *crypto-shredding*,
reembrulho das DEK, chaves de época, auditoria das leituras, purga — está em
`../docs/identidade.md` §8, com o ticket de cada um.

### Detalhes Técnicos

- **Componentes:** CHR (módulo `identity`), TEN (FK `tenants.owner_contact_id` diferida criada nesta migração, `DEFERRABLE INITIALLY DEFERRED`). Módulo em `packages/core-ts`; o AGR (Python) só conhece `contact_id`.
- **Chaves:** porta `KeyProvider` (`getLookupKey(kid)`, `getEpochKey(YYYYMM)`, `wrapDek/unwrapDek`) com implementação de ambiente para dev e a de cofre em KAM-010; `hmac_key_versions(kid, criado_at, estado)` guarda metadados, nunca segredos. Rotação anual do *pepper* com `kid` (`../docs/tecnica/08` §5).
- **DEK por contacto:** `contact_deks(dek_id, tenant_id, wrapped_dek, kek_id, destroyed_at)`; necessária para o apagamento selectivo (`../docs/tecnica/06` §7.6); `../docs/tecnica/03` §5.3 diz «chave por tenant», que não permite apagar um só titular — divergência registada no PR.
- **Ganchos:** `onContactMerge` registado por `conversations` (KAM-014) e pelos *checkpoints* (KAM-026) para migrar dados para o `contact_id` mais antigo; a emissão do evento fica a cargo do chamador (KAM-014), pois KAM-005 não é dependência deste ticket.
- **Fora de âmbito:** consentimento (KAM-022; há três tabelas de consentimento nos documentos), fluxo de direitos do titular (KAM-070), purga de retenção (KAM-071).

### Testes Requeridos

- Unit/propriedade: determinismo e unicidade por tenant; rotação com 10 000 linhas; cifra/decifra com DEK errada falha.
- Segurança: *dump grep* de canários; privilégios do papel; logs sem telefone (linter de logging).
- Integração: fusão transaccional com falha a meio (rollback completo); `eraseContact` ponta a ponta.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais, segredos); testes verdes; cobertura ≥ 90% no código de identidade.
- [x] Documentação actualizada; divergências 01/03/06 registadas para correcção; Conventional Commits.
- [x] **Isolamento de tenant** — RLS em `contacts`, `contact_endpoints`, `contact_deks`; teste cruzado.
- [x] **Privacidade** — telefone nunca é chave nem aparece em claro em logs, eventos ou BD; HMAC com segredo rodado; retenção e finalidade em `contact_endpoints.expira_at` (valores a confirmar por parecer).
- [x] **Sem segredos** — chaves só via `KeyProvider`; scan limpo.
- [x] **Migrações reversíveis** — `downgrade` testado (sem perda silenciosa de endpoints: backup lógico no passo).

### Handoff para Claude Code

```text
És o executor do ticket KAM-008 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-008), ../docs/tecnica/03_Core_Comercio_Medusa.md (§5.3),
../docs/tecnica/06_Dados_Eventos_Analytics.md (§7.2, §7.6) e ../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§6).
Objectivo: identidade de contacto em duas camadas (ADR-010).
- contacts (lookup_hmac, kid, phone_hmac, erased_at) e contact_endpoints (bsuid_enc, phone_enc, DEK por contacto).
- resolveContact idempotente (BSUID → telefone com kid actual e anterior → criar), fusão transaccional,
  rekeyLookup retomável, eraseContact (crypto-shredding), sujeito_ref por época. Porta KeyProvider (env em dev).
- Papel kamba_identity para endpoints; kamba_app sem acesso. Prod falha com KeyProvider de ambiente.
- Telefone nunca em claro em BD, logs ou eventos; HMAC é pseudonimização, não anonimização.
Não expandas escopo: sem consentimento (KAM-022), sem direitos do titular (KAM-070), sem emissão de eventos.
Testes: propriedade, dump grep de canários, privilégios, fusão com falha, erase ponta a ponta. Abre PR com o template do §7.
```

---

## KAM-009 — TEN: entitlements e limites aplicados por middleware

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-003 |
| Bloqueia | KAM-021, KAM-027, KAM-028, KAM-059, KAM-091, KAM-096, KAM-121, KAM-124 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/00_Arquitectura_Solucao.md` (§4 TEN, §6.2), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.2), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§5), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (M-2), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§7.2), ADR-012, ADR-015 |

### Contexto

TEN decide o que cada tenant pode usar: que módulos (verticais) estão activos e que limites tem (mensagens de IA por mês, valor máximo por pedido, confirmação manual máxima, marcações). O REG consulta o entitlement ao activar uma vertical; a ToolLayer verifica limites em cada `invoke`. Os documentos usam chaves diferentes para o mesmo conceito (`valor_max_pedido_kz` em 02; `manual_max_minor` em 03 e 04) e a regra do conjunto é dinheiro em inteiros com moeda explícita (03 §5.1 prefere unidades menores). Sem entitlement activo a resposta é estática «serviço indisponível» e alerta (02 §5).

> **Herdado do KAM-003 e do KAM-004 — uma decisão que ninguém tomou.** `kamba_app` pode alterar
> `tenants.plano`, `estado` e `verificado_at`, e com a política `id = app.tenant_id` do KAM-004 um
> contexto de tenant altera o **próprio** plano. Nenhum documento do desenho diz quem o deve fazer.
> Este ticket aplica os *entitlements* que dependem do plano: ou decide quem o altera (e retira o
> privilégio a `kamba_app`), ou diz por escrito porque fica como está. Ver `../docs/isolamento.md` §7.

### Objectivo

Implementar o serviço/biblioteca TEN com registo de chaves de limite, *middleware* (HTTP e hook de tool) que aplica entitlements e consome limites de forma atómica e idempotente, e a matriz de estado do tenant usada pelo CHR.

### Critérios de Aceitação

- [ ] Existe `registry/entitlement_keys.schema.json` com as chaves: `msgs_ai_mes`, `valor_max_pedido_minor`, `manual_max_minor`, `marcacoes_mes` (nomes em proposta; decisão de unidades registada no PR e propagada a `../docs/tecnica/02`, `03` e `04`); uma chave desconhecida em `limites` é rejeitada na escrita.
- [ ] `checkEntitlement(tenant, modulo)` devolve negado (fail-closed) se não houver linha, se `ativo=false` ou se o tenant estiver `onboarding`, `suspenso` ou `encerrado`; o *middleware* HTTP responde `403 ENTITLEMENT_DISABLED` (códigos em proposta).
- [ ] `consumeLimit(tenant, key, n, idempotencyKey)` é atómico: 1 000 chamadas paralelas de 1 unidade contra limite 100 aceitam exactamente 100 e negam 900 (`429 LIMIT_EXCEEDED`); o contador final é 100.
- [ ] Repetir a mesma `idempotencyKey` não consome duas vezes (10 repetições, uso = 1).
- [ ] O período mensal fecha às 00:00 de `Africa/Luanda`: com relógio fixo em `2026-11-30T23:59:59+01:00` o consumo conta para Novembro; em `2026-12-01T00:00:00+01:00` para Dezembro.
- [ ] `tenantGate(estado, acção)` implementa a matriz de `../docs/tecnica/01` §7.2 (ex.: `restrito` não envia *marketing*; `suspenso` só mensagem estática; `encerrado` descarta) e é consumido pelo CHR.
- [ ] Uma alteração de entitlement é visível em ≤ 60 s (TTL de cache, proposta) e a cache nunca devolve dados de outro tenant (teste cruzado).
- [ ] Métricas `ten_limit_denied_total{key}` e `ten_entitlement_denied_total{modulo}` expostas; o `tenant_id` nunca vem de parâmetro do cliente, só do contexto.

### Detalhes Técnicos

- **Componentes:** TEN (biblioteca em `packages/core-ts` com binding Python em `libs/py-core` para a ToolLayer; o Python chama a mesma regra SQL).
- **Contador:** `tenant_usage(tenant_id, key, periodo date, valor bigint)` e `usage_ledger(tenant_id, key, idempotency_key UNIQUE, n)`; o consumo é um `INSERT ... ON CONFLICT DO UPDATE ... WHERE valor + n <= limite` dentro da transacção que regista a `idempotency_key` (atomicidade sem *lock* global). RLS por `tenant_id` (KAM-004).
- **Planos:** `registry/plans.yaml` mapeia `plano` → entitlements por omissão; **os valores por plano não têm fonte** (H6 por validar): usar valores de exemplo marcados «proposta, calibrar no Piloto», nunca preços.
- **Fora de âmbito:** facturação da assinatura (KAM-059), aplicação em tools (KAM-028 usa esta biblioteca), provisioning (KAM-091 escreve os entitlements).

### Testes Requeridos

- Concorrência: 1 000 paralelas / limite 100; repetição idempotente; relógio fixo na fronteira de mês.
- Isolamento: leitura e consumo de A com contexto de B recusados; cache sem mistura.
- Unit: matriz de estados (6 estados × acções); validação do registo de chaves.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (limites de dinheiro e isolamento); testes verdes; cobertura ≥ 90% no consumo de limites.
- [ ] Documentação actualizada (`docs/ten.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — `tenant_id` do contexto, RLS e teste cruzado do novo caminho.
- [ ] **Idempotência** — consumo de limite com chave e teste de repetição.
- [ ] **Pagamento / plataforma sem fundos** — `manual_max_minor` aplica-se sem nunca criar saldo; valores em inteiros com moeda.
- [ ] **Custo e observabilidade** — métricas por tenant desde o código (ADR-018).
- [ ] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-009 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-009), ../docs/tecnica/02_Agent_Runtime_Verticais.md (§5),
../docs/tecnica/03_Core_Comercio_Medusa.md (§5.2) e ../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§7.2).
Objectivo: TEN com entitlements e limites aplicados por middleware.
- Registo de chaves (msgs_ai_mes, valor_max_pedido_minor, manual_max_minor, marcacoes_mes) e plans.yaml.
- checkEntitlement fail-closed; consumeLimit atómico e idempotente (tenant_usage + usage_ledger); mês em Africa/Luanda.
- tenantGate(estado, acção) conforme a matriz de ../docs/tecnica/01 §7.2; middleware HTTP e hook para a ToolLayer.
- Valores por plano são exemplos «proposta»; não inventes preços; regista a decisão de unidades no PR.
Não expandas escopo: sem facturação (KAM-059), sem provisioning (KAM-091).
Testes: concorrência 1 000/100, idempotência, fronteira de mês, isolamento. Abre PR com o template do §7.
```

---

## KAM-010 — Gestão de segredos e chaves (Doppler no Piloto, interface OpenBao)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001 |
| Bloqueia | KAM-008, KAM-013, KAM-016, KAM-030, KAM-056, KAM-072 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§5), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§6), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.14), ADR-008, ADR-014, `specs/01_Engineering_Standards_e_Handoff.md` §3 |

### Contexto

Doppler Developer (grátis até 3 utilizadores, 8 USD por utilizador acima; 10 projectos e 50 *service tokens*; logs de 3 dias, E4 §2.14, CONFIRMADO em resumo) cobre o arranque; OpenBao (MPL-2.0) entra nos Clusters; HashiCorp Vault fica excluído (BUSL-1.1). Segredos não são dados pessoais, pelo que o SaaS não agrava o ADR-008 (`../docs/tecnica/08` §5). Há dependência de terceiro para segredos críticos (risco MÉDIO em E4), por isso a interface é a costura. As chaves Meta e do facilitador são distintas por ambiente (número de teste e *sandbox* em *staging*). **KAM-008, KAM-013 e KAM-016 consomem esta interface** (o backlog mestre não declara a dependência); até este ticket estar concluído usam a implementação de ambiente.

### Objectivo

Entregar a porta `SecretProvider` com implementações de ambiente (dev), Doppler (Piloto) e um contrato verificável para OpenBao, o inventário máquina-legível de segredos com rotação, a separação por ambiente e a evidência de acessos.

### Critérios de Aceitação

- [x] A decisão está escrita em `docs/adr/` (MADR, numeração após ADR-019): mecanismo de injecção escolhido (variáveis ao arranque do contentor ou ficheiros em `tmpfs`), com a justificação; o mecanismo exacto não consta de `../docs/tecnica/` e é decidido aqui.
- [ ] Existem 3 projectos Doppler (`dev`, `staging`, `prod`); um *service token* de `staging` usado contra `prod` é recusado (teste, evidência anexada).
- [ ] `ops/secrets-inventory.yaml` lista 100% dos segredos da tabela de `../docs/tecnica/08` §5 (Meta App Secret, tokens de cliente, `verify_token`, PIN 2FA, chaves ProxyPay/AppyPay, chaves LLM/STT e LiteLLM, credenciais de BD, *pepper* HMAC, tokens Chatwoot) com `owner`, `rotacao_dias`, `ambientes`, `consumidores`; uma verificação de CI falha se o código pedir um segredo ausente do inventário.
- [x] `getRing(name)` devolve `[actual, anterior]` para o Meta App Secret e o GWY aceita ambos (contrato testado em KAM-013).
- [x] Um serviço sem segredo obrigatório falha ao arrancar com mensagem que nomeia o segredo (nunca o valor); em `prod`, se o cofre estiver inacessível no arranque, o serviço não arranca; depois do arranque mantém o último valor conhecido durante 15 min (proposta).
- [ ] Varrimento das camadas das imagens construídas e dos ficheiros compose: 0 segredos (scanner de KAM-002 sobre as imagens).
- [ ] MFA obrigatório para todos os utilizadores do cofre (captura de configuração em `docs/evidencia/KAM-010.md`).
- [ ] A suite de contrato `SecretProvider` passa em Env e em Doppler (conta de teste) e contra um *fake* de OpenBao; trocar de implementação é só configuração.
- [ ] Procedimento de exportação e restauro dos segredos de `staging` ensaiado e cronometrado: restauro ≤ 30 min (proposta).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#14`, ramo `feature/KAM-010-gestao-de-segredos`. Cada caixa marcada acima
tem uma linha aqui; **as doze não marcadas também** (4 marcadas, 12 vazias, em 9 critérios e 7 linhas de DoD) — uma caixa marcada sem
evidência nomeada é pior do que uma caixa vazia. Os comandos e as saídas estão em
`../docs/evidencia/KAM-010.md`.

| CA | Estado | Evidência |
|---|---|---|
| 1. ADR do mecanismo de injecção | **satisfeito** | `../docs/adr/ADR-L002-injeccao-de-segredos.md`: escolhe **variáveis de ambiente no arranque do contentor** sobre ficheiros em `tmpfs`, com a tabela de *trade-offs*, as duas fraquezas de (A) e o que as cobre, os três gatilhos de reversão e as quatro lacunas declaradas. Numeração `ADR-L002`, no espaço local que `../docs/adr/README.md` justifica: a sequência canónica está tomada até ADR-020 e o número seguinte colidiria se ela crescer. A frase do CA «numeração após ADR-019» está desactualizada pela mesma razão — o ADR-020 foi acrescentado a 2026-10-09 |
| 2. 3 projectos Doppler; *token* de `staging` recusado contra `prod` | **não satisfeito** | Exige uma conta Doppler, que não existe e que não se cria por iniciativa do executor. O que está feito e provado é **metade da regra, do lado do cliente**: o `DopplerSecretProvider` recusa-se a construir quando a configuração não bate com o ambiente (`AmbienteErradoError`), nos dois sentidos, e recusa também quando a resposta identifica uma configuração diferente — 2 casos em `secrets.negativos.test.ts` e 2 em `test_secrets_negativos.py`. A metade que falta é a do servidor, e é a que o CA pede |
| 3. Inventário a 100% + verificação de CI | **parcial** | **A parte do inventário está satisfeita e medida:** `ops/secrets-inventory.yaml` tem **19 entradas** que cobrem as **11/11 (100%)** linhas da tabela de `../docs/tecnica/08` §5, cada uma com `owner`, `rotacao_dias`, `ambientes` e `consumidores`. Medido por `cd tools && python -m secrets_inventory --root .. all`. A cobertura é calculada **lendo a tabela do documento** e não uma cópia, e há a verificação inversa (uma entrada que reclama uma linha inexistente é erro). **A parte da CI não:** a ferramenta existe e tem 69 testes verdes, mas o ticket proíbe-se de tocar no `Makefile`, em `.github/`, em `ci/` e em `docs/ci.md` — são do KAM-002, que ainda não fundiu. O alvo, o nome do *job* e as cinco linhas a acrescentar estão em `../tools/secrets_inventory/README.md` §4 |
| 4. `getRing` devolve `[actual, anterior]` | **satisfeito** | A tupla posicional é o contrato, nas três implementações: `getRing devolve [actual, anterior]` e `getRing dá anterior null quando nunca houve rotação` correm sobre Env, *fake* de OpenBao e Doppler (6 casos em TypeScript, 6 em Python). O `meta_app_secret` está no inventário com `anel: true`. **A segunda metade do CA — «o GWY aceita ambos» — é explicitamente do KAM-013** («contrato testado em KAM-013») e não deste ticket: aqui fica a porta e o anel, lá fica o consumidor |
| 5. Arranque: segredo ausente, `prod` sem cofre, 15 min | **satisfeito** | Três regras, cada uma com caso próprio nas duas linguagens. (a) Ausente: `ArranqueAbortadoError` nomeia **todos** os que faltam de uma vez (`meta_app_secret, meta_verify_token`), e um caso separado prova que o valor do segredo que **existe** não aparece na mensagem nem no *stack*. Variável vazia ou só-espaços conta como ausente. (b) `prod` com cofre selado não arranca; fora de `prod` avisa e aborta ao não conseguir ler, nomeando o segredo. (c) A janela são 900 000 ms, verificados nos três pontos: serve ao segundo 1, serve a 899 s, **recusa a 900 s** (limite `>=`), e recupera quando o cofre volta. A janela cobre **indisponibilidade e não revogação** — um segredo apagado propaga-se sempre, para que revogar um *token* o desactive na hora e não em quinze minutos; é decisão de desenho deste ticket, não do CA |
| 6. Varrimento das imagens construídas | **não satisfeito** | O *scanner* é do KAM-002 (o próprio CA o diz), que está em `feature/KAM-002-pipeline-ci-gates` e não fundiu. O ramo `main` **não tem** `tools/githooks/pre-commit`, pelo que nem o *hook* de segredos existe aqui. O que se pôde fazer está em `../docs/evidencia/KAM-010.md` §2: todos os valores de teste são da forma `...-de-teste`, e as 3 ocorrências de prefixos de chave (`sk-`) são casos de teste deliberados — **que o gate 9 vai ver quando ligar**, e que precisam de entrada em `ci/secrets-allow.yaml` ou de mudar de forma |
| 7. MFA obrigatório, com captura | **não satisfeito** | Exige conta Doppler. Não há captura, e uma captura inventada seria pior do que a caixa vazia. `../docs/evidencia/KAM-010.md` §3 diz o que falta e o que desbloqueia. O inventário cobre a parte da linha «Acesso humano» do doc 08 §5 que **é** um segredo (`vpn_wireguard_admin`), com a nota de que o MFA é política e ficou em aberto |
| 8. Suite de contrato em Env, Doppler e *fake* de OpenBao | **parcial** | A suite é **uma só bateria de 10 casos, escrita uma vez**, que corre sobre as três implementações: 31 casos em TypeScript (3 × 10 + 1) e 32 em Python. Env e *fake* de OpenBao passam contra as implementações reais. **O Doppler passa contra um transporte falso, e não contra a «conta de teste» que o CA pede** — e por isso a caixa fica vazia. Além disso, a forma da API do Doppler é **NÃO VERIFICADO**: tudo o que dela depende está atrás de uma função injectável, e o que falta confirmar está na constante `A_CONFIRMAR` de `../packages/core-ts/src/secrets/doppler.ts`. A parte «trocar de implementação é só configuração» está provada pela existência da bateria comum e por `test_as_tres_implementacoes_sao_SecretProvider` |
| Nota de caminho | **desvio declarado** | Os Detalhes Técnicos pedem `packages/core-ts/secrets/` e `libs/py-core/secrets/`. Entregou-se em `packages/core-ts/src/secrets/` e `libs/py-core/src/kamba_core/secrets/`, porque os caminhos da letra ficam **fora** do `rootDir: src` do `tsconfig.json` e fora do pacote `kamba_core` que o `pyproject.toml` publica — um módulo lá não compilaria nem se importaria. O desvio é de forma e não de âmbito, e fica registado em vez de corrigido em silêncio |
| 9. Exportação/restauro ensaiado, ≤ 30 min | **não satisfeito** | `ops/runbooks/secrets-export.md` existe e está escrito passo a passo, com as regras do destino, a conferência de contagem e o relógio a contar da decisão ao `make smoke`. **Não foi ensaiado e não há número:** falta um `staging` (KAM-075) e a CLI do Doppler, cujos subcomandos estão marcados NÃO VERIFICADO no próprio runbook (§7). O alvo de 30 min continua *proposta* |

**DoD, as sete linhas:**

| DoD | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos | **não satisfeito** | Dos nove: **3 satisfeitos** (1, 4, 5), **2 parciais** (3, 8), **4 não satisfeitos** (2, 6, 7, 9). Os **seis** que ficam por marcar dependem, todos eles, de uma conta Doppler (2, 7 e a metade Doppler do 8), de um `staging` — KAM-075 — (9), ou do KAM-002 fundido (6 e a metade de CI do 3). Nenhum se resolve neste ramo |
| Revisto por **2** revisores (segredos) | **não satisfeito** | Zero revisores humanos. O ticket é P0 e toca segredos, pelo que `01_Engineering_Standards_e_Handoff.md` §3 pede dois. Nenhuma verificação automática conta como revisor |
| Documentação e ADR local; Conventional Commits | **satisfeito** | `ADR-L002` + linha no índice de `../docs/adr/README.md`; `ops/runbooks/secrets-export.md`; `../tools/secrets_inventory/README.md`; `../docs/evidencia/KAM-010.md`; §3.9 de `02_Dicionario_de_Dados_Canonico.md` com linha 1.3 no controlo de versões; bloco novo no `.env.example`. Cada mensagem de *commit* passou `lint_arch commit-msg` **e** o `commitlint`, este corrido em contentor por não haver Node no *host* |
| **Sem segredos** — scan limpo no repositório e nas imagens | **não satisfeito** | Mesma razão do CA 6: o *scanner* é do KAM-002 e o `main` não tem `pre-commit`. O que se verificou à mão está em `../docs/evidencia/KAM-010.md` §2 |
| **Privacidade** — cofre sem dados pessoais; SaaS no inventário de subprocessadores | **não satisfeito** | A primeira metade é afirmação do canon (`../docs/tecnica/08` §5) e o runbook repete-a com o limite: vale para o **conteúdo** do cofre, e deixa de valer no momento em que alguém puser um identificador de pessoa num segredo. A segunda metade — registar o alojamento da Doppler no inventário de subprocessadores — é **KAM-069**, que não existe ainda; este ticket não o cria |
| **Dependências** — SDK/CLI do cofre fixado por lockfile; licença verificada | **parcial** | **Não se acrescentou dependência nenhuma**: o adaptador Doppler recebe um transporte injectado e não um SDK, e o verificador do inventário lê YAML com um leitor próprio em vez de PyYAML (a razão é a do KAM-001 — as ferramentas dos *hooks* têm de correr num clone antes de qualquer instalação). Logo não há SDK para fixar, e isso é decisão e não omissão. A licença está verificada e herdada com o seu estado (`E4` §2.14: Doppler CONFIRMADO em resumo, OpenBao MPL-2.0, Vault BUSL-1.1 excluído). **O que falha à letra:** o runbook pressupõe a CLI do Doppler, que nenhum lockfile fixa porque não está instalada |
| Inventário completo e verificado por CI | **parcial** | Completo e verificado: sim, por `python -m secrets_inventory`, com 100% de cobertura. **Por CI: não** — ver CA 3 |

> **O que isto custa, dito com clareza.** O ticket **não está fechado**. A porta,
> o inventário, o ADR, o runbook e a ferramenta de verificação estão feitos,
> testados e medidos: 58 casos de TypeScript, 75 de Python e 69 do verificador,
> todos verdes. O que falta divide-se em três montes, e nenhum é trabalho que
> este ramo pudesse ter feito:
>
> - **conta Doppler** — CA 2, CA 7 e a metade do CA 8 que pede conta de teste;
> - **`staging` (KAM-075)** — CA 9;
> - **KAM-002 fundido** — CA 6, a metade de CI do CA 3 e o DoD «sem segredos».
>
> E uma coisa que falta e é humana: **dois revisores**. É um ticket P0 de
> segredos, e a regra de `01_Engineering_Standards_e_Handoff.md` §3 é explícita.

### Detalhes Técnicos

- **Componentes:** transversal (GWY, LLM, PAY, HND, CHR consomem). Ficheiros: `packages/core-ts/secrets/`, `libs/py-core/secrets/`, `ops/secrets-inventory.yaml`, `ops/runbooks/secrets-export.md` (o runbook completo é KAM-083; rotação é KAM-072).
- **Regras:** nenhum segredo em imagem, repositório, log ou *trace*; credenciais de BD a 90 dias com papéis distintos; chaves por ambiente nunca reutilizáveis; CI com OIDC (KAM-002).
- **Custo:** Developer chega para a equipa inicial; acima de 3 utilizadores 8 USD/utilizador (preços a reconferir antes de orçamentar, `../docs/tecnica/09` watch list).
- **Fora de âmbito:** instalar OpenBao (Clusters), KMS próprio, rotação automática.

### Testes Requeridos

- Contrato: mesma suite sobre Env, Doppler e *fake* OpenBao.
- Segurança: token de ambiente errado recusado; scan de imagens; ausência de segredo no arranque.
- Operacional: ensaio de exportação/restauro em `staging` com cronómetro.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-010.md`).
- [ ] Código revisto por 2 revisores (segredos); testes verdes.
- [x] Documentação e ADR local actualizados; Conventional Commits.
- [ ] **Sem segredos** — scan de segredos limpo no repositório e nas imagens.
- [ ] **Privacidade** — o cofre não guarda dados pessoais; alojamento do SaaS registado no inventário de subprocessadores (KAM-069).
- [ ] **Dependências** — SDK/CLI do cofre fixado por lockfile; licença verificada.
- [ ] Inventário completo e verificado por CI.

### Handoff para Claude Code

```text
És o executor do ticket KAM-010 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-010), ../docs/tecnica/08_Seguranca_Conformidade.md (§5) e
../docs/tecnica/evidencia/E4_Stack_Licencas.md (§2.14). Objectivo: SecretProvider + Doppler no Piloto + inventário.
- Porta SecretProvider (get, getRing, versões) com implementações Env, Doppler e contrato OpenBao (fake).
- ops/secrets-inventory.yaml com a tabela do doc 08 §5 e verificação de CI (segredo usado ⊂ inventário).
- 3 projectos dev/staging/prod; token de staging recusado em prod; falha no arranque sem expor valores.
- Escreve o ADR do mecanismo de injecção; ensaia exportação/restauro; evidência em docs/evidencia/KAM-010.md.
Não expandas escopo: rotação automática (KAM-072), runbooks completos (KAM-083), OpenBao real (Clusters).
Testes: contrato nos 3 provedores, scan de imagens, ambiente errado. Abre PR com o template do §7.
```

---

## KAM-011 — StorageProvider S3-compatível (SeaweedFS ou gerido)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001, ext:D6 |
| Bloqueia | KAM-020, KAM-071, KAM-087, KAM-098, KAM-120 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-014, D6), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.1, §3.8, §7.5), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§3.1, §19), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.11) |

### Contexto

O MinIO foi arquivado (2026-04-24, E4 CONFIRMADO) e está excluído (ADR-014). As opções são SeaweedFS 4.48 (Apache-2.0, a mais madura com licença permissiva) ou S3 gerido; a escolha (D6) depende do alojamento (D1). Itens **NÃO VERIFICADOS**: semântica S3 do SeaweedFS para os nossos casos (*multipart*, URLs assinadas, *object lock*) e preços de S3 gerido acessíveis em Angola. O prefixo `t/{tenant_id}/` e URLs assinadas com TTL ≤ 5 min são o controlo de isolamento (`../docs/tecnica/08` §3.1, §3.8); URLs da Meta nunca são persistidas.

### Objectivo

Definir e implementar a porta `StorageProvider` com implementação S3 (funciona contra SeaweedFS e contra S3 gerido por configuração) e uma implementação *fake*, validar a semântica necessária contra SeaweedFS e registar a decisão D6.

### Critérios de Aceitação

- [x] A interface expõe `put`, `get`, `signUrl`, `delete`, `list`, todas com `ctx.tenantId` obrigatório; a chave do objecto é `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` e uma chave cujo prefixo não coincide com o `ctx` é recusada.
- [x] Ida e volta com *checksum* idêntico para objectos de 1 KB, 10 MB e 25 MB (este último valida *multipart*).
- [x] `signUrl` recusa `ttl` > 300 s; uma URL com `ttl` de 60 s devolve 200 antes e 403 depois de 65 s.
- [x] X-08: com `ctx` de A, `signUrl`/`get`/`list` sobre objectos ou prefixos de B falham; nenhuma listagem devolve chaves de outro tenant.
- [x] A mesma suite de contrato passa na implementação *fake* e contra SeaweedFS 4.48 em compose; os resultados de 3 testes de capacidade (*multipart*, URL assinada com expiração, *object lock* sim/não) ficam em `docs/evidencia/KAM-011-seaweedfs.md`.
- [ ] A decisão D6 (SeaweedFS vs S3 gerido) está escrita em ADR local com critérios: resultado dos 3 testes, custo cotado (marcado NÃO VERIFICADO se não houver cotação), local de alojamento (D1) e `destino.country`.
- [ ] A configuração exige `destino.country` e `destino.provider`; o valor é lido pelo gate de transferência (KAM-069); em `prod`, `country != AO` sem referência `apd_ref` configurada produz aviso bloqueante no arranque.
- [x] Cada objecto leva metadados `classe` e `retain_until` (ex.: áudio com alvo ≤ 24 h após transcrição, limite 72 h, `../docs/tecnica/08` §7.5); a purga em si é KAM-071.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#22`, ramo `feature/KAM-011-storage-provider`.
**Nove caixas marcadas, seis vazias** (8 critérios e 7 linhas de DoD) — cada
uma com uma linha aqui. Os números são os do *commit* `25f8d14`: as suites
correm no *gate* 4, e a prova contra o servidor real reproduz-se com
`python infra/storage/contrato.py`
([`../docs/evidencia/KAM-011-seaweedfs.md`](../docs/evidencia/KAM-011-seaweedfs.md)).
A revisão adversarial
([`ANALISE-09`](../docs/analises/ANALISE-09-KAM-011-storage-provider.md)) **não
aprovou** a primeira versão: a regra do `apd_ref` (critério 7) falhava aberta
para qualquer ambiente que não fosse a cadeia exacta `prod`.

**A decisão D6 não foi tomada, e não era deste ticket tomá-la.** Está aberta
(`../docs/tecnica/00_Arquitectura_Solucao.md` §13.3; Carta §4.2) e depende do
alojamento (D1). O que dela depende, critério a critério: **o CA6 inteiro**, e
por arrasto a primeira e a terceira linhas da DoD; o **valor** de
`destino.country` no CA7 (o mecanismo não). Os CA1 a CA5 e o CA8 **não**
dependem: a porta fala com qualquer servidor S3 por configuração, e a prova
contra o SeaweedFS é um dado para a decisão, não a decisão.

| CA | Estado | Evidência |
|---|---|---|
| 1 — `put`, `get`, `signUrl`, `delete`, `list` com `ctx.tenantId`; forma da chave; prefixo alheio recusado | **satisfeito** | A porta é uma só classe (`ArmazenamentoPorTenant`) sobre um motor: o *fake* e o S3 recusam o mesmo porque a recusa não é deles. 41 chaves mal formadas em TypeScript e 44 em Python, cada uma contra 5 operações, todas `ChaveInvalidaError` **sem o motor ser tocado** (conta-se); chave bem formada de outro tenant → `ChaveForaDoTenantError` nas 5, e a metade positiva no mesmo motor. A revisão tentou cerca de 150 vias à mão; a única que passou (subclasses de `str` em Python) está fechada. **Desvios da letra, declarados:** um sexto método, `head`; `list` tem `limite`; em Python os nomes são `snake_case` |
| 2 — ida e volta de 1 KB, 10 MB e 25 MB com *checksum* idêntico | **satisfeito** | Nos três alvos, nas duas linguagens: *fake*, motor S3 sobre servidor em memória, e SeaweedFS 4.48. Contra o servidor real, os 25 MiB vão em **1 abertura, 2 partes, 1 fecho**, contados por um transporte espião, e voltam com o mesmo SHA-256. «25 MB» está implementado como 25 MiB |
| 3 — `signUrl` recusa `ttl` > 300 s; URL de 60 s dá 200 antes e 403 depois de 65 s | **satisfeito** | 301, 3600, 0, −1, 1,5, `NaN`, infinito, `"60"`, `True` e subclasses de `int` recusados; 300 aceite. Contra o SeaweedFS o relógio **não** é injectado: a suite espera 65 s a sério e quem recusa é o servidor (200, depois 403). Uma URL com a chave trocada pela de outro objecto dá 403 |
| 4 — X-08 | **satisfeito** | Com o contexto de A: `get`, `head`, `signUrl`, `delete` e `list` sobre objectos e prefixos de B falham, nos três alvos; cada caso afirma primeiro que A vê o seu (um armazenamento vazio passava trivialmente) e confere no fim que o objecto de B está intacto. Segunda camada: um motor que devolva uma chave fora do prefixo pedido faz a listagem **falhar inteira**. O registo do caso na suite do KAM-066 (`registerCase`) fica por fazer: o KAM-066 não existe |
| 5 — mesma suite no *fake* e contra SeaweedFS 4.48 em compose; 3 testes de capacidade registados | **satisfeito** | A bateria (15 casos) está escrita uma vez por linguagem e corre sobre os três alvos. Contra `chrislusf/seaweedfs:4.48`, fixado por *digest* em `infra/compose/docker-compose.storage.yml`: **TypeScript 20 de 20, Python 17 de 17**. *Multipart*: sim. URL com expiração: sim. *Object lock*: sim pela API S3, **estado INDÍCIO** (um nó, sem reinício, sem atacar o *filer*). O servidor recusa a chave errada e o pedido anónimo — sem isso a bateria não provava o SigV4 escrito à mão. **Não corre no CI**: o ticket não pede um *gate* |
| 6 — decisão D6 em ADR local | **não satisfeito** | **Depende inteiramente da D6**, que está aberta. Não há ADR porque não há decisão. O que cada um dos quatro critérios do ADR tem hoje está em `../docs/evidencia/KAM-011-seaweedfs.md` §6: os 3 testes feitos para o SeaweedFS e para nenhum S3 gerido; custo **sem cotação** (NÃO VERIFICADO); D1 aberta; `destino.country` por decidir |
| 7 — configuração exige `destino.country` e `destino.provider`; lido pelo KAM-069; em `prod`, fora de `AO` sem `apd_ref`, aviso bloqueante | **parcial** | **Satisfeito:** sem `country` ou sem `provider` não há configuração, em nenhum ambiente; em `prod`, fora de `AO`, sem `apd_ref`, `lerConfig` lança `DestinoSemApdRefError`. Depois da revisão, um ambiente fora de `dev`/`staging`/`prod` é recusado em vez de tratado como «não é `prod`». **Não satisfeito:** «o valor é lido pelo gate de transferência (KAM-069)» — o KAM-069 não existe e nada consome `config.destino`. E o país é **declarado**: o módulo não o verifica |
| 8 — cada objecto leva `classe` e `retain_until` | **satisfeito** | Obrigatórios em `put` (o esboço do ticket tinha `retainUntil?` opcional; seguiu-se o critério); a classe tem de coincidir com o segmento da chave; `head` lê-os **do servidor**, e a interoperabilidade Python↔TypeScript lê os dois nos dois sentidos contra o SeaweedFS. `put` só escreve um prazo que `head` consiga ler de volta. A purga é KAM-071 |
| DoD — todos os CA satisfeitos | **não satisfeito** | Seis satisfeitos (1, 2, 3, 4, 5, 8), um parcial (7), um não satisfeito (6). O 6 depende da D6; o 7, do KAM-069 |
| DoD — 2 revisores; testes verdes; cobertura ≥ limiar | **não satisfeito** | Testes verdes e estrato `critico` a **100% (2879 de 2879 linhas, 18 ficheiros)** no *run* do PR — `*/storage/*` entrou no estrato. **Zero revisores humanos**: a revisão adversarial é evidência, não é um revisor, e as correcções que ela motivou não foram revistas por uma segunda ronda |
| DoD — documentação e ADR de D6; Conventional Commits | **não satisfeito** | Documentação: `../docs/armazenamento.md`, `../docs/evidencia/KAM-011-seaweedfs.md`, `ANALISE-09`, dicionário §3.11, `../docs/ci.md`. *Commits* conformes. **O ADR da D6 não existe** (CA6) |
| DoD — isolamento de tenant: prefixo e X-08 | **satisfeito** | CA1 e CA4. Prova por mutação, em cópia fora do repositório e com linha de base verde (`python infra/storage/mutacoes.py`): na última passagem completa, **142 de 145** apanhadas; das 3 sobreviventes, uma fechou-se com um teste e foi repetida, e duas são equivalentes em Python e saíram da lista, que ficou em 143 (`ANALISE-09` §4). O revisor fez 58 execuções suas: 13 sobreviviam, de 8 mutações distintas, e as 8 são hoje apanhadas |
| DoD — privacidade | **parcial** | URLs de leitura com tecto de 300 s; o módulo nunca vê nem guarda URLs da Meta (recebe bytes, devolve referências); o destino tem país registado e, em `prod`, o arranque é recusado fora de `AO` sem `apd_ref`. **Fica vazia** porque «nenhum dado pessoal sai de Angola sem `apd_ref`» é mais do que isto prova: o país é declarado e não verificado, a `apd_ref` é uma cadeia com forma, e o *gate* por tenant é do KAM-069 |
| DoD — sem segredos: credenciais via `SecretProvider` | **satisfeito** | `criarStorageS3` pede `storage_access_key_id` e `storage_secret_access_key` ao `SecretProvider` **em cada pedido** (há teste de rotação, com o `EnvSecretProvider` real); as duas entradas estão em `../ops/secrets-inventory.yaml` e o verificador passa (22 segredos). *Gate* 9 limpo. Nenhuma mensagem de erro leva credencial, URL assinada ou chave — incluindo `cause` e `__context__` |
| DoD — dependências: imagem por *digest*; Apache-2.0 verificada; MinIO ausente | **satisfeito** | `sha256:4e61d15f…872d`, igual ao `RepoDigests` local. `LICENSE` na etiqueta `4.48` do repositório: HTTP 200, Apache-2.0 (CONFIRMADO, 2026-10-12). `git grep -il minio` em `infra/`, `packages/`, `libs/` e `services/` só devolve o comentário do compose que diz que está excluído; `lint_arch` conforme. **Nenhuma dependência nova**: o SigV4 está escrito à mão nos dois lados |

#### Decisões tomadas neste ticket

- **Nenhuma dependência nova.** O SDK da AWS e o `boto3` trariam mais de cem
  pacotes; os dois núcleos partilhados não têm dependências de execução por
  desenho. O SigV4 está escrito à mão, e a prova de que está certo é o
  servidor real, não um teste nosso contra nós próprios.
- **`head` como sexto método**, para o CA8 se poder provar do lado do servidor.
- **`retain_until` obrigatório**, contra o esboço do próprio ticket. Um objecto
  sem prazo legal tem hoje de levar uma data; qual, é do consumidor ou do
  KAM-071.
- **A lista de classes não é fixada aqui**: só a forma (`snake_case`, 2 a 32
  caracteres).
- **`*/storage/*` no estrato `critico`** de `ci/thresholds.yaml`: é a camada
  «Storage» do isolamento. Muda um *gate* existente, não cria um; alterar
  limiares pede dois revisores, e essa caixa está vazia.
- **O SeaweedFS de teste vive num compose próprio**, fora do de
  desenvolvimento: a pilha `dev` não ganha um armazenamento por omissão
  enquanto a D6 estiver aberta.
- **Só endereçamento por caminho.** Um S3 gerido que exija *virtual-hosted*
  precisa de código novo — é um dado para a D6.

#### O que fica em aberto

- **A D6 e o seu ADR** (CA6).
- **A forma da chave no KAM-020** (`t/{tenant_id}/media/{classe}/…`), que a
  porta recusa: dicionário §3.11 e `../docs/dividas-documentais.md`, linha 8.
- **O registo do X-08 no KAM-066** e **o consumo de `config.destino` pelo
  KAM-069**, quando existirem.
- **Qualquer S3 gerido, TLS até ao servidor, cifra em repouso**: NÃO
  VERIFICADO.

### Detalhes Técnicos

- **Componentes:** STO (e MED como consumidor). Código em `packages/core-ts/storage/` e `libs/py-core/storage/`.
- **Contrato (esboço):**
```ts
interface StorageProvider {
  put(ctx: Ctx, key: ObjectKey, body: Stream, meta: { contentType: string; classe: string; retainUntil?: Instant }): Promise<ObjectRef>;
  get(ctx: Ctx, ref: ObjectRef): Promise<Stream>;
  signUrl(ctx: Ctx, ref: ObjectRef, o: { ttlSeconds: number /* ≤ 300 */ }): Promise<string>;
  delete(ctx: Ctx, ref: ObjectRef): Promise<void>;
  list(ctx: Ctx, prefix: string): Promise<ObjectRef[]>;
}
```
- **Cifra:** em repouso pelo servidor de objectos; cifra por objecto com a DEK do contacto (crypto-shredding de mídia, `../docs/tecnica/06` §7.6) fica como gancho, implementado em KAM-070/071.
- **Fora de âmbito:** pipeline de mídia (KAM-020), purga por retenção (KAM-071), WORM (`../docs/tecnica/08` §6: só em Clusters e NÃO VERIFICADO para SeaweedFS), Langfuse.

### Testes Requeridos

- Contrato: suite única sobre *fake* e SeaweedFS; objectos 1 KB/10 MB/25 MB; expiração de URL.
- Isolamento: X-08 (URL e listagem cruzadas).
- Configuração: arranque com `destino.country` ausente falha.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (isolamento de tenant); testes verdes; cobertura ≥ limiar.
- [ ] Documentação e ADR de D6 actualizados; Conventional Commits.
- [x] **Isolamento de tenant** — prefixo por tenant e teste cruzado X-08 do novo caminho.
- [ ] **Privacidade** — destino com país registado; nenhum dado pessoal sai de Angola sem `apd_ref`; URLs de curta duração; sem URLs da Meta persistidas.
- [x] **Sem segredos** — credenciais S3 via `SecretProvider`.
- [x] **Dependências** — imagem SeaweedFS por digest; licença Apache-2.0 verificada; MinIO ausente.

### Handoff para Claude Code

```text
És o executor do ticket KAM-011 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-011), ../docs/tecnica/08_Seguranca_Conformidade.md (§3.8, §7.5) e
../docs/tecnica/evidencia/E4_Stack_Licencas.md (§2.11). Objectivo: StorageProvider S3-compatível (ADR-014, D6).
- Interface com ctx.tenantId obrigatório; chaves t/{tenant_id}/{classe}/aaaa/mm/uuid; signUrl com TTL ≤ 300 s.
- Implementações S3 (SeaweedFS 4.48 ou gerido, por configuração) e fake; mesma suite de contrato.
- Testa multipart (25 MB), expiração de URL e object lock em SeaweedFS; regista em docs/evidencia; escreve o ADR de D6.
- Configuração exige destino.country/provider (consumido por KAM-069); metadados classe e retain_until.
Não expandas escopo: sem pipeline de mídia (KAM-020), sem purga (KAM-071), sem WORM. Nunca MinIO.
Testes: contrato, X-08, configuração. Abre PR com o template do §7.
```

---

## KAM-012 — `audit_log` append-only para dinheiro, stock e preço

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-003 |
| Bloqueia | KAM-028, KAM-054, KAM-099 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/08_Seguranca_Conformidade.md` (§6, §3.3), `../docs/tecnica/00_Arquitectura_Solucao.md` (§10.5), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.6), ADR-013, ADR-015 |

### Contexto

A ToolLayer audita as tools de dinheiro, stock e preço (ADR-015); o `ManualProvider` regista quem confirmou e o limite aplicado (ADR-013); o acesso de staff a conversas é auditado (acesso indevido é crime, Arts. 55–59.º, E3). `../docs/tecnica/08` §6 propõe, proporcionalmente ao Piloto, uma tabela *append-only* (privilégios + *trigger*), cadeia de hash por tenant, verificação nocturna e âncora diária do último hash exportada para fora do host. WORM real fica para Clusters (NÃO VERIFICADO para SeaweedFS). O conteúdo das conversas **nunca** vai para o `audit_log`. O backlog mestre marca este ticket P1 mas KAM-028 (P0) depende dele: sinalizado nos riscos.

### Objectivo

Criar `audit_log` imutável com função `audit_append`, encadeamento de hash por tenant, *job* nocturno de verificação e exportação da âncora diária.

### Critérios de Aceitação

- [ ] `UPDATE`, `DELETE` e `TRUNCATE` em `audit_log` falham para `kamba_app`, para o dono da tabela e para `kamba_batch` (privilégios revogados e *trigger* `BEFORE UPDATE OR DELETE` + de `TRUNCATE`).
- [ ] `audit_append(tenant, actor_type, actor_id, action, entity, entity_id, turn_id, before, after)` calcula `payload_hash` sobre o JSON canónico de *before/after* (nunca o conteúdo) e `row_hash = H(prev_hash ‖ campos)`.
- [ ] 1 000 inserções concorrentes para o mesmo tenant produzem uma cadeia linear (sem bifurcações, `prev_hash` único) validada pelo verificador.
- [ ] Vocabulário fechado de `action`: `price.update`, `stock.adjust`, `payment.manual_confirm`, `access.conversation`, `batch.run`, `breakglass.open` (extensível por migração); uma acção fora da lista é recusada.
- [ ] Adulterar uma linha (com `session_replication_role` no ambiente de teste) é detectado pelo *job* de verificação na execução seguinte, que levanta alerta Sev1.
- [ ] A âncora diária (`último row_hash` por tenant e dia) é escrita num `AnchorSink` (ficheiro local e `StorageProvider` quando existir); o ficheiro é reproduzível a partir da BD.
- [ ] Um teste de esquema prova que o `payload` aceite não tem campo de texto de mensagem (apenas hashes e identificadores).
- [ ] `audit_append` p95 ≤ 5 ms em 1 tenant com carga de 100 inserções/s (proposta).
- [ ] Leitura de `audit_log` por `kamba_app` recusada; leitura só por papel de auditoria com registo da própria leitura (`access.conversation`/`audit.read`).

### Detalhes Técnicos

- **Componentes:** GOV/OBS (consumida por TLS, PAY, ManualProvider). DDL de `../docs/tecnica/08` §6 (`id`, `ts`, `tenant_id`, `actor_type` ∈ `contact|owner|staff|agent|system`, `actor_id`, `action`, `entity`, `entity_id`, `turn_id`, `payload_hash`, `prev_hash`, `row_hash`).
- **Cadeia:** tabela auxiliar `audit_heads(tenant_id PK, last_hash)` bloqueada `FOR UPDATE` em `audit_append`, que serializa por tenant. `audit_append` é `SECURITY DEFINER` com `search_path` fixo e entra em `ci/secdef_allowlist.yaml` (exceção justificada: actualiza a cabeça da cadeia).
- **`tenant_id` nulo** (acções de plataforma): cadeia própria `tenant_id IS NULL`.
- **Hash:** SHA-256 sobre JSON canónico; vectores de teste fixos no repositório.
- **Fora de âmbito:** WORM, repositório de backup fora do host (KAM-079; até lá, âncora local), instrumentação das tools (KAM-028) e do `ManualProvider` (KAM-054).

### Testes Requeridos

- Segurança: tentativas de `UPDATE/DELETE/TRUNCATE` por 3 papéis; adulteração detectada.
- Concorrência: 1 000 inserções paralelas por tenant e verificação de cadeia.
- Unit: JSON canónico e vectores de hash; vocabulário de acções.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dinheiro, segurança); testes verdes; cobertura ≥ 90%.
- [ ] Documentação actualizada (`docs/auditoria.md`); Conventional Commits.
- [ ] **Isolamento de tenant** — cadeia por tenant, RLS e teste cruzado; leitura restrita.
- [ ] **Privacidade** — sem conteúdo de mensagens nem telefone em `audit_log`; só hashes e identificadores.
- [ ] **Custo e observabilidade** — métricas `audit_append_total`, `audit_chain_verify_failed_total`.
- [ ] **Migrações reversíveis** — `downgrade` testado (o *down* é aditivo: só em ambientes de teste).

### Handoff para Claude Code

```text
És o executor do ticket KAM-012 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-012) e ../docs/tecnica/08_Seguranca_Conformidade.md (§6, §3.3).
Objectivo: audit_log append-only com cadeia de hash por tenant.
- DDL do doc 08 §6; REVOKE UPDATE/DELETE/TRUNCATE + triggers; audit_heads bloqueada FOR UPDATE por tenant.
- audit_append(...) SECURITY DEFINER com search_path fixo (entrada na allowlist); payload_hash sobre JSON canónico.
- Vocabulário fechado de acções; job nocturno de verificação (Sev1 se falhar); AnchorSink (ficheiro/STO).
- Nunca guardes conteúdo de mensagens, telefone ou texto livre no log.
Não expandas escopo: sem WORM, sem backup fora do host (KAM-079), sem instrumentar tools (KAM-028).
Testes: imutabilidade por papel, 1 000 concorrentes, adulteração, vectores de hash. Abre PR com o template do §7.
```

---

## KAM-111 — Dicionário de dados canónico e reconciliação de `../docs/tecnica/`

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001, KAM-002, KAM-128 |
| Bloqueia | KAM-139, KAM-140, KAM-141 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/02_Dicionario_de_Dados_Canonico.md` (§3, §5, §6), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.2, §6.3, §13.2), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.2, §5.3, §12), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§6.2), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§4, §5, §7.2–§7.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.5, §8.5, §11, §14), `../docs/tecnica/10_Onboarding_Governanca.md` (§6.4, §15.1), `specs/01_Engineering_Standards_e_Handoff.md` (§4, gate 3b), ADR-009, ADR-010 |

### Contexto

Os documentos `../docs/tecnica/` e os epics foram escritos em paralelo e divergem em nomes, unidades e estados. O dicionário (`specs/02_Dicionario_de_Dados_Canonico.md`, versão 1.0 **proposta**) fixa um nome por conceito e prevalece sobre `../docs/tecnica/03`, `04`, `06`, `08` e `10` até este ticket estar `Done`. O KAM-003 **dependia** dele porque o primeiro DDL (`tenants`, `tenant_channels`, `entitlements`) não pode nascer com nomes que o dicionário rejeita; a **emenda E-01** da Carta §7 dispensou essa dependência, depois de os oito nomes de `platform` que faltavam entrarem no dicionário §3.2 (emenda 1.2). O que fica em dívida é a parte (b): sem o gate 3b, nada por máquina impede o DDL **seguinte** de divergir. O ticket tem **duas partes**: (a) emendar `../docs/tecnica/` nas 12 divergências da lista dos Detalhes Técnicos e **só nessas** (não é «rever tudo»); (b) um lint de CI, o gate 3b, que impede novas divergências. As escolhas marcadas «*proposta*» no dicionário só passam a decisão com a aprovação do Responsável de Produto, registada na tabela de versões do dicionário.

### Objectivo

Aplicar as 12 emendas de nomenclatura a `../docs/tecnica/` e entregar o lint `canon-lint`, que compara DDL de migrações, schemas de eventos e contratos de tools com as tabelas do §3 do dicionário e falha o build perante um nome fora dele.

### Critérios de Aceitação

- [ ] Parte (a): cada divergência D-01 a D-12 está resolvida no documento e secção indicados; uma pesquisa por cada variante substituída em `../docs/tecnica/` devolve 0 ocorrências, salvo notas explícitas «substitui X» e tabelas de correcção históricas (excepções listadas no PR).
- [ ] Âmbito fechado: o *diff* de `../docs/tecnica/` toca só as linhas das 12 divergências (≤ 80 linhas alteradas, *proposta*); qualquer outra divergência encontrada vira ticket `fix`. Cada documento tocado regista a emenda no seu «Controlo de versões» com referência a KAM-111.
- [x] Parte (b): `canon-lint` lê os nomes de `canon/dicionario.yaml`, exportado das tabelas do §3 por `tools/dict_export`; o CI falha se o ficheiro divergir do Markdown (a fonte da verdade é o dicionário).
- [ ] Verifica 3 superfícies: colunas, tabelas e valores de `CHECK` das migrações (`platform`, `servicos`, `lg`, `idx`); `tipo` e campos de payload em `contratos/eventos/**/v*.schema.json`; campos e parâmetros dos contratos de tools (`registry/*.yaml`).
- [ ] Dois níveis de falha: (1) qualquer nome da coluna «Substitui / variantes» do §3 (`valor_kz`, `callback_hmac_ok`, `sig_ok`, `consent_log`, `consent_ledger`, `consents`, `llm_calls`, `msisdn_hash`…) falha sempre; (2) nome de conceito não coberto pelo §3 só passa se constar de `canon/extensoes.yaml` (nome, tipo, ticket de origem, data), revisto pelo Arquitecto de Plataforma.
- [ ] Fixtures: 12 negativas (uma por divergência; build vermelho com a mensagem «<variante> → <canónico>, dicionário §3.x») e 12 positivas; mutação deliberada (`valor_kz` numa migração de teste) torna o gate vermelho; o lint corre em ≤ 60 s (*proposta*).
- [x] O gate 3b corre como *job* bloqueante de merge; se KAM-001/KAM-002 ainda não estiverem `Done`, entrega-se o CLI e o alvo `make canon-lint` e a ligação ao pipeline fica pendente e registada no PR.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#17`, ramo `feature/KAM-111-dicionario-canonico-e-lint`.
**Cinco caixas marcadas, sete vazias** — cada uma com uma linha aqui. A primeira
versão passou os oito *gates* e foi **reprovada** pela revisão adversarial (3
bloqueantes, 9 maiores): o que se corrigiu, o que não se reproduziu e o que fica
está em [`ANALISE-05`](../docs/analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md).
Os números são os do ramo **já integrado com `main`** (KAM-004 e KAM-065 fundidos;
dicionário 1.5; revisão `0002`) e reproduzem-se com `make ci-3b`.

| CA | Estado | Evidência |
|---|---|---|
| 1 — parte (a): D-01 a D-12 resolvidas; pesquisa de cada variante a zero | **não satisfeito** — caixa vazia | As doze estão emendadas nas secções indicadas, e a pesquisa das variantes **das doze** dá zero salvo citações: `consent_log` 2→0, `consent_ledger` 6→0, `consents` 4→0, `sig_ok` 1→0, `llm_calls` 2→0, `valor_kz` 5→1 e `callback_hmac_ok` 5→1 (as duas que ficam são a tabela «Correcção ao documento 11» de `04` §6.1). **Mas ficam 19 usos vivos de seis variantes do §3 que as doze não cobrem** (`kamba_ops` ×3, `valor_max_pedido_kz` ×3, `preco_kz` ×8, `'exato'` ×2, `total_kz` ×2, e `tenant_isolamento` ×1, que passou a variante com a emenda 1.5 do KAM-004), e o critério só admite citações. O critério 2 proíbe tocar-lhes; os dois chocam. Estão declaradas em `ci/canon-allow.yaml` como dívidas **com prazo a 2026-11-10** — a partir do dia seguinte o gate 3b fica vermelho em `main` — e são o **KAM-139**. Fica também por resolver, por não ter variante com nome: D-05 em `03` §2 e §6.2 e `04` §2 e §7; D-08 em `07` (KAM-140). |
| 2 — âmbito fechado: ≤ 80 linhas; o resto vira ticket `fix`; controlo de versões | **não satisfeito** — caixa vazia | `git diff --shortstat origin/main...HEAD -- docs/tecnica`: **87 inserções, 72 remoções**, 10 documentos. Acima de 80 (*proposta*) em qualquer leitura que conte inserções; 77 sem as dez linhas de controlo de versões. Doze linhas estão fora da coluna «Onde emendar» — todas de uma das doze divergências (a pesquisa não dava zero sem elas, ou as FK para `contacts(id)` partiam), incluindo `00` §9, que o ticket não lista. **Cumpridos:** os tickets `fix` existem (KAM-139, KAM-140, KAM-141, neste epic e no backlog mestre), e os dez documentos têm a linha 1.1 com KAM-111 e as secções tocadas. A leitura de «linhas alteradas» não está fixada em lado nenhum: decide quem escreveu o critério. |
| 3 — `canon/dicionario.yaml` exportado do §3; o CI falha se divergir | **satisfeito** | `tools/dict_export` gera o ficheiro (66 entradas, 14 variantes, do dicionário 1.5); o primeiro passo de `make ci-3b` é `dict_export --check`, verde no *job* `gate 3b — nomes canonicos`. Testes: mudar o Markdown sem regenerar falha, editar o YAML à mão falha, dicionário ilegível é erro 2; o conjunto das 14 variantes está fixado num teste, conferido à mão contra a coluna «Substitui». **Limite:** uma variante sem crases, ou em prosa fora de tabela, não é vista — não tem forma mecânica. |
| 4 — verifica 3 superfícies | **parcial** — caixa vazia | As três estão implementadas e testadas (migrações: `sql.py`, `revisao.py`, `ddl.py`; eventos: `eventos.py`; registo: `registo.py`). **Só uma tem ficheiros reais**: as revisões `0001` e `0002` (49 instruções — 21 e 28 —, 3 tabelas, 38 colunas, 20 valores de `CHECK`, zero achados, zero ilegíveis). `contratos/eventos/` e `registry/*.yaml` não existem — nascem com o KAM-007 e o EPIC-03 — e o que se sabe dessas duas vem de *fixtures* e de testes. Dos quatro esquemas do critério só `platform` tem migração; `servicos`, `lg` e `idx` não têm, e o caminho que o EPIC-06 lhes dá (`migrations/NNNN_idx_schema.sql`) não é superfície: uma sentinela fá-lo falhar até ser declarado. «Parâmetros dos contratos de tools» não têm forma definida no desenho (`02` §5.1 só mostra nomes); o lint lê as chaves `parametros`/`params`/`args` e recusa as outras. |
| 5 — dois níveis de falha; extensões revistas pelo Arquitecto | **parcial** — caixa vazia | Nível 1: as oito variantes que o critério nomeia, e as outras seis, falham em qualquer superfície, incluindo dentro de cadeias SQL e de JSON; uma extensão não as pode declarar (erro de configuração). Nível 2: `canon/extensoes.yaml` tem nome, tipo, ticket e data (20 entradas, as colunas da `0001` que o §3 não enumera), e um nome fora dele falha. **Duas coisas em falta.** (a) **A revisão pelo Arquitecto de Plataforma não aconteceu** e não é imposta — o *ruleset* tem zero aprovações. (b) **O nível 2 não sabe o tipo de um nome**: tabelas, colunas, valores, campos e parâmetros partilham 219 nomes. Medido com 77 nomes plausivelmente errados: 37 (48%) passam como coluna; 0 como evento, *tool* ou papel (eram 51, 66%, antes da revisão). KAM-141, linha 9. |
| 6 — 12 + 12 *fixtures*; mutação `valor_kz`; ≤ 60 s | **não satisfeito** — caixa vazia | **10 + 10**: D-07 e D-09 não têm forma de nome em nenhuma das três superfícies, e não se inventaram *fixtures* (KAM-141, linha 8). A positiva do D-03 não tem `currency`, que o §3 não lista (KAM-141, linha 2). **Cumpridos:** cada negativa dá exactamente um achado com a mensagem «`variante` → `canónico`, dicionário §3.x»; `valor_kz` na revisão `0001` (em cópia) deixa o gate vermelho; o *job* do gate leva 6 s no *runner* e `make ci-3b` 0,9 s num contentor local. |
| 7 — gate 3b como *job* bloqueante de merge | **satisfeito** | *Job* `gate 3b — nomes canonicos` no *workflow*, nos `needs` de `gates do KAM-002`, que é *required check*; `esperados=9` (com o gate 6 do KAM-004). **Demonstrado com um PR deliberadamente vermelho** (#19, `llm_calls` reposto em `09`): gate 3b `fail` com «`llm_calls` → `llm_call_log`, dicionário §3.6», resumo `fail`, `mergeStateStatus: BLOCKED`; *run* 38175423832. O gate 4 falhou por arrasto (um teste corre o lint sobre o repositório). O PR foi fechado sem fundir. **Limite:** o contexto do gate 3b não está no *ruleset* — bloqueia pelo resumo, como o gate 8 (`docs/ci.md` §7, lacuna 17). |

| DoD | Estado | Evidência |
|---|---|---|
| Todos os critérios satisfeitos e demonstráveis | **não satisfeito** — caixa vazia | Critérios 1, 2, 4, 5 e 6. |
| Revisto por ≥ 1 revisor; parte (a) pelo Responsável de Produto | **não satisfeito** — caixa vazia | Nenhuma revisão humana. A revisão adversarial é evidência, não é um revisor. |
| `docs/nomes-canonicos.md`; Conventional Commits | **satisfeito** | [`docs/nomes-canonicos.md`](../docs/nomes-canonicos.md) §5 («Como acrescentar uma extensão»); os *commits* do ramo têm `KAM-111` no âmbito e passaram o *hook* `commit-msg`. |
| **Eventos** — D-12 reflecte a regra do envelope | **satisfeito** | `../docs/tecnica/03` §12: «versões desconhecidas **falham de forma visível** (bloqueio com alerta, `06` §6.6), nunca são ignoradas em silêncio». A regra `versao` com `const` nos *schemas* é uma leitura mecânica dela, *proposta*, e não é o que esta caixa pede. |
| Dependências fixadas, licenças permitidas, sem segredos | **satisfeito** | Nenhuma dependência nova: os dois pacotes usam só a biblioteca padrão (o ticket admitia uma biblioteca de DDL; não se usou). Gates 9 e 11 verdes no PR. |

**Contagem conferida:** 12 caixas = 5 marcadas + 7 vazias.

**O que este ticket deixa a correr com prazo.** As nove entradas `dividas` de
`ci/canon-allow.yaml` vencem a **2026-11-10**. A 2026-11-11 o gate 3b fica
vermelho em `main` e em todos os PR. É deliberado — a alternativa é uma lista de
dívidas que ninguém revisita — e o ticket que as paga é o KAM-139.

**As três divergências que o KAM-003 deixou registadas**, e que não constam das
doze:

1. `kamba_ops` contra `kamba_batch` — **apanhada** pelo gate (`03` §5.5, `04`
   §6.2; três ocorrências), declarada como dívida. Emenda proposta: `kamba_batch`;
   em `04` §6.2 o `REVOKE` é de um papel que não existe. KAM-139.
2. O DDL de `tenant_channels` de `03` §5.2 contra o de `01` §7.1 — **não
   apanhada nos documentos**: `pausado`, `revogado` e `persona` não são
   variantes da coluna «Substitui», e os documentos só têm nível 1. **Numa
   migração** seria recusada (há um teste com esse DDL). Emenda proposta: `03`
   §5.2 remete para `01` §7.1. KAM-140.
3. `valor_max_pedido_kz` contra `valor_max_pedido_minor` — **apanhada** (`02`
   §5.1, §6.1, §6.2), declarada como dívida. KAM-139.

**Integração com o KAM-004.** A revisão `0002` desse ticket monta o SQL com
*f-strings* e chama `db/rls.py`. O gate lê-a seguindo o auxiliar com os
argumentos da chamada: **28 instruções, 18 delas vindas de `db/rls.py`, zero
achados e zero ilegíveis** — medido primeiro contra o ramo do KAM-004, numa cópia
(`ANALISE-05` §4), e depois sobre `main` já integrado, onde é o que o gate faz em
cada execução e está fixado num teste. `canon/extensoes.yaml` não precisou de
entradas novas. `db/rls.py` está declarado em
`ci/canon-lint.yaml` (`auxiliares_de_migracao`) e **não** é dispensado de leitura.

### Detalhes Técnicos

- **Componentes:** transversal (CI e documentação); sem código de runtime. O parser de DDL usa biblioteca de licença permitida (KAM-067). Fora de âmbito: reescrever o dicionário (só por emenda, dicionário §5–§6), nomes de tabelas que o §3 não cobre (vão para `extensoes.yaml`), reconciliar os tickets (já usam o dicionário).

| # | Variante → nome canónico (dicionário) | Onde emendar |
|---|---|---|
| D-01 | três versões de `contacts` → `contacts` + `contact_endpoints` (§3.1) | `01` §6.2, `03` §5.3, `06` §7.2 |
| D-02 | `consent_log`, `consent_ledger`, `consents` → `consent_event` (§3.1) | `01` §6.2–§6.3, `05` §10, `06` §7.3, `08` §8.1, §8.4, §8.5, §8.7 |
| D-03 | `valor_kz` → `valor_minor` + `currency` (§3.4) | `06` §4, §10.3 |
| D-04 | `callback_hmac_ok`, `sig_ok` → `authn_ok` + `authn_method` (§3.4) | `04` §6.2, `06` §4, `08` §4.5, §14 |
| D-05 | `payment.confirmed` usado para ambos os caminhos → dois eventos, `payment.confirmed` e `payment.manual_confirmed` (§3.4) | `04` §4.1, `06` §5, `03` §12 |
| D-06 | `UNIQUE(provider, referencia)` → unicidade de `04` §6.2; idempotência `(provider, account_id, referencia)` (§3.4) | `08`: o dicionário indica §6 (auditoria); a ocorrência encontrada é o dedup de §4.5; confirmar |
| D-07 | `tenant.activated` como gatilho → `tenant.approved` (§3.5) | `01` §13.2, `02` §13.1, `03` §12, `06` §5 |
| D-08 | tenant sem `restrito`; RED → `suspenso` → `restrito` (§3.2) | `03` §5.2, `10` §6.4, §15.1 |
| D-09 | retenção de `assistant_queries` 12 vs 13 meses → 12 (*proposta*, §3.6) | `06` §7.4 alinha com `08` §11 |
| D-10 | `llm_calls` → `llm_call_log` (§3.6) | `09` §9.3, §20 |
| D-11 | `confirm:{cart_id}` para ambas → `confirm:{hold_id}` em Serviços (§3.3) | `02` §6.2, §6.3, §8.2 |
| D-12 | «consumidores ignoram versões desconhecidas» → falham de forma visível (§3.5) | `03` §12 |

### Testes Requeridos

- Unit: parsers de DDL, de JSON Schema e de contratos de tools; exportação do dicionário (cada linha do §3 gera uma entrada).
- Fixtures: 12 + 12 e a mutação acima; o lint passa sobre as próprias tabelas do dicionário.
- Revisão: pesquisa das 12 variantes em `../docs/tecnica/` antes e depois, anexa ao PR.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; a parte (a) revista também pelo Responsável de Produto.
- [x] Documentação actualizada: `docs/nomes-canonicos.md` (como acrescentar uma extensão); Conventional Commits.
- [x] **Eventos** — D-12 reflecte a regra do envelope: versões desconhecidas falham de forma visível (ADR-009).
- [x] Dependências do lint fixadas, licenças permitidas, sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-111 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-111) e specs/02_Dicionario_de_Dados_Canonico.md (§3, §5, §6).
Objectivo: (a) emendar ../docs/tecnica/ nas 12 divergências D-01 a D-12 e só nelas; (b) lint canon-lint (gate 3b).
- Parte (a): edita só as linhas listadas; regista a emenda no Controlo de versões de cada documento; o resto vira ticket fix.
- Parte (b): exporta o §3 para canon/dicionario.yaml; verifica DDL, schemas de eventos e contratos de tools; variante conhecida
  falha sempre; nome fora do §3 exige entrada em canon/extensoes.yaml. Não inventes nomes: o dicionário manda.
Não expandas escopo: sem reescrever o dicionário nem os tickets. Testes: 12 fixtures negativas e 12 positivas, mutação.
Abre PR com o template do §7.
```

---

## KAM-128 — Reorganização do conjunto documental sob `docs/` e reescrita das referências cruzadas

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001 |
| Bloqueia | KAM-111, KAM-129, KAM-130, KAM-145, KAM-146, KAM-147, KAM-150 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/INDICE.md`, `../docs/tecnica/INDICE.md`, `specs/INDICE.md` (§1, §3.1, §4, §7), `specs/01_Engineering_Standards_e_Handoff.md` (§4 gate 3, §5), `../docs/adr/README.md`, `README.md` |

### Contexto

O conjunto documental nasceu na raiz do repositório: `tecnica/`, `analises/`, a biblioteca exploratória `01`–`14`, o `INDICE.md` e o documento mestre. Com a entrada de código em KAM-001 (`services/`, `packages/`, `libs/`, `tools/`, …), a raiz passou a misturar duas coisas que se leem de maneiras diferentes, e deixou de dizer o que é material de leitura e o que é executável. Este ticket move o material de leitura para `docs/` e mantém `specs/` na raiz, por ser o backlog executável e o contrato de execução, não documentação.

**Este ticket é retroactivo, e é isso que este parágrafo regista.** O trabalho já está na história, em dois commits feitos **sem ticket**: `d2dbb14` (34 renomeações puras, `R100`, zero alterações de conteúdo) e `53189a2` (referências cruzadas de 37 documentos, mais o documento mestre recompilado e o `docs/compilar-mestre.sh`). Entraram no ramo do KAM-001 por descuido de um `git add -A`, foram separados em commits próprios com a razão escrita na mensagem, e usaram `--no-verify` porque nenhum `KAM-NNN` os cobria. Este ticket é essa cobertura: fecha a dívida que esses dois commits deixaram registada e completa o que ficou a meio.

**Porque não é o KAM-111.** O KAM-111 é o candidato óbvio e não serve. O seu critério de aceitação fecha o âmbito em «12 divergências de nomenclatura, ≤ 80 linhas alteradas» e em «o *diff* de `tecnica/` toca só as linhas das 12 divergências». Mover directórios e reescrever ~1300 referências não cabe lá, e carimbar o KAM-111 falsearia o seu próprio critério — ficaria satisfeito pela razão errada. São também dois problemas distintos: o KAM-111 reconcilia **nomes de dados**, este reorganiza **a árvore de ficheiros**. Por isso o KAM-128 **bloqueia** o KAM-111: a emenda das 12 divergências tem de incidir sobre a árvore final, ou o seu *diff* e as suas buscas nascem inválidos.

**Convenção de caminhos — decisão registada.** O conjunto tinha já duas convenções em uso. A reorganização obrigou a escolher, e escolheu-se **por posição do ficheiro**, não uma forma única:

| Onde | Convenção em vigor | Porquê |
|---|---|---|
| `specs/**` → `docs/**` | relativa ao ficheiro: `../docs/tecnica/NN_…` | 1098 ocorrências; resolve como ligação clicável a partir de `specs/` |
| `specs/**` → `specs/**` | relativa à raiz: `specs/01_…` | 270 ocorrências pré-existentes, mantidas |
| dentro de `docs/tecnica/` | irmão nu: `NN_…` ou `` `NN` `` | convenção já nativa do directório (`evidencia/E1_…`, 34 referências `` `NN` ``) |
| dentro de `docs/` | irmão nu: `00-KAMBA-documento-mestre.md` | o índice já ligava assim |

Não se uniformizou o conjunto numa só convenção: seria um *diff* de ~1400 linhas sem ganho funcional e alargaria o âmbito sem necessidade. O que se exige é que **toda a referência resolva**, não que todas tenham a mesma forma.

### Objectivo

Deixar o conjunto documental sob `docs/`, com `specs/` na raiz, sem nenhuma referência cruzada pendurada, sem nenhuma afirmação estrutural falsa nos índices e nos cabeçalhos de navegação, e com o documento mestre a ser artefacto reproduzível em vez de ficheiro editado à mão.

### Critérios de Aceitação

- [x] A árvore é `docs/tecnica/`, `docs/analises/`, `docs/exploracao/` (biblioteca `01`–`14`), `docs/INDICE.md` e `docs/00-KAMBA-documento-mestre.md`; `specs/`, `docs/adr/` e `docs/evidencia/` ficam onde estavam. `git show --name-status d2dbb14` confirma 34 linhas `R100` e 0 linhas `M` — conteúdo inalterado.
- [x] **Zero ligações markdown quebradas** em todo o conjunto `.md`, verificado por script que resolve cada `[texto](caminho)` relativo ao ficheiro **e** relativo à raiz (ver Testes Requeridos). Antes: 3; alvo: 0.
- [x] **Zero referências `tecnica/NN` dentro de `docs/tecnica/`** (busca G1 dos Testes Requeridos). Antes: 216 — não resolviam de posição nenhuma, porque eram relativas à antiga raiz.
- [x] As referências a `analises/` apontam para `docs/analises/` ou `../analises/`, conforme a posição (buscas G2 e G3): 4 corrigidas em `.claude/skills/agentic-engineering/` e 3 ligações do documento mestre em `../docs/INDICE.md`, que apontavam para `exploracao/` quando o mestre está em `docs/`.
- [ ] As referências nuas a ficheiros da biblioteca (`14-tese-minima-e-plano-de-validacao.md`, `01-modelo-negocios-angola-ai-first.md`) passam a `../docs/exploracao/…` em `specs/` e a `docs/exploracao/…` em `.claude/skills/`: 10 ocorrências. Cai com elas a afirmação de que a biblioteca está «na raiz de `Ideias/`» (`specs/EPIC-10` §: Abreviaturas). **Excepção deliberada:** as 24 ocorrências dentro de `docs/00-KAMBA-documento-mestre.md` não se tocam — são herdadas das fontes, onde são irmãs correctas, e o mestre é gerado; corrigi-las à mão seria editar um artefacto compilado e perder-se-ia na regeneração seguinte.
- [x] Nenhum caminho **funcional** da *toolchain* quebra: `make lint-arch` e a parte Python de `make check` ficam verdes. O único caminho documental lido por código é `docs/evidencia/KAM-001-node.md`, em `tools/lint_arch/structure.py` (`REQUIRED_FILES`), e não se move.
- [x] Os cabeçalhos de navegação deixam de descrever a árvore antiga: `../docs/INDICE.md` (§2, §6 e linha de fecho), `../docs/tecnica/INDICE.md` (§4, §6), `README.md` («O que está aqui», «Onde ler o quê») e a tabela de fontes de verdade de `.claude/skills/agentic-engineering/SKILL.md` §1.
- [x] O documento mestre é gerado por `docs/compilar-mestre.sh` a partir de `docs/exploracao/*.md`, declara-o no cabeçalho («NÃO EDITAR À MÃO») e inclui a PARTE 14, que o `../docs/INDICE.md` §2 já listava e o ficheiro não tinha: 13 partes (01–08, 10–14). O script é idempotente — duas execuções seguidas dão o mesmo ficheiro, *byte* a *byte*. Corolário que vale como regra: **quem editar uma fonte em `docs/exploracao/` regenera o mestre no mesmo commit**, ou deixa um artefacto gerado desactualizado em `git`.
- [x] O backlog fica sincronizado nos dois lados: linha em `specs/INDICE.md` §4 (sub-tabela do EPIC-01) e bloco `## KAM-128 — ` neste epic, com tipo, estimativa, prioridade, fase e dependências iguais; `Bloqueia` do KAM-001 e `Dependências` do KAM-111 actualizados; contagens de `specs/INDICE.md` §1 e §3.1 e de `README.md` a dizer 128.
- [ ] Cada documento formal tocado regista a emenda no seu «Controlo de versões» com referência a KAM-128.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#2`, fundido em `main` (`6eb618f`); o trabalho
está em `08426f3`, com `d2dbb14` e `53189a2` na história do ramo do KAM-001.
Medido a 2026-10-11 sobre `main` (`1401cd3`), por *script* no *scratchpad* — o
gate 3 (`tools/lint_refs`) é o KAM-002 e ainda não está em `main`. Os valores
«antes» foram medidos contra `df03076`, o pai de `08426f3`. Cada caixa marcada
acima tem uma linha aqui; **as cinco não marcadas também**. Quatro destas linhas
foram emendadas depois da revisão adversarial registada em
`../docs/analises/ANALISE-04-encerramento-kam-001-128-129.md`.

| CA | Estado | Evidência |
|---|---|---|
| Árvore e renomeações puras | **satisfeito** | Árvore conforme: `docs/tecnica/` (12 `.md` mais o subdirectório de evidência), `docs/analises/` (1), `docs/exploracao/` (14, `01`–`14`), `docs/INDICE.md`, `docs/00-KAMBA-documento-mestre.md`; `specs/` (16), `docs/adr/` (2) e `docs/evidencia/` (1) onde estavam; a raiz já não tem `tecnica/` nem `analises/`. `git show --name-status d2dbb14` → **34** linhas `R100`, **0** linhas `M` |
| Zero ligações markdown quebradas | **satisfeito** | Resolvedor sobre os 66 `.md`, cada `[texto](caminho)` resolvido relativo ao ficheiro **e** relativo à raiz, excluídos os marcadores de forma: **antes 3, agora 0**. As três eram as mesmas de G3 — `docs/INDICE.md` a ligar para `exploracao/00-KAMBA-documento-mestre.md`, que está em `docs/` e não em `docs/exploracao/` |
| G1: zero `tecnica/NN` em `docs/tecnica/` | **satisfeito** | **antes 216, agora 0**, medido com o padrão do CA sobre `docs/tecnica/` |
| G2 e G3 a zero | **satisfeito** | Sobre a árvore seguida pelo git: G2 **antes 4, agora 0** (as 4 eram em `.claude/skills/agentic-engineering/`, como o CA diz); G3 **antes 3, agora 0** (as 3 ligações do mestre em `docs/INDICE.md`). Nota de medição: sobre o sistema de ficheiros cru G2 dá 1, num ficheiro de estado de execução sob `.claude/state/` — **não rastreado** e transitório, fora da árvore que o gate varre |
| Referências nuas à biblioteca: 10 ocorrências | **não satisfeito** | As 10 estão corrigidas, mas **não eram todas**. Em `df03076` havia **17** ocorrências nuas em `specs/` e `.claude/skills/` — 8 em `specs/EPIC-10`, 6 em `specs/EPIC-11`, 3 na *skill*. Hoje restam **7**, contadas com a mesma exclusão de `EPIC-01` que as buscas G1–G3 declaram (o próprio texto deste critério acrescentou-lhe 2 ocorrências nuas): `specs/EPIC-10` linhas 105, 288, 469, 589, 649, 709 e `specs/EPIC-11` linha 784. Todas as 7 estão **dentro de blocos de *handoff*** — que é precisamente a questão que o KAM-129 deixou em aberto para os caminhos de evidência, mas que este ticket não declarou como excepção. O CA afirma uma população de 10 e a população é 17; fica por marcar até quem escreveu o critério decidir se os blocos de *handoff* são excepção. Segunda leitura, menor: a excepção declarada do mestre diz «24 ocorrências» e a medição dá **25** (sob qualquer regra de contagem que tentei — todas em *code-span*, nenhuma em posição de alvo de ligação); as 24 saem se se excluir a referência ao ficheiro `09`, que o mestre não inclui como parte |
| Nenhum caminho funcional da *toolchain* quebra | **satisfeito** | `lint_arch --root . all` → «lista de bloqueio: conforme», «estrutura: conforme». Parte Python de `make check`: `pip_lock.py --check-offline` → «coerente com os pins» (2 ficheiros); `test-py` → as **três** suites verdes no contentor, **75 + 13 + 7**. No anfitrião só as duas primeiras são reproduzíveis — a do AGR exige o `.venv` que `make bootstrap` cria, e `libs/py-core` só passa com `PYTHONPATH` explícito. `docs/evidencia/KAM-001-node.md` continua em `REQUIRED_FILES` de `tools/lint_arch/structure.py` e não se moveu |
| Cabeçalhos de navegação | **satisfeito** | Os quatro lidos e conformes à árvore nova: `docs/INDICE.md` §2 (bloco de árvore com `docs/` e `specs/` na raiz) e linha de fecho (liga a `00-KAMBA-documento-mestre.md` e `exploracao/13-big-picture-ecossistema.md`); `docs/tecnica/INDICE.md` §4 (`../exploracao/01`–`13`) e §6 (`../exploracao/`, `../00-KAMBA-documento-mestre.md`, `../../specs/INDICE.md`); `README.md` «O que está aqui» (árvore com `docs/` e as suas quatro subpastas) e «Onde ler o quê»; `.claude/skills/agentic-engineering/SKILL.md` §1 (tabela de fontes de verdade, com `docs/tecnica/`, `docs/exploracao/`). Duas ressalvas: o §6 de `docs/INDICE.md`, que o critério nomeia, não foi examinado na primeira passagem — está conforme à árvore, mas afirma que o mestre «compila as partes 01–13», afirmação que o CA8 deste ticket falsifica (13 partes, `01`–`08` e `10`–`14`); e o mesmo ficheiro repete-a no §2 e no §4. É defeito real, sem ticket que o cubra — inventariado em `../docs/analises/ANALISE-04-encerramento-kam-001-128-129.md` §5 |
| Mestre gerado e idempotente | **satisfeito** | `bash docs/compilar-mestre.sh` duas vezes seguidas: «mestre regenerado: 175733 bytes, 13 partes» nas duas, `sha256` igual nas duas (`de9669847792bfc5998f22bd4cd0c58dbc7b44c8745060ca506100191d777fb7`) e **igual ao que está em git** — `git status --short` vazio depois de cada execução. Cabeçalho declara «NÃO EDITAR À MÃO»; 13 partes, `01`–`08` e `10`–`14`, com a PARTE 14 presente |
| Backlog sincronizado e contagens | **satisfeito** | Linha do §4 com `chore`, `M`, `P0`, fase 0 e dependência `KAM-001` — igual ao bloco deste epic. `Bloqueia` do KAM-001 contém `KAM-128`; `Dependências` do KAM-111 contém `KAM-128`. No *merge* do ticket (`6eb618f`), `specs/INDICE.md` §1 dizia «128 tickets atómicos (KAM-001 a KAM-128)» e o `README.md` «Backlog mestre (128 tickets)». À data da medição (2026-10-11) diziam 130, por causa do KAM-129 e do KAM-130, e a linha de versão 1.4 do `specs/INDICE.md` regista essa passagem. **Remedição a 2026-10-12:** o backlog cresceu para **143** e o `specs/INDICE.md` §1 e o §3.1 acompanharam; o `README.md` ficou atrás, a dizer 130 — defeito de contagem da classe que o KAM-130 possui, não deste ticket. O que este critério exige é a sincronia dos dois lados, e essa mantém-se |
| Controlo de versões com KAM-128 | **não satisfeito** | Dos **15** documentos formais tocados por `08426f3` que têm tabela de versões, só **4** registam a emenda: `docs/INDICE.md`, `docs/tecnica/INDICE.md`, `specs/INDICE.md` e `specs/EPIC-01_Fundacoes_Dados.md`. Os **11** que ficaram sem linha: `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/02_Agent_Runtime_Verticais.md`, `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/07_Geo_Logistica_Federada.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/09_Topologia_Operacao_Escala.md`, `../docs/tecnica/10_Onboarding_Governanca.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md` e `specs/EPIC-11_Modulos_Entrada.md` — todos com «Controlo de versões» e nenhum com menção a KAM-128 |
| DoD: todos os CA satisfeitos, evidência em `docs/evidencia/KAM-128.md` | **não satisfeito** | Dois CA em aberto (população das referências nuas, controlo de versões), e o ficheiro de evidência que o DoD nomeia **não existe**: `docs/evidencia/` tem só `KAM-001-node.md` |
| DoD: ≥ 1 revisor e revisão do Arquitecto | **não satisfeito** | O PR #2 foi fundido com `reviewDecision: REVIEW_REQUIRED` e `reviews: []` — **zero** revisores humanos |
| DoD: documentação actualizada | **satisfeito** | Os quatro documentos que o DoD nomeia estão actualizados (linha dos cabeçalhos de navegação, acima); *Conventional Commits*: `08426f3` é «chore(KAM-128): regulariza a reorganizacao documental e fecha as referencias» |
| DoD: sincronia mestre↔epics | **satisfeito** | O critério é a **igualdade dos dois lados e zero divergências**, e não um número absoluto — que o backlog muda. À data da medição (2026-10-11): **130** linhas `KAM-NNN` no backlog mestre e **130** blocos `## KAM-NNN` únicos nos 11 epics, sem órfãos de nenhum lado, **0** divergências de tipo, prioridade, estimativa, fase e dependências, e segunda passagem byte a byte idêntica com `git status --short` vazio — verificação, não edição. **Remedido a 2026-10-12: 143 e 143, 0 órfãos de cada lado, 0 divergências.** O invariante aguenta |
| DoD: todo o caminho citado resolve | **não satisfeito** | Dentro de `.md` resolve (linha das ligações markdown). Fora, não: o `CODEOWNERS` tem **3** regras que apontam para caminhos que a reorganização removeu — a de `/tecnica/`, a de `/tecnica/evidencia/` e a do documento 08 de segurança sob o mesmo prefixo. Um `CODEOWNERS` que aponta para um directório inexistente não atribui dono nenhum, e é um caminho funcional, não prosa |
| DoD: sem segredos | **satisfeito** | Não aplicável como o ticket declara, e verificado: `08426f3` toca **23** ficheiros, **todos `.md`**; nenhuma configuração nem dependência nova. Ressalva de âmbito: o `docs/compilar-mestre.sh` não vem deste *commit* — foi criado por `53189a2`, e é o único dos três *commits* da cobertura retroactiva que acrescentou um *script* executável, pelo que é o que esta linha **não** cobre |
| DoD: defeitos fora do âmbito em ticket próprio | **satisfeito** | KAM-129 (prefixo das referências de evidência) e KAM-130 (contagens e intervalos herdados) abertos, ambos com bloco próprio neste epic e linha no backlog mestre, e o bloco do KAM-130 escreve a justificação da separação |

> **O que isto custa, dito com clareza.** Três defeitos reais, nenhum deles
> grande: sete referências nuas por converter, onze documentos formais sem linha
> de versão, e três regras de `CODEOWNERS` penduradas. Nenhum impede navegar o
> conjunto; todos contradizem uma afirmação do próprio ticket. Mais a revisão
> humana e o ficheiro de evidência, que faltam.

### Detalhes Técnicos

- **Componentes:** transversal (documentação e backlog); sem código de *runtime*, sem migrações, sem dependências novas. Ficheiros: `docs/**`, `specs/**`, `.claude/skills/agentic-engineering/**`, `README.md`, `docs/compilar-mestre.sh`.
- **Renomeações:** feitas com `git mv`, para que o git as registe como `R100` e a revisão confirme em segundos que nenhum conteúdo mudou. Mover e editar no mesmo commit destrói essa garantia — foi por isso que `d2dbb14` (mover) e `53189a2` (editar) são commits separados.
- **Regra de posição:** a forma da referência depende de onde está o ficheiro que refere, não de preferência de estilo (tabela no Contexto). Uma substituição cega de `tecnica/` produz `docs/docs/tecnica/` e troca irmãos por caminhos que não resolvem: o script tem de excluir `docs/` e `../` à cabeça e conhecer a profundidade do ficheiro que está a editar.
- **Fora de âmbito:** uniformizar as duas convenções de caminho numa só; as referências `evidencia/EN_*.md` que **já não resolviam antes desta reorganização** (contagem idêntica em `main` e no ramo) — defeito pré-existente agora coberto pelo **KAM-129**, que ao medi-lo apurou 59 ocorrências em seis epics (EPIC-05 a EPIC-08, EPIC-10 e EPIC-11), e não as ~32 em três que esta nota estimou; as divergências de contagem herdadas («126 tickets» em `../docs/adr/ADR-L001-toolchain.md`, «13 vs 14 documentos activos» em `../docs/INDICE.md`, «E1–E4» onde são E1–E5, «D1–D12» onde são D1–D13, contagens de ADR 12/18/19 desactualizadas), cobertas pelo **KAM-130**; reescrever o conteúdo de qualquer documento exploratório.

### Testes Requeridos

- Verificação por máquina, não por leitura: script que extrai cada `[texto](caminho)` e cada caminho `.md` em *code-span* de todos os `.md` do conjunto, resolve-o relativo ao ficheiro **e** relativo à raiz, e falha se não resolver de nenhuma das duas formas. Corre antes e depois; o resultado vai no PR.
- Buscas de regressão, todas com resultado 0. Os padrões excluem as formas que **resolvem** (`docs/…`, `../…`): a prosa deste conjunto cita caminhos legítimos, e uma busca ingénua acusaria texto correcto. Excluem também este bloco de ticket, que cita necessariamente as formas erradas para as nomear — a mesma excepção que o KAM-111 usa para as suas tabelas de correcção histórica, e que se lista no PR.

```text
G1  grep -rPo '(?<!docs/)tecnica/\d{2}' docs/tecnica/
G2  grep -rPo '(?<!docs/)(?<!\.\./)analises/ANALISE' docs/ specs/ .claude/ README.md \
      --exclude=EPIC-01_Fundacoes_Dados.md
G3  grep -rPo '\]\(exploracao/00-KAMBA' docs/ specs/ .claude/
```
- Renomeações: `git show --name-status d2dbb14` → 34 linhas `R100`, 0 linhas `M`.
- Idempotência do mestre: `bash docs/compilar-mestre.sh` duas vezes seguidas deixa a árvore limpa (`git status --short` vazio).
- `make lint-arch` e a parte Python de `make check` (`lock-check`, `test-py`) verdes, antes e depois.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-128.md`).
- [ ] Revisto por ≥ 1 revisor; a árvore e a convenção de caminhos revistas também pelo Arquitecto de Plataforma.
- [x] Documentação actualizada: `../docs/INDICE.md`, `../docs/tecnica/INDICE.md`, `README.md` e a tabela de fontes de verdade da *skill*; Conventional Commits.
- [x] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e o bloco deste epic dizem o mesmo; segunda passagem de verificação dá 0 divergências.
- [ ] **Referências** — todo o caminho citado resolve; nenhum `KAM-NNN`, `ADR-NNN` ou `D#` citado deixou de existir.
- [x] **Sem segredos** — não aplicável: o ticket não acrescenta configuração nem dependências.
- [x] Defeitos encontrados fora do âmbito abertos como ticket `fix` próprio, não corrigidos aqui (`specs/01_Engineering_Standards_e_Handoff.md` §5).

### Handoff para Claude Code

```text
És o executor do ticket KAM-128 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-128) e specs/INDICE.md (§1, §3.1, §4, §7).
Objectivo: conjunto documental sob docs/, specs/ na raiz, zero referências cruzadas penduradas.
- Move com git mv, num commit só de renomeações (tem de dar R100); edita as referências num commit separado.
- A forma da referência depende da posição do ficheiro: de specs/ usa ../docs/tecnica/NN_...; dentro de
  docs/tecnica/ o irmão é nu (NN_... ou `NN`); dentro de docs/ o irmão é nu. Exclui docs/ e ../ antes de
  substituir, ou produzes docs/docs/tecnica/. Não uniformizes as duas convenções: está fora de âmbito.
- Regenera o mestre com docs/compilar-mestre.sh (inclui a PARTE 14); não o edites à mão.
- Actualiza os dois lados do backlog, as contagens (§1, §3.1, README) e o Controlo de versões de cada documento tocado.
Não expandas escopo: as referências evidencia/EN_*.md já estavam quebradas antes — são o KAM-129 (e as contagens herdadas o KAM-130).
Testes: script que resolve toda a ligação markdown e todo o caminho .md, antes e depois; make lint-arch verde.
Abre PR com o template do §7.
```

---

## KAM-129 — Correcção do prefixo das referências aos anexos de evidência em `specs/`

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-128 |
| Bloqueia | KAM-145, KAM-147 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/EPIC-05_Pagamentos_Billing.md`, `specs/EPIC-06_Indice_Pesquisa.md`, `specs/EPIC-07_Seguranca_Conformidade.md`, `specs/EPIC-08_Topologia_Operacao.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `specs/EPIC-11_Modulos_Entrada.md`, `specs/INDICE.md` (§4), bloco KAM-128 deste epic («Convenção de caminhos — decisão registada») |

### Contexto

Seis epics citam os anexos de evidência sem directório qualificador — `` `evidencia/E1_Meta_WhatsApp.md` ``, `` `evidencia/E3` ``, `` `evidencia/validacao/Gate_Fase0.md` `` — e essas referências **não resolvem de posição nenhuma**: a partir de `specs/` não existe `specs/evidencia/`, e a partir da raiz não existe `evidencia/`. O caminho real é `../docs/tecnica/evidencia/`, que é também a forma usada pelas restantes 168 referências a evidência feitas de `specs/` e a convenção registada no KAM-128.

**O defeito é pré-existente; não foi a reorganização que o causou.** A contagem é idêntica em `main` (`6d30625`, anterior a todo o trabalho de KAM-001 e KAM-128) e no ramo do KAM-128, e está declarada fora de âmbito no bloco do KAM-128 precisamente para vir a ticket `fix` próprio, como manda `specs/01_Engineering_Standards_e_Handoff.md` §5 («bug = novo ticket»). Verificação:

```text
# ancorado em commits fixos, e sem -c: o -c conta LINHAS e ignora o -oE,
# pelo que daria 51 (as linhas) em vez das 59 (as ocorrencias).
git grep -oE '(^|[^/A-Za-z._-])evidencia/' 6d30625   -- 'specs/EPIC-0[5-8]*.md' 'specs/EPIC-1[01]*.md' | wc -l    # -> 59
git grep -oE '(^|[^/A-Za-z._-])evidencia/' 08426f3   -- 'specs/EPIC-0[5-8]*.md' 'specs/EPIC-1[01]*.md' | wc -l    # -> 59
```

Os seis epics tem de ser enumerados: em `specs/*.md` os totais **nao** sao iguais (59 contra 62), porque o proprio bloco do KAM-128 acrescentou tres ocorrencias em `specs/EPIC-01` ao nomear o defeito. A identidade que prova a pre-existencia e a dos seis epics afectados, com a distribuicao 3/4/9/13/27/3 igual nos dois *commits*.

**Duas classes de alvo, que se distinguem antes de corrigir.** Confundi-las levaria a «criar ficheiros em falta» que nenhum ticket pediu:

| Classe | O que é | Existe em disco | O que se corrige |
|---|---|---|---|
| **A — anexo existente** | `E1`–`E5`, os cinco anexos de evidência | sim, `docs/tecnica/evidencia/EN_*.md` | só o prefixo |
| **B — artefacto futuro** | 13 alvos nomeados em 17 referências — `validacao/` seguido de `H3_Coexistencia_244.md`, `Meta_Perguntas.md`, `Gate_Fase0.md`, `Gate_Piloto.md`, `Piloto_Protocolo.md`, `Pacote_Parecer_Juridico.md`, `Pagamentos_Respostas.md`, `Tech_Provider_Dossie.md`, `Alojamento_Cotacoes.md`, `Entrevistas_Guiao.md`, `H7_Voz_STT.md`, `H10_H12_Modulos_Entrada.md`, `KAM-126_Factura_AI.md` — mais 1 referência nua ao directório `validacao/` | não, e **não deve existir ainda** | só o prefixo |

A classe B é a **saída** dos tickets de spike, de gate e de experimento (KAM-100 a KAM-110, KAM-120, KAM-126 e KAM-127): são artefactos que esses tickets criam quando correm. A sua ausência em disco não é defeito e este ticket não os cria.

Dois artefactos da mesma família **já estavam citados correctamente** e por isso não entram nas 59: `validacao/Registo_Hipoteses.md` (`specs/EPIC-10`, KAM-100) e `Carga_Dimensionamento.md` (`specs/EPIC-08`, KAM-084). Ficam aqui inventariados para que a classe se leia completa, mas nenhuma linha sua é tocada — e nenhum registo de emenda os pode dar como corrigidos. O `../docs/tecnica/evidencia/validacao/` também não se cria vazio — nasce com o primeiro artefacto.

**Duas formas de citação, ambas legítimas.** Parte das referências usa o nome completo (`` `evidencia/E3_Regulatorio_Dados.md` ``) e parte usa só o código do anexo com secção (`` `evidencia/E3` §7 ``). A forma-código é convenção pré-existente do conjunto, usada em documentos que este ticket não toca (`specs/00_KAMBA_Carta.md`, `specs/00_System_Spec.md`), e **nenhuma** referência a evidência feita de `specs/` é uma ligação markdown `[texto](caminho)` — são todas *code-span* em prosa. (O universal vale para `specs/`, não para o conjunto: `README.md` liga a `docs/tecnica/evidencia/E4_Stack_Licencas.md` em markdown, e `../docs/adr/ADR-L001-toolchain.md` e `../docs/PR-KAM-001.md` ligam a `docs/evidencia/KAM-001-node.md`. Nenhuma dessas está neste âmbito, e todas resolvem.) Por isso: corrige-se o prefixo e **mantém-se a forma**. Expandir os códigos para nomes completos mudaria 15 referências de prosa sem ganho funcional e sai de âmbito, pela mesma razão que o KAM-128 não uniformizou as duas convenções de caminho.

**Porque não é o KAM-128 nem o KAM-111.** O KAM-128 move a árvore e reescreve as referências que a mudança de árvore quebrou; estas estavam quebradas antes dela, pelo que carimbá-las no KAM-128 falsearia a sua afirmação central — que a contagem é idêntica em `main` e no ramo — e satisfaria o seu critério pela razão errada. O KAM-111 reconcilia **nomes de dados**, não caminhos de ficheiros, e tem o âmbito fechado em «12 divergências de nomenclatura, ≤ 80 linhas alteradas». Este ticket **depende** do KAM-128 porque o destino `../docs/tecnica/evidencia/` só existe depois da reorganização: corrigir antes produziria um prefixo que também não resolvia.

### Objectivo

Deixar toda a referência a evidência feita de `specs/` a resolver de posição — a dos anexos que existem, para o ficheiro em disco; a dos artefactos que ainda não existem, para o caminho onde o seu ticket os vai criar — sem alterar a forma das citações, sem criar ficheiros que nenhum ticket pediu e sem tocar no conteúdo técnico de nenhum epic.

### Critérios de Aceitação

- [ ] **Zero referências a evidência sem directório qualificador em `specs/`**: a busca G1 dos Testes Requeridos dá 0. Antes: 59, distribuídas por EPIC-05 (3), EPIC-06 (4), EPIC-07 (9), EPIC-08 (13), EPIC-10 (27) e EPIC-11 (3).
- [x] As 59 referências passam a `../docs/tecnica/evidencia/…`, **com a forma de citação inalterada**: 25 com nome completo de anexo, 15 na forma-código (`E1`–`E5`), 18 de artefacto futuro e 1 referência nua ao directório (em `specs/EPIC-05`, bloco KAM-059: «NÃO está em `../docs/tecnica/evidencia/`»).
- [x] **O *diff* é linha-por-linha**: nos seis epics, `git diff --numstat` dá **+57 −51**, decomposto em **51 inserções contra 51 eliminações** de linhas de referência (líquido 0) e **6 inserções** das linhas de «Controlo de versões», uma por epic. O líquido zero na parte das referências é a prova de que nenhuma frase foi reescrita e nenhum conteúdo técnico mudou; as 51 são menos do que as 59 porque **sete** linhas contêm mais do que uma referência, somando oito referências excedentes (quatro linhas de EPIC-08 com 2 cada; EPIC-10 com 2, 3 e 2).
- [ ] **Toda a referência de classe A resolve em disco**: o resolvedor da busca G2 confirma que cada `../docs/tecnica/evidencia/EN_*.md` existe; 25 de 25. As da forma-código não são caminhos de ficheiro e ficam fora do resolvedor, por desenho.
- [x] **Toda a referência de classe B consta da lista declarada** na tabela do Contexto e **nenhum ficheiro novo é criado**: `git status --short` não mostra ficheiros não rastreados sob `docs/tecnica/evidencia/`, e esse directório continua a ter exactamente os cinco anexos `E1`–`E5`.
- [x] As referências que **já** estavam correctas não são tocadas. Em `specs/EPIC-10` são 15, das quais duas sob `validacao/` («Natureza dos tickets» e o Registo de Hipóteses do KAM-100): essas 15 eram a prova, dentro do próprio ficheiro, de qual é a forma certa, e é por isso que este defeito nunca foi uma dúvida de convenção.
- [x] **O prefixo das três ocorrências em `specs/EPIC-01` não é corrigido** — e a formulação importa, porque duas dessas linhas *são* reescritas por este ticket, para passarem a remeter para o KAM-129 e o KAM-130: o que se preserva é o prefixo defeituoso, não a linha. As três estão no bloco do KAM-128: duas nomeiam o defeito (têm de citar a forma errada para a identificar) e uma descreve a convenção de irmão nu válida **dentro** de `docs/tecnica/`. A exclusão é explícita no *script*, não acidental, e repete a excepção que o KAM-111 e o KAM-128 já usam para as suas tabelas de correcção histórica.
- [x] O backlog fica sincronizado nos dois lados: linha em `specs/INDICE.md` §4 (sub-tabela do EPIC-01) e bloco `## KAM-129 — ` neste epic, com tipo, estimativa, prioridade, fase e dependências iguais; contagens de `specs/INDICE.md` §1 e §3.1 e de `README.md` actualizadas.
- [x] **O grafo de dependências fica recíproco**: `Dependências` e `Bloqueia` concordam nos dois sentidos para todos os tickets (busca G5). O conjunto mantém esta reciprocidade sem excepções, e a sincronia mestre↔epics **não a apanha**, porque compara apenas campos que a linha do §4 também tem — e o §4 não tem coluna `Bloqueia`. Um ticket novo que declare `Dependências | KAM-NNN` sem entrar no `Bloqueia` do KAM-NNN satisfaz o critério de sincronia pela razão errada; foi o que aconteceu na primeira versão deste ticket, e é por isso que G5 existe.
- [x] Cada documento formal tocado regista a emenda no seu «Controlo de versões» com referência a KAM-129.
- [x] Os defeitos de contagem herdados encontrados na mesma varredura **não** são corrigidos aqui: ficam no KAM-130, com a justificação da separação escrita nesse bloco.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#3`, fundido em `main` (`1401cd3`); o trabalho
está em `3c56c09` (correcção) e `4d84226` (emenda da revisão adversarial), sobre
`bebe2ae`. Medido a 2026-10-11 sobre `main`, por *script* no *scratchpad*. Cada
caixa marcada acima tem uma linha aqui; **as cinco não marcadas também**. Três
caixas foram desmarcadas depois da revisão adversarial registada em
`../docs/analises/ANALISE-04-encerramento-kam-001-128-129.md`: as contagens deste
ticket bateram todas na medição, mas dois dos seus critérios afirmam mais do que
os seus números medem, e é aí — não na aritmética — que a marcação enganava.

| CA | Estado | Evidência |
|---|---|---|
| G1 a zero | **parcial** | Busca G1 sobre `specs/*.md`, excluído `EPIC-01_Fundacoes_Dados.md`: **antes 59, agora 0**. A distribuição está confirmada pelas próprias linhas de «Controlo de versões» acrescentadas: 3 (EPIC-05), 4 (EPIC-06), 9 (EPIC-07), 13 (EPIC-08), 27 (EPIC-10), 3 (EPIC-11) = 59. Contado por ocorrência e não por linha (`grep -o` encadeado em `wc -l`, não `grep -c`), pela razão que o Contexto deste ticket nomeia. **Mas o título do critério é mais largo do que a busca que o operacionaliza, e por isso a caixa fica vazia.** G1 ancora no literal `evidencia/`, pelo que uma referência a anexo **sem directório nenhum** é-lhe invisível — e há **três** em `specs/EPIC-10_Spikes_Validacao_Gates.md:11`: `E2_Pagamentos_Angola.md`, `E3_Regulatorio_Dados.md` e `E4_Stack_Licencas.md`, nuas depois de uma quarta com o prefixo certo. Não resolvem de posição nenhuma, são pré-existentes (3 em `6d30625`, 3 hoje) e são uma **terceira** forma de citação que o ticket nunca classificou. «Zero referências a evidência sem directório qualificador em `specs/`» é falso à letra |
| 59 referências, forma inalterada: 25 / 15 / 18 / 1 | **satisfeito** | Classificadas a partir das linhas removidas por `3c56c09`: **25** com nome completo de anexo, **15** na forma-código (`E1`, `E2`, `E3` e `E4` — nunca `E5`), **18** de artefacto futuro e **1** referência nua ao directório, em `specs/EPIC-05` — total **59**, exactamente os números do CA. As linhas acrescentadas repetem a mesma classificação com o prefixo novo: 25 / 15 / 18 |
| *Diff* linha-por-linha: +57 −51 | **satisfeito** | `git diff --numstat 3c56c09^ 3c56c09` nos seis epics enumerados → `+57 −51`: 4/3, 5/4, 10/9, 10/9, 24/23, 4/3. Decomposição confirmada: **51 inserções contra 51 eliminações** de linhas de referência (líquido 0) mais **6** linhas de «Controlo de versões». As 59 referências em 51 linhas explicam-se por **7** linhas com mais do que uma referência, somando **8** excedentes — e a distribuição é a que o CA diz: quatro linhas de EPIC-08 com 2 cada, e EPIC-10 com 2, 3 e 2 |
| Classe A resolve em disco: 25 de 25 | **parcial** | As **25** com prefixo resolvem todas a partir de `specs/`: **0** que não resolvam. São **quatro** nomes distintos e não cinco — `E1_Meta_WhatsApp.md` (11), `E3_Regulatorio_Dados.md` (6), `E2_Pagamentos_Angola.md` (4), `E4_Stack_Licencas.md` (4); o `E5_Modulos_Entrada.md` tem **0**, porque as suas citações em `specs/EPIC-11` já estavam certas e nunca entraram nas 59. **A caixa fica vazia porque o critério diz «toda a referência de classe A»**, e a classe A está definida no Contexto como «anexo existente, `E1`–`E5`»: as três referências nuas da linha de G1 são referências a anexos existentes e **não** resolvem. O critério é verdadeiro para a população corrigida e falso para a que o seu texto nomeia. As da forma-código ficam fora do resolvedor, por desenho |
| Classe B declarada, nenhum ficheiro criado | **satisfeito** | Os alvos de classe B são **13** nomeados em **17** referências, mais **1** referência nua ao directório `validacao/` — 14 distintos, todos na tabela do Contexto, nenhum inventado. `docs/tecnica/evidencia/` tem exactamente os cinco anexos `E1`–`E5`; `validacao/` **não existe**; `git status --short` nessa pasta está limpo, sem ficheiros não rastreados |
| Referências já correctas não tocadas | **satisfeito** | Em `bebe2ae`, `specs/EPIC-10` tinha **15** referências já com o prefixo certo, **2** delas sob `validacao/` — os números do CA. Depois do ticket tem **43**, que é exactamente 15 + 27 corrigidas + 1 da linha de «Controlo de versões»: as 15 continuam lá, nenhuma reescrita |
| As três ocorrências de `specs/EPIC-01` preservadas | **satisfeito** | O bloco `## KAM-128` tem **3** ocorrências do prefixo defeituoso, as mesmas três: duas que nomeiam o defeito e uma que descreve a convenção de irmão nu válida dentro de `docs/tecnica/`. As outras 15 ocorrências do ficheiro estão no bloco `## KAM-129`, que tem de citar a forma errada para a identificar — 14 da redacção original e 1 acrescentada pela emenda da revisão adversarial, que precisa de nomear a âncora de G1; o bloco `## KAM-130` tem 0. A exclusão é de um só ficheiro, como os Testes Requeridos exigem |
| Backlog sincronizado | **satisfeito** | Linha do §4 com `fix`, `S`, `P1`, fase 0 e dependência `KAM-128` — igual ao bloco deste epic. Contagens actualizadas e coerentes entre si à data da medição (2026-10-11): `specs/INDICE.md` §1 «130 tickets atómicos (KAM-001 a KAM-130)», §3.1 com total **130** e EPIC-01 a **16** (`KAM-001 – KAM-012, KAM-111, KAM-128 – KAM-130`), `README.md` «Backlog mestre (130 tickets)» — e 130 era o número de blocos contados nos epics. **Remedição a 2026-10-12:** são **143** blocos e 143 linhas, com o §1 e o §3.1 a acompanhar; o `README.md` continua a dizer 130 e passou a divergir — defeito de contagem posterior a este ticket, da classe do KAM-130 |
| G5: grafo recíproco | **satisfeito à data, com regressão posterior registada** | *Parser* dos campos `Dependências` e `Bloqueia` dos **130** blocos dos 11 epics, a 2026-10-11: **0** falhas de reciprocidade nos dois sentidos e **0** blocos duplicados. A caixa fica marcada porque o critério é sobre o estado que este ticket entregou, e esse está medido. **Mas o invariante já não se verifica em `main`:** remedido a 2026-10-12 sobre 143 blocos, dá **8 falhas** — `KAM-131` a `KAM-138` declaram `Dependências \| KAM-002` e nenhum entra no `Bloqueia` do KAM-002. É exactamente o modo de falha que o texto deste critério previu («um ticket novo que declare `Dependências \| KAM-NNN` sem entrar no `Bloqueia` do KAM-NNN satisfaz o critério de sincronia pela razão errada»), e aconteceu porque o G5 continua a ser um teste requerido e não um gate: o **KAM-138** (gate 3c) está aberto e não implementado, pelo que nada em `tools/` verifica reciprocidade e o CI fica verde com as 8 falhas |
| Controlo de versões com KAM-129 | **satisfeito** | Os seis epics tocados têm a linha dentro da sua tabela de «Controlo de versões» (EPIC-05 L707, EPIC-06 L362, EPIC-07 L892, EPIC-08 L775, EPIC-10 L761, EPIC-11 L831, todas 5 linhas abaixo do cabeçalho da secção), e `specs/INDICE.md` regista a emenda na linha de versão 1.4. `specs/EPIC-01` regista-a na 1.2 |
| Contagens herdadas não corrigidas aqui | **satisfeito** | O bloco `## KAM-130` existe neste epic e escreve a justificação da separação — critério fechado do KAM-129, âmbito que passaria de `specs/` para `docs/`, e cada contagem a exigir decisão de canon própria; regista também que não há sobreposição de linhas entre os dois |
| DoD: todos os CA satisfeitos, evidência em `docs/evidencia/KAM-129.md` | **não satisfeito** | Dois CA em aberto depois da revisão (G1 à letra e a classe A), e o ficheiro de evidência que o DoD nomeia **não existe**: `docs/evidencia/` tem só `KAM-001-node.md` |
| DoD: ≥ 1 revisor e revisão da distinção A/B | **não satisfeito** | O PR #3 foi fundido com `reviewDecision: REVIEW_REQUIRED` e `reviews: []` — **zero** revisores humanos |
| DoD: documentação actualizada | **satisfeito** | `specs/INDICE.md` §1, §3.1, §4 e linha de versão; `README.md` a 130, que era o valor certo a 2026-10-11; «Controlo de versões» dos seis epics. *Conventional Commits*: `fix(KAM-129): corrige o prefixo das referencias aos anexos de evidencia` e `fix(KAM-129): emenda os achados da revisao adversarial` |
| DoD: sincronia mestre↔epics | **satisfeito** | A 2026-10-11, 130 linhas no mestre e 130 blocos únicos nos epics, **0** divergências de campo, segunda passagem com saída idêntica e `git status` vazio. **Remedido a 2026-10-12: 143 e 143, 0 divergências** — o invariante aguenta, ao contrário da reciprocidade do G5 |
| DoD: referências | **não satisfeito** | A segunda metade cumpre-se: varredura de identificadores de ticket, de ADR e de anexo sobre os 66 `.md` rastreados → **0** inválidos no âmbito deste ticket e **0** que tenham deixado de existir. (Fora do âmbito restam três grupos deliberados, nenhum deles uma referência: um identificador de ticket propositadamente inválido citado como critério de teste no bloco do KAM-002; dois números de ADR citados no `docs/adr/README.md` para dizer que não se usam; e três identificadores de nós de um diagrama Mermaid na biblioteca exploratória com a forma de um código de anexo.) **A primeira metade não se cumpre.** Resolvedor sobre os 15 `specs/*.md` rastreados, excluído `EPIC-01`, cada caminho `.md` em *code-span* resolvido relativo ao ficheiro **e** à raiz: **61 caminhos distintos, 68 ocorrências, não resolvem**. Desses, **15** são a lista declarada de classe B, **3** são as referências nuas da linha de G1, e os restantes **~43** são entregas futuras de outros tickets (`docs/gwy.md`, `ops/runbooks/RB-K01..RB-K10.md`, `docs/evidencia/KAM-016.md`, `Gate_Piloto_Decisao.md`, …) — categoria legítima e pré-existente que a redacção desta caixa **não** cobre, porque a única lista declarada do ticket é a de classe B, restrita a evidência. A caixa gémea do KAM-128 foi lida à letra e deixada aberta por menos do que isto; ler esta por aproximação seria aplicar duas réguas no mesmo ficheiro. Fica por marcar, e a decisão sobre a redacção volta a quem a escreveu |
| DoD: sem segredos | **satisfeito** | Não aplicável como o ticket declara, e verificado: os *commits* do ticket tocam apenas ficheiros `.md` em `specs/` |
| DoD: defeitos fora do âmbito em ticket próprio | **satisfeito** | KAM-130 aberto, com bloco neste epic e linha no backlog mestre |

> **O que isto custa, dito com clareza.** A aritmética deste ticket está certa:
> os números do CA (59, 25/15/18/1, +57 −51, 51/51, 8 excedentes, 15 e 2,
> 3 preservadas, 0 de reciprocidade) bateram todos na medição, sem arredondar
> nenhum, e foram reproduzidos por um revisor independente. Mas dois critérios
> afirmam mais do que os seus números medem — «zero referências sem qualificador»
> e «toda a referência de classe A» —, e as três referências nuas de
> `specs/EPIC-10:11` falsificam os dois. A primeira marcação deste bloco deu os
> números como prova do título; não eram. Falta ainda o ficheiro de evidência e a
> revisão humana.

### Detalhes Técnicos

- **Componentes:** transversal (documentação e backlog); sem código de *runtime*, sem migrações, sem dependências novas. Ficheiros: `specs/EPIC-05`, `specs/EPIC-06`, `specs/EPIC-07`, `specs/EPIC-08`, `specs/EPIC-10`, `specs/EPIC-11`, `specs/EPIC-01` (bloco do ticket), `specs/INDICE.md`, `README.md`.
- **Regra de posição (KAM-128).** A forma depende de onde está o ficheiro que refere: de `specs/` para `docs/` usa-se `../docs/…`. Daí `../docs/tecnica/evidencia/` e não `docs/tecnica/evidencia/`.
- **A substituição tem de ser ancorada.** O padrão exige que o caractere antes de `evidencia/` **não** seja `/` nem caractere de palavra de caminho (`[^/A-Za-z._-]`), ou reescreve as 168 referências que já estão certas e produz `../docs/tecnica/../docs/tecnica/evidencia/`. Uma substituição cega de `evidencia/` é o modo de falha deste ticket.
- **Fora de âmbito:** expandir a forma-código para nomes completos de ficheiro; criar o directório `validacao/` ou qualquer artefacto de classe B; as divergências de contagem herdadas (KAM-130); as referências a evidência feitas **de dentro** de `docs/tecnica/`, onde `evidencia/EN_*.md` é irmão nu e está correcto.
- **Questão aberta que este ticket não decide: a forma do caminho dentro dos blocos de *handoff*.** Um bloco de *handoff* fala a um executor cujo *cwd* é a raiz do repositório — diz «Lê specs/EPIC-10…», à raiz — mas cita os documentos de desenho como `../docs/tecnica/…`, à posição do ficheiro. Lido ao pé da letra pelo executor, `../docs/…` fica **acima** da raiz do repositório, e nas quatro instruções `Cria …/validacao/*.md` isso seria uma escrita fora da árvore, não uma leitura que falha. A regra do KAM-128 é de referência cruzada entre documentos e não resolve o caso. **A decisão fica em aberto e as quatro linhas seguem o padrão dominante**: dos 31 caminhos de evidência dentro de blocos de *handoff* nos seis epics, 27 já diziam `../docs/…` antes deste ticket, e reescrever só as quatro produziria uma segunda convenção dentro do mesmo bloco — pior do que o defeito. Decidir isto bem obriga a tratar as 31 de uma vez, em ticket próprio, e com o `cwd` do executor declarado nos padrões de `specs/01_Engineering_Standards_e_Handoff.md`.

### Testes Requeridos

- Verificação por máquina, não por leitura — corre antes e depois, e o resultado vai no PR. G1 e G3 excluem `EPIC-01_Fundacoes_Dados.md`, que cita necessariamente a forma errada e o modo de falha (`docs/docs/…`, `../docs/tecnica/../docs/tecnica/…`) para os nomear. A exclusão é de **um só** ficheiro, e é por isso que as linhas de «Controlo de versões» dos seis epics descrevem a correcção sem citar a forma antiga: uma busca de regressão que precisasse de excluir sete ficheiros não provaria nada.

```text
G1  grep -rnoE '(^|[^/A-Za-z._-])evidencia/' specs/*.md \
      --exclude=EPIC-01_Fundacoes_Dados.md                      # antes 59, alvo 0
G2  resolvedor: para cada '../docs/tecnica/evidencia/<nome>.md' em specs/*.md,
      verifica (dir(ficheiro) / caminho).exists(); falha se um nome completo de
      anexo nao resolver ou se um alvo fora da lista de classe B nao existir
G3  grep -rnoE '\.\./docs/tecnica/\.\./|docs/docs/' specs/*.md       --exclude=EPIC-01_Fundacoes_Dados.md                      # alvo 0
G4  ls docs/tecnica/evidencia/ -> exactamente E1..E5; git status --short sem
      ficheiros nao rastreados sob docs/tecnica/evidencia/
G5  reciprocidade do grafo: parser dos campos Dependencias/Bloqueia de todos os
      blocos ## KAM-NNN dos 11 epics; para cada 'A dep B' exige 'B bloqueia A' e
      vice-versa                                                     # alvo 0
```

- *Diff* linha-por-linha: os seis epics enumerados, **nunca** por *glob* (`specs/EPIC-0*.md specs/EPIC-1*.md` apanha EPIC-01 a 04 e 09 e devolve 287/53):

```text
git diff --numstat -- specs/EPIC-05_Pagamentos_Billing.md specs/EPIC-06_Indice_Pesquisa.md \n  specs/EPIC-07_Seguranca_Conformidade.md specs/EPIC-08_Topologia_Operacao.md \n  specs/EPIC-10_Spikes_Validacao_Gates.md specs/EPIC-11_Modulos_Entrada.md
# -> +57 -51, dos quais 51/51 de referencia (liquido 0) e 6 de Controlo de versoes
```
- Sincronia mestre↔epics em segunda passagem: 0 divergências.
- `make lint-arch` e a parte Python de `make check` (`lock-check`, `test-py`) verdes, antes e depois. Em Git Bash sem `make`: `PYTHONPATH=tools python -m lint_arch --root . all`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-129.md`).
- [ ] Revisto por ≥ 1 revisor; a distinção entre classe A e classe B revista também pelo Arquitecto de Plataforma, por ser onde um executor apressado criaria ficheiros a mais.
- [x] Documentação actualizada: `specs/INDICE.md` (§1, §3.1, §4, Controlo de versões), `README.md` e o «Controlo de versões» de cada epic tocado; Conventional Commits.
- [x] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e o bloco deste epic dizem o mesmo; segunda passagem de verificação dá 0 divergências.
- [ ] **Referências** — todo o caminho citado resolve ou consta da lista declarada de artefactos futuros; nenhum `KAM-NNN`, `ADR-NNN`, `D#`, `H#` ou `E#` citado deixou de existir.
- [x] **Sem segredos** — não aplicável: o ticket não acrescenta configuração nem dependências.
- [x] Defeitos encontrados fora do âmbito abertos como ticket `fix` próprio, não corrigidos aqui (`specs/01_Engineering_Standards_e_Handoff.md` §5) — feito: KAM-130.

### Handoff para Claude Code

```text
És o executor do ticket KAM-129 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-129, e o bloco KAM-128 para a convenção de caminhos).
Objectivo: as 59 referências a evidência de specs/ que não resolvem passam a ../docs/tecnica/evidencia/...
- Distingue ANTES de corrigir: E1..E5 existem em disco; os alvos validacao/* e Carga_Dimensionamento.md são
  saída de tickets de spike/gate e NÃO devem existir ainda. Em nenhum dos casos cries ficheiros ou directórios.
- Corrige só o prefixo. Mantém a forma: quem cita `evidencia/E3` §7 continua a citar o código, não o nome
  completo; quem cita o nome completo mantém-no. Expandir a forma-código está fora de âmbito.
- Ancora a substituição: o caractere antes de evidencia/ não pode ser / nem [A-Za-z._-], ou reescreves as 168
  referências já correctas e produzes ../docs/tecnica/../docs/tecnica/evidencia/.
- Exclui specs/EPIC-01_Fundacoes_Dados.md: as suas 3 ocorrências nomeiam o defeito ou descrevem o irmão nu
  válido dentro de docs/tecnica/. Não toques nas 2 referências já correctas de specs/EPIC-10.
- Actualiza os dois lados do backlog, as contagens (§1, §3.1, README) e o Controlo de versões de cada epic tocado.
Não expandas escopo: as divergências de contagem herdadas são o KAM-130.
Testes: G1 a G4 do bloco, antes e depois; git diff --numstat tem de dar 51/51 e 0 líquido; make lint-arch verde.
Abre PR com o template do §7.
```

---

## KAM-130 — Reconciliação das contagens e intervalos herdados no conjunto documental

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-128 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/00_Arquitectura_Solucao.md` (§8, §13.3), `../docs/tecnica/INDICE.md` (§5), `../docs/INDICE.md` (§2), `../docs/adr/ADR-L001-toolchain.md`, `specs/INDICE.md` (§1, §3.1, §4), `specs/00_KAMBA_Carta.md`, `specs/00_System_Spec.md`, `specs/01_Engineering_Standards_e_Handoff.md` |

### Contexto

O conjunto afirma em vários sítios **quantos** ADRs, decisões abertas, anexos de evidência, tickets e documentos activos existem. Essas contagens foram escritas em momentos diferentes e nunca foram reconciliadas: cada vez que o canon cresceu — ADR-019 e ADR-020, D13, o anexo E5, os tickets KAM-111 a KAM-117, KAM-128 e KAM-129 — ficaram atrás números que ninguém voltou a tocar. O resultado é um conjunto que se contradiz a si mesmo sobre factos triviais de verificar, e é a assinatura típica de alterações feitas a meio.

**O defeito é de contagem, não de resolução.** Nenhuma destas afirmações impede navegar o conjunto; todas enganam quem confia nelas em vez de contar. Por isso são `fix` de prioridade mais baixa do que o KAM-129, e por isso **não** entraram nele.

**Porque não entra no KAM-129.** O KAM-129 tem um critério fechado e verificável por uma só busca — «zero referências sem directório qualificador, 59 corrigidas, *diff* de 51/51 linhas». Juntar-lhe as contagens quebraria isso em três sentidos: o *diff* deixaria de ser linha-por-linha, o âmbito passaria de `specs/` para `docs/tecnica/`, `docs/adr/` e `docs/INDICE.md`, e — o que mais pesa — cada contagem exige **uma decisão de canon própria** (qual é a base de contagem?), enquanto o KAM-129 não decide nada, só reescreve prefixos. Foi também verificado que **não há sobreposição de linhas** entre os dois: nenhuma das linhas com contagem errada contém uma referência de caminho quebrada, pelo que separar não divide nenhuma edição a meio.

**Inventário do defeito** (varredura de 2026-10-11; a contagem de ocorrências confirma-se antes de corrigir, porque o conjunto continua a crescer):

| # | Afirmação errada | Onde | Canon | Fonte do canon |
|---|---|---|---|---|
| C1 | «12 ADRs», «18 ADRs», «19 ADRs» | `../docs/tecnica/INDICE.md` §5, `../docs/INDICE.md`, `specs/00_System_Spec.md`, os rodapés de `../docs/tecnica/04`, `07`, `09`, `10`, e `.claude/skills/agentic-engineering/references/revisao-adversarial.md` | **20** (ADR-001…ADR-020) | `../docs/tecnica/00_Arquitectura_Solucao.md` §8 |
| C2 | «D1–D12» | `specs/00_KAMBA_Carta.md` (2×), `specs/00_System_Spec.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/INDICE.md` §1, `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` | **D1–D13** | `../docs/tecnica/00_Arquitectura_Solucao.md` §13.3 |
| C3 | «E1–E4» | `specs/00_KAMBA_Carta.md`, `specs/EPIC-08` e `specs/EPIC-10` (legendas de abreviaturas), `../docs/tecnica/00` §16, `../docs/tecnica/07`, `../docs/tecnica/10` | **E1–E5** | `ls docs/tecnica/evidencia/` → cinco anexos |
| C4 | «126 tickets», «127 tickets» | `../docs/adr/ADR-L001-toolchain.md`, `../docs/PR-KAM-001.md`, e 6 ocorrências em `.claude/skills/agentic-engineering/` (`SKILL.md` ×2, `references/encerramento.md`, `references/evidencia-e-verificacao.md`, `references/revisao-adversarial.md` ×2) | a contagem vigente do `specs/INDICE.md` §4 | `specs/INDICE.md` §1, §3.1 |
| C5 | «14 documentos ativos» (§2) vs «13 documentos activos» (linha de versão 1.6) | `../docs/INDICE.md` | **uma** das duas, com a base de contagem escrita | o próprio §2 |
| C6 | tabela de versões fora de ordem cronológica (1.0, 1.2, 1.1, 1.3, …) | `specs/INDICE.md` §: Controlo de versões | ordem crescente | — |

**A *skill* conta como parte do conjunto, e é onde este defeito mais facilmente escapa.** `.claude/skills/agentic-engineering/` afirma contagens de canon (seis vezes «127 tickets», uma vez «12 ADRs») e o KAM-128 já a tratou como parte do conjunto documental, listando-a entre os ficheiros que tocou. Uma busca limitada a `docs/ specs/ README.md` **não a alcança** e devolveria zero com o defeito de pé — motivo por que as buscas H1 e H4 a incluem explicitamente. É o caso em que uma verificação verde prova apenas que se procurou no sítio errado.

**Duas armadilhas, que são a razão de este ticket não ser uma substituição cega.**

Primeira: **não toda a ocorrência de «N ADRs» é um defeito.** As três ocorrências de «10 ADRs» em `../docs/INDICE.md` descrevem o conteúdo do documento exploratório `11-arquitectura-detalhada-engenharia.md`, que de facto tinha dez ADRs próprios quando foi escrito. São descrição histórica correcta de um documento histórico, não contagem do canon, e **mantêm-se**. O mesmo vale para os pares «12 ADRs / 14 ADRs» nos rodapés, que têm de ser lidos no contexto antes de se decidir se contam o canon ou o documento.

Segunda: **C5 não é uma gralha, é uma base de contagem não declarada.** O §2 de `../docs/INDICE.md` conta 14 incluindo o documento mestre compilado (01–08, 10–14, mais o 00); a linha de versão conta 13 sem ele. Ambos os números são defensáveis — o defeito é o conjunto afirmar os dois sem dizer qual a base. A correcção é escolher uma base, escrevê-la e usá-la nos dois sítios, não alinhar os dígitos.

### Objectivo

Deixar o conjunto a afirmar um só número por grandeza, com a base de contagem explícita onde ela não é óbvia, e com as contagens de canon (ADRs, decisões abertas, anexos de evidência, tickets) a derivarem da fonte de verdade em vez de repetirem um valor antigo.

### Critérios de Aceitação

- [ ] **C1 — ADRs:** toda a afirmação que conta o **canon** diz 20; busca `grep -rnoE '\b(1[0-9]|20) ADRs?' docs/ specs/ .claude/skills/ README.md` revista ocorrência a ocorrência, com as que descrevem documentos exploratórios (as três de «10 ADRs» em `../docs/INDICE.md`) explicitamente mantidas e listadas no PR como excepção deliberada.
- [ ] **C2 — decisões abertas:** zero ocorrências de `D1–D12` como intervalo das decisões abertas; todas passam a `D1–D13`. Antes: 6 locais.
- [ ] **C3 — anexos de evidência:** zero ocorrências de `E1–E4` como intervalo dos anexos; todas passam a `E1–E5`. Antes: 7 locais, excluindo as citações dentro dos blocos KAM-128 e KAM-129 que nomeiam o defeito. As legendas de abreviaturas de `specs/EPIC-08` e `specs/EPIC-10` passam a cobrir E5.
- [ ] **C4 — tickets:** `../docs/adr/ADR-L001-toolchain.md` e `../docs/PR-KAM-001.md` deixam de dizer 126 e passam a dizer a contagem vigente do `specs/INDICE.md` §4, ou — preferível, e decidido no ticket — deixam de repetir o número e remetem para `specs/INDICE.md` §1, para não voltarem a envelhecer.
- [ ] **C5 — documentos activos:** `../docs/INDICE.md` afirma o mesmo número no §2 e na linha de versão, com a base de contagem escrita («inclui o 00 compilado» ou «exclui»); a grafia fica `activos`, na norma do conjunto (`specs/01_Engineering_Standards_e_Handoff.md` §5).
- [ ] **Nenhuma contagem nova nasce errada:** cada número alterado é derivado por busca ou por `ls` no momento da correcção, com o comando no PR, não copiado de outro documento.
- [ ] **Sem alteração de conteúdo técnico:** o *diff* toca só as linhas das contagens; nenhuma afirmação de desenho, estado de verificação ou decisão é reescrita.
- [ ] O backlog fica sincronizado nos dois lados: linha em `specs/INDICE.md` §4 (sub-tabela do EPIC-01) e bloco `## KAM-130 — ` neste epic, com tipo, estimativa, prioridade, fase e dependências iguais.
- [ ] Cada documento formal tocado regista a emenda no seu «Controlo de versões» com referência a KAM-130.

### Detalhes Técnicos

- **Componentes:** transversal (documentação); sem código de *runtime*, sem migrações, sem dependências novas. Ficheiros: `../docs/tecnica/INDICE.md`, `../docs/tecnica/00`, `04`, `07`, `09`, `10`, `../docs/INDICE.md`, `../docs/adr/ADR-L001-toolchain.md`, `../docs/PR-KAM-001.md`, `../docs/tecnica/evidencia/E5_Modulos_Entrada.md`, `specs/00_KAMBA_Carta.md`, `specs/00_System_Spec.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/INDICE.md`, `specs/EPIC-08`, `specs/EPIC-10`, `.claude/skills/agentic-engineering/**`.
- **Regra de derivação.** A contagem escreve-se a partir da fonte, não de outro documento: ADRs de `../docs/tecnica/00` §8, decisões de §13.3, anexos de `ls docs/tecnica/evidencia/`, tickets do `specs/INDICE.md` §4. Repetir um número lido num índice é como o defeito se propagou.
- **Preferir a remissão ao número.** Onde um documento não precisa do valor para se entender (o caso de `ADR-L001` e de `PR-KAM-001.md`), remeter para a fonte em vez de repetir o número elimina a classe de defeito em vez de a adiar. Registar essa escolha no ticket.
- **Fora de âmbito:** gerar as contagens automaticamente por *script* de CI — é trabalho do **KAM-138** (gate 3c, lint de coerência do backlog), não deste `fix`; verificou-se que nem o gate 3 de KAM-002 (que lê o §4 só para extrair identificadores) nem o lint de KAM-111 (nomes canónicos de dados, que declara «reconciliar os tickets» fora de âmbito) a cobrem, e foi essa lacuna que abriu o KAM-138; corrigir o conteúdo de qualquer documento exploratório; o prefixo das referências a evidência (KAM-129).

### Testes Requeridos

- Verificação por máquina, corrida antes e depois, com o resultado no PR:

```text
H1  grep -rnoE '\b(1[0-9]|20) ADRs?' docs/ specs/ .claude/skills/ README.md
      -> cada ocorrencia classificada: canon (tem de dizer 20) ou historica (mantem-se)
H2  grep -rnoE 'D1[^0-9A-Za-z]{0,4}(a|–|-)[^0-9A-Za-z]{0,4}D12' docs/ specs/   # alvo 0
H3  grep -rnoE 'E1[^0-9A-Za-z]{0,4}(a|–|-|ate)[^0-9A-Za-z]{0,4}E4' docs/ specs/ \
      --exclude=EPIC-01_Fundacoes_Dados.md                                     # alvo 0
H4  grep -rnoE '1[23][0-9] tickets' docs/ specs/ .claude/skills/ README.md
      -> 0 fora de specs/INDICE.md e README.md, ou todas iguais a contagem vigente
      (a skill diz 6x '127 tickets'; sem o .claude/skills/ a busca devolve 0 com o
       defeito de pe)
H5  grep -rnoE '1[0-9] documentos (activos|ativos)' docs/
      -> as duas ocorrencias de docs/INDICE.md dizem o mesmo numero e a grafia e 'activos'
H6  contagem derivada: ADRs de docs/tecnica/00 §8, D# de §13.3, anexos de
      ls docs/tecnica/evidencia/, tickets de specs/INDICE.md §4 -> conferem com o texto
```

- `make lint-arch` e a parte Python de `make check` verdes, antes e depois. Em Git Bash sem `make`: `PYTHONPATH=tools python -m lint_arch --root . all`.
- Segunda passagem de todas as buscas: 0 alterações. Uma verificação que muda algo na segunda passagem é uma edição, não uma verificação.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-130.md`).
- [ ] Revisto por ≥ 1 revisor; a classificação canon/histórica de C1 e a base de contagem de C5 revistas também pelo Arquitecto de Plataforma, por serem onde uma substituição cega estragaria texto correcto.
- [ ] Documentação actualizada: o «Controlo de versões» de cada documento tocado; Conventional Commits.
- [ ] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e o bloco deste epic dizem o mesmo; segunda passagem de verificação dá 0 divergências.
- [ ] **Referências** — nenhum `KAM-NNN`, `ADR-NNN`, `D#`, `H#` ou `E#` citado deixou de existir; nenhum caminho citado deixou de resolver.
- [ ] **Sem segredos** — não aplicável: o ticket não acrescenta configuração nem dependências.
- [ ] Defeitos encontrados fora do âmbito abertos como ticket `fix` próprio, não corrigidos aqui (`specs/01_Engineering_Standards_e_Handoff.md` §5).

### Handoff para Claude Code

```text
És o executor do ticket KAM-130 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-130) e a tabela de inventário C1..C5 do seu Contexto.
Objectivo: uma só contagem por grandeza, derivada da fonte, com a base de contagem escrita onde não é óbvia.
- Deriva cada número no momento: ADRs de docs/tecnica/00 §8 (são 20), decisões de §13.3 (D1-D13), anexos de
  ls docs/tecnica/evidencia/ (E1-E5), tickets de specs/INDICE.md §4. Não copies um número de outro índice.
- Inclui .claude/skills/agentic-engineering/ nas buscas: diz 6x «127 tickets» e 1x «12 ADRs», e uma
  busca limitada a docs/ specs/ README.md devolve 0 com o defeito de pé.
- NÃO substituas cegamente «N ADRs»: as três ocorrências de «10 ADRs» em docs/INDICE.md descrevem o documento
  exploratório 11 e estão CORRECTAS. Classifica cada ocorrência como canon ou histórica antes de tocar.
- C5 não é gralha: 14 conta com o mestre compilado, 13 sem ele. Escolhe uma base, escreve-a, usa-a nos dois
  sítios, e corrige a grafia para «activos».
- Onde o número não é preciso para entender o documento (ADR-L001, PR-KAM-001.md), remete para
  specs/INDICE.md §1 em vez de repetir o número — elimina a classe de defeito em vez de a adiar.
- Actualiza o Controlo de versões de cada documento tocado e os dois lados do backlog.
Não expandas escopo: o prefixo das referências a evidência é o KAM-129; automatizar as contagens em CI é KAM-002/KAM-111.
Testes: H1 a H6 do bloco, antes e depois, com segunda passagem a dar 0 alterações; make lint-arch verde.
Abre PR com o template do §7.
```

---

## KAM-131 — Gate 9 sobre a história do PR: varrimento dos *blobs* novos

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Segurança (dono do gate 9) com Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` (§3 gate 9, §7 lacuna 9), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` (§2 M8), `specs/01_Engineering_Standards_e_Handoff.md` §4, `../docs/tecnica/08_Seguranca_Conformidade.md` §4.8, ADR-008 |

### Contexto

O gate 9 do KAM-002 varre **a árvore seguida pelo git**, e não o que o PR acrescenta à história. Um segredo posto no *commit* A e retirado no *commit* B passa o gate — a árvore final já não o tem — e entra no `main` com o *merge*, porque o `main` recebe os dois *commits*. O segredo fica na história do repositório para sempre.

**É o cenário com que o próprio `../docs/ci.md` §3 justifica o *pre-commit*:** «um segredo que passa o pre-commit e chega ao servidor deixa de se remover apagando uma linha — fica na história, e a correcção passa a ser reescrever a história **e** rodar a chave». O gate que devia ser a segunda linha de defesa não vê exactamente o caso que a primeira linha existe para apanhar, e o *hook* de *pre-commit* é local: contorna-se com `--no-verify`, ou simplesmente não está instalado na máquina de quem abre o PR.

**O que pesa mais neste ticket do que nos outros seis desta série.** É o gate de segurança, e a falha é de alcance e não de forma: o *scanner* está correcto (`tools/scan_secrets/` detecta por forma, com o canário a prová-lo), o que falta é dar-lhe os objectos certos para ler. Registado como lacuna 9 em `../docs/ci.md` §7 e como M8 na revisão adversarial.

**Prioridade: há aqui uma decisão por tomar, e este ticket não a toma sozinho.** Pela legenda do `specs/INDICE.md` §4, P0 é «bloqueia o gate da fase» e P1 «necessário ao Piloto». Um varrimento de segredos incompleto **não** bloqueia o gate da Fase 0 (KAM-108: uma conversa real cria um pedido e o evento é consumido), pelo que P0 seria usar a legenda contra o que ela diz. Fica **P1** — antes do Piloto, que é quando entram credenciais reais de PMEs, da Meta e do facilitador — e a subida a P0 é **decisão do Responsável de Segurança com o Arquitecto de Plataforma**, registada aqui ou num ADR. A decisão é de prioridade, não de âmbito: o conteúdo do ticket não muda com ela.

### Objectivo

Fazer o gate 9 recusar um PR que introduza um segredo em qualquer *commit* do seu intervalo, mesmo que o segredo não exista na árvore final, mantendo o varrimento da árvore que já existe.

### Critérios de Aceitação

- [x] **As duas passagens correm, e nenhuma substitui a outra.** O gate 9 falha se encontrar um segredo (a) na árvore seguida pelo git — o comportamento actual, inalterado — **ou** (b) em qualquer *blob* que o PR acrescente à história.
- [x] **Demonstração do cenário A→B**, por execução e não por leitura: um ramo com dois *commits*, o primeiro a introduzir um segredo-canário num ficheiro e o segundo a removê-lo, faz o gate 9 **vermelho**. O mesmo ramo faz o gate verde hoje, e esse «antes» fica registado na evidência.
- [x] **O conjunto de *blobs* é o do intervalo do PR:** os objectos alcançáveis por `git rev-list <base>..<head>` e não pelo `main` inteiro. Um PR que não acrescenta *commits* não varre nada de novo; um PR de 40 *commits* varre os 40.
- [x] **O `base` chega ao gate sem o *workflow* o adivinhar.** O *job* passa o SHA de base explicitamente e o `actions/checkout` traz história suficiente para o resolver; um `fetch-depth` que não alcance a base faz o gate **falhar**, não passar em silêncio.
- [x] **Fail-closed quando não se consegue determinar o intervalo.** Sem `base` resolúvel — `push` directo no `main`, `workflow_dispatch`, repositório sem história — o gate diz qual o modo em que corre e **não** dá a passagem da história por satisfeita. A escolha entre falhar e varrer só a árvore está escrita no ticket, por modo de accionamento, e não deixada ao caso.
- [x] **As áreas permitidas de `ci/secrets-allow.yaml` aplicam-se à história com o caminho que o *blob* tinha nesse *commit*,** e não o que tem hoje: um segredo movido para fora da pasta do canário num *commit* intermédio é achado.
- [x] **O relatório continua a não revelar o valor** (quatro caracteres e comprimento, como hoje) e acrescenta o *commit* e o caminho onde o *blob* apareceu, para a correcção saber o que rodar.
- [x] **Um *blob* repetido varre-se uma vez.** A deduplicação é por SHA de objecto, para que um PR grande não pague o mesmo ficheiro várias vezes.
- [x] Tempo do gate 9 ≤ 60 s para um PR de até 100 *commits* (*proposta*, a calibrar com a primeira medição registada).
- [x] O *pre-commit* mantém-se como é: varre o que está em *stage*. Este ticket não lhe muda o âmbito.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `tools/scan_secrets/cli.py` (subcomando novo), `tools/scan_secrets/` (travessia de objectos), `.github/workflows/ci.yaml` (*job* do gate 9), `Makefile` (alvo `ci-9`), `ci/secrets-allow.yaml` (sem alteração de esquema esperada).
- **Forma do subcomando.** Hoje existem `tree`, `staged` e `files`. Acrescenta-se um quarto modo — `history --base <ref> --head <ref>` — e o `make ci-9` passa a correr `tree` **e** o modo novo quando o intervalo estiver definido. Dois subcomandos em vez de um `tree` que também olha para a história: o alcance de cada passagem fica legível no comando que a corre.
- **Travessia.** `git rev-list <base>..<head>` para os *commits*, e `git diff-tree -r --no-commit-id --diff-filter=d` (ou `git rev-list --objects`) para os *blobs* que cada um introduz; o conteúdo lê-se por `git cat-file`. Só a biblioteca padrão, pela mesma razão que o resto do `scan_secrets`: tem de poder correr antes de qualquer instalação (o *job* do gate 9 não instala dependências).
- **Plumbing no *workflow*.** Num `pull_request`, a base é `${{ github.event.pull_request.base.sha }}` e a cabeça o `HEAD` do *merge commit* de teste; o `actions/checkout@v5` precisa de história para os alcançar (`fetch-depth: 0`, ou uma profundidade justificada e verificada). **Uma base que não resolve é um gate vermelho** — o caso em que o CI não sabe o que varrer é o caso em que não pode dar passagem.
- **Decisão a registar no ticket, não aqui:** se um `push` no `main` varre `before..after` do evento, ou só a árvore. O `before` de um `push` pode ser `0000…` (ramo novo) e nesse caso não há intervalo; a regra tem de nomear os dois casos.
- **Fora de âmbito:** limpar segredos já na história (é resposta a incidente, KAM-113, e rotação de chaves, KAM-072); reescrever história; alterar o *scanner* por forma ou as suas classes; o *pre-commit*.

### Testes Requeridos

- Unit: travessia sobre um repositório temporário construído no teste — (a) segredo em A, removido em B: achado; (b) segredo só na árvore: achado pelas duas passagens, reportado uma vez; (c) *blob* repetido entre *commits*: varrido uma vez; (d) `base` inalcançável: erro, não passagem; (e) área permitida com o caminho do *commit* em que o *blob* apareceu.
- Integração: um PR de teste deliberadamente vermelho com o padrão A→B, no formato da demonstração do `../docs/ci.md` §8 — um PR, um bloqueio, com o *run* do GitHub Actions como evidência.
- Segurança: o canário continua a ser detectado pelas duas passagens e pelo *pre-commit*; o relatório de nenhuma delas imprime o valor (verificado por teste sobre a saída, não por inspecção).
- Medição: tempo do gate 9 antes e depois, no mesmo *commit*, com o número de *blobs* varridos ao lado.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `../docs/evidencia/KAM-131.md`, com o «antes» verde e o «depois» vermelho do mesmo ramo A→B).
- [ ] Código revisto por ≥ 2 revisores — altera um gate de segurança (`specs/01_Engineering_Standards_e_Handoff.md` §4, DoD do KAM-002); testes verdes.
- [x] Documentação actualizada: `../docs/ci.md` §3 (gate 9 passa a declarar as duas passagens) e §7 (lacuna 9 passa a fechada, com o ticket ao lado); Conventional Commits.
- [x] **Sem segredos** — o próprio repositório limpo nas duas passagens; autenticação por OIDC, sem chaves estáticas.
- [x] **Dependências** — nenhuma nova (só biblioteca padrão e `git`).
- [ ] A decisão de prioridade (P1 ou P0) fica registada com dono e data, e o `specs/INDICE.md` §4 e este bloco dizem o mesmo valor.
- [x] Nenhum gate marcado *skip* sem entrada em `ci/waivers.yaml`.

### Verificação dos Critérios de Aceitação

Uma linha por caixa: o que se mediu, com que comando, e o número que saiu.
**10 de 10** Critérios de Aceitação marcados e **5 de 7** caixas de DoD; as duas
vazias estão nomeadas no fim. Os *runs* do GitHub Actions estão em
[`../docs/evidencia/KAM-131.md`](../docs/evidencia/KAM-131.md).

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | As duas passagens correm | **satisfeito** | `make ci-9` tem duas receitas `@$(PYTHON) -c` — `tree` e `history` — e cada uma sai por `sys.exit`, pelo que uma falha reprova o alvo (`tools/lint_arch/tests/test_ci_gate9.py::TestAlvoCi9::test_nenhuma_passagem_substitui_a_outra`). No CI do PR #32: `limpo — 549 ficheiros seguidos pelo git` **e** `limpo — 36 blob(s) varrido(s) em 7 commit(s) do intervalo`. Um segredo na árvore é achado pelas duas e reportado uma vez por passagem (`test_o_segredo_na_arvore_e_achado_pelas_duas_passagens`). A revisão adversarial construiu **duas evasões** à passagem (b), por *evil merge*, e as duas estão fechadas com teste próprio: `test_evil_merge_que_poe_o_mesmo_blob_dentro_e_fora_da_area` e `test_blob_que_ja_estava_na_base_e_reposto_por_um_merge` ([`ANALISE-14`](../docs/analises/ANALISE-14-KAM-131-gate-9-na-historia.md) A1, A2) |
| 2 | Demonstração A→B por execução | **satisfeito** | Dois PRs de teste com o mesmo padrão (segredo-canário no *commit* A, removido no *commit* B). **Antes** (PR #33, sobre `main`): *gate* 9 **verde** em 8 s — `limpo — 541 ficheiros seguidos pelo git`, sem passagem da história. **Depois** (PR #34, sobre este ramo, reintegrado com o estado final): *gate* 9 **vermelho** em 11 s — a árvore `limpo — 546 ficheiros` e a história `1 achado(s) em 30 blob(s) varrido(s) em 9 commit(s)` |
| 3 | O conjunto é o do intervalo | **satisfeito** | `git rev-list --objects <base>..<head>`. Um segredo num *commit* anterior à base não é varrido: 1 *commit*, 1 *blob*, 0 achados (`test_o_que_e_anterior_a_base_nao_se_varre`). Um PR sem *commits* novos varre 0 *blobs* em 0 *commits* (`test_sem_commits_novos_nao_se_varre_nada`). Um intervalo de 40 *commits* dá 40 *commits* e 40 *blobs* (`test_quarenta_commits_varrem_os_quarenta`). No CI do PR #32, 36 *blobs* em 7 *commits* — e não os 549 ficheiros da árvore nem os 150 *commits* do repositório. Um *blob* que só o *merge* introduz também é varrido (`test_blob_que_so_o_merge_introduz_e_varrido`) |
| 4 | O `base` chega sem ser adivinhado | **satisfeito** | O *job* passa `GATE9_BASE: ${{ github.event.pull_request.base.sha \|\| github.event.before }}` e `fetch-depth: 0`; seis asserções em `test_ci_gate9.py::TestJobDoGate9`. Um `fetch-depth` que não alcance a base **falha**: base irresolúvel levanta erro com `fetch-depth` na mensagem (`test_base_que_nao_resolve_e_erro`), e um clone raso é recusado antes de varrer (`test_clone_raso_e_erro`). A CLI sai com **2**, não 0 (`test_base_irresoluvel_sai_dois`). As asserções prendem a **linha inteira** e não a expressão solta: a revisão trocou `GATE9_BASE` com `GATE9_HEAD` e as quatro asserções da primeira versão continuaram todas a bater, com o *gate* a varrer um intervalo invertido (`ANALISE-14` A3) |
| 5 | *Fail-closed* sem intervalo | **satisfeito** | A escolha está escrita por accionamento em `tools/scan_secrets/historia.py` (`SEM_INTERVALO`) e na tabela de `../docs/ci.md` §3: `pull_request`, `pull_request_target` e `merge_group` sem base são **vermelhos**; `push` com `before` a zeros, `workflow_dispatch`, `schedule` e a execução local correm em modo `so-arvore`. Onze testes em `TestModoDeAccionamento`, incluindo um que trava a tabela (`test_a_tabela_de_accionamentos_nao_cresce_sem_decisao`) e um accionamento não escrito a dar erro. No modo `so-arvore` a saída diz `passagem da historia NAO CORRIDA` com a razão (`test_modo_so_arvore_diz_que_a_passagem_nao_correu`) — não dá a passagem por satisfeita. O modo `push` com intervalo real foi corrido à mão sobre 48 *commits* deste repositório. Depois da revisão, o *fail-closed* ganhou três dentes que não tinha: um intervalo de **zero** *commits* num accionamento que decide um *merge* é erro (`exigir_commits`, `TestIntervaloVazio`, `test_intervalo_invertido_num_pull_request_sai_dois`); um *blob* que o `git cat-file` não devolva levanta erro; e o modo `so-arvore` imprime também um `::warning::`, para a linha chegar ao resumo do *job* (`ANALISE-14` A3, A4, A9) |
| 6 | Áreas com o caminho do *commit* | **satisfeito** | O conteúdo lê-se uma vez por SHA com as áreas desligadas, e as áreas aplicam-se depois a **todos** os caminhos do *blob*. O canário na sua pasta dá 0 achados (`test_na_pasta_do_canario_e_permitido`); o mesmo *blob* que entra na pasta no *commit* A e fora dela no *commit* B dá 1 *blob* varrido e achado **só** no caminho de fora (`test_movido_para_fora_da_pasta_do_canario_e_achado`), e o mesmo com o caminho de fora a ordenar **depois** do do canário (`test_movido_para_um_caminho_que_ordena_depois_do_canario`) — sem o segundo, uma implementação que confrontasse o **primeiro** caminho passava por acidente da ordem alfabética (`ANALISE-14` A6) |
| 7 | O relatório não revela o valor | **satisfeito** | Linha real do CI do PR #34: `671a4d1bf52e services/gwy/src/prova-kam-131.ts:4: possivel segredo (openai, classe chave_api): sk-p…U2 (56 caracteres)` + `blob 1518d44e71a1`. Quatro caracteres e comprimento, como na passagem da árvore, mais o *commit*, o caminho e o SHA do *blob*. Verificado sobre a saída e não por inspecção (`test_nao_revela_o_valor_e_diz_o_commit_e_o_caminho`, `test_segredo_no_intervalo_sai_um`). A revisão apanhou duas degradações do campo do *commit*, as duas fechadas: `(sem atrib` por truncatura de um valor que não é SHA (`test_um_commit_que_nao_e_sha_nao_se_trunca`) e a perda da atribuição numa mudança de nome (`test_uma_mudanca_de_nome_nao_perde_o_commit`). O relatório passou também a dizer o que **não** varreu, em contadores próprios (`ANALISE-14` A4, A6, A7) |
| 8 | *Blob* repetido varre-se uma vez | **satisfeito** | Dois *commits* com o mesmo conteúdo em caminhos diferentes: 2 *commits*, **1** *blob* lido, e `bytes_varridos` igual ao tamanho de um ficheiro (`test_blob_repetido_le_se_uma_vez`). A deduplicação é por SHA de objecto na leitura e no casamento dos padrões, **nunca** na aplicação das áreas — ver o critério 6 |
| 9 | Tempo ≤ 60 s para até 100 *commits* | **satisfeito** | PR de prova #35, com **108 *commits*** no intervalo e o estado final do código: o *job* inteiro do *gate* 9 em **13 s** (19:35:07 → 19:35:20), de que a árvore são 3,38 s (550 ficheiros) e a história **1,09 s** (136 *blobs*, 2 370 925 *bytes*). No PR #32 (7 *commits*, 36 *blobs*): 13 s. O limiar continua **proposta**: são medições no mesmo tipo de *runner*, e com folga de quase duas ordens de grandeza o número a vigiar é o dos *bytes* e não o dos *commits* |
| 10 | O *pre-commit* não muda | **satisfeito** | `git diff origin/main...HEAD -- tools/githooks/` é vazio; o subcomando `staged` não foi tocado; `../docs/ci.md` §3 diz por escrito que o âmbito do *hook* não muda |

**Definition of Done**

| # | Caixa | Estado |
|---|---|---|
| 1 | Todos os CA satisfeitos e demonstráveis | **marcada** — as dez caixas de Critérios de Aceitação estão marcadas com evidência nomeada, e o «antes» verde e o «depois» vermelho do mesmo padrão A→B estão em [`../docs/evidencia/KAM-131.md`](../docs/evidencia/KAM-131.md) |
| 2 | Código revisto por ≥ 2 revisores | **CAIXA VAZIA** — não há revisão humana imposta por máquina (`../docs/ci.md` §7, lacuna 16: o *ruleset* exige 0 aprovações, por decisão do fundador). A revisão adversarial de [`ANALISE-14`](../docs/analises/ANALISE-14-KAM-131-gate-9-na-historia.md) é evidência, **não é um revisor** — e este ticket altera um *gate* de segurança, que é precisamente o caso em que o DoD pede dois |
| 3 | Documentação actualizada | **marcada** — `../docs/ci.md` §2, §3 e §7 (lacuna 9 fechada), versão 1.15; Conventional Commits verificados pelo *hook* e pelo *gate* 2. **E a dívida que este ticket abriu, paga no mesmo ticket:** os cinco sítios de `../docs/seguranca/` que afirmavam «varre a árvore, não a história do PR» — a linha do *gate* 9 em `lacunas.md` §2, o RR-04 de `riscos_residuais.md`, a linha do *scanner* **e a célula REG-I** de `ameacas_stride.md`, e a linha `K-01` da matriz, regenerada por `gerar_matriz.py` — passam a declarar as duas passagens e os limites que ficam, e a linha 18 de `../docs/dividas-documentais.md` está riscada. O `validar.py` desses artefactos não ganhou erros: 5 antes e 5 depois, todos da linha 6 das dívidas |
| 4 | Sem segredos | **marcada**, com a precisão que a revisão obrigou a escrever — «as duas passagens» são as que o *gate* corre: a árvore e **o intervalo do PR**, e as duas correm limpas no CI do PR #32. A **história inteira** do repositório não está limpa: a revisão correu a passagem nova da raiz até à cabeça e achou cinco valores de classe `chave_api` em *commits* antigos — que é a tese deste ticket demonstrada sobre o próprio repositório. São valores do canário, **nunca emitidos por serviço nenhum**, pelo que não há chave para rodar; limpar a história é KAM-113 e KAM-072, fora do âmbito por escrito (`ANALISE-14` A11). O *job* não ganhou segredo nenhum e continua em OIDC (`grep` por referências ao cofre do GitHub no `ci.yaml` devolve 0, como no KAM-002) |
| 5 | Dependências — nenhuma nova | **marcada** — `historia.py` importa `dataclasses`, `re`, `subprocess` e `pathlib`; nada fora da biblioteca padrão, e `git` já era requisito do `tree` |
| 6 | Decisão de prioridade registada com dono e data | **CAIXA VAZIA** — a segunda metade cumpre-se (o `specs/INDICE.md` §4 e este bloco dizem **P1**), a primeira não: a decisão de subir a P0 é do **Responsável de Segurança com o Arquitecto de Plataforma** e **não foi tomada aqui**. Ver «Decisão devolvida» |
| 7 | Nenhum *gate* marcado *skip* | **marcada** — `ci/waivers.yaml` não foi alterado e nenhum *gate* foi marcado *skip*; o resumo `gates do KAM-002` continua a exigir `success` em 9 |

**Prova por mutação.** 24 mutações novas em `db/mutacoes.py`, prefixadas `KAM-131`,
**24 apanhadas em 24** (`python db/mutacoes.py python KAM-131`, com as duas linhas
de base verdes), corridas sobre o estado final — depois de integrar o KAM-136,
que reescreveu o leitor de YAML por onde o `scan_secrets` lê o
`ci/secrets-allow.yaml`. Catorze à travessia e à decisão de modo, cinco à CLI,
quatro ao *workflow* e uma ao `Makefile`. `python db/mutacoes.py --aplicaveis`
→ 138 mutações conferidas, 0 não aplicáveis. Dez delas vieram da revisão adversarial,
que mostrou que a lista anterior estava enviesada: a mutação das áreas estava
escrita na única direção em que o teste mordia (`ANALISE-14` A6). As mutações ao YAML e ao `Makefile` são
detectáveis porque este ticket acrescentou
`tools/lint_arch/tests/test_ci_gate9.py`: **não há *lint* de *workflows*** neste
repositório (`../docs/ci.md` §7, lacuna 15), e sem esse ficheiro uma mutação ao
*job* do *gate* 9 não seria apanhada por nada.

### Decisões tomadas neste ticket

1. **O conjunto de *blobs* sai de duas travessias, não de uma.**
   `git rev-list --objects base..head` é completo por definição mas não diz em que
   *commit* o *blob* entrou; `git log --raw` diz, mas não imprime sequer o
   cabeçalho de um *merge*. Usam-se as duas: a primeira garante que nada escapa
   (incluindo um *evil merge*), a segunda dá o *commit* e o caminho que o critério
   7 exige no relatório.
2. **Sem `-m` no `git log`.** Numa cabeça que é o *merge commit* de teste do PR, o
   *diff* contra cada pai arrastaria tudo o que o `main` ganhou desde a
   bifurcação — o `main` inteiro, que o critério 3 proíbe. O preço é um *merge*
   não atribuir *commit* a nada, e está pago pela travessia por objectos.
3. **A deduplicação por SHA aplica-se ao custo, não às áreas permitidas.** Lê-se e
   casam-se os padrões uma vez por objecto; as áreas aplicam-se a cada caminho em
   que o *blob* entrou. Deduplicar também as áreas daria verde pelo caminho mais
   conveniente, e era isso que o critério 6 ia buscar.
4. **A decisão por accionamento vive em Python, não em YAML.** Não há *lint* de
   *workflows*: uma condição escrita no *job* não seria verificável por teste
   nenhum. O *job* passa três valores em bruto e `decidir_intervalo` decide.
5. **A base vai como o evento a dá, e o erro é na direcção segura.** Se o `main`
   andou desde o evento, o intervalo pode incluir *commits* de `main` e o *gate*
   varre a mais — um falso vermelho, nunca uma passagem indevida. Preferiu-se isso
   a adivinhar a base, que o critério 4 proíbe. Está escrito em `../docs/ci.md` §3.
6. **Os dois PRs de prova foram criados pela API do GitHub e não localmente.** O
   *hook* de pre-commit recusa — com razão — um *commit* que contenha um segredo, e
   o cenário a demonstrar é precisamente o de quem abre o PR sem o *hook*
   instalado, que é o que o Contexto deste ticket nomeia. Não se usou
   `--no-verify`.

### Decisão devolvida

**A prioridade P1 → P0 não foi decidida aqui, e o ticket diz que não é de quem o
executa.** O bloco escreve-o: «a subida a P0 é **decisão do Responsável de
Segurança com o Arquitecto de Plataforma**, registada aqui ou num ADR». O
conteúdo entregue é o mesmo com qualquer das duas, e os dois lados do *backlog*
continuam a dizer **P1**. O que falta para a fechar: a decisão, com dono e data,
neste bloco ou num ADR, e a linha de `specs/INDICE.md` §4 a acompanhar.

### Handoff para Claude Code

```text
És o executor do ticket KAM-131 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-131), docs/ci.md §3 (gate 9) e §7 (lacuna 9), e
docs/analises/ANALISE-02-KAM-002-pipeline-ci.md §2 (M8). Objectivo: o gate 9 recusa um segredo introduzido em
qualquer commit do PR, mesmo que a árvore final já não o tenha.
- Acrescenta um modo `history --base <ref> --head <ref>` ao tools/scan_secrets, e MANTÉM o `tree`. As duas
  passagens correm; nenhuma substitui a outra.
- Blobs do intervalo: git rev-list base..head, conteúdo por git cat-file. Só biblioteca padrão — o job do
  gate 9 não instala dependências, pela mesma razão que o hook de pre-commit.
- Passa o base no workflow (github.event.pull_request.base.sha) e garante história suficiente no checkout.
  Base que não resolve é gate VERMELHO, não passagem silenciosa — fail-closed inclui não saber o que varrer.
- Decide e ESCREVE o comportamento por modo de accionamento (pull_request, push no main com before 0000...,
  workflow_dispatch). Não deixes o caso sem base ao critério do acaso.
- As áreas de ci/secrets-allow.yaml aplicam-se com o caminho que o blob tinha NO COMMIT, não o de hoje.
- Deduplica por SHA de objecto. O relatório nunca imprime o valor: quatro caracteres e comprimento, como hoje.
Não expandas escopo: não limpes segredos já na história (KAM-113 incidentes, KAM-072 rotação), não reescrevas
história, não toques no scanner por forma nem no pre-commit.
Testes: unit sobre repositório temporário (A→B, blob repetido, base inalcançável); 1 PR de teste vermelho com
o padrão A→B, no formato da demonstração do docs/ci.md §8; medição do tempo antes e depois.
Abre PR com o template do §7.
```

---

## KAM-132 — Cobertura Node sobre todo o TypeScript do âmbito (`--test-coverage-include`)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | M |
| Dependências | KAM-002 |
| Bloqueia | KAM-151 |
| Responsável sugerido | Engenheiro de Plataforma (dono do gate 4) |
| Documentos de referência | `../docs/ci.md` (§3 gate 4, §7 lacuna 10), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` §3, `specs/01_Engineering_Standards_e_Handoff.md` §4.1, `ci/thresholds.yaml` |

### Contexto

O gate 4 mede cobertura dos dois lados em LCOV. Do lado Python, `coverage run --source=.` mede **o que não é importado**: um módulo sem testes entra no denominador com 0% e faz o número descer. Do lado Node, `node --test --experimental-test-coverage` mede **só os ficheiros que os testes carregam** — pelo que **nenhuma** quantidade de TypeScript sem testes move a percentagem, porque o denominador não cresce com ela.

A consequência é precisa, e é pior do que parece: um serviço Node inteiro sem um único teste **não faz o gate 4 vermelho**. Mantém-no verde, porque não é medido. O limiar de 75% do §4.1 aplica-se a uma amostra que o próprio código escolhe — os ficheiros que alguém se lembrou de importar num teste.

**Porque não entrou no KAM-002.** `--test-coverage-include='src/**'` resolve-o, e **altera o valor medido**: o denominador passa a incluir ficheiros hoje invisíveis, e a percentagem do estrato `restante` desce por um valor que ninguém mediu ainda. Entra com medição própria e não de passagem — e muito provavelmente com **testes novos**, porque o estrato tem de ficar acima de 75% sem que o limiar seja baixado para o acomodar. É esse trabalho, e não a *flag*, que faz deste ticket um `M`.

**A assimetria entre os dois lados é o defeito, não a *flag* em falta.** Um gate que mede com régua diferente em cada ecossistema reporta um número que não significa a mesma coisa nas duas metades, e é o número agregado que o §4.1 compara com o limiar.

### Objectivo

Pôr o lado Node a medir o mesmo universo que o lado Python — todo o código do âmbito, carregado ou não — e deixar o estrato `restante` acima do limiar com testes, não com ajuste de limiar.

### Critérios de Aceitação

- [x] **Um ficheiro TypeScript sem nenhum teste entra na medição com 0%.** Verificado por execução: acrescentar um módulo de ~50 declarações sem teste faz a percentagem do estrato descer, e o valor da descida fica registado. Hoje não desce nada, e esse «antes» fica na evidência.
- [x] **O universo medido é o do `ci/thresholds.yaml`, e não uma segunda lista.** Os padrões `services/*/src/**`, `packages/*/src/**` e `libs/*/src/**` continuam a ser a fonte de quem está no âmbito; a *flag* do Node não introduz um critério de inclusão paralelo que possa divergir do ficheiro de limiares. Se a tradução entre os dois não for exacta, a diferença está escrita, com a razão.
- [x] **Os `excluidos` do `ci/thresholds.yaml` continuam a valer** (`**/tests/**`, `**/*.test.ts`, `services/*/src/server.ts`, `**/dist/**`): o que a *flag* acrescenta é denominador de código de execução, não de pontos de entrada nem de testes.
- [x] **O valor medido está registado antes e depois**, com o comando ao lado, no formato que o `../docs/ci.md` §8 usa: percentagem do estrato, linhas cobertas, total de linhas e número de ficheiros. Um número sem o comando que o reproduz não conta.
- [x] **O estrato `restante` fica ≥ 75% com testes novos, não com limiar novo.** Se a medição mostrar que 75% é inalcançável no estado actual do repositório, o ticket **não** baixa o limiar: regista o número medido, nomeia os ficheiros que faltam cobrir e leva a decisão ao dono do gate 4 — o limiar é *proposta* do §4.1 e altera-se por emenda registada, com os dois revisores que o DoD do KAM-002 exige para mexer em limiares.
- [ ] **A régua passa a ser a mesma nos dois lados**, e o `../docs/ci.md` §3 (gate 4) di-lo explicitamente, em vez de o leitor ter de inferir que «cobertura» significa duas coisas.
- [x] Um ficheiro medido que nenhum estrato classifica continua a **falhar** o gate, como hoje.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#41`, a partir de `main` (`dc243e0`). Medido a
2026-10-12. Não há `node` nem `make` na máquina de medição: os alvos correram em
`node:24.21.0-trixie-slim` com `make`, `python3`, `python3-venv` e `git`
instalados, sobre uma cópia da árvore de fontes no disco do contentor — o
comando é o mesmo, o que muda é onde o `make` corre. O detalhe com os comandos
está em [`../docs/evidencia/KAM-132.md`](../docs/evidencia/KAM-132.md). Cada
caixa marcada acima tem uma linha aqui; **as três não marcadas também**.

| CA | Estado | Evidência |
|---|---|---|
| Um `.ts` sem teste entra com 0% | **satisfeito** | Medido por execução, com os quatro números do mesmo conjunto de relatórios Python e só o lado Node remedido. Módulo de prova com **50 declarações exportadas em 355 linhas** em `packages/core-ts/src/` (estrato `restante`), que nenhum teste importa. Régua antiga (`--sem-universo`): sem o módulo **91%, 9418/10291 linhas, 99 ficheiros**; com o módulo **91%, 9418/10291, 99** — *byte a byte igual*, que é a medição do «hoje não desce nada» que o critério pede. Régua nova: sem o módulo **91%, 9418/10291, 99**; com o módulo **88%, 9418/10646, 100**. Desce **3 pontos**, o denominador cresce exactamente as 355 linhas do ficheiro, e o `make ci-4` nomeia-o. Reprodução: `make coverage-node && python tools/coverage_gate.py --root .` com e sem `--sem-universo` |
| Universo = `ci/thresholds.yaml`, não uma segunda lista | **satisfeito**, depois da revisão | O universo é computado por `coverage_gate.universo()` a partir dos `padroes` dos estratos menos os `excluidos` do mesmo ficheiro, e a procura começa nas **raízes dos próprios `padroes`**; não há segunda lista em sítio nenhum. A lista do `--test-coverage-exclude` do `make coverage-node` **também** vem dali (`coverage_gate.py --exclusoes-node <pacote>`), em **caminhos exactos e não *globs***, pelo que não há tradução entre o `fnmatch` do ficheiro de limiares e o *glob* do Node — a armadilha nomeada nos Detalhes Técnicos, medida a morder: `--test-coverage-include=./src/**` dá **zero** ficheiros. **A revisão adversarial encontrou aqui um critério de inclusão paralelo e não escrito**: `EXTENSOES_DO_UNIVERSO` só contava `.ts`, e um `fuga.mts` com 50 declarações sem teste deixava os três números iguais. Corrigido para as oito extensões que o Node 24 executa — nenhum ficheiro dessas extensões existe hoje no âmbito, pelo que nenhum número se moveu com a correcção. Imposto por máquina: `test_a_lista_vem_do_coverage_gate`, `test_a_flag_vai_para_o_node_test`, `test_as_outras_extensoes_do_node_nao_fogem`, e as mutações «a lista passa a ser escrita à mão no Makefile», «o `node --test` deixa de receber a lista» e «volta a deixar fugir tudo o que não seja `.ts`», todas apanhadas |
| Os `excluidos` continuam a valer | **satisfeito** | Passam a valer **duas** vezes: além de tirarem um ficheiro medido da avaliação, tiram-no da injecção e entram no `--test-coverage-exclude`. Medido: dos 13 excluídos da execução final, os quatro `services/*/src/server.ts` e `packages/core-ts/src/identity/contactos.ts` não aparecem no universo (`test_nao_tem_os_excluidos`), e `test_o_excluido_nao_e_injectado` prova que um ficheiro excluído de 999 linhas não entra no denominador. Mutações «o serviço de identidade deixa de estar excluído», «os pontos de entrada deixam de estar excluídos», «os `excluidos` deixam de valer na injecção» e «passa o âmbito em vez do que está excluído»: as quatro apanhadas |
| Valor registado antes e depois, com o comando | **satisfeito** | `make ci-4` completo nos dois estados, na mesma árvore e com as mesmas dependências. **Os números que contam são os do CI** (`docs/ci.md` §8), e são um par perfeito: o mesmo conjunto de oito relatórios LCOV do *run* 38304958677 sobre `73cb77d`, avaliado nas duas réguas. **Antes** (`--sem-universo`): `restante` 91% — 9652/10526 linhas, 100 ficheiros; `critico` 99% — 4802/4810, 26 ficheiros. **Depois** (o *gate*): `restante` 91% — 9652/10526, 100 ficheiros; `critico` 94% — 4802/5055, 29 ficheiros. **O `restante` é idêntico até à linha**, que é a prova mais directa de que nada lá estava invisível. E o par com `make ci-4` inteiro nos dois estados, que também exercita a cablagem do `Makefile`, está na evidência §4.2: `restante` 9323/10223 → 9418/10291 e `critico` 4802/4810 → 4802/5055 sobre a árvore anterior ao *merge* do KAM-131. Os quatro números por estrato, com o comando ao lado, em `../docs/evidencia/KAM-132.md` §4 e em `../docs/ci.md` §3 |
| `restante` ≥ 75% com testes, não com limiar novo | **satisfeito** | **91%**, com 16 pontos de margem, e o limiar de `ci/thresholds.yaml` **não foi tocado** (a mutação «o limiar do `restante` baixa de 75 para 50» é apanhada). **Zero testes novos foram necessários, e a medição é que o diz**: no `restante` não havia nada invisível — os seus 16 ficheiros TypeScript são todos carregados por algum teste, e os três que o lado Node nunca mediu caem todos no `critico`. O ticket esperava que o `restante` descesse «por um valor que ninguém mediu ainda»; o valor medido é **zero**. Leitura que se devolve ao dono do *gate* 4: a segunda metade da letra deste critério («com testes novos») ficou vacante por o problema não estar onde o ticket supunha, e não por se ter evitado trabalho |
| A régua é a mesma nos dois lados | **parcial** | **A assimetria que o ticket nomeia está fechada**, e o `../docs/ci.md` §3 di-lo numa tabela explícita: os dois lados medem agora o mesmo **universo** — todo o código do âmbito, carregado ou não. Duas desigualdades sobrevivem, e é por elas que a caixa fica vazia. (a) **A definição de «linha» continua diferente**: o `LF` do Node é o número de linhas do ficheiro, comentários e linhas vazias incluídos — `packages/core-ts/src/storage/motor.ts`, que é só tipos e comentários, sai `67/67` depois de ser carregado —, enquanto o `coverage.py` conta instruções. Igualar isto obriga a escolher uma das duas para os dois lados (lacuna 23). (b) **`services/agr/src/` não é medido por nenhum alvo**: os três ficheiros de `services/agr/src/kamba_agr/` estão no âmbito (`services/*/src/**`) e ficam fora do denominador, apesar de `services/agr/tests/` existir (lacuna 25). As duas estão registadas em `../docs/ci.md` §7 e a decisão fica com o dono do *gate* 4. **Leitura de 2026-10-12, à entrega deste ticket: a alínea (b) foi depois fechada pelo KAM-151**, que acrescentou o `--source=services/agr/src` ao `make coverage-python`; a alínea (a) continua aberta. A caixa fica vazia porque era o estado a esta data, e a avaliação não se reescreve para trás |
| Ficheiro medido sem estrato continua a falhar | **satisfeito**, depois da revisão | **A primeira versão regrediu aqui, e estava marcada como satisfeita pela razão errada.** Passar o âmbito em `--test-coverage-include` retirava do relatório o ficheiro que nenhum estrato classifica, pelo que ele deixava de chegar ao `avaliar()` e deixava de falhar; o que mantinha a caixa verde era `test_ficheiro_sem_estrato_falha`, que exercita `avaliar()` com um caminho `.py` sintético — o nível errado. Reproduzido pela revisão e confirmado por mim: `packages/core-ts/fora.ts` carregado por um teste, sem a *flag* dá «1 ficheiro(s) medidos e nao classificados» e com ela não dá nenhum. Corrigido: passa-se `--test-coverage-exclude` com o que está excluído, e nada filtra o que não está classificado. Regressão ao nível certo: `test_um_ts_medido_sem_estrato_falha_o_gate` (LCOV com o órfão → código 1, com o caminho impresso), `test_o_que_nenhum_estrato_classifica_nao_e_excluido` e `test_nao_passa_o_ambito_em_test_coverage_include`; mutação «volta a filtrar pelo âmbito em vez de excluir», apanhada. O universo lido do disco continua a **não** injectar um ficheiro sem estrato, de propósito: fabricar uma medição para o fazer falhar era o *gate* a criar o seu próprio achado (mutação «um ficheiro sem estrato passa a ser injectado», apanhada; `test_cada_um_esta_classificado` confere que os **32** ficheiros do universo real estão todos classificados) |
| DoD: todos os CA satisfeitos e demonstráveis | **não satisfeito** | Um CA em **parcial**: a régua não é a mesma nos dois lados em definição de linha nem em cablagem do lado Python (lacunas 23 e 25). Da cablagem encarregou-se depois o KAM-151 (lacuna 25 fechada); a definição de linha continua aberta |
| DoD: ≥ 1 revisor, 2 se o limiar for alterado; testes verdes | **não satisfeito** | Testes verdes: **225** em `tools/lint_arch` (0 falhas, 2 saltados por falta de `jsonschema` no *host*), `make ci-4` verde nos dois estados, e **24 mutações, 24 apanhadas, 0 sobreviventes** (`tools/lint_arch/tests/mutacoes.py`), mais «114 mutações conferidas, 0 não aplicáveis» em `db/mutacoes.py --aplicaveis`. **Revisores humanos: zero** — o *ruleset* de `main` exige 0 aprovações (lacuna 16 de `../docs/ci.md` §7). A revisão adversarial independente está em [`ANALISE-15`](../docs/analises/ANALISE-15-KAM-132-cobertura-de-todo-o-typescript.md) e **é evidência, não é um revisor**. O limiar **não** foi alterado, pelo que os dois revisores do DoD do KAM-002 não se aplicam |
| DoD: documentação e Conventional Commits | **satisfeito** | `../docs/ci.md` §3 com a tabela dos dois universos, o que as *flags* do Node fazem e não fazem, as raízes da procura e os números antes/depois; §7 com a lacuna 10 **fechada** (e com a correcção de que a cura que ela propunha não funcionava) e as lacunas 23, 24 e 25 novas; versão 1.17 na §9. `../docs/seguranca/lacunas.md` deixa de repetir a versão antiga do limite do *gate* 4. Evidência em `../docs/evidencia/KAM-132.md`; revisão em `../docs/analises/ANALISE-15-KAM-132-cobertura-de-todo-o-typescript.md`. Todos os *commits* em `tipo(KAM-132): …` |
| DoD: sem segredos | **satisfeito** | Não aplicável por natureza e verificado: o *diff* não acrescenta configuração nem credenciais, e `make ci-9` corre verde sobre o ramo |
| DoD: dependências — nenhuma nova | **satisfeito** | Nenhuma. `--test-coverage-include` é do Node 24, já fixado em `.node-version` (`24.21.0`); `os.walk` é da biblioteca padrão. `pnpm-lock.yaml` e os locks de Python não mudam |
| DoD: emenda ao limiar registada | **satisfeito** | Vacante: **o limiar não foi emendado**. `ci/thresholds.yaml` mantém 90/75; a única alteração é de comentário, a dizer que o ficheiro passou a decidir também **quem é medido** e não só com que limiar |

> **O que isto custa, dito com clareza.** O *gate* 4 passa a ver o código que
> não tem testes, e isso está provado por execução nas duas direcções: o módulo
> de 50 declarações que não movia nada move 3 pontos.
>
> **A primeira versão deste ticket não cumpria dois dos seus critérios**, e foi
> a revisão adversarial independente que o mostrou por execução
> ([`ANALISE-15`](../docs/analises/ANALISE-15-KAM-132-cobertura-de-todo-o-typescript.md)):
> três maiores — o CA7 regredido pela própria cura, três extensões de TypeScript
> a fugir, e o número do *gate* a depender de ficheiros que o `.gitignore`
> ignora —, nove menores e uma suspeita. Os três maiores, a suspeita e sete
> menores estão corrigidos, cada um com teste de regressão e mutação; as
> mutações passaram de 17 para 24.
>
> O que não se fez: os três ficheiros que entraram a 0% ficaram a 0% —
> cobri-los com um teste que só os importasse dava-lhes ~100% sem exercitar
> comportamento, porque o `LF` do Node conta `export { … }` e comentários como
> linhas atingidas. E a régua não ficou igual nas duas metades: falta a
> definição de «linha» e falta medir `services/agr/src/` — **esta segunda foi
> fechada pelo KAM-151, depois desta entrega; a primeira continua a faltar**.
> **E o estrato que
> este ticket aperta é o `critico`**, com ~250 linhas de folga sobre os 90%. As
> quatro coisas estão nomeadas, em `../docs/ci.md` §7 e no corpo do PR.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `Makefile` (`coverage-node`, `ci-4`), `tools/coverage_gate.py`, `ci/thresholds.yaml` (comentário, e limiar só se houver emenda registada), testes novos sob `services/*/src/` e `packages/*/src/`.
- **A *flag*.** `node --test --experimental-test-coverage --test-coverage-include=<padrão>`, no Node 24 que o `.node-version` fixa. O padrão tem de cobrir o mesmo que os `padroes` do estrato `restante`; confirmar a semântica de *glob* do Node contra a do `fnmatch` que o `tools/coverage_gate.py` usa — **são ferramentas diferentes a ler padrões parecidos**, e o `ci/thresholds.yaml` já tem um aviso escrito sobre uma armadilha desta classe (`*` atravessa barras no `fnmatch`, e `**/` exige um segmento pelo meio). Uma divergência aqui põe ficheiros fora da medição sem ninguém dar por isso, que é exactamente o defeito que este ticket fecha.
- **Ordem do trabalho:** medir primeiro com a *flag* e sem testes novos, registar o número, e só depois escrever testes. O número intermédio é o que diz quanto trabalho falta, e é ele que justifica a estimativa.
- **Fora de âmbito:** piso de cobertura por ficheiro (é a lacuna 7 de `../docs/ci.md` §7, decisão do canon sobre a granularidade do §4.1, e não deste ticket); o estrato `critico`, que está vazio até existir código de dinheiro, isolamento ou validador; alterar o limiar sem emenda registada.

### Testes Requeridos

- Unit: `tools/coverage_gate.py` sobre LCOV sintético que inclua ficheiros a 0% — o agregado do estrato desce, e um ficheiro sem estrato falha.
- Integração: `make ci-4` antes e depois, no mesmo *commit*, com os quatro números (percentagem, cobertas, total, ficheiros) e o comando ao lado.
- Regressão de desenho: um módulo novo sem teste faz o estrato descer de forma medível — o teste que prova que o denominador cresce, que é a propriedade em falta hoje.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-132.md`, com o «antes» e o «depois» do valor medido).
- [ ] Código revisto por ≥ 1 revisor, **2 se o limiar for alterado** (DoD do KAM-002); testes verdes.
- [x] Documentação actualizada: `../docs/ci.md` §3 (gate 4, a régua dos dois lados) e §7 (lacuna 10 fechada); Conventional Commits.
- [x] **Sem segredos** — não aplicável: não acrescenta configuração nem credenciais.
- [x] **Dependências** — nenhuma nova: a *flag* é do Node 24, já fixado.
- [x] Se o limiar do §4.1 for emendado, a emenda fica registada no `specs/01_Engineering_Standards_e_Handoff.md` §4.1 e em `ci/thresholds.yaml`, com dono e data — não só no código.

### Handoff para Claude Code

```text
És o executor do ticket KAM-132 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-132), docs/ci.md §3 (gate 4) e §7 (lacuna 10), e ci/thresholds.yaml.
Objectivo: o lado Node mede todo o TypeScript do âmbito, não só o que os testes carregam.
- MEDE PRIMEIRO. Acrescenta --test-coverage-include, corre make ci-4, e registra os quatro números
  (percentagem do estrato, linhas cobertas, total, ficheiros) com o comando ao lado. Só depois escreve testes.
- O universo medido vem dos `padroes` do estrato `restante` de ci/thresholds.yaml, não de uma segunda lista.
  Confirma a semântica de glob do Node contra o fnmatch do tools/coverage_gate.py: são leitores diferentes de
  padrões parecidos, e o próprio ci/thresholds.yaml tem um aviso escrito sobre uma armadilha desta classe.
- Os `excluidos` continuam a valer: testes, dist, node_modules, services/*/src/server.ts, **/__main__.py.
- Se 75% ficar inalcançável, NÃO baixes o limiar. Regista o número, nomeia os ficheiros a cobrir e leva a
  decisão ao dono do gate 4 — o limiar é proposta do §4.1 e muda por emenda registada, com dois revisores.
- Acrescenta um teste que prove que o denominador CRESCE: um módulo novo sem teste faz o estrato descer.
  É a propriedade que falta hoje, e é ela que este ticket entrega.
Não expandas escopo: sem piso por ficheiro (é a lacuna 7, decisão do canon), sem tocar no estrato `critico`
(está vazio até existir código de dinheiro/isolamento/validador).
Testes: unit do coverage_gate com LCOV sintético a 0%; make ci-4 antes e depois com os números no PR.
Abre PR com o template do §7.
```

---

## KAM-133 — SBOM por serviço a atravessar as dependências `link:` do *workspace*

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Segurança (dono do gate 11) com Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` (§3 gate 11 «SBOM por serviço» e «Fronteira com o KAM-067», §7 lacuna 11), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` §2 (M7), `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, ADR-014 |

### Contexto

O SBOM por serviço do gate 11 fecha-se por travessia do `pnpm-lock.yaml` a partir das dependências directas de cada importador. A travessia **não atravessa um `link:`**, que é a forma como o `pnpm` declara uma dependência de outro pacote do próprio *workspace*: o `services/gwy` declara `@kamba/core-ts`, os testes carregam-no, e ele não aparece no SBOM do `gwy` — que leva três componentes (o seu pacote, `hono` e `@hono/node-server`).

**O que isto custa hoje: pouco. O que custa no dia seguinte: a atribuição inteira.** No dia em que o `core-ts` tomar uma dependência de terceiros, ela não aparecerá no SBOM de nenhum dos quatro serviços que o carregam. O SBOM por serviço existe para responder «o que é que este serviço tem dentro», e é precisamente essa pergunta que passa a ter resposta errada.

**O veredicto de licenças e de vulnerabilidades não está afectado**, e vale dizê-lo para o ticket não ser lido como maior do que é: ambos correm sobre o fecho completo (`kamba.cdx.json`), que está correcto. O que falta é a **atribuição por serviço** — e é por isso que é `S` e P2, não P0.

**Fronteira com o KAM-067, que o `../docs/ci.md` §3 já fixa dimensão por dimensão.** Aqui: por **serviço**, a partir do código-fonte e dos *lockfiles*, em cada PR, falhando o gate 11. No KAM-067: por **imagem**, a partir das camadas, no *build* e no *release*, falhando os gates 14 e 18. O gerador é o mesmo e vive em `tools/sbom/`; este ticket corrige a travessia, e não duplica nada do KAM-067.

### Objectivo

Fazer o SBOM de cada serviço incluir os pacotes do *workspace* que ele carrega, e o fecho transitivo de terceiros que esses pacotes trazem, mantendo o determinismo que torna dois SBOM comparáveis.

### Critérios de Aceitação

- [ ] **`@kamba/core-ts` aparece no SBOM do `services/gwy`.** É o caso medido na revisão adversarial, e é o teste de aceitação mínimo. O mesmo vale para os outros serviços e os outros pacotes do *workspace* que declarem.
- [ ] **A travessia é transitiva.** Um terceiro declarado pelo `@kamba/core-ts` aparece no SBOM de cada serviço que carrega o `core-ts` — verificado com uma dependência acrescentada de propósito num teste, e não só por leitura do código.
- [ ] **Os pacotes do *workspace* continuam a ser reconhecidos como nossos** (`proprios` de `ci/licenses.yaml`) e não passam a terceiros sem licença determinada, o que faria o gate 11 vermelho pela política de `desconhecidas` e seria uma regressão disfarçada de correcção.
- [ ] **O SBOM continua determinista:** sem *timestamp*, chaves ordenadas; duas execuções no mesmo *commit* dão ficheiros idênticos (`diff` vazio). «Comparar é metade da utilidade de o ter» (`../docs/ci.md` §3).
- [ ] **Continua a ser um SBOM por serviço, e não nove cópias do fecho completo.** A contagem de componentes de cada serviço é a do seu fecho real: sobe face aos 3 de hoje, e **não** iguala os 91 da raiz. Os números de antes e depois, por serviço, ficam no PR.
- [ ] **Os SBOM continuam a validar contra o esquema CycloneDX 1.6** (uma cadeia fora da enumeração SPDX vai em `license.name`, como o M2 fixou), e os testes existentes sobre os SBOM reais continuam verdes.
- [ ] **Ciclos entre pacotes do *workspace* não penduram nem duplicam** a travessia: visitado é visitado, e há teste para isso.
- [ ] O fecho completo (`kamba.cdx.json`) e os veredictos de licenças e vulnerabilidades **não mudam** — eram já correctos. Se mudarem, a diferença está explicada no PR.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `tools/sbom/pnpm_lock.py` (travessia), `tools/sbom/collect.py`, `tools/sbom/cyclonedx.py` e `tools/sbom/spdx.py` se a relação precisar de ficar no documento, `tools/sbom/tests/`.
- **A forma do `link:`.** No `pnpm-lock.yaml`, a dependência de um pacote do *workspace* resolve-se como `link:../../packages/core-ts` (ou `workspace:*` no manifesto). A travessia actual pára aí porque o especificador não nomeia uma versão publicada; o que falta é mapear o caminho de volta ao importador correspondente do *lockfile* e continuar dali.
- **Relação no SBOM.** Decidir e escrever no ticket se o pacote do *workspace* entra como componente com `dependsOn` (mantendo a árvore legível) ou se só os seus terceiros são promovidos ao serviço. A primeira forma responde melhor à pergunta «o que é que este serviço tem dentro», mas é uma decisão de desenho do documento e tem de ficar registada, não implícita.
- **Lado Python.** Confirmar se o `kamba-core`/`kamba-agr` têm o equivalente (instalação editável) e se o mesmo defeito existe desse lado; se existir, entra aqui — é a mesma travessia e o mesmo gerador. Se não existir, fica escrito que não existe, e porquê.
- **Fora de âmbito:** SBOM por imagem, *digests*, `cosign`, quarentena e *egress* (KAM-067, gates 14 e 18); alterar a *allowlist* de licenças ou a política de `desconhecidas`; o varrimento de vulnerabilidades, que já corre sobre o fecho completo.

### Testes Requeridos

- Unit: travessia sobre um `pnpm-lock.yaml` de *fixture* com `link:` — (a) o pacote do *workspace* aparece; (b) um terceiro que ele declara aparece transitivamente; (c) um ciclo entre dois pacotes do *workspace* termina e não duplica.
- Integração: `python -m sbom --root ..` e `make ci-11` verdes; `diff` de duas execuções no mesmo *commit* vazio; contagem de componentes por serviço, antes e depois, no PR.
- Esquema: os testes de validação CycloneDX 1.6 sobre os SBOM reais continuam verdes (`tools/sbom/tests/test_spdx.py` e o teste do gate 11).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-133.md`, com a contagem por serviço antes e depois).
- [ ] Código revisto por ≥ 1 revisor; testes verdes.
- [ ] Documentação actualizada: `../docs/ci.md` §3 («SBOM por serviço» passa a descrever a travessia do `link:`) e §7 (lacuna 11 fechada); a tabela de fronteira com o KAM-067 revista e confirmada, não reescrita; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.
- [ ] **Dependências** — SBOM gerado; licenças permitidas; lista de bloqueio activa; nenhuma dependência nova no gerador.
- [ ] A decisão de desenho (componente com `dependsOn` vs promoção dos terceiros) fica escrita no ticket e no `../docs/ci.md`, com a razão.

### Handoff para Claude Code

```text
És o executor do ticket KAM-133 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-133), docs/ci.md §3 (gate 11: «SBOM por serviço» e «Fronteira
com o KAM-067») e §7 (lacuna 11), e docs/analises/ANALISE-02-KAM-002-pipeline-ci.md §2 (M7).
Objectivo: o SBOM de cada serviço inclui os pacotes do workspace que ele carrega, e os terceiros que eles trazem.
- Caso de aceitação mínimo, medido na revisão: @kamba/core-ts TEM de aparecer no SBOM do services/gwy.
- A travessia do pnpm-lock.yaml pára no `link:` porque o especificador não nomeia versão publicada. Mapeia o
  caminho de volta ao importador do lockfile e continua dali. Transitivo, e com visitado-é-visitado (há ciclos).
- Os pacotes do workspace continuam a ser `proprios` (ci/licenses.yaml). Se passarem a terceiros sem licença,
  o gate 11 fica vermelho pela política de `desconhecidas` — seria uma regressão disfarçada de correcção.
- DETERMINISMO: sem timestamp, chaves ordenadas, duas execuções no mesmo commit dão diff vazio. Não negociável.
- Continua a ser por serviço: a contagem sobe dos 3 actuais e NÃO iguala os 91 da raiz. Põe os números por
  serviço, antes e depois, no PR.
- Decide e ESCREVE no docs/ci.md se o pacote do workspace entra como componente com dependsOn ou se só os seus
  terceiros são promovidos. É decisão de desenho do documento, não detalhe de implementação.
- Confirma se o lado Python (kamba-core, kamba-agr, instalação editável) tem o mesmo defeito. Se não tiver,
  escreve que não tem e porquê.
Não expandas escopo: SBOM por imagem, digests, cosign, quarentena e egress são KAM-067 (gates 14 e 18); não
toques na allowlist de licenças nem no varrimento de vulnerabilidades, que já correm sobre o fecho completo.
Testes: fixture de pnpm-lock.yaml com link: (workspace, transitivo, ciclo); make ci-11 verde; diff de duas
execuções vazio; validação CycloneDX 1.6 sobre os SBOM reais.
Abre PR com o template do §7.
```

---

## KAM-134 — Chaves de `ci/*.yaml` que nenhum código lê, e recusa de chaves desconhecidas

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-002 |
| Bloqueia | KAM-135 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` (§7 lacuna 12), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` §3, `ci/thresholds.yaml`, `ci/licenses.yaml`, `ci/refs-allow.yaml`, `ci/waivers.yaml`, `specs/01_Engineering_Standards_e_Handoff.md` §4 |

### Contexto

Sete chaves dos ficheiros `ci/*.yaml` descrevem política que **nenhum código lê**:

| Chave | Ficheiro | O que promete | O que acontece |
|---|---|---|---|
| `arredondamento: truncar` | `ci/thresholds.yaml` | que a política de arredondamento é configurável | o gate trunca, por código; a chave não é lida |
| `desconhecidas.politica: falha` | `ci/licenses.yaml` | que se pode escolher falhar ou avisar | falha, por código; a chave não é lida |
| `expressoes.and` | `ci/licenses.yaml` | semântica de `A AND B` | implementada em código |
| `expressoes.or` | `ci/licenses.yaml` | semântica de `A OR B` | implementada em código |
| `expressoes.with` | `ci/licenses.yaml` | semântica de `A WITH excepção` | implementada em código |
| `serie_d.prazos_conhecidos` | `ci/refs-allow.yaml` | que a lista de prazos da série `D` é configurável | o gate 3 decide por intervalo canónico; a lista não é lida |
| `regra` | `ci/waivers.yaml` (exemplo comentado) | que um *waiver* de gate 11 se restringe a um veredicto | dispensa o alvo para **qualquer** veredicto |

**Porque é um defeito e não cosmética.** O objectivo do KAM-002 promete «limiares e excepções em ficheiros versionados». Um ficheiro que descreve regras que o código não lê é **pior** do que não as descrever: alguém vai editá-lo a pensar que alterou a política, vai ver o gate comportar-se como antes, e vai concluir que o gate está avariado. No caso do `regra`, a leitura errada é a mais perigosa das sete — quem escrever `regra: licenca` num *waiver* de gate 11 acredita que dispensou só a licença, e dispensou também a vulnerabilidade.

**Duas saídas por chave, e a escolha é por chave.** Ou o código passa a lê-la, ou ela passa a comentário — e um comentário diz o que o código faz, não o que se podia configurar. Nem todas merecem a mesma saída: `desconhecidas.politica` tem valor como interruptor declarado (há um caso legítimo em que se quer avisar em vez de falhar, com *waiver*), enquanto `expressoes.*` descreve semântica de SPDX que não é configuração de ninguém.

**A recusa de chaves desconhecidas fecha a classe inteira**, e é por isso que é o centro deste ticket e não um extra: enquanto um leitor aceitar em silêncio o que não conhece, uma chave nova mal escrita — ou uma gralha numa existente — volta a prometer política que não existe. É também a razão por que este ticket **bloqueia o KAM-135**: a parte «chaves desconhecidas em silêncio» do validador de *waivers* resolve-se com o mecanismo que aqui se escreve, e não com uma segunda implementação.

### Objectivo

Deixar cada chave dos `ci/*.yaml` ou lida pelo código ou declarada como comentário descritivo, e fazer qualquer leitor destes ficheiros **recusar** uma chave que não conheça.

### Critérios de Aceitação

- [ ] **As sete chaves estão resolvidas, uma a uma, com a escolha escrita.** Para cada uma: passou a ser lida (e há teste que prova que alterar o valor altera o comportamento do gate), ou passou a comentário (e não há mais nenhuma chave activa com esse nome). Nenhuma fica como está.
- [ ] **Nenhuma chave nova nasce não lida.** Toda a chave activa nos `ci/*.yaml` depois deste ticket tem um leitor, e um teste que falha se o leitor desaparecer.
- [ ] **Chave desconhecida é erro de configuração**, em todos os leitores de `ci/*.yaml` (`tools/coverage_gate.py`, `tools/ci_waivers.py`, `tools/ci_gate_reservado.py`, `tools/sbom/`, `tools/lint_refs/`, `tools/scan_secrets/`): o gate falha com o nome do ficheiro, a chave e o conjunto de chaves aceites. **Não avisa, não ignora** — é a mesma postura com que o `Permissoes.ler` do `ci/secrets-allow.yaml` já recusa uma classe inexistente (M4), e pela mesma razão: três áreas desse ficheiro declaravam classes que não existiam e por isso não permitiam nada, enquanto o ficheiro dizia o contrário.
- [ ] **A recusa distingue erro de configuração de achado.** Código de saída 2 (configuração), não 1 (achado), como o `tools/lint_arch` já faz: «um ficheiro de bloqueio malformado não pode parecer um repositório limpo».
- [ ] **Uma gralha numa chave existente é apanhada.** `padrões` por `padroes`, `permitidos` por `permitidas`: verificado por teste, por ser a forma mais provável de a classe reaparecer.
- [ ] **Se `regra` passar a ser lida, um *waiver* de gate 11 com `regra: licenca` deixa de dispensar a vulnerabilidade** — e há teste que o prova nas duas direcções. Se passar a comentário, o cabeçalho de `ci/waivers.yaml` diz explicitamente que um *waiver* de gate 11 dispensa o alvo para **qualquer** veredicto.
- [ ] **O `../docs/ci.md` e os cabeçalhos dos ficheiros dizem o mesmo que o código.** Nenhuma passagem descreve configuração que não existe depois deste ticket.
- [ ] Os gates continuam verdes com os ficheiros actuais: a recusa não introduz falha sobre configuração válida.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `ci/thresholds.yaml`, `ci/licenses.yaml`, `ci/refs-allow.yaml`, `ci/waivers.yaml`, `ci/secrets-allow.yaml` (verificar), e os leitores em `tools/`.
- **Mecanismo partilhado.** Uma função de validação de chaves, com o conjunto aceite declarado ao lado de cada leitor, em vez de seis implementações. É o que o KAM-135 vai consumir para a sua parte de chaves desconhecidas, e é a razão da dependência entre os dois.
- **Chaves aninhadas.** A validação tem de descer: `desconhecidas.politica` e `expressoes.and` são aninhadas, e um validador só do primeiro nível não as apanharia. O conjunto aceite é por nível.
- **Postura, e o que ela custa.** Recusar o desconhecido torna estes ficheiros mais rígidos de editar — é o preço de eles significarem o que dizem, e é a mesma troca que o `ci/secrets-allow.yaml` já fez. Está escrita aqui para não ser descoberta por quem acrescentar uma chave.
- **Fora de âmbito:** a semântica dos *waivers* (prazo contado da criação, `criado_em`, data de aprovação, `GATES_COM_WAIVER` sem os gates 14 e 18) é **KAM-135**; os erros de leitura do `tools/kamba_yaml.py` são **KAM-136**; alterar limiares, *allowlist* de licenças ou áreas de segredos.

### Testes Requeridos

- Unit, por leitor: (a) ficheiro válido actual passa; (b) chave desconhecida ao primeiro nível falha com código 2 e nomeia a chave; (c) chave desconhecida aninhada falha; (d) gralha numa chave existente falha; (e) para cada chave que passou a ser lida, dois valores diferentes produzem dois comportamentos diferentes.
- Integração: `make ci` verde com os ficheiros actuais; `make ci-waivers`, `make ci-4`, `make ci-11` e `make ci-3` falham com código 2 sobre uma *fixture* com chave inventada.
- Documental: nenhuma passagem de `../docs/ci.md` nem dos cabeçalhos dos `ci/*.yaml` descreve configuração inexistente — verificado chave a chave, com a lista no PR.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-134.md`, com a tabela das sete chaves e a saída escolhida para cada uma).
- [ ] Código revisto por ≥ 2 revisores — toca em limiares e regras de bloqueio (DoD do KAM-002); testes verdes.
- [ ] Documentação actualizada: `../docs/ci.md` §7 (lacuna 12 fechada) e os cabeçalhos de cada `ci/*.yaml` tocado; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.
- [ ] **Dependências** — nenhuma nova.
- [ ] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e este bloco dizem o mesmo, incluindo o `Bloqueia KAM-135`.
- [ ] Nenhum gate marcado *skip* sem entrada em `ci/waivers.yaml`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-134 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-134) e docs/ci.md §7 (lacuna 12). Objectivo: cada chave dos
ci/*.yaml ou é lida pelo código, ou é comentário; e um leitor recusa o que não conhece.
- As sete chaves estão na tabela do Contexto: arredondamento, desconhecidas.politica, expressoes.and/or/with,
  serie_d.prazos_conhecidos, regra. Resolve UMA A UMA e escreve a escolha. Nenhuma fica como está.
- O centro do ticket é a RECUSA de chaves desconhecidas em todos os leitores de ci/*.yaml. Enquanto um leitor
  aceitar em silêncio o que não conhece, a classe reabre com a próxima gralha.
- Código de saída 2 (configuração), não 1 (achado): um ficheiro malformado não pode parecer repositório limpo.
  É a mesma postura do Permissoes.ler do ci/secrets-allow.yaml, que recusa uma classe inexistente (M4).
- A validação DESCE: desconhecidas.politica e expressoes.and são aninhadas. Conjunto aceite por nível.
- Escreve UM mecanismo partilhado, não seis. O KAM-135 vai consumi-lo para a sua parte de chaves desconhecidas.
- O `regra` é a mais perigosa das sete: quem escreve `regra: licenca` num waiver de gate 11 acredita que
  dispensou só a licença, e dispensou também a vulnerabilidade. Se a tornares lida, testa nas duas direcções;
  se passar a comentário, diz no cabeçalho que um waiver de gate 11 dispensa o alvo para qualquer veredicto.
- Testa a gralha: `padrões` por `padroes`, `permitidos` por `permitidas`.
Não expandas escopo: a semântica dos waivers (criado_em, prazo da criação, data de aprovação, gates 14 e 18)
é o KAM-135; os erros de leitura do tools/kamba_yaml.py são o KAM-136. Não alteres limiares nem allowlists.
Testes: por leitor (válido passa, desconhecida falha com código 2, aninhada falha, gralha falha, e para cada
chave que passou a ser lida dois valores dão dois comportamentos); make ci verde com os ficheiros actuais.
Abre PR com o template do §7.
```

---

## KAM-135 — Validador de *waivers*: `criado_em`, data de aprovação verificada e gates 14 e 18

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-002, KAM-134 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma com Responsável de Segurança |
| Documentos de referência | `../docs/ci.md` (§5 excepções, §7 lacuna 13), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` §3, `ci/waivers.yaml`, `tools/ci_waivers.py`, `specs/01_Engineering_Standards_e_Handoff.md` §4 |

### Contexto

`ci/waivers.yaml` é **o** mecanismo de excepção do pipeline: o KAM-067 e o KAM-078 consomem este esquema em vez de inventarem o seu, e a regra transversal do §4 do Engineering Standards diz que «nenhum gate pode ser marcado *skip* sem ADR ou aprovação registada». O validador aceita quatro coisas que não devia:

1. **Data de aprovação impossível.** `adr_ou_aprovacao: aprovacao:alguem@9999-99-99` passa. O campo é obrigatório e a sua presença é verificada; o seu **conteúdo** não. Uma aprovação com data inventada satisfaz a exigência de «aprovação registada» sem registar nada.
2. **O prazo conta-se de hoje, não da criação.** Não há campo `criado_em`, pelo que `expira_em ≤ 30 dias` é sempre medido contra a data em que o gate corre. Consequência: **um *waiver* renova-se para sempre com um *diff* de um caractere** — basta empurrar `expira_em` trinta dias para a frente, e a excepção que devia caducar nunca caduca. É o inverso exacto da propriedade que o §5 diz entregar: «a alternativa é uma excepção que fica para sempre porque ninguém reparou que caducou».
3. **Chaves desconhecidas em silêncio.** Um campo mal escrito — `expira`, `aprovacao`, `razão` — é ignorado, e o *waiver* passa a valer sem o campo que o autor acreditava ter escrito.
4. **`GATES_COM_WAIVER` não inclui os gates 14 e 18.** É `{3, 4, 5, 6, 7, 8, 9, 11}`. O §5 diz que o KAM-067 e o KAM-078 consomem este esquema, e os gates desses tickets são o 14 (imagem) e o 18 (*release* sem SBOM), pela tabela de fronteira do §3. Hoje um *waiver* para o gate 14 é **recusado** pelo validador que o devia aceitar — pelo que o KAM-067 vai encontrar o mecanismo fechado e a tentação de inventar o seu, que é precisamente o que o §5 existe para evitar.

Os quatro são de alcance diferente, e o segundo é o que importa: **os outros três deixam passar um *waiver* malformado; esse deixa passar um *waiver* eterno.**

### Objectivo

Fazer o validador de *waivers* recusar uma excepção malformada, impedir que uma excepção se renove indefinidamente sem decisão nova, e aceitar os gates que o canon diz que consomem este esquema.

### Critérios de Aceitação

- [ ] **`criado_em` é campo obrigatório**, data ISO, e o prazo mede-se **dele**: `expira_em − criado_em ≤ 30 dias` (*proposta* do KAM-002, mantida). Um *waiver* existente sem `criado_em` faz o `make ci-waivers` falhar com a mensagem que diz o que acrescentar.
- [ ] **Renovar deixa de ser um *diff* de um caractere.** Empurrar o `expira_em` sem mexer no `criado_em` **falha**; prolongar a excepção exige alterar `criado_em`, `adr_ou_aprovacao` e `autor` — ou seja, uma decisão nova com dono novo, que se lê no *diff*. Verificado por teste, nas duas direcções.
- [ ] **A data dentro de `adr_ou_aprovacao` é validada.** `aprovacao:<quem>@<data>` exige uma data ISO real e não futura; `9999-99-99` falha, e a mensagem diz porquê. A forma `ADR-NNN`/`ADR-LNNN` continua a ser verificada contra o conjunto canónico, como o gate 3 já faz.
- [ ] **Chave desconhecida num *waiver* é erro de configuração**, com código de saída 2, usando o mecanismo partilhado do **KAM-134** e não uma segunda implementação. A mensagem nomeia a chave e o conjunto aceite.
- [ ] **`GATES_COM_WAIVER` inclui 14 e 18**, e a razão fica escrita ao lado do conjunto: são os gates que o KAM-067 e o KAM-078 consomem (§5, e a tabela de fronteira do §3). Os gates 1 e 2 continuam a **não** aceitar *waiver* — «um *build* que não compila corrige-se» — e há teste para isso.
- [ ] **O conjunto de gates deixa de poder divergir do canon em silêncio.** Um gate que o `specs/01_Engineering_Standards_e_Handoff.md` §4 nomeia e que o conjunto não inclui é um defeito visível: ou o validador o aceita, ou diz explicitamente porque não. A escolha fica escrita, gate a gate.
- [ ] **Um *waiver* expirado continua a falhar o pipeline** — não avisa, não ignora. O comportamento actual mantém-se.
- [ ] O `ci/waivers.yaml` continua sem excepções activas, e o exemplo comentado passa a mostrar a forma nova (com `criado_em`).
- [ ] O cabeçalho de `ci/waivers.yaml` e o `../docs/ci.md` §5 descrevem os campos obrigatórios tal como o código os exige, incluindo `criado_em` na tabela.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `tools/ci_waivers.py` (`_CAMPOS`, `GATES_COM_WAIVER`, validação de datas), `ci/waivers.yaml` (cabeçalho e exemplo), `tools/lint_arch/tests/test_ci_waivers.py`, `tools/ci_gate_reservado.py` (consome os *waivers* dos gates reservados).
- **Dependência do KAM-134, e o que ela significa na prática:** a parte 3 (chaves desconhecidas) **não** se implementa aqui. Este ticket consome o validador de chaves que o KAM-134 escreve e acrescenta-lhe o conjunto aceite dos *waivers*. Implementá-la duas vezes é o defeito que a dependência existe para evitar.
- **`criado_em` em *waivers* existentes.** Hoje são zero (`waivers: []`), pelo que não há migração a fazer — e vale registá-lo, porque o mesmo ticket feito seis meses mais tarde teria de a fazer.
- **Prazo de 30 dias.** Continua a ser *proposta* do KAM-002. Este ticket não o altera: muda **a partir de quando** se conta, que é o defeito.
- **Fora de âmbito:** a chave `regra` e a recusa genérica de chaves desconhecidas (**KAM-134**); implementar os gates 14 e 18 (KAM-067, KAM-078) — aqui só se abre o esquema a eles; alterar o limite de 30 dias; os erros de leitura do `tools/kamba_yaml.py` (**KAM-136**).

### Testes Requeridos

- Unit: (a) *waiver* sem `criado_em` falha; (b) `expira_em − criado_em` de 31 dias falha, de 30 passa; (c) `expira_em` empurrado sem mexer em `criado_em` falha; (d) `aprovacao:x@9999-99-99` falha, `aprovacao:x@2026-10-01` passa, data futura falha; (e) um `ADR-NNN` fora do conjunto canónico falha; (f) chave desconhecida falha com código 2; (g) gate 14 e gate 18 aceitos; (h) gates 1 e 2 recusados; (i) *waiver* expirado falha.
- Integração: `make ci-waivers` verde com o `ci/waivers.yaml` actual; vermelho sobre uma *fixture* por cada um dos nove casos acima.
- Regressão: um *waiver* de gate reservado com `alvo: pipeline` continua a dispensar, e com outro alvo continua a não dispensar (correcção já feita no KAM-002, que este ticket não pode desfazer).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-135.md`).
- [ ] Código revisto por ≥ 2 revisores — altera o mecanismo de excepção dos gates (DoD do KAM-002); testes verdes.
- [ ] Documentação actualizada: `../docs/ci.md` §5 (tabela de campos com `criado_em`, e os gates que aceitam *waiver*) e §7 (lacuna 13 fechada); cabeçalho de `ci/waivers.yaml`; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.
- [ ] **Dependências** — nenhuma nova; o validador de chaves vem do KAM-134.
- [ ] **Referências** — os gates nomeados existem no `specs/01_Engineering_Standards_e_Handoff.md` §4; os ADRs citados em *fixtures* de teste estão declarados em `ci/refs-allow.yaml` se forem deliberadamente inválidos.
- [ ] Nenhum gate marcado *skip* sem entrada em `ci/waivers.yaml`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-135 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-135), docs/ci.md §5 e §7 (lacuna 13), e tools/ci_waivers.py.
Objectivo: um waiver malformado é recusado, e uma excepção não se renova para sempre sem decisão nova.
- O DEFEITO QUE MAIS PESA é o prazo contado de hoje. Acrescenta `criado_em` obrigatório e mede
  expira_em - criado_em <= 30 dias. Hoje empurrar o expira_em trinta dias à frente renova o waiver com um diff
  de um caractere, e a excepção que devia caducar nunca caduca.
- Valida a data DENTRO de adr_ou_aprovacao: `aprovacao:<quem>@<data>` exige data ISO real e não futura.
  Hoje `@9999-99-99` passa, e uma aprovação com data inventada satisfaz «aprovação registada» sem registar nada.
- Acrescenta 14 e 18 a GATES_COM_WAIVER, com a razão ao lado: são os gates do KAM-067 e do KAM-078, que a §5
  diz que consomem este esquema. Hoje um waiver de gate 14 é recusado pelo validador que o devia aceitar.
  Os gates 1 e 2 continuam a NÃO aceitar waiver — um build que não compila corrige-se.
- Chaves desconhecidas: CONSOME o mecanismo do KAM-134, não escrevas um segundo. É a razão da dependência.
- Não alteres o limite de 30 dias (é proposta do KAM-002): muda só a partir de quando se conta.
- Há zero waivers activos hoje (waivers: []), pelo que não há migração. Registra isso — o mesmo ticket seis
  meses mais tarde teria de a fazer.
- Actualiza o exemplo comentado de ci/waivers.yaml e a tabela de campos do docs/ci.md §5 com o criado_em.
Não expandas escopo: a chave `regra` e a recusa genérica de chaves desconhecidas são KAM-134; implementar os
gates 14 e 18 é KAM-067/KAM-078 (aqui só se abre o esquema a eles); kamba_yaml é KAM-136.
Testes: os nove casos do bloco, um por fixture; make ci-waivers verde com o ficheiro actual; e a regressão do
`alvo: pipeline` nos gates reservados, que o KAM-002 corrigiu e este ticket não pode desfazer.
Abre PR com o template do §7.
```

---

## KAM-136 — Dois erros de leitura silenciosos do `tools/kamba_yaml.py`

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` (§7 lacuna 14), `../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md` §3, `tools/kamba_yaml.py`, `tools/lint_arch/tests/test_kamba_yaml.py` |

### Contexto

O `tools/kamba_yaml.py` é o leitor de YAML de todos os ficheiros `ci/*.yaml`, escrito sem dependências porque os gates 9 e 4 têm de poder correr antes de qualquer instalação. O módulo argumenta — e é a razão de existir — que **a recusa larga é o que o torna confiável**: o que não entende, recusa. Dois casos fazem o contrário disso e **lêem mal em silêncio**:

1. **`>-` como primeira chave de um item de lista engole as chaves seguintes.** Um item que comece por um escalar em bloco (`razao: >-`, a forma que todos os ficheiros `ci/*.yaml` usam para texto longo) absorve as linhas seguintes como continuação do texto, incluindo as que são chaves do mesmo item. O item resulta com uma chave e um `razao` longo; as outras chaves desaparecem — sem erro.
2. **Item de lista não citado que contenha `:` torna-se um mapa.** Um item de lista de cadeias que inclua `:` é lido como um mapa de uma chave em vez de uma cadeia.

**O que ambos têm em comum, e porque são um ticket e não dois.** Nenhum dos dois **falha**: os dois devolvem uma estrutura plausível e errada. Num leitor cuja premissa é «recusa o que não entendes», é o modo de falha mais caro que existe, porque não há sintoma. E o que estes ficheiros descrevem são **limiares, excepções e áreas permitidas** — uma chave engolida é um campo obrigatório de *waiver* que desaparece, uma área de segredos que não se aplica, um estrato de cobertura sem padrões.

**A correcção certa pode ser recusar, não interpretar.** Para um leitor com esta premissa, falhar com «escalar em bloco não suportado nesta posição» é melhor resultado do que adivinhar a intenção — e muito mais barato de verificar. A escolha, caso a caso, é parte do ticket.

### Objectivo

Deixar o `tools/kamba_yaml.py` sem nenhum caso em que lê mal sem o dizer: cada construção que ele não interpreta correctamente passa a ser recusada com mensagem, ou passa a ser interpretada correctamente com teste que o prova.

### Critérios de Aceitação

- [x] **Caso 1 resolvido, com a escolha escrita.** Um item de lista cuja primeira chave é `>-` (ou `>`, `|`, `|-`) ou (a) é lido correctamente, com todas as chaves seguintes presentes, ou (b) é **recusado** com erro de configuração que nomeia o ficheiro e a linha. O silêncio deixa de ser uma das saídas possíveis.
- [x] **Caso 2 resolvido, com a escolha escrita.** Um item de lista não citado que contenha `:` ou é lido como cadeia, ou é recusado com mensagem. Em nenhum caso se torna um mapa em silêncio.
- [x] **Os ficheiros `ci/*.yaml` actuais lêem-se igual, campo a campo.** Verificado por comparação da estrutura lida antes e depois da alteração, e não por «os gates continuam verdes» — os gates podem continuar verdes precisamente por causa do defeito.
- [x] **As construções que os ficheiros reais usam estão todas cobertas por teste**, em particular `razao: >-` num item de lista que tem mais chaves — a forma que os ficheiros de limiares e excepções usam para texto longo —, nas duas posições em que aparece nos 22 ficheiros: **com as outras chaves antes dele**, que é a forma de `ci/canon-lint.yaml` (10 ocorrências), `ci/refs-allow.yaml` (7), `ci/secrets-allow.yaml` (6) e `ci/licenses.yaml` (3); e **com uma chave depois dele**, que é a dos dois estratos de `ci/thresholds.yaml`, onde a chave engolida é o `padroes` do estrato. Como **primeira** chave do item (`- razao: >-`) não aparece em nenhum dos 22 — e é por isso que o critério 3 manda comparar a estrutura e não os *gates*. `ci/waivers.yaml` não entra na lista: tem `waivers: []` e a única ocorrência da forma está num exemplo comentado (linha 61).
- [x] **A recusa é erro de configuração (código 2), não achado (código 1).**
- [x] **O *docstring* do módulo passa a dizer o que ele recusa**, com estes dois casos nomeados — o módulo documenta a sua recusa larga como garantia, e a lista tem de ser verdadeira.
- [x] **Nenhuma dependência nova.** O módulo continua a correr antes de qualquer instalação, que é a razão de existir: o *job* do gate 9 e o *hook* de *pre-commit* dependem disso.
- [x] Nenhum ficheiro `ci/*.yaml` é reescrito para contornar o defeito do leitor: a correcção é no leitor.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `tools/kamba_yaml.py`, `tools/lint_arch/tests/test_kamba_yaml.py`.
- **Confirmar primeiro, com um comando.** Os dois casos estão reproduzidos na revisão adversarial; a primeira coisa a fazer é reproduzi-los no estado actual do módulo e registar a estrutura errada que ele devolve. É o «antes» da evidência, e é o que distingue este ticket de uma leitura do código.
- **Preferir recusar a interpretar.** Para cada caso, pesar o custo: interpretar um escalar em bloco correctamente exige seguir a indentação e a dobra de linhas (`>-` dobra, `|` preserva, e o sufixo `-` corta a linha final), e cada regra que se implementa é uma regra que pode ficar errada. Recusar é uma linha e não tem modo de falha silencioso. O ticket decide caso a caso e **escreve a razão**.
- **Varrer o módulo à procura de mais casos da mesma classe.** Estes dois vieram de uma revisão, não de uma varredura sistemática: âncoras e *aliases* (`&`, `*`), documentos múltiplos (`---`), chaves duplicadas, tabulações, `null`/`~`, e cadeias que começam por `#`. Cada um que leia mal em silêncio entra neste ticket; cada um que já recuse fica registado como coberto.
- **Fora de âmbito:** adoptar uma biblioteca de YAML (contraria a razão de existir do módulo, e o gate 9 não instala dependências); recusa de chaves desconhecidas, que é de outro nível e é **KAM-134**; reescrever os `ci/*.yaml`.

### Testes Requeridos

- Unit: *fixture* por caso — (a) item com `razao: >-` seguido de duas chaves: as duas presentes, ou recusa com linha; (b) `|`, `|-`, `>` na mesma posição; (c) item de lista com `:` não citado; (d) os casos varridos da mesma classe, um teste cada, a provar leitura correcta ou recusa.
- Equivalência: a estrutura lida de cada `ci/*.yaml` real, antes e depois, comparada campo a campo (teste que carrega os ficheiros do repositório, não *fixtures*).
- Integração: `make ci` verde; `make ci-waivers`, `make ci-4`, `make ci-11` e `make ci-9` a correr sobre os ficheiros reais.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-136.md`, com a estrutura errada que o módulo devolvia antes).
- [ ] Código revisto por ≥ 1 revisor, **2 se a leitura de algum `ci/*.yaml` mudar de resultado** — significaria que um limiar ou uma excepção estava a ser lido errado; testes verdes.
- [x] Documentação actualizada: `../docs/ci.md` §7 (lacuna 14 fechada) e o *docstring* do módulo com a lista do que recusa; Conventional Commits.
- [x] **Sem segredos** — não aplicável.
- [x] **Dependências** — nenhuma nova, e o módulo continua sem dependências por desenho.
- [x] Os casos varridos da mesma classe estão listados no PR, cada um com o seu resultado (lê bem, recusa, ou corrigido aqui).

### Handoff para Claude Code

```text
És o executor do ticket KAM-136 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-136), docs/ci.md §7 (lacuna 14) e tools/kamba_yaml.py.
Objectivo: nenhum caso em que o leitor lê mal sem o dizer.
- REPRODUZ PRIMEIRO os dois casos no estado actual e registra a estrutura errada que o módulo devolve. É o
  «antes» da evidência, e é o que distingue isto de uma leitura do código.
  (1) `razao: >-` como primeira chave de um item de lista engole as chaves seguintes.
  (2) item de lista não citado com `:` torna-se um mapa.
- PREFERE RECUSAR A INTERPRETAR. A premissa do módulo é «recusa o que não entendes», e é ela que o torna
  confiável. Interpretar escalares em bloco exige seguir indentação e dobra (`>-` dobra, `|` preserva, `-`
  corta a final) — cada regra implementada é uma regra que pode ficar errada. Decide caso a caso e escreve a razão.
- A forma `razao: >-` num item com mais chaves aparece em duas posições nos 22 ficheiros, e as duas
  têm de ficar cobertas por teste: com as outras chaves ANTES dele em ci/canon-lint.yaml (10),
  ci/refs-allow.yaml (7), ci/secrets-allow.yaml (6) e ci/licenses.yaml (3); com uma chave DEPOIS dele
  nos dois estratos de ci/thresholds.yaml, onde a chave engolida e o `padroes` do estrato. Como primeira
  chave do item (`- razao: >-`) nao aparece em nenhum dos 22. Em ci/waivers.yaml (`waivers: []`) so
  existe num exemplo comentado.
- Compara a estrutura lida de cada ci/*.yaml real ANTES e DEPOIS, campo a campo. Não te fies em «os gates
  continuam verdes»: eles podem continuar verdes por causa do defeito.
- VARRE o módulo à procura de mais casos da mesma classe: âncoras e aliases (& *), documentos múltiplos (---),
  chaves duplicadas, tabulações, null/~, cadeias que começam por #. Lista cada um no PR com o seu resultado.
- Erro de configuração é código 2, não 1.
Não expandas escopo: NÃO adoptes uma biblioteca de YAML (o gate 9 não instala dependências, e é a razão de
existir do módulo); recusa de chaves desconhecidas é KAM-134; não reescrevas os ci/*.yaml para contornar o leitor.
Testes: fixture por caso; teste de equivalência sobre os ci/*.yaml reais; make ci verde.
Abre PR com o template do §7.
```

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#36`, ramo
`feature/KAM-136-leitor-de-yaml-sem-silencios`, a partir de `origin/main`
(`7015cbf`), com `origin/main` integrado depois do KAM-008 (`13dc8f8`).
**Treze caixas marcadas, uma vazia** — a dos revisores humanos.
Os números estão em [`../docs/evidencia/KAM-136.md`](../docs/evidencia/KAM-136.md),
com o comando ao lado de cada um; a revisão adversarial está em
[`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md).

| CA | Estado | Evidência |
|---|---|---|
| 1 — caso 1 resolvido, com a escolha escrita | **satisfeito** | Escolha: **ler correctamente**, não recusar. O defeito era `indentacao_chave - 1` em `_ler_lista`, não uma regra em falta — a dobra já existia e já estava certa na posição de mapa. A estrutura errada do «antes» está registada (evidência §1.1): o item vinha com uma chave e um `razao` que continha `caminho: ci/x.yaml obrigatorio: true`. Testes: `TestCaso1DoKam136` (7 testes, 20 subcasos). Mutação «`indentacao_chave` → `indentacao_chave - 1`»: apanhada por três testes. Os outros indicadores de bloco na mesma posição (`>`, `>+`, `|`, `|-`, `|+`) são **recusados**, com ficheiro e linha na mensagem. **A primeira versão deste critério estava satisfeita só em parte:** a revisão adversarial encontrou o mesmo defeito de fronteira no outro extremo do bloco — um `# ver ADR-014` como **primeira** linha de um `razao: >-` desaparecia sem erro ([`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md) §4, A1). A `_ler_dobrado` passou a receber o número da linha do indicador, e a mutação que repõe o defeito é apanhada por cinco testes |
| 2 — caso 2 resolvido, com a escolha escrita | **satisfeito** | Escolha: **ler como cadeia**. O YAML exige `:` seguido de espaço ou fim de linha para separar chave de valor, e o `_CHAVE` não o exigia; passou a exigir. «Antes»: `- https://exemplo.ao/pagina` dava `{"https": "//exemplo.ao/pagina"}` (evidência §1.2). Em posição de mapa, `chave:valor` passa a **recusa**. Testes: `TestCaso2DoKam136` (5 casos). Mutação «*lookahead* retirado»: apanhada por quatro testes |
| 3 — os `ci/*.yaml` lêem-se igual, campo a campo | **satisfeito** | `TestEquivalenciaAntesEDepois`: **22 ficheiros, 0 divergências, 2 221 campos folha**, comparados contra a cópia congelada do leitor anterior (`tools/lint_arch/tests/leitor_antes_do_kam136.py`) e não contra um retrato em JSON, que envelheceria a cada edição de um `ci/*.yaml`. O teste também verifica que a cópia congelada **ainda tem os dois defeitos** — se os perder, deixou de ser oráculo. E não se mediu por «os *gates* continuam verdes»: a varredura das formas mostra que `- razao: >-` tem **zero** ocorrências nos 22 ficheiros, que é precisamente por que os *gates* estavam verdes com o defeito presente |
| 4 — as construções dos ficheiros reais todas cobertas | **satisfeito** | **Doze formas** sintácticas enumeradas por varrimento dos 22 ficheiros (evidência §4), cada uma com o seu teste, mais as 171 linhas de continuação de escalar dobrado. A forma `razao: >-` num item com mais chaves existe **28 vezes** em cinco ficheiros (26 com o `razao` em último, 2 com o `padroes` depois) e está em `test_a_forma_que_os_ficheiros_reais_usam`; as **50** ocorrências são a forma 8 da tabela acima, `chave: >-` em posição de mapa com qualquer nome de chave. **Nota de precisão, já emendada:** a primeira versão deste critério dizia que a forma era a que `ci/licenses.yaml`, `ci/refs-allow.yaml`, `ci/secrets-allow.yaml` e `ci/waivers.yaml` usam «na maioria das entradas». O `ci/waivers.yaml` tem `waivers: []` e a única ocorrência está dentro de um comentário (linha 61) — não há entradas, logo não há maioria. A varredura posicional mostrou mais: nos outros três, e no `ci/canon-lint.yaml` que a frase omitia, o `razao: >-` é sempre a **última** chave do item; a forma com uma chave **depois** dele só existe nos dois estratos do `ci/thresholds.yaml`. O critério foi reescrito com as duas posições e os ficheiros de cada uma (versão 1.20); a construção já estava coberta — era a frase que estava errada |
| 5 — recusa é erro de configuração (2), não achado (1) | **satisfeito** | Dos dez consumidores do módulo, **dois** devolviam 1: o `ci_waivers` (passou a ter `ConfiguracaoIlegivel`, subclasse de `WaiverInvalido` para não quebrar quem já apanhava a classe mãe) e o `supply_chain egress`, que convertia o `YamlSubsetError` num achado `egress-invalido` — e **um achado dispensa-se com um *waiver* do *gate* 11**. O segundo foi encontrado pela revisão adversarial, numa versão anterior da evidência §5 que o dava por conforme. Um *waiver* expirado **continua** a ser 1 — esse é um achado. Oito dos dez estão provados por execução ou por teste; o `dict_export` e o `lint_refs` por leitura do caminho de erro, e isso está dito na evidência §5 como limitação. No próprio módulo, o `UnicodeDecodeError` passou a `YamlSubsetError`: antes saía como excepção não tratada e o *gate* morria com *traceback* e código 1 |
| 6 — o *docstring* diz o que o módulo recusa | **satisfeito** | Reescrito em quatro grupos (estrutura, escalares em bloco, escalares, e o desvio dos escapes) com os dois casos do ticket nomeados e a escolha de cada um escrita. **Cada linha da lista tem um teste**: `TestRecusa.CASOS` (15) e `TestVarreduraDaMesmaClasse.RECUSAM` (64). **Duas linhas estavam falsas na primeira versão** e a revisão adversarial mediu-as: «algarismos não-ASCII» estava na lista do que recusa e são lidos como texto, e a garantia sobre linha vazia e `#` dentro de um `>-` não valia para a primeira linha do bloco. As duas corrigidas; o *docstring* registra que a lista já mentiu uma vez |
| 7 — nenhuma dependência nova | **satisfeito** | O módulo importa `re` e `pathlib`. O `git diff origin/main` acrescenta dois `import`: `tempfile` (biblioteca padrão, só no ficheiro de testes) e `leitor_antes_do_kam136` (a cópia congelada, dentro de `tools/lint_arch/tests/`). Nenhum `requirements*.txt`, `package.json` ou `pnpm-lock.yaml` tocado (evidência §9) |
| 8 — nenhum `ci/*.yaml` reescrito | **satisfeito** | `git diff --stat origin/main` não lista nenhum ficheiro de `ci/`. A correcção é no leitor, e as recusas novas foram escolhidas **depois** de se confirmar que nenhum ficheiro real as dispara (`test_todos_os_ficheiros_reais_se_leem`, descoberta por *glob*) |
| DoD — todos os CA satisfeitos; evidência com a estrutura errada do «antes» | **satisfeito** | Os oito. A estrutura errada está em evidência §1, reproduzida antes de se alterar uma linha |
| DoD — ≥ 1 revisor, **2 se a leitura mudar de resultado**; testes verdes | **não satisfeito** | **Zero revisores humanos.** A revisão adversarial independente ([`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md)) é evidência, não é um revisor — e esta é a vez em que isso mais se nota: ela encontrou dois bloqueadores depois de o PR estar aberto e verde. A condição dos 2 revisores **não se aplica**: nenhuma leitura de nenhum `ci/*.yaml` mudou de resultado (CA 3, 0 divergências em 2 221 campos). Testes verdes: evidência §6 |
| DoD — documentação; `docs/ci.md` §7 lacuna 14 fechada; Conventional Commits | **satisfeito** | Lacuna 14 riscada e fechada com o que mudou e o que ficou aberto (a lacuna 22 nova: há **três** leitores de subconjunto de YAML no repositório e só um foi varrido); `docs/ci.md` linha de versão 1.15; *docstring* no CA 6; *commits* `fix(KAM-136)` e `docs(KAM-136)`, validados pelo `lint_arch` no *hook* |
| DoD — sem segredos | **satisfeito** | Não aplicável, e o *gate* 9 corre sobre o diff: `scan_secrets: limpo` em cada *commit* (*hook* de *pre-commit*) |
| DoD — dependências: nenhuma nova | **satisfeito** | CA 7 |
| DoD — os casos varridos listados no PR, cada um com o resultado | **satisfeito** | **101 casos**, cada um corrido contra o leitor anterior **e** contra o actual e classificado pela diferença, não por leitura: 20 já recusavam, 20 já liam bem, **46 liam mal em silêncio e passaram a recusar**, **10 liam mal em silêncio e passaram a ler bem**, e **5 recusavam de mais e passaram a ler**. A tabela está no corpo do PR e em [`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md) §2 e §4 |

#### Decisões tomadas aqui, e porquê

| # | Decisão | Razão |
|---|---|---|
| 1 | Caso 1: **interpretar**, não recusar | A dobra já existia e já estava correcta na posição de mapa, duas linhas acima; o defeito era a indentação do pai que lhe era passada. Recusar seria recusar uma forma que o leitor lê bem no mapa e mal na lista, e obrigaria a reescrever ficheiros que a usassem. A dobra passou, ao mesmo tempo, a recusar tudo o que não seja a dobra uniforme — o que fica interpretado é exactamente o que é verificável |
| 2 | Caso 2: **interpretar como cadeia**, não recusar | É o que o YAML diz e o que o autor quis. Recusar o item seria recusar uma cadeia legítima (`https://…`, `C:/…`) que nenhuma outra forma substitui sem aspas. O mesmo `:` em posição de **mapa** (`chave:valor`) passa a recusa, porque aí a cadeia tem outro significado |
| 3 | Os restantes 46: **recusar** | Em todos, interpretar exigia uma regra nova de YAML (dobra com linhas mais indentadas, *chomping*, escapes, resolução de tipos por versão do YAML). «Cada regra que se implementa é uma regra que pode ficar errada»: recusar é uma linha e não tem modo de falha silencioso |
| 4 | Só `>-` se aceita; `>` e `>+` passam a recusa | Diferem do `>-` apenas na linha final, que este leitor não preserva. Aceitá-los era ler `>` como `>-` em silêncio. Nenhum ficheiro real os usa (verificado) |
| 5 | `ci_waivers` **e** `supply_chain egress` passam a devolver 2 para uma recusa do leitor | É o CA 5. Eram os dois únicos dos dez consumidores a reportar uma recusa do leitor como achado — e um achado dispensa-se com um *waiver* do *gate* 11. No `ci_waivers` fez-se por subclasse (`ConfiguracaoIlegivel(WaiverInvalido)`) e só para a recusa do leitor: um *waiver* expirado continua a ser 1, porque é um achado, e a semântica dos *waivers* é do KAM-135. O do `egress` foi encontrado pela revisão adversarial |
| 6 | A cópia congelada do leitor anterior entra no repositório | É o único oráculo de equivalência que não envelhece. Vive em `tools/lint_arch/tests/`, que o `coverage-python` omite (`--omit="*/tests/*"`) |
| 7 | Cinco recusas que recusavam **de mais** passam a ler-se | O BOM UTF-8 era a pior: qualquer editor do Windows que gravasse «UTF-8 with BOM» matava o *gate* com uma mensagem a mandar procurar um erro de sintaxe inexistente. Mais o `---` de um documento único (que é YAML válido e comum), um `---` indentado dentro de um escalar dobrado (onde é conteúdo), e `[ ]`. Nenhuma delas é interpretação nova: cada uma tem **um** significado |
| 8 | Os escapes em aspas duplas **ficam** literais, e passam a estar escritos | É a semântica de que o `tools/dict_export/exportar.py` depende (`_texto`), e a ida-e-volta do `render` prova que quem escreve e quem lê concordam. Recusar o `\` quebraria o `dict_export` por causa de um `\` numa descrição do dicionário — e esse risco não foi medido. É um **desvio do YAML** declarado no *docstring*, não uma leitura silenciosa |

#### Decisões devolvidas

| # | O que | A quem |
|---|---|---|
| ~~1~~ | ~~**A frase do CA 4 está errada num dos quatro ficheiros.** `ci/waivers.yaml` não usa `razao: >-` «na maioria das entradas»: não tem entradas. A construção está coberta por teste; a frase precisa de emenda~~ — **resolvida** na versão 1.20 deste epic: o critério foi reescrito com as duas posições em que a forma aparece e os ficheiros de cada uma, e a varredura posicional acrescentou que o `ci/canon-lint.yaml` estava omitido da enumeração | A quem escreveu o critério — **respondido** |
| 1b | **A `ANALISE-11` que o *handoff* atribuiu já existe** (KAM-068, em `main` desde `443dc8f`, citada nove vezes). Tomou-se o número livre seguinte, **12**. Se um dos tickets em paralelo nesta vaga tiver levado o 12, renumera-se na integração | A quem orquestra a vaga |
| 2 | **O repositório tem três leitores de subconjunto de YAML** — `tools/kamba_yaml.py`, `tools/canon_lint/yamlreg.py` e `tools/secrets_inventory/yamlsubset.py` — e este ticket varreu **um**. Os outros dois leem `canon/*.yaml` em estilo de fluxo e `ops/secrets-inventory.yaml`, e podem ter a mesma classe de leitura silenciosa. Registado como lacuna 22 de `../docs/ci.md` §7; precisa de ticket | Ao fundador |

---

## KAM-137 — Verificação do *ruleset* de `main` e onde vive o *token* de administração

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P2 |
| Estimativa | M |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma com Responsável de Segurança |
| Documentos de referência | `../docs/ci.md` (§6 autenticação, §7 lacuna 15), `.github/rulesets/README.md`, `.github/rulesets/main.json`, `../docs/tecnica/08_Seguranca_Conformidade.md` §4.8, `specs/01_Engineering_Standards_e_Handoff.md` §4, ADR-008 |

### Contexto

O *ruleset* `main: gates fail-closed do KAM-002` é **a peça de que toda a propriedade *fail-closed* depende**: sem ele, os seis gates correm, reportam, e nada impede o *merge*. É configuração que vive na API do GitHub, altera-se sem PR e sem revisor, e não deixa rasto no repositório.

O KAM-002 espelhou-o em `.github/rulesets/main.json`, e o `README.md` ao lado diz com precisão o que o espelho **não** faz: o ficheiro não é aplicado por nada. Editá-lo não altera o GitHub, e alterar o GitHub não o actualiza. **A volta está aberta nos dois sentidos**, e o espelho pode estar desactualizado sem ninguém dar por isso — o que é a pior posição possível, porque um ficheiro que parece ser a fonte e não é engana melhor do que a ausência dele.

**E aqui está a razão por que isto não se fecha de passagem.** Fechar a volta — aplicar o ficheiro, ou comparar os dois — precisa de um *token* com `administration: write`. O critério de aceitação do KAM-002 diz «sem chaves estáticas», e o `../docs/tecnica/08` §4.8 exige OIDC; o §6 do `../docs/ci.md` registra que um `grep` por chaves estáticas nos *workflows* devolve zero, e o gate 9 varre os próprios ficheiros do *workflow*. Um *token* de administração guardado nos segredos do repositório contradiz isso **e** é o *token* mais perigoso que existe neste contexto: quem o tem desliga os gates todos.

**Por isso o ticket é, antes de tudo, uma decisão — e é essa decisão que o torna `M`.** As opções são conhecidas e não equivalentes:

| Opção | O que resolve | O que custa |
|---|---|---|
| GitHub App própria, com `administration: write` e *token* de instalação de curta duração | Fecha a volta sem chave estática; auditável por instalação | Uma App para manter, e a sua chave privada passa a ser o segredo crítico |
| Verificação **fora** do CI do repositório (*workflow* agendado noutro contexto, ou execução manual periódica) | Não põe o *token* no CI que ele poderia desligar | Deixa de ser gate de PR; detecta a divergência mais tarde |
| Só detecção, com *token* de leitura (`administration: read`) a comparar e nunca a aplicar | Muito menos poder concedido; apanha a divergência | Não repõe o *ruleset*; alguém tem de agir sobre o alerta |
| Revisão humana periódica contra o `main.json`, sem *token* | Sem segredo novo | Depende de disciplina, que é o que o KAM-002 existe para não depender |

**A opção de menor poder que resolve o problema declarado é a terceira**, e é a recomendação a levar à decisão — detectar a divergência é o que falta; repô-la automaticamente é conveniência, e paga-se com o *token* que desliga tudo. Mas a escolha é do Arquitecto de Plataforma com o Responsável de Segurança, fica registada em ADR local, e o ticket não a toma sozinho.

### Objectivo

Fechar a volta entre o *ruleset* que o GitHub aplica e o espelho versionado, com a decisão sobre onde vive o *token* de administração — e com quanto poder — registada em ADR antes de se escrever a verificação.

### Critérios de Aceitação

- [ ] **A decisão está registada em ADR local** (`../docs/adr/`, numeração `ADR-LNNN` como o `ADR-L001`, para não colidir com a sequência canónica — ver `../docs/adr/README.md`), com: a opção escolhida, as rejeitadas e porquê, onde vive a credencial, que permissões tem, quem a pode usar, como se roda e o que acontece se for comprometida.
- [ ] **A verificação existe e corre**, na forma que o ADR escolher, e **falha** quando o *ruleset* efectivo divergir de `.github/rulesets/main.json`.
- [ ] **A divergência é detectada nos dois sentidos**, verificado por execução e não por leitura: (a) um *required check* retirado no GitHub e presente no ficheiro; (b) um acrescentado no ficheiro e ausente do GitHub. Os dois casos demonstrados, com o resultado registado.
- [ ] **A comparação é sobre o que importa, e a lista está escrita.** `required_status_checks` (os sete contextos), `pull_request` (uma aprovação), `deletion`, `non_fast_forward`, `enforcement: active`, `bypass_actors` **vazio** — um *bypass actor* acrescentado é tão grave como um gate retirado, e é a alteração que mais facilmente passa despercebida. Campos voláteis que a API devolva e não sejam política (identificadores, carimbos) ficam fora da comparação, nomeados um a um.
- [ ] **Fail-closed inclui não conseguir verificar.** Se a API não responder ou a credencial não autorizar, a verificação **falha** — não dá o *ruleset* por conforme. É a mesma regra que o gate 11 já aplica à OSV: «um gate de segurança que passa quando não consegue verificar é um gate que mente».
- [ ] **Nenhuma chave estática entra nos *workflows*.** O `grep` do §6 continua a devolver zero e o gate 9 continua a varrer os ficheiros do *workflow*; se a opção escolhida precisar de credencial no CI, o ADR explica como ela não é chave estática, e o critério de aceitação do KAM-002 é reavaliado explicitamente — não contornado.
- [ ] **O espelho deixa de poder envelhecer em silêncio.** Depois deste ticket, `.github/rulesets/main.json` desactualizado é um resultado visível; e o `README.md` ao lado passa a dizer o que a volta fechada faz, substituindo a secção «O que não faz».
- [ ] **O procedimento de reposição está escrito**, mesmo que manual: o que correr, com que credencial e quem pode, para que a resposta ao alerta não seja inventada no momento.
- [ ] O comando de exportação do `README.md` continua a reproduzir o ficheiro, com o `id` do *ruleset* ao lado.

### Detalhes Técnicos

- **Componentes:** transversal (CI e governação do repositório). Ficheiros: `.github/rulesets/main.json`, `.github/rulesets/README.md`, ADR local novo em `../docs/adr/`, e o que a opção escolhida exigir (`.github/workflows/`, `tools/`, `Makefile`).
- **A ordem importa: ADR primeiro.** Escrever a verificação antes de decidir onde vive a credencial é escolher a opção por omissão — a que for mais fácil de implementar — numa decisão cujo critério é segurança e não conveniência.
- **`strict_required_status_checks_policy: false`** é deliberado e está justificado no `README.md` («exigir *rebase* a cada *merge* alheio custa mais do que vale num repositório com um contribuidor», a rever quando a equipa crescer). A verificação compara-o como está, e não o trata como defeito; se a decisão mudar, muda no ficheiro e no `README.md`.
- **O *ruleset* é a dependência silenciosa de todos os gates.** Vale registar no ADR: um *ruleset* apagado deixa os gates a correr e o `main` aberto, e nada no CI do repositório o detectaria — é o modo de falha que este ticket existe para fechar, e é por isso que a opção «verificação dentro do mesmo CI que o *token* poderia desligar» tem de ser ponderada e não assumida.
- **Fora de âmbito:** acrescentar ou retirar regras ao *ruleset* (é decisão de governação, não deste ticket, e o `required_approving_review_count` de 1 vem do KAM-002); gerir *rulesets* de outros ramos; `CODEOWNERS`; assinatura de *commits* e *tags* (KAM-067, gates 14 e 18); o CI/CD completo e o *deploy* (KAM-078).

### Testes Requeridos

- Integração, por execução e não por leitura: (a) *required check* retirado no GitHub → verificação vermelha; (b) contexto acrescentado ao ficheiro e ausente do GitHub → vermelha; (c) `bypass_actors` com uma entrada → vermelha; (d) ficheiro e API iguais → verde; (e) credencial sem autorização ou API em baixo → vermelha, não verde. Cada caso com o registo do resultado; (a) e (c) feitos e revertidos numa janela registada, com a reposição confirmada.
- Unit (se houver comparador próprio): normalização e comparação sobre respostas de API em *fixture*, incluindo campos voláteis ignorados e um campo de política ausente.
- Segurança: `grep` por chaves estáticas nos *workflows* devolve zero; gate 9 verde sobre `.github/**`; o relatório da verificação não imprime a credencial nem o *token*.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-137.md`, com os cinco casos de integração e as janelas de alteração do *ruleset*).
- [ ] ADR local emitido e aprovado **antes** da implementação, com a decisão sobre a credencial; revisto pelo Arquitecto de Plataforma **e** pelo Responsável de Segurança.
- [ ] Código e configuração revistos por ≥ 2 revisores — altera a governação do `main` e introduz (ou decide não introduzir) uma credencial de administração; testes verdes.
- [ ] Documentação actualizada: `../docs/ci.md` §6 (autenticação, se a decisão a tocar) e §7 (lacuna 15 fechada); `.github/rulesets/README.md` reescrito na parte «O que não faz»; Conventional Commits.
- [ ] **Sem segredos** — nenhuma chave estática nos *workflows*; a credencial, se existir, vive onde o ADR diz e tem rotação definida (KAM-010, KAM-072).
- [ ] **Dependências** — nenhuma dependência nova sem entrada na *allowlist* de licenças.
- [ ] O procedimento de reposição do *ruleset* está escrito e foi ensaiado uma vez.

### Handoff para Claude Code

```text
És o executor do ticket KAM-137 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-137), docs/ci.md §6 e §7 (lacuna 15), e
.github/rulesets/README.md. Objectivo: fechar a volta entre o ruleset que o GitHub aplica e o espelho versionado.
- ADR PRIMEIRO, implementação depois. A decisão é onde vive o token com `administration: write` e quanto poder
  tem. Escrever a verificação antes de decidir é escolher a opção mais fácil de implementar numa decisão cujo
  critério é segurança. O bloco tem a tabela das quatro opções com o que cada uma custa.
- A recomendação a levar à decisão é a de MENOR PODER que resolve o problema declarado: só detecção, com
  `administration: read`. Detectar a divergência é o que falta; repor automaticamente é conveniência e paga-se
  com o token que desliga todos os gates. Mas decidem o Arquitecto de Plataforma e o Responsável de Segurança.
- ADR local em docs/adr/, numeração ADR-LNNN (ver docs/adr/README.md): não colide com a sequência canónica.
- Compara o que é política e escreve a lista: required_status_checks (os sete contextos), pull_request,
  deletion, non_fast_forward, enforcement, e bypass_actors VAZIO — um bypass actor acrescentado é tão grave
  como um gate retirado e é o que mais facilmente passa despercebido. Nomeia os campos voláteis ignorados.
- strict_required_status_checks_policy: false é DELIBERADO e justificado no README. Compara-o como está;
  não o trates como defeito.
- Fail-closed inclui não conseguir verificar: API em baixo ou credencial sem autorização é VERMELHO, como o
  gate 11 já faz com a OSV.
- Demonstra os dois sentidos da divergência por execução: retira um required check no GitHub, acrescenta um
  contexto só no ficheiro, e põe uma entrada em bypass_actors. Reverte e confirma a reposição.
Não expandas escopo: não acrescentes nem retires regras ao ruleset (governação, não este ticket); sem
CODEOWNERS, sem assinatura de commits/tags (KAM-067), sem deploy (KAM-078).
Testes: os cinco casos de integração do bloco, com registo; grep de chaves estáticas nos workflows a zero.
Abre PR com o template do §7.
```

---

## KAM-138 — Gate 3c: lint de coerência do backlog (mestre ↔ epics)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P2 |
| Estimativa | M |
| Dependências | KAM-002 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma com Engenheiro de Plataforma |
| Documentos de referência | `specs/INDICE.md` (§3.1, §4), `specs/01_Engineering_Standards_e_Handoff.md` (§4 tabela de gates, §5), `../docs/ci.md` (§2 gate → alvo → dono, §3 gate 3), `tools/lint_refs/`, `specs/EPIC-01_Fundacoes_Dados.md` (blocos KAM-128, KAM-129, KAM-130) |

### Contexto

O backlog diz as mesmas coisas em dois sítios: a linha do ticket em `specs/INDICE.md` §4 (o «contrato entre epics») e o bloco `## KAM-NNN — ` no epic. Tipo, estimativa, prioridade, fase e dependências aparecem nos dois, e **nada no repositório verifica que concordam**.

**Não é hipótese: é o defeito mais frequente desta série de tickets.** Os blocos KAM-128, KAM-129 e KAM-130 têm cada um a linha de DoD «**Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e o bloco deste epic dizem o mesmo; segunda passagem de verificação dá 0 divergências», e o KAM-129 chegou a precisar de uma busca própria (G5) por ter sido apanhado com uma dependência declarada de um só lado. Três tickets seguidos gastaram critério de aceitação a verificar à mão o que um lint verifica em segundos — e a verificação manual é precisamente o que falha quando há pressa.

**Nenhum gate existente cobre isto, e vale dizer porquê**, para o ticket não nascer a duplicar:

| Gate | O que verifica | Porque não serve |
|---|---|---|
| 3 — referências cruzadas (KAM-002) | que um `KAM-NNN` citado **existe** no §4 | lê o §4 só para extrair identificadores; não olha para os campos nem para os blocos |
| 3b — nomes canónicos (KAM-111) | DDL, schemas de eventos e contratos de tools contra o dicionário de dados | âmbito é nomenclatura de dados; o próprio ticket declara «Fora de âmbito: reconciliar os tickets» |
| `lint_arch` | lista de bloqueio de dependências e árvore obrigatória | não lê `specs/` |

O KAM-130 declara esta automatização fora do seu âmbito e remete-a para «o gate de referências de KAM-002 e o lint de KAM-111». Verificado: **nenhum dos dois a cobre.** É a razão de existir deste ticket.

**Um defeito vivo, que o lint apanharia no primeiro dia.** A «Tabela Resumo de Tickets» do §3 deste epic **não tem o KAM-129 nem o KAM-130**: ficaram de fora quando esses tickets foram abertos, e ninguém deu por isso porque nada compara as três superfícies. É o caso de aceitação natural do ticket, e não um exemplo inventado.

**A armadilha que o KAM-129 já documentou, e que este ticket tem de fechar.** O §4 **não tem coluna `Bloqueia`**, pelo que uma comparação linha↔bloco compara apenas os campos que a linha também tem. Consequência: um ticket que declare `Dependências | KAM-NNN` sem entrar no `Bloqueia` do KAM-NNN **satisfaz a sincronia pela razão errada** — foi o que aconteceu na primeira versão do KAM-129. Um lint que se limite a comparar os cinco campos herda esse buraco e dá uma falsa garantia, que é pior do que não ter lint.

### Objectivo

Entregar um gate que falhe o PR quando o backlog mestre e os blocos dos epics discordarem, quando o grafo de dependências não for recíproco, ou quando uma contagem declarada não corresponder ao que está escrito — tornando desnecessárias as verificações manuais que os tickets têm vindo a repetir.

### Critérios de Aceitação

- [ ] **Sincronia linha↔bloco, campo a campo.** Para cada ticket, os cinco campos que existem nos dois lados (título, tipo, estimativa, prioridade, fase) e as `Dependências` são comparados; qualquer divergência falha o gate e a mensagem diz o ticket, o campo, o valor do §4 e o valor do bloco.
- [ ] **Nenhum ticket órfão, nos dois sentidos.** Uma linha no §4 sem bloco falha; um bloco `## KAM-NNN — ` que não tenha linha no §4 falha. Hoje são 0 e 0, e esse estado fica medido como baseline.
- [ ] **Reciprocidade do grafo (o buraco do G5).** `Dependências` e `Bloqueia` concordam nos dois sentidos: se o bloco de A declara `Dependências | B`, o bloco de B tem A no `Bloqueia`, e vice-versa. **Este critério é o que distingue este gate de uma comparação de tabelas** — sem ele, o lint herda a falsa garantia que o KAM-129 documentou, por o §4 não ter coluna `Bloqueia`.
- [ ] **Sem ciclos no grafo de dependências**, e o ciclo é reportado com o caminho completo (`A → B → C → A`), não só com o nome de um ticket.
- [ ] **Inversões de prioridade e de fase são detectadas.** Um P0 que depende de um P1 ou P2, ou um ticket de Fase 0 que depende de um de Fase 1, é reportado. **O estado inicial não é limpo** — o risco R11 deste epic registra que o KAM-012 e o KAM-010 são P1 e servem tickets P0 — pelo que estas duas verificações nascem como **aviso** com a lista das inversões conhecidas declarada num ficheiro de excepções com razão por entrada, e passam a falha quando essa lista estiver vazia. A escolha está escrita, e não implícita.
- [ ] **Contagens derivadas, nunca copiadas.** O gate recalcula e compara: a contagem por epic e o intervalo do §3.1, a soma da coluna «N.º tickets» contra o TOTAL, o intervalo e o total do TOTAL, e os números do §1. Uma contagem que não derive do §4 falha, com o valor lido e o valor derivado lado a lado.
- [ ] **O «Controlo de versões» de cada documento é uma sequência sem buracos, e o cabeçalho diz a última.** Duas verificações sobre a tabela que todos os documentos de `specs/` e `docs/` têm no fim: (a) as linhas formam uma sequência contínua — um número saltado falha, com o número em falta na mensagem; (b) onde o cabeçalho tem campo de versão, ele iguala a última linha. **O estado inicial não é limpo, e está medido:** dos **25** documentos com esta tabela, **1** tem buraco (este epic, sem `1.13`, resíduo da renumeração do `80ab82b`) e **9** têm o cabeçalho atrasado — oito em «Versão 1.0» com histórico até 1.1, 1.5 e 1.20. Como as inversões de prioridade, estas duas nascem como **aviso** com o estado conhecido declarado em `ci/backlog-allow.yaml`, e passam a falha quando a lista esvaziar. **Porque é que isto é do gate e não de quem escreve:** o buraco do `1.13` nasceu de dois ramos a tomarem o mesmo número em paralelo, e a emenda do CA 4 do KAM-136 renumerou **quatro** vezes em poucas horas pela mesma razão. Com vários tickets a fundir no mesmo dia, a linha de versão é ponto de contenção garantido, e nenhuma revisão humana a apanha de forma fiável.
- [ ] **O cabeçalho de versão é reconhecido nas duas formas que o conjunto usa**, ou o gate recusa: `| Versão | 1.2 |` numa tabela de campos (os epics, `specs/01`, `specs/02`) e `**Versão do conjunto:** 1.2` em texto corrido (`specs/INDICE.md`). **11** dos 25 não têm campo nenhum, e para esses só vale a verificação da sequência — a ausência do campo não é defeito, e o gate não a inventa.
- [ ] **A «Tabela Resumo de Tickets» do §3 de cada epic entra na comparação**, como terceira superfície. O gate falha hoje sobre o EPIC-01, por lhe faltarem o KAM-129 e o KAM-130 — e essa falha, antes da correcção, é o teste de aceitação que prova que o gate morde.
- [ ] **O gate é fail-closed sobre a sua própria entrada.** Um epic que o parser não consiga ler, um bloco sem tabela de campos, um campo obrigatório ausente: erro de configuração (código de saída 2), não «nada a reportar». Um lint de coerência que dê verde por não ter conseguido ler nada é o modo de falha que ele existe para não ter.
- [ ] **Entra na tabela de gates e tem dono.** `specs/01_Engineering_Standards_e_Handoff.md` §4 e `../docs/ci.md` §2 passam a listar o gate 3c com alvo `make ci-3c` e dono, na forma que o 3b (KAM-111) já usa.
- [ ] **Corre em ≤ 15 s** sobre o conjunto actual (*proposta*, a calibrar com a primeira medição) e **sem dependências novas**, como o resto das ferramentas de gate.
- [ ] **As linhas de DoD manuais passam a remeter para o gate.** Depois deste ticket, um ticket novo não precisa de «segunda passagem de verificação dá 0 divergências» como critério próprio: o gate di-lo. A alteração dessas linhas nos blocos existentes **não** entra aqui (ver Fora de âmbito).

### Detalhes Técnicos

- **Componentes:** transversal (CI e documentação); sem código de *runtime*. Ficheiros: `tools/lint_backlog/` (novo), `Makefile` (alvo `ci-3c`), `.github/workflows/ci.yaml` (*job* novo, e `required_status_checks` do *ruleset*), `ci/backlog-allow.yaml` (excepções das inversões conhecidas e dos cabeçalhos de versão atrasados), `specs/01_Engineering_Standards_e_Handoff.md` §4, `../docs/ci.md` §2.
- **Ferramenta própria ou extensão do `lint_refs`?** O `lint_refs` já lê o §4 para extrair identificadores, e partilhar o leitor evita duas gramáticas para a mesma tabela. Mas o alcance é outro — ele varre a árvore toda à procura de citações, este lê dois formatos de `specs/` — e misturá-los torna a mensagem de falha ambígua sobre qual o gate que falhou. **Proposta: módulo próprio (`tools/lint_backlog/`) que reutilize o leitor do §4 do `lint_refs`**, com a decisão e a razão escritas no PR.
- **Duas gramáticas a reconhecer, e ambas são frágeis.** A linha do §4 é `| KAM-NNN | título | tipo | est | prio | fase | deps |`; o bloco é `## KAM-NNN — título` seguido de uma tabela `| Campo | Valor |`. O parser tem de ser estrito e dizer o que não entendeu — e os títulos trazem *markup* (`` `código` ``, `*itálico*`), pelo que a comparação de títulos precisa de uma regra de normalização **escrita** (ou de exigir igualdade exacta, que é mais simples de verificar e foi o que se observou ser verdade hoje).
- **Fonte da verdade quando os dois lados discordam.** O gate **não** decide: reporta e falha. O §4 é «contrato entre epics» e o bloco é a especificação; qual dos dois se corrige é decisão de quem escreveu o ticket, e um lint que escolhesse por omissão esconderia metade dos defeitos ao corrigi-los.
- **Nota de calibração do `Bloqueia`.** O campo usa `—` para «nenhum» e listas separadas por vírgula; a reciprocidade tem de tratar `ext:` (dependências externas, como `ext:D6` e `ext:KAM-102`) sem exigir reciprocidade de uma decisão ou de um terceiro. O `ext:KAM-NNN` é o caso que engana: tem forma de ticket e significa «espera por este, que é externo ao código».
- **Porque é P2 e não P0.** Nenhum ticket depende deste, e o backlog está hoje coerente nos campos comparados (medido: 137 linhas, 137 blocos, 0 divergências). O que o gate impede é a **regressão** — e o custo de não o ter é pago em revisão manual, não em bloqueio.
- **Fora de âmbito:** corrigir os cabeçalhos de versão atrasados e o `1.13` em falta neste epic, que estão registados como resíduo em [`dividas-documentais`](../docs/dividas-documentais.md), linhas 4 e 21 — aqui só se passa a medi-los; corrigir as contagens e os inventários herdados (**KAM-130**, que está aberto e é dono dessa classe, incluindo a ausência do KAM-129 e do KAM-130 no §3 do EPIC-01); reescrever as linhas de DoD dos blocos existentes que fazem a verificação à mão; nomes canónicos de dados (**KAM-111**, gate 3b); validar o **conteúdo** de um ticket (se os critérios são SMART, se a estimativa é realista) — isto verifica coerência, não qualidade; gerar o backlog a partir de uma fonte única, que seria reescrever o conjunto e não verificá-lo.

### Testes Requeridos

- Unit, com *fixtures* de um `INDICE.md` e um epic mínimos: (a) campo divergente em cada um dos seis campos, um teste cada; (b) linha sem bloco; (c) bloco sem linha; (d) dependência declarada de um só lado (o caso G5); (e) ciclo de três tickets, com o caminho na mensagem; (f) P0 a depender de P1; (g) Fase 0 a depender de Fase 1; (h) contagem do §3.1 errada; (i) soma da coluna diferente do TOTAL; (j) intervalo do §3.1 que não cobre um ticket existente; (k) epic ilegível → código 2; (l) bloco sem tabela de campos → código 2; (m) título com *markup* igual nos dois lados → passa; (n) `ext:D6` e `ext:KAM-102` não exigem reciprocidade.
- Unit, controlo de versões: (a) tabela com um número saltado — o número em falta vem na mensagem; (b) cabeçalho atrasado em cada uma das duas formas (`| Versão | x.y |` e `**Versão do conjunto:** x.y`); (c) documento sem campo de versão — passa, e só a sequência é verificada; (d) entrada de `ci/backlog-allow.yaml` a baixar um dos dois de falha a aviso, e a remoção dela a repor a falha.
- Regressão medida sobre o conjunto real, controlo de versões: **25** documentos com tabela, **1** buraco (`1.13` neste epic) e **9** cabeçalhos atrasados — os três números registados como *baseline*, porque são o que a lista de `ci/backlog-allow.yaml` tem de cobrir no primeiro dia.
- Regressão medida sobre o conjunto real: o gate **falha** sobre o `specs/EPIC-01` antes da correcção do §3 (KAM-129 e KAM-130 ausentes) e **passa** depois dela — os dois resultados registados, porque é a prova de que morde.
- Integração: `make ci-3c` verde sobre o conjunto corrigido; tempo de execução medido, com o comando ao lado; o *job* aparece nos *required checks*.
- Mutação deliberada: alterar a estimativa de um ticket só no §4 torna o gate vermelho; reverter torna-o verde.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-138.md`, com o «antes» vermelho sobre o §3 do EPIC-01 e os números do conjunto).
- [ ] Código revisto por ≥ 1 revisor, **2 por acrescentar um gate bloqueante de *merge*** (`specs/01_Engineering_Standards_e_Handoff.md` §4); testes verdes.
- [ ] Documentação actualizada: `specs/01_Engineering_Standards_e_Handoff.md` §4 e `../docs/ci.md` §2 com o gate 3c, alvo e dono; o «Fora de âmbito» do KAM-130 passa a remeter para este ticket em vez de para KAM-002/KAM-111; Conventional Commits.
- [ ] **Sem segredos** — não aplicável: o gate lê `specs/` e não acede à rede.
- [ ] **Dependências** — nenhuma nova; só biblioteca padrão, como as outras ferramentas de gate.
- [ ] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e este bloco dizem o mesmo; e a partir deste ticket é o próprio gate que o verifica.
- [ ] As inversões de prioridade declaradas em `ci/backlog-allow.yaml` têm razão escrita por entrada e remetem para o risco do epic que as registra (R11).
- [ ] O *job* do gate 3c está nos *required checks* do *ruleset*, e o espelho `.github/rulesets/main.json` foi actualizado (ver KAM-137).

### Handoff para Claude Code

```text
És o executor do ticket KAM-138 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-138), specs/INDICE.md §3.1 e §4, e o bloco KAM-129 deste epic
(o parágrafo da busca G5). Objectivo: um gate que falhe quando o backlog mestre e os blocos dos epics discordarem.
- O QUE DISTINGUE ISTO DE UMA COMPARAÇÃO DE TABELAS é a reciprocidade Dependências<->Bloqueia. O §4 NÃO tem
  coluna `Bloqueia`, pelo que comparar só os cinco campos deixa passar uma dependência declarada de um lado —
  foi o que aconteceu na primeira versão do KAM-129. Sem este critério o lint dá falsa garantia.
- Verifica também: órfãos nos dois sentidos, ciclos (com o caminho completo na mensagem), e contagens
  DERIVADAS do §4 (§3.1 por epic, intervalo, soma da coluna contra o TOTAL, e os números do §1).
- Terceira superfície: a «Tabela Resumo de Tickets» do §3 de cada epic. O gate FALHA HOJE sobre o EPIC-01,
  porque lhe faltam o KAM-129 e o KAM-130 — usa isso como teste de aceitação, é a prova de que morde. NÃO
  corrijas o §3 neste ticket: é do KAM-130, que está aberto e é dono dessa classe. Registra o vermelho.
- Inversões de prioridade e de fase: o estado inicial NÃO é limpo (risco R11 deste epic: KAM-012 e KAM-010 são
  P1 e servem P0). Nascem como AVISO, com as conhecidas em ci/backlog-allow.yaml com razão por entrada, e
  passam a falha quando a lista esvaziar. Escreve a escolha.
- O gate NÃO decide qual dos dois lados está certo: reporta e falha. Escolher por omissão esconderia metade
  dos defeitos ao corrigi-los.
- Fail-closed sobre a própria entrada: epic ilegível ou bloco sem tabela de campos é código 2, não verde.
  Um lint de coerência que dá verde por não ter lido nada é o modo de falha que ele existe para não ter.
- Trata `ext:` (ext:D6, ext:KAM-102) sem exigir reciprocidade. O ext:KAM-NNN é o que engana: tem forma de
  ticket e significa «espera por este, que é externo ao código».
- Módulo próprio em tools/lint_backlog/, reutilizando o leitor do §4 do lint_refs. Sem dependências novas.
- Acrescenta o gate 3c ao specs/01 §4 e ao docs/ci.md §2 com alvo e dono, na forma que o 3b (KAM-111) já usa,
  e põe o job nos required checks (actualiza o espelho .github/rulesets/main.json — ver KAM-137).
Não expandas escopo: contagens e inventários herdados são KAM-130; nomes canónicos de dados são KAM-111
(gate 3b); não avalies a QUALIDADE de um ticket (critérios SMART, estimativa realista) — isto é coerência;
não gères o backlog a partir de uma fonte única, que seria reescrever o conjunto e não verificá-lo.
Testes: os catorze casos unitários do bloco; a regressão medida sobre o EPIC-01 (vermelho antes, verde depois);
mutação deliberada de uma estimativa só no §4. Abre PR com o template do §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| # | Risco / item | Estado | Decisão ligada | Mitigação / critério de saída |
|---|---|---|---|---|
| R1 | Garantias de entrega do BullMQ (jobs parados, perda da cauda do AOF) | NÃO VERIFICADO (E4 §2.10) | ADR-009; D12 (Redis vs Valkey) | KAM-005 assume o pior caso; nota de leitura da documentação no PR; reconciliador de KAM-006 |
| R2 | Licença e comportamento do Redis ≥ 7.4 vs Valkey com BullMQ, Chatwoot, Medusa | NÃO VERIFICADO (conhecimento geral, `../docs/tecnica/09` §3.1) | D12 | Compose parametrizado (KAM-001); validação em *staging* antes de `prod` |
| R3 | `uuidv7()` nativo no PG 18.6 | INDÍCIO (`../docs/tecnica/06` §4) | ADR-006 | KAM-005 verifica; *fallback* gerado na aplicação |
| R4 | Semântica S3 do SeaweedFS (*multipart*, URL assinada, *object lock*) e preços de S3 gerido em Angola | NÃO VERIFICADO (E4 §6) | D6, D1 | KAM-011 testa e regista; ADR de D6 com cotação ou a marca NÃO VERIFICADO |
| R5 | Local de alojamento do cofre, do S3 e da BD sem procedimento APD | Decisão aberta | D1, D9, ADR-008 | `destino.country` obrigatório (KAM-011); gate de transferência em KAM-069; nenhum dado real antes de D1/D9 |
| R6 | Papel da KAMBÁ perante a Lei 22/11 (responsável vs subcontratada) e retenção de `contact_endpoints` | NÃO VERIFICADO (E3 Q1) | D9 | `expira_at` parametrizável; valores «a confirmar por parecer» (KAM-104) |
| R7 | Prazo de retenção fiscal (CGT) para `orders_mirror`/`audit_log` | NÃO VERIFICADO (E3 §6) | D8 | Parâmetro por tenant; sem purga de registos de dinheiro até haver prazo |
| R8 | Três desenhos de `contacts` (01 §6.2, 03 §5.3, 06 §7.2) e de consentimento; chaves de entitlement e unidades monetárias incoerentes | Conflito documental | ADR-010 | Decisões registadas em KAM-007/008/009/022; propagar a `../docs/tecnica/01`, `03`, `06`, `02` |
| R9 | Intervalo de Node suportado pelo Medusa 2.21.x e adopção de Node 24 | NÃO VERIFICADO / INDÍCIO (`../docs/tecnica/09` §3.1) | D3 | Evidência em KAM-001; teste de arranque do Medusa no spike KAM-041 |
| R10 | Dependência de terceiro (Doppler) para segredos críticos | Risco MÉDIO (E4) | ADR-008 | Interface `SecretProvider`, exportação ensaiada (KAM-010) e caminho para OpenBao |
| R11 | Inversão de prioridades: KAM-012 e KAM-010 são P1 mas bloqueiam/servem tickets P0 (KAM-028; KAM-008, KAM-013, KAM-016) | Defeito do backlog | — | Executar ambos no início da Fase 0; ver sugestão ao responsável de produto |
| R12 | O publicador de instância única é ponto único de falha do EVT | Risco aceite no Piloto | ADR-009 | Réplica em espera por *advisory lock*, alerta de atraso do outbox; Kafka/NATS só na escala |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

---

## KAM-139 — Variantes vivas em `../docs/tecnica/` fora das 12 do KAM-111 (dívidas do gate 3b)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-111 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/02_Dicionario_de_Dados_Canonico.md` (§3.2, §3.3), `../ci/canon-allow.yaml` (secção `dividas`), `../docs/nomes-canonicos.md` (§6), `../docs/analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md` (B3), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§5.1, §6.1, §6.2), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§6.2), `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§6.1, §12), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§6.1, §10.2, §12), `specs/00_KAMBA_Carta.md` (§7, emenda E-01) |

### Contexto

O KAM-111 emendou `../docs/tecnica/` nas doze divergências que enumera, «e só nessas». O gate 3b que o mesmo ticket entregou varre os documentos à procura de **todos** os nomes da coluna «Substitui» do dicionário §3, e encontrou seis variantes vivas que nenhuma das doze cobre: **19 ocorrências** em cinco documentos. Duas são as que a emenda E-01 da Carta já registava (`kamba_ops`, `valor_max_pedido_kz`); três vêm do §3.3 (`preco_kz`, `'exato'`, `total_kz`); a sexta (`tenant_isolamento`) passou a variante com a emenda 1.5 do dicionário, do KAM-004.

Estão declaradas em `../ci/canon-allow.yaml` como **dívidas com prazo: vencem a 2026-11-10** (30 dias, *proposta*). A partir do dia seguinte o gate 3b fica vermelho em `main` e em todos os PR. Este ticket é o que as paga.

| Variante | Canónico (dicionário) | Onde | Ocorrências |
|---|---|---|---|
| `kamba_ops` | `kamba_batch` (§3.2) | `03` §5.5; `04` §6.2 | 1 + 2 |
| `valor_max_pedido_kz` | `valor_max_pedido_minor` (§3.2) | `02` §5.1, §6.1, §6.2 | 3 |
| `preco_kz` | `preco_minor` (§3.3) | `05` §6.1, §12; `06` §10.2 | 5 + 3 |
| `'exato'` | `'fixo'` (§3.3) | `05` §6.1; `06` §10.2 | 1 + 1 |
| `total_kz` | `total_minor` (§3.3) | `06` §6.1, §12 | 2 |
| `tenant_isolamento` | `tenant_iso` (§3.2, emenda 1.5) | `03` §5.5 | 1 |

**A de `04` §6.2 não é só nome.** O DDL de pagamentos faz `REVOKE ALL … FROM PUBLIC, kamba_app, kamba_ops`: revoga de um papel que não existe, e essa instrução falha num PostgreSQL real. Tem de estar corrigida antes de o KAM-053 copiar o DDL.

**As de `preco_kz` e `total_kz` mudam a unidade, não só o nome.** O dicionário §2 fixa dinheiro em unidade menor inteira; os documentos escrevem Kz inteiros (`max_preco_kz = 250000`, `preco_kz int`). Trocar o nome sem rever os valores e os tipos (`int` → `bigint`) deixaria os exemplos errados por um factor de 100.

### Objectivo

Substituir as 19 ocorrências pelas formas canónicas, com as unidades revistas onde a troca as altera, e retirar as nove entradas de `dividas` de `../ci/canon-allow.yaml`.

### Critérios de Aceitação

- [ ] As 19 ocorrências da tabela estão corrigidas; `python -m canon_lint check` reporta **0 dívidas** e a secção `dividas` de `../ci/canon-allow.yaml` está vazia (`dividas: []`).
- [ ] Onde a troca muda a unidade (`preco_kz`, `total_kz`, e os derivados `max_preco_kz`, `min_preco_kz`, `alvo_preco_kz`, `mediana_kz`, `receita_paga_kz` que as acompanham), os valores de exemplo, os tipos SQL e o texto à volta ficam coerentes com «unidade menor inteira + `currency`» (dicionário §2). Os derivados não são variantes do §3: decide-se e escreve-se, por cada um, se muda de nome ou fica.
- [ ] `04` §6.2 deixa de referir um papel inexistente: `REVOKE`/`GRANT` usam os papéis do dicionário §3.2.
- [ ] O exemplo `registry/vendedor.yaml` de `02` §5.1 passa o `canon_lint` como ficheiro do registo, salvo pelas *tools* que ainda não têm extensão — listadas no PR.
- [ ] Cada documento tocado regista a emenda no seu «Controlo de versões» com referência a este ticket.
- [ ] Nenhuma entrada nova em `historicas` nem em `dividas`: uma ocorrência que não se corrija volta para quem escreveu o ticket, com a razão.

### Detalhes Técnicos

- **Componentes:** documentação (`../docs/tecnica/02`, `03`, `04`, `05`, `06`) e `../ci/canon-allow.yaml`. Sem código de *runtime*.
- **O gate é o teste.** Corrigir uma ocorrência sem actualizar a contagem em `../ci/canon-allow.yaml` falha o gate 3b («N ocorrências, e o ficheiro declara M»); retirar a entrada sem corrigir também. A ordem natural é documento a documento, entrada a entrada.
- **Fora de âmbito:** as divergências estruturais que não são variantes de nome (**KAM-140**); as contradições do próprio dicionário (**KAM-141**); o DDL real das tabelas de dinheiro (KAM-053).

### Testes Requeridos

- `make ci-3b` verde com `dividas: []`.
- `make ci-3` verde (referências cruzadas dos documentos tocados).
- Revisão: pesquisa das seis variantes em `../docs/tecnica/` antes e depois, anexa ao PR.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Revisto por ≥ 1 revisor e pelo Responsável de Produto (altera documentos de desenho).
- [ ] Documentação actualizada: `../docs/nomes-canonicos.md` §6 (tabela das dívidas retirada) e `../docs/ci.md` §3 (gate 3b sem dívidas); Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-139 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-139), ci/canon-allow.yaml (secção `dividas`) e docs/nomes-canonicos.md §6.
Objectivo: pagar as 19 dívidas do gate 3b antes de 2026-11-10 — a partir daí o gate fica vermelho em main.
- Corre `cd tools && python -m canon_lint --root .. check` antes de tocar em nada: tem de dizer 9 dívidas, 19 ocorrências.
- Documento a documento: corrige as ocorrências e retira a entrada correspondente de ci/canon-allow.yaml. O gate
  falha se a contagem declarada não bater com a do documento, nos dois sentidos.
- `preco_kz` e `total_kz` mudam a UNIDADE (Kz inteiros → unidade menor): revê valores de exemplo e tipos SQL.
- `04` §6.2 revoga de um papel que não existe (`kamba_ops`): usa os papéis do dicionário §3.2.
Não expandas escopo: divergências estruturais são o KAM-140; contradições do dicionário são o KAM-141.
Não acrescentes entradas a `historicas` nem a `dividas`. Abre PR com o template do §7.
```

---

## KAM-140 — Divergências de `../docs/tecnica/` que o KAM-111 encontrou e não enumera

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-111 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/02_Dicionario_de_Dados_Canonico.md` (§3.1, §3.2, §3.4, §3.5), `../docs/nomes-canonicos.md` (§6), `../docs/analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md` (m9), `../docs/analises/ANALISE-03-KAM-003-schema-platform.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.2, §7.1), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§5.1), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§2, §5.2, §5.3, §6.2), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§2, §7), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.3), `../docs/tecnica/07_Geo_Logistica_Federada.md`, `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.1), `../docs/tecnica/10_Onboarding_Governanca.md` (§15.1) |

### Contexto

O critério 2 do KAM-111 diz que o seu *diff* toca só as linhas das doze divergências e que «qualquer outra divergência encontrada vira ticket `fix`». Este é esse ticket para as divergências que **não são variantes de nome** — e que por isso o gate 3b, que nos documentos só procura nomes da coluna «Substitui», não vê. Vieram de três sítios: da execução do KAM-003, da execução do KAM-111 e da sua revisão adversarial.

| # | Divergência | Onde | Origem |
|---|---|---|---|
| 1 | DDL de `tenant_channels` com três estados (`ativo`, `pausado`, `revogado`) e colunas `persona`, `canal`, `coexistencia`, contra o de `01` §7.1 — que é o implementado na revisão `0001` e o do dicionário §3.2 | `03` §5.2 | KAM-003 |
| 2 | `contacts` e `contact_endpoints` continuam com formas diferentes em dois documentos (três versões passaram a duas); em `03` §5.3 `contact_endpoints` ficou sem chave primária, `finalidade` e `expira_at` aplicam-se também às linhas de BSUID, e a nota (c) refere uma unicidade que já não está no DDL | `01` §6.2, `03` §5.3 | KAM-111 (D-01), revisão |
| 3 | `contacts.consentimento jsonb`: uma quarta forma de guardar consentimento, fora de `consent_event` | `03` §5.3 | KAM-111 |
| 4 | Campos e finalidades de `consent_event` diferentes entre si e do dicionário §3.1 (`purpose`/`finalidade`, `accepted`/`granted`/`estado`, `servico` contra `transaccao`) | `01` §6.2, `06` §7.3, `08` §8.1 | KAM-111 (D-02 trocou só o nome da tabela) |
| 5 | `payment.confirmed` descrito como o único evento que faz avançar a encomenda | `03` §2 e §6.2, `04` §2 e §7 | KAM-111 (D-05 lista só três secções) |
| 6 | `registry/servicos.yaml` de exemplo subscreve só `payment.confirmed`; o dicionário §3.5 diz que subscreve os dois eventos de pagamento | `02` §5.1 | KAM-111 |
| 7 | Estados do tenant enumerados sem `restrito` | `07` (a linha que enumera os estados do tenant) | revisão (D-08 não lista o `07`) |
| 8 | A tabela de transições não tem linhas próprias para `restrito → ativo` e `restrito → suspenso` (estão dentro da célula de `ativo → restrito`) | `10` §15.1 | revisão |
| 9 | O diagrama Mermaid de `10` §15.1, alterado pelo KAM-111, nunca passou por um *parser* | `10` §15.1 | KAM-111 |

Enquanto o KAM-008 (identidade), o KAM-022 (consentimento) e o KAM-053 (ledger) não forem executados, estes documentos são a única fonte de desenho — e o executor de cada um vai lê-los.

### Objectivo

Resolver as nove divergências da tabela contra o dicionário, uma a uma, com a decisão escrita em cada caso: emenda ao documento, ou emenda ao dicionário quando for o dicionário que está errado (essa parte faz-se no KAM-141).

### Critérios de Aceitação

- [ ] Cada linha da tabela tem uma disposição escrita no PR: **emendada** (com o documento e a secção), ou **devolvida** ao KAM-141 por ser o dicionário que tem de mudar, com a razão.
- [ ] Depois das emendas, `contacts`, `contact_endpoints` e `tenant_channels` têm **um** DDL de referência em `../docs/tecnica/`, e os outros documentos remetem para ele em vez de o repetirem.
- [ ] `consent_event` tem os mesmos campos e as mesmas finalidades nos três documentos, e são os do dicionário §3.1 — ou o dicionário é emendado no KAM-141 e este critério cita a emenda.
- [ ] Os dois diagramas Mermaid de estado do tenant (`00` §6.2 e `10` §15.1) passam por um *parser*, com o comando registado.
- [ ] Cada documento tocado regista a emenda no seu «Controlo de versões».
- [ ] O gate 3b continua verde, e nenhuma destas emendas introduz uma variante: `make ci-3b`.

### Detalhes Técnicos

- **Componentes:** documentação. Sem código de *runtime*.
- **Precedência:** o dicionário prevalece sobre `../docs/tecnica/` (dicionário §1); onde a implementação já existe (revisão `0001`, inventário de `db/tests/test_inventario.py`), ela é evidência de qual das versões foi a escolhida, não a fonte.
- **O que o lint não vê, e porquê:** nos documentos o gate 3b só tem o nível 1. Um DDL errado num bloco de código de um documento não é verificado como DDL; alargar o lint aos blocos de código dos documentos está **fora de âmbito** (reprovaria centenas de nomes de tabelas ainda não canónicas) e, se for desejável, é ticket próprio.
- **Fora de âmbito:** as variantes de nome (**KAM-139**); as contradições do dicionário (**KAM-141**); escrever o DDL final de `contacts` (KAM-008), de consentimento (KAM-022) e do ledger (KAM-053).

### Testes Requeridos

- `make ci-3` e `make ci-3b` verdes.
- *Parser* de Mermaid sobre os diagramas tocados.
- Revisão: uma linha por divergência da tabela, com o «antes» e o «depois».

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Revisto por ≥ 1 revisor e pelo Responsável de Produto.
- [ ] Documentação actualizada: `../docs/nomes-canonicos.md` §6 (as linhas resolvidas saem); Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-140 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-140), docs/nomes-canonicos.md §6 e docs/analises/ANALISE-05 (m9).
Objectivo: resolver as nove divergências de docs/tecnica/ que o KAM-111 encontrou e não podia corrigir.
- Uma disposição por linha da tabela: emendada (onde), ou devolvida ao KAM-141 (porquê).
- O dicionário prevalece. A revisão 0001 e o inventário de db/tests são evidência da versão escolhida.
- Um DDL de referência por tabela; os outros documentos remetem para ele.
- Passa os diagramas Mermaid que tocares por um parser e regista o comando.
Não expandas escopo: variantes de nome são o KAM-139; emendas ao dicionário são o KAM-141; o DDL final é do
KAM-008, KAM-022 e KAM-053. Abre PR com o template do §7.
```

---

## KAM-141 — Contradições do dicionário canónico encontradas pelo gate 3b

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-111 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/02_Dicionario_de_Dados_Canonico.md` (§2, §3.1, §3.2, §3.4, §3.5, §3.7, §5, §6), `../docs/nomes-canonicos.md` (§6), `../docs/analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md` (B2, M2, n2), `../ci/canon-lint.yaml` (`dominios_so_no_registo`), `../tools/canon_lint/cli.py` (`SEM_FORMA_DE_NOME`), `specs/00_KAMBA_Carta.md` (§6 ponto 4) |

### Contexto

O gate 3b lê o dicionário por máquina, e ao lê-lo encontrou sítios onde o dicionário **se contradiz** ou **não diz** o que os tickets assumem. Não foram resolvidos no KAM-111, cujo âmbito exclui «reescrever o dicionário (só por emenda)»: cada um é uma escolha entre duas afirmações do canon, e essa escolha é de quem aprova emendas (dicionário §5–§6; Carta §6 ponto 4).

| # | Achado | Consequência hoje |
|---|---|---|
| 1 | `manual_max_minor` está na coluna do nome **e** na coluna «Substitui» da linha «Entitlement (chaves)» (§3.2) | o gate trata-o como canónico e imprime um aviso em cada execução |
| 2 | `currency` não está no §3, só no §2; o D-03 do KAM-111 dá `valor_minor` + `currency` como forma canónica «(§3.4)» | o gate recusa `currency` como coluna e como campo de evento; a *fixture* positiva do D-03 não o tem |
| 3 | O §3.1 põe `bsuid_hmac` em `contact_endpoints`; o KAM-008 pede `lookup_hmac` e `hmac_kid` em `contacts` e o papel `kamba_identity`, que o §3.2 não lista | o DDL do KAM-008, escrito como o ticket manda, é recusado pelo gate |
| 4 | `authn_method` ∈ {`hmac`, `manual`, `consulta`} no §3.4; `../docs/tecnica/04` §6.2 escreve `('hmac_sha256','status_pull','humano_auditado','sistema')` | o DDL do KAM-053, copiado do documento, é recusado pelo gate |
| 5 | O envelope do §3.5 tem nove campos; o de `../docs/tecnica/06` §4 tem mais seis e põe `seq` dentro de `agregado` | cada campo a mais num *schema* do KAM-005 precisa de extensão |
| 6 | O §3.7 dá `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`}; o §3.2 diz que `entitlements.modulo` tem `CHECK` de forma e não de domínio, e `../docs/tecnica/02` §5.1 usa `modulo: vendedor` | a política do gate declara que esse domínio só vale no registo (`dominios_so_no_registo`) |
| 7 | O cabeçalho do dicionário diz «Versão 1.0»; o §6 vai na 1.4 | — |
| 8 | O critério 6 do KAM-111 pede 12 *fixtures* negativas e 12 positivas; D-07 e D-09 não têm forma de nome em nenhuma das três superfícies | a caixa está por marcar; o canário do gate fixa 10 + 10 no código |
| 9 | O nível 2 do gate aceita um nome do §3 em qualquer posição de tabela, coluna, valor, campo ou parâmetro: o §3 não diz o **tipo** de cada nome | medido na revisão adversarial; ver `../docs/nomes-canonicos.md` §1 |

### Objectivo

Decidir cada linha da tabela por emenda ao dicionário (ou ao ticket que o contradiz), e deixar o gate 3b sem avisos de contradição e sem a excepção de `dominios_so_no_registo`.

### Critérios de Aceitação

- [ ] Cada linha da tabela tem uma decisão escrita: emenda ao dicionário (linha nova no §6, marcada *proposta* até ratificação), emenda ao ticket contradito, ou «fica como está» com a razão.
- [ ] `python -m canon_lint check` não imprime nenhum «aviso: contradicao no dicionario».
- [ ] `currency` passa o gate como coluna e como campo de evento **por estar no §3**, e a *fixture* positiva do D-03 passa a tê-lo.
- [ ] As linhas 3 e 4 ficam decididas **antes** de o KAM-008 e o KAM-053 começarem: o dicionário e o ticket (ou o documento) dizem o mesmo, e um DDL escrito como o ticket manda passa o gate.
- [ ] A linha 8 fica decidida por quem escreveu o critério: ou o critério passa a «uma *fixture* por divergência que tenha forma de nome», ou diz-se que forma têm D-07 e D-09. Em qualquer dos casos, `SEM_FORMA_DE_NOME` em `../tools/canon_lint/cli.py` e a caixa do KAM-111 ficam coerentes com a decisão.
- [ ] A linha 9 fica decidida: ou o dicionário passa a dizer o tipo de cada nome (e o gate passa a aceitar por tipo), ou regista-se que o nível 2 por tipo não é requisito, com a taxa medida.
- [ ] `canon/dicionario.yaml` é regenerado (`make dict-export`) e o *diff* está no PR: é a lista do que o gate passa a aceitar e a recusar.

### Detalhes Técnicos

- **Componentes:** `specs/02_Dicionario_de_Dados_Canonico.md`, `canon/dicionario.yaml` (gerado), `ci/canon-lint.yaml`, e os blocos dos tickets que a decisão alterar.
- **Uma emenda ao dicionário tem alcance.** Um nome que entre na coluna «Substitui» passa a falhar em todas as superfícies, incluindo `../docs/tecnica/`. O `git diff` de `canon/dicionario.yaml` mostra-o antes de fundir.
- **Fora de âmbito:** corrigir `../docs/tecnica/` (**KAM-139**, **KAM-140**); reescrever o dicionário para além das linhas da tabela.

### Testes Requeridos

- `make ci-3b` verde, sem avisos de contradição.
- O teste que fixa o conjunto de variantes (`tools/dict_export/tests/test_exportar.py`) actualizado à mão, linha a linha, com a emenda.
- *Fixture* positiva do D-03 com `currency`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Cada emenda ao dicionário aprovada pelo Arquitecto de Plataforma e registada no §6; revisto por ≥ 1 revisor.
- [ ] Documentação actualizada: `../docs/nomes-canonicos.md` §6 (as linhas decididas saem); Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-141 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-141), specs/02_Dicionario_de_Dados_Canonico.md (§3, §5, §6) e
docs/nomes-canonicos.md §6.
Objectivo: decidir, por emenda, as nove contradições que o gate 3b encontrou no dicionário.
- NÃO decidas sozinho entre duas afirmações do canon: apresenta as alternativas e a consequência de cada uma, e
  regista quem aprovou. As emendas entram no §6 marcadas *proposta*.
- As linhas 3 (contacts/KAM-008) e 4 (authn_method/KAM-053) bloqueiam tickets do caminho crítico: primeiro essas.
- Depois de cada emenda: `make dict-export`, lê o diff de canon/dicionario.yaml, e actualiza à mão o teste que
  fixa o conjunto de variantes.
- A linha 8 (12 fixtures) é de quem escreveu o critério do KAM-111: não inventes fixtures para D-07 e D-09.
Não expandas escopo: docs/tecnica é KAM-139 e KAM-140. Abre PR com o template do §7.
```

---

## KAM-142 — Celeridade do processo de entrega: vagas, mutações em paralelo e menos colisões

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-002, KAM-004 |
| Bloqueia | KAM-143 |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../.claude/skills/agentic-engineering/SKILL.md`, `../docs/ci.md`, `db/mutacoes.py`, `Makefile` |

### Contexto

Nove tickets fechados, e o backlog passou de 127 para 141: cria-se trabalho quase ao ritmo a que se fecha. O grafo de dependências obriga a doze vagas sucessivas, e cada ticket de fundação levou perto de um dia. Parte desse tempo é rigor, e o rigor **fica** — o fundador decidiu (Outubro 2026) não o graduar por ticket nem cortar o backlog. A outra parte é trabalho repetido e espera, e é essa que este ticket corta:

1. **A prova por mutação corria em série e repetia tudo.** No KAM-004 foram 48 execuções da suite, uma a uma, cerca de duas horas — 30 delas sobre mutações que já estavam provadas.
2. **Dois tickets em paralelo colidiam sempre nos mesmos sítios.** As duas listas de suites escritas à mão no `Makefile` são um deles — e uma suite nova que ficasse fora delas não era corrida por ninguém (aconteceu com a `secrets_inventory` no KAM-010).
3. **Cada contradição de documentos virava ticket.** As revisões adversariais encontram sempre mais do que o ticket pede.
4. **Esperava-se por revisão humana que não existe.** O *ruleset* de `main` exige 0 aprovações.

### Objectivo

Encurtar o ciclo de um ticket sem lhe tirar verificação: correr em paralelo o que é independente, não repetir o que já está provado, e reduzir os pontos onde tickets paralelos colidem.

### Critérios de Aceitação

- [x] `db/mutacoes.py` aceita como filtro um **excerto do nome** da mutação, além da suite e do nome exacto; um filtro que não escolhe nenhuma mutação termina com código 2, e não com «0 não apanhadas».
- [x] As mutações correm em paralelo, cada uma no seu PostgreSQL descartável; o número vem de `KAMBA_MUTACOES_PARALELO` (omissão 4), um valor inválido é recusado **antes** de qualquer execução, e a linha de base verde continua obrigatória.
- [x] O `Makefile` descobre as suites de `tools/` pelo disco, nos dois alvos que as corriam por lista (`test-py` e `coverage-python`); uma descoberta vazia é erro.
- [x] `make test-py` corre as mesmas sete suites que corria antes desta alteração.
- [x] Existe `docs/dividas-documentais.md`, com a regra de uso, e a skill `agentic-engineering` manda para lá o que uma revisão encontrar fora do âmbito.
- [x] A skill `agentic-engineering` tem a secção de ritmo: vagas pelo grafo de dependências, merge com o CI verde, ficheiros partilhados declarados, mutações só das novas.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#20`. **Oito caixas marcadas, uma vazia.** A
revisão adversarial (um agente independente; 5 maiores, 15 menores, nenhum no
comportamento do código) está resumida abaixo — não tem documento de análise
próprio, porque todos os achados cabem nesta secção.

| CA | Estado | Evidência |
|---|---|---|
| 1 — filtro por excerto; filtro vazio dá código 2 | **satisfeito** | Corrido pela revisão: `downgrade da 0002` → 3 mutações, `guarda:` → 10, `RLS:` → 5; `xyz-nao-existe` → código 2. `resolvedor` atravessa as duas suites (6 + 3) e exige as duas linhas de base |
| 2 — paralelo; valor inválido recusado antes; linha de base obrigatória | **satisfeito** | 18 mutações em paralelo (3, 10 e 8 de cada vez): 18 apanhadas, com **as mesmas contagens de falhas e o mesmo primeiro teste** do registo em série da `ANALISE-07` §4 nas 15 comparáveis; nenhum contentor órfão. `0`, `abc`, vazio e `²` → código 2 antes da linha de base. Uma excepção numa execução conta como «PROVA INVALIDA» sem levar o relatório das outras. **Depois da entrega** (seguimento): a omissão passou a 8, provada com cinco mutações do catálogo apanhadas em paralelo; e uma falha por carga da máquina — que o revisor avisou que contaria como «apanhada» — passa a `PROVA INVALIDA`, com teste por sinal |
| 3 — suites descobertas pelo disco nos dois alvos; vazia é erro | **satisfeito** | `SUITES_DE_TOOLS` parte de `$(ROOT)` e só conta pastas com `test_*.py`; `test-py` e `coverage-python` dependem de `exige-suites`, que falha com a lista vazia e imprime as suites. A primeira versão usava um `$(error)` à cabeça que matava `make help` fora da raiz — corrigido |
| 4 — as mesmas sete suites | **satisfeito** | `make -n exige-suites` a partir de outro directório: `(7): canon_lint dict_export lint_arch lint_refs sbom scan_secrets secrets_inventory`. No *runner*, a cobertura do gate 4 é **idêntica** à do PR anterior (6456/7343 linhas, 76 ficheiros). O conjunto mínimo está preso por teste |
| 5 — `docs/dividas-documentais.md` com regra; a skill manda para lá | **satisfeito** | O ficheiro existe com quatro linhas. A revisão mostrou que a primeira versão da regra contradizia `specs/01` §6 («o que fica fora é ticket»): a regra ficou restrita a **resíduos textuais**, e `specs/01` §6 ganhou a excepção escrita (v1.1) |
| 6 — secção de ritmo na skill | **satisfeito** | Secção «Ritmo», com as contradições que a revisão apontou resolvidas por escrito: como se lê com «Proporcionalidade», como se aplica depois da lista de «Paralelismo», e «em `main`» a fazer as vezes de «`Done`». O script das vagas existe (`.claude/skills/agentic-engineering/scripts/vagas.py`) |
| DoD — todos os CA satisfeitos | **satisfeito** | Os seis acima |
| DoD — revisto por ≥ 1 revisor; testes verdes | **não satisfeito** | Testes verdes. **Zero revisores humanos**; a revisão adversarial é evidência, não é um revisor, e as correcções que motivou não foram revistas por uma segunda ronda |
| DoD — documentação; Conventional Commits | **satisfeito** | Skill, `specs/01` §6, `docs/ci.md`, `docs/dividas-documentais.md`, *docstring* de `db/mutacoes.py` |

#### O que a revisão encontrou e o que se fez

- **Corrigido:** a contradição com `specs/01` §6 e com duas secções da própria skill; a regra «só as mutações novas», que ignorava o caso em que muda o código mutado (ganhou a segunda condição e o modo `--aplicaveis`, sem Docker); a reciprocidade `Bloqueia` nos blocos do KAM-002 e do KAM-004; o `$(error)` que matava todos os alvos; a descoberta que aceitava `__pycache__` e pastas vazias; a falta de guarda por teste; `²` como paralelismo; a excepção que levava o relatório; três textos vizinhos desactualizados.
- **Registado como dívida** (`../docs/dividas-documentais.md`): o `Bloqueia` do KAM-002 sem KAM-131 a KAM-138, a tabela-resumo deste epic sem KAM-129 e KAM-130, e o cabeçalho do `INDICE.md`.
- **Não corrigido, e dito:** o filtro é sensível a maiúsculas e não tem modo de listar sem correr; sob muita carga um `lock_timeout` contaria como «apanhada» (não observado com dez em paralelo); a decisão do fundador de não graduar o rigor está na skill e neste bloco, **não na Carta**.

#### Seguimento, depois da entrega

A nota «sob muita carga um `lock_timeout` contaria como apanhada (não
observado)» era uma porta aberta: subir o paralelismo tornava a prova mais
fácil, que é o defeito que ela existe para apanhar. Fechada no ramo
`fix/KAM-142-mutacoes-mais-rapidas-e-carga`, com a medida que a motivou — a
lista completa do KAM-008 levou **3 h 24 min** em série, com 95 mutações. A
omissão passa a 8, `SINAIS_DE_CARGA` nomeia as falhas do servidor que não são
mutações apanhadas, e a classificação da saída passa a ter 16 testes
(`db/tests/test_mutacoes.py`) — um instrumento que mede testes também tem de
ser medido. A proposta de correr a lista inteira de noite, no GitHub, está
escrita e **não** foi aplicada: perde a garantia de que a lista estava verde no
momento do merge, e isso é decisão do fundador.

#### Não verificado

A lista inteira das 48 mutações em paralelo; `make` no Git Bash do Windows; o comportamento com Ctrl+C a meio.

### Detalhes Técnicos

- **Componentes:** transversal (processo e CI). Ficheiros: `db/mutacoes.py`, `Makefile`, `.claude/skills/agentic-engineering/SKILL.md`, `docs/dividas-documentais.md`.
- **O que este ticket não faz, por decisão:** não cria níveis de rigor por ticket, e não corta o backlog ao caminho do Piloto.
- **O preço da descoberta, e como se paga.** Uma lista escrita à mão rebentava quando uma suite desaparecia; uma descoberta deixa de a correr, calada. `tools/lint_arch/tests/test_makefile.py` prende o conjunto mínimo das sete, exige que cada suite seja importável e recusa uma pasta de testes que a descoberta não veja.
- **O que fica por fazer:** `esperados=N` no resumo do `ci.yaml` continua escrito à mão — é um guarda deliberado contra um `needs` retirado em silêncio, e calculá-lo a partir dos próprios `needs` anulava-o. As tabelas de controlo de versões continuam a colidir entre tickets paralelos; resolve-as quem integra.

### Testes Requeridos

- `python db/mutacoes.py <python> "<excerto>"` sobre três mutações conhecidas: três apanhadas, com linha de base verde.
- Filtro sem correspondência e `KAMBA_MUTACOES_PARALELO=0`: código 2.
- `make test-py` num contentor: sete suites, todas verdes; `make ci` verde no *runner*.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes.
- [x] Documentação actualizada; Conventional Commits.

### Handoff para Claude Code

```text
És o executor do ticket KAM-142 da KAMBÁ. Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-142).
Objectivo: encurtar o ciclo de um ticket sem lhe tirar verificação.
- db/mutacoes.py: filtro por excerto do nome, execução em paralelo, recusa de filtro vazio.
- Makefile: suites de tools/ descobertas pelo disco; descoberta vazia é erro.
- docs/dividas-documentais.md e a secção de ritmo na skill agentic-engineering.
Não expandas escopo: sem níveis de rigor por ticket, sem cortar o backlog, sem mexer em `esperados`.
Abre PR com o template do §7.
```

---

## KAM-143 — Prova por mutação completa como tarefa nocturna, e fatiada por *runner*

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-142 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` (§3, gate 8), `db/mutacoes.py`, `../.claude/skills/agentic-engineering/SKILL.md` («Ritmo»), bloco do KAM-142 |

### Contexto

A prova por mutação dos *gates* de base de dados cresce com cada ticket que toca em `db/`: 20 no KAM-003, 48 no KAM-004, **95 com o KAM-008**. Uma execução completa em série levou **3 h 24 min** nesta máquina (medido a 2026-10-12), e a regra da skill manda correr a lista inteira sempre que o diff toque num ficheiro que alguma mutação altera. O custo caía todo no relógio de quem esperava pelo PR, e o KAM-142 já tinha pago metade dele (paralelismo 8, filtro por excerto, sinais de carga).

O fundador decidiu (Outubro 2026) aplicar a outra metade: **no PR corre-se o que é novo; a lista inteira corre de noite, no GitHub.** A decisão foi tomada com o seu custo escrito — deixa de haver garantia de que a lista inteira estava verde no momento do merge.

**O número, datado.** As 95 mutações e as 3 h 24 min foram medidas a 2026-10-12 no ramo do KAM-008, que é onde a lista cresce para esse tamanho; em `main` a lista tem 48 e nunca teve 95. Citar «95» sem dizer onde é afirmar mais do que se verifica, e foi assim que entrou na primeira versão deste bloco.

### Objectivo

Tirar a prova completa do caminho dos PRs sem a deixar de correr, e sem que uma sobrevivente passe calada.

### Critérios de Aceitação

- [x] `db/mutacoes.py --fatia i/n` corre a i-ésima de n fatias da lista escolhida, alternadamente; as n fatias cobrem a lista **sem perder nem repetir** nenhuma mutação (teste); uma fatia vazia e uma fatia malformada saem com código 2.
- [x] Existe `.github/workflows/mutacoes.yaml`, agendado uma vez por noite e disparável à mão, que corre a lista inteira repartida por seis fatias, cada uma no seu *runner*.
- [x] **Não é um gate**: não corre em PRs, não entra nos `needs` do resumo do `ci.yaml` nem no `esperados`, e não bloqueia merge nenhum.
- [x] Antes de gastar horas, a tarefa confirma em segundos que todas as mutações ainda se aplicam (`--aplicaveis`); se alguma não se aplicar, as fatias não correm.
- [x] Uma sobrevivente, uma `PROVA INVALIDA` ou uma mutação não aplicável **abrem um *issue*** com a ligação para o registo; enquanto estiver aberto não se abre outro, e o corpo diz que não é um ticket do backlog e o que distingue os três resultados.
- [x] O relatório de cada fatia fica guardado como artefacto da execução.
- [x] O custo perdido pela decisão está escrito onde se decide (`../docs/ci.md` §3, no gate 8, e este bloco), e a skill diz que no PR correm as novas e a lista inteira corre de noite.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#30`. **Nove caixas marcadas, duas vazias** (9 +
2 = 11). A revisão adversarial **não aprovou** a primeira versão — 7 maiores, 11
menores — e três critérios só passaram a cumprir-se depois dela.

| CA | Estado | Evidência |
|---|---|---|
| 1 — `--fatia i/n` alternado, cobre sem perder nem repetir; vazia e malformada com código 2 | **satisfeito** | A revisão provou a cobertura por **enumeração exaustiva**: lista inteira e 10 listas filtradas, `n` de 1 a 100 cada, comparando identidades de objecto — zero perdas, zero repetições. Fatias equilibradas (`[8,8,8,8,8,8]`). Malformada e `--fatia` sem valor saíam com 2 **sem teste que o prendesse** (duas mutações da revisão sobreviviam): agora há, e a lista de formas recusadas inclui dígitos de largura total e árabes, que `int()` aceita e a guarda `isascii` recusa |
| 2 — tarefa agendada, disparável à mão, lista inteira em seis fatias | **satisfeito** | `.github/workflows/mutacoes.yaml`, validado com um analisador YAML real; `cron: 10 2 * * *` = 02:10 UTC = **03:10 em Luanda** (WAT, sem horário de verão), uma vez por noite; matriz `[1..6]`, um *runner* por fatia. Com filtro (execução à mão) corre tudo na fatia 1: com seis fatias, qualquer filtro curto deixava fatias vazias, e o teste manual que o próprio ticket exige **não podia passar** |
| 3 — não é um *gate* | **satisfeito** | Quatro provas independentes, feitas pela revisão: `on:` só `schedule` e `workflow_dispatch`; zero ocorrências de `mutac` em `ci.yaml` (a vigia que entrou depois chama-se `vigia-das-mutacoes` e **não** está nos `needs`); o resumo `gates do KAM-002` tem 9 `needs` e `esperados=9`, inalterado; `.github/rulesets/main.json` não o tem entre os 7 contextos exigidos |
| 4 — `--aplicaveis` antes das horas; sem ele as fatias não correm | **satisfeito** | `needs: aplicaveis`, *job* leve (só `setup-python`, biblioteca padrão). **O achado maior da revisão estava aqui:** `--aplicaveis` passado como *filtro* — que é o que a entrada do `workflow_dispatch` alimenta — fazia as seis fatias correrem a conferência de segundos e saírem **verdes, com zero mutações e zero linhas de base**. A opção só vale como primeiro argumento e sozinha; um posicional que comece por `--` é erro; e o código de saída de `aplicaveis()` passou a ter teste |
| 5 — sobrevivente, `PROVA INVALIDA` ou não aplicável abrem *issue*; um só de cada vez; o corpo diz que não é um ticket | **satisfeito** | `needs: [aplicaveis, fatias]` com `failure()` cobre também o caso de a conferência falhar. A revisão confirmou no repositório, sem escrever nada, que `gh issue list --label mutacoes` com a etiqueta inexistente devolve `0` e sai 0 — a guarda funciona na primeira noite. O título dizia «há sobreviventes» em casos em que não há (a conferência a falhar significa que as fatias nem correram): passou a «não ficou verde», e o corpo começa por mandar ver qual o *job* que falhou. A etiqueta passa a criar-se só se faltar, em vez de criar e engolir o erro |
| 6 — relatório de cada fatia como artefacto | **satisfeito** | `upload-artifact@v4` com `if: always()` e nome único por fatia; o `tee` cria o ficheiro antes de o Python poder rebentar. `set -o pipefail` preserva o código de saída do Python através do `tee` |
| 7 — o custo escrito onde se decide, e a skill a dizer PR/noite | **satisfeito** | O texto está em `../docs/ci.md` §3, no *gate* 8. **Cinco documentos diziam §5** — que é «Excepções (*waivers*)» —, incluindo este critério e o corpo do *issue*: corrigidos. A skill diz qual parágrafo substitui o outro e quem decide correr a lista à mão |
| DoD — todos os CA satisfeitos | **satisfeito** | Os sete acima |
| DoD — revisto por ≥ 1 revisor; testes verdes | **não satisfeito** | Testes verdes: **33** em `db/tests/test_mutacoes.py`; `lint_refs`, `canon_lint`, `scan_secrets`, `lint_arch`, `supply_chain` conformes. **Zero revisores humanos** — a revisão adversarial é evidência, não é um revisor, e as correcções que ela motivou não foram revistas por uma segunda ronda |
| DoD — documentação; Conventional Commits | **satisfeito** | `../docs/ci.md` (v1.13), a skill, `.github/mutacoes-alerta.md`, este bloco. A reciprocidade `Bloqueia` do KAM-142 estava em falta e foi corrigida |
| DoD — custo em minutos de CI medido; o resultado tem quem o leia | **não satisfeito** | O custo **não foi medido**: a tarefa nunca correu no GitHub, e a estimativa da revisão (5–10 min por fatia com a lista de 48; 10–15 min com a de 110 do ramo do KAM-008) é cálculo, não medição. Quem lê: o *issue* existe e a vigia dá pela noite que não correu, mas nenhum dos dois foi exercitado em execução real |

#### O que a revisão encontrou, e o que se fez

Sete maiores. **Corrigidos:** o `--aplicaveis` como filtro a dar a prova por feita (o mais grave — fazia a tarefa nocturna inteira sair verde sem correr nada); as cinco referências a `docs/ci.md` §5; a ausência de testes ao **código de saída** (seis das sete mutações da revisão estavam aí, e uma delas reintroduzia exactamente o defeito que o seguimento do KAM-142 corrigiu: contar só o `SOBREVIVEU` como não-apanhada); a noite que não corre, que nenhum alarme dava — entrou a vigia não-bloqueante em `ci.yaml`; o teste manual com filtro curto, que era garantidamente vermelho; o diagnóstico de uma linha de base vermelha, que mostrava doze linhas de arranque do PostgreSQL e cortava a causa.

**Corrigido com honestidade, não com código:** «95 mutações, 3 h 24 min» não se reproduz em `main`, que tem 48 — o número é do ramo do KAM-008, e passou a estar datado e atribuído onde é citado.

Menores corrigidos: reciprocidade `Bloqueia`; título e abertura do *issue*; os prazos dos *jobs* (90 min por fatia em vez de 300, e 10 min nos dois *jobs* de segundos); as fatias deixam de correr o `make bootstrap` inteiro — só Python e as dependências das migrações, poupando minutos de Node em seis *runners* por noite; a justificação do `concurrency`, que era factualmente falsa; a criação da etiqueta a engolir qualquer erro; a guarda `isascii` sem teste; a contradição dentro da secção «Ritmo» da skill; e **a frase «no PR correm-se as mutações novas» descrevia disciplina humana, não maquinaria** — `make ci-8` passa a correr `--aplicaveis`, que leva segundos e só usa a biblioteca padrão.

**Declarado, não corrigido:** `--fatia` repetido duas vezes na linha de comandos é apanhado por acidente (o segundo torna-se filtro e não escolhe nada, saindo com 2); não há *lint* de *workflows* no repositório, pelo que **nenhuma mutação ao YAML é detectável** — a revisão preparou quatro e nenhuma seria apanhada por nada.

#### Não verificado

A tarefa a correr no GitHub: o alerta a disparar, a desduplicação do *issue*, a subida dos artefactos, o comportamento do `concurrency` com execuções em fila, o tempo de parede por fatia, e a vigia a passar de vermelha a verde depois da primeira noite. Como as seis fatias se reequilibram quando o ramo do KAM-008 fundir. A lista inteira de mutações numa execução fatiada.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `db/mutacoes.py`, `db/tests/test_mutacoes.py`, `.github/workflows/mutacoes.yaml`, `.github/mutacoes-alerta.md`, `../docs/ci.md`, `../.claude/skills/agentic-engineering/SKILL.md`.
- **Fatias alternadas, não em blocos.** As mutações de um ticket estão juntas na lista e não custam todas o mesmo — as de identidade semeiam mil contactos. Em blocos, uma fatia levava todas as caras e as outras esperavam por ela. O preço é cada fatia correr as duas linhas de base.
- **Dois níveis de paralelismo.** Seis *runners* (fatias) × duas execuções por *runner* (`KAMBA_MUTACOES_PARALELO=2`): uma máquina de dois núcleos com mais do que isso esgota ligações, e isso não acelera nada — invalida a prova.
- **A entrada do `workflow_dispatch` não é interpolada no `run`.** Vai por variável de ambiente: interpolar texto de quem dispara dentro de um *shell* é injecção de comandos.
- **O corpo do *issue* é um ficheiro do repositório** (`.github/mutacoes-alerta.md`), e não uma cadeia dentro do *shell*: cada acento grave do Markdown numa cadeia entre aspas era substituição de comando, e o texto do alerta revê-se em *diff* como qualquer outro documento.
- **Fora de âmbito:** reutilizar uma base de dados entre mutações (pouparia mais do que tudo o resto, e uma base suja da mutação anterior faz a seguinte falhar — contando como «apanhada», que é o defeito que esta prova existe para apanhar); um canal de alerta fora do GitHub; a prova por mutação das ferramentas de `tools/`, que tem corredor próprio.

### Testes Requeridos

- Unit: as n fatias cobrem a lista sem perdas nem repetições, para vários n; fatias equilibradas; fatia vazia e malformada com código 2; a opção não se confunde com o filtro.
- Integração: uma fatia real contra PostgreSQL, com linha de base verde.
- A tarefa corrida à mão (`workflow_dispatch`) com um filtro curto, antes de se confiar na noite.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes.
- [x] Documentação actualizada; Conventional Commits.
- [ ] **Custo e observabilidade** — o custo em minutos de CI está medido e registado, e o resultado tem quem o leia.

### Handoff para Claude Code

```text
És o executor do ticket KAM-143 da KAMBÁ. Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-143).
Objectivo: a prova por mutação completa sai do caminho dos PRs e corre de noite, sem deixar de correr.
- `--fatia i/n` em db/mutacoes.py, alternadamente, com teste de cobertura sem perdas.
- .github/workflows/mutacoes.yaml: agendado, seis fatias, `--aplicaveis` primeiro, issue no fim.
- NÃO é um gate: fora do ci.yaml, fora do `esperados`, não corre em PRs.
Não expandas escopo: não reutilizes bases entre mutações; não crias canal de alerta fora do GitHub.
Abre PR com o template do §7.
```

---

## KAM-144 — Reciprocidade `Dependências`↔`Bloqueia`: os oito tickets que o KAM-002 não declara bloquear

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | — |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/INDICE.md` (§1, §3.1, §4), bloco KAM-002 deste epic, bloco KAM-129 deste epic (critério 9, busca G5), bloco KAM-138 deste epic, `../.claude/skills/agentic-engineering/SKILL.md` (§5, «SINCRONIA MESTRE↔EPICS»), `README.md` |

### Contexto

O grafo de dependências do backlog vive em dois campos de cada bloco de ticket: `Dependências` e `Bloqueia`. São a mesma aresta vista dos dois lados, e só valem se concordarem — é o campo `Bloqueia` que diz a quem lê um ticket fundido o que é que ele acaba de desbloquear, e é dele que depende qualquer decisão de paralelismo (`../.claude/skills/agentic-engineering/scripts/vagas.py` lê o grafo, não a prosa).

**O defeito, medido.** Oito tickets declaram `Dependências | KAM-002` e **nenhum** entra no `Bloqueia` do KAM-002:

```text
KAM-131, KAM-132, KAM-133, KAM-134, KAM-135, KAM-136, KAM-137, KAM-138
```

O `Bloqueia` do KAM-002 dizia `KAM-004, KAM-030, KAM-067, KAM-068, KAM-078, KAM-111, KAM-142` — sete arestas, quando são quinze. Apurado a 2026-10-12 ao remedir os critérios do KAM-129 contra `main` em `f4c7e3d`: **143 blocos, 8 falhas de reciprocidade**, contra as 0 que a entrega do KAM-129 registou. É uma regressão, não um defeito antigo: os oito tickets nasceram depois (versões 1.5 e 1.6 do `specs/INDICE.md` §7) e nenhuma das duas inscrições fechou o outro lado da aresta.

**É o modo de falha que o próprio KAM-129 previu por escrito.** O seu critério 9 diz: «Um ticket novo que declare `Dependências | KAM-NNN` sem entrar no `Bloqueia` do KAM-NNN satisfaz o critério de sincronia pela razão errada; foi o que aconteceu na primeira versão deste ticket, e é por isso que G5 existe.» Oito tickets depois, aconteceu exactamente isso. O critério violado é do KAM-129; o KAM-002 é apenas o bloco onde a falha se materializa.

**Este ticket não declara dependência, e isso é uma decisão.** A primeira versão declarava `Dependências | KAM-129`, por o defeito ter sido apurado a remedir o seu critério 9. A revisão adversarial devolveu a escolha, e a medição dá-lhe razão: **nada da entrega do KAM-129 é necessário para acrescentar oito IDs a um campo `Bloqueia`**. O precedente do conjunto é ordem técnica, não proveniência — o KAM-130 precisa de os caminhos do KAM-128 terem aterrado, o KAM-139 a KAM-141 precisam da saída do gate 3b do KAM-111, o KAM-143 precisa do `--fatia` do KAM-142. Inscrever `KAM-129` punha no grafo uma aresta que não existe, e fazia o KAM-129 «bloquear» algo que não bloqueia — **num ticket cuja tese é que o grafo diga a verdade**. A proveniência fica em prosa, onde não mente a nenhum leitor automático; a reciprocidade do ticket é `—`↔`—`, e a verificação conta-a como conta as outras.

**Porque a sincronia mestre↔epics não apanha isto.** A verificação de sincronia compara, entre a linha do `specs/INDICE.md` §4 e o bloco do epic, **só os campos que existem nos dois lados**: tipo, estimativa, prioridade, fase e dependências. O §4 **não tem coluna `Bloqueia`**. A reciprocidade é, portanto, invisível à sincronia por construção: o `Bloqueia` só se verifica contra os `Dependências` dos outros blocos, nunca contra o mestre. Uma passagem de sincronia a dar zero divergências continua a dar zero com estas oito falhas de pé.

**Porque ninguém notou.** A reciprocidade é hoje um *teste requerido* escrito em prosa — a busca G5 do KAM-129 — e não um *gate*. O **KAM-138** («Gate 3c: lint de coerência do backlog (mestre ↔ epics)») está aberto e **não implementado**: não existe `tools/lint_backlog`, nenhum ficheiro de `tools/` contém a palavra `Bloqueia`, e não há alvo `make ci-3c`. O CI de `main` está verde com as oito falhas, e continuará verde com as próximas oito.

### Objectivo

Pôr as quinze arestas que entram no KAM-002 a dizer o mesmo dos dois lados, com a contagem medida por máquina antes e depois, e deixar escrito que a correcção de dados não fecha a causa.

### Critérios de Aceitação

- [x] O `Bloqueia` do KAM-002 passa a conter os quinze tickets que dele dependem, em ordem crescente de ID: `KAM-004, KAM-030, KAM-067, KAM-068, KAM-078, KAM-111, KAM-131, KAM-132, KAM-133, KAM-134, KAM-135, KAM-136, KAM-137, KAM-138, KAM-142`.
- [x] A verificação de reciprocidade sobre os 11 epics devolve **0 falhas** nos dois sentidos (`A` depende de `B` sem `B` bloquear `A`, e `B` bloqueia `A` sem `A` depender de `B`), com o número no PR. **Exige-se o número, não a leitura**: o defeito existe precisamente porque ninguém contou.
- [x] A verificação procura **mais do que estas oito** — corre sobre todo o grafo, não sobre o bloco corrigido — e o PR diz se corrigir o KAM-002 expôs arestas que estavam encobertas.
- [x] Sincronia mestre↔epics, ciclos, prioridades invertidas, fases invertidas, unicidade de blocos e contagens derivadas continuam a 0 falhas depois da correcção (medidas antes, para que a comparação exista).
- [x] Este ticket entra **nos dois lados**: linha em `specs/INDICE.md` §4 (sub-tabela do EPIC-01) e bloco `## KAM-144 — ` neste epic, com tipo, estimativa, prioridade, fase e dependências iguais — e com a **sua própria reciprocidade correcta**: declara `Dependências | —` e `Bloqueia | —`, e a verificação conta-o entre os 144 blocos em vez de o excluir.
- [x] As contagens derivadas acompanham: `specs/INDICE.md` §1 (total e intervalo) e §3.1 (intervalo e total do EPIC-01, e o TOTAL).
- [x] **A correcção de dados não fecha a causa, e o ticket di-lo.** O bloco regista que a causa é o KAM-138 não estar implementado, e regista a recomendação sobre a sua prioridade em texto, não por implicação.
- [x] `specs/EPIC-01_Fundacoes_Dados.md` e `specs/INDICE.md` registam a emenda no respectivo «Controlo de versões».

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#44`, ramo `fix/KAM-144-reciprocidade-bloqueia`,
sobre `main` em `f4c7e3d`. **Quinze caixas marcadas, uma vazia** (15 + 1 = 16).
A correcção e o ticket vão no mesmo PR: este bloco abre o ticket e a mesma
alteração paga a dívida de dados, pelo que as caixas marcam-se aqui e não num PR
posterior.

**A linha de base, medida antes de tocar em nada.** Sem ela não há como distinguir
«corrigi oito» de «corrigi oito e estraguei três»:

```text
antes  (main f4c7e3d)   143 blocos, 143 linhas no mestre, 8 falhas  -> todas G5
depois                  144 blocos, 144 linhas no mestre, 0 falhas
2a passagem             144 blocos, 144 linhas no mestre, 0 falhas  (0 alteracoes)
```

| CA | Estado | Evidência |
|---|---|---|
| 1 — `Bloqueia` do KAM-002 com os quinze, em ordem crescente | **satisfeito** | Linha 193 do epic: `KAM-004, KAM-030, KAM-067, KAM-068, KAM-078, KAM-111, KAM-131, KAM-132, KAM-133, KAM-134, KAM-135, KAM-136, KAM-137, KAM-138, KAM-142` — **7 arestas → 15**, ordem crescente de ID conferida termo a termo. Os oito acrescentados são exactamente os oito que a medição nomeou; nenhum outro ID entrou |
| 2 — reciprocidade a 0 nos dois sentidos, com o número | **satisfeito** | O comando do pedido (143 blocos, 8 falhas em `main`) dá **144 blocos, 0 falhas**. A verificação larga confirma nos dois sentidos separadamente: `A` depende de `B` sem `B` bloquear `A` → 0; `B` bloqueia `A` sem `A` depender de `B` → 0. O segundo sentido é o que apanharia um `Bloqueia` inflacionado, e foi medido precisamente porque acrescentar oito IDs é a forma mais fácil de criar a falha simétrica |
| 3 — procura mais do que estas oito, sobre todo o grafo | **satisfeito** | A verificação corre sobre os **11 epics** e as **144 linhas** do §4, não sobre o bloco corrigido: 144 blocos lidos, **758** arestas conferidas — **379** em `Dependências` e **379** em `Bloqueia` (em `main` eram **379** contra **371** — as oito arestas declaradas de um só lado). A igualdade dos dois totais é **necessária e não suficiente**: a revisão construiu o contra-exemplo — trocar um ID dentro do `Bloqueia` mantém os dois totais iguais e cria duas falhas. A prova é a contagem nos dois sentidos, não a aritmética dos totais. **Estes três números foram corrigidos depois do *merge* do PR #44**, onde diziam 760, 380 e 380: eram a medição feita **antes** de a aresta `KAM-144`→`KAM-129` sair do grafo, e não reproduziam no *commit* fundido. É a terceira ocorrência da mesma classe de defeito neste ticket — ver o achado maior M1 — e a segunda que escapou a uma revisão. A lição está na linha do DoD das referências e vale para as duas: **um número que depende do texto remede-se depois de a última alteração ao texto estar feita**, e a retirada de uma aresta é uma alteração ao texto. **Corrigir o KAM-002 não expôs nenhuma aresta encoberta** — as 8 falhas de `main` tinham todas a mesma causa (o `Bloqueia` do KAM-002) e nenhuma mascarava outra, o que se vê por o número ter passado de 8 para 0 sem passagem intermédia por valor maior |
| 4 — sincronia, ciclos, prioridades, fases, unicidade e contagens a 0 | **satisfeito** | Medidos **antes** (todos a 0 em `main`, com as 8 de G5 como única falha) e **depois** (todos a 0). S1 sincronia mestre↔epics nos cinco campos comuns e existência nos dois lados; S2 ciclos por travessia em profundidade; S3 prioridade invertida; S4 fase invertida; S5 unicidade de blocos; S6 referências; S7 contagens derivadas. A linha de base a 0 é o que torna a comparação possível: sem ela, «0 falhas depois» não distinguiria correcção de coincidência |
| 5 — o ticket nos dois lados, com a sua própria reciprocidade correcta | **satisfeito** | Linha no §4 (sub-tabela do EPIC-01, depois do KAM-143) e bloco `## KAM-144 — ` neste epic; S1 confere `fix`/`S`/`P1`/`0` e dependências vazias nos dois lados. A reciprocidade do próprio ticket está fechada por não declarar aresta nenhuma — e **isso é medido, não assumido**: o bloco entra nos 144 que G5 percorre, e um `Dependências` ou `Bloqueia` que aqui aparecesse sem o outro lado contaria como falha. É a parte que a ironia do caso tornava obrigatório medir. A primeira versão declarava `KAM-129`; a decisão de o retirar está no Contexto |
| 6 — contagens derivadas acompanham | **satisfeito** | §1: `143 tickets atómicos (KAM-001 a KAM-143)` → `144 … (KAM-001 a KAM-144)`, e o intervalo dos acrescentados passa a `KAM-128 a KAM-144`. §3.1: EPIC-01 `KAM-128 – KAM-144` com `30` (era 29), TOTAL `KAM-001 – KAM-144` com `144`. S7 verifica os três contra o número de blocos **e** contra a soma por epic, não contra o texto: soma das onze linhas = 144 = blocos = linhas do §4 |
| 7 — o bloco diz que a correcção de dados não fecha a causa | **satisfeito** | Secção «A causa não é corrigida aqui — e a recomendação sobre o KAM-138». Os três factos que a sustentam foram medidos, não lidos: `grep -rl Bloqueia tools/` → **vazio** (nenhuma ferramenta do CI conhece o campo); `ls tools/ \| grep -i backlog` → vazio e `grep -n ci-3c Makefile` → vazio (não há `tools/lint_backlog` nem alvo `make ci-3c`). A recomendação de subir o KAM-138 a P1/Fase 0 está escrita com o seu fundamento e **explicitamente não aplicada**, com a decisão devolvida ao Arquitecto de Plataforma |
| 8 — «Controlo de versões» nos dois documentos | **satisfeito** | `specs/EPIC-01_Fundacoes_Dados.md` v1.17 e `specs/INDICE.md` §7 v1.10, ambas a nomear o KAM-144, os números medidos e a causa não fechada |
| DoD — todos os CA satisfeitos e demonstráveis | **satisfeito** | Os oito acima, cada um com o comando e o número |
| DoD — revisto por ≥ 1 revisor; recomendação revista pelo Arquitecto | **não satisfeito** | **Zero revisores humanos** — a revisão adversarial é evidência, não é um revisor (`specs/01_Engineering_Standards_e_Handoff.md`, DoD). E a recomendação de prioridade do KAM-138 **não foi revista por ninguém**: é uma decisão devolvida, não uma decisão tomada, e é por isso que esta caixa fica vazia em vez de se marcar pelo facto de a recomendação estar escrita |
| DoD — documentação actualizada; Conventional Commits | **satisfeito** | As duas linhas de versão (CA 8); *commits* `fix(KAM-144): …` |
| DoD — sincronia mestre↔epics, segunda passagem a 0 | **satisfeito** | S1 a 0 nas duas passagens, sem alterações entre elas |
| DoD — reciprocidade a 0, com o número no PR | **satisfeito** | 8 → 0, nos dois sentidos (CA 2) |
| DoD — referências | **satisfeito** | `lint_refs --root . check` → **«conforme»**, com `KAM: 144 (KAM-001–KAM-144)` — o conjunto fechado e o KAM-144 já reconhecido como existente. **Esta linha deixou de citar o total de referências do repositório, e a razão é o próprio defeito que o CA 2 nomeia.** A primeira versão dizia «10 580 referências»: número medido antes de a secção de verificação entrar no bloco, que não reproduzia em *commit* nenhum (a revisão mediu 10 895 nesse estado e 10 486 em `main`). Corrigido para 10 919 — e **voltou a ficar errado**, porque o total conta as referências `KAM-NNN` do próprio texto que o publica: mexeu em **10 580 → 10 895 → 10 914 → 10 919 → 11 117** ao longo das emendas, e a última subida foi só por se ter acrescentado o `ANALISE-16`. Um número instável por construção não é evidência de nada; perseguir-lhe o valor era repetir o defeito a cada edição. **O que é evidência é o veredicto e o conjunto `KAM` reconhecido, que são estáveis**, e é isso que esta linha afirma. O total continua a ler-se no *log* do comando, onde pertence. O comando emite ainda **30 avisos** de *tokens* `D#` fora do intervalo canónico, todos pré-existentes em `main` e nenhum vindo deste diff: «conforme» é o veredicto, não a ausência de avisos; `canon_lint --root . check` rc=0; `lint_arch --root . all` → «lista de bloqueio: conforme», «estrutura: conforme» |
| DoD — sem segredos | **satisfeito** | Medido em vez de declarado não aplicável: `scan_secrets --root . tree` → «limpo — 552 ficheiros seguidos pelo git» |
| DoD — defeitos fora do âmbito abertos ou registados, não corrigidos aqui | **satisfeito** | Um encontrado e **registado**: o `README.md` diz «Backlog mestre (130 tickets)», errado em 13 **antes** deste ticket e em 14 depois. Entrou como **linha 19** de `../docs/dividas-documentais.md`. A primeira versão desta linha marcava a caixa dizendo que a dívida «já tem dono» no KAM-130, e a revisão adversarial mostrou que isso era falso à letra: a linha de alvo da busca H4 do KAM-130 diz «0 **fora de** `specs/INDICE.md` **e `README.md`**» — ou seja **isenta** o `README.md` do alvo 0 — e a tabela de inventário C1–C5 nomeia só o `ADR-L001` e o `PR-KAM-001.md`. O DoD pede «abertos como ticket `fix` próprio **ou** registados em `../docs/dividas-documentais.md`», e nenhuma das duas vias estava cumprida. Agora está a segunda; não se abriu ticket novo por ser resíduo textual de uma linha, que é o que a lista de dívidas existe para levar |

#### O que a revisão encontrou, e o que se fez

A revisão adversarial **não aprovou sem reservas**: 2 maiores, 9 menores e 3
suspeitas, com *parser* do grafo escrito de zero e medição em `main` e no ramo.
Está em [`ANALISE-16`](../docs/analises/ANALISE-16-KAM-144-reciprocidade-do-grafo.md).

**Os dois maiores são do mesmo tipo, e são os dois do ticket e não da
correcção: afirmação com mais confiança do que a medição sustentava.** O
primeiro foi o ticket a cometer o defeito que nomeia — a linha de DoD publicava
«10 580 referências», número colhido a meio do trabalho que **não reproduz em
*commit* nenhum** (10 895 no ramo, 10 486 em `main`), num bloco cujo critério 2
diz «exige-se o número, não a leitura». O segundo era uma frase falsa a servir
de fundamento a uma decisão a entregar ao Arquitecto: «é o único dos oito cuja
ausência esconde defeitos» — e pelo menos seis dos outros sete fecham falhas
silenciosas, três deles já fundidos. Os dois corrigidos, com o erro escrito
onde esteve.

**A medição da correcção reproduziu-se inteira**, por verificação independente:
as 8 → 0 falhas, as 379/371 → 379/379 arestas, os 143 → 144 blocos, a diferença
simétrica vazia entre o `Bloqueia` do KAM-002 e quem declara depender dele, e a
confirmação de que **não há nona falha** nem aresta encoberta.

**Uma suspeita mudou o ticket.** A revisão devolveu — sem a classificar como
achado — a escolha de `Dependências | KAM-129`, e mediu que o precedente do
conjunto é ordem técnica e não proveniência. Acolhida: os dois campos passaram
a `—`, e a razão está no Contexto.

Menores corrigidos: o *placeholder* `#PR` que ficou no primeiro *commit*; a
frase que fazia da igualdade dos totais de arestas uma prova (é necessária e não
suficiente, e a revisão construiu o contra-exemplo); a caixa dos defeitos fora
de âmbito, marcada por uma posse que o teste citado nega — o alvo da busca H4 do
KAM-130 **isenta** o `README.md` —, paga agora com a linha 19 de
`../docs/dividas-documentais.md`; os separadores `---` em falta e em duplicado;
a bala «Fora de âmbito» fora de lugar; duas grafias PT-BR («registra»); a
reincidência contada como um evento quando são dois (0 → 7 na versão 1.5, 7 → 8
na 1.6, o que é melhor argumento); e a prioridade P1 sem justificação face ao
P2 do KAM-130.

**Declarado, não corrigido:** a «segunda passagem a 0 alterações» é estabilidade
de um verificador que não escreve, não evidência de correcção — a regra do
SKILL §7 existe para *scripts* que corrigem e verificam na mesma passagem. E
não se abriu lacuna nova em `../docs/ci.md` §7 para «o CI está verde com as oito
falhas», por o KAM-138 já ser o dono declarado dessa lacuna.

#### Não verificado

O *gate* a recusar a nona falha: não existe, é o KAM-138, e nada neste PR o prova. A reciprocidade voltar a regredir depois deste PR é o resultado esperado enquanto o *gate* não existir, e este ticket **não** o impede — só o mede uma vez. A verificação usada é um *script* do scratchpad, não maquinaria do repositório: corre à mão, e ninguém a corre no próximo PR.

### Detalhes Técnicos

- **Componentes:** transversal (documentação). Sem código de *runtime*, sem migrações, sem dependências novas. Ficheiros: `specs/EPIC-01_Fundacoes_Dados.md`, `specs/INDICE.md`.
- **A correcção é de dados, não de regra.** Não se altera nenhum campo `Dependências`: os oito declaram correctamente que dependem do KAM-002. A aresta existe; faltava-lhe o outro lado. Alterar os `Dependências` em vez do `Bloqueia` mudaria o grafo em vez de o completar.
- **Ordem crescente de ID no `Bloqueia`.** É a convenção do conjunto em todos os blocos existentes, e é o que torna uma omissão visível a olho — `KAM-111, KAM-142`, com um salto de 31, não mostra nada; `KAM-111, KAM-131, …, KAM-142` mostra.
- **Nenhuma aresta nova foi inventada.** As quinze saem dos campos `Dependências` dos próprios blocos, lidos por máquina. Acrescentar ao `Bloqueia` um ticket que não declare a dependência cria a falha simétrica, que a mesma verificação apanha.

- **Fora de âmbito** (a secção seguinte diz porque é que o primeiro item é a causa e não um pormenor)**:** implementar o *gate* 3c, `tools/lint_backlog` ou o alvo `make ci-3c` — é o **KAM-138**, e fazê-lo aqui esvaziaria um ticket aberto sem o fechar; a contagem de tickets do `README.md` (linha «Backlog mestre (130 tickets)»), que está desactualizada em 13 **antes** deste ticket e cuja reconciliação é o **KAM-130** (defeito C4) — escolher aqui o seu valor seria decidir a base de contagem que o KAM-130 tem por critério decidir; as linhas de evidência dos KAM-001, KAM-128 e KAM-129, actualizadas em `albinoJimy/kamba#43`; qualquer alteração aos campos `Dependências` dos oito tickets; alterar a prioridade ou a fase do KAM-138.

#### A causa não é corrigida aqui — e a recomendação sobre o KAM-138

**A causa é o KAM-138 não estar implementado.** Este `fix` paga oito arestas de uma vez; não impede a nona. Enquanto a reciprocidade for prosa num *teste requerido* e não um *gate* fail-closed, o próximo ticket que declare `Dependências | KAM-NNN` sem fechar o outro lado passa no CI verde, exactamente como estes oito passaram — e o défice volta a acumular-se em silêncio até alguém o remedir à mão.

**Recomendação registada, não aplicada: o KAM-138 deve subir de P2/Fase 1 para P1/Fase 0.** O fundamento é a reincidência medida, não o incómodo: a reciprocidade regrediu em **duas** inscrições sucessivas e independentes — a versão 1.5 do `specs/INDICE.md` §7 acrescentou os KAM-131 a KAM-137 (**0 → 7**) e a 1.6 acrescentou o KAM-138 (**7 → 8**) —, o que mostra que não foi um lapso único mas o comportamento por omissão de quem acrescenta um ticket. Contado à letra, este é o **primeiro** `fix` de reciprocidade do backlog: o custo do *gate* ainda não se pagou duas vezes em tickets. Pagou-se uma vez aqui, e uma vez em revisão — a primeira versão do próprio KAM-129, que o seu critério 9 regista. O KAM-138 depende do KAM-002, que é P0 de Fase 0 e está em `main`, pelo que a subida **não cria inversão de prioridade nem de fase** (verificado por máquina: S3 e S4 a 0 com o KAM-138 a P1/Fase 0). É também o único dos oito dependentes do KAM-002 cuja ausência esconde defeitos **no próprio backlog** — a fonte que decide ordem e paralelismo —, e esse é o limite da afirmação. A primeira versão deste bloco dizia «é o único… cuja ausência esconde defeitos em vez de os deixar à vista: os outros sete corrigem coisas que já se vêem», e **era falso**: a revisão adversarial mediu que **pelo menos seis dos outros sete** fecham também falhas silenciosas nos seus domínios — o KAM-136 chama-se «Dois erros de leitura *silenciosos*», o KAM-134 faz recusar chave hoje aceite em silêncio — e que **três dos oito já estão fundidos** (KAM-131, KAM-132 e KAM-136), pelo que falar da sua «ausência» já não se aplica.

**Porque este ticket é P1 e o KAM-130 é P2.** São os dois `fix` documentais do mesmo epic, com o mesmo responsável sugerido, e a diferença é o que o defeito alimenta: uma contagem errada engana quem a lê e não alimenta máquina nenhuma, enquanto o grafo de dependências é lido por `../.claude/skills/agentic-engineering/scripts/vagas.py` para decidir **o que corre em paralelo**. Um `Bloqueia` incompleto não engana um leitor — faz uma decisão de execução ser tomada com o grafo errado. Daí P1 aqui e P2 no KAM-130. A revisão adversarial apontou que esta diferença não estava escrita.

**A subida de prioridade do KAM-138 não foi feita neste ticket.** Prioridade e fase são campos do contrato do §4, e a sua alteração é decisão do Arquitecto de Plataforma; aplicá-la aqui seria mudar o contrato de outro ticket a pretexto de uma correcção de dados — a mesma espécie de alteração em silêncio que esta família de `fix` existe para apanhar. A decisão fica **devolvida**, com o fundamento acima escrito no bloco para que não se decida por esquecimento.


### Testes Requeridos

- Verificação por máquina sobre os 11 epics e o `specs/INDICE.md` §4, corrida **antes e depois**, com os dois números no PR:

```text
G5   reciprocidade Dependencias<->Bloqueia nos dois sentidos        antes 8   ->  alvo 0
S1   sincronia mestre<->epics (tipo, estimativa, prioridade, fase,
     dependencias) e existencia nos dois lados                     antes 0   ->  alvo 0
S2   ciclos de dependencias                                        antes 0   ->  alvo 0
S3   prioridade invertida (P0 a depender de P1 ou P2)               antes 0   ->  alvo 0
S4   fase invertida (fase 0 a depender de fase 1)                   antes 0   ->  alvo 0
S5   exactamente um bloco "## KAM-NNN — " por ticket                antes 0   ->  alvo 0
S6   referencias: todo o KAM-NNN citado em Dependencias ou
     Bloqueia tem bloco                                             antes 0   ->  alvo 0
S7   contagens derivadas: §1 e §3.1 (intervalo, total por epic,
     TOTAL) conferem com o numero de blocos e com as linhas do §4    antes 0   ->  alvo 0
```

- Segunda passagem de G5 e S1–S7: **0 alterações**. Uma verificação que muda algo na segunda passagem é uma edição, não uma verificação.
- `git diff --stat` revisto linha a linha: o *diff* toca só os campos `Bloqueia` do KAM-002 e do KAM-129, o bloco novo, a linha do §4, as contagens e as duas linhas de versão.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis, com secção «Verificação dos Critérios de Aceitação» neste bloco: uma linha por critério, com o comando e o número que saiu.
- [ ] Revisto por ≥ 1 revisor; a recomendação de prioridade do KAM-138 revista pelo Arquitecto de Plataforma, a quem a decisão fica devolvida.
- [x] Documentação actualizada: «Controlo de versões» de `specs/EPIC-01_Fundacoes_Dados.md` e de `specs/INDICE.md`; Conventional Commits.
- [x] **Sincronia mestre↔epics** — a linha do §4 e este bloco dizem o mesmo; segunda passagem a 0 divergências.
- [x] **Reciprocidade** — G5 a 0 nos dois sentidos, com o número no PR.
- [x] **Referências** — nenhum `KAM-NNN` citado deixou de existir; nenhum caminho citado deixou de resolver.
- [x] **Sem segredos** — não aplicável: o ticket não acrescenta configuração nem dependências.
- [x] Defeitos encontrados fora do âmbito abertos como ticket `fix` próprio ou registados em `../docs/dividas-documentais.md`, não corrigidos aqui.

### Handoff para Claude Code

```text
És o executor do ticket KAM-144 da KAMBÁ. Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-144).
Objectivo: as arestas do grafo do backlog dizem o mesmo dos dois lados, e o número prova-o.
- Acrescenta KAM-131 a KAM-138 ao campo `Bloqueia` do KAM-002, em ordem crescente de ID.
- NAO toques nos campos `Dependências` dos oito: estão certos. Falta o outro lado da aresta, não a aresta.
- Corre a verificação de reciprocidade sobre os 11 epics ANTES e DEPOIS, e exige 0. Não confies na leitura:
  o defeito existe porque ninguém contou. Corre-a sobre TODO o grafo — corrigir o KAM-002 pode expor
  arestas que estavam encobertas.
- Mede também sincronia, ciclos, prioridades, fases, unicidade e contagens: antes da correcção estavam a 0,
  e é essa a linha de base que torna a comparação possível.
- Este ticket entra nos dois lados (linha no §4 e este bloco) e tem de ter a sua própria reciprocidade
  correcta. NAO declares `Dependências | KAM-129`: a proveniência do defeito nao e uma aresta tecnica, e
  inscreve-la poe no grafo uma aresta que nao existe. Os dois campos ficam `—`, e a verificacao conta-os.
- Actualiza as contagens de specs/INDICE.md §1 e §3.1 e o Controlo de versões dos dois documentos.
Não expandas escopo: NAO implementes o gate 3c (é o KAM-138); NAO corrijas a contagem do README.md (é o
KAM-130); NAO toques nas linhas de evidência dos KAM-001, KAM-128 e KAM-129 (PR albinoJimy/kamba#43);
NAO alteres a prioridade do KAM-138 — a recomendação de a subir fica escrita no bloco e a decisão devolvida.
Abre PR com o template do §7.
```

---

## KAM-145 — Forma do caminho dentro dos blocos de *handoff*, e o `cwd` do executor declarado

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-128, KAM-129 |
| Bloqueia | KAM-147 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `specs/01_Engineering_Standards_e_Handoff.md` (§5, §7, §8), bloco KAM-128 deste epic («Convenção de caminhos — decisão registada» e o critério das referências nuas), bloco KAM-129 deste epic («Detalhes Técnicos», a questão aberta), os onze `specs/EPIC-*.md` |

### Contexto

Um bloco `### Handoff para Claude Code` fala a um executor, e cita caminhos de duas formas na mesma frase: `specs/EPIC-10…` relativo à raiz do repositório, e `../docs/tecnica/…` relativo à posição do ficheiro que o contém. O KAM-129 levantou isto nos seus «Detalhes Técnicos» e **deixou-o deliberadamente em aberto**: lido à letra por um executor cujo *cwd* é a raiz, `../docs/…` fica **acima** da raiz, e nas quatro instruções `Cria …/validacao/*.md` isso seria uma escrita fora da árvore, não uma leitura que falha. Reescrever só uma parte produziria uma segunda convenção dentro do mesmo bloco — pior do que o defeito.

Duas coisas tornam a decisão inevitável agora.

**O *cwd* do executor não está declarado em documento normativo nenhum.** Busca por `cwd`, `raiz do repositório`, `directório de trabalho` e `diretório de trabalho` em `specs/01_Engineering_Standards_e_Handoff.md` → **0 ocorrências**. O único texto do conjunto que o afirma é a nota do bloco KAM-129, que o declara em aberto. Sem *cwd* declarado nenhuma das duas formas é verificável, e é por isso que o gate 3 do KAM-002 não as apanha: resolve caminhos em *code-span* de prosa, e os de um bloco de *handoff* estão dentro de uma cerca de texto.

**Um critério de aceitação do KAM-128 está em aberto por causa disto.** As sete referências nuas a ficheiros da biblioteca exploratória que restam estão **todas** dentro de blocos de *handoff*, e o texto desse critério manda-as passar a `../docs/exploracao/…` em `specs/` — precisamente a forma relativa ao ficheiro que esta decisão pode recusar. Corrigir só as sete produziria a segunda convenção.

População medida sobre `main` (`f10bde8`), contando só o que está dentro de um bloco `### Handoff para Claude Code` nos onze epics:

| Classe de caminho | `../docs/…` | `docs/…` (à raiz) | nua, sem directório | Total |
|---|---|---|---|---|
| Anexos de evidência | 41 | 4 | — | 45 |
| Outros documentos de desenho | 206 | 33 | — | 239 |
| Biblioteca exploratória | 0 | 0 | 7 | 7 |
| **Total** | **247** | **37** | **7** | **291** |

As **31** que o KAM-129 contou são o subconjunto de evidência dos **seis** epics que esse ticket tocou — EPIC-05 2, EPIC-06 0, EPIC-07 6, EPIC-08 2, EPIC-10 13, EPIC-11 8 — todas `../docs/…`. As restantes 14 estão no EPIC-01 (8, das quais 4 à raiz), no EPIC-02 (5) e no EPIC-03 (1): fora do âmbito do KAM-129, e por isso nunca contadas. As sete nuas são `specs/EPIC-10_Spikes_Validacao_Gates.md` nas linhas 105, 288, 469, 589, 649 e 709, e `specs/EPIC-11_Modulos_Entrada.md` na linha 784.

### Objectivo

Declarar o *cwd* do executor nos padrões, decidir **uma** convenção de caminho para dentro dos blocos de *handoff*, e aplicá-la às 291 ocorrências de uma vez — de modo que as sete referências nuas deixem de o ser como consequência da convenção, e não por uma correcção isolada.

### Critérios de Aceitação

- [ ] **O *cwd* do executor está declarado** em `specs/01_Engineering_Standards_e_Handoff.md`, numa frase, no §5 ou no §8, e o §8 passa a citar os seus próprios quatro caminhos na forma que a declaração implica.
- [ ] **Há uma convenção escrita para caminhos dentro de blocos de *handoff***, com a consequência de cada alternativa registada: tudo relativo à raiz, tudo relativo ao ficheiro, ou uma regra que distinga ler de escrever. **A escolha é do Arquitecto de Plataforma** (o papel que `specs/01_Engineering_Standards_e_Handoff.md` §9 nomeia para este documento; as três linhas de assinatura estão vazias e o documento é *proposta*): apresentam-se as alternativas e as consequências, e regista-se quem aprovou — não se decide sozinho entre duas afirmações do canon.
- [ ] As **291** ocorrências medidas obedecem à convenção decidida: **0** de forma divergente, verificado por *script* sobre os onze `specs/EPIC-*.md`, com a tabela do «antes» e do «depois» no PR.
- [ ] As **quatro** instruções `Cria …/validacao/*.md` não escrevem fora da árvore do repositório quando lidas à letra do *cwd* declarado.
- [ ] **O critério em aberto do KAM-128 fica reconciliado com a decisão.** Se a convenção não for `../docs/exploracao/…`, o texto desse critério é emendado para dizer a forma decidida; e a medição dessa caixa passa a dizer **17 de 17** — que é a população real do critério, e não as 10 que o texto afirma, como a secção de verificação do KAM-128 já registou. A disposição da caixa é do DoD, não deste critério.
- [ ] Nenhum caminho **fora** de blocos de *handoff* é tocado: a referência cruzada entre documentos continua a ser a regra do KAM-128.
- [ ] A convenção fica verificada por máquina **neste PR**, pelo *script* de classificação, que passa a viver em `tools/` em vez de morrer no *scratchpad*: corre-o duas vezes e as duas dizem 0 divergentes. Inscrevê-la no **KAM-138** fica como proposta escrita nos «Detalhes Técnicos» — não como via alternativa para fechar este critério, porque poria trabalho num ticket que não é dependência deste. Uma convenção que nenhum gate lê volta a divergir.
- [ ] Cada epic tocado e o `specs/01_Engineering_Standards_e_Handoff.md` registam a emenda no «Controlo de versões», **sem citar a forma antiga**, para não acender as buscas de regressão **G1 e G3 do KAM-129** (`grep -rnoE '(^|[^/A-Za-z._-])evidencia/'` e `grep -rnoE '\.\./docs/tecnica/\.\./|docs/docs/'`, ambas sobre `specs/*.md` com `--exclude=EPIC-01_Fundacoes_Dados.md`) — são essas que excluem **um só** ficheiro, e por isso que uma forma antiga escrita em qualquer dos outros dez as acende.

### Detalhes Técnicos

- **Componentes:** `specs/01_Engineering_Standards_e_Handoff.md` (§5, §8), os onze `specs/EPIC-*.md`, e o bloco KAM-128 deste epic (texto do critério das referências nuas).
- **O *script* de medição delimita o bloco** por `### Handoff para Claude Code` e pelo fecho da cerca, e classifica cada ocorrência em `../docs/…`, `docs/…` à raiz, ou nua. É o mesmo *script* que produz a tabela do «antes» e do «depois», e corre-se duas vezes: uma verificação que muda algo na segunda passagem é uma edição, não uma verificação.
- **A decisão tem alcance para além dos epics.** As linhas de DoD que nomeiam anexos de evidência já usam as duas formas no mesmo ficheiro (`docs/evidencia/KAM-128.md` num ticket, `../docs/evidencia/KAM-131.md` noutro). Essas estão **fora** deste âmbito — são prosa, não *handoff* — mas a convenção decidida aqui é a referência natural para quem as reconciliar.
- **Serializa com o KAM-146 e o KAM-147 no bloco `## KAM-128` deste epic.** Os três editam o mesmo bloco — este o texto de um critério, o KAM-146 a caixa desse critério, o KAM-147 a primeira linha do DoD — pelo que **não correm em paralelo**, mesmo tendo dependências disjuntas no grafo. O KAM-147 depende deste pela forma do caminho.
- **Alternativa a considerar antes de começar: partir em dois.** Este ticket contém duas coisas separáveis — declarar o *cwd* e escolher a convenção (com aprovação), e aplicá-la às 291 ocorrências. A estimativa subiu a **L** por isso: a população é 9× a das 31 que o KAM-129 previu, e há uma alteração normativa a uma fonte de verdade. A objeção do próprio KAM-129 («corrigir só as 7 produz uma segunda convenção») é contra corrigir **subconjuntos da aplicação**, e não impede separar a decisão da aplicação. Quem executar decide, e escreve a razão.
- **Proposta para o KAM-138, não requisito deste ticket:** o gate 3c pode passar a ler os blocos de *handoff* e recusar a forma divergente. Fica escrito aqui para não se perder; inscrevê-lo é trabalho desse ticket.
- **Fora de âmbito:** caminhos em prosa e em *code-span* fora dos blocos de *handoff* (regra do KAM-128); as contagens e intervalos herdados (**KAM-130**); as linhas de «Controlo de versões» do KAM-128 (**KAM-146**); os anexos de evidência (**KAM-147**).

### Testes Requeridos

- *Script* de classificação corrido antes e depois, com as duas tabelas no PR, e segunda passagem a dar **0** divergências.
- As buscas de regressão dos dois tickets sem novas ocorrências, nomeadas sem as confundir: **G1 e G3 do KAM-129** (as que excluem um só ficheiro, sobre `specs/*.md`) e **G1 do KAM-128** (`tecnica/NN` dentro de `docs/tecnica/`, sem exclusão). O **G2 do KAM-128** não está a zero hoje e não é deste ticket — está registado em `../docs/dividas-documentais.md`.
- Resolvedor de ligações markdown sobre todo o conjunto `.md` sem ligações novas quebradas.
- `make lint-arch` e a parte Python de `make check` verdes.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis, com a medição numa secção «Verificação dos Critérios de Aceitação» deste bloco.
- [ ] A convenção e o *cwd* aprovados pelo **Arquitecto de Plataforma** (`specs/01_Engineering_Standards_e_Handoff.md` §9) e registados nesse documento; revisto por ≥ 1 revisor.
- [ ] Documentação actualizada: linha de «Controlo de versões» em cada epic tocado e no `specs/01_Engineering_Standards_e_Handoff.md`; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-145 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-145, e os blocos KAM-128 e KAM-129 que o abrem) e
specs/01_Engineering_Standards_e_Handoff.md (§5, §7, §8).
Objectivo: declarar o cwd do executor, decidir uma convenção de caminho para dentro dos blocos de handoff,
e aplicá-la às 291 ocorrências de uma vez.
- NÃO decidas a convenção sozinho: são duas afirmações do canon. Apresenta as alternativas com a
  consequência de cada uma, e regista quem aprovou.
- Mede primeiro, com script, e põe a tabela do antes no PR. A população é 291 nos onze epics, não 31:
  as 31 do KAM-129 são só a evidência dos seis epics que esse ticket tocou.
- Reconcilia o texto do critério das referências nuas do KAM-128 com a decisão, em vez de corrigir só
  as sete que restam — eram 17, e corrigir parte produz uma segunda convenção no mesmo bloco.
- As linhas de versão não citam a forma antiga: quebrariam as buscas G1 e G3.
Não expandas escopo: prosa fora dos blocos de handoff é a regra do KAM-128; contagens herdadas são o
KAM-130; linhas de versão do KAM-128 são o KAM-146; anexos de evidência são o KAM-147.
Abre PR com o template do §7.
```

---

## KAM-146 — As onze linhas de «Controlo de versões» que o KAM-128 não acrescentou

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-128 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | Bloco KAM-128 deste epic (o critério do «Controlo de versões» e os seus «Testes Requeridos» G1 e G3), `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/02_Agent_Runtime_Verticais.md`, `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/07_Geo_Logistica_Federada.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/09_Topologia_Operacao_Escala.md`, `../docs/tecnica/10_Onboarding_Governanca.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `specs/EPIC-11_Modulos_Entrada.md` |

### Contexto

Um critério de aceitação do KAM-128 pede que «cada documento formal tocado regista a emenda no seu "Controlo de versões" com referência a KAM-128». Não se cumpriu, e a caixa está vazia.

Medição sobre `main` (`f10bde8`): o *commit* `08426f3` tocou **23** ficheiros, todos `.md`. Desses, **15** têm tabela de versões (cabeçalho `| Versão | Data |`) e **4** têm linha a citar o KAM-128 — `../docs/INDICE.md`, `../docs/tecnica/INDICE.md`, `specs/INDICE.md` e este epic. **Faltam 11:**

| # | Documento |
|---|---|
| 1 | `../docs/tecnica/00_Arquitectura_Solucao.md` |
| 2 | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` |
| 3 | `../docs/tecnica/02_Agent_Runtime_Verticais.md` |
| 4 | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` |
| 5 | `../docs/tecnica/06_Dados_Eventos_Analytics.md` |
| 6 | `../docs/tecnica/07_Geo_Logistica_Federada.md` |
| 7 | `../docs/tecnica/08_Seguranca_Conformidade.md` |
| 8 | `../docs/tecnica/09_Topologia_Operacao_Escala.md` |
| 9 | `../docs/tecnica/10_Onboarding_Governanca.md` |
| 10 | `specs/EPIC-10_Spikes_Validacao_Gates.md` |
| 11 | `specs/EPIC-11_Modulos_Entrada.md` |

Os outros **8** ficheiros que `08426f3` tocou não têm tabela de versões — `README.md`, `../docs/00-KAMBA-documento-mestre.md` (que é gerado e diz «NÃO EDITAR À MÃO»), `../docs/PR-KAM-001.md`, `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` e os quatro de `.claude/skills/agentic-engineering/`. Nenhum é documento formal: a regra das três tabelas — cabeçalho, aprovação e controlo de versões — está nas «Convenções não negociáveis» de `.claude/skills/agentic-engineering/SKILL.md`, e **não** em `specs/01_Engineering_Standards_e_Handoff.md`, que não usa a expressão «documento formal» em sitio nenhum (busca → 0 ocorrências). É uma das coisas que este ticket tem de deixar escritas.

**Armadilha a respeitar.** As linhas que o KAM-129 acrescentou aos seis epics descrevem a correcção **sem citar a forma antiga** — de propósito, e os «Testes Requeridos» desse ticket dizem-no por palavras suas: «a exclusão é de **um só** ficheiro, e é por isso que as linhas de "Controlo de versões" dos seis epics descrevem a correcção sem citar a forma antiga». As buscas em causa são **G1 e G3 do KAM-129**, sobre `specs/*.md` com `--exclude=EPIC-01_Fundacoes_Dados.md` — **não** as do KAM-128, cujo G1 varre só `docs/tecnica/` e cuja exclusão de um ficheiro pertence ao G2. Uma linha que escreva a forma antiga em qualquer dos outros dez acende a busca, e o defeito volta disfarçado de registo.

### Objectivo

Dar a cada um dos onze documentos a sua linha de versão a referir o KAM-128, a descrever o que mudou **nesse** documento, sem citar a forma antiga e sem reescrever linhas existentes.

### Critérios de Aceitação

- [ ] Cada um dos **onze** documentos tem uma linha nova no seu «Controlo de versões» com referência a KAM-128, a dizer o que mudou nesse documento em concreto — não a mesma linha genérica onze vezes.
- [ ] **Nenhuma linha nova cita a forma antiga** do caminho. Verificado com a busca certa para cada forma, e com a contagem igual antes e depois: `evidencia/EN` pelo **G1 do KAM-129** (`specs/*.md`, exclui só este epic — alcança portanto o `EPIC-10` e o `EPIC-11`, que são dois dos onze); `tecnica/NN` pelo **G1 do KAM-128** (`docs/tecnica/`, sem exclusão — alcança os outros nove). Para o **nome nu da biblioteca não existe busca de regressão nenhuma** no conjunto: essa verifica-se com o resolvedor de caminhos, nomeando-o nos «Testes Requeridos», e não se finge que uma busca a cobre.
- [ ] O número de versão de cada linha segue a sequência da tabela do próprio documento, e nenhuma linha antiga é reescrita ou reordenada.
- [ ] Nenhum conteúdo técnico muda: o `git diff` de cada ficheiro é a linha nova e mais nada.
- [ ] **A definição de «documento formal» usada fica escrita** no bloco deste ticket, e os 8 ficheiros sem tabela de versões ficam nomeados, com a razão de ficarem de fora.
- [ ] A medição da caixa do critério do KAM-128 dá **15 de 15** pela definição operacional (tem tabela `| Versão | Data |`) **e 12 de 12** pela definição das três tabelas — as duas têm de ser escritas, porque dão populações diferentes: os três que só a primeira conta (`../docs/INDICE.md`, `../docs/tecnica/INDICE.md`, `specs/INDICE.md`) **já têm** a linha, pelo que a lista dos onze em falta é a mesma nas duas. A disposição da caixa é do DoD.

### Detalhes Técnicos

- **Componentes:** os onze documentos da tabela, e o critério do «Controlo de versões» no bloco KAM-128 deste epic.
- **O que cada linha diz** sai do `git show 08426f3 -- <ficheiro>`: é o único registo do que mudou em cada um. Descreve-se pela consequência («as N referências passam a resolver»), nunca pela forma que deixou de se usar.
- **Fora de âmbito:** o `README.md` e o documento mestre (sem tabela de versões, e o mestre é gerado por `../docs/compilar-mestre.sh`); as linhas de versão de outros tickets; a forma do caminho dentro de blocos de *handoff* (**KAM-145**); as contagens herdadas (**KAM-130**).

### Testes Requeridos

- *Script* que liste os `.md` de `08426f3`, detecte a tabela `| Versão | Data |` e a linha a citar KAM-128 → **15** com tabela, **15** com linha, **0** em falta.
- Buscas G1 e G3 do KAM-128 com contagem inalterada, com o número antes e depois no PR.
- `git diff --stat` lido linha a linha: onze ficheiros, uma linha acrescentada em cada.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis, com a medição numa secção «Verificação dos Critérios de Aceitação» deste bloco.
- [ ] Revisto por ≥ 1 revisor.
- [ ] Documentação actualizada; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-146 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-146, e o bloco KAM-128 de onde a lacuna vem).
Objectivo: dar a cada um dos onze documentos formais a sua linha de «Controlo de versões» a referir o KAM-128.
- NÃO cites a forma antiga do caminho em nenhuma linha nova: acenderia o G1 e o G3 **do KAM-129** (os que
  excluem só o EPIC-01), ou o G1 **do KAM-128** (`tecnica/NN` em docs/tecnica/). Não confundas as etiquetas:
  os dois tickets têm G1/G2/G3 com o mesmo nome e conteudo diferente. Descreve pela consequencia, como as
  linhas que o KAM-129 deixou nos seis epics. Para o nome nu da biblioteca nao existe busca: usa o resolvedor.
- O que cada linha diz sai de `git show 08426f3 -- <ficheiro>`, um ficheiro de cada vez. Nada de linha
  genérica repetida onze vezes.
- Confirma por script, no fim: 15 ficheiros com tabela de versões, 15 com linha a citar KAM-128.
- Escreve a definição de «documento formal» que usaste, e nomeia os 8 que ficam de fora.
Não expandas escopo: nenhum conteúdo técnico muda; o README e o documento mestre não têm tabela de versões;
a forma do caminho em blocos de handoff é o KAM-145 e as contagens herdadas são o KAM-130.
Abre PR com o template do §7.
```

---

## KAM-147 — Os anexos de evidência que o DoD do KAM-128 e do KAM-129 nomeia e não existem

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-128, KAM-129, KAM-145 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | Blocos KAM-128 e KAM-129 deste epic (DoD e «Verificação dos Critérios de Aceitação»), bloco KAM-002 deste epic (o precedente contrário), `../docs/evidencia/KAM-131.md` e `../docs/evidencia/KAM-136.md` (a forma do anexo), `specs/01_Engineering_Standards_e_Handoff.md` §3 |

### Contexto

A primeira linha de DoD do KAM-128 diz «evidência em `docs/evidencia/KAM-128.md`», e a do KAM-129 diz o mesmo para `KAM-129.md`. **Nenhum dos dois ficheiros existe.** Medido sobre `main` (`f4c7e3d`): a pasta `../docs/evidencia/` tem **seis** anexos — `KAM-001-node.md`, `KAM-010.md`, `KAM-011-seaweedfs.md`, `KAM-131.md`, `KAM-132.md` e `KAM-136.md` — e as secções de verificação dos dois blocos já registam a caixa como **não satisfeita** por essa razão exacta. **A contagem envelhece a cada ticket entregue:** quando este bloco foi escrito dizia cinco, e o KAM-132 fundiu vinte minutos antes. Quem executar remede, com o *commit* à vista, em vez de copiar estes números.

O conjunto tem **dois precedentes em tensão**, ambos defensáveis:

- **O anexo escreve-se.** O KAM-131 e o KAM-136 nomearam-no no DoD, escreveram-no, e o bloco do ticket remete para ele. A medição longa — comandos, execuções de CI, tabelas — vive no anexo e o bloco fica legível.
- **O DoD não nomeia anexo.** O KAM-002, entregue e com revisão adversarial, **não** tem linha de DoD a nomear anexo nenhum: a medição vive na secção «Verificação dos Critérios de Aceitação» do próprio bloco, que é também o que o KAM-128 e o KAM-129 já fizeram.

Hoje os dois tickets estão no pior dos dois mundos: têm a medição no bloco **e** uma linha de DoD a prometer um ficheiro que não existe, pelo que a caixa não fecha por nenhuma das duas leituras.

**A escolha não é de quem executa este ticket.** É de quem escreveu a linha do DoD, e tem consequência para além destes dois: das **doze** linhas de DoD deste epic que nomeiam um anexo dessa pasta — onze delas na forma `docs/evidencia/…` e uma, a do KAM-131, em `../docs/evidencia/…`, o que é por si um sintoma do **KAM-145** — **quatro** existem (`KAM-010`, `KAM-131`, `KAM-132`, `KAM-136`) e **oito** não; e **seis** dessas oito são de tickets ainda não executados (KAM-130, KAM-133 a KAM-135, KAM-137, KAM-138), onde o anexo é parte da execução futura e não um defeito. Só o KAM-128 e o KAM-129 estão entregues com a promessa por cumprir.

### Objectivo

Fechar a primeira linha de DoD do KAM-128 e do KAM-129 por uma das duas vias, decidida por quem a escreveu: escrever os dois anexos, ou emendar as duas linhas para remeterem para a secção de verificação do próprio bloco.

### Critérios de Aceitação

- [ ] **A escolha está escrita, com a razão e quem a aprovou:** escrever os dois anexos, ou emendar as duas linhas de DoD para remeterem para a secção «Verificação dos Critérios de Aceitação» do próprio bloco. Apresentam-se as duas, com a consequência de cada uma. **Decide o Arquitecto de Plataforma** — as linhas de DoD dos dois tickets estão assinadas «Equipa KAMBÁ», que não é uma pessoa, e `specs/01_Engineering_Standards_e_Handoff.md` §9 nomeia esse papel para os padrões. **Não se decide sozinho.**
- [ ] Se a via for **escrever**: `../docs/evidencia/KAM-128.md` e `../docs/evidencia/KAM-129.md` existem, na forma de `KAM-131.md` e `KAM-136.md` (tabela `| Campo | Valor |` com `Ticket`, `Ramo`, `PR`, `Data`, `Máquina`, e remissão para o bloco do ticket), e **cada número neles é reproduzido ou citado** da secção de verificação do bloco correspondente, com o comando. **Nenhuma medição nova é inventada.** O que não se puder reproduzir hoje aparece como tal, com a razão.
- [ ] Se a via for **emendar**: as duas linhas de DoD passam a remeter para a secção de verificação do próprio bloco, como o KAM-002 faz, e a emenda diz-se aplicável a estes dois tickets ou a todos — e nesse caso as outras **seis** linhas do epic são tratadas, ou ficam nomeadas como fora de âmbito.
- [ ] Os PR e os *commits* citados estão certos: o KAM-128 foi entregue no PR `albinoJimy/kamba#2` (trabalho em `08426f3`, fundido em `6eb618f`) e o KAM-129 no PR `albinoJimy/kamba#3` (fundido em `1401cd3`), como as secções de verificação dos próprios blocos dizem.
- [ ] A primeira linha de DoD de cada um dos dois tickets tem a sua medição escrita na secção de verificação do respectivo bloco: o que a via escolhida produziu, e o estado resultante. **As restantes caixas em aberto dos dois tickets não se tocam**: dependem do KAM-145 e do KAM-146, não deste ticket. A disposição da caixa é do DoD.
- [ ] O caminho usado nas duas linhas de DoD obedece à convenção que o **KAM-145** decidir; se este ticket entrar primeiro, mantém-se a forma dominante do ficheiro e diz-se que se fez assim.

### Detalhes Técnicos

- **Componentes:** `../docs/evidencia/` e os blocos KAM-128 e KAM-129 deste epic.
- **A fonte das medições é a secção «Verificação dos Critérios de Aceitação» de cada bloco**, e o `git show` dos *commits* que ela nomeia. Uma medição que hoje já não se reproduza — o estado de `main` mudou desde `1401cd3` — **cita-se com a data e o *commit* em que foi feita**, e nunca se refaz em silêncio contra outro estado.
- **A decisão tem alcance.** Emendar o padrão de DoD afecta as seis linhas de tickets ainda abertos; escrever os anexos fixa a expectativa para essas seis. Qualquer das duas sai do âmbito deste ticket se se tentar aplicar às seis — e isso fica dito, não feito.
- **O KAM-145, o KAM-146 e este ticket já seguem a via B, e isso não pré-julga a decisão.** A primeira linha de DoD dos três remete para a secção de verificação do próprio bloco, como o KAM-002, em vez de nomear um anexo. Foi uma escolha de redacção de tickets novos, registada aqui para que não passe por decisão tomada: se a via escolhida for a A, as três linhas mudam com as outras.
- **Fora de âmbito:** os anexos dos sete tickets não executados; as outras caixas em aberto do KAM-128 (**KAM-145**, **KAM-146**) e do KAM-129 (**KAM-145**); os cinco anexos `E1`–`E5` de `../docs/tecnica/evidencia/`, que são outra pasta e outra contagem.

### Testes Requeridos

- `ls docs/evidencia/` antes e depois, com a contagem no PR.
- *Script* que cruze cada linha de DoD do epic que nomeie um anexo de `../docs/evidencia/` com a existência do ficheiro → **0** tickets entregues com a promessa por cumprir.
- Cada número do anexo, se se escrever, rastreado à linha da secção de verificação de onde veio, ou ao comando que o reproduz.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis, com a leitura critério a critério numa secção «Verificação dos Critérios de Aceitação» deste bloco.
- [ ] A via escolhida aprovada pelo **Arquitecto de Plataforma** (`specs/01_Engineering_Standards_e_Handoff.md` §9); revisto por ≥ 1 revisor.
- [ ] Documentação actualizada: linha de «Controlo de versões» neste epic; Conventional Commits.
- [ ] **Sem segredos** — não aplicável.

### Handoff para Claude Code

```text
És o executor do ticket KAM-147 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-147, e os blocos KAM-128, KAM-129 e KAM-002).
Objectivo: fechar a primeira linha de DoD do KAM-128 e do KAM-129, que nomeia um anexo de evidência
que não existe.
- NÃO decidas a via sozinho: é de quem escreveu a linha do DoD. Escrever os dois anexos, ou emendar as
  duas linhas para remeterem para a secção de verificação do bloco, como o KAM-002 faz. Apresenta as duas
  com a consequência, e regista quem aprovou.
- NÃO INVENTES MEDIÇÕES. Tudo o que entrar num anexo é reproduzido com o comando, ou citado da secção de
  verificação do bloco com a data e o commit em que foi medido: o estado de main mudou desde então.
- Os PRs são o #2 (KAM-128) e o #3 (KAM-129), não outros.
- Toca só na primeira linha de DoD de cada um: as outras caixas em aberto são o KAM-145 e o KAM-146.
Não expandas escopo: os anexos dos sete tickets ainda não executados não são deste ticket, e os cinco
anexos E1-E5 são outra pasta.
Abre PR com o template do §7.
```

---

## KAM-148 — Leituras silenciosas nos outros dois leitores de YAML (`yamlreg` e `yamlsubset`)

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | M |
| Dependências | KAM-136 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma |
| Documentos de referência | `../docs/ci.md` §7 (lacuna 22), `../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md` §2 e §6, `../docs/evidencia/KAM-136.md`, `../docs/dividas-documentais.md` (linha 16), `tools/canon_lint/yamlreg.py`, `tools/secrets_inventory/yamlsubset.py`, `tools/lint_arch/tests/leitor_antes_do_kam136.py` |

### Contexto

O repositório tem **três** leitores de subconjunto de YAML sem dependências, e cada um tem a sua razão escrita no *docstring*. Nenhum é redundante, e nenhum é acidente:

| Leitor | O que lê | Porque não é o `kamba_yaml` |
|---|---|---|
| `tools/kamba_yaml.py` | os `ci/*.yaml`, `canon/*.yaml`, `tools/blocklist.yaml` e os `services/*/egress.yaml` | é o leitor de base: corre no *hook* de *pre-commit* e no *gate* 9, antes de qualquer instalação |
| `tools/canon_lint/yamlreg.py` | os `registry/*.yaml` do AgentRegistry (superfície 3 do *gate* 3b): `id` de vertical, `entitlements`, `subscriptions[].tipo` e `versao`, `tools[]` | os manifestos usam **estilo de fluxo** (`- { tipo: payment.confirmed, versao: 1 }`, `../docs/tecnica/02` §5.1), que o `kamba_yaml` recusa de propósito. Alargá-lo tornaria mais permissivo o leitor que corre no *pre-commit* |
| `tools/secrets_inventory/yamlsubset.py` | `../ops/secrets-inventory.yaml` (429 linhas) | o inventário precisa de listas em estilo de fluxo **com conteúdo** (`ambientes`, `consumidores`), que o `kamba_yaml` também recusa |

O **KAM-136** varreu **um**: das 101 construções que classificou por execução, **56 liam mal sem o dizer** — 46 passaram a recusa e 10 a leitura correcta, e 5 recusas que recusavam de mais foram desfeitas. Os outros dois **nunca foram varridos** à procura da mesma classe de defeito: construções que o leitor interpreta mal **sem o dizer**. Está registado como lacuna 22 de [`../docs/ci.md`](../docs/ci.md) §7 e como decisão devolvida ao fundador no bloco do KAM-136.

**A mesma classe de defeito está nos dois, e isso está medido, não suposto.** Uma sonda de 15 construções contra cada leitor, corrida antes de se abrir este ticket (estado: **CONFIRMADO**; a forma do comando está nos Detalhes Técnicos):

| Construção | `yamlreg.ler` | `yamlsubset.load` |
|---|---|---|
| `a: FALSE` | `'FALSE'` — cadeia **verdadeira** em Python, quando o YAML 1.2 *core* resolve `false` | `'FALSE'` |
| `a: NULL` | `'NULL'` | `'NULL'` |
| `a: 1.5` | `'1.5'` — um limiar que rebenta longe do sítio do erro, ou passa | `'1.5'` |
| `a: 0x1f` | `'0x1f'` (o *core* resolve 31) | `'0x1f'` |
| `a: +5` | `'+5'` (o *core* resolve 5) | `5` — lê bem |
| `a: ١٢٣` | `123` — o `int()` aceita algarismos Unicode; o YAML não | `123` |
| `a: "abre e não fecha` | `'"abre e nao fecha'` — a aspa entra no texto; o YAML dá erro | idem |
| `a: "x" extra` | `'"x" extra'` — o YAML dá erro | idem |
| `a:` + `  - - x` (lista aninhada) | `['- x']` — a sequência interior vira cadeia | recusa |
| `id: nao e' assim # comentario` | `"nao e' assim # comentario"` — o apóstrofo abre uma aspa e o comentário entra no valor | lê bem |
| `a: 1` + `a: 2` (chave de topo repetida) | recusa | **`{'a': 2}` — a segunda cala a primeira** |
| `a:b` (sem espaço) | recusa | `{'a': 'b'}` — torna-se um mapa |
| `- https://exemplo.ao/p` | lê bem (cadeia) | **`{'https': '//exemplo.ao/p'}` — é o caso 2 do KAM-136, vivo aqui** |
| `a: ["x, y", z]` | lê bem (dois itens) | **`['"x', 'y"', 'z']` — três itens em vez de dois** |
| `a: "tem # dentro"` | lê bem | lê bem |

**Dez** das quinze lêem mal em silêncio no `yamlreg`, **onze** no `yamlsubset`. Nenhuma falha e nenhuma avisa: as duas devolvem uma estrutura plausível e errada.

**O que isto custa.** No `yamlsubset`, uma chave de topo repetida que se cala é uma entrada do inventário de segredos que desaparece — um segredo sem `rotacao_dias`, sem `owner` e sem `consumidores`, num ficheiro cuja razão de existir é «não é uma intenção, é um teste que falha». No `yamlreg`, uma `versao` engolida é uma subscrição de evento sem versão, e o *gate* 3b deixa de ver nomes que estão no ficheiro.

**Assimetria dos corpora, e porque é que importa agora.** O `../ops/secrets-inventory.yaml` está vivo e é lido em cada execução. O `registry/` **não tem nenhum ficheiro de produção** — só um `README.md`; o conteúdo é do EPIC-03, e o corpus do `yamlreg` são hoje **quatro** *fixtures* de `tools/canon_lint/tests/fixtures/` (verificado por execução: as quatro lêem-se sem recusa; o `manifesto.yaml` da mesma pasta é lido pelo `kamba_yaml`, não por este leitor). Duas consequências, e as duas pertencem ao critério: a prova de equivalência tem de **dizer sobre que corpus correu** — zero ficheiros dão zero divergências, e o critério ficaria satisfeito pela razão errada — e **este é o momento mais barato para corrigir o `yamlreg`**, porque antes do primeiro manifesto nenhum manifesto é lido mal.

**A premissa é a do KAM-136: recusar o que não se entende.** Para um leitor cuja garantia escrita é «um ficheiro que este leitor não percebe **falha** o *gate*», falhar com «escalar em bloco não suportado nesta posição» é melhor resultado do que adivinhar a intenção, e muito mais barato de verificar. A escolha, caso a caso, é parte do ticket — e escreve-se.

### Objectivo

Deixar os dois leitores sem nenhum caso em que lêem mal sem o dizer: cada construção que não interpretam correctamente passa a ser recusada com mensagem que nomeia o ficheiro e a linha, ou passa a ser interpretada correctamente com teste que o prova — e a lista do que cada um recusa, no seu *docstring*, passa a ser verdadeira.

### Critérios de Aceitação

- [x] **A varredura corre por execução, caso a caso, contra cada um dos dois leitores.** As 101 construções do KAM-136 ([`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md) §2, com as 40 que a revisão independente acrescentou no §4) mais os casos próprios de cada um — estilo de fluxo no `yamlreg` (fluxo partido por várias linhas, `[` por fechar, chave repetida em fluxo, aspas e vírgulas dentro de fluxo, fluxo aninhado) e, no `yamlsubset`, o `partition(":")` que não exige espaço, a chave de topo repetida e o `split(",")` da lista de fluxo. Cada caso classificado pela **saída medida** — lê bem, recusa, ou lê mal em silêncio — e não por leitura do código. A tabela caso a caso vai no corpo do PR e na análise.
- [x] **Nenhum caso em que qualquer dos dois leia mal sem o dizer.** Cada construção da varredura ou é recusada com erro que nomeia ficheiro e linha, ou é lida correctamente com teste que o prova. O silêncio deixa de ser uma das saídas possíveis.
- [x] **A decisão entre recusar e interpretar está escrita caso a caso, com a razão.** Onde divergir da que o KAM-136 tomou para o mesmo caso, a divergência é justificada pelo corpus — um leitor que aceita estilo de fluxo não é o mesmo leitor — e não fica implícita.
- [x] **Equivalência campo a campo, com a cópia congelada do leitor anterior como oráculo**, uma por leitor, no padrão de [`leitor_antes_do_kam136.py`](../tools/lint_arch/tests/leitor_antes_do_kam136.py) e não um retrato em JSON, que envelheceria a cada edição dos ficheiros. O teste **diz sobre que corpus correu e quantos campos folha comparou**: `../ops/secrets-inventory.yaml` para o `yamlsubset`; para o `yamlreg`, os `registry/*.yaml` que existirem **mais** as *fixtures* de `tools/canon_lint/tests/`, com a contagem de cada grupo escrita. Zero ficheiros não satisfaz este critério.
- [x] **Cada cópia congelada é verificada como oráculo:** o teste prova que ela **ainda tem** os defeitos que este ticket corrige. Se os perder, deixou de ser oráculo e a equivalência passa a verde por construção.
- [x] **A recusa chega a quem chama como bloqueio nomeado, e a semântica fica escrita por consumidor.** Hoje, no `secrets_inventory` a recusa chega pela lista de erros de `carregar()`, e no `canon_lint` como `Achado(ILEGIVEL)` do *gate* 3b — por desenho declarado em `tools/canon_lint/registo.py` («um ficheiro que este leitor não percebe falha o *gate*»), e **não** como código 2 do KAM-136. O ticket decide se isso se mantém, escreve a razão e prova por execução o que ficar decidido. O que não é aceitável é uma recusa que não bloqueia nada.
- [x] **Nenhuma excepção escapa sem ser recusa.** Qualquer construção que faça um dos leitores rebentar com uma excepção que não é a sua (`TypeError`, `IndexError`, `RecursionError`, ou `UnicodeDecodeError` no caminho de quem lê o ficheiro) passa a `YamlIlegivel`/`YamlSubsetError` com ficheiro e linha. Foi um destes que no KAM-136 matava o *gate* com *traceback* e código 1.
- [x] **O *docstring* de cada leitor passa a dizer o que ele recusa**, com os casos deste ticket nomeados e a escolha de cada um escrita; **cada linha da lista tem um teste**. Inclui o «Limite conhecido» do `yamlsubset` sobre comentários de fim de linha: ou deixa de ser limite, ou passa a estar provado por teste.
- [x] **O resíduo da linha 16 de [`../docs/dividas-documentais.md`](../docs/dividas-documentais.md) fica pago:** o *docstring* do `tools/secrets_inventory/yamlsubset.py` cita `tools/lint_arch/yamlmini.py` **quatro vezes**, e esse módulo passou a `tools/kamba_yaml.py`; as quatro passam a citar o nome actual e a linha 16 é riscada no mesmo PR.
- [x] **Nenhuma dependência nova**, e nenhum ficheiro real reescrito para contornar os leitores: a correcção é nos leitores. Os três continuam três e continuam a correr antes de qualquer instalação.
- [x] **A lacuna 22 de `../docs/ci.md` §7 é fechada** com o que mudou, o que ficou aberto e os números da varredura; `../docs/ci.md` ganha linha de versão.

### Detalhes Técnicos

- **Componentes:** transversal (CI). Ficheiros: `tools/canon_lint/yamlreg.py`, `tools/secrets_inventory/yamlsubset.py`, os testes de `tools/canon_lint/tests/` e `tools/secrets_inventory/tests/`, uma cópia congelada por leitor sob `tests/`, `../docs/ci.md` §7 e `../docs/dividas-documentais.md`.
- **Confirmar primeiro, com um comando** — como no KAM-136, o «antes» da evidência é a estrutura errada que cada leitor devolve hoje, registada antes de se alterar uma linha. A forma da sonda que produziu a tabela do Contexto:

  ```bash
  python -c "import sys; sys.path.insert(0,'tools'); from canon_lint.yamlreg import ler; print(ler('a: FALSE'))"
  ```

- **O método reaproveita-se, não se reinventa.** A tabela está em [`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md) §2, repartida pelas cinco classes (as 40 construções que a revisão independente acrescentou estão no §4); a classificação é da máquina — correr o caso contra o leitor congelado **e** contra o actual, e classificar pela diferença. O padrão do oráculo, e o aviso de que o teste falhar não é defeito do teste, estão no *docstring* de `tools/lint_arch/tests/leitor_antes_do_kam136.py`.
- **Preferir recusar a interpretar**, pela razão do KAM-136: «cada regra que se implementa é uma regra que pode ficar errada». As duas excepções que lá se abriram — a dobra na posição de item de lista e o `:` não citado num item — não se aplicam ao `yamlreg`, que recusa escalares de bloco por desenho e cujo `_CHAVE` já exige espaço depois dos dois pontos; aplicam-se ao `yamlsubset`, onde as duas estão vivas.
- **Verificar, antes de recusar, que nenhum ficheiro real dispara a recusa nova**, por `grep` sobre o corpus, como no KAM-136. Medido na abertura deste ticket: o `../ops/secrets-inventory.yaml` não tem nenhuma das formas da tabela do Contexto — 0 ocorrências de `chave:valor` sem espaço, 0 de booleano ou nulo não-minúsculo, 0 de decimal, exponente ou hexadecimal, 0 de vírgula dentro de aspas em fluxo, 0 chaves de topo repetidas. É por isso que se espera **0 divergências** na equivalência, e é isso que mantém fora de jogo a condição dos dois revisores do DoD.
- **O `yamlreg` tem uma superfície que o `kamba_yaml` não tem:** o estilo de fluxo, com analisador próprio (`_Fluxo`). A varredura tem de o cobrir — é a parte do leitor sem equivalente no KAM-136 e, por isso, a que nunca ninguém mediu.
- **Fora de âmbito:** **fundir os três leitores num só** ou **adoptar uma biblioteca de YAML** — o `kamba_yaml` corre no *gate* 9 e no *hook* de *pre-commit* antes de qualquer instalação, e é essa a razão de existir dos três (KAM-001); alargar um leitor para absorver o corpus de outro, que é tornar mais permissivo o que corre no *pre-commit* e o que o *docstring* do `yamlsubset` recusa explicitamente; recusa de chaves desconhecidas, que é **KAM-134** para os `ci/*.yaml` e no `canon_lint` já existe por lista fechada; reescrever `../ops/secrets-inventory.yaml` ou as *fixtures*; criar manifestos `registry/*.yaml`, que são do EPIC-03.

### Testes Requeridos

- Unit: um teste por caso da varredura, em cada *suite*, a provar leitura correcta ou recusa com a linha na mensagem. No padrão de `TestVarreduraDaMesmaClasse` do KAM-136 (casos que lêem bem e casos que recusam, em dicionários nomeados), para que a lista do *docstring* e a lista dos testes sejam a mesma coisa.
- Equivalência: um teste por leitor contra a sua cópia congelada, sobre o corpus descoberto por *glob* e não fixado à mão, com a contagem de ficheiros e de campos folha na mensagem; e um teste que prova que a cópia congelada ainda tem os defeitos.
- Regressão do corpus: as quatro *fixtures* de `registry` e o `../ops/secrets-inventory.yaml` continuam a ler-se sem recusa, com a lista descoberta por *glob*.
- Mutação: as mutações novas de `db/mutacoes.py` para as linhas alteradas em cada leitor, corridas com `python db/mutacoes.py <python> <excerto>`; `python db/mutacoes.py --aplicaveis` verde. A lista inteira corre na tarefa nocturna (KAM-143).
- Integração: `make ci` verde; `make ci-3b` (as quatro superfícies e o canário) e as *suites* de `tools/canon_lint` e `tools/secrets_inventory` sobre os ficheiros reais.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `../docs/evidencia/KAM-148.md`, com a estrutura errada que cada leitor devolvia antes).
- [ ] Código revisto por ≥ 1 revisor, **2 se a leitura do `../ops/secrets-inventory.yaml` ou de uma *fixture* de `registry` mudar de resultado** — significaria que uma entrada do inventário de segredos ou uma subscrição de evento estava a ser lida errado; testes verdes.
- [x] Documentação actualizada: `../docs/ci.md` §7 (lacuna 22 fechada) e o *docstring* de cada leitor com a lista do que recusa; linha 16 de `../docs/dividas-documentais.md` riscada; Conventional Commits.
- [x] **Sem segredos** — o ticket toca no leitor do inventário e não no inventário; nenhum valor entra em nenhum ficheiro.
- [x] **Dependências** — nenhuma nova, e os dois módulos continuam sem dependências por desenho.
- [x] Os casos varridos estão listados no PR, cada um com o seu resultado nos **dois** leitores (lê bem, recusa, ou corrigido aqui), e a revisão adversarial está em `../docs/analises/ANALISE-NN-KAM-148-leitores-de-yaml.md`.

### Handoff para Claude Code

```text
És o executor do ticket KAM-148 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (blocos KAM-148 e KAM-136), docs/ci.md §7 (lacuna 22),
docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md (a tabela das 101 construcoes, §2 e §4) e docs/evidencia/KAM-136.md.
Objectivo: nenhum caso em que o tools/canon_lint/yamlreg.py ou o tools/secrets_inventory/yamlsubset.py leiam
mal sem o dizer.
- O MÉTODO JÁ EXISTE: reaproveita a varredura do KAM-136, caso a caso, POR EXECUÇÃO e não por leitura. Corre
  cada caso contra a cópia congelada do leitor anterior E contra o actual, e classifica pela diferença.
- REPRODUZ PRIMEIRO. A tabela do Contexto deste bloco tem 15 construções confirmadas por sonda; registra a
  estrutura errada de cada uma antes de alterar uma linha. É o «antes» da evidência.
- PREFERE RECUSAR A INTERPRETAR, e escreve a razão caso a caso. Onde divergires da decisão do KAM-136 para o
  mesmo caso, justifica pelo corpus.
- O yamlreg tem estilo de fluxo (_Fluxo), que o KAM-136 nunca mediu: fluxo partido por linhas, `[` por fechar,
  chave repetida em fluxo, aspas e vírgulas dentro de fluxo, fluxo aninhado.
- O yamlsubset tem três defeitos próprios já confirmados: a chave de topo repetida cala a primeira em silêncio;
  o partition(":") não exige espaço (`a:b` vira mapa, e `- https://x` vira {'https': '//x'}, que é o caso 2 do
  KAM-136 vivo aqui); e o split(",") da lista de fluxo parte `["x, y", z]` em três itens.
- EQUIVALÊNCIA CAMPO A CAMPO, uma cópia congelada por leitor, no padrão de
  tools/lint_arch/tests/leitor_antes_do_kam136.py. O teste TEM DE DIZER sobre que corpus correu e quantos campos
  comparou: registry/ não tem nenhum ficheiro de produção (só README.md), e o corpus do yamlreg são as quatro
  fixtures de tools/canon_lint/tests/fixtures/. Zero ficheiros = zero divergências = critério satisfeito pela
  razão errada. E prova que cada cópia congelada AINDA TEM os defeitos.
- A RECUSA TEM DE BLOQUEAR, e a semântica escreve-se por consumidor: no canon_lint a recusa é Achado(ILEGIVEL)
  por desenho declarado em registo.py; no secrets_inventory chega pela lista de erros de carregar(). Decide se
  se mantém, escreve a razão, prova por execução.
- PAGA A LINHA 16 de docs/dividas-documentais.md: o docstring do yamlsubset cita tools/lint_arch/yamlmini.py
  quatro vezes, e o módulo passou a tools/kamba_yaml.py.
- Fecha a lacuna 22 de docs/ci.md §7 com os números da varredura.
Não expandas escopo: NÃO fundas os três leitores, NÃO adoptes uma biblioteca de YAML (o gate 9 e o hook de
pre-commit correm antes de qualquer instalação, e é a razão de existir dos três), não alargues um leitor para
absorver o corpus de outro, não reescrevas ops/secrets-inventory.yaml nem as fixtures, não cries manifestos
registry/*.yaml (EPIC-03). Recusa de chaves desconhecidas em ci/*.yaml é KAM-134.
Testes: um por caso varrido em cada suite; equivalência por leitor com o seu oráculo; mutações novas; make ci verde.
Abre PR com o template do §7.
```

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#55_KAM144`, ramo
`feature/KAM-148-varredura-dos-outros-dois-leitores`, **empilhado** no
`feature/KAM-136-leitor-de-yaml-sem-silencios` por decisão do fundador
(2026-10-12), por o KAM-136 ainda não estar em `main`. **Dezesseis caixas
marcadas, uma vazia** — a dos revisores humanos. Os números são os **de
depois** da revisão adversarial independente, que chegou a «não cumpre ainda os
critérios de aceitação» com **treze achados, um P0 e quatro P1**, todos fechados
neste ramo: o corpus passou de 208 para 240 construções, as leituras silenciosas
fechadas de 95 para 110, a equivalência de 507 para 525 campos folha e as
mutações de 30 para 46. Os números estão em
[`../docs/evidencia/KAM-148.md`](../docs/evidencia/KAM-148.md), com o comando ao
lado de cada um; a revisão adversarial está em
[`ANALISE-13`](../docs/analises/ANALISE-13-KAM-148-leitores-de-yaml.md).

| CA | Estado | Evidência |
|---|---|---|
| 1 — a varredura corre por execução, caso a caso | **satisfeito** | **240 construções** classificadas pela diferença entre a cópia congelada de cada leitor e o actual, não por leitura: 131 no `yamlreg` (35 já recusava, 38 já lia bem, 49 silêncio→recusa, 9 silêncio→lê bem) e 109 no `yamlsubset` (28, 27, 47, 5, mais 2 recusas que recusavam de mais e passaram a ler). O corpus vive em `tools/canon_lint/tests/corpus_yamlreg.py` e `tools/secrets_inventory/tests/corpus_yamlsubset.py` e **é o mesmo** que os testes permanentes usam, para que a lista do que se recusa e a lista dos testes não possam divergir. Tabela construção a construção em evidência §10 |
| 2 — nenhum caso lê mal em silêncio | **satisfeito** | **110 leituras silenciosas fechadas** (96 por recusa, 14 por leitura correcta), e a varredura final não deixa nenhuma: `test_cada_caso_tem_o_resultado_declarado` nas duas *suites*. **Quinze delas vieram da revisão independente** e não da varredura: `@a: 1`, `` `a: 1 `` e `%YAML: 1` liam-se como chaves (achado A4), `a: ]`, `a: }`, `a: ,` e `a: ?` como cadeia (A5), e `a:` sozinho dava `[]` em vez de nulo (A6). As piores eram a **chave de topo repetida** no `yamlsubset`, que calava a primeira — no inventário de segredos, uma entrada que desaparece — e o `FALSE` lido como a cadeia `"FALSE"`, verdadeira em Python |
| 3 — a decisão está escrita caso a caso, com a razão | **satisfeito** | **18 decisões** em evidência §3, mais uma tabela própria das **seis divergências** face ao KAM-136, cada uma justificada pelo corpus e não pelo gosto. A revisão encontrou **duas decisões tomadas e não escritas** — a classe de nomes de chave do `yamlsubset` (A2) e a recusa do item de lista com chave citada no `yamlreg` (A8) —, e as duas eram **recusas que recusavam de mais**: desfizeram-se, em vez de se escreverem. A mais importante: `- https://x` lê-se como cadeia no `kamba_yaml` e **recusa-se** no `yamlsubset`, porque este não tem itens de lista escalares — a cadeia não teria onde ser lida |
| 4 — equivalência campo a campo, com o corpus nomeado | **satisfeito** | **0 divergências** em **525 campos folha**: 418 do `ops/secrets-inventory.yaml`, 50 nas quatro *fixtures* da superfície 3, e 57 nos dois manifestos de `docs/tecnica/02` §5.1 — a forma que o EPIC-03 vai escrever, lida do próprio documento e não de uma cópia, que é hoje a melhor resposta à pergunta «e se uma recusa nova recusar de mais?». O teste **nomeia o corpus e conta os campos**, e a evidência diz o que o critério exige que se diga: o `registry/` não tem hoje nenhum ficheiro de produção (o conteúdo é do EPIC-03), pelo que zero ficheiros dariam zero divergências. O corpus descobre-se por *glob*: o primeiro manifesto entra sem se alterar uma linha |
| 5 — o oráculo é verificado como oráculo | **satisfeito** | `test_o_leitor_congelado_ainda_tem_os_defeitos`: **7 defeitos** por leitor que a cópia congelada tem de continuar a devolver, e o teste prova também que o leitor de hoje **não** os devolve. Sem isto, a equivalência passava a verde por construção no dia em que alguém «arrumasse» a cópia |
| 6 — a recusa chega como bloqueio nomeado, e a semântica fica escrita | **satisfeito** | Três caminhos, provados por execução (evidência §5): no `canon_lint` a recusa é `Achado(ILEGIVEL)` com o caminho do ficheiro e **mantém-se** em código 1, porque um `registry/*.yaml` é o **objecto** que o *gate* analisa e não a sua configuração — ao contrário dos `ci/*.yaml` do KAM-136; no `secrets_inventory` chega pela lista de erros de `carregar()`, com ficheiro e linha, e faz falhar `TestInventarioReal.test_esquema_valido`. **Corrigido aqui:** o subcomando `ficheiro` do `canon_lint` morria com *traceback* e código 1 num ficheiro que não fosse UTF-8 — é o defeito que o KAM-136 fechou no `load_file`, vivo na única leitura que não passa pelo `_ler` |
| 7 — nenhuma excepção escapa sem ser recusa | **satisfeito, depois de ter estado marcado e falso** | Esta caixa esteve marcada com o defeito presente, e é o achado **P0** da revisão: o `yamlreg` deixava escapar um **`RecursionError`** com **400 linhas de YAML de bloco perfeitamente comum** (ou ~500 níveis de fluxo), e o *gate* 3b morria com *traceback* e código 1 — o modo de falha que o critério nomeia. O teste que o devia apanhar estava **verde**, porque mutações de um a três caracteres nunca constroem profundidade. Fechado com `_PROFUNDIDADE_MAXIMA = 50` nos dois caminhos, contado em **níveis** e não em chamadas (contar chamadas recusaria uma lista de 60 itens), com a linha na mensagem, quatro casos no corpus e duas mutações próprias. A prova por fuzz — 30 000 mutações por leitor, 0 excepções que não a do leitor — **continua a valer para o que mede**, a superfície de texto, e isso está agora escrito em evidência §6 em vez de insinuado |
| 8 — o *docstring* diz o que recusa, com um teste por linha | **satisfeito** | Os dois *docstrings* reescritos em dois grupos (estrutura e escalares), com os casos deste ticket nomeados e a escolha de cada um escrita; cada linha tem o seu caso no corpus. A verificação linha a linha foi feita **duas vezes**: a auto-validação encontrou nove linhas sem caso, e a revisão independente encontrou **mais seis problemas na mesma lista** — duas frases falsas (`@a: 1` em posição de chave, A4; «listas aninhadas, estrutura que este leitor não tem», que ele tem em fluxo, A11), uma regra mais larga do que o prometido (A9), uma restrição que existia e não estava escrita (A2), um número errado (A12) e o `DEL` sem caso próprio (A13). É a terceira vez neste par de tickets que esta lista mente, e por isso cada linha tem agora caso **e** a mensagem tem asserção. O «Limite conhecido» do `yamlsubset` deixou de ser limite: a regra que ele descrevia **é** a do YAML (num escalar plano, ` #` abre comentário) e passou a estar provada nos dois sentidos, com o caso ambíguo — aspa aberta antes de um `#` — a recusar |
| 9 — a linha 16 das dívidas documentais fica paga | **satisfeito** | `grep -c yamlmini tools/secrets_inventory/yamlsubset.py` → **0**; as quatro ocorrências passaram a `tools/kamba_yaml.py`. Linha 16 riscada em `../docs/dividas-documentais.md`, com linha de versão 1.6 |
| 10 — nenhuma dependência nova, nenhum ficheiro real reescrito | **satisfeito** | O `yamlsubset` ganha `import re` (biblioteca padrão), pelas mesmas regras numéricas do `kamba_yaml`; nos testes entram `contextlib`, `io`, `random` e `tempfile`, todos padrão. Nenhum `requirements*.txt`, `package.json` ou `pnpm-lock.yaml` tocado, e nem o `ops/secrets-inventory.yaml` nem as *fixtures* aparecem no `git diff --stat`: a correcção é nos leitores |
| 11 — a lacuna 22 de `../docs/ci.md` §7 é fechada | **satisfeito** | Riscada e fechada com os números da varredura, o que se interpretou e o que se recusou, e **o que fica dito e não fechado** (o `registry/` vazio e os três leitores que continuam três); `../docs/ci.md` com linha de versão 1.16 |
| DoD — todos os CA satisfeitos; evidência com o «antes» | **satisfeito** | Os onze. A estrutura errada de cada construção está em evidência §1, reproduzida antes de se alterar uma linha |
| DoD — ≥ 1 revisor, **2 se a leitura mudar de resultado**; testes verdes | **não satisfeito** | **Zero revisores humanos.** A revisão adversarial independente ([`ANALISE-13`](../docs/analises/ANALISE-13-KAM-148-leitores-de-yaml.md)) é evidência, não é um revisor. A condição dos 2 revisores **não se aplica**: nenhuma leitura mudou de resultado (CA 4, 0 divergências em 525 campos folha). Testes verdes: `canon_lint` 182/182, `secrets_inventory` 77/77, `lint_arch` 197/197 |
| DoD — documentação; lacuna 22; dívida 16; Conventional Commits | **satisfeito** | CA 9 e CA 11, mais o *docstring* de cada leitor (CA 8); *commits* `fix(KAM-148)` e `docs(KAM-148)`, validados pelo `lint_arch` no *hook* |
| DoD — sem segredos | **satisfeito** | O ticket toca no leitor do inventário e não no inventário; nenhum valor entra em nenhum ficheiro, e o *gate* 9 corre sobre o diff em cada *commit* (*hook* de *pre-commit*) |
| DoD — dependências: nenhuma nova | **satisfeito** | CA 10 |
| DoD — casos listados no PR, com o resultado nos dois leitores | **satisfeito** | A tabela das 240 construções está em evidência §10 e no corpo do PR, cada uma com o que o leitor devolvia antes e o que faz agora |

#### Decisões tomadas aqui, e porquê

| # | Decisão | Razão |
|---|---|---|
| 1 | O corpus da varredura **é** o corpus dos testes, num módulo próprio por leitor | A alternativa era escrever os casos três vezes (varredura, testes, análise) e deixá-los divergir. Assim, a lista do que cada leitor recusa, a lista dos testes e a tabela da evidência saem todas do mesmo sítio |
| 2 | As regras de escalar vêm do `kamba_yaml` depois do KAM-136, à letra | São a decisão já tomada e já revista para a mesma classe de defeito. Reinventá-las produziria três leitores com três respostas para `0644`, que é precisamente o defeito que isto fecha |
| 3 | Onde o corpus manda, divergiu-se do KAM-136 — e escreveu-se | Seis divergências, em evidência §3. Um leitor que aceita estilo de fluxo e outro que só aceita «mapa de topo → lista de mapas» não podem ter a mesma resposta para um item de lista escalar |
| 4 | A recusa do `canon_lint` **continua** a ser achado (1) e não erro de configuração (2) | Um `registry/*.yaml` é o objecto que o *gate* 3b analisa; os `ci/*.yaml` do KAM-136 são a configuração do próprio *gate*. «Não consigo verificar» aplica-se à configuração, não ao objecto — e o `registo.py` já declarava isto desde o KAM-111 |
| 5 | O teste **não** exige que o `registry/` continue vazio | Seria fazer falhar o ticket do EPIC-03 que escrever o primeiro manifesto. O corpus descobre-se por *glob* e cresce sozinho; o que o teste garante é que há corpus e quantos campos tem |
| 6 | A prova por mutação dos dois leitores vive em `tools/canon_lint/tests/mutacoes_dos_leitores.py` | O `db/mutacoes.py` copia `db/` e levanta PostgreSQL por mutação, e nenhuma *suite* de `db/` lê por estes leitores. Alargar aquele corredor é trabalho com medição própria (KAM-142/KAM-143). Dentro de `tests/` porque o `coverage-python` omite `*/tests/*` e o `discover` só recolhe `test_*.py`: um módulo que ninguém importa não faz a cobertura descer |
| 7 | Os caracteres invisíveis entram no código como escapes, não literais | Uma primeira versão deixou o BOM, o `U+2028` e os algarismos árabes **literais** dentro de cadeias do código. Funcionava e era ilegível; nas linhas de prosa ficam como estão, que ali são legíveis |
| 8 | O limite de profundidade conta **níveis**, não chamadas, e é 50 | Contar chamadas recusaria uma lista de 60 itens, que é aninhamento 1 — seria uma recusa que recusa de mais introduzida para fechar um P0. Cinquenta é dez vezes o que os manifestos de `../docs/tecnica/02` §5.1 usam, e o limite do Python chega aos ~400: o espaço entre os dois é a margem |
| 9 | A classe de nomes de chave é **negativa**, nos dois leitores | A lista positiva `[A-Za-z_][A-Za-z0-9_.-]*` que uma primeira versão pôs no `yamlsubset` recusava `rotação_dias:`. Num repositório inteiramente em português, uma chave acentuada não é um caso exótico — é a forma por omissão. O que fica de fora são os indicadores do YAML e o `#`, e isso está escrito |
| 10 | Uma recusa nomeada tem de ter **asserção na mensagem** | Duas mutações sobreviveram por isto: apagar a recusa nomeada do indicador em posição de chave deixava o caso a recusar — pela mensagem genérica. Um teste que só verifica «recusou» não distingue a regra certa da errada, e é a forma fina do «verde pela razão errada» |

#### Decisões devolvidas

| # | O que | A quem |
|---|---|---|
| 1 | **Os três leitores passam a ter as mesmas ~60 linhas de regras de escalar** (`_INTEIRO`, `_PARECE_NUMERO`, `_AMBIGUOS`, `_CONTROLO`, `_QUEBRAS_AMBIGUAS`, o tratamento de aspas). Foi deliberado — divergirem seria o defeito — mas a duplicação é real e vai divergir com o tempo. Um módulo partilhado **só com as regras de escalar** não torna nenhum leitor mais permissivo, que é a razão pela qual os três existem separados; fundir os leitores, isso sim, está fora de âmbito. Vale um ticket? | Ao fundador |
| 2 | **A prova por mutação destes dois leitores corre-se à mão.** O corredor nocturno do KAM-143 cobre as *suites* de `db/`; esta não entra lá, e uma sobrevivente nova só aparece se alguém correr o script | A quem mantém o KAM-143 |
| 3 | **Uma recusa do *gate* 3b sobre um `registry/*.yaml` sai com código 1 e a do *gate* 9 sobre um `ci/*.yaml` com 2.** A razão está escrita (decisão 4) e é defensável, mas se o fundador quiser um só código para «não consegui ler», é decisão dele e muda os dois | Ao fundador |

---

## KAM-150 — Regras de `CODEOWNERS` penduradas no prefixo que o KAM-128 removeu

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-128 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `CODEOWNERS`, este epic (verificação do KAM-128, linha do DoD «todo o caminho citado resolve»), `../docs/seguranca/lacunas.md` (L-19), `../docs/seguranca/riscos_residuais.md` (RR-05), `../docs/seguranca/ameacas_stride.md` (GOV-T), `../docs/ci.md` §7 (lacuna 16), `.github/rulesets/main.json`, `tools/lint_arch/structure.py` |

### Contexto

O KAM-128 moveu o conjunto documental da raiz para `docs/`. As referências dentro
dos `.md` foram reescritas e medidas; o `CODEOWNERS` não, porque não é um `.md` e
nenhuma das buscas de regressão G1–G3 desse ticket o varre. Ficaram três regras
presas ao prefixo antigo:

```
/tecnica/                     @kamba/plataforma
/tecnica/evidencia/           @kamba/plataforma @kamba/seguranca
/tecnica/08_Seguranca_Conformidade.md  @kamba/seguranca
```

**Uma regra de `CODEOWNERS` que aponta para um caminho inexistente não atribui
dono nenhum, e não avisa.** Não é um erro de sintaxe que o GitHub recuse: é um
padrão que nunca casa. O efeito é o oposto do que o ficheiro existe para fazer —
`docs/tecnica/` e `docs/tecnica/evidencia/` caíram na regra geral `*`
(@kamba/plataforma), e o documento 08 de segurança perdeu o dono de Segurança que
a regra específica lhe dava. É um caminho funcional, não prosa, e por isso não é
dívida documental: é defeito com ticket.

O defeito está declarado fora de âmbito na secção «Verificação dos Critérios de
Aceitação» do KAM-128, neste epic, onde deixa o DoD «**Referências** — todo o
caminho citado resolve» por marcar. Está também em `../docs/seguranca/lacunas.md`
(L-19), em `../docs/seguranca/riscos_residuais.md` (RR-05) e em
`../docs/seguranca/ameacas_stride.md` (GOV-T), sempre misturado com uma segunda
afirmação que **este ticket não resolve**: que nada impõe a revisão por dono de
área. São dois factos independentes, e convinha separá-los — corrigir os caminhos
não faz o ficheiro bloquear nada.

**O que a medição acrescenta ao aviso do cabeçalho.** O cabeçalho já avisava que
as equipas `@kamba/*` são *proposta* «enquanto a organização do GitHub não
existir». A verificação confirma o aviso e aperta-o: `gh repo view` dá
`isInOrganization: false` — o repositório é de um utilizador, logo **nenhuma**
equipa pode existir, e `gh api orgs/kamba/teams` devolve 404. Além disso o
*ruleset* de `main` tem `require_code_owner_review: false` e
`required_approving_review_count: 0`. O aviso continua a fazer sentido; o que lhe
faltava era dizer que, mesmo com caminhos e donos certos, o ficheiro não impõe
revisão — para que a correcção dos caminhos não se leia como imposição
restaurada.

### Objectivo

As regras do `CODEOWNERS` apontam todas para caminhos que existem, verificado por
comando e não por leitura, e os documentos que afirmavam o contrário deixam de o
afirmar — sem tocar em quem impõe a revisão, que é decisão de governação.

### Critérios de Aceitação

- [x] **As três regras apontam para os caminhos reais** — `/docs/tecnica/`,
  `/docs/tecnica/evidencia/` e `/docs/tecnica/08_Seguranca_Conformidade.md` — com
  os mesmos donos que tinham. Nenhum dono muda neste ticket.
- [x] **Nenhuma regra do ficheiro fica pendurada**, e isso é medido sobre
  **todas** as regras, não só sobre as três: o comando do critério percorre cada
  linha não-comentário, resolve o padrão contra a árvore e lista as que não
  existem. Antes: 3 de 18. Depois: 0 de 18.
- [x] **O aviso do cabeçalho é reavaliado contra o estado medido** e passa a dizer
  que o ficheiro não impõe revisão, com a razão e a fonte: repositório de
  utilizador (sem equipas possíveis) e *ruleset* com
  `require_code_owner_review: false`.
- [x] **Os documentos que afirmavam caminhos inexistentes deixam de o afirmar**
  (L-19, RR-05, GOV-T), e a segunda afirmação de cada um — que nada impõe a
  revisão — **mantém-se**, porque continua verdadeira.
- [x] **Nenhuma regra nova, nenhum dono novo, nenhuma alteração ao *ruleset*.** O
  diff do `CODEOWNERS` é três caminhos e um bloco de comentário.

### Detalhes Técnicos

- **Componentes:** transversal (governação do repositório); sem código de
  *runtime*, sem migrações, sem dependências novas. Ficheiros: `CODEOWNERS`,
  `specs/INDICE.md`, `specs/EPIC-01_Fundacoes_Dados.md`, `README.md`,
  `../docs/seguranca/lacunas.md`, `../docs/seguranca/riscos_residuais.md`,
  `../docs/seguranca/ameacas_stride.md`, `../docs/dividas-documentais.md`,
  `../docs/evidencia/KAM-150.md`.
- **Confirmar primeiro, com um comando.** A medição é esta, e corre antes e depois
  (nenhuma saída = conforme):

```bash
grep -vE '^\s*#|^\s*$' CODEOWNERS | awk '{print $1}' | while read -r p; do \
  t="${p#/}"; t="${t%/}"; \
  if [ "$p" != "*" ] && [ ! -e "$t" ]; then echo "INEXISTENTE: $p"; fi; done
```

  Duas ressalvas de leitura, escritas porque o comando as esconde: o padrão `*` é
  excluído por não ser um caminho, e um padrão de `CODEOWNERS` pode casar sem ser
  um caminho literal (`*.md`, `**/x`). Nenhuma das 18 regras deste ficheiro usa
  curingas no meio, pelo que a equivalência «padrão resolve» ↔ «caminho existe»
  vale hoje e deixaria de valer se alguma regra passasse a usar curingas. Um gate
  que o imponha é trabalho próprio (ver «Fora de âmbito»).
- **Porque não foi apanhado antes.** `tools/lint_arch/structure.py` tem
  `"CODEOWNERS"` em `REQUIRED_FILES`: verifica que o ficheiro **existe**, nunca lê
  uma linha dele. O gate 3 (`tools/lint_refs`) valida *tokens* `KAM-NNN`,
  `ADR-NNN` e `D#`, não caminhos. As buscas G1–G3 do KAM-128 varrem `.md`. Entre
  os três, nenhum olha para dentro deste ficheiro — e é por isso que o defeito
  sobreviveu a dois tickets que mediram referências.
- **Fora de âmbito:**
  - **Um gate que valide os caminhos do `CODEOWNERS`.** É a prevenção natural
    deste defeito e é código com testes (ampliar `tools/lint_arch/structure.py`,
    que já conhece o ficheiro). Não cabe num `fix` de S; fica registado aqui como
    o trabalho que impede a recorrência.
  - **Substituir as equipas `@kamba/*` por utilizadores reais** e **dar dono de
    Segurança a `docs/seguranca/`** (segunda parte do remédio de L-19): decisão de
    governação, não de caminho.
  - **Repor aprovações exigidas ou `require_code_owner_review`** — é o *ruleset*,
    e é **KAM-137**, que por sua vez declarou o `CODEOWNERS` fora do seu âmbito.
    Este ticket fecha o lado que o KAM-137 deixou de fora; o lado do *ruleset*
    continua lá.
  - **As sete referências nuas à biblioteca exploratória e as onze linhas de
    «Controlo de versões» em falta do KAM-128.** São os outros dois defeitos
    declarados na mesma secção de verificação do KAM-128, e são distintos deste.
    Por isso o DoD «**Referências**» do KAM-128 **continua por marcar** depois
    deste ticket: tinha duas causas e este fecha uma.
  - **O que o `README.md` afirma sobre imposição** («Revisão por dono de área —
    imposta por `CODEOWNERS`»): é resíduo textual, não caminho, e vai para
    `../docs/dividas-documentais.md`.

### Testes Requeridos

- O comando do critério 2 sobre **todas** as regras, antes e depois, com a
  contagem no PR. Não há teste unitário a acrescentar: o ficheiro não é lido por
  código nenhum.
- Regressão: `grep -cPo '(?<!docs)/tecnica/' CODEOWNERS` → **0**.
- `make lint-arch` verde (o `CODEOWNERS` continua em `REQUIRED_FILES`).
- Gate 3 (`make ci-3`) verde depois de o ticket entrar nos dois lados do backlog —
  é o que prova que o ID novo resolve e que nenhum ID citado deixou de existir.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em
  [`../docs/evidencia/KAM-150.md`](../docs/evidencia/KAM-150.md)).
- [ ] Revisto por ≥ 1 revisor; **2 revisores por tocar num ficheiro de regra de
  revisão**, mesmo que a medição mostre que hoje não impõe nada; testes verdes.
- [x] Documentação actualizada: `../docs/seguranca/lacunas.md` (L-19),
  `../docs/seguranca/riscos_residuais.md` (RR-05),
  `../docs/seguranca/ameacas_stride.md` (GOV-T), `README.md` e as contagens de
  `specs/INDICE.md`; *Conventional Commits*.
- [x] **Sincronia mestre↔epics** — a linha de `specs/INDICE.md` §4 e este bloco
  dizem o mesmo; reciprocidade com o `Bloqueia` do KAM-128 fechada.
- [x] **Referências** — todo o caminho citado resolve, e nenhum `KAM-NNN`,
  `ADR-NNN` ou `D#` citado deixou de existir (gate 3 verde).
- [x] **Sem segredos** — não aplicável: o ticket não acrescenta configuração nem
  dependências.
- [x] Defeitos e resíduos encontrados fora do âmbito registados, não corrigidos
  aqui (`specs/01_Engineering_Standards_e_Handoff.md` §6).

### Handoff para Claude Code

```text
És o executor do ticket KAM-150 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-150 e a verificacao do KAM-128) e docs/seguranca/lacunas.md (L-19).
Objectivo: nenhuma regra de CODEOWNERS aponta para um caminho que nao existe.
- MEDE PRIMEIRO, sobre todas as regras, com o comando do criterio 2; guarda a saida.
- Corrige /tecnica/ -> /docs/tecnica/ nas tres regras, sem mudar nenhum dono.
- Reavalia o aviso do cabecalho contra o estado medido (gh repo view; .github/rulesets/main.json).
- Corrige o que L-19, RR-05 e GOV-T afirmam dos caminhos; NAO toques no que afirmam da imposicao.
Nao expandas escopo: nao crias gate, nao mexes no ruleset (KAM-137), nao substituis as equipas por
utilizadores, nao tratas as referencias nuas nem as linhas de versao em falta do KAM-128.
Testes: o comando antes e depois; grep de regressao a 0; make lint-arch e make ci-3 verdes.
Abre PR com o template do §7.
```

### Verificação dos Critérios de Aceitação

Entregue no ramo `fix/KAM-150-codeowners-no-prefixo-removido`, a partir de
`origin/main` (`f10bde8`), com `origin/main` integrado por *merge* depois do
KAM-132 (`f4c7e3d`) — integração que a revisão adversarial obrigou, porque o
`main` entretanto tocou dois dos ficheiros deste changeset e a linha de versão
1.16 do epic colidia. **Onze caixas marcadas, uma vazia** — a dos revisores
humanos. Os números estão em
[`../docs/evidencia/KAM-150.md`](../docs/evidencia/KAM-150.md), com o comando ao
lado de cada um; a revisão adversarial está em
[`ANALISE-17`](../docs/analises/ANALISE-17-KAM-150-codeowners-pendurado.md).

| CA | Estado | Evidência |
|---|---|---|
| 1 — as três regras apontam para os caminhos reais, com os mesmos donos | **satisfeito** | `git diff CODEOWNERS` → 3 linhas de regra alteradas, **só o caminho**: os conjuntos de donos antes e depois são idênticos linha a linha (`@kamba/plataforma`; `@kamba/plataforma @kamba/seguranca`; `@kamba/seguranca`). As 15 regras restantes, byte a byte iguais |
| 2 — nenhuma regra pendurada, medido sobre todas | **satisfeito** | Comando do critério sobre as **18** regras não-comentário: em `main` (`git show main:CODEOWNERS`) **3 INEXISTENTE** (as três de `/tecnica/`); no ramo **0**. Regressão `grep -cPo '(?<!docs)/tecnica/' CODEOWNERS` → **0** |
| 3 — aviso do cabeçalho reavaliado contra o estado medido | **satisfeito** | `gh repo view albinoJimy/kamba --json isInOrganization` → `false` (repositório de **utilizador**: nenhuma das **6** equipas `@kamba/*` distintas pode existir); `gh api orgs/kamba/teams` → **404**; `.github/rulesets/main.json` → `require_code_owner_review: false`, `required_approving_review_count: 0`. O aviso **mantém-se válido** e ganhou um parágrafo com estes três factos |
| 4 — L-19, RR-05 e GOV-T deixam de afirmar caminhos inexistentes; a afirmação sobre imposição mantém-se | **satisfeito** | Três edições cirúrgicas, uma por documento: em cada uma, a oração dos caminhos passa a dizer que o KAM-150 os corrigiu, e a oração das 0 aprovações / «nada o impõe» fica intacta. Busca por «caminhos que já não existem» em `docs/seguranca/` → **0**; as orações de imposição, inalteradas nos três |
| 5 — nenhuma regra nova, nenhum dono novo, nenhuma alteração ao *ruleset* | **satisfeito** | `CODEOWNERS`: 18 regras antes, **18** depois; conjunto de donos idêntico (6 equipas). `git diff --stat .github/` → **vazio** |
| DoD — todos os CA satisfeitos, evidência em `../docs/evidencia/KAM-150.md` | **satisfeito** | Os cinco acima; o ficheiro de evidência existe e tem o comando de cada número |
| DoD — ≥ 1 revisor, **2 por tocar em ficheiro de regra de revisão**; testes verdes | **não satisfeito** | **Zero revisores humanos**, como em todos os tickets até aqui: o *ruleset* de `main` exige 0 aprovações, por decisão do fundador. A revisão adversarial ([`ANALISE-17`](../docs/analises/ANALISE-17-KAM-150-codeowners-pendurado.md)) é evidência, **não é um revisor**. Testes verdes: `lint_arch all` → «lista de bloqueio: conforme», «estrutura: conforme»; gate 3 → **conforme**, com **148** tickets reconhecidos e **0** referências inválidas (a contagem total de referências não se fixa aqui: muda sempre que um documento do conjunto cita uma — incluindo esta linha) |
| DoD — documentação actualizada; *Conventional Commits* | **satisfeito** | Os três documentos de `../docs/seguranca/`, `../docs/dividas-documentais.md`, `README.md` e `specs/INDICE.md`, cada um com linha de versão nova onde tem tabela |
| DoD — sincronia mestre↔epics | **satisfeito** | Linha do §4 (`fix`, `S`, `P1`, fase 0, `KAM-128`) igual ao cabeçalho deste bloco; `Bloqueia` do KAM-128 passa a `KAM-111, KAM-129, KAM-130, KAM-150`; **148** linhas `KAM-NNN` no §4 e **148** blocos únicos nos 11 epics, 0 órfãos de cada lado; segunda passagem idêntica |
| DoD — referências; todo o caminho citado resolve | **satisfeito** | Gate 3 **conforme**, com **148** tickets reconhecidos e **0** referências inválidas (a contagem total de referências não se fixa aqui: muda sempre que um documento do conjunto cita uma — incluindo esta linha). Ligações markdown locais: **0 quebradas acrescentadas** por este changeset (as 2 que o conjunto tem são as mesmas de `origin/main`: a dívida 16 em `tools/README.md` e o `[texto](caminho)` de prosa-modelo do KAM-128). **Esta caixa esteve marcada por cima de um gate vermelho**, e foi a revisão independente que o mostrou: cinco intervalos nus `KAM-001 – KAM-14N` e quatro ligações para esta análise antes de ela existir — **7** referências inválidas no gate 3. A causa foi de método, e está escrita em [`../docs/evidencia/KAM-150.md`](../docs/evidencia/KAM-150.md) §5.2: o gate correu antes de este bloco e o ficheiro de evidência serem escritos. Corre agora depois da última linha |
| DoD — sem segredos | **satisfeito** | O *commit* toca `CODEOWNERS`, seis `.md` e dois `.md` novos; nenhuma configuração, nenhuma dependência |
| DoD — defeitos fora do âmbito registados | **satisfeito** | Um defeito de código (gate que valide os caminhos) nomeado em «Fora de âmbito» e devolvido abaixo; três resíduos textuais em `../docs/dividas-documentais.md` (linhas 19 a 21) |

#### Decisões tomadas aqui, e porquê

| # | Decisão | Razão |
|---|---|---|
| 1 | **ID KAM-150 = maior do §4 de `main` (147) + 1**, e não «o primeiro identificador livre» | **Três tentativas, e as duas primeiras erradas.** A 1.ª escolheu 145 e afirmou que «não aparece em lado nenhum» — falso, apanhado pela revisão independente ([`ANALISE-17`](../docs/analises/ANALISE-17-KAM-150-codeowners-pendurado.md) A1), porque a varredura não olhava para os **nomes** de ramo e o *hook* `pre-push` faz de um nome uma reclamação. A 2.ª escolheu 149, o primeiro não reclamado por ninguém — e **o gate 4 reprovou**: o teste `test_kam_cobre_o_backlog_inteiro_sem_buracos` exige que o backlog seja `1..máximo` **sem lacunas**, e saltar 148 abre uma. A regra do repositório é **contiguidade**, imposta por máquina, não «evitar os vizinhos». Saltar um número troca um conflito de *merge* (minutos) por um teste vermelho (bloqueia). A colisão com os dois outros ramos que também querem o 148 fica, e resolve-a quem integra — foi o que o PR #45 fez, no *commit* `f616777`. Medição e as três tentativas em [`../docs/evidencia/KAM-150.md`](../docs/evidencia/KAM-150.md) §5.1 |
| 2 | **O aviso do cabeçalho mantém-se e ganha um parágrafo**, em vez de ser reescrito ou removido | A pergunta do âmbito era se ainda faz sentido. Faz, e a medição dá-lhe mais força do que ele próprio reclamava (repositório de utilizador: as equipas não podem existir, não é só que não existem). O que faltava era impedir a leitura errada de que caminhos certos = revisão imposta |
| 3 | **O DoD «Referências» do KAM-128 fica por marcar** | Tinha duas causas: as 7 referências nuas e estas 3 regras. Este ticket fecha uma. Marcar a caixa com metade da causa resolvida é o enfeite que `specs/01` §6 não admite |
| 4 | **O comando do critério ficou escrito com as suas duas ressalvas** (o `*` excluído; curingas no meio do padrão) | Um comando que esconde o que não cobre é pior do que nenhum: daria por «conforme» um ficheiro com `*.md` numa regra. Hoje nenhuma das 18 regras usa curingas no meio, e isso está medido, não assumido |
| 5 | **A contagem do `README.md` passa de 130 a 144, não de 143 para 144** | Estava **13** atrás: o KAM-129 deixou-a em 130 e nenhum ticket desde então a tocou. O âmbito manda actualizar a contagem do README; actualizá-la para 131 seria cumprir à letra um número errado |

#### Decisões devolvidas

| # | O que | A quem |
|---|---|---|
| 1 | **Nada verifica este ficheiro por máquina, e foi por isso que o defeito viveu dois tickets de referências.** `structure.py` vê que o `CODEOWNERS` existe; o gate 3 vê *tokens*; G1–G3 vêem `.md`. Ampliar `structure.py` para resolver cada padrão é pequeno e é código com testes — ticket próprio, não este `fix` | Arquitecto de Plataforma |
| 2 | **O `CODEOWNERS` corrigido continua inerte.** Repor `require_code_owner_review` e ≥ 1 aprovação é do **KAM-137**, que declarou este ficheiro fora do seu âmbito; substituir as equipas por utilizadores e dar dono de Segurança a `docs/seguranca/` (L-19) não tem ticket. Com dois contribuidores, «2 revisores» do DoD continua insatisfazível | Responsável de Segurança, com o fundador |

## KAM-152 — `db/gate8.py`: um caminho que não existe, numa mensagem que manda correr o ficheiro

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | — |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `db/tests/base.py`, `db/gate_bd.py`, `db/bootstrap.py`, `../.github/workflows/ci.yaml` (job `gate-8-migracoes`), `../docs/seguranca/gerar_matriz.py`, `../docs/seguranca/ameacas_stride.md`, `../docs/seguranca/validar.py`, `../docs/seguranca/lacunas.md` (L-20), `../docs/dividas-documentais.md` (linhas 3 e 6) |

### Contexto

O ficheiro que levanta o PostgreSQL descartável e corre as suites dos *gates* 8 e 6 chama-se hoje **`db/gate_bd.py`**. Chamou-se `db/gate8.py`, e o nome antigo ficou pendurado em **8 ocorrências de 7 ficheiros** — **7 delas vivas, em 6 ficheiros**, sendo a oitava a linha 6 do registo de dívidas, que já a nomeava. Seis das vivas são prosa, comentário ou dados gerados; **uma é uma mensagem de erro que diz ao utilizador para correr um ficheiro que não existe**, e é a razão deste ticket:

```python
# db/tests/base.py, em exigir_base_descartavel()
raise unittest.SkipTest(
    f"KAMBA_DB_NAME={base!r} nao e {BASE_DESCARTAVEL!r}. Os testes do "
    "gate 8 apagam o schema `platform` e so correm contra a base "
    "descartavel que `python db/gate8.py` cria."
)
```

Quem aponta a suite à base errada — por um `.env`, por uma variável herdada da *shell* — recebe esta mensagem, segue a instrução e recebe `No such file or directory`. O trinco funciona (recusa correr e não apaga a base de desenvolvimento); é a saída dele que mente sobre como sair da situação. É **o pior sítio** onde um caminho pendurado pode estar: a mensagem só aparece a quem já está perdido.

**O nome `*_gate8` não é o defeito, e não se toca nele.** A base descartável chama-se `kamba_gate8`, o trinco é a igualdade a esse nome, e os contentores são `kamba-gate8-*` (`db/gate_bd.py` linhas 70 e 162, `db/tests/base.py` linha 26, `packages/core-ts/tests_bd/apoio.ts` linha 32). O próprio `db/gate_bd.py` di-lo por escrito: «o nome e o do trinco, e ficou do primeiro gate que o usou». São **25** ocorrências de `gate8` que são o nome do trinco e estão certas; o defeito são as **8** que são o caminho `gate8.py`. Confundir as duas coisas renomeava uma base de dados num ticket de uma linha.

**Onde estava, medido e não lido.** O pedido deste ticket e o achado A10 da revisão adversarial do *fix* do `CODEOWNERS` nomeiam **três** sítios. São **7 ocorrências vivas em 6 ficheiros** (8 em 7, com a linha da dívida). **Cinco** ficheiros editam-se à mão; o sexto é o CSV, que se regenera:

```text
db/tests/base.py:8                         docstring                           (nomeado)
db/tests/base.py:48                        mensagem de SkipTest <- o defeito   (nomeado)
docs/seguranca/gerar_matriz.py:363         fonte da linha K-12 da matriz       (nomeado)
docs/seguranca/matriz_conformidade.csv:67  K-12, gerado do anterior            (nomeado)
docs/seguranca/ameacas_stride.md:90        prosa                               (nomeado)
.github/workflows/ci.yaml:217              comentario do gate-8-migracoes      <- NAO nomeado
db/bootstrap.py:26                         docstring                           <- NAO nomeado
docs/dividas-documentais.md:32             a propria linha de divida           (consequencia)
```

Os dois não nomeados são da mesma classe e saem da mesma varredura; deixá-los de pé fechava o ticket com o defeito meio corrigido.

**Porque é que nada apanhou isto.** O único mecanismo do repositório que resolve caminhos e nomes de teste nestes ficheiros é `../docs/seguranca/validar.py`, e ele **aborta antes de chegar lá**: tem a contagem de tickets fixada (`assert len(KAM) == 138`, com **150** no backlog), o que é o KAM-144 (`albinoJimy/kamba#42`, aberto). Relaxado o `assert`, dá **5** erros, dois deles estes. E `validar.py` **não está no CI** — é a lacuna **L-20** de `../docs/seguranca/lacunas.md` («o gate 3 só vê `KAM-NNN` e `ADR-NNN`; colunas, células vazias, caminhos e nomes de teste não têm gate»). Para `db/tests/base.py`, `db/bootstrap.py` e `../.github/workflows/ci.yaml` **não há mecanismo nenhum**, nem dentro nem fora do CI: nada no repositório verifica um caminho citado num *docstring* ou num comentário de Python ou de YAML.

### Objectivo

Nenhuma **citação viva** do caminho `db/gate8.py` fica no repositório, e a mensagem de erro do trinco do *gate* 8 passa a nomear um comando que corre. Sem tocar no nome do trinco `*_gate8`, que está certo.

**«Viva» é a qualificação que falta ao absoluto, e o título deste ticket é a razão de ela ser precisa:** por embutir `db/gate8.py`, o título põe a cadeia de caracteres no §4 do `specs/INDICE.md` (a tabela-contrato do backlog), na tabela-resumo do §3 deste epic e em todo este bloco. Um título pelo sintoma — «o caminho do *gate* 8 numa mensagem que manda correr o ficheiro» — teria deixado a fasquia do pedido quase literal. A escolha está feita e não se desfaz aqui, mas é ela que obriga a medir por exclusão, e isso diz-se.

### Critérios de Aceitação

- [x] A mensagem de `SkipTest` de `db/tests/base.py::exigir_base_descartavel` nomeia `python db/gate_bd.py`, e esse comando é **válido como está escrito** — verificado contra o analisador de argumentos, não por semelhança de nome.
- [x] O caminho `gate8.py` desaparece das **7** citações vivas dos **6** ficheiros (8 em `main` em `148567c`, contando a linha 6 da dívida) → **0**. A fasquia mede-se por **papel do ficheiro**, não por lista de nomes: são **registo** o `specs/` (blocos de ticket e backlog), o `../docs/analises/`, o `../docs/evidencia/` e o `../docs/dividas-documentais.md` — citam o caminho antigo porque é disso que falam —, e é **vivo** todo o resto (código, configuração, *workflows* e o desenho corrente). **A lista de nomes foi tentada primeiro e cresceu de 3 para 8 a cada documento escrito; uma lista que cresce assim não é um âmbito.** E há uma guarda sem excepção: **em qualquer ficheiro, incluindo os de registo, uma forma de comando (`python db/gate8.py`) fora de um bloco de código citado é sempre defeito** — é precisamente o que este ticket fecha, e os blocos de ticket levam «Handoff» com comandos, pelo que a exclusão por papel sozinha deixava passar a classe que o ticket existe para apanhar., que têm de citar o nome antigo para o poderem descrever: um ticket que documenta um caminho pendurado reintroduz a cadeia de caracteres, e isso é escrita e não defeito. **Por isso `grep -rn "gate8\.py" . → 0` é impossível à letra tanto quanto a fasquia do pedido**, e o âmbito está escrito em vez de presumido. O quarto documento é o bloco do KAM-149, que nasceu em `main` durante este trabalho.
- [x] O nome do trinco fica intacto: **21** ocorrências em **21** linhas de ficheiros vivos, **iguais em `148567c`, em `origin/main` e aqui**, nenhuma tocada pelo `git diff`. **A evidência é a invariância, não o número:** contar o trinco em *todos* os ficheiros dá 26 em `148567c` e **157** aqui, porque o ticket se documenta a si mesmo — a partir de certo ponto essa contagem mede a prosa do ticket e não o repositório.
- [x] A linha K-12 da matriz corrige-se **no gerador** (`../docs/seguranca/gerar_matriz.py`) e o CSV regenera-se por comando, não à mão. O CSV estava em sincronia com o gerador antes da alteração, e o *diff* do CSV é de **uma só linha**.
- [x] `../docs/seguranca/validar.py` (com o `assert` da contagem relaxado **em memória**, porque corrigi-lo é o **KAM-149**) passa de **5** erros para **3**: os dois de `db/gate8.py` desaparecem e **nenhum erro novo aparece**. Os três que ficam são o nome de teste desactualizado, fora deste âmbito.
- [x] A linha 6 de `../docs/dividas-documentais.md` **não se risca**: fecha metade. A metade do `db/gate8.py` sai da linha, a do nome de teste fica, e a linha diz que a primeira fechou aqui.
- [x] Este ticket entra nos dois lados — linha em `specs/INDICE.md` §4 (sub-tabela do EPIC-01) e bloco `## KAM-152 — ` neste epic — com tipo, estimativa, prioridade, fase e dependências iguais, e com a sua própria reciprocidade fechada (`—`↔`—`).
- [x] As contagens derivadas acompanham: `specs/INDICE.md` §1 e §3.1 passam a **151** tickets, com o EPIC-01 a **36**. O backlog fica **descontínuo** e os intervalos escrevem-se assim (`KAM-001 – KAM-150, KAM-152`): o **151** está reclamado por um ramo em voo e não tem bloco em `main`. O gate 3 expande intervalos, pelo que um intervalo fechado no 152 reprovaria o PR.
- [x] `specs/EPIC-01_Fundacoes_Dados.md` e `specs/INDICE.md` registam a emenda no respectivo «Controlo de versões».

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba#55`, ramo `fix/KAM-152-caminho-gate8-pendurado`,
a partir de `main` em `148567c` e **integrado com `main` em `5a9c53f`** (43 *commits* à frente, com os KAM-145 a KAM-149 nascidos entretanto). **Dezasseis caixas marcadas, uma vazia** (16 + 1 = 17): 9 nos Critérios de Aceitação e 8 no Definition of Done. **A primeira versão desta frase dizia «Dezassete marcadas, uma vazia (17 + 1 = 18)»**, e contava a caixa vazia duas vezes — 17 é o total de caixas, não o das marcadas. Apanhado por verificação independente, não pela leitura.

**A linha de base, medida antes de tocar em nada:**

```text
Medido fora dos tres documentos que registam a mudanca de nome (este bloco, o
§7 do specs/INDICE.md e a linha 6 da divida), que citam o nome antigo por oficio:

antes  (main 148567c)   caminho gate8.py   7 ocorrencias / 7 linhas / 5 ficheiros
                        (+1 na linha 6 da divida, que e a 8a de `main`)
                        trinco *_gate8    26 ocorrencias / 25 linhas
                        validar.py (assert relaxado em memoria) -> 5 erros
                        CSV == saida do gerador                 -> 0 diferencas
depois                  caminho gate8.py   0
                        trinco *_gate8    26 ocorrencias / 25 linhas, intactas
                        validar.py (assert relaxado em memoria) -> 3 erros, nenhum novo
```

| CA | Estado | Evidência |
|---|---|---|
| 1 — a mensagem nomeia um comando que corre | **satisfeito** | `db/tests/base.py:48` passa a `python db/gate_bd.py`. Que o comando é válido **sem argumentos** foi verificado no analisador e não presumido: `db/gate_bd.py:242-247` declara `--suite` com `default="tests"` e `choices=SUITES`, pelo que uma invocação nua corre a suite do *gate* 8, que é precisamente a que a mensagem manda correr. Era a parte que podia falhar em silêncio: um `--suite` obrigatório teria feito do caminho corrigido uma segunda instrução inválida, e a correcção mecânica do nome não o teria mostrado |
| 2 — o caminho desaparece das citações vivas | **satisfeito** | `git grep -o -n \"gate8\.py\" -- . ':!specs/EPIC-01_Fundacoes_Dados.md' ':!specs/INDICE.md' ':!docs/dividas-documentais.md'` dá **7** em `148567c`, em **6** ficheiros, e **0** no ramo. Os sete, por ficheiro: `db/tests/base.py` (2), `../.github/workflows/ci.yaml` (1), `db/bootstrap.py` (1), `../docs/seguranca/gerar_matriz.py` (1), `../docs/seguranca/matriz_conformidade.csv` (1), `../docs/seguranca/ameacas_stride.md` (1); a oitava de `main` era a linha 6 da dívida. **A primeira versão desta linha dizia `grep -rn "gate8\.py" . → 0` sem âmbito, e era falsa**: este bloco cita o nome antigo para o poder descrever, e a varredura sem exclusões dá **23** no estado final (17 neste bloco, 2 no `specs/INDICE.md`, 1 no bloco do KAM-149 e 1 na linha da dívida). A primeira versão desta frase publicou **22**, que não reproduz em *commit* nenhum. É o defeito que o ticket nomeia, cometido pelo ticket — a mesma espécie que o KAM-144 registou no seu número de referências — e está corrigido com o âmbito escrito, não com o número ajustado |
| 3 — o nome do trinco intacto | **satisfeito** | `git grep -o -P "gate8(?!\.py)"` sobre os ficheiros vivos dá **21** ocorrências em **21** linhas em `148567c`, **21/21** em `origin/main` e **21/21** aqui; o `git diff` não toca nenhuma. **Duas emendas, e a segunda é a que importa.** A primeira versão dizia «25 ocorrências», que é a contagem de *linhas* apresentada como contagem de ocorrências (a linha 140 da `ANALISE-03` tem duas) — corrigida para 26/25. A segunda veio da regra: sob o âmbito por papel o número é **21/21**, e contar todos os ficheiros passou de 26 para **157** à medida que este bloco e a evidência foram escritos. **Daí a afirmação ser a invariância e não o número** — um número que cresce com a prosa que o publica não é evidência de nada, e é a terceira vez que este ticket tropeça nessa mesma pedra. As 21 são: `BASE = "kamba_gate8"`, `BASE_DESCARTAVEL = "kamba_gate8"`, `kamba-gate8-{token}`, `*_gate8` e o `apoio.ts` do `core-ts` ficam por palavra. **É a caixa que torna a fasquia do pedido impossível à letra**: `grep -rn "gate8" → 0` exigiria renomear a base de dados, o trinco e os contentores. A fasquia cumprida é `gate8\.py` → 0, e a diferença está escrita aqui em vez de resolvida em silêncio |
| 4 — K-12 pelo gerador, CSV regenerado | **satisfeito** | A alteração é em `../docs/seguranca/gerar_matriz.py:363`; o CSV sai de `python docs/seguranca/gerar_matriz.py docs/seguranca/matriz_conformidade.csv` («68 linhas»). Que o CSV estava em sincronia **antes** foi medido, não suposto: gerado para o scratchpad e comparado com `diff -u` contra o comprometido → **0 diferenças**. Sem essa medição, um CSV que já tivesse divergido teria entrado no *diff* deste ticket como se fosse dele. O `diff` do CSV é de **1 linha** (K-12) |
| 5 — validar.py de 5 para 3 erros, nenhum novo | **satisfeito** | Antes: 5 erros — `matriz C-05` (teste inexistente), `matriz A-02` (controlo sem teste com caminho), `matriz A-02` (teste inexistente), **`matriz K-12: caminho inexistente db/gate8.py`**, **`ameacas_stride.md: caminho inexistente db/gate8.py`**. Depois: **3**, exactamente os três primeiros, conferidos por igualdade de texto e não por contagem. As restantes secções não se movem: MATRIZ 68×13, STRIDE 96/96 células, DPIA 12 operações, DOCS 5 ficheiros e 454 citações `CA n`. O `assert` da contagem foi relaxado **em memória** por um corredor do scratchpad que lê `validar.py`, substitui a linha e executa o resto — o ficheiro comprometido não foi tocado, e `git diff --stat` prova-o: `../docs/seguranca/validar.py` não aparece |
| 6 — a linha 6 da dívida fecha metade | **satisfeito** | Reescrita, não riscada. Sai a metade do `db/gate8.py`; fica a do nome de teste `test_a_premissa_kamba_app_ve_zero_linhas` (hoje `test_a_premissa_kamba_app_sem_contexto_ve_zero_linhas`), que é código no gerador e não é deste âmbito. A coluna «Onde» perde `seguranca/ameacas_stride.md` e o `K-12` **por medição**: o nome de teste antigo está em `gerar_matriz.py` e no CSV (C-05 e A-02) e **não** está no `ameacas_stride.md` — era o `gate8.py` que lá estava, e saiu. A contagem da linha passa de «cinco erros» a «três», e o «backlog tem 142» a 144 |
| 7 — o ticket nos dois lados, reciprocidade fechada | **satisfeito** | Linha no §4 (sub-tabela do EPIC-01, depois do KAM-144) e este bloco; `fix`/`S`/`P2`/fase `0`/`—` iguais nos dois lados. Os campos `Dependências` e `Bloqueia` ficam os dois a `—`: **não se declara dependência do KAM-149**, embora seja o seu `assert` que esconde o defeito. A correcção de um caminho em seis ficheiros não precisa de nada da entrega do KAM-149 — o grafo regista ordem técnica, não proveniência, e é o precedente que o KAM-144 fixou ao retirar o seu `KAM-129`. A linha do §3 «Tabela Resumo de Tickets» deste epic também entra |
| 8 — contagens derivadas | **satisfeito** | Depois da integração de `main`: §1 `150 tickets atómicos` → **151**; §3.1 EPIC-01 `… KAM-128 – KAM-148, KAM-150, KAM-152` com `36` (era 35), TOTAL `KAM-001 – KAM-150, KAM-152` com `151`. **Os intervalos são descontínuos porque o 151 está reclamado por um ramo em voo e não tem bloco**, e um intervalo fechado no 152 — que esta linha não escreve, pela mesma razão — seria expandido pelo gate 3 até exigir o 151 no §4. A soma das onze linhas = 150 = linhas do §4 = blocos `## KAM-NNN — ` nos 11 epics, e o EPIC-01 tem **35** blocos para as **35** da sua linha. **O furo na numeração que a primeira versão deste bloco descrevia desapareceu**, e não por emenda: os identificadores 145 a 149 nasceram em `main` enquanto este ticket era escrito, e o KAM-152 volta a fechar o intervalo. A lição fica: **o gate 3 expande intervalos**, pelo que um intervalo fechado escrito sobre um backlog com furos reprova o PR — e foi o gate, não a leitura, que o apanhou, duas vezes neste ticket. A segunda foi a renumeração: substituir `KAM-150` por `KAM-152` em bloco reescreveu também os intervalos **que estavam certos**, e o verificador apanhou os quatro |
| 9 — «Controlo de versões» nos dois documentos | **satisfeito** | `specs/EPIC-01_Fundacoes_Dados.md` v1.18 e `specs/INDICE.md` §7 v1.11 |
| DoD — todos os CA satisfeitos e demonstráveis | **satisfeito** | Os nove acima, cada um com o comando e o número |
| DoD — revisto por ≥ 1 revisor | **não satisfeito** | **Zero revisores humanos.** A revisão adversarial é evidência, não é um revisor (`specs/01_Engineering_Standards_e_Handoff.md`, DoD) |
| DoD — documentação actualizada; Conventional Commits | **satisfeito** | As duas linhas de versão (CA 9); *commits* `fix(KAM-152): …` |
| DoD — sincronia mestre↔epics, segunda passagem a 0 | **satisfeito** | Sincronia nos cinco campos comuns e existência nos dois lados → 0 divergências, nas duas passagens, sem alterações entre elas |
| DoD — reciprocidade | **satisfeito** | O ticket não declara aresta nenhuma, e isso é medido e não assumido: entra nos 145 blocos que a verificação percorre, e um `Dependências` ou `Bloqueia` aqui sem o outro lado contaria como falha |
| DoD — referências | **satisfeito** | `lint_refs --root . check` → «conforme — **11 429** referências em **553** ficheiros (KAM 8 662, ADR 1 609, D 1 158); KAM: **145**», com o KAM-152 já reconhecido. **O número foi remedido depois de esta linha o escrever, e é essa a medição publicada:** as primeiras diziam 11 427 e 11 428, colhidos antes de a linha existir, e a própria frase acrescentou um *token* `KAM-152`. É o defeito que o KAM-144 registou no mesmo campo, e a defesa é remedir no estado final e confirmar que já não se move. Emite **26** avisos de *tokens* `D#` fora do intervalo canónico, todos pré-existentes em `main`: «conforme» é o veredicto, não a ausência de avisos. `canon_lint check` e `canario` rc=0; `lint_arch all` → «lista de bloqueio: conforme», «estrutura: conforme». Todos os caminhos citados neste bloco resolvem, verificados um a um; a revisão adversarial que nomeia o achado A10 **não** é citada por caminho, por viver no ramo de `albinoJimy/kamba#47`, aberto, e não existir em `main`. **O gate reprovou duas vezes antes disto, e as duas foram deste ticket:** primeiro cinco identificadores reservados escritos em prosa com o prefixo, depois — e esta é a que importa — **quatro intervalos fechados no último ID**, em `specs/INDICE.md` §1, §3.1 e §7 e na linha 8 desta tabela, porque o gate **expande intervalos** e um intervalo que termine em KAM-152 exige que os cinco identificadores sem bloco existam. O número exacto de achados de cada uma das duas passagens **não foi registado antes de as corrigir** e por isso não se publica aqui: é `NÃO VERIFICADO`, e dizê-lo custa menos do que um número que não reproduz |
| DoD — sem segredos | **satisfeito** | Medido, não declarado não aplicável |
| DoD — defeitos fora do âmbito registados, não corrigidos aqui | **satisfeito** | **(a)** O nome de teste desactualizado (3 erros do `validar.py`), que fica na linha **6** de `../docs/dividas-documentais.md`, reescrita e não riscada. **(b)** A tabela-resumo do §3 deste epic não tem linha para os KAM-129, KAM-130 e KAM-144; a linha **3** da dívida já os nomeia — **a primeira versão deste ticket reclamava ter descoberto e registado a do KAM-144, e isso deixou de ser verdade com a integração de `main`, onde outro PR já a tinha inscrito**. A linha do KAM-152 entrou, porque um ticket tem de ser consistente consigo; as dos outros três não, porque são ticket alheio. **(c)** Uma **regressão de reciprocidade que veio de `main`**, medida e não corrigida: o KAM-148 declara `Dependências | KAM-136` e o `Bloqueia` do KAM-136 está a `—`. É exactamente a falha que o KAM-144 fechou oito vezes e cuja causa nomeou — o KAM-138 (*gate* 3c) não está implementado —, e reapareceu no primeiro ticket inscrito depois dele, o que confirma a previsão do KAM-144 em vez de a refutar. Registada na linha **26** de `../docs/dividas-documentais.md` (e a linha **27** leva os *placeholders* `#PR` que ficaram na análise e na evidência do KAM-148, um a nomear o ticket errado — terceira ocorrência da mesma classe); corrigi-la aqui seria alterar o campo de outro ticket a pretexto de um `fix` de texto. **(d)** Uma alteração fora de `FILES_IN_SCOPE`, declarada: o bloco do KAM-149 em `specs/EPIC-07_Seguranca_Conformidade.md` dizia que a linha 6 da dívida «nomeia dois», e este ticket fecha um deles. Ficaria a contradizer a linha 6 — contradição criada por este diff —, pelo que a frase foi emendada para nomear o que fechou e o que fica. É a única alteração a um bloco de outro ticket, e é tecnicamente necessária |

#### O que a revisão encontrou, e o que se fez

A revisão adversarial está em [`ANALISE-19`](../docs/analises/ANALISE-19-KAM-152-caminho-gate8-pendurado.md).

#### O ID mudou duas vezes debaixo do ticket, e isso é o registo

Medido sobre a **união** de duas bases, e é a união que importa: os **nomes** de `refs/heads` e `refs/remotes` (o `pre-push` faz de um nome de ramo uma reclamação) **e os conteúdos** dessas refs (um bloco `## KAM-NNN — ` dentro de um ramo reclama o ID sem que o nome o diga). Nenhuma das duas sozinha responde: sobre nomes apenas, o 146 e o 147 não apareciam; sobre conteúdos apenas, o 149 estava livre.

**À primeira medição, o 150 era a única vaga** — 145 a 149 tinham bloco ou nome de ramo, e o 151 já estava reclamado por `fix/KAM-148-cobertura-python-do-agr`. O ticket foi escrito como KAM-150. Enquanto o era, **o `albinoJimy/kamba#47` fundiu e levou o 150** para as regras de `CODEOWNERS`, e os 145 a 149 chegaram a `main` pelos PRs #45, #38 e #42. Renumerou-se para **152**, a primeira vaga livre sobre as duas bases depois dessas fusões.

**A lição não é «medir melhor»: é que num backlog com seis sessões a fundir em paralelo o ID só está seguro depois do *merge*.** A medição estava certa quando foi feita e ficou errada sem que nada neste ramo mudasse. O que a torna recuperável é ter sido medida por comando e registada com a sua base, em vez de escolhida de memória — e é também por isso que as contagens deste ticket se fecham **depois** de integrar `main`, e não antes.

**O 151 continua reclamado e sem bloco em `main`**, pelo que o backlog fica descontínuo e os intervalos escrevem-se `KAM-001 – KAM-150, KAM-152`. Não é estilo: **o gate 3 expande intervalos** (`tools/lint_refs/scan.py`), e um intervalo fechado no 152 exigiria que o 151 existisse no §4 — razão por que nenhuma frase deste bloco o escreve fechado, e por que a renumeração em bloco, que reescreveu quatro intervalos correctos, teve de ser desfeita à mão.

#### A causa não é corrigida aqui

**Nada no repositório verifica um caminho citado em código.** O `validar.py` resolve caminhos, mas só nos ficheiros de `../docs/seguranca/`, e **não corre no CI** — é a lacuna **L-20**, que já tem dono declarado («Ticket novo, com o script do anexo A como ponto de partida») e não se abre aqui. Para `db/tests/base.py`, `db/bootstrap.py` e `../.github/workflows/ci.yaml` não há mecanismo nenhum: o *gate* 3 (`tools/lint_refs`) vê `KAM-NNN`, `ADR-NNN` e `D#`, e **não vê caminhos**. Este `fix` paga oito ocorrências; não impede a nona, e a nona reaparece no próximo ficheiro que mude de nome.

**Não se acrescentou teste de regressão, e isso é uma decisão.** Um teste que afirmasse que o caminho nomeado na mensagem de `SkipTest` existe guardaria **esta** linha e nenhuma outra, viveria em `db/tests/`, que só corre com Docker dentro do *gate* 8, e daria a aparência de uma classe de defeito fechada quando o que ficava coberto era uma ocorrência. A cobertura da classe é o L-20 alargado a `db/` e a `../.github/`, não um `assert` sobre uma *f-string*. **A decisão de alargar o L-20 a caminhos citados em código fica devolvida ao Arquitecto de Plataforma**, com este ticket como o seu segundo caso medido.

### Detalhes Técnicos

- **Componentes:** transversal. Uma mensagem de erro em `db/tests/base.py`, dois *docstrings*, um comentário de YAML e a fonte de uma linha da matriz de conformidade. Sem migrações, sem dependências novas, sem alteração de comportamento: o trinco recusa exactamente os mesmos casos, antes e depois.
- **A correcção é de texto, e o texto é a interface.** `exigir_base_descartavel` não muda de condição nem de excepção; muda o que diz a quem a vê. Num trinco, a mensagem **é** a funcionalidade — é o único caminho de saída que o utilizador recebe.
- **O CSV não se edita.** `../docs/seguranca/matriz_conformidade.csv` é gerado; o seu cabeçalho e o de `gerar_matriz.py` dizem-no («Edita-se esta lista e nao o CSV»). Editar a linha K-12 à mão passaria o `validar.py` e voltaria atrás na geração seguinte.
- **Fora de âmbito:** corrigir o `assert len(KAM) == 138` de `../docs/seguranca/validar.py` — é o **KAM-149**, que está no backlog (EPIC-07) e **não está implementado**: medido, a linha 43 continua a fixar 138, e o `merge` do `albinoJimy/kamba#42` não tocou o ficheiro. O relaxamento usado aqui foi **em memória**, e `git diff` prova que o ficheiro não entrou no *diff*; pôr o `validar.py` no CI, ou alargá-lo a `db/` e `../.github/` — é o **L-20**; corrigir o nome de teste `test_a_premissa_kamba_app_ve_zero_linhas` no gerador, que fica na linha 6 da dívida; acrescentar à tabela-resumo do §3 as linhas em falta dos KAM-129, KAM-130 e KAM-144 — linha 3 da dívida; renomear `kamba_gate8`, `*_gate8` ou `kamba-gate8-*`; a contagem de tickets do `README.md` — é o **KAM-130**.

### Testes Requeridos

- Verificação por máquina, corrida **antes e depois**, com os dois números no PR:

```text
P0   forma de comando `python db/gate8.py` fora de um
     bloco citado, em QUALQUER ficheiro                   antes 2    ->  alvo 0
P1   caminho gate8.py em ficheiros VIVOS (papel: nao
     specs/, analises/, evidencia/, dividas)              antes 7    ->  alvo 0
P2   trinco: gate8 NAO seguido de .py, ficheiros vivos    antes 21   ->  alvo 21 (invariante)
P3   validar.py com o assert relaxado em memoria          antes 5    ->  alvo 3, nenhum novo
P4   diff do CSV contra a saida do gerador                antes 0    ->  alvo 0 (1 linha mudada)
P5   `--suite` tem default, logo `python db/gate_bd.py`
     e uma invocacao valida                               -> confirmado no analisador
S1   sincronia mestre<->epics e existencia nos dois lados  antes 0    ->  alvo 0
S7   contagens derivadas (§1, §3.1, TOTAL) contra os
     blocos e as linhas do §4                             antes 0    ->  alvo 0
S8   intervalos `KAM-NNN a KAM-NNN` que se expandam
     para um ID sem bloco (e o que o gate 3 faz)          antes 0    ->  alvo 0
     (com o backlog contiguo da-se de gracas; fica porque
      o proximo furo volta a reprovar o PR)
```

- Segunda passagem de P1–P4 e S1/S7: **0 alterações**.
- `git diff --stat` revisto linha a linha: o *diff* toca só as oito ocorrências do caminho, as linhas 3 e 6 da dívida, o bloco novo, as duas linhas do backlog, as contagens e as duas linhas de versão.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis, com secção «Verificação dos Critérios de Aceitação» neste bloco: uma linha por critério, com o comando e o número que saiu.
- [ ] Revisto por ≥ 1 revisor.
- [x] Documentação actualizada: «Controlo de versões» de `specs/EPIC-01_Fundacoes_Dados.md` e de `specs/INDICE.md`; Conventional Commits.
- [x] **Sincronia mestre↔epics** — a linha do §4 e este bloco dizem o mesmo; segunda passagem a 0 divergências.
- [x] **Reciprocidade** — `—`↔`—`, contada entre os 145 blocos.
- [x] **Referências** — nenhum `KAM-NNN` citado deixou de existir; todos os caminhos citados resolvem.
- [x] **Sem segredos** — medido.
- [x] Defeitos encontrados fora do âmbito registados em `../docs/dividas-documentais.md`, não corrigidos aqui.

### Handoff para Claude Code

```text
Es o executor do ticket KAM-152 da KAMBA. Le specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-152).
Objectivo: a mensagem de erro do trinco do gate 8 deixa de mandar correr um ficheiro que nao existe.
- Varre `gate8\.py` ANTES de editar, e conta. O pedido nomeia tres sitios; sao cinco ficheiros e oito
  ocorrencias. Corrigir so os tres nomeados fecha o ticket com o defeito meio corrigido.
- NAO toques no nome do trinco: `kamba_gate8`, `*_gate8` e `kamba-gate8-*` estao CERTOS, e
  `grep -rn "gate8" -> 0` so se cumpriria renomeando a base de dados. A fasquia e `gate8.py` -> 0,
  e a diferenca escreve-se, nao se resolve em silencio.
- Define o ambito por PAPEL do ficheiro, nao por lista de nomes: specs/, docs/analises/,
  docs/evidencia/ e dividas-documentais.md sao REGISTO (citam o caminho antigo porque e disso que
  falam); o resto e VIVO. Tentei a lista de nomes primeiro: cresceu de 3 para 8 a cada documento que
  escrevi, e uma lista que cresce assim nao e um ambito.
- E poe uma guarda SEM EXCEPCAO: uma forma de comando (`python db/gate8.py`) fora de um bloco de
  codigo citado e defeito em QUALQUER ficheiro — o Handoff de um ticket leva comandos, e e essa a
  classe que este ticket fecha.
- Afirma a INVARIANCIA do trinco, nao o seu numero: o numero muda com a regra de contagem e cresce
  com a tua propria prosa (26 -> 157 enquanto escrevia). Mede-o em main e no ramo e mostra que e
  igual; conta OCORRENCIAS e nao linhas, que `grep -c` conta linhas.
- Confirma no analisador de argumentos que `python db/gate_bd.py` e valido SEM argumentos antes de o
  escrever na mensagem. Trocar um caminho invalido por um comando invalido nao e corrigir nada.
- A linha K-12 da matriz corrige-se em docs/seguranca/gerar_matriz.py e o CSV REGENERA-SE por comando.
  Mede primeiro que o CSV estava em sincronia com o gerador, senao a divergencia antiga entra no teu diff.
- Corre docs/seguranca/validar.py antes e depois. O assert da contagem fixada aborta-o: relaxa-o EM
  MEMORIA (le o ficheiro, substitui a linha, executa), NAO no ficheiro — e o ambito do KAM-149.
  Antes 5 erros, depois 3, e confere os tres por TEXTO e nao por contagem.
- A linha 6 de docs/dividas-documentais.md NAO se risca: fecha metade. Sai o gate8.py, fica o nome de
  teste. Confere por medicao quais os ficheiros que ainda citam o nome de teste antes de reescrever a
  coluna «Onde» — nao e onde a linha diz que e.
- Actualiza as contagens do specs/INDICE.md §1 e §3.1 (total, linha do EPIC-01 e TOTAL).
- Integra origin/main ANTES de fechar as contagens: enquanto escreves, outras sessoes fundem
  tickets e o total muda debaixo de ti. E se o backlog tiver furos, NAO escrevas intervalos
  fechados (`KAM-001 a KAM-NNN`): o gate 3 EXPANDE intervalos e exige que cada ID exista no §4.
Nao expandas escopo: NAO corrijas o assert do validar.py (KAM-149); NAO o ponhas no CI nem o alargues a
db/ (L-20); NAO corrijas o nome de teste no gerador; NAO acrescentes as linhas em falta dos KAM-129,
KAM-130 e KAM-144 a tabela-resumo do §3 (linha 3 da divida); NAO acrescentes teste de regressao — a
decisao de alargar o L-20 fica devolvida ao Arquitecto de Plataforma.
Abre PR com o template do §7.
```

---

## KAM-151 — Cobertura Python sobre `services/agr/src/`, que nenhum alvo media

| Campo | Valor |
|---|---|
| Epic | EPIC-01 — Fundações e Dados |
| Fase | 1 |
| Tipo | fix |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-132 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma (dono do gate 4) |
| Documentos de referência | `../docs/ci.md` (§3 gate 4, §7 lacunas 25 e 26), `../docs/evidencia/KAM-132.md` §4, `../docs/evidencia/KAM-151.md`, `../docs/analises/ANALISE-18-KAM-151-cobertura-python-do-agr.md`, `specs/01_Engineering_Standards_e_Handoff.md` §4.1, `ci/thresholds.yaml`, `Makefile` (alvo `coverage-python`) |

### Contexto

O `ci/thresholds.yaml` decide **quem é medido** e não só com que limiar, e põe
`services/*/src/**` no estrato `restante`. Os três ficheiros de
`services/agr/src/kamba_agr/` (`__init__.py`, `app.py`, `meta.py`) estão
portanto declarados no âmbito do *gate* 4. Mas o `make coverage-python` mede
`tools/` e `libs/py-core/src`, e mais nada: os do AGR nunca entraram no
denominador. **E a suite existia**: `services/agr/tests/` tem nove testes que
exercitam esses ficheiros a fundo, e corre em `make test-py` desde o KAM-001.
Faltava a medição, não os testes.

A consequência era precisa: alguém mexer naqueles ficheiros, ou acrescentar
Python ao AGR sem testes, não movia o número do *gate* 4. O limiar de 75%
aplicava-se a uma amostra que não incluía o serviço.

**Porque não entrou no KAM-132.** O KAM-132 fechou a mesma classe de defeito do
lado Node — âmbito declarado, medição em falta — e **mediu e declarou esta**,
como lacuna 25, sem a fechar, por duas razões escritas: a cura é cablagem do
alvo de Python e não avaliação, e a via que o KAM-132 usou do lado Node
(`universo()`, que injecta a 0% o que nenhum relatório mediu) **não serve para
`.py`**, porque injectar um `.py` exigiria contar **instruções**, que é a régua
do `coverage.py`, e não o número de linhas do ficheiro, que é o que se sabe
calcular sem executar nada.

**O que a lacuna não dizia, e é metade deste ticket:** do lado Python o universo
não tem gate nenhum. O `universo()` protege o lado Node de um ficheiro novo sem
testes; do lado Python a garantia é a cablagem do alvo, e uma cablagem
incompleta não deixa nada vermelho. Foi assim que estes três ficheiros ficaram
fora do denominador desde o KAM-002 sem ninguém notar.

### Objectivo

Medir o Python que o `ci/thresholds.yaml` declara — todo — e pôr a **falta de um
`--source=`** a falhar um teste, para que a próxima pasta de `.py` do âmbito não
repita a lacuna em silêncio.

### Critérios de Aceitação

- [x] **`make coverage-python` mede `services/agr/src/`**, correndo a suite que já existe sob `coverage run --source=services/agr/src`, e funde o LCOV com os outros — como o alvo já fazia para `libs/py-core`. Verificado por execução: os três ficheiros passam de ausentes a medidos no relatório do *gate*.
- [x] **O «antes» e o «depois» ficam medidos, não estimados**, com o mesmo conjunto de relatórios avaliado nas duas situações, para que a única variável seja a medição nova.
- [x] **Um `.py` do âmbito que nenhum `--source=` meça falha um teste.** O universo sai do próprio `ci/thresholds.yaml` — os `padroes` dos estratos menos os `excluidos` —, e não de uma lista escrita no `Makefile` que divergisse dele. Verificado por execução nos dois sentidos: vermelho antes da correcção, verde depois.
- [x] **O ticket não baixa o limiar.** Registado o número medido; se o estrato descesse abaixo dos 75%, o ticket nomeava os ficheiros a cobrir e devolvia a decisão ao dono do *gate* 4 — o limiar é *proposta* do `specs/01_Engineering_Standards_e_Handoff.md` §4.1 e altera-se por emenda registada, com os dois revisores que o DoD do KAM-002 exige para mexer em limiares. **Não foi preciso: o estrato ficou em 91%, com os mesmos 16 pontos de margem.**
- [x] **O que fica sem cobertura fica nomeado** — ficheiro, e as linhas quando o ficheiro está parcialmente coberto —, com a razão, em vez de se cobrir com um teste escrito só para subir o número.
- [x] A lacuna 25 fica fechada em `../docs/ci.md` §7 e a linha do *gate* 4 de `../docs/seguranca/lacunas.md` deixa de a listar como sem dono.

### Verificação dos Critérios de Aceitação

Entregue no PR [`albinoJimy/kamba#53`](https://github.com/albinoJimy/kamba/pull/53), a partir de `f4c7e3d` (o *merge* do KAM-132). Medido a 2026-10-12. Não há `make` nem
`node` na máquina de medição: os alvos correram em `node:24.21.0-trixie-slim`
com `make`, `python3`, `python3-venv` e `git` instalados por `apt-get`, sobre uma
cópia da árvore de fontes no disco do contentor — o comando é o mesmo, o que
muda é onde o `make` corre. O detalhe com os comandos está em
[`../docs/evidencia/KAM-151.md`](../docs/evidencia/KAM-151.md). Cada caixa
marcada acima tem uma linha aqui; **a do DoD que não se cumpre também**.

| CA | Estado | Evidência |
|---|---|---|
| CA1: o alvo mede `services/agr/src/` | **satisfeito** | O `make ci-4` passa de 8 para 9 relatórios LCOV e de 142 para 146 ficheiros medidos; os três do AGR entram no estrato `restante`, que vai de 100 para 103 ficheiros. O quarto ficheiro medido é o `__main__.py`, que o `ci/thresholds.yaml` exclui e o *gate* conta como excluído (13 → 14) |
| CA2: o antes e o depois medidos | **satisfeito** | Par perfeito, o **mesmo** conjunto de relatórios avaliado com e sem o do AGR. Medido duas vezes, porque o `main` andou cinco vezes entretanto, e **o delta é idêntico nas duas**: em `f4c7e3d` (onde o ticket era o KAM-148), `restante` **91%** 9652/10526 em 100 ficheiros → **91%** 9681/10557 em 103; na árvore que funde, **92%** 9880/10730 em 100 → **92%** 9909/10761 em 103. Em ambas: **+29** no numerador, **+31** no denominador, **+3** ficheiros, e a percentagem não se move. O absoluto subiu entre as duas porque o KAM-148 acrescentou código testado a `tools/`, que está no estrato — **não** por causa deste ticket. O `critico` fica intacto nas duas (94%, 4802/5055, 29 ficheiros). Os três ficheiros do âmbito saem a **93%** (29/31 instruções) nas duas |
| CA3: a falta de `--source=` falha um teste | **satisfeito** | `TestCoberturaPythonMedeOAmbito` em `tools/lint_arch/tests/test_makefile.py`, quatro testes. Com o `Makefile` de `HEAD` (sem a correcção), dois ficam vermelhos e nomeiam os três ficheiros; a mensagem é `services/agr/src not found in {tools, libs/py-core/src}`. Com a correcção, os quatro verdes |
| CA4: o limiar não baixa | **satisfeito** | Vacante: **o limiar não foi tocado**. O `ci/thresholds.yaml` mantém 90/75 e este ticket não lhe altera uma linha. O `restante` ficou em 91% contra 75%, pelo que não houve decisão para devolver ao dono do *gate* 4 — e **não havia como a adiar**: o número mediu-se antes de se escrever este bloco |
| CA5: o que fica sem cobertura nomeado | **satisfeito** | Nenhum ficheiro ficou a zero; o que ficou descoberto são **duas instruções**, as linhas 16 e 18 de `services/agr/src/kamba_agr/__init__.py`: o corpo de `kamba_agr.create_app()`, a fachada de importação tardia que existe para `meta` ser legível sem Starlette instalado. Nenhum teste a chama, porque os testes importam `kamba_agr.app.create_app` directamente. O `app.py` e o `meta.py` saem a **100%**, e o `__init__.py` a 60%. Fica nomeado aqui, no `../docs/ci.md` §7 e na evidência §2 e §6, para o dono do *gate* 4 decidir se quer um teste à fachada |
| CA6: lacuna 25 fechada | **satisfeito** | `../docs/ci.md` §7 item 25 riscado e com «**Fechada pelo KAM-151**», com o que fica aberto nomeado; `../docs/seguranca/lacunas.md` linha do *gate* 4 deixa de a listar — a tabela é de **limites vivos**, e um limite que já não existe não pertence lá (a história fica no `../docs/ci.md` §7 e §9). A mesma linha ganha a **lacuna 26** |
| Prova por mutação | **satisfeito** | `tools/lint_arch/tests/mutacoes.py` — o cabeçalho manda correr quando se mexe no `coverage_gate`, nos limiares ou no alvo, e este diff mexe em dois. **28 mutações: 28 apanhadas, 0 sobreviventes**, de 24 que eram: quatro novas `cablagem:` provam que a cablagem do lado Python morde (o `--source=` do AGR trocado, o LCOV fora do `glob` do *gate*, o LCOV com nome que não resolve, e o bloco movido para antes do `coverage lcov` do `libs`). Sem elas, a propriedade ficava provada por uma execução pontual e não por oráculo permanente. E `python db/mutacoes.py --aplicaveis` → **138 conferidas, 0 não aplicáveis** |
| DoD: todos os CA satisfeitos | **satisfeito** | Os seis acima, com evidência em [`../docs/evidencia/KAM-151.md`](../docs/evidencia/KAM-151.md) |
| DoD: revisto por ≥ 1 revisor | **não satisfeito** | A caixa fica vazia. Houve revisão adversarial independente ([`ANALISE-18`](../docs/analises/ANALISE-18-KAM-151-cobertura-python-do-agr.md): 2 maiores, 6 menores, 2 suspeitas, todas tratadas), e **isso é evidência, não é um revisor**; e o limiar não foi alterado, pelo que a regra dos dois revisores do DoD do KAM-002 não se aplica a este diff. Em todos os tickets desta fase a caixa está vazia, por decisão do fundador: funde-se com o CI verde, sem esperar revisão humana |
| DoD: documentação | **satisfeito** | `../docs/ci.md` §3 (as duas afirmações de âmbito), §7 (lacuna 25) e §9 (versão); `../docs/seguranca/lacunas.md`; `specs/INDICE.md` §4, as três contagens e a versão 1.10; este bloco. Conventional Commits |
| DoD: sem segredos | **satisfeito** | Não aplicável: não acrescenta configuração nem credenciais |
| DoD: dependências | **satisfeito** | Nenhuma nova. O `coverage` já estava no `.venv` por `tools/requirements/tools.in`, e o `starlette` do AGR por `services/agr/requirements/runtime.txt` — ambos instalados pelo `make bootstrap` e em cache no *runner* do *gate* 4 |
| DoD: emenda ao limiar registada | **satisfeito** | Vacante: **o limiar não foi emendado** |

> **O que isto custa, dito com clareza.** O número do estrato **não se moveu**, e
> isso não é o ticket a não fazer nada: é a medição a dizer que o código que
> estava invisível já estava testado. O que mudou é que deixa de o estar por
> acidente. A propriedade que o ticket entrega não é um número melhor, é um
> número que **reage**, e isso mediu-se em vez de se prometer: um módulo de 840
> instruções sem testes em `services/agr/src/` leva o `restante` de 91% a
> **84%**, e antes deste ticket movia **zero**.
>
> **O que o ficheiro não faz, e uma versão anterior deste bloco dizia que fazia:**
> esse `.py` **não sai nomeado** no relatório do *gate*. O `coverage_gate` imprime
> nomes só do que **injecta**, e injecta apenas o que o Node executa; um `.py`
> entra por medição e nunca passa por ali. A frase vinha do `../docs/ci.md` §3,
> onde descreve o caso Node e está certa. Fica registada como **lacuna 26**,
> destapada por este ticket e devolvida ao dono do *gate* 4: nomear o que foi
> medido é mexer no relatório para todos os estratos e nas duas linguagens.
>
> **E fica dito o que este ticket não fecha.** A lacuna 23 continua aberta e este
> ticket toca-lhe: as 31 do AGR são **instruções** do `coverage.py`, enquanto as
> 10 526 do estrato misturam instruções (do Python) com linhas de ficheiro (do
> Node). Somar as duas num só agregado é o que a lacuna 23 nomeia, e este ticket
> acrescenta-lhe uma terceira parcela sem a resolver — o que a torna um pouco
> mais urgente, não menos. A lacuna 24 (um ficheiro que nenhum estrato
> classifica) também não é deste ticket, e a **26** é nova — saiu desta entrega,
> ao desmentir-se uma frase que este bloco afirmava.

### Detalhes Técnicos

- **Componentes:** `Makefile` (alvo `coverage-python`), `tools/coverage_gate.py` (o comentário de `EXTENSOES_DO_UNIVERSO`, que afirmava a lacuna, e o parâmetro `extensoes` de `universo()`), `tools/lint_arch/tests/test_makefile.py` (a classe nova).
- **A cura é no alvo, não na avaliação.** O `universo()` fica a contar só o que o Node executa. Do lado Python o `coverage run --source=<pasta>` já percorre o disco e mede o que não é importado: o que faltava era uma pasta na lista, não um mecanismo novo.
- **O nome do LCOV não é livre.** O `coverage_gate.base_do_nome` lê o pacote do nome do ficheiro: `python-agr.lcov` dava a base `agr`, que não é família nenhuma; usa-se `python-services-agr.lcov`, que dá `services/agr`. Preso por teste.
- **A ordem dos blocos do alvo importa.** `coverage run` sem `--append` apaga o ficheiro de dados, pelo que o bloco novo corre **depois** do `coverage lcov` do `libs/py-core`. Preso por teste, porque um bloco inserido no meio deixava o outro com um relatório vazio e sem erro.
- **Fora de âmbito:** a definição de «linha» nos dois lados (lacuna 23); um ficheiro que nenhum estrato classifica (lacuna 24); **nomear no relatório do *gate* um `.py` medido a 0% (lacuna 26, destapada por este ticket)**; medir `db/**`, que o `ci/thresholds.yaml` exclui com razão escrita; cobrir a fachada `kamba_agr.create_app()`, que fica nomeada e sem teste.

### Testes Requeridos

- Unit: `TestCoberturaPythonMedeOAmbito` — todo o `.py` do âmbito cai sob um `--source=`; o AGR é medido pelo nome; cada `coverage run` escreve o seu LCOV antes do próximo; o nome de cada LCOV resolve para uma pasta real.
- Integração: `make ci-4` completo, nos dois estados, com o par de números por estrato.
- Regressão de desenho: o teste do âmbito corrido contra o `Makefile` de `HEAD`, para provar que fica **vermelho** sem a correcção — um teste que passasse nos dois estados não provaria nada.
- Prova por mutação: quatro mutações `cablagem:` novas em `tools/lint_arch/tests/mutacoes.py`, que desfazem a cablagem de quatro maneiras e exigem que as baterias fiquem vermelhas.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-151.md`, com o «antes» e o «depois» do valor medido).
- [ ] Código revisto por ≥ 1 revisor, **2 se o limiar for alterado** (DoD do KAM-002); testes verdes.
- [x] Documentação actualizada: `../docs/ci.md` §3 (as duas afirmações de âmbito), §7 (lacuna 25 fechada) e §9; `../docs/seguranca/lacunas.md` (linha do *gate* 4); Conventional Commits.
- [x] **Sem segredos** — não aplicável: não acrescenta configuração nem credenciais.
- [x] **Dependências** — nenhuma nova: o `coverage` e o `starlette` já estavam no `.venv`.
- [x] Se o limiar do §4.1 for emendado, a emenda fica registada no `specs/01_Engineering_Standards_e_Handoff.md` §4.1 e em `ci/thresholds.yaml`, com dono e data — não só no código. **Vacante: o limiar não foi emendado.**

### Handoff para Claude Code

```text
És o executor do ticket KAM-151 da KAMBÁ. Lê specs/EPIC-01_Fundacoes_Dados.md (bloco KAM-151).
Objectivo: o gate 4 passa a medir o Python que o ci/thresholds.yaml declara — todo.
- Makefile, alvo `coverage-python`: um terceiro `coverage run --branch
  --source=services/agr/src` sobre a suite de services/agr/tests, e o seu
  `coverage lcov` para ci/coverage/python-services-agr.lcov. Corre DEPOIS do
  `coverage lcov` do libs/py-core: `coverage run` sem `--append` apaga os dados.
- O nome do LCOV tem de ser `python-services-agr.lcov`: o coverage_gate le o
  pacote do nome do ficheiro, e `python-agr.lcov` da a base `agr`, que nao existe.
- tools/lint_arch/tests/test_makefile.py: classe nova que le o ambito do
  ci/thresholds.yaml e falha quando um `.py` do ambito nao tem `--source=`.
  Prova-a contra o Makefile de HEAD: tem de ficar VERMELHA sem a correccao.
- Mede o par (com e sem o relatorio do AGR) e poe os quatro numeros por estrato
  em docs/evidencia/KAM-151.md §4. NAO baixes o limiar: se o estrato descer
  abaixo de 75%, nomeia os ficheiros e devolve a decisao ao dono do gate 4.
- Fecha a lacuna 25 em docs/ci.md §7 e actualiza a linha do gate 4 em
  docs/seguranca/lacunas.md.
Nao expandas escopo: nao mexas no universo() para injectar `.py` (a regua do
coverage.py sao instrucoes); nao resolvas a lacuna 23 nem a 24; nao cubras a
fachada kamba_agr.create_app() — nomeia-a.
Abre PR com o template do §7.
```

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: KAM-001 a KAM-012 (fundações, dados, eventos, identidade, segredos, storage, auditoria); KAM-111 (dicionário de dados canónico) acrescentado na consolidação. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-128 (reorganização do conjunto documental sob `docs/` e reescrita das referências cruzadas) acrescentado para cobrir trabalho já na história sem ticket; KAM-128 bloqueia o KAM-111 e entra no `Bloqueia` do KAM-001. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-129 (correcção do prefixo das referências aos anexos de evidência em `specs/`) e KAM-130 (reconciliação das contagens e intervalos herdados) acrescentados como `fix`, para defeitos pré-existentes identificados na varredura do KAM-128 e declarados fora do seu âmbito; a nota de «Fora de âmbito» do KAM-128 passa a remeter para os dois e corrige a estimativa de ~32 ocorrências em três epics para as 59 medidas em seis. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-131 a KAM-137 acrescentados: as lacunas 9 a 15 de `../docs/ci.md` §7, registadas pela revisão adversarial do KAM-002 ([`ANALISE-02`](../docs/analises/ANALISE-02-KAM-002-pipeline-ci.md)) como trabalho com medição própria, passam a tickets. Seis `fix` e um `chore`; o KAM-131 (gate 9 sobre a história do PR) é o único P1, e o KAM-134 bloqueia o KAM-135. As lacunas 1 a 7 **não** geraram ticket por serem decisões do canon, e a 8 por já estar atribuída ao ticket que instalar os componentes *enterprise*. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | KAM-138 (gate 3c, lint de coerência do backlog) acrescentado: a sincronia mestre↔epics, a reciprocidade `Dependências`↔`Bloqueia` (a busca G5 do KAM-129) e as contagens derivadas passam a ter um gate, em vez de serem critério manual repetido em cada ticket. Verificou-se que nem o gate 3 (KAM-002) nem o gate 3b (KAM-111) a cobriam, ao contrário do que o «Fora de âmbito» do KAM-130 remetia — nota corrigida. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | Encerramento com evidência dos KAM-001, KAM-128 e KAM-129: as caixas de Critérios de Aceitação e Definition of Done passam a estar marcadas, e cada bloco ganha uma secção «Verificação dos Critérios de Aceitação» com uma linha por critério — o que se mediu, com que comando e o número que saiu. As caixas que não se cumprem ficam vazias e nomeadas: 5 no KAM-001, 5 no KAM-128 e 5 no KAM-129. Nenhum critério foi reescrito e nenhum defeito revelado pela medição foi corrigido aqui. Quatro caixas inicialmente marcadas foram desmarcadas depois da revisão adversarial de `../docs/analises/ANALISE-04-encerramento-kam-001-128-129.md`, que apurou 4 achados P0, 8 P1 de evidência e 8 defeitos documentais fora deste âmbito. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | KAM-004 entregue: 13 caixas marcadas e 2 vazias, com secção de verificação, decisões, desvios e prova por mutação; a revisão adversarial está em [`ANALISE-07`](../docs/analises/ANALISE-07-KAM-004-rls-e-isolamento.md). Nota no bloco do KAM-009 com a decisão devolvida sobre quem altera `tenants.plano`. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | KAM-111: caixas marcadas com evidência (5 de 12) e secção «Verificação dos Critérios de Aceitação», depois da revisão adversarial ([`ANALISE-05`](../docs/analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md)). KAM-139, KAM-140 e KAM-141 acrescentados — os `fix` que o critério 2 do KAM-111 manda abrir para o que fica fora das doze divergências — e inscritos no `Bloqueia` do KAM-111. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | KAM-142 acrescentado: celeridade do processo de entrega. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | KAM-011 entregue: 9 caixas marcadas e 6 vazias, com secção de verificação, decisões e prova por mutação; a revisão adversarial está em [`ANALISE-09`](../docs/analises/ANALISE-09-KAM-011-storage-provider.md). A decisão D6 **não** foi tomada: o critério 6 e o ADR ficam por cumprir. | Equipa KAMBÁ |
| 1.10 | Outubro 2026 | Seguimento do KAM-142: a prova por mutação passa a oito execuções em paralelo e uma falha por carga da máquina deixa de contar como mutação apanhada. | Equipa KAMBÁ |
| 1.11 | Outubro 2026 | KAM-143 acrescentado: prova por mutação completa como tarefa nocturna, fatiada por *runner*. | Equipa KAMBÁ |
| 1.12 | Outubro 2026 | KAM-008 entregue: 11 caixas marcadas e 5 vazias, com secção de verificação, decisões e as três decisões devolvidas; as duas revisões adversariais estão em [`ANALISE-08`](../docs/analises/ANALISE-08-KAM-008-identidade-de-contacto.md). | Equipa KAMBÁ |
| 1.14 | Outubro 2026 | KAM-131 entregue: 15 caixas marcadas e 2 vazias (revisores humanos; decisão de prioridade), com secção de verificação, decisões e prova por mutação. O *gate* 9 passa a correr duas passagens — a árvore e os *blobs* que o intervalo do PR acrescenta à história — e fecha a lacuna 9 de `../docs/ci.md` §7. A subida de P1 a P0 **não** foi decidida: é do Responsável de Segurança com o Arquitecto de Plataforma, como o próprio bloco diz. A revisão adversarial está em [`ANALISE-14`](../docs/analises/ANALISE-14-KAM-131-gate-9-na-historia.md). | Equipa KAMBÁ |
| 1.15 | Outubro 2026 | KAM-136 entregue: 13 caixas marcadas e 1 vazia (a dos revisores humanos), com secção de verificação, seis decisões e duas devolvidas; a revisão adversarial está em [`ANALISE-12`](../docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md). O leitor de YAML do CI deixa de ter casos em que lê mal sem o dizer: **101** construções classificadas contra o leitor anterior, **56** leituras silenciosas fechadas (46 por recusa) e 5 recusas que recusavam de mais desfeitas; a estrutura lida dos 22 ficheiros reais é igual antes e depois (2 221 campos folha, 0 divergências). **A primeira versão da correcção não cumpria o objectivo:** a revisão independente devolveu 2 bloqueadores — um deles o mesmo defeito de fronteira do caso 1, no outro extremo do bloco — e 26 achados, todos com disposição escrita. Duas decisões devolvidas: a frase do CA 4 está errada quanto ao `ci/waivers.yaml`, e os outros dois leitores de subconjunto de YAML do repositório ficaram por varrer (lacuna 22 de `../docs/ci.md` §7). | Equipa KAMBÁ |
| 1.16 | Outubro 2026 | KAM-132 entregue: 10 caixas marcadas e 3 vazias (a dos revisores humanos, o DoD que depende de todos os CA, e a da régua igual nos dois lados), com secção de verificação e as decisões devolvidas; a revisão adversarial está em [`ANALISE-15`](../docs/analises/ANALISE-15-KAM-132-cobertura-de-todo-o-typescript.md). O *gate* 4 passa a medir todo o código do âmbito que o Node executa, carregado ou não: `make ci-4` dá `restante` 91% → 91% e `critico` 99% → 94%, e um módulo de 50 declarações sem teste, que deixava os três números iguais, passa a levar o `restante` de 91% para 88%. **O limiar não foi tocado.** Duas correcções ao que o ticket supunha: a `--test-coverage-include` é um filtro, sozinha não move o denominador e **não se usa** — retirava do relatório o ficheiro que nenhum estrato classifica, que tem de falhar o *gate* —, e o estrato que descia não era o `restante`, que não tinha nada invisível, mas o `critico`. A revisão independente devolveu 3 maiores, 9 menores e 1 suspeita, com disposição escrita para todos; as mutações passaram de 17 para 24, todas apanhadas. Três lacunas novas em `../docs/ci.md` §7 (23 a 25). | Equipa KAMBÁ |
| 1.17 | Outubro 2026 | KAM-144 acrescentado: a reciprocidade `Dependências`↔`Bloqueia` regrediu de 0 para 8 falhas — os KAM-131 a KAM-138 declaram depender do KAM-002 e nenhum estava no seu `Bloqueia`, que passa de 7 para 15 arestas. O ticket não declara dependência: a proveniência (foi apurado a remedir o critério 9 do KAM-129) fica em prosa, porque inscrevê-la punha no grafo uma aresta técnica que não existe. Medido por máquina antes e depois (143 blocos, 8 falhas → 144 blocos, 0 falhas), com sincronia, ciclos, prioridades, fases, unicidade e contagens a 0 nas duas passagens. A revisão adversarial devolveu 2 achados maiores e 9 menores, todos com disposição escrita no bloco: um número publicado que não reproduzia em *commit* nenhum (10 580 contra os 10 895 reais) e uma afirmação falsa que servia de fundamento à recomendação devolvida. **A correcção é de dados e não fecha a causa:** o KAM-138 (gate 3c) continua não implementado, e a recomendação de o subir a P1/Fase 0 fica escrita no bloco e devolvida ao Arquitecto de Plataforma. | Equipa KAMBÁ |
| 1.18 | Outubro 2026 | Emenda ao KAM-144, depois do merge do PR #44: as contagens de arestas do critério 3 diziam **760 / 380 / 380** e são **758 / 379 / 379**. Eram a medição feita antes de a revisão adversarial retirar a aresta `KAM-144`→`KAM-129`, e não reproduziam no commit fundido (`148567c`, medido em 379/379). É a mesma classe de defeito do achado maior M1 — número dependente do texto medido antes da última alteração ao texto — e a terceira ocorrência neste ticket. As 0 falhas de reciprocidade, os 144 blocos e as 144 linhas do mestre **não mudam** e foram remedidos no commit fundido. Corrigido também o `ANALISE-16` (v1.1) e uma vírgula a mais. E a linha do DoD das referências deixou de citar o total do `lint_refs`: esse total conta as referências `KAM-NNN` do próprio texto que o publica, mexeu cinco vezes durante este ticket (10 580 → 10 895 → 10 914 → 10 919 → 11 117) e é instável por construção — fica o veredicto «conforme» e o conjunto `KAM: 144`, que são estáveis. | Equipa KAMBÁ |
| 1.19 | Outubro 2026 | KAM-145, KAM-146 e KAM-147 acrescentados: as três lacunas documentais que a medição dos critérios do KAM-128 deixou fora do seu encerramento. O KAM-145 decide a forma do caminho dentro dos blocos de *handoff* e manda declarar o *cwd* do executor nos padrões — a questão que o KAM-129 deixou em aberto, e de que dependem as sete referências nuas à biblioteca exploratória que restam; o KAM-146 paga as onze linhas de «Controlo de versões» que faltam; o KAM-147 fecha a linha de DoD dos dois tickets que nomeia um anexo de evidência inexistente. Os três dependem do KAM-128 e entram no seu `Bloqueia`. Total: 147 tickets. | Equipa KAMBÁ |
| 1.20 | Outubro 2026 | Quarto critério de aceitação do KAM-136 emendado, fechando a primeira decisão devolvida do bloco e a linha 17 de [`dividas-documentais`](../docs/dividas-documentais.md). A frase dizia que `razao: >-` seguido de mais chaves era a forma que `ci/licenses.yaml`, `ci/refs-allow.yaml`, `ci/secrets-allow.yaml` e `ci/waivers.yaml` usam «na maioria das entradas». O `ci/waivers.yaml` tem `waivers: []` e a única ocorrência está num exemplo comentado. A varredura posicional dos 22 ficheiros acrescentou duas coisas que a frase não dizia: o `ci/canon-lint.yaml` usa a forma mais do que qualquer um dos nomeados (10 ocorrências) e estava omitido, e nos quatro o `razao: >-` é sempre a **última** chave do item — a forma com uma chave **depois** dele, que é a que o defeito engolia, só existe nos dois estratos do `ci/thresholds.yaml`. O critério passa a nomear as duas posições e os ficheiros de cada uma; a mesma frase foi corrigida no Handoff, e a contagem da linha de verificação do CA 4 passa de 50 para as 28 ocorrências de `razao: >-` (as 50 são a forma 8 da evidência, `chave: >-` com qualquer nome de chave). Nenhum `ci/*.yaml` nem o `tools/kamba_yaml.py` alterados: a construção já estava coberta por teste. O **KAM-138** (gate 3c) ganha dois critérios: o «Controlo de versões» de cada documento passa a ser sequência sem buracos com o cabeçalho a dizer a última, nas duas formas que o conjunto usa. Medido ao escrevê-los: 25 documentos com a tabela, 1 buraco (o `1.13` deste epic) e 9 cabeçalhos atrasados. Nasceu de este ramo ter renumerado quatro vezes em poucas horas — 1.16 (KAM-132), 1.17 (KAM-144), 1.18 (PR #48) — e de o `1.13` ter nascido da mesma colisão. | Equipa KAMBÁ |
| 1.21 | Outubro 2026 | KAM-148 acrescentado: a varredura de leituras silenciosas nos outros dois leitores de subconjunto de YAML (`tools/canon_lint/yamlreg.py` e `tools/secrets_inventory/yamlsubset.py`), que o KAM-136 declarou fora do seu âmbito e registou como lacuna 22 de `../docs/ci.md` §7 e decisão devolvida ao fundador. Depende do KAM-136, que lhe dá o método e o padrão do oráculo, e entra no seu `Bloqueia`. | Equipa KAMBÁ |
| 1.22 | Outubro 2026 | KAM-150 acrescentado e entregue: as três regras de `CODEOWNERS` que ficaram presas ao prefixo `/tecnica/` removido pelo KAM-128 passam a `/docs/tecnica/`. **3 de 18 regras estavam penduradas, agora 0** — uma regra que aponta para um caminho inexistente não atribui dono nenhum e não avisa. 11 caixas marcadas e 1 vazia (a dos revisores humanos, que o DoD deste ticket pede em dobro por se tocar num ficheiro de regra de revisão). O defeito estava declarado fora de âmbito na verificação do KAM-128, cujo DoD «**Referências**» **continua por marcar**: tinha duas causas e esta era uma. O aviso do cabeçalho sobre as equipas serem *proposta* foi reavaliado e mantém-se — o repositório é de um utilizador, pelo que nenhuma equipa `@kamba/*` pode existir, e o *ruleset* tem `require_code_owner_review: false`; o ficheiro corrigido continua inerte, e isso passou a estar escrito nele. A revisão adversarial está em [`ANALISE-17`](../docs/analises/ANALISE-17-KAM-150-codeowners-pendurado.md) e **reprovou a primeira versão**, com 3 achados P0: o ticket nasceu com o número 145, um ID já reclamado por outro ramo; deixou o gate 3 **vermelho** com 7 referências inválidas e a caixa «Referências» marcada por cima; e ligava quatro vezes para uma análise que não existia. Os três estão fechados, e o padrão que partilham — afirmar por memória o resultado de uma verificação corrida antes da redacção que a quebrou — está escrito em [`KAM-150.md`](../docs/evidencia/KAM-150.md) §5.2. Duas decisões devolvidas: o gate que validaria estes caminhos (código, ticket próprio) e a imposição da revisão (KAM-137 e L-19). | Equipa KAMBÁ |
| 1.23 | Outubro 2026 | KAM-151 acrescentado: fecha a lacuna 25 de `../docs/ci.md` §7. O `make coverage-python` ganha o terceiro `--source=`, e a falta de um `--source=` para uma pasta de `.py` do âmbito passa a falhar um teste. Medido: o **delta**, que é o que o ticket faz e não depende da árvore: **+29** no numerador, **+31** no denominador, **+3** ficheiros, com a percentagem a não se mover. Na árvore que funde: `restante` 92% → 92% (9880/10730 → 9909/10761), 100 → 103 ficheiros; em `f4c7e3d`, onde foi medido primeiro, era 91% → 91% (9652/10526 → 9681/10557). O absoluto subiu porque o KAM-148 acrescentou código testado a `tools/`, que está no estrato; limiar não tocado. A revisão adversarial ([`ANALISE-18`](../docs/analises/ANALISE-18-KAM-151-cobertura-python-do-agr.md)) devolveu 2 maiores, 6 menores e 2 suspeitas, e desmentiu uma afirmação deste bloco: um `.py` medido a 0% **não** sai nomeado no relatório do *gate* — lacuna 26 nova. Prova por mutação do *gate* 4 de 24 para 28, 0 sobreviventes. O `Bloqueia` do KAM-132 passa a nomear o KAM-151. | Equipa KAMBÁ |
| 1.24 | Outubro 2026 | KAM-152 acrescentado e entregue: o caminho `db/gate8.py` — o ficheiro chama-se `db/gate_bd.py` desde que passou a servir os *gates* 8 e 6 — estava citado em **8 ocorrências de 7 ficheiros**, **7 delas vivas em 6 ficheiros**, e uma é a mensagem de `SkipTest` do trinco de `db/tests/base.py`, que mandava o utilizador correr um ficheiro inexistente. O pedido nomeava três sítios; a varredura encontrou seis ficheiros vivos, com o comentário do job `gate-8-migracoes` em `../.github/workflows/ci.yaml` e o *docstring* de `db/bootstrap.py` por nomear. O nome do trinco (`kamba_gate8`, `*_gate8`, `kamba-gate8-*`: **21** ocorrências em ficheiros vivos, iguais em `main` e no ramo) **não** foi tocado — é o nome canónico da base descartável —, e a fasquia `grep gate8 → 0` do pedido fica registada como impossível à letra. `../docs/seguranca/validar.py`, com o `assert` da contagem relaxado **em memória**, passa de **5** para **3** erros, sem nenhum novo; corrigir o `assert` é o **KAM-149**. **O ticket nasceu KAM-150 e renumerou para 152:** o `albinoJimy/kamba#47` fundiu durante o trabalho e levou o 150, e o 151 está reclamado por um ramo em voo — o ID só está seguro depois do *merge*, e as contagens fecham-se depois de integrar `main`. A linha 6 de `../docs/dividas-documentais.md` fecha metade e fica reescrita, não riscada. **A causa não é fechada:** nada no repositório verifica um caminho citado em código (L-20), e a decisão de alargar o validador a `db/` e `../.github/` fica devolvida ao Arquitecto de Plataforma. | Equipa KAMBÁ |

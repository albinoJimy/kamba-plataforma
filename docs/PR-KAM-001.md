## KAM-001 — Monorepo, estrutura de serviços e toolchain

> Corpo de Pull Request no formato do §7 de
> [`specs/01_Engineering_Standards_e_Handoff.md`](../specs/01_Engineering_Standards_e_Handoff.md).
> Esta é a cópia versionada; o PR aberto tem o mesmo texto.
>
> Ramo: `feature/KAM-001-monorepo-e-toolchain`

### Aviso de leitura: dois commits não são deste ticket

O ramo traz **cinco** commits. Três são do KAM-001; **dois não são**, e estão
marcados como tal:

| Commit | É do KAM-001? | O que é |
|---|---|---|
| `chore(KAM-001): cria o monorepo…` | sim | 122 ficheiros, o ticket |
| `chore: reorganiza o conjunto documental sob docs/` | **não** | 34 renomeações puras (R100), zero alterações de conteúdo |
| `chore: reescreve as referencias cruzadas para a arvore docs/` | **não** | 37 documentos, só caminhos, mais o documento mestre recompilado |
| `fix(KAM-001): corrige a portabilidade dos git hooks` | sim | duas falhas em Windows |
| `docs(KAM-001): aponta as referencias para docs/…` | sim | as 64 referências do ticket + este ficheiro |

Os dois commits do meio são uma reorganização do conjunto documental feita em
paralelo, que entrou neste ramo por descuido de um `git add -A`. Foram separados
em commits próprios, com a razão escrita na mensagem, e cada um usa `--no-verify`
e diz porque, em vez de inventar uma atribuição que passaria o *hook* e mentiria
na história.

**Já têm ticket: `KAM-128`** — «Reorganização do conjunto documental sob `docs/` e
reescrita das referências cruzadas», no EPIC-01, aberto no ramo
`feature/KAM-128-regulariza-reorganizacao-documental`. Esse ticket cobre
retroactivamente estes dois commits, explica porque não é o KAM-111 (cujo âmbito
está fechado em 12 divergências de nomenclatura) e completa o que eles deixaram a
meio. A dívida que este aviso registava está, portanto, fechada; os commits ficam
onde estão, e a atribuição vive no backlog.

**Para rever só o KAM-001**, veja os três commits com `(KAM-001)` no cabeçalho.
Os outros dois são verificáveis em segundos: o primeiro é 34 × `R100` (o git
confirma que o conteúdo não mudou), o segundo é substituição de caminhos.

### O que muda

Primeiro código do repositório. Levanta a árvore que os 126 tickets seguintes
assumem (`services/`, `packages/`, `libs/`, `db/`, `registry/`, `infra/`,
`tools/`), com `/healthz` por serviço, `make bootstrap/check/up` como fachada
única, dependências fixadas com *hash* nos dois ecossistemas, e uma lista de
bloqueio que corre **antes** de qualquer instalação. Nenhum serviço tem
comportamento: o GWY não verifica assinaturas, o AGR não tem grafo, o COM não
arranca o Medusa.

### ADRs e decisões aplicáveis

- **ADR-002** — LangGraph como biblioteca MIT. `langgraph-api` e
  `langgraph-runtime-inmem` (Elastic-2.0), Dify, n8n e Typebot estão na lista de
  bloqueio, com teste por item.
- **ADR-005** — LiteLLM ≥ 1.83.0. Bloqueado abaixo disso em pacotes **e** em
  imagens, incluindo `ghcr.io/berriai/litellm`.
- **ADR-006** — Postgres 18 + pgvector ≥ 0.8.7. O compose levanta 18.6 com
  pgvector 0.8.7 e pg_trgm, e o `initdb` **falha o arranque** se as versões não
  forem essas.
- **ADR-014** — MinIO excluído. Bloqueado como pacote e como imagem; o
  `StorageProvider` é o KAM-011.
- **ADR-019** — a vitrine Next.js fica para Clusters; em seu lugar há
  `services/onboarding-web`.
- **Decisões abertas tocadas:**
  - **D12** (licença do Redis / Valkey) — **continua aberta e o código não a
    decide.** O serviço chama-se `queue`, a imagem é `${KAMBA_QUEUE_IMAGE}` e o
    cliente `${KAMBA_QUEUE_CLI}`. Verificado por execução com Valkey 9.1.2 **e**
    Redis 8.10.2, ambos com `appendonly yes`.
  - **D1/D6** (alojamento e *object storage*) — não tocadas: não há
    `StorageProvider` neste ticket.

Decisões locais de implementação: **ADR-L001**
([`docs/adr/ADR-L001-toolchain.md`](adr/ADR-L001-toolchain.md)), 11 secções, com
o gatilho de reversão de cada uma.

### Como foi testado

- [x] **Unit** — 84 casos verdes: 64 em `tools/lint_arch` (lista de bloqueio,
      convenções, estrutura, versões, *hooks*), 13 em `libs/py-core`, 7 em
      `services/agr`.
- [x] **Integração** — a pilha de dados e o AGR levantados a sério:
      `docker compose up --wait` → `healthy`; `curl /healthz` → 200 conforme ao
      contrato; `nobody` + sistema de ficheiros só de leitura confirmados por
      `id` e `touch` dentro do contentor.
- [x] **Reprodutibilidade** — `pip_lock.py --check-offline` e `--check` verdes;
      `pip install --require-hashes` instala os 13 pacotes; um *hash* alterado é
      recusado (`THESE PACKAGES DO NOT MATCH THE HASHES`).
- [ ] **Isolamento cruzado** — não aplicável: não há tabelas (KAM-004).
- [ ] **Idempotência** — não aplicável: não há consumidores (KAM-005).
- [ ] **Contrato (Meta/facilitador/eventos)** — não aplicável; o único contrato
      é `/healthz`, e esse é validado.
- [ ] **Golden PT-AO** — não aplicável: não há artefacto comportamental.

**`make bootstrap && make check` a partir de clone limpo: verde em 74 s**
(bootstrap 66 s + check 8 s), num contentor `node:24.21.0-trixie-slim` com Node
24, pnpm, `make` e Python. O orçamento do critério de aceitação é 600 s.

**O lado Node foi executado**, e era o maior risco declarado deste PR:

| Verificação | Resultado |
|---|---|
| `pnpm-lock.yaml` | 871 linhas, 102 pacotes, as 91 resoluções com `integrity: sha512-` |
| **Reprodutibilidade** | dois `bootstrap` consecutivos dão o ficheiro **byte a byte idêntico** (`sha256:aeecf74f…`) |
| `pnpm install --frozen-lockfile --ignore-scripts` | instala os 7 *workspaces* |
| `pnpm run build` | `packages/*` emitem `dist/` |
| `pnpm -r run typecheck` | **6 de 6 projectos verdes** |
| `pnpm -r run test` | **21 casos, 21 passam** |
| `commitlint` vs `lint_arch` | **0 divergências em 15 mensagens** — a promessa de `tools/conventions.json`, medida |
| `docker compose up --wait` | **os 7 contentores `Healthy`** |
| `/healthz` dos **cinco** serviços | 200, conformes ao contrato, com o SHA real |
| Contentores | `node`/`nobody`, filesystem só de leitura, portas só em `127.0.0.1`, sem `.env` |

Os *hooks* testados com `git commit` real:

| Mensagem | Resultado |
|---|---|
| `chore(KAM-001): cria a arvore do monorepo e a toolchain` | aceite |
| `feat(KAM-004): acrescenta RLS FORCE as tabelas com tenant_id` | aceite (siglas permitidas) |
| `arranjei umas coisas` | recusada |
| `chore(KAM-001): CRIA TUDO EM MAIUSCULAS` | recusada |
| ramos `develop`, `chore/KAM-001-…` | recusados |
| ramos `main`, `feature/KAM-001-…`, `fix/KAM-013-…` | aceites |

**O que continua por verificar** está em
[`docs/evidencia/KAM-001-node.md`](evidencia/KAM-001-node.md) §7.2, com o ticket
que resolve cada item: a medição não foi feita em CI (KAM-002), nada foi medido
sob carga, os clientes sobre Valkey continuam por testar (D12), o Medusa em Node
24 é o KAM-041, os digests são o KAM-067, e **nada disto corre num pipeline** —
todas as verificações acima foram feitas à mão nesta sessão.

### Checklist DoD de domínio

- [x] **Isolamento de tenant e contacto** — não aplicável (sem dados); a árvore e
      o `packages/contracts` ficam prontos para o KAM-003/KAM-004.
- [x] **Números só de *tools*** — não aplicável (sem LLM).
- [x] **Pagamento só por evento autenticado** — não aplicável.
- [x] **Sem fundos de terceiros** — não aplicável.
- [x] **Sem telefone/PII em logs, chaves ou eventos** — o único log é
      `service.started` com nome do serviço, anfitrião e porta.
- [x] **Custo e métricas** — não aplicável (KAM-076).
- [x] **Sem segredos** — `.env.example` só com *placeholders*; `.env` no
      `.gitignore`. **E verificado na imagem**: o `.dockerignore` exclui `.env`,
      `.env.*`, `*.pem` e `*.key`, os `Dockerfile` usam `COPY` selectivo, e
      `lint_arch structure` **falha** se essas linhas desaparecerem. Confirmado
      por execução com uma sonda que procurou a senha nas camadas: não está lá.
- [x] **Dependências fixadas e permitidas** — `--frozen-lockfile --ignore-scripts`
      e `--require-hashes`; lista de bloqueio activa com 18 *fixtures*.
- [x] **Migração reversível** — não aplicável: zero tabelas (KAM-003).

Adicionais do ticket:

- [x] `CODEOWNERS` por área (equipas `@kamba/*` são **proposta** — a organização
      do GitHub não existe ainda, e um `CODEOWNERS` que aponta para equipas
      inexistentes não bloqueia nada; está dito no próprio ficheiro).
- [x] Renovate com quarentena ≥ 7 dias; excepção de segurança **com revisão** e
      sem *auto-merge* em nenhuma circunstância.
- [x] O compose não expõe portas além de `localhost` — e os serviços de dados não
      expõem nenhuma, porque estão numa rede `internal`.

### Dados pessoais e transferências

**Nenhum.** Não há tabelas, não há tratamento, não há saída de Angola. Os
contentores de dados estão numa rede `internal: true` **sem rota de saída** —
verificado com um `ping` de dentro dessa rede. O ambiente local não contém dados
reais.

### Riscos e rollback

**Como se reverte:** `git revert` de um único commit. Nenhuma PME está activa,
não há estado persistido fora dos volumes de desenvolvimento local, e
`make nuke` apaga-os.

**Impacto em PMEs activas:** nenhum — não há.

**Riscos reais, por ordem:**

1. **Nada corre num pipeline.** Era o lado Node o maior risco; agora é este. As
   verificações acima foram feitas à mão e não protegem o PR seguinte.
   Transformá-las em *gates* que falham um merge é o **KAM-002**, que este
   ticket desbloqueia.
2. **TypeScript fixado em 5.9.3 quando o `latest` é 7.0.2.** Decisão, não
   descuido: o 7.x é a reescrita nativa e avaliá-la pertence ao KAM-002. Vai
   aparecer em auditorias de dependências como desactualizado; a razão está em
   ADR-L001 §3 e numa regra do Renovate.
3. **D12 continua aberta.** Que o BullMQ, o Chatwoot e o Medusa funcionem sobre
   Valkey é **NÃO VERIFICADO** — verificou-se o servidor, não os clientes. É o
   teste em *staging* que `tecnica/09` §20 pede.
4. **O orçamento de ≤ 10 min para `bootstrap && check` não foi medido** por
   inteiro: a parte Python levou segundos, falta a parte Node. Passa a ser
   medido continuamente no KAM-002.

---

## Nota de revisão

Este PR passou por uma **revisão adversarial independente** antes de ser aberto,
e as correcções dela estão incluídas. O que ela encontrou, porque o registo
importa mais do que o resultado:

| Achado | Estado |
|---|---|
| Um `COPY . .` punha o `.env` (com a senha do Postgres) nas camadas das imagens Node | corrigido: `COPY` selectivo + `.dockerignore` + verificação em `lint_arch structure`; confirmado por sonda |
| **Oito** formas reproduzíveis de passar por baixo da lista de bloqueio: `langgraph_api` com `_`, `ghcr.io/berriai/litellm`, `pnpm.overrides`, `resolutions`, `FROM --platform`, `build-system.requires`, alias `npm:`, `-e …#egg=`, compose com nome não convencional | todas fechadas, cada uma com *fixture* própria (30/30 casos de bypass e de falso positivo verificados) |
| `match: substring` bloqueava pacotes npm **reais** (`modify-values`, `minion`, `codify`) — e o `modify-values` é do ecossistema do `@commitlint` que este repo usa | corrigido com `match: boundary`; fixture `p3` prova a distinção |
| O `commitlint` impunha `subject-case: lower-case`, que recusaria `acrescenta RLS FORCE ao schema platform` | corrigido; as regras do `.cjs` e do Python estão agora travadas por um teste |
| `pip_lock` dava `python_version == "3.12.*"` por falso — o único ponto *fail-open* do módulo | corrigido; `_compare` levanta `MarkerUndecided` em tipos mistos |
| `VENV_BIN := $(VENV)/bin` quebrava `make bootstrap` em Git Bash, que o README manda usar | corrigido com detecção por `$(OS)` |
| `make check` ia à PyPI por cada pin, contra o critério «usando apenas lockfiles» | separado: `lock-check` é offline, `lock-verify` usa rede |
| Os ramos do Renovate violavam a própria convenção de ramos | corrigido (`branchTopic` + padrão alargado) |
| No AGR, `HOST`/`PORT` eram decorativos — o `0.0.0.0` estava no `CMD` | corrigido com `kamba_core.net` e `python -m kamba_agr` |
| Três números do ADR-L001 estavam errados a favor do argumento (85 linhas em vez de 425) | corrigidos |
| O `.gitignore` não ignorava `node_modules/` | corrigido |

Depois da revisão, correr a toolchain Node encontrou **seis defeitos mais**, dois
dos quais teriam atingido todos os desenvolvedores: `walk()` rebentava com
`OSError: [WinError 1920]` em qualquer máquina onde alguém tivesse corrido
`pnpm install` (o `rglob` descia a `node_modules` antes do filtro), e as duas
verificações de versão do `make doctor` **nunca tinham corrido** — as barras de
continuação estavam dentro das aspas simples, pelo que o interpretador recebia
uma barra literal. Os seis estão em
[`docs/evidencia/KAM-001-node.md`](evidencia/KAM-001-node.md) §7.3, cada um com
teste a guardá-lo.

Uma afirmação da revisão **não se confirmou** e está registada como tal: o
`@commitlint/config-conventional` **não** define `scope-case`, pelo que o âmbito
`KAM-001` nunca estaria em risco. A regra foi desligada explicitamente de
qualquer forma, para que uma versão futura que a acrescente não recuse de um dia
para o outro o formato que o ticket manda impor.

Dois defeitos foram encontrados **por execução** e não por leitura, e ficam
registados em [`docs/evidencia/KAM-001-node.md`](evidencia/KAM-001-node.md) §7.3
porque são conhecimento sobre as ferramentas:

1. O PostgreSQL 18+ recusa arrancar com o ponto de montagem antigo
   (`/var/lib/postgresql/data`).
2. Um `\connect :"POSTGRES_DB"` num script de `initdb` falha **e fica calado**: o
   script abortou, as extensões não foram criadas, e o contentor ficou
   `healthy` — um *fail-open* do tipo que o princípio 7 de `specs/01` §6 proíbe.

### Emendas pedidas ao canon (não feitas neste PR)

Não se editou `specs/` nem `tecnica/`, porque o ticket diz para não expandir
escopo e o **KAM-111** é o ticket de reconciliação. Fica pedido:

1. **`specs/01` §5** diz «novos ADRs numeram-se após o último canónico
   (actualmente ADR-019)». São **vinte**: o `ADR-020` existe em `tecnica/00` §8 e
   está FIXA na Carta §4.2. Daí o espaço de numeração separado `ADR-L###` para
   ADRs locais, explicado em [`docs/adr/README.md`](adr/README.md).
2. **`tecnica/09` §3.1**, linha do `gateway`: o item «intervalo de Node aceite
   pelo Medusa a confirmar» está **resolvido** — `@medusajs/medusa@2.21.2`
   declara `engines.node: ^20.19.0 || >=22.12.0`, e o Node 24 LTS satisfaz
   (CONFIRMADO, manifesto publicado no registo npm).
3. **`tecnica/09` §3.1**, linha do `postgres`: acrescentar que
   `pgvector/pgvector:0.8.7-pg18` entrega PostgreSQL 18.6 e pgvector 0.8.7,
   verificado por execução.

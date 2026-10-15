# KAM-001 — Node, Hono e a pilha de desenvolvimento: evidência de execução

| Campo | Valor |
|---|---|
| Ticket | KAM-001 — Monorepo, estrutura de serviços e toolchain |
| Propósito | Registar o intervalo de Node aceite pelo Medusa 2.21.x e as versões que o compose de desenvolvimento fixa, com fonte e estado |
| Origem do pedido | Critério de aceitação do KAM-001: «o ficheiro `docs/evidencia/KAM-001-node.md` registra o intervalo de Node aceite pelo Medusa 2.21.x lido do `package.json` oficial (item NÃO VERIFICADO em `../tecnica/09` §3.1)» |
| Data das leituras | 2026-10-10 |
| Estado | Ver cada secção; a escala é **CONFIRMADO** / **INDÍCIO** / **NÃO VERIFICADO** |

Este documento é um anexo de execução do KAM-001, não um anexo de evidência
canónico. Os anexos canónicos são `../tecnica/evidencia/E1`–`E5`; o que aqui se
apura e que corrige um item de `../tecnica/`, corrige-se lá por emenda — ver §6.

---

## 1. O item que estava NÃO VERIFICADO

`../tecnica/09` §3.1, linha do `gateway`, diz:

> **Hono 4.13.x** (não 5.0.0-rc.0, de 2026-10-08); **Node 24 LTS** em vez de Node 20
> (Node 20 chegou ao fim de vida em Abril de 2026, conhecimento geral, INDÍCIO);
> **intervalo de Node aceite pelo Medusa a confirmar no `engines`**

A pergunta em aberto era uma só, e é material: **o Medusa 2.21.x aceita o Node 24?**
Se não aceitasse, o Piloto teria de correr dois runtimes de Node — um para o GWY
e outro para o COM — e isso mudaria a topologia, não apenas uma linha de
`package.json`.

---

## 2. Resposta: o Medusa 2.21.2 aceita o Node 24

**Estado: CONFIRMADO** (manifesto publicado, fonte primária).

| Item | Valor |
|---|---|
| Pacote | `@medusajs/medusa` |
| Versão lida | `2.21.2` |
| Fonte | `https://registry.npmjs.org/@medusajs/medusa/2.21.2` (manifesto publicado no registo npm), lido a 2026-10-10 |
| Campo `engines` | `{"node":"^20.19.0 \|\| >=22.12.0"}` |
| Requisito de `npm` | nenhum declarado |

Leitura do intervalo:

- `^20.19.0` — a linha Node 20, de 20.19.0 até abaixo de 21.
- `>=22.12.0` — tudo a partir de 22.12.0, **sem limite superior**.

**Node 24.21.0 satisfaz `>=22.12.0`.** Não há conflito entre o Medusa 2.21.x e o
Node 24 LTS, e a topologia do Piloto fica com um único runtime de Node.

Duas observações que a leitura obriga a registar:

1. O intervalo **não tem tecto**. Isso não é uma garantia de que o Medusa foi
   testado em Node 24 — é a ausência de uma proibição. A diferença importa: o
   `engines` diz o que o `pnpm` recusa a instalar, não o que o fornecedor
   suporta. Se a matriz de CI oficial do Medusa não incluir o Node 24, há risco
   residual, e esse ponto fica **NÃO VERIFICADO** (ver §5).
2. O `^20.19.0` confirma indirectamente que o Node 20 ainda é um alvo declarado
   do Medusa. A nossa razão para não o usar é o fim de vida do Node 20, não o
   Medusa.

---

## 3. Versões que o KAM-001 fixa, com fonte

| Componente | Versão fixada | Onde está fixada | Fonte e estado |
|---|---|---|---|
| Node | `24.21.0` (LTS «Krypton») | `.node-version`, `.nvmrc`, `engines.node` de `package.json` (`>=24.21.0 <25`) | `https://nodejs.org/dist/index.json`, lido a 2026-10-10: `v24.21.0`, 2026-09-07, `lts: "Krypton"`; é a linha LTS mais recente. **CONFIRMADO** |
| pnpm | `12.11.2`, com hash de integridade | campo `packageManager` de `package.json` | `https://registry.npmjs.org/pnpm/latest`, lido a 2026-10-10: `12.11.2`, `integrity: sha512-JaUWUqGWeFr18ova…` (o hash está no `packageManager`, e é o Corepack que o verifica). **CONFIRMADO** |
| Hono | `4.13.13` | `dependencies` dos quatro serviços Node | `https://registry.npmjs.org/hono/latest`, lido a 2026-10-10: `4.13.13`, `engines: {"node":">=16.9.0"}`. Coerente com `../tecnica/09` §3.1 e E4 §2.13; o `5.0.0-rc.0` **não** entra. **CONFIRMADO** |
| TypeScript | `5.9.3` | `devDependencies` da raiz | O `latest` do registo é `7.0.2` (`engines: {"node":">=16.20.0"}`), lido a 2026-10-10. A escolha do 5.9.3 é **decisão**, não evidência: ver `docs/adr/ADR-L001-toolchain.md` §4. **CONFIRMADO** quanto às versões existentes |
| `@types/node` | `24.19.2` | `devDependencies` da raiz | O `latest` é `26.6.5`; usa-se o major que corresponde ao runtime (24.x), porque tipos de Node 26 sobre um runtime Node 24 descrevem APIs que não existem. **CONFIRMADO** |
| PostgreSQL | `18.6` | imagem `pgvector/pgvector:0.8.7-pg18` no compose | Verificado por execução a 2026-10-10, duas vezes: `docker run --rm --entrypoint postgres … --version` → `postgres (PostgreSQL) 18.6 (Debian 18.6-1.pgdg12+2)`; e, dentro da pilha a correr, `current_setting('server_version')` → `18.6 (Debian 18.6-1.pgdg12+2)`. Digest observado: `sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11`. **CONFIRMADO** |
| pgvector | `0.8.7` | mesma imagem | Verificado em execução a 2026-10-10: `pg_extension` → `vector 0.8.7`, e `'[1,2,3]'::vector <-> '[1,2,4]'::vector` = `1`. O script de arranque **falha o arranque** se `extversion` não for `0.8.7`, pelo que a afirmação é reverificada em cada `make up`. **CONFIRMADO** |
| pg_trgm | `1.6` (contrib do PG 18) | mesma imagem | Verificado em execução: `similarity('kamba','kambá')` = `0.5`. **CONFIRMADO** |
| Fila (D12) | `valkey/valkey:9.1.2-trixie` por omissão | variável `KAMBA_QUEUE_IMAGE` | Verificado em execução a 2026-10-10: `valkey_version:9.1.2`, `appendonly yes`, `appendfsync everysec`, e um valor escrito sobreviveu a `restart` (AOF a funcionar). É **proposta**: a decisão D12 está ABERTA (`../tecnica/00` §13.3). Ver §4 |
| Python (AGR) | `3.12` | `requires-python = ">=3.12,<3.13"`, imagem `python:3.12-slim-trixie` | `../tecnica/09` §3.1. **CONFIRMADO** como decisão de desenho |

### 3.1 Nota sobre o digest do Postgres

O digest acima está registado porque foi observado, **não porque esteja fixado**.
O compose referencia a tag, não o digest: fixar imagens por digest, gerar SBOM e
verificar assinaturas é o **KAM-067**, e antecipá-lo aqui seria expandir escopo.
O digest fica aqui para que o KAM-067 tenha um ponto de partida datado.

> **Nota posterior (KAM-067, 2026-10-12).** O compose passou a referenciar o
> digest, e não só a tag. Relido da fonte nesse dia, o digest é o mesmo que
> aqui ficou registado. O inventário vive em `ci/supply-chain/imagens.yaml`.

---

## 4. D12 continua aberta, e o código não a decide

A decisão **D12** (`../tecnica/00` §13.3; `specs/00_KAMBA_Carta.md` §4.2) cobre a
licença do Redis e a alternativa Valkey. Está **ABERTA**.

O que o KAM-001 fez para não a fechar por acidente:

| Mecanismo | Efeito |
|---|---|
| O serviço no compose chama-se `queue`, não `redis` nem `valkey` | O nome do serviço é também o nome DNS na rede do compose; chamá-lo `redis` escreveria a decisão em cada cadeia de ligação |
| `image: ${KAMBA_QUEUE_IMAGE:-valkey/valkey:9.1.2-trixie}` | Trocar de implementação é mudar uma variável de ambiente |
| `healthcheck` usa `${KAMBA_QUEUE_CLI:-valkey-cli}` | O cliente de linha de comando difere entre as duas imagens; é a única outra diferença observável |
| `command` só com flags (`--appendonly yes …`) | Os *entrypoints* das duas imagens prefixam o binário do servidor quando o primeiro argumento começa por `-`, pelo que o mesmo `command` serve ambas |
| Nenhuma dependência de código | No KAM-001 nenhum serviço se liga à fila; quando se ligar (KAM-005), liga-se por `redis://` — que é o esquema que os clientes usam para as duas |

Para experimentar Redis em vez de Valkey, `.env`:

```
KAMBA_QUEUE_IMAGE=redis:8.10.2-trixie
KAMBA_QUEUE_CLI=redis-cli
```

**Verificado por execução a 2026-10-10**, e não apenas afirmado: o mesmo ficheiro
de compose, sem uma linha alterada, levantou os dois motores com AOF activo.

| Motor | `INFO server` | `appendonly` | `appendfsync` | Estado |
|---|---|---|---|---|
| Valkey (omissão) | `valkey_version:9.1.2` | `yes` | `everysec` | `Healthy` |
| Redis (alternativa) | `redis_version:8.10.2` | `yes` | `everysec` | `Healthy` |

### 4.1 Descoberta: trocar de motor exige volume limpo

O que a execução revelou e que não estava em nenhum documento: **o AOF do Valkey
9.x e o do Redis 8.x não são intercambiáveis**. Ao apontar a variável para o
Redis sobre um volume já escrito pelo Valkey, o contentor fica *unhealthy* com:

```
# Bad file format reading the append only file
  appendonlydir/appendonly.aof.1.base.rdb at offset 0
```

Com volume limpo, o Redis arranca e fica saudável. Consequência prática para
D12: a parametrização serve para **escolher** o motor na instalação, não para
migrar entre motores com dados escritos. Isso não afecta o Piloto — a fila é
estado transitório — mas tem de estar escrito antes de alguém o descobrir em
produção. A nota está em `.env.example`, onde quem troca a variável a vai ler.

**NÃO VERIFICADO:** que o BullMQ 6.3.11, o Chatwoot 4.18 e o Medusa 2.21.x
funcionem sobre Valkey 9.x. O que acima se verificou é que o **servidor** arranca
e persiste; nada se verificou sobre os clientes. É exactamente o teste em
*staging* que `../tecnica/09` §20 pede e que D12 espera. O KAM-001 não o faz e não
finge fazer.

---

## 5. O que fica NÃO VERIFICADO

| Item | Porquê | Onde se resolve |
|---|---|---|
| Se o Medusa 2.21.x é **testado** em Node 24 (e não apenas permitido pelo `engines`) | Lemos o manifesto publicado, não a matriz de CI do projecto | KAM-041 (spike Medusa v2): o spike corre o Medusa a sério e responde por execução |
| Compatibilidade do Valkey 9.x com BullMQ, Chatwoot e Medusa | Exige *staging* e carga, não leitura | D12, `../tecnica/09` §20 |
| ~~`make bootstrap && make check` em ≤ 10 min~~ | **Resolvido**: 52 s a partir de clone limpo, num contentor Node 24 (§7.1). A medição contínua é do KAM-002 | — |
| Que o Node 20 chegou ao fim de vida em Abril de 2026 | `../tecnica/09` §3.1 marca-o INDÍCIO e continua INDÍCIO: `nodejs.org/dist/index.json` mostra `v20.20.2` de 2026-03-24 como última 20.x, o que é **consistente** com o fim de vida mas não o prova | Irrelevante para a decisão: o Node 24 é a LTS mais recente de qualquer forma |

---

## 6. Emendas que este documento pede a `../tecnica/`

O KAM-001 não edita `../tecnica/`. Fica aqui o que deve ser emendado, para que o
KAM-111 (reconciliação) ou uma emenda directa o faça:

1. **`../tecnica/09` §3.1, linha do `gateway`:** substituir «intervalo de Node
   aceite pelo Medusa a confirmar no `engines`» por «Medusa 2.21.2 declara
   `engines.node: ^20.19.0 || >=22.12.0`; o Node 24 LTS satisfaz
   (CONFIRMADO, `docs/evidencia/KAM-001-node.md` §2)».
2. **`../tecnica/09` §3.1, linha do `postgres`:** acrescentar que a imagem
   `pgvector/pgvector:0.8.7-pg18` entrega PostgreSQL 18.6 e pgvector 0.8.7,
   verificado por execução (`docs/evidencia/KAM-001-node.md` §3).
3. **`../tecnica/evidencia/E4_Stack_Licencas.md` §2.13:** o `engines` do Hono
   4.13.13 é `>=16.9.0` — não restringe nada no nosso caso.

---

## 7. Como estas leituras foram feitas, e o que isso limita

As leituras de versões foram feitas contra os registos públicos (`registry.npmjs.org`,
`pypi.org`, `nodejs.org/dist`, Docker Hub) e, no caso do PostgreSQL, por execução
do contentor. São reproduzíveis e estão datadas.

A máquina onde o KAM-001 correu tem **Docker 29.7.2** e **Python 3.13**, mas
**não tem Node, pnpm nem `make`**. O `make` e o Python 3.12 foram usados dentro
de um contentor `python:3.12-slim-trixie` sobre uma cópia limpa da árvore; o
Node não foi possível de todo.

### 7.1 O que foi executado e passou

A máquina de execução tem **Docker 29.7.2** e **Python 3.13**, e **não tem Node,
pnpm nem `make`**. Tudo o que precisava deles correu dentro de contentores
`node:24.21.0-trixie-slim` e `python:3.12-slim-trixie` sobre uma cópia limpa da
árvore. Isso cobre o lado Node por inteiro — e é o que, numa versão anterior
deste documento, estava declarado como não verificado.

#### Toolchain e reprodutibilidade

| Verificação | Resultado |
|---|---|
| `make bootstrap && make check` **a partir de clone limpo** | **verde, 52 s** (bootstrap 46 s + check 6 s). O critério de aceitação pede ≤ 10 min |
| `pnpm-lock.yaml` gerado | 871 linhas, `lockfileVersion: 9.0`, 102 pacotes distintos |
| **Dois `bootstrap` consecutivos dão lockfiles idênticos** | `sha256:aeecf74f…` nas duas vezes, byte a byte — sem *drift* |
| `pnpm install --frozen-lockfile --ignore-scripts` | instala os 7 *workspaces* a partir do lockfile |
| `packageManager` verificado pelo Corepack | o pnpm 12.11.2 é descarregado e o hash `sha512.25a51652…` confere |
| `pnpm run build` | `packages/contracts` e `packages/core-ts` emitem `dist/` |
| `pnpm -r run typecheck` | **6 de 6 projectos verdes** (`tsc -p`, `erasableSyntaxOnly` activo) |
| `pnpm -r run test` | **21 casos, 21 passam** (`node --test`, 6 projectos) |
| `make doctor` | reporta `node 24.21.0 ok`, `Python 3.13.5 ok`; **recusa Node 22.23.3** com a mensagem certa |
| Locks Python, offline e contra a PyPI | `lock-check` e `lock-verify` verdes |
| `pip install --require-hashes` | instala os 13 pacotes; um *hash* alterado dá `THESE PACKAGES DO NOT MATCH THE HASHES` |
| `lint_arch` sobre o repositório **instalado** | conforme, em 0,5 s com `node_modules` presente |
| Testes Python | 67 em `lint_arch`, 13 em `libs/py-core`, 7 em `services/agr` |

#### Convenções

| Verificação | Resultado |
|---|---|
| `commitlint` sobre 15 mensagens | 5 aceitas, 10 recusadas, com a regra citada em cada recusa |
| **`commitlint` (JS) vs `lint_arch` (Python)** | **0 divergências em 15 mensagens** — é a prova da promessa de `tools/conventions.json`: o *hook* aceita exactamente o que o CI aceita |
| Siglas no meio da descrição | `feat(KAM-004): acrescenta RLS FORCE as tabelas com tenant_id` passa nas duas vias |
| *Hooks* com `git commit` real | 7 mensagens e 5 nomes de ramo, todos com o veredicto esperado |
| Lista de bloqueio | 30/30 casos de *bypass* e de falso positivo; 102 pacotes do lockfile real, **zero colisões** |

#### Pilha a correr

| Verificação | Resultado |
|---|---|
| `docker compose up --wait` | **os 7 contentores `Healthy`**: os 5 serviços, Postgres e a fila |
| `/healthz` dos **cinco** serviços | 200, conformes ao contrato, com o SHA real do commit |
| PostgreSQL | `18.6 (Debian 18.6-1.pgdg12+2)`; `vector 0.8.7`; `pg_trgm 1.6`; **0 tabelas** |
| pgvector e pg_trgm a funcionar | `'[1,2,3]'::vector <-> '[1,2,4]'::vector` = 1; `similarity('kamba','kambá')` = 0.5 |
| Fila com AOF, nos dois motores | Valkey 9.1.2 e Redis 8.10.2, `appendonly yes`, `appendfsync everysec` |
| Utilizador dos contentores | `node` nos quatro serviços Node, `nobody` no AGR — **nenhum é root** |
| Sistema de ficheiros | `Read-only file system` nos cinco |
| Portas publicadas | todas `127.0.0.1:…`; Postgres e fila **sem publicação** (rede `internal`) |
| Rede `data` sem saída | `ping` de dentro dessa rede não sai |
| Segredos nas imagens | `/app/.env` não existe em nenhum dos cinco serviços |

### 7.2 O que continua NÃO VERIFICADO

A lista encurtou muito, mas não ficou vazia.

- **O orçamento de 52 s foi medido numa máquina, não em CI.** É o tempo de uma
  máquina com cache de rede quente; um *runner* frio descarrega os 76 pacotes e
  as imagens. A medição contínua é do **KAM-002**.
- **Nada foi medido sob carga.** O compose de desenvolvimento levanta; isso não
  diz nada sobre latência, memória residente ou concorrência. Os números de
  dimensionamento de `../tecnica/09` §4 continuam estimativa.
- **Que o BullMQ, o Chatwoot e o Medusa funcionem sobre Valkey.** Verificou-se o
  **servidor** — arranca e persiste; nada se verificou sobre os clientes. É o
  teste em *staging* que D12 espera (`../tecnica/09` §20).
- **Que o Medusa 2.21.x seja testado em Node 24**, e não apenas permitido pelo
  `engines`. Lemos o manifesto publicado, não a matriz de CI do projecto. O
  **KAM-041** corre o Medusa a sério e responde por execução.
- **As imagens não são fixadas por digest** e não há SBOM nem assinatura: é o
  **KAM-067**, explicitamente fora de escopo.
- **Nada disto corre num pipeline.** Todas as verificações acima foram feitas à
  mão nesta sessão. Transformá-las em *gates* que falham um PR é o **KAM-002**.

### 7.3 Seis defeitos que só a execução encontrou

Ficam registados porque são conhecimento sobre as ferramentas, não sobre este
ticket, e porque mostram o que a leitura não apanha. Os três desta secção vieram
de correr a toolchain Node; os três da §7.4, de levantar a pilha de dados.

1. **`walk()` rebentava num repositório instalado.** O `Path.rglob` descia a
   `node_modules` antes de o filtro o rejeitar, e um `is_file()` sobre as
   ligações simbólicas que o `pnpm` cria em `node_modules/.pnpm` levanta
   `OSError: [WinError 1920]` em Windows. Resultado: `make lint-arch` saía com
   código 2 — erro de configuração — em qualquer máquina onde alguém tivesse
   corrido `pnpm install`. Ou seja, em todas, depois do primeiro `make bootstrap`.
   Passou a `os.walk` com poda dos directórios antes de descer: 0,5 s com
   `node_modules` presente, e imune a ligações que o sistema não consegue seguir.

2. **As duas verificações de versão do `make doctor` nunca tinham corrido.** As
   barras de continuação estavam **dentro** das aspas simples, pelo que a shell
   não as consumia e o interpretador recebia uma barra literal
   (`SyntaxError: Expected unicode escape`). Só se descobriu quando um contentor
   teve Node e Python ao mesmo tempo — antes, o `doctor` falhava no
   `command -v` e nunca chegava lá. Agora são de uma linha, e há um teste que
   recusa qualquer continuação dentro de aspas simples no `Makefile`.

3. **`${v}` num `Makefile` é expansão do make, não da shell.** Depois de
   corrigido o ponto 5, o `doctor` imprimia `node  ok` — sem versão: o make
   expandia `${v}` para vazio antes de a shell ver a linha. Precisa de `$${v}`.
   O mesmo vale para qualquer `${…}` dentro de uma receita.
### 7.4 Os três defeitos da pilha de dados

Os três que apareceram ao levantar o Postgres e a fila:

4. **PostgreSQL 18+ mudou o ponto de montagem.** As imagens oficiais passaram a
   guardar os dados num subdirectório por versão maior e **recusam arrancar** se
   encontrarem dados em `/var/lib/postgresql/data`
   (`docker-library/postgres#1259`). A convenção antiga — que está em quase todo
   o `docker-compose.yml` do mundo — deixa o contentor *unhealthy*. O compose
   monta em `/var/lib/postgresql`.
5. **`\connect :"POSTGRES_DB"` num script de `initdb` falha, e falha calado.**
   As variáveis de ambiente não são variáveis de `psql`. Pior: o script abortou,
   as extensões não foram criadas, e o contentor ficou **`healthy`** — um
   *fail-open* exactamente do tipo que o princípio 7 de `specs/01` §6 proíbe. O
   script já não usa `\connect` (o *entrypoint* liga-o à base certa) e tem uma
   asserção que falha o arranque se as versões não forem as esperadas.
6. **`ports:` num serviço ligado só a uma rede `internal` é decoração.** O
   Docker não publica a porta e não avisa. O compose tinha
   `127.0.0.1:5432:5432` no Postgres e a porta recusava conexões no *host*. As
   declarações mortas foram removidas e `make psql`/`make queue-cli` dão o
   acesso pelo contentor.

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.1 | Outubro 2026 | Lado Node verificado por execução em contentor: lockfile gerado e reprodutível (byte a byte), `typecheck` e testes verdes, `commitlint` confrontado com o `lint_arch` (0 divergências em 15 mensagens), os 5 serviços a responder `/healthz` na pilha, `make bootstrap && make check` em 52 s. §7.1 e §7.2 reescritas; três defeitos novos em §7.3. | Equipa KAMBÁ |
| 1.0 | Outubro 2026 | Emissão inicial no âmbito do KAM-001: `engines` do Medusa 2.21.2 confirmado; versões de Node, pnpm, Hono, TypeScript, `@types/node`, PostgreSQL, pgvector e fila registadas com fonte e estado; D12 mantida aberta; limites de execução declarados. | Equipa KAMBÁ |

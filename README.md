# KAMBÁ — monorepo

Plataforma WhatsApp-native de comércio conversacional para PMEs em Angola.

Este ficheiro é o arranque de **engenharia**. O produto, as decisões e o backlog
estão no conjunto documental: comece por [`specs/INDICE.md`](specs/INDICE.md).

> **Nada aqui está ratificado.** A Carta, o dicionário de dados e a classificação
> dos ADRs são propostas até o fundador as aprovar.

---

## Arrancar

Precisa de **Node 24 LTS**, **Python 3.12**, **Docker** e **make**.

```bash
make bootstrap   # instala tudo a partir dos lockfiles, constrói, liga os hooks
make check       # lint de arquitectura, locks, tipos e testes unitários
make up          # levanta a pilha local e sonda /healthz de cada serviço
```

`make help` lista o resto. `make doctor` diz se a sua máquina serve antes de
tentar instalar nada.

Os pacotes em `packages/` compilam para `dist/`; `make bootstrap` faz isso, e
quem mexer neles corre `make build`. O código dos serviços fica em TypeScript e
corre sem compilação — a assimetria tem uma razão de resolução de módulos, e está
em [`docs/adr/ADR-L001-toolchain.md`](docs/adr/ADR-L001-toolchain.md) §9.

**Em Windows:** corra estes comandos em **WSL** ou **Git Bash**. O `Makefile`
assume um shell POSIX e o `make` não existe no PowerShell.

Da última medição: **`make bootstrap && make check` em 52 s** a partir de clone
limpo (46 s + 6 s), contra um orçamento de 10 min. Os números e as condições
estão em [`docs/evidencia/KAM-001-node.md`](docs/evidencia/KAM-001-node.md) §7.1.

---

## O que está aqui

```
services/            os cinco serviços do Piloto (docs/tecnica/09 §3.1)
  gwy/               Node + Hono 4.13.x — único endpoint de webhook da Meta
  worker-canal/      Node — consumidor da fila de entrada
  agr/               Python 3.12 + Starlette — runtime de agentes
  com/               Node — anfitrião do registo de comércio (Medusa 2.21.x)
  onboarding-web/    Node — onboarding self-service
packages/
  contracts/         JSON Schema: fonte única de contratos para TS e Python
  core-ts/           núcleo TypeScript partilhado
                     (os dois compilam para dist/ — ver docs/adr/ADR-L001 §9)
libs/py-core/        núcleo Python partilhado
db/migrations/       reservado ao KAM-003 (schema platform, Alembic)
registry/            reservado ao AgentRegistry (registry/*.yaml, SemVer)
infra/compose/       pilha de desenvolvimento local
tools/               lint de arquitectura, lista de bloqueio, git hooks, locks
docs/                conjunto documental (ver docs/INDICE.md)
  tecnica/           desenho formal por subsistema + evidencia/E1–E5
  exploracao/        biblioteca exploratória 01–14 (histórica)
  analises/          análises adversariais
  adr/               ADRs locais (ADR-L###); os canónicos estão em docs/tecnica/00 §8
  evidencia/         evidência de execução por ticket
  spikes/            relatórios de spike, com o resultado de cada critério
spikes/              instrumentos de medição dos spikes — não é código de produção
  medusa-d3/         KAM-041: harness do spike do Medusa (decisão D3)
specs/               backlog executável (KAM-NNN) — na raiz, não é documentação
  tickets/           um ficheiro por ticket do EPIC-01 (43); os outros dez epics
                     mantêm os blocos no próprio ficheiro (KAM-155)
```

Cada serviço expõe **`/healthz`**, com a mesma carga útil em TypeScript e em
Python, validada contra
[`packages/contracts/schemas/healthz.response.v1.json`](packages/contracts/schemas/healthz.response.v1.json):

```json
{ "status": "ok", "service": "gwy", "version": "0.1.0", "commit": "a1b2c3d…" }
```

`commit` é `"unknown"` quando o serviço não corre a partir de uma imagem
construída pelo CI. A sonda continua a responder 200: uma sonda de vivacidade que
falha por falta de metadados derruba o serviço por nada.

---

## O que o repositório não deixa entrar

`make check` falha se um manifesto declarar uma dependência que um ADR canónico
proíbe. A lista está em [`tools/blocklist.yaml`](tools/blocklist.yaml), cada
entrada com o ADR e a evidência:

| Dependência | Porquê | ADR |
|---|---|---|
| `langgraph-api`, `langgraph-runtime-inmem` | Elastic-2.0, exigem chave de licença e *beacon* | ADR-002 |
| Dify | Apache-2.0 modificada: proíbe multi-tenant | ADR-002 |
| n8n | Sustainable Use License | ADR-002 |
| Typebot | FSL-1.1, «Competing Use» | ADR-002 |
| MinIO | Arquivado desde 2026-04-24 | ADR-014 |
| `litellm` < 1.83.0 | 1.82.7 e 1.82.8 foram maliciosas no PyPI | ADR-005 |

A verificação corre **antes** de qualquer instalação — primeiro passo do
`make bootstrap` — porque um linter de dependências que só corresse depois do
`pnpm install` chegaria tarde para o único caso que interessa.

### Dependências fixadas com *hash*

| Ecossistema | Como |
|---|---|
| Node | `pnpm-lock.yaml` + `pnpm install --frozen-lockfile --ignore-scripts`. O próprio pnpm está fixado com hash de integridade no campo `packageManager` |
| Python | `requirements/*.in` com o fecho completo → `requirements/*.txt` com `--hash=sha256:` por distribuição, instalado com `pip install --require-hashes --no-deps` |

`make lock` regenera os locks Python a partir dos `.in`. `make check` corre a
verificação **offline** (os `.txt` correspondem aos pins e cada um tem *hash*) e
`make lock-verify` reconfere os *hashes* e o fecho contra a PyPI — separadas de
propósito, para que um gate não falhe por falta de ligação.

Dois `make bootstrap` consecutivos produzem o mesmo `pnpm-lock.yaml` byte a byte
(`sha256:aeecf74f…`), o que é o teste de reprodutibilidade do lado Node.

---

## Convenções que as ferramentas impõem

| Convenção | Imposta por |
|---|---|
| `tipo(KAM-NNN): descrição no imperativo` | `commitlint` + hook `commit-msg` |
| `feature/KAM-NNN-<slug>` ou `fix/KAM-NNN-<slug>` | hook `pre-push` |
| Quarentena de ≥ 7 dias para versões novas | [`renovate.json5`](renovate.json5) |
| Revisão por dono de área | [`CODEOWNERS`](CODEOWNERS) |

Tipos aceites: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `spike`.
Tickets de tipo `chore` também usam ramos `feature/`: o prefixo diz o que o ramo
faz ao repositório, não o tipo do ticket.

As regras vivem num só ficheiro — [`tools/conventions.json`](tools/conventions.json)
— lido pelo `commitlint` (JS) e pelo `lint_arch` (Python), para que o hook não
possa aceitar o que o CI recusa.

`make bootstrap` liga os hooks (`git config core.hooksPath tools/githooks`). Se
clonou e não correu o bootstrap, os hooks não estão activos.

---

## Pilha de desenvolvimento local

| Serviço | Imagem | Acesso |
|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.7-pg18` (PostgreSQL **18.6**, pgvector 0.8.7, pg_trgm 1.6) | `make psql` |
| `queue` | `${KAMBA_QUEUE_IMAGE}`, por omissão `valkey/valkey:9.1.2-trixie`, com AOF | `make queue-cli` |
| `gwy` / `worker-canal` / `com` / `onboarding-web` | construídas localmente | `127.0.0.1:3000` / `3001` / `3002` / `3003` |
| `agr` | construída localmente | `127.0.0.1:8000` |

Duas coisas que o compose cumpre e que não são negociáveis: **nenhuma porta é
publicada fora de `127.0.0.1`**, e a rede `data` é `internal: true` — sem rota de
saída (`docs/tecnica/09` §3.2), verificado com um `ping` de dentro dessa rede.

Como consequência da rede ser interna, **o Postgres e a fila não publicam porta
nenhuma no *host*** — o Docker não o faz para um contentor ligado apenas a uma
rede `internal`, e nem avisa. Daí `make psql` e `make queue-cli`, que entram pelo
contentor. É mais restritivo do que publicar em `127.0.0.1` e cumpre o DoD com
folga.

Cada serviço tem um `healthcheck` que chama o seu próprio `/healthz`, pelo que
`make up` só devolve o controlo quando os serviços respondem — e não quando os
processos arrancam.

### A fila: decisão D12 em aberto

A licença do Redis (≥ 7.4 passou a RSAL/SSPL) e a alternativa Valkey são a
**decisão D12**, que está **ABERTA**. Nada no código nem no nome do serviço
depende da escolha: o serviço chama-se `queue` e trocar de implementação são duas
variáveis no `.env`:

```
KAMBA_QUEUE_IMAGE=redis:8.10.2-trixie
KAMBA_QUEUE_CLI=redis-cli
```

Isto foi verificado: o mesmo compose levantou Valkey 9.1.2 e Redis 8.10.2, ambos
com `appendonly yes`. **Mas exige volume limpo** — o AOF de um não é legível pelo
outro (`make nuke && make up`).

Que o BullMQ, o Chatwoot e o Medusa funcionem sobre Valkey é **NÃO VERIFICADO** —
verificou-se o servidor, não os clientes. É o teste em *staging* que D12 espera.

### Segredos

Nenhum segredo entra no repositório. `.env.example` só tem *placeholders*;
`make bootstrap` copia-o para `.env`, que está no `.gitignore`. Segredos a sério
(Meta, facilitador, provedores de LLM) vivem no gestor de segredos do **KAM-010**.

---

## O que este repositório ainda não faz

O KAM-001 entrega o esqueleto. Nenhum serviço tem comportamento: o GWY não
verifica assinaturas, o AGR não tem grafo, o COM não arranca o Medusa.

| O que falta | Ticket |
|---|---|
| Pipeline de CI com gates *fail-closed* | KAM-002 |
| Schema `platform` e migrações | KAM-003 |
| RLS `FORCE` e suite de isolamento | KAM-004 |
| Outbox transaccional e envelope de evento | KAM-005 |
| Gestão de segredos | KAM-010 |
| Webhook da Meta | KAM-013 |
| SBOM por imagem, assinatura cosign e `release.lock` (as imagens já vêm por *digest*: KAM-067, [`docs/supply-chain.md`](docs/supply-chain.md)) | KAM-078 |
| Ambientes e infraestrutura como código | KAM-075 |

---

## Onde ler o quê

| Pergunta | Documento |
|---|---|
| O que é o produto, e o que está decidido | [`specs/00_KAMBA_Carta.md`](specs/00_KAMBA_Carta.md) |
| Arquitectura, ADR-001…ADR-020, decisões abertas D1…D13 | [`docs/tecnica/00_Arquitectura_Solucao.md`](docs/tecnica/00_Arquitectura_Solucao.md) |
| Como se chama cada coisa | [`specs/02_Dicionario_de_Dados_Canonico.md`](specs/02_Dicionario_de_Dados_Canonico.md) |
| DoR, DoD, gates, convenções, template de PR | [`specs/01_Engineering_Standards_e_Handoff.md`](specs/01_Engineering_Standards_e_Handoff.md) |
| Backlog mestre (169 tickets) | [`specs/INDICE.md`](specs/INDICE.md) §4 |
| Topologia, operação, CI/CD | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](docs/tecnica/09_Topologia_Operacao_Escala.md) |
| Segurança, conformidade, cadeia de abastecimento | [`docs/tecnica/08_Seguranca_Conformidade.md`](docs/tecnica/08_Seguranca_Conformidade.md) |
| Licenças e versões verificadas | [`docs/tecnica/evidencia/E4_Stack_Licencas.md`](docs/tecnica/evidencia/E4_Stack_Licencas.md) |

A biblioteca exploratória em [`docs/exploracao/`](docs/exploracao/) (`01`–`14`) é
**histórica**: foi escrita antes da pesquisa e contém afirmações que a evidência
corrigiu. Não decida com ela.

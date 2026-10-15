# ADR-L001 — Toolchain do monorepo

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-10 |
| Ticket | KAM-001 — Monorepo, estrutura de serviços e toolchain |
| Âmbito | Local (ver [`README.md`](README.md)): escolhas de implementação da toolchain, não decisões de produto |
| Decisores | Arquitecto de Plataforma |
| ADRs canónicos aplicáveis | ADR-002 (LangGraph biblioteca), ADR-005 (LiteLLM ≥ 1.83.0 por digest), ADR-014 (MinIO excluído) |
| Substitui | — |

## Contexto

O KAM-001 pede «uma única ferramenta de orquestração de tarefas (`make` como
*facade*)» e manda registar num ADR local as escolhas de *task runner* de TS e de
Python. A decisão real é maior do que o *task runner*: o KAM-001 escolhe o
compilador, o executor de testes, a biblioteca web do AGR e a forma como as
dependências se fixam. Todas essas escolhas são herdadas por 126 tickets, e
algumas são caras de reverter.

Há um critério que atravessa todas elas, e vem de o KAM-001 ser o primeiro
ticket: **cada dependência que esta camada introduz é uma dependência que todos
os tickets seguintes pagam** — a fixar com *hash*, a actualizar sob quarentena, a
auditar por licença e a manter quando quebrar. Num esqueleto, a ferramenta que
não se instala é melhor do que a ferramenta ligeiramente mais conveniente.

## Decisões

### 1. `make` como fachada única de tarefas

**Decisão:** todas as tarefas passam por `make`. Nem `pnpm run` nem `tox` nem
`just` nem scripts soltos em `scripts/`.

`pnpm` e `pip` ficam gestores de dependências; não são executores de tarefas.
Quem chega ao repositório lê um ficheiro — o `Makefile` — para saber como se
constrói, verifica e levanta isto. O ponto não é o `make` ser bom; é haver um só
sítio onde olhar, e o `make` ser o que não acrescenta dependência nenhuma.

**Custo aceite:** o `make` não existe no PowerShell. Em Windows, os comandos
correm em WSL ou Git Bash, e o `make help` diz isso.

### 2. `node --test` em vez de Vitest ou Jest

**Decisão:** os testes de TypeScript correm no executor de testes do Node 24
(`node --test`), com `node:assert/strict`.

O Vitest estável é a versão `5.0.3` (`registry.npmjs.org/vitest/latest`, lido a 2026-10-10); o Jest arrasta uma árvore maior. O que os
dois dariam a mais — *watch* esperto, *mocking*, cobertura — não é o que falta a
um esqueleto cujo teste mais complexo verifica quatro campos de um JSON. O Node
24 corre TypeScript directamente, pelo que o código dos serviços não precisa de
compilação (os pacotes partilhados precisam, por uma razão de resolução de
módulos e não de testes — §9).

**Quando reverter:** quando houver teste que precise de *mocking* de módulos ou
de relatório de cobertura como gate (candidato natural: KAM-002, que define os
gates). Reverter custa um PR; o inverso — tirar o Vitest depois de 30 ficheiros
de teste o usarem — custa muito mais.

### 3. TypeScript 5.9.3, e não 7.0.2

**Decisão:** fixa-se `typescript@5.9.3`. O Renovate está configurado para não
propor `>= 7.0.0`.

O `latest` do registo é o `7.0.2` (lido a 2026-10-10). O TypeScript 7 é a
reescrita nativa do compilador: muda o executável, o desempenho e, em casos
conhecidos, o comportamento de configuração. Avaliar isso é trabalho real, e
pertence ao ticket que define os gates de tipos (KAM-002) — não a um ticket de
esqueleto que, por falta de Node na máquina de execução, **não conseguiu correr
`tsc` nenhum** para comparar os dois.

É esta a parte honesta da decisão: escolheu-se a versão madura porque a outra não
pôde ser testada. Isso está registado em
[`docs/evidencia/KAM-001-node.md`](../evidencia/KAM-001-node.md) §3 e §7.

### 4. Starlette no AGR, não FastAPI

**Decisão:** o AGR usa Starlette 1.7.0 + Uvicorn 0.54.0.

No KAM-001 o AGR expõe uma rota que devolve quatro campos constantes. O FastAPI
traria o Pydantic para validar um corpo de pedido que não existe, e o Pydantic é
uma dependência compilada a fixar com *hash* por plataforma.

**Quando reverter:** quando o AGR tiver uma API interna com corpo validado — o
`/internal/turn` do EPIC-03 é o candidato. O FastAPI é construído sobre o
Starlette, pelo que a migração é aditiva.

### 5. `unittest` da biblioteca padrão, não `pytest`

**Decisão:** os testes Python correm com `python -m unittest`.

Mesma lógica: o `pytest` é melhor do que o `unittest` em quase tudo, e nada disso
se nota num ticket cujos testes são asserções sobre dicionários e ficheiros.
Entra quando o AGR tiver testes a sério (EPIC-03), que é quando as *fixtures* e a
parametrização passam a pagar-se.

### 6. `lint_arch` depende apenas da biblioteca padrão

**Decisão:** `tools/lint_arch` não importa nada fora da biblioteca padrão do
Python, incluindo para ler YAML.

Esta é a decisão com mais consequência técnica das seis. A verificação da lista
de bloqueio tem de poder correr **antes** de qualquer `pnpm install` ou
`pip install`: um linter que precisasse de dependências instaladas para dizer que
uma dependência é proibida chegaria sempre tarde para o único caso que interessa
— o do pacote malicioso que corre no `postinstall` (`../tecnica/08` §4.8; E4 §2.7,
LiteLLM 1.82.7/1.82.8). Por isso `make bootstrap` corre `lint-arch` como primeiro
passo, antes de instalar.

**Custo aceite:** `tools/blocklist.yaml` é lido por
`tools/lint_arch/yamlmini.py`, um leitor de um subconjunto estrito de YAML, com
~100 linhas. Não é um parser de YAML e recusa, em voz alta, tudo o que não seja a
forma exacta que o ficheiro de bloqueio usa — sem âncoras, sem estilo de fluxo,
sem escalares de bloco, sem aninhamento. Isso é deliberado: um leitor que
aceitasse mais seria reutilizado como se fosse YAML a sério.

A alternativa — PyYAML com *hash* — foi rejeitada porque devolveria a verificação
para depois da instalação, que é o problema que se queria resolver.

### 7. Fecho de dependências Python explícito, verificado por máquina

**Decisão:** os pins vivem em `requirements/*.in` (incluindo os transitivos) e
`tools/pip_lock.py` gera o `.txt` com `--hash=sha256:` para cada distribuição.

`pip-tools`/`uv` fariam isto melhor, e são a escolha óbvia assim que houver uma
árvore de dependências a sério. Para treze pacotes, ~425 linhas de biblioteca
padrão evitam uma dependência na própria camada que existe para controlar
dependências —
e fazem uma coisa que importa: **verificam que o fecho está completo**, lendo o
`requires_dist` de cada pacote fixado e falhando se algo exigido não estiver
fixado.

`make check` corre `pip_lock.py --check`, que falha se o `.txt` estiver
dessincronizado do `.in`. É o teste de reprodutibilidade do lado do Python.

### 8. Nenhum ESLint

**Decisão:** não há *linter* de TypeScript no KAM-001. Há `tsc --noEmit` e
`.editorconfig`.

Os gates de lint são explicitamente o **KAM-002** («build, lint, tipos, unit,
secrets, SBOM, licenças»). Escolher e configurar o ESLint aqui seria tomar a
decisão do ticket seguinte, com menos informação do que ele vai ter.

### 9. Os pacotes partilhados emitem JavaScript; os serviços correm TypeScript

**Decisão:** `packages/contracts` e `packages/core-ts` são compilados por `tsc`
para `dist/` (JS + `.d.ts`). O código dentro de `services/*/src` fica em
TypeScript e corre sem compilação.

Isto parece inconsistente e não é. A documentação do Node é explícita:

> «Node.js refuses to handle TypeScript files inside folders under a
> `node_modules` path» — [nodejs.org/api/typescript.html](https://nodejs.org/api/typescript.html)

Os pacotes do *workspace* chegam ao serviço por `node_modules/@kamba/*` (o pnpm
cria lá uma ligação). Se fossem TypeScript, o Node recusar-se-ia a carregá-los — e
os serviços não arrancavam. O código do próprio serviço não passa por
`node_modules`, pelo que corre em `.ts` sem problema.

Consequências práticas, todas registadas porque são o tipo de coisa que alguém
«simplifica» e quebra:

| Onde | `tsconfig` | Emite? | Imports com `.ts`? |
|---|---|---|---|
| `packages/*` (fonte) | `tsconfig.json` | sim, para `dist/` | não (incompatível com emissão) |
| `packages/*` (testes) | `tsconfig.tests.json` | não | sim |
| `services/*` | `tsconfig.json` | não | sim |

`make bootstrap` corre `pnpm run build` depois do `install`, e os `Dockerfile`
dos serviços Node têm o mesmo passo. Quem mexer nos pacotes partilhados corre
`make build`.

A base activa **`erasableSyntaxOnly`**. O Node apaga tipos mas não transforma
código: `enum`, `namespace` com valores, propriedades de parâmetro e aliases de
*import* rebentam em execução com `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`. Com esta
opção, isso passa a ser um erro de tipos — que é onde se quer descobri-lo.

**Esta decisão não foi verificada em execução.** A máquina onde o KAM-001 correu
não tem Node, pelo que nem `tsc` nem `node --test` nem os `Dockerfile` dos
serviços Node correram. O que está acima é a leitura da documentação do Node,
que é fonte primária; o resto é desenho por verificar
([`docs/evidencia/KAM-001-node.md`](../evidencia/KAM-001-node.md) §7.2).

### 10. A correspondência de nomes é por fronteira, não por subcadeia

**Decisão:** as entradas curtas da lista de bloqueio (`dify`, `n8n`, `typebot`,
`minio`, `litellm`) usam `match: boundary` — o nome tem de aparecer delimitado
por algo que não seja letra nem dígito. Os nomes PyPI comparam-se normalizados
por PEP 503; as imagens comparam-se por **todos** os sufixos do caminho.

A primeira versão usava `substring`, e uma revisão adversarial mostrou que isso
tinha os dois defeitos ao mesmo tempo:

| Forma | `substring` | `boundary` + normalização |
|---|---|---|
| `langgraph_api==0.15.4` (PEP 503) | **passava** | bloqueia |
| `ghcr.io/berriai/litellm:main-v1.82.7` | **passava** | bloqueia |
| `"storage": "npm:minio@8.0.0"` | **passava** | bloqueia |
| `modify-values` (pacote real, família `conventional-changelog`) | **bloqueava** | passa |
| `minion`, `dominion`, `codify`, `solidify`, `nodify` (pacotes reais) | **bloqueavam** | passam |
| `n8n-nodes-base`, `langgenius/dify-api` | bloqueava | bloqueia |

Os falsos positivos não eram teóricos: `modify-values` é do mesmo ecossistema do
`@commitlint/*` que este repositório usa, e bastaria entrar como dependência
transitiva para deixar `make check` vermelho por um pacote que ninguém escolheu.
**Um gate que bloqueia o que ninguém escolheu é um gate que alguém acaba por
desligar** — e a seguir já não bloqueia nada.

Consequência que vale a pena nomear: para uma entrada com `forbidden_below`, uma
imagem tem de **trazer a versão na tag**, mesmo quando é fixada por digest
(`litellm:v1.104.2@sha256:…`). Resolver um digest para uma versão exigiria rede,
pelo que um digest sozinho não prova versão nenhuma — e, para um pacote que já
foi vector de ataque, «não provado» trata-se como «não permitido».

### 11. O `.dockerignore` é um controlo, não uma optimização

**Decisão:** `lint_arch structure` falha se o `.dockerignore` não excluir `.env`,
`.env.*`, `*.pem` e `*.key`, e os `Dockerfile` dos serviços usam `COPY`
selectivo em vez de `COPY . .`.

São duas barreiras para o mesmo defeito, de propósito. O `make bootstrap` cria
`.env` na raiz, a raiz é o contexto de *build*, e um `COPY . .` assava a senha do
Postgres do desenvolvedor numa camada de imagem — visível em `docker history`,
contra o DoD do KAM-001 («sem segredos»), `../tecnica/08` §5 e o critério de saída
do EPIC-01 («0 segredos em camadas de imagem»). Uma linha apagada num
`.dockerignore` não dá erro em nenhum sítio; a verificação de estrutura é esse
erro.

## Consequências

**Boas:**

- O `make bootstrap` instala **quatro** pacotes de desenvolvimento em Node
  (`typescript`, `@types/node`, `@commitlint/cli`, `@commitlint/config-conventional`)
  e **treze** em Python (sete de *runtime* do AGR, seis das ferramentas). A
  superfície a auditar, fixar e manter é pequena para um monorepo de cinco
  serviços. Os números exactos estão em `package.json` e nos dois
  `requirements/*.in` — é por eles que se decide, não por esta frase.
- A verificação da lista de bloqueio corre antes de qualquer instalação, que é a
  única ordem em que serve para algo.
- Nenhuma destas escolhas é difícil de reverter, e cada uma tem o gatilho de
  reversão escrito.

**Más, e assumidas:**

- `node --test` e `unittest` vão ser trocados quando o projecto crescer. Isso é
  uma migração de testes, que é trabalho chato.
- Há um passo de compilação, ao contrário do que a §2 desejava: os pacotes
  partilhados têm de emitir JavaScript por causa da restrição do Node (§9).
  Duas configurações de `tsc` por pacote partilhado são o preço.
- O `yamlmini.py` é código nosso a fazer o que uma biblioteca faz melhor. Fica
  justificado só enquanto o ficheiro de bloqueio for um formato de forma fixa.
- O TypeScript 5.9.3 fica atrás do `latest` por decisão, e vai aparecer em
  qualquer auditoria de dependências como desactualizado. A razão está escrita
  aqui e na regra do Renovate.
- Em Windows, nada disto corre no PowerShell.

## Alternativas rejeitadas

| Alternativa | Porque não |
|---|---|
| `just`, `task`, `nx`, `turbo` | Mais uma dependência na camada de orquestração. O `nx`/`turbo` pagam-se com dezenas de pacotes e grafos de build; aqui há seis |
| `pnpm run` como fachada | Deixaria as tarefas de Python fora da fachada, ou obrigaria o Node a invocar Python — e o `make bootstrap` tem de correr antes de o Node estar instalado |
| `uv` para Python | Provavelmente a escolha certa daqui a pouco. Hoje seria uma ferramenta nova na camada que existe para controlar o que é novo. Reavaliar no KAM-002 |
| PyYAML em `lint_arch` | Devolveria a verificação da lista de bloqueio para depois do `pip install`. Ver §6 |
| TypeScript 7.0.2 | Não pôde ser testado nesta execução. Ver §3 |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial (KAM-001). | Equipa KAMBÁ |

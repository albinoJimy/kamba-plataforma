# worker-canal — imagem multi-stage (KAM-001).
#
# O que esta imagem ja faz: instala a partir do lockfile com `--frozen-lockfile`,
# nao corre scripts de instalacao de terceiros (`--ignore-scripts`), e corre como
# utilizador sem privilegios (`docs/tecnica/09` §3.2, `docs/tecnica/08` §4.8).
#
# A base vem por digest (KAM-067), registado em `ci/supply-chain/imagens.yaml`
# com a data e a fonte de onde se leu. O que esta imagem NAO faz: nao gera SBOM
# por imagem e nao e assinada — nao ha ainda pipeline que a construa e publique
# (KAM-078).
#
# Tres escolhas que valem explicacao:
#
# 1. **`COPY` selectivo, nunca `COPY . .`.** O contexto e a raiz do monorepo e
#    contem o `.env` que o `make bootstrap` cria. Um `COPY . .` assava a senha do
#    Postgres do desenvolvedor numa camada da imagem, visivel em
#    `docker history` — contra o DoD do KAM-001 ("sem segredos") e `docs/tecnica/08`
#    §5. O `.dockerignore` tambem o exclui; sao duas barreiras para o mesmo
#    defeito, de proposito, porque uma linha apagada num `.dockerignore` nao da
#    erro em nenhum sitio.
#
# 2. **Compila-se `packages/`, nao os servicos.** O Node 24 corre TypeScript
#    directamente, mas **recusa apagar tipos em ficheiros sob `node_modules`**
#    ("Node.js refuses to handle TypeScript files inside folders under a
#    node_modules path", nodejs.org/api/typescript.html). Os pacotes do workspace
#    chegam ao servico por `node_modules/@kamba/*`, pelo que teriam de ser
#    JavaScript — e e por isso que `packages/*` emitem para `dist/`. O codigo do
#    proprio servico fica em `.ts` e corre sem compilacao.
#
# 3. **Nao se poda o `node_modules`.** `pnpm prune --prod` ou `pnpm deploy`
#    reduziriam a imagem, mas dependem de detalhes de layout que este ticket nao
#    tem como testar (a maquina de execucao nao tem Node). Imagem maior e certa
#    vale mais do que menor e nao verificada; a imagem magra fica para o KAM-002,
#    que e quem a vai construir e medir.
ARG NODE_IMAGE=node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
# `corepack enable` passa a resolver o pnpm pelo campo `packageManager` do
# package.json, que inclui o hash de integridade da versao exacta.
RUN corepack enable

# Manifestos primeiro: a camada de instalacao so se invalida quando mudarem.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY packages/contracts/package.json packages/contracts/
COPY packages/core-ts/package.json packages/core-ts/
COPY services/worker-canal/package.json services/worker-canal/
RUN pnpm install --frozen-lockfile --ignore-scripts

# Fonte, e so a fonte dos pacotes que este servico usa.
COPY tsconfig.base.json ./
COPY packages/contracts packages/contracts
COPY packages/core-ts packages/core-ts
COPY services/worker-canal services/worker-canal
RUN pnpm run build

FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ARG KAMBA_COMMIT_SHA=unknown
# HOST=0.0.0.0 e definido aqui, e nunca no codigo: dentro do contentor e preciso
# escutar na interface da rede do compose, mas correr o servico a mao na maquina
# de alguem continua a escutar so em 127.0.0.1 (DoD do KAM-001).
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3001 \
    KAMBA_COMMIT_SHA=${KAMBA_COMMIT_SHA}
COPY --from=deps /app ./
USER node
EXPOSE 3001
CMD ["node", "services/worker-canal/src/server.ts"]

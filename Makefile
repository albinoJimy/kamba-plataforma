# Makefile da KAMBÁ — fachada unica de orquestracao de tarefas (KAM-001).
#
# Uma so ferramenta para correr tarefas, por decisao registada em
# docs/adr/ADR-L001-toolchain.md. `pnpm` e `pip` sao gestores de dependencias,
# nao executores de tarefas: quem precisa de saber como se constroi isto le este
# ficheiro e mais nenhum.
#
# Os tres comandos que importam:
#   make bootstrap   prepara um clone limpo (instala tudo a partir dos lockfiles)
#   make check       verifica tudo o que se verifica sem levantar a pilha
#   make up          levanta a pilha de desenvolvimento
#
# `make help` lista o resto.
#
# Ordem deliberada no bootstrap: a lista de bloqueio corre **antes** de qualquer
# instalacao. Um linter de dependencias que so corresse depois do `pnpm install`
# chegaria sempre tarde para o unico caso que interessa (`docs/tecnica/08` §4.8).

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
COMPOSE_FILE := infra/compose/docker-compose.dev.yml
# `--env-file .env` e obrigatorio e nao opcional: sem ele, o docker compose
# procura o `.env` ao lado do ficheiro de compose (`infra/compose/.env`) e nao na
# raiz, onde o `make bootstrap` o cria. O caminho do `--env-file` e relativo ao
# directorio de trabalho, que aqui e sempre a raiz do repositorio.
COMPOSE := docker compose --env-file .env -f $(COMPOSE_FILE)

VENV := .venv
# `python -m venv` cria `Scripts/python.exe` em Windows e `bin/python` no resto.
# Fixar `bin` deixava `make bootstrap` a morrer no Git Bash — que e um dos dois
# caminhos que o README manda usar em Windows, e o que nao exige instalar uma
# distribuicao Linux.
ifeq ($(OS),Windows_NT)
VENV_BIN := $(VENV)/Scripts
VENV_PYTHON := $(VENV_BIN)/python.exe
PYTHON ?= python
else
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
PYTHON ?= python3
endif

PY_LOCKS := services/agr/requirements/runtime.in tools/requirements/tools.in db/requirements/migrations.in
# As suites de `tools/` descobrem-se pelo disco: toda a `tools/<nome>/tests`.
# Eram duas listas escritas a mao (`test-py` e `coverage-python`), e uma suite
# nova que ficasse fora delas nao era corrida por ninguem — aconteceu com a
# `secrets_inventory` no KAM-010. Eram tambem o sitio onde dois tickets em
# paralelo colidiam sempre. Uma lista vazia e erro, nao e «nada para correr».
#
# Conta como suite o directorio `tools/<nome>/tests` que tenha pelo menos um
# `test_*.py` — nao um `tests/` vazio nem o `__pycache__` que uma troca de ramo
# deixa para tras. O caminho parte de $(ROOT), para a descoberta nao depender
# do directorio de onde se chama o `make`; e a lista vazia verifica-se nas
# receitas que a usam (`exige-suites`), nao a cabeca, para nao matar `make help`.
# O conjunto minimo esperado esta preso em `tools/lint_arch/tests/test_makefile.py`:
# uma suite que desapareca do disco falha la, em vez de deixar de correr calada.
SUITES_DE_TOOLS := $(sort $(patsubst $(ROOT)/tools/%/tests/,%,$(dir $(wildcard $(ROOT)/tools/*/tests/test_*.py))))

exige-suites:
	@test -n "$(strip $(SUITES_DE_TOOLS))" || { \
	  echo "nenhuma suite encontrada em $(ROOT)/tools/*/tests/test_*.py" >&2; exit 1; }
	@echo "    suites de tools/ ($(words $(SUITES_DE_TOOLS))): $(SUITES_DE_TOOLS)"

PYTHONPATH_ALL := $(ROOT)/tools:$(ROOT)/libs/py-core/src:$(ROOT)/services/agr/src

# Servicos e portas, para a sonda. Tem de coincidir com o compose.
HEALTHZ_TARGETS := gwy=3000 worker-canal=3001 com=3002 onboarding-web=3003 agr=8000

# Pacotes Node com testes, para a medicao de cobertura por pacote. Enumerados e
# nao descobertos: um pacote novo tem de entrar aqui **e** em ci/thresholds.yaml,
# e e melhor que isso seja uma alteracao visivel do que uma deteccao silenciosa.
PACOTES_NODE := packages/contracts packages/core-ts services/gwy \
                services/worker-canal services/com services/onboarding-web

export PYTHONPATH := $(PYTHONPATH_ALL)

.PHONY: bootstrap build check ci ci-1 ci-11 ci-2 exige-pnpm exige-suites \
        ci-3 ci-4 ci-5 ci-6 ci-7 ci-8 ci-9 \
        ci-waivers clean coverage-node coverage-python doctor down help \
        hooks lint-arch lint-branch lock lock-check lock-verify logs \
        nuke ps psql queue-cli smoke test test-py \
        test-ts typecheck up \
        ci-3b canon-lint dict-export \
        supply-chain ruleset \
        log-lint x11 storage-contrato mermaid

## help: lista os comandos disponiveis
help:
	@echo "KAMBÁ — comandos disponiveis:"
	@echo
	@grep -E '^## [a-z-]+:' $(MAKEFILE_LIST) \
	  | sed -e 's/^## //' -e 's/:/\t/' \
	  | awk -F'\t' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Em Windows, corra estes comandos em WSL ou Git Bash: o Makefile"
	@echo "assume um shell POSIX e o 'make' nao existe no PowerShell."

# -----------------------------------------------------------------------------
# Bootstrap
# -----------------------------------------------------------------------------

## doctor: verifica que a toolchain da maquina serve
doctor:
	@echo "==> toolchain"
	@command -v node     >/dev/null || { echo "FALTA node 24 LTS (ver .node-version)"; exit 1; }
	@command -v corepack >/dev/null || { echo "FALTA corepack (vem com o Node 24)"; exit 1; }
	@command -v $(PYTHON) >/dev/null || { echo "FALTA $(PYTHON) (>= 3.12)"; exit 1; }
	@# As verificacoes de versao sao de UMA linha, de proposito. Com a forma
	@# multi-linha, as barras de continuacao ficam DENTRO das aspas simples: a
	@# shell nao as consome, e o interpretador recebe uma barra literal e morre
	@# com "Expected unicode escape". Estiveram assim e nunca correram.
	@# `$$` e obrigatorio: num Makefile, `${v}` e expansao de variavel do make e
	@# chegava ao node ja vazio — o `doctor` imprimia "node  ok" sem versao nenhuma.
	@node -e 'const v = process.versions.node; if (!v.startsWith("24.")) { console.error(`Node $${v} nao serve: $${require("./package.json").engines.node} (ver .node-version e docs/evidencia/KAM-001-node.md)`); process.exit(1); } console.log(`    node $${v} ok`);'
	@# Minimo 3.12, nao exactamente 3.12. O AGR **corre** em 3.12 (imagem
	@# `python:3.12-slim`, docs/tecnica/09 §3.1), mas o que o `make check` pede a
	@# maquina e correr `lint_arch`, `pip_lock` e os testes, e isso funciona em
	@# 3.12 ou acima. Exigir a minor exacta rejeitaria quem ja tenha 3.13.
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python %d.%d nao serve: minimo 3.12 (docs/tecnica/09 3.1)" % sys.version_info[:2])'
	@echo "    $$($(PYTHON) --version) ok"
	@# O docker e preciso para `make up`, nao para instalar dependencias.
	@# Avisa-se e segue-se: um runner que so constroi e testa nao tem de o ter,
	@# e o CA do ticket pede `make bootstrap && make check` verdes, nao `make up`.
	@if command -v docker >/dev/null 2>&1; then echo "    $$(docker --version | cut -d, -f1) ok"; else echo "    AVISO: sem docker - 'make up' nao vai funcionar nesta maquina"; fi

## bootstrap: prepara um clone limpo, so a partir dos lockfiles
bootstrap: doctor lint-arch hooks $(VENV)/.stamp
	@echo "==> .env"
	@if [ ! -f .env ]; then cp .env.example .env; echo "    .env criado a partir de .env.example"; \
	 else echo "    .env ja existe, mantido"; fi
	@echo "==> dependencias Node (lockfile, sem scripts de instalacao)"
	@corepack enable
	@pnpm install --frozen-lockfile --ignore-scripts
	@echo "==> construcao dos pacotes partilhados"
	@# `packages/contracts` e `packages/core-ts` emitem JavaScript para `dist/`.
	@# Nao e preferencia de estilo: o Node recusa apagar tipos em ficheiros sob
	@# `node_modules`, e e por la que os pacotes do workspace chegam aos
	@# servicos (ver docs/adr/ADR-L001-toolchain.md §9).
	@pnpm run build
	@echo
	@echo "Pronto. Agora: make check   (e depois: make up)"

# O venv depende dos locks: mexer num lock reinstala, e so isso.
$(VENV)/.stamp: services/agr/requirements/runtime.txt tools/requirements/tools.txt db/requirements/migrations.txt
	@echo "==> ambiente Python (--require-hashes)"
	@$(PYTHON) -m venv $(VENV)
	@# Sem `pip install --upgrade pip`: esteve aqui, e era a unica instalacao
	@# do repositorio que ia ao PyPI sem hash — a actualizar precisamente a
	@# ferramenta que impoe os hashes. O `pip` que o `venv` traz chega para
	@# `--require-hashes` (KAM-067; `make supply-chain` falha se a linha voltar).
	@$(VENV_PYTHON) -m pip install --quiet --require-hashes --no-deps \
	  -r tools/requirements/tools.txt \
	  -r db/requirements/migrations.txt
	@$(VENV_PYTHON) -m pip install --quiet --require-hashes --no-deps \
	  -r services/agr/requirements/runtime.txt
	@touch $@

## hooks: aponta o git para tools/githooks
hooks:
	@git config core.hooksPath tools/githooks
	@chmod +x tools/githooks/* 2>/dev/null || true
	@echo "==> git hooks: core.hooksPath = tools/githooks"

# -----------------------------------------------------------------------------
# Verificacao
# -----------------------------------------------------------------------------

## check: tudo o que se verifica sem levantar a pilha
check: lint-arch lint-branch lock-check test-py typecheck test-ts
	@echo
	@echo "make check: verde."

## lint-arch: lista de bloqueio e estrutura da arvore
lint-arch:
	@echo "==> lint_arch"
	@$(PYTHON) -m lint_arch --root $(ROOT) all

## lint-branch: nome do ramo actual
lint-branch:
	@echo "==> nome do ramo"
	@$(PYTHON) -m lint_arch --root $(ROOT) branch

## lock-check: os locks Python correspondem aos pins (sem rede)
lock-check:
	@echo "==> locks Python (sem drift, offline)"
	@# Deliberadamente offline. O CA do ticket diz "a partir de um clone limpo
	@# termina verde em <= 10 min **usando apenas lockfiles**"; um gate que vai a
	@# PyPI por cada pin falha por ligacao e nao por codigo — o que, para uma
	@# equipa em Luanda e para um runner sem egresso, e o pior tipo de gate.
	@$(PYTHON) tools/pip_lock.py --check-offline $(PY_LOCKS)

## lock-verify: reconfere os hashes e o fecho contra a PyPI (precisa de rede)
lock-verify:
	@echo "==> locks Python (fecho e hashes, contra a PyPI)"
	@$(PYTHON) tools/pip_lock.py --check $(PY_LOCKS)

## lock: regenera os locks Python com hashes a partir dos .in
lock:
	@$(PYTHON) tools/pip_lock.py $(PY_LOCKS)
	@echo "Locks Python regenerados. Para o Node: pnpm install --lockfile-only"

## exige-pnpm: diz o que fazer quando o pnpm nao esta no PATH
exige-pnpm:
	@# O `pnpm` vem do Corepack, que o `make bootstrap` activa. Sem bootstrap, os
	@# alvos que o usam morriam com `pnpm: command not found` e codigo 127 — uma
	@# mensagem que nao diz o que fazer, num ficheiro que em todos os outros
	@# sitios diz. Apanhado a correr `make check` num contentor limpo, nao a ler.
	@command -v pnpm >/dev/null 2>&1 || { \
	  echo "    ERRO: pnpm nao esta no PATH." >&2; \
	  echo "    Vem do Corepack, que o bootstrap activa. Corra 'make bootstrap'." >&2; \
	  exit 1; }

## build: compila os pacotes partilhados (packages/*) para dist/
build: exige-pnpm
	@echo "==> pacotes partilhados"
	@pnpm run build

## test: testes unitarios de Python e de TypeScript
test: test-py test-ts

## test-py: testes unitarios Python
test-py: exige-suites
	@echo "==> testes Python"
	@# lint_arch e py-core nao tem dependencias: correm com qualquer Python 3.12.
	@# As quatro suites de `tools/`, e nao so a do `lint_arch`.
	@#
	@# As tres novas do KAM-002 (`lint_refs`, `scan_secrets`, `sbom`) nao eram
	@# corridas por nenhum alvo que pudesse falhar: so por `coverage-python`,
	@# que engolia o resultado. Uma suite que nada corre nao protege nada.
	@for suite in $(SUITES_DE_TOOLS); do \
	  echo "    $$suite"; \
	  $(PYTHON) -m unittest discover -s "tools/$$suite/tests" -t tools || exit 1; \
	done
	@$(PYTHON) -m unittest discover -s libs/py-core/tests -t libs/py-core/tests
	@# O AGR importa Starlette, que vive no venv. Sem venv, dizer o que fazer e
	@# melhor do que cair no python do sistema e devolver um ImportError opaco.
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "    ERRO: $(VENV) nao existe. Corra 'make bootstrap' antes de 'make check'." >&2; \
	  exit 1; \
	fi
	@$(VENV_PYTHON) -m unittest discover -s services/agr/tests -t services/agr/tests

## test-ts: testes unitarios TypeScript (node --test)
test-ts: exige-pnpm
	@echo "==> testes TypeScript"
	@# Os testes importam a fonte `.ts` directamente; os pacotes partilhados
	@# precisam de estar construidos, o que `make bootstrap` garante.
	@pnpm -r run test

## typecheck: verificacao de tipos em todos os pacotes
typecheck: exige-pnpm
	@echo "==> tipos"
	@pnpm -r run typecheck

# -----------------------------------------------------------------------------
# Pilha de desenvolvimento
# -----------------------------------------------------------------------------

## up: levanta a pilha de desenvolvimento e espera pelas sondas
up:
	@command -v docker >/dev/null 2>&1 || { echo "FALTA docker: 'make up' levanta contentores."; exit 1; }
	@if [ ! -f .env ]; then echo "Sem .env. Corra 'make bootstrap' primeiro."; exit 1; fi
	@KAMBA_COMMIT_SHA="$$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
	  $(COMPOSE) up --build --detach --wait
	@$(MAKE) smoke

## down: para a pilha (mantem os volumes)
down:
	@$(COMPOSE) down

## ps: estado dos contentores
ps:
	@$(COMPOSE) ps

## logs: segue os logs da pilha
logs:
	@$(COMPOSE) logs --follow --tail=100

## smoke: curl /healthz de cada servico, validado contra o contrato
smoke:
	@echo "==> /healthz de cada servico"
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "    ERRO: $(VENV) nao existe. Corra 'make bootstrap' (instala jsonschema)." >&2; \
	  exit 1; \
	fi
	@$(VENV_PYTHON) tools/healthz_check.py --retries 8 --delay 1.5 $(HEALTHZ_TARGETS)

## psql: abre um psql na base da plataforma (a rede `data` e interna)
psql:
	@$(COMPOSE) exec postgres psql -U "$${POSTGRES_USER:-kamba}" -d "$${POSTGRES_DB:-kamba_platform}"

## queue-cli: abre o cliente da fila (valkey-cli ou redis-cli, conforme D12)
queue-cli:
	@$(COMPOSE) exec queue "$${KAMBA_QUEUE_CLI:-valkey-cli}"

## storage-contrato: contrato do StorageProvider contra um SeaweedFS descartavel (KAM-011)
storage-contrato:
	@# Nao e um gate: o ticket nao pede um, e o gate 5 continua reservado. A
	@# mesma bateria corre no gate 4 sobre o fake e sobre um S3 em memoria; este
	@# alvo corre-a contra um servidor real, fixado por digest, e apaga-o no fim.
	@$(PYTHON) infra/storage/contrato.py

# =============================================================================
# Gates de CI (KAM-002)
# =============================================================================
#
# Cada gate e um alvo `ci-<n>`. O workflow do GitHub Actions **so os orquestra**:
# nenhuma logica fica presa a plataforma de CI, e qualquer gate corre a mao,
# localmente, com o mesmo comando que o pipeline usa.
#
# A numeracao e a do §4 do Engineering Standards, e nao se renumera: o gate 11 e
# o gate 11 em toda a documentacao, nos waivers e nos tickets a jusante.
#
# Activos: 1, 2, 3, 4, 9, 11 (KAM-002), 8 (KAM-003) e 6 (KAM-004).
# Reservados e fail-closed: 5, 7 — falham ate o ticket que os implementa
# os ligar. Ver `ci-5` para a razao.
# Fora de ambito: 10 (SAST), 12-18 (KAM-067, KAM-078, KAM-088).

## ci: corre todos os gates activos (KAM-002 e o gate 8 do KAM-003)
ci: ci-1 ci-2 ci-3 ci-3b ci-4 ci-6 ci-7 ci-8 ci-9 ci-11 ci-waivers
	@echo
	@echo "ci: todos os gates activos estao verdes (1, 2, 3, 3b, 4, 6, 7, 8, 9, 11)."

## ci-waivers: valida ci/waivers.yaml (prazo, referencia, alcance)
ci-waivers:
	@echo "==> waivers"
	@$(PYTHON) tools/ci_waivers.py --root $(ROOT)

## ci-1: gate 1 — build a partir dos lockfiles
ci-1: doctor
	@echo "==> gate 1: build"
	@# `--frozen-lockfile` e `--ignore-scripts` sao a razao de ser do gate: o build
	@# tem de vir do lockfile e nao executar codigo de terceiros na instalacao.
	@corepack enable
	@pnpm install --frozen-lockfile --ignore-scripts
	@pnpm run build
	@$(MAKE) lock-check

## ci-2: gate 2 — lint, formato e tipos
ci-2:
	@echo "==> gate 2: tipos"
	@pnpm -r run typecheck
	@$(MAKE) lint-arch
	@$(MAKE) log-lint
	@# Nao ha linter de estilo: os gates de lint sao deste ticket, mas a escolha do
	@# ESLint ficou declarada fora de ambito no KAM-001 (ADR-L001 §8) e nao se
	@# decide aqui por conveniencia. `make ci-2` cobre tipos e arquitectura.

# --- Logs sem conteudo (KAM-068) ----------------------------------------------
#
# Dois alvos, e cada um entra num gate que ja existia em vez de abrir um job:
#
#   log-lint  no gate 2. Nenhum servico escreve fora do logger (`console.*`,
#             `print`, `logging`, stdout). O segundo passo e o canario: as
#             fixtures negativas TEM de falhar, cada uma pela sua regra.
#   x11       no gate 6. E o X-11 da suite cruzada de `docs/tecnica/08` §3.7 e
#             §14: 1 000 chamadas com telefones, NIF, e-mails, texto, tokens,
#             IBAN e referencias passam pelos dois loggers; a saida de Python e
#             a de TypeScript tem de ser IGUAL byte a byte e nao ter achado
#             nenhum. O varrimento prova primeiro que ve os identificadores na
#             entrada (controlo positivo) — sem isso, o zero nao dizia nada.
#
# O padrao do NIF e um parametro (`make x11 X11_NIF='<regex>'`): nenhum
# documento o define, e o ticket manda nao o inventar. Sem ele, o varrimento
# diz em voz alta que o NIF nao e medido por padrao proprio.
#
# So biblioteca padrao do lado Python; do lado Node, o `node` que o gate ja tem.

X11_NIF ?=
X11_DIR := ci/x11

## log-lint: nenhum servico escreve fora do logger (KAM-068)
log-lint:
	@echo "==> log_policy: nenhum servico escreve fora do logger"
	@$(PYTHON) -m log_policy --root $(ROOT) lint
	@$(PYTHON) -m log_policy --root $(ROOT) canario

## x11: X-11 — 1 030 fixtures com dados pessoais pelos dois loggers, 0 achados
x11:
	@echo "==> X-11: logs sem identificadores (1 000 fixtures de canarios e 30 de forma, Python e TypeScript)"
	@command -v node >/dev/null 2>&1 || { echo "    ERRO: o X-11 precisa do node para o logger em TypeScript." >&2; exit 1; }
	@rm -rf $(X11_DIR) && mkdir -p $(X11_DIR)
	@$(PYTHON) -m log_policy fixtures --saida $(X11_DIR)/fixtures.json
	@$(PYTHON) -m log_policy conduzir $(X11_DIR)/fixtures.json --saida $(X11_DIR)/py.log --contadores $(X11_DIR)/py.contadores.json --ponte $(X11_DIR)/py.ponte.log
	@node packages/core-ts/tests/x11_conduzir.ts $(X11_DIR)/fixtures.json $(X11_DIR)/ts.log $(X11_DIR)/ts.contadores.json
	@$(PYTHON) -m log_policy iguais $(X11_DIR)/py.log $(X11_DIR)/ts.log
	@$(PYTHON) -m log_policy iguais $(X11_DIR)/py.contadores.json $(X11_DIR)/ts.contadores.json
	@$(PYTHON) -m log_policy x11 --fixtures $(X11_DIR)/fixtures.json --linhas-esperadas 1030 $(if $(X11_NIF),--nif-padrao '$(X11_NIF)') $(X11_DIR)/py.log $(X11_DIR)/ts.log
	@$(PYTHON) -m log_policy x11 --fixtures $(X11_DIR)/fixtures.json $(if $(X11_NIF),--nif-padrao '$(X11_NIF)') $(X11_DIR)/py.ponte.log

## ci-3: gate 3 — referencias cruzadas, caminhos de handoff e contagens
#
# Tres passos, e cada um le uma coisa diferente do mesmo conjunto:
#
#  1. `lint_refs` le **identificadores** (KAM, ADR, D#) em todo o conjunto.
#  2. `lint_handoff` le **caminhos**, e so dentro dos blocos
#     `### Handoff para Claude Code`, onde a regra e outra: o executor corre
#     na raiz do repositorio, pelo que ali os caminhos sao relativos a raiz
#     (specs/01_Engineering_Standards_e_Handoff.md §5, KAM-145). Fora desses
#     blocos vale a convencao do KAM-128 e o `lint_handoff` nao a le.
#  3. `lint_contagens` le **contagens em prosa** («N tickets», «N ADRs»,
#     «N epics») e confronta cada uma com a fonte que a conta (KAM-158).
#     Nao le zonas de historia — uma linha de «Controlo de versoes» e uma
#     seccao de verificacao registam o que era verdade **entao**.
#
# Entra aqui, e nao como gate novo, de proposito: um gate novo acrescentaria
# um contexto exigido ao ruleset de `main` — alteracao de regra de bloqueio,
# que nao e deste ticket. Assim a convencao passa a ser verificada por
# maquina sem mexer nos sete contextos.
ci-3:
	@echo "==> gate 3: referencias cruzadas"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from lint_refs.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from lint_handoff.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from lint_contagens.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"

# --- Gate 3b: nomes canonicos (KAM-111) --------------------------------------
#
# Tres passos, e os tres contam:
#
#   1. `canon/dicionario.yaml` corresponde ao §3 do dicionario. A fonte da
#      verdade e o Markdown; um YAML editado a mao, ou um Markdown alterado sem
#      regenerar, falha aqui.
#   2. As quatro superficies (migracoes, schemas de evento, registo e
#      `docs/tecnica/`) so usam nomes do dicionario ou de `canon/extensoes.yaml`.
#   3. O canario: as fixtures negativas TEM de falhar com a mensagem esperada e
#      as positivas tem de passar. Sem este passo, a prova de que o lint morde
#      vivia so num `unittest` — e as superficies `eventos` e `registo` estao
#      hoje vazias, pelo que o passo 2 passa nelas sem ter lido nada.
#
# So biblioteca padrao: corre antes de qualquer instalacao, como o gate 3.

## ci-3b: gate 3b — nomes canonicos (dicionario §3; KAM-111)
ci-3b:
	@echo "==> gate 3b: nomes canonicos"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from dict_export.cli import main; sys.exit(main(['--root', '$(ROOT)', '--check']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from canon_lint.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from canon_lint.cli import main; sys.exit(main(['--root', '$(ROOT)', 'canario']))"

## mermaid: passa os diagramas Mermaid do conjunto por um parser (KAM-140)
#
# Nao e gate: nao ha *job* que o corra, e isso esta registado em docs/ci.md §7.
# Corre `mermaid.parse` a serio — nao uma heuristica sobre o texto. A regra do
# conjunto e que «escreve-los sem acentos nos IDs nao prova que compilam», e
# ate ao KAM-140 o unico parse alguma vez feito foi a mao, num navegador.
#
# Precisa de Docker e de rede na primeira execucao. O `mermaid` **nao** e
# dependencia do repositorio de proposito: traz uma arvore grande de terceiros
# que iria para o SBOM e para o veredicto de licencas do gate 11, para uma
# ferramenta que nao vai para producao. Corre num contentor descartavel, com a
# imagem do `.node-version` fixada por digest — o padrao que o
# `db/tests_eventos/node.py` ja usa, e pela mesma razao: nao ha Node no *host*.
mermaid:
	@echo "==> diagramas Mermaid"
	@command -v docker >/dev/null 2>&1 || { echo "    ERRO: este alvo precisa de Docker." >&2; exit 2; }
	@# Tudo numa so receita, e o intermedio num temporario e nao em `ci/`: numa
	@# versao anterior, uma cerca por fechar fazia a extraccao sair com 2 e o
	@# `rm` da linha seguinte nunca corria — ficava lixo por versionar dentro do
	@# repositorio. O `trap` so vale dentro da shell que o declara, pelo que as
	@# duas metades tem de partilhar a mesma.
	@#
	@# E o `verificar.mjs` e copiado para junto do `node_modules`: o `NODE_PATH`
	@# **nao** vale para `import` de ESM, e correr o ficheiro de `/lint` deixa a
	@# resolucao a subir uma arvore que nao tem os pacotes (`ERR_MODULE_NOT_FOUND`).
	@blocos="$$(mktemp)"; trap 'rm -f "$$blocos"' EXIT INT TERM; \
	 $(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from mermaid_lint.extrair import main; sys.exit(main(['--root', '$(ROOT)']))" > "$$blocos" && \
	 docker run --rm -i -v "$(ROOT)/tools/mermaid_lint:/lint:ro" node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66 sh -c 'cp -r /lint /tmp/m && cd /tmp/m && npm ci --silent --no-audit --no-fund --ignore-scripts >/dev/null 2>&1 && node /tmp/m/verificar.mjs' < "$$blocos"

## canon-lint: o gate 3b pelo nome que o ticket lhe da (igual a ci-3b)
canon-lint: ci-3b

## dict-export: regenera canon/dicionario.yaml a partir do dicionario (§3)
dict-export:
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from dict_export.cli import main; sys.exit(main(['--root', '$(ROOT)']))"

## ci-4: gate 4 — testes unitarios e cobertura
ci-4: coverage-node coverage-python
	@echo "==> gate 4: cobertura contra ci/thresholds.yaml"
	@if [ -x "$(VENV_PYTHON)" ]; then PY="$(VENV_PYTHON)"; else PY="$(PYTHON)"; fi; \
	  "$$PY" tools/coverage_gate.py --root $(ROOT)

## coverage-node: mede cobertura dos pacotes e servicos Node (LCOV)
coverage-node:
	@echo "==> cobertura Node"
	@mkdir -p ci/coverage
	@# Um relatorio **por pacote**, com o caminho do pacote no nome do ficheiro.
	@#
	@# Nao se usa `pnpm -r exec` com um nome derivado de `$$PWD`: o `basename`
	@# resolvia para o directorio de quem invocou o make, pelo que os seis
	@# pacotes escreviam no **mesmo** ficheiro e sobreviviam-se uns aos outros.
	@# Ficava um LCOV com tres linhas.
	@#
	@# O caminho no nome tambem resolve o segundo problema: o Node emite caminhos
	@# `SF:` **relativos** ao pacote (`src/app.ts`), e sem saber a que pacote
	@# pertencem nao ha como os classificar contra ci/thresholds.yaml. O
	@# `coverage_gate` le a base do nome do ficheiro.
	@# Um teste vermelho **falha** o alvo. O gate 4 chama-se «unit e cobertura»,
	@# e a primeira versao deste alvo engolia o codigo de saida do `node --test`
	@# com um `|| echo aviso`: media a cobertura do codigo que os testes
	@# cobriam e nunca olhava para o resultado deles. Um teste quebrado passava
	@# o gate verde. Correm-se todos antes de falhar, para o relatorio mostrar
	@# as suites todas e nao so a primeira.
	@#
	@# `--test-coverage-exclude` (KAM-132): o relatorio de cada pacote deixa de
	@# levar o que o ci/thresholds.yaml ja nao conta — os pontos de entrada, os
	@# ficheiros de teste e o `dist/` dos pacotes do workspace. A lista nao se
	@# escreve aqui: pede-se ao `coverage_gate`, que a deriva do mesmo ficheiro
	@# de limiares que depois classifica o que foi medido — uma segunda lista a
	@# divergir dele poe ficheiros fora da medicao sem ninguem dar por isso.
	@#
	@# **Passa-se a exclusao, nao a inclusao.** A primeira versao deste alvo
	@# passava `--test-coverage-include` com o ambito, e a *flag* de inclusao
	@# retira do relatorio tudo o que nao esteja na lista — incluindo um
	@# ficheiro que nenhum estrato classifica, que e precisamente o que tem de
	@# chegar ao gate para o **falhar**. A revisao adversarial reproduziu-o: um
	@# `packages/core-ts/fora.ts` carregado por um teste falhava o gate sem a
	@# *flag* e passava com ela.
	@#
	@# E sao **caminhos exactos**, nao globs. O `ci/thresholds.yaml` le padroes
	@# com `fnmatch` e o Node le-os com o seu proprio glob; traduzir entre os
	@# dois era a armadilha que o ticket nomeia (`*` atravessa barras num e nao
	@# no outro, e um `./` a cabeca faz o padrao do Node nao bater em nada —
	@# medido). Com caminhos exactos nao ha traducao nenhuma.
	@#
	@# O que nenhuma *flag* do Node faz e crescer o denominador: filtram o que o
	@# V8 reportou e nunca vao ao disco. Quem conta o TypeScript sem testes e o
	@# `coverage_gate`, que injecta a 0% o que nenhum relatorio mediu.
	@falhou=""; \
	if [ -x "$(VENV_PYTHON)" ]; then PY="$(VENV_PYTHON)"; else PY="$(PYTHON)"; fi; \
	for pacote in $(PACOTES_NODE); do \
	  nome=$$(echo "$$pacote" | tr "/" "-"); \
	  registo="$(ROOT)/ci/coverage/node-$$nome.log"; \
	  lista="$(ROOT)/ci/coverage/excluidos-$$nome.txt"; \
	  "$$PY" tools/coverage_gate.py --root $(ROOT) --exclusoes-node "$$pacote" >"$$lista"; \
	  excluir=$$(sed "s|^|--test-coverage-exclude=|" "$$lista" | tr "\n" " "); \
	  if (cd "$$pacote" && node --test --experimental-test-coverage $$excluir \
	    --test-reporter=tap --test-reporter-destination=stdout \
	    --test-reporter=lcov \
	    --test-reporter-destination="$(ROOT)/ci/coverage/node-$$nome.lcov" \
	    tests/*.test.ts) >"$$registo" 2>&1; then \
	    rm -f "$$registo"; \
	  else \
	    falhou="$$falhou $$pacote"; \
	    echo "    FALHA: $$pacote" >&2; \
	    grep -n "^not ok" "$$registo" | head -10 >&2 || true; \
	  fi; \
	done; \
	if [ -n "$$falhou" ]; then \
	  echo "" >&2; \
	  echo "  Testes Node vermelhos em:$$falhou" >&2; \
	  echo "  O registo de cada um esta em ci/coverage/node-*.log." >&2; \
	  exit 1; \
	fi
	@ls ci/coverage/node-*.lcov >/dev/null 2>&1 \
	  && echo "    $$(ls ci/coverage/node-*.lcov | wc -l) relatorio(s) Node, testes verdes" \
	  || { echo "    ERRO: nenhum relatorio LCOV produzido" >&2; exit 1; }

## coverage-python: mede cobertura do Python (LCOV)
coverage-python: exige-suites
	@echo "==> cobertura Python"
	@mkdir -p ci/coverage
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "    ERRO: $(VENV) nao existe. Corra 'make bootstrap'." >&2; exit 1; \
	fi
	@# As quatro suites, nao so uma: `tools` e onde vive o codigo que **impoe**
	@# os gates, e medir so uma delas dava uma percentagem que nao descreve nada.
	@#
	@# E um teste vermelho **falha** o alvo. A primeira versao punha `|| true` em
	@# cada suite com `>/dev/null 2>&1` por cima: o gate 4 media cobertura e
	@# nunca olhava para o resultado dos testes. Um teste de `lint_refs` esteve
	@# vermelho desde que este alvo nasceu, e o gate passou verde em sete PRs.
	@falhou=""; \
	primeira=1; \
	for suite in $(SUITES_DE_TOOLS); do \
	  if [ "$$primeira" = "1" ]; then acumula=""; primeira=0; else acumula="--append"; fi; \
	  registo="$(ROOT)/ci/coverage/python-$$suite.log"; \
	  if (cd tools && $(ROOT)/$(VENV_PYTHON) -m coverage run --branch $$acumula \
	    --source=. --omit="*/tests/*" \
	    -m unittest discover -s "$$suite/tests" -t .) >"$$registo" 2>&1; then \
	    rm -f "$$registo"; \
	  else \
	    falhou="$$falhou $$suite"; \
	    echo "    FALHA: $$suite" >&2; \
	    grep -nE "^(FAIL|ERROR):" "$$registo" | head -10 >&2 || true; \
	  fi; \
	done; \
	(cd tools && $(ROOT)/$(VENV_PYTHON) -m coverage lcov \
	  -o $(ROOT)/ci/coverage/python-tools.lcov --quiet); \
	if [ -n "$$falhou" ]; then \
	  echo "" >&2; \
	  echo "  Testes Python vermelhos em:$$falhou" >&2; \
	  echo "  O registo de cada um esta em ci/coverage/python-*.log." >&2; \
	  exit 1; \
	fi
	@$(VENV_PYTHON) -m coverage run --branch --source=libs/py-core/src \
	  -m unittest discover -s libs/py-core/tests -t libs/py-core/tests \
	  >ci/coverage/python-libs.log 2>&1 || { \
	    echo "    FALHA: libs/py-core" >&2; \
	    cat ci/coverage/python-libs.log >&2; exit 1; }
	@rm -f ci/coverage/python-libs.log
	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-libs.lcov --quiet
	@# E a suite do AGR, que e o unico Python dentro de `services/*/src/**` — o
	@# ambito que o `ci/thresholds.yaml` declara e que nenhum alvo media. Os
	@# testes de `services/agr/tests/` ja existiam e exercitavam os tres
	@# ficheiros a fundo: o que faltava era a **medicao**, pelo que o estrato
	@# `restante` nao descia se alguem lhes mexesse (KAM-151, lacuna 25 do
	@# docs/ci.md §7). E a mesma classe de defeito que o KAM-132 fechou do lado
	@# Node — ambito declarado, medicao em falta — e cura-se aqui, no alvo, e nao
	@# no `universo()` do `coverage_gate`: injectar um `.py` a 0% exigia contar
	@# **instrucoes**, que e a regua do `coverage.py` e nao o numero de linhas do
	@# ficheiro (ver `EXTENSOES_DO_UNIVERSO` em tools/coverage_gate.py).
	@#
	@# **Corre depois do `coverage lcov` do `libs/py-core`, e a ordem nao e
	@# estetica:** `coverage run` sem `--append` apaga o ficheiro de dados, pelo
	@# que um bloco novo entre o `run` e o `lcov` de outro deixava esse outro com
	@# um relatorio vazio, sem erro nenhum. Preso por teste em
	@# `tools/lint_arch/tests/test_makefile.py::TestCoberturaPythonMedeOAmbito`.
	@#
	@# O nome do LCOV e `python-services-agr.lcov` por exigencia do
	@# `coverage_gate.base_do_nome`, que le o pacote do nome do ficheiro:
	@# `python-agr.lcov` dava a base `agr`, que nao e familia nenhuma.
	@$(VENV_PYTHON) -m coverage run --branch --source=services/agr/src \
	  -m unittest discover -s services/agr/tests -t services/agr/tests \
	  >ci/coverage/python-agr.log 2>&1 || { \
	    echo "    FALHA: services/agr" >&2; \
	    cat ci/coverage/python-agr.log >&2; exit 1; }
	@rm -f ci/coverage/python-agr.log
	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-services-agr.lcov --quiet
	@echo "    testes Python verdes"

## ci-9: gate 9 — varrimento de segredos
#
# Duas passagens, e nenhuma substitui a outra (KAM-131):
#
#   tree     o que o git segue agora
#   history  os blobs que o intervalo do PR acrescenta a historia
#
# A segunda existe porque a primeira nao ve o cenario com que o `docs/ci.md` §3
# justifica o *pre-commit*: um segredo posto no commit A e retirado no commit B
# nao esta na arvore final, passa o gate, e entra no `main` com o merge.
#
# O intervalo vem do CI em tres variaveis, e o alvo **nao decide nada** sobre
# elas: quem decide e `tools/scan_secrets/historia.py:decidir_intervalo`, que e
# uma funcao pura com testes. Nao ha *lint* de *workflows* neste repositorio,
# pelo que uma condicao escrita em YAML ou aqui no `make` nao seria verificavel
# por teste nenhum. Sem as variaveis — `make ci-9` na maquina de quem
# desenvolve — o modo e `so-arvore`, e o comando di-lo em voz alta em vez de dar
# a passagem da historia por satisfeita.
GATE9_EVENTO ?=
GATE9_BASE ?=
GATE9_HEAD ?= HEAD

ci-9:
	@echo "==> gate 9: segredos"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from scan_secrets.cli import main; sys.exit(main(['--root', '$(ROOT)', 'tree']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from scan_secrets.cli import main; sys.exit(main(['--root', '$(ROOT)', 'history', '--evento', '$(GATE9_EVENTO)', '--base', '$(GATE9_BASE)', '--head', '$(GATE9_HEAD)']))"
	@# O canario prova-se **no gate**, e nao so num teste unitario.
	@#
	@# A pasta do canario e a unica area onde um valor com forma real e
	@# permitido, pelo que o varrimento da arvore passa por la sem o apanhar —
	@# e e isso que se quer. Mas assim a unica prova de que o scanner detecta
	@# alguma coisa vinha de um `unittest`, que durante sete PRs nao era
	@# corrido por nada que pudesse falhar. Copia-se o canario para fora da
	@# area e exige-se que seja apanhado: a prova fica no gate.
	@prova="$(ROOT)/ci/prova-canario"; \
	  rm -rf "$$prova"; mkdir -p "$$prova"; \
	  cp tools/scan_secrets/tests/fixtures/canario/segredos.txt "$$prova/"; \
	  cp tools/scan_secrets/tests/fixtures/canario/chave_privada.txt "$$prova/"; \
	  achados=$$($(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from scan_secrets.cli import main; sys.exit(main(['--root', '$(ROOT)', 'files', 'ci/prova-canario/segredos.txt', 'ci/prova-canario/chave_privada.txt']))" 2>&1 | grep -c "possivel segredo" || true); \
	  rm -rf "$$prova"; \
	  if [ "$$achados" -lt 9 ]; then \
	    echo "    ERRO: o canario fora da sua area deu $$achados achados, esperava 9 ou mais." >&2; \
	    echo "    O scanner deixou de detectar o que existe para detectar." >&2; \
	    exit 1; \
	  fi; \
	  echo "    canario fora da area: $$achados achados (prova de que o scanner morde)"

## ci-11: gate 11 — SCA (OSV), licencas e SBOM
ci-11: ci-waivers
	@echo "==> gate 11: SBOM, licencas e vulnerabilidades"
	@if [ -x "$(VENV_PYTHON)" ]; then PY="$(VENV_PYTHON)"; else PY="$(PYTHON)"; fi; \
	  "$$PY" -c "import sys; sys.path.insert(0, 'tools'); from sbom.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"
	@# A lista de bloqueio nao se reimplementa aqui: e a mesma do KAM-001.
	@$(MAKE) lint-arch
	@# O que o KAM-067 acrescenta ao gate 11, sem repetir nada do que esta acima.
	@$(MAKE) supply-chain

# --- Cadeia de abastecimento (KAM-067) ---------------------------------------
#
# Corre dentro do gate 11, e nao num gate proprio. Os gates 14 (imagem) e 18
# (release) do §4 sao do KAM-078, que e quem constroi e publica imagens; o que
# aqui esta e a parte que se verifica **no repositorio**, em cada PR, antes de
# existir imagem nenhuma. Dois passos, e os dois contam:
#
#   1. `check`    imagens por digest e no inventario, sem instalacao em runtime,
#                 servicos so de leitura, lista de saidas por servico, registo
#                 de licencas coerente, quarentena do Renovate, CI sem chaves.
#   2. `canario`  copia o repositorio, aplica um defeito de cada vez e exige que
#                 cada um de vermelho pela regra certa. Sem este passo, a prova
#                 de que as verificacoes mordem vivia so num `unittest`.
#
# So biblioteca padrao: corre antes de qualquer instalacao.

## supply-chain: digests, instalacao, egress, licencas e quarentena (KAM-067)
supply-chain:
	@echo "==> cadeia de abastecimento (KAM-067)"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from supply_chain.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from supply_chain.cli import main; sys.exit(main(['--root', '$(ROOT)', 'canario']))"

# --- Ruleset de main: o espelho contra o que o GitHub aplica (KAM-137) -------
#
# NAO esta no `ci:` e nao e required check de nenhum PR, e e deliberado.
# A API dos rulesets exige a permissao `administration`, que o `GITHUB_TOKEN`
# das Actions nao tem; qualquer outro token obrigava a uma referencia
# `secrets.*` num workflow, que e exactamente o que a regra
# `chave-estatica-no-ci` do gate 11 recusa. A decisao, o que custa, e onde vive
# a credencial de leitura estao em `docs/adr/ADR-L003-verificacao-do-ruleset.md`.
#
# Precisa de `gh auth login` com `administration: read` sobre o repositorio, ou
# de `--transporte http` com KAMBA_RULESET_TOKEN. Saida 0 = conforme,
# 1 = diverge, 2 = nao se conseguiu verificar — e 2 nunca e verde.

## ruleset: compara o ruleset de main com .github/rulesets/main.json (KAM-137)
ruleset:
	@echo "==> ruleset de main (KAM-137)"
	@$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); from ruleset_check.cli import main; sys.exit(main(['--root', '$(ROOT)', 'check']))"

# --- Gates reservados, fail-closed ------------------------------------------
#
# Os gates 5 a 8 existem no §4 do Engineering Standards e sao implementados pelos
# tickets que criam o que eles testam. Os que ainda nao existem ficam aqui a
# **falhar**, de proposito: um job reservado que passasse em silencio fazia
# parecer que o pipeline cobre o que nao cobre, e ninguem se lembraria de o
# ligar. Em Outubro de 2026 so o 5 continua reservado — o 6 e o 8 nasceram com
# o KAM-004 e o KAM-003, e o 7 com o KAM-007.
#
# A valvula e `ci/waivers.yaml`, com prazo de 30 dias e referencia — o que forca
# a revisitar a decisao em vez de a esquecer.

define GATE_RESERVADO
@echo "==> gate $(1): $(2)"
@$(PYTHON) tools/ci_gate_reservado.py --root $(ROOT) --gate $(1) --nome "$(2)" --ticket "$(3)"
endef

## ci-5: gate 5 — integracao (reservado; KAM-003)
ci-5:
	$(call GATE_RESERVADO,5,integracao contra Postgres e fila reais,KAM-003)

## ci-6: gate 6 — isolamento de tenant: RLS FORCE, X-03, X-04, X-05 (KAM-004)
ci-6:
	@# O X-11 primeiro: nao precisa de base de dados, e se os logs levam
	@# identificadores nao vale a pena levantar um PostgreSQL para o saber.
	@$(MAKE) x11
	@echo "==> gate 6: isolamento de tenant contra um PostgreSQL 18.6 descartavel"
	@# A camada SQL do isolamento (ADR-015): a suite semeia dois tenants com
	@# canarios em todas as tabelas com `tenant_id` — descobertas pelo catalogo —
	@# e tenta ler e escrever os dados de um com o contexto do outro. A suite
	@# ponta a ponta (rotas, tools, storage) e o KAM-066.
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "    ERRO: $(VENV) nao existe. Corra 'make bootstrap'." >&2; exit 1; \
	fi
	@command -v docker >/dev/null 2>&1 || { \
	  echo "    ERRO: o gate 6 precisa do Docker para levantar o PostgreSQL." >&2; \
	  exit 1; }
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_isolamento

## ci-7: gate 7 — contratos de evento: compatibilidade, PII, exemplos (KAM-007)
ci-7:
	@echo "==> gate 7: contratos de evento"
	@# Quatro verificacoes, e a primeira precisa do ramo base: o criterio 3 do
	@# KAM-007 diz «comparacao com a branch principal», e um contrato nao esta
	@# errado em absoluto — esta errado em relacao ao que os consumidores ja
	@# assinaram. Num `checkout` sem `fetch-depth: 0` o `origin/main` nao
	@# existe, e o gate **recusa** em vez de saltar: uma verificacao que se
	@# desliga sozinha quando nao encontra a base nunca falha no dia em que
	@# alguem configura mal o CI.
	@#
	@# A parte dos **webhooks** da Meta continua por fazer e e o KAM-024. Este
	@# alvo cobre os contratos de evento; quando o KAM-024 chegar, acrescenta
	@# a sua verificacao aqui.
	@$(VENV_PYTHON) -m contract_diff --root $(ROOT) check

## ci-8: gate 8 — migracoes: aplicar, reverter e voltar a aplicar (KAM-003)
ci-8:
	@echo "==> gate 8: migracoes contra um PostgreSQL 18.6 descartavel"
	@# O gate levanta o seu proprio PostgreSQL, em tmpfs, e apaga-o no fim. Nao
	@# usa o do compose de desenvolvimento, e nao pode: a suite faz
	@# `downgrade base`, que apaga o schema `platform`. A suite recusa-se a
	@# correr contra uma base que nao se chame `*_gate8`.
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "    ERRO: $(VENV) nao existe. Corra 'make bootstrap'." >&2; exit 1; \
	fi
	@command -v docker >/dev/null 2>&1 || { \
	  echo "    ERRO: o gate 8 precisa do Docker para levantar o PostgreSQL." >&2; \
	  exit 1; }
	@# A prova por mutacao completa corre de noite (KAM-143) e nao aqui — sao
	@# horas. Mas a conferencia de que cada mutacao ainda **encontra o seu
	@# texto** leva segundos e so usa a biblioteca padrao, e e o que torna
	@# verdadeira a frase «no PR corre o que e novo»: sem isto, um PR que mude
	@# codigo mutado sem actualizar a lista so era apanhado na manha seguinte.
	@$(PYTHON) db/mutacoes.py --aplicaveis
	@$(VENV_PYTHON) db/gate_bd.py --suite tests
	@# A segunda metade (KAM-008): o modulo de identidade de contacto, que e
	@# TypeScript, contra uma base igual — resolver, fundir, rodar chaves, apagar
	@# — com o *dump* e o registo do servidor procurados por canarios. Outra base
	@# descartavel, e nao a de cima: esta suite quer a tabela de versoes de chave
	@# vazia. Fica no job do gate 8 porque precisa do mesmo PostgreSQL e das
	@# mesmas migracoes; o gate 5 (integracao de servicos) continua reservado.
	@echo "==> gate 8: identidade de contacto contra um PostgreSQL 18.6 descartavel"
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_identidade
	@# A terceira metade (KAM-005): o publicador de eventos, que tambem e
	@# TypeScript, contra a mesma base **e** uma fila real. As garantias do
	@# BullMQ estao NAO VERIFICADO (E4 §2.10): o recuo, a republicacao depois de
	@# um `kill -9`, a eleicao de lider e o atraso sob carga nao se provam contra
	@# uma fila em memoria, e e por isso que esta suite levanta um Valkey (a
	@# omissao da D12) ao lado do PostgreSQL, na mesma rede, os dois em tmpfs e
	@# apagados no fim. Leva mais tempo do que as outras duas juntas, e a razao
	@# e o proprio criterio: o 4 para a fila 60 s, o 8 mede 5 minutos de carga.
	@echo "==> gate 8: publicador de eventos contra PostgreSQL 18.6 e fila reais"
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_eventos
	@# A quarta (KAM-006): o **consumidor**, a DLQ e a reposicao. O que so aqui
	@# se prova e que a marca de consumo e o efeito estao na mesma transaccao,
	@# que seis tentativas abrem a DLQ e que o que o Redis perdeu volta a fila —
	@# nada disso se mede com uma base falsa. Corre com o relogio acelerado que
	@# os «Testes Requeridos» do ticket pedem (a escada e a carencia; os valores
	@# reais tem prova propria nos testes sem fila), e por isso leva segundos e
	@# nao os 756 s por teste que a escada do §6.4 custaria.
	@echo "==> gate 8: consumidor, DLQ e reposicao contra PostgreSQL 18.6 e fila reais"
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_eventos_consumo
	@# E a medicao de carga, em suite propria: sao cinco minutos (o numero e do
	@# criterio 8), e uma suite custa isso **por cada mutacao** que a escolha.
	@# Separada, as mutacoes do publicador correm em tres minutos e esta corre
	@# uma vez. Nao e opcional: um p95 acima do limiar falha o build.
	@echo "==> gate 8: carga de eventos (50/s durante 5 min)"
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_eventos_carga
	@echo "==> gate 8: concorrencia da cadeia de auditoria (KAM-012)"
	@$(VENV_PYTHON) db/gate_bd.py --suite tests_auditoria_carga

# -----------------------------------------------------------------------------
# Limpeza
# -----------------------------------------------------------------------------

## clean: remove artefactos locais (mantem os volumes de dados)
clean:
	@rm -rf $(VENV) ci/coverage ci/sbom ci/x11
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -name 'node_modules' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Limpo. 'make bootstrap' reconstroi."

## nuke: clean e APAGA os volumes de dados da pilha local
nuke: clean
	@$(COMPOSE) down --volumes --remove-orphans
	@echo "Volumes de desenvolvimento apagados."

# Portões por eixo, custo e velocidade

Lê este ficheiro quando fores decidir que portões correr, por que ordem, e o que mandar para
background.

- [O agregador](#o-agregador)
- [Roteamento: eixo → portões](#roteamento-eixo--portões)
- [Custo e ordem](#custo-e-ordem)
- [Seis regras de velocidade](#seis-regras-de-velocidade)
- [O que não se acelera](#o-que-não-se-acelera)

---

## O agregador

Cada gate é um alvo `make ci-<n>`, e o *workflow* do GitHub Actions **só os orquestra**: nenhuma
lógica fica presa à plataforma de CI, e qualquer gate corre à mão com o mesmo comando que o
pipeline usa.

```bash
make ci        # os onze activos — lento; raramente é o que queres
make ci-3c     # um gate
```

A numeração é a do `specs/01_Engineering_Standards_e_Handoff.md` §4 e **não se renumera**: o
gate 11 é o gate 11 na documentação, nos *waivers* e nos tickets a jusante. A tabela
gate → alvo → dono é a do `docs/ci.md` §2 — consulta-a lá, não de memória.

| # | Gate | Alvo | Estado |
|---|---|---|---|
| 1 | Build a partir dos lockfiles | `make ci-1` | activo |
| 2 | Lint, tipos, e nenhum serviço a escrever fora do *logger* | `make ci-2` | activo |
| 3 | Referências cruzadas, caminhos de handoff, contagens em prosa | `make ci-3` | activo |
| 3b | Nomes canónicos | `make ci-3b` | activo |
| 3c | Coerência do backlog (mestre ↔ epics) | `make ci-3c` | activo |
| 4 | Unit e cobertura | `make ci-4` | activo |
| 5 | Integração | `make ci-5` | **reservado, fail-closed** |
| 6 | Isolamento de tenant (RLS, X-03/04/05) e X-11 | `make ci-6` | activo |
| 7 | Contratos de evento, e webhooks da Meta | `make ci-7` | activo |
| 8 | **Primeiro** `db/mutacoes.py --aplicaveis`, depois migrações: aplicar, reverter, voltar a aplicar | `make ci-8` | activo |
| 9 | Segredos (árvore **e** história do PR) | `make ci-9` | activo |
| 10 | SAST | — | lacuna, sem ticket |
| 11 | SCA, licenças, vulnerabilidades, SBOM, cadeia de abastecimento | `make ci-11` | activo |
| 12–18 | Categorias, eval, imagem, deploy, aprovação, tag | — | KAM-067, KAM-078, KAM-088 |

**Um gate reservado falha de propósito.** O 5 continua a avermelhar com
`tools/ci_gate_reservado.py` até o ticket que o implementa o ligar: um *job* reservado que
passasse em silêncio fazia parecer que o pipeline cobre o que não cobre, e ninguém se lembraria
de o ligar. A válvula é `ci/waivers.yaml`, com prazo de 30 dias e referência — o que força a
revisitar a decisão em vez de a esquecer. `make ci-waivers` valida-a.

**O pipeline é fail-closed e nenhum gate se marca `skip`** sem ADR ou aprovação registada, e
esse registo é o `ci/waivers.yaml`, não uma condição no *workflow*.

### Os códigos de saída, e o que engana em cada um

```text
0   verde
1   vermelho
2   NÃO SE CONSEGUIU VERIFICAR — nunca é verde
```

O `2` é o que custa. O `make ruleset` sai 2 quando não consegue falar com a API; o
`lint_arch` sai 2 com `check`, que não é subcomando dele; e um
`make ci-2` numa máquina sem `pnpm` responde `command not found` com 127 — o que não é «o gate
passa», é «o gate não correu». Lê o código de saída, não a última linha do output
([`evidencia-e-verificacao.md`](evidencia-e-verificacao.md)).

**Os limiares só apertam.** O `ci/thresholds.yaml` classifica por estrato, e o `coverage_gate`
**injecta a 0% o que nenhum relatório mediu** — um pacote Node novo entra no `PACOTES_NODE` do
`Makefile` **e** no `ci/thresholds.yaml`, senão os seus ficheiros afundam o estrato sem que
ninguém lhes tenha medido nada.

---

## Roteamento: eixo → portões

A pergunta não é «que gates existem», é «o que é que eu toquei». A análise de impacto já
respondeu — esta tabela traduz a resposta.

| Tocaste em… | Portões |
|---|---|
| **`specs/`, `docs/`, prosa, contagens, referências** | `ci-3` |
| **`specs/INDICE.md` §4, bloco de ticket, tabela-resumo do §3** | `ci-3c` |
| **`specs/02` §3, `canon/*.yaml`, nomes em migrações ou eventos** | `ci-3b` (+ `make dict-export`) |
| **Diagramas Mermaid** | `make mermaid` — não é gate, precisa de Docker |
| **`packages/*`, `services/*` (TypeScript)** | `ci-1` `ci-2` `ci-4` — **e `make up && make smoke`** se mexeste no arranque, nas portas, nas env vars ou na superfície HTTP |
| **`libs/py-core`, `tools/*` (Python)** | `ci-2` (`lint_arch`) `ci-4` |
| **Qualquer serviço que escreva uma linha de log** | `ci-2` (`log-lint`) + `make x11` |
| **`db/migrations`, revisões, DDL** | `ci-8` (+ `python db/mutacoes.py --aplicaveis`) |
| **Tabelas com `tenant_id`, políticas RLS, funções `SECURITY *`** | `ci-6` |
| **Contratos de evento, schemas, `packages/contracts`** | `ci-7` |
| **Webhooks da Meta, `tools/meta-sim`** | `ci-7-meta` |
| **Lockfiles, dependências, imagens, licenças** | `ci-1` (`lock-check`) `ci-11` |
| **`.github/workflows/`, `ci/*.yaml`, `Makefile`** | `ci-waivers` + o gate que o alvo serve; `make ruleset` à mão |
| **Composição da pilha, `infra/compose/`, portas, `/healthz`** | `make up && make smoke` |
| **Qualquer coisa, sempre** | `ci-9` (segredos) |

Três gates **anti-recorrência** merecem nota, porque fecham defeitos que escaparam a tudo o
resto:

- **`ci-3c`** (KAM-138) — nasceu porque o backlog mestre e os epics divergiram sem que nenhuma
  leitura o apanhasse. Verifica a reciprocidade `Dependências`↔`Bloqueia`, que o §4 **não** tem
  coluna para denunciar.
- **O passo de canário**, no `ci-3b`, no `ci-9`, no `ci-11` e no `log-lint`: as fixtures
  negativas **têm de falhar**, cada uma pela sua regra. Sem este passo, a prova de que o lint
  morde vivia só num `unittest` — e um teste de `lint_refs` esteve vermelho desde que o alvo de
  cobertura nasceu, com o gate verde em sete PRs.
- **A segunda passagem do `ci-9`**, sobre os *blobs* que o intervalo do PR acrescenta à
  história: um segredo posto no commit A e retirado no B não está na árvore final, passava o
  gate, e entrava no `main` com o merge.

### Os que precisam de Docker

O `ci-6`, o `ci-8` e o `make mermaid` levantam contentores. O `ci-8` levanta o **seu próprio**
PostgreSQL em tmpfs e apaga-o no fim — não usa o do compose, e não pode: a suite faz
`downgrade base`, que apaga o schema, e recusa-se a correr contra uma base que não se chame
`*_gate8`. Sem Docker utilizável, estes gates não correm; dizer «não corri» é a única resposta
honesta.

---

## Custo e ordem

```text
SEGUNDOS      ci-3 · ci-3b · ci-3c · ci-waivers · lint-arch · lint-branch · lock-check
              db/mutacoes.py --aplicaveis
DEZENAS DE S  ci-2 (typecheck + log-lint) · ci-9 · ci-11 (sbom, licenças, supply-chain)
MINUTOS       ci-1 (install do lockfile + build) · ci-4 (cobertura Node e Python)
CAROS         ci-6 (PostgreSQL + X-11) · ci-8 (dezenas de suites, 5 min só de carga de
              eventos, 60 s de carga do webhook) · make mermaid (primeira corrida, imagem)
HORAS         a lista inteira de mutações — 822 mutações hoje. Medido no runner a
              2026-10-26: as seis fatias de uma lista de 783 levaram 43, 46, 51,
              52, 54 e 75 min. Em série, nesta máquina, muitas horas.
```

**Não orces pelos 3 h 24 min de 2026-10-12.** Essa medição é de uma lista oito a nove vezes mais
curta, e o `.github/workflows/mutacoes.yaml` nomeia-a como a estimativa que pôs a tarefa nocturna
a 83% do tecto — «a estimativa nunca foi medição». Com um orçamento de relógio errado, a regra de
parar ao dobro faz-te abandonar uma prova que estava a correr normalmente.

A ordem é fail-fast: os linters de biblioteca padrão primeiro (correm **antes** de qualquer
instalação, de propósito), depois os tipos, depois os testes do componente, depois os gates com
Docker. Respeita-a quando correres subconjuntos — uma referência inválida não precisa de
esperar que um PostgreSQL suba para se revelar.

**As mutações: no PR corre o que é novo; a lista inteira corre de noite** (KAM-143, em
`.github/workflows/mutacoes.yaml`, repartida por seis *runners*). O que o PR verifica por
máquina é `--aplicaveis` (segundos, sem Docker, dentro do gate 8): confirma que nenhuma mutação
antiga deixou de se aplicar. Correr à mão o subconjunto novo chega quando o diff só
**acrescenta** testes e mutações; a lista inteira corre-se quando o diff toca num teste antigo
**ou num ficheiro que alguma mutação altera**.

> **E por isso o `gate` 8 não é «o das migrações».** O `--aplicaveis` é o **primeiro** passo
> do alvo (`Makefile`, antes do `gate_bd.py`), pelo que **um PR sem uma única migração pode
> pintar o `gate` 8 de vermelho** — basta tocar numa linha que alguma mutação aponte. Medido:
> um PR de `tools/` e `docs/` falhou-o com `MUTACAO NAO APLICAVEL`, porque trocou as entradas
> de um dicionário por uma compreensão e a mutação procurava a linha literal. A inferência
> «não toquei em migrações, logo este vermelho não é meu» é **falsa**, e foi feita.

```bash
python db/mutacoes.py --aplicaveis              # sempre, segundos
python db/mutacoes.py <python> <excerto>        # só as que casam o excerto, 8 de cada vez
```

A tarefa nocturna não diz qual PR quebrou uma mutação: diz o commit de `main` em que correu.

---

## Seis regras de velocidade

**1. Fail-fast, e por eixo.** Linters → tipos → testes do componente → portões do eixo. A suite
inteira é para antes de abrir PR, não para cada iteração.

**2. O lint corre-se depois da última edição.** Correr antes e editar a seguir é como não o ter
corrido.

**3. Os caros vão para background.** Lança o `ci-8` e o `ci-6` em background e continua no que
não depende deles. **Não faças polling** — a notificação chega quando terminarem.

**4. Vagas, não fila.** Correm em paralelo os tickets cujas dependências já estão fechadas:

```bash
python .claude/skills/software-factory/scripts/vagas.py
```

Dois candidatos que definam o mesmo nome ou o mesmo contrato **não** correm juntos, e os que
acrescentam revisões de base de dados entram em série — cada uma encaixa na anterior. Lança os
subagentes **na mesma mensagem**, senão correm em série e pagas a latência sem ganhar nada. Cada
escritor no seu worktree ([`isolamento.md`](isolamento.md)).

**5. Não refaças a discovery.** `KNOWN_FACTS` no contrato do agente é o campo que mais poupa.
Sem ele cada subagente redescobre o mesmo conjunto e chega a conclusões ligeiramente diferentes
— o que produz conflitos que não existiam, e cada conflito custa uma ronda de arbitragem.

**6. Decide e avança.** Quando tens informação para agir, age. Não re-derives factos já
estabelecidos, não reabras decisões já tomadas, não enumeres opções que não vais seguir. Não
pares à espera: enquanto uma prova longa corre, avança no que não depende dela.

### Três armadilhas de medição

- **Um `kamba.pth` feito à mão não equivale ao runner.** Resolver um `ImportError` acrescentando
  caminhos ao `site-packages` do venv faz a suite passar localmente e esconde uma receita de
  cópia quebrada, que o runner descobre. Mede com a receita que o `Makefile` tem.
- **Validação dirigida não cobre o pacote.** Correr um teste por nome deixa passar testes do
  mesmo ficheiro que só correm noutro gate. Verde dirigido não é verde.
- **Medir uma vez apresenta não-determinismo como determinismo.** Uma corrida só não distingue
  defeito de *flake*, e uma `PROVA INVALIDA` no relatório das mutações é a suite a falhar por
  carga da máquina — conta como sobrevivente e baixa-se o paralelismo.

---

## O que não se acelera

Quatro coisas. Cortá-las não é velocidade, é dívida com juros:

- **O portão do fundador.** Ratificar, fechar um `D#`, mexer numa regra de bloqueio.
- **A revisão adversarial.** É a primeira a ser sacrificada quando há pressa, e a que mais
  custa quando falta.
- **Os passos de canário.** São a prova de que o lint morde. Saltá-los deixa um gate que mede
  nada e devolve verde.
- **As caixas do ticket com evidência nomeada.** Marcar por memória do trabalho feito é a forma
  mais barata de transformar um DoD num enfeite.

E **os gates só correm sobre aquilo a que o ficheiro os expõe** — um defeito de forma que não
esteja num ficheiro exercitado passa por todos. Há relatos públicos — **INDÍCIO**, sem fonte
primária citada aqui e sem anexo de evidência no repositório — de que com agentes o *throughput*
sobe e a estabilidade de entrega desce. A fábrica existe para que as duas subam juntas, e é isso
que [`metricas-e-realimentacao.md`](metricas-e-realimentacao.md) mede.

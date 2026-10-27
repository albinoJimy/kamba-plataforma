# Isolamento de escritores concorrentes

Lê este ficheiro antes de lançar mais do que um agente a **escrever**, e sempre que trabalhares
num worktree.

- [A regra](#a-regra)
- [Worktree por escritor](#worktree-por-escritor)
- [Não há registo de sessões — e o que isso custa](#não-há-registo-de-sessões--e-o-que-isso-custa)
- [Recursos partilhados sem o parecerem](#recursos-partilhados-sem-o-parecerem)
- [Ficheiros que não se partilham](#ficheiros-que-não-se-partilham)
- [Integração do trabalho paralelo](#integração-do-trabalho-paralelo)

---

## A regra

> **Quem lê pode partilhar a árvore. Quem escreve precisa da sua.**

Um agente read-only — Discovery, revisão, auditoria — corre na árvore que já tens e não há nada
a isolar. Um agente que chama `Write`, `Edit` ou `Bash` com efeitos precisa de worktree próprio,
ou de uma fronteira de ficheiros tão estreita que o worktree seria redundante.

A versão prática: **dois escritores nunca tocam nos mesmos ficheiros**. Se não consegues
garantir isso por desenho, não é paralelismo — é uma corrida que vais perder mais tarde, quando
já houver trabalho feito sobre o resultado errado.

E a lição que este repositório pagou mais caro não é de ficheiros, é de **vocabulário**: cinco
redactores sobre o mesmo desenho produziram três esquemas de `contacts`, `valor_kz` contra
`valor_minor` e dois eventos para a mesma confirmação de pagamento. Antes de lançar escritores
em paralelo, fixa o dicionário (SKILL.md §1.3).

---

## Worktree por escritor

Nesta app, um subagente recebe árvore própria com `isolation: "worktree"`; a sessão corrente
entra e sai de um worktree com as ferramentas de worktree do host. O repositório já é trabalhado
assim: `git worktree list` dá hoje 8 árvores além do checkout principal, e `.claude/worktrees/`
tem 12 entradas — duas delas resíduos, com `;W` e `;C` no nome.

O que isso implica, e que é a origem de quase todos os acidentes desta classe:

```text
Cada worktree tem ficheiros próprios.
Todos partilham o MESMO .git.
E ramos que não se fundiram NÃO SE VÊEM.
```

Há ainda uma particularidade desta máquina: **dentro de um worktree, o `lint_contagens` sai com
código 2** e diz que três grandezas não casam nada. O filtro do corpus exclui tudo o que tenha
`.claude` no caminho, e os worktrees vivem em `.claude/worktrees/`. É defeito dele, registado
como **dívida 44 de `docs/dividas-documentais.md`** — descoberto no KAM-133, atribuído ao dono do
gate 3, e **não** ao KAM-158, que está entregue e foi quem criou o passo. Até estar corrigido,
confia no que o CI diz desse passo e não no que lês localmente.

---

## Não há registo de sessões — e o que isso custa

Outros repositórios da casa têm um `sessoes.py` que registam tarefa, tickets e ficheiros, e que
sinaliza três colisões: mesmo ticket, mesmo ficheiro, e **base divergente** (dois HEAD em que
nenhum é ancestral do outro). **Aqui não existe.** É lacuna conhecida, e enquanto o for, a
verificação é manual e faz-se **antes** de escrever.

**Começa pela lista de sessões, não pelo `git`**, e a ordem não é preferência:

```
mcp__ccd_session_mgmt__list_sessions   # título, cwd, ramo, isRunning, PR
```

> **O `git` é cego a uma sessão em curso.** Uma sessão desta app abre ramo com nome gerado
> (`claude/frosty-benz-177ecd`) e não committa nada até ter algo que preste. Zero commits mais um
> nome sem ticket faz com que as três buscas abaixo devolvam **zero** sobre um ticket que está a
> ser implementado neste momento — e zero lê-se como «ninguém está nisto».
>
> **Medido, e sobre esta própria skill:** na primeira admissão a sério, declarou «não há colisão»
> sobre o KAM-038 com uma sessão a implementá-lo, `isRunning: true`. O worktree
> (`wonderful-murdock-9d1ff6`) e o ramo estavam à vista nas três buscas, e nenhuma os ligou ao
> ticket. Quem leva o `KAM-NNN` é o **título** da sessão.
>
> Isto não substitui as buscas: a lista vê quem está a trabalhar **nesta máquina e nesta app**.
> Trabalho noutra máquina, ou fora da app, continua invisível até ao `push`.

Depois da lista, as buscas do `git`, para o que já está committado:

```bash
git worktree list                                   # que árvores existem
git branch -a --sort=-committerdate | head -20      # que ramos têm trabalho recente
git log --all --oneline --grep 'KAM-NNN' | head     # alguém já tocou neste ticket?
git log --all --name-only --oneline -5 -- <ficheiro>
```

```bash
python .claude/skills/software-factory/scripts/vagas.py
```

O `vagas.py` cobre uma parte do problema e não a outra: diz que **tickets** podem arrancar, lido
do backlog mestre e dos blocos fechados; não diz que **sessões** já arrancaram. Dois agentes
podem pegar na mesma vaga ao mesmo tempo e nenhum instrumento o diz.

**Porque é que isto não é um gate.** O runner tem um só worktree, onde uma verificação de
colisão não teria com que colidir e passaria sempre — fail-open silencioso, pior do que
verificação nenhuma. Um registo destes é observação do agora, partilhada entre worktrees, e
versioná-lo em `specs/` ou `docs/` tornava-o invisível entre ramos até ao merge, que é quando a
colisão já custou o trabalho.

**O caso que mais custa é a base divergente**, e só se descobre ao abrir o PR, com o trabalho
todo feito: um ramo assenta numa base que foi reescrita por baixo dele.

---

## Recursos partilhados sem o parecerem

Estes recursos são comuns a **todos** os worktrees da máquina, ou colidem entre si. Nenhum dá
erro quando dois agentes os usam ao mesmo tempo; dão resultado errado.

### 1. Os contentores dos gates com base de dados

O `ci-6` e o `ci-8` levantam PostgreSQL em Docker, e o `ci-8` levanta também uma fila. Duas
sessões a correr o mesmo gate disputam portas e nomes de contentor, e a suite de migrações faz
`downgrade base` — que apaga o schema da base em que correr. A guarda que existe é o nome: a
suite **recusa-se a correr** contra uma base que não se chame `*_gate8`. O que ela não impede é
que duas corridas tuas se atropelem.

Corre um de cada vez, ou dá prefixo próprio ao teu. E nunca aponte nenhum deles à base do
`make up`.

### 2. `ci/coverage/`

O `coverage-node` escreve um LCOV **por pacote**, com o caminho do pacote no nome do ficheiro, e
o `coverage-python` acumula com `--append` por suite. Dois runs sobrepostos escrevem por cima um
do outro e o `coverage_gate` lê a mistura: um estrato afunda sem que nenhum teste tenha mudado.
E a ordem interna não é estética — `coverage run` sem `--append` apaga o ficheiro de dados, pelo
que um bloco novo no meio deixa o relatório de outro vazio, sem erro nenhum.

### 3. `ci/x11/` e `ci/prova-canario/`

Os dois começam por `rm -rf`. O `make x11` apaga e recria `ci/x11` antes de gerar as 1 030
fixtures; o passo de canário do `ci-9` cria e apaga `ci/prova-canario`. Duas corridas ao mesmo
tempo apagam o trabalho uma da outra, e o X-11 compara saídas byte a byte — uma comparação sobre
ficheiros meio escritos dá um vermelho que não tem nada a ver com o teu diff.

### 4. O `.venv` e o `pnpm store`

O `.venv` vive na árvore, pelo que cada worktree tem o seu — e cada um custa um `bootstrap`
completo com `--require-hashes`. O *store* do pnpm e a cache do Corepack, não: são da máquina.
**Nunca acrescentes caminhos ao `site-packages` à mão para resolver um `ImportError`**: um
`kamba.pth` feito a mão faz a suite passar localmente e esconde uma receita de cópia quebrada,
que o runner descobre depois.

### 5. A pilha do `make up`

Um só `docker compose` por máquina, com portas fixas (`gwy=3000`, `worker-canal=3001`,
`com=3002`, `onboarding-web=3003`, `agr=8000`). Dois worktrees a levantar a pilha disputam as
portas, e o `make smoke` do segundo mede os contentores do primeiro. **Um smoke verde sobre a
pilha de outra sessão é pior do que smoke nenhum**, porque produz evidência com o nome do teu
ticket.

---

## Ficheiros que não se partilham

Candidatos permanentes a `FILES_OUT_OF_SCOPE` quando há mais do que um escritor. Listar o que
**não** se toca é mais eficaz do que listar o que se toca: o segundo é uma sugestão, o primeiro
é uma fronteira.

| Ficheiro / área | Porquê |
|---|---|
| `specs/INDICE.md` §4 | backlog mestre — dependências, prioridades e fases de tudo |
| `specs/02_Dicionario_de_Dados_Canonico.md` §3 | o vocabulário; dois escritores aqui divergem por desenho |
| `canon/dicionario.yaml` | é **gerado** por `make dict-export`; dois geradores, dois ficheiros |
| `docs/tecnica/00` §8 e §13.3 | a tabela de ADRs e as decisões abertas |
| `db/migrations/` | cada revisão encaixa na anterior — entram em **série**, nunca em paralelo |
| `Makefile`, `.github/workflows/ci.yaml`, `docs/ci.md`, `ci/thresholds.yaml` | ficheiros de registo |
| Tabelas-resumo do §3 de cada epic, e as linhas de «Controlo de versões» | colidem a cada ticket |

Os da última linha e os ficheiros de registo são a **excepção consentida**: colidem sempre, as
colisões são mecânicas, e resolve-as quem integra. As revisões de base de dados **não** são
mecânicas, e é por isso que estão na lista pela razão oposta.

---

## Integração do trabalho paralelo

**Ramos verdes sozinhos já partiram juntos.** Daí a regra:

```text
VERDE EM CADA RAMO  ≠  VERDE NA ÁRVORE INTEGRADA
```

1. Funde pela **ordem de dependência**, um de cada vez. Há um só integrador.
2. Depois de cada merge, corre os portões do eixo **na árvore integrada**, não no ramo.
3. Lê o diff antes de fundir — não basta o CI ter passado.
4. Quem toca em ficheiros partilhados **diz quais**: o contrato de cada agente pede a lista, e
   quem integra funde por ordem e traz o `main` aos ramos que ficaram atrás (merge, nunca
   *force-push*).
5. Dois PRs em cadeia fundem-se pela ordem; fundir a base por squash deixa o encadeado em
   `CONFLICTING`.

Dentro de um worktree desta app, sincroniza com a base pelo `sync_with_base_branch` do host: o
merge local não consegue escrever os ficheiros protegidos pela sandbox do repositório.

E o trabalho de uma sessão em worktree próprio **não está nesta árvore** até o ramo ser fundido.
Antes de qualquer passo que precise das peças juntas, nomeia cada ramo pelo ref completo
(`refs/heads/…`) e confirma que é isso que se quer fundir.

> **E não perguntes ao `git` se um ramo fundiu.** A `main` funde por *squash*, e há dois remotos
> sem antepassado comum — `origin` (privado) e `publico` (onde os PR vivem). O
> `merge-base --is-ancestor` diz «não fundido» para um ramo que acabou de fundir, e para um ramo
> da outra linha o `merge-base` **falha**: quem não verificar o código de saída lê o silêncio
> como «este ramo não tem nada a mais». Custou chegar a um passo de apagar sete worktrees com
> 164 a 254 commits cada. A prova é o estado do PR no GitHub — ver
> [`encerramento.md`](encerramento.md).

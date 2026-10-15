# ANÁLISE-15 — Revisão adversarial do KAM-132 (cobertura de todo o TypeScript do âmbito)

| Campo | Valor |
|---|---|
| Ticket | KAM-132 — Cobertura Node sobre todo o TypeScript do âmbito (`--test-coverage-include`) |
| Ramo | `feature/KAM-132-cobertura-de-todo-o-typescript` (PR `albinoJimy/kamba#41`) |
| *Baseline* revista | `28f80ef` (depois de `git merge origin/main`, `dc243e0`) |
| Data | Outubro 2026 |
| Método | Revisão independente por agente que recebeu os requisitos e o código e **não** as justificações do executor; prova por execução no mesmo contentor em que o ticket foi medido; avaliação dos critérios à letra |
| Veredicto da revisão | **Não fechar como está** — 3 maiores, 9 menores, 1 suspeita |
| Estado | Os 3 maiores, a suspeita e 7 dos 9 menores **corrigidos**, cada um com teste de regressão e mutação; 2 menores aceites sem alteração, com a razão escrita (§3). A prova por mutação passou de 17 para **24 mutações, 24 apanhadas** |

A revisão foi conduzida por um agente independente, que recebeu os requisitos e
o código e não as justificações de quem o escreveu. Quando começou, o
`make ci-4` corria verde nos dois estados, as 17 mutações do executor estavam
todas apanhadas, e as 216 baterias de `tools/lint_arch` passavam.

> **O que esta revisão ensina, em uma frase:** as três maiores são a mesma
> classe de defeito — **a cura escolhida criou uma segunda fuga por onde a
> primeira saía**. A *flag* que tornava o relatório igual ao âmbito tornava
> também inalcançável a regra que faz falhar um ficheiro sem estrato; a
> constante que dizia quais ficheiros medir deixava passar três extensões de
> TypeScript; e o universo lido do disco inteiro trazia ficheiros que o
> `.gitignore` ignora. Nenhuma das três aparecia num teste verde, e nenhuma das
> 17 mutações do executor as cobria.

---

## 1. O que o ticket supunha e a medição contradisse

Duas coisas, e as duas são do ticket e não da revisão. Ficam aqui porque são o
contexto sem o qual os achados não se leem.

**`--test-coverage-include` não cresce o denominador.** O Contexto do ticket diz
que «`--test-coverage-include='src/**'` resolve-o, e **altera o valor medido**».
Não altera: é um filtro sobre o que o V8 reportou. Medido no Node 24.21.0, em
`packages/core-ts` com `tests/health.test.ts`, que carrega um ficheiro:

| `--test-coverage-include` | Ficheiros no LCOV |
|---|---|
| (sem a *flag*) | 1 |
| `src/**`, `src/**/*.ts`, `src/*` | 1 |
| `./src/**` | **0** |
| `src/storage/motor.ts` (nunca carregado) | **0** |

E confirmado no código do próprio Node
(`lib/internal/test_runner/coverage.js`): «This check filters out files that do
not match the include globs». A revisão reproduziu a tabela inteira.

**O estrato que desce não era o `restante`.** O ticket esperava que o `restante`
descesse «por um valor que ninguém mediu ainda». O valor é **zero**: os 16
ficheiros do `restante` são todos carregados por algum teste. Os três que o lado
Node nunca mediu caem todos no `critico`.

---

## 2. Achados maiores

### A1 — Código do âmbito que não fosse `.ts` escapava por completo, e escapava *pior* do que antes

`EXTENSOES_DO_UNIVERSO = (".ts",)`. Um ficheiro no âmbito cuja extensão não fosse
`.ts` não era injectado **nem medido**: a lista do `--test-coverage-include` era
derivada do universo, e a *flag* de inclusão retira do relatório tudo o que não
esteja nela. Reproduzido com 50 declarações em cada extensão, sobre a base
`critico 94% 4802/5055 29 fich.` e `restante 91% 9282/10175 99 fich.`:

| Ficheiro criado | Ficheiros medidos | `critico` | `restante` |
|---|---|---|---|
| `src/fuga.mts`, `.cts`, `.tsx`, `.js` | 137 | inalterado | inalterado |
| **controle** `src/fuga.ts` | **138** | inalterado | **90%, 9282/10225, 100** |

`.mts`, `.cts` e `.tsx` **são** TypeScript, e o `module: nodenext` do
`tsconfig.base.json` corre-os sem configuração nenhuma. O CA1 fala em «ficheiro
TypeScript»; a demonstração do ticket tinha escolhido a extensão em que a
propriedade valia.

**Corrigido.** `EXTENSOES_DO_UNIVERSO` passa a ser `.ts`, `.mts`, `.cts`,
`.tsx`, `.js`, `.mjs`, `.cjs` e `.jsx` — tudo o que o Node 24 executa. Medido:
não existe hoje nenhum ficheiro dessas extensões dentro das raízes do âmbito,
pelo que nenhum número se moveu com a correcção. Regressão:
`test_as_outras_extensoes_do_node_nao_fogem`. Mutações «volta a deixar fugir
tudo o que não seja `.ts`» e «também conta ficheiros que nenhum medidor lê»:
ambas apanhadas.

**Por fechar, declarado.** A revisão pedia também uma bateria que proibisse, em
`*/src/**`, qualquer extensão executável fora da lista. Não entrou: é uma regra
nova sobre **o que pode existir na árvore**, e não sobre o que se mede, e
inventá-la aqui era alargar o escopo. Uma extensão que o Node não execute
directamente (`.vue`, `.svelte`) continua fora do universo.

### A2 — O CA7 regrediu: um ficheiro medido que nenhum estrato classifica deixava de falhar o *gate*

É o achado mais caro, porque contraria um critério de aceitação do próprio
ticket e porque as baterias novas **impunham** a regressão.

Com o âmbito passado em `--test-coverage-include`, um `packages/core-ts/fora.ts`
(fora de `src/`, logo sem estrato) carregado por um teste era retirado do
relatório e nunca chegava ao `avaliar()`:

```text
fora.ts no LCOV:  sem a flag 1 | com a flag 0
o gate:           sem a flag → "1 ficheiro(s) medidos e nao classificados"
                  com a flag → nenhum achado desse tipo
```

Reproduzido pela revisão e **confirmado pelo executor** antes de corrigir. O que
mantinha a caixa verde era `test_ficheiro_sem_estrato_falha`, que exercita
`avaliar()` com um caminho `.py` sintético — o nível errado, que é o padrão «a
verificação correu sobre o nível errado» do guião.

**Corrigido.** O `make coverage-node` passa agora
**`--test-coverage-exclude`** com os ficheiros que os `excluidos` do
`ci/thresholds.yaml` retiram, em vez de `--test-coverage-include` com o âmbito.
A lista continua a sair do mesmo ficheiro de limiares, em caminhos exactos; o
que muda é o sentido: exclui-se o que não conta, em vez de incluir-se só o que
conta, pelo que um ficheiro sem estrato continua a chegar ao *gate* e a
falhá-lo. Regressão, ao nível certo: `test_um_ts_medido_sem_estrato_falha_o_gate`
(LCOV com o órfão → `EXIT=1`, com o caminho impresso),
`test_o_que_nenhum_estrato_classifica_nao_e_excluido` e
`test_nao_passa_o_ambito_em_test_coverage_include`. Mutações «volta a filtrar
pelo âmbito em vez de excluir», «passa o âmbito em vez do que está excluído» e
«o `node --test` deixa de receber a lista»: as três apanhadas.

### A3 — O número do *gate* dependia de ficheiros não versionados em qualquer parte da árvore

`universo()` percorria a árvore toda, e os padrões do `critico` são da forma
`*/identity/*`, `*/storage/*`, `*/logger/*` — com o `*` do `fnmatch` a atravessar
barras. Qualquer `.ts` em qualquer pasta com um desses nomes entrava no estrato
dos 90%. Medido pela revisão:

| O que se pôs no disco | `critico` |
|---|---|
| (base) | 94% — 4802/5055, 29 ficheiros |
| `tmp/base/` com uma cópia de `packages/core-ts/src/` | **46% — 4802/10281, 46 ficheiros**, *gate* vermelho |
| `rascunho/storage/x.ts` | 4802/5057, 30 ficheiros |
| `docs/exemplos/identity/x.ts` | 4802/5056, 30 ficheiros |

`tmp/` e `scratch/` estão no `.gitignore`, e **o próprio ambiente de medição
deste ticket tinha `/repo/tmp/base/` com uma cópia de `origin/main`**. Salvou-se
por acidente: o único `.ts` que lá estava não batia em padrão nenhum. Contraria
o princípio 1 do `docs/ci.md` §1 — o mesmo *commit* dava números diferentes no
CI e na máquina de quem trabalha.

**Corrigido.** A procura começa nas **raízes dos `padroes`** — os primeiros
segmentos literais, hoje `libs/`, `packages/`, `services/` e `tools/` — e não na
raiz do repositório; um ficheiro de limiares cujos padrões comecem todos por `*`
é **erro de configuração** e não universo vazio. Regressão:
`test_nao_entra_pelo_que_esta_fora_das_raizes_dos_padroes` (com cópias em
`tmp/base/`, `rascunho/` e `.claude/worktrees/`) e
`test_sem_raiz_literal_e_erro_de_configuracao`. Mutações «volta a percorrer a
árvore inteira em vez das raízes», «sem raiz literal mede zero em silêncio» e
«as pastas com ponto à cabeça contam como código»: as três apanhadas — a última
só depois de a bateria ganhar uma pasta de ferramenta **dentro** de uma raiz,
porque sobreviveu à primeira execução.

**Residual declarado** (`docs/ci.md` §3): dentro das raízes, um ficheiro por
versionar conta. É a mesma propriedade do lado Python — `coverage run
--source=.` também lê o disco — e é o que torna a demonstração deste *gate*
reproduzível à mão. O número do CI é o que decide.

---

## 3. Achados menores, e o que se fez de cada um

| # | Achado | Disposição |
|---|---|---|
| 4 | `linhas_do_ficheiro()` não era o `LF` do Node em geral: o `str.splitlines` divide em `\x0c`, `\x0b` e `\x85`, que não são terminadores de linha de JavaScript. Ficheiro de 5 linhas com um *form feed* num literal: Node `LF:5`, o *gate* **8** | **Corrigido.** Contam-se os terminadores do JavaScript (LF, CR, LS, PS), `\r\n` como um só, e o último terminador não abre linha nova. Três testes (`..._terminadores_do_javascript...`, `..._crlf_e_um_terminador...`, `..._ficheiro_vazio...`) e duas mutações, apanhadas. A afirmação na documentação passou de «o `LF` que o Node daria» a dizer **como** se conta |
| 5 | Os números de lacuna no bloco do ticket contradiziam o `docs/ci.md` §7: «lacuna 22» e «lacuna 24» onde são 23 e 25, e a lacuna 22 é de outro ticket | **Corrigido** nas quatro citações |
| 6 | `docs/seguranca/lacunas.md` repetia a versão antiga: «a cobertura Node só mede os ficheiros carregados pelos testes», com a lacuna 10 como limite activo | **Corrigido.** A linha passa a nomear as lacunas 7, 23 e 25, e perde também a afirmação de que o estrato `critico` está vazio, que era falsa desde o KAM-004 |
| 7 | Contagens que não reproduziam: «42 ficheiros do universo real» (são **32**) e «192 testes em `tools/lint_arch`» (são **225**) | **Corrigido**, com os números remedidos |
| 8 | `ANALISE-15` citada e inexistente | **Corrigido**: é este ficheiro |
| 9 | A tabela do §3 afirmava «todo o `.py` do âmbito» do lado Python, contra a lacuna 25 do mesmo documento, e o título dizia «a régua é a mesma» enquanto a auto-avaliação marcava o critério como parcial | **Corrigido.** O título passa a «os dois lados passam a medir o mesmo universo», a célula do Python nomeia os alvos que medem e o que fica de fora, e uma nota diz o que o ticket **não** igualou |
| 10 | Dois testes do âmbito real são tautológicos no código não mutado | **Aceito sem alteração.** Existem para apanhar mutações que removam os filtros, e apanham-nas. O que se corrigiu foi a afirmação: a auto-avaliação citava-os como verificação do âmbito real, e passou a citar o que eles conferem |
| 11 | Os números antes/depois não reproduziam na ponta do ramo: `restante` 9392/10267 contra 9282/10175 registados, porque o «antes» era `7015cbf` e `main` passou a `dc243e0` | **Corrigido.** Os quatro números foram remedidos com `make ci-4` nos dois estados **sobre a árvore fundida**, e os documentos levam os novos |
| 12 (suspeita) | `$$incluir` expandido sem aspas: um caminho com espaço partia-se em dois argumentos e o padrão deixava de bater, em silêncio. Não reproduzido | **Corrigido na origem.** O `coverage_gate --exclusoes-node` **recusa** (código 2) um caminho com espaço em branco, com a razão na mensagem. Teste `test_caminho_com_espaco_e_erro` e mutação «um caminho com espaço passa em silêncio», apanhada |

---

## 4. O que a revisão atacou e não cedeu

Vale registar, porque uma revisão que só lista defeitos não diz o que está
sólido:

- **A semântica da *flag* está certa**, e é a correcção do executor contra o seu
  próprio ticket. A revisão reproduziu a tabela do §1 byte a byte.
- **Os `excluidos` valem nos dois sítios.** O filtro retira de cada relatório
  exactamente o que o `ci/thresholds.yaml` já excluía, pelo que nenhum número de
  estrato se move.
- **Uma lista de âmbito vazia não é engolida**: `coverage_gate` sai com 2 e o
  `make` aborta (`.SHELLFLAGS := -eu -o pipefail -c`).
- **Não há segunda lista de padrões**: tudo vem de `coverage_gate`, em caminhos
  exactos.
- **O arreio de mutação é sólido** — cópia fora do repositório, linha de base
  conferida, uma cópia por mutação. O que lhe faltava era cobertura: nenhuma das
  17 mutações originais cobria A1, A2 ou A3. São agora **24**.
- **O limiar não foi tocado**: `specs/01` §4.1 intacto, `ci/thresholds.yaml` só
  com alteração de comentário.
- **A injecção é auditável**: os ficheiros saem pelo nome, e as 245 linhas
  conferem (108 + 70 + 67 = 5055 − 4810).

---

## 5. O que a revisão não conseguiu verificar

Fica escrito porque é informação, e porque nenhuma destas lacunas foi fechada
depois:

- **O «antes» não foi reproduzido pela revisão**: não repôs `origin/main` nem
  reconstruiu as dependências desse estado. Reproduziu o «depois» e a separação
  entre as duas réguas com `--sem-universo` sobre o mesmo LCOV.
- **Só o *gate* 4 correu na ponta do ramo** durante a revisão; `make ci-2`,
  `ci-9` e os restantes não. (Correram depois, no executor e no CI.)
- **O `lint_refs` sobre `/repo`** não corre dentro do contentor, porque o `.git`
  da árvore de trabalho aponta para um caminho de Windows; correu sobre uma
  cópia com repositório local.
- **Ligações simbólicas**: `os.walk` não as segue, pelo que uma pasta de fontes
  acessível só por *symlink* escaparia ao universo. Não testado, e não fechado.
- **Windows**: toda a medição correu em Linux dentro do contentor. A
  normalização (`as_posix()`, `replace("\\", "/")`) está certa por leitura, não
  por execução.

---

## 6. Uma consequência que a revisão nomeou e que se devolve ao dono do *gate* 4

O estrato que ficou com margem curta é o **`critico`**: 94% contra um mínimo de
90%, o que dá cerca de **250 linhas** de folga. Bastam dois ou três módulos
novos sem cobertura em `*/identity/*`, `*/storage/*`, `*/logger/*`,
`*/tenant_guard/*`, `*/pagamentos/*` ou `*/validador/*` para pôr o *gate*
vermelho — e três dos 29 ficheiros do estrato estão a 0% por não ter nenhum
teste que os importe (os dois índices de módulo e o motor de armazenamento).
Cobri-los com uma bateria de superfície é defensável e **não se fez neste
ticket**: um teste que apenas os importasse dava-lhes ~100% sem exercitar
comportamento, porque o `LF` do Node conta `export { … }` e comentários como
linhas atingidas. É decisão de quem é dono do limiar, não do executor.

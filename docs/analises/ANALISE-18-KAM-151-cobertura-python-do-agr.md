# ANÁLISE-16 — Revisão adversarial do KAM-151 (cobertura Python sobre `services/agr/src/`)

| Campo | Valor |
|---|---|
| Objecto | O diff do KAM-151: `Makefile`, `tools/coverage_gate.py`, `tools/lint_arch/tests/test_makefile.py`, `tools/lint_arch/tests/mutacoes.py`, `docs/ci.md`, `docs/seguranca/lacunas.md`, `docs/dividas-documentais.md`, `specs/INDICE.md`, `specs/EPIC-01_Fundacoes_Dados.md`, e o novo `docs/evidencia/KAM-151.md` |
| Ticket | KAM-151 — Cobertura Python sobre `services/agr/src/`, que nenhum alvo media |
| Data | 2026-10-12 |
| Revisor | Agente independente, com o diff e os requisitos originais — **sem** as justificações de quem escreveu |
| Veredicto | **Pronto com correcções nomeadas** — as duas maiores corrigidas neste PR |

> **Nada aqui é opinião sobre estilo.** A revisão recebeu instrução de procurar
> razões para o trabalho estar errado, de recalcular os números a partir das
> fracções e de atacar a fundo a hipótese central do ticket. O que segue são os
> achados e o que se fez a cada um.

---

## 1. O que a revisão confirmou por medição própria

Vale registar antes dos achados, porque é o que dá peso ao resto: o revisor
reproduziu os números centrais do ticket **com os seus próprios comandos**, numa
máquina sem `make` nem `node`, instalando `coverage`, `starlette` e `uvicorn`.

| Afirmação do ticket | Resultado |
|---|---|
| 9 testes na *suite* do AGR | reproduzido (2 em `test_arranque.py`, 7 em `test_healthz.py`) |
| `48 stmts / 3 miss / 92%`, e o por-ficheiro 5-2, 17-1, 12-0, 14-0 | reproduzido **à linha** |
| «77 linhas» e «31 instruções» nos três do âmbito | `PythonParser`: 5+12+14 = 31; `wc -l`: 18+28+31 = 77 |
| «as linhas 16 e 18 do `__init__.py` são o corpo de `create_app()`» | confirmado |
| 29/31 = 93%, 4802/5055 = 94%, 9652/10526 = 91%, 9681/10557 = 91% | confirmados, com a truncatura do `ci/thresholds.yaml` |
| Linha de base «antes» | coincide com `../evidencia/KAM-132.md` §4 e com o *run* do CI que ela cita |
| CA3 vermelho antes da correcção, verde depois | reproduzido nos dois sentidos |
| Backlog: 144 blocos, um só `## KAM-151`, EPIC-01 com 30, sincronia nos seis campos, reciprocidade com o KAM-132, sem ciclos nem inversões | confirmado por *script* |
| Mutações | 24/24 apanhadas (antes das quatro novas); `db/mutacoes.py --aplicaveis` 138/0 |

**A hipótese que se pediu para atacar a fundo foi refutada, por medição.** A
pergunta era se o par de números é mesmo um par — se o próprio diff não cresce o
denominador, dado que `tools/coverage_gate.py` ganhou linhas e `tools/**` está no
estrato `restante`. O revisor mediu com o `coverage.parser`: **248 instruções
antes e 248 depois** (624 → 641 linhas de ficheiro), e confirmou que o numerador
também não se move, correndo a cobertura do módulo com e sem a bateria nova
(248 stmts, 20 miss, 92% nas duas). O par é um par.

---

## 2. Achados maiores

### M1 — «o ficheiro sai nomeado no relatório do *gate*» era falso. **Corrigido.**

**Onde:** `docs/evidencia/KAM-151.md` §4.1 e a *blockquote* do bloco do ticket.

A promessa central do ticket estava escrita como «antes, acrescentar Python sem
testes a `services/agr/src/` deixava o `restante` onde estava; agora baixa-o, **e
o ficheiro sai nomeado no relatório do *gate***». A primeira metade é verdade; a
segunda não.

O `tools/coverage_gate.py` imprime nomes **só** da lista `injectados`, que sai de
`universo(raiz, limiares)` — e esse corre com `EXTENSOES_DO_UNIVERSO`, que não
tem `.py`, por tudo o que o ticket explica. O achado de estrato abaixo do limiar
imprime a percentagem, a fracção e a contagem de ficheiros, nunca os nomes. Um
`.py` novo e sem testes é **medido** a 0% (correcto, baixa o agregado) e nunca
passa por `injectados`.

Diagnóstico do revisor, e é o que faz deste um achado maior e não um lapso: **a
frase vinha do `docs/ci.md` §3, onde é verdadeira**, porque ali descreve o caso
Node do KAM-132, em que o ficheiro entra por injecção. É o padrão «afirmação
promovida» — uma frase correcta no documento vizinho, copiada para um mecanismo
diferente.

**O que se fez.** Mediu-se, em vez de se corrigir só a redacção: um módulo de 840
instruções em 962 linhas sem testes leva o `restante` de **91% a 84%** e **não
aparece** na saída, onde só os três `.ts` injectados saem nomeados. A frase foi
retirada dos dois sítios, a reacção do número ficou com o par medido
(`../evidencia/KAM-151.md` §5.1), e a falta ficou registada como **lacuna 26** de
`../ci.md` §7 e na linha do *gate* 4 de `../seguranca/lacunas.md` — é uma
assimetria real que o ticket destapou e que não se fecha nele, porque nomear o
que foi medido é mexer no relatório para os dois estratos e as duas linguagens.

### M2 — três afirmações do bloco do KAM-132 continuavam a dizer que a lacuna estava aberta. **Corrigido.**

**Onde:** `specs/EPIC-01_Fundacoes_Dados.md`, bloco do KAM-132 — a linha do CA
«A régua é a mesma nos dois lados» (**parcial**, alínea (b)), a linha «DoD: todos
os CA satisfeitos» e a *blockquote* «O que isto custa».

As três diziam que `services/agr/src/` não é medido por alvo nenhum e que «a
decisão fica com o dono do *gate* 4». O ticket actualizou a tabela do
`../ci.md` §3, o §7 e o `../seguranca/lacunas.md`, e deixou três afirmações no
**mesmo ficheiro** que estava a editar, 1 200 linhas acima do bloco novo, a dizer
o contrário.

O revisor agravou-o com um argumento que se aceita: o ticket **registou** uma
dívida documental bem mais marginal — a contagem «138 blocos» do *blockquote*
«Como ler» do `../seguranca/lacunas.md`, linha 19 de
`../dividas-documentais.md` — e **não registou esta**, que qualifica
exactamente pelo mesmo critério.

**O que se fez.** Corrigiram-se as três, **sem reescrever a avaliação para trás**:
cada uma passa a dizer que é a leitura à data da entrega do KAM-132, e que a
alínea (b) foi depois fechada pelo KAM-151, ficando a (a) aberta. As caixas do
KAM-132 mantêm-se como estavam — uma avaliação datada não se altera porque o
mundo mudou depois. É o mesmo tratamento que o ticket defende para o caso dos
«138 blocos», aplicado com coerência.

---

## 3. Achados menores

| # | Achado | O que se fez |
|---|---|---|
| m3 | Três referências de secção erradas: a evidência remetia para o seu §5 onde a decisão está no §6; citava o «§5 do KAM-132» quando a decisão devolvida ao dono do *gate* 4 está no §7; e dizia que a fachada fica nomeada «na evidência §4», quando está no §2 e no §6 | **Corrigidas** as três |
| m4 | A bateria nova pregava o `--source=` mas **não** o relatório a chegar ao *gate*: lia o nome do LCOV por uma expressão que só apanhava `ci/coverage/<algo>.lcov`. Um destino com outra extensão (`ci/coverage/agr.dat`) não era apanhado, a lista continuava *truthy*, e **os quatro testes ficavam verdes** enquanto o `glob("*.lcov")` do `coverage_gate` deixava de ler o AGR. «A mesma classe de defeito que o ticket diz estar a fechar, um nível acima» | **Corrigido**, e é a correcção mais valiosa da revisão. O teste passa a exigir um `coverage lcov` por `coverage run`, que o destino caia dentro do `glob` do *gate*, e que a `base_do_nome` desse destino cubra a pasta que aquele `coverage run` mede — liga as três peças em vez de duas. Provado vermelho nos dois modos de falha |
| m5 | A prova por mutação do *gate* 4 não tinha sido corrida nem registada, apesar de o cabeçalho de `tools/lint_arch/tests/mutacoes.py` a mandar correr «quando se mexe no `coverage_gate`, nos limiares ou no alvo» — e o diff mexe em dois. Além disso, o lado Node tinha três mutações `cablagem:` e o lado Python nenhuma: a propriedade ficava provada por execução pontual e não por oráculo permanente | **Corrigido**: quatro mutações `cablagem:` novas do lado Python. Bateria de 24 para **28, 28 apanhadas, 0 sobreviventes**. O revisor correu-a também, antes das novas: 24/24 |
| m6 | `../seguranca/lacunas.md` é a tabela «Defeitos e limites conhecidos de controlos que já existem», e a linha do *gate* 4 passava a trazer uma lacuna **fechada** na coluna «Ticket» — um limite que já não existe, lido na coluna errada | **Corrigido**: a linha lista só limites vivos, e ganha a lacuna 26. A história fica no `../ci.md` §7 (riscado) e §9 |
| m7 | «9652/10526 = 91,70% e 9681/10557 = 91,70%» servia de prova de que «não é arredondamento a esconder nada» e escrevia uma identidade que não existe: são 91,697% e 91,702% | **Corrigido** para três decimais, e a frase passa a dizer o que os números dizem — o valor **subiu** cinco milésimas |
| m8 | PEP8 (três linhas em branco antes de `_comandos`, uma antes da classe seguinte) e a fragilidade de `_pastas_medidas`, que usa o primeiro `cd X &&` do comando para prefixar todos os `--source=` desse comando | **Corrigido** o espaçamento, e a regra «um `cd` por comando» ficou escrita em comentário no sítio onde se assume |

---

## 4. Suspeitas

| # | Suspeita | O que se fez |
|---|---|---|
| s9 | O CA5 dizia «Os **ficheiros** não cobertos ficam nomeados», e o que se entregou foram duas **instruções** dentro de um ficheiro a 60% — não há ficheiro não coberto. «Satisfeito em espírito; o substantivo do critério está errado e convida a uma leitura mais forte do que o facto» | **Aceite e corrigido**: o critério passa a «o que fica sem cobertura fica nomeado — ficheiro, e as linhas quando o ficheiro está parcialmente coberto». É o princípio «cumprir à letra, não em espírito» aplicado a um critério escrito por quem o ia cumprir |
| s10 | `../ci.md` §3 dizia «há **um alvo** por cada pasta do âmbito». Há **um** alvo (`coverage-python`) com três `--source=` | **Corrigido** para «um `--source=` por cada pasta», que é a formulação que o `Makefile` e a *docstring* do `coverage_gate` já usavam |

---

## 5. O que a revisão declarou NÃO VERIFICADO

Registado porque é informação útil, e porque a honestidade do veredicto depende
de se saber onde ele não chega:

- **A linha de base de oito relatórios**, que precisa de `node` e `pnpm` — a
  máquina do revisor não os tem. Herda-a de `../evidencia/KAM-132.md`, com que
  coincide à linha: **INDÍCIO forte, não medição própria**.
- **Qualquer execução de `make`.** Em particular, o revisor atesta que todos os
  números do bloco «o alvo inteiro» do §4 coincidem com o que reproduziu em
  separado, e **não** que o comando correu.
- Uma falha local de `log_policy` por dependências do ambiente do revisor, sem
  relação com o diff e não investigada.
- O backlog foi verificado **estruturalmente** (contagem, unicidade, sincronia de
  campos, grafo), por *script*, e não por leitura dos ~150 blocos.

Nota de método que o próprio revisor levantou: **o `docs/evidencia/KAM-151.md`
mudou no disco a meio da revisão**, ganhando o número do alvo inteiro e a medição
das 248 instruções. Isso fechou dois achados que ele tinha em mão. Fica dito
porque uma revisão sobre um alvo em movimento é mais fraca do que uma sobre um
alvo parado.

---

## 6. Leitura

Duas coisas que esta revisão diz sobre o processo e não sobre o ticket.

**A primeira é que o achado maior foi uma afirmação, não um defeito de código.**
O código fazia o que devia; o que estava errado era a frase que o descrevia — e
era a frase que vendia o ticket. O repositório tem um nome para isto desde a
`../../.claude/skills/agentic-engineering/SKILL.md`: «o modo de falha dominante
não é escrever a coisa errada, é afirmar com mais confiança do que a evidência
sustenta». Aconteceu duas vezes neste ticket: aqui, e numa versão anterior do
`../ci.md` que trazia «95%, 73/77 instruções» escritos **antes** de se medir
(os valores reais são 93% e 29/31).

**A segunda é que o m4 é o achado que paga a revisão.** Era um teste novo, escrito
precisamente para fechar uma classe de defeito, que tinha dentro de si a mesma
classe de defeito — um furo pelo qual o relatório saía do *gate* com os quatro
testes verdes. Nenhuma leitura o apanhava; apanhou-o quem foi procurar razões
para o trabalho estar errado.

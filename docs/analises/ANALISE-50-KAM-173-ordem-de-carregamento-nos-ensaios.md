# ANALISE-50 — KAM-173: a ordem de carregamento do `unittest`, e o portão que a fecha

| Campo | Valor |
|---|---|
| Ticket | KAM-173 |
| PR | `#109` |
| Data | Novembro de 2026 |
| Instrumentos | `code-review high`, `ponytail-review`, um revisor documental independente |
| Classificação | Documento de Referência — Interno |

> **`security-review` não correu, e a razão é mecânica.** O *prompt* dessa
> *skill* tem `git diff origin/HEAD...` embutido, e entre as duas linhas de
> remoto deste repositório não há antepassado comum — responde
> `fatal: no merge base`. O diff também não toca RLS, segredos, identidade nem
> *egress*. Fica **NÃO VERIFICADO** por esse eixo, dito em vez de suposto.

## 1. O que a revisão mudou, numa frase

**O portão passava verde sobre falhas reais, e o defeito era todo numa junta
só:** o veredicto era derivado de um `dict` com perdas (`estado`) em vez do
`TestResult` que o código já tinha na mão. Três sintomas, os três reproduzidos,
e o pior deles cobria **332 usos de `subTest` em 55 ficheiros** das duas suites
que o portão diz proteger.

Um portão que se fecha verde sobre o que devia apanhar é pior do que nenhum
portão, porque passa a ser citado como prova. É o defeito que este ticket
existe para não repetir, cometido dentro dele.

## 2. Os achados que bloqueavam, e o que se mediu

### A-1 — uma falha dentro de `self.subTest(...)` saía verde

O `unittest` **não** chama `addFailure` quando um sub-caso falha: chama
`addSubTest`, que o `Registo` não derrubava. O `startTest` já tinha escrito
`'ok'`, e nada o corrigia.

```text
antes:  ordem_dos_ensaios: f_sub — 2 testes na ordem inversa, 0 vermelhos   rc=0
        unittest sobre a mesma ordem: FAILED (failures=1)
depois: ordem_dos_ensaios: f_sub — 1 de 2 teste(s) ... vermelho(s) na inversa  rc=1
        - caso_sub.TestALeitura.test_dentro_de_subtest: ok -> subtest-failure
```

**População:** 332 usos de `subTest` em 55 ficheiros (31 em
`libs/py-core/tests`, 24 em `services/agr/tests`). Nenhum deles conseguia ficar
vermelho neste portão.

### A-2 — um `SkipTest` de módulo apagava N testes do inventário

Um `setUpModule` que salte produz **uma** entrada `skip` e faz desaparecer os
testes que cobre. O `check` só recusava `corridos == 0`, pelo que 5 testes numa
ordem e 3 na outra passavam como verde — e isso é **exactamente** o acoplamento
de ordem que o portão existe para apanhar, entregue como conforme.

```text
antes:  f_skip — 3 testes na ordem inversa, 0 vermelhos   rc=0   (dois nunca correram)
depois: f_skip — 3 teste(s) existem numa passagem e nao na outra (5 contra 2)   rc=1
```

### A-3 — dois casos com o mesmo `id()` colapsavam, e o segundo apagava o vermelho do primeiro

`estado` é indexado pelo `id()`, e o `id()` usa o `__module__` de **onde a
classe foi definida**. Uma `TestCase` em `base_partilhada.py` importada por dois
módulos — o padrão de bateria partilhada que este repositório já usa — dá o
mesmo `id()` duas vezes; com o `startTest` a escrever `'ok'`
incondicionalmente, o segundo apagava a falha do primeiro, e `corridos` era
`len(estado)` em vez de `testsRun`.

**Latente, não vivo:** `libs/py-core` tem 551 casos e 551 `id()` distintos. A
correcção é uma palavra e o mecanismo é real.

### C-1 — a mensagem de falha afirmava o que o `check` nunca media

O `check` corria **só** a ordem inversa e a queixa dizia «a ordem de omissão já
foi exigida verde pelo `coverage-python`». Um teste simplesmente quebrado —
vermelho nas duas ordens — era reportado como «passa por acidente da ordem de
carregamento», com o parágrafo do remédio a mandar limpar estado de processo.

### F2 (documental) — e é a mesma coisa vista do outro lado

As duas passagens **não diferiam só na ordem**: a de omissão era a do
`coverage-python`, sob `coverage run --branch`; esta não. E a prova de que isso
importa já estava escrita no ticket de onde este herda —
`../../specs/tickets/KAM-163.md` registra que **duas versões do mesmo ensaio
ficaram vermelhas sem nada ter mudado no código: uma pela ordem das classes,
outra pelo rastreador do `coverage`**. O ticket herdou o mecanismo e não herdou
a ressalva.

## 3. A correcção, que é uma e não cinco

O `check` passa a correr **as duas ordens**, cada uma no seu processo, nas
mesmas condições e sem `coverage` em nenhuma — pelo que a única coisa que
difere entre elas é a ordem, e uma diferença de resultado é dela. Custa uma
execução a mais por suite (~15 s no `libs/py-core`, ~145 s no `services/agr`) e
paga-se: sem ela o portão afirmava mais do que media.

E o veredicto passa a vir do `TestResult`:

```text
Resultado.corridos   testsRun          (nao len(estado))
Resultado.sucesso    wasSuccessful()   (o veredicto)
Resultado.relato     failures + errors + subfalhas, com traceback
Resultado.estado     o diagnostico por teste — com perdas, e agora cruzado
```

**A rede que não se tira:** se o `wasSuccessful()` disser que a ordem não passou
e a classificação por teste não nomear um único vermelho, o portão sai com
**2** e recusa o verde. Fecha A-1 e A-3, e fecha qualquer sinal que o
`unittest` acrescente no futuro — que é o que distingue corrigir o defeito de
corrigir os três sintomas.

> **E desde o KAM-182 a rede diz *quem*.** A primeira versão desta frase dizia
> que o portão «diz que o instrumento perdeu informação» — e dizia-o quando a
> informação **estava no processo**: medido a 2026-11-05 no *gate* 4 do PR
> `#137`, `corridos=1402, classificados=1402, sucesso=False`, com o `relato`
> impresso logo a seguir a levar o nome e o *traceback* do vermelho. O código
> de saída não mudou e a recusa não se negociou; o que mudou é que o
> `Resultado` passou a levar também o que o próprio `TestResult` acusa, e a
> **diferença** entre os dois conjuntos nomeia qual das três causas se
> verificou — `id()` repetido, sinal não derrubado, ou erro atribuído a um caso
> já fechado como verde. Quando não há `id()` de teste para nomear — o
> `_ErrorHolder` de um `tearDownModule`, cujo `id()` é uma frase — a saída
> continua a ser **2**. Ver `specs/tickets/KAM-182.md`.

Os achados dão quatro mensagens distintas, porque o remédio de cada um é outro
e um relatório que os misture manda corrigir a coisa errada:

| Achado | Saída | Para onde manda |
|---|---|---|
| verde na omissão, vermelho na inversa | 1 | o estado de processo que o teste suja |
| inventário diferente entre as ordens | 1 | o `SkipTest` de módulo ou de classe |
| vermelho nas duas ordens | 1 | o `coverage-python`; não é ordem |
| o `TestResult` discorda da classificação | 2 | o `corredor`; é falha do portão — e desde o KAM-182 a saída nomeia o caso e a causa |

## 4. Porque é que a suite do módulo não apanhou nada disto

**É a parte que vale mais do que a correcção.** Nenhum caso da suite fazia
passar um vermelho **através** do `Registo`: os que havia corriam combinações
que ficam verdes, ou construíam um `Resultado` à mão. Um *hook* em falta ou com
assinatura errada era invisível — e era exactamente isso o `addSubTest`.

Fechado com a *fixture* `tests/fixtures/sinais/`, um caso por sinal
(`ok`, `failure`, `error`, `skip`, `expected-failure`, `unexpected-success`,
`subTest`), e com `TestOsSinaisDoUnittest` a afirmar a classificação de cada
um, o `sucesso`/`corridos` vindos do `TestResult`, e que o relato traz
*traceback* em vez da cadeia de pontos.

## 5. Os achados menores, e o que se fez de cada um

| # | Achado | Disposição |
|---|---|---|
| F-1 | A cablagem do `relato` estava morta, e mesmo ligada dava `'.F'` — o `printErrors()` só é chamado pelo `TextTestRunner` | **Ligada**: o relato monta-se do `failures`/`errors`/`subfalhas`, com *traceback*, e sai no `stderr` do portão |
| F-2 | Os re-exports do `__init__.py` não tinham consumidor | **Removidos**; a razão ficou escrita no lugar deles |
| F-3 | O `Registo` herdava de `TextTestResult` por um fluxo que ninguém lia | Passa a herdar de `TestResult` |
| B-1 | O canário aceitava vermelhos **a mais** ao lado do declarado (pertença, não igualdade), contra o que a sua própria página promete | Passa a igualdade exacta |
| A-4 | Sem tecto, um filho pendurado mata o *job* no relógio do GitHub sem nada para ler — e a ordem inversa é precisamente a condição que torna um trinco latente em bloqueio | `TECTO_SEGUNDOS = 1800`, folga de vinte vezes, com saída 2 e a ordem nomeada |
| E-1 | O canário corria no `$(PYTHON)` e a medição no `$(VENV_PYTHON)`: a prova num interpretador, a medida noutro | **Um interpretador só**; a guarda do `.venv` passou para primeiro |
| E-2 | A ordem dos pré-requisitos do `ci-4` é assumida e não imposta (`make -j` corre-os em paralelo) | Deixou de ser carga: o `check` mede as duas ordens por si. A ordem fica por *fail-fast*, e o teste que a prende diz essa razão. Não há `-j` em parte nenhuma deste repositório |

## 6. Os achados documentais, e o que se fez de cada um

| # | Achado | Disposição |
|---|---|---|
| F1 | O §2 do `../ci.md` não ganhou o passo, e os **dois precedentes que o ticket invoca** estão escritos nessa mesma coluna | Corrigido na linha do *gate* 4 |
| F3 | «As duas propriedades estão presas por…» e a classe prendia outra | `test_as_fixtures_vivem_debaixo_de_tests` acrescentado; a terceira propriedade passa a estar presa |
| F4 | «Portão sobre si próprio» estava em **Testes Requeridos** e não é um teste que volte a correr | Movido para a tabela das execuções |
| F5 | A medição por sementes é irreproduzível com o que o PR entrega (`ORDENS` só tem duas) | Marcada **INDÍCIO**, com o instrumento do *scratchpad* nomeado |
| F6 | «Multiplicava-o» não sai dos números: acrescentar uma passagem a um lado que já paga outra tanto é **duplicar** | Reescrito com as duas razões, a do *gate* e a do alvo |
| F7 | O comando escrito na tabela não corre da raiz (`No module named`) | A precondição do `PYTHONPATH` ficou escrita na tabela |
| F8 | **Esta classe já apareceu antes do KAM-163**, na `ANALISE-26`/KAM-012, e a ocorrência vive nas suites de `db/` que o portão exclui | Nomeada no bloco, e a exclusão de `db/` passa a dizer que exclui a única ocorrência anterior conhecida |
| F9 | A metade **Node** do *gate* 4 não era nomeada no «o que fica de fora» | Nomeada, com a razão |
| F10 | «O `unittest` carrega os módulos pela ordem do disco» — não: `_find_tests` faz `sorted(os.listdir(...))` | Corrigido |
| F11 | Nenhuma caixa marcada e a tabela de verificação a dizer oito satisfeitas | As caixas com evidência passam a marcadas |
| F12 | A dívida 2 de `../dividas-documentais.md` nomeia o campo que este PR edita, e está paga | Riscada, com a medição |
| F13 | Os 1 911 s / 1 422 s | **MORTO** na adenda do próprio revisor: remediu-os e o factor é 0,76 suite a suite — a máquina dele é ~25% mais rápida, e as proporções batem |
| F14 | Os 1 361 testes do AGR | **PLAUSÍVEL**: não reproduz sem contentor, e é em contentor que a linha diz que foi medido |
| F15 | A enumeração do §1 do `INDICE` e a dívida 4(b) | Verificado e deixado: a dívida é **auto-datada** por escrito («a omissão cresce a cada ticket novo»), e o número que cita é uma medição de 2026-10-28 |

## 7. O que as duas revisões mataram, e vale dizer

- **A contiguidade das classes sob inversão** — não é só afirmada, está medida:
  `libs/py-core` dá 100 blocos de classe para 100 classes distintas e 18 blocos
  de módulo para 18 módulos distintos, **nas duas ordens**. O `setUpClass` e o
  `setUpModule` continuam a correr uma vez.
- **As *fixtures* no denominador da cobertura** — morto por uma razão mais forte
  do que o `--omit`: o `EXTENSOES_DO_UNIVERSO` do `../../tools/coverage_gate.py`
  não tem `.py`, pelo que **nenhum** ficheiro Python pode entrar a 0%. O
  `--omit` e o `excluidos` do `ci/thresholds.yaml` são a segunda e a terceira
  barreira.
- **As *fixtures* descobertas pelas suites reais** — 45 `id`s, zero com
  `caso_`, zero `_FailedTest`.
- **A cablagem do `ci-4` não presa** — provada **por mutação**: cortar o
  pré-requisito deixa o `test_makefile.py` e o `lint_arch` verdes e faz a suite
  deste módulo vermelha em dois testes.
- **Testes assíncronos partidos pela inversão** — 1 361 verdes; cada teste traz
  o seu *event loop*.
- **A duplicação com o `../../tools/env_lint/canario.py` e o
  `../../db/correr_suite.py`** — partilham a **forma**, não o código. Extrair um
  `Caso` comum dava uma abstracção com dois utilizadores que não partilham um
  campo além de `codigo` e `descricao`.

## 8. Contagem

| | Código | Documental |
|---|---|---|
| Candidatos perseguidos | 21 | 25 |
| CONFIRMADO | 9 | 12 |
| PLAUSÍVEL | 5 | 2 |
| MORTO | 7 | 11 |

**Vinte e um `CONFIRMADO` corrigidos.** Os `PLAUSÍVEL` ficam nesta página com o
que falta para os decidir; nenhum deles bloqueia, e o `A-4` foi corrigido de
qualquer modo porque o remédio era uma linha.

## 9. O que fica em aberto, nomeado

| # | O quê | Onde |
|---|---|---|
| 1 | `../../libs/py-core/tests/integracao/` **não tem `__init__.py`**, pelo que o `unittest discover` nunca lá desce: o `test_storage_s3real.py` não está nos 551 do portão **nem** no universo que o `coverage-python` mede. **Anterior a este PR** | fora de âmbito; achado da revisão de código |
| 2 | As 19 suites de `tools/*/tests` e as de `db/` ficam fora do portão, por custo medido | `shortcut:` do alvo `ordem-dos-ensaios`, revisto até 2026-12-03 |
| 3 | A metade **Node** do *gate* 4 não tem verificação equivalente: o `node --test` tem a sua própria ordem e é outro instrumento | nomeada no bloco do KAM-173 |
| 4 | A varredura das 18 suites de `tools/` é **INDÍCIO**: as duas passagens de cada uma correram com a árvore a mexer-se | bloco do KAM-173 |

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-173): as duas revisões adversariais do PR `#109`, com 21 `CONFIRMADO` corrigidos. O defeito que bloqueava era um só — o veredicto derivado de um `dict` com perdas em vez do `TestResult` — com três sintomas reproduzidos, o pior a cobrir 332 usos de `subTest` em 55 ficheiros. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **KAM-182: a rede passa a nomear, e não só a recusar.** A frase da «rede que não se tira» dizia que o portão declara ter perdido a informação; era falsa, porque a informação estava no processo — medido a 2026-11-05 no *gate* 4 do PR `#137` (`corridos=1402, classificados=1402, sucesso=False`, com o nome e o *traceback* no `relato` logo abaixo). O código de saída continua **2** e a recusa não se negociou; o `Resultado` ganhou o que o próprio `TestResult` acusa, e a diferença entre os dois conjuntos nomeia qual das três causas se verificou. Sem `id()` de teste para nomear (o `_ErrorHolder` de um `tearDownModule`), continua **2**. | Equipa KAMBÁ |

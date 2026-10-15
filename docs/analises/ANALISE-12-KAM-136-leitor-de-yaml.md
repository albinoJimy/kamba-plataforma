# ANÁLISE-12 — Revisão adversarial do KAM-136 (leitor de YAML sem silêncios)

| Campo | Valor |
|---|---|
| Ticket | KAM-136 — Dois erros de leitura silenciosos do `tools/kamba_yaml.py` |
| Ramo | `feature/KAM-136-leitor-de-yaml-sem-silencios` (PR `albinoJimy/kamba#36`) |
| *Baseline* revista | `7015cbf` (`origin/main`) |
| Data | Outubro 2026 |
| Revisão | Um subagente independente, com os requisitos e o código e **sem** as justificações de quem escreveu a alteração |

> **Nota sobre a numeração.** O *handoff* deste ticket atribuiu
> `ANALISE-11-KAM-136-leitor-de-yaml.md`, mas o `ANALISE-11` já existe em `main`
> desde o KAM-068 (`443dc8f`), citado sete vezes em `docs/logs.md` e duas em
> `specs/EPIC-07`. Tomou-se o número livre seguinte, **12**, e o conflito está
> no relatório final. Se um dos tickets que correm em paralelo nesta vaga tiver
> levado o 12, renumera-se na integração, como as linhas de versão.

---

## 1. O que esta revisão procurou

A premissa do módulo é **«recusa o que não entendes»**, e é essa premissa que o
torna confiável para os nove *gates* que o leem. O ticket nomeia dois casos que
fazem o contrário — leem mal e não dizem nada — e manda varrer o módulo à
procura de mais da mesma classe.

Por isso a revisão não perguntou «está certo?». Perguntou:

- Que construção é que o leitor **continua** a engolir em silêncio?
- Que recusa nova recusa **de mais** — uma forma legítima que os ficheiros reais
  usam, ou poderiam ganhar amanhã?
- A equivalência «antes e depois» mede o que diz medir, ou está verde por
  construção?
- Algum teste passa pela **razão errada** — está verde mesmo com o defeito
  presente?
- A recusa chega a quem chama como erro de configuração, ou como achado?

## 2. A varredura, caso a caso

**101 construções**, cada uma corrida contra o leitor em `origin/main` (a cópia
congelada `tools/lint_arch/tests/leitor_antes_do_kam136.py`) **e** contra o
actual, e classificada pela diferença entre as duas saídas. A classificação é
da máquina, não da leitura.

| Classe | Quantos |
|---|---|
| Já recusava | 20 |
| Já lia bem | 20 |
| **Lia mal em silêncio → passou a recusar** | **46** |
| **Lia mal em silêncio → passou a ler bem** | **10** |
| **Recusava de mais → passou a ler** | **5** |
| | **101** |

As subsecções abaixo descrevem as 61 construções da primeira varredura; as 40
que a revisão independente acrescentou estão no §4, uma linha por achado, com a
disposição.

### 2.1 Já recusava — coberto, nada a fazer

| Caso | Mensagem |
|---|---|
| âncora (`chave: &a valor`) | `ancora nao suportado ('&')` |
| *alias* (`b: *x`) | `alias nao suportado ('*')` |
| âncora em item de lista | `ancora nao suportado ('&')` |
| *merge key* (`<<:`) | `ancora`/`merge key` |
| mapa em fluxo (`{a: 1}`) | `mapa em estilo de fluxo nao suportado ('{')` |
| mapa vazio em fluxo (`{}`) | idem |
| lista em fluxo com conteúdo (`[a, b]`) | `lista em estilo de fluxo com conteudo nao suportada` |
| *tag* (`!!str 1`) | `tag nao suportado ('!')` |
| directiva (`%YAML 1.2`) | `esperava 'chave: valor'` |
| documentos múltiplos (`---`) | `documentos multiplos nao suportados` |
| fim de documento (`...`) | `fim de documento ('...') nao suportado` |
| tabulação na indentação | `tabulacao na indentacao` |
| chave repetida no mapa | `chave repetida 'a'` |
| chave repetida no item de lista | `chave repetida no item` |
| lista ao nível da chave (`a:` + `- x`) | `chave sem valor nem bloco` |
| documento de topo que é lista | `conteudo nao consumido` |
| escalar dobrado sem conteúdo | `escalar dobrado sem conteudo` |
| cadeia que começa por `#` **sem aspas**, em mapa | `chave sem valor nem bloco` (o `#` é comentário, como em YAML) |
| cadeia que começa por `#` **sem aspas**, em item de lista | `indentacao inesperada` |

### 2.2 Já lia bem — correcto, agora com teste

`null`, `~`, `#` dentro de aspas, `[]`, data (`2026-10-12` → cadeia), versão de
três partes (`1.83.0` → cadeia), etiqueta com sufixo (`0.8.7-pg18` → cadeia),
inteiro com sinal (`+5` → `5`), inteiro com zeros à esquerda (`007` → `7`), item
citado com dois pontos (`- "a: b"` → cadeia), valor plano com dois pontos
(`razao: a: b` → cadeia), tabulação depois dos dois pontos, apóstrofo em texto
plano, apóstrofo com comentário, escalar dobrado na posição de mapa, comentário
desindentado a seguir à dobra, `...` indentado, e **as cadeias que começam por
`#`**: `chave: "#abc"`, `chave: '#abc'` e `- "#abc"` leem-se, e `chave: a#b`
mantém o `#` (não há espaço antes, logo não é comentário). O ticket nomeia esta
família na varredura, e passou a ter teste próprio.

### 2.3 Liam mal em silêncio e passaram a recusar

| Caso | O que lia antes | Porque se recusa, e não se interpreta |
|---|---|---|
| `>` como `>-` | o texto dobrado sem a linha final | O `>` (*clip*) guarda uma linha final que este leitor não preserva. Implementar o *chomping* é uma regra nova; recusar é uma linha |
| `>+` como `>-` | idem | O `+` (*keep*) preserva **todas** as linhas finais em branco. O `_Linhas` descarta-as antes de o parser as ver |
| `#` dentro de escalar dobrado | `"texto com"` — o resto desaparecia | Em YAML o `#` dentro de um bloco é conteúdo. O `_sem_comentario` corre linha a linha, antes de se saber se a linha é conteúdo de bloco; ensiná-lo a saber é reordenar o parser |
| linha vazia dentro da dobra | `"a b"` em vez de `"a\nb"` | Uma linha vazia dentro de um bloco é uma quebra de parágrafo (`\n`); aqui virava um espaço |
| linha comentada ao nível do conteúdo da dobra | desaparecia | Em YAML é conteúdo |
| indentação irregular dentro da dobra | juntava tudo com espaços | Em YAML, uma linha **mais** indentada dentro de um `>` deixa de ser dobrada e passa a literal. Duas regras, duas formas de ficar errado |
| aspa dupla aberta e não fechada | a aspa entrava no texto (`'"abre e nao fecha'`) | YAML dá erro |
| aspa simples aberta e não fechada | idem | idem |
| conteúdo depois da aspa de fecho (`"a" extra`) | `'"a" extra'` como texto | YAML dá erro |
| duas partes citadas (`"a" "b"`) | `'a" "b'` — tirava a primeira e a última aspa | YAML dá erro |
| `#` depois de uma aspa aberta e não fechada | o comentário entrava no valor | **Não se sabe** se o `#` é comentário ou conteúdo. Adivinhar é o defeito que este ticket fecha |
| decimal (`1.5`) | a cadeia `"1.5"` | É um **limiar**. Uma comparação com uma cadeia rebenta longe do sítio onde o erro está, ou — pior — passa |
| exponente (`1e3`) | cadeia | idem |
| hexadecimal (`0x1f`) | cadeia | idem |
| separador de milhares (`1_000`) | o inteiro `1000` — o `int()` do Python aceita-o | O YAML não resolve `1_000` como inteiro. Era o leitor a ser **mais** permissivo do que o YAML, na direcção errada |
| `.inf` | cadeia | idem |
| `.nan` | cadeia | idem |
| `True` | a cadeia `"True"` | O YAML 1.2 *core* resolve `True` como booleano. Um `obrigatorio: True` lido como texto é verdadeiro em Python por acidente (`bool("True")`), não por leitura |
| `FALSE` | cadeia `"FALSE"` | O YAML 1.2 *core* resolve-o como **falso**; a cadeia é **verdadeira** em Python. O pior caso possível |
| `yes` / `no` | cadeia | Booleanos em YAML 1.1. O ficheiro não declara versão de YAML; escolher uma em silêncio é a decisão que não se toma |
| `on` / `off` | cadeia | idem |
| `NULL` | cadeia `"NULL"` | O YAML 1.2 *core* resolve-o como nulo |
| `None` | cadeia `"None"` | Não é YAML, é Python. Quem o escreve espera nulo |
| lista aninhada (`- - a`) | a cadeia `"- a"` | Uma sequência dentro de uma sequência. Suportá-la é estrutura nova |

### 2.4 Liam mal em silêncio e passaram a ler bem

| Caso | Antes | Depois | Porque se interpreta, e não se recusa |
|---|---|---|---|
| **Caso 1 do ticket** — `>-` como primeira chave de um item | o item ficava com uma chave e as outras dentro do texto | o item tem todas as chaves | O defeito era `indentacao_chave - 1`, não uma regra em falta: a dobra já existia e já estava certa na posição de mapa, duas linhas acima. Recusar seria recusar uma forma que o leitor lê bem no mapa e mal na lista |
| **Caso 2 do ticket** — item não citado com `:` | `- https://x` → `{"https": "//x"}` | a cadeia `"https://x"` | É o que o YAML diz e o que o autor quis. Nenhuma outra forma substitui a cadeia sem aspas. O mesmo `:` em posição de **mapa** passa a recusa |
| apóstrofo a meio de um texto plano antes de um `#` | o comentário entrava no valor | o comentário é cortado | Em YAML, uma aspa só abre uma cadeia citada onde um escalar pode começar (início da linha, depois de `:`, depois de `-`). O `_sem_comentario` tratava qualquer apóstrofo como aspa aberta |
| algarismos não-ASCII (`١٢٣`) | o inteiro `123` | a cadeia `"١٢٣"` | `int()` aceita algarismos Unicode; o YAML resolve inteiros só com `[0-9]`. A conversão passou a `re.fullmatch` |

### 2.5 Três casos que não são construções

| Caso | Antes | Depois |
|---|---|---|
| ficheiro que não é UTF-8 | `UnicodeDecodeError` **não tratado** (o `UnicodeDecodeError` não é `OSError`): o *gate* morria com *traceback* e código 1 | `YamlSubsetError` com o nome do ficheiro → erro de configuração, código 2 |
| `ci_waivers` devolvia 1 para uma recusa do leitor | código 1 — «encontrei achados», quando não chegou a ler nada | código 2, por `ConfiguracaoIlegivel` |
| `supply_chain egress` devolvia 1 (achado `egress-invalido`) | código 1 — e **um achado dispensa-se com um *waiver* do *gate* 11** | código 2, por `ConfiguracaoInvalida` (achado D1, §4) |

## 3. O que se procurou e **não** se encontrou

Dito explicitamente, porque uma revisão que não lista o que descartou está a
esconder o âmbito:

- **Dependências novas:** nenhuma. O módulo importa `re` e `pathlib`. O
  `tempfile` entra só no ficheiro de testes, e a revisão independente provou por
  execução que o módulo carrega num interpretador sem `site-packages`.
- **Ficheiros `ci/*.yaml` reescritos para contornar o leitor:** nenhum. O
  `git diff --stat origin/main` não lista nada em `ci/`.
- **Recusas que recusam de mais:** nenhuma sobre os ficheiros reais
  (`test_todos_os_ficheiros_reais_se_leem`, 22 ficheiros descobertos por *glob*)
  — e a revisão independente confirmou-o com a sua própria comparação. **Cinco
  recusas que já recusavam de mais antes deste ticket** foram desfeitas (§4: B1,
  B2, B4, B7). A que fica está nomeada no §6.
  As formas que as recusas novas apanham foram verificadas por `grep` nos 22
  ficheiros **antes** de se decidir recusar: zero ocorrências de `>` ou `>+`
  nus, zero de `chave:valor` sem espaço, zero de valores que pareçam número e
  não sejam inteiro decimal, zero de booleanos ambíguos (os 11 `true`/`false`
  dos 22 ficheiros são todos minúsculos; os 60 e tantos de
  `ops/secrets-inventory.yaml` também, mas esse ficheiro tem outro leitor).
- **Mudança de leitura de um limiar ou de uma excepção:** nenhuma. 0
  divergências em 2 221 campos folha. É isto que mantém a condição dos «2
  revisores» do DoD fora de jogo.

## 4. Achados da revisão independente

Um subagente recebeu os requisitos e o código, **nunca as justificações** de
quem escreveu a alteração, e foi mandado procurar o que o leitor **continua** a
engolir em silêncio além dos dois casos do bloco. Instalou PyYAML 6.0.3 no
*venv* de recurso para ter um oráculo de YAML a sério, usou-o em todos os casos
e desinstalou-o no fim. **Veredicto dele: não integrar, 2 bloqueadores.**

Estava certo. **Cada achado foi reproduzido por quem escreveu o código antes de
ser corrigido** — a tabela abaixo tem os **28 achados** e as **4 notas**, uma
linha cada (o A9 junta as suas três partes, o C8 e o C9 partilham linha, e a
NOTA-4 partilha com o D2), com a disposição de todos, incluindo os que se
recusam a corrigir e porquê.

| # | Achado | Classe | Verificado | Disposição |
|---|---|---|---|---|
| A1 | **Comentário ou linha vazia como *primeira* linha de um `>-` desaparecia sem erro.** `razao: >-` seguido de `# ver ADR-014` e do texto dava só o texto | BLOQUEADOR | sim — reproduzido nas cinco variantes, incluindo o *waiver* completo | **corrigido.** Era o mesmo defeito de fronteira do caso 1, no outro extremo do bloco: a varredura das linhas descartadas usava a primeira linha **de conteúdo** como limite inferior, e não a linha do indicador. Passa a receber o número da linha do `>-`. Fecha também A9(c) |
| D1 | **`supply_chain egress` devolvia 1, não 2** — e a evidência §5 afirmava 2 | BLOQUEADOR | sim — `python -m supply_chain --root <tmp> egress` → `EXIT=1`; agora `EXIT=2` | **corrigido.** O `egress.py` convertia o `YamlSubsetError` num achado `egress-invalido`; as `imagens` e as `licencas` ao lado já levantavam `ConfiguracaoInvalida`. Um achado dispensa-se com um *waiver* do *gate* 11, um erro de configuração não — e é o que o próprio `base.ConfiguracaoInvalida` escreve. Um caso do `test_formas_invalidas` passou a teste próprio |
| A2 | **`017` → 17, `0644` → 644.** Octal em YAML 1.1, decimal em 1.2 | IMPORTANTE | sim | **corrigido**, por recusa. É exactamente a ambiguidade 1.1/1.2 que o `_AMBIGUOS` existe para recusar, e aqui o módulo escolhia — e escolhia um **número errado**, não um texto. `0[0-9][0-9_]*` entrou no `_PARECE_NUMERO`, e o `_INTEIRO` passou a `(0\|[1-9][0-9]*)`. Zero ocorrências nos ficheiros reais (verificado por `grep` antes de decidir) |
| A3 | **`1:30` → `'1:30'`**, sexagesimal em YAML 1.1 | IMPORTANTE | sim | **corrigido**, por recusa, pela mesma razão. Zero ocorrências nos ficheiros reais |
| A4 | **`razao: a - "b # c"` guardava o comentário dentro do valor.** O `_comeca_escalar` aceitava qualquer `-` ou `:` anterior como início de escalar, e o hífen é pontuação corrente nestes textos | IMPORTANTE | sim, e o inverso também (`razao: a - 'b # c` era recusado) | **corrigido**, e passou a ler bem. O `_inicio_do_escalar` calcula agora **a posição** onde o escalar começa (depois da indentação, dos `- ` e do `:` da chave) e só uma aspa nessa posição abre uma cadeia citada. As duas leituras passaram a coincidir com o PyYAML |
| A5 | **`CR` sozinho não era quebra de linha**: `a: 1\rb: 2` dava `{'a': '1\rb: 2'}` | IMPORTANTE | sim | **corrigido**, e passou a ler bem: o YAML 1.2 §5.4 diz que `CR` sozinho é quebra de linha. O `NEL`, o `U+2028` e o `U+2029` — quebras em 1.1 e não em 1.2 — passam a **recusa**, pela regra do `_AMBIGUOS` |
| A6 | **Escapes em aspas duplas ficam literais** (`"a\nb"` → cinco caracteres) | IMPORTANTE | sim | **não corrigido, e escrito.** Não é uma leitura silenciosa: é a semântica de que o `tools/dict_export/exportar.py` depende (`_texto` escolhe a aspa que o texto não contém e recusa o que contenha as duas), e a verificação de ida-e-volta do `render` prova que quem escreve e quem lê concordam. Recusar o `\` quebraria o `dict_export` por um `\` numa descrição do dicionário, e o revisor também não mediu esse risco. O *docstring* passa a dizer que é um **desvio do YAML** e porquê. Uma aspa escapada (`\"`) cai na recusa de «conteúdo depois da aspa de fecho», agora com a mensagem a nomear o caso |
| A7 | **`.strip("\"'")` mutilava chaves citadas**: `"a'"` ficava `a`, `"''"` ficava vazia | MENOR | sim | **corrigido.** Entrou `_nome_da_chave`, que tira **um** par de aspas |
| A8 | **Caracteres de controlo aceitos**: `\x00`, `\x1b`, e um *form feed* a contar como indentação 0 | MENOR | sim | **corrigido**, por recusa (YAML 1.2 §5.1) |
| A9 | (a) `- a:\tb` aceito; (b) **`razao: a: b` aceito** onde o YAML dá erro; (c) primeira linha do bloco mais indentada | MENOR | sim, os três | (b) **corrigido**, por recusa: um escalar não citado com `: ` ou acabado em `:` passa a erro, e a mensagem diz que o YAML também o recusa. Zero ocorrências nos ficheiros reais. (c) fechado por A1. (a) **não corrigido**: um `TAB` depois do `:` é espaço válido em YAML e a leitura (`'b'`) é a correcta; o `ScannerError` do PyYAML é da sua própria análise de *tokens*, não da especificação |
| B1 | **BOM UTF-8 recusado**, com mensagem que mandava procurar um erro de sintaxe inexistente | IMPORTANTE | sim | **corrigido**: o BOM é permitido no início do *stream* (YAML 1.2 §5.2) e passa a ser ignorado. Era a recusa com o pior custo: qualquer editor do Windows que grave «UTF-8 with BOM» matava o *gate* |
| B2 | **`---` como marcador de *um* documento recusado como «documentos múltiplos»** | IMPORTANTE | sim, e `--- # doc` dava uma mensagem ainda pior | **corrigido**: um `---` na coluna 0 antes de haver conteúdo é o marcador de início e aceita-se; um segundo `---` continua a ser recusado, e agora é esse o caso que o teste cobre |
| B3 | **`''` e `\"` dentro de aspas recusados com mensagem que não diagnostica** | IMPORTANTE | sim | **corrigido só na mensagem.** Interpretar `''` seria uma regra nova, e o módulo recusa o que não entende; mas a mensagem passa a nomear o caso e a dizer a saída (usar a outra aspa). Um `razao` com apóstrofo escreve-se hoje com aspas duplas, e funciona |
| B4 | **`---` e `...` recusados onde são conteúdo** (indentados, dentro de um `>-`) | MENOR | sim | **corrigido**: os marcadores só contam na coluna 0 |
| B5 | **`None` recusado como «ambíguo» sem o ser** — nenhuma versão do YAML o resolve, e o comentário do `_AMBIGUOS` afirmava que todos se resolvem | MENOR | sim | **mantém-se a recusa; corrigiu-se o comentário.** Quem escreve `None` espera nulo, e dar-lhe a cadeia `"None"` (verdadeira em Python) é o mesmo género de surpresa que o `FALSE`. O comentário passa a dizer que esta é a excepção e porquê |
| B6 | `>` e `>+` recusados | MENOR | — | **mantém-se**, é a decisão do ticket e está escrita. O custo cai sobre quem escreve o ficheiro, e é por isso que a mensagem diz o que fazer |
| B7 | **`a: [ ]` recusado quando `a: []` passa** | MENOR | sim | **corrigido** |
| B8 | Recusas largas pré-existentes (lista ao nível da chave, nulo implícito, listas de listas, escalar plano em várias linhas) | NOTA | — | **fora de âmbito**, todas documentadas e anteriores ao ticket. Registado aqui porque «é aqui que estão as próximas surpresas» |
| C1 | **O canário do caso 1 passa com o defeito presente** — não distingue os dois estados do mundo | IMPORTANTE | sim, medido com o leitor congelado: `suspeitos = []` nos dois | **corrigido no *docstring*, não no teste.** O teste fica, porque passa a discriminar no dia em que um ficheiro real ganhar a forma; mas o *docstring* passa a dizer que **não é um discriminador hoje**, e a nomear quem discrimina (a equivalência e o `TestCaso1DoKam136`) |
| C2 | **`007` → 7 era o único caso da família que não podia falhar** (0–7 é onde octal e decimal coincidem) | IMPORTANTE | sim | **corrigido**: com A2, `007` passou de `LEEM` para `RECUSAM`, e entraram `017`, `0644`, `008` e `-010`. O `LEEM` fica com `0`, que é inteiro em qualquer leitura |
| C3 | **`LEEM["valor plano com dois pontos"]` afirmava «lê bem» sobre YAML inválido** | IMPORTANTE | sim | **corrigido** com A9(b): passou para `RECUSAM`. O revisor tem razão no fundo — numa tabela cuja promessa é «lê bem ou recusa», «aceita o que o YAML recusa» é um terceiro estado que não devia existir |
| C4 | **O *docstring* tinha duas afirmações falsas**, e a lista verdadeira é um critério de aceitação explícito | IMPORTANTE | sim, as duas | **corrigido.** (1) «algarismos não-ASCII» estava na lista do que **recusa** e são lidos como texto — a linha saiu; (2) a garantia de que dentro de um `>-` se recusa linha vazia e `#` era falsa para a primeira linha (A1). O *docstring* passa a dizer «em qualquer posição do bloco, incluindo antes da primeira linha de conteúdo», e a registar que esta lista já mentiu uma vez |
| C5 | **`RECUSAM["documentos multiplos"]` usava um documento único** | MENOR | sim | **corrigido**: o caso passou a dois documentos a sério, e o documento único foi para `LEEM` (B2) |
| C6 | **As guardas do teste de equivalência medem menos do que parecem**: `campos > 1000` é satisfeito pelo `canon/dicionario.yaml` sozinho; o `_folhas` não produz par para um mapa vazio; e colide `{"a": {"b": 1}}` com `{"a.b": 1}` | MENOR | sim | **corrigido**: o caminho passou a **tuplo** em vez de texto (sem colisão), um mapa vazio produz o seu par, o limiar subiu, e acrescentou-se a exigência de que os seis `ci/*.yaml` que o ticket nomeia estejam **mesmo** na comparação |
| C7 | **O *docstring* do `TestRecusaEhErroDeConfiguracao` afirmava que os outros oito devolvem 2** — falso por D1 | MENOR | sim | **corrigido** com D1, e a tabela da evidência passou a dizer quais estão provados por execução e quais por leitura |
| C8/C9 | Etiqueta ilegível no `subTest` (`molde[:3]`); `import tempfile` repetido | NOTA | sim | **corrigidos** |
| NOTA-1 | A árvore estava a ser editada durante a revisão, e uma corrida intermédia deu falhas que não eram defeitos | NOTA | — | **aceite**, com a lição: o revisor fixou um instantâneo e reverificou tudo contra ele, o que é o comportamento certo. Os `md5` que ele registou são do instantâneo que auditou, anterior às correcções desta tabela |
| NOTA-2 | O oráculo congelado estava fora do índice no início da revisão, e a *suite* não importava num clone limpo | NOTA | — | **resolvido durante a revisão** (entrou no primeiro *commit*). Registado para não voltar a sair |
| NOTA-3 | `tools/kamba_yaml.py` com CRLF na árvore de trabalho | NOTA | sim | **resolvido**: era dos *scripts* de mutação a reescrever o ficheiro sem `newline="\n"`. Os *scripts* passaram a fixar LF |
| NOTA-4 / D2 | Existe um segundo leitor de subconjunto de YAML (`secrets_inventory/yamlsubset.py`); e a `ANALISE-12` era citada e não existia | NOTA | sim | **são **três**, não dois** — o revisor não viu o `canon_lint/yamlreg.py`. Registado como lacuna 22 de `../ci.md` §7, com ticket sugerido. A `ANALISE-12` é este ficheiro, que não existia quando ele leu |

### O que a revisão independente mudou, em números

| | Antes da revisão | Depois |
|---|---|---|
| Construções classificadas | 61 | **101** |
| Leituras silenciosas fechadas | 28 | **56** |
| Recusas que recusavam de mais, desfeitas | 0 | **5** |
| Casos no quadro `RECUSAM` | 41 | **64** |
| Casos no quadro `LEEM` | 18 | **29** |
| Testes do `kamba_yaml` | 38 | **39** (com mais 36 subcasos) |
| Mutações do módulo, todas apanhadas | 10 | **19** |
| Consumidores a devolver 1 numa recusa | 1 (corrigido) | **2** (corrigidos) |
| Linhas falsas no *docstring* | 2 | **0** |
| Testes verdes pela razão errada, encontrados | 0 | **2** (C1 e as quebras ambíguas) |

## 5. Veredicto

**Integra-se.** Dos **28 achados** (2 bloqueadores e 26), **23 foram corrigidos**
e **5 mantêm-se com a razão escrita**: A6 (escapes literais, de que o
`dict_export` depende), A9a (o `TAB` depois de `:`, onde a leitura é a correcta),
B5 (a recusa do `None` mantém-se; o comentário que a justificava mal é que
mudou), B6 (`>` e `>+`, decisão do ticket) e B8 (recusas largas anteriores a este
ticket). As 4 notas estão resolvidas ou registadas. Fica também escrita no
*docstring* uma recusa que recusa de mais e que não se fechou: a linha de
conteúdo de um escalar dobrado que começa por uma aspa não fechada e tem um
` #` depois.

Duas coisas ficam ditas sem adornos:

- **A primeira versão desta correcção não cumpria o objectivo do ticket.** O
  A1 é da mesma família do caso 1 — um defeito de fronteira num intervalo — e
  passou por quem escreveu o código, por 38 testes e por um teste de
  equivalência sobre 22 ficheiros reais. O que o apanhou foi uma revisão com um
  oráculo de YAML a sério e sem acesso às justificações. É a frase da *skill* a
  acontecer: *um agente produz evidências; não produz a verdade*.
- **O *docstring* mentia em duas linhas, e o critério de aceitação 6 pede
  exactamente que não minta.** Uma lista de garantias que não é verificada linha
  a linha é um enfeite. Agora cada linha tem um teste, e a lista diz que já
  mentiu uma vez.

## 6. O que **não** foi verificado

- **A mutação `kam136 identidade: as chaves seguintes do item deixam de entrar`
  não correu nesta máquina.** A linha de base de `tests_identidade` fica
  vermelha aqui (`Cannot find package 'pg'`: não há Node nem `node_modules` no
  *host*), e o corredor recusa-se a contar sobre uma linha de base vermelha —
  que é o comportamento certo. Corre na tarefa nocturna do KAM-143.
- **O código de saída 2 está provado por execução ou por teste em oito dos dez
  consumidores.** O `dict_export` e o `lint_refs` ficam por leitura do caminho
  de erro: a raiz temporária que seria preciso montar para eles morre antes de
  chegar ao leitor (o `lint_refs` corre `git ls-files`; os dois leem primeiro
  `specs/INDICE.md` e `specs/02_Dicionario_de_Dados_Canonico.md`). O quadro está
  em `../evidencia/KAM-136.md` §5. **Foi exactamente a linha «verificado por
  leitura» da versão anterior desse quadro que escondeu o defeito do
  `egress`** — e é a razão para o dizer aqui em vez de o deixar implícito.
- **Uma recusa que recusa de mais, conhecida e aceite.** Uma linha de conteúdo
  de um escalar dobrado que comece por uma aspa, não a feche, e tenha um ` #`
  depois é recusada; o YAML leria aquilo como texto. Os comentários tiram-se
  linha a linha, antes de se saber se a linha é conteúdo de bloco, e saber isso
  exigia reordenar o leitor. A recusa é alta e diagnostica. Está no *docstring*.
- **O `TAB` depois de `:` (A9a) não foi tratado.** O PyYAML dá `ScannerError`
  para `- a:\tb`; o módulo lê `'b'`, que é o que a especificação diz (um `TAB`
  é espaço válido ali). A divergência é da análise de *tokens* do PyYAML, não da
  especificação, mas não se mediu contra outro parser.
- **`make ci` não correu nesta máquina** — não há `make` nem Node no *host*.
  Correu-se cada *suite* de Python dos consumidores à mão (evidência §6) e os
  nove *gates* correm no CI do PR.
- **Os outros dois leitores de subconjunto de YAML não foram varridos:**
  `tools/canon_lint/yamlreg.py` e `tools/secrets_inventory/yamlsubset.py`. Está
  fora do âmbito deste ticket, que nomeia um módulo, e está registado como
  lacuna 22 de `../ci.md` §7.
- **Não se comparou com um parser de YAML a sério.** Não há PyYAML no *host* e
  instalá-lo contrariaria a razão de existir do módulo. As afirmações sobre o
  que o YAML faz estão fundamentadas na especificação (YAML 1.2, esquema
  *core*), não medidas. Onde a diferença entre YAML 1.1 e 1.2 importa — os
  booleanos `yes`/`no`/`on`/`off` — a decisão foi **recusar**, precisamente para
  não escolher uma versão que ninguém declarou.

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: a varredura dos 101 casos (61 na primeira passagem) e os 28 achados da revisão independente do KAM-136, com a disposição de cada um. | Equipa KAMBÁ |

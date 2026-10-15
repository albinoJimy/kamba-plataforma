# ANÁLISE-13 — Revisão adversarial do KAM-148 (os outros dois leitores de YAML)

| Campo | Valor |
|---|---|
| Ticket | KAM-148 — Leituras silenciosas nos outros dois leitores de YAML (`yamlreg` e `yamlsubset`) |
| Ramo | `feature/KAM-148-varredura-dos-outros-dois-leitores`, empilhado no `feature/KAM-136-leitor-de-yaml-sem-silencios` (PR `albinoJimy/kamba#PR_KAM144`) |
| *Baseline* revista | O ramo do KAM-136, que é a base deste |
| Data | Outubro 2026 |
| Revisão | Um subagente independente, com os requisitos e o código e **sem** as justificações de quem escreveu a alteração |

---

## 1. O que esta revisão procurou

A premissa dos três leitores de subconjunto de YAML é **«recusa o que não
entendes»**, e é ela que os torna confiáveis para os *gates* que leem por eles.
O KAM-136 fechou essa classe de defeito num; este ticket foi varrer os outros
dois. Por isso a revisão não perguntou «está certo?». Perguntou:

1. Que construção é que cada leitor **continua** a engolir em silêncio — fora do
   corpus que o ticket escreveu?
2. Que recusa nova recusa **de mais**: uma forma legítima que o
   `ops/secrets-inventory.yaml` usa, ou que os `registry/*.yaml` vão usar quando
   o EPIC-03 os escrever (`docs/tecnica/02` §5.1)?
3. A equivalência «antes e depois» mede o que diz medir, ou está verde por
   construção — com um corpus vazio ou um oráculo que já não tem os defeitos?
4. Algum teste passa pela **razão errada** — verde com o defeito presente, ou a
   recusar por outra regra que não a que diz estar a provar?
5. A recusa chega a quem chama, e **bloqueia**?
6. A lista do que cada leitor recusa, nos *docstrings*, é **verdadeira**? (No
   KAM-136, duas linhas dessa lista estavam falsas.)
7. Algum número escrito na evidência, no `docs/ci.md` ou no bloco do epic não
   corresponde ao que a máquina devolve?
8. Algum documento do conjunto fica a contradizer outro?

## 2. A varredura revista

| Leitor | Construções | Já recusava | Já lia bem | Silêncio → recusa | Silêncio → lê bem | Recusava de mais → lê |
|---|---|---|---|---|---|---|
| `tools/canon_lint/yamlreg.py` | 131 | 35 | 38 | 49 | 9 | — |
| `tools/secrets_inventory/yamlsubset.py` | 109 | 28 | 27 | 47 | 5 | 2 |
| **Total** | **208** | 57 | 56 | **83** | **12** |

A classificação é da máquina: cada construção corre contra a cópia congelada do
leitor anterior e contra o actual, e a classe sai da diferença. A tabela
construção a construção está em
[`../evidencia/KAM-148.md`](../evidencia/KAM-148.md) §10, e o corpus é o mesmo
que os testes permanentes usam.

## 3. Antes da revisão independente: o que a prova por mutação já tinha apanhado

Três buracos no corpus, nenhum deles encontrado por leitura:

| Mutação que sobreviveu | O que faltava |
|---|---|
| A verificação de chave de topo repetida desaparece do ramo que **abre uma lista** no `yamlsubset` | Os casos exercitavam só o ramo do valor |
| A recusa de *merge key* desaparece do **estilo de fluxo** no `yamlreg` | Só o ramo de bloco tinha caso |
| A recusa de `NEL`/`U+2028`/`U+2029` desaparece no `yamlsubset` | Os três casos **recusavam pela regra errada** — caíam na recusa do escalar não citado com `: `, e passavam com o defeito presente |

O terceiro é a forma fina do «critério satisfeito pela razão errada»: o teste
estava verde, a construção era recusada, e a regra que a recusava não era a que
o teste dizia estar a provar.

## 4. Achados da revisão independente

**Treze achados, um deles P0.** O revisor correu as três *suites*, a prova por
mutação e a sua própria sonda, e reverificou cada achado no estado final do ramo
(o ramo mudou durante a revisão, e isso está dito no relatório dele).

| # | Severidade | Achado | Disposição |
|---|---|---|---|
| A1 | **P0** | **`RecursionError` escapa do `yamlreg` e mata o *gate* 3b com *traceback* e código 1.** 400 linhas de YAML de bloco perfeitamente comum chegam; por fluxo, ~500 níveis. O CA 7 **nomeia** o `RecursionError` e estava marcado: o critério dizia ter fechado exactamente o modo de falha que a medição mostrou aberto. Pior, o teste que o devia apanhar (`TestNenhumaExcepcaoEscapa`) estava **verde com o defeito presente**, porque 10 000 mutações de um a três caracteres nunca constroem profundidade | **Corrigido.** `_PROFUNDIDADE_MAXIMA = 50`, contado em níveis e não em chamadas — contar chamadas recusaria uma lista de 60 itens, que é aninhamento 1 — nos dois caminhos (bloco e fluxo), com a linha na mensagem. Dois casos no corpus acima do limite e dois abaixo, mais duas mutações próprias |
| A2 | P1 | **O `_CHAVE` novo do `yamlsubset` recusava de mais, e a restrição não estava escrita.** A classe `[A-Za-z_][A-Za-z0-9_.-]*` que acompanhou a correcção do `partition(":")` recusava `rotação_dias:`, `a b:`, `a/b:`, `2fa:` e `a : b` — todas lidas **correctamente** pelo próprio oráculo do ticket. Num repositório inteiramente em português, a chave acentuada é a forma mais plausível de todas | **Corrigido.** A classe passou a ser **negativa**, como a do `yamlreg`: o que fica de fora são os indicadores do YAML e o `#`. Seis casos novos no corpus para as formas que voltaram a ler-se, um para o `a#b:` que continua recusado, e a restrição escrita no *docstring* |
| A3 | P1 | **`"a #b": c` passou de leitura correcta a recusa no `yamlreg`.** O início do escalar era calculado **depois** do nome da chave, pelo que uma aspa em posição de chave não «abria» nada e o ` #b": c` era cortado como comentário | **Corrigido.** O conjunto `aberturas` tem as duas posições — o início da chave e o início do valor. Caso no corpus nos dois leitores, e uma mutação por leitor |
| A4 | P1 | **A lista do *docstring* do `yamlreg` era falsa em posição de chave.** `@a: 1`, `` `a: 1 `` e `%YAML: 1` liam-se como chaves chamadas `@a`, `` `a `` e `%YAML`, em silêncio, e nenhuma é YAML válido (§7.3.3). E `%YAML 1.2` era recusado **pela regra errada** («esperava chave: valor»), a forma fina do «verde pela razão errada» | **Corrigido.** `%@`` ?` saem da classe do primeiro caractere da chave, nos dois leitores, e uma linha que comece por um indicador recusa com o **nome** do indicador. Quatro casos no corpus por leitor, e a mensagem passou a ter asserção — sem ela, a mutação que apagava a recusa nomeada **sobrevivia** |
| A5 | P1 | **`a: ]`, `a: }`, `a: ,` e `a: ?` liam-se em silêncio como cadeia nos dois leitores.** Em YAML 1.2 um escalar plano não pode começar por um indicador de fluxo, e o `?` sozinho é o indicador de chave explícita | **Corrigido.** Os três indicadores entram em `_PROIBIDOS` nos dois leitores e o `?` tem recusa própria; dentro de um escalar continuam a ser texto (`a: b,c` lê-se). Oito casos novos no corpus |
| A6 | P2 | **`a:` no topo do `yamlsubset` dava `[]` em vez de nulo.** Uma chave sem valor assumia **sempre** que abria uma lista, mesmo sem nenhum item | **Corrigido.** A chave fica a nulo e só passa a lista quando o primeiro item chega. Dois casos no corpus e uma mutação |
| A7 | P2 | **A equivalência não comparava 18 valores do inventário real.** O `_folhas` só emitia folha para escalares: `[]`, `{}` e a chave ausente eram indistinguíveis, e o `ops/secrets-inventory.yaml` tem 18 contentores vazios. O número publicado era verdadeiro e tinha este ponto cego | **Corrigido.** Um contentor vazio é agora uma folha com marca própria (`<lista vazia>`, `<mapa vazio>`): a contagem do inventário passou de 400 para **418** campos, e uma chave de valor `[]` a desaparecer deixa de passar |
| A8 | P2 | **`- "a": 1` passou a recusa no `yamlreg`, e o `yamlsubset` lia-o bem.** A exclusão da aspa no ramo de mapa de um item de lista impedia uma chave citada de ser chave | **Corrigido.** A aspa deixa de excluir o ramo de mapa: `- "a": 1` é um mapa e `- "a: b"` continua a ser cadeia, porque o `:` tem de vir **depois** da aspa de fecho. Caso no corpus e mutação |
| A9 | P2 | **Um `]` dentro de aspas numa lista de fluxo do `yamlsubset` recusava, com a mensagem errada** («lista de listas» para uma entrada sem lista nenhuma). O `split(",")` foi ensinado a respeitar aspas e a detecção de aninhamento não | **Corrigido.** O aninhamento verifica-se **depois** de partir pelas vírgulas que estão fora de aspas; `["x]y"]` lê-se, `[a, [b]]` recusa, e um `[` ou `]` dentro de um item não citado tem mensagem própria |
| A10 | P2 | **Código morto no `yamlsubset`:** a recusa de chave vazia era inalcançável, e nenhuma mutação a apanharia | **Corrigido:** o ramo saiu. Com a classe nova, `_CHAVE` nunca produz nome vazio |
| A11 | P2 | **Contradição no *docstring* do `yamlreg`:** «listas aninhadas, que são estrutura que este leitor não tem» — tem, em fluxo (`[[1, 2]]` e `{a: {b: 1}}` lêem-se) | **Corrigido:** a frase passou a dizer «em bloco», e o que se lê em fluxo está escrito |
| A12 | P2 | **Número errado no *docstring* do `yamlsubset`:** «cadeia de cinco caracteres» para `"a\nb"`, que tem quatro | **Corrigido**, com os quatro nomeados e verificados por execução. A mesma frase está no `tools/kamba_yaml.py` (KAM-136, em curso) e **não** se tocou nela: fica como linha 19 de [`../dividas-documentais.md`](../dividas-documentais.md) |
| A13 | P2 | **Dois números desactualizados nos documentos:** `canon_lint` com 181 testes quando já eram 182, e a linha do `DEL` na lista do *docstring* sem caso próprio no corpus | **Corrigido.** Os números desta análise e da evidência são agora os da última medição, e o `DEL` tem caso nos dois corpora |

**O que a revisão confirmou, e vale dizer:** as 83 recusas novas que existiam
quando ela correu foram verificadas **uma a uma** contra os oráculos, e nenhuma
era leitura correcta antes; os dois manifestos de `docs/tecnica/02` §5.1 lêem-se
**linha a linha** com o leitor novo; os dois oráculos são cópia textual do código
anterior (confirmado por `diff`); e não há «verde por construção» na
equivalência. O relatório também não encontrou nenhum problema no corte de
comentários em interacção com aspas fora dos casos acima, nem nas fronteiras das
expressões numéricas, nem ReDoS mensurável.

### O que mudou por causa desta revisão

| | Antes da revisão | Depois |
|---|---|---|
| Construções no corpus | 208 | **240** |
| Leituras silenciosas fechadas | 95 | **110** |
| Recusas que recusavam de mais, desfeitas | 0 | **2** |
| Campos folha na equivalência | 507 | **525** (os 18 contentores vazios entraram) |
| Mutações | 30 | **46** |
| Linhas da lista do *docstring* sem caso | 9 (fechadas na auto-validação) | **0** |

## 5. Veredicto

A revisão independente chegou a **«não cumpre ainda os critérios de aceitação»**,
com um P0 e quatro P1. Todos os treze achados foram fechados neste mesmo ramo, e
cada um tem caso no corpus e — onde a regra é código — mutação própria. O que a
revisão mediu e que vale guardar, porque é o argumento do ticket contra si
mesmo:

- **o critério 7 estava marcado e era falso.** Não por descuido de leitura: o
  teste que o devia sustentar estava verde **com o defeito presente**, porque a
  mutação de um a três caracteres nunca constrói profundidade. É o padrão que o
  KAM-136 chama «satisfeito pela razão errada», e o único jeito de o apanhar foi
  alguém com os requisitos e sem as justificações;
- **a correcção do caso 2 do KAM-136 trouxe uma recusa que recusava de mais**, e
  a forma que ela recusava — uma chave acentuada — é a mais plausível de todas
  num repositório em português. Estava a um `grep` de distância e não foi vista
  por quem escreveu a alteração;
- **duas construções passaram de recusa a leitura** por causa da revisão. É uma
  classe que o KAM-136 também teve (cinco casos) e que este ticket não previa na
  tabela da varredura: ela ganhou uma quinta coluna.

Com os treze fechados, os onze critérios de aceitação ficam satisfeitos, e a
secção «Verificação dos Critérios de Aceitação» do bloco do KAM-148 diz, por
critério, o que foi medido e com que comando. A caixa dos revisores humanos
continua vazia: **esta análise é evidência, não é um revisor.**

## 6. O que **não** foi verificado

- **`make ci` não correu nesta máquina** — não há `make` nem Node no *host*.
  Correram-se à mão as *suites* de `canon_lint` (182), `secrets_inventory` (77)
  e `lint_arch` (197), o *gate* 3 e os três passos do *gate* 3b; os restantes
  correm no CI do PR.
- **Não se comparou com um parser de YAML a sério.** Não há PyYAML no *host* e
  instalá-lo contrariaria a razão de existir dos leitores. As afirmações sobre o
  que o YAML faz estão fundamentadas na especificação (YAML 1.2, esquema
  *core*), não medidas — e onde a diferença entre 1.1 e 1.2 importa (`yes`/`no`,
  `017`, `1:30`) a decisão foi **recusar**, precisamente para não escolher uma
  versão que ninguém declarou.
- **O corpus real do `yamlreg` são quatro *fixtures*.** O `registry/` não tem
  ficheiros de produção — o conteúdo é do EPIC-03 — pelo que a equivalência
  mede 50 campos folha, não um manifesto a sério. A forma documentada do
  manifesto (`docs/tecnica/02` §5.1) foi corrida contra o leitor novo, e isso
  está nos achados; um manifesto real pode trazer formas que ninguém previu, e
  é para isso que o corpus se descobre por *glob*.
- **A prova por mutação dos dois leitores corre-se à mão**
  (`tools/canon_lint/tests/mutacoes_dos_leitores.py`). Não entra no corredor
  nocturno do KAM-143, que cobre as *suites* de `db/`: uma sobrevivente nova só
  aparece se alguém correr o script. Está registado como decisão devolvida.
- **O código de saída 2 está provado por execução em dois caminhos** (o
  subcomando `ficheiro` do `canon_lint` e o `carregar()` do
  `secrets_inventory`). O `YamlIlegivel` no `except` do `cli.main` é rede
  inalcançável hoje — o `registo.verificar` apanha-o antes — e está dito como
  tal, não contado como prova.

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: a varredura das 240 construções dos dois leitores e os achados da revisão independente do KAM-148. | Equipa KAMBÁ |

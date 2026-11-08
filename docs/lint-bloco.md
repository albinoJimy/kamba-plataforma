# Coerência interna de um bloco de ticket

| Campo | Valor |
|---|---|
| Ticket | KAM-183 |
| Âmbito | As duas superfícies que um bloco tem sobre o mesmo facto, e a sua comparação por máquina |
| Instrumento | `tools/lint_bloco` — `check`, `canario`, e os dois instrumentos de prova: `medir.py` e `mutacao.py` |
| Estado | **Entregue e sem portão.** Ver §7 |
| Não cobre | Os números de uma caixa contra os da prosa (§6, devolvido com a medição); a unificação do vocabulário de estados (§5, devolvido ao fundador) |

---

## 1. O escape, e porque é que ele não é um descuido

Um bloco de ticket diz **duas vezes** se um critério está cumprido:

```text
lista de caixas      ### Critérios de Aceitação      - [ ]  ou  - [x]
tabela de verificação | # | Critério | Estado | …    **satisfeito** / **parcial**
```

As duas podem discordar, e **nenhum dos onze *jobs* de gate as compara**.

Aconteceu duas vezes numa semana:

- o **KAM-082** abriu com as tabelas a dar quatro linhas como `marcada` e a lista
  de caixas com **zero** `- [x]` em doze. Apanhou-o quem verificou o PR, a olho,
  por ter cruzado os dois números;
- antes dessa, um bloco fundiu com «1 erro de conteúdo» na caixa e «3» na prosa
  do **mesmo** bloco. Apanhou-o uma revisão adversarial sobre **outro** ramo, um
  dia depois.

A regra desta casa é que «um escape que um portão podia ter apanhado vira
portão, não vira nota». Este documento é esse portão, e o que ele **não** cobre.

---

## 2. A regra que se entrega

Uma só, e chama-se `estado_contra_caixa`:

> Quando a tabela de verificação e a lista de caixas estão em correspondência
> um-a-um, a caixa e a célula de `Estado` têm de dizer o mesmo — **par a par**.

**Par a par e não em contagem**, e isso tem ensaio próprio: trocar duas caixas
entre si deixa o total de `- [x]` igual, e um *lint* que comparasse totais dizia
«conforme» sobre um bloco em que dois critérios estão com o estado do outro.

---

## 3. Os números têm comando, e o comando está no repositório

**Esta secção foi reescrita por inteiro.** A primeira versão citava dez números —
«121 dos 125 blocos», «52 primeiras-palavras», «646 células de `satisfeito`»,
«25% de alarme» — medidos por *scripts* que correram numa pasta temporária e
desapareceram. A revisão adversarial montou vinte receitas e **não reproduziu
nenhum deles**: a conclusão mantinha-se, os números não.

Um número reconstruído à mão é `INDÍCIO`, não `CONFIRMADO`. Por isso há agora
**`tools/lint_bloco/medir.py`**, que declara o predicado de cada número antes de
o contar, e esta secção **cita a saída dele** em vez de a parafrasear:

```text
$ python tools/lint_bloco/medir.py
A POPULACAO  (predicados 1, 2 e 3)
  blocos                                        183
  com seccao de verificacao                     123
  com tabela de coluna `Estado`                 103
  uniao dos dois                                129

O VOCABULARIO DA COLUNA `Estado`  (predicado 4)
  celulas de estado                             1471
  termos distintos                              76
  tabelas com coluna de assunto e sem `Estado`   41
  os dez termos mais frequentes:
        687  'satisfeito'
        176  'marcada'
        136  'parcial'
        113  'não satisfeito'
         90  'vazia'
         57  'não verificado'
         49  'confirmado'
         21  'marcado'
         11  'indício'
          7  'vazio'

A REGRA INGENUA, a que o pedido original descrevia  (predicado 5)
  blocos da uniao                               129
  que ela poria a vermelho                      109
  ou seja                                       84%

O QUE O *LINT* MEDE HOJE  (sem dispensas)
  blocos                                        183
  emparelhados                                  81
  achados                                       30
  em quantos blocos                             8
  nao medido ( 80)  sem tabela de verificacao com coluna `Estado`
  nao medido ( 16)  tabela sem correspondencia um-a-um com a lista
  nao medido (  8)  tabela com coluna `Estado` e sem coluna de assunto conhecida
  nao medido (  7)  o vocabulario nao classifica a celula de Estado

A REGRA DOS NUMEROS, que NAO se entrega  (predicado 6)
  pares comparaveis                             407
  sem numeros na caixa                          219
  com numeros, a concordar                       48
  com numeros, a divergir                       140
  taxa de alarme sobre os pares com numeros     74%
```

**E cita-se num sítio só, de propósito.** Integrar a `publico/main` a meio
deste ticket mudou nove destes números — os emparelhados de 79 para 81, as
células de estado de 1 432 para 1 471 — porque a base trouxe blocos novos. Um
número restatado em cinco sítios fica velho em cinco sítios; o resto deste
documento aponta para aqui em vez de repetir.

Os seis predicados estão escritos na *docstring* do `medir.py`, **antes** de
qualquer contagem — pela razão que o `tools/obs_lint/contar_metricas.py` já
escreveu: «uma contagem feita antes de se definir o que conta produz números
errados com a mesma firmeza com que produziria os certos».

### 3.1 O que estes números dizem, e o que mudou no desenho por causa deles

**A regra que o pedido descrevia — «o número de `- [x]` iguala o número de linhas
`marcada`» — poria 84% dos blocos a vermelho** (o predicado 5 do §3). E não por
estarem errados: a coluna de `Estado` usa dezenas de termos distintos, e
`marcada` é minoria por quase quatro para um contra `satisfeito`. Há dezenas de
tabelas com coluna de assunto e **sem** coluna `Estado` — nessas o estado vive na
prosa da evidência. Os valores exactos estão na saída acima.

Entregar a regra como pedida era entregar um *lint* que grita, e a seguir ninguém
o lê.

**Três renúncias de desenho, e cada uma é uma troca escrita:**

1. **Não se delimita a secção de verificação.** Ela não tem fronteira fiável —
   uns blocos põem-na antes dos «Detalhes Técnicos», outros depois do «Handoff»,
   e no KAM-013 as tabelas vivem sob um título irmão. Procuram-se **tabelas** em
   todo o bloco e identificam-se pelo **cabeçalho**.
2. **O emparelhamento é guiado pelos dados.** Há duas convenções: tabela de DoD
   própria, ou **uma** tabela que tabula os critérios **e** a DoD — o KAM-155 tem
   8 + 4 caixas e 12 linhas numa tabela só. Contra a lista dos critérios, aquilo
   lia-se como «quatro linhas a mais».
3. **O vocabulário é declarado em três listas**, e a terceira é a que torna as
   outras honestas (§5).

### 3.2 A regra estrutural, despromovida depois de medida

Havia uma segunda regra candidata, melhor em teoria: *cada caixa tem uma linha na
tabela, e cada linha tem uma caixa* — independente do vocabulário.

**Não se sabe distinguir os seus achados de um terceiro formato.** São os blocos
da categoria «tabela sem correspondência um-a-um com a lista» do §3, com tabelas
de 17 e 18 linhas para listas de 10 e 8 caixas que podem estar a tabular
sub-itens.

Ficou **despromovida a «não medido»**, que é o que ela é: o *lint* diz que não
conseguiu emparelhar aquele bloco, conta-o, e **não afirma que está errado**. Um
achado sobre o que não se sabe ensina a ignorar o *lint*, e aí ele deixa de valer
para o que sabe.

> **Uma correcção que a revisão adversarial obrigou.** A primeira versão desta
> secção dizia «12 em 53 blocos emparelhados, 23%», e o denominador **excluía os
> seus próprios numeradores**: nenhum bloco sem correspondência um-a-um está
> entre os emparelhados, por construção. A taxa não se refaz aqui — o número que
> conta é o **16** acima, e o denominador honesto são os blocos que têm tabela.

---

## 4. A cobertura é parte da saída

```text
$ python -m lint_bloco --root . check
lint_bloco: 183 bloco(s), 81 emparelhado(s), 0 achado(s), 111 nao medido(s),
            26 tabela(s) sem assunto, 8 dispensa(s)
lint_bloco:   nao medido (80): sem tabela de verificacao com coluna `Estado`
lint_bloco:   nao medido (16): tabela sem correspondencia um-a-um com a lista
lint_bloco:   nao medido (8): tabela com coluna `Estado` e sem coluna de assunto conhecida
lint_bloco:   nao medido (7): o vocabulario nao classifica a celula de Estado
```

**«0 achados» sobre 81 blocos de 183 não é «está tudo bem»: é «olhei para 81».**
Um *lint* que não diga o que não mediu ensina exactamente a leitura errada, e é a
disciplina que o `log_policy` e o `obs_lint` desta casa já impõem — «passar sem
ter lido nada não é passar».

**E as quatro categorias são quatro e não uma, por correcção.** A revisão
adversarial mediu que **35 dos 118** blocos da categoria «sem tabela de
verificação com coluna `Estado`» **tinham** coluna `Estado` — a mensagem dizia que
ela não existia, tendo-a. Vinte e seis eram `| CA | Estado | Evidência |`, que o
*parser* descartava: reconhecê-las levou os blocos emparelhados de **53 para
79**, e fez aparecer um oitavo bloco com divergência.

Dois pisos: `MINIMO_DE_BLOCOS` (150) apanha um `glob` que deixe de casar;
`MINIMO_DE_BLOCOS_MEDIDOS` (**43**) apanha o modo de falha mais perigoso deste
*lint* — uma mudança na forma do cabeçalho põe o emparelhamento a zero e a saída
continua a dizer «0 achados». Abaixo de qualquer um deles o comando sai com **2**.

> **E o valor dos pisos passou a ter ensaio**, não só o mecanismo. A revisão
> adversarial mediu que `MINIMO_DE_BLOCOS_MEDIDOS = 0` passava — porque `0 <= 81`
> é verdade, e um piso a zero é o mesmo que não ter piso.

> **O piso de emparelhados sobe quando o corpus cresce, e já subiu três vezes.**
> O ensaio exige `piso >= medidos // 2`, pelo que a folga são sempre dois
> blocos: 40 → **41** com o KAM-108, 41 → **42** com o KAM-182, e 42 → **43**
> com o KAM-184, cada um a acrescentar a sua secção de verificação — o último
> medido em `86` blocos emparelhados contra `85` na `main`. **Este número estava desactualizado
> aqui desde o KAM-108** — dizia 40 quando o código dizia 41 —, e com ele o
> literal do `mutacao.py`, pelo que a mutação do piso não casava e passava por
> medida sem o ser. As duas pontas ficaram emendadas no KAM-182. Quem subir o
> piso mexe em **três** sítios: o `lint.py`, o `mutacao.py` e esta linha.

---

## 5. O vocabulário, devolvido ao fundador

O *lint* classifica a coluna `Estado` em três, e a terceira lista é a que o torna
honesto:

| Classe | Entradas | Termos |
|---|---|---|
| **cumprido** | 11 | `satisfeito`, `satisfeita`, `marcada`, `marcado`, `cumprido`, `cumprida`, `confirmado`, `confirmada`, `verde`, `já satisfeito` e a variante sem acento |
| **por cumprir** | 19 | `parcial`, `vazia`, `vazio`, `caixa vazia`, `não satisfeito`, `não cumprido`, `não verificado`, `por marcar`, `por cumprir`, `morto`, `não — caixa vazia`, e as variantes sem acento e femininas |
| **sem classe** | 21 | `não aplicável`, `não alterado`, `decisão aberta`, `decisão escrita`, `a confirmar por parecer`, `a confirmar na integração`, `divergência registada`, `observação de backlog`, `conflito documental`, `defeito do backlog`, `condicionado ao spike`, `devolvido`, `indício`, e variantes |

**A terceira lista não é uma lacuna, é uma recusa de julgar.** Nenhuma daquelas
palavras quer dizer «cumprido» nem «por cumprir»: dizem que a pergunta não se
aplica, que a resposta não é nossa, ou que há uma divergência registada. E foi um
achado falso a aparecer que o mostrou — `não aplicável` com a caixa **marcada**
lia-se como defeito, quando um critério que não se aplica pode legitimamente ter
a caixa marcada.

### 5.1 O casamento é por **termo** e não por prefixo, e isso era um defeito

A primeira versão casava por **prefixo nu**, e a revisão adversarial mediu o
preço: `verde` está em `ESTADOS_FEITO`, logo `verde-azulado` dava «cumprido»; e
`cumprido parcialmente`, `marcadamente insuficiente` e
`confirmado / não verificado` — esta última uma forma **real** da árvore — davam o
mesmo. Era palpite por prefixo, no próprio sítio em que o ticket afirma que nada
se classifica por palpite. **Uma fronteira de palavra não chega**: o `-` de
`verde-azulado` e o espaço de `cumprido parcialmente` são fronteiras.

O modelo é outro: **o estado é o termo, e o que vem depois de um separador é
justificação.** Prova-se a célula inteira por igualdade; se não casar, corta-se no
primeiro separador seguido de espaço (`, `, ` — `, ` (`, `: `) e prova-se a
cabeça. Uma célula sem separador que não seja um termo conhecido fica **não
medida** — e o preço está declarado: `satisfeito pelo que o repositório tem` deixa
de se classificar. Perde-se cobertura e não se ganha palpite.

### 5.2 E a ordem das três listas é precaução, não necessidade

A primeira versão afirmava que os «por fazer» tinham de ir primeiro «senão
`vazia, satisfeito` classificava-se ao contrário». **É falso:** o termo de
`vazia, satisfeito` é `vazia`, e nenhuma ordem o muda. A mutação que troca as
listas **sobrevivia** aos ensaios, e havia um ensaio a afirmar o contrário. Hoje
o ensaio diz o que de facto governa — o termo — e a ordem fica por ser a leitura
certa de uma célula composta.

### 5.3 O que se devolve

**A unificação.** Onze entradas para «cumprido» e dezanove para «por cumprir» não
são trinta maneiras de pensar: são a mesma decisão escrita de maneiras diferentes
por tickets diferentes, com dezenas de termos distintos na árvore (§3). Unificá-las é fixar
o que a secção de verificação de um bloco tem de parecer, o que é **canon** e não
implementação. Com uma convenção ratificada:

- as tabelas com coluna de assunto e sem `Estado` (§3) passam a poder tê-la;
- a terceira lista pode encolher;
- uma palavra nova deixa de ser «não medido» e passa a poder ser **achado**.

**Credor: o fundador.**

---

## 6. A regra dos números, devolvida **com a medição**

O pedido nomeava uma segunda comparação: **os números escritos dentro de uma
caixa contra os mesmos números na prosa da célula de evidência**. É a que teria
apanhado o escape de «1 erro de conteúdo» contra «3» — e **não se entrega**.

O predicado 6 do `medir.py` mede-a: todos os inteiros do texto da caixa têm de
aparecer na **célula de evidência** da sua linha.

O número está na saída do §3, no predicado 6: hoje **74%** dos pares com números
divergem.

**Três em cada quatro**, e a razão é a mesma que já se via com um número mais
pequeno: a caixa de um critério traz uma referência de secção, uma versão ou uma
contagem de outra coisa, que a célula de evidência não tem razão nenhuma para
repetir. Entregar isto era entregar um *lint* que grita em três de cada quatro pares.

> **A primeira versão desta secção dizia 25%**, medido contra a **linha** inteira
> da tabela em vez da célula de evidência, e com outra extracção de inteiros. A
> revisão adversarial não o reproduziu, e tinha razão: eram dois predicados
> diferentes com o mesmo nome. Hoje o predicado está escrito no `medir.py` e o
> número sai de lá — e a devolução ficou **mais** fundamentada, não menos.

**O que falta para a fazer:** uma convenção declarada de que a célula de evidência
**restabelece** o número do critério, ou um campo legível por máquina por
critério. Credor: **o fundador**, pela mesma razão do §5.

**Dito sem rodeios:** o *lint* que este ticket entrega apanha o escape do KAM-082
e **não** apanha o que custou a fusão de ontem. Metade do pedido, com a outra
metade medida e devolvida.

---

## 7. Porque é que não está ligado a portão, e onde se liga

**Não está, e é deliberado.** Ligar uma verificação que trava fusões é alteração
de regra de bloqueio, pelos **dois** caminhos que esta casa já conhece:

- um ***job*** novo acrescenta um contexto exigido ao *ruleset* da `main` e ao
  agregador «gates do KAM-002», que hoje tem onze `needs`;
- uma **linha num alvo que já corre** muda o **critério** de um portão que já
  bloqueia: a partir desse momento o gate reprova árvores que antes aprovava.

É a fronteira que o KAM-080 respeitou ao entregar o `tools/obs_lint` sem portão.

**Para ligar, quando essa decisão for tomada, é uma linha** no alvo `ci-3`:

```make
	@$(PYTHON) -m lint_bloco --root $(ROOT) check
```

Nada mais: o alvo `bloco-lint` já corre o *lint* e o canário, pela ordem certa.
Registado como **lacuna 31** de [`ci.md`](ci.md). **Credor: o fundador.**

---

## 8. As dispensas, e porque não se corrigem aqui

As **30** divergências medidas estão em **oito** blocos, declaradas em
[`../ci/bloco-allow.yaml`](../ci/bloco-allow.yaml): KAM-031 (6), KAM-035 (6),
KAM-037 (4), KAM-075 (4), KAM-076 (3), KAM-171 (5), KAM-143 (1) e KAM-042 (1).

**Isto é dívida e não conformidade**, na mesma leitura que o
`ci/backlog-allow.yaml` escreve para si próprio.

**Não se corrigem neste PR** porque a caixa segue a tabela, e **a tabela é a
evidência daquele ticket e não deste**. Marcar as 30 caixas seria este ticket a
decidir, por oito outros, que a coluna de `Estado` deles está certa — e a
convenção que o manda fazer não está ratificada: é exactamente o que o §5 devolve.

A dispensa é por **bloco** e não por linha, de propósito. E cada entrada exige
`bloco`, `razao` e `credor` — uma dispensa sem credor é trabalho que ninguém
reclama.

**E há ensaios a prender as duas pontas:**
`test_sem_as_dispensas_a_arvore_real_da_achados` exige que, **sem** o ficheiro, a
árvore real dê achados; `test_nenhuma_dispensa_a_mais` recusa uma que já não seja
precisa; `test_cada_dispensa_e_de_um_bloco_que_existe` recusa um nome inventado.

---

## 9. Como se corre, e como se prova

```bash
export PYTHONPATH='tools;libs/py-core/src'      # `;` — Python do Windows
python -m lint_bloco --root . check              # 0 conforme, 1 achados, 2 nao verificou
python -m lint_bloco --root . canario            # as negativas mordem?
python tools/lint_bloco/medir.py                 # todos os numeros deste documento
python tools/lint_bloco/mutacao.py               # os ensaios mordem?
```

Pelo `Makefile`, quando houver `make`: `make bloco-lint`, que corre os dois
primeiros pela ordem certa.

**Os dois últimos são os instrumentos de prova, e estão no repositório porque a
primeira versão deste ticket os não tinha.** O `medir.py` produz os números; o
`mutacao.py` responde se os ensaios mordem, **com controlo** — corre a cópia sem
mutação primeiro, e para se ela não for verde, porque sem isso N vermelhos a
seguir podiam ser o mesmo defeito N vezes. (E não é hipotético: o controlo ficou
vermelho duas vezes a construí-lo, com `ModuleNotFoundError`, porque a cadeia de
importações é mais longa do que parece.)

---

## 10. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-183**. O `tools/lint_bloco` com a regra `estado_contra_caixa` (par a par, não em contagem), canário com negativas e positivas, dois pisos de cobertura, e a cobertura na própria saída. **Entregue sem portão** (§7). Devolve com a medição: a regra do pedido tal como escrita, a regra estrutural e a regra dos números; e a unificação do vocabulário, que é canon. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **A revisão adversarial deu 17 achados e todos se confirmaram contra a árvore.** Esta versão é a resposta. **Defeitos de código:** a coluna de assunto casava por sub-cadeia e a tabela `## Riscos do Epic` era lida como tabela de critérios em quatro blocos; o `\|` escapado deslocava a coluna de `Estado`; o casamento por prefixo nu dava `verde-azulado` como cumprido; e faltava `por cumprir` na lista que tem esse nome. **Cobertura:** reconhecer `\| CA \| Estado \| Evidência \|` levou os emparelhados de **53 para 81**, e a categoria «sem tabela com coluna `Estado`» deixou de ser falsa para 35 blocos. **Provas:** metade das mutações sobrevivia — entre elas o salto de cercas, a ordem das listas e o **valor** dos dois pisos —, uma assertiva estava desactivada com `if False` a esconder um defeito real, e a positiva da cerca não podia morder porque as caixas cercadas estavam fora das duas listas. **Números:** dez não se reproduziam, e a resposta não foi reescrevê-los mas **embarcar o instrumento** — `medir.py`, com os seis predicados escritos antes das contagens, e este documento passa a citar a saída dele; o `mutacao.py` entra pela mesma razão, com controlo. **E a espécie `ambigua` saiu**, porque a justificação dela não se verificava na medição. | Equipa KAMBÁ |
| 1.2 | Novembro 2026 | **KAM-182: o piso de emparelhados sobe de 41 para 42, e as três superfícies dele passam a dizer o mesmo.** O ensaio `test_os_pisos_valem_alguma_coisa` exige `piso >= medidos // 2`; duas secções de verificação fundiram entre o corte do ramo do KAM-182 e a medição dele — a do KAM-055 (PR `#146`) e a dele —, o `medidos` passou a **84** e `84 // 2` são 42. Medido nas duas pontas: com a `main` em `ca5cac55` são 83 e 41 bastava; com a `main` em `06b8aba2` são 84 e o ensaio falha com `41 not greater than or equal to 42`. **E emenda duas superfícies que estavam atrasadas desde o KAM-108:** este documento dizia `40` e o literal do `mutacao.py` também, pelo que a mutação do piso **não casava** e ficava verde por não ter mudado nada. Achado da revisão adversarial do KAM-182. O número não se sobe em antecipação — um piso acima do medido avermelha o portão sem defeito nenhum —, pelo que a folga volta a ser dois blocos. | Equipa KAMBÁ |
| 1.3 | Novembro 2026 | **KAM-184: o piso de emparelhados sobe de 42 para 43, e as três superfícies outra vez.** A secção de verificação daquele bloco é a **86.ª** medida — eram 85 na `main` em `b974dda4` —, e `86 // 2` são 43. É a terceira subida (40 → 41 no KAM-108, 41 → 42 no KAM-182), e a nota do §4.2 pagou-se como estava escrita: mexeram-se os **três** sítios no mesmo *commit* — o `MINIMO_DE_BLOCOS_MEDIDOS` do `lint.py`, o literal da mutação `o piso de emparelhados a zero` do `mutacao.py` (que, se ficasse em 42, deixava de casar e passava por medida sem o ser) e a linha do §4. Medido na árvore e não copiado de outro ramo: correm cinco sessões neste lote e cada secção de verificação que funda sobe o medido, pelo que quem fundir depois **renumera na integração**. | Equipa KAMBÁ |

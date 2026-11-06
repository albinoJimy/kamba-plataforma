# Coerência interna de um bloco de ticket

| Campo | Valor |
|---|---|
| Ticket | KAM-183 |
| Âmbito | As duas superfícies que um bloco tem sobre o mesmo facto, e a sua comparação por máquina |
| Instrumento | `tools/lint_bloco`, `python -m lint_bloco --root . check` e `canario` |
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

- o **KAM-082** abriu com as tabelas a dar **quatro** linhas como `marcada` e a
  lista de caixas com **zero** `- [x]` em doze — as quatro provas escritas na
  coluna de evidência e as quatro caixas por marcar. Apanhou-o quem verificou o
  PR, a olho, por ter cruzado os dois números;
- antes dessa, um bloco fundiu com «1 erro de conteúdo» na caixa e «3» na prosa
  do **mesmo** bloco. A medição dava 3. Apanhou-o uma revisão adversarial sobre
  **outro** ramo, um dia depois.

A regra desta casa é que «um escape que um portão podia ter apanhado vira
portão, não vira nota». Este documento é esse portão, e o que ele **não** cobre.

---

## 2. A regra que se entrega

Uma só, e chama-se `estado_contra_caixa`:

> Quando a tabela de verificação e a lista de caixas estão em correspondência
> um-a-um, a caixa e a célula de `Estado` têm de dizer o mesmo — **par a par**.

**Par a par e não em contagem**, e isso tem um teste próprio: trocar duas caixas
entre si deixa o total de `- [x]` igual, e um *lint* que comparasse totais dizia
«conforme» sobre um bloco em que dois critérios estão com o estado do outro.

Medido na árvore em `74ddc23`, antes de qualquer correcção: **29 divergências em
7 blocos**, de 53 emparelhados. Em **todas**, a caixa está por marcar e a tabela
diz `satisfeito` ou `marcada` — a mesma forma exacta do escape do KAM-082. Os
sete estão declarados em [`../ci/bloco-allow.yaml`](../ci/bloco-allow.yaml), com
a razão de não se corrigirem aqui (§8).

---

## 3. O que se mediu antes de escrever, e porque mudou o desenho

**A primeira versão deste *lint* ia impor «o número de `- [x]` iguala o número de
linhas `**marcada**`»** — era isso que o pedido descrevia. Medida sobre a árvore,
essa regra punha **121 dos 125** blocos com secção de verificação a vermelho. E
não por estarem errados: não há **uma** convenção.

| O que se mediu | Valor |
|---|---|
| Blocos com secção de verificação | **120** |
| Blocos emparelháveis (tabela com coluna `Estado` e correspondência um-a-um) | **53** |
| Primeiras-palavras distintas na coluna `Estado` | **52** |
| As cinco de topo | `satisfeito` (646 células), `parcial` (110), `marcada` (110), `não satisfeito` (103), `vazia` (73) |
| Formas distintas de cabeçalho de tabela | mais de uma dúzia |
| Tabelas **sem** coluna `Estado` (o estado vive na prosa da evidência) | **19** |

A palavra que a regra ia exigir — `marcada` — é **minoria**: 110 células contra
646 de `satisfeito`.

Três consequências de desenho, e cada uma é uma renúncia escrita:

1. **Não se delimita a secção de verificação.** Ela não tem fronteira fiável —
   uns blocos põem-na antes dos «Detalhes Técnicos», outros depois do «Handoff»,
   e no KAM-013 as tabelas vivem sob um título irmão (`### Os critérios, um a
   um`). Procuram-se **tabelas** em todo o bloco e identificam-se pelo
   **cabeçalho**.
2. **O emparelhamento é guiado pelos dados.** Há duas convenções: tabela de DoD
   própria, ou **uma** tabela que tabula os critérios **e** a DoD — o KAM-155 tem
   8 caixas de critérios, 4 de DoD e **12** linhas numa tabela só. Contra a lista
   dos critérios sozinha, aquilo lia-se como «quatro linhas a mais», e deu **13
   achados falsos** na primeira versão. Hoje provam-se as duas.
3. **O vocabulário é declarado e não inferido**, em três listas — cumprido, por
   cumprir, e **sem classe**. A terceira é a que torna as outras honestas (§5).

### 3.1 A regra estrutural que não resistiu à medição

Havia uma segunda regra candidata, e melhor em teoria: *cada caixa tem uma linha
na tabela, e cada linha tem uma caixa* — independente do vocabulário, e apanha um
critério que saia da verificação sem que nada o diga.

**Grita.** Com o emparelhamento já guiado pelos dados, ela dá **12 achados em 53
blocos emparelhados** (23%), e não se sabe de nenhum deles se é defeito ou um
terceiro formato: tabelas de 17 e 18 linhas para listas de 10 e 8 caixas, que
podem estar a tabular sub-itens.

Ficou **despromovida a «não medido»**, que é o que ela é: o *lint* diz que não
conseguiu emparelhar aquele bloco, conta-o, e não afirma que está errado. Um
achado sobre o que não se sabe ensina a ignorar o *lint*, e aí ele deixa de valer
para o que sabe.

---

## 4. A cobertura é parte da saída

```text
$ python -m lint_bloco --root . check
lint_bloco: 183 bloco(s), 54 emparelhado(s), 0 achado(s), 139 nao medido(s),
            11 tabela(s) ambigua(s), 7 dispensa(s)
lint_bloco:   nao medido (118): o bloco nao tem tabela de verificacao com coluna `Estado`
lint_bloco:   nao medido (12): tabela sem correspondencia um-a-um com a lista
lint_bloco:   nao medido (9): o vocabulario nao classifica a celula de Estado
```

**«0 achados» sobre 54 blocos de 183 não é «está tudo bem»: é «olhei para 54».**
Um *lint* que não diga o que não mediu ensina exactamente a leitura errada, e é a
disciplina que o `log_policy` e o `obs_lint` desta casa já impõem — «passar sem
ter lido nada não é passar».

Daí **dois pisos**, e o segundo é o que importa: `MINIMO_DE_BLOCOS` (150) apanha
um `glob` que deixe de casar; `MINIMO_DE_BLOCOS_MEDIDOS` (40) apanha o modo de
falha mais perigoso deste *lint* — uma mudança na forma do cabeçalho das tabelas
põe o emparelhamento a zero e a saída continua a dizer «0 achados». Abaixo de
qualquer um deles o comando sai com **2**, «não se conseguiu verificar», que
nunca se lê como verde.

---

## 5. O vocabulário, devolvido ao fundador

O *lint* classifica a coluna `Estado` em três, e a terceira lista é a que o torna
honesto:

| Classe | Palavras |
|---|---|
| **cumprido** | `satisfeito`, `satisfeita`, `marcada`, `marcado`, `cumprido`, `cumprida`, `confirmado`, `confirmada`, `verde`, `já satisfeito` |
| **por cumprir** | `parcial`, `vazia`, `vazio`, `caixa vazia`, `não satisfeito`, `não cumprido`, `não verificado`, `por marcar`, `morto` |
| **sem classe** | `não aplicável`, `não alterado`, `decisão aberta`, `decisão escrita`, `a confirmar por parecer`, `a confirmar na integração`, `divergência registada`, `observação de backlog`, `conflito documental`, `defeito do backlog`, `condicionado ao spike`, `devolvido`, `indício` |

**As listas acima são as palavras, e as constantes têm mais entradas do que
elas** — `ESTADOS_FEITO` tem **11**, `ESTADOS_POR_FAZER` **15** e
`ESTADOS_SEM_CLASSE` **21**. A diferença são as variantes **sem acento** da mesma
palavra (`nao satisfeito` ao lado de `não satisfeito`), e elas existem porque a
árvore tem as duas formas escritas: um *lint* que só conhecesse a acentuada
deixava de classificar metade das células sem dizer que o fazia.

**A terceira lista não é uma lacuna, é uma recusa de julgar.** Nenhuma daquelas
palavras quer dizer «cumprido» nem «por cumprir»: dizem que a pergunta não se
aplica, que a resposta não é nossa, ou que há uma divergência registada. E foi um
achado falso a aparecer que o mostrou — `não aplicável` com a caixa **marcada**
lia-se como defeito, quando um critério que não se aplica pode legitimamente ter
a caixa marcada.

**O que se devolve: a unificação.** Cinco palavras para «cumprido» e nove para
«por cumprir» não são cinco e nove maneiras de pensar — são a mesma decisão
escrita de maneiras diferentes por tickets diferentes. Unificá-las é fixar o que
a secção de verificação de um bloco tem de parecer, o que é **canon** e não
implementação. Com uma convenção ratificada, três coisas mudam:

- os **19** blocos cujas tabelas não têm coluna `Estado` passam a poder tê-la, e
  os **118** sem tabela nenhuma deixam de ser a maioria dos não medidos;
- a terceira lista pode encolher, porque cada palavra dela passa a ter um sítio
  declarado;
- uma palavra nova deixa de ser «não medido» e passa a poder ser **achado**, que
  é mais forte.

**Credor: o fundador.** Nada disto se decide de dentro de um *lint*.

---

## 6. A regra dos números, devolvida **com a medição**

O pedido nomeava uma segunda comparação: **os números escritos dentro de uma
caixa contra os mesmos números na prosa da célula de evidência**. É a que teria
apanhado o escape de «1 erro de conteúdo» contra «3» — e **não se entrega**.

Mediu-se um predicado directo: para cada par (caixa, linha de tabela), todos os
inteiros do texto da caixa têm de aparecer na linha da tabela.

| | |
|---|---|
| Pares comparáveis | **438** |
| Sem números na caixa | 196 |
| Números da caixa todos presentes na linha | **182** |
| Números da caixa em falta na linha | **60** |
| Taxa de alarme sobre os pares com números | **25%** |

**Um em cada quatro**, e os exemplos dizem porquê: a caixa de um critério traz
números que a célula de evidência não tem razão nenhuma para repetir — uma
referência de secção, uma versão, uma contagem de outra coisa. Entregar isto era
entregar um *lint* que grita sobre blocos limpos, e a seguir ninguém o lê.

**O que falta para a fazer**, e é o mesmo que o §5: uma convenção declarada de
que a célula de evidência **restabelece** o número do critério, ou um campo
legível por máquina por critério. Credor: **o fundador**, pela mesma razão.

**Dito sem rodeios:** o *lint* que este ticket entrega apanha o escape do
KAM-082 e **não** apanha o que custou a fusão de ontem. Metade do pedido, com a
outra metade medida e devolvida.

---

## 7. Porque é que não está ligado a portão, e onde se liga

**Não está, e é deliberado.** Ligar uma verificação que trava fusões é alteração
de regra de bloqueio, pelos **dois** caminhos que esta casa já conhece:

- um ***job*** novo acrescenta um contexto exigido ao *ruleset* da `main` e ao
  agregador «gates do KAM-002», que hoje tem onze `needs`;
- uma **linha num alvo que já corre** muda o **critério** de um portão que já
  bloqueia: a partir desse momento o gate reprova árvores que antes aprovava. É a
  mesma fronteira, por outra porta.

É a fronteira que o KAM-080 respeitou ao entregar o `tools/obs_lint` sem portão.

**Para ligar, quando essa decisão for tomada, é uma linha** no alvo `ci-3` do
`Makefile`, ao lado dos outros *lints* de referências:

```make
	@$(PYTHON) -m lint_bloco --root $(ROOT) check
```

Nada mais: o alvo `bloco-lint` já corre o *lint* e o canário, pela ordem certa.

**Credor: o fundador.**

---

## 8. As dispensas, e porque não se corrigem aqui

As **29** divergências medidas estão em sete blocos, declaradas em
[`../ci/bloco-allow.yaml`](../ci/bloco-allow.yaml): KAM-031 (6), KAM-035 (6),
KAM-037 (4), KAM-075 (4), KAM-076 (3), KAM-171 (5) e KAM-042 (1).

**Isto é dívida e não conformidade**, na mesma leitura que o
`ci/backlog-allow.yaml` escreve para si próprio.

**Não se corrigem neste PR** porque a caixa segue a tabela, e **a tabela é a
evidência daquele ticket e não deste**. Marcar as 29 caixas seria este ticket a
decidir, por sete outros, que a coluna de `Estado` deles está certa — e a
convenção que o manda fazer (o KAM-080 e o KAM-082) não está ratificada: é
exactamente o que o §5 devolve. Corrigir sem essa decisão seria propagar uma
convenção por 29 caixas de tickets alheios a pretexto de um *lint* novo.

A dispensa é por **bloco** e não por linha, de propósito: quem emendar um destes
blocos tira a linha de lá e o *lint* passa a cobri-lo por inteiro, em vez de
ficar a meio. E cada entrada exige `bloco`, `razao` e `credor` — uma dispensa sem
credor é trabalho que ninguém reclama, e era a forma de aquele ficheiro virar
gaveta.

**E há um teste a prender as duas pontas:** `test_sem_as_dispensas_a_arvore_real_da_achados`
exige que, **sem** o ficheiro, a árvore real dê achados. Sem ele, uma dispensa a
mais — ou um `frozenset` que o CLI deixasse de ler — tornava o verde
indistinguível de «não há nada para dispensar». E
`test_nenhuma_dispensa_a_mais` recusa uma dispensa que já não seja precisa.

---

## 9. Como se corre

```bash
export PYTHONPATH='tools;libs/py-core/src'      # `;` — Python do Windows
python -m lint_bloco --root . check              # 0 conforme, 1 achados, 2 nao verificou
python -m lint_bloco --root . canario            # prova que a regra morde
```

Pelo `Makefile`, quando houver `make`: `make bloco-lint`, que corre os dois pela
ordem certa.

O canário tem **4 negativas e 4 positivas**, e a lista de regras que ele exige
que sejam exercitadas vem do **código** e não das *fixtures* — um manifesto vazio
não pode dar «tudo verde». A suite são **33 testes**, e entra no *gate* 4 pelo
`wildcard` de `$(SUITES_DE_TOOLS)` sem ninguém a declarar.

---

## 10. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-183**. O `tools/lint_bloco` com a regra `estado_contra_caixa` (par a par, não em contagem), 33 testes, canário com 4 negativas e 4 positivas, dois pisos de cobertura, e a cobertura na própria saída. **Entregue sem portão** (§7). Devolve com a medição: a regra do pedido original tal como escrita, que punha **121 dos 125** blocos a vermelho por não haver uma convenção; a regra estrutural, que grita em **23%** dos blocos emparelhados; a regra dos números, que alarma em **25%** dos pares com números; e a unificação do vocabulário de **52** primeiras-palavras, que é canon. As **29** divergências medidas em 7 blocos ficam declaradas em `../ci/bloco-allow.yaml` com credor. | Equipa KAMBÁ |

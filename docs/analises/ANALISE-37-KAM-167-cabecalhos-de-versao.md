# ANALISE-37 — KAM-167: as 19 dispensas de cabeçalho de versão

| Campo | Valor |
|---|---|
| Ticket | KAM-167 |
| PR | `#83` |
| Data da revisão | 2026-10-28 |
| Instrumento | subagente `general-purpose`, independente, que recebeu o diff e os requisitos e **não** o raciocínio do autor |
| Base efectiva | `refs/remotes/publico/main` em `664a211` |

Registo datado. Mede o que era verdade no dia em que correu, e não se reescreve
— é a regra que põe `docs/analises/` fora do corpus dos *gates*
(`tools/lint_backlog/versoes.py`).

## Como correu, e a limitação que isso impôs

A revisão foi lançada **assim que o diff existiu**, pela regra do §1.6 da
`software-factory` — que é tempo de relógio sobreposto em vez de somado. O preço
é o que o próprio revisor escreveu no seu aviso metodológico: **a árvore mexeu-se
por baixo dele**. Arrancou com a base em `2dbc2f0` e as cinco superfícies do
*backlog* ainda vazias, e durante a auditoria o KAM-166 fundiu, a base passou a
`664a211`, as superfícies foram escritas e o `docs/ci.md` foi corrigido.

Daí uma parte do relatório descrever um estado intermédio. Cada achado foi por
isso **reverificado contra a árvore que vai fundir**, e três mudaram de
classificação por essa reverificação. O revisor registou impressões SHA-256 dos
ficheiros que leu, o que tornou a reverificação possível em vez de discutível.

**Calibração:** 13 achados levantados, **8 confirmados e corrigidos**, 1
reclassificado como morto, 4 plausíveis (3 corrigidos por serem baratos, 1
respondido por argumento). Mais 10 achados que o revisor já trouxe mortos, com a
evidência que os matou.

## Os achados confirmados, e o que cada um custou

| # | Achado | Onde | Correcção |
|---|---|---|---|
| 1 | O `ci/backlog-allow.yaml` dizia que a dívida 4 «fechou com o KAM-167», e a própria dívida 4, escrita no mesmo PR, diz em letras gordas que **não** fecha | `ci/backlog-allow.yaml` | A frase passa a dizer que a 21 fechou com o KAM-165 e que a 4 **não fecha**, por ser de duas metades |
| 2 | O precedente do KAM-163 estava **errado no número** (`1.43`, é `1.42`) e descrito ao contrário: a linha que ele acrescentou **regista** o pagamento do cabeçalho, pelo que o precedente invocado era, na parte que importava, um contra-exemplo | `specs/tickets/KAM-167.md` | Número corrigido e o precedente reescrito: sustenta a **operação**, não a ausência de registo |
| 3 | A evidência da dívida 4 citava «campo `1.33`, `max` `1.33`» do `INDICE` — valor que o próprio PR substituiu duas vezes | dívida 4 e evidência do CA 4 | Deixa de citar o número: o que fica escrito é a **relação**, verificada por máquina |
| 4 | A dívida 4 dizia que o parágrafo omite «KAM-150 a KAM-165»; a omissão real já era até ao **KAM-167**, aumentada pelo próprio PR | dívida 4 e CA 4 | Corrigido, e dito que a omissão **cresce** a cada ticket porque a enumeração é copiada e não derivada |
| 5 | Parágrafo deixado no presente a dizer «o que está aqui continua a ser trabalho de outro ticket» e «**nenhum ticket os reclama hoje**», três linhas acima da frase que diz que dois tickets os reclamaram e que o ficheiro não declara nada | `ci/backlog-allow.yaml` | Passado ao passado, como os vizinhos |
| 6 | A linha de versão `1.60` do `docs/ci.md` escrita **sem acentos**, ao contrário das vizinhas e do parágrafo que o mesmo *hunk* acrescenta | `docs/ci.md` | Reescrita acentuada. Nenhum dos seis *linters* apanha isto |
| 7 | O `specs/EPIC-07` tem **conteúdo** alterado e não ganhava linha de «Controlo de versões» — a classe exacta que a casa registra como dívida **101** | `specs/EPIC-07` | Ganha a linha `1.8`, com o campo do cabeçalho a acompanhar. E o mesmo achado generalizou-se a um sítio que o revisor não nomeou: o `docs/dividas-documentais.md`, também alterado, ganha a `1.72` |
| 8 | Números de corpus em presente e desactualizados (24 em 41, 16 sem campo; hoje 58 e 33) | `ci/backlog-allow.yaml` | A medição datada fica como datada, e os números de hoje ficam escritos ao lado |

O achado 8 veio classificado `PLAUSÍVEL` — o revisor disse que lhe faltava a
regra da casa sobre o que, dentro de um comentário datado, conta como afirmação
viva. Corrigi-o por ser barato e por a fronteira ser a mesma do achado 5.

Também corrigi, dos plausíveis, a frase de evidência do CA 1 (dizia «o `git
diff` dá 19 ficheiros», o que só é verdade restringido aos 19 documentos de
cabeçalho — o PR inteiro toca 26) e as formas brasileiras «registra» e
«registraria» no texto novo. Esta última fica **meia-corrigida de propósito**: o
conjunto tem 78 ocorrências de «registra», incluindo uma escrita pelo KAM-165
neste mesmo ficheiro, e harmonizar as 78 é alargar escopo. Corrigi as minhas.

## O achado que não sobreviveu à reverificação

```
ACHADO: O campo `Dependências` do ticket diz «—», e o ticket não podia passar os
        gates antes de o KAM-166 estar no §4.
CLASSIFICAÇÃO DO REVISOR: CONFIRMADO
RECLASSIFICAÇÃO: MORTO
```

O mecanismo que o revisor mediu está certo — o §1 tem de ser contíguo, e isso
cria uma ordem de fusão real. O que não se sustenta é a conclusão de que essa
ordem pertence ao campo `Dependências`, e **a casa decide isto por uso**:

| Ticket | `Dependências` | Antecessor numérico |
|---|---|---|
| KAM-165 | `—` | KAM-164 |
| KAM-166 | `KAM-018` | KAM-165 |

Nenhum dos dois declara o seu antecessor numérico. A contiguidade do topo do
*backlog* vale para **todos** os pares consecutivos, pelo que declará-la como
dependência encheria o campo de arestas que não dizem nada sobre trabalho — e
obrigaria à reciprocidade no `Bloqueia` do antecessor, que o *gate* 3c verifica.
O campo serve para dizer de que trabalho um ticket depende; o KAM-167 não depende
de nada que o KAM-166 produza.

A ordem de fusão fica onde pertence: escrita em «Detalhes Técnicos», com o
mecanismo e os dois ficheiros de código que o impõem.

## O que o revisor trouxe já morto, e que fica registado para não se pagar outra vez

| Hipótese | A evidência que a matou |
|---|---|
| Um dos 19 cabeçalhos com o valor errado | Verificados um a um, três vezes, por duas leituras independentes (o `versoes.varrer` do próprio leitor e um script do revisor). Nos 19: campo == `max` == última linha física |
| Sobrou ou faltou uma declaração | As três chaves ausentes; `lint_backlog` dá «0 declaracao(oes)». Os 19 corrigidos são exactamente as 19 entradas removidas, comparadas item a item |
| Atribuição histórica errada dos cinco pagos de passagem | Os quatro tickets e os quatro números de PR verificam-se commit a commit. (O único erro era o **valor** `1.43` — achado 2) |
| Os dois canários podem não reproduzir | Reproduzidos em processo, sem editar a árvore, por *monkeypatch* do leitor. As duas mensagens citadas no bloco são literalmente as que o código produz |
| Terminadores de linha mudados | 0 CRLF em todos os ficheiros tocados; `.gitattributes` tem `* text=auto eol=lf`; o `--numstat` dá 1/1 por documento, e um ficheiro com terminadores trocados daria o total de linhas |
| Buraco ou número repetido introduzido | 0 buracos e 0 repetidos em 58 documentos. As linhas novas são contíguas aos `max` anteriores |
| Escopo expandido para uma regra de bloqueio | `git diff --name-only` sobre `tools/`, `.github/`, `Makefile` e `ci/` devolve **apenas** `ci/backlog-allow.yaml` |
| A afirmação sobre o `_PROPOSITO`, o `_INTERVALO` e a linha 1.43 do epic | As três verificam-se nos ficheiros citados |

## O achado lateral: a dívida 44 está paga há oito dias e ninguém a riscou

O revisor mediu, por sua conta, aquilo que o seu *briefing* lhe dava como facto —
e o *briefing* dava-o porque o **§1.5 da `software-factory`** o diz por escrito,
citando a **dívida 44**: que o `lint_contagens` sai com código 2 de dentro de um
*worktree*, porque o filtro do corpus exclui caminhos com `.claude` sobre o
caminho **absoluto**. A atribuição é essa, e não a nenhuma sessão: a crença vem
da skill e da linha 44, não de quem a repetiu.

**Não reproduz.** O revisor correu-o três vezes de `tools/` com `--root ..` e deu
**0** nas três, com «13 contagem(ns) viva(s) ... Fontes: 167 tickets». E uma
terceira sessão corroborou-o de forma independente, de dentro de
`.claude/worktrees/cool-goldwasser-c67fbd` — um caminho **com** `.claude` —, com
o mesmo 0 e as mesmas 13 contagens em 10 ficheiros, tanto no `main` como no seu
ramo.

**A explicação está medida, e a primeira que escrevi estava errada.** Eu atribuí
o não-reproduzir à invocação com `--root` **relativo**, supondo que o `glob`
devolvia caminhos sem segmento `.claude` para o filtro apanhar. É o contrário: o
`ficheiros()` de `tools/lint_contagens/scan.py` **já filtra sobre o caminho
relativo à raiz** (`rel = f.relative_to(raiz)`), pelo que não reproduz com
invocação nenhuma. O próprio comentário da função descreve o defeito no
**passado** e nomeia os *worktrees* do Claude Code como o caso que o revelava.

Quem o corrigiu, e quando:

| Evento | Data | Onde |
|---|---|---|
| A dívida 44 é escrita | **2026-10-19** | `ee930fc`, KAM-133 (PR `#24`) |
| O defeito é corrigido | **2026-10-20** | `f4f63a6`, **KAM-158** (PR `#34`) — «a exclusao do corpus e relativa a raiz, nao ao caminho absoluto» |
| A linha 44 continua **não riscada** | 2026-10-28 | `docs/dividas-documentais.md`:70 |

A dívida era legítima quando foi escrita e foi paga **no dia seguinte**. O que
ficou foi a linha, e com ela o §1.5 da skill a mandar não confiar num passo de
*gate* que funciona. Custou a esta execução duas medições a mais e um indício
errado escrito num ficheiro de análise.

**Não é riscada aqui, e a razão é de âmbito, não de dúvida.** A própria linha 44
atribui o trabalho ao dono do *gate* 3 e diz explicitamente que **não** é do
KAM-158; riscá-la obriga a corrigir também o §1.5 da skill, que é alteração a
doutrina e estava a ser editada por outra sessão no momento desta revisão. A
medição acima foi-lhe entregue em vez do trabalho.

**E foi aproveitada: o PR `#84` risca a linha 44** — verificado e não aceite por
relato: `gh pr diff 84` mostra `| 44 |` a passar a `| ~~44~~ |`, com o `f4f63a6`
como evidência. Essa sessão reproduziu a medição por sua conta antes de a
aceitar, chamando o `ficheiros()` com a raiz dentro de cada
`.claude/worktrees/*` da máquina: **62 a 142 ficheiros, nunca zero**.

E encontrou **mais duas passagens** do aviso obsoleto do que as que esta análise
nomeou — o `references/portoes-e-velocidade.md` e o **bloco de *handoff* do
próprio `specs/tickets/KAM-165.md`**, que mandava o executor desconfiar do passo
a cada leitura do ticket. Fica registado aqui porque é o verdadeiro custo da
dívida paga e não riscada: não foi a linha, foram as cinco passagens que ela
autorizou. **Mandar desconfiar de um passo que funciona é pior do que não avisar
nada**, porque ensina a ler um verde como inconclusivo.

A consequência prática, que vale repetir porque é o contrário do que a dívida
sugere: **o terceiro passo do *gate* 3 é verificável de dentro de um
*worktree***, e um código 2 ali **não se desculpa com a dívida 44 sem o
reproduzir**.

## Um achado sobre o leitor do próprio *gate* 3c, sem dono aqui

Encontrado pelo autor durante a execução, e não pela revisão. O
`_corpo_da_tabela` de `tools/lint_backlog/versoes.py` pára na primeira linha que
não começa por `|`, pelo que uma tabela de histórico **cortada por uma linha
vazia** é lida só até ao corte.

Medido no `docs/ci.md`: tem uma linha vazia na 2435, o leitor devolve `max=1.45`
e o ficheiro tem linhas até à `1.59`. Hoje é inócuo ali — aquele documento não
tem campo de versão no cabeçalho, e o pedaço lido está contíguo —, mas significa
que o *gate* pode não ver um buraco nem um número repetido na parte que não lê.

É do dono do *gate* 3c. Não foi corrigido: é código e é alteração ao leitor de
uma regra de bloqueio.

## A lição de método, que não é sobre o resultado

O revisor apanhou, em trânsito, a árvore de trabalho com dois cabeçalhos
**adiantados** em relação à sua tabela — o `EPIC-01` em `1.46` com a tabela em
`1.45`, e o `INDICE` em `1.35` com a tabela em `1.34` —, porque a sequência de
edição subiu o campo antes de escrever a linha de histórico.

Nenhum *commit* ficou nesse estado (o primeiro *commit* não toca nenhum dos dois
ficheiros, e o segundo faz as duas edições juntas), pelo que não é defeito do
resultado. Mas é um modo de falha do método que passou a ter consequência **por
causa deste ticket**: com as três listas vazias, uma árvore nesse estado já não
tem válvula nenhuma para declarar. Quem pagar um cabeçalho e acrescentar linha no
mesmo PR deve escrever a linha **primeiro** e o campo depois, ou as duas no mesmo
*commit*.

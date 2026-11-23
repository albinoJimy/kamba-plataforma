"""As regras que comparam as duas superficies de um bloco, e a sua cobertura.

**Uma regra**, e e a que apanha o escape que deu origem a este *lint*:

    estado_contra_caixa a caixa `- [x]` e a celula de `Estado` tem de dizer o
                        mesmo, **par a par** e nao em contagem. Uma troca entre
                        duas linhas da a mesma contagem e e um defeito.

**Esta *docstring* dizia «duas regras» e documentava uma `tabela_sem_par` que nao
existe em codigo nenhum.** Ela existiu, foi despromovida a «nao medido» por
gritar em blocos limpos (ver o §3.2 do `docs/lint-bloco.md`), e o topo deste
modulo ficou a descrever a versao anterior — canon a mentir sobre codigo que uma
revisao matou. Apanhou-o a revisao adversarial do proprio ticket, com um `grep`:
a cadeia `tabela_sem_par` tinha **uma** ocorrencia em toda a arvore, e era esta
linha.

## O ESCAPE QUE ISTO FECHA, MEDIDO E NAO SUPOSTO

O KAM-082 abriu com as tabelas a dar **quatro** linhas como `marcada` e a lista
de caixas com **zero** `- [x]` em doze — as quatro provas escritas na coluna de
evidencia e as quatro caixas por marcar. Nenhum dos onze *jobs* de gate o leu;
apanhou-o quem verificou o PR, a olho, e **por ter cruzado os dois numeros**.

E custou uma fusao antes dessa: um bloco com «1 erro de conteudo» na caixa e «3»
na prosa do mesmo bloco, apanhado um dia depois por uma revisao adversarial
sobre outro ramo.

A regra desta casa e que «um escape que um portao podia ter apanhado vira
portao». Este e o portao — **entregue sem estar ligado**, porque ligar uma
verificacao que trava fusoes e alteracao de regra de bloqueio.

## O EMPARELHAMENTO E GUIADO PELOS DADOS, E A PRIMEIRA VERSAO NAO ERA

A primeira versao emparelhava a tabela de `Critério` com a lista de critérios, e
ponto. Deu **13 achados falsos**, e a causa mediu-se: ha blocos que tabulam os
critérios **e** a DoD numa **so** tabela com cabecalho `| # | Critério | Estado |
Evidência |` — o KAM-155 tem 8 caixas de critérios, 4 de DoD e **12** linhas.
Contra a lista dos critérios sozinha, aquilo lia-se como «quatro linhas a mais».

Por isso o emparelhamento prova as duas convencoes e **nao escolhe por palpite**:

    uma tabela de DoD propria   ->  critérios↔critérios e DoD↔DoD
    so a tabela de critérios    ->  tenta `len(linhas) == len(CA)`;
                                    senao tenta `len(CA) + len(DoD)`;
                                    se nenhuma casar, **ai** e achado

O que isto renuncia, dito: uma tabela combinada cujo numero de linhas por
coincidencia iguale o das caixas de critérios e emparelhada com a lista errada.
Nao ha daqui como as distinguir, e preferiu-se a convencao mais comum.

## O QUE ESTE *LINT* NAO MEDE, E PORQUE

A terceira comparacao que o pedido original nomeava — **os numeros escritos
dentro de uma caixa contra os mesmos numeros na prosa da celula de evidencia** —
**nao se implementou**. A razao esta em `docs/lint-bloco.md` §6, com a medicao:
nao se encontrou predicado que a meca sem gritar sobre blocos limpos. Fica
devolvida com a medicao, em vez de entregue a gritar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lint_bloco import modelo

#: As regras, pelo nome com que aparecem num achado. Fixa no codigo e **nao**
#: lida das *fixtures*: um manifesto vazio nao pode dar «tudo verde».
REGRAS_OBRIGATORIAS = ("estado_contra_caixa",)

#: Quantos blocos, no minimo, tem de ser medidos para a saida valer algo.
#:
#: Sao **parametros** do `verificar` e nao constantes fechadas, pela razao do
#: `minimo` do `lint_backlog.ler_blocos`: as *fixtures* do canario sao arvores de
#: dois ou tres blocos, e um piso fechado tornava-as impossiveis de escrever —
#: o que empurrava o canario para fora da arvore real, que e onde ele vale menos.
#:
#: **Nao e enfeite.** Um `glob` que deixe de casar, um titulo de seccao que mude,
#: ou uma mudanca na forma do cabecalho das tabelas poem este *lint* a medir
#: **zero** blocos e a dizer «0 achados» — que se le como «esta tudo bem» e e a
#: falha que o `log_policy` e o `obs_lint` desta casa ja recusam. Medido a
#: 2026-11-06: **81** blocos emparelhados, com este ticket dentro. (Eram 53
#: antes de a revisao adversarial mostrar que o cabecalho `| CA | Estado |
#: Evidência |` — 26 tabelas — estava a ser descartado.) O piso fica
#: abaixo com folga, para nao exigir emenda a cada bloco novo, e acima de zero
#: com muita.
#:
#: **Subiu de 40 para 41 com o KAM-108**, e a razao e mecanica e nao de
#: desenho: a seccao de verificacao que aquele ticket acrescentou ao seu bloco
#: fez o emparelhamento passar de **81 para 82**, e o
#: `test_os_pisos_valem_alguma_coisa` exige `piso >= medidos // 2` — `82 // 2`
#: sao 41. Medido nas duas pontas: a `main` em `52d8000a` da 81 e o ensaio
#: passa; com o bloco do KAM-108 da 82 e o ensaio falha com `40 not greater
#: than or equal to 41`. (O `42` que esta linha dizia era o piso **deste**
#: ticket e nao o da ponta que o KAM-108 mediu; apanhado pela revisao
#: adversarial do KAM-069, que o mediu em vez de o ler.)
#:
#: **Subir o piso torna este *lint* mais estrito e nao menos**, que e o que
#: distingue esta emenda de um esvaziamento: o piso e um **minimo** de blocos
#: medidos, e o ensaio existe precisamente para forcar a emenda quando o corpus
#: cresce. O que fica dito, porque e limite do desenho e nao deste ticket: com o
#: piso em metade do medido, a **folga sao dois blocos** — ao 86.º volta a pedir
#: emenda. Mexer nisso e do KAM-183, que escreveu a regra.
#:
#: **E ao 84.º chegou, exactamente como a nota acima previa.** O piso ficou em
#: **42** e quem o pos la foi o **KAM-182**, que fundiu primeiro; o KAM-079 tinha
#: medido o mesmo valor no seu ramo e chegaria ao mesmo numero. **Qual dos dois
#: o subiu e um dado sobre a ordem de fusao e nao sobre o corpus**, pelo que nao
#: vale a pena escreve-lo de outra forma: o que vale e o numero e como se mede.
#:
#: As duas restricoes que o `test_os_pisos_valem_alguma_coisa` e o
#: `test_os_pisos_da_arvore_real_ficam_abaixo_do_medido` impoem juntas:
#:
#:     medidos // 2  <=  MINIMO_DE_BLOCOS_MEDIDOS  <=  medidos
#:
#: Medido na arvore desta fusao — a `publico/main` em `b974dda4` com o bloco do
#: KAM-079 dentro: **86 medidos**, e `86 // 2` sao 43, pelo que o piso **sobe
#: para 43**.
#:
#: Uma versao anterior desta nota dizia «85 medidos, e o piso fica em 42», e era
#: verdadeira enquanto a `main` estava em `b79d1e8c`. Deixou de o ser sem
#: ninguem tocar numa linha deste ficheiro: o **KAM-069** (#156) fundiu primeiro
#: e trouxe o 86.º bloco. **A emenda e de quem funde em segundo e faz-se na
#: integracao**, nunca em antecipacao — um piso acima do medido avermelha o
#: portao sem defeito nenhum, e um piso copiado de outra ponta nao mede a arvore
#: em que esta.
#:
#: **Dizer «folga» aqui nao chega, porque as duas leituras dao numeros
#: diferentes e as duas estao certas:** `piso - exigido` e **zero** (o piso fica
#: colado ao minimo), e **faltam dois blocos** para a proxima emenda — o 43
#: serve ate aos **87** medidos, e ao 88.º `88 // 2` sao 44. A integracao deste
#: ticket viu a mesma palavra usada nos dois sentidos na mesma conversa, uma vez
#: por cada leitura, pelo que o que fica escrito e a **conta**. Nao se nomeia
#: aqui quem pagara essa emenda — ha ramos abertos com seccoes de verificacao
#: por fundir, e qual deles aterra em segundo decide-se na fusao e nao aqui.
#:
#: **Cinco blocos a pagar esta linha e um dado sobre o desenho, e nao sobre
#: nenhum dos tickets.** Desde os 81: a seccao do KAM-108, a do KAM-055, a do
#: KAM-182, a do KAM-069 e a do KAM-079. O limite nao e a regra — o piso e que a
#: torna util —, e sim a **cadencia**: cada dois blocos de verificacao novos
#: exigem uma emenda a uma constante que vive no ticket de outra pessoa, e a
#: emenda e sempre uma medicao na arvore de quem funde. Fica registado para o
#: **KAM-183**, que e quem governa esta regra.
#:
#: **E o 87.o bloco chegou com o KAM-051, e o 88.o com o KAM-070: o piso sobe
#: para 44.** Vale a pena guardar a sequencia porque ela mostra a cadencia a
#: funcionar, e **as duas fusoes mediram-se na arvore de quem integrou**:
#:
#:     main 0e3541d3   86 medidos   piso 43   (o KAM-079 subiu-o de 42)
#:     main 2669c6f8   87 medidos   piso 43   (o KAM-051 entrou, e **nao** pagou
#:                                             emenda: o 43 servia ate aos 87)
#:     esta arvore     88 medidos   piso 44   (o KAM-070 entrou e paga)
#:
#: A linha do meio e a que vale mais: **uma seccao nova nem sempre custa uma
#: emenda**, e a nota do KAM-079 previa-o («o 43 serve ate aos 87») sem ter visto
#: acontecer. Logo nao se sobe por haver seccao nova — sobe-se por a conta o
#: pedir, e a conta le-se da arvore.
#:
#: Medido na arvore desta integracao, com a `publico/main` em `2669c6f8` dentro:
#: `medidos 88 | exigido 44 | piso 43` antes desta linha subir. Com o piso em 43,
#: o `test_os_pisos_valem_alguma_coisa` falha com
#: `43 not greater than or equal to 44`.
#:
#: Quem acrescentar o **90.o** paga a emenda seguinte: o 44 serve ate aos 89.
#: **E o 89.o bloco e o do KAM-086 — mas o piso que ele escreve e 45, e nao 44.**
#: Esta e a primeira vez que a emenda nao sai da arvore de quem a escreve, e vale
#: a pena dizer porque, que e a razao de a casa ter a regra «mede na arvore da
#: fusao»:
#:
#:     esta arvore                       89 medidos   exigido 44   (o 44 da main
#:                                                                  ainda servia)
#:     esta arvore + o bloco do #157     90 medidos   exigido 45
#:
#: As duas linhas sao **medidas**, e a segunda mediu-se trocando o
#: `specs/EPIC-03_Agent_Runtime_Verticais.md` desta arvore pela versao da ponta
#: do #157 (KAM-184) e voltando a correr o `check`. O #157 esta na fila a frente
#: e nao toca neste ficheiro, pelo que **a ordem de fusao decidia o valor**: com
#: o KAM-086 primeiro, 44 chegava; com o #157 primeiro, 44 avermelhava o portao
#: num ramo onde ninguem mexeu numa linha.
#:
#: O 45 e o unico valor que as duas restricoes aceitam nas **duas** arvores —
#: `44 <= 45 <= 89` e `45 <= 45 <= 90` — pelo que escrever 45 e o que torna o
#: piso independente da ordem de fusao. **Nao e antecipacao:** um piso acima do
#: medido avermelha o portao, e 45 nao esta acima de 89. A regra que a nota do
#: KAM-079 fixou («a emenda e de quem funde em segundo») fica intacta; o que esta
#: nota acrescenta e que, quando a emenda **depende de quem funde primeiro**, o
#: valor a escrever e o que vale para os dois, e nao o que vale para o caso que
#: der mais sorte.
#:
#: Sao **oito** blocos desde os 81: KAM-108, KAM-055, KAM-182, KAM-069, KAM-079,
#: KAM-051, KAM-070 e este. E **mexer neste piso sao duas edicoes**: o par fixado
#: do `mutacao.py` cita o literal, e um par que nao casa deixa a prova por
#: mutacao a medir nada.
#:
#: **E o #157 fundiu, pelo que as duas linhas acima deixaram de ser uma
#: simulacao e a de baixo passou a ser a arvore.** Medido depois de integrar a
#: `publico/main` em `5941a11f`: **90 medidos, exigido 45**, e o 45 que este
#: ficheiro ja tinha e agora o valor que a conta pede e nao um que a antecipa.
#: Fica registado que a ordem de fusao confirmou a medicao e nao a contrariou —
#: se tivesse fundido ao contrario, o 45 continuava a servir, que era a razao de
#: o escrever.
#:
#: **E o KAM-060 mediu-o tres vezes no mesmo ramo, com tres resultados** — 86 na
#: base de corte (onde escreveu a emenda para 43), 89 com a `77a579bd` dentro
#: (onde o 44 servia e **reverteu** a emenda) e 90 com a `5941a11f` (onde ela se
#: paga). A seccao dele nao pagou e pagou sem uma linha dela mudar, e e a mesma
#: licao do paragrafo de cima vista do outro lado: a de cima diz que o **valor**
#: nao depende da ordem de fusao se se escolher o que vale nas duas arvores, e
#: esta diz que a **divida** depende dela sempre. As duas juntas fecham a regra:
#: mede-se na arvore da fusao, e escreve-se o valor que sobrevive a ordem.
#:
#: Quem acrescentar o **92.o** paga a emenda seguinte: o 45 serve ate aos 91.
#:
#: **O 92.o e o do KAM-185, e a emenda veio dada por um instrumento.** O
#: `.claude/skills/software-factory/scripts/fila.py` mede o piso na arvore do
#: `merge-tree` de cada PR aberto com a `main` e da a cada um o valor que lhe
#: cabe pela ordem da fila. Com o #162 (KAM-060) na cabeca, disse a este PR
#: «92 medidos -> sobe para 46, e o literal par em `tools/lint_bloco/mutacao.py`»
#: antes de ele integrar a `35111c35`; medido depois: **92 medidos, exigido 46**.
#:
#: Quem acrescentar o **94.o** paga a emenda seguinte: o 46 serve ate aos 93.
#:
#: **O 94.o e o do KAM-033**, e o valor veio da fila outra vez: medido na arvore
#: integrada com a `publico/main` em `fc6d91bd` (o KAM-137 e o KAM-057 dentro),
#: **94 medidos, exigido 47**. Quem acrescentar o **96.o** paga a seguinte: o 47
#: serve ate aos 95.
#:
#: **O 96.o e o do KAM-083**, medido na arvore do ramo sobre a `publico/main` em
#: `6583930f`: **96 medidos, exigido 48**. Se outro ramo do mesmo lote fundir
#: antes com um bloco medido, o numero re-mede-se na integracao, e nao se soma de
#: cabeca. Quem acrescentar o **98.o** paga a seguinte: o 48 serve ate aos 97.
#:
#: **O 97.o e o do KAM-090**, medido na arvore integrada com a `publico/main` em
#: `c1c45644`: **97 medidos, exigido 48** — nao custou emenda.
#:
#: **O 98.o e o do KAM-073**, medido na arvore integrada com a `publico/main` em
#: `06ad9ef4`: **98 medidos, exigido 49**. Quem acrescentar o **100.o** paga a
#: seguinte: o 49 serve ate aos 99.
#:
#: **O 99.o e o do KAM-186**, medido na arvore integrada com a `publico/main` em
#: `3a1b19f8`: **99 medidos**, e `99 // 2` sao 49. **Fica 50 e nao 49**, e e
#: escolha medida: o #168 e o #172 estao a frente dele na fila, cada um pode
#: trazer um bloco medido, e o 50 e o unico valor que cumpre
#: `medidos // 2 <= piso <= medidos` nas duas ordens de fusao possiveis
#: (`49 <= 50 <= 99` sem eles, `50 <= 50 <= 101` com os dois). Com 49, quem
#: fundisse depois deles avermelhava. O 50 serve ate aos 101.
#:
#: **O 102.o e o do KAM-081**, medido na arvore integrada com a `publico/main` em
#: `baf579bb` (o #168 e o #172 ja fundidos): **102 medidos**, e `102 // 2` sao
#: 51. Sobe para 51, que serve ate aos 103.
#:
#: **O 104.o e o do KAM-040**, medido na arvore integrada com a `publico/main`
#: em `7acab4ed` (o #176 do KAM-189 ja fundido): **104 medidos**, e `104 // 2`
#: sao 52. Sobe para 52, que serve ate aos 105.
#:
#: **O 106.o e o do KAM-071**, medido na arvore integrada com a `publico/main`
#: em `b55d2a84` (o #175 do KAM-093 ja fundido): **106 medidos**, e `106 // 2`
#: sao 53. Sobe para 53, que serve ate aos 107.
#:
#: **O 107.o e o do KAM-099**, medido na arvore integrada com a `publico/main`
#: em `baef17ea` (o #178 do KAM-071 ja fundido): **107 medidos**, e `107 // 2`
#: sao 53. **Fica em 53**, que serve ate aos 107 — o 108.o pede a emenda.
#:
#: **O 108.o e o do KAM-087**, medido na arvore integrada com a `publico/main`
#: em `af404aef` (o #180 do KAM-099 ja fundido): **108 medidos**, e `108 // 2`
#: sao 54. Sobe para 54, que serve ate aos 109.
#:
#: **O 109.o e o do KAM-088**, medido na arvore integrada com a `publico/main`
#: em `c4fbbb0c` (o #181 do KAM-087 ja fundido): **109 medidos**, e `109 // 2`
#: sao 54. **Fica em 54**, que serve ate aos 109 — o 110.o pede a emenda.
#:
#: **O 110.o e o do KAM-061**, medido na arvore integrada com a `publico/main`
#: em `9b68d6b5` (o #179 do KAM-088 ja fundido): **110 medidos**, e `110 // 2`
#: sao 55. **Sobe para 55**, que serve ate aos 111.
#:
#: **O 112.o e o do KAM-050**, medido na arvore integrada com a `publico/main`
#: em `8c5158d4` (o #183 do KAM-193 ja fundido): **112 medidos**, e `112 // 2`
#: sao 56. Sobe para 56, que serve ate aos 113.
#:
#: **O 114.o e o do KAM-192**, contado com o do KAM-191 (#184), que funde antes:
#: **114 medidos** na arvore integrada, e `114 // 2` sao 57. Sobe para 57, que
#: serve ate aos 115.
#:
#: **O 116.o e o do KAM-062**, medido na arvore integrada com a `publico/main`
#: em `32092f45` (o #187 do KAM-089 ja fundido): **116 medidos**, e `116 // 2`
#: sao 58. Sobe para 58, que serve ate aos 117.
#:
#: **O 118.o e o do KAM-049**, medido na arvore integrada com a `publico/main`
#: em `c63c3c01` (o #190 do KAM-063 ja fundido): **118 medidos**, e `118 // 2`
#: sao 59. Sobe para 59, que serve ate aos 119.
#:
#: **O 120.o e o do KAM-196**, medido na arvore integrada com a `publico/main`
#: em `c085a8a6` (o #192 do KAM-197 ja fundido): **120 medidos**, e `120 // 2`
#: sao 60. Sobe para 60, que serve ate aos 121.
#:
#: **O 122.o e o do KAM-198**, medido na arvore integrada com a `publico/main`
#: em `be3e6eba` (o #193 do KAM-194 ja fundido): **122 medidos**, e `122 // 2`
#: sao 61. Sobe para 61, que serve ate aos 123.
#:
#: **O 124.o e o do KAM-064**, medido na arvore integrada com a `publico/main`
#: em `cd696baf` (o #194 do KAM-120 ja fundido): **124 medidos**, e `124 // 2`
#: sao 62. Sobe para 62, que serve ate aos 125.
#:
#: **O 126.o e o do KAM-097**, medido na arvore integrada com a `publico/main`
#: em `970ea958` (o #196 do KAM-059 ja fundido): **126 medidos**, e `126 // 2`
#: sao 63. Sobe para 63, que serve ate aos 127.
#:
#: **O 128.o e o do KAM-124**, que funde depois do #200 (KAM-056): na arvore
#: integrada com a `publico/main` em `e1fe2ee8` (o #197 do KAM-097 ja fundido)
#: mede **127**, e com o bloco do KAM-056 por baixo **128** — `128 // 2` sao 64.
#: Sobe para 64, que serve ate aos 129 e vale ja para os 127.
#:
#: **O 130.o e o do KAM-095**, medido na arvore integrada com a `publico/main`
#: em `ec22756c` (o #202 do KAM-092 ja fundido): **130 medidos**, e `130 // 2`
#: sao 65. Sobe para 65, que serve ate aos 131.
#:
#: **O 132.o e o do KAM-201**, medido na arvore integrada com a `publico/main`
#: em `23b54a3e` (o #201 do KAM-095 e o #203 do KAM-199 ja fundidos): **132
#: medidos**, e `132 // 2` sao 66. Sobe para 66, que serve ate aos 133.
#:
#: **O 133.o e o do KAM-058**, medido na arvore integrada com a `publico/main`
#: em `8d507a9d` (o #204 do KAM-201 ja fundido): **133 medidos**, e `133 // 2`
#: sao 66. Fica em 66, e o 134.o sobe-o para 67.
#:
#: **O 134.o e o do KAM-117**, medido na arvore integrada com a `publico/main`
#: em `8b8f2057` (o #206 do KAM-058 ja fundido): **134 medidos**, e `134 // 2`
#: sao 67. Sobe para 67, que serve ate aos 135.
#:
#: **O 136.o e o do KAM-096**, medido na arvore integrada com a `publico/main`
#: em `7382be01` (o #207 do KAM-094 ja fundido): **136 medidos**, e `136 // 2`
#: sao 68. Sobe para 68, que serve ate aos 137.
#:
#: **O 137.o e o do KAM-072**, medido na arvore integrada com a `publico/main`
#: em `1869a0c2` (o #209 do KAM-096 ja fundido): **137 medidos**, e `137 // 2`
#: sao 68. Fica em 68, e o 138.o sobe-o para 69.
#:
#: **O 138.o e o do KAM-190**, medido no ramo dele sobre a `publico/main` em
#: `234e4739`: **138 medidos**, e `138 // 2` sao 69. Sobe para 69, que serve ate
#: aos 139. *Provisorio*: o KAM-098, o KAM-118, o KAM-195 e o KAM-200 correm ao
#: lado, e quem fundir em segundo remede na arvore integrada.
#:
#: **O 139.o e o do KAM-200**, medido na arvore integrada com a `publico/main`
#: em `b2f2a108` (o #210 do KAM-190 ja fundido): **139 medidos**, e `139 // 2`
#: sao 69. Fica em 69, e o 140.o sobe-o para 70.
#:
#: **O 140.o e o do KAM-098**, medido na arvore integrada com a `publico/main`
#: em `4dbe709a` (o #212 do KAM-200 ja fundido): **140 medidos**, e `140 // 2`
#: sao 70. Sobe para 70, que serve ate aos 141.
#:
#: **O 141.o e o do KAM-195**, medido na arvore integrada com a `publico/main`
#: em `7ae41e27` (o #211 do KAM-098 ja fundido): **141 medidos**, e `141 // 2`
#: sao 70. Fica em 70, e o 142.o sobe-o para 71.
#:
#: **O 142.o e o do KAM-118**, medido na arvore integrada com a `publico/main`
#: em `5ef99f83` (o #213 do KAM-195 ja fundido): **142 medidos**, e `142 // 2`
#: sao 71. Sobe para 71, que serve ate aos 143.
#:
#: **O 144.o e o do KAM-214**, medido na arvore integrada com a `publico/main`
#: em `7d56e48f` (o #217 do KAM-213 ja fundido, com **143 medidos** na `main`
#: pristina): **144 medidos**, e `144 // 2` sao 72. Sobe para 72, que serve ate
#: aos 145.
#:
#: **O 146.o e o do KAM-204**, medido na arvore integrada com a `publico/main`
#: em `7245e5e3` (o #218 do KAM-205 ja fundido, com **145 medidos** na `main`):
#: **146 medidos**, e `146 // 2` sao 73. Sobe para 73, que serve ate aos 147.
#:
#: **O 147.o e o do KAM-211**, medido na arvore integrada com a `publico/main`
#: em `0ee34a38` (o #220 do KAM-204 ja fundido, com **146 medidos** na `main`):
#: **147 medidos**, e `147 // 2` sao 73. Fica em 73, e o 148.o sobe-o para 74.
#:
#: **O 148.o e o do KAM-210**, medido na arvore integrada com a `publico/main`
#: em `795f393c` (o #221 do KAM-211 ja fundido, com **147 medidos** na `main`):
#: **148 medidos**, e `148 // 2` sao 74. Sobe para 74, que serve ate aos 149.
#:
#: **O 150.o e o do KAM-207**, medido sobre a `publico/main` em `f0a31b54`
#: (**149 medidos** na `main` pristina): **150 medidos**, e `150 // 2` sao 75.
#: Sobe para 75, que serve ate aos 151. Ha tres PRs ao lado no lote 12, e quem
#: fundir em segundo remede na arvore integrada.
#:
#: **O 151.o e o do KAM-123**, medido na arvore integrada com a `publico/main`
#: em `d6c427fa` (o #225 do KAM-207 ja fundido, com **150 medidos** na `main`):
#: **151 medidos**, e `151 // 2` sao 75. Fica em 75, e o 152.o sobe-o para 76.
#:
#: **O 152.o e o do KAM-217**, medido na arvore integrada com a `publico/main`
#: em `1fb4694b` (o #227 do KAM-123 ja fundido, com **151 medidos** na `main`):
#: **152 medidos**, e `152 // 2` sao 76. Sobe para 76, que serve ate aos 153.
#:
#: **O 153.o e o do KAM-219**, medido na arvore integrada com a `publico/main`
#: em `f933984f` (o #224 do KAM-217 ja fundido, com **152 medidos** na `main`):
#: **153 medidos**, e `153 // 2` sao 76. Fica em 76, e o 154.o sobe-o para 77.
#:
#: **O 154.o e o do KAM-220**, medido no ramo sobre a `publico/main` em `57446ec0`
#: (com **153 medidos** na `main`): o bloco do KAM-220 ganha a verificacao, e o
#: do KAM-226 nasce sem ela. **154 medidos**, e `154 // 2` sao 77. Sobe para 77,
#: que serve ate aos 155. Ha quatro PRs ao lado no lote 13, e quem fundir em
#: segundo remede na arvore integrada.
#:
#: **O 155.o e o do KAM-224**, medido na arvore integrada com a `publico/main`
#: em `3d5f4857` (o #229 do KAM-220 ja fundido, com **154 medidos** na `main`):
#: **155 medidos**, e `155 // 2` sao 77. Fica em 77, e o 156.o sobe-o para 78.
#:
#: **O 156.o e o do KAM-222**, medido na arvore integrada com a `publico/main`
#: em `e273d74c` (o #230 do KAM-224 ja fundido, com **155 medidos** na `main`):
#: o bloco do KAM-222 ganha a verificacao, e o do KAM-228 nasce sem ela. **156
#: medidos**, e `156 // 2` sao 78. Sobe para 78, que serve ate aos 157.
#:
#: **O 158.o e o do KAM-216**, medido na arvore integrada com a `publico/main`
#: em `5f8a17b8` (o #233 do KAM-229 ja fundido, com **157 medidos** na `main`):
#: **158 medidos**, e `158 // 2` sao 79. Sobe para 79, que serve ate aos 159.
#: **O 160.o e o do KAM-221**, medido na arvore integrada com a `publico/main`
#: em `4b2f00ab` (o #234 do KAM-228 ja fundido, com o bloco dele medido):
#: **160 medidos**, e `160 // 2` sao 80. Sobe para 80, que serve ate aos 161.
#:
#: **O 161.o e o do KAM-119**, medido na arvore integrada com a `publico/main`
#: em `19247ace` (o #228 do KAM-221 ja fundido, com **160 medidos** na `main`):
#: o bloco do KAM-119 ganha a verificacao, e o do KAM-231 nasce sem ela. **161
#: medidos**, e `161 // 2` sao 80. Fica em 80; o 162.o sobe-o para 81.
#:
#: **O 162.o e o do KAM-223**, medido na arvore integrada com a `publico/main`
#: em `fd1157ed` (o #236 do KAM-119 ja fundido, com **161 medidos** na `main`):
#: o bloco do KAM-223 ganha a verificacao, e o do KAM-232 nasce sem ela. **162
#: medidos**, e `162 // 2` sao 81. Sobe para 81, que serve ate aos 163.
#:
#: **O 163.o e o do KAM-226**, medido na arvore integrada com a `publico/main`
#: em `82e9aa11` (o #238 do KAM-223 ja fundido, com **162 medidos** na `main`):
#: **163 medidos**, e `163 // 2` sao 81. Fica em 81, e o 164.o sobe-o para 82.
#:
#: **O 164.o e o do KAM-218**, medido na arvore integrada com a `publico/main`
#: em `1250ba45` (o #239 do KAM-226 ja fundido, com **163 medidos** na `main`):
#: o bloco do KAM-218 ganha a verificacao, e o do KAM-233 nasce sem ela. **164
#: medidos**, e `164 // 2` sao 82. Sobe para 82, que serve ate aos 165.
#:
#: **O 165.o e o do KAM-227** e **o 166.o e o do KAM-230**, medidos na arvore
#: integrada com a `publico/main` em `54a45e9c` (o #235 do KAM-227 ja fundido,
#: com **165 medidos** na `main`): **166 medidos**, e `166 // 2` sao 83. Sobe
#: para 83, que serve ate aos 167.
#:
#: **O 167.o e o do KAM-234** e **o 168.o e o do KAM-121**, medidos na arvore
#: integrada com a `publico/main` em `12f23918` (o #237 do KAM-234 ja fundido,
#: com **167 medidos** na `main`): o bloco do KAM-121 ganha a verificacao.
#: **168 medidos**, e `168 // 2` sao 84. Sobe para 84, que serve ate aos 169.
#:
#: **O 169.o e o do KAM-202**, medido na arvore integrada com a `publico/main`
#: em `d9472c40` (o #243 do KAM-121 ja fundido, com **168 medidos** na `main`):
#: o bloco do KAM-202 ganha a verificacao, e os do KAM-235 e do KAM-236 nascem
#: sem ela. **169 medidos**, e `169 // 2` sao 84. Fica em 84; o 170.o sobe-o
#: para 85.
#:
#: **O 170.o e o do KAM-215**, medido na arvore integrada com a `publico/main`
#: em `d790a9be` (o #244 do KAM-202 ja fundido, com **169 medidos** na `main`):
#: **170 medidos**, e `170 // 2` sao 85. Sobe para 85, que serve ate aos 171.
#:
#: **O 171.o e o do KAM-206**, ja na `main` em `28bb7e88`. **O 172.o e o do
#: KAM-232**, medido na arvore integrada com a `publico/main` em `28bb7e88` (o
#: #245 do KAM-206 ja fundido, com **171 medidos** na `main`): o bloco do
#: KAM-232 ganha a verificacao. **172 medidos**, e `172 // 2` sao 86. Sobe para
#: 86, que serve ate aos 173.
#:
#: **O 173.o e o do KAM-235**, medido na arvore integrada com a `publico/main`
#: em `b37d1ffe` (o #246 do KAM-232 ja fundido, com **172 medidos** na `main`):
#: o bloco do KAM-235 ganha a verificacao. **173 medidos**, e `173 // 2` sao 86.
#: Fica em 86, e o 174.o sobe-o para 87.
#:
#: **O 174.o e o do KAM-125**, medido na arvore integrada com a `publico/main`
#: em `96411555` (o #248 do KAM-235 ja fundido, com **173 medidos** na `main`):
#: o bloco do KAM-125 ganha a verificacao, e o do KAM-237 nasce sem ela.
#: **174 medidos**, e `174 // 2` sao 87. Sobe para 87, que serve ate aos 175.
#:
#: **O 175.o e o do KAM-236**, medido na arvore integrada com a `publico/main`
#: em `600952bd` (o #247 do KAM-125 ja fundido, com **174 medidos** na `main`):
#: o bloco do KAM-236 ganha a verificacao, e os do KAM-238 ao KAM-240 nascem
#: sem ela. **175 medidos**, e `175 // 2` sao 87. Fica em 87, que serve ate aos 175.
#:
#: **O 176.o e o do KAM-237**, medido na arvore com a `publico/main` em
#: `95826f19` (o #249 do KAM-236 ja fundido, com **175 medidos** na `main`): o
#: bloco do KAM-237 ganha a verificacao. **176 medidos**, e `176 // 2` sao 88.
#: Sobe para 88, que serve ate aos 177.
#:
#: **O 177.o e o do KAM-238**, medido na arvore da integracao com a
#: `publico/main` em `18cfdf69` (o #252 do KAM-237 ja fundido, com **176
#: medidos** na `main`): o bloco do KAM-238 ganha a verificacao, e os do
#: KAM-241 e do KAM-242 nascem sem ela. **177 medidos**, e `177 // 2` sao 88.
#: O piso fica em 88, que serve ate aos 177: o bloco seguinte a ganhar a
#: verificacao sobe-o para 89.
#:
#: **O 178.o e o do KAM-231**, medido na arvore da integracao com a
#: `publico/main` em `44b8c4b0` (o #253 do KAM-238 ja fundido, com **177
#: medidos** na `main`): o bloco do KAM-231 ganha a verificacao, e o do KAM-243
#: nasce sem ela. **178 medidos**, e `178 // 2` sao 89. Sobe para 89, que serve
#: ate aos 179.
#:
#: **O 179.o e o do KAM-122**, medido na arvore da integracao com a
#: `publico/main` em `f5da45da` (o #250 do KAM-231 ja fundido, com **178
#: medidos** na `main`): o bloco do KAM-122 ganha a verificacao, e o do KAM-246
#: nasce sem ela. **179 medidos**, e `179 // 2` sao 89. O piso fica em 89, que
#: serve ate aos 179: o bloco seguinte a ganhar a verificacao sobe-o para 90.
#:
#: **O 180.o e o do KAM-225**, medido na arvore da integracao com a
#: `publico/main` em `25babeca` (o #255 do KAM-122 ja fundido, com **179
#: medidos** na `main`): o bloco do KAM-225 ganha a verificacao. **180
#: medidos**, e `180 // 2` sao 90. Sobe para 90, que serve ate aos 181.
#:
#: **O 181.o e o do KAM-233**, medido na arvore da integracao com a
#: `publico/main` em `fec6fdce` (o #251 do KAM-225 ja fundido, com **180
#: medidos** na `main`): o bloco do KAM-233 ganha a verificacao, e os do KAM-247
#: e do KAM-248 nascem sem ela. **181 medidos**, e `181 // 2` sao 90. O piso
#: fica em 90, que serve ate aos 181: o bloco seguinte sobe-o para 91.
#:
#: **O 182.o e o do KAM-208**, medido na arvore da integracao com a
#: `publico/main` em `4e9909b9` (o #256 do KAM-233 ja fundido, com **181
#: medidos** na `main`): o bloco do KAM-208 ganha a verificacao. **182
#: medidos**, e `182 // 2` sao 91. Sobe para 91, que serve ate aos 183.
#:
#: **O 183.o e o do KAM-242**, medido na arvore da integracao com a
#: `publico/main` em `3054739c` (o #257 do KAM-208 ja fundido, com **182
#: medidos** na `main`): o bloco do KAM-242 ganha a verificacao. **183
#: medidos**, e `183 // 2` sao 91. O piso fica em 91, que serve ate aos 183:
#: o bloco seguinte a ganhar a verificacao sobe-o para 92.
MINIMO_DE_BLOCOS_MEDIDOS = 91

#: Quantos blocos existem, no minimo. O mesmo argumento, para a camada de baixo:
#: se o `ler_blocos` deixar de ver a populacao, o piso de cima podia continuar a
#: ser atingido por acidente. Medido: 184 (KAM-184).
MINIMO_DE_BLOCOS = 150


class ConfiguracaoInvalida(RuntimeError):
    """Nao se conseguiu medir o suficiente para a saida valer algo."""


@dataclass(frozen=True)
class Achado:
    regra: str
    onde: str
    detalhe: str

    def __str__(self) -> str:
        return f"{self.onde}: {self.regra} — {self.detalhe}"


@dataclass(frozen=True)
class NaoMedido:
    """Um bloco, ou metade de um bloco, que o *lint* nao conseguiu medir.

    **Nao e um achado**, e a diferenca importa: um achado diz «isto esta
    errado», isto diz «isto nao foi olhado». Contam-se e nomeiam-se, porque um
    *lint* que nao diga o que nao mediu ensina a ler «0 achados» como «esta tudo
    bem».
    """

    bloco: str
    onde: str
    #: A categoria, para a saida agrupar. Um campo e nao um prefixo do texto:
    #: agrupar pelo inicio da frase dava «critérios 7» como categoria.
    categoria: str
    porque: str


@dataclass(frozen=True)
class Par:
    """Uma tabela emparelhada com a lista de caixas que ela tabula."""

    rotulo: str
    caixas: tuple[modelo.Caixa, ...]
    estados: tuple[str, ...]
    onde_tabela: str


def emparelhar(bloco: modelo.Bloco) -> tuple[list[Par], list[NaoMedido]]:
    """Que lista de caixas cada tabela do bloco tabula.

    Ver a secao «O emparelhamento e guiado pelos dados» no topo do modulo.

    **Nao devolve achados, e devolvia uma lista sempre vazia.** Ela sobrou da
    regra `tabela_sem_par`, despromovida a «nao medido»; o `verificar` filtrava
    essa lista por dispensas e somava-a, sobre nada. Encanamento morto que um
    leitor tem de percorrer para descobrir que nao faz nada — apanhado pela
    revisao adversarial do proprio ticket.
    """
    pares: list[Par] = []
    nao_medidos: list[NaoMedido] = []

    tab_ca = bloco.tabela("criterios")
    tab_dod = bloco.tabela("dod")

    if tab_ca is None and tab_dod is None:
        # **A mensagem distingue tres casos, e a primeira versao dava um so.**
        # A revisao adversarial mediu que **35 dos 118** blocos daquela categoria
        # tinham coluna `Estado` — a mensagem dizia que ela nao existia, tendo-a.
        # Vinte e seis eram `| CA | Estado | Evidência |`, hoje reconhecidas; as
        # que sobram tem a coluna e um assunto que este *lint* nao sabe ler, e e
        # isso que a categoria passa a dizer.
        sem_assunto = [t for t in bloco.tabelas if t.especie == "sem_assunto"]
        if sem_assunto:
            nao_medidos.append(NaoMedido(
                bloco.id, f"{bloco.ficheiro}:{sem_assunto[0].numero}",
                "tabela com coluna `Estado` e sem coluna de assunto conhecida",
                "tem coluna `Estado` e o cabecalho "
                f"{' | '.join(sem_assunto[0].cabecalho)!r} nao diz se tabula os "
                "critérios ou a DoD"))
        else:
            nao_medidos.append(NaoMedido(
                bloco.id, bloco.onde,
                "sem tabela de verificacao com coluna `Estado`",
                "o bloco nao tem tabela de verificacao com coluna `Estado`"))
        return pares, nao_medidos

    def exigir(tabela: modelo.Tabela, caixas: list[modelo.Caixa],
               rotulo: str) -> None:
        onde = f"{bloco.ficheiro}:{tabela.numero}"
        if not caixas:
            nao_medidos.append(NaoMedido(
                bloco.id, onde, "tabela sem lista de caixas",
                f"tem tabela de {rotulo} e nao tem lista de caixas de {rotulo}"))
            return
        if len(tabela.estados) != len(caixas):
            nao_medidos.append(NaoMedido(
                bloco.id, onde, "tabela sem correspondencia um-a-um com a lista",
                f"a tabela de {rotulo} tem {len(tabela.estados)} linha(s) e a "
                f"lista tem {len(caixas)} caixa(s): sem correspondencia um-a-um "
                "nao se emparelha"))
            return
        pares.append(Par(rotulo, tuple(caixas), tabela.estados, onde))

    if tab_dod is not None:
        # Ha tabela de DoD propria: cada lista contra a sua.
        if tab_ca is not None:
            exigir(tab_ca, bloco.criterios, "critérios")
        exigir(tab_dod, bloco.dod, "DoD")
        return pares, nao_medidos

    # So a tabela de critérios: ela tabula os critérios, ou os critérios **e** a
    # DoD. Prova-se a primeira convencao e depois a segunda.
    onde = f"{bloco.ficheiro}:{tab_ca.numero}"
    linhas = len(tab_ca.estados)
    if linhas == len(bloco.criterios) and bloco.criterios:
        pares.append(Par("critérios", tuple(bloco.criterios), tab_ca.estados, onde))
    elif linhas == len(bloco.criterios) + len(bloco.dod) and bloco.criterios:
        pares.append(Par("critérios e DoD",
                         tuple(bloco.criterios) + tuple(bloco.dod),
                         tab_ca.estados, onde))
    elif not bloco.criterios:
        nao_medidos.append(NaoMedido(
            bloco.id, onde, "tabela sem lista de caixas",
            "tem tabela de verificacao e nao tem lista de caixas"))
    else:
        nao_medidos.append(NaoMedido(
            bloco.id, onde, "tabela sem correspondencia um-a-um com a lista",
            f"a tabela tem {linhas} linha(s) e nao casa nem com as "
            f"{len(bloco.criterios)} caixa(s) de critérios nem com as "
            f"{len(bloco.criterios) + len(bloco.dod)} de critérios mais DoD"))
    return pares, nao_medidos


def _comparar(bloco: modelo.Bloco, par: Par, dispensas: frozenset[str]
              ) -> tuple[list[Achado], list[NaoMedido]]:
    """A regra `estado_contra_caixa`, par a par."""
    achados: list[Achado] = []
    nao_medidos: list[NaoMedido] = []
    for indice, (caixa, estado) in enumerate(zip(par.caixas, par.estados), start=1):
        classe = modelo.classificar_estado(estado)
        if classe is None:
            nao_medidos.append(NaoMedido(
                bloco.id, f"{bloco.ficheiro}:{caixa.numero}",
                "o vocabulario nao classifica a celula de Estado",
                f"{par.rotulo} {indice}: a celula de Estado e "
                f"{modelo.limpo(estado)[:40]!r}, que o vocabulario nao classifica"))
            continue
        if classe != caixa.marcada and bloco.id not in dispensas:
            achados.append(Achado(
                "estado_contra_caixa", f"{bloco.ficheiro}:{caixa.numero}",
                f"{par.rotulo} {indice}: a caixa esta "
                f"{'marcada' if caixa.marcada else 'por marcar'} e a tabela diz "
                f"{modelo.limpo(estado)[:40]!r} "
                f"({'cumprido' if classe else 'por cumprir'})"))
    return achados, nao_medidos


def verificar(raiz: Path, dispensas: frozenset[str] = frozenset(),
              minimo_blocos: int = MINIMO_DE_BLOCOS,
              minimo_medidos: int = MINIMO_DE_BLOCOS_MEDIDOS
              ) -> tuple[list[Achado], list[NaoMedido], dict[str, int]]:
    """Corre as duas regras sobre todos os blocos.

    `dispensas` sao os `KAM-NNN` declarados em `ci/bloco-allow.yaml`: blocos que
    **ja divergiam antes deste *lint* existir**. Nao se corrigem aqui, e a razao
    esta escrita no ficheiro — a caixa segue a tabela, e a tabela e a evidencia
    daquele ticket e nao deste.
    """
    blocos = modelo.ler_blocos(raiz)
    if len(blocos) < minimo_blocos:
        raise ConfiguracaoInvalida(
            f"li {len(blocos)} bloco(s) e esperam-se pelo menos "
            f"{minimo_blocos}. Ou um glob ou a forma do titulo deixaram de "
            "ver a populacao — e «0 achados» sobre o vazio e a falha que este "
            "lint existe para recusar")

    achados: list[Achado] = []
    nao_medidos: list[NaoMedido] = []
    medidos = 0
    sem_assunto = 0
    for bloco in blocos:
        sem_assunto += sum(1 for t in bloco.tabelas
                           if t.especie == "sem_assunto")
        pares, n = emparelhar(bloco)
        nao_medidos += n
        for par in pares:
            a2, n2 = _comparar(bloco, par, dispensas)
            achados += a2
            nao_medidos += n2
        if pares:
            medidos += 1

    if medidos < minimo_medidos:
        raise ConfiguracaoInvalida(
            f"emparelharam-se {medidos} bloco(s) e esperam-se pelo menos "
            f"{minimo_medidos}. Uma mudanca na forma do cabecalho das "
            "tabelas poe este lint a medir quase nada e a dizer «0 achados»")

    numeros = {
        "blocos": len(blocos),
        "medidos": medidos,
        "achados": len(achados),
        "nao_medidos": len(nao_medidos),
        "tabelas_sem_assunto": sem_assunto,
        "dispensas": len(dispensas),
    }
    return achados, nao_medidos, numeros

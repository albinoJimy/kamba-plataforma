# Análise Adversarial do KAM-153 — referências a anexo sem prefixo, e a busca que as veja (ANALISE-21)

| Campo | Valor |
|---|---|
| Objecto | A primeira versão do KAM-153: a correcção das três referências a anexo citadas sem directório nenhum em `../../specs/EPIC-10_Spikes_Validacao_Gates.md:11`, o bloco do ticket em `../../specs/EPIC-01_Fundacoes_Dados.md`, as buscas novas, a emenda ao bloco do KAM-129, e o changeset como alteração documental. Três *commits* sobre `f4c7e3d`, o `main` de então. O ticket foi renumerado duas vezes depois desta revisão — pelos achados do §2 e pelo gate 4 do §5 — e o número final é o que o título diz; as medições desta análise foram feitas contra o conteúdo, não contra o identificador |
| Método | Dois revisores independentes, em paralelo, com âmbitos disjuntos e **sem acesso ao raciocínio de quem executou**: (A) a correcção e as verificações — podem as buscas dar 0 pela razão errada?; (B) o changeset como alteração documental — identificador, sincronia, contagens, regressão, convenções, caixas. Cada revisor re-mediu com instrumentos próprios, reimplementou as buscas a partir da descrição escrita em vez de copiar o código, e foi instruído a tratar cada número como alegação a falsificar. Achados classificados P0 (a afirmação engana) / P1 (evidência insuficiente ou imprecisa) / P2 (dívida ou imprecisão menor) |
| Data | 2026-10-12 |
| Classificação | Interno — auditoria |

---

## 1. Sumário executivo

**Veredicto: REPROVADO na primeira versão; APROVADO APÓS REMEDIAÇÃO.** Os dois
revisores reprovaram, de forma independente e por achados que se sobrepõem em
três dos cinco P0. **E a remediação do P0 mais importante estava ela própria
errada**, o que nenhum revisor viu e só o CI apanhou — §5.

A parte material do trabalho resistiu a tudo. Os dois revisores re-mediram o que
o ticket afirma sobre o defeito e as buscas, e **falharam em falsificar**: as
três referências e a sua pré-existência em `6d30625`, `G6 3 → 0`,
`G7 152 → 0`, as 17 ocorrências fora de *code-span*, o *diff* de uma linha com
líquido zero — um dos revisores verificou-o **caractere a caractere**: 582 → 660,
exactamente três inserções de 26 caracteres e nada mais —, `G1`/`G3` a 0, `G5`
com 8 falhas pré-existentes e 0 novas, a sincronia 144/144 campo a campo, as
contagens derivadas a fecharem entre si nos quatro sítios, o gate 3b sem
variantes novas, os finais de linha em LF, zero formas PT-BR e zero alterações
acidentais. Um dos revisores verificou ainda que a actualização do `README.md`
**não** invade o âmbito do KAM-130.

**O que reprovou foi o fecho, e o padrão é um só:** o ticket aplicou a sua
própria lição a toda a parte menos a si mesmo.

| P0 | O defeito | A ironia |
|---|---|---|
| 1 | O identificador escolhido não estava livre | O ticket gastou 50 linhas a provar com rigor que o número **anterior** estava tomado, varrendo todos os ramos. Aplicou esse rigor ao vizinho errado: três sessões escolheram o mesmo número em dez segundos |
| 2 | O gate 3 reprovava, por causa do ficheiro de evidência | A linha que afirmava «gate 3 conforme» era uma das três que o faziam reprovar. O documento explica que o varredor expande intervalos — e escreve três intervalos contínuos |
| 3 | A `ANALISE-21` era citada em dois documentos do canon e não existia | O ticket cuja tese é «uma referência que não resolve é defeito» escreveu duas, em ligação markdown, e **nem G6 nem G7 as apanham**: ancoram em nomes de anexo, não em caminhos em geral |
| 4 | O bloco era declarado «entregue» com as 17 caixas vazias e sem a secção de verificação que a evidência dizia existir | É a quinta repetição do defeito que a *skill* §5 relata quatro vezes: a diferença entre «entregue» e «fechado» a desaparecer sem ninguém decidir |
| 5 | O número de PR citado era o de outro ticket, e não havia PR | — |

E dois P1 que mudaram o desenho, não só o texto:

- **«As 152 são a população completa» e «cobre qualquer forma» eram falsos.** G7
  ancora na forma de nome de ficheiro; o universo em `specs/` é **181**, e as 29
  em forma-código ficavam fora **em silêncio**. É literalmente a frase que
  descreve o defeito do KAM-129 — uma busca ancorada numa forma, declarada
  completa — dita pelo ticket que existe para a desmontar.
- **O limite declarado («resolve só a partir da raiz é aceite por desenho») era
  uma racionalização.** Um revisor mediu: **zero** das 152 dependiam dessa
  permissão, e ela aceitava precisamente a forma que a regra de posição do
  KAM-128 declara errada. A remediação **reverteu o desenho**: resolução estrita,
  e o canário dessa forma passou de «passa» a «apanhado».

Distribuição: **P0 ×5 · P1 ×5 · P2 ×6**. Todos remediados na segunda versão,
com o registo em `../evidencia/KAM-153.md` §7.

---

## 2. Achados P0

### ADV-17-01 · O identificador não estava livre, e o comando citado como prova devolvia o contrário

**O que o trabalho dizia.** «Livre em todos os ramos, locais e remotos, e em
todos os PRs abertos», com o comando de varredura transcrito e o resultado
`-> vazio`.

**O que as revisões mediram.** O mesmo comando, verbatim, no mesmo *worktree*,
devolvia **três** ramos. Dois deles já escreviam o identificador na linha 71 do
`../../specs/EPIC-01_Fundacoes_Dados.md` e na linha 114 do
`../../specs/INDICE.md` — o mesmo ID com títulos, estimativas e dependências
diferentes. Um dos dois abria ainda os dois identificadores seguintes.
Ordenando os ramos por data de *commit*, os três estão a **cinco e dez
segundos** um do outro.

**Consequência.** O segundo a fundir produz conflito ou, se alguém resolver o
conflito a favor de um lado, um ID duplicado ou um bloco silenciosamente
perdido — e o gate 3 não detecta duplicados. O requisito explícito «confirmar
que o identificador está realmente livre» não estava cumprido.

**O achado de fundo, que é maior do que a renumeração.** Varrer *refs* é uma
**corrida, não uma reserva**. O comando estava certo e o resultado era verdadeiro
no instante em que correu; o defeito foi apresentá-lo como facto apurado.
Nenhuma varredura torna um identificador seguro — torna-o livre naquele
instante.

**Remediação:** renumerado para o primeiro identificador confirmado livre, com a
varredura repetida imediatamente antes de escrever. O §2 da evidência foi
reescrito para **declarar a janela e dizer de quem é a resolução** em vez de
prometer unicidade, e para registar que os intervalos descontínuos do índice
passarão a omitir tickets quando os ramos reservados fundirem — colisão mecânica
num ficheiro de registo, não uma afirmação que caduca em silêncio.

### ADV-17-02 · O gate 3 reprovava, e a linha que o declarava verde era uma das causas

**O que o trabalho dizia.** «Gate 3 — referências cruzadas | conforme →
conforme | `… referencias em 552 ficheiros`».

**O que as revisões mediram.** Os dois revisores correram o gate em `HEAD` e
obtiveram **3 referências inválidas**, as três no próprio ficheiro de evidência,
e código de saída 1. Um deles correu-o também nos dois primeiros *commits*, onde
dá conforme: **a regressão entra com o terceiro *commit***, o que acrescenta o
ficheiro de evidência. O CI corre este gate, pelo que o PR não fundiria.

**Mecanismo.** O varredor **expande intervalos de série**. O ficheiro escrevia o
intervalo contínuo três vezes — duas em prosa e uma a transcrever a saída do
próprio gate —, e um intervalo contínuo afirma todos os identificadores que
contém, incluindo os reservados que não existem no §4. Nenhuma entrada em
`../../ci/refs-allow.yaml` os cobria, e a própria evidência argumentava —
corretamente — contra criar uma.

**A impressão digital.** A evidência declarava `552 ficheiros`; os revisores
mediram **553**. O número publicado só é obtível num estado da árvore que
**exclui o ficheiro que o publica**: o gate foi corrido antes de o ficheiro
existir e nunca re-corrido. Foi por aqui que um dos revisores chegou ao achado.

**A ironia, que é o que dá valor ao achado.** O documento **explica** que o
varredor expande intervalos, e explica isso para justificar ter tornado
descontínuos os intervalos do `../../specs/INDICE.md`. A lição foi aplicada ao
índice e não ao ficheiro que a enuncia.

**Remediação:** os três intervalos reescritos; o gate re-medido com o ficheiro na
árvore; e a regra escrita na evidência — «um gate que lê a árvore mede-se depois
de a árvore estar completa, e a contagem de ficheiros confere-se contra
`git ls-files`».

### ADV-17-03 · Duas referências quebradas escritas pelo próprio ticket, e invisíveis às suas buscas

**O que o trabalho dizia.** Duas ligações markdown, uma na linha de versão do
epic e outra no ficheiro de evidência, a apontar para esta análise.

**O que as revisões mediram.** O ficheiro não existia, e nenhum *commit* do
changeset tocava `../analises/`. Um revisor notou o contraste: outra análise
também não existe na árvore, mas **não é citada em parte nenhuma** — logo este
era defeito novo, não herdado.

**Consequência.** Caminho quebrado escrito por este ticket num documento formal
do canon, o que torna a sua caixa de DoD «todo o caminho que **este** ticket
escreve resolve» falsa à letra. E — o que importa mais — **nem G6 nem G7 o
apanham**: ancoram em nomes de anexo `E1`–`E5`, não em caminhos `.md` em geral. É
o mesmo buraco de busca que o ticket fecha, um nível acima.

**Remediação:** este ficheiro. E, no fecho, um resolvedor sobre **todas** as
linhas novas do changeset — 38 caminhos distintos, 0 que não resolvam —, que é a
verificação que faltava e que agora está na secção de verificação do bloco.

### ADV-17-04 · «Entregue» com as dezassete caixas vazias

**O que o trabalho dizia.** Linha de versão do epic: «acrescentado **e
entregue**». Ficheiro de evidência: «a leitura critério a critério está no bloco,
secção "Verificação dos Critérios de Aceitação"».

**O que as revisões mediram.** As 10 caixas de Critérios de Aceitação e as 7 de
Definition of Done estavam **todas** vazias, e a secção não existia. Um revisor
varreu os 30 blocos do epic por fronteiras de bloco: os 15 blocos entregues têm
todos a secção e caixas marcadas; os não executados têm `0/0/N`. **O bloco novo
era o único declarado entregue com a forma de não executado.**

**Consequência, e é a inversa da habitual.** Não havia nenhuma caixa marcada sem
evidência — havia **15 das 17 que um revisor conseguiu demonstrar sozinho** e que
ficaram vazias sem explicação. Três documentos do mesmo changeset diziam três
coisas diferentes sobre o estado do ticket.

**Remediação:** secção escrita, com uma linha por critério — o que se mediu, com
que comando, e o número que saiu —, as caixas marcadas com evidência nomeada, e
a dos revisores humanos vazia e nomeada.

### ADV-17-05 · O número de PR era de outro ticket

A tabela de cabeçalho da evidência citava um número de PR que, consultado,
pertence a outro ticket; não existia PR para o ramo e o ramo não estava
publicado. **Remediado** no fecho.

---

## 3. Achados P1

### ADV-17-06 · «População completa» e «qualquer forma»: a família forma-código ficava de fora em silêncio

**O que o trabalho dizia.** «As 152 são a população completa» e «cobre qualquer
forma de prefixo, e qualquer contexto».

**O que as revisões mediram.** G7 ancora em `E[1-5]_…\.md` — **só** na forma de
nome de ficheiro. Em `specs/`, fora do ficheiro excluído, há **17** citações em
forma-código com prefixo e **12** nuas: **29** que nem G6, nem G7, nem G1 vêem.
O universo é **181**, não 152. Um revisor construiu o caso e confirmou que uma
citação nua em forma-código atravessa as quatro buscas.

**Consequência.** «Uma busca ancorada numa forma, declarada completa» é
literalmente a frase que descreve o defeito do KAM-129. O ticket repetiu-a sobre
si mesmo. Acresce que **três das 12 nuas tinham sido escritas pelo próprio
changeset**, na linha de «Controlo de versões» do `specs/EPIC-10`, ao nomear os
anexos pelo código.

**A disposição, que não é «corrigir».** As citações em forma-código **não são
caminhos**: `` `E3` §7 `` é uma referência por abreviatura, com legenda no
documento. Não levam prefixo e quem lhes acrescentar um estraga texto correcto —
duas delas são intervalos `E1`–`E4` e pertencem ao C3 do KAM-130. **Remediação:**
a população passou a declarar-se «152 de 181», as 29 ficaram contadas por uma
busca própria (G9) e localizadas uma a uma, a forma foi **nomeada no canon** como
legítima na emenda ao bloco do KAM-129 — para que nenhum executor a «corrija» —
e a linha de versão do `specs/EPIC-10` foi reescrita sem citar código nenhum: 9
nuas antes, 9 depois.

### ADV-17-07 · O limite declarado do resolvedor era uma racionalização, e contradizia o próprio ticket

**O que o trabalho dizia.** O resolvedor aceita o directório do ficheiro **e** a
raiz do repositório; um caminho que resolva só a partir da raiz «não é defeito e
não é apanhado — limite declarado, não omissão», justificado pelas citações de
irmãos e pelos blocos de *handoff*.

**O que a revisão mediu.** Com um resolvedor próprio que separa os três estados:
**`so-da-raiz = 0`** nas 152 ocorrências. Um resolvedor estritamente relativo dá
o mesmo `0/152`. As «citações de irmãos» que justificavam a permissão **não
estão nesta população** — G7 só olha para nomes de anexo. No repositório inteiro
há 7 ocorrências nesse estado, examinadas uma a uma: cinco são etiquetas num
ficheiro de *skill*, uma é o **texto** de uma ligação cujo alvo está certo, uma é
prosa a descrever uma ligação. **Zero defeitos reais.**

**Consequência.** A justificação escrita não se aplicava a nenhuma ocorrência
medida — era racionalização, não medição. E **contradizia os Detalhes Técnicos do
mesmo bloco**, que declaram errada exactamente a forma que a verificação aceitava:
um caminho sem o `../`, que resolve da raiz e quebra na renderização do GitHub.

**Remediação: o desenho foi revertido.** Resolução estritamente relativa ao
ficheiro. O canário dessa forma passou de «passa» a **apanhado**, e o `0/152` não
mudou.

### ADV-17-08 · «Verdadeira à letra» não se sustenta: o CA1 do KAM-129 continua falso

**O que o trabalho dizia.** Na emenda ao bloco do KAM-129 e na decisão 3:
«depois dele a afirmação do CA1 passa a ser verdadeira à letra».

**O que a revisão mediu.** O CA1 diz «zero referências a evidência **sem
directório qualificador** em `specs/`». As 12 citações em forma-código nua são
exactamente isso — sem directório qualificador —, e uma delas é a linha de
versão que o changeset acabou de escrever.

**Consequência.** A emenda substituía o predicado do critério: o CA1 fala de
«sem directório qualificador», a emenda provava «0 que não resolvam». São
afirmações diferentes, e a primeira continua literalmente falsa — e **tem de
continuar**, porque as referências por abreviatura não devem levar directório
nenhum.

**Remediação:** a frase foi retirada. A emenda passa a dizer que, à letra, o CA1
continua falso por causa das 9 referências por abreviatura, que satisfazê-lo
exigiria redefini-lo, e que essa decisão é de quem o escreveu. Reforça — em vez
de enfraquecer — a decisão de **não** remarcar as caixas.

### ADV-17-09 · O `0` do resolvedor era, numa dimensão, artefacto da máquina

**O que a revisão mediu.** G7 usava `Path.exists()` e correu em **Windows**, onde
a resolução é insensível a maiúsculas; o CI corre em Linux. Um prefixo com a
grafia errada passava na máquina de quem mede e reprovaria no CI. O revisor
mediu-o com resolução componente a componente por `os.listdir` — e **não** com
`Path.resolve()`, que no Windows canonicaliza a grafia e esconde o problema —
obtendo **0** ocorrências com divergência de grafia em `specs/` e **0** no
repositório inteiro. O defeito não é vivo; o `0` era parcialmente artefacto.

**Remediação:** resolução por `os.listdir`, componente a componente, com a razão
escrita. O canário dessa forma passou a ser apanhado.

### ADV-17-10 · O resolvedor confundia o texto de uma ligação com o seu alvo

A caminhada para trás parava no delimitador de *code-span* ou no `[`, pelo que o
**texto** de uma ligação markdown era lido como caminho, produzindo uma **falha
falsa**. Reproduzido por um revisor como caso inventado. Não disparava na
população — `specs/` tem **0** ligações markdown a anexo, o que de resto valida
uma afirmação do KAM-129 — mas invalidava a frase «cobre … ligação markdown»:
esse contexto nunca tinha sido exercitado, e no único sítio do repositório onde a
forma existe o resolvedor errava o sinal. **Remediado:** as ligações tratam-se
primeiro, pelo alvo.

---

## 4. Achados P2

1. **O canário provava menos do que aquilo que sustentava.** Quatro casos, usados
   para afirmar «qualquer forma e qualquer contexto». Um revisor correu dez
   casos, dos quais três revelaram defeito (ADV-17-07, 09 e 10). **Remediado:** o
   canário passou a nove formas, com o resultado de cada uma escrito no bloco,
   incluindo as duas que passam e porquê.
2. **O resíduo 20 generalizava para onze o que era verdade para sete.** Medido
   ficheiro a ficheiro: 7 dos 11 epics têm a tabela de versões à frente do
   cabeçalho; nos outros 4 não há desvio nenhum. **Remediado** na linha de
   dívida.
3. **A dívida 4 ficou a citar um número que este changeset tornou velho.**
   Dizia «histórico até 1.8»; o changeset acrescentou a linha 1.10 ao mesmo
   ficheiro. Tocar o ficheiro das dívidas sem refrescar a dívida que se acabou de
   alargar. **Remediado.**
4. **Uma terceira superfície de sincronia que a medição não cobria.** A §3
   «Tabela Resumo de Tickets» de cada epic é uma terceira cópia dos campos; no
   `EPIC-01` tem 28 linhas para 30 tickets. É pré-existente e é a dívida 3, e o
   changeset fez a coisa certa ao acrescentar lá a sua linha — mas a frase «0
   divergências» escondia-a. **Remediado:** a afirmação passou a declarar que
   vale para o §4 ↔ blocos, e a terceira superfície está nomeada com a sua
   dívida.
5. **A contagem de ramos do identificador anterior estava subcontada** («2
   ramos» para três). **Remediado.**
6. **Se as buscas novas subissem a gate, a exclusão deixaria de ser de um
   ficheiro.** Dentro de `specs/` a exclusão de um só ficheiro é necessária e
   suficiente — um revisor verificou as suas ocorrências uma a uma e **nenhuma é
   referência real**. Fora de `specs/`, a classe falha também no anexo de análise
   que inventariou o defeito e no ficheiro de evidência que transcreve o canário:
   três exclusões, não uma. **Remediado** como nota na decisão de não acrescentar
   gate.

---

## 5. O que os revisores não apanharam, e o CI apanhou

Esta secção existe porque um relatório de revisão que só liste o que a revisão
encontrou mede mal o seu próprio alcance.

### ADV-17-17 · A remediação do ADV-17-01 estava errada, e nenhum dos dois revisores o viu

O ADV-17-01 apurou que o identificador escolhido estava tomado por três ramos
concorrentes. A remediação varreu outra vez todos os ramos e **saltou para o
primeiro número livre acima de todos**, três acima do maior do `main`,
documentando a decisão com rigor: a corrida declarada, os intervalos de série
escritos descontínuos para o gate 3 não reprovar, a janela de instabilidade
assumida.

**O gate 4 do CI reprovou.**

```text
FALHA: lint_refs
FAIL: test_kam_cobre_o_backlog_inteiro_sem_buracos
```

```python
numeros = sorted(int(x[4:]) for x in self.conjuntos.kam)
self.assertEqual(numeros[0], 1)
self.assertEqual(numeros, list(range(1, numeros[-1] + 1)), "o backlog nao tem buracos")
```

**Não existe «próximo número livre» neste repositório.** O conjunto lido do §4
tem de ser `1..máximo`. Com o gate 3 a reprovar quem cite um identificador que
não esteja no §4, as duas regras deixam exactamente uma escolha: **o seguinte ao
maior do `main`**. Toda a construção da segunda versão — varrer ramos para
escolher, declarar a janela, escrever intervalos descontínuos — era arquitectura
sobre uma premissa falsa. A consequência verdadeira é mais simples e mais dura:
**ramos concorrentes colidem sempre neste número, por construção**, e a colisão
resolve-se na integração, renumerando quem fundir depois.

**Porque é que os dois revisores não o apanharam, e isso é o achado de método.**
Os dois correram «os gates que lêem documentos» — 3, 3b, `lint_arch` — e
declararam, nas suas secções «o que não revi», que não corriam o gate 4 por ser
de testes e cobertura. A regra que o ticket violava vivia num **teste unitário do
`lint_refs`**, não no gate de referências. Um revisor verificou com rigor que não
havia buracos de **reciprocidade** no grafo e que as contagens fechavam; nenhum
perguntou se o **conjunto de identificadores** podia ter buracos. A lição: *ter
corrido os gates que parecem relevantes não é o mesmo que ter corrido os gates*,
e num repositório onde uma regra de canon pode viver num teste unitário, a
varredura por relevância aparente deixa buracos — do mesmo tipo, aliás, que o
defeito que este ticket fecha.

### Dois efeitos do `main` ter avançado durante a revisão

Não são achados de revisão, mas falsificaram medições que esta análise confirmara:

1. **G5 passou de «8 falhas» a 0.** As oito arestas de reciprocidade que os dois
   revisores confirmaram como dívida 2 pré-existente foram fechadas por outro
   ticket, que fundiu entretanto. A linha de evidência que dizia «8 antes, 8
   depois» era verdadeira e deixou de o ser: refeita contra o `main` novo.
2. **O número desta análise e a linha de versão do epic foram tomados.** Um
   ticket levou o `ANALISE-16` e a versão `1.17`; esta análise é a **17** e a
   linha ficou na **1.20** depois de mais duas fusões. É a colisão mecânica de
   ficheiro de registo — o mesmo fenómeno do identificador, à escala dos
   ficheiros em vez dos tickets.
3. **O identificador do ticket mudou quatro vezes.** 145 → 148 → 145 → 148 →
   151, porque o `main` avançou quatro vezes e o identificador é obrigatoriamente
   o seguinte ao seu máximo. Dois PRs foram fechados por isso, e à quarta deixou
   de se renomear o ramo — renomeá-lo custa outro PR. O custo está registado em
   `../evidencia/KAM-153.md` §2, com a observação de que a solução é de processo
   — reservar o identificador ao abrir o ramo, ou numerar só na integração — e
   que essa é decisão do fundador, não deste ticket.
4. **Dois dos achados P2 desta análise foram absorvidos pelo `main`.** Os resíduos
   da linha de versão 1.13 e do campo `Versão` do cabeçalho, que esta análise
   mandou registar, foram registados entretanto por outro ticket (linha 21 das
   dívidas). Não se repetem; em troca entra uma falha de reciprocidade nova e
   pré-existente no `main`, que nenhum gate vigia porque a vigilância é do
   KAM-138.

---

## 6. O que os revisores confirmaram

Registado porque um veredicto de reprovação sem isto deixaria a impressão errada
sobre o que estava certo.

| Afirmação | Medição independente |
|---|---|
| Três referências nuas na linha 11, pré-existentes | resolvedor próprio em `6d30625` e em `f4c7e3d`: 3 nos dois |
| `G6 3 → 0` | confirmado nos dois estados |
| `G7 152/3 → 152/0` | confirmado, com resolvedor reimplementado a partir da descrição escrita |
| «17 fora de *code-span*» | 135 dentro + 17 fora = 152, e as 17 são prosa em blocos de *handoff* |
| *Diff* de uma linha, líquido zero, forma inalterada | `--numstat` `2 1`; diferença caractere a caractere: 582 → 660, exactamente 3 × 26 |
| `G1 = 0`, `G3 = 0`, antes e depois | confirmado |
| `G5`: 143 → 144 blocos, 8 falhas antes e depois | confirmado; as 8 são a dívida 2; par KAM-129↔KAM-153 recíproco nos dois sentidos |
| Sincronia §4 ↔ blocos, campo a campo | 144/144, 0 divergências; 0 blocos duplicados; 0 linhas duplicadas no §4 |
| Ciclos, prioridade e fase invertidas | 0, 0, 0 |
| Contagens derivadas coerentes nos quatro sítios | §4 = blocos = §3.1 = §1 = `README.md` = 144; cada intervalo declarado expande-se ao conjunto do seu epic |
| `README.md` a 144 não invade o KAM-130 | o C4 nomeia outros dois ficheiros, e a busca H4 espera do `README.md` a contagem vigente |
| Gate 3b, 17 ficheiros / 31 ocorrências | confirmado nos dois lados: 0 variantes novas |
| `lint_arch all`, `branch`, `commit-msg` | conforme; 3 de 3 mensagens |
| Finais de linha | `i/lf w/lf` em todos os ficheiros tocados; `--ignore-all-space` idêntico ao normal |
| Nenhuma alteração acidental | os *hunks* estão todos onde deviam; nenhum ficheiro alterado por inteiro |
| Zero formas PT-BR nas linhas novas | confirmado |
| Resíduos 19 e 20 verdadeiros, e bem classificados como dívida | a linha 1.13 não existe em ramo nenhum; o 20 com a correcção do P2-2 |
| Nenhuma referência desta classe com defeito fora de `specs/` | 103 ficheiros, 265 ocorrências, 23 falhas — todas citações do defeito para o nomear |

---

## 7. O que não foi revisto

- **Nenhuma revisão humana.** Esta análise é produzida por agentes e **não conta
  como revisor** para efeitos do DoD. Continua a faltar ≥ 1 revisor humano.
- **A adequação dos critérios**, por oposição ao seu cumprimento. Nenhum revisor
  perguntou se as caixas do bloco cobrem o objectivo do ticket.
- **Os ~43 caminhos de entregas futuras** e a redacção da caixa de DoD
  «Referências» que os devia cobrir: fora de âmbito por decisão do pedido.
  Nenhum revisor verificou a contagem «~43» nem a sua enumeração na
  `ANALISE-04`, e nenhum contestou a decisão de os não corrigir — apenas se
  registou que a decisão de não acrescentar gate depende dela.
- **As contagens herdadas (KAM-130)**, além do necessário para decidir que a
  actualização do `README.md` não invade esse âmbito.
- **Código, CI, migrações e prova por mutação.** O changeset são seis ficheiros
  `.md`. Correram os gates que lêem documentos (3 e 3b), o `lint_arch` e o
  *scanner* de segredos.
- **O estado do CI no PR**, que à data desta análise não existia.
- **O conteúdo dos anexos `E1`–`E5`**: verificou-se que os caminhos resolvem,
  nunca que o que é citado lá está.
- **A segunda e a terceira versões não foram revistas por um terceiro revisor
  independente.** As remediações foram verificadas por quem as fez, com os mesmos
  instrumentos, e as medições estão em `../evidencia/KAM-153.md`. É evidência mais
  fraca do que a dos achados, e fica dito — tanto mais que a remediação do
  ADV-17-01 estava errada e foi o CI, não uma revisão, a apanhá-la (§5).
- **Nenhum revisor correu o gate 4** (testes e cobertura), por instrução e por o
  julgarem irrelevante para um changeset documental. Foi exactamente aí que estava
  a regra violada. Os gates que precisam de Docker ou de Node continuam não
  corridos.

---

## 8. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.1 | Outubro 2026 | Acrescentado o §5: a remediação do ADV-17-01 estava errada — o gate 4 do CI reprovou-a por um teste que proíbe buracos na numeração do backlog, regra que nenhum dos dois revisores podia ver porque nenhum correu esse gate. E os dois efeitos do `main` ter avançado durante a revisão. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | Quarta renumeração do ticket (151) e dois efeitos novos do `main` ter avançado: os dois resíduos P2 desta análise foram absorvidos por outro ticket, e apareceu uma falha de reciprocidade pré-existente que nenhum gate vigia. | Equipa KAMBÁ |
| 1.0 | Outubro 2026 | Emissão inicial: duas revisões adversariais independentes do KAM-153, em âmbitos disjuntos. Ambas reprovaram a primeira versão. 5 achados P0 (identificador tomado por sessões concorrentes, gate 3 vermelho pelo ficheiro de evidência, análise citada e inexistente, ticket declarado entregue com as caixas vazias, número de PR de outro ticket), 5 P1 (dois dos quais mudaram o desenho do resolvedor) e 6 P2. Todos remediados, com o registo em `../evidencia/KAM-153.md` §7. | Equipa KAMBÁ |

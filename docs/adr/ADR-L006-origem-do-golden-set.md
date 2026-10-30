# ADR-L006 — A origem do *golden set*: valem as três origens do KAM-040

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-30 |
| Ticket | KAM-169 — A origem do *golden set* no canon: as três do KAM-040 |
| Âmbito | Local (ver [`README.md`](README.md)): **qual dos dois lados do canon vale** sobre a origem dos casos do *golden set* do KAM-040. Não especifica o dataset (é o **KAM-040**), não constrói o *gate* 13 (é o **KAM-040**), não decide o enquadramento legal (é o parecer do **KAM-104**) e não emenda o ADR-018 |
| Decisores | **O fundador, a 2026-10-30**, sobre a divergência que a revisão adversarial do KAM-104 mediu |
| ADRs canónicos aplicáveis | ADR-018 (observabilidade leve e proibição de treino com dados do WhatsApp), ADR-008 (transferências) |
| Documentos aplicáveis | [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) §8 e §11; [`../tecnica/10_Onboarding_Governanca.md`](../tecnica/10_Onboarding_Governanca.md) §11.2, §11.3, §18 e §20.1; [`../logs.md`](../logs.md) §9; [`../concierge.md`](../concierge.md); [`../tecnica/02_Agent_Runtime_Verticais.md`](../tecnica/02_Agent_Runtime_Verticais.md) §16.2; [`../../specs/00_KAMBA_Carta.md`](../../specs/00_KAMBA_Carta.md) §4.1; [`../../specs/EPIC-03_Agent_Runtime_Verticais.md`](../../specs/EPIC-03_Agent_Runtime_Verticais.md) bloco KAM-040; [`../../specs/EPIC-06_Indice_Pesquisa.md`](../../specs/EPIC-06_Indice_Pesquisa.md) bloco KAM-064; [`../../specs/EPIC-10_Spikes_Validacao_Gates.md`](../../specs/EPIC-10_Spikes_Validacao_Gates.md) bloco KAM-109 |
| Substitui | — (**não** substitui o ADR-018; ver «Isto não é substituição de ADR») |

## Contexto

O *golden set* é o conjunto de avaliação que gateia *deploys* dos artefactos
comportamentais (grafos, *prompts*, *tools*, registo, política, alias de modelo),
e o *gate* 13 que o corre **não existe**: nasce com o **KAM-040**. A sua ausência
já deixou a caixa do «eval-gate» vazia em tickets entregues
([`../../specs/EPIC-03_Agent_Runtime_Verticais.md`](../../specs/EPIC-03_Agent_Runtime_Verticais.md),
blocos KAM-037, KAM-034 e KAM-114).

A **origem** dos casos desse conjunto estava escrita em dois sentidos opostos, e
a divergência foi encontrada pela revisão adversarial do **KAM-104** (pacote de
perguntas para o parecer jurídico). A tensão mais incómoda estava **dentro de um
só documento**: a célula do ADR-018 em `../tecnica/00` §8 dizia «Golden set por
reescrita sintética», e a premissa «Dados da Meta e ML» do §11 do **mesmo
documento** dizia «reescrita sintética **e** por casos autorizados pela PME», as
duas a citar o ADR-018.

### As duas leituras

| Leitura | O que afirma | Qual é a defesa perante os Termos da Meta §4.7 |
|---|---|---|
| **A** — só reescrita sintética | O *golden set* não contém material real; as conversas resolvidas entram como reescritas sem dados pessoais | **A exclusão.** Não há material real no conjunto, logo não há uso de dados do WhatsApp para «melhorar» nada |
| **B** — material real com consentimento | O *golden set* admite três origens, e um caso real entra **só** com consentimento, base legal e registo | **A barreira.** O que os Termos proíbem é *criar, desenvolver, treinar ou melhorar* ML; a avaliação com consentimento específico e base legal é uma questão distinta, e é essa que o parecer resolve (L-G1, E1 Q7) |

A **A** é mais segura de afirmar e mais pobre de medir: um conjunto só sintético
não mede qualidade em português de Angola sobre o que os clientes escrevem, que é
precisamente o que está **NÃO VERIFICADO** e que este conjunto existe para medir
(`../tecnica/02` §19, L1–L3). A **B** mede isso e paga-o com uma barreira que tem
de ser imposta por máquina, não por intenção.

### As vinte linhas, medidas em três passagens

Medido em `main` (`fd0a32d`) e, para as duas últimas, na árvore depois de o PR #93
fundir (`7426abf`). **E a contagem subiu em cada passagem, o que é o assunto deste
ADR a repetir-se sobre si próprio:**

```text
o enunciado que chegou ao ticket          7 linhas
a medição deste ticket                   17   (buscas melhores; ver abaixo)
a revisão adversarial + a base a mexer   20   (duas reclassificadas, uma nova)
```

Nenhum dos três números estava a esconder nada: os três eram o que o instrumento
daquela passagem via. **A lição não é «conta melhor», é que uma enumeração que se
declara completa envelhece** — e esta declara-se completa à data acima, não para
sempre. As três buscas que falharam na primeira passagem, e porquê:

```text
grep -rnE "golden.{0,120}reescrita sint|reescrita sint.{0,120}golden"
  perde o §11.2 de `../tecnica/10`  — 120 caracteres entre as duas expressões
  perde o §11.3 e a PA-GOV-4        — dizem «reescritaS sintéticaS», no plural
  perde a Carta e as glosas         — dizem «golden sintético», sem «reescrita»
```

**Afirmam só reescrita sintética (catorze):**

| Onde | Estado |
|---|---|
| `../tecnica/00` §8, célula do ADR-018 | corrigida neste PR |
| `../logs.md` §9, última regra | corrigida neste PR |
| `../tecnica/10` §18, linha de risco | corrigida neste PR (o risco **mantém-se**; muda a mitigação) |
| `../tecnica/10` §11.2, o pipeline | corrigida neste PR — lia-se como o pipeline do conjunto, e passa a dizer que é o da reescrita sintética de casos T2 **sem fechar** o rótulo de `origem`, porque o canon tem duas respostas: o KAM-109 do `../../specs/EPIC-10` (fundido no #93) diz `t2_anonimizado` e três linhas mais antigas dizem `sintetico`. Fecha-o o **KAM-040** |
| `../tecnica/10` §11.3, cláusula (a) | corrigida neste PR |
| `../tecnica/10` §20.1, **PA-GOV-4** | corrigida neste PR |
| `../../specs/00_KAMBA_Carta.md` §4.1, linha do ADR-018 | corrigida neste PR; é a fonte de verdade de **nível 1** e repetia a abreviação um nível acima |
| `../concierge.md`, «O *golden*, e o que a Meta proíbe» | corrigida neste PR — atribuía ao §11.3 do `10` a conclusão **oposta** à que ele passou a tirar. A primeira versão desta página classificou-a entre as que «não são contradição», e **é**: achado da revisão adversarial |
| `../../specs/EPIC-10` bloco KAM-109, «Detalhes Técnicos» | **PR #93** (KAM-104), fundido em `7426abf` — não tocada aqui |
| `../../specs/EPIC-03` §1, glosa «ADR-018 (golden sintético…)» | dívida documental **157**: resíduo textual, fora do âmbito |
| `../../specs/EPIC-10` §1, glosa «ADR-018 (golden sintético…)» | dívida documental **157**; o PR #93 não a toca |
| `../../specs/EPIC-06` bloco KAM-064, glosa no *handoff* | dívida documental **157** |
| `../../specs/EPIC-03` bloco KAM-114, Contexto | dívida documental **157** — «o dataset golden recebe reescritas sintéticas das decisões, **nunca cópias de conversas**»: «das decisões» circunscreve a frase à exportação do concierge, mas o universal que sobra lê-se como contrário à decisão. Achado da revisão adversarial |
| `../tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md`, «Por que importa» do KAM-040 | **corrigida neste PR** — glosa «dataset **golden sintético** e eval harness como gate», que chegou com o PR #93 depois de esta página ser escrita. Passou a nomear as três origens no mesmo PR que lhe acrescentou a quinta variante da pergunta F-03 |

**Admitem material real com consentimento (seis), e nenhuma muda:**

| Onde | O que diz |
|---|---|
| `../tecnica/00` §11, premissa «Dados da Meta e ML» | «reescrita sintética **e** por casos autorizados pela PME (ADR-018)» |
| `../../specs/EPIC-03` bloco KAM-040, critério 1 | `origem ∈ {sintetico, t2_anonimizado, real_consentido}` e nenhum `real_consentido` sem registo de consentimento |
| `../../specs/EPIC-03` bloco KAM-040, Contexto | «o dataset é **sintético** (reescrita) e, só com consentimento e base legal, caso real (L-G1)» |
| `../../specs/EPIC-03` §R5, tabela de riscos | «Golden sintético; real só com consentimento e parecer» |
| `../../specs/EPIC-06` bloco KAM-064, Contexto | conversas reais entram «**pseudonimizadas e reescritas sinteticamente**, com consentimento específico para avaliação» |
| `../tecnica/02` §16.2, regra (4) | as três origens em prosa, com a cláusula §4.7 marcada «a confirmar por parecer (L-G1)» |

**Dois sítios dizem `sintetico` e não são contradição**, porque falam de uma
origem concreta e não do conjunto: a **exportação de candidatos do concierge** (o
critério 7 do KAM-114 em `../../specs/EPIC-03` e a sua verificação, o
`../../specs/02_Dicionario_de_Dados_Canonico.md` §3.34, e o trecho do
`../concierge.md` que descreve o comando — exportam **só metadados** e entram com
`origem=sintetico` por desenho) e o ***golden* dos módulos do dono**
(`../../specs/EPIC-11`), que é um dataset distinto do KAM-040.

**Esta tabela foi corrigida pela revisão adversarial, e isso fica dito.** A
primeira versão contava **dezassete** linhas e **quatro** sítios não
contraditórios; a revisão mostrou que dois desses sítios — a linha do
`../concierge.md` e o Contexto do KAM-114 — são afirmações sobre o **conjunto** e
não sobre uma origem, e a fusão do PR #93 trouxe uma glosa nova. Classificar uma
contradição como «não sendo uma» é pior do que não a medir, porque fecha a
pergunta.

## Decisão

**Valem as três origens do KAM-040 — `sintetico`, `t2_anonimizado` e
`real_consentido` —, com registo de consentimento obrigatório para os casos
reais.** Leitura **B**. Decidida pelo fundador a **2026-10-30**.

## Isto não é substituição de ADR, e a verificação está aqui

A regra desta casa é que não se contradiz um ADR em vigor sem o substituir
explicitamente, e substituir um ADR canónico é decisão do fundador — não do
executor. **A leitura escrita, antes de se emendar a célula:** a célula da tabela
do §8 não é o ADR-018 a dizer algo que agora deixa de valer; é a **metade
abreviada** do que o próprio documento já afirmava trinta linhas abaixo. Três
factos medidos sustentam-no:

1. **A premissa do §11 do mesmo documento atribui ao ADR-018 as duas metades** —
   «reescrita sintética **e** por casos autorizados pela PME (ADR-018)». Logo o
   ADR-018, como o `../tecnica/00` o registra, **já** admitia casos autorizados: a
   célula do §8 é que os perdeu.
2. **A razão escrita na célula continua verdadeira e não é tocada.** Os Termos da
   Meta §4.7 proíbem «criar, desenvolver, treinar ou melhorar» sistemas de ML com
   dados do WhatsApp. É uma proibição sobre **treino**, e nenhuma das três origens
   treina ou afina modelo nenhum — o que a decisão muda é a origem do conjunto de
   **avaliação**. As cláusulas (b), (c) e (d) do §11.3 de `../tecnica/10` ficam
   intactas por isso mesmo. **Mas esta leitura é nossa, e leva marcador:** que
   «avaliar com consentimento» não caia dentro de «melhorar» é
   **(a confirmar por parecer)** e continua **NÃO VERIFICADO** (L-G1, E1 Q7). O
   que esta alínea estabelece é que a razão do ADR-018 é **compatível** com as
   três origens, não que o enquadramento está resolvido — a primeira versão desta
   página escrevia-a sem marcador, e isso é pôr uma defesa jurídica no canon como
   facto (achado da revisão adversarial).
3. **O estado do ADR-018 não muda.** Continua **FIXA** na Carta §4.1, sem gatilho
   de reabertura, e não entra nem sai nenhum ADR de `../tecnica/00` §8 — pelo que
   a contagem de ADRs e o mapeamento ADR → documento de `../tecnica/INDICE.md` §5
   ficam como estão (**vinte**, `ADR-001` a `ADR-020`).

Se a leitura fosse a outra — a célula do §8 como o ADR-018 verdadeiro e o §11
como erro —, isto seria substituição de ADR e **paráva aqui**, com a pergunta
devolvida ao fundador. Não é, e a diferença mede-se: o §11 nomeia o ADR-018 e
diz as duas metades; a célula nomeia-se a si própria e diz uma.

## Consequências

**O que a decisão obriga.** A barreira do KAM-040 — «nenhum caso
`real_consentido` entra sem registo de consentimento», critério 1 do bloco —
**passa a ser a defesa** em vez da exclusão do material real. Era uma condição
entre outras num critério de aceitação; passa a ser o mecanismo de que depende a
conformidade do conjunto todo. O que isso implica, com credor nomeado:

* **a barreira tem de morder por máquina, não por revisão.** Um caso
  `real_consentido` sem registo de consentimento não pode entrar no dataset nem
  passar o *gate* 13 — é o padrão de *fail-closed* desta casa, e o canário é esse
  fluxo exacto (um caso real sem registo ⇒ o *gate* vermelho). Credor:
  **KAM-040**;
* **o `registo de consentimento` é um nome canónico que ainda não existe.** A
  finalidade do consentimento para avaliação, a sua base legal e a forma do
  registo entram em `../../specs/02_Dicionario_de_Dados_Canonico.md` §3 **antes**
  de entrarem em código — o §7.2 de `../tecnica/10` já tem o domínio de `purpose`
  com `CHECK` sobre dez finalidades, e é ali que a de avaliação se resolve.
  Credor: **KAM-040**;
* **a premissa vai ao parecer, e é a mesma.** O **KAM-104** leva aos Termos da
  Meta §4.7 e à Lei 22/11 a pergunta de que isto depende (L-G1, E1 Q7). Esta
  decisão escolhe **qual lado do canon vale**; não torna a leitura jurídica
  verificada, que continua **NÃO VERIFICADO** e leva `(a confirmar por parecer)`
  onde aparece. Credor: **KAM-104**;
* **se o parecer vier contra, há dois recuos escritos e não são o mesmo — e
  escolher entre eles não é desta estação.** Medido na árvore depois de o PR #93
  fundir (`7426abf`):

  ```text
  a primeira versão desta página   «cai a origem real_consentido e não as outras
                                    duas: o conjunto reduz-se a sintetico e
                                    t2_anonimizado»
  o pacote do KAM-104, fundido     «(a) recuar para conjunto INTEIRAMENTE
  (../tecnica/evidencia/validacao/  sintético […] Se o parecer recusar (b), a
   Pacote_Parecer_Juridico.md)      KAMBÁ recua para (a)»
  ```

  A diferença é **se um caso `t2_anonimizado` sobrevive a um parecer que recuse o
  consentimento**: uma conversa real de suporte T2 anonimizada não é sintética, e
  «inteiramente sintético» exclui-a. O pacote confirma que lê assim, porque nomeia
  à parte a opção **(c)**, «material real pseudonimizado para além do que o
  KAM-040 admite». E a diferença não é teórica: o pipeline do §11.2 de
  `../tecnica/10` é a **única** fonte de casos escritos por clientes reais em
  português de Angola, que é o que está NÃO VERIFICADO e o que este conjunto
  existe para medir — pelo recuo do pacote, o conjunto fica só com o que a equipa
  inventou.

  **Decisão do fundador a 2026-10-30, ao ser-lhe apresentada a divergência: a
  pergunta vai ao parecer, e não se decide internamente.** A razão é que a
  diferença entre os dois recuos é se uma conversa reescrita sem dados pessoais
  continua a ser, para o §4.7, uma conversa real — leitura jurídica, não decisão
  de produto. Executada: a pergunta **F-03** do
  `../tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md` ganhou a **quinta
  variante** (a conversa real concreta reescrita, que é a `t2_anonimizado`), e a
  «Resposta pedida» passou a exigir que o parecer diga se ela conta como conversa
  real — porque é essa resposta que fixa o alcance do recuo (a). **Se a resposta
  for «não conta», os dois recuos convergem sozinhos** e esta divergência fecha-se
  sem ninguém escolher. Até lá, **vale o que o pacote escreve**, por ser canon e
  não por ser melhor; esta página não é autoridade sobre o recuo. Achado da revisão
  adversarial, que o apanhou por correr sobre a árvore depois do *merge* e não
  sobre a que eu tinha. Credor da resposta: **o parecer (KAM-104)**; credor do
  registo: **KAM-040**.

**O custo assumido.** Um conjunto de avaliação que admite material real é mais
exposto: um caso mal consentido é uma violação, onde antes era impossível por
construção. A decisão troca uma impossibilidade por uma barreira — e uma barreira
tem de ser testada, o que a impossibilidade não precisava.

## Esta decisão é candidata a subir a canónica, e isso não se decide aqui

O [`README.md`](README.md) fixa o critério: uma decisão local sobe a canónica
«quando passa a governar mais do que o seu ticket». **Esta governa o KAM-040, o
KAM-104 e a leitura do ADR-018 em oito documentos** — os sete da primeira tabela
acima mais o `../tecnica/02`, pelo que o critério aponta
para cima — e o caminho natural não é um ADR canónico novo, é a **emenda à célula
do ADR-018**, que é o que este PR faz.

Fica **local** porque é o registo da decisão e do seu alcance, não a decisão em
si: a decisão é do fundador e está datada. Promovê-lo tomaria o número seguinte ao
último canónico, obrigaria a actualizar a contagem e o mapeamento de
`../tecnica/INDICE.md` §5, e acrescentaria um ADR canónico que ninguém pediu para
dizer o que a célula do ADR-018 passou a dizer.

(**Não se escreve aqui o número que ele teria**, pela razão que o `ADR-L005` já
registou: o `lint_refs` recusa uma referência a um `ADR-NNN` que o §8 não tem.
A primeira versão desta página escrevia-o, e o *lint* **apanhou-o — mas só depois
do `git commit`**, porque varre os ficheiros versionados e um ficheiro novo ainda
não o é. Logo: num ticket que cria ficheiros, os seis *linters* valem depois do
`git add`, e correr antes dá um verde que não cobre o que é novo. A dispensa em
`ci/refs-allow.yaml` existe e **não** se usou: o próprio ficheiro diz que não é
mecanismo de dispensa genérico.)

## Como se mede que o canon ficou sem a divergência

Corre-se da **raiz do repositório**. As duas buscas cobrem as três formas que a
medição apanhou (a janela de 120 caracteres, o plural e a glosa), e os três filtros
não são enfeite: **sem eles a receita devolve a prosa deste próprio PR** —
dezassete linhas, oito delas linhas de «Controlo de versões», o bloco do ticket e
esta página, nenhuma delas nas tabelas acima. Foi o achado da revisão adversarial
sobre a primeira versão desta receita, e é o defeito mais insidioso dos catorze:
uma receita que devolve ruído obriga a próxima auditoria a re-derivar a
classificação, que é exactamente o trabalho que esta página existe para poupar.

```bash
EXCLUIR='/analises/|/dividas-documentais|^specs/tickets/|^docs/adr/|:[0-9]+:\| 1\.[0-9]'
grep -rniE "golden.{0,200}reescritas? sint|reescritas? sint.{0,200}golden" \
  specs/ docs/ --include=*.md | grep -vE "$EXCLUIR"
grep -rniE "golden sintético" specs/ docs/ --include=*.md | grep -vE "$EXCLUIR"
```

Depois deste PR as ocorrências que sobram são, uma a uma, as que as tabelas desta
página classificam: a de `../../specs/EPIC-10` bloco KAM-109 (corrigida no PR #93,
e por isso já não aparece), as **quatro** glosas na dívida **157**, os **dois**
sítios que falam de uma origem concreta, e as linhas corrigidas, que passam a
nomear as três origens no mesmo sítio onde dizem «reescrita sintética». Qualquer
linha que apareça e não esteja nas tabelas é divergência nova, e não resíduo
deste PR.

A verificação completa é a revisão adversarial deste ticket, em
[`../analises/ANALISE-44-KAM-169-origem-do-golden-set.md`](../analises/ANALISE-44-KAM-169-origem-do-golden-set.md)
— **44 e não 43**, porque o `ANALISE-43` é do KAM-104 e veio com o PR #93: o
número tinha sido assumido em vez de medido, que é o defeito que o próprio
critério 7 desta página manda não cometer com a numeração dos ADRs locais.

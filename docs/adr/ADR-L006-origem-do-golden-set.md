# ADR-L006 — A origem do *golden set*: valem as três origens do KAM-040

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-30 |
| Ticket | KAM-169 — A origem do *golden set* no canon: as três do KAM-040 |
| Âmbito | Local (ver [`README.md`](README.md)): **qual dos dois lados do canon vale** sobre a origem dos casos do *golden set* do KAM-040. Não especifica o dataset (é o **KAM-040**), não constrói o *gate* 13 (é o **KAM-040**), não decide o enquadramento legal (é o parecer do **KAM-104**) e não emenda o ADR-018 |
| Decisores | **O fundador, a 2026-10-30**, sobre a divergência que a revisão adversarial do KAM-104 mediu |
| ADRs canónicos aplicáveis | ADR-018 (observabilidade leve e proibição de treino com dados do WhatsApp), ADR-008 (transferências) |
| Documentos aplicáveis | [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) §8 e §11; [`../tecnica/10_Onboarding_Governanca.md`](../tecnica/10_Onboarding_Governanca.md) §11.2, §11.3, §12 e §16; [`../logs.md`](../logs.md) §9; [`../tecnica/02_Agent_Runtime_Verticais.md`](../tecnica/02_Agent_Runtime_Verticais.md) §16.2; [`../../specs/00_KAMBA_Carta.md`](../../specs/00_KAMBA_Carta.md) §4.1; [`../../specs/EPIC-03_Agent_Runtime_Verticais.md`](../../specs/EPIC-03_Agent_Runtime_Verticais.md) bloco KAM-040; [`../../specs/EPIC-06_Indice_Pesquisa.md`](../../specs/EPIC-06_Indice_Pesquisa.md) bloco KAM-064; [`../../specs/EPIC-10_Spikes_Validacao_Gates.md`](../../specs/EPIC-10_Spikes_Validacao_Gates.md) bloco KAM-109 |
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

### As dezassete linhas, medidas

Medido em `main` (`fd0a32d`), **antes** deste PR. O enunciado que chegou a este
ticket falava de **sete** linhas; a medição deu **dezassete**, e a diferença não é
detalhe — é a mesma classe de erro que criou a divergência, instrumento parcial
lido como leitura. As três buscas que falharam, e porquê:

```text
grep -rnE "golden.{0,120}reescrita sint|reescrita sint.{0,120}golden"
  perde o §11.2 de `../tecnica/10`  — 120 caracteres entre as duas expressões
  perde o §11.3 e a PA-GOV-4        — dizem «reescritaS sintéticaS», no plural
  perde a Carta e as glosas         — dizem «golden sintético», sem «reescrita»
```

**Afirmam só reescrita sintética (onze):**

| Onde | Estado |
|---|---|
| `../tecnica/00` §8, célula do ADR-018 | corrigida neste PR |
| `../logs.md` §9, última regra | corrigida neste PR |
| `../tecnica/10` §12, linha de risco | corrigida neste PR (o risco **mantém-se**; muda a mitigação) |
| `../tecnica/10` §11.2, o pipeline | corrigida neste PR — lia-se como o pipeline do conjunto e é o da **segunda** origem |
| `../tecnica/10` §11.3, cláusula (a) | corrigida neste PR |
| `../tecnica/10` §16, **PA-GOV-4** | corrigida neste PR |
| `../../specs/00_KAMBA_Carta.md` §4.1, linha do ADR-018 | corrigida neste PR; é a fonte de verdade de **nível 1** e repetia a abreviação um nível acima |
| `../../specs/EPIC-10` bloco KAM-109, «Detalhes Técnicos» | **PR #93** (KAM-104) — não tocada aqui |
| `../../specs/EPIC-03` §1, glosa «ADR-018 (golden sintético…)» | dívida documental: resíduo textual, fora do âmbito |
| `../../specs/EPIC-10` §1, glosa «ADR-018 (golden sintético…)» | dívida documental; o PR #93 não a toca |
| `../../specs/EPIC-06` bloco KAM-064, glosa no *handoff* | dívida documental |

**Admitem material real com consentimento (seis), e nenhuma muda:**

| Onde | O que diz |
|---|---|
| `../tecnica/00` §11, premissa «Dados da Meta e ML» | «reescrita sintética **e** por casos autorizados pela PME (ADR-018)» |
| `../../specs/EPIC-03` bloco KAM-040, critério 1 | `origem ∈ {sintetico, t2_anonimizado, real_consentido}` e nenhum `real_consentido` sem registo de consentimento |
| `../../specs/EPIC-03` bloco KAM-040, Contexto | «o dataset é **sintético** (reescrita) e, só com consentimento e base legal, caso real (L-G1)» |
| `../../specs/EPIC-03` §R5, tabela de riscos | «Golden sintético; real só com consentimento e parecer» |
| `../../specs/EPIC-06` bloco KAM-064, Contexto | conversas reais entram «**pseudonimizadas e reescritas sinteticamente**, com consentimento específico para avaliação» |
| `../tecnica/02` §16.2, regra (4) | as três origens em prosa, com a cláusula §4.7 marcada «a confirmar por parecer (L-G1)» |

**Quatro sítios dizem `sintetico` e não são contradição**, porque falam de uma
origem concreta e não do conjunto: a exportação de candidatos do concierge
(`../concierge.md`, `../../specs/EPIC-03` bloco KAM-114 e
`../../specs/02_Dicionario_de_Dados_Canonico.md` §3.34, que exportam **só
metadados** e entram com `origem=sintetico` por desenho) e o *golden* dos módulos
do dono (`../../specs/EPIC-11`), que é um dataset distinto do KAM-040.

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
   intactas por isso mesmo.
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
* **se o parecer vier contra**, o que cai é a origem `real_consentido` e não as
  outras duas: o conjunto reduz-se a `sintetico` e `t2_anonimizado`, e o *gate*
  13 continua a existir. Credor: **KAM-040**, com o pivô registado no bloco.

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
si: a decisão é do fundador e está datada. Promover isto a `ADR-021` tomaria o
número seguinte ao último canónico, obrigaria a actualizar a contagem e o
mapeamento de `../tecnica/INDICE.md` §5, e acrescentaria um ADR canónico que
ninguém pediu para dizer o que a célula do ADR-018 passou a dizer.

## Como se mede que o canon ficou sem a divergência

```text
# Nenhuma afirmação de origem exclusiva sobre o golden do KAM-040, nas três
# formas que a medição apanhou (a 120 caracteres, o plural e a glosa):
grep -rniE "golden.{0,200}reescritas? sint|reescritas? sint.{0,200}golden" \
  specs/ docs/ --include=*.md | grep -v '/analises/'
grep -rniE "golden sintético" specs/ docs/ --include=*.md | grep -v '/analises/'
```

Depois deste PR as ocorrências que sobram são, uma a uma, as que esta página
classifica: a de `../../specs/EPIC-10` (PR #93), as **três** glosas em dívida, as
**quatro** que falam de uma origem concreta, e as linhas corrigidas, que passam a
nomear as três origens no mesmo sítio onde dizem «reescrita sintética». A
verificação completa é a revisão adversarial deste ticket, em
[`../analises/ANALISE-43-KAM-169-origem-do-golden-set.md`](../analises/ANALISE-43-KAM-169-origem-do-golden-set.md).

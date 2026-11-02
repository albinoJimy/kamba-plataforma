# ANÁLISE 44 — KAM-169, a origem do *golden set* no canon

> **Renumerada de 43 para 44 ao integrar os achados**, pela razão que o próprio
> achado `C-04` desta página dá: o `ANALISE-43` é do KAM-104 e chegou com o PR
> #93. As ocorrências de «`ANALISE-43`» que sobram abaixo são as citações do
> achado e ficam como estavam, porque é o registo do que foi medido.

| Campo | Valor |
|---|---|
| Ticket | KAM-169 — A origem do *golden set* no canon: as três do KAM-040, e a barreira do consentimento (EPIC-01) |
| Ramo | `fix/KAM-169-origem-do-golden-set`, *commit* `175544f` (13 ficheiros, 429 inserções, 20 remoções) |
| Base lida | `fd0a32d` — e a base **mexeu durante esta revisão**: `publico/main` é hoje `7426abf` (PR #93, KAM-104) |
| Estação | revisão adversarial, com verificação do achado |
| Instrumento | subagente independente, com o diff e os requisitos e **sem** o raciocínio do executor |
| Achados levantados | 31 |
| `CONFIRMADO` | 14 |
| `PLAUSÍVEL` | 2 |
| `MORTO` | 15 (levantados pelo revisor e por ele próprio mortos, com a evidência) |
| Veredicto | **Não funde como está.** Quatro achados são de bloqueio: C-01, C-02, C-03 e C-04 |
| Estado | Vivo |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

---

## 1. A medição que importa mais

**O PR mede o canon com cuidado exemplar e não se mede a si próprio.** A secção
«As dezassete linhas, medidas» do `ADR-L006` escreve as **três buscas que
falharam** e porquê — 120 caracteres de janela, o plural, a glosa sem a palavra
«reescrita». Essa parte verifiquei-a e está certa: a classe de erro está
nomeada, as dezassete linhas existem e a classificação de cada uma é
reproduzível.

O que não foi medido são as **referências que o próprio PR escreve**. Dos
quatorze `CONFIRMADO`, nove são do mesmo molde:

| O que o PR afirma | O que a árvore diz |
|---|---|
| «a linha de risco do `tecnica/10` **§12**» (sete sítios) | o risco está no **§18**; o §12 é «Segmento A vs B» |
| «a **PA-GOV-4** do §16» (seis sítios) | a PA-GOV-4 está no **§20.1**; o §16 é «Métricas de governação» |
| «A célula tem **354** caracteres» | 354 é o **número da linha**; a célula tinha 306 e tem 590 |
| «a análise em `ANALISE-43-KAM-169-…`» | `ANALISE-43` é do **KAM-104**, fundida no mesmo dia |

Nenhuma destas é opinião: todas se decidem com um comando. E o padrão é o
contrário do que o ticket fez bem — o número do `ADR-L` foi **medido**
(`ls docs/adr/`, critério 7), e o número da análise foi **assumido**. A mesma
disciplina, aplicada a um artefacto e não ao outro, no mesmo bloco.

> **A lição, na forma que serve a próxima execução:** um bloco que escreve
> «§NNN» está a fazer uma afirmação verificável, exactamente como um que escreve
> um caminho. O `lint_refs` resolve `KAM-NNN`, `ADR-NNN` e caminhos; **ninguém
> resolve `§NNN`**, e por isso é o sítio onde uma citação errada sobrevive a
> seis *linters* verdes. O instrumento é um `grep -n "^#\{2,3\} "` no documento
> citado, antes de escrever o número.

A segunda medição que importa: **a base mexeu**. O PR #93 (KAM-104) fundiu em
`7426abf` enquanto esta revisão corria. Não há conflito — `git merge-tree
--write-tree 7426abf 175544f` sai **0**, e isso é o requisito 4 a pagar-se: não
tocar no `EPIC-10` evitou o conflito mecânico que o bloco previu. Mas traz dois
achados novos (C-03 e C-12), porque o `#93` escreveu sobre o mesmo assunto.

---

## 2. Os achados, por gravidade

### C-01 — CONFIRMADO — A defesa jurídica entrou no canon como facto, sem `(a confirmar por parecer)`

**Onde.** `docs/tecnica/00_Arquitectura_Solucao.md:354` (célula do ADR-018 no §8)
e `docs/tecnica/10_Onboarding_Governanca.md:574` (§11.3, cláusula (a)); a
justificação está em `docs/adr/ADR-L006-origem-do-golden-set.md:111-116`.

**O que está errado.** A célula do §8 passa a afirmar, em canon e sem marcador:

> «os Termos da Meta proíbem treinar ou melhorar ML com dados do WhatsApp, **e a
> defesa é o registo de consentimento, não a exclusão do material real**»

e o §11.3 (a) repete «a barreira é a defesa, e não a exclusão do material real».
A primeira metade é uma afirmação sobre o texto dos Termos; a segunda é uma
**leitura jurídica** — a de que avaliação com consentimento cai fora de
«melhorar». Nenhuma das duas linhas leva `(a confirmar por parecer)` nem estado
de verificação.

**Evidência.**

* A regra da casa é explícita: `.claude/skills/software-factory/SKILL.md:716` —
  «**Jurídico leva `(a confirmar por parecer)`.** O conjunto trata APD, BNA, AGT
  e Termos da Meta — nenhuma leitura nossa é definitiva.»
* O `E1` sustenta a proibição e **não** sustenta a leitura:
  `docs/tecnica/evidencia/E1_Meta_WhatsApp.md:105` dá a cláusula §4.7 como
  «CONFIRMADO (fonte primária), com ressalva de leitura automática do texto PT;
  **verificar a cláusula exacta**», e a pergunta 7 (linha 199) é precisamente
  «pode-se usar um LLM de terceiros (inferência) com dados de conversas?».
* O documento fundido no mesmo dia diz que isto está **em aberto**:
  `docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md:1227-1233`
  (PR #93) — «**O que se pede ao advogado já não é «qual dos lados vale»** —
  isso era decisão da KAMBÁ e está tomada — **mas se a decisão se sustenta**».
* As linhas comparáveis do conjunto levam o marcador:
  `docs/tecnica/02_Agent_Runtime_Verticais.md:874` («uma questão a confirmar por
  parecer (L-G1)») e `specs/EPIC-03_Agent_Runtime_Verticais.md:3791`
  («(L-G1: a confirmar por parecer)»).
* O próprio `ADR-L006:146-150` promete o marcador — «continua **NÃO VERIFICADO**
  e leva `(a confirmar por parecer)` **onde aparece**» — e as duas linhas que
  escreveu não o levam.

**Agrava-o** que o `ADR-L006:105` apresente isto como o segundo de «**três
factos medidos**». Os factos 1 e 3 são medidos e verifiquei-os. O facto 2 é uma
inferência jurídica, e chamar-lhe facto medido é a caixa marcada pela razão
errada no sítio onde mais custa: a página que existe para dizer que **não houve
substituição de ADR**.

**O que fazer.** Acrescentar `(a confirmar por parecer)` às duas linhas de canon,
e no `ADR-L006` separar o facto 2 dos outros dois — ele não é medição, é a
premissa que o KAM-104 leva ao parecer. A decisão do fundador não muda: o que
muda é o conjunto deixar de afirmar como estabelecido o que o pacote jurídico
fundido no mesmo dia manda perguntar.

---

### C-02 — CONFIRMADO — O pivô está escrito de duas maneiras, e a outra já está fundida

**Onde.** `docs/adr/ADR-L006-origem-do-golden-set.md:151-153` contra
`docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md:1238-1245`.

**O que está errado.** O `ADR-L006` escreve o pivô assim:

> «**se o parecer vier contra**, o que cai é a origem `real_consentido` e não as
> outras duas: o conjunto reduz-se a `sintetico` e `t2_anonimizado`»

O pacote do KAM-104, fundido em `7426abf`, escreve-o assim:

> «**(a)** recuar para conjunto **inteiramente sintético**, se o consentimento da
> PME não bastar perante os Termos […] **Se o parecer recusar (b), a KAMBÁ recua
> para (a)**»

Não são o mesmo pivô. Um caso `t2_anonimizado` é uma conversa real de suporte T2
anonimizada — não é sintético. «Inteiramente sintético» exclui-o; «reduz-se a
`sintetico` e `t2_anonimizado`» mantém-no. E o pacote nomeia à parte a opção
**(c)**, «material real pseudonimizado **para além do que o KAM-040 admite**», o
que mostra que lê o `t2_anonimizado` como material real dentro do KAM-040.

**Porque é grave.** O `ADR-L006` é o registo da decisão e o sítio onde o KAM-040
vai ler o que fazer se o parecer recusar; o pacote é o documento que vai ao
advogado com o recuo escrito. Dois recuos diferentes para a mesma pergunta é a
classe de divergência que este ticket existe para fechar, criada pelo ticket que
a fecha.

**O que fazer.** É matéria de decisão e não de redacção: qual dos dois recuos
vale é do fundador, porque a diferença é se uma conversa real anonimizada
sobrevive a um parecer que recuse o consentimento. Entregar a medição e
perguntar — não emendar nenhum dos dois lados por semelhança.

---

### C-03 — CONFIRMADO — Duas secções citadas erradas, em dez sítios: o risco está no §18 e a PA-GOV-4 no §20.1

**Onde.** `docs/adr/ADR-L006-origem-do-golden-set.md:11`, `:64`, `:67`;
`specs/tickets/KAM-169.md:13`, `:64`, `:69`, `:92`, `:135`, `:195`;
`docs/tecnica/10_Onboarding_Governanca.md:837` (linha de versão 1.8). São sete
ocorrências de «§12» e seis de «§16».

**O que está errado.** O bloco e o ADR dizem «a linha de risco do **§12** do
`tecnica/10`» e «a **PA-GOV-4** do **§16**». Medido no documento citado:

```text
727:## 18. Riscos e mitigações          <- a linha de risco (740)
776:## 20. Propostas de ADR e lacunas no canon
778:### 20.1 Propostas de ADR            <- a PA-GOV-4 (785)
578:## 12. Segmento A vs B e política de comunicação
680:## 16. Métricas de governação e alvos mensuráveis
```

O próprio documento o diz no seu índice, `docs/tecnica/10:28`: «métricas e RACI
(**§16**–§17)». O §12 e o §16 são duas secções que este PR **não tocou**.

**Onde custa mais.** Em três sítios:

1. `ADR-L006:11`, «Documentos aplicáveis» — quem seguir a referência canónica do
   ADR aterra duas vezes no sítio errado;
2. `KAM-169.md:195`, o **bloco de *handoff***: «NÃO apagues a linha de risco do
   docs/tecnica/10 §12» — a instrução ao próximo executor protege uma linha que
   não existe nessa secção, e a que tem de proteger fica sem endereço;
3. `KAM-169.md:92`, a linha de evidência do critério 4, que se chama «O risco do
   §12». O comando que ela cita (`grep -n "Golden set contamina"`) devolve a
   linha certa — a prova está certa e o endereço não, que é o inverso do defeito
   habitual e igualmente caro.

**O que fazer.** `§12 → §18` e `§16 → §20.1` nos dez sítios. E, porque nenhum
dos seis *linters* vê um `§NNN`, vale a pena registar a classe: as referências
de secção são a única família de citação deste conjunto sem gate.

---

### C-04 — CONFIRMADO — O número da análise foi assumido e colidiu: o `ANALISE-43` é do KAM-104

**Onde.** `docs/adr/ADR-L006-origem-do-golden-set.md:189` e
`specs/tickets/KAM-169.md:171` (caixa de DoD, marcada `[x]`).

**O que está errado.** Os dois citam
`docs/analises/ANALISE-43-KAM-169-origem-do-golden-set.md`. O número 43 já é de
outro ticket: `docs/analises/ANALISE-43-KAM-104-pacote-parecer-juridico.md`,
fundido em `7426abf` (PR #93) **a 2026-10-30**, o mesmo dia da decisão. O
primeiro livre é o **44**.

**Evidência.**

```text
$ ls docs/analises/ | grep 43
ANALISE-43-KAM-104-pacote-parecer-juridico.md
```

E a resolução de todos os caminhos relativos dos dois ficheiros novos dá
exactamente uma falha, esta:

```text
FALHA 190: ../analises/ANALISE-43-KAM-169-origem-do-golden-set.md
FALHA 171: ../../docs/analises/ANALISE-43-KAM-169-origem-do-golden-set.md
```

**A segunda metade do achado.** A caixa de DoD estava `[x]` — «Revisão
adversarial independente feita, com os achados classificados […] e a análise em
`ANALISE-43-…`» — antes de a revisão existir e com o caminho a não resolver. É a
caixa marcada pela razão errada na forma mais directa: a prova é o ficheiro, e o
ficheiro não existia.

**Nota sobre este ficheiro.** Escrevi-o no caminho que o pedido nomeou, para que
as duas referências resolvam; **fica como dívida imediata do PR** renumerar os
três — este ficheiro para `ANALISE-44-KAM-169-origem-do-golden-set.md` e as duas
referências com ele. Dois `ANALISE-43` na mesma pasta é a mesma classe de
resíduo que o `docs/adr/README.md` tinha com as linhas duplicadas e que este PR
limpou.

---

### C-05 — CONFIRMADO — `docs/concierge.md:170` ficou a atribuir ao §11.3 uma conclusão que o §11.3 já não tira

**Onde.** `docs/concierge.md:170`.

**O que está errado.** A linha diz:

> «e o [`tecnica/10`] **§11.3** tira a conclusão: o *golden* leva **reescritas
> sintéticas**, nunca cópias.»

Este PR reescreveu o §11.3 (a) para que uma conversa real entre como
`real_consentido` com registo de consentimento. A linha do `concierge.md` ficou
a citar a secção emendada como fonte da conclusão **oposta**.

**Porque não é um «falso positivo».** O `ADR-L006:85-90` classifica o
`../concierge.md` entre os «**quatro sítios [que] dizem `sintetico` e não são
contradição**, porque falam de uma origem concreta e não do conjunto». Para o
`concierge.md` isso é verdade da sua linha ~179 («`origem=sintetico` em cada
registo», que é a exportação de metadados) e é **falso da linha 170**, que é um
universal — «nunca cópias» — e nem fala da exportação. A contradição não ficou
por medir: ficou **classificada como não sendo uma**.

**Evidência.** A busca de verificação do próprio ADR devolve-a:

```text
$ grep -rniE "golden.{0,200}reescritas? sint|reescritas? sint.{0,200}golden" \
    specs/ docs/ --include=*.md | grep -v '/analises/'
docs/concierge.md:170:§11.3 tira a conclusão: o *golden* leva **reescritas sintéticas**, nunca cópias.
```

**O que fazer.** Ou corrigir a linha 170 (é uma frase, e o documento é do mesmo
eixo), ou pôr **esta** linha na dívida documental com o seu número — mas não
deixá-la contada entre as que «não são contradição», porque é.

---

### C-06 — CONFIRMADO — O §11.2 foi declarado «o pipeline da segunda origem», e três referências do canon apontam-no como o da origem `sintetico`

**Onde.** `docs/tecnica/10_Onboarding_Governanca.md:570`.

**O que está errado.** A nova frase diz «este pipeline é o da **segunda**» —
isto é, `t2_anonimizado`. O conjunto tem três referências que apontam para o
§11.2 como o pipeline de onde saem casos com `origem=sintetico`:

| Onde | O que diz |
|---|---|
| `specs/EPIC-03_Agent_Runtime_Verticais.md:3883` (KAM-114, CA 7) | «para a **reescrita sintética** de `../docs/tecnica/10` **§11.2**; […] os casos entram em KAM-040 com `origem=sintetico`» |
| `specs/EPIC-03_Agent_Runtime_Verticais.md:3933` (verificação do mesmo CA) | a mesma frase, com a prova |
| `specs/02_Dicionario_de_Dados_Canonico.md:2263` (§3.34) | «quem escreve o caso reescreve-o sinteticamente (`../docs/tecnica/10` **§11.2**); o caso entra em **KAM-040**», com `origem=sintetico` |

A leitura do PR é defensável — `docs/tecnica/02:874` regra (4) ordena as origens
«sintéticos e escritos pela equipa», «casos de suporte T2 anonimizados (ciclo
`10`)» e conversas reais, e o pipeline do §11.2 arranca em «caso resolvido», que
é T2. **Mas a leitura decide uma coisa que não é deste ticket:** que rótulo de
`origem` leva um caso T2 reescrito sinteticamente. Isso é o domínio do critério 1
do KAM-040, e três linhas do canon respondem hoje `sintetico`.

**O que fazer.** Não resolver aqui. A frase pode dizer que o pipeline do §11.2 é
o da reescrita sintética de casos T2 **sem** fixar qual das três origens o rótulo
nomeia, e o rótulo fica para o KAM-040 com a tensão escrita. Alternativa: pedir
ao fundador, que é quem decide se o `t2_anonimizado` absorve o que hoje três
linhas chamam `sintetico`.

---

### C-07 — CONFIRMADO — «a barreira é do KAM-040 e vale para os três» contradiz a frase que a precede

**Onde.** `docs/tecnica/10_Onboarding_Governanca.md:570`, fim da frase.

**O que está errado.** A frase diz primeiro:

> «Um caso `real_consentido` percorre o mesmo pipeline **mais** o registo de
> consentimento, sem o qual não entra»

e fecha com:

> «a barreira é do KAM-040 e **vale para os três**»

Lido à letra, a segunda metade exige registo de consentimento também para um
caso `sintetico`, que não tem titular nenhum, e desfaz o «**mais**» da primeira.
Lido com boa vontade, «a barreira» é o critério 1 do KAM-040 (que governa as três
origens) e não o registo de consentimento — mas o antecedente mais próximo de «a
barreira» nesta frase é o registo.

**O que fazer.** Nomear o sujeito: «o critério 1 do KAM-040 governa as três
origens, e o registo de consentimento é a condição da terceira». É uma frase.

---

### C-08 — CONFIRMADO — `specs/EPIC-03:3868` ficou com um universal: «o dataset golden […] nunca cópias de conversas»

**Onde.** `specs/EPIC-03_Agent_Runtime_Verticais.md:3868` (Contexto do KAM-114).

**O que está errado.** A linha afirma «o dataset golden recebe reescritas
sintéticas das decisões, **nunca cópias de conversas** (ADR-018)». «Nunca cópias
de conversas» é uma afirmação sobre o conjunto, e um caso `real_consentido` é uma
conversa real. O `ADR-L006:85-90` conta «`EPIC-03` bloco KAM-114» entre os quatro
sítios que «falam de uma origem concreta e não do conjunto»; esta linha fala do
conjunto.

**Mais fraco do que o C-05** porque «das decisões» circunscreve a frase à
exportação do concierge, e a leitura benigna existe. Mas a frase que sobra, lida
por quem chega ao bloco, diz o contrário da decisão de 2026-10-30.

**O que fazer.** Uma linha na dívida documental com o seu número, ou a emenda da
frase. O que não serve é ficar contada entre as que não contradizem.

---

### C-09 — CONFIRMADO — Depois do rebase obrigatório sobra uma quarta glosa, e a enumeração do ADR não a classifica

**Onde.** `docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md:1234`,
contra `docs/adr/ADR-L006-origem-do-golden-set.md:184-187`.

**O que está errado.** O ADR fecha a dizer que depois deste PR «as ocorrências
que sobram são, **uma a uma**, as que esta página classifica». A base mexeu: o
PR #93 fundiu e trouxe

> «**Por que importa.** Bloqueia **KAM-040** (dataset **golden sintético** e eval
> harness como gate)»

que é exactamente a glosa de uma linha com a metade abreviada, e está no
documento que, trinta linhas acima, declara as três origens decididas. Não é
nenhuma das três que a dívida 157 nomeia (duas em `§1` de epics e uma em
*handoff*), e o ficheiro não existia em `fd0a32d`.

**Evidência.**

```text
$ grep -rniE "golden sintético" docs/tecnica/evidencia/ --include=*.md
docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md:1234:…
```

**O que fazer.** No rebase, acrescentar esta quarta à linha 157 de
`docs/dividas-documentais.md` — e corrigir a frase da dívida, que diz «as
**três** glosas».

---

### C-10 — CONFIRMADO — «A célula tem 354 caracteres» é o número da linha, não uma contagem

**Onde.** `specs/tickets/KAM-169.md:89` (evidência do critério 1).

**O que está errado.** A linha oferece como prova de que a célula foi lida
inteira: «A célula tem **354 caracteres** e foi lida inteira antes de se
emendar». Medido:

| O que | Valor |
|---|---|
| Número da linha da fila do ADR-018 em `docs/tecnica/00` | **354** |
| Célula de decisão em `fd0a32d` | **306** caracteres |
| Célula de decisão depois do PR | **590** caracteres |
| Fila inteira depois do PR | **630** caracteres |

354 não é nenhuma das contagens: é o endereço. A afirmação verdadeira do resto da
linha — a metade de observabilidade não mudou uma palavra — **essa confirmei-a** e
está certa (visível no diff; só o período da «reescrita sintética» foi
substituído e a razão dos Termos ficou).

**O que fazer.** Tirar o número ou pôr o certo. O custo não é a aritmética: é que
um número inventado ao lado de uma afirmação verdadeira contamina a afirmação.

---

### C-11 — CONFIRMADO — A evidência do critério 2 diz «o mesmo» onde a árvore dá «compatíveis»

**Onde.** `specs/tickets/KAM-169.md:90`.

**O que está errado.** A linha conclui: «As duas afirmações do documento passam a
nomear **as mesmas origens**». Medido:

* `docs/tecnica/00:354` (§8, emendada): três origens nomeadas —
  `sintetico`, `t2_anonimizado`, `real_consentido` — mais o registo de
  consentimento;
* `docs/tecnica/00:413` (§11, intocada por exigência do pedido): «reescrita
  sintética **e** por casos autorizados pela PME (ADR-018)» — duas coisas, sem
  `t2_anonimizado` e sem registo de consentimento.

São **compatíveis** (foi o que dei por verificado: nenhuma delas afirma hoje o
contrário da outra) e não são «as mesmas origens». O critério 2 pede que «passem
a dizer o mesmo»; à letra não passam, e não podiam, porque o requisito 3 proíbe
tocar no §11.

**O que fazer.** A emenda é na linha de evidência, não no §11: dizer
«compatíveis, e o §11 fica como está por exigência do pedido». Marcar
«satisfeito» com uma prova mais forte do que o texto sustenta é o defeito, não o
estado do documento.

---

### C-12 — CONFIRMADO — «predominantemente» entrou numa cláusula de conformidade sem número e sem gate

**Onde.** `docs/tecnica/10_Onboarding_Governanca.md:574`, cláusula (a) do §11.3.

**O que está errado.** A cláusula passa a abrir com «o golden set é
**predominantemente** reescrita sintética». Não há proporção, não há limiar, não
há marcador *proposta*, e nada o mede — o *gate* 13 não existe. Numa cláusula que
existe para ser lida por um advogado (é a premissa que o KAM-104 leva ao parecer,
como a própria cláusula (d) agora diz), um adverbio de quantidade sem quantidade
é pior do que nada: sugere um tecto que ninguém pode verificar.

**Evidência.** A convenção da casa:
`.claude/skills/software-factory/SKILL.md:715` — «Valores de desenho ainda não
calibrados são *proposta*».

**O que fazer.** Ou tirar «predominantemente» (a frase funciona sem ele: o que
importa é que um caso real só entra com registo), ou dar-lhe um número marcado
*proposta* e um credor — e o credor natural é o KAM-040.

---

### C-13 — CONFIRMADO — A declaração de escopo diz «duas emendas» e são quatro superfícies além do pedido

**Onde.** `specs/tickets/KAM-169.md:123-137` («Duas emendas estão fora das três
que o pedido nomeou, e as duas estão declaradas aqui»).

**O que está errado.** Confrontado o `git show --stat 175544f` ficheiro a
ficheiro contra o pedido:

| Ficheiro | Declarado onde |
|---|---|
| `docs/tecnica/00`, `docs/logs.md`, `docs/tecnica/10` (risco) | pedido, critérios 1, 3 e 4 |
| `docs/tecnica/10` §11.2, §11.3, PA-GOV-4 | declarado, «além do pedido» n.º 2 |
| `specs/00_KAMBA_Carta.md` | declarado, «além do pedido» n.º 1 |
| `docs/adr/ADR-L006…`, `specs/tickets/KAM-169.md` | critério 7 e 8 |
| `specs/INDICE.md`, `specs/EPIC-01`, `specs/EPIC-07`, `README.md` | critério 8 (cinco superfícies) |
| `docs/dividas-documentais.md` | secção «o que não faz» |
| **`.claude/skills/software-factory/SKILL.md`** | só em «Detalhes Técnicos:147-149» — **fora** da secção que conta o que vai além do pedido |
| **`docs/adr/README.md`, a desduplicação de duas filas** | só na evidência do critério 7 e numa nota no próprio ficheiro |

As duas últimas são defensáveis e **estão** ditas em algum sítio — por isso isto
é um achado de contabilidade e não de escopo escondido. Mas a secção que existe
para contar diz «duas» e são quatro, e é essa secção que um revisor lê para saber
o que confrontar.

**O que fazer.** Passar as duas para a secção que as conta. (A emenda ao
`SKILL.md` tem precedente no `fd0a32d`, que também lhe mexeu.)

---

### C-14 — CONFIRMADO — A receita de verificação, corrida como está escrita, devolve dezassete linhas das quais oito são o próprio PR

**Onde.** `docs/adr/ADR-L006-origem-do-golden-set.md:176-187`.

**O que está errado.** O ADR dá duas buscas e diz que o que sobra são «uma a
uma» as linhas que a página classifica. Corridas à letra na árvore do PR, a
primeira devolve **17** linhas, e oito delas são prosa nova deste PR — as linhas
de versão de `specs/EPIC-01:192`, `docs/logs.md:609`, `docs/tecnica/00:526`, a
dívida `docs/dividas-documentais.md:184`, duas do `KAM-169.md` e duas do próprio
`ADR-L006`. Nenhuma está nas tabelas da página.

**Porque conta.** A receita é o que a próxima auditoria vai correr. Se devolve
oito linhas que a página não explica, quem a corre tem de re-derivar a
classificação — que é precisamente o trabalho que a página existe para poupar.

**O que fazer.** Acrescentar à receita a exclusão das linhas de versão e dos
ficheiros do próprio ticket (`grep -v 'Controlo\|KAM-169\|ADR-L006'` não serve;
serve excluir `specs/tickets/`, `docs/adr/` e as filas que começam por `| 1.`), ou
dizer na página que a saída inclui o registo da própria emenda.

---

## 3. Os `PLAUSÍVEL`

### P-01 — A célula do ADR-018 quase duplicou de tamanho, e não sei se o §8 é o sítio

**Onde.** `docs/tecnica/00_Arquitectura_Solucao.md:354`.

**O que medi.** A célula de decisão passou de **306** para **590** caracteres, e
passou a conter a decisão, as três origens, a barreira, a razão dos Termos, a
defesa, a data da decisão e um *link* para o ADR local. É a célula mais longa da
tabela depois do ADR-020.

**O que não consegui decidir.** Se uma fila do §8 deve carregar isto ou só a
decisão, com o resto no ADR local. A tabela não tem regra escrita: o ADR-020 tem
uma fila igualmente longa e o ADR-016 tem três linhas.

**O que falta para o decidir.** Uma regra em `specs/01_Engineering_Standards_e_Handoff.md`
§5 ou em `docs/tecnica/INDICE.md` §5 sobre o que cabe numa fila do §8 — hoje não
existe. É decisão de forma do canon, do fundador, e não a levanto como defeito.

### P-02 — Não sei se o marcador jurídico também devia ir à Carta §4.1 e à regra do `logs.md` §9

**Onde.** `specs/00_KAMBA_Carta.md:83` e `docs/logs.md:579`, as outras duas linhas
emendadas.

**O que medi.** As duas passam a nomear as três origens e a barreira; nenhuma
enuncia a leitura jurídica («a defesa é o registo»), que é o que o C-01 apanha nas
outras duas. Por isso **não** as incluí no C-01.

**O que não consegui decidir.** Se a regra «Jurídico leva `(a confirmar por
parecer)`» abrange uma linha que nomeia origens de um dataset cuja admissibilidade
está sob parecer, ou só as que tiram a conclusão jurídica.

**O que falta para o decidir.** O fundador a dizer o alcance da regra. A diferença
prática é duas marcações.

---

## 4. Os `MORTO`, com a evidência que os matou

Registados para a próxima auditoria não os repetir.

| # | O que levantei | Porque morreu |
|---|---|---|
| M-01 | A desduplicação do `docs/adr/README.md` seria escopo alargado, ou as filas não eram iguais | `git show fd0a32d:docs/adr/README.md` dá as filas **46–49** como dois pares **byte a byte idênticos**, coluna do ticket incluída. A remoção é correcta e está declarada no critério 7 e no próprio ficheiro |
| M-02 | O `docs/logs.md` ganhou a fila `1.3` e o cabeçalho não subiu | O `logs.md` **não tem campo `Versão`** no cabeçalho (`sed -n '1,12p'`), logo não há desacordo. O `lint_backlog` conta «60 documento(s) com Controlo de versões (**35 sem campo** no cabeçalho)» |
| M-03 | A Carta ganhou a fila `1.3` com o cabeçalho em `1.0` | Pré-existente: em `fd0a32d` era `1.0` contra `1.2`. O campo é `**1.0 — PROPOSTA (por ratificar pelo fundador)**` e o `lint_backlog` sai **0**. Não foi criado aqui |
| M-04 | O `specs/EPIC-07` mudou sem fila de versão | Prática da casa, lida no histórico da linha: `fd0a32d` (KAM-168), `4165d9a` (KAM-167), `664a211` (KAM-166) e `2dbc2f0` (KAM-165) bumparam o mesmo número sem fila |
| M-05 | `registra` / `registra-a` seriam PT-BR | 83 ocorrências de `registra` em `specs/` e `docs/` antes deste PR. É grafia da casa, não um deslize deste ticket. Nenhum outro marcador PT-BR nos dois ficheiros novos |
| M-06 | As filas de «Controlo de versões» teriam buracos ou repetições | As seis sequências são contíguas: `tecnica/00` 1.0–1.4, `tecnica/10` 1.0–1.8, `EPIC-01` 1.0–1.48, `INDICE` 1.0–1.37, Carta 1.0–1.3, `logs.md` 1.0–1.3. Cabeçalho igual à última fila em `tecnica/00` (1.4), `tecnica/10` (1.8), `EPIC-01` (1.48) e `INDICE` (1.37) |
| M-07 | «O backlog tem 169» com o `AssertionError: (143, …)` ao lado seria contagem desactualizada | O `143` nunca acompanhou o backlog: `git log -L 1067,1071` mostra quatro *commits* a bumpar só o primeiro número. E o `docs/seguranca/validar.py` **deste** repositório é um *stub* que sai **2** («nao vive neste repositorio») |
| M-08 | O número do `ADR-L` teria sido assumido | Medido e certo: `ls docs/adr/` dava `ADR-L001`–`ADR-L005` antes do PR; o livre é o `L006`. O contraste com o C-04 é o achado |
| M-09 | A dívida 157 afirma «nenhuma destas três está no PR #93» sem o #93 estar fundido | Verificado **depois** da fusão (`7426abf`): `specs/EPIC-10:19`, `specs/EPIC-03:21` e `specs/EPIC-06:318` continuam com as glosas; o #93 mexeu só na linha do bloco KAM-109, hoje `specs/EPIC-10:733`. A afirmação é verdadeira |
| M-10 | «casos autorizados pela **PME**» (§11, intocado) não é consentimento do **titular**, logo a leitura do ADR assentaria numa equivalência falsa | Morto pelo documento do #93: `Pacote_Parecer_Juridico.md:1229-1231` escreve «o consentimento recolhido do **titular pela PME**». É o mesmo mecanismo, e o §11 fica compatível |
| M-11 | As cinco superfícies ou as contagens vivas estariam incompletas | `ls specs/tickets/ \| wc -l` → **54** (o §2 diz 54); §3.1 `KAM-150 – KAM-169`, 54 no epic e 169 no total; §1 169; `README.md` 169; `EPIC-07` 169. `lint_contagens` conforme, **14** contagens vivas em 10 ficheiros |
| M-12 | Os números citados nas evidências 6 e 9 estariam errados | `grep -cE "^\| \*{0,2}ADR-0[0-9]{2}\*{0,2} \|" docs/tecnica/00…` → **20**; `docs/tecnica/INDICE.md` fora do diff; `grep -n "ci-13" Makefile` → exit **1** (os alvos são `ci-1`…`ci-9`, `ci-11`, com `3b`, `3c` e `7-meta` e **sem** `ci-10`) |
| M-13 | Os seis *linters* não estariam conformes | Corridos de `tools/`: `lint_backlog`, `lint_refs`, `lint_handoff`, `lint_contagens`, `canon_lint` com `check` e `lint_arch` com `all` — **exit 0** nos seis, lido com `echo $?`. O `lint_backlog` diz «169 linha(s) no §4, 169 bloco(s) e 169 linha(s) de §3 em 11 epics» |
| M-14 | Haveria caminho que não resolve nos ficheiros novos | Resolvidos **28** caminhos relativos dos dois ficheiros da posição em que estão escritos: todos existem, excepto o `ANALISE-43` do C-04 |
| M-15 | O PR colidiria com o #93 já fundido | `git merge-tree --write-tree 7426abf 175544f` → exit **0**, sem conflito. Não tocar no `EPIC-10` (requisito 4) pagou-se |

---

## 5. O que o PR faz bem, e que fica dito

Três coisas, porque um relatório que só acusa não ensina:

1. **A medição que corrige o enunciado.** O pedido falava de sete linhas; o
   bloco mediu dezassete, **escreveu as três buscas que falharam** e explicou
   porquê. Verifiquei as três falhas e são reais — e a minha primeira busca
   caiu na quarta variante do mesmo erro (`sint[eé]tic` não casa `sintético`
   numa localidade de bytes, porque o `é` são dois). A classe está bem nomeada.
2. **A leitura sobre substituição de ADR existe e tem um facto medido a
   sustentá-la.** O facto 1 — o §11 do mesmo documento atribui ao ADR-018 as duas
   metades — confirma-se em `docs/tecnica/00:413`, e é o que sustenta que a
   célula do §8 era a metade abreviada. É a parte do requisito 5 que ficou
   cumprida; o que falha é o facto 2 (C-01).
3. **O risco não foi apagado, e a mitigação mudou de forma.** `docs/tecnica/10:740`
   mantém a fila, qualifica o risco («dados reais **sem consentimento
   registado**») e troca a exclusão pelo registo. O requisito 2 está cumprido à
   letra, e é a barreira a mudar de forma e não a sair.

---

## 6. Veredicto

**Não funde como está.** Quatro achados de bloqueio, nenhum dos quais obriga a
reabrir a decisão do fundador:

* **C-01** — o canon passa a afirmar uma defesa jurídica sem `(a confirmar por
  parecer)`, no mesmo dia em que o pacote do KAM-104 funde a dizer que é essa a
  pergunta ao advogado. Emenda de duas linhas mais a reclassificação do «facto 2»
  no `ADR-L006`;
* **C-02** — o pivô «se o parecer vier contra» está escrito de duas maneiras, uma
  delas já em `main`. **Devolve-se ao fundador**: qual dos dois recuos vale é
  decisão, não redacção;
* **C-03** — nove referências de secção erradas, uma delas na instrução de
  *handoff* que protege a linha de risco. `§12 → §18`, `§16 → §20.1`;
* **C-04** — o `ANALISE-43` colide com o do KAM-104 e a caixa de DoD foi marcada
  antes de o ficheiro existir. Renumerar para **44** nos três sítios.

Os restantes dez `CONFIRMADO` são emendas de uma a três linhas cada, excepto o
**C-06** (que rótulo de origem leva um caso T2 reescrito), que é matéria do
KAM-040 e deve sair deste PR como tensão escrita em vez de resposta implícita.

A decisão de 2026-10-30 em si — as três origens com registo de consentimento
obrigatório nos reais — está correctamente registada, correctamente propagada às
sete afirmações substantivas, e as cinco superfícies do backlog estão todas
tocadas com os seis *gates* documentais verdes. O problema deste PR não é o que
decidiu: é o que afirmou sobre si próprio.

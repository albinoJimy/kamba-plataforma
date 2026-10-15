# ANÁLISE 19 — KAM-152: `db/gate8.py`, um caminho que não existe

| Campo | Valor |
|---|---|
| Ticket | KAM-152 — `db/gate8.py`: um caminho que não existe, numa mensagem que manda correr o ficheiro |
| Ramo | `fix/KAM-152-caminho-gate8-pendurado` (nasceu `fix/KAM-150-…`) |
| Revisto | `86618b5`, sobre `main` em `148567c` |
| Revisores | Dois agentes independentes, sem acesso às justificações de quem escreveu: um adversarial (parecer), um de remedição (só números) |
| Data | 2026-10-13 |
| Veredicto da revisão adversarial | **REPROVADO** — 1 P0, 5 P1, 9 P2, 2 suspeitas |
| Estado depois das emendas | Todos os achados com disposição escrita; 0 por corrigir |

A revisão recebeu o pedido original, o *diff* e os ficheiros. **Não recebeu as
justificações de quem escreveu o ticket** — é a condição que faz dela evidência
e não concordância.

---

## 1. O que a revisão confirmou

Vale primeiro o que foi medido de novo, por quem não o escreveu, porque é a
parte do ticket que estava bem:

- **O caminho sai das citações vivas.** 7 em `148567c` → 0, com os números de
  linha da listagem do bloco a reproduzirem **um a um** (`ci.yaml:217`,
  `bootstrap.py:26`, `base.py:8` e `:48`, `ameacas_stride.md:90`,
  `gerar_matriz.py:363`, `CSV:67`, `dividas:32`).
- **O trinco intacto:** 26 ocorrências em 25 linhas, idênticas antes e depois,
  **nenhuma** tocada pelo *diff* — e inspeccionadas **uma a uma**: todas são o
  nome do trinco ou da base, nenhuma é um caminho.
- **O critério 1 está satisfeito pela razão certa.** `--suite` tem
  `default="tests"` (`db/gate_bd.py:242-247`), logo `python db/gate_bd.py` é
  válido sem argumentos. A revisão foi **mais longe do que o bloco** e mediu que
  `_ambiente_da_suite` (`:88-104`) **sobrepõe** `KAMBA_DB_NAME` a `kamba_gate8`:
  o comando cumpre a promessa da mensagem **mesmo para o utilizador cujo `.env`
  disparou o trinco**. Era o sítio onde o critério podia estar verde pela razão
  errada.
- **`validar.py` 5 → 3**, com o `assert` relaxado em memória sobre instantâneos
  dos dois *commits*: os 3 restantes são **idênticos por texto** aos 3 primeiros,
  nenhum novo; MATRIZ 68×13, STRIDE 96/96, DPIA 12, DOCS 5 e 454 citações `CA n`
  não se movem. **`docs/seguranca/validar.py` não aparece no *diff*.**
- **A atribuição dos 3 erros restantes**, que o bloco não provava: os **dois** de
  A-02 vêm ambos do nome de teste velho — `estado_controlo` é `parcial` e o único
  teste com caminho não existe, o que dispara também `validar.py:200-201`.
  Corrigir o nome fecha os dois.
- **O CSV estava em sincronia antes** (0 diferenças nos dois *commits*) e o seu
  *diff* é de **1 linha**.
- **A coluna «Onde» reescrita da linha 6 está certa, e a antiga estava errada:**
  o nome de teste velho está em `gerar_matriz.py` e no CSV, e **não** está no
  `ameacas_stride.md` — era o `gate8.py` que lá estava.
- **Os cinco ficheiros são o âmbito real**, não alargamento: os dois não nomeados
  pelo pedido saem da mesma varredura, e a revisão varreu por conta própria sem
  encontrar nada de pé (incluindo variantes `db/gate_8.py`, `gate6.py`,
  `db/gate.py`).
- **A fasquia por exclusão é legítima, não é mover a baliza.** `grep gate8 → 0`
  exigiria renomear a base de dados, o trinco e os contentores. A exclusão **não
  esconde nada que devesse ter sido corrigido**.

---

## 2. Achados, e o que se fez

### P0

| # | Achado | Disposição |
|---|---|---|
| A1 | **O bloco citava `ANALISE-18-…`, que não existia, com a caixa do DoD «todos os caminhos resolvem» marcada.** Dos 27 caminhos do bloco, exactamente 1 não resolvia — e era a classe de defeito que o ticket existe para fechar, cometida pelo ticket, invisível aos gates (o 3 não vê caminhos; o `validar.py` só vê `docs/seguranca/`) | **Aceite.** Este ficheiro passa a existir, com um número livre (§3), e o verificador do ticket passou a resolver **todos** os caminhos `.md` citados no bloco — a caixa só fecha com 0 |

### P1

| # | Achado | Disposição |
|---|---|---|
| A2 | `ANALISE-18` já estava reclamado por `fix/KAM-148-cobertura-python-do-agr` (`ANALISE-18-151-…`). O ticket mediu o próximo `KAM-` livre mas **não fez o mesmo ao número da análise** | **Aceite.** Medido sobre nomes e conteúdos de todas as refs: 17 duplamente reclamado, 18 e 20 reclamados, **19 livre**. É esta análise |
| A3 | «Dezassete caixas marcadas, uma vazia (17 + 1 = 18)» — são **16 marcadas, 1 vazia, 17 no total**. A caixa vazia contada duas vezes | **Aceite.** Corrigido, com o erro escrito onde esteve, e o verificador passou a conferir a própria frase contra a contagem |
| A4 | «Emite **26** avisos» — são **30**, antes e depois. 26 era a leitura da truncagem («(e mais 25)»), e é a contagem de ocorrências do trinco reaproveitada por engano | **Aceite.** Corrigido para 30, com a origem do erro nomeada |
| A5 | A linha 6 da dívida, reescrita por este *commit*, publicava «o backlog tem 144» — e era **145** por causa deste *commit*. Quem fechasse o ticket do `assert` a ler aquela linha escrevia o número errado | **Aceite.** Hoje 151, e o dono passou a ser nomeado como **KAM-149** |
| A6 | **Regressão no §1 do backlog mestre:** a frase do furo foi colada a meio da oração canónica, e o §1 passou a ler-se como se o gate 3 exigisse critérios SMART. Era a **única** ocorrência de «critérios de aceitação SMART» no conjunto | **Aceite.** A oração está restaurada e intacta; o §1 foi reconstruído de `main` em vez de emendado. Nenhum critério mencionava a reescrita da prosa — foi a caixa «nenhuma alteração acidental» que falhou |

### P2

| # | Achado | Disposição |
|---|---|---|
| A7 | «oito ocorrências de **cinco** ficheiros» — são **8 em 7 ficheiros**, e as 7 vivas em **6**. Os cinco editados à mão não contêm todas | **Aceite.** Corrigido nos quatro sítios |
| A8 | «a varredura sem exclusões dava **22**» não reproduzia: **23** | **Aceite.** Corrigido, com a decomposição por ficheiro |
| A9 | O âmbito da exclusão dizia «§7 do `INDICE`», e uma das ocorrências está no **§4**, a tabela-contrato, porque o título do ticket embute o caminho. E o «Objectivo» era um absoluto falso («nenhuma citação fica no repositório») | **Aceite.** O Objectivo qualifica-se («citação **viva**»), a exclusão diz-se **por ficheiro**, e o bloco passou a registar que **o título é a razão de a fasquia precisar de âmbito** |
| A10 | Linha de tabela quebrada na própria tabela de evidência: `|` não escapados dentro de *code spans* (`` `Dependências | —` ``) dão 6 `|` numa tabela de 4 | **Aceite.** Reescrita sem os `|`. O mesmo defeito foi cometido **outra vez** na linha nova do registo de dívidas e apanhado por contagem de células |
| A11 | PT-BR: «o grafo **registra**» | **Aceite.** «regista» |
| A12 | *Placeholder* `albinoJimy/kamba#PR` na secção de verificação — a lição do KAM-144 era fixar o número | **Aceite.** Fixado no fecho |
| A13 | «os identificadores 145 a 149 ainda não têm bloco» era falso para quatro deles: tinham bloco em ramos em voo. Só verdadeiro lido como «em `main`» | **Resolvido por integração.** Os cinco chegaram a `main`, e a frase desapareceu com a narrativa do furo |
| A14 | A base da medição do ID estava incompleta: o 150 só era o primeiro livre sobre a **união** de nomes e conteúdos, e ficava por dizer que o **151 já estava tomado** — logo o 150 não era uma escolha, era a única vaga | **Aceite**, e tornou-se o centro de §4: a união está escrita, e o 151 nomeado |
| A15 | A linha 4 da dívida ficou mais desactualizada do que estava («histórico até 1.8», hoje mais) por este *commit* lhe acrescentar uma linha de versão | **Aceite.** Acertada em 1.15 |

### Suspeitas (não são achados)

| # | Suspeita | Juízo |
|---|---|---|
| S1 | **A escolha do título é o que torna a fasquia inalcançável.** Pôr `db/gate8.py` no título obriga a cadeia a viver no §4 do `INDICE` e no §3 do epic, e é o que exige exclusões em vez de nenhuma. Um título pelo sintoma deixava a fasquia quase literal | **Acolhida como registo, não como alteração.** O título mantém-se — é o que torna o ticket encontrável por quem procurar o caminho antigo —, e a razão está agora escrita no «Objectivo». É a resposta honesta à pergunta «porque é que a fasquia precisa de âmbito» |
| S2 | Não haver teste de regressão está justificado e a decisão fica devolvida, com o L-20 nomeado como a cobertura certa da classe | **Aceite pela revisão.** Mantém-se |

---

## 3. O que a revisão **não** reviu

Dito porque importa mais do que o que reviu:

- **As suites dos *gates* 8 e 6 não correram** (precisam de Docker), nem prova
  por mutação. A condição de `exigir_base_descartavel` não muda — só a *string* —
  mas **nenhuma suite correu**, e isso é `NÃO VERIFICADO` por execução.
- Não correram o `gate 9 history`, nem os gates 1, 2, 4, 5, 7, nem `make ci`.
- Os 151 blocos não foram lidos linha a linha: o backlog foi verificado
  **estruturalmente** (sincronia, reciprocidade, unicidade, contagens).
- As reclamações de ramos em voo foram medidas sobre `refs/heads` e
  `refs/remotes` locais, que podem estar atrasados face ao remoto — e **estavam**:
  ver §4.

---

## 4. O achado que a revisão não podia ter: o ID mudou debaixo do ticket

A revisão mediu, e com razão, que **o 150 era a única vaga livre**. Entre a
medição e o fecho, o `albinoJimy/kamba#47` fundiu em `main` e **levou o
KAM-150** para as regras de `CODEOWNERS`; os 145 a 149 chegaram pelos PRs #45,
#38 e #42. O ticket renumerou para **KAM-152**, a primeira vaga sobre a união
de nomes e conteúdos depois dessas fusões (o identificador 151 está reclamado por
`fix/KAM-148-cobertura-python-do-agr`).

**A lição não é «medir melhor».** A medição estava certa quando foi feita e
ficou errada sem que nada neste ramo mudasse, porque seis sessões fundem em
paralelo. O que a torna recuperável é ter sido feita por comando e registada com
a sua base, em vez de escolhida de memória. Três consequências ficaram escritas
no bloco:

1. **O ID só está seguro depois do *merge*.**
2. **As contagens fecham-se depois de integrar `main`**, nunca antes.
3. **Renumerar por substituição em bloco é perigoso:** trocar `KAM-150` por
   `KAM-152` reescreveu também **quatro intervalos que estavam certos**, fechando
   em 152 os que terminavam em 150 — forma que o gate 3 expande e que exigiria o
   151, e que esta frase não pode escrever pela mesma razão. Foi o verificador
   que os apanhou, não a leitura.

E uma quarta, que é um defeito de outro ticket encontrado por este: a
reciprocidade `Dependências`↔`Bloqueia` **voltou a falhar** — o KAM-148 declara
o KAM-136 nas suas dependências e o `Bloqueia` do KAM-136 está a `—`. É a falha
que o KAM-144 fechou oito vezes, reaparecida no primeiro ticket inscrito depois
dele, **o que confirma a previsão do KAM-144** (a causa é o KAM-138 não estar
implementado). Medida aqui, registada na linha **26** do registo de dívidas, e
**não corrigida**: é campo de outro ticket.

---

## 5. Achados deste ticket que são do mesmo tipo

Três dos achados são a **mesma espécie** e vale nomeá-la, porque é a que este
repositório produz mais: **um número publicado que não reproduz no *commit* que
o publica.**

- A3 (caixas), A4 (avisos), A8 (22 contra 23) e A5 (144 contra 145) são todos
  isso.
- E o caso mais puro não veio da revisão: a contagem de referências do gate 3
  **moveu-se três vezes com a própria frase que a publica** (11 427 → 11 428 →
  11 429), porque cada emenda à linha acrescentava um *token* `KAM-NNN`. É
  exactamente o que o KAM-144 registou no mesmo campo, e a defesa aplicada é a
  mesma: remedir no estado final, correr o gate duas vezes, e só então escrever.

A conclusão operacional é a do §5 do `SKILL.md`, com um número a mais: **não se
publica um número medido antes da última alteração ao texto que o publica.**

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: 1 P0, 5 P1, 9 P2 e 2 suspeitas da revisão adversarial independente, mais a remedição de 13 afirmações numéricas por um segundo revisor (2 não reproduziram). Inclui o achado que a revisão não podia ter — o ID consumido por um PR que fundiu durante o trabalho — e a regressão de reciprocidade herdada de `main`. | Equipa KAMBÁ |

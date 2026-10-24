---
name: agentic-engineering
description: Framework de engenharia multiagente para trabalho complexo neste repositório — discovery antes de escrever, decomposição, paralelismo só quando é seguro, revisão adversarial independente e auditoria de completude, ancorado no canon da KAMBÁ (Carta, ADRs, dicionário de dados, backlog KAM-NNN e evidência E1–E5). Usa esta skill sempre que a tarefa tocar em mais de um documento do conjunto, alterar um ADR ou uma decisão aberta, mexer no backlog mestre, redigir ou revalidar documentos técnicos ou specs, implementar um ticket KAM-NNN que atravesse componentes, ou quando houver risco de divergência documental — mesmo que o utilizador nunca diga "multiagente", "plano" ou "subagentes". Também quando várias tarefas relacionadas chegarem juntas, quando fizer falta validação independente de trabalho já feito, ou quando o pedido combinar pesquisa e redacção. Não a uses para uma correcção pequena e isolada num só ficheiro.
---

# Engenharia agêntica — KAMBÁ

> **Um agente produz evidências; não produz a verdade.**

Nenhum agente — nem tu — pode declarar sozinho que uma alteração está correcta, completa ou
segura. Toda a conclusão relevante assenta em evidência verificável e, quando o risco o
justificar, em validação independente de quem a produziu.

Neste repositório o modo de falha dominante **não é escrever a coisa errada**: é
**afirmar com mais confiança do que a evidência sustenta**, e deixar dois documentos a dizer
coisas diferentes sem ninguém notar. O produto aqui é desenho e backlog; um documento que se
contradiz com o vizinho é um defeito tão real como um teste vermelho — só não há compilador que
o apanhe. Esta skill é esse compilador.

## Proporcionalidade

O pipeline abaixo é o ciclo completo. Aplica as fases que o risco justifica e **diz quais
saltaste** — saltar em silêncio é o defeito que esta skill fecha, saltar com justificação é
engenharia. Corrigir uma gralha não precisa de grafo de dependências.

Dois sinais fiáveis de que precisas do ciclo inteiro:

- **não consegues nomear todos os documentos que afirmam o que vais mudar**;
- vais lançar **mais de um agente a escrever** no mesmo conjunto.

```text
DISCOVERY → IMPACTO → DECOMPOSIÇÃO → PARALELISMO → PRODUÇÃO
   → SELF-VALIDATION → REVISÃO ADVERSARIAL → INTEGRAÇÃO
   → VERIFICAÇÃO DO CONJUNTO → AUDITORIA DE COMPLETUDE → CONHECIMENTO → RELATÓRIO
```

---

## Ritmo — o rigor é o mesmo, o que muda é o que se repete

O backlog tem mais de uma centena de tickets e mais de uma dúzia de níveis de
dependência. O que se corta é trabalho repetido e espera, não verificação.

**Como isto se lê com a «Proporcionalidade», acima.** A proporcionalidade vale
para o que **não é um ticket**: uma gralha, uma emenda pequena. **Um ticket
`KAM-NNN` passa sempre por revisão adversarial e fecha com evidência**, seja
qual for o tamanho — decisão do fundador (Outubro 2026), que recusou graduar o
rigor por ticket e cortar o backlog. Onde as duas secções parecerem
discordar sobre um ticket, prevalece esta.

- **Vagas, não fila.** São candidatos a correr em paralelo os tickets cujas
  dependências já estão em `main`:

  ```bash
  python .claude/skills/agentic-engineering/scripts/vagas.py
  ```

  O script lê o backlog mestre e os blocos já fechados; não substitui a lista
  de «Paralelismo» (§3), **aplica-se depois dela**. Dois candidatos que definam
  o mesmo nome ou o mesmo contrato não correm juntos. Os ficheiros de registo
  (`Makefile`, `.github/workflows/ci.yaml`, `docs/ci.md`, `specs/INDICE.md`,
  tabelas de versões) são a excepção consentida àquela lista: colidem sempre,
  as colisões são mecânicas, e resolve-as quem integra. Revisões de base de
  dados **não** são mecânicas — cada uma encaixa na anterior — e os tickets
  que as acrescentam entram em série.
- **«Em `main`» faz as vezes de «`Done`» para as dependências.** O DoR de
  `specs/01` pede dependências `Done`, e nenhum ticket fica `Done` à letra
  enquanto a caixa dos revisores estiver vazia. Enquanto o projecto não estiver
  em produção, uma dependência conta como satisfeita quando o seu PR está
  fundido com as caixas marcadas com evidência.
- **Merge com o CI verde.** Depois da revisão adversarial e das correcções, o PR
  funde-se sem esperar revisão humana (decisão do fundador; o *ruleset* de
  `main` exige 0 aprovações). A caixa «revisto por N revisores» **continua
  vazia** em todos os tickets, incluindo os que alteram regras de bloqueio — é
  um facto registado, não um bloqueio.
- **Quem toca em ficheiros partilhados diz quais.** O contrato de cada agente
  pede a lista; o orquestrador funde por ordem e integra `main` nos ramos que
  ficaram para trás (merge, nunca *force-push*).
- **Mutações: as novas, em paralelo — com duas condições.**
  `python db/mutacoes.py <python> <excerto>` corre só as mutações cujo nome
  contém o excerto, oito de cada vez (`KAMBA_MUTACOES_PARALELO`). Chega quando
  o diff só **acrescenta** testes e mutações. A lista inteira corre-se sempre
  que o diff toque num teste antigo **ou num ficheiro que alguma mutação
  altera** — e custa horas: eram 20 no KAM-003, 48 em `main`, e 95 no ramo do
  KAM-008 quando lá se mediram 3 h 24 min (2026-10-12). E
  `python db/mutacoes.py --aplicaveis` corre-se sempre: confirma em segundos,
  sem Docker, que nenhuma mutação antiga deixou de se aplicar.

  **No PR corre o que é novo; a lista inteira corre de noite** (KAM-143), na
  tarefa `.github/workflows/mutacoes.yaml`, repartida por seis *runners*. Isto
  substitui o parágrafo acima quando o custo for o problema: a lista inteira
  deixa de ser razão para parar um PR, e quem decide corrê-la à mão antes do
  merge é quem escreveu o diff — a regra é correr quando uma sobrevivente
  descoberta só na manhã seguinte custaria mais do que a espera. O que o PR
  verifica por máquina é `--aplicaveis` (dentro do *gate* 8, segundos); a
  tarefa nocturna não diz qual PR quebrou uma mutação, diz o *commit* de `main`
  em que correu.

  Uma `PROVA INVALIDA` no relatório **não é uma mutação apanhada**: é a suite a
  falhar por carga da máquina, por não carregar, ou por rebentar antes de
  chegar a um teste. Conta como sobrevivente e baixa-se o paralelismo.
- **Um resíduo textual não é um ticket.** Uma frase desactualizada, um nome
  antigo ou uma contagem errada que uma revisão encontre fora do âmbito vai,
  numa linha, para `docs/dividas-documentais.md`. **Um defeito continua a ser
  ticket** (`specs/01` §6, princípio 1, com a excepção lá escrita): tudo o que
  peça código, ou escolher entre duas fontes, ou que o critério de aceitação do
  próprio ticket mande abrir.
- **Tickets pequenos do mesmo tema podem partilhar um PR.** O ramo leva o ID do
  primeiro (`feature/KAM-NNN-<slug>`); cada *commit* leva o ID do ticket a que
  pertence; o corpo do PR tem uma secção do modelo do §7 por ticket; e cada
  ticket mantém o seu bloco, as suas caixas e a sua secção de verificação. A
  revisão adversarial é uma só.
- **Não parar à espera.** Enquanto uma prova longa corre ou um agente trabalha,
  avança-se no que não depende dela. Só uma decisão que é mesmo do fundador
  justifica parar.

---

## 1. Discovery — antes de escrever

Não alteres nada nesta fase. O objectivo é saber o que o conjunto já afirma, não mudá-lo.

Delega a varredura a um subagente **`Explore`**: é read-only, devolve a conclusão em vez do
despejo de ficheiros, e mantém o teu contexto livre para a decisão. Uma varredura larga feita
inline enche a janela com excertos que não vais reler.

```
Agent(subagent_type: "Explore", prompt: "...")
```

O que tem de sair de aqui, explicitamente:

```text
RESULTADO DA DISCOVERY
Objectivo:
Documentos envolvidos:
ADRs e decisões abertas tocadas (ADR-NNN, D#):
Tickets afectados (KAM-NNN):
Afirmações existentes sobre o tema (e o seu estado de verificação):
Nomes canónicos envolvidos (dicionário §3):
Contradições já visíveis entre documentos:
Riscos:
Hipóteses (ainda por validar):
Lacunas de informação:
```

**As lacunas são a parte que importa.** Uma discovery que não lista nada em falta ou não
procurou, ou está a esconder incerteza.

### Fontes de verdade neste repositório, por ordem

Quando duas fontes discordam, **não escolhas em silêncio**. Regista o conflito no formato de
[`references/decomposicao.md`](references/decomposicao.md) e resolve-o contra a ordem abaixo.

| Ordem | Fonte |
|---|---|
| 1 | `specs/00_KAMBA_Carta.md` — forma do produto, registo de decisões e DoD do Piloto (quando ratificada; hoje é **proposta**) |
| 2 | `docs/tecnica/00_Arquitectura_Solucao.md` §8 — ADR-001…ADR-020; §13.3 — decisões abertas D1…D13 |
| 3 | `specs/02_Dicionario_de_Dados_Canonico.md` — **prevalece sobre `docs/tecnica/` até KAM-111 estar feito** |
| 4 | `specs/01_Engineering_Standards_e_Handoff.md` — DoR, DoD, gates, convenções |
| 5 | `specs/INDICE.md` §4 — backlog mestre: a linha do ticket é o contrato (ID, tipo, estimativa, prioridade, fase, dependências) |
| 6 | O ticket `KAM-NNN` — em `specs/tickets/KAM-NNN.md` no EPIC-01, no `specs/EPIC-XX_*.md` nos outros dez — e os seus critérios de aceitação |
| 7 | `docs/tecnica/01`–`docs/tecnica/10` — desenho por subsistema |
| 8 | `docs/tecnica/evidencia/E1`–`E5` — factos sobre Meta, pagamentos, lei, licenças e módulos de entrada, **com o seu estado** |
| 9 | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` — escopo do Piloto e hipóteses H1…H12 |
| 10 | Biblioteca exploratória `01`–`13` — **histórica**; corrigida pelos níveis acima |
| 11 | Código, quando existir, e evidência obtida em execução |

Três regras que esta ordem esconde:

- A biblioteca exploratória (`01`–`13`) **não é fonte de verdade**. Foi escrita antes da pesquisa
  e contém afirmações que a evidência corrigiu (custos Meta, grupos, MinIO, alojamento). Usa-a
  para intenção e história, nunca para decidir.
- `docs/tecnica/evidencia/` diz o que é **CONFIRMADO**, **INDÍCIO** ou **NÃO VERIFICADO**. Herda esse
  estado quando citares — promover um INDÍCIO a facto é o defeito mais comum aqui.
- O `docs/00-KAMBA-documento-mestre.md` é artefacto compilado e está desactualizado. Não o edites e
  não o cites como fonte.

---

## 2. Análise de impacto

Não julgues o tamanho pela contagem de ficheiros. **Uma linha no dicionário ou num ADR é maior
do que trezentas linhas num epic.**

```text
DIRECTO         ficheiros que vais alterar
INDIRECTO       documentos que afirmam o mesmo, índices, contagens, tabelas-resumo
CANÓNICO        ADRs, decisões abertas, nomes do dicionário, linhas do backlog mestre
VERIFICAÇÃO     o que deixa de estar verificado, o que precisa de nova evidência
FASE            o que muda de P/C/D, e se cria dependência de fase invertida
```

Neste repositório o impacto indirecto tem cinco sítios que escapam quase sempre:

- **`specs/INDICE.md` §4 (backlog mestre).** Dependências, prioridades e fases vivem aqui. Um
  ticket novo ou uma dependência nova muda o campo `Bloqueia` de outros tickets, que está
  replicado em cada epic. **Nunca edites um só lado.**
- **`specs/02_Dicionario_de_Dados_Canonico.md`.** Um nome novo de tabela, coluna, evento ou
  estado pertence aqui antes de pertencer a um ticket. Um nome fora do dicionário é um defeito.
- **`docs/tecnica/00` §8 e §13.3.** Acrescentar um ADR obriga a actualizar a contagem em
  `docs/tecnica/INDICE.md` §5 e, se for promoção de proposta, o mapeamento em `specs/INDICE.md` §6.
- **Contagens e tabelas-resumo.** «20 ADRs», o total de tickets, «11 epics», «5 anexos de evidência»,
  os totais por epic no §3.1 e as linhas de versão. Uma contagem desactualizada é a assinatura
  típica de uma alteração feita a meio.
- **Documento que fica a contradizer outro.** Quando corriges um desenho em `docs/tecnica/04`, o
  `docs/tecnica/08` que repetia a versão antiga **não se corrige sozinho**. Procura quem mais afirma
  a mesma coisa, com `Grep`, antes de fechar.

---

## 3. Decomposição e grafo de dependências

Divide em tasks pequenas o suficiente para um agente compreender, completas o suficiente para
produzir um resultado **verificável por si só**. O template da task, os estados do grafo e o
formato de estado de execução estão em
[`references/decomposicao.md`](references/decomposicao.md) — lê-o quando a tarefa tiver mais de
três unidades ou dependências não-triviais.

Para desenhar algo verdadeiramente estrutural (um conjunto novo, uma reorganização do canon),
delega a um subagente **`Plan`**. Não escreve conteúdo; devolve o plano, os ficheiros críticos e
os trade-offs.

### Paralelismo

> Paralelismo é permitido pela **independência**, não pela conveniência.

Antes de correr tasks em paralelo, todas as caixas têm de fechar:

```text
[ ] Não alteram os mesmos ficheiros
[ ] Não dependem de resultado ainda não produzido
[ ] Não definem o mesmo nome, estado, evento ou contrato
[ ] Não tocam no mesmo estado partilhado (backlog mestre, dicionário, tabela de ADRs, índices)
[ ] Não colidem semanticamente (duas respostas válidas e incompatíveis para a mesma pergunta)
[ ] Cada uma tem critério de validação próprio
```

**A costura natural de paralelismo aqui é o ficheiro: um agente por documento, nunca dois no
mesmo.** Mas isso não basta, e esta é a lição mais cara deste repositório:

> **Agentes a escrever em paralelo divergem nos nomes.** Cinco redactores sobre o mesmo desenho
> produziram três esquemas de `contacts`, três tabelas de consentimento, `valor_kz` contra
> `valor_minor` e dois eventos para a mesma confirmação de pagamento. Nenhum errou; nenhum tinha
> um nome canónico para seguir.

Daí a regra: **antes de lançar escritores em paralelo, fixa o vocabulário**. Cada contrato de
agente leva `specs/02_Dicionario_de_Dados_Canonico.md` e a linha do backlog mestre, e proíbe
inventar nomes sem os marcar como proposta. Se o vocabulário ainda não existe, criá-lo é a
primeira task, não uma limpeza posterior.

Quando lançares subagentes em paralelo, manda-os **na mesma mensagem** — senão correm em série e
pagas a latência sem ganhar nada.

---

## 4. Produção (redacção ou implementação)

Cada agente recebe um contrato explícito — papel, âmbito, o que pode e não pode assumir, o que
tem de devolver. O formato está em
[`references/contratos-de-agente.md`](references/contratos-de-agente.md), com a definição de cada
papel e o mapeamento para os `subagent_type` disponíveis.

Quatro regras que valem mais do que o resto desta secção:

**Não inventes.** Preços, prazos, limites de terceiros, nomes de parâmetros, artigos de lei,
capacidades de ferramentas — se não está confirmado, é `NÃO VERIFICADO`. Se precisares de um
valor para avançar, marca-o como **proposta** e diz onde se calibra:

```text
HIPÓTESE
- Hipótese:
- Evidência que a sustenta:
- Estado (CONFIRMADO / INDÍCIO / NÃO VERIFICADO):
- Como validar (spike, pergunta escrita, parecer, medição):
```

Uma hipótese declarada é engenharia. Uma hipótese silenciosa é o defeito que só aparece quando
alguém assina um contrato por causa dela.

**Não alargues o escopo em silêncio.** Nada de reescrita oportunista nem harmonização não
pedida. Uma alteração fora de `FILES_IN_SCOPE` só passa se for tecnicamente necessária,
justificada e registada. Defeito fora de escopo abre ticket novo — usa
`mcp__ccd_session__spawn_task` para o marcar sem descarrilar o trabalho actual. Um
*resíduo textual* (sem código nem decisão) vai para `docs/dividas-documentais.md`.

**Respeita o canon.** Não contradigas um ADR em vigor sem o substituir explicitamente; não
promovas uma decisão aberta a fechada sem o gatilho que a Carta nomeia; não marques uma fase P
para algo que depende de um ticket de fase 1.

**Escreve pelo mínimo que resolve.** Quando o ticket produz código, a escrita corre em modo
*ponytail* — a alteração mais pequena que resolve o problema **por inteiro**, incluindo os
chamadores, os testes e as *fixtures* que ela quebra:

```
Skill(skill: "ponytail:ponytail")
```

Invoca-se **ao entrar nesta secção**, antes da primeira linha, e vale até ao fim da escrita.
Não acrescenta fase nenhuma ao ciclo: **substitui** o hábito de desenhar a abstracção antes
do caso de uso, e reforça pelo outro lado a regra do escopo acima — ali é o escopo que não se
alarga, aqui é o código.

**Nível `full` (a omissão), sempre o mesmo.** O nível do *ponytail* é sobre a forma do diff,
não sobre quanto se verifica — o rigor por ticket não se gradua (§«Ritmo»), e nenhum dos
níveis mexe no que esta skill exige. O `lite` não se usa: pára para o utilizador escolher
entre duas opções, e aqui não se pára à espera. O `ultra` questiona o próprio pedido, e por
isso **só se usa fora de um ticket** — ao redigir um ticket, um ADR ou um critério de
aceitação, onde pôr em causa a necessidade é precisamente o trabalho. Dentro de um `KAM-NNN`
o critério de aceitação é o contrato: cumpre-se à letra (§5), não se discute a meio.

Duas fronteiras, porque o *ponytail* é lacónico e esta skill não é:

- **Governa o diff, não o registo.** O relatório do §8, as caixas do epic e a secção
  `### Verificação dos Critérios de Aceitação` mantêm-se por inteiro. A frase final do
  *ponytail* — o que saltou e o risco que fica — é útil e não é evidência nomeada; onde as
  duas se cruzarem, prevalece o §5.
- **Um atalho deliberado leva comentário**, na forma `shortcut: <o limite>, <quando se
  revê>`. É o que o `ponytail-debt` depois lê, sem ficheiro novo para manter (ver «Fora do
  ciclo de um ticket»). Um atalho sem limite escrito não é atalho, é defeito.

---

## 5. Self-validation

Depois de produzir, valida o teu próprio trabalho — sabendo que isto **não substitui** a revisão
independente. Serve para não desperdiçares um reviewer com defeitos que apanharias sozinho.

### O que existe hoje

O repositório tem **CI desde o KAM-002**: dos 18 gates de
`specs/01_Engineering_Standards_e_Handoff.md` §4 estão activos os que `docs/ci.md` §3 lista
(referências cruzadas, nomes canónicos, cobertura, isolamento, migrações, segredos, SBOM), e os
restantes continuam a ser o **alvo**.

> **O `Makefile` diz o que cada gate faz; não é a forma de o correr.** Nesta máquina não há
> `make`, `node` nem `pnpm` no `PATH`, e um `make ci-2` responde `command not found` — o que não
> é «o gate passa», é «o gate não correu». As quatro vias que funcionam, com as armadilhas que
> fazem um lint parecer verde quando saiu com 2, estão em
> [`references/evidencia-e-verificacao.md`](references/evidencia-e-verificacao.md),
> «Como correr a verificação aqui». Lê-as **antes** de dizer que verificaste.

O que os gates ainda não cobrem verifica-se por script
*ad-hoc* no teu scratchpad, com o `git diff` a sustentar a auditoria do changeset — mas as três
que pagam sempre **já não são disso**: desde o KAM-138 corre-as uma ferramenta, e a mão só serve
para enganar.

```text
[x] CONSISTÊNCIA DO BACKLOG   gate 3 + gate 3c — `make ci-3` e `make ci-3c`
[x] SINCRONIA MESTRE↔EPICS    gate 3c — `make ci-3c`
[x] REFERÊNCIAS               gate 3 — `make ci-3`
```

Do teu *worktree*, sem `make` no anfitrião:

```text
cd tools && python -m lint_backlog --root .. check   # 3c: as três superfícies do backlog
cd tools && python -m lint_refs --root .. check      # 3: identificadores
cd tools && python -m lint_handoff --root .. check   # 3: caminhos dos blocos de handoff
cd tools && python -m lint_contagens --root .. check # 3: contagens em prosa
```

**O `lint_contagens` não corre de dentro de um *worktree*** e sai com código 2 a dizer que três
grandezas não casam nada: o filtro do corpus exclui tudo o que tenha `.claude` no caminho, e os
*worktrees* vivem em `.claude/worktrees/`. É defeito dele (dono: KAM-158), medido no KAM-138 e
devolvido; os outros três correm de qualquer sítio. Até estar corrigido, confia no que o CI diz
desse passo.

O 3c compara a linha do `specs/INDICE.md` §4, o bloco `## KAM-NNN — ` e a tabela-resumo do §3 do
epic; verifica a reciprocidade `Dependências`↔`Bloqueia` (que o §4 **não** tem coluna para
denunciar), os ciclos com o caminho completo, as inversões de prioridade e de fase, as contagens
derivadas e o «Controlo de versões» de cada documento. **Um ticket novo não precisa de pôr
«segunda passagem de verificação dá 0 divergências» nos seus critérios: o gate di-lo.** O que
continua a ser teu é o que o gate não sabe julgar — se o ticket diz a coisa certa.

Diagramas Mermaid passam por um parser antes de se dizer que estão certos — escrevê-los sem
acentos nos IDs não prova que compilam. SQL e DDL que nunca correram contra um Postgres são
**propostas**, não desenho validado; diz isso onde aparecem.

### Checklist

```text
[ ] Critérios de aceitação do ticket atendidos, um a um
[ ] **As caixas do ticket marcadas no epic** — Critérios de Aceitação e DoD, só as que
    têm evidência, com uma linha de evidência nomeada por caixa
[ ] **As caixas que não se cumprem ficam vazias, e o relatório diz quais e porquê**
[ ] Afirmações novas têm estado de verificação (CONFIRMADO / INDÍCIO / NÃO VERIFICADO)
[ ] Valores numéricos sem fonte estão marcados como proposta, com onde se calibram
[ ] Nomes usados são os do dicionário; nomes novos estão lá, marcados como proposta
[ ] Nenhum documento vizinho ficou a contradizer este (procurado com Grep, não de memória)
[ ] Contagens, totais e tabelas-resumo actualizados
[ ] Linha de controlo de versões acrescentada onde o documento a tem
[ ] Nenhuma alteração acidental — reli o que mudou, não confio na memória
[ ] ADR, decisão aberta ou hipótese novos estão registados no sítio canónico
```

> **As caixas do epic são o controlo, não decoração — e foram ignoradas quatro vezes.**
> O KAM-001, o KAM-002, o KAM-128 e o KAM-129 foram entregues, com PR verde, e deixaram
> **62 caixas por marcar** entre os quatro. Nenhum relatório mencionou isso, e a diferença
> entre «entregue» e «fechado» desapareceu sem ninguém decidir.
>
> Três regras, por esta ordem:
>
> 1. **Marca-se com evidência nomeada, nunca por memória do trabalho feito.** A evidência
>    vive numa secção `### Verificação dos Critérios de Aceitação` no bloco do ticket, com
>    uma linha por critério: o que se mediu, com que comando, e o número que saiu.
> 2. **Uma caixa que não se cumpre fica vazia**, e aparece nessa secção com o estado
>    `parcial` ou `não satisfeito` e a razão. Marcá-la para o ticket «ficar fechado» é a
>    forma mais barata de transformar um DoD num enfeite.
> 3. **Cumprir à letra, não em espírito.** «p95 de 20 execuções» com 17 execuções não está
>    cumprido, mesmo com uma margem de doze vezes; «um canário numa *fixture* falha o PR»
>    não está cumprido se a pasta do canário for uma área permitida, mesmo que a decisão
>    seja defensável. Quando a leitura divergir da letra, escreve-se a leitura e devolve-se
>    a decisão a quem escreveu o critério — não se marca a caixa.
>
> E o DoD tem uma linha que se esquece sempre: **«2 revisores se alterar regras de bloqueio
> ou limiares»**. Uma revisão adversarial é evidência, não é um revisor.

> **Lê o `git diff` antes de fechar.** É agora a forma mais barata de apanhar uma alteração
> acidental num dos 56 documentos — e a razão pela qual edições em lote por script deixaram de
> ser um risco cego:
>
> ```bash
> git status --short && git diff --stat
> ```
>
> O `.gitattributes` fixa os finais de linha em LF, para que um documento não apareça alterado
> por inteiro só por ter sido tocado noutra máquina. Se vires isso, é defeito de configuração,
> não alteração real.

---

## 6. Revisão adversarial

Esta é a fase que dá substância ao princípio central, e é a primeira a ser sacrificada quando há
pressa. Não a sacrifiques.

A revisão **procura razões para o resultado estar errado**. Não confirma que está certo. Um
reviewer que só relê o documento e concorda não produziu evidência nenhuma.

Quando houver código, a revisão corre com dois instrumentos **na mesma passagem**:

```
Skill(skill: "code-review", args: "high")
Skill(skill: "ponytail:ponytail-review")
```

O `code-review` procura o defeito no diff. O `ponytail-review` lê o **código ligado** — quem
chama a função que mudou, o que ela chama, os testes, o que o repositório diz da carga
esperada — e faz as perguntas que o primeiro não faz: aguenta a carga real, a lógica
arriscada tem um teste que falha quando ela quebrar, e cada linha é precisa. Exige um caso
concreto por achado («esta entrada dá este resultado errado»), que é a mesma exigência de
evidência que esta skill faz ao resto. **Substitui** a última pergunta da lista abaixo (o
`simplify`) quando o trabalho é código, e não acrescenta passagem nenhuma — ver a
reconciliação no fim desta secção.

Para trabalho documental — que é a maior parte aqui — a revisão independente é um subagente
`general-purpose` que recebe **o documento e os requisitos, nunca as tuas justificações**. O
guião está em [`references/revisao-adversarial.md`](references/revisao-adversarial.md), com os
padrões de defeito que este repositório já produziu; as perguntas centrais são:

- Que afirmação aqui tem mais confiança do que a evidência sustenta?
- Que número apareceu sem fonte e passou a requisito?
- Que documento do conjunto fica a contradizer este?
- Que decisão foi tomada em silêncio entre duas fontes que discordavam?
- Que consumidor deste desenho quebra (ticket, documento, gate)?
- **O critério de aceitação pode estar satisfeito pela razão errada?**
- Existe forma mais simples que preserve o significado? Em trabalho documental, pergunta-a o
  revisor; em código é o grupo *Lean* do `ponytail-review`, que a substitui com a exigência de
  um caso concreto — o `Skill(skill: "simplify")` deixa de se invocar no ciclo de um ticket.

As análises adversariais ficam em `docs/analises/ANALISE-NN-<slug>.md`, com achados classificados e
veredicto — é onde vive a memória das revisões deste conjunto.

### O `ponytail-review` e a revisão adversarial que já existe

**Uma revisão adversarial por ticket. O `ponytail-review` não é uma segunda: é o instrumento
de código da que já está aqui.**

Isto está escrito porque a confusão é fácil e tem preço. A decisão do fundador (Outubro de
2026) é «sem segundas leituras nem gates novos», e a razão dela não foi a revisão — essa
encontrou defeitos reais em todas as primeiras entregas — foi **repeti-la**: segundas e
terceiras passagens, achados menores devolvidos ao autor, e configuração nova a cada ticket.
Um instrumento mais afiado dentro da passagem que já se faz não repete nada; uma passagem
nova repetiria tudo. Por isso o `ponytail-review` entra como instrumento e nunca como fase.

Na prática:

- **Uma passagem, uma lista, uma volta de correcções.** Os achados dos dois instrumentos
  juntam-se numa lista só, corrigem-se de uma vez, e o PR funde. Não se pede ao
  `ponytail-review` para reler as correcções, mesmo quando a correcção inclui um redesenho.
- **Corre-o o revisor, não o autor.** Vale a regra desta secção: o revisor recebe o diff e os
  requisitos, nunca as justificações de quem escreveu.
- **Achado menor segue o destino que já tem.** Um *Nice to have*, ou um *Lean* fora do âmbito,
  não volta ao autor: resíduo textual vai para `docs/dividas-documentais.md`, o que pede
  código abre ticket (§«Ritmo»).
- **Não é gate.** `Verdict: fix 1 and 3 first.` é parecer para quem corrige, não bloqueio de
  CI. Nenhum gate novo entra no pipeline por causa disto, e nenhum relatório do *ponytail*
  passa a ser condição de merge.
- **O que não se corta são defeitos.** O grupo *Must fix* — defeito, segurança, perda de
  dados, quebra na carga esperada — corrige-se antes do merge, como qualquer achado da revisão
  adversarial sempre se corrigiu.
- **Em trabalho documental não entra.** Lê código, e a maior parte do que se faz aqui é
  desenho e backlog; para isso o guião é
  [`references/revisao-adversarial.md`](references/revisao-adversarial.md), inteiro e sem
  acrescento.

---

## 7. Integração e verificação do conjunto

Antes de integrar, audita o que mudou face ao que **era suposto** mudar. O portão de integração
está em [`references/encerramento.md`](references/encerramento.md).

> **E depois de fundir, não perguntes ao `git` se fundiu.** A `main` funde por *squash* e há dois
> remotos sem antepassado comum: o `merge-base --is-ancestor` diz «não fundido» para um ramo que
> acabou de fundir, e para um ramo da outra linha o `merge-base` **falha** — e quem não verificar
> o código de saída lê o silêncio como «este ramo não tem nada a mais». Custou-me chegar a um
> passo de apagar sete *worktrees* com 164 a 254 commits cada. A prova é o estado do PR no
> GitHub; a receita e a limpeza que vem depois estão no mesmo ficheiro, «Como saber que um ramo
> fundiu» e «Limpeza depois do merge».

Depois corre a verificação que atravessa documentos. Hoje, por script *ad-hoc*; quando KAM-002 e
KAM-111 existirem, pelos gates. O princípio não muda: **a verificação é por máquina, não por
leitura**. Nesta sessão, a leitura dos relatórios dos redactores não apanhou nenhuma das ~60
dependências em falta; o script apanhou todas, mais dois ciclos e doze inversões de prioridade.

```text
[ ] Backlog consistente (ciclos, prioridades, fases, unicidade de blocos)
[ ] Epics sincronizados com o backlog mestre (segunda passagem = 0 divergências)
[ ] Referências válidas (KAM, ADR, D, H, E, caminhos)
[ ] Diagramas Mermaid passam o parser
[ ] Contagens e índices coerentes com o conteúdo
```

Uma verificação que corre duas vezes e muda alguma coisa na segunda passagem não é uma
verificação: é uma edição. Corre até estabilizar.

---

## 8. Auditoria de completude e encerramento

Compara o **pedido original** com o que existe agora — requisitos, tasks, produção, verificação
— e procura o que se perdeu pelo caminho. O formato da auditoria, o quality gate e o relatório
estão em [`references/encerramento.md`](references/encerramento.md).

Toda a afirmação relevante no relatório precisa de evidência nomeada:

```text
AFIRMAÇÃO: "O backlog está consistente."
EVIDÊNCIA:  script de consistência sobre specs/INDICE.md §4 → N tickets, 0 erros
            (ciclos, prioridade invertida, fase invertida, dependências inexistentes);
            N blocos únicos nos 11 epics; segunda passagem de sincronia → 0 divergências.
```

Sem evidência, escreve `NÃO VERIFICADO`. É informação útil. «Provavelmente está bem» não é.

### Conhecimento persistente

| O que descobriste | Onde vive |
|---|---|
| Decisão de arquitectura nova | `docs/tecnica/00_Arquitectura_Solucao.md` §8 (ADR-NNN), e a contagem em `docs/tecnica/INDICE.md` §5 |
| Decisão que depende de terceiro | `docs/tecnica/00` §13.3 (D#) e `specs/00_KAMBA_Carta.md` §4.2, com dono e escalada |
| Nome, estado, evento ou unidade | `specs/02_Dicionario_de_Dados_Canonico.md` §3, com emenda no §6 |
| Facto novo sobre Meta, pagamentos, lei, licenças | `docs/tecnica/evidencia/EN_*.md`, com URL, data e estado |
| Hipótese de negócio nova | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H#), com limiar e prazo |
| Trabalho a fazer | ticket novo em `specs/tickets/KAM-NNN.md` (EPIC-01) ou `specs/EPIC-XX_*.md` (os outros dez) **e** linha no backlog mestre `specs/INDICE.md` §4 |
| Achado de revisão | `docs/analises/ANALISE-NN-<slug>.md` |
| Resíduo textual fora do âmbito (sem código nem decisão) | `docs/dividas-documentais.md`, uma linha |
| Desenho de subsistema | `docs/tecnica/01`–`docs/tecnica/10`, na secção própria ou como adenda datada |

Não registes ruído temporário, e não reescrevas conhecimento existente sem confirmar que a
versão anterior deixou mesmo de ser verdade — a maior parte das vezes não deixou, apenas ficou
incompleta. Para execuções longas, mantém `.claude/state/execution-state.md` (formato em
[`references/decomposicao.md`](references/decomposicao.md)): é estado transitório, não fonte de
verdade.

---

## Fora do ciclo de um ticket — auditoria do repositório e livro de dívida

Duas das skills do `/ponytail` são de **repositório**, não de ticket. Têm cadência própria,
produzem relatório, e **não entram no PR de um ticket**: entrar lá fazia delas um gate, e
gates novos não entram (§«Ritmo»).

**`ponytail-audit` — ao fechar um epic.**

```
Skill(skill: "ponytail:ponytail-audit")
```

Auditoria do código do repositório ordenada por gravidade, que não altera nada. A cadência é
o fecho de um `EPIC-XX`, ou um pedido do fundador — nunca a entrega de um ticket: o que ela
procura (carga real, lógica arriscada sem teste, código que não devia existir) só se vê
depois de vários tickets assentarem, e dentro de um PR seria ruído fora de âmbito. O que sai
dela **não** é lista para corrigir ali: o relatório vai para
`docs/analises/ANALISE-NN-<slug>.md`, como qualquer memória de revisão, e cada achado segue a
regra que já existe — defeito abre ticket (`specs/01` §6), resíduo textual vai para
`docs/dividas-documentais.md`. **Acrescenta** uma vista que o ciclo de um ticket não tem, e
**não substitui** a auditoria de completude do §8, que compara o pedido com o entregue e é de
âmbito inteiramente diferente.

**`ponytail-debt` — na mesma cadência, e antes de prometer um limite.**

```
Skill(skill: "ponytail:ponytail-debt")
```

Lê os comentários `shortcut:` do repositório e devolve-os como livro de dívida: uma linha por
atalho, com o tecto que ele nomeia e o gatilho de revisão. Não substitui nada — não havia
onde ler isto. Corre com o `ponytail-audit`, e também **quando um ticket vai afirmar um
limite** (um p95, um tecto de carga, uma capacidade): um atalho declarado por baixo dessa
afirmação é a razão mais provável para ela ser verdade por acidente, que é o defeito que o §6
persegue. Um atalho que o relatório marque `no-trigger` — sem gatilho escrito — emenda-se no
próprio comentário, no mesmo PR: é a forma de dívida que apodrece em silêncio.

### `ponytail-debt` e `docs/dividas-documentais.md` não são a mesma lista

São dois livros de naturezas diferentes, e misturá-los estraga os dois:

| | `docs/dividas-documentais.md` | `ponytail-debt` |
|---|---|---|
| O que regista | resíduo **textual**: frase desactualizada, nome antigo, contagem errada | limite **de código** aceite de propósito, com o seu tecto |
| Onde vive | ficheiro do repositório, mantido à mão | no comentário `shortcut:`, ao lado da linha que explica; a lista gera-se quando se pede |
| Quem acrescenta | uma revisão que encontrou algo fora do âmbito | quem escreveu o atalho, no mesmo diff |
| Como se fecha | quem emenda o documento risca a linha | o gatilho chega e abre-se ticket, porque pede código |

Daí duas regras: um `shortcut:` **não** se copia para `docs/dividas-documentais.md` — ficava a
mesma dívida em dois sítios, e um deles a desactualizar-se; e um resíduo textual **não** leva
comentário `shortcut:`, porque não há código onde o pôr.

### `ponytail-gain` fica de fora

Mostra as poupanças medidas do *ponytail* — médias de 39 tarefas noutro repositório, e a
própria skill proíbe derivar delas um número para o repositório onde corre. Aqui isso seria
uma afirmação sobre o mundo sem evidência local, **NÃO VERIFICADO** à letra da escala de
verificação, e um relatório de ticket não a pode citar. Não entra em nenhuma fase. (O
`ponytail-help` é só o cartão de referência dos níveis e comandos: usa-o quem precisar, não
tem sítio no fluxo.)

---

## Convenções não negociáveis deste repositório

- **Português europeu/angolano**, na grafia do conjunto: `arquitectura`, `activo`, `facto`,
  `objectivo`, `correcção`, `acção`. Sem PT-BR. Termos técnicos consagrados ficam em inglês
  (`outbox`, `handoff`, `webhook`, `checkpointer`, `fact`).
- **Escala de verificação em três estados** em tudo o que é afirmação sobre o mundo:
  **CONFIRMADO** (fonte primária), **INDÍCIO** (fonte secundária ou inferência),
  **NÃO VERIFICADO**. Valores de desenho ainda não calibrados são *proposta*.
- **Jurídico leva `(a confirmar por parecer)`.** Não somos advogados e o conjunto trata APD,
  BNA, AGT e Termos da Meta — nenhuma leitura nossa é definitiva.
- **Fase em tudo o que é capacidade:** `P` (Piloto), `C` (Clusters), `D` (Diferido).
- **Dinheiro** em unidade menor inteira (`*_minor`) com moeda explícita; nunca vírgula
  flutuante. Datas em UTC, apresentação em `Africa/Luanda`.
- **Nomes só do dicionário.** Um nome novo entra no dicionário marcado como proposta, antes de
  entrar num ticket.
- **Documentos formais** levam tabela de cabeçalho, tabela de aprovação e controlo de versões;
  uma alteração relevante acrescenta linha de versão.
- **Atalho deliberado em código leva comentário `shortcut: <o limite>, <quando se revê>`.**
  A palavra-chave fica em inglês, porque é por ela que o `ponytail-debt` procura; o limite e o
  gatilho escrevem-se em português. Um atalho sem limite escrito é defeito, não atalho.
- **Nada está ratificado** até o fundador o dizer. A Carta, o dicionário e a classificação dos
  ADRs são propostas — não as apresentes como decididas.

## Os dez princípios

1. **Não inventar** — sem evidência, é desconhecido; sem calibração, é proposta.
2. **Não assumir completude** — produzir não é concluir, e entregar não é fechar: as caixas do ticket marcam-se com evidência, e as que não se cumprem ficam vazias e nomeadas.
3. **Não confundir verificação com leitura** — a máquina apanha o que os olhos não apanham.
4. **Não paralelizar sem vocabulário** — escritores paralelos sem dicionário divergem.
5. **Não alargar escopo em silêncio** — toda a alteração extra precisa de justificação.
6. **Não confiar cegamente noutro agente** — resultados verificam-se, incluindo os teus.
7. **Não esconder incerteza** — a incerteza declarada é barata; a escondida não.
8. **Não deixar o conjunto a contradizer-se** — corrigir num sítio é corrigir em todos.
9. **Não concluir sem auditoria** — execução complexa passa pelo completeness audit.
10. **Preservar conhecimento** — o que se descobriu tem de sobreviver a esta execução.

## Referências

| Ficheiro | Lê quando… |
|---|---|
| [`references/decomposicao.md`](references/decomposicao.md) | Vais partir a tarefa, modelar dependências, resolver um conflito de fontes ou manter estado de execução |
| [`references/contratos-de-agente.md`](references/contratos-de-agente.md) | Vais lançar um subagente ou definir o que ele devolve |
| [`references/evidencia-e-verificacao.md`](references/evidencia-e-verificacao.md) | Vais afirmar um facto, atribuir-lhe estado, ou **correr** a verificação (o `make` não corre aqui) |
| [`references/revisao-adversarial.md`](references/revisao-adversarial.md) | Estás a rever — o teu trabalho ou o de outro agente |
| [`references/encerramento.md`](references/encerramento.md) | Estás a integrar, auditar completude, escrever o relatório final, ou a limpar depois de um merge |

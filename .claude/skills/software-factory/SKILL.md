---
name: software-factory
description: Fábrica de software agêntica para a KAMBÁ — admissão e triagem do pedido, seis linhas de produção (achado→ticket, ticket→PR, PR→merge, falha em execução→correcção, conhecimento→canon, fecho→ratificação), ciclo interno com estações que não se avaliam a si próprias, portões de CI roteados pelo eixo tocado, isolamento de escritores concorrentes em worktrees, revisão adversarial com verificação do achado, métricas e realimentação. Usa esta skill sempre que a tarefa implementar um ticket KAM-NNN, tocar em mais de um documento do conjunto, alterar um ADR, uma decisão aberta ou o dicionário canónico, mexer no backlog mestre, atravessar componentes (packages, services, libs, db, tools), mudar migrações, contratos de evento ou regras de bloqueio, ou quando houver risco de regressão ou de divergência documental — mesmo que o utilizador nunca diga "multiagente", "plano", "subagentes" ou "fábrica". Também quando várias tarefas relacionadas chegarem juntas, quando houver trabalho em paralelo em mais do que um worktree, quando fizer falta validação independente de trabalho já feito, quando for preciso decidir que gates correr, e quando se for abrir ticket, fundir PR, fechar um epic ou converter uma lição em portão. Não a uses para uma edição pequena e isolada num só ficheiro.
---

# Fábrica de software agêntica — KAMBÁ

> **Um agente produz evidências; não produz a verdade.**
> **Uma fábrica produz evidência repetível; não produz confiança por decreto.**

Nenhum agente — nem tu — pode declarar sozinho que uma alteração está correcta, completa ou
segura. Toda a conclusão relevante assenta em evidência verificável e, quando o risco o
justificar, em validação independente de quem a produziu.

Esta skill existe porque o modo de falha dominante aqui não é escrever a coisa errada: é
**declarar-se pronto cedo demais**, e deixar dois documentos a dizer coisas diferentes sem
ninguém notar. Produzir não é concluir, e entregar não é fechar — o KAM-001, o KAM-002, o
KAM-128 e o KAM-129 foram entregues com PR verde e deixaram **62 caixas por marcar** entre os
quatro, sem que nenhum relatório o mencionasse. Um documento que contradiz o vizinho é um
defeito tão real como um teste vermelho; só não há compilador que o apanhe. Esta skill é esse
compilador.

O que a torna uma **fábrica**, e não um método, são cinco propriedades. Se uma delas não se
verificar no teu trabalho de hoje, não estás a correr a fábrica — estás a improvisar com
vocabulário emprestado.

```text
1. PORTA DE ENTRADA   todo o pedido é classificado e roteado antes de começar
2. LINHAS             cada trabalho recorrente tem artefacto de entrada e de saída
3. SEPARAÇÃO          nenhuma estação avalia o seu próprio produto
4. INSTRUMENTAÇÃO     a fábrica mede-se; o que não se mede não melhora
5. REALIMENTAÇÃO      um escape vira portão, não vira nota
```

## Proporcionalidade, e o que ela não gradua

O ciclo abaixo é o completo. Aplica as estações que o risco justifica e **diz quais saltaste** —
saltar em silêncio é o defeito que esta skill fecha; saltar com justificação é engenharia. Uma
gralha num comentário não precisa de grafo de dependências.

**Mas a proporcionalidade vale para o que não é um ticket.** Um `KAM-NNN` passa sempre por
revisão adversarial e fecha sempre com evidência nomeada, seja qual for o tamanho — decisão do
fundador (Outubro de 2026), que recusou graduar o rigor por ticket e recusou cortar o backlog
ao Piloto. Onde esta secção e a letra de um ticket parecerem discordar, prevalece o ticket.

Um sinal fiável de que precisas do ciclo inteiro: **não consegues nomear todos os documentos
que afirmam o que vais mudar**, ou vais lançar mais do que um agente a escrever no mesmo
conjunto.

---

## 0. Admissão — a porta de entrada

Antes de qualquer coisa, classifica o pedido. A classe determina a linha, a linha determina os
portões, e os portões determinam o que conta como feito. Classificar leva trinta segundos e
evita os dois erros simétricos: correr `make ci` inteiro para uma emenda de prosa, e tratar uma
falha observada em execução como se fosse um ticket por implementar.

| O pedido é… | Linha | Autoridade |
|---|---|---|
| Hipótese, auditoria, «vê se isto está certo», defeito avistado de passagem | **L1** achado → ticket | eu |
| Ticket `KAM-NNN` com critérios de aceitação | **L2** ticket → PR | eu |
| PR aberto à espera de CI, conflito ou comentário | **L3** PR → merge | eu, com CI verde |
| Sintoma observado a correr a pilha, um gate ou uma suite | **L4** falha em execução → correcção | eu |
| Decisão, nome, contrato, evidência ou risco novo a registar | **L5** conhecimento → canon | eu |
| Fechar um epic, ratificar a Carta, fechar um `D#`, assinar um limite | **L6** fecho → ratificação | **o fundador** |
| Uma edição isolada num só ficheiro | nenhuma — não uses esta skill | eu |

**Antes de arrancar, procura quem já está a trabalhar nisto — e não procures no `git`.** O
repositório é trabalhado em vários worktrees ao mesmo tempo (`git worktree list` dá 8 além do
checkout principal), em ramos que não se vêem uns aos outros.

> **O `git` não vê uma sessão a trabalhar.** Uma sessão desta app abre ramo com nome gerado —
> `claude/frosty-benz-177ecd` — e não committa nada até ter algo que preste. `git branch | grep
> KAM-NNN`, `git log --all --grep KAM-NNN` e `git worktree list` devolvem **zero** sobre um
> ticket que está a ser implementado neste momento. Medido: a admissão desta skill declarou «não
> há colisão» sobre o KAM-038 enquanto uma sessão o implementava, com o worktree e o ramo à
> vista nas três buscas.
>
> **O instrumento é a lista de sessões**, e corre-se primeiro:
>
> ```
> mcp__ccd_session_mgmt__list_sessions   # título, cwd, ramo, isRunning, PR
> ```
>
> O **título** da sessão é que leva o `KAM-NNN`; o ramo não. Uma sessão com `isRunning: true`
> sobre o teu ticket é uma colisão, e nenhuma das duas sabe da outra. Depois disto, as buscas do
> `git` servem para o que já está committado.

Sem a lista — noutra máquina, ou fora desta app — **não há instrumento**, e a colisão
descobre-se a olho ou ao abrir o PR. A receita manual, e o que ela não cobre, estão em
[`references/isolamento.md`](references/isolamento.md).

Os candidatos a arrancar agora leem-se do backlog, não da memória:

```bash
python .claude/skills/software-factory/scripts/vagas.py
```

Devolve os tickets cujas dependências já estão fechadas. É uma lista de **candidatos**: a lista
de paralelismo da estação 1.3 aplica-se depois dela, não antes.

> **E o backlog que ele lê é o teu, não o da base.** O `main` funde por *squash* várias vezes
> ao dia, e um ID livre no teu checkout pode já estar fundido. **Medido:** o ticket que fechou
> as dispensas do *gate* 3c abriu como KAM-163, passou a KAM-164 e ficou **KAM-165** — os dois
> primeiros foram tomados enquanto se escrevia, e a alteração mecânica fez-se **três vezes**.
>
> São **três** medidas antes da primeira edição, e nenhuma substitui as outras:
>
> ```bash
> git fetch publico main:refs/remotes/publico/main --force   # sem refspec só move o FETCH_HEAD
> git show refs/remotes/publico/main:specs/INDICE.md \
>   | grep -oE '^\| KAM-[0-9]{3} \|' | grep -oE '[0-9]{3}' | sort -n | tail -1
> gh pr list --repo albinoJimy/kamba-plataforma --state open --json number,title,headRefName
> git ls-remote --heads publico | grep -oE 'KAM-[0-9]{3}' | sort -u | tail -5
> git checkout -b fix/KAM-NNN-<slug> refs/remotes/publico/main
> ```
>
> **O `sort -n` não é enfeite.** O §4 está agrupado por epic, pelo que um `tail -1` sem ordenar
> devolve o último ticket do EPIC-11 — `KAM-127` no dia em que o maior era o 165. A primeira
> versão desta receita tinha esse defeito e mandou duas sessões para o mesmo número.
>
> **E a base não mostra um ID reclamado por um PR aberto**, que foi como nasceu a segunda
> colisão do mesmo dia: dois PRs com o mesmo `KAM-165`, e o segundo em `CONFLICTING` quando o
> primeiro fundiu. Daí o `gh pr list` e o `ls-remote`, que vêem o que a `main` ainda não tem.
>
> **E lê o `title` do PR, não o `headRefName`.** O nome de um ramo mente no instante em que o
> ticket dentro dele é renumerado, porque ninguém renomeia o ramo. Medido: um PR cujo título já
> dizia o número novo e cujo ramo continuava a dizer o antigo — o `ls-remote` não via o número
> reclamado, e foi preciso o título para o ver. O `ls-remote` fica para os ramos empurrados
> **sem** PR, que é o único caso que só ele vê. O mesmo vale localmente: o nome da
> pasta de um *worktree* e o `git worktree list` guardam o nome antigo — quem diz a verdade é o
> `.git/worktrees/<nome>/HEAD`.
>
> O mesmo vale para as contagens, para o número da próxima linha de «Controlo de versões» e
> para a dispensa que vais pagar: lêem-se da base, não do teu ficheiro. Uma delas pode já ter
> sido paga por outro ticket, e então a tua correcção é uma declaração morta.
>
> **E se entrares num worktree, confirma a base lá dentro.** O `EnterWorktree` ramifica de
> `origin/<default-branch>`, e aqui o `origin` é o espelho privado, sem antepassado comum com o
> `publico`: numa entrada medida, pôs a sessão em `f344990` — o merge de um PR dezenas de
> commits atrás.

As seis linhas, com artefacto de entrada, artefacto de saída, portões e a tabela de autoridade
completa — o que posso fazer sozinho e onde tenho de parar e pedir — estão em
[`references/admissao-e-linhas.md`](references/admissao-e-linhas.md).

---

## 1. O ciclo interno

Cada linha corre este ciclo. A diferença entre linhas está em onde entra, onde sai e que
portões se aplicam — não no rigor.

```text
DISCOVERY → IMPACTO → DECOMPOSIÇÃO → PARALELISMO → PRODUÇÃO
   → SELF-VALIDATION → REVISÃO ADVERSARIAL → INTEGRAÇÃO
   → VERIFICAÇÃO DO CONJUNTO → AUDITORIA DE COMPLETUDE → CONHECIMENTO → RELATÓRIO
```

Cada estação tem um papel **e uma proibição**. A proibição é o que produz o valor: um Explorer
que escreve deixou de ser uma segunda opinião e passou a ser mais uma fonte de texto por rever.

| Estação | Papel | Proibido | Saída verificável |
|---|---|---|---|
| Discovery | `Explore` | alterar o que lê | as lacunas, listadas |
| Impacto e desenho | `Plan` | editar ficheiros para testar hipóteses | contratos, riscos, trade-offs |
| Produção | `general-purpose` | alargar o escopo em silêncio | diff dentro de `FILES_IN_SCOPE` |
| Testes | agente distinto do autor | derivar os casos do diff | o nome da função de teste |
| Revisão adversarial | agente que não vê o meu raciocínio | concordar sem ter procurado | achados `CONFIRMADO` / `PLAUSÍVEL` / `MORTO` |
| Integração | eu | aceitar alteração inesperada | changeset auditado |

> **Nenhuma estação avalia o seu próprio produto.** É a regra que não tem excepção de
> conveniência. Quando o risco não justificar um revisor separado, diz que a revisão foi
> própria — não finjas que houve independência.

### 1.1 Discovery — antes de escrever

Não alteres nada nesta fase. O objectivo é saber o que o conjunto já afirma, não mudá-lo.
Delega a varredura a um subagente **`Explore`**: é read-only, devolve a conclusão em vez do
despejo de ficheiros, e mantém o teu contexto livre para a decisão.

```text
RESULTADO DA DISCOVERY
Objectivo:
Documentos envolvidos:
Componentes envolvidos (packages, services, libs, db, tools):
ADRs e decisões abertas tocadas (ADR-NNN, D#):
Tickets afectados (KAM-NNN):
Afirmações existentes sobre o tema (e o seu estado de verificação):
Nomes canónicos envolvidos (dicionário §3):
Contradições já visíveis entre documentos:
Testes e gates existentes que cobrem isto:
Riscos:
Hipóteses (ainda por validar):
Lacunas de informação:
```

**As lacunas são a parte que importa.** Uma discovery que não lista nada em falta ou não
procurou, ou está a esconder incerteza.

**Medições independentes vão numa só mensagem.** Entre dois comandos que não dependem um do
outro não há ordem a respeitar, e mandá-los um a um é a maior fonte de lentidão deste ciclo:
dezenas de idas e voltas por ticket, cada uma a pagar latência por nada. O ciclo é sequencial
nas **estações**, não nos comandos — e isto vale em todas elas, não só na discovery.

Quando o alvo é código que ninguém da sessão conhece, junta
`Skill(skill: "ponytail:ponytail-audit", args: "services/<nome>")` — é read-only e o que sai
dela entra como **riscos e hipóteses**, nunca como trabalho a fazer
([`references/ponytail.md`](references/ponytail.md)).

#### Fontes de verdade neste repositório, por ordem

Quando duas fontes discordam, **não escolhas em silêncio**. Regista o conflito no formato de
[`references/decomposicao.md`](references/decomposicao.md) e resolve-o contra a ordem abaixo.

| Ordem | Fonte |
|---|---|
| 1 | `specs/00_KAMBA_Carta.md` — forma do produto, registo de decisões e DoD do Piloto (hoje **proposta**) |
| 2 | `docs/tecnica/00_Arquitectura_Solucao.md` §8 — ADR-001…ADR-020; §13.3 — decisões abertas D1…D13 |
| 3 | `docs/adr/ADR-L001`…`ADR-L004` — **ADRs locais**, numeração própria; decisões de execução já tomadas (o `ADR-L003` regista uma decisão do fundador de 2026-10-18) |
| 4 | `specs/02_Dicionario_de_Dados_Canonico.md` §3 — nomes canónicos, com `canon/dicionario.yaml` derivado dele |
| 5 | `specs/00_System_Spec.md` — Foundation: capacidades, mapeamento capacidade → componente → epic, KPIs, SLOs e critérios de aceitação sistémicos |
| 6 | `specs/01_Engineering_Standards_e_Handoff.md` — DoR, DoD, os 18 gates do §4, convenções |
| 7 | `specs/INDICE.md` §4 — backlog mestre: a linha do ticket é o contrato (ID, tipo, estimativa, prioridade, fase, dependências) |
| 8 | O ticket `KAM-NNN` — em `specs/tickets/KAM-NNN.md` no EPIC-01, no `specs/EPIC-XX_*.md` nos outros dez — e os seus critérios de aceitação |
| 9 | `docs/tecnica/01`–`docs/tecnica/10` — desenho por subsistema |
| 10 | `docs/tecnica/evidencia/E1`–`E5` — factos sobre Meta, pagamentos, lei, licenças e módulos de entrada, **com o seu estado** |
| 11 | `docs/evidencia/KAM-NNN.md` — anexos de evidência por ticket (21 hoje); medições, procedimentos e registos que não cabem no bloco |
| 12 | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` — escopo do Piloto e hipóteses H1…H12 |
| 13 | Biblioteca exploratória `01`–`13` — **histórica**; corrigida pelos níveis acima |
| 14 | Código e testes — descrevem o comportamento que alguém decidiu preservar |
| 15 | Evidência obtida em execução (gates, suites, `make smoke`, output real) |

**Os ADRs locais não são ADRs canónicos, e a numeração separada é deliberada.** O
`docs/adr/README.md` fixa a regra: dar-lhes um número da sequência `ADR-NNN` fazia parecer que
eram canon. Não contradigas um `ADR-L` em vigor — e lê-os na discovery, senão contradizes uma
decisão sem saber que ela existe.

Três regras que esta ordem esconde:

- O código é fonte de verdade sobre o que **acontece**, não sobre o que **devia** acontecer. Um
  teste verde sobre comportamento errado continua a ser comportamento errado.
- `docs/tecnica/evidencia/` diz o que é **CONFIRMADO**, **INDÍCIO** ou **NÃO VERIFICADO**.
  Herda esse estado quando citares — promover um INDÍCIO a facto é o defeito mais comum aqui.
- O `docs/00-KAMBA-documento-mestre.md` é artefacto compilado e está desactualizado. Não o
  edites e não o cites como fonte. A biblioteca exploratória `01`–`13` também não decide nada.

### 1.2 Análise de impacto

Não julgues o tamanho pela contagem de ficheiros. **Uma linha no dicionário ou num ADR é maior
do que trezentas linhas num epic.**

```text
DIRECTO         ficheiros que vais alterar
INDIRECTO       documentos que afirmam o mesmo, índices, contagens, tabelas-resumo, consumidores
CANÓNICO        ADRs, decisões abertas, nomes do dicionário, linhas do backlog mestre
COMPORTAMENTAL  o que muda / o que TEM de ficar igual
VERIFICAÇÃO     o que deixa de estar verificado, o que precisa de nova evidência, que gate muda
FASE            o que muda de P/C/D, e se cria dependência de fase invertida
```

Neste repositório o impacto indirecto tem cinco sítios que escapam quase sempre:

- **`specs/INDICE.md` §4 (backlog mestre).** Dependências, prioridades e fases vivem aqui. Um
  ticket novo ou uma dependência nova muda o campo `Bloqueia` de outros tickets, replicado na
  tabela-resumo de cada epic. **Nunca edites um só lado** — o gate 3c lê as três superfícies.
- **`specs/02_Dicionario_de_Dados_Canonico.md` §3.** Um nome novo de tabela, coluna, evento ou
  estado pertence aqui antes de pertencer a um ticket, e `canon/dicionario.yaml` deriva dele
  (`make dict-export`). Um nome fora do dicionário avermelha o gate 3b.
- **`docs/tecnica/00` §8 e §13.3.** Um ADR canónico novo obriga a actualizar a contagem **e** o
  mapeamento ADR → documento, que vivem os dois em `docs/tecnica/INDICE.md` §5. Uma decisão de
  execução não vai para aqui: vai para `docs/adr/ADR-L<NNN>-<slug>.md`, com numeração própria.
- **Contagens e tabelas-resumo.** «20 ADRs», o total de tickets, «11 epics», os totais por
  epic e as linhas de controlo de versões. Uma contagem desactualizada é a assinatura típica de
  uma alteração feita a meio — e desde o KAM-158 há um linter que a apanha.
- **`ci/thresholds.yaml` e o `Makefile`.** Um pacote Node novo entra no `PACOTES_NODE` **e** no
  `ci/thresholds.yaml`; um ficheiro que nenhum estrato classifique falha o gate 4 de propósito,
  e o `coverage_gate` injecta a 0% o que nenhum relatório mediu.

O eixo que identificares aqui é o que escolhe os portões na estação 1.7. Impacto e portões são
a mesma pergunta feita duas vezes.

### 1.3 Decomposição e paralelismo

Divide em tasks pequenas o suficiente para um agente compreender, completas o suficiente para
produzir um resultado **verificável por si só**. O template da task, os estados do grafo e o
formato de estado de execução estão em
[`references/decomposicao.md`](references/decomposicao.md).

A `VALIDACAO` de cada task é **um comando**, não uma frase. Um gate, um teste nomeado, um
`make ci-<n>`. Se não consegues escrever o comando, ainda não sabes o que estás a construir.

> Paralelismo é permitido pela **independência**, não pela conveniência.

```text
[ ] Não alteram os mesmos ficheiros
[ ] Não dependem de resultado ainda não produzido
[ ] Não definem o mesmo nome, estado, evento ou contrato
[ ] Não tocam no mesmo estado partilhado (backlog mestre, dicionário, tabela de ADRs, índices)
[ ] Não acrescentam revisões de base de dados ao mesmo tempo (cada uma encaixa na anterior)
[ ] Não colidem semanticamente (duas respostas válidas e incompatíveis para a mesma pergunta)
[ ] Cada uma tem critério de validação próprio
```

Em dúvida, sequencial. Uma corrida perdida custa uma tarde; um conflito semântico integrado
custa a confiança em tudo o que veio a seguir.

**E a lição mais cara deste repositório não está na lista:**

> **Agentes a escrever em paralelo divergem nos nomes.** Cinco redactores sobre o mesmo desenho
> produziram três esquemas de `contacts`, três tabelas de consentimento, `valor_kz` contra
> `valor_minor` e dois eventos para a mesma confirmação de pagamento. Nenhum errou; nenhum
> tinha um nome canónico para seguir.

Daí a regra: **antes de lançar escritores em paralelo, fixa o vocabulário.** Cada contrato de
agente leva `specs/02_Dicionario_de_Dados_Canonico.md` e a linha do backlog mestre, e proíbe
inventar nomes sem os marcar como proposta. Se o vocabulário ainda não existe, criá-lo é a
primeira task, não uma limpeza posterior.

Os ficheiros de registo (`Makefile`, `.github/workflows/ci.yaml`, `docs/ci.md`,
`specs/INDICE.md`, tabelas de versões) são a **excepção consentida** à primeira caixa: colidem
sempre, as colisões são mecânicas, e resolve-as quem integra. Quando houver mais do que um
agente a **escrever**, lê [`references/isolamento.md`](references/isolamento.md) antes de os
lançar — worktree por escritor, e os recursos que são partilhados sem o parecerem.

### 1.4 Produção (redacção ou implementação)

Cada agente recebe um contrato explícito — papel, âmbito, o que pode e não pode assumir, o que
tem de devolver. O formato está em
[`references/contratos-de-agente.md`](references/contratos-de-agente.md).

Três regras que valem mais do que o resto desta secção:

**Não inventes.** Preços, prazos, limites de terceiros, nomes de parâmetros, artigos de lei,
APIs, campos, tabelas, capacidades de ferramentas — se não está confirmado, é
`NÃO VERIFICADO`. Se precisares de um valor para avançar, marca-o como **proposta** e diz onde
se calibra:

```text
HIPÓTESE
- Hipótese:
- Evidência que a sustenta:
- Estado (CONFIRMADO / INDÍCIO / NÃO VERIFICADO):
- Como validar (spike, pergunta escrita, parecer, medição):
```

Uma hipótese declarada é engenharia. Uma hipótese silenciosa é o defeito que só aparece quando
alguém assina um contrato por causa dela. E uma negativa trazida por um subagente — «isso não
existe no repositório» — é uma afirmação como as outras: confirma-a com comando próprio antes
de a deixares decidir escopo.

**Não alargues o escopo em silêncio.** Nada de reescrita oportunista, harmonização não pedida
ou limpeza não relacionada. Uma alteração fora de `FILES_IN_SCOPE` só passa se for tecnicamente
necessária, justificada e registada. Um defeito fora de escopo abre ticket novo — o que o põe
na **L1**, não neste PR. Um **resíduo textual** (sem código nem decisão) vai, numa linha, para
`docs/dividas-documentais.md`.

**Respeita o canon.** Não contradigas um ADR em vigor sem o substituir explicitamente; não
promovas uma decisão aberta a fechada sem o gatilho que a Carta nomeia; não marques fase `P`
para algo que depende de um ticket de fase 1.

**Escreve pelo mínimo que resolve** (`Skill(skill: "ponytail:ponytail", args: "full")`): a
alteração mais pequena que fecha a tarefa **inteira**, incluindo chamadores, testes e fixtures
que ela parte. Com uma fronteira que não se negocia — *mínimo* nunca é retirar uma barreira.
Uma política RLS, um fail-closed, um passo de canário, uma verificação de assinatura não são
código a mais: são o produto. As três regras de divergência estão em
[`references/ponytail.md`](references/ponytail.md).

### 1.5 Self-validation

Valida o teu próprio trabalho sabendo que isto **não substitui** a revisão independente. Serve
para não desperdiçares um revisor com defeitos que apanharias sozinho.

> **O `Makefile` diz o que cada gate faz; não é a forma de o correr.** Nesta máquina não há
> `make`, `node` nem `pnpm` no `PATH`, e um `make ci-2` responde `command not found` — o que não
> é «o gate passa», é «o gate não correu». As vias que funcionam, e as armadilhas que fazem um
> lint parecer verde quando saiu com 2, estão em
> [`references/evidencia-e-verificacao.md`](references/evidencia-e-verificacao.md). Lê-as
> **antes** de dizer que verificaste.

Do teu worktree, sem `make` no anfitrião, os quatro que pagam sempre:

```bash
cd tools && python -m lint_backlog --root .. check   # 3c: as três superfícies do backlog
cd tools && python -m lint_refs --root .. check      # 3: identificadores
cd tools && python -m lint_handoff --root .. check   # 3: caminhos dos blocos de handoff
cd tools && python -m lint_contagens --root .. check # 3: contagens em prosa
```

**O `lint_contagens` não corre de dentro de um worktree** e sai com código 2: o filtro do corpus
exclui tudo o que tenha `.claude` no caminho, e os worktrees vivem em `.claude/worktrees/`. É
defeito dele, registado como **dívida 44 de `docs/dividas-documentais.md`**, descoberto no
KAM-133 e atribuído ao dono do gate 3 — **não** ao KAM-158, que está entregue e foi quem criou o
passo. Até estar corrigido, confia no que o CI diz desse passo.

```text
[ ] Critérios de aceitação do ticket atendidos, um a um
[ ] As caixas do ticket marcadas — só as que têm evidência, com uma linha de evidência
    nomeada por caixa, na secção `### Verificação dos Critérios de Aceitação`
[ ] As caixas que não se cumprem ficam vazias, e o relatório diz quais e porquê
[ ] Afirmações novas têm estado de verificação (CONFIRMADO / INDÍCIO / NÃO VERIFICADO)
[ ] Nomes usados são os do dicionário; nomes novos estão lá, marcados como proposta
[ ] Nenhum documento vizinho ficou a contradizer este (procurado com Grep, não de memória)
[ ] Contagens, totais, tabelas-resumo e linha de controlo de versões actualizados
[ ] Compila e os testes do componente passam
[ ] Nenhuma alteração acidental no diff — lê o `git diff`, não confies na memória
[ ] Tratamento de erro adequado; fail-closed onde a governação o exige
[ ] Cobertura não regrediu (`ci/thresholds.yaml` classifica o que mediste)
```

> **As caixas do epic são o controlo, não decoração — e foram ignoradas quatro vezes.**
> Marca-se com evidência nomeada, nunca por memória do trabalho feito. Uma caixa que não se
> cumpre fica vazia e aparece com o estado `parcial` ou `não satisfeito` e a razão. E cumpre-se
> **à letra, não em espírito**: «p95 de 20 execuções» com 17 execuções não está cumprido,
> mesmo com margem de doze vezes. Quando a leitura divergir da letra, escreve-se a leitura e
> devolve-se a decisão a quem escreveu o critério — não se marca a caixa.

**O lint corre-se depois da última edição.** Correr antes e editar a seguir é como se não se
tivesse corrido. Diagramas Mermaid passam por um parser (`make mermaid`) antes de se dizer que
estão certos; SQL e DDL que nunca correram contra um PostgreSQL são **propostas**, não desenho
validado, e diz-se isso onde aparecem.

### 1.6 Revisão adversarial, com verificação

Esta é a estação que dá substância ao princípio central, e a primeira a ser sacrificada quando
há pressa. Não a sacrifiques.

A revisão **procura razões para o resultado estar errado**. Não confirma que está certo. Um
revisor que só relê o documento e concorda não produziu evidência nenhuma.

**Uma revisão adversarial por ticket.** É a decisão do fundador de Outubro de 2026: sem
segundas leituras, sem terceiras passagens, sem configuração nova a cada ticket. Os instrumentos
correm todos na **mesma passagem**, os achados juntam-se numa lista só, corrigem-se de uma vez,
e o PR funde.

**Lança-a assim que o diff existir, não no fim.** É read-only e não depende da tua
self-validation, pelo que as duas correm ao mesmo tempo. Lançada no fim, é tempo de relógio
somado em vez de sobreposto: **medido**, vinte minutos de revisão contra dois de
self-validation, no ticket das dispensas do *gate* 3c. O que não se antecipa é a conclusão — não
se funde antes de ela responder. E se a árvore mudou desde o lançamento, cada achado
`CONFIRMADO` verifica-se outra vez contra a árvore que vai fundir: aconteceu, e cinco dos dez
achados dessa revisão já estavam mortos quando ela respondeu.

```
Skill(skill: "code-review", args: "high")
Skill(skill: "ponytail:ponytail-review")   # + o eixo do que não devia existir
Skill(skill: "security-review")            # quando o diff toca RLS, segredos, identidade ou egress
```

Para trabalho documental — que é a maior parte do que se faz aqui — a revisão independente é um
subagente `general-purpose` que recebe **o documento e os requisitos, nunca as tuas
justificações**. O guião, com os padrões de defeito que este repositório já produziu, está em
[`references/revisao-adversarial.md`](references/revisao-adversarial.md).

A adição da fábrica é o que vem **depois** do achado. Um revisor instruído a encontrar
problemas encontra problemas, haja-os ou não. Por isso nenhum achado gera trabalho antes de
passar pela verificação:

```text
ACHADO → verificar contra o código e o canon → CONFIRMADO | PLAUSÍVEL | MORTO
```

Só o `CONFIRMADO` entra no portão de integração. O `PLAUSÍVEL` vai para o relatório com o que
falta para o decidir. O `MORTO` regista-se com a evidência que o matou — senão volta na próxima
auditoria e paga-se outra vez. As análises ficam em `docs/analises/ANALISE-NN-<slug>.md`, que é
onde vive a memória das revisões deste conjunto.

**Uma caixa por marcar não é trabalho por fazer**: pode ser trabalho feito cuja caixa ninguém
marcou. Confirma antes de abrir ticket.

### 1.7 Integração e verificação do conjunto

Antes de integrar, audita o changeset — o que mudou face ao que **era suposto** mudar:

```bash
git status --short && git diff --stat
```

Qualquer ficheiro que não esperavas ver é para investigar, não para aceitar. **E não procures o
que não pode aparecer:** `ci/coverage/`, `.venv/`, `ci/x11/`, `ci/prova-canario/` e
`packages/*/dist/` estão todos no `.gitignore`, pelo que nunca saem num `git status`. Os
suspeitos reais são os que o `git` mostra sem avisar que são erro — um índice com a contagem
antiga, uma tabela-resumo dessincronizada, uma linha de controlo de versões que ficou a meio, um
documento vizinho tocado por uma edição em lote. O portão de integração está em
[`references/encerramento.md`](references/encerramento.md).

Depois corre **os portões do eixo que tocaste**, não os que te lembrares. A tabela completa
eixo → portões, o custo de cada um, a ordem fail-fast e o que correr em background está em
[`references/portoes-e-velocidade.md`](references/portoes-e-velocidade.md).

E corre a verificação que atravessa documentos, que é por **máquina e não por leitura**:

```text
[ ] Backlog consistente e sincronizado com os epics (gate 3c)
[ ] Referências válidas — KAM, ADR, D, H, E, caminhos (gate 3)
[ ] Nomes canónicos (gate 3b), contagens em prosa (gate 3), diagramas no parser
[ ] Os portões do eixo, verdes, com o comando e o resultado registados
```

Uma verificação que corre duas vezes e muda alguma coisa na segunda passagem não é uma
verificação: é uma edição. Corre até estabilizar. Nesta sessão, a leitura dos relatórios dos
redactores não apanhou nenhuma das ~60 dependências em falta; o script apanhou todas, mais dois
ciclos e doze inversões de prioridade.

**E corre o sistema, não só as verificações.** Uma suite verde sobre uma pilha que não arranca é
o caso exemplar de teste a passar pela razão errada:

```bash
make up && make smoke     # /healthz dos cinco serviços, validado contra o contrato
```

Para mudanças no *wiring* de um serviço — porta, variável de ambiente, ordem de arranque,
superfície HTTP, composição do `infra/compose/` — **é a única evidência que conta**, e os três
portões que a tabela de eixos dá para TypeScript (`ci-1`, `ci-2`, `ci-4`) não a substituem:
compilam e cobrem o código, e nenhum deles levanta nada. Num worktree, confirma antes que não
estás a medir a pilha de outra sessão ([`references/isolamento.md`](references/isolamento.md)).

> **E depois de fundir, não perguntes ao `git` se fundiu.** A `main` funde por *squash* e há
> dois remotos sem antepassado comum (`origin` privado, `publico` activo): o
> `merge-base --is-ancestor` diz «não fundido» para um ramo que acabou de fundir, e para um
> ramo da outra linha o `merge-base` **falha** — e quem não verificar o código de saída lê o
> silêncio como «este ramo não tem nada a mais». Custou chegar a um passo de apagar sete
> worktrees com 164 a 254 commits cada. A prova é o estado do PR no GitHub; a receita e a
> limpeza estão em [`references/encerramento.md`](references/encerramento.md).

### 1.8 Auditoria de completude e encerramento

Compara o **pedido original** com o que existe agora — requisitos, tasks, produção, verificação
— e procura o que se perdeu pelo caminho. O formato da auditoria, o quality gate e o relatório
estão em [`references/encerramento.md`](references/encerramento.md).

Toda a afirmação relevante precisa de evidência nomeada:

```text
AFIRMAÇÃO: "O backlog está consistente."
EVIDÊNCIA:  python -m lint_backlog --root .. check → N tickets, 0 divergências
            (ciclos, prioridade invertida, fase invertida, reciprocidade);
            segunda passagem de sincronia → 0 divergências.
```

Sem evidência, escreve `NÃO VERIFICADO`. É informação útil. «Provavelmente está bem» não é.

Antes de fechar, faz o livro da dívida com `Skill(skill: "ponytail:ponytail-debt")`: lê os
comentários `shortcut:` e devolve-os com o tecto e o gatilho de revisão de cada um. Um atalho
que saia `no-trigger` — sem gatilho escrito — emenda-se no próprio comentário, no mesmo PR: é a
forma de dívida que apodrece em silêncio.

---

## 2. Velocidade

A fábrica é rápida por desenho, não por cortes. Seis regras, todas sobre fazer o mesmo trabalho
em menos tempo de relógio — nenhuma sobre fazer menos trabalho.

1. **Fail-fast, e por eixo.** Os linters de segundos primeiro (`lint_refs`, `lint_backlog`,
   `canon_lint`), depois `typecheck`, depois os testes do componente, depois os portões do eixo.
   Nunca `make ci` inteiro primeiro: um erro de tipos não precisa de esperar que um PostgreSQL
   suba para se revelar.
2. **O lint corre-se no fim.** Depois da última edição, não a meio.
3. **Portões lentos em background.** O `ci-8` e o `ci-6` levantam PostgreSQL em Docker e o
   `ci-8` inclui cinco minutos de carga de eventos; lança-os em background e continua. Não
   faças polling — a notificação chega.
4. **Vagas, não fila.** Correm em paralelo os tickets cujas dependências já estão fechadas
   (`vagas.py`), cada escritor no seu worktree, e os subagentes lançam-se na mesma
   mensagem, como todos os comandos independentes (§1.1).
5. **Não refaças a discovery.** `KNOWN_FACTS` no contrato do agente é o campo que mais poupa:
   sem ele cada subagente redescobre o mesmo conjunto e chega a conclusões ligeiramente
   diferentes — o que produz conflitos que não existiam.
6. **Decide e avança.** Quando tens informação para agir, age. Não re-derives factos já
   estabelecidos, não reabras decisões já tomadas, não enumeres opções que não vais seguir. Só
   uma decisão que é mesmo do fundador justifica parar.

**O que não se acelera:** o portão do fundador, a revisão adversarial, e a prova de que o lint
morde (os passos de canário dos gates 3b, 9, 11 e do `log-lint`). Velocidade só vale enquanto
preserva confiança — e há relatos públicos, **INDÍCIO** e sem anexo de evidência local, de que
com agentes o *throughput* sobe e a
estabilidade de entrega desce. A fábrica existe para que as duas subam juntas.

---

## 3. Métricas e realimentação

Uma fábrica que não se mede não melhora — repete. Seis indicadores, cada um com o seu
instrumento nomeado:

```text
artefactos que já existem
  VERDE À PRIMEIRA    gh pr checks <n>, primeira corrida
  TEMPO ATÉ MERGE     da abertura do PR ao squash
  CAIXAS POR MARCAR   as do ticket, contadas ao declarar entregue

sem instrumento neste repositório — lê-se à mão, e isso é uma lacuna
  CALIBRAÇÃO          achados CONFIRMADOS / achados levantados
  TAXA DE RETRABALHO  achados pós-feito / entregas declaradas
  ESCAPES POR PORTÃO  achados com o portão que os devia ter apanhado
```

Os três de baixo não se leem de nenhum artefacto que este repositório produza: a leitura é das
análises em `docs/analises/` contra os PRs. **Diz isso quando citares um deles** — um número
reconstruído à mão é `INDÍCIO`, não `CONFIRMADO`.

E a regra que fecha o ciclo:

> **Um escape que um portão podia ter apanhado vira portão.** Não vira aviso, não vira nota de
> rodapé, não vira «ter cuidado da próxima vez».

**Isto não contradiz «sem gates novos».** A decisão do fundador recusa cerimónia nova no ciclo
de um ticket — segundas leituras, passagens repetidas, configuração por ticket. Um portão
mecânico vai no sentido oposto: substitui vigilância humana por uma verificação que não se
esquece. A forma que este repositório usa é **entrar num gate que já existe** em vez de abrir
*job* novo — foi assim que o `log-lint` entrou no gate 2 e o X-11 no gate 6 — porque um *job*
novo acrescenta um contexto exigido ao *ruleset* de `main`, e isso é alteração de regra de
bloqueio, que precisa do fundador. O detalhe, os três destinos legítimos de um escape e o que
faz de um portão um portão estão em
[`references/metricas-e-realimentacao.md`](references/metricas-e-realimentacao.md).

---

## Convenções não negociáveis deste repositório

- **Português europeu/angolano**, na grafia do conjunto: `arquitectura`, `activo`, `facto`,
  `objectivo`, `correcção`, `acção`. Sem PT-BR. Termos técnicos consagrados ficam em inglês
  (`outbox`, `handoff`, `webhook`, `checkpointer`, `fact`).
- **Escala de verificação em três estados** em tudo o que é afirmação sobre o mundo:
  **CONFIRMADO** (fonte primária), **INDÍCIO** (fonte secundária ou inferência),
  **NÃO VERIFICADO**. Valores de desenho ainda não calibrados são *proposta*.
- **Jurídico leva `(a confirmar por parecer)`.** O conjunto trata APD, BNA, AGT e Termos da
  Meta — nenhuma leitura nossa é definitiva.
- **Fase em tudo o que é capacidade:** `P` (Piloto), `C` (Clusters), `D` (Diferido).
- **Dinheiro** em unidade menor inteira (`*_minor`) com moeda explícita; nunca vírgula
  flutuante. Datas em UTC, apresentação em `Africa/Luanda`.
- **Nomes só do dicionário.** Um nome novo entra no dicionário marcado como proposta, antes de
  entrar num ticket; `canon/dicionario.yaml` regenera-se com `make dict-export`.
- **Documentos formais** levam tabela de cabeçalho, tabela de aprovação e controlo de versões;
  uma alteração relevante acrescenta linha de versão. Não é cosmético: o gate 3c lê o «Controlo
  de versões» de cada documento, e um documento novo sem ele entra numa dispensa de
  `ci/backlog-allow.yaml` com prazo — que é dívida, não conformidade.
- Conventional Commits com ticket; ramo `feature/KAM-NNN-<slug>`. Tickets pequenos do mesmo
  tema podem partilhar um PR, com uma secção por ticket no corpo.
- Nada de binários, cobertura, `.venv` ou artefactos de build no commit. Nenhum segredo em
  texto claro — env var ou ficheiro montado em runtime.
- **Atalho deliberado em código leva comentário `shortcut: <o limite>, <quando se revê>`.** A
  palavra-chave fica em inglês, porque é por ela que o `ponytail-debt` procura. Um atalho sem
  limite escrito é defeito, não atalho.
- **Nada está ratificado** até o fundador o dizer. A Carta, o dicionário e a classificação dos
  ADRs são propostas — não as apresentes como decididas.

## Os doze princípios

1. **Não inventar** — sem evidência, é desconhecido; sem calibração, é proposta.
2. **Não assumir completude** — produzir não é concluir, e entregar não é fechar: as caixas marcam-se com evidência, e as que não se cumprem ficam vazias e nomeadas.
3. **Não confundir verificação com leitura** — a máquina apanha o que os olhos não apanham.
4. **Não paralelizar sem vocabulário** — escritores paralelos sem dicionário divergem.
5. **Não alargar escopo em silêncio** — toda a alteração extra precisa de justificação.
6. **Não confiar cegamente noutro agente** — resultados verificam-se, incluindo os teus; e um achado verifica-se antes de gerar trabalho.
7. **Não esconder incerteza** — a incerteza declarada é barata; a escondida não.
8. **Não deixar o conjunto a contradizer-se** — corrigir num sítio é corrigir em todos.
9. **Não trocar qualidade por velocidade** — velocidade só vale enquanto preserva confiança.
10. **Não concluir sem auditoria** — execução complexa passa pelo completeness audit.
11. **Preservar conhecimento** — o que se descobriu tem de sobreviver a esta execução.
12. **Um escape vira portão, e a fábrica mede-se** — sem indicador não há melhoria, há repetição.

## Referências

| Ficheiro | Lê quando… |
|---|---|
| [`references/admissao-e-linhas.md`](references/admissao-e-linhas.md) | Estás a classificar o pedido, a escolher a linha, ou precisas de saber onde parar e pedir ao fundador |
| [`references/portoes-e-velocidade.md`](references/portoes-e-velocidade.md) | Vais decidir que portões correr, em que ordem, e o que mandar para background |
| [`references/evidencia-e-verificacao.md`](references/evidencia-e-verificacao.md) | Vais afirmar um facto, atribuir-lhe estado, ou **correr** a verificação (o `make` não corre aqui) |
| [`references/isolamento.md`](references/isolamento.md) | Vai haver mais do que um agente a escrever, ou trabalhas num worktree |
| [`references/decomposicao.md`](references/decomposicao.md) | Vais partir a tarefa, modelar dependências, resolver um conflito de fontes ou manter estado de execução |
| [`references/contratos-de-agente.md`](references/contratos-de-agente.md) | Vais lançar um subagente ou definir o que ele devolve |
| [`references/revisao-adversarial.md`](references/revisao-adversarial.md) | Estás a rever — o teu trabalho ou o de outro agente — e a verificar achados |
| [`references/ponytail.md`](references/ponytail.md) | Vais usar as skills do `ponytail` numa estação, ou recebeste um achado de «cortar» |
| [`references/encerramento.md`](references/encerramento.md) | Estás a integrar, auditar completude, escrever o relatório final, ou a limpar depois de um merge |
| [`references/metricas-e-realimentacao.md`](references/metricas-e-realimentacao.md) | Fechaste uma linha e vais converter o que aprendeste em portão |

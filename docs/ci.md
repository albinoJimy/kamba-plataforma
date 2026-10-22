# Pipeline de CI — gates, alvos e donos

| Campo | Valor |
|---|---|
| Ticket | KAM-002 — Pipeline de CI base: gates fail-closed |
| Fonte normativa | [`specs/01_Engineering_Standards_e_Handoff.md`](../specs/01_Engineering_Standards_e_Handoff.md) §4 (os 18 gates) e §4.1 (limiares) |
| Desenho | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](tecnica/09_Topologia_Operacao_Escala.md) §7, [`docs/tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §4.8 |
| Plataforma | GitHub Actions ([`.github/workflows/ci.yaml`](../.github/workflows/ci.yaml)) |
| Estado | Gates 1, 2, 3, 3b, 4, 6, 7, 8, 9 e 11 **activos**; 5 reservado e a falhar; 10 e 12–18 fora de âmbito |

> **Nada está ratificado.** Os limiares, os donos e a plataforma de CI são
> *proposta* até o fundador os aprovar. Onde este documento diz «proposta», é
> porque nenhuma fonte canónica o decide.

---

## 1. O princípio

O pipeline é **fail-closed**: qualquer gate vermelho bloqueia a progressão. A
regra transversal do §4 acrescenta que **nenhum gate se marca `skip` sem ADR ou
aprovação registada** — e esse registo é [`ci/waivers.yaml`](../ci/waivers.yaml),
não uma condição no *workflow*.

Cada gate é um alvo `make ci-<n>`. O *workflow* só os orquestra. Três razões:

1. **Qualquer gate corre à mão**, localmente, com o mesmo comando que o pipeline
   usa. Um gate que só se reproduz no CI é um gate que se depura por tentativa.
2. **Nada fica preso à plataforma.** Trocar de CI não deve custar mais do que
   reescrever `.github/workflows/ci.yaml`.
3. **A numeração é a do §4 e não se renumera.** O gate 11 é o gate 11 na
   documentação, nos *waivers* e nos tickets a jusante.

---

## 2. Gate → alvo → dono

> **Os donos são *proposta*, e vale a pena dizer porquê.** `specs/01` §4 não tem
> coluna de dono. `docs/tecnica/09` §7 atribui donos a seis gates — isolamento,
> *eval*, licenças, *supply chain*, migrações e *smoke* — e **nenhum aos gates 1,
> 2, 3, 4 e 9**. O DoD do KAM-002 exige esta tabela com donos, pelo que a coluna
> existe; os cinco que faltavam são propostos aqui e precisam de ratificação.
> A lacuna está registada em [§7](#7-lacunas-do-canon-que-este-ticket-encontrou).

| # | Gate | Alvo | Dono | Origem do dono |
|---|---|---|---|---|
| 1 | Build a partir dos lockfiles | `make ci-1` | Plataforma | **proposta** |
| 2 | Lint, formato e tipos — e, desde o KAM-068, nenhum serviço a escrever fora do *logger* | `make ci-2` | Plataforma | **proposta** |
| 3 | Referências cruzadas (`KAM`, `ADR`, `D#`) e caminhos dentro dos blocos de *handoff* | `make ci-3` | Plataforma | **proposta** |
| 3b | Nomes canónicos | `make ci-3b` | Arquitecto de Plataforma | KAM-111 (activo desde o KAM-111) |
| 3c | Coerência do backlog: o §4 do `specs/INDICE.md`, o bloco de cada ticket e a tabela-resumo do §3 de cada epic | `make ci-3c` | Arquitecto de Plataforma | KAM-138 (activo desde o KAM-138) |
| 4 | Unit e cobertura | `make ci-4` | Plataforma | **proposta** |
| 5 | Integração | `make ci-5` *(reservado)* | — | **lacuna**: nenhum ticket o reclama |
| 6 | Isolamento de tenant (camada SQL: RLS, X-03, X-04, X-05) e *logs* sem identificadores (X-11) | `make ci-6` | Segurança | `docs/tecnica/09` §7 (activo desde o KAM-004; o X-11 entrou com o KAM-068; a suite ponta a ponta é KAM-066) |
| 7 | Contratos | `make ci-7` | Plataforma | KAM-007 (eventos); KAM-024 (webhooks da Meta, por fazer) |
| 8 | Migrações: aplicar, reverter, voltar a aplicar | `make ci-8` | Plataforma | `docs/tecnica/09` §7 (activo desde o KAM-003) |
| 9 | Segredos (árvore **e** história do PR) | `make ci-9` | Segurança | **proposta** |
| 10 | SAST | — | — | **lacuna**: sem ticket |
| 11 | SCA, licenças, vulnerabilidades e SBOM | `make ci-11` | Segurança | `docs/tecnica/09` §7 |
| 12–18 | Categorias, *eval*, imagem, deploy, aprovação, tag | — | ver KAM-067, KAM-078, KAM-088 | — |

`make ci` corre os **onze** activos: os seis do KAM-002 (1, 2, 3, 4, 9 e 11), o 8 do KAM-003, o 6 do KAM-004, o 7 do KAM-007, o 3b do KAM-111 e o 3c do KAM-138. A frase dizia «nove» e depois «dez» — o 7 estava a faltar na conta desde que o KAM-007 o ligou, e o KAM-138 limitou-se a incrementar. `make ci-waivers` valida as excepções.

---

## 3. O que cada gate activo faz

### Gate 1 — build

`pnpm install --frozen-lockfile --ignore-scripts`, `pnpm run build` e
`make lock-check`. As duas *flags* são a razão de ser do gate: o build vem do
*lockfile* e **não executa código de terceiros na instalação** — foi por
`postinstall` que vários ataques de cadeia de abastecimento passaram
(`docs/tecnica/08` §4.8; E4 §2.7, o incidente do LiteLLM).

`lock-check` é **offline** por desenho. A verificação dos *hashes* contra a PyPI
é `make lock-verify`, separada: o critério de aceitação do KAM-001 diz «termina
verde usando apenas lockfiles», e um gate que vai à rede por cada *pin* falha por
ligação e não por código — o que, para uma equipa em Luanda e para um *runner*
sem egresso, é o pior tipo de gate.

### Gate 2 — lint e tipos

`tsc` em todos os projectos e `lint_arch` (lista de bloqueio + estrutura).

**Não há *linter* de estilo.** A escolha do ESLint ficou declarada fora de âmbito
no KAM-001 ([ADR-L001](adr/ADR-L001-toolchain.md) §8) e não se decide aqui por
conveniência de ter a coluna preenchida.

**Desde o KAM-068 há um terceiro passo: `make log-lint`.** Nenhum ficheiro de
`services/*`, `packages/*` ou `libs/*` (fora das pastas `tests`) usa `console`,
`print`, `logging`, `traceback`, o `stdout` ou o `stderr`, nem sai com texto —
a única isenção é o próprio *logger*. Entrou neste *gate*, e não num *job* novo, porque é o que o *gate* 2
já é: uma verificação estática da fonte, sem executar nada. E traz o seu
canário, pela razão do *gate* 3b: 29 *fixtures* negativas têm de falhar, cada
uma pela regra do seu nome e só por ela, com as regras obrigatórias fixas no
código. A
política, o âmbito e o que o *lint* não apanha estão em [`logs.md`](logs.md) §4.1
e §7.

### Gate 3 — referências cruzadas

Falha se o repositório citar um `KAM-NNN` fora do backlog mestre, um `ADR-NNN`
fora de `docs/tecnica/00` §8, ou um `D#` fora de §13.3. Os conjuntos válidos são
**lidos das fontes canónicas**, nunca de constantes: hoje `KAM-001`–`KAM-130`,
`ADR-001`–`ADR-020`, `D1`–`D13`.

Varre `git ls-files`, não o *diff*. O *diff* torna o gate não-determinista — o
mesmo *commit* passa ou falha conforme a base — e deixa passar apodrecimento
pré-existente. Resolve também os `.claude/worktrees/*`, que são cópias completas
do repositório, ignoradas pelo git mas visíveis a qualquer varrimento do sistema
de ficheiros, cada uma com o seu próprio `KAM-999`.

**A série `D` está sobrecarregada no canon**: significa decisão aberta *e* prazo
em dias. Medido token a token sobre a árvore seguida pelo git: `D1`–`D13` são
decisões (168, 67, 62, 58, 62, 46, 41, 57, 79, 56, 10, 63 e 27 ocorrências);
`D0`, `D30` e `D60` são prazos. Um `D` fora do intervalo canónico é **aviso**,
não falha, e intervalos de prazos não se expandem — `Prazos D0–D30`
(`specs/EPIC-09`) inventava `D14`…`D29`, 32 referências que ninguém escreveu.
A correcção de fundo é o canon deixar de escrever prazos como `D30`, e está
pedida num ticket próprio.

Excepções em [`ci/refs-allow.yaml`](../ci/refs-allow.yaml), cada uma com
ficheiro, token e razão.

**Segundo passo: os caminhos dentro dos blocos de *handoff*** (`lint_handoff`, KAM-145). O
primeiro passo lê **identificadores** em todo o conjunto; este lê **caminhos**, e só
dentro dos blocos `### Handoff para Claude Code`, onde a regra é outra: esse bloco fala a
um processo cujo `cwd` é a raiz do repositório, pelo que ali os caminhos são relativos
à raiz (`../specs/01_Engineering_Standards_e_Handoff.md` §5). Recusa duas classes: o
caminho que, normalizado, sai da árvore, e o nome de ficheiro sem directório nenhum, que
não resolve de posição alguma. **Fora desses blocos não lê nada** — aí vale a
convenção do KAM-128, relativa à posição do ficheiro.

**Lê dois sítios, desde o KAM-155:** `specs/EPIC-*.md`, nos dez epics que mantêm os
blocos no próprio ficheiro, e `specs/tickets/*.md`, no EPIC-01, que os tirou de lá. Com
um glob só, o *gate* ficava verde sobre os dez e deixava **39** blocos sem ser lidos. A
lista de globos é explícita no código (`PADROES`) e a resolução tira repetidos: dois
globos sobrepostos contavam o mesmo ficheiro duas vezes, e a guarda da contagem passava
a mentir ao contrário — blocos a dobrar contra títulos a dobrar, que batem.

Duas guardas contra o gate mentir: o número de blocos encontrados tem de igualar o
número de blocos `## KAM-NNN` (um título mal escrito ou uma cerca que não fecha deixaria
parte da árvore sem ser lida, e o gate diria «conforme»), e uma excepção declarada que
não case nenhuma linha falha o gate.

Excepções em [`ci/handoff-allow.yaml`](../ci/handoff-allow.yaml), cada uma com o
excerto da linha e a razão. São para a linha cujo **assunto é uma forma de caminho**:
o literal que o executor tem de produzir, e não um ficheiro que ele abre. Hoje são
**quatro**, todas frases que ensinam ou ilustram a convenção de prosa do KAM-128 ou descrevem o resultado que um ticket produz.

Entra no `ci-3` e **não** como *gate* novo de propósito: um *gate* novo acrescentaria
um contexto exigido ao *ruleset* de `main`. Os sete mantêm-se.

**Terceiro passo: as contagens escritas em prosa** (`lint_contagens`, KAM-158).
«N tickets», «N ADRs», «N epics» são números que derivam de um sítio onde as
coisas se contam — as linhas `| KAM-NNN |` do `../specs/INDICE.md` §4, os
`ADR-NNN` do §8 do `tecnica/00`, os ficheiros de epic. Escritos à mão num
segundo sítio, deixam de acompanhar: aconteceu **quatro** vezes (dívidas
~~19~~, 26, 30 e o §1 do `INDICE`), e quatro vezes se corrigiu à mão. Este
passo confronta cada contagem com a sua fonte e imprime, quando falha, o sítio,
os dois números e o comando que reproduz o da fonte.

Três decisões que o tornam utilizável:

- **Lê uma zona, não o ficheiro todo.** Uma linha de «Controlo de versões» e uma
  secção «Verificação dos Critérios de Aceitação» registam o que era verdade
  **então**; corrigi-las falsearia o registo. `analises/` e `evidencia/` ficam
  de fora por inteiro, pela mesma razão: são registos datados.
- **A fonte depende de onde está escrito.** «São 11 tickets» dentro do `EPIC-04`
  fala desse epic; a mesma frase no `INDICE` fala do total. Um número passa se
  for **um dos dois** que a árvore conta, e não há terceira leitura.
- **Duas listas em [`ci/contagens-allow.yaml`](../ci/contagens-allow.yaml), com
  significados diferentes:** `excepcoes` são linhas em que o número **está
  certo** por não ser uma contagem do conjunto (a citação de um defeito passado,
  a descrição do conteúdo de outro documento) e não têm prazo; `dividas` são
  contagens **erradas** que pertencem a outro ticket, com dono, `ocorrencias` e
  `expira_em` — e a partir dessa data o *gate* falha. Uma declaração que não
  casa nada, em qualquer das duas, falha o *gate*.

E duas guardas contra dizer «conforme» sobre o vazio: cada grandeza declarada
tem de aparecer pelo menos uma vez (um padrão que deixa de casar nada não
protege nada, e isso não se vê no total), e a população encontrada tem de ficar
acima de um mínimo escrito à mão, como o `esperados=N` do resumo.

### Gate 3b — nomes canónicos

Entrou com o KAM-111. Falha se uma migração, um *schema* de evento, um ficheiro
do registo ou um documento de `docs/tecnica/` usar um nome que o dicionário
canónico substitui — e, nas três primeiras superfícies, um nome que o
dicionário não cobre e que não está em
[`canon/extensoes.yaml`](../canon/extensoes.yaml). O mecanismo, as regras e a
forma de acrescentar uma extensão estão em
[`docs/nomes-canonicos.md`](nomes-canonicos.md); aqui fica só o que o *gate* é
enquanto *gate*.

`make ci-3b` são **três passos, e os três contam**:

1. **`dict_export --check`** — [`canon/dicionario.yaml`](../canon/dicionario.yaml)
   corresponde ao §3 do dicionário. A fonte da verdade é o Markdown; o YAML é
   gerado. Um dos dois alterado sem o outro falha aqui.
2. **`canon_lint check`** — as quatro superfícies.
3. **`canon_lint canario`** — dez *fixtures* negativas têm de dar **exactamente
   um** achado, com a mensagem esperada, e dez positivas têm de passar.

> **O terceiro passo nasceu por causa das duas superfícies vazias, e fica
> depois de elas se encherem.** Quando uma superfície tem zero ficheiros, o
> passo 2 passa nela **sem ter lido nada**, e di-lo na saída («A SUPERFÍCIE
> AINDA NÃO EXISTE; nada foi verificado aqui»). Sem o canário, a prova de que
> essas verificações mordem vivia só num `unittest` — o padrão que deixou o
> *gate* 9 sete PRs sem prova (§3, *gate* 9). As duas encheram-se: `eventos`
> com o KAM-007 (os contratos de `contratos/eventos/`) e `registo` com o
> KAM-009 (`registry/plans.yaml`), e a frase deixou de aparecer na saída. O
> canário continua a correr, porque o que ele prova — que cada verificação dá
> **exactamente um** achado com a mensagem esperada — não é o mesmo que a
> superfície ter ficheiros limpos.
>
> **E o que o canário prova está no código, não no manifesto.** A primeira
> versão lia do YAML de *fixtures* quantos casos havia: com `casos: []` dava «0
> negativas vermelhas» e saída 0, e os testes continuavam verdes
> ([`ANALISE-05`](analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md),
> B1). O conjunto de divergências com *fixture* obrigatória, as duas que podem
> não a ter e o mínimo de uma negativa por superfície estão agora em
> `tools/canon_lint/cli.py`.

> **A superfície 3 tem duas formas desde o KAM-009.** Um ficheiro de
> `registry/` é uma **vertical** (chave de topo `id`, a forma de
> [`docs/tecnica/02`](tecnica/02_Agent_Runtime_Verticais.md) §5.1) ou os
> **planos** (chave de topo `plans`, o `registry/plans.yaml`: `plano` →
> entitlements por omissão). A forma lê-se pela chave de topo e **nunca** pelo
> nome do ficheiro. As chaves de topo de cada forma são listas fechadas, cada
> nome de limite é confrontado com as dez chaves do dicionário §3.2, e um
> ficheiro que não seja **nenhuma** das duas falha — não passa por não ter sido
> lido.

**Falha fechada**, e cada sítio tem um teste que falha se a regra for retirada
(prova por mutação: `ANALISE-05` §5):

- **uma revisão que o lint não consegue seguir falha.** As revisões são Python;
  o lint lê a árvore sintáctica e resolve cadeias, constantes de módulo,
  *f-strings* sobre elas, ciclos sobre constantes e chamadas a módulos
  auxiliares **declarados** — abrindo o auxiliar e seguindo-o com os argumentos
  da chamada. É assim que lê a revisão `0002` do KAM-004, que chama `db/rls.py`.
  Tudo o resto — a API de operações do Alembic, `sa.Table`, um `import` não
  declarado, um *alias* de `op`, uma constante reatribuída, uma revisão de que
  não se leu instrução nenhuma — é achado, com a linha;
- uma instrução SQL de forma desconhecida **falha**, e um bloco `$$` com
  `CREATE` ou `ALTER` lá dentro também;
- uma coluna com domínio no dicionário num `CHECK` ilegível, ou criada sem
  `CHECK` nenhum, **falha**;
- um ficheiro com forma de superfície fora dos padrões — uma migração em
  `services/x/migrations/`, um `.sql` em qualquer sítio, um `registry/x.YAML` —
  **falha** (sentinelas). As dez mínimas estão no código, e retirá-las da
  política é erro;
- um ficheiro de política em falta, mal formado ou com uma chave que nenhum
  código lê é **erro** (saída 2), não «conforme».

**As excepções têm contagem, âncora ou prazo.**
[`ci/canon-allow.yaml`](../ci/canon-allow.yaml) lista as variantes que ficam em
`docs/tecnica/`, por ficheiro, variante e **número exacto de ocorrências**: a
décima não entra atrás da primeira, e uma excepção que já não corresponde a
nada também falha. São 31 ocorrências: 12 **históricas** (a variante é citada
para dizer que foi substituída — cada uma com a **âncora** que o prova, porque
não têm prazo) e 19 **dívidas** — divergências reais que as doze do KAM-111 não
enumeram.

> **A lista de dívidas está hoje vazia, e foi para isso que o prazo existiu.**
> Eram nove entradas e seis variantes, com prazo a 2026-11-10 — a partir do dia
> seguinte o *gate* ficava vermelho em `main` e em todos os PR, de propósito.
> O **KAM-139** pagou-as, e pagou também as nove que entretanto entraram com o
> KAM-007 e o KAM-141: **54 ocorrências em cinco documentos técnicos**, com os
> valores convertidos para unidade menor onde a troca mudava a unidade. O
> `ci/canon-allow.yaml` tem `dividas: []`.
>
> O mecanismo fica, e é o que importa aqui: uma dívida nova é uma excepção
> **com prazo**, o prazo de 30 dias é *proposta* e conta-se de `criado_em`,
> `criado_em` não pode ser futuro, e a contagem prende a ocorrência nos dois
> sentidos — mais ocorrências do que as declaradas falha, menos também.

**O *gate* não usa `ci/waivers.yaml`.** Um *waiver* dispensa um *gate*; aqui o
que se declara é uma ocorrência, com a contagem que a prende. E um *waiver*
exige `aprovacao:<quem>@<data>`, que este ticket não tinha de quem obter.

**O que a revisão adversarial mudou.** A primeira versão passou os oito *gates*
e foi reprovada: três bloqueantes, nove maiores. Os defeitos eram os que as
`ANALISE-02` e `-03` já descreviam — o canário que se esvaziava, o domínio
fechado que se contornava com a forma que o `pg_dump` escreve
(`estado::text IN (…)`), a variante que não era vista dentro de uma cadeia
(`'{"valor_max_pedido_kz": 5}'`, o único sítio onde uma migração a escreveria),
SQL não literal que passava em silêncio contra o que esta secção afirmava. Estão
corrigidos, cada um com teste; o que não está — e o que se mediu — fica em
[`docs/nomes-canonicos.md`](nomes-canonicos.md) §1 e na `ANALISE-05`.

Medido: o *job* do *gate* 3b leva **7 s** no *runner* (Python 3.12); `make
ci-3b` num contentor Linux local (Python 3.13), 0,9 s — contra os 60 s do
critério. 49 instruções (21 da revisão `0001`, 28 da `0002`), 3 tabelas, 38
colunas e 20 valores de `CHECK`; 17 documentos.

### Gate 3c — coerência do backlog

Entrou com o KAM-138. O backlog diz as mesmas coisas em **três** sítios, e até
aqui nada os comparava: a linha do ticket em [`specs/INDICE.md`](../specs/INDICE.md)
§4 (o «contrato entre epics»), o bloco `## KAM-NNN — ` — em `specs/tickets/` no
EPIC-01, pela convenção do KAM-155, e dentro do ficheiro nos outros dez — e a
«Tabela Resumo de Tickets» do §3 de cada epic. Tipo, estimativa, prioridade,
fase e dependências estão replicados, e a verificação era manual: três tickets
seguidos (KAM-128, KAM-129, KAM-130) gastaram um critério de aceitação em
«segunda passagem de verificação dá 0 divergências».

**O que o distingue de uma comparação de tabelas** é a reciprocidade
`Dependências`↔`Bloqueia`. O §4 **não tem coluna `Bloqueia`**, pelo que comparar
só os campos que as duas superfícies partilham deixa passar uma aresta declarada
de um só lado — aconteceu na primeira versão do KAM-129 (a busca G5) e outra vez
em oito tickets, que o KAM-144 teve de repor à mão, registando por escrito que a
causa era este *gate* não existir. Na entrega do KAM-138 estavam **seis** arestas
outra vez por fechar, abertas pelos quatro tickets inscritos depois do KAM-144.

O que verifica, por ordem de execução:

1. **Sincronia linha↔bloco**, nos seis campos que os dois escrevem (título,
   tipo, estimativa, prioridade, fase, dependências). A mensagem diz o ticket, o
   campo e **os dois valores**, com ficheiro e linha de cada um.
2. **Órfãos nos dois sentidos** — linha sem bloco, e bloco sem linha.
3. **A terceira superfície**: a tabela-resumo do §3, nos cinco campos que tem
   (não tem coluna `Fase`).
4. **Reciprocidade do grafo**, nos dois sentidos.
5. **Ciclos**, reportados com o caminho completo (`A → B → C → A`) e não com o
   nome de um ticket.
6. **Inversões de prioridade e de fase.**
7. **Contagens derivadas**: a contagem e o intervalo de cada epic no §3.1, a
   soma da coluna contra o TOTAL, o intervalo e o total do TOTAL, e os números
   do §1. Nenhuma se copia; todas se recalculam do §4.
8. **«Controlo de versões»** de cada documento de `specs/` e `docs/`: a
   sequência não salta números, nenhum número aparece duas vezes, e onde o
   cabeçalho tem campo de versão ele iguala a última linha. O buraco e o número
   repetido são **a mesma causa vista dos dois lados** — dois ramos tomam o
   número em paralelo; se um renumera fica o buraco, se nenhum renumerar ficam
   duas emendas com o mesmo nome. A verificação da sequência sozinha não vê o
   repetido, porque trabalha sobre o conjunto.

   **Uma limitação declarada:** o *gate* lê a tabela, não o *diff*. Vê que a
   tabela é coerente consigo própria e com o cabeçalho, e **não** vê «este
   documento mudou e a tabela não acompanhou» — que é a omissão mais comum, e a
   que o KAM-138 cometeu no `dividas-documentais.md` antes da revisão
   adversarial a apanhar. Fechá-la exige ler o *diff* do PR, o que torna o
   *gate* não-determinista (o mesmo *commit* passa ou falha conforme a base),
   e é a troca que o *gate* 3 já recusou por escrito. Fica para quem tiver
   melhor ideia.

Três decisões que o tornam utilizável:

- **O *gate* não decide qual dos lados está certo.** Reporta os dois valores e
  falha. O §4 é o contrato e o bloco é a especificação; qual deles se corrige é
  de quem escreveu o ticket, e um lint que escolhesse por omissão esconderia
  metade dos defeitos ao «corrigi-los».
- **Os títulos comparam-se com uma regra de normalização escrita, e uma só:**
  colapsa-se a subida de directório (`../../docs/` ≡ `../docs/`). Um título pode
  conter um caminho relativo, e pela convenção do KAM-128 o caminho é relativo
  ao documento que o escreve — o §4 e um bloco de `specs/tickets/` escrevem-no
  legitimamente com profundidades diferentes. Três títulos dependem disto hoje
  (KAM-111, KAM-139, KAM-140). O resto — `código`, *itálico*, travessões —
  compara-se tal como está escrito.
- **Duas verificações nascem como aviso, com o estado conhecido declarado em
  [`ci/backlog-allow.yaml`](../ci/backlog-allow.yaml):** as inversões e o
  controlo de versões. O estado inicial não é limpo, e a alternativa a declará-lo
  era não verificar nada. Uma inversão ou um documento que **não** esteja
  declarado falha desde o primeiro dia; quando as listas esvaziarem, as duas
  passam a falha sem ninguém mexer no código. Uma declaração que deixe de casar
  alguma coisa **falha** (código 2), como nos irmãos.

É **fail-closed sobre a própria entrada**: um epic sem §3, um bloco sem tabela de
campos, um campo obrigatório ausente, dois blocos para o mesmo ticket ou uma
população abaixo do mínimo escrito à mão dão código 2, não «0 divergências». Um
lint de coerência que dê verde por não ter conseguido ler nada é o modo de falha
que ele existe para não ter.

Reutiliza o leitor do §4 do `lint_refs` (`seccao` e `LINHA_BACKLOG`, públicos
desde este ticket): duas gramáticas para a mesma tabela era a forma garantida de
o *gate* 3 e o 3c discordarem sobre o que é uma linha de ticket.

Entra nos `needs` de `gates do KAM-002` e **não** no `main.json`, pela mesma
razão do 3b ([lacuna 17](#7-lacunas-do-canon-que-este-ticket-encontrou)): por
esse caminho bloqueia o *merge* na mesma, sem precisar de um *token* com
`administration: write`.

### Gate 4 — unit e cobertura

Mede com `node --test --experimental-test-coverage` (sem dependência: o Node 24
já traz) e com `coverage.py`, ambos em **LCOV** — o único formato que as duas
ferramentas emitem sem tradução nossa. Depois aplica
[`ci/thresholds.yaml`](../ci/thresholds.yaml).

#### Os dois lados passam a medir o mesmo universo (KAM-132)

Vale dizê-lo antes da taxonomia, porque durante onze versões deste documento
«cobertura» significou **duas coisas diferentes** em cada metade do
repositório, e era o número agregado que o §4.1 comparava com o limiar:

| | O que entra no denominador | Como |
|---|---|---|
| Python | Todo o `.py` **medido por um alvo**, importado ou não — e desde o KAM-151 há um `--source=` por cada pasta do âmbito (`tools/`, `libs/py-core/src`, `services/agr/src`) | `coverage run --source=<pasta>` percorre o disco |
| Node, até ao KAM-132 | Só o que algum teste **carregou** | o V8 reporta os *scripts* que correram |
| Node, desde o KAM-132 | Todo o código do âmbito que o Node executa (`.ts`, `.mts`, `.cts`, `.tsx`, `.js`, `.mjs`, `.cjs`, `.jsx`), carregado ou não | o `coverage_gate` lê o âmbito do disco e injecta a 0% o que nenhum relatório mediu |

> **O título desta secção diz «o mesmo universo» e não «a mesma régua»**, de
> propósito: a **definição de linha** continua diferente nas duas metades
> (lacuna 23). O que o KAM-132 fechou é o universo medido, que era a assimetria
> com consequência no número — e fechou-o do lado Node. Do lado Python o
> universo não se garante por injecção mas por **cablagem**, um `--source=` por
> pasta do âmbito, e faltava o de `services/agr/src/`: é o que o **KAM-151**
> acrescentou, com o teste que torna a falta vermelha em vez de invisível
> (lacuna 25).

A consequência da linha do meio era precisa e pior do que parece: **um serviço
Node inteiro sem um único teste não fazia o *gate* 4 vermelho.** Mantinha-o
verde, porque não era medido — o limiar de 75% aplicava-se à amostra que o
próprio código escolhia, os ficheiros que alguém se lembrou de importar num
teste.

> **`--test-coverage-include` não resolve isto**, ao contrário do que a
> [§7](#7-lacunas-do-canon-que-este-ticket-encontrou) lacuna 10 supunha quando
> foi escrita. É um **filtro** sobre o que o V8 reportou, e nunca vai ao disco.
> Está medido no Node 24.21.0 — com `--test-coverage-include=src/**` sobre uma
> *suite* que carrega um ficheiro, o relatório fica com esse ficheiro e mais
> nenhum; com `--test-coverage-include=src/storage/motor.ts`, que nenhum teste
> carrega, o relatório fica **vazio** em vez de ganhar `motor.ts` a 0% — e está
> escrito no próprio Node, em `lib/internal/test_runner/coverage.js`: «This
> check filters out files that do not match the include globs».
>
> **E a *flag* de inclusão não se usa, porque faz pior do que nada.** A primeira
> versão do KAM-132 passava-lhe o âmbito, para o LCOV ficar igual ao que o
> *gate* conta. A revisão adversarial mostrou o custo por execução: a inclusão
> **retira do relatório tudo o que não esteja na lista**, e um ficheiro que
> nenhum estrato classifica não está nela — logo deixava de chegar ao *gate* e
> deixava de o falhar. Um `packages/core-ts/fora.ts` carregado por um teste
> falhava o *gate* sem a *flag* e passava com ela. A regra que impede um
> directório novo de deixar de ter cobertura exigida em silêncio tinha ficado
> **inalcançável** do lado Node.
>
> O que o `make coverage-node` passa é **`--test-coverage-exclude`** com os
> ficheiros que os `excluidos` do `ci/thresholds.yaml` já não contam. A lista
> não se escreve no `Makefile`: pede-se ao `coverage_gate`
> (`--exclusoes-node <pacote>`), que a deriva do mesmo ficheiro de limiares que
> depois classifica o que foi medido. Uma segunda lista a divergir dos limiares
> põe ficheiros fora da medição sem ninguém dar por isso, que é exactamente o
> defeito que este *gate* existe para não ter.
>
> São **caminhos exactos, não *globs***. O `ci/thresholds.yaml` lê padrões com
> `fnmatch` e o Node lê-os com o seu próprio *glob*: `*` atravessa barras num e
> não no outro, e um `./` à cabeça faz o padrão do Node não bater em nada
> (medido: `--test-coverage-include=./src/**` dá zero ficheiros). Com caminhos
> exactos não há tradução nenhuma a divergir. E o `coverage_gate` **recusa** um
> caminho com espaço em branco, porque o `Makefile` expande a lista sem aspas e
> um caminho partido em dois deixava de bater, em silêncio.

Quem conta o código sem testes é o `coverage_gate`: lê do disco os ficheiros que
os `padroes` dos estratos classificam e os `excluidos` não retiram, e **injecta
a 0%** os que nenhum relatório mediu, imprimindo-os pelo nome. O denominador de
um ficheiro injectado é o seu número de linhas, que é a régua que o próprio Node
usa — o `LF` do LCOV do Node é o número de linhas do ficheiro, comentários e
linhas vazias incluídas (medido: nos 26 registos de `packages/core-ts/src/` em
medição o `LF` deu exactamente o `wc -l` de cada um). Contam-se os terminadores
de linha do JavaScript (LF, CR, LS e PS) e **não** os do `str.splitlines` do
Python, que divide também em `\x0b`, `\x0c` e `\x85`: um ficheiro de cinco linhas
com um *form feed* dentro de um literal dá `LF:5` no Node e dava 8 pelo
`splitlines`.

A procura começa nas **raízes dos `padroes`** — os primeiros segmentos literais,
hoje `libs/`, `packages/`, `services/` e `tools/` —, e não na raiz do
repositório. Não é arrumação: `*/identity/*` apanha qualquer caminho com esse
segmento, porque o `*` do `fnmatch` atravessa barras, e uma cópia de
`packages/core-ts/src/` dentro de `tmp/` — que o `.gitignore` ignora — levava o
estrato `critico` de 94% para **46%**. Um ficheiro de limiares cujos padrões
comecem todos por `*` não diz por onde procurar, e é **erro de configuração**,
não universo vazio.

Isto tem quatro consequências que ficam ditas em vez de serem descobertas:

- **Os `excluidos` passam a valer duas vezes.** Além de tirarem um ficheiro
  medido da avaliação, tiram-no da injecção e do `--test-coverage-include`. Um
  ponto de entrada (`services/*/src/server.ts`) ou o serviço de identidade
  (`packages/core-ts/src/identity/contactos.ts`, medido contra a base de dados
  no *gate* 8) não passam a denominador por não serem carregados.
- **Acrescentar um padrão a `ci/thresholds.yaml` pode baixar o número**, porque
  traz ficheiros novos para o denominador. Antes só mudava o limiar aplicado.
- **Árvores de trabalho e pastas de ferramenta não contam.** `.claude/worktrees/`
  tem cópias inteiras do repositório; ficam fora por não estarem numa raiz, e
  uma pasta com ponto à cabeça **dentro** de uma raiz fica fora pela regra do
  ponto.
- **O universo é o disco, não o índice do git.** Um ficheiro por versionar
  dentro de uma raiz conta; o número local pode portanto divergir do número do
  CI, que mede um *checkout* limpo. É a mesma propriedade do lado Python
  (`coverage run --source=.` também lê o disco) e é o que torna a demonstração
  deste *gate* reproduzível à mão, mas vale saber: **o número do CI é o que
  decide**, como já valia para o *gate* 11 (§8).

**O que custou**, no *run* do CI do PR do KAM-132 — o mesmo conjunto de oito
relatórios LCOV avaliado nas duas réguas, pelo que a única variável é a régua
(detalhe e comandos em [`evidencia/KAM-132.md`](evidencia/KAM-132.md)):

| | `restante` | `critico` |
|---|---|---|
| antes (régua antiga) | 91% — 9652/10526 linhas, 100 ficheiros | 99% — 4802/4810 linhas, 26 ficheiros |
| depois (o *gate*) | 91% — 9652/10526 linhas, 100 ficheiros | 94% — 4802/5055 linhas, 29 ficheiros |

**O `restante` é idêntico nas duas réguas, até à linha.** O que mudou está todo
no `critico`: entraram
`packages/core-ts/src/identity/index.ts`,
`packages/core-ts/src/storage/index.ts` e
`packages/core-ts/src/storage/motor.ts`, 245 linhas a 0%, que nenhum teste
importa. **No `restante` não havia nada invisível** — os seus 16 ficheiros
TypeScript são todos carregados por algum teste —, pelo que os 75% nunca
estiveram em risco e o limiar não foi tocado. O que mexe no denominador do
`restante` é o `coverage_gate` a crescer com baterias próprias, não a injecção.
**O estrato que este ticket aperta é o `critico`**: 94% contra 90% deixa cerca
de 250 linhas de folga, e três dos seus 29 ficheiros estão a 0% por nenhum teste
os importar.

E a propriedade que faltava, por execução: um módulo de **50 declarações em 355
linhas** sem um único teste, posto em `packages/core-ts/src/`, deixava o
`restante` **exactamente igual** (91%, 9418/10291, 99 ficheiros) e passa a
levá-lo a **88%** (9418/10646, 100 ficheiros). Três pontos, e o ficheiro sai
nomeado no relatório do *gate*.

**O que nenhum documento tinha é a taxonomia.** O §4.1 nomeia os estratos — «≥
90% em código de dinheiro, isolamento e validador; ≥ 75% no restante» — e não diz
como classificar um ficheiro num deles. A classificação é por *glob* de caminho,
avaliada **na ordem escrita**: o primeiro padrão que bate decide.

> **O estrato `critico` esteve vazio até ao KAM-004, e hoje só tem código de
> isolamento.** Os dois *helpers* de `tenant_guard` caem nele e estão a 100%.
> Continua a não existir código de dinheiro nem de validador no repositório: os
> padrões desses dois estão escritos para os tickets que os vão criar (KAM-052+
> pagamentos, KAM-007 validador), e o gate começa a morder neles no dia em que o
> primeiro ficheiro bater num padrão. Um limiar de 90% sobre zero ficheiros não
> protege nada — e foi por isso que isto esteve sempre dito, e não implícito.
>
> **Desde o KAM-011 o estrato tem também `*/storage/*`**: a porta de
> armazenamento, em TypeScript e em Python. É a camada «Storage» do isolamento
> (`docs/tecnica/08` §3.1), e entra inteira — a guarda e a assinatura dos
> pedidos —, porque é a assinatura que impede a URL de um objecto de abrir
> outro. Medido no *run* do PR do KAM-011: estrato `critico` a 100% (2879 de
> 2879 linhas, 18 ficheiros — os dois `tenant_guard` e os dois `storage/`).
>
> **Desde o KAM-014 o estrato tem também `*/chr/*`**: o ChannelResolver, que é
> **o sítio onde o `tenant_id` nasce** para o estado do grafo
> (`docs/tecnica/01` §7.2). Um defeito aqui não é um bug: é uma mensagem de um
> cliente entregue ao assistente de outra loja, ou uma conversa em modo `humano`
> interrompida pelo bot. A medição que conta é a de `db/tests_chr/`, **por
> ficheiro**, pela mesma razão do `identity/contactos.ts`: o CHR resolve contra
> uma base com três papéis diferentes, e sem ela só correm as recusas à entrada.
> O `chr/fila.ts` fica de fora (`excluidos`): é casca sobre o BullMQ, e quem o
> exercita é uma fila real.

Trunca-se, não se arredonda: o ticket diz «descer 1 ponto abaixo falha o gate»,
pelo que 89,9% não é 90%.

**O limiar é agregado por estrato, não por ficheiro**, porque é assim que o §4.1
o escreve: «Cobertura de linhas no restante ≥ 75%» é uma percentagem do estrato.
Isto tem uma consequência que vale dizer em vez de descobrir: **um módulo
pequeno sem testes nenhuns não faz o gate vermelho** — faz o número descer, o
que desde o KAM-132 também vale para o TypeScript, mas um estrato grande
absorve um ficheiro pequeno. Está medido, e não inferido — o PR de teste do gate
4 acrescentou primeiro um módulo de 21 linhas sem cobertura, o estrato
`restante` foi de 79,4% para 79,1% (2091/2643 linhas em 42 ficheiros), e o gate
passou. Com 2091 linhas cobertas, descer abaixo de 75% exige mais de 145 linhas
não cobertas de uma vez.

Ficheiro medido que nenhum estrato classifica **falha** o gate, e não é nota: é
a única forma de um directório novo não passar a ter cobertura exigida sem
alguém decidir isso. Um ficheiro do âmbito que nenhum relatório mediu **não**
falha por si: entra a 0% e deixa o limiar decidir — fabricar um achado a partir
de uma medição que o gate inventou seria o gate a avaliar-se a si mesmo.

> Um piso por ficheiro apanharia o módulo de 21 linhas, e o §4.1 não o pede.
> Acrescentá-lo aqui seria inventar requisito; fica registado na §7 como lacuna
> do canon, para quem decidir o limiar decidir também a sua granularidade. O
> KAM-132 não o acrescentou por essa razão, e não por ser difícil.

### Gate 9 — segredos

**Duas passagens, e nenhuma substitui a outra** (KAM-131):

| Passagem | Alcance | Comando |
|---|---|---|
| `tree` | a árvore seguida pelo git, **agora** | `scan_secrets … tree` |
| `history` | os *blobs* que o intervalo do PR acrescenta à história | `scan_secrets … history --base <ref> --head <ref>` |

Varre por **forma** e não por conteúdo: chaves com prefixo conhecido, blocos de
chave privada, credenciais em URL, e atribuições a nomes que significam segredo
com entropia suficiente. O *scanner* é o mesmo nas duas passagens; o que muda é
o conjunto de objectos que lê.

#### A segunda passagem: os *blobs* novos do PR

Até ao KAM-131 o *gate* via só a árvore final. Um segredo posto no *commit* A e
retirado no *commit* B passava — a árvore já não o tinha — e entrava no `main`
com o *merge*, porque o `main` recebe os dois *commits*. Era a lacuna 9 do
[§7](#7-lacunas-do-canon-que-este-ticket-encontrou) e o achado M8 da
[`ANALISE-02`](analises/ANALISE-02-KAM-002-pipeline-ci.md), **e era exactamente
o cenário com que esta secção justifica o *pre-commit***.

O conjunto de *blobs* sai de **duas travessias**:

- `git rev-list --objects <base>..<head>` — todo o objecto **alcançável** da
  cabeça e não da base. Dá o conjunto, mas **um** caminho por objecto: o `git`
  imprime cada objecto uma vez, com o nome em que a travessia o encontrou.
- `git log --raw -c` sobre o mesmo intervalo — dá **todos** os caminhos e o
  *commit* em que cada *blob* entrou, que é o que a correcção precisa de saber.
  `-c` e não `-m`: com `-m`, numa cabeça que é o *merge commit* de teste do PR, o
  *diff* contra cada pai arrastaria tudo o que o `main` ganhou desde a bifurcação
  — o `main` inteiro. Com `-c`, um *merge* leva só os caminhos que diferem de
  **todos** os pais: nada num *merge* limpo, e o que ele introduza por si quando
  o houver.

> **O `-c` custou duas evasões para aparecer.** A primeira versão corria
> `git log --raw` sem nenhum dos dois, e nessa forma o `git` não imprime sequer o
> cabeçalho de um *merge*. A revisão adversarial construiu, e correu, duas
> maneiras de pôr um segredo num *commit* do PR e o *gate* ficar verde: (a) um
> *evil merge* que acrescenta o **mesmo** *blob* na pasta do canário e fora dela
> — o `rev-list` nomeava só o caminho do canário, a área permitia-o, e o
> resultado dependia da ordem alfabética da travessia; (b) um *blob* que já
> estava na base e que um *evil merge* repõe fora da área — o `rev-list` exclui-o
> por ser alcançável da base, e o `log` sem `-c` não o via. Ambas fecham com o
> `-c`, e cada uma tem o seu teste. Está em
> [`ANALISE-14`](analises/ANALISE-14-KAM-131-gate-9-na-historia.md) A1 e A2.

A **deduplicação é por SHA de objecto** no que custa (ler o *blob* e casar os
padrões), e nunca na aplicação das áreas permitidas: as áreas de
[`ci/secrets-allow.yaml`](../ci/secrets-allow.yaml) aplicam-se a **todos** os
caminhos em que o *blob* entrou, com o caminho que tinha nesse *commit*. Um
segredo movido para fora da pasta do canário num *commit* intermédio é achado —
deduplicar e aplicar a área de um só caminho daria verde pelo caminho mais
conveniente.

**O que o *gate* faz quando não há intervalo está escrito, por accionamento,** e
não deixado ao caso (`tools/scan_secrets/historia.py`, `SEM_INTERVALO`):

| Accionamento | Sem SHA de base |
|---|---|
| `pull_request`, `pull_request_target`, `merge_group` | **gate vermelho** — é o accionamento que decide um *merge*, e um *gate* que não sabe o que varrer não dá passagem. Cada um destes traz a base na sua própria chave do evento, e as três estão na cadeia do `GATE9_BASE`: um accionamento *fail-closed* cuja chave não vá no *job* ficaria vermelho em **todas** as execuções no dia em que se ligar (`ANALISE-14` A10) |
| `push` com `before` a zeros (ramo novo) | modo `so-arvore`, **declarado**: não existe estado anterior, e o `main` só recebe *commits* por PRs que foram varridos |
| `workflow_dispatch`, `schedule` | modo `so-arvore`, **declarado**: o accionamento não traz intervalo |
| execução local (`make ci-9` sem as variáveis) | modo `so-arvore`, **declarado** |

No modo `so-arvore` o comando imprime `passagem da historia NAO CORRIDA` com a
razão, e um `::warning::` para que a linha chegue ao resumo do *job* — **não** dá
a passagem por satisfeita. E um intervalo que existe mas não se resolve é sempre
vermelho: base ou cabeça que o `rev-parse` não acha, um clone **raso** (com o
`fetch-depth: 0` nomeado na mensagem de erro), ou um *blob* que está no intervalo
e que o `git cat-file` não devolve.

**Num accionamento que decide um *merge*, um intervalo de zero *commits* é
erro.** A cabeça de um `pull_request` é o *merge commit* de teste, que é novo por
construção: zero *commits* ali significa que a base e a cabeça vieram trocadas,
ou iguais. Foi assim que a revisão adversarial pôs o *gate* a não varrer nada e a
dizer-se limpo, trocando duas linhas do YAML sem nenhuma asserção falhar
([`ANALISE-14`](analises/ANALISE-14-KAM-131-gate-9-na-historia.md) A3) — e é por
isso que as asserções de `test_ci_gate9.py` passaram a prender a **linha
inteira**, e não a expressão solta.

**O relatório diz o que não varreu.** Conta os *blobs* que leu e descodificou,
os *bytes* desses, e à parte os que saltou por extensão de binário e os que não
são texto UTF-8 — com as palavras `NAO varrido(s)`. A primeira versão somava os
*bytes* antes de descodificar e contava os *blobs* que *pretendia* ler: dizia «1
*blob* novo, 73 *bytes* lidos, limpo» sobre um ficheiro que não tinha varrido
(`ANALISE-14` A4). **A lista de extensões de binário fica como está** — alterar o
*scanner* por forma está fora do âmbito do KAM-131 —, e com ela fica o limite:
quem comete escolhe a extensão, e na história o ficheiro não precisa de
sobreviver ao *commit* seguinte (`ANALISE-14` A5).

O *job* passa os três valores em bruto (`github.event_name`,
`github.event.pull_request.base.sha || github.event.before`, `github.sha`) e
**não decide nada**: a decisão é uma função pura com testes. Isto é deliberado —
**não há *lint* de *workflows*** (§7, lacuna 15), pelo que uma condição escrita
em YAML não seria verificável por teste nenhum. As três linhas e o
`fetch-depth: 0` são confrontados por
`tools/lint_arch/tests/test_ci_gate9.py`, e são isso que torna uma mutação ao
YAML detectável.

> **O erro conhecido, e a sua direcção.** `github.event.pull_request.base.sha` é
> a ponta de `main` no momento do evento. Se `main` andou desde então, o
> *merge ref* que o *checkout* traz tem outro primeiro pai e o intervalo inclui
> *commits* de `main` — o *gate* varre a mais, não a menos. Um segredo já em
> `main` faria um PR inocente ficar vermelho, o que é um falso alarme mas **não**
> uma passagem indevida. Preferiu-se isso a adivinhar a base: o critério de
> aceitação 4 pede que o `base` chegue ao *gate* sem o *workflow* o adivinhar.

**O mesmo scanner corre como *hook* de pre-commit**, sobre o que está em *stage*,
e o KAM-131 **não lhe mudou o âmbito**. O ticket exige-o, e não é conveniência: um
segredo que passa o pre-commit e chega ao servidor deixa de se remover apagando
uma linha — fica na história, e a correcção passa a ser reescrever a história
**e** rodar a chave. O *hook* é local, contorna-se e pode nem estar instalado; a
segunda passagem do *gate* é a rede que apanha isso.

Áreas permitidas em [`ci/secrets-allow.yaml`](../ci/secrets-allow.yaml), por
**classe** e não por interruptor. Nem as *fixtures* são passe livre: a única área
onde um valor de forma real é permitido é a pasta do canário, que existe para
provar que o scanner funciona.

**Um digest nunca é achado.** É público por desenho — serve para verificar, não
para autenticar — e reportá-los dava 11 falsos positivos só com o SHA fictício
dos testes do KAM-001. O reconhecimento serve para **suprimir**: evita que um
`sha256:` seja lido como atribuição.

A amostra no relatório nunca revela o valor: os **quatro primeiros**
caracteres, os **dois últimos** e o comprimento. (O KAM-002 escreveu aqui
«quatro caracteres e o comprimento», e `_ofuscar` sempre mostrou seis — a
descrição estava errada, não o código. `ANALISE-14` A15.) Um relatório de
segredos que imprime o segredo copia-o para os *logs* do CI, que é exactamente
onde ele não pode estar.

> **O canário prova-se no *gate*, e não só num teste unitário.** A pasta do
> canário é a única área onde um valor com forma real é permitido, pelo que a
> varredura da árvore passa por lá sem o apanhar — e é isso que se quer. Mas
> assim a única prova de que o *scanner* detecta alguma coisa vinha de um
> `unittest`, que durante sete PRs não era corrido por nada que pudesse falhar
> (§3, *gate* 4). O `make ci-9` passou a copiar o canário para fora da área e a
> exigir nove achados ou mais; hoje dá 17. É uma leitura do CA — que pede que um
> canário numa *fixture* **falhe** o PR — e não a sua letra: a área permitida
> existe, e a prova de que o *gate* morde está agora no *gate*.

#### A *push protection* do GitHub, e porque é que ela não é um defeito

Num repositório público há **dois** detectores de segredos a olhar para o
canário: o do *gate* 9 e o do próprio GitHub. O segundo recusa o `push` com
`GH013 — Repository rule violations`, e o desbloqueio é manual, por segredo,
feito por uma pessoa na interface. Foi assim que a cópia pública ficou criada.

**O problema nunca foi o `push` que já passou: era o próximo.** Cada padrão novo
que o *scanner* aprender traz um valor novo ao canário, e volta a parar o `push`
de quem o acrescentar — com uma mensagem que não explica que é esperado.

Desde o **KAM-157** existe um [`.github/secret_scanning.yml`](../.github/secret_scanning.yml)
com um `paths-ignore` de **uma** entrada: a pasta do canário. Decisão do
fundador, 2026-10-18.

Três coisas que isto **não** é, e que importa dizer:

- **Não é uma área cega nova.** O `ci/secrets-allow.yaml` já declarava essa
  pasta como a única onde um valor com forma de segredo é permitido, com razão
  escrita e verificada por máquina. A via alinha o *scanner* do GitHub com uma
  excepção que já existia.
- **Não torna o canário invisível ao *gate* 9.** São dois *scanners*, e o nosso
  continua a varrer a pasta — e o `make ci-9` copia-a para fora da área
  permitida e exige nove achados ou mais; hoje dá 17.
- **Não pode crescer em silêncio.** O
  `tools/scan_secrets/tests/test_push_protection.py` fica vermelho se o
  `paths-ignore` deixar de coincidir **exactamente** com a área declarada, se
  ganhar um caminho a mais, ou se o nosso *scanner* alguma vez passar a ler
  aquele ficheiro. Uma área cega que ninguém declarou é o único modo de falha
  sério desta via.

### Gate 11 — SCA, licenças, vulnerabilidades e SBOM

Gera SBOM CycloneDX 1.6 por alvo e confronta as licenças dos componentes
instalados com [`ci/licenses.yaml`](../ci/licenses.yaml). A lista de bloqueio não
se reimplementa: chama `lint_arch deps`, do KAM-001.

Lê **do disco**, não da rede: os metadados estão nos pacotes que o
`make bootstrap` instalou. Consequência a assumir: sem `bootstrap` não há
componentes para varrer, e o `Makefile` encadeia os dois.

Avaliam-se **expressões** SPDX, não cadeias. `MIT AND BUSL-1.1` (Meilisearch, E4
§2.13) falha, porque num `AND` a pior manda; `MIT OR Apache-2.0` passa, porque
num `OR` escolhemos uma permitida. Quatro veredictos, não dois:

| Veredicto | O que fazer |
|---|---|
| permitida | nada |
| negada | tirar a dependência, ou *waiver* com ADR |
| **pendente de decisão** | fechar a decisão aberta que a trava (`D#`) |
| desconhecida | descobrir a licença e registar; nunca deixar passar |

O estado `pendente_de_decisao` é exigido por `specs/EPIC-07` para Redis/Valkey: o
Valkey é `BSD-3-Clause`, que está na *allowlist*, e aprová-lo por via da licença
fecharia a **D12** pela porta de trás — a escolha entre Redis e Valkey *é* a
decisão.

#### A *allowlist* proposta pelo ticket dava três falsos vermelhos

A proposta (`MIT, Apache-2.0, BSD, ISC, PostgreSQL, MPL-2.0`) está marcada como
*proposta*. Aplicada à letra, contra as dependências que o repositório tem:

| Problema | Evidência |
|---|---|
| `BSD` não é identificador SPDX | está instalado `BSD-3-Clause` |
| `PSF-2.0` fora da lista | `typing-extensions@4.16.0`, fixado nos **dois** `.in` |
| `UNLICENSED` fora da lista | os sete `package.json` do monorepo que o declaram (os outros dois `proprios` são pacotes Python sem campo de licença) |
| `Python-2.0` fora da lista | `argparse@2.0.1`, via `js-yaml` → `cosmiconfig` → `@commitlint/load` |

Corrigido: identificadores SPDX exactos, `PSF-2.0` e `Python-2.0` acrescentados
com razão, e os pacotes do *workspace* resolvidos por **identidade** — pôr
`UNLICENSED` nas permitidas deixaria passar qualquer dependência de terceiros que
a declarasse.

#### SBOM por serviço, e não nove cópias

O `pnpm` tem uma loja única e o `venv` é um só, pelo que «o que está instalado» é
sempre o *workspace* inteiro. A primeira versão dava nove ficheiros com os mesmos
92 componentes — o que satisfaz a letra de «SBOM por serviço» e não a pergunta a
que um SBOM existe para responder.

O fecho real vem do `pnpm-lock.yaml`, por travessia a partir das dependências
directas de cada importador.

É determinista — sem *timestamp*, chaves ordenadas. Um SBOM que muda a cada
execução deixa de se poder comparar, e comparar é metade da utilidade de o ter.

##### A travessia atravessa um `link:` (KAM-133)

Uma dependência de outro pacote do próprio *workspace* resolve-se no *lockfile*
como `link:../../packages/core-ts` — um caminho relativo ao importador, e não uma
versão publicada. A primeira versão da travessia descartava essas linhas, e com
isso o `services/gwy` levava três componentes e não mostrava nem o
`@kamba/core-ts` que carrega nem o `bullmq` que o `core-ts` lhe traz. **O custo
não era o de hoje, era o do dia seguinte:** no dia em que um pacote nosso tome
uma dependência de terceiros, ela não apareceria no SBOM de nenhum dos serviços
que o carregam, e a pergunta «o que é que este serviço tem dentro» passava a ter
resposta errada sem ninguém dar por isso.

O caminho mapeia-se de volta à chave do importador (`services/gwy` +
`../../packages/core-ts` → `packages/core-ts`) e a travessia continua dali,
transitivamente, com visitado-é-visitado: dois pacotes nossos podem declarar-se
um ao outro, e uma travessia ingénua não terminaria.

**Atravessar não é copiar.** Ao entrar num pacote do *workspace* seguem-se só os
grupos que um consumidor herda — `dependencies` e `optionalDependencies` — e não
as `devDependencies`, que são as ferramentas com que esse pacote se constrói e
não fazem parte do que o serviço carrega. As `devDependencies` do **próprio**
alvo continuam a contar: sem isso a raiz, que só tem `devDependencies`, ficava
com zero componentes.

**E excluir um grupo um nível acima não chega, porque ele volta a entrar um
nível abaixo.** Um *peer* opcional já resolvido escreve-se, na secção
`snapshots:`, debaixo de `optionalDependencies:` — indistinguível a olho de uma
`optionalDependencies` verdadeira. O `bullmq@6.3.11` declara o `pg` em
`peerDependencies` com `peerDependenciesMeta.pg.optional: true`, e o `pg` só
está resolvido porque o `@kamba/core-ts` o declara nas suas `devDependencies`.
Seguir essa aresta punha o `pg` e mais treze no `services/gwy`, no `com` e no
`onboarding-web`, que não o têm — **14 de 41 componentes, por um caminho que a
exclusão de um nível acima tinha acabado de fechar.** A primeira versão do
KAM-133 publicou-os, e a revisão adversarial independente mediu-os.

Por isso lê-se também a secção `packages:`, de onde saem os *peers* opcionais de
cada pacote, e **não se segue uma aresta de `optionalDependencies:` cujo nome
seja um *peer* opcional do pacote.** Não se perde nada: um *peer* só está
resolvido porque alguém na árvore o fornece, e esse alguém declara-o. O
`ioredis` é *peer* opcional do `bullmq` exactamente pela mesma via e **continua**
no fecho dos três serviços, porque o `core-ts` o declara em `dependencies`; e as
`optionalDependencies` verdadeiras continuam a seguir-se — são elas que põem os
seis `@msgpackr-extract/*` no fecho.

**O oráculo desta regra não é um raciocínio nosso: é o próprio `pnpm`.** A
travessia é confrontada, importador a importador, com
`pnpm --filter <alvo> list --prod --depth Infinity --json`, e o oráculo medido
está guardado em `tools/sbom/tests/oraculo_pnpm.json` com o `sha256` do
*lockfile* do dia — se o *lockfile* mudar e o oráculo não, o teste diz que está
velho em vez de abençoar o erro. Era a verificação que faltava: a primeira
versão foi validada só com *fixtures* escritas por quem escreveu o código, e
elas passaram todas enquanto o documento publicava 14 componentes a mais.

**O pacote do *workspace* entra como componente, com `dependsOn` — não se
promovem só os seus terceiros.** É decisão de desenho do documento, e a razão é
que a outra forma responde pior à pergunta a que o SBOM existe para responder:
promover o `bullmq` para dentro do `gwy` e deixar o `@kamba/core-ts` de fora diz
*que* o `bullmq` lá está e não *porque* — e é «porquê» que alguém pergunta no dia
em que o `bullmq` aparecer num boletim de segurança. Os SBOM passam a ter o campo
`dependencies` do CycloneDX, ordenado nas duas dimensões como o resto do
ficheiro. **Um componente sem entrada nesse campo é um componente cujo grafo o
gerador não conhece; uma entrada com `dependsOn` vazio é um componente que não
depende de nada** — e a distinção importa, porque do lado Python há *pins* e não
um grafo resolvido, pelo que os terceiros `pypi` ficam de fora do campo em vez de
entrarem a mentir que não dependem de nada.

Há um **terceiro** estado, e é o que mente: a **entrada parcial**. O `kamba-agr`
saía com `dependsOn: [kamba-core]` quando o `pyproject.toml` declara três, e o
`starlette` e o `uvicorn` estavam no mesmo documento, com versão — com entrada,
quem lê conclui que o grafo é conhecido. Uma aresta que o manifesto declara e
cuja outra ponta está no documento **entra sempre**; omitir o nó é não afirmar o
que não se sabe, apagar a aresta é afirmar o que é falso.

**O lado Python tem a mesma ligação, e tinha o mesmo defeito.** Não por
instalação editável — o `make bootstrap` instala os três `requirements/*.txt` com
`--require-hashes --no-deps` e **não** instala `kamba-core` nem `kamba-agr` em
modo nenhum —, mas por declaração: o `services/agr/pyproject.toml` nomeia
`kamba-core` em `[project].dependencies`, e o `kamba-core` não aparecia no SBOM
do `services/agr`. Mesma travessia, mesmo gerador, mesmo ticket. Só se resolvem
nomes de pacotes **nossos**; a atribuição de terceiros do lado Python continua a
vir dos *pins* de `requirements/*.in`, que é o único sítio onde há versões.

Contagem de componentes por alvo, antes e depois, medida com
`python -m sbom --root .. check` sobre um `pnpm install --frozen-lockfile` limpo
(110 pacotes npm) e os três *locks* de Python instalados:

| Alvo | Antes | Depois |
|---|---|---|
| `kamba` (conjunto) | 142 | 142 |
| `services/gwy` | 3 | 25 |
| `services/com` | 3 | 25 |
| `services/onboarding-web` | 3 | 25 |
| `services/worker-canal` | 20 | 42 |
| `services/agr` | 8 | 9 |
| `packages/core-ts` | 38 | 39 |
| `packages/contracts` | 1 | 1 |
| `libs/py-core` | 1 | 1 |

O conjunto **não muda**, que é o que se esperava: o fecho completo já estava
certo, e é sobre ele que correm licenças e vulnerabilidades. E cada serviço
continua a ser um serviço: 25 não é 142.

> O número de um serviço é menor do que o seu fecho porque o SBOM cruza o fecho
> com o que está **no disco**: os seis `@msgpackr-extract/*` são binários por
> plataforma e só um se instala. Em fecho, cada um dos três serviços leva 27
> terceiros e três pacotes nossos.

#### Fronteira com o KAM-067

O ticket manda não duplicar. A divisão, dimensão por dimensão:

| Dimensão | Gate 11 (KAM-002) | KAM-067 |
|---|---|---|
| Unidade | por **serviço** (código-fonte, lockfiles) | por **imagem** (camadas) |
| Momento | cada **PR** | *build* da imagem e **release** |
| Artefacto | artefacto do CI, 90 dias | guardado com o *release*, no manifesto da tag |
| Gate que falha | 11 | 14 (imagem) e 18 (*release* sem SBOM) |
| Digests, cosign, quarentena, egress | **fora** | **todo** |

O gerador é o mesmo, e é por isso que vive em `tools/sbom/` e não em
`ci/supply-chain/`.

#### O que o KAM-067 acrescentou a este gate

A tabela acima foi escrita antes do KAM-067 e continua certa quanto à
**fronteira**; o que mudou é que a parte do KAM-067 que se verifica **no
repositório** passou a correr aqui, em cada PR. `make ci-11` chama, no fim,
`make supply-chain`:

| Passo | O que faz |
|---|---|
| `supply_chain check` | imagens por *digest* e no inventário; nenhuma instalação em *runtime*, e as de *build* só do *lockfile*; serviços de compose só de leitura; lista de saídas por serviço; registo de licenças por versão coerente com a política e com a lista de bloqueio; quarentena do Renovate; workflows sem chaves estáticas |
| `supply_chain canario` | copia o repositório, aplica 59 defeitos um de cada vez, e exige que cada um dê vermelho **pela regra esperada** |

Não é um gate novo, de propósito: os gates 14 (publicação da imagem) e 18
(*release*) são do KAM-078, que é quem constrói e publica imagens. Isto é a
verificação estática, anterior a existir imagem — a mesma relação que o
varrimento da OSV tem com o gate 14, mais abaixo. O nome do *job* e
`esperados=9` no resumo não mudaram.

Uma condição do próprio `tools/sbom` também mudou: **uma licença proibida só se
dispensa com *waiver* que cite um ADR que exista**. Uma `aprovacao:<quem>@<data>` continua a
servir para uma licença por determinar, e deixou de servir para uma AGPL ou uma
BUSL (`tools/sbom/tests/test_excepcao_em_adr.py`).

O que fica por fazer — `cosign verify` real, SBOM por imagem, *flags*
*Enterprise* — e porquê, está em [`supply-chain.md`](supply-chain.md) §9. As
regras, o inventário de imagens e o guia de excepções estão no mesmo documento.

---

> **O *job* no GitHub continua a chamar-se `gate 11 — SCA, licencas e SBOM`**,
> sem a palavra «vulnerabilidades». O nome do *job* é o **contexto do *required
> check***: está no *ruleset* e nos *runs* dos seis PRs de teste que são a
> evidência da §8. Renomeá-lo invalidaria os dois ao mesmo tempo, por uma
> palavra. A tabela da §2 e esta secção dizem o que o *gate* faz; o nome do *job*
> fica estável de propósito.

#### Vulnerabilidades (OSV)

O critério de aceitação diz que o *gate* 11 «falha com vulnerabilidade crítica
**sem excepção registada**». Essa metade do *gate* não existia na primeira
versão deste ticket — e, pior do que faltar, não estava declarada em sítio
nenhum, enquanto o `ci/waivers.yaml` dizia ao leitor que `alvo` podia ser «uma
CVE». Foi a revisão adversarial que o encontrou ([`ANALISE-02`](analises/ANALISE-02-KAM-002-pipeline-ci.md) B2).

Consulta-se a **OSV** (<https://osv.dev>) por `purl`, e não `pnpm audit` ou
`pip-audit`, por três razões: é uma fonte para os dois ecossistemas, consultada
pelo identificador que o SBOM já produz, sem tradução nossa pelo meio; não
precisa de gestor de pacotes nem de credenciais, o que encaixa no «sem chaves
estáticas» do CA; e devolve o intervalo afectado por versão, pelo que a decisão
é sobre a versão que está no *lockfile*.

Só `CRITICAL` bloqueia — é o que o critério nomeia. As outras entram no
relatório como aviso, sem parar o trabalho de ninguém. Uma severidade ausente
**não** bloqueia: bloquear por falta de metadados transformaria cada aviso
incompleto num PR parado.

> **Fail-closed inclui a rede.** Se a OSV não responder, o *gate* falha. Um
> *gate* de segurança que passa quando não consegue verificar é um *gate* que
> mente. Para trabalho local sem rede existe `KAMBA_SEM_REDE=1`, que **salta** o
> varrimento dizendo-o em voz alta — e uma execução feita com ela **não**
> satisfaz o *gate* 11. O CI nunca a define.

Verificado a correr, e não por inspecção: `lodash@4.17.11` e `django@3.0.0`
devolvem 48 vulnerabilidades, 5 delas `CRITICAL`, entre as quais a
`GHSA-jf85-cpcp-j695`. Sobre os 76 componentes instalados deste repositório:
zero.

Para dispensar uma: entrada em [`ci/waivers.yaml`](../ci/waivers.yaml) com
`gate: 11` e `alvo` igual ao `purl` do pacote ou ao identificador da
vulnerabilidade. Um *waiver* sem `alvo` não dispensa nada.

**Isto não duplica o *gate* 14.** O `specs/EPIC-08` atribui ao *gate* 14
(KAM-067) «vulnerabilidade crítica sem excepção registada também falha», e é
verdade — mas por **imagem** e no **release**, sobre o que a imagem contém
depois de construída. O *gate* 11 corre por **PR**, sobre as dependências
declaradas nos *lockfiles*, antes de existir imagem nenhuma. São dois momentos e
dois objectos; apanhar no primeiro é mais barato, e não dispensa o segundo.

---

### Gate 6 — isolamento de tenant

Entrou com o KAM-004, que ligou a *row-level security*. É a **camada SQL** do
isolamento — X-03, X-04 e X-05 da matriz do `docs/tecnica/08` §3.7; as rotas, as
tools, o storage e a injecção de *prompt* (X-01, X-02, X-06 a X-10) são do
KAM-066 e não estão aqui. O desenho, a política e os papéis estão em
[`isolamento.md`](isolamento.md); esta secção é só sobre o *gate*.

Usa o mesmo PostgreSQL descartável do gate 8, pelo mesmo orquestrador
(`db/gate_bd.py --suite tests_isolamento`), e pela mesma razão: a *suite* semeia
dois tenants e ataca um com o contexto do outro, e isso não se faz contra uma
base que mais alguém use.

Três coisas tornam este *gate* difícil de satisfazer pela razão errada:

- **É parametrizado sobre o catálogo.** A *suite* pergunta à base que tabelas
  têm coluna `tenant_id`, em qualquer schema aplicacional. Uma tabela nova entra
  sozinha em todos os testes; sem receita de sementes, o *gate* falha.
- **Cada caso afirma primeiro a metade positiva.** «A não vê B» prova-se
  trivialmente com uma base vazia. Cada teste exige antes que A veja as suas.
- **A recusa é conferida pelo texto, não só pelo código.** `42501` é o SQLSTATE
  de uma linha recusada pela política **e** de um privilégio em falta. Um teste
  que aceitasse qualquer `42501` passava se alguém tirasse o `INSERT` a
  `kamba_app` — pela razão errada.

As excepções vivem em [`ci/rls_exceptions.yaml`](../ci/rls_exceptions.yaml) e em
[`ci/secdef_allowlist.yaml`](../ci/secdef_allowlist.yaml), os dois vazios. Ao
contrário de um *waiver*, **exigem um ADR** e não uma aprovação datada: uma
tabela com `tenant_id` sem RLS é uma decisão de arquitectura, não uma dispensa
com prazo. E uma excepção morta — para uma tabela que já tem RLS, ou que já não
existe — falha o *gate*.

**O estrato `critico` deixou de estar vazio.** Desde o KAM-002 que o limiar de
90% não tinha código sobre que morder (§3, *gate* 4). Os dois *helpers* de
`tenant_guard` — Python e TypeScript — caem nele, e estão a 100% (240 de 240
linhas no *run* do PR do KAM-004).

#### X-11 — *logs* sem identificadores (KAM-068)

O primeiro passo do `make ci-6` é `make x11`, que não precisa de base de dados.
Está neste *gate* porque é aqui que `docs/tecnica/08` o põe: a §14 mede «leituras
cruzadas» pela «suite X-01..X-11 em cada PR», e a §7.3 chama X-11 ao varrimento
dos *logs*. (A §3.7, que define os outros, não o define — `seguranca/lacunas.md`,
L-23.)

Mil chamadas com telefones, NIF, e-mails, texto, tokens, IBAN e referências
passam pelo *logger* em Python e em TypeScript. O alvo exige três coisas, por
esta ordem: que **os padrões vejam os identificadores na entrada** (controlo
positivo — sem ele o zero não dizia nada); que **a saída das duas linguagens
seja igual byte a byte**, e os contadores de rejeição também; e que o
varrimento dê **zero achados** em exactamente 1 030 linhas por linguagem (as
1 000 de canários e 30 de forma, que exercitam as regras que os canários não
tocam).

Três coisas a saber antes de mexer nele:

- **o varrimento conhece a forma da linha.** Um `tenant_id` é um UUID, e cerca
  de 0,6% dos UUID aleatórios têm a forma de um telemóvel angolano lá dentro;
  os campos de forma fechada são conferidos pela forma e não varridos;
- **o padrão do NIF é um parâmetro** (`make x11 X11_NIF='<regex>'`). Nenhum
  documento o define, e sem ele a saída diz que o NIF não é medido por padrão
  próprio;
- **não varre a suite cruzada ponta a ponta**, que é o KAM-066 e não existe. A
  camada SQL deste *gate* não escreve pelo *logger*.

O desenho, os padrões e os limites estão em [`logs.md`](logs.md) §4.2 e §7.

---

### Gate 8 — migrações

Entrou com o KAM-003, que é o primeiro ticket a ter o que este *gate* testa. O
critério é o do `specs/01` §4 — «aplicar e reverter; sem perda em dados de
teste» — e o do próprio ticket: `upgrade → downgrade → upgrade` contra um
PostgreSQL 18.6 vazio, com 0 objectos em `platform` depois do `downgrade`.

**O *gate* levanta o seu próprio PostgreSQL** (`db/gate_bd.py`), e não usa o do
compose de desenvolvimento. Não pode: a *suite* faz `downgrade base`, que apaga
o schema. Quatro coisas tornam isso seguro em vez de assustador:

- a imagem é a do compose, **fixada por *digest***. O critério diz 18.6, e uma
  etiqueta que flutue de *minor* deixava de o provar — há um teste que lê a
  versão do servidor. Desde o KAM-067 a fixação de *digests* é sistemática
  ([`supply-chain.md`](supply-chain.md) §3), e a constante deste *gate* está
  declarada no inventário de imagens;
- os dados vivem em `tmpfs` e o contentor é removido no fim, corra a *suite*
  bem ou mal;
- as palavras-passe são geradas em cada execução e passam pelo ambiente, nunca
  pela linha de comandos;
- **a *suite* recusa-se a correr se a base não se chamar `*_gate8`.** É o trinco
  contra um `.env` errado ou uma variável herdada da *shell*: sem ele, o *gate*
  estava a um esquecimento de apagar a base de desenvolvimento.

No *workflow* o *job* chama `make ci-8` e mais nada. Não há `services:`, de
propósito: a imagem, o *digest* e as credenciais vivem num sítio só, e o *gate*
corre igual na máquina e no *runner* — verificado nos dois sentidos, num
contentor Linux e directamente em Windows, porque o `pg8000` é Python puro.

O que a *suite* cobre, além do ciclo: um caso negativo por `CHECK` e por
`UNIQUE`; os domínios fechados lidos **do catálogo** e não só testados por
inserção (sem isso, um sexto estado acrescentado por engano passava); um
**inventário fechado** de colunas, com tipo, nulidade, omissão e a resposta a
«guarda dados pessoais?»; a **matriz exacta** de privilégios por tabela e por
coluna, as pertenças e os privilégios por omissão — o que cada papel
*consegue*, e não só os atributos que tem; e a guarda de arranque do Fluxo B
contra linhas reais, incluindo um ensaio com a RLS que o KAM-004 vai ligar.

> **Os testes foram provados por mutação — duas vezes, e a primeira estava
> errada.** A *suite* passou à primeira, que é quando menos se sabe se morde.
> Seis mutações minhas foram apanhadas, e isso deu confiança a mais: a revisão
> adversarial fez outras cinco (`GRANT kamba_batch TO kamba_app`, `ON DELETE
> CASCADE`, treze `NOT NULL` retirados, privilégios por omissão, uma coluna de
> contacto em claro) e **as cinco deixavam os 75 testes verdes**. Uma prova por
> mutação vale o que valerem as mutações, e quem escreveu os testes é o pior
> autor possível delas.
>
> A prova está agora em `db/mutacoes.py`: uma alteração por execução, em cópia
> fora do repositório. No KAM-003 eram vinte, e as vinte apanhadas
> ([`ANALISE-03`](analises/ANALISE-03-KAM-003-schema-platform.md) §4). Não faz
> parte do *gate* e corre-se quando se mexe nos testes, na revisão ou no código
> que as mutações alteram.
>
> **A lista cresce com cada ticket de base de dados, e o tempo com ela.** No
> KAM-004 eram 48 alterações; com o KAM-008 passam de 90, e uma execução
> completa em série levou três horas e meia. Por isso corre em paralelo
> (`KAMBA_MUTACOES_PARALELO`, por omissão 8) e aceita um excerto do nome como
> filtro, para se repetirem só as novas; `python db/mutacoes.py --aplicaveis`
> confere em segundos, e sem Docker, que nenhuma mutação antiga deixou de se
> aplicar.
>
> Paralelismo tem um preço, e está pago: com a máquina a esgotar ligações ou à
> espera de um trinco, a *suite* falha por **carga** e não por a mutação ter
> sido apanhada — e isso contava como «apanhada». `SINAIS_DE_CARGA` nomeia
> essas falhas do servidor, cada uma conta como `PROVA INVALIDA`, e o corredor
> sai diferente de zero. **Subir o paralelismo não pode tornar a prova mais
> fácil**; a classificação da saída tem testes próprios
> (`db/tests/test_mutacoes.py`), porque um instrumento que mede testes também
> tem de ser medido.
>
> **E a lista inteira saiu do caminho dos PRs** (KAM-143). No PR correm-se as
> mutações novas, mais `--aplicaveis`; a lista completa corre **uma vez por
> noite**, sobre `main`, repartida por seis *runners* (`--fatia i/6`) na tarefa
> [`mutacoes.yaml`](../.github/workflows/mutacoes.yaml). Não é um *gate*: não
> corre em PRs, não entra nos `needs` do resumo nem no `esperados`, e não
> bloqueia merge nenhum.
>
> **O que se perde, e foi decidido com isto escrito:** deixa de haver garantia
> de que a lista inteira estava verde **no momento do merge**. Uma mutação
> antiga que deixe de ser apanhada por causa de um PR aparece na manhã
> seguinte, não antes do merge, e a tarefa não diz qual PR a quebrou — diz o
> *commit* de `main` em que correu. Decisão do fundador (Outubro 2026), tomada
> enquanto o projecto não está em produção.
>
> **O que não se perde:** nada do que é novo deixa de ser provado antes do
> merge, e uma sobrevivente não fica calada — a tarefa abre um *issue* com a
> ligação para o registo e não abre um segundo enquanto esse estiver aberto. O
> corpo do *issue* é um ficheiro do repositório
> ([`mutacoes-alerta.md`](../.github/mutacoes-alerta.md)), para se rever em
> *diff*, e diz à cabeça que **não é um ticket do backlog**.
>
> O que **não** se fez, e porquê: reutilizar uma base de dados entre mutações
> poupava mais tempo do que tudo o resto — a maior parte dos minutos é a
> levantar e a derrubar PostgreSQL —, mas uma base que uma mutação deixe suja
> faz a seguinte falhar, e uma falha herdada conta como «apanhada». Seria
> trocar tempo por exactamente o defeito que esta prova existe para apanhar.

**O trinco protege a base, não a instância.** Os papéis de base de dados são
globais à instância: o `bootstrap` redefine-lhes a palavra-passe, e correr o
*gate* contra uma instância que outros serviços usam trocava-lhes as
credenciais. Por isso o modo `--bd-existente` exige as três palavras-passe dadas
no ambiente, e só é seguro contra uma instância descartável. O caminho por
omissão — o que o CI usa — cria a sua.

**A *suite* tem limite de tempo, e um teste saltado falha.** Um *gate* pendurado
é pior do que um vermelho; aconteceu uma vez, por um bloqueio entre ligações de
um teste, e durou dez minutos. E o `python -m unittest` sai com 0 quando todos
os testes são saltados — pelo que o *gate* usa um corredor próprio
(`db/correr_suite.py`) em que saltar é falhar.

**O que este *gate* não mede.** O código de `db/` está excluído da medição do
*gate* 4 (`ci/thresholds.yaml`): é exercitado aqui, contra uma base real, e
ninguém mede hoje que percentagem dele estes testes tocam. É limitação dita, não
dispensa.

#### A segunda metade: identidade de contacto (KAM-008)

O `make ci-8` corre **catorze** *suites*, cada uma com a sua base descartável:
`tests` (as migrações, acima), **`tests_identidade`** (esta secção),
**`tests_eventos`** e **`tests_eventos_carga`** (a secção seguinte, KAM-005),
`tests_eventos_consumo` (KAM-006), `tests_auditoria_carga` (KAM-012),
**`tests_ten`** (KAM-009), **`tests_entrada`** e **`tests_entrada_carga`**
(KAM-013), **`tests_chr`** (KAM-014), **`tests_outbound`** (KAM-015),
**`tests_handoff`** (KAM-019), **`tests_media`** (KAM-020) e **`tests_modos`**
(KAM-018, a última secção).
A de identidade entrou com o KAM-008. Esta põe o módulo de identidade — TypeScript, em
`packages/core-ts/src/identity/` — a correr contra o PostgreSQL com o papel
`kamba_identity` verdadeiro e a RLS ligada. O desenho está em
[`identidade.md`](identidade.md); aqui fica o que o *gate* mede.

- **Os testes em Node correm uma vez**, por `db/tests_identidade/`: os três
  ficheiros unitários de identidade (os mesmos do *gate* 4) e
  `tests_bd/identity.bd.test.ts`, que só corre aqui. Um teste saltado falha, e a
  lista dos grupos e dos testes que dão a letra de cada critério está fechada
  na *suite* — um grupo que desapareça não passa por haver menos testes.
- **Os canários procuram-se de fora do processo que os semeou.** 1 000 contactos
  com BSUID e telefone canário; depois, o `pg_dump` da base inteira, o registo do
  servidor com `log_statement = 'all'` (instruções **e** parâmetros) e a saída
  dos testes. Cada canário procura-se **em claro e em hexadecimal** — é assim
  que o `pg_dump` e o registo escrevem um `bytea`, e um BSUID guardado em claro
  numa coluna `bytea` não aparecia como texto. A procura tem controlo positivo:
  um valor que **tem** de lá estar, e um canário posto de propósito que tem de
  ser encontrado.
- **A cobertura de `src/identity/` mede-se aqui, por ficheiro**, contra o
  limiar do estrato `critico` (90%), lido de `ci/thresholds.yaml`.
  `contactos.ts` está excluído da medição do *gate* 4 por essa razão, e só por
  essa: sem base de dados, o serviço não corre.

#### A terceira e a quarta: o publicador de eventos (KAM-005)

O KAM-005 acrescenta duas *suites*, e são as primeiras que precisam de **mais do
que uma base de dados**: o publicador entrega a filas BullMQ, e as garantias de
entrega do BullMQ estão `NÃO VERIFICADO` (`tecnica/evidencia/E4` §2.10). O
recuo, a republicação depois de um `kill -9`, a eleição de líder e o atraso sob
carga não se provam contra uma fila em memória — provar contra uma fila falsa era
provar o desenho do teste.

Por isso, para estas duas, o `db/gate_bd.py` levanta **uma rede Docker própria**
com o PostgreSQL e um Valkey 9.1.2 (`--appendonly yes --appendfsync everysec`, a
configuração que o desenho assume), os dois em `tmpfs` e apagados no fim. O
digest do Valkey está em `ci/supply-chain/imagens.yaml` e a constante
`IMAGEM_FILA` de `db/gate_bd.py` está declarada em `fontes_adicionais`, pelo que
o *gate* 11 falha se os dois divergirem.

Três detalhes que são decisões, e não acidentes:

- **O contentor da fila não leva `--rm`.** O critério 4 **pára** a fila (`docker
  stop`) e volta a arrancá-la; com `--rm`, o `stop` remove o contentor e não há
  `start` depois. E a porta publicada é **fixa**, escolhida pelo processo: uma
  porta efémera muda no `docker start`, e a *suite* ficava a falar com a antiga.
- **O `kill -9` é um `kill -9`.** O publicador corre como processo
  (`packages/core-ts/tests_bd/publicador_runner.ts`), parado de propósito entre
  o `add` e o `COMMIT`, e o sinal vai ao **contentor**: matar o `docker run`
  deixava o Node de dentro a publicar com o *lock* consultivo na mão.
- **A carga está em *suite* própria (`tests_eventos_carga`), e é por custo.** São
  cinco minutos — o número é do critério 8 — e uma *suite* custa isso **por cada
  mutação** que a escolha em `db/mutacoes.py`. Dentro de `tests_eventos`, cada
  mutação do publicador passava a custar oito minutos; separada, as do publicador
  correm em três e a carga corre uma vez. Não é opcional: o `make ci-8` corre-a.

O que estas duas medem, e o que **não** medem, está na secção de verificação do
bloco do KAM-005 em `../specs/EPIC-01_Fundacoes_Dados.md`. **Três caixas desse
bloco fecharam na primeira execução destas *suites* aqui**: no anfitrião de
desenvolvimento (Windows) a da fila parada não reproduzia e o p95 media 6,0 s,
acima do limiar *proposto* de 1 s; em `ubuntu-latest` a fila parada passa e o p95
é **0,195 s** ([execução 38881054356](https://github.com/albinoJimy/kamba-plataforma/actions/runs/38881054356)). Fica uma vazia, a dos dois revisores. O
desenho está em [`eventos.md`](eventos.md).

**Fica no *job* do *gate* 8, e não num *gate* novo.** Precisa do mesmo
PostgreSQL e das mesmas migrações, e não acrescenta um *job* aos `needs` do
resumo. O *gate* 5 («integração: serviços contra Postgres e Redis reais»)
continua reservado: quando um serviço tiver integração para correr, é para lá
que isto se muda — decisão registada no bloco do KAM-008.

**Onde isto deixa de correr igual na máquina e no *runner*.** No *runner* há
`node` no `PATH`. Numa máquina sem ele, a *suite* corre a imagem oficial do Node
**na rede do contentor do PostgreSQL** (`--network container:…`), sem publicar
mais nada. Nos dois casos o `pg_dump` e o registo pedem-se ao contentor, cujo
nome o `gate_bd.py` passa em `KAMBA_GATE_CONTENTOR`; com `--bd-existente` e sem
essa variável, a *suite* **falha** em vez de saltar o *dump*.

**O Alembic deixou de ser um processo por chamada nos testes.** A *suite* `tests`
chamava `python -m alembic` dezenas de vezes; medido em Windows, oito a nove
segundos por chamada, e a *suite* a passar dos dez minutos com as migrações do
KAM-008. Agora os testes chamam a mesma classe da linha de comandos
(`alembic.config.CommandLine`) dentro do processo, e só se chama de todo quando
a base não está na revisão de cabeça. O ciclo `upgrade → downgrade → upgrade`
do critério 1 do KAM-003 continua a correr o executável, num processo novo, e há
um teste que confere que as duas vias dizem o mesmo.

#### A sétima: o consumo de limites (KAM-009)

`tests_ten` prova a **função** `platform.ten_consumir` da revisão `0007` — a
regra única que a biblioteca em TypeScript e o lado Python chamam, em vez de
cada um ter a sua aritmética de limites. É *suite* própria pela mesma razão
que a carga de eventos e a da cadeia de auditoria: o critério 3 pede **mil
chamadas paralelas**, e isso custa — dentro de `tests`, cada mutação da `0007`
pagava esse custo somado ao da *suite* inteira.

O que só aqui se mede:

- **as mil paralelas, a sério.** Mil chamadas de 1 unidade contra um tecto de
  100, em 32 ligações concorrentes com `commit`: **100 aceites, 900 negadas,
  contador final 100**. Um ciclo sequencial dava os mesmos cem e não provava
  nada da serialização no bloqueio da linha nem da reavaliação do `WHERE` do
  `ON CONFLICT DO UPDATE` sobre o valor já actualizado;
- **a chave que uma recusa não pode gastar.** A função regista a chave de
  idempotência **antes** de contar, e desfá-la com o *rollback* de uma
  subtransacção — não com um `DELETE`, que obrigaria a dar `DELETE` à
  aplicação. Os dois caminhos de recusa têm teste, e as 900 negadas acima
  deixam o livro com **100** linhas e não com mil;
- **a fronteira do mês com relógio fixo.** O `p_agora` existe na assinatura
  para isto. Os dois instantes do critério, e — porque os dois passariam com a
  função escrita em UTC — um instante que cai em **meses diferentes** nos dois
  fusos (`2026-11-30T23:30:00Z` é Dezembro em `Africa/Luanda`). E a resposta
  não pode depender do `TimeZone` da sessão;
- **o isolamento da função, que o *gate* 6 não prova.** O catálogo do *gate* 6
  descobre `tenant_usage` e `usage_ledger` sozinho e prova-lhes a política
  `tenant_iso`. Isso prova a política. Uma função SQL contorna a RLS inteira
  com um `SECURITY DEFINER`, e o isolamento passaria a depender do `p_tenant`
  que o chamador escolhe — que é o que o ADR-015 recusa. Aqui prova-se o facto
  estrutural (`prosecdef` falso) **e** o comportamento: com o contexto de B e
  o `p_tenant` de A, a função não vê o tecto de A, nega, e não escreve nada.

E o que não está no bloco do ticket e é decisão da revisão: o tecto vem de
`entitlements` e é o **mínimo** entre os módulos activos que declaram a chave;
sem linha activa que a declare, **nega** — e nega antes de olhar para o
`p_limite`, porque um argumento não substitui uma linha; o `p_limite` de quem
chama só **desce**; e uma quantidade que não seja positiva **levanta**.

---


#### A nona e a décima: a entrada de canal (KAM-013)

`tests_entrada` e `tests_entrada_carga` são as *suites* do webhook da Meta, e a
diferença face a todas as outras é **o que elas lançam**: os processos de
produção. `services/gwy/src/server.ts` e
`services/worker-canal/src/entrada.ts`, sem uma linha de código de teste pelo
meio. As outras *suites* lançam programas de ensaio escritos para elas
(`publicador_runner.ts`); aqui não se pode, porque o que há para provar é o
comportamento de um servidor HTTP a falar com uma fila a sério:

| O que só aqui se prova | Como |
|---|---|
| «o 200 só é devolvido depois de o *job* estar enfileirado» | A leitura da fila é imediatamente depois da resposta, sem espera nenhuma |
| «com Redis indisponível o GWY responde 503 e nunca 200» | `docker stop --timeout 0` no contentor da fila, cinco pedidos, e o conjunto de códigos tem de ser exactamente `{503}`. Depois `start`, e o **mesmo** processo volta a aceitar sem ser reiniciado |
| «a mesma mensagem em dois corpos distintos produz 1 linha» | Dois corpos com o mesmo `wamid` e `sha256` diferente: **dois** *jobs* na fila e **uma** linha em `inbound_events` |
| «JSON inválido: 200 e quarentena; nunca 5xx» | Um corpo que não faz `parse`, e a linha de `unrouted_events` com `motivo = json_invalido` e o corpo em base64 |
| Os privilégios da revisão `0008` bastam e não sobram | Com o papel `kamba_app` verdadeiro: o `RETURNING id` funciona, o `payload` da quarentena é recusado, `count(*)` é recusado, e nenhuma das duas tabelas aceita `DELETE` |

**A assinatura calcula-se em Python**, com `hmac`/`hashlib` da biblioteca
padrão, e não com o módulo TypeScript que está a ser testado. É uma segunda
implementação independente, e por isso o que se mede é **interoperabilidade** e
não auto-consistência — a diferença entre «o nosso código concorda consigo» e
«o nosso código concorda com quem calcula HMAC-SHA256 por outro caminho».

**Os domínios comparam-se com três fontes:** o `CHECK` que o PostgreSQL tem, o
dicionário exportado (`canon/dicionario.yaml`) e a lista do módulo TypeScript,
lida do ficheiro. Duas fontes a concordar é uma cópia; três é um contrato.

**A carga está em *suite* própria, e é por custo**, como a de eventos: 200
pedidos/s durante 60 s — 50 corpos de mensagem e 150 de estado por segundo, que
é a leitura de «3 estados por mensagem» —, com p99 < 500 ms, mediana ≤ 250 ms e
menos de 1% acima de 1 s. Uma *suite* paga esse minuto por cada mutação que a
escolha.

**Os processos arrancam por classe de teste e não por método**, e isso é uma
medição: com um `docker run` por método a *suite* levava 763 s. Os dois
processos não têm estado próprio — está na base e na fila, que se limpam entre
testes.


#### A décima primeira: o CHR (KAM-014)

`tests_chr` põe o módulo do CHR — TypeScript, em
`packages/core-ts/src/chr/` — a correr contra o PostgreSQL com os **três papéis
verdadeiros**: `kamba_resolver`, `kamba_identity` e `kamba_app`. É a primeira
*suite* que abre três ligações com três papéis, e isso não é arrumação: a
resposta à pergunta do CHR **depende do papel**, e é essa a propriedade que só
aqui se prova. O desenho está em [`chr.md`](chr.md).

| O que só aqui se prova | Como |
|---|---|
| «o `phone_number_id` de A nunca devolve o contexto de B» | Dois tenants, dois canais, o resolvedor **sem contexto de tenant**. A propriedade vem da `tenant_channels_phone_number_id_uq` e da política `resolver_leitura`, não do código: não há duas linhas onde escolher |
| «`kamba_app` não consegue responder à pergunta» | A mesma consulta com os dois papéis: `kamba_app` sem contexto devolve **zero linhas** (que o CHR leria como «canal desconhecido») e `kamba_resolver` devolve uma. É o que torna o papel necessário e não conveniente |
| «o `plano` está entre as colunas que o resolvedor lê» | Foi a revisão `0009` que lho concedeu; sem ele o `ChannelContext` do critério 1 ficava a sete campos |
| «uma conversa de B não se vê com o contexto de A» | O CHR abre a conversa de B; com `comTenant(A)`, a contagem é zero. É a RLS `FORCE` da `0009` |
| a convergência de identidade, e **o seu limite** | A sequência medida: só-telefone cria P, só-BSUID cria A (nada os liga), a primeira que traz os dois funde no mais antigo com `contact.merged` **uma** vez em dez repetições, e daí em diante os dois sentidos devolvem P. O critério 4 não se cumpre à letra, e é esta medição que o mostra |
| o gancho de fusão, nos dois casos | Sem colisão reaponta; com colisão no mesmo canal dobra os tempos e **não** viola a `UNIQUE`. E se o gancho lançar, a fusão inteira é desfeita — com a fotografia das conversas igual antes e depois |
| «repetição do mesmo `wamid` não cria 2 conversas» | O mesmo evento duas vezes: **uma** linha em `conversations`, com o mesmo `conversation_id` nos dois *jobs* |
| a guarda do ADR-011 no arranque | Uma linha de Fluxo B de cada um dos três tipos, e o arranque recusado nas três; com `kamba_app`, a guarda **recusa-se a correr** (`GuardaCega`) em vez de contar zero; com `kamba_batch`, que contorna a RLS, corre |
| «`kamba_app` não altera o `mode`» | O privilégio **não existe** (revisão `0009`): as transições são KAM-018. Provar pela ausência de privilégio é mais forte do que por política |
| a latência do critério 8 | p95 de 40 execuções, com e sem *cache*, impresso no registo do *gate*. O que estes números valem está em [`chr.md`](chr.md) §8 |

E a *suite* mede a **cobertura de `src/chr/` por ficheiro**, contra o limiar do
estrato `critico` lido de `ci/thresholds.yaml` — porque o *gate* 4 não tem base
de dados e o CHR sem base só corre as recusas à entrada. É a mesma solução do
`tests_identidade`, e pela mesma razão.

**Não precisa de fila**, ao contrário das do KAM-013: a porta do AGR é uma
interface, e o que se faz com o *job* é KAM-025. O `chr/fila.ts` — a casca sobre
o BullMQ — fica por isso fora da medição, declarado nos `excluidos` do
`ci/thresholds.yaml`.

#### A décima segunda: a saída de canal (KAM-015)

`tests_outbound` põe o módulo de saída — TypeScript, em
`packages/core-ts/src/outbound/` — a correr contra o PostgreSQL **e** contra o
servidor Graph falso do KAM-024. É a primeira *suite* que junta os dois, e a
razão é a letra do critério 2: «2 chamadas com a mesma `idempotency_key`
produzem **1 chamada à API** (servidor falso conta) e **1 linha** em
`outbound_messages`». Uma base prova a linha e não a chamada; um servidor falso
prova a chamada e não a linha. O desenho está em [`outbound.md`](outbound.md).

| O que só aqui se prova | Como |
|---|---|
| «1 chamada à API e 1 linha» | A mesma chave duas vezes, com o `GraphFalso` a contar: **uma** chamada e **uma** linha. O `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING` devolve vazio na segunda, e é disso — e não de uma verificação prévia — que o adapter conclui «não chamar» |
| «a unicidade é **por tenant**» | A mesma chave em dois *tenants* dá **duas** linhas. É a primeira divergência da emenda 1.21 face ao `../docs/tecnica/01` §8.4: com unicidade global, o segundo *tenant* era deduplicado em silêncio |
| «estados monótonos» sob concorrência | Dois `statuses` da mesma mensagem em **duas ligações**, em paralelo: o estado final é o maior dos dois e o custo conta **uma** vez. A monotonia está no predicado (`state = ANY($4)`), e é a base que serializa — com uma ligação só, o teste provava que o JavaScript é sequencial |
| a RLS sobre as duas tabelas novas | Com o contexto de A, as linhas de B não aparecem **e** uma escrita na linha de B não acontece. É o X-03 dos *Testes Requeridos*, e com `FORCE` vale até para o dono |
| o custo por *tenant* sai da **tabela** | O `SQL_CUSTO_DO_TENANT` soma o `pricing` das entregues, e o de A não inclui o de B. É isto que substitui a etiqueta `{tenant}` que as bibliotecas de métricas recusam — ver [`outbound.md`](outbound.md) §5 |
| o bloqueio de template recategorizado | Recategorizar para `marketing` bloqueia e é **idempotente** (a Meta reenvia o *webhook*), preservando o primeiro instante |
| o `downgrade` da `0010` | Em `db/tests/test_saida_schema.py`, na *suite* `tests`: vazio desce e sobe; com linhas e sem `KAMBA_DOWNGRADE_0010_COPIA` **recusa** e deixa o `FORCE` intacto; com a variável escreve a cópia das catorze colunas de cada envio e das dez de cada template, **com o `pricing`** |
| **a fronteira de mes e a de `Africa/Luanda`** (KAM-023; desenho em [`metering.md`](metering.md)) | Dois instantes a **uma hora** de distancia — `22:30Z` e `23:30Z` de 31 de Outubro — caem em meses **diferentes** em Luanda e no mesmo mes em UTC. O contador reinicia no segundo e nao no primeiro, e o fuso vem de `platform.ten_periodo` (revisao `0007`), onde ele vive num sitio so. Nenhuma base falsa pode fazer esta asserção |
| **o flanco do aviso sob concorrencia** (KAM-023) | Dois incrementos em paralelo na travessia dos 800, em **duas ligacoes**: o contador sobe dois e sai **um** aviso. E o `FOR UPDATE` do `SQL_CONTAR` que faz o segundo processo reler o que o primeiro escreveu — com uma leitura previa, os dois liam 799 e os dois concluiam «eu atravessei» |
| **o contador e idempotente por `wamid`** (KAM-023) | Tres `delivered` do mesmo `wamid`, com o adapter e o contador ligados: contador **+1**. A propriedade e da base — tres chegadas produzem **uma** transicao — e o adapter di-lo a quem conta pelo campo `entregou` |
| **os contadores de A nao se leem nem escrevem com o contexto de B** (KAM-023) | Nos dois sentidos, com a metade positiva primeiro. E o X-03 dos *Testes Requeridos* do KAM-023, aplicado a `tenant_channels` |
| **a reconciliacao le o `pricing` `jsonb` e nao erra o mes** (KAM-023) | Mede as **duas** divergencias que o criterio 7 admite (contagem contra contagem, facturavel contra facturavel) e uma entrega de outro mes **nao entra**: o periodo exprime-se pela funcao do fuso e nao por fronteiras em instantes, que vinham em UTC |
| **a marca de restricao e o `channel.updated`** (KAM-023, revisao `0013`) | A marca cai na coluna, o codigo de erro entra no conjunto **uma** vez, e o evento aparece no `events_outbox` — que e o que o publicador le. Uma segunda marca **nao** emite outro: um evento por mensagem falhada e o contrario de um alerta, e quem o decide e o `antes` sob `FOR UPDATE`. Duas marcas em paralelo, em duas ligacoes: **um** evento. E o X-03 sobre as duas colunas novas, nos dois sentidos |
| **a idempotencia da transicao de qualidade e da base** (KAM-021, revisao `0014`; desenho em [`qualidade.md`](qualidade.md)) | O mesmo `event_key` em **duas ligacoes**, em paralelo: **uma** linha em `channel_quality_log`, **uma** transicao, **um** `channel.updated`. Quem decide e o indice unico, e a chave e composta com o `tenant_id` — a mesma chave em dois *tenants* da **duas** linhas, pela razao da emenda 1.21. Em serie, a segunda chamada nem chega a tocar no estado |
| **o `UPDATE` no registo de qualidade nao existe** (KAM-021) | E o oposto de um teste de politica: a *suite* afirma o **`42501`** num `UPDATE` e noutro `DELETE` feitos como `kamba_app`, e afirma que o `SELECT` e o `INSERT` **funcionam** — sem essa metade positiva, uma concessao em falta por inteiro passava as duas negativas. Um teste do lado do codigo prova o que o codigo faz hoje; este prova o que nenhum codigo pode fazer |
| **cada ticket levanta apenas o motivo que poe** (KAM-021) | Um canal `restrito` com `motivo_restricao = 'payment_method'` **nao** se repoe com um `GREEN`: o predicado esta no `SQL_REPOR`. E o inverso — um canal `ativo` ja marcado por falta de pagamento que vai a `RED` fica `restrito` **com a marca original**, pelo `COALESCE`: o motivo que o KAM-115 conta ao dono e a causa e nao a consequencia |
| **a medicao do escalao e uma juncao, um `DISTINCT` e um intervalo movel** (KAM-021) | `count(DISTINCT contact_id)` sobre `outbound_messages` ligada a `tenant_channels` pelo numero, com `kind <> 'service'`, `state <> 'queued'` e **24 h moveis**: uma mensagem de ha 25 h cai fora, hora a hora, e nao «no dia anterior». E por isso que esta consulta **nao** chama a `platform.ten_periodo` — o mes do *free tier* reinicia num fuso, este vai andando. E a letra do criterio: 200 unicos com `TIER_250` dao `0,8` e avisam |
| **o criterio 9 de ponta a ponta: a saida honra o `restrito`** (KAM-021) | A `Saida` do KAM-015, com a porta de estado ligada a uma consulta real, recusa com `STATE_REFUSED` um template num canal que **a propria bateria** acabou de restringir — e deixa sair uma `service` dentro da janela, porque a linha `restrito` da matriz tem `responder_sessao: true` e um `if (estado === "restrito")` cortava-a. E o unico sitio onde os dois modulos se encontram sobre a mesma linha da base. **Com um teste de controlo**, sem o qual nao se distinguia uma recusa de um envio que nunca podia sair |
| **a prova de consentimento e idempotente pela propria prova** (KAM-022, revisao `0015`; desenho em [`consentimento.md`](consentimento.md)) | O mesmo botao em **duas ligacoes**, em paralelo: **uma** linha em `consent_event` e **um** `consent.recorded`. A unicidade e `(tenant_id, contact_id, purpose, evidence_hash)` e o que a torna suficiente e a composicao do resumo — o `wamid` e a hora sao **da Meta**, pelo que uma reentrega do mesmo *webhook* da o mesmo valor. Com a nossa hora, duas entregas davam duas linhas |
| **a vista `consent_actual` respeita a RLS de quem a consulta** (KAM-022) | **A primeira vista do esquema**, e o `security_invoker = true` e o que a faz correr como quem pergunta — sem ele, uma vista corre com os privilegios do **dono** e o isolamento passa a depender do `FORCE`, numa relacao onde ninguem iria procurar. Mede-se pelo caminho do modulo: o estado de B nao aparece com o contexto de A. O `verificar_vistas` do *gate* 6 exige-o a qualquer vista **sem lista de excepcoes**, e existe desde o KAM-004 sem nunca ter tido nada para ver |
| **o *append-only* da prova e um privilegio** (KAM-022) | **`42501`** num `UPDATE` e num `DELETE` em `consent_event`, e num `INSERT` em `consent_texts` — com a metade positiva a provar que o `SELECT` e o `INSERT` na prova funcionam. E o criterio 6 escrito em privilegios: uma prova de consentimento que se possa corrigir nao e prova, e quem publica uma versao do texto e operacao e nao o caminho que serve clientes |
| **a contagem de avisos sai do prefixo da chave de idempotencia** (KAM-022) | «Repete o aviso ate 2 vezes e depois encaminha a `humano`» precisa de uma contagem, e **nao ha coluna para ela no esquema**. O aviso sai com `aviso:{conversation_id}:{n}` e a contagem e um `count(*)` com prefixo sobre `outbound_messages`: a mesma chave que impede o aviso de sair duas vezes diz quantas vezes saiu. So um planeador prova que ela conta isso e nada mais, e resolve-se pelo indice `(tenant_id, idempotency_key)` da `0010` |
| **a versao vigente do aviso e a que ja passou** (KAM-022) | Uma versao publicada com `vigente_desde` no futuro **nao vigora**, e e assim que um texto novo se publica antes de valer; subir a versao poe quem ja tinha consentido em `desactualizado` e obriga a re-avisar (criterio 7). E **sem versao nenhuma o gate falha fechada** — a `consent_texts` nasce vazia porque o texto esta a confirmar por parecer, e a loja fica muda em vez de tratar dados sem ter mostrado o aviso |
| **a idempotencia do onboarding sao duas unicidades, e «1 canal» sai de «1 linha»** (KAM-016, revisao `0017`; desenho em [`onboarding-canal.md`](onboarding-canal.md)) | O mesmo `(tenant_id, waba_id)` em **duas ligacoes**, em paralelo: **uma** linha em `channel_onboarding`. O `ON CONFLICT DO NOTHING` **sem alvo** e que decide, e e sem alvo de proposito — ha **duas** chaves (`(tenant_id, code_hash)` e `(tenant_id, waba_id)`) e o criterio 2 quer as duas a deduplicar; com um alvo nomeado, a repeticao do mesmo *code* noutro WABA levantava `23505` em vez de devolver a linha que la estava. E «1 canal» nao e uma propriedade do codigo: o canal cria-se na **mesma transaccao** que escreve o `channel_id` nessa linha, pelo que duas chamadas concorrentes nao podem ter as duas uma linha, logo nao podem ter as duas um canal. As duas chaves levam o `tenant_id`, pela razao da emenda 1.21 |
| **o 409 do `phone_number_id` e a unicidade a morder, e a transaccao a reverter** (KAM-016) | A `tenant_channels_phone_number_id_uq` da `0001` e **global** — sem `tenant_id` na chave — e e ela que levanta o `23505`; **nao ha `SELECT` antes do `INSERT`**, porque entre os dois cabe outro processo. O «nao altera nada» do criterio 4 nao se mede no codigo: mede-se na base **depois do `ROLLBACK`**, e a bateria conta os canais antes e depois, le o `tenant_id` da linha do dono e exige que a tentativa do outro *tenant* nao exista. O registo de auditoria escreve-se **a seguir**, numa transaccao propria — e **nao e o `audit_log`**: o dominio de `action` tem sete valores no `CHECK` da `0006`, fundida, e o *gate* 3b compara-o com o dicionario nos dois sentidos |
| **os 81 pares de transicao contra o `CHECK` e contra o *compare-and-set*** (KAM-016) | A matriz tem **dezesseis** arestas e o diagrama do `../docs/tecnica/01` §13.1 desenha onze: a diferenca e «de qualquer fase nao terminal vai-se a `falhado`», que o criterio 7 obriga — o passo 4 corre em `es_concluido` e uma saga cuja compensacao nao tem onde se registar nao compensa. A *suite* percorre os **dezesseis** pares legais contra um PostgreSQL real, poe a linha na fase de partida (o que exercita tambem o `channel_onboarding_canal_ck`, que exige `channel_id` nas seis fases do meio) e exige que a **segunda** passagem devolva **zero linhas** — e o `WHERE fase = <esperada>` do `SQL_TRANSITAR` que serializa duas transicoes concorrentes. O `desligado` do diagrama **nao** entra no dominio: e estado de `tenant_channels` e nao fase de onboarding |
| **a compensacao mede-se em tres sitios, e nao na coluna** (KAM-016) | Uma falha injectada no passo 4 — a subscricao, o que o criterio 7 nomeia — tem de deixar `0` linhas em `tenant_channels`, `0` segredos no cofre e `0` subscricoes **no WABA**, e o terceiro le-se no `GraphFalso` do KAM-024 e em mais sitio nenhum: e a razao de esta *suite* ser a unica do *gate* 8 que o monta. A coluna `recursos_criados` fica `[]`, mas uma lista vazia so prova que a lista esta vazia. A compensacao percorre a lista ao **contrario**, e isso nao e arbitrario: anular a subscricao exige o *token* em claro, pelo que revogar o *token* primeiro deixava a subscricao sem forma de ser desfeita. E **uma compensacao que falha nao esvazia a lista**: quem retomar tem de saber o que falta desfazer |
| **o *token* de cliente e o PIN nao estao em coluna nenhuma** (KAM-016) | O *dump grep* do criterio 3 e **literal**: a bateria junta `tenant_channels` e `channel_onboarding` em texto (`c.*::text`) e procura o *token*, o *code* e o PIN. O que esta na base e a referencia opaca; o que esta no cofre e o **criptograma**, e a bateria decifra-o com a KEK para provar que e o mesmo *token* — a cifra e nossa, com DEK **derivada** por *tenant* e `kid` dentro do criptograma, e e isso que a entrada `kek_token_cliente` do inventario existe para fazer. O `code` entra em `sha256` e nunca em claro: ele e trocavel por um *token*, logo e um segredo com o valor do *token* |
| **o contador `es_onboardings_7d` atravessa *tenants*, e so com `BYPASSRLS`** (KAM-016) | O tecto de dez clientes por sete dias e da **nossa app** perante a Meta e nao de uma loja (CONFIRMADO, `E1` §3), pelo que a contagem **nao leva `tenant_id`** — e com a politica `tenant_iso` o `kamba_app` contaria sempre as suas e contaria mal, o que e pior do que nao contar porque parece certo. Mede-se com dois *tenants*: duas linhas, `+2`. E mede-se a fronteira — oito dias atras nao conta, sete dias menos um minuto conta — e o lado **conservador**: o `abandonado` e o `falhado` contam, porque se um *popup* fechado consome um lugar na contagem **deles** e NAO VERIFICADO, e contar de menos custa um cliente |
| **o `kamba_app` le o onboarding e nao escreve nada** (KAM-016) | **`42501`** num `INSERT`, num `UPDATE` e num `DELETE` em `channel_onboarding` feitos como `kamba_app`, com a metade positiva a provar que o `SELECT` funciona — e e a **primeira** tabela deste esquema em que aquele papel le e nao escreve: a `message_templates` le e altera, a `events_dlq` escreve e nao le. A razao e que o onboarding e **provisionamento** e quem provisiona e o `kamba_batch` (dicionario §3.2), e as tres consequencias estao medidas: a contagem atravessa *tenants*, a compensacao **apaga** uma linha de `tenant_channels` (e `kamba_app` nao tem `DELETE` desde a `0001`), e o que protege a escrita passa a ser a falta de privilegio |

E a *suite* mede a **cobertura de `src/outbound/` por ficheiro**, contra o
limiar do estrato `restante` lido de `ci/thresholds.yaml` — e **não** o do
`critico`, por uma razão escrita na própria *suite*: o DoD do KAM-015 diz
«cobertura ≥ limiar» sem número, e alterar `ci/thresholds.yaml` pede dois
revisores. Não se alarga um ficheiro de limiares para marcar uma caixa que não
pede o número.

**Leva o `tools/meta-sim` montado**, que é a diferença face ao `tests_chr`: sem
a pasta de módulos do simulador o `import` do `GraphFalso` falha com
`ERR_MODULE_NOT_FOUND`. O `@kamba/meta-sim` é por isso uma `devDependency` do
`@kamba/core-ts`, o que fecha um **ciclo** — aceitável porque é de
desenvolvimento nos dois sentidos, e o oráculo do `pnpm list --prod` prova que
o fecho de produção de ambos é zero.

**A cobertura de `src/metering/` (KAM-023), de `src/qualidade/` (KAM-021) e de
`src/consentimento/` (KAM-022) nao se mede aqui**, e e deliberado: o
filtro da medicao e `/src/outbound/`, e o contador do *free tier* vive noutra
pasta. Mede-se no *gate* 4, onde a bateria de unidade dele corre — e essa
bateria **tambem** entra na lista desta *suite*, nao pela cobertura mas pela
**prova por mutacao**: as mutacoes em `custo.ts` e em `metricas.ts` so por ela
sao apanhadas, e declarar uma mutacao sem o seu oraculo era declarar prova que
nao existe.

**O `cliente.ts` fica fora da medição**, como o `chr/fila.ts`: a parte dele que
pode errar em silêncio — a forma do corpo, a leitura do `error.code`, o
`Retry-After` — tem bateria própria no *gate* 4 com o `fetch` por porta, e esta
*suite* usa o `GraphFalso` por porta e não passa pela chamada de rede. Medi-lo
aqui dava-lhe uma cobertura que diria só que o ensaio não abre socket.

#### A décima terceira: a passagem a humano (KAM-019)

`tests_handoff` põe o módulo da passagem — TypeScript, em
`packages/core-ts/src/hnd/` — a correr contra o PostgreSQL com a RLS ligada. O
desenho está em [`hnd.md`](hnd.md). **Os ordinais destes títulos correm um à
frente da lista desde o `tests_entrada`**, e esta secção segue a sequência deles
em vez de a corrigir a meio de outro ticket: pela lista, é a **décima segunda**.
O desvio está declarado em
[`dividas-documentais.md`](dividas-documentais.md).

A *suite* é de uma classe diferente das onze anteriores, e vale dizer qual: ela
**não corre os testes, corre a saída deles**. As cinco baterias do *gate* 4 e o
ensaio de base produzem TAP, e as cinco asserções Python lêem esse TAP —
confirmam que cada grupo apareceu, que cada teste obrigatório passou pelo nome,
e que a cobertura de cada um dos **dez** ficheiros de `src/hnd/` está acima do
limiar. É a mesma forma do `tests_outbound`, e a razão é a mesma: um *gate* que
conte testes não nota que um desapareceu.

**O que só esta *suite* prova**, porque pede um PostgreSQL verdadeiro:

- **A idempotência é da base e não do código.** Cinco `openHandoff`
  concorrentes, em **duas ligações**, deixam uma linha e fazem uma chamada ao
  provedor — e quem o garante é a chave primária `(handoff_id)` com o
  `handoff_id` **derivado** de `hash(thread_id, ordinal)`. O mesmo para a conta:
  `(tenant_id, provedor)`.
- **A mesma conta do provedor em dois *tenants* é recusada.** A
  `handoff_accounts_conta_uq UNIQUE (provedor, account_id)` devolve `23505`, e é
  o lado do isolamento que nenhuma verificação em código apanharia.
- **O `close` duplicado é *no-op* pela base.** Dois `close` em paralelo em duas
  ligações: o `WHERE status = ANY($3)` faz o segundo não casar, e as métricas
  dos dois somadas contam **uma** passagem fechada.
- **O X-03 sobre as duas tabelas novas**, incluindo a escrita: com `FORCE`, nem
  como dono da tabela se escreve na linha de outro *tenant*.
- **Uma passagem `degraded` conta no SLA.** Está tão longe de ser atendida como
  uma à espera, e esconder-lhe o atraso era mostrar um painel verde no pior caso.

A cobertura de `src/hnd/` mede-se aqui, contra o estrato **`restante`** e não o
`critico`, pela mesma razão do KAM-015: o DoD não dá número e alterar
`ci/thresholds.yaml` pede dois revisores.

**Uma bateria que o *gate* não corre é uma bateria que apodrece em silêncio**, e
isso aconteceu neste ticket: o `hnd.resposta.test.ts` nasceu, passou, e a
*suite* ficou verde **sem o correr** — o `node --test` apanhava-o pelo *glob*
`tests/hnd.*.test.ts`, e a lista de ficheiros que o CI usa, que é esta, não o
tinha. O `resposta.ts` também não estava na lista de módulos medidos, pelo que
nem a cobertura o denunciou. É por isso que as duas listas são explícitas e não
um *glob*: um *glob* nunca falha por esquecimento, e é isso que o torna pior.

#### A décima quarta: a mídia recebida (KAM-020)

`tests_media` põe o módulo da mídia — TypeScript, em
`packages/core-ts/src/med/` — a correr contra o PostgreSQL com a RLS ligada. O
desenho está em [`media.md`](media.md). Pelos ordinais destes títulos é a
décima quarta; **pela lista é a décima terceira**, e o desvio é o que a dívida
62 declara.

É da mesma classe do `tests_outbound` e do `tests_handoff` — não corre os
testes, corre a **saída** deles —, e a razão de haver um ensaio de base é a
lição mais cara do KAM-019:

> **Uma base falsa nunca lê o texto do SQL.** Ela despacha por identidade da
> constante e responde o que o ensaio quiser, pelo que **qualquer mutação do SQL
> sobrevive** — e uma mutação que nenhum teste pode matar conta como prova de
> uma garantia que não temos.

**O que só esta *suite* prova**, porque pede um PostgreSQL verdadeiro:

- **O `ON CONFLICT` da reserva sob concorrência.** Duas chamadas em **duas
  ligações**, e é a única forma de o provocar: em série a segunda nem chega ao
  `INSERT` — encontra a linha na leitura e sai pelo caminho rápido. Foi
  exactamente este o buraco que a prova por mutação encontrou no `ensureAccount`
  do KAM-019.
- **A monotonia do `WHERE estado = 'pendente'`.** Sem ele, uma segunda passagem
  reescrevia um `armazenado` já feito — com o `content_type`, o `size` e o
  `sha256` de outro objecto — ou ressuscitava um `rejeitado`.
- **A `media_assets_armazenado_ck` a recusar pelo caminho do código**, e não por
  um `INSERT` escrito à mão no teste.
- **O X-03 sobre a `media_assets`**, com o controlo positivo: com o contexto de
  A vê-se a de A, e as de B não aparecem; e uma escrita na linha de B não
  acontece, com `FORCE`, nem como dono.
- **Que nenhum URL da Meta chega à base**, percorrendo a tabela inteira
  convertida a texto, coluna a coluna (critério 3).

A cobertura de `src/med/` mede-se aqui, contra o estrato **`restante`** e não o
`critico`, pela mesma decisão escrita que a saída e o *handoff* tomaram: o DoD
do ticket diz «cobertura ≥ limiar», sem número, e alterar `ci/thresholds.yaml`
pede dois revisores.

**Não corre contra simulador nenhum, e isso é decisão e não falta.** A API de
mídia da Meta **não tem evidência nenhuma** no `E1` — nem tamanhos, nem
expiração do URL, nem o fluxo de duas etapas, nem códigos de erro —, pelo que o
`ClienteDeMidia` entra por porta e o cliente falso vive no próprio ensaio. Um
simulador dela seria uma invenção a fingir medição; e o simulador do KAM-024 não
a cobre, porque o `id` que ele põe no webhook não é servível pelos *endpoints*
de mídia.

#### A décima quinta: os modos da conversa (KAM-018)

`tests_modos` põe o módulo dos modos — TypeScript, em
`packages/core-ts/src/modos/` — a correr contra o PostgreSQL com a RLS ligada e
**cinco ligações**: três de `kamba_app`, uma de `kamba_resolver` e a do
administrador. O desenho está em [`modos-conversa.md`](modos-conversa.md). Pelos
ordinais destes títulos é a décima quinta; **pela lista é a décima quarta**, e o
desvio é o que a dívida 62 declara.

**As três ligações de `kamba_app` não são luxo**, e são a razão pela qual esta
*suite* existe: um `pg_advisory_xact_lock` só é exclusão mútua entre **sessões
diferentes**, e o `comTenant` do `tenant_guard` recusa dois usos concorrentes da
mesma ligação (`LigacaoEmUsoError`). Com uma, as duas transacções sairiam em
série pela mesma conexão e o ensaio provava que o JavaScript é sequencial.

**O que só esta *suite* prova**, porque o objecto da prova é o servidor:

- **O *lock* serializa de verdade.** A guarda pré-envio **bloqueia** à porta de
  uma transição em curso — mede-se que ela não resolveu depois de 150 ms com a
  transacção aberta — e, quando entra, vê o modo já mudado. É a metade do
  critério 8 do KAM-015 que esse ticket teve de deixar por cumprir («**Não há
  *lock***»), e é este ticket que a fecha.
- **Duas transições concorrentes deixam uma transição e um evento.** Quem decide
  é o predicado `AND antes.mode = ANY($4)` do `SQL_MUDAR_MODO` sob `FOR UPDATE`,
  não quem leu primeiro — e quem perde a corrida **não emite evento**, que é o
  que impede duas mudanças publicadas para uma transição. Em série, as duas
  chamadas davam o mesmo resultado pela razão errada.
- **As 100 intercalações do critério 3, com semente fixa e reproduzíveis.** A
  ordem de cada volta sai de um `mulberry32` com a semente escrita no ficheiro, e
  o ensaio corre as 100 **duas vezes** e compara as sequências: é essa segunda
  passagem que impede um `Math.random()` de voltar. Em todas as voltas em que o
  *echo* foi ordenado primeiro, **0 mensagens do bot saíram**.
- **O silenciamento é por conversa e não por canal.** Duas conversas do **mesmo**
  canal, uma em `dono` e outra em `bot`: a primeira suprime, a segunda passa. Com
  uma base falsa isto não prova nada; aqui prova que nada no caminho do envio
  olha para o canal.
- **0 invocações do AGR fora do modo `bot`**, com o `Chr` do KAM-014 e o
  `ResolvedorDeCanal` **verdadeiros** a ler o modo que esta bateria acabou de
  escrever, e com o controlo positivo primeiro: sem o *job* que sai em `bot`, o
  zero dos outros três não dizia nada.
- **O relógio das 24 h conta do `handoffs.opened_at` quando não houve actividade
  humana nenhuma.** É um `COALESCE` com subconsulta e um `max` sobre a tabela do
  KAM-019, e nada disso se prova sem planeador. E o caso de fronteira fica
  afirmado: sem actividade **e** sem *handoff*, a conversa **não** é pausada.
- **O privilégio da revisão `0016` existe e é por coluna.** O oposto de um teste
  de política: não se afirma que o código não escreve o modo por fora, afirma-se
  o que cada papel **consegue** — `kamba_app` escreve `mode` e
  `last_human_activity_at`, continua a não poder reescrever as quatro colunas da
  identidade da conversa, e o `kamba_resolver` não lê nem escreve conversas.
- **O X-03 sobre a `conversations`, pelo caminho deste módulo.** Com o contexto
  de A, o modo de B não se lê nem se muda — e a guarda de A sobre uma conversa de
  B **recusa** o envio em vez de o deixar passar, que é o lado seguro.
- **Que a emissão e a escrita confirmam juntas.** Com uma porta de emissão que
  levanta, a transição é desfeita: é a propriedade que o `chr/eventos.ts` **não**
  tem para o `contact.merged` e que aqui se tem, porque quem escreve o modo e
  quem emite são o mesmo papel na mesma transacção.

A cobertura de `src/modos/` mede-se aqui, contra o estrato **`critico`** e não o
`restante`, e a decisão diverge da que a saída, o *handoff* e a mídia tomaram: é
o único código que escreve `conversations.mode`, e um defeito nele não é um bug —
é o assistente a interromper uma pessoa (`docs/tecnica/01` §10.2) ou a responder
a um cliente que pediu para parar. `ci/thresholds.yaml` ganha `*/modos/*` no
`critico`, e **isso pede dois revisores que esta alteração não tem**: fica dito
aqui e na secção de verificação do ticket.

**Não corre contra simulador nenhum, e isso é desenho e não falta.** A guarda
recusa o envio **antes** de haver chamada à Meta — é o passo 3 dos sete do
`outbound/adapter.ts`, e o `SQL_ENFILEIRAR` é o passo 4 —, pelo que não há
chamada HTTP nenhuma a contar. A porta do AGR é uma interface (KAM-025) e não uma
fila.

**E o que esta *suite* não mede, por não existir:** a transição `bot→dono` por
*echo* real precisa de `smb_message_echoes`, que é coexistência (KAM-017), e a
métrica `echo_latency_ms` pede ≥ 30 *echoes* de *staging* com números +244
(R6/L6, KAM-100). Nesta bateria o gatilho `echo_do_dono` é **disparado** pelo
ensaio, que é o que a máquina expõe.

## 4. Gates reservados (5)

Existem no §4 e são implementados pelos tickets que criam o que eles testam.
Ficam a **falhar**, de propósito.

Não é teimosia: um *job* reservado que passasse em silêncio fazia o pipeline
parecer que cobre o que não cobre, e nada obrigaria ninguém a ligá-lo. Um *job*
vermelho com o ticket no nome é um lembrete que não se perde.

No *workflow* estão com `continue-on-error: true` e **fora dos *required
checks***: aparecem vermelhos em cada PR e não bloqueiam o *merge* hoje. A
válvula formal é um *waiver* com prazo de 30 dias.

**Sobra um.** O 7 saiu desta lista com o KAM-007, e sair custou três
alterações e não uma — é o detalhe em que um gate «ligado» fica ligado a
fingir:

1. o alvo `ci-7` passou a correr o `contract_diff` em vez do
   `ci_gate_reservado.py`, e entrou no alvo `ci:`;
2. ganhou **job próprio** no *workflow*, sem `continue-on-error` e com
   `fetch-depth: 0` — a comparação com o ramo principal precisa de histórico;
3. entrou no `needs:` do agregador «gates do KAM-002». Sem este terceiro passo,
   o *job* ficava verde e **ninguém o exigia**.

#### A parte dos webhooks da Meta (KAM-024)

O alvo `ci-7-meta`, que o `ci-7` chama. Três verificações, e a ordem não é
arbitrária: o *scan* primeiro, porque é o que protege um dado pessoal, e um PR
que o quebre não precisa de esperar pelos testes para o saber.

| Passo | Comando | Falha quando |
|---|---|---|
| *scan* de telefones | `meta-sim varrer $(ROOT)` | um número de forma real está num ficheiro sem entrada no inventário, **ou um a mais num ficheiro já declarado** |
| cobertura | `meta-sim cobertura` | algum dos 33 itens (16 tipos, 11 campos, 6 motivos) tem 0 *fixtures* ou 0 testes, ou há uma marca desconhecida |
| *suite* offline | `pnpm --filter @kamba/meta-sim run test` e a ida e volta no GWY | qualquer teste vermelho |

**Os códigos de saída são três e não dois**: `0` conforme, `2` há achados, `1` a
ferramenta não conseguiu correr. O terceiro existe de propósito — «0 ficheiros
lidos» **não** é «0 achados», e devolver `0` aí transformava o gate num enfeite.
É a mesma armadilha que o `lint_contagens` sob `.claude/` já mordeu uma vez
(`docs/dividas-documentais.md`, linha 44).

O *scan* confronta o repositório com o inventário de
`tools/meta-sim/src/inventario.ts`, e esse ficheiro explica porque é um
**raquete** e não uma isenção: isentar `tests/` deixava passar um número novo
dentro de um ficheiro já tolerado, que é exactamente o caso que importa. Medido
hoje: **1053 ficheiros, 86 ocorrências de forma real, 86 declaradas, 0
divergências**.

Tempo das duas suites: **24 s**, contra os ≤ 5 min que o critério 8 do KAM-024
põe como *proposta*.

A *suite* **online** — a nocturna contra o número de teste de *staging* — não
existe e não bloqueia este gate: depende de `ext:KAM-102` e do número de teste da
app Meta de *staging*. Quando existir, é de *release* (gate 15, KAM-078) e não de
PR, e uma falha da Meta ou das credenciais gera **alerta e não falso verde**.

#### A quinta verificação: os `enum` contra o dicionário (KAM-159)

O gate 7 tinha quatro verificações e passou a ter cinco. A nova,
`contract_diff dominios`, confronta o `enum` de um contrato com o **domínio
canónico** que lhe corresponde, e nasceu de um defeito que esteve dois tickets
de pé sem nenhum gate o dizer:

> O dicionário nomeava **cinco** finalidades de consentimento e os 38 contratos
> nomeavam **oito**. Cruzavam-se **numa só**, e duas que o canon declarava eram
> **impossíveis de emitir** — o `enum` era fechado e não as tinha.

Cada gate verificava o seu lado e ninguém verificava a costura: o **3b** lê os
contratos, mas o nível 1 só procura variantes **declaradas** e o nível 2 só
pergunta «este nome existe algures no §3?»; o `canon_lint/eventos.py` nunca
compara um `enum` com um domínio; e o gate 7 não consultava o dicionário.

Compara **nos dois sentidos**, e a assimetria é deliberada:

| Sentido | Alcance | Porquê |
|---|---|---|
| valor no contrato que o canon não declara | **todas** as versões | congelado não quer dizer dispensado |
| valor no canon que o contrato não tem | só a **última** versão de cada tipo | uma versão publicada está congelada (§6.6): exigir que uma `v1` cubra um domínio que cresceu depois dela seria exigir que se alterasse um contrato fundido |

Vive no gate 7 e não no 3b porque é aqui que os contratos já estão lidos e
indexados por tipo e versão. É **fail-closed** nos três sítios onde pode não
ver nada: sem dicionário, sem domínios, ou com um caminho vigiado que não bate
em contrato nenhum.

---

## 5. Excepções (*waivers*)

[`ci/waivers.yaml`](../ci/waivers.yaml) é **o** mecanismo. O KAM-067 diz
«excepção registada em ADR» e o KAM-078 diz «exige referência a ADR/aprovação»;
ambos consomem este esquema em vez de inventarem o seu.

| Campo | Obrigatório | Nota |
|---|---|---|
| `gate` | sim | **doze** aceitam: 3, **3b**, **3c**, 4, 5, 6, 7, 8, 9, 11, **14** e **18**. Os outros **oito** não (1, 2, 10, 12, 13, 15, 16 e 17), e a recusa diz a razão **desse** gate — ver abaixo. Os vinte são os dezoito do canon mais o 3b e o 3c |
| `alvo` | sim | o que exactamente se dispensa; nunca «tudo» |
| `adr_ou_aprovacao` | sim | `ADR-NNN`, `ADR-LNNN` ou `aprovacao:<quem>@<data>`. **A data é lida** (KAM-135): tem de ser real, não futura, e não pode preceder o `criado_em` em mais de 30 dias |
| `autor` | sim | a quem se pergunta |
| `razao` | sim | ≥ 40 caracteres: tem de sobreviver à saída do autor |
| `criado_em` | sim | data ISO, não futura. Obrigatório desde o **KAM-135** |
| `expira_em` | sim | data ISO, ≤ 30 dias **contados de `criado_em`** (*proposta* do KAM-002) |

Qualquer outra chave é **erro de configuração**, com código 2 (KAM-134).

**Um *waiver* expirado falha o pipeline.** Não avisa, não ignora. A alternativa
produz excepções que ninguém revisita, porque nada obriga a isso.

### Renovar não é empurrar uma data

Até ao KAM-135 o prazo contava-se de **hoje**, e não havia `criado_em`.
Consequência: bastava mexer um dígito no `expira_em` para a excepção durar mais
trinta dias — e depois mais trinta, para sempre. Era **o inverso exacto** da
propriedade que esta secção diz entregar.

Agora prolongar exige um `criado_em` novo — e, **na forma
`aprovacao:<quem>@<data>`, uma aprovação contemporânea dele**: uma aprovação
com mais de 30 dias do que a criação é recusada, pelo que renovar é pedir a
alguém que volte a aprovar.

**O que isto não verifica, e fica dito em vez de prometido.** Um `ADR-NNN` não
caduca — é uma decisão de arquitectura, e exigir um ADR novo de trinta em trinta
dias seria pedir arquitectura nova. E o `autor` não se verifica: não há estado
da versão anterior. Para a forma `ADR-NNN`, «decisão nova com dono novo» é
**convenção de revisão**, não propriedade imposta. Quem revê o *diff* é quem a
impõe.

### Os dezanove gates do canon, e a posição de cada um

Os gates que aceitam *waiver* deixaram de poder divergir do canon em silêncio.
O conjunto não se escreve à mão: o `tools/ci_waivers.py` **lê a tabela do
`specs/01` §4** e exige que cada um dos **dezanove** esteja classificado — ou
aceita, ou «não aceita, e eis porquê». Um gate novo no canon que ninguém
classificou falha o `make ci-waivers` **no dia em que nasce**, e não no dia em
que alguém precisar dele.

> **Dezanove, e não dezoito.** A primeira versão desta leitura procurava só
> dígitos, e com isso o **`3b`** — o lint de nomes canónicos, vivo desde o
> KAM-111, com *job* próprio — ficava invisível: nem aceitava *waiver* nem dizia
> porque não, e respondia a quem lho pedisse com a frase dos gates 1 e 2. Pior:
> o teste que devia detectar a divergência prendia-se a «dezoito», que era o
> número errado, e **cimentava a cegueira**. Hoje o número deriva da tabela.

| Não aceita | Porquê |
|---|---|
| 1, 2 | um *build* que não compila, ou um tipo que não verifica, corrige-se |
| 10 | SAST não tem ticket nem implementação (§7, lacuna 3): abrir-lhe a porta antes de ele existir é prometer uma excepção a um *gate* que ninguém pode correr |
| 12 | política de categorias: é lei e Termos da Meta, não qualidade de código |
| 13 | *eval golden*: o limiar **é** a baseline, e dispensá-la é movê-la sem o dizer |
| 15 | *smoke* em staging: é a última verificação antes de produção |
| 16 | aprovação humana — um *waiver* a uma aprovação humana é a aprovação a dispensar-se a si própria |
| 17 | *deploy* em produção não é uma verificação, é um acto |

**Os gates 14 e 18 entraram** porque o KAM-067 e o KAM-078 consomem este
esquema, como esta secção sempre disse — e o validador **recusava-os**. O
KAM-067 ia encontrar o mecanismo fechado, e a tentação de inventar o seu é
precisamente o que esta secção existe para evitar.

---

## 6. Autenticação

Por **OIDC** (`id-token: write`), como `docs/tecnica/08` §4.8 exige. Não há
chaves estáticas: um `grep` por referências ao cofre de segredos do GitHub nos
*workflows* devolve zero, e o gate 9 varre os próprios ficheiros do *workflow*.
Desde o KAM-067 esse `grep` deixou de ser uma frase deste documento: é a regra
`chave-estatica-no-ci`, que falha o gate 11 ([`supply-chain.md`](supply-chain.md) §7).

O `permissions` de topo é `contents: read` e cada *job* pede o mínimo que precisa.

**A verificação do *ruleset* (KAM-137) não está aqui, e é por causa desta
secção.** Comparar o *ruleset* efectivo com
[`.github/rulesets/main.json`](../.github/rulesets/main.json) exige a permissão
`administration` do GitHub, que o `GITHUB_TOKEN` das Actions não oferece; trazer
outro *token* obrigava a uma referência `secrets.*` num *workflow*, que é o que
a regra `chave-estatica-no-ci` recusa. Por isso a verificação é `make ruleset`,
corre fora deste CI, e a credencial é de **leitura**
(`administration: read`) — ver
[`adr/ADR-L003-verificacao-do-ruleset.md`](adr/ADR-L003-verificacao-do-ruleset.md).
**Nenhum ficheiro de `.github/workflows/` foi tocado por esse ticket**, e é essa
a razão pela qual o `grep` acima continua a devolver zero.

---

## 7. Lacunas do canon que este ticket encontrou

Ficam registadas porque são do canon e não deste ticket, e porque inventar-lhes
resposta seria pior do que nomeá-las:

1. **Os donos dos gates 1, 2, 3, 4 e 9 não existem em nenhum documento.**
   `specs/01` §4 não tem coluna de dono; `docs/tecnica/09` §7 só atribui seis. Os
   cinco da tabela §2 são **proposta**.
2. **O gate 5 (integração) não é reclamado por nenhum ticket.**
   `specs/EPIC-01` atribui os gates 5–8 a KAM-003, KAM-004, KAM-007 e KAM-024,
   mas nenhum dos quatro menciona o gate 5.
3. **O gate 10 (SAST) não tem ticket.** O KAM-002 exclui-o explicitamente.
4. **A série `D` significa duas coisas** — decisão aberta e prazo em dias — e isso
   limita o que o gate 3 pode garantir (§3).
5. **`docs/evidencia/KAM-024.md` é citado em `specs/EPIC-02` e não existe.**
6. **Os anexos `E1`–`E5` não têm índice canónico** em nenhum dos três `INDICE.md`.
7. **O §4.1 fixa o limiar de cobertura e não a sua granularidade.** Agregado por
   estrato (o que está implementado, por ser a leitura literal) deixa passar um
   módulo pequeno sem testes; um piso por ficheiro apanha-o e fecha a porta a
   ficheiros gerados legítimos. A decisão é do canon, não deste ticket (§3,
   gate 4).
8. **O critério de *flags* de edição *enterprise*** que `docs/tecnica/09` §7
   atribui ao *gate* das licenças — `rbac`/`auth-oidc` Medusa, `enterprise/`
   Chatwoot, `ee/` Langfuse activos — não está implementado, e é dessa linha que
   a tabela §2 herda o dono do *gate* 11. Fica para o ticket que instalar esses
   componentes: hoje não há o que verificar. **Continua aberta depois do
   KAM-067**, pela mesma razão — o critério 7 desse ticket ficou por cumprir, e o
   que entrou foi o registo do que tem de ficar desligado (campo `ee` de
   `ci/supply-chain/licencas.yaml`).
9. ~~**O *gate* 9 varre a árvore, não a história do PR.**~~ **FECHADA pelo
   KAM-131.** Um segredo posto num *commit* e retirado no seguinte passava, e
   entrava no `main` com o *merge* — que é precisamente o cenário com que o §3
   justifica o *pre-commit*. O *gate* 9 corre agora **duas** passagens; o
   conjunto de *blobs* é o do intervalo do PR, as áreas permitidas aplicam-se
   com o caminho que o *blob* tinha nesse *commit*, e o `base` chega ao *gate*
   em bruto a partir do evento (§3, *gate* 9). **Fica aberta a parte que não era
   do ticket:** a decisão de subir a prioridade de P1 a P0 é do Responsável de
   Segurança com o Arquitecto de Plataforma, e não foi tomada.
10. ~~**A cobertura Node mede só os ficheiros carregados pelos testes.**~~
    **Fechada pelo KAM-132** (§3, *gate* 4): o `coverage_gate` lê do disco o
    âmbito de `ci/thresholds.yaml` e injecta a 0% o que nenhum relatório mediu,
    pelo que o denominador do lado Node cresce com TypeScript sem testes, como
    já crescia do lado Python. **A lacuna estava certa no defeito e errada na
    cura**: `--test-coverage-include` é um filtro sobre o que o V8 reportou e
    nunca vai ao disco, pelo que sozinho não move o denominador — medido no Node
    24.21.0 e confirmado no código do próprio Node. A *flag* entrou, mas para
    fazer o relatório ser igual ao âmbito — e nem para isso ficou, porque a
    inclusão retirava do relatório o ficheiro que nenhum estrato classifica. O
    que o `make coverage-node` passa é `--test-coverage-exclude`.
11. ~~**O SBOM por serviço não atravessa um `link:`.** Omite os pacotes do
    próprio *workspace* que o serviço carrega: o `services/gwy` declara
    `@kamba/core-ts`, os testes carregam-no, e não aparece no seu SBOM.~~
    **Fechada pelo KAM-133** (§3, *gate* 11). A travessia mapeia o caminho do
    `link:` de volta à chave do importador e continua dali, transitivamente e
    com visitado-é-visitado. O `services/gwy` passa de **3** para **25**
    componentes, com `@kamba/contracts`, `@kamba/core-ts` e os 22 terceiros
    instalados que o `core-ts` traz; o conjunto (`kamba.cdx.json`) fica nos
    mesmos **142**, que é a prova de que o fecho completo já estava certo — e é
    por isso que licenças e vulnerabilidades não mudaram.

    **Atravessar não chegava: a primeira versão trazia 14 componentes a mais a
    três serviços**, e a revisão adversarial independente mediu-os contra o
    próprio `pnpm`. O `pg` está resolvido como *peer* opcional no *snapshot* do
    `bullmq` **porque o `core-ts` o declara nas suas `devDependencies`** — o
    grupo excluído um nível acima a voltar a entrar um nível abaixo. A
    travessia passou a ler os *peers* opcionais de `packages:` e a não os
    seguir, e é agora confrontada com
    `pnpm --filter <alvo> list --prod --depth Infinity` nos sete importadores
    (`tools/sbom/tests/test_oraculo_pnpm.py`).

    **E a classe fica fechada, não só o caso npm.** Eram três formas da mesma
    ligação, e só uma estava no enunciado: (a) o `link:` de `importers:`; (b) um
    importador escrito `packages/contracts: {}`, que o leitor nem registava como
    importador — o `@kamba/contracts` não entrava no SBOM de nenhum dos quatro
    serviços que o declaram, e não se via porque, sem travessia de `link:`, nada
    procurava o destino; e (c) o lado **Python**, onde o
    `services/agr/pyproject.toml` nomeia `kamba-core` em
    `[project].dependencies` — não é instalação editável, que não existe neste
    repositório, mas é a mesma declaração e tinha o mesmo defeito. Varridos os
    outros leitores de `pnpm-lock.yaml`: o `tools/lint_arch/manifests.py` lê o
    `specifier` e não faz fecho por alvo, pelo que não tem esta forma.
12. ~~**Sete chaves de `ci/*.yaml` que nenhum código lê**~~ — **fechada pelo
    KAM-134**, e eram **oito**: a `desconhecidas.razao` não estava em lista
    nenhuma. Todas passaram a **comentário**, nenhuma a ser lida, e a escolha é
    a mesma oito vezes pela mesma razão: todas descrevem ou uma **regra de
    bloqueio** (o arredondamento da cobertura, a política de licenças não
    determinadas) ou uma **semântica** (as expressões SPDX, o intervalo da
    série `D`). Nenhuma é parâmetro de operação, e uma regra de bloqueio
    configurável deixa de ser uma regra. A razão de cada uma está escrita no
    `ci/*.yaml` respectivo.

    **E a classe fica fechada, não só as oito:** os **catorze** leitores de
    `ci/*.yaml` — e não os seis que o ticket nomeava — recusam agora uma chave
    que não conheçam, com **código 2**, por nível, com o conjunto aceite na
    mensagem. O mecanismo é um só, `kamba_yaml.exigir_chaves`; eram **quatro**
    implementações da mesma ideia (`canon_lint`, `supply_chain/imagens`,
    `supply_chain/licencas`, e a que o ticket mandava escrever de novo).
    Um teste confronta, por ficheiro, as chaves presentes com as que o leitor
    declara — é o que impede uma chave nova de nascer não lida.
13. ~~**O validador de *waivers* aceita o que não devia**~~ — **fechada por
    dois tickets.** As «chaves desconhecidas em silêncio» pelo **KAM-134**, com
    o mecanismo partilhado, que é o que o Contexto dele previa e a razão de ele
    bloquear o seguinte. As outras três pelo **KAM-135**: a data dentro de
    `adr_ou_aprovacao` passou a ser lida (um `@9999-99-99` satisfazia a
    exigência de «aprovação registada» do `specs/01` §4 sem registar nada); o
    `criado_em` é obrigatório e o prazo conta-se **dele**, pelo que renovar
    deixou de ser um *diff* de um caractere; e os *gates* **14** e **18**
    entraram, que esta secção sempre disse consumirem o esquema e que o
    validador recusava.

    **E a classe fica fechada, não só os quatro:** o conjunto de *gates*
    deriva agora da tabela do `specs/01` §4 e exige que os dezanove estejam
    classificados. Um *gate* novo no canon sem posição falha o
    `make ci-waivers` no dia em que nasce.
14. ~~**O `tools/kamba_yaml.py` tem dois erros de leitura silenciosos:** um `>-`
    como primeira chave de um item de lista engole as chaves seguintes, e um
    item de lista não citado que contenha `:` torna-se um mapa. O módulo
    argumenta que a recusa larga é o que o torna confiável, e estes dois casos
    são o contrário disso.~~ **Fechada pelo KAM-136.** O caso 1 passou a
    **ler-se correctamente** — o defeito era a indentação do pai passada à
    dobra, não uma regra em falta — e o caso 2 passou a **ler-se como cadeia**,
    porque o YAML exige `:` seguido de espaço ou fim de linha para separar
    chave de valor. A varredura classificou **101** construções contra o leitor
    anterior e fechou **56** leituras silenciosas, 46 delas por recusa: `>` e
    `>+` lidos como `>-`; `#` e linha vazia dentro de um escalar dobrado **em
    qualquer posição, incluindo antes da primeira linha de conteúdo**;
    indentação irregular dentro da dobra; aspa aberta e não fechada; escalares
    que parecem número e não são inteiro decimal (incluindo `017` e `0644`,
    octais em YAML 1.1 e decimais em 1.2, e `1:30`, sexagesimal em 1.1);
    escalares ambíguos como booleano ou nulo; caracteres de controlo; `NEL` e
    `U+2028` como quebras de linha; e um escalar não citado com `: `, que o
    YAML também recusa. Cinco recusas que recusavam **de mais** passaram a
    ler-se: o BOM UTF-8, o `---` de um documento único, um `---` indentado
    dentro de um escalar dobrado e `[ ]`. O *docstring* do módulo passa a listar
    o que recusa, e **cada linha da lista tem um teste** — duas estavam falsas
    na primeira versão. A estrutura lida dos 22 ficheiros reais é a mesma antes
    e depois, campo a campo (2 221 campos folha, 0 divergências), provado por um
    teste permanente que usa a cópia congelada do leitor anterior como oráculo
    (`tools/lint_arch/tests/leitor_antes_do_kam136.py`). O `ci_waivers` e o
    `supply_chain egress` — os dois únicos dos dez consumidores que reportavam
    uma recusa do leitor como achado, e portanto dispensável por *waiver* —
    passam a devolver 2. Evidência em
    [`evidencia/KAM-136.md`](evidencia/KAM-136.md); revisão adversarial em
    [`ANALISE-12`](analises/ANALISE-12-KAM-136-leitor-de-yaml.md), que
    encontrou um bloqueador da mesma família do caso 1 e outro no `egress` que
    a primeira versão da evidência dava por conforme. **Fica aberto o que o
    ticket deixou fora:** o repositório tem **três** leitores de subconjunto de
    YAML — este, `tools/canon_lint/yamlreg.py` e
    `tools/secrets_inventory/yamlsubset.py` — e só o primeiro foi varrido
    (lacuna 22).
15. ~~**O *ruleset* não tem quem o verifique.** Está espelhado em
    [`.github/rulesets/main.json`](../.github/rulesets/main.json), e o espelho
    não é aplicado por nada: fechar a volta precisa de um *token* com
    `administration: write`, que o CA deste ticket proíbe («sem chaves
    estáticas»).~~ **Fechada pelo KAM-137 na metade que se podia fechar — a
    detecção —, e a lacuna estava errada numa coisa: comparar não precisa de
    `administration: write`, precisa de `administration: read`.** É essa a
    decisão, registada em
    [`adr/ADR-L003-verificacao-do-ruleset.md`](adr/ADR-L003-verificacao-do-ruleset.md):
    só detecção, com um *token* de leitura, que compara e nunca aplica — e o
    módulo só faz `GET`, com uma guarda de máquina que varre todos os seus
    módulos e recusa verbos de escrita em literais, `--method`/`-X`, comandos
    do sistema, `subprocess` fora de `gh api` e pedidos com corpo (o que essa
    guarda **não** garante está escrito nela). O `make ruleset` compara os seis
    campos de política, com `bypass_actors` vazio e os sete contextos nomeados,
    e sai **2** quando não consegue ler — `403`, sem `gh`, API em baixo — pela
    mesma regra que o *gate* 11 aplica à OSV. Os campos voláteis ignorados
    estão nomeados um a um em `tools/ruleset_check/comparador.py`.

    **Corre sobre uma lista de alvos, e não sobre um repositório.** O espelho
    viaja na árvore que é empurrada para os **dois** repositórios, e a primeira
    versão nomeava só o privado: corrida de um clone do público, lia o
    *ruleset* do privado, imprimia «conforme» e saía 0 de dentro de um
    repositório sem protecção nenhuma. Agora [`../ci/ruleset.yaml`](../ci/ruleset.yaml)
    declara um alvo por repositório, resolve o *ruleset* pelo `name` do
    espelho, e **um repositório sem *ruleset* nenhum é vermelho** — saída 1,
    `repositorio-sem-ruleset`, porque a leitura correu e a resposta foi que a
    política não está aplicada ali.

    **O que fica por fechar, e é metade:** isto **não é um *gate* de PR** e não
    corre no CI deste repositório. A API dos *rulesets* exige a permissão
    `administration`, que o `GITHUB_TOKEN` das Actions não tem, e qualquer outro
    *token* obrigaria a uma referência `secrets.*` num *workflow* — que é
    exactamente o que a regra `chave-estatica-no-ci` deste documento recusa
    (§6). **A divergência é detectada quando alguém corre a verificação, e não
    quando acontece**, e montar a execução periódica exige um contexto fora
    destas Actions que não existe. Fica como **lacuna 28**. E uma segunda coisa
    ficou por fechar, nomeada ao medir: o `albinoJimy/kamba-plataforma`, onde os
    PR são abertos hoje, **não tem *ruleset* nenhum** — lacuna 29, agora com
    alvo declarado e com a verificação a dar vermelho por causa dela.
16. **Nenhum PR tem revisão humana imposta por máquina.** O *ruleset* exigia uma
    aprovação, e com um só contribuidor a regra não podia ser satisfeita: o
    GitHub não deixa o autor aprovar o próprio PR. O fundador baixou-a para 0
    para fundir o KAM-002. O DoD continua a pedir revisor e as caixas ficam por
    marcar nos tickets, mas nada bloqueia o *merge* sem ela. **Volta a 1 com o
    segundo contribuidor** (`.github/rulesets/README.md`).
17. **O *gate* 3b bloqueia pelo *job* de resumo, não por nome próprio.** Está
    nos `needs` de `gates do KAM-002`, que é *required check*; o contexto
    `gate 3b — nomes canonicos` **não** foi acrescentado ao *ruleset*, porque
    isso é uma alteração de configuração do repositório que este ticket não
    fez. O efeito é o mesmo do *gate* 8, que também só bloqueia pelo resumo.
    Desde o KAM-137 o estado é **visível** — acrescentar o contexto só ao
    ficheiro põe o `make ruleset` vermelho com `contexto-so-no-ficheiro`, e foi
    assim que o caso (b) desse ticket se demonstrou —, mas visível não é
    aplicado: continua a ser o fundador a acrescentá-lo no GitHub, se o quiser.
    **O *gate* 3c (KAM-138) entrou pelo mesmo caminho e pela mesma razão**,
    embora o seu DoD peça o contexto próprio: escrevê-lo no `main.json` sem o
    aplicar tornaria o espelho **falso**, que é pior do que a lacuna. A caixa
    fica por marcar nesse ticket.
18. **Duas das doze divergências do KAM-111 não têm forma de nome** (D-07, o
    gatilho do *provisioning*; D-09, a retenção de `assistant_queries`) e o
    *gate* 3b não as vê. O critério de aceitação pede doze *fixtures*; há dez.
    Não se inventaram duas para a conta fechar; a decisão é do KAM-141.
19. **O dicionário tem uma contradição que o *gate* imprime em cada execução**
    (`manual_max_minor` nas duas colunas da mesma linha) e não lista `currency`
    no §3. Ver [`docs/nomes-canonicos.md`](nomes-canonicos.md) §7, com mais
    sete achados do mesmo género. Ticket: KAM-141.
20. **O nível 2 do *gate* 3b não sabe o tipo de um nome.** Tabelas, colunas,
    valores, campos e parâmetros partilham um conjunto: `estado` é aceite como
    coluna de qualquer tabela. Medido com 77 nomes plausivelmente errados: 37
    (48%) passam como coluna, 0 como evento, *tool* ou papel — eram 51 (66%) em
    qualquer posição antes da revisão adversarial. Fechar o resto pede que o
    dicionário diga o tipo de cada nome (KAM-141).
21. **O *gate* 3b tem um prazo dentro: a 2026-11-11 fica vermelho** em `main` e
    em todos os PR se as 19 dívidas de `ci/canon-allow.yaml` não tiverem sido
    pagas. É deliberado e tem dono: KAM-139.
22. ~~**Há três leitores de subconjunto de YAML, e o KAM-136 varreu um.** O
    `tools/kamba_yaml.py` (os `ci/*.yaml`, `canon/*.yaml`, `tools/blocklist.yaml`
    e os `egress.yaml`), o `tools/canon_lint/yamlreg.py` (estilo de fluxo, que o
    primeiro recusa de propósito) e o `tools/secrets_inventory/yamlsubset.py`
    (`ops/secrets-inventory.yaml`, que o primeiro também recusa). Cada um tem a
    sua razão escrita e nenhum é redundante, mas **a varredura de leituras
    silenciosas do KAM-136 cobriu só o primeiro** — e dos 101 casos que ela
    classificou, 56 liam mal sem o dizer. Os outros dois leem limiares,
    excepções e o inventário de segredos. O `yamlsubset.py` cita ainda
    `tools/lint_arch/yamlmini.py`, que já não existe (passou a
    `tools/kamba_yaml.py`). Precisa de ticket.~~ **Fechada pelo KAM-148.** Os
    outros dois leitores foram varridos com o método do KAM-136 — cada
    construção corrida contra uma cópia congelada do leitor anterior **e** contra
    o actual, e classificada pela diferença — e a mesma classe de defeito estava
    nos dois: **240 construções** classificadas (131 no `yamlreg`, 109 no
    `yamlsubset`) e **110 leituras silenciosas fechadas**, 96 por recusa e 14 por
    leitura correcta, mais duas recusas que recusavam de mais e passaram a ler. As piores eram uma **chave de topo repetida** no
    `yamlsubset`, que calava a primeira sem dizer nada — no inventário de
    segredos, uma entrada que desaparece — o `chave:valor` sem espaço, que
    virava um mapa (o caso 2 do KAM-136, vivo ali), o `split(",")` que partia
    `["x, y", z]` em três itens, e o `FALSE` lido como a cadeia `"FALSE"`, que é
    **verdadeira** em Python. O que se interpreta e o que se recusa está escrito
    caso a caso no bloco do ticket e em
    [`ANALISE-13`](analises/ANALISE-13-KAM-148-leitores-de-yaml.md); a decisão
    foi a mesma do KAM-136 em tudo menos onde o corpus a mudava, e essas
    divergências estão justificadas. O *docstring* de cada leitor passa a listar
    o que recusa, com um teste por linha, e o do `yamlsubset` deixa de citar o
    `tools/lint_arch/yamlmini.py` (linha 16 de
    [`dividas-documentais.md`](dividas-documentais.md), paga). A equivalência
    campo a campo está provada por teste permanente, com a cópia congelada como
    oráculo e o corpus descoberto por *glob*: **0 divergências** em 525 campos
    folha: 418 do `ops/secrets-inventory.yaml`, 50 nas quatro *fixtures* da
    superfície 3 e 57 nos dois manifestos de `docs/tecnica/02` §5.1, lidos do
    próprio documento — a forma que o EPIC-03 vai escrever, e a prova de que
    nenhuma recusa nova lhe toca.
    **O que ficou dito, e não fechado:** à data do KAM-148 o `registry/` não
    tinha ficheiro de produção nenhum — o conteúdo era do EPIC-03 — pelo que o
    corpus real do `yamlreg` eram quatro *fixtures*. O KAM-009 pôs lá o
    primeiro (`registry/plans.yaml`, a forma dos planos), e ele é lido por este
    leitor em cada execução do *gate*; o primeiro manifesto entra na equivalência
    sem se alterar uma linha, e é por isso que corrigir o leitor **antes** dele
    era o momento mais barato. Os três leitores continuam três: fundi-los, ou
    adoptar uma biblioteca de YAML, contraria a razão de existir dos três (o
    *gate* 9 e o *hook* de *pre-commit* correm antes de qualquer instalação).
23. **O `LF` do Node conta linhas de comentário e linhas vazias; o do
    `coverage.py` conta instruções.** São duas definições de «linha coberta» no
    mesmo número agregado, e a do Node **infla** a cobertura de código muito
    comentado — que é a norma deste repositório. Medido no KAM-132:
    `packages/core-ts/src/storage/motor.ts`, que é só tipos e comentários, sai
    `67/67` depois de ser carregado, e `src/identity/chaves.ts` sai `235/407`
    contando os 407 como linhas do ficheiro. O KAM-132 igualou o **universo**
    medido; igualar a **definição de linha** é outra coisa, obriga a escolher
    uma das duas para os dois lados, e não tem ticket.
24. **Um `.ts` que nenhum estrato classifica continua invisível.** A regra
    «medido e não classificado falha o *gate*» é sobre o que foi medido; um
    ficheiro fora de `services/*/src/**`, `packages/*/src/**` e `libs/*/src/**`
    — uma pasta `apps/` nova, por exemplo — não é medido nem injectado, e
    nenhum *gate* o diz. O KAM-132 não o fechou porque fechá-lo é decidir que
    todo o `.ts` do repositório tem cobertura exigida, que é a mesma classe de
    decisão da lacuna 7 e não é deste ticket.
25. ~~**Do lado Python, `services/agr/src/` não é medido por nenhum alvo.**~~
    **Fechada pelo KAM-151** (§3, *gate* 4): o `make coverage-python` ganhou um
    terceiro `coverage run --source=services/agr/src` que corre a *suite* de
    `services/agr/tests/` — a que já existia — e funde o LCOV com os outros. A
    lacuna estava certa no defeito e certa na cura: a via do KAM-132 (injectar
    do disco a 0%) não serve para `.py`, porque exigiria contar **instruções**,
    que é a régua do `coverage.py` e não o número de linhas do ficheiro.
    **O que faltava não eram os testes, era a medição**: os três ficheiros já
    estavam exercitados, e medi-los deu **93%** (29/31 instruções) — o estrato
    `restante` **não se moveu**, e o que conta é o delta, que não depende da
    árvore: **+29** no numerador, **+31** no denominador, **+3** ficheiros no
    estrato. Medido duas vezes, por o `main` ter andado entre uma e outra:
    91% → 91% (9652/10526 → 9681/10557) em `f4c7e3d`, e 92% → 92%
    (9880/10730 → 9909/10761) na árvore que funde. **As 31 são instruções e não
    linhas de ficheiro** (os três ficheiros têm 77 linhas): é a régua do
    `coverage.py`, e é a razão pela qual a lacuna 23 continua aberta.
    O que o ticket acrescentou de novo, e que a lacuna não pedia, é o **gate da
    própria cablagem**:
    `tools/lint_arch/tests/test_makefile.py::TestCoberturaPythonMedeOAmbito`
    lê o âmbito do `ci/thresholds.yaml` e falha quando uma pasta de `.py` do
    âmbito não tem `--source=` que a meça — sem isso, a próxima pasta repetia a
    lacuna em silêncio. **Fica aberto o que o ticket deixou fora:**
    as duas instruções não cobertas são o corpo de
    `kamba_agr.create_app()`, a fachada de importação tardia que existe para
    `meta` ser legível sem Starlette instalado e que nenhum teste chama —
    os testes importam `kamba_agr.app.create_app` directamente (nomeado em
    [`evidencia/KAM-151.md`](evidencia/KAM-151.md) §2 e §6). E **a lacuna 26**,
    que este ticket destapou ao fechar esta: o `.py` medido a 0% faz o número
    descer e não sai nomeado no relatório.

26. **Um `.py` medido a 0% não sai nomeado no relatório do *gate*.** Do lado
    Node, um ficheiro do âmbito que nenhum teste carrega entra por **injecção**,
    e o `coverage_gate` imprime-o pelo nome — é o que faz uma descida da
    percentagem ser accionável. Do lado Python o ficheiro entra por **medição**,
    não passa pela lista `injectados`, e o achado de estrato abaixo do limiar
    imprime a percentagem, a fracção e a contagem de ficheiros, nunca os nomes:
    quem vê o *gate* vermelho sabe que o estrato desceu e não sabe por causa de
    quê. Medido no KAM-151: um módulo de 840 instruções sem testes em
    `services/agr/src/` leva o `restante` de 91% para 84% e **não aparece** na
    saída, onde só os três `.ts` injectados saem nomeados. Destapada ao fechar a
    lacuna 25 — uma versão do KAM-151 afirmou o contrário, por ter copiado a
    frase do caso Node do §3. Não se fecha aí porque nomear o que foi medido é
    mexer no relatório para **todos** os estratos e nas duas linguagens, e é
    decisão do dono do *gate* 4, não cablagem de um alvo.
27. **Os diagramas Mermaid nao sao verificados por *gate* nenhum.** O KAM-140
    entregou o `make mermaid`, que corre `mermaid.parse` a serio sobre os **49**
    blocos de `docs/tecnica/`, `docs/` e `specs/` — e passa. Mas nao ha *job*
    que o corra: um diagrama partido entra em `main` na mesma. Nao se fechou ai
    por duas razoes medidas, e nenhuma delas e o tamanho. Primeira: os *jobs* do
    *gate* 3 e do 3b **nao tem Node**, de proposito (`docs/adr/ADR-L001-toolchain.md`),
    e e nesses que um lint de documentos cairia. Segunda: o `mermaid` nao e
    dependencia deste repositorio, e po-lo no `pnpm-lock.yaml` arrasta uma arvore
    grande de terceiros para o SBOM e para o veredicto de licencas do *gate* 11,
    para uma ferramenta que nao vai para producao — por isso corre num contentor
    com a imagem do `.node-version` fixada por *digest*. Pendurar o alvo num
    *job* que ja tenha `preparar` (o *gate* 2, por exemplo) e a via natural, e e
    decisao do dono do *gate*. Ate la, corre-se a mao.
28. **A verificação do *ruleset* não é um *gate* e não tem agendamento.** O
    KAM-137 entregou a detecção (`make ruleset`) e deixou-a a correr à mão: uma
    divergência aparece quando alguém olha, e não quando acontece. As duas
    razões estão medidas na lacuna 15 e em
    [`adr/ADR-L003-verificacao-do-ruleset.md`](adr/ADR-L003-verificacao-do-ruleset.md)
    — a permissão `administration` não existe no `GITHUB_TOKEN` das Actions, e
    trazer outro *token* para um *workflow* é a chave estática que o §6 proíbe.
    Fechá-la exige um contexto de execução fora destas Actions, que hoje não
    existe. É também a razão por que a **subida a uma GitHub App com escrita**
    continua escrita como caminho de evolução e não como rejeição: o §6 do ADR
    tem os três gatilhos. Precisa de ticket.
29. **O `albinoJimy/kamba-plataforma` não tem *ruleset* nenhum.** Medido a
    2026-10-18: `gh api repos/albinoJimy/kamba-plataforma/rules/branches/main`
    devolve `[]`, e o mesmo comando no `albinoJimy/kamba` devolve
    `["pull_request","required_status_checks","deletion","non_fast_forward"]`.
    O repositório **público**, que é onde os PR são abertos hoje, não tem
    nenhuma das protecções que este documento descreve: nem PR obrigatório, nem
    *required checks*, nem protecção contra apagar ou reescrever `main`. **O
    fundador decidiu a 2026-10-18 criar lá uma cópia do *ruleset* do privado**,
    e criá-lo é acto dele — o KAM-137 estava impedido de alterar *rulesets*.
    O que o KAM-137 fez foi pôr o repositório na lista de alvos de
    [`../ci/ruleset.yaml`](../ci/ruleset.yaml): enquanto o *ruleset* não
    existir, o `make ruleset` sai **1** com `repositorio-sem-ruleset`, e a
    lacuna deixa de depender de alguém se lembrar dela.

    **Vale registar como esta lacuna quase se tornou pior do que era.** A
    primeira versão do KAM-137 nomeava um repositório só, e o espelho
    `.github/rulesets/main.json` descrevia o `kamba` enquanto viajava na árvore
    do `kamba-plataforma`. Corrida de um clone do público, a verificação dizia
    «conforme» — uma máquina a certificar a protecção de um repositório que não
    tinha nenhuma. Foi a revisão adversarial independente a apanhá-lo, e é o
    caso-tipo do que o §1 deste documento chama um *gate* que mente.

> As lacunas 9 a 14 vêm da revisão adversarial, e cada uma está reproduzida com
> um comando em [`ANALISE-02`](analises/ANALISE-02-KAM-002-pipeline-ci.md).
> Não se corrigiram no KAM-002 porque são trabalho com medição própria, não
> porque sejam pequenas — e deixá-las sem nome seria o defeito que este documento
> existe para não ter. A **9** está fechada (KAM-131); as outras cinco são
> KAM-132 a KAM-136.

---

## 8. Demonstração: 6 PRs vermelhos, 6 bloqueios

O critério de aceitação pede prova por execução, e não por leitura: «um PR sem
eles verdes não faz *merge* (verificado por um PR de teste deliberadamente
vermelho por *gate*: 6 PR, 6 bloqueios)». Correu-se sobre o *ruleset* `main:
gates fail-closed do KAM-002` (id 24879081), que exige os seis *gates* activos,
uma aprovação, e proíbe `deletion` e `non_fast_forward`. (A aprovação exigida passou a 0 depois desta demonstração — §7, lacuna 16.)

| PR | Quebra introduzida | *Gate* que falhou | Outros *gates* |
|---|---|---|---|
| #5 | `export const porta: number = "isto nao e um numero"` | 2 — lint e tipos | os cinco verdes |
| #6 | documento a citar `KAM-999`, que não existe no *backlog* | 3 — referências cruzadas | os cinco verdes |
| #7 | módulo de ~450 declarações sem teste nenhum | 4 — unit e cobertura (66%, mínimo 75%) | os cinco verdes |
| #8 | `export const apiKey = "K7mQ…"` com forma de chave de API | 9 — segredos | os cinco verdes |
| #9 | dependência `zod` no `package.json` e fora do *lockfile* | 1 — build | **2, 4 e 11 também** |
| #10 | `PSF-2.0` retirado da *allowlist* (torna `typing-extensions` proibida) | 11 — SCA, licenças, vulnerabilidades e SBOM | os cinco verdes |
| #4 | nenhuma (o próprio KAM-002) | nenhum | **os seis verdes** |

Três coisas que esta tabela diz e que vale a pena não deixar implícitas:

**O PR #9 arrasta três *gates*, e isso está correcto.** O *gate* 1 é
`pnpm install --frozen-lockfile`; quando falha não há `node_modules`, e os
*gates* 2 (`tsc`), 4 (`node --test`) e 11 (lê as licenças do disco) não têm com
que correr. Um *gate* que passasse sem dependências instaladas é que seria
defeito. A cascata é consequência da ordem de dependências do *workflow*, não
imprecisão da atribuição.

**O PR #7 passou à primeira tentativa, e o *gate* estava certo.** A primeira
versão acrescentou 21 linhas sem cobertura: o estrato `restante` foi de 79,4%
para 79,1% e o *gate* 4 passou, porque o limiar do §4.1 é agregado por estrato
(§3, *gate* 4). A demonstração estava fraca, não o *gate*; reforçada para ~450
declarações, o estrato caiu para 66% e o *gate* ficou vermelho. Fica escrito
porque é a parte da demonstração que ensina algo: **um *gate* pode passar pela
razão certa e ainda assim deixar uma demonstração sem valor.**

**Os *gates* 5–8 aparecem vermelhos nos sete PRs** (à data desta demonstração o 8 ainda era reservado; passou a activo com o KAM-003), por desenho (§4): são
`continue-on-error` e não estão nos *required checks*, pelo que não bloqueiam
nada — mas também não se deixam esquecer.

Medição local, no mesmo *commit*: `make ci` verde em **216 s** (168 s de
`bootstrap` + 48 s de *gates*). *Gate* 3: 6930 referências em 210 ficheiros.
*Gate* 9: 236 ficheiros varridos, 0 segredos. *Gate* 11: 99 componentes, 90 com
licença permitida, 9 nossos, e 90 de terceiros consultados na OSV sem nenhuma
`CRITICAL`. *Gate* 4: 78% sobre 2821 linhas, testes verdes.

Cada número acima reproduz-se com um comando, e é por isso que estão aqui em
vez de numa mensagem de *commit*:

```bash
python -c "import sys; sys.path.insert(0,'tools'); from lint_refs.cli import main; sys.exit(main(['--root','.','check']))"
python -c "import sys; sys.path.insert(0,'tools'); from scan_secrets.cli import main; sys.exit(main(['--root','.','tree']))"
cd tools && python -m sbom --root .. licenses
make ci-4
```

> **Os números do *gate* 11 mudam com o `node_modules`**, porque a contagem é do
> que está no disco e não do que o *lockfile* declara — e isso vale a pena
> contar como aconteceu. A revisão adversarial mediu 92 componentes e 83
> permitidas contra os 99 e 90 escritos aqui, e concluiu que o número não
> reproduzia. Reproduz: **num `pnpm install --frozen-lockfile` limpo, que é o
> que o CI faz,** são 99 e 90. Os 92 eram de uma árvore de trabalho com
> instalações parciais por cima.
>
> Os números desta secção são os do CI, que é a árvore que decide se um PR
> passa. Uma contagem feita na máquina de alguém pode divergir, e divergir não é
> defeito — é o que a guarda de instalação do *gate* 11 passou a dizer em voz
> alta em vez de deixar passar.

Os seis PRs de teste foram fechados e os seus ramos apagados depois desta
medição; os números acima são verificáveis nos *runs* do GitHub Actions, que
sobrevivem ao PR.

---

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial (KAM-002): gates 1, 2, 3, 4, 9 e 11 activos; 5–8 reservados; *waivers*, limiares, *allowlist* de licenças e áreas de segredos; seis lacunas do canon registadas. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Demonstração dos 6 bloqueios registada (§8); granularidade do limiar de cobertura documentada (§3) e acrescentada como sétima lacuna do canon (§7). | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | Revisão adversarial ([`ANALISE-02`](analises/ANALISE-02-KAM-002-pipeline-ci.md)): varrimento de vulnerabilidades acrescentado ao gate 11 (§3); alcance do gate 3 passado a lista de exclusão; três evasões do gate 9 fechadas; guarda de instalação no gate 11; *ruleset* espelhado e o *job* de resumo nos *required checks*; números do gate 11 corrigidos (92/83, com comando ao lado); oito lacunas novas (§7, 8–15). | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | O `make ci-9` passa a provar o canário fora da sua área (17 achados), em vez de a prova viver só num `unittest`. Números da §8 fixados nos do CI. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | **Gate 8 activo** (KAM-003): migrações contra um PostgreSQL 18.6 descartável, fixado por *digest*, com trinco `*_gate8`; reservados passam a 5–7; `make ci` corre sete. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | *Gate* 8 depois da revisão adversarial do KAM-003 ([`ANALISE-03`](analises/ANALISE-03-KAM-003-schema-platform.md)): prova por mutação refeita e posta no repositório (20/20); trinco por igualdade; `--bd-existente` exige as palavras-passe; limite de tempo; saltar é falhar. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | KAM-002 fundido em `main`. Aprovações exigidas pelo *ruleset* passam de 1 para 0, por decisão do fundador: com um só contribuidor a regra era insatisfazível. Registado como lacuna 16, com a condição de reversão. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | **Gate 6 activo** (KAM-004): isolamento de tenant na camada SQL, parametrizado sobre o catálogo; `ci/rls_exceptions.yaml` e `ci/secdef_allowlist.yaml`; reservados passam a 5 e 7; `make ci` corre oito; o estrato `critico` deixa de estar vazio. O orquestrador passa a `db/gate_bd.py`. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | **Gate 3b activo** (KAM-111): exportação do dicionário, quatro superfícies e canário; `make ci` corre nove; lacunas 17 a 21. Inclui o que a revisão adversarial ([`ANALISE-05`](analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md)) mudou: canário fixado no código, leitura das revisões por avaliação estática (com os auxiliares do KAM-004), domínios fechados nas formas do `pg_dump`, variantes em cadeias, sentinelas mínimas no código. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | **Gate 11 alargado** (KAM-067): `make ci-11` passa a chamar `make supply-chain` — imagens por *digest* com inventário, sem instalação em *runtime*, serviços só de leitura, lista de saídas por serviço, registo de licenças por versão, quarentena e CI sem chaves, com canário de 59 mutações. Uma licença proibida só se dispensa com ADR. Sem gate novo: `esperados` continua em 9. Detalhe em [`supply-chain.md`](supply-chain.md). | Equipa KAMBÁ |
| 1.10 | Outubro 2026 | **KAM-068**: `make log-lint` como terceiro passo do *gate* 2 (nenhum serviço escreve fora do *logger*, com canário) e `make x11` como primeiro passo do *gate* 6 (1 000 *fixtures* pelos dois *loggers*, saída igual byte a byte, zero achados). Sem *job* novo: os `needs` e o `esperados` do resumo não mudam. O *logger* entra no estrato `critico` de `ci/thresholds.yaml`. | Equipa KAMBÁ |
| 1.11 | Outubro 2026 | KAM-011: o padrão `*/storage/*` entra no estrato `critico` (§3, *gate* 4). Nenhum *gate* novo: a prova contra um servidor S3 real é `make storage-contrato`, à mão ([`armazenamento.md`](armazenamento.md) §7). | Equipa KAMBÁ |
| 1.12 | Outubro 2026 | Prova por mutação dos *gates* de base de dados: paralelismo por omissão de 4 para 8, e uma falha por **carga** da máquina deixa de contar como «apanhada» (`SINAIS_DE_CARGA` → `PROVA INVALIDA`). A classificação da saída ganha testes próprios (`db/tests/test_mutacoes.py`). Seguimento do KAM-142. | Equipa KAMBÁ |
| 1.13 | Outubro 2026 | **KAM-143**: a prova por mutação completa sai do caminho dos PRs e passa a tarefa nocturna no GitHub, fatiada por seis *runners*, com *issue* automático em caso de sobrevivente. Não é um *gate*. O custo — deixar de haver garantia de que a lista estava verde no momento do merge — está escrito no §3, no gate 8. | Equipa KAMBÁ |
| 1.14 | Outubro 2026 | KAM-008: o *gate* 8 passa a correr duas *suites* — `tests` e **`tests_identidade`** (o módulo de identidade de contacto contra o PostgreSQL, com canários no `pg_dump` e no registo do servidor, e a cobertura de `src/identity/` medida por ficheiro); `contactos.ts` excluído da medição do *gate* 4 e `*/identity/*` no estrato `critico`; os testes de `db/` chamam o Alembic no processo. | Equipa KAMBÁ |
| 1.15 | Outubro 2026 | **KAM-136: lacuna 14 fechada.** O `tools/kamba_yaml.py` — o leitor de todos os `ci/*.yaml`, que corre antes de qualquer instalação — deixa de ter casos em que lê mal sem o dizer. Os dois do bloco passaram a ler-se correctamente (o `>-` como primeira chave de um item) e como cadeia (o item não citado com `:`); a varredura classificou **101** construções contra o leitor anterior e fechou **56** leituras silenciosas, 46 delas por recusa, e desfez 5 recusas que recusavam de mais (BOM, `---` de documento único, `[ ]`). A estrutura lida dos 22 ficheiros reais é a mesma antes e depois (2 221 campos folha, 0 divergências), com a cópia congelada do leitor anterior como oráculo permanente. O `ci_waivers` e o `supply_chain egress` passam a devolver 2 — e não 1 — quando o leitor recusa o ficheiro: eram os dois únicos dos dez consumidores a reportar uma recusa como achado, que o *gate* 11 dispensa por *waiver*. Nenhuma dependência nova e nenhum `ci/*.yaml` reescrito. **A primeira versão da correcção não cumpria o objectivo**: a revisão adversarial independente ([`ANALISE-12`](analises/ANALISE-12-KAM-136-leitor-de-yaml.md)) encontrou 2 bloqueadores e 26 achados, com disposição escrita para todos. **Lacuna 22 nova:** há três leitores de subconjunto de YAML e só um foi varrido. | Equipa KAMBÁ |
| 1.16 | Outubro 2026 | **KAM-131**: o *gate* 9 passa a correr duas passagens — a árvore (inalterada) **e** os *blobs* que o intervalo do PR acrescenta à história (`scan_secrets … history`). Fecha a lacuna 9 do §7. O conjunto de *blobs* sai de `git rev-list --objects base..head` e de `git log --raw -c`, deduplicado por SHA de objecto mas com as áreas de `ci/secrets-allow.yaml` aplicadas a **todos** os caminhos do *blob*; o que fazer sem intervalo está escrito por accionamento, e um clone raso, uma base irresolúvel, um intervalo de zero *commits* num PR ou um *blob* que o `git` não devolve são vermelhos. O relatório diz o que **não** varreu. O *job* ganha `fetch-depth: 0` e três variáveis em bruto, confrontadas linha a linha por `tools/lint_arch/tests/test_ci_gate9.py` — não há *lint* de *workflows*. O `-c`, o confronto por linha inteira e os contadores vieram da revisão adversarial ([`ANALISE-14`](analises/ANALISE-14-KAM-131-gate-9-na-historia.md)), que construiu três evasões à primeira versão. Sem *gate* novo: `esperados` continua em 9. | Equipa KAMBÁ |
| 1.17 | Outubro 2026 | **KAM-132**: o *gate* 4 passa a medir o mesmo **universo** nos dois lados — o `coverage_gate` lê do disco o âmbito de `ci/thresholds.yaml`, a partir das raízes dos próprios `padroes`, e injecta a 0% o código que nenhum relatório mediu. Medido com `make ci-4` nos dois estados: `restante` 91% → 91% (o estrato não tinha nada invisível) e `critico` 99% → 94%, com os três ficheiros que entraram a 0% nomeados; um módulo de 50 declarações sem teste, que deixava os três números iguais, leva o `restante` a 88%. O limiar **não** foi tocado. Lacuna 10 fechada, com duas correcções ao que ela propunha: a *flag* sozinha **não** move o denominador (é um filtro; medido no Node 24.21.0 e confirmado no código do próprio Node) e **a de inclusão não se usa** — retirava do relatório o ficheiro que nenhum estrato classifica, que tem de falhar o *gate*; o `make coverage-node` passa `--test-coverage-exclude`. A revisão independente ([`ANALISE-15`](analises/ANALISE-15-KAM-132-cobertura-de-todo-o-typescript.md)) devolveu 3 maiores, 9 menores e 1 suspeita. Lacunas 23 a 25 novas: o `LF` do Node conta comentários, um `.ts` sem estrato continua invisível, e `services/agr/src/` não é medido do lado Python. | Equipa KAMBÁ |
| 1.18 | Outubro 2026 | **KAM-148**: a lacuna 22 fecha. Os outros dois leitores de subconjunto de YAML — `tools/canon_lint/yamlreg.py` (os `registry/*.yaml`) e `tools/secrets_inventory/yamlsubset.py` (o `ops/secrets-inventory.yaml`) — passam pela varredura do KAM-136: 240 construções classificadas por execução contra a cópia congelada de cada leitor, 110 leituras silenciosas fechadas (96 por recusa, 14 por leitura correcta), equivalência campo a campo com 0 divergências e um *docstring* por leitor com um teste por linha da lista do que recusa. | Equipa KAMBÁ |
| 1.19 | Outubro 2026 | KAM-151: a lacuna 25 fecha. O `make coverage-python` mede `services/agr/src/`, que estava no âmbito do *gate* 4 e fora do denominador desde o KAM-002 — com a *suite* a exercitá-lo. O §3 deixa de dizer que falta um alvo do lado Python, e a falta de um `--source=` para uma pasta de `.py` do âmbito passa a falhar um teste. Medido: o **delta**, que é o que o ticket faz e não depende da árvore: **+29** no numerador, **+31** no denominador, **+3** ficheiros, com a percentagem a não se mover. Na árvore que funde: `restante` 92% → 92% (9880/10730 → 9909/10761), 100 → 103 ficheiros; em `f4c7e3d`, onde foi medido primeiro, era 91% → 91% (9652/10526 → 9681/10557). O absoluto subiu porque o KAM-148 acrescentou código testado a `tools/`, que está no estrato; `critico` intacto; limiar não tocado. A prova por mutação do *gate* 4 passa de 24 para 28 (28 apanhadas, 0 sobreviventes), com quatro `cablagem:` novas do lado Python. **Lacuna 26 nova**, destapada por este ticket e trazida pela revisão adversarial: um `.py` medido a 0% faz o número descer e não sai nomeado no relatório. | Equipa KAMBÁ |
| 1.20 | Outubro 2026 | **KAM-154**: o *gate* 2 passa a resolver cada regra do `CODEOWNERS` contra a árvore seguida pelo git. Uma regra que não case com nada reprova o PR — até aqui era ignorada pelo GitHub e deixava a área sem dono, em silêncio, que foi como três regras sobreviveram ao prefixo removido pelo KAM-128 e a dois tickets de medição de referências. Implementa a semântica de *glob* documentada e não `[ -e ]`, e é *fail-closed* no que o GitHub não suporta. Entrou neste *gate* pela razão do `log-lint`, e não como número novo de `specs/01` §4. Não valida se o dono existe: isso é o KAM-137 e a lacuna L-19. | Equipa KAMBÁ |
| 1.21 | Outubro 2026 | KAM-145: o *gate* 3 passa a ter um segundo passo, `lint_handoff`, que lê os **caminhos** dentro dos blocos `### Handoff para Claude Code` e exige que sejam relativos à raiz do repositório — que é onde o executor corre, agora declarado em `../specs/01_Engineering_Standards_e_Handoff.md` §5. Converteram-se **254** ocorrências nos onze epics (247 que apontavam para fora da árvore e 7 sem directório nenhum), entre elas as quatro instruções que mandam escrever um ficheiro de validação. Entra no `ci-3` e **não** como *gate* novo, para não acrescentar um contexto exigido ao *ruleset* de `main`: os sete mantêm-se. Fora dos blocos de *handoff* a regra continua a ser a do KAM-128. | Equipa KAMBÁ |
| 1.22 | Outubro 2026 | KAM-005: o *gate* 8 passa a correr **quatro** *suites* — `tests_eventos` e `tests_eventos_carga` juntam-se às duas, com uma rede Docker própria, PostgreSQL **e** Valkey (digest em `ci/supply-chain/imagens.yaml`), o contentor da fila sem `--rm` e porta fixa para o critério 4 a poder pará-la, e o `kill -9` mandado ao contentor. A carga fica em *suite* própria por custo das mutações. O *gate* 6 ganha `verificar_particoes`: a política de uma tabela particionada não cobre quem lê a partição directamente. | Equipa KAMBÁ |
| 1.23 | Outubro 2026 | KAM-005: as *suites* de eventos correm pela primeira vez num anfitrião Linux ([execução 38881054356](https://github.com/albinoJimy/kamba-plataforma/actions/runs/38881054356)) e fecham três caixas do bloco — a da fila parada, que no anfitrião Windows não reproduzia, e a do p95, que lá media 6,0 s e aqui mede **0,195 s**. | Equipa KAMBÁ |
| 1.24 | Outubro 2026 | KAM-155: o segundo passo do *gate* 3 passa a ler **dois** globos — `specs/EPIC-*.md` e `specs/tickets/*.md` —, porque o EPIC-01 passou a ter um ficheiro por ticket. Com um só, o *gate* ficava verde e deixava 39 blocos sem ser lidos. | Equipa KAMBÁ |
| 1.25 | Outubro 2026 | KAM-158: o *gate* 3 ganha um **terceiro** passo, `lint_contagens`, que confronta cada contagem escrita em prosa com a fonte que a conta. Fecha por máquina a classe «contagem que não acompanha», que já custou quatro correcções à mão. A dívida 30 fica paga; seis ficam declaradas com dono (KAM-130) e prazo. | Equipa KAMBÁ |
| 1.26 | Outubro 2026 | **Gate 7 activo** (KAM-007): contratos de evento — compatibilidade contra o ramo principal, *lint* de PII, exemplos validados e `versao_max` das subscrições. Sai da matriz dos reservados, ganha *job* próprio com `fetch-depth: 0` e entra no `needs:` do agregador; `make ci` corre dez. Reservado passa a ser só o 5. A parte dos *webhooks* do gate 7 continua por fazer (KAM-024). | Equipa KAMBÁ |
| 1.27 | Outubro 2026 | KAM-140: **lacuna 27** — os diagramas Mermaid passam a ter um verificador (`make mermaid`, 49 blocos, `mermaid.parse` a sério) e **não** a ter *gate*: os *jobs* do 3 e do 3b não têm Node de propósito (ADR-L001), e o `mermaid` não é dependência do repositório para não entrar no SBOM nem no veredicto de licenças do *gate* 11. Pendurá-lo num *job* com `preparar` é a via, e é decisão do dono do *gate*. | Equipa KAMBÁ |
| 1.28 | Outubro 2026 | KAM-134: a **lacuna 12** fecha. As oito chaves que nenhum código lia passam a comentário — e eram oito e não sete —, e os **catorze** leitores de `ci/*.yaml` passam a recusar uma chave desconhecida com código 2. O mecanismo e um só (`kamba_yaml.exigir_chaves`), onde eram quatro. O `ci_gate_reservado` devolvia **1 para tudo**, e com isso perdia o que o KAM-136 tinha construído. | Equipa KAMBÁ |
| 1.29 | Outubro 2026 | KAM-157: o §3 (*gate* 9) ganha a *push protection* do GitHub. Existe um `.github/secret_scanning.yml` com uma entrada — a pasta do canário —, por decisão do fundador de 2026-10-18. Não é área cega nova (o `ci/secrets-allow.yaml` já a declarava), não torna o canário invisível ao *gate* 9 (são dois *scanners*), e não pode crescer em silêncio: um teste exige que as duas listas coincidam exactamente. | Equipa KAMBÁ |
| 1.30 | Outubro 2026 | KAM-135: o §5 passa a descrever o que o validador exige. `criado_em` obrigatório e o prazo contado **dele** — renovar deixa de ser empurrar uma data; a data dentro de `adr_ou_aprovacao` é lida e não pode ser futura; e os gates **14** e **18** passam a aceitar *waiver*, que o KAM-067 e o KAM-078 precisam e o validador recusava. O conjunto de gates deriva agora da tabela do `specs/01` §4: os **dezanove** estão classificados — o `3b` incluído, que a primeira versão do *regex* não via e que o teste cimentava a 18 —, e um gate novo sem posição falha. A aprovação datada tem de ser contemporânea da criação, e o que **não** se verifica (o `ADR-NNN`, o `autor`) fica dito em vez de prometido. | Equipa KAMBÁ |
| 1.31 | Outubro 2026 | KAM-159: o *gate* 7 ganha a **quinta** verificação — `contract_diff dominios` —, que confronta o `enum` de um contrato com o domínio canónico, nos dois sentidos. Fecha a costura que nenhum dos dois *gates* via: o dicionário e os contratos nomeavam listas de finalidades que se cruzavam numa só, e duas do canon eram impossíveis de emitir. | Equipa KAMBÁ |
| 1.32 | Outubro 2026 | **KAM-133: a lacuna 11 fecha.** O SBOM por serviço do *gate* 11 passa a atravessar as dependências `link:` do *workspace*: o caminho mapeia-se de volta à chave do importador e a travessia continua dali, transitivamente e com visitado-é-visitado. O `services/gwy` passa de **3** para **25** componentes e o conjunto fica nos mesmos **142** — que é a prova de que o fecho completo já estava certo, e a razão por que licenças e vulnerabilidades não mudaram. **Atravessar não é copiar:** de um pacote ligado seguem-se só `dependencies` e `optionalDependencies`, não as `devDependencies`. **E excluir um grupo um nível acima não chega:** um *peer* opcional já resolvido escreve-se em `snapshots:` como uma `optionalDependencies` qualquer, e o `pg` do `bullmq` só está resolvido porque o `core-ts` o declara em `devDependencies` — a primeira versão deste ticket publicou-o, e a mais treze, em três serviços que o não têm. A travessia passou a ler os *peers* opcionais de `packages:`, e tem agora como oráculo o próprio `pnpm` (`pnpm list --prod --depth Infinity` nos sete importadores, com o `sha256` do *lockfile* a datar a medição). Decisão de desenho escrita no §3: o pacote do *workspace* entra **como componente, com `dependsOn`**, e não se promovem só os seus terceiros. Eram três formas da mesma ligação e só uma estava no enunciado: juntaram-se o importador escrito `packages/contracts: {}`, que o leitor nem registava, e o lado **Python** (`services/agr` declara `kamba-core` em `[project].dependencies`; instalação editável não existe neste repositório). | Equipa KAMBÁ |
| 1.33 | Outubro 2026 | **KAM-137: a lacuna 15 fecha na metade da detecção**, e fecha **corrigida** — comparar não precisa de `administration: write`, precisa de `read`. Decisão do fundador de 2026-10-18, em [`ADR-L003`](adr/ADR-L003-verificacao-do-ruleset.md): só detecção, com *token* de leitura, que compara e nunca aplica. O `make ruleset` (`tools/ruleset_check`) compara os seis campos de política — as quatro regras, os sete contextos, `enforcement`, `conditions`, `name`, `target` — com `bypass_actors` **vazio**, ignora oito campos voláteis nomeados um a um, e sai **2** quando não consegue ler, nunca 0. **Corre sobre uma lista de alvos, e não sobre um repositório:** a primeira versão nomeava só o privado, e como o espelho viaja na árvore dos dois, corrida de um clone do público dizia «conforme» de dentro de um repositório sem protecção nenhuma — foi a revisão adversarial a apanhá-lo, e é o caso-tipo do §1. Agora um repositório sem *ruleset* é **1**, nomeado, e o ramo funde **vermelho** até o `albinoJimy/kamba-plataforma` ter o seu (lacuna 29). **Não é *gate* e não entra no `make ci`**: a permissão `administration` não existe no `GITHUB_TOKEN` das Actions e qualquer outro *token* seria a chave estática que o §6 proíbe; nenhum ficheiro de `.github/workflows/` foi tocado. Executados a sério: contexto acrescentado só ao ficheiro (vermelho, revertido), ficheiro e API iguais no alvo que tem *ruleset* (verde), credencial inválida nos dois transportes, sem credencial e *endpoint* inalcançável (saída 2). Os dois casos que mexem no *ruleset* do GitHub ficam para o fundador, com o procedimento escrito em [`evidencia/KAM-137.md`](evidencia/KAM-137.md) §5. Lacunas **28** e **29** novas. | Equipa KAMBÁ |
| 1.34 | Outubro 2026 | KAM-138: entra o *gate* **3c**, coerência do backlog. O §2 ganha a linha com alvo e dono, e o §3 a secção que descreve as oito verificações — sincronia linha↔bloco nos seis campos, órfãos nos dois sentidos, a tabela-resumo do §3 de cada epic como terceira superfície, reciprocidade `Dependências`↔`Bloqueia`, ciclos com o caminho completo, inversões de prioridade e de fase, contagens derivadas do §4 e «Controlo de versões» sem buracos. O que o distingue de uma comparação de tabelas é a reciprocidade: o §4 não tem coluna `Bloqueia`, e na entrega havia **seis** arestas declaradas de um só lado, abertas pelos quatro tickets inscritos depois do KAM-144. A **lacuna 17** passa a nomear também o 3c: entra nos `needs` de `gates do KAM-002` e não no `main.json`, porque escrever no espelho o que o *ruleset* não tem tornava-o falso. | Equipa KAMBÁ |
| 1.35 | Outubro 2026 | **KAM-009: a superfície 3 passa a ler duas formas.** Um `registry/*.yaml` é uma **vertical** (chave de topo `id`) ou os **planos** (chave de topo `plans`), e a forma lê-se pela chave e nunca pelo nome do ficheiro; as chaves de topo de cada forma são listas fechadas, cada nome de limite é confrontado com as dez chaves do dicionário §3.2 nas duas, e um ficheiro que não seja **nenhuma** das duas falha. A superfície deixa de estar vazia (`registry/plans.yaml`, com `estado: hipotese_nao_validada` por entrada) e a frase «A SUPERFÍCIE AINDA NÃO EXISTE» deixa de aparecer para ela. Corrigido de passagem: `ManualProvider`, que a linha «Entitlement (chaves)» escreve em prosa e o exportador colhia, era aceite como nome de limite — o lint passa a exigir a forma `^[a-z][a-z0-9_]*$`, a mesma do `CHECK` de `tenant_usage.chave_limite`. | Equipa KAMBÁ |
| 1.36 | Outubro 2026 | **KAM-009: o *gate* 8 passa a correr sete *suites*.** A sétima é `tests_ten`, que prova a **função** `platform.ten_consumir` da revisão `0007` e não o esquema: mil chamadas paralelas de 1 unidade contra um tecto de 100 em 32 ligações — **100 aceites, 900 negadas, contador final 100, e o livro de idempotência com 100 linhas e não mil** —, as dez repetições do critério 4 mais o caso que o critério não pede (uma recusa não pode gastar a chave, nos dois caminhos de recusa), a fronteira do mês com relógio fixo nos dois instantes do critério **e** num instante que cai em meses diferentes em UTC e em `Africa/Luanda`, e o isolamento da função — que o *gate* 6 não prova, porque a política de uma tabela não diz o que uma função `SECURITY INVOKER` faz quando quem a chama é outro tenant. O *gate* 6 ganha as receitas de sementes das duas tabelas novas, sem as quais se recusava a correr, e `entitlements` passa a ser uma tabela que `kamba_app` **não altera** (a `0007` revogou-lhe o `UPDATE`). Quinze mutações novas. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.37 | Outubro 2026 | **KAM-009 reprovou na revisão adversarial, e o *gate* 8 passa a morder onde ela mordeu.** Três críticos, nenhum apanhado pelos 47 testes nem pelas 15 mutações que havia: a chave de idempotência valia para **todas** as chaves de limite e não olhava à quantidade (repetir a chave de um consumo de uma mensagem autorizava um pedido de 999 999,99 Kz contra um tecto de 50 000, sem contar); `kamba_app` mantinha `INSERT` em `entitlements`, e com `WITH CHECK (tenant_id = app.tenant_id)` o tenant **criava** o próprio tecto; e `GRANT UPDATE (valor)` em `tenant_usage` deixava-o **zerar** o próprio contador. A revisão `0007` ganha a `chave_limite` na chave do livro, a comparação da quantidade (`KA002`), o `REVOKE INSERT`, e o *trigger* `tenant_usage_so_sobe` — o padrão do `audit_log_imutavel` da `0006`: o que o privilégio por coluna não sabe exprimir, exprime-o um `BEFORE UPDATE`. Mais o `UPDATE (tenants.estado)` revogado (um tenant `suspenso` reactivava-se e retirava a condição do critério 2), o `p_agora` fechado a quem não é `kamba_batch`, e quatro erros que escapavam aos tratadores (`22P02` de um limite não inteiro, `22003` de transbordo, chave de idempotência vazia, aviso de ordem das chaves no `COMMENT`). A *suite* `tests_ten` ganha o `test_escalada.py` — o atacante é o **próprio** tenant, que é o caso que a RLS nunca podia parar — e passa a correr o `SQL_CONSUMIR` e o `SQL_PERIODO` **das bibliotecas** em vez de uma cópia deles, o que destapou um defeito real: o `SQL_PERIODO` não tinha `coalesce` e devolvia `NULL` sem instante. Mutações: 256 → **270**. | Equipa KAMBÁ |
| 1.38 | Outubro 2026 | **KAM-013: o *gate* 8 passa a correr nove *suites*.** As duas novas são `tests_entrada` e `tests_entrada_carga`, e a diferença face a todas as outras é o que elas lançam: os **processos de produção** (`services/gwy/src/server.ts` e `services/worker-canal/src/entrada.ts`), sem programa de ensaio pelo meio — porque o que há para provar é o comportamento de um servidor HTTP com uma fila a sério. O que só aqui se mede: o 200 com o *job* **já** na fila, o 503 com o contentor da fila parado (e o mesmo processo a voltar a aceitar sem reinício), a mesma mensagem em dois corpos a deixar **uma** linha, e um corpo ilegível a dar 200 e quarentena em vez de começar sete dias de re-entregas. **A assinatura calcula-se em Python**, que é uma segunda implementação: mede-se interoperabilidade e não auto-consistência. E os domínios de `kind` e `motivo` comparam-se com **três** fontes — o `CHECK` do PostgreSQL, o dicionário exportado e a lista do módulo TypeScript. A *suite* apanhou **três defeitos que nenhum teste unitário apanhava**: o `backoffStrategy` que faltava no *worker* (todos os *jobs* levam `backoff: custom` do `addLote`, e um *worker* que o não registe lança ao calcular o atraso — o *job* ficava em `failed` sem passar pela quarentena); o `SELECT` por coluna que o `ON CONFLICT (kind, event_key)` exige em `unrouted_events` (a mesma lição que a `0005` já escrevera para o `events_dlq`); e um *job* falhado a não deixar **linha nenhuma** de registo, porque o BullMQ nada escreve quando ninguém ouve o acontecimento `failed`. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.39 | Outubro 2026 | **KAM-014: o *gate* 8 passa a correr dez *suites*.** A décima é `tests_chr`, e é a primeira que abre **três ligações com três papéis** — `kamba_resolver`, `kamba_identity` e `kamba_app` —, porque a resposta à pergunta do CHR depende do papel: a mesma consulta devolve **zero linhas** com `kamba_app` sem contexto e uma com o resolvedor, e é isso que torna o papel necessário e não conveniente. O que só aqui se prova está no §3: o `phone_number_id` de A nunca devolve o contexto de B (propriedade da chave única e da política, não do código), a convergência de identidade **e o seu limite**, o gancho de fusão nos dois casos, a guarda do ADR-011 a recusar-se a correr com um papel que não vê tudo, e a ausência de `UPDATE (mode)` para a aplicação. O estrato `critico` ganha `*/chr/*` e o `chr/fila.ts` entra nos `excluidos`. O *gate* 6 ganha a receita de sementes da `conversations` — a primeira tabela isolada **sem coluna de texto livre**, com o canário na chave primária —, e a descoberta do X-05 passa de dezasseis tabelas a **dezassete**. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.40 | Outubro 2026 | **KAM-024: a parte dos *webhooks* do *gate* 7 passa a existir.** O alvo `ci-7-meta` corre o *scan* de telefones, o relatório de cobertura dos 33 itens (16 tipos, 11 campos e 6 motivos) e a *suite* offline, incluindo a ida e volta das 32 *fixtures* assinadas contra o GWY do KAM-013. **24 s**, contra os ≤ 5 min da *proposta*. Três coisas que não são transcrição: os códigos de saída são **três** e não dois, porque «0 ficheiros lidos» não é «0 achados» — a armadilha que o `lint_contagens` já mordeu; o *scan* confronta o repositório com um **inventário** por ficheiro, com contagem exacta e razão, e não com uma pasta isenta, porque uma pasta isenta deixava passar um número novo dentro de um ficheiro já tolerado; e o `tools/meta-sim` entra em `PACOTES_NODE`, sem o que o `coverage_gate` injectava os seus dezasseis ficheiros a 0% — e o `base_do_nome` ganha a família `tools`, sem a qual os mesmos dezasseis saíam como «medidos e não classificados», que é o estado em que um ficheiro escapa ao limiar em silêncio. A *suite* **online** continua por fazer e depende de `ext:KAM-102`. | Equipa KAMBÁ |
| 1.41 | Outubro 2026 | **KAM-015: o *gate* 8 passa a correr onze *suites*.** A décima primeira é `tests_outbound`, e é a primeira que junta o PostgreSQL ao servidor Graph falso do KAM-024 — porque o critério 2 pede «1 chamada à API (servidor falso conta) **e** 1 linha em `outbound_messages`», e nenhum dos dois prova a metade do outro. O que só aqui se prova está no §3: a idempotência (é da base, pelo `ON CONFLICT ... RETURNING` vazio), a unicidade **por tenant** da chave, a monotonia sob concorrência **real** (duas ligações, que é o que torna a corrida verdadeira), o X-03 sobre as duas tabelas novas e o custo por *tenant* a sair da tabela em vez de uma etiqueta de métrica. A cobertura de `src/outbound/` mede-se aqui, contra o estrato **`restante`** e não o `critico`: o DoD não dá número e alterar `ci/thresholds.yaml` pede dois revisores. O *gate* 6 ganha as receitas de sementes da `outbound_messages` e da `message_templates`, e a descoberta do X-05 passa de dezassete tabelas a **dezanove**. **E o `pnpm-workspace.yaml` ganha `ignoreWorkspaceCycles: true`**, sem o que o `pnpm -r run typecheck` do *gate* 2 recusa correr: o `@kamba/core-ts` e o `@kamba/meta-sim` dependem um do outro em desenvolvimento — o simulador lê o vocabulário de campos do `core-ts` em vez de o reescrever, e os testes da saída usam o `GraphFalso` para contar as chamadas HTTP, que é metade do critério 2. O que a declaração troca é a **ordem** das tarefas, não uma garantia: o fecho de produção dos dois é zero e o oráculo do `pnpm list --prod` mede-o a cada PR. E o erro de ciclo abortava o passo **antes** do `tsc`, pelo que escondia um segundo defeito — um `bd.query` de ensaio sem parâmetro de tipo. Quatro defeitos que só uma máquina apanhou: o `set_config(..., true)` solto — «local à transacção», pelo que o contexto morria antes da instrução seguinte e o `kamba_app` com `FORCE` via zero linhas (a *suite* caiu de 421 s para 33 s); a `outbound_messages_entrega_ck` a matar um `failed` depois de um `delivered`; a limpeza do ensaio a apagar conversas antes das mensagens que lhes apontam; e a `outbound_rate_limited_total` a somar a nossa travagem com a da Meta sob uma ajuda escrita que dizia só a primeira. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.42 | Outubro 2026 | **KAM-019: o *gate* 8 passa a correr doze *suites*.** A nova é `tests_handoff`, e é da mesma classe do `tests_outbound` — não corre os testes, corre a **saída** deles: as cinco baterias do *gate* 4 e o ensaio de base produzem TAP, e cinco asserções Python confirmam que cada grupo apareceu, que cada teste obrigatório passou **pelo nome**, e que a cobertura de cada um dos dez ficheiros de `src/hnd/` está acima do limiar, porque um *gate* que conte testes não nota que um desapareceu. O que só aqui se prova está no §3: a idempotência é da **chave primária** com o `handoff_id` derivado de `hash(thread_id, ordinal)` — cinco aberturas concorrentes em duas ligações, uma linha e uma chamada ao provedor; a `handoff_accounts_conta_uq` a recusar com `23505` a mesma conta do provedor em dois *tenants*, que é o lado do isolamento que nenhuma verificação em código apanha; o `close` duplicado como *no-op* da base, com as métricas dos dois a somar **uma** passagem fechada; o X-03 sobre as duas tabelas novas, escrita incluída, que com `FORCE` falha mesmo como dono; e uma passagem `degraded` a contar no SLA. O *gate* 6 ganha as receitas de sementes das duas tabelas, e a descoberta do X-05 passa de dezanove para **vinte e uma**. **Dois defeitos que só uma máquina apanhou, e o segundo é deste *gate*:** a bateria do critério 6 **pendurou** — dezasseis minutos a 99% de CPU, que nenhum relatório de testes mostrou porque nenhum chegou a sair, e que um `docker top` mostrou — porque montava o `Saida` verdadeiro com o relógio congelado e um `dormir` que não fazia nada, e o *token bucket* do KAM-015 espera pelo primeiro token comparando `agora()` com o instante em que começou, pelo que nem a espera nem a recusa por `ESPERA_MAXIMA_DE_DEBITO_MS` terminavam; e a *suite* ficou verde com essa bateria **sem a correr**, porque o `node --test` apanhava-a pelo *glob* e a lista de ficheiros que o CI usa não a tinha — o `resposta.ts` também não estava nos módulos medidos, pelo que nem a cobertura o denunciou. As duas listas continuam explícitas e não um *glob*: um *glob* nunca falha por esquecimento, e é isso que o torna pior. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.43 | Outubro 2026 | **KAM-019: a `tests_handoff` ganha quatro grupos e quatro testes obrigatorios, e a razao e que o spike correu.** O veredicto foi `O TOKEN DO BOT CHEGA`, e no caminho ate la o spike mediu quatro coisas que a implementacao fazia de outra maneira — pelo que as baterias cresceram de 89 para **108** testes e a *suite* passa a exigir pelo nome, entre outros, «o inbox e criado com o token do UTILIZADOR e nao da plataforma» e «o set_agent_bot existe, e sem ele nada funciona». O `resposta.ts` entra nos modulos medidos (dez agora). **E a prova por mutacao do modulo correu pela primeira vez, com quatro sobreviventes que nao eram testes em falta:** duas mutacoes eram **imortais** (uma apagava uma linha redundante, outra trocava `timingSafeEqual` por `===` num ponto onde as duas dao o mesmo resultado — essa foi retirada, e a limitacao de tempo constante fica **dita** em vez de fingida); o `ON CONFLICT` da conta **nao era exercitado** por caminho nenhum, porque duas chamadas sequenciais usam o caminho rapido; e uma das duas unicidades passava por causa da outra, com a assercao a aceitar qualquer «duplicate key». Depois das correccoes: **26 corridas, 0 nao apanhadas**. O `supply_chain` pediu `read_only: true` nos quatro servicos do compose do spike e as quatro listas de saidas, todas **vazias** com `por_omissao: negar`. Sem *job* novo. | Equipa KAMBÁ |
| 1.44 | Outubro 2026 | **KAM-020: o *gate* 8 passa a correr treze *suites*.** A nova é `tests_media`, e é da classe do `tests_outbound` e do `tests_handoff` — não corre os testes, corre a **saída** deles: três baterias do *gate* 4 e um ensaio de base produzem TAP, e cinco asserções Python confirmam **dezasseis** grupos e vinte e dois testes obrigatórios **pelo nome** (a primeira versão desta entrada dizia treze grupos e os obrigatórios eram vinte e quatro; a revisão adversarial contou, e a lista de grupos tinha três em falta — dois deles do único ficheiro que fala com o PostgreSQL), e a cobertura de seis ficheiros de `src/med/` (89% a 100%, contra o limiar de 75% do estrato `restante`). **O ensaio de base existe pela lição do KAM-019:** uma base falsa nunca lê o texto do SQL, pelo que qualquer mutação dele sobrevive — e o que só aqui se prova é o `ON CONFLICT` da reserva **sob concorrência** (em série a segunda chamada nem chega ao `INSERT`), a monotonia do `WHERE estado = 'pendente'`, a `media_assets_armazenado_ck` a recusar pelo caminho do código, o X-03 sobre a tabela nova, e que nenhum URL da Meta chega à base. O *gate* 6 ganha a receita de sementes da `media_assets`, e a descoberta do X-05 passa de vinte e uma para **vinte e duas** tabelas. **Não corre contra simulador nenhum, e é decisão:** a API de mídia da Meta não tem evidência nenhuma no `E1`, e um simulador dela fingiria medição. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.45 | Outubro 2026 | **KAM-023: o *gate* 8 nao ganha *suite* nova, ganha cinco propriedades na `tests_outbound`.** O contador do *free tier* vive em `packages/core-ts/src/metering/` e nao cria DDL — as duas colunas que mantem nascem na `0001` —, mas escreve `tenant_channels` e le `outbound_messages`, e as propriedades que **so** uma base prova nao tinham onde correr: a fronteira de mes a meia-noite de `Africa/Luanda` (dois instantes a uma hora de distancia que caem em meses diferentes em Luanda e no mesmo mes em UTC, com o fuso a vir da `platform.ten_periodo` da `0007`), o flanco do aviso sob concorrencia real em duas ligacoes (um aviso e nao dois, pelo `FOR UPDATE`), a idempotencia por `wamid` com o adapter ligado, o X-03 sobre `tenant_channels` nos dois sentidos, e a reconciliacao sobre o `pricing` `jsonb`. **Dois defeitos que so uma maquina apanhou:** o driver `pg` converte uma coluna `date` num `Date` a meia-noite **local do processo**, pelo que o mes voltava com um dia de erro em qualquer fuso a oeste de Greenwich e certo no CI, que corre em UTC (passou a `to_char`, que tambem nao depende do `DateStyle` da sessao); e a reconciliacao recebia o periodo em instantes, o que deixava comparar o contador do mes corrente com as entregas de outro e punha as fronteiras em UTC — o periodo passou a exprimir-se pela propria funcao do fuso. A bateria de unidade do modulo entra na lista da *suite* pela **prova por mutacao** e nao pela cobertura: as mutacoes nas funcoes puras so por ela sao apanhadas. A cobertura de `src/metering/` continua a medir-se no *gate* 4, porque o filtro desta *suite* e `/src/outbound/`. Sem *job* novo: o `esperados` do resumo nao muda. | Equipa KAMBA |

| 1.46 | Outubro 2026 | **KAM-023, a segunda metade: a `tests_outbound` ganha a sexta propriedade e a suite `tests` ganha o `downgrade` da `0013`.** A revisao deixou de estar bloqueada quando o KAM-020 fundiu a `0012` — as revisoes de base encaixam uma na anterior pelo `down_revision`, e duas a reclamar o mesmo pai nao sao colisao mecanica: o Alembic recusa. O que entra: a marca de `motivo_restricao`, o conjunto `meta_error_codes_seen`, e o `channel.updated` a cair no `events_outbox` por `platform.evt_emitir` (o envelope constroi-se em SQL, regra do KAM-005 e do ADR-009). **Uma mutacao foi escrita e descartada por ser imortal:** apagava o `REVOKE`/`GRANT` que o `downgrade` fazia antes do `DROP COLUMN`, e nenhum teste a podia matar — o PostgreSQL remove a concessao **com** a coluna. As duas instrucoes sairam da revisao, e o teste do `downgrade` continua a provar a propriedade. **E o `--aplicaveis` apanhou um defeito que o `git merge` produziu sem conflito nenhum:** o KAM-020 e este ticket escolheram ambos a constante `MED_SQL` em `db/mutacoes.py`, e a minha, por vir depois, sombreou a dele — duas mutacoes da midia passaram a apontar para o ficheiro do free tier, sem nenhum teste o ver. As minhas passaram a `FT_*`. Sem *job* novo: o `esperados` do resumo nao muda. | Equipa KAMBA |
| 1.47 | Outubro 2026 | **KAM-021: o *gate* 8 nao ganha *suite* nova, ganha cinco propriedades na `tests_outbound` e a revisao `0014` na `tests`.** A gestao de canal vive em `packages/core-ts/src/qualidade/` e entra nesta *suite* pelas mesmas razoes que o contador do KAM-023 — escreve `tenant_channels`, le `outbound_messages`, usa o mesmo `apoio.ts` — e por uma quarta que so vale para ela: **o criterio 9 prova-se de ponta a ponta**, com a `Saida` do KAM-015 a recusar um template num canal que a bateria da qualidade acabou de restringir, e isso precisa do `GraphFalso` do KAM-024, que **so esta *suite* monta**. O que so aqui se prova esta no §3: a idempotencia da transicao sob concorrencia real (o indice unico e que decide, e a chave e composta com o `tenant_id`), o **`42501`** de um `UPDATE` que nao existe na tabela nova — com a metade positiva a provar que o `SELECT` e o `INSERT` funcionam, sem a qual uma concessao em falta por inteiro passava as duas negativas —, a regra de que cada ticket levanta so o motivo que poe (nos **dois** sentidos, o `SQL_REPOR` e o `COALESCE` do `SQL_RESTRINGIR`), a medicao do escalao com `count(DISTINCT)` e 24 h **moveis**, e o criterio 9 de ponta a ponta. O *gate* 6 ganha a receita de sementes da `channel_quality_log`, e a descoberta do X-05 passa de vinte e duas para **vinte e tres** tabelas. **Dois defeitos que so uma maquina apanhou, e o segundo e do proprio teste:** o nome `max_phone_numbers_per_business` contem «phone» e dispara a lista fechada de colunas de telefone do `test_catalogo.py` (declarou-se, com a razao de que num `integer` nao cabe um E.164 — garantia mais forte do que a do `phone_number_id`, que e `text`), e descer de `head` para a `0011` passa agora pela `0014`, que compromete **antes** de a `0012` recusar, pelo que a assercao do `downgrade` da midia mudou de `TABELAS` para `TABELAS_ATE_0013`; e o grupo do criterio 9 passava **pela razao errada** — o `tenants.estado` nasce `onboarding`, que e mais restritivo do que `restrito`, pelo que as tres asserções de `STATE_REFUSED` teriam passado com o canal `ativo`. Ganhou um `before` que poe o *tenant* `ativo` e um teste de **controlo**. O `TEMPO_MAXIMO` da *suite* sobe de 900 para 1 200 s: ela ganhou quatro ficheiros em dois tickets e corre com `--test-concurrency=1`, pelo que os tempos somam. Sem *job* novo: o `esperados` do resumo nao muda. | Equipa KAMBA |
| 1.48 | Outubro 2026 | **KAM-022: o *gate* 6 ganha a primeira vista do esquema e a `tests_outbound` ganha cinco propriedades.** A revisao `0015` cria duas tabelas — a `consent_event` (prova *append-only*) e a `consent_texts` (o texto do aviso, **sem `tenant_id`**: e um texto juridico de plataforma e nao dado de *tenant*, pelo que nao entra no X-05 nem no `../ci/rls_exceptions.yaml`, que continua com uma entrada so) — e **a `consent_actual`, a primeira vista**. O `verificar_vistas` do catalogo do X-05 existe desde o KAM-004 a exigir `security_invoker = true` sem lista de excepcoes, e **nunca tinha tido nada para ver**: sem a opcao, uma vista corre com os privilegios do dono e a RLS passa a depender do `FORCE`. A descoberta do X-05 passa de vinte e tres para **vinte e quatro** tabelas e ganha receita de sementes para a prova. O que so a `tests_outbound` prova esta no §3: a idempotencia pela **propria prova** sob concorrencia real, a vista a respeitar a RLS pelo caminho do modulo, o **`42501`** de um `UPDATE` que nao existe (com a metade positiva), a contagem de avisos pelo prefixo da chave de idempotencia — que nao acrescentou DDL —, e a versao vigente a excluir as futuras. **Quatro ripples que a primeira vista do esquema produziu, e nenhum estava previsto:** o `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` descobria pelo `information_schema.columns`, que inclui as colunas das vistas, e uma vista nao tem indice nem `NOT NULL` (passou a filtrar `table_type = 'BASE TABLE'`); o `_tabelas` do `test_media_schema.py` era o unico dos tres que nao filtrava e passou a devolver uma relacao a mais; o inventario ganhou a vista como entrada **derivada** da tabela, com as tres colunas que ela nao mostra declaradas e com a razao de cada uma; e o dominio de `consent_texts.purpose` precisou de ser declarado **outra vez** no dicionario, porque os dominios dele sao qualificados pela coluna (emenda 1.14) — nove achados `fora-do-dicionario` a primeira volta. **E dois defeitos que so uma maquina apanhou, os dois do ensaio e nao do esquema:** a bateria inventou um `excepcao.sqlstate` que o `pg8000` nao tem (o codigo vem no campo `C` da mensagem do servidor, e o `db/tests/base.py` ja tinha o ajudante e os nomes) — dezasseis erros —, e a metade positiva do *append-only* contava linhas que a sessao da aplicacao nao podia ver, porque a ligacao do `ComBase` nunca confirma. **E um terceiro que o CI apanhou e eu nao, e e a licao deste documento:** declarar `consent_event.canal ∈ {whatsapp}` no dicionario fez o *gate* 3b passar a **exigir** um `CHECK` fechado nessa coluna em qualquer revisao que a crie, e a *fixture* **positiva** do canario do `canon_lint` criava-a sem ele. Eu corri as duas primeiras linhas do alvo `ci-3b` — o `dict_export --check` e o `canon_lint check` — e nao a terceira, o `canon_lint canario`; e ela derruba tambem o *gate* 4, porque o `test_o_canario_esta_verde` corre o canario dentro dos testes de unidade. **Correr a funcao de um gate nao e correr os testes dele**, e e a terceira vez que este conjunto paga essa licao. Sem *job* novo: o `esperados` do resumo nao muda. | Equipa KAMBA |
| 1.49 | Outubro 2026 | **KAM-018: o *gate* 8 passa a correr catorze *suites*.** A nova é `tests_modos`, e é a primeira que abre **três** ligações do **mesmo** papel: um `pg_advisory_xact_lock` só é exclusão mútua entre sessões diferentes, e o `comTenant` do `tenant_guard` recusa dois usos concorrentes da mesma ligação — com uma, as duas transacções sairiam em série e o ensaio provava que o JavaScript é sequencial. O que só aqui se prova está no §3: a guarda a **bloquear** à porta de uma transição em curso (medido: não resolve depois de 150 ms com a transacção aberta); duas transições concorrentes a deixarem **uma** transição e **um** evento pelo predicado `antes.mode = ANY(...)` sob `FOR UPDATE`, e não por quem leu primeiro; as 100 intercalações do critério 3 com semente **fixa** e corridas **duas vezes** para o provar (46 com o *echo* primeiro, 0 enviadas); o relógio das 24 h a contar do `handoffs.opened_at` quando não houve actividade humana, que é um `COALESCE` com subconsulta e um `max` sobre a tabela do KAM-019; e o `GRANT UPDATE (mode, last_human_activity_at)` da revisão `0016` a existir e a ser **por coluna**, com as quatro da identidade da conversa ainda vedadas. O estrato `critico` ganha `*/modos/*` — **e isso pede dois revisores que esta alteração não tem**, o que fica dito aqui, no comentário do `ci/thresholds.yaml` e na verificação do ticket. **Três mutações foram escritas, corridas e removidas**, as três por apagarem código inalcançável: duas guardas do `transicoes.ts` que nenhuma célula da tabela podia accionar — e a resposta foi **apagar as guardas** e afirmar o invariante num teste, porque uma guarda inalcançável dá a ilusão de proteger — e o `validarPayload` do evento, cuja precondição nenhum caminho alcança hoje; a chamada fica (é a regra do KAM-007) e o que a protege é um teste de paridade entre o que se monta e o que o contrato exige. **E três mutações sobreviveram e viraram testes:** o `FOR UPDATE` da transição, que só se mata correndo o SQL **sem** o *advisory lock*, e as duas escritas monótonas de `last_human_activity_at`, que só se matam com um *echo* fora de ordem — o caso real, porque a Meta não garante ordem nos *webhooks*. Sem *job* novo: o `esperados` do resumo não muda. | Equipa KAMBÁ |
| 1.50 | Outubro 2026 | **KAM-016: o *gate* 8 ganha sete propriedades na `tests_outbound` e a revisao `0017` na `tests`.** A revisao e a **`0017`** e nao a `0016` porque o KAM-018 reclamou aquele numero e chegou primeiro ao remoto — e a dele **nao cria tabela nenhuma**, pelo que o `TABELAS_ATE_0016` do `db/tests/base.py` tem as mesmas tabelas que o `TABELAS_ATE_0015` teria. O onboarding de canal vive em `packages/core-ts/src/onboarding/` e entra nesta *suite* pelas razoes dos tres tickets anteriores — escreve `tenant_channels`, usa o mesmo `apoio.ts` e os mesmos papeis — e por uma que nao tinha alternativa: **«0 subscricoes no WABA» le-se no `GraphFalso` do KAM-024, e esta e a unica *suite* do *gate* 8 que o monta.** A descoberta do X-05 passa de vinte e quatro para **vinte e cinco** tabelas e ganha receita de sementes para a tentativa de onboarding, com o canario no `waba_id` (a unicidade dele leva o `tenant_id`, pelo que os dois *tenants* podem semear o mesmo valor; o `phone_number_id` nao servia, porque a unicidade **dele** e global). **Tres defeitos que a maquina apanhou e eu nao, e os tres antes de a base entrar:** o cliente da Graph mandava o *code* e o `client_secret` no corpo `form-urlencoded`, pela RFC 6749 §4.1.3, e o `#trocarCode` do `GraphFalso` le `pedido.consulta.code` e responde `400` a quem nao o ponha la — alargar o simulador era passar a provar o cliente contra uma superficie alargada para lhe servir, pelo que se seguiu o simulador e a exposicao ficou **declarada** no `graph.ts`, no dicionario §3.20 e no `onboarding-canal.md` §6; a procura por «v2/v3» do criterio 1 estava escrita como `["']?[^3"']` e dava achado em `sessionInfoVersion: "3"` — o `["']?` casava vazio e o `[^3"']` casava a propria aspa —, pelo que o teste media a ortografia do canon e nao o codigo; e um `graph.ouvir()` a mais num teste ficou sem `fechar()` e o `node --test` **nunca terminou**, porque o processo tinha um socket a escuta. **E dois que o *gate* 3b apanhou, os dois da emenda:** declarar o dominio como `channel_onboarding.recursos_criados[].recurso` fez o `dict_export` colhe-lo como dominio da **coluna** `jsonb` e o gate exigiu-lhe um `CHECK (recursos_criados IN (…))` que ela nao pode ter — passou a `RecursoCriado.recurso`, qualificado pelo tipo, que e a correccao que a emenda 1.22 ja fez duas vezes; e o `waac_id` passou a ser nome do §3.20 e a extensao `tenant_channels.waac_id` ficou **redundante**, como o `token_ref` na emenda 1.22 (25 extensoes, eram 26). O `ci/thresholds.yaml` ganha **um** padrao — `*/onboarding/cifra.ts` no estrato `critico`, medido a 94,8% —, e o resto do modulo fica no `restante`, como o `qualidade/` e o `consentimento/`. Sem *job* novo: o `esperados` do resumo nao muda. | Equipa KAMBA |
| 1.51 | Outubro 2026 | **KAM-017: o *gate* 8 não ganha *suite* nova, ganha três ficheiros e doze grupos na `tests_outbound`, e a revisão `0018` na `tests`.** A coexistência vive em `packages/core-ts/src/coexistencia/` e entra naquela *suite* por uma razão que não é a dos quatro tickets anteriores: **ela lê `outbound_messages`**, que é a tabela daquela *suite*, e é dessa leitura que sai a regra do critério 7 — «um *echo* cujo `wamid` consta de `outbound_messages` é ignorado como actividade humana». Não há onde provar isso sem as duas tabelas na mesma base. Uma *suite* própria custava um ficheiro de arranque, um alvo no `Makefile`, uma entrada em `db/gate_bd.py`, outra em `db/correr_suite.py` e uma entrada em `ci/supply-chain/imagens.yaml` para levantar o mesmo PostgreSQL. **Os dois ficheiros de unidade entram pela prova por mutação**, pela razão que o `metering.test.ts` escreveu: as mutações na tradução dos seis motivos, na decisão do 2593109, nos três desfechos do *echo* e no `COALESCE` do aviso só por eles são apanhadas. O *gate* 8 passa a correr **602** mutações (eram 570), **32** delas deste ticket — quatro da revisão e 28 de código. **O *gate* 6 ganha a receita de sementes da `channel_coexistence`** e a tabela entra na descoberta do X-05, que passa a **vinte e seis**; o `apagarTenant` do `tests_bd/apoio.ts` aprende a oitava tabela, e a nota que a sétima deixou lá escrita previu-a por extenso. **O *gate* 2 e o 3b não mudam de forma**, mas este ticket pagou-lhes uma lição que vale para quem vier: um valor de lista fechada que vá ao `outcome` de um registo confronta-se com o `logger/politica.ts` **antes** — os seis motivos de `PARTNER_REMOVED` vão em minúsculas por isso, e o código 2593109 **não pode ser registado de todo**, porque tem sete dígitos e o `DIGITOS_MAXIMOS` é seis. | Equipa KAMBÁ |

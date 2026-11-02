# ANALISE-47 — KAM-170: o portão para as citações de secção (`§N`)

| Campo | Valor |
|---|---|
| Ticket | KAM-170 — as citações de secção passam a resolver-se por máquina, dentro do *gate* 3 |
| Ramo | `feature/KAM-170-citacoes-de-seccao` |
| Base | `refs/remotes/publico/main` em `9c5fa60` |
| Método | Revisão adversarial por um subagente `general-purpose` que recebeu **o diff e os requisitos**, e **não** o raciocínio do autor |
| Achados | 10 levantados — **8 CONFIRMADO**, **1 PLAUSÍVEL**, **10 MORTO** (dos quais 2 mortos pela correcção feita durante a revisão) |
| Veredicto | «Não fundiria sem resposta» a quatro. Os oito confirmados estão corrigidos; o plausível está escrito |
| Estado | Vivo |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

---

## 1. A medição que importa mais

**O portão foi escrito com honestidade sobre o que não fecha, e com números
errados sobre o que faz.** As duas metades vêm da mesma causa — o módulo
argumenta que «um número escrito é uma afirmação verificável» e os números que
ele próprio escrevia não tinham sido medidos com o módulo entregue, mas com um
protótipo e com `grep`s de outro corpus. A revisão foi medi-los um a um:

| O que o módulo afirmava | O que a árvore diz |
|---|---|
| «**nove** citações que não resolvem» | o portão reporta **dez**; onze a contar a dispensada por área |
| «em **3 629** endereçáveis» | **4 500** no corpus que o portão varre |
| «as **onze** citações» para documentos sem títulos numerados | **30** — e só 25 vão para os *stubs* nomeados |
| «`#### 7.6.2` existe **três vezes**» | **zero**; os três títulos de três níveis são `8.3.1`, `8.3.2` e `5.3.1` |
| «`docs/tecnica/0` casa **seis** ficheiros» | dez antes da fronteira do prefixo, **zero** depois |
| «a passagem custa **3,7 s** sobre uma base de 11,7 s» | +2,5 s sobre 4,4 s aqui, +7,55 s sobre 4,67 s na medição independente |

Nenhum destes números mudava uma decisão de desenho; todos foram corrigidos, e
o que **não** se reconcilia — o custo — fica escrito com as duas medições e sem
figura precisa, em vez de com um número que nenhuma delas sustenta.

**E a segunda medição que importa: dois defeitos reais de desenho, nenhum dos
quais tinha instância na árvore no dia em que foi escrito.** O portão nasceu com
dois pontos cegos que o deixavam prometer mais do que fazia — os blocos de
*handoff* e a mudança de linha. Os dois foram encontrados por quem não escreveu
o código.

---

## 2. Os achados, por gravidade

### A-02 — CONFIRMADO — bloqueio — Os blocos de *handoff* estavam fora do portão

**Onde.** `tools/lint_refs/seccoes.py`, a condição 3 (saltar blocos cercados),
contra a abertura do mesmo *docstring*, que nomeia o bloco de *handoff* como o
caso que motiva o portão.

**O que estava errado.** O bloco de *handoff* é cercado **por construção** — são
170 blocos em 65 ficheiros, todos dentro de ``` ``` ``` —, e é o **único** sítio
do conjunto onde um `§N` dá uma **ordem** a quem executa a seguir. A ocorrência
que motivou este ticket vivia exactamente ali: «NÃO apagues a linha de risco do
§12», dentro da cerca de `specs/tickets/KAM-169.md`. A condição 3 saltava-a.

**Evidência (do revisor, reproduzida).** A mesma linha, só a mudar se está dentro
da cerca:

```text
canário com §99 DENTRO do bloco de handoff → saída 0
a mesma linha FORA do bloco               → saída 1
```

**Porque é o mais grave dos dez.** Não é um buraco de cobertura: é o portão a
nomear um caso como a sua razão de ser e a não o ler. Mesmo que o §12 não
existisse, a ocorrência do *handoff* passava.

**Correcção.** Varrem-se os blocos de *handoff*, com a detecção **importada do
`lint_handoff`** — que já entra neles para resolver caminhos — em vez de uma
gramática própria: `blocos` passa a público, pela razão com que o KAM-138 tornou
público o `LINHA_BACKLOG` do `lint_refs`. Duas leituras de «o que é um bloco de
*handoff*» era a forma garantida de os dois passos do *gate* 3 discordarem sobre
o mesmo bloco. Preso por quatro testes, incluindo o controlo que mostra que era a
cerca que a escondia e o que confirma que uma cerca comum continua de fora.

**Os 170 blocos estão limpos hoje** — o portão sai 0 sobre eles —, o que é
informação e não dispensa: o ponto cego fecha antes de a primeira ocorrência
aparecer, e não depois.

---

### A-03 — CONFIRMADO — relevante — Uma citação partida por mudança de linha escapava

**Onde.** `specs/EPIC-03_Agent_Runtime_Verticais.md:391-392`.

**Evidência.** O designador fecha a 391 e o `§` abre a 392:

```text
391: … E o `../docs/tecnica/06`
392: §7.6.2 diz que os *checkpoints* são cifrados com a DEK do contacto …
```

O `docs/tecnica/06` tem `### 7.6` e **não tem 7.6.2** — é a **gémea exacta** da
citação que este PR corrige em `specs/02_Dicionario_de_Dados_Canonico.md:1186`, a
uma mudança de linha de distância, e o portão saía 0 com ela. O revisor mediu a
cegueira: **77 citações endereçáveis** perdidas por mudança de linha, uma delas
defeituosa.

**Porque não é exótico.** A prosa deste conjunto muda de linha a ~80 colunas em
todos os documentos. Era uma classe, não um acidente.

**Correcção.** Varre-se a **fronteira entre duas linhas**, aceitando só os pares
que a atravessam, sem repetir o que cada linha já deu, e sem atravessar uma linha
vazia — que separa parágrafos, e juntar através dela emparelharia um documento de
um parágrafo com um `§` do seguinte. O achado é atribuído à linha onde o `§` está
escrito, que é o token a corrigir.

---

### A-07 — CONFIRMADO — relevante — A condição 2 isentava mais do que dizia, e escondia um `§` quebrado

**Onde.** A razão escrita da condição 2 («é um *stub* de um documento que vive
noutro repositório») contra o que ela fazia.

**Evidência.** Das 30 citações isentas, **oito** iam para documentos que não são
*stub* de nada — três para `docs/adr/ADR-L002-injeccao-de-segredos.md`, que é um
ADR **deste** repositório, e cinco para ficheiros de `docs/analises/`. O ADR-L002
numera a sua última secção assim:

```text
## §6 — Quando reverter, e o que falta nesta porta
```

O padrão do título não lia o `§`, pelo que `numeros_de_seccao` devolvia vazio e o
**documento inteiro** ficava inendereçável. Consequência medida:
`libs/py-core/src/kamba_core/secrets/port.py:14` citava o `ADR-L002` **§5**, e o
ADR-L002 não tem §5 nenhum — um falso negativo da classe exacta do ticket, tapado
por uma condição cuja razão escrita não se aplicava ali.

**Correcção.** O `§` no título passa a ser opcional (`^#{2,4}\s+§?N…`), o que
torna o ADR-L002 e o ADR-L003 endereçáveis; o `§5` do `port.py` passa a **§6**,
que é onde a razão citada está escrita de facto (ADR-L002:141-142: «O AGR lê
segredos ao arranque, onde bloquear é o que se quer, e relê com
`asyncio.to_thread`»). E a razão escrita da condição passa a dizer os dois grupos
reais: 25 *stubs* e 5 ficheiros de `docs/analises/`.

---

### A-04 — CONFIRMADO — relevante — O PR cometia a sub-classe 2 no ficheiro que a explica

**Onde.** `tools/lint_refs/__init__.py:18`.

**O que estava errado.** A tabela de falsos positivos do *gate* 3 dava como
«Exemplo real» a forma `` `D1–D9` em `docs/exploracao/05` §6.1 ``. A minha
correcção pôs o `§6.1` em `§6` — e o revisor foi ver o resto da linha: **não
existe `D1–D9` em sítio nenhum do repositório**.

**Evidência.** `git grep -n "D1[–-]D9" -- '*.md' '*.py'` → sem resultados. O
ficheiro `docs/exploracao/05` nasceu já sem nenhuma ocorrência, e o `§6` é «O que
NÃO resolve», uma lista de cinco pontos sobre *cold-start*, qualidade de dados,
equipas de rua, comissão e *bypass* — nenhum `D`. A série `D1`–`D13` vive em
`docs/tecnica/00` §13.3.

**Porque pesa mais do que parece.** É a sub-classe 2 — citação que passa a
resolver e continua a apontar para o que não está lá — **cometida dentro do PR
que existe para a nomear**, e num ficheiro que a área `tools/lint_refs/**` do
`ci/refs-allow.yaml` torna inverificável por qualquer portão. Corrigir o número e
deixar a afirmação falsa era fazer exactamente o que o `C-03` reprovou.

**Correcção.** A linha passa ao caso medido e real: `` `D0–D30` em
`specs/EPIC-09` ``, que é o intervalo de prazos que o `extrair` do `scan.py` já
documenta (`specs/EPIC-09:1054`) e cuja expansão inventava `D14`…`D29`.

---

### A-01 — CONFIRMADO, e já declarado — O portão não apanha a classe que o motivou

**Evidência do revisor.** Correu o portão contra um *worktree* da árvore que
**tinha** as dez citações do KAM-169, antes da correcção:

```text
EXIT=1 — e um único achado, que não é nenhuma das dez
```

**Zero das dez.** O §12, o §16, o §18 e o §20.1 do `docs/tecnica/10` existem
todos, logo as dez resolvem.

**Classificação.** Não é defeito escondido: está escrito no *docstring*, no
`docs/ci.md`, no bloco do ticket e preso por
`test_a_sub_classe_que_este_portao_nao_fecha`. A leitura do revisor que fica
registada, e que é justa: **o requisito 1 está meio cumprido** — o portão
verifica *existência*, não *correcção*, e as dez eram de correcção. O que foi
mecanizado é a sub-classe vizinha.

---

### A-05 — CONFIRMADO na primeira metade, PLAUSÍVEL na segunda — O alvo novo do `arestas.py` não sustenta a frase

**Onde.** `services/agr/src/kamba_agr/verticais/vendedor/arestas.py:116`.

**O que estava errado.** O original citava `docs/tecnica/08` §9.2, que não existe
(o §9 é «Matriz de conformidade» e não tem subsecções). A minha correcção pôs
§7.3 e declarou a inferência. O revisor foi ver se o §7.3 sustenta a frase: a
frase afirma **duas** coisas — «o nome de um nó não identifica ninguém», que o
§7.3 **não diz** (deduz-se da *allowlist*, não está escrito), e «mas também não
se mede por nó sem alguém decidir», que não tem nada no §7.3. E procurou alvo
melhor: `docs/tecnica/02` §9.2 é «Limitações assumidas» do validador de citação,
e a prosa sobre etiquetas de métrica está no `02` §6.5 — nenhum é o alvo.

**Correcção.** A frase passa a afirmar **só o que a secção diz** — que o §7.3
fixa a *allowlist* de campos de log e que não há campo de nó nenhum nela — e a
dizer, por escrito, que «não se medir **por nó**» não está em sítio nenhum do
canon e fica como decisão por tomar. Deixa de ser uma inferência disfarçada de
citação.

**PLAUSÍVEL, e fica registado:** não há no canon um alvo que sustente a segunda
metade. Se alguém escrever essa regra, a citação ganha destino.

---

### A-06 e A-09 — CONFIRMADO — relevante — Os números do próprio módulo não reproduziam

Tratados na secção 1. Todos remedidos com o módulo entregue, contra a árvore, e
reescritos. O custo é o único que não se reconcilia entre as duas medições, e
está escrito com as duas e sem figura precisa.

---

### A-10 — CONFIRMADO — menor — Formas de citação que o portão deixa cair, e um prefixo que resolvia errado

**O que fica fora**, medido pelo revisor sobre a árvore, sem produzir falso
positivo nenhum: o intervalo `§8.3–§8.4` (70 linhas), o `§§1–7` (2), o documento
numa célula de tabela com o `§` na célula seguinte (140), a preposição fora da
lista, e as maiúsculas trocadas no caminho. Com a fronteira declarada, isto é
cobertura que falta e não defeito — e o total fora do portão está escrito.

**O que era defeito, e foi corrigido:** `_por_prefixo` aceitava qualquer prefixo
único, e na árvore real **`docs/tecnica/1` resolvia para
`docs/tecnica/10_Onboarding_Governanca.md`** por ser o único `1*` daquela pasta —
quando quem escreve «doc 1» quer o `01_Canais…`. Resolver para o documento errado
é pior do que não resolver. O teste que protegia isto era **sintético**: usava uma
*fixture* com um `11_*.md` que este repositório não tem. Passa a exigir-se que o
prefixo acabe numa **fronteira** do nome (`_`, `-` ou `.`), o que cobre as três
formas da casa (`10_Onboarding…`, `05-estrategia…`, `concierge.md`) e faz
`docs/tecnica/0` e `docs/tecnica/1` designarem **nada**.

E o travessão entra na corrida de `§`, o que recupera as 70 linhas do intervalo —
expandindo as **pontas escritas** e não o interior, porque um intervalo não diz
quais são os números entre as pontas.

---

### A-08 — CONFIRMADO, e resolvido em prosa — Escrever *sobre* uma citação errada reprova o portão

O revisor apanhou a árvore num estado intermédio, com nove achados, todos
**citações das citações** que o PR corrige. É a situação que o KAM-002 encontrou
e que o `ci/refs-allow.yaml` escreve no cabeçalho: «a regra a reconhecer que uma
referência pode ser citada *como exemplo de referência inválida*».

**O precedente dava a dispensa, e não se usou.** Sete entradas por token eram
defensáveis e teriam feito o ticket entregar um portão cuja primeira utilização
foi abrir-lhe sete excepções. A saída foi nomear o documento e deixar o número
mau solto: «o `docs/logs.md` tem um §7 sem subsecções, e uma citação pede-lhe um
§7.14» diz o mesmo, e o número mau não tem designador ao lado, logo não é
endereçável.

**A leitura do revisor que fica registada:** o `EXCLUIDOS` cobre `docs/analises/`
e `docs/evidencia/`, mas **não** os blocos de ticket nem as linhas de «Controlo
de versões», que são os outros dois sítios onde esta casa escreve história. O
custo é real e pagou-se duas vezes dentro deste PR. Não se alargou a exclusão:
excluir os blocos de ticket tiraria do portão 170 blocos de *handoff* que o A-02
acabou de lhe dar, e as linhas de versão são escritas uma vez e lidas muitas.

---

## 3. MORTOS, com a evidência que os matou

| # | Achado | O que o matou |
|---|---|---|
| M-01 | «Regras de bloqueio tocadas» | `git diff refs/remotes/publico/main --stat -- .github Makefile ci` → **vazio**. O `ci-3` não muda, nenhum *job* novo, nenhum critério tocado |
| M-02 | «A dispensa anunciada na mensagem não funciona» | Construiu o repositório mínimo, declarou `token: §99@docs/tecnica/00_…` com razão de 30+ caracteres: saída **1 → 0**. A forma documentada funciona |
| M-03 | «O canário sai 1 pela razão errada» | Um só achado, vindo da verificação de secções; o controlo negativo com `§18` sai 0 na mesma *fixture*; o teste assere `len(achados) == 1` |
| M-04 | «A corrida atravessa documentos» | Era verdade na versão que o revisor leu primeiro, e o autor corrigiu durante a revisão (precedência da ordem B). **Resíduo PLAUSÍVEL:** «`06` §7.1 e §3.5 (`specs/02`)» continuaria a atribuir mal; sem ocorrência viva |
| M-05 | «2 270 das 7 905 ocorrências» | Não reproduzia; corrigido pelo autor durante a revisão para o par medido com `grep -ohE` |
| M-06 | Resolvedor: `..` a sair da raiz, não-`.md`, prefixos ambíguos, memória | Os quatro aguentam: `../../etc/passwd` → `None`; `cli.py` §4 → `None`; a chave da memória leva a pasta do citante; a normalização é lexical |
| M-07 | Convenções de língua | Zero PT-BR nos ficheiros novos; comentários de `tools/` sem acentos. Um lapso de concordância, corrigido |
| M-08 | A secção-contentor | `docs/exploracao/06` tem `## Camada 3` sem número com `### 3.1`–`### 3.4` por baixo, e **exactamente 2** citações resolvem só por essa regra — o que o *docstring* diz |
| M-09 | As outras quatro correcções de prosa | Verificadas uma a uma contra o alvo: `logs.md` §7 ponto 14 é o `[k: string]: never`; pontos 5 e 6 são «O *lint* é um *lint*» e «O que as dependências escrevem»; `tecnica/06` §7.6 ponto 2 é o *crypto-shredding*; `ADR-L001` §7 parafraseia-se na frase citante; `tecnica/04:378` tem `valor_declarado_minor bigint`; `EPIC-07:559` é a linha do consentimento |
| M-10 | «19 pares, 7 falsos positivos» | **NÃO VERIFICADO**, e é justo: a implementação candidata não está no diff, pelo que não há nada para correr. O método está na secção 6 |

---

## 4. O falso positivo que a base trouxe a meio, e que ninguém pediu

Enquanto a revisão corria, a `main` moveu-se de `808e328` para `9c5fa60` e trouxe
uma linha nova à **Carta**, que é a fonte de nível 1:

```text
specs/00_KAMBA_Carta.md:91
… a regra do `../docs/tecnica/09` §5.3 em
  `../docs/tecnica/evidencia/validacao/Alojamento_Cotacoes.md` …
```

O portão acusou um `§5.3` inexistente no `Alojamento_Cotacoes.md`. **Era falso
positivo, e sobre prosa inteiramente válida:** o `§5.3` é **do** `tecnica/09`
(que o tem, «Recomendação de trabalho»), e o `Alojamento_Cotacoes.md` é onde a
regra está **escrita**. A ordem B aceitava preposições **locativas** (`em`, `no`,
`na`) como se fossem possessivas, e atribuía o `§` ao documento errado.

**O custo de as tirar, medido antes de as tirar: zero.** Nessa posição a árvore
tem 66 `do`, 15 `de` e **um** `em` — que era este. A ordem B passa a aceitar só
`do`, `da`, `de`.

**Porque é que isto vale uma secção.** É o único falso positivo que o portão
produziu sobre prosa que ninguém escreveu para o testar, e apareceu porque a base
mexeu — não porque alguém o procurou. É o argumento a favor de correr o portão
contra a base todas as vezes, e não só contra a árvore em que foi escrito.

---

## 5. As «oito citações erradas do EPIC-10», que chegaram três vezes e não são defeito

Esta reclamação chegou de uma sessão par **três vezes**, cada uma com uma classe
diferente, e fica aqui porque uma quarta é provável e o instrumento já a
resolveu. O histórico, porque a forma como a afirmação mudou é a parte útil:

| Passagem | O que foi afirmado | O que a árvore diz |
|---|---|---|
| 1.ª | oito citações `§` erradas do `EPIC-10`, na Carta, no `01` e no `INDICE` | não reproduz: nenhuma linha desses três ficheiros cita `EPIC-10` com um `§` |
| 2.ª | a direcção era a inversa — o `EPIC-10` a citá-los — e o defeito é do **prefixo do caminho** | as seis linhas existem; o defeito de caminho não se sustenta |
| 3.ª | retirada: não são defeito nenhum | confirmado, por medição própria |

**A medição que fecha a questão**, feita com o módulo deste PR sobre as seis
linhas nomeadas (`specs/EPIC-10_Spikes_Validacao_Gates.md`, linhas 471, 724,
785, 846, 859 e 936):

```text
citacoes enderecaveis no EPIC-10: 135
nas seis linhas nomeadas:          27, e as 27 resolvem
```

As 27 resolvem **todas**, e a razão está no `_resolver` do
`tools/lint_refs/seccoes.py`: ele tenta `for base in (pasta, "")` — primeiro
relativo à pasta do ficheiro citante, **depois relativo à raiz**. Um
`specs/00_KAMBA_Carta.md` escrito dentro de `specs/` falha a primeira tentativa
(daria `specs/specs/…`) e acerta na segunda. **Não é defeito de secção nem de
caminho.** Nenhuma destas citações é população deste ticket, e o âmbito não se
alarga para as cobrir.

E a linha 859 não produz citação endereçável nenhuma, o que também é correcto:
ela nomeia um `Gate_Piloto_Decisao.md` como **artefacto a produzir** num critério
de aceitação, e esse ficheiro não existe na árvore — o designador não resolve,
pelo que a citação não é endereçável. Um critério que nomeia o entregável que o
ticket tem de criar não é uma referência quebrada, e o portão não a trata como
tal.

**A lição de processo, que é a que vale guardar.** Três passagens de uma
reclamação, duas delas erradas em classes diferentes, resolvidas pelo mesmo
comando. Um relato de outra sessão é uma afirmação como as outras: verifica-se
com instrumento próprio antes de mudar âmbito. Nenhuma das três mudou uma linha
deste PR.

## 6. O que fica por mecanizar, e o método para quem o tentar

**A sub-classe «a secção existe e é a errada»** continua sem instrumento. A única
candidata foi medida e recusada, e o método está aqui para ser reproduzido, já
que a implementação não vai no diff:

```text
1. Para cada linha, casar `(?<![A-Za-z0-9-])(?:[A-Z][A-Z0-9]*-)+[A-Z0-9]*[0-9][A-Z0-9]*`
   seguido, em ≤70 caracteres sem `.`, `;` ou `|`, de um `§N`.
2. Resolver o designador mais próximo da linha; exigir que o `§N` resolva.
3. Exigir que o identificador ocorra no documento de destino.
4. Acusar quando ele NÃO ocorre dentro do corpo da secção citada.
```

Resultado sobre a árvore: **19 pares verificáveis, 7 falsos positivos** — o par
`KAM-111` / `§6.4` na mesma célula de `docs/dividas-documentais.md` sem relação
nenhuma, e seis do mesmo molde. Apanharia **seis** das dez do KAM-169 e pagaria
sete dispensas. Uma verificação que precisa de dispensas para passar é uma nota.

**O cunho abreviado sem pasta** (`` `00` §12 ``) é a forma mais comum de citar
aqui e fica fora. Resolvê-lo pela pasta do ficheiro citante funciona em
`docs/tecnica/` e **mente** noutros sítios: o `docs/tecnica/06` escreve «Doc 11
diz “todo o DELETE é soft”» a falar da biblioteca exploratória. A medição que
falta, e que decide: quantas resolvem, e quantas resolvem para o documento
**errado**.

---

## 7. O que esta revisão custou, e o que ela vale

**Oito achados confirmados, oito corrigidos**, e dois deles — A-02 e A-07 —
fechavam pontos cegos que faziam o portão prometer mais do que fazia. Nenhum dos
dois tinha instância viva na árvore no dia em que foi escrito, e os dois eram
reais: o A-02 deixava 170 blocos sem portão e o A-07 deixava dois documentos
inteiros inendereçáveis com um `§` quebrado lá dentro.

**O que a revisão não podia apanhar, e apanhou-se de outra maneira:** o falso
positivo da Carta (secção 4) veio de a base mexer, não da revisão. E a correcção
do «7 905» veio da auto-validação do autor, não dela — a revisão confirmou-a
morta.

**A métrica da fábrica, para quem a ler depois:** 10 achados levantados, 8
confirmados → calibração de **0,8**. É `INDÍCIO` e não `CONFIRMADO`, porque é
lida à mão desta análise contra o PR, e este repositório não tem instrumento que
a produza.

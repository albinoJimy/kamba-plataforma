# ANÁLISE-22 — Revisão adversarial do KAM-155 (EPIC-01 por ticket)

| Campo | Valor |
|---|---|
| Ticket | KAM-155 — Divisão do EPIC-01 em um ficheiro por ticket, com o epic como índice |
| Ramo | `feature/KAM-155-epic-01-por-ticket-pub` |
| Base | `main` (`7a68b6d`) |
| Revisor | Agente independente, com os requisitos e o resultado — **sem** as justificações de quem produziu |
| Data | Outubro de 2026 |
| Veredicto da primeira passagem | **REPROVADO** — 1 bloqueador, 10 achados maiores, 7 menores |
| Veredicto depois das correcções | Aprovado com dívida declarada (3 dívidas novas: 30, 31, 32) |

> **O que esta revisão substituiu.** A versão anterior deste ficheiro media uma
> implementação **diferente** do mesmo ticket, feita noutro ramo (`…-por-ticket`,
> 35 blocos, 4 347 linhas, 147 de índice, e a decisão **oposta** quanto ao
> prefixo `../`). Foi o primeiro achado desta revisão, e o único bloqueador:
> oferecer como evidência uma análise de outro artefacto. Este documento é a
> revisão da entrega que está neste ramo (39 blocos, 5 587 linhas, 160 de
> índice).

---

## 1. Âmbito e método

O revisor recebeu os oito critérios de aceitação declarados, o estado anterior
(`git show HEAD:specs/EPIC-01_Fundacoes_Dados.md`) e o resultado na árvore de
trabalho. Não recebeu o raciocínio de quem produziu.

O que correu, por sua conta:

- extracção própria dos 39 blocos do `HEAD`, com contagem de cercas, pareada
  **linha a linha** com cada ficheiro de ticket;
- resolução em disco de cada token `../` a partir de `specs/` e de
  `specs/tickets/`, nos dois sentidos;
- `lint_refs check`, `lint_handoff check`, `canon_lint check` + canário,
  `lint_arch all`, e as *suites* de unidade de `lint_handoff`, `lint_refs`,
  `canon_lint` e `lint_arch`;
- varrimento por consumidores: `grep -rn` por `EPIC-01_Fundacoes_Dados`,
  `specs/EPIC-`, `## KAM-` e `EPIC-XX` em `*.py *.yaml *.yml *.sh *.ts *.js *.md
  Makefile`, excluídos `.git/` e `.claude/worktrees/`;
- reconciliação das contagens entre `specs/INDICE.md` §1, §3.1 e §4, a tabela do
  epic e os ficheiros em disco.

---

## 2. Achados

### Bloqueador

| # | Achado | O que se fez |
|---|---|---|
| **C1** | **A revisão adversarial citada como evidência auditava outra entrega.** A linha «DoD 2» do bloco oferecia este ficheiro como a revisão independente, e ele media o outro ramo: 35 blocos contra 39, 4 347 linhas contra 5 587, −612 bytes contra +932, «462 caminhos `../` ficaram à profundidade antiga» classificado como **Maior** — a decisão oposta à desta entrega. Nenhuma menção a 537, 5 587, 658 080, `PADROES` ou aos dois globos | **Corrigido.** Este documento passou a ser a revisão desta entrega, com a nota de abertura a dizer o que substituiu |

### Maiores

| # | Achado | O que se fez |
|---|---|---|
| **M1** | Critério 4: «158 linhas / 35 735 bytes» não reproduzia — o ficheiro tem 160 linhas, e os bytes mudam a cada edição. Medido antes da última alteração ao texto | **Corrigido**: 160 linhas e o byte medido no fim, com a nota de que a primeira medição foi feita cedo |
| **M2** | Critério 7: «os 18 tickets fechados do EPIC-01» não reproduzia; são **27**. O 18 vinha copiado da análise do outro ramo, e estava propagado para o *docstring* do `vagas.py` | **Corrigido** nos dois sítios |
| **M3** | Critério 3: o denominador («614 ocorrências») e a repartição não reproduziam sob a tokenização do revisor (621/84/21) | **Corrigido declarando o universo**: 614 tokens `../<raiz>` **a um nível, fora de cercas**, que é o universo que esta operação decide. Os tokens já a dois níveis estão agora contados e nomeados em separado |
| **M4** | **62 referências vivas ficaram à profundidade errada.** A regra «subir quando o caminho resolve em disco» nunca sobe `../docs/tecnica/NN`, porque um caminho sem extensão não resolve — e a mesma forma nos outros dez epics está certa. O precedente contradizia a justificação: a dívida 23, paga pelo KAM-150, era precisamente `tecnica/08` em prosa | **Corrigido na raiz: a regra mudou.** Passou a subir **todo** o token a um nível, com **9 linhas declaradas por excerto** (12 tokens) onde o caminho é o objecto da frase. O disco deixou de decidir |
| **M5** | O universo auditado nunca incluiu as referências relativas **sem** `../`: 11 nomes irmãos que resolviam de `specs/`, três deles prosa viva (`01_Engineering_Standards_e_Handoff.md` no KAM-010). «0 quebras» era falso | **Corrigido**: os 3 nomes que são referência viva sobem a `../<nome>`; os 10 restantes estão declarados como **nome** e não caminho (uma *fixture*, a árvore anterior ao KAM-128, o ficheiro excluído de uma busca) |
| **M6** | A linha do KAM-155 (e, antes dela, a do KAM-154) estava na sub-tabela do **EPIC-11** do §4: 38 contra os 40 do §3.1. A tabela do epic saiu certa pela razão errada — o filtro real foi «tem bloco», não o agrupamento do §4 | **Corrigido**: as duas linhas passaram para a sub-tabela do EPIC-01, e a contagem por epic do §4 passou a bater com o §3.1 em todos os onze |
| **M7** | Consumidores por corrigir além dos três nomeados: `specs/01_Engineering_Standards_e_Handoff.md` §2 e §7 (**canon** — dizem onde um ticket vive), `SKILL.md` ×2, `encerramento.md` (a origem dos requisitos), e o comentário de `packages/core-ts/src/secrets/doppler.ts` | **Corrigidos os sete.** E a revisão não tinha visto um oitavo, que a correcção destapou: **37 apontadores de *handoff*** que mandavam ler o bloco no ficheiro do epic, 14 deles em tickets **não entregues** |
| **M8** | `README.md`: «Backlog mestre (154 tickets)». A dívida 19, riscada como paga pelo KAM-153, estava reaberta | **Corrigido**: 155 |
| **M9** | «derivada do backlog mestre, pelo que a omissão deixa de ser possível à mão» é afirmação sem suporte: a tabela é Markdown estático, nada a gera, nenhum *gate* a compara, e o que o faria é o KAM-138 | **Corrigido**: a afirmação passou a dizer que foi derivada **nesta entrega** e verificada campo a campo, e que **nada a mantém derivada** |
| **M10** | As buscas de regressão G1/G3 (KAM-129) e G6/G7 (KAM-153) estão declaradas sobre `specs/*.md` com a exclusão **nomeada** de um ficheiro. O material que vigiam saiu para `specs/tickets/`: o valor medido continua 0, por o corpus não chegar lá | **Declarado** como dívida **32** |

### Menores

| # | Achado | O que se fez |
|---|---|---|
| **m1** | O critério 2 nomeava um só `../../` pré-existente como causa de dois ficheiros | **Corrigido**: os dois estão nomeados (`../../packages/core-ts` no KAM-133, `../../specs/INDICE.md` no KAM-128) |
| **m2** | A justificação dizia que o `link:../../packages/core-ts` fica de fora «por estar dentro de uma cerca»; está em prosa | **Corrigido**: fica de fora por já estar a dois níveis, que é a razão verdadeira |
| **m3** | As dívidas novas foram escritas para dentro de uma cauda malformada da tabela (linha riscada fora da tabela, cabeçalho sem linha vazia) | **Corrigido**: a riscada 28 volta à tabela, junto das outras, e o cabeçalho ficou separado |
| **m4** | A dívida 31 não nomeava a análise real do KAM-144 (`ANALISE-16`), que existe | **Corrigido** |
| **m5** | Os três mapas do conjunto (`specs/INDICE.md` §2, `README.md`, `docs/INDICE.md` §2) não mencionavam `specs/tickets/`: 40 documentos canónicos ausentes do mapa | **Corrigido nos três** |
| **m6** | O cabeçalho do epic diz `Versão 1.0` com histórico até 1.31, e falta a 1.13 | **Declarado**; é a dívida 21, do KAM-138 |
| **m7** | O `vagas.py` traz uma correcção alheia ao âmbito (`sys.stdout.reconfigure`) | **Mantida e declarada**: sem ela o guião morre a meio em cp1252, e a evidência deste ticket precisa de o correr até ao fim |

---

## 3. Números que a revisão reproduziu

Dezoito dos vinte e dois números afirmados bateram à primeira. Os quatro que não
bateram estão em M1, M2 e M3, e todos foram corrigidos.

| Afirmado | Medido pela revisão | Bate? |
|---|---|---|
| 39 blocos `## KAM-` no `HEAD` | 39 | sim |
| Blocos: 658 080 bytes | 658 080 | sim |
| Inverso devolve o `HEAD` em 37 de 39 | 37 (falham KAM-128 e KAM-133, pelo próprio inverso) | sim |
| 537 prefixos subidos *(primeira passagem)* | 537 | sim |
| 0 referências quebradas no universo `../` | 0 quebradas, 0 retarguetadas | sim |
| 62 na forma `docs/tecnica/NN`; 1 em `NN_` | 62; 1 | sim |
| Tabela resumo: 36 → 40, campos iguais ao mestre | 40, **0 divergências** nos cinco campos | sim |
| `lint_handoff` antes 596/154/11, depois 608/155/50 | igual | sim |
| `varrer_ficheiro` do KAM-155: 12 caminhos | 12 | sim |
| §1 = 155; §3.1 EPIC-01 = 40; TOTAL = 155; soma por epic = 155; série 1–155 sem buracos | igual | sim |
| Contexto: 101 revisões de 231; 28 de 36 do primeiro pai | igual | sim |
| 12 caixas: 11 marcadas, 1 vazia | igual | sim |
| **614 ocorrências auditadas** | 621 sob outra tokenização | **não** → M3 |
| **77 ficaram em `../`** | 84 sob outra tokenização | **não** → M3 |
| **Epic: 158 linhas / 35 735 bytes** | 160 / 36 343 | **não** → M1 |
| **18 tickets fechados do EPIC-01** | 27 | **não** → M2 |

---

## 4. O que a revisão cobriu e não encontrou defeito

- **Integridade do movimento.** 39 de 39 blocos iguais linha a linha a menos do
  prefixo; nenhum bloco perdeu, ganhou ou trocou conteúdo; nenhuma caixa de
  critério mexida.
- **Contagem a dobrar.** Nenhum consumidor conta o mesmo ficheiro duas vezes:
  `lint_handoff.ficheiros()` tira repetidos e tem teste com globos sobrepostos,
  `vagas.py` acumula num conjunto, `lint_refs` percorre `git ls-files` uma vez, e
  o corpus do `canon_lint` é `docs/tecnica/**` e nunca leu `specs/`.
  `grep -c '^## KAM-' specs/EPIC-01_Fundacoes_Dados.md` dá **0**: nenhum bloco em
  dois sítios.
- **`CODEOWNERS` e `.github/`.** A regra `/specs/` cobre `specs/tickets/`
  recursivamente — nenhum ficheiro ficou sem dono, e o *gate* do KAM-154 não
  regride. Nenhum *workflow* filtra por `paths:` sobre `specs/`.
- **Gates e testes.** Todos verdes, antes e depois.

---

## 5. Lições que esta revisão deixa ao conjunto

1. **Uma análise adversarial é de uma entrega, não de um ticket.** Dois ramos com
   o mesmo número de ticket produzem dois artefactos diferentes, e a análise de
   um não serve de evidência ao outro. O nome do ficheiro — `ANALISE-NN-KAM-NNN` —
   convida ao erro.
2. **Uma regra que delega a decisão ao disco não é neutra.** «Subir o prefixo
   quando o caminho resolve» parece mecânico e é uma escolha: exclui tudo o que
   não tem extensão. A regra uniforme com excepções declaradas por excerto diz o
   que faz e deixa-se auditar.
3. **O número mede-se no fim.** Duas das quatro divergências são medições feitas
   antes da última alteração ao ficheiro. É a terceira vez que esta classe
   aparece no repositório.
4. **O universo auditado é parte da afirmação.** «0 quebras» sobre um universo
   que exclui metade das formas não é «0 quebras». O universo escreve-se ao lado
   do número.

# Integração, auditoria e relatório final

Lê este ficheiro quando estiveres a integrar, a auditar completude, a escrever o relatório
final, ou a limpar depois de um merge.

- [Auditoria do changeset](#auditoria-do-changeset)
- [Portão de integração](#portão-de-integração)
- [Como saber que um ramo fundiu](#como-saber-que-um-ramo-fundiu)
- [Limpeza depois do merge](#limpeza-depois-do-merge)
- [Auditoria de completude](#auditoria-de-completude)
- [Quality gate](#quality-gate)
- [Auditoria final](#auditoria-final)
- [Relatório final](#relatório-final)
- [Conhecimento persistente](#conhecimento-persistente)

---

## Auditoria do changeset

Antes de integrar, compara o que mudou com o que **era suposto** mudar.

```text
AUDITORIA DO CHANGESET

Ficheiros modificados:
Ficheiros criados:
Ficheiros removidos:
Alterações esperadas:
Alterações inesperadas:        ← investigar, não aceitar
Alterações fora do escopo:     ← justificar ou reverter
Propagação em falta:           ← quem afirma o mesmo e não foi actualizado
```

```bash
git status --short
git diff --stat
git diff -- <ficheiro>          # para ver o que mudou, não só quanto
```

O repositório está sob git desde 2026-10-10 (baseline `036e307`). Antes disso esta fase era
estruturalmente impossível, e as alterações feitas por script sobre dezenas de documentos não
tinham rede. Agora têm: **nenhuma edição em lote fecha sem ler o `git diff`**.

As alterações inesperadas mais frequentes neste conjunto: um índice com contagem antiga, uma
tabela-resumo dessincronizada do backlog mestre, uma linha de versão esquecida, e um documento
tocado por um agente que devia ter ficado fora do escopo.

A **propagação em falta** é a linha que importa mais aqui, e não tem equivalente num repositório
de código: corrigir uma afirmação num documento e deixar o vizinho a dizer o contrário é o
defeito característico deste conjunto.

---

## Portão de integração

Uma task só integra quando **todas** fecham:

```text
[ ] Produção concluída
[ ] Self-validation concluída
[ ] Verificações relevantes executadas (nomeadas, com resultado — não "verifiquei")
[ ] Revisão independente concluída
[ ] Achados verificados — os CONFIRMADOS resolvidos, os PLAUSÍVEIS no relatório,
    os MORTOS registados com a evidência que os matou
[ ] Portões do eixo corridos na árvore integrada, com comando e resultado
[ ] Problemas críticos resolvidos — não adiados
[ ] Changeset auditado (ou a lacuna declarada)
[ ] Propagação feita: nenhum documento do conjunto ficou a contradizer
[ ] Nomes novos registados no dicionário
[ ] Dependências satisfeitas
[ ] **Caixas do epic tratadas** — marcadas as que têm evidência, vazias as que não,
    e a secção de verificação escrita no bloco do ticket
```

Um problema crítico «resolvido registando-o como limitação conhecida» não passa este portão.
Limitação conhecida é para o que se decidiu não fazer; não é destino para o que falhou.

E **uma caixa marcada sem evidência não passa este portão tão-pouco**. É o inverso do mesmo
defeito: em vez de declarar como falha o que foi decisão, declara como feito o que não foi
medido. Os dois acabam no mesmo sítio — um DoD em que ninguém confia.

---

## Como saber que um ramo fundiu

Esta secção existe porque o `git` **não** responde a esta pergunta neste repositório, e responde
com confiança a coisa errada. Medido a 2026-10-19, no encerramento do KAM-013.

**Duas propriedades do repositório tornam o `git` enganador aqui:**

1. **A `main` funde por *squash*.** O título é `KAM-NNN — <título> (#N)`. Logo
   `git merge-base --is-ancestor <ramo> publico/main` responde **«não fundido» sempre**, mesmo
   para um ramo que acabou de fundir — os commits individuais não são antepassados do *squash*. O
   meu ramo do KAM-013, minutos depois de fundir, mostrava quatro commits «fora da `main`».
2. **Há dois remotos, e as histórias deles não têm antepassado comum.** `publico`
   (`albinoJimy/kamba-plataforma`) é o activo; `origin` (`albinoJimy/kamba`) é a linha antiga, com
   numeração de PR própria e uma `main` divergente. Para um ramo da linha do `origin`,
   `git merge-base <ramo> publico/main` **falha** — código 1, sem saída.

**E é a segunda que arma a ratoeira.** Um comando que capture a saída do `merge-base` sem
verificar o código de saída fica com a variável vazia, e um `git diff --name-only "" <ramo>`
devolve **zero linhas** — que se lê como «este ramo não tem nada que a `main` não tenha». Foi
exactamente o que eu li, para sete *worktrees*, e cada um guardava entre 164 e 254 commits que a
`publico/main` não contém. A um passo de os apagar.

**A prova é o estado do PR, e vem do GitHub:**

```bash
gh pr list --repo albinoJimy/kamba-plataforma --head <ramo> --state all   --json number,state,mergedAt
```

| Resposta | Leitura |
|---|---|
| `MERGED` com `mergedAt` | **O trabalho está na `main`.** O ramo local e o *worktree* podem ir |
| `CLOSED` | **Não fundiu.** Fechado sem merge — e um ticket fechado com o mesmo número não é prova de que *este* ramo aterrou |
| `OPEN` | É a cópia de trabalho de um PR vivo. **Não se toca** |
| `[]` | Não há PR nesse repositório. **Pergunta ao outro remoto** antes de concluir |

Duas confirmações baratas que acompanham a resposta `MERGED`: o ramo remoto deixou de existir
(`git ls-remote --heads publico <ramo>` devolve vazio, porque o merge apaga-o) e o conteúdo é
igual (`git diff --stat HEAD publico/main` vazio, quando o ramo está em dia com a `main`).

---

## Limpeza depois do merge

Pela ordem, e com a razão de cada passo:

```text
[ ] PR fundido, confirmado pelo GitHub (acima) e não pelo `git`
[ ] Ramo remoto apagado (o `gh pr merge --delete-branch` fá-lo)
[ ] `main` do checkout principal em dia: `git pull --ff-only publico main`
[ ] Ramo local apagado
[ ] Worktree removido
[ ] Contentores e redes órfãos removidos
[ ] Registos temporários da sessão apagados
```

Quatro coisas que esta limpeza ensinou:

- **O `git worktree remove` falha em Windows** com «Function not implemented», pelas ligações
  simbólicas dentro do `node_modules`. O registo é limpo e a pasta fica: remove-se com
  `Remove-Item -Recurse -Force` e, se isso falhar num caminho longo, com `rmdir /s /q`. Confirma
  com `Test-Path` — não assumas pelo código de saída.
- **Os contentores de uma suite que abortou no `setUpClass` ficam vivos.** Encontrei um
  `kamba-gwy-*` de pé há duas horas, e uma rede `kamba-eventos-*` órfã. Procura-os por
  `docker ps -a --filter "name=kamba"` e `docker network ls --filter "name=kamba"`.
- **Apaga só o que esta sessão criou.** O `%TEMP%` tinha 5 658 pastas `kamba-*` de outras
  sessões, de outros dias, ao lado dos 63 ficheiros de registo meus. Filtra por data **e** por
  padrão, e não por prefixo.
- **Um *worktree* de outra sessão não é teu para apagar.** Um `locked` foi bloqueado por alguém
  com uma razão que tu não vês, e um ramo com PR **aberto** é a cópia de trabalho de alguém. A
  ferramenta da app (`clean_up_worktrees`) respeita isso, mas a janela mínima dela é **30 dias de
  inactividade**: para o trabalho desta semana ela não faz nada, e dizê-lo é melhor do que a
  chamar e parecer que fez.

---

## Auditoria de completude

Compara, um contra o outro:

```text
PEDIDO → REQUISITOS → TASKS → PRODUÇÃO → VERIFICAÇÃO → PROPAGAÇÃO
```

Procura deliberadamente: requisitos esquecidos, tasks não executadas, verificações ausentes,
documentos não propagados, índices desactualizados, e alterações **parcialmente** feitas.

A alteração parcial é a mais perigosa das seis: está certa onde olhaste e errada no resto, e
ninguém vai suspeitar dela porque há evidência de que «está feito». Nesta sessão, o caso-tipo foi
o evento do gatilho de provisioning — corrigido no documento de onboarding e deixado na versão
antiga em quatro outros.

```text
AUDITORIA DE COMPLETUDE

Requisitos:
- [x] ...
- [x] ...
- [ ] ...          ← se ficar por marcar, diz porquê

Em falta:
- ...

Riscos residuais:
- ...

Conclusão: COMPLETO / INCOMPLETO / PARCIALMENTE VERIFICADO
```

A origem dos requisitos são os **Critérios de Aceitação** do ticket `KAM-NNN` — em
`specs/tickets/KAM-NNN.md` no EPIC-01, no `specs/EPIC-XX_*.md` nos outros dez (KAM-155) —
e o DoD de `specs/01_Engineering_Standards_e_Handoff.md` §3. Percorre-os um
a um, com a evidência ao lado. Um critério marcado sem evidência nomeada não está marcado — está
presumido.

---

## Quality gate

```text
[ ] Requisitos atendidos
[ ] Produção verificada (por máquina onde é estrutura, por leitura onde é significado)
[ ] Afirmações com estado de verificação; propostas marcadas como tal
[ ] Revisão independente concluída
[ ] Alterações auditadas
[ ] Contradições avaliadas e propagação feita
[ ] Integração verificada (segunda passagem estável)
[ ] Completude verificada
[ ] Riscos residuais documentados
[ ] Conhecimento actualizado quando havia o que actualizar
[ ] Caixas do epic marcadas com evidência; as não cumpridas vazias e nomeadas
[ ] **Contagem conferida:** caixas do ticket = marcadas + vazias declaradas. Se a soma
    não fechar, há uma caixa que ninguém olhou
```

> **Como se confere a contagem**, porque fazê-lo de cabeça é como isto se perdeu quatro vezes:
>
> ```bash
> # marcadas, e vazias — cada vazia tem de aparecer na secção de verificação
> # No EPIC-01 cada ticket é um ficheiro (KAM-155), e o bloco é o ficheiro todo:
> bloco=$(cat specs/tickets/KAM-003.md)
> # Nos outros dez epics os blocos vivem dentro do ficheiro do epic, e a gama
> # termina no cabeçalho SEGUINTE — não num `---`:
> # bloco=$(awk -v t='^## KAM-029 ' '$0~t{f=1} f&&/^## KAM-/&&$0!~t{exit} f' \
> #           specs/EPIC-03_Agent_Runtime_Verticais.md)
> echo "$bloco" | grep -c '^- \[x\]'
> echo "$bloco" | grep -c '^- \[ \]'
> echo "$bloco" | grep -c '^## KAM-'    # tem de dar 1; se der 2, a gama atravessou
> ```
>
> **A gama não pode terminar em `^---$`.** Nem todos os blocos têm esse separador antes do
> seguinte: em `specs/EPIC-03`, o KAM-029 e o KAM-035 não o têm, e
> `awk '/^## KAM-029 /,/^---$/'` atravessa para o KAM-030 e devolve 15 marcadas e 14 vazias
> em vez de 9 e 5 — uma soma que **fecha**, e por isso ninguém a olha outra vez. Dois em 115
> blocos sobrecontam assim; o EPIC-02 está entre os 113 que funcionam, o que faz a receita
> errada parecer certa quando se testa. É para isso que serve a última linha.

---

## Auditoria final

Dez perguntas, antes de responder ao utilizador:

```text
 1. O pedido original foi totalmente compreendido?
 2. Todas as partes do pedido foram feitas?
 3. Existem partes não verificadas — e estão declaradas?
 4. Existem alterações fora do escopo?
 5. As verificações são suficientes, ou apenas presentes?
 6. Existem riscos residuais?
 7. Falta registo (ADR, decisão aberta, dicionário, hipótese, evidência, ticket)?
 8. O resultado é reproduzível por outra pessoa?
 9. O conjunto ficou consistente?
10. Existe alguma conclusão baseada apenas em suposição?
```

Se alguma resposta crítica for negativa, **não declares a tarefa concluída**. Entrega o que está
feito, nomeia o que ficou por fazer e porquê. Reduzir o âmbito é decisão do utilizador, não tua —
mas esconder que o âmbito encolheu é decisão de ninguém.

---

## Relatório final

Objectivo, baseado em evidência, sem hedging.

```text
RESUMO DE EXECUÇÃO

Objectivo:

Concluído:
- ...

Ficheiros alterados:
- ...                    (com nº de linhas quando for redacção)

Verificações executadas:
- ...                    (o que fez + resultado, não "verifiquei")

Revisão:
- ...                    (quem/o quê reviu, e o que encontrou)

Caixas do ticket:
- marcadas: N de M       (cada uma com evidência na secção de verificação do epic)
- por marcar: ...        (uma linha por caixa vazia, com a razão — nunca em silêncio)

Decisões que tomei:
- ...                    (o que decidi sozinho, para o utilizador poder inverter)

Propostas e valores não calibrados:
- ...

Não verificado:
- ...                    (explícito, não omitido)

Riscos residuais:
- ...

Indicadores:
- Verde à primeira:      sim / não (e porquê)
- Achados:               N levantados → N confirmados → N plausíveis → N mortos
- Caixas por marcar:     N (as da secção acima)
- Escape a converter:    nenhum / o passo ou gate que passa a cobri-lo

Completude: COMPLETO / PARCIAL / NÃO VERIFICADO

Estado final: DONE / NEEDS ATTENTION
```

Seis notas sobre como isto se lê:

**«Verificações executadas»** com o que a verificação faz e o resultado vale mais do que uma
lista de nomes. «N tickets, 0 erros de consistência; segunda passagem 0 divergências» é
reproduzível; «backlog verificado» não é.

**«Revisão»** tem de dizer o que a revisão *encontrou*, mesmo quando foi nada. «Revisão
adversarial: 6 achados, 4 corrigidos, 2 aceites como limitação» é evidência de que houve revisão.
«Revisto» não é.

**«Caixas do ticket»** existe porque a sua ausência custou quatro tickets. O KAM-001, o
KAM-002, o KAM-128 e o KAM-129 foram entregues com PR verde e 62 caixas por marcar entre os
quatro, e nenhum relatório o mencionou. «10 de 14 marcadas; por marcar: p95 pede 20 execuções
e há 17; o canário não cumpre o critério à letra» diz ao leitor exactamente onde o ticket está.
«Entregue» não diz nada — e é precisamente a palavra que esconde a diferença entre entregue e
fechado.

**«Decisões que tomei»** é a secção que dá ao utilizador a oportunidade de discordar. Neste
conjunto, as decisões tomadas por mim incluíram a classificação FIXA/CONDICIONAL dos ADRs, a
promoção de propostas a ADR canónico e todos os limiares numéricos — e cada uma tinha de ser
nomeada.

**«Não verificado»** nunca se omite por ser má notícia. Dizer «o SQL nunca correu» e «ninguém leu
os tickets linha a linha» é o que permite ao leitor decidir onde olhar.

**«Indicadores»** é o que faz da fábrica uma fábrica e não um método: sem número, não há
melhoria, há repetição. Os dois primeiros leem-se de artefactos (`gh pr checks`, o bloco do
ticket); a linha dos achados é a contagem da revisão desta entrega, e não uma taxa acumulada —
uma taxa reconstruída à mão é `INDÍCIO`, nunca `CONFIRMADO`
([`metricas-e-realimentacao.md`](metricas-e-realimentacao.md)). E «escape a converter» responde
à pergunta que fecha o ciclo: **se um portão podia ter apanhado isto, qual, e já ficou a
apanhar?**

---

## Conhecimento persistente

Depois de fechar, actualiza o conhecimento quando houver mesmo o que registar:

| O que descobriste | Onde vive |
|---|---|
| Decisão de arquitectura canónica nova | `docs/tecnica/00_Arquitectura_Solucao.md` §8 (ADR-NNN); contagem **e** mapeamento ADR → documento em `docs/tecnica/INDICE.md` §5 |
| Decisão de execução (toolchain, segredos, fila, verificação) | `docs/adr/ADR-L<NNN>-<slug>.md`, numeração própria — **não** é ADR canónico |
| Medição, procedimento ou registo longo de um ticket | `docs/evidencia/KAM-NNN.md` (21 anexos hoje; um deles é `REQUIRED_FILES` do `lint_arch`) |
| Decisão que depende de terceiro | `docs/tecnica/00` §13.3 (D#) e `specs/00_KAMBA_Carta.md` §4.2, com dono e escalada |
| Nome, estado, evento ou unidade | `specs/02_Dicionario_de_Dados_Canonico.md` §3, com emenda no §6 |
| Facto novo sobre Meta, pagamentos, lei, licenças, fornecedores | `docs/tecnica/evidencia/EN_*.md`, com URL, data e estado |
| Hipótese de negócio nova | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H#), com limiar, prazo e pivô |
| Desenho de subsistema | `docs/tecnica/01`–`docs/tecnica/10`, na secção própria ou como adenda datada |
| Trabalho a fazer | ticket em `specs/tickets/KAM-NNN.md` (EPIC-01) ou `specs/EPIC-XX_*.md` (os outros dez) **e** linha no backlog mestre `specs/INDICE.md` §4 |
| Achado de revisão | `docs/analises/ANALISE-NN-<slug>.md` |
| Risco operacional ou armadilha de execução | o documento de operação (`docs/tecnica/09`) ou esta skill |
| Resíduo textual fora do âmbito (sem código nem decisão) | `docs/dividas-documentais.md`, uma linha |
| Decisão sobre o pipeline, ou lacuna que ele deixou | `docs/ci.md`, e o §7 se ficou lacuna |
| **Defeito que escapou a um portão** | **um passo num gate que existe, ou um gate alargado** — ver [`metricas-e-realimentacao.md`](metricas-e-realimentacao.md) |

Duas regras de higiene:

- **Não contradigas um ADR em vigor** sem o substituir explicitamente, e não feches uma decisão
  aberta sem o gatilho que a Carta nomeia.
- **Antes de reescrever conhecimento existente**, confirma que a versão anterior deixou mesmo de
  ser verdade — a maior parte das vezes não deixou, apenas ficou incompleta.

E uma regra de âmbito: o `docs/00-KAMBA-documento-mestre.md` é artefacto compilado da biblioteca
exploratória. Está desactualizado face ao conjunto técnico e às specs, nunca se edita à mão, e
precisa de ser regenerado antes de qualquer partilha externa.

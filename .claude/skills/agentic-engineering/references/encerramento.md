# Integração, auditoria e relatório final

Lê este ficheiro quando estiveres a integrar, a auditar completude, ou a escrever o relatório
final.

- [Auditoria do changeset](#auditoria-do-changeset)
- [Portão de integração](#portão-de-integração)
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

A origem dos requisitos são os **Critérios de Aceitação** do ticket `KAM-NNN` no
`specs/EPIC-XX_*.md`, e o DoD de `specs/01_Engineering_Standards_e_Handoff.md` §3. Percorre-os um
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
> bloco=$(awk '/^## KAM-003 /,/^---$/' specs/EPIC-01_Fundacoes_Dados.md)
> echo "$bloco" | grep -c '^- \[x\]'
> echo "$bloco" | grep -c '^- \[ \]'
> ```

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

Completude: COMPLETO / PARCIAL / NÃO VERIFICADO

Estado final: DONE / NEEDS ATTENTION
```

Cinco notas sobre como isto se lê:

**«Verificações executadas»** com o que a verificação faz e o resultado vale mais do que uma
lista de nomes. «127 tickets, 0 erros de consistência; segunda passagem 0 divergências» é
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

---

## Conhecimento persistente

Depois de fechar, actualiza o conhecimento quando houver mesmo o que registar:

| O que descobriste | Onde vive |
|---|---|
| Decisão de arquitectura nova | `docs/tecnica/00_Arquitectura_Solucao.md` §8 (ADR-NNN); contagem em `docs/tecnica/INDICE.md` §5; mapeamento em `specs/INDICE.md` §6 |
| Decisão que depende de terceiro | `docs/tecnica/00` §13.3 (D#) e `specs/00_KAMBA_Carta.md` §4.2, com dono e escalada |
| Nome, estado, evento ou unidade | `specs/02_Dicionario_de_Dados_Canonico.md` §3, com emenda no §6 |
| Facto novo sobre Meta, pagamentos, lei, licenças, fornecedores | `docs/tecnica/evidencia/EN_*.md`, com URL, data e estado |
| Hipótese de negócio nova | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H#), com limiar, prazo e pivô |
| Desenho de subsistema | `docs/tecnica/01`–`docs/tecnica/10`, na secção própria ou como adenda datada |
| Trabalho a fazer | ticket em `specs/EPIC-XX_*.md` **e** linha no backlog mestre `specs/INDICE.md` §4 |
| Achado de revisão | `docs/analises/ANALISE-NN-<slug>.md` |
| Risco operacional ou armadilha de execução | o documento de operação (`docs/tecnica/09`) ou esta skill |

Duas regras de higiene:

- **Não contradigas um ADR em vigor** sem o substituir explicitamente, e não feches uma decisão
  aberta sem o gatilho que a Carta nomeia.
- **Antes de reescrever conhecimento existente**, confirma que a versão anterior deixou mesmo de
  ser verdade — a maior parte das vezes não deixou, apenas ficou incompleta.

E uma regra de âmbito: o `docs/00-KAMBA-documento-mestre.md` é artefacto compilado da biblioteca
exploratória. Está desactualizado face ao conjunto técnico e às specs, nunca se edita à mão, e
precisa de ser regenerado antes de qualquer partilha externa.

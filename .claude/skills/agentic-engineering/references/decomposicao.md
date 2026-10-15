# Decomposição, dependências e estado

Lê este ficheiro quando fores partir a tarefa em unidades, modelar o grafo de dependências,
resolver um conflito entre fontes de verdade, recuperar de uma falha, ou manter estado de
execução retomável.

- [Conflito entre fontes](#conflito-entre-fontes)
- [Anatomia de uma task](#anatomia-de-uma-task)
- [Grafo e estados](#grafo-e-estados)
- [Dependências no backlog](#dependências-no-backlog)
- [Recuperação de falhas](#recuperação-de-falhas)
- [Estado de execução](#estado-de-execução)

---

## Conflito entre fontes

Duas fontes de verdade a discordar é informação, não ruído. O erro é escolher a mais recente, ou
a mais conveniente, sem o dizer. Regista:

```text
CONFLITO
- Fonte A:
- Fonte B:
- Diferença:
- Impacto (o que muda consoante a escolha):
- Decisão:
- Justificação:
- Propagação (que outros documentos afirmam o mesmo e têm de mudar):
```

A ordem de precedência está na tabela de fontes de verdade do `SKILL.md`. Quatro casos que este
repositório já produziu:

**Dois documentos técnicos escritos em paralelo divergem.** Aconteceu com `contacts` (três
esquemas), o consentimento (três tabelas) e a unidade monetária (`valor_kz` contra
`valor_minor`). Nenhum está errado por si: falta um nome canónico. A resolução não é escolher o
melhor, é **registar o nome no dicionário** e corrigir os dois.

**Um documento corrige um desenho e o vizinho fica desactualizado.** O `docs/tecnica/04` corrigiu a
unicidade do ledger e o `docs/tecnica/08` continuou com a versão antiga. O documento mais específico
sobre o subsistema ganha, e a divergência é um defeito a corrigir — não uma licença para
replicar a versão antiga em conteúdo novo.

**A biblioteca exploratória contradiz a evidência.** Ganha a evidência, sempre. A biblioteca
`01`–`13` foi escrita antes da pesquisa; afirmações como «vender por conversa custa ~$0» ou
«assistente em grupos de bairro» estão factualmente corrigidas por `docs/tecnica/evidencia/E1`.

**O ticket pede algo que um ADR proíbe.** O ADR ganha. Se o ticket for necessário, o caminho é
substituir o ADR explicitamente — nunca implementar contra ele em silêncio.

---

## Anatomia de uma task

Uma task tem de ser pequena o suficiente para um agente a compreender sem reconstruir o conjunto
inteiro, e completa o suficiente para produzir um resultado que se possa verificar isoladamente.
Se não consegues escrever `VALIDACAO` sem depender de outra task, ainda não partiste no sítio
certo.

```text
TASK_ID:
OBJECTIVO:              o resultado, não a actividade
CONTEXTO:               o mínimo que torna a task compreensível
INPUTS:                 documentos, ADRs, linha do backlog mestre, evidência aplicável
VOCABULARIO:            os nomes canónicos que tem de usar (dicionário §3)
OUTPUT_ESPERADO:
FILES_IN_SCOPE:
FILES_OUT_OF_SCOPE:     explícito — é o que impede o alargamento silencioso
DEPENDENCIAS:
RESTRICOES:             ADRs e invariantes que não pode violar
VALIDACAO:              o comando ou verificação concreta que prova o resultado
CRITERIOS_DE_ACEITACAO:
RISCO:                  o que corre mal se esta task estiver errada
```

`FILES_OUT_OF_SCOPE` merece atenção especial. Listar o que **não** se toca é mais eficaz do que
listar o que se toca: o segundo é uma sugestão, o primeiro é uma fronteira. Neste repositório os
candidatos permanentes são:

- `specs/INDICE.md` (o backlog mestre — alterado por um só agente, de preferência por script);
- `specs/02_Dicionario_de_Dados_Canonico.md` (o vocabulário);
- `docs/tecnica/00_Arquitectura_Solucao.md` (ADRs e decisões abertas);
- `specs/00_KAMBA_Carta.md` (registo de decisões e DoD);
- `docs/00-KAMBA-documento-mestre.md` (artefacto compilado; nunca editado à mão).

`VOCABULARIO` é o campo que este repositório pagou para aprender. Sem ele, cada escritor escolhe
nomes razoáveis e diferentes.

---

## Grafo e estados

Modela as dependências antes de começar. Uma task só arranca quando as obrigatórias estiverem
satisfeitas.

```text
TASK-A ─────┐
            ├──> TASK-C ───> TASK-E
TASK-B ─────┘
                 ↑
TASK-D ──────────┘
```

Estados no caminho feliz:

```text
PENDING → ANALYZED → READY → PRODUCING → PRODUCED
        → SELF-VALIDATED → UNDER-REVIEW → REVIEWED
        → INTEGRATING → INTEGRATED → SET-VERIFIED
        → COMPLETENESS-VALIDATED → DONE
```

Estados de paragem:

```text
BLOCKED        dependência não satisfeita, ou informação em falta
FAILED         a task correu e não produziu o resultado
NEEDS-REWORK   produziu resultado, mas a revisão encontrou defeito
```

A distinção entre `PRODUCED` e `DONE` é o ponto todo desta lista. São dez estados de distância, e
a maioria das entregas prematuras acontece por alguém tratar os dois como sinónimos.

---

## Dependências no backlog

Quando a tarefa toca tickets `KAM-NNN`, o grafo não é teu: está no `specs/INDICE.md` §4. Três
invariantes que a verificação tem de impor, porque cada um já foi violado aqui:

| Invariante | Porque importa | Como falhou |
|---|---|---|
| **Sem ciclos** | um ciclo torna o arranque impossível | `KAM-027` exigia o gate golden, que vem de `KAM-040`, que depende de `KAM-031`, que depende de `KAM-027` |
| **Sem prioridade invertida** | um P0 que depende de um P1 não é P0 | doze casos, incluindo o gate do Piloto a depender de tickets P1 |
| **Sem fase invertida** | uma capacidade de fase 0 que depende de fase 1 não cabe na fase 0 | `search_catalog` (fase 0) precisava do índice (`KAM-061`, fase 1) |

E uma regra de propagação: **o campo `Bloqueia` é derivado**, nunca escrito à mão. É o inverso
das dependências em todo o backlog. Alterar uma dependência muda o `Bloqueia` de outro ticket,
noutro ficheiro — por isso a sincronia mestre↔epics corre por script e repete-se até estabilizar.

---

## Recuperação de falhas

Não repitas a mesma tentativa à espera de resultado diferente. Classifica primeiro:

```text
FAILED → CLASSIFICAR → estratégia → repetir ou reatribuir → validar
```

| Classe | Sintoma | Estratégia |
|---|---|---|
| **LOCAL** | erro no que foi escrito agora | corrigir e repetir a mesma task |
| **VOCABULÁRIO** | nomes divergentes entre resultados | fixar o dicionário primeiro; só depois repetir |
| **DEPENDÊNCIA** | falta algo que outra task devia ter produzido | voltar ao grafo; a dependência estava mal modelada |
| **CONTEXTO** | o agente não tinha informação suficiente | enriquecer o contrato do agente e reatribuir |
| **DESENHO** | a solução está errada, não a execução | voltar ao Architect; produzir melhor não salva |
| **EVIDÊNCIA** | a decisão dependia de um facto que não existe | parar; abrir pergunta escrita, spike ou parecer |

Duas falhas seguidas da mesma classe significam que a classificação está errada. Sobe um nível:
se dois `LOCAL` seguidos, provavelmente é `DESENHO`; se dois `LOCAL` em agentes diferentes,
quase certamente é `VOCABULÁRIO`.

A classe `EVIDÊNCIA` é a que não se resolve com mais trabalho. Quando a bloqueia é a resposta da
Meta, do banco ou do advogado, a saída é registar a decisão aberta (D#) com dono e escalada, e
avançar no que não depende dela.

---

## Estado de execução

Para execuções longas, mantém `.claude/state/execution-state.md`. O critério é simples: o estado
tem de permitir retomar **sem depender do histórico da conversa**. É transitório — não é fonte de
verdade, e o conhecimento durável vai para os sítios da tabela do `SKILL.md` §8.

```markdown
# Execution State

## Objectivo
...

## Fase actual
PRODUCING

## Tasks
| ID | Estado | Agente | Dependências |
|----|--------|--------|--------------|
| T01 | DONE | Explorer | - |
| T02 | DONE | Architect | T01 |
| T03 | PRODUCING | Implementer | T02 |
| T04 | READY | Reviewer | T03 |

## Vocabulário fixado
- ... (nomes canónicos decididos nesta execução, e onde foram registados)

## Riscos
- ...

## Decisões
- ... (com a justificação, não só a escolha)

## Bloqueios
- ... (e se é decisão aberta D#, com dono)

## Evidência
- ... (verificação corrida → o que provou)

## Próxima acção
- ...
```

A secção **Decisões** é a que salva a retoma. Uma escolha registada sem o porquê obriga a refazer
o raciocínio — que é exactamente o custo que este ficheiro existe para evitar. A secção
**Vocabulário fixado** evita que uma retoma reintroduza a divergência que a execução já resolveu.

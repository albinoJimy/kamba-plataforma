"""Gate 3c — lint de coerencia do backlog (mestre <-> epics). KAM-138.

O backlog diz as mesmas coisas em tres sitios, e ate aqui nada os comparava:

1. a **linha** do ticket em `specs/INDICE.md` §4, o «contrato entre epics»;
2. o **bloco** `## KAM-NNN — `, em `specs/tickets/KAM-NNN.md` (EPIC-01, pela
   convencao do KAM-155) ou dentro de `specs/EPIC-XX_*.md` (os outros dez);
3. a **«Tabela Resumo de Tickets»** do §3 de cada epic.

Tipo, estimativa, prioridade, fase e dependencias estao replicados nos tres, e
a verificacao era manual: tres tickets seguidos (KAM-128, KAM-129, KAM-130)
gastaram um criterio de aceitacao em «segunda passagem de verificacao da 0
divergencias». A verificacao manual e precisamente o que falha quando ha pressa,
e falhou: o KAM-144 teve de repor oito arestas do grafo que se perderam, e
registou por escrito que a causa era este *gate* nao existir.

**O que distingue este gate de uma comparacao de tabelas** e a reciprocidade
`Dependencias`<->`Bloqueia`. O §4 **nao tem coluna `Bloqueia`**, pelo que
comparar so os campos que as duas superficies partilham deixa passar uma aresta
declarada de um so lado — foi o que aconteceu na primeira versao do KAM-129 (a
busca G5) e outra vez nos oito tickets do KAM-144. Um lint que se limitasse aos
campos herdava esse buraco e dava uma falsa garantia, que e pior do que nao ter
lint nenhum.

**O gate nao decide qual dos lados esta certo**: reporta os dois valores e
falha. O §4 e o contrato e o bloco e a especificacao; qual deles se corrige e de
quem escreveu o ticket. Um lint que escolhesse por omissao esconderia metade dos
defeitos ao «corrigi-los».

**Fail-closed sobre a propria entrada** (codigo 2, nao «nada a reportar»): um
epic que o parser nao leia, um bloco sem tabela de campos, um campo obrigatorio
ausente, ou uma populacao abaixo do minimo escrito a mao. Um lint de coerencia
que de verde por nao ter conseguido ler nada e o modo de falha que ele existe
para nao ter.
"""

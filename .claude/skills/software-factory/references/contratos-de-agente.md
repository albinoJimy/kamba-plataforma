# Papéis, contratos e resultados de agente

Lê este ficheiro quando fores lançar um subagente, decidir que contexto lhe dar, ou definir o que
ele tem de devolver.

- [Os seis papéis](#os-seis-papéis)
- [Contrato do agente](#contrato-do-agente)
- [O contrato mínimo de um escritor](#o-contrato-mínimo-de-um-escritor)
- [Controlo de contexto](#controlo-de-contexto)
- [Resultado obrigatório](#resultado-obrigatório)
- [Conflito entre agentes](#conflito-entre-agentes)

---

## Os seis papéis

Um papel é uma **restrição**, não um rótulo. O valor vem do que o agente está proibido de fazer:
um Explorer que escreve deixou de ser uma segunda opinião e passou a ser mais uma fonte por
rever.

| Papel | Responsabilidade | Não deve | `subagent_type` |
|---|---|---|---|
| **Explorer** | descoberta, mapeamento do conjunto, dependências, levantamento de afirmações existentes | produzir conteúdo; é read-only por construção | `Explore` |
| **Researcher** | pesquisa externa com fonte, URL, data e estado de verificação | decidir desenho a partir do que encontrou | `general-purpose` |
| **Architect** | desenho, análise de impacto, ADRs, decisões, riscos | escrever o conjunto todo para testar uma hipótese | `Plan` |
| **Writer / Implementer** | produzir o documento ou o código dentro do escopo, nos nomes canónicos | alargar o escopo ou inventar vocabulário | `general-purpose` |
| **Reviewer** | revisão independente, procura de defeitos, comparação com requisitos | ver o raciocínio de quem produziu | `general-purpose` ou `Skill(code-review)` |
| **Integrator** | integração, conflitos, verificação transversal, estado final | aceitar alteração inesperada sem investigar | agente principal |

**Sobre o Researcher.** O resultado tem de trazer estado por afirmação. Um relatório de pesquisa
sem **CONFIRMADO / INDÍCIO / NÃO VERIFICADO** por linha é pior do que nenhum: parece evidência e
não é. Exige também que diga **como leu** a fonte — uma página lida por sumarizador automático
não sustenta um preço num contrato, e tem de o declarar.

**Sobre o Reviewer.** A independência é o mecanismo, não a etiqueta. Um subagente a quem entregas
a tua justificação vai avaliá-la, não o resultado. Dá-lhe o documento e os requisitos; guarda o
raciocínio para ti.

**Sobre o Writer.** O modo de falha característico aqui não é escrever mal: é **escolher nomes
razoáveis e diferentes dos do vizinho**. Por isso o vocabulário é parte do contrato, não uma
sugestão.

---

## Contrato do agente

Um subagente começa sem o teu contexto. O contrato existe para lhe dar o suficiente sem lhe dar
tudo — e para tornar o âmbito explícito o bastante para se saber, depois, se foi respeitado.

```text
ROLE:
TASK:
OBJECTIVE:
CONTEXT:                  o mínimo que torna a tarefa compreensível
KNOWN_FACTS:              o que já está estabelecido e não precisa de ser redescoberto
VOCABULARY:               nomes canónicos obrigatórios + onde estão (dicionário §3)
SOURCES_OF_TRUTH:         por ordem, e o que está desactualizado
EVIDENCE_RULES:           como atribuir CONFIRMADO / INDÍCIO / NÃO VERIFICADO e proposta
ASSUMPTIONS_ALLOWED:      onde pode decidir sozinho
ASSUMPTIONS_FORBIDDEN:    onde tem de parar e declarar
FILES_IN_SCOPE:
FILES_OUT_OF_SCOPE:
DEPENDENCIES:
CONSTRAINTS:              ADRs e invariantes que não pode violar
ACCEPTANCE_CRITERIA:
VALIDATION_REQUIRED:      a verificação que tem de correr
EXPECTED_EVIDENCE:        o que tem de trazer como prova
```

`KNOWN_FACTS` é o campo que mais poupa. Sem ele, cada subagente refaz a discovery — e dois
agentes a explorar o mesmo conjunto chegam a conclusões ligeiramente diferentes, o que produz
conflitos que não existiam.

`ASSUMPTIONS_FORBIDDEN` é o que mais evita retrabalho. Neste repositório, os candidatos
permanentes:

- não assumir que a coexistência funciona em `+244` (NÃO VERIFICADO; depende de spike);
- não assumir que a Meta autoriza um número agregador (NÃO VERIFICADO; decisão D2);
- não assumir prazos ou custos de banco, facilitador, Meta ou fornecedor sem fonte;
- não assumir que uma ferramenta pode ser exposta a tenants sem ler a licença;
- não assumir que um documento da biblioteca `01`–`13` está actualizado;
- não assumir que um nome existe no dicionário — confirmar, e se não existir, propô-lo;
- não assumir que um DDL ou diagrama está correcto por «parecer» correcto.

---

## O contrato mínimo de um escritor

Quando lanças agentes a produzir documentos em paralelo, estes cinco campos são o que separa um
conjunto coerente de cinco documentos que se contradizem. Foi a lição desta sessão: cinco
redactores competentes, sem vocabulário comum, produziram três esquemas para a mesma tabela.

```text
1. SOURCES_OF_TRUTH    a ordem, e o aviso de que a biblioteca exploratória está desactualizada
2. VOCABULARY          o dicionário, e a ordem de o usar em vez de inventar
3. CONTRACT_LINE       a linha do backlog mestre, se houver — é fixa e não se altera
4. EVIDENCE_RULES      a escala de três estados e a marca "proposta" para valores não calibrados
5. FILES_OUT_OF_SCOPE  o canon (dicionário, ADRs, backlog mestre, Carta) e os ficheiros de outros agentes
```

E duas instruções que valem a pena repetir em cada contrato:

- **devolve os problemas que encontraste no que recebeste** (dependências em falta, contradições,
  nomes divergentes), sem os corrigir — quem integra decide;
- **não edites ficheiros de outros agentes**, mesmo que vejas um defeito lá.

A primeira transforma cada escritor num revisor passivo do canon, de graça. Nesta sessão, foi
assim que as ~60 dependências em falta e as contradições entre documentos vieram à superfície.

---

## Controlo de contexto

Contexto a mais é tão prejudicial como contexto a menos: dilui o sinal e faz o agente atender ao
que é acessível em vez do que é relevante.

```text
CONTEXTO DA TASK → DOCUMENTOS RELEVANTES → CANON (ADRs, dicionário) → EVIDÊNCIA
   → CONHECIMENTO RELEVANTE → só então, contexto mais largo
```

O contexto deve ser suficiente, preciso, relevante, verificável e **delimitado**. Prefere apontar
caminhos e secções (`docs/tecnica/00_Arquitectura_Solucao.md` §8, `specs/INDICE.md` §4) a colar
blocos: o agente lê o que precisa e vê a vizinhança, que os teus excertos escondem.

Um aviso específico: os documentos deste conjunto são grandes (vários acima de 700 linhas, um com
mais de 1.300). Mandar «lê o conjunto todo» gasta a janela do agente sem lhe dar foco. Diz qual
documento e qual secção, e manda-o ler **inteiro** só o que é o objecto da task.

---

## Resultado obrigatório

Não aceites `"Feito"`. Um agente que reporta sucesso sem estrutura não deixou nada verificável
para trás — e a verificação é o único produto que interessa.

```text
RESULTADO DO AGENTE

Task:
Estado:                   (dos estados do grafo, não "ok")

Produzido:
- ...

Ficheiros alterados:
- ...                     (com nº de linhas, se foi redacção)

Validação:
- ...                     (verificação corrida → resultado)

Evidência:
- ...                     (o que sustenta cada afirmação acima, com estado)

Suposições e propostas:
- ...                     (valores não calibrados, nomes novos, decisões tomadas sozinho)

Problemas no que recebi:
- ...                     (dependências em falta, contradições, nomes divergentes — sem corrigir)

Riscos:
- ...

Limitações conhecidas:
- ...                     (o que não verificou, e porquê)

Próximo passo recomendado:
- ...
```

**Suposições, Riscos e Limitações vazios são suspeitos.** Trabalho real produz incerteza
residual. Três secções vazias significam quase sempre que o agente não procurou, não que não
havia.

A secção **Problemas no que recebi** é a mais valiosa das nove, e a que os agentes omitem se não
for pedida explicitamente.

---

## Conflito entre agentes

Dois agentes com conclusões incompatíveis é um sinal valioso — normalmente aponta para
ambiguidade real na fonte de verdade. Desperdiçá-lo aceitando o último resultado é o erro caro.

1. Não escolher automaticamente o mais recente.
2. Preservar **ambas** as evidências.
3. Identificar a origem: contexto diferente? fonte diferente? vocabulário em falta?
   interpretação diferente do mesmo texto?
4. Comparar com a fonte de verdade (ordem de precedência no `SKILL.md`).
5. Pedir nova análise se nenhuma das duas resolver.
6. Registar a decisão, **e propagá-la** a todos os documentos que afirmam o mesmo.

```text
RESOLUÇÃO DE CONFLITO

Conflito:
Agente A:
Agente B:
Evidência A:
Evidência B:
Fonte de verdade consultada:
Decisão:
Razão:
Propagação:              (documentos corrigidos)
Validação:
```

Se a origem for **vocabulário em falta**, a correcção é o dicionário, não a escolha entre os
dois. Se for **interpretação diferente do mesmo texto**, o defeito está no texto: corrige o
documento, o ADR ou o ticket — senão o conflito volta na próxima execução.

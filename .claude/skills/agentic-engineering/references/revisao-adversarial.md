# Revisão adversarial, evidência e regressão

Lê este ficheiro quando estiveres a rever — o teu trabalho ou o de outro agente.

- [O guião](#o-guião)
- [Evidência antes de conclusão](#evidência-antes-de-conclusão)
- [Regressão documental](#regressão-documental)
- [Padrões de defeito neste repositório](#padrões-de-defeito-neste-repositório)
- [Onde fica a revisão](#onde-fica-a-revisão)

---

## O guião

A revisão procura razões para o resultado estar **errado**. Se terminas a rever e não encontraste
nada, a pergunta seguinte não é «está bom?» — é «que classe de defeito é que eu não procurei?».

```text
Que afirmação aqui tem mais confiança do que a evidência sustenta?

Que número apareceu sem fonte e passou a requisito?

Que documento do conjunto fica a contradizer este?

Que decisão foi tomada em silêncio entre duas fontes que discordavam?

Que requisito do ticket pode ter ficado de fora?

Que consumidor deste desenho quebra — ticket, documento, gate, decisão aberta?

O critério de aceitação pode estar satisfeito pela razão errada?

Que nome foi inventado e não está no dicionário?

Que contagem, total ou índice ficou desactualizado?

Existe forma mais simples que preserve o significado?
```

**«O critério de aceitação pode estar satisfeito pela razão errada?»** é a pergunta com melhor
retorno. Formas comuns de um critério verde não provar nada neste repositório:

- o critério verifica a **existência** de uma secção, não o que ela diz;
- o critério é sobre um documento que o ticket escreveu, e não sobre o sistema que descreve;
- a verificação correu sobre o ficheiro errado, ou sobre uma cópia;
- o script de verificação corrigiu e verificou na mesma passagem — passou porque acabou de
  escrever o que foi verificar;
- o diagrama «está correcto» porque foi escrito com cuidado, mas nunca passou por um parser;
- o DDL «está correcto» por leitura, e nunca correu contra um Postgres.

Os dois últimos têm verificação directa e barata. Fá-la.

---

## Evidência antes de conclusão

Cada afirmação relevante precisa de evidência nomeada.

```text
AFIRMAÇÃO: "O backlog está consistente."
EVIDÊNCIA:
- script de consistência sobre specs/INDICE.md §4 → 127 tickets, 0 erros (ciclos,
  prioridade invertida, fase invertida, dependências inexistentes);
- 127 blocos únicos `## KAM-NNN — ` nos 11 epics, 0 duplicados, 0 em falta;
- segunda passagem da sincronia mestre↔epics → 0 divergências.
```

Cita a verificação **pelo que ela faz e pelo resultado**, não pelo nome. «Corri o script de
verificação» não é evidência; «127 tickets, 0 erros de consistência» é.

E separa o que verificaste do que não verificaste. Nesta sessão, o conjunto de specs foi
verificado na estrutura (referências, grafo, unicidade, sincronia) e **não** foi lido linha a
linha; o SQL nunca correu. As duas coisas têm de aparecer no relatório.

---

## Regressão documental

Toda a alteração tem três partes, e a segunda é a que ninguém verifica:

```text
AFIRMAÇÃO NOVA  +  AFIRMAÇÃO PRESERVADA  +  CONTRADIÇÃO POSSÍVEL
```

Perguntas obrigatórias:

- Que outros documentos afirmam o que eu acabei de mudar? (`Grep`, não memória)
- Algum ADR passou a ser contrariado sem ser substituído?
- Alguma decisão aberta foi tratada como fechada?
- Algum nome mudou de significado sem passar pelo dicionário?
- Alguma capacidade mudou de fase sem se verificar quem depende dela?
- Alguma contagem, total ou tabela-resumo ficou a dizer o número antigo?
- Algum documento que repetia a versão antiga **continua a repeti-la** porque ninguém olhou?

A última é a assinatura do defeito mais caro deste conjunto. Quando o `docs/tecnica/04` corrigiu a
unicidade do ledger, o `docs/tecnica/08` ficou com a versão antiga — e nenhum dos dois documentos
sabia do outro.

---

## Padrões de defeito neste repositório

Estes padrões não são hipotéticos: todos foram encontrados neste conjunto. Procura-os por nome.

**Afirmação promovida de estado.** Um INDÍCIO citado como CONFIRMADO, ou uma leitura por
sumarizador apresentada como fonte primária. É o defeito mais comum e o mais difícil de ver
depois, porque a frase parece sólida. Antídoto: herdar sempre o estado da fonte, e dizer como
foi lida.

**Número proposto endurecido em requisito.** Um valor que eu escolhi numa conversa aparece três
documentos depois com ar de medição — tectos, limiares, volumes, metas de latência. Antídoto:
marca *proposta* e diz onde se calibra, no sítio onde o número aparece.

**Divergência de vocabulário entre escritores paralelos.** Três esquemas de `contacts`, três
tabelas de consentimento, `valor_kz` contra `valor_minor`, dois eventos para a mesma confirmação
de pagamento. Nenhum escritor errou; faltava dicionário. Antídoto: fixar o vocabulário antes de
paralelizar.

**Documento que fica a contradizer depois de uma correcção.** O vizinho que repetia a versão
antiga não se corrige sozinho. Antídoto: procurar quem mais afirma o mesmo, antes de fechar.

**Dependência em falta e prioridade invertida.** Um P0 que depende de um P1, um ticket que usa o
que outro produz sem o declarar. Cerca de 60 casos neste backlog, nenhum visível na leitura.
Antídoto: grafo verificado por script.

**Ciclo de dependências.** `KAM-027` exigia o gate golden, que vem de `KAM-040`, que depende de
`KAM-031`, que depende de `KAM-027`. Um ciclo não se vê a ler tickets um a um.

**Fase invertida.** Uma capacidade de fase 0 que depende de um ticket de fase 1 — o
`search_catalog` a precisar do índice. Torna o plano de fases impossível sem ninguém notar.

**Gate que não bloqueia o que diz bloquear.** O gate do Piloto não dependia do inventário de
subprocessadores nem da revisão de segurança, apesar de a Carta os exigir no DoD. Um gate é só
tão forte como as suas dependências declaradas.

**Capacidade atribuída a ferramenta cuja licença não a permite.** Typebot e n8n em fluxos de
tenants, publicação automática em redes sem App Review, MinIO depois de arquivado. Antídoto: ler
a licença e os termos antes de desenhar sobre a ferramenta.

**Verificação que valida o próprio trabalho.** Um script que corrige e verifica na mesma passagem
passa sempre. Antídoto: modo de verificação primeiro, escrita depois, e segunda passagem a dar
zero.

**Contagem desactualizada.** «12 ADRs» quando são 20, «13 documentos activos» quando são 12,
totais por epic que não somam. É a assinatura típica de uma alteração feita a meio — e o sinal
mais fácil de procurar.

**Decisão do utilizador apresentada como facto estabelecido.** Uma escolha do fundador é uma
decisão, não uma validação de mercado. A Carta, o dicionário e a classificação dos ADRs são
**propostas** até ratificação; apresentá-las como decididas engana quem ler depois.

---

## Onde fica a revisão

As análises adversariais deste conjunto vivem em `docs/analises/ANALISE-NN-<slug>.md`, com:

- **objecto** (o que foi revisto, em que versão);
- **método** (como foi atacado);
- **achados classificados** por gravidade, com evidência por achado;
- **veredicto** explícito;
- o que **não** foi revisto.

A última secção é a que dá honestidade ao resto. Uma revisão que não declara o seu âmbito
convida a ser lida como mais completa do que foi.

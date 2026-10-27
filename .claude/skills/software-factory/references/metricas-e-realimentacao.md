# Métricas e realimentação

Lê este ficheiro quando fechares uma linha e for preciso converter o que aprendeste em portão.

- [Seis indicadores](#seis-indicadores)
- [Um escape vira portão](#um-escape-vira-portão)
- [O que faz de um portão um portão](#o-que-faz-de-um-portão-um-portão)
- [Padrões de escape neste repositório](#padrões-de-escape-neste-repositório)

---

## Seis indicadores

Uma fábrica que não se mede não melhora — repete. Seis indicadores, e a coluna que importa é a do
instrumento: é ela que separa medição de intenção.

| Indicador | Onde se lê | Instrumento |
|---|---|---|
| **Verde à primeira** | `gh pr checks <n>`, primeira corrida | artefacto do GitHub |
| **Tempo até merge** | abertura do PR → squash | artefacto do GitHub |
| **Caixas por marcar** | as do ticket, contadas ao declarar entregue | o bloco do ticket |
| **Calibração** | achados `CONFIRMADO` / achados levantados | **sem instrumento** |
| **Taxa de retrabalho** | achados pós-feito / entregas declaradas | **sem instrumento** |
| **Escapes por portão** | achados com o portão que os devia ter apanhado | **sem instrumento** |

### Os três primeiros leem-se; os três últimos reconstroem-se

Os três de cima saem de artefactos que o repositório já produz, e a leitura é directa.

Os três de baixo **não têm instrumento aqui**. Reconstroem-se à mão, das análises em
`docs/analises/ANALISE-NN-<slug>.md` contra os PRs do período. Diz isso quando citares um deles:
um número reconstruído é **INDÍCIO**, nunca **CONFIRMADO**, e uma taxa sem denominador escrito
não é `0%` — é **desconhecida**.

**Porque é que isto não é um gate.** Um ledger destes é observação do agora, e no runner não
haveria o que ler: um gate que passa sempre é pior do que verificação nenhuma. E versioná-lo em
`specs/` ou `docs/` tornava-o invisível entre ramos até ao merge, que é quando a divergência já
custou o trabalho.

Três notas sobre como se leem:

**«Caixas por marcar» é o indicador desta casa.** O KAM-001, o KAM-002, o KAM-128 e o KAM-129
foram entregues com PR verde e deixaram **62 caixas por marcar** entre os quatro, sem que nenhum
relatório o mencionasse — a diferença entre «entregue» e «fechado» desapareceu sem ninguém
decidir. Conta-as ao declarar entregue, não depois. E atenção ao sentido inverso: uma **caixa por
marcar não é trabalho por fazer** — o EPIC-02 tem os treze tickets fundidos e, das 71 caixas
vazias que a auditoria de 2026-10-23 contou, **só sete esperam genuinamente um terceiro**; as
outras repartem-se por revisores humanos, caixas derivadas e trabalho que o KAM-115 entregou
depois. Lê `docs/epic-02-divida-de-criterios.md` antes de somar: hoje o ficheiro do epic tem 62
vazias, e tomar esse número por trabalho em falta inverte a lição.

**A taxa de retrabalho é a que não mente.** O *throughput* sobe facilmente com agentes, e há
relatos públicos de que a estabilidade de entrega desce ao mesmo tempo — **INDÍCIO**, sem fonte
primária citada aqui e sem anexo em `docs/tecnica/evidencia/`; não o cites como CONFIRMADO num
relatório, e se o quiseres usar como requisito, abre o anexo primeiro. O que não precisa de
evidência externa é a aritmética: contar PRs, tickets ou linhas premeia exactamente o
comportamento que esta fábrica existe para travar.

**A calibração corta nos dois sentidos.** Perto de 100% de achados confirmados significa que a
revisão só procurou o óbvio. Perto de 0% significa que está a produzir ruído. Qual é a ordem de
grandeza saudável **neste** repositório é hoje `NÃO VERIFICADO` — não importes o número de outro
conjunto para aqui.

---

## Um escape vira portão

> **Um escape que um portão podia ter apanhado vira portão.** Não vira aviso, não vira nota de
> rodapé, não vira «ter cuidado da próxima vez».

Uma nota depende de alguém se lembrar de a ler — e esquecer-se é indistinguível do caso correcto,
que é a definição do defeito que a nota pretendia evitar.

### Isto não contradiz «sem gates novos»

A decisão do fundador de Outubro de 2026 recusa **cerimónia** nova no ciclo de um ticket:
segundas leituras, passagens repetidas, configuração por ticket. Um portão mecânico vai no
sentido oposto — substitui vigilância humana por uma verificação que não se esquece, e por isso
*reduz* cerimónia em vez de a acrescentar.

E há a razão prática, que o próprio repositório já escreveu: **um *job* novo acrescenta um
contexto exigido ao *ruleset* de `main`**, e isso é alteração de regra de bloqueio, que precisa do
fundador. A forma que este repositório usa é **entrar num gate que já existe**:

- o `log-lint` do KAM-068 entrou no **gate 2**, não num *job* próprio;
- o X-11 entrou no **gate 6**, pela mesma razão;
- o `lint_handoff` (KAM-145) e o `lint_contagens` (KAM-158) entraram como passos do **gate 3**;
- a parte dos webhooks da Meta (KAM-024) entrou no **gate 7** — «um gate por ticket é como se
  perde a conta aos gates».

O 3b e o 3c são a excepção, e a razão está escrita no `Makefile`: separaram-se porque a mensagem
de falha deixava de dizer qual dos dois falhou. E o *job* do 3c entra nos `needs` do agregador e
**não** nos `required_status_checks` espelhados em `.github/rulesets/main.json` — o bloqueio chega
pelo agregador, sem tocar nos sete contextos.

### Classifica primeiro

Há três destinos legítimos, e a escolha não é de gosto:

```text
ESCAPE → classificar → PASSO NUM GATE QUE EXISTE | GATE ALARGADO | PADRÃO NOMEADO
```

| Destino | Quando | Exemplo deste repositório |
|---|---|---|
| **Passo num gate que existe** | a classe de defeito é verificável mecanicamente e nenhum passo a cobre | `lint_contagens` no gate 3 — contagens em prosa confrontadas com a fonte que as conta |
| **Gate alargado** | existe verificação para a classe, mas a varredura não chegava ao sítio | a **segunda passagem** do gate 9, sobre os *blobs* que o PR acrescenta à história; a medição do AGR no gate 4 (KAM-151), que estava no âmbito declarado e não era medida |
| **Padrão nomeado** | o defeito exige julgamento e não se reduz a um predicado | os padrões em [`revisao-adversarial.md`](revisao-adversarial.md) |

**O terceiro destino é o último recurso, não o primeiro.** Escolher «padrão nomeado» porque é
mais rápido do que escrever o passo é precisamente a troca que esta regra proíbe.

E um gate novo de corpo inteiro — como o 3c foi — é legítimo quando a mensagem de falha o exige,
mas custa um pedido ao fundador se for para *required check*. Diz isso quando o propuseres.

### Depois de fechar o escape, pergunta se a forma é partilhada

Um defeito de **forma** — um nome que não respeita o dicionário, um valor por omissão que
significa «sem barreiras», uma configuração que degrada em silêncio — raramente está num sítio só.

```text
Fechei o defeito aqui.
Quantos outros sítios têm esta forma?
A verificação que acabei de escrever varre-os todos, ou só o meu?
```

---

## O que faz de um portão um portão

Escrever um gate que não impede nada é pior do que não o escrever: produz verde e consome
confiança. Cinco testes, e qualquer um que falhe desqualifica o portão.

**1. O canário prova-se no gate, não num `unittest`.** É o padrão desta casa, e nasceu de um
defeito real: um teste de `lint_refs` esteve vermelho desde que o alvo de cobertura nasceu, e o
gate passou verde em sete PRs porque o alvo engolia o código de saída. As fixtures negativas
**têm de falhar**, cada uma pela sua regra, dentro do gate — é assim no 3b, no 9, no 11 e no
`log-lint`.

**2. Não engolir o código de saída.** `|| true`, `>/dev/null 2>&1` por cima de um `|| echo
aviso`, um `-ErrorAction SilentlyContinue`: qualquer um transforma uma medição numa decoração. O
`coverage-node` media a cobertura do código que os testes cobriam e nunca olhava para o resultado
deles — um teste quebrado passava o gate verde.

**3. Não fail-open onde não tem com que colidir.** Um gate que passa sempre no runner porque ali
não existe a condição que ele persegue é fail-open silencioso. É por isso que uma verificação de
colisão entre sessões não é gate de CI ([`isolamento.md`](isolamento.md)).

**4. Não é lista escrita à mão.** Um detector que partilha o modo de falha do defeito que
persegue — esquecer uma entrada produz o mesmo silêncio que esquecer a chamada — não serve.
Deriva a lista do registo único por onde tudo passa: as suites de `tools/` descobrem-se do disco
(`SUITES_DE_TOOLS`) porque eram duas listas à mão e uma suite nova ficava fora das duas; a lista
de exclusões do `coverage-node` pede-se ao `coverage_gate`, que é quem depois classifica.

**5. O controlo negativo tem de ter alvo.** «Não encontrou nada» testado sobre um padrão que casa
zero por erro de escapamento passa com qualquer implementação. O X-11 varre primeiro os
identificadores **na entrada** (controlo positivo) — sem isso, o zero achados não dizia nada.

E quando acrescentares um portão, pergunta: **como é que a ausência dele se torna visível?** Uma
verificação imposta por quem escreve se lembrar de a chamar é uma barreira por convenção, e o
esquecimento é indistinguível do caso correcto.

---

## Padrões de escape neste repositório

Catálogo curto do que já passou por tudo. Procura-os por nome antes de declarar uma revisão
feita.

**Os gates só correm sobre aquilo a que o ficheiro os expõe.** Um defeito de forma que não esteja
num ficheiro exercitado passa por todos os portões e pela revisão. Pergunta sempre qual é a
entrada que faria a verificação olhar para o teu caso — e **mede a superfície em vez de confiar
num comentário**: o `Makefile` diz que as superfícies `eventos` e `registo` do gate 3b «estão
hoje vazias», o `ci/canon-lint.yaml` corrige-o por escrito («estiveram VAZIAS e ja nao estao»), e
quem decide é o `canon_lint`, que hoje lê 23 migrações, **76** schemas de evento, **4** de registo
e 17 documentos. Um comentário desactualizado produz exactamente o escape que esta secção
cataloga.

**Verificação por leitura não apanha o que a máquina apanha.** A leitura dos relatórios dos
redactores não apanhou nenhuma das ~60 dependências em falta; o script apanhou todas, mais dois
ciclos e doze inversões de prioridade.

**Uma segunda passagem que muda algo não é verificação, é edição.** Corre até estabilizar.

**Medir uma vez apresenta não-determinismo como determinismo.** Uma corrida só não distingue
defeito de *flake*, e uma `PROVA INVALIDA` no relatório das mutações é a suite a falhar por carga
da máquina — conta como sobrevivente e baixa-se o paralelismo.

**A mutação local não equivale ao runner.** Um `kamba.pth` acrescentado à mão ao `site-packages`
faz a suite passar e esconde uma receita de cópia quebrada, que o runner descobre depois.

**A correcção pode ser pior do que o achado.** Rever o diff não é rever a correcção: trocar um
`fail-closed` por um aviso muda quem fica com o trabalho a meio, e escolher o guarda mais largo
«por ser seguro» já abriu regressões onde o estreito já estava garantido a montante.

**A negativa de um subagente é uma afirmação.** «Isso não existe no repositório» decide âmbito, e
já foi falso. Confirma com comando próprio, e usa `-F` quando procuras uma frase literal.

**Contagem não é medição.** Contar testes, tickets ou linhas premeia volume. Um aperto de
contrato vale como instrumento; uma contagem não.

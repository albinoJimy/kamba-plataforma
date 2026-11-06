# Medida de reaproveitamento por vertical — regras de contagem

| Campo | Valor |
|---|---|
| Documento | `docs/reuse-metric.md` |
| Versão | 1.1 |
| Estado | Proposta |
| Âmbito | A medida `reuso` do ADR-012, e a condição (d) da regra de dois |
| Fonte | `docs/tecnica/02_Agent_Runtime_Verticais.md` §5.4; `docs/tecnica/00_Arquitectura_Solucao.md` §13.2 |
| Ticket | KAM-039 |
| Instrumento | `tools/reuse_metric`, declarado em `ci/regra-de-dois.yaml` |

## 1. O que esta medida responde, e o que não responde

O ADR-012 afirma que uma vertical é configuração e não código: o runtime de
agentes serve o Vendedor e os Serviços sem código específico de vertical no
núcleo. O §5.4 dá a essa afirmação uma forma mensurável:

```text
reuso = 1 − LoC_específico / LoC_total
```

sobre o **caminho de execução** da vertical nova — «grafo + tools + prompts +
migrações» —, com limiar `≥ 70%`.

**Uma métrica sem regras de contagem escritas não se pode repetir nem
contestar**, e é por isso que este documento existe antes do número. A conta é
trivial; o que decide o resultado é o que entra em cada parcela. Duas pessoas de
boa-fé com a mesma fórmula e sem estas regras chegam a números diferentes — e
foi o que aconteceu ao escrever este ticket: a primeira contagem, feita com uma
lista de ficheiros escolhida à mão, deu **88,99%**; a mesma fórmula com o
caminho derivado deu **87,58%**. A diferença não era um erro de aritmética: era
uma lista generosa.

O que esta medida **não** responde:

- **não diz se o código corre.** Mede código escrito, não código executado.
  Para «corre ou não corre» há cobertura, que é o *gate* 4;
- **não diz se o reaproveitamento é bom.** Um núcleo com 95% de reuso e um
  defeito de isolamento é pior do que um com 70% e nenhum;
- **não substitui a condição (d).** As duas são independentes: uma vertical
  pode reaproveitar 90% do núcleo e ter-lhe acrescentado um `if` por vertical.

## 2. A unidade: linha com código, e não linha

A unidade é a **linha com código** (SLOC), medida por
`tools/reuse_metric/sloc.py`. Uma linha conta quando leva pelo menos um *token*
que não é comentário, não é estrutura do analisador, e não é uma *docstring* —
isto é, uma cadeia que seja, ela só, uma instrução de expressão.

**Porque não `wc -l`.** A convenção desta casa é comentar por extenso: o
`verticais/servicos/nos.py` tem 1435 linhas e **649** com código. Uma métrica em
linhas brutas não mede reaproveitamento, mede densidade de prosa — e move-se
quando alguém explica melhor uma decisão. Pior: com `wc -l`, acrescentar trinta
linhas de comentário ao `nos.py` de Serviços **baixava** o reuso sem acrescentar
uma instrução, e apagar comentários subia-o. Um número que se move ao contrário
do que afirma medir não se defende. Está preso por teste
(`TestMutacaoDaUnidade`, em `tools/reuse_metric/tests/test_sloc.py`): a prosa
não move a contagem, uma linha de código move.

Uma cadeia que é **valor** — um SQL, um texto de persona, um molde — conta como
código. Alguém a escreveu e alguém a mantém. A primeira versão do contador
excluía qualquer cadeia de três aspas e contava a menos.

## 3. As cinco classes

Cada ficheiro (ou símbolo) do caminho cai numa classe. As quatro declaráveis
estão em `ci/regra-de-dois.yaml`; o `partilhado` é o resto.

| Classe | Entra em | Significa |
|---|---|---|
| `especifico` | numerador **e** denominador | Código que existe só porque esta vertical existe |
| `partilhado` | denominador | Núcleo atravessado pelo caminho, e símbolos importados de ficheiros mistos |
| `misto` | — (resolve-se em símbolos) | Ficheiro de que a vertical importa **alguns** símbolos |
| `outra_vertical` | nem uma nem outra | Alcançado pelo caminho e pertencente à **outra** vertical |
| `excluido` | nada | Testes e código gerado. É um filtro, não uma classe |

O `excluido` decide-se **primeiro**, e não é um empate: ele retira do universo,
como os `excluidos` de `ci/thresholds.yaml`. Um `fakes.py` dentro de
`verticais/servicos/` bate em `especifico` e em `excluido`, e a resposta certa é
«fora da conta» — é código de ensaio, e o §5.4 manda excluir testes seja onde
for que vivam. Entre as outras três, **um ficheiro que bata em duas classes
levanta**: a ordem das linhas de um ficheiro de configuração não pode decidir se
um ficheiro vai ao numerador.

### As dez regras

**Regra 1 — o caminho deriva-se, não se lista.** O conjunto partilhado obtém-se
por **fecho de importação** a partir dos pontos de entrada declarados, seguindo
cada `import` por AST. Uma lista escrita à mão é a parte contestável de qualquer
métrica: quem a escreve escolhe o resultado, e ninguém distingue uma omissão de
uma decisão. Medido: a lista feita à mão com cuidado deixava de fora o
`tls/com.py`, o `tls/vendedor.py` e o `tls/catalogo.py` — e os três são
alcançados a partir do grafo de Serviços.

**Regra 2 — há dois pontos de entrada, e não um.** Um turno de Serviços entra
pelo grafo (mensagem do cliente) ou pelo consumidor de eventos (§6.3), e nenhum
alcança o outro. Com só o grafo, o `eventos/handlers.py` — onde vive o consumo
cruzado do critério (b) — ficava fora do denominador.

**Regra 3 — no ficheiro misto conta-se o símbolo, não o ficheiro.** Os doze nós
que Serviços reaproveita vivem no `verticais/vendedor/nos.py`, que tem 2168
linhas. Contar o ficheiro punha no partilhado 2168 linhas que ninguém
reaproveitou; não o contar escondia o reuso inteiro. Conta-se cada símbolo
importado, resolvido a partir dos `import` reais — e é isto que faz da métrica
uma **medida**: copiar um nó em vez de o importar faz o `import` desaparecer, o
símbolo sair do partilhado **e** o ficheiro específico crescer. O número desce
pelas duas pontas (`TestMutacaoACopiaBaixaOReuso`).

**Regra 4 — do ficheiro misto conta-se o símbolo importado, e não o que ele por
sua vez usa.** Um nó reaproveitado pode usar constantes do mesmo ficheiro que a
vertical nova não importa pelo nome. Essas não contam. Isto **subestima** o
partilhado, logo empurra o reuso para **baixo**: é a direcção conservadora, e
está escrita para que não se leia o número como um majorante.

**Regra 5 — excluem-se testes e código gerado**, como o §5.4 manda, e as duas
listas são concretas e não uma intenção:

- testes: `*/tests/*`, `*/test_*.py`, e os `*/fakes.py` — duplos de ensaio que
  vivem em `src/` e que **nenhum código de produção importa** (medido);
- gerado: `libs/py-core/src/kamba_core/eventos/contratos.py`, produzido por
  `python -m contract_diff gerar`. É alcançado pelo fecho e tem centenas de
  linhas; deixá-lo dentro enchia o denominador de código que ninguém escreveu.

**Regra 6 — as migrações entram pelas duas pontas, pela cadeia do Alembic.** São
o único termo do §5.4 sem grafo de importação: ninguém importa uma migração.
Declaradas só como `especifico`, mediam mal — as 387 linhas do esquema
`servicos` entravam no numerador e as ~1 000 linhas de `platform` sobre as quais
elas correm não entravam no denominador, e o reuso descia por assimetria de
contagem. A cadeia partilhada deriva-se do `down_revision`, que é a resposta que
já está no disco; o que se declara é quais migrações são **da vertical**.

O caso de fronteira está declarado com a razão: a `0026_codigos_de_agenda`
altera uma tabela **partilhada** (`platform.tool_audit`) para lhe acrescentar
dois códigos de erro da agenda. Pelo esquema que toca era partilhada; pela razão
de existir é da vertical, e é assim que conta. São **19** linhas, e a
classificação oposta move o reuso em menos de 0,2 pontos. O número está escrito
para que a fronteira se discuta com ele à vista.

**Regra 7 — o fecho de importação é um majorante do caminho de execução.** Um
módulo importado pode ter código que nunca corre num turno de Serviços. Isto
empurra o denominador — e portanto o reuso — para **cima**, que é a direcção
desfavorável à honestidade do número, e por isso fica escrito aqui e o relatório
nomeia o que ficou de fora. A alternativa, medir por execução, media **um**
turno e não a vertical: nenhuma conversa atravessa os vinte e dois nós.

**Regra 8 — «prompts» é um termo vazio nesta árvore, e declara-se vazio.** O
§5.4 põe «prompts» no caminho. Medido: não existe `prompts/`, não existe nenhum
`.j2`, e nenhum ficheiro ou pasta com `prompt` ou `persona` no nome. O que
existe é (i) texto de persona como configuração declarativa no bloco `persona:`
de `registry/<vertical>.yaml`, e (ii) o `compose`, o `safe_reply` e o
`ask_repeat`, que são **nós** e já contam como `especifico`. O `registry/` não
entra: o critério (d) exclui-o por extenso, e as 4 linhas do bloco `persona:` do `registry/servicos.yaml` (5 no do Vendedor) não são
linhas de código no mesmo sentido. Fica dito porque **uma ausência silenciosa
lê-se como zero**, e um `glob` que não encontra nada sem o dizer é a forma mais
limpa de uma métrica mentir.

**Regra 9 — o *backend* TypeScript das tools da vertical **não** entra, e isso
declara-se.** O §5.4 põe «tools» no caminho, e a medida conta o
`tls/servicos.py` (64 linhas) — que são os **modelos dos argumentos** das cinco
tools de Serviços. A implementação delas é TypeScript e vive no COM, em
`services/com/src/servicos/`: **1059 linhas de código**, que existem só porque
esta vertical existe, e não estão em nenhuma parcela. O instrumento mede
Python; medir TypeScript é trabalho de outro ticket.

Contado simetricamente — o Serviços TS ao numerador (1059) e a infra-estrutura
partilhada do COM ao denominador (`api`, `port`, `adapters`, `repo-base`: 1453;
o `orders` e o `produtos`, 3549, seriam `outra_vertical`) — o reuso dá
**83,77%**. Continua acima do limiar, e por isso a ausência não muda a
conclusão; fica escrita porque **uma ausência silenciosa lê-se como zero**, que
é a mesma razão da regra 8, e porque esta é a maior ausência da medida.

**Regra 10 — a cadeia das migrações é posicional, e numa cadeia linear isso é
uma data e não uma dependência.** A regra 6 deriva o conjunto partilhado dos
`down_revision`. Nesta árvore a cadeia é **estritamente linear** (`0001` ←
`0002` ← … ← `0032`), pelo que «antepassados da `0026`» é identicamente «todas
as migrações escritas antes de Serviços aterrar». Se a `0025_servicos` tivesse
sido numerada `0003`, o termo partilhado seria ~500 linhas em vez de 4866, com o
mesmo esquema e o mesmo código.

Das 4866, **2017 (41%)** são subsistemas que uma marcação nunca toca — saída de
canal, media, consentimento, modos de conversa, onboarding de canal,
coexistência, aviso ao dono, `llm_call_log`, `draft_decisions`. Sem elas o reuso
dá **86,36%** (medido, e o número do revisor para as 2017 linhas bateu);
sem migração nenhuma, 85,78%. **Nenhuma das variantes desce abaixo do
limiar**, e é por isso que a regra 6 fica como está em vez de se trocar por uma
heurística de esquema — mas quem citar o 88,26% tem de saber que **38%** do
denominador entra por posição na cadeia. Achado da revisão adversarial.

## 4. A condição (d), e porque é que um `grep` não serve

O §5.4 escreve a condição (d) como «nenhuma excepção no core (`grep` de nomes de
vertical em `core/` = 0)», e o bloco do KAM-039 acrescenta a exclusão de
`registry/` e dos testes.

**`core/` não existe como directório neste repositório.** A declaração nomeia o
que o substitui: `libs/py-core/src/kamba_core/` (o `core` literal: a biblioteca
partilhada) e `services/agr/src/kamba_agr/` **menos** `verticais/` e menos os
dois catálogos de tools por vertical.

Corrido à letra sobre esse núcleo, o `grep -iE 'vendedor|servicos|assistente'`
devolve **163** ocorrências em 30 dos 110 ficheiros. Um portão sobre esse número
seria um defeito, por duas razões independentes:

1. **118 das 163 são prosa** — comentários e *docstrings* a explicar **porque**
   é que o núcleo não depende de uma vertical. Um portão que as contasse
   obrigava a apagar a explicação para ficar verde;
2. **um `grep` não distingue as duas coisas que importam.** Estas duas linhas
   dão uma ocorrência cada:

   ```python
   TEXTOS = {("vendedor", "payment.confirmed"): "..."}   # tabela por vertical
   if estado["vertical"] == "vendedor": ...               # EXCEPÇÃO no núcleo
   ```

   A primeira é «verticais como configuração», que é a tese do ADR-012. A
   segunda é precisamente o que ele proíbe.

O verificador classifica cada ocorrência em três:

| Classe | É excepção? |
|---|---|
| `prosa` | comentário ou *docstring* — **nunca** |
| `conteudo` | literal numa tabela, ou identificador — configuração; conta-se e vai ao relatório |
| `dominio` | o ramo verifica que a vertical é **conhecida** — uma pertença a uma lista fechada com o domínio inteiro, ou uma asserção. Não distingue entre verticais: **não é excepção** |
| `fluxo` | o núcleo faz coisa **diferente** segundo **qual** vertical: igualdade, subconjunto próprio, `match`, mapa indexado pela vertical — **é a excepção** |

**A classe `dominio` é a correcção do achado mais sério da revisão
adversarial**, e sem ela a condição (d) era impossível de satisfazer. A primeira
versão só marcava literais escritos **dentro** da expressão de decisão, e o
idioma desta casa é a constante de módulo — pelo que o `contexto.py`, um
ficheiro de núcleo, tinha isto a passar como `conteudo`:

```python
VERTICAIS: Final = ("vendedor", "servicos")      # linha 71: `conteudo`
if valores["vertical"] not in VERTICAIS:         # linha 191: NADA
    raise InvocacaoInvalidaError("campo_invalido_vertical")
```

O verificador passou a seguir constantes de módulo. Mas pôr aquilo a reprovar
era errado por uma razão boa: uma lista **fechada** não distingue entre
verticais, e o critério 5 do KAM-014 **exige-a** por escrito («`assistente` por
igualdade não via `assistente_v2`»). O discriminante é mecânico — uma pertença
a um conjunto com o domínio inteiro é `dominio`; uma igualdade, um subconjunto
próprio, ou um **mapa** indexado pela vertical (onde os valores diferem por
construção) é `fluxo`. E os dois lados de uma pertença não são a mesma coisa:
em `if "vendedor" in texto` o nome está do lado da **agulha**, e isso é
despacho.

**A condição (d) é `fluxo == 0`, e hoje `fluxo = 1`.** O `conteudo` conta-se e nomeia-se, e **não**
reprova a condição por si: onde passa a fronteira entre «tabela indexada pela
vertical» e «excepção no núcleo» é decisão de quem assina o ADR-012 — não do
instrumento, e não de quem o escreveu. O que o instrumento garante é que a
decisão se toma sobre uma lista e não sobre uma impressão. A lista das 48
ocorrências de `conteudo` está em `docs/evidencia/KAM-039.md`.

**O limite honesto do verificador:** as quatro formas de `fluxo` que ele conhece
não são uma lista exaustiva das formas possíveis de escrever a excepção —
nenhuma lista o é. Uma excepção escrita por uma via que não esteja lá passa.
Cada uma das quatro tem canário de mutação em
`tools/reuse_metric/tests/test_nucleo.py`.

## 5. Isto não está ligado a nenhum portão, e porquê

Nem a condição (d) nem o limiar de 70% falham o *build* hoje. O bloco do KAM-039
pede as duas coisas («o CI falha se devolver > 0», «falha o *build* abaixo de
70%»), e as duas são **regras de bloqueio**: mudam o que impede uma fusão. Nesta
casa isso é decisão de quem as assina, e um *job* novo acrescenta um contexto
exigido ao *ruleset* da `main`, que é a mesma fronteira.

O que este ticket entrega é a **medição** e a prova de que ela morde nas duas
direcções. Ligar a máquina é uma linha, e está escrita abaixo para quem a
decidir:

```bash
make reuso
```

O alvo corre os dois comandos, escreve `ci/reuso.json` e `ci/nucleo.json`, e sai
com `1` se alguma das duas condições falhar. Entrar num *gate* que já existe —
como o `log-lint` entrou no *gate* 2 e o X-11 no 6 — é a forma que esta casa usa
para não acrescentar contexto exigido; qual, e se, é a decisão que fica em
aberto.

## 6. O resultado de hoje

Medido a 2026-11-05 com `make reuso`, no ramo do KAM-039 sobre a `main` em
`8f8ac19`. **O *commit* exacto nao se escreve aqui a mao:** o artefacto leva-o,
com a marca de arvore suja ao lado — foi um achado da revisao adversarial que
a afirmacao «medido em X» nao era verificavel pelo instrumento, e um numero
escrito a mao envelhece no *commit* seguinte.

| Medida | Valor |
|---|---|
| `reuso` da vertical Serviços | **88,29%** (limiar ≥ 70%) |
| `LoC_específico` | 1705 linhas com código |
| `LoC_partilhado` | 12 859 linhas com código |
| `LoC_total` | 14 564 linhas com código |
| Condição (d) — `fluxo` | **0** — era **1**, e a excepção era real; ver abaixo |
| `dominio` | 1 (validação por lista fechada; não é excepção) |
| `conteudo` | 45 ocorrências, em 5 de 110 ficheiros de núcleo |
| `prosa` | 118 ocorrências |
| Reprodutibilidade | duas execuções, `sha1` igual byte a byte |

**A condição (d) passa desde 2026-11-06, e a excepção que a fazia falhar tinha
nome:** `eventos/handlers.py:272`,
`dono_por = envelope.tipo if par in AO_DONO else None`. O `AO_DONO` era uma
tabela de pares `(vertical, tipo)` com entradas **só do Vendedor**, pelo que o
núcleo decidia ali, pelo nome da vertical, se o dono da loja era avisado. Foi
encontrada pela revisão adversarial do KAM-039, que obrigou o verificador a
seguir constantes de módulo — a primeira versão dava `fluxo = 0` porque só
olhava para literais escritos dentro da expressão de decisão, e o idioma desta
casa é a constante.

**Saiu para `subscriptions[].notifica` do `registry/<id>.yaml`**, por decisão do
fundador, e a condição (d) exclui o `registry/` da busca por extenso: é onde a
configuração por vertical pertence. Medido antes e depois, na mesma árvore
(`db0582d` como base): `fluxo 1 → 0`, saída `1 → 0`. O relatório está em
[`evidencia/KAM-039.md`](evidencia/KAM-039.md) §5.0.

**A extracção ensinou uma coisa sobre esta métrica, e é a razão 2 do §4 a
morder em código novo:** as guardas de arranque escritas contra as tabelas —
`par not in TEXTOS` — são elas próprias `fluxo`, porque um mapa indexado pela
vertical lido num teste é despacho seja qual for a intenção. A forma que diz o
que faz é ler o **conjunto de chaves** por um nome derivado. A primeira versão
das guardas deu `fluxo 3`, e o verificador tinha razão.

**A folga do limiar, sob os cinco enquadramentos defensáveis.** Nenhum deles
desce abaixo de 70%, e dizer os cinco vale mais do que defender um:

| Enquadramento | `reuso` |
|---|---|
| O que as regras acima fixam | **88,29%** |
| Sem o que entra por `import` dentro de função (regra 7) | 86,72% |
| Sem migrações em nenhuma ponta | 85,78% |
| Com o *backend* TypeScript das tools nas duas pontas (regra 9) | 83,77% |
| Só as migrações da vertical no numerador (a versão **defeituosa**) | 82,34% |

Os quatro primeiros saem das parcelas de `ci/reuso.json`; o do TypeScript sai da
contagem da regra 9.

As parcelas, entrada por entrada, estão no `ci/reuso.json` que o comando
escreve, junto com a provenância (o *commit* e se a árvore estava suja) e a
lista dos 16 módulos da regra 7. O número **não** está preso por teste: o que
está preso é a propriedade (`reuso ≥ limiar`) e a **lista** das excepções do
núcleo, em `tools/reuse_metric/tests/test_repositorio.py` — hoje **vazia**, e
vazia não é o mesmo que ausente: um conjunto vazio mantém o ensaio a dizer
«nenhuma», e uma excepção nova fica vermelha **nomeada**. Um teste que pinasse
88,29 parte-se em cada *commit* que toque uma linha do núcleo.

## 7. Como se corre

```bash
make reuso                                          # os dois, com artefactos
cd tools && python -m reuse_metric --root .. medir   # só a métrica
cd tools && python -m reuse_metric --root .. nucleo  # só a condição (d)
```

Códigos de saída: `0` passa, `1` achado, `2` declaração ou árvore malformadas.

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Primeira versao (**KAM-039**). As regras de contagem da medida do ADR-012, a classificacao da condicao (d) em **quatro** classes, e o resultado medido. **Dez regras, e cinco nascem de correccoes feitas durante o ticket — tres de auto-validacao e duas da revisao adversarial —, cada uma com o numero que a motivou:** a unidade passou de linha bruta a linha com codigo (o `nos.py` de Servicos tem 1435 e **649**); o caminho partilhado passou de lista a mao a fecho de importacao (**88,99% -> 87,58%**, porque a lista a mao era generosa); as migracoes passaram de so-numerador a cadeia do Alembic nas duas pontas (a versao assimetrica dava **82,34%**); a ToolLayer partilhada passou a estar declarada, simetrica ao catalogo da vertical que ja estava no numerador (**87,58% -> 88,26%** — a assimetria que o proprio ticket condenava nas migracoes, deixada no termo vizinho); e o majorante da regra 7 passou de afirmado a **nomeado** no artefacto (1677 linhas em 16 modulos). As regras **9** e **10** sao limites declarados e nao correccoes: o *backend* TypeScript das tools da vertical (1059 linhas) fica fora da medida, e a cadeia das migracoes e posicional. | Equipa KAMBA |
| 1.1 | Novembro 2026 | **A condicao (d) passa, e o §6 deixa de descrever uma arvore que nao existe (KAM-039, caixa devolvida).** O `AO_DONO` do `eventos/handlers.py` saiu do nucleo para `subscriptions[].notifica` do `registry/<id>.yaml`, por decisao do fundador a 2026-11-06, e com ele a unica ocorrencia de `fluxo`. Medido sobre `db0582d`: `fluxo 1 -> 0`, saida `1 -> 0`; `conteudo 48 -> 45` (as tres entradas da tabela saiem com ela), `prosa 114 -> 118`, `reuso 88,26% -> 88,29%`. O §4 ganha uma licao medida em codigo novo: uma guarda escrita contra a tabela (`par not in TEXTOS`) **e** `fluxo`, e a primeira versao das guardas de arranque deu `fluxo 3` — le-se o conjunto de chaves por um nome derivado. O que **nao** muda: as dez regras de contagem, o limiar, e a fronteira do `conteudo`, que continua devolvida ao fundador. | Equipa KAMBA |

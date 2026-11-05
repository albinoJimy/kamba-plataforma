# Medida de reaproveitamento por vertical — regras de contagem

| Campo | Valor |
|---|---|
| Documento | `docs/reuse-metric.md` |
| Versão | 1.0 |
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

### As oito regras

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
entra: o critério (d) exclui-o por extenso, e oito linhas de YAML não são
linhas de código no mesmo sentido. Fica dito porque **uma ausência silenciosa
lê-se como zero**, e um `glob` que não encontra nada sem o dizer é a forma mais
limpa de uma métrica mentir.

## 4. A condição (d), e porque é que um `grep` não serve

O §5.4 escreve a condição (d) como «nenhuma excepção no core (`grep` de nomes de
vertical em `core/` = 0)», e o bloco do KAM-039 acrescenta a exclusão de
`registry/` e dos testes.

**`core/` não existe como directório neste repositório.** A declaração nomeia o
que o substitui: `libs/py-core/src/kamba_core/` (o `core` literal: a biblioteca
partilhada) e `services/agr/src/kamba_agr/` **menos** `verticais/` e menos os
dois catálogos de tools por vertical.

Corrido à letra sobre esse núcleo, o `grep -iE 'vendedor|servicos|assistente'`
devolve **162** ocorrências em 30 dos 110 ficheiros. Um portão sobre esse número
seria um defeito, por duas razões independentes:

1. **114 das 162 são prosa** — comentários e *docstrings* a explicar **porque**
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
| `fluxo` | o nome **decide um ramo**: comparação, `match`, teste de `if`/`while`/`assert`, `startswith` — **é a excepção** |

**A condição (d) é `fluxo == 0`.** O `conteudo` conta-se e nomeia-se, e **não**
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

Medido em `183e2b0`, a 2026-11-05, com `make reuso`:

| Medida | Valor |
|---|---|
| `reuso` da vertical Serviços | **87,58%** (limiar ≥ 70%) |
| `LoC_específico` | 1705 linhas com código |
| `LoC_partilhado` | 12 019 linhas com código |
| `LoC_total` | 13 724 linhas com código |
| Condição (d) — `fluxo` | **0** |
| `conteudo` | 48 ocorrências, em 110 ficheiros de núcleo |
| `prosa` | 114 ocorrências |
| Reprodutibilidade | duas execuções, `sha1` igual byte a byte |

As parcelas, entrada por entrada, estão no `ci/reuso.json` que o comando
escreve. O número **não** está preso por teste: o que está preso é a
propriedade (`fluxo == 0`, `reuso ≥ limiar`), em
`tools/reuse_metric/tests/test_repositorio.py`. Um teste que pinasse 87,58
parte-se em cada *commit* que toque uma linha do núcleo, e um teste que falha
por razões que não tem nada a ver com o que afirma é um teste que alguém vai
desligar.

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
| 1.0 | Novembro 2026 | Primeira versão (**KAM-039**). As regras de contagem da medida do ADR-012, a classificação da condição (d) em três classes, e o resultado medido em `183e2b0`. As oito regras nascem de três correcções feitas durante o ticket, e as três estão escritas com o número que as motivou: a unidade passou de linha bruta a linha com código (o `nos.py` de Serviços tem 1435 e 649); o caminho partilhado passou de lista à mão a fecho de importação (88,99% → 87,58%); e as migrações passaram de só-numerador a cadeia do Alembic nas duas pontas. | Equipa KAMBÁ |

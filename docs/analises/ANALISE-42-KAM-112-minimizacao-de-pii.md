# ANÁLISE 42 — KAM-112, minimização de PII antes do LLM

| Campo | Valor |
|---|---|
| Ticket | KAM-112 — Minimização de PII antes do LLM (EPIC-07) |
| PR | [albinoJimy/kamba-plataforma#91](https://github.com/albinoJimy/kamba-plataforma/pull/91) |
| Estação | revisão adversarial, com verificação do achado |
| Instrumento | subagente `general-purpose`, com o diff e os requisitos e **sem** o raciocínio do executor |
| Achados levantados | 14 |
| `CONFIRMADO` | 12 |
| `PLAUSÍVEL` | 2 |
| `MORTO` | 7 (levantados pelo revisor e por ele próprio mortos, com a evidência) |
| Estado | Vivo — os `CONFIRMADO` corrigidos no mesmo PR |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

---

## 1. A medição que importa mais

**A bateria estava verde com oito furos de critério abertos.** 1357 testes, exit
0, e os critérios 1, 2, 3, 4 e 5 todos com buracos reproduzíveis numa linha.

Não é um acidente desta execução: é a classe de defeito que esta casa já pagou
quatro vezes — o varrimento de privacidade do KAM-026 a procurar texto em
`msgpack`, o *gate* 7 do KAM-027 a ler zero das oito subscrições, o X-02 do
KAM-028 a medir onze **recusas** e não onze tools, e os limites do validador do
KAM-032. A assinatura é sempre a mesma: **o corpus foi construído em volta do
detector**, e por isso mede que o detector contém as suas próprias premissas.

Os dois casos mais claros deste ticket:

- os **oito** locais de e-mail do corpus tinham **zero** dígitos, e `joao123@…`
  era precisamente a única forma que falhava;
- as **trinta** famílias `preco_que_parece_telefone` levavam **todas** `Kz`, e
  um total sem marcador de moeda era precisamente o que se mascarava.

Nenhum dos dois foi escolhido com má-fé. Os dois saíram de escrever o corpus
**depois** de pensar o detector, com a cabeça no que ele faz em vez de no que a
língua faz.

> **A lição, na forma que serve a próxima execução:** quando um corpus é escrito
> por quem escreveu o detector, ele mede concordância e não cobertura. O
> instrumento que o apanha não é reler o corpus — é **pedir a alguém que não viu
> o detector para escrever entradas** e medir com elas.

---

## 2. Os achados, com o veredicto e a correcção

### CONFIRMADO — critério 1 (a barreira de tipo)

**Achado 3 — o selo forjava-se de quatro maneiras.** A causa é uma só: **o selo
provava quem construiu, não o que ficou construído.** Um `object()` igual para
qualquer texto copia-se de um objecto legítimo para um forjado.

| Forja | Porque passava |
|---|---|
| `dataclasses.replace(m, texto=cru)` | reinvoca o `__init__` com o selo **real** do objecto de partida |
| `object.__setattr__(m, "texto", cru)` | o `frozen=True` protege o `__setattr__` da classe, não o do `object` |
| `MinimisedText(cru, m.selo)` | o selo era **campo público**: `repr=False` esconde-o do `repr`, não do acesso |
| `MensagemMinimizada("user", pato)` | a classe não validava nada; quem validava era a função, que se contorna construindo a classe |

**Correcção:** a `impressao` passou a ser um HMAC do próprio texto com uma chave
de processo. As três primeiras falham porque a impressão não corresponde ao texto
novo; a do `__setattr__` falha no `verificada()`, que o `para_esquema` chama no
último ponto antes do corpo HTTP. A quarta fecha no `__post_init__` da classe, e
o `chamar` passou a validar o `conteudo` e não só o invólucro.

**Achado 4 — a política AST estava invertida.** Recusava
`[mensagem("user", minimo)]` — a forma correcta, que a sua própria mensagem
recomenda por escrito — e aceitava as quatro forjas desde que se atribuísse a
uma variável. **Não mordia hoje** só porque o varrimento lê
`services/agr/src/kamba_agr`, onde não há chamador: estava à espera do dia em que
o grafo chamasse o gateway de forma idiomática para avermelhar o *gate* 4 sobre
código conforme.

**Correcção:** olha para o **valor** e não para a forma do nó (resolve variáveis
ligadas a literais, e pergunta pelas chaves do dicionário em vez de pelo tipo da
lista), e tem **seis evasões** medidas e **três formas conformes** como canários
nos dois sentidos.

> Um portão que avermelha o caminho certo é um portão que alguém desliga. Uma
> política sem controlo positivo é satisfeita por uma que recuse tudo.

### CONFIRMADO — critérios 2 e 3 (o que escapa)

**Achados 1 e 6 — o `sku` reclamava PII.** O `SKU` exige letras **e** dígitos num
lance, e três coisas são exactamente isso: a parte local de `joao123@…`, o
`tel912345678` e o `whatsapp912345678`. Um intervalo reclamado como número de
negócio **nunca é mascarado**, pelo que o e-mail e o telefone saíam em claro.

São o quarto e o quinto membros da família que o `_na_fronteira` existe para
fechar — e a regra de fronteira fecha o lado do **ponto** (o separador do BSUID),
não o do **arroba** nem o de uma letra qualquer.

**Correcção, em duas partes.** A primeira é estrutural: o e-mail e o BSUID **têm
marcador próprio** (`@`, `XX.`) e por isso decidem-se **antes** do `reclamar`,
cujos intervalos passam a respeitar os deles. A segunda é uma guarda: um `sku` ou
uma quantidade deixam de aceitar letra colada a nove ou mais dígitos — nove é o
comprimento de um móvel angolano, e um `SKU-912345678` continua reclamado porque
ali há um hífen.

**O telefone não muda de ordem, e isso é a decisão desta correcção.** Nove dígitos
é também a forma de um total; dar-lhe prioridade sobre os números de negócio
quebrava o critério 4, que é o mais duro do bloco. O e-mail e o BSUID podem vir
primeiro **porque têm marcador**.

### CONFIRMADO — critério 4 (o que se mascara e não devia)

**Achado 5 — um total de nove dígitos sem marcador era mascarado.** «O total da
encomenda e 912500000.» saía `TELEFONE_1`, com o dano a jusante que o próprio
módulo descreve: o modelo não pode citar o número e o validador de citação
recusa a resposta.

**Correcção:** o `CONTEXTO_DE_NEGOCIO` — uma palavra de negócio colada ao número
reclama-o. **E a correcção abriu dois furos no critério 3, os dois medidos:**

| Furo que a correcção abriu | Como se fechou |
|---|---|
| «factura com o NIF 5417238690» → o `factura` reclamava o NIF (recall 100% → 93%) | um **marcador de PII vence** um marcador de negócio |
| «Liga ao 912345678, o total e 12.500 Kz.» → o `total` protegia o **telefone** | o lado de **depois** é ancorado e não uma janela |

> Esta é a observação mais útil da análise inteira, e é sobre o método: **a tensão
> entre o critério 3 e o critério 4 é real e não se resolve de um lado só.** Cada
> passo que melhora um tem de ser medido contra o outro no mesmo instante, e é
> por isso que este ticket tem dois corpus e não um. Um executor que medisse só
> o recall teria aceitado as duas regressões sem as ver.

### CONFIRMADO — critério 5 (o catálogo)

**Achado 8 — um nome de catálogo composto não protegia nada.** A barreira
comparava a palavra candidata com os nomes **inteiros e dobrados**
(`"maria gourgel"`), pelo que um nome com mais do que uma palavra não protegia
nem o composto nem os componentes.

**E é precisamente o caso que importa:** um `servicos.resources.nome` é
tipicamente nome e apelido, que é a forma que a regra do **par** mascara sem
precisar de gatilho. Isto é, o profissional do catálogo era o caso mais provável
de virar `PESSOA_1` — o dano exacto que o critério 5 existe para impedir, pela
porta que a sua própria implementação abriu.

A bateria do catálogo só exercitava nomes de **uma** palavra.

**Correcção:** a comparação passa a ser por **palavra** do catálogo, com as
ligações (`de`, `da`, `dos`) e as palavras curtas descartadas.

### CONFIRMADO — a medição (o achado mais incómodo)

**Achado 9 — o recall de morada, pessoa e NIF era uma tautologia.** O corpus não
tinha **um único** topónimo fora de `LOCAIS` nem um nome fora de
`NOMES_PROPRIOS`: o limiar de 90% media que o dicionário contém as suas próprias
entradas. A via de contexto — a única que apanha o que a lista não tem, e **a
razão declarada de o limiar ser 90 e não 99** — nunca era exercitada no
denominador.

**Correcção:** entram oito topónimos e seis nomes de fora. E para os apanhar foi
preciso construir a via simétrica da que os locais já tinham: um gatilho
**forte** de pessoa basta por si. Sem ela, acrescentar casos honestos ao corpus
só fazia o limiar falhar — isto é, media-se melhor e detectava-se igual.

> O que isto diz sobre a ordem de trabalho: **o corpus honesto obrigou a melhorar
> o detector.** Se o corpus tivesse sido escrito primeiro, por quem não ia
> escrever o detector, a via de contexto de pessoa teria nascido com ele.

### CONFIRMADO — duas afirmações falsas no código

**Achado 11 — o `TECTO_MS` não é um *timeout*.** A nota afirmava que «um detector
que demore mais do que isso **falha** em vez de atrasar o turno» e que «o que ele
apanha é a expressão regular que entrou em retrocesso catastrófico». As duas são
falsas: a duração mede-se **depois** de o detector ter corrido. Medido pelo
revisor com um detector a dormir 400 ms — levantou **depois** dos 400 ms.

**Correcção:** a afirmação, não o código. O que o tecto garante, e é o que o
critério 7 pede pela letra, é que uma minimização lenta **não chega ao LLM**; o
que não garante é que o turno não demore. Interromper a sério obrigava a um
`signal.alarm` (que não vale em *threads*) ou a outro processo, e fica como
**lacuna declarada** com um `shortcut:` e um gatilho de revisão.

**Achado 12 — a falha fechada cobria só a chamada ao detector.** A atribuição de
tokens, a substituição e as duas chamadas às métricas corriam fora do `try`, e a
*docstring* dizia «qualquer erro do detector levanta `FalhaDeMinimizacao`». Hoje
cobre o corpo inteiro.

### CONFIRMADO — âmbito, e devolvido

**Achado 7 — o pipeline não tem chamador.** Nenhum turno minimiza nada hoje: o
`cliente_de_llm` é construído e nunca injectado no grafo, e o `__main__.py`
di-lo por escrito. O pipeline está completo para todos os sítios de chamada que
existem — **zero** — e a barreira garante que os futuros têm de passar por ele.

É o que o critério 1 pede e é verdadeiro, mas é verdadeiro em parte **por
vacuidade**. Duas consequências declaradas no PR: a frase «a janela leva as
mensagens minimizadas dos turnos anteriores» descreve o desenho e não é verdade
hoje, e a caixa de isolamento mede o mapa e não um turno ponta a ponta.

**Ligar o grafo é do KAM-031 e do KAM-035**, e fazê-lo aqui era alargar escopo em
silêncio para dentro de dois tickets fechados. Se a leitura do fundador for que o
critério 1 exige um chamador real, a caixa passa a `parcial` e abre ticket — é
uma decisão sobre a letra de um critério.

### CONFIRMADO — propagação

**Achado 10 — `docs/agr.md` e o runbook de degradação ainda diziam seis motivos.**
O código, os testes, o dicionário e o `canon/` estavam feitos; faltavam os dois
documentos de operação. Pior do que a contagem: o **runbook** não tinha entrada
para o motivo novo, pelo que um operador que visse `motivo=minimizacao` no painel
não tinha o que fazer. Corrigido, com os cinco passos de diagnóstico.

### PLAUSÍVEL

**Achado 13 — o `__repr__` protege o objecto, não a forma que persiste.** O
`Mapa.__repr__` esconde valores; o que fica em `ConversaState["pii_map"]` é o
`dict` cru. Não se encontrou caminho que serialize o estado inteiro (ver MORTO 3),
pelo que hoje não há vazamento — **mas a barreira está no objecto que não
persiste.** Fecha-se com uma subclasse de `dict` com `__repr__` próprio, ou com
um varrimento dos `extra=` de *logger*. Fica declarado.

**Achado 14 — IBAN, conta bancária e telefone com barras escapam.** Nenhum está
nos seis tipos que o critério 2 enumera, logo não é violação da letra — e é PII
directa que atravessa, e um cliente angolano manda o IBAN para pagar por
transferência com frequência. **Declarados como limites**, com credor proposto
(KAM-033 ou ticket próprio) e a decisão devolvida a quem escreve o âmbito.

### MORTOS, com a evidência

| # | Hipótese | O que a matou |
|---|---|---|
| 1 | moeda colada antes do número («Kz912500000») deixava o total sair como telefone | o `SKU` reclamava o lance inteiro. **Mas deixou de o fazer** quando a guarda dos nove dígitos entrou, e por isso o `PRECO` ganhou a forma de moeda colada: um MORTO que ressuscitou pela correcção de outro achado, e a razão por que um `CONFIRMADO` se verifica outra vez contra a árvore que vai fundir |
| 2 | outro egresso para um modelo além do `ClienteDeLlm` | `grep` de `httpx\|requests\|urlopen` em `services/agr/src` dá só `llm/cliente.py`; `egress.yaml` tem `destinos: []`; há teste de que `chat/completions` aparece num ficheiro só |
| 3 | o mapa a sair por log, `extra`, evento, *trace* ou `llm_call_log` | nenhum caminho; os dois `dict(estado)` do grafo vão ao `ToolContext.de_estado`, que copia só as chaves declaradas e levanta nas que faltam |
| 4 | os três buracos conhecidos da família BSUID | fechados e com teste nomeado |
| 5 | `_SELO` referido fora do módulo na fonte | não escapava por referência de módulo — escapava pelo **atributo da instância**, que é o achado 3 |
| 6 | contagens antigas em código, testes e canon | actualizadas e com teste; o que faltava era o achado 10 |
| 7 | `docs/minimizacao.md` em falta | entrou a meio da revisão |

---

## 3. O que a fábrica aprendeu, e o que disto devia virar portão

A regra do §3 da skill é que **um escape que um portão podia ter apanhado vira
portão**, e que a forma desta casa é **entrar num gate que já existe** em vez de
abrir *job* novo.

Dois candidatos, e nenhum se implementa aqui — abrir um portão novo é alteração
de regra de bloqueio e é do fundador:

1. **O corpus escrito pelo autor do detector.** Foi a causa de dois dos oito
   furos, e é mecanizável em parte: um varrimento que exija que um corpus de
   recall tenha **pelo menos N casos cujos valores não estejam em nenhuma lista
   do módulo que ele testa**. Não apanha tudo, apanha a tautologia — que foi
   exactamente o achado 9. Credor natural: **KAM-040**, que constrói o *gate* 13
   e os *goldens*.
2. **A política sem controlo positivo.** O `politica_llm_ast.py` nasceu com
   canários negativos e sem `CONFORMES`, e por isso recusava o caminho certo sem
   ninguém notar. É a mesma lacuna que o `log_policy` não tem (ele corre o
   canário **e** as positivas). Vale como convenção escrita: **uma política AST
   nova leva fixtures nos dois sentidos**, e isso cabe no `lint_arch`, que já lê
   a forma dos ficheiros de teste.

E uma observação que não vira portão porque é sobre julgamento:

> **A tensão entre dois critérios do mesmo ticket mede-se nos dois lados a cada
> passo, não no fim.** As duas regressões que o `CONTEXTO_DE_NEGOCIO` abriu no
> critério 3 só apareceram porque o corpus de PII correu outra vez logo depois.
> Um executor que tivesse medido o critério 4, dado por fechado e passado ao
> seguinte teria entregado um recall de NIF de 93% a dizer 100%.

---

## 4. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial. Catorze achados da revisão adversarial do KAM-112: doze `CONFIRMADO` (oito deles furos nos critérios 1, 2, 3, 4 e 5), dois `PLAUSÍVEL` e sete `MORTO` com a evidência. Os `CONFIRMADO` corrigidos no mesmo PR, excepto o achado 7 (âmbito, devolvido) e os dois `PLAUSÍVEL` (declarados). **Proposta.** | Equipa KAMBÁ |

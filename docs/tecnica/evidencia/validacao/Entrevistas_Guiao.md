# Entrevistas a PMEs: guião, ficha de registo e medição de H1 e H2

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — guião das 30 entrevistas, ficha de registo e medição de H2 e do sinal de H1 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-106 (EPIC-10) |
| Estado | NÃO VERIFICADO — nenhuma entrevista foi feita, e o guião ainda não passou pela revisão cruzada nem pelas 2 entrevistas-piloto |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H1, H2), §3 (pontos 1 e 2), §6; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-106) |
| Dono | Responsável de Produto (o `../../10_Onboarding_Governanca.md` §12 manda o guião aprovado por Produto) |
| Documento-fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md`; `../../10_Onboarding_Governanca.md` §12; `../E1_Meta_WhatsApp.md` (risco 9); `../E3_Regulatorio_Dados.md` §1, §5 |
| Relacionados | [`Entrevistas_Consentimento.md`](Entrevistas_Consentimento.md), [`Canais_Acesso_PME.md`](Canais_Acesso_PME.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md), [`Entrevistas_Ficha.csv`](Entrevistas_Ficha.csv) |

> **Este documento é o material, não o resultado.** As entrevistas são
> humanas, e nenhuma foi feita: não há aqui uma única resposta, nome de PME ou
> contacto. O que fica pronto é o que tem de estar fixado **antes** da primeira
> entrevista — o guião, a ficha com os campos fixos, os limiares e o *script*
> que os aplica —, para que a medição seja uma leitura e não uma discussão.
>
> **Os limiares de H2 e a definição de «repetível» são propostas** (`14` §2 e o
> bloco do KAM-106), fixadas antes de medir; só mudam por emenda registada.

---

## 1. Antes de começar: o que o guião não pode fazer

1. **Sem *pitch*.** A entrevista mede o que a PME faz hoje, não o que acha de
   uma ideia. O entrevistador não apresenta a KAMBÁ, não diz o que o produto
   faz e não responde a «e vocês fazem isso?» antes do fim — a resposta fixa é
   «no fim falamos disso, agora interessa-me como fazem hoje».
2. **Sem perguntas orientadoras.** Pergunta-se pelo **último caso concreto**
   («da última vez que…»), não pela opinião («acha que…?», «não seria
   melhor…?»). Nunca se sugere a resposta, nem com exemplos.
3. **Regras de comunicação do segmento A** (`../../10_Onboarding_Governanca.md`
   §12): nunca dizer que a plataforma «não deixa rasto», «escapa à AGT» ou «não
   regista vendas»; não usar o INAPEM como argumento.
4. **Consentimento primeiro.** Sem consentimento (por escrito ou gravado), não
   se tomam notas — lê-se o texto de
   [`Entrevistas_Consentimento.md`](Entrevistas_Consentimento.md) e, se a
   resposta for não, agradece-se e termina. Não se pedem dados de clientes da
   PME, nem se aceitam.
5. **O nome da PME e o contacto não entram na ficha.** A ficha leva um
   `id_anonimo` (por exemplo `P-07`); a correspondência entre o id e a PME vive
   só no arquivo controlado.

## 2. O guião (cerca de 25 minutos)

Cada bloco diz que coluna da ficha alimenta. O que vai entre aspas lê-se como
está; o resto é orientação para o entrevistador.

### A. Perfil (2 min) — `categoria`, `formal`, `n_empregados`

- «O que vendem, principalmente?» → `categoria`, em palavras genéricas (por
  exemplo «roupa», «restauração»), nunca o nome da loja.
- «A empresa tem NIF?» → `formal`: `S` se tem NIF, `N` se não tem. Uma
  empresa em formalização que já tenha NIF é `S`; sem NIF é `N`, e o resto
  anota-se no arquivo. O Piloto aceita só o segmento A, com NIF obrigatório
  (`../../10_Onboarding_Governanca.md` §9 e §12), e é por isso que o *script*
  lê esta coluna (§5, item 7).
- «Quantas pessoas trabalham na empresa, contando consigo?» → `n_empregados`.

### B. Atendimento (5 min) — `dor`

- «Conte-me a última vez que um cliente lhe escreveu a perguntar por um
  produto. O que aconteceu, desde a mensagem até ao fim?»
- «E quando chegam várias mensagens ao mesmo tempo, como fazem?»
- O entrevistador **classifica depois** a dor, de 1 a 5, pela âncora abaixo
  (*proposta*); não pede à PME que se classifique:

| `dor` | Âncora |
|---|---|
| 1 | Não refere perda nem esforço com o atendimento |
| 2 | Refere esforço, sem perda de venda |
| 3 | Refere atrasos com perda ocasional de venda |
| 4 | Refere perda de vendas recorrente, ou alguém dedicado só a responder |
| 5 | Refere perda recorrente **e** já tentou resolver (pessoa, ferramenta, horário) |

### C. Como vendem e cobram hoje (5 min)

- «Na última venda que fez por mensagem, como é que o cliente pagou?»
- «Como soube que o dinheiro tinha entrado?»
- As respostas ficam nas notas do arquivo; a ficha não tem coluna para elas,
  porque o critério não lhes fixa escala.

### D. Comprovativos (2 min) — `comprovativos_semana`

- «Numa semana normal, quantos comprovativos de pagamento recebe por
  mensagem?» → número inteiro; se der intervalo, regista-se o valor de baixo.
- «Como confirma que um comprovativo corresponde a dinheiro entrado?» → nas
  notas.

### E. Preços dos 20 produtos principais (6 min) — `produto_01` … `produto_20`

- «Pode dizer-me os 20 produtos ou serviços que mais vende?» Os nomes **não**
  se registam na ficha — só a classificação de cada um.
- Para cada um: «Se um cliente lhe perguntar o preço deste por mensagem, o que
  responde?» O entrevistador classifica:

| Classe | Quando |
|---|---|
| `fixo` | Responde com um preço, sem condições |
| `a partir de` | Responde com um preço mínimo, ou um preço com variações conhecidas (tamanho, quantidade) |
| `sob consulta` | Não dá preço sem conversa, negociação, ou ver o cliente |

- Uma PME que não chegue a 20 produtos fica **incompleta** (o *script* não a
  conta). É a leitura literal de «dos 20 produtos»; está no §5, item 2.

### F. Quanto pagaria (3 min) — `faixa_preco`

Para perguntar o preço é preciso dizer o quê, e é aqui que mais facilmente se
entra em *pitch*. Por isso a descrição é **fixa** e lê-se tal como está, sem
adjectivos nem promessas:

> «Imagine um serviço que responde às mensagens dos seus clientes no WhatsApp,
> mostra os produtos com o preço que o senhor definir e regista os pedidos.
> Quanto pagaria por mês por isso?»

O entrevistador mostra as quatro faixas e regista a escolhida:

| `faixa_preco` | Faixa (Kz por mês) |
|---|---|
| `<15` | menos de 15 mil |
| `15-30` | de 15 mil a 30 mil |
| `30-60` | mais de 30 mil até 60 mil |
| `>60` | mais de 60 mil |

As faixas da letra («< 15 mil, 15–30 mil, 30–60 mil, > 60 mil») partilham os
extremos; a tabela atribui os 30 mil à segunda e os 60 mil à terceira, e isso é
leitura nossa (§5, item 3). O preço de referência de 30–60 mil Kz é **hipótese**
(bloco do KAM-106, «Contexto»), e não se diz ao entrevistado.

### G. Cartão internacional (1 min) — `cartao_internacional`

- «A empresa tem algum cartão que pague em moeda estrangeira?» → `S`/`N`. Alimenta D5 e o KAM-102: a
  Meta factura Angola em moeda estrangeira (E1 §1).

### H. Categoria vedada — `categoria_vedada` (não se pergunta)

O entrevistador marca `S` se a categoria principal da PME estiver numa destas
listas, e `N` no resto. Entrevistar estas PMEs é legítimo para medir a perda,
mas **não** as inscreve no piloto (bloco do KAM-106, «Detalhes Técnicos»).

| Origem | Categorias | Estado |
|---|---|---|
| Meta, política de comércio (`../E1_Meta_WhatsApp.md`, a linha das categorias proibidas, e o risco 9) | álcool, tabaco, saúde e farmácia, crédito e empréstimos, apostas, multinível; e o resto da lista não exaustiva de E1 (armas, drogas, animais vivos excepto gado, produtos para adultos, entre outras) | CONFIRMADO (fonte primária), como E1 o declara na linha das categorias; a dimensão da perda é que está por medir |
| Lei angolana (`../E3_Regulatorio_Dados.md` §5) | medicamentos fora de farmácia licenciada; jogos de fortuna ou azar sem licença | INDÍCIO e CONFIRMADO conforme a linha de E3; **a confirmar por parecer** |

Em dúvida, marca-se `S` e anota-se a dúvida no arquivo: um falso `S` custa uma
candidata ao piloto, um falso `N` põe uma categoria vedada no piloto.

### I. Disponibilidade (1 min) — `disponivel_piloto`

Só no fim, depois de tudo o resto registado, e só a quem tem `formal` = `S`.
A quem não tem NIF não se faz o convite (`../../10_Onboarding_Governanca.md`
§12: ao segmento B não há *pitch* no Piloto); se perguntar, informa-se que o
produto implica NIF e registo, e regista-se `N`.

> «Vamos fazer um teste gratuito de 30 dias com algumas empresas. Gostaria de
> participar?»

→ `S`/`N`. Um `S` só serve para o convite se a pessoa tiver autorizado o uso
do contacto para isso no consentimento
([`Entrevistas_Consentimento.md`](Entrevistas_Consentimento.md) §1). Agora, e só agora, o entrevistador pode responder a perguntas sobre
a KAMBÁ — e nada do que se disser a seguir muda as respostas já registadas.

## 3. A ficha de registo

### 3.1 O CSV

O modelo vazio é [`Entrevistas_Ficha.csv`](Entrevistas_Ficha.csv): só o
cabeçalho, separado por `;` (abre directamente numa folha de cálculo em
português). O *script* aceita também `,`. **A ficha preenchida não entra no
repositório**: vive no arquivo controlado, e passa-se ao *script* pelo caminho.

| Coluna | Valores | Notas |
|---|---|---|
| `id_anonimo` | texto, único | Nunca o nome da PME; os ids `SINT-` estão reservados à ficha sintética de ensaio |
| `data_entrevista` | `AAAA-MM-DD` | Acrescentada aos campos da letra para medir «até ao fim da semana 4» |
| `categoria` | texto genérico | Sem nome de marca nem de loja |
| `formal` | `S`, `N` | `S` = tem NIF (§2 A) |
| `n_empregados` | inteiro ≥ 0 | |
| `canal_origem` | `C1` … `C5` | Os canais de [`Canais_Acesso_PME.md`](Canais_Acesso_PME.md) |
| `dor` | 1 a 5 | Pela âncora do §2 B |
| `comprovativos_semana` | inteiro ≥ 0 | |
| `faixa_preco` | `<15`, `15-30`, `30-60`, `>60` | Mil Kz por mês |
| `cartao_internacional` | `S`, `N` | |
| `categoria_vedada` | `S`, `N` | Pela tabela do §2 H |
| `disponivel_piloto` | `S`, `N` | |
| `consentimento` | `escrito`, `gravado`, `nao` | Uma linha com `nao` fica vazia no resto: o *script* conta-a à parte, e recusa a ficha se ela tiver respostas |
| `produto_01` … `produto_20` | `fixo`, `a partir de`, `sob consulta` | Só a classe, nunca o nome do produto |

Duas regras do *script*, que convém saber ao preencher:

- **Célula vazia** torna a entrevista **incompleta**, e as incompletas não
  contam (critério 2).
- **Valor fora da lista** é erro: o *script* recusa a ficha inteira (código 2)
  e diz a linha. Um erro de digitação corrige-se; não se deixa cair calado.

### 3.2 O formulário em papel

Para a entrevista no terreno, a mesma ficha numa página. Copia-se para o CSV no
mesmo dia, e o papel arquiva-se com o consentimento.

| Campo | Resposta |
|---|---|
| id anónimo | ______ |
| data | ____-__-__ |
| categoria | ______ |
| formal | ☐ S ☐ N |
| n.º de empregados | ______ |
| canal de origem | ☐ C1 ☐ C2 ☐ C3 ☐ C4 ☐ C5 |
| dor (1–5) | ☐ 1 ☐ 2 ☐ 3 ☐ 4 ☐ 5 |
| comprovativos por semana | ______ |
| faixa de preço | ☐ <15 ☐ 15-30 ☐ 30-60 ☐ >60 |
| cartão internacional | ☐ S ☐ N |
| categoria vedada | ☐ S ☐ N |
| disponível para piloto | ☐ S ☐ N |
| consentimento | ☐ escrito ☐ gravado ☐ não |
| produtos 1–20 | 20 linhas: ☐ fixo ☐ a partir de ☐ sob consulta |

## 4. A medição

O *script* é `scripts/entrevistas_h2.py`, com ensaios em
`scripts/tests/test_entrevistas_h2.py`:

```text
python scripts/entrevistas_h2.py <ficha.csv> --inicio <1.º dia da semana 1>
python scripts/entrevistas_h2.py <ficha.csv> --rondas <rondas.csv> --lista <lista.csv> --resumo
python -m unittest discover -s scripts/tests -t scripts
```

O que devolve, com **contagens absolutas** em todas as linhas:

| Saída | Regra | Critério |
|---|---|---|
| H2 por PME | `fixo` + `a partir de` ≥ 14 de 20 | 3 |
| Estado de H2 | `confirmada` se ≥ 50% das completas passam e n ≥ 30 (com n = 30: ≥ 15); `refutada` abaixo disso; `inconclusiva` com n < 30 | 3 |
| Pivô | Se `refutada`: o de `14` §6, com KAM-043, KAM-061 e a mensagem comercial | 3 |
| Sinal de H1 | Contagem por faixa; disponíveis e elegíveis para piloto (com NIF e fora de categoria vedada); «problema de distribuição» se < 10 elegíveis após as 30 | 4 |
| Canais | Entrevistas por canal, tecto de 40% (*proposta*), e — com `--rondas` — repetível se ≥ 6 PMEs-alvo em ≥ 2 rondas (*proposta*) | 2, 5, 6 |
| Entradas | % em categoria vedada (KAM-088); n.º com cartão (KAM-102, D5); e, com `--lista`, a % vedada na lista de PMEs-alvo | 7 |
| Prazo | Com `--inicio`: completas antes do fim da semana 4 e fora dele, e o aviso «critério 2 por cumprir» se as de dentro não chegarem a 30 | 2 |

**O estado que o *script* dá não é a decisão.** A decisão sobre H2 é humana e
regista-se no [`Registo_Hipoteses.md`](Registo_Hipoteses.md) com resultado,
fonte, decisão e data. O `--resumo` sai já com a forma do
`H1H2_Entrevistas_Resumo.md` que o critério 8 pede — título, ressalva de que
n = 30 é **direccional**, contagens absolutas e nenhum id —, e esse ficheiro só
se escreve com dados reais. Uma ficha com ids `SINT-` sai marcada «FICHA
SINTÉTICA — isto é um ensaio, não é resultado» em todas as saídas.

Um zero sem amostra escreve-se «0 de 0 (não medido)», nunca «0%».

## 5. Leituras da letra e o que fica por decidir

Escritas aqui para não ficarem escondidas no código. Nenhuma muda um limiar; se
o dono do limiar discordar de uma, muda-se por emenda registada **antes** da
primeira entrevista.

1. **n diferente de 30.** Com mais de 30 completas, o *script* aplica os 50% a
   n (a forma de `14` §2); com menos, dá `inconclusiva`.
2. **PME com menos de 20 produtos** fica incompleta, pela letra («dos 20
   produtos»). A alternativa — medir a percentagem sobre os que existem —
   aceitava PMEs pequenas, mas é outro limiar.
3. **Extremos das faixas.** 30 mil vai para `15-30`, 60 mil para `30-60`.
4. **Elegíveis para piloto.** A regra dos «< 10» aplica-se a quem está
   disponível, tem NIF **e** está fora de categoria vedada, porque as vedadas e
   as do segmento B não entram no piloto; o relatório mostra também as
   disponíveis em bruto.
5. **«Última linha de `14` §6»** lê-se como a última linha da **tabela**
   (resolver a distribuição), e não o parágrafo da paragem total que vem a
   seguir.
6. **«≥ 6 PMEs-alvo em ≥ 2 rondas»** lê-se como total ≥ 6 e pelo menos duas
   rondas com entrega; uma ronda sem PMEs não conta como ronda.
7. **«Formal S/N»** lê-se como «tem NIF». A letra não define a coluna; o
   segmento A inclui as empresas «em formalização», mas o Piloto exige NIF
   (`../../10_Onboarding_Governanca.md` §9), e é o NIF que decide se uma
   disponível é elegível.
8. **Prazo da semana 4.** O estado de H2 conta todas as completas, e o prazo
   assinala-se à parte (§4). Se o dono do limiar quiser H2 só sobre as
   completas dentro do prazo, é emenda.

## 6. O que continua humano

| Passo | Quem | Estado |
|---|---|---|
| Revisão cruzada do guião (sem *pitch*, sem perguntas orientadoras), por pessoa distinta do autor | Responsável de Produto e um revisor | por fazer |
| 2 entrevistas-piloto antes da amostra, e emenda do guião se preciso | Responsável de Produto | por fazer |
| As 30 entrevistas, até ao fim da semana 4 | Responsável de Produto | 0 de 30 |
| Arquivo controlado para consentimentos, notas, contactos e a ficha preenchida | Responsável de Produto, com o de Segurança | por escolher (ver [`Entrevistas_Consentimento.md`](Entrevistas_Consentimento.md) §3) |
| Registo de H2 e do sinal de H1 no `Registo_Hipoteses.md` | Fundador decide; Produto regista | por medir |

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto (aprova o guião) | | | |
| Revisor do guião (pessoa distinta do autor) | | | |
| Fundador (dono dos limiares) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-106 (lote 24). Guião em nove blocos sem *pitch*, com a descrição do serviço fixa para a pergunta de preço; ficha CSV com os doze campos da letra mais a data e os 20 produtos; formulário em papel; tabela de categorias vedadas com o estado das fontes; a medição pelo `scripts/entrevistas_h2.py`; oito leituras da letra escritas, duas delas pedidas pela revisão adversarial (o NIF nos elegíveis e o prazo). Nenhuma entrevista feita. | Equipa KAMBÁ |

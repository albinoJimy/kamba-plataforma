# ANÁLISE 33 — revisão adversarial do KAM-032 (validador de citação)

| Campo | Valor |
|---|---|
| Ticket | KAM-032 — Validador de citação: *renderer* por referência e validador numérico com `sku` |
| Diff revisto | `69d7059` contra `7d44c51`, reverificado contra `dcd4eb7` |
| Revisor | subagente independente, com encargo apertado (ficheiros e secções nomeados, nove perguntas numeradas, proibição de escrever ficheiros e de correr `mutacoes`) |
| O que o revisor **não** recebeu | as justificações do autor. O encargo mandava tratar as notas de módulo como **afirmações** e proibia ler a secção «Verificação dos Critérios de Aceitação» |
| Instrumentos | `/code-review high` + `ponytail-review`, numa passagem, com cada achado executado |
| Veredicto | **REPROVADO** — 7 *must fix*, 11 *should fix*, 4 *nice to have* |
| Estado | **os 7 *must fix* corrigidos com teste**; 10 dos 11 *should fix* corrigidos; os 4 *nice to have* corrigidos |

---

## A classe de defeito que esta revisão encontrou, e porque era previsível

Dos sete *must fix*, **cinco eram falsos aceites de dinheiro** e **dois eram
provas que não mediam o que diziam medir**. Nenhum era código mal escrito; todos
eram a mesma coisa:

> um mecanismo existia, a bateria passava, e **o caso que o quebrava não estava no
> conjunto**.

O ticket avisava que este era o risco principal («um critério pode estar
satisfeito pela razão errada — e neste ticket é o risco principal»), e nomeava
três precedentes: o varrimento de privacidade do KAM-026 a procurar texto em
`msgpack`, o *gate* 7 do KAM-027 a ler zero das oito subscrições, o X-02 do
KAM-028 a medir onze **recusas** e não onze tools. Aconteceu outra vez, e o
conjunto adversarial de 246 casos **não o viu** — porque os casos foram gerados a
partir do mesmo modelo mental que escreveu o código.

A lição operacional está no fim deste documento.

---

## Os sete *must fix*

### 1. A prova de privacidade olhava para os dois campos que nunca a podiam quebrar

O `test_um_erro_nao_leva_texto` construía o canário certo — `"o meu numero e
923456789 e moro na Rua X"` — e depois percorria `(erro.codigo, erro.sku)`. O
campo `erro.valor` **não entrava no laço**.

Medido: o `validar` devolvia `Erro(codigo='number_unbacked', valor=923456789)` —
o canário inteiro no objecto que o grafo vai registar. E a *docstring* do `Erro`
afirmava «o que fica são números e `sku` — dados da tool, não do contacto»:
**falso por construção**, porque um `number_unbacked` é, por definição, o número
que *não* veio de tool nenhuma. É exactamente aí que um telefone, um número de
porta ou um NIF repetido pelo modelo aterra.

**Corrigido** em dois tempos, porque um só não bastava:

* o `valor` só se preenche quando o número **casa** um *fact* — o
  `money_unbacked`, o `qty_unbacked`, o `discount_unbacked` e o
  `number_unbacked` vão sem ele. O `sku_price_mismatch` mantém-no, e tem direito:
  aquele valor casou um *fact*, logo é dado da tool;
* o teste percorre **todos** os campos da *dataclass* por reflexão
  (`dataclasses.fields`), e não uma lista escrita à mão. É o que impede a
  repetição: um campo novo entra no laço sozinho.

### 2. O `validar` levantava em vez de devolver um `Verdict`

O `_MARCA_DE_MOEDA` aceita `[A-Z]{3}` (ISO 4217), e **`DEZ`, `MIL` e `UMA`
casam**. Medido: `validar("Temos DEZ unidades")`, `validar("Custa 2 MIL Kz")` e
`validar("Levo UMA caixa")` levantavam `MoedaEstrangeiraError` para fora da
função.

Importa por três razões, e a terceira fecha o círculo com o achado 1: o nó
`validate` rebentava em vez de recusar, pelo que o «retry → handoff» do §8.4
nunca corria; um `Verdict` que não existe não é «0 falsos aceites», é zero
veredictos; e a mensagem da excepção levava uma palavra do texto gerado para o
*traceback*.

**Corrigido:** uma palavra de número não é uma marca de moeda, mesmo em
maiúsculas (consulta-se `PALAVRAS_DE_NUMERO` antes da forma ISO), e há uma
bateria que afirma que o `validar` **nunca levanta** sobre cinco entradas desse
tipo.

### 3. Um valor que coincidia com um *fact* `total` dispensava o vínculo ao `sku`

Era um atalho deliberado, com comentário `shortcut:` e remetido para as
limitações do §9.2 como «coincidência de valores». **O revisor recusou o
enquadramento, e tinha razão.**

A linha do §9.2 é «preço de A igual ao **stock** de B», e a mitigação que ela
nomeia é «validação por `kind` e por vínculo» — era precisamente o `kind` e o
vínculo que o atalho saltava. E não é coincidência: **num carrinho de um item o
`total` *é* o preço desse item**, pelo que a carga mais comum da loja cruzava o
limite sempre, não por acidente.

Medido: *facts* `price SKU-100=12 500`, `price SKU-200=9 000`, `total=9 000`;
texto `"SKU-100 - Camisa Azul - 9 000 Kz"` → **aceite**. É o «produto errado com
preço certo» do ADR-007 a passar pela porta que este ticket existe para fechar.

O caso que estava nos `LIMITES` escondia-o: construía a coincidência à mão com um
total longe de todos os preços.

**Corrigido:** um `total` dispensa o vínculo **só numa linha que não fala de
produto nenhum** — sem `sku` e sem nome. Uma linha que identifica um produto
passa sempre pelo vínculo. O caso dos `LIMITES` foi reescrito para o que resta do
limite (um valor numa linha sem produto, que não pode trocar um por outro), e o
caso que era falso aceite entrou no conjunto a **recusar**.

### 4. O mesmo atalho desarmava o critério 4 inteiro

O ramo do `a_partir_de` estava **depois** do `continue` do atalho. Medido: com
`price SKU-500=5 000` (oferta `a_partir_de`) e `total=5 000`, o texto
`"SKU-500 - Fato Completo - 5 000 Kz"` era **aceite** — um preço publicado como
mínimo apresentado como final.

E o marcador era frouxo por conta própria: o `tem_a_partir_de` procurava a frase
em **qualquer** sítio da linha, pelo que `"… 5 000 Kz, entregamos a partir de
amanha"` passava sem total nenhum.

**Corrigido:** o atalho deixou de existir (achado 3) e o marcador passa a ter de
estar **imediatamente antes** do valor.

### 5. O `_marca` reservava o intervalo e depois desistia — e o número desaparecia

A ordem estava invertida: o intervalo era reservado **antes** de se saber se o
achado se conseguia ler. Quando o ramo desistia, o intervalo ficava ocupado e o
varrimento final também o saltava.

Três entradas medidas, todas aceites:

| Entrada | *Facts* | O que o cliente lia |
|---|---|---|
| `SKU-9 - Camisa 12 500 Kz` | `price=500 Kz` | **12 500 Kz** num produto de 500 Kz |
| `SKU-700 - Tinta 250 unidades` | `stock=2` | 250 unidades inventadas |
| `O carro custa 2 milhões de Kz` | nenhum | um preço sem *fact* nenhum |

A terceira é a mais instrutiva: o `_DINHEIRO` casa `milh[õo]es` de propósito, mas
o multiplicador do `para_centimos` era `[a-zA-Z]+`, que **não casa acentos**.
Levantava, o `continue` disparava, e o número ia-se. A versão sem acento
extraía-se bem — a falha era invisível no caminho que os testes percorriam.

**Corrigido** em três sítios: marca-se **só depois** de o achado existir
(`_guardar`); o multiplicador aceita acentos; e o `_PRECO_NO_NOME` passa a
recusar um nome que **acaba** em dígitos, porque é isso que o cola ao número
seguinte (dígitos no meio, como «Vestido 2 peças», não têm esse problema).

### 6. As formas de data/hora eram uma união achatada sobre todos os *facts*

Medido: *facts* `2026-11-14T13:30Z` e `2026-11-15T15:00Z`; texto `"A entrega e a
14/11/2026 as 16h00"` → **aceite**. O cliente recebia confirmação de um instante
que nenhuma tool devolveu — a data de um *slot* com a hora de outro.

O conjunto adversarial não o podia ver: tinha exactamente **um** *fact*
`datetime`.

**Corrigido:** as datas e horas de uma linha têm de caber **todas no mesmo
*fact***. Uma marcação é um instante, e o *renderer* escreve um por linha.

### 7. Um bloco `total` sem `fact_id` escolhia o primeiro em silêncio

O `fact_id` era opcional, e `None` casava qualquer *fact* daquele `kind`. Medido:
com `total=5 000` e `total=21 500` na mesa, `{"type": "total"}` escrevia «Total:
5 000 Kz».

A *docstring* do `BlocoInvalidoError` diz que aqui se levanta «em vez de
degradar», porque uma mensagem mais curta e plausível é «a classe de defeito que
ninguém vê ao ler o resultado». Aqui degradava para o **número errado**,
produzido pela camada 1 — a divergência que o ADR-007 proíbe, vinda do mecanismo
que existe para a impedir.

**Corrigido:** o `fact_id` é obrigatório nos blocos `total` e `datetime`.

---

## Os *should fix*, e os dois custos de um validador

Dez dos onze foram corrigidos. O que eles mostram, juntos, é que **um validador
tem dois custos e só um deles é falso aceite**: um validador estrito demais gasta
uma repetição do modelo por cada resposta legítima e acaba em *handoff* —
bloqueia a loja em vez de a proteger.

| # | Achado | Estado |
|---|---|---|
| 8 | Um nome que é prefixo de outro, ou repetido em duas variantes, recusava o *output* do próprio *renderer* | corrigido: reserva-se do mais longo para o mais curto, e o nome resolve para um **conjunto** de `sku` com pergunta de pertença |
| 9 | Um `sku` que é prefixo de outro (`SKU-10`/`SKU-100`) dava o mesmo falso rejeito | corrigido pela mesma ordenação |
| 10 | Um bloco `text` que nomeasse um produto era recusado pela camada 2 | corrigido: o vínculo nome→`sku` só se exige em linhas que citam um número de produto — sem número, um nome não pode enganar sobre preço |
| 11 | A guarda de dígitos da camada 1 não via números por extenso («doze mil Kz» passava) | corrigido: pergunta-se ao extractor, que é quem sabe o que é um número |
| 12 | «Mil desculpas», «Cem por cento de certeza», «Dois minutos e volto» e um nome de marca com «Zero» davam `number_unbacked` | corrigido: uma palavra de número **isolada** só conta quando a moeda ou uma palavra de contagem a reclama |
| 13 | Formas legítimas de data/hora recusadas com o *fact* certo na mão | **não corrigido** — o extractor reconhece sete formas e o *renderer* declara cinco. É a família «formatos regionais» do §9.2 pelo lado do falso rejeito, e fica na dívida **123** |
| 14 | O `allowed_literals` perdoava «100 USD» | corrigido: uma moeda estrangeira é `money_unbacked` e não `number_unbacked`, pelo que um literal não a pode absolver. A *docstring* da `Policy` deixou de dar «horários da loja» como exemplo — um horário é um *fact* `datetime` |
| 15 | Duas das quatro taxas do §9.2 não se liam dos contadores como a nota as escrevia | corrigido em três sítios: `falhas / total` (o `handoff` é **subconjunto** das falhas), e o `render_only_ratio` sobre `agr_turns_total{executado}`, porque o denominador de uma proporção de **respostas** é o turno |
| 16 | `registar` é o nome que o `log_policy` do *gate* 2 proíbe | corrigido: passa a `medir_validacao`, com teste. É a lição que o `tls/auditoria.py` escreveu ao escolher `escrever` |
| 17 | Quatro propriedades delicadas sem mutação | corrigido: `name_sku_mismatch` (o único dos sete veredictos sem mutação), `MONEY_KINDS`, `CAMPOS_DE_ITEM` (a garantia **estrutural** do critério 5, que estava garantida por **ausência**) e os cêntimos do `kz_display` |
| 18 | O conjunto adversarial era mais fraco do que o número sugeria | corrigido: a expectativa por caso passa a **igualdade** e não subconjunto, porque um veredicto colateral desencaminha o *retry* e nunca reprovava um caso |

Os quatro *nice to have* foram corrigidos: a regra 2 do separador passou a ser
verdade (o multiplicador não era visível à regra que o nomeia), o limite de «mil
milhões» está escrito e com teste, as *docstrings* que afirmavam campos
inexistentes foram emendadas, e o `_inteiro` duplicado passou a um só.

---

## A mutação que sobreviveu depois das correcções

A mutação nova `cit: o stock passa a sustentar um preco` — pôr `stock` em
`MONEY_KINDS` — **sobreviveu** à *suite* inteira na primeira execução.

A propriedade estava certa: o revisor testou-a e um valor monetário igual a um
*fact* `stock` recusava. O que não existia era **medição**: os stocks do catálogo
são 1 a 25, e um valor em cêntimos igual a 3 seria «0,03 Kz», que ninguém
escreve. A separação por `kind` — que o §9.2 nomeia como a mitigação da
coincidência de valores — não tinha um único teste.

É a definição de um teste que passa pela razão errada, encontrada pela prova por
mutação depois de a revisão humana ter passado por ali. Fechou-se com uma bateria
que constrói o *fact* `stock` com o valor do preço.

**Resultado final:** 806 mutações aplicáveis (0 não aplicáveis), 23 `cit:`
corridas, **0 não apanhadas**.

---

## O que esta revisão ensina a quem vier depois

**1. Um conjunto adversarial gerado por quem escreveu o código herda-lhe os
pontos cegos.** Os 246 casos tinham um total longe de todos os preços, **um**
*fact* `datetime`, nenhum prefixo de `sku`, nenhum nome repetido e nenhum nome
que acabasse em dígitos. Cinco falsos aceites viviam exactamente nesses buracos.
O número de casos não é a medida; a diversidade do **catálogo** é.

**2. Um `shortcut:` bem escrito não torna o atalho defensável.** O atalho do
`total` tinha limite escrito, gatilho de revisão e remissão para o §9.2 — e
estava errado sobre a sua própria frequência: num carrinho de um item era a carga
normal, não uma coincidência. A pergunta que faltou foi «com que frequência isto
acontece na loja?», e não «está documentado?».

**3. Uma prova de privacidade escolhe o canário certo e mede o campo errado.** É
a terceira vez nesta linha (KAM-026, KAM-028, agora). A correcção que resiste não
é olhar para o campo que faltava: é **percorrer todos os campos por reflexão**,
para que o próximo campo entre no laço sozinho.

**4. O que não se extrai não se valida.** Três dos sete *must fix* eram números
que **desapareciam** do texto — por um padrão guloso, por um intervalo reservado
cedo demais, por um acento. É o falso aceite mais difícil de ver, porque nada no
resultado o denuncia: o veredicto diz `ok` e a lista de erros está vazia.

**5. Um validador tem dois custos.** Seis dos onze *should fix* eram **falsos
rejeitos** — respostas legítimas da loja recusadas, cada uma a gastar uma
repetição do modelo e, ao esgotar o tecto, um *handoff*. Um validador que recusa
tudo tem «0 falsos aceites» e bloqueia a loja. Os casos de controlo positivo são
metade da prova, não um apêndice dela.

---

## Controlo de versões

| Versão | Data | Autor | Alterações |
|---|---|---|---|
| 1.0 | 2026-10-26 | KAM-032 | Emissão: 7 *must fix*, 11 *should fix*, 4 *nice to have*; as correcções, a mutação sobrevivente que apareceu depois delas, e as cinco lições |

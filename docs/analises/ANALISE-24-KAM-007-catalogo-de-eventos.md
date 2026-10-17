# ANÁLISE-24 — KAM-007: catálogo de contratos de evento e *gate* 7

| Campo | Valor |
|---|---|
| Ticket | KAM-007 — Catálogo de eventos: contratos v1, compatibilidade e *lint* de PII |
| Âmbito | Os 38 contratos de `contratos/eventos/`, o pacote `tools/contract_diff/` (classificador, *lint* de PII, exemplos, `versao_max`, leitura do ramo base, gerador, CLI e canário), a emenda 1.11 e 1.12 do dicionário, os tipos gerados para TypeScript e Python, o `validarPayload`, e o *gate* 7 ligado no `Makefile`, no `ci.yaml` e no `docs/ci.md` |
| Método | Revisão adversarial **independente**: um subagente recebeu os requisitos (bloco do ticket, `docs/tecnica/06` §4, §5, §6.6, §7.1 e §7.3) e o código, e **nunca as justificações de quem o escreveu**. Mandato: procurar razões para estar errado, com dez perguntas fixas, e dizer explicitamente onde procurou e não encontrou |
| Resultado | 15 achados — 1 crítico, 7 maiores, 7 menores. **13 corrigidos**, 2 declarados (m6 e m7) |
| Veredicto do revisor | **APROVADO COM RESSALVAS** |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. O que a revisão mudou, em três frases

O achado C1 é o que justifica a leitura mais dura desta entrega: o *lint* de
PII — a peça que existe para impedir que dado pessoal saia num evento —
comparava os sete nomes do §7.3 **por segmento exacto**, e com isso passava o
plural de cada um deles e o vocabulário inglês inteiro. `nomes`, `telefones`,
`emails`, `phone`, `mail`, `address`, `full_name`, `msg`, `wa_id`: vinte e
cinco nomes que o revisor demonstrou a atravessar o gate.

O segundo é o M2, e a sua medida é o número: o `agregado.tipo` era texto livre
nos trinta e oito contratos, e no minuto em que passou a `const` **apanhou
vinte e sete dos trinta e oito exemplos** com `agregado.tipo: "order"` — o
valor da primeira pasta, copiado. Estavam todos «válidos» porque nada os lia.

O terceiro não é um defeito de código: é uma afirmação do próprio ticket que
não resistia à leitura. A secção de verificação dizia que a regra de PII tinha
«quatro barreiras independentes». Três delas eram a mesma função copiada para
três linguagens, com o buraco do C1 nas três.

## 2. Os achados

### C1 — o *lint* de PII falhava nos plurais e em todo o inglês — **corrigido**

`tools/contract_diff/pii.py`. A comparação era `segmento in PROIBIDOS`, e a
razão de ser por segmento era boa: procurar por subcadeia apanhava `nome`
dentro de `numero_publico`. O que faltou foi reparar que a escolha fechava a
porta a `nome` e a deixava aberta a `nomes`.

A demonstração do revisor, reproduzida:

```
nomes PASSA   telefones PASSA   emails PASSA   moradas PASSA   textos PASSA
phone PASSA   telephone PASSA   mail PASSA     address PASSA   endereco PASSA
msg PASSA     wa_id PASSA       full_name PASSA   customer_name PASSA
```

Só bloqueavam `nome_completo`, `texto_livre`, `review_texto` e
`morada_entrega` — a forma singular composta, que é precisamente a que ninguém
escreve por acidente.

**A correcção** compara por **raiz**, aceitando a raiz e a raiz mais «s», e
acrescenta o vocabulário inglês e as abreviaturas. Não se usa `startswith`,
que apanhava `nomeacao`. Os plurais em «-ções» escrevem-se à mão, porque a
regra do «s» não os cobre.

**E tem uma consequência que vale mais do que a correcção.** A lista aprovada
de `ci/contratos-allow.yaml` — a que o §7.3 nomeia e nunca enumera — tinha
nascido vazia, e o ticket apresentava isso como virtude. Com o *lint* a
funcionar, o primeiro nome apanhado foi `phone_number_id`, que é o
identificador que a Meta dá ao **número do tenant** e não o telefone de
pessoa nenhuma. A entrada está escrita, com a razão por extenso. Um *lint* que
nunca precisa de excepção é um *lint* que nunca apanha nada.

**Sobre as «quatro barreiras».** Ficam três implementações, porque correm em
sítios diferentes e em momentos diferentes, e a quarta — o *gate* 3b — é
genuinamente independente. Mas a frase mudou: não são independentes por serem
três, são três cópias que agora partilham a **regra certa** em vez de
partilharem o buraco.

### M1 — os 38 contratos admitiam `classe_pii: "P2"` — **corrigido**

O §7.1 é categórico: «sem PII crua em eventos (P2 proibida)». O enum do
envelope era `["P0","P1","P2"]` nos trinta e oito, e a única verificação de P2
incidia sobre o **exemplo**. Um produtor que emitisse `classe_pii: "P2"`
passava o contrato, passava o `validarPayload` (que não olha para o envelope)
e passava o *gate* 7 inteiro. A base de dados também não o impede: o
`events_log.classe_pii` é `text NOT NULL` sem `CHECK`.

O enum passa a ser o que o §5 dá a cada tipo: `["P0"]` nos dezanove eventos
P0, `["P0","P1"]` nos restantes. Não é `const` porque a classe do §5 é um
**máximo** — um `order.created` sem `contact_id` é legitimamente P0.

### M2 — o `agregado.tipo` era livre, e a *docstring* prometia o que não fazia — **corrigido**

A `exemplos.coerencia` dizia, por extenso: «um exemplo cujo `agregado.tipo` não
bata com o do catálogo passa, e um cuja `classe_pii` seja mais permissiva do
que a do §5 também. **Estas são as duas** que o schema sozinho não apanha.» O
código a seguir verificava `tipo`, `versao` e `classe_pii == "P2"`, e nunca
tocava no `agregado.tipo`.

As duas verificações passaram a existir — e no sítio certo, que é o **schema**:
`agregado.tipo` com `const` lido do §5, `classe_pii` com `enum` limitado. Falha
agora na validação, que é mais forte do que falhar no *lint*, porque passa a
valer também para o produtor.

**O que apanhou no dia em que entrou:** 27 exemplos de 38.

### M3 — duas divergências resolvidas e não registadas — **corrigido**

A emenda 1.11 resolveu `preco_tipo` contra `preco_modo` e `expira_at` contra
`expires_at` «a favor do dicionário», e **não pôs nenhuma das formas antigas
na coluna «Substitui»**. Duas consequências, as duas mensuráveis:

1. A migração que criasse `catalog_items.preco_modo` ou
   `platform.stock_reservations.expires_at` — DDL que o `docs/tecnica/03`
   escreve — falharia o *gate* 3b por um nome que o documento técnico manda
   usar, sem variante que o explicasse.
2. O *gate* 3b não contava as ocorrências nos documentos, porque só conta
   variantes **registadas**. A contradição estava invisível dos dois lados.

A emenda 1.12 regista as duas. No momento em que entraram, o *gate* passou a
ver **18 ocorrências** em três documentos técnicos, declaradas como dívidas em
`ci/canon-allow.yaml` com o prazo de trinta dias da casa.

**A segunda metade deste achado fica por fechar**, e está declarada: o revisor
nota que `cliente` e `consulta` já são nomes canónicos, e que o *gate* 3b
aceita um nome canónico **em qualquer posição** — pelo que um payload com um
campo `cliente` passaria as duas barreiras. É uma decisão maior do que este
ticket (restringir a aceitação do *gate* 3b por superfície) e está em
`docs/contratos.md` §6.

### M4 — o critério 1 estava guardado por uma contagem, não pela fonte — **corrigido**

```python
ESPERADOS = 38
def test_sao_trinta_e_oito_e_carregam_todos(self):
    self.assertEqual(len(self.contratos), ESPERADOS)
```

O critério 1 não fala de **quantos**, fala de **quais**: «100% dos tipos de
Fase P». Apagar o `order.paid` e acrescentar um `foo.bar` deixava este teste
verde, o *gate* verde e o *gate* 3b verde.

Hoje a bateria lê a tabela do `docs/tecnica/06` §5, filtra a coluna Fase, e
exige **igualdade de conjuntos** com o catálogo, com os oito tipos de fora
nomeados um a um e com a razão de cada um. A verificação inversa também passou
a existir: nada de Fase C ou D pode ter contrato.

Uma nota de leitura ficou registada como dívida: o §5 escreve as famílias em
abreviatura (`tenant.activated` / `.suspended`), e numa linha isso não dá o
nome certo — `privacy.erasure_requested` / `.applied` quer dizer
`privacy.erasure_applied`. A correcção está à vista num dicionário de uma
entrada, em vez de escondida numa regra que acerte nos dois casos.

### M5 — o lado Python não exprimia nada, e não tinha validador — **corrigido**

Os trinta e oito `TypedDict` saíam `total=False`: **nenhum campo era
obrigatório** para um verificador de tipos. O argumento que sustenta o critério
6 — «essa metade é do compilador, pelo tipo gerado» — não tinha contraparte
deste lado, e o `agent-runtime`, que é Python, é o produtor de `review.created`
e dos três `query.*`, todos de Fase P.

Gera-se agora `total=True` com `NotRequired` nos opcionais, e escreveu-se o
`validar_payload`, espelho do `validarPayload` de `@kamba/core-ts`, com o
mesmo limite declarado. O `CATALOGO` Python era gerado e **nada o lia**.

Detalhe que custou uma medição: o ficheiro gerado deixou de ter
`from __future__ import annotations`. Com ele, as anotações ficam texto e o
`TypedDict` não reconhece o `NotRequired` **em execução** — o
`__required_keys__` passa a dizer que todos os campos são obrigatórios, que é o
contrário do que o ficheiro declara. O mypy lê-o bem nos dois casos; o que se
perde é a verdade em *runtime*, e é dela que um teste se serve.

### M6 — o `docs/eventos.md` contradizia-se a si próprio — **corrigido**

As linhas 129-137 diziam que «fica por decidir se o contrato v1 tem nove ou
treze campos de topo» e que, «enquanto não estiver tomada, qualquer
`v1.schema.json` que declare os treze campos **falha o gate 3b**». A linha 565
do mesmo ficheiro, escrita por este PR, diz que a decisão fechou em catorze. E
a afirmação sobre o *gate* era falsa, medida: `canon_lint` diz
`eventos: 38 ficheiro(s)` / `conforme`, com os trinta e oito a declarar
catorze.

O revisor acrescentou a observação que mais incomoda: a entrada 1.25 do
controlo de versões das dívidas afirma que o resíduo foi «encontrado a
verificar que nenhum documento vizinho ficou a contradizer este» — e a
verificação não alcançou **o ficheiro que o próprio PR estava a editar**.

### M7 — os dois pagamentos eram indistinguíveis — **corrigido**

O §5 diz que `payment.confirmed` é emitido «**só** por *callback* autenticado
(ADR-013)» e que `payment.manual_confirmed` é «confirmação humana auditada».
Os dois contratos declaravam o **mesmo** objecto `autenticacao`, com
`authn_method ∈ {hmac, manual, consulta}` nos dois. O único facto que separava
os dois eventos era o nome do tipo, e o DAT, que o §5 manda contar o manual «à
parte», não tinha por onde reconciliar.

Os domínios passam a ser disjuntos — `{hmac, consulta}` e `{manual}` — e o
`authn_ok` passa a `const: true`, porque «confirmado» com autenticação
falhada é uma contradição em termos.

**O que não se fez, e porquê.** O revisor argumenta que o aprovador devia ir no
payload, por uma referência pseudónima, e que não o fazer deixa a auditoria que
o §5 exige sem rasto no evento. O argumento é bom e a decisão foi **devolvida**,
não tomada: o §7.1 classifica uma referência a pessoa como **P1**, e o §5 fixa
este evento em **P0** — pôr lá o aprovador obriga a reclassificar o evento
contra a sua própria fonte. A leitura que fica escrita é a da minimização: a
auditoria vive no registo de cobranças, com ACL de *tenant*, que é o que o §7.1
manda («vai-se buscar por referência»). Está em `docs/contratos.md` §6,
decisão 6.

### m1 — o classificador rebentava em vez de falhar fechado — **corrigido**

A *docstring* do `diff.py` promete, desde o primeiro dia, que «uma diferença
que este classificador não saiba ler é classificada quebrante». Cumpria-o só
para as **palavras-chave**. Três formas levantavam `TypeError` e abortavam o
`check` inteiro:

| forma | o que acontecia |
|---|---|
| `items` em tuplo | `TypeError: unhashable type: 'dict'` |
| `enum` de objectos | `TypeError: unhashable type: 'dict'` |
| subschema booleano | `TypeError: 'bool' object is not iterable` |

Nenhuma existe nos trinta e oito contratos de hoje — o revisor verificou-o. A
que aparecesse no **ramo base** matava o *gate* para toda a gente, com uma
mensagem que não aponta para o contrato nem para a causa. E um *gate* que
morre não é um *gate* que bloqueia: é um *gate* que alguém desliga.

### m2 — o único silêncio do classificador — **corrigido**

O acrescento ao `required` era filtrado por `properties` e a remoção não. Um
`required` novo sobre um campo não declarado saía como **lista vazia**: nem
quebrante, nem aditivo, diferença nenhuma. O schema é mal formado, mas
devolver vazio é pior do que classificar mal — o *gate* diz «sem diferenças»
sobre um documento que mudou.

### m3 — anotação pura custava uma versão — **corrigido**

`default`, `examples`, `deprecated`, `readOnly` e `writeOnly` estavam no mesmo
plano de `type`, quando são anotação tão pura como a `description` que já
estava isenta. Entraram nas `CONHECIDAS`.

Duas das três classes de «falso quebrante» que o revisor mediu **ficam
quebrantes de propósito**, e o que mudou foi a mensagem: acrescentar um `enum`
onde não havia saía como «o domínio ganhou», que descreve ao contrário o que
aconteceu. Fechar um campo livre parte o **produtor**; abrir um campo fechado
parte o **consumidor**. São os dois quebrantes, por lados diferentes, e agora a
mensagem diz qual.

### m4 — o *lint* de PII calava-se perante metade do JSON Schema — **corrigido**

Visitava cinco palavras-chave e ignorava `$defs`, `oneOf`, `allOf`, `anyOf`,
`patternProperties` e `additionalProperties`-como-schema, **sem aviso** —
contraste deliberado com o `diff.py`, que trata o desconhecido como quebrante,
e com o próprio *gate* 3b, cujo leitor segue `$ref` internos. Em vez de se
enumerar o que faltava, que é a forma de voltar a falhar quando o JSON Schema
crescer, o percurso passou a descer por qualquer subdocumento.

### m5 — os testes do critério 2 não viam o dinheiro aninhado — **corrigido**

`order.created.payload.linhas[].preco_minor` era invisível para eles. Os
valores medidos estavam certos — o revisor varreu os trinta e oito
recursivamente e não encontrou um único `"number"` nem um objecto aberto — e o
que faltava era o **invariante**. A bateria `TestAQualquerProfundidade` fá-lo
agora a qualquer profundidade.

### m6 — divergências com o `docs/tecnica/03` não declaradas — **declarado**

O `docs/tecnica/03` tem um **segundo catálogo de eventos**, paralelo ao do §5
e divergente dele: `charge.requested`, `charge.issued`, `payment.mismatch`,
`product.published`, `price.changed`, `stock.changed` — nomes que nem o §5 nem
o dicionário conhecem — e um payload para `payment.confirmed` com `charge_id`
e `paga_via` que o §4 do `06` não dá.

Os contratos seguem o `06`, que é o documento de eventos. O ticket declarava
seis desvios e não declarava este. Fica na linha 37 de
`docs/dividas-documentais.md`, e a parte que é desenho — se o
`payment.confirmed` deve levar `charge_id` para o COM reconciliar sem ir à base
— em `docs/contratos.md` §6, decisão 7.

### m7 — `contratos/converters/` nomeado e inexistente — **declarado**

Os Detalhes Técnicos do bloco nomeiam `contratos/converters/<tipo>/v1_to_v2` e
a pasta não existe. Nenhum critério a exige, porque não há v2. Fica dito na
secção de verificação, que é onde o que não se fez tem de aparecer.

## 3. O que a revisão confirmou

Vale registá-lo, porque uma revisão que só lista defeitos não diz onde a
entrega é sólida:

- **Todos os números citados na secção de verificação conferem.** O revisor
  correu o *gate*, contou os testes por AST, e confirmou nome a nome: 55
  testes no `contract_diff` (8 + 18 + 14 + 15), `TestQuebrante` com 9 casos e
  `TestAditivo` com 3, 38 contratos, 214 mutações aplicáveis, `eventos: 38
  ficheiro(s)` no *gate* 3b.
- **O critério 1 é verdadeiro.** Contou os tipos de Fase P do §5 à mão: 30.
  Estão os 30, mais os oito declarados. Nenhum em falta, nenhum de Fase C ou D
  a mais.
- **O critério 2 é verdadeiro de facto.** Zero `"number"` nos trinta e oito, a
  qualquer profundidade; os sete campos `*_minor` são `integer`; os seis
  payloads com dinheiro têm `currency` com domínio `["AOA"]` e têm-no em
  `required`; zero objectos abertos.
- **O envelope concorda com o KAM-005 campo a campo.** Os catorze campos dos
  contratos são exactamente os que o `jsonb_build_object` do `evt_emitir`
  constrói e os que o `CAMPOS_DO_ENVELOPE` do `lerEnvelope` exige, com o `seq`
  dentro do `agregado` e com os quatro campos nuláveis certos.
- **O *gate* 7 bloqueia mesmo, nos três sítios**, e o revisor verificou o
  quarto que ninguém tinha verificado: **num PR de um *fork*** o `origin` do
  `actions/checkout` é o repositório base, pelo que `origin/main` existe e é o
  ramo certo; e o `|| true` do *fetch* não abre furo, porque o `base.py` recusa
  com saída 2 se a referência faltar.

## 4. A lição desta revisão

É a mesma de três entregas seguidas, com uma forma nova: **uma verificação que
nunca encontra nada não está verificada.** O *lint* de PII passava sobre
trinta e oito contratos sem um único achado, e isso lia-se como prova de que os
contratos estavam limpos. Era prova de que o *lint* não funcionava. A lista
aprovada vazia, que o ticket apresentava como virtude, era o sintoma: uma
excepção nunca necessária é uma regra nunca aplicada.

O mesmo padrão aparece no M2 — a `coerencia()` só era exercitada pelo caminho
em que devolve vazio — e aparece outra vez na prova por mutação desta mesma
correcção, que é onde ele ficou mais claro. **Quatro das dezoito mutações
sobreviveram à primeira passagem**, e duas delas sobreviveram porque o teste
que as provava existia — no `libs/py-core`, que é outra *suite* e que esta
prova não corre. Um invariante provado noutra bateria não protege o ficheiro
que o gera.

## 5. O que fica em aberto

| # | O quê | Onde |
|---|---|---|
| 1 | O `cliente`/`consulta` canónicos e o *gate* 3b a aceitar um nome canónico em qualquer posição | `docs/contratos.md` §6, decisão 6 do M3 |
| 2 | Se o `payment.manual_confirmed` deve levar quem aprovou | `docs/contratos.md` §6, decisão 6 |
| 3 | Se o `payment.confirmed` deve levar `charge_id` | `docs/contratos.md` §6, decisão 7 |
| 4 | As 18 ocorrências de `expires_at` e `preco_modo` nos documentos técnicos | `ci/canon-allow.yaml`, prazo 2026-11-16; `docs/dividas-documentais.md` linha 36 |
| 5 | O segundo catálogo de eventos do `docs/tecnica/03` | `docs/dividas-documentais.md` linha 37 |
| 6 | A ambiguidade da abreviatura `.applied` no §5 | Lida à vista no `LEITURA_CORRIGIDA` da bateria |

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão. Revisão adversarial do KAM-007: 15 achados, 13 corrigidos, 2 declarados. | Equipa KAMBÁ |

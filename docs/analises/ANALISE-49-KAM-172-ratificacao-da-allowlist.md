# ANALISE-49 — KAM-172: a ratificação da allowlist de colunas `*_minor`

| Campo | Valor |
|---|---|
| Ticket | KAM-172 — A allowlist de colunas `*_minor` em `platform`: ratificar ou recusar o afrouxamento de uma caixa do DoD |
| PR | `albinoJimy/kamba-plataforma#108` |
| Data | 2026-11-03 |
| Instrumento | Revisão adversarial por subagente que **não viu o raciocínio** de quem escreveu o ramo: recebeu o diff, o contrato (o bloco do ticket), as fronteiras, e nove áreas onde procurar |
| Base medida | `121666f..HEAD`; a revisão começou em `7d1cf30` e re-mediu tudo contra `f1535cf` |

**Dez achados levantados, dez verificados, dez confirmados, dez corrigidos; um
morreu durante a própria revisão.** Não houve `PLAUSÍVEL` e não houve `MORTO` por
engano do revisor — o único que morreu foi corrigido por mim enquanto ele media,
e ele mediu-o outra vez e disse-o.

## O que a revisão apanhou, por classe

| # | Achado | Gravidade | Estado |
|---|---|---|---|
| 1 | A razão escrita para o `ADR-L` ficar local **nega o disjunto errado** do critério do `README.md`, e fecha uma pergunta que os dois precedentes deixam ao fundador | bloqueia | corrigido |
| 2 | O mesmo facto classificado nos **dois ramos** do critério 2 («alterar o critério de um *gate*» em três documentos; «nada em §4 muda» na célula), sem reconciliação | bloqueia | corrigido |
| 3 | A tabela «Quem fica bloqueado» continua falsa no ficheiro; a correcção vivia só numa célula de verificação | bloqueia | corrigido |
| 4 | Das três pernas da forma ratificada, a do `bigint` é a **única sem canário** | nota | corrigido (canário novo) |
| 5 | «Fundiu **antes** da decisão» afirmado como facto em cinco sítios, e nada no registo o pode ordenar | corrige | corrigido (passa a INDÍCIO) |
| 6 | «esta ratificada» sem acento, na abertura em negrito da linha de versão do EPIC-01 | nota | corrigido |
| 7 | A emenda que fechou a contradição aponta para o **parágrafo errado** | corrige | corrigido |
| 8 | «Três parágrafos acima» não reproduz (são dois abaixo e um acima) | nota | corrigido |
| 9 | «Só é possível se» sobre um efeito da **ordem de descoberta** do `unittest` | nota | corrigido |
| 10 | «A corrida sobre a árvore que funde» não é verdade à letra do HEAD | nota | corrigido |

## As três lições que valem mais do que os achados

**1. Negar um disjunto não nega a disjunção.** O critério do
[`../adr/README.md`](../adr/README.md) para uma decisão local subir a canónica é
«porque outro subsistema depende dela, **ou** porque contradiz um ADR em vigor».
A primeira versão do `ADR-L008` concedia o primeiro disjunto por escrito — «esta
governa quatro tickets» — e depois escrevia, como primeira razão para ficar local,
«não contradiz o ADR-004». **A razão era inválida na forma, não discutível no
conteúdo.** E a consequência era pior do que o erro lógico: o `ADR-L005` e o
`ADR-L006` têm os dois uma secção chamada «Esta decisão é candidata a subir a
canónica, **e isso não se decide aqui**», que conclui «o critério aponta para
cima» e nomeia quem promove; o `ADR-L008` concluía «fica local por três razões, e
a terceira é a que decide». Num ticket cujo objecto é que este tipo de decisão é
do fundador, o executor tinha fechado à sua mesa a pergunta que os precedentes
deixam fora dela.

**2. Uma contradição entre documentos pode ser aparente — e mede-se.** O ticket,
a linha 1.51 do `EPIC-01` e o bloco KAM-043 dizem «alterar o critério de uma
verificação que bloqueia», e a célula do critério 2 dizia «nada em §4 muda». As
duas são verdadeiras e falam de coisas diferentes — **quem decide** contra **que
documento carrega o critério** —, mas isso não estava escrito em lado nenhum. A
reconciliação que ficou não é retórica, é uma medição: o *gate* 8 corre **27**
asserções de catálogo só no `test_catalogo.py`, e o §4 não nomeia **nenhuma**
(zero ocorrências de `saldo`, `_minor`, `phone_hmac`, `timestamptz` ou
`platform.`). A granularidade de §4 nunca foi o registo das asserções de cada
suite.

**3. Um canário por perna, e não um canário por ticket.** O `ADR-L008` vende a
forma ratificada como **três** garantias conjuntas: declarada na allowlist,
verificada nos dois sentidos, e `bigint` e não `numeric`. Os dois canários da
primeira entrega cobriam as duas primeiras, e a terceira ficava sem prova —
**apagar o laço do tipo inteiro não avermelhava nenhum dos 656 testes**, porque
os ensaios criavam sempre a coluna como `bigint` e a asserção do conjunto rebenta
antes de o laço correr. Era o defeito deste ticket a repetir-se na perna que
faltava. O canário novo
(`test_canario_uma_coluna_declarada_mas_numeric_tambem_falha`) tem de declarar a
entrada **e** criar a coluna `numeric` ao mesmo tempo: declarada para chegar ao
laço, `numeric` para ele a recusar.

## O que a revisão confirmou, e que fica registado para não se pagar outra vez

O revisor não se limitou a procurar defeitos: mediu o que **não** estava errado, e
duas dessas medições são caras de refazer.

**A prova de que o canário morde, por mutação mental de cada asserção que ele
guarda.** Apagar o `assertEqual(proibidas, [])` → os três ensaios deixam de
levantar e o `assertRaises` fica vermelho. Apagar **uma** das três cláusulas `OR`
→ só o `subTest` correspondente fica vermelho, pelo que cada sub-padrão está
guardado individualmente. Apagar a igualdade de conjuntos → os dois sentidos
deixam de levantar. Enfraquecê-la para subconjunto → **o sentido 2 passa a ser o
único que apanha**, o que mostra que ele não é cerimónia. Estragar o filtro
`table_schema = 'platform'`, que é a forma exacta da vacuidade original → os dois
canários ficam vermelhos.

**Os caminhos em que a tabela de ensaio podia sobreviver, percorridos um a um.** O
`CREATE` a falhar sobre uma fuga anterior é auto-curativo (o `finally` limpa, e a
excepção de BD não é `AssertionError`, logo o teste é **alto** e não silencioso);
o `DROP` por *lock* não é alcançável (as ligações do teste só leram
`information_schema`/`pg_catalog` e foram revertidas antes); `ComBase.setUpClass`
**não** faz `downgrade`, pelo que nada reconstrói o esquema entre classes e a
limpeza tem de ser a do `finally` — e é. **O único caminho residual**, e fica
escrito porque é a ordem frágil: se um `conexao.rollback()` do laço do `finally`
levantasse, o `DROP` nunca corria. Não é alcançável hoje; o `DROP` estar **depois**
do laço, e não em `try` próprio, é o que o torna concebível.

E o `patch.object(type(self), …)` não tem fuga: `EM_UNIDADE_MENOR` está no
`__dict__` de `TestConvencoes`, logo o `__exit__` repõe por `setattr` e não apaga;
não há subclasse; e o `correr_suite.py` corre de um só fio, pelo que a mutação não
pode cruzar testes.

## E a correcção do achado 4 descobriu uma quarta lição, que nenhum dos dois viu

**Um `subTest` não propaga a falha: regista-a no `TestResult` corrente.** O laço
do tipo do `test_nao_ha_colunas_de_dinheiro_nem_saldos` corre dentro de um
`subTest`, pelo que chamar esse teste de dentro de outro — que é como os três
canários o exercitam — dá **duas coisas erradas ao mesmo tempo**:

```text
AssertionError: AssertionError not raised      o assertRaises nao ve excepcao
FAIL: test_canario_..._numeric_tambem_falha    e a falha do ensaio e contada
      (coluna='canario_kam172.ensaio_minor')   contra o proprio canario
```

Não é teoria: é o que o *gate* 8 devolveu na corrida seguinte à correcção do
achado 4 — `Ran 657 tests` / `FAILED (failures=2)`, e as duas eram o mesmo
canário a falhar pelas duas pontas. **Custou uma corrida do *gate* inteiro**
(≈ 6 min) e vale o registo, porque a forma errada é a que qualquer um escreve
primeiro.

A forma certa, e que os três canários passaram a usar: correr o teste guardado
numa instância própria com `TestResult` próprio
(`type(self)("test_…").run(resultado)`), e afirmar sobre
`resultado.failures + resultado.errors`. Apanha as falhas de `subTest` — que era
exactamente o que faltava para a perna do tipo — e não deixa a falha do ensaio
escorrer para o resultado da suite. **A consequência que importa:** um canário
escrito com `assertRaises` sobre um teste que use `subTest` pode ficar verde sem
provar nada, se o único caminho de falha do ensaio for o de dentro do `subTest`.

## O que fica por fechar, e é de outro

**A hora da decisão.** O `ADR-L008` tem data e não hora, e o *commit* do KAM-053
tem as duas (`2026-11-03 09:25:39 +0100`). A ordem dentro do dia **não é derivável
do registo**, e por isso passou a INDÍCIO nos cinco sítios onde estava afirmada
como facto. Quem quiser fechá-la, o que falta é a hora da resposta do fundador, e
o sítio é a secção «Decisão» daquela página. A cobertura das três entradas do
KAM-053 não depende da ordem, e é por isso que isto não bloqueia.

**O docstring da revisão `0027`.** Ele diz, por escrito, «a `payment_charges` é o
KAM-055» — e ela chegou com o KAM-053, na `0029`. É resíduo do KAM-053 e não deste
ramo, está fora do diff, e não foi tocado.

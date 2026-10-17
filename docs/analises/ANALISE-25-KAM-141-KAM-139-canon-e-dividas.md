# ANÁLISE-25 — KAM-141 e KAM-139: contradições do dicionário e dívidas do *gate* 3b

| Campo | Valor |
|---|---|
| Tickets | KAM-141 — contradições do dicionário canónico encontradas pelo *gate* 3b; KAM-139 — variantes vivas em `docs/tecnica/` fora das 12 do KAM-111 |
| Âmbito | `specs/02_Dicionario_de_Dados_Canonico.md` (emenda 1.13), `tools/dict_export/`, `tools/canon_lint/`, `ci/canon-lint.yaml`, `ci/canon-allow.yaml`, e `docs/tecnica/02` a `06` |
| Método | Revisão adversarial **independente**: um subagente recebeu os requisitos e o código, e **nunca as justificações de quem o escreveu**. Mandato: procurar razões para estar errado, com dez perguntas fixas |
| Resultado | 11 achados — 1 crítico, 4 maiores, 6 menores. **8 corrigidos**, 3 registados como dívida |
| Veredicto do revisor | **APROVADO COM RESSALVAS** |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |

---

## 1. O que a revisão mudou, em três frases

O achado C1 é o que justifica a leitura dura: o KAM-139 trocou `preco_kz` por
`preco_minor` no contrato de saída do `search_catalog` (`docs/tecnica/05`
§6.3), e **não** trocou o `value_kz` do validador de citação que lê esse
contrato (`docs/tecnica/02` §9.1). O resultado era a rede de segurança do preço
citado — a peça do ADR-007 que impede o assistente de inventar um preço — a
comparar cêntimos com Kz e a falhar **sempre**, por um factor de cem.

O segundo é de fronteira: quatro épicos (`EPIC-03`, `04`, `05`, `06`) passaram
a conter **critérios de aceitação que mandam escrever código que o *gate* 3b
recusa**, porque as emendas 1.12 e 1.13 registaram como variantes nomes que
esses critérios usam. O `docs/tecnica/04` §6.2 foi corrigido; o bloco do
KAM-053, que é o que o implementador lê primeiro, não.

O terceiro é sobre a peça que este PR introduziu: o `_so_no_registo`, que
passou a ser a **única** fonte da distinção entre domínio do registo e domínio
de coluna, era uma heurística de frase que a revisão enganou de quatro formas,
todas com falha silenciosa.

## 2. Os achados

### C1 — o validador de citação comparava cêntimos com Kz — **corrigido**

`docs/tecnica/02` §9.1, linhas 566, 569 e 580.

```python
if not any(f.kind in MONEY_KINDS and f.value_kz == m.value_kz for f in facts): ...
```

O *fact* vem do `search_catalog`, cujo contrato de saída este PR mudou para
`preco_minor` (cêntimos). O token vem do texto que o assistente escreveu, em
Kz. `1250000 == 12500` é falso, e o único caminho em que passava era o
assistente escrever «1 250 000 Kz» a um cliente angolano.

O *gate* não o via — `value_kz` não é variante registada — e as sete decisões
de derivados do critério 2 do KAM-139 não o cobriam, porque a lista era do `05`
e do `06` e este estava no `02`. **É exactamente «o sítio onde o nome mudou e o
valor não» que a pergunta 2 do guião mandava procurar, e que a entrega não
encontrou.**

A correcção é `value_minor`, e o parágrafo da normalização passa a dizer por
extenso quem converte: o cliente e o assistente falam em Kz, a comparação
faz-se em cêntimos.

### M2, M3 e M4 — quatro épicos a mandar escrever código que o *gate* recusa — **registados**

Três achados da mesma família, e a classificação deles foi a decisão mais
difícil desta revisão.

- **M4.** `specs/EPIC-05`, doze linhas, escrevem o `CHECK` de `authn_method`
  com `hmac_sha256`, `status_pull` e `humano_auditado` — as três formas que a
  emenda 1.13 acabou de registar como substituídas. A linha 154 tem duas na
  mesma expressão. A tabela do próprio KAM-141 enuncia a consequência como «o
  DDL do **KAM-053**, copiado do documento, é recusado pelo *gate*» — e o
  KAM-053 vive no EPIC-05. Antes da emenda, falhava com «fora do dicionário»;
  depois dela, falha com «variante». **A mensagem melhorou; a contradição mudou
  de sítio.**
- **M3.** `specs/EPIC-04` §171 lista `kamba_ops` entre os «papéis Postgres em
  uso». É o mesmo papel inexistente que o KAM-139 corrigiu no `docs/tecnica/04`
  §6.2, com a justificação «o KAM-053 ia copiá-la» — e o argumento aplica-se
  com mais força ao critério de aceitação do épico.
- **M2.** `specs/EPIC-06` §85 e `specs/EPIC-04` §838 descrevem uma regra de
  conversão (`preco_minor/100`, `fixo→exato`) entre o `docs/tecnica/05` e o
  `03` que **deixou de ser precisa**: os dois já dizem o mesmo. E o `EPIC-04`
  §846 exige que a vista `com.v_oferta_viva` exponha `preco_kz` — um critério
  de aceitação que manda criar uma variante registada.

**Porque é que ficam registados e não corrigidos.** São blocos de outros
tickets, e o KAM-141 acabou de recusar, por princípio, reescrever o critério 6
do KAM-111 para o poder dar por cumprido. Corrigi-los aqui seria aplicar a
regra contrária à que o PR defende três parágrafos antes. Ficam nas linhas 38 e
39 de `docs/dividas-documentais.md`, com os números de linha medidos e com a
consequência dita sem atenuantes.

### M5 — o `so_no_registo` era uma heurística com quatro buracos — **corrigido**

`tools/dict_export/exportar.py`. A primeira versão procurava «No registo» em
**todo** o prefixo da célula e localizava a declaração pelo nome:

```python
antes = celula.split(f"`{alvo}`")[0]
return bool(_SO_NO_REGISTO.search(antes))
```

| Caso | Célula | Dava | Devia dar |
|---|---|---|---|
| duas declarações, frase só na primeira | `No registo: `id` ∈ {…}. E a coluna `tenants.tipo` ∈ {…}` | `True`, **`True`** | `True`, `False` |
| mesmo nome duas vezes, coluna primeiro | `Na coluna `modulo` ∈ {…}. No registo: `modulo` ∈ {…}` | **`False`, `False`** | `False`, `True` |
| «No registo **e também na coluna**» | `No registo e também na coluna: `modulo` ∈ {…}` | **`True`** | `False` |
| «no registo» em prosa inocente | `… guardado no registo de auditoria; a coluna `tenants.tipo` ∈ {…}` | **`True`** | `False` |

**O modo de falha é sempre o mesmo e é silencioso:** um domínio marcado a mais
faz o `dominio_de()` devolver `None`, e o *gate* deixa de verificar aquele
domínio sem dizer nada.

A correcção usa a **posição** de cada declaração (`finditer`), limita a procura
à frase imediatamente anterior, e trata «e também na coluna» como negação. Os
quatro casos da revisão são hoje o `test_as_quatro_formas_que_enganavam_a_heuristica`.

Atenuante que a revisão mediu e que vale registar: o `dominio_de()` consulta
primeiro o domínio **qualificado**, que ignora o `so_no_registo`. `tenants.tipo`,
`tenant_channels.origem` e `contacts.papel` estavam imunes na prática; os
expostos eram os não qualificados — `authn_method`, `preco_tipo`, `stock_modo`,
`beneficiary_kind`, `currency`.

### m6 a m11 — seis menores

| # | O quê | Disposição |
|---|---|---|
| m6 | Três das cinco linhas de «Controlo de versões» diziam «**KAM-139** (contradições do dicionário)» — que é o título do **KAM-141**. A redacção foi copiada entre agentes | **corrigido** |
| m7 | O *docstring* do `db/rls.py` era o último sítio do repositório a anunciar a divergência `tenant_isolamento`, que este PR fechou | **corrigido** |
| m8 | Oito nomes `*_kz` no `docs/tecnica/07`, fora dos cinco documentos do ticket — com uma colisão real: o `04` §378 tem `valor_declarado_minor bigint` e o `07` §363 tem `valor_declarado_kz` no mesmo conceito | **registado** (dívida 40) |
| m9 | «111 com tipo / 255 sem» não reproduz: são **109 / 257**. A percentagem (30/70) aguentava; os inteiros não | **corrigido**, com o método de contagem escrito |
| m10 | O `assertEqual(cli.main(...), 0)` ficou pendurado no teste errado pela inserção; e nenhum teste prendia o **comportamento** do `so_no_registo` depois de a lista de excepções ficar vazia | **corrigido**, com uma bateria nova que prova que `id uuid PRIMARY KEY` passa e que um valor fora de um domínio não qualificado falha |
| m11 | `status_pull(ev)` era o nome de uma **função** e não um valor de enum; a substituição mecânica deu-lhe o nome de um valor | **corrigido** → `puxar_estado(ev)` |

## 3. O que a revisão confirmou

- **As 12 ocorrências que restam são mesmo citações históricas.** O revisor leu
  as doze linhas uma a uma. Nenhuma é uso vivo.
- **A conversão de unidade está aritmeticamente certa** nos cinco valores do
  `05`, factor 100 exacto, e **não ficou nenhum `int` onde devia ser `bigint`**
  em todo o repositório — verificado em `docs/`, `specs/`, `db/`, `contratos/`,
  `packages/` e `libs/`.
- **Não há comparação cêntimos↔Kz dentro do `05` e do `06`.** A correcção da
  Q5, que somava `gmv_pago_kz` a partir de `total_minor`, verifica-se no *diff*.
- **A protecção não se perdeu com `dominios_so_no_registo: []`.** O revisor
  montou cinco migrações sintéticas numa cópia descartável: `id uuid PRIMARY
  KEY` passa; `tenants.tipo` com um valor inventado falha; `authn_method` com
  `sistema` falha; `currency` com `USD` falha — o domínio novo da emenda morde;
  e `preco_tipo` com `'exato'` dá dois achados.
- **As quatro baterias reescritas são mais fortes, não mais fracas.** Para cada
  uma, o revisor construiu a mutação que repõe o defeito e confirmou que falha.
- **A superfície de código está limpa:** procurou as nove variantes em `db/`,
  `packages/`, `libs/`, `services/`, `contratos/`, `registry/`, `infra/`,
  `ops/`, `.github/` e no `Makefile`. **Uma única ocorrência**, o `db/rls.py`
  do m7.

## 4. A lição desta revisão

**Uma emenda ao canon tem alcance maior do que o seu *diff*.** O KAM-141
registou cinco nomes como variantes substituídas — cinco linhas de tabela — e
com isso tornou falsos, de uma assentada, doze critérios de aceitação em quatro
épicos e um validador de preço noutro documento. O ticket avisava disto no seu
próprio «Detalhes Técnicos» («Uma emenda ao dicionário tem alcance. Um nome que
entre na coluna «Substitui» passa a falhar em todas as superfícies») e a
verificação que se fez foi a que o *gate* alcança — `docs/tecnica/` — e não a
que a frase descreve.

O corolário prático é o C1: a pergunta certa depois de trocar um nome de campo
não é «onde é que este nome aparece», que o *gate* responde, mas **«quem lê o
valor deste campo»**, que nenhum *gate* responde.

## 5. O que fica em aberto

| # | O quê | Onde |
|---|---|---|
| 1 | Os doze critérios do `EPIC-05` com o `CHECK` de `authn_method` nas formas substituídas | `docs/dividas-documentais.md`, linha 38 |
| 2 | O `kamba_ops` no `EPIC-04` §171, a conversão obsoleta do `EPIC-06` §85, e o `preco_kz` exigido pelo `EPIC-04` §846 | `docs/dividas-documentais.md`, linha 39 |
| 3 | Os oito `*_kz` do `docs/tecnica/07` e a colisão de `valor_declarado_*` | `docs/dividas-documentais.md`, linha 40 |
| 4 | A linha 8 do KAM-141 (as 12 + 12 *fixtures*), devolvida a quem escreveu o critério 6 do KAM-111 | Secção de verificação do KAM-141 |
| 5 | O critério 4 do KAM-139 (`registry/vendedor.yaml`), vazio por o sétimo achado ser a linha 6 do KAM-140 | Secção de verificação do KAM-139 |

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão. Revisão adversarial do KAM-141 e do KAM-139: 11 achados, 8 corrigidos, 3 registados como dívida. | Equipa KAMBÁ |

# ADR-L008 — A allowlist de colunas `*_minor` em `platform`: ratificada

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-11-03 |
| Ticket | KAM-172 — A allowlist de colunas `*_minor` em `platform`: ratificar ou recusar o afrouxamento de uma caixa do DoD |
| Âmbito | Local (ver [`README.md`](README.md)): **a forma da caixa «o DDL não modela saldos»** do DoD do **KAM-003**, verificada pelo `test_nao_ha_colunas_de_dinheiro_nem_saldos` de [`../../db/tests/test_catalogo.py`](../../db/tests/test_catalogo.py) no *gate* 8. Não emenda o **ADR-004**, não acrescenta entrada nenhuma à allowlist, não toca na tabela de *gates* do [`../../specs/01_Engineering_Standards_e_Handoff.md`](../../specs/01_Engineering_Standards_e_Handoff.md) §4, e **não** decide a outra metade da mesma caixa do KAM-003 — o tenant `tipo = 'platform'` com `estado = 'ativo'`, que continua devolvida |
| Decisores | **O fundador, a 2026-11-03** |
| ADRs canónicos aplicáveis | **ADR-004** (pagamentos via facilitador; liquidação directa à PME; a plataforma nunca detém fundos) |
| Documentos aplicáveis | [`../../db/tests/test_catalogo.py`](../../db/tests/test_catalogo.py) (`EM_UNIDADE_MENOR`); [`../../specs/tickets/KAM-003.md`](../../specs/tickets/KAM-003.md) (DoD); [`../../specs/EPIC-04_Core_Comercio.md`](../../specs/EPIC-04_Core_Comercio.md) (blocos KAM-043 e KAM-044); [`../../specs/EPIC-05_Pagamentos_Billing.md`](../../specs/EPIC-05_Pagamentos_Billing.md) (blocos KAM-053 e KAM-055); [`../../specs/02_Dicionario_de_Dados_Canonico.md`](../../specs/02_Dicionario_de_Dados_Canonico.md) §2 e §3.3; [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) §8 |
| Substitui | — (**não** substitui o ADR-004; ver «Isto não é substituição de ADR») |

## Contexto

O `test_nao_ha_colunas_de_dinheiro_nem_saldos` é uma caixa da Definition of Done
do **KAM-003** e corre no *gate* 8. Até 2026-11-02 afirmava que o esquema
`platform` não tem coluna nenhuma cujo nome contenha `saldo` ou `balance`, ou
termine em `_minor` ou `_kz`:

```python
self.assertEqual(linhas, [])
```

**Passava por vazio.** Nenhuma tabela de `platform` tinha dinheiro: a
`payment_accounts` da revisão `0027` guarda capacidades e um beneficiário, não
valores, e o único `preco_minor` do repositório vivia em `servicos.services` —
outro esquema, que a consulta do teste não vê, porque filtra
`table_schema = 'platform'`. A asserção era verdadeira sobre um conjunto vazio, e
por isso nunca disse nada sobre o que devia acontecer quando dinheiro aparecesse.

O **KAM-043** trouxe o primeiro, e com ele a contradição: o critério 1 daquele
bloco manda, à letra, «valores em `bigint` minor», e as duas tabelas da revisão
`0028` têm `offer_terms.preco_minor` e `price_quotes.preco_total_minor`. Ou
`platform` não tem colunas `*_minor`, ou o KAM-043 cumpre o seu critério 1.

O que o KAM-043 entregou foi a **distinção** e a **medição**, e disse por escrito
que a decisão não era dele:

```text
saldo, balance, _kz   proibidos SEM EXCEPÇÃO, e a asserção continua `== []`
_minor                allowlist declarada em EM_UNIDADE_MENOR, coluna a coluna,
                      com a razão de cada uma, verificada NOS DOIS SENTIDOS,
                      e com a afirmação de que o tipo é `bigint` e não `numeric`
```

## Decisão

**Ratificada.** A allowlist declarada é a forma certa da caixa «o DDL não modela
saldos» do DoD do KAM-003: uma coluna em unidade menor pode existir em `platform`
desde que esteja declarada em `EM_UNIDADE_MENOR` com a razão escrita pela qual
não é um saldo, e `saldo`, `balance` e `_kz` continuam proibidos **sem excepção**.

A pergunta e a resposta, textuais:

> **Pergunta ao fundador:** «Ratificas o afrouxamento da caixa do DoD que o
> KAM-172 descreve?»
>
> **Resposta, a 2026-11-03:** «Ratifico»

A razão que a ratificação aceita é a que o KAM-043 escreveu: o que a caixa proíbe,
e o que o **ADR-004** funda, é a plataforma **deter fundos de terceiros** —
*saldos*. Um preço de catálogo não é um saldo; é um número que o dono publica para
o agente citar, e a plataforma não detém nada por causa dele.

## Onde é que isto fica vinculativo, e porque é aqui

O critério 2 do KAM-172 dá duas hipóteses e manda escolher com razão: um `ADR-L`
novo, **se for decisão de execução**, ou uma emenda ao `specs/01` §4, **se mudar o
critério de um *gate***. A escolha é a primeira, e a razão é que nada em §4 muda:

1. **A linha do *gate* 8 em §4 continua inteiramente verdadeira.** Ela diz
   «Migrações — aplicar e reverter; sem perda em dados de teste», e «Falha
   bloqueia: Merge». O *gate* continua a validar as migrações e continua a
   bloquear o *merge*. O que mudou foi a forma de **uma asserção dentro de um dos
   seus testes** — a que implementa uma caixa do DoD do KAM-003.
2. **Não há nada em §4 para emendar: haveria de se lhe acrescentar.** §4 não
   nomeia esta asserção, nem o esquema `platform`, nem o sufixo `_minor` — a
   granularidade da tabela é «que *gates* existem, o que cada um valida, e o que
   a vermelho bloqueia». Pôr uma asserção de um ticket na tabela canónica dos
   *gates* é o erro que o [`README.md`](README.md) descreve ao contrário: fazer
   uma decisão local parecer canónica.
3. **O critério que mudou é de um ticket, não de §4.** A caixa vive em
   `specs/tickets/KAM-003.md`, é reavaliada no próprio bloco por este PR, e a
   regra transversal de §4 — «nenhum *gate* pode ser marcado *skip* sem ADR ou
   aprovação registada» — é sobre dispensas, e aqui não se dispensa nada: a
   asserção fica, com o lado rígido intacto e com um canário novo a prová-lo.

**O contrapeso, dito por inteiro, porque não é pequeno.** O
[`README.md`](README.md) fixa que uma decisão local sobe a canónica «quando passa
a governar mais do que o seu ticket», e **esta governa quatro** — KAM-043 (que a
levantou), KAM-053 (que já escreveu três entradas debaixo dela), KAM-044 e
KAM-055. O caminho que o README dá para esse caso **não é o `specs/01` §4**: é
`../tecnica/00` §8, com o número canónico seguinte, a contagem e o mapeamento de
[`../tecnica/INDICE.md`](../tecnica/INDICE.md) §5 actualizados. Fica local por três
razões, e a terceira é a que decide:

* não contradiz o ADR-004: **lê-o**. Um ADR canónico novo diria, com um número
  novo, o que o ADR-004 já diz — que a plataforma não detém fundos;
* o que esta página registra é a decisão e o seu **alcance**, não uma regra de
  produto nova;
* **e há um gatilho escrito para subir.** No dia em que um ticket precisar de uma
  entrada que **não** seja um preço de catálogo, o montante de uma cobrança ou um
  facto de *ledger* — uma coluna cujo valor a plataforma **acumule** —, a pergunta
  deixa de ser sobre o nome da coluna e passa a ser sobre o próprio ADR-004. Essa
  é canónica, e não se decide aqui nem num `ADR-L`.

(**Não se escreve aqui o número canónico que ele teria**, pela razão que o
`ADR-L005` e o `ADR-L006` já registaram: o `lint_refs` recusa uma referência a um
`ADR-NNN` que o §8 não tem.)

## Isto não é substituição de ADR

O **ADR-004** diz que a liquidação é sempre directa à PME e que a plataforma nunca
detém fundos; receber-e-repassar, *escrow* e *payouts* são actividades reguladas,
só por PSP licenciado e fora do Piloto. Nenhuma das cinco colunas da allowlist
faz a plataforma deter nada:

* `offer_terms.preco_minor` e `price_quotes.preco_total_minor` são **preço
  publicado** e **total cotado** — números que o dono escreve para o agente citar;
* `payment_charges.amount_minor` é o montante **de um pedido de pagamento**, que
  não muda depois de emitido e cujo dinheiro vai da conta do cliente para a da
  PME;
* `payment_events.valor_minor` é o valor **de um facto** registado num *ledger*
  *append-only*: não se soma a nada, registra-se;
* `v_payment_events_audit.valor_minor` é a projecção dessa mesma coluna na vista
  de auditoria.

O estado do ADR-004 não muda, nenhum ADR entra ou sai de `../tecnica/00` §8, e a
contagem e o mapeamento de `../tecnica/INDICE.md` §5 ficam como estão (**vinte**,
`ADR-001` a `ADR-020`).

## Alcance da decisão

**Três coisas que ela inclui, e duas que não.**

**Vale para vistas tanto como para tabelas, e isto é medido.** O
`information_schema.columns` lista as colunas das **vistas**, pelo que o
varrimento de `%_minor` apanha o `valor_minor` que a `v_payment_events_audit`
projecta — e é por isso que ela tem entrada própria na allowlist, com a razão
escrita ao lado. Uma vista nova que exponha uma coluna de dinheiro responde a esta
pergunta exactamente como uma tabela.

**Vale nos dois sentidos.** Uma coluna `*_minor` nova sem entrada falha o teste; e
uma entrada sem coluna na base também falha, porque é uma declaração morta. É a
razão pela qual esta ratificação **não** autoriza inscrever por antecipação as
colunas de um ticket que ainda não correu.

**Vale com o tipo afirmado.** As colunas declaradas são `bigint`, nunca `numeric`:
o §2 do dicionário manda unidade menor **inteira**, e um `numeric` é o defeito que
o nome `_minor` existe para impedir.

**Não abre a porta ao `_kz`.** Essa metade da asserção fica rígida, pela razão do
§3.3 do dicionário — `*_kz` é a variante que ele substitui, e uma coluna assim é
dinheiro em kwanzas inteiros ou, pior, em vírgula flutuante, que o §2 proíbe. O
`saldo` e o `balance` ficam rígidos porque são a coisa que o ADR-004 recusa.

**Não acrescenta entradas.** Cada coluna nova paga a sua linha, com a sua razão,
pela mão do ticket que a cria.

## O canário, e porque é que ele é metade desta decisão

A metade rígida — `saldo`, `balance`, `_kz` — passava **exactamente pelo mesmo
vazio** que a outra: nunca houve uma coluna assim em `platform`, pelo que o
`assertEqual(proibidas, [])` nunca disse nada sobre o que acontece quando uma
aparecer. Ratificar a allowlist sem provar que o lado rígido morde era repetir, no
lado que ficou de pé, o defeito que levou a esta decisão.

Por isso o KAM-172 entrega um passo de canário em
[`../../db/tests/test_catalogo.py`](../../db/tests/test_catalogo.py): uma coluna de
ensaio chamada `saldo_x`, `x_balance` e `x_kz` faz o teste falhar, **uma a uma**, e
o ensaio limpa-se e o teste volta a passar. A medição está na «Verificação dos
Critérios de Aceitação» do bloco
[`../../specs/tickets/KAM-172.md`](../../specs/tickets/KAM-172.md).

## Consequências

**Os três credores encontram a allowlist já lá, e só acrescentam a linha com a
razão.** Era a razão de o KAM-172 ser P0 sem escrever código: uma recusa punha
quatro tickets em conflito em vez de um.

| Ticket | O que traz para `platform` | O que a ratificação lhe diz |
|---|---|---|
| **KAM-044** | `orders_mirror.total_minor` (DDL do `../tecnica/03` §5.4) | Acrescenta a entrada com a razão pela qual o total de uma encomenda não é um saldo |
| **KAM-053** | o *ledger* `payment_events` e a `payment_charges` | **Já entregue, e debaixo da pergunta em aberto.** As suas três entradas ficam cobertas por esta decisão |
| **KAM-055** | nenhuma coluna nova: consome `payment_charges`/`payment_events` e compara o `valor_minor` do evento com `orders_mirror.total_minor` | O nome `*_minor` que o seu critério 1 pressupõe em `platform` está ratificado |

**E a tabela de credores do ticket envelheceu entre a sua abertura e a decisão,
o que fica dito porque muda o alcance do aviso.** O KAM-172 atribuía a
`payment_charges` ao KAM-055; ela chegou com o **KAM-053**, na revisão `0029`,
fundido a 2026-11-03 (`94bd634`, PR #104) — antes desta ratificação. Logo o aviso
ao KAM-053 é **retroactivo**: ele escreveu três entradas com a pergunta ainda
aberta, e o que esta decisão faz é cobri-las. As cinco entradas da allowlist à
data desta página são as duas do KAM-043 e as três do KAM-053.

**O que a ratificação não fecha.** A caixa do DoD do KAM-003 continua **não
satisfeita**, e por uma razão que não é esta: o DDL aceita um tenant
`tipo = 'platform'` com `estado = 'ativo'`, que é a costura do ADR-011 e está
devolvida como decisão própria. O que esta página fecha é a metade dos saldos.

**O custo assumido.** Uma lista declarada é mais frágil do que uma proibição
total: depende de cada autor escrever a razão certa, e uma razão mal escrita passa
o *gate*. A decisão troca uma impossibilidade por uma declaração revista à mão — e
é por isso que a declaração é obrigatória nos dois sentidos, que o tipo é
afirmado, e que o lado rígido tem canário.

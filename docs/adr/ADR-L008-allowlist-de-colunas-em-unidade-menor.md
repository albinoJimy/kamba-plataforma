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
novo, **se for decisão de execução**, ou uma emenda ao
[`../../specs/01_Engineering_Standards_e_Handoff.md`](../../specs/01_Engineering_Standards_e_Handoff.md)
§4, **se mudar o critério de um *gate***. A escolha é a primeira.

**Primeiro, a contradição aparente, porque o próprio ticket a cria.** Os Detalhes
Técnicos do KAM-172, a linha 1.51 do `EPIC-01` e o bloco KAM-043 do `EPIC-04`
dizem todos que isto é «alterar o critério de uma verificação que bloqueia», e é
dessa frase que o ticket tira a sua autoridade (linha **L6**: a decisão é do
fundador) e a sua prioridade **P0**. Essa frase é verdadeira, e é sobre **quem
decide**. A pergunta do critério 2 é outra: **que documento carrega o critério**.
As duas respostas não se anulam — o fundador decidiu, e §4 não é onde este
critério vive.

**E isso mede-se, em vez de se afirmar.** O *gate* 8 corre 27 asserções de
catálogo só em `../../db/tests/test_catalogo.py` — telefone nunca em claro, chaves
primárias `uuid`, toda a coluna `_at` em `timestamptz`, nenhuma FK para fora de
`platform`, oito papéis e só oito, e esta. **O §4 não nomeia nenhuma delas:** zero
ocorrências de `saldo`, `_minor`, `phone_hmac`, `timestamptz` ou `platform.` no
documento inteiro. A linha do *gate* 8 diz «Migrações — aplicar e reverter; sem
perda em dados de teste» e «Falha bloqueia: Merge», e as duas continuam
inteiramente verdadeiras. A granularidade de §4 é «que *gates* existem, o que cada
um valida, e o que a vermelho bloqueia» — não é, e nunca foi, o registo das
asserções de cada suite. Emendá-lo para esta e só para esta punha-o em desacordo
com a sua própria granularidade, e fazia uma decisão de um ticket parecer canon.

O critério que mudou é de um ticket: a caixa vive em
[`../../specs/tickets/KAM-003.md`](../../specs/tickets/KAM-003.md) e é reavaliada
no próprio bloco por este PR. E a regra transversal de §4 — «nenhum *gate* pode
ser marcado *skip* sem ADR ou aprovação registada» — é sobre dispensas: aqui não
se dispensa nada, a asserção fica, o lado rígido fica intacto, e ganha canário.

## Esta decisão é candidata a subir a canónica, e isso não se decide aqui

O [`README.md`](README.md) deste directório fixa o critério: uma decisão local sobe
a canónica «quando passa a governar mais do que o seu ticket — porque outro
subsistema depende dela, **ou** porque contradiz um ADR em vigor». São duas causas
em **disjunção**, e **a primeira está cumprida**: esta governa quatro tickets —
KAM-043 (que a levantou), KAM-053 (que já escreveu três entradas debaixo dela),
KAM-044 e KAM-055 — em **dois subsistemas**, o Core de Comércio e os Pagamentos.
**Pelo que o critério aponta para cima**, e negar o segundo disjunto — esta não
contradiz o ADR-004, lê-o — não o desfaz. A primeira versão desta página concluía
«fica local por três razões», e essa conclusão era inválida na forma: fechava, à
mesa do executor, a pergunta que os dois precedentes desta casa deixam
explicitamente de fora dela (`ADR-L005` e `ADR-L006`, ambos com esta secção e a
mesma conclusão). Achado da revisão adversarial deste ticket.

Fica **local** pela razão que o `ADR-L005` escreve, e não por outra: **promovê-la é
uma alteração ao canon que ninguém pediu.** Um ADR canónico novo em
[`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) §8
toma o número seguinte ao último — hoje o **vigésimo**, que o fundador acrescentou
a 2026-10-09 e a Carta marca FIXA —, obriga a actualizar a contagem de ADRs e o
mapeamento ADR → documento em [`../tecnica/INDICE.md`](../tecnica/INDICE.md) §5, e
diria com um número novo o que o ADR-004 já diz. **O que falta para a promover está
nomeado aqui; quem a promove é quem o fundador mandar.**

**E há um gatilho que torna a pergunta inevitável.** No dia em que um ticket
precisar de uma entrada que **não** seja um preço de catálogo, o montante de uma
cobrança ou um facto de *ledger* — uma coluna cujo valor a plataforma **acumule** —,
a pergunta deixa de ser sobre o nome da coluna e passa a ser sobre o próprio
ADR-004. Essa é canónica, e não se decide num `ADR-L`.

(**Não se escreve aqui o número canónico que ela teria**, pela razão que o
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
`payment_charges` ao KAM-055; ela chegou com o **KAM-053**, na revisão `0029` —
**CONFIRMADO**: `db/migrations/versions/0029_ledger_de_pagamentos.py` cria-a, e
nenhuma revisão é atribuível ao KAM-055. O KAM-053 fundiu **no mesmo dia** desta
ratificação: `94bd634` (PR #104), `2026-11-03 09:25:39 +0100`.

**A ordem dentro do dia é INDÍCIO, e não se afirma como medida.** O *commit* tem
hora; esta decisão tem **data e não hora**, pelo que nada no registo a ordena
contra ele. O que se sabe sem a ordem é o que importa, e basta: o KAM-053 escreveu
as suas três entradas enquanto a pergunta estava **escrita como aberta** no
próprio `EM_UNIDADE_MENOR` — isso lê-se no ficheiro que ele fundiu —, e esta
decisão cobre-as. Se alguém quiser fechar a ordem, o que falta é a hora da
resposta do fundador, e o sítio é a secção «Decisão» desta página. As cinco
entradas da allowlist à data desta página são as duas do KAM-043 e as três do
KAM-053.

**O que a ratificação não fecha.** A caixa do DoD do KAM-003 continua **não
satisfeita**, e por uma razão que não é esta: o DDL aceita um tenant
`tipo = 'platform'` com `estado = 'ativo'`, que é a costura do ADR-011 e está
devolvida como decisão própria. O que esta página fecha é a metade dos saldos.

**O custo assumido.** Uma lista declarada é mais frágil do que uma proibição
total: depende de cada autor escrever a razão certa, e uma razão mal escrita passa
o *gate*. A decisão troca uma impossibilidade por uma declaração revista à mão — e
é por isso que a declaração é obrigatória nos dois sentidos, que o tipo é
afirmado, e que o lado rígido tem canário.

"""Encomendas: espelho, grafo de estados e registo de transicoes (KAM-044).

A primeira linha e **sem acentos**, como as vinte e nove revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria, e o que **nao** cria

Cria as **tres** tabelas de encomendas de `docs/tecnica/03` §5.4 que faltavam —
`platform.orders_mirror` (a autoridade do **ciclo de vida**), `order_intents`
(o recibo de idempotencia do §6.3), `order_state_log` (o registo *append-only*
das transicoes) —, mais duas que o §5.4 nao tem e que os criterios exigem: o
grafo `order_state_graph(de, para)` e o `order_reconciliation_issues` dos
*Detalhes Tecnicos* do bloco. Mais as tres funcoes e os tres *triggers* que
fazem das regras do §6.2 uma barreira da base e nao uma convencao de modulo.

**Nao** cria a `stock_reservations`, que esta no mesmo bloco SQL do §5.4 e e do
**KAM-045**; nao cria a FK de `payment_charges.order_id`, que e do **KAM-055**
(a `0029` deixou-a por escrito sem FK, a espera desta tabela); e nao escreve
fluxo nenhum — a `createOrder` e o recibo de intencao sao do **KAM-046**, o
consumo de `payment.*` e do **KAM-055**, e o pagamento tardio, a disputa, a
entrega falhada e o reembolso sao do **KAM-050**.

## Os estados sao **doze** e o `CHECK` do §5.4 tem nove

E a divergencia mais consequente desta revisao, e nao e escolha de gosto: esta
decidida desde a emenda 1.50 do dicionario e esta tabela e o primeiro sitio onde
a decisao se escreve em SQL.

O `CHECK` do §5.4 enumera nove (`criada`, `aguarda_pagamento`,
`pendente_confirmacao`, `paga`, `em_entrega`, `entregue`, `expirada`,
`cancelada`, `reembolso_pendente`). O §3.3 do dicionario fixa **doze** — os
nove mais `entrega_falhada`, `em_disputa` e `reembolsada` — e marca, na mesma
linha, a maquina de `docs/tecnica/03` §6.1 como «Maquina incompleta», com a
fonte em `docs/tecnica/00` §6.1. O `ORDER_STATES` de
`services/com/src/port/contrato.ts` (KAM-042) ja tem os doze, e escreve por que
razao: com nove, o KAM-050 nao podia chamar `transition(ctx, id, 'em_disputa',
…)` sem alterar o tipo da porta — isto e, a costura partia-se num ticket que
**nao** troca de Registo. Esse mesmo comentario nomeia esta revisao: «o `CHECK`
de `orders_mirror` nao existe ainda: a tabela e do **KAM-044**. Quando ele
nascer, e desta lista que sai.» Sai.

**O dominio da coluna e os doze; o grafo tem so o nucleo.** Sao duas coisas
diferentes e a distincao e o que torna o KAM-050 **aditivo**: ele acrescenta
*linhas* ao `order_state_graph`, que e dados, e nao um `ALTER TABLE ... DROP
CONSTRAINT` sobre um `CHECK` de uma tabela com encomendas vivas. Um dominio de
nove obrigava o KAM-050 a mexer no esquema; com doze, ele mexe numa tabela de
dados.

## O grafo e dados, e o *trigger* e que o impoe

O §6.2 acaba com a instrucao a letra: «a tabela e dados
(`order_state_graph(de, para)`) validados por *trigger* `BEFORE UPDATE` sobre
`estado`». As **doze** linhas do nucleo sao as do `NUCLEO` abaixo, e duas delas
levam `flag = 'COM_DELIVERY_ENABLED'`: o criterio 1 poe o `em_entrega` atras
dessa bandeira, desligada no Piloto, e o criterio do KAM-050 exige que
«activa-lo nao exija migracao». Por isso a bandeira **nao** e uma linha que se
insere ou apaga: e uma coluna lida em execucao de
`current_setting('app.com_delivery_enabled', true)`, e activar a entrega e uma
alteracao de configuracao da sessao ou do papel, sem DDL.

O `CHECK` da coluna `flag` fecha-a **no nome que o bloco escreve** e nao em
texto livre. Um nome de GUC vindo da linha deixava quem escreve no grafo
escolher que variavel a base consulta.

**O que o nucleo nao tem, e de quem e:** `expirada -> paga` (pagamento tardio),
`paga -> reembolso_pendente` e `entregue -> reembolso_pendente` (disputa), e
tudo o que passe por `entrega_falhada`, `em_disputa` ou `reembolsada`. Sao do
KAM-050, que o bloco nomeia tres vezes. O §6.1 de `docs/tecnica/03` chama as
duas primeiras «extensao proposta»; o §15 registou a lacuna.

## A FK do contacto e **composta**, e as de `orders_mirror` tambem

A correccao de 2026-10-27 do §5.4 (spike KAM-041, ISO-58) nomeia esta tabela
por extenso — «**A tabela de producao e do KAM-044**, que a cria a partir desta
seccao» — e estende a regra a toda a FK entre duas tabelas com `tenant_id`,
dando os tres exemplos: `stock_reservations -> orders_mirror`,
`order_state_log -> orders_mirror`, `price_quotes -> contacts`. O que a forma
simples permite esta **medido** e nao inferido: com `ctx` do tenant A e o
`contact_id` de B, a `createOrder` do spike criou uma encomenda de A a apontar
para um contacto de B — a FK e satisfeita pela chave primaria de `contacts`, que
nao inclui o tenant, e a politica `tenant_iso` olha para o `tenant_id` da linha
da encomenda, que e o do contexto e esta correcto.

Por isso a `orders_mirror` leva `orders_mirror_tenant_id_uq UNIQUE (tenant_id,
id)`, que nao serve consulta nenhuma: existe para que as tres tabelas que a
referenciam o possam fazer pelo par. E a mesma razao da
`tenant_channels_tenant_id_uq` da `0009` e da `contacts_tenant_contact_uq` da
`0003`.

**Uma FK composta com uma metade nula nao e imposta** (`MATCH SIMPLE`, que e a
omissao do PostgreSQL), e isso aplica-se a `order_intents.order_id` e ao
`order_reconciliation_issues.order_id`, os dois anulaveis. Com `order_id` nulo a
linha nao aponta para nada e nao ha nada a verificar; com `order_id` preenchido
o par e verificado inteiro. Fica dito porque a leitura ingenua e a oposta.

## `currency` e `text` com `CHECK`, e nao `char(3)`

O §5.4 escreve `char(3)`. O §3.4 do dicionario fecha o dominio em `{AOA}` e o
`canon_lint` do *gate* 3b le os valores de um `CHECK` contra o dominio fechado —
um `char(3)` sem `CHECK` aceita `'USD'` em silencio e **nao e lido por gate
nenhum**. A `0025` fixou a forma `text` + `CHECK` e a `0028` seguiu-a; esta
segue as duas. Divergencia da mesma classe que a emenda 1.52 registou.

## O `total_minor` e a *allowlist* do ADR-L008

A coluna entra em `EM_UNIDADE_MENOR` de `db/tests/test_catalogo.py` **na mesma
alteracao** que a cria, com a razao escrita pela qual nao e um saldo. Nao ha
outra ordem possivel: a asercao vale **nos dois sentidos** desde o KAM-172 — uma
coluna `*_minor` que a lista nao declare reprova, e uma entrada que a base nao
tenha e uma declaracao morta que reprova igual. `bigint` e nao `numeric`, pela
razao do §2 do dicionario.

## Tres *triggers*, e o terceiro e o que fecha a quinta via

O criterio 3 pede que `paga` so seja alcancavel «com `causa.evento_id` de evento
autenticado do PAY e actor `sistema`». Isso **nao e expressavel** numa coluna:
o actor e o evento nao vivem na `orders_mirror`, vivem na linha do
`order_state_log` que a transicao grava. Um `BEFORE UPDATE` corre antes de essa
linha existir.

A barreira e por isso um **`CONSTRAINT TRIGGER` diferido** —
`order_estado_exige_log` — que corre no `COMMIT` e exige, para **cada** mudanca
de estado, a linha de registo correspondente: mesmo `(tenant_id, order_id,
version)`, mesmo `de`, mesmo `para`. E quando o `para` e `paga`, exige mais: que
essa linha tenha `actor_kind = 'sistema'`, `evento_id` nao nulo e `causa` num dos
dois eventos autenticados do PAY. Isto da tres coisas que um `BEFORE UPDATE` nao
dava:

1. **«na mesma transaccao» passa a ser imposto e nao combinado.** Quem muda o
   estado e nao grava o registo **nao confirma**. O criterio 2 pede os dois na
   mesma transaccao; isto e o que o verifica.
2. **Fecha a quinta via.** Qualquer caminho que escreva `paga` — o modulo, um
   `UPDATE` a mao de quem tem privilegio, uma migracao futura — tem de deixar
   atras de si a linha de registo **e** o recibo de consumo do evento que ela
   cita. O DoD diz «nenhuma via leva a `paga` sem evento ou confirmacao manual
   auditada», e uma verificacao em TypeScript so cobre a via que passa pelo
   TypeScript.

   **O que esta barreira prova, exactamente:** que a transicao correu com actor
   `sistema`, com uma das duas causas autenticadas do §12, e que o `evento_id`
   que ela cita tem recibo de consumo em `platform.events_consumed` (KAM-006)
   **neste tenant**. O que ela **nao** prova e que esse evento foi autenticado
   pelo PAY: quem decide isso e o PAY (§10.1, «PAY decide; COM so aplica»), e a
   verificacao do `authn_ok` contra `platform.payment_events` exige a FK
   `payment_charges.order_id -> orders_mirror`, que e do **KAM-055** e nao
   existe. Ate la, o que o espelho exige e que o evento tenha entrado pela fila
   e sido consumido.

   A primeira versao desta revisao exigia so que o `evento_id` nao fosse vazio,
   e a revisao adversarial mostrou o que isso vale: como `kamba_app`, escreveu
   `paga` com `evento_id = 'inventado-pelo-app'` e com o outbox e o
   `payment_events` a zero.
3. **A idempotencia fica numa restricao.** A unicidade
   `(tenant_id, order_id, version)` do registo torna «a mesma transicao gravada
   duas vezes» um `23505` em vez de uma duplicacao silenciosa, que e a linha de
   idempotencia do DoD.

O `INSERT` tem *trigger* proprio, `order_nasce_criada`: o §6.2 tem uma unica
seta de entrada (`— -> criada`), e sem ele uma encomenda nascia `paga` por
`INSERT` directo, sem passar por transicao nenhuma — com o grafo, o registo e o
evento todos intactos e nenhum deles exercitado.

## O `order_state_log` leva uma coluna que o §5.4 nao tem

A `version`, e e ela que torna o *trigger* diferido **exacto**. Sem ela a unica
forma de ligar a linha do registo a transicao que a provocou era o par
`(de, para)` mais o instante, e o par repete-se: `expirada ->
aguarda_pagamento -> expirada` e um ciclo legitimo do nucleo, pelo que uma linha
de uma volta anterior satisfazia a verificacao de uma volta nova. Com a
`version` — a **de depois** da transicao, que e a que o CAS escreveu — cada
transicao tem uma linha e so uma.

Da tambem o `CHECK (version >= 2)`: uma encomenda nasce na versao 1 e a primeira
transicao leva-a a 2, pelo que um registo na versao 1 descreveria uma transicao
que nao houve.

Acrescentar coluna a um DDL que um criterio manda seguir e divergencia e nao
arrumacao, pelo que fica aqui e na emenda do dicionario, como as quatro que a
`0028` acrescentou.

## O `numero_publico` tem **oito** caracteres, e a razao e uma medicao

O criterio 5 pede base32 sem ambiguos, «≤ 8 caracteres, por exemplo `K7H3Q9`»,
unico por tenant, e «10.000 geracoes sem colisao no teste». O exemplo tem seis e
o tecto tem oito: entre os dois, a aritmetica decide.

O alfabeto e o de Crockford — os dez digitos e as vinte e duas letras que ficam
depois de sair `I`, `L`, `O` e `U` —, logo 32 simbolos. Com **seis**
caracteres ha 32^6 = 1 073 741 824 valores, e a probabilidade de colisao em
10 000 geracoes e 1 - exp(-49 995 000 / 32^6) ≈ **4,6%**: um ensaio que reprova
uma vez em vinte e duas sem haver defeito nenhum. Com **oito** ha 32^8 =
1 099 511 627 776, e a mesma conta da ≈ **4,5 x 10^-5**. Oito.

A entropia vem de `gen_random_uuid()` e nao de `random()`: o numero e tambem a
referencia curta que o PAY mostra ao cliente (§5.4, comentario da coluna), e um
gerador previsivel deixava adivinhar a referencia de outra encomenda. Os dez
primeiros digitos hexadecimais de um UUID v4 sao todos aleatorios — o digito da
versao e o decimo-terceiro e o da variante o decimo-setimo —, o que da os 40
bits que oito grupos de cinco consomem exactamente.

A unicidade por tenant e a do indice (`orders_mirror_numero_uq`); a funcao nao
tenta de novo em caso de colisao, e nao e esquecimento: quem insere e que sabe
se vale a pena repetir, e um laco de repeticao dentro da funcao escondia a
colisao de quem a devia medir.

## Privilegios: o `kamba_app` escreve a encomenda, insere o registo e nao apaga

O `kamba_app` tem `SELECT` e `INSERT` na `orders_mirror` e `UPDATE` **coluna a
coluna** (`UPDATE_DA_APP_EM_ENCOMENDAS`), pela razao que a `0028` escreveu e a
revisao adversarial dela ensinou: a chave, o `criado_at`, a `currency`, o
`contact_id`, a `origem`, o `intent_key` e o `numero_publico` **nao** se alteram.
Mudar o `numero_publico` de uma encomenda era mudar a referencia que o cliente
tem no telemovel; mudar o `contact_id` era transferir a encomenda para outra
pessoa.

O `lines_snapshot` e o `total_minor` **estao** na lista, e tem de estar: em
`criada` o §6.2 deixa a encomenda mudar (o KAM-046 resolve precos e linhas). O
que os congela depois de `aguarda_pagamento` nao e o privilegio — e o
*trigger*, que e uma barreira mais forte do que um `GRANT` partilhado pelos dois
caminhos.

No `order_state_log` o `kamba_app` tem **`SELECT` e `INSERT` e mais nada**, que
e o criterio 6 a letra. O `SELECT` esta la por duas razoes: quem reconcilia le o
historico, e — como a `0004` escreveu para o outbox — sem um papel sujeito a RLS
que leia a tabela, a politica nunca e exercida e a sua suite de isolamento mede
uma tabela que ninguem consulta. O `deny_mutation` da `0029` fecha o resto, e
fecha-o tambem ao dono e ao superutilizador, que e o que nenhum `REVOKE`
alcanca.

**O `deny_mutation` e da `0029` e esta revisao usa-o.** E a razao pela qual o
`down_revision` e `0029` e nao `0028`: o `downgrade` da `0029` apaga a funcao, e
apaga-a depois das tabelas que a usam — com esta revisao no meio, a ordem
`0030 -> 0029` continua a valer, porque os *triggers* desta caem com as tabelas
desta, antes de a funcao cair.

O `order_state_graph` e tabela de **referencia**, como a `evt_subscricoes` da
`0004`: nao tem `tenant_id`, nao entra no X-05 nem em
`ci/rls_exceptions.yaml` (a descoberta pergunta pela coluna, e ela nao a tem), e
o `kamba_app` tem nela `SELECT` e nada mais. Quem a escreve e o `kamba_migrator`,
numa revisao: as transicoes validas de um sistema nao sao configuracao de
tenant.

O `kamba_resolver`, o `kamba_identity`, o `kamba_audit`, o `kamba_agr` e o
`kamba_pay_hooks` **nao ganham nada**: resolvem canais, guardam o cofre de
contactos, leem a auditoria, guardam o estado das conversas e recebem webhooks.
Nenhum tem razao para chegar as encomendas de ninguem.

## O `downgrade` recusa-se a ser destrutivo

O §11 de `docs/tecnica/03` diz, por extenso, que a `orders_mirror` e o
`order_state_log` «nao tem `downgrade` destrutivo (so aditivo)», e os *Detalhes
Tecnicos* do bloco repetem-no. A revisao e aditiva — antes dela nao havia
encomendas —, mas o passo apaga tabelas que, com linhas dentro, sao o ciclo de
vida de encomendas reais e o rasto auditado de cada mudanca. **Uma perda dessas
nao pode ser silenciosa**, e por isso o `downgrade` segue a `0004`: com linhas
em qualquer das **quatro** tabelas de tenant (o grafo e referencia, e e a revisao que o semeia), so avanca se
`KAMBA_DOWNGRADE_0030_COPIA` apontar para um ficheiro novo, onde ficam todas as
linhas, uma por linha de JSON.

A copia corre **depois** de a RLS ser desligada: o dono esta sujeito ao `FORCE`
e sem contexto de tenant leria zero linhas — a copia saia vazia e o passo
apagava tudo com um ficheiro que parecia prova. E a licao da `0003` e da `0004`.

Tudo isto e SQL **proposto ate correr**: o *gate* 8 e o que o promove.
"""

from __future__ import annotations

import base64
import json
import os

from alembic import op

import rls

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
ENCOMENDAS = "platform.orders_mirror"
INTENCOES = "platform.order_intents"
REGISTO = "platform.order_state_log"
GRAFO = "platform.order_state_graph"
DIVERGENCIAS = "platform.order_reconciliation_issues"

#: As tabelas com `tenant_id` desta revisao, pela ordem em que se criam. Sao as
#: cinco menos o grafo, que e de referencia.
TABELAS_DE_TENANT = (
    "orders_mirror",
    "order_intents",
    "order_state_log",
    "order_reconciliation_issues",
)

#: As que o `downgrade` copia antes de apagar, pela ordem das FK.
TABELAS_COPIADAS = (
    "order_reconciliation_issues",
    "order_state_log",
    "order_intents",
    "orders_mirror",
)

#: Os **doze** estados de uma encomenda, pela ordem do dicionario §3.3 (fonte:
#: `docs/tecnica/00` §6.1). Ver a nota do modulo para a razao de serem doze e
#: nao os nove do `CHECK` do §5.4. Ja entre apostrofos, pela razao da `0015`: e
#: a unica forma que o *gate* 3b resolve, porque segue
#: `", ".join(<constante de modulo>)` dentro de uma f-string.
ESTADOS = (
    "'criada'",
    "'aguarda_pagamento'",
    "'pendente_confirmacao'",
    "'paga'",
    "'expirada'",
    "'em_entrega'",
    "'entrega_falhada'",
    "'entregue'",
    "'em_disputa'",
    "'reembolso_pendente'",
    "'reembolsada'",
    "'cancelada'",
)

#: O estado em que uma encomenda nasce, e o unico em que o `lines_snapshot`
#: ainda se pode alterar (criterio 4).
CRIADA = "'criada'"

#: O estado que o criterio 3 fecha a evento autenticado.
PAGA = "'paga'"

#: As **doze** transicoes do nucleo de `docs/tecnica/03` §6.2, uma por linha,
#: com a bandeira de cada uma. Texto de `VALUES` e nao tuplas de Python: o
#: *gate* 3b segue `", ".join(<constante de modulo>)` e nao uma compreensao.
#:
#: O que **nao** esta aqui e do KAM-050 — `expirada -> paga` (pagamento tardio),
#: `paga -> reembolso_pendente` e `entregue -> reembolso_pendente` (disputa) — e
#: tudo o que passe por `entrega_falhada`, `em_disputa` ou `reembolsada`.
NUCLEO = (
    "('criada', 'aguarda_pagamento', NULL)",
    "('criada', 'cancelada', NULL)",
    "('aguarda_pagamento', 'paga', NULL)",
    "('aguarda_pagamento', 'pendente_confirmacao', NULL)",
    "('aguarda_pagamento', 'expirada', NULL)",
    "('pendente_confirmacao', 'paga', NULL)",
    "('pendente_confirmacao', 'aguarda_pagamento', NULL)",
    "('expirada', 'aguarda_pagamento', NULL)",
    "('expirada', 'cancelada', NULL)",
    "('paga', 'entregue', NULL)",
    "('paga', 'em_entrega', 'COM_DELIVERY_ENABLED')",
    "('em_entrega', 'entregue', 'COM_DELIVERY_ENABLED')",
)

#: A unica bandeira do grafo, e o nome e o que o criterio 1 escreve. `CHECK`
#: fechado e nao texto livre: um nome vindo da linha deixava quem escreve no
#: grafo escolher que GUC a base consulta.
BANDEIRAS = ("'COM_DELIVERY_ENABLED'",)

#: A variavel de sessao que liga a entrega. Desligada no Piloto; activa-la nao
#: exige migracao (criterio do KAM-050).
GUC_DA_ENTREGA = "app.com_delivery_enabled"

#: As duas origens de uma encomenda (§5.4). `plataforma` e Diferido (ADR-011).
ORIGENS = ("'pme'", "'plataforma'")

#: Os cinco subestados da confirmacao do dono (§5.4). O fluxo e do KAM-046.
CONFIRMACOES = (
    "'nao_aplicavel'",
    "'pendente'",
    "'confirmada'",
    "'recusada'",
    "'expirada'",
)

#: `currency` ∈ {`AOA`} (dicionario §3.4, emenda 1.13). Dominio de um valor: a
#: plataforma e de Angola, e alarga-lo e emenda e nao `ALTER`.
MOEDAS = ("'AOA'",)

#: Os dois modos de entrega (§5.4). O `entrega` fica atras da bandeira.
MODOS_DE_ENTREGA = ("'levantamento'", "'entrega'")

#: As tres vias de pagamento do dominio do §5.4.
VIAS_DE_PAGAMENTO = ("'provider_autenticado'", "'manual_auditado'", "'cod_manual'")

#: As **duas** vias que levam a `paga`, e e o criterio 3 a letra
#: (`paga_via ∈ {provider_autenticado, manual_auditado}`).
#:
#: O `cod_manual` fica no dominio da coluna, porque o §5.4 o tem, e **nao** no
#: `CHECK` do estado: nenhuma transicao do nucleo o escreve, e o fluxo de
#: dinheiro a cobranca (COD) e de quem o implementar. Quem o quiser alcancavel
#: alarga este `CHECK` com a razao escrita, que e o que esta linha existe para
#: obrigar.
VIAS_QUE_PAGAM = ("'provider_autenticado'", "'manual_auditado'")

#: As tres excepcoes do §5.4. Quem as escreve e o KAM-050.
EXCEPCOES = (
    "'pagamento_tardio_sem_stock'",
    "'pagamento_duplicado'",
    "'valor_divergente'",
)

#: Quem pode confirmar uma entrega (§5.4).
CONFIRMA_ENTREGA = ("'cliente'", "'dono'", "'estafeta'")

#: Os quatro `actor.kind` do dicionario §3.2 (emenda 1.50). Um `kind` fora dos
#: quatro **falha fechado**: aceita-lo deixava o `actor_kind` com um valor que
#: nenhuma consulta de auditoria sabe interpretar.
ACTOR_KINDS = ("'agente'", "'dono'", "'sistema'", "'ops'")

#: As duas causas que o criterio 3 aceita para `paga`. Sao os **dois eventos
#: distintos** do §12: o do facilitador autenticado e o do `ManualProvider`.
CAUSAS_QUE_PAGAM = ("'payment.confirmed'", "'payment.manual_confirmed'")

#: Os tres estados de um recibo de intencao (§5.4). O fluxo e do KAM-046.
ESTADOS_DA_INTENCAO = ("'em_curso'", "'concluida'", "'falhada'")

#: Os **cinco** tipos de divergencia do §10.3, um por regra e pela ordem em que
#: aquele paragrafo as escreve.
TIPOS_DE_DIVERGENCIA = (
    "'orfao_no_registo'",
    "'espelho_sem_encomenda'",
    "'divergencia_de_linhas'",
    "'reserva_sem_encomenda'",
    "'estado_divergente'",
)

#: Os dois estados de uma divergencia. A metrica do bloco e «divergencias
#: abertas > 5 min = 0», logo o que conta e a passagem de `aberta` a
#: `resolvida`.
ESTADOS_DA_DIVERGENCIA = ("'aberta'", "'resolvida'")

#: O alfabeto base32 de Crockford: os dez digitos e as vinte e duas letras que
#: ficam depois de sair `I`, `L`, `O` e `U`. E o «base32 sem ambiguos» do
#: criterio 5 — o `0` deixa de se confundir com o `O` por o `O` nao existir.
ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: A classe de caracteres do `CHECK`, escrita por intervalos: `A-H`, `J`, `K`,
#: `M`, `N`, `P-T` e `V-Z` sao as vinte e duas letras do alfabeto acima.
CLASSE_DO_NUMERO = "[0-9A-HJKMNP-TV-Z]"

#: Quantos caracteres a funcao gera. **Oito e nao seis**, e a razao e a medicao
#: que esta na nota do modulo: com seis, 10 000 geracoes colidem com
#: probabilidade 4,6%.
DIGITOS_DO_NUMERO = 8

#: O indice do ultimo digito, para o laco. **Constante propria e nao
#: `DIGITOS_DO_NUMERO - 1` dentro da f-string**: o *gate* 3b resolve uma
#: f-string sobre constantes de modulo e **nao** sobre uma expressao, e a
#: subtraccao punha a funcao inteira como `[ilegivel]` — medido na primeira
#: passagem do `canon_lint` deste ticket.
ULTIMO_DIGITO = 7

#: Os SQLSTATE proprios desta revisao. Os dois primeiros digitos `KA` seguem a
#: `0007`, que ja tem `KA001` (chave de idempotencia em falta) e `KA002` (a
#: mesma chave com outra quantidade). Codigos proprios e nao `check_violation`
#: para todos: a porta `CommerceRegistry` traduz cada recusa para um erro
#: diferente, e com um codigo unico nao ha como as distinguir sem ler texto.
SQLSTATE_TRANSICAO = "KA003"
SQLSTATE_SNAPSHOT = "KA004"
SQLSTATE_REGISTO = "KA005"
SQLSTATE_AUTENTICIDADE = "KA006"
SQLSTATE_TECTO_MANUAL = "KA007"

#: A chave de entitlement que o §6.2 nomeia como guarda do
#: `pendente_confirmacao` («`total_minor <= limite_manual` do tenant»; o §5.2
#: escreve-a `manual_max_minor` no exemplo do registo).
#:
#: **Le-se por `platform.ten_tecto`, da revisao `0007`, e nao de um caminho
#: novo.** E a funcao que o `checkCeiling` do `packages/core-ts/src/ten` chama,
#: e o que ela devolve e o **minimo** entre os modulos activos que declaram a
#: chave — `NULL` quando ninguem a declara. O `COALESCE(-1)` do *trigger* e que
#: faz desse `NULL` uma recusa: «sem tecto» nao quer dizer «sem limite», que e a
#: falha fechada do criterio 2 do KAM-009.
CHAVE_DO_TECTO_MANUAL = "manual_max_minor"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"

#: O que o `kamba_app` pode alterar numa encomenda, coluna a coluna.
#:
#: **Nao e `UPDATE` de tabela inteira**, pela razao que a revisao adversarial da
#: `0028` ensinou. Ficam de fora o `id`, o `tenant_id`, o `contact_id`, a
#: `origem`, o `numero_publico`, o `intent_key`, a `currency` e o `criado_at`:
#: mudar o `numero_publico` era mudar a referencia que o cliente tem no
#: telemovel, e mudar o `contact_id` era passar a encomenda para outra pessoa.
#:
#: O `lines_snapshot` e o `total_minor` **estao** aqui porque em `criada` a
#: encomenda ainda muda (KAM-046); o que os congela depois e o *trigger*.
UPDATE_DA_APP_EM_ENCOMENDAS = (
    "estado",
    "confirmacao_dono",
    "total_minor",
    "lines_snapshot",
    "entrega_modo",
    "medusa_order_id",
    "expira_at",
    "paga_at",
    "paga_via",
    "excepcao",
    "entregue_at",
    "entrega_confirmada_por",
    "version",
    "atualizado_at",
    "deleted_at",
)

#: O que o `kamba_app` pode alterar num recibo de intencao: o `estado` e o
#: `order_id`, que e o fecho do recibo quando a encomenda nasce (§6.3). A chave
#: e o `draft_hash` nao — reescrever o *hash* do rascunho era mudar aquilo de
#: que a idempotencia e recibo.
UPDATE_DA_APP_EM_INTENCOES = ("estado", "order_id")

#: O que o `kamba_app` pode alterar numa divergencia: fecha-la. Abrir e
#: `INSERT`; o `tipo`, o `detalhe` e o `order_id` de uma divergencia aberta sao
#: o que ela e.
UPDATE_DA_APP_EM_DIVERGENCIAS = ("estado", "resolvida_at")

#: A variavel que autoriza a perda no `downgrade`. Ver a nota do modulo.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0030_COPIA"


def upgrade() -> None:
    # O gerador do numero vem **antes** da tabela: e `DEFAULT` da coluna, e uma
    # coluna nao pode ter por omissao uma funcao que ainda nao existe.
    _funcao_do_numero()
    _orders_mirror()
    _order_intents()
    _order_state_log()
    _order_state_graph()
    _order_reconciliation_issues()
    _funcoes()
    _triggers()
    _rls()
    _privilegios()


def _orders_mirror() -> None:
    """A autoridade do ciclo de vida da encomenda (§10.1)."""
    op.execute(
        f"""
        CREATE TABLE {ENCOMENDAS} (
            id                     uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id              uuid        NOT NULL,
            -- **Sem `msisdn`, e e o ADR-010 mais a minimizacao da Lei 22/11.**
            -- O §5.1 n.o 3 registou que o `orders_mirror.cliente_msisdn text
            -- NOT NULL` do documento 11 viola as duas. O telefone, quando
            -- existe, vive cifrado em `contact_endpoints` (revisao `0003`).
            contact_id             uuid        NOT NULL,
            origem                 text        NOT NULL DEFAULT 'pme',
            -- Base32 de Crockford, oito caracteres. Serve tambem de referencia
            -- curta no PAY (§5.4), e e por isso que a entropia vem de
            -- `gen_random_uuid()` e nao de `random()`.
            --
            -- **`DEFAULT` e nao argumento de quem insere**, e a diferenca e uma
            -- via: com a funcao por omissao, **todo** o caminho de insercao
            -- recebe um numero valido — o modulo, o repo-base (que constroi o
            -- `INSERT` e nao aceita expressoes) e um `INSERT` a mao. Passado
            -- pelo chamador, cada caminho novo tinha de se lembrar dele, e o
            -- `CHECK` do formato so apanhava quem se lembrasse errado.
            numero_publico         text        NOT NULL
                                   DEFAULT platform.order_numero_publico(),
            -- A chave de idempotencia da criacao (§6.3). Quem a escreve e o
            -- KAM-046; aqui ela e so unica por tenant.
            intent_key             text        NOT NULL,
            -- O id no Registo. Nulo enquanto o Registo nao o atribuir, que e o
            -- estado de toda a Fase 0 — e a FK e **logica** (texto), nunca de
            -- base de dados, pelo §5.1 n.o 7.
            medusa_order_id        text,
            -- Os **doze** do dicionario §3.3, e nao os nove do `CHECK` do
            -- §5.4. Ver a nota do modulo: o dominio e doze para que o KAM-050
            -- acrescente linhas ao grafo em vez de alterar este `CHECK`.
            estado                 text        NOT NULL DEFAULT 'criada',
            confirmacao_dono       text        NOT NULL DEFAULT 'nao_aplicavel',
            -- Unidade menor inteira, 1 Kz = 100 centimos (§5.1 n.o 2;
            -- dicionario §2). Declarada em `EM_UNIDADE_MENOR` com a razao pela
            -- qual nao e um saldo (ADR-L008).
            total_minor            bigint      NOT NULL,
            currency               text        NOT NULL DEFAULT 'AOA',
            -- As linhas no instante da encomenda, copiadas do Registo (§10.1).
            -- **Imutavel depois de `aguarda_pagamento`**, pelo *trigger*. A
            -- forma e `[{{sku, nome, qty, preco_minor, preco_tipo,
            -- origem_preco}}]`; quem a escreve e o KAM-046.
            lines_snapshot         jsonb       NOT NULL,
            entrega_modo           text        NOT NULL DEFAULT 'levantamento',
            -- Fim da reserva activa. O `order.expired` leva-o no payload, pelo
            -- que expirar sem ele seria emitir um evento que o contrato recusa.
            expira_at              timestamptz,
            paga_at                timestamptz,
            paga_via               text,
            excepcao               text,
            entregue_at            timestamptz,
            entrega_confirmada_por text,
            -- Concorrencia optimista. O CAS do §6.2 compara-a e o *trigger*
            -- exige que suba de um em cada mudanca de estado.
            version                integer     NOT NULL DEFAULT 1,
            criado_at              timestamptz NOT NULL DEFAULT now(),
            -- Escrito pelo modulo em cada `UPDATE`, nao por *trigger* — a
            -- mesma escolha da `0028`, e a `orders_mirror` do §5.4 e o
            -- precedente que ela citou.
            atualizado_at          timestamptz NOT NULL DEFAULT now(),
            -- Soft delete do §5.6: nenhuma encomenda se apaga fisicamente. A
            -- purga e da retencao (KAM-071).
            deleted_at             timestamptz,
            CONSTRAINT orders_mirror_pkey PRIMARY KEY (id),
            -- Nao serve consulta nenhuma: existe para que as tres tabelas que
            -- referenciam esta o possam fazer pelo par `(tenant_id, id)`. Ver
            -- a nota do modulo e a `tenant_channels_tenant_id_uq` da `0009`.
            CONSTRAINT orders_mirror_tenant_id_uq UNIQUE (tenant_id, id),
            CONSTRAINT orders_mirror_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta, e o bloco SQL do §5.4 escrevia-a simples.** A
            -- correccao de 2026-10-27 nomeia esta tabela: o ISO-58 do spike
            -- KAM-041 mediu uma encomenda de A a apontar para um contacto de B.
            CONSTRAINT orders_mirror_contacto_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            CONSTRAINT orders_mirror_origem_ck
                CHECK (origem IN ({", ".join(ORIGENS)})),
            CONSTRAINT orders_mirror_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS)})),
            CONSTRAINT orders_mirror_confirmacao_ck
                CHECK (confirmacao_dono IN ({", ".join(CONFIRMACOES)})),
            CONSTRAINT orders_mirror_total_ck CHECK (total_minor >= 0),
            CONSTRAINT orders_mirror_currency_ck
                CHECK (currency IN ({", ".join(MOEDAS)})),
            -- Um objecto nao e uma lista de linhas, e um `lines_snapshot` que
            -- nao seja uma lista rebentava em quem o projecta para o payload do
            -- `order.created`.
            CONSTRAINT orders_mirror_snapshot_ck
                CHECK (jsonb_typeof(lines_snapshot) = 'array'),
            CONSTRAINT orders_mirror_entrega_modo_ck
                CHECK (entrega_modo IN ({", ".join(MODOS_DE_ENTREGA)})),
            -- **Sem `IS NULL OR`, e a coluna continua anulavel.** Um
            -- `CHECK` passa quando a expressao e verdadeira **ou nula**, e
            -- `NULL IN (...)` e nulo: a guarda explicita era redundante, e o
            -- *gate* 3b nao a le como dominio fechado (medido: quatro achados
            -- `[regra]` «sem CHECK fechado» na primeira passagem).
            CONSTRAINT orders_mirror_paga_via_ck
                CHECK (paga_via IN ({", ".join(VIAS_DE_PAGAMENTO)})),
            -- **O criterio 3 na coluna, e nao so na funcao.** `paga` exige
            -- instante e via, e a via tem de ser uma das duas autenticadas. O
            -- actor e o evento nao caberiam aqui, e e por isso que existe o
            -- *trigger* diferido.
            CONSTRAINT orders_mirror_paga_exige_via_ck
                CHECK (estado <> {PAGA}
                       OR (paga_at IS NOT NULL
                           AND paga_via IN ({", ".join(VIAS_QUE_PAGAM)}))),
            CONSTRAINT orders_mirror_excepcao_ck
                CHECK (excepcao IN ({", ".join(EXCEPCOES)})),
            CONSTRAINT orders_mirror_entrega_confirmada_ck
                CHECK (entrega_confirmada_por
                       IN ({", ".join(CONFIRMA_ENTREGA)})),
            -- Entregue sem quem confirmou era uma entrega que ninguem assume, e
            -- o payload do `order.delivered` exige o campo.
            CONSTRAINT orders_mirror_entregue_exige_quem_ck
                CHECK (estado <> 'entregue'
                       OR (entregue_at IS NOT NULL
                           AND entrega_confirmada_por IS NOT NULL)),
            CONSTRAINT orders_mirror_version_ck CHECK (version >= 1),
            CONSTRAINT orders_mirror_numero_ck
                CHECK (numero_publico ~ '^{CLASSE_DO_NUMERO}{{1,8}}$'),
            CONSTRAINT orders_mirror_intent_key_ck CHECK (btrim(intent_key) <> ''),
            CONSTRAINT orders_mirror_intent_uq UNIQUE (tenant_id, intent_key),
            CONSTRAINT orders_mirror_numero_uq UNIQUE (tenant_id, numero_publico)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {ENCOMENDAS} IS "
        "'Espelho de pedidos e autoridade do ciclo de vida da encomenda "
        "(KAM-044). O Registo e autoridade das linhas e do stock; o estado muda "
        "so por transicao auditada (docs/tecnica/03 secao 10.1 e secao 6.2). Sem "
        "msisdn: aponta para contacts (ADR-010). Dicionario 3.41.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {ENCOMENDAS}.numero_publico IS "
        "'Base32 de Crockford, oito caracteres, unico por tenant. Serve tambem "
        "de referencia curta no PAY, e por isso a entropia e de "
        "gen_random_uuid() e nao de random().'"
    )
    # As listagens da encomenda filtram sempre por tenant e por estado, e
    # ordenam pela data: e a consulta do `listOrders` da porta.
    op.execute(
        f"CREATE INDEX orders_mirror_estado_idx ON {ENCOMENDAS} "
        "(tenant_id, estado, criado_at DESC)"
    )
    # O varrimento da expiracao (KAM-045) procura por instante e nao por tenant:
    # corre por toda a base, como *job*. Parcial nos dois estados que expiram.
    op.execute(
        f"CREATE INDEX orders_mirror_expira_idx ON {ENCOMENDAS} (expira_at) "
        "WHERE estado IN ('aguarda_pagamento', 'pendente_confirmacao')"
    )


def _order_intents() -> None:
    """O recibo de idempotencia da criacao de pedido (§6.3)."""
    op.execute(
        f"""
        CREATE TABLE {INTENCOES} (
            tenant_id  uuid        NOT NULL,
            intent_key text        NOT NULL,
            -- O *hash* do rascunho confirmado. **32 octetos**, que e sha256:
            -- a mesma forma do `payload_hash` da `audit_log` (`0006`), e fixar
            -- o tamanho impede que dois tickets usem dois *hashes* diferentes
            -- para a mesma pergunta («e o mesmo rascunho?»).
            draft_hash bytea       NOT NULL,
            estado     text        NOT NULL DEFAULT 'em_curso',
            -- Anulavel enquanto a encomenda nao existe, que e o estado
            -- `em_curso`. A FK composta com uma metade nula **nao e imposta**
            -- (`MATCH SIMPLE`): com `order_id` nulo nao ha par para verificar.
            order_id   uuid,
            criado_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT order_intents_pkey PRIMARY KEY (tenant_id, intent_key),
            CONSTRAINT order_intents_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT order_intents_encomenda_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, order_id)
                REFERENCES platform.orders_mirror (tenant_id, id),
            CONSTRAINT order_intents_intent_key_ck CHECK (btrim(intent_key) <> ''),
            CONSTRAINT order_intents_draft_hash_ck
                CHECK (octet_length(draft_hash) = 32),
            CONSTRAINT order_intents_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_INTENCAO)})),
            -- Um recibo concluido sem encomenda nao e recibo de nada, e uma
            -- encomenda num recibo `em_curso` dizia que a saga nao acabou com a
            -- prova de que acabou. Nos dois sentidos, como o
            -- `offer_terms_preco_ck` da `0028`.
            CONSTRAINT order_intents_concluida_exige_encomenda_ck
                CHECK ((estado = 'concluida') = (order_id IS NOT NULL))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {INTENCOES} IS "
        "'Recibo de idempotencia da criacao de pedido (docs/tecnica/03 secao "
        "6.3). A chave e (tenant_id, intent_key); o fluxo que o escreve e o "
        "KAM-046. Dicionario 3.41.'"
    )


def _order_state_log() -> None:
    """O registo *append-only* das transicoes (§5.4, §5.6)."""
    op.execute(
        f"""
        CREATE TABLE {REGISTO} (
            -- **`uuid` e nao `bigint GENERATED ALWAYS AS IDENTITY`, que e o que
            -- o §5.4 escreve.** A divergencia e obrigatoria e a razao e medivel:
            -- o dicionario §2 manda chaves `uuid` porque uma chave sequencial
            -- vaza volume (quantas encomendas tem o vizinho), e as excepcoes
            -- que o `test_as_colunas_de_identidade_sao_as_declaradas` aceita
            -- tem **todas** a mesma propriedade — «nenhum papel sujeito a RLS
            -- le a coluna». Aqui essa propriedade **nao se verifica**: o
            -- `kamba_app` tem de ter `SELECT` nesta tabela, porque e o
            -- *trigger* diferido `order_estado_exige_log` que a le, e ele corre
            -- como quem escreveu a encomenda (`SECURITY INVOKER`; uma
            -- `SECURITY DEFINER` lia zero linhas sob `FORCE`, ver `db/rls.py`).
            -- Com `bigint` de identidade, o papel que atende um cliente media,
            -- pela diferenca entre dois ids, quantas transicoes de encomenda a
            -- plataforma inteira tem.
            --
            -- O que a identidade dava e que nao se perde: a ordem. A ordem que
            -- a auditoria desta tabela le e `(order_id, version)`, que e por
            -- transicao e nao por instante de insercao — ao contrario da
            -- `audit_log`, onde a cadeia de *hash* se verifica pela ordem de
            -- escrita e por isso a identidade e que serve.
            id         uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id  uuid        NOT NULL,
            order_id   uuid        NOT NULL,
            de         text        NOT NULL,
            para       text        NOT NULL,
            -- A `version` **depois** da transicao, que e a que o CAS escreveu.
            -- Coluna que o §5.4 nao tem: e ela que liga esta linha a transicao
            -- exacta que a provocou, e sem ela o ciclo legitimo
            -- `expirada -> aguarda_pagamento -> expirada` deixava a linha de
            -- uma volta anterior satisfazer a verificacao de uma volta nova.
            version    integer     NOT NULL,
            -- `payment.confirmed`, `payment.manual_confirmed`, `ttl`,
            -- `dono_confirma`, `cliente_cancela`, `reconciliacao`, ... Texto
            -- livre de proposito: o §5.4 da exemplos e nao um dominio, e fechar
            -- aqui uma lista que nenhum documento fecha travava o KAM-050.
            causa      text        NOT NULL,
            -- O `id` do evento que causou a transicao. **Obrigatorio para
            -- `paga`**, pelo *trigger* diferido: e a prova do criterio 3.
            evento_id  text,
            actor_kind text        NOT NULL,
            actor_id   text,
            em         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT order_state_log_pkey PRIMARY KEY (id),
            CONSTRAINT order_state_log_encomenda_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, order_id)
                REFERENCES platform.orders_mirror (tenant_id, id),
            CONSTRAINT order_state_log_de_ck CHECK (de IN ({", ".join(ESTADOS)})),
            CONSTRAINT order_state_log_para_ck
                CHECK (para IN ({", ".join(ESTADOS)})),
            CONSTRAINT order_state_log_sem_laco_ck CHECK (de <> para),
            -- Uma encomenda nasce na versao 1 e a primeira transicao leva-a a
            -- 2: um registo na versao 1 descrevia uma transicao que nao houve.
            CONSTRAINT order_state_log_version_ck CHECK (version >= 2),
            CONSTRAINT order_state_log_causa_ck CHECK (btrim(causa) <> ''),
            CONSTRAINT order_state_log_actor_kind_ck
                CHECK (actor_kind IN ({", ".join(ACTOR_KINDS)})),
            -- **A idempotencia do DoD, numa restricao.** A mesma transicao
            -- gravada duas vezes e um `23505` e nao uma duplicacao silenciosa.
            CONSTRAINT order_state_log_version_uq
                UNIQUE (tenant_id, order_id, version)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {REGISTO} IS "
        "'Registo append-only das transicoes de estado da encomenda "
        "(docs/tecnica/03 secao 5.4 e secao 5.6). So INSERT para kamba_app; o "
        "deny_mutation da 0029 recusa UPDATE, DELETE e TRUNCATE a todos. A "
        "version e a de depois da transicao. Dicionario 3.41.'"
    )
    # A consulta do historico e por encomenda e por ordem de versao; a unicidade
    # `(tenant_id, order_id, version)` ja da o indice que ela e a RLS precisam, e
    # comeca pelo `tenant_id`, que e o que o X-05 exige.


def _order_state_graph() -> None:
    """O grafo de transicoes, como **dados** (§6.2)."""
    op.execute(
        f"""
        CREATE TABLE {GRAFO} (
            de   text NOT NULL,
            para text NOT NULL,
            -- Nula quando a transicao esta sempre activa. O nome e fechado por
            -- `CHECK`: um GUC vindo da linha deixava quem escreve no grafo
            -- escolher que variavel a base consulta.
            flag text,
            CONSTRAINT order_state_graph_pkey PRIMARY KEY (de, para),
            CONSTRAINT order_state_graph_de_ck CHECK (de IN ({", ".join(ESTADOS)})),
            CONSTRAINT order_state_graph_para_ck
                CHECK (para IN ({", ".join(ESTADOS)})),
            CONSTRAINT order_state_graph_sem_laco_ck CHECK (de <> para),
            -- Anulavel sem `IS NULL OR`, pela razao escrita na
            -- `orders_mirror_paga_via_ck`.
            CONSTRAINT order_state_graph_flag_ck
                CHECK (flag IN ({", ".join(BANDEIRAS)}))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {GRAFO} IS "
        "'As transicoes validas da encomenda, como dados (docs/tecnica/03 secao "
        "6.2). Tabela de referencia, sem tenant_id: as transicoes validas de um "
        "sistema nao sao configuracao de tenant. O nucleo e do KAM-044; o "
        "pagamento tardio, a disputa e o reembolso sao do KAM-050. Dicionario 3.41.'"
    )
    op.execute(
        f"""
        INSERT INTO {GRAFO} (de, para, flag)
        VALUES {", ".join(NUCLEO)}
        """
    )


def _order_reconciliation_issues() -> None:
    """As divergencias Registo <-> espelho (§10.3 e *Detalhes Tecnicos*)."""
    op.execute(
        f"""
        CREATE TABLE {DIVERGENCIAS} (
            id           uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id    uuid        NOT NULL,
            -- Anulavel, e as regras dizem porque: a regra 1 encontra uma
            -- encomenda no Registo que **nao tem** linha no espelho, e a regra
            -- 4 uma reserva sem encomenda. A FK composta com uma metade nula
            -- nao e imposta (`MATCH SIMPLE`).
            order_id     uuid,
            tipo         text        NOT NULL,
            -- O que divergia, para quem reconcilia ler sem reabrir o Registo.
            -- **Sem PII**: o que entra aqui sao `intent_key`, `sku`, totais e
            -- estados, e e o `test_inventario` que responde coluna a coluna.
            detalhe      jsonb       NOT NULL DEFAULT '{{}}',
            estado       text        NOT NULL DEFAULT 'aberta',
            aberta_at    timestamptz NOT NULL DEFAULT now(),
            resolvida_at timestamptz,
            CONSTRAINT order_reconciliation_issues_pkey PRIMARY KEY (id),
            CONSTRAINT order_reconciliation_issues_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT order_reconciliation_issues_encomenda_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, order_id)
                REFERENCES platform.orders_mirror (tenant_id, id),
            CONSTRAINT order_reconciliation_issues_tipo_ck
                CHECK (tipo IN ({", ".join(TIPOS_DE_DIVERGENCIA)})),
            CONSTRAINT order_reconciliation_issues_detalhe_ck
                CHECK (jsonb_typeof(detalhe) = 'object'),
            CONSTRAINT order_reconciliation_issues_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_DIVERGENCIA)})),
            -- Nos dois sentidos: uma divergencia resolvida sem instante nao se
            -- consegue medir contra os 5 min da metrica, e um instante numa
            -- divergencia aberta dizia que ela fechou.
            CONSTRAINT order_reconciliation_issues_resolvida_ck
                CHECK ((estado = 'resolvida') = (resolvida_at IS NOT NULL))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {DIVERGENCIAS} IS "
        "'Divergencias Registo <-> espelho (docs/tecnica/03 secao 10.3, cinco "
        "regras). A metrica e divergencias abertas > 5 min = 0; as correccoes "
        "ficam em order_state_log com causa = reconciliacao. Dicionario 3.41.'"
    )
    # A metrica le as abertas por tenant, pela data de abertura: e a consulta do
    # *job*, e comeca pelo `tenant_id`, que e o que o X-05 exige.
    op.execute(
        f"CREATE INDEX order_reconciliation_issues_abertas_idx ON {DIVERGENCIAS} "
        "(tenant_id, estado, aberta_at)"
    )


def _funcao_do_numero() -> None:
    """O gerador do `numero_publico`, que e `DEFAULT` da coluna."""
    # --------------------------------------------------- order_numero_publico
    #
    # Oito caracteres do alfabeto de Crockford a partir dos 40 bits aleatorios
    # dos dez primeiros digitos hexadecimais de um UUID v4. Ver a nota do modulo
    # para a razao de serem oito e nao seis, e de a entropia nao vir de
    # `random()`.
    #
    # `VOLATILE` por extenso e nao por omissao: a funcao devolve valor diferente
    # a cada chamada, e um planificador que a tomasse por `STABLE` podia
    # avalia-la uma vez por instrucao — o que num `INSERT ... SELECT` de varias
    # linhas dava o mesmo numero a todas.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_numero_publico() RETURNS text
        LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
          v_bits  bigint;
          v_saida text := '';
          v_i     integer;
        BEGIN
          v_bits := ('x' || substr(translate(gen_random_uuid()::text, '-', ''),
                                   1, 10))::bit(40)::bigint;
          FOR v_i IN 0..{ULTIMO_DIGITO} LOOP
            v_saida := substr('{ALFABETO}',
                              1 + ((v_bits >> (5 * v_i)) & 31)::integer, 1)
                       || v_saida;
          END LOOP;
          RETURN v_saida;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_numero_publico() IS "
        "'Gera um numero publico de oito caracteres em base32 de Crockford "
        "(criterio 5 do KAM-044). Nao repete em caso de colisao: quem insere e "
        "que sabe se vale a pena, e a unicidade e do indice por tenant.'"
    )


def _funcoes() -> None:
    """Os corpos dos tres *triggers* da encomenda."""
    # ----------------------------------------------------- order_nasce_criada
    #
    # A unica seta de entrada do §6.2 e `— -> criada`. Sem este *trigger* uma
    # encomenda nascia `paga` por `INSERT` directo, sem passar por transicao
    # nenhuma — com o grafo, o registo e o *trigger* diferido todos intactos e
    # nenhum deles exercitado. E a quinta via do KAM-053, nesta tabela.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_nasce_criada() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.estado <> {CRIADA} THEN
            RAISE EXCEPTION
              'orders_mirror: uma encomenda nasce em criada e veio em %, '
              'e o unico caminho para outro estado e a transicao (KAM-044, '
              'docs/tecnica/03 secao 6.2)', NEW.estado
              USING ERRCODE = '{SQLSTATE_TRANSICAO}';
          END IF;
          IF NEW.version <> 1 THEN
            RAISE EXCEPTION
              'orders_mirror: uma encomenda nasce na versao 1 e veio na %',
              NEW.version
              USING ERRCODE = '{SQLSTATE_TRANSICAO}';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_nasce_criada() IS "
        "'Recusa um INSERT em qualquer estado que nao criada, ou em versao que "
        "nao 1: o unico caminho para outro estado e a transicao (KAM-044).'"
    )

    # -------------------------------------------------- order_transicao_valida
    #
    # O `BEFORE UPDATE` do §6.2, e faz tres coisas:
    #
    #   1. uma mudanca de estado tem de estar no grafo, e se a linha do grafo
    #      tiver bandeira, a bandeira tem de estar ligada;
    #   2. a `version` tem de subir **de um** em cada mudanca de estado — e o
    #      que faz do numero uma contagem de transicoes e nao um contador
    #      qualquer, e e o que a `version` do registo referencia;
    #   3. o `lines_snapshot`, o `total_minor` e a `currency` ficam **congelados**
    #      depois de a encomenda sair de `criada` (criterio 4).
    #
    # O total e a moeda congelam com as linhas e nao sozinhos: o total e a soma
    # das linhas, e deixar mudar um sem o outro era deixar o espelho afirmar um
    # total que as suas proprias linhas desmentem — que e precisamente a
    # divergencia que a regra 3 do §10.3 manda resolver a favor do snapshot.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_transicao_valida() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_flag     text;
          v_existe   boolean;
          v_ligada   text;
        BEGIN
          IF NEW.estado IS DISTINCT FROM OLD.estado THEN
            SELECT g.flag, true INTO v_flag, v_existe
              FROM platform.order_state_graph g
             WHERE g.de = OLD.estado AND g.para = NEW.estado;
            IF NOT COALESCE(v_existe, false) THEN
              RAISE EXCEPTION
                'orders_mirror: a transicao % -> % nao esta no '
                'order_state_graph (KAM-044, docs/tecnica/03 secao 6.2)',
                OLD.estado, NEW.estado
                USING ERRCODE = '{SQLSTATE_TRANSICAO}';
            END IF;
            IF v_flag IS NOT NULL THEN
              v_ligada := COALESCE(
                NULLIF(current_setting('{GUC_DA_ENTREGA}', true), ''), 'off');
              IF v_ligada <> 'on' THEN
                RAISE EXCEPTION
                  'orders_mirror: a transicao % -> % esta atras de % e a '
                  'bandeira esta desligada (desligada no Piloto)',
                  OLD.estado, NEW.estado, v_flag
                  USING ERRCODE = '{SQLSTATE_TRANSICAO}';
              END IF;
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
              RAISE EXCEPTION
                'orders_mirror: a version sobe de um em cada transicao, de % '
                'para % (CAS do docs/tecnica/03 secao 6.2)',
                OLD.version, NEW.version
                USING ERRCODE = '{SQLSTATE_TRANSICAO}';
            END IF;
            -- A guarda do `pendente_confirmacao` (§6.2): `total_minor <=
            -- limite_manual` do tenant. Le-se por `platform.ten_tecto`, que e
            -- o caminho que o `checkCeiling` do `ten` ja usa — ver a nota da
            -- `CHAVE_DO_TECTO_MANUAL`.
            --
            -- O `COALESCE(-1)` e a falha fechada: sem entitlement activo que
            -- declare a chave, `ten_tecto` devolve `NULL` e a comparacao com
            -- `NULL` nao e verdadeira para valor nenhum — o `IF` nao disparava e
            -- a transicao passava **sem tecto nenhum**, que e precisamente o que
            -- o criterio 2 do KAM-009 chama «sem tecto nao quer dizer sem
            -- limite». Com `-1`, um `total_minor >= 0` recusa sempre.
            IF NEW.estado = 'pendente_confirmacao' THEN
              IF NEW.total_minor > COALESCE(
                   platform.ten_tecto(NEW.tenant_id, '{CHAVE_DO_TECTO_MANUAL}'),
                   -1) THEN
                RAISE EXCEPTION
                  'orders_mirror: o total % excede o tecto manual do tenant '
                  '(% = %); a confirmacao manual e so ate ao tecto '
                  '(docs/tecnica/03 secao 6.2)',
                  NEW.total_minor, '{CHAVE_DO_TECTO_MANUAL}',
                  COALESCE(platform.ten_tecto(
                    NEW.tenant_id, '{CHAVE_DO_TECTO_MANUAL}')::text, 'sem tecto')
                  USING ERRCODE = '{SQLSTATE_TECTO_MANUAL}';
              END IF;
            END IF;
          END IF;
          IF OLD.estado <> {CRIADA} AND (
               NEW.lines_snapshot <> OLD.lines_snapshot
               OR NEW.total_minor <> OLD.total_minor
               OR NEW.currency <> OLD.currency) THEN
            RAISE EXCEPTION
              'orders_mirror: o lines_snapshot, o total_minor e a currency sao '
              'imutaveis depois de criada (criterio 4; a encomenda esta em %)',
              OLD.estado
              USING ERRCODE = '{SQLSTATE_SNAPSHOT}';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_transicao_valida() IS "
        "'BEFORE UPDATE de orders_mirror: so as transicoes do "
        "order_state_graph, com a bandeira ligada quando a linha a tem, a "
        "version a subir de um, e o lines_snapshot congelado depois de criada "
        "(KAM-044, docs/tecnica/03 secao 6.2).'"
    )

    # ------------------------------------------------- order_estado_exige_log
    #
    # O `CONSTRAINT TRIGGER` diferido. Ver a nota do modulo para as tres coisas
    # que ele da e que um `BEFORE UPDATE` nao dava.
    #
    # Compara `OLD` com `NEW` **dentro** da funcao e nao numa clausula `WHEN`:
    # num *trigger* de restricao diferido a condicao e avaliada no instante da
    # instrucao e o corpo no `COMMIT`, e manter a comparacao no corpo deixa as
    # duas coisas no mesmo sitio.
    #
    # `SECURITY INVOKER` (a omissao), como o `evt_emitir` da `0004`: le o
    # `order_state_log` com a RLS e o contexto de quem escreveu a encomenda, que
    # e quem tem de ter gravado a linha. Uma `SECURITY DEFINER` aqui lia zero
    # linhas — o dono esta sujeito ao `FORCE` (ver `db/rls.py`) — e a
    # verificacao recusava **todas** as transicoes.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_estado_exige_log() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE v_log platform.order_state_log;
        BEGIN
          IF NEW.estado IS NOT DISTINCT FROM OLD.estado THEN
            RETURN NULL;
          END IF;
          SELECT * INTO v_log
            FROM platform.order_state_log l
           WHERE l.tenant_id = NEW.tenant_id
             AND l.order_id = NEW.id
             AND l.version = NEW.version;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'orders_mirror: a transicao % -> % (version %) nao gravou '
              'order_state_log na mesma transaccao (criterio 2 do KAM-044)',
              OLD.estado, NEW.estado, NEW.version
              USING ERRCODE = '{SQLSTATE_REGISTO}';
          END IF;
          IF v_log.de <> OLD.estado OR v_log.para <> NEW.estado THEN
            RAISE EXCEPTION
              'orders_mirror: o order_state_log da version % diz % -> % e a '
              'encomenda foi de % para %',
              NEW.version, v_log.de, v_log.para, OLD.estado, NEW.estado
              USING ERRCODE = '{SQLSTATE_REGISTO}';
          END IF;
          IF NEW.estado = {PAGA} THEN
            IF v_log.actor_kind <> 'sistema'
               OR v_log.evento_id IS NULL
               OR btrim(v_log.evento_id) = ''
               OR v_log.causa NOT IN ({", ".join(CAUSAS_QUE_PAGAM)}) THEN
              RAISE EXCEPTION
                'orders_mirror: paga exige evento autenticado do PAY com actor '
                'sistema e veio causa=%, actor=%, evento=% (criterio 3 do '
                'KAM-044, ADR-013)',
                v_log.causa, v_log.actor_kind, v_log.evento_id
                USING ERRCODE = '{SQLSTATE_AUTENTICIDADE}';
            END IF;
            -- **E o evento tem de existir.** As tres verificacoes acima nao
            -- ligam aquele texto a evento nenhum: a primeira versao desta
            -- revisao aceitava `evento_id = 'inventado'` com actor `sistema` e
            -- causa `payment.confirmed`, e a revisao adversarial mediu-o — o
            -- `paga` escrito, o outbox a zero e o `payment_events` a zero.
            --
            -- A ancora e o recibo de consumo do KAM-006
            -- (`platform.events_consumed`, revisao `0005`): o consumidor
            -- idempotente registra ali o `evento.id` **antes** de agir, pelo que
            -- exigir a linha e exigir que a transicao corra dentro do consumo de
            -- um evento que entrou de facto pela fila. Nao e o
            -- `payment_events` da `0029` porque o `payment_charges.order_id`
            -- **nao tem FK** — e do KAM-055 — e uma barreira que assentasse numa
            -- coluna que ninguem impoe nao e uma barreira.
            --
            -- Compara-se em **texto** e nao com um `::uuid`: um `evento_id` que
            -- nao seja um UUID levantaria `22P02` em vez da recusa com o codigo
            -- desta revisao, e o que se quer dizer a quem chama e «esse evento
            -- nao existe», nao «esse texto nao e um UUID».
            IF NOT EXISTS (
                 SELECT 1 FROM platform.events_consumed c
                  WHERE c.tenant_id = NEW.tenant_id
                    AND c.event_id::text = btrim(v_log.evento_id)) THEN
              RAISE EXCEPTION
                'orders_mirror: paga cita o evento % e nao ha recibo de consumo '
                'dele neste tenant (events_consumed, KAM-006); o consumidor '
                'registra o evento antes de transitar (criterio 3 do KAM-044, '
                'ADR-013)',
                v_log.evento_id
                USING ERRCODE = '{SQLSTATE_AUTENTICIDADE}';
            END IF;
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_estado_exige_log() IS "
        "'CONSTRAINT TRIGGER diferido de orders_mirror: no COMMIT, toda a "
        "mudanca de estado tem a sua linha de order_state_log, e paga exige "
        "actor sistema com evento autenticado do PAY (KAM-044 criterios 2 e 3, "
        "ADR-013).'"
    )


def _triggers() -> None:
    """Os quatro *triggers*: tres na encomenda e o `deny_mutation` no registo."""
    op.execute(
        f"""
        CREATE TRIGGER order_nasce_criada BEFORE INSERT ON {ENCOMENDAS}
          FOR EACH ROW EXECUTE FUNCTION platform.order_nasce_criada()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER order_transicao_valida BEFORE UPDATE ON {ENCOMENDAS}
          FOR EACH ROW EXECUTE FUNCTION platform.order_transicao_valida()
        """
    )
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER order_estado_exige_log
          AFTER UPDATE ON {ENCOMENDAS}
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION platform.order_estado_exige_log()
        """
    )
    # O `deny_mutation` e da `0029` e recusa `UPDATE`, `DELETE` e `TRUNCATE` a
    # **todos**, incluindo ao dono e ao superutilizador, que e o que nenhum
    # `REVOKE` alcanca. Dois *triggers*, como ali — mas o segundo cobre mais.
    #
    # **O por instrucao leva `DELETE` e nao so `TRUNCATE`, e a `0029` nao leva.**
    # A diferenca esta medida: um `BEFORE DELETE ... FOR EACH ROW` nao dispara
    # quando nao ha linhas, pelo que um `DELETE FROM order_state_log WHERE
    # <predicado que nao casa>` **passava** — nao apaga nada, mas devolve
    # `DELETE 0` a quem o escreveu e deixa quem audita a concluir que a tabela
    # aceita `DELETE`. Com o `FOR EACH STATEMENT`, a recusa vem antes de haver
    # linhas e e a mesma para o caso que apaga e para o que nao apaga.
    #
    # A `payment_events` da `0029` tinha a mesma lacuna (o `FOR EACH STATEMENT`
    # dela era so `BEFORE TRUNCATE`). Nao se corrigiu aqui: era outra revisao e
    # outro ticket. Ficou na **divida documental 175** e nao «no PR deste», que
    # e o que esta nota dizia: o corpo de um PR nao e versionado, pelo que
    # registar ali e nao registar. Apanhado pela revisao adversarial.
    #
    # **A divida 175 tem credor, e esta paga: o KAM-175.** A `0029` passou a
    # `BEFORE TRUNCATE OR DELETE OR UPDATE ... FOR EACH STATEMENT`, e a medicao
    # dele acrescentou a metade que esta nota nao via: um `UPDATE` sem linhas
    # tambem passava, pela mesma razao. **E essa metade continua aberta aqui**,
    # porque o `order_state_log_sem_truncate` abaixo e `BEFORE TRUNCATE OR
    # DELETE` e para ali — divida **176**, credor **KAM-176**.
    op.execute(
        f"""
        CREATE TRIGGER order_state_log_sem_mutacao
          BEFORE UPDATE OR DELETE ON {REGISTO}
          FOR EACH ROW EXECUTE FUNCTION platform.deny_mutation()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER order_state_log_sem_truncate
          BEFORE TRUNCATE OR DELETE ON {REGISTO}
          FOR EACH STATEMENT EXECUTE FUNCTION platform.deny_mutation()
        """
    )
    # ------------------------------------------------------- ENABLE ALWAYS
    #
    # **Os cinco sao `ENABLE ALWAYS`, e nao a omissao.** A omissao (`O`) e
    # saltada por `session_replication_role = replica`, que e o que a `0029`
    # escreveu para os *triggers* do ledger e que vale aqui pela mesma razao com
    # mais uma: as cinco barreiras desta revisao sao **invariantes de negocio** e
    # nao integridade referencial — o grafo, a entrada unica, a imutabilidade do
    # snapshot, o registo de toda a transicao e a autenticidade de `paga`.
    #
    # Com a omissao, um superutilizador que ponha a sessao em `replica` escreve
    # `paga` sem evento nenhum e sem registo nenhum, e nada no catalogo diz que
    # isso e possivel. E tambem o modo em que corre quem **aplica** replicacao
    # logica, onde uma linha que violasse o grafo entrava em silencio.
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} ENABLE ALWAYS TRIGGER order_nasce_criada"
    )
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} ENABLE ALWAYS TRIGGER order_transicao_valida"
    )
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} ENABLE ALWAYS TRIGGER order_estado_exige_log"
    )
    op.execute(
        f"ALTER TABLE {REGISTO} ENABLE ALWAYS TRIGGER order_state_log_sem_mutacao"
    )
    op.execute(
        f"ALTER TABLE {REGISTO} ENABLE ALWAYS TRIGGER order_state_log_sem_truncate"
    )


def _rls() -> None:
    """RLS `FORCE` e politica `tenant_iso` nas quatro tabelas com `tenant_id`.

    O `order_state_graph` **nao** entra: nao tem `tenant_id`, como a
    `evt_subscricoes` da `0004` e a `payment_outbox_map` da `0029`. A descoberta
    do X-05 pergunta pela coluna, pelo que ele tambem nao precisa de entrada em
    `ci/rls_exceptions.yaml`.
    """
    # Por extenso e pela ordem de criacao. Nao num `for` sobre a tupla: o *gate*
    # 3b segue a chamada com os argumentos que consegue resolver sem correr a
    # revisao, e um nome vindo de uma iteracao nao e um deles.
    rls.enable_tenant_rls("orders_mirror")
    rls.enable_tenant_rls("order_intents")
    rls.enable_tenant_rls("order_state_log")
    rls.enable_tenant_rls("order_reconciliation_issues")


def _privilegios() -> None:
    """Tabela a tabela e coluna a coluna. Ver a nota do modulo."""
    op.execute(f"GRANT SELECT, INSERT ON {ENCOMENDAS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_ENCOMENDAS)}) ON {ENCOMENDAS} "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(f"GRANT SELECT, INSERT ON {INTENCOES} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_INTENCOES)}) ON {INTENCOES} "
        f"TO {PAPEL_DA_APP}"
    )
    # **So `SELECT` e `INSERT`**, que e o criterio 6 a letra. Ver a nota do
    # modulo para a razao de o `SELECT` estar aqui.
    op.execute(f"GRANT SELECT, INSERT ON {REGISTO} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT, INSERT ON {DIVERGENCIAS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_DIVERGENCIAS)}) "
        f"ON {DIVERGENCIAS} TO {PAPEL_DA_APP}"
    )
    # O grafo e de referencia: a aplicacao le-o, e quem o escreve e uma revisao.
    op.execute(f"GRANT SELECT ON {GRAFO} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.order_numero_publico() "
        f"TO {PAPEL_DA_APP}"
    )
    # O `kamba_batch` e a retencao (KAM-071) e o semeador das baterias de
    # isolamento. Tem `BYPASSRLS` por atributo, e e por isso que varre a base
    # toda; a auditoria do que ele faz e do KAM-012.
    #
    # **No `order_state_log` nao tem `UPDATE` nem `DELETE`**, ao contrario das
    # outras: o `deny_mutation` recusava-os de qualquer forma, e conceder um
    # privilegio que um *trigger* anula escrevia no catalogo uma permissao que
    # nao existe. Quem purgar o registo tera de o fazer com a tabela, como a
    # `0029` registou para o ledger.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {ENCOMENDAS} TO {PAPEL_DE_LOTE}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {INTENCOES} TO {PAPEL_DE_LOTE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON {REGISTO} TO {PAPEL_DE_LOTE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {DIVERGENCIAS} TO {PAPEL_DE_LOTE}"
    )
    op.execute(f"GRANT SELECT ON {GRAFO} TO {PAPEL_DE_LOTE}")


# As tres funcoes abaixo nao recebem argumentos, e nao e por gosto: o *gate* 3b
# le esta revisao sem a correr, e so segue uma chamada cujos argumentos consiga
# resolver. O padrao e o da `0003` e o da `0004`.


def _contar() -> dict[str, int]:
    """Linhas em cada uma das quatro tabelas de tenant da revisao."""
    contagens = {}
    for tabela_a_contar in TABELAS_COPIADAS:
        contagens[tabela_a_contar] = (
            op.get_bind()
            .exec_driver_sql(f"SELECT count(*) FROM platform.{tabela_a_contar}")
            .scalar_one()
        )
    return contagens


def _celula(valor):
    """Um valor de coluna em JSON: os `bytea` em base64, o `jsonb` como JSON.

    **O `jsonb` nao passa por `str()`, e a razao foi medida pela revisao
    adversarial.** O `pg8000` descodifica `jsonb` para objecto de Python, pelo
    que um `str()` dava a representacao de Python — `[{'qty': 2, ...}]`, com
    apostrofos — e a copia **deixava de ser JSON valido**. O `lines_snapshot` e
    a unica prova das linhas de uma encomenda real; uma copia que nao se volta a
    carregar nao e uma copia.

    O `_celula` da `0004` tem a mesma forma e a mesma classe de defeito; ali o
    que se copia nao tem `jsonb` de negocio (o `envelope` sai pelo
    `json.dumps` de fora), e aqui tem duas colunas — o `lines_snapshot` e o
    `detalhe` da divergencia.
    """
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(valor)).decode("ascii")}
    if isinstance(valor, (dict, list)):
        return valor
    return None if valor is None else str(valor)


def _linhas():
    """Todas as linhas a copiar: (tabela, {coluna: valor em JSON})."""
    for tabela_copiada in TABELAS_COPIADAS:
        resultado = op.get_bind().exec_driver_sql(
            f"SELECT * FROM platform.{tabela_copiada}"
        )
        colunas = list(resultado.keys())
        for linha in resultado:
            yield tabela_copiada, {c: _celula(v) for c, v in zip(colunas, linha)}


def _copia_logica() -> None:
    """Escreve as linhas de encomendas num ficheiro, ou recusa o `downgrade`.

    A revisao e **aditiva** — antes dela nao havia encomendas —, mas o passo
    apaga tabelas que, com linhas dentro, sao o ciclo de vida de encomendas
    reais e o rasto auditado de cada mudanca de estado. O §11 de
    `docs/tecnica/03` diz que a `orders_mirror` e o `order_state_log` nao tem
    `downgrade` destrutivo, e o `order_state_log` nao se reconstroi de sitio
    nenhum: e ele a prova de que `paga` veio de um evento autenticado. Uma perda
    dessas nao pode ser silenciosa. Com linhas em qualquer das quatro tabelas, o
    passo so avanca se `KAMBA_DOWNGRADE_0030_COPIA` apontar para um ficheiro
    **novo**, onde ficam todas as linhas, uma por linha de JSON.

    Corre **depois** de a RLS ser desligada: o dono das tabelas esta sujeito ao
    `FORCE`, e sem contexto de tenant leria zero linhas — a copia saia vazia e o
    passo apagava tudo com um ficheiro que parecia prova. E a licao da `0003` e
    da `0004`.
    """
    contagens = _contar()
    if not any(contagens.values()):
        return

    destino = os.environ.get(VARIAVEL_DA_COPIA, "")
    resumo = ", ".join(f"{tabela}: {n}" for tabela, n in contagens.items())
    if not destino:
        raise RuntimeError(
            f"downgrade da 0030 recusado: ha encomendas nas tabelas ({resumo}) e "
            f"o passo apaga-as. Defina {VARIAVEL_DA_COPIA} com o caminho de um "
            "ficheiro novo para a copia logica, ou esvazie as tabelas de proposito."
        )

    # Modo `x`: nunca por cima de uma copia anterior. 0600: so quem a fez a le.
    descritor = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    escritas = dict.fromkeys(contagens, 0)
    with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as ficheiro:
        for origem, registo in _linhas():
            ficheiro.write(
                json.dumps({"tabela": origem, "linha": registo}, sort_keys=True) + "\n"
            )
            escritas[origem] += 1
        ficheiro.flush()
        os.fsync(ficheiro.fileno())
    if escritas != contagens:
        raise RuntimeError(
            f"downgrade da 0030 recusado: a copia tem {escritas} e as tabelas "
            f"tem {contagens}"
        )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # A RLS primeiro, por duas razoes: a ordem inversa do `upgrade`, e porque a
    # copia logica a seguir precisa de ver as linhas (ver `_copia_logica`).
    #
    # Por extenso e pela ordem inversa do `upgrade`. Nao `reversed(...)`: o
    # *gate* 3b segue a chamada com os argumentos que consegue resolver sem
    # correr a revisao, e uma iteracao invertida nao e um deles.
    rls.disable_tenant_rls("order_reconciliation_issues")
    rls.disable_tenant_rls("order_state_log")
    rls.disable_tenant_rls("order_intents")
    rls.disable_tenant_rls("orders_mirror")
    _copia_logica()
    # Os *triggers* caem com as tabelas; as funcoes nao, e por isso vao a
    # seguir. O `deny_mutation` **nao** se apaga aqui: e da `0029`, e o
    # `downgrade` dela e que o leva.
    op.execute(f"DROP TABLE {DIVERGENCIAS}")
    op.execute(f"DROP TABLE {REGISTO}")
    op.execute(f"DROP TABLE {INTENCOES}")
    op.execute(f"DROP TABLE {GRAFO}")
    op.execute(f"DROP TABLE {ENCOMENDAS}")
    op.execute("DROP FUNCTION platform.order_estado_exige_log()")
    op.execute("DROP FUNCTION platform.order_transicao_valida()")
    op.execute("DROP FUNCTION platform.order_nasce_criada()")
    op.execute("DROP FUNCTION platform.order_numero_publico()")

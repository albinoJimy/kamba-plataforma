"""Onboarding de canal: as fases do Embedded Signup v4 e os recursos da saga (KAM-016).

A primeira linha e **sem acentos**, como as quinze revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

Uma tabela:

    channel_onboarding   a tentativa de ligar um numero, fase a fase, com os
                         recursos que cada passo criou (`01` §13.1 e §13.2)

## O que esta revisao **nao** acrescenta, e isso e o achado principal

**Nada em `tenant_channels`.** Os tres identificadores que o criterio 8 manda
guardar — `waba_id`, `waac_id` (nulo hoje) e `phone_number_id` — existem desde a
`0001`, e o `token_ref` do criterio 3 tambem. A leitura do bloco do ticket
sugere colunas novas; a da revisao `0001` mostra que ja estao todas lá, com os
`CHECK` de forma e o `GRANT UPDATE` por coluna a cobri-las.

**E o 409 do criterio 4 nao e codigo.** «Anexar um `phone_number_id` ja usado
por outro tenant devolve 409» e a `tenant_channels_phone_number_id_uq` da `0001`
a morder: a unicidade e **global**, sem `tenant_id` na chave, e e a mesma
propriedade que torna a resolucao do CHR deterministica (a nota do `SQL_CANAL`
em `packages/core-ts/src/chr/consultas.ts` escreve-o por extenso). Uma
verificacao em codigo antes do `INSERT` seria uma segunda verdade a reconciliar
com a primeira, e perderia a corrida: entre o `SELECT` e o `INSERT` cabe outro
processo.

Consequencia de desenho que vale a pena dizer aqui: por isso o `INSERT` em
`tenant_channels` vem **depois** da troca do *code*, e nao antes. O
`token_ref` e `NOT NULL`, pelo que nao ha linha de canal a criar antes de haver
*token* — e um conflito no `INSERT` compensa o passo do *token*, que e
exactamente a maquinaria do criterio 7. **O criterio 4 e o criterio 7 sao a
mesma maquinaria**, e isso nao foi planeado: saiu de a coluna ser `NOT NULL`.

## As nove fases, e a decima que nao e fase

O criterio 6 enumera nove: `iniciado`, `es_concluido`, `subscrito`,
`a_sincronizar`, `verificado`, `pronto`, `ativo`, `falhado`, `abandonado`. O
diagrama do `01` §13.1 desenha **dez** — tem tambem `desligado`, com a aresta
`ativo --> desligado: account update PARTNER_REMOVED`.

**O `desligado` nao e fase de onboarding: e estado do canal.** Esta no dominio
de `tenant_channels.estado` desde a `0001` (dicionario §3.2), e quem o escreve e
o tratador do `account_update` — KAM-017, pelo seu criterio da reconexao. O
diagrama mistura as duas maquinas num desenho, e o criterio deste ticket
desfaz a mistura: o `ativo` e **terminal** nesta tabela, e a saga acaba ali.
Quem precisar de reconectar passa por `falhado → iniciado` ou por
`abandonado → iniciado`, que o diagrama ja desenha.

## A matriz de transicoes, e as sete arestas que o diagrama nao desenha

O diagrama desenha onze arestas. A matriz desta revisao tem **dezesseis**, e a
diferenca e uma so regra: **de qualquer fase nao terminal vai-se a `falhado`.**

O diagrama so desenha `a_sincronizar --> falhado` (o prazo de 24 h). Mas o
criterio 7 pede «uma falha injectada no **passo 4** deixa 0 recursos orfaos», e
o passo 4 do `01` §13.2 e a subscricao — que corre na fase `es_concluido`. Uma
saga cuja compensacao nao tem onde se registar e uma saga que nao compensa: sem
a aresta `es_concluido → falhado`, o caminho que o criterio 7 manda exercitar
nao e representavel na tabela que o criterio 6 define. As seis arestas novas sao
a mesma afirmacao para as outras seis fases nao terminais.

O `abandonado` fica como o diagrama o desenha: **so de `iniciado`**. O criterio
diz «sem conclusao em 30 min», e o diagrama diz de que conclusao fala —
`iniciado --> abandonado: popup fechado ou timeout 30 min`. Uma tentativa que ja
trocou o *code* e subscreveu campos nao se «abandona»: ou acaba, ou falha com
compensacao, e o que distingue as duas e haver recursos a desfazer.

**A matriz vive no codigo e nao num gatilho**, e e a escolha que a `0010` fez
para a monotonia de `outbound_messages.state`: a transicao faz-se por
*compare-and-set* (`WHERE fase = <esperada>`), que e atomico, e quem decide se o
par e legal e o `TRANSICOES` de `packages/core-ts/src/onboarding/contrato.ts`. O
que esta revisao poe na base e o `CHECK` do dominio das nove — uma fase fora da
lista nao entra, venha de onde vier — e a *suite* do *gate* 8 percorre os **81**
pares ordenados contra um PostgreSQL real e exige que exactamente dezesseis
passem.

Um gatilho daria a matriz a base, e pesou-se: custa uma funcao `SECURITY
INVOKER`, o seu `REVOKE ALL FROM PUBLIC`, a leitura do *gate* 3b e o
`downgrade`, para substituir um *compare-and-set* que ja e atomico. A `0006` tem
um gatilho porque a cadeia de *hash* precisa de uma garantia que o privilegio
nao sabe exprimir; aqui o privilegio e o `CHECK` dizem o que ha a dizer.

## A idempotencia do criterio 2 e da base, e sao duas unicidades

«Repetir o mesmo `code` ou o mesmo `(tenant_id, waba_id)` 2x produz 1 canal, 1
*token* e 0 subscricoes duplicadas.» Sao duas chaves, e nenhuma e o canal:

    channel_onboarding_code_uq         (tenant_id, code_hash)
    channel_onboarding_tenant_waba_uq  (tenant_id, waba_id)

O `INSERT ... ON CONFLICT DO NOTHING RETURNING` devolve zero linhas na
repeticao, e o modulo le então a linha que ja la estava e devolve-a. Nao ha
`SELECT` antes do `INSERT`: entre os dois cabe outro processo, e o criterio pede
**um** canal e nao «quase sempre um». E a mesma forma do `SQL_REGISTAR_TRANSICAO`
da `0014`, do `SQL_ENFILEIRAR` da `0010` e do `SQL_REGISTAR_PROVA` da `0015`.

**«1 canal» sai de «1 linha de onboarding»**, porque o canal cria-se dentro da
mesma transaccao que escreve o `channel_id` nesta linha. E o que torna a
afirmacao uma propriedade da base e nao do codigo: duas chamadas concorrentes
com o mesmo `(tenant_id, waba_id)` nao podem ter as duas uma linha aqui, logo
nao podem ter as duas um canal.

**As duas sao compostas com o `tenant_id`**, pela razao da emenda 1.21 que a
`0015` repetiu: com unicidade global, uma tentativa do *tenant* B que calhasse
no mesmo `code_hash` era deduplicada em silencio contra a linha de A — e o que
se perdia era o onboarding de B, sem erro nenhum a dizer porque.

**O que a `(tenant_id, waba_id)` custa, e esta escrito e nao escondido:** um
*tenant* nao pode ter dois numeros no **mesmo** WABA por este caminho. Um WABA
aceita varios numeros, pelo que o caso e real; o criterio 2 fixa-o assim, e a
razao de o aceitar e que o recurso que o passo 4 cria — a subscricao — e **do
WABA** e nao do numero: «0 subscricoes duplicadas» e, literalmente, uma
subscricao por `(tenant, waba)`. Quem acrescentar um segundo numero ao mesmo
WABA tem de reutilizar a subscricao que ja existe, e isso e um caminho novo e
nao um relaxamento desta chave. Fica na secção de verificacao do bloco.

## O `code` entra em resumo e nunca em claro, e isso e o criterio 3

A coluna e `code_hash bytea` com `CHECK (octet_length(...) = 32)`: um `sha256`,
nem mais nem menos. O *code* do Embedded Signup e trocavel por um *token* de
cliente — e, portanto, um segredo com o valor do *token*. Guarda-lo em claro
numa coluna para fazer idempotencia era pôr na base exactamente aquilo que o
criterio 3 manda nao pôr lá, e o *dump grep* desse criterio encontrava-o.

Um resumo serve para o que a idempotencia precisa (igualdade) e nao serve para o
que um atacante precisa (trocar). Nao leva sal nem HMAC: o *code* tem entropia
de segredo, pelo que um resumo dele nao e enumeravel — ao contrario de um
telefone, que e o que obriga o `pepper_contact_hmac` da `0003` a existir.

## O `pin_ref` fica aqui e nao em `tenant_channels`, e e decisao

O criterio 3 manda o PIN 2FA de seis digitos para o cofre «com acesso minimo»; o
`ops/secrets-inventory.yaml` ja o declara (`meta_pin_2fa`, `instancias: tenant`,
«so o provisionamento o le»). O que faltava era onde guardar a **referencia**.

Nao vai para `tenant_channels` porque o PIN e artefacto de **onboarding** e nao
do canal: e o que o passo 5' do `01` §13.2 usa para registar o numero no modo
`cloud_only`, uma vez. Uma coluna em `tenant_channels` dizia que o canal precisa
dele para viver, e o `GRANT UPDATE` por coluna da `0001` teria de a admitir — o
que poe a referencia de um segredo ao alcance de `kamba_app`, que nunca a le.

E leva `CHECK` de forma de `SecretRef` — a mesma do `port.ts`. Uma referencia
mal formada e um segredo que ninguem vai conseguir ir buscar, e isso descobre-se
no dia em que faz falta.

## O `recursos_criados` e um `jsonb` **array**, e e a lista da compensacao

O `01` §13.2 di-lo: «cada passo registra o recurso criado; a falha dispara a
compensacao inversa». A coluna e a lista, pela ordem em que os passos correram,
e a compensacao percorre-a ao contrario. O `CHECK` exige
`jsonb_typeof(...) = 'array'`: um objecto aqui era uma lista sem ordem, e a
ordem e a metade do que faz a compensacao inversa ser inversa.

**Zero recursos orfaos le-se nesta coluna.** Depois de compensar, a lista e
`[]` — e e isso que o criterio 7 afirma e o teste mede, ao lado de «0 linhas em
`tenant_channels`» e «0 subscricoes no WABA».

## O registo de auditoria do criterio 4 **nao** e o `audit_log`, e foi medido

«Devolve 409, nao altera nada e deixa registo de auditoria.» O registo e uma
linha desta tabela em `falhado`, com o `motivo` e `recursos_criados = []`.

Nao e o `platform.audit_log` da `0006`, e a razao e mecanica e nao preferencia:
o dominio de `audit_log.action` tem **sete** valores e o `CHECK` esta na `0006`,
fundida. O *gate* 3b le o `CHECK` de **cada revisao isoladamente** e compara-o
com o dicionario nos dois sentidos — `tools/canon_lint/ddl.py` reporta `falta:`
—, pelo que acrescentar um oitavo valor ao dicionario deixava a `0006` vermelha.
E a mecanica que a emenda 1.20 pagou para o `unrouted_events.motivo` e a 1.26
para o `motivo_restricao`, pelo outro lado: ali os valores entraram na revisao
que cria o `CHECK`, e aqui essa revisao nao se reescreve.

Nenhum dos sete valores descreve isto (`price.update`, `stock.adjust`,
`payment.manual_confirm`, `access.conversation`, `batch.run`,
`breakglass.open`, `audit.read`), e enfiar a recusa em `access.conversation`
era mentir num registo que existe para nao mentir.

**E «nao altera nada» continua literalmente verdadeiro**, porque o 409 vem de
uma transaccao que **reverte**: o `INSERT` em `tenant_channels` levanta `23505`,
a transaccao cai, e nem a linha do canal nem a actualizacao desta tabela
sobrevivem. A linha de `falhado` escreve-se **depois**, numa transaccao propria.
Se a linha de auditoria contasse como «alterar», o criterio contradizia-se a si
proprio na mesma frase.

## O papel que escreve e o `kamba_batch`, e nao o `kamba_app`

O onboarding de um canal e **provisionamento**, e o dicionario §3.2 ja o
atribuiu: «quem os altera e o `kamba_batch` — provisionamento (KAM-091) e
cobranca (KAM-059) sao de retaguarda e ja la correm». Tres consequencias:

1. O contador `es_onboardings_7d` do criterio 8 **atravessa tenants** — o limite
   de dez clientes por sete dias e da nossa app perante a Meta, nao de uma loja.
   Com RLS `FORCE` e a politica `tenant_iso`, `kamba_app` nunca o poderia contar;
   o `kamba_batch` tem `BYPASSRLS` e conta.
2. A compensacao apaga a linha de `tenant_channels` que o passo anterior criou, e
   `kamba_app` **nao tem `DELETE` em tabela nenhuma** desde a `0001` («soft
   delete: estado, nunca DELETE»). Quem apaga e o `kamba_batch`.
3. `kamba_app` fica com **`SELECT` e mais nada** nesta tabela: o painel da loja
   le em que fase esta o seu canal. E o que torna o X-03/X-04 do *gate* 6
   significativo aqui — a RLS protege a **leitura**, e o que protege a escrita e
   a falta de privilegio, que e mais forte do que a politica recusar.

## Tres indices, e cada um responde a uma pergunta diferente

    channel_onboarding_tenant_fase_idx    (tenant_id, fase)
    channel_onboarding_janela_idx         (criado_at DESC)
    channel_onboarding_espera_idx         (fase, actualizado_at)

O primeiro comeca pelo `tenant_id` **porque a RLS o le em toda a consulta** — a
licao da `0011`, onde o *gate* 8 recusou a tabela sem ele — e e a pergunta do
painel.

O segundo **nao** comeca pelo `tenant_id`, e e a primeira vez que isso acontece
neste esquema. A pergunta do criterio 8 e «quantos onboardings houve na
plataforma nos ultimos sete dias», e por o `tenant_id` a frente numa pergunta
que nao filtra por ele era pedir ao PostgreSQL que varresse o indice inteiro.
Quem a faz tem `BYPASSRLS`, pelo que o predicado da politica nao entra na
consulta. A regra da `0001` («`tenant_id` em primeiro lugar num indice de cada
tabela») fica satisfeita pelo primeiro indice, que e o que ela pede.

O terceiro e a varredura dos 30 minutos: `fase = 'iniciado'` e
`actualizado_at` antigo. Pelo mesmo motivo do segundo, nao leva `tenant_id`: um
*popup* abandonado nao e problema de uma loja, e quem varre e o `kamba_batch`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

#: As nove fases do criterio 6, pela ordem do `01` §13.1.
#:
#: Os valores vem **ja entre apostrofos**: e a unica forma que o *gate* 3b
#: resolve, porque le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*. E a licao que a
#: `0015` escreveu para as finalidades do consentimento.
#:
#: **O `desligado` nao esta aqui**, e isso e a decisao do docstring: e estado de
#: `tenant_channels` e nao fase de onboarding.
FASES = (
    "'iniciado'",
    "'es_concluido'",
    "'subscrito'",
    "'a_sincronizar'",
    "'verificado'",
    "'pronto'",
    "'ativo'",
    "'falhado'",
    "'abandonado'",
)

#: As fases em que **ja existe canal**, e por isso o `channel_id` nao e nulo.
#:
#: E o complemento de `iniciado`, `falhado` e `abandonado`: antes da troca do
#: *code* nao ha linha em `tenant_channels`, e depois de compensar tambem nao.
#: Escreve-se como a lista das **tres** e nao das seis, porque o `CHECK` e uma
#: implicacao e nao uma igualdade — uma tentativa que falhe **com** canal criado
#: (a compensacao a correr) e um estado legitimo, e um `CHECK` sobre as seis
#: recusava-a.
FASES_SEM_CANAL = ("'iniciado'", "'falhado'", "'abandonado'")

#: Bytes de um `sha256`, como na `0015`. O `code_hash` e `bytea` e nao `text`:
#: hexadecimal gastava 64 caracteres para dizer o mesmo, com a liberdade de
#: alguem escrever maiusculas num e minusculas noutro e os dois deixarem de
#: comparar iguais.
BYTES_DO_SHA256 = 32

#: A forma de uma `SecretRef`, literalmente a do `REF` de
#: `packages/core-ts/src/secrets/port.ts`.
#:
#: O `~` do PostgreSQL e POSIX e nao ECMAScript, pelo que a classe
#: `[A-Za-z0-9._:-]` e as chaves de repeticao passam tal e qual. O que **nao**
#: passa e o `\x21-\x7e` que o `cripto.ts` usa noutro sitio: aqui nao e preciso.
FORMA_DA_REF = r"^[a-z][a-z0-9_]{2,63}(/[A-Za-z0-9._:-]{1,128})?$"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.channel_onboarding (
            id                uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id         uuid        NOT NULL,
            -- Nulo ate a troca do *code* criar a linha de `tenant_channels`, e
            -- nulo outra vez depois de a compensacao a apagar. O `CHECK` abaixo
            -- prende a implicacao: nas seis fases do meio, existe.
            channel_id        uuid,
            waba_id           text        NOT NULL,
            -- Nulo hoje, por desenho: a Fase 3 do novo modelo de contas (H1
            -- 2028, CONFIRMADO em `E1` §3) passa a exigir o ID do WAAC nos
            -- caminhos da API. A coluna existe aqui **e** em `tenant_channels`
            -- desde a `0001`, e e isto que o criterio 8 pede.
            waac_id           text,
            phone_number_id   text        NOT NULL,
            -- O resumo do *code* do Embedded Signup, nunca o *code*: ver a nota
            -- do modulo. E a metade da idempotencia do criterio 2.
            code_hash         bytea       NOT NULL,
            fase              text        NOT NULL DEFAULT 'iniciado',
            -- A lista dos recursos que cada passo criou, pela ordem. A
            -- compensacao percorre-a ao contrario, e `[]` depois de compensar e
            -- o que o criterio 7 afirma.
            recursos_criados  jsonb       NOT NULL DEFAULT '[]'::jsonb,
            -- A referencia ao PIN 2FA no cofre (`meta_pin_2fa`), para o modo
            -- `cloud_only`. Nunca o PIN.
            pin_ref           text,
            -- Porque e que falhou ou foi abandonada. Texto nosso e nao da Meta:
            -- um codigo de erro da Meta vive no `meta_error_codes_seen` da
            -- `0013`, que e a coluna que o KAM-023 criou para isso.
            motivo            text,
            criado_at         timestamptz NOT NULL DEFAULT now(),
            actualizado_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT channel_onboarding_pkey PRIMARY KEY (id),
            -- **A primeira metade da idempotencia do criterio 2.** Composta com
            -- o `tenant_id` pela razao da emenda 1.21: com unicidade global,
            -- uma tentativa de B que calhasse no mesmo resumo era deduplicada
            -- em silencio contra a linha de A.
            CONSTRAINT channel_onboarding_code_uq UNIQUE (tenant_id, code_hash),
            -- **A segunda metade**, e e ela que faz «1 canal» ser propriedade da
            -- base: o canal cria-se na mesma transaccao que escreve o
            -- `channel_id` nesta linha. Ver a nota do modulo para o que custa.
            CONSTRAINT channel_onboarding_tenant_waba_uq UNIQUE (tenant_id, waba_id),
            CONSTRAINT channel_onboarding_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta com o `tenant_id`**, pela razao que a `0009` fixou e a
            -- `0011`, a `0012`, a `0014` e a `0015` repetiram: sem ele, uma
            -- tentativa de A podia apontar para um canal de B, e nem o *gate* 6
            -- nem o 3b o veriam. Assenta na `tenant_channels_tenant_id_uq` que a
            -- `0009` acrescentou precisamente para isto.
            CONSTRAINT channel_onboarding_channel_fk
                FOREIGN KEY (tenant_id, channel_id)
                REFERENCES platform.tenant_channels (tenant_id, id),
            CONSTRAINT channel_onboarding_fase_ck
                CHECK (fase IN ({", ".join(FASES)})),
            -- Uma implicacao e nao uma igualdade: nas fases do meio ha canal.
            -- Nas tres de fora pode nao haver — e o `falhado` **pode** ter
            -- canal, enquanto a compensacao nao correu.
            CONSTRAINT channel_onboarding_canal_ck
                CHECK (channel_id IS NOT NULL
                       OR fase IN ({", ".join(FASES_SEM_CANAL)})),
            CONSTRAINT channel_onboarding_waba_id_ck
                CHECK (waba_id <> '' AND waba_id = btrim(waba_id)),
            CONSTRAINT channel_onboarding_waac_id_ck
                CHECK (waac_id IS NULL
                       OR (waac_id <> '' AND waac_id = btrim(waac_id))),
            CONSTRAINT channel_onboarding_phone_number_id_ck
                CHECK (phone_number_id <> ''
                       AND phone_number_id = btrim(phone_number_id)),
            -- Trinta e dois octetos, nem mais nem menos: um `code_hash` de
            -- outro tamanho nao e um `sha256`, e uma idempotencia que compara
            -- resumos de tamanhos diferentes nao compara nada.
            CONSTRAINT channel_onboarding_code_hash_ck
                CHECK (octet_length(code_hash) = {BYTES_DO_SHA256}),
            CONSTRAINT channel_onboarding_recursos_ck
                CHECK (jsonb_typeof(recursos_criados) = 'array'),
            -- A forma de uma `SecretRef`, e nao so «nao vazio»: uma referencia
            -- mal formada e um segredo que ninguem vai conseguir ir buscar, e
            -- isso descobre-se no dia em que faz falta.
            CONSTRAINT channel_onboarding_pin_ref_ck
                CHECK (pin_ref IS NULL OR pin_ref ~ '{FORMA_DA_REF}'),
            CONSTRAINT channel_onboarding_motivo_ck
                CHECK (motivo IS NULL OR btrim(motivo) <> '')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.channel_onboarding IS "
        "'A tentativa de ligar um numero pelo Embedded Signup v4, fase a fase "
        "(KAM-016). Uma linha por (tenant, waba): as duas unicidades sao a "
        "idempotencia do criterio 2, e e por o canal se criar na mesma "
        "transaccao que escreve o channel_id aqui que «1 canal» e propriedade da "
        "base. Quem escreve e o kamba_batch — o onboarding e provisionamento —, "
        "e kamba_app tem SELECT e mais nada.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_onboarding.fase IS "
        "'As nove fases do `01` §13.1 que o criterio 6 enumera. O `desligado` do "
        "diagrama **nao** esta no dominio: e estado de tenant_channels e nao "
        "fase de onboarding, e quem o escreve e o KAM-017. O `ativo` e terminal. "
        "A matriz de transicoes vive em src/onboarding/contrato.ts e aplica-se "
        "por compare-and-set (WHERE fase = <esperada>), como a monotonia de "
        "outbound_messages.state da `0010`; a base impoe o dominio.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_onboarding.code_hash IS "
        "'sha256 do code do Embedded Signup, **nunca o code**. O code e "
        "trocavel por um token de cliente, logo e um segredo com o valor do "
        "token: guarda-lo em claro para fazer idempotencia punha na base o que o "
        "criterio 3 manda nao por la, e o dump grep desse criterio encontrava-o. "
        "Sem sal e sem HMAC: o code tem entropia de segredo, pelo que o resumo "
        "nao e enumeravel — ao contrario de um telefone, que e o que obriga o "
        "pepper_contact_hmac da `0003` a existir.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_onboarding.recursos_criados IS "
        "'A lista dos recursos que cada passo criou, **pela ordem** (`01` "
        "§13.2). A compensacao percorre-a ao contrario, e e por isso que e um "
        "array e nao um objecto: a ordem e a metade do que faz a compensacao "
        "inversa ser inversa. Depois de compensar vale `[]`, e e ai que se le os "
        "«0 recursos orfaos» do criterio 7.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_onboarding.pin_ref IS "
        "'Referencia opaca ao PIN 2FA no cofre (meta_pin_2fa), para o registo do "
        "numero em modo cloud_only. Nunca o PIN. Fica aqui e nao em "
        "tenant_channels porque o PIN e artefacto de onboarding e nao do canal — "
        "e porque uma coluna la obrigava o GRANT UPDATE por coluna da `0001` a "
        "admiti-la, pondo a referencia ao alcance de kamba_app, que nunca a le.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_onboarding.waac_id IS "
        "'O ID do WhatsApp account, **nulo hoje** e de proposito: a Fase 3 do "
        "novo modelo de contas (H1 2028, CONFIRMADO em E1 §3) passa a exigi-lo "
        "nos caminhos da API. Guardar os dois identificadores hoje e o criterio "
        "8, e e o que torna a Fase 3 uma alteracao de caminho e nao de esquema.'"
    )

    # O indice do painel: `tenant_id` primeiro **porque a RLS o le em toda a
    # consulta** (a licao da `0011`). Satisfaz tambem a regra da `0001`.
    op.execute(
        "CREATE INDEX channel_onboarding_tenant_fase_idx "
        "ON platform.channel_onboarding (tenant_id, fase)"
    )
    # O contador `es_onboardings_7d` do criterio 8: **atravessa tenants**, porque
    # o limite de dez clientes por sete dias e da nossa app perante a Meta. Por
    # isso nao leva `tenant_id` a frente — ver a nota do modulo.
    op.execute(
        "CREATE INDEX channel_onboarding_janela_idx "
        "ON platform.channel_onboarding (criado_at DESC)"
    )
    # A varredura dos 30 minutos do criterio 6. Pelo mesmo motivo, sem
    # `tenant_id`: um *popup* abandonado nao e problema de uma loja.
    op.execute(
        "CREATE INDEX channel_onboarding_espera_idx "
        "ON platform.channel_onboarding (fase, actualizado_at)"
    )

    rls.enable_tenant_rls("channel_onboarding")

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela, sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce
    # acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # **`SELECT` e mais nada para `kamba_app`**, e e a decisao do docstring: o
    # onboarding e provisionamento, e quem provisiona e o `kamba_batch`. O
    # `SELECT` existe porque o painel da loja le em que fase esta o seu canal — e
    # e isso que torna o X-03/X-04 do *gate* 6 significativo nesta tabela.
    op.execute("GRANT SELECT ON platform.channel_onboarding TO kamba_app")
    # Os quatro verbos para quem provisiona, varre os abandonados e purga
    # (KAM-071). O `DELETE` e preciso **e e usado**: a compensacao do criterio 7
    # apaga a linha de `tenant_channels` que o passo anterior criou, e
    # `kamba_app` nao tem `DELETE` em tabela nenhuma desde a `0001`.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.channel_onboarding "
        "TO kamba_batch"
    )


def downgrade() -> None:
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou, o
    # `downgrade` falha em vez de o apagar em silencio. E a regra que todas as
    # revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados, e sem copia para ficheiro.** A `0010` e a `0012`
    # recusam descer com linhas e copiam-nas para JSON; a `0015` recusa as duas
    # coisas, porque o que la esta e prova juridica. Aqui o que se perde e o
    # **registo de tentativas de onboarding**: nao e dinheiro nem prova, e as
    # tentativas vivas refazem-se (o `code` queima-se e o dono repete o *popup*).
    # O que **nao** se perde com esta revisao sao os canais: a linha de
    # `tenant_channels` e da `0001` e fica onde esta.
    #
    # **E sem repor concessoes**, pela licao que o KAM-023 mediu na `0013`: o
    # PostgreSQL remove as concessoes **com** o objecto, pelo que um `REVOKE`
    # antes do `DROP TABLE` e uma instrucao que nenhuma mutacao consegue matar —
    # e uma mutacao imortal nao e um teste em falta, e um sinal de que o codigo
    # nao faz nada.
    rls.disable_tenant_rls("channel_onboarding")
    op.execute("DROP INDEX platform.channel_onboarding_espera_idx")
    op.execute("DROP INDEX platform.channel_onboarding_janela_idx")
    op.execute("DROP INDEX platform.channel_onboarding_tenant_fase_idx")
    op.execute("DROP TABLE platform.channel_onboarding")

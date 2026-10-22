"""Coexistencia: o estado por canal da sincronizacao, dos echoes e do desligamento (KAM-017).

A primeira linha e **sem acentos**, como as dezassete revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

Uma tabela:

    channel_coexistence   o estado de coexistencia de um canal — a sincronizacao
                          das 24 h, o relogio do ultimo *echo* e o aviso de
                          inactividade (`01` §10.4 e §10.5)

## Porque e **uma** tabela e nao duas, e porque e por canal e nao por sincronizacao

A leitura imediata do bloco pede duas: uma para o *job* de sincronizacao
(criterios 3 e 4) e outra para a actividade do canal (criterio 6). Sao uma, e a
razao e que as duas perguntas tem a **mesma chave** e o mesmo tempo de vida: «o
que e que se passa com a coexistencia deste canal». A unicidade
`(tenant_id, channel_id)` da as duas de uma vez — a sincronizacao que corre uma
so vez por canal, e o relogio de inactividade que so existe enquanto o canal
estiver em coexistencia.

**E por canal e nao por tentativa de sincronizacao**, e isso e o criterio 9 a
decidir: «a reconexao `desligado → iniciado` reutiliza o ES de KAM-016 **sem
criar canal duplicado**». Com uma linha por tentativa, uma reconexao deixava
duas linhas para o mesmo canal e a pergunta «este canal ja sincronizou?» passava
a ter duas respostas. Com uma linha por canal, a reconexao **repoe** a linha que
la esta (`sincronizacao_reposta`, abaixo) e a unicidade e quem garante que nao
ha segunda.

## Os passos sao um `text[]` e nao colunas booleanas, e e o criterio 3 a mandar

«Cada passo executado uma vez; 2.ª execucao = *no-op*.» O `E1` §2 nomeia **dois**
passos — contactos e historico — e diz que cada um «so pode ser executado uma
vez». A forma que torna isso propriedade da **base** e um conjunto com a
instrucao a filtrar por ele:

    UPDATE ... SET passos_feitos = passos_feitos || $3
     WHERE ... AND NOT ($3 = ANY (passos_feitos))

Zero linhas na segunda passagem, e o *no-op* e do PostgreSQL e nao de um `if`.
Com duas colunas booleanas a propriedade era a mesma, mas o dia em que a Meta
acrescentasse um terceiro passo pedia DDL; e o `CHECK` de conteudo
(`passos_feitos <@ ARRAY[...]`) diz exactamente o mesmo que duas colunas diziam,
com o dominio num sitio so.

**O `CHECK` e de conteudo e nao de cardinalidade**: um conjunto vazio e o estado
normal no inicio, e tres elementos sao impossiveis porque os valores sao dois e
o `||` corre sob o `NOT ... = ANY`. Nao se escreveu `array_length(...) <= 2`
porque isso afirmava a mesma coisa duas vezes e a segunda podia divergir.

## O codigo 2593109 vive **aqui** e nao num registo, e foi medido

«O erro 2593109 conduz a `sincronizado_sem_historico` e **nao** a falha.»

O codigo tem **sete** digitos. A politica de *logs* da casa
(`packages/core-ts/src/logger/politica.ts`) recusa mais de **seis** digitos em
qualquer campo de texto — `DIGITOS_MAXIMOS = 6`, a regra que apanha o telefone,
o NIF e o IBAN em qualquer arrumacao — e recusa-o nos **dois** campos onde ele
caberia: no `outcome`, cuja gramatica sao palavras de letras com ate tres
digitos no fim, e no `error_code`, cujo `NUMERO` e `[0-9]{1,6}`. Mediu-se contra
o espelho Python: `validar("error_code", "2593109")` devolve `None`, e
`validar("error_code", "131049")` — seis digitos — passa.

Consequencia: **o numero nao pode ser registado**, e o que o registo leva e o
`outcome` simbolico `sincronizado_sem_historico`. O numero fica na coluna
`meta_error_code` desta tabela, que e `integer` e nao `text` justamente para nao
voltar a ser confundido com um campo de registo. A `tenant_channels`
`meta_error_codes_seen` da `0013` guarda a **lista** de codigos vistos no canal;
esta coluna guarda **o codigo que decidiu o estado desta sincronizacao**, que e
uma pergunta diferente e tem uma resposta so.

## Os quatro estados, e porque `sincronizado_sem_historico` nao e `falhado`

    a_sincronizar                 o *job* esta a correr; o prazo ainda nao caiu
    sincronizado                  os dois passos correram
    sincronizado_sem_historico    o cliente nao partilhou historico (2593109)
    falhado                       as 24 h cairam sem conclusao

O terceiro e o criterio 4 inteiro, e e **terminal e bem-sucedido**: a Meta diz
que o cliente escolheu nao partilhar, o que e uma escolha do titular e nao uma
avaria nossa. Trata-lo como `falhado` disparava o *offboard* do criterio 3 — isto
e, mandava o dono repetir o Embedded Signup — por o cliente ter exercido uma
escolha que a propria Meta lhe oferece no *popup*.

**O dominio e qualificado pela tabela** (`channel_coexistence.estado`), pela
regra da emenda 1.14: «estado» e um nome generico, e um dominio nu valia para
qualquer coluna futura com esse nome. A `tenant_channels.estado` ja tem o seu, e
sao dois dominios diferentes da mesma palavra.

## O que esta revisao **nao** acrescenta

**Nada em `tenant_channels`.** O `coexistence_synced_at` e o
`last_account_update_at` existem desde a `0001` (`db/migrations/versions/
0001_schema_platform.py:134-135`), estao no `GRANT UPDATE` por coluna que a
`0014` reescreveu por inteiro, e **nunca tiveram escritor**. Este ticket e o
primeiro a escrever-lhes, e isso nao custa DDL nenhuma: custa codigo. O
`channel_mode` e o `estado` — incluindo o valor `desligado` que o criterio 5
escreve — tambem ja la estao, com os seus `CHECK` da `0001`.

Isto repete o achado da `0017`, e pela mesma razao: a leitura do bloco do ticket
sugere colunas novas, e a da `0001` mostra que estao todas la.

## O papel que escreve e o `kamba_app`, e **nao** o `kamba_batch`

E a diferenca face a `0017`, e tem razao. O onboarding e provisionamento e corre
de retaguarda; a coexistencia corre no **caminho de um webhook** — um `echo`
chega, um `history` chega, um `account_update` chega —, e quem trata webhooks e
o `worker-canal` com o papel `kamba_app` sob RLS `FORCE`. Dar isto ao
`kamba_batch` obrigava o tratador de um webhook a mudar de papel a meio, e o
papel que trata dados de um *tenant* e o que a politica `tenant_iso` filtra.

O `kamba_batch` fica com `SELECT` e `DELETE`: le para o relatorio de
coexistencia e apaga na purga (KAM-071). **Sem `UPDATE`** — nao ha caminho de
retaguarda que altere o estado de uma sincronizacao, e dar-lhe o verbo era
abrir um que ninguem pediu.

## Dois indices

    channel_coexistence_tenant_estado_idx   (tenant_id, estado)
    channel_coexistence_prazo_idx           (estado, prazo_em)

O primeiro comeca pelo `tenant_id` **porque a RLS o le em toda a consulta** (a
licao da `0011`, onde o *gate* 8 recusou a tabela sem ele) e e a pergunta do
painel: «como esta a coexistencia dos meus canais».

O segundo e a varredura dos prazos — as 12 h e as 24 h do criterio 3, e os 10
dias do criterio 6. Nao leva `tenant_id` a frente pela razao que a `0017`
escreveu para o `channel_onboarding_espera_idx`: um prazo que caiu nao e
problema de uma loja, e a varredura pergunta pelo estado e pelo relogio. A regra
da `0001` («`tenant_id` em primeiro lugar num indice de cada tabela») fica
satisfeita pelo primeiro.

Nao ha terceiro indice para o aviso de inactividade: a varredura dos 10 dias
filtra por `estado` (so canais sincronizados) e ordena por `ultimo_echo_em`, e o
`prazo_em` do segundo indice nao lhe serve — mas a tabela tem uma linha **por
canal**, e o numero de canais do Piloto e da ordem das dezenas. Um indice que
custa escrita em todo o `echo` para poupar uma varredura de dezenas de linhas
uma vez por dia e troca errada, e fica escrito aqui para quem medir ao contrario
no dia em que houver milhares.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

#: Os quatro estados de uma sincronizacao de coexistencia.
#:
#: Os valores vem **ja entre apostrofos**: e a unica forma que o *gate* 3b
#: resolve, porque le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*. E a licao que a
#: `0015` escreveu para as finalidades do consentimento e a `0017` repetiu para
#: as fases.
ESTADOS = (
    "'a_sincronizar'",
    "'sincronizado'",
    "'sincronizado_sem_historico'",
    "'falhado'",
)

#: Os dois passos que o `E1` §2 nomeia, e que «so podem ser executados uma vez».
#:
#: Dois e nao tres: o `E1` diz «contactos e historico», e inventar um terceiro
#: passo (uma «verificacao», digamos) era pre-declarar um nome sem superficie,
#: que e o que o *gate* 3b recusa.
PASSOS = ("'contactos'", "'historico'")

#: Os seis motivos de `PARTNER_REMOVED` (`E1` §2, CONFIRMADO), em minusculas.
#:
#: **Em minusculas e nao na forma da Meta**, e a razao foi medida: estes valores
#: sao tambem `outcome` de registo, e a gramatica desse campo
#: (`packages/core-ts/src/logger/politica.ts`, `IDENTIFICADOR`) so aceita
#: minusculas. Um `PRIMARY_INACTIVITY` escrito tal e qual era recusado pelo
#: *logger*, e **em modo estrito — o do CI — o `Logger` levanta**: um desfecho
#: normal de um webhook virava excepcao nao tratada. A forma da Meta fica no
#: codigo, no mapa `MOTIVO_POR_EVENTO_META`, e converte-se na fronteira.
MOTIVOS_DE_DESLIGAMENTO = (
    "'primary_inactivity'",
    "'companion_inactivity'",
    "'business_downgrade'",
    "'change_number'",
    "'user_re_registered'",
    "'account_disconnected'",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.channel_coexistence (
            id                   uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id            uuid        NOT NULL,
            channel_id           uuid        NOT NULL,
            estado               text        NOT NULL DEFAULT 'a_sincronizar',
            -- O conjunto dos passos ja executados. Vazio no inicio; a instrucao
            -- que o estende filtra por `NOT ($n = ANY (passos_feitos))`, e e dai
            -- que sai o *no-op* da segunda execucao do criterio 3.
            passos_feitos        text[]      NOT NULL DEFAULT '{{}}'::text[],
            -- Quando o *job* arrancou, e o prazo duro das 24 h a contar dele
            -- (`E1` §2, CONFIRMADO). O prazo e **coluna e nao calculo**: o
            -- relogio dos testes e acelerado, e um prazo derivado de `now()` na
            -- consulta nao se consegue acelerar sem mexer no servidor.
            iniciado_em          timestamptz NOT NULL DEFAULT now(),
            prazo_em             timestamptz NOT NULL,
            -- Quando o alerta das 12 h saiu. Nulo e o estado normal, e e a
            -- coluna que torna o alerta idempotente: a instrucao filtra por
            -- `alertado_em IS NULL`.
            alertado_em          timestamptz,
            concluido_em         timestamptz,
            -- **Contagens e nao corpos.** O criterio 2 e explicito: «o corpo das
            -- mensagens de historico nao e persistido nem indexado no Piloto
            -- (apenas contactos e contagens)». Nao ha coluna de texto para o
            -- conteudo nesta tabela, e isso e a forma de o garantir — uma regra
            -- que depende de ninguem escrever num sitio onde da para escrever
            -- nao e uma regra.
            contactos_vistos     integer     NOT NULL DEFAULT 0,
            mensagens_vistas     integer     NOT NULL DEFAULT 0,
            -- O codigo da Meta que decidiu o estado. Hoje so o 2593109, e e
            -- `integer` de proposito: ver a nota do modulo sobre os sete
            -- digitos e a politica de *logs*.
            meta_error_code      integer,
            -- O relogio do criterio 6. Escreve-se a cada `echo` que **nao** foi
            -- nosso; o aviso dos 10 dias le-o.
            ultimo_echo_em       timestamptz,
            -- Quando o `channel.inactivity_warning` saiu. Nulo e o estado
            -- normal; repoe-se a nulo quando chega actividade do dono, que e o
            -- que faz o aviso voltar a poder sair na janela seguinte.
            avisado_em           timestamptz,
            -- Porque e que o canal se desligou, se se desligou. Um dos seis
            -- motivos do `E1` §2, em minusculas. Nulo enquanto o canal viver.
            motivo_desligamento  text,
            desligado_em         timestamptz,
            criado_at            timestamptz NOT NULL DEFAULT now(),
            actualizado_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT channel_coexistence_pkey PRIMARY KEY (id),
            -- **Uma linha por canal**, e e esta unicidade que faz o criterio 9
            -- («sem criar canal duplicado») ser propriedade da base e nao de um
            -- `if`: a reconexao repoe a linha que ja la esta.
            CONSTRAINT channel_coexistence_canal_uq UNIQUE (tenant_id, channel_id),
            CONSTRAINT channel_coexistence_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Composta com o `tenant_id`**, pela razao que a `0009` fixou e a
            -- `0011`, a `0012`, a `0014`, a `0015` e a `0017` repetiram: sem
            -- ele, a coexistencia de A podia apontar para um canal de B, e nem o
            -- *gate* 6 nem o 3b o veriam.
            CONSTRAINT channel_coexistence_channel_fk
                FOREIGN KEY (tenant_id, channel_id)
                REFERENCES platform.tenant_channels (tenant_id, id),
            CONSTRAINT channel_coexistence_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS)})),
            -- Conteudo e nao cardinalidade: ver a nota do modulo.
            CONSTRAINT channel_coexistence_passos_ck
                CHECK (passos_feitos <@ ARRAY[{", ".join(PASSOS)}]::text[]),
            -- **Sem o `IS NULL OR`**, e nao e descuido: em SQL um `NULL IN
            -- (...)` vale `NULL`, e um `CHECK` que devolve `NULL` **passa** —
            -- pelo que a forma curta ja admite o nulo. A longa dizia a mesma
            -- coisa e o *gate* 3b **nao a reconhecia**: o leitor de AST procura
            -- `CHECK (coluna IN (…))` e reportava o dominio como nao imposto. E
            -- a mesma forma que a `0013` usa para o `motivo_restricao`.
            CONSTRAINT channel_coexistence_motivo_ck
                CHECK (motivo_desligamento IN ({", ".join(MOTIVOS_DE_DESLIGAMENTO)})),
            -- O prazo e **depois** do arranque. Um prazo no passado fazia o
            -- *job* nascer vencido, e as 24 h do criterio 3 deixavam de ser as
            -- 24 h de coisa nenhuma.
            CONSTRAINT channel_coexistence_prazo_ck
                CHECK (prazo_em > iniciado_em),
            -- As contagens nao descem. Nao e zelo: a unica escrita que as move e
            -- um `+ $n` de um lote de `history`, e um valor negativo so aparece
            -- se alguem passar um lote negativo — que e defeito, e um defeito
            -- que fica visivel aqui em vez de no relatorio tres meses depois.
            CONSTRAINT channel_coexistence_contagens_ck
                CHECK (contactos_vistos >= 0 AND mensagens_vistas >= 0),
            -- Um desligamento tem **as duas** metades ou nenhuma: so com o
            -- motivo, nao se sabe quando; so com o instante, nao se sabe porque.
            CONSTRAINT channel_coexistence_desligamento_ck
                CHECK ((motivo_desligamento IS NULL) = (desligado_em IS NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.channel_coexistence IS "
        "'O estado de coexistencia de um canal (KAM-017): a sincronizacao com "
        "prazo duro de 24 h (`E1` §2, CONFIRMADO), o relogio do ultimo echo e o "
        "aviso de inactividade. Uma linha por (tenant, canal) — a unicidade e o "
        "que faz a reconexao do criterio 9 nao duplicar. Quem escreve e "
        "kamba_app, porque isto corre no caminho de um webhook e nao de "
        "retaguarda; kamba_batch le e purga.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.estado IS "
        "'Os quatro estados da sincronizacao. O sincronizado_sem_historico e "
        "**terminal e bem-sucedido**: e o erro 2593109 da Meta, que diz que o "
        "cliente escolheu nao partilhar historico. Trata-lo como falhado "
        "disparava o offboard do criterio 3 por o titular ter exercido uma "
        "escolha que o proprio popup lhe oferece. Dominio qualificado pela "
        "tabela (emenda 1.14): tenant_channels.estado tem outro, e sao dois "
        "dominios diferentes da mesma palavra.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.passos_feitos IS "
        "'Os passos ja executados, dos dois que o `E1` §2 nomeia. Cada passo so "
        "pode correr uma vez (CONFIRMADO), e quem o impoe e a instrucao: "
        "UPDATE ... SET passos_feitos = passos_feitos || $n WHERE NOT ($n = ANY "
        "(passos_feitos)). Zero linhas na segunda passagem — o no-op do criterio "
        "3 e do PostgreSQL e nao de um if.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.meta_error_code IS "
        "'O codigo da Meta que decidiu o estado — hoje so o 2593109. E integer e "
        "nao text porque **nao pode ser registado**: tem sete digitos, e a "
        "politica de logs da casa recusa mais de seis em qualquer campo de texto "
        "(DIGITOS_MAXIMOS), nos dois campos onde caberia (outcome e error_code). "
        "O que vai ao registo e o outcome simbolico sincronizado_sem_historico. "
        "Diferente de tenant_channels.meta_error_codes_seen, que e a lista de "
        "codigos vistos no canal: esta coluna e o codigo desta sincronizacao.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.mensagens_vistas IS "
        "'**Uma contagem, nunca um corpo.** O criterio 2 proibe persistir ou "
        "indexar o corpo das mensagens de historico no Piloto, e a base legal "
        "para o usar e parecer por dar (KAM-104). Nao ha coluna de texto para "
        "conteudo nesta tabela, e e essa a forma de garantir a regra: uma regra "
        "que depende de ninguem escrever onde da para escrever nao e uma regra.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.ultimo_echo_em IS "
        "'Quando chegou o ultimo echo que **nao** foi nosso — isto e, cujo wamid "
        "nao consta de outbound_messages. E o relogio do aviso preventivo dos 10 "
        "dias do criterio 6 (heuristica do `01` §10.5). A outra metade da "
        "heuristica — «sem acesso ao painel» — nao se mede: nao ha painel, e "
        "inventar um sinal era inventar evidencia.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.channel_coexistence.motivo_desligamento IS "
        "'Um dos seis motivos de PARTNER_REMOVED (`E1` §2, CONFIRMADO), **em "
        "minusculas**. A forma da Meta e MAIUSCULA e converte-se na fronteira "
        "(MOTIVO_POR_EVENTO_META), porque estes valores sao tambem outcome de "
        "registo e a gramatica desse campo so aceita minusculas — em modo "
        "estrito o Logger levanta, e um desfecho normal de webhook virava "
        "excepcao nao tratada. E a licao que o sem_humano_24h do KAM-018 pagou.'"
    )

    # O indice do painel: `tenant_id` primeiro **porque a RLS o le em toda a
    # consulta** (a licao da `0011`). Satisfaz tambem a regra da `0001`.
    op.execute(
        "CREATE INDEX channel_coexistence_tenant_estado_idx "
        "ON platform.channel_coexistence (tenant_id, estado)"
    )
    # A varredura dos prazos — 12 h e 24 h do criterio 3. Sem `tenant_id` a
    # frente pela razao que a `0017` escreveu para o `espera_idx`: um prazo que
    # caiu nao e problema de uma loja.
    op.execute(
        "CREATE INDEX channel_coexistence_prazo_idx "
        "ON platform.channel_coexistence (estado, prazo_em)"
    )

    rls.enable_tenant_rls("channel_coexistence")

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela, sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce
    # acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # **`kamba_app` escreve**, e e a diferenca face a `0017`: a coexistencia
    # corre no caminho de um webhook, e quem trata webhooks e o `worker-canal`
    # sob RLS `FORCE`. Sem `DELETE`, pela regra da `0001`: «soft delete: estado,
    # nunca DELETE».
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON platform.channel_coexistence TO kamba_app"
    )
    # Le para o relatorio e apaga na purga (KAM-071). **Sem `UPDATE`**: nao ha
    # caminho de retaguarda que altere o estado de uma sincronizacao, e dar-lhe
    # o verbo era abrir um que ninguem pediu.
    op.execute(
        "GRANT SELECT, DELETE ON platform.channel_coexistence TO kamba_batch"
    )


def downgrade() -> None:
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou, o
    # `downgrade` falha em vez de o apagar em silencio. E a regra que todas as
    # revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados.** A `0010` e a `0012` recusam descer com linhas e
    # copiam-nas para JSON; a `0015` recusa as duas coisas, porque o que la esta
    # e prova juridica. Aqui o que se perde e o **estado de uma sincronizacao**:
    # nao e dinheiro nem prova, e uma sincronizacao perdida refaz-se — o dono
    # repete o Embedded Signup, que e exactamente o que o prazo das 24 h ja manda
    # fazer quando ele cai. O que **nao** se perde sao os canais: a linha de
    # `tenant_channels` e da `0001` e fica onde esta, e o
    # `coexistence_synced_at` que este ticket lhe escreve tambem.
    #
    # **E sem repor concessoes**, pela licao que o KAM-023 mediu na `0013`: o
    # PostgreSQL remove as concessoes **com** o objecto, pelo que um `REVOKE`
    # antes do `DROP TABLE` e uma instrucao que nenhuma mutacao consegue matar —
    # e uma mutacao imortal nao e um teste em falta, e um sinal de que o codigo
    # nao faz nada.
    rls.disable_tenant_rls("channel_coexistence")
    op.execute("DROP INDEX platform.channel_coexistence_prazo_idx")
    op.execute("DROP INDEX platform.channel_coexistence_tenant_estado_idx")
    op.execute("DROP TABLE platform.channel_coexistence")

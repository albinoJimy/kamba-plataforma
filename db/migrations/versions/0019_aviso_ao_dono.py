"""KAM-115: o aviso ao dono por canal alternativo.

Duas tabelas: `owner_contacts`, o endereco alternativo do dono, cifrado e com
prova de verificacao; e `owner_notices`, o registo de cada aviso enviado, **sem
corpo**.

## Porque e que sao duas e nao uma

O criterio 7 manda que uma falha de entrega «marque o contacto como invalido».
Isso e uma **escrita no contacto** e nao no aviso: o aviso que falhou fica
`falhado`, e o endereco fica inutilizavel para os avisos seguintes. Com uma
tabela so, a invalidacao tinha de viver na ultima linha de aviso — e a pergunta
«este dono tem contacto valido?» passava a ser uma consulta sobre o historico de
envios em vez de um facto.

## O endereco do dono vive **cifrado**, e nao ha coluna em claro

E o DoD «Privacidade» do ticket: «endereco do dono so em cifra e nunca em logs».
A cifra e a do `packages/core-ts/src/onboarding/cifra.ts` (AES-256-GCM, DEK por
tenant derivada por HKDF de uma KEK do cofre, `kid` dentro do criptograma) e
**nao se reescreveu nada**: o que muda e a KEK, que e a entrada nova
`kek_contacto_dono` do `ops/secrets-inventory.yaml`. Duas KEK diferentes dao
duas DEK diferentes para o mesmo tenant, pelo que uma cifra de *token* de
cliente nao abre como endereco e vice-versa — e a separacao de dominio sai da
chave em vez de sair de uma constante que alguem pode esquecer de mudar.

**Nao ha HMAC de pesquisa**, ao contrario do `contact_endpoints` do KAM-008. La
ha pesquisa por valor (chega um telefone num *webhook* e e preciso achar o
contacto); aqui nao: entra-se sempre pelo `tenant_id`, que e quem tem o aviso
para mandar. Um HMAC sem quem o consulte era uma chave a mais para guardar e
rodar, e o `docs/identidade.md` §8 ja escreveu que pseudonimizacao nao e
anonimizacao.

## A verificacao e por ligacao, e o que esta tabela guarda e o **resumo** do
## segredo

O criterio 6 pede «≥ 1 contacto alternativo verificado por ligacao de
confirmacao». O que se guarda e `sha256` do *token* da ligacao e nao o *token*:
quem leia a base nao consegue confirmar um endereco por ele. **Sem chave**, e
isto e diferente do `contact_endpoints`: um *token* de 32 octetos do gerador do
sistema nao se enumera, pelo que um resumo simples basta — o que obriga a HMAC
no KAM-008 e o espaco dos numeros angolanos ter poucos milhoes de elementos, nao
o resumo ser fraco.

**Quem manda a ligacao e o KAM-086**, que e quem capta o e-mail (o criterio
di-lo). Este ticket emite o *token*, guarda-lhe o resumo, poe-lhe prazo e
confirma-o; a mensagem que leva a ligacao ao dono e do outro ticket, e dizer isto
e melhor do que construir um segundo caminho de e-mail que depois teria de ser
reconciliado com o dele.

## `owner_notices` nao tem coluna de corpo, e e assim que a regra se garante

Os *Detalhes Tecnicos* dizem «com RLS e sem corpo». O mesmo argumento que a
`0018` escreveu para as contagens do historico: uma regra que depende de ninguem
escrever num sitio onde da para escrever nao e uma regra. O que se registou e
**qual** o modelo que saiu (pelo `gatilho`, que o escolhe), para quem, por que
canal e com que desfecho — nunca o texto.

## A idempotencia e a `chave`, e os lembretes sao o `lembrete`

O criterio 2 quer «o mesmo evento 3x produz 1 aviso»; o criterio 4 quer
«lembretes as 24 h e 72 h se o estado persiste». As duas coisas vivem na mesma
unicidade e nao se contradizem: a `chave` e o resumo de `(tenant, gatilho,
episodio)` — o mesmo episodio da sempre a mesma chave — e o `lembrete` e a ordem
do lembrete, `0` para o aviso proprio, `1` para as 24 h e `2` para as 72 h. A
unicidade e `(tenant_id, chave, lembrete, canal)`, e dela saem as duas
propriedades de uma vez:

* tres entregas do mesmo evento tentam escrever a **mesma** linha, e o
  `ON CONFLICT DO NOTHING` deixa uma;
* um novo episodio depois de resolvido tem **outro** `episodio`, logo outra
  chave, logo outra linha — que e a segunda metade do criterio 2;
* e o lembrete das 24 h nao colide com o aviso de que e lembrete.

O `lembrete <= 2` no `CHECK` e o «depois para» do criterio 4. **A base recusa um
quarto aviso do mesmo episodio**, e isso nao e zelo: a regra de parar e a parte
do limite que protege o dono de nos, e deixa-la so no codigo era deixa-la ao
alcance do primeiro `if` mal escrito.

## O que esta revisao **nao** faz

Nao toca em `tenants` nem em `tenant_channels`. O contacto alternativo nao e uma
coluna de `tenants` — tentou-se, e o que a desaconselha e o `GRANT UPDATE` por
coluna dessa tabela: o `estado` saiu de `kamba_app` na emenda 1.18 porque o
sujeito de uma condicao nao pode ser quem a retira, e meter aqui duas colunas
novas obrigava a reabrir essa lista. Uma tabela propria tem a sua RLS, a sua
unicidade e os seus privilegios, e nao mexe no que a `0007` fechou.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

#: Os cinco gatilhos do criterio 1, **ja entre apostrofos**.
#:
#: A forma com apostrofos e a unica que o *gate* 3b resolve: ele le o AST da
#: revisao sem a executar e segue `", ".join(<constante de modulo>)` dentro de
#: uma *f-string*. E a licao que a `0015` escreveu e a `0017` e a `0018`
#: repetiram.
#:
#: **Cinco e nao seis**, e os nomes nao sao os dos eventos que os provocam. O
#: criterio enumera cinco situacoes e duas delas chegam pelo mesmo tipo de evento
#: (`channel.updated` com `desligado`, e o `restrito` por qualidade), pelo que o
#: gatilho e a **situacao** e nao o tipo. Quem traduz um evento num gatilho e o
#: `avisos/decisao.ts`, e «um gatilho fora da lista nao envia nada» e esta lista
#: a ser fechada nos dois lados.
#:
#: **Em minusculas e sem acentos**, e a razao e a mesma que a `0018` mediu: estes
#: valores sao tambem `outcome` de linha de registo, e o `IDENTIFICADOR` do
#: `packages/core-ts/src/logger/politica.ts` so aceita minusculas — **em modo
#: estrito, que e o do CI, o `Logger` levanta**. Um `indisponivel` com acento
#: seria recusado, e um aviso perfeitamente normal virava excepcao nao tratada.
GATILHOS = (
    "'canal_desligado'",
    "'inactividade'",
    "'qualidade_restrita'",
    "'sem_pagamento'",
    "'painel_indisponivel'",
)

#: Os canais por onde um aviso sai: **e-mail e painel**.
#:
#: Dois, e o WhatsApp **nao esta aqui** — nem podia: o ticket chama-se «por canal
#: alternativo» porque avisar o dono pelo canal que falhou e inutil, e o criterio
#: 8 pede um teste de configuracao a prova-lo. O `sms` nao esta pre-declarado,
#: porque o adaptador e o KAM-116 e um nome sem superficie e o que o *gate* 3b
#: recusa.
CANAIS_DE_AVISO = ("'email'", "'painel'")

#: O canal de um contacto alternativo: hoje so o **e-mail**.
#:
#: Dominio **qualificado pela coluna** e diferente do `owner_notices.canal`, pela
#: regra da emenda 1.14 — sao dois dominios da mesma palavra, e o do contacto e
#: mais pequeno: o painel e um canal por onde o aviso sai mas **nao tem
#: endereco**, pelo que nao ha contacto a guardar. Um valor so, com o precedente
#: do `consent_event.canal IN ('whatsapp')` da `0015`.
CANAIS_DE_CONTACTO = ("'email'",)

#: Os tres estados de um aviso.
#:
#: Nao ha `suprimido`. Um aviso recusado por um limite de frequencia **nao
#: escreve linha**: escrever uma era inventar um aviso que nao houve, e a
#: pergunta «quantos avisos levou este dono hoje?» — que e o proprio limite —
#: passava a ter de distinguir os que contam dos que nao contam. O que se recusou
#: **conta-se**, em `owner_notice_suppressed_total{gatilho,motivo}`.
ESTADOS_DE_AVISO = ("'pendente'", "'entregue'", "'falhado'")

#: Porque e que um aviso falhou.
#:
#: Os dois primeiros sao os do criterio 7 («*bounce*, rejeicao»); o
#: `sem_contacto` e o criterio 6 a encontrar um tenant `ativo` sem endereco
#: verificado; o `indisponivel` e o fornecedor em baixo. **Quatro e nao tres**: um
#: `sem_contacto` tratado como `bounce` marcava como invalido um endereco que nao
#: existe.
MOTIVOS_DE_FALHA = ("'bounce'", "'rejeitado'", "'sem_contacto'", "'indisponivel'")

#: Porque e que um contacto ficou invalido. Os dois do criterio 7.
MOTIVOS_DE_INVALIDEZ = ("'bounce'", "'rejeitado'")

#: O ultimo lembrete que a base aceita: o das 72 h.
#:
#: `0` e o aviso proprio, `1` as 24 h, `2` as 72 h. O «depois para» do criterio 4
#: e este numero, e esta no `CHECK` e nao so no codigo pela razao da nota do
#: modulo.
LEMBRETE_MAXIMO = 2

#: As colunas de `owner_notices` que `kamba_app` pode alterar.
#:
#: **O desfecho, e nada mais.** Nem a `chave`, nem o `gatilho`, nem o `episodio`,
#: nem o `lembrete`, nem o `canal`: mover qualquer um deles era fazer um aviso
#: passar por outro e a unicidade deixava de significar o que significa. O
#: `criado_at` fica de fora porque e registo, e o `tenant_id` pela regra de
#: sempre.
COLUNAS_DE_AVISO_QUE_A_APP_ALTERA = (
    "estado, entregue_at, falha_motivo, tentativas, actualizado_at"
)

#: As colunas de `owner_contacts` que `kamba_app` pode alterar.
#:
#: O `endereco_enc` **esta aqui** e o `canal` nao: trocar o endereco e o que o
#: dono faz quando muda de e-mail (KAM-086 escreve-o por este papel), e trocar o
#: canal era transformar um e-mail num painel. A verificacao e a invalidacao sao
#: as duas escritas deste ticket.
COLUNAS_DE_CONTACTO_QUE_A_APP_ALTERA = (
    "endereco_enc, verificado_at, confirmacao_hash, confirmacao_expira_em,\n"
    "                 invalido_at, motivo_invalido, actualizado_at"
)


def upgrade() -> None:
    # ------------------------------------------------------- owner_contacts
    op.execute(
        f"""
        CREATE TABLE platform.owner_contacts (
            id                     uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id              uuid        NOT NULL,
            canal                  text        NOT NULL DEFAULT 'email',
            -- **Cifrado, e nao ha coluna em claro.** Ver a nota do modulo: e a
            -- cifra do `onboarding/cifra.ts` com a KEK `kek_contacto_dono`, e o
            -- `kid` vai dentro do criptograma para a rotacao da KEK nao tornar
            -- ilegivel o que ja esta escrito.
            endereco_enc           bytea       NOT NULL,
            -- Nulo enquanto a ligacao de confirmacao nao for seguida, e e isso
            -- que o criterio 6 chama «verificado». Um endereco nao verificado
            -- **nao recebe avisos**: quem o decide e o predicado da consulta.
            verificado_at          timestamptz,
            -- `sha256` do *token* da ligacao, nunca o *token*. Sem chave, pela
            -- razao da nota do modulo: 32 octetos do gerador do sistema nao se
            -- enumeram.
            confirmacao_hash       bytea,
            confirmacao_expira_em  timestamptz,
            -- Quando uma entrega falhou de forma que condena o endereco
            -- (criterio 7). Nulo e o estado normal.
            invalido_at            timestamptz,
            motivo_invalido        text,
            criado_at              timestamptz NOT NULL DEFAULT now(),
            actualizado_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT owner_contacts_pkey PRIMARY KEY (id),
            -- **Um endereco por (tenant, canal).** O criterio 6 pede «≥ 1», que
            -- e um minimo e nao um numero: com varios por canal, a pergunta
            -- «para onde vai o aviso?» passava a ter de escolher, e escolher
            -- entre dois e-mails do mesmo dono nao e decisao que um aviso de
            -- avaria deva tomar. O KAM-116 acrescenta uma **linha** com
            -- `canal = 'sms'`, nao uma coluna.
            CONSTRAINT owner_contacts_canal_uq UNIQUE (tenant_id, canal),
            CONSTRAINT owner_contacts_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT owner_contacts_canal_ck
                CHECK (canal IN ({", ".join(CANAIS_DE_CONTACTO)})),
            -- Sem o `IS NULL OR`: em SQL um `NULL IN (...)` vale `NULL` e um
            -- `CHECK` que devolve `NULL` **passa**, pelo que a forma curta ja
            -- admite o nulo — e e a unica que o *gate* 3b reconhece como
            -- dominio imposto (a licao da `0018`).
            CONSTRAINT owner_contacts_motivo_ck
                CHECK (motivo_invalido IN ({", ".join(MOTIVOS_DE_INVALIDEZ)})),
            -- Uma invalidacao tem **as duas** metades ou nenhuma: so com o
            -- motivo nao se sabe quando, so com o instante nao se sabe porque.
            -- E a forma do `channel_coexistence_desligamento_ck` da `0018`.
            CONSTRAINT owner_contacts_invalidez_ck
                CHECK ((motivo_invalido IS NULL) = (invalido_at IS NULL)),
            -- Um resumo de confirmacao sem prazo era uma ligacao eterna, e um
            -- prazo sem resumo era um prazo de nada.
            CONSTRAINT owner_contacts_confirmacao_ck
                CHECK ((confirmacao_hash IS NULL) = (confirmacao_expira_em IS NULL)),
            -- `sha256` tem 32 octetos. Um resumo mais curto e um resumo de outra
            -- coisa, e o sitio de o dizer e aqui: a coluna e `bytea` e `bytea`
            -- aceita qualquer comprimento.
            CONSTRAINT owner_contacts_hash_ck
                CHECK (confirmacao_hash IS NULL OR octet_length(confirmacao_hash) = 32),
            -- Um endereco cifrado tem, no minimo, versao, `kid`, IV e etiqueta.
            -- Trinta octetos nao e o comprimento certo de nada — e o piso que
            -- distingue um criptograma de um campo preenchido com lixo curto.
            CONSTRAINT owner_contacts_enc_ck
                CHECK (octet_length(endereco_enc) >= 30)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.owner_contacts IS "
        "'O endereco alternativo do dono (KAM-115): por onde se avisa quando o "
        "canal de WhatsApp falhou. Uma linha por (tenant, canal), e hoje o unico "
        "canal com endereco e o e-mail — o painel nao tem endereco e o sms e o "
        "KAM-116. O endereco vive **cifrado** (AES-256-GCM, DEK por tenant "
        "derivada da KEK kek_contacto_dono) e nunca em claro nem em logs: e o DoD "
        "Privacidade do ticket. Quem capta o e-mail e o KAM-086; este ticket "
        "verifica-o, usa-o e invalida-o.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_contacts.endereco_enc IS "
        "'O endereco, cifrado com a cifra do onboarding/cifra.ts e a KEK "
        "kek_contacto_dono. **Nao existe coluna em claro**, e e assim que a regra "
        "se garante: uma regra que depende de ninguem escrever onde da para "
        "escrever nao e uma regra. Nao ha HMAC de pesquisa porque nao ha pesquisa "
        "por valor — entra-se sempre pelo tenant_id, que e quem tem o aviso para "
        "mandar; um HMAC sem consumidor era uma chave a mais para rodar.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_contacts.verificado_at IS "
        "'Quando a ligacao de confirmacao foi seguida. Nulo e o estado normal de "
        "um endereco acabado de captar, e um endereco nao verificado **nao recebe "
        "avisos** — quem o impoe e o predicado da consulta e nao um if. Um tenant "
        "ativo sem nenhum endereco verificado conta em owner_alt_contact_missing "
        "e abre tarefa a T2 (criterio 6).'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_contacts.confirmacao_hash IS "
        "'sha256 do token da ligacao de confirmacao, nunca o token. Sem chave, ao "
        "contrario dos *_hmac do KAM-008: o que obriga a HMAC la e o espaco dos "
        "numeros angolanos ter poucos milhoes de elementos, e um token de 32 "
        "octetos do gerador do sistema nao se enumera. Quem entrega a ligacao ao "
        "dono e o KAM-086, que e quem capta o e-mail.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_contacts.invalido_at IS "
        "'Quando uma entrega falhou de forma que condena o endereco — bounce ou "
        "rejeicao (criterio 7). O aviso seguinte tenta o painel e abre tarefa a "
        "T2; nenhum aviso se perde em silencio. E facto do contacto e nao do "
        "aviso, e e por isso que sao duas tabelas: com uma so, a pergunta «este "
        "dono tem contacto valido?» era uma consulta sobre o historico de "
        "envios.'"
    )

    # O caminho do aviso: do tenant para o endereco valido e verificado. O
    # `tenant_id` primeiro **porque a RLS o le em toda a consulta** (a licao da
    # `0011`), e satisfaz tambem a regra da `0001`.
    op.execute(
        "CREATE INDEX owner_contacts_tenant_canal_idx "
        "ON platform.owner_contacts (tenant_id, canal)"
    )
    # A varredura do criterio 6: tenants `ativo` sem endereco verificado. Parcial
    # e **sem `tenant_id` a frente**, pela razao que a `0017` escreveu para o
    # `espera_idx` e a `0018` repetiu: um dono sem contacto nao e problema de uma
    # loja, e o indice cheio seria quase todo entradas que a consulta nao quer.
    op.execute(
        "CREATE INDEX owner_contacts_verificado_idx "
        "ON platform.owner_contacts (canal, verificado_at) "
        "WHERE verificado_at IS NOT NULL AND invalido_at IS NULL"
    )

    rls.enable_tenant_rls("owner_contacts")

    # -------------------------------------------------------- owner_notices
    op.execute(
        f"""
        CREATE TABLE platform.owner_notices (
            id              uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       uuid        NOT NULL,
            gatilho         text        NOT NULL,
            -- O episodio: o que distingue «o canal caiu outra vez» de «o canal
            -- caiu». E **texto e nao uuid** porque quem o cunha e quem conhece o
            -- episodio: um desligamento e o `channel_id` com o motivo, uma
            -- restricao de qualidade e a `event_key` da Meta. Opaco para esta
            -- tabela, e e dele que sai a `chave`.
            episodio        text        NOT NULL,
            -- `sha256(tenant ‖ gatilho ‖ episodio)`. Redundante com as tres
            -- colunas de proposito: e sobre ela que a unicidade se faz, e um
            -- resumo de comprimento fixo nao se parte com um `episodio` de 300
            -- caracteres que um indice de texto nao aguentava.
            chave           bytea       NOT NULL,
            -- `0` o aviso, `1` as 24 h, `2` as 72 h. Ver a nota do modulo: e com
            -- esta coluna que a idempotencia do criterio 2 e os lembretes do
            -- criterio 4 cabem na mesma unicidade.
            lembrete        smallint    NOT NULL DEFAULT 0,
            canal           text        NOT NULL,
            estado          text        NOT NULL DEFAULT 'pendente',
            -- Quantas vezes se tentou entregar **este** aviso. Nao e o limite de
            -- frequencia (esse conta avisos, nao tentativas): e o que torna
            -- visivel um fornecedor a devolver erro transitorio em serie.
            tentativas      smallint    NOT NULL DEFAULT 0,
            falha_motivo    text,
            criado_at       timestamptz NOT NULL DEFAULT now(),
            entregue_at     timestamptz,
            actualizado_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT owner_notices_pkey PRIMARY KEY (id),
            -- **A idempotencia do criterio 2, e os lembretes do criterio 4.**
            -- Tres entregas do mesmo evento tentam escrever esta mesma linha e o
            -- `ON CONFLICT DO NOTHING` deixa uma; um episodio novo tem outra
            -- chave; e o lembrete das 24 h nao colide com o aviso de que e
            -- lembrete.
            CONSTRAINT owner_notices_idempotencia_uq
                UNIQUE (tenant_id, chave, lembrete, canal),
            CONSTRAINT owner_notices_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT owner_notices_gatilho_ck
                CHECK (gatilho IN ({", ".join(GATILHOS)})),
            CONSTRAINT owner_notices_canal_ck
                CHECK (canal IN ({", ".join(CANAIS_DE_AVISO)})),
            CONSTRAINT owner_notices_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DE_AVISO)})),
            CONSTRAINT owner_notices_falha_ck
                CHECK (falha_motivo IN ({", ".join(MOTIVOS_DE_FALHA)})),
            -- O «depois para» do criterio 4, na base. Ver a nota do modulo:
            -- deixa-lo so no codigo era deixa-lo ao alcance do primeiro `if` mal
            -- escrito, e a regra de parar e a parte do limite que protege o dono
            -- de nos.
            CONSTRAINT owner_notices_lembrete_ck
                CHECK (lembrete BETWEEN 0 AND {LEMBRETE_MAXIMO}),
            CONSTRAINT owner_notices_tentativas_ck
                CHECK (tentativas >= 0),
            -- Os dois desfechos e as suas provas, e as duas em `=` e nao em
            -- `->`: um aviso `entregue` sem instante de entrega era um aviso que
            -- se diz entregue e nao sabe quando, e um `entregue_at` num aviso
            -- `pendente` era o contrario.
            CONSTRAINT owner_notices_entrega_ck
                CHECK ((estado = 'entregue') = (entregue_at IS NOT NULL)),
            CONSTRAINT owner_notices_motivo_ck
                CHECK ((estado = 'falhado') = (falha_motivo IS NOT NULL)),
            -- O episodio nao e vazio. Um `episodio` vazio punha todos os avisos
            -- do mesmo gatilho na mesma chave, e o segundo episodio de um tenant
            -- deixava de ser avisado para sempre — o pior defeito possivel neste
            -- modulo, porque e silencioso.
            CONSTRAINT owner_notices_episodio_ck
                CHECK (length(episodio) > 0),
            -- `sha256` tem 32 octetos, como no `owner_contacts`.
            CONSTRAINT owner_notices_chave_ck
                CHECK (octet_length(chave) = 32)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.owner_notices IS "
        "'O registo de cada aviso ao dono (KAM-115), **sem corpo**. Os Detalhes "
        "Tecnicos do ticket pedem RLS e nenhum corpo, e nao haver coluna de texto "
        "e a forma de o garantir — o mesmo argumento que a 0018 escreveu para as "
        "contagens do historico. Guarda qual o gatilho, qual o episodio, por que "
        "canal, com que desfecho e em que lembrete; nunca o texto que saiu. A "
        "unicidade (tenant_id, chave, lembrete, canal) e a idempotencia do "
        "criterio 2 e os lembretes do criterio 4 ao mesmo tempo.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_notices.gatilho IS "
        "'Um dos cinco do criterio 1, e um gatilho fora da lista nao envia nada — "
        "a lista e fechada nos dois lados, aqui e no avisos/contrato.ts. Cinco e "
        "nao seis: o gatilho e a **situacao** e nao o tipo de evento, e duas das "
        "cinco chegam pelo mesmo channel.updated. Em minusculas e sem acentos "
        "porque sao tambem outcome de linha de registo, e em modo estrito o "
        "Logger levanta um valor que a gramatica recuse — a licao que o "
        "sem_humano_24h do KAM-018 pagou e a 0018 repetiu.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_notices.episodio IS "
        "'O que distingue «o canal caiu outra vez» de «o canal caiu». Texto "
        "opaco, cunhado por quem conhece o episodio: o channel_id com o motivo "
        "num desligamento, a event_key da Meta numa restricao de qualidade. Nao "
        "pode ser vazio: um episodio vazio punha todos os avisos do mesmo gatilho "
        "na mesma chave e o segundo episodio de um tenant nunca mais era avisado "
        "— um defeito silencioso.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_notices.lembrete IS "
        "'0 o aviso proprio, 1 o lembrete das 24 h, 2 o das 72 h (criterio 4). O "
        "CHECK de 0 a 2 e o «depois para» do criterio, **na base**: a regra de "
        "parar e a parte do limite que protege o dono de nos, e deixa-la so no "
        "codigo era deixa-la ao alcance do primeiro if mal escrito. Depois do 2 "
        "abre-se tarefa a T2 em vez de insistir.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.owner_notices.estado IS "
        "'Tres estados, e **nao ha suprimido**: um aviso recusado por um limite "
        "de frequencia nao escreve linha. Escrever uma era inventar um aviso que "
        "nao houve, e a pergunta «quantos avisos levou este dono hoje?» — que e o "
        "proprio limite — passava a ter de distinguir os que contam dos que nao "
        "contam. O que se recusou conta-se em owner_notice_suppressed_total.'"
    )

    # Os dois limites do criterio 4, e sao dois indices porque sao duas
    # consultas: «quantos avisos deste gatilho nas ultimas 24 h?» e «quantos
    # avisos deste tenant hoje?». O segundo nao se serve do primeiro — um
    # intervalo sobre o `criado_at` nao usa um indice onde ele vem depois de uma
    # igualdade que a consulta nao tem.
    op.execute(
        "CREATE INDEX owner_notices_tenant_gatilho_idx "
        "ON platform.owner_notices (tenant_id, gatilho, criado_at DESC)"
    )
    op.execute(
        "CREATE INDEX owner_notices_tenant_criado_idx "
        "ON platform.owner_notices (tenant_id, criado_at DESC)"
    )
    # A varredura dos lembretes das 24 h e das 72 h, e a dos avisos que ficaram
    # `pendente` com o fornecedor em baixo. Parcial, e sem `tenant_id` a frente
    # pela razao dos outros indices de varredura desta casa.
    op.execute(
        "CREATE INDEX owner_notices_pendentes_idx "
        "ON platform.owner_notices (estado, criado_at) "
        "WHERE estado <> 'entregue'"
    )

    rls.enable_tenant_rls("owner_notices")

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela, sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce
    # acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # **`kamba_app` escreve as duas**, e o `UPDATE` e **por coluna**: a licao que
    # a revisao adversarial da `0018` mediu duas vezes — um `UPDATE` ao nivel da
    # tabela deixava mover um aviso para outro tenant **e** tornava o
    # `test_privilegios_por_coluna_nas_tabelas_com_matriz` vacuo, porque ele
    # compara `de_tabela or coluna in por_coluna` e o `or` curto-circuita.
    #
    # Sem `DELETE` para a aplicacao, pela regra da `0001`: «soft delete: estado,
    # nunca DELETE».
    op.execute("GRANT SELECT, INSERT ON platform.owner_notices TO kamba_app")
    op.execute(
        f"""
        GRANT UPDATE ({COLUNAS_DE_AVISO_QUE_A_APP_ALTERA})
          ON platform.owner_notices TO kamba_app
        """
    )
    op.execute("GRANT SELECT, INSERT ON platform.owner_contacts TO kamba_app")
    op.execute(
        f"""
        GRANT UPDATE ({COLUNAS_DE_CONTACTO_QUE_A_APP_ALTERA})
          ON platform.owner_contacts TO kamba_app
        """
    )
    # **`kamba_batch` precisa dos tres verbos, e isto e o achado que a `0018`
    # pagou para nao se repetir aqui.** Tres caminhos de retaguarda alteram estas
    # tabelas, e os tres correm **sem `tenant_id` no predicado**: os lembretes
    # das 24 h e das 72 h, a varredura dos tenants `ativo` sem contacto
    # verificado (criterio 6) e a dos avisos que ficaram `pendente`. Um `UPDATE`
    # sem contexto de tenant so corre com `BYPASSRLS`, e o unico papel que o tem
    # e este (`db/bootstrap.py`). Sem estas concessoes os criterios 4 e 6 nao
    # tinham caminho executavel — so decisao escrita.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON platform.owner_notices TO kamba_batch")
    op.execute("GRANT SELECT, UPDATE, DELETE ON platform.owner_contacts TO kamba_batch")


def downgrade() -> None:
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou, o
    # `downgrade` falha em vez de o apagar em silencio. E a regra que todas as
    # revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados**, ao contrario da `0015`. O que aqui se perde e o
    # historico de avisos e um endereco que o dono volta a dar: nao e prova
    # juridica como o consentimento, e um aviso perdido nao desfaz o aviso — ele
    # foi entregue. O que se perde de facto e a **idempotencia**: descer e subir
    # faz o episodio em curso poder ser avisado outra vez. Fica dito, e e preco
    # aceitavel num `downgrade`, que e caminho de emergencia e nao de operacao.
    #
    # **E sem repor concessoes**, pela licao que o KAM-023 mediu na `0013`: o
    # PostgreSQL remove-as **com** o objecto, pelo que um `REVOKE` antes do `DROP
    # TABLE` e uma instrucao que nenhuma mutacao consegue matar — e uma mutacao
    # imortal nao e um teste em falta, e um sinal de que o codigo nao faz nada.
    #
    # A ordem e a inversa da subida, e aqui isso **tem** consequencia: as duas
    # tabelas nao se referenciam uma a outra (as duas apontam para `tenants`),
    # pelo que qualquer ordem funcionaria — e e por isso que se escolhe a inversa,
    # para nao haver uma segunda regra a decorar.
    rls.disable_tenant_rls("owner_notices")
    op.execute("DROP INDEX platform.owner_notices_pendentes_idx")
    op.execute("DROP INDEX platform.owner_notices_tenant_criado_idx")
    op.execute("DROP INDEX platform.owner_notices_tenant_gatilho_idx")
    op.execute("DROP TABLE platform.owner_notices")

    rls.disable_tenant_rls("owner_contacts")
    op.execute("DROP INDEX platform.owner_contacts_verificado_idx")
    op.execute("DROP INDEX platform.owner_contacts_tenant_canal_idx")
    op.execute("DROP TABLE platform.owner_contacts")

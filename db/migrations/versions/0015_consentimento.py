"""Consentimento no primeiro contacto: a prova e o texto versionado (KAM-022).

A primeira linha e **sem acentos**, como as catorze revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

Duas tabelas e **a primeira vista do esquema**:

    consent_event      a prova, append-only (DDL de referencia: `10` §7.2)
    consent_texts      o texto do aviso, versionado e de plataforma
    consent_actual     o ultimo estado por (tenant, contacto, finalidade)

## O `id` e `uuid` e nao `bigint` de identidade, contra o `10` §7.2

Aquele DDL escreve `bigint GENERATED ALWAYS AS IDENTITY`, e **nao se segue**. A
regra do dicionario §2 e `uuid` para a coluna que identifica, e o
`test_as_colunas_de_identidade_sao_as_tres_declaradas` prende-a com **tres**
excepcoes escritas — o `events_outbox`, a `events_dlq` e o `audit_log` —, todas
com a mesma propriedade: **nenhum papel sujeito a RLS le a coluna**. Uma chave
sequencial vaza volume ao vizinho, e e so isso que aquela propriedade dispensa.

A `consent_event` **nao** tem essa propriedade: o `kamba_app` **le-a**, porque o
`ConsentGate` pergunta pelo estado antes de decidir. Com um `id` sequencial, esse
papel media quantos consentimentos tem a plataforma inteira — e, pela cadencia,
quantos clientes novos ela ve por dia. E a mesma razao que poe o
`inbound_events` da `0008`, a `conversations` da `0009`, a `outbound_messages` da
`0010` e o `channel_quality_log` da `0014` em `uuid` aleatorio.

**E a vista paga por isso, e o preco esta medido.** Um `uuid` de versao 4 nao
ordena por nada, pelo que o `DISTINCT ON` precisa de uma ordem que venha das
colunas. A primeira versao desta revisao usou `ocorrido_em DESC, id DESC` e
afirmou que «um empate no `ocorrido_em` e impossivel dentro do trio, porque a
`consent_event_prova_uq` o impede». **Era falso, e o gate 8 do CI apanhou-o.**

A unicidade e sobre o `evidence_hash` e nao sobre o instante: duas provas do
mesmo trio com resumos diferentes entram as duas, e podem muito bem partilhar o
`ocorrido_em` — **a hora que a Meta manda tem resolucao de segundos**, pelo que
dois cliques no mesmo segundo dao o mesmo instante com `wamid` diferentes. Com o
empate, a vista desempatava pelo `uuid` aleatorio: deterministico para os mesmos
dados, **e arbitrario** em relacao a cronologia. O ensaio contra a base escolheu
a `v2` na minha maquina e a `v1` no CI, com os mesmos dados.

Por isso a tabela tem **duas** horas, e o par e o mesmo que o envelope de evento
do `06` §6.1 ja usa — `ocorrido_em` e `registado_em`:

    ocorrido_em    a hora que a Meta diz. E a que entra no `evidence_hash`, e e
                   por isso que ela sozinha nao serve de ordem: nao e nossa e
                   nao e estritamente crescente.
    registado_em   a hora em que **nos** escrevemos a linha, com
                   `clock_timestamp()`. A ordem da vista e
                   `(ocorrido_em DESC, registado_em DESC, id DESC)`.

**`clock_timestamp()` e nao `now()`, e e a unica coluna deste esquema que o
usa.** O `now()` e o **inicio da transaccao**: duas linhas escritas na mesma
transaccao partilham-no, e era precisamente o empate que se quer quebrar. O
`clock_timestamp()` avanca a cada chamada e tem resolucao de microsegundos. O
`id DESC` fica como terceiro critario — nao porque se espere empatar no
microsegundo, mas para que a vista **nunca** devolva uma linha diferente para os
mesmos dados.

O `ocorrido_em` tambem nao e um `DEFAULT` na pratica: o modulo escreve-o sempre,
porque o `evidence_hash` cobre a hora e os dois tem de concordar. O `DEFAULT
now()` fica para quem insira a mao e para a semente do *gate* 6.

## A idempotencia do criterio 2 e da base, e sai do proprio `evidence_hash`

«O mesmo botao repetido 2x produz 1 linha.» A unicidade e
`(tenant_id, contact_id, purpose, evidence_hash)`, e o que a torna suficiente e a
composicao do resumo: `sha256(texto_mostrado || contact_id || wamid || hora)`. O
`wamid` e da mensagem do botao e a hora e **a que a Meta diz**, nao a nossa —
pelo que uma reentrega do mesmo *webhook* produz o **mesmo** resumo e bate na
unicidade. Com a nossa hora, duas entregas do mesmo botao davam dois resumos e
duas linhas, e o criterio dizia o contrario.

Nao ha `SELECT` antes do `INSERT`: entre os dois cabe outro processo, e o
criterio pede **uma** linha e nao «quase sempre uma». E a mesma forma do
`SQL_REGISTAR_TRANSICAO` da `0014` e do `SQL_ENFILEIRAR` da `0010`.

**Composta com o `tenant_id`**, pela razao da emenda 1.21: com unicidade global,
uma prova do *tenant* B que calhasse no mesmo resumo era deduplicada em silencio
contra uma linha de A — e aqui o que se perdia era prova juridica.

**E o que ela NAO garante:** duas provas do mesmo trio com resumos **diferentes**
entram as duas, e e isso que torna a revogacao uma linha nova. Uma leitura
anterior deste ficheiro dizia que ela impedia um empate no `ocorrido_em`, e nao
impede — ver a nota do `id` e da ordem, acima.

## A vista leva `security_invoker = true`, e sem isso era uma porta

Uma vista corre, por omissao, com os privilegios do **dono**, e o dono das
tabelas esta sujeito a RLS **so por causa do `FORCE`**. Com
`security_invoker = true` a vista corre como quem a consulta, que e o que a RLS
pressupoe.

**Esta e a primeira vista do esquema**, e o `verificar_vistas` do
`db/tests_isolamento/catalogo.py` existe desde o KAM-004 a exigir exactamente
isto — sem lista de excepcoes, ao contrario da RLS das tabelas. E a primeira vez
que aquela verificacao tem alguma coisa para ver.

## A `consent_texts` **nao** tem `tenant_id`, e e decisao e nao esquecimento

O aviso e um texto juridico revisto uma vez e mostrado por todas as lojas: nao e
dado de *tenant*. Quem o escreve e o GOV, quem o aprova e um parecer (KAM-104), e
a versao vigente e a mesma para a plataforma inteira. Dar-lhe `tenant_id` dizia
que cada loja pode ter o seu aviso, o que contradiz «o texto final em PT-AO e
revisto juridicamente» do proprio bloco.

Consequencia directa, e esta e a parte que importa: **nao precisa de excepcao de
RLS**. O gate 6 pergunta por RLS as tabelas que **tem** coluna `tenant_id`; uma
tabela sem ela nao esta no ambito do X-05 e nao entra no
`ci/rls_exceptions.yaml`, que continua a ter uma entrada so. Esconder de uma loja
o texto que os clientes dela veem tambem nao protegeria ninguem.

O nome da loja **nao** vive no texto: ele leva um marcador, e o que se mostra ao
contacto e o texto preenchido. E por isso que o `evidence_hash` cobre o texto
**mostrado** e nao a linha da tabela — ver o `COMMENT` da coluna.

## O `canal` e o transporte e nao a linha do canal

O dicionario §3.1 nomeia o campo `canal`, e ele guarda **por onde** o
consentimento foi dado: `whatsapp`, e mais nada enquanto nao houver outro
transporte. Dominio fechado de um valor, de proposito — acrescentar um segundo e
uma migracao e nao uma insercao em silencio.

**Nao e uma FK para `tenant_channels`**, e a razao e que isto e uma prova
juridica: ela nao pode deixar de se poder ler porque a linha de um canal mudou.
Qual o numero que a recebeu deduz-se da conversa, que tem `channel_id`.

## O que a tabela NAO tem: `UPDATE` nem `DELETE` para a aplicacao

«*append-only* (`UPDATE/DELETE` recusados para `kamba_app`); revogacao = nova
linha». A aplicacao recebe `SELECT` e `INSERT` e mais nada, como o
`channel_quality_log` da `0014` e o `usage_ledger` da `0007`. **Sem gatilho de
imutabilidade**, ao contrario do `audit_log_imutavel` da `0006`: ali a cadeia de
*hash* precisa de uma garantia que o privilegio por coluna nao sabe exprimir;
aqui o privilegio diz tudo o que ha a dizer.

A diferenca face a `0014` e que aqui o *append-only* e **criterio** e nao
consequencia: uma prova de consentimento que se possa corrigir nao e prova.

## O que esta revisao NAO faz, e e escopo e nao esquecimento

* **Nao cria `consent_ledger` nem finalidades analiticas novas.** O `06` §7.3
  descrevia uma segunda forma da mesma tabela com propositos analiticos; o
  KAM-140 reconciliou as cinco formas no `10` §7.2 e esta revisao segue essa. Os
  propositos analiticos estao **ja** no dominio de dez do dicionario §3.1
  (emenda 1.16, KAM-159).
* **Nao toca em `conversations.mode`.** Passar a conversa a `humano` ou a
  `pausada` e o gancho do KAM-018, e a coluna existe desde a `0009`.
* **Nao insere texto nenhum.** A `consent_texts` nasce **vazia**: o texto e
  juridico, esta «a confirmar por parecer» (KAM-104), e uma revisao que o
  escrevesse punha no esquema uma afirmacao legal que ninguem reviu. Quem o
  carrega e uma semente de operacao, e o modulo trata a ausencia de versao
  vigente como falha fechada.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

#: As dez finalidades do dicionario §3.1 (emenda 1.16, KAM-159), que sao a
#: uniao das cinco que o dicionario nomeava e das oito dos contratos
#: publicados. O `contract_diff dominios` (gate 7) confronta-as com o `enum` da
#: ultima versao dos contratos, nos dois sentidos.
#:
#: Os valores vem **ja entre apostrofos**: e a unica forma que o *gate* 3b
#: resolve, porque le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*.
FINALIDADES = (
    "'transacao'",
    "'atendimento'",
    "'marketing'",
    "'analytics_agregado'",
    "'melhoria_servico'",
    "'sugestoes_patrocinadas'",
    "'partilha_loja'",
    "'partilha_parceiros'",
    "'partilha_estafeta'",
    "'notificacao_dono'",
)

#: Os transportes por onde um consentimento pode ser dado. **Um**, e o dominio
#: fechado diz que o segundo entra por migracao e nao por insercao.
CANAIS = ("'whatsapp'",)

#: Bytes de um `sha256`. O `evidence_hash` e `bytea` e nao `text`: o resumo tem
#: 32 bytes e guarda-los em hexadecimal gastava 64 caracteres para dizer o
#: mesmo, com a liberdade de alguem escrever maiusculas num e minusculas noutro
#: e os dois deixarem de comparar iguais.
BYTES_DO_SHA256 = 32


def upgrade() -> None:
    # ------------------------------------------------- o texto, versionado
    #
    # Sem `tenant_id`: ver a nota do modulo. Nasce vazia.
    op.execute(
        f"""
        CREATE TABLE platform.consent_texts (
            version        text        NOT NULL,
            purpose        text        NOT NULL,
            texto          text        NOT NULL,
            hash           bytea       NOT NULL,
            vigente_desde  timestamptz NOT NULL,
            criado_em      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT consent_texts_pkey PRIMARY KEY (version, purpose),
            CONSTRAINT consent_texts_purpose_ck
                CHECK (purpose IN ({", ".join(FINALIDADES)})),
            -- Um texto vazio nao e um texto, e um aviso vazio e pior do que
            -- nenhum: ele e a prova de que se informou.
            CONSTRAINT consent_texts_texto_ck CHECK (btrim(texto) <> ''),
            CONSTRAINT consent_texts_version_ck CHECK (btrim(version) <> ''),
            CONSTRAINT consent_texts_hash_ck
                CHECK (octet_length(hash) = {BYTES_DO_SHA256})
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.consent_texts IS "
        "'O texto do aviso de privacidade, por versao e finalidade. Sem "
        "tenant_id de proposito: e um texto juridico revisto uma vez e mostrado "
        "por todas as lojas, e dar-lhe tenant_id dizia que cada loja pode ter o "
        "seu (KAM-022). Nasce vazia: o texto esta a confirmar por parecer "
        "(KAM-104), e uma migracao que o escrevesse punha no esquema uma "
        "afirmacao legal que ninguem reviu.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.consent_texts.hash IS "
        "'sha256 do texto desta linha, para se poder dizer que a versao nao foi "
        "editada depois de mostrada. NAO e o evidence_hash de consent_event: "
        "esse cobre o texto **preenchido** que um contacto viu, com o nome da "
        "loja no lugar do marcador, mais o contacto, o wamid do botao e a hora.'"
    )
    # A versao vigente de uma finalidade e a de `vigente_desde` mais alto que
    # ja passou. O indice e por finalidade e pela data **descendente**, que e a
    # ordem em que a pergunta se faz.
    op.execute(
        "CREATE INDEX consent_texts_vigente_idx "
        "ON platform.consent_texts (purpose, vigente_desde DESC)"
    )

    # ------------------------------------------------------- a prova
    op.execute(
        f"""
        CREATE TABLE platform.consent_event (
            id             uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id      uuid        NOT NULL,
            contact_id     uuid        NOT NULL,
            purpose        text        NOT NULL,
            text_version   text        NOT NULL,
            accepted       boolean     NOT NULL,
            canal          text        NOT NULL,
            evidence_hash  bytea       NOT NULL,
            ocorrido_em    timestamptz NOT NULL DEFAULT now(),
            -- A hora em que **nos** escrevemos, e e o desempate da vista. Ver a
            -- nota do modulo: `clock_timestamp()` e nao `now()`, porque o
            -- `now()` e o inicio da transaccao e empata entre linhas dela.
            registado_em   timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT consent_event_pkey PRIMARY KEY (id),
            -- **A idempotencia do criterio 2, e e da base.** Ver a nota do
            -- modulo: o resumo leva o `wamid` e a hora **da Meta**, pelo que
            -- uma reentrega do mesmo botao da o mesmo resumo.
            CONSTRAINT consent_event_prova_uq
                UNIQUE (tenant_id, contact_id, purpose, evidence_hash),
            -- **Composta com o `tenant_id`**, pela razao que a `0009` fixou e
            -- a `0011`, a `0012` e a `0014` repetiram: sem ele, uma prova de A
            -- podia apontar para um contacto de B, e nem o *gate* 6 nem o 3b o
            -- veriam. A unicidade do lado de `contacts` e a
            -- `contacts_tenant_contact_uq` da `0003`.
            CONSTRAINT consent_event_contact_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            CONSTRAINT consent_event_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT consent_event_purpose_ck
                CHECK (purpose IN ({", ".join(FINALIDADES)})),
            CONSTRAINT consent_event_canal_ck
                CHECK (canal IN ({", ".join(CANAIS)})),
            CONSTRAINT consent_event_text_version_ck
                CHECK (btrim(text_version) <> ''),
            -- Trinta e dois bytes, nem mais nem menos: um `evidence_hash` de
            -- outro tamanho nao e um sha256, e uma prova que nao se sabe
            -- reproduzir nao e prova.
            CONSTRAINT consent_event_evidence_ck
                CHECK (octet_length(evidence_hash) = {BYTES_DO_SHA256})
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.consent_event IS "
        "'A prova de consentimento, **append-only**: a revogacao e uma linha "
        "nova e nao uma correccao (KAM-022, criterio 6). kamba_app tem SELECT e "
        "INSERT e mais nada — uma prova que se possa corrigir nao e prova.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.consent_event.evidence_hash IS "
        "'sha256(texto_mostrado || contact_id || wamid_do_botao || hora), nesta "
        "ordem e com separador, como o criterio 7 o escreve. Cobre o texto "
        "**preenchido** que o contacto viu e nao a linha de consent_texts: o "
        "nome da loja entra no lugar do marcador, e a prova e do que foi "
        "mostrado. Reprodutivel a partir da linha e da versao do texto.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.consent_event.registado_em IS "
        "'A hora em que a plataforma escreveu a linha, com clock_timestamp(). E "
        "o desempate da vista consent_actual: o ocorrido_em e a hora da Meta e "
        "tem resolucao de segundos, pelo que dois cliques no mesmo segundo o "
        "partilham. clock_timestamp() e nao now() porque now() e o inicio da "
        "transaccao e empatava tambem. O par ocorrido_em/registado_em e o mesmo "
        "do envelope de evento do 06 §6.1.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.consent_event.canal IS "
        "'Por onde o consentimento foi dado. Dominio fechado de um valor "
        "(whatsapp): o segundo transporte entra por migracao e nao por "
        "insercao. Nao e FK para tenant_channels, porque uma prova juridica nao "
        "pode deixar de se ler por a linha de um canal ter mudado; qual o numero "
        "que a recebeu deduz-se da conversa.'"
    )
    # O indice do `06` §7.3, com o sufixo `_idx` que todos os indices deste
    # esquema levam e que aquele documento nao escreve. A ordem das colunas e a
    # da pergunta que a vista faz, e comeca pelo `tenant_id` **porque a RLS o le
    # em toda a consulta** — a licao e da `0011`, onde o *gate* 8 recusou a
    # tabela sem ele.
    op.execute(
        "CREATE INDEX consent_event_contacto_idx "
        "ON platform.consent_event "
        "(tenant_id, contact_id, purpose, ocorrido_em DESC)"
    )

    rls.enable_tenant_rls("consent_event")

    # ----------------------------------------------- a vista do estado actual
    #
    # **`security_invoker = true` nao e opcional**, e e a razao pela qual o
    # `verificar_vistas` do catalogo existe desde o KAM-004 sem nunca ter tido
    # nada para ver: uma vista corre com os privilegios do dono, e o dono esta
    # sujeito a RLS so por causa do `FORCE`. Com `security_invoker` a vista
    # corre como quem a consulta, que e o que a politica pressupoe.
    op.execute(
        """
        CREATE VIEW platform.consent_actual
          WITH (security_invoker = true) AS
        SELECT DISTINCT ON (tenant_id, contact_id, purpose)
               tenant_id, contact_id, purpose, accepted, text_version,
               ocorrido_em
          FROM platform.consent_event
         ORDER BY tenant_id, contact_id, purpose,
                  ocorrido_em DESC, registado_em DESC, id DESC
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.consent_actual IS "
        "'O ultimo estado por (tenant, contacto, finalidade), do `06` §7.3. "
        "Ordena por (ocorrido_em DESC, registado_em DESC, id DESC). O id e uuid "
        "e nao identidade, porque kamba_app le esta tabela e uma chave "
        "sequencial media quantos consentimentos tem a plataforma; e o "
        "ocorrido_em sozinho nao basta, porque e a hora da Meta e tem resolucao "
        "de segundos — dois cliques no mesmo segundo empatavam e a vista "
        "escolhia pelo uuid, arbitrariamente. Leva security_invoker = true: sem "
        "ele a vista corria como o dono e a RLS dependia do FORCE.'"
    )

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela, sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce
    # acessivel (`db/migrations/README.md`).
    #
    # **`SELECT, INSERT` e mais nada para a aplicacao**, e aqui isso e o
    # criterio 6 e nao uma precaucao. O `SELECT` e preciso: o `ConsentGate` le o
    # estado antes de decidir, e a vista le a tabela.
    op.execute("GRANT SELECT, INSERT ON platform.consent_event TO kamba_app")
    op.execute("GRANT SELECT ON platform.consent_actual TO kamba_app")
    # O texto le-se e nao se escreve pela aplicacao: quem publica uma versao
    # nova e operacao, com o papel de administracao.
    op.execute("GRANT SELECT ON platform.consent_texts TO kamba_app")
    # O `kamba_batch` tem os quatro verbos nas duas tabelas, que e o que tem em
    # todas as outras desde a `0001`, porque e quem purga e quem carrega.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.consent_event "
        "TO kamba_batch"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.consent_texts "
        "TO kamba_batch"
    )
    op.execute("GRANT SELECT ON platform.consent_actual TO kamba_batch")


def downgrade() -> None:
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou,
    # o `downgrade` falha em vez de o apagar em silencio. E a regra que todas as
    # revisoes desde a `0001` seguem.
    #
    # **E sem guarda de dados, ao contrario da `0010`.** Aquela recusa descer
    # com linhas, porque apagar `outbound_messages` perde o registo do que se
    # enviou e cobrou. Aqui o que se perde e **prova de consentimento**, que e
    # mais grave do que dinheiro — e e por isso que a guarda **nao** e o
    # mecanismo certo: uma copia para ficheiro JSON, que e o que a `0010` e a
    # `0012` fazem, era guardar prova juridica num ficheiro fora do esquema, sem
    # RLS e sem retencao. Quem precisa de descer esta revisao com linhas tem de
    # exportar primeiro, e quem o fizer sabe porque; o que esta revisao nao faz
    # e fingir que um `json.dump` resolve o problema.
    #
    # **A vista cai primeiro**, e isso nao e cerimonia como o `DROP INDEX` antes
    # do `DROP TABLE`: sem `CASCADE`, o `DROP TABLE consent_event` **falha**
    # enquanto a vista existir.
    op.execute("DROP VIEW platform.consent_actual")
    rls.disable_tenant_rls("consent_event")
    op.execute("DROP INDEX platform.consent_event_contacto_idx")
    op.execute("DROP TABLE platform.consent_event")
    op.execute("DROP INDEX platform.consent_texts_vigente_idx")
    op.execute("DROP TABLE platform.consent_texts")

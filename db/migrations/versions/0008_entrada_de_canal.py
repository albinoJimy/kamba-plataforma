"""Entrada de canal: o registo e a quarentena dos webhooks da Meta (KAM-013).

**A primeira linha e ASCII de proposito, e segue a forma das outras sete.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a do
executavel: um travessao aqui faz as duas divergirem na descodificacao e poe
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` vermelho.

Revisao: 0008
Anterior: 0007

**Porque e que esta revisao existe.** O GWY e o endpoint unico de webhook da
Meta (ADR-001) e responde 200 sem I/O pesado: quem registra o que chegou e o
*worker* de canal, depois da fila. A Meta re-entrega webhooks falhados **ate
sete dias, com backoff exponencial, sem ordem garantida e com entrega
concorrente** (`evidencia/E1` §5, CONFIRMADO), e as garantias do BullMQ
continuam **NAO VERIFICADO** (`evidencia/E4` §2.10). Dois factos que, juntos,
obrigam a deduplicacao em base: o `jobId = sha256(corpo)` do GWY apanha a
re-entrega byte-a-byte, e nada mais apanha a mesma mensagem embrulhada em dois
corpos diferentes. E isso que o `UNIQUE (kind, event_key)` faz.

A fonte de cada coisa:

* `inbound_events` e `unrouted_events` — dicionario §3.12, emenda 1.19
  (KAM-013). A forma vem do bloco do ticket e de `docs/tecnica/01` §5.2 e §5.5.
* Os dominios de `kind` — criterio 8 do bloco (roteamento) com os onze campos
  de webhook que o criterio do KAM-016 fixa; a emenda explica porque sao
  catorze valores e nao onze, e porque se partem em doze (entrada) mais dois
  (quarentena).
* A forma de `event_key` — criterio 4 do bloco: «`event_key` de estados e
  `wamid:estado`».
* A retencao de sete dias do `payload` da quarentena — criterio 6 do bloco
  (*proposta*). **Esta revisao nao a impoe**: nao cria funcao de limpeza nem
  agendador, pela mesma decisao que a `0004` tomou para as particoes mensais e
  a `0005` para a retencao das suas tabelas — o agendador nasce com KAM-071.

**Nenhuma das duas tem `tenant_id`, e isso e desenho.** O tenant so nasce no
CHR (KAM-014), que corre depois desta escrita: no momento em que o *worker*
registra o que chegou, ainda nao se sabe de quem e o `phone_number_id`. Como o
teste de catalogo X-05 do *gate* 6 descobre as tabelas a isolar **pela coluna
`tenant_id`** (`db/tests_isolamento/catalogo.py`, `tabelas_isoladas`), nenhuma
politica e exigida nem dispensada, e **nao ha entrada em
`ci/rls_exceptions.yaml`** — ao contrario do `audit_heads`, que tem `tenant_id`
e por isso precisou de uma.

**O que `inbound_events` NAO guarda: o corpo.** O *payload* de conversa vive no
*job* e, depois, nos *checkpoints* do AGR — e a tabela guarda so o suficiente
para dizer «este evento ja passou por aqui». E o DoD do ticket, linha
«Privacidade».

**O que `unrouted_events` guarda, e e a excepcao:** o corpo bruto, em base64.
Sem ele nao se diagnostica o que nao encaixou, e e para isso que a quarentena
existe. Tres consequencias, as tres deliberadas:

1. **E base64 e nao `jsonb`.** O caso principal da quarentena e o criterio 6 —
   «JSON invalido com assinatura valida» —, e um corpo que nao e JSON nao entra
   num `jsonb`. Tambem pode nao ser UTF-8 valido, e por isso nao entra num
   `text` em claro. Base64 e sem perdas e nao tem forma de SQL nem de JSON.
2. **Tem tecto.** `PAYLOAD_MAXIMO` caracteres de base64. Um corpo influenciado
   por quem chama, numa coluna sem limite, e armazenamento ilimitado a custa de
   outrem; e um `CHECK` que falhasse na insercao da quarentena fazia o *job*
   repetir para sempre, que e o contrario do que o criterio 6 pede. Por isso o
   limite esta no `CHECK` **e** no codigo, que guarda `NULL` quando o corpo o
   excede (`services/worker-canal/src/entrada.ts`).
3. **`kamba_app` escreve e nao le o `payload`.** O mesmo desenho do `audit_log`
   (KAM-012), aqui por privacidade: a coluna pode levar telefone e texto de
   mensagem, e quem a escreve nao precisa de a ler. Le quem opera, que e
   `kamba_batch`. O `SELECT` que ele **tem** e de duas colunas e nao e uma
   concessao: `kind` e `event_key` sao os elementos de inferencia do
   `ON CONFLICT`, e o PostgreSQL trata-os como leitura.

**Privilegios.** `inbound_events` da a `kamba_app` `SELECT` e `INSERT` de
tabela e `UPDATE` **so em `processado_at`**. O `SELECT` e preciso e nao e
generoso: o `INSERT ... ON CONFLICT DO NOTHING RETURNING id` do *worker* e o
que distingue uma linha nova de um duplicado, e o `RETURNING` exige `SELECT` na
coluna devolvida. A objeccao que levou o `events_dlq` (KAM-006) a nao ter
`SELECT` — «um `id` sequencial mede o volume do vizinho» — nao se aplica: aqui
o `id` e `gen_random_uuid()` e a tabela nao tem dado de tenant nenhum.
`kamba_batch` tem os quatro verbos de dados nas duas, que e o que tem em todas
as outras desde a `0001`, porque e quem purga. `kamba_resolver`,
`kamba_identity` e `kamba_audit` nao tem nada: o resolvedor corre antes de
haver contexto, a identidade nao sabe de canais, e quem audita le o
`audit_log`.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

#: As classes de um evento de canal. Lista fechada, imposta por `CHECK`
#: (dicionario §3.12, emenda 1.19).
#:
#: Os doze primeiros sao os onze campos de webhook do criterio do KAM-016, com
#: o campo `messages` a dar dois: a Meta entrega `value.messages[]` e
#: `value.statuses[]` no **mesmo** `value`, e os dois tem destinos opostos —
#: `messages` vai ao CHR e `statuses` nunca vai ao AGR (criterio 8).
#:
#: **A lista parte-se em duas, e as duas tabelas tem `CHECK` diferentes.** O
#: `inbound_events` guarda os doze que sao campos de webhook; o
#: `unrouted_events` guarda **so** `desconhecido` e `invalido`, que nao sao
#: campos da Meta: sao os dois caminhos de quarentena, e existem como `kind`
#: para que a chave `(kind, event_key)` deduplique tambem o que nao se
#: conseguiu encaminhar.
#:
#: A divisao nao e cosmetica — foi o *gate* 3b que a obrigou, ao pedir o dominio
#: **por coluna**, e e mais estreita do que a primeira versao desta revisao: com
#: um `CHECK` de catorze valores nas duas tabelas, uma `message` podia ser
#: escrita na quarentena e um `invalido` no registo de entrada. Nenhum caminho
#: do codigo o fazia, e agora nenhum o pode fazer.
#:
#: Os valores vem **ja entre apostrofos**, e isso nao e desleixo: e a unica
#: forma que o gate 3b resolve. Ele le a AST da revisao sem a executar e segue
#: `', '.join(<constante de modulo>)` dentro de uma *f-string* — a forma da
#: `0002`. Tres variantes recusadas antes desta, cada uma com a sua mensagem:
#: uma funcao auxiliar `_dominio(coluna, valores)` («tem mais do que validacoes
#: e um `return`»), uma constante derivada `KINDS_SQL = ", ".join(...)` («nao e
#: uma constante de modulo») e um gerador dentro da *f-string* («expressao
#: GeneratorExp»). Interpretar qualquer delas seria correr Python arbitrario
#: para descobrir que valores um `CHECK` fixa, e e para nao o fazer que o gate
#: existe. A suite `db/tests_entrada` prende estes dominios aos do dicionario.
KINDS_DE_ENTRADA = (
    "'message'",
    "'echo'",
    "'statuses'",
    "'history'",
    "'smb_app_state_sync'",
    "'account_update'",
    "'phone_number_quality_update'",
    "'business_capability_update'",
    "'account_alerts'",
    "'message_template_status_update'",
    "'template_category_update'",
    "'message_template_quality_update'",
)

#: Os dois caminhos de quarentena. Ver a nota de `KINDS_DE_ENTRADA`.
KINDS_DE_QUARENTENA = ("'desconhecido'", "'invalido'")

#: Porque e que um evento foi para a quarentena. Lista fechada, por `CHECK`.
#:
#: `json_invalido` e o criterio 6 do bloco. `campo_desconhecido` e um
#: `changes[].field` que nao esta nos onze; chega quando alguem subscreve um
#: campo novo na consola da Meta sem o codigo o conhecer, e e o caso em que o
#: alerta vale mais do que o 5xx. `corpo_sem_entry` e o corpo que fez `parse`
#: mas nao tem `entry` utilizavel — ausente, vazio, sem `id` ou sem `changes`.
#: `change_sem_itens` e um campo **conhecido** cujo `value` nao traz nenhum
#: item que se saiba tratar: acontece de verdade com o campo `messages`, onde a
#: Meta poe `errors` em vez de `messages` ou `statuses`. Tem motivo proprio
#: para que o alerta diga a verdade — nao e campo desconhecido nem corpo
#: malformado.
MOTIVOS = (
    "'json_invalido'",
    "'campo_desconhecido'",
    "'corpo_sem_entry'",
    "'change_sem_itens'",
)

#: Tecto do `payload` da quarentena, em caracteres de base64 — 256 KiB, que sao
#: cerca de 192 KiB de corpo.
#:
#: *Proposta*, e calibra-se onde se mede: o webhook da Meta e pequeno (um
#: `statuses` tem centenas de bytes), e o `3x o trafego de estados + 1x o de
#: entrada` do `E1` §5 e sobre a **taxa**, nao sobre o tamanho de um corpo. O
#: numero existe para haver um tecto, nao porque se saiba qual e o certo.
PAYLOAD_MAXIMO = 262_144

#: Tecto de uma `event_key`. Um `wamid` tem dezenas de caracteres e o resumo
#: canonico tem 34; 256 e folga, e o que impede e uma chave de dimensao
#: arbitraria vinda de um corpo externo a entrar num indice unico.
EVENT_KEY_MAXIMO = 256

#: Tecto dos dois identificadores da Meta. Sao opacos e curtos (`E1` §5); o
#: limite e a mesma ideia do de cima. A forma segue
#: `tenant_channels_waba_id_ck` da `0001`, que ja os validava na outra ponta.
ID_META_MAXIMO = 64


# Os dois dominios entram no SQL por um `join` **dentro** da *f-string*, sobre
# uma constante de modulo. E a forma que a `0002` usa, e e a unica que o gate 3b
# le: ele resolve a AST da revisao sem a executar, e segue constantes de modulo,
# ciclos e *f-strings*. Duas formas que tentei antes e ele recusou, as duas com
# a mensagem certa: uma funcao auxiliar `_dominio(coluna, valores)` («tem mais
# do que validacoes e um `return`») e uma constante `KINDS_SQL = ", ".join(...)`
# («nao e uma constante de modulo»). Interpretar qualquer das duas seria correr
# Python arbitrario para descobrir que valores um `CHECK` fixa — e o gate existe
# exactamente para nao ter de o fazer.


def upgrade() -> None:
    # --------------------------------------------------------- inbound_events
    op.execute(
        f"""
        CREATE TABLE platform.inbound_events (
            id              uuid        NOT NULL DEFAULT gen_random_uuid(),
            kind            text        NOT NULL,
            event_key       text        NOT NULL,
            waba_id         text        NOT NULL,
            phone_number_id text,
            recebido_at     timestamptz NOT NULL DEFAULT now(),
            processado_at   timestamptz,
            CONSTRAINT inbound_events_pkey PRIMARY KEY (id),
            CONSTRAINT inbound_events_kind_ck
                CHECK (kind IN ({", ".join(KINDS_DE_ENTRADA)})),
            CONSTRAINT inbound_events_event_key_ck
                CHECK (event_key <> '' AND length(event_key) <= {EVENT_KEY_MAXIMO}),
            CONSTRAINT inbound_events_waba_id_ck
                CHECK (waba_id <> '' AND length(waba_id) <= {ID_META_MAXIMO}),
            CONSTRAINT inbound_events_phone_number_id_ck
                CHECK (phone_number_id IS NULL
                       OR (phone_number_id <> ''
                           AND length(phone_number_id) <= {ID_META_MAXIMO})),
            -- O segundo nivel de deduplicacao, e o que torna todo o consumidor
            -- idempotente sem depender das garantias do BullMQ (E4 §2.10, NAO
            -- VERIFICADO). O indice que esta restricao cria e o mesmo que o
            -- `ON CONFLICT (kind, event_key)` do *worker* infere.
            CONSTRAINT inbound_events_kind_event_key_uq UNIQUE (kind, event_key)
        )
        """
    )

    # -------------------------------------------------------- unrouted_events
    #
    # `waba_id` e `phone_number_id` sao **anulaveis** aqui e `waba_id` nao o e
    # na outra: um corpo que nem faz `parse` nao tem `entry` nenhum, e e esse o
    # caso principal desta tabela. A assimetria e a propria razao de haver duas
    # tabelas em vez de uma com colunas opcionais.
    op.execute(
        f"""
        CREATE TABLE platform.unrouted_events (
            id              uuid        NOT NULL DEFAULT gen_random_uuid(),
            kind            text        NOT NULL,
            event_key       text        NOT NULL,
            waba_id         text,
            phone_number_id text,
            motivo          text        NOT NULL,
            payload         text,
            recebido_at     timestamptz NOT NULL DEFAULT now(),
            processado_at   timestamptz,
            CONSTRAINT unrouted_events_pkey PRIMARY KEY (id),
            -- **Dois valores, e nao os doze da outra tabela.** Uma `message` na
            -- quarentena era um evento de conversa guardado com o corpo ao
            -- lado; um `invalido` no registo de entrada era um corpo ilegivel
            -- a contar como evento tratado.
            CONSTRAINT unrouted_events_kind_ck
                CHECK (kind IN ({", ".join(KINDS_DE_QUARENTENA)})),
            CONSTRAINT unrouted_events_motivo_ck CHECK (motivo IN ({", ".join(MOTIVOS)})),
            CONSTRAINT unrouted_events_event_key_ck
                CHECK (event_key <> '' AND length(event_key) <= {EVENT_KEY_MAXIMO}),
            CONSTRAINT unrouted_events_waba_id_ck
                CHECK (waba_id IS NULL
                       OR (waba_id <> '' AND length(waba_id) <= {ID_META_MAXIMO})),
            CONSTRAINT unrouted_events_phone_number_id_ck
                CHECK (phone_number_id IS NULL
                       OR (phone_number_id <> ''
                           AND length(phone_number_id) <= {ID_META_MAXIMO})),
            -- O tecto esta aqui **e** no codigo. Aqui para que nenhuma outra
            -- via de escrita o ignore; no codigo para que um corpo grande
            -- entre com `payload` nulo em vez de fazer a insercao falhar e o
            -- *job* repetir durante sete dias (criterio 6: nunca 5xx).
            CONSTRAINT unrouted_events_payload_ck
                CHECK (payload IS NULL OR length(payload) <= {PAYLOAD_MAXIMO}),
            CONSTRAINT unrouted_events_kind_event_key_uq UNIQUE (kind, event_key)
        )
        """
    )

    # ------------------------------------------------------------ privilegios
    #
    # Tabela a tabela e coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: uma
    # tabela nova nao nasce acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    op.execute("GRANT SELECT, INSERT ON platform.inbound_events TO kamba_app")
    # Uma coluna, e e a unica que o *worker* escreve depois de inserir. Mudar
    # `kind` ou `event_key` era reescrever a chave de deduplicacao de um evento
    # que ja passou — isto e, fazer com que ele volte a passar.
    op.execute("GRANT UPDATE (processado_at) ON platform.inbound_events TO kamba_app")

    # **Escreve e nao le.** Ver o ponto 3 do docstring: a coluna `payload` pode
    # levar telefone e texto de mensagem. Sem `SELECT`, o *worker* tambem nao
    # pode usar `RETURNING` nesta tabela — e nao precisa: a quarentena nao tem
    # de distinguir uma entrada nova de um duplicado, basta nao duplicar.
    op.execute("GRANT INSERT ON platform.unrouted_events TO kamba_app")
    # **E `SELECT` em duas colunas, que nao e uma concessao a mais: e o que o
    # `ON CONFLICT (kind, event_key)` exige.** O PostgreSQL trata os elementos
    # da clausula de inferencia como **leitura**, e sem eles a insercao falha
    # com 42501 — medido na suite `tests_entrada`, onde a quarentena ficava a
    # zero sem erro visivel. E a mesma licao que a `0005` ja escreveu para o
    # `ON CONFLICT (consumer, event_id)` do `events_dlq` (KAM-006).
    #
    # **O `payload` continua fechado**, e e isso que importa: a coluna que pode
    # levar telefone e texto de mensagem nao entra, nem o `motivo`, nem os dois
    # identificadores da Meta.
    #
    # **O que estas duas colunas dao de lambuja, dito e nao escondido:** com
    # privilegio em **qualquer** coluna, o PostgreSQL aceita `count(*)`. Logo
    # `kamba_app` passa a poder contar as linhas da quarentena. A objeccao que
    # levou o `events_dlq` (KAM-006) a nao ter `SELECT` era «um `id` sequencial
    # mede o volume do vizinho», e aqui nao ha vizinho: a tabela nao tem
    # `tenant_id`, o `id` e `gen_random_uuid()`, e a contagem e da plataforma
    # inteira — diz quantos corpos nao encaixaram, nao de quem sao. Medido em
    # `db/tests_entrada`, no teste que o declara.
    op.execute(
        "GRANT SELECT (kind, event_key) ON platform.unrouted_events TO kamba_app"
    )

    for tabela in ("inbound_events", "unrouted_events"):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.{tabela} TO kamba_batch"
        )


def downgrade() -> None:
    """Reverter e seguro: a revisao e aditiva e nao toca em tabela anterior.

    `DROP TABLE` leva consigo as restricoes, os indices e os `GRANT` — e por
    isso nao ha `REVOKE` aqui: revogar numa tabela que deixa de existir e
    ruido, e um `REVOKE` depois do `DROP` falhava.

    **O que se perde e o registo de deduplicacao.** Depois de um `downgrade`,
    um webhook que a Meta re-entregue volta a ser tratado como novo: o
    `jobId = sha256(corpo)` continua a apanhar a re-entrega identica enquanto o
    *job* estiver na janela de `removeOnComplete`, e o resto repete. Nao e
    corrupcao — todo o consumidor e idempotente —, e o custo de reverter esta
    revisao com trafego a entrar e processar outra vez o que ja se processou.
    """
    op.execute("DROP TABLE platform.unrouted_events")
    op.execute("DROP TABLE platform.inbound_events")

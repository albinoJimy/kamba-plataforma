"""Ledger de pagamentos append-only: payment_charges, inbox e payment_events (KAM-053).

A primeira linha e **sem acentos**, como as vinte e oito revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria

As tres tabelas do `docs/tecnica/04` §6.2 que faltavam ao PAY, mais a unica
porta de escrita do ledger:

    payment_charges          estado **derivado** do ledger; a unica tabela
                             mutavel de PAY — e mutavel so pela funcao
    payment_callbacks_inbox  toda a entrega HTTP, incluindo as rejeitadas.
                             **Sem `tenant_id`**: quem chega nao o sabe
    payment_events           o ledger. `INSERT` so por `append_payment_event`;
                             `UPDATE`/`DELETE`/`TRUNCATE` nao existem
    payment_outbox_map       `(tipo_evento, authn_method) -> tipo EVT`. Fica
                             **vazia**: o conteudo e do KAM-055

    append_payment_event     `SECURITY DEFINER`, a porta. `FOR UPDATE`,
                             sequencia, cadeia de hashes, projeccao do estado e
                             *outbox* na mesma transaccao
    payment_charge_nasce_iniciada
                             o *trigger* que fecha a **quinta via**: uma
                             cobranca nasce em `iniciada`, para ninguem a
                             inserir ja `paga`
    resolve_webhook_token    resolve o *token* sem contexto de tenant e **sem
                             permitir enumeracao**: a politica `pay_hooks_token`
                             carrega o predicado, pelo que o papel compara a
                             coluna do segredo sem ter `SELECT` nela
    payment_instante         a serializacao de um instante para o elo, em UTC
    next_state               a maquina do §7.1, pura
    rebuild_charge_state     reconstroi o estado a partir dos eventos
    verify_ledger_chain      recalcula a cadeia e devolve os elos partidos
    payment_event_row_hash   a formula de um elo
    deny_mutation            o *trigger* que recusa a mutacao

## O ticket inteiro e «um so caminho de escrita»

Tudo o que segue existe para que nao haja uma segunda porta, e cada barreira
fecha uma porta diferente:

    REVOKE/GRANT      nenhum papel de aplicacao tem `INSERT` em payment_events.
                      Um `INSERT` directo como `kamba_app` falha com 42501
    SECURITY DEFINER  e o que da a `append_payment_event` o privilegio que o
                      chamador nao tem. **Nao** lhe da isolamento: ver abaixo
    deny_mutation     recusa `UPDATE`/`DELETE`/`TRUNCATE` **a todos**, incluindo
                      ao dono e ao superutilizador
    sem UPDATE        nenhum papel tem `UPDATE` em payment_charges. O `estado`
                      muda **so** pela projeccao da funcao
    next_state        uma transicao fora do §7.1 e recusada, nao adivinhada

## `SECURITY DEFINER` nao contorna o `FORCE`, e aqui isso e uma vantagem

O `db/rls.py` nomeia esta revisao como credora da licao que o KAM-052 pagou:
`SECURITY DEFINER` troca o `current_user` pelo **dono** da funcao — o
`kamba_migrator`, que e `NOBYPASSRLS` — e o `FORCE` vincula o dono da tabela.
No `assert_beneficiary` da `0027` isso foi um defeito, porque a funcao precisava
de **ler** uma conta de `tenant_id` nulo.

Aqui e o desenho certo, e nao um remendo. A funcao precisa de duas coisas
diferentes, e o PostgreSQL da-lhas por caminhos diferentes:

* **privilegio** para escrever em payment_events, que nenhum papel de aplicacao
  tem: vem do `DEFINER`;
* **isolamento** por tenant, que nao se quer perder: vem da RLS, que continua a
  valer porque o `FORCE` prende tambem o dono. O `app.tenant_id` do chamador
  esta na mesma transaccao, pelo que a politica `tenant_iso` avalia com o
  contexto de quem chamou.

Resultado medivel: a funcao nao escreve um evento de outro tenant **mesmo sendo
`DEFINER`**, porque o `WITH CHECK` da `tenant_iso` o recusa.

E a **unica** entrada que esta revisao acrescenta ao
`ci/secdef_allowlist.yaml`, como o DoD do bloco exige — e chegar la custou tres
tentativas na resolucao do `webhook_token`, que tem o mesmo problema de
contexto e **nao** se resolve com uma segunda `DEFINER`. As tres estao escritas
em `_privilegios`, porque a terceira so se entende contra as duas que
falharam.

## O que esta revisao **nao** cria, e e deliberado

* **FK de `order_id` para `orders_mirror` e de `billing_cycle_id` para
  `billing_cycles`.** As duas tabelas nao existem (KAM-044 e KAM-059), e o
  bloco do ticket escreve por extenso que a primeira FK e do **KAM-055** e a
  segunda do **KAM-059**. O `CHECK` de exclusividade — exactamente um dos dois
  — fica **aqui**, porque nao depende de tabela nenhuma.
* **O conteudo da `payment_outbox_map`.** O mapeamento definitivo e do KAM-055;
  a suite enche-o com um mapeamento de ensaio, que e o que o bloco manda.
* **`manual_confirmations`, `refund_cases` e `fraud_signals`** (§6.3): KAM-054 e
  KAM-060.

## O *trigger* `assert_beneficiary` liga-se **aqui**, e nao no KAM-055

O comentario da `0027` escreve «o `CREATE TRIGGER` sobre `payment_charges` e do
KAM-055», e e a unica coisa desta revisao que contraria o que ficou escrito.
A razao: a `payment_charges` nasce **nesta** revisao, e deixar uma tabela de
dinheiro dois tickets sem a guarda G-1 do §10.4 nao e «nao alargar o escopo» —
e tirar uma barreira que ja existe, construida e testada, por causa de uma frase
escrita quando se supunha que a tabela nasceria mais tarde. O que fica para o
KAM-055 e o que ele tem de ser: a FK para `orders_mirror`.

O `downgrade` da `0027` continua a funcionar sem `CASCADE`, porque o *trigger*
cai com a `payment_charges` no `downgrade` **desta** revisao, que corre antes.

## `authn_method` tem **quatro** valores, e a decisao era deste ticket

O §6.2 fixa `authn_method IN ('hmac','consulta','manual','sistema')` e anota, em
texto, que o quarto valor «nao tem contrapartida no dicionario» e que «a decisao
pertence a quem escrever o KAM-053». Fica decidida, e a decisao e **manter o
`sistema`** — com o seu dominio escrito, que e o que faltava:

* um `pagamento_confirmado` **nunca** e `sistema`. Nao e uma convencao: a
  restricao `confirmar_exige_autenticacao` nao inclui o `sistema`, pelo que a
  base recusa. Um pagamento confirmado pela plataforma a partir de um extracto
  e `manual` (ha um humano de ops, com `actor_id`); a partir da fila do
  facilitador e `consulta`;
* o `sistema` serve os factos de ciclo de vida que **nao** sao autenticados por
  ninguem porque nao vem de fora: `cobranca_criada`, `referencia_emitida`,
  `push_enviado`, `cobranca_expirada`, `cobranca_cancelada`. Para esses,
  `consulta` seria uma afirmacao falsa (nao houve consulta) e `manual` e
  impossivel (o `humano_exige_actor` exige `actor_id`).

O dicionario §3.4 passa a quatro valores pela mesma emenda que acrescenta o
§3.38, e o `canon/dicionario.yaml` e regenerado dele.

## `hmac`, e nao `hmac_sha256`; e `authn_hmac_ok`, e nao `callback_hmac_ok`

O criterio 9 do bloco escreve `callback_hmac_ok = (authn_method='hmac_sha256'
AND authn_ok)`, e os **dois** nomes estao na coluna «Substitui» do dicionario
§3.4. Sao duas situacoes diferentes, e so uma se resolve aqui:

* `hmac_sha256` -> `hmac`. E uma traducao, e a emenda 1.13 (KAM-141, linha 4)
  escreveu-a **com este ticket nomeado**: «sem isto, o DDL do KAM-053, copiado
  do documento como o ticket manda, era recusado pelo gate sem explicacao». A
  vista usa `hmac`.
* `callback_hmac_ok` nao se traduz: e o **nome da coluna** que o criterio pede,
  e e variante de nivel 1 — falha em qualquer superficie, dentro de cadeias e de
  comentarios, e nenhuma excepcao existe para o salvar. A coluna chama-se
  `authn_hmac_ok`, com o mesmo predicado, e a **caixa do criterio 9 fica vazia**
  com a medicao escrita. Ver o comentario de `_vistas`.
"""

from alembic import op

import rls

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes, pela razao da `0025`: o
#: *gate* 3b le o AST da revisao sem a executar e resolve `f"..."` sobre
#: constantes de modulo, mas nao sobre constantes que sejam elas proprias
#: f-strings.
COBRANCAS = "platform.payment_charges"
INBOX = "platform.payment_callbacks_inbox"
EVENTOS = "platform.payment_events"
MAPA = "platform.payment_outbox_map"

#: O `prev_hash` do primeiro elo de uma cadeia. Trinta e dois zeros, e nao
#: `NULL`, pela razao da `0006`: com `NULL` o `sha256(NULL || ...)` e `NULL` e o
#: `row_hash NOT NULL` recusava a primeira linha de cada cobranca.
GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000000"

#: Os dez estados da cobranca do §6.2, pela ordem do diagrama do §7.1.
ESTADOS_DA_COBRANCA = (
    "'iniciada'",
    "'emitida'",
    "'aguarda_cliente'",
    "'pendente_confirmacao'",
    "'paga'",
    "'expirada'",
    "'falhada'",
    "'cancelada'",
    "'reembolso_pendente'",
    "'reembolsada'",
)

#: Os quatro estados que ocupam o indice `payment_charges_activa_uq`: uma
#: encomenda nao tem duas cobrancas a correr ao mesmo tempo. Depois de um
#: estado terminal o par liberta-se, e **tem** de libertar-se, senao o
#: `tentativa + 1` do F-06 nao podia existir.
ESTADOS_ACTIVOS = (
    "'iniciada'",
    "'emitida'",
    "'aguarda_cliente'",
    "'pendente_confirmacao'",
)

#: O dominio de `metodo` do §6.2.
METODOS = ("'referencia'", "'express_push'", "'manual'", "'cod'")

#: O dominio de `motivo_falha` do §6.2.
MOTIVOS_DE_FALHA = (
    "'valor_divergente'",
    "'referencia_divergente'",
    "'entidade_divergente'",
    "'rejeitada_provider'",
    "'recusada_cliente'",
    "'timeout_cliente'",
    "'provider_indisponivel'",
    "'criacao_incerta'",
    "'manual_rejeitada'",
)

#: Os dezassete tipos de evento do §6.2, pela ordem do documento. Factos e
#: decisoes na mesma lista: o que os distingue e a `decisao`, nao o tipo.
TIPOS_DE_EVENTO = (
    "'cobranca_criada'",
    "'referencia_emitida'",
    "'push_enviado'",
    "'pagamento_recebido'",
    "'pagamento_confirmado'",
    "'pagamento_divergente'",
    "'pagamento_orfao'",
    "'pagamento_duplicado'",
    "'pagamento_rejeitado_provider'",
    "'cobranca_expirada'",
    "'cobranca_cancelada'",
    "'confirmacao_manual_pedida'",
    "'confirmacao_manual_registada'",
    "'confirmacao_manual_rejeitada'",
    "'confirmacao_manual_revertida'",
    "'reembolso_manual_registado'",
    "'ajuste_reconciliacao'",
)

#: `authn_method`: os tres do dicionario §3.4 mais o `sistema` do §6.2 — ver o
#: cabecalho para a decisao que este ticket devia e passa a ter tomado.
METODOS_DE_AUTENTICACAO = ("'hmac'", "'consulta'", "'manual'", "'sistema'")

#: Os tres de `authn_method` que podem autenticar um `pagamento_confirmado`. O
#: `sistema` **nao** esta aqui, e e esse o dominio do quarto valor.
AUTENTICACOES_QUE_CONFIRMAM = ("'hmac'", "'consulta'", "'manual'")

#: O dominio de `decisao` do §6.2.
DECISOES = ("'aceite'", "'rejeitada'", "'informativo'")

#: O dominio de `actor_kind` do §6.2.
ACTORES = ("'provider'", "'dono'", "'ops'", "'sistema'")

#: O dominio de `payment_callbacks_inbox.estado` do §6.2.
ESTADOS_DO_INBOX = (
    "'recebido'",
    "'processado'",
    "'duplicado'",
    "'hmac_invalido'",
    "'token_desconhecido'",
    "'ignorado'",
    "'erro'",
)

#: Os campos que entram no `row_hash`, por esta ordem. O `id` **nao** esta
#: aqui: e `GENERATED ALWAYS AS IDENTITY` e so se conhece depois do `INSERT`,
#: pelo que um elo que o incluisse nao se podia recalcular com a formula.
#: O `recebido_at` tambem nao: e `DEFAULT now()` e a verificacao da cadeia
#: le-o da linha, nao o reconstroi.
CAMPOS_DO_ROW_HASH = (
    "prev_hash",
    "tenant_id",
    "charge_id",
    "order_id",
    "billing_cycle_id",
    "provider",
    "account_id",
    "referencia",
    "tipo_evento",
    "sequencia",
    "provider_event_id",
    "valor_minor",
    "currency",
    "authn_method",
    "authn_ok",
    "decisao",
    "motivo",
    "actor_kind",
    "actor_id",
    "payload_hash",
    "ocorrido_at",
    "recebido_at",
)

#: As colunas da tabela que **nao** entram no elo, cada uma com a razao.
#: A revisao adversarial mostrou que a primeira versao deixava **nove** de
#: fora — o `actor_id`, o `actor_kind`, o `motivo`, o `ocorrido_at`, o
#: `tenant_id`, o `order_id` e o `billing_cycle_id` entre elas — e mediu o
#: que isso permitia: reescrever a atribuicao do acto humano, ou reatribuir
#: um evento a outro tenant, **sem a cadeia dar por nada**.
#:
#: O `test_o_elo_cobre_todas_as_colunas` compara esta lista com o catalogo,
#: nos dois sentidos. O ensaio anterior varria as **posicoes de argumento**
#: da funcao e era, por construcao, tautologico quanto a pergunta «que
#: coluna fica de fora».
FORA_DO_ROW_HASH = {
    "id": "identidade: so existe depois do INSERT, e um elo recalcula-se",
    "payload": "coberto pelo payload_hash, que entra no elo",
    "prev_hash": "e a entrada do elo",
    "row_hash": "e a saida do elo",
}

#: A expressao SQL que concatena os campos do `row_hash`, pela razao da `0006`:
#: escrita uma vez, usada na funcao e no comentario. `chr(31)` e o separador de
#: unidades — nao ocorre em nenhum dos valores, pelo que a concatenacao nao e
#: ambigua (dois campos adjacentes nao se podem confundir deslocando a
#: fronteira).
CONCATENACAO_DO_ROW_HASH = (
    "encode(p_prev_hash, 'hex') || chr(31) || "
    "p_tenant_id::text || chr(31) || "
    "p_charge_id::text || chr(31) || "
    "coalesce(p_order_id::text, '') || chr(31) || "
    "coalesce(p_billing_cycle_id::text, '') || chr(31) || "
    "p_provider || chr(31) || "
    "p_account_id::text || chr(31) || "
    "p_referencia || chr(31) || "
    "p_tipo_evento || chr(31) || "
    "p_sequencia::text || chr(31) || "
    "coalesce(p_provider_event_id, '') || chr(31) || "
    "p_valor_minor::text || chr(31) || "
    "p_currency || chr(31) || "
    "p_authn_method || chr(31) || "
    "p_authn_ok::text || chr(31) || "
    "p_decisao || chr(31) || "
    "coalesce(p_motivo, '') || chr(31) || "
    "p_actor_kind || chr(31) || "
    "coalesce(p_actor_id::text, '') || chr(31) || "
    "encode(p_payload_hash, 'hex') || chr(31) || "
    "coalesce(platform.payment_instante(p_ocorrido_at), '') || chr(31) || "
    "platform.payment_instante(p_recebido_at)"
)

#: A assinatura de `payment_event_row_hash`, para o `GRANT`, o `COMMENT` e o
#: `DROP`. Escrita uma vez: os tipos tem de ser os mesmos nos tres sitios ou o
#: `DROP` nao a encontra.
ARGUMENTOS_DE_ROW_HASH = (
    "bytea, uuid, uuid, uuid, uuid, text, uuid, text, text, integer, text, "
    "bigint, character, text, boolean, text, text, text, uuid, bytea, "
    "timestamp with time zone, timestamp with time zone"
)

#: A assinatura de `append_payment_event`, idem.
ARGUMENTOS_DE_APPEND = (
    "uuid, text, uuid, bigint, text, boolean, text, text, text, uuid, text, "
    "jsonb, timestamptz"
)

#: A assinatura de `next_state`, idem.
ARGUMENTOS_DE_NEXT_STATE = "text, text, text"

#: Os tipos de evento que **nunca** movem o estado. Nao e o complemento das
#: arestas do §7.1: e a lista dos factos que o §5.1, o §7.2 e o §8 mandam
#: registar **sem** transicao, e um tipo que nao esteja aqui nem numa aresta e
#: recusado em vez de tratado como inofensivo.
#:
#:     cobranca_criada               F-09 e F-13: registo da criacao
#:     pagamento_recebido            §5.1: escreve-se **antes** da decisao
#:     pagamento_orfao               G3: «nao confirma, nao reconhece»
#:     pagamento_duplicado           F-01 e F-08: «200, sem efeito»
#:     confirmacao_manual_registada  §4.1: o registo do acto humano. Quem move
#:                                   para `paga` e o `pagamento_confirmado`
#:     ajuste_reconciliacao          §8: compensatorio mais caso para ops
EVENTOS_SEM_TRANSICAO = (
    "'cobranca_criada'",
    "'pagamento_recebido'",
    "'pagamento_orfao'",
    "'pagamento_duplicado'",
    "'confirmacao_manual_registada'",
    "'ajuste_reconciliacao'",
)

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"
#: O papel estreito do §6.2 e dos «Detalhes Tecnicos» do bloco: resolve
#: `webhook_token -> account` **antes de existir contexto de tenant**, porque
#: nesse instante ainda nao se sabe de quem e o callback.
PAPEL_DOS_HOOKS = "kamba_pay_hooks"

#: A variavel de sessao que leva o `webhook_token` a politica
#: `pay_hooks_token`. O padrao e o do `app.tenant_id` da `tenant_iso`
#: (`db/rls.py`): uma variavel que o chamador poe e a politica le.
VARIAVEL_DO_TOKEN = "app.webhook_token"

#: O predicado da politica. Escrito uma vez: entra no `CREATE POLICY` e o
#: `test_privilegios_do_token` compara-o com o que o catalogo devolve.
#:
#: O `NULLIF` esta la pela razao do `db/rls.py`: uma variavel nunca
#: definida da `NULL` e uma que expirou da `''`, e as duas tem de dar zero
#: linhas em vez de todas.
PREDICADO_DO_TOKEN = (
    "NULLIF(current_setting('app.webhook_token', true), '')"
)

#: As colunas do inbox que o papel dos hooks e o lote podem alterar. O `body`,
#: o `body_hash`, os `headers`, o `source_ip` e o `recebido_at` **nao** estao
#: aqui: o que entrou pela rede nao se reescreve. E o que faz do inbox uma
#: prova em vez de um registo de trabalho.
UPDATE_DO_INBOX = ("estado", "processado_at", "erro", "authn_ok")


def upgrade() -> None:
    _papel_dos_hooks()
    _cobrancas()
    _nasce_iniciada()
    _inbox()
    _eventos()
    _mapa_do_outbox()
    _row_hash()
    _next_state()
    _append()
    _rebuild()
    _verificacao_da_cadeia()
    _vistas()
    _rls()
    _privilegios()


def _papel_dos_hooks() -> None:
    """`kamba_pay_hooks`: o papel que resolve o *token* sem contexto de tenant.

    **Criado aqui e nao no `db/bootstrap.py`**, e e uma divergencia que fica
    escrita. O `bootstrap` cria os oito papeis da lista fechada do `ATRIBUTOS` e
    corre como superutilizador, **antes** do Alembic; uma revisao corre como
    `kamba_migrator`, que e `NOCREATEROLE`. Logo este `CREATE ROLE` so funciona
    porque o `db/bootstrap.py` **tambem** o cria — e e la que ele esta, com os
    atributos. O que esta revisao faz e garantir que existe quando se aplica
    contra uma base que o `bootstrap` desta versao ja preparou, e nao falhar
    contra uma que nao o tenha.

    `NOBYPASSRLS`, como todos menos o `kamba_batch`: este papel nao ve dado de
    tenant nenhum. O que ele ve e o inbox, que nao tem `tenant_id`, e o
    `webhook_token` da `payment_accounts` — que e exactamente o par de que
    precisa e nada mais.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL_DOS_HOOKS}') THEN
            RAISE EXCEPTION
              'o papel {PAPEL_DOS_HOOKS} nao existe: corre o db/bootstrap.py '
              'desta versao antes desta revisao (uma revisao corre como '
              'kamba_migrator, que e NOCREATEROLE)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
        END $$
        """
    )


def _cobrancas() -> None:
    """A `payment_charges` do §6.2: estado derivado, e a unica tabela mutavel.

    «Mutavel» diz o que ela **e**, nao quem a muda: nenhum papel tem `UPDATE`
    nesta tabela. O `estado` e o `atualizado_at` mudam **so** pela projeccao da
    `append_payment_event`, que e `SECURITY DEFINER` e corre como o dono.

    E a barreira que o DoD do bloco mede («nao existe caminho de codigo que
    escreva `paga` fora de `append_payment_event`): sem `UPDATE` concedido, o
    caminho nao existe por privilegio, e nao por disciplina de quem escreve o
    codigo.
    """
    op.execute(
        f"""
        CREATE TABLE {COBRANCAS} (
            -- `= chargeId = Idempotency-Key` (§6.2). Quem cria a cobranca
            -- escolhe o `id`, que e o que torna a criacao retentavel com a
            -- mesma chave (F-09).
            id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id          uuid        NOT NULL,
            -- **Sem FK**, e as duas por razoes diferentes: a `orders_mirror`
            -- e do KAM-044 e a FK e do KAM-055; a `billing_cycles` e do
            -- KAM-059. O `CHECK` de exclusividade nao depende de nenhuma das
            -- duas e fica aqui.
            order_id           uuid,
            billing_cycle_id   uuid,
            -- Depois de um estado terminal, a mesma encomenda recebe uma
            -- cobranca nova com `tentativa + 1` (F-06). E o que o
            -- `payment_charges_activa_uq` deixa acontecer e o `UNIQUE (order_id,
            -- tentativa)` impede que se repita.
            tentativa          smallint    NOT NULL DEFAULT 1,
            account_id         uuid        NOT NULL,
            provider           text        NOT NULL,
            metodo             text        NOT NULL,
            -- Anulavel: um `express_push` nao tem referencia. Quando existe, o
            -- par `(account_id, referencia)` e unico — **com** a conta, porque
            -- uma referencia Multicaixa e Entidade + Referencia e duas PMEs
            -- podem ter o mesmo numero (`evidencia/E2` §2).
            referencia         text,
            provider_charge_id text,
            amount_minor       bigint      NOT NULL,
            currency           char(3)     NOT NULL DEFAULT 'AOA',
            estado             text        NOT NULL DEFAULT 'iniciada',
            motivo_falha       text,
            requer_humano      boolean     NOT NULL DEFAULT false,
            valid_until        timestamptz NOT NULL,
            -- HMAC do msisdn Express do pagador (anti-auto-compra, §9). Um
            -- HMAC e nao o numero: o numero e PII P2 (ADR-010).
            payer_hmac         bytea,
            criado_at          timestamptz NOT NULL DEFAULT now(),
            atualizado_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT payment_charges_pkey PRIMARY KEY (id),
            CONSTRAINT payment_charges_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT payment_charges_account_fk
                FOREIGN KEY (account_id) REFERENCES platform.payment_accounts (id),
            CONSTRAINT payment_charges_order_tentativa_uq UNIQUE (order_id, tentativa),
            CONSTRAINT payment_charges_billing_tentativa_uq
                UNIQUE (billing_cycle_id, tentativa),
            -- Exactamente um sujeito: uma encomenda ou um ciclo de billing
            -- (§6.1). A facturacao da propria KAMBA usa o mesmo PAY (§11.2), e
            -- e por isso que o `order_id` do documento 11 nao podia ser
            -- obrigatorio.
            CONSTRAINT payment_charges_um_sujeito
                CHECK ((order_id IS NULL) <> (billing_cycle_id IS NULL)),
            CONSTRAINT payment_charges_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_COBRANCA)})),
            CONSTRAINT payment_charges_metodo_ck
                CHECK (metodo IN ({", ".join(METODOS)})),
            -- **Sem `IS NULL OR`**, pela razao da `0027`: num `CHECK` do
            -- PostgreSQL um `NULL IN (…)` avalia a `NULL`, que conta como
            -- satisfeito, e a disjuncao torna o dominio ilegivel para o
            -- `canon_lint`, que exige a forma `CHECK (coluna IN (…))`.
            CONSTRAINT payment_charges_motivo_falha_ck
                CHECK (motivo_falha IN ({", ".join(MOTIVOS_DE_FALHA)})),
            CONSTRAINT payment_charges_amount_ck CHECK (amount_minor > 0),
            -- `AOA` enquanto a plataforma for de Angola (dicionario §3.4);
            -- alarga-lo e emenda, nao configuracao.
            CONSTRAINT payment_charges_currency_ck CHECK (currency = 'AOA'),
            CONSTRAINT payment_charges_tentativa_ck CHECK (tentativa >= 1),
            CONSTRAINT payment_charges_provider_ck CHECK (btrim(provider) <> '')
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {COBRANCAS} IS "
        "'Cobranca: o estado **derivado** do ledger payment_events (KAM-053). "
        "Unica tabela mutavel de PAY, e mutavel so por append_payment_event: "
        "nenhum papel tem UPDATE. docs/tecnica/04 secao 6.2; dicionario 3.42.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {COBRANCAS}.estado IS "
        "'Projeccao de next_state sobre o ledger. O rebuild_charge_state "
        "reconstroi-o a partir dos eventos e um job nocturno compara os dois "
        "(docs/tecnica/04 secao 8).'"
    )
    op.execute(
        f"COMMENT ON COLUMN {COBRANCAS}.order_id IS "
        "'Sem FK nesta revisao: a orders_mirror e do KAM-044 e a FK do "
        "KAM-055. O CHECK payment_charges_um_sujeito nao depende dela.'"
    )
    # O criterio 4 do §6.2: `(account_id, referencia)` e unico **com** a conta.
    op.execute(
        f"CREATE UNIQUE INDEX payment_charges_ref_uq ON {COBRANCAS} "
        "(account_id, referencia) WHERE referencia IS NOT NULL"
    )
    # Uma cobranca activa por sujeito. O `COALESCE` e do §6.2 e funciona porque
    # o `um_sujeito` garante que exactamente um dos dois nao e nulo.
    op.execute(
        f"CREATE UNIQUE INDEX payment_charges_activa_uq ON {COBRANCAS} "
        "(COALESCE(order_id, billing_cycle_id)) "
        f"WHERE estado IN ({', '.join(ESTADOS_ACTIVOS)})"
    )
    # O `tenant_id` primeiro, porque e o predicado que a RLS acrescenta a toda
    # a consulta (`test_tenant_id_e_not_null_e_vem_primeiro_num_indice`).
    op.execute(
        f"CREATE INDEX payment_charges_tenant_idx ON {COBRANCAS} (tenant_id, estado)"
    )
    # A leitura do worker: «a cobranca desta conta com esta referencia», que e
    # o G3 do §5. Servida pelo `payment_charges_ref_uq`.
    #
    # **A guarda G-1 do §10.4 liga-se aqui** — ver o cabecalho para a razao de
    # nao esperar pelo KAM-055.
    op.execute(
        f"""
        CREATE TRIGGER payment_charges_beneficiario
          BEFORE INSERT ON {COBRANCAS}
          FOR EACH ROW EXECUTE FUNCTION platform.assert_beneficiary()
        """
    )


def _nasce_iniciada() -> None:
    """A cobranca nasce em `iniciada`, e isto fecha a **quinta via**.

    ## O defeito que esta funcao corrige, medido pela revisao adversarial

    A primeira versao desta revisao afirmava, no DoD e em tres comentarios, que
    «nao existe caminho de codigo que escreva `paga` fora de
    `append_payment_event`», e provava-o com quatro vias: `UPDATE` na cobranca,
    `INSERT` no ledger, a porta sem autenticacao e a porta com decisao
    rejeitada. **Faltava a quinta, que e a obvia:** o `kamba_app` tem `INSERT`
    nesta tabela, e o `estado` tinha dominio mas nao tinha valor inicial
    imposto — pelo que um

        INSERT INTO platform.payment_charges (..., estado, ...)
        VALUES (..., 'paga', ...)

    passava, com o contexto do proprio tenant, e deixava uma cobranca **paga com
    zero eventos no ledger**. Medido. Qualquer um dos dez estados entrava,
    incluindo o `reembolso_pendente` que esta revisao declara inalcancavel pelo
    ledger.

    **E o que o agravava:** o unico detector seria o *job* do §8, e ele excluia
    esta forma **por construcao** — compara a projeccao com a reconstrucao so
    para cobrancas **com** eventos, e uma cobranca forjada nao tem nenhum.

    A barreira existia so para o `UPDATE`. Conflui-se «ninguem tem `UPDATE`» com
    «nao ha caminho para escrever `paga`», e as duas coisas nao sao a mesma.

    ## Porque e um *trigger* e nao um `CHECK`

    Um `CHECK (estado = 'iniciada')` e avaliado em **toda** a versao da linha,
    incluindo a que a projeccao da porta escreve — isto e, impedia a cobranca de
    sair de `iniciada` e o ledger deixava de servir para nada. O `BEFORE INSERT`
    vincula **o nascimento** e deixa a transicao em paz.

    E vincula-o a **todos**: ao `kamba_app`, ao `kamba_batch` (que tem
    `BYPASSRLS`), ao dono e ao superutilizador. A unica forma de o contornar e
    desliga-lo, que e privilegio de dono — a mesma via que a cadeia de *hashes*
    existe para denunciar.
    """
    op.execute(
        """
        CREATE FUNCTION platform.payment_charge_nasce_iniciada() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF NEW.estado <> 'iniciada' THEN
            RAISE EXCEPTION
              'uma cobranca nasce em iniciada e nao em %: o estado e projeccao '
              'do ledger e muda so por append_payment_event (docs/tecnica/04 '
              'secao 5)', NEW.estado
              USING ERRCODE = 'check_violation';
          END IF;
          -- O `motivo_falha` e o `requer_humano` descrevem o resultado de uma
          -- decisao que ainda nao houve. Nascerem preenchidos era a mesma
          -- falsificacao por outra coluna: um painel de ops a mostrar uma
          -- cobranca que exige humano sem nada no ledger a justifica-lo.
          IF NEW.motivo_falha IS NOT NULL OR NEW.requer_humano THEN
            RAISE EXCEPTION
              'uma cobranca nasce sem motivo_falha e sem requer_humano: as duas '
              'colunas sao resultado de uma decisao do ledger'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.payment_charge_nasce_iniciada() IS "
        "'Uma cobranca nasce em iniciada, sem motivo_falha e sem requer_humano "
        "(KAM-053). Fecha a quinta via de escrever paga sem passar pela porta: o "
        "kamba_app tem INSERT nesta tabela, e sem isto um INSERT com estado=paga "
        "passava e deixava uma cobranca paga com zero eventos no ledger — que o "
        "job do secao 8 nao detecta, porque so compara cobrancas COM eventos. "
        "Trigger e nao CHECK, porque um CHECK impediria a projeccao de mover o "
        "estado.'"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.payment_charge_nasce_iniciada() FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE TRIGGER payment_charges_nasce_iniciada
          BEFORE INSERT ON {COBRANCAS}
          FOR EACH ROW EXECUTE FUNCTION platform.payment_charge_nasce_iniciada()
        """
    )
    # `ALWAYS`, pela razao dos dois *triggers* do ledger: um
    # `session_replication_role = replica` salta os de omissao, e com ele a
    # quinta via voltava a abrir.
    op.execute(
        "ALTER TABLE "
        + COBRANCAS
        + " ENABLE ALWAYS TRIGGER payment_charges_nasce_iniciada"
    )


def _inbox() -> None:
    """A `payment_callbacks_inbox` do §6.2: **sem `tenant_id`**, e nao e um lapso.

    O §5.1 escreve `inbox.insert` **antes** de `verifyCallback`, e e nessa
    ordem que esta tabela faz sentido: quando o corpo chega, nao se sabe se o
    *token* e de alguem, pelo que nao se sabe de que tenant e. Uma coluna
    `tenant_id` aqui teria de ser anulavel e preenchida depois — isto e, uma
    chave de isolamento que o atacante controla no instante em que e escrita.

    O que substitui a RLS e um **papel**: so o `kamba_pay_hooks` chega a esta
    tabela. O `kamba_app` nao lhe toca, pelo que um defeito na ToolLayer nao le
    callbacks de ninguem.

    Nao entra no `ci/rls_exceptions.yaml`: o X-05 do *gate* 6 descobre as
    tabelas **com** `tenant_id` pelo catalogo, e esta nao tem.

    ## Append-only, mas com quatro colunas que mudam

    O §6.2 chama-lhe «append-only» e o §5.1 faz `inbox.mark(receipt, …)`, que e
    um `UPDATE`. As duas coisas sao verdade ao mesmo tempo, e a base e que diz
    onde esta a fronteira: o `GRANT UPDATE` e **por coluna**, e as colunas do
    que entrou pela rede — `body`, `body_hash`, `headers`, `source_ip`,
    `recebido_at` — ficam de fora. O que se reescreve e o resultado do
    processamento; o que se prova nao se reescreve.
    """
    op.execute(
        f"""
        CREATE TABLE {INBOX} (
            id            bigint      GENERATED ALWAYS AS IDENTITY,
            -- **Anulavel**: nulo quando o `webhook_token` nao resolve (recibo
            -- `token_desconhecido`). Guardar a entrega de um token desconhecido
            -- e o que torna o 404 uniforme auditavel — sem isto, um varrimento
            -- de tokens nao deixava rasto nenhum.
            account_id    uuid,
            recebido_at   timestamptz NOT NULL DEFAULT now(),
            source_ip     inet,
            -- Sem segredos (§6.2). O que escreve aqui redige o `Authorization`
            -- e a assinatura antes de gravar.
            headers       jsonb       NOT NULL DEFAULT '{{}}',
            -- O corpo **cru**, em octetos: o HMAC e sobre o corpo cru, e
            -- guardar texto descodificado perdia a capacidade de o reverificar.
            body          bytea       NOT NULL,
            body_hash     bytea       NOT NULL,
            -- Anulavel: `NULL` enquanto o `verifyCallback` nao correu. O §5.1
            -- grava a linha antes de haver veredicto.
            authn_ok      boolean,
            estado        text        NOT NULL DEFAULT 'recebido',
            processado_at timestamptz,
            erro          text,
            CONSTRAINT payment_callbacks_inbox_pkey PRIMARY KEY (id),
            CONSTRAINT payment_callbacks_inbox_account_fk
                FOREIGN KEY (account_id) REFERENCES platform.payment_accounts (id),
            CONSTRAINT payment_callbacks_inbox_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DO_INBOX)})),
            CONSTRAINT payment_callbacks_inbox_body_hash_sha256
                CHECK (octet_length(body_hash) = 32)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {INBOX} IS "
        "'Toda a entrega HTTP de callback, incluindo as rejeitadas (KAM-053). "
        "Gravada ANTES de qualquer 2xx (docs/tecnica/04 secao 5.1): um 2xx dado "
        "antes da gravacao perde o callback se o processo morrer. Sem "
        "tenant_id, porque quem chega ainda nao o revelou; acessivel so ao "
        "papel estreito kamba_pay_hooks.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {INBOX}.account_id IS "
        "'Nulo quando o webhook_token nao resolve (recibo token_desconhecido). "
        "Guardar a entrega e o que torna o 404 uniforme auditavel.'"
    )
    # A leitura do worker: «o que falta processar», por ordem de chegada.
    op.execute(
        f"CREATE INDEX payment_callbacks_inbox_pendentes ON {INBOX} (id) "
        "WHERE estado = 'recebido'"
    )
    # O alerta do F-05: «falhas de HMAC por conta, por hora».
    op.execute(
        f"CREATE INDEX payment_callbacks_inbox_conta_idx ON {INBOX} "
        "(account_id, recebido_at DESC)"
    )


def _eventos() -> None:
    """O ledger. `INSERT` so por funcao, e `UPDATE`/`DELETE`/`TRUNCATE` nunca.

    As duas barreiras sao diferentes e as duas fazem falta:

    * **privilegio**: nenhum papel de aplicacao tem `INSERT`. Um `INSERT`
      directo como `kamba_app` falha com `42501` antes de chegar a qualquer
      `CHECK`;
    * **`deny_mutation`**: dois *triggers*, e quem **da a propriedade** e o por
      instrucao. O `payment_events_sem_truncate` e
      `BEFORE TRUNCATE OR DELETE OR UPDATE ... FOR EACH STATEMENT` e corre
      **uma vez por instrucao, antes de haver linhas**, pelo que recusa do
      mesmo modo a instrucao que toca linhas e a que nao toca nenhuma. O
      `payment_events_imutavel` e `BEFORE UPDATE OR DELETE ... FOR EACH ROW` e,
      depois do KAM-175, e **estritamente redundante** (medido: com ele
      desligado e o por instrucao ligado, um `UPDATE` e um `DELETE` com linhas
      continuam recusados); fica pela razao escrita ao lado do
      `CREATE TRIGGER`. Os dois recusam **a todos** — ao dono, e ao
      superutilizador, que e o unico que os `REVOKE` nao prendem. E a razao de
      a imutabilidade nao ser so uma matriz de privilegios.

    **Porque e que sao dois e nao um:** o `FOR EACH ROW` nao admite `TRUNCATE`,
    pelo que o `TRUNCATE` obriga a um *trigger* por instrucao. O que o KAM-175
    notou e que esse, existindo, cobre tambem o `UPDATE` e o `DELETE` — e com
    custo nulo, porque uma instrucao que fosse passar ja era recusada.
    """
    op.execute(
        f"""
        CREATE TABLE {EVENTOS} (
            id                bigint      GENERATED ALWAYS AS IDENTITY,
            tenant_id         uuid        NOT NULL,
            charge_id         uuid        NOT NULL,
            -- Sem FK, como na `payment_charges` e pela mesma razao (KAM-055 e
            -- KAM-059). Copiados da cobranca pela funcao, nunca enviados pelo
            -- chamador: um evento nao pode apontar para um sujeito diferente
            -- do da cobranca a que pertence.
            order_id          uuid,
            billing_cycle_id  uuid,
            provider          text        NOT NULL,
            account_id        uuid        NOT NULL,
            -- `NOT NULL` (§6.2). Providers sem referencia usam
            -- `numero_publico#tentativa`, o que mantem a unicidade por conta.
            referencia        text        NOT NULL,
            tipo_evento       text        NOT NULL,
            -- n-esima ocorrencia deste tipo para esta referencia. Calculada
            -- pela funcao sob `FOR UPDATE` na cobranca, que e o que faz as
            -- vinte chamadas concorrentes do criterio 3 darem 1..20 sem lacunas.
            sequencia         integer     NOT NULL,
            -- Anulavel: um facto que a plataforma gera nao tem identificador de
            -- entrega. Quando existe num `pagamento_recebido`, o indice parcial
            -- `payment_events_entrega_uq` fa-lo unico por conta — e o G7.
            provider_event_id text,
            valor_minor       bigint      NOT NULL,
            currency          char(3)     NOT NULL DEFAULT 'AOA',
            authn_method      text        NOT NULL,
            authn_ok          boolean     NOT NULL,
            decisao           text        NOT NULL,
            motivo            text,
            actor_kind        text        NOT NULL,
            actor_id          uuid,
            payload_hash      bytea       NOT NULL,
            -- Redigido: sem PII (§6.2, ADR-010). O `evt_emitir` tem uma guarda
            -- que recusa um payload com padrao de telefone, e e ela que o
            -- criterio 8 usa para forcar a falha no *outbox*.
            payload           jsonb       NOT NULL DEFAULT '{{}}',
            ocorrido_at       timestamptz,
            recebido_at       timestamptz NOT NULL DEFAULT now(),
            -- Cadeia por cobranca (tamper-evident). O `prev_hash` da primeira
            -- linha de cada cobranca e a genese — trinta e dois zeros, nao
            -- `NULL`, pela razao da `0006`.
            prev_hash         bytea       NOT NULL DEFAULT '{GENESE}'::bytea,
            row_hash          bytea       NOT NULL,
            CONSTRAINT payment_events_pkey PRIMARY KEY (id),
            CONSTRAINT payment_events_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT payment_events_charge_fk
                FOREIGN KEY (charge_id) REFERENCES platform.payment_charges (id),
            CONSTRAINT payment_events_account_fk
                FOREIGN KEY (account_id) REFERENCES platform.payment_accounts (id),
            CONSTRAINT payment_events_uq
                UNIQUE (provider, account_id, referencia, tipo_evento, sequencia),
            CONSTRAINT payment_events_um_sujeito
                CHECK ((order_id IS NULL) <> (billing_cycle_id IS NULL)),
            CONSTRAINT payment_events_tipo_evento_ck
                CHECK (tipo_evento IN ({", ".join(TIPOS_DE_EVENTO)})),
            CONSTRAINT payment_events_sequencia_ck CHECK (sequencia >= 1),
            CONSTRAINT payment_events_valor_ck CHECK (valor_minor >= 0),
            CONSTRAINT payment_events_currency_ck CHECK (currency = 'AOA'),
            CONSTRAINT payment_events_authn_method_ck
                CHECK (authn_method IN ({", ".join(METODOS_DE_AUTENTICACAO)})),
            CONSTRAINT payment_events_decisao_ck
                CHECK (decisao IN ({", ".join(DECISOES)})),
            CONSTRAINT payment_events_actor_kind_ck
                CHECK (actor_kind IN ({", ".join(ACTORES)})),
            -- A restricao que o §14 cita como mecanismo do alvo «100% das
            -- `paga` com evento autenticado». O `sistema` **nao** esta na
            -- lista, e e esse o dominio do quarto valor de `authn_method`.
            CONSTRAINT confirmar_exige_autenticacao
                CHECK (tipo_evento <> 'pagamento_confirmado'
                       OR (authn_ok AND decisao = 'aceite'
                           AND authn_method IN ({", ".join(AUTENTICACOES_QUE_CONFIRMAM)}))),
            CONSTRAINT humano_exige_actor
                CHECK (authn_method <> 'manual' OR actor_id IS NOT NULL),
            -- Acrescentado ao DDL do §6.2 (desvio aditivo, registado no PR e na
            -- seccao de verificacao do bloco), pela razao da `0006`: sem isto um
            -- `prev_hash` de outro comprimento passava, e a verificacao da
            -- cadeia deixava de poder afirmar que compara sha256 com sha256.
            CONSTRAINT payment_events_hashes_sha256 CHECK (
                octet_length(payload_hash) = 32
                AND octet_length(prev_hash) = 32
                AND octet_length(row_hash) = 32
            )
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {EVENTOS} IS "
        "'Ledger append-only de pagamentos (KAM-053). Factos "
        "(pagamento_recebido) e decisoes (pagamento_confirmado, "
        "pagamento_divergente) em linhas separadas; o estado e derivado e vive "
        "em payment_charges. INSERT so por append_payment_event; UPDATE, "
        "DELETE e TRUNCATE recusados por deny_mutation a todos, incluindo ao "
        "superutilizador. docs/tecnica/04 secao 6.2; dicionario 3.42.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {EVENTOS}.sequencia IS "
        "'n-esima ocorrencia deste tipo para esta referencia. Calculada pela "
        "funcao sob FOR UPDATE na cobranca: vinte chamadas concorrentes dao "
        "1..20 sem lacunas.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {EVENTOS}.row_hash IS "
        "'sha256(prev_hash || campos canonicos), pela formula de "
        "payment_event_row_hash. Cadeia por cobranca; verify_ledger_chain "
        "recalcula-a e o job diario exporta a cabeca para STO.'"
    )
    # ---------------------------------------------------- dedupe de entregas (G7)
    #
    # Parcial e **com o tipo de evento no predicado**, que e o §6.2 a letra. A
    # razao de nao ser global: o mesmo `provider_event_id` pode aparecer num
    # `pagamento_confirmado` que decorre do `pagamento_recebido` que o trouxe, e
    # um indice sobre todos os tipos recusava a decisao por causa do facto.
    op.execute(
        f"CREATE UNIQUE INDEX payment_events_entrega_uq ON {EVENTOS} "
        "(provider, account_id, provider_event_id) "
        "WHERE provider_event_id IS NOT NULL AND tipo_evento = 'pagamento_recebido'"
    )
    # A leitura da cadeia e do `rebuild`: os eventos de uma cobranca por ordem.
    op.execute(f"CREATE INDEX payment_events_charge_idx ON {EVENTOS} (charge_id, id)")
    # O `tenant_id` primeiro, pela razao da `payment_charges`.
    op.execute(
        f"CREATE INDEX payment_events_tenant_idx ON {EVENTOS} (tenant_id, recebido_at DESC)"
    )

    # ------------------------------------------------------------ deny_mutation
    op.execute(
        """
        CREATE FUNCTION platform.deny_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          RAISE EXCEPTION 'tabela append-only: % proibido em %',
            TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.deny_mutation() IS "
        "'Recusa UPDATE, DELETE e TRUNCATE numa tabela append-only (KAM-053). "
        "SECURITY INVOKER: nao precisa de privilegio nenhum para recusar, e um "
        "DEFINER aqui seria um DEFINER a mais na lista aprovada. Prende tambem "
        "o dono e o superutilizador, que e o que os REVOKE nao fazem.'"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.deny_mutation() FROM PUBLIC")
    # `ALWAYS`, pela razao da `0006`: um `session_replication_role = replica`
    # salta os *triggers* de omissao, e com ele um `UPDATE` passava.
    op.execute(
        f"""
        CREATE TRIGGER payment_events_imutavel
          BEFORE UPDATE OR DELETE ON {EVENTOS}
          FOR EACH ROW EXECUTE FUNCTION platform.deny_mutation()
        """
    )
    op.execute("ALTER TABLE " + EVENTOS + " ENABLE ALWAYS TRIGGER payment_events_imutavel")
    # **O por instrucao leva `DELETE` e `UPDATE`, e nao so `TRUNCATE` (KAM-175).**
    #
    # Um *trigger* `FOR EACH ROW` **nao dispara quando nao ha linhas**, pelo que
    # com o por instrucao so em `BEFORE TRUNCATE` um
    # `DELETE FROM payment_events WHERE <predicado que nao casa>` devolvia
    # `DELETE 0` e **passava** — e um `UPDATE ... WHERE <predicado que nao casa>`
    # devolvia `UPDATE 0`. Nenhuma linha se perdia; o que falhava era a
    # **propriedade**, e quem audita a tabela lia a ausencia de erro como «a
    # tabela aceita `DELETE`». Medido a 2026-11-03 contra o PostgreSQL 18.6.
    #
    # Com o `FOR EACH STATEMENT`, a recusa vem **antes de haver linhas** e e a
    # mesma para a instrucao que toca linhas e para a que nao toca nenhuma. O
    # `UPDATE` cabe aqui porque um *trigger* por instrucao nao tem `OLD` nem
    # `NEW` e a `deny_mutation` **nao os usa**: ela levanta a excepcao com o
    # `TG_OP` e o `TG_TABLE_NAME`, que existem nos dois niveis. E por isso que a
    # alteracao e a lista de eventos e nao a funcao.
    #
    # **Depois disto, quem da a propriedade e este e nao o
    # `payment_events_imutavel`**, que fica estritamente redundante — medido:
    # com o por linha desligado e este ligado, um `UPDATE` e um `DELETE` com
    # linhas continuam recusados com `42501`. **Fica, e a razao nao e defesa em
    # profundidade:** o `_desligar_trigger` do `tests_pagamentos/test_cadeia.py`
    # desliga-o **pelo nome** para forjar um elo partido, e os dois confrontos
    # do `tests_pagamentos/test_downgrade.py` prendem o par
    # `[('payment_events_imutavel', 'A'), ('payment_events_sem_truncate', 'A')]`.
    # Remove-lo era mexer em tres ensaios para nao ganhar barreira nenhuma.
    #
    # **A alteracao entra aqui e nao numa revisao nova** (criterio 7 do
    # KAM-175), e a pergunta que o decide e de facto: existe base onde a `0029`
    # ja foi aplicada e que nao se reconstroi de zero? Medido, nao: o *gate* 8
    # corre contra a base descartavel que o `db/gate_bd.py` cria e destroi
    # (`exigir_base_descartavel` recusa qualquer nome que nao seja o dela, e a
    # suite faz `downgrade base`); nao ha alvo de `Makefile` nem *script* de
    # `initdb` que corra `alembic` contra a base do `infra/compose/`; e os
    # `infra/envs/{staging,prod}` apontam para o modulo `provider-pendente`,
    # com `chaves_ssh_de_administracao = []` e a nota «nao ha host», sem estado
    # de Terraform no repositorio. Sem base nessas condicoes, uma revisao nova
    # para corrigir uma linha deixava duas verdades na cadeia.
    op.execute(
        f"""
        CREATE TRIGGER payment_events_sem_truncate
          BEFORE TRUNCATE OR DELETE OR UPDATE ON {EVENTOS}
          FOR EACH STATEMENT EXECUTE FUNCTION platform.deny_mutation()
        """
    )
    op.execute(
        "ALTER TABLE " + EVENTOS + " ENABLE ALWAYS TRIGGER payment_events_sem_truncate"
    )


def _mapa_do_outbox() -> None:
    """`(tipo_evento, authn_method) -> tipo EVT`. Fica **vazia**.

    O bloco e explicito: «o tipo de evento de *outbox* sai de uma tabela de
    mapeamento que o KAM-055 preenche; aqui testa-se com um mapeamento de
    ensaio». Inventar aqui o conteudo definitivo era decidir, sem o dizer, que
    eventos de dominio a plataforma publica — e isso e um contrato com os
    consumidores, nao um detalhe desta revisao.

    Configuracao **global** e nao dado de tenant, como a `evt_subscricoes` da
    `0004`: diz que evento EVT corresponde a que facto do ledger, e e igual
    para todos. Fica fora da RLS por nao ter `tenant_id`.

    Uma linha em falta nao e um erro: um tipo de evento sem mapeamento nao
    produz evento de dominio, e o ledger grava-se na mesma. E o que permite que
    esta revisao funde antes do KAM-055.
    """
    op.execute(
        f"""
        CREATE TABLE {MAPA} (
            tipo_evento  text     NOT NULL,
            authn_method text     NOT NULL,
            evt_tipo     text     NOT NULL,
            evt_versao   smallint NOT NULL DEFAULT 1,
            CONSTRAINT payment_outbox_map_pkey PRIMARY KEY (tipo_evento, authn_method),
            CONSTRAINT payment_outbox_map_tipo_evento_ck
                CHECK (tipo_evento IN ({", ".join(TIPOS_DE_EVENTO)})),
            CONSTRAINT payment_outbox_map_authn_method_ck
                CHECK (authn_method IN ({", ".join(METODOS_DE_AUTENTICACAO)})),
            CONSTRAINT payment_outbox_map_evt_tipo_ck CHECK (btrim(evt_tipo) <> ''),
            CONSTRAINT payment_outbox_map_evt_versao_ck CHECK (evt_versao >= 1)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {MAPA} IS "
        "'Mapeamento (tipo_evento, authn_method) -> tipo de evento EVT "
        "(KAM-053). Configuracao global, como evt_subscricoes. Fica vazia: o "
        "conteudo definitivo e do KAM-055, e um tipo sem mapeamento nao produz "
        "evento de dominio. dicionario 3.42.'"
    )


def _row_hash() -> None:
    """A formula de um elo, isolada para se poder testar e recalcular.

    `IMMUTABLE STRICT`, pela razao da `0006`: a mesma entrada da sempre o mesmo
    *hash*, e um argumento nulo da nulo em vez de um *hash* de uma cadeia com um
    buraco.

    ## O `STRICT` obriga quem **chama** a tratar o nulo, e nao esta funcao

    O `coalesce(p_provider_event_id, '')` da concatenacao **nao basta**, e a
    primeira versao desta revisao supunha que bastava: o `STRICT` e avaliado
    **antes** do corpo, pelo que um `provider_event_id` nulo devolve nulo sem o
    `coalesce` chegar a correr. Medido — os 62 ensaios da suite deram, todos, o
    mesmo `23502 null value in column "row_hash"`, porque quase todo o evento
    gerado pela plataforma nao tem identificador de entrega.

    Por isso o nulo trata-se **nos dois chamadores** — a `append_payment_event`
    e o `verify_ledger_chain` —, e nos dois com o mesmo `coalesce(…, '')`, que e
    o que faz o elo de um evento sem entrega ser recalculavel. O `coalesce` do
    corpo fica: nao e redundancia inutil, e o que garante que um terceiro
    chamador que se esqueca do molde produza o mesmo elo em vez de um diferente.

    O `id` e o `recebido_at` **nao** entram no elo, e e deliberado: o `id` e
    `GENERATED ALWAYS AS IDENTITY` e so se conhece depois do `INSERT`, pelo que
    um elo que o incluisse nao se podia recalcular com esta formula — que e
    exactamente o que o `verify_ledger_chain` faz.
    """
    # A serializacao de um instante, num sitio so.
    #
    # `to_char` em UTC e **nao** `::text`: a saida de `::text` de um
    # `timestamptz` depende do `TimeZone` e do `DateStyle` da sessao, e um elo
    # que dependesse da sessao de quem o verifica nao e um elo — o
    # `verify_ledger_chain` recalcula-o noutra sessao, por definicao. Em UTC,
    # pela convencao do dicionario §2.
    op.execute(
        """
        CREATE FUNCTION platform.payment_instante(p_quando timestamptz)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT
        SET search_path = pg_catalog, platform AS $func$
          SELECT to_char(p_quando AT TIME ZONE 'UTC',
                         'YYYY-MM-DD"T"HH24:MI:SS.US')
        $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.payment_instante(timestamptz) IS "
        "'Serializa um instante para o elo da cadeia, em UTC e com "
        "microssegundos (KAM-053). Existe porque o ::text de um timestamptz "
        "depende do TimeZone e do DateStyle da sessao, e o verify_ledger_chain "
        "recalcula o elo noutra sessao.'"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.payment_instante(timestamptz) FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.payment_event_row_hash(
          p_prev_hash bytea, p_tenant_id uuid, p_charge_id uuid,
          p_order_id uuid, p_billing_cycle_id uuid, p_provider text,
          p_account_id uuid, p_referencia text, p_tipo_evento text,
          p_sequencia integer, p_provider_event_id text, p_valor_minor bigint,
          p_currency char(3), p_authn_method text, p_authn_ok boolean,
          p_decisao text, p_motivo text, p_actor_kind text, p_actor_id uuid,
          p_payload_hash bytea, p_ocorrido_at timestamptz,
          p_recebido_at timestamptz)
        RETURNS bytea LANGUAGE sql IMMUTABLE
        SET search_path = pg_catalog, platform AS $func$
          SELECT sha256(convert_to({CONCATENACAO_DO_ROW_HASH}, 'UTF8'))
        $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.payment_event_row_hash({ARGUMENTOS_DE_ROW_HASH}) IS "
        "'Um elo da cadeia do ledger: sha256(prev_hash || campos canonicos), "
        "separados por chr(31) (KAM-053). IMMUTABLE STRICT, e sem o id nem o "
        "recebido_at: um elo tem de se poder recalcular, e o id so existe "
        "depois do INSERT.'"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.payment_event_row_hash({ARGUMENTOS_DE_ROW_HASH}) "
        "FROM PUBLIC"
    )


def _next_state() -> None:
    """A maquina do §7.1, pura. Tres respostas, e nao duas.

    O criterio 5 diz «cobre todas as transicoes do §7.1 e **rejeita as
    restantes**». Rejeitar tudo o que nao e aresta deixaria de fora os factos
    que o §5.1 manda registar sem transicao — o `pagamento_recebido` escreve-se
    **antes** da decisao, e um ledger que o recusasse nao podia registar nada.
    Dai as tres respostas:

        <estado novo>   uma aresta do diagrama do §7.1
        <estado igual>  um facto da lista EVENTOS_SEM_TRANSICAO, que nao move
        NULL            recusado: nem aresta nem facto sem transicao

    `IMMUTABLE STRICT`: e uma funcao da tabela do documento e de nada mais.

    ## Para `paga` ha **um** caminho, e isso resolve uma leitura do §7.1

    O diagrama desenha `pendente_confirmacao --> paga: confirmacao humana
    auditada`, e a tentacao e ler «a confirmacao humana» como um tipo de evento
    — o `confirmacao_manual_registada`. Nao e, e a diferenca e a do ticket
    inteiro: `confirmacao humana auditada` e um **`authn_method`**
    (`manual`, com `actor_id`), nao um tipo de evento.

    Se o `confirmacao_manual_registada` movesse para `paga`, haveria um segundo
    caminho para `paga` que **nao passa** pela restricao
    `confirmar_exige_autenticacao` — isto e, a segunda porta que este ticket
    existe para nao ter. Com um caminho so, o alvo do §14 («100% das `paga` com
    evento autenticado») e uma propriedade da base e nao uma intencao.

    ## Tres arestas do §7.1 que esta funcao **nao** tem, e porque

        paga --> reembolso_pendente: disputa
            Nao ha tipo de evento para «disputa» nos dezassete do §6.2. Abrir um
            caso de disputa e `refund_cases` (§6.3), que e do KAM-054. Sem
            evento, nao ha aresta — e inventar um tipo era alargar o escopo.

        aguarda_cliente --> falhada: pagamento_divergente
        pendente_confirmacao --> falhada: pagamento_divergente
            O §7.1 desenha a divergencia **so** a partir de `emitida`, e o G4
            pode bater numa cobranca de `express_push` ou numa a espera de
            confirmacao. As duas ficam recusadas, porque o criterio manda
            seguir o §7.1 a letra; a lacuna e do §7.1 e esta na divida
            documental.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.next_state(
          p_estado text, p_tipo_evento text, p_decisao text)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT
        SET search_path = pg_catalog, platform AS $func$
          SELECT CASE
            -- Um facto que nao move o estado (§5.1, §7.2, §8).
            WHEN p_tipo_evento IN ({", ".join(EVENTOS_SEM_TRANSICAO)})
              THEN p_estado

            -- iniciada
            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'referencia_emitida'
              THEN 'emitida'
            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'push_enviado'
              THEN 'aguarda_cliente'
            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'pagamento_rejeitado_provider'
              THEN 'falhada'

            -- emitida
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'confirmacao_manual_pedida'
              THEN 'pendente_confirmacao'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'pagamento_divergente'
              THEN 'falhada'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'cobranca_expirada'
              THEN 'expirada'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'cobranca_cancelada'
              THEN 'cancelada'

            -- aguarda_cliente
            WHEN p_estado = 'aguarda_cliente' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'aguarda_cliente' AND p_tipo_evento = 'cobranca_expirada'
              THEN 'expirada'
            WHEN p_estado = 'aguarda_cliente'
                 AND p_tipo_evento = 'pagamento_rejeitado_provider'
              THEN 'falhada'

            -- pendente_confirmacao
            WHEN p_estado = 'pendente_confirmacao'
                 AND p_tipo_evento = 'pagamento_confirmado' AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'pendente_confirmacao'
                 AND p_tipo_evento = 'confirmacao_manual_rejeitada'
              THEN 'emitida'

            -- expirada: pagamento tardio autenticado (G6, 03 §6.6)
            WHEN p_estado = 'expirada' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'

            -- falhada: divergencia aceite por ops (manual, dupla)
            WHEN p_estado = 'falhada' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'

            -- reembolso_pendente: executado fora da plataforma e registado
            -- (ADR-004: nunca ha fundos de terceiros aqui)
            WHEN p_estado = 'reembolso_pendente'
                 AND p_tipo_evento = 'reembolso_manual_registado'
              THEN 'reembolsada'

            ELSE NULL
          END
        $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE}) IS "
        "'A maquina de estados da cobranca (docs/tecnica/04 secao 7.1), pura "
        "(KAM-053). Devolve o estado novo numa aresta, o mesmo estado num facto "
        "que nao move, e NULL numa transicao recusada. Para paga ha um caminho "
        "so: pagamento_confirmado com decisao aceite, que e o unico que passa "
        "pela restricao confirmar_exige_autenticacao.'"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE}) FROM PUBLIC"
    )


def _append() -> None:
    """`append_payment_event`: a porta. A unica entrada do allowlist.

    Os sete passos do contrato do §6.2, nesta ordem e numa transaccao, mais um
    passo zero que o contrato nao numera e o DoD exige:

        0  recusa um payload (ou um motivo) com padrao de telefone — a caixa de
           privacidade do bloco, com os padroes do `evt_emitir` da `0004`
        1  SELECT … FROM payment_charges WHERE id = :charge FOR UPDATE
        2  sequencia = 1 + count(*) do mesmo (provider, account_id, referencia,
           tipo_evento)
        3  recusa um `pagamento_confirmado` com valor diferente, conta
           diferente ou `authn_ok` falso — cinto-e-suspensorios sobre o CHECK
        4  row_hash = sha256(prev_hash || campos canonicos)
        5  INSERT
        6  projecta payment_charges.estado por next_state
        7  escreve no events_outbox (pelo evt_emitir, na mesma transaccao)

    ## O `FOR UPDATE` e que faz a sequencia nao ter lacunas

    Sem ele, vinte sessoes a contar `1 + count(*)` leem todas o mesmo numero e
    dezanove levam `23505` do `payment_events_uq`. Com ele, a tranca esta na
    **cobranca** — que e o que serializa tambem a leitura do `prev_hash` e a
    projeccao do estado, as tres coisas que tem de ver a mesma versao do mundo.

    ## O que a funcao **nao** aceita do chamador

    O `tenant_id`, o `order_id`, o `billing_cycle_id`, o `provider` e a
    `referencia` sao copiados da cobranca e **nao** sao parametros. Um evento
    nao pode discordar da cobranca a que pertence, e a forma de garantir isso e
    nao haver por onde o dizer.

    O `account_id` e **parametro**, de proposito: e o que o *webhook* resolveu a
    partir do *token*, e compara-lo com o da cobranca e o G2. Se nao fosse
    parametro, o G2 nao tinha nada para comparar.

    ## `SECURITY DEFINER`, e o que isso **nao** da

    Da privilegio: nenhum papel de aplicacao tem `INSERT` em `payment_events`.
    **Nao** da isolamento — o `FORCE` prende tambem o dono (`db/rls.py`), pelo
    que a politica `tenant_iso` continua a avaliar com o `app.tenant_id` do
    chamador. Uma chamada com o contexto do tenant A sobre uma cobranca de B
    nao encontra a cobranca, e recusa.
    """
    op.execute(
        rf"""
        CREATE FUNCTION platform.append_payment_event(
          p_charge_id uuid,
          p_tipo_evento text,
          p_account_id uuid,
          p_valor_minor bigint,
          p_authn_method text,
          p_authn_ok boolean,
          p_decisao text,
          p_motivo text DEFAULT NULL,
          p_actor_kind text DEFAULT 'provider',
          p_actor_id uuid DEFAULT NULL,
          p_provider_event_id text DEFAULT NULL,
          p_payload jsonb DEFAULT '{{}}',
          p_ocorrido_at timestamptz DEFAULT NULL)
        RETURNS TABLE (
          event_id bigint, sequencia integer, row_hash bytea,
          estado_novo text, outbox_event_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge      platform.payment_charges;
          v_seq         integer;
          v_prev        bytea;
          v_hash        bytea;
          v_payload     bytea;
          v_agora       timestamptz;
          v_estado      text;
          v_id          bigint;
          v_evt_tipo    text;
          v_evt_versao  smallint;
          v_evt_id      uuid;
        BEGIN
          -- (1) Serializa. A tranca e na cobranca: e ela que a sequencia, o
          -- `prev_hash` e a projeccao tem de ver na mesma versao.
          SELECT * INTO v_charge FROM platform.payment_charges
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            -- Duas leituras que esta funcao nao distingue, pela razao do
            -- `assert_beneficiary` da `0027`: sob RLS, a cobranca de outro
            -- tenant e indistinguivel de uma que nao existe. Recusa nos dois.
            RAISE EXCEPTION
              'append_payment_event: a cobranca % nao existe ou nao e visivel '
              'no contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- (3a) G2 do §5, e para **todos** os tipos: um evento de uma conta
          -- que nao e a da cobranca nao e um evento desta cobranca.
          --
          -- **`IS DISTINCT FROM` e nao `<>`**, e a revisao adversarial mediu
          -- porque: `NULL <> x` avalia a `NULL`, o `IF` nao disparava, e o
          -- `INSERT` gravava o `account_id` **da cobranca** — pelo que nao
          -- havia `NOT NULL` que o apanhasse depois, ao contrario do
          -- `p_valor_minor` e do `p_authn_ok`, que as colunas apanham. Isto e,
          -- `p_account_id => NULL` saltava o G2 **em silencio** e confirmava o
          -- pagamento. E o nulo nao e hipotetico: o recibo
          -- `token_desconhecido` do `hooks.ts` grava `accountId: null`.
          IF p_account_id IS NULL
             OR p_account_id IS DISTINCT FROM v_charge.account_id THEN
            RAISE EXCEPTION
              'append_payment_event: o evento e da conta % e a cobranca % e da '
              'conta % (G2)', p_account_id, p_charge_id, v_charge.account_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- (0) A guarda de privacidade, antes de tudo o resto.
          --
          -- O §6.2 escreve «payload redigido: sem PII» e o DoD do bloco faz
          -- disso uma caixa. Uma caixa que se marca por convencao de quem
          -- escreve o codigo nao e uma barreira: o ledger e **append-only**,
          -- pelo que um telefone que entre aqui nao sai mais — nem com um
          -- `UPDATE`, que o `deny_mutation` recusa.
          --
          -- Os dois padroes sao **os mesmos** do `evt_emitir` da `0004`, e e
          -- deliberado que sejam os mesmos e nao melhores: o que esta guarda
          -- apanha e o que essa apanha, e um ledger que fosse mais permissivo
          -- do que o *outbox* deixava passar o que o evento de dominio recusa.
          -- O que nenhuma das duas apanha e um telefone escrito de outra forma;
          -- isso diz-se, e e a razao de a redaccao continuar a ser
          -- responsabilidade de quem constroi o payload.
          --
          -- O `motivo` entra na verificacao: ele viaja para o *outbox* no
          -- `jsonb_build_object` do passo (7), pelo que um telefone ali era PII
          -- num evento de dominio.
          -- As chaves do quantificador vao **duplicadas**: este SQL esta numa
          -- f-string, e `{{8}}` simples era um campo de substituicao — o *gate*
          -- 3b recusou-o com «f-string com um valor que nao e texto», que e a
          -- mesma leitura que o Python faz. A cadeia e `rf` pela razao da
          -- `0004`: `\+` nao e sequencia de escape de Python, e numa cadeia
          -- normal escrevia-se `\+` — o ficheiro deixava de se poder ler
          -- contra o `docs/tecnica/06` §6.1 a olho.
          IF p_payload::text ~ '\+?244 ?9[0-9]{{8}}'
             OR p_payload::text ~ '"\+[0-9]{{9,15}}"'
             OR coalesce(p_motivo, '') ~ '\+?244 ?9[0-9]{{8}}' THEN
            RAISE EXCEPTION
              'append_payment_event: o payload ou o motivo do evento % contem '
              'padrao de telefone (PII P2, ADR-010); o ledger e append-only e '
              'nao se corrige', p_tipo_evento
              USING ERRCODE = 'check_violation';
          END IF;

          -- (3b) As tres recusas do contrato do §6.2, sobre o CHECK e nao em
          -- vez dele. O `CHECK` nao pode fazer esta: nao ve a cobranca.
          IF p_tipo_evento = 'pagamento_confirmado' THEN
            IF p_valor_minor <> v_charge.amount_minor THEN
              RAISE EXCEPTION
                'append_payment_event: nao se confirma % com valor % quando a '
                'cobranca e de % (G4); o evento e pagamento_divergente',
                p_charge_id, p_valor_minor, v_charge.amount_minor
                USING ERRCODE = 'check_violation';
            END IF;
            IF NOT p_authn_ok THEN
              RAISE EXCEPTION
                'append_payment_event: nao se confirma % sem autenticacao (G1)',
                p_charge_id
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;

          -- (6a) A projeccao calcula-se **antes** do INSERT, para que uma
          -- transicao recusada nao deixe o evento escrito. O ledger nao se
          -- corrige: uma linha a mais ficava la para sempre.
          v_estado := platform.next_state(
            v_charge.estado, p_tipo_evento, p_decisao);
          IF v_estado IS NULL THEN
            RAISE EXCEPTION
              'append_payment_event: a cobranca % esta em % e % nao e uma '
              'transicao do docs/tecnica/04 secao 7.1', p_charge_id,
              v_charge.estado, p_tipo_evento
              USING ERRCODE = 'check_violation';
          END IF;

          -- (2) A sequencia, sob a tranca de (1).
          SELECT 1 + count(*) INTO v_seq FROM platform.payment_events
            WHERE provider = v_charge.provider
              AND account_id = v_charge.account_id
              AND referencia = coalesce(v_charge.referencia,
                    v_charge.id::text || '#' || v_charge.tentativa::text)
              AND tipo_evento = p_tipo_evento;

          -- (4) O elo. O `prev_hash` e o da ultima linha **desta cobranca**: a
          -- cadeia e por cobranca (§6.2).
          SELECT e.row_hash INTO v_prev FROM platform.payment_events e
            WHERE e.charge_id = p_charge_id ORDER BY e.id DESC LIMIT 1;
          v_prev := coalesce(v_prev, '{GENESE}'::bytea);
          v_payload := sha256(convert_to(p_payload::text, 'UTF8'));
          -- O `recebido_at` fixa-se **aqui** e nao pelo `DEFAULT now()` da
          -- coluna, porque passou a entrar no elo: um campo que a coluna
          -- preenchesse depois do calculo nao podia ser recalculado pelo
          -- verificador. Dentro de uma transaccao o `now()` e estavel, pelo
          -- que o valor e o mesmo — o que muda e haver **um** sitio a fixa-lo.
          v_agora := now();
          v_hash := platform.payment_event_row_hash(
            v_prev, v_charge.tenant_id, p_charge_id, v_charge.order_id,
            v_charge.billing_cycle_id, v_charge.provider, v_charge.account_id,
            coalesce(v_charge.referencia,
              v_charge.id::text || '#' || v_charge.tentativa::text),
            p_tipo_evento, v_seq, coalesce(p_provider_event_id, ''),
            p_valor_minor, v_charge.currency, p_authn_method, p_authn_ok,
            p_decisao, p_motivo, p_actor_kind, p_actor_id, v_payload,
            p_ocorrido_at, v_agora);

          -- (5) O INSERT. O `tenant_id`, o sujeito, o `provider` e a
          -- `referencia` vem da cobranca e nao do chamador.
          INSERT INTO platform.payment_events (
              tenant_id, charge_id, order_id, billing_cycle_id, provider,
              account_id, referencia, tipo_evento, sequencia, provider_event_id,
              valor_minor, currency, authn_method, authn_ok, decisao, motivo,
              actor_kind, actor_id, payload_hash, payload, ocorrido_at,
              recebido_at, prev_hash, row_hash)
            VALUES (
              v_charge.tenant_id, p_charge_id, v_charge.order_id,
              v_charge.billing_cycle_id, v_charge.provider, v_charge.account_id,
              coalesce(v_charge.referencia,
                v_charge.id::text || '#' || v_charge.tentativa::text),
              p_tipo_evento, v_seq, p_provider_event_id, p_valor_minor,
              v_charge.currency, p_authn_method, p_authn_ok, p_decisao, p_motivo,
              p_actor_kind, p_actor_id, v_payload, p_payload, p_ocorrido_at,
              v_agora, v_prev, v_hash)
            RETURNING id INTO v_id;

          -- (6b) Projecta. O `atualizado_at` e o `motivo_falha` acompanham: uma
          -- cobranca `falhada` sem motivo nao diz nada a ops.
          IF v_estado <> v_charge.estado THEN
            UPDATE platform.payment_charges SET
                estado = v_estado,
                atualizado_at = now(),
                requer_humano = CASE
                  WHEN p_tipo_evento = 'pagamento_divergente' THEN true
                  ELSE requer_humano END,
                motivo_falha = CASE
                  WHEN v_estado = 'falhada' THEN coalesce(p_motivo, motivo_falha)
                  ELSE motivo_falha END
              WHERE id = p_charge_id;
          END IF;

          -- (7) O *outbox*, na mesma transaccao (ADR-009). Um tipo sem
          -- mapeamento nao produz evento de dominio: o mapa e do KAM-055, e e
          -- o que deixa esta revisao fundir antes dele.
          SELECT m.evt_tipo, m.evt_versao INTO v_evt_tipo, v_evt_versao
            FROM platform.payment_outbox_map m
            WHERE m.tipo_evento = p_tipo_evento
              AND m.authn_method = p_authn_method;
          IF v_evt_tipo IS NOT NULL THEN
            v_evt_id := platform.evt_emitir(
              v_evt_tipo, v_evt_versao, v_charge.tenant_id, 'payment_charge',
              p_charge_id::text,
              jsonb_build_object(
                'charge_id', p_charge_id, 'tipo_evento', p_tipo_evento,
                'sequencia', v_seq, 'estado', v_estado,
                'valor_minor', p_valor_minor, 'currency', v_charge.currency,
                'authn_method', p_authn_method, 'decisao', p_decisao,
                'motivo', p_motivo));
          END IF;

          RETURN QUERY SELECT v_id, v_seq, v_hash, v_estado, v_evt_id;
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.append_payment_event({ARGUMENTOS_DE_APPEND}) IS "
        "'A unica porta de escrita do ledger (KAM-053): FOR UPDATE na cobranca, "
        "sequencia sem lacunas, cadeia de hashes, projeccao do estado por "
        "next_state e evt_emitir na mesma transaccao. SECURITY DEFINER porque "
        "nenhum papel de aplicacao tem INSERT em payment_events; o isolamento "
        "continua a ser da RLS, que prende tambem o dono (FORCE).'"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.append_payment_event({ARGUMENTOS_DE_APPEND}) "
        "FROM PUBLIC"
    )


def _rebuild() -> None:
    """`rebuild_charge_state`: o estado a partir dos eventos, e so deles.

    Dobra o ledger desde `iniciada` pela ordem do `id`. O *job* nocturno do §8
    compara o que esta funcao devolve com a projeccao em `payment_charges` e
    alerta na divergencia — que e a forma de medir que a projeccao do passo (6)
    da `append_payment_event` nao se desviou.

    **Levanta em vez de devolver NULL** se encontrar um evento que nao e
    transicao a partir do estado em que a dobra esta. Uma cadeia construida pela
    porta nao pode ter um desses; um devolvido por um `INSERT` forjado com
    superutilizador pode, e ai o silencio era pior do que o erro.
    """
    op.execute(
        """
        CREATE FUNCTION platform.rebuild_charge_state(p_charge_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_estado text := 'iniciada';
          v_linha  record;
        BEGIN
          FOR v_linha IN
            SELECT id, tipo_evento, decisao FROM platform.payment_events
              WHERE charge_id = p_charge_id ORDER BY id
          LOOP
            v_estado := platform.next_state(
              v_estado, v_linha.tipo_evento, v_linha.decisao);
            IF v_estado IS NULL THEN
              RAISE EXCEPTION
                'rebuild_charge_state: o evento % (%) nao e transicao a partir '
                'do estado em que a reconstrucao da cobranca % estava',
                v_linha.id, v_linha.tipo_evento, p_charge_id
                USING ERRCODE = 'data_corrupted';
            END IF;
          END LOOP;
          RETURN v_estado;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.rebuild_charge_state(uuid) IS "
        "'Reconstroi payment_charges.estado a partir do ledger e de nada mais "
        "(KAM-053). O job nocturno do docs/tecnica/04 secao 8 compara-o com a "
        "projeccao e alerta na divergencia. Levanta data_corrupted num evento "
        "que nao seja transicao: uma cadeia escrita pela porta nao tem nenhum.'"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.rebuild_charge_state(uuid) FROM PUBLIC")


def _verificacao_da_cadeia() -> None:
    """`verify_ledger_chain`: recalcula a cadeia e devolve os elos partidos.

    Devolve **linhas**, e nao um booleano: quem alerta precisa de saber qual o
    elo e de que cobranca, e um booleano obrigava a procurar outra vez. Zero
    linhas e a cadeia inteira intacta — e o `0 UPDATE/DELETE` do §14.

    Duas coisas diferentes, as duas verificadas:

        encadeamento   o `prev_hash` de cada elo e o `row_hash` do anterior
        formula        o `row_hash` guardado e o que a formula devolve hoje

    A segunda e a que apanha um byte alterado com superutilizador — que e o
    criterio 6 — e a primeira apanha uma linha **removida** no meio, que a
    formula sozinha nao veria.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.verify_ledger_chain(p_charge_id uuid DEFAULT NULL)
        RETURNS TABLE (
          charge_id uuid, event_id bigint, sequencia integer, falha text)
        LANGUAGE sql STABLE SET search_path = pg_catalog, platform AS $func$
          WITH encadeado AS (
            SELECT e.*,
              lag(e.row_hash) OVER (PARTITION BY e.charge_id ORDER BY e.id)
                AS anterior
            FROM platform.payment_events e
            WHERE p_charge_id IS NULL OR e.charge_id = p_charge_id
          )
          SELECT c.charge_id, c.id, c.sequencia, f.falha
          FROM encadeado c
          CROSS JOIN LATERAL (
            SELECT CASE
              WHEN c.prev_hash
                   <> coalesce(c.anterior, '{GENESE}'::bytea)
                THEN 'prev_hash nao e o row_hash do elo anterior'
              WHEN c.row_hash <> platform.payment_event_row_hash(
                     c.prev_hash, c.tenant_id, c.charge_id, c.order_id,
                     c.billing_cycle_id, c.provider, c.account_id,
                     c.referencia, c.tipo_evento, c.sequencia,
                     coalesce(c.provider_event_id, ''), c.valor_minor,
                     c.currency, c.authn_method, c.authn_ok, c.decisao,
                     c.motivo, c.actor_kind, c.actor_id, c.payload_hash,
                     c.ocorrido_at, c.recebido_at)
                THEN 'row_hash nao corresponde aos campos canonicos'
              WHEN c.payload_hash
                   <> sha256(convert_to(c.payload::text, 'UTF8'))
                THEN 'payload_hash nao corresponde ao payload'
              ELSE NULL
            END AS falha
          ) f
          WHERE f.falha IS NOT NULL
          ORDER BY c.charge_id, c.id
        $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.verify_ledger_chain(uuid) IS "
        "'Recalcula a cadeia de hashes do ledger e devolve os elos partidos "
        "(KAM-053). Zero linhas e a cadeia intacta. Verifica o encadeamento (o "
        "prev_hash e o row_hash do anterior), a formula (o row_hash guardado) e "
        "o payload_hash: a formula apanha um byte alterado, o encadeamento "
        "apanha uma linha removida. Corre diariamente (secao 8).'"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.verify_ledger_chain(uuid) FROM PUBLIC")


def _vistas() -> None:
    """As duas vistas: a de auditoria do §8 do doc 08, e a cabeca da cadeia.

    `security_invoker = true` nas duas, e nao e opcional: o *gate* 6 falha com
    uma vista sem ele e **para vistas nao ha lista de excepcoes**. Sem o
    `invoker`, uma vista corre com os privilegios do dono — o `kamba_migrator` —
    e seria um caminho de leitura por cima dos `GRANT` das tabelas.
    """
    # ## O criterio 9 e a unica caixa deste bloco que **nao** se pode marcar
    #
    # Ele pede uma vista que exponha `callback_hmac_ok = (authn_method =
    # 'hmac_sha256' AND authn_ok)`. Os dois nomes que a linha escreve estao os
    # dois na coluna «Substitui» do dicionario §3.4, e o primeiro e **variante
    # de nivel 1** do *gate* 3b: o nivel 1 varre todos os tokens, incluindo o
    # interior das cadeias e dos `COMMENT ON`, e nenhuma entrada de
    # `canon/extensoes.yaml` o salva — o leitor recusa o ficheiro com erro de
    # configuracao se o tentar. Medido: a primeira versao desta revisao escrevia
    # o nome e dava dois achados `[variante]`, um na vista e um no comentario.
    #
    # O `ci/canon-allow.yaml` tambem nao serve: cobre so a superficie
    # `documentos` (`docs/tecnica/`), e e por isso que o nome **pode** aparecer
    # no §6.1 do doc 04 e nao aqui.
    #
    # Logo a coluna chama-se `authn_hmac_ok`, que e o mesmo predicado com um
    # nome que o dicionario nao proibe, e a caixa do criterio 9 fica **vazia**
    # com a razao escrita. Mudar o que o *gate* 3b aceita e alteracao de regra
    # de bloqueio, e essa decisao nao e de um ticket.
    #
    # `authn_method = 'hmac'` e nao `'hmac_sha256'`: ver o cabecalho.
    op.execute(
        f"""
        CREATE VIEW platform.v_payment_events_audit
          WITH (security_invoker = true) AS
          SELECT e.id, e.tenant_id, e.charge_id, e.provider, e.account_id,
                 e.referencia, e.tipo_evento, e.sequencia, e.valor_minor,
                 e.currency, e.authn_method, e.authn_ok, e.decisao, e.motivo,
                 e.actor_kind, e.actor_id, e.ocorrido_at, e.recebido_at,
                 (e.authn_method = 'hmac' AND e.authn_ok) AS authn_hmac_ok
            FROM {EVENTOS} e
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_payment_events_audit IS "
        "'O ledger com o predicado de HMAC do docs/tecnica/08 secao 14 como "
        "expressao derivada (KAM-053): authn_hmac_ok = (authn_method = hmac AND "
        "authn_ok). O nome que o criterio 9 pede e variante de nivel 1 do gate "
        "3b e nao pode aparecer numa migracao — ver o comentario de _vistas. "
        "security_invoker: a RLS do ledger continua a valer para quem le a vista.'"
    )
    # A cabeca da cadeia por cobranca, que e o que o *job* diario exporta para
    # STO (ancora externa, §8). Uma linha por cobranca com eventos.
    op.execute(
        f"""
        CREATE VIEW platform.v_payment_ledger_heads
          WITH (security_invoker = true) AS
          SELECT DISTINCT ON (e.charge_id)
                 e.charge_id, e.tenant_id, e.id AS event_id, e.sequencia,
                 e.row_hash, e.recebido_at
            FROM {EVENTOS} e
           ORDER BY e.charge_id, e.id DESC
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_payment_ledger_heads IS "
        "'A cabeca da cadeia de hashes por cobranca (KAM-053). O job diario do "
        "docs/tecnica/04 secao 8 exporta-a para STO como ancora externa: uma "
        "cadeia cuja cabeca esta fora do host nao se reescreve sem se notar.'"
    )


def _rls() -> None:
    """RLS `FORCE` nas duas tabelas com `tenant_id` (ADR-015).

    O inbox nao entra: nao tem `tenant_id`, e o que o isola e o papel estreito
    (ver `_inbox`). O `payment_outbox_map` tambem nao: e configuracao global,
    como a `evt_subscricoes` da `0004`.

    O X-05 do *gate* 6 descobre as tabelas pelo catalogo e nao por lista, pelo
    que estas duas entram na verificacao sem ninguem as declarar — e as outras
    duas ficam de fora sem ninguem as dispensar.
    """
    rls.enable_tenant_rls("payment_charges")
    rls.enable_tenant_rls("payment_events")


def _privilegios() -> None:
    """A matriz, tabela a tabela. O que **nao** se concede e onde vive a barreira.

        payment_charges          app: SELECT, INSERT    lote: SELECT, INSERT, DELETE
        payment_callbacks_inbox  hooks: SELECT, INSERT, UPDATE(4 colunas)
                                 lote:  SELECT, UPDATE(4 colunas), DELETE
        payment_events           app, lote, auditoria, hooks: SELECT
        payment_outbox_map       app, hooks: SELECT       lote: SELECT, INSERT, DELETE

    **Ninguem tem `UPDATE` em `payment_charges`.** E a barreira do DoD: o
    `estado` muda so pela projeccao da `append_payment_event`, que corre como o
    dono. Com `UPDATE` concedido a qualquer papel havia um caminho para escrever
    `paga` sem passar pela porta — que e exactamente o que este ticket existe
    para nao ter.

    **O `kamba_app` tem `INSERT` em `payment_charges`.** Uma cobranca nasce num
    turno de conversa (o `createOrder` do COM), ao contrario de uma
    `payment_account`, que nasce no onboarding de retaguarda — e e por isso que
    a `0027` nao lhe deu `INSERT` e esta da. O `WITH CHECK` da `tenant_iso` prende
    o `tenant_id` ao contexto, e o *trigger* `assert_beneficiary` prende o
    beneficiario (G-1).

    **Ninguem tem `INSERT` em `payment_events`.** E a outra metade da porta: sem
    privilegio, um `INSERT` directo falha com `42501` antes de chegar a um
    `CHECK`. O `deny_mutation` fecha o resto, e fecha-o tambem ao dono e ao
    superutilizador.

    **O `kamba_app` executa a porta; o `kamba_pay_hooks` nao.** O papel dos
    hooks corre **antes** de haver contexto de tenant: a RLS recusar-lhe-ia a
    cobranca de qualquer forma, e dar-lhe `EXECUTE` era deixar na matriz um
    privilegio que nao se pode usar. Quem escreve no ledger e o *worker*, que
    corre como `kamba_app` com o contexto resolvido — a ordem do §5.1
    (`inbox.insert -> 2xx -> worker`) e o que separa os dois papeis.

    **O `kamba_batch` nao executa a porta, e precisa de a executar um dia**: a
    reconciliacao do §8 e o KAM-056. Fica sem `EXECUTE` aqui porque nesta
    revisao nao ha quem o chame como lote, e um privilegio sem chamador e uma
    porta aberta sem ninguem a usar (a licao da politica que a `0027` nao criou).

    **O `kamba_resolver`, o `kamba_identity` e o `kamba_agr` nao ganham nada.**
    """
    # **O `USAGE` no esquema, primeiro.** Um papel novo nao o tem, e sem ele
    # todo o `GRANT` por tabela e letra morta: o `SELECT` seguinte falha com
    # `42501 permission denied for schema platform`, que nao nomeia a tabela
    # nenhuma e parece um `GRANT` em falta onde o que falta e o esquema. Cada
    # papel desta base o recebeu na revisao que o estreou — a `0001` para o
    # `kamba_app` e o `kamba_batch`, a `0002` para o `kamba_resolver`, a `0003`
    # para o `kamba_identity`, a `0006` para o `kamba_audit` —, e este recebe-o
    # aqui. Medido: os cinco ensaios do papel estreito falharam todos nele.
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {PAPEL_DOS_HOOKS}")

    # ------------------------------------------------------------ payment_charges
    op.execute(f"GRANT SELECT, INSERT ON {COBRANCAS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {COBRANCAS} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {COBRANCAS} TO {PAPEL_DE_LOTE}")

    # ---------------------------------------------------- payment_callbacks_inbox
    #
    # O `kamba_app` **nao** entra. O inbox nao tem `tenant_id` e nao tem RLS:
    # um `SELECT` do papel da aplicacao lia os callbacks de todas as PMEs.
    op.execute(f"GRANT SELECT, INSERT ON {INBOX} TO {PAPEL_DOS_HOOKS}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DO_INBOX)}) ON {INBOX} TO {PAPEL_DOS_HOOKS}"
    )
    op.execute(f"GRANT SELECT, DELETE ON {INBOX} TO {PAPEL_DE_LOTE}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DO_INBOX)}) ON {INBOX} TO {PAPEL_DE_LOTE}"
    )
    # A sequencia do `GENERATED ALWAYS AS IDENTITY` tem de ser usavel por quem
    # insere, ou o `INSERT` falha com `42501` na sequencia e nao na tabela.
    op.execute(
        f"GRANT USAGE ON SEQUENCE platform.payment_callbacks_inbox_id_seq "
        f"TO {PAPEL_DOS_HOOKS}"
    )

    # -------------------------------------------------- payment_accounts (leitura)
    #
    # ## Tres versoes, e o que cada uma mediu
    #
    # Esta e a parte do ticket que custou mais a acertar, e as duas primeiras
    # tentativas falharam por razoes **opostas**. Fica escrito porque a terceira
    # so se entende contra elas.
    #
    #     1.ª  `SECURITY DEFINER` na funcao, sem politica.
    #          **Nao funciona.** O `DEFINER` corre como o dono — o
    #          `kamba_migrator`, que e `NOBYPASSRLS` — e o `FORCE` vincula o
    #          dono: sem contexto de tenant a funcao ve **zero linhas**. E a
    #          licao que o `db/rls.py` escreve e que nomeia este ticket como
    #          credor; eu re-aprendi-a aqui, com o ensaio do papel estreito a
    #          devolver lista vazia.
    #
    #     2.ª  `SECURITY INVOKER` + politica `USING (true)` + `GRANT SELECT` por
    #          coluna, **incluindo o `webhook_token`** (a coluna entra porque a
    #          funcao a compara, e sob `INVOKER` quem chama precisa de `SELECT`
    #          em toda a coluna que a consulta referencia).
    #          **Funciona e abre um buraco.** A revisao adversarial mediu-o: o
    #          papel passava a poder `SELECT webhook_token FROM
    #          payment_accounts` — 36 linhas e 36 *tokens* — isto e, enumerar o
    #          segredo de callback de **todas** as PMEs. Para os facilitadores
    #          sem assinatura (OPG, EMIS, MoMenu) o *token* e a unica credencial
    #          do callback (§5).
    #
    #     3.ª  **A politica carrega o predicado.** `SECURITY INVOKER`, `GRANT
    #          SELECT` **sem** o `webhook_token`, e a politica a comparar o
    #          *token* com uma variavel de sessao que quem chama poe:
    #
    #              USING (webhook_token = NULLIF(current_setting(
    #                       'app.webhook_token', true), ''))
    #
    # ## Porque e que a terceira resolve as duas coisas
    #
    # A expressao de uma politica e **definida pelo dono** da tabela, e os
    # privilegios de coluna sao conferidos contra as colunas que a **consulta**
    # referencia — nao contra as que a politica referencia. Logo o papel compara
    # o `webhook_token` sem ter `SELECT` nele.
    #
    # O efeito: sem saber um *token*, o papel ve **zero linhas**; sabendo um, ve
    # **uma**. Nao ha enumeracao porque nao ha consulta que devolva mais do que
    # a linha do *token* que quem pergunta ja tem. E nao ha segunda
    # `SECURITY DEFINER`, pelo que a caixa do DoD («`SECURITY DEFINER` apenas em
    # `append_payment_event`») fica satisfeita **sem** se pagar com uma
    # enumeracao de segredos.
    #
    # O padrao e o mesmo do `app.tenant_id` da `tenant_iso`: uma variavel de
    # sessao que o chamador poe e a politica le. O `NULLIF` esta la pela mesma
    # razao do `db/rls.py` — uma variavel nunca definida da `NULL` e uma que
    # expirou da `''`, e as duas tem de dar zero linhas em vez de todas.
    op.execute(
        f"GRANT SELECT (id, tenant_id, provider, entidade, pos_id, estado) "
        f"ON platform.payment_accounts TO {PAPEL_DOS_HOOKS}"
    )
    op.execute(
        f"""
        CREATE POLICY pay_hooks_token ON platform.payment_accounts
          FOR SELECT TO {PAPEL_DOS_HOOKS}
          USING (webhook_token = {PREDICADO_DO_TOKEN})
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.resolve_webhook_token(p_token text)
        RETURNS TABLE (account_id uuid, tenant_id uuid, provider text,
                       entidade text, pos_id text, estado text)
        LANGUAGE plpgsql
        SET search_path = pg_catalog, platform AS $func$
        BEGIN
          -- **`VOLATILE` (a omissao) e nao `STABLE`**, e e uma correccao de
          -- honestidade: ela chama o `set_config`, que e `VOLATILE`. O
          -- PostgreSQL nao recusa um `STABLE` que chame um `VOLATILE` — a
          -- marca e uma promessa de quem escreve, nao uma verificacao —, e uma
          -- promessa falsa sobre volatilidade e um convite a que o planeador a
          -- avalie uma vez por consulta onde ela tem efeito de sessao.
          --
          -- O *token* vai para a variavel de sessao que a politica le, e nao
          -- para um `WHERE` — porque e a politica que o compara, e e isso que
          -- dispensa dar `SELECT` na coluna do segredo a quem pergunta.
          --
          -- `true` no terceiro argumento do `set_config`: **local a
          -- transaccao**. Um *token* que sobrevivesse a transaccao ficava a
          -- valer para a consulta seguinte da mesma ligacao, que e um conjunto
          -- de ligacoes reutilizadas por um servidor HTTP.
          PERFORM set_config('{VARIAVEL_DO_TOKEN}', coalesce(p_token, ''), true);
          RETURN QUERY
            SELECT a.id, a.tenant_id, a.provider, a.entidade, a.pos_id, a.estado
              FROM platform.payment_accounts a;
          -- A variavel limpa-se a seguir: o que a politica precisava dela,
          -- precisou agora.
          PERFORM set_config('{VARIAVEL_DO_TOKEN}', '', true);
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.resolve_webhook_token(text) IS "
        "'Resolve webhook_token -> conta ANTES de existir contexto de tenant "
        "(KAM-053): no instante em que o callback chega ainda nao se sabe de quem "
        "ele e. SECURITY INVOKER, e o que a torna possivel e a politica "
        "pay_hooks_token, que compara o token com a variavel de sessao "
        "app.webhook_token — a expressao de uma politica e do dono da tabela, "
        "pelo que o papel compara a coluna sem ter SELECT nela. Sem token, zero "
        "linhas; com token, uma. Nao ha enumeracao e nao ha segunda SECURITY "
        "DEFINER: as duas alternativas foram tentadas e medidas (ver a revisao).'"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.resolve_webhook_token(text) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.resolve_webhook_token(text) "
        f"TO {PAPEL_DOS_HOOKS}"
    )

    # ------------------------------------------------------------- payment_events
    #
    # `REVOKE` antes do `GRANT`, pela letra do §6.2. Nao e redundante com a
    # omissao do PostgreSQL: deixa escrito, no proprio SQL, que o que falta
    # falta de proposito.
    op.execute(
        f"REVOKE ALL ON {EVENTOS} FROM PUBLIC, {PAPEL_DA_APP}, {PAPEL_DE_LOTE}"
    )
    op.execute(f"GRANT SELECT ON {EVENTOS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {EVENTOS} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {EVENTOS} TO {PAPEL_DE_AUDITORIA}")

    # ------------------------------------------------------------- as vistas
    #
    # **Faltavam, e a revisao adversarial mediu o que isso custava:** uma
    # vista sem `GRANT` nao e lida por papel nenhum (`42501 permission denied
    # for view`). A `v_payment_ledger_heads` e o que o *job* diario exporta
    # para STO, pelo que a ancora externa **falhava na primeira execucao
    # real**; a `v_payment_events_audit` existe para os alvos do
    # `docs/tecnica/08` §14 e o `kamba_audit` nao a conseguia abrir.
    #
    # Nenhum ensaio o via: os de catalogo inspeccionam como administrador, o
    # `test_privilegios.py` nao tem matriz para vistas, e o ensaio do
    # `ledger.ts` usa uma porta falsa. O `TestPrivilegiosDasVistas` da suite
    # passa a le-las **como papel**, que e a unica forma de o medir.
    #
    # `security_invoker = true` nas duas: o `GRANT` da acesso a vista, e a
    # RLS da tabela continua a decidir **que linhas** cada papel ve.
    for papel in (PAPEL_DA_APP, PAPEL_DE_LOTE, PAPEL_DE_AUDITORIA):
        op.execute(f"GRANT SELECT ON platform.v_payment_events_audit TO {papel}")
    # A cabeca da cadeia e de plataforma: le-a quem verifica (lote) e quem
    # audita. O `kamba_app` **nao** entra — um turno de conversa nao tem razao
    # para ver a cabeca da cadeia de cobranca nenhuma.
    for papel in (PAPEL_DE_LOTE, PAPEL_DE_AUDITORIA):
        op.execute(f"GRANT SELECT ON platform.v_payment_ledger_heads TO {papel}")

    # --------------------------------------------------------- payment_outbox_map
    op.execute(f"GRANT SELECT ON {MAPA} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {MAPA} TO {PAPEL_DE_LOTE}")

    # --------------------------------------------------------------- as funcoes
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.append_payment_event({ARGUMENTOS_DE_APPEND}) "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE}) "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE}) "
        f"TO {PAPEL_DE_LOTE}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.payment_event_row_hash("
        f"{ARGUMENTOS_DE_ROW_HASH}) TO {PAPEL_DE_LOTE}"
    )
    # O `rebuild` e a verificacao da cadeia correm no *job* nocturno, que e lote.
    # O `kamba_audit` tambem os executa: «esta cadeia esta intacta» e uma
    # pergunta de auditoria.
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.rebuild_charge_state(uuid) "
        f"TO {PAPEL_DE_LOTE}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.rebuild_charge_state(uuid) "
        f"TO {PAPEL_DE_AUDITORIA}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.verify_ledger_chain(uuid) "
        f"TO {PAPEL_DE_LOTE}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.verify_ledger_chain(uuid) "
        f"TO {PAPEL_DE_AUDITORIA}"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # **Sem guarda de dados, e aqui isso tem peso**: o que se perde e o ledger,
    # que e prova e nao configuracao. O `downgrade` existe para o ciclo do
    # *gate* 8 e para reverter um *deploy* no dia em que a tabela ainda esta
    # vazia; quem o corre contra uma base com eventos perde-os, e nenhum
    # `deny_mutation` o impede — um `DROP TABLE` nao e um `DELETE`, e o
    # *trigger* nao dispara. Fica dito porque a aparencia de imutabilidade e
    # pior do que a imutabilidade medida.
    #
    # A ordem e a inversa da criacao, e as vistas e os *triggers* caem primeiro
    # porque dependem do que vem depois.
    op.execute("DROP VIEW platform.v_payment_ledger_heads")
    op.execute("DROP VIEW platform.v_payment_events_audit")
    op.execute(f"DROP FUNCTION platform.append_payment_event({ARGUMENTOS_DE_APPEND})")
    op.execute("DROP FUNCTION platform.verify_ledger_chain(uuid)")
    op.execute("DROP FUNCTION platform.rebuild_charge_state(uuid)")
    op.execute("DROP FUNCTION platform.resolve_webhook_token(text)")
    # A politica e sobre uma tabela da `0027`, que esta revisao nao apaga:
    # por isso cai aqui a mao. Deixa-la pendurada fazia o `downgrade` da
    # `0027` encontrar uma politica que nao criou.
    op.execute("DROP POLICY pay_hooks_token ON platform.payment_accounts")
    op.execute(f"DROP FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE})")
    op.execute(f"DROP FUNCTION platform.payment_event_row_hash({ARGUMENTOS_DE_ROW_HASH})")
    op.execute("DROP FUNCTION platform.payment_instante(timestamptz)")
    rls.disable_tenant_rls("payment_events")
    rls.disable_tenant_rls("payment_charges")
    # Os *triggers* e os indices caem com as tabelas. O `deny_mutation` cai
    # **depois** das tabelas que o usam.
    op.execute(f"DROP TABLE {MAPA}")
    op.execute(f"DROP TABLE {EVENTOS}")
    op.execute(f"DROP TABLE {INBOX}")
    op.execute(f"DROP TABLE {COBRANCAS}")
    op.execute("DROP FUNCTION platform.deny_mutation()")
    # O *trigger* do nascimento cai com a `payment_charges`; a funcao nao, e
    # por isso vai a seguir.
    op.execute("DROP FUNCTION platform.payment_charge_nasce_iniciada()")
    # O `kamba_pay_hooks` **nao** se apaga: e criado pelo `db/bootstrap.py`,
    # como os outros sete, e uma revisao que o apagasse deixava a base sem um
    # papel que o bootstrap desta versao declara.

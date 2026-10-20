"""Passagem a humano: handoff e conta de atendimento (KAM-019).

**A primeira linha e ASCII de proposito, e segue a forma das outras dez.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a do
executavel: um travessao aqui faz as duas divergirem na descodificacao e poe
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` vermelho.

Revisao: 0011
Anterior: 0010

**Porque e que esta revisao existe.** O KAM-015 deu a plataforma a capacidade de
falar para fora; esta da-lhe a de **calar-se e chamar uma pessoa**. Duas
tabelas, e cada uma existe por um criterio que nao se consegue cumprir sem ela:

* `handoffs` guarda a passagem — quem foi chamado, quando, por que motivo e em
  que estado. O `handoff_id` e a chave de idempotencia do criterio 4, e e
  **derivado** (`hash(thread_id, ordinal_do_handoff)`, `docs/tecnica/01` §11.1):
  cinco chamadas concorrentes chegam ao mesmo valor sem se falarem.
* `handoff_accounts` guarda o que o `ensureAccount` criou no provedor. Sem ela,
  «chamado 2x nao duplica» (criterio 1) nao tem onde assentar: a primeira
  chamada cria conta, *inbox* e bot no Chatwoot, e a segunda nao tem como saber
  que ja existem. Nao havia tabela candidata — a `tenant_channels.token_ref` da
  `0001` e do canal **Meta**.

A fonte dos nomes e o dicionario §3.15 (emenda 1.22), que entrou antes desta
revisao porque o *gate* 3b le o AST de cada migracao e recusa um nome que o §3
nao cubra. O desenho e o `docs/tecnica/01` §11 e o `docs/tecnica/02` §11.

**O que esta revisao nao faz, e nenhuma das tres e esquecimento:**

* **Nao da `UPDATE (mode)` a `kamba_app`**, e por isso o `setBotMuted` da
  interface **nao e executavel** por quem corre o HND. A `0009` escreveu a
  razao — «um privilegio concedido para quando for preciso e um privilegio que
  ninguem volta a tirar» — e as transicoes de modo sao do KAM-018. A porta fica
  na interface e levanta; a caixa do criterio fica vazia, com isto escrito.
* **Nao poe `CHECK` sobre o `resumed_at` nem sobre o `resolver`.** Era o que
  apetecia («um instante de retoma so existe num `resumed`») e e exactamente o
  defeito que a `0010` pagou: a `outbound_messages_entrega_ck` so admitia
  `delivered_at` em `delivered` e `read`, e matava com `23514` um `failed` que
  chegasse depois de uma entrega — um estado que a propria maquina de estados
  produz. Aqui e pior, porque **ninguem escreve estas duas colunas neste
  ticket**: o *compare-and-set* `waiting -> resumed` e do KAM-034 (criterio 7).
  Uma restricao sobre colunas que nenhum codigo toca seria descoberta por quem
  fizer o KAM-034, contra linhas que ja existem. As colunas nascem; a regra
  nasce com quem as escrever.
* **Nao cria tabela de fila de espelho.** O `docs/tecnica/01` §14 pede uma fila
  que «reconcilia por `wamid`», e isso e uma fila BullMQ com `jobId` derivado
  dele: a reconciliacao e a de-duplicacao que ela ja faz. Uma tabela de fila ao
  lado de uma fila era um segundo sitio para a mesma verdade.
"""

from __future__ import annotations

import json
import os

from alembic import op

import rls

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

#: O ciclo de vida de uma passagem a humano. Lista fechada, imposta por `CHECK`
#: (dicionario §3.15, emenda 1.22), e sao **exactamente** os do
#: `docs/tecnica/02` §11: «`waiting -> resumed | timeout | cancelled |
#: degraded`».
#:
#: `waiting` e a omissao: a linha nasce quando se chama por uma pessoa e antes
#: de ela responder. `resumed` e o que o *compare-and-set* do KAM-034 escreve —
#: aqui ninguem o escreve. `timeout` e as 24 h do escalonador. `cancelled` e a
#: desistencia. `degraded` e a passagem aberta **com o provedor em baixo**:
#: enfileirada e ainda nao criada la (`docs/tecnica/02` §14, «HND/Chatwoot
#: indisponivel -> `degraded`»), e sem ele uma passagem degradada era
#: indistinguivel de uma a espera de humano.
#:
#: Os valores vem **ja entre apostrofos**, e isso nao e desleixo: e a unica
#: forma que o *gate* 3b resolve. Ele le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*. Funcao
#: auxiliar, constante derivada e expressao geradora sao recusadas, cada uma com
#: a sua mensagem (ver `0008`, que pagou as tres).
ESTADOS_DE_HANDOFF = (
    "'waiting'",
    "'resumed'",
    "'timeout'",
    "'cancelled'",
    "'degraded'",
)

#: O provedor de atendimento. **Um valor hoje, e a coluna existe mesmo assim.**
#:
#: E o ADR-012 que a justifica: ele fixa a costura `HandoffProvider` e diz que o
#: Chatwoot e substituivel. Uma tabela chamada `tenant_chatwoot` tornava a
#: substituicao uma migracao; uma coluna de dominio torna-a uma linha.
PROVEDORES = ("'chatwoot'",)

#: A variavel que autoriza um `downgrade` destrutivo. A mesma forma da `0003`,
#: da `0009` e da `0010`.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0011_COPIA"

#: As colunas de uma passagem que o `kamba_app` pode alterar.
#:
#: Quatro, e sao as que o ciclo de vida muda depois de a linha existir: o
#: estado, o identificador que o provedor devolve, o instante da retoma e quem
#: retomou.
#:
#: **O que nao esta aqui e o que importa.** O `handoff_id` nao se altera nunca —
#: reescrever a chave de idempotencia de uma passagem que ja abriu e faze-la
#: voltar a abrir, a mesma frase que a `0008` escreveu para o `kind`/`event_key`
#: e a `0010` para a `idempotency_key`. O `tenant_id`, o `conversation_id`, o
#: `motivo` e o `opened_at` tambem nao: mudar o motivo depois de alguem ter sido
#: chamado e reescrever porque e que foi.
COLUNAS_DA_APLICACAO = (
    "status",
    "external_id",
    "resumed_at",
    "resolver",
)

#: As colunas de uma conta de atendimento que o `kamba_app` pode alterar.
#:
#: Quatro. O `account_id` **nao** esta: uma conta no provedor nao muda de
#: identidade, e se mudar e uma conta nova. O `tenant_id` e o `provedor` sao a
#: chave primaria. O `inbox_id` e o `bot_id` podem ser repostos — o
#: `ensureAccount` «repoe» uma conta em falta (`docs/tecnica/01` §11.5) — e o
#: `token_ref` muda na rotacao do segredo (182 dias, `ops/secrets-inventory.yaml`).
COLUNAS_DA_CONTA_NA_APLICACAO = (
    "inbox_id",
    "bot_id",
    "token_ref",
    "updated_at",
)

#: As colunas da copia logica de `handoffs`, pela ordem do `SELECT`.
COLUNAS_DA_COPIA_DE_HANDOFFS = (
    "handoff_id",
    "tenant_id",
    "conversation_id",
    "status",
    "motivo",
    "external_id",
    "opened_at",
    "resumed_at",
    "resolver",
)

#: Idem para as contas de atendimento.
COLUNAS_DA_COPIA_DE_CONTAS = (
    "tenant_id",
    "provedor",
    "account_id",
    "inbox_id",
    "bot_id",
    "token_ref",
    "criado_at",
    "updated_at",
)


def upgrade() -> None:
    # ----------------------------------------------------------------- handoffs
    #
    # A chave primaria e **texto** e nao `uuid`, contra o habito do §2 do
    # dicionario, e a razao esta no `docs/tecnica/01` §11.1: o `handoff_id` e
    # `hash(thread_id, ordinal_do_handoff)`, isto e, **derivado**. E isso que o
    # torna a chave de idempotencia do criterio 4 — cinco chamadas concorrentes
    # calculam o mesmo valor sem se falarem, o que nenhum `gen_random_uuid()`
    # consegue. Um UUID aqui obrigava a uma segunda coluna com o resumo e a
    # unicidade nela, o que e a mesma coisa com um nivel de indireccao a mais.
    op.execute(
        f"""
        CREATE TABLE platform.handoffs (
            handoff_id      text        NOT NULL,
            tenant_id       uuid        NOT NULL,
            conversation_id uuid        NOT NULL,
            status          text        NOT NULL DEFAULT 'waiting',
            motivo          text        NOT NULL,
            external_id     text,
            opened_at       timestamptz NOT NULL DEFAULT now(),
            resumed_at      timestamptz,
            resolver        text,
            CONSTRAINT handoffs_pkey PRIMARY KEY (handoff_id),
            CONSTRAINT handoffs_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- FK **composta**, pela razao que a `0009` escreveu: sem o
            -- `tenant_id` do lado de destino, uma passagem do tenant A podia
            -- apontar para uma conversa de B, e nem a RLS de `handoffs` (a
            -- linha e de A) nem a de `conversations` (uma FK e verificada por
            -- dentro) o veriam. Assenta na `conversations_tenant_id_uq` que a
            -- `0010` acrescentou.
            CONSTRAINT handoffs_conversation_fk
                FOREIGN KEY (tenant_id, conversation_id)
                REFERENCES platform.conversations (tenant_id, id),
            CONSTRAINT handoffs_status_ck
                CHECK (status IN ({', '.join(ESTADOS_DE_HANDOFF)})),
            -- Um motivo vazio e pior do que nenhum: diz que houve razao e nao
            -- diz qual. A mesma forma do `token_ref` da `0001`.
            CONSTRAINT handoffs_motivo_ck CHECK (btrim(motivo) <> '')
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoffs.handoff_id IS "
        "'hash(thread_id, ordinal_do_handoff) do docs/tecnica/01 §11.1. "
        "Derivado e nao gerado: e isso que torna cinco chamadas concorrentes "
        "idempotentes sem se falarem (criterio 4 do KAM-019).'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoffs.external_id IS "
        "'Identificador da conversa no provedor, devolvido pelo openHandoff. "
        "NULL enquanto a passagem estiver em degraded, isto e, enfileirada e "
        "ainda nao criada la.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoffs.resolver IS "
        "'Identificador opaco do agente humano no provedor (docs/tecnica/02 "
        "§11, «resolver (humano)»). Nunca nome, e-mail nem telefone; nao e um "
        "contact_id da KAMBA. Dado pessoal de um trabalhador da PME.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoffs.resumed_at IS "
        "'Instante da retoma. Nenhum codigo do KAM-019 a escreve: o "
        "compare-and-set waiting -> resumed e do KAM-034 (criterio 7). Nasce "
        "sem CHECK de proposito — ver o docstring da revisao.'"
    )

    # **O indice que a RLS precisa, e nao e opcional.**
    #
    # A convencao da casa — imposta por
    # `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` — e que toda a
    # tabela com `tenant_id` tenha **algum** indice que comece por ele, porque
    # e o predicado que a RLS acrescenta a todas as consultas: num indice
    # `(status, tenant_id)` nao serviria. As outras tabelas desta classe
    # satisfazem-na de graca, pela chave primaria ou por uma `UNIQUE` de
    # negocio; a `handoffs` **nao**, porque a sua chave primaria e o
    # `handoff_id` derivado e nao tem `tenant_id`. Medido: o teste da convencao
    # recusou a primeira versao desta revisao.
    #
    # A segunda coluna e o `opened_at` descendente, e e a consulta do SLA que a
    # escolhe: «passagens a espera ha mais de 15 min, por tenant»
    # (`docs/tecnica/02` §11). Um indice so de `tenant_id` cumpria a convencao
    # e deixava essa consulta a ordenar em memoria.
    op.execute(
        "CREATE INDEX handoffs_tenant_idx "
        "ON platform.handoffs (tenant_id, opened_at DESC)"
    )

    rls.enable_tenant_rls("handoffs")

    # -------------------------------------------------------- handoff_accounts
    op.execute(
        f"""
        CREATE TABLE platform.handoff_accounts (
            tenant_id  uuid        NOT NULL,
            provedor   text        NOT NULL,
            account_id bigint      NOT NULL,
            inbox_id   bigint      NOT NULL,
            bot_id     bigint      NOT NULL,
            token_ref  text        NOT NULL,
            criado_at  timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- `(tenant_id, provedor)` e nao um UUID: e isto que torna «uma
            -- conta por PME» (criterio 1) uma propriedade da **base** e nao do
            -- codigo. Um `ensureAccount` concorrente bate na chave.
            CONSTRAINT handoff_accounts_pkey PRIMARY KEY (tenant_id, provedor),
            CONSTRAINT handoff_accounts_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **O outro sentido, e e o que fecha o isolamento entre contas.**
            -- A chave primaria impede dois registos para o mesmo tenant; esta
            -- impede a mesma conta do provedor em dois tenants, que e o furo
            -- que o X-10 procura. Sem ela, um `ensureAccount` que devolvesse
            -- por erro a conta de outra PME ficava gravado sem ninguem ver.
            CONSTRAINT handoff_accounts_conta_uq UNIQUE (provedor, account_id),
            CONSTRAINT handoff_accounts_provedor_ck
                CHECK (provedor IN ({', '.join(PROVEDORES)})),
            -- Uma referencia a segredo vazia e um segredo que ninguem vai
            -- buscar. A mesma forma do `token_ref` da `0001`.
            CONSTRAINT handoff_accounts_token_ck CHECK (btrim(token_ref) <> '')
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoff_accounts.token_ref IS "
        "'SecretRef opaca do token do agent bot desta conta "
        "(chatwoot_bot_token, instancias: conta). Nunca o token. O "
        "chatwoot_platform_token nao entra em tabela nenhuma: tem instancias "
        "nenhuma e vive so no modulo de provisionamento (docs/tecnica/08 §3.6).'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.handoff_accounts.provedor IS "
        "'Um valor hoje (chatwoot). A coluna existe por causa do ADR-012, que "
        "fixa a costura HandoffProvider e diz que o provedor e substituivel.'"
    )

    rls.enable_tenant_rls("handoff_accounts")

    # ------------------------------------------------------------- privilegios
    #
    # Tabela a tabela e coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: uma
    # tabela nova nao nasce acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # O `SELECT` de tabela em `handoffs` e preciso e nao e generoso: o
    # `openHandoff` le a linha para saber se a passagem ja abriu (idempotencia),
    # e um `INSERT ... ON CONFLICT (handoff_id) DO NOTHING RETURNING` exige
    # `SELECT` na coluna de inferencia — a licao que a `0008` escreveu para o
    # `SQL_QUARENTENA` e a `0010` repetiu.
    op.execute("GRANT SELECT, INSERT ON platform.handoffs TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_APLICACAO)}) "
        "ON platform.handoffs TO kamba_app"
    )

    # **`INSERT` tambem aqui, ao contrario dos `message_templates` da `0010`.**
    # A diferenca e quem cria: um template e submetido pelo onboarding
    # (KAM-091), mas uma conta de atendimento e criada pelo proprio
    # `ensureAccount`, que corre no HND. Negar-lhe o `INSERT` era entregar um
    # criterio que nao pode passar.
    op.execute("GRANT SELECT, INSERT ON platform.handoff_accounts TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_CONTA_NA_APLICACAO)}) "
        "ON platform.handoff_accounts TO kamba_app"
    )

    # O `kamba_batch` tem os quatro verbos nas duas, que e o que tem em todas as
    # outras desde a `0001`, porque e quem purga (KAM-071).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.handoffs TO kamba_batch"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON platform.handoff_accounts TO kamba_batch"
    )


def _contar_handoffs() -> int:
    """Quantas passagens existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.handoffs"
    ).scalar_one()


def _contar_contas() -> int:
    """Quantas contas de atendimento existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.handoff_accounts"
    ).scalar_one()


def _handoffs() -> list[dict]:
    """A tabela de passagens em JSON: tempos como texto."""
    resultado = op.get_bind().exec_driver_sql(
        "SELECT handoff_id, tenant_id, conversation_id, status, motivo, "
        "       external_id, opened_at, resumed_at, resolver "
        "  FROM platform.handoffs ORDER BY opened_at, handoff_id"
    )
    return [
        {
            coluna: (None if valor is None else str(valor))
            for coluna, valor in zip(COLUNAS_DA_COPIA_DE_HANDOFFS, linha)
        }
        for linha in resultado
    ]


def _contas() -> list[dict]:
    """As contas de atendimento em JSON."""
    resultado = op.get_bind().exec_driver_sql(
        "SELECT tenant_id, provedor, account_id, inbox_id, bot_id, token_ref, "
        "       criado_at, updated_at "
        "  FROM platform.handoff_accounts ORDER BY tenant_id, provedor"
    )
    return [
        {
            coluna: (None if valor is None else str(valor))
            for coluna, valor in zip(COLUNAS_DA_COPIA_DE_CONTAS, linha)
        }
        for linha in resultado
    ]


def downgrade() -> None:
    """Reverter apaga passagens e contas, e por isso pergunta.

    O que se perde sao duas coisas que nao se reconstroem. A primeira e a
    **conta no provedor**: o `account_id`, o `inbox_id` e o `bot_id` ficam a
    existir **lá fora**, e sem a linha que os aponta o `ensureAccount` seguinte
    cria uma segunda conta para a mesma PME — que e exactamente o que o criterio
    1 proibe, e que nenhuma migracao nossa pode desfazer, porque o recurso nao e
    nosso. A segunda e o **historico de passagens**, que e o que sustenta o SLA
    de retoma do `docs/tecnica/02` §11.

    Com linhas em qualquer das duas tabelas, exige-se `KAMBA_DOWNGRADE_0011_COPIA`
    com o caminho de um ficheiro onde as duas sao escritas antes de cairem — a
    mesma forma da `0003`, da `0009` e da `0010` (`db/migrations/README.md`).
    Sem a variavel, o `downgrade` **recusa**: nao ha perda em silencio.

    **As politicas saem ANTES de se contar, e isso foi um defeito medido na
    `0009` e confirmado na `0010`.** Com `FORCE ROW LEVEL SECURITY`, o dono da
    tabela esta sujeito a politica — e uma migracao corre **sem** contexto de
    tenant. Contar `count(*)` como `kamba_migrator` ve **zero linhas** sobre uma
    tabela cheia: nao pede copia nenhuma e apaga em silencio, que e exactamente
    o contrario do que estas linhas existem para impedir. As duas tabelas desta
    revisao tem `FORCE`, logo sao **duas** chamadas a `disable_tenant_rls` antes
    da primeira contagem.

    Os `disable_tenant_rls` sao as primeiras instrucoes, e por isso a recusa
    tambem as desfaz: o Alembic corre **uma transacao por revisao**
    (`transaction_per_migration=True`), pelo que levantar aqui deixa as tabelas
    com as politicas intactas e a base em `0011`.
    """
    rls.disable_tenant_rls("handoffs")
    rls.disable_tenant_rls("handoff_accounts")

    passagens = _contar_handoffs()
    contas = _contar_contas()
    if passagens or contas:
        destino = os.environ.get(VARIAVEL_DA_COPIA, "").strip()
        if not destino:
            raise RuntimeError(
                f"downgrade da 0011: ha {passagens} passagem(ns) e {contas} "
                "conta(s) de atendimento, e reverter apaga-as — com elas, a "
                "ligacao as contas que existem no provedor (que nenhuma "
                "migracao nossa pode desfazer, porque o recurso nao e nosso) e "
                "o historico que sustenta o SLA de retoma. Defina "
                f"{VARIAVEL_DA_COPIA} com o caminho de um ficheiro para a copia "
                "logica, ou esvazie as duas tabelas primeiro."
            )
        with open(destino, "w", encoding="utf-8") as ficheiro:
            json.dump(
                {"handoffs": _handoffs(), "handoff_accounts": _contas()},
                ficheiro,
                ensure_ascii=False,
                indent=1,
            )

    # Pela ordem inversa do `upgrade`. Os `REVOKE` que as tabelas levam consigo
    # no `DROP` nao se escrevem (seria ruido, e um `REVOKE` depois do `DROP`
    # falhava).
    #
    # As politicas ja sairam, nas primeiras instrucoes desta funcao (ver o
    # docstring): sem isso, as contagens de cima viam zero linhas.
    #
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou, o
    # `downgrade` falha em vez de o apagar em silencio. Nenhuma das duas
    # referencia a outra, pelo que a ordem entre elas e so a inversa da criacao.
    op.execute("DROP TABLE platform.handoff_accounts")
    op.execute("DROP TABLE platform.handoffs")

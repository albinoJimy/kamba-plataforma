"""Saida de canal: envio, templates e custo (KAM-015).

**A primeira linha e ASCII de proposito, e segue a forma das outras nove.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a do
executavel: um travessao aqui faz as duas divergirem na descodificacao e poe
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` vermelho.

Revisao: 0010
Anterior: 0009

**Porque e que esta revisao existe.** Ate aqui a plataforma so recebia. O
`ChannelAdapter` do KAM-015 e o primeiro codigo que fala para fora, e o que ele
precisa de guardar sao duas coisas que nao existiam: o que foi enviado (para
nao enviar duas vezes, para seguir o estado e para saber quanto custou) e que
templates o tenant tem aprovados (para decidir com a janela fechada).

A fonte de cada coisa:

* `outbound_messages` e as suas catorze colunas — dicionario §3.14, emenda 1.21
  (KAM-015). O DDL de `docs/tecnica/01` §8.4 tem **treze** (contadas uma a uma:
  `id`, `tenant_id`, `channel_id`, `contact_id`, `idempotency_key`, `wamid`,
  `kind`, `template_name`, `state`, `pricing`, `error_code`, `created_at`,
  `delivered_at`); a catorze e `conversation_id`, sem a qual nao ha ordem por
  conversa (criterio 6), e nao se acrescenta mais nada. A primeira versao desta
  nota dizia «doze» e contava o `created_at` como acrescento — uma coluna que o
  documento ja tem nao pode ser um acrescento, e 12 + 1 nao da 14. Apanhado pela
  revisao adversarial.
* `message_templates` e as suas dez colunas — dicionario §3.14. O DDL do §8.3
  tem nove; a decima e `bloqueado_em`, que o criterio 9 pede por implicacao: a
  recategorizacao para `marketing` bloqueia o uso, e um bloqueio sem instante
  nao se audita nem se levanta.
* Os dominios de `state`, `kind`, `category`, `status` e `quality` — §3.14.
* `UNIQUE (tenant_id, id)` em `conversations` — nao e o ticket que a pede: e o
  que permite a FK composta de `outbound_messages` para a conversa. A `0009`
  so lhe deu `PRIMARY KEY (id)` e `UNIQUE (tenant_id, contact_id, channel_id)`.
  Ver abaixo.

**Quatro divergencias assumidas, e cada uma esta no §3.14 com a sua razao.**
Resumidas aqui porque quem le esta revisao tem de as encontrar aqui:

1. **`platform.` e FK compostas**, contra a forma dos DDL do §8.3-§8.4 — que
   nao tem prefixo nem chaves estrangeiras — e contra o «exactamente como o doc
   01 §8.3-§8.4» do proprio bloco do ticket. As nove revisoes anteriores criam
   tudo em `platform.` e, desde a `0003`, com FK em `(tenant_id, ...)`. A `0009`
   escreveu a razao e vale aqui palavra por palavra: sem a composta, uma
   mensagem do tenant A podia apontar para um canal — ou uma conversa, ou um
   contacto — do tenant B, e **nem o gate 6 nem o 3b o veriam** (a linha e de A
   e ve-se com o contexto de A; a FK e verificada por dentro).
2. **`UNIQUE (tenant_id, idempotency_key)`**, e nao a unicidade global do §8.4.
   Com unicidade global, duas chaves iguais de tenants diferentes colidem: o
   segundo envio e deduplicado em silencio, e o `INSERT` falha sobre uma linha
   que o segundo tenant **nao pode ver**. Um tenant suprime mensagens de outro
   se adivinhar a chave. E a licao da emenda 1.18, que levou a chave do
   `usage_ledger` de global a composta pela mesma medicao.
3. **O `wamid` fica com unicidade global**, e a assimetria com a chave de
   idempotencia e deliberada: a chave e nossa e uma colisao entre tenants e
   acidente de nomes, o `wamid` e da Meta e globalmente unico por construcao,
   pelo que uma colisao ali e um defeito que vale a pena fazer barulho.
4. **`status` e `quality` em minusculas**, contra o §8.3, que os escreve em
   MAIUSCULAS porque e o vocabulario da Meta. O §2 do dicionario manda
   «Estados: minusculas, snake_case, sem acentos» e prevalece sobre
   `docs/tecnica/`: a base e nossa, e a traducao do vocabulario da Meta faz-se
   na fronteira, numa funcao com teste — o mesmo desenho do `wa_type` do §3.12.

**O sexto valor de `state` nasce aqui, e e de outro ticket.** O
`suppressed_by_human` e do KAM-018, cuja migracao diz que o «adiciona se ainda
nao existir». Nasce nesta revisao porque o *gate* 3b le o AST de cada revisao
**isoladamente** e compara o `CHECK` com uma entrada por coluna: alargar o
dominio numa revisao posterior deixava esta vermelha por lhe «faltar» um valor.
Foi medido no `unrouted_events.motivo` (emenda 1.20), e o bloco do KAM-015
manda-o por extenso. A migracao do KAM-018 fica sem trabalho.

> **A `UNIQUE` sobre uma tabela com `FORCE` leva o cuidado da `0003` e da
> `0009`.** Um `ADD CONSTRAINT UNIQUE` constroi um indice, e um indice e uma
> varredura fisica que a politica nao filtra — mas a propriedade «duas linhas
> iguais sao recusadas» passa a depender de uma escolha de implementacao do
> PostgreSQL em vez de estar garantida. O `FORCE` sai e volta na **mesma
> transacao**, como em `docs/isolamento.md` §6, e o intervalo nao se ve de fora.

**O que esta revisao NAO faz, e e escopo e nao esquecimento:**

* **Nao da `INSERT` em `message_templates` a `kamba_app`.** Quem submete o
  conjunto padrao de templates por tenant e o onboarding (KAM-091), e e esse
  ticket que pede o privilegio. O adapter do KAM-015 **le** os templates para
  decidir e **bloqueia** um que seja recategorizado; nao cria nenhum. Um
  `INSERT` concedido aqui era a aplicacao a poder inventar um template aprovado
  que a Meta nunca viu — e e a mesma frase que a `0009` escreveu para o
  `UPDATE (mode)`: um privilegio concedido «para quando for preciso» e um
  privilegio que ninguem volta a tirar.
* **Nao cria coluna para a janela FEP.** O §3.13 atribuia-a a este ticket e os
  *Detalhes Tecnicos* do proprio KAM-015 atribuem-na a Clusters; a emenda 1.21
  corrige a linha do §3.13. Nenhum dos nove criterios menciona FEP.
* **Nao mantem o contador do *free tier*.** `tenant_channels.free_tier_used` e
  `free_tier_month` existem desde a `0001` e `kamba_app` ja pode altera-las,
  mas quem as mantem e o KAM-023, que o «Fora de ambito» do KAM-015 exclui.
* **Nao consome os webhooks de template.** O destino `gestao_de_canal` tem
  tratador no KAM-016/KAM-021. Esta revisao da-lhes a tabela e o privilegio de
  `UPDATE` nas colunas de ciclo de vida, e o KAM-015 escreve a regra de
  bloqueio que elas sustentam.
* **Nao cria tabela de *handoff*, de consentimento nem de lembretes.** KAM-019,
  KAM-022, KAM-048.
"""

from __future__ import annotations

import json
import os

from alembic import op

import rls

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

#: O ciclo de vida de uma mensagem de saida. Lista fechada, imposta por `CHECK`
#: (dicionario §3.14, emenda 1.21).
#:
#: `queued` e a omissao: a linha nasce antes de haver chamada HTTP, e e isso que
#: torna o envio idempotente — quem repete a chave encontra a linha e nao
#: envia. `sent`, `delivered` e `read` vem dos `statuses` da Meta e sao
#: **monotonos** (criterio 3): um `delivered` seguido de um `sent` fica
#: `delivered`. `failed` e terminal. `suppressed_by_human` e do KAM-018 e nasce
#: aqui — ver o docstring.
#:
#: Os valores vem **ja entre apostrofos**, e isso nao e desleixo: e a unica
#: forma que o *gate* 3b resolve. Ele le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string*. Funcao
#: auxiliar, constante derivada e expressao geradora sao recusadas, cada uma com
#: a sua mensagem (ver `0008`, que pagou as tres).
ESTADOS = (
    "'queued'",
    "'sent'",
    "'delivered'",
    "'read'",
    "'failed'",
    "'suppressed_by_human'",
)

#: A categoria que a Meta factura. Lista fechada (§3.14; `docs/tecnica/01` §8.2).
#:
#: `service` e a mensagem livre dentro da janela de 24 h; as outras tres exigem
#: template. O `marketing` esta no dominio porque a Meta **recategoriza** e a
#: tabela tem de poder registar o que ela diz — o que o Piloto recusa e
#: **enviar** nessa categoria (criterio 7), e recusar no envio e diferente de
#: nao saber ler o que chega.
#:
#: Atencao ao nome: `kind` ja e coluna de `inbound_events` (§3.12, doze
#: valores). Duas colunas com o mesmo nome e dominios diferentes convivem
#: porque o *gate* 3b compara uma entrada **por coluna qualificada pela
#: tabela**; e a armadilha que o §3.13 registou.
CATEGORIAS = ("'service'", "'utility'", "'marketing'", "'authentication'")

#: O estado de aprovacao de um template, **em minusculas** (§3.14, divergencia 4).
ESTADOS_DE_TEMPLATE = (
    "'pending'",
    "'approved'",
    "'rejected'",
    "'paused'",
    "'disabled'",
)

#: A categoria de um template. Tres, e nao quatro: nao ha template `service` —
#: uma mensagem de servico e livre, por definicao.
CATEGORIAS_DE_TEMPLATE = ("'utility'", "'marketing'", "'authentication'")

#: A nota de qualidade que a Meta da a um template, em minusculas. Anulavel: um
#: template recem-submetido nao tem nota.
QUALIDADES = ("'green'", "'yellow'", "'red'")

#: A variavel que autoriza um `downgrade` destrutivo. A mesma forma da `0003` e
#: da `0009`.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0010_COPIA"

#: As colunas que o `kamba_app` pode alterar numa mensagem de saida.
#:
#: Cinco, e sao as que o ciclo de vida muda depois de a linha existir: o estado,
#: o `wamid` que a Meta devolve, o `pricing` que chega nos `statuses`, o codigo
#: de erro de uma falha e o instante da entrega.
#:
#: **O que nao esta aqui e o que importa.** `tenant_id`, `channel_id`,
#: `contact_id`, `conversation_id`, `idempotency_key`, `kind`, `template_name` e
#: `created_at` nao se alteram nunca por esta via. Reescrever a
#: `idempotency_key` de uma linha que passou e faze-la voltar a passar — a mesma
#: frase que a `0008` escreveu para o `kind`/`event_key` — e mudar o `kind`
#: depois do envio e reescrever quanto a mensagem custou.
COLUNAS_DA_APLICACAO = (
    "state",
    "wamid",
    "pricing",
    "error_code",
    "delivered_at",
)

#: As colunas de um template que o `kamba_app` pode alterar.
#:
#: Seis, e todas vem de **fora**: os tres webhooks de template
#: (`message_template_status_update`, `template_category_update`,
#: `message_template_quality_update`) escrevem `status`, `category` e `quality`;
#: o `meta_template_id` chega na submissao; o `bloqueado_em` e a regra de
#: bloqueio do criterio 9; e o `updated_at` acompanha os outros.
#:
#: **Nao leva `tenant_id`, `name`, `lang` nem `body_hash`.** Os tres primeiros
#: sao a chave primaria — altera-los e fazer o template ser outro — e o
#: `body_hash` e o que permite dizer «o corpo aprovado nao e o corpo que estamos
#: a enviar»: se a aplicacao o pudesse reescrever, deixava de o poder dizer.
COLUNAS_DO_TEMPLATE_NA_APLICACAO = (
    "status",
    "category",
    "quality",
    "meta_template_id",
    "bloqueado_em",
    "updated_at",
)


def upgrade() -> None:
    # --------------------------------- o que a FK composta da conversa precisa
    #
    # O `FORCE` sai e volta na mesma transacao (ver o docstring e
    # `docs/isolamento.md` §6). A instrucao do meio e a unica que pode falhar, e
    # se falhar nada fica — incluindo o `NO FORCE`.
    #
    # A `0009` fez exactamente isto a `tenant_channels`, e por isso a FK do
    # canal ja tem onde assentar. A da conversa nao tinha.
    op.execute("ALTER TABLE platform.conversations NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE platform.conversations "
        "ADD CONSTRAINT conversations_tenant_id_uq UNIQUE (tenant_id, id)"
    )
    op.execute("ALTER TABLE platform.conversations FORCE ROW LEVEL SECURITY")

    # -------------------------------------------------------- message_templates
    #
    # A chave primaria e `(tenant_id, name, lang)`, como o §8.3: um template e
    # identificado pelo que a Meta conhece, e nao por um UUID nosso. O §2 do
    # dicionario pede UUID para a coluna que **referencia**, e nada referencia
    # esta tabela por chave estrangeira — ver a nota de `template_name` abaixo.
    op.execute(
        f"""
        CREATE TABLE platform.message_templates (
            tenant_id        uuid        NOT NULL,
            name             text        NOT NULL,
            lang             text        NOT NULL,
            category         text        NOT NULL,
            status           text        NOT NULL DEFAULT 'pending',
            -- Anulavel: um template recem-submetido nao tem nota.
            quality          text,
            -- Anulavel: o identificador da Meta so existe depois de ela aceitar
            -- a submissao.
            meta_template_id text,
            body_hash        text        NOT NULL,
            -- O instante em que o template foi bloqueado, e NULL quando nao
            -- esta. Um booleano dizia que esta bloqueado e nao dizia desde
            -- quando, e o criterio 9 pede alerta — que se audita pela data.
            bloqueado_em     timestamptz,
            updated_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT message_templates_pkey PRIMARY KEY (tenant_id, name, lang),
            CONSTRAINT message_templates_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT message_templates_category_ck
                CHECK (category IN ({", ".join(CATEGORIAS_DE_TEMPLATE)})),
            CONSTRAINT message_templates_status_ck
                CHECK (status IN ({", ".join(ESTADOS_DE_TEMPLATE)})),
            -- Sem o `quality IS NULL OR` a cabeca, e isso **nao** deixa de
            -- permitir nulos: em SQL um `CHECK` que avalie a NULL **passa**,
            -- e `NULL IN (...)` e NULL. A forma explicita diz a mesma coisa e o
            -- *gate* 3b recusa-a, porque so reconhece `coluna IN (...)` como
            -- dominio fechado — e tem razao em ser estreito: e por ai que um
            -- `CHECK` que nao fecha nada passaria por um que fecha.
            CONSTRAINT message_templates_quality_ck
                CHECK (quality IN ({", ".join(QUALIDADES)}))
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.message_templates.status IS "
        "'Em minusculas, contra o docs/tecnica/01 §8.3, que usa o vocabulario "
        "da Meta: o §2 do dicionario manda minusculas e a base e nossa. A "
        "traducao faz-se na fronteira.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.message_templates.bloqueado_em IS "
        "'Instante do bloqueio por recategorizacao para marketing (criterio 9 "
        "do KAM-015). NULL quando o template esta utilizavel.'"
    )

    rls.enable_tenant_rls("message_templates")

    # ------------------------------------------------------- outbound_messages
    op.execute(
        f"""
        CREATE TABLE platform.outbound_messages (
            id              uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       uuid        NOT NULL,
            channel_id      uuid        NOT NULL,
            contact_id      uuid        NOT NULL,
            conversation_id uuid        NOT NULL,
            idempotency_key text        NOT NULL,
            -- Anulavel: a linha nasce em `queued`, antes de haver chamada HTTP,
            -- e o `wamid` so existe depois de a Meta aceitar. E isso que torna
            -- o envio idempotente — quem repete a chave encontra a linha.
            wamid           text,
            kind            text        NOT NULL,
            -- Anulavel so para `service`: ver a constraint de coerencia.
            template_name   text,
            state           text        NOT NULL DEFAULT 'queued',
            -- O `pricing` que chegou nos `statuses`, tal e qual. Nao se
            -- recalcula: a cobranca e por mensagem entregue e quem factura e a
            -- Meta (E1 §1, CONFIRMADO).
            pricing         jsonb,
            error_code      int,
            created_at      timestamptz NOT NULL DEFAULT now(),
            delivered_at    timestamptz,
            CONSTRAINT outbound_messages_pkey PRIMARY KEY (id),
            CONSTRAINT outbound_messages_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- As tres compostas, como todas as FK desde a `0003`: a mensagem, o
            -- contacto, o canal e a conversa sao do mesmo tenant, e e a base
            -- que o diz.
            CONSTRAINT outbound_messages_contact_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            CONSTRAINT outbound_messages_channel_fk
                FOREIGN KEY (tenant_id, channel_id)
                REFERENCES platform.tenant_channels (tenant_id, id),
            CONSTRAINT outbound_messages_conversation_fk
                FOREIGN KEY (tenant_id, conversation_id)
                REFERENCES platform.conversations (tenant_id, id),
            CONSTRAINT outbound_messages_kind_ck
                CHECK (kind IN ({", ".join(CATEGORIAS)})),
            CONSTRAINT outbound_messages_state_ck
                CHECK (state IN ({", ".join(ESTADOS)})),
            -- **Por tenant, e nao global.** Ver a divergencia 2 do docstring.
            CONSTRAINT outbound_messages_idempotency_uq
                UNIQUE (tenant_id, idempotency_key),
            -- Global, e a assimetria e deliberada: o `wamid` e da Meta.
            CONSTRAINT outbound_messages_wamid_uq UNIQUE (wamid),
            -- Uma mensagem `service` e livre e nao leva template; as outras
            -- tres exigem um. E a tabela de decisao do §8.2 em forma de
            -- constraint, e e o que impede uma `utility` sem template de ser
            -- gravada como se tivesse sido enviada.
            CONSTRAINT outbound_messages_template_ck
                CHECK ((kind = 'service' AND template_name IS NULL)
                       OR (kind <> 'service' AND template_name IS NOT NULL)),
            -- Um instante de entrega nao existe antes de haver entrega: a
            -- cobranca e na entrega, e um `delivered_at` num `queued` tornava o
            -- custo impossivel de reconciliar.
            --
            -- **Os dois terminais estao na lista, e a primeira versao nao os
            -- tinha.** Uma mensagem entregue pode passar a `failed` depois (a
            -- Meta nao garante ordem nos `statuses`, e o `estados.ts` deixa
            -- sair de qualquer nao-terminal para um terminal), e o
            -- `delivered_at` **nao se apaga** nesse caso: a entrega aconteceu,
            -- o custo ja foi contado, e apagar o instante era destruir a linha
            -- de auditoria que reconcilia a factura. Sem `failed` e
            -- `suppressed_by_human` aqui, esse `UPDATE` morria com 23514 —
            -- medido no ensaio de base, nao previsto.
            CONSTRAINT outbound_messages_entrega_ck
                CHECK (delivered_at IS NULL
                       OR state IN ('delivered', 'read', 'failed',
                                    'suppressed_by_human')),
            -- Um codigo de erro so existe num `failed`.
            CONSTRAINT outbound_messages_erro_ck
                CHECK (error_code IS NULL OR state = 'failed')
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.outbound_messages.idempotency_key IS "
        "'Unica por (tenant_id, idempotency_key) e nao global, contra o "
        "docs/tecnica/01 §8.4: com unicidade global um tenant suprime "
        "mensagens de outro se adivinhar a chave. Ver a emenda 1.18.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.outbound_messages.pricing IS "
        "'O pricing que chegou nos statuses, tal e qual: billable, "
        "pricing_model, type e category. Nao se recalcula.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.outbound_messages.conversation_id IS "
        "'Nao esta no DDL do docs/tecnica/01 §8.4. Sem ela nao ha ordem por "
        "conversa, que o criterio 6 do KAM-015 pede.'"
    )

    rls.enable_tenant_rls("outbound_messages")

    # ------------------------------------------------------------- privilegios
    #
    # Tabela a tabela e coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: uma
    # tabela nova nao nasce acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # O `SELECT` de tabela em `outbound_messages` e preciso e nao e generoso: o
    # adapter le a linha para saber se a chave ja passou (idempotencia) e para
    # recusar um estado que ande para tras (monotonia), e o
    # `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING`
    # exige `SELECT` nas colunas de inferencia — a licao que a `0008` escreveu
    # para o `SQL_QUARENTENA`.
    op.execute("GRANT SELECT, INSERT ON platform.outbound_messages TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_APLICACAO)}) "
        "ON platform.outbound_messages TO kamba_app"
    )

    # **`SELECT` e `UPDATE`, e nao `INSERT`.** Quem submete templates e o
    # onboarding (KAM-091) — ver o docstring.
    op.execute("GRANT SELECT ON platform.message_templates TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DO_TEMPLATE_NA_APLICACAO)}) "
        "ON platform.message_templates TO kamba_app"
    )

    # O `kamba_batch` tem os quatro verbos nas duas, que e o que tem em todas as
    # outras desde a `0001`, porque e quem purga (KAM-071).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON platform.outbound_messages TO kamba_batch"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON platform.message_templates TO kamba_batch"
    )


#: As colunas que a copia logica do `downgrade` escreve, pela ordem em que saem.
COLUNAS_DA_COPIA_DE_ENVIOS = (
    "id",
    "tenant_id",
    "channel_id",
    "contact_id",
    "conversation_id",
    "idempotency_key",
    "wamid",
    "kind",
    "template_name",
    "state",
    "pricing",
    "error_code",
    "created_at",
    "delivered_at",
)

#: Idem para os templates.
COLUNAS_DA_COPIA_DE_TEMPLATES = (
    "tenant_id",
    "name",
    "lang",
    "category",
    "status",
    "quality",
    "meta_template_id",
    "body_hash",
    "bloqueado_em",
    "updated_at",
)

# As quatro funcoes abaixo nao recebem argumentos, e nao e por gosto: o *gate*
# 3b le esta revisao sem a correr, e so segue uma chamada cujos argumentos
# consiga resolver. E a mesma razao que a `0003` e a `0009` escreveram para as
# suas.


def _contar_envios() -> int:
    """Quantas mensagens de saida existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.outbound_messages"
    ).scalar_one()


def _contar_templates() -> int:
    """Quantos templates existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.message_templates"
    ).scalar_one()


def _envios() -> list[dict]:
    """A tabela de envios em JSON: UUID e tempos como texto, `pricing` tal e qual."""
    resultado = op.get_bind().exec_driver_sql(
        "SELECT id, tenant_id, channel_id, contact_id, conversation_id, "
        "       idempotency_key, wamid, kind, template_name, state, "
        "       pricing, error_code, created_at, delivered_at "
        "  FROM platform.outbound_messages ORDER BY created_at, id"
    )
    copia = []
    for linha in resultado:
        copia.append(
            {
                coluna: (None if valor is None else valor if coluna == "pricing" else str(valor))
                for coluna, valor in zip(COLUNAS_DA_COPIA_DE_ENVIOS, linha)
            }
        )
    return copia


def _templates() -> list[dict]:
    """A tabela de templates em JSON."""
    resultado = op.get_bind().exec_driver_sql(
        "SELECT tenant_id, name, lang, category, status, quality, "
        "       meta_template_id, body_hash, bloqueado_em, updated_at "
        "  FROM platform.message_templates ORDER BY tenant_id, name, lang"
    )
    copia = []
    for linha in resultado:
        copia.append(
            {
                coluna: (None if valor is None else str(valor))
                for coluna, valor in zip(COLUNAS_DA_COPIA_DE_TEMPLATES, linha)
            }
        )
    return copia


def downgrade() -> None:
    """Reverter apaga o que foi enviado e o que esta aprovado, e por isso pergunta.

    O que se perde sao duas coisas que nao se reconstroem. A primeira e o
    **custo**: o `pricing` de cada mensagem entregue e o unico registo do que a
    Meta cobrou, e o §16 do `docs/tecnica/01` aponta-o como o mecanismo de
    «custo monitorizado por tenant e por mensagem» — sem ele nao ha como
    reconciliar uma factura. A segunda e a **idempotencia**: as chaves que ja
    passaram desaparecem, e um `upgrade` seguido de uma repeticao de envio
    reenvia tudo o que estava em voo.

    Com linhas em qualquer das duas tabelas, exige-se `KAMBA_DOWNGRADE_0010_COPIA`
    com o caminho de um ficheiro onde as duas sao escritas antes de cairem — a
    mesma forma da `0003` e da `0009` (`db/migrations/README.md`). Sem a
    variavel, o `downgrade` **recusa**: nao ha perda em silencio.

    **As politicas saem ANTES de se contar, e isso foi um defeito medido na
    `0009`.** Com `FORCE ROW LEVEL SECURITY`, o dono da tabela esta sujeito a
    politica — e uma migracao corre **sem** contexto de tenant. Contar `count(*)`
    como `kamba_migrator` ve **zero linhas** sobre uma tabela cheia: nao pede
    copia nenhuma e apaga em silencio, que e exactamente o contrario do que
    estas linhas existem para impedir. E a mesma armadilha que o
    `docs/isolamento.md` §6 escreve para a validacao de uma FK nova — «a
    validacao passa sem ter olhado para nada» —, aqui a contar em vez de
    validar. As duas tabelas desta revisao tem `FORCE`, logo sao **duas**
    chamadas a `disable_tenant_rls` antes da primeira contagem.

    Os `disable_tenant_rls` sao as primeiras instrucoes, e por isso a recusa
    tambem as desfaz: o Alembic corre **uma transacao por revisao**
    (`transaction_per_migration=True`), pelo que levantar aqui deixa as tabelas
    com as politicas intactas e a base em `0010`.
    """
    rls.disable_tenant_rls("outbound_messages")
    rls.disable_tenant_rls("message_templates")

    envios = _contar_envios()
    templates = _contar_templates()
    if envios or templates:
        destino = os.environ.get(VARIAVEL_DA_COPIA, "").strip()
        if not destino:
            raise RuntimeError(
                f"downgrade da 0010: ha {envios} mensagem(ns) de saida e "
                f"{templates} template(s), e reverter apaga-os — com eles, o "
                "pricing de cada mensagem entregue (o unico registo do que a "
                "Meta cobrou) e as chaves de idempotencia que ja passaram. "
                f"Defina {VARIAVEL_DA_COPIA} com o caminho de um ficheiro para "
                "a copia logica, ou esvazie as duas tabelas primeiro."
            )
        with open(destino, "w", encoding="utf-8") as ficheiro:
            json.dump(
                {
                    "outbound_messages": _envios(),
                    "message_templates": _templates(),
                },
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
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou,
    # o `downgrade` falha em vez de o apagar em silencio. A `outbound_messages`
    # cai primeiro porque e ela que referencia a `conversations`.
    op.execute("DROP TABLE platform.outbound_messages")
    op.execute("DROP TABLE platform.message_templates")

    # A `UNIQUE` sai depois da tabela que a usava, e com o mesmo cuidado do
    # `FORCE` — um `DROP CONSTRAINT` nao le linhas, mas a simetria com o
    # `upgrade` e o que faz o par `upgrade`/`downgrade` ser lido de uma vez.
    op.execute("ALTER TABLE platform.conversations NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE platform.conversations "
        "DROP CONSTRAINT conversations_tenant_id_uq"
    )
    op.execute("ALTER TABLE platform.conversations FORCE ROW LEVEL SECURITY")

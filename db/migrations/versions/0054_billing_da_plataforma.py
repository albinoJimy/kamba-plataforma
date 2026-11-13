"""Billing da plataforma: assinatura pela mesma interface de pagamento (KAM-059).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

As quatro tabelas do `docs/tecnica/04` §11.2, a FK que a `0029` deixou para
este ticket, e as barreiras que fazem do ciclo uma propriedade da base:

    price_book                o precario, versionado por `valido_de`. So se
                              acrescenta; cada linha nova fica no `audit_log`
                              (criterio 6), pelo *trigger* `price_book_auditado`
    subscriptions             uma por tenant (`UNIQUE (tenant_id)`)
    billing_cycles            `UNIQUE (subscription_id, periodo)`: um ciclo por
                              periodo (criterio 1)
    commission_accruals       so `modo='sombra'` (`commission_accruals_so_sombra`)
                              e so de um `pagamento_confirmado` autenticado pelo
                              facilitador (criterio 7)
    billing_ops_approvals     as aprovacoes de ops da confirmacao manual de um
                              ciclo, uma por pessoa e por cobranca (criterio 5)
    charges_billing_fk        `(tenant_id, billing_cycle_id)` -> `billing_cycles`

    billing_cycles_transicao  o grafo do estado do ciclo; `paga` so com a
                              cobranca `paga` (DoD: «pagamento so por evento
                              autenticado ou confirmacao humana de ops»)
    payment_charges_ciclo_pago a projeccao: a cobranca do ciclo passa a `paga`
                              no ledger, o ciclo passa a `paga` e emite-se
                              `billing.cycle_paid`, **na mesma transaccao**
                              (criterio 4)
    billing_confirmar_ops     a confirmacao de ops com dupla aprovacao
    payment_events_g8_ops     o G8 do caminho de ops, para as cobrancas de ciclo
    payment_events_billing_papel
                              o ledger de um ciclo so pelo `kamba_pay`, e o
                              `kamba_pay` so no ledger dos ciclos
    payment_charges_ciclo_vivo
                              uma cobranca nova so num ciclo que ainda se cobra

## Porque e que o ciclo nao ouve o `payment.confirmed`

O criterio 4 escreve «`payment.confirmed` autenticado leva o ciclo a `paga`». O
envelope `payment.confirmed` **nao existe** para uma cobranca de ciclo: a `0035`
fechou-o as cobrancas de encomenda, porque os cinco contratos `payment.*`
agregam por `order` e exigem `order_id` («o evento de billing e do KAM-059 e
tera contrato proprio»). O que existe e o **facto** que esse envelope publica —
o `pagamento_confirmado` autenticado no ledger —, e e dele que o ciclo depende:
o *trigger* `payment_charges_ciclo_pago` corre quando a projeccao do ledger poe
a cobranca do ciclo em `paga`.

Isto e mais forte do que um consumidor, e nao so mais curto: um consumidor era
um segundo processo a poder falhar entre o pagamento e o ciclo, e a
idempotencia ficava do recibo dele. Aqui a idempotencia e do ledger — o mesmo
`pagamento_confirmado` dez vezes da **uma** transicao da cobranca (o G7 absorve
as repeticoes antes do ledger, e uma cobranca `paga` nao volta a `paga`) — e do
`WHERE estado IN (...)` do `UPDATE` do ciclo, que so muda uma vez.

## O papel de billing e o `kamba_pay`

O §6.2 diz que a conta de receita propria e «acessivel so ao papel de billing»,
e a `0027` escreveu que esse papel nao existia e nomeou este ticket como
credor. Existe desde a `0051` (KAM-197): e o papel do PAY. Esta revisao da-lhe
**uma politica** sobre a `payment_accounts` — `pay_receita_propria`, so
`SELECT`, so as linhas de `plataforma_receita_propria` — e **so as colunas** de
que o `assert_beneficiary` precisa. Sem o `webhook_token` nem o
`credenciais_ref`, pela licao da `0029` (a segunda versao do `pay_hooks_token`
enumerava os *tokens* de todas as PMEs).

**Porque e que nao e uma `SECURITY DEFINER`**: o dono das funcoes e o
`kamba_migrator`, que e `NOBYPASSRLS`, e o `FORCE` vincula-o — dentro de uma
`DEFINER` a conta de `tenant_id` nulo e invisivel, e o `assert_beneficiary`
(`INVOKER`) recusava toda a cobranca de billing. E a razao escrita na `0027`.
Por isso o *job* corre **como** `kamba_pay`, e a politica e o que lhe da a conta.

O *job* tambem le as subscricoes de **todos** os tenants — e a lista de quem a
KAMBA cobra —, pelo que o `kamba_pay` tem uma segunda politica,
`pay_billing_subscricoes`, de `SELECT` sobre a `subscriptions`. As escritas
(ciclo e cobranca) continuam sob a `tenant_iso`: o *job* poe o `app.tenant_id`
do tenant que esta a cobrar, e o `WITH CHECK` recusa outro.

## O G8 das cobrancas de ciclo

O G8 da `0032` (`exigir_fase_manual`) exige, para um `pagamento_confirmado`
manual, uma fase de `manual_confirmations` com o `actor_contact_id` do evento —
e a `manual_confirmations_actor_fk` aponta para `contacts`. **Ops nao e um
contacto**: a identidade da equipa e do IdP (KAM-196, dicionario §3.65), e nao
ha tabela dela. Logo o G8 da `0032` recusa sempre a confirmacao de ops de um
ciclo.

A saida **nao** reescreve a `exigir_fase_manual`: um `CREATE OR REPLACE`
copiava o corpo para aqui, e a copia passava a ser a que corre — as mutacoes que
alguem escrever sobre o texto da `0032` deixavam de morder. Em vez disso, o
*trigger* da `0032` passa a ter `WHEN (NEW.billing_cycle_id IS NULL)` — a funcao
dele continua a ser a que corre para toda a cobranca de encomenda, sem uma
letra mudada — e as cobrancas de ciclo ganham o seu proprio, o
`payment_events_g8_ops`: `actor_kind='ops'`, motivo nao vazio, e **duas**
aprovacoes de pessoas distintas, uma delas a do evento. Os dois `ENABLE
ALWAYS`.

E o caminho do dono fica **fechado** as cobrancas de ciclo: a PME e quem paga,
e um confirmador dela a confirmar o pagamento a KAMBA era o devedor a passar o
proprio recibo. O *trigger* `manual_confirmations_so_encomenda` recusa a fase.

## O que fica de fora, e porque

* **O callback de um facilitador sobre a conta propria da KAMBA.** O
  `resolve_webhook_token` devolve o `tenant_id` da conta — nulo — e a cobranca
  do ciclo e do tenant que paga, pelo que o *worker* nao tem contexto onde a
  encontrar. Depende de a KAMBA ter conta EMIS ou facilitador (D4, NAO
  VERIFICADO), que e o que o bloco manda deixar parcial.
* **A regua (D+3/D+7/D+10)**, os estados `em_atraso` e `suspensa` da subscricao
  e o agendamento do *job*: KAM-058.
* **A factura-recibo.** Nenhum documento fiscal sai daqui (DP 71/25, D7).
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0054"
#: **Provisorio.** Escrita sobre a cabeca da `publico/main` (`0051`) para que o
#: *gate* 8 corra; o numero final e o `down_revision` da-os o orquestrador na
#: integracao, pela ordem de quem fica pronto (a cadeia prevista e #193 `0052`,
#: KAM-097 `0053`, este `0054`).
down_revision = "0051"
branch_labels = None
depends_on = None

PRECARIO = "platform.price_book"
SUBSCRICOES = "platform.subscriptions"
CICLOS = "platform.billing_cycles"
ACCRUALS = "platform.commission_accruals"
APROVACOES = "platform.billing_ops_approvals"
COBRANCAS = "platform.payment_charges"
EVENTOS = "platform.payment_events"
CONTAS = "platform.payment_accounts"
CONFIRMACOES = "platform.manual_confirmations"

PAPEL_DO_PAY = "kamba_pay"
PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

#: Os estados do §11.2, ja entre apostrofos pela razao da `0015` (o *gate* 3b
#: so resolve `", ".join(<constante de modulo>)` dentro de uma f-string).
ESTADOS_DA_SUBSCRICAO = ("'ativa'", "'em_atraso'", "'suspensa'", "'cancelada'")
ESTADOS_DO_CICLO = (
    "'aberto'",
    "'cobranca_emitida'",
    "'paga'",
    "'em_atraso'",
    "'anulado'",
)
MODOS_DA_COMISSAO = ("'sombra'", "'facturavel'")

#: Os dois de `authn_method` que autenticam pelo facilitador. A sombra da
#: comissao so deriva destes (§11.1: «`paga_via='provider_autenticado'`»): uma
#: confirmacao humana nao mede atribuicao nenhuma.
AUTENTICADOS_PELO_FACILITADOR = ("'hmac'", "'consulta'")

#: As colunas que o papel de billing escreve numa cobranca: **sem `order_id`**.
COLUNAS_DA_COBRANCA_DE_CICLO = (
    "id, tenant_id, billing_cycle_id, tentativa, account_id, provider, metodo, "
    "referencia, amount_minor, currency, valid_until"
)

#: O `COMMENT` do `assert_beneficiary`, como a `0027` o deixou (para o
#: `downgrade`) e como fica: o billing corre como `kamba_pay`, e nao como
#: `kamba_batch`, que era o que a `0027` dizia antes de haver papel de billing.
COMENTARIO_G1_0027 = (
    "Guarda G-1 do docs/tecnica/04 secao 10.4 (KAM-052): o beneficiario de "
    "uma cobranca de encomenda e a PME que vendeu, e o de uma de billing e a "
    "KAMBA. O CREATE TRIGGER sobre payment_charges e do KAM-055. SECURITY "
    "INVOKER: o DEFINER nao contorna FORCE ROW LEVEL SECURITY (corre como o "
    "dono, que e NOBYPASSRLS), e o billing corre como kamba_batch, que tem "
    "BYPASSRLS e ve a conta de tenant_id nulo."
)
COMENTARIO_G1 = (
    "Guarda G-1 do docs/tecnica/04 secao 10.4 (KAM-052): o beneficiario de "
    "uma cobranca de encomenda e a PME que vendeu, e o de uma de billing e a "
    "KAMBA. SECURITY INVOKER: o DEFINER nao contorna FORCE ROW LEVEL SECURITY. "
    "O billing corre como kamba_pay, que ve a conta de tenant_id nulo pela "
    "politica pay_receita_propria (KAM-059)."
)

#: A assinatura da porta de ops, para o `COMMENT`, o `GRANT` e o `DROP`.
CONFIRMAR_OPS = "platform.billing_confirmar_ops(uuid, uuid, text, bigint)"


def upgrade() -> None:
    _precario()
    _subscricoes()
    _ciclos()
    _fk_da_cobranca()
    _accruals()
    _aprovacoes()
    _transicao_do_ciclo()
    _ciclo_pago()
    _g8_das_cobrancas_de_ciclo()
    _confirmar_ops()
    _rls()
    _privilegios()


# ---------------------------------------------------------------- tabelas


def _precario() -> None:
    """`price_book`: global, sem `tenant_id` e so de acrescentar.

    **Sem `tenant_id` e sem RLS**, como a `payment_outbox_map`: o preco de um
    plano e o mesmo para todos os tenants, e uma politica por tenant numa tabela
    sem tenant nao isolava nada. O que se protege aqui e a **escrita**: so o
    `kamba_batch` insere, ninguem actualiza nem apaga, e cada linha nova fica no
    `audit_log` com o actor que a sessao declarou (`app.actor_id`). Sem actor,
    o `INSERT` e recusado — um preco sem autor nao entra.

    O `iva_pct` tem `14.00` por omissao, como o DDL do §11.2, e o bloco diz o
    estado: **a confirmar com contabilista**, e nao esta em
    `docs/tecnica/evidencia/`. O `valor_minor` e o que se cobra; se inclui o IVA
    ou nao e a mesma pergunta, e fica com ela.
    """
    op.execute(
        f"""
        CREATE TABLE {PRECARIO} (
            id          uuid         NOT NULL DEFAULT gen_random_uuid(),
            plano       text         NOT NULL,
            valor_minor bigint       NOT NULL,
            currency    char(3)      NOT NULL DEFAULT 'AOA',
            iva_pct     numeric(4,2) NOT NULL DEFAULT 14.00,
            valido_de   date         NOT NULL,
            -- Exclusivo, como o fim do periodo. Nulo: vale ate haver outra.
            valido_ate  date,
            nota        text,
            criado_at   timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT price_book_pkey PRIMARY KEY (id),
            CONSTRAINT price_book_plano_valido_de_uq UNIQUE (plano, valido_de),
            CONSTRAINT price_book_plano_ck CHECK (plano ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT price_book_valor_ck CHECK (valor_minor >= 0),
            CONSTRAINT price_book_currency_ck CHECK (currency = 'AOA'),
            CONSTRAINT price_book_iva_ck CHECK (iva_pct >= 0 AND iva_pct < 100),
            CONSTRAINT price_book_validade_ck CHECK (valido_ate > valido_de)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {PRECARIO} IS "
        "'Precario da assinatura da KAMBA (KAM-059; docs/tecnica/04 secao 11.2 e "
        "12). Versionado por valido_de e so de acrescentar: uma alteracao de "
        "preco e uma linha nova, que vale a partir do ciclo seguinte e fica no "
        "audit_log (price_book_auditado). Precos e IVA sao decisao de produto e "
        "de contabilista, nao deste esquema.'"
    )
    # O `plano` tem a forma do `tenants_plano_ck` da `0007`, e e a mesma coluna
    # conceptual: o plano em que o tenant esta, cujo preco esta aqui.
    op.execute(
        """
        CREATE FUNCTION platform.price_book_auditar() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_actor text := NULLIF(btrim(current_setting('app.actor_id', true)), '');
        BEGIN
          IF v_actor IS NULL THEN
            RAISE EXCEPTION
              'price_book: uma linha de preco sem actor nao entra; a sessao '
              'declara app.actor_id e a alteracao fica no audit_log (KAM-059, '
              'criterio 6)'
              USING ERRCODE = 'check_violation';
          END IF;
          PERFORM platform.audit_append(
            NULL, 'staff', v_actor, 'price.update', 'price_book', NEW.id::text,
            NULL,
            sha256(convert_to(
              NEW.plano || chr(31) || NEW.valor_minor::text || chr(31) ||
              NEW.iva_pct::text || chr(31) || NEW.valido_de::text || chr(31) ||
              coalesce(NEW.valido_ate::text, ''), 'UTF8')));
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.price_book_auditar() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER price_book_auditado
          AFTER INSERT ON {PRECARIO}
          FOR EACH ROW EXECUTE FUNCTION platform.price_book_auditar()
        """
    )
    op.execute(f"ALTER TABLE {PRECARIO} ENABLE ALWAYS TRIGGER price_book_auditado")


def _subscricoes() -> None:
    """`subscriptions`: uma por tenant.

    O `periodo_dia` vai de 1 a 28, e o DDL do §11.2 nao o limitava: um dia 31
    nao existe em Fevereiro, e qualquer regra de recuo fazia as fronteiras dos
    periodos moverem-se de mes para mes — com o `UNIQUE (subscription_id,
    periodo)` a deixar de querer dizer «um por mes».

    `subscriptions_tenant_id_uq (tenant_id, id)` nao serve consulta nenhuma:
    existe para que o ciclo a referencie pelo par, pela licao ISO-58 da `0030`
    (uma FK so sobre `subscription_id` deixava o ciclo do tenant A apontar para a
    subscricao de B).
    """
    op.execute(
        f"""
        CREATE TABLE {SUBSCRICOES} (
            id          uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id   uuid        NOT NULL,
            plano       text        NOT NULL,
            estado      text        NOT NULL DEFAULT 'ativa',
            periodo_dia smallint    NOT NULL DEFAULT 1,
            criado_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT subscriptions_pkey PRIMARY KEY (id),
            CONSTRAINT subscriptions_tenant_uq UNIQUE (tenant_id),
            CONSTRAINT subscriptions_tenant_id_uq UNIQUE (tenant_id, id),
            CONSTRAINT subscriptions_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT subscriptions_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DA_SUBSCRICAO)})),
            CONSTRAINT subscriptions_plano_ck CHECK (plano ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT subscriptions_periodo_dia_ck
                CHECK (periodo_dia BETWEEN 1 AND 28)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {SUBSCRICOES} IS "
        "'A assinatura de cada tenant a KAMBA (KAM-059; docs/tecnica/04 secao "
        "11.2). Mudar o plano actualiza os entitlements na mesma instrucao "
        "(SQL_MUDAR_PLANO de packages/core-ts/src/pagamentos/billing.ts). O "
        "estado em_atraso nao toca nos limites: so a suspensao da regua "
        "(KAM-058) os tira.'"
    )


def _ciclos() -> None:
    """`billing_cycles`: um por subscricao e por periodo (criterio 1).

    `valor_minor > 0`, e o DDL nao o dizia: a cobranca do ciclo tem
    `payment_charges_amount_ck (amount_minor > 0)`, pelo que um ciclo de zero
    era um ciclo que nunca se podia cobrar. Um plano gratuito nao abre ciclo.

    O `periodo` e um `daterange` limitado nos dois lados e nao vazio; a forma
    canonica de um intervalo discreto no PostgreSQL e sempre `[)`, pelo que
    `[inicio, fim)` e o que fica gravado seja qual for a forma escrita.
    """
    op.execute(
        f"""
        CREATE TABLE {CICLOS} (
            id              uuid      NOT NULL DEFAULT gen_random_uuid(),
            subscription_id uuid      NOT NULL,
            tenant_id       uuid      NOT NULL,
            periodo         daterange NOT NULL,
            valor_minor     bigint    NOT NULL,
            estado          text      NOT NULL DEFAULT 'aberto',
            CONSTRAINT billing_cycles_pkey PRIMARY KEY (id),
            CONSTRAINT billing_cycles_periodo_uq UNIQUE (subscription_id, periodo),
            CONSTRAINT billing_cycles_tenant_id_uq UNIQUE (tenant_id, id),
            CONSTRAINT billing_cycles_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT billing_cycles_subscricao_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, subscription_id)
                REFERENCES {SUBSCRICOES} (tenant_id, id),
            CONSTRAINT billing_cycles_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS_DO_CICLO)})),
            CONSTRAINT billing_cycles_valor_ck CHECK (valor_minor > 0),
            CONSTRAINT billing_cycles_periodo_ck CHECK (
                NOT isempty(periodo)
                AND NOT lower_inf(periodo) AND NOT upper_inf(periodo))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {CICLOS} IS "
        "'Ciclo de facturacao da assinatura (KAM-059). Guarda o valor_minor do "
        "price_book em vigor no inicio do periodo, pelo que uma alteracao de "
        "preco nao toca num ciclo ja aberto. O estado paga so se atinge pela "
        "projeccao do ledger (payment_charges_ciclo_pago).'"
    )


def _fk_da_cobranca() -> None:
    """`charges_billing_fk`, composta com o `tenant_id`.

    O nome e o do §11.2 e do criterio 1. A forma e a das FK de encomenda da
    `0035` (`(tenant_id, order_id) -> orders_mirror (tenant_id, id)`), pela
    mesma razao: so sobre `billing_cycle_id`, a cobranca do tenant A podia
    apontar para o ciclo de B. `MATCH SIMPLE` deixa passar a cobranca de
    encomenda, que tem `billing_cycle_id` nulo.
    """
    op.execute(
        f"ALTER TABLE {COBRANCAS} ADD CONSTRAINT charges_billing_fk "
        f"FOREIGN KEY (tenant_id, billing_cycle_id) REFERENCES {CICLOS} (tenant_id, id)"
    )


def _accruals() -> None:
    """`commission_accruals`: sombra, e so sombra (criterio 7).

    Duas restricoes sobre o `modo`, e nao uma: `commission_accruals_modo_ck`
    fecha o dominio do §11.2 (`sombra`, `facturavel`), e
    `commission_accruals_so_sombra` estreita-o ao Piloto. Activar a facturacao
    de comissao e **largar a segunda**, numa revisao que cite o parecer (D8) — e
    nao uma *flag* que se liga em producao.

    `comissao_minor = base_minor * taxa_bps / 10000` (divisao inteira, e para
    numeros nao negativos e o `floor`) e um `CHECK`: a base nao guarda um valor
    que nao seja o calculo da taxa gravada ao lado.

    **Sem FK para a `payment_events`**, e nao e descuido: o gatilho abaixo
    confere que o evento existe (e e o certo), e o ledger e *append-only* — o
    evento nao desaparece. Uma FK so acrescentava uma coisa, e era um defeito:
    um `TRUNCATE` ao ledger passava a falhar com `0A000` («tabela referida por
    uma FK») **antes** do `payment_events_sem_truncate`, e os ensaios que medem
    que o ledger recusa o `TRUNCATE` deixavam de medir a barreira deles.

    O *trigger* `commission_accruals_so_autenticado` exige que o evento seja um
    `pagamento_confirmado` **aceite** e autenticado pelo facilitador (`hmac` ou
    `consulta`), do mesmo tenant e da mesma encomenda, e que a base seja o valor
    dele — a sombra mede atribuicao, e uma confirmacao humana nao mede nenhuma.

    **O `id` e `uuid` gerado, e o §11.2 escreve `bigint GENERATED ALWAYS AS
    IDENTITY`.** Prevalece o dicionario §2: uma chave sequencial vaza volume, e
    a excepcao so se admite quando nenhum papel sujeito a RLS le a coluna — o
    que aqui nao e verdade (o `kamba_pay` e o `kamba_app` leem a tabela sob a
    `tenant_iso`). Contada por tenant, a sequencia dizia quantos pagamentos
    autenticados a plataforma inteira teve.
    """
    op.execute(
        f"""
        CREATE TABLE {ACCRUALS} (
            id               uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id        uuid        NOT NULL,
            order_id         uuid        NOT NULL,
            payment_event_id bigint      NOT NULL,
            base_minor       bigint      NOT NULL,
            taxa_bps         integer     NOT NULL,
            comissao_minor   bigint      NOT NULL,
            modo             text        NOT NULL DEFAULT 'sombra',
            criado_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT commission_accruals_pkey PRIMARY KEY (id),
            CONSTRAINT commission_accruals_evento_uq UNIQUE (payment_event_id),
            CONSTRAINT commission_accruals_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT commission_accruals_encomenda_do_mesmo_tenant_fk
                FOREIGN KEY (tenant_id, order_id)
                REFERENCES platform.orders_mirror (tenant_id, id),
            CONSTRAINT commission_accruals_modo_ck
                CHECK (modo IN ({", ".join(MODOS_DA_COMISSAO)})),
            CONSTRAINT commission_accruals_so_sombra CHECK (modo = 'sombra'),
            CONSTRAINT commission_accruals_base_ck CHECK (base_minor >= 0),
            CONSTRAINT commission_accruals_taxa_ck
                CHECK (taxa_bps BETWEEN 0 AND 10000),
            CONSTRAINT commission_accruals_calculo_ck
                CHECK (comissao_minor = base_minor * taxa_bps / 10000)
        )
        """
    )
    # A leitura «a sombra deste tenant», pela encomenda. O `tenant_id` vem
    # primeiro, que e o predicado que a RLS acrescenta a todas as consultas.
    op.execute(
        f"CREATE INDEX commission_accruals_tenant_idx ON {ACCRUALS} (tenant_id, order_id)"
    )
    op.execute(
        f"COMMENT ON TABLE {ACCRUALS} IS "
        "'Comissao em modo sombra (KAM-059; docs/tecnica/04 secao 11.1): mede "
        "atribuicao e unit economics, nunca factura e nunca retem (ADR-004, "
        "ADR-017). So modo sombra enquanto D8 nao fechar: largar o "
        "commission_accruals_so_sombra e uma revisao que cite o parecer.'"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.commission_accrual_verificar() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_evento {EVENTOS};
        BEGIN
          SELECT * INTO v_evento FROM {EVENTOS} WHERE id = NEW.payment_event_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'commission_accruals: o evento % nao existe ou nao e visivel no '
              'contexto desta transaccao (RLS)', NEW.payment_event_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF v_evento.tipo_evento <> 'pagamento_confirmado'
             OR v_evento.decisao <> 'aceite'
             OR v_evento.authn_method NOT IN ({", ".join(AUTENTICADOS_PELO_FACILITADOR)})
             OR v_evento.authn_ok IS NOT TRUE THEN
            RAISE EXCEPTION
              'commission_accruals: a sombra so deriva de um pagamento_confirmado '
              'aceite e autenticado pelo facilitador (hmac ou consulta); o evento '
              '% e % por %', NEW.payment_event_id, v_evento.tipo_evento,
              v_evento.authn_method
              USING ERRCODE = 'check_violation';
          END IF;
          IF v_evento.tenant_id <> NEW.tenant_id
             OR v_evento.order_id IS DISTINCT FROM NEW.order_id
             OR v_evento.valor_minor IS DISTINCT FROM NEW.base_minor THEN
            RAISE EXCEPTION
              'commission_accruals: o tenant, a encomenda e a base tem de ser os '
              'do evento %', NEW.payment_event_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.commission_accrual_verificar() FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE TRIGGER commission_accruals_so_autenticado
          BEFORE INSERT ON {ACCRUALS}
          FOR EACH ROW EXECUTE FUNCTION platform.commission_accrual_verificar()
        """
    )
    op.execute(
        f"ALTER TABLE {ACCRUALS} ENABLE ALWAYS TRIGGER commission_accruals_so_autenticado"
    )


def _aprovacoes() -> None:
    """`billing_ops_approvals`: uma aprovacao de ops por pessoa e por cobranca.

    O `actor_id` e a identidade da equipa no IdP (KAM-196), **sem FK**: nao ha
    tabela dela, e e a mesma forma do `review_decision_log.revisor_id` da
    `0048`. A base nao autentica a pessoa — isso e da consola, com MFA —; o que
    a base garante e que duas aprovacoes sao de **dois** `actor_id` diferentes
    (`UNIQUE (charge_id, actor_id)`), que cada uma tem motivo, e que o valor
    aprovado e o da cobranca.
    """
    op.execute(
        f"""
        CREATE TABLE {APROVACOES} (
            id          uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id   uuid        NOT NULL,
            charge_id   uuid        NOT NULL,
            actor_id    uuid        NOT NULL,
            motivo      text        NOT NULL,
            valor_minor bigint      NOT NULL,
            criado_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT billing_ops_approvals_pkey PRIMARY KEY (id),
            CONSTRAINT billing_ops_approvals_pessoa_uq UNIQUE (charge_id, actor_id),
            CONSTRAINT billing_ops_approvals_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT billing_ops_approvals_charge_fk
                FOREIGN KEY (charge_id) REFERENCES {COBRANCAS} (id),
            CONSTRAINT billing_ops_approvals_motivo_ck CHECK (btrim(motivo) <> ''),
            CONSTRAINT billing_ops_approvals_valor_ck CHECK (valor_minor > 0)
        )
        """
    )
    op.execute(
        f"CREATE INDEX billing_ops_approvals_tenant_idx ON {APROVACOES} (tenant_id, charge_id)"
    )
    op.execute(
        f"COMMENT ON TABLE {APROVACOES} IS "
        "'Aprovacoes de ops da confirmacao manual de uma cobranca de ciclo "
        "(KAM-059, criterio 5; docs/tecnica/04 secao 9: confirmacoes de ops "
        "exigem motivo e dupla aprovacao). actor_id e a identidade da equipa "
        "(IdP, KAM-196), sem FK. Escrita pela billing_confirmar_ops.'"
    )


# ---------------------------------------------------------------- barreiras


def _transicao_do_ciclo() -> None:
    """O grafo de `billing_cycles.estado`, e o `paga` atado ao ledger.

    Nasce `aberto`. As arestas:

        aberto            -> cobranca_emitida | anulado
        cobranca_emitida  -> em_atraso | anulado | paga
        em_atraso         -> anulado | paga

    **`paga` so com uma cobranca deste ciclo em `paga`.** E a cobranca que so
    muda pela `append_payment_event` (nenhum papel tem `UPDATE` nela), pelo que
    um ciclo pago e, por construcao, um ciclo cujo pagamento esta no ledger —
    autenticado pelo facilitador ou confirmado por dois de ops. Um `UPDATE ...
    SET estado = 'paga'` de quem tenha o privilegio da coluna e recusado se a
    cobranca nao estiver la.

    E as outras colunas nao mudam: o valor de um ciclo e o do preco em vigor
    quando abriu (criterio 6), e um `UPDATE` que o mudasse depois era a
    alteracao de preco a meio que o criterio proibe.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.billing_cycle_transitar() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.estado <> 'aberto' THEN
              RAISE EXCEPTION
                'billing_cycles: um ciclo nasce aberto, e nao %', NEW.estado
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.subscription_id IS DISTINCT FROM OLD.subscription_id
             OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.periodo IS DISTINCT FROM OLD.periodo
             OR NEW.valor_minor IS DISTINCT FROM OLD.valor_minor THEN
            RAISE EXCEPTION
              'billing_cycles: so o estado muda; o periodo e o valor de um ciclo '
              'sao os de quando abriu (KAM-059, criterio 6)'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.estado = OLD.estado THEN
            RETURN NEW;
          END IF;
          IF NOT (
               (OLD.estado = 'aberto'
                 AND NEW.estado IN ('cobranca_emitida', 'anulado'))
            OR (OLD.estado = 'cobranca_emitida'
                 AND NEW.estado IN ('em_atraso', 'anulado', 'paga'))
            OR (OLD.estado = 'em_atraso' AND NEW.estado IN ('anulado', 'paga'))
          ) THEN
            RAISE EXCEPTION
              'billing_cycles: nao ha aresta de % para %', OLD.estado, NEW.estado
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.estado = 'paga' AND NOT EXISTS (
               SELECT 1 FROM {COBRANCAS} c
                WHERE c.billing_cycle_id = NEW.id AND c.tenant_id = NEW.tenant_id
                  AND c.estado = 'paga') THEN
            RAISE EXCEPTION
              'billing_cycles: o ciclo % so fica paga com uma cobranca dele paga '
              'no ledger (evento autenticado ou confirmacao de ops com dupla '
              'aprovacao)', NEW.id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.billing_cycle_transitar() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER billing_cycles_transicao
          BEFORE INSERT OR UPDATE ON {CICLOS}
          FOR EACH ROW EXECUTE FUNCTION platform.billing_cycle_transitar()
        """
    )
    op.execute(f"ALTER TABLE {CICLOS} ENABLE ALWAYS TRIGGER billing_cycles_transicao")


def _ciclo_pago() -> None:
    """A cobranca do ciclo fica `paga` no ledger: o ciclo fica `paga` e emite-se.

    `AFTER UPDATE` sobre a `payment_charges`, que so a projeccao da
    `append_payment_event` actualiza — pelo que isto corre **dentro** da
    transaccao do pagamento, e o ciclo, o ledger e o evento confirmam juntos ou
    nao confirmam.

    O `UPDATE` do ciclo tem `estado IN ('cobranca_emitida', 'em_atraso')`, e e
    isso que da **um** `billing.cycle_paid` por ciclo: uma segunda cobranca do
    mesmo ciclo paga depois (tentativa 2) encontra o ciclo ja `paga` e nao
    emite. Esse segundo pagamento e dinheiro a devolver; abrir o caso e do
    KAM-060 (sinais) e de ops, e fica dito aqui.

    Corre como quem fez o `UPDATE` da cobranca — o dono, dentro da
    `append_payment_event` —, com o contexto do tenant que paga.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.billing_cycle_pagar() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_ciclo {CICLOS};
        BEGIN
          UPDATE {CICLOS} SET estado = 'paga'
           WHERE id = NEW.billing_cycle_id AND tenant_id = NEW.tenant_id
             AND estado IN ('cobranca_emitida', 'em_atraso')
          RETURNING * INTO v_ciclo;
          IF FOUND THEN
            PERFORM platform.evt_emitir(
              'billing.cycle_paid', 1::smallint, NEW.tenant_id, 'billing_cycle',
              v_ciclo.id::text,
              jsonb_build_object(
                'billing_cycle_id', v_ciclo.id,
                'subscription_id', v_ciclo.subscription_id,
                'charge_id', NEW.id,
                'periodo_inicio', lower(v_ciclo.periodo),
                'periodo_fim', upper(v_ciclo.periodo),
                'valor_minor', v_ciclo.valor_minor,
                'currency', NEW.currency));
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.billing_cycle_pagar() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER payment_charges_ciclo_pago
          AFTER UPDATE OF estado ON {COBRANCAS}
          FOR EACH ROW
          WHEN (NEW.billing_cycle_id IS NOT NULL AND NEW.estado = 'paga'
                AND OLD.estado IS DISTINCT FROM 'paga')
          EXECUTE FUNCTION platform.billing_cycle_pagar()
        """
    )
    op.execute(f"ALTER TABLE {COBRANCAS} ENABLE ALWAYS TRIGGER payment_charges_ciclo_pago")
    # **Uma cobranca nova so num ciclo vivo.** A revisao adversarial criou e
    # pagou uma tentativa 2 de um ciclo ja `paga` — dinheiro recebido duas vezes,
    # sem sinal nenhum. Num ciclo `paga` ou `anulado` nao ha nada a cobrar, e o
    # `INSERT` recusa. O que **nao** se recusa e o pagamento de uma cobranca que
    # ja existia quando o ciclo foi anulado: o dinheiro chegou, e o ledger regista
    # factos; cancelar a cobranca ao anular o ciclo e da regua (KAM-058).
    op.execute(
        f"""
        CREATE FUNCTION platform.billing_cobranca_de_ciclo_vivo() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF NOT EXISTS (
               SELECT 1 FROM {CICLOS} b
                WHERE b.id = NEW.billing_cycle_id AND b.tenant_id = NEW.tenant_id
                  AND b.estado IN ('aberto', 'cobranca_emitida', 'em_atraso')) THEN
            RAISE EXCEPTION
              'payment_charges: o ciclo % nao esta vivo (paga, anulado ou '
              'invisivel); nao ha nada a cobrar', NEW.billing_cycle_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.billing_cobranca_de_ciclo_vivo() FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE TRIGGER payment_charges_ciclo_vivo
          BEFORE INSERT ON {COBRANCAS}
          FOR EACH ROW WHEN (NEW.billing_cycle_id IS NOT NULL)
          EXECUTE FUNCTION platform.billing_cobranca_de_ciclo_vivo()
        """
    )
    op.execute(f"ALTER TABLE {COBRANCAS} ENABLE ALWAYS TRIGGER payment_charges_ciclo_vivo")


#: O `CREATE TRIGGER` do G8 da `0032`, **com** a condicao que esta revisao lhe
#: acrescenta. Escrito uma vez para o `upgrade`.
G8_SO_ENCOMENDA = """
        CREATE TRIGGER payment_events_g8_humano
          BEFORE INSERT ON platform.payment_events
          FOR EACH ROW WHEN (NEW.billing_cycle_id IS NULL)
          EXECUTE FUNCTION platform.exigir_fase_manual()
"""

#: E sem ela, para o `downgrade`: o da `0032`, que vale para todas as cobrancas.
G8_TODAS = """
        CREATE TRIGGER payment_events_g8_humano
          BEFORE INSERT ON platform.payment_events
          FOR EACH ROW EXECUTE FUNCTION platform.exigir_fase_manual()
"""


def _g8_das_cobrancas_de_ciclo() -> None:
    """O G8 da `0032` para as encomendas, e o de ops para os ciclos.

    Ver o cabecalho para a razao de **nao** se reescrever a funcao da `0032`.

    **As aprovacoes contam-se sem filtro de tenant, e nao e descuido.** O
    gatilho corre dentro da `append_payment_event`, como o dono, sob `FORCE` e
    com o `app.tenant_id` de quem paga: uma aprovacao escrita noutro tenant e
    **invisivel** aqui. A primeira versao filtrava por `tenant_id` tambem, e a
    revisao adversarial mostrou-o por mutacao: tirar o filtro nao mudava nada,
    porque a RLS ja fazia o trabalho. Um filtro que nenhum ensaio consegue
    morder e codigo que parece barreira e nao e.

    **E o ledger de um ciclo so se escreve pelo papel de billing.** A revisao
    adversarial mediu os dois buracos que o G8 de ops sozinho deixava: o
    `kamba_app` — o papel dos turnos do agente, no contexto da PME que **deve**
    — pagava o ciclo com um `pagamento_confirmado` `hmac` directo na porta do
    ledger, sem facilitador e sem ops; e o `kamba_pay`, com o `EXECUTE` que este
    ticket lhe da, escrevia no ledger de **encomendas** de qualquer tenant. O
    gatilho `payment_events_billing_papel` fecha os dois, pelo `session_user` —
    o papel que abriu a ligacao, que um `SECURITY DEFINER` nao troca: um evento
    de ciclo so entra numa ligacao do `kamba_pay`, e o `kamba_pay` so escreve
    eventos de ciclo. O que isto pressupoe, e fica dito: cada papel liga-se com
    a sua credencial (`db/ligacao.py`), sem `SET ROLE` a partir de um *pooler*.
    """
    op.execute("DROP TRIGGER payment_events_g8_humano ON platform.payment_events")
    op.execute(G8_SO_ENCOMENDA)
    op.execute(
        "ALTER TABLE platform.payment_events "
        "ENABLE ALWAYS TRIGGER payment_events_g8_humano"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.exigir_dupla_de_ops() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF NEW.tipo_evento <> 'pagamento_confirmado'
             OR NEW.authn_method <> 'manual' THEN
            RETURN NEW;
          END IF;
          IF NEW.actor_kind <> 'ops' THEN
            RAISE EXCEPTION
              'G8 (billing): a confirmacao manual de uma cobranca de ciclo e de '
              'ops, e nao de %; a PME e quem paga', NEW.actor_kind
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.motivo IS NULL OR btrim(NEW.motivo) = '' THEN
            RAISE EXCEPTION
              'G8 (billing): uma confirmacao de ops sem motivo nao entra no '
              'ledger (docs/tecnica/04 secao 9)'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NOT EXISTS (
               SELECT 1 FROM {APROVACOES} a
                WHERE a.charge_id = NEW.charge_id AND a.actor_id = NEW.actor_id
                  AND a.valor_minor = NEW.valor_minor)
             OR (SELECT count(DISTINCT a.actor_id) FROM {APROVACOES} a
                  WHERE a.charge_id = NEW.charge_id
                    AND a.valor_minor = NEW.valor_minor) < 2 THEN
            RAISE EXCEPTION
              'G8 (billing): a cobranca % so se confirma por ops com duas '
              'aprovacoes de pessoas distintas, uma delas a do actor %',
              NEW.charge_id, NEW.actor_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.exigir_dupla_de_ops() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER payment_events_g8_ops
          BEFORE INSERT ON platform.payment_events
          FOR EACH ROW WHEN (NEW.billing_cycle_id IS NOT NULL)
          EXECUTE FUNCTION platform.exigir_dupla_de_ops()
        """
    )
    op.execute(
        "ALTER TABLE platform.payment_events ENABLE ALWAYS TRIGGER payment_events_g8_ops"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.billing_papel_no_ledger() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          -- O superutilizador nao e um papel de aplicacao: pode tudo, incluindo
          -- largar este gatilho, e os ensaios que medem os `CHECK` do ledger
          -- sozinhos escrevem por ele. A guarda separa os papeis de aplicacao.
          IF (SELECT r.rolsuper FROM pg_catalog.pg_roles r
               WHERE r.rolname = session_user) THEN
            RETURN NEW;
          END IF;
          IF NEW.billing_cycle_id IS NOT NULL
             AND session_user::text <> '{PAPEL_DO_PAY}' THEN
            RAISE EXCEPTION
              'ledger: um evento da cobranca de um ciclo de billing so entra pelo '
              'papel de billing (%), e esta ligacao e de %; a PME que deve nao '
              'escreve o pagamento a KAMBA', '{PAPEL_DO_PAY}', session_user
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NEW.billing_cycle_id IS NULL
             AND session_user::text = '{PAPEL_DO_PAY}' THEN
            RAISE EXCEPTION
              'ledger: o papel de billing so escreve eventos de ciclos de billing, '
              'e a cobranca % e de uma encomenda', NEW.charge_id
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.billing_papel_no_ledger() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER payment_events_billing_papel
          BEFORE INSERT ON platform.payment_events
          FOR EACH ROW EXECUTE FUNCTION platform.billing_papel_no_ledger()
        """
    )
    op.execute(
        "ALTER TABLE platform.payment_events "
        "ENABLE ALWAYS TRIGGER payment_events_billing_papel"
    )
    # O caminho do dono fica fechado as cobrancas de ciclo.
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_so_encomenda() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF EXISTS (SELECT 1 FROM {COBRANCAS} c
                      WHERE c.id = NEW.charge_id
                        AND c.billing_cycle_id IS NOT NULL) THEN
            RAISE EXCEPTION
              'manual_confirmations: a cobranca % e de um ciclo de billing; a PME '
              'e quem paga, e a confirmacao e de ops (billing_confirmar_ops)',
              NEW.charge_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.manual_so_encomenda() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER manual_confirmations_so_encomenda
          BEFORE INSERT ON {CONFIRMACOES}
          FOR EACH ROW EXECUTE FUNCTION platform.manual_so_encomenda()
        """
    )
    op.execute(
        f"ALTER TABLE {CONFIRMACOES} "
        "ENABLE ALWAYS TRIGGER manual_confirmations_so_encomenda"
    )


def _confirmar_ops() -> None:
    """`billing_confirmar_ops`: uma aprovacao; a segunda, de outra pessoa, paga.

    **`SECURITY INVOKER`**, e nao por economia: corre como `kamba_pay`, que ve a
    cobranca do tenant em contexto e escreve a aprovacao pelo `INSERT` que tem.
    O que faz da regra uma regra e o `payment_events_g8_ops`, que vale para
    quem chegue ao ledger por outro caminho — esta funcao e a forma ordenada de
    la chegar, e nao a barreira.

    Serializa pelo **ciclo** (`FOR UPDATE`), e nao pela cobranca: o `kamba_pay`
    nao tem `UPDATE` em coluna nenhuma da `payment_charges`, e o
    `FOR UPDATE` exige-o. Duas aprovacoes simultaneas do mesmo ciclo passam uma
    de cada vez, e a segunda ve a primeira.

    Devolve `concluida` verdadeiro quando o pagamento entrou no ledger, e
    `repetida` quando a mesma pessoa ja tinha aprovado esta cobranca.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.billing_confirmar_ops(
          p_charge_id uuid, p_actor_id uuid, p_motivo text, p_valor_minor bigint)
        RETURNS TABLE (aprovacoes integer, concluida boolean, repetida boolean)
        LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge {COBRANCAS};
          v_ciclo  uuid;
          v_id     uuid;
          v_n      integer;
        BEGIN
          IF p_actor_id IS NULL OR p_motivo IS NULL OR btrim(p_motivo) = '' THEN
            RAISE EXCEPTION
              'billing_confirmar_ops: sem actor ou sem motivo nao ha aprovacao '
              'de ops (docs/tecnica/04 secao 9)'
              USING ERRCODE = 'check_violation';
          END IF;
          SELECT * INTO v_charge FROM {COBRANCAS} WHERE id = p_charge_id;
          IF NOT FOUND OR v_charge.billing_cycle_id IS NULL THEN
            RAISE EXCEPTION
              'billing_confirmar_ops: a cobranca % nao e de um ciclo de billing '
              'visivel no contexto desta transaccao', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;
          SELECT id INTO v_ciclo FROM {CICLOS}
           WHERE id = v_charge.billing_cycle_id FOR UPDATE;
          -- Relida depois da tranca: uma aprovacao concorrente pode te-la pago.
          SELECT * INTO v_charge FROM {COBRANCAS} WHERE id = p_charge_id;
          IF p_valor_minor IS DISTINCT FROM v_charge.amount_minor THEN
            RAISE EXCEPTION
              'billing_confirmar_ops: o valor aprovado (%) nao e o da cobranca '
              '(%)', p_valor_minor, v_charge.amount_minor
              USING ERRCODE = 'check_violation';
          END IF;
          SELECT count(DISTINCT actor_id) INTO v_n FROM {APROVACOES}
           WHERE charge_id = p_charge_id AND valor_minor = v_charge.amount_minor;
          IF v_charge.estado = 'paga' THEN
            -- Ja paga: nada a aprovar, e nada se escreve.
            RETURN QUERY SELECT v_n, true, true;
            RETURN;
          END IF;

          INSERT INTO {APROVACOES} (tenant_id, charge_id, actor_id, motivo, valor_minor)
            VALUES (v_charge.tenant_id, p_charge_id, p_actor_id, btrim(p_motivo),
                    p_valor_minor)
            ON CONFLICT (charge_id, actor_id) DO NOTHING
            RETURNING id INTO v_id;
          IF v_id IS NULL THEN
            -- A mesma pessoa outra vez nao e uma segunda aprovacao.
            RETURN QUERY SELECT v_n, false, true;
            RETURN;
          END IF;
          v_n := v_n + 1;
          IF v_n < 2 THEN
            RETURN QUERY SELECT v_n, false, false;
            RETURN;
          END IF;

          PERFORM 1 FROM platform.append_payment_event(
            p_charge_id => p_charge_id,
            p_tipo_evento => 'pagamento_confirmado',
            p_account_id => v_charge.account_id,
            p_valor_minor => p_valor_minor,
            p_authn_method => 'manual',
            p_authn_ok => true,
            p_decisao => 'aceite',
            p_motivo => btrim(p_motivo),
            p_actor_kind => 'ops',
            p_actor_id => p_actor_id);
          RETURN QUERY SELECT v_n, true, false;
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {CONFIRMAR_OPS} IS "
        "'Confirmacao de ops da cobranca de um ciclo de billing (KAM-059, "
        "criterio 5): motivo obrigatorio e duas pessoas distintas; a segunda "
        "aprovacao escreve o pagamento_confirmado manual com actor_kind ops. "
        "SECURITY INVOKER; a barreira e o trigger payment_events_g8_ops.'"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {CONFIRMAR_OPS} FROM PUBLIC")


def _rls() -> None:
    """`tenant_iso` nas quatro tabelas de tenant, e as duas politicas do PAY.

    O `price_book` nao tem tenant e nao leva RLS (ver o `_precario`).
    """
    for tabela in (
        "subscriptions",
        "billing_cycles",
        "commission_accruals",
        "billing_ops_approvals",
    ):
        rls.enable_tenant_rls(tabela)
    op.execute(
        f"""
        CREATE POLICY pay_receita_propria ON {CONTAS}
          FOR SELECT TO {PAPEL_DO_PAY}
          USING (beneficiary_kind = 'plataforma_receita_propria')
        """
    )
    op.execute(
        f"""
        CREATE POLICY pay_billing_subscricoes ON {SUBSCRICOES}
          FOR SELECT TO {PAPEL_DO_PAY}
          USING (true)
        """
    )


def _privilegios() -> None:
    """O que cada papel pode, tabela a tabela.

    `kamba_pay` (o billing): le o precario e as subscricoes, abre ciclos e
    cobrancas, muda o estado do ciclo (o grafo e do *trigger*), escreve
    aprovacoes de ops e a sombra, chama a porta do ledger. Na `payment_accounts`
    so as cinco colunas de que o `assert_beneficiary` e o *job* precisam.

    `kamba_batch`: escreve o precario e as subscricoes (e quem muda o plano, com
    os `entitlements`, que ja so ele escreve desde a `0007`) e apaga o que o
    semeador das baterias de isolamento semeou. `kamba_app` e `kamba_audit`
    leem as tabelas de tenant, sob a `tenant_iso`.
    """
    for tabela in (SUBSCRICOES, CICLOS, ACCRUALS, APROVACOES):
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DA_APP}")
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT ON {PRECARIO} TO {PAPEL_DE_AUDITORIA}")

    op.execute(f"GRANT SELECT, INSERT ON {PRECARIO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SUBSCRICOES} TO {PAPEL_DE_LOTE}")
    for tabela in (CICLOS, ACCRUALS, APROVACOES):
        op.execute(f"GRANT SELECT, DELETE ON {tabela} TO {PAPEL_DE_LOTE}")

    op.execute(f"GRANT SELECT ON {PRECARIO} TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT SELECT ON {SUBSCRICOES} TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT SELECT, INSERT ON {CICLOS} TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT UPDATE (estado) ON {CICLOS} TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT SELECT, INSERT ON {ACCRUALS} TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT SELECT, INSERT ON {APROVACOES} TO {PAPEL_DO_PAY}")
    # **Sem `order_id`**: o papel de billing so cria cobrancas de ciclo. Com o
    # `INSERT` de tabela, criava uma cobranca de encomenda na conta de uma PME
    # de qualquer tenant (achado da revisao adversarial).
    op.execute(f"GRANT SELECT ON {COBRANCAS} TO {PAPEL_DO_PAY}")
    op.execute(
        f"GRANT INSERT ({COLUNAS_DA_COBRANCA_DE_CICLO}) ON {COBRANCAS} TO {PAPEL_DO_PAY}"
    )
    op.execute(f"GRANT SELECT ON {EVENTOS} TO {PAPEL_DO_PAY}")
    op.execute(
        f"GRANT SELECT (id, beneficiary_kind, tenant_id, provider, estado) "
        f"ON {CONTAS} TO {PAPEL_DO_PAY}"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.append_payment_event("
        "uuid, text, uuid, bigint, text, boolean, text, text, text, uuid, text, "
        f"jsonb, timestamptz) TO {PAPEL_DO_PAY}"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {CONFIRMAR_OPS} TO {PAPEL_DO_PAY}")
    op.execute(
        f"COMMENT ON FUNCTION platform.assert_beneficiary() IS '{COMENTARIO_G1}'"
    )


def downgrade() -> None:
    """O inverso, com uma recusa: um ciclo com cobranca nao se perde.

    A `payment_charges` e o ledger nao se apagam, e uma cobranca de ciclo
    aponta para ele pela `charges_billing_fk`. Com uma cobranca dessas, largar a
    `billing_cycles` deixava o `billing_cycle_id` do ledger sem o ciclo a que
    pertence. **A contagem corre com o `FORCE` desligado**, pela licao do
    KAM-050: a ligacao do Alembic e dona da tabela, e sob `FORCE` sem contexto
    um `count(*)` le zero.
    """
    op.execute(f"ALTER TABLE {COBRANCAS} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $guarda$
        BEGIN
          IF EXISTS (SELECT 1 FROM {COBRANCAS} WHERE billing_cycle_id IS NOT NULL) THEN
            RAISE EXCEPTION
              'downgrade do billing recusado: ha cobrancas de ciclos de billing, e '
              'largar a billing_cycles deixava o ledger sem o ciclo (KAM-059)'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
        END $guarda$
        """
    )
    op.execute(f"ALTER TABLE {COBRANCAS} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"COMMENT ON FUNCTION platform.assert_beneficiary() IS '{COMENTARIO_G1_0027}'"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {CONFIRMAR_OPS} FROM {PAPEL_DO_PAY}")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION platform.append_payment_event("
        "uuid, text, uuid, bigint, text, boolean, text, text, text, uuid, text, "
        f"jsonb, timestamptz) FROM {PAPEL_DO_PAY}"
    )
    op.execute(
        f"REVOKE SELECT (id, beneficiary_kind, tenant_id, provider, estado) "
        f"ON {CONTAS} FROM {PAPEL_DO_PAY}"
    )
    op.execute(f"REVOKE ALL ON {EVENTOS} FROM {PAPEL_DO_PAY}")
    op.execute(
        f"REVOKE INSERT ({COLUNAS_DA_COBRANCA_DE_CICLO}) ON {COBRANCAS} FROM {PAPEL_DO_PAY}"
    )
    op.execute(f"REVOKE ALL ON {COBRANCAS} FROM {PAPEL_DO_PAY}")
    op.execute(f"DROP FUNCTION {CONFIRMAR_OPS}")

    op.execute(
        f"DROP TRIGGER manual_confirmations_so_encomenda ON {CONFIRMACOES}"
    )
    op.execute("DROP FUNCTION platform.manual_so_encomenda()")
    op.execute("DROP TRIGGER payment_events_billing_papel ON platform.payment_events")
    op.execute("DROP FUNCTION platform.billing_papel_no_ledger()")
    op.execute("DROP TRIGGER payment_events_g8_ops ON platform.payment_events")
    op.execute("DROP FUNCTION platform.exigir_dupla_de_ops()")
    op.execute("DROP TRIGGER payment_events_g8_humano ON platform.payment_events")
    op.execute(G8_TODAS)
    op.execute(
        "ALTER TABLE platform.payment_events "
        "ENABLE ALWAYS TRIGGER payment_events_g8_humano"
    )

    op.execute(f"DROP TRIGGER payment_charges_ciclo_vivo ON {COBRANCAS}")
    op.execute("DROP FUNCTION platform.billing_cobranca_de_ciclo_vivo()")
    op.execute(f"DROP TRIGGER payment_charges_ciclo_pago ON {COBRANCAS}")
    op.execute("DROP FUNCTION platform.billing_cycle_pagar()")
    op.execute(f"ALTER TABLE {COBRANCAS} DROP CONSTRAINT charges_billing_fk")

    op.execute(f"DROP POLICY pay_billing_subscricoes ON {SUBSCRICOES}")
    op.execute(f"DROP POLICY pay_receita_propria ON {CONTAS}")
    for tabela in (
        "billing_ops_approvals",
        "commission_accruals",
        "billing_cycles",
        "subscriptions",
    ):
        rls.disable_tenant_rls(tabela)

    # As funcoes de *trigger* caem com as tabelas? Nao: caem os *triggers*, e
    # as funcoes ficam. Por isso largam-se a seguir, cada uma depois da sua.
    op.execute(f"DROP TABLE {APROVACOES}")
    op.execute(f"DROP TABLE {ACCRUALS}")
    op.execute("DROP FUNCTION platform.commission_accrual_verificar()")
    op.execute(f"DROP TABLE {CICLOS}")
    op.execute("DROP FUNCTION platform.billing_cycle_transitar()")
    op.execute(f"DROP TABLE {SUBSCRICOES}")
    op.execute(f"DROP TABLE {PRECARIO}")
    op.execute("DROP FUNCTION platform.price_book_auditar()")

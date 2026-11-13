"""O PAY abre a refund_cases ao consumir order.refund_requested (KAM-197).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## A decisao que esta revisao executa

O fundador decidiu a 2026-11-12, opcao (b): **o PAY abre o caso de reembolso ao
consumir `order.refund_requested`, com o papel dele, e a tabela tem um so
dono.** O COM emite o pedido (regras 3 e 4 do KAM-050, e as tres arestas para
`reembolso_pendente`) e nao ganha escritor na `refund_cases`.

Ate aqui a `refund_cases` tinha **um** escritor, a `manual_reverter` da `0032`,
que abre o caso **dentro** de uma reversao no *ledger*. Esta revisao acrescenta o
segundo, e e outro caminho e nao uma copia: o caso abre-se **sem reversao no
ledger** — nenhuma linha nova em `payment_events`, nenhuma cobranca muda de
estado. O dinheiro entrou e nao sai pela plataforma (ADR-004); quem o devolve e
a PME a partir da conta dela, e o caso e o registo disso
(`docs/tecnica/04` §6.3).

## Tres coisas, e porque sao tres

1. **A porta `abrir_caso_de_reembolso`**, `SECURITY DEFINER`, com `EXECUTE` so
   ao papel do consumidor do PAY, o `kamba_pay` (decisao (A) do fundador de
   2026-11-13; o papel nasce no `db/bootstrap.py`, e esta revisao concede-lhe o
   que consumir pede). A tabela continua **sem `INSERT`** para papel
   nenhum — a razao da `0032` («com `INSERT`, abria-se um caso de reembolso sem
   reversao e sem evento no ledger») vale para um `INSERT` concedido, que nao
   tem barreira nenhuma; a porta tem quatro, abaixo.
2. **A coluna `pedido_evento_id` e o indice unico parcial** que fazem a
   idempotencia ser uma propriedade da base e nao do consumidor. O consumo ja
   deduplica pelo recibo de `events_consumed`; isto e a segunda barreira, e e a
   que vale para quem chamar a porta fora do consumo.
3. **Duas linhas na `payment_outbox_map`**: o `pagamento_duplicado` pelos dois
   caminhos autenticados do facilitador (`hmac` e `consulta`) passa a emitir
   `payment.confirmed`, que e o evento que a regra 4 do KAM-050 le. Sem elas, o
   segundo pagamento da **mesma** cobranca nunca chegava ao COM (divida 211).

## As quatro barreiras da porta

    motivo      lista fechada dos quatro `MotivoDeReembolso` do dicionario
                §3.60. A coluna `refund_cases.motivo` e `text NOT NULL` sem
                `CHECK` — a `manual_reverter` escreve nela o texto livre de ops —,
                pelo que e aqui que o dominio do pedido se fecha.
    encomenda   a encomenda tem de existir **no tenant da transaccao**: lida sob
                RLS, porque o `DEFINER` da privilegio e nao da isolamento (a nota
                da `0039`). A FK composta da `0035` garante o mesmo por outra via.
    moeda       a do pedido tem de ser a da encomenda. A `refund_cases` nao tem
                coluna de moeda, e um `valor_minor` sem moeda so e dinheiro se a
                moeda for a da encomenda a que o caso pertence.
    repeticao   o mesmo `pedido_evento_id` devolve o caso que ja existe; e, se o
                conteudo divergir do que se gravou, **recusa** — uma repeticao
                que diz outra coisa nao e uma repeticao.

## O que fica de fora, e de proposito

* **O `charge_id` fica nulo.** O `order.refund_requested` nao o traz, e uma
  encomenda pode ter mais do que uma cobranca (a regra 4 tambem dispara pela
  segunda cobranca de uma encomenda ja paga). Escolher uma por heuristica era
  pr a porta a afirmar o que o evento nao disse. O `refund_cases_um_sujeito` e
  inclusivo, pelo que o `order_id` basta.
* **O `(pagamento_duplicado, manual)` nao se mapeia.** A `manual_confirmar` nao
  confirma uma cobranca ja `paga`, pelo que nao ha caminho que o escreva; e o
  `sistema` nunca autentica pagamento nenhum (o `confirmar_exige_autenticacao`
  da `0029`).
* **Um reentregue nao e um duplo.** O F-01 (o facilitador reentrega o mesmo
  callback) e absorvido pelo G7 **antes** do ledger — o `prescricaoDosGates`
  devolve `[]` para o veredicto `duplicado` —, e o `pagamento_duplicado` so se
  escreve no F-08, que e o segundo pagamento autenticado. Mapear o tipo nao faz
  uma reentrega pedir reembolso.
"""

from __future__ import annotations

from alembic import op

revision = "0050"
#: **Provisorio.** A cabeca da `publico/main` e a `0049` (KAM-062), medido com
#: `git ls-tree --name-only refs/remotes/publico/main db/migrations/versions/`.
#: O lote tem mais tres revisoes abertas (`0051` a `0053`), e o numero final
#: da-o quem integra, pela regra da casa: um ramo nao reserva a linha para outro.
down_revision = "0049"
branch_labels = None
depends_on = None

REEMBOLSOS = "platform.refund_cases"
ENCOMENDAS = "platform.orders_mirror"
MAPA = "platform.payment_outbox_map"

#: O papel que corre o consumidor do PAY e e o unico com `EXECUTE` na porta.
#:
#: **Um papel proprio, e nao o `kamba_app`**, por decisao (A) do fundador de
#: 2026-11-13. O COM corre como `kamba_app`; com a porta concedida a ele, «o COM
#: nao escreve na `refund_cases`» era uma convencao, e com ela concedida so a
#: este papel e uma recusa da base (`42501`), medida no
#: `test_o_papel_do_com_nao_abre_caso_pela_porta`. **O papel nasce no
#: `db/bootstrap.py`** e nao aqui, como os outros oito: o Alembic corre como
#: `kamba_migrator`, que nao tem `CREATEROLE`. Esta revisao da-lhe o que ele
#: pode, e o `downgrade` tira-lho.
PAPEL_DO_PAY = "kamba_pay"

COLUNA = "pedido_evento_id"
INDICE = "refund_cases_pedido_uq"

#: A assinatura, para o `COMMENT`, o `GRANT` e o `DROP`. Escrita uma vez, pela
#: licao do KAM-175: um nome repetido em tres instrucoes desvia-se numa delas.
ASSINATURA = (
    "platform.abrir_caso_de_reembolso(uuid, uuid, text, bigint, text, uuid)"
)

#: Os quatro motivos de um pedido de reembolso, dicionario §3.60 e `enum` do
#: `contratos/eventos/order.refund_requested/v1.schema.json`. Repetidos aqui e
#: nao lidos do contrato, pela razao da `0039`: uma revisao nao depende de um
#: ficheiro que ninguem revia ao mesmo tempo. O confronto com o contrato e o
#: `test_os_motivos_da_porta_sao_os_do_contrato`.
MOTIVOS = (
    "'pagamento_apos_cancelamento'",
    "'pagamento_duplicado'",
    "'disputa'",
    "'entrega_falhada'",
)


def upgrade() -> None:
    _coluna()
    _porta()
    _privilegios()
    _mapa()


def downgrade() -> None:
    """O inverso, com uma recusa: um caso aberto por esta porta nao se perde.

    A `refund_cases` e o registo de um processo que corre fora da plataforma, e
    tirar-lhe a coluna apagava a ligacao entre o caso e o pedido que o abriu. Com
    um caso desses na tabela, o `downgrade` recusa-se.

    **A contagem corre com o `FORCE` desligado**, pela licao do KAM-050 (`0046`):
    a ligacao do Alembic e dona da tabela, o `FORCE` sujeita-a a `tenant_iso`, e
    sem `app.tenant_id` um `count(*)` le **zero** — a guarda passava sempre. O
    `NO FORCE` e o `FORCE` ficam na transaccao da migracao.
    """
    op.execute(f"ALTER TABLE {REEMBOLSOS} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $guarda$
        BEGIN
          IF EXISTS (SELECT 1 FROM {REEMBOLSOS} WHERE {COLUNA} IS NOT NULL) THEN
            RAISE EXCEPTION
              'downgrade da 0050 recusado: ha casos de reembolso abertos pelo '
              'consumidor do PAY, e tirar a coluna {COLUNA} apagava a ligacao '
              'ao pedido que os abriu (KAM-197)'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
        END $guarda$
        """
    )
    op.execute(f"ALTER TABLE {REEMBOLSOS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DELETE FROM {MAPA} WHERE tipo_evento = 'pagamento_duplicado'"
    )
    op.execute(f"DROP FUNCTION {ASSINATURA}")
    _sem_privilegios()
    op.execute(f"DROP INDEX platform.{INDICE}")
    op.execute(f"ALTER TABLE {REEMBOLSOS} DROP COLUMN {COLUNA}")


def _coluna() -> None:
    """`pedido_evento_id`: o `id` do envelope do pedido que abriu o caso.

    Anulavel, porque os casos da `manual_reverter` nao vem de pedido nenhum. O
    indice e **parcial** pela mesma razao, e e **com** o `tenant_id`: o `id` de
    um envelope e um UUIDv7 global, mas uma unicidade sem o tenant deixava um
    tenant saber, por um `23505`, que o `id` existia noutro.
    """
    op.execute(f"ALTER TABLE {REEMBOLSOS} ADD COLUMN {COLUNA} uuid")
    op.execute(
        f"CREATE UNIQUE INDEX {INDICE} ON {REEMBOLSOS} (tenant_id, {COLUNA}) "
        f"WHERE {COLUNA} IS NOT NULL"
    )
    op.execute(
        f"COMMENT ON COLUMN {REEMBOLSOS}.{COLUNA} IS "
        "'O id do envelope order.refund_requested que abriu o caso (KAM-197). "
        "Nulo nos casos da manual_reverter, que nao vem de pedido nenhum. O "
        "indice unico parcial refund_cases_pedido_uq torna a abertura idempotente "
        "na base, e nao so no consumo.'"
    )


def _porta() -> None:
    """A porta, com as quatro barreiras do cabecalho.

    O `SET search_path = pg_catalog, platform` e **sem `public`**, pela razao da
    `0029`: num `SECURITY DEFINER`, um schema onde o chamador crie objectos
    deixava-o sombrear uma funcao que este corpo chama.

    **Nao toca no ledger nem na cobranca.** Nao ha `append_payment_event` aqui,
    e o `test_o_caso_abre_sem_linha_nova_no_ledger` prende-o pela contagem.
    """
    motivos = ", ".join(MOTIVOS)
    op.execute(
        f"""
        CREATE FUNCTION platform.abrir_caso_de_reembolso(
            p_tenant_id        uuid,
            p_order_id         uuid,
            p_motivo           text,
            p_valor_minor      bigint,
            p_currency         text,
            p_pedido_evento_id uuid)
          RETURNS uuid
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_moeda text;
          v_caso  uuid;
          v_antes {REEMBOLSOS};
        BEGIN
          -- (1) O motivo, contra a lista fechada do contrato.
          IF p_motivo IS NULL OR p_motivo NOT IN ({motivos}) THEN
            RAISE EXCEPTION
              'abrir_caso_de_reembolso: o motivo % nao e um dos quatro do '
              'order.refund_requested', p_motivo
              USING ERRCODE = 'check_violation';
          END IF;
          IF p_pedido_evento_id IS NULL THEN
            RAISE EXCEPTION
              'abrir_caso_de_reembolso: sem pedido_evento_id nao ha '
              'idempotencia, e a porta so abre casos a partir de um pedido'
              USING ERRCODE = 'check_violation';
          END IF;

          -- (2) A encomenda, no tenant da transaccao. Lida sob RLS: o `FORCE`
          -- vincula o dono, pelo que outro tenant nao a encontra.
          SELECT o.currency INTO v_moeda FROM {ENCOMENDAS} o
           WHERE o.tenant_id = p_tenant_id AND o.id = p_order_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'abrir_caso_de_reembolso: a encomenda % nao existe ou nao e '
              'visivel no contexto desta transaccao (RLS)', p_order_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- (3) A moeda do pedido e a da encomenda.
          IF p_currency IS DISTINCT FROM v_moeda THEN
            RAISE EXCEPTION
              'abrir_caso_de_reembolso: o pedido vem em % e a encomenda % e em '
              '%; um valor_minor sem a moeda certa nao e dinheiro',
              p_currency, p_order_id, v_moeda
              USING ERRCODE = 'check_violation';
          END IF;

          -- (4) A repeticao. `ON CONFLICT DO NOTHING` e nao um `SELECT` antes:
          -- duas entregas concorrentes do mesmo pedido passavam as duas pelo
          -- `SELECT` e a segunda levava `23505`.
          INSERT INTO {REEMBOLSOS} (
              tenant_id, order_id, motivo, valor_minor, estado,
              {COLUNA})
            VALUES (
              p_tenant_id, p_order_id, p_motivo, p_valor_minor, 'aberto',
              p_pedido_evento_id)
            ON CONFLICT (tenant_id, {COLUNA}) WHERE {COLUNA} IS NOT NULL
            DO NOTHING
            RETURNING id INTO v_caso;
          IF v_caso IS NOT NULL THEN
            RETURN v_caso;
          END IF;

          SELECT * INTO v_antes FROM {REEMBOLSOS} r
           WHERE r.tenant_id = p_tenant_id
             AND r.{COLUNA} = p_pedido_evento_id;
          IF v_antes.order_id IS DISTINCT FROM p_order_id
             OR v_antes.motivo IS DISTINCT FROM p_motivo
             OR v_antes.valor_minor IS DISTINCT FROM p_valor_minor THEN
            RAISE EXCEPTION
              'abrir_caso_de_reembolso: o pedido % ja abriu o caso % com outro '
              'conteudo; uma repeticao que diverge nao e uma repeticao',
              p_pedido_evento_id, v_antes.id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN v_antes.id;
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {ASSINATURA} IS "
        "'Abre o caso de reembolso a partir de um order.refund_requested "
        "(KAM-197, decisao (b) do fundador de 2026-11-12): sem reversao no "
        "ledger e sem tocar na cobranca. Quatro barreiras: o motivo contra a "
        "lista fechada do contrato, a encomenda no tenant da transaccao, a moeda "
        "da encomenda, e a repeticao do mesmo pedido a devolver o caso que ja "
        "existe (ou a recusar, se o conteudo divergir). O outro escritor da "
        "tabela e a platform.manual_reverter.'"
    )


def _privilegios() -> None:
    """O que o papel do PAY pode: consumir, e abrir o caso pela porta.

    O `REVOKE ALL ... FROM PUBLIC` primeiro, pela razao da `0029`: uma funcao
    nasce com `EXECUTE` para `PUBLIC`, e sem este passo o `kamba_app` chamava-a.

    Consumir pede tres tabelas e mais nenhuma, que sao as do `kamba_app`
    consumidor da `0004` e da `0005`: o envelope no `events_log` (o
    `SQL_ENVELOPE_DO_EVENTO` do trabalhador), o recibo em `events_consumed` e a
    DLQ — esta com `INSERT` de tabela e `SELECT` so das tres colunas que o
    `ON CONFLICT` do `paraDlq()` pede, pela razao escrita na `0005` (o `id` e
    sequencial e revelava o volume do vizinho). **Nenhum privilegio na
    `refund_cases`**: a porta e o caminho, e e a porta que tem as barreiras.
    """
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {PAPEL_DO_PAY}")
    op.execute(f"GRANT SELECT ON platform.events_log TO {PAPEL_DO_PAY}")
    op.execute(
        f"GRANT SELECT, INSERT ON platform.events_consumed TO {PAPEL_DO_PAY}"
    )
    op.execute(f"GRANT INSERT ON platform.events_dlq TO {PAPEL_DO_PAY}")
    op.execute(
        "GRANT SELECT (consumer, event_id, estado) ON platform.events_dlq TO "
        f"{PAPEL_DO_PAY}"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {ASSINATURA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ASSINATURA} TO {PAPEL_DO_PAY}")


def _sem_privilegios() -> None:
    """O inverso do `_privilegios`, para o `downgrade`.

    O papel **fica**: nasce no `db/bootstrap.py`, como o `kamba_pay_hooks` da
    `0029`, e uma revisao nao apaga o que nao criou. Fica sem nada, que e o
    estado de um papel que nenhuma revisao alcanca.
    """
    op.execute(
        "REVOKE SELECT (consumer, event_id, estado) ON platform.events_dlq FROM "
        f"{PAPEL_DO_PAY}"
    )
    op.execute(f"REVOKE ALL ON platform.events_dlq FROM {PAPEL_DO_PAY}")
    op.execute(f"REVOKE ALL ON platform.events_consumed FROM {PAPEL_DO_PAY}")
    op.execute(f"REVOKE ALL ON platform.events_log FROM {PAPEL_DO_PAY}")
    op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {PAPEL_DO_PAY}")


def _mapa() -> None:
    """O `pagamento_duplicado` pelos dois caminhos autenticados do facilitador.

    `payment.confirmed` e nao um evento novo: e o que a regra 4 do KAM-050 le
    («segundo pagamento autenticado na mesma encomenda»), e o `ramoDoPagamento`
    do COM decide pelo estado da encomenda — paga ou adiante, e `duplicado`.
    A `payment_evt_payload` da `0035` recusa um `payment.confirmed` sem
    `authn_ok`, pelo que um duplicado nao autenticado continua sem evento.
    """
    op.execute(
        f"INSERT INTO {MAPA} (tipo_evento, authn_method, evt_tipo, evt_versao) "
        "VALUES ('pagamento_duplicado', 'hmac', 'payment.confirmed', 1), "
        "('pagamento_duplicado', 'consulta', 'payment.confirmed', 1)"
    )

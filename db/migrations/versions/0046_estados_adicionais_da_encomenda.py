"""Estados adicionais da encomenda: pagamento tardio, disputa, entrega falhada,
reembolso (KAM-050). Fase *expand* de *expand -> migrate -> contract*.

Revisao **aditiva**: nao apaga coluna, tabela nem linha. O que faz, por ordem:

1. **Nove arestas** novas na `platform.order_state_graph` (o KAM-044 deixou-a
   com as doze do nucleo e escreveu que o resto era deste ticket). Sao as oito
   do criterio 1 mais a `em_entrega -> entrega_falhada` do `docs/tecnica/00`
   §6.1: sem ela, as duas arestas que **saem** de `entrega_falhada` eram linhas
   mortas, porque nenhuma la chegava. As tres que tocam `entrega_falhada` ficam
   atras de `COM_DELIVERY_ENABLED` (criterio 6); activar a bandeira continua a
   nao exigir migracao, porque a bandeira e a variavel de sessao e nao a linha.
2. **O `orders_mirror_excepcao_ck` ganha `pagamento_apos_cancelamento`**, a
   regra 3 do `docs/tecnica/03` §6.6. As tres da `0030` sao as do §5.4, e
   nenhuma descreve um pagamento sobre uma encomenda `cancelada`.
3. **O `audit_log_action` ganha `order.refund_record`**: o criterio 5 pede
   `audit_log` no registo do reembolso, e o dominio fechado da `0006` (estendido
   pela `0038` e pela `0042`) nao tem accao que o descreva. O dicionario §3.2 autoriza a
   extensao por migracao, como a `0038` fez.
4. **O `order_estado_exige_log` passa a exigir, para `reembolsada`, um actor
   `dono` ou `ops` com `actor_id`** (criterio 5), com o mesmo `KA006` do `paga`.
   E `CREATE OR REPLACE` do corpo da `0030`, que fica **igual** em tudo o resto:
   o corpo da `0030` esta copiado abaixo a letra, e o ramo novo e um fragmento.
5. **A `stock_reservations_linha_uq` passa a indice unico parcial**
   (`WHERE estado <> 'libertada'`). A regra 1 do §6.6 manda re-reservar uma
   encomenda `expirada`, e as linhas dela ja tem reserva `libertada`: com a
   unicidade total, a segunda reserva da mesma linha era `23505`. A unicidade
   que importa — uma reserva **viva** por linha — fica; a que impedia
   re-reservar uma linha libertada sai. O `expirada -> aguarda_pagamento` do
   nucleo tinha o mesmo bloqueio, e deixa de o ter.

## O que **nao** faz

**Nao escreve na `refund_cases`, nem lhe da escritor.** Abrir um caso de
reembolso sem reversao no *ledger* e a decisao que a `0039` devolveu ao
fundador; as regras 3 e 4 ficam com a excepcao e o evento.

## O `downgrade` e aditivo, e recusa em vez de apagar

Desfaz os cinco passos pela ordem inversa. Tres deles nao se desfazem sobre
dados que dependam deles, e o `downgrade` **recusa** com a razao em vez de os
apagar: uma encomenda com a quarta excepcao, uma linha de `audit_log` com a
accao nova (o registo e *append-only*, ninguem tem `DELETE`), e uma linha de
encomenda com duas reservas. As arestas saem sem recusa: uma encomenda num
estado novo fica nele, sem saida pelo grafo, que e o estado certo para uma fase
*contract* que ainda nao correu.
"""

from __future__ import annotations

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

ENCOMENDAS = "platform.orders_mirror"
GRAFO = "platform.order_state_graph"
RESERVAS = "platform.stock_reservations"
AUDIT_LOG = "platform.audit_log"

#: As nove arestas, com a bandeira de cada uma. Texto de `VALUES`, como o
#: `NUCLEO` da `0030`, pela razao escrita la (o *gate* 3b segue
#: `", ".join(<constante de modulo>)`).
ADICIONAIS = (
    "('expirada', 'paga', NULL)",
    "('paga', 'reembolso_pendente', NULL)",
    "('entregue', 'em_disputa', NULL)",
    "('em_disputa', 'reembolso_pendente', NULL)",
    "('em_disputa', 'entregue', NULL)",
    "('em_entrega', 'entrega_falhada', 'COM_DELIVERY_ENABLED')",
    "('entrega_falhada', 'em_entrega', 'COM_DELIVERY_ENABLED')",
    "('entrega_falhada', 'reembolso_pendente', 'COM_DELIVERY_ENABLED')",
    "('reembolso_pendente', 'reembolsada', NULL)",
)

#: Os pares `(de, para)` das nove, para o `DELETE` do `downgrade`.
PARES_ADICIONAIS = (
    "('expirada', 'paga')",
    "('paga', 'reembolso_pendente')",
    "('entregue', 'em_disputa')",
    "('em_disputa', 'reembolso_pendente')",
    "('em_disputa', 'entregue')",
    "('em_entrega', 'entrega_falhada')",
    "('entrega_falhada', 'em_entrega')",
    "('entrega_falhada', 'reembolso_pendente')",
    "('reembolso_pendente', 'reembolsada')",
)

#: As **quatro** excepcoes depois desta revisao, e as tres da `0030`, que o
#: `downgrade` repoe. Copiadas e nao importadas, pela razao da `0038`.
EXCEPCOES = (
    "'pagamento_tardio_sem_stock'",
    "'pagamento_duplicado'",
    "'valor_divergente'",
    "'pagamento_apos_cancelamento'",
)
EXCEPCOES_DA_0030 = (
    "'pagamento_tardio_sem_stock'",
    "'pagamento_duplicado'",
    "'valor_divergente'",
)
EXCEPCAO_NOVA = "pagamento_apos_cancelamento"
RESTRICAO_DA_EXCEPCAO = "orders_mirror_excepcao_ck"

#: O dominio de `audit_log.action` depois desta revisao, e o da `0042`, que o
#: `downgrade` repoe. Por extenso, pela razao escrita na `0006`.
#:
#: **Parte do dominio da revisao anterior, e nao da `0038`**: a `0042` (KAM-071)
#: acrescentou as duas do *hold* legal, e uma revisao que reescrevesse o `CHECK`
#: a partir da `0038` apagava-as — o `upgrade` falhava com `23514` sobre linhas
#: de *hold* escritas, ou passava e recusava todo o *hold* seguinte. Apanhado
#: pela revisao adversarial do KAM-050. A `0043`, a `0044` e a `0045`, que
#: ficam entre as duas, **nao** mexem no dominio (lido na integracao), pelo que
#: o da `0042` e o da revisao anterior.
LITERAIS_DE_ACCAO_0046 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record'"
)
LITERAIS_DE_ACCAO_0042 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado'"
)
ACCAO_NOVA = "order.refund_record"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: A unicidade da `0033` e o indice que a substitui.
UNICIDADE_DA_0033 = "stock_reservations_linha_uq"
INDICE_DA_LINHA_VIVA = "stock_reservations_linha_viva_uq"

#: As constantes que o corpo da `0030` usa, com os valores da `0030`.
PAGA = "'paga'"
CAUSAS_QUE_PAGAM = ("'payment.confirmed'", "'payment.manual_confirmed'")
SQLSTATE_REGISTO = "KA005"
SQLSTATE_AUTENTICIDADE = "KA006"

#: O ramo que esta revisao acrescenta ao corpo da `0030`, antes do ultimo
#: `RETURN NULL`. O `actor_id` e exigido alem do `actor_kind`: «dono» sem quem
#: e um registo que nao se consegue atribuir a ninguem.
#:
#: **Literal, e nao uma *f-string*:** o *gate* 3b le o que o `_funcao` executa
#: substituindo o argumento pelo valor desta constante, e so resolve constantes
#: que sao texto. Os valores sao o `REEMBOLSADA` e os `ACTORES_DO_REEMBOLSO` do
#: `services/com/src/orders/graph_ext.ts` e o `SQLSTATE_AUTENTICIDADE` acima, e
#: o `TestReembolsadaSoPorDonoOuOps` mede o ramo na base.
RAMO_DO_REEMBOLSO = """
          -- KAM-050, criterio 5: `reembolsada` so por registo manual de um dono
          -- ou de ops **identificado**. A linha de `audit_log` e escrita pelo
          -- modulo na mesma transaccao; esta funcao nao a pode ler (o
          -- `kamba_app` nao tem `SELECT` no `audit_log`), e por isso a barreira
          -- da base e o actor, e a do rasto e o modulo.
          IF NEW.estado = 'reembolsada' THEN
            IF v_log.actor_kind NOT IN ('dono', 'ops')
               OR v_log.actor_id IS NULL
               OR btrim(v_log.actor_id) = '' THEN
              RAISE EXCEPTION
                'orders_mirror: reembolsada exige registo manual de dono ou '
                'ops identificado, e veio actor=% id=% (criterio 5 do KAM-050, '
                'ADR-004)',
                v_log.actor_kind, v_log.actor_id
                USING ERRCODE = 'KA006';
            END IF;
          END IF;
"""

#: O ramo vazio: a versao da `0030`, que o `downgrade` repoe.
SEM_RAMO = ""


def _funcao(ramo: str) -> None:
    """O `order_estado_exige_log`, com o ramo que lhe derem.

    O corpo e copia **literal** da `0030`, e so o ramo antes do ultimo
    `RETURN NULL` e parametro — o mesmo padrao do `_porta(passo_sete)` da
    `0035`: as duas versoes sao identicas por construcao em tudo o resto, e o
    `downgrade` repoe a da `0030` porque e a mesma cadeia com o ramo vazio.
    """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION platform.order_estado_exige_log() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE v_log platform.order_state_log;
        BEGIN
          IF NEW.estado IS NOT DISTINCT FROM OLD.estado THEN
            RETURN NULL;
          END IF;
          SELECT * INTO v_log
            FROM platform.order_state_log l
           WHERE l.tenant_id = NEW.tenant_id
             AND l.order_id = NEW.id
             AND l.version = NEW.version;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'orders_mirror: a transicao % -> % (version %) nao gravou '
              'order_state_log na mesma transaccao (criterio 2 do KAM-044)',
              OLD.estado, NEW.estado, NEW.version
              USING ERRCODE = '{SQLSTATE_REGISTO}';
          END IF;
          IF v_log.de <> OLD.estado OR v_log.para <> NEW.estado THEN
            RAISE EXCEPTION
              'orders_mirror: o order_state_log da version % diz % -> % e a '
              'encomenda foi de % para %',
              NEW.version, v_log.de, v_log.para, OLD.estado, NEW.estado
              USING ERRCODE = '{SQLSTATE_REGISTO}';
          END IF;
          IF NEW.estado = {PAGA} THEN
            IF v_log.actor_kind <> 'sistema'
               OR v_log.evento_id IS NULL
               OR btrim(v_log.evento_id) = ''
               OR v_log.causa NOT IN ({", ".join(CAUSAS_QUE_PAGAM)}) THEN
              RAISE EXCEPTION
                'orders_mirror: paga exige evento autenticado do PAY com actor '
                'sistema e veio causa=%, actor=%, evento=% (criterio 3 do '
                'KAM-044, ADR-013)',
                v_log.causa, v_log.actor_kind, v_log.evento_id
                USING ERRCODE = '{SQLSTATE_AUTENTICIDADE}';
            END IF;
            -- **E o evento tem de existir.** As tres verificacoes acima nao
            -- ligam aquele texto a evento nenhum: a primeira versao desta
            -- revisao aceitava `evento_id = 'inventado'` com actor `sistema` e
            -- causa `payment.confirmed`, e a revisao adversarial mediu-o — o
            -- `paga` escrito, o outbox a zero e o `payment_events` a zero.
            --
            -- A ancora e o recibo de consumo do KAM-006
            -- (`platform.events_consumed`, revisao `0005`): o consumidor
            -- idempotente registra ali o `evento.id` **antes** de agir, pelo que
            -- exigir a linha e exigir que a transicao corra dentro do consumo de
            -- um evento que entrou de facto pela fila. Nao e o
            -- `payment_events` da `0029` porque o `payment_charges.order_id`
            -- **nao tem FK** — e do KAM-055 — e uma barreira que assentasse numa
            -- coluna que ninguem impoe nao e uma barreira.
            --
            -- Compara-se em **texto** e nao com um `::uuid`: um `evento_id` que
            -- nao seja um UUID levantaria `22P02` em vez da recusa com o codigo
            -- desta revisao, e o que se quer dizer a quem chama e «esse evento
            -- nao existe», nao «esse texto nao e um UUID».
            IF NOT EXISTS (
                 SELECT 1 FROM platform.events_consumed c
                  WHERE c.tenant_id = NEW.tenant_id
                    AND c.event_id::text = btrim(v_log.evento_id)) THEN
              RAISE EXCEPTION
                'orders_mirror: paga cita o evento % e nao ha recibo de consumo '
                'dele neste tenant (events_consumed, KAM-006); o consumidor '
                'registra o evento antes de transitar (criterio 3 do KAM-044, '
                'ADR-013)',
                v_log.evento_id
                USING ERRCODE = '{SQLSTATE_AUTENTICIDADE}';
            END IF;
          END IF;
{ramo}          RETURN NULL;
        END $$
        """
    )


COMENTARIO_DA_0030 = (
    "'CONSTRAINT TRIGGER diferido de orders_mirror: no COMMIT, toda a "
    "mudanca de estado tem a sua linha de order_state_log, e paga exige "
    "actor sistema com evento autenticado do PAY (KAM-044 criterios 2 e 3, "
    "ADR-013).'"
)
COMENTARIO_DA_0046 = (
    "'CONSTRAINT TRIGGER diferido de orders_mirror: no COMMIT, toda a "
    "mudanca de estado tem a sua linha de order_state_log, e paga exige "
    "actor sistema com evento autenticado do PAY (KAM-044 criterios 2 e 3, "
    "ADR-013). Desde a 0046, reembolsada exige actor dono ou ops "
    "identificado (KAM-050 criterio 5).'"
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO {GRAFO} (de, para, flag)
        VALUES {", ".join(ADICIONAIS)}
        """
    )
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} DROP CONSTRAINT {RESTRICAO_DA_EXCEPCAO}"
    )
    op.execute(
        f"""
        ALTER TABLE {ENCOMENDAS}
          ADD CONSTRAINT {RESTRICAO_DA_EXCEPCAO}
          CHECK (excepcao IN ({", ".join(EXCEPCOES)}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0046}))
        """
    )
    _funcao(RAMO_DO_REEMBOLSO)
    op.execute(
        "COMMENT ON FUNCTION platform.order_estado_exige_log() IS "
        + COMENTARIO_DA_0046
    )
    op.execute(f"ALTER TABLE {RESERVAS} DROP CONSTRAINT {UNICIDADE_DA_0033}")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDICE_DA_LINHA_VIVA}
          ON {RESERVAS} (tenant_id, order_id, line_no)
          WHERE estado <> 'libertada'
        """
    )


def _contar(tabela: str, sql: str) -> int:
    """Conta **todas** as linhas, de todos os tenants.

    **Com o `FORCE ROW LEVEL SECURITY` suspenso, e tem de ser.** A ligacao da
    migracao e dona da tabela, e o `FORCE` sujeita o dono a politica
    `tenant_iso`: sem `app.tenant_id`, um `count(*)` le **zero** — e a guarda
    deixava passar a descida ate ao `ADD CONSTRAINT`, que valida sem RLS e
    falha com um `23514` que nao diz o que fazer. Medido no ensaio
    `test_downgrade_0046`, na primeira versao desta funcao. O `NO FORCE` vale so
    dentro da transaccao da migracao: o `FORCE` volta logo a seguir, e uma
    falha a meio reverte os dois.
    """
    op.execute(f"ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY")
    contagem = int(op.get_bind().exec_driver_sql(sql).scalar_one())
    op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
    return contagem


def downgrade() -> None:
    duplas = _contar(
        RESERVAS,
        f"SELECT count(*) FROM (SELECT 1 FROM {RESERVAS} "
        "GROUP BY tenant_id, order_id, line_no HAVING count(*) > 1) d",
    )
    if duplas:
        raise RuntimeError(
            f"downgrade da 0046 recusado: ha {duplas} linha(s) de encomenda com "
            "mais do que uma reserva (re-reservas do pagamento tardio), e a "
            "unicidade da 0033 nao as aceita. Decida o que fazer a essas "
            "reservas antes de descer."
        )
    accoes = _contar(
        AUDIT_LOG,
        f"SELECT count(*) FROM {AUDIT_LOG} WHERE action = '{ACCAO_NOVA}'",
    )
    if accoes:
        raise RuntimeError(
            f"downgrade da 0046 recusado: ha {accoes} linha(s) de audit_log com "
            f"accao {ACCAO_NOVA} e o dominio da 0042 nao as aceita. O audit_log "
            "e append-only e nenhum papel tem DELETE: exporte a cadeia e decida "
            "o que fazer a essas linhas antes de descer."
        )
    excepcoes = _contar(
        ENCOMENDAS,
        f"SELECT count(*) FROM {ENCOMENDAS} WHERE excepcao = '{EXCEPCAO_NOVA}'",
    )
    if excepcoes:
        raise RuntimeError(
            f"downgrade da 0046 recusado: ha {excepcoes} encomenda(s) com a "
            f"excepcao {EXCEPCAO_NOVA}, que o dominio da 0030 nao aceita. "
            "Resolva-as antes de descer."
        )
    op.execute(f"DROP INDEX platform.{INDICE_DA_LINHA_VIVA}")
    op.execute(
        f"""
        ALTER TABLE {RESERVAS}
          ADD CONSTRAINT {UNICIDADE_DA_0033} UNIQUE (tenant_id, order_id, line_no)
        """
    )
    _funcao(SEM_RAMO)
    op.execute(
        "COMMENT ON FUNCTION platform.order_estado_exige_log() IS "
        + COMENTARIO_DA_0030
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0042}))
        """
    )
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} DROP CONSTRAINT {RESTRICAO_DA_EXCEPCAO}"
    )
    op.execute(
        f"""
        ALTER TABLE {ENCOMENDAS}
          ADD CONSTRAINT {RESTRICAO_DA_EXCEPCAO}
          CHECK (excepcao IN ({", ".join(EXCEPCOES_DA_0030)}))
        """
    )
    op.execute(
        f"DELETE FROM {GRAFO} WHERE (de, para) IN ({', '.join(PARES_ADICIONAIS)})"
    )

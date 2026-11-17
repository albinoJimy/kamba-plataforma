"""Subscricoes de Trust & Safety e a fonte da mudanca de conta (KAM-200).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao escreve

1. **Sete linhas em `platform.evt_subscricoes`**, as do `registry/trust.yaml`:
   o consumidor `trust` dos sete tipos do criterio 1 do KAM-097. E a forma da
   `0052` (KAM-194) e da `0061` (KAM-201): as linhas so as escreve o dono das
   tabelas, e em producao nao ha escritor. Sem elas, o publicador nunca poe um
   evento nas filas `evt.trust.p<n>`, e o consumidor do processo de lote
   (`services/onboarding-web/src/lote.ts`) fica vivo e surdo. O `exige_ordem`
   deriva do prefixo `payment.` (a restricao
   `evt_subscricoes_payment_exige_ordem` da `0005`), e o `versao_max` e 2: o
   *payload* que o `efeitoDeTrust` le e o mesmo na v1 e na v2 dos sete
   contratos.

2. **A fonte da `mudanca_de_conta`**, que nao existia: nem a `payment_accounts`
   nem o `tenants.nif` tinham historico nem evento (criterio 6 do KAM-097,
   devolvido ao KAM-200). Dois *triggers* `AFTER`, um em cada tabela, gravam um
   sinal `mudanca_de_conta` (severidade `alta`, a do tipo) quando:

   * o `tenants.nif` muda;
   * uma conta de pagamento de `pme` nasce, ou muda num dos campos que dizem
     **para onde vai o dinheiro** (`entidade`, `pos_id`, `iec`,
     `liquidacao_destino`, `manual_instrucoes`, `credenciais_ref`);

   e **so depois da activacao** (`tenants.primeira_activacao_at` preenchido,
   escrito pelo *trigger* da `0040`): o onboarding configura a conta e o NIF, e
   isso nao e sinal de nada. O caso `trust` nao nasce aqui: abre-o a varredura
   `mudancas_de_conta` do processo de lote, pela fila de revisao, que e quem
   tem o desenho dos casos (`ServicoDeTrust.proporSancao`).

3. **A `limitacao` no caminho do catalogo** (criterio 7): um *trigger*
   `BEFORE` recusa com `23514` um produto novo (`INSERT` em `offer_terms`), a
   primeira publicacao de um rascunho (`offer_terms.estado` a `publicado`) e
   uma ingestao nova ou publicada do catalogo por IA (`catalog_ingestions`),
   quando o tenant tem um passo `limitacao` ou acima em vigor — sem um recurso
   **provido** sobre ele, a mesma leitura do `emVigor` do
   `packages/core-ts/src/trust/servico.ts`. Na base e nao num `if` do COM,
   porque ha dois escritores: o COM (TypeScript) e o catalogo por IA (Python),
   e um `if` num deles deixava o outro aberto. O que ja estava publicado
   continua a vender; o preco e o stock continuam a mudar. **Esta e `SECURITY
   INVOKER`**, ao contrario da de cima: quem escreve no catalogo e o
   `kamba_app` com o contexto do tenant (a RLS `FORCE` das duas tabelas
   exige-o) ou o `kamba_batch`, que tem `BYPASSRLS`, e os dois leem o passo, o
   `recurso_de` e o `recurso_estado` da `ts_sanction` (`0056`). Um escritor sem
   contexto nao ve as sancoes e passa — mas tambem nao passa a RLS da tabela
   que escreve.

## Os triggers da mudanca de conta sao `SECURITY DEFINER`, e porque

Quem escreve na `payment_accounts` e o `kamba_batch` (`0027`), que tem
`BYPASSRLS` e pode nao ter `app.tenant_id` posto; quem escreve o `nif` e o
`kamba_app` (`0001`), que tem `INSERT` na `ts_signal` mas so no seu tenant. Um
*trigger* que corresse como o chamador dependia de qual dos dois escreveu. Como
dono, com `search_path = pg_catalog, platform` (sem `public`, pela razao da
`0029`), escreve sempre. **E a `ts_signal` tem RLS `FORCE`**, que prende tambem
o dono: por isso a funcao poe o `app.tenant_id` no tenant **da linha** que
disparou, escreve, e repoe o que estava. O tenant e o da linha que o escritor ja
tinha autoridade para escrever; a funcao nao recebe tenant de ninguem.

A chave do sinal (`ref_evento`) e um `uuid` novo por mudanca: cada mudanca e um
sinal, e uma escrita que nao muda nada nao dispara (`IS DISTINCT FROM`).

## O `downgrade`

Larga os cinco *triggers* e as duas funcoes, e apaga as sete subscricoes **e so
estas**, pela chave primaria `(consumer, tipo)`. **O `upgrade` nao usa `ON
CONFLICT`**, pela razao da `0052`: uma linha ja presente com a mesma chave e uma
subscricao que esta revisao nao criou, e o `downgrade` apaga-la-ia. Os sinais
gravados pelos *triggers* ficam: a `ts_signal` e *append-only* e e da `0056`.

## Numero

`0069`, dado pelo orquestrador do lote 10 como provisorio, com a `0067`
(KAM-098) e a `0068` (KAM-118) por fundir. **O `down_revision` aponta a `0066`**,
a cabeca da `main` em que este ramo nasceu, para a cadeia correr no CI deste
PR; reaponta-se na integracao, pela ordem da fila, como o numero.
"""

from __future__ import annotations

from alembic import op

revision = "0069"
down_revision = "0066"
branch_labels = None
depends_on = None

#: `(consumer, tipo, versao_max, finalidade, exige_ordem)`, na forma da `0052`.
LINHAS = (
    ("trust", "order.created", "2", "transacao", "false"),
    ("trust", "order.paid", "2", "transacao", "false"),
    ("trust", "order.delivered", "2", "transacao", "false"),
    ("trust", "payment.manual_confirmed", "2", "transacao", "true"),
    ("trust", "payment.confirmed", "2", "transacao", "true"),
    ("trust", "query.handoff", "2", "transacao", "false"),
    ("trust", "screening.violation_detected", "2", "transacao", "false"),
)

FUNCAO = "platform.ts_mudanca_de_conta()"
TRIGGER_DA_CONTA = "payment_accounts_mudanca_de_conta"
TRIGGER_DO_NIF = "tenants_mudanca_de_nif"

LIMITACAO = "platform.ts_limitacao_do_catalogo()"
TRIGGER_DA_OFERTA_NOVA = "offer_terms_ts_limitacao_nova"
TRIGGER_DA_OFERTA_PUBLICADA = "offer_terms_ts_limitacao_publicada"
TRIGGER_DA_INGESTAO = "catalog_ingestions_ts_limitacao"

#: Os campos da conta que dizem para onde vai o dinheiro.
CAMPOS_DA_CONTA = (
    "entidade",
    "pos_id",
    "iec",
    "liquidacao_destino",
    "manual_instrucoes",
    "credenciais_ref",
)

#: «Mudou um campo do destino do dinheiro», por extenso, para o *trigger*. Um
#: literal, e nao construido de `CAMPOS_DA_CONTA`: o gate 3b le as instrucoes sem
#: executar a revisao. O ensaio da revisao confronta-o com a tupla.
MUDOU_A_CONTA = (
    "NEW.entidade IS DISTINCT FROM OLD.entidade"
    " OR NEW.pos_id IS DISTINCT FROM OLD.pos_id"
    " OR NEW.iec IS DISTINCT FROM OLD.iec"
    " OR NEW.liquidacao_destino IS DISTINCT FROM OLD.liquidacao_destino"
    " OR NEW.manual_instrucoes IS DISTINCT FROM OLD.manual_instrucoes"
    " OR NEW.credenciais_ref IS DISTINCT FROM OLD.credenciais_ref"
)


def upgrade() -> None:
    for consumer, tipo, versao_max, finalidade, exige_ordem in LINHAS:
        op.execute(
            f"""
            INSERT INTO platform.evt_subscricoes
                   (consumer, tipo, versao_max, finalidade, exige_ordem, activo)
            VALUES ('{consumer}', '{tipo}', {versao_max}, '{finalidade}', {exige_ordem}, true)
            """
        )
    _mudanca_de_conta()
    _limitacao_do_catalogo()


def _limitacao_do_catalogo() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {LIMITACAO}
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_limitado boolean;
        BEGIN
          -- So o que e novo: um produto novo, a primeira publicacao, uma
          -- ingestao nova ou publicada. O resto passa sem perguntar.
          IF TG_OP = 'UPDATE' THEN
            -- Um `pausado` que volta a `publicado` ja foi publicado: nao e novo.
            IF TG_TABLE_NAME = 'offer_terms'
               AND NOT (OLD.estado = 'rascunho' AND NEW.estado = 'publicado') THEN
              RETURN NEW;
            END IF;
            IF TG_TABLE_NAME = 'catalog_ingestions'
               AND (NEW.estado <> 'publicada' OR OLD.estado = 'publicada') THEN
              RETURN NEW;
            END IF;
          END IF;

          SELECT EXISTS (
                   SELECT 1 FROM platform.ts_sanction s
                    WHERE s.tenant_id = NEW.tenant_id AND s.recurso_de IS NULL
                      AND s.passo IN ('limitacao', 'suspensao', 'encerramento')
                      AND NOT EXISTS (
                            SELECT 1 FROM platform.ts_sanction r
                             WHERE r.tenant_id = s.tenant_id AND r.recurso_de = s.id
                               AND r.recurso_estado = 'provido'))
            INTO v_limitado;

          IF v_limitado THEN
            RAISE EXCEPTION 'loja com limitacao de Trust & Safety em vigor: sem produtos nem listas novos'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {LIMITACAO} FROM PUBLIC")
    op.execute(
        f"""
        COMMENT ON FUNCTION {LIMITACAO} IS
        'KAM-200: recusa (23514) um produto novo, a primeira publicacao e uma
         ingestao nova ou publicada do catalogo de um tenant com limitacao de T&S
         ou acima em vigor (sem recurso provido).'
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_DA_OFERTA_NOVA}
          BEFORE INSERT ON platform.offer_terms
          FOR EACH ROW EXECUTE FUNCTION {LIMITACAO}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_DA_OFERTA_PUBLICADA}
          BEFORE UPDATE OF estado ON platform.offer_terms
          FOR EACH ROW EXECUTE FUNCTION {LIMITACAO}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_DA_INGESTAO}
          BEFORE INSERT OR UPDATE OF estado ON platform.catalog_ingestions
          FOR EACH ROW EXECUTE FUNCTION {LIMITACAO}
        """
    )


def _mudanca_de_conta() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {FUNCAO}
          RETURNS trigger
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_tenant  uuid;
          v_antes   text;
          v_activo  boolean;
        BEGIN
          IF TG_TABLE_NAME = 'tenants' THEN
            IF NEW.nif IS NOT DISTINCT FROM OLD.nif THEN
              RETURN NULL;
            END IF;
            v_tenant := NEW.id;
          ELSE
            IF NEW.beneficiary_kind <> 'pme' OR NEW.tenant_id IS NULL THEN
              RETURN NULL;
            END IF;
            IF TG_OP = 'UPDATE' AND NOT ({MUDOU_A_CONTA}) THEN
              RETURN NULL;
            END IF;
            v_tenant := NEW.tenant_id;
          END IF;

          -- O contexto do tenant **da linha**, para a RLS `FORCE` da
          -- `ts_signal` (e da `tenants`); reposto no fim.
          v_antes := current_setting('app.tenant_id', true);
          PERFORM set_config('app.tenant_id', v_tenant::text, true);

          SELECT t.primeira_activacao_at IS NOT NULL INTO v_activo
            FROM platform.tenants t WHERE t.id = v_tenant;
          IF coalesce(v_activo, false) THEN
            INSERT INTO platform.ts_signal
                   (tenant_id, tipo, severidade, ref_evento, detalhe, ocorrido_em)
            VALUES (v_tenant, 'mudanca_de_conta', 'alta', gen_random_uuid(),
                    '{{}}'::jsonb, now());
          END IF;

          PERFORM set_config('app.tenant_id', coalesce(v_antes, ''), true);
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCAO} FROM PUBLIC")
    op.execute(
        f"""
        COMMENT ON FUNCTION {FUNCAO} IS
        'KAM-200: grava um ts_signal mudanca_de_conta quando o NIF ou a conta de
         pagamento de uma PME muda depois da activacao. SECURITY DEFINER com o
         app.tenant_id do tenant da linha, reposto no fim.'
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_DA_CONTA}
          AFTER INSERT OR UPDATE OF {", ".join(CAMPOS_DA_CONTA)}
          ON platform.payment_accounts
          FOR EACH ROW EXECUTE FUNCTION {FUNCAO}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_DO_NIF}
          AFTER UPDATE OF nif ON platform.tenants
          FOR EACH ROW EXECUTE FUNCTION {FUNCAO}
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER {TRIGGER_DA_INGESTAO} ON platform.catalog_ingestions")
    op.execute(f"DROP TRIGGER {TRIGGER_DA_OFERTA_PUBLICADA} ON platform.offer_terms")
    op.execute(f"DROP TRIGGER {TRIGGER_DA_OFERTA_NOVA} ON platform.offer_terms")
    op.execute(f"DROP FUNCTION {LIMITACAO}")
    op.execute(f"DROP TRIGGER {TRIGGER_DO_NIF} ON platform.tenants")
    op.execute(f"DROP TRIGGER {TRIGGER_DA_CONTA} ON platform.payment_accounts")
    op.execute(f"DROP FUNCTION {FUNCAO}")
    for consumer, tipo, _versao_max, _finalidade, _exige_ordem in LINHAS:
        op.execute(
            f"""
            DELETE FROM platform.evt_subscricoes
             WHERE consumer = '{consumer}' AND tipo = '{tipo}'
            """
        )

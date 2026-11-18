"""Entrega presa ao actor: o papel e o instante de entregue pela base (KAM-204).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero

Provisorio: `0071` sobre a `0070` do canal do dono (KAM-118). Quem funde em
segundo renumera. Os ensaios descobrem-na pelo *glob* `*_entrega_presa_ao_actor.py`
e leem o `down_revision` daqui.

## O que esta revisao cria

| Objecto | Para que serve |
|---|---|
| `platform.order_entrega_presa()` e o *trigger* `order_entrega_presa` (`BEFORE INSERT OR UPDATE`, `ENABLE ALWAYS`) | o `entregue_at` e o `now()` da transaccao em cada entrada em `entregue`; no fim de uma disputa ficam o instante e o papel da entrega que houve; fora disso, as duas colunas nao mudam, e uma encomenda nao nasce com elas |
| `platform.order_entrega_exige_papel()` e o `CONSTRAINT TRIGGER` diferido `order_entrega_exige_papel` (`ENABLE ALWAYS`) | no `COMMIT`, o `entrega_confirmada_por` de uma entrega tem de ser o papel que o `actor_kind` da linha do `order_state_log` dessa `version` pode declarar |
| `REVOKE UPDATE (entregue_at)` ao `kamba_app` | o instante deixa de ser coluna que a aplicacao escreve |

## Porque sao dois *triggers* e nao um

O papel e o actor nao vivem na mesma linha: o actor esta no `order_state_log`,
que o `transition` grava **depois** do CAS. Um `BEFORE UPDATE` corre antes de
essa linha existir, e e por isso que a `0030` pos a autenticidade de `paga` num
`CONSTRAINT TRIGGER` diferido. O papel segue o mesmo caminho.

O instante e a imutabilidade, ao contrario, sao da propria linha, e um `BEFORE`
e o unico sitio onde o valor se **escreve** em vez de se recusar: o criterio 2 do
bloco diz que o valor que a aplicacao mande e ignorado, e so um `BEFORE` pode
substituir o `NEW`.

## Porque nao se edita o `order_estado_exige_log`

O papel podia ser mais um ramo daquele corpo, como o reembolso da `0046`. Fica
num *trigger* proprio por duas razoes: o `downgrade` passa a ser um `DROP`, sem
copia literal do corpo da `0046`; e o SQLSTATE e outro (`23514`, que o criterio 1
do bloco pede), pelo que as recusas ficam em funcoes diferentes.

**Os dois diferidos leem a mesma linha, e os dois recusam a falta dela**, com o
mesmo `KA005`. A primeira versao desta revisao devolvia sem verificar, a contar
com o `order_estado_exige_log` — e a revisao adversarial mostrou que isso so vale
se os dois correrem no mesmo instante: um `SET CONSTRAINTS
platform.order_entrega_exige_papel IMMEDIATE` (que nao pede privilegio nenhum)
entre o `UPDATE` e o `INSERT` do registo corria este diferido antes de haver
linha, e um dono gravava `cliente`. O `test_correr_o_papel_antes_do_registo_e_recusado`
mede-o.

## A janela procura-se no contacto canonico

A fusao de contactos (KAM-008) reaponta as conversas do contacto absorvido para
o que fica, e a `orders_mirror.contact_id` nao muda. Por isso a janela le-se
sobre a cadeia de `merged_into` do contacto da encomenda, ate oito passos, como o
`SQL_PEDIDOS_ENTREGUES` do KAM-096: sem isso, um cliente fundido que escreve hoje
nao confirmava uma encomenda de antes da fusao.

## O que a base prova, e o que nao prova

Prova que o actor do registo e um `agente` e que o cliente do contacto escreveu
nas ultimas 24 h. **Nao prova** que foi o agente quem escreveu a linha: o
`actor_kind` do `order_state_log` e a janela da `conversations` sao os dois
escritos pelo `kamba_app` (a `0009` da-lhe `UPDATE (last_inbound_at,
window_expires_at)`), pelo que uma instrucao directa do proprio `kamba_app`,
fora do `transition`, consegue as duas coisas. E o mesmo limite do `paga` da
`0030`: a base distingue actores pelo que o registo diz, e nao distingue
caminhos de codigo dentro do mesmo papel.

## `SECURITY INVOKER`, como o `order_estado_exige_log`

A omissao. O diferido le o `order_state_log` (e, para o `cliente`, a
`conversations`) com a RLS e o contexto de quem escreveu a encomenda. Uma
`SECURITY DEFINER` lia zero linhas, porque o dono esta sujeito ao `FORCE`
(`db/rls.py`), e recusava todas as entregas.

## O `downgrade`

Nao perde dados: tira as duas barreiras e devolve o privilegio. Os valores que
elas escreveram ficam, e sao validos para a `0030`. Por isso nao recusa.
"""

from __future__ import annotations

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

ENCOMENDAS = "platform.orders_mirror"
PAPEL_DA_APP = "kamba_app"

#: O SQLSTATE das recusas desta revisao. O criterio 1 do bloco pede `23514`
#: (`check_violation`), e o 3 recusa pela mesma regra de coluna.
SQLSTATE_PAPEL = "23514"

#: O SQLSTATE da `0030` para a mudanca de estado sem `order_state_log`.
SQLSTATE_REGISTO = "KA005"

#: Os pares `(actor_kind, entrega_confirmada_por)` que entram. **Um papel por
#: actor** (decisao do fundador, 2026-11-18), e e o que deixa o `transition`
#: pedir o papel ao `ctx` (criterio 4): o `PAPEL_POR_ACTOR` do
#: `services/com/src/orders/contrato.ts` tem os mesmos tres. O `ops` nao declara
#: papel nenhum: decide disputas, e o fim de uma disputa mantem o papel da
#: entrega que houve. O `estafeta` do `sistema` nao tem produtor hoje (Fase C).
PARES_ACTOR_PAPEL = (
    "('agente', 'cliente')",
    "('dono', 'dono')",
    "('sistema', 'estafeta')",
)


def upgrade() -> None:
    # O *trigger* do instante e da imutabilidade. Ver a nota do modulo.
    #
    # O fim de uma disputa e `em_disputa -> entregue` (KAM-050): o `NEW` fica com o
    # `OLD`, e o que a aplicacao mande e ignorado, como na entrada nova.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_entrega_presa() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.entregue_at IS NOT NULL
               OR NEW.entrega_confirmada_por IS NOT NULL THEN
              RAISE EXCEPTION
                'orders_mirror: uma encomenda nasce sem entregue_at nem '
                'entrega_confirmada_por; escreve-os a transicao para entregue '
                '(KAM-204)'
                USING ERRCODE = '{SQLSTATE_PAPEL}';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.estado = 'entregue' AND OLD.estado <> 'entregue' THEN
            IF OLD.estado = 'em_disputa' THEN
              NEW.entregue_at := OLD.entregue_at;
              NEW.entrega_confirmada_por := OLD.entrega_confirmada_por;
            ELSE
              NEW.entregue_at := now();
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.entregue_at IS DISTINCT FROM OLD.entregue_at
             OR NEW.entrega_confirmada_por
                IS DISTINCT FROM OLD.entrega_confirmada_por THEN
            RAISE EXCEPTION
              'orders_mirror: entregue_at e entrega_confirmada_por so se '
              'escrevem na transicao para entregue (a encomenda esta em %; '
              'KAM-204)',
              OLD.estado
              USING ERRCODE = '{SQLSTATE_PAPEL}';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_entrega_presa() IS "
        "'BEFORE INSERT OR UPDATE de orders_mirror: entregue_at e o now() da "
        "transaccao em cada entrada em entregue, o fim de uma disputa mantem o "
        "instante e o papel da entrega, e fora disso as duas colunas nao mudam "
        "(KAM-204).'"
    )
    op.execute(
        f"""
        CREATE TRIGGER order_entrega_presa BEFORE INSERT OR UPDATE ON {ENCOMENDAS}
          FOR EACH ROW EXECUTE FUNCTION platform.order_entrega_presa()
        """
    )
    # O diferido do papel. **Para o `cliente`, mais do que o actor**: a conversa do
    # contacto da encomenda tem a janela de 24 h aberta, isto e, o cliente escreveu
    # nas ultimas 24 h. E o «turno do contacto da encomenda» do criterio 1, lido na
    # base, porque o `actor_id` do agente (`grafo-<vertical>`) nao o diz.
    op.execute(
        f"""
        CREATE FUNCTION platform.order_entrega_exige_papel() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE v_log platform.order_state_log;
        BEGIN
          IF NEW.estado IS DISTINCT FROM 'entregue'
             OR OLD.estado IN ('entregue', 'em_disputa') THEN
            RETURN NULL;
          END IF;
          SELECT * INTO v_log
            FROM platform.order_state_log l
           WHERE l.tenant_id = NEW.tenant_id
             AND l.order_id = NEW.id
             AND l.version = NEW.version;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'orders_mirror: a entrega da version % nao tem order_state_log; '
              'o papel verifica-se contra o actor do registo (KAM-204)',
              NEW.version
              USING ERRCODE = '{SQLSTATE_REGISTO}';
          END IF;
          IF (v_log.actor_kind, NEW.entrega_confirmada_por)
             NOT IN ({", ".join(PARES_ACTOR_PAPEL)}) THEN
            RAISE EXCEPTION
              'orders_mirror: o actor % nao declara a entrega como %, '
              '(version %; KAM-204)',
              v_log.actor_kind, NEW.entrega_confirmada_por, NEW.version
              USING ERRCODE = '{SQLSTATE_PAPEL}';
          END IF;
          IF NEW.entrega_confirmada_por = 'cliente' AND NOT EXISTS (
               WITH RECURSIVE cadeia(contacto, passos) AS (
                   SELECT NEW.contact_id, 0
                   UNION ALL
                   SELECT k.merged_into, c.passos + 1
                     FROM cadeia c
                     JOIN platform.contacts k
                       ON k.tenant_id = NEW.tenant_id AND k.contact_id = c.contacto
                    WHERE k.merged_into IS NOT NULL AND c.passos < 8)
               SELECT 1 FROM platform.conversations v
                 JOIN cadeia c ON v.contact_id = c.contacto
                WHERE v.tenant_id = NEW.tenant_id
                  AND v.window_expires_at > now()) THEN
            RAISE EXCEPTION
              'orders_mirror: a entrega confirmada pelo cliente exige a janela '
              'de 24 h aberta na conversa do contacto da encomenda (KAM-204)'
              USING ERRCODE = '{SQLSTATE_PAPEL}';
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.order_entrega_exige_papel() IS "
        "'CONSTRAINT TRIGGER diferido de orders_mirror: no COMMIT, o "
        "entrega_confirmada_por de uma entrega e o papel que o actor_kind do "
        "order_state_log dessa version pode declarar, e cliente exige a janela "
        "aberta na conversa do contacto (KAM-204).'"
    )
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER order_entrega_exige_papel
          AFTER UPDATE ON {ENCOMENDAS}
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION platform.order_entrega_exige_papel()
        """
    )
    # `ENABLE ALWAYS`, pela razao da `0030`: com a omissao, uma sessao em
    # `session_replication_role = replica` escrevia qualquer papel e qualquer
    # instante.
    op.execute(f"ALTER TABLE {ENCOMENDAS} ENABLE ALWAYS TRIGGER order_entrega_presa")
    op.execute(
        f"ALTER TABLE {ENCOMENDAS} ENABLE ALWAYS TRIGGER order_entrega_exige_papel"
    )
    op.execute(f"REVOKE UPDATE (entregue_at) ON {ENCOMENDAS} FROM {PAPEL_DA_APP}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE (entregue_at) ON {ENCOMENDAS} TO {PAPEL_DA_APP}")
    op.execute(f"DROP TRIGGER order_entrega_exige_papel ON {ENCOMENDAS}")
    op.execute("DROP FUNCTION platform.order_entrega_exige_papel()")
    op.execute(f"DROP TRIGGER order_entrega_presa ON {ENCOMENDAS}")
    op.execute("DROP FUNCTION platform.order_entrega_presa()")

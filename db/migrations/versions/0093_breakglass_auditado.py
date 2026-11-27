"""O acesso de excepcao a um host escreve-se no `audit_log` (KAM-259).

Revisao: 0093
Anterior: 0092

A abertura de um acesso de excepcao a um *host* de `staging` ou de `prod` passa
pela conta `breakglass` do `infra/modules/host-base/`, e o `sshd` dessa conta
corre sempre o portao `kamba_breakglass.py` (a *shell* de login e o
`ForceCommand`). O portao escreve `breakglass.open` antes de a *shell* abrir e
`breakglass.close` quando ela fecha. Decisao do fundador de 2026-11-25, opcao A (bloco do KAM-259, secao
«Decisoes do fundador»).

Esta revisao traz o lado da base, e tres pecas:

    breakglass.close        a accao do fecho, no dominio de `audit_log.action`.
    breakglass_registar     a porta: `SECURITY DEFINER`, so as duas accoes, so
                            na cadeia de plataforma (`tenant_id` nulo), sempre
                            com `actor_type = 'staff'` e `entity = 'host'`.
    breakglass_registo      a politica que deixa o dono da tabela inserir essas
                            linhas, e so com a variavel que a porta liga.

## Porque um papel proprio, e nao o `kamba_batch`

A cadeia de plataforma so a escreve, ate aqui, o `kamba_batch`, por ter
`BYPASSRLS` (revisao `0006`). Mas o `docs/tecnica/08` §3.3, regra (5), diz que
o acesso humano a producao **nao usa** o `kamba_batch`, e a credencial que o
portao le no *host* ficava ao alcance de quem esta dentro da sessao. O
`kamba_breakglass` (criado pelo `db/bootstrap.py`, como os outros) nao tem
privilegio em tabela nenhuma: tem `USAGE` no esquema e `EXECUTE` nesta porta, e
mais nada. O que o papel faz e escrever as duas accoes de *break-glass* na
cadeia de plataforma.

## O `DEFINER` nao atravessa o `FORCE`, e por isso a politica

A porta corre como o dono (`kamba_migrator`), que e `NOBYPASSRLS`, e o `FORCE`
do `audit_log` vincula-o: a `tenant_iso` recusa uma linha de `tenant_id` nulo
(a nota de `db/rls.py`, medida no KAM-052). A saida e a da `0084`: uma politica
**so para o dono**, so de `INSERT`, e so com a variavel `app.registo_breakglass`
ligada. A porta liga-a com `set_config(..., true)` antes da escrita e desliga-a
depois; a clausula `SET` da funcao nao serve, porque um nao-superutilizador nao
pode fixar uma variavel de marcador por ela (medido no KAM-236).

A politica e de `INSERT` e mais nada: nao da ao dono leitura nenhuma, pelo que o
X-04 do *gate* 6 («o dono das tabelas tambem nao ve nada») continua verdadeiro.

## O encadeamento nao muda

A linha entra pelo mesmo `INSERT` em `audit_log`, e o *trigger*
`audit_encadear` escreve o `criado_at`, o `prev_hash` e o `row_hash` como em
todas as outras. A porta nao toca na cadeia, e nao pode: nao escreve em
`audit_heads`.
"""

from __future__ import annotations

from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"
ACCAO_NOVA = "breakglass.close"

#: O papel do portao do *host*. Criado pelo `db/bootstrap.py`.
PAPEL = "kamba_breakglass"

#: A porta, com a assinatura completa, para o `GRANT` e o `REVOKE`.
PORTA = "platform.breakglass_registar(text, text, text, bytea)"

#: A politica do dono, e a variavel que a abre.
POLITICA = "breakglass_registo"
VARIAVEL = "app.registo_breakglass"

#: O dominio da accao da `0086` (vinte e uma), e o de agora, com a nova no fim.
#: Por extenso, porque o *gate* 3b le a revisao sem a correr e nao resolve um
#: `", ".join(...)` (a licao da `0006`).
LITERAIS_DE_ACCAO_0086 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto', "
    "'trust.tecto', "
    "'secret.rotate', 'secret.revoke', "
    "'order.contact_view', "
    "'privacy.telefones_exportados'"
)
LITERAIS_DE_ACCAO = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto', "
    "'trust.tecto', "
    "'secret.rotate', 'secret.revoke', "
    "'order.contact_view', "
    "'privacy.telefones_exportados', "
    "'breakglass.close'"
)

#: As duas accoes que a porta aceita, por extenso para o SQL.
LITERAIS_DO_BREAKGLASS = "'breakglass.open', 'breakglass.close'"


def upgrade() -> None:
    _trocar_a_accao(LITERAIS_DE_ACCAO)
    _politica()
    _porta()
    _privilegios()


def _trocar_a_accao(literais: str) -> None:
    """Troca o `CHECK` da accao, com `NO FORCE` a volta (a armadilha da `0038`)."""
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({literais}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def _politica() -> None:
    """So `INSERT`, so o dono, so as duas accoes sem tenant, e so com a variavel."""
    op.execute(
        f"CREATE POLICY {POLITICA} ON {AUDIT_LOG} FOR INSERT TO kamba_migrator "
        f"WITH CHECK (tenant_id IS NULL AND action IN ({LITERAIS_DO_BREAKGLASS}) "
        f"AND current_setting('{VARIAVEL}', true) = 'on')"
    )


def _porta() -> None:
    """A porta do portao do *host*. Ver a nota do modulo.

    O `search_path` e `pg_catalog, platform` e **sem `public`**, pela razao da
    `0029`: num `SECURITY DEFINER`, um esquema onde o chamador crie objectos
    deixava-o sombrear um operador que este corpo usa.

    A accao confere-se aqui e nao so pelo `CHECK`: o `CHECK` aceita as vinte e
    duas, e a porta so as duas de *break-glass*. A politica confere-o outra vez,
    e e ela que manda — a verificacao daqui da a mensagem.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.breakglass_registar(
          p_accao text, p_actor text, p_host text, p_payload_hash bytea)
          RETURNS void
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF p_accao IS NULL OR p_accao NOT IN ({LITERAIS_DO_BREAKGLASS}) THEN
            RAISE EXCEPTION
              'breakglass_registar: so breakglass.open e breakglass.close (KAM-259)'
              USING ERRCODE = 'check_violation';
          END IF;
          PERFORM set_config('app.registo_breakglass', 'on', true);
          INSERT INTO platform.audit_log
            (tenant_id, actor_type, actor_id, action, entity, entity_id, turn_id, payload_hash)
          VALUES (NULL, 'staff', p_actor, p_accao, 'host', p_host, NULL, p_payload_hash);
          PERFORM set_config('app.registo_breakglass', 'off', true);
        END
        $func$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION {PORTA} IS
        'Escreve breakglass.open ou breakglass.close na cadeia de plataforma do
         audit_log, com actor_type staff e entity host. A porta do portao do host
         (infra/modules/host-base/kamba_breakglass.py). SECURITY DEFINER porque o
         kamba_breakglass nao tem INSERT em tabela nenhuma; o encadeamento e do
         trigger audit_encadear, como nas outras linhas (KAM-259).'
        """
    )


def _privilegios() -> None:
    """A porta nasce com `EXECUTE` para o `PUBLIC`; revoga-se e da-se a um papel so."""
    op.execute(f"REVOKE ALL ON FUNCTION {PORTA} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {PAPEL}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {PORTA} TO {PAPEL}")


def downgrade() -> None:
    # A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e
    # a guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`).
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log WHERE action = 'breakglass.close'"
        )
        .scalar_one()
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da 0093 recusado: ha {linhas} linha(s) de audit_log com "
            f"accao {ACCAO_NOVA} e o dominio da 0086 nao as aceita. O audit_log e "
            "append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    op.execute(f"REVOKE ALL ON FUNCTION {PORTA} FROM {PAPEL}")
    op.execute(f"DROP FUNCTION {PORTA}")
    op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {PAPEL}")
    op.execute(f"DROP POLICY {POLITICA} ON {AUDIT_LOG}")
    _trocar_a_accao(LITERAIS_DE_ACCAO_0086)

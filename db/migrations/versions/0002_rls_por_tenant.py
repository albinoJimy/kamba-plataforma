"""RLS `FORCE` por `app.tenant_id` e o papel estreito do resolvedor (KAM-004).

Revisao: 0002
Anterior: 0001

Liga a segunda barreira do ADR-015: a ToolLayer injecta o `tenant_id` (primeira),
e a base devolve zero linhas mesmo que a primeira falhe.

Tres tabelas, e a terceira e um caso especial:

    tenant_channels, entitlements   politica sobre `tenant_id`.
    tenants                         nao tem `tenant_id`: a politica e sobre `id`
                                    (`id = app.tenant_id`). Um contexto de tenant
                                    ve e altera so a sua propria linha — e so
                                    cria um tenant cujo `id` seja o do contexto,
                                    que e a pre-alocacao que o dicionario §3.2 ja
                                    descreve para o onboarding.

O papel `kamba_resolver` existe porque ha uma pergunta que tem de ser respondida
**antes** de haver contexto: a que tenant pertence este `phone_number_id`? Com a
politica `tenant_iso`, sem contexto ninguem ve nada. O resolvedor tem uma
politica propria, so de leitura, e `SELECT` so nas colunas de que essa pergunta
precisa — e nao consegue ler `entitlements` nem mais tabela nenhuma.

O que esta revisao **nao** faz: nao muda quem altera `tenants.plano`, `estado`
e `verificado_at`. `kamba_app` continua a poder, e com esta politica um contexto
de tenant altera o **proprio** plano. E uma decisao que nenhum documento toma, e
esta devolvida em `docs/isolamento.md` §7 e nos blocos do KAM-004 e do
KAM-009, em vez de tomada aqui.
"""

from alembic import op

import rls

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

#: Colunas que o resolvedor le. Lista minima, e *proposta*: o CHR nasce no
#: KAM-014 e pode pedir mais uma — o que se faz acrescentando-a aqui numa
#: revisao, e nao dando-lhe a tabela inteira.
#:
#:   tenant_channels   a pergunta (`phone_number_id`), a resposta (`tenant_id`,
#:                     `id`), e o que decide o encaminhamento (`vertical`,
#:                     `estado`, `channel_mode`) e a guarda do ADR-011 (`origem`).
#:   tenants           o estado (um tenant `suspenso` e rejeitado antes do AGR,
#:                     doc 08 §3.1) e o tipo (guarda do ADR-011).
COLUNAS_DO_RESOLVEDOR = {
    "tenant_channels": (
        "id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",
        "channel_mode",
    ),
    "tenants": ("id", "tipo", "estado"),
}


def upgrade() -> None:
    rls.enable_tenant_rls("tenant_channels")
    rls.enable_tenant_rls("entitlements")
    rls.enable_tenant_rls("tenants", coluna="id")

    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")
    for tabela, colunas in COLUNAS_DO_RESOLVEDOR.items():
        op.execute(
            f"GRANT SELECT ({', '.join(colunas)}) ON platform.{tabela} TO kamba_resolver"
        )
        # Politicas permissivas somam-se por OU: para o resolvedor, `tenant_iso`
        # (falso, sem contexto) OU esta (verdadeiro, so para SELECT). So le, e
        # so o que os GRANT por coluna deixarem.
        op.execute(
            f"CREATE POLICY resolver_leitura ON platform.{tabela} "
            "FOR SELECT TO kamba_resolver USING (true)"
        )


def downgrade() -> None:
    for tabela, colunas in COLUNAS_DO_RESOLVEDOR.items():
        op.execute(f"DROP POLICY resolver_leitura ON platform.{tabela}")
        op.execute(
            f"REVOKE SELECT ({', '.join(colunas)}) ON platform.{tabela} "
            "FROM kamba_resolver"
        )
    op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_resolver")

    rls.disable_tenant_rls("tenants")
    rls.disable_tenant_rls("entitlements")
    rls.disable_tenant_rls("tenant_channels")

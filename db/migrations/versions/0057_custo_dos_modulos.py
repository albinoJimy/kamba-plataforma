"""Custo por modulo de entrada: ledger, precos de teste e as vistas da H12 (KAM-124).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

| Objecto | Para que serve |
|---|---|
| `platform.module_cost_ledger` | o custo de cada modulo de entrada, uma linha por facto de custo (uma chamada ao modelo, um trabalho de imagem, uma mensagem entregue), **so de acrescentar** |
| `platform.module_test_prices` | o preco de teste de cada modulo em cada plano, carregado do `registry/plans.yaml` **sem deploy** (`h12-export carregar-precos`) |
| `platform.module_cost_gravar(...)` | a unica porta de escrita do ledger, idempotente pela `idempotency_key` |
| `platform.v_module_cost_month` | custo por tenant, mes, modulo e rubrica, em USD e em centimos de Kz |
| `platform.v_h12` | custo, preco de teste, racio e margem por tenant, mes e modulo |

E concede ao `kamba_batch` o `SELECT` em `platform.image_jobs` (KAM-120), que
e de onde a consolidacao le o custo de imagem.

## O ledger e so de acrescentar, e porque e que o `kamba_batch` tem `INSERT`

O bloco pede «`INSERT` por funcao». A funcao e `SECURITY INVOKER`, pela razao
da `0007`: um `SECURITY DEFINER` corre como o dono da tabela, e com a `FORCE`
o dono esta sujeito a politica de RLS — ou se lhe da o contexto do tenant por
dentro (e o contexto fica a valer no resto da transaccao de quem chamou), ou
se lhe tira a politica. Nenhuma das duas e melhor do que isto: **so o
`kamba_batch` escreve**, e escreve pela funcao, que e quem sabe a regra da
idempotencia. Ter o `INSERT` por coluna e o preco de ser `INVOKER`, e diz-se.

O que impede a reescrita nao e o privilegio sozinho: o gatilho
`module_cost_ledger_imutavel` recusa `UPDATE` e `DELETE` e o
`module_cost_ledger_sem_truncate` recusa o `TRUNCATE`, os dois `ENABLE
ALWAYS` (um superutilizador em `session_replication_role = replica` nao os
salta), pela licao do `audit_log` da `0006`.

## Idempotencia

`UNIQUE (tenant_id, idempotency_key)`. A funcao faz `ON CONFLICT DO NOTHING`
e, quando a chave ja existe, **compara** o que veio com o que esta: o mesmo
custo devolve `gravado = false`; outro custo com a mesma chave levanta
`23514`, pela razao do `KA002` da `0007` — repetir uma chave com outro valor
e defeito de quem chama, e devolver «ja estava» escondia-o.

## O `id` e `uuid`, e nao o `bigserial` do esboco do bloco

A convencao do `platform` e uma chave `uuid` gerada, e o gate 8 recusa uma
`IDENTITY` nova sem razao (`test_catalogo`). Uma chave sequencial nao traz nada
aqui: a ordem do ledger e a do `ocorrido_em`, e a identidade de negocio e a
`idempotency_key`.

## Dois numeros de dinheiro, e porque

`custo_usd numeric(12, 6)` e a verdade: 0,018 USD nao cabe num centimo (a
decisao da `0054`, e a da `dat.llm_call_log`). `custo_minor` e o mesmo custo em
**centimos de Kz** ao cambio do momento do registo, que vai ao lado em
`fx_aoa_per_usd` — nenhum valor em Kz fica sem a taxa (a regra do KAM-081). As
vistas **nao** leem o `custo_minor`: convertem o `custo_usd` ao cambio da
sessao (`app.fx_aoa_per_usd`, omissao 913), que e o que deixa a analise de
sensibilidade (+7,4%) correr sem reescrever o ledger.

## Os precos de teste sao hipotese, e a tabela di-lo

`module_test_prices.estado` so aceita `hipotese_nao_validada`. Um preco
decidido e outra coisa, com outro dono (KAM-059, o precario da assinatura):
esta tabela nao e precario e nenhuma cobranca a le.

## A cadeia

`0057` sobre a `0056` (KAM-097, Trust & Safety), o numero da integracao: o
ramo nasceu como `0058` sobre a `0057` do KAM-092, e ficou com a `0057` por
estar pronto primeiro. Os ensaios encontram esta revisao pelo *glob*
`*_custo_dos_modulos.py`.

## O `downgrade`

Larga as vistas, a funcao, os gatilhos e as duas tabelas, sem `CASCADE`, e
devolve o `SELECT` do `kamba_batch` em `image_jobs`. As linhas do ledger vao
com a tabela: uma base onde se desce esta revisao e de ensaio.
"""

from __future__ import annotations

from alembic import op

import modulos_custo
import rls

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

LEDGER = "platform.module_cost_ledger"
PRECOS = "platform.module_test_prices"

#: Os quatro modulos de entrada (dicionario §3.7), como literais de SQL.
MODULOS = ("'catalogo'", "'foto'", "'social'", "'orcamento'")

#: As tres rubricas do criterio 4.
RUBRICAS = ("'llm'", "'imagem'", "'mensagem'")

#: A assinatura da funcao de escrita, para o `GRANT`, o `COMMENT` e o `DROP`.
ASSINATURA_GRAVAR = (
    "platform.module_cost_gravar(uuid, text, text, numeric, text, text, timestamptz, numeric)"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {LEDGER} (
          id               uuid CONSTRAINT module_cost_ledger_pkey PRIMARY KEY
                           DEFAULT gen_random_uuid(),
          tenant_id        uuid NOT NULL
                           CONSTRAINT module_cost_ledger_tenant_fk REFERENCES platform.tenants (id),
          modulo           text NOT NULL
                           CONSTRAINT module_cost_ledger_modulo_ck
                           CHECK (modulo IN ({", ".join(MODULOS)})),
          rubrica          text NOT NULL
                           CONSTRAINT module_cost_ledger_rubrica_ck
                           CHECK (rubrica IN ({", ".join(RUBRICAS)})),
          custo_usd        numeric(12, 6) NOT NULL
                           CONSTRAINT module_cost_ledger_custo_usd_ck CHECK (custo_usd >= 0),
          custo_minor      bigint NOT NULL
                           CONSTRAINT module_cost_ledger_custo_minor_ck CHECK (custo_minor >= 0),
          fx_aoa_per_usd   numeric NOT NULL
                           CONSTRAINT module_cost_ledger_fx_ck CHECK (fx_aoa_per_usd > 0),
          ref              text
                           CONSTRAINT module_cost_ledger_ref_ck CHECK (length(ref) BETWEEN 1 AND 200),
          idempotency_key  text NOT NULL
                           CONSTRAINT module_cost_ledger_idempotency_key_ck
                           CHECK (length(idempotency_key) BETWEEN 1 AND 200),
          ocorrido_em      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT module_cost_ledger_idempotency_uq UNIQUE (tenant_id, idempotency_key)
        )
        """
    )
    # O mes de um tenant e o que as vistas e a guarda de orcamento agregam.
    op.execute(
        f"CREATE INDEX module_cost_ledger_mes_idx ON {LEDGER} (tenant_id, modulo, ocorrido_em)"
    )
    op.execute(
        f"COMMENT ON TABLE {LEDGER} IS "
        "'Custo por modulo de entrada (KAM-124): uma linha por facto de custo, so de "
        "acrescentar. Escrita so pela platform.module_cost_gravar, pelo kamba_batch. "
        "custo_usd e a verdade; custo_minor e o mesmo em centimos de Kz ao cambio "
        "fx_aoa_per_usd do registo. Sem contacto, telefone nem texto.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.module_cost_ledger_recusar()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION 'module_cost_ledger e so de acrescentar: % recusado', TG_OP
            USING ERRCODE = '23514';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER module_cost_ledger_imutavel
          BEFORE UPDATE OR DELETE ON {LEDGER}
          FOR EACH ROW EXECUTE FUNCTION platform.module_cost_ledger_recusar()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER module_cost_ledger_sem_truncate
          BEFORE TRUNCATE ON {LEDGER}
          FOR EACH STATEMENT EXECUTE FUNCTION platform.module_cost_ledger_recusar()
        """
    )
    op.execute(f"ALTER TABLE {LEDGER} ENABLE ALWAYS TRIGGER module_cost_ledger_imutavel")
    op.execute(f"ALTER TABLE {LEDGER} ENABLE ALWAYS TRIGGER module_cost_ledger_sem_truncate")

    op.execute(
        """
        CREATE FUNCTION platform.module_cost_gravar(
          p_tenant          uuid,
          p_modulo          text,
          p_rubrica         text,
          p_custo_usd       numeric,
          p_ref             text,
          p_idempotency_key text,
          p_ocorrido_em     timestamptz,
          p_fx_aoa_per_usd  numeric DEFAULT 913
        )
        RETURNS TABLE (gravado boolean, id uuid)
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_id     uuid;
          v_antigo platform.module_cost_ledger%ROWTYPE;
        BEGIN
          IF p_custo_usd IS NULL OR p_custo_usd < 0 THEN
            RAISE EXCEPTION 'module_cost_gravar: custo_usd nulo ou negativo (%)', p_custo_usd
              USING ERRCODE = '23514';
          END IF;
          IF p_fx_aoa_per_usd IS NULL OR p_fx_aoa_per_usd <= 0 THEN
            RAISE EXCEPTION 'module_cost_gravar: cambio nao positivo (%)', p_fx_aoa_per_usd
              USING ERRCODE = '23514';
          END IF;
          IF p_ocorrido_em IS NULL THEN
            RAISE EXCEPTION 'module_cost_gravar: ocorrido_em nulo'
              USING ERRCODE = '23514';
          END IF;

          INSERT INTO platform.module_cost_ledger AS l
                 (tenant_id, modulo, rubrica, custo_usd, custo_minor, fx_aoa_per_usd,
                  ref, idempotency_key, ocorrido_em)
          VALUES (p_tenant, p_modulo, p_rubrica, p_custo_usd,
                  round(p_custo_usd * p_fx_aoa_per_usd * 100)::bigint, p_fx_aoa_per_usd,
                  p_ref, p_idempotency_key, p_ocorrido_em)
          ON CONFLICT ON CONSTRAINT module_cost_ledger_idempotency_uq DO NOTHING
          RETURNING l.id INTO v_id;

          IF v_id IS NOT NULL THEN
            RETURN QUERY SELECT true, v_id;
            RETURN;
          END IF;

          SELECT * INTO v_antigo
            FROM platform.module_cost_ledger AS l
           WHERE l.tenant_id = p_tenant AND l.idempotency_key = p_idempotency_key;
          IF v_antigo.modulo IS DISTINCT FROM p_modulo
             OR v_antigo.rubrica IS DISTINCT FROM p_rubrica
             OR v_antigo.custo_usd IS DISTINCT FROM p_custo_usd::numeric(12, 6)
             OR v_antigo.ref IS DISTINCT FROM p_ref THEN
            RAISE EXCEPTION
              'module_cost_gravar: a chave % ja registou outro custo', p_idempotency_key
              USING ERRCODE = '23514';
          END IF;
          RETURN QUERY SELECT false, v_antigo.id;
        END;
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {ASSINATURA_GRAVAR} IS "
        "'Regista um custo de modulo (KAM-124). Idempotente por (tenant, idempotency_key): "
        "o mesmo custo devolve gravado = false; outro custo com a mesma chave levanta 23514. "
        "SECURITY INVOKER: so o kamba_batch a executa.'"
    )

    op.execute(
        f"""
        CREATE TABLE {PRECOS} (
          plano              text NOT NULL
                             CONSTRAINT module_test_prices_plano_ck CHECK (plano ~ '^[a-z][a-z0-9_]*$'),
          modulo             text NOT NULL
                             CONSTRAINT module_test_prices_modulo_ck
                             CHECK (modulo IN ({", ".join(MODULOS)})),
          preco_teste_minor  bigint NOT NULL
                             CONSTRAINT module_test_prices_preco_ck CHECK (preco_teste_minor >= 0),
          estado             text NOT NULL
                             CONSTRAINT module_test_prices_estado_ck
                             CHECK (estado IN ('hipotese_nao_validada')),
          carregado_em       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT module_test_prices_pkey PRIMARY KEY (plano, modulo)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {PRECOS} IS "
        "'Precos de teste dos modulos de entrada (KAM-124), em centimos de Kz, carregados "
        "do registry/plans.yaml pelo h12-export carregar-precos. Hipotese, nao decisao: "
        "estado so hipotese_nao_validada. Nao e precario e nenhuma cobranca o le (KAM-059).'"
    )

    rls.enable_tenant_rls("module_cost_ledger")
    op.execute(f"REVOKE ALL ON {LEDGER} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON {PRECOS} FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT (tenant_id, modulo, rubrica, custo_usd, custo_minor, "
        "fx_aoa_per_usd, ref, idempotency_key, ocorrido_em) "
        f"ON {LEDGER} TO kamba_batch"
    )
    # A aplicacao le o seu proprio custo (a guarda de orcamento da imagem e o
    # `get_usage`), pela politica `tenant_iso`.
    op.execute(f"GRANT SELECT ON {LEDGER} TO kamba_app")
    # O `carregar-precos` substitui a tabela inteira (apaga e insere): sem
    # `UPDATE`, que nenhum caminho usa.
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {PRECOS} TO kamba_batch")
    op.execute("REVOKE ALL ON FUNCTION platform.module_cost_ledger_recusar() FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {ASSINATURA_GRAVAR} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ASSINATURA_GRAVAR} TO kamba_batch")

    # A consolidacao le o custo de imagem da `image_jobs` (KAM-120), que ate
    # aqui so a aplicacao lia. Leitura e mais nada: a tabela nao tem dado de
    # pessoa (as fotos vivem no STO).
    op.execute("GRANT SELECT ON platform.image_jobs TO kamba_batch")

    modulos_custo.criar_vistas()


def downgrade() -> None:
    modulos_custo.remover_vistas()
    op.execute("REVOKE SELECT ON platform.image_jobs FROM kamba_batch")
    rls.disable_tenant_rls("module_cost_ledger")
    op.execute(f"DROP FUNCTION {ASSINATURA_GRAVAR}")
    op.execute(f"DROP TRIGGER module_cost_ledger_sem_truncate ON {LEDGER}")
    op.execute(f"DROP TRIGGER module_cost_ledger_imutavel ON {LEDGER}")
    op.execute("DROP FUNCTION platform.module_cost_ledger_recusar()")
    op.execute(f"DROP TABLE {PRECOS}")
    op.execute(f"DROP TABLE {LEDGER}")

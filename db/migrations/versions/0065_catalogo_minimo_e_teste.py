"""Catalogo minimo e teste ponta a ponta: publicacao segura, is_test e onboarding_smoke (KAM-094).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `platform.conteudo_sha256_do_produto(categoria, nome)` — o `conteudo_sha256`
  do KAM-088 para um produto, **byte a byte** o do `conteudoSha256` de
  `packages/core-ts/src/screening/motor.ts`: o `sha256` do JSON
  `[categoria_declarada, [nome]]` sem espacos, que e a entrada do
  `SQL_POR_REANALISAR`. O `to_json(text)` do PostgreSQL escapa o mesmo conjunto
  que o `JSON.stringify` (aspas, barra invertida, os cinco escapes curtos e o
  resto abaixo de `0x20` em `\\u00xx` minusculo); o ensaio de base compara os
  dois sobre os mesmos casos, os dificeis incluidos.
* `platform.oferta_publicavel(tenant, sku, nome)` — a regra do
  `assertPublishable` (KAM-088) **na base**: `NULL` se o produto pode ser
  publicado com este nome; senao o motivo, `sem_decisao`, `bloqueada` ou
  `por_rever`. Le as decisoes do conteudo de agora, na versao de politica mais
  recente que as tem.
* o *trigger* `offer_terms_publicacao_segura` — a caixa da DoD «publicacao
  protegida por restricao de BD (nao so por convencao)».
* `conversations.is_test` — a conversa do teste ponta a ponta, fora das
  metricas, da golden e do Score.
* `platform.onboarding_smoke` — as tentativas do teste, para contar as tres
  falhas seguidas do criterio 5.

## O *trigger*, e os caminhos de escrita que ele deixa passar

A `offer_terms` e do KAM-043 e quem lhe escreve e o COM. Os cinco caminhos,
medidos em `services/com/src/`:

| Caminho | O que escreve | O que o *trigger* faz |
|---|---|---|
| `inserirNoTenant` (upsert de rascunho) | `INSERT` sem `estado` | nada: nasce `rascunho` |
| `SQL_ACTUALIZAR_TERMOS` | `nome` e termos | so com o nome **diferente** num `publicado`: sem decisao para o nome novo, o produto **sai** para `rascunho` (criterio 3) |
| `SQL_PUBLICAR` | `estado = 'publicado'` | sem decisao, **salta a linha**: zero linhas, que o `publishProduct` ja le como `VALIDATION_ERROR` |
| `SQL_AJUSTAR_STOCK`, `SQL_ALTERAR_OFERTA`, reservas | stock e preco | nada: nao tocam `estado` nem `nome` |
| `deleted_at` (retencao) | o *soft delete* | nada |

**Saltar a linha, e nao `23514`, na transicao para `publicado`.** O
`publishProduct` trata zero linhas como recusa de dominio e devolve-a no
`Resultado`; um `23514` era uma excepcao que o COM nao espera e que lhe
atravessava a porta. Um `INSERT` ja `publicado` de um papel de servico e que
recusa com `23514`: nenhum caminho do COM o faz, logo so o faz quem esta a
contornar o rascunho.

**O dono da tabela fica de fora**, e a razao e que ele pode desligar o
*trigger* (`ALTER TABLE ... DISABLE TRIGGER`): medi-lo nao acrescenta
barreira, e as sementes de ensaio (`db/tests_produtos`, `golden_search`,
`ensaio_idx`) inserem como dono ofertas ja publicadas. A barreira e para os
papeis de servico, que sao os que um defeito de aplicacao usa.

**O que nao decide.** Uma decisao gravada numa versao antiga da politica
continua a valer na base ate a re-analise do KAM-088 gravar a nova: a versao
corrente esta no codigo e nao na base. Mudar a categoria declarada do tenant
muda o `conteudo_sha256` de todos os produtos, e a base nao os retira por isso:
a contagem do catalogo minimo deixa de os contar, e a re-analise volta a
avalia-los. E a `origem = 'humano'` que o `kamba_app` pode inserir (0044)
continua a valer como recurso, como no `assertPublishable`: a desconfianca
dessa coluna e do KAM-092 para a categoria, e para o produto fica como achado.

## `onboarding_smoke`

Uma linha por tentativa. **A aplicacao abre, e so o lote fecha**: o `kamba_app`
insere o caso, o tenant e a janela (a pagina do dono carrega em «comecar»), e
o `resultado` nasce `pendente` porque a aplicacao nao tem a coluna; o
`kamba_batch` fecha-a, porque o mesmo passo marca o gate `e2e`, e um contexto
de tenant que fechasse o proprio teste como `ok` activava-se a si proprio — a
razao da 0058 para os gates. Uma tentativa fechada nao muda (*trigger*). O
`levou_a_fila` marca a falha que abriu o `review_case`: a contagem das falhas
seguidas recomeca depois dela.

## Descida

Larga o *trigger*, as tres funcoes, a tabela e a coluna, sem `CASCADE`. A
coluna `is_test` perde-se, e com ela a marca das conversas de teste: e estado
de medicao e nao prova.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0065"
#: **Provisoria.** O orquestrador do lote deu a `0065` sobre a `0064` (KAM-058),
#: com a `0060` a `0063` por fundir a frente; a base deste ramo vai na `0059`,
#: e e sobre ela que a cadeia se testa. Renumera-se na integracao.
down_revision = "0059"
branch_labels = None
depends_on = None

OFERTAS = "platform.offer_terms"
TENTATIVAS = "platform.onboarding_smoke"

#: As quatro causas de um teste falhado (`CAUSAS_DO_TESTE`, `activacao/contrato.ts`).
CAUSAS = ("'sem_inbound'", "'sem_resposta'", "'sem_entrega'", "'sem_consentimento'")

#: Os tres resultados de uma tentativa.
RESULTADOS = ("'pendente'", "'ok'", "'falhou'")

CONTEUDO = "platform.conteudo_sha256_do_produto(text, text)"
PUBLICAVEL = "platform.oferta_publicavel(uuid, text, text)"


def upgrade() -> None:
    _publicacao_segura()
    _conversa_de_teste()
    _tentativas()


def _publicacao_segura() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.conteudo_sha256_do_produto(p_categoria text, p_nome text)
          RETURNS bytea
          LANGUAGE sql
          IMMUTABLE
          STRICT
          SET search_path = pg_catalog
        AS $$
          SELECT sha256(convert_to(
            '[' || to_json(p_categoria)::text || ',[' || to_json(p_nome)::text || ']]',
            'UTF8'))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.oferta_publicavel(p_tenant_id uuid, p_sku text, p_nome text)
          RETURNS text
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_categoria text;
          v_sha       bytea;
          v_versao    text;
          v_humana    text;
        BEGIN
          SELECT c.sujeito_ref INTO v_categoria
            FROM platform.screening_decision c
           WHERE c.tenant_id = p_tenant_id AND c.sujeito_tipo = 'categoria'
           ORDER BY c.criado_at DESC, c.id DESC
           LIMIT 1;
          v_sha := platform.conteudo_sha256_do_produto(coalesce(v_categoria, ''), p_nome);

          SELECT d.versao_politica INTO v_versao
            FROM platform.screening_decision d
           WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
             AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
           ORDER BY d.criado_at DESC, d.id DESC
           LIMIT 1;
          IF NOT FOUND THEN
            RETURN 'sem_decisao';
          END IF;

          SELECT d.decisao INTO v_humana
            FROM platform.screening_decision d
           WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
             AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
             AND d.versao_politica = v_versao AND d.origem = 'humano'
           ORDER BY d.criado_at DESC, d.id DESC
           LIMIT 1;
          IF FOUND THEN
            RETURN CASE v_humana WHEN 'permitida' THEN NULL
                                 WHEN 'bloqueada' THEN 'bloqueada'
                                 ELSE 'por_rever' END;
          END IF;

          IF EXISTS (SELECT 1 FROM platform.screening_decision d
                      WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
                        AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
                        AND d.versao_politica = v_versao AND d.decisao = 'bloqueada') THEN
            RETURN 'bloqueada';
          END IF;
          IF EXISTS (SELECT 1 FROM platform.screening_decision d
                      WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
                        AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
                        AND d.versao_politica = v_versao AND d.decisao <> 'permitida') THEN
            RETURN 'por_rever';
          END IF;
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.offer_terms_publicacao_segura()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_motivo text;
        BEGIN
          IF NEW.estado <> 'publicado' THEN
            RETURN NEW;
          END IF;
          -- O dono da tabela pode desligar este trigger; medi-lo nao acrescenta
          -- barreira. Ver a nota da revisao.
          IF EXISTS (SELECT 1 FROM pg_roles r, pg_class c
                      WHERE r.rolname = current_user AND c.oid = TG_RELID
                        AND (r.rolsuper OR r.oid = c.relowner)) THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.estado = 'publicado'
             AND OLD.nome IS NOT DISTINCT FROM NEW.nome THEN
            RETURN NEW;
          END IF;

          v_motivo := platform.oferta_publicavel(NEW.tenant_id, NEW.sku, NEW.nome);
          IF v_motivo IS NULL THEN
            RETURN NEW;
          END IF;

          IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'oferta nao publicavel: %', v_motivo
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.estado = 'publicado' THEN
            -- O nome mudou num publicado e o nome novo nao tem decisao que o
            -- deixe: sai de publicado (criterio 3). O resto da escrita fica.
            NEW.estado := 'rascunho';
            RETURN NEW;
          END IF;
          -- A transicao para publicado sem decisao: zero linhas, que o COM le
          -- como recusa de dominio.
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER offer_terms_publicacao_segura
          BEFORE INSERT OR UPDATE OF estado, nome ON {OFERTAS}
          FOR EACH ROW EXECUTE FUNCTION platform.offer_terms_publicacao_segura()
        """
    )
    op.execute(f"ALTER TABLE {OFERTAS} ENABLE ALWAYS TRIGGER offer_terms_publicacao_segura")
    op.execute(f"REVOKE ALL ON FUNCTION {CONTEUDO} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {PUBLICAVEL} FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.offer_terms_publicacao_segura() FROM PUBLIC")
    # O *trigger* corre com os privilegios de quem escreve: os dois papeis que
    # escrevem a oferta precisam de poder chamar as duas funcoes.
    for papel in ("kamba_app", "kamba_batch"):
        op.execute(f"GRANT EXECUTE ON FUNCTION {CONTEUDO} TO {papel}")
        op.execute(f"GRANT EXECUTE ON FUNCTION {PUBLICAVEL} TO {papel}")


def _conversa_de_teste() -> None:
    op.execute(
        "ALTER TABLE platform.conversations ADD COLUMN is_test boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN platform.conversations.is_test IS "
        "'Conversa do teste ponta a ponta da activacao (KAM-094). Fora das metricas, "
        "da golden e do Score.'"
    )


def _tentativas() -> None:
    op.execute(
        f"""
        CREATE TABLE {TENTATIVAS} (
          id             uuid CONSTRAINT onboarding_smoke_pkey PRIMARY KEY
                         DEFAULT gen_random_uuid(),
          onboarding_id  uuid NOT NULL,
          tenant_id      uuid NOT NULL,
          iniciada_em    timestamptz NOT NULL DEFAULT now(),
          expira_em      timestamptz NOT NULL,
          resultado      text NOT NULL DEFAULT 'pendente'
                         CONSTRAINT onboarding_smoke_resultado_ck
                         CHECK (resultado IN ({", ".join(RESULTADOS)})),
          causa          text
                         CONSTRAINT onboarding_smoke_causa_ck
                         CHECK (causa IN ({", ".join(CAUSAS)})),
          fechada_em     timestamptz,
          levou_a_fila   boolean NOT NULL DEFAULT false,
          CONSTRAINT onboarding_smoke_janela_ck
            CHECK (expira_em > iniciada_em AND expira_em <= iniciada_em + interval '10 minutes'),
          CONSTRAINT onboarding_smoke_causa_do_resultado_ck
            CHECK ((resultado = 'falhou') = (causa IS NOT NULL)),
          CONSTRAINT onboarding_smoke_fecho_ck
            CHECK ((resultado = 'pendente') = (fechada_em IS NULL)),
          CONSTRAINT onboarding_smoke_fila_ck
            CHECK (NOT levou_a_fila OR resultado = 'falhou'),
          CONSTRAINT onboarding_smoke_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES platform.onboarding_case (id, tenant_id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX onboarding_smoke_caso_idx ON {TENTATIVAS} (onboarding_id, iniciada_em)"
    )
    op.execute(f"CREATE INDEX onboarding_smoke_tenant_idx ON {TENTATIVAS} (tenant_id)")
    op.execute(
        f"COMMENT ON TABLE {TENTATIVAS} IS "
        "'Tentativas do teste ponta a ponta assistido pelo dono (KAM-094). A aplicacao "
        "abre, so o lote fecha; uma tentativa fechada nao muda. levou_a_fila marca a "
        "falha que abriu o review_case.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.onboarding_smoke_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.resultado <> 'pendente'
             AND (NEW.resultado, NEW.causa, NEW.fechada_em)
                 IS DISTINCT FROM (OLD.resultado, OLD.causa, OLD.fechada_em) THEN
            RAISE EXCEPTION 'tentativa de teste ja fechada'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
          IF NEW.levou_a_fila AND NOT OLD.levou_a_fila AND NEW.resultado <> 'falhou' THEN
            RAISE EXCEPTION 'so uma falha leva o caso a fila'
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.levou_a_fila AND NOT NEW.levou_a_fila THEN
            RAISE EXCEPTION 'a ida a fila nao se desfaz'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER onboarding_smoke_transicao
          BEFORE UPDATE ON {TENTATIVAS}
          FOR EACH ROW EXECUTE FUNCTION platform.onboarding_smoke_transicao()
        """
    )
    op.execute(f"ALTER TABLE {TENTATIVAS} ENABLE ALWAYS TRIGGER onboarding_smoke_transicao")
    rls.enable_tenant_rls("onboarding_smoke")
    op.execute(f"REVOKE ALL ON {TENTATIVAS} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT (onboarding_id, tenant_id, iniciada_em, expira_em) "
        f"ON {TENTATIVAS} TO kamba_app"
    )
    op.execute(
        f"GRANT SELECT, UPDATE (resultado, causa, fechada_em, levou_a_fila) "
        f"ON {TENTATIVAS} TO kamba_batch"
    )
    op.execute(f"GRANT SELECT ON {TENTATIVAS} TO kamba_audit")
    op.execute("REVOKE ALL ON FUNCTION platform.onboarding_smoke_transicao() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("onboarding_smoke")
    op.execute(f"DROP TABLE {TENTATIVAS}")
    op.execute("DROP FUNCTION platform.onboarding_smoke_transicao()")
    op.execute("ALTER TABLE platform.conversations DROP COLUMN is_test")
    op.execute(f"DROP TRIGGER offer_terms_publicacao_segura ON {OFERTAS}")
    op.execute("DROP FUNCTION platform.offer_terms_publicacao_segura()")
    op.execute(f"DROP FUNCTION {PUBLICAVEL}")
    op.execute(f"DROP FUNCTION {CONTEUDO}")

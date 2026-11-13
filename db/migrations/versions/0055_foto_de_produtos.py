"""Foto de produtos AI: platform.image_jobs e a finalidade imagem (KAM-120).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

* cria `platform.image_jobs` — um trabalho de melhoramento de uma foto do dono
  (`docs/tecnica/03` §17), do `pendente` ao `concluido` ou `falhado`, com a
  versao nova **ao lado** do original e nunca por cima dele;
* cria `platform.image_jobs_transicao()` e o *trigger* do mesmo nome, que
  recusa uma transicao de `estado` fora da tabela de
  `libs/py-core/src/kamba_core/foto/estados.py`, recusa qualquer alteracao a
  um `falhado`, so deixa mudar a `escolhida` num `concluido`, e recusa que o
  `custo_usd` desca;
* acrescenta **`imagem`** ao dominio de `platform.tenant_destinations.purpose`
  (a `0036`), que passa de treze a **catorze** valores. O bloco diz «destino
  `imagem:<provider>`» e nenhuma das treze serve o melhoramento de imagem: a
  `visao` e a extraccao de campos por um modelo de linguagem (o KAM-049), e
  notificar a APD de um tratamento com o nome de outro e o defeito que o
  ADR-008 existe para impedir.

## As divergencias do DDL do bloco, e a razao de cada uma

* **`origem_ref` e `versao_ref` em vez de `origem_asset_id` e
  `versao_asset_id`.** A unica tabela com `asset_id` e a `media_assets` da
  `0012`, presa a uma mensagem do WhatsApp (`wamid`, `contact_id` e
  `conversation_id` NOT NULL); a foto que o dono melhora vem do Catalogo AI
  (`catalog_ingestions.media_ref`) ou do painel, e nenhuma das duas tem linha
  la. As duas colunas sao chaves do STO **do proprio tenant**, com o mesmo
  `starts_with` da `catalog_ingestions_media_ref_ck`, e a versao numa classe
  propria (`foto`).
* **`custo_usd numeric(10, 6)` em vez de `custo_minor bigint`.** O preco de
  referencia de um recorte e 0,018 USD (E5): em centimos inteiros nao cabe, e o
  precedente do mesmo dado e o `catalog_ingestions.custo_llm_usd` e o
  `dat.llm_call_log.custo_usd`. E custo de fornecedor, nao dinheiro de cliente
  nem de tenant, que e o que a regra do `*_minor` cobre. A decisao fica escrita
  no bloco, e devolvida a quem escreveu o criterio.
* **`motivo`**, que o bloco nao tem: o `bloqueada_gate` e retomavel e o
  `falhado` e final, e o dono precisa de saber se lhe pedem outra foto (rostos
  ou matriculas) ou se o problema e nosso (fornecedor). O `CHECK` amarra cada
  motivo ao seu estado.
* **`sintetica`**, porque o processamento corre depois do pedido e fora dele:
  a regra «em *staging* so imagens sinteticas» precisa de saber, no
  trabalhador, o que o pedido declarou.
* **`gerado_por_ia`** e coluna **gerada** (`operacao = 'variacao_lifestyle'`):
  a marca do bloco («versoes geradas levam `gerado_por_ia=true`») nao pode
  ficar mal escrita porque ninguem a escreve.
* **`escolhida`**: o dono escolhe a versao «por botao», e o original e o que
  fica enquanto ele nao escolher. So um `concluido` pode ser escolhido, e so
  **um** por original (`image_jobs_escolhida_uq`, unico e parcial).
* **O `motivo` com `IS NOT NULL` dentro do `image_jobs_motivo_ck`**: um `CHECK`
  que avalia a NULL passa, e `NULL IN (…)` e NULL — sem a guarda, um
  `bloqueada_gate` ou um `falhado` sem motivo entrava (achado da medicao do
  gate 8).
* **`latencia_ms`**, para o p50/p95 do *bake-off*, e **`aviso_at`**, o registo
  do aviso da primeira utilizacao («esta foto vai ser processada por servico de
  IA no estrangeiro»).
* **`versao`** e **`atualizado_at`**, do *trigger*, pela licao da `0050`: o
  repositorio escreve contra a versao lida, e dois trabalhadores que recebam o
  mesmo trabalho (a fila e «pelo menos uma vez») nao se sobrepoem em silencio.

## Privilegios

O `kamba_app` le, insere a identidade do pedido e actualiza o resultado, menos a
`versao` e o `atualizado_at`. **Nao tem `DELETE`**: o original e a versao vivem
no STO e expiram pelo `retain_until`; a linha sai com a relacao do tenant
(KAM-071).

## A cadeia

`0055` sobre a `0051`, que e a cabeca da `main` quando este ramo nasceu: o
numero e **provisorio** e e o da integracao do lote, que o da por extenso (a
`0052`, a `0053` e a `0054` sao de tres PR abertos). Renumerar e mudar o nome
do ficheiro, o `revision` e o `down_revision`, e mais nada: os ensaios
encontram esta revisao pelo *glob* `*_foto_de_produtos.py`.

## O `downgrade`

Larga o *trigger*, a funcao, a politica e a tabela, sem `CASCADE`, e repoe o
dominio de treze. **Recusa-se se houver linhas de `tenant_destinations` com
`purpose = 'imagem'`**, como a `0047` com o `screening`: sao registos de uma
decisao de transferencia e nao se apagam para descer. As linhas de
`image_jobs` vao com a tabela: uma base onde se desce esta revisao e de ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0055"
down_revision = "0051"
branch_labels = None
depends_on = None

TABELA = "platform.image_jobs"

#: Os cinco estados do bloco, como literais de SQL. Copiados de
#: `kamba_core.foto.estados` e nao importados: uma revisao nao importa codigo
#: da aplicacao. Ja entre apostrofos, pela razao da `0015`: e a forma que o
#: *gate* 3b resolve.
ESTADOS_DO_TRABALHO = (
    "'pendente'",
    "'a_processar'",
    "'concluido'",
    "'bloqueada_gate'",
    "'falhado'",
)

#: As quatro operacoes do criterio 1. A `variacao_lifestyle` e a unica
#: generativa, e e desligada por omissao na configuracao, nao aqui.
OPERACOES_DE_IMAGEM = (
    "'cutout'",
    "'fundo_simples'",
    "'luz_basica'",
    "'variacao_lifestyle'",
)

#: Os motivos de um `bloqueada_gate`: retomaveis, porque o que falta e uma
#: autorizacao, uma carta ou um detector a responder.
MOTIVOS_DO_BLOQUEIO = (
    "'sem_destino'",
    "'so_sinteticas'",
    "'sem_carta'",
    "'minimizacao'",
)

#: Os motivos de um `falhado`: finais. `dados_pessoais` pede outra foto ao dono
#: (rostos, matriculas, documentos ou ecras); `formato` tambem; `fornecedor` e
#: `resultado_invalido` sao do nosso lado e mantem o original.
MOTIVOS_DA_FALHA = (
    "'dados_pessoais'",
    "'formato'",
    "'fornecedor'",
    "'resultado_invalido'",
)

#: O dominio inteiro do `motivo`, as oito, por extenso: o *gate* 3b le o
#: dominio de uma coluna num `CHECK (coluna IN (…))` e nao numa disjuncao. O
#: `image_jobs_motivo_ck` e que amarra cada um ao seu estado.
MOTIVOS_DO_TRABALHO = (
    "'sem_destino'",
    "'so_sinteticas'",
    "'sem_carta'",
    "'minimizacao'",
    "'dados_pessoais'",
    "'formato'",
    "'fornecedor'",
    "'resultado_invalido'",
)

#: As **catorze** finalidades de transferencia: as treze da `0036` e a `imagem`.
#: Por ordem alfabetica, como la.
FINALIDADES_DE_TRANSFERENCIA = (
    "'alojamento'",
    "'canal'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'imagem'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: As treze da `0036`, para o `downgrade`. Por extenso e nao filtradas da de
#: cima: o *gate* 3b nao le SQL gerado por *generator*.
FINALIDADES_DA_0036 = (
    "'alojamento'",
    "'canal'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: A forma de um fornecedor, a mesma do `tenant_destinations_provider_ck`.
FORMA_DO_FORNECEDOR = "^[a-z][a-z0-9_-]{1,62}$"

#: A tabela de transicoes, igual a `estados.TRANSICOES`: o ensaio de base
#: compara as 25 combinacoes com a do modulo.
TRANSICOES_SQL = """
               (OLD.estado = 'pendente' AND NEW.estado IN
                 ('a_processar', 'bloqueada_gate', 'falhado'))
            OR (OLD.estado = 'a_processar' AND NEW.estado IN
                 ('concluido', 'bloqueada_gate', 'falhado'))
            OR (OLD.estado = 'bloqueada_gate' AND NEW.estado IN ('a_processar', 'falhado'))
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABELA} (
          image_job_id     uuid CONSTRAINT image_jobs_pkey PRIMARY KEY
                           DEFAULT gen_random_uuid(),
          tenant_id        uuid NOT NULL
                           CONSTRAINT image_jobs_tenant_fk REFERENCES platform.tenants (id),
          origem_ref       text NOT NULL,
          versao_ref       text,
          operacao         text NOT NULL
                           CONSTRAINT image_jobs_operacao_ck
                           CHECK (operacao IN ({", ".join(OPERACOES_DE_IMAGEM)})),
          provider         text NOT NULL
                           CONSTRAINT image_jobs_provider_ck CHECK (provider ~ '{FORMA_DO_FORNECEDOR}'),
          estado           text NOT NULL DEFAULT 'pendente'
                           CONSTRAINT image_jobs_estado_ck
                           CHECK (estado IN ({", ".join(ESTADOS_DO_TRABALHO)})),
          motivo           text
                           CONSTRAINT image_jobs_motivo_dominio_ck
                           CHECK (motivo IN ({", ".join(MOTIVOS_DO_TRABALHO)})),
          idempotency_key  text NOT NULL
                           CONSTRAINT image_jobs_idempotency_key_ck
                           CHECK (length(idempotency_key) BETWEEN 1 AND 200),
          sintetica        boolean NOT NULL DEFAULT false,
          gerado_por_ia    boolean NOT NULL
                           GENERATED ALWAYS AS (operacao = 'variacao_lifestyle') STORED,
          escolhida        boolean NOT NULL DEFAULT false,
          custo_usd        numeric(10, 6) NOT NULL DEFAULT 0
                           CONSTRAINT image_jobs_custo_ck CHECK (custo_usd >= 0),
          latencia_ms      integer
                           CONSTRAINT image_jobs_latencia_ck CHECK (latencia_ms >= 0),
          aviso_at         timestamptz,
          versao           integer NOT NULL DEFAULT 0,
          criado_at        timestamptz NOT NULL DEFAULT now(),
          atualizado_at    timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT image_jobs_idempotency_uq UNIQUE (tenant_id, idempotency_key),
          CONSTRAINT image_jobs_origem_ref_ck
            CHECK (starts_with(origem_ref, 't/' || tenant_id::text || '/')),
          CONSTRAINT image_jobs_versao_ref_ck
            CHECK (starts_with(versao_ref, 't/' || tenant_id::text || '/foto/')),
          CONSTRAINT image_jobs_motivo_ck
            CHECK (
              (estado = 'bloqueada_gate' AND motivo IS NOT NULL
                 AND motivo IN ({", ".join(MOTIVOS_DO_BLOQUEIO)}))
              OR (estado = 'falhado' AND motivo IS NOT NULL
                 AND motivo IN ({", ".join(MOTIVOS_DA_FALHA)}))
              OR (estado NOT IN ('bloqueada_gate', 'falhado') AND motivo IS NULL)
            ),
          CONSTRAINT image_jobs_concluido_ck
            CHECK (estado <> 'concluido' OR (versao_ref IS NOT NULL AND latencia_ms IS NOT NULL)),
          CONSTRAINT image_jobs_escolhida_ck
            CHECK (NOT escolhida OR estado = 'concluido')
        )
        """
    )
    # A fila humana: o que espera por um destino autorizado, uma carta ou o
    # detector.
    op.execute(
        f"CREATE INDEX image_jobs_bloqueados_idx ON {TABELA} (tenant_id, criado_at) "
        "WHERE estado = 'bloqueada_gate'"
    )
    # Uma versao escolhida por original: o botao do dono escolhe **uma**, e o
    # `escolher` desmarca a anterior antes de marcar a nova.
    op.execute(
        f"CREATE UNIQUE INDEX image_jobs_escolhida_uq ON {TABELA} (tenant_id, origem_ref) "
        "WHERE escolhida"
    )
    op.execute(
        f"COMMENT ON TABLE {TABELA} IS "
        "'Foto de produtos AI (KAM-120): um melhoramento de uma foto do dono. "
        "origem_ref e versao_ref sao chaves do STO do proprio tenant; o original "
        "nunca e substituido, e a versao so conta quando o dono a escolhe. Nada "
        "sai sem destino imagem com apd_ref, sem EXIF e sem rostos ou matriculas. "
        "Transicoes de estado impostas por trigger.'"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.image_jobs_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.estado = 'falhado' THEN
            RAISE EXCEPTION 'image_jobs falhado e final: a linha nao muda'
              USING ERRCODE = '23514';
          END IF;
          IF OLD.estado = 'concluido' AND (
               NEW.estado IS DISTINCT FROM OLD.estado
               OR NEW.versao_ref IS DISTINCT FROM OLD.versao_ref
               OR NEW.provider IS DISTINCT FROM OLD.provider
               OR NEW.custo_usd IS DISTINCT FROM OLD.custo_usd
               OR NEW.latencia_ms IS DISTINCT FROM OLD.latencia_ms
               OR NEW.motivo IS DISTINCT FROM OLD.motivo
          ) THEN
            RAISE EXCEPTION 'image_jobs concluido: so a escolha do dono muda'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.custo_usd < OLD.custo_usd THEN
            RAISE EXCEPTION 'custo_usd nao desce: % -> %', OLD.custo_usd, NEW.custo_usd
              USING ERRCODE = '23514';
          END IF;
          IF NEW.estado IS DISTINCT FROM OLD.estado AND NOT (
               {TRANSICOES_SQL}
          ) THEN
            RAISE EXCEPTION 'transicao de image_jobs recusada: % -> %',
              OLD.estado, NEW.estado USING ERRCODE = '23514';
          END IF;
          NEW.versao := OLD.versao + 1;
          NEW.atualizado_at := now();
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER image_jobs_transicao
          BEFORE UPDATE ON {TABELA}
          FOR EACH ROW EXECUTE FUNCTION platform.image_jobs_transicao()
        """
    )

    rls.enable_tenant_rls("image_jobs")
    op.execute(f"REVOKE ALL ON {TABELA} FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT (image_job_id, tenant_id, origem_ref, operacao, provider, "
        "idempotency_key, sintetica, aviso_at), "
        "UPDATE (estado, motivo, provider, versao_ref, custo_usd, latencia_ms, escolhida) "
        f"ON {TABELA} TO kamba_app"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.image_jobs_transicao() FROM PUBLIC")

    # A finalidade `imagem` no dominio da `0036`.
    op.execute(
        "ALTER TABLE platform.tenant_destinations "
        "DROP CONSTRAINT tenant_destinations_purpose_ck"
    )
    op.execute(
        f"""
        ALTER TABLE platform.tenant_destinations
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({", ".join(FINALIDADES_DE_TRANSFERENCIA)}))
        """
    )


def downgrade() -> None:
    # Uma linha `imagem` e o registo de uma decisao sobre uma transferencia
    # (contrato, `apd_ref`), e nao se apaga para descer: recusa-se, como a
    # `0047` com o `screening`. A contagem corre sem a `FORCE`, porque o dono da
    # tabela tambem esta sujeito a politica e veria zero.
    op.execute("ALTER TABLE platform.tenant_destinations NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql("SELECT count(*) FROM platform.tenant_destinations WHERE purpose = 'imagem'")
        .scalar_one()
    )
    op.execute("ALTER TABLE platform.tenant_destinations FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da foto_de_produtos recusado: ha {linhas} destino(s) com "
            "purpose imagem, e o dominio da 0036 nao os aceita. Sao registos de "
            "uma decisao de transferencia: exporte-os e decida antes de descer."
        )
    op.execute(
        "ALTER TABLE platform.tenant_destinations "
        "DROP CONSTRAINT tenant_destinations_purpose_ck"
    )
    op.execute(
        f"""
        ALTER TABLE platform.tenant_destinations
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({", ".join(FINALIDADES_DA_0036)}))
        """
    )
    rls.disable_tenant_rls("image_jobs")
    op.execute(f"DROP TRIGGER image_jobs_transicao ON {TABELA}")
    op.execute("DROP FUNCTION platform.image_jobs_transicao()")
    op.execute(f"DROP TABLE {TABELA}")

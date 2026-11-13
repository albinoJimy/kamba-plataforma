"""Catalogo AI: platform.catalog_ingestions, RLS FORCE e transicoes por trigger (KAM-049).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `platform.catalog_ingestions` — uma linha por foto que o dono manda, do
  `recebida` ao `publicada` (`docs/tecnica/03` §8.3), com o que a visao extraiu
  campo a campo (`extraido`: valor, confianca, fonte, confirmado, corrigido),
  as perguntas feitas, a `categoria_restrita` do screening e o custo de LLM;
* `platform.catalog_ingestions_transicao()` e o *trigger* do mesmo nome, que
  recusa uma transicao de `estado` fora da tabela de
  `libs/py-core/src/kamba_core/catalogo/estados.py`, recusa que as perguntas
  desçam e recusa qualquer alteracao a uma linha `publicada` ou `descartada`.
  O ensaio de base confronta as 81 combinacoes com a tabela do Python.

## As divergencias do DDL do §8.3, e a razao de cada uma

* **`categoria_restrita`**, que o §8.3 nao tem e o criterio 7 exige
  («`categoria_restrita` preenchida»). Forma `^[a-z0-9_]{1,60}$` (o `id` da
  entrada da politica do KAM-088, ou uma regra sintetica do motor); a lista nao
  se fecha aqui porque a politica e versionada sem revisao de base.
* **`confirmado_at` e `confirmado_por`**: a `OwnerConfirmation` da etapa 9
  (quem e quando), para que `publicada` sem confirmacao seja recusada **pela
  base** e nao so pelo Python (`catalog_ingestions_publicada_ck`).
* **`media_ref` presa ao tenant da linha**: `starts_with(media_ref,
  't/' || tenant_id || '/catalogo/')`. E a chave do STO (KAM-011), e com isto
  nem uma URL da Meta nem a chave de outro tenant cabem na coluna.
* **`custo_llm_usd NOT NULL DEFAULT 0`**: o §8.3 deixa-o anulavel, e o
  criterio 9 soma-o «incluindo repeticoes» — um nulo numa soma e um custo que
  desaparece. **Fica `numeric` e nao unidade menor inteira**, pelo precedente
  do mesmo dado: o custo de LLM em USD e `dat.llm_call_log.custo_usd
  numeric(12, 6)` desde a `0023`, e este e a soma dessas linhas. Nao e dinheiro
  de cliente nem de tenant, que e o que a regra do `*_minor` cobre.
* **`perguntas_feitas BETWEEN 0 AND 12`** em vez de `<= 12`: um negativo nao e
  um numero de perguntas.
* **`versao`**, que o *trigger* sobe em cada escrita (e o `atualizado_at`, que
  ele tambem poe): o repositorio escreve **contra a versao lida**. A primeira
  versao escrevia contra o estado, e a revisao adversarial mostrou o custo —
  uma correcção do dono entre a leitura e a escrita da confirmacao era
  publicada com a confirmacao da versao anterior, e duas respostas no mesmo
  estado perdiam a primeira em silencio.
* **`ultima_mensagem_id`**: o identificador da ultima resposta do dono que a
  ingestao processou. A entrega do WhatsApp e «pelo menos uma vez», e uma
  resposta reentregue nao pode voltar a contar perguntas.

## Privilegios

O `kamba_app` le, insere (so a identidade da foto) e actualiza o resto, **menos**
a `versao` e o `atualizado_at`, que sao do *trigger*. **Nao tem `DELETE`**: uma
ingestao descarta-se pelo estado, e a purga e da retencao (KAM-071), que hoje
classifica a tabela na relacao com o tenant.

**O que isto nao separa, dito:** o `kamba_app` escreve o `estado` e a
`categoria_restrita`, pelo que a base nao distingue a aplicacao do T&S. A
decisao humana do screening nao vive aqui: e a `screening_decision` do KAM-088,
e o `retomar` volta a perguntar ao screening em vez de a ler desta linha. Nenhum
outro papel le a tabela; uma leitura transversal da fila para o T&S e do
KAM-119.

## A cadeia

**O numero e provisorio.** A cadeia do lote e `0050` (KAM-197), esta e `0052`
(KAM-194), e o numero final da-o a integracao pela ordem de quem funde.
Ate la o `down_revision` e a cabeca da `main` (`0049`), para que o ramo se
meca sozinho. Renumerar e mudar o nome do ficheiro, o `revision` e o
`down_revision`, e mais nada: nenhum outro ficheiro deste ticket escreve o
numero desta revisao como literal (os ensaios descobrem-na pelo *glob*
`*_catalogo_ai.py`, e as listas do `db/tests/base.py` chamam-se pelo nome da
tabela e nao pelo numero).

## O `downgrade`

Larga o *trigger*, a funcao, a politica e a tabela, sem `CASCADE`. **Apaga as
ingestoes**: uma base onde se desce esta revisao e de ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0051"
down_revision = "0049"
branch_labels = None
depends_on = None

TABELA = "platform.catalog_ingestions"

#: Os nove estados do §8.3, como literais de SQL. Copiados de
#: `kamba_core.catalogo.estados` e nao importados: uma revisao nao importa
#: codigo da aplicacao. Por extenso, e nao gerados, para o gate 3b os ler.
LITERAIS_DE_ESTADO = (
    "'recebida', 'rejeitada_qualidade', 'em_extraccao', 'a_perguntar', "
    "'rascunho', 'publicada', 'bloqueada_gate', 'bloqueada_categoria', "
    "'descartada'"
)

#: A tabela de transicoes, igual a `estados.TRANSICOES`: o ensaio de base
#: compara as 81 combinacoes com a do modulo.
TRANSICOES_SQL = """
               (OLD.estado = 'recebida' AND NEW.estado IN
                 ('rejeitada_qualidade', 'bloqueada_gate', 'em_extraccao', 'descartada'))
            OR (OLD.estado = 'rejeitada_qualidade' AND NEW.estado IN ('descartada'))
            OR (OLD.estado = 'bloqueada_gate' AND NEW.estado IN ('em_extraccao', 'descartada'))
            OR (OLD.estado = 'em_extraccao' AND NEW.estado IN
                 ('a_perguntar', 'rascunho', 'bloqueada_categoria', 'descartada'))
            OR (OLD.estado = 'a_perguntar' AND NEW.estado IN
                 ('rascunho', 'bloqueada_categoria', 'descartada'))
            OR (OLD.estado = 'rascunho' AND NEW.estado IN
                 ('a_perguntar', 'publicada', 'bloqueada_categoria', 'descartada'))
            OR (OLD.estado = 'bloqueada_categoria' AND NEW.estado IN
                 ('a_perguntar', 'rascunho', 'descartada'))
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABELA} (
          id                 uuid CONSTRAINT catalog_ingestions_pkey PRIMARY KEY
                             DEFAULT gen_random_uuid(),
          tenant_id          uuid NOT NULL
                             CONSTRAINT catalog_ingestions_tenant_fk REFERENCES platform.tenants (id),
          media_ref          text NOT NULL,
          media_id_meta      text
                             CONSTRAINT catalog_ingestions_media_id_ck
                             CHECK (length(media_id_meta) BETWEEN 1 AND 256),
          phash              bytea
                             CONSTRAINT catalog_ingestions_phash_ck CHECK (octet_length(phash) = 8),
          estado             text NOT NULL DEFAULT 'recebida'
                             CONSTRAINT catalog_ingestions_estado_ck CHECK (estado IN ({LITERAIS_DE_ESTADO})),
          extraido           jsonb NOT NULL DEFAULT '{{}}'
                             CONSTRAINT catalog_ingestions_extraido_ck CHECK (jsonb_typeof(extraido) = 'object'),
          campos_em_falta    text[] NOT NULL DEFAULT '{{}}',
          perguntas_feitas   smallint NOT NULL DEFAULT 0
                             CONSTRAINT catalog_ingestions_perguntas_ck CHECK (perguntas_feitas BETWEEN 0 AND 12),
          categoria_restrita text
                             CONSTRAINT catalog_ingestions_categoria_ck
                             CHECK (categoria_restrita ~ '^[a-z0-9_]{{1,60}}$'),
          sku                text
                             CONSTRAINT catalog_ingestions_sku_ck CHECK (length(sku) BETWEEN 1 AND 64),
          custo_llm_usd      numeric(10, 6) NOT NULL DEFAULT 0
                             CONSTRAINT catalog_ingestions_custo_ck CHECK (custo_llm_usd >= 0),
          confirmado_at      timestamptz,
          confirmado_por     text
                             CONSTRAINT catalog_ingestions_confirmado_por_ck
                             CHECK (length(confirmado_por) BETWEEN 1 AND 200),
          ultima_mensagem_id text
                             CONSTRAINT catalog_ingestions_ultima_mensagem_ck
                             CHECK (length(ultima_mensagem_id) BETWEEN 1 AND 256),
          versao             integer NOT NULL DEFAULT 0,
          criado_at          timestamptz NOT NULL DEFAULT now(),
          atualizado_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT catalog_ingestions_media_uq UNIQUE (tenant_id, media_id_meta),
          CONSTRAINT catalog_ingestions_media_ref_ck
            CHECK (starts_with(media_ref, 't/' || tenant_id::text || '/catalogo/')),
          CONSTRAINT catalog_ingestions_bloqueada_ck
            CHECK (estado <> 'bloqueada_categoria' OR categoria_restrita IS NOT NULL),
          CONSTRAINT catalog_ingestions_publicada_ck
            CHECK (estado <> 'publicada' OR (categoria_restrita IS NULL AND sku IS NOT NULL
                   AND confirmado_at IS NOT NULL AND confirmado_por IS NOT NULL))
        )
        """
    )
    # A pergunta «e o mesmo produto?» (criterio 1).
    op.execute(
        f"CREATE INDEX catalog_ingestions_phash_idx ON {TABELA} (tenant_id, phash) "
        "WHERE phash IS NOT NULL"
    )
    # A fila humana: o que espera por um destino autorizado ou pelo T&S.
    op.execute(
        f"CREATE INDEX catalog_ingestions_fila_idx ON {TABELA} (tenant_id, estado, criado_at) "
        "WHERE estado IN ('bloqueada_gate', 'bloqueada_categoria')"
    )
    op.execute(
        f"COMMENT ON TABLE {TABELA} IS "
        "'Catalogo AI (KAM-049): uma foto do dono, da captura a publicacao. "
        "media_ref e a chave do STO do proprio tenant, nunca URL da Meta; EXIF e GPS "
        "saem antes do STO. extraido: campo -> valor, confianca, fonte, confirmado, "
        "corrigido. Nada publica sem confirmado_at e confirmado_por. Transicoes de "
        "estado impostas por trigger.'"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.catalog_ingestions_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.estado IN ('publicada', 'descartada') THEN
            RAISE EXCEPTION 'catalog_ingestions % e final: a linha nao muda', OLD.estado
              USING ERRCODE = '23514';
          END IF;
          IF NEW.perguntas_feitas < OLD.perguntas_feitas THEN
            RAISE EXCEPTION 'perguntas_feitas nao desce: % -> %',
              OLD.perguntas_feitas, NEW.perguntas_feitas USING ERRCODE = '23514';
          END IF;
          IF NEW.estado IS DISTINCT FROM OLD.estado AND NOT (
               {TRANSICOES_SQL}
          ) THEN
            RAISE EXCEPTION 'transicao de catalog_ingestions recusada: % -> %',
              OLD.estado, NEW.estado USING ERRCODE = '23514';
          END IF;
          -- A versao da linha e da base, e nao de quem escreve: sobe uma em
          -- cada escrita, e e contra ela que o repositorio escreve. Ninguem a
          -- pode baixar nem repetir, porque nenhum papel tem UPDATE nela.
          NEW.versao := OLD.versao + 1;
          NEW.atualizado_at := now();
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER catalog_ingestions_transicao
          BEFORE UPDATE ON {TABELA}
          FOR EACH ROW EXECUTE FUNCTION platform.catalog_ingestions_transicao()
        """
    )

    rls.enable_tenant_rls("catalog_ingestions")
    op.execute(f"REVOKE ALL ON {TABELA} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT (id, tenant_id, media_ref, media_id_meta, phash), "
        "UPDATE (estado, phash, extraido, campos_em_falta, perguntas_feitas, "
        "categoria_restrita, sku, custo_llm_usd, confirmado_at, confirmado_por, "
        f"ultima_mensagem_id) ON {TABELA} TO kamba_app"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.catalog_ingestions_transicao() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("catalog_ingestions")
    op.execute(f"DROP TRIGGER catalog_ingestions_transicao ON {TABELA}")
    op.execute("DROP FUNCTION platform.catalog_ingestions_transicao()")
    op.execute(f"DROP TABLE {TABELA}")

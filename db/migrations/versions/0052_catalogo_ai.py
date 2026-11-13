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
  desaparece.
* **`perguntas_feitas BETWEEN 0 AND 12`** em vez de `<= 12`: um negativo nao e
  um numero de perguntas.

## Privilegios

O `kamba_app` le, insere (so a identidade da foto) e actualiza o resto. **Nao
tem `DELETE`**: uma ingestao descarta-se pelo estado, e a purga e da retencao
(KAM-071), que hoje classifica a tabela na relacao com o tenant.

## A cadeia

**O numero e provisorio.** A cadeia do lote e `0050` (KAM-197), `0051`
(KAM-196) e esta, e o numero final da-o a integracao pela ordem de quem funde.
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

revision = "0052"
down_revision = "0049"
branch_labels = None
depends_on = None

TABELA = "platform.catalog_ingestions"

#: Os nove estados do §8.3. Copiados de `kamba_core.catalogo.estados` e nao
#: importados: uma revisao nao importa codigo da aplicacao.
ESTADOS = (
    "recebida",
    "rejeitada_qualidade",
    "em_extraccao",
    "a_perguntar",
    "rascunho",
    "publicada",
    "bloqueada_gate",
    "bloqueada_categoria",
    "descartada",
)

#: A tabela de transicoes, igual a `estados.TRANSICOES` (o ensaio compara).
TRANSICOES = {
    "recebida": ("rejeitada_qualidade", "bloqueada_gate", "em_extraccao", "descartada"),
    "rejeitada_qualidade": ("descartada",),
    "bloqueada_gate": ("em_extraccao", "descartada"),
    "em_extraccao": ("a_perguntar", "rascunho", "bloqueada_categoria", "descartada"),
    "a_perguntar": ("rascunho", "bloqueada_categoria", "descartada"),
    "rascunho": ("a_perguntar", "publicada", "bloqueada_categoria", "descartada"),
    "bloqueada_categoria": ("a_perguntar", "rascunho", "descartada"),
}


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def _transicoes_sql() -> str:
    return "\n            OR ".join(
        f"(OLD.estado = '{de}' AND NEW.estado IN ({_lista(para)}))" for de, para in TRANSICOES.items()
    )


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
                             CONSTRAINT catalog_ingestions_estado_ck CHECK (estado IN ({_lista(ESTADOS)})),
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
               {_transicoes_sql()}
          ) THEN
            RAISE EXCEPTION 'transicao de catalog_ingestions recusada: % -> %',
              OLD.estado, NEW.estado USING ERRCODE = '23514';
          END IF;
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
        f"atualizado_at) ON {TABELA} TO kamba_app"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.catalog_ingestions_transicao() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("catalog_ingestions")
    op.execute(f"DROP TRIGGER catalog_ingestions_transicao ON {TABELA}")
    op.execute("DROP FUNCTION platform.catalog_ingestions_transicao()")
    op.execute(f"DROP TABLE {TABELA}")

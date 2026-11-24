"""Categoria da oferta e a fonte do preco anomalo (KAM-209).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

1. **`offer_terms.categoria`**, texto anulavel, com o `CHECK
   offer_terms_categoria_ck` na lista fechada de
   `policy/categorias_de_produto.yaml` (decisao do fundador de 2026-11-21). A
   lista esta aqui **escrita**, e nao importada: uma revisao nao le ficheiros que
   mudam depois dela. O `libs/py-core/tests/test_categorias_de_produto.py` le a
   politica e recusa esta copia se divergir.

2. **A guarda na publicacao** (decisao do fundador de 2026-11-21: vale so na
   publicacao, transicao e `INSERT`): o *trigger*
   `offer_terms_categoria_na_publicacao`.

   | Escrita | Sem categoria |
   |---|---|
   | `INSERT` ja `publicado` | recusa, `23514` |
   | transicao para `publicado` (o `SQL_PUBLICAR`) | **salta a linha**: zero linhas, que o `publishProduct` ja le como recusa de dominio — a forma da `0080` |
   | `publicado` com categoria posta a nulo | recusa, `23514` |
   | `publicado` que ja era nulo e continua nulo | passa: e uma oferta de antes desta revisao, e fica como estava |

   As ofertas publicadas antes desta revisao **ficam nulas**, nao se avaliam, e a
   varredura conta-as. **O dono da tabela fica de fora**, pela razao da `0080`:
   pode desligar o *trigger*, e as sementes de ensaio inserem como dono ofertas
   ja publicadas.

3. **O `kamba_app` escreve a coluna**: `UPDATE (categoria)`. O `INSERT` ja e de
   tabela inteira desde a `0028`.

4. **A `fonte` no detalhe de um sinal de T&S**: o `ts_signal_detalhe_ck` da
   `0056` passa a admitir a chave `fonte`, que o `preco_anomalo` usa para o nome
   e a versao da fonte das referencias (`plataforma/1`, decisao do fundador de
   2026-11-21). As outras seis chaves ficam.

## O que nao faz

Nenhuma categoria se preenche nas ofertas que ja existem: inferi-la do nome era
escrever pelo dono o que o dono nao confirmou. A varredura do preco anomalo
(`packages/core-ts/src/trust/precos.ts`) le a coluna como `kamba_batch`, que ja
tem `SELECT` na tabela desde a `0028`: nenhum privilegio novo para ela.

## Descida

Recusa se houver um sinal com a chave `fonte`: a `ts_signal` e *append-only*, e o
`CHECK` antigo nao o admite. **A contagem corre com o `FORCE` desligado**, pela
licao do KAM-050: sob `FORCE` sem contexto um `count(*)` le zero. Depois larga o
*trigger*, a funcao, o privilegio e a coluna (com o `CHECK` dela), e devolve o
`ts_signal_detalhe_ck` a forma da `0056`. Sem `CASCADE`.

## Numero

`0088`, sobre a `0087` do KAM-208: a vaga que a coordenacao do lote 18 deu ao
KAM-209 a 2026-11-21 (fila 0084 KAM-236, 0085 KAM-122, 0086 KAM-233, 0087
KAM-208).
"""

from __future__ import annotations

from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

OFERTAS = "platform.offer_terms"
SINAIS = "platform.ts_signal"
GUARDA = "platform.offer_terms_categoria_na_publicacao()"

#: A lista fechada, a de `policy/categorias_de_produto.yaml` 1.0.0, escrita por
#: extenso para que o *gate* 3b a leia sem executar a revisao. O nulo passa sem
#: `IS NULL OR`: um `CHECK` que da nulo nao recusa.
CHECK_DA_CATEGORIA = (
    "categoria IN ('moda', 'mercearia', 'restauracao', 'beleza', "
    "'electronica', 'servicos', 'material_construcao', 'outra')"
)

#: O `ts_signal_detalhe_ck` da `0056`, e o desta revisao com a `fonte`.
DETALHE_DA_0056 = (
    "jsonb_typeof(detalhe) = 'object' AND (detalhe - ARRAY['order_id', 'coincidencia', "
    "'contagem', 'sku', 'versao_politica', 'pedidos']) = '{}'::jsonb"
)
DETALHE_COM_FONTE = (
    "jsonb_typeof(detalhe) = 'object' AND (detalhe - ARRAY['order_id', 'coincidencia', "
    "'contagem', 'sku', 'versao_politica', 'pedidos', 'fonte']) = '{}'::jsonb"
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {OFERTAS} ADD COLUMN categoria text "
        f"CONSTRAINT offer_terms_categoria_ck CHECK ({CHECK_DA_CATEGORIA})"
    )
    op.execute(
        f"COMMENT ON COLUMN {OFERTAS}.categoria IS "
        "'Categoria da oferta, da lista fechada de policy/categorias_de_produto.yaml (KAM-209). "
        "Nula nas ofertas publicadas antes da revisao 0088; a base nao publica sem ela. "
        "Dicionario 3.68.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.offer_terms_categoria_na_publicacao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF NEW.estado <> 'publicado' OR NEW.categoria IS NOT NULL THEN
            RETURN NEW;
          END IF;
          -- O dono da tabela pode desligar este trigger; medi-lo nao acrescenta
          -- barreira. Ver a nota da revisao.
          IF EXISTS (SELECT 1 FROM pg_roles r, pg_class c
                      WHERE r.rolname = current_user AND c.oid = TG_RELID
                        AND (r.rolsuper OR r.oid = c.relowner)) THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.estado = 'publicado' THEN
            IF OLD.categoria IS NULL THEN
              -- Publicada antes desta revisao: fica como estava.
              RETURN NEW;
            END IF;
            RAISE EXCEPTION 'oferta publicada sem categoria'
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'oferta publicada sem categoria'
              USING ERRCODE = 'check_violation';
          END IF;
          -- A transicao para publicado sem categoria: zero linhas, que o COM le
          -- como recusa de dominio.
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER offer_terms_categoria_na_publicacao
          BEFORE INSERT OR UPDATE OF estado, categoria ON {OFERTAS}
          FOR EACH ROW EXECUTE FUNCTION {GUARDA}
        """
    )
    op.execute(f"ALTER TABLE {OFERTAS} ENABLE ALWAYS TRIGGER offer_terms_categoria_na_publicacao")
    op.execute(f"REVOKE ALL ON FUNCTION {GUARDA} FROM PUBLIC")
    op.execute(f"GRANT UPDATE (categoria) ON {OFERTAS} TO kamba_app")

    op.execute(f"ALTER TABLE {SINAIS} DROP CONSTRAINT ts_signal_detalhe_ck")
    op.execute(f"ALTER TABLE {SINAIS} ADD CONSTRAINT ts_signal_detalhe_ck CHECK ({DETALHE_COM_FONTE})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {SINAIS} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $guarda$
        BEGIN
          IF EXISTS (SELECT 1 FROM {SINAIS} WHERE detalhe ? 'fonte') THEN
            RAISE EXCEPTION
              'downgrade da 0088 recusado: ha sinais de T&S com a chave fonte, e a '
              'ts_signal e append-only (KAM-097)'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
        END $guarda$
        """
    )
    op.execute(f"ALTER TABLE {SINAIS} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SINAIS} DROP CONSTRAINT ts_signal_detalhe_ck")
    op.execute(f"ALTER TABLE {SINAIS} ADD CONSTRAINT ts_signal_detalhe_ck CHECK ({DETALHE_DA_0056})")

    op.execute(f"REVOKE UPDATE (categoria) ON {OFERTAS} FROM kamba_app")
    op.execute(f"DROP TRIGGER offer_terms_categoria_na_publicacao ON {OFERTAS}")
    op.execute(f"DROP FUNCTION {GUARDA}")
    op.execute(f"ALTER TABLE {OFERTAS} DROP COLUMN categoria")

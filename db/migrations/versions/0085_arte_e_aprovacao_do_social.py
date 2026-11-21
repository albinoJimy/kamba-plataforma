"""Arte e aprovacao do social: transicoes, colunas da arte e da aprovacao, termos e a finalidade (KAM-122).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

1. **O gatilho `content_items_transicao`**, que faz da maquina de estados do
   item uma restricao da base (criterio 6: «0 itens `entregue` sem estado
   `aprovado`»). As arestas:

       rascunho            -> pendente_aprovacao, rejeitado, expirado
       pendente_aprovacao  -> aprovado, rejeitado, expirado
       aprovado            -> entregue, pendente_aprovacao (uma edicao invalida a aprovacao), rejeitado
       entregue, rejeitado, expirado   finais: a linha nao muda

   E duas regras que o grafo nao chega para dizer: **a legenda e a arte nao
   mudam num item `aprovado` ou `entregue`** sem que ele volte a
   `pendente_aprovacao` (criterio 5: a aprovacao fica ligada ao que o dono viu),
   e **a passagem a `aprovado` nao muda a legenda nem a arte na mesma
   instrucao**.
2. **As colunas da arte e da aprovacao em `platform.content_items`**:
   `arte_ref` (a chave do STO, `t/{tenant}/...`, presa ao tenant da linha por
   `CHECK`), `arte_sha256`, `arte_fundo` (`gerado` ou `gradiente`),
   `arte_tentativas` (0 a 3, criterio 9), `arte_custo_usd` (a soma das
   tentativas do fornecedor, o custo por item do ADR-018), `aprovacao_hash`
   (o `hash(legenda, arte, versao)` do criterio 5), `aprovado_at` e
   `entregue_at`. O `art_asset_id uuid` do bloco fica por usar: a arte e um
   objecto do STO, e a chave dele e texto (a decisao da `image_jobs` da `0054`).
3. **`platform.brand_profile.termos_entrega_at`**: a hora em que os termos sem
   garantia de exclusividade se mostraram, na primeira entrega (criterio 9).
4. **`geracao_de_imagem` em `tenant_destinations.purpose`**, que passa de
   dezassete a **dezoito** valores: a finalidade de transferencia do fundo
   gerado das artes (criterio 3). **Decisao do fundador de 2026-11-21, opcao A
   da D3 do bloco do KAM-122**, pelo precedente da `classificacao_de_conteudo`
   (`0079`): outro tratamento, outra finalidade no ADR-008 — um destino
   autorizado para a `imagem` (a melhoria da foto do produto, KAM-120) nao
   cobre a geracao de uma cena de raiz. A `v_transfer_audit` nao se recria,
   pela razao que a `0078` escreve.

## Os privilegios do `kamba_app`

O `UPDATE` das colunas novas, que o AGR escreve; nenhum `INSERT` novo (a arte e
a aprovacao chegam a um item que ja existe). Sem `DELETE` para ninguem.

## O `downgrade`

**Recusa-se com um destino `geracao_de_imagem`**, como a `0079`: e o registo
de uma decisao de transferencia, e nao se apaga para descer. Depois tira o
gatilho, as restricoes e as colunas. Os itens `aprovado` e `entregue` ficam,
porque o dominio da `0079` ja os tinha; perdem a prova da aprovacao, e uma base
onde se desce esta revisao e uma base de ensaio.

## Numero

`0085`, dada pela coordenacao do lote 17, sobre a `0084` do KAM-236.
"""

from __future__ import annotations

from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None

ITENS = "platform.content_items"
PERFIL = "platform.brand_profile"
DESTINOS = "platform.tenant_destinations"

#: As **dezoito** finalidades de transferencia: as dezassete da `0079` e a
#: `geracao_de_imagem`. Por ordem alfabetica, como la.
FINALIDADES_DE_TRANSFERENCIA = (
    "'alojamento'",
    "'canal'",
    "'classificacao_de_catalogo'",
    "'classificacao_de_condicoes'",
    "'classificacao_de_conteudo'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'geracao_de_imagem'",
    "'imagem'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: As dezassete da `0079`, para o `downgrade`. Por extenso e nao filtradas da de
#: cima: o *gate* 3b nao le SQL gerado por *generator*.
FINALIDADES_DA_0079 = (
    "'alojamento'",
    "'canal'",
    "'classificacao_de_catalogo'",
    "'classificacao_de_condicoes'",
    "'classificacao_de_conteudo'",
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

FUNDOS = ("'gerado'", "'gradiente'")

#: As arestas da maquina do item, **por extenso**: o *gate* 3b le o SQL das
#: revisoes sem as executar. O ensaio `services/agr/tests/test_social_aprovacao.py`
#: confronta-as com o `social/repositorio.py` (`TRANSICOES`).
TRANSICOES_SQL = """
               (OLD.estado = 'rascunho' AND NEW.estado IN ('pendente_aprovacao', 'rejeitado', 'expirado'))
            OR (OLD.estado = 'pendente_aprovacao' AND NEW.estado IN ('aprovado', 'rejeitado', 'expirado'))
            OR (OLD.estado = 'aprovado' AND NEW.estado IN ('entregue', 'pendente_aprovacao', 'rejeitado'))
"""
FINAIS_SQL = "'entregue', 'rejeitado', 'expirado'"

#: O que o `kamba_app` passa a mudar no item, alem das colunas da `0079`.
UPDATE_DO_ITEM = (
    "arte_ref",
    "arte_sha256",
    "arte_fundo",
    "arte_tentativas",
    "arte_custo_usd",
    "aprovacao_hash",
    "aprovado_at",
    "entregue_at",
)
UPDATE_DO_PERFIL = ("termos_entrega_at",)

#: A chave do STO (`kamba_core/storage/chave.py`), com o tenant da linha.
CHAVE_DO_STO = r"'^t/[0-9a-f-]{36}/[a-z][a-z0-9_]{1,31}/[0-9]{4}/(0[1-9]|1[0-2])/[0-9a-f-]{36}$'"
SHA256 = r"'^[0-9a-f]{64}$'"


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(valores)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {ITENS}
          ADD COLUMN arte_ref text
            CONSTRAINT content_items_arte_ref_ck
            CHECK (arte_ref IS NULL OR (arte_ref ~ {CHAVE_DO_STO}
                   AND left(arte_ref, 38) = 't/' || tenant_id::text)),
          ADD COLUMN arte_sha256 text
            CONSTRAINT content_items_arte_sha256_ck CHECK (arte_sha256 IS NULL OR arte_sha256 ~ {SHA256}),
          ADD COLUMN arte_fundo text
            CONSTRAINT content_items_arte_fundo_ck CHECK (arte_fundo IN ({_lista(FUNDOS)})),
          ADD COLUMN arte_tentativas smallint NOT NULL DEFAULT 0
            CONSTRAINT content_items_arte_tentativas_ck CHECK (arte_tentativas BETWEEN 0 AND 3),
          ADD COLUMN arte_custo_usd numeric(12, 6) NOT NULL DEFAULT 0
            CONSTRAINT content_items_arte_custo_ck CHECK (arte_custo_usd >= 0),
          ADD COLUMN aprovacao_hash text
            CONSTRAINT content_items_aprovacao_hash_ck CHECK (aprovacao_hash IS NULL OR aprovacao_hash ~ {SHA256}),
          ADD COLUMN aprovado_at timestamptz,
          ADD COLUMN entregue_at timestamptz
        """
    )
    op.execute(
        f"""
        ALTER TABLE {ITENS}
          ADD CONSTRAINT content_items_arte_completa_ck
            CHECK ((arte_ref IS NULL) = (arte_sha256 IS NULL) AND (arte_ref IS NULL) = (arte_fundo IS NULL)),
          ADD CONSTRAINT content_items_pendente_ck
            CHECK (estado <> 'pendente_aprovacao' OR (legenda IS NOT NULL AND arte_ref IS NOT NULL)),
          ADD CONSTRAINT content_items_aprovado_ck
            CHECK (estado NOT IN ('aprovado', 'entregue')
                   OR (legenda IS NOT NULL AND arte_ref IS NOT NULL
                       AND aprovacao_hash IS NOT NULL AND aprovado_at IS NOT NULL)),
          ADD CONSTRAINT content_items_entregue_ck
            CHECK ((estado = 'entregue') = (entregue_at IS NOT NULL))
        """
    )
    op.execute(f"ALTER TABLE {PERFIL} ADD COLUMN termos_entrega_at timestamptz")
    op.execute(
        f"""
        CREATE FUNCTION platform.content_items_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.estado IN ({FINAIS_SQL}) AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'content_items % e final: a linha nao muda', OLD.estado
              USING ERRCODE = '23514';
          END IF;
          IF NEW.estado IS DISTINCT FROM OLD.estado AND NOT ({TRANSICOES_SQL}) THEN
            RAISE EXCEPTION 'transicao de content_items recusada: % -> %',
              OLD.estado, NEW.estado USING ERRCODE = '23514';
          END IF;
          -- A aprovacao fica ligada ao que o dono viu: uma linha que fica (ou
          -- passa a) aprovado ou entregue nao muda a legenda, a arte nem o hash
          -- na mesma instrucao. Mudar e voltar a pendente_aprovacao.
          IF NEW.estado IN ('aprovado', 'entregue') AND (
               NEW.legenda IS DISTINCT FROM OLD.legenda
               OR NEW.arte_ref IS DISTINCT FROM OLD.arte_ref
               OR NEW.arte_sha256 IS DISTINCT FROM OLD.arte_sha256
               OR NEW.aprovacao_hash IS DISTINCT FROM OLD.aprovacao_hash
          ) THEN
            RAISE EXCEPTION 'a legenda e a arte de um item aprovado nao mudam sem nova aprovacao'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER content_items_transicao
          BEFORE UPDATE ON {ITENS}
          FOR EACH ROW EXECUTE FUNCTION platform.content_items_transicao()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.content_items_transicao() FROM PUBLIC")
    op.execute(f"GRANT UPDATE ({', '.join(UPDATE_DO_ITEM)}) ON {ITENS} TO kamba_app")
    op.execute(f"GRANT UPDATE ({', '.join(UPDATE_DO_PERFIL)}) ON {PERFIL} TO kamba_app")
    op.execute(f"ALTER TABLE {DESTINOS} DROP CONSTRAINT tenant_destinations_purpose_ck")
    op.execute(
        f"""
        ALTER TABLE {DESTINOS}
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({_lista(FINALIDADES_DE_TRANSFERENCIA)}))
        """
    )


def downgrade() -> None:
    # Uma linha `geracao_de_imagem` e o registo de uma decisao sobre uma
    # transferencia, e nao se apaga para descer: recusa-se **antes de tocar em
    # nada**, como a `0079`. A contagem corre sem a `FORCE`, porque o dono da
    # tabela tambem esta sujeito a politica e veria zero.
    op.execute(f"ALTER TABLE {DESTINOS} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.tenant_destinations WHERE purpose = 'geracao_de_imagem'"
        )
        .scalar_one()
    )
    op.execute(f"ALTER TABLE {DESTINOS} FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da arte_e_aprovacao_do_social recusado: ha {linhas} destino(s) com "
            "purpose geracao_de_imagem, e o dominio da social_do_dono nao os aceita. Sao "
            "registos de uma decisao de transferencia: exporte-os e decida antes de descer."
        )
    op.execute(f"ALTER TABLE {DESTINOS} DROP CONSTRAINT tenant_destinations_purpose_ck")
    op.execute(
        f"""
        ALTER TABLE {DESTINOS}
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({_lista(FINALIDADES_DA_0079)}))
        """
    )
    op.execute(f"REVOKE UPDATE ({', '.join(UPDATE_DO_PERFIL)}) ON {PERFIL} FROM kamba_app")
    op.execute(f"REVOKE UPDATE ({', '.join(UPDATE_DO_ITEM)}) ON {ITENS} FROM kamba_app")
    op.execute(f"DROP TRIGGER content_items_transicao ON {ITENS}")
    op.execute("DROP FUNCTION platform.content_items_transicao()")
    op.execute(f"ALTER TABLE {PERFIL} DROP COLUMN termos_entrega_at")
    op.execute(
        f"""
        ALTER TABLE {ITENS}
          DROP CONSTRAINT content_items_entregue_ck,
          DROP CONSTRAINT content_items_aprovado_ck,
          DROP CONSTRAINT content_items_pendente_ck,
          DROP CONSTRAINT content_items_arte_completa_ck,
          DROP COLUMN entregue_at,
          DROP COLUMN aprovado_at,
          DROP COLUMN aprovacao_hash,
          DROP COLUMN arte_custo_usd,
          DROP COLUMN arte_tentativas,
          DROP COLUMN arte_fundo,
          DROP COLUMN arte_sha256,
          DROP COLUMN arte_ref
        """
    )

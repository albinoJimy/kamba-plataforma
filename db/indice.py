"""O esquema `idx`: o indice de pesquisa por tenant e o `idx.candidatos` (KAM-061).

O SQL deste ticket vive **aqui** e nao na revisao, pela razao do `db/custo.py`:

* os ensaios de base de dados importam-no deste modulo em vez de o copiarem. Uma
  copia no ensaio passava verde no dia em que a revisao mudasse;
* a revisao chama `indice.criar()` e o *gate* 3b le o SQL **por aqui**: este
  ficheiro esta declarado em `ci/canon-lint.yaml` como modulo auxiliar de
  migracao, e o lint segue o corpo das funcoes ate as constantes que elas
  executam. Por isso cada instrucao e uma cadeia **literal**, sem *f-strings*.

**Mudar o que esta aqui e uma revisao nova**, que larga o objecto e chama a
versao nova; a revisao que o criou nao se reescreve. Os `CREATE` falham se o
objecto ja existir, pelo que uma alteracao neste modulo sem revisao nova nao
muda bases ja migradas — so as novas, e o *gate* 8 ve-o.

## A origem, e o que se adaptou

O DDL e o do `docs/tecnica/05` §4.1, §4.2 e §4.4 e a funcao e a do §6.2, **sem
alteracoes de semantica** (Detalhes Tecnicos do bloco). As adaptacoes, todas de
forma, e cada uma com a razao:

1. **`tenants` passa a `platform.tenants`**, nas duas FK e na porta `tn` da
   funcao. O SQL do documento e anterior ao esquema `platform` do
   `docs/tecnica/03` §5, e o bloco manda adaptar.
2. **As restricoes tem nome** (`search_doc_tenant_fk`, ...), como em todas as
   revisoes desde a `0001`: um nome gerado pelo PostgreSQL nao se cita num
   ensaio nem numa mensagem de erro.
3. **As tres sub-consultas dos ramos desempatam por `doc_id` antes do `LIMIT`**
   (`ORDER BY sc DESC, d.doc_id`). O §6.2 so desempata **fora** do `LIMIT`
   (`row_number() OVER (ORDER BY s.sc DESC, s.doc_id)`), e isso nao chega: com
   empates no `p_k`-esimo lugar, *quais* documentos passam o `LIMIT` e
   arbitrario — o defeito D5 do proprio §6.1, a uma escala menor. O criterio 6
   pede «20 execucoes devolvem a mesma lista (desempate por `doc_id`)», e e este
   desempate que o cumpre. A ordenacao **dentro** do conjunto que passa e a
   mesma do documento; muda so que empate no limite ja nao e sorteio.
4. **Tres formas de instrucao.** `CREATE FUNCTION` e `CREATE SCHEMA idx` sem
   `OR REPLACE` nem `IF NOT EXISTS`: numa revisao, um objecto que ja exista e
   erro e nao substituicao silenciosa. E `CREATE EXTENSION unaccent WITH SCHEMA
   public`, porque o `idx.f_unaccent` do proprio §4.1 chama
   `public.unaccent('public.unaccent'::regdictionary, ...)` — sem o esquema, a
   extensao ia para o primeiro do `search_path` do migrator.

**E o que o §4 nao tem e o bloco pede**, que nao e adaptacao mas acrescento: a
RLS das duas tabelas (criterio 3) — a `tenant_iso` intacta nas duas e, no
`termo_canonico`, a `termos_globais` so de leitura, pela forma da
`destinos_globais` do KAM-069 —, os `GRANT` e os comentarios.

## A pesquisa so le o que o contexto deixa

A funcao e `SECURITY INVOKER` (a omissao, e a forma do `db/rls.py` para quem le
tabelas com `FORCE`), pelo que a RLS de `idx.search_doc` **e** a de
`platform.tenants` aplicam-se a quem chama. Daqui sai o criterio 3 sem uma linha
a mais: sem `app.tenant_id`, a porta `tn` le zero tenants e a funcao devolve
zero linhas; com o contexto de A e `p_tenant = B`, a porta le zero tenants (a
RLS de `tenants` e por `id`) e a funcao devolve zero linhas. O `p_tenant` do
§6.2 fica na assinatura, e o isolamento **nao depende dele**.

## O que **nao** esta aqui, e de proposito

* **Nenhum indice ANN** (`hnsw`, `ivfflat`) sobre o `embedding` — PROP-IDX-1,
  §7.2. A salvaguarda anti-vazio do §7.3 so se escreve com o primeiro HNSW.
* **Nenhuma coluna de preco ou stock.** Preco e stock entram na resposta pelo
  *join* com a `platform.v_oferta_viva` (KAM-051), nunca pelo indice (ADR-007).
  O ensaio do criterio 4 varre o `information_schema` do esquema inteiro.
* **O `DROP EXTENSION` no `downgrade`.** As tres extensoes criam-se com
  `IF NOT EXISTS`, porque o `infra/compose/postgres/initdb` ja cria o `vector` e
  o `pg_trgm` e a `0028` ja cria o `pg_trgm`. Com a guarda, esta revisao **nao
  sabe se as criou**, e apaga-las arrancava-as por baixo de quem as tinha antes
  — o argumento do `db/tests_produtos/test_downgrade.py`, que vale igual aqui.

## Quem le e quem escreve

So o `kamba_app`, e so no seu tenant: le as duas tabelas, escreve o
`idx.search_doc` (o consumidor de `catalog.product_changed` e dos eventos de
estado do tenant corre como ele, dentro do `consumir` do KAM-006, que define o
contexto a partir do envelope) e executa a funcao. As entradas **globais** do
`idx.termo_canonico` (`tenant_id` nulo) sao legiveis por todos os tenants e nao
sao escritas por ninguem nesta revisao: leem-se pela politica `termos_globais`,
so de leitura, e o `WITH CHECK` da `tenant_iso` exige o tenant do contexto. Quem
cura o lexico global e o KAM-062.
"""

from __future__ import annotations

from typing import Final

from alembic import op

#: O esquema.
ESQUEMA: Final = "idx"

#: As duas tabelas, pelo nome qualificado.
SEARCH_DOC: Final = "idx.search_doc"
TERMO_CANONICO: Final = "idx.termo_canonico"

#: A funcao, com a assinatura que o `DROP FUNCTION` e o `GRANT` precisam.
CANDIDATOS: Final = "idx.candidatos"
ASSINATURA_DOS_CANDIDATOS: Final = (
    "idx.candidatos(uuid, text, text, halfvec, integer, real, real, real, integer)"
)

#: A configuracao de pesquisa textual do §4.1.
CONFIGURACAO_FTS: Final = "idx.kamba_pt"

#: As tres extensoes do §4.1. `vector` >= 0.8.7 (E4 §2.9: corrige o
#: *buffer overflow* do IVFFlat); a imagem do *gate* 8 e a do compose e
#: `pgvector/pgvector:0.8.7-pg18`.
EXTENSOES: Final = ("vector", "pg_trgm", "unaccent")

#: O limiar do `pg_trgm` que o chamador poe com `SET LOCAL` (§6.2, nota i). **E
#: proposta** (criterio 1): o valor final sai do dataset do KAM-064, e e o unico
#: numero dos ensaios T1-T4 que se pode afinar.
LIMIAR_DE_PALAVRA: Final = 0.45

#: A variavel do `pg_trgm` que o limiar ajusta.
PARAMETRO_DO_LIMIAR: Final = "pg_trgm.word_similarity_threshold"

#: Os pesos e o `k` do RRF por omissao (§6.2). INDICIO, a afinar no dataset.
PESOS_POR_OMISSAO: Final = {"sem": 0.5, "tri": 0.3, "fts": 0.2}
RRF_K_POR_OMISSAO: Final = 60
K_POR_OMISSAO: Final = 40

#: A expressao que proibe nomes de coluna no esquema (criterio 4 e §4.2, regra
#: dura a). Um nome que **contenha** qualquer destes e vermelho.
COLUNAS_PROIBIDAS: Final = r"(preco|price|stock|qtd)"

#: O tipo do `termo_canonico`, pelo §4.4. Lista fechada do `CHECK`.
TIPOS_DE_TERMO: Final = ("marca", "unidade", "sinonimo", "erro_comum", "stopword")

#: A origem do `termo_canonico`, pelo §4.4. Lista fechada do `CHECK`.
ORIGENS_DE_TERMO: Final = ("ops", "catalogo", "dataset", "tenant")

#: O papel da aplicacao: o unico com privilegios no esquema.
PAPEL_DA_APP: Final = "kamba_app"

SQL_EXTENSOES: Final = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public
"""

SQL_ESQUEMA: Final = """
CREATE SCHEMA idx
"""

SQL_F_UNACCENT: Final = """
CREATE FUNCTION idx.f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
"""

SQL_CONFIGURACAO_FTS: Final = """
CREATE TEXT SEARCH CONFIGURATION idx.kamba_pt (COPY = pg_catalog.portuguese);
ALTER TEXT SEARCH CONFIGURATION idx.kamba_pt
  ALTER MAPPING FOR hword, hword_part, word WITH public.unaccent, pg_catalog.portuguese_stem
"""

SQL_SEARCH_DOC: Final = """
CREATE TABLE idx.search_doc (
  doc_id           uuid        NOT NULL DEFAULT gen_random_uuid(),
  tenant_id        uuid        NOT NULL,
  -- O id opaco no COM. **Nunca** preco nem stock (ADR-007). Hoje e o `sku`
  -- (`platform.v_oferta_viva`, nota 1 da revisao 0037).
  product_ref      text        NOT NULL,
  -- A versao do dicionario PT-AO aplicada; reindexa quando muda (§4.4).
  norm_versao      integer     NOT NULL,
  -- Minusculas, sem acentos, marca e unidade canonicas (§5.1).
  nome_norm        text        NOT NULL,
  marca_canon      text,
  categoria_canon  text,
  descr_norm       text        NOT NULL DEFAULT '',
  -- Herdada do tenant, so para filtro grosseiro.
  zona             text,
  -- Publicado **e** tenant activo, mantida pelo consumidor de eventos. A
  -- funcao junta `platform.tenants` em cada chamada (dupla defesa, §4.3).
  visivel          boolean     NOT NULL DEFAULT true,
  -- *Opt-in* explicito da PME (Clusters).
  visivel_federado boolean     NOT NULL DEFAULT false,
  -- NULL => so modo lexical. A dimensao e a do modelo (§7.4); `halfvec(1024)`
  -- e provisorio ate ao KAM-063 (PROP-IDX-4).
  embedding        halfvec(1024),
  embedding_modelo text,
  fts tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('idx.kamba_pt'::regconfig, nome_norm), 'A')
     || setweight(to_tsvector('idx.kamba_pt'::regconfig, coalesce(marca_canon, '')), 'A')
     || setweight(to_tsvector('idx.kamba_pt'::regconfig, coalesce(categoria_canon, '')), 'B')
     || setweight(to_tsvector('idx.kamba_pt'::regconfig, descr_norm), 'C')) STORED,
  atualizado_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT search_doc_pkey PRIMARY KEY (doc_id),
  CONSTRAINT search_doc_tenant_fk
    FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
  CONSTRAINT search_doc_tenant_product_ref_uq UNIQUE (tenant_id, product_ref)
)
"""

#: Os tres indices do §4.2. **Nenhum ANN**: ver a nota do modulo.
SQL_INDICES_DO_SEARCH_DOC: Final = """
CREATE INDEX search_doc_fts_gin   ON idx.search_doc USING gin (fts);
CREATE INDEX search_doc_nome_trgm ON idx.search_doc USING gin (nome_norm gin_trgm_ops);
CREATE INDEX search_doc_tenant    ON idx.search_doc (tenant_id) WHERE visivel
"""

SQL_TERMO_CANONICO: Final = """
CREATE TABLE idx.termo_canonico (
  id           bigint      GENERATED ALWAYS AS IDENTITY,
  -- NULL = global; o do tenant prevalece (§4.4).
  tenant_id    uuid,
  tipo         text        NOT NULL,
  -- Minusculas, sem acentos.
  termo        text        NOT NULL,
  canonico     text        NOT NULL,
  peso         real        NOT NULL DEFAULT 1.0,
  origem       text        NOT NULL,
  activo       boolean     NOT NULL DEFAULT true,
  aprovado_por text,
  criado_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT termo_canonico_pkey PRIMARY KEY (id),
  CONSTRAINT termo_canonico_tenant_fk
    FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
  CONSTRAINT termo_canonico_tipo_ck
    CHECK (tipo IN ('marca', 'unidade', 'sinonimo', 'erro_comum', 'stopword')),
  CONSTRAINT termo_canonico_peso_ck CHECK (peso > 0 AND peso <= 1),
  CONSTRAINT termo_canonico_origem_ck
    CHECK (origem IN ('ops', 'catalogo', 'dataset', 'tenant'))
);
CREATE UNIQUE INDEX termo_canonico_uq
  ON idx.termo_canonico
     (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), tipo, termo)
  WHERE activo
"""

#: A RLS das duas tabelas (criterio 3). As duas levam a politica `tenant_iso`
#: do `db/rls.py`, intacta e escrita por extenso porque o *gate* 3b le cadeias
#: literais. O `termo_canonico` leva **uma segunda**, `termos_globais`, pela
#: forma da `destinos_globais` do KAM-069: `FOR SELECT USING (tenant_id IS
#: NULL)`. As duas sao permissivas e somam-se por `OR`, e e o `FOR SELECT` que
#: segura a barreira — com `ALL`, um tenant escrevia uma entrada global, que e
#: mudar o lexico de todas as lojas a partir do contexto de uma.
SQL_RLS: Final = """
ALTER TABLE idx.search_doc ENABLE ROW LEVEL SECURITY;
ALTER TABLE idx.search_doc FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON idx.search_doc
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE idx.termo_canonico ENABLE ROW LEVEL SECURITY;
ALTER TABLE idx.termo_canonico FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON idx.termo_canonico
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY termos_globais ON idx.termo_canonico
  FOR SELECT USING (tenant_id IS NULL)
"""

#: A funcao do §6.2. Ver as adaptacoes 1, 3 e 4 na nota do modulo; o resto e o
#: texto do documento.
SQL_CANDIDATOS: Final = """
CREATE FUNCTION idx.candidatos(
  p_tenant uuid,
  p_q_norm text,
  p_q_or   text,
  p_qvec   halfvec DEFAULT NULL,
  p_k      int     DEFAULT 40,
  p_w_sem  real    DEFAULT 0.5,
  p_w_tri  real    DEFAULT 0.3,
  p_w_fts  real    DEFAULT 0.2,
  p_rrf_k  int     DEFAULT 60)
RETURNS TABLE (o_doc_id uuid, o_product_ref text, o_score real,
               o_rk_sem int, o_rk_tri int, o_rk_fts int)
LANGUAGE sql STABLE PARALLEL SAFE AS $$
WITH tn AS (
  SELECT t.id FROM platform.tenants t WHERE t.id = p_tenant AND t.estado = 'ativo'
),
q AS (SELECT websearch_to_tsquery('idx.kamba_pt'::regconfig, p_q_or) AS tsq),
sem AS (
  SELECT s.doc_id, row_number() OVER (ORDER BY s.dist, s.doc_id) AS rk
  FROM (SELECT d.doc_id, d.embedding <=> p_qvec AS dist
          FROM idx.search_doc d JOIN tn ON tn.id = d.tenant_id
         WHERE d.visivel AND p_qvec IS NOT NULL AND d.embedding IS NOT NULL
         ORDER BY d.embedding <=> p_qvec, d.doc_id
         LIMIT p_k) s
),
tri AS (
  SELECT s.doc_id, row_number() OVER (ORDER BY s.sc DESC, s.doc_id) AS rk
  FROM (SELECT d.doc_id, word_similarity(p_q_norm, d.nome_norm) AS sc
          FROM idx.search_doc d JOIN tn ON tn.id = d.tenant_id
         WHERE d.visivel AND p_q_norm <% d.nome_norm
         ORDER BY sc DESC, d.doc_id
         LIMIT p_k) s
),
fts AS (
  SELECT s.doc_id, row_number() OVER (ORDER BY s.sc DESC, s.doc_id) AS rk
  FROM (SELECT d.doc_id, ts_rank(d.fts, q.tsq, 32) AS sc
          FROM idx.search_doc d JOIN tn ON tn.id = d.tenant_id CROSS JOIN q
         WHERE d.visivel AND d.fts @@ q.tsq
         ORDER BY sc DESC, d.doc_id
         LIMIT p_k) s
),
cand AS (SELECT doc_id FROM sem UNION SELECT doc_id FROM tri UNION SELECT doc_id FROM fts)
SELECT d.doc_id, d.product_ref,
       (COALESCE(p_w_sem / (p_rrf_k + s.rk), 0)
      + COALESCE(p_w_tri / (p_rrf_k + t.rk), 0)
      + COALESCE(p_w_fts / (p_rrf_k + f.rk), 0))::real,
       s.rk::int, t.rk::int, f.rk::int
FROM cand c
JOIN idx.search_doc d ON d.doc_id = c.doc_id
LEFT JOIN sem s ON s.doc_id = c.doc_id
LEFT JOIN tri t ON t.doc_id = c.doc_id
LEFT JOIN fts f ON f.doc_id = c.doc_id
ORDER BY 3 DESC, d.doc_id
LIMIT p_k;
$$
"""

SQL_COMENTAR: Final = """
COMMENT ON SCHEMA idx IS
  'Indice de pesquisa por tenant (KAM-061; docs/tecnica/05 secao 4). Nunca fonte de preco nem de stock (ADR-007): esses entram pelo join com platform.v_oferta_viva.';
COMMENT ON TABLE idx.search_doc IS
  'Um documento por produto e tenant (docs/tecnica/05 secao 4.2). Sem indice ANN no Piloto (PROP-IDX-1). RLS FORCE por tenant_id.';
COMMENT ON TABLE idx.termo_canonico IS
  'Dicionario PT-AO (docs/tecnica/05 secao 4.4). tenant_id nulo = entrada global, legivel por todos os tenants.';
COMMENT ON FUNCTION idx.candidatos(uuid, text, text, halfvec, integer, real, real, real, integer) IS
  'Pesquisa hibrida por tenant com RRF (docs/tecnica/05 secao 6.2). SECURITY INVOKER: sem app.tenant_id devolve zero linhas. O chamador poe SET LOCAL pg_trgm.word_similarity_threshold.'
"""

SQL_CONCEDER: Final = """
GRANT USAGE ON SCHEMA idx TO kamba_app;
GRANT SELECT, INSERT, UPDATE ON idx.search_doc TO kamba_app;
GRANT SELECT ON idx.termo_canonico TO kamba_app;
REVOKE ALL ON FUNCTION idx.f_unaccent(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION idx.f_unaccent(text) TO kamba_app;
REVOKE ALL ON FUNCTION idx.candidatos(uuid, text, text, halfvec, integer, real, real, real, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION idx.candidatos(uuid, text, text, halfvec, integer, real, real, real, integer) TO kamba_app
"""

#: O inverso, pela ordem inversa das dependencias. **Sem `CASCADE`**: se alguma
#: coisa passar a depender do esquema, o `downgrade` deve falhar em vez de a
#: levar atras. As extensoes ficam (nota do modulo).
SQL_REMOVER: Final = """
DROP FUNCTION idx.candidatos(uuid, text, text, halfvec, integer, real, real, real, integer);
DROP TABLE idx.termo_canonico;
DROP TABLE idx.search_doc;
DROP TEXT SEARCH CONFIGURATION idx.kamba_pt;
DROP FUNCTION idx.f_unaccent(text);
DROP SCHEMA idx
"""


# ------------------------------------------------------------------ KAM-062
#
# A revisao `0048`: o que a normalizacao PT-AO precisa e o esquema da `0045`
# nao tem. **Nao muda a funcao `idx.candidatos`.** Tres pecas:
#
# 1. **`idx.norm_versao`**, o «`idx.norm_versao` global» do §4.4 que a `0045`
#    nao criou. Um registo so de acrescento: cada escrita no `termo_canonico`
#    acrescenta uma linha, pelo gatilho, e diz se afecta o indice (marca ou
#    unidade: os passos 4 e 5 do §5.1 escrevem no `nome_norm`) ou so a consulta
#    (sinonimo, erro comum, *stopword*). Daqui saem as duas versoes que o
#    `kamba_core.idx.lexico` le: a maior de todas e a maior das que afectam o
#    indice. **Sem `tenant_id`**: a versao e global (§4.4), e uma linha diz so
#    que «algo mudou», nunca o que nem de quem — pelo que nao leva RLS, pela
#    regra do *gate* 6 (pergunta por RLS a quem tem a coluna). A identidade
#    comeca em **2**, porque **1** e a versao com que o KAM-061 escreveu o
#    indice (e a que o lexico devolve sem linhas).
# 2. **Duas `CHECK` no `termo_canonico`** (criterio 7): o `aprovado_por` e
#    obrigatorio e nao vazio, e uma entrada `origem = 'dataset'` nao fica
#    `activo` — ate o *gate* do KAM-064 existir, que e quem a pode soltar. E
#    falha fechada: o lexico de *dataset* entra inactivo e espera.
# 3. **O `kamba_app` le a versao** e nao a escreve. Quem escreve o lexico (e por
#    isso, pelo gatilho, a versao) e o dono — a curadoria de *ops*.

#: A tabela das versoes.
NORM_VERSAO: Final = "idx.norm_versao"

#: Os tipos do lexico que escrevem no indice (passos 4 e 5 do §5.1).
TIPOS_QUE_AFECTAM_O_INDICE: Final = ("marca", "unidade")

SQL_NORM_VERSAO: Final = """
CREATE TABLE idx.norm_versao (
  versao        bigint      GENERATED ALWAYS AS IDENTITY (START WITH 2),
  -- Verdadeiro quando a alteracao foi de marca ou unidade: os documentos com
  -- versao anterior ficam marcados para reindexar.
  afecta_indice boolean     NOT NULL,
  criado_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT norm_versao_pkey PRIMARY KEY (versao)
)
"""

#: O gatilho que acrescenta a versao. `AFTER`, por linha, nas tres operacoes:
#: apagar uma marca tambem muda o indice. `SECURITY INVOKER` (a omissao): quem
#: escreve o lexico escreve a versao, e o `kamba_app` nao escreve nenhum.
SQL_REGISTAR_NORM_VERSAO: Final = """
CREATE FUNCTION idx.f_registar_norm_versao() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  v_afecta boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    v_afecta := NEW.tipo IN ('marca', 'unidade');
  ELSIF TG_OP = 'DELETE' THEN
    v_afecta := OLD.tipo IN ('marca', 'unidade');
  ELSE
    v_afecta := NEW.tipo IN ('marca', 'unidade') OR OLD.tipo IN ('marca', 'unidade');
  END IF;
  INSERT INTO idx.norm_versao (afecta_indice) VALUES (v_afecta);
  RETURN NULL;
END
$$;
CREATE TRIGGER termo_canonico_norm_versao
  AFTER INSERT OR UPDATE OR DELETE ON idx.termo_canonico
  FOR EACH ROW EXECUTE FUNCTION idx.f_registar_norm_versao()
"""

#: As duas regras do criterio 7. A tabela nasce vazia (a `0045` nao lhe deu
#: escritor), pelo que a validacao das linhas existentes nao recusa nada.
SQL_REGRAS_DO_LEXICO: Final = """
ALTER TABLE idx.termo_canonico
  ADD CONSTRAINT termo_canonico_aprovado_ck
    CHECK (aprovado_por IS NOT NULL AND btrim(aprovado_por) <> ''),
  ADD CONSTRAINT termo_canonico_dataset_inactivo_ck
    CHECK (origem <> 'dataset' OR NOT activo)
"""

SQL_COMENTAR_NORMALIZACAO: Final = """
COMMENT ON TABLE idx.norm_versao IS
  'Versao do dicionario PT-AO (docs/tecnica/05 secao 4.4; KAM-062). Uma linha por escrita no idx.termo_canonico, pelo gatilho; afecta_indice diz se os documentos reindexam. Sem tenant_id.';
COMMENT ON FUNCTION idx.f_registar_norm_versao() IS
  'Gatilho do idx.termo_canonico: acrescenta uma versao. Marca e unidade afectam o indice; o resto so a consulta.'
"""

SQL_CONCEDER_NORMALIZACAO: Final = """
GRANT SELECT ON idx.norm_versao TO kamba_app;
REVOKE ALL ON FUNCTION idx.f_registar_norm_versao() FROM PUBLIC
"""

SQL_REMOVER_NORMALIZACAO: Final = """
DROP TRIGGER termo_canonico_norm_versao ON idx.termo_canonico;
DROP FUNCTION idx.f_registar_norm_versao();
DROP TABLE idx.norm_versao;
ALTER TABLE idx.termo_canonico
  DROP CONSTRAINT termo_canonico_dataset_inactivo_ck,
  DROP CONSTRAINT termo_canonico_aprovado_ck
"""


def criar_normalizacao() -> None:
    """O `upgrade` da `0048` (KAM-062): versao, gatilho, regras e privilegios."""
    op.execute(SQL_NORM_VERSAO)
    op.execute(SQL_REGISTAR_NORM_VERSAO)
    op.execute(SQL_REGRAS_DO_LEXICO)
    op.execute(SQL_COMENTAR_NORMALIZACAO)
    op.execute(SQL_CONCEDER_NORMALIZACAO)


def remover_normalizacao() -> None:
    """O `downgrade` da `0048`: o inverso, sem `CASCADE`."""
    op.execute(SQL_REMOVER_NORMALIZACAO)


def criar() -> None:
    """O `upgrade` inteiro: extensoes, esquema, tabelas, RLS, funcao e privilegios."""
    op.execute(SQL_EXTENSOES)
    op.execute(SQL_ESQUEMA)
    op.execute(SQL_F_UNACCENT)
    op.execute(SQL_CONFIGURACAO_FTS)
    op.execute(SQL_SEARCH_DOC)
    op.execute(SQL_INDICES_DO_SEARCH_DOC)
    op.execute(SQL_TERMO_CANONICO)
    op.execute(SQL_RLS)
    op.execute(SQL_CANDIDATOS)
    op.execute(SQL_COMENTAR)
    op.execute(SQL_CONCEDER)


def remover() -> None:
    """O `downgrade`: tudo o que `criar()` fez, menos as extensoes."""
    op.execute(SQL_REMOVER)

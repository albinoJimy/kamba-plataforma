"""Social do dono: brand_profile, content_calendar, content_items, o sujeito e a finalidade do conteudo (KAM-121).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

1. **A `platform.brand_profile`**, o perfil de marca de um tenant: uma linha por
   tenant, com os sete campos da conversa guiada (criterio 1) e o logotipo.
   **Os campos sao anulaveis ate a resposta** — `NULL` e «por responder», e
   uma lista vazia e «nenhuma» —, porque o perfil nasce vazio quando a conversa
   comeca. A `versao` e o *compare-and-set* de cada resposta. Diverge do DDL do
   bloco em tres pontos, escritos no dicionario §3.82: a `categoria` entra, as
   colunas sao anulaveis, e a `versao` e de escrita.
2. **A `platform.content_calendar`**, o calendario de uma semana: **um `activo`
   por `(tenant_id, semana_iso)`**, pelo indice unico parcial — a chave do
   criterio 2. «NOVA» abre a `geracao` seguinte e o anterior passa a
   `substituido`. Guarda a decisao do screening dos temas e a versao da
   politica.
3. **A `platform.content_items`**, os itens de um calendario: nascem `rascunho`
   e com `is_ai_generated = true` (criterio 8). O `screening_ref bigint` do DDL
   do bloco nao entra: o `id` da `screening_decision` e `uuid`, e a decisao
   liga-se ao item pelo sujeito `conteudo` com o `id` dele. A FK ao calendario
   e **composta** com o `tenant_id` (a licao ISO-58): um item do tenant A nao
   aponta para um calendario de B.
4. **`conteudo` em `screening_decision.sujeito_tipo`**, que passa de tres a
   quatro valores (decisao do fundador de 2026-11-20, opcao A, bloco do
   KAM-121). A `sujeito_ref` e o `content_item_id`. Nenhuma consulta existente muda de resposta: a
   re-analise, a activacao do tenant e a categoria do COM filtram por
   `categoria` ou por `produto`, explicitamente.
5. **`classificacao_de_conteudo` em `tenant_destinations.purpose`**, que passa
   de dezasseis a **dezassete** valores: a finalidade de transferencia do
   classificador de screening quando le os temas e as legendas do modulo
   `social`. **Pelo precedente da `finalidade_das_condicoes` (`0078`, decisao do
   fundador de 2026-11-20, opcao B)**: o mesmo classificador, outro tratamento,
   outra finalidade no ADR-008 — um destino autorizado so para o catalogo ou
   para as condicoes nao cobre o conteudo. **Decisao do fundador de 2026-11-21**:
   a finalidade propria, recusada a reutilizacao da `classificacao_de_catalogo`.
   A `v_transfer_audit` nao se recria, pela razao que a `0078` escreve.

## Os privilegios do `kamba_app`

`SELECT`, o `INSERT` das colunas que o AGR escreve, e o `UPDATE` **so das
colunas que mudam**: o `is_ai_generated`, o `tenant_id`, as chaves e as horas
de criacao nunca. Sem `DELETE` para ninguem: a purga e a da retencao (classe
`relacao`).

## O `downgrade`

**Recusa-se com um destino `classificacao_de_conteudo`**, como a `0078`: e o
registo de uma decisao de transferencia, e nao se apaga para descer. Depois
larga as tres tabelas e, pela regra da `0074`, **apaga as decisoes `conteudo`**
antes de repor o dominio de tres: uma base onde se desce uma revisao do
screening e uma base de ensaio, e recusar deixava a descida presa a uma tabela
*append-only*.

## Numero

`0079`, dada pela fila de integracao, sobre a `0078` do KAM-230 ja fundida.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

TENANTS = "platform.tenants"
PERFIL = "platform.brand_profile"
CALENDARIO = "platform.content_calendar"
ITENS = "platform.content_items"
DECISOES = "platform.screening_decision"
RESTRICAO = "screening_decision_sujeito_tipo_ck"
DESTINOS = "platform.tenant_destinations"

#: Por extenso: o *gate* 3b le o SQL das revisoes sem as executar.
SUJEITOS = ("'categoria'", "'condicoes'", "'conteudo'", "'produto'")
SUJEITOS_DA_0074 = ("'categoria'", "'condicoes'", "'produto'")

#: As **dezassete** finalidades de transferencia: as dezasseis da
#: `finalidade_das_condicoes` (`0078`) e a `classificacao_de_conteudo`. Por
#: ordem alfabetica, como la.
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
    "'imagem'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: As dezasseis da `0078`, para o `downgrade`. Por extenso e nao filtradas da de
#: cima: o *gate* 3b nao le SQL gerado por *generator*.
FINALIDADES_DA_0078 = (
    "'alojamento'",
    "'canal'",
    "'classificacao_de_catalogo'",
    "'classificacao_de_condicoes'",
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

TONS = ("'proximo'", "'profissional'", "'divertido'")
TIPOS = ("'produto'", "'dica'", "'bastidores'", "'promocao'")
ESTADOS_DO_ITEM = (
    "'rascunho'",
    "'pendente_aprovacao'",
    "'aprovado'",
    "'entregue'",
    "'rejeitado'",
    "'expirado'",
)
ESTADOS_DO_CALENDARIO = ("'activo'", "'substituido'")
DECISOES_DO_SCREEN = ("'permitida'", "'condicional'", "'bloqueada'")

INSERT_DO_PERFIL = ("tenant_id", "nome", "categoria", "tom", "cores", "publico", "slots_preferidos", "factos", "versao")
UPDATE_DO_PERFIL = (
    "nome",
    "categoria",
    "tom",
    "cores",
    "publico",
    "slots_preferidos",
    "factos",
    "logo_asset_id",
    "versao",
    "atualizado_at",
)
INSERT_DO_CALENDARIO = ("calendar_id", "tenant_id", "semana_iso", "geracao", "decisao", "versao_politica")
UPDATE_DO_CALENDARIO = ("estado",)
INSERT_DO_ITEM = (
    "content_item_id",
    "tenant_id",
    "calendar_id",
    "semana_iso",
    "tipo",
    "tema",
    "agendado_at",
    "revisao_reforcada",
    "versao_politica",
)
UPDATE_DO_ITEM = (
    "legenda",
    "art_asset_id",
    "estado",
    "revisao_reforcada",
    "versao_politica",
    "versao",
    "atualizado_at",
)

SEMANA_ISO = r"'^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$'"


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(valores)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {PERFIL} (
          tenant_id         uuid CONSTRAINT brand_profile_pkey PRIMARY KEY,
          nome              text CONSTRAINT brand_profile_nome_ck
                            CHECK (nome IS NULL OR char_length(nome) BETWEEN 2 AND 60),
          categoria         text CONSTRAINT brand_profile_categoria_ck
                            CHECK (categoria IS NULL OR char_length(categoria) BETWEEN 2 AND 60),
          tom               text CONSTRAINT brand_profile_tom_ck
                            CHECK (tom IN ({_lista(TONS)})),
          cores             text[] CONSTRAINT brand_profile_cores_ck
                            CHECK (cores IS NULL OR (cardinality(cores) <= 3
                                   AND array_to_string(cores, ',') ~ '^(#[0-9A-F]{{6}}(,|$))*$')),
          logo_asset_id     uuid,
          publico           text CONSTRAINT brand_profile_publico_ck
                            CHECK (publico IS NULL OR char_length(publico) BETWEEN 2 AND 200),
          slots_preferidos  jsonb CONSTRAINT brand_profile_slots_ck
                            CHECK (slots_preferidos IS NULL OR (jsonb_typeof(slots_preferidos) = 'array'
                                   AND jsonb_array_length(slots_preferidos) BETWEEN 1 AND 7)),
          factos            jsonb CONSTRAINT brand_profile_factos_ck
                            CHECK (factos IS NULL OR (jsonb_typeof(factos) = 'array'
                                   AND jsonb_array_length(factos) <= 10)),
          idioma            text NOT NULL DEFAULT 'pt-AO'
                            CONSTRAINT brand_profile_idioma_ck CHECK (idioma IN ('pt-AO')),
          versao            integer NOT NULL DEFAULT 1
                            CONSTRAINT brand_profile_versao_ck CHECK (versao >= 1),
          criado_at         timestamptz NOT NULL DEFAULT now(),
          atualizado_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT brand_profile_tenant_fk FOREIGN KEY (tenant_id) REFERENCES {TENANTS} (id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {CALENDARIO} (
          calendar_id       uuid CONSTRAINT content_calendar_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id         uuid NOT NULL,
          semana_iso        text NOT NULL
                            CONSTRAINT content_calendar_semana_ck CHECK (semana_iso ~ {SEMANA_ISO}),
          geracao           integer NOT NULL
                            CONSTRAINT content_calendar_geracao_ck CHECK (geracao >= 1),
          estado            text NOT NULL DEFAULT 'activo'
                            CONSTRAINT content_calendar_estado_ck
                            CHECK (estado IN ({_lista(ESTADOS_DO_CALENDARIO)})),
          decisao           text NOT NULL
                            CONSTRAINT content_calendar_decisao_ck
                            CHECK (decisao IN ({_lista(DECISOES_DO_SCREEN)})),
          versao_politica   text NOT NULL
                            CONSTRAINT content_calendar_versao_politica_ck
                            CHECK (char_length(versao_politica) BETWEEN 1 AND 64),
          criado_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT content_calendar_geracao_uq UNIQUE (tenant_id, semana_iso, geracao),
          CONSTRAINT content_calendar_tenant_id_uq UNIQUE (tenant_id, calendar_id),
          CONSTRAINT content_calendar_tenant_fk FOREIGN KEY (tenant_id) REFERENCES {TENANTS} (id)
        )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX content_calendar_um_activo_uq ON {CALENDARIO} (tenant_id, semana_iso) "
        "WHERE estado = 'activo'"
    )
    op.execute(
        f"""
        CREATE TABLE {ITENS} (
          content_item_id   uuid CONSTRAINT content_items_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id         uuid NOT NULL,
          calendar_id       uuid NOT NULL,
          semana_iso        text NOT NULL
                            CONSTRAINT content_items_semana_ck CHECK (semana_iso ~ {SEMANA_ISO}),
          tipo              text NOT NULL
                            CONSTRAINT content_items_tipo_ck CHECK (tipo IN ({_lista(TIPOS)})),
          tema              text NOT NULL
                            CONSTRAINT content_items_tema_ck CHECK (char_length(tema) BETWEEN 1 AND 300),
          legenda           text CONSTRAINT content_items_legenda_ck
                            CHECK (legenda IS NULL OR char_length(legenda) BETWEEN 1 AND 1000),
          art_asset_id      uuid,
          estado            text NOT NULL DEFAULT 'rascunho'
                            CONSTRAINT content_items_estado_ck CHECK (estado IN ({_lista(ESTADOS_DO_ITEM)})),
          is_ai_generated   boolean NOT NULL DEFAULT true,
          revisao_reforcada boolean NOT NULL DEFAULT false,
          versao_politica   text CONSTRAINT content_items_versao_politica_ck
                            CHECK (versao_politica IS NULL OR char_length(versao_politica) BETWEEN 1 AND 64),
          versao            integer NOT NULL DEFAULT 1
                            CONSTRAINT content_items_versao_ck CHECK (versao >= 1),
          agendado_at       timestamptz NOT NULL,
          criado_at         timestamptz NOT NULL DEFAULT now(),
          atualizado_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT content_items_calendario_fk FOREIGN KEY (tenant_id, calendar_id)
            REFERENCES {CALENDARIO} (tenant_id, calendar_id),
          CONSTRAINT content_items_tenant_fk FOREIGN KEY (tenant_id) REFERENCES {TENANTS} (id)
        )
        """
    )
    op.execute(f"CREATE INDEX content_items_calendario_idx ON {ITENS} (tenant_id, calendar_id, agendado_at)")
    for tabela, texto in (
        (PERFIL, "O perfil de marca do tenant (KAM-121): NULL e por responder. Sem DELETE para ninguem."),
        (CALENDARIO, "O calendario semanal do social (KAM-121): um activo por (tenant_id, semana_iso)."),
        (ITENS, "Os itens de um calendario (KAM-121): nascem rascunho e gerados por IA; nada aqui publica."),
    ):
        op.execute(f"COMMENT ON TABLE {tabela} IS '{texto}'")
    for nome in ("brand_profile", "content_calendar", "content_items"):
        rls.enable_tenant_rls(nome)
    for tabela, inserir, mudar in (
        (PERFIL, INSERT_DO_PERFIL, UPDATE_DO_PERFIL),
        (CALENDARIO, INSERT_DO_CALENDARIO, UPDATE_DO_CALENDARIO),
        (ITENS, INSERT_DO_ITEM, UPDATE_DO_ITEM),
    ):
        op.execute(f"REVOKE ALL ON {tabela} FROM PUBLIC")
        op.execute(
            f"GRANT SELECT, INSERT ({', '.join(inserir)}), UPDATE ({', '.join(mudar)}) ON {tabela} TO kamba_app"
        )
    op.execute(f"ALTER TABLE {DECISOES} DROP CONSTRAINT {RESTRICAO}")
    op.execute(
        f"""
        ALTER TABLE {DECISOES}
          ADD CONSTRAINT screening_decision_sujeito_tipo_ck
          CHECK (sujeito_tipo IN ({_lista(SUJEITOS)}))
        """
    )
    op.execute(f"ALTER TABLE {DESTINOS} DROP CONSTRAINT tenant_destinations_purpose_ck")
    op.execute(
        f"""
        ALTER TABLE {DESTINOS}
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({_lista(FINALIDADES_DE_TRANSFERENCIA)}))
        """
    )


def downgrade() -> None:
    # Uma linha `classificacao_de_conteudo` e o registo de uma decisao sobre uma
    # transferencia (contrato, `apd_ref`), e nao se apaga para descer: recusa-se
    # **antes de tocar em nada**, como a `0078`. A contagem corre sem a `FORCE`,
    # porque o dono da tabela tambem esta sujeito a politica e veria zero.
    op.execute(f"ALTER TABLE {DESTINOS} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.tenant_destinations "
            "WHERE purpose = 'classificacao_de_conteudo'"
        )
        .scalar_one()
    )
    op.execute(f"ALTER TABLE {DESTINOS} FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da social_do_dono recusado: ha {linhas} destino(s) com purpose "
            "classificacao_de_conteudo, e o dominio da finalidade_das_condicoes nao os "
            "aceita. Sao registos de uma decisao de transferencia: exporte-os e "
            "decida antes de descer."
        )
    op.execute(f"ALTER TABLE {DESTINOS} DROP CONSTRAINT tenant_destinations_purpose_ck")
    op.execute(
        f"""
        ALTER TABLE {DESTINOS}
          ADD CONSTRAINT tenant_destinations_purpose_ck
          CHECK (purpose IN ({_lista(FINALIDADES_DA_0078)}))
        """
    )
    op.execute(f"ALTER TABLE {DECISOES} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {DECISOES} DISABLE TRIGGER screening_decision_imutavel")
    op.execute(f"DELETE FROM {DECISOES} WHERE sujeito_tipo = 'conteudo'")
    op.execute(f"ALTER TABLE {DECISOES} ENABLE TRIGGER screening_decision_imutavel")
    op.execute(f"ALTER TABLE {DECISOES} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {DECISOES} DROP CONSTRAINT {RESTRICAO}")
    op.execute(
        f"""
        ALTER TABLE {DECISOES}
          ADD CONSTRAINT screening_decision_sujeito_tipo_ck
          CHECK (sujeito_tipo IN ({_lista(SUJEITOS_DA_0074)}))
        """
    )
    for nome in ("content_items", "content_calendar", "brand_profile"):
        rls.disable_tenant_rls(nome)
    op.execute(f"DROP TABLE {ITENS}")
    op.execute(f"DROP TABLE {CALENDARIO}")
    op.execute(f"DROP TABLE {PERFIL}")

"""O caso de onboarding e o KYC K1: onboarding_case e kyc_check (KAM-087).

O SQL das duas tabelas vive **aqui** e nao na revisao, pela razao do
`db/custo.py`: os ensaios de base de dados (`db/tests/test_kyc_schema.py`)
importam-no deste modulo em vez de o copiarem, e o *gate* 3b le-o seguindo o
corpo de `criar()` — este ficheiro esta declarado em `ci/canon-lint.yaml` como
modulo auxiliar de migracao. Por isso cada instrucao e uma cadeia **literal**:
o que o lint nao segue, recusa.

**Mudar uma tabela e uma revisao nova**, que altera o que esta revisao criou;
esta nao se reescreve depois de fundir.

## `platform.onboarding_case` — o credor do KAM-086 e do KAM-093

O DDL e o dos Detalhes Tecnicos do bloco do KAM-086, com tres diferencas, todas
na emenda do dicionario que acompanha esta revisao:

* **a coluna e `fase` e nao `estado`.** O dicionario §3.2 e o codigo fundido do
  KAM-086 (`Caso.fase`, `marcarFase`) dizem `fase`; so o DDL do bloco diz
  `estado`, e `estado` e ja o nome de `tenants.estado`, com outro dominio;
* **os catorze valores do bloco**, e nao os seis do §3.2: o KAM-086 ja escreve
  `registo`, `otp_pendente` e `kyc_pendente`, e o indice unico do NIF precisa das
  tres fases mortas. A divergencia esta medida na emenda;
* **duas colunas a mais**: o `preflight` que o KAM-093 deixou com credor, e o
  `fase_at`, que e o «D» dos D+30 do criterio 10 do KAM-087 e que **so o
  *trigger* escreve** — um `fase_at` escrito por quem insere deixava purgar os
  documentos de um caso no dia em que ele morreu.

E uma restricao a mais: `UNIQUE (id, tenant_id)`, que e o alvo da FK composta do
`kyc_check`. O `tenant_id` ja e unico sozinho; a unicidade composta existe para
a FK poder prender os dois.

RLS `FORCE` pela `tenant_iso`, sobre o `tenant_id` **pre-alocado**: o caso tem o
seu tenant desde o registo, e o `tenant_id` e unico por caso, pelo que limitar a
sessao ao `tenant_id` do caso e limita-la ao caso. E o que a `contract_acceptance`
da `0040` ja faz com a mesma pre-alocacao.

## `platform.kyc_check`

O DDL do bloco do KAM-087, com tres colunas a mais: o `tenant_id` (a RLS e o
X-05 agarram a tabela por ele, e a FK composta impede uma linha com o caso de um
e o tenant de outro), o `custo_micro_usd` (DoD 4, «custo por caso medido») e a
unicidade `(onboarding_id, sha256)`, que e a idempotencia da DoD 4.
O `doc_ref` e conferido contra o prefixo do tenant no STO: um documento so pode
apontar para um objecto do tenant da propria linha.

## Privilegios

O KYC corre como `kamba_batch` — a pergunta do `phash` atravessa tenants (ver
`packages/core-ts/src/kyc/sql.ts`) —, pelo que e o lote que insere e decide. O
`kamba_app` le e escreve o seu caso pela RLS, no que o registo do KAM-086
escreve, e **nao le o `kyc_check`**: as marcas sao o motivo interno, que o
criterio 7 reserva ao T&S, e o servico do dono so devolve o motivo publico. Com
`SELECT`, um defeito no `onboarding-web` mostrava ao dono «nif_divergente».
**Ninguem tem `DELETE`**: a purga dos D+30 esquece os campos (`extraido_enc` a
nulo) e apaga o objecto no STO, e a linha fica como registo da decisao.
"""

from __future__ import annotations

from typing import Final

from alembic import op

#: As catorze fases, pela ordem do bloco do KAM-086. Iguais ao `FASES` de
#: `packages/core-ts/src/inscricao/contrato.ts`; o ensaio confronta as duas.
FASES: Final = (
    "registo",
    "otp_pendente",
    "kyc_pendente",
    "em_revisao",
    "aprovado",
    "provisionando",
    "aguarda_es",
    "lista_espera",
    "aguarda_catalogo",
    "aguarda_teste",
    "activo",
    "rejeitado",
    "abandonado",
    "cancelado",
)

SQL_CRIAR_CASO: Final = """
CREATE TABLE platform.onboarding_case (
  id                    uuid CONSTRAINT onboarding_case_pkey PRIMARY KEY
                        DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL DEFAULT gen_random_uuid()
                        CONSTRAINT onboarding_case_tenant_uq UNIQUE,
  fase                  text NOT NULL DEFAULT 'registo'
                        CONSTRAINT onboarding_case_fase_ck
                        CHECK (fase IN ('registo', 'otp_pendente', 'kyc_pendente',
                          'em_revisao', 'aprovado', 'provisionando', 'aguarda_es',
                          'lista_espera', 'aguarda_catalogo', 'aguarda_teste',
                          'activo', 'rejeitado', 'abandonado', 'cancelado')),
  fase_at               timestamptz NOT NULL DEFAULT now(),
  origem                text NOT NULL
                        CONSTRAINT onboarding_case_origem_ck
                        CHECK (origem IN ('convite', 'contabilista', 'anuncio')),
  nome_negocio          text NOT NULL,
  categoria_declarada   text NOT NULL,
  nif_enc               bytea NOT NULL,
  nif_hmac              bytea NOT NULL
                        CONSTRAINT onboarding_case_nif_hmac_ck
                        CHECK (octet_length(nif_hmac) = 32),
  phone_enc             bytea NOT NULL,
  phone_hmac            bytea NOT NULL
                        CONSTRAINT onboarding_case_phone_hmac_ck
                        CHECK (octet_length(phone_hmac) = 32),
  email_enc             bytea,
  device_hash           bytea,
  ip_prefix_hash        bytea,
  flags                 text[] NOT NULL DEFAULT '{}'
                        CONSTRAINT onboarding_case_flags_ck
                        CHECK (flags <@ ARRAY['duplicado_ambiguo']::text[]),
  owner_active_seconds  integer NOT NULL DEFAULT 0
                        CONSTRAINT onboarding_case_owner_active_seconds_ck
                        CHECK (owner_active_seconds >= 0),
  preflight             jsonb
                        CONSTRAINT onboarding_case_preflight_ck
                        CHECK (jsonb_typeof(preflight) = 'array'),
  criado_at             timestamptz NOT NULL DEFAULT now(),
  activo_at             timestamptz,
  CONSTRAINT onboarding_case_id_tenant_uq UNIQUE (id, tenant_id)
)
"""

SQL_INDICE_DO_NIF: Final = """
CREATE UNIQUE INDEX onboarding_nif_vivo ON platform.onboarding_case (nif_hmac)
  WHERE fase NOT IN ('rejeitado', 'abandonado', 'cancelado')
"""

SQL_INDICE_DO_TELEFONE: Final = """
CREATE INDEX onboarding_case_phone_hmac_idx ON platform.onboarding_case (phone_hmac)
"""

SQL_INDICE_DOS_MORTOS: Final = """
CREATE INDEX onboarding_case_fase_at_idx ON platform.onboarding_case (fase, fase_at)
"""

SQL_COMENTAR_CASO: Final = """
COMMENT ON TABLE platform.onboarding_case IS
'Caso de onboarding self-service (KAM-086, tabela criada pelo KAM-087). fase em 14 valores; fase_at escrito so pelo trigger. NIF e telefone cifrados em aplicacao, com HMAC para correspondencia. tenant_id pre-alocado: a linha de tenants nasce no passo 1 da saga (KAM-091).'
"""

SQL_FUNCAO_FASE_AT: Final = """
CREATE FUNCTION platform.onboarding_case_fase_at()
  RETURNS trigger
  LANGUAGE plpgsql
  SET search_path = pg_catalog, platform
AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.fase IS DISTINCT FROM OLD.fase THEN
    NEW.fase_at := now();
  ELSE
    NEW.fase_at := OLD.fase_at;
  END IF;
  RETURN NEW;
END;
$$
"""

SQL_TRIGGER_FASE_AT: Final = """
CREATE TRIGGER onboarding_case_fase_at
  BEFORE INSERT OR UPDATE ON platform.onboarding_case
  FOR EACH ROW EXECUTE FUNCTION platform.onboarding_case_fase_at()
"""

SQL_CRIAR_KYC: Final = """
CREATE TABLE platform.kyc_check (
  id               uuid CONSTRAINT kyc_check_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
  onboarding_id    uuid NOT NULL,
  tenant_id        uuid NOT NULL,
  doc_tipo         text NOT NULL
                   CONSTRAINT kyc_check_doc_tipo_ck
                   CHECK (doc_tipo IN ('nif', 'alvara', 'bi', 'banco')),
  doc_ref          text NOT NULL,
  sha256           bytea NOT NULL
                   CONSTRAINT kyc_check_sha256_ck CHECK (octet_length(sha256) = 32),
  phash            bytea
                   CONSTRAINT kyc_check_phash_ck CHECK (octet_length(phash) = 8),
  extraido_enc     bytea,
  flags            text[] NOT NULL DEFAULT '{}'
                   CONSTRAINT kyc_check_flags_ck
                   CHECK (flags <@ ARRAY['nif_divergente', 'alvara_expirado',
                     'imagem_reutilizada', 'software_de_edicao', 'iban_invalido',
                     'nome_titular_divergente', 'confianca_baixa',
                     'actividade_incoerente', 'visao_recusada',
                     'orcamento_excedido', 'ilegivel']::text[]),
  score            smallint
                   CONSTRAINT kyc_check_score_ck CHECK (score >= 0),
  resultado        text NOT NULL
                   CONSTRAINT kyc_check_resultado_ck
                   CHECK (resultado IN ('k1_ok', 'fila', 'ilegivel', 'pendente')),
  versao_regras    text NOT NULL
                   CONSTRAINT kyc_check_versao_regras_ck
                   CHECK (versao_regras ~ '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$'),
  custo_micro_usd  integer NOT NULL DEFAULT 0
                   CONSTRAINT kyc_check_custo_micro_usd_ck CHECK (custo_micro_usd >= 0),
  criado_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT kyc_check_documento_uq UNIQUE (onboarding_id, sha256),
  CONSTRAINT kyc_check_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
    REFERENCES platform.onboarding_case (id, tenant_id),
  CONSTRAINT kyc_check_doc_ref_ck
    CHECK (starts_with(doc_ref, 't/' || tenant_id::text || '/kyc_documento/'))
)
"""

SQL_INDICE_DO_KYC: Final = """
CREATE INDEX kyc_check_onboarding_idx ON platform.kyc_check (onboarding_id, criado_at)
"""

SQL_INDICE_DO_TENANT_KYC: Final = """
CREATE INDEX kyc_check_tenant_idx ON platform.kyc_check (tenant_id)
"""

SQL_COMENTAR_KYC: Final = """
COMMENT ON TABLE platform.kyc_check IS
'Verificacao K1 de um documento (KAM-087). Idempotente por (onboarding_id, sha256). extraido_enc cifrado em aplicacao (AES-256-GCM, contexto onboarding_id:tipo); esquecido a D+30 de um caso rejeitado ou abandonado. Nunca rejeita por suspeita: so ilegivel.'
"""

SQL_CONCEDER_CASO_APP: Final = """
GRANT SELECT, INSERT, UPDATE (fase, flags, owner_active_seconds, preflight)
  ON platform.onboarding_case TO kamba_app
"""

SQL_CONCEDER_CASO_LOTE: Final = """
GRANT SELECT, UPDATE (fase, flags, preflight, activo_at)
  ON platform.onboarding_case TO kamba_batch
"""

SQL_CONCEDER_CASO_AUDITORIA: Final = "GRANT SELECT ON platform.onboarding_case TO kamba_audit"

SQL_CONCEDER_KYC_LOTE: Final = """
GRANT SELECT, INSERT, UPDATE (resultado, score, flags, extraido_enc)
  ON platform.kyc_check TO kamba_batch
"""

SQL_CONCEDER_KYC_AUDITORIA: Final = "GRANT SELECT ON platform.kyc_check TO kamba_audit"

SQL_REMOVER_KYC: Final = "DROP TABLE platform.kyc_check"

SQL_REMOVER_CASO: Final = "DROP TABLE platform.onboarding_case"

SQL_REMOVER_FUNCAO: Final = "DROP FUNCTION platform.onboarding_case_fase_at()"


def criar() -> None:
    """Cria as duas tabelas, os indices, o *trigger* e os comentarios.

    A RLS e os privilegios vem a seguir, na revisao, por `rls.enable_tenant_rls`
    e por `conceder()`: a ordem e a de todas as revisoes desta casa.
    """
    op.execute(SQL_CRIAR_CASO)
    op.execute(SQL_INDICE_DO_NIF)
    op.execute(SQL_INDICE_DO_TELEFONE)
    op.execute(SQL_INDICE_DOS_MORTOS)
    op.execute(SQL_COMENTAR_CASO)
    op.execute(SQL_FUNCAO_FASE_AT)
    op.execute(SQL_TRIGGER_FASE_AT)
    op.execute(SQL_CRIAR_KYC)
    op.execute(SQL_INDICE_DO_KYC)
    op.execute(SQL_INDICE_DO_TENANT_KYC)
    op.execute(SQL_COMENTAR_KYC)


def conceder() -> None:
    """Os privilegios. Ver a nota do modulo."""
    op.execute(SQL_CONCEDER_CASO_APP)
    op.execute(SQL_CONCEDER_CASO_LOTE)
    op.execute(SQL_CONCEDER_CASO_AUDITORIA)
    op.execute(SQL_CONCEDER_KYC_LOTE)
    op.execute(SQL_CONCEDER_KYC_AUDITORIA)


def remover() -> None:
    """O inverso, para o `downgrade`. Sem `CASCADE`: um dependente faz falhar."""
    op.execute(SQL_REMOVER_KYC)
    op.execute(SQL_REMOVER_CASO)
    op.execute(SQL_REMOVER_FUNCAO)

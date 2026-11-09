"""Aceite contratual versionado: contract_document e contract_acceptance (KAM-090).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## O que esta revisao cria

* a `platform.contract_document`, **uma versao publicada** de um dos quatro
  documentos (ToS, DPA, aviso de privacidade, lista de subprocessadores), com o
  `sha256` do conteudo canonico. **Sem `tenant_id`**: e texto de plataforma e
  nao dado de tenant, como a `consent_texts` da `0015` — e pela mesma razao
  fica fora do X-05 e do `ci/rls_exceptions.yaml`;
* a `platform.contract_acceptance`, **a prova de um aceite**, append-only, com
  RLS `FORCE` pela `tenant_iso`;
* o **gate**: um *trigger* em `platform.tenants` que recusa `ativo` a um tenant
  sem aceite das versoes vigentes dos quatro documentos — o criterio 4 do
  bloco, «falha por restricao de BD (`tenant sem DPA aceite nao activa`)»;
* a `platform.dpa_em_falta()`, a pergunta da verificacao diaria do criterio 8.

## Sem `SECURITY DEFINER`, e e escolha e nao omissao

A forma obvia era uma funcao `DEFINER` como porta de escrita, a maneira da
`0029` e da `0039`. Nao e precisa, e o `docs/tecnica/08` §3.3 proibe-as fora da
lista aprovada. As quatro coisas que a porta faria fazem-se sem ela:

    versao vigente      trigger BEFORE INSERT, de quem invoca: le a
                        contract_document, que e de leitura para quem escreve
    texto publicado     FK composta (document_id, versao, doc_sha256) para a
                        unicidade com o mesmo nome da contract_document: um
                        aceite que cite outro texto nao tem para onde apontar
    hora e evidencia    o mesmo trigger escreve `aceite_em = now()` e o
                        `evidence_hash`, por cima do que o chamador mandou; e o
                        CHECK `contract_acceptance_evidencia_ck` prende a formula
                        mesmo para quem escreva sem passar pelo trigger
    OTP noutro caso     EXCLUDE (otp_challenge_id =, onboarding_id <>): **a
                        unica das quatro que tem de ver atraves dos tenants**,
                        porque cada caso tem o seu `tenant_id` pre-alocado. Uma
                        porta, mesmo `DEFINER`, nao via a linha do outro caso —
                        corre como o dono, que e `NOBYPASSRLS`, e o `FORCE`
                        vincula-o. Uma restricao e avaliada por baixo da RLS.

O `EXCLUDE` precisa do `btree_gist`, que a `0025` instalou no esquema
`servicos`; o operador vem qualificado (`servicos.gist_uuid_ops`) para nao
depender do `search_path` de quem corre a migracao.

## O `id` e `uuid`, e nao o `bigserial` dos Detalhes Tecnicos do bloco

Pela regra do dicionario §2 que a emenda 1.28 ja aplicou a `consent_event`: o
`kamba_app` le esta tabela, e uma chave sequencial diz a quem a le quantos
aceites a plataforma tem.

## Porque e que nao ha FK para `tenants` nem para o caso

O aceite acontece **antes** de o caso passar a `aprovado`, e a linha de
`platform.tenants` so nasce no passo 1 da saga, depois do `tenant.approved`. E
a mesma pre-alocacao do `provisioning_step.tenant_id` da `0034`. A tabela do
caso (`onboarding_case`) **nao existe** nesta base — credor KAM-086/087 —, pelo
que o `onboarding_id` tambem nao tem FK.

## O gate e de transicao, e nao decide o destino dos tenants existentes

O bloco diz que uma versao nova «por omissao so bloqueia activacoes novas
(consequencia para tenants existentes decidida com o parecer)». Por isso o
*trigger* exige as **vigentes** so a quem entra em `ativo` vindo de
`onboarding` (ou nasce `ativo`); a quem volta a `ativo` de `restrito` ou
`suspenso` exige **um** aceite de cada um dos quatro, de qualquer versao. Sem
esta segunda metade, `onboarding -> restrito -> ativo` contornava o gate; com as
vigentes ali, uma versao nova do DPA impedia a reactivacao de um tenant que ja
estava activo — e isso e a decisao que o bloco devolve ao parecer.

O *trigger* corre como **quem invoca**. Quem muda `tenants.estado` e o
`kamba_batch` (a `0007` tirou-o ao `kamba_app`), que tem `BYPASSRLS` e le os
aceites de todos os tenants. Um papel que nao os consiga ler ve zero aceites e
o gate **recusa** — falha fechado, que e o que o *Handoff* do bloco pede.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

DOCUMENTOS = "platform.contract_document"
ACEITES = "platform.contract_acceptance"

#: Os quatro tipos do criterio 1, e sao fechados: um quinto documento e uma
#: condicao nova de activacao, e entra por migracao e nao por insercao.
TIPOS = ("dpa", "privacidade", "subprocessadores", "tos")

#: Por extenso, e nao `", ".join(TIPOS)`: o *gate* 3b le a revisao sem a correr
#: e so resolve cadeias e constantes de modulo. Um `CHECK` que ele nao le e um
#: dominio que ele nao verifica.
LITERAIS_DE_TIPO = "'dpa', 'privacidade', 'subprocessadores', 'tos'"

#: SemVer sem pre-lancamento nem metadados: `1.0.0`, `0.1.0`, `12.3.4`. Um
#: documento juridico com `-rc1` nao e uma versao que alguem aceite.
SEMVER = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

FALTA = "platform.contrato_em_falta(uuid, boolean)"
EVIDENCIA = "platform.contrato_evidencia(bytea, uuid, timestamp with time zone, uuid)"
DPA_EM_FALTA = "platform.dpa_em_falta()"


def upgrade() -> None:
    _evidencia()
    _documentos()
    _aceites()
    _gate()
    _privilegios()


def _evidencia() -> None:
    """A formula do `evidence_hash`, num sitio so.

    `sha256(doc_sha256 || signatario || aceite_em || otp_challenge_id)`, a
    ordem do criterio 3, com **campos de largura fixa**: 32 octetos do resumo, 16
    do `uuid`, 8 do instante em microssegundos desde a epoca (big-endian, o
    `int8send`) e 16 do `uuid`. Com largura fixa nao ha separador a escolher e
    nao ha duas concatenacoes com o mesmo resultado.

    `IMMUTABLE` e verdade, e e o que a deixa entrar num `CHECK`: a epoca de um
    `timestamptz` nao depende do `TimeZone` da sessao.
    """
    op.execute(
        """
        CREATE FUNCTION platform.contrato_evidencia(
            p_doc_sha256 bytea, p_signatario uuid, p_aceite_em timestamptz,
            p_otp_challenge_id uuid)
          RETURNS bytea
          LANGUAGE sql
          IMMUTABLE STRICT PARALLEL SAFE
        AS $$
          SELECT pg_catalog.sha256(
                   p_doc_sha256
                   || pg_catalog.uuid_send(p_signatario)
                   || pg_catalog.int8send(
                        (extract(epoch FROM p_aceite_em) * 1000000)::bigint)
                   || pg_catalog.uuid_send(p_otp_challenge_id))
        $$
        """
    )


def _documentos() -> None:
    op.execute(
        f"""
        CREATE TABLE {DOCUMENTOS} (
          document_id    uuid CONSTRAINT contract_document_pkey PRIMARY KEY
                         DEFAULT gen_random_uuid(),
          tipo           text NOT NULL
                         CONSTRAINT contract_document_tipo_ck
                         CHECK (tipo IN ({LITERAIS_DE_TIPO})),
          versao         text NOT NULL
                         CONSTRAINT contract_document_versao_ck
                         CHECK (versao ~ '{SEMVER}'),
          sha256         bytea NOT NULL,
          conteudo       text NOT NULL,
          vigente_desde  timestamptz NOT NULL,
          publicado_em   timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT contract_document_versao_uq UNIQUE (tipo, versao),
          CONSTRAINT contract_document_vigencia_uq UNIQUE (tipo, vigente_desde),
          CONSTRAINT contract_document_citavel_uq
            UNIQUE (document_id, versao, sha256),
          CONSTRAINT contract_document_sha256_ck
            CHECK (sha256 = pg_catalog.sha256(convert_to(conteudo, 'UTF8'))),
          CONSTRAINT contract_document_canonico_ck
            CHECK (conteudo IS NFC NORMALIZED
                   AND strpos(conteudo, E'\\r') = 0
                   AND btrim(conteudo) <> ''),
          CONSTRAINT contract_document_sem_retroactivo_ck
            CHECK (vigente_desde >= publicado_em)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {DOCUMENTOS} IS "
        "'Versoes publicadas de ToS, DPA, aviso de privacidade e lista de "
        "subprocessadores (KAM-090). Imutaveis: alterar e publicar versao nova. "
        "Texto juridico com marcadores ate ao parecer (KAM-104).'"
    )
    # O `sem_retroactivo`: uma versao nao pode ter estado vigente antes de ser
    # publicada. Sem ele, publicar hoje um DPA com `vigente_desde` no ano
    # passado reescrevia o que um tenant activado no ano passado tinha de ter
    # aceite — e a prova de um aceite antigo passava a parecer a de uma versao
    # que nao era a vigente.
    #
    # A imutabilidade e por *trigger* e nao so por privilegio, porque o
    # criterio diz «uma versao publicada e imutavel» e o ensaio adversarial
    # «alteracao de texto publicado => recusada»: o dono da tabela tambem leva
    # a recusa. O `DELETE` nao se concede a ninguem, e o de uma versao ja
    # aceite e impossivel tambem ao dono, pela FK do aceite.
    op.execute(
        """
        CREATE FUNCTION platform.contract_document_imutavel()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION
            'uma versao publicada de % e imutavel: alterar e publicar versao nova',
            OLD.tipo
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER contract_document_imutavel
          BEFORE UPDATE ON {DOCUMENTOS}
          FOR EACH ROW EXECUTE FUNCTION platform.contract_document_imutavel()
        """
    )


def _aceites() -> None:
    op.execute(
        f"""
        CREATE TABLE {ACEITES} (
          id                uuid CONSTRAINT contract_acceptance_pkey PRIMARY KEY
                            DEFAULT gen_random_uuid(),
          onboarding_id     uuid NOT NULL,
          tenant_id         uuid NOT NULL,
          document_id       uuid NOT NULL,
          versao            text NOT NULL,
          doc_sha256        bytea NOT NULL,
          signatario_ref    uuid NOT NULL,
          otp_challenge_id  uuid NOT NULL,
          ip_prefix_hash    bytea
                            CONSTRAINT contract_acceptance_ip_prefix_hash_ck
                            CHECK (octet_length(ip_prefix_hash) = 32),
          aceite_em         timestamptz NOT NULL DEFAULT now(),
          evidence_hash     bytea NOT NULL,
          CONSTRAINT contract_acceptance_aceite_uq
            UNIQUE (onboarding_id, document_id, versao),
          CONSTRAINT contract_acceptance_documento_fk
            FOREIGN KEY (document_id, versao, doc_sha256)
            REFERENCES {DOCUMENTOS} (document_id, versao, sha256),
          CONSTRAINT contract_acceptance_evidencia_ck
            CHECK (evidence_hash = platform.contrato_evidencia(
                     doc_sha256, signatario_ref, aceite_em, otp_challenge_id)),
          CONSTRAINT contract_acceptance_otp_de_um_caso_ex
            EXCLUDE USING gist (
              otp_challenge_id servicos.gist_uuid_ops WITH =,
              onboarding_id servicos.gist_uuid_ops WITH <>)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {ACEITES} IS "
        "'Prova de aceite de uma versao publicada (KAM-090). Append-only por "
        "privilegio: ninguem tem UPDATE nem DELETE. Sem PII: o signatario e uma "
        "referencia e o IP so entra como hash do prefixo (ADR-010).'"
    )
    # O gate le os aceites por tenant e por documento.
    op.execute(
        f"CREATE INDEX contract_acceptance_tenant_idx "
        f"ON {ACEITES} (tenant_id, document_id)"
    )
    op.execute(
        """
        CREATE FUNCTION platform.contract_acceptance_preparar()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_tipo    text;
          v_vigente uuid;
        BEGIN
          SELECT tipo INTO v_tipo
            FROM platform.contract_document
           WHERE document_id = NEW.document_id;
          IF v_tipo IS NULL THEN
            RAISE EXCEPTION 'documento % nao esta publicado', NEW.document_id
              USING ERRCODE = '23503';
          END IF;

          -- So a versao vigente se aceita. O gate so conta as vigentes, pelo
          -- que um aceite de uma antiga nunca activava ninguem — mas deixa-lo
          -- entrar punha na base uma prova de aceite de um texto que ja nao
          -- vigorava, que e o caso adversarial do bloco.
          SELECT document_id INTO v_vigente
            FROM platform.contract_document
           WHERE tipo = v_tipo
             AND vigente_desde <= now()
           ORDER BY vigente_desde DESC
           LIMIT 1;
          IF v_vigente IS DISTINCT FROM NEW.document_id THEN
            RAISE EXCEPTION
              'a versao % de % nao e a vigente', NEW.versao, v_tipo
              USING ERRCODE = '23514';
          END IF;

          -- A hora e a da base, e a evidencia calcula-se aqui: o que o chamador
          -- mandou nestas duas colunas e ignorado.
          NEW.aceite_em := now();
          NEW.evidence_hash := platform.contrato_evidencia(
            NEW.doc_sha256, NEW.signatario_ref, NEW.aceite_em,
            NEW.otp_challenge_id);
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER contract_acceptance_preparar
          BEFORE INSERT ON {ACEITES}
          FOR EACH ROW EXECUTE FUNCTION platform.contract_acceptance_preparar()
        """
    )
    rls.enable_tenant_rls("contract_acceptance")


def _gate() -> None:
    """O criterio 4 e a pergunta do criterio 8.

    `contrato_em_falta(tenant, so_vigentes)` devolve os tipos a que falta um
    aceite, por ordem. Sem documento vigente de um tipo, esse tipo **falta**: o
    gate nao abre por ausencia de texto publicado.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.contrato_em_falta(
            p_tenant_id uuid, p_so_vigentes boolean)
          RETURNS text[]
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT coalesce(array_agg(t.tipo ORDER BY t.tipo), ARRAY[]::text[])
            FROM unnest(ARRAY[{LITERAIS_DE_TIPO}]) AS t(tipo)
           WHERE NOT EXISTS (
                   SELECT 1
                     FROM platform.contract_acceptance a
                     JOIN platform.contract_document d
                       ON d.document_id = a.document_id
                    WHERE a.tenant_id = p_tenant_id
                      AND d.tipo = t.tipo
                      AND (NOT p_so_vigentes
                           OR d.document_id = (
                                SELECT v.document_id
                                  FROM platform.contract_document v
                                 WHERE v.tipo = t.tipo
                                   AND v.vigente_desde <= now()
                                 ORDER BY v.vigente_desde DESC
                                 LIMIT 1)))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.tenants_exige_aceite()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_falta text[];
        BEGIN
          IF NEW.estado <> 'ativo' THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.estado = 'ativo' THEN
            RETURN NEW;
          END IF;
          v_falta := platform.contrato_em_falta(
            NEW.id, TG_OP = 'INSERT' OR OLD.estado = 'onboarding');
          IF cardinality(v_falta) > 0 THEN
            RAISE EXCEPTION 'tenant sem DPA aceite nao activa'
              USING ERRCODE = '23514',
                    DETAIL = 'sem aceite: ' || array_to_string(v_falta, ', ');
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tenants_exige_aceite
          BEFORE INSERT OR UPDATE OF estado ON platform.tenants
          FOR EACH ROW EXECUTE FUNCTION platform.tenants_exige_aceite()
        """
    )
    # A verificacao diaria do criterio 8: os tenants `ativo` a que falta o
    # aceite de alguma versao **vigente**. Depois de uma versao nova do DPA, sao
    # todos os activos ate aceitarem — e e assim que a notificacao do criterio 6
    # sabe a quem escrever, sem que o gate os bloqueie.
    op.execute(
        """
        CREATE FUNCTION platform.dpa_em_falta()
          RETURNS TABLE (tenant_id uuid, em_falta text[])
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT f.tenant_id, f.em_falta
            FROM (SELECT t.id AS tenant_id,
                         platform.contrato_em_falta(t.id, true) AS em_falta
                    FROM platform.tenants t
                   WHERE t.estado = 'ativo') AS f
           WHERE cardinality(f.em_falta) > 0
           ORDER BY f.tenant_id
        $$
        """
    )


def _privilegios() -> None:
    """Quem le, quem escreve, e o que ninguem faz.

    A `contract_document` publica-se pelo lote (o *job* de ops que a carrega do
    repositorio) e le-se por todos; o aceite escreve-se pela aplicacao, que e
    quem serve o ecra. **Ninguem tem `UPDATE` nem `DELETE` em nenhuma das duas.**
    """
    op.execute(f"REVOKE ALL ON {DOCUMENTOS} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON {ACEITES} FROM PUBLIC")
    op.execute(f"GRANT SELECT ON {DOCUMENTOS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT, INSERT ON {DOCUMENTOS} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {DOCUMENTOS} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT, INSERT ON {ACEITES} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {ACEITES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {ACEITES} TO {PAPEL_DE_AUDITORIA}")

    op.execute(f"REVOKE ALL ON FUNCTION {FALTA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FALTA} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FALTA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FALTA} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"REVOKE ALL ON FUNCTION {DPA_EM_FALTA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {DPA_EM_FALTA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {DPA_EM_FALTA} TO {PAPEL_DE_AUDITORIA}")


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes: um objecto pendurado que esta
    # revisao nao criou faz o `downgrade` falhar em vez de cair em silencio.
    # **Este `downgrade` apaga as provas de aceite.** Nao se escreve copia
    # logica: uma base onde se desce esta revisao e uma base de ensaio, e numa
    # de producao a prova sai antes pela exportacao do criterio 9.
    op.execute("DROP TRIGGER tenants_exige_aceite ON platform.tenants")
    op.execute("DROP FUNCTION platform.tenants_exige_aceite()")
    op.execute(f"DROP FUNCTION {DPA_EM_FALTA}")
    op.execute(f"DROP FUNCTION {FALTA}")
    rls.disable_tenant_rls("contract_acceptance")
    op.execute(f"DROP TRIGGER contract_acceptance_preparar ON {ACEITES}")
    op.execute("DROP FUNCTION platform.contract_acceptance_preparar()")
    op.execute(f"DROP TABLE {ACEITES}")
    op.execute(f"DROP TRIGGER contract_document_imutavel ON {DOCUMENTOS}")
    op.execute("DROP FUNCTION platform.contract_document_imutavel()")
    op.execute(f"DROP TABLE {DOCUMENTOS}")
    op.execute(f"DROP FUNCTION {EVIDENCIA}")

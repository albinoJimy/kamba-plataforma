"""Identidade de contacto em duas camadas: contacts, contact_endpoints, DEK e versoes de chave (KAM-008).

Revisao: 0003
Anterior: 0002

O ADR-010 manda: `contact_id` aleatorio nas tabelas de negocio e nos eventos;
BSUID e telefone so cifrados, numa tabela a parte; o telefone nunca e chave.

Quatro tabelas, e a forma de cada uma tem fonte:

    contacts            a chave de negocio. Forma do dicionario §3.1
                        (`contacts(contact_id, tenant_id, criado_at, ...)`), com
                        `phone_hmac` e `erased_at` do `docs/tecnica/03` §5.3 e a
                        versao da chave (`hmac_kid`) que o ticket nomeia.
    contact_endpoints   o cofre. Forma do dicionario §3.1
                        (`contact_endpoints(contact_id, tipo, bsuid_hmac,
                        bsuid_enc, dek_id, phone_enc, ...)`).
    contact_deks        a chave de dados de cada contacto, embrulhada pela KEK
                        do cofre. Apagar a DEK e o *crypto-shredding* do
                        `docs/tecnica/06` §7.6.
    hmac_key_versions   metadados das versoes do segredo do HMAC. **Nunca o
                        segredo**: esse vive no cofre (`pepper_contact_hmac`).

**Onde vive o HMAC de pesquisa — a decisao que este ficheiro toma.** O bloco do
KAM-008 pede `lookup_hmac` e `UNIQUE (tenant_id, hmac_kid, lookup_hmac)` em
`contacts`; o dicionario §3.1 poe `bsuid_hmac` em `contact_endpoints`. O
dicionario prevalece sobre o ticket (ordem das fontes) e foi essa a forma que a
emenda D-01 do KAM-111 levou a `docs/tecnica/`. Aqui o HMAC do BSUID chama-se
`bsuid_hmac`, vive em `contact_endpoints`, e a unicidade e
`UNIQUE (tenant_id, hmac_kid, bsuid_hmac)` nessa tabela. E *proposta*: a
contradicao esta registada no dicionario (emenda 1.8) e devolvida ao KAM-141.

O que esta revisao **nao** faz, e de quem e:

    consentimento                KAM-022. `contacts.consentimento jsonb` do
                                 doc 03 §5.3 fica de fora (divergencia do KAM-140).
    contacts.papel               KAM-118.
    username, display_name,
    janela de 24 h               do doc 01 §6.2; a janela e do KAM-014.
    purga por `expira_at`        KAM-071. Aqui a coluna existe e mais nada.
    privilegios de kamba_batch   nenhum nestas tabelas. Quem purga e quem roda
                                 pede o que precisar, por revisao (KAM-071,
                                 KAM-072).

Tudo isto e SQL **proposto ate correr**: o gate 8 e o que o promove.
"""

from __future__ import annotations

import base64
import json
import os

from alembic import op

import rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

#: As tres tabelas com `tenant_id`, pela ordem das FK.
TABELAS_DE_TENANT = ("contacts", "contact_deks", "contact_endpoints")

#: O que a copia logica do `downgrade` leva, pela ordem em que se repoe: as
#: versoes de chave primeiro (as outras referem-nas). Sem elas, as linhas
#: copiadas nao se repunham — e qual era a `actual` e a `anterior` perdia-se.
TABELAS_COPIADAS = ("hmac_key_versions", "contacts", "contact_deks", "contact_endpoints")

#: Os donos de tenant (`tenants.owner_contact_id`), que o `downgrade` anula.
SQL_DONOS = (
    "SELECT id, owner_contact_id FROM platform.tenants WHERE owner_contact_id IS NOT NULL"
)

#: Colunas de `contacts` que `kamba_app` le. O `contact_id` e a chave que as
#: tabelas de negocio vao referenciar; `erased_at` e a fusao dizem se o contacto
#: ainda e alguem. `phone_hmac` e `hmac_kid` ficam de fora: um HMAC de telefone
#: e pseudonimizacao, nao anonimizacao (doc 08 §7.2), e a aplicacao nao precisa
#: dele para nada que este ticket conheca.
COLUNAS_DA_APP = (
    "contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",
)

#: O que o modulo de identidade altera depois do *insert*, coluna a coluna.
#:
#:   contacts            o telefone (completar, trocar, rodar a chave), o
#:                       apagamento e a fusao. Nunca `tenant_id` nem `contact_id`.
#:   contact_endpoints   mudar de contacto (fusao), rodar o HMAC, renovar o
#:                       telefone guardado. Nunca `tenant_id`, `tipo` nem
#:                       `bsuid_enc`.
#:   contact_deks        mudar de contacto (fusao), reembrulhar com outra KEK e
#:                       destruir. Nunca `tenant_id`.
UPDATE_DA_IDENTIDADE = {
    "contacts": ("phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at"),
    "contact_endpoints": (
        "contact_id", "bsuid_hmac", "hmac_kid", "phone_enc", "dek_id",
        "recolhido_at", "expira_at",
    ),
    "contact_deks": ("contact_id", "wrapped_dek", "kek_id", "destroyed_at"),
}

#: Variavel com o caminho do ficheiro de copia logica que o `downgrade` escreve.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0003_COPIA"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.hmac_key_versions (
          kid        text CONSTRAINT hmac_key_versions_pkey PRIMARY KEY
                     CONSTRAINT hmac_key_versions_kid_ck
                     CHECK (kid ~ '^[a-z0-9][a-z0-9_.-]{0,62}$'),
          estado     text NOT NULL
                     CONSTRAINT hmac_key_versions_estado_ck
                     CHECK (estado IN ('actual','anterior','retirada')),
          criado_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.hmac_key_versions IS
          'Metadados das versoes do segredo do HMAC de contactos. Nunca o segredo: esse vive no cofre.'
        """
    )
    # No maximo uma versao `actual` e uma `anterior`: sao as duas que a pesquisa
    # tenta durante a janela de rotacao.
    op.execute(
        """
        CREATE UNIQUE INDEX hmac_key_versions_actual_uq
          ON platform.hmac_key_versions (estado) WHERE estado = 'actual'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX hmac_key_versions_anterior_uq
          ON platform.hmac_key_versions (estado) WHERE estado = 'anterior'
        """
    )

    op.execute(
        """
        CREATE TABLE platform.contacts (
          contact_id   uuid CONSTRAINT contacts_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id    uuid NOT NULL
                       CONSTRAINT contacts_tenant_fk
                       REFERENCES platform.tenants (id),
          phone_hmac   bytea
                       CONSTRAINT contacts_phone_hmac_ck
                       CHECK (octet_length(phone_hmac) = 32),
          hmac_kid     text
                       CONSTRAINT contacts_hmac_kid_fk
                       REFERENCES platform.hmac_key_versions (kid),
          criado_at    timestamptz NOT NULL DEFAULT now(),
          erased_at    timestamptz,
          merged_into  uuid,
          merged_at    timestamptz,
          CONSTRAINT contacts_tenant_contact_uq UNIQUE (tenant_id, contact_id),
          CONSTRAINT contacts_phone_par_ck
            CHECK ((phone_hmac IS NULL) = (hmac_kid IS NULL)),
          CONSTRAINT contacts_merged_fk
            FOREIGN KEY (tenant_id, merged_into)
            REFERENCES platform.contacts (tenant_id, contact_id),
          CONSTRAINT contacts_merged_par_ck
            CHECK ((merged_into IS NULL) = (merged_at IS NULL)),
          CONSTRAINT contacts_merged_outro_ck
            CHECK (merged_into <> contact_id),
          CONSTRAINT contacts_inactivo_sem_phone_ck
            CHECK ((erased_at IS NULL AND merged_into IS NULL) OR phone_hmac IS NULL)
        )
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.contacts.phone_hmac IS
          'HMAC-SHA256 do telefone normalizado, com o segredo do cofre. Pseudonimizacao, nao anonimizacao: continua dado pessoal (doc 08 §7.2).'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.contacts.merged_into IS
          'Contacto que absorveu este numa fusao. A linha fica como lapide: quem ainda tiver o contact_id antigo chega ao novo.'
        """
    )
    # Um telefone identifica um contacto por tenant: dois contactos com o mesmo
    # telefone revelaram-se o mesmo e fundem-se. `tenant_id` em primeiro lugar,
    # que e o predicado que a RLS acrescenta a todas as consultas.
    op.execute(
        """
        CREATE UNIQUE INDEX contacts_phone_hmac_uq
          ON platform.contacts (tenant_id, hmac_kid, phone_hmac)
          WHERE phone_hmac IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE platform.contact_deks (
          dek_id        uuid CONSTRAINT contact_deks_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id     uuid NOT NULL
                        CONSTRAINT contact_deks_tenant_fk
                        REFERENCES platform.tenants (id),
          contact_id    uuid NOT NULL,
          wrapped_dek   bytea,
          kek_id        text NOT NULL
                        CONSTRAINT contact_deks_kek_id_ck
                        CHECK (kek_id <> '' AND kek_id = btrim(kek_id)),
          criado_at     timestamptz NOT NULL DEFAULT now(),
          destroyed_at  timestamptz,
          CONSTRAINT contact_deks_tenant_dek_uq UNIQUE (tenant_id, dek_id),
          CONSTRAINT contact_deks_contact_fk
            FOREIGN KEY (tenant_id, contact_id)
            REFERENCES platform.contacts (tenant_id, contact_id),
          CONSTRAINT contact_deks_destruida_ck
            CHECK ((wrapped_dek IS NULL) = (destroyed_at IS NOT NULL))
        )
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.contact_deks.wrapped_dek IS
          'DEK do contacto embrulhada pela KEK do cofre (kek_id). NULL depois de destruida: e o crypto-shredding do doc 06 §7.6.'
        """
    )
    op.execute(
        """
        CREATE INDEX contact_deks_tenant_contact_idx
          ON platform.contact_deks (tenant_id, contact_id)
        """
    )

    op.execute(
        """
        CREATE TABLE platform.contact_endpoints (
          id            uuid CONSTRAINT contact_endpoints_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id     uuid NOT NULL
                        CONSTRAINT contact_endpoints_tenant_fk
                        REFERENCES platform.tenants (id),
          contact_id    uuid NOT NULL,
          tipo          text NOT NULL
                        CONSTRAINT contact_endpoints_tipo_ck
                        CHECK (tipo IN ('bsuid','telefone')),
          bsuid_hmac    bytea
                        CONSTRAINT contact_endpoints_bsuid_hmac_ck
                        CHECK (octet_length(bsuid_hmac) = 32),
          hmac_kid      text
                        CONSTRAINT contact_endpoints_hmac_kid_fk
                        REFERENCES platform.hmac_key_versions (kid),
          bsuid_enc     bytea,
          phone_enc     bytea,
          dek_id        uuid NOT NULL,
          finalidade    text
                        CONSTRAINT contact_endpoints_finalidade_ck
                        CHECK (finalidade IN ('pagamento_express','entrega','contacto_pedido')),
          recolhido_at  timestamptz NOT NULL DEFAULT now(),
          expira_at     timestamptz,
          CONSTRAINT contact_endpoints_contact_fk
            FOREIGN KEY (tenant_id, contact_id)
            REFERENCES platform.contacts (tenant_id, contact_id),
          CONSTRAINT contact_endpoints_dek_fk
            FOREIGN KEY (tenant_id, dek_id)
            REFERENCES platform.contact_deks (tenant_id, dek_id),
          CONSTRAINT contact_endpoints_bsuid_uq UNIQUE (tenant_id, hmac_kid, bsuid_hmac),
          CONSTRAINT contact_endpoints_forma_ck CHECK (
            (tipo = 'bsuid'
               AND bsuid_hmac IS NOT NULL AND hmac_kid IS NOT NULL
               AND bsuid_enc IS NOT NULL AND phone_enc IS NULL
               AND finalidade IS NULL)
            OR
            (tipo = 'telefone'
               AND phone_enc IS NOT NULL AND bsuid_enc IS NULL
               AND bsuid_hmac IS NULL AND hmac_kid IS NULL
               AND finalidade IS NOT NULL AND expira_at IS NOT NULL)
          )
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.contact_endpoints IS
          'Cofre de identidade: BSUID e telefone so cifrados (AES-256-GCM, DEK por contacto). So kamba_identity le; nunca entra em joins de negocio (ADR-010).'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.contact_endpoints.expira_at IS
          'Fim da retencao do endpoint. Obrigatorio no telefone; os valores sao de quem chama e estao por confirmar por parecer. A purga e do KAM-071.'
        """
    )
    # Um telefone guardado por contacto e por finalidade: guardar outra vez
    # renova a linha, nao acumula copias do mesmo numero.
    op.execute(
        """
        CREATE UNIQUE INDEX contact_endpoints_telefone_uq
          ON platform.contact_endpoints (tenant_id, contact_id, finalidade)
          WHERE tipo = 'telefone'
        """
    )
    op.execute(
        """
        CREATE INDEX contact_endpoints_tenant_contact_idx
          ON platform.contact_endpoints (tenant_id, contact_id)
        """
    )

    # A FK que o KAM-003 deixou por criar. Composta: o dono de um tenant e um
    # contacto **desse** tenant — com a FK simples do doc 03 §5.3, um tenant
    # podia apontar para o contacto de outro. Diferida, porque o tenant e o seu
    # primeiro contacto nascem na mesma transaccao e referem-se um ao outro.
    #
    # O `FORCE` de `tenants` sai e volta a entrar a volta do `ADD CONSTRAINT`, e
    # nao e cosmetica: o PostgreSQL valida as linhas existentes com uma consulta
    # feita pelo dono da tabela, e com `FORCE` o dono — sem contexto de tenant —
    # ve **zero linhas**. A validacao passava sem ter olhado para nada, e um
    # `owner_contact_id` orfao ficava debaixo de uma FK que diz que nao ha
    # orfaos (medido contra o PostgreSQL 18.6: a primeira versao desta revisao
    # aceitava-o). Ate aqui a coluna nao tinha FK nem tabela para onde apontar,
    # pelo que qualquer valor nao nulo e orfao: o `upgrade` falha, e quem o corre
    # decide o que fazer a essas linhas. O intervalo sem `FORCE` nao se ve de
    # fora — e a mesma transaccao, com a tabela trancada.
    op.execute("ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        ALTER TABLE platform.tenants
          ADD CONSTRAINT tenants_owner_fk
          FOREIGN KEY (id, owner_contact_id)
          REFERENCES platform.contacts (tenant_id, contact_id)
          DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        COMMENT ON COLUMN platform.tenants.owner_contact_id IS
          'Contacto do dono, do proprio tenant (FK composta e diferida, KAM-008).'
        """
    )

    for tabela in TABELAS_DE_TENANT:
        rls.enable_tenant_rls(tabela)

    # Privilegios, tabela a tabela e coluna a coluna, como na 0001.
    #
    # `kamba_app` le de `contacts` so as colunas de que um *join* de negocio
    # precisa, e **nao escreve** em nenhuma destas tabelas: um contacto nasce,
    # funde-se e apaga-se so pelo modulo de identidade. Nao tem `UPDATE` por
    # coluna porque nao tem `UPDATE` de todo, e continua sem `DELETE`.
    #
    # `kamba_identity` e o unico papel que le `contact_endpoints` e
    # `contact_deks`. Tem `DELETE` em `contact_endpoints` e so ai: o apagamento
    # a pedido do titular e um `DELETE` verdadeiro — o «soft delete» do
    # dicionario §2 vale para dados operacionais, nao para dados pessoais
    # (doc 06 §7.6). Nao contorna a RLS: trabalha um tenant de cada vez.
    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_identity")
    op.execute(
        f"GRANT SELECT ({', '.join(COLUNAS_DA_APP)}) ON platform.contacts TO kamba_app"
    )
    op.execute(
        """
        GRANT SELECT, INSERT
          ON platform.contacts, platform.contact_deks, platform.contact_endpoints,
             platform.hmac_key_versions
          TO kamba_identity
        """
    )
    for tabela, colunas in UPDATE_DA_IDENTIDADE.items():
        op.execute(
            f"GRANT UPDATE ({', '.join(colunas)}) ON platform.{tabela} TO kamba_identity"
        )
    op.execute("GRANT UPDATE (estado) ON platform.hmac_key_versions TO kamba_identity")
    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")


def _copia_logica() -> None:
    """Escreve as linhas de identidade num ficheiro, ou recusa o `downgrade`.

    Leva as quatro tabelas da revisao e os donos de tenant
    (`tenants.owner_contact_id`), que o passo anula a seguir: sem a FK e sem
    `contacts`, um dono preenchido ficava a apontar para nada — e o `upgrade`
    seguinte, que recusa orfaos, deixava de subir.

    O `downgrade` apaga `contact_endpoints`: BSUID e telefone cifrados que nao
    se voltam a obter (o telefone pode nunca mais vir num webhook). Uma perda
    dessas nao pode ser silenciosa. Com linhas em qualquer das tres tabelas, o
    passo so avanca se `KAMBA_DOWNGRADE_0003_COPIA` apontar para um ficheiro
    **novo**, onde ficam todas as linhas, uma por linha de JSON (os `bytea` em
    base64). O ficheiro nao tem nada em claro que a base nao tivesse: so HMAC,
    cifra e DEK embrulhadas — mas continua a ser dado pessoal, e guarda-se como
    tal.

    Corre **depois** de a RLS ser desligada: o dono das tabelas esta sujeito ao
    `FORCE`, e sem contexto leria zero linhas — a copia sairia vazia e o passo
    apagaria tudo com um ficheiro que parecia prova.
    """
    contagens = _contar()
    if not any(contagens.values()):
        return

    destino = os.environ.get(VARIAVEL_DA_COPIA, "")
    resumo = ", ".join(
        f"{'donos de tenant' if tabela == 'tenants' else tabela}: {n}"
        for tabela, n in contagens.items()
    )
    if not destino:
        raise RuntimeError(
            f"downgrade da 0003 recusado: ha linhas de identidade ({resumo}) e o "
            f"passo apaga-as. Defina {VARIAVEL_DA_COPIA} com o caminho de um "
            "ficheiro novo para a copia logica, ou esvazie as tabelas de proposito."
        )

    # Modo `x`: nunca por cima de uma copia anterior. 0600: so quem a fez a le.
    descritor = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    escritas = dict.fromkeys(contagens, 0)
    with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as ficheiro:
        for origem, registo in _linhas():
            ficheiro.write(
                json.dumps({"tabela": origem, "linha": registo}, sort_keys=True) + "\n"
            )
            escritas[origem] += 1
        ficheiro.flush()
        os.fsync(ficheiro.fileno())
    if escritas != contagens:
        raise RuntimeError(
            f"downgrade da 0003 recusado: a copia tem {escritas} e as tabelas "
            f"tem {contagens}"
        )


# As duas funcoes abaixo nao recebem argumentos, e nao e por gosto: o gate 3b
# le esta revisao sem a correr, e so segue uma chamada cujos argumentos consiga
# resolver. Um `for` sobre uma constante de modulo, ele desdobra.


def _contar() -> dict[str, int]:
    """Linhas em cada uma das quatro tabelas, e quantos tenants tem dono."""
    contagens = {}
    for tabela in TABELAS_COPIADAS:
        contagens[tabela] = op.get_bind().exec_driver_sql(
            f"SELECT count(*) FROM platform.{tabela}"
        ).scalar_one()
    contagens["tenants"] = len(op.get_bind().exec_driver_sql(SQL_DONOS).fetchall())
    return contagens


def _celula(valor):
    """Um valor de coluna em JSON: os `bytea` em base64, o resto como texto."""
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(valor)).decode("ascii")}
    return None if valor is None else str(valor)


def _linhas():
    """Todas as linhas a copiar: (tabela, {coluna: valor em JSON}).

    As quatro tabelas por inteiro; de `tenants`, so o par (`id`,
    `owner_contact_id`) de quem tem dono.
    """
    for tabela in TABELAS_COPIADAS:
        resultado = op.get_bind().exec_driver_sql(f"SELECT * FROM platform.{tabela}")
        colunas = list(resultado.keys())
        for linha in resultado:
            yield tabela, {c: _celula(v) for c, v in zip(colunas, linha)}
    for identificador, dono in op.get_bind().exec_driver_sql(SQL_DONOS):
        yield "tenants", {"id": _celula(identificador), "owner_contact_id": _celula(dono)}


def downgrade() -> None:
    op.execute("ALTER TABLE platform.tenants DROP CONSTRAINT tenants_owner_fk")
    op.execute(
        """
        COMMENT ON COLUMN platform.tenants.owner_contact_id IS
          'Sem FK nesta revisao: platform.contacts e do KAM-008, que acrescenta a FK diferida.'
        """
    )

    # `tenants` fica sem `FORCE` enquanto o passo le e anula os donos: com
    # ele, o dono da tabela — sem contexto — via zero linhas, a copia saia sem
    # donos e o `UPDATE` nao anulava nenhum. Volta a entrar mais abaixo; e a
    # mesma transaccao, com a tabela trancada.
    op.execute(
        "ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY"
    )

    # Pela ordem inversa das FK, e por extenso: o gate 3b le esta revisao sem
    # a correr, e nao segue um `reversed(...)`.
    rls.disable_tenant_rls("contact_endpoints")
    rls.disable_tenant_rls("contact_deks")
    rls.disable_tenant_rls("contacts")

    _copia_logica()

    # Sem `contacts`, um dono preenchido apontava para nada, e o `upgrade`
    # seguinte recusava-o. Os pares (tenant, dono) estao na copia.
    op.execute(
        "UPDATE platform.tenants SET owner_contact_id = NULL "
        "WHERE owner_contact_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY"
    )

    # Os `GRANT` sobre as tabelas vao com elas; o do schema nao.
    op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_identity")

    op.execute("DROP TABLE platform.contact_endpoints")
    op.execute("DROP TABLE platform.contact_deks")
    op.execute("DROP TABLE platform.contacts")
    op.execute("DROP TABLE platform.hmac_key_versions")

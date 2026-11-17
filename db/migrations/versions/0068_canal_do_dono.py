"""Canal do dono: contacts.papel, owner_actions e a porta definir_dono (KAM-118).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero e provisorio

`down_revision = "0066"` e o que corre hoje sobre a `publico/main`. O
orquestrador deu a `0067` ao KAM-098: **na integracao esta revisao passa a
assentar na `0067`** (ou renumera-se, pela regra da casa — quem funde em
segundo renumera, e nunca por `sed`). Os ensaios descobrem-na pelo *glob*
`*_canal_do_dono.py` e leem o `down_revision` daqui, pelo que nao mudam.

## O que esta revisao cria

| Objecto | Para que serve |
|---|---|
| `platform.contacts.papel` | `cliente` ou `dono`; nasce `cliente` |
| `platform.contacts.papel_mudou_at` | quando o papel mudou por troca de telefone; e o que arma o bloqueio de 24 h das accoes sensiveis |
| `contacts_um_dono` | indice unico parcial: **no maximo um** `dono` por tenant |
| `platform.owner_actions` | as accoes sensiveis a espera do botao `confirm:{action_id}` |
| `platform.definir_dono(p_contact_id, p_origem)` | a **unica** porta que muda o `papel` |

## O papel so muda pela porta, e porque e uma propriedade da base

O criterio 2 do bloco diz que o `papel` so muda por OTP validado ou pela saga,
e que 20 textos adversariais dao **zero** alteracoes. Se isto fosse uma
convencao do codigo do CHR, bastava um `UPDATE` esquecido num modulo qualquer
para que «sou o dono» passasse a ser uma promocao. Por isso:

* **Ninguem tem `UPDATE (papel)`** nem `UPDATE (papel_mudou_at)`. O
  `kamba_identity` mantem o `UPDATE` por coluna da `0003`, que nao as inclui.
* **O `INSERT` do `kamba_identity` passa a ser por coluna**, sem o `papel` nem
  o `papel_mudou_at`. Com o `INSERT` de tabela da `0003`, as colunas novas
  ficavam concedidas sem ninguem o ter escrito, e um contacto podia **nascer**
  `dono` num tenant que ainda nao o tem — a mesma escalada que o `UPDATE`
  negado fechava, por outro verbo (a licao da `0007` com o `entitlements`).
  Os `INSERT` do modulo de identidade ja nomeiam as colunas (o
  `SQL_CRIAR_CONTACTO` do `packages/core-ts/src/identity/consultas.ts`), e nao
  mudam.
* **A porta e `SECURITY DEFINER`** e so o `kamba_identity` a executa. Com
  `SECURITY INVOKER`, a excepcao mudava de sitio e ficava maior: era preciso
  conceder `UPDATE (papel)` a quem a chama.

O `DEFINER` da privilegio e nao da isolamento: o `kamba_migrator` e
`NOBYPASSRLS` e o `FORCE` vincula o dono das tabelas (`db/rls.py`), pelo que a
`tenant_iso` continua a avaliar com o `app.tenant_id` de quem chamou — na
`contacts` e na `tenants` (politica pela coluna `id`, `0002`). **O tenant vem
so do contexto** e nao e argumento: um contacto de outro tenant nao se
encontra, e recusa com `23503`.

## As recusas da porta

    origem     `provisionamento` ou `troca_de_telefone`; outra coisa -> `22023`
    contexto   sem `app.tenant_id` -> `42501`
    tenant     o do contexto nao existe -> `23503`
    contacto   inexistente, apagado (`erased_at`) ou fundido (`merged_into`)
               no tenant -> `23503`
    reentrega  o contacto ja e o dono -> devolve `NULL` e nada muda (a
               reentrega da saga, criterio 3: 3x -> 1 dono)
    saga       ja ha **outro** dono e a origem e `provisionamento` -> `23505`:
               uma reentrega do `tenant.provisioned` nao troca o dono
    lapide     o dono que la esta foi apagado ou fundido -> **nao** recusa: a
               lapide passa a `cliente` e o lugar fica livre. Sem isto, um dono
               absorvido pelo `#fundir` (que nao leva o papel) ou apagado a
               pedido do titular prendia o `contacts_um_dono` para sempre, e a
               saga recusava com `23505` (achado da revisao adversarial)

## A concorrencia

A porta tranca primeiro a linha do tenant (`FOR UPDATE`). Duas chamadas sobre o
mesmo tenant serializam-se ali, e em `READ COMMITTED` a segunda le o dono que a
primeira deixou: duas trocas concorrentes dao duas trocas seguidas e nunca dois
donos. O `contacts_um_dono` e a segunda barreira, a que vale para quem nao
passe por aqui.

## O preenchimento

Um tenant que ja tenha `owner_contact_id` (o provisioning do KAM-092 escreve-o
pelo lote) ganha o seu `dono` nesta revisao, se o contacto estiver activo. Sem
isto, o dono que a saga ja escolheu era `cliente` ate a proxima reentrega — que
em producao nao chega, porque o `tenant.provisioned` ainda nao e emitido. O
`papel_mudou_at` fica nulo: nao houve troca.

## O `downgrade`

Larga a porta, a `owner_actions`, o indice e as duas colunas, e repoe o
`INSERT` de tabela do `kamba_identity` da `0003`. **Sem recusa**: as linhas da
`owner_actions` sao fichas de confirmacao de 15 minutos (*proposta*), e o
registo de uma accao executada e da accao (o `audit_log` de quem a executa),
nao da ficha. O `owner_contact_id` dos tenants fica como esta: e da `0001`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0068"
#: **Provisorio**: na integracao passa a `0067` (KAM-098). Ver o cabecalho.
down_revision = "0066"
branch_labels = None
depends_on = None

CONTACTOS = "platform.contacts"
TENANTS = "platform.tenants"
ACCOES = "platform.owner_actions"
INDICE = "contacts_um_dono"

#: A assinatura, para o `COMMENT`, o `GRANT` e o `DROP`. Escrita uma vez, pela
#: licao do KAM-175: um nome repetido em tres instrucoes desvia-se numa delas.
ASSINATURA = "platform.definir_dono(uuid, text)"

#: O papel que corre o modulo de identidade (OTP e saga) e o unico com `EXECUTE`.
PAPEL_DA_IDENTIDADE = "kamba_identity"

#: As colunas da `contacts` que o `kamba_identity` pode escrever num `INSERT`:
#: as da `0003`, **sem** o `papel` e o `papel_mudou_at`. Um contacto nasce
#: `cliente` (o `DEFAULT`), e so a porta o promove.
INSERT_DA_IDENTIDADE = (
    "contact_id", "tenant_id", "phone_hmac", "hmac_kid", "criado_at",
    "erased_at", "merged_into", "merged_at",
)

#: O que o `kamba_app` le de novo na `contacts`: o CHR decide a persona pelo
#: `papel`, e o portao das accoes sensiveis pelo `papel_mudou_at`.
SELECT_DA_APP = ("papel", "papel_mudou_at")

#: O que o `kamba_app` muda numa accao: so o desfecho. Mudar o `contact_id`, o
#: `tipo`, a `ref` ou o `expira_at` era confirmar outra coisa, ou empurrar o
#: prazo do botao.
UPDATE_DA_APP = ("estado", "confirmada_at")


def upgrade() -> None:
    _papel()
    _preencher()
    _accoes()
    _porta()
    _privilegios()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {ASSINATURA}")
    # Revogar o `INSERT` de tabela leva tambem as concessoes por coluna do mesmo
    # privilegio; a seguir repoe-se exactamente o que a `0003` concedeu.
    op.execute(f"REVOKE INSERT ON {CONTACTOS} FROM {PAPEL_DA_IDENTIDADE}")
    op.execute(f"GRANT INSERT ON {CONTACTOS} TO {PAPEL_DA_IDENTIDADE}")
    rls.disable_tenant_rls("owner_actions")
    op.execute(f"DROP TABLE {ACCOES}")
    op.execute(f"DROP INDEX platform.{INDICE}")
    # As concessoes por coluna do `kamba_app` saem com as colunas.
    op.execute(f"ALTER TABLE {CONTACTOS} DROP COLUMN papel_mudou_at")
    op.execute(f"ALTER TABLE {CONTACTOS} DROP COLUMN papel")


def _papel() -> None:
    """As duas colunas e o indice do «no maximo um dono».

    O indice e **parcial** e so pelo `tenant_id`: uma linha por tenant entre as
    que sao `dono`, e nenhuma restricao entre os `cliente`. Nao e diferivel (um
    indice nao o e), pelo que quem troca o dono despromove o anterior primeiro.
    """
    op.execute(
        f"""
        ALTER TABLE {CONTACTOS}
          ADD COLUMN papel text NOT NULL DEFAULT 'cliente'
            CONSTRAINT contacts_papel_ck CHECK (papel IN ('cliente', 'dono')),
          ADD COLUMN papel_mudou_at timestamptz
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {INDICE} ON {CONTACTOS} (tenant_id) WHERE papel = 'dono'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONTACTOS}.papel IS "
        "'cliente ou dono (KAM-118). No maximo um dono por tenant (contacts_um_dono). "
        "Ninguem tem UPDATE nem INSERT nesta coluna: so a platform.definir_dono a muda, "
        "chamada pelo kamba_identity depois de um OTP validado ou pela saga.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONTACTOS}.papel_mudou_at IS "
        "'Quando o papel mudou por troca de telefone (KAM-118). Nulo no provisionamento. "
        "Arma o bloqueio de 24 h das accoes sensiveis (proposta).'"
    )


def _preencher() -> None:
    """O dono que o provisioning ja escreveu no `owner_contact_id` (cabecalho).

    **Corre com o `FORCE` desligado** nas duas tabelas, pela licao da `0003` e
    da `0046`: a ligacao do Alembic e dona delas, o `FORCE` sujeita-a a
    `tenant_iso`, e sem `app.tenant_id` o `UPDATE` via zero linhas — o
    preenchimento passava sem ter feito nada. E a mesma transaccao, com as
    tabelas trancadas.
    """
    op.execute(f"ALTER TABLE {TENANTS} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {CONTACTOS} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        UPDATE {CONTACTOS} c SET papel = 'dono'
          FROM {TENANTS} t
         WHERE t.id = c.tenant_id AND t.owner_contact_id = c.contact_id
           AND c.erased_at IS NULL AND c.merged_into IS NULL
        """
    )
    op.execute(f"ALTER TABLE {CONTACTOS} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TENANTS} FORCE ROW LEVEL SECURITY")


def _accoes() -> None:
    """A ficha de cada accao sensivel a espera do botao `confirm:{action_id}`.

    O `UNIQUE (tenant_id, tipo, ref)` e a idempotencia da criacao (ADR-009): a
    mesma accao pedida duas vezes e uma ficha. O `owner_actions_confirmada_ck`
    prende o desfecho a data: uma ficha `confirmada` sem `confirmada_at`, ou ao
    contrario, nao existe. A confirmacao e um `UPDATE ... WHERE estado =
    'pendente' AND expira_at > now() RETURNING`, e e esse predicado que faz o
    duplo toque dar uma execucao.
    """
    op.execute(
        f"""
        CREATE TABLE {ACCOES} (
          action_id     uuid CONSTRAINT owner_actions_pkey PRIMARY KEY
                        DEFAULT gen_random_uuid(),
          tenant_id     uuid NOT NULL,
          contact_id    uuid NOT NULL,
          tipo          text NOT NULL
                        CONSTRAINT owner_actions_tipo_ck
                        CHECK (tipo IN ('preco_stock_em_massa', 'aprovar_conteudo',
                                        'enviar_proposta')),
          ref           text NOT NULL
                        CONSTRAINT owner_actions_ref_ck
                        CHECK (char_length(ref) BETWEEN 1 AND 200),
          estado        text NOT NULL DEFAULT 'pendente'
                        CONSTRAINT owner_actions_estado_ck
                        CHECK (estado IN ('pendente', 'confirmada', 'expirada',
                                          'cancelada')),
          criado_at     timestamptz NOT NULL DEFAULT now(),
          expira_at     timestamptz NOT NULL,
          confirmada_at timestamptz,
          CONSTRAINT owner_actions_confirmada_ck
            CHECK ((estado = 'confirmada') = (confirmada_at IS NOT NULL)),
          CONSTRAINT owner_actions_uq UNIQUE (tenant_id, tipo, ref),
          CONSTRAINT owner_actions_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES {TENANTS} (id),
          CONSTRAINT owner_actions_contact_fk FOREIGN KEY (tenant_id, contact_id)
            REFERENCES {CONTACTOS} (tenant_id, contact_id)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {ACCOES} IS "
        "'Accoes sensiveis do dono a espera do botao confirm:{{action_id}} (KAM-118). "
        "So o mesmo contact_id confirma, uma vez, antes do expira_at. Sem DELETE para "
        "ninguem: uma ficha fecha-se pelo estado.'"
    )
    rls.enable_tenant_rls("owner_actions")


def _porta() -> None:
    """A porta, com as recusas do cabecalho.

    O `SET search_path = pg_catalog, platform` e **sem `public`**, pela razao da
    `0029`: num `SECURITY DEFINER`, um schema onde o chamador crie objectos
    deixava-o sombrear uma funcao que este corpo chama.

    A ordem das escritas e a do indice: o anterior passa a `cliente` **antes** de
    o novo passar a `dono`, porque o `contacts_um_dono` verifica linha a linha.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.definir_dono(p_contact_id uuid, p_origem text)
          RETURNS uuid
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_tenant   uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
          v_anterior uuid;
          v_lapide   boolean;
        BEGIN
          IF p_origem IS NULL OR p_origem NOT IN ('provisionamento', 'troca_de_telefone') THEN
            RAISE EXCEPTION
              'definir_dono: a origem % nao e provisionamento nem troca_de_telefone',
              p_origem
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          IF v_tenant IS NULL THEN
            RAISE EXCEPTION
              'definir_dono: sem app.tenant_id nao ha tenant; o tenant vem so do contexto'
              USING ERRCODE = 'insufficient_privilege';
          END IF;

          -- A tranca do tenant serializa as chamadas sobre o mesmo tenant
          -- (cabecalho, «A concorrencia»). Lida sob RLS: so o do contexto.
          PERFORM 1 FROM {TENANTS} t WHERE t.id = v_tenant FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'definir_dono: o tenant do contexto nao existe'
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          PERFORM 1 FROM {CONTACTOS} c
           WHERE c.tenant_id = v_tenant AND c.contact_id = p_contact_id
             AND c.erased_at IS NULL AND c.merged_into IS NULL
           FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'definir_dono: o contacto % nao existe neste tenant, foi apagado ou '
              'foi fundido noutro', p_contact_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          SELECT c.contact_id, (c.erased_at IS NOT NULL OR c.merged_into IS NOT NULL)
            INTO v_anterior, v_lapide
            FROM {CONTACTOS} c
           WHERE c.tenant_id = v_tenant AND c.papel = 'dono'
           FOR UPDATE;
          IF v_anterior = p_contact_id THEN
            RETURN NULL;
          END IF;
          IF v_anterior IS NOT NULL AND p_origem = 'provisionamento' AND NOT v_lapide THEN
            RAISE EXCEPTION
              'definir_dono: o tenant ja tem outro dono; uma reentrega da saga nao '
              'troca o dono, so a troca de telefone com OTP o faz'
              USING ERRCODE = 'unique_violation';
          END IF;

          IF v_anterior IS NOT NULL THEN
            UPDATE {CONTACTOS} SET papel = 'cliente', papel_mudou_at = now()
             WHERE tenant_id = v_tenant AND contact_id = v_anterior;
          END IF;
          UPDATE {CONTACTOS}
             SET papel = 'dono',
                 papel_mudou_at = CASE WHEN p_origem = 'troca_de_telefone' THEN now() END
           WHERE tenant_id = v_tenant AND contact_id = p_contact_id;
          UPDATE {TENANTS} SET owner_contact_id = p_contact_id WHERE id = v_tenant;
          RETURN v_anterior;
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {ASSINATURA} IS "
        "'A unica porta que muda contacts.papel (KAM-118). Tenant so do app.tenant_id. "
        "provisionamento: idempotente, e recusa (23505) se ja ha outro dono. "
        "troca_de_telefone: o anterior passa a cliente, o novo a dono, papel_mudou_at "
        "nos dois e tenants.owner_contact_id no novo. Devolve o dono anterior ou NULL. "
        "EXECUTE so para o kamba_identity.'"
    )


def _privilegios() -> None:
    """Os privilegios novos, e o `INSERT` por coluna do `kamba_identity` (cabecalho).

    O `REVOKE ALL ... FROM PUBLIC` da funcao primeiro, pela razao da `0029`: uma
    funcao nasce com `EXECUTE` para `PUBLIC`, e sem este passo o `kamba_app`
    chamava-a.

    Na `owner_actions`, o `kamba_app` cria a ficha, le-a e fecha-a, sem
    `DELETE`. O `kamba_resolver` nao lhe toca (o bloco, «Isolamento»), nem
    ninguem mais: o `kamba_audit` le o `audit_log` de quem executa a accao.
    """
    op.execute(f"REVOKE ALL ON FUNCTION {ASSINATURA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ASSINATURA} TO {PAPEL_DA_IDENTIDADE}")

    op.execute(f"REVOKE INSERT ON {CONTACTOS} FROM {PAPEL_DA_IDENTIDADE}")
    op.execute(
        f"GRANT INSERT ({', '.join(INSERT_DA_IDENTIDADE)}) ON {CONTACTOS} "
        f"TO {PAPEL_DA_IDENTIDADE}"
    )
    op.execute(f"GRANT SELECT ({', '.join(SELECT_DA_APP)}) ON {CONTACTOS} TO kamba_app")

    op.execute(f"REVOKE ALL ON {ACCOES} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {ACCOES} TO kamba_app")
    op.execute(f"GRANT UPDATE ({', '.join(UPDATE_DA_APP)}) ON {ACCOES} TO kamba_app")

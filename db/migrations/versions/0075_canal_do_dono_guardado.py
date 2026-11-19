"""Canal do dono guardado: tenants.owner_channel_wa pela definir_dono (KAM-216).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O numero

A `0075`, sobre a `0074` do KAM-222, pela fila de migracoes do lote 13: uma
revisao por fundir de cada vez.

## A decisao do fundador (2026-11-19)

O criterio 1 do bloco deixava a forma do numero da loja a uma decisao de
desenho. O fundador escolheu a **opcao C**: o numero da loja nao se guarda;
guarda-se so o booleano `owner_channel_wa`, calculado pelo `onboarding-web` a
cada troca de telefone, e comparado com o telefone do dono **actual** e nao com
o do caso. Emenda o «nao e coluna» das decisoes do executor do KAM-118.

## O que esta revisao cria

| Objecto | Para que serve |
|---|---|
| `platform.tenants.owner_channel_wa` | `true` se o dono fala pelo WhatsApp da loja, `false` se o telefone dele e o numero da loja; nulo se ninguem o calculou |
| `platform.definir_dono(p_contact_id, p_origem, p_owner_channel_wa)` | a mesma porta da `0070`, com o terceiro argumento, nulo por omissao |
| `SELECT (id, owner_channel_wa)` na `tenants` ao `kamba_identity` | a leitura do `GET /painel/canal`, pela ligacao da troca |

## Um escritor so, e e a porta

A coluna muda **quando o dono muda**, na transaccao em que a `definir_dono`
move o papel e escreve o `owner_contact_id`: o dono e o canal dele tem um
escritor so, e nao divergem. Ninguem tem `UPDATE (owner_channel_wa)`. A
reentrega idempotente (o contacto ja e o dono) devolve sem tocar em nada, como
na `0070`: uma reentrega do `tenant.provisioned`, que manda nulo, nao apaga o
valor que a troca calculou.

O terceiro argumento tem `DEFAULT NULL`, e por isso a chamada de dois
argumentos continua a resolver: o provisionamento nao muda. A assinatura de
dois argumentos **sai** (`DROP FUNCTION`), e nao fica ao lado: duas funcoes com
o mesmo nome eram duas portas, e uma chamada de dois argumentos ficava ambigua.

## O `downgrade`

Larga a concessao de leitura, repoe a porta de dois argumentos da `0070` (o
mesmo corpo, o mesmo comentario, as mesmas concessoes) e larga a coluna. **Sem
recusa**: o booleano recalcula-se na troca seguinte, e sem ele o painel mostra
o painel, que funciona sempre.
"""

from __future__ import annotations

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

CONTACTOS = "platform.contacts"
TENANTS = "platform.tenants"

#: As duas assinaturas, escritas uma vez cada (licao do KAM-175).
ASSINATURA = "platform.definir_dono(uuid, text, boolean)"
ASSINATURA_DA_0070 = "platform.definir_dono(uuid, text)"

#: O papel que corre o modulo de identidade, o unico com `EXECUTE`.
PAPEL_DA_IDENTIDADE = "kamba_identity"

#: O que o `kamba_identity` le da `tenants`: a chave da politica e a coluna nova.
SELECT_DA_IDENTIDADE = ("id", "owner_channel_wa")

COMENTARIO_DA_0070 = (
    "'A unica porta que muda contacts.papel (KAM-118). Tenant so do app.tenant_id. "
    "provisionamento: idempotente, e recusa (23505) se ja ha outro dono. "
    "troca_de_telefone: o anterior passa a cliente, o novo a dono, papel_mudou_at "
    "nos dois e tenants.owner_contact_id no novo. Devolve o dono anterior ou NULL. "
    "EXECUTE so para o kamba_identity.'"
)

COMENTARIO = (
    "'A unica porta que muda contacts.papel (KAM-118) e tenants.owner_channel_wa "
    "(KAM-216). Tenant so do app.tenant_id. provisionamento: idempotente, e recusa "
    "(23505) se ja ha outro dono. troca_de_telefone: o anterior passa a cliente, o "
    "novo a dono, papel_mudou_at nos dois, e tenants.owner_contact_id e "
    "owner_channel_wa no novo. A reentrega nao toca em nada. Devolve o dono anterior "
    "ou NULL. EXECUTE so para o kamba_identity.'"
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TENANTS} ADD COLUMN owner_channel_wa boolean")
    op.execute(
        f"COMMENT ON COLUMN {TENANTS}.owner_channel_wa IS "
        "'O canal do dono (KAM-216, decisao do fundador de 2026-11-19): true se o "
        "telefone do dono actual nao e o numero da loja, false se e; nulo se ninguem "
        "o calculou. Calcula-o o onboarding-web na troca de telefone; escreve-o so a "
        "platform.definir_dono, quando o dono muda. Nulo e false dao painel.'"
    )
    op.execute(f"DROP FUNCTION {ASSINATURA_DA_0070}")
    _porta(com_canal=True)
    op.execute(f"COMMENT ON FUNCTION {ASSINATURA} IS {COMENTARIO}")
    _executar(ASSINATURA)
    op.execute(
        f"GRANT SELECT ({', '.join(SELECT_DA_IDENTIDADE)}) ON {TENANTS} TO {PAPEL_DA_IDENTIDADE}"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(SELECT_DA_IDENTIDADE)}) ON {TENANTS} FROM {PAPEL_DA_IDENTIDADE}"
    )
    op.execute(f"DROP FUNCTION {ASSINATURA}")
    _porta(com_canal=False)
    op.execute(f"COMMENT ON FUNCTION {ASSINATURA_DA_0070} IS {COMENTARIO_DA_0070}")
    _executar(ASSINATURA_DA_0070)
    op.execute(f"ALTER TABLE {TENANTS} DROP COLUMN owner_channel_wa")


def _executar(assinatura: str) -> None:
    """O `EXECUTE` so ao `kamba_identity`, depois de o tirar a `PUBLIC` (`0029`)."""
    op.execute(f"REVOKE ALL ON FUNCTION {assinatura} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {assinatura} TO {PAPEL_DA_IDENTIDADE}")


def _porta(*, com_canal: bool) -> None:
    """A porta da `0070`, com ou sem o terceiro argumento.

    Um corpo so para as duas formas, e a diferenca sao duas linhas: a assinatura
    e a escrita da `tenants`. Escrever o corpo duas vezes era deixar uma das
    copias desviar-se da outra (a licao do KAM-175). O `downgrade` repoe assim o
    corpo da `0070` letra a letra, tirando o que esta revisao acrescentou.
    """
    if com_canal:
        parametros = "p_contact_id uuid, p_origem text, p_owner_channel_wa boolean DEFAULT NULL"
        escrita = (
            f"UPDATE {TENANTS} SET owner_contact_id = p_contact_id, "
            "owner_channel_wa = p_owner_channel_wa WHERE id = v_tenant;"
        )
    else:
        parametros = "p_contact_id uuid, p_origem text"
        escrita = f"UPDATE {TENANTS} SET owner_contact_id = p_contact_id WHERE id = v_tenant;"
    op.execute(
        f"""
        CREATE FUNCTION platform.definir_dono({parametros})
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
          {escrita}
          RETURN v_anterior;
        END $func$
        """
    )

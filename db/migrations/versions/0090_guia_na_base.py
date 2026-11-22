"""Guia na base: o estado do passo guiado do ES e a busca pelo numero ligado (KAM-239).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## Para que serve

O guia do Embedded Signup (KAM-093) nao se montava em `prod`: o estado dele
(`RepositorioDoGuia`) vivia em memoria, e um reinicio perdia o popup aberto, o
numero ligado e os dois factos do `verificado` (bloco do KAM-239). Esta revisao
da-lhe onde viver, com o `kamba_app` e sob a RLS do tenant **pre-alocado** do
caso, como o desafio do OTP da `0084`.

| Objecto | Para que serve |
|---|---|
| `platform.onboarding_guia` | o estado do guia de um caso, um so, preso ao caso |
| `guia_busca` | a politica que deixa a funcao abaixo ler o guia de qualquer tenant |
| `platform.guia_caso_por_phone_number_id` | o caso de um numero ligado, que devolve so o caso e o tenant |

O pre-voo **nao** esta aqui: vive na `onboarding_case.preflight` desde a `0043`
(o array dos sete itens), que e a coluna que o bloco do KAM-093 nomeia. Aqui
fica so o instante da avaliacao (`preflight_at`), que o array nao leva.

## Quem escreve o que (decisao do fundador de 2026-11-22, A)

O `onboarding-web` le e escreve o estado como `kamba_app`, pela RLS do tenant
do caso, com o `INSERT` e o `UPDATE` por coluna. O processo de lote
(`onboarding-lote`, `kamba_batch`) so **le** e muda o `estado` e o
`actualizado_at`: e a volta dos 30 minutos, que passa a `abandonado` os popups
abertos de todos os tenants (o `iniciadosAntesDe` do guia). **Ninguem apaga**
(dicionario §2): o guia sai com o caso.

## A busca pelo numero (a forma da D1-A do KAM-236)

Os sinais da Meta chegam por `phone_number_id`, **antes** de se saber de que
tenant e o numero (`porPhoneNumberId`). A forma e a das cinco buscas do registo
da `0084`: uma funcao `SECURITY DEFINER` que devolve **so** o `id` do caso e o
`tenant_id`, com `EXECUTE` so para o `kamba_app`, e uma politica so para o dono
das tabelas (`FOR SELECT TO kamba_migrator`) ligada por uma variavel que a
funcao liga e desliga no seu corpo. **O `DEFINER` sozinho nao chega**: o dono e
`NOBYPASSRLS`, e o `FORCE` vincula-o (a nota da `0084`).

Devolve **um** caso, porque a porta devolve um: o mais recente a **ligar** o
numero (`numero_ligado_at`, que so se escreve quando o `phone_number_id` muda), e
nunca um guia ja preso por numero divergente. Dois guias com o mesmo numero sao o
caso que o criterio 4 do KAM-093 prende: o segundo a liga-lo e o que tem o numero
alheio, e e esse que o `confirmarNumero` tem de comparar; preso ele, os sinais do
numero voltam ao outro. **Nao o `actualizado_at`**, que sobe com qualquer escrita
(o pre-voo repetido, a sincronizacao, a propria prisao): ordenar por ele mandava
os sinais para quem mexeu por ultimo no guia, e nao para quem ligou o numero
(achado 2 da revisao adversarial).

## O `downgrade`

Larga o que esta revisao criou, pela ordem inversa, sem `CASCADE`.

## Numero

`0090`, sobre a `0089` do KAM-240: a vaga que a coordenacao do lote 19 deu ao
KAM-239 a 2026-11-22.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0090"
down_revision = "0084"
branch_labels = None
depends_on = None

CASOS = "platform.onboarding_case"
GUIA = "platform.onboarding_guia"

#: Os estados do guia, **por extenso**: o *gate* 3b le as revisoes sem as
#: executar. Iguais ao `ESTADOS_DO_GUIA` de `packages/core-ts/src/guia/contrato.ts`.
ESTADOS_SQL = (
    "'pre_voo', 'iniciado', 'es_concluido', 'subscrito', 'a_sincronizar', "
    "'verificado', 'pronto', 'abandonado', 'falhado', 'desligado'"
)

#: Os motivos de falha. Iguais ao `MOTIVOS_DE_FALHA` do mesmo ficheiro.
MOTIVOS_SQL = "'numero_divergente', 'sincronizacao_vencida', 'ligacao_recusada', 'tecto_da_meta'"

#: O tecto dos identificadores da Meta e da tentativa: o do `textoCurto` do guia
#: (`packages/core-ts/src/guia/guia.ts`), para que a base nao recuse o que o guia
#: aceitou (um 23514 a meio do `FINISH`, achado 8 da revisao adversarial).
TECTO_DO_IDENTIFICADOR = 512

#: A funcao, com a assinatura que o `GRANT` e o `DROP` pedem.
F_NUMERO = "platform.guia_caso_por_phone_number_id(text)"

#: O que o `kamba_app` insere: so o caso e o tenant. O resto nasce pelos `DEFAULT`.
INSERT_DO_GUIA = ("onboarding_id", "tenant_id")
#: O que o `kamba_app` muda: as transicoes, o pre-voo e os dois factos.
UPDATE_DO_GUIA = (
    "estado",
    "preflight_at",
    "iniciado_at",
    "motivo",
    "tentativa_id",
    "phone_number_id",
    "numero_ligado_at",
    "waba_id",
    "numero_confirmado",
    "sincronizado",
    "actualizado_at",
)
#: O que o `kamba_batch` muda: o abandono dos popups vencidos, e mais nada.
UPDATE_DO_LOTE = ("estado", "actualizado_at")


def upgrade() -> None:
    _guia()
    _busca()


def _guia() -> None:
    op.execute(
        f"""
        CREATE TABLE {GUIA} (
          onboarding_id      uuid CONSTRAINT onboarding_guia_pkey PRIMARY KEY,
          tenant_id          uuid NOT NULL,
          estado             text NOT NULL DEFAULT 'pre_voo'
                             CONSTRAINT onboarding_guia_estado_ck
                             CHECK (estado IN ({ESTADOS_SQL})),
          preflight_at       timestamptz,
          iniciado_at        timestamptz,
          motivo             text
                             CONSTRAINT onboarding_guia_motivo_ck
                             CHECK (motivo IN ({MOTIVOS_SQL})),
          tentativa_id       text
                             CONSTRAINT onboarding_guia_tentativa_ck
                             CHECK (char_length(tentativa_id) BETWEEN 1 AND {TECTO_DO_IDENTIFICADOR}),
          phone_number_id    text
                             CONSTRAINT onboarding_guia_phone_number_ck
                             CHECK (char_length(phone_number_id) BETWEEN 1 AND {TECTO_DO_IDENTIFICADOR}),
          numero_ligado_at   timestamptz,
          waba_id            text
                             CONSTRAINT onboarding_guia_waba_ck
                             CHECK (char_length(waba_id) BETWEEN 1 AND {TECTO_DO_IDENTIFICADOR}),
          numero_confirmado  boolean NOT NULL DEFAULT false,
          sincronizado       boolean NOT NULL DEFAULT false,
          actualizado_at     timestamptz NOT NULL DEFAULT now(),
          criado_at          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT onboarding_guia_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES {CASOS} (id, tenant_id)
        )
        """
    )
    # O `tenant_id` primeiro num indice: e o predicado que a RLS acrescenta a
    # todas as consultas (a convencao do `test_catalogo`).
    op.execute(f"CREATE INDEX onboarding_guia_tenant_idx ON {GUIA} (tenant_id)")
    # A volta dos 30 minutos, como lote: so os popups abertos.
    op.execute(
        f"CREATE INDEX onboarding_guia_iniciado_idx ON {GUIA} (iniciado_at) WHERE estado = 'iniciado'"
    )
    # A busca pelo numero ligado.
    op.execute(
        f"CREATE INDEX onboarding_guia_phone_number_idx ON {GUIA} (phone_number_id) "
        "WHERE phone_number_id IS NOT NULL"
    )
    op.execute(
        f"COMMENT ON TABLE {GUIA} IS "
        "'O estado do passo guiado do Embedded Signup de um caso de onboarding (KAM-239): um por "
        "caso. O pre-voo vive na onboarding_case.preflight; aqui fica o instante dele. Nao se apaga.'"
    )
    rls.enable_tenant_rls("onboarding_guia")
    op.execute(f"REVOKE ALL ON {GUIA} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DO_GUIA)}), "
        f"UPDATE ({', '.join(UPDATE_DO_GUIA)}) ON {GUIA} TO kamba_app"
    )
    op.execute(f"GRANT SELECT, UPDATE ({', '.join(UPDATE_DO_LOTE)}) ON {GUIA} TO kamba_batch")


def _busca() -> None:
    """A politica do dono e a funcao. Ver a nota do modulo.

    O `SET search_path = pg_catalog, platform` e **sem `public`**, pela razao da
    `0029` que a `0084` repete.
    """
    op.execute(
        f"CREATE POLICY guia_busca ON {GUIA} FOR SELECT TO kamba_migrator "
        "USING (current_setting('app.guia_busca', true) = 'on')"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.guia_caso_por_phone_number_id(p_phone_number_id text)
          RETURNS TABLE (id uuid, tenant_id uuid)
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        BEGIN
          PERFORM set_config('app.guia_busca', 'on', true);
          RETURN QUERY SELECT g.onboarding_id, g.tenant_id FROM {GUIA} g
           WHERE g.phone_number_id = p_phone_number_id
             AND NOT (g.estado = 'falhado' AND g.motivo IS NOT DISTINCT FROM 'numero_divergente')
           ORDER BY g.numero_ligado_at DESC NULLS LAST, g.onboarding_id
           LIMIT 1;
          PERFORM set_config('app.guia_busca', 'off', true);
          RETURN;
        END
        $func$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {F_NUMERO} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_NUMERO} TO kamba_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {F_NUMERO}")
    op.execute(f"DROP POLICY guia_busca ON {GUIA}")
    rls.disable_tenant_rls("onboarding_guia")
    op.execute(f"DROP TABLE {GUIA}")

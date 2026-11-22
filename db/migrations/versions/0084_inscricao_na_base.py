"""Inscricao na base: chave do registo, buscas do registo, OTP, contadores e revogacoes (KAM-236).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## Para que serve

O `onboarding-web` recusava `prod` porque o registo, o OTP, os contadores do
anti-abuso e as sessoes revogadas do painel viviam em memoria, e um reinicio
perdia-os (bloco do KAM-236). Esta revisao da-lhes onde viver, com o
`kamba_app` e sob a RLS do tenant **pre-alocado** do caso.

| Objecto | Para que serve |
|---|---|
| `onboarding_case.chave_idem` | a chave de idempotencia do registo (criterio 2 do KAM-086), unica |
| `registo_busca` | a politica que deixa as cinco funcoes abaixo ler o caso de qualquer tenant |
| `platform.registo_*` (cinco) | as buscas do registo que atravessam tenants, que devolvem so o caso e o tenant |
| `platform.onboarding_otp` | o desafio do OTP de um caso, um so |
| `platform.onboarding_contador` | as janelas deslizantes do anti-abuso e do OTP, por chave |
| `platform.painel_revogacao` | as sessoes do painel revogadas, por sessao ou por tenant |

## As buscas que atravessam tenants (decisao do fundador, 2026-11-21, D1-A)

O registo procura um caso por chave de idempotencia, pelo NIF, pelo telefone, e
conta os casos de um dispositivo, **antes** de saber de que tenant e o caso. O
`kamba_app` e `NOBYPASSRLS`, e a `tenant_iso` so lhe mostra o tenant do
contexto. O fundador escolheu funcoes `SECURITY DEFINER` que devolvem **so** o
`id` e o `tenant_id` (ou uma contagem), com `EXECUTE` so para o `kamba_app`; o
adaptador poe depois o `app.tenant_id` desse caso e le a linha pela RLS.
Recusou o `kamba_batch` no `onboarding-web` (B) e um papel novo (C).

**O `DEFINER` sozinho nao chega**, e e o que a `0070` deixou escrito: o dono
das funcoes e das tabelas e o `kamba_migrator`, que e `NOBYPASSRLS`, e o
`FORCE` vincula o dono. Dentro de uma funcao `SECURITY DEFINER` o
`current_user` e o dono, pelo que a politica `registo_busca` e o que a deixa ver
o caso de outro tenant: `FOR SELECT TO kamba_migrator`, e **so com a variavel
`app.registo_busca` ligada**. Cada funcao liga-a com `set_config(..., true)`
imediatamente antes da sua consulta e desliga-a imediatamente depois, no mesmo
corpo `plpgsql` (a clausula `SET` da funcao, que o PostgreSQL desfaz ao sair,
recusa uma variavel de marcador a quem nao e superutilizador: `42501`, medido).
Fora das funcoes, o dono continua a nao ver nada sem contexto, que e o que o
X-04 do *gate* 6 mede (`test_o_dono_das_tabelas_tambem_nao_ve_nada`); a
primeira versao desta politica era `USING (true)` e o X-04 apanhou-a.

**Quem mais ve a variavel.** A politica e so do `kamba_migrator`, e nenhum
processo da aplicacao corre com esse papel; o `kamba_app` pode ligar a variavel
a mao, e nao ganha nada, porque a politica nao e dele. O que ela abriria e outra
funcao `SECURITY DEFINER` do dono que lesse a `onboarding_case` na mesma
transaccao, depois de a aplicacao a ligar: **nao ha nenhuma**, e o
`test_so_as_cinco_buscas_leem_o_caso_como_dono` do
`db/tests/test_inscricao_na_base_schema.py` falha no dia em que houver.

**O que a funcao nao devolve e a garantia.** Nenhuma devolve o NIF, o telefone,
o nome ou a fase: quem chama recebe um par de identificadores e le o resto como
`kamba_app`, sob a RLS do tenant do caso. Os HMAC entram em hexadecimal e a
funcao descodifica-os, para que um argumento mal formado de um erro em vez de
uma busca por octetos inventados.

## O desafio do OTP

Um por caso: `guardar` substitui, e o `apagar` da porta (no acerto e no
esgotamento) **nao apaga**: marca o `usado_at`, e um desafio usado deixa de se
ler. E a regra do dicionario §2 («*soft delete*: estado, nunca `DELETE`»), que o
`test_privilegios` mede em todas as tabelas: o `kamba_app` nao apaga linhas de
tabela nenhuma. O codigo **nunca** entra, so o HMAC preso ao caso
(`hmacDoCodigo`); a linha sai com o caso.

## Os contadores

Uma linha por chave (`rede:<hmac>`, `envios:<hmac>`, `batida:<id>`,
`orcamento`...), com os instantes da janela num `timestamptz[]`. **Sem
`tenant_id` e sem RLS**: o orcamento diario de SMS e o prefixo de rede nao sao
de tenant nenhum, e a chave ja e um HMAC ou um identificador opaco. A
atomicidade que o `Contadores` exige vem da linha: o `INSERT ... ON CONFLICT DO
UPDATE` tranca-a. O tecto de 10 000 instantes por chave e o
`INSTANTES_POR_CHAVE` do duplo em memoria.

O `actualizado_at` e o instante mais recente escrito (o relogio de quem chama,
e nao o `now()`). **Quem apaga e o executor da retencao**, como `kamba_batch`
(a classe `contadores_do_registo`, 25 h sobre o `actualizado_at`, pela forma da
quarentena da entrada): a maior janela perguntada e de 24 h, e o `kamba_app`
nao apaga linhas de tabela nenhuma (dicionario §2).

## As revogacoes

Uma linha por sessao revogada (`sid`) ou um corte por tenant (`ate`, em
segundos desde a epoca, inclusive), nunca as duas. O `expira_at` e o fim do
tecto absoluto da sessao (90 dias depois da emissao): depois dele a linha ja nao
revoga nada que se possa apresentar. **Sem `DELETE`**; a purga das expiradas
fica com credor na politica de retencao.

## O `downgrade`

Larga o que esta revisao criou, pela ordem inversa, sem `CASCADE`.

## Numero

`0084`, sobre a `0083` do KAM-232: a vaga que a coordenacao do lote 17 deu ao
KAM-236 a 2026-11-21.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None

CASOS = "platform.onboarding_case"
OTP = "platform.onboarding_otp"
CONTADORES = "platform.onboarding_contador"
REVOGACOES = "platform.painel_revogacao"

#: A forma de uma chave de idempotencia. Igual ao `CHAVE` de
#: `packages/core-ts/src/sms/contrato.ts`, que o registo usa para a validar.
FORMA_DA_CHAVE = "'^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'"

#: A forma de um HMAC em hexadecimal (SHA-256).
FORMA_DO_HMAC = "'^[0-9a-f]{64}$'"

#: O tecto de instantes por chave. O `INSTANTES_POR_CHAVE` de
#: `packages/core-ts/src/inscricao/memoria.ts`.
INSTANTES_POR_CHAVE = 10000

#: A variavel que liga a politica `registo_busca`, so dentro das cinco funcoes.
VARIAVEL_DA_BUSCA = "app.registo_busca"

#: As fases mortas, **por extenso**: o *gate* 3b le as revisoes sem as executar.
#: Iguais ao `FASES_MORTAS` de `packages/core-ts/src/inscricao/contrato.ts` e ao
#: predicado do `onboarding_nif_vivo` da `0043`.
FASES_MORTAS_SQL = "'rejeitado', 'abandonado', 'cancelado'"

#: As funcoes, com a assinatura que o `GRANT` e o `DROP` pedem. **Uma constante
#: por funcao, e as instrucoes por extenso**: o *gate* 3b nao segue uma variavel
#: de ciclo.
F_TENANT = "platform.registo_tenant_do_caso(uuid)"
F_CHAVE = "platform.registo_caso_por_chave(text)"
F_NIF = "platform.registo_caso_vivo_por_nif(text)"
F_TELEFONE = "platform.registo_casos_vivos_por_telefone(text)"
F_DISPOSITIVO = "platform.registo_contar_por_dispositivo(text, timestamptz)"

#: O que o `kamba_app` insere num desafio.
INSERT_DO_OTP = ("onboarding_id", "tenant_id", "codigo_hmac", "expira_at", "tentativas")
#: O que muda num desafio: o `guardar` substitui, o `somarTentativa` soma e o
#: `apagar` marca o `usado_at`.
UPDATE_DO_OTP = ("codigo_hmac", "expira_at", "tentativas", "usado_at")

#: O que o `kamba_app` insere numa revogacao.
INSERT_DA_REVOGACAO = ("tenant_id", "sid", "ate", "expira_at")
#: O que muda num corte por tenant: so sobe.
UPDATE_DA_REVOGACAO = ("ate", "expira_at")


def upgrade() -> None:
    _chave()
    _buscas()
    _otp()
    _contadores()
    _revogacoes()


def _chave() -> None:
    """A chave de idempotencia do registo, unica entre todos os casos.

    O `INSERT` do `kamba_app` na `onboarding_case` e de tabela (a `0043` so
    restringe o `UPDATE` por coluna), pelo que a coluna nova fica inserivel sem
    `GRANT` novo, e **nao** fica actualizavel: a chave escreve-se uma vez.
    Nula nas linhas que nao vieram do registo (as sementes dos ensaios).
    """
    op.execute(
        f"""
        ALTER TABLE {CASOS} ADD COLUMN chave_idem text
          CONSTRAINT onboarding_case_chave_idem_ck CHECK (chave_idem ~ {FORMA_DA_CHAVE})
        """
    )
    op.execute(f"CREATE UNIQUE INDEX onboarding_case_chave_idem_uq ON {CASOS} (chave_idem)")


def _buscas() -> None:
    """A politica do dono e as cinco funcoes. Ver a nota do modulo.

    O `SET search_path = pg_catalog, platform` e **sem `public`**, pela razao da
    `0029`: num `SECURITY DEFINER`, um schema onde o chamador crie objectos
    deixava-o sombrear um operador que este corpo usa.
    """
    op.execute(
        f"CREATE POLICY registo_busca ON {CASOS} FOR SELECT TO kamba_migrator "
        f"USING (current_setting('{VARIAVEL_DA_BUSCA}', true) = 'on')"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.registo_tenant_do_caso(p_id uuid)
          RETURNS uuid
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_tenant uuid;
        BEGIN
          PERFORM set_config('app.registo_busca', 'on', true);
          SELECT c.tenant_id INTO v_tenant FROM {CASOS} c WHERE c.id = p_id;
          PERFORM set_config('app.registo_busca', 'off', true);
          RETURN v_tenant;
        END
        $func$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.registo_caso_por_chave(p_chave text)
          RETURNS TABLE (id uuid, tenant_id uuid)
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        BEGIN
          PERFORM set_config('app.registo_busca', 'on', true);
          RETURN QUERY SELECT c.id, c.tenant_id FROM {CASOS} c WHERE c.chave_idem = p_chave;
          PERFORM set_config('app.registo_busca', 'off', true);
          RETURN;
        END
        $func$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.registo_caso_vivo_por_nif(p_nif_hmac text)
          RETURNS TABLE (id uuid, tenant_id uuid)
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        BEGIN
          PERFORM set_config('app.registo_busca', 'on', true);
          RETURN QUERY SELECT c.id, c.tenant_id FROM {CASOS} c
           WHERE c.nif_hmac = decode(p_nif_hmac, 'hex')
             AND c.fase NOT IN ({FASES_MORTAS_SQL});
          PERFORM set_config('app.registo_busca', 'off', true);
          RETURN;
        END
        $func$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.registo_casos_vivos_por_telefone(p_phone_hmac text)
          RETURNS TABLE (id uuid, tenant_id uuid)
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        BEGIN
          PERFORM set_config('app.registo_busca', 'on', true);
          RETURN QUERY SELECT c.id, c.tenant_id FROM {CASOS} c
           WHERE c.phone_hmac = decode(p_phone_hmac, 'hex')
             AND c.fase NOT IN ({FASES_MORTAS_SQL})
           ORDER BY c.criado_at, c.id;
          PERFORM set_config('app.registo_busca', 'off', true);
          RETURN;
        END
        $func$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.registo_contar_por_dispositivo(p_device_hash text, p_desde timestamptz)
          RETURNS integer
          LANGUAGE plpgsql SECURITY DEFINER
          SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_n integer;
        BEGIN
          PERFORM set_config('app.registo_busca', 'on', true);
          SELECT count(*)::integer INTO v_n FROM {CASOS} c
           WHERE c.device_hash = decode(p_device_hash, 'hex') AND c.criado_at >= p_desde;
          PERFORM set_config('app.registo_busca', 'off', true);
          RETURN v_n;
        END
        $func$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {F_TENANT} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {F_CHAVE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {F_NIF} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {F_TELEFONE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {F_DISPOSITIVO} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_TENANT} TO kamba_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_CHAVE} TO kamba_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_NIF} TO kamba_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_TELEFONE} TO kamba_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {F_DISPOSITIVO} TO kamba_app")


def _otp() -> None:
    op.execute(
        f"""
        CREATE TABLE {OTP} (
          onboarding_id  uuid CONSTRAINT onboarding_otp_pkey PRIMARY KEY,
          tenant_id      uuid NOT NULL,
          codigo_hmac    text NOT NULL
                         CONSTRAINT onboarding_otp_codigo_hmac_ck
                         CHECK (codigo_hmac ~ {FORMA_DO_HMAC}),
          expira_at      timestamptz NOT NULL,
          tentativas     integer NOT NULL DEFAULT 0
                         CONSTRAINT onboarding_otp_tentativas_ck
                         CHECK (tentativas >= 0),
          usado_at       timestamptz,
          criado_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT onboarding_otp_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES {CASOS} (id, tenant_id)
        )
        """
    )
    # O `tenant_id` primeiro num indice: e o predicado que a RLS acrescenta a
    # todas as consultas (a convencao do `test_catalogo`).
    op.execute(f"CREATE INDEX onboarding_otp_tenant_idx ON {OTP} (tenant_id)")
    op.execute(
        f"COMMENT ON TABLE {OTP} IS "
        "'O desafio do OTP de posse do telefone de um caso de onboarding (KAM-236): um por "
        "caso, so o HMAC do codigo. Marca-se usado no acerto e no esgotamento; nao se apaga.'"
    )
    rls.enable_tenant_rls("onboarding_otp")
    op.execute(f"REVOKE ALL ON {OTP} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DO_OTP)}), "
        f"UPDATE ({', '.join(UPDATE_DO_OTP)}) ON {OTP} TO kamba_app"
    )


def _contadores() -> None:
    op.execute(
        f"""
        CREATE TABLE {CONTADORES} (
          chave           text CONSTRAINT onboarding_contador_pkey PRIMARY KEY
                          CONSTRAINT onboarding_contador_chave_ck
                          CHECK (char_length(chave) BETWEEN 1 AND 200),
          instantes       timestamptz[] NOT NULL
                          CONSTRAINT onboarding_contador_instantes_ck
                          CHECK (cardinality(instantes) <= {INSTANTES_POR_CHAVE}),
          actualizado_at  timestamptz NOT NULL
        )
        """
    )
    op.execute(
        f"CREATE INDEX onboarding_contador_actualizado_idx ON {CONTADORES} (actualizado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {CONTADORES} IS "
        "'As janelas deslizantes do anti-abuso e do OTP do registo (KAM-236), por chave HMAC "
        "ou opaca. Sem tenant: o orcamento de SMS e o prefixo de rede nao sao de ninguem.'"
    )
    op.execute(f"REVOKE ALL ON {CONTADORES} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE (instantes, actualizado_at) ON {CONTADORES} TO kamba_app"
    )
    # A purga das chaves paradas e do executor da retencao, que corre como lote.
    op.execute(f"GRANT SELECT, DELETE ON {CONTADORES} TO kamba_batch")


def _revogacoes() -> None:
    op.execute(
        f"""
        CREATE TABLE {REVOGACOES} (
          revogacao_id  uuid CONSTRAINT painel_revogacao_pkey PRIMARY KEY
                        DEFAULT gen_random_uuid(),
          tenant_id     uuid NOT NULL,
          sid           uuid,
          ate           bigint
                        CONSTRAINT painel_revogacao_ate_ck CHECK (ate >= 0),
          expira_at     timestamptz NOT NULL,
          criado_at     timestamptz NOT NULL DEFAULT now(),
          -- Uma sessao ou um corte por tenant, nunca as duas nem nenhuma.
          CONSTRAINT painel_revogacao_alvo_ck CHECK ((sid IS NULL) <> (ate IS NULL))
        )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX painel_revogacao_sid_uq ON {REVOGACOES} (tenant_id, sid) "
        "WHERE sid IS NOT NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX painel_revogacao_corte_uq ON {REVOGACOES} (tenant_id) "
        "WHERE ate IS NOT NULL"
    )
    op.execute(
        f"COMMENT ON TABLE {REVOGACOES} IS "
        "'As sessoes do painel do dono revogadas (KAM-236): por sessao ou por corte do tenant. "
        "expira_at e o fim do tecto absoluto da sessao; sem DELETE para ninguem.'"
    )
    rls.enable_tenant_rls("painel_revogacao")
    op.execute(f"REVOKE ALL ON {REVOGACOES} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_REVOGACAO)}), "
        f"UPDATE ({', '.join(UPDATE_DA_REVOGACAO)}) ON {REVOGACOES} TO kamba_app"
    )


def downgrade() -> None:
    rls.disable_tenant_rls("painel_revogacao")
    op.execute(f"DROP TABLE {REVOGACOES}")
    op.execute(f"DROP TABLE {CONTADORES}")
    rls.disable_tenant_rls("onboarding_otp")
    op.execute(f"DROP TABLE {OTP}")
    op.execute(f"DROP FUNCTION {F_DISPOSITIVO}")
    op.execute(f"DROP FUNCTION {F_TELEFONE}")
    op.execute(f"DROP FUNCTION {F_NIF}")
    op.execute(f"DROP FUNCTION {F_CHAVE}")
    op.execute(f"DROP FUNCTION {F_TENANT}")
    op.execute(f"DROP POLICY registo_busca ON {CASOS}")
    op.execute("DROP INDEX platform.onboarding_case_chave_idem_uq")
    op.execute(f"ALTER TABLE {CASOS} DROP COLUMN chave_idem")

"""TEN: contador de uso por periodo, livro de idempotencia e a regra unica (KAM-009).

**A primeira linha e ASCII de proposito, e segue a forma das outras seis.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a
do executavel: um travessao aqui faz as duas divergirem na descodificacao e
poe `test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo`
vermelho — por causa de um caracter num docstring.

Revisao: 0007
Anterior: 0006

**Porque e que esta revisao existe.** O `docs/tecnica/03` §5.2 da a tabela
`entitlements`, que guarda o **tecto** — quanto um tenant pode. Nenhum
documento do conjunto diz onde fica o **consumo**: quanto ja gastou. Sem isso,
`msgs_ai_mes` e um numero num `jsonb` que ninguem pode fazer cumprir. As duas
tabelas entram no dicionario pela emenda 1.17 (§3.2), porque o §1 declara
defeito um nome de DDL fora dele.

A fonte de cada coisa:

* `tenant_usage` e `usage_ledger` — dicionario §3.2, emenda 1.17 (KAM-009).
  Nao ha DDL destas tabelas em documento tecnico nenhum: sao desenho deste
  ticket, e as colunas sao as do dicionario.
* `platform.ten_consumir` — a regra do criterio 3 do bloco do KAM-009: «1 000
  chamadas paralelas de 1 unidade contra limite 100 aceitam exactamente 100».
* O fuso do periodo — criterio 5 do mesmo bloco: 00:00 em `Africa/Luanda`.
* Os privilegios que **saem** — dicionario §3.2, linha «Privilegios de
  `kamba_app`», emenda 1.17.

**Porque e que a regra e uma funcao SQL e nao codigo.** O bloco do ticket pede
a biblioteca em TypeScript **e** um lado Python «a chamar a mesma regra SQL».
Duas implementacoes da mesma aritmetica de limites divergem — foi o que a
`0002` ja escreveu sobre a RLS, e e o mesmo argumento. A regra vive aqui, e as
duas linguagens chamam-na. O precedente de forma e a familia `platform.evt_*`
da `0004`.

**A funcao corre como quem a chama** (`SECURITY INVOKER`, por omissao, e dito
por extenso abaixo). Um `SECURITY DEFINER` passaria por cima da RLS e punha
todo o isolamento de tenant a depender dos argumentos — que e exactamente o
que o ADR-015 recusa.

O que esta revisao **nao** faz, e de quem e:

* **nao** escreve entitlements — e o provisionamento, KAM-091;
* **nao** factura nem cobra assinatura — KAM-059;
* **nao** aplica limites em tools — KAM-028 usa a biblioteca deste ticket;
* **nao** fecha o dominio de `tenants.plano` por `CHECK IN (…)`. O gate 3b
  exige o `CHECK` de um dominio **na revisao que cria a coluna**, e essa e a
  `0001`, fundida. A coluna ganha aqui o `CHECK` de **forma**, como
  `entitlements.modulo` ja tem, e a lista fechada de planos vive em
  `registry/plans.yaml`. Esta escrito no dicionario §3.2;
* **nao** retira a `kamba_app` o `UPDATE` sobre `tenants.estado` nem sobre
  `verificado_at`. Retira o do `plano`, que e o que manda nos entitlements, e
  o de `entitlements(limites, ativo)`. Os outros dois voltam ao §4 do
  dicionario com dono (KAM-091): retira-los sem o fluxo de onboarding escrito
  seria decidir o provisionamento de fora dele.

Tudo isto e SQL **proposto ate correr**: o gate 8 e o que o promove.
"""

from alembic import op

import rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: As colunas de `tenants` que `kamba_app` pode alterar **depois** desta
#: revisao, ja em SQL. E a lista da `0001` menos `plano`, e escreve-se por
#: inteiro em vez de um `REVOKE` da coluna sozinha por duas razoes: quem vier
#: aqui ver o que a aplicacao pode fazer le uma lista, e nao uma lista menos
#: uma subtraccao noutro ficheiro; e o gate 3b le o **texto** das instrucoes
#: sem as executar, pelo que uma lista montada por `join` deixava-o sem nada
#: para ler. Literal, portanto — nao e estilo, e o que torna a revisao
#: verificavel por maquina.
COLUNAS_QUE_A_APLICACAO_ALTERA = (
    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "
    "estado, medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "
    "litellm_key_id, fuso_horario, verificado_at, deleted_at"
)

#: A mesma lista com `plano`, para o `downgrade` repor **exactamente** o que a
#: `0001` concedeu. Um `downgrade` que repusesse de memoria deixava a base num
#: estado que revisao nenhuma escreveu.
COLUNAS_DA_0001 = (
    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "
    "plano, estado, medusa_sales_channel_id, medusa_merchant_id, "
    "chatwoot_account_id, litellm_key_id, fuso_horario, verificado_at, "
    "deleted_at"
)


def upgrade() -> None:
    # --- o contador -----------------------------------------------------
    #
    # Uma linha por (tenant, chave, periodo). O `periodo` e o **primeiro dia
    # do mes** em `Africa/Luanda`, e nao um intervalo: dois meses sao duas
    # linhas, e o fecho do mes nao e um trabalho que corra — e a chave mudar.
    op.execute(
        """
        CREATE TABLE platform.tenant_usage (
          tenant_id     uuid NOT NULL
                        CONSTRAINT tenant_usage_tenant_fk
                        REFERENCES platform.tenants(id),
          chave_limite  text NOT NULL
                        CONSTRAINT tenant_usage_chave_limite_ck
                        CHECK (chave_limite ~ '^[a-z][a-z0-9_]*$'),
          periodo       date NOT NULL
                        CONSTRAINT tenant_usage_periodo_ck
                        CHECK (periodo = date_trunc('month', periodo)::date),
          valor         bigint NOT NULL DEFAULT 0
                        CONSTRAINT tenant_usage_valor_ck CHECK (valor >= 0),
          actualizado_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, chave_limite, periodo)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.tenant_usage.periodo IS "
        "'Primeiro dia do mes em Africa/Luanda (dicionario §3.2). O CHECK "
        "impede uma linha a meio do mes, que partiria a chave em duas.'"
    )

    # --- o livro de idempotencia ----------------------------------------
    #
    # **A chave unica e que recusa a segunda chamada**, e nao uma leitura
    # previa: entre o `SELECT` e o `INSERT` de uma leitura previa cabe a
    # chamada repetida inteira. A chave e por tenant, e nao global, porque a
    # chave de idempotencia e escolhida por quem chama e dois tenants podem
    # escolher a mesma.
    op.execute(
        """
        CREATE TABLE platform.usage_ledger (
          tenant_id       uuid NOT NULL
                          CONSTRAINT usage_ledger_tenant_fk
                          REFERENCES platform.tenants(id),
          idempotency_key text NOT NULL
                          CONSTRAINT usage_ledger_idempotency_key_ck
                          CHECK (btrim(idempotency_key) <> ''),
          chave_limite    text NOT NULL
                          CONSTRAINT usage_ledger_chave_limite_ck
                          CHECK (chave_limite ~ '^[a-z][a-z0-9_]*$'),
          periodo         date NOT NULL,
          quantidade      bigint NOT NULL
                          CONSTRAINT usage_ledger_quantidade_ck
                          CHECK (quantidade > 0),
          criado_at       timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, idempotency_key)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.usage_ledger IS "
        "'O que torna o consumo idempotente. Uma chave por tenant; repetir a "
        "mesma nao consome segunda vez (KAM-009, criterio 4).'"
    )
    # O indice de retencao: apagar os livros de um periodo fechado le por
    # (tenant, periodo), e a chave primaria comeca por `idempotency_key`
    # depois do tenant. Com `tenant_id` em primeiro lugar, como a `0001`
    # escreveu: e o predicado que a RLS acrescenta a todas as consultas.
    op.execute(
        "CREATE INDEX usage_ledger_periodo_idx "
        "ON platform.usage_ledger (tenant_id, periodo)"
    )

    # --- a regra, uma so -------------------------------------------------
    op.execute(_FUNCAO_CONSUMIR)
    op.execute(_FUNCAO_PERIODO)

    # --- isolamento ------------------------------------------------------
    rls.enable_tenant_rls("tenant_usage")
    rls.enable_tenant_rls("usage_ledger")

    # --- privilegios -----------------------------------------------------
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
          ON platform.tenant_usage, platform.usage_ledger
          TO kamba_batch
        """
    )
    # A aplicacao consome: le, insere e actualiza o contador; le e insere o
    # livro. **Sem `DELETE` em tabela nenhuma**, como todas as outras desde a
    # `0001` — e isso teve consequencia no desenho da funcao, e nao o
    # contrario: a primeira versao desfazia a chave de idempotencia com um
    # `DELETE` quando o tecto recusava, o que obrigava a conceder `DELETE` a
    # aplicacao. O teste que diz «a app nao apaga linhas de tabela nenhuma»
    # apanhou-o, e tinha razao. O desfazer passou a ser o que devia ter sido
    # desde o inicio: o **rollback de uma subtransaccao**, que nao e uma
    # escrita compensatoria e nao pode ficar a meio.
    op.execute(
        """
        GRANT SELECT, INSERT ON platform.tenant_usage, platform.usage_ledger
          TO kamba_app
        """
    )
    op.execute(
        "GRANT UPDATE (valor, actualizado_at) ON platform.tenant_usage TO kamba_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz) "
        "TO kamba_app, kamba_batch"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.ten_periodo(timestamptz) "
        "TO kamba_app, kamba_batch"
    )

    # --- a forma de `tenants.plano` --------------------------------------
    op.execute(
        "ALTER TABLE platform.tenants ADD CONSTRAINT tenants_plano_ck "
        "CHECK (plano ~ '^[a-z][a-z0-9_]*$')"
    )

    # --- o que a aplicacao deixa de poder --------------------------------
    #
    # **Esta e a decisao do ticket, e nao uma limpeza.** Com a politica
    # `id = app.tenant_id` da `0002`, um contexto de tenant altera a propria
    # linha de `tenants`: com `UPDATE (plano)` subia o proprio plano, e com
    # `UPDATE (limites, ativo)` em `entitlements` subia os proprios limites.
    # Os limites sao a unica coisa entre um tenant e o tecto de dinheiro por
    # pedido (ADR-013, ADR-015). Quem os altera e o `kamba_batch`, que ja tem
    # tudo nas duas tabelas: provisionamento (KAM-091) e cobranca (KAM-059)
    # sao de retaguarda.
    #
    # Nao se usa `REVOKE UPDATE (plano)`: o PostgreSQL guarda a concessao por
    # coluna e revogar uma deixa a lista a divergir do que esta escrito em
    # qualquer sitio. Revoga-se a concessao inteira e concede-se a nova.
    op.execute("REVOKE UPDATE ON platform.tenants FROM kamba_app")
    op.execute(
        f"GRANT UPDATE ({COLUNAS_QUE_A_APLICACAO_ALTERA}) "
        "ON platform.tenants TO kamba_app"
    )
    op.execute("REVOKE UPDATE ON platform.entitlements FROM kamba_app")


def downgrade() -> None:
    # Pela ordem inversa, e a repor **exactamente** o que a `0001` concedeu.
    op.execute(
        f"GRANT UPDATE ({COLUNAS_DA_0001}) "
        "ON platform.tenants TO kamba_app"
    )
    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")
    op.execute("ALTER TABLE platform.tenants DROP CONSTRAINT tenants_plano_ck")

    op.execute(
        "DROP FUNCTION platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz)"
    )
    op.execute("DROP FUNCTION platform.ten_periodo(timestamptz)")

    rls.disable_tenant_rls("usage_ledger")
    rls.disable_tenant_rls("tenant_usage")

    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao
    # criou, o `downgrade` falha em vez de o apagar em silencio.
    op.execute("DROP INDEX platform.usage_ledger_periodo_idx")
    op.execute("DROP TABLE platform.usage_ledger")
    op.execute("DROP TABLE platform.tenant_usage")


#: O periodo de um instante. Funcao propria, e nao uma expressao copiada, para
#: que o fuso exista **num** sitio: o TypeScript, o Python e o `CHECK` de
#: `tenant_usage.periodo` tem todos de concordar, e tres copias de
#: `'Africa/Luanda'` divergem no dia em que uma delas mudar.
_FUNCAO_PERIODO = """
CREATE FUNCTION platform.ten_periodo(p_agora timestamptz DEFAULT now())
RETURNS date
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')::date
$$
"""

#: O consumo: atomico e idempotente, sem lock global.
#:
#: A ordem das duas insercoes nao e indiferente, e a inversa esta errada:
#: contar primeiro e registar a chave depois deixa uma chamada repetida a
#: contar duas vezes na janela entre as duas. Regista-se a chave primeiro e,
#: se o tecto recusar, apaga-se a linha que **esta transaccao** acabou de
#: inserir — que e seguro precisamente porque o `RETURNING` disse que foi ela.
#:
#: O tecto nao vem por argumento sozinho: vem de `entitlements`, e e o
#: **minimo** entre os modulos activos que declaram a chave. E a regra que o
#: dicionario §3.2 ja escreve para o par `valor_max_pedido_minor` /
#: `manual_max_minor`, aplicada ao caso geral. Sem linha activa que declare a
#: chave, **nega** — falha fechada, criterio 2.
#:
#: O `p_limite` existe na assinatura para o chamador poder impor um tecto mais
#: baixo do que o do plano (um tecto de confianca, `EPIC-09`), nunca mais alto:
#: o efectivo e o minimo dos dois.
_FUNCAO_CONSUMIR = """
CREATE FUNCTION platform.ten_consumir(
  p_tenant          uuid,
  p_chave           text,
  p_quantidade      bigint,
  p_idempotency_key text,
  p_limite          bigint DEFAULT NULL,
  p_agora           timestamptz DEFAULT now()
)
RETURNS TABLE (aceite boolean, valor bigint, repetido boolean, limite bigint)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_periodo date := platform.ten_periodo(p_agora);
  v_limite  bigint;
  v_valor    bigint;
  v_repetido boolean := false;
  v_negado   boolean := false;
BEGIN
  IF p_quantidade IS NULL OR p_quantidade <= 0 THEN
    RAISE EXCEPTION 'ten_consumir: quantidade tem de ser positiva, veio %', p_quantidade
      USING ERRCODE = 'check_violation';
  END IF;

  -- O tecto do plano: o minimo entre os modulos activos que declaram a
  -- chave. `NULL` quando nenhum a declara, e `NULL` nega.
  SELECT min((e.limites ->> p_chave)::bigint) INTO v_limite
    FROM platform.entitlements AS e
   WHERE e.tenant_id = p_tenant
     AND e.ativo
     AND e.limites ? p_chave;

  IF v_limite IS NULL THEN
    -- Falha fechada, e **antes** de olhar para o `p_limite`: sem entitlement
    -- activo que declare a chave nao ha tecto nenhum, e «sem tecto» nao quer
    -- dizer «sem limite». A primeira versao fazia
    -- `least(coalesce(v_limite, p_limite), p_limite)`, que deixava o chamador
    -- **inventar** um tecto onde o canon manda negar — o criterio 2 do bloco
    -- diz «devolve negado se nao houver linha», e um argumento nao substitui
    -- uma linha.
    RETURN QUERY SELECT false, 0::bigint, false, NULL::bigint;
    RETURN;
  END IF;

  -- O tecto de quem chama so **desce**: e para um tecto de confianca
  -- (`EPIC-09`) poder ser mais apertado do que o do plano, nunca mais largo.
  IF p_limite IS NOT NULL THEN
    v_limite := least(v_limite, p_limite);
  END IF;

  -- As duas escritas, **numa subtransaccao**. O bloco com `EXCEPTION` e o
  -- que o plpgsql da como savepoint: se alguma coisa aqui dentro levantar,
  -- desfaz-se tudo o que o bloco escreveu e so ele, e a transaccao de quem
  -- chama continua.
  --
  -- A ordem nao e indiferente, e a inversa esta errada: contar primeiro e
  -- registar a chave depois deixa uma chamada repetida a contar duas vezes
  -- na janela entre as duas. Regista-se a chave primeiro; se o tecto
  -- recusar, levanta-se, e o rollback do bloco leva a chave com ele.
  BEGIN
    INSERT INTO platform.usage_ledger
                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);

    IF p_quantidade > v_limite THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.tenant_usage
                (tenant_id, chave_limite, periodo, valor)
         VALUES (p_tenant, p_chave, v_periodo, p_quantidade)
    ON CONFLICT (tenant_id, chave_limite, periodo) DO UPDATE
       SET valor = platform.tenant_usage.valor + p_quantidade,
           actualizado_at = now()
     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite
    RETURNING platform.tenant_usage.valor INTO v_valor;

    -- E aqui que a atomicidade mora: duas transaccoes em conflito na mesma
    -- chave serializam no lock da linha, e a segunda reavalia o `WHERE`
    -- sobre o valor **ja actualizado** pela primeira. Sem linha devolvida, o
    -- tecto recusou.
    IF v_valor IS NULL THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;
  EXCEPTION
    WHEN unique_violation THEN
      -- A chave ja la estava: isto e a mesma chamada outra vez. Devolve-se o
      -- estado e **nao se consome**. O `INSERT` desta tentativa foi desfeito
      -- pelo rollback do bloco, que e o que torna isto seguro de repetir.
      v_repetido := true;
    WHEN SQLSTATE 'KA001' THEN
      -- O tecto recusou. O rollback levou a chave de idempotencia consigo,
      -- senao uma segunda tentativa com a mesma chave era lida como
      -- repeticao de um consumo que nunca aconteceu.
      v_negado := true;
  END;

  IF v_repetido OR v_negado THEN
    SELECT u.valor INTO v_valor
      FROM platform.tenant_usage AS u
     WHERE u.tenant_id = p_tenant AND u.chave_limite = p_chave
       AND u.periodo = v_periodo;
    RETURN QUERY SELECT v_repetido, coalesce(v_valor, 0::bigint), v_repetido, v_limite;
    RETURN;
  END IF;

  RETURN QUERY SELECT true, v_valor, false, v_limite;
END;
$$
"""

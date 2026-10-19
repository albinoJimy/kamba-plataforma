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
* **nao** retira a `kamba_app` o `UPDATE` sobre `tenants.verificado_at`. Essa
  coluna volta ao §4 do dicionario com dono (KAM-091) e nao e entrada de
  decisao nenhuma.

**O que a revisao adversarial mudou nesta revisao.** Ela reprovou o ticket
com tres criticos, e os tres sao daqui. Ficam escritos no sitio onde foram
corrigidos — a chave de `usage_ledger`, os privilegios e o trigger — e
resumidos aqui porque sao tres portas para a mesma escalada: **um tenant a
decidir o proprio tecto**, que e o que este ticket existe para fechar.

1. a chave de idempotencia nao estava ligada ao pedido. Valia para todas as
   chaves de limite do tenant e nao olhava a quantidade, pelo que repetir uma
   chave autorizava qualquer pedido contra qualquer tecto;
2. `kamba_app` mantinha `INSERT` em `entitlements`. Nao e preciso subir o
   proprio tecto se se pode **criar** um;
3. `GRANT UPDATE (valor)` em `tenant_usage` deixava o tenant **zerar** o
   proprio contador. O privilegio por coluna nao sabe dizer «so sobe»; um
   trigger sabe.

E duas portas menores da mesma familia: `UPDATE (tenants.estado)`, que
deixava um tenant `suspenso` reactivar-se e com isso retirar a condicao do
criterio 2; e o `p_agora`, que dava a quem corre como `kamba_app` um balde
novo por cada mes do calendario.

**E a revisao ganhou uma terceira funcao, `ten_tecto`.** Nao veio dos
criticos: veio de a correccao do M5 ter posto o `min` entre os modulos
activos a ser escrito **outra vez** nas bibliotecas, para quem pergunta
«cabe?» sem consumir. Duas copias de uma regra de limites divergem — e a
copia ja divergia, sem a guarda do `22P02`. A regra passa a viver num sitio
so, como o fuso ja vivia na `ten_periodo`.

Tudo isto e SQL **proposto ate correr**: o gate 8 e o que o promove.
"""

from alembic import op

import rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: As colunas de `tenants` que `kamba_app` pode alterar **depois** desta
#: revisao, ja em SQL. E a lista da `0001` menos `plano` e menos `estado`, e
#: escreve-se por inteiro em vez de um `REVOKE` da coluna sozinha por duas
#: razoes: quem vier aqui ver o que a aplicacao pode fazer le uma lista, e nao
#: uma lista menos uma subtraccao noutro ficheiro; e o gate 3b le o **texto**
#: das instrucoes sem as executar, pelo que uma lista montada por `join`
#: deixava-o sem nada para ler. Literal, portanto — nao e estilo, e o que
#: torna a revisao verificavel por maquina.
#:
#: **O `estado` saiu na revisao adversarial, e a razao e a do criterio 2.** A
#: primeira versao desta revisao deixou-o alteravel, escrevendo que retira-lo
#: seria decidir o KAM-091 de fora dele. A revisao mediu a consequencia que
#: essa razao nao dizia: `UPDATE platform.tenants SET estado = 'ativo'` com o
#: proprio contexto **passa**, e o consumo seguinte e aceite. O criterio 2
#: manda negar um tenant `onboarding`, `suspenso` ou `encerrado`; um
#: privilegio que deixa o proprio sujeito retirar a condicao nao torna o
#: criterio dificil de cumprir, torna-o impossivel de fazer cumprir. E o
#: mesmo argumento que ja tinha tirado o `plano` e os `limites`, aplicado a
#: terceira coluna da mesma linha. O `verificado_at` fica: nao e entrada de
#: decisao nenhuma.
COLUNAS_QUE_A_APLICACAO_ALTERA = (
    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "
    "medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "
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
    #
    # **E a `chave_limite` faz parte dela, desde a revisao adversarial.** A
    # primeira versao tinha `PRIMARY KEY (tenant_id, idempotency_key)`, e isso
    # deixava uma chave de idempotencia valer para **todas** as chaves de
    # limite do tenant. Medido: consumir `msgs_ai_mes` n=1 com a chave `IDK` e
    # depois pedir `valor_max_pedido_minor` n=99 999 999 com a **mesma** `IDK`
    # devolvia aceite, contra um tecto de 50 000 Kz — porque a chamada era
    # lida como repeticao da primeira. Um cliente que mande um
    # `Idempotency-Key` constante tornava todos os limites ilimitados, e o
    # criterio 3 ficava vacuo. A chave de idempotencia identifica **um
    # pedido**, e um pedido e contra uma chave de limite.
    #
    # O resto do pedido — a quantidade — nao entra na chave primaria, e isso
    # tambem e decisao: entrar fazia de duas quantidades duas chamadas
    # distintas, que e o contrario de idempotencia. Compara-se na funcao, e
    # uma repeticao com outra quantidade levanta `KA002`.
    op.execute(
        """
        CREATE TABLE platform.usage_ledger (
          tenant_id       uuid NOT NULL
                          CONSTRAINT usage_ledger_tenant_fk
                          REFERENCES platform.tenants(id),
          idempotency_key text NOT NULL
                          CONSTRAINT usage_ledger_idempotency_key_ck
                          CHECK (idempotency_key !~ '^[[:space:]]*$'),
          chave_limite    text NOT NULL
                          CONSTRAINT usage_ledger_chave_limite_ck
                          CHECK (chave_limite ~ '^[a-z][a-z0-9_]*$'),
          periodo         date NOT NULL,
          quantidade      bigint NOT NULL
                          CONSTRAINT usage_ledger_quantidade_ck
                          CHECK (quantidade > 0),
          criado_at       timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, chave_limite, idempotency_key)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.usage_ledger IS "
        "'O que torna o consumo idempotente. Uma chave por tenant e por chave "
        "de limite; repetir a mesma nao consome segunda vez (KAM-009, "
        "criterio 4). A chave de idempotencia **nao** atravessa chaves de "
        "limite: sem a chave_limite na chave primaria, uma so chave repetida "
        "autorizava um pedido contra qualquer tecto.'"
    )
    # O indice de retencao: apagar os livros de um periodo fechado le por
    # (tenant, periodo), e a chave primaria comeca por `idempotency_key`
    # depois do tenant. Com `tenant_id` em primeiro lugar, como a `0001`
    # escreveu: e o predicado que a RLS acrescenta a todas as consultas.
    op.execute(
        "CREATE INDEX usage_ledger_periodo_idx "
        "ON platform.usage_ledger (tenant_id, periodo)"
    )

    # --- o contador nao desce --------------------------------------------
    #
    # **Isto saiu da revisao adversarial, e e o terceiro critico.** A
    # aplicacao precisa de `UPDATE (valor, actualizado_at)` para o
    # `ON CONFLICT DO UPDATE` da `ten_consumir` funcionar — a funcao e
    # `SECURITY INVOKER` e corre com os privilegios de quem chama. Mas um
    # privilegio de coluna nao diz **em que direccao**: medido,
    # `UPDATE platform.tenant_usage SET valor = 0` com o proprio contexto
    # passa, e o tenant consome vinte contra um tecto de dez, repetidamente.
    #
    # O gate 6 provava que B nao altera o contador de A. Nao havia nada a
    # provar que A nao altera o **seu**, e a RLS nunca o poderia provar: a
    # linha e dele.
    #
    # O remedio e o padrao da `0006` (`audit_log_imutavel`): o que o
    # privilegio nao sabe exprimir, exprime-o um `BEFORE UPDATE`. O contador
    # e *append-only* — so sobe. Quem precisa de o repor apaga a linha, e
    # `DELETE` so o `kamba_batch` tem.
    #
    # `ENABLE ALWAYS` pela mesma razao da `0006`: sem ele o trigger nao
    # dispara em sessoes de replica, e a propriedade deixava de valer
    # exactamente onde nao ha ninguem a olhar.
    op.execute(_FUNCAO_SO_SOBE)
    op.execute(
        """
        CREATE TRIGGER tenant_usage_so_sobe
          BEFORE UPDATE ON platform.tenant_usage
          FOR EACH ROW EXECUTE FUNCTION platform.ten_usage_so_sobe()
        """
    )
    op.execute(
        "ALTER TABLE platform.tenant_usage ENABLE ALWAYS TRIGGER tenant_usage_so_sobe"
    )

    # --- a regra, uma so -------------------------------------------------
    op.execute(_FUNCAO_PERIODO)
    op.execute(_FUNCAO_TECTO)
    op.execute(_FUNCAO_CONSUMIR)
    op.execute(_COMENTARIO_DA_CONSUMIR)

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
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.ten_tecto(uuid, text) "
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
    # **`INSERT` e nao so `UPDATE`, desde a revisao adversarial.** A primeira
    # versao revogava so o `UPDATE` e deixava o `INSERT` da `0001` de pe. Com
    # `WITH CHECK (tenant_id = app.tenant_id)`, um tenant **insere a propria
    # linha**: medido, `INSERT INTO platform.entitlements VALUES (…, 'auto',
    # '{"valor_max_pedido_minor": 900000000000}', true)` passa, e o pedido de
    # 500 000 000 que antes era negado passa a ser aceite com esse tecto.
    #
    # E a **mesma escalada que este ticket foi escrito para fechar, por outro
    # verbo**: nao e preciso subir o proprio tecto se se pode criar um. A
    # regra da `ten_consumir` e o **minimo** entre os modulos activos, o que
    # tornaria uma linha nova inofensiva — mas so se a chave ja estivesse
    # declarada noutro modulo activo. Quando nao esta, a linha nova e o unico
    # tecto que existe, e o minimo de um conjunto com um elemento e esse
    # elemento.
    #
    # Quem escreve entitlements e o `kamba_batch`: provisionamento (KAM-091) e
    # cobranca (KAM-059) sao de retaguarda, e esta pelo ambito do proprio
    # ticket.
    op.execute("REVOKE INSERT, UPDATE ON platform.entitlements FROM kamba_app")


def downgrade() -> None:
    # Pela ordem inversa, e a repor **exactamente** o que a `0001` concedeu.
    op.execute(
        f"GRANT UPDATE ({COLUNAS_DA_0001}) "
        "ON platform.tenants TO kamba_app"
    )
    op.execute("GRANT INSERT ON platform.entitlements TO kamba_app")
    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")
    op.execute("ALTER TABLE platform.tenants DROP CONSTRAINT tenants_plano_ck")

    op.execute(
        "DROP FUNCTION platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz)"
    )
    op.execute("DROP FUNCTION platform.ten_periodo(timestamptz)")
    op.execute("DROP FUNCTION platform.ten_tecto(uuid, text)")
    # O trigger **antes** da funcao, e os dois a mao: um `DROP FUNCTION`
    # sem `CASCADE` recusa enquanto houver um trigger pendurado nela
    # (`2BP01`), e `CASCADE` e o que esta revisao nao usa em lado nenhum.
    op.execute("DROP TRIGGER tenant_usage_so_sobe ON platform.tenant_usage")
    op.execute("DROP FUNCTION platform.ten_usage_so_sobe()")

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

#: O contador so sobe. O que o privilegio por coluna nao sabe exprimir.
#:
#: `SECURITY INVOKER`, como o `audit_log_imutavel` da `0006` e pela mesma
#: razao: recusar nao precisa de privilegio nenhum.
#:
#: Verifica duas coisas, e as duas sao o mesmo defeito por caminhos
#: diferentes. Baixar o `valor` apaga consumo; mover a linha para outro
#: `(tenant_id, chave_limite, periodo)` apaga-o na mesma, levando o numero
#: para uma conta onde ele nao conta. A segunda so e alcancavel pelo
#: `kamba_batch` — a aplicacao tem `UPDATE` em duas colunas e nenhuma delas e
#: chave — e esta aqui porque a propriedade e da tabela e nao do papel.
_FUNCAO_SO_SOBE = """
CREATE FUNCTION platform.ten_usage_so_sobe()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.chave_limite IS DISTINCT FROM OLD.chave_limite
     OR NEW.periodo IS DISTINCT FROM OLD.periodo THEN
    RAISE EXCEPTION
      'tenant_usage: a chave de uma linha de uso nao se altera (%/%/% -> %/%/%)',
      OLD.tenant_id, OLD.chave_limite, OLD.periodo,
      NEW.tenant_id, NEW.chave_limite, NEW.periodo
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.valor < OLD.valor THEN
    RAISE EXCEPTION
      'tenant_usage: o contador nao desce (% -> %). Repor um periodo e apagar a linha, e DELETE so o kamba_batch tem.',
      OLD.valor, NEW.valor
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$
"""

#: O aviso que nao se pode apagar sem alguem dar por isso.
#:
#: Duas chamadas na **mesma transaccao**, contra duas chaves de limite, em
#: ordens opostas, bloqueiam-se uma a outra nas linhas de `tenant_usage`: a
#: revisao adversarial mediu um `40P01` (*deadlock detected*). Nao ha ordem
#: que a funcao possa impor — ela ve uma chave de cada vez —, pelo que a
#: ordem e de quem chama, e o unico sitio onde isso se pode dizer a quem
#: liga a base e aqui. O `db/tests_ten/test_tecto.py` le este comentario e
#: falha se ele deixar de nomear a regra: um aviso que se pode apagar em
#: silencio nao e um aviso.
_COMENTARIO_DA_CONSUMIR = """
COMMENT ON FUNCTION platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz) IS
'Consome uma quantidade contra o tecto de uma chave de limite (KAM-009).
Atomica e idempotente; devolve (aceite, valor, repetido, limite).

ORDEM DAS CHAVES. Quem consumir mais do que uma chave de limite na mesma
transaccao tem de o fazer sempre pela mesma ordem — `chave_limite`
ascendente — ou duas transaccoes em ordens opostas bloqueiam-se e uma morre
com deadlock (40P01). A funcao nao pode impor a ordem: ve uma chave de cada
vez.

NIVEL DE ISOLAMENTO. Desenhada para READ COMMITTED, que e a omissao: e a
reavaliacao do WHERE do ON CONFLICT DO UPDATE sobre a linha ja actualizada
que faz a contagem serializar. Sob REPEATABLE READ a segunda transaccao
morre com 40001 em vez de reavaliar.

SQLSTATE. 23514 quantidade nao positiva ou chave de idempotencia vazia;
22023 instante fora do periodo corrente para quem nao e kamba_batch, ou
limite nao inteiro em entitlements; KA002 a mesma chave de idempotencia
repetida com outra quantidade.'
"""

#: O tecto de uma chave para um tenant: o **minimo** entre os modulos activos
#: que a declaram. Funcao propria, e nao uma consulta repetida, pela mesma
#: razao que a `ten_periodo` existe — e pela razao com que esta revisao se
#: justifica inteira: duas implementacoes da mesma aritmetica de limites
#: divergem.
#:
#: Quem pergunta «cabe?» **sem consumir** precisa dela: um tecto por pedido
#: (`valor_max_pedido_minor`, `manual_max_minor`) nao e um balde que se gasta,
#: e passa-lo pela `ten_consumir` criava linha em `tenant_usage` e gastava o
#: balde do mes. A primeira versao das bibliotecas reescreveu o `min(...)` em
#: SQL do lado de fora, com o `22P02` de volta por cima; isto e o que o
#: substitui.
#:
#: `NULL` quando nenhum modulo activo a declara — e `NULL` **nega**, porque
#: «sem tecto» nao quer dizer «sem limite». Um valor que nao se saiba ler
#: **levanta**: ignorar a linha ilegivel tirava um modulo do minimo, e o
#: minimo de menos modulos e maior.
#:
#: `STABLE` e nao `IMMUTABLE`: le tabelas.
_FUNCAO_TECTO = """
CREATE FUNCTION platform.ten_tecto(p_tenant uuid, p_chave text)
RETURNS bigint
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
AS $$
DECLARE
  v_limite   bigint;
  v_ilegivel boolean;
BEGIN
  -- O `CASE` e o que impede o `22P02`: um `(limites ->> p_chave)::bigint`
  -- solto rebenta quando o valor nao e um numero, e o `AND` do SQL **nao**
  -- garante curto-circuito — a guarda tinha de ficar no `WHEN`, que garante.
  -- `length <= 18` em vez de comparar com o maximo do `bigint`: dezoito
  -- algarismos cabem sempre, e comparar obrigava a um segundo cast. E e esse
  -- tecto de algarismos que torna o transbordo da soma do contador
  -- impossivel, e nao um cast para `numeric` la em baixo — com limites ate
  -- 10^18, `valor + quantidade` nunca passa de 2 x 10^18 e o `bigint` vai ate
  -- 9,2 x 10^18. (O cast estava la, e a prova por mutacao mostrou que nao
  -- morria ninguem ao tira-lo: era defesa sobre uma porta ja fechada.)
  SELECT min(CASE WHEN d.legivel THEN d.texto::bigint END),
         bool_or(NOT d.legivel)
    INTO v_limite, v_ilegivel
    FROM (
      SELECT (e.limites ->> p_chave) AS texto,
             (    jsonb_typeof(e.limites -> p_chave) = 'number'
              AND (e.limites ->> p_chave) ~ '^[0-9]+$'
              AND length(e.limites ->> p_chave) <= 18) AS legivel
        FROM platform.entitlements AS e
       WHERE e.tenant_id = p_tenant
         AND e.ativo
         AND e.limites ? p_chave
    ) AS d;

  IF coalesce(v_ilegivel, false) THEN
    RAISE EXCEPTION
      'ten_tecto: a chave % tem um limite que nao e um inteiro em entitlements', p_chave
      USING ERRCODE = 'invalid_parameter_value';
  END IF;

  RETURN v_limite;
END;
$$
"""

#: O consumo: atomico e idempotente, sem lock global.
#:
#: A ordem das duas insercoes nao e indiferente, e a inversa esta errada:
#: contar primeiro e registar a chave depois deixa uma chamada repetida a
#: contar duas vezes na janela entre as duas. Regista-se a chave primeiro e,
#: se o tecto recusar, desfaz-se o bloco inteiro.
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
#:
#: **O que a revisao adversarial acrescentou**, por ordem de gravidade:
#:
#: * a chave de idempotencia e agora unica por `(tenant, chave_limite, chave)`
#:   — ver o comentario da tabela — e uma repeticao com **outra quantidade**
#:   levanta `KA002` em vez de devolver «repetido». Sem isso, repetir a chave
#:   de um consumo de 1 autorizava um pedido de 99 999 999 sem o contar;
#: * `p_agora` deixa de poder apontar para outro periodo quando quem chama
#:   nao e `kamba_batch`. A aplicacao nao o usa — o `coalesce($6, now())` das
#:   bibliotecas passa `now()` — mas tem `EXECUTE` na assinatura de seis
#:   argumentos, e um instante do ano passado dava-lhe um balde vazio por mes
#:   de calendario;
#: * um valor nao inteiro em `limites` abortava a transaccao com `22P02`,
#:   fora de todos os tratadores. Agora e um erro nomeado, e **falha
#:   fechada**: um tecto que nao se sabe ler nao e um tecto;
#: * a soma do contador compara-se em `numeric`. Em `bigint`, um tecto perto
#:   do maximo fazia `valor + p_quantidade` transbordar com `22003` — outra
#:   vez fora dos tratadores;
#: * `p_idempotency_key` nula ou so com espacos levanta aqui, com o nome do
#:   argumento, em vez de rebentar la dentro no `CHECK` da coluna.
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
  v_periodo date;
  v_limite  bigint;
  v_valor    bigint;
  v_antes    bigint;
  v_repetido boolean := false;
  v_negado   boolean := false;
BEGIN
  IF p_quantidade IS NULL OR p_quantidade <= 0 THEN
    RAISE EXCEPTION 'ten_consumir: quantidade tem de ser positiva, veio %', p_quantidade
      USING ERRCODE = 'check_violation';
  END IF;

  -- A coluna tem o mesmo `CHECK` e o `NOT NULL`, mas os dois rebentam
  -- **dentro** do bloco com `EXCEPTION`, onde so se tratam
  -- `unique_violation` e `KA001`: o erro saia sem dizer que argumento era.
  --
  -- E e `[[:space:]]` e nao `btrim`: o `btrim` de um argumento so tira
  -- **espacos**, pelo que uma chave de um so tabulador passava a guarda e
  -- passava o `CHECK` da coluna. Medido, e a coluna foi corrigida com ele.
  IF p_idempotency_key IS NULL OR p_idempotency_key ~ '^[[:space:]]*$' THEN
    RAISE EXCEPTION 'ten_consumir: p_idempotency_key nula ou vazia'
      USING ERRCODE = 'check_violation';
  END IF;

  IF p_agora IS NULL THEN
    RAISE EXCEPTION 'ten_consumir: p_agora nulo'
      USING ERRCODE = 'invalid_parameter_value';
  END IF;

  v_periodo := platform.ten_periodo(p_agora);

  -- O relogio so se fixa de retaguarda. `p_agora` existe para a fronteira de
  -- mes se poder provar e para a reconciliacao poder reprocessar um periodo
  -- fechado; nas maos de quem corre como `kamba_app` era um balde novo por
  -- cada mes do calendario. Quem pode e quem ja podia tudo nestas tabelas.
  IF v_periodo <> platform.ten_periodo(now())
     AND NOT pg_has_role(current_user, 'kamba_batch', 'USAGE') THEN
    RAISE EXCEPTION
      'ten_consumir: p_agora aponta para o periodo % e o corrente e %; so o kamba_batch fixa o relogio',
      v_periodo, platform.ten_periodo(now())
      USING ERRCODE = 'invalid_parameter_value';
  END IF;

  -- O tecto do plano, por uma funcao propria: quem pergunta «cabe?» sem
  -- consumir — o `checkCeiling` das duas bibliotecas — precisa da **mesma**
  -- regra, e a primeira versao dela escreveu-a outra vez em SQL do lado de
  -- fora. Duas copias de uma regra de limites divergem, que e o argumento
  -- com que esta revisao existe.
  v_limite := platform.ten_tecto(p_tenant, p_chave);

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
      -- A chave ja la estava, para esta chave de limite: isto e a mesma
      -- chamada outra vez. Devolve-se o estado e **nao se consome**. O
      -- `INSERT` desta tentativa foi desfeito pelo rollback do bloco, que e o
      -- que torna isto seguro de repetir.
      v_repetido := true;
    WHEN SQLSTATE 'KA001' THEN
      -- O tecto recusou. O rollback levou a chave de idempotencia consigo,
      -- senao uma segunda tentativa com a mesma chave era lida como
      -- repeticao de um consumo que nunca aconteceu.
      v_negado := true;
  END;

  IF v_repetido THEN
    -- **A chave diz qual foi o pedido, e o pedido tem uma quantidade.** Sem
    -- esta comparacao, repetir a chave de um consumo de 1 autorizava um
    -- pedido de 99 999 999: a funcao respondia «repetido» e quem chama lia
    -- «podes». Levanta-se com codigo proprio porque isto nao e uma recusa de
    -- limite — e um conflito no pedido de quem chama, e um `429` seria a
    -- resposta errada.
    SELECT l.quantidade INTO v_antes
      FROM platform.usage_ledger AS l
     WHERE l.tenant_id = p_tenant
       AND l.chave_limite = p_chave
       AND l.idempotency_key = p_idempotency_key;
    IF v_antes IS DISTINCT FROM p_quantidade THEN
      RAISE EXCEPTION
        'ten_consumir: a chave de idempotencia % ja foi usada em % com quantidade % e veio %',
        p_idempotency_key, p_chave, v_antes, p_quantidade
        USING ERRCODE = 'KA002';
    END IF;
  END IF;

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

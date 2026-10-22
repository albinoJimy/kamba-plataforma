/**
 * O SQL do onboarding de canal (KAM-016), num ficheiro só.
 *
 * Está separado da lógica pela mesma razão que o `qualidade/consultas.ts` e o
 * `chr/consultas.ts` estão: a suite de base de dados lê estas constantes **deste
 * ficheiro** e exercita-as contra um PostgreSQL real, pela classe
 * `ConsultaDoTypeScript` de `db/tests/base.py`. Uma cópia do SQL no teste
 * provava que a cópia funciona.
 *
 * **Os marcadores são `$n` e a ordem em que aparecem no texto importa**: o
 * `pg8000` da suite Python não tem `$n`, tem `%s`, e liga-os pela ordem de
 * aparição. A `ConsultaDoTypeScript` reordena, mas só se a numeração for
 * contígua a partir de 1.
 *
 * ## Um papel só, e é o `kamba_batch`
 *
 * Ao contrário do CHR, que reparte as consultas por três papéis, tudo aqui corre
 * como `kamba_batch`. O onboarding de um canal é **provisionamento**, e o
 * dicionário §3.2 já lho atribuiu: «quem os altera é o `kamba_batch` —
 * provisionamento (KAM-091) e cobrança (KAM-059) são de retaguarda e já lá
 * correm». As três consequências estão no `docstring` da revisão `0016`; a que
 * se vê aqui é a `SQL_CONTAR_JANELA`, que **atravessa tenants** e por isso só
 * pode correr com `BYPASSRLS`.
 *
 * O `kamba_app` tem `SELECT` em `channel_onboarding` e mais nada, e nenhuma
 * consulta deste ficheiro é para ele: o painel da loja é KAM-093.
 */

/**
 * Abre a tentativa, ou devolve nada se ela já existia. **A idempotência do
 * critério 2, e é da base.**
 *
 * `ON CONFLICT DO NOTHING RETURNING` sem `SELECT` antes: entre um `SELECT` e um
 * `INSERT` cabe outro processo, e o critério pede **um** canal e não «quase
 * sempre um». É a mesma forma do `SQL_REGISTAR_TRANSICAO` da `0014`, do
 * `SQL_ENFILEIRAR` da `0010` e do `SQL_REGISTAR_PROVA` da `0015`.
 *
 * **O `ON CONFLICT` não nomeia a chave**, e isso é deliberado: há **duas** —
 * `(tenant_id, code_hash)` e `(tenant_id, waba_id)` — e o critério 2 quer as
 * duas a deduplicar. Um `ON CONFLICT (tenant_id, waba_id)` deixava a repetição
 * do mesmo `code` com outro WABA a levantar `23505` em vez de devolver a linha
 * que já lá estava. A forma sem alvo cobre qualquer restrição de unicidade da
 * tabela, que é exactamente o que se quer.
 *
 * O `code_hash` entra já resumido (`$5::bytea`): o `sha256` faz-se no módulo,
 * para que o *code* em claro nunca entre numa cadeia de SQL que um log de
 * consultas lentas pudesse apanhar.
 */
export const SQL_ABRIR = `
  INSERT INTO platform.channel_onboarding
              (tenant_id, waba_id, waac_id, phone_number_id, code_hash)
       VALUES ($1::uuid, $2, $3, $4, $5::bytea)
  ON CONFLICT DO NOTHING
    RETURNING id::text            AS id,
              tenant_id::text     AS tenant_id,
              channel_id::text    AS channel_id,
              waba_id,
              waac_id,
              phone_number_id,
              fase,
              recursos_criados,
              pin_ref,
              motivo
`;

/**
 * A tentativa de um `(tenant_id, waba_id)`, para a repetição devolver o que já
 * havia.
 *
 * Corre **depois** de o `SQL_ABRIR` devolver zero linhas, e só então. Procura
 * pelo WABA e não pelo `code_hash` porque a repetição que interessa ao módulo é
 * a do par: um `code` repetido é o mesmo *popup*, e um `code` novo sobre o mesmo
 * WABA é uma segunda tentativa do mesmo onboarding — as duas devolvem a mesma
 * linha, que é o que «produz 1 canal» quer dizer.
 */
export const SQL_TENTATIVA = `
  SELECT id::text            AS id,
         tenant_id::text     AS tenant_id,
         channel_id::text    AS channel_id,
         waba_id,
         waac_id,
         phone_number_id,
         fase,
         recursos_criados,
         pin_ref,
         motivo
    FROM platform.channel_onboarding
   WHERE tenant_id = $1::uuid
     AND waba_id = $2
`;

/**
 * A transição, por *compare-and-set* sobre a fase esperada.
 *
 * `WHERE fase = $3` é o que a torna atómica: duas transições concorrentes a
 * partir da mesma fase não podem ganhar as duas, e a que perde recebe zero
 * linhas. É a forma que a `0010` usa para a monotonia de
 * `outbound_messages.state`, e a razão é a mesma — ler, decidir e escrever em
 * três idas à base deixa a decisão velha quando a escrita chega.
 *
 * **Quem decide se o par é legal é o `TRANSICOES` do contrato**, e não esta
 * consulta: ver o `docstring` da revisão `0016` para porque não é um gatilho. O
 * que a base impõe é o domínio das nove (`channel_onboarding_fase_ck`), e a
 * suite do *gate* 8 percorre os 81 pares ordenados contra um PostgreSQL real.
 *
 * O `actualizado_at` escreve-se com `clock_timestamp()` e não `now()`, pela
 * razão que a `0015` fixou: o `now()` é o início da transacção, e duas
 * transições na mesma transacção partilhavam-no — o que faria o prazo dos 30
 * minutos do critério 6 contar desde a primeira.
 */
export const SQL_TRANSITAR = `
  UPDATE platform.channel_onboarding
     SET fase = $4,
         motivo = $5,
         actualizado_at = clock_timestamp()
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
     AND fase = $3
     RETURNING fase, actualizado_at
`;

/**
 * Acrescenta um recurso à lista da compensação, **sem reescrever a lista**.
 *
 * `recursos_criados || $4::jsonb` e não um `SET recursos_criados = $4`: a
 * segunda forma exige que quem chama tenha lido a lista antes, e entre a leitura
 * e a escrita cabe outro passo da mesma saga a registar o seu recurso — que se
 * perdia. Um recurso perdido da lista é um recurso **órfão** depois da
 * compensação, e é precisamente o que o critério 7 mede.
 *
 * O `jsonb ||` sobre dois *arrays* concatena-os, e é por isso que a coluna é um
 * *array* e não um objecto (ver o `COMMENT` da coluna na `0016`).
 */
export const SQL_REGISTAR_RECURSO = `
  UPDATE platform.channel_onboarding
     SET recursos_criados = recursos_criados || $3::jsonb,
         actualizado_at = clock_timestamp()
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
     RETURNING recursos_criados
`;

/**
 * Esvazia a lista de recursos. **É o fim da compensação, e o «0 órfãos».**
 *
 * Corre depois de todos os recursos terem sido desfeitos, e nunca antes: a
 * lista vazia é a afirmação de que não há nada pendurado, e esvaziá-la primeiro
 * era apagar o mapa antes de desfazer o caminho.
 *
 * **E corre depois de a fase já estar em `falhado`**, o que é a ordem inversa da
 * que parecia natural. A razão é o `channel_onboarding_canal_ck`: nas seis fases
 * do meio o `channel_id` **não pode** ser nulo, pelo que pôr-lhe `NULL` com a
 * fase ainda em `es_concluido` levanta `23514`. A revisão adversarial
 * apanhou-o — a compensação do critério 7 rebentava no **último** passo, depois
 * de ter desfeito tudo o que havia a desfazer, que é o pior momento possível
 * para rebentar.
 */
export const SQL_LIMPAR_RECURSOS = `
  UPDATE platform.channel_onboarding
     SET recursos_criados = '[]'::jsonb,
         channel_id = NULL,
         pin_ref = NULL,
         actualizado_at = clock_timestamp()
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
     RETURNING recursos_criados
`;

/**
 * Abre um ponto de salvaguarda antes do `INSERT` do canal.
 *
 * **Sem ele, o 409 do critério 4 deixa o *token* no cofre**, e isto foi a
 * revisão adversarial: um `23505` **aborta a transacção inteira** no PostgreSQL,
 * pelo que todas as instruções seguintes respondem `25P02` — incluindo as da
 * compensação, que é quem revoga o *token* que o passo anterior cunhou. O
 * `ROLLBACK` da rota apaga a linha do canal e a da tentativa, mas **o cofre não
 * é transaccional**: o *token* ficava lá, sem nada a apontar para ele e sem
 * ninguém a saber que existe.
 *
 * Com o ponto de salvaguarda, o conflito desfaz-se só até aqui, a ligação
 * continua utilizável, e a compensação corre na mesma transacção. É o mesmo
 * mecanismo que o `assertErroSql` de `db/tests/base.py` usa, e quase pela mesma
 * razão — lá para o teste poder continuar, aqui para a saga poder compensar.
 *
 * **Isto torna a porta 1 do contrato exigível e não só convencionada:** um
 * `SAVEPOINT` fora de um bloco de transacção levanta `25P01`. Quem ligar este
 * módulo a uma ligação em *autocommit* descobre-o no primeiro onboarding, e
 * descobre-o ruidosamente — que é melhor do que descobrir um *token* órfão no
 * cofre seis meses depois.
 */
export const SQL_PONTO_DE_SALVAGUARDA = "SAVEPOINT criar_canal";

/** Desfaz até ao ponto de salvaguarda. A ligação continua utilizável. */
export const SQL_VOLTAR_AO_PONTO = "ROLLBACK TO SAVEPOINT criar_canal";

/**
 * Larga o ponto de salvaguarda quando o `INSERT` passou.
 *
 * Não é higiene: um `SAVEPOINT` por onboarding numa transacção longa acumula, e
 * o PostgreSQL mantém o estado de cada um. Com um passo a usá-lo a diferença é
 * pequena; largá-lo é o que impede que deixe de ser.
 */
export const SQL_LARGAR_O_PONTO = "RELEASE SAVEPOINT criar_canal";

/**
 * Cria o canal. **O 409 do critério 4 é esta instrução a levantar `23505`.**
 *
 * A `tenant_channels_phone_number_id_uq` da `0001` é **global** — sem
 * `tenant_id` na chave —, e é ela que faz o conflito. Não há `SELECT` antes: uma
 * verificação em código seria uma segunda verdade a reconciliar com a primeira,
 * e perderia a corrida entre o `SELECT` e o `INSERT`.
 *
 * **O `estado` nasce `pendente`**, que é a omissão da `0001`, e fica lá até ao
 * *gate* de activação (KAM-093): este ticket não activa canal nenhum, e o
 * `01` §13.2 di-lo por extenso — «nenhum cliente é contactado até ao passo 10
 * passar».
 *
 * O `vertical` entra por parâmetro e não fixado: é configuração (ADR-012), com
 * `CHECK` de forma e não de domínio desde a `0001`.
 */
export const SQL_CRIAR_CANAL = `
  INSERT INTO platform.tenant_channels
              (tenant_id, waba_id, waac_id, phone_number_id, channel_mode,
               vertical, token_ref)
       VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
    RETURNING id::text AS id
`;

/**
 * Liga o canal à tentativa. Corre na **mesma transacção** que o `SQL_CRIAR_CANAL`.
 *
 * É esta atomicidade que faz «1 canal» ser propriedade da base: duas chamadas
 * concorrentes com o mesmo `(tenant_id, waba_id)` não podem ter as duas uma
 * linha em `channel_onboarding`, logo não podem ter as duas um canal.
 *
 * A fase passa a `es_concluido` aqui e não num `SQL_TRANSITAR` à parte, e isso
 * **não** é um atalho à matriz: o módulo valida `iniciado → es_concluido` antes
 * de chamar, e o `WHERE fase = 'iniciado'` prende-o. Juntar as duas escrituras
 * evita que a linha exista com `channel_id` e ainda em `iniciado`, que o
 * `channel_onboarding_canal_ck` permite mas que nenhum passo quer ver.
 */
export const SQL_LIGAR_CANAL = `
  UPDATE platform.channel_onboarding
     SET channel_id = $3::uuid,
         fase = 'es_concluido',
         actualizado_at = clock_timestamp()
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
     AND fase = 'iniciado'
     RETURNING fase
`;

/**
 * Guarda a referência do PIN 2FA. Só em `cloud_only`.
 *
 * Coluna própria e não uma entrada do `recursos_criados` sozinha, pela razão do
 * `COMMENT` da `0016`: a compensação não deve depender de interpretar um `jsonb`
 * para saber que segredo revogar, e o `CHECK` de forma de `SecretRef` só se pode
 * impor sobre uma coluna.
 */
export const SQL_GUARDAR_PIN = `
  UPDATE platform.channel_onboarding
     SET pin_ref = $3,
         actualizado_at = clock_timestamp()
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
     RETURNING pin_ref
`;

/**
 * Apaga o canal que a compensação desfaz.
 *
 * `DELETE` e não `estado = 'encerrado'`, e é a única excepção ao «soft delete:
 * estado, nunca DELETE» do dicionário §2 em todo este módulo. A razão é
 * estreita: o critério 7 pede **0 recursos órfãos**, e um canal `encerrado`
 * continua a ocupar o `phone_number_id` na unicidade global — o dono não
 * conseguia repetir o ES com o mesmo número, que é exactamente o caminho
 * `falhado → iniciado` do `01` §13.1.
 *
 * Quem o corre é o `kamba_batch`, que é o único com `DELETE` desde a `0001`. O
 * `WHERE` leva o `tenant_id` **e** a confirmação de que o canal ainda está
 * `pendente`: um canal que já tenha sido activado não é um recurso desta saga, e
 * apagá-lo era apagar um canal a funcionar.
 */
export const SQL_APAGAR_CANAL = `
  DELETE FROM platform.tenant_channels
        WHERE id = $1::uuid
          AND tenant_id = $2::uuid
          AND estado = 'pendente'
      RETURNING id::text AS id
`;

/**
 * O contador `es_onboardings_7d` do critério 8. **Atravessa tenants.**
 *
 * O limite de dez clientes novos por sete dias é da **nossa app** perante a Meta
 * e não de uma loja (CONFIRMADO, `E1` §3), pelo que a contagem não leva
 * `tenant_id`. Só corre com `BYPASSRLS`; com a política `tenant_iso`, o
 * `kamba_app` veria sempre as suas e contaria mal — o que é pior do que não
 * contar, porque parece certo.
 *
 * **Conta tudo o que entrou na janela, incluindo o abandonado e o falhado.** É o
 * lado conservador, e a razão é que o contador da Meta é dela: se um *popup*
 * fechado consome um lugar na contagem deles é **NÃO VERIFICADO**, e contar de
 * menos fazia-nos passar o tecto e receber a recusa no onboarding de um cliente
 * real. Contar de mais custa esperar; contar de menos custa um cliente.
 *
 * O intervalo entra por parâmetro em dias (`$1`) e não fixado em `interval '7
 * days'`, para que o teste possa medir a fronteira sem esperar uma semana.
 */
export const SQL_CONTAR_JANELA = `
  SELECT count(*)::bigint AS contagem
    FROM platform.channel_onboarding
   WHERE criado_at > now() - ($1::integer * interval '1 day')
`;

/**
 * Passa a `abandonado` as tentativas paradas em `iniciado` há mais do que o
 * prazo. **O critério 6, a segunda metade.**
 *
 * Uma instrução e não uma leitura seguida de N transições: a varredura é de
 * retaguarda e o que importa é que o estado fique certo, não que cada linha
 * passe pelo `SQL_TRANSITAR`. A transição `iniciado → abandonado` é uma das
 * dezesseis, e o `WHERE fase = 'iniciado'` é o que garante que esta instrução
 * **só** faz essa — não há caminho aqui para abandonar uma tentativa que já
 * trocou o *code*.
 *
 * O prazo entra em minutos (`$1`) pela razão da consulta anterior: um teste que
 * esperasse 30 minutos não é um teste.
 *
 * Devolve os `id` para que quem varre possa contar e registar, e **não** o
 * `tenant_id`: um alerta de operação sobre *popups* abandonados não precisa de
 * saber de que lojas são.
 */
export const SQL_ABANDONAR = `
  UPDATE platform.channel_onboarding
     SET fase = 'abandonado',
         motivo = 'sem conclusao no prazo',
         actualizado_at = clock_timestamp()
   WHERE fase = 'iniciado'
     AND actualizado_at < now() - ($1::integer * interval '1 minute')
     RETURNING id::text AS id
`;

/**
 * Regista a recusa do critério 4, **numa transacção própria**.
 *
 * O 409 vem de uma transacção que **reverte** (o `SQL_CRIAR_CANAL` levanta
 * `23505`), pelo que nem a linha do canal nem a actualização da tentativa
 * sobrevivem — é isso que faz «não altera nada» ser literalmente verdadeiro.
 * Esta instrução corre depois, fora dessa transacção, e é o «deixa registo de
 * auditoria».
 *
 * **Não é o `platform.audit_log`**, e a razão é mecânica: ver o `docstring` da
 * revisão `0016`. O domínio de `audit_log.action` tem sete valores, o `CHECK`
 * está na `0006` (fundida), e o *gate* 3b compara-o com o dicionário nos dois
 * sentidos — um oitavo valor deixava a `0006` vermelha.
 *
 * `ON CONFLICT ... DO UPDATE` e não `DO NOTHING`: a tentativa pode já existir
 * (foi o `SQL_ABRIR` desta mesma chamada, revertido — ou uma anterior), e o que
 * se quer é que o motivo da recusa fique lá. O `recursos_criados` vai a `[]` na
 * mesma instrução, porque uma recusa não deixa recurso nenhum **por
 * construção**: o conflito é a primeira escrita que toca fora desta tabela.
 */
export const SQL_REGISTAR_RECUSA = `
  INSERT INTO platform.channel_onboarding
              (tenant_id, waba_id, waac_id, phone_number_id, code_hash,
               fase, motivo)
       VALUES ($1::uuid, $2, $3, $4, $5::bytea, 'falhado', $6)
  ON CONFLICT (tenant_id, waba_id) DO UPDATE
     SET fase = 'falhado',
         motivo = $6,
         channel_id = NULL,
         recursos_criados = '[]'::jsonb,
         actualizado_at = clock_timestamp()
   RETURNING id::text AS id
`;

/**
 * A lista de recursos de uma tentativa, pelo `id`. Para a compensação.
 *
 * Procura pelo `id` e não pelo `(tenant_id, waba_id)` do `SQL_TENTATIVA`, e a
 * razão é o caminho que a usa: a compensação pode correr sobre uma tentativa que
 * outro processo já mudou de WABA é impossível, mas o `id` é o que ela tem em mão
 * — e lê-lo pela chave primária é uma ida à base em vez de duas.
 *
 * **Vive aqui e não embutida no módulo** pela regra deste ficheiro: a suite do
 * *gate* 8 lê estas constantes e corre as cadeias reais contra um PostgreSQL. Uma
 * consulta escrita no meio da lógica é uma consulta que nenhuma bateria exercita.
 */
export const SQL_RECURSOS = `
  SELECT recursos_criados
    FROM platform.channel_onboarding
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
`;

/**
 * A fase corrente de uma tentativa, pelo `id`.
 *
 * A compensação precisa dela porque pode correr a partir de qualquer passo: a
 * transição para `falhado` sai de onde a tentativa estiver, e assumir a fase era
 * passar à matriz um par que ela recusa.
 */
export const SQL_FASE = `
  SELECT fase
    FROM platform.channel_onboarding
   WHERE id = $1::uuid
     AND tenant_id = $2::uuid
`;

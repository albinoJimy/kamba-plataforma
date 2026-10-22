/**
 * O SQL dos modos da conversa (KAM-018), num ficheiro só.
 *
 * Em constantes e separado da lógica pela razão que o `chr/consultas.ts` e o
 * `outbound/consultas.ts` já escreveram: a *suite* do *gate* 8 corre **estas**
 * cadeias e não cópias delas, e foi assim que o KAM-009 descobriu um `coalesce`
 * em falta que uma cópia no teste escondia.
 *
 * **Os marcadores são `$n` e a ordem em que aparecem no texto importa**: o
 * `pg8000` da suite Python não tem `$n`, tem `%s`, e liga-os pela ordem de
 * aparição. A `ConsultaDoTypeScript` reordena, mas só se a numeração for
 * contígua a partir de 1.
 *
 * ## Três coisas que este SQL faz, e que vale a pena ver antes de as ler
 *
 * **A exclusão mútua é da base.** O `SQL_TRANCAR_CONVERSA` é um
 * `pg_advisory_xact_lock` sobre `(tenant_id, contact_id)`, e é o mesmo *lock*
 * que a transição de modo e a verificação pré-envio tomam. Dentro da secção
 * crítica, um dos dois corre inteiro antes de o outro começar — o que é o que
 * torna «o bot não fala depois de o *echo* estar registado» uma propriedade e
 * não uma probabilidade.
 *
 * **A tabela de transições é da base também.** O `SQL_MUDAR_MODO` leva
 * `AND mode = ANY($4)` com o que o `origensDe` do `transicoes.ts` devolve, e não
 * lê para decidir e escreve depois. É o padrão do `SQL_AVANCAR_ESTADO` do
 * KAM-015: dois processos a disparar o mesmo gatilho chegam em dois processos, e
 * só a base os serializa. O `transicoes.ts` existe para **saber qual** é a
 * transição; o predicado existe para ganhar a corrida.
 *
 * **A actividade humana é monótona.** Todas as escritas de
 * `last_human_activity_at` passam por `GREATEST`, e não é zelo: a Meta não
 * garante ordem nos *webhooks* (`E1` §5, CONFIRMADO), pelo que um *echo* antigo
 * pode chegar depois de um recente. Sem o `GREATEST`, esse *echo* fazia o
 * relógio do silêncio andar para trás e o `PreSendGuard` deixar passar um envio
 * que devia suprimir.
 */

/**
 * Toma o *lock* da conversa. **Dentro** de uma transacção, sempre.
 *
 * `pg_advisory_xact_lock` é largado no `COMMIT`; fora de uma transacção, cada
 * instrução é a sua própria transacção e o *lock* é largado na instrução
 * seguinte — o que é o mesmo que não existir. É por isso que o `ComTenant` do
 * `contrato.ts` não entrega o cliente a ninguém fora de uma transacção.
 *
 * **A chave é `(tenant_id, contact_id)` e não a conversa**, e é o que o critério
 * 2 escreve: `pg_advisory_xact_lock(hash(tenant_id, contact_id))`. Um contacto
 * pode ter conversas em canais diferentes, e a chave por contacto trava-as
 * todas juntas — o que é mais largo do que o estritamente necessário para o
 * guarda, e é exactamente o que o `onOptOut` precisa: ele pausa **todas** as
 * conversas de um contacto, e com uma chave por conversa pausava-as uma a uma
 * com janelas entre elas.
 *
 * `hashtextextended(texto, 0)` e não `hashtext`: o primeiro devolve `bigint`, que
 * é a largura que o `pg_advisory_xact_lock(bigint)` aceita; o segundo devolve
 * `int4` e obrigava à forma de dois argumentos. A semente `0` é fixa de
 * propósito — uma semente que variasse dava chaves diferentes para a mesma
 * conversa em processos diferentes, que é o mesmo que não ter *lock*.
 *
 * **O separador `':'` não é decoração.** Sem ele, `hash(a || b)` colidia para
 * pares diferentes cuja concatenação coincidisse; com UUID de largura fixa isso
 * não acontece hoje, mas a propriedade passava a depender da largura.
 */
export const SQL_TRANCAR_CONVERSA = `
  SELECT pg_advisory_xact_lock(hashtextextended($1::text || ':' || $2::text, 0))
`;

/**
 * O contacto de uma conversa, e **só** ele. Corre **antes** do *lock*.
 *
 * Existe porque a chave do *lock* é `(tenant_id, contact_id)` e quem chama tem
 * o `conversation_id` e mais nada — é o que a porta `MudarModo` do
 * `ConsentGate` dá. Alguma coisa tem de ser lida antes de trancar.
 *
 * **É uma consulta à parte e não o `SQL_CONVERSA_PARA_MODO` com o resultado
 * parcialmente ignorado**, e a razão é que a diferença entre as duas é a única
 * que importa aqui: esta pode correr antes do *lock* porque o `contact_id` de
 * uma conversa só muda numa fusão de contactos, que corre com `kamba_identity`
 * e não com este papel; a outra **não pode**, porque o modo que ela traz decide,
 * e decidir antes do *lock* é decidir fora da secção crítica. Com uma consulta
 * só, nada no código nem nos testes distinguia os dois usos — e a base falsa das
 * baterias passou a poder exigir o *lock* ao `SQL_CONVERSA_PARA_MODO` sem
 * excepções.
 *
 * O `tenant_id` está no predicado além da RLS, pela razão do `SQL_JANELA` do
 * KAM-015: repeti-lo é o que torna a consulta correcta mesmo que alguém a corra
 * sem contexto — devolve zero linhas em vez da conversa de outro.
 */
export const SQL_CONTACTO_DA_CONVERSA = `
  SELECT contact_id::text AS contact_id
    FROM platform.conversations
   WHERE tenant_id = $1 AND id = $2
`;

/**
 * O modo e a actividade humana de uma conversa. **Só com o *lock* tomado.**
 *
 * É a leitura que decide — na máquina de modos e na guarda pré-envio —, e é por
 * isso que não corre antes do `SQL_TRANCAR_CONVERSA`. Ver
 * `SQL_CONTACTO_DA_CONVERSA` para a que corre antes, e porque são duas.
 */
export const SQL_CONVERSA_PARA_MODO = `
  SELECT mode, last_human_activity_at
    FROM platform.conversations
   WHERE tenant_id = $1 AND id = $2
`;

/**
 * As conversas de um contacto, para o `onOptOut`. Como `kamba_app`, com contexto.
 *
 * Um contacto pode ter conversa em mais de um canal do mesmo tenant (a
 * `conversations_tenant_contact_channel_uq` da `0009` permite uma por canal), e
 * o «PARAR» é do **contacto** e não de um canal: o critério 7 diz
 * `onOptOut(contact)`.
 *
 * `ORDER BY channel_id` para a ordem ser determinística — é o que faz duas
 * execuções do `onOptOut` emitirem os eventos pela mesma ordem, e é o que a
 * bateria compara.
 */
export const SQL_CONVERSAS_DO_CONTACTO = `
  SELECT id::text AS id, mode, last_human_activity_at
    FROM platform.conversations
   WHERE tenant_id = $1 AND contact_id = $2
   ORDER BY channel_id
`;

/**
 * Muda o modo, e **devolve o modo que substituiu**. Precisa do *lock* tomado.
 *
 * O `$4` é a lista dos modos de onde se pode sair para o `$3`, e vem do
 * `origensDe` do `transicoes.ts`. O `UPDATE` que não casa linha nenhuma é a
 * corrida perdida: outro processo já transitou, e **não se emite evento** — é a
 * mesma leitura do «zero linhas» que o `SQL_AVANCAR_ESTADO` do KAM-015 fixou, e
 * pela mesma razão. Emitir a partir de uma leitura prévia publicava duas
 * mudanças para uma transição.
 *
 * O `modo_antes` sai daqui e não de uma leitura anterior, exactamente como o
 * `estado_antes` do KAM-015: com dois gatilhos concorrentes, os dois leram
 * `humano` e só um transitou, e é o `modo_antes` que diz qual. A forma é a
 * mesma — `FROM (SELECT ... FOR UPDATE) AS antes` —, porque um
 * `RETURNING c.mode` devolve o valor **novo** e não o que se substituiu, e
 * porque o `FOR UPDATE` é o que torna o par «verificar o predicado, escrever»
 * atómico mesmo para quem corra esta consulta sem o *lock* da conversa.
 *
 * **O `$5` é a actividade humana e pode ser `NULL`.** O `GREATEST` do
 * PostgreSQL **ignora** os nulos e devolve o maior dos restantes (ao contrário
 * do SQL padrão), pelo que um gatilho que não seja actividade humana passa
 * `NULL` e a coluna fica como estava. Um `CASE WHEN $5 IS NULL` fazia o mesmo
 * com mais texto; um `SET last_human_activity_at = $5` apagava a actividade
 * humana de uma conversa a cada `handoff_pedido`, que é o contrário do que a
 * coluna existe para guardar.
 *
 * **O `$1` aparece duas vezes**, como no `SQL_AVANCAR_ESTADO` do KAM-015: na
 * subconsulta e no predicado de fora. A consequência é que esta constante não
 * se consegue correr pela `ConsultaDoTypeScript` da suite Python — ela recusa
 * marcadores repetidos —, e não é perda: quem a exercita contra a base é
 * `tests_bd/modos.bd.test.ts`, em TypeScript e com o `pg`, que tem `$n` de
 * verdade.
 */
export const SQL_MUDAR_MODO = `
  UPDATE platform.conversations AS c
     SET mode                   = $3,
         last_human_activity_at = GREATEST(c.last_human_activity_at, $5)
    FROM (
      SELECT id, mode
        FROM platform.conversations
       WHERE tenant_id = $1 AND id = $2
         FOR UPDATE
    ) AS antes
   WHERE c.tenant_id = $1
     AND c.id = antes.id
     AND antes.mode = ANY($4::text[])
  RETURNING antes.mode AS modo_antes, c.mode AS modo_depois
`;

/**
 * Só a actividade humana, sem tocar no modo. Precisa do *lock* tomado.
 *
 * É o caso `sem_efeito` de um gatilho que **é** actividade humana: o dono a
 * responder numa conversa que já está em `dono`, ou um agente a escrever numa
 * que já está em `humano`. Não há transição, e há mesmo assim uma escrita — e é
 * esta que adia o silêncio do dono e que o `PreSendGuard` compara com o início
 * do turno.
 *
 * Sem esta consulta, o segundo *echo* de uma conversa já em `dono` não
 * actualizava nada e o `silencio_dono_min` contava-se do **primeiro** *echo*: o
 * bot retomava a palavra a meio de uma conversa que o dono estava a fazer, trinta
 * minutos depois de a ter começado. Era o defeito que o critério 1 do KAM-018
 * quer dizer com «sem actividade do dono».
 */
export const SQL_REGISTAR_ACTIVIDADE_HUMANA = `
  UPDATE platform.conversations
     SET last_human_activity_at = GREATEST(last_human_activity_at, $3)
   WHERE tenant_id = $1 AND id = $2
  RETURNING mode
`;

/**
 * Pausa as conversas que ficaram 24 h em atendimento humano sem humano nenhum.
 *
 * É o *job* idempotente do critério 7, e a idempotência é do **predicado** e não
 * de uma chave: depois da primeira passagem as linhas já estão em `pausada` e o
 * `mode = ANY($3)` deixa de casar. Correr o *job* duas vezes seguidas pausa N e
 * depois 0, e não há coluna de controlo a manter — ver a nota da revisão `0016`.
 *
 * **O relógio das 24 h não é só o `last_human_activity_at`.** Uma conversa que
 * passou a `humano` e onde **nunca** houve resposta humana tem a coluna a
 * `NULL`, e é precisamente o caso que o critério descreve («24 h sem humano após
 * handoff»). O instante a partir do qual se conta é então o do *handoff*, que
 * vive em `platform.handoffs.opened_at` (KAM-019, revisão `0011`) — tabela em que
 * `kamba_app` tem `SELECT` desde essa revisão. O `max` é porque uma conversa pode
 * ter tido mais do que um *handoff*: conta-se do mais recente.
 *
 * **E se os dois forem `NULL`, a conversa não é pausada**, o que a deixa em
 * `humano` indefinidamente. É deliberado e é o lado seguro: ficar em `humano`
 * significa que o bot continua calado, e o invariante da §10.2 é «o bot nunca
 * interrompe uma conversa em modo dono/humano». Uma conversa em `humano` sem
 * actividade humana **e** sem *handoff* só pode vir de uma escrita que não passou
 * por esta máquina; pausá-la por omissão era deixar o assistente retomar uma
 * conversa cuja história não conhecemos.
 *
 * **Sem *lock*, e isso é uma escolha escrita.** O *job* não toma o
 * `pg_advisory_xact_lock` da conversa, porque não precisa: antes dele o modo é
 * `humano` e depois é `pausada`, e o `PreSendGuard` suprime o envio do bot nos
 * dois. Qualquer intercalação com o guarda dá o mesmo desfecho — 0 mensagens —, e
 * um *lock* por linha num `UPDATE` em lote obrigava a um ciclo de N transacções
 * para não ganhar propriedade nenhuma.
 */
export const SQL_PAUSAR_POR_INACTIVIDADE = `
  UPDATE platform.conversations AS c
     SET mode = $4
   WHERE c.tenant_id = $1
     AND c.mode = ANY($3::text[])
     AND COALESCE(
           c.last_human_activity_at,
           (SELECT max(h.opened_at) FROM platform.handoffs AS h
             WHERE h.tenant_id = c.tenant_id AND h.conversation_id = c.id)
         ) < $2
  RETURNING c.id::text AS id, c.contact_id::text AS contact_id
`;

/**
 * Registra um envio do bot que o guarda descartou. Como `kamba_app`, com
 * contexto.
 *
 * `state = 'suppressed_by_human'` é o sexto valor de `outbound_messages.state`,
 * que nasceu na revisão `0010` (KAM-015) por antecipação deste ticket — o *gate*
 * 3b lê o AST de cada revisão isoladamente, e alargar o domínio aqui deixava a
 * `0010` vermelha por lhe faltar um valor.
 *
 * **A linha é escrita pelo guarda e não pelo adapter**, e a razão é a ordem dos
 * sete passos do `outbound/adapter.ts`: o guarda é o passo 3 e o
 * `SQL_ENFILEIRAR` é o passo 4. Quando o guarda recusa, o adapter devolve
 * `GUARD_REFUSED` e **nunca** enfileira — não há linha para marcar. Quem tem de
 * a escrever é quem sabe que suprimiu.
 *
 * `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id`, com a
 * mesma chave do `SQL_ENFILEIRAR` e por duas razões: a repetição do mesmo envio
 * suprimido deixa **uma** linha (o `RETURNING` vazio é o sinal de «já passou»),
 * e um envio que já tinha sido enfileirado antes de o guarda recusar não é
 * reescrito como suprimido — o que aconteceu continua escrito.
 *
 * O `kind` vem de quem chama e **não se lê o template para o confirmar**: um
 * corpo de template é registado como `utility`, que é o que o `categoriaDe` do
 * KAM-015 devolve quando não encontra a linha do template. Ir à base buscar a
 * categoria exacta de uma mensagem que **não** vai sair era uma leitura para
 * nada, e a categoria que a Meta cobraria por uma mensagem que nunca enviou não
 * é um facto. O `template_name` acompanha-o, porque a
 * `outbound_messages_template_ck` exige o par.
 */
export const SQL_SUPRIMIR_ENVIO = `
  INSERT INTO platform.outbound_messages
         (tenant_id, channel_id, contact_id, conversation_id,
          idempotency_key, kind, template_name, state)
  VALUES ($1, $2, $3, $4, $5, $6, $7, 'suppressed_by_human')
      ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
   RETURNING id::text AS id
`;

/**
 * `SELECT platform.evt_emitir(...)` para `conversation.mode_changed`.
 *
 * Precisa de contexto de tenant e do papel `kamba_app`, e corre **dentro** da
 * transacção da transição: o `evt_emitir` escreve no `events_outbox` do KAM-005,
 * pelo que o evento e a mudança de modo confirmam juntos ou não confirmam
 * nenhum. É a propriedade que o `chr/eventos.ts` **não** tem para o
 * `contact.merged` — lá a fusão corre com `kamba_identity` e a emissão fora da
 * transacção dela, e a janela está declarada em `docs/chr.md` §5. Aqui não há
 * janela, porque quem escreve o modo e quem emite são o mesmo papel.
 *
 * `SECURITY INVOKER` (a omissão do `evt_emitir`): a função corre com os
 * privilégios e o contexto de quem a chama, pelo que o `WITH CHECK` da política
 * `tenant_iso` continua a valer sobre o `INSERT` no outbox.
 *
 * Os marcadores são `$n` contíguos a partir de 1, para a `ConsultaDoTypeScript`
 * os poder reordenar.
 */
export const SQL_EMITIR_MODE_CHANGED = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb
  ) AS event_id
`;

/**
 * O SQL da coexistência (KAM-017).
 *
 * Em constantes e num módulo só, pela razão que o `outbound/consultas.ts` do
 * KAM-015, o `chr/consultas.ts` do KAM-014 e o `qualidade/consultas.ts` do
 * KAM-021 escreveram: a *suite* do *gate* 8 corre **estas** cadeias e não
 * cópias delas, e foi assim que o KAM-009 descobriu um `coalesce` em falta que
 * uma cópia no teste escondia.
 *
 * ## Tudo parametrizado, e o `tenant_id` no predicado além da RLS
 *
 * O módulo corre como `kamba_app`, sujeito à RLS, mas um processo de retaguarda
 * pode chamá-lo com outro papel; uma interpolação aqui lia os canais de todos
 * os *tenants* no dia em que alguém a chamasse com o papel errado. O
 * `tenant_id` está no predicado **além** da política pela razão do
 * `SQL_JANELA` do KAM-015: ela já o garante, e repeti-lo é o que torna a
 * consulta correcta mesmo corrida sem contexto — devolve zero linhas em vez do
 * canal de outro.
 *
 * ## As duas varreduras não levam `tenant_id`, e isso é decisão
 *
 * O `SQL_PARA_ALERTAR`, o `SQL_PARA_FALHAR` e o `SQL_PARA_AVISAR` percorrem
 * prazos vencidos **na plataforma inteira**: um prazo que caiu não é problema
 * de uma loja, e quem os corre é o processo de retaguarda. Correm sob
 * `BYPASSRLS` — como o `es_onboardings_7d` do KAM-016 —, e por isso devolvem o
 * `tenant_id` de cada linha: quem trata cada uma volta a entrar com contexto.
 * É a razão de o `channel_coexistence_prazo_idx` não começar pelo `tenant_id`.
 */

/**
 * Abre (ou reabre) a coexistência de um canal, e devolve a linha.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante de arranque, `$4`
 * o prazo.
 *
 * ## A reconexão **repõe** e não insere, e é aqui que o critério 9 vive
 *
 * «A reconexão `desligado → iniciado` reutiliza o ES de KAM-016 **sem criar
 * canal duplicado**.» A unicidade `(tenant_id, channel_id)` da `0018` torna
 * isso propriedade da base; o que esta instrução acrescenta é o que acontece na
 * segunda vez: `ON CONFLICT … DO UPDATE` **repõe** a linha ao estado inicial —
 * passos vazios, relógios a nulo, contagens a zero — em vez de a deixar como
 * estava.
 *
 * Repor e não deixar: uma reconexão é uma sincronização **nova**, e o `E1` §2 é
 * explícito em que cada passo corre uma vez **por onboarding**. Deixar os
 * `passos_feitos` da ligação anterior fazia a sincronização nova nascer
 * concluída sem ter corrido, que é precisamente o modo de falhar que o prazo de
 * 24 h existe para apanhar.
 *
 * **O `motivo_desligamento` e o `desligado_em` também se limpam**, e as duas
 * juntas: o `channel_coexistence_desligamento_ck` exige que tenham as duas
 * metades ou nenhuma, e limpar só uma era um `23514` na reconexão.
 */
export const SQL_ABRIR = `
  INSERT INTO platform.channel_coexistence
         (tenant_id, channel_id, estado, iniciado_em, prazo_em)
  VALUES ($1, $2, 'a_sincronizar', $3, $4)
  ON CONFLICT (tenant_id, channel_id) DO UPDATE
     SET estado              = 'a_sincronizar',
         passos_feitos       = '{}'::text[],
         iniciado_em         = EXCLUDED.iniciado_em,
         prazo_em            = EXCLUDED.prazo_em,
         alertado_em         = NULL,
         concluido_em        = NULL,
         contactos_vistos    = 0,
         mensagens_vistas    = 0,
         meta_error_code     = NULL,
         avisado_em          = NULL,
         motivo_desligamento = NULL,
         desligado_em        = NULL,
         actualizado_at      = now()
  RETURNING id::text AS id
`;

/** A coexistência de um canal, por canal. */
export const SQL_POR_CANAL = `
  SELECT id::text         AS id,
         estado           AS estado,
         passos_feitos    AS passos_feitos,
         iniciado_em      AS iniciado_em,
         prazo_em         AS prazo_em,
         alertado_em      AS alertado_em,
         concluido_em     AS concluido_em,
         contactos_vistos AS contactos_vistos,
         mensagens_vistas AS mensagens_vistas,
         meta_error_code  AS meta_error_code,
         ultimo_echo_em   AS ultimo_echo_em,
         avisado_em       AS avisado_em,
         motivo_desligamento AS motivo_desligamento,
         desligado_em     AS desligado_em
    FROM platform.channel_coexistence
   WHERE tenant_id = $1 AND channel_id = $2
`;

/**
 * Soma as contagens de um lote e marca o passo — **uma vez só**.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o passo, `$4` contactos, `$5`
 * mensagens.
 *
 * ## O «2.ª execução = *no-op*» do critério 3 é do PostgreSQL
 *
 * O predicado `NOT ($3 = ANY (passos_feitos))` é o que faz a segunda passagem
 * devolver **zero linhas**. Não há `SELECT` antes: entre o `SELECT` e o
 * `UPDATE` cabe outro processo, e o critério pede «cada passo executado uma
 * vez» e não «quase sempre uma vez». É a mesma forma do `SQL_MUDAR_MODO` da
 * `0016` e do `SQL_AVANCAR_ESTADO` da `0010`.
 *
 * **E o estado tem de ser `a_sincronizar`**: um passo que chegue depois de o
 * prazo das 24 h ter caído não ressuscita uma sincronização `falhada`. A Meta
 * reenvia durante sete dias, e sem este predicado um `history` atrasado
 * desfazia o *offboard* que o critério 3 acabou de pedir.
 */
export const SQL_MARCAR_PASSO = `
  UPDATE platform.channel_coexistence
     SET passos_feitos    = passos_feitos || $3::text,
         contactos_vistos = contactos_vistos + $4::integer,
         mensagens_vistas = mensagens_vistas + $5::integer,
         actualizado_at   = now()
   WHERE tenant_id = $1
     AND channel_id = $2
     AND estado = 'a_sincronizar'
     AND NOT ($3::text = ANY (passos_feitos))
  RETURNING passos_feitos AS passos_feitos
`;

/**
 * Fecha a sincronização em `sincronizado` quando os dois passos correram.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante.
 *
 * O predicado `passos_feitos @> ARRAY['contactos','historico']` é a condição
 * inteira, e está na instrução e não no código pela mesma razão de sempre:
 * entre ler os passos e escrever o estado cabe o outro lote.
 */
export const SQL_CONCLUIR = `
  UPDATE platform.channel_coexistence
     SET estado         = 'sincronizado',
         concluido_em   = $3,
         actualizado_at = now()
   WHERE tenant_id = $1
     AND channel_id = $2
     AND estado = 'a_sincronizar'
     AND passos_feitos @> ARRAY['contactos','historico']::text[]
  RETURNING id::text AS id
`;

/**
 * Fecha a sincronização em `sincronizado_sem_historico` (critério 4).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante, `$4` o código da
 * Meta.
 *
 * **Terminal e bem-sucedido**, e por isso escreve o `concluido_em` como o
 * `SQL_CONCLUIR` escreve: o cliente não partilhou histórico, o que é uma
 * escolha dele e não uma falha nossa — ver a nota do `ESTADOS` no contrato.
 *
 * **Não exige que o passo `historico` tenha corrido**, e é de propósito: o erro
 * 2593109 chega *em vez* do histórico, não depois dele. Exigir o passo fazia o
 * caminho normal do critério 4 ser impossível.
 */
export const SQL_CONCLUIR_SEM_HISTORICO = `
  UPDATE platform.channel_coexistence
     SET estado          = 'sincronizado_sem_historico',
         concluido_em    = $3,
         meta_error_code = $4::integer,
         actualizado_at  = now()
   WHERE tenant_id = $1
     AND channel_id = $2
     AND estado = 'a_sincronizar'
  RETURNING id::text AS id
`;

/**
 * Marca o alerta das 12 h — **uma vez só**, e devolve quem alertou.
 *
 * Parâmetros: `$1` o instante do corte (agora menos 12 h), `$2` o instante.
 *
 * O `alertado_em IS NULL` é o que torna o alerta idempotente: a segunda
 * varredura na mesma janela devolve zero linhas. Sem ele, um processo chamado
 * de cinco em cinco minutos alertava doze vezes por hora durante doze horas.
 */
export const SQL_ALERTAR_VENCIDAS = `
  UPDATE platform.channel_coexistence
     SET alertado_em    = $2,
         actualizado_at = now()
   WHERE estado = 'a_sincronizar'
     AND alertado_em IS NULL
     AND iniciado_em <= $1
  RETURNING id::text AS id, tenant_id::text AS tenant_id, channel_id::text AS channel_id
`;

/**
 * Marca `falhado` tudo o que passou do prazo, e devolve quem falhou.
 *
 * Parâmetros: `$1` o instante.
 *
 * O `prazo_em <= $1` lê a **coluna** e não `now() - interval '24 hours'`, e é
 * essa a razão de o prazo ser coluna: com o relógio acelerado dos testes, um
 * prazo derivado de `now()` na consulta não se acelera sem mexer no servidor.
 *
 * O *offboard* do critério 3 é o que quem chama faz com estas linhas: este
 * módulo marca o estado e emite, e quem reagenda o Embedded Signup é o KAM-093
 * (a UI) sobre o `falhado → iniciado` do KAM-016.
 */
export const SQL_FALHAR_VENCIDAS = `
  UPDATE platform.channel_coexistence
     SET estado         = 'falhado',
         actualizado_at = now()
   WHERE estado = 'a_sincronizar'
     AND prazo_em <= $1
  RETURNING id::text AS id, tenant_id::text AS tenant_id, channel_id::text AS channel_id
`;

/**
 * Regista um *echo* do dono: move o relógio e **limpa o aviso**.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante.
 *
 * O `avisado_em = NULL` é metade do critério 6 e não um extra: sem ele, um
 * canal avisado uma vez nunca mais era avisado, porque o predicado do aviso
 * filtra por `avisado_em IS NULL`. Actividade do dono **reabre** a janela.
 *
 * `GREATEST` e não atribuição directa, pela razão que o `SQL_MUDAR_MODO` da
 * `0016` escreveu para o `last_human_activity_at`: dois *echoes* fora de ordem
 * — e eles chegam fora de ordem, porque a fila é de concorrência 1 mas a Meta
 * reentrega — não podem recuar o relógio.
 */
export const SQL_REGISTAR_ECHO = `
  UPDATE platform.channel_coexistence
     SET ultimo_echo_em = GREATEST(COALESCE(ultimo_echo_em, $3), $3),
         avisado_em     = NULL,
         actualizado_at = now()
   WHERE tenant_id = $1 AND channel_id = $2
  RETURNING ultimo_echo_em AS ultimo_echo_em
`;

/**
 * Marca o aviso de inactividade — **uma vez só** — e devolve quem avisar.
 *
 * Parâmetros: `$1` o instante do corte (agora menos 10 dias), `$2` o instante.
 *
 * **Só canais que acabaram de sincronizar**, e os dois estados de sucesso
 * contam: um canal cuja sincronização falhou já não está em coexistência, e
 * avisá-lo de inactividade era avisar de um problema que não é o dele.
 *
 * O `COALESCE(ultimo_echo_em, iniciado_em)` é o caso do canal que **nunca**
 * teve *echo*: o relógio conta do arranque. Sem o `COALESCE`, um dono que nunca
 * escreveu na app — exactamente quem o aviso existe para apanhar — nunca era
 * avisado, porque `NULL <= $1` é `NULL`.
 */
export const SQL_AVISAR_INACTIVOS = `
  UPDATE platform.channel_coexistence
     SET avisado_em     = $2,
         actualizado_at = now()
   WHERE estado IN ('sincronizado', 'sincronizado_sem_historico')
     AND desligado_em IS NULL
     AND avisado_em IS NULL
     AND COALESCE(ultimo_echo_em, iniciado_em) <= $1
  RETURNING id::text AS id, tenant_id::text AS tenant_id, channel_id::text AS channel_id
`;

/**
 * Regista o desligamento na coexistência do canal.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o motivo canónico, `$4` o
 * instante.
 *
 * O `desligado_em IS NULL` é a primeira metade do «repetir o mesmo evento 2×
 * produz 1 transição» do critério 5. A segunda está no `SQL_DESLIGAR_CANAL`, e
 * as duas correm na mesma transacção: se só uma mordesse, as duas tabelas
 * discordavam sobre se o canal está desligado.
 */
export const SQL_REGISTAR_DESLIGAMENTO = `
  UPDATE platform.channel_coexistence
     SET motivo_desligamento = $3,
         desligado_em        = $4,
         actualizado_at      = now()
   WHERE tenant_id = $1
     AND channel_id = $2
     AND desligado_em IS NULL
  RETURNING id::text AS id
`;

/**
 * Passa o canal a `desligado` — **uma vez só**.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante do
 * `account_update`.
 *
 * O `estado <> 'desligado'` é o que faz a segunda passagem devolver zero
 * linhas, e é por isso que «repetir o mesmo evento 2× produz 1 transição» não
 * precisa de um `if`: o predicado do `UPDATE` decide, e decide sob
 * concorrência. É a forma do `SQL_RESTRINGIR` do KAM-021.
 *
 * **Não se mexe em `encerrado` nem em `suspenso`.** Um canal encerrado não se
 * desliga — já não existe —, e um suspenso está suspenso por decisão nossa que
 * um *webhook* da Meta não revoga. O domínio da `0001` tem seis valores e este
 * predicado nomeia os três de onde faz sentido cair.
 */
export const SQL_DESLIGAR_CANAL = `
  UPDATE platform.tenant_channels
     SET estado                 = 'desligado',
         last_account_update_at = GREATEST(COALESCE(last_account_update_at, $3), $3)
   WHERE tenant_id = $1
     AND id = $2
     AND estado IN ('pendente', 'ativo', 'restrito')
  RETURNING phone_number_id AS phone_number_id
`;

/**
 * Escreve o `coexistence_synced_at` do canal.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o instante.
 *
 * **Uma vez, quando a sincronização acaba** — e não a cada lote de `history`.
 * «Sincronizou» é um facto e não um progresso, e um carimbo que se mexe a cada
 * lote respondia «há cinco minutos» a uma pergunta que é «quando é que este
 * canal ficou pronto».
 *
 * O `IS NULL` no predicado não está cá: uma reconexão **tem** de o reescrever,
 * e é por isso que o `GREATEST` chega — o carimbo só anda para a frente.
 */
export const SQL_MARCAR_SINCRONIZADO = `
  UPDATE platform.tenant_channels
     SET coexistence_synced_at = GREATEST(COALESCE(coexistence_synced_at, $3), $3)
   WHERE tenant_id = $1 AND id = $2
  RETURNING coexistence_synced_at AS coexistence_synced_at
`;

/**
 * O canal pelo seu `phone_number_id`, com o modo e o estado.
 *
 * É a resolução que os tratadores de *webhook* fazem antes de qualquer escrita.
 * Lê o `channel_mode` porque é ele que decide o que fica activo (critério 8):
 * em `cloud_only` não há sincronização nem *echoes*.
 */
export const SQL_CANAL_POR_NUMERO = `
  SELECT id::text     AS channel_id,
         channel_mode AS channel_mode,
         estado       AS estado
    FROM platform.tenant_channels
   WHERE tenant_id = $1 AND phone_number_id = $2
`;

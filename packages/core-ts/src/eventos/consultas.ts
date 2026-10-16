/**
 * O SQL do publicador, num sítio só (KAM-005, `docs/tecnica/06` §6.2).
 *
 * Está separado do publicador pela mesma razão que o `identity/consultas.ts`:
 * para se poder ler o SQL sem ler o laço, e para as mutações do
 * `db/mutacoes.py` terem onde morder. Cada cadeia é usada uma vez.
 *
 * **Tudo parametrizado.** Nenhuma destas cadeias é construída por interpolação:
 * o publicador corre como `kamba_batch`, que tem `BYPASSRLS`, e uma injecção
 * aqui lia o outbox de todos os tenants.
 */

/**
 * O lock consultivo que faz do processo o líder.
 *
 * O valor 7101 é o de `docs/tecnica/06` §6.2. É um `pg_try_advisory_lock` de
 * **sessão** (não `_xact`): tem de sobreviver às transacções do laço, e larga-se
 * quando a ligação morre — que é o que faz a réplica assumir sem ninguém
 * intervir. Um *kill -9* do líder fecha a ligação; o PostgreSQL larga o lock.
 */
export const LOCK_DO_PUBLICADOR = 7101;

/** Tenta ficar líder. `true` se ficou; `false` se já há líder. */
export const SQL_ELEGER = "SELECT pg_try_advisory_lock($1) AS lider";

/** Larga a liderança (encerramento limpo). */
export const SQL_LARGAR = "SELECT pg_advisory_unlock($1) AS largou";

/**
 * As linhas por publicar, trancadas.
 *
 * `ORDER BY id` é a ordem de escrita, e é a que preserva a ordem do agregado:
 * o `seq` sai de um contador na transacção do produtor, pelo que o `id` maior é
 * sempre o `seq` maior do mesmo agregado.
 *
 * `FOR UPDATE SKIP LOCKED` não é para concorrência entre publicadores — só um é
 * líder — mas para não bloquear atrás de uma linha que outra transacção tenha
 * trancada (uma correcção manual, o *job* de retenção). Sem o `SKIP LOCKED`, o
 * laço parava no primeiro obstáculo.
 */
export const SQL_PENDENTES = `
  SELECT id, event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
         particao, envelope, tentativas
    FROM platform.events_outbox
   WHERE publicado_at IS NULL AND proxima_tentativa_at <= now()
   ORDER BY id
   LIMIT $1
     FOR UPDATE SKIP LOCKED`;

/** As subscrições activas. Lidas a cada ciclo: activar uma não exige reinício. */
export const SQL_SUBSCRICOES = `
  SELECT consumer, tipo, versao_max, finalidade, exige_ordem
    FROM platform.evt_subscricoes
   WHERE activo`;

/**
 * Arquiva no `events_log` o que se vai marcar como publicado.
 *
 * Copia da própria linha do outbox, e não do envelope reconstruído: as colunas
 * de indexação (`tenant_id`, `agregado_*`) são as que a base escreveu. As três
 * que só existem no envelope (`ocorrido_em`, `registado_em`, `classe_pii`)
 * saem dele — e é por isso que o publicador valida o envelope **antes** de
 * chegar aqui: um `ocorrido_em` em falta dava `NULL` numa coluna `NOT NULL` e
 * abortava a transacção inteira, perdendo o lote.
 *
 * `ON CONFLICT DO NOTHING`: uma republicação depois de um *kill -9* volta a
 * arquivar o mesmo evento, e o arquivo é imutável — a segunda vez não faz nada.
 */
export const SQL_ARQUIVAR = `
  INSERT INTO platform.events_log (
           event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
           agregado_seq, ocorrido_em, registado_em, classe_pii, envelope)
  SELECT event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
         agregado_seq,
         (envelope->>'ocorrido_em')::timestamptz,
         (envelope->>'registado_em')::timestamptz,
         envelope->>'classe_pii',
         envelope
    FROM platform.events_outbox
   WHERE id = ANY($1)
  ON CONFLICT DO NOTHING`;

/**
 * Marca o lote como publicado. É o último passo antes do `COMMIT`.
 *
 * `clock_timestamp()` e **não** `now()`. O `now()` do PostgreSQL é
 * `transaction_timestamp()`: o instante em que a transacção do ciclo começou,
 * isto é, **antes** do `SELECT ... FOR UPDATE` e antes de todos os `add` do
 * lote. Com ele, o atraso `publicado_at - criado_at` — que é o número do
 * critério 8 e o que a métrica `evt_outbox_lag_seconds` acompanha — excluía o
 * tempo de enfileiramento de até 200 linhas, e o enviesamento crescia
 * exactamente no regime em que o atraso real é maior. O achado é da revisão
 * adversarial (ANALISE-20, achado 7). `clock_timestamp()` é o instante real da
 * escrita.
 */
export const SQL_MARCAR_PUBLICADO = `
  UPDATE platform.events_outbox
     SET publicado_at = clock_timestamp()
   WHERE id = ANY($1)`;

/**
 * Recuo: mais uma tentativa e a próxima adiada.
 *
 * O atraso vem em milissegundos, calculado por `atrasoDaTentativa`. Corre numa
 * transacção **própria**, depois de a do lote ter revertido: se fosse na mesma,
 * o `ROLLBACK` que a falha obriga levava o recuo com ele e o laço repetia o
 * mesmo lote em ciclo apertado.
 */
export const SQL_RECUAR = `
  UPDATE platform.events_outbox
     SET tentativas = tentativas + 1,
         proxima_tentativa_at = now() + make_interval(secs => $2::double precision / 1000)
   WHERE id = ANY($1)`;

/**
 * Idade, em segundos, do evento pendente mais antigo.
 *
 * `criado_at` e não `proxima_tentativa_at`: o atraso que interessa é o que o
 * consumidor sente, e o recuo faz parte dele. Sem linhas pendentes dá 0 — e 0
 * é a resposta certa, não «sem dados».
 */
export const SQL_ATRASO = `
  SELECT COALESCE(EXTRACT(EPOCH FROM (now() - min(criado_at))), 0)::double precision AS atraso
    FROM platform.events_outbox
   WHERE publicado_at IS NULL`;

/** `LISTEN`/`NOTIFY` para acordar o laço sem esperar os 200 ms (§6.2). */
export const CANAL_DE_AVISO = "evt_novo";
export const SQL_ESCUTAR = "LISTEN evt_novo";

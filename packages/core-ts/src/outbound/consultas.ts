/**
 * O SQL da saída de canal (KAM-015).
 *
 * Em constantes e num módulo só, pela razão que o `chr/consultas.ts` do KAM-014
 * escreveu: a *suite* do gate 8 corre **estas** cadeias e não cópias delas, e
 * foi assim que o KAM-009 descobriu um `coalesce` em falta que uma cópia no
 * teste escondia.
 *
 * ## Três coisas que o SQL aqui faz e que vale a pena ver antes de as ler
 *
 * **A idempotência é da base.** O `SQL_ENFILEIRAR` é um
 * `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING`,
 * e o `RETURNING` vazio é o sinal de «esta chave já passou». Não há `SELECT`
 * antes do `INSERT`: entre o `SELECT` e o `INSERT` cabe outro processo, e o
 * critério 2 pede **uma** linha e **uma** chamada HTTP, não «quase sempre
 * uma». Com `ON CONFLICT`, quem perde a corrida sabe que perdeu.
 *
 * **A monotonia é da base também.** O `SQL_AVANCAR_ESTADO` tem o predicado da
 * ordem no próprio `UPDATE` (`WHERE ... AND state IN (...)`), e não lê para
 * decidir e escreve depois. A decisão em TypeScript (`estados.ts`) existe para
 * saber **se houve entrega** — que é o que decide o custo — e não para proteger
 * a ordem: dois `statuses` concorrentes da mesma mensagem chegam em dois
 * processos, e só a base os serializa.
 *
 * **O `ON CONFLICT` exige `SELECT` nas colunas de inferência.** É a lição que a
 * `0008` escreveu para o `SQL_QUARENTENA` e que a revisão `0010` paga ao
 * conceder `SELECT` de tabela: sem ele, o `INSERT` falha com `42501` e a
 * mensagem de erro não diz que o que falta é o `SELECT`.
 */

/**
 * A janela da conversa, para a decisão de envio.
 *
 * Lê de `conversations` e não de `contacts` — ver a nota de `decisao.ts` e a
 * emenda 1.20. A conversa é lida **pelo seu `id`** e com o `tenant_id` no
 * predicado: a RLS já o garante, e repeti-lo é o que torna a consulta correcta
 * mesmo que alguém a corra sem contexto (devolve zero linhas em vez da conversa
 * de outro).
 */
export const SQL_JANELA = `
  SELECT window_expires_at, mode
    FROM platform.conversations
   WHERE tenant_id = $1 AND id = $2
`;

/**
 * O template de um tenant, para a decisão.
 *
 * Pelo idioma exacto e não por prefixo: `pt_PT` e `pt_BR` são templates
 * diferentes com corpos diferentes, e um `LIKE 'pt%'` enviava um pelo outro.
 */
export const SQL_TEMPLATE = `
  SELECT name, lang, category, status, quality, bloqueado_em
    FROM platform.message_templates
   WHERE tenant_id = $1 AND name = $2 AND lang = $3
`;

/**
 * Enfileira um envio, e **não faz nada** se a chave já passou.
 *
 * O `RETURNING id` vazio é o sinal de repetição. O estado nasce em `queued` por
 * omissão da coluna, e é isso que torna a linha anterior à chamada HTTP: quem
 * repete a chave encontra a linha e não envia.
 */
export const SQL_ENFILEIRAR = `
  INSERT INTO platform.outbound_messages
         (tenant_id, channel_id, contact_id, conversation_id,
          idempotency_key, kind, template_name)
  VALUES ($1, $2, $3, $4, $5, $6, $7)
      ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
   RETURNING id
`;

/** A linha de um envio pela sua chave de idempotência. */
export const SQL_POR_CHAVE = `
  SELECT id, wamid, kind, state, pricing, error_code
    FROM platform.outbound_messages
   WHERE tenant_id = $1 AND idempotency_key = $2
`;

/**
 * Guarda o `wamid` que a Meta devolveu e passa a `sent`.
 *
 * `WHERE state = 'queued'` e não `WHERE id = $2` sozinho: se um `statuses`
 * chegou antes de esta escrita (a Meta é rápida e a ordem não é garantida), a
 * mensagem já está em `delivered` e este `UPDATE` **não a deve** fazer recuar.
 * É a monotonia aplicada ao próprio envio, e sem esta cláusula o critério 3
 * quebrava-se no caminho mais rápido em vez de no mais lento.
 */
export const SQL_MARCAR_ENVIADA = `
  UPDATE platform.outbound_messages
     SET wamid = $3, state = 'sent'
   WHERE tenant_id = $1 AND id = $2 AND state = 'queued'
   RETURNING state
`;

/** Marca uma falha, com o código da Meta. */
export const SQL_MARCAR_FALHADA = `
  UPDATE platform.outbound_messages
     SET state = 'failed', error_code = $3
   WHERE tenant_id = $1 AND id = $2 AND state NOT IN ('failed', 'suppressed_by_human')
   RETURNING state
`;

/**
 * Avança o estado de uma mensagem, e **devolve o estado que substituiu**.
 *
 * O `$4` é a lista dos estados de que se pode sair para o `$3`, e vem do
 * `estados.ts`: é o mesmo cálculo, mas aplicado pela base, que é quem serializa
 * dois `statuses` concorrentes. O `delivered_at` só se escreve quando o estado
 * novo o permite (`outbound_messages_entrega_ck`), e é o `CASE` que o garante
 * em vez de duas consultas.
 *
 * ## O `estado_antes`, e porque é que ele é o centro desta consulta
 *
 * **Quem decide o custo é a transição que de facto aconteceu, e só a base a
 * sabe.** A primeira versão desta consulta devolvia só o estado novo, e quem
 * chamava calculava o custo a partir de uma leitura feita **antes** — com dois
 * `statuses` concorrentes, os dois liam `sent`, os dois concluíam «houve
 * entrega» e os dois somavam 4 000. O guarda «zero linhas» não os apanhava,
 * porque ambos os `UPDATE` casavam: `delivered` aceita sair de `sent` e `read`
 * aceita sair de `sent` **e** de `delivered`.
 *
 * O par que o produz é exactamente o que a Meta produz: ela não garante ordem
 * nos `statuses` (`E1` §5), logo `delivered` e `read` chegam juntos a dois
 * processos. Oito mil micro-dólares para uma mensagem entregue uma vez, e o
 * `SQL_CUSTO_DO_TENANT` — que soma por linha — a dizer quatro mil. A
 * reconciliação em que o DoD «Custo e observabilidade» se apoia deixava de
 * fechar, e o painel mentia **por cima**.
 *
 * O `FOR UPDATE` da subconsulta é o que torna o `estado_antes` fiável: o
 * segundo processo **bloqueia** ali, e quando passa relê a versão comprometida
 * pelo primeiro. Não é uma leitura optimista com esperança — é a serialização
 * que o ADR-015 já exige para a RLS, usada aqui para o dinheiro.
 *
 * `RETURNING` vazio significa «não avançou», e continua a ser isso que o
 * chamador lê para não contar duas vezes um estado que não mexeu em nada.
 */
export const SQL_AVANCAR_ESTADO = `
  UPDATE platform.outbound_messages AS m
     SET state = $3,
         pricing = COALESCE($5::jsonb, m.pricing),
         delivered_at = CASE
             WHEN $3 IN ('delivered', 'read') THEN COALESCE(m.delivered_at, now())
             ELSE m.delivered_at
         END
    FROM (
      SELECT id, state
        FROM platform.outbound_messages
       WHERE tenant_id = $1 AND wamid = $2
         FOR UPDATE
    ) AS antes
   WHERE m.tenant_id = $1
     AND m.id = antes.id
     AND antes.state = ANY($4::text[])
   RETURNING m.id, antes.state AS estado_antes, m.state, m.kind
`;

/** A mensagem a que um `wamid` pertence. */
export const SQL_POR_WAMID = `
  SELECT id, state, kind, pricing
    FROM platform.outbound_messages
   WHERE tenant_id = $1 AND wamid = $2
`;

/**
 * Bloqueia um template recategorizado (critério 9).
 *
 * Escreve a `category` nova **e** o `bloqueado_em` na mesma instrução: separar
 * deixava uma janela em que o template está em `marketing` e não está
 * bloqueado, e é exactamente nessa janela que um envio passaria.
 *
 * `WHERE bloqueado_em IS NULL` torna-o idempotente — a Meta reenvia o webhook —
 * e preserva o **primeiro** instante de bloqueio, que é o que se audita.
 */
export const SQL_BLOQUEAR_TEMPLATE = `
  UPDATE platform.message_templates
     SET category = $4, bloqueado_em = now(), updated_at = now()
   WHERE tenant_id = $1 AND name = $2 AND lang = $3 AND bloqueado_em IS NULL
   RETURNING name, category, bloqueado_em
`;

/**
 * O estado de um template, vindo de um webhook.
 *
 * `updated_at = now()` sempre, mesmo quando o valor não muda: é o que diz «a
 * Meta confirmou isto agora», e um template cujo `updated_at` pare é um
 * template de que deixámos de ouvir falar.
 */
export const SQL_ESTADO_DO_TEMPLATE = `
  UPDATE platform.message_templates
     SET status = $4, updated_at = now()
   WHERE tenant_id = $1 AND name = $2 AND lang = $3
   RETURNING name, status
`;

/**
 * O custo acumulado de um tenant num período, em micro-dólares.
 *
 * **É esta consulta que substitui a etiqueta `{tenant}` da métrica**, e a razão
 * está no §3.14 e no DoD: as bibliotecas de métricas recusam por gramática uma
 * etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID
 * com hífenes — a chamada levanta. O `OBS-I` e o X-11 do gate 6 dizem porquê:
 * uma etiqueta é tão legível como uma linha de registo.
 *
 * O `docs/tecnica/01` §16 já aponta este caminho («custo monitorizado por
 * tenant e por mensagem | mecanismo: `pricing` dos *status*»), e é o único que
 * não re-identifica.
 *
 * Soma por categoria com os valores em micro-dólares **inteiros**, e o `CASE`
 * está no SQL em vez de em TypeScript porque somar aqui é somar uma vez; somar
 * lá era trazer todas as linhas do mês para memória.
 */
export const SQL_CUSTO_DO_TENANT = `
  SELECT COALESCE(SUM(CASE pricing->>'category'
             WHEN 'service'        THEN 4000
             WHEN 'utility'        THEN 4000
             WHEN 'authentication' THEN 4000
             WHEN 'marketing'      THEN 22500
             ELSE 0
         END), 0)::bigint AS micro_usd,
         count(*)::bigint AS entregues
    FROM platform.outbound_messages
   WHERE tenant_id = $1
     AND delivered_at >= $2
     AND delivered_at < $3
     AND pricing IS NOT NULL
     AND (pricing->>'billable')::boolean
`;

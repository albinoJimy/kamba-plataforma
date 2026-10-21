/**
 * O SQL da monitorização do *free tier* (KAM-023).
 *
 * Em constantes e num módulo só, pela razão que o `outbound/consultas.ts` do
 * KAM-015 e o `chr/consultas.ts` do KAM-014 escreveram: a *suite* do *gate* 8
 * corre **estas** cadeias e não cópias delas, e foi assim que o KAM-009
 * descobriu um `coalesce` em falta que uma cópia no teste escondia.
 *
 * ## Nenhuma destas consultas cria DDL, e isso é o ticket inteiro
 *
 * As duas colunas que aqui se escrevem — `free_tier_used` e `free_tier_month`
 * — nascem na revisão `0001` e já estão na lista de treze colunas do
 * `GRANT UPDATE` de `kamba_app`. Não há `ALTER TABLE` neste ticket para elas.
 * O que **falta** de DDL (`motivo_restricao` e `meta_error_codes_seen`, dos
 * critérios 5 e 6) está fora deste módulo e espera pela revisão `0013`, que
 * descende da `0012` do KAM-020.
 *
 * ## O mês é da base, e o fuso vive num sítio
 *
 * Todas as consultas que precisam de saber «que mês é este» chamam
 * `platform.ten_periodo(timestamptz)` da revisão `0007`, que é
 * `date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')::date` e é
 * `IMMUTABLE`. Não se reescreve em TypeScript, e a razão está no comentário
 * que a criou: «para que o fuso exista **num** sítio […] três cópias de
 * `'Africa/Luanda'` divergem no dia em que uma delas mudar». Há um teste em
 * `libs/py-core/tests/test_ten.py` que recusa o nome do fuso escrito no
 * código, e ele está certo.
 *
 * O `coalesce($n, now())` aparece em todas, e é a lição que o `SQL_PERIODO` do
 * KAM-009 pagou: a função tem `DEFAULT now()`, mas **um argumento nomeado
 * ausente não se exprime numa chamada posicional**. Passar `NULL` a secas
 * punha o período a `NULL`, e `NULL` não é um mês — é um buraco que cada lado
 * tapava à sua maneira.
 *
 * ## O mês sai em `to_char` e não como `date`, e isto foi medido
 *
 * As duas consultas que devolvem o mês fazem-no com
 * `to_char(..., 'YYYY-MM-DD')` em vez de deixarem sair uma `date`. Não é
 * estilo: é a correcção de um defeito que a bateria contra a base apanhou e que
 * nenhuma base falsa podia mostrar.
 *
 * O driver `pg` do Node **converte uma coluna `date` num `Date` de
 * JavaScript**, e fá-lo à meia-noite **local** do processo. A primeira versão
 * deste módulo recebia esse `Date` e fazia `toISOString().slice(0, 10)` — o que
 * está certo num contentor em UTC (onde o CI corre) e **errado por um dia** em
 * qualquer processo com fuso a oeste de Greenwich: `2026-11-01` às 00:00 locais
 * volta de `toISOString` como `2026-10-31`. Um contador de *free tier* que
 * reporte o mês errado na fronteira é precisamente o defeito que o critério 3
 * existe para impedir, e teria passado todos os ensaios da máquina do CI.
 *
 * Um `::text` resolvia-o em quase todos os casos, mas depende do `DateStyle` da
 * sessão, que é um GUC e pode vir de fora. O `to_char` com a máscara escrita
 * não depende de nada.
 *
 * ## Tudo parametrizado
 *
 * O módulo corre como `kamba_app`, sujeito à RLS, mas um processo de
 * retaguarda pode chamá-lo com outro papel; uma interpolação aqui lia os
 * contadores de todos os *tenants* no dia em que alguém a chamasse com o papel
 * errado. O `tenant_id` está no predicado **além** da RLS pela razão do
 * `SQL_JANELA` do KAM-015: a política já o garante, e repeti-lo é o que torna
 * a consulta correcta mesmo corrida sem contexto — devolve zero linhas em vez
 * do canal de outro.
 */

/**
 * Incrementa o contador de *service* entregues, reiniciando-o no mês novo.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o `phone_number_id`, `$3` o instante
 * (`NULL` para `now()`).
 *
 * ## O `FOR UPDATE` e o `antes`: é a lição do dinheiro do KAM-015
 *
 * A forma é a do `SQL_AVANCAR_ESTADO`, e não por simetria estética. A primeira
 * versão desta consulta era um `UPDATE ... RETURNING free_tier_used` simples, e
 * devolvia só o valor **depois**. Com isso, quem chamava não conseguia saber se
 * **este** incremento foi o que atravessou os 800 — tinha de ler antes e
 * comparar, e entre a leitura e a escrita cabe outro processo. Dois `statuses`
 * concorrentes liam 799, ambos escreviam 800 e 801, e ambos concluíam «eu
 * atravessei»: **dois avisos** para uma travessia, ou nenhum.
 *
 * Com a subconsulta `FOR UPDATE`, o segundo processo bloqueia e relê a versão
 * comprometida pelo primeiro. O `antes` que volta é o valor que **este**
 * `UPDATE` substituiu, e não um que alguém leu há um momento. É a mesma
 * serialização que o ADR-015 já exige para a RLS, usada aqui para o aviso.
 *
 * ## O reinício é `IS DISTINCT FROM`, e não `<>`
 *
 * O `free_tier_month` é anulável e é `NULL` no primeiro uso de um canal. Um
 * `<>` com `NULL` dá `NULL`, que num `CASE WHEN` não é verdadeiro — e o canal
 * nunca reiniciava, somando o primeiro mês ao nada. Com `IS DISTINCT FROM`, o
 * `NULL` conta como «diferente» e a primeira entrega do canal põe o contador a
 * `1` e o mês no sítio, que é o que se quer.
 *
 * O `CASE` põe `1` e não `0` no mês novo: **esta** entrega conta. Pôr `0` e
 * deixar o incremento para a próxima perdia uma mensagem por mês e por canal,
 * e um erro de uma em mil é exactamente o tamanho que a reconciliação de 2% do
 * critério 7 não distingue de ruído.
 */
export const SQL_CONTAR = `
  UPDATE platform.tenant_channels AS c
     SET free_tier_used = CASE
             WHEN antes.free_tier_month
                  IS DISTINCT FROM platform.ten_periodo(coalesce($3, now()))
             THEN 1
             ELSE antes.free_tier_used + 1
         END,
         free_tier_month = platform.ten_periodo(coalesce($3, now()))
    FROM (
      SELECT id, free_tier_used, free_tier_month
        FROM platform.tenant_channels
       WHERE tenant_id = $1 AND phone_number_id = $2
         FOR UPDATE
    ) AS antes
   WHERE c.tenant_id = $1
     AND c.id = antes.id
   RETURNING antes.free_tier_used AS usadas_antes,
             (antes.free_tier_month
              IS DISTINCT FROM platform.ten_periodo(coalesce($3, now()))) AS reiniciou,
             c.free_tier_used AS usadas,
             to_char(c.free_tier_month, 'YYYY-MM-DD') AS mes
`;

/**
 * Quantas *service* já foram entregues neste canal e **neste** mês.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o `phone_number_id`, `$3` o instante
 * (`NULL` para `now()`).
 *
 * É esta consulta que implementa a porta `EstadoDoFreeTier` que o KAM-015
 * declara e deixou a `null` à espera deste ticket.
 *
 * **O `CASE` do mês não é enfeite, é a correcção de um defeito que custaria
 * dinheiro a uma PME.** O contador é uma coluna e não se reinicia sozinho à
 * meia-noite: ninguém corre um processo mensal para o pôr a zero. Logo, no dia
 * 1 de um mês novo a coluna ainda tem o valor do mês anterior — 1.500, por
 * exemplo. Sem o `CASE`, o KAM-015 lia 1.500, concluía «acima do tecto» e
 * **contava custo** à primeira mensagem de um mês em que ela é grátis. O
 * `CASE` lê o mês guardado, compara-o com o período de agora, e devolve `0`
 * quando viraram — a leitura diz a verdade sem precisar de escrever nada.
 *
 * Zero linhas significa «canal que não existe, ou de outro *tenant*», e quem
 * lê trata-o como tal e não como um contador a zero: um canal desconhecido com
 * contador zero era dar *free tier* a quem não devia ter nenhum.
 */
export const SQL_ESTADO = `
  SELECT CASE
             WHEN c.free_tier_month
                  IS DISTINCT FROM platform.ten_periodo(coalesce($3, now()))
             THEN 0
             ELSE c.free_tier_used
         END AS usadas,
         to_char(platform.ten_periodo(coalesce($3, now())), 'YYYY-MM-DD') AS mes
    FROM platform.tenant_channels AS c
   WHERE c.tenant_id = $1 AND c.phone_number_id = $2
`;

/**
 * A taxa de falhas recentes de um canal (critério 5).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o `phone_number_id`, `$3` o tamanho da
 * janela.
 *
 * ## A janela só conta mensagens cujo destino já se sabe
 *
 * O filtro é `state IN ('delivered', 'read', 'failed')`, e a omissão é
 * deliberada: uma mensagem em `queued` ou `sent` **ainda não falhou nem foi
 * entregue**. Incluí-las diluía a taxa exactamente no momento em que ela
 * importa — uma rajada de 20 envios que a Meta vai recusar entra na janela
 * como 20 mensagens «sem falha» e faz a taxa parecer boa enquanto o canal está
 * a morrer. O `suppressed_by_human` também fica fora: é uma decisão nossa
 * (KAM-018), não um veredicto da Meta.
 *
 * ## A junção existe porque `outbound_messages` não tem `phone_number_id`
 *
 * O critério 1 conta «por `phone_number_id`», e é essa a chave de
 * `tenant_channels`. Mas `outbound_messages` guarda `channel_id` e não o
 * número (`0010`), pelo que a junção é obrigatória. É divergência entre o
 * critério e o DDL, está escrita na secção de verificação, e resolve-se aqui e
 * não no chamador — dar a esta função uma chave diferente da das outras duas
 * era obrigar quem a usa a ter as duas e a saber quando usa qual.
 *
 * A junção leva `tenant_id` nos **dois** lados, como todas as FK desde a
 * `0003`: sem isso uma mensagem do *tenant* A podia casar com um canal de B se
 * a RLS estivesse desligada, e o número que saía era a soma de dois canais.
 */
export const SQL_FALHAS_RECENTES = `
  SELECT count(*)::bigint AS total,
         count(*) FILTER (WHERE recentes.state = 'failed')::bigint AS falhas
    FROM (
      SELECT m.state
        FROM platform.outbound_messages AS m
        JOIN platform.tenant_channels AS c
          ON c.tenant_id = m.tenant_id AND c.id = m.channel_id
       WHERE m.tenant_id = $1
         AND c.phone_number_id = $2
         AND m.state IN ('delivered', 'read', 'failed')
       ORDER BY m.created_at DESC
       LIMIT $3
    ) AS recentes
`;

/**
 * O que o `pricing` diz ter sido entregue em *service* num período
 * (critério 7).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o `phone_number_id`, `$3` o instante
 * (`NULL` para `now()`).
 *
 * ## O período não entra por parâmetro, e a revisão adversarial é que o mostrou
 *
 * A primeira versão recebia `$3` e `$4` — início e fim do período — e tinha
 * **dois** defeitos que só se vêem a olhar para o conjunto:
 *
 * 1. **Comparava o contador de um mês com as entregas de outro.** O
 *    `free_tier_used` é **uma coluna**, não uma série: só sabe falar do mês
 *    corrente. Reconciliar Outubro já em Novembro lia um contador reposto a
 *    zero contra as mil e duzentas entregas de Outubro e devolvia 100% de
 *    divergência — num canal onde tudo estava certo. A API aceitava o pedido e
 *    respondia com um número sem significado.
 * 2. **As fronteiras do período vinham em UTC.** Um `delivered_at >= $3` com um
 *    `$3` à meia-noite de UTC perde a última hora do mês de `Africa/Luanda`
 *    (UTC+1) e ganha a primeira do seguinte. Numa reconciliação cujo limiar é
 *    **2%**, uma hora de tráfego é exactamente o tamanho do erro que ela não
 *    distingue de ruído — e era o mesmo defeito de fuso que o critério 3 existe
 *    para impedir, a entrar pela porta das traseiras.
 *
 * Os dois desaparecem com a mesma mudança: o período **não se exprime em
 * instantes**, exprime-se pela função. Uma mensagem pertence ao período quando
 * `ten_periodo(delivered_at)` é igual a `ten_periodo(agora)` — a mesma função
 * que decide o mês do contador, no mesmo fuso, pelo mesmo caminho. Não há
 * fronteira para errar, e não há como pedir um mês de que o contador não sabe
 * falar.
 *
 * O custo é um `ten_periodo` por linha em vez de um intervalo indexável. É
 * `IMMUTABLE`, e a alternativa — repetir `AT TIME ZONE 'Africa/Luanda'` aqui —
 * era a terceira cópia do fuso, que é precisamente o que a `0007` existe para
 * não haver.
 *
 * ## Conta linhas e não soma dinheiro, e a diferença é o ponto
 *
 * O critério 7 compara «o contador interno vs `pricing.billable` agregado», e
 * o contador interno é uma **contagem**. Somar micro-dólares aqui era
 * acrescentar uma segunda cópia do `CASE` de tarifas que o
 * `SQL_CUSTO_DO_TENANT` do KAM-015 já tem — e duas cópias de uma tabela de
 * preços divergem no trimestre em que uma mudar. Quem quer o dinheiro medido
 * chama aquela consulta; esta responde à pergunta do critério.
 *
 * `entregues` são as linhas com `pricing` de categoria *service* entregues no
 * período; `facturaveis` são as que a Meta marcou `billable`. As duas são
 * precisas: o nosso contador conta **todas** as *service* entregues (é o que
 * consome o *free tier*), e a Meta só factura as que estão acima dele. Com as
 * duas, a divergência pode atribuir-se — se `entregues` bate e `facturaveis`
 * não, o que divergiu foi a fronteira do *free tier* e não a contagem.
 *
 * **O `pricing.billable` não decide nada aqui, e é o próprio bloco do ticket
 * que o diz:** «é registado mas não se confia nele para decidir o *free tier*
 * até a reconciliação». Esta consulta é a reconciliação — o sítio onde ele é
 * medido em vez de obedecido.
 */
export const SQL_RECONCILIAR = `
  SELECT count(*)::bigint AS entregues,
         count(*) FILTER (
             WHERE (m.pricing->>'billable')::boolean
         )::bigint AS facturaveis
    FROM platform.outbound_messages AS m
    JOIN platform.tenant_channels AS c
      ON c.tenant_id = m.tenant_id AND c.id = m.channel_id
   WHERE m.tenant_id = $1
     AND c.phone_number_id = $2
     AND m.delivered_at IS NOT NULL
     AND platform.ten_periodo(m.delivered_at)
         = platform.ten_periodo(coalesce($3, now()))
     AND m.pricing IS NOT NULL
     AND (m.pricing->>'category') = 'service'
`;

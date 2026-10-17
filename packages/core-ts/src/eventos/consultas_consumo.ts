/**
 * O SQL do consumidor, num sítio só (KAM-006, `docs/tecnica/06` §6.3–§6.5).
 *
 * Separado do consumidor pela mesma razão que o `consultas.ts` do publicador:
 * para se poder ler o SQL sem ler o laço, e para as mutações do
 * `db/mutacoes.py` terem onde morder.
 *
 * **Tudo parametrizado.** O consumidor corre como `kamba_app`, sujeito à RLS;
 * o reconciliador corre como `kamba_batch`, que tem `BYPASSRLS` — e uma
 * injecção ali lia e re-enfileirava eventos de todos os tenants.
 */

/**
 * O contexto de tenant da transacção: o `app.tenant_id` que a RLS lê.
 *
 * **Sem isto o consumidor não escreve nada.** As três tabelas deste ticket têm
 * `ENABLE`, `FORCE` e a política `tenant_iso` (`db/rls.py`), e o consumidor
 * corre como `kamba_app`, que é `NOBYPASSRLS`: um `INSERT` em
 * `events_consumed` sem contexto não viola um privilégio — viola o `WITH
 * CHECK`, e a mensagem fala de *row-level security*, não de uma variável
 * esquecida. Era o defeito que a suite de integração apanhou à primeira
 * execução.
 *
 * O valor vem **do envelope** e não da fila: a fila trouxe um ponteiro, e quem
 * diz de quem é o evento é o arquivo. O `true` do terceiro argumento é o
 * `is_local` — o contexto morre com a transacção, e não fica agarrado a uma
 * ligação que serve dezasseis filas.
 */
export const SQL_DEFINIR_TENANT = `
  SELECT set_config('app.tenant_id', $1, $2)
`;

/**
 * Há uma transacção aberta nesta ligação?
 *
 * `now()` é o `transaction_timestamp()`. O PostgreSQL documenta que ele e o
 * `statement_timestamp()` são **iguais durante o primeiro comando de uma
 * transacção** e podem diferir nos seguintes. Em *autocommit*, cada instrução
 * é a primeira da sua transacção implícita, pelo que são sempre iguais; dentro
 * de uma transacção aberta que já correu alguma coisa, o segundo é maior.
 *
 * Serve uma guarda, e não uma decisão de negócio: o `once()` abre transacções
 * próprias, e o PostgreSQL **não tem transacções encadeadas** — um `BEGIN`
 * dentro de uma transacção aberta é um aviso e mais nada, e o `COMMIT`
 * seguinte fecha a transacção de fora. Chamar o `once()` de dentro do consumo
 * confirmava, assim, a marca de `events_consumed` antes de o efeito existir:
 * uma falha a seguir deixava o evento marcado como consumido e sem efeito,
 * para sempre, porque toda a re-entrega passa a ler «duplicado».
 *
 * **O que esta guarda não apanha:** o caso em que o `once()` é a *primeira*
 * instrução de uma transacção aberta, onde os dois instantes são iguais por
 * definição. No laço do consumo isso não acontece — o `SET LOCAL` e o `INSERT`
 * da marca correm antes —, e uma guarda que apanha o caso alcançável vale mais
 * do que nenhuma.
 */
export const SQL_TRANSACCAO_ABERTA = `
  SELECT now() <> statement_timestamp() AS aberta
`;

/**
 * A linha de deduplicação. **É esta consulta que torna a entrega
 * *at-least-once* num efeito exactamente-uma-vez.**
 *
 * `ON CONFLICT (consumer, event_id) DO NOTHING` devolve `rowCount = 0` quando a
 * linha já existe, e é esse zero que diz «duplicado». Corre na **mesma
 * transacção** que o efeito: se o efeito falhar, a linha desaparece com ele e a
 * re-entrega volta a tentar. Separar as duas transacções dava os dois modos de
 * falha de uma vez — efeito sem marca (repete-se) ou marca sem efeito (perde-se).
 *
 * **O alvo do conflito está nomeado**, e não é detalhe: com `DO NOTHING` sem
 * alvo, um conflito em *qualquer* índice único que a tabela venha a ter devolve
 * zero linhas, e esse zero lê-se «duplicado» — um efeito saltado em silêncio.
 * (Achado da revisão do espelho em Python.)
 */
export const SQL_MARCAR_CONSUMIDO = `
  INSERT INTO platform.events_consumed
    (consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq)
  VALUES ($1, $2, $3, $4, $5, $6)
  ON CONFLICT (consumer, event_id) DO NOTHING
`;

/**
 * O maior `seq` já consumido deste agregado, **excluindo** o evento em mão.
 *
 * O `event_id <> $4` é do §6.3 e não é decoração: a linha do evento em curso já
 * foi escrita acima, na mesma transacção, e sem a exclusão o máximo incluía-a —
 * um evento nunca estaria «atrasado» em relação a si mesmo e a verificação de
 * ordem não fazia nada.
 */
export const SQL_ULTIMO_SEQ = `
  SELECT max(agregado_seq) AS ultimo
    FROM platform.events_consumed
   WHERE consumer = $1 AND agregado_tipo = $2 AND agregado_id = $3 AND event_id <> $4
`;

/**
 * Abre uma entrada na DLQ: nova, ou **reaberta** se estava resolvida.
 *
 * `ON CONFLICT (consumer, event_id)`: a reentrada é idempotente por construção
 * (§6.4). Sem ela, um evento que falhasse em duas execuções abria duas entradas
 * e o alerta contava o dobro.
 *
 * **Mas uma unicidade sobre o par inteiro não servia**, e o caso é este: um
 * evento falha seis vezes e entra na DLQ; alguém reprocessa-o
 * (`estado = 'reprocessada'`); o reprocessamento volta a falhar seis vezes. A
 * segunda falha colidia com a linha **fechada**, não escrevia nada, e ficava
 * uma DLQ com zero entradas abertas sobre um efeito que continua por aplicar —
 * `evt_dlq_open` a zero, alerta nenhum, e a retenção de 30 dias a apagar a
 * única evidência. Num `payment.*`, um Sev1 que se apaga a si próprio.
 *
 * A resposta é a **unicidade parcial** (`events_dlq_aberta_uq`, só sobre as
 * abertas), e o alvo do conflito nomeia o seu predicado:
 * `ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING`. Duas
 * falhas na mesma execução continuam a dar uma entrada; um ciclo novo depois
 * de uma resolução abre a sua, com a anterior guardada — que é o que uma
 * auditoria quer ler.
 *
 * A alternativa — reabrir a linha fechada com um `DO UPDATE` — obrigava a dar
 * `UPDATE (estado, ...)` a `kamba_app`, e com isso quem consome passava a poder
 * **fechar** uma entrada sozinho. Era desfazer, do lado do código, a regra dos
 * dois aprovadores.
 *
 * **Sem `RETURNING`**, de propósito: `INSERT ... RETURNING` exige `SELECT` nas
 * colunas devolvidas, e `kamba_app` tem só `INSERT` — é o que mantém o `id`
 * sequencial fora do alcance de um papel sujeito a RLS (um tenant mediria pela
 * sequência quantas falhas o vizinho teve). A contagem de linhas basta, e um
 * `DO NOTHING` sobre um índice parcial não lê nada: nem `SELECT`, nem `UPDATE`.
 */
export const SQL_PARA_DLQ = `
  INSERT INTO platform.events_dlq
    (consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
  ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING
`;

/** As entradas abertas, por tipo: é o que a métrica `evt_dlq_open` expõe. */
export const SQL_DLQ_ABERTAS = `
  SELECT tipo, count(*) AS quantas,
         min(criado_at) AS mais_antiga
    FROM platform.events_dlq
   WHERE estado = 'aberta'
   GROUP BY tipo
`;

/** Uma entrada aberta, pelo seu `id`. Para o reprocessamento e o descarte. */
export const SQL_DLQ_POR_ID = `
  SELECT id, consumer, event_id, tipo, versao, tenant_id, envelope, erro,
         tentativas, estado, criado_at
    FROM platform.events_dlq
   WHERE id = $1
`;

/**
 * Fecha uma entrada da DLQ.
 *
 * O `WHERE estado = 'aberta'` é a trava: `rowCount = 0` significa «já estava
 * fechada», e o chamador não pode tratar isso como sucesso — reprocessar duas
 * vezes uma entrada já reprocessada aplicaria o efeito outra vez se a janela de
 * deduplicação já tivesse expirado.
 */
export const SQL_FECHAR_DLQ = `
  UPDATE platform.events_dlq
     SET estado = $2, resolvido_at = now(), resolvido_por = $3
   WHERE id = $1 AND estado = 'aberta'
`;

/** Registra uma aprovação de descarte. A chave primária recusa a repetida. */
export const SQL_APROVAR_DESCARTE = `
  INSERT INTO platform.evt_dlq_aprovacoes (dlq_id, aprovador)
  VALUES ($1, $2)
  ON CONFLICT DO NOTHING
`;

/** Quem já aprovou o descarte desta entrada, por ordem de chegada. */
export const SQL_APROVADORES = `
  SELECT aprovador FROM platform.evt_dlq_aprovacoes
   WHERE dlq_id = $1 ORDER BY criado_at, aprovador
`;

/**
 * Registra uma acção externa, ou diz que já está registada.
 *
 * `rowCount = 0` significa que outra execução já a registou: o chamador lê o
 * estado e decide. É o `once(key, fn)` do §6.3, e a chave é
 * `consumer:event_id:acção` — o mesmo valor que vai no `Idempotency-Key` do
 * pedido ao terceiro.
 *
 * **O alvo do conflito está nomeado**, pela razão do `SQL_MARCAR_CONSUMIDO`:
 * com `DO NOTHING` sem alvo, um conflito em qualquer índice único que a tabela
 * venha a ter devolve zero linhas, e esse zero lê-se «já está registada» — um
 * efeito externo saltado em silêncio.
 */
export const SQL_ABRIR_ACCAO = `
  INSERT INTO platform.evt_acoes
    (idempotency_key, consumer, event_id, accao, tenant_id)
  VALUES ($1, $2, $3, $4, $5)
  ON CONFLICT (idempotency_key) DO NOTHING
`;

/** O estado e o resultado de uma acção externa. */
export const SQL_LER_ACCAO = `
  SELECT estado, resultado FROM platform.evt_acoes WHERE idempotency_key = $1
`;

/** Fecha uma acção externa com o seu desfecho. */
export const SQL_FECHAR_ACCAO = `
  UPDATE platform.evt_acoes
     SET estado = $2, resultado = $3, concluido_at = now()
   WHERE idempotency_key = $1 AND estado = 'em_curso'
`;

/**
 * O que se perdeu: eventos arquivados que ninguém consumiu nem mandou para a
 * DLQ (`docs/tecnica/06` §6.5, **a consulta do documento**).
 *
 * Os dois intervalos são parâmetros e não literais, porque o teste do critério 8
 * tem de acelerar o relógio: com `interval '10 minutes'` escrito na consulta,
 * provar a reposição levava dez minutos de espera real por execução.
 *
 * O `envelope->'finalidades' ? s.finalidade` é o roteamento por finalidade
 * (§7.3): sem ele, o reconciliador re-enfileirava para consumidores que **nunca
 * deviam ter recebido** o evento — e a reposição passava a ser uma fuga de
 * finalidade.
 */
export const SQL_A_REPOR = `
  SELECT l.event_id, l.tipo, l.tenant_id, l.agregado_id, s.consumer
    FROM platform.events_log l
    JOIN platform.evt_subscricoes s ON s.tipo = l.tipo AND s.activo
    LEFT JOIN platform.events_consumed c
           ON c.consumer = s.consumer AND c.event_id = l.event_id
    LEFT JOIN platform.events_dlq d
           ON d.consumer = s.consumer AND d.event_id = l.event_id
   WHERE l.ocorrido_em > now() - make_interval(secs => $1)
     AND l.registado_em < now() - make_interval(secs => $2)
     AND l.envelope->'finalidades' ? s.finalidade
     AND c.event_id IS NULL AND d.event_id IS NULL
   ORDER BY l.ocorrido_em
   LIMIT $3
`;

/**
 * As subscrições activas de `payment.*` sem ordem.
 *
 * O critério 7 pede que **o arranque falhe** se houver alguma. A restrição
 * `evt_subscricoes_payment_exige_ordem` da revisão 0005 faz a configuração ser
 * recusada pela base; esta consulta é a outra metade, e continua a valer se
 * alguém largar a restrição.
 */
export const SQL_PAYMENT_SEM_ORDEM = `
  SELECT consumer, tipo FROM platform.evt_subscricoes
   WHERE tipo LIKE 'payment.%' AND NOT exige_ordem
   ORDER BY consumer, tipo
`;

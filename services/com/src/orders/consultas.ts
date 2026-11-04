/**
 * As cadeias SQL do módulo `orders`, confrontadas contra PostgreSQL pelo gate 8.
 *
 * Não são uma cópia de nada: a suite `db/tests_encomendas/` lê estas constantes
 * **deste ficheiro** e corre-as contra a base, como o `db/tests_produtos/` e o
 * `db/tests_servicos/` fazem com as dos seus módulos. A razão está escrita no
 * `db/tests_produtos/consultas.py`: uma cópia prova que a cópia funciona, e a
 * revisão adversarial do KAM-009 descobriu SQL de biblioteca que nunca corria
 * contra base nenhuma.
 *
 * ## O `$1` é o `tenant_id` e não o `id`, e o §6.2 escreve o contrário
 *
 * O §6.2 dá o CAS como `UPDATE … WHERE id=$1 AND version=$2 AND estado=$de`. Aqui
 * é `WHERE tenant_id = $1 AND id = $2 AND version = $3 AND estado = $4`, e a
 * diferença é a numeração e não o predicado: as três colunas que o §6.2 compara
 * estão todas lá, e o que entra à frente é o filtro de tenant que o repo-base do
 * KAM-042 **exige** imediatamente depois do primeiro `WHERE` — sem ele a
 * consulta não chega à base (`com_repo_filtro_em_falta_total`). A alternativa era
 * reescrever o CAS como CTE para satisfazer um verificador, que é deixar a
 * ferramenta decidir a forma do SQL.
 *
 * O filtro de tenant é **redundante com a RLS** e está lá de propósito: a RLS é
 * a segunda barreira (§5.5), e o RR-01 de `seguranca/riscos_residuais.md` diz
 * que ela «protege de um `WHERE` esquecido, não de código que escolha o tenant
 * errado».
 *
 * ## O CAS **não** usa `FOR UPDATE`, e isso é a escolha
 *
 * O `produtos` lê com `FOR UPDATE` antes de escrever, porque a idempotência dele
 * é uma comparação do «antes» com o pedido. Aqui a prova é outra: o §6.2 manda
 * «falha de CAS ⇒ reler e reavaliar (nunca forçar)», e é o `UPDATE … WHERE
 * version = $3` que faz disso uma propriedade — vinte transacções concorrentes
 * sobre a mesma versão escrevem uma linha e dezanove escrevem zero, sem nenhuma
 * esperar pela outra. Com `FOR UPDATE` as dezanove **esperavam**, liam a versão
 * nova e tinham de reavaliar de qualquer forma, com a serialização a custar
 * dezanove trancas. Medido no gate 8 (`test_concorrencia`).
 */

/**
 * Lê a encomenda para decidir a transição. **Sem tranca**, pela nota acima.
 *
 * O `deleted_at IS NULL` está no predicado e não na aplicação: uma encomenda
 * sob *soft delete* (§5.6) não transita, e deixar isso ao chamador era deixá-lo
 * esquecer-se.
 */
export const SQL_LER = `
  SELECT id, numero_publico, estado, version, total_minor, currency,
         contact_id, origem, entrega_modo, expira_at, paga_at, paga_via,
         entregue_at, entrega_confirmada_por, confirmacao_dono, lines_snapshot
    FROM platform.orders_mirror
   WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
`;

/**
 * O CAS do §6.2: muda o estado **se** a versão e o estado de partida baterem.
 *
 * `RETURNING *` no §6.2; aqui devolve as colunas que o chamador precisa de ler,
 * que é o mesmo conjunto do `SQL_LER` — um `*` obrigava quem lê a conhecer a
 * ordem das colunas da tabela, e a revisão `0030` acrescenta-lhe colunas.
 *
 * Os campos derivados do estado entram todos na mesma instrução, e não num
 * `UPDATE` a seguir: `paga_at`/`paga_via` para `paga`, `entregue_at` e
 * `entrega_confirmada_por` para `entregue`, `expira_at` para quem o fixa. Um
 * segundo `UPDATE` seria uma segunda transição do ponto de vista do *trigger* —
 * e o `BEFORE UPDATE` exige que a `version` suba de um em cada mudança de
 * estado, pelo que o segundo passava sem mudar estado e deixava a linha do
 * registo a descrever metade do que aconteceu.
 *
 * **Cada `$n` aparece uma só vez**, e não é estilo: o `ConsultaDoTypeScript` que
 * a suite do gate 8 usa para correr esta cadeia recusa um marcador repetido —
 * não há equivalente posicional para o mesmo argumento usado duas vezes no
 * `pg8000`. Por isso os derivados não são `CASE WHEN $5 = 'paga' THEN …`: quem
 * decide o que cada estado escreve é o `transition.ts`, que passa `null` nas
 * colunas que não mexe, e o `COALESCE` preserva o que lá estava. O que impede
 * um chamador distraído de levar a encomenda a `paga` sem via é o
 * `orders_mirror_paga_exige_via_ck`, na coluna, e não a forma desta cadeia.
 */
export const SQL_TRANSITAR = `
  UPDATE platform.orders_mirror
     SET estado = $5,
         version = version + 1,
         atualizado_at = now(),
         paga_at = COALESCE($6::timestamptz, paga_at),
         paga_via = COALESCE($7, paga_via),
         entregue_at = COALESCE($8::timestamptz, entregue_at),
         entrega_confirmada_por = COALESCE($9, entrega_confirmada_por),
         expira_at = COALESCE($10::timestamptz, expira_at)
   WHERE tenant_id = $1 AND id = $2 AND version = $3 AND estado = $4
     AND deleted_at IS NULL
  RETURNING id, numero_publico, estado, version, total_minor, currency,
            expira_at, paga_via, entrega_confirmada_por
`;

/**
 * ## Os três `INSERT` **não** estão aqui, e a razão é o repo-base
 *
 * A linha de `order_state_log`, o espelho novo e a divergência aberta entram por
 * `repo.inserirNoTenant`, que **constrói** o `INSERT` com a coluna do filtro —
 * «não há como o esquecer», diz o `repo-base/index.ts`, e é a barreira que o
 * KAM-042 desenhou: um `INSERT` escrito à mão aceita o `tenant_id` de quem o
 * escreve, e o `noTenant` recusa-o por não ter `WHERE` nenhum.
 *
 * O `numero_publico` não aparece em insersão nenhuma por uma segunda razão da
 * mesma família: é `DEFAULT platform.order_numero_publico()` na coluna
 * (revisão `0030`), pelo que **todo** o caminho de inserção recebe um número
 * válido — incluindo o repo-base, que não aceita expressões em `valores`.
 */

/**
 * O grafo, lido da base. **A base é a fonte**, não uma lista em TypeScript.
 *
 * Não tem filtro de tenant porque a tabela não tem `tenant_id`: as transições
 * válidas de um sistema não são configuração de tenant. Por isso **não** entra
 * pelo repo-base — entra pela porta estreita das chamadas de função, como o
 * `evt_emitir`.
 */
export const SQL_GRAFO = `
  SELECT de, para, flag
    FROM platform.order_state_graph
   ORDER BY de, para
`;

/**
 * Fecha uma divergência. A métrica é «abertas > 5 min = 0», logo o que conta é
 * esta passagem.
 */
export const SQL_FECHAR_DIVERGENCIA = `
  UPDATE platform.order_reconciliation_issues
     SET estado = 'resolvida', resolvida_at = now()
   WHERE tenant_id = $1 AND id = $2 AND estado = 'aberta'
  RETURNING id
`;

/**
 * As divergências abertas de um tenant, as mais antigas primeiro.
 *
 * É a consulta da métrica do bloco, e o índice
 * `order_reconciliation_issues_abertas_idx` existe para ela.
 */
export const SQL_DIVERGENCIAS_ABERTAS = `
  SELECT id, order_id, tipo, detalhe, aberta_at
    FROM platform.order_reconciliation_issues
   WHERE tenant_id = $1 AND estado = 'aberta'
   ORDER BY aberta_at
`;

/**
 * Emite um evento pelo outbox. O envelope **constrói-se em SQL**.
 *
 * `platform.evt_emitir`, como em todos os produtores deste repositório: não há
 * construtor de envelope em TypeScript, de propósito, para não haver duas
 * fontes para a mesma forma (KAM-005, ADR-009). A emissão corre **na transacção
 * de quem chama** — a transição e o evento entram ou não entram juntos, que é o
 * que faz do outbox um outbox.
 *
 * É a mesma cadeia que o `produtos/consultas.ts` e o `servicos/consultas.ts`
 * usam, com os mesmos oito argumentos e os mesmos *casts*.
 */
export const SQL_EMITIR = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb, $7, $8::text[]
  ) AS event_id
`;

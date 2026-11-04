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

// ------------------------------------------- KAM-046: o recibo de intenção

/*
 * As oito cadeias abaixo são a *saga* de `createOrder` do §6.3 e o fluxo de
 * confirmação do dono do critério 7. O `INSERT` do recibo **não** está aqui,
 * pela razão de sempre: entra por `repo.inserirNoTenant`, com o
 * `ON CONFLICT (tenant_id, intent_key) DO NOTHING RETURNING` no `sufixo` — e é
 * esse `ON CONFLICT` que serializa as cinquenta concorrentes do critério 3.
 *
 * **Porque é que o `DO NOTHING` basta, e o que ele faz que uma leitura não
 * faz:** com `ON CONFLICT DO NOTHING` o PostgreSQL **espera** pela transacção
 * que inseriu a linha em conflito e só depois decide — salta se ela confirmou,
 * insere se ela abortou. Logo quem perde a corrida só lê o recibo **depois** de
 * o vencedor ter confirmado a saga inteira, e o que lê é o estado final com o
 * `order_id`. Um `SELECT` antes do `INSERT` não tem essa propriedade: as
 * cinquenta liam zero linhas ao mesmo tempo e as cinquenta inseriam.
 */

/**
 * O recibo de uma ou mais chaves do anel (§6.3, passo 2).
 *
 * **`= ANY($2)` e não um `IN` por marcador**, porque as chaves são uma ou duas
 * conforme o segredo já tenha rodado — ver o `chavesDoAnel` do `intents.ts`. Com
 * um marcador por chave, o texto desta cadeia mudava com o estado do cofre, e
 * então não havia cadeia nenhuma para o *gate* 8 confrontar.
 *
 * A ordem é a do `criado_at` **descendente**: com as duas versões do anel a
 * acertar (o que só acontece a rodar), vale o recibo mais recente.
 */
export const SQL_LER_INTENCAO = `
  SELECT tenant_id, intent_key, draft_hash, estado, order_id, criado_at
    FROM platform.order_intents
   WHERE tenant_id = $1 AND intent_key = ANY($2::text[])
   ORDER BY criado_at DESC
`;

/**
 * Fecha o recibo: `concluida` com a encomenda (§6.3, passo 3).
 *
 * `WHERE estado = 'em_curso'` e não um `UPDATE` incondicional: o
 * `order_intents_concluida_exige_encomenda_ck` exige os dois lados ao mesmo
 * tempo, e um recibo que já esteja `concluida` com **outra** encomenda é uma
 * saga que correu duas vezes — o que se quer é que a segunda não escreva, não
 * que ela sobreponha. Zero linhas é a resposta, e quem chama relê.
 */
export const SQL_CONCLUIR_INTENCAO = `
  UPDATE platform.order_intents
     SET estado = 'concluida', order_id = $3
   WHERE tenant_id = $1 AND intent_key = $2 AND estado = 'em_curso'
  RETURNING intent_key, estado, order_id
`;

/**
 * Marca `falhada` uma intenção `em_curso` abandonada (critério 5).
 *
 * «Intenção `em_curso` > 2 min é retomada ou marcada `falhada`», e são **duas**
 * instruções e não uma: esta fecha a abandonada, e o `SQL_RETOMAR_INTENCAO`
 * reabre-a. Cada uma tem o estado esperado no predicado, pelo que de N
 * concorrentes passa **uma** — a retoma por leitura-e-escrita deixava passar
 * todas, que é a lição que o `idempotency.py` da TLS escreveu para a mesma
 * tabela do outro lado.
 *
 * O instante entra como argumento e não é `now() - interval`, para que o ensaio
 * possa pôr a fronteira numa igualdade exacta em vez de dormir dois minutos.
 *
 * **O `criado_at` não se reescreve, e isso tem uma consequência que custou um
 * achado de revisão adversarial.** O `UPDATE_DA_APP_EM_INTENCOES` da revisão
 * `0030` dá ao `kamba_app` duas colunas — `estado` e `order_id` — e o instante
 * da criação de um recibo não é de quem o retoma. Logo um recibo retomado
 * continua a parecer velho, e o predicado desta instrução é o estado **e a
 * idade**: um segundo chamador que chegue enquanto a saga retomada corre
 * **volta a falhá-la** e retoma-a por cima de uma viva.
 *
 * A primeira versão desta nota dizia que isso era «inofensivo, porque o
 * predicado é o estado, não a idade». Era falso nas duas metades: o predicado
 * tem a idade, e a consequência não é inofensiva — duas sagas escrevem o
 * espelho, e a segunda bate na `orders_mirror_intent_uq`.
 *
 * **O que fecha isto não é esta cadeia: é o `catch` do `23505` na fase 2** do
 * `create_order.ts`, que relê a encomenda que o vencedor escreveu e devolve-a
 * como repetição. A encomenda continua a ser **uma** — era sempre, pela
 * unicidade —, e o que mudou foi a forma com que o travão chega a quem perde:
 * uma resposta e não uma excepção. Uma guarda por idade a sério pedia uma coluna
 * que esta revisão não tem, e dar-lha é alterar a `0030`.
 */
export const SQL_FALHAR_INTENCAO = `
  UPDATE platform.order_intents
     SET estado = 'falhada'
   WHERE tenant_id = $1 AND intent_key = $2 AND estado = 'em_curso'
     AND criado_at < $3
  RETURNING intent_key, criado_at
`;

/** Reabre um recibo `falhada`. A segunda metade do critério 5. */
export const SQL_RETOMAR_INTENCAO = `
  UPDATE platform.order_intents
     SET estado = 'em_curso'
   WHERE tenant_id = $1 AND intent_key = $2 AND estado = 'falhada'
  RETURNING intent_key, estado
`;

/**
 * O «já tem o pedido K7H3Q9 por pagar» do critério 8.
 *
 * Três filtros que são o critério à letra — **mesmo contacto**, **mesmo
 * `draft_hash`**, **não paga** — mais a janela de 30 minutos, que entra como
 * argumento (`$4`) pela razão do `SQL_COTACAO_VALIDA` do `produtos`: para que a
 * fronteira se escreva como igualdade em vez de se dormir.
 *
 * **«Não paga» são os três estados antes do dinheiro** e não `estado <> 'paga'`:
 * uma encomenda `cancelada` ou `expirada` não é um pedido por pagar, e dizer ao
 * cliente que tem um pedido que já caducou era pior do que não dizer nada. Os
 * três são `criada`, `aguarda_pagamento` e `pendente_confirmacao`, que é o
 * caminho do §6.2 até ao `paga`.
 *
 * O `$5` exclui o recibo da própria chamada: na repetição de um toque, o recibo
 * desta intenção já está `concluida` e apontaria para a encomenda que acabámos
 * de devolver — o que dizia ao cliente que tem por pagar o pedido que ele está a
 * fazer agora.
 *
 * **Isto nunca bloqueia**, e é a segunda metade do critério: a resposta é um
 * *facto* para o agente perguntar, e quem decide é o cliente.
 */
export const SQL_PEDIDO_POR_PAGAR = `
  SELECT m.id, m.numero_publico, m.estado, m.total_minor, m.currency,
         m.criado_at
    FROM platform.order_intents i
    JOIN platform.orders_mirror m
      ON m.tenant_id = i.tenant_id AND m.id = i.order_id
   WHERE i.tenant_id = $1
     AND i.draft_hash = $2
     AND i.estado = 'concluida'
     AND i.intent_key <> $5
     AND m.contact_id = $3
     AND m.criado_at > $4
     AND m.estado IN ('criada', 'aguarda_pagamento', 'pendente_confirmacao')
     AND m.deleted_at IS NULL
   ORDER BY m.criado_at DESC
   LIMIT 1
`;

/**
 * Põe (ou tira) o pedido de confirmação ao dono. Critério 7.
 *
 * **Um CAS pelo subestado esperado (`$4`) e não um `UPDATE` cego**, e é o que
 * torna «sim do dono» idempotente: dois cliques no mesmo botão dão uma escrita e
 * uma releitura. Os cinco subestados são o `orders_mirror_confirmacao_ck` da
 * revisão `0030`.
 *
 * **Não muda o `estado`**, e é a letra do critério: o item `confirmar_dono`
 * deixa a encomenda `criada`. Por isso esta instrução não dispara o *trigger*
 * diferido `order_estado_exige_log` (ele devolve `NULL` quando o estado não
 * muda) nem o `order_transicao_valida` (que só consulta o grafo numa mudança de
 * estado), e **não** há linha de `order_state_log` a escrever — o que é certo,
 * porque aquela tabela tem `CHECK (de <> para)` e aqui não há `de`.
 *
 * O `criada` no predicado é a barreira contra pedir confirmação a uma encomenda
 * que já passou: uma encomenda em `aguarda_pagamento` tem referência emitida, e
 * pôr-lhe `confirmacao_dono='pendente'` era pedir ao dono que confirmasse o que
 * o cliente já está a pagar.
 */
export const SQL_CONFIRMACAO_DO_DONO = `
  UPDATE platform.orders_mirror
     SET confirmacao_dono = $3,
         atualizado_at = now()
   WHERE tenant_id = $1 AND id = $2 AND confirmacao_dono = $4
     AND estado = 'criada' AND deleted_at IS NULL
  RETURNING id, numero_publico, estado, confirmacao_dono, version
`;

/**
 * Relê o subestado da confirmação, para distinguir as três razões de zero linhas.
 *
 * Existe **como constante e não como cadeia dentro da função** pela razão que
 * este ficheiro inteiro tem: o que o *gate* 8 confronta contra PostgreSQL é o
 * texto que o módulo envia, e um SQL escrito na função que o usa nunca é lido
 * pela suite — o `TestCoberturaDasConsultas` do `test_outbox.py` procura por
 * `export const SQL_… = ` e um literal escondido passava por entre ele. Foi
 * assim que o `SQL_GRELHA` do KAM-047 chegou com um defeito que nenhuma bateria
 * tocava.
 *
 * **Sem o `estado = 'criada'`** que o `SQL_CONFIRMACAO_DO_DONO` tem: é
 * precisamente essa a diferença que esta leitura serve para medir — se a linha
 * existe e o `UPDATE` não a apanhou, ou o subestado não batia ou a encomenda já
 * saiu de `criada`.
 */
export const SQL_LER_CONFIRMACAO = `
  SELECT confirmacao_dono, estado, version
    FROM platform.orders_mirror
   WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
`;

/**
 * A encomenda de uma `intent_key`. É a releitura que fecha a corrida perdida.
 *
 * **Existe por causa de um achado da revisão adversarial**, e vale escrever a
 * cadeia de razões porque ela liga três coisas que pareciam separadas.
 *
 * O `UPDATE_DA_APP_EM_INTENCOES` da revisão `0030` dá ao `kamba_app` **duas**
 * colunas — `estado` e `order_id` — e o `criado_at` não é uma delas. Logo um
 * recibo retomado continua a parecer velho, e um segundo chamador pode
 * falhá-lo e retomá-lo **por cima de uma saga viva**: dois a correr, dois a
 * escrever o espelho. Quem os separa é o `orders_mirror_intent_uq`, que é a
 * «segunda barreira independente» que o Contexto do bloco nomeia — mas ela
 * chega como `23505`, isto é, como **excepção** e fora do `Resultado` que a
 * operação promete. Numa operação de classe `money` isso é um 500 em vez da
 * encomenda que já existe.
 *
 * Com esta leitura, o `23505` deixa de ser uma avaria e passa a ser a resposta
 * certa: quem perdeu a corrida relê a encomenda que o vencedor escreveu e
 * devolve-a como repetição. É a mesma forma que o `upsertProductDraft` do
 * KAM-043 usou para o SKU novo — zero linhas, relê, segue — com a diferença de
 * que aqui o sinal vem do erro e não da contagem.
 */
export const SQL_ENCOMENDA_DA_CHAVE = `
  SELECT id, numero_publico, estado, version, total_minor, currency,
         confirmacao_dono, lines_snapshot
    FROM platform.orders_mirror
   WHERE tenant_id = $1 AND intent_key = $2 AND deleted_at IS NULL
`;

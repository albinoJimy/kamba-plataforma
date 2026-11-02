/**
 * O SQL do módulo `produtos`, por extenso (KAM-043).
 *
 * Num ficheiro só, pela razão do `servicos/consultas.ts` e do
 * `ten/consultas.ts`: o texto que o módulo envia é o que o *gate* 8 exercita
 * contra um PostgreSQL verdadeiro, e um SQL escrito dentro da função que o usa
 * nunca é confrontado como texto. A suite `db/tests_produtos/` **lê estas
 * constantes deste ficheiro** — não é uma cópia —, pelo que alterar uma aqui
 * muda o que o gate corre. A lição é do KAM-009: o `SQL_PERIODO` tinha um
 * defeito real que nenhum teste tocava, porque o SQL das bibliotecas nunca
 * corria contra uma base.
 *
 * ## Todas levam `tenant_id = $1`, e o `servicos` não leva. Porquê
 *
 * O `servicos/consultas.ts` escreve, por extenso, que nenhuma consulta leva
 * `tenant_id` no `WHERE` e que isso é deliberado: «a RLS é que o põe lá; um
 * `WHERE tenant_id = $1` escrito à mão ao lado da política criava uma segunda
 * fonte para a mesma regra». Aqui é o contrário, e não é incoerência — é a
 * fronteira a que cada módulo pertence.
 *
 * Estas consultas entram na base pelo **repo-base** do KAM-042
 * (`repo.noTenant`), porque o `getOfferView`, o `upsertProductDraft` e o
 * `publishProduct` são métodos da porta `CommerceRegistry` e o critério 4 daquele
 * ticket exige que nenhuma consulta saia sem o filtro. O repo-base **recusa** uma
 * consulta que não contenha `tenant_id = $1` depois do primeiro `WHERE`, com o
 * contador de recusas a disparar. Logo o predicado não é uma segunda fonte da
 * política: é o que a barreira de cima exige para deixar a consulta passar, e a
 * RLS continua a ser a segunda. O `$1` é sempre o tenant, e é o repo-base que o
 * passa — ver `repoBase().noTenant`, que faz `query(sql, [tenantId, ...resto])`.
 *
 * ## Nenhuma repete um `$n`, e isso é uma regra e não um estilo
 *
 * A suite do *gate* 8 converte `$n` em `%s` para o `pg8000`, que é **posicional
 * pela ordem de aparição**. O `ConsultaDoTypeScript` do `db/tests/base.py`
 * guarda a ordem dos marcadores e **reordena** os argumentos, pelo que uma
 * consulta cujos `$n` não apareçam por ordem crescente — como um `UPDATE`, onde
 * o `SET` vem antes do `WHERE` e o `tenant_id = $1` que o repo-base exige fica
 * no fim — é exercitada correctamente. Não é por acaso que essa classe existe:
 * nasceu de o PostgreSQL ter recusado um `'feita'` onde esperava `jsonb`.
 *
 * O que ela **não** sabe fazer é um `$n` repetido: não há equivalente
 * posicional para o mesmo argumento usado duas vezes, e o `args()` recusa-o. É
 * por isso que o `SQL_PESQUISAR` passa o termo em `$2` **e** em `$3` em vez de
 * repetir `$2` — o operador `%` e o `similarity()` querem o mesmo texto, e a
 * consulta pede-o duas vezes em vez de o reutilizar.
 *
 * ## O `INSERT` não está aqui, e não é esquecimento
 *
 * O repo-base não **verifica** um `INSERT`: constrói-o (`inserirNoTenant`), com
 * a coluna do filtro escrita por ele e não procurada no texto de quem chama. É a
 * regra 5 daquele ficheiro, e nasceu de uma medição: o `INSERT` legítimo era
 * recusado pela verificação por texto, e a saída de menor resistência era pôr o
 * predicado num comentário. Por isso o que escreve em `offer_terms` e em
 * `price_quotes` passa pelo `inserirNoTenant`, com o `sufixo` a levar o
 * `ON CONFLICT`, e o que existe aqui são as leituras e os `UPDATE`.
 */

/**
 * Os termos de uma oferta, para o `getOfferView` e para o caminho de escrita.
 *
 * `FOR UPDATE` **não** está aqui: esta consulta serve a leitura. Quem escreve
 * usa o `SQL_TERMOS_PARA_ESCRITA`, e a separação é deliberada — um `FOR UPDATE`
 * na leitura do agente punha uma tranca de linha em cada `getOfferView`, que é a
 * operação mais chamada do módulo.
 *
 * O `deleted_at IS NULL` é o soft delete do §5.6: uma oferta apagada não se lê.
 */
export const SQL_TERMOS = `
  SELECT sku, nome, preco_tipo, preco_minor, currency,
         preco_atualizado_at, preco_valido_ate,
         stock_modo, stock_verificado_at, estado, categoria_restrita,
         atualizado_at
    FROM platform.offer_terms
   WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL
`;

/**
 * O mesmo, com a linha trancada, para o caminho de escrita.
 *
 * **O `FOR UPDATE` é o que torna a idempotência do critério 5 verdadeira sob
 * concorrência.** O ajuste de preço e de stock lê o valor anterior, compara, e
 * só escreve, audita e emite se mudou. Com duas transacções a fazer isso ao
 * mesmo tempo e sem tranca, as duas leem o mesmo «antes», as duas concluem que
 * mudou, e saem **dois** eventos para uma alteração — que é exactamente o que o
 * DoD proíbe («ajustes de stock repetidos não duplicam efeitos nem eventos»).
 */
export const SQL_TERMOS_PARA_ESCRITA = `
  SELECT sku, nome, preco_tipo, preco_minor, currency,
         preco_atualizado_at, preco_valido_ate,
         stock_modo, stock_verificado_at, estado, categoria_restrita,
         atualizado_at
    FROM platform.offer_terms
   WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL
     FOR UPDATE
`;

/**
 * Actualiza os termos de uma oferta já existente. **Nunca toca no `estado`.**
 *
 * É o `upsertProductDraft` a apanhar uma linha que já existe, e a coluna
 * `estado` fica de fora da lista de propósito: o critério 4 diz que o
 * `upsertProductDraft` **nunca publica**, e a forma mais forte de o garantir não
 * é verificar o estado antes de escrever — é não ter a coluna na instrução. Um
 * produto publicado cujos termos mudam continua publicado; um rascunho continua
 * rascunho. Quem muda o estado é o `SQL_PUBLICAR`, e mais nada.
 *
 * O `atualizado_at` é escrito aqui e não por *trigger* — ver a nota da revisão
 * `0028`.
 */
export const SQL_ACTUALIZAR_TERMOS = `
  UPDATE platform.offer_terms
     SET nome = $3,
         preco_tipo = $4,
         preco_minor = $5,
         preco_valido_ate = $6,
         stock_modo = $7,
         preco_atualizado_at = now(),
         atualizado_at = now()
   WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL
  RETURNING sku, preco_tipo, preco_minor, currency, stock_modo, atualizado_at
`;

/**
 * Publica uma oferta. O predicado é a barreira, e não uma verificação anterior.
 *
 * Três condições no `WHERE`, e as três são o critério 4:
 *
 *   `categoria_restrita IS NULL`   um produto com categoria restrita **não
 *                                  publica** — e é a base que o recusa, não um
 *                                  `if` que alguém pode esquecer de escrever no
 *                                  próximo chamador;
 *   `estado <> 'arquivado'`        arquivar é terminal; republicar um arquivado
 *                                  era ressuscitar uma oferta que alguém
 *                                  retirou;
 *   `deleted_at IS NULL`           o soft delete do §5.6.
 *
 * Zero linhas afectadas é a resposta, e o módulo distingue as razões lendo a
 * linha depois — porque «não existe», «tem categoria restrita» e «está
 * arquivado» são recusas diferentes para quem opera.
 *
 * **A `OwnerConfirmation` não está no predicado**, e tem de ficar dito: ela é
 * verificada no módulo, antes desta instrução, porque não há coluna onde vive. A
 * `offer_terms` do §5.4 não tem onde guardar a confirmação do dono, e inventar-lhe
 * uma era escopo de outro ticket — o fluxo conversacional de `confirmar_dono` é
 * o KAM-046. O que fica provado por máquina é que uma publicação **sem**
 * confirmação válida falha; o que não fica é o rasto dela na tabela, e a linha de
 * `audit_log` é que o guarda.
 */
export const SQL_PUBLICAR = `
  UPDATE platform.offer_terms
     SET estado = 'publicado',
         atualizado_at = now()
   WHERE tenant_id = $1 AND sku = $2
     AND categoria_restrita IS NULL
     AND estado <> 'arquivado'
     AND deleted_at IS NULL
  RETURNING sku, estado, atualizado_at
`;

/**
 * Renova o `stock_verificado_at` de um SKU. É o ajuste de stock do critério 5.
 *
 * **Não há coluna de quantidade em `offer_terms`, e isso não é omissão desta
 * revisão.** O §5.4 põe o stock no Registo (`commerce.stock_levels` na opção C,
 * o módulo de inventário do Medusa na B) e dá a esta tabela o **modo** e o
 * instante da última conferência, que é o que governa o que o agente pode dizer.
 * O número de unidades é do Registo, e o Registo da opção B não existe em
 * `infra/compose/` — o KAM-042 registou-o. Logo o que este `UPDATE` escreve é o
 * que esta tabela tem: o modo e o instante.
 *
 * A quantidade do ajuste atravessa o módulo e sai no payload do
 * `stock.adjusted`, que é quem a leva ao DAT, e é por isso que um ajuste é
 * auditável e emitido sem haver coluna para ele.
 */
export const SQL_AJUSTAR_STOCK = `
  UPDATE platform.offer_terms
     SET stock_modo = $3,
         stock_verificado_at = now(),
         atualizado_at = now()
   WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL
  RETURNING sku, stock_modo, stock_verificado_at, atualizado_at
`;

/**
 * A pesquisa lexical mínima do critério 8. **Descartável**, e dito onde está.
 *
 * `similarity()` do `pg_trgm` e não `LIKE`: o critério pede pesquisa lexical, e
 * um `LIKE 'x%'` não encontra «sabão» a partir de «sabao» nem «arroz 5 kg» a
 * partir de «5kg arroz». O `%` é o operador de semelhança de trigramas, que usa
 * o índice `offer_terms_nome_trgm_idx` da revisão `0028`; o `similarity()` no
 * `ORDER BY` ordena, e o `LIMIT` é o tecto de cinco do critério.
 *
 * Só o que está **publicado**, porque um rascunho não se oferece a um cliente, e
 * só do tenant — pelo `tenant_id = $1` que o repo-base exige e pela RLS atrás.
 *
 * **Não devolve preço**, e é a parte que importa: o §6.2 do `docs/tecnica/02`
 * diz que o `search_catalog` «devolve candidatos (sku, nome) **sem preço no
 * ranking**», e quem quer o preço chama o `getOfferView`, que o formata com o
 * modo. Uma pesquisa que devolvesse `preco_minor` dava ao agente um número sem
 * modo ao lado — que é precisamente o que o validador de citação (KAM-032) existe
 * para apanhar.
 *
 * Isto sai no KAM-061 (`idx.candidatos`), e o contrato da porta não a expõe.
 */
export const SQL_PESQUISAR = `
  SELECT sku, nome
    FROM platform.offer_terms
   WHERE tenant_id = $1
     AND estado = 'publicado'
     AND deleted_at IS NULL
     AND nome % $2
   ORDER BY similarity(nome, $3) DESC, nome
   LIMIT $4
`;

/**
 * A cotação válida de um `(sku, qty)`, ou nada (critério 6).
 *
 * **A expiração é por `valida_ate` e não pelo `estado`**: uma cotação vencida
 * não espera por varrimento para deixar de valer, e um estado só muda quando
 * alguém o muda. Por isso o predicado compara o instante — e compara-o com um
 * argumento (`$4`) e não com `now()`, para que o teste do critério 6 possa pôr a
 * fronteira numa igualdade exacta em vez de dormir.
 *
 * `qty` exacto e não `>=`: uma cotação é para uma quantidade, porque o
 * `preco_total_minor` é o total da linha e o desconto de quantidade é a razão de
 * existir a cotação. Dez unidades cotadas não dizem nada sobre três.
 *
 * A mais recente primeiro: se o dono cotou duas vezes, vale a última.
 */
export const SQL_COTACAO_VALIDA = `
  SELECT id, sku, qty, preco_total_minor, currency, valida_ate, estado
    FROM platform.price_quotes
   WHERE tenant_id = $1
     AND sku = $2
     AND qty = $3
     AND estado = 'emitida'
     AND valida_ate > $4
   ORDER BY criado_at DESC
   LIMIT 1
`;

/** Marca uma cotação como aceite. O único `UPDATE` que o `kamba_app` pode. */
export const SQL_ACEITAR_COTACAO = `
  UPDATE platform.price_quotes
     SET estado = 'aceite'
   WHERE tenant_id = $1 AND id = $2 AND estado = 'emitida'
  RETURNING id, estado
`;

/**
 * Escreve uma linha de auditoria pela porta documentada do KAM-012.
 *
 * `platform.audit_append`, e não um `INSERT` directo: a função é «a porta
 * documentada» daquele ticket, e o `criado_at`, o `prev_hash` e o `row_hash` são
 * escritos pelo *trigger* `audit_encadear` e **não** por quem insere — sem isso,
 * quem tem `INSERT` forja uma linha correctamente encadeada com a data que
 * quiser.
 *
 * Não devolve nada, de propósito: um `RETURNING` lê, e dar `SELECT` no
 * `row_hash` a quem escreve abria uma excepção ao critério 9 do KAM-012.
 *
 * **Este módulo é o primeiro chamador em produção.** O KAM-012 registou, em
 * `specs/tickets/KAM-012.md` e em `docs/auditoria.md`, que «nada chama
 * `audit_append` em produção»; passa a chamar. O `kamba_app` tem `EXECUTE` nela
 * e **não** tem `SELECT` em `audit_log`, que é a assimetria desenhada.
 *
 * **Corre em `READ COMMITTED`**, que é a omissão do PostgreSQL. O
 * `audit_append` serializa a cadeia por tenant, e sob `REPEATABLE READ` duas
 * escritas concorrentes dão `40001` e a segunda perde-se. Nenhuma operação deste
 * módulo muda o nível de isolamento.
 *
 * O `sha256()` é da base e não do Node: o `payload_hash` tem de ter 32 bytes
 * (`audit_log_hashes_sha256`), e calcular o SHA em JavaScript obrigava a passar
 * um `bytea` pela fronteira do driver para obter exactamente o mesmo valor que a
 * base calcula sozinha a partir do texto.
 */
export const SQL_AUDITAR = `
  SELECT platform.audit_append(
    $1::uuid, $2, $3, $4, $5, $6, $7, sha256($8::bytea)
  )
`;

/**
 * Emite um evento pelo outbox. O envelope **constrói-se em SQL**.
 *
 * `platform.evt_emitir`, como em todos os produtores deste repositório: não há
 * construtor de envelope em TypeScript, de propósito, para não haver duas fontes
 * para a mesma forma (KAM-005, ADR-009). A emissão corre **na transacção de quem
 * chama** — a escrita e o evento entram ou não entram juntos, que é o que faz do
 * outbox um outbox e não um segundo sistema a precisar de reconciliação.
 *
 * É a mesma cadeia que o `servicos/consultas.ts` usa, com os mesmos oito
 * argumentos e os mesmos *casts*.
 */
export const SQL_EMITIR = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb, $7, $8::text[]
  ) AS event_id
`;

/** `23514`: violação de `CHECK`. É o `offer_terms_preco_ck` do critério 1. */
export const SQLSTATE_CHECK = "23514";

/** `23503`: violação de chave estrangeira. É a FK composta do contacto. */
export const SQLSTATE_FK = "23503";

/** `23505`: violação de unicidade. É a chave `(tenant_id, sku)`. */
export const SQLSTATE_UNICIDADE = "23505";

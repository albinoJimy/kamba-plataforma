/**
 * As consultas do MED (KAM-020).
 *
 * Uma por instrução e cada uma com o seu nome, pela razão que o KAM-013
 * escreveu: uma consulta com nome aparece num `grep`, e uma consulta construída
 * por concatenação não aparece em nenhum.
 *
 * **Nenhuma destas consultas escreve um URL da Meta**, e isso não é disciplina:
 * não há coluna onde ele caiba (critério 3). O que se guarda é o `media_id`,
 * que é um identificador, e o `storage_ref`, que é a chave do **nosso** objecto.
 */

/**
 * Reserva a linha antes da descarga, em `pendente`.
 *
 * **`RETURNING` vazio significa «já existe», e é a idempotência do critério 2.**
 * É esta instrução que a torna uma propriedade da base: «a mesma
 * `(tenant_id, wamid, media_id)` processada 3× produz 1 objecto e 1 linha» não
 * depende de o código verificar primeiro, depende de a `media_assets_origem_uq`
 * existir.
 *
 * **E é por isso que a linha se escreve ANTES da descarga.** Os três valores da
 * chave vêm todos da mensagem, pelo que são conhecidos sem falar com a Meta: o
 * segundo chamador perde o conflito e **não descarrega**. É o contrário do
 * `ensureAccount` do HND, que precisava de identificadores que só a criação no
 * provedor devolve e por isso deixa recurso órfão numa corrida. Aqui não há
 * órfão possível — o que pode sobrar é uma linha em `pendente`, que é nossa e
 * que a purga do KAM-071 vê.
 */
export const SQL_RESERVAR = `
  INSERT INTO platform.media_assets
         (tenant_id, contact_id, conversation_id, wamid, media_id, classe, estado)
  VALUES ($1, $2, $3, $4, $5, $6, 'pendente')
      ON CONFLICT (tenant_id, wamid, media_id) DO NOTHING
   RETURNING asset_id
`;

/** A linha de uma origem, para quando a reserva perdeu o conflito. */
export const SQL_POR_ORIGEM = `
  SELECT asset_id, estado, classe, storage_ref, sha256
    FROM platform.media_assets
   WHERE tenant_id = $1 AND wamid = $2 AND media_id = $3
`;

/** A linha de um `asset_id`, que é por onde o `signUrl` entra. */
export const SQL_POR_ASSET = `
  SELECT asset_id, estado, classe, storage_ref, sha256
    FROM platform.media_assets
   WHERE tenant_id = $1 AND asset_id = $2
`;

/**
 * Marca a linha como armazenada, com o que a descarga descobriu.
 *
 * As quatro colunas vêm todas da descarga e do `put`, e não da mensagem: o
 * `content_type` **real** (não o anunciado), o tamanho, o resumo e a chave.
 *
 * **O `WHERE estado = 'pendente'` é a monotonia no predicado**, e é a lição da
 * `0010` e do HND: sem ele, uma segunda passagem sobre a mesma linha
 * reescrevia um `armazenado` já feito — ou, pior, ressuscitava um `rejeitado`.
 * Zero linhas aqui significa «outro já tratou isto», e quem chama tem de saber
 * distingui-lo de um erro.
 */
export const SQL_MARCAR_ARMAZENADO = `
  UPDATE platform.media_assets
     SET estado = 'armazenado',
         content_type = $3,
         size = $4,
         sha256 = $5,
         storage_ref = $6,
         retain_until = $7
   WHERE tenant_id = $1 AND asset_id = $2
     AND estado = 'pendente'
   RETURNING asset_id, estado
`;

/**
 * Marca a linha como rejeitada ou falhada.
 *
 * Uma instrução para os dois, e o estado vem por parâmetro — ao contrário do
 * `SQL_MARCAR_ARMAZENADO`, que o tem embutido. A diferença é que o `armazenado`
 * escreve **seis** colunas que só ele tem, e estes dois não escrevem nenhuma:
 * uma rejeição e uma falha não têm `content_type` real, nem tamanho, nem
 * resumo, nem chave. Juntá-los numa instrução com seis parâmetros nulos tornava
 * impossível ler o que cada caminho faz.
 *
 * O domínio é imposto pela base (`media_assets_estado_ck`), pelo que um valor
 * inventado aqui não passa.
 */
export const SQL_MARCAR_DESFECHO = `
  UPDATE platform.media_assets
     SET estado = $3
   WHERE tenant_id = $1 AND asset_id = $2
     AND estado = 'pendente'
   RETURNING asset_id, estado
`;

/**
 * Os objectos cujo prazo de retenção passou, por *tenant*.
 *
 * **Esta consulta não é usada por este ticket**, e fica aqui porque é a forma
 * que a coluna `retain_until` existe para servir. A purga é KAM-071 e corre
 * como `kamba_batch` (que tem `BYPASSRLS`), pelo que a consulta dele não leva
 * `tenant_id` e não usa esta. O que esta serve é o painel de uma PME a
 * perguntar «o que é que está prestes a desaparecer», e é por isso que leva o
 * *tenant* e usa o índice `(tenant_id, criado_at DESC)`.
 */
export const SQL_FORA_DA_RETENCAO = `
  SELECT asset_id, estado, classe, storage_ref, sha256
    FROM platform.media_assets
   WHERE tenant_id = $1
     AND retain_until IS NOT NULL
     AND retain_until < now()
     AND estado = 'armazenado'
   ORDER BY criado_at DESC
`;

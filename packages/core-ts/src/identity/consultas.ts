/**
 * Todo o SQL do módulo de identidade, num sítio só (KAM-008).
 *
 * Três regras, e as três são verificadas por teste:
 *
 * 1. **Só parâmetros ligados.** Nenhuma instrução se constrói por concatenação,
 *    e nenhum parâmetro leva um BSUID ou um telefone em claro: o que vai para a
 *    base é HMAC e cifra. Com `log_statement = 'all'` no servidor, o registo do
 *    PostgreSQL continua sem um único identificador em claro.
 * 2. **`tenant_id` em todas as instruções sobre tabelas de tenant.** A RLS já
 *    filtra; o predicado explícito é a primeira barreira e é o que usa o índice.
 * 3. **Nada fora das quatro tabelas da revisão `0003`.** O papel `kamba_identity`
 *    não lê tenants, canais nem entitlements, e este ficheiro não lho pede.
 */

const VERSOES_VIVAS =
  "SELECT kid, estado FROM platform.hmac_key_versions WHERE estado IN ('actual', 'anterior')";

/**
 * As versões de chave que a pesquisa tenta: a actual e a anterior.
 *
 * `FOR SHARE`: quem resolve um contacto segura as versões até ao fim da sua
 * transacção, e uma rotação (`KIDS_VIVOS_TRANCADOS`) espera por ele. Sem isto,
 * um pedido que já tinha lido «a actual é k1» escrevia sob k1 depois de outro,
 * a seguir à rotação, ter criado o mesmo contacto sob k2 — e os índices únicos,
 * que levam a versão, não davam por nada: o mesmo BSUID com dois contactos,
 * para sempre (achado 1 da revisão adversarial, `ANALISE-08`).
 */
export const KIDS_VIVOS = `${VERSOES_VIVAS} FOR SHARE`;

/** As mesmas, trancadas: quem inicia ou conclui uma rotação não corre em paralelo. */
export const KIDS_VIVOS_TRANCADOS = `${VERSOES_VIVAS} ORDER BY kid FOR UPDATE`;

/** O estado de uma versão, segura até ao fim da transacção (como `KIDS_VIVOS`). */
export const ESTADO_DO_KID =
  "SELECT estado FROM platform.hmac_key_versions WHERE kid = $1 FOR SHARE";

export const DESPROMOVER_ACTUAL =
  "UPDATE platform.hmac_key_versions SET estado = 'anterior' WHERE estado = 'actual'";

export const REGISTAR_ACTUAL =
  "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES ($1, 'actual')";

export const RETIRAR_ANTERIOR =
  "UPDATE platform.hmac_key_versions SET estado = 'retirada' " +
  "WHERE estado = 'anterior' RETURNING kid";

/**
 * O endpoint de um BSUID, pelo HMAC sob a chave actual **ou** sob a anterior.
 *
 * `$4` e `$5` são nulos quando não há versão anterior: `hmac_kid = NULL` não é
 * verdadeiro para linha nenhuma, e a segunda metade do `OR` cai.
 */
export const ENDPOINT_POR_BSUID =
  "SELECT id, contact_id, hmac_kid FROM platform.contact_endpoints " +
  "WHERE tenant_id = $1 AND tipo = 'bsuid' " +
  "AND ((hmac_kid = $2 AND bsuid_hmac = $3) OR (hmac_kid = $4 AND bsuid_hmac = $5))";

/** O contacto de um telefone, pelo HMAC sob a chave actual ou sob a anterior. */
export const CONTACTO_POR_TELEFONE =
  "SELECT contact_id, hmac_kid FROM platform.contacts " +
  "WHERE tenant_id = $1 AND phone_hmac IS NOT NULL " +
  "AND ((hmac_kid = $2 AND phone_hmac = $3) OR (hmac_kid = $4 AND phone_hmac = $5))";

/**
 * Tranca os contactos em que a operação vai mexer, por ordem de `contact_id`.
 *
 * A ordem fixa é o que impede o abraço mortal entre duas fusões que envolvam os
 * mesmos dois contactos. O que se lê **depois** de trancar é o que vale: entre a
 * pesquisa e a tranca, outro pedido pode ter apagado ou fundido o contacto.
 */
export const TRANCAR_CONTACTOS =
  "SELECT contact_id, criado_at, erased_at, merged_into, phone_hmac, hmac_kid " +
  "FROM platform.contacts WHERE tenant_id = $1 AND contact_id = ANY($2::uuid[]) " +
  "ORDER BY contact_id FOR UPDATE";

export const TEM_BSUID =
  "SELECT 1 AS tem FROM platform.contact_endpoints " +
  "WHERE tenant_id = $1 AND contact_id = $2 AND tipo = 'bsuid' LIMIT 1";

export const CRIAR_CONTACTO =
  "INSERT INTO platform.contacts (tenant_id, phone_hmac, hmac_kid) " +
  "VALUES ($1, $2, $3) RETURNING contact_id, criado_at";

export const DEFINIR_TELEFONE =
  "UPDATE platform.contacts SET phone_hmac = $3, hmac_kid = $4 " +
  "WHERE tenant_id = $1 AND contact_id = $2";

export const LIMPAR_TELEFONE =
  "UPDATE platform.contacts SET phone_hmac = NULL, hmac_kid = NULL " +
  "WHERE tenant_id = $1 AND contact_id = $2";

/** A DEK viva mais antiga do contacto: é com ela que se cifra o que for novo. */
export const DEK_VIVA =
  "SELECT dek_id, wrapped_dek, kek_id FROM platform.contact_deks " +
  "WHERE tenant_id = $1 AND contact_id = $2 AND destroyed_at IS NULL " +
  "ORDER BY criado_at, dek_id LIMIT 1";

export const CRIAR_DEK =
  "INSERT INTO platform.contact_deks (dek_id, tenant_id, contact_id, wrapped_dek, kek_id) " +
  "VALUES ($1, $2, $3, $4, $5)";

export const CRIAR_ENDPOINT_BSUID =
  "INSERT INTO platform.contact_endpoints " +
  "(tenant_id, contact_id, tipo, bsuid_hmac, hmac_kid, bsuid_enc, dek_id) " +
  "VALUES ($1, $2, 'bsuid', $3, $4, $5, $6)";

export const ACTUALIZAR_HMAC_DO_BSUID =
  "UPDATE platform.contact_endpoints SET bsuid_hmac = $3, hmac_kid = $4 " +
  "WHERE tenant_id = $1 AND id = $2";

/**
 * Guarda (ou renova) o telefone cifrado de um contacto, para uma finalidade.
 *
 * Um por contacto e por finalidade (`contact_endpoints_telefone_uq`): guardar
 * outra vez renova a cifra e o prazo, não acumula cópias do mesmo número.
 */
export const GUARDAR_TELEFONE =
  "INSERT INTO platform.contact_endpoints " +
  "(tenant_id, contact_id, tipo, phone_enc, dek_id, finalidade, expira_at) " +
  "VALUES ($1, $2, 'telefone', $3, $4, $5, $6) " +
  "ON CONFLICT (tenant_id, contact_id, finalidade) WHERE tipo = 'telefone' " +
  "DO UPDATE SET phone_enc = EXCLUDED.phone_enc, dek_id = EXCLUDED.dek_id, " +
  "expira_at = EXCLUDED.expira_at, recolhido_at = now()";

export const APAGAR_TELEFONES =
  "DELETE FROM platform.contact_endpoints " +
  "WHERE tenant_id = $1 AND contact_id = $2 AND tipo = 'telefone'";

export const MOVER_ENDPOINTS =
  "UPDATE platform.contact_endpoints SET contact_id = $3 " +
  "WHERE tenant_id = $1 AND contact_id = $2";

export const MOVER_DEKS =
  "UPDATE platform.contact_deks SET contact_id = $3 " +
  "WHERE tenant_id = $1 AND contact_id = $2";

/** A lápide: o contacto absorvido fica a apontar para quem o absorveu. */
export const MARCAR_FUNDIDO =
  "UPDATE platform.contacts SET phone_hmac = NULL, hmac_kid = NULL, " +
  "merged_into = $3, merged_at = now() WHERE tenant_id = $1 AND contact_id = $2 " +
  "RETURNING merged_at";

export const CONTACTO =
  "SELECT contact_id, criado_at, erased_at, merged_into FROM platform.contacts " +
  "WHERE tenant_id = $1 AND contact_id = $2";

export const APAGAR_ENDPOINTS =
  "DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2";

/** *Crypto-shredding*: o embrulho desaparece, e fica a data em que desapareceu. */
export const DESTRUIR_DEKS =
  "UPDATE platform.contact_deks SET wrapped_dek = NULL, destroyed_at = now() " +
  "WHERE tenant_id = $1 AND contact_id = $2 AND destroyed_at IS NULL";

export const MARCAR_APAGADO =
  "UPDATE platform.contacts SET phone_hmac = NULL, hmac_kid = NULL, erased_at = now() " +
  "WHERE tenant_id = $1 AND contact_id = $2 RETURNING erased_at";

/**
 * Os endpoints **dentro do prazo**. Um telefone cujo `expira_at` já passou não
 * se serve, mesmo que a purga (KAM-071) ainda não o tenha apagado.
 */
export const ENDPOINTS_DO_CONTACTO =
  "SELECT e.id, e.tipo, e.bsuid_enc, e.phone_enc, e.finalidade, e.expira_at, " +
  "e.dek_id, d.wrapped_dek, d.kek_id " +
  "FROM platform.contact_endpoints e " +
  "JOIN platform.contact_deks d ON d.tenant_id = e.tenant_id AND d.dek_id = e.dek_id " +
  "WHERE e.tenant_id = $1 AND e.contact_id = $2 " +
  "AND (e.expira_at IS NULL OR e.expira_at > now()) " +
  "ORDER BY e.recolhido_at, e.id";

/** Um lote de endpoints de BSUID cujo HMAC ainda não está sob a chave nova. */
export const BSUID_POR_RODAR =
  "SELECT e.id, e.bsuid_enc, e.dek_id, d.wrapped_dek, d.kek_id " +
  "FROM platform.contact_endpoints e " +
  "JOIN platform.contact_deks d ON d.tenant_id = e.tenant_id AND d.dek_id = e.dek_id " +
  "WHERE e.tenant_id = $1 AND e.tipo = 'bsuid' AND e.hmac_kid <> $2 " +
  "ORDER BY e.id LIMIT $3 FOR UPDATE OF e";

/** Um lote de contactos cujo HMAC de telefone ainda não está sob a chave nova. */
export const TELEFONES_POR_RODAR =
  "SELECT contact_id FROM platform.contacts " +
  "WHERE tenant_id = $1 AND phone_hmac IS NOT NULL AND hmac_kid <> $2 " +
  "AND contact_id > $4 ORDER BY contact_id LIMIT $3 FOR UPDATE";

/** A cifra mais recente do telefone de um contacto, se houver alguma legível. */
export const CIFRA_DO_TELEFONE =
  "SELECT e.phone_enc, e.dek_id, d.wrapped_dek, d.kek_id " +
  "FROM platform.contact_endpoints e " +
  "JOIN platform.contact_deks d ON d.tenant_id = e.tenant_id AND d.dek_id = e.dek_id " +
  "WHERE e.tenant_id = $1 AND e.contact_id = $2 AND e.tipo = 'telefone' " +
  "AND d.destroyed_at IS NULL ORDER BY e.recolhido_at DESC, e.id LIMIT 1";

export const CONTAR_POR_RODAR =
  "SELECT " +
  "(SELECT count(*) FROM platform.contact_endpoints " +
  "  WHERE tenant_id = $1 AND tipo = 'bsuid' AND hmac_kid <> $2)::int AS bsuids, " +
  "(SELECT count(*) FROM platform.contacts " +
  "  WHERE tenant_id = $1 AND phone_hmac IS NOT NULL AND hmac_kid <> $2)::int AS telefones";

/** Todas as instruções, para o teste que confere as três regras do cabeçalho. */
export const TODAS: Readonly<Record<string, string>> = {
  KIDS_VIVOS,
  KIDS_VIVOS_TRANCADOS,
  ESTADO_DO_KID,
  DESPROMOVER_ACTUAL,
  REGISTAR_ACTUAL,
  RETIRAR_ANTERIOR,
  ENDPOINT_POR_BSUID,
  CONTACTO_POR_TELEFONE,
  TRANCAR_CONTACTOS,
  TEM_BSUID,
  CRIAR_CONTACTO,
  DEFINIR_TELEFONE,
  LIMPAR_TELEFONE,
  DEK_VIVA,
  CRIAR_DEK,
  CRIAR_ENDPOINT_BSUID,
  ACTUALIZAR_HMAC_DO_BSUID,
  GUARDAR_TELEFONE,
  APAGAR_TELEFONES,
  MOVER_ENDPOINTS,
  MOVER_DEKS,
  MARCAR_FUNDIDO,
  CONTACTO,
  APAGAR_ENDPOINTS,
  DESTRUIR_DEKS,
  MARCAR_APAGADO,
  ENDPOINTS_DO_CONTACTO,
  BSUID_POR_RODAR,
  TELEFONES_POR_RODAR,
  CIFRA_DO_TELEFONE,
  CONTAR_POR_RODAR,
};

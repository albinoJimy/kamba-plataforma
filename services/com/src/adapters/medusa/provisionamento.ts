/**
 * Provisionamento de um tenant no Registo da opção B (KAM-042, critério 5).
 *
 * «Cada tenant tem canal de vendas e localização de stock próprios (segunda
 * barreira) e `tenants.medusa_sales_channel_id`/`medusa_merchant_id`
 * preenchidos por comando de provisioning (na Fase 0, por *script*; o evento
 * `tenant.activated` é KAM-092).»
 *
 * **Segunda barreira, nunca a primeira.** O canal e a localização por tenant
 * são reforço: foi medido no KAM-041 (ISO-11..18) que o canal limita o que uma
 * chave publicável vê e **não substitui** o filtro `merchant_id`, e que o
 * *query graph* não aplica filtro nenhum (ISO-27..32). Quem isola é o
 * repo-base. Isto reduz o raio de um erro, não cria isolamento.
 *
 * ## Um tenant por chamada, e com o papel estreito
 *
 * O comando provisiona **um** tenant, com o contexto desse tenant, pelo papel
 * `kamba_app` — que tem `UPDATE (medusa_sales_channel_id, medusa_merchant_id)`
 * em `platform.tenants` desde a revisão `0001` e não precisa de mais nada. Quem
 * decide *quais* tenants provisionar atravessa tenants, e isso é de retaguarda
 * (`kamba_batch`, `comBatch` com nome de *job*) — fica fora deste ficheiro de
 * propósito, porque a lista de candidatos é do *script* da Fase 0 e depois do
 * KAM-092.
 *
 * ## O lado do Medusa é uma porta, e isso é uma afirmação sobre o que falta
 *
 * O `RegistoAdmin` abaixo é uma **porta**, não um cliente HTTP. A implementação
 * contra a Admin API do Medusa **não está escrita**, e a razão não é
 * conveniência:
 *
 *   1. a opção B é a recomendação do KAM-041 e não está ratificada (D3);
 *   2. não há Medusa em `infra/compose/` — só a base `kamba_medusa` que o
 *      `initdb` cria —, pelo que um cliente HTTP escrito aqui não teria contra
 *      o que correr, e um cliente não exercitado é *proposta* com cara de
 *      código;
 *   3. as rotas da Admin API que criariam o canal, a localização e o
 *      `merchant` não foram lidas em fonte primária nesta sessão. Escrevê-las
 *      de memória era inventar, que é o primeiro dos doze princípios.
 *
 * O que **está** escrito e provado é a parte que é nossa e que não muda com a
 * opção: a ordem das três criações, a idempotência, e a escrita em
 * `platform.tenants` com o `UPDATE` que só preenche o que está vazio.
 */

import { eUuid } from "../../port/contrato.ts";
import type { ClienteSql, ComTenant } from "../../port/contrato.ts";
import { MerchantEmFaltaError, SQL_MERCHANT_DO_TENANT } from "../../repo-base/index.ts";

/**
 * O que o Registo tem de saber criar, por tenant.
 *
 * As três operações são **idempotentes por `tenantId`**: chamadas duas vezes
 * devolvem o mesmo id. É exigência e não esperança — um provisionamento que
 * corra a meio e seja repetido não pode deixar dois canais para o mesmo tenant,
 * porque o segundo canal é stock que ninguém vê.
 */
export interface RegistoAdmin {
  /** O `merchant` do módulo custom (§3.3). Idempotente por `tenantId`. */
  criarMerchant(tenantId: string, nome: string): Promise<string>;
  /** O Sales Channel do tenant. Idempotente por `tenantId`. */
  criarSalesChannel(tenantId: string, nome: string): Promise<string>;
  /** A Stock Location do tenant. Idempotente por `tenantId`. */
  criarStockLocation(tenantId: string, nome: string): Promise<string>;
  /** Liga as três ao `merchant` por *link* do Medusa. */
  ligar(
    merchantId: string,
    salesChannelId: string,
    stockLocationId: string,
  ): Promise<void>;
}

/** O resultado de um provisionamento. */
export interface Provisionamento {
  readonly tenantId: string;
  readonly merchantId: string;
  readonly salesChannelId: string;
  readonly stockLocationId: string;
  /** `false` quando este tenant já estava provisionado e nada foi criado. */
  readonly criou: boolean;
}

/** O tenant não existe, ou está `deleted_at`. */
export class TenantDesconhecidoError extends Error {
  override readonly name = "TenantDesconhecidoError";
  constructor(tenantId: string) {
    super(
      `nao existe platform.tenants com id = ${tenantId} e deleted_at IS NULL: ` +
        "provisionar um tenant que nao existe criava um merchant orfao no " +
        "Registo, que nenhuma consulta do COM voltaria a alcancar (KAM-042)",
    );
  }
}

/**
 * O `UPDATE` que escreve os dois ids.
 *
 * **Só preenche o que está vazio** (`IS NULL`), e o `RETURNING` diz se
 * escreveu. Sem o `IS NULL`, uma segunda corrida do *script* sobrescrevia o
 * `merchant_id` de um tenant já a operar — e todas as linhas do Registo
 * ficavam penduradas num `merchant` que o COM deixou de nomear, o que é perder
 * o catálogo de uma loja sem apagar uma linha.
 */
export const SQL_FIXAR_IDS =
  "UPDATE platform.tenants " +
  "SET medusa_merchant_id = $2, medusa_sales_channel_id = $3 " +
  "WHERE id = $1 AND deleted_at IS NULL " +
  "AND medusa_merchant_id IS NULL AND medusa_sales_channel_id IS NULL " +
  "RETURNING medusa_merchant_id, medusa_sales_channel_id";

/** O nome do tenant, para dar nome ao canal e à localização no Registo. */
export const SQL_NOME_DO_TENANT =
  "SELECT nome FROM platform.tenants WHERE id = $1 AND deleted_at IS NULL";

/**
 * Provisiona um tenant. Idempotente: um tenant já provisionado sai `criou:
 * false` sem tocar no Registo.
 *
 * A ordem das operações é a que sobrevive a uma falha a meio:
 *
 *   1. ler o estado actual de `platform.tenants` — se já tem os dois ids, sai;
 *   2. criar `merchant`, canal e localização no Registo (idempotentes);
 *   3. ligá-los;
 *   4. **só então** escrever os ids em `platform.tenants`.
 *
 * Uma falha entre 2 e 4 deixa objectos no Registo sem referência no
 * `platform` — e é recuperável, porque o passo 2 é idempotente por `tenantId`:
 * a corrida seguinte reencontra-os em vez de duplicar. A ordem inversa não
 * seria recuperável: um `merchant_id` escrito antes de o `merchant` existir
 * punha o repo-base a filtrar por um id que não existe, e uma consulta assim
 * devolve zero linhas — que é indistinguível de «esta loja não tem produtos».
 */
export async function provisionarTenant(
  deps: { readonly comTenant: ComTenant; readonly admin: RegistoAdmin },
  tenantId: string,
): Promise<Provisionamento> {
  if (!eUuid(tenantId)) throw new TenantDesconhecidoError(String(tenantId));
  const canonico = tenantId.toLowerCase();

  return deps.comTenant(canonico, async (cliente: ClienteSql) => {
    const nome = await nomeDoTenant(cliente, canonico);
    const existente = await cliente.query(SQL_MERCHANT_DO_TENANT, [canonico]);
    const merchantActual = existente.rows[0]?.["medusa_merchant_id"];
    const canalActual = existente.rows[0]?.["medusa_sales_channel_id"];

    if (typeof merchantActual === "string" && merchantActual.length > 0) {
      // Já provisionado. **O canal em falta não se completa aqui**: um tenant
      // com `merchant_id` e sem canal é um provisionamento que ficou a meio, e
      // completá-lo em silêncio escondia a razão por que ficou. Devolve-se o
      // que há e quem chama decide — o `criou: false` com `salesChannelId`
      // vazio é um estado que o *script* da Fase 0 tem de ver.
      return {
        tenantId: canonico,
        merchantId: merchantActual,
        salesChannelId: typeof canalActual === "string" ? canalActual : "",
        stockLocationId: "",
        criou: false,
      };
    }

    const merchantId = await deps.admin.criarMerchant(canonico, nome);
    const salesChannelId = await deps.admin.criarSalesChannel(canonico, nome);
    const stockLocationId = await deps.admin.criarStockLocation(canonico, nome);
    await deps.admin.ligar(merchantId, salesChannelId, stockLocationId);

    const escrito = await cliente.query(SQL_FIXAR_IDS, [
      canonico,
      merchantId,
      salesChannelId,
    ]);
    if (escrito.rows.length === 0) {
      // Outra corrida ganhou entre a leitura e a escrita. Não é erro — é a
      // corrida que o `IS NULL` existe para resolver —, mas o que há na base é
      // o que vale, e não o que esta corrida criou.
      throw new MerchantEmFaltaError(canonico);
    }

    return {
      tenantId: canonico,
      merchantId,
      salesChannelId,
      stockLocationId,
      criou: true,
    };
  });
}

async function nomeDoTenant(
  cliente: ClienteSql,
  tenantId: string,
): Promise<string> {
  const { rows } = await cliente.query(SQL_NOME_DO_TENANT, [tenantId]);
  const nome = rows[0]?.["nome"];
  if (typeof nome !== "string" || nome.length === 0) {
    throw new TenantDesconhecidoError(tenantId);
  }
  return nome;
}

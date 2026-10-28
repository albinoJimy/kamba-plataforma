/**
 * O modelo `merchant` — a base da opcao B.
 *
 * O `docs/tecnica/03` §3.3 propoe «modulo custom `merchant` + *links* para
 * produto, stock location, sales channel, encomenda» e marca-o NAO VERIFICADO.
 * Este ficheiro e a parte verificavel dessa hipotese: o modulo existe, e o
 * spike mede o que ele **nao** da.
 *
 * `tenant_id` e o `platform.tenants.id`. A coluna existe aqui porque o lado
 * Medusa precisa de saber a quem pertence um produto, e o `tenants` da
 * plataforma ja guarda o caminho inverso (`medusa_merchant_id`, revisao 0001).
 *
 * `created_at`, `updated_at` e `deleted_at` sao automaticos no `model.define` —
 * nao se declaram.
 */
import { model } from "@medusajs/framework/utils";

const Merchant = model.define("merchant", {
  id: model.id({ prefix: "merch" }).primaryKey(),
  tenant_id: model.text(),
  nome: model.text(),
});

export default Merchant;

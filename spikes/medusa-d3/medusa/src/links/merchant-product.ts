/**
 * `merchant` -> muitos `product`. O *link* da hipotese do §3.3.
 *
 * **O que este link nao da, e que o spike mede:** a documentacao oficial diz
 * que as colunas da tabela de link «store only the IDs of the linked records and
 * do not hold a foreign key constraint». Ou seja o link nao da integridade
 * referencial **nem** filtragem automatica — um `Query.graph` que atravesse o
 * link devolve o que o link alcanca, e nao o que o tenant do contexto pode ver.
 *
 * Se o `merchant_id` e a fronteira de tenant, impo-la e codigo nosso. E isso
 * que a matriz ISO-27..32 confirma por execucao em vez de por leitura.
 *
 * A tabela gerada chama-se `merchant_merchant_product_product`, com as colunas
 * `merchant_id` e `product_id`.
 */
import { defineLink } from "@medusajs/framework/utils";
import ProductModule from "@medusajs/medusa/product";

import MerchantModule from "../modules/merchant";

export default defineLink(MerchantModule.linkable.merchant, {
  linkable: ProductModule.linkable.product,
  isList: true,
});

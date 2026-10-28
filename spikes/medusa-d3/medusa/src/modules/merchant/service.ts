import { MedusaService } from "@medusajs/framework/utils";

import Merchant from "./models/merchant";

/**
 * `MedusaService` gera o CRUD (`createMerchants`, `retrieveMerchant`,
 * `listMerchants`, ...).
 *
 * **Nenhum destes metodos filtra por tenant.** E o ponto: o servico gerado
 * aceita um filtro, nao o impoe. Quem tem de o injectar e o adaptador do COM, e
 * e isso que a matriz ISO-27..32 vai tentar furar — um `listMerchants()` sem
 * filtro devolve os tres tenants ficticios, e e o resultado certo para este
 * nivel. O isolamento nao esta aqui; esta na porta e na RLS.
 */
class MerchantModuleService extends MedusaService({
  Merchant,
}) {}

export default MerchantModuleService;

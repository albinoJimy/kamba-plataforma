import { Module } from "@medusajs/framework/utils";

import MerchantModuleService from "./service";

/** O nome do modulo: so alfanumericos e `_` (`merchant` serve). */
export const MERCHANT_MODULE = "merchant";

export default Module(MERCHANT_MODULE, {
  service: MerchantModuleService,
});

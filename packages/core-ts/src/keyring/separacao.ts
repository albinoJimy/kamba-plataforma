/**
 * Chaves distintas por ambiente (KAM-072, critério 8).
 *
 * «Um teste de configuração falha se uma chave Meta ou do facilitador de `prod`
 * estiver presente em `staging`.» A verificação compara os **valores** que dois
 * provedores de segredos devolvem para as mesmas referências — a actual e a
 * anterior de cada anel, porque uma chave de `prod` acabada de rodar continua
 * a ser de `prod` — e falha se algum coincidir.
 *
 * ## Como se compara sem expor
 *
 * Por resumo e em tempo constante: cada valor passa por um HMAC com uma chave
 * aleatória desta chamada, e comparam-se os resumos. O resumo não sai daqui, e
 * a chave morre com a chamada, pelo que nem um resumo de um segredo de `prod`
 * fica a valer como impressão digital fora dela. O erro nomeia a referência e
 * os dois ambientes, e **nunca** o valor.
 *
 * Quem tem acesso aos dois cofres ao mesmo tempo é a CI de configuração, com
 * credenciais de leitura dos dois projectos — o que hoje não existe (não há
 * conta Doppler, KAM-010 critério 2). O ensaio prova a regra com dois
 * provedores de ensaio; correr contra os projectos reais é a caixa devolvida.
 */

import { Buffer } from "node:buffer";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import type { Ambiente, SecretProvider } from "../secrets/index.ts";

/**
 * As referências que o critério 8 nomeia: as chaves da Meta e do facilitador.
 * Os `id` são os do `ops/secrets-inventory.yaml`.
 */
export const REFS_SEPARADAS_POR_AMBIENTE: readonly string[] = [
  "meta_app_secret",
  "meta_verify_token",
  "proxypay_api_key",
  "appypay_client_secret",
];

/** A mesma chave aparece em dois ambientes. Nunca diz o valor. */
export class ChavePartilhadaEntreAmbientesError extends Error {
  override readonly name = "ChavePartilhadaEntreAmbientesError";
  readonly ref: string;
  readonly ambientes: readonly [Ambiente, Ambiente];

  constructor(ref: string, a: Ambiente, b: Ambiente) {
    super(`a chave ${ref} de ${a} está presente em ${b}; as chaves são distintas por ambiente`);
    this.ref = ref;
    this.ambientes = [a, b];
  }
}

/**
 * Verifica que nenhum valor de `refs` se repete entre os provedores dados.
 *
 * Um provedor que não tenha uma referência não conta como violação — a
 * ausência é do `Secrets.arrancar`, não desta regra.
 */
export async function verificarSeparacaoDeAmbientes(
  provedores: readonly SecretProvider[],
  refs: readonly string[] = REFS_SEPARADAS_POR_AMBIENTE,
): Promise<void> {
  const chave = randomBytes(32);
  const resumo = (valor: string): Buffer => createHmac("sha256", chave).update(valor, "utf8").digest();

  for (const ref of refs) {
    const vistos: { ambiente: Ambiente; resumo: Buffer }[] = [];
    for (const provedor of provedores) {
      let anel: readonly (string | null)[];
      try {
        anel = await provedor.getRing(ref); // kamba:secrets-inventory dinamico as refs sao as de REFS_SEPARADAS_POR_AMBIENTE, todas no inventario
      } catch {
        continue;
      }
      for (const valor of anel) {
        if (typeof valor !== "string" || valor === "") continue;
        const r = resumo(valor);
        let repetido: Ambiente | null = null;
        for (const visto of vistos) {
          // Sem sair ao primeiro: o resultado decide-se depois de comparar todos.
          if (timingSafeEqual(visto.resumo, r) && visto.ambiente !== provedor.ambiente) {
            repetido = repetido ?? visto.ambiente;
          }
        }
        if (repetido !== null) {
          throw new ChavePartilhadaEntreAmbientesError(ref, repetido, provedor.ambiente);
        }
        vistos.push({ ambiente: provedor.ambiente, resumo: r });
      }
    }
  }
}

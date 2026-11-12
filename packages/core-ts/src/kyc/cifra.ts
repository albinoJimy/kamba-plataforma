/**
 * AES-256-GCM para o `kyc_check.extraido_enc` (KAM-087).
 *
 * Os campos extraídos são dados pessoais (NIF, nome, número do BI, IBAN) e
 * guardam-se cifrados em aplicação, com o contexto (`onboarding_id` e tipo)
 * como dados autenticados: um `extraido_enc` copiado para outra linha não
 * decifra. Forma: `iv (12) ‖ etiqueta (16) ‖ cifrado`.
 *
 * A chave é de 32 octetos e vem do cofre (KAM-010); este módulo não a lê.
 */

import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

import type { Cifra } from "./contrato.ts";

export class CifraAesGcm implements Cifra {
  readonly #chave: Uint8Array;

  constructor(chave: Uint8Array) {
    if (chave.length !== 32) throw new Error("a chave de cifra tem 32 octetos");
    this.#chave = Uint8Array.from(chave);
  }

  async cifrar(claro: Uint8Array, contexto: string): Promise<Uint8Array> {
    const iv = randomBytes(12);
    const c = createCipheriv("aes-256-gcm", this.#chave, iv);
    c.setAAD(Buffer.from(contexto, "utf8"));
    const corpo = Buffer.concat([c.update(claro), c.final()]);
    return new Uint8Array(Buffer.concat([iv, c.getAuthTag(), corpo]));
  }

  async decifrar(cifrado: Uint8Array, contexto: string): Promise<Uint8Array> {
    if (cifrado.length < 28) throw new Error("cifrado curto demais");
    const d = createDecipheriv("aes-256-gcm", this.#chave, cifrado.subarray(0, 12));
    d.setAAD(Buffer.from(contexto, "utf8"));
    d.setAuthTag(cifrado.subarray(12, 28));
    return new Uint8Array(Buffer.concat([d.update(cifrado.subarray(28)), d.final()]));
  }
}

/**
 * Os alvos em memória da bateria de contrato (KAM-011): o *fake*, e o motor S3
 * ligado a um servidor S3 em memória. Partilhados pelas suites de contrato e de
 * isolamento, para que as duas ataquem exactamente as mesmas montagens.
 */

import { criarStorageS3 } from "../../src/storage/config.ts";
import { criarStorageFake } from "../../src/storage/fake.ts";
import type { Alvo } from "./contrato-storage.ts";
import { S3EmMemoria } from "./s3-em-memoria.ts";

/** Um relógio que só anda quando lhe mandam. */
export class Relogio {
  #agora: number;
  constructor(inicio = "2026-10-12T09:00:00.000Z") {
    this.#agora = new Date(inicio).getTime();
  }
  readonly agora = (): Date => new Date(this.#agora);
  avancar(segundos: number): void {
    this.#agora += segundos * 1000;
  }
}

/** Valores de teste, com forma que não se confunde com uma chave real. */
export const CREDENCIAIS_DE_TESTE = {
  accessKeyId: "chave-de-teste",
  secretAccessKey: "valor-de-teste",
} as const;

export const CONFIG_DE_TESTE = {
  endpoint: "http://s3.teste.invalid:8333",
  bucket: "kamba-teste",
  regiao: "ao-teste-1",
  destino: { country: "AO", provider: "seaweedfs_teste", apdRef: null },
  avisos: [],
} as const;

/** Um cofre de teste: devolve os dois valores e conta os pedidos. */
export function cofreDeTeste(valores: Readonly<Record<string, string>> = {
  storage_access_key_id: CREDENCIAIS_DE_TESTE.accessKeyId,
  storage_secret_access_key: CREDENCIAIS_DE_TESTE.secretAccessKey,
}): { get(ref: string): Promise<string>; pedidos: string[] } {
  const pedidos: string[] = [];
  return {
    pedidos,
    async get(ref: string): Promise<string> {
      pedidos.push(ref);
      const valor = valores[ref];
      if (valor === undefined) throw new Error(`segredo ausente: ${ref}`);
      return valor;
    },
  };
}

export async function alvoFake(): Promise<Alvo> {
  const relogio = new Relogio();
  const fake = criarStorageFake({ agora: relogio.agora });
  return {
    storage: fake.storage,
    buscar: fake.buscar,
    avancar: async (segundos) => relogio.avancar(segundos),
  };
}

/** O motor S3 sobre um servidor em memória, e o servidor para quem o quer espiar. */
export function montarS3EmMemoria(o: { pagina?: number; tamanhoDaParte?: number } = {}): {
  alvo: Alvo;
  servidor: S3EmMemoria;
  relogio: Relogio;
} {
  const relogio = new Relogio();
  const servidor = new S3EmMemoria({
    bucket: CONFIG_DE_TESTE.bucket,
    regiao: CONFIG_DE_TESTE.regiao,
    credenciais: CREDENCIAIS_DE_TESTE,
    agora: relogio.agora,
    ...(o.pagina === undefined ? {} : { pagina: o.pagina }),
  });
  const storage = criarStorageS3({
    config: CONFIG_DE_TESTE,
    secrets: cofreDeTeste(),
    transporte: servidor.transporte,
    agora: relogio.agora,
    ...(o.tamanhoDaParte === undefined ? {} : { tamanhoDaParte: o.tamanhoDaParte }),
  });
  return {
    alvo: {
      storage,
      buscar: (url) => servidor.buscar(url),
      avancar: async (segundos) => relogio.avancar(segundos),
    },
    servidor,
    relogio,
  };
}

export async function alvoS3EmMemoria(): Promise<Alvo> {
  return montarS3EmMemoria().alvo;
}

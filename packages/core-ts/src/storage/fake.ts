/**
 * Implementação *fake* do armazenamento: tudo em memória (KAM-011).
 *
 * É o que os consumidores usam nos seus testes unitários (o MED no KAM-020, o
 * KYC no KAM-098) e é um dos alvos da suite de contrato — a mesma bateria corre
 * aqui e contra um servidor S3 real.
 *
 * O que a torna um *fake* e não um *mock*: **comporta-se**. Guarda bytes, soma
 * tamanhos, expira URLs pelo relógio e recusa uma URL adulterada. O que não
 * tem: persistência, concorrência entre processos, e HTTP — a URL que assina
 * tem o esquema `kamba-fake:` e só `buscar` a sabe resolver.
 */

import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { ArmazenamentoPorTenant } from "./guarda.ts";
import type { Escrito, InfoBruta, ItemListado, MetaBruta, Motor } from "./motor.ts";
import { ObjectoInexistenteError, type StorageProvider } from "./port.ts";

/** Esquema das URLs que o *fake* assina. */
export const ESQUEMA_FAKE = "kamba-fake:";

interface Guardado {
  readonly bytes: Uint8Array;
  readonly meta: MetaBruta;
}

/** Resposta de `buscar`: o que um cliente HTTP veria. */
export interface RespostaFake {
  readonly estado: 200 | 403 | 404;
  readonly corpo: Uint8Array;
}

export interface MotorEmMemoriaOpcoes {
  /** Relógio. Por omissão, o do sistema. Os testes injectam um que avança. */
  readonly agora?: () => Date;
}

async function* emBlocos(bytes: Uint8Array, tamanho = 64 * 1024): AsyncIterable<Uint8Array> {
  for (let i = 0; i < bytes.length; i += tamanho) {
    yield bytes.subarray(i, Math.min(i + tamanho, bytes.length));
  }
}

/** Motor em memória. Ver `criarStorageFake` para a forma de o usar. */
export class MotorEmMemoria implements Motor {
  readonly nome = "fake";
  readonly #objectos = new Map<string, Guardado>();
  readonly #agora: () => Date;
  /** Chave de assinatura das URLs: aleatória, por instância, nunca exposta. */
  readonly #segredo = randomBytes(32);

  constructor(opcoes: MotorEmMemoriaOpcoes = {}) {
    this.#agora = opcoes.agora ?? (() => new Date());
  }

  async put(chave: string, corpo: AsyncIterable<Uint8Array>, meta: MetaBruta): Promise<Escrito> {
    const blocos: Uint8Array[] = [];
    const soma = createHash("sha256");
    let tamanho = 0;
    for await (const bloco of corpo) {
      // Copia: quem chamou pode reutilizar o seu buffer depois do `put`.
      blocos.push(Uint8Array.from(bloco));
      soma.update(bloco);
      tamanho += bloco.length;
    }
    const bytes = new Uint8Array(tamanho);
    let posicao = 0;
    for (const bloco of blocos) {
      bytes.set(bloco, posicao);
      posicao += bloco.length;
    }
    this.#objectos.set(chave, {
      bytes,
      meta: { contentType: meta.contentType, metadados: { ...meta.metadados } },
    });
    return { tamanho, sha256: soma.digest("hex") };
  }

  async get(chave: string): Promise<AsyncIterable<Uint8Array>> {
    return emBlocos(this.#exigir(chave).bytes);
  }

  async head(chave: string): Promise<InfoBruta> {
    const guardado = this.#exigir(chave);
    return {
      tamanho: guardado.bytes.length,
      contentType: guardado.meta.contentType,
      metadados: { ...guardado.meta.metadados },
    };
  }

  async delete(chave: string): Promise<void> {
    this.#objectos.delete(chave);
  }

  async list(
    prefixo: string,
    maximo: number,
  ): Promise<{ readonly itens: readonly ItemListado[]; readonly truncada: boolean }> {
    const chaves = [...this.#objectos.keys()].filter((c) => c.startsWith(prefixo)).sort();
    const itens = chaves.slice(0, maximo).map((chave) => ({
      chave,
      tamanho: (this.#objectos.get(chave) as Guardado).bytes.length,
    }));
    return { itens, truncada: chaves.length > maximo };
  }

  async signUrl(chave: string, ttlSegundos: number): Promise<string> {
    const expira = Math.floor(this.#agora().getTime() / 1000) + ttlSegundos;
    return `${ESQUEMA_FAKE}//objectos/${chave}?expira=${expira}&assinatura=${this.#assinar(chave, expira)}`;
  }

  /**
   * Resolve uma URL assinada por este motor, como um cliente HTTP faria.
   *
   * 403 se a assinatura não bate ou se o prazo passou — os dois casos dão a
   * mesma resposta, como num servidor S3. 404 se a URL é válida e o objecto já
   * não existe.
   */
  async buscar(url: string): Promise<RespostaFake> {
    const recusado: RespostaFake = { estado: 403, corpo: new Uint8Array(0) };
    let lida: URL;
    try {
      lida = new URL(url);
    } catch {
      return recusado;
    }
    if (lida.protocol !== ESQUEMA_FAKE || lida.host !== "objectos") return recusado;
    const chave = decodeURIComponent(lida.pathname.slice(1));
    // Lidos da *query* em bruto: o `searchParams` trocava um `+` por espaço, e o
    // `Number()` aceitava `1.0`, `0x10` e espaços — o lado Python não.
    const m = /^\?expira=([0-9]{1,12})&assinatura=([0-9a-f]{64})$/.exec(lida.search);
    if (m === null) return recusado;
    const expira = Number(m[1]);
    const assinatura = m[2] as string;
    const esperada = Buffer.from(this.#assinar(chave, expira), "hex");
    const recebida = Buffer.from(assinatura, "hex");
    if (recebida.length !== esperada.length || !timingSafeEqual(recebida, esperada)) {
      return recusado;
    }
    if (Math.floor(this.#agora().getTime() / 1000) >= expira) return recusado;
    const guardado = this.#objectos.get(chave);
    if (guardado === undefined) return { estado: 404, corpo: new Uint8Array(0) };
    return { estado: 200, corpo: Uint8Array.from(guardado.bytes) };
  }

  /** Número de objectos guardados, de todos os tenants. Só para testes. */
  get total(): number {
    return this.#objectos.size;
  }

  #assinar(chave: string, expira: number): string {
    return createHmac("sha256", this.#segredo).update(`${chave}\n${expira}`).digest("hex");
  }

  #exigir(chave: string): Guardado {
    const guardado = this.#objectos.get(chave);
    if (guardado === undefined) throw new ObjectoInexistenteError();
    return guardado;
  }
}

/** A porta sobre memória, e o que um teste precisa além dela. */
export interface StorageFake {
  readonly storage: StorageProvider;
  /** Resolve uma URL assinada por este armazenamento, como um cliente HTTP faria. */
  readonly buscar: (url: string) => Promise<RespostaFake>;
  /** Número de objectos guardados, de todos os tenants. */
  readonly total: () => number;
}

/**
 * Cria um armazenamento *fake*, já com a guarda de isolamento.
 *
 * ```ts
 * const { storage } = criarStorageFake();
 * const key = novaChave(ctx, "audio");
 * const ref = await storage.put(ctx, key, bytes, { contentType, classe: "audio", retainUntil });
 * ```
 *
 * O motor não sai daqui: quem tem o motor lê qualquer chave sem contexto, e um
 * *fake* que ensina esse atalho nos testes ensina-o para o código.
 */
export function criarStorageFake(opcoes: MotorEmMemoriaOpcoes = {}): StorageFake {
  const motor = new MotorEmMemoria(opcoes);
  return {
    storage: new ArmazenamentoPorTenant(motor),
    buscar: (url) => motor.buscar(url),
    total: () => motor.total,
  };
}

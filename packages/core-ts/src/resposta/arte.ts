/**
 * A arte do módulo social, lida do STO para sair como imagem (KAM-246).
 *
 * A `agent_replies.media_ref` guarda a **chave** do objecto (nunca um URL), e o
 * consumidor `outbound` lê-a para carregar o JPEG na Meta. Duas recusas, pela
 * ordem, e as duas **antes** de qualquer byte sair do armazenamento:
 *
 * 1. a chave tem de ser do tenant do envelope e da classe `arte`
 *    (`chaveDaArte`): uma chave forjada, de outro tenant ou de outra classe —
 *    a foto do dono, um documento de KYC — não se lê;
 * 2. o objecto tem de ser um JPEG dentro do tecto (`MAXIMO_DA_IMAGEM`), pelos
 *    metadados (`head`) e outra vez pelos bytes lidos.
 *
 * A revisão do KAM-246 repete a primeira na base (o `CHECK` da coluna), e esta é
 * a outra metade: continua a valer se alguém largar a restrição. A porta do STO
 * (`ArmazenamentoPorTenant`) é a terceira: recusa uma chave fora do tenant do
 * contexto.
 */

import { MAXIMO_DA_IMAGEM, TIPO_DA_IMAGEM } from "../outbound/contrato.ts";
import { chaveDoCtx } from "../storage/chave.ts";
import { ChaveForaDoTenantError, ChaveInvalidaError, type StorageProvider } from "../storage/port.ts";

/** A classe de retenção da arte no STO (KAM-122, dicionário §3.82). */
export const CLASSE_DA_ARTE = "arte";

/** Porque é que uma arte não sai. Literais, para o desfecho: nenhum leva a chave. */
export const MOTIVOS_DA_ARTE_RECUSADA = [
  /** A chave não tem a forma, ou não é do tenant do envelope. */
  "de_outro_tenant",
  /** A chave é do tenant, mas de outra classe que não `arte`. */
  "de_outra_classe",
  /** O objecto não é um JPEG. */
  "nao_e_jpeg",
  /** O objecto está vazio, ou passa do tecto. */
  "fora_do_tamanho",
] as const;
export type MotivoDaArteRecusada = (typeof MOTIVOS_DA_ARTE_RECUSADA)[number];

/** A arte não serve para sair. Não há tentativa que o resolva. */
export class ArteRecusadaError extends Error {
  override readonly name = "ArteRecusadaError";
  readonly motivo: MotivoDaArteRecusada;

  constructor(motivo: MotivoDaArteRecusada) {
    super(`a arte da resposta foi recusada: ${motivo}`);
    this.motivo = motivo;
  }
}

/**
 * Confere a chave contra o tenant e a classe. Pura: corre antes de tocar no STO.
 *
 * @throws {ArteRecusadaError} `de_outro_tenant` ou `de_outra_classe`.
 */
export function chaveDaArte(tenantId: string, mediaRef: string): string {
  let classe: string;
  try {
    classe = chaveDoCtx({ tenantId }, mediaRef, "get").classe;
  } catch (erro) {
    if (erro instanceof ChaveForaDoTenantError || erro instanceof ChaveInvalidaError) {
      throw new ArteRecusadaError("de_outro_tenant");
    }
    throw erro;
  }
  if (classe !== CLASSE_DA_ARTE) throw new ArteRecusadaError("de_outra_classe");
  return mediaRef;
}

/** O início de todo o JPEG (SOI e o primeiro marcador). */
const ASSINATURA_DO_JPEG = [0xff, 0xd8, 0xff] as const;

/** Os bytes são um JPEG dentro do tecto, ou recusa. */
export function exigirJpeg(bytes: Uint8Array): Uint8Array {
  if (bytes.length === 0 || bytes.length > MAXIMO_DA_IMAGEM) throw new ArteRecusadaError("fora_do_tamanho");
  if (!ASSINATURA_DO_JPEG.every((b, i) => bytes[i] === b)) throw new ArteRecusadaError("nao_e_jpeg");
  return bytes;
}

/** A porta: o JPEG da arte de uma resposta, conferido. Ver a nota do módulo. */
export type LerArte = (tenantId: string, mediaRef: string) => Promise<Uint8Array>;

/** O leitor de produção, sobre a porta do STO (`criarStorageS3`). */
export function arteDoSto(armazenamento: StorageProvider): LerArte {
  return async (tenantId, mediaRef) => {
    const key = chaveDaArte(tenantId, mediaRef);
    const ctx = { tenantId };
    const info = await armazenamento.head(ctx, { key, tamanho: 0, sha256: null });
    if (info.classe !== CLASSE_DA_ARTE) throw new ArteRecusadaError("de_outra_classe");
    if (info.contentType !== TIPO_DA_IMAGEM) throw new ArteRecusadaError("nao_e_jpeg");
    if (info.tamanho <= 0 || info.tamanho > MAXIMO_DA_IMAGEM) throw new ArteRecusadaError("fora_do_tamanho");
    const partes: Uint8Array[] = [];
    let total = 0;
    for await (const parte of await armazenamento.get(ctx, { key, tamanho: info.tamanho, sha256: null })) {
      total += parte.length;
      // Um objecto que cresce entre o `head` e o `get` não se lê até ao fim.
      if (total > MAXIMO_DA_IMAGEM) throw new ArteRecusadaError("fora_do_tamanho");
      partes.push(parte);
    }
    const bytes = new Uint8Array(total);
    let posicao = 0;
    for (const parte of partes) {
      bytes.set(parte, posicao);
      posicao += parte.length;
    }
    return exigirJpeg(bytes);
  };
}

/**
 * O NIF e o e-mail do caso de onboarding, cifrados (KAM-236): o
 * `onboarding_case.nif_enc` e o `onboarding_case.email_enc`.
 *
 * O formato é o do `./telefone_do_caso.ts` — AES-256-GCM, DEK derivada por
 * tenant com HKDF, `kid` dentro do criptograma, e o contexto autenticado com o
 * tenant, o `onboarding_id` e o **campo** —, com outro domínio. O campo no
 * contexto é o que faz um `nif_enc` copiado para o `email_enc` do mesmo caso
 * **não abrir**; o `onboarding_id`, que não abra noutro caso.
 *
 * **Só se escreve.** Nenhuma rota do `onboarding-web` lê o NIF ou o e-mail de
 * volta: a correspondência faz-se pelo `nif_hmac`, e o e-mail não tem leitor
 * neste ticket. O decifrador existe para o ensaio e para quem o vier a ler.
 *
 * Nenhum erro deste ficheiro contém o valor que recusou.
 */

import { Buffer } from "node:buffer";
import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";

import { separarKid } from "../secrets/kid.ts";
import type { SecretRingTuple } from "../secrets/port.ts";

import type { CifraDoCaso } from "./sql.ts";
import {
  cifrarTelefoneDoCaso,
  decifrarTelefoneDoCaso,
  type AnelDoTelefone,
  type CasoDoTelefone,
} from "./telefone_do_caso.ts";

/** Os dois campos que esta cifra guarda. Entram no contexto autenticado. */
export const CAMPOS_DOS_DADOS = ["nif_enc", "email_enc"] as const;
export type CampoDosDados = (typeof CAMPOS_DOS_DADOS)[number];

const VERSAO = 1;
const OCTETOS_DE_CHAVE = 32;
const OCTETOS_DE_IV = 12;
const OCTETOS_DE_ETIQUETA = 16;
const DOMINIO_DA_DEK = "kamba.inscricao.dados.dek.v1";
const DOMINIO_DA_CIFRA = "kamba.inscricao.dados.v1";
const UUID_CANONICO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O anel da KEK: a versão com que se cifra e todas as que abrem. */
export interface AnelDosDados {
  readonly ref: string;
  readonly kid: string;
  readonly chaves: ReadonlyMap<string, Buffer>;
}

/** A KEK não serve, ou o criptograma não abre. Sem o valor na mensagem. */
export class DadosDoCasoError extends Error {
  override readonly name = "DadosDoCasoError";
}

function versao(ref: string, valor: string, posicao: string): { kid: string; chave: Buffer } {
  const separado = separarKid(valor);
  if (separado === null) {
    throw new DadosDoCasoError(`a ${ref} ${posicao} nao tem a forma <kid>:<base64 de 32 octetos>`);
  }
  return { kid: separado.kid, chave: Buffer.from(separado.chave, "base64") };
}

/** O anel a partir do `getRing` do cofre, com `kid` estável nas duas posições. */
export function anelDosDados(ref: string, [actual, anterior]: SecretRingTuple): AnelDosDados {
  const a = versao(ref, actual, "actual");
  const chaves = new Map<string, Buffer>([[a.kid, a.chave]]);
  if (anterior !== null) {
    const b = versao(ref, anterior, "anterior");
    if (chaves.has(b.kid)) throw new DadosDoCasoError(`a ${ref} tem o mesmo kid nas duas versoes`);
    chaves.set(b.kid, b.chave);
  }
  return { ref, kid: a.kid, chaves };
}

function caso(c: CasoDoTelefone): { tenant: string; onboarding: string } {
  const tenant = String(c.tenantId).toLowerCase();
  const onboarding = String(c.onboardingId).toLowerCase();
  if (!UUID_CANONICO.test(tenant) || !UUID_CANONICO.test(onboarding)) {
    throw new DadosDoCasoError("o tenant_id ou o onboarding_id nao e um UUID canonico");
  }
  return { tenant, onboarding };
}

function dek(kek: Buffer, tenant: string): Buffer {
  return Buffer.from(hkdfSync("sha256", kek, Buffer.alloc(0), Buffer.from(`${DOMINIO_DA_DEK}\0${tenant}`), OCTETOS_DE_CHAVE));
}

function contexto(c: CasoDoTelefone, campo: CampoDosDados, kid: string): Buffer {
  const { tenant, onboarding } = caso(c);
  return Buffer.from(`${DOMINIO_DA_CIFRA}\0${tenant}\0${onboarding}\0${campo}\0${kid}`, "utf8");
}

/** Cifra um campo do caso com a versão actual. Um IV novo por chamada. */
export function cifrarDadoDoCaso(
  anel: AnelDosDados,
  c: CasoDoTelefone,
  campo: CampoDosDados,
  claro: { revelar(): string },
): Buffer {
  const { tenant } = caso(c);
  const kek = anel.chaves.get(anel.kid);
  if (kek === undefined) throw new DadosDoCasoError(`a ${anel.ref} nao tem a versao actual`);
  const kid = Buffer.from(anel.kid, "utf8");
  const iv = randomBytes(OCTETOS_DE_IV);
  const cifra = createCipheriv("aes-256-gcm", dek(kek, tenant), iv);
  cifra.setAAD(contexto(c, campo, anel.kid));
  const corpo = Buffer.concat([cifra.update(claro.revelar(), "utf8"), cifra.final()]);
  return Buffer.concat([Buffer.from([VERSAO, kid.byteLength]), kid, iv, cifra.getAuthTag(), corpo]);
}

/** Abre um campo do caso com a versão que ele diz. Lança `DadosDoCasoError`. */
export function decifrarDadoDoCaso(
  anel: AnelDosDados,
  c: CasoDoTelefone,
  campo: CampoDosDados,
  criptograma: Uint8Array,
): string {
  const { tenant } = caso(c);
  const dados = Buffer.from(criptograma);
  if (dados.byteLength < 2 || dados[0] !== VERSAO) throw new DadosDoCasoError("formato desconhecido");
  const inicio = 2 + (dados[1] ?? 0);
  const cabecalho = inicio + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA;
  if (inicio === 2 || dados.byteLength <= cabecalho) throw new DadosDoCasoError("criptograma curto");
  const kid = dados.subarray(2, inicio).toString("utf8");
  const kek = anel.chaves.get(kid);
  if (kek === undefined) throw new DadosDoCasoError("a versao da KEK que o cifrou nao esta no anel");
  const decifra = createDecipheriv("aes-256-gcm", dek(kek, tenant), dados.subarray(inicio, inicio + OCTETOS_DE_IV));
  decifra.setAAD(contexto(c, campo, kid));
  decifra.setAuthTag(dados.subarray(inicio + OCTETOS_DE_IV, cabecalho));
  try {
    return Buffer.concat([decifra.update(dados.subarray(cabecalho)), decifra.final()]).toString("utf8");
  } catch {
    throw new DadosDoCasoError("a autenticacao falhou");
  }
}

/**
 * A `CifraDoCaso` do adaptador: o telefone com a `kek_telefone_do_caso`
 * (decisão do fundador de 2026-11-20), e o NIF e o e-mail com o anel `dados`.
 */
export function cifraDoCaso(telefone: AnelDoTelefone, dados: AnelDosDados): CifraDoCaso {
  return {
    nif: (c, nif) => cifrarDadoDoCaso(dados, c, "nif_enc", nif),
    email: (c, email) => cifrarDadoDoCaso(dados, c, "email_enc", email),
    telefone: (c, t) => cifrarTelefoneDoCaso(telefone, c, t),
    abrirTelefone: (c, cifra) => {
      try {
        return decifrarTelefoneDoCaso(telefone, c, cifra).revelar();
      } catch {
        return null;
      }
    },
  };
}

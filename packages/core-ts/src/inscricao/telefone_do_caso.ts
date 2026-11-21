/**
 * O telefone verificado do caso de onboarding, cifrado (KAM-215): o
 * `onboarding_case.phone_enc`, quem o escreve e quem o lê.
 *
 * ## A decisão é do fundador (2026-11-20), e é esta
 *
 * **KEK própria**, `kek_telefone_do_caso`, só para este campo, com anel
 * (actual e anterior) e `kid` estável no valor (`<kid>:<base64 de 32
 * octetos>`). Só a recebem o `onboarding-web`, que escreve, e o processo do
 * consumidor `dono`, que lê. Foram **recusadas** a KEK dos *tokens* da Meta
 * (`kek_token_cliente`, `../onboarding/cifra.ts`) e a das DEK de contacto
 * (`kek_contact_dek`, KAM-008): a separação de domínio sai da chave, e não de
 * uma constante que alguém pode esquecer de mudar — o argumento que a
 * `kek_contacto_dono` deixou escrito no inventário.
 *
 * ## O formato é o do resto, com o caso no contexto
 *
 * AES-256-GCM, DEK **derivada** por tenant (`HKDF-SHA256(KEK, info = domínio ‖
 * tenant_id)`, sem tabela de DEK, pela razão do `../onboarding/cifra.ts`), e o
 * `kid` em claro dentro do criptograma:
 *
 *     versão(1) ‖ comprimento do kid(1) ‖ kid ‖ IV(12) ‖ etiqueta(16) ‖ cifra
 *
 * O contexto autenticado leva **o tenant, o `onboarding_id` e o campo** (e o
 * `kid`). É o `onboarding_id` que faz um `phone_enc` copiado para outro caso
 * **não abrir**, mesmo do mesmo tenant: sem ele, mover a coluna de um caso para
 * outro dava ao segundo o telefone do primeiro, e o dono do provisionamento
 * passava a ser outra pessoa.
 *
 * ## Quem escreve, e quem lê
 *
 * O **escritor** é o `colunasDoTelefone`: as duas colunas que o `INSERT` do caso
 * escreve juntas, o `phone_enc` e o `phone_hmac`. O `kamba_app` só tem `INSERT`
 * nelas (o `UPDATE` da `0043` é por coluna, e nenhuma é esta), pelo que o
 * telefone de um caso escreve-se uma vez, ao criá-lo, com o `id` e o
 * `tenant_id` **pré-alocados** pelo escritor — o contexto autenticado precisa
 * dos dois antes de a linha existir.
 *
 * O **leitor** é o `lerTelefoneDoCaso`: lê a coluna pela ligação que recebe,
 * sob a RLS do tenant que essa ligação já tem no contexto, e devolve `null` em
 * vez de lançar — um caso de outro tenant (zero linhas), uma coluna ilegível,
 * uma versão da KEK que saiu do anel. É a forma do `telefoneDe` do KAM-086.
 *
 * **Nenhum erro deste ficheiro contém o valor que recusou**, como no
 * `identity/cripto.ts` e no `../onboarding/cifra.ts`.
 */

import { Buffer } from "node:buffer";
import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";

import { separarKid } from "../secrets/kid.ts";
import type { SecretRingTuple } from "../secrets/port.ts";
import { Opaco } from "../sms/opaco.ts";

import { normalizarTelefone, type Telefone } from "./identificadores.ts";

/** A referência da KEK no cofre. O inventário tem a entrada com o mesmo `id`. */
export const REF_KEK_DO_TELEFONE = "kek_telefone_do_caso";

/** O campo que esta cifra guarda. Entra no contexto autenticado. */
export const CAMPO_DO_TELEFONE = "phone_enc";

/** Octetos de uma KEK e de uma DEK: AES-256. */
export const OCTETOS_DE_CHAVE = 32;
/** Octetos do IV de GCM. */
export const OCTETOS_DE_IV = 12;
/** Octetos da etiqueta de GCM. */
export const OCTETOS_DE_ETIQUETA = 16;
/** A versão do formato, o primeiro octeto do criptograma. */
export const VERSAO_DO_FORMATO = 1;

const DOMINIO_DA_DEK = "kamba.inscricao.telefone.dek.v1";
const DOMINIO_DA_CIFRA = "kamba.inscricao.telefone.v1";

const UUID_CANONICO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O caso a que o telefone pertence: os dois identificadores do contexto. */
export interface CasoDoTelefone {
  readonly tenantId: string;
  readonly onboardingId: string;
}

/** A KEK não serve: forma errada, sem `kid` estável, ou duas versões com o mesmo `kid`. */
export class KekDoTelefoneInvalidaError extends Error {
  override readonly name = "KekDoTelefoneInvalidaError";

  constructor(motivo: string) {
    super(`a ${REF_KEK_DO_TELEFONE} nao serve: ${motivo}`);
  }
}

/** O criptograma não abre, ou o que se deu não cifra. */
export class TelefoneCifradoInvalidoError extends Error {
  override readonly name = "TelefoneCifradoInvalidoError";

  constructor(motivo: string) {
    super(`o telefone cifrado do caso nao se consegue tratar: ${motivo}`);
  }
}

/**
 * O telefone do caso em claro, **opaco**: `revelar()` é o único caminho para o
 * número, e qualquer conversão para texto dá `***`. Sem HMAC, de propósito: o
 * HMAC da inscrição pedia o *pepper* dela, e quem lê este telefone (o
 * consumidor do dono) não o tem nem precisa — o `resolveContact` cunha o do
 * contacto com a chave dele.
 */
export class TelefoneDoCasoEmClaro extends Opaco {
  constructor(bruto: unknown) {
    super(normalizarTelefone(bruto));
  }
}

/** O anel da KEK: a versão com que se cifra e todas as que abrem. */
export interface AnelDoTelefone {
  readonly kid: string;
  readonly chaves: ReadonlyMap<string, Buffer>;
}

function versao(valor: string, posicao: "actual" | "anterior"): { kid: string; chave: Buffer } {
  // **`kid` estável, sempre.** Esta KEK nasce depois do KAM-205, e não tem
  // criptogramas legados: um valor sem `kid`, com um rótulo posicional por
  // `kid`, ou que não dê 32 octetos é uma configuração errada (o `separarKid`
  // recusa os três), e cifrar com ele gravava um `kid` que a próxima rotação
  // faz apontar para outra chave.
  const separado = separarKid(valor);
  if (separado === null) {
    throw new KekDoTelefoneInvalidaError(`a versao ${posicao} nao tem a forma <kid>:<base64 de 32 octetos>`);
  }
  return { kid: separado.kid, chave: Buffer.from(separado.chave, "base64") };
}

/** O anel a partir do `getRing` do cofre: `[actual, anterior]`. */
export function anelDoTelefone([actual, anterior]: SecretRingTuple): AnelDoTelefone {
  const a = versao(actual, "actual");
  const chaves = new Map<string, Buffer>([[a.kid, a.chave]]);
  if (anterior !== null) {
    const b = versao(anterior, "anterior");
    if (chaves.has(b.kid)) {
      throw new KekDoTelefoneInvalidaError("a versao actual e a anterior tem o mesmo kid");
    }
    chaves.set(b.kid, b.chave);
  }
  return { kid: a.kid, chaves };
}

/** Lê o anel do cofre. O `getRing` é literal, para o inventário o ver. */
export async function lerAnelDoTelefone(segredos: {
  getRing(ref: string): Promise<SecretRingTuple>;
}): Promise<AnelDoTelefone> {
  return anelDoTelefone(await segredos.getRing("kek_telefone_do_caso"));
}

function exigirCaso(caso: CasoDoTelefone): { tenant: string; onboarding: string } {
  const tenant = typeof caso.tenantId === "string" ? caso.tenantId.toLowerCase() : "";
  const onboarding = typeof caso.onboardingId === "string" ? caso.onboardingId.toLowerCase() : "";
  if (!UUID_CANONICO.test(tenant) || !UUID_CANONICO.test(onboarding)) {
    throw new TelefoneCifradoInvalidoError("o tenant_id ou o onboarding_id nao e um UUID canonico");
  }
  return { tenant, onboarding };
}

function dek(kek: Buffer, tenant: string): Buffer {
  const info = Buffer.from(`${DOMINIO_DA_DEK}\0${tenant}`, "utf8");
  return Buffer.from(hkdfSync("sha256", kek, Buffer.alloc(0), info, OCTETOS_DE_CHAVE));
}

/** O contexto autenticado: domínio, tenant, caso, campo e `kid`. */
export function contextoDoTelefone(caso: CasoDoTelefone, kid: string): Buffer {
  const { tenant, onboarding } = exigirCaso(caso);
  return Buffer.from(`${DOMINIO_DA_CIFRA}\0${tenant}\0${onboarding}\0${CAMPO_DO_TELEFONE}\0${kid}`, "utf8");
}

/** Cifra o telefone com a versão actual do anel. Um IV novo por chamada. */
export function cifrarTelefoneDoCaso(
  anel: AnelDoTelefone,
  caso: CasoDoTelefone,
  telefone: Pick<Opaco, "revelar">,
): Buffer {
  const { tenant } = exigirCaso(caso);
  const kek = anel.chaves.get(anel.kid);
  if (kek === undefined) throw new KekDoTelefoneInvalidaError("o anel nao tem a versao actual");
  const octetosDoKid = Buffer.from(anel.kid, "utf8");
  const iv = randomBytes(OCTETOS_DE_IV);
  const cifra = createCipheriv("aes-256-gcm", dek(kek, tenant), iv);
  cifra.setAAD(contextoDoTelefone(caso, anel.kid));
  const corpo = Buffer.concat([cifra.update(telefone.revelar(), "utf8"), cifra.final()]);
  return Buffer.concat([
    Buffer.from([VERSAO_DO_FORMATO, octetosDoKid.byteLength]),
    octetosDoKid,
    iv,
    cifra.getAuthTag(),
    corpo,
  ]);
}

/**
 * Abre o criptograma com a versão da KEK que ele próprio diz. Lança
 * `TelefoneCifradoInvalidoError`; quem quer `null` usa o `lerTelefoneDoCaso`.
 */
export function decifrarTelefoneDoCaso(
  anel: AnelDoTelefone,
  caso: CasoDoTelefone,
  criptograma: Uint8Array,
): TelefoneDoCasoEmClaro {
  const { tenant } = exigirCaso(caso);
  const dados = Buffer.from(criptograma);
  if (dados.byteLength < 2 || dados[0] !== VERSAO_DO_FORMATO) {
    throw new TelefoneCifradoInvalidoError("formato desconhecido");
  }
  const comprimento = dados[1] ?? 0;
  const inicio = 2 + comprimento;
  const cabecalho = inicio + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA;
  if (comprimento === 0 || dados.byteLength <= cabecalho) {
    throw new TelefoneCifradoInvalidoError("o criptograma e mais curto do que o seu cabecalho");
  }
  const kid = dados.subarray(2, inicio).toString("utf8");
  const kek = anel.chaves.get(kid);
  // Sem o `kid` na mensagem: não é segredo, mas também não é preciso para
  // reagir, e o incidente diz-se pelo nome do erro.
  if (kek === undefined) throw new TelefoneCifradoInvalidoError("a versao da KEK que o cifrou nao esta no anel");
  const decifra = createDecipheriv("aes-256-gcm", dek(kek, tenant), dados.subarray(inicio, inicio + OCTETOS_DE_IV));
  decifra.setAAD(contextoDoTelefone(caso, kid));
  decifra.setAuthTag(dados.subarray(inicio + OCTETOS_DE_IV, cabecalho));
  let claro: string;
  try {
    claro = Buffer.concat([decifra.update(dados.subarray(cabecalho)), decifra.final()]).toString("utf8");
  } catch {
    // O mesmo motivo para DEK errada, contexto errado e conteúdo alterado.
    throw new TelefoneCifradoInvalidoError("a autenticacao falhou");
  }
  try {
    return new TelefoneDoCasoEmClaro(claro);
  } catch {
    throw new TelefoneCifradoInvalidoError("o conteudo nao e um telefone");
  }
}

/** As duas colunas do telefone que o `INSERT` do caso escreve juntas. */
export interface ColunasDoTelefone {
  readonly phoneEnc: Buffer;
  readonly phoneHmac: Buffer;
}

/**
 * **O escritor do `phone_enc`**: o telefone verificado de um caso novo, nas duas
 * colunas que o `INSERT` escreve — a cifra, com o caso no contexto, e o HMAC da
 * inscrição que o `Telefone` já cunhou (o do índice de duplicados). O `id` e o
 * `tenant_id` do caso são os que o `INSERT` vai escrever, pré-alocados.
 */
export function colunasDoTelefone(anel: AnelDoTelefone, caso: CasoDoTelefone, telefone: Telefone): ColunasDoTelefone {
  return {
    phoneEnc: cifrarTelefoneDoCaso(anel, caso, telefone),
    phoneHmac: Buffer.from(telefone.hmac, "hex"),
  };
}

/** O `phone_enc` de um caso, sob a RLS do tenant que a ligação tem no contexto. */
export const SQL_TELEFONE_DO_CASO = "SELECT phone_enc FROM platform.onboarding_case WHERE id = $1";

/** A ligação de quem lê: a forma do `pg`. */
export interface LigacaoDeLeitura {
  query(sql: string, parametros?: readonly unknown[]): Promise<{ rows: readonly Record<string, unknown>[] }>;
}

/**
 * **O decifrador**: o telefone do caso, ou `null`.
 *
 * Lê pela ligação que recebe — no consumidor do dono, a do `consumir`, que é
 * `kamba_app` e já tem o `app.tenant_id` do **envelope** no contexto. Por isso
 * um `onboarding_id` de outro tenant devolve zero linhas e `null`, e não o
 * telefone de outro dono. Uma falha da base **sobe**: não é «o caso não tem
 * telefone», é «não se perguntou», e a fila repete.
 */
export function lerTelefoneDoCaso(anel: AnelDoTelefone) {
  return async (bd: LigacaoDeLeitura, caso: CasoDoTelefone): Promise<TelefoneDoCasoEmClaro | null> => {
    if (!UUID_CANONICO.test(String(caso.onboardingId).toLowerCase())) return null;
    const { rows } = await bd.query(SQL_TELEFONE_DO_CASO, [caso.onboardingId]);
    const cifra = rows[0]?.["phone_enc"];
    if (!(cifra instanceof Uint8Array)) return null;
    try {
      return decifrarTelefoneDoCaso(anel, caso, cifra);
    } catch {
      return null;
    }
  };
}

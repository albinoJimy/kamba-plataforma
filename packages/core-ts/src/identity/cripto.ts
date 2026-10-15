/**
 * As primitivas do módulo de identidade: normalizar, pseudonimizar, cifrar (KAM-008).
 *
 * Funções puras, sem base de dados e sem cofre: recebem as chaves como
 * argumento. É aqui que vivem as três decisões de forma do módulo, e todas são
 * ***proposta***:
 *
 * 1. **O HMAC de pesquisa leva o tenant e o tipo dentro.** O `docs/tecnica/06`
 *    §7.2 escreve `HMAC-SHA256(K_lookup[kid], bsuid)`; aqui a mensagem é
 *    `"kamba.identity.v1" ␀ tipo ␀ tenant ␀ valor`. Com o tenant dentro, o mesmo
 *    telefone em dois tenants dá dois HMAC diferentes: quem leia a base inteira
 *    não liga o cliente de uma loja ao de outra, que é o que «o mesmo cliente em
 *    dois tenants é dois contactos» (`docs/tecnica/03` §5.3) promete. Com o tipo
 *    dentro, um BSUID e um telefone nunca colidem. **Continua a ser
 *    pseudonimização, não anonimização** (`docs/tecnica/08` §7.2): com a chave,
 *    o espaço de números angolanos enumera-se em minutos, tenant a tenant.
 * 2. **A cifra é AES-256-GCM com IV aleatório de 96 bits**, e o que se guarda é
 *    `versão(1) ‖ IV(12) ‖ etiqueta(16) ‖ cifra`. O contexto autenticado prende
 *    cada cifra ao tenant, à DEK e ao campo: uma cifra copiada para outra coluna
 *    ou para a linha de outro contacto não abre.
 * 3. **`trunc16` são os primeiros 16 octetos** do HMAC. O `docs/tecnica/06` §8
 *    declara `sujeito_ref bytea`, e é essa a leitura.
 *
 * O comprimento da cifra revela o comprimento do texto (um telefone tem entre 8
 * e 15 algarismos). Não se disfarça: está dito em `docs/identidade.md` §8.
 *
 * **Nenhum erro deste ficheiro contém o valor que recusou.**
 */

import { Buffer } from "node:buffer";
import { createCipheriv, createDecipheriv, createHmac, randomBytes } from "node:crypto";

import { OCTETOS_DE_CHAVE } from "./chaves.ts";

/** Os dois tipos de endpoint (`contact_endpoints.tipo`). */
export const TIPOS = ["bsuid", "telefone"] as const;
export type Tipo = (typeof TIPOS)[number];

/** As colunas cifradas, que entram no contexto autenticado. */
export type CampoCifrado = "bsuid_enc" | "phone_enc";

/** Octetos de um HMAC-SHA256, e o comprimento das colunas `*_hmac`. */
export const OCTETOS_DE_HMAC = 32;
/** Octetos de `sujeito_ref` (`trunc16`). */
export const OCTETOS_DE_SUJEITO_REF = 16;

const DOMINIO_DE_PESQUISA = "kamba.identity.v1";
const DOMINIO_DE_CIFRA = "kamba.identity.enc.v1";
const DOMINIO_DE_EMBRULHO = "kamba.identity.dek.v1";
const VERSAO_DA_CIFRA = 1;
const OCTETOS_DE_IV = 12;
const OCTETOS_DE_ETIQUETA = 16;
/** Tecto do texto a cifrar: um BSUID tem até 131 caracteres (`E1` §3). */
const MAXIMO_DE_TEXTO = 512;

const UUID_CANONICO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TELEFONE = /^\+?([1-9][0-9]{7,14})$/;
// Sem espaços, sem controlo, sem nada fora do ASCII imprimível. A forma que a
// Meta documenta (`E1` §3, CONFIRMADO) é `PT.` seguido de até 128 alfanuméricos;
// não se exige essa forma exacta, para que uma alteração do formato pela Meta
// não se torne em mensagens recusadas. Exige-se só que seja um identificador.
const BSUID = /^[\x21-\x7e]{1,256}$/;

/** Um identificador de contacto com forma inválida. Não repete o valor. */
export class IdentificadorInvalidoError extends Error {
  override readonly name = "IdentificadorInvalidoError";
  readonly campo: string;

  constructor(campo: string, tipo: string, comprimento: number) {
    super(
      `${campo} inválido (recebido: ${tipo} com ${comprimento} caracteres); ` +
        "o valor não é repetido nesta mensagem",
    );
    this.campo = campo;
  }
}

/** Uma cifra que não abre: DEK errada, contexto errado, ou conteúdo alterado. */
export class CifraInvalidaError extends Error {
  override readonly name = "CifraInvalidaError";

  constructor(motivo: string) {
    super(`a cifra não se consegue abrir: ${motivo}`);
  }
}

function recusar(campo: string, valor: unknown): never {
  throw new IdentificadorInvalidoError(
    campo,
    typeof valor,
    typeof valor === "string" ? valor.length : 0,
  );
}

/** O `contact_id` (ou outro UUID) na forma canónica, ou lança. */
export function normalizarUuid(valor: unknown, campo: string): string {
  if (typeof valor === "string") {
    const minusculas = valor.toLowerCase();
    if (UUID_CANONICO.test(minusculas)) return minusculas;
  }
  return recusar(campo, valor);
}

/**
 * O BSUID tal como a Meta o manda, ou lança.
 *
 * **Não se altera nada**: nem caixa, nem espaços. Dois BSUID que diferem na
 * caixa são dois utilizadores, e aparar um espaço era aceitar em silêncio uma
 * entrada que não é a que a Meta mandou.
 */
export function normalizarBsuid(valor: unknown): string {
  if (typeof valor === "string" && BSUID.test(valor)) return valor;
  return recusar("bsuid", valor);
}

/**
 * O telefone em E.164 **sem o `+`**, ou lança.
 *
 * `+244923456789` e `244923456789` são o mesmo número (o `wa_id` da Meta vem
 * sem `+`), e têm de dar o mesmo HMAC. Só algarismos, com o indicativo: um
 * número nacional de nove algarismos não se distingue de um internacional
 * curto, e adivinhar o indicativo era fundir pessoas diferentes.
 */
export function normalizarTelefone(valor: unknown): string {
  if (typeof valor === "string") {
    const encontro = TELEFONE.exec(valor);
    if (encontro?.[1] !== undefined) return encontro[1];
  }
  return recusar("telefone", valor);
}

function exigirChave(chave: Uint8Array, nome: string): void {
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_CHAVE) {
    throw new CifraInvalidaError(`${nome} tem de ter ${OCTETOS_DE_CHAVE} octetos`);
  }
}

/**
 * O HMAC de pesquisa de um identificador **já normalizado**.
 *
 * `tenant` tem de vir na forma canónica: a mesma chave, o mesmo valor e o mesmo
 * tenant escrito de duas maneiras dariam dois HMAC, e o contacto duplicava.
 */
export function hmacDePesquisa(
  chave: Uint8Array,
  tenant: string,
  tipo: Tipo,
  valor: string,
): Buffer {
  exigirChave(chave, "a chave de pesquisa");
  if (!UUID_CANONICO.test(tenant)) recusar("tenant", tenant);
  if (!TIPOS.includes(tipo)) recusar("tipo", tipo);
  if (typeof valor !== "string" || valor.length === 0) recusar(tipo, valor);
  return createHmac("sha256", chave)
    .update(`${DOMINIO_DE_PESQUISA}\0${tipo}\0${tenant}\0`, "utf8")
    .update(valor, "utf8")
    .digest();
}

/** O contexto autenticado de uma cifra: tenant, DEK e campo. */
export function contextoDaCifra(tenant: string, dekId: string, campo: CampoCifrado): Buffer {
  return Buffer.from(`${DOMINIO_DE_CIFRA}\0${campo}\0${tenant}\0${dekId}`, "utf8");
}

/** O contexto autenticado do embrulho de uma DEK: tenant e `dek_id`. */
export function contextoDoEmbrulho(tenant: string, dekId: string): Buffer {
  return Buffer.from(`${DOMINIO_DE_EMBRULHO}\0${tenant}\0${dekId}`, "utf8");
}

/** Uma DEK nova: 32 octetos do gerador do sistema. */
export function novaDek(): Buffer {
  return randomBytes(OCTETOS_DE_CHAVE);
}

/** Cifra `texto` com a DEK. Cada chamada usa um IV novo. */
export function cifrar(dek: Uint8Array, texto: string, contexto: Uint8Array): Buffer {
  exigirChave(dek, "a DEK");
  if (typeof texto !== "string" || texto.length === 0 || texto.length > MAXIMO_DE_TEXTO) {
    throw new CifraInvalidaError("o texto a cifrar está vazio ou é demasiado longo");
  }
  const iv = randomBytes(OCTETOS_DE_IV);
  const cifra = createCipheriv("aes-256-gcm", dek, iv);
  cifra.setAAD(contexto);
  const corpo = Buffer.concat([cifra.update(texto, "utf8"), cifra.final()]);
  return Buffer.concat([Buffer.from([VERSAO_DA_CIFRA]), iv, cifra.getAuthTag(), corpo]);
}

/** Abre uma cifra. Lança `CifraInvalidaError` se a DEK ou o contexto não forem os certos. */
export function decifrar(dek: Uint8Array, cifrado: Uint8Array, contexto: Uint8Array): string {
  exigirChave(dek, "a DEK");
  const cabecalho = 1 + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA;
  if (
    !(cifrado instanceof Uint8Array) ||
    cifrado.length <= cabecalho ||
    cifrado[0] !== VERSAO_DA_CIFRA
  ) {
    throw new CifraInvalidaError("formato desconhecido");
  }
  const dados = Buffer.from(cifrado);
  const decifra = createDecipheriv(
    "aes-256-gcm",
    dek,
    dados.subarray(1, 1 + OCTETOS_DE_IV),
  );
  decifra.setAAD(contexto);
  decifra.setAuthTag(dados.subarray(1 + OCTETOS_DE_IV, cabecalho));
  try {
    return Buffer.concat([decifra.update(dados.subarray(cabecalho)), decifra.final()]).toString(
      "utf8",
    );
  } catch {
    throw new CifraInvalidaError("a autenticação falhou");
  }
}

/**
 * `sujeito_ref = trunc16(HMAC-SHA256(K_época, contact_id))`.
 *
 * Determinístico dentro da época (a mesma chave); entre épocas a chave é outra
 * e o pseudónimo não se liga. Nunca leva telefone nem BSUID: a entrada é o
 * `contact_id` aleatório, pelo que a chave comprometida não deixa enumerar
 * números (`docs/tecnica/06` §7.2).
 */
export function sujeitoRefDe(chaveDeEpoca: Uint8Array, contactId: string): Buffer {
  exigirChave(chaveDeEpoca, "a chave de época");
  const canonico = normalizarUuid(contactId, "contact_id");
  return createHmac("sha256", chaveDeEpoca)
    .update(canonico, "utf8")
    .digest()
    .subarray(0, OCTETOS_DE_SUJEITO_REF);
}

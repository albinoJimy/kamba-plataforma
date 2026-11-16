/**
 * O anel de chaves `[actual, anterior]` com `kid` (KAM-072).
 *
 * Os Detalhes Técnicos do bloco dizem a forma: «`ring = [current, previous]`
 * com `kid`; operações `verify(any)` e `sign(current)`; revogar remove
 * `previous` e regista no `audit_log`». Este ficheiro é a metade **pura** disso:
 * o valor de um anel, as duas operações criptográficas e as transições. Quem
 * guarda o anel e quem regista a transição é o `rotacao.ts`.
 *
 * ## O que já existia, e porque é que este ficheiro não o substitui
 *
 * Os dois consumidores de HMAC do Piloto já aceitam duas chaves: o GWY com
 * `assinaturaValida` (`entrada/assinatura.ts`, KAM-013) e o PAY com
 * `assinaturaVerifica` (`pagamentos/proxypay/verify.ts`, KAM-056). Recebem
 * **valores** e não sabem de `kid` nem de janelas, e está certo que assim seja:
 * um consumidor verifica, não decide quando uma chave deixa de valer. O que
 * faltava era quem decide — e é isso que este módulo traz. `valoresVivos` é a
 * ponte: devolve a lista que esses dois já sabem consumir.
 *
 * ## Três regras
 *
 * 1. **Tempo constante, sem sair ao primeiro acerto.** Calcula-se o HMAC com
 *    todas as chaves vivas antes de decidir, e o acumulador é um número: um `||`
 *    curto-circuitava e dizia, pelo tempo de resposta, qual das duas acertou.
 * 2. **Um `kid` nunca volta.** Rodar para o `kid` da anterior, ou reutilizar o
 *    da actual com outro valor, é recusado: duas chaves com o mesmo `kid`
 *    tornavam ambíguo tudo o que guarda o `kid` ao lado do dado (o
 *    `hmac_key_ver` dos contactos, o criptograma dos *tokens* de cliente).
 * 3. **Nenhum erro, nenhum registo e nenhum `toString` leva um valor.** As
 *    classes de erro deste ficheiro recebem o `kid`, nunca a chave.
 */

import { Buffer } from "node:buffer";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/** A forma de um `kid`: a mesma do `identity/chaves.ts`, para os dois casarem. */
const KID = /^[a-z0-9][a-z0-9_.-]{0,62}$/;

/** Uma versão de um segredo: o identificador e o valor. */
export interface ChaveDoAnel {
  readonly kid: string;
  readonly valor: string;
}

/**
 * O anel de um segredo.
 *
 * `anteriorAte` é o fim da janela de sobreposição: a partir desse instante a
 * anterior deixa de ser viva **para quem verifica**, mesmo que ninguém a tenha
 * ainda retirado do cofre. `null` quer dizer que não há anterior; `undefined`
 * nunca aparece.
 */
export interface Anel {
  readonly actual: ChaveDoAnel;
  readonly anterior: ChaveDoAnel | null;
  readonly anteriorAte: Date | null;
}

/** O `kid` não tem a forma de um identificador. Nunca repete o que recebeu. */
export class KidDoAnelInvalidoError extends Error {
  override readonly name = "KidDoAnelInvalidoError";

  constructor() {
    super("o kid tem de ser minúsculas, algarismos, `_`, `.` ou `-` (1 a 63 caracteres)");
  }
}

/** A chave está vazia. Uma chave vazia deixava qualquer pessoa assinar. */
export class ChaveVaziaError extends Error {
  override readonly name = "ChaveVaziaError";
  readonly kid: string;

  constructor(kid: string) {
    super(`a versão ${kid} está vazia; uma chave vazia não assina nem verifica`);
    this.kid = kid;
  }
}

/** Um `kid` já usado neste anel com outro valor, ou o `kid` da anterior. */
export class KidRepetidoError extends Error {
  override readonly name = "KidRepetidoError";
  readonly kid: string;

  constructor(kid: string) {
    super(`a versão ${kid} já existiu neste anel; uma versão nova tem um kid novo`);
    this.kid = kid;
  }
}

/** `true` se `kid` tem a forma de um identificador de versão. */
export function kidValido(kid: unknown): kid is string {
  return typeof kid === "string" && KID.test(kid);
}

function exigirChave(chave: ChaveDoAnel): ChaveDoAnel {
  if (!kidValido(chave.kid)) throw new KidDoAnelInvalidoError();
  if (typeof chave.valor !== "string" || chave.valor.trim() === "") {
    throw new ChaveVaziaError(chave.kid);
  }
  return chave;
}

/** Um anel com uma só versão: o estado de um segredo que nunca rodou. */
export function anelInicial(actual: ChaveDoAnel): Anel {
  return { actual: exigirChave(actual), anterior: null, anteriorAte: null };
}

/**
 * A anterior ainda vale em `agora`?
 *
 * Fecha no limite: em `anteriorAte` exacto já não vale. É a direcção certa
 * para errar, porque a janela é uma concessão e não uma garantia.
 */
export function anteriorViva(anel: Anel, agora: Date): boolean {
  return (
    anel.anterior !== null &&
    anel.anteriorAte !== null &&
    agora.getTime() < anel.anteriorAte.getTime()
  );
}

/** As chaves que verificam em `agora`, a actual primeiro. */
export function chavesVivas(anel: Anel, agora: Date): readonly ChaveDoAnel[] {
  return anteriorViva(anel, agora) && anel.anterior !== null
    ? [anel.actual, anel.anterior]
    : [anel.actual];
}

/**
 * Os **valores** vivos, na forma que os dois consumidores existentes recebem:
 * `assinaturaValida` do GWY e `assinaturaVerifica` do PAY.
 */
export function valoresVivos(anel: Anel, agora: Date): readonly string[] {
  return chavesVivas(anel, agora).map((chave) => chave.valor);
}

/**
 * Roda o anel: a nova passa a actual e a actual passa a anterior até
 * `agora + janelaMs`.
 *
 * **Idempotente**: rodar para a versão que já é a actual, com o mesmo valor,
 * devolve o mesmo anel — é o que torna seguro repetir uma rotação que caiu a
 * meio. Com o mesmo `kid` e outro valor, ou com o `kid` da anterior, recusa.
 *
 * A comparação do valor, quando o `kid` coincide, é em tempo constante: é o
 * único sítio deste ficheiro onde se comparam dois valores de chave.
 */
export function rodar(anel: Anel, nova: ChaveDoAnel, agora: Date, janelaMs: number): Anel {
  exigirChave(nova);
  if (!Number.isFinite(janelaMs) || janelaMs < 0) {
    throw new RangeError("a janela tem de ser um número de milissegundos não negativo");
  }
  if (nova.kid === anel.actual.kid) {
    if (valoresIguais(nova.valor, anel.actual.valor)) return anel;
    throw new KidRepetidoError(nova.kid);
  }
  if (anel.anterior !== null && nova.kid === anel.anterior.kid) {
    throw new KidRepetidoError(nova.kid);
  }
  return {
    actual: nova,
    anterior: anel.actual,
    anteriorAte: new Date(agora.getTime() + janelaMs),
  };
}

/** Retira a anterior. Num anel sem anterior, devolve o mesmo anel. */
export function revogarAnterior(anel: Anel): Anel {
  if (anel.anterior === null) return anel;
  return { actual: anel.actual, anterior: null, anteriorAte: null };
}

/** Igualdade de dois valores sem revelar, pelo tempo, onde diferem. */
function valoresIguais(a: string, b: string): boolean {
  // Compara-se o resumo e não os textos: o `timingSafeEqual` exige o mesmo
  // comprimento, e recusar antes pelo comprimento dizia-o pelo tempo.
  const ra = createHmac("sha256", "kamba-keyring-igualdade").update(a, "utf8").digest();
  const rb = createHmac("sha256", "kamba-keyring-igualdade").update(b, "utf8").digest();
  return timingSafeEqual(ra, rb);
}

/** `HMAC-SHA256(actual, dados)`: assinar é sempre com a actual. */
export function assinar(anel: Anel, dados: Uint8Array): { kid: string; mac: Buffer } {
  const { kid, valor } = anel.actual;
  return { kid, mac: createHmac("sha256", valor).update(dados).digest() };
}

/** O que `verificar` devolve: se acertou e com que versão. */
export interface Verificacao {
  readonly valida: boolean;
  /** O `kid` que acertou, ou `null`. Calculado depois de todas as comparações. */
  readonly kid: string | null;
}

/**
 * `mac` é o HMAC-SHA256 de `dados` com alguma chave viva em `agora`?
 *
 * Um `mac` com comprimento diferente de 32 octetos recusa-se antes de
 * qualquer HMAC: o comprimento de um resumo SHA-256 é público, e o
 * `timingSafeEqual` **levanta** com buffers de tamanhos diferentes.
 */
export function verificar(anel: Anel, dados: Uint8Array, mac: Uint8Array, agora: Date): Verificacao {
  if (mac.byteLength !== 32) return { valida: false, kid: null };
  const recebido = Buffer.from(mac);
  let acertos = 0;
  let indice = -1;
  const vivas = chavesVivas(anel, agora);
  for (let i = 0; i < vivas.length; i += 1) {
    const chave = vivas[i] as ChaveDoAnel;
    const esperado = createHmac("sha256", chave.valor).update(dados).digest();
    const acertou = timingSafeEqual(esperado, recebido) ? 1 : 0;
    acertos |= acertou;
    // Sem ramo: o índice guarda-se por aritmética, para não haver um `if`
    // cujo corpo só corre num dos casos.
    indice = acertou * i + (1 - acertou) * indice;
  }
  return acertos === 1
    ? { valida: true, kid: (vivas[indice] as ChaveDoAnel).kid }
    : { valida: false, kid: null };
}

/** Alfabeto do base32 em minúsculas (RFC 4648 sem preenchimento). */
const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

/**
 * Um `kid` novo: `AAAAMMDD.<8 caracteres de base32>`.
 *
 * A data diz quando a versão nasceu, que é o que um operador quer ler num
 * registo; o sufixo é aleatório para que duas rotações no mesmo dia não
 * colidam. **Base32 e não hexadecimal**: um hexadecimal num *payload* pode
 * casar com a guarda de telefone do `evt_emitir`, e o `kid` vai parar a
 * registos e eventos.
 */
export function novoKid(agora: Date): string {
  const data = agora.toISOString().slice(0, 10).replaceAll("-", "");
  const bytes = randomBytes(5);
  let bits = 0;
  let acumulado = 0;
  let sufixo = "";
  for (const byte of bytes) {
    // A máscara guarda só os bits ainda por consumir (nunca mais de doze).
    acumulado = ((acumulado << 8) | byte) & 0xfff;
    bits += 8;
    while (bits >= 5) {
      sufixo += BASE32[(acumulado >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  return `${data}.${sufixo}`;
}

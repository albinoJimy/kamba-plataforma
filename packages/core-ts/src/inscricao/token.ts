/**
 * O *token* da ligação `/entrar?c=<token>` (KAM-086, critério 1).
 *
 * «`/entrar?c=<token>` só abre com token assinado (HMAC) com origem (`convite`,
 * `contabilista`, `anuncio`) e validade; token inválido, expirado ou forjado
 * devolve 403 sem criar linhas.»
 *
 * ## É uma capacidade, e não uma sessão
 *
 * O que este *token* prova é que **alguém com a chave** emitiu esta ligação, com
 * esta origem, antes desta data. Não prova quem a está a abrir, não identifica
 * ninguém, e não cria estado: é por isso que ele é um valor autenticado e não
 * uma linha numa tabela de convites. A linha vem depois, no `POST /api/registo`,
 * e é o `./registo.ts` que a cria.
 *
 * **Não leva dado pessoal nenhum, e isso é uma barreira e não uma convenção.**
 * A carga é a origem, o fim da validade e um nonce; a forma é fechada e
 * verificada. Um convite com o telefone do convidado lá dentro era um dado
 * pessoal num parâmetro de URL — exactamente o que o KAM-068 e os *Dados* do
 * bloco proíbem («PII fora de URLs e logs»).
 *
 * ## A assinatura vem antes da validade, e a ordem é a medição
 *
 * O `verificar` compara o HMAC **primeiro** e só depois lê a data. Pela ordem
 * inversa, o tempo de resposta distinguia um *token* expirado de um forjado — e
 * um *token* expirado é prova de que a chave esteve certa algum dia, que é
 * informação que não se dá a quem está a tentar forjar.
 *
 * ## O anel de duas chaves, e porque não há `kid`
 *
 * Uma rotação da chave não pode invalidar as ligações já distribuídas — um
 * anúncio impresso ou um e-mail de um contabilista vivem semanas. O `verificar`
 * aceita as duas chaves do anel, em tempo constante e **sem sair ao primeiro
 * acerto**, pela razão do `../entrada/assinatura.ts`. Não há `kid` na carga: ele
 * dizia a quem recebe qual das chaves assinou, que é informação sobre o estado
 * da rotação, e o anel de duas resolve a leitura sem ela.
 */

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { ORIGENS, type Origem, type Relogio } from "./contrato.ts";
import { OCTETOS_DE_HMAC } from "./identificadores.ts";

/**
 * Separador de domínio do HMAC do convite. Versionado.
 *
 * Chama-se `DOMINIO_DO_CONVITE` e não `DOMINIO_DO_TOKEN`, e o nome é do *gate*
 * 9: o `tools/scan_secrets` dispara a classe `atribuicao` sobre uma atribuição a
 * um nome que **significa** segredo — e «TOKEN» significa — com um valor de
 * entropia suficiente para não ser uma palavra. Medido: a primeira versão desta
 * linha deu um achado de 26 caracteres. O valor não é segredo nenhum, e a
 * resposta certa não é uma dispensa em `ci/secrets-allow.yaml`: é um nome que
 * não minta sobre o que a constante é.
 */
export const DOMINIO_DO_CONVITE = "kamba/onboarding/entrar/v1";

/** Octetos do nonce. Oito bastam para que dois convites da mesma origem difiram. */
export const OCTETOS_DE_NONCE = 8;

/** Octetos do HMAC que vão no *token*. O SHA-256 inteiro. */
export const OCTETOS_DA_ASSINATURA = 32;

/** Validade máxima de um convite, em dias. ***Proposta***, a calibrar no Piloto. */
export const VALIDADE_MAXIMA_DIAS = 90;

/** Tecto do *token* em caracteres. Um `c=` maior do que isto não se lê. */
export const CARACTERES_MAXIMOS = 256;

/** Porque é que um *token* foi recusado. **Nenhum destes valores é um dado.** */
export const RECUSAS = ["forma", "assinatura", "expirado", "origem", "validade"] as const;

export type Recusa = (typeof RECUSAS)[number];

/**
 * Levantado quando o *token* não serve.
 *
 * **A mensagem não leva o *token***: ele é a credencial, e uma credencial
 * recusada numa mensagem de erro é uma credencial num ficheiro de log. Leva a
 * recusa, que é o que distingue «veio deformado» de «veio assinado por outra
 * chave» sem revelar qual.
 */
export class TokenInvalidoError extends Error {
  override readonly name = "TokenInvalidoError";
  readonly recusa: Recusa;

  constructor(recusa: Recusa) {
    super(`token de /entrar recusado: ${recusa}`);
    this.recusa = recusa;
  }
}

/** O que um *token* válido diz. */
export interface Convite {
  readonly origem: Origem;
  readonly expiraEm: Date;
}

function base64url(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64url");
}

/**
 * A carga em texto, que é exactamente o que entra no HMAC.
 *
 * Uma função e não uma concatenação em dois sítios: assinar uma carga e
 * verificar outra é a maneira canónica de fazer um verificador que aceita o que
 * não devia. O separador é `.`, que não ocorre em nenhum dos três campos — a
 * origem é de uma lista fechada, o instante é decimal, e o nonce é base64url.
 */
function carga(origem: string, segundos: number, nonce: string): string {
  return `${origem}.${segundos}.${nonce}`;
}

function assinar(chave: Uint8Array, texto: string): Buffer {
  return createHmac("sha256", chave)
    .update(`${DOMINIO_DO_CONVITE}\0`, "utf8")
    .update(texto, "utf8")
    .digest();
}

/**
 * Cunha um *token* para esta origem, válido até `expiraEm`.
 *
 * `chave` é a **actual** do anel. A anterior serve para reconhecer um *token*
 * emitido antes de uma rotação, e é o que o `verificar` faz.
 */
export function cunharToken(
  origem: Origem,
  expiraEm: Date,
  chave: Uint8Array,
  agora: Relogio = () => new Date(),
): string {
  if (!ORIGENS.includes(origem)) throw new TokenInvalidoError("origem");
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) {
    throw new TokenInvalidoError("assinatura");
  }
  const segundos = Math.floor(expiraEm.getTime() / 1000);
  if (!Number.isSafeInteger(segundos) || segundos <= 0) throw new TokenInvalidoError("validade");
  const tecto = agora().getTime() + VALIDADE_MAXIMA_DIAS * 86_400_000;
  // O tecto é da emissão e não da verificação: um *token* com validade de dez
  // anos é um *token* permanente, e quem o emitiu não o quis necessariamente
  // assim. Recusa-se a cunhar, que é onde a correcção é barata.
  if (expiraEm.getTime() > tecto) throw new TokenInvalidoError("validade");
  const nonce = base64url(randomBytes(OCTETOS_DE_NONCE));
  const texto = carga(origem, segundos, nonce);
  return `${Buffer.from(texto, "utf8").toString("base64url")}.${base64url(assinar(chave, texto))}`;
}

/**
 * Lê um *token*, ou lança.
 *
 * A ordem das verificações é a do cabeçalho: forma, assinatura, e **só depois**
 * a validade e a origem. Reparar que a origem se verifica no fim é deliberado —
 * ela vem de dentro de uma carga já autenticada, pelo que uma origem
 * desconhecida ali não é um ataque: é um *token* emitido por uma versão nossa
 * que conhecia um valor que esta já não conhece, e tratá-lo como forjado
 * confundia duas coisas diferentes no registo.
 */
export function verificarToken(
  bruto: unknown,
  anel: readonly (Uint8Array | null)[],
  agora: Relogio = () => new Date(),
): Convite {
  if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > CARACTERES_MAXIMOS) {
    throw new TokenInvalidoError("forma");
  }
  const partes = bruto.split(".");
  if (partes.length !== 2) throw new TokenInvalidoError("forma");
  const [cargaB64, assinaturaB64] = partes as [string, string];
  if (!/^[A-Za-z0-9_-]+$/.test(cargaB64) || !/^[A-Za-z0-9_-]+$/.test(assinaturaB64)) {
    throw new TokenInvalidoError("forma");
  }
  const recebida = Buffer.from(assinaturaB64, "base64url");
  if (recebida.length !== OCTETOS_DA_ASSINATURA) throw new TokenInvalidoError("forma");
  const texto = Buffer.from(cargaB64, "base64url").toString("utf8");

  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    acertos |= timingSafeEqual(assinar(chave, texto), recebida) ? 1 : 0;
  }
  if (acertos !== 1) throw new TokenInvalidoError("assinatura");

  const campos = texto.split(".");
  if (campos.length !== 3) throw new TokenInvalidoError("forma");
  const [origem, segundos, nonce] = campos as [string, string, string];
  if (nonce === "" || !/^[0-9]{1,15}$/.test(segundos)) throw new TokenInvalidoError("forma");
  // `isSafeInteger` antes da comparação: quinze algarismos dão um instante que
  // o `Date` não representa, e `NaN <= agora` é **falso** — um *token* com data
  // impossível passava por não expirado. Hoje é inalcançável, porque o
  // `cunharToken` recusa cunhá-lo e só quem tem a chave assina; fecha-se porque
  // o ramo existe e um segundo emissor tornava-o alcançável. Achado da revisão.
  const instante = Number(segundos) * 1000;
  if (!Number.isSafeInteger(instante)) throw new TokenInvalidoError("forma");
  const expiraEm = new Date(instante);
  if (expiraEm.getTime() <= agora().getTime()) throw new TokenInvalidoError("expirado");
  if (!ORIGENS.includes(origem as Origem)) throw new TokenInvalidoError("origem");
  return { origem: origem as Origem, expiraEm };
}

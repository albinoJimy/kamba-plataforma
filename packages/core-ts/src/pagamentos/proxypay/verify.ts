/**
 * A assinatura do callback RPS e a leitura do pagamento (KAM-056, criterio 2).
 *
 * «`verifyCallback` valida `X-Signature = hex(HMAC-SHA256(API_KEY, corpo cru))`
 * em tempo constante com chave corrente ou anterior (janela de duas chaves);
 * 1 byte alterado devolve 401 e `hmac_invalido`.»
 *
 * O formato da assinatura e **CONFIRMADO** (`evidencia/E2` §1.2): cabecalho
 * `X-Signature`, `HexEncode(HMAC-SHA-256(API_KEY, corpo bruto))`. O 401 e o
 * `hmac_invalido` nao sao deste ficheiro: este levanta `AuthError`, e e o
 * `hooks.ts` (KAM-053) que o traduz para os dois.
 *
 * ## Tempo constante, e onde ele acaba
 *
 * A comparacao e `timingSafeEqual` sobre os 32 bytes do HMAC, nunca `===` sobre
 * texto. E calcula-se o HMAC com **todas** as chaves da janela antes de decidir
 * — um `some` que parasse na primeira dizia, pelo tempo, se a assinatura era da
 * chave corrente ou da anterior. O que **nao** e constante, e fica dito: uma
 * assinatura com forma errada (comprimento ou caracteres nao hexadecimais)
 * recusa-se antes do HMAC. Isso so revela a forma, que e publica.
 *
 * ## O corpo do pagamento: o que e CONFIRMADO e o que nao e
 *
 * CONFIRMADO em `E2` §1.2: o pagamento traz `entity_id`, `fee`,
 * `terminal_type`, `terminal_transaction_id`, `terminal_location`,
 * `terminal_id`; os `custom_fields` da referencia sao copiados para ele; e
 * deduplica-se «por id do pagamento».
 *
 * **NAO VERIFICADO**, e lido aqui como hipotese ate ao *sandbox* (`ext:KAM-103`):
 *
 *     id, reference_id   o nome dos campos e que podem vir como numero JSON
 *     amount, fee        que chegam como texto `decimal2`
 *     datetime           o nome do campo do instante do pagamento
 *     o corpo            que o callback e o objecto do pagamento, sem envelope
 *
 * Cada hipotese **falha fechada**: um campo que nao tenha a forma esperada da
 * `VALIDATION`, e o callback fica no *inbox* em `erro` em vez de virar um
 * pagamento com um valor adivinhado. O caso que mais importa e o `amount` como
 * numero JSON: o `JSON.parse` ja o teria passado por virgula flutuante, e o
 * `dinheiro.ts` mede que isso perde um centimo em cada vinte e dois valores.
 * Recusa-se em vez de se converter.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import { minorDeDecimal2 } from "../dinheiro.ts";
import { AuthError, type Minor, ProviderError, type VerifiedEvent } from "../tipos.ts";

/** O cabecalho da assinatura, em minusculas (os cabecalhos HTTP nao distinguem). */
export const CABECALHO_X_SIGNATURE = "x-signature";

/** Bytes de um HMAC-SHA256; em hexadecimal sao o dobro. */
const BYTES_DO_HMAC = 32;
const HEXADECIMAL = /^[0-9a-fA-F]+$/;

/** A assinatura de um corpo, na forma do §3.3. */
export function assinaturaRps(corpo: Uint8Array, chave: string): string {
  return createHmac("sha256", chave).update(corpo).digest("hex");
}

/**
 * A assinatura `recebida` verifica com alguma das `chaves`?
 *
 * Calcula com todas antes de responder (ver o cabecalho). Uma lista vazia de
 * chaves e `false`: sem chave nao ha verificacao, e nao ha excepcao a isso.
 *
 * **Uma chave vazia nao conta.** Um cofre que devolva `""` — uma variavel de
 * ambiente por definir — deixava qualquer pessoa calcular o HMAC e forjar o
 * callback. Ignora-se, e se nao sobrar nenhuma a resposta e `false`.
 */
export function assinaturaVerifica(
  corpo: Uint8Array,
  recebida: string,
  chaves: readonly string[],
): boolean {
  if (recebida.length !== BYTES_DO_HMAC * 2 || !HEXADECIMAL.test(recebida)) return false;
  const esperada = Buffer.from(recebida, "hex");
  const validas = chaves.filter(chaveUtilizavel);
  let alguma = false;
  for (const chave of validas) {
    const calculada = createHmac("sha256", chave).update(corpo).digest();
    // A comparacao fica a esquerda do `||`: corre sempre, e nenhuma chave salta.
    alguma = timingSafeEqual(calculada, esperada) || alguma;
  }
  return validas.length > 0 && alguma;
}

/** Uma chave com que se pode assinar: nao vazia, e nao so espacos. */
export function chaveUtilizavel(chave: string): boolean {
  return chave.trim().length > 0;
}

/** O valor de um cabecalho, sem distinguir maiusculas. */
export function cabecalho(
  cabecalhos: Readonly<Record<string, string>>,
  nome: string,
): string | undefined {
  for (const [chave, valor] of Object.entries(cabecalhos)) {
    if (chave.toLowerCase() === nome) return valor;
  }
  return undefined;
}

/**
 * Verifica e levanta `AuthError` se nao verificar. E o G1 do §5.
 *
 * A mensagem nao diz qual chave falhou nem porque: quem forja nao precisa de
 * pistas, e quem depura tem o *inbox* com o corpo (o `hooks.redigir` tira o
 * `X-Signature` antes de o gravar).
 */
export function exigirAssinatura(
  corpo: Uint8Array,
  cabecalhos: Readonly<Record<string, string>>,
  chaves: readonly string[],
): void {
  const recebida = cabecalho(cabecalhos, CABECALHO_X_SIGNATURE);
  if (recebida === undefined) {
    throw new AuthError("callback sem o cabecalho X-Signature (docs/tecnica/04 §3.3)");
  }
  if (!assinaturaVerifica(corpo, recebida, chaves)) {
    throw new AuthError(
      "a assinatura do callback nao verifica com a chave actual nem com a anterior " +
        "(docs/tecnica/04 §3.3)",
    );
  }
}

/** Um pagamento RPS, lido do corpo. Mais rico do que o `VerifiedEvent`. */
export type PagamentoRps = {
  readonly id: string;
  readonly referencia: string;
  readonly valor: Minor;
  readonly fee?: Minor;
  readonly ocorridoEm: string;
  /** `entity_id`: o G2 do §5 compara-o com a entidade da conta. */
  readonly entidade?: string;
  /** `custom_fields.charge`: o G5 do §5 compara-o com o `chargeId`. */
  readonly chargeId?: string;
  readonly terminal: Readonly<Record<string, string>>;
};

const CAMPOS_DE_TERMINAL = [
  "terminal_type",
  "terminal_transaction_id",
  "terminal_location",
  "terminal_id",
] as const;

/** Le um corpo JSON cru. Uma forma errada e `VALIDATION`, nunca `AuthError`. */
export function lerJson(bytes: Uint8Array): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    // **Nao e `AuthError`**: quando isto corre, a assinatura ja verificou. O
    // corpo e genuino e esta malformado, e confundir os dois mandava investigar
    // um ataque onde ha um defeito do facilitador.
    throw new ProviderError("VALIDATION", "o corpo do facilitador nao e JSON valido");
  }
}

/** Le um objecto de pagamento, venha do callback ou do `GET /payments`. */
export function lerPagamentoRps(lido: unknown): PagamentoRps {
  if (typeof lido !== "object" || lido === null || Array.isArray(lido)) {
    throw new ProviderError("VALIDATION", "o pagamento do facilitador nao e um objecto");
  }
  const p = lido as Record<string, unknown>;
  const id = _identificador(p.id, "id");
  const referencia = _identificador(p.reference_id, "reference_id");
  const valor = _decimal2(p.amount, "amount");
  const ocorridoEm = _instante(p.datetime);
  const campos = p.custom_fields;
  const chargeId =
    typeof campos === "object" && campos !== null && typeof (campos as Record<string, unknown>).charge === "string"
      ? ((campos as Record<string, unknown>).charge as string)
      : undefined;
  const terminal: Record<string, string> = {};
  for (const campo of CAMPOS_DE_TERMINAL) {
    const lidoDoCampo = p[campo];
    if (typeof lidoDoCampo === "string" || typeof lidoDoCampo === "number") {
      terminal[campo] = `${lidoDoCampo}`;
    }
  }
  const entidade =
    p.entity_id === undefined || p.entity_id === null ? undefined : _identificador(p.entity_id, "entity_id");
  return {
    id,
    referencia,
    valor,
    ocorridoEm,
    terminal,
    ...(p.fee === undefined || p.fee === null ? {} : { fee: _decimal2(p.fee, "fee") }),
    ...(entidade === undefined ? {} : { entidade }),
    ...(chargeId === undefined ? {} : { chargeId }),
  };
}

/**
 * O pagamento como `VerifiedEvent`.
 *
 * `authnMethod` diz **por que via** o facto chegou: `hmac` para o callback,
 * `consulta` para a fila autenticada do `GET /payments` (§8: «processar como
 * callback, verificado pela fila autenticada»).
 *
 * O `providerChargeId` leva o `charge` dos `custom_fields` — o `chargeId` que o
 * `createCharge` devolveu nesse mesmo campo —, e e por ele que o *worker* aplica
 * o G5. O `entity_id` do G2 nao cabe no `VerifiedEvent` sem mudar o contrato do
 * KAM-052; o *worker* le-o do corpo guardado no *inbox* com `lerPagamentoRps`.
 *
 * O `providerEventId` e o id do pagamento, prefixado. O prefixo nao e
 * enfeite: a unicidade do KAM-053 e por `(provider, provider_event_id)`, e o
 * mesmo pagamento tem de dar a **mesma** chave pelas duas vias — o callback e
 * a reconciliacao —, senao o G7 deixava o mesmo dinheiro confirmar duas vezes.
 */
export function eventoDoPagamento(p: PagamentoRps, via: "hmac" | "consulta"): VerifiedEvent {
  return {
    providerEventId: `rps:${p.id}`,
    referencia: p.referencia,
    valor: p.valor,
    currency: "AOA",
    authnMethod: via,
    ocorridoEm: p.ocorridoEm,
    ...(p.chargeId === undefined ? {} : { providerChargeId: p.chargeId }),
    ...(p.fee === undefined ? {} : { fee: p.fee }),
  };
}

/** O id do pagamento no facilitador, a partir do `providerEventId`. */
export function idDoPagamento(providerEventId: string): string {
  if (!providerEventId.startsWith("rps:")) {
    throw new ProviderError("VALIDATION", "o evento nao e um pagamento RPS");
  }
  return providerEventId.slice("rps:".length);
}

/**
 * O que vai para `payment_events.payload` (criterio 7: «um `fee` do evento e
 * guardado em `payload.fee`»).
 *
 * O `fee` vai em **unidade menor**, como texto: o dicionario §2 fixa dinheiro
 * em `*_minor` inteiro, e um JSON com o numero `1500` voltava a passar por
 * virgula flutuante em quem o lesse com `JSON.parse`. Sem PII: o pagamento RPS
 * nao traz pagador, e os campos de terminal sao do ATM ou do banco.
 */
export function payloadDoPagamento(p: PagamentoRps): Readonly<Record<string, unknown>> {
  return {
    ...(p.fee === undefined ? {} : { fee: `${p.fee}` }),
    ...(p.entidade === undefined ? {} : { entity_id: p.entidade }),
    ...p.terminal,
  };
}

/**
 * Um identificador do facilitador como texto.
 *
 * Um numero JSON so se aceita se for inteiro **seguro**: acima de 2^53 o
 * `JSON.parse` arredonda, e dois pagamentos diferentes podiam ficar com o mesmo
 * id — o G7 descartava o segundo como duplicado, que e perder um pagamento.
 */
function _identificador(lido: unknown, campo: string): string {
  if (typeof lido === "string" && lido.length > 0 && lido.length <= 64) return lido;
  if (typeof lido === "number" && Number.isSafeInteger(lido) && lido >= 0) return `${lido}`;
  throw new ProviderError(
    "VALIDATION",
    `o campo '${campo}' do pagamento nao e um identificador (texto, ou inteiro abaixo de 2^53)`,
  );
}

function _decimal2(lido: unknown, campo: string): Minor {
  if (typeof lido !== "string") {
    throw new ProviderError(
      "VALIDATION",
      `o campo '${campo}' do pagamento nao e texto decimal2: um numero JSON ja passou ` +
        "por virgula flutuante, e nao se converte num caminho de dinheiro",
    );
  }
  try {
    return minorDeDecimal2(lido);
  } catch {
    throw new ProviderError("VALIDATION", `o campo '${campo}' do pagamento nao tem a forma decimal2`);
  }
}

/** ISO-8601 com fuso. Devolve-se a cadeia lida, normalizada para UTC. */
function _instante(lido: unknown): string {
  if (typeof lido !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(lido)) {
    throw new ProviderError("VALIDATION", "o campo 'datetime' do pagamento nao e um instante ISO-8601");
  }
  const ms = Date.parse(lido);
  if (Number.isNaN(ms)) {
    throw new ProviderError("VALIDATION", "o campo 'datetime' do pagamento nao e um instante valido");
  }
  return new Date(ms).toISOString();
}

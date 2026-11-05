/**
 * A porta `SmsProvider` (KAM-116).
 *
 * Isto é o contrato, e mais nada: não há aqui HTTP, nem cofre, nem agregador.
 * O `FakeSmsProvider` vive em `fake.ts`, e o adaptador do agregador escolhido
 * **não existe** — a escolha é do fundador e não está feita (ver `fornecedor.ts`
 * e `../../../../docs/evidencia/KAM-116.md`). A suite de contrato
 * (`tests/sms.contrato.test.ts`) corre a mesma bateria sobre qualquer
 * implementação, que é o que torna «trocar de agregador é configuração» uma
 * afirmação verificável em vez de uma intenção.
 *
 * ## Porque é que esta porta existe antes do agregador
 *
 * O onboarding tem de provar a posse do telefone do dono **antes de existir
 * número ligado** (`../../../../docs/tecnica/10` §4.1, passo 2), e o canal não
 * pode ser o WhatsApp da KAMBÁ: ele está vedado até D2 e D10, e o D10 é
 * precisamente a decisão aberta sobre ter número operacional próprio. O Piloto
 * usa SMS por agregador local; o KAM-086 liga esta porta ao `OtpProvider`
 * (`sms_local`) e o KAM-115 usa-a como `SmsNotifier`.
 *
 * **O OTP por WhatsApp não é assumido.** Entra como alternativa condicionada a
 * D10 e ao KAM-101, e o fluxo do KAM-086 não muda por causa dela.
 *
 * ## Três coisas que este ficheiro faz de propósito
 *
 * 1. **Os nomes dos métodos são os do critério 5, em inglês.** `send`, `status`
 *    e `onDeliveryReceipt`. O resto do módulo é português, como o conjunto; a
 *    assinatura não é, porque o critério de aceitação a escreve assim e
 *    traduzi-la fazia a caixa deixar de ser verificável à letra.
 * 2. **O código do OTP nunca é uma `string` nesta porta.** É um `CodigoOtp`, e
 *    a razão está em `codigo.ts`: um `string` passa por `${}`, por
 *    `JSON.stringify` e por `console.log` sem resistência, e o critério 6 diz
 *    que ele «nunca aparece em logs, traces ou métricas». Uma convenção não
 *    impede um `${}`; um tipo cujo `toString` devolve a máscara impede-o.
 * 3. **O destino também não é uma `string` solta.** É um `Destino` cunhado em
 *    `destino.ts`, que só aceita `+244` e guarda o HMAC ao lado do número — o
 *    número fica em memória, e o que vai para qualquer registo é o HMAC.
 *
 * ## O que esta porta não tem, e porque
 *
 * Não tem `cancel`, não tem `listar`, não tem consulta por destino. Um
 * agregador que não está escolhido não tem superfície conhecida, e desenhar
 * operações sem consumidor é desenho especulativo — a mesma razão pela qual a
 * `SecretProvider` do KAM-010 não tem escrita (`../secrets/port.ts`).
 */

import type { CodigoOtp } from "./codigo.ts";
import type { Destino } from "./destino.ts";
import type { NomeDeModelo, Parametros } from "./modelos.ts";

/**
 * Os três erros tipados do critério 5.
 *
 * A lista é fechada, e a diferença entre eles **não é cosmética**: decide se
 * quem chama pode repetir. É a lição que o `../agr/shim.ts` escreveu para o
 * AGR — um 400 retentado gasta a escada de tentativas num corpo que nunca
 * melhora, e um 503 não retentado perde o pedido.
 */
export const CODIGOS_DE_ERRO = ["RATE_LIMITED", "INVALID_DESTINATION", "PROVIDER_DOWN"] as const;

export type CodigoDeErro = (typeof CODIGOS_DE_ERRO)[number];

/**
 * Quais dos três se repetem, e qual é a resposta certa a cada um.
 *
 *     RATE_LIMITED         repete — o agregador recusou por frequência, e a
 *                          recusa é temporária por definição
 *     PROVIDER_DOWN        repete — mas **com a mesma chave**, porque não se
 *                          sabe se o SMS saiu (ver `idempotencia.ts`)
 *     INVALID_DESTINATION  **não** repete — o número não melhora com o tempo
 */
export const REPETIVEIS: Readonly<Record<CodigoDeErro, boolean>> = {
  RATE_LIMITED: true,
  PROVIDER_DOWN: true,
  INVALID_DESTINATION: false,
};

/**
 * A falha de um envio, com o código tipado.
 *
 * Uma classe só, com `codigo` fechado, e não três classes: quem trata uma falha
 * de SMS trata-as em conjunto (`catch (e) { if (e instanceof SmsError) … }`) e
 * ramifica pelo `codigo`. Três classes obrigavam a três `instanceof` em cada
 * sítio de uso, e a quarta — a que alguém acrescentasse — passava despercebida.
 *
 * **A mensagem nunca leva o destino nem o código do OTP.** Leva o código de
 * erro e, quando o agregador o der, um motivo que o adaptador tem de limitar a
 * texto sem dados pessoais. É a regra 1 da `../secrets/port.ts`, aplicada a
 * outro tipo de segredo.
 */
export class SmsError extends Error {
  /**
   * `string` e não o literal `"SmsError"`.
   *
   * O `DestinoInvalidoError` do `destino.ts` **estende** esta classe — é um
   * `INVALID_DESTINATION` como os outros — e um campo tipado com o literal não
   * se deixa redeclarar numa subclasse (`TS2416`). É a única classe de erro
   * deste módulo com herança, e é por isso a única onde o literal não serve.
   */
  override readonly name: string = "SmsError";
  readonly codigo: CodigoDeErro;
  /** `true` se repetir faz sentido. Derivado de `REPETIVEIS`, não escolhido. */
  readonly repetivel: boolean;

  constructor(codigo: CodigoDeErro, motivo = "") {
    super(motivo === "" ? `envio de SMS recusado: ${codigo}` : `envio de SMS recusado: ${codigo} (${motivo})`);
    this.codigo = codigo;
    this.repetivel = REPETIVEIS[codigo];
  }
}

/**
 * O estado de um envio.
 *
 *     em_curso   entregue ao agregador, sem recibo ainda
 *     entregue   recibo positivo do agregador
 *     falhou     recibo negativo
 *     indeterminado  o agregador não respondeu ao envio; **pode ter saído**
 *
 * O `indeterminado` é o estado que a maior parte das portas de SMS não tem, e é
 * o único honesto para um `PROVIDER_DOWN`: a resposta perdeu-se, não o SMS.
 * Tratá-lo como `falhou` convidava a um segundo envio com chave nova, que é
 * exactamente o SMS a dobrar que o critério 5 proíbe.
 */
export const ESTADOS = ["em_curso", "entregue", "falhou", "indeterminado"] as const;

export type Estado = (typeof ESTADOS)[number];

/** As operadoras que o critério 2 mede, mais a honestidade do que não se sabe. */
export const OPERADORAS = ["unitel", "africell", "desconhecida"] as const;

export type Operadora = (typeof OPERADORAS)[number];

/**
 * O que um envio devolve.
 *
 * `repetido` é o que o ensaio de idempotência lê: a segunda chamada com a mesma
 * chave devolve o **mesmo** `id` com `repetido: true`, e nenhum SMS sai.
 */
export interface ResultadoDeEnvio {
  /** O id do envio do lado do agregador. Opaco: não se parte nem se interpreta. */
  readonly id: string;
  readonly estado: Estado;
  /** `true` quando este resultado veio do registo e não de um envio novo. */
  readonly repetido: boolean;
}

/**
 * Um recibo de entrega, já autenticado e já normalizado.
 *
 * O `idDoFornecedor` é a chave de idempotência do recibo (critério 5): o mesmo
 * recibo entregue duas vezes corre o `handler` **uma**. Os agregadores
 * re-entregam, e um recibo contado duas vezes estraga a `sms_delivery_ratio`
 * antes de estragar qualquer coisa de negócio.
 */
export interface Recibo {
  readonly idDoFornecedor: string;
  readonly estado: Estado;
  readonly operadora: Operadora;
  /** Quando o agregador diz que o estado mudou. */
  readonly em: Date;
  /** Motivo do agregador, já limpo de dados pessoais, ou `null`. */
  readonly motivo: string | null;
}

/** Quem trata um recibo. */
export type OuvinteDeRecibo = (recibo: Recibo) => void | Promise<void>;

/** Desliga um ouvinte registado por `onDeliveryReceipt`. */
export type Desligar = () => void;

/**
 * A porta.
 *
 * Os parâmetros de `send` são os do critério 5, por esta ordem: `destino`,
 * `modelo`, `parametros`, `idempotency_key`.
 */
export interface SmsProvider {
  /** Nome curto da implementação, para métricas e mensagens: `fake`, `<agregador>`. */
  readonly nome: string;

  /**
   * Envia um SMS de um modelo fixo, uma vez por `idempotencyKey`.
   *
   * @throws {SmsError} com `INVALID_DESTINATION`, `RATE_LIMITED` ou `PROVIDER_DOWN`
   */
  send(
    destino: Destino,
    modelo: NomeDeModelo,
    parametros: Parametros,
    idempotencyKey: string,
  ): Promise<ResultadoDeEnvio>;

  /** O estado de um envio pelo `id` que o `send` devolveu. */
  status(id: string): Promise<Estado>;

  /**
   * Registra um ouvinte de recibos. Devolve a função que o desliga.
   *
   * O ouvinte corre **uma vez por `idDoFornecedor`**: a idempotência do recibo
   * é da implementação e não de quem ouve, porque quem ouve é código de
   * negócio e esquecer-se dela é o modo de falha normal.
   */
  onDeliveryReceipt(handler: OuvinteDeRecibo): Desligar;
}

/** Relógio injectável, como nos outros módulos desta casa. */
export type Relogio = () => Date;

/** A chave de idempotência tem de ter forma: opaca, imprimível e sem espaços. */
export const CHAVE = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

/** Levantado quando a chave de idempotência não tem forma de chave. */
export class ChaveInvalidaError extends Error {
  override readonly name = "ChaveInvalidaError";
  /** Comprimento da cadeia recusada. **Nunca o seu conteúdo.** */
  readonly comprimento: number;

  constructor(chave: string) {
    // Comprimento e não conteúdo, pela razão do `SecretRefInvalidaError`: se
    // alguém passou o telefone como chave por engano, o telefone não entra no
    // log por causa desta mensagem.
    super(
      `chave de idempotencia invalida (${chave.length} caracteres); ` +
        "esperava 8 a 128 caracteres de [A-Za-z0-9._:-]",
    );
    this.comprimento = chave.length;
  }
}

/** Valida a forma da chave e devolve-a, para encadear. */
export function validarChave(chave: string): string {
  if (typeof chave !== "string" || !CHAVE.test(chave)) {
    throw new ChaveInvalidaError(typeof chave === "string" ? chave : "");
  }
  return chave;
}

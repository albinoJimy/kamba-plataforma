/**
 * O `FakeSmsProvider` (KAM-116).
 *
 * É o que CI e `staging` usam (critério 8), e é contra ele que a bateria de
 * contrato corre. Implementa `SmsProvider` compondo a ligação de `envio.ts`
 * com uma entrega em memória — **a mesma ligação** que um adaptador do agregador
 * escolhido comporia. É isso que torna a bateria de contrato transferível: se a
 * idempotência fosse deste ficheiro, o verde dele não dizia nada sobre o
 * adaptador.
 *
 * ## O que ele deixa um ensaio fazer, e porquê cada coisa
 *
 *     enfileirarErro(codigo)   o próximo envio levanta esse erro tipado. É como
 *                              se medem os três códigos do critério 5 sem um
 *                              agregador, e como se mede que o `PROVIDER_DOWN`
 *                              **não** liberta a chave.
 *     entregar(id, …)          dispara o recibo. Separado do envio de propósito:
 *                              um recibo que chegasse dentro do `send` fazia a
 *                              latência medir zero e escondia a idempotência do
 *                              recibo.
 *     enviados                 os corpos compostos, para o ensaio contar **SMS**
 *                              e não chamadas. É o número que o critério 5 mede.
 *
 * ## Os corpos ficam guardados, e isso é deliberado — e limitado ao `fake`
 *
 * O `enviados` guarda o corpo do SMS, que **contém o código do OTP em claro**.
 * Num adaptador real isso seria um defeito grave: o corpo entrega-se e larga-se.
 * Aqui é o instrumento sem o qual o ensaio não consegue afirmar «saiu um SMS, e
 * foi este» — e o ficheiro é `fake.ts`, que nunca corre em `prod` porque o
 * *gate* do `fornecedor.ts` recusa o arranque sem agregador autorizado.
 *
 * Mesmo assim, o `destino` guardado é o **HMAC** e não o número: o ensaio não
 * precisa do número para distinguir destinos, e deixar aqui a porta aberta
 * convidava alguém a copiar este ficheiro para um adaptador.
 */

import type {
  Desligar,
  Estado,
  OuvinteDeRecibo,
  Operadora,
  Recibo,
  Relogio,
  ResultadoDeEnvio,
  SmsProvider,
} from "./contrato.ts";
import { SmsError, type CodigoDeErro } from "./contrato.ts";
import type { Destino } from "./destino.ts";
import { Envios, type Entrega, type OpcoesDeEnvios } from "./envio.ts";
import type { NomeDeModelo, Parametros } from "./modelos.ts";

/**
 * Quantos corpos o `fake` guarda. Ver a nota do `#entregar`.
 *
 * Mil chega para qualquer ensaio desta casa — o maior varre 200 — e põe um
 * tecto no que um `staging` acumula.
 */
export const CORPOS_GUARDADOS = 1_000;

/** Um envio que o `fake` aceitou. */
export interface EnvioFalso {
  readonly id: string;
  /** O **HMAC** do destino, nunca o número. Ver a nota do módulo. */
  readonly destinoHmac: string;
  readonly modelo: NomeDeModelo;
  /** O corpo composto, com o código em claro. Só existe no `fake`. */
  readonly corpo: string;
  readonly chave: string;
}

/** Opções do `fake`. */
export interface OpcoesDoFake extends Omit<OpcoesDeEnvios, "fornecedor"> {
  /** O nome que sai nas etiquetas de métrica. Por omissão `fake`. */
  readonly fornecedor?: string;
}

/**
 * Uma implementação de `SmsProvider` que não fala com ninguém.
 *
 * O `id` de um envio é `fake-<n>`, sequencial e com forma de id de recibo
 * (`ID_DE_RECIBO`): assim o registo de recibos aceita-o, e um ensaio pode usar o
 * `id` do envio como id de recibo, que é o caso normal nos agregadores.
 */
export class FakeSmsProvider implements SmsProvider {
  readonly nome: string;
  readonly #envios: Envios;
  readonly #enviados: EnvioFalso[] = [];
  readonly #errosEnfileirados: CodigoDeErro[] = [];
  readonly #relogio: Relogio;
  #seguinte = 1;

  constructor(opcoes: OpcoesDoFake = {}) {
    this.nome = opcoes.fornecedor ?? "fake";
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
    this.#envios = new Envios({ ...opcoes, fornecedor: this.nome });
  }

  async send(
    destino: Destino,
    modelo: NomeDeModelo,
    parametros: Parametros,
    idempotencyKey: string,
  ): Promise<ResultadoDeEnvio> {
    return this.#envios.enviar(destino, modelo, parametros, idempotencyKey, this.#entregar);
  }

  async status(id: string): Promise<Estado> {
    return this.#envios.estado(id);
  }

  onDeliveryReceipt(handler: OuvinteDeRecibo): Desligar {
    return this.#envios.onDeliveryReceipt(handler);
  }

  /** A entrega em memória. É aqui que um adaptador real falaria com o agregador. */
  readonly #entregar = async (
    destino: Destino,
    corpo: string,
    chave: string,
    modelo: NomeDeModelo,
  ): Promise<Entrega> => {
    const erro = this.#errosEnfileirados.shift();
    if (erro !== undefined) throw new SmsError(erro, "enfileirado pelo FakeSmsProvider");
    const id = `fake-${this.#seguinte}`;
    this.#seguinte += 1;
    // **O tecto não é optimização.** O critério 8 põe o *fake* em `staging`, e
    // um processo de `staging` que corra dias acumulava no *heap* **todos** os
    // códigos de OTP que emitiu. Achado da revisão adversarial: a justificação
    // escrita acima terminava em «nunca corre em `prod`», o que é verdade e
    // insuficiente. Guardam-se os últimos, que é o que um ensaio precisa.
    if (this.#enviados.length >= CORPOS_GUARDADOS) {
      this.#enviados.splice(0, Math.trunc(CORPOS_GUARDADOS / 2));
    }
    // O `modelo` vem de quem enviou e **não é uma constante**: era-o, e no dia
    // em que houvesse um segundo modelo o `enviados` do ensaio mentia sem nada
    // acusar. Achado da revisão adversarial.
    this.#enviados.push({ id, destinoHmac: destino.hmac, modelo, corpo, chave });
    return { id };
  };

  /** O próximo envio levanta este erro tipado. Enfileiram-se vários. */
  enfileirarErro(codigo: CodigoDeErro): void {
    this.#errosEnfileirados.push(codigo);
  }

  /**
   * Dispara um recibo para um envio.
   *
   * `idDoRecibo` por omissão é o `id` do envio, que é o caso normal; passá-lo
   * diferente é como se mede a idempotência do recibo com dois ids distintos
   * para o mesmo envio.
   */
  async entregar(
    id: string,
    opcoes: {
      readonly entregue?: boolean;
      readonly operadora?: Operadora;
      readonly em?: Date;
      readonly motivo?: string | null;
      readonly idDoRecibo?: string;
    } = {},
  ): Promise<boolean> {
    const recibo: Recibo = {
      idDoFornecedor: opcoes.idDoRecibo ?? id,
      estado: (opcoes.entregue ?? true) ? "entregue" : "falhou",
      operadora: opcoes.operadora ?? "desconhecida",
      em: opcoes.em ?? this.#relogio(),
      motivo: opcoes.motivo ?? null,
    };
    return this.#envios.receber(recibo, id);
  }

  /**
   * Entrega um `Recibo` já construído, como um adaptador real faria.
   *
   * O `entregar` acima constrói o recibo por conveniência dos ensaios; este é a
   * ponta que o `receberPedido` do `recibo.ts` chama, e é o que permite exercer
   * a cadeia inteira — autenticar, interpretar, normalizar, entregar — contra o
   * *fake*.
   */
  async receberRecibo(recibo: Recibo, idDoEnvio?: string): Promise<boolean> {
    return this.#envios.receber(recibo, idDoEnvio);
  }

  /** Os envios aceites, pela ordem em que saíram. */
  get enviados(): readonly EnvioFalso[] {
    return this.#enviados;
  }

  /** Quantos SMS saíram. É o número que o ensaio de idempotência lê. */
  get quantosSairam(): number {
    return this.#enviados.length;
  }
}

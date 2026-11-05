/**
 * A ligação: reserva, entrega, recibo e métricas, num sítio só (KAM-116).
 *
 * ## Porque é que isto é uma classe e não três funções soltas
 *
 * Uma função correcta ligada ao sítio errado passa todos os ensaios dela. A
 * idempotência deste módulo não está no `RegistoDeEnvios` — está na **ordem**
 * em que se reserva, entrega, conclui e liberta, e na decisão de qual dos três
 * destinos de uma reserva cabe a cada erro tipado. Se essa ordem viver dentro
 * de cada adaptador, cada adaptador tem a sua, e o ensaio de idempidência do
 * `fake` não diz nada sobre o do agregador.
 *
 * Por isso a ordem vive aqui, uma vez, e o que um adaptador fornece é a função
 * `Entregar` — a chamada ao agregador e mais nada. O `FakeSmsProvider` compõe
 * esta classe com uma entrega em memória; um adaptador do agregador escolhido
 * compõe-na com uma entrega por HTTP. **A ligação é a mesma nos dois**, e é por
 * isso que a bateria de contrato vale para os dois.
 *
 * ## A ordem, e o que cada passo custa se correr trocado
 *
 *     1. valida a chave e **compõe o corpo**      — um parâmetro inválido não
 *                                                   gasta a chave
 *     2. reserva a chave                          — atómico; ver `idempotencia.ts`
 *     3. se já estava reservada, devolve o que     — `repetido: true`, e **nenhum
 *        está guardado                              SMS sai**
 *     4. entrega, com o relógio a correr
 *     5. conclui (aceitou) ou liberta (recusou e    — qual dos dois, por
 *        não enviou) ou deixa em curso (não sei)      `REPETIVEIS` e pelo código
 *
 * Compor o corpo **antes** de reservar é o passo que parece fora de ordem e não
 * está: um `validade_min` a 0 levantaria depois da reserva, e a chave ficava
 * reservada para sempre sobre um envio que nunca aconteceu — a repetição
 * seguinte, agora correcta, devolvia `repetido` sem nunca ter enviado nada.
 *
 * ## Um `PROVIDER_DOWN` não liberta a chave, e é a decisão mais contra-intuitiva
 *
 * O agregador não respondeu. **Pode ter enviado.** Libertar a chave convidava a
 * repetição a enviar o segundo SMS — o SMS a dobrar que o critério 5 proíbe —, e
 * concluir dava um `id` que não existe. Fica em curso: a repetição devolve
 * `estado: "indeterminado"` com `repetido: true` e não envia, e quem resolve é
 * o `status(id)` do agregador ou o recibo que chega atrasado.
 *
 * O `RATE_LIMITED` **liberta**: o agregador respondeu, e a resposta foi «não
 * enviei». O `INVALID_DESTINATION` também, e por mais uma razão — o número não
 * melhora com o tempo, mas quem corrige um dígito e repete tem direito a que a
 * chave nova funcione.
 */

import type {
  Desligar,
  Estado,
  OuvinteDeRecibo,
  Recibo,
  Relogio,
  ResultadoDeEnvio,
} from "./contrato.ts";
import { SmsError, validarChave } from "./contrato.ts";
import type { Destino } from "./destino.ts";
import type { RegistoDeEnvios, RegistoDeRecibos } from "./idempotencia.ts";
import { RegistoDeEnviosEmMemoria, RegistoDeRecibosEmMemoria } from "./idempotencia.ts";
import type { MetricasDeSms } from "./metricas.ts";
import { construir, type NomeDeModelo, type Parametros } from "./modelos.ts";

/** O que uma entrega devolve. O `custoMinor` é em unidade menor de Kz. */
export interface Entrega {
  readonly id: string;
  readonly custoMinor?: bigint;
}

/**
 * A chamada ao agregador, e mais nada.
 *
 * Recebe o corpo **já composto** — nunca os parâmetros — porque compor texto é
 * a responsabilidade do `modelos.ts` e um adaptador que o fizesse outra vez
 * podia compor outro texto. Levanta `SmsError` com o código tipado que
 * corresponde à resposta do agregador.
 */
export type Entregar = (destino: Destino, corpo: string, chave: string) => Promise<Entrega>;

/** Opções de `Envios`. */
export interface OpcoesDeEnvios {
  /** Nome curto do fornecedor, para as etiquetas: `fake`, `<agregador>`. */
  readonly fornecedor: string;
  readonly registo?: RegistoDeEnvios;
  readonly recibosVistos?: RegistoDeRecibos;
  readonly metricas?: MetricasDeSms;
  readonly relogio?: Relogio;
  /**
   * Custo por SMS em unidade menor de Kz, quando o agregador não o devolve.
   *
   * `null` é o valor por omissão e quer dizer «não sei»: **não há cotação**, e o
   * preço por SMS é NÃO VERIFICADO até haver (`../../../../docs/evidencia/KAM-116.md`).
   * Com `null`, a `sms_cost_kz_total` não se move — uma métrica de custo a zero
   * é lida como «barato», e inventar um preço era pior.
   */
  readonly custoMinorPorSms?: bigint | null;
}

/** Quantos instantes de envio se guardam para medir latência. */
export const INSTANTES_GUARDADOS = 10_000;

/**
 * A ligação entre a porta e um agregador.
 *
 * Não implementa `SmsProvider`: fornece as três operações dele a quem
 * implementa. A diferença importa — um `SmsProvider` tem um `send` com a
 * assinatura do critério 5, e esta classe tem um `enviar` que leva também a
 * função de entrega.
 */
export class Envios {
  readonly fornecedor: string;
  readonly #registo: RegistoDeEnvios;
  readonly #recibosVistos: RegistoDeRecibos;
  readonly #metricas: MetricasDeSms | null;
  readonly #relogio: Relogio;
  readonly #custoMinorPorSms: bigint | null;
  readonly #ouvintes = new Set<OuvinteDeRecibo>();
  /** `id` do agregador para o instante do envio, em ms, para a latência. */
  readonly #enviadoEm = new Map<string, number>();
  readonly #estados = new Map<string, Estado>();

  constructor(opcoes: OpcoesDeEnvios) {
    this.fornecedor = opcoes.fornecedor;
    this.#registo = opcoes.registo ?? new RegistoDeEnviosEmMemoria();
    this.#recibosVistos = opcoes.recibosVistos ?? new RegistoDeRecibosEmMemoria();
    this.#metricas = opcoes.metricas ?? null;
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
    this.#custoMinorPorSms = opcoes.custoMinorPorSms ?? null;
  }

  /** Envia uma vez por chave. Ver a ordem na nota do módulo. */
  async enviar(
    destino: Destino,
    modelo: NomeDeModelo,
    parametros: Parametros,
    idempotencyKey: string,
    entregar: Entregar,
  ): Promise<ResultadoDeEnvio> {
    const chave = validarChave(idempotencyKey);
    // Passo 1: compor antes de reservar. Ver a nota do módulo.
    const corpo = construir(modelo, parametros);

    const reserva = await this.#registo.reservar(chave);
    if (!reserva.novo) {
      this.#metricas?.contarEnvio(this.fornecedor, "repetido");
      const guardado = reserva.registo;
      return guardado === null
        ? { id: "", estado: "indeterminado", repetido: true }
        : { id: guardado.id, estado: guardado.estado, repetido: true };
    }

    const inicio = this.#relogio().getTime();
    let entrega: Entrega;
    try {
      entrega = await entregar(destino, corpo, chave);
    } catch (erro) {
      const codigo = erro instanceof SmsError ? erro.codigo : "PROVIDER_DOWN";
      // Um erro que **não** é um `SmsError` conta como `PROVIDER_DOWN` e não
      // liberta: um adaptador que rebenta com um `TypeError` a meio de um
      // `fetch` pode ter mandado o pedido. A direccao certa para falhar e a que
      // nao manda o segundo SMS.
      if (codigo !== "PROVIDER_DOWN") await this.#registo.libertar(chave);
      this.#metricas?.contarEnvio(this.fornecedor, codigo);
      throw erro;
    }

    this.#lembrarInstante(entrega.id, inicio);
    this.#estados.set(entrega.id, "em_curso");
    await this.#registo.concluir(chave, { id: entrega.id, estado: "em_curso" });
    this.#metricas?.contarEnvio(this.fornecedor, "aceite");
    const custo = entrega.custoMinor ?? this.#custoMinorPorSms;
    if (custo !== null && custo !== undefined) {
      this.#metricas?.acumularCusto(this.fornecedor, custo);
    }
    return { id: entrega.id, estado: "em_curso", repetido: false };
  }

  /** O estado conhecido de um envio. `indeterminado` quando o `id` não é nosso. */
  estado(id: string): Estado {
    return this.#estados.get(id) ?? "indeterminado";
  }

  /** Registra um ouvinte de recibos. Devolve a função que o desliga. */
  onDeliveryReceipt(handler: OuvinteDeRecibo): Desligar {
    this.#ouvintes.add(handler);
    return (): void => {
      this.#ouvintes.delete(handler);
    };
  }

  /**
   * Trata um recibo **já autenticado** (ver `recibo.ts`), uma vez por id.
   *
   * Devolve `true` se correu os ouvintes, `false` se o recibo era repetido. A
   * repetição não é erro — os agregadores re-entregam, e é para isso que o
   * registo de recibos existe.
   *
   * A latência observa-se aqui e **só para o primeiro** recibo de um envio: um
   * recibo repetido observado duas vezes punha o mesmo valor no histograma
   * duas vezes, e o `_count` deixava de ser o número de entregas.
   */
  async receber(recibo: Recibo, idDoEnvio?: string): Promise<boolean> {
    if (!(await this.#recibosVistos.primeiraVez(recibo.idDoFornecedor))) return false;

    const id = idDoEnvio ?? recibo.idDoFornecedor;
    if (this.#estados.has(id)) this.#estados.set(id, recibo.estado);

    const inicio = this.#enviadoEm.get(id);
    if (inicio !== undefined) {
      this.#enviadoEm.delete(id);
      this.#metricas?.observarLatencia(this.fornecedor, (recibo.em.getTime() - inicio) / 1000);
    }
    this.#metricas?.contarRecibo(this.fornecedor, recibo.operadora, recibo.estado === "entregue");

    for (const ouvinte of this.#ouvintes) await ouvinte(recibo);
    return true;
  }

  /**
   * Guarda o instante do envio, com tecto.
   *
   * Sem tecto, um processo que receba recibos de uma fracção dos envios acumula
   * instantes para sempre — e a fuga aparece como o serviço a morrer sem razão
   * aparente. É o mesmo tecto, e a mesma razão, do `RegistoDeRecibosEmMemoria`.
   */
  #lembrarInstante(id: string, ms: number): void {
    if (this.#enviadoEm.size >= INSTANTES_GUARDADOS) {
      let aDeitar = Math.trunc(INSTANTES_GUARDADOS / 2);
      for (const antigo of this.#enviadoEm.keys()) {
        if (aDeitar-- <= 0) break;
        this.#enviadoEm.delete(antigo);
      }
    }
    this.#enviadoEm.set(id, ms);
  }
}

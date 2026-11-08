/**
 * O tempo de actividade do dono (KAM-086, critério 10).
 *
 * «`owner_active_seconds` acumula por *heartbeat* de 30 s (intervalos > 5 min
 * não contam); não regista teclas nem conteúdo.»
 *
 * ## O que se mede, e o que **não** se pode medir
 *
 * Mede-se quanto tempo o dono teve a página aberta e a responder. É o número que
 * diz se o registo leva cinco minutos ou vinte e cinco, e é a medição que a
 * hipótese do tempo de onboarding precisa. **Não** se mede o que ele escreveu,
 * nem quando, nem quantas vezes apagou um campo: a assinatura do `bater` leva um
 * `onboarding_id` e mais nada, e é essa ausência de parâmetros que torna o «não
 * regista teclas nem conteúdo» verificável por leitura em vez de por promessa.
 *
 * ## O servidor soma o tempo que passou, e não o que o cliente diz
 *
 * A diferença é a que separa uma medição de um número reportado. O cliente bate
 * a cada trinta segundos; o que se soma é o **tempo decorrido desde a batida
 * anterior**, lido do relógio do servidor. Consequência, e é a propriedade que
 * vale a pena escrever: o acumulado **nunca pode passar o tempo de parede**, faça
 * o cliente o que fizer. Mil batidas num segundo somam um segundo. Um cliente
 * que mandasse «mais trinta segundos» a cada pedido inflacionava o número à
 * vontade, e o número deixava de servir para decidir nada.
 *
 * ## O intervalo máximo é o que distingue «a pensar» de «foi almoçar»
 *
 * Uma pausa de dois minutos é o dono a procurar o NIF numa gaveta, e conta. Uma
 * pausa de meia hora é um separador aberto e esquecido, e não conta — somá-la
 * dava um tempo médio de onboarding feito de abandonos. O corte é de cinco
 * minutos (*proposta* do critério) e a batida que o excede **não soma nada**, em
 * vez de somar o tecto: somar o tecto fazia um separador esquecido durante um
 * dia contribuir com cinco minutos por batida.
 */

import type { Contadores, RepositorioDeCasos, Relogio } from "./contrato.ts";

/** Período nominal da batida, em segundos. *Proposta* do critério 10. */
export const PERIODO_SEGUNDOS = 30;

/** Intervalo acima do qual a batida não soma nada, em segundos. *Proposta*. */
export const INTERVALO_MAXIMO_SEGUNDOS = 300;

/** As chaves de contagem deste módulo. */
export const CHAVES = {
  batida: (onboardingId: string): string => `actividade:${onboardingId}`,
} as const;

/** O que uma batida devolve. */
export interface Batida {
  /** Segundos somados **por esta** batida. Zero na primeira e após uma ausência. */
  readonly somados: number;
  /** O `owner_active_seconds` depois desta batida. */
  readonly total: number;
}

/** Opções da actividade. */
export interface OpcoesDeActividade {
  readonly repositorio: RepositorioDeCasos;
  readonly contadores: Contadores;
  readonly relogio?: Relogio;
  readonly intervaloMaximoSegundos?: number;
}

/** O acumulador de `owner_active_seconds`. */
export class Actividade {
  readonly #repositorio: RepositorioDeCasos;
  readonly #contadores: Contadores;
  readonly #relogio: Relogio;
  readonly intervaloMaximoSegundos: number;

  constructor(opcoes: OpcoesDeActividade) {
    this.#repositorio = opcoes.repositorio;
    this.#contadores = opcoes.contadores;
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
    this.intervaloMaximoSegundos = opcoes.intervaloMaximoSegundos ?? INTERVALO_MAXIMO_SEGUNDOS;
  }

  /**
   * Uma batida deste caso.
   *
   * `null` se o caso não existe — e não um zero: um zero dizia «o dono esteve
   * parado» sobre um caso que não há, e é o 404 do teste de isolamento do DoD.
   */
  async bater(onboardingId: string): Promise<Batida | null> {
    // O caso lê-se **primeiro**, e um id desconhecido não escreve nada: sem
    // isto, bater com o id do caso B a partir da sessão do caso A criava uma
    // chave de contagem por cada id tentado, e uma rajada de ids inventados
    // enchia a memória do contador. É o mesmo argumento do `./antiabuso.ts`
    // para não contar tentativas.
    const caso = await this.#repositorio.porId(onboardingId);
    if (caso === null) return null;

    const agora = this.#relogio();
    const chave = CHAVES.batida(onboardingId);
    const anterior = await this.#contadores.ultimo(chave);
    // A janela do `registar` é o intervalo máximo: a porta só precisa de guardar
    // a batida anterior, e guardar o histórico de um dia de batidas de 30 s era
    // dez mil instantes por caso em memória, para responder a uma pergunta que
    // só olha para o último.
    await this.#contadores.anotar(chave, agora, this.intervaloMaximoSegundos * 1000);

    const decorridoS =
      anterior === null ? 0 : Math.floor((agora.getTime() - anterior.getTime()) / 1000);
    // O negativo é um relógio que andou atrás, e trata-se como a primeira
    // batida. Nunca se soma um número negativo a um acumulado monótono.
    const somados =
      decorridoS <= 0 || decorridoS > this.intervaloMaximoSegundos ? 0 : decorridoS;

    if (somados === 0) return { somados: 0, total: caso.activoSegundos };
    const total = await this.#repositorio.acumularActivo(onboardingId, somados);
    return { somados, total };
  }
}

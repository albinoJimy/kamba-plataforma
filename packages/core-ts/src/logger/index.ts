/**
 * `@kamba/core-ts/logger` — o único sítio por onde um serviço Node escreve
 * (KAM-068).
 *
 * ```ts
 * import { instalar } from "@kamba/core-ts/logger";
 *
 * const log = instalar("gwy");
 * log.info({ outcome: "service_started" });
 * log.error({ tenant_id, tool: "criar_pedido", outcome: "recusado",
 *             error_code: "stock_insuficiente", latency_ms: 42 });
 * try { ... } catch (erro) { log.excepcao(erro, "callback_invalido", { tenant_id }); }
 * ```
 *
 * Cada chamada escreve **uma linha JSON** com campos da *allowlist* de
 * `docs/tecnica/08` §7.3 e mais nenhum. Um campo fora dela é um **erro de
 * compilação**; em execução — porque um `as any` ou JavaScript sem tipos chegam
 * cá na mesma — é **retirado** da linha e contado em
 * `log_field_rejected_total:<motivo>`, tal como um valor que não tenha a forma
 * fechada do seu campo. Em modo estrito (`KAMBA_LOG_ESTRITO=1`) lança
 * `CampoRejeitadoError` e não escreve nada.
 *
 * Três coisas que este módulo nunca faz: **registar uma mensagem** (não há
 * argumento de texto; um erro regista-se por `error_code` e classe, nunca por
 * `erro.message`), **chamar `String()` sobre o que recebe**, e **lançar fora do
 * modo estrito**.
 *
 * É o espelho de `kamba_core.logger` em Python. A política está em
 * `politica.ts`; o processo para acrescentar um campo, em `docs/logs.md` §5.
 */

import { Contadores } from "../tenant_guard/index.ts";
import {
  CAMPOS_DE_CHAMADA,
  CAMPOS_RESERVADOS,
  type CamposDeLog,
  METRICA_ESCRITA_FALHADA,
  METRICA_REJEITADOS,
  MOTIVO_DESCONHECIDO,
  MOTIVO_MENSAGEM,
  MOTIVO_RESERVADO,
  MOTIVO_VALOR,
  NIVEIS,
  VARIAVEL_ESTRITO,
  codigoComClasse,
  nomeLegivel,
  validar,
  validarSvc,
} from "./politica.ts";

export {
  CAMPOS,
  CAMPOS_DE_CHAMADA,
  CAMPOS_RESERVADOS,
  type CampoDeChamada,
  type CamposDeLog,
  METRICA_ESCRITA_FALHADA,
  METRICA_REJEITADOS,
  MOTIVOS,
  NIVEIS,
  type Nivel,
  VARIAVEL_ESTRITO,
  idOpaco,
  mascararReferencia,
} from "./politica.ts";

/** Contadores do *logger*. Só números; os nomes são os de `politica.ts`. */
export const CONTADORES = new Contadores();

/**
 * `T` só com chaves de `Permitidos`, cada uma com o seu tipo; qualquer outra
 * chave passa a `never`, e nada lhe é atribuível.
 *
 * Um literal com uma chave a mais já falharia pela verificação de propriedades
 * em excesso. Isto fecha os outros caminhos: um objecto guardado numa variável
 * ou espalhado, que o TypeScript aceitaria por ser estruturalmente compatível;
 * e — com `T extends object` nas assinaturas — um texto no lugar dos campos.
 */
export type SoCampos<T, Permitidos = CamposDeLog> = [keyof T] extends [never]
  ? // `object`, `{}` e um `unknown` estreitado não dizem que chaves têm: sem
    // isto passavam, com o que quer que levassem lá dentro. Quem não tem
    // campos chama sem argumento.
    never
  : { readonly [K in keyof T]: K extends keyof Permitidos ? Permitidos[K] : never };

/** Os campos de `excepcao`: o `error_code` é o seu segundo argumento. */
export type CamposDeErro = Omit<CamposDeLog, "error_code">;

/** O nome do serviço não tem a forma de um. A mensagem não repete o valor. */
export class ServicoInvalidoError extends Error {
  constructor() {
    super(
      "o nome do servico tem de ser minusculas, digitos e hifenes " +
        "(ate 32 caracteres), como em docs/tecnica/09 §3.1",
    );
    this.name = "ServicoInvalidoError";
  }
}

export type Rejeicao = readonly [motivo: string, nome: string];

/**
 * Modo estrito: a chamada trazia algo que não pode ir para um *log*. A
 * mensagem diz o motivo e, quando é legível, o **nome** do campo. Nunca o valor.
 */
export class CampoRejeitadoError extends Error {
  readonly rejeicoes: readonly Rejeicao[];

  constructor(rejeicoes: readonly Rejeicao[]) {
    const partes = rejeicoes.map(([motivo, nome]) => `${motivo} (${nome})`).join(", ");
    super(
      `o logger recusou ${rejeicoes.length} elemento(s): ${partes}. So entram ` +
        "campos da allowlist com a forma fechada de cada um (docs/logs.md).",
    );
    this.name = "CampoRejeitadoError";
    this.rejeicoes = rejeicoes;
  }
}

/** Onde as linhas são escritas. Por omissão, `process.stdout`. */
export interface Destino {
  write(texto: string): unknown;
}

export interface OpcoesDeLogger {
  readonly destino?: Destino;
  readonly relogio?: () => Date;
  readonly estrito?: boolean;
}

const TS = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/;
const RESERVADOS: readonly string[] = CAMPOS_RESERVADOS;
const DE_CHAMADA: readonly string[] = CAMPOS_DE_CHAMADA;
const NIVEIS_VALIDOS: readonly string[] = NIVEIS;

/** Escreve linhas JSON com os campos da *allowlist* e mais nenhum. */
export class Logger {
  readonly svc: string;
  readonly estrito: boolean;
  readonly #destino: Destino | undefined;
  readonly #relogio: () => Date;

  constructor(svc: string, opcoes: OpcoesDeLogger = {}) {
    const canonico = validarSvc(svc);
    if (canonico === null) {
      throw new ServicoInvalidoError();
    }
    this.svc = canonico;
    this.#destino = opcoes.destino;
    this.#relogio = opcoes.relogio ?? (() => new Date());
    this.estrito = opcoes.estrito ?? process.env[VARIAVEL_ESTRITO] === "1";
  }

  /** O mesmo *logger*, fora do modo estrito. É o que os ganchos do processo usam. */
  tolerante(): Logger {
    return new Logger(this.svc, {
      ...(this.#destino === undefined ? {} : { destino: this.#destino }),
      relogio: this.#relogio,
      estrito: false,
    });
  }

  debug<T extends object>(campos?: SoCampos<T>): void {
    this.registar("debug", [], campos);
  }

  info<T extends object>(campos?: SoCampos<T>): void {
    this.registar("info", [], campos);
  }

  warn<T extends object>(campos?: SoCampos<T>): void {
    this.registar("warn", [], campos);
  }

  error<T extends object>(campos?: SoCampos<T>): void {
    this.registar("error", [], campos);
  }

  /** Regista um erro por `error_code` e classe. Nunca pela mensagem. */
  excepcao<T extends object>(
    erro: unknown,
    codigo?: string,
    campos?: SoCampos<T, CamposDeErro>,
  ): void {
    let dados: Record<string, unknown>;
    try {
      dados = { ...(campos as object | undefined) };
    } catch {
      dados = {};
    }
    dados.error_code = codigoComClasse(codigo, classeDe(erro));
    this.registar("error", [], dados);
  }

  /**
   * A forma dinâmica das chamadas acima; é por aqui que todas passam. Não tem
   * tipos de propósito: é a porta por onde entra o que o compilador não viu —
   * e por isso é a que tem a rede. O que não for uma rejeição do modo estrito e
   * lançar cá dentro (um relógio que falha, um objecto que mente sobre o que
   * é) conta em `log_write_failed_total` e a chamada volta sem escrever. O
   * *lint* proíbe usá-la fora do *logger*.
   */
  registar(nivel: unknown, posicionais: unknown, campos: unknown): void {
    try {
      this.#registar(nivel, posicionais, campos);
    } catch (erro) {
      if (erro instanceof CampoRejeitadoError) {
        throw erro;
      }
      CONTADORES.incrementar(METRICA_ESCRITA_FALHADA);
    }
  }

  #registar(nivel: unknown, posicionais: unknown, campos: unknown): void {
    const rejeicoes: Rejeicao[] = [];
    let nivelFinal = "error";
    if (typeof nivel === "string" && NIVEIS_VALIDOS.includes(nivel)) {
      nivelFinal = nivel;
    } else {
      rejeicoes.push([MOTIVO_VALOR, "level"]);
    }
    // O que não é uma lista conta como um posicional, como em Python.
    const quantos = Array.isArray(posicionais)
      ? posicionais.length
      : posicionais === undefined || posicionais === null
        ? 0
        : 1;
    for (let i = 0; i < quantos; i += 1) {
      rejeicoes.push([MOTIVO_MENSAGEM, "<posicional>"]);
    }

    const aceites = new Map<string, string | number>();
    if (campos !== undefined && campos !== null) {
      if (typeof campos !== "object" || Array.isArray(campos)) {
        // Um texto, um número ou uma lista no lugar dos campos: é a mensagem
        // livre de quem vem de `console.log("...")`.
        rejeicoes.push([MOTIVO_MENSAGEM, "<posicional>"]);
      } else if (!objectoSimples(campos)) {
        // Um `Error`, um `Map`, um `Headers`, uma instância de classe: não são
        // «os campos», e `Object.keys` não diz o que levam. Em Python o
        // equivalente (o que não é um `dict` exacto) conta da mesma maneira.
        rejeicoes.push([MOTIVO_MENSAGEM, "<posicional>"]);
      } else {
        this.#separar(campos as Record<string, unknown>, aceites, rejeicoes);
      }
    }

    if (rejeicoes.length > 0 && this.estrito) {
      throw new CampoRejeitadoError(rejeicoes);
    }
    for (const [motivo] of rejeicoes) {
      CONTADORES.incrementar(`${METRICA_REJEITADOS}:${motivo}`);
    }

    const ts: unknown = Date.prototype.toISOString.call(this.#relogio());
    if (typeof ts !== "string" || !TS.test(ts)) {
      // Um relógio que não devolve um instante: não se escreve o que ele
      // devolveu no lugar da hora.
      throw new TypeError("relogio invalido");
    }
    const linha: Record<string, string | number> = {
      ts,
      level: nivelFinal,
      svc: this.svc,
    };
    for (const nome of DE_CHAMADA) {
      const valor = aceites.get(nome);
      if (valor !== undefined) {
        linha[nome] = valor;
      }
    }
    this.#escrever(JSON.stringify(linha));
  }

  #separar(
    campos: Record<string, unknown>,
    aceites: Map<string, string | number>,
    rejeicoes: Rejeicao[],
  ): void {
    let nomes: string[];
    try {
      nomes = Object.keys(campos);
    } catch {
      rejeicoes.push([MOTIVO_VALOR, "<campos>"]);
      return;
    }
    for (const nome of nomes) {
      let valor: unknown;
      try {
        valor = campos[nome];
      } catch {
        // Um *getter* que lança: não é um valor, e não é deste módulo.
        rejeicoes.push([MOTIVO_VALOR, nomeLegivel(nome)]);
        continue;
      }
      if (valor === undefined || valor === null) {
        continue;
      }
      if (RESERVADOS.includes(nome)) {
        rejeicoes.push([MOTIVO_RESERVADO, nome]);
      } else if (!DE_CHAMADA.includes(nome)) {
        rejeicoes.push([MOTIVO_DESCONHECIDO, nomeLegivel(nome)]);
      } else {
        const limpo = validar(nome, valor);
        if (limpo === null) {
          rejeicoes.push([MOTIVO_VALOR, nome]);
        } else {
          aceites.set(nome, limpo);
        }
      }
    }
  }

  #escrever(texto: string): void {
    // Sem `try` próprio: um destino que falha lança até à rede de `registar`,
    // que conta em `log_write_failed_total` e segue. Sem destino não há onde
    // dizer que falhou; o que não se faz é deixar a excepção subir até ao pedido.
    (this.#destino ?? process.stdout).write(`${texto}\n`);
  }
}

/** Um objecto literal (`{...}`) ou sem protótipo; nada com classe própria. */
function objectoSimples(valor: object): boolean {
  try {
    const prototipo: unknown = Object.getPrototypeOf(valor);
    return prototipo === Object.prototype || prototipo === null;
  } catch {
    // Um *proxy* que lança ao ser inspeccionado não é um objecto simples.
    return false;
  }
}

/**
 * O nome da classe de um erro, sem lhe ler a mensagem. Vem do construtor e não
 * de `erro.name`, que é uma propriedade que qualquer código pode ter escrito.
 */
function classeDe(erro: unknown): string | undefined {
  if (typeof erro !== "object" || erro === null) {
    return undefined;
  }
  try {
    const construtor: unknown = Object.getPrototypeOf(erro)?.constructor;
    if (typeof construtor === "function") {
      return construtor.name;
    }
  } catch {
    // Um *proxy* que lança ao ser inspeccionado: fica sem classe.
  }
  return undefined;
}

export const OUTCOME_NAO_TRATADA = "excepcao_nao_tratada";
export const CODIGO_NAO_TRATADA = "excepcao_nao_tratada";
export const OUTCOME_AVISO = "aviso_do_processo";
export const CODIGO_AVISO = "aviso_do_processo";

/** O mínimo de `process` de que `instalar` precisa; permite testá-lo sem o processo real. */
export interface ProcessoMinimo {
  on(evento: string, tratador: (...argumentos: unknown[]) => void): unknown;
  removeAllListeners(evento: string): unknown;
  exit(codigo?: number): unknown;
}

export interface OpcoesDeInstalar extends OpcoesDeLogger {
  readonly processo?: ProcessoMinimo;
}

/**
 * Cria o *logger* do serviço e liga-o às excepções que ninguém apanha.
 *
 * Sem isto, um erro por tratar faz o Node imprimir a pilha **e a mensagem** no
 * `stderr` — que é onde vive o *payload* que o fez falhar. Com isto, sai uma
 * linha com `excepcao_nao_tratada:<Classe>` e o processo termina com código 1.
 *
 * Os avisos do processo (`process.emitWarning`, depreciações) têm o mesmo
 * problema — o Node imprime-lhes o texto — e levam o mesmo tratamento: tira-se
 * o ouvinte de origem e sai `aviso_do_processo:<Classe>`, sem o texto.
 *
 * Chama-se uma vez, no arranque. O erro que um *tratador de pedido* lança não
 * chega aqui: é da biblioteca HTTP, e cada serviço liga-o em `createApp`.
 */
export function instalar(svc: string, opcoes: OpcoesDeInstalar = {}): Logger {
  const registo = new Logger(svc, opcoes);
  const tolerante = registo.tolerante();
  const processo: ProcessoMinimo = opcoes.processo ?? process;
  const naoTratada = (erro: unknown): void => {
    tolerante.registar("error", [], {
      outcome: OUTCOME_NAO_TRATADA,
      error_code: codigoComClasse(CODIGO_NAO_TRATADA, classeDe(erro)),
    });
    processo.exit(1);
  };
  processo.on("uncaughtException", naoTratada);
  processo.on("unhandledRejection", naoTratada);
  processo.removeAllListeners("warning");
  processo.on("warning", (aviso: unknown): void => {
    tolerante.registar("warn", [], {
      outcome: OUTCOME_AVISO,
      error_code: codigoComClasse(CODIGO_AVISO, classeDe(aviso)),
    });
  });
  return registo;
}

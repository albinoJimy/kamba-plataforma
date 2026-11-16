/**
 * O orquestrador da rotação: `rotate(secret_id)`, a revogação e a rotação de
 * emergência (KAM-072).
 *
 * Duas portas e um relógio. O **cofre de anéis** guarda o anel de cada segredo
 * (`anel.ts`); o **registo de rotação** guarda o que aconteceu — o
 * identificador do segredo, a acção, o `kid` e a hora, **nunca o valor**. O
 * critério 7 do bloco pede esse registo no `audit_log`; o adaptador para lá
 * depende de uma acção nova no domínio `audit_log_action` (revisão `0048`),
 * que não existe, e por isso a porta é a fronteira: o `RegistoEmMemoria` deste
 * ficheiro é o que os ensaios usam, e o adaptador de base é o credor.
 *
 * ## A ordem: cofre primeiro, registo depois, e a repetição repara
 *
 * Gravar no cofre e depois no registo deixa uma janela onde a rotação
 * aconteceu e ainda não está registada. A ordem inversa deixava o contrário —
 * um registo de uma rotação que não aconteceu —, que é pior: um auditor
 * confiaria nele. O que fecha a janela é a **idempotência**: repetir
 * `rotate` com a mesma versão não roda outra vez, mas, se a última entrada do
 * registo não for desta versão, escreve-a. Uma rotação que caiu entre os dois
 * passos repara-se repetindo-a, e nunca fica duas vezes no registo.
 *
 * ## Concorrência
 *
 * O cofre escreve com uma condição: o `kid` actual tem de ser o que se leu.
 * Duas rotações ao mesmo tempo dão uma vitória e um `RotacaoConcorrenteError`,
 * e não um anel onde a anterior é a versão que outra pessoa acabou de criar.
 */

import { randomBytes } from "node:crypto";

import {
  type Anel,
  type ChaveDoAnel,
  anelInicial,
  rodar,
  revogarAnterior,
} from "./anel.ts";

/** O que o registo de rotação aceita como acção. */
export type AccaoDeRotacao = "rotacao" | "revogacao" | "emergencia";

/**
 * Uma entrada do registo. **Não tem campo para o valor**, e é de propósito:
 * a forma do tipo é a primeira barreira, e o ensaio que serializa o registo e
 * procura o valor é a segunda.
 */
export interface EntradaDeRotacao {
  /** O `id` do segredo no `ops/secrets-inventory.yaml`. */
  readonly segredo: string;
  readonly accao: AccaoDeRotacao;
  /** A versão actual depois da acção. */
  readonly kid: string;
  /** A versão que deixou de ser actual (rotação) ou que foi retirada (revogação). */
  readonly kidAnterior: string | null;
  readonly em: Date;
  /** Quem executou: um papel ou um identificador de operador, nunca um valor. */
  readonly actor: string;
}

/** O cofre de anéis. Guarda e devolve o anel inteiro de cada segredo. */
export interface CofreDeAneis {
  /** O anel de `segredo`, ou `null` se o segredo ainda não tem nenhum. */
  ler(segredo: string): Promise<Anel | null>;
  /**
   * Grava `anel` se o `kid` actual no cofre for `kidEsperado` (ou se não houver
   * anel e `kidEsperado` for `null`); senão levanta `RotacaoConcorrenteError`.
   */
  escrever(segredo: string, anel: Anel, kidEsperado: string | null): Promise<void>;
}

/** O registo de rotação. `gravar` e não `registar`: o nome está reservado ao logger. */
export interface RegistoDeRotacao {
  gravar(entrada: EntradaDeRotacao): Promise<void>;
  /** As entradas de `segredo`, da mais antiga para a mais recente. */
  entradas(segredo: string): Promise<readonly EntradaDeRotacao[]>;
}

/** Outra rotação mudou o anel entre a leitura e a escrita. */
export class RotacaoConcorrenteError extends Error {
  override readonly name = "RotacaoConcorrenteError";
  readonly segredo: string;

  constructor(segredo: string) {
    super(`o anel de ${segredo} mudou durante a rotação; leia-o outra vez e repita`);
    this.segredo = segredo;
  }
}

/** Pediu-se uma revogação ou uma rotação sobre um segredo sem anel. */
export class AnelInexistenteError extends Error {
  override readonly name = "AnelInexistenteError";
  readonly segredo: string;

  constructor(segredo: string) {
    super(`${segredo} não tem anel no cofre; a primeira versão entra por iniciar()`);
    this.segredo = segredo;
  }
}

/** Pediu-se `iniciar` sobre um segredo que já tem anel, com outra versão. */
export class AnelJaIniciadoError extends Error {
  override readonly name = "AnelJaIniciadoError";
  readonly segredo: string;

  constructor(segredo: string) {
    super(`${segredo} já tem anel no cofre; uma versão nova entra por rotate()`);
    this.segredo = segredo;
  }
}

/** Um `id` de segredo com a forma do inventário: `snake_case` minúsculo. */
const ID_DO_SEGREDO = /^[a-z][a-z0-9_]{2,63}$/;

function exigirSegredo(segredo: string): string {
  if (typeof segredo !== "string" || !ID_DO_SEGREDO.test(segredo)) {
    throw new RangeError("o segredo tem de ser um id do inventário, em snake_case");
  }
  return segredo;
}

/** Opções do `Rotador`. */
export interface OpcoesDoRotador {
  readonly cofre: CofreDeAneis;
  readonly registo: RegistoDeRotacao;
  readonly actor: string;
  /** O relógio. Por omissão, o do sistema; os ensaios avançam-no à mão. */
  readonly agora?: () => Date;
}

/** O resultado de uma acção: se mudou alguma coisa, e a versão actual. */
export interface ResultadoDaRotacao {
  readonly mudou: boolean;
  readonly kid: string;
}

/**
 * Janelas de sobreposição por omissão, em dias (**proposta**).
 *
 * `meta_app_secret`: 7 dias, porque a Meta re-entrega *webhooks* falhados até
 * sete dias (`evidencia/E1` §5). `proxypay_api_key`: 1 dia — o RB-K07 §3.2 pede
 * 24 h sem falhas de autenticação antes de retirar a anterior, e o reconciliador
 * por consulta apanha o que falhar. O resto: 1 dia.
 */
export const JANELA_POR_OMISSAO_DIAS: Readonly<Record<string, number>> = {
  meta_app_secret: 7,
  proxypay_api_key: 1,
};

/** Milissegundos de um dia. */
export const DIA_MS = 86_400_000;

/** A janela de `segredo` em milissegundos. */
export function janelaDe(segredo: string): number {
  return (JANELA_POR_OMISSAO_DIAS[segredo] ?? 1) * DIA_MS;
}

/**
 * Um valor novo de 32 octetos em base64, para os segredos que **nós** geramos
 * (*pepper*, KEK, segredos de assinatura internos). O App Secret da Meta e a
 * chave do facilitador não nascem aqui: geram-se nos painéis deles.
 */
export function gerarValor(): string {
  return randomBytes(32).toString("base64");
}

/** O orquestrador. Um por processo de operação; não guarda estado. */
export class Rotador {
  readonly #cofre: CofreDeAneis;
  readonly #registo: RegistoDeRotacao;
  readonly #actor: string;
  readonly #agora: () => Date;

  constructor(opcoes: OpcoesDoRotador) {
    if (typeof opcoes.actor !== "string" || opcoes.actor.trim() === "") {
      throw new RangeError("o rotador precisa de um actor para o registo");
    }
    this.#cofre = opcoes.cofre;
    this.#registo = opcoes.registo;
    this.#actor = opcoes.actor;
    this.#agora = opcoes.agora ?? (() => new Date());
  }

  /** Grava a primeira versão de um segredo. Idempotente com a mesma versão. */
  async iniciar(segredo: string, primeira: ChaveDoAnel): Promise<ResultadoDaRotacao> {
    exigirSegredo(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido !== null) {
      // Repetir com o mesmo `kid` e o mesmo valor não muda nada (o `rodar`
      // devolve o mesmo anel, ou levanta `KidRepetidoError` com outro valor).
      // Com outro `kid`, o segredo já foi iniciado: o caminho é o `rotate`.
      if (rodar(lido, primeira, this.#agora(), 0) !== lido) {
        throw new AnelJaIniciadoError(segredo);
      }
      return { mudou: false, kid: lido.actual.kid };
    }
    await this.#cofre.escrever(segredo, anelInicial(primeira), null);
    await this.#gravar(segredo, "rotacao", primeira.kid, null);
    return { mudou: true, kid: primeira.kid };
  }

  /**
   * `rotate(secret_id)`: a nova passa a actual e a actual fica viva durante a
   * janela. Idempotente: repetir com a mesma versão não roda outra vez.
   */
  async rotate(
    segredo: string,
    nova: ChaveDoAnel,
    janelaMs: number = janelaDe(segredo),
  ): Promise<ResultadoDaRotacao> {
    return this.#rodar(segredo, nova, janelaMs, "rotacao");
  }

  /**
   * Rotação de emergência: o segredo está comprometido, pelo que a anterior
   * **não** fica viva — roda-se com janela zero e retira-se a anterior no mesmo
   * passo. É o caminho do critério 6; o preço é que o tráfego assinado com a
   * comprometida passa a ser recusado já, e quem recupera é a re-entrega da
   * Meta e o reconciliador do PAY.
   */
  async emergencia(segredo: string, nova: ChaveDoAnel): Promise<ResultadoDaRotacao> {
    return this.#rodar(segredo, nova, 0, "emergencia");
  }

  /** Retira a anterior. Num anel sem anterior, não faz nada e não regista nada. */
  async revogar(segredo: string): Promise<ResultadoDaRotacao> {
    exigirSegredo(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    if (lido.anterior === null) return { mudou: false, kid: lido.actual.kid };
    const retirada = lido.anterior.kid;
    await this.#cofre.escrever(segredo, revogarAnterior(lido), lido.actual.kid);
    await this.#gravar(segredo, "revogacao", lido.actual.kid, retirada);
    return { mudou: true, kid: lido.actual.kid };
  }

  /**
   * Revoga a anterior se a janela já fechou. É o passo que um agendador corre;
   * sem ele, a anterior deixa de verificar (o `anteriorAte` já a exclui) mas
   * continua no cofre, e um segredo que já não serve não deve ficar guardado.
   */
  async revogarSeVencida(segredo: string): Promise<ResultadoDaRotacao> {
    exigirSegredo(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    if (
      lido.anterior === null ||
      lido.anteriorAte === null ||
      this.#agora().getTime() < lido.anteriorAte.getTime()
    ) {
      return { mudou: false, kid: lido.actual.kid };
    }
    return this.revogar(segredo);
  }

  async #rodar(
    segredo: string,
    nova: ChaveDoAnel,
    janelaMs: number,
    accao: "rotacao" | "emergencia",
  ): Promise<ResultadoDaRotacao> {
    exigirSegredo(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    const agora = this.#agora();
    const rodado = rodar(lido, nova, agora, janelaMs);

    if (rodado === lido) {
      // Repetição: o cofre já tem esta versão. Repara o registo se a rotação
      // anterior caiu entre os dois passos.
      const entradas = await this.#registo.entradas(segredo);
      if (!entradas.some((e) => e.kid === nova.kid && e.accao !== "revogacao")) {
        await this.#gravar(segredo, accao, nova.kid, lido.anterior?.kid ?? null);
      }
      if (accao === "emergencia" && lido.anterior !== null) {
        await this.revogar(segredo);
      }
      return { mudou: false, kid: nova.kid };
    }

    const final = accao === "emergencia" ? revogarAnterior(rodado) : rodado;
    await this.#cofre.escrever(segredo, final, lido.actual.kid);
    await this.#gravar(segredo, accao, nova.kid, lido.actual.kid);
    return { mudou: true, kid: nova.kid };
  }

  async #gravar(
    segredo: string,
    accao: AccaoDeRotacao,
    kid: string,
    kidAnterior: string | null,
  ): Promise<void> {
    await this.#registo.gravar({
      segredo,
      accao,
      kid,
      kidAnterior,
      em: this.#agora(),
      actor: this.#actor,
    });
  }
}

/** Cofre de anéis em memória: para `dev` e para os ensaios. */
export class CofreEmMemoria implements CofreDeAneis {
  readonly #aneis = new Map<string, Anel>();

  async ler(segredo: string): Promise<Anel | null> {
    return this.#aneis.get(segredo) ?? null;
  }

  async escrever(segredo: string, anel: Anel, kidEsperado: string | null): Promise<void> {
    const actual = this.#aneis.get(segredo)?.actual.kid ?? null;
    if (actual !== kidEsperado) throw new RotacaoConcorrenteError(segredo);
    this.#aneis.set(segredo, anel);
  }
}

/** Registo em memória: para `dev` e para os ensaios. */
export class RegistoEmMemoria implements RegistoDeRotacao {
  readonly #entradas: EntradaDeRotacao[] = [];

  async gravar(entrada: EntradaDeRotacao): Promise<void> {
    this.#entradas.push(Object.freeze({ ...entrada }));
  }

  async entradas(segredo: string): Promise<readonly EntradaDeRotacao[]> {
    return this.#entradas.filter((entrada) => entrada.segredo === segredo);
  }

  /** Todas as entradas, por ordem. Para o ensaio que procura valores no registo. */
  todas(): readonly EntradaDeRotacao[] {
    return [...this.#entradas];
  }
}

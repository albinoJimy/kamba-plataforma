/**
 * O orquestrador da rotação: `rotate(secret_id)`, a revogação e a rotação de
 * emergência (KAM-072).
 *
 * Duas portas e um relógio. O **cofre de anéis** guarda o anel de cada segredo
 * (`anel.ts`); o **registo de rotação** guarda o que aconteceu — o
 * identificador do segredo, a acção, o `kid` e a hora, **nunca o valor**, e é
 * dele que o rotador lê o que já aconteceu (a reparação, o histórico de `kid`,
 * a idade). O critério 7 do bloco pede, além disso, a linha no `audit_log`: é a
 * terceira porta, opcional, `AuditoriaDeRotacao` (`auditoria.ts`), com as duas
 * acções que a revisão `0066` acrescenta ao domínio fechado `audit_log_action`.
 * O `audit_log` só guarda o resumo dos metadados, e por isso não serve de
 * registo de onde se lê: são duas portas e não uma.
 *
 * ## A ordem: cofre primeiro, registo depois, e repetir repara
 *
 * Gravar no cofre e depois no registo deixa uma janela onde a acção aconteceu
 * e ainda não está registada. A ordem inversa deixava o contrário — um registo
 * de uma acção que não aconteceu —, que é pior: um auditor confiaria nele. O
 * que fecha a janela é a **repetição**: repetir `iniciar`, `rotate`,
 * `emergencia` ou `revogar` depois de uma falha entre os dois passos não muda o
 * cofre outra vez, e escreve a entrada que faltou. A entrada reparada leva a
 * hora da repetição e não a da acção: a hora da acção perdeu-se com a falha, e
 * inventá-la seria pior.
 *
 * ## Concorrência
 *
 * O cofre escreve com uma condição sobre o par de `kid` lido (actual e
 * anterior). Duas acções sobre o mesmo anel ao mesmo tempo dão uma vitória e um
 * `RotacaoConcorrenteError`, e nunca uma revogação que retira a anterior que
 * outra rotação acabou de abrir.
 *
 * ## Três recusas que o anel sozinho não consegue fazer
 *
 * 1. **Um `kid` nunca volta**, nem um de há duas rotações: o anel só se lembra
 *    de duas versões, e quem se lembra das outras é o registo.
 * 2. **O mesmo valor com outro `kid` é recusado**: era uma emergência que
 *    deixava a chave comprometida a assinar com um nome novo.
 * 3. **Não se roda com uma anterior ainda viva.** Rodar `[B, A]` para C dava
 *    `[C, B]` e tirava A antes do fim da janela dela, sem registo. Com a janela
 *    vencida, a revogação de A faz-se primeiro e fica registada; numa
 *    emergência faz-se sempre.
 */

import { validarRef } from "../secrets/port.ts";

import type { AuditoriaDeRotacao } from "./auditoria.ts";

import {
  type Anel,
  type ChaveDoAnel,
  anelInicial,
  rodar,
  revogarAnterior,
  valoresIguais,
} from "./anel.ts";

/** O que o registo de rotação aceita como acção. */
export type AccaoDeRotacao = "inicio" | "rotacao" | "revogacao" | "emergencia";

/**
 * Uma entrada do registo. **Não tem campo para o valor**, e é de propósito:
 * a forma do tipo é a primeira barreira, e o ensaio que serializa o registo e
 * procura o valor é a segunda.
 */
export interface EntradaDeRotacao {
  /** A referência do segredo: o `id` do inventário, ou `<id>/<instância>`. */
  readonly segredo: string;
  readonly accao: AccaoDeRotacao;
  /** A versão actual depois da acção. */
  readonly kid: string;
  /** A versão que deixou de ser actual (rotação) ou que foi retirada (revogação). */
  readonly kidAnterior: string | null;
  readonly em: Date;
  /**
   * Quando nasceu a versão actual. Numa rotação é `em`; num `inicio` é o que
   * quem importa o segredo souber dizer, ou `null` — e com `null` a idade fica
   * por saber, em vez de começar a zero.
   */
  readonly criadaEm: Date | null;
  /** Quem executou: um papel ou um identificador de operador, nunca um valor. */
  readonly actor: string;
}

/** O par de versões que se leu, e que tem de estar no cofre quando se escreve. */
export interface KidsLidos {
  readonly actual: string;
  readonly anterior: string | null;
}

/** O cofre de anéis. Guarda e devolve o anel inteiro de cada segredo. */
export interface CofreDeAneis {
  /** O anel de `segredo`, ou `null` se o segredo ainda não tem nenhum. */
  ler(segredo: string): Promise<Anel | null>;
  /**
   * Grava `anel` se o par de `kid` no cofre for `esperado` (ou se não houver
   * anel e `esperado` for `null`); senão levanta `RotacaoConcorrenteError`.
   */
  escrever(segredo: string, anel: Anel, esperado: KidsLidos | null): Promise<void>;
}

/** O registo de rotação. `gravar` e não `registar`: o nome está reservado ao logger. */
export interface RegistoDeRotacao {
  gravar(entrada: EntradaDeRotacao): Promise<void>;
  /** As entradas de `segredo`, da mais antiga para a mais recente. */
  entradas(segredo: string): Promise<readonly EntradaDeRotacao[]>;
}

/** Outra acção mudou o anel entre a leitura e a escrita. */
export class RotacaoConcorrenteError extends Error {
  override readonly name = "RotacaoConcorrenteError";
  readonly segredo: string;

  constructor(segredo: string) {
    super(`o anel de ${segredo} mudou durante a operação; leia-o outra vez e repita`);
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

/** Um `kid` que já existiu neste segredo. Diz o `kid`, nunca o valor. */
export class KidJaUsadoError extends Error {
  override readonly name = "KidJaUsadoError";
  readonly segredo: string;
  readonly kid: string;

  constructor(segredo: string, kid: string) {
    super(`a versão ${kid} já existiu em ${segredo}; uma versão nova tem um kid novo`);
    this.segredo = segredo;
    this.kid = kid;
  }
}

/** O valor novo é o da actual ou o da anterior, com outro `kid`. */
export class ValorRepetidoError extends Error {
  override readonly name = "ValorRepetidoError";
  readonly segredo: string;

  constructor(segredo: string) {
    super(`o valor novo de ${segredo} é um valor que o anel já tem; gere um valor novo`);
    this.segredo = segredo;
  }
}

/** A anterior ainda está dentro da janela: rodar agora tirava-a antes do fim. */
export class JanelaAbertaError extends Error {
  override readonly name = "JanelaAbertaError";
  readonly segredo: string;
  readonly ate: Date;

  constructor(segredo: string, ate: Date) {
    super(
      `${segredo} ainda tem a anterior viva até ${ate.toISOString()}; ` +
        `revogue-a primeiro, ou use a rotação de emergência`,
    );
    this.segredo = segredo;
    this.ate = ate;
  }
}

/** Opções do `Rotador`. */
export interface OpcoesDoRotador {
  readonly cofre: CofreDeAneis;
  readonly registo: RegistoDeRotacao;
  readonly actor: string;
  /**
   * O `audit_log` (critério 7). Escreve-se **antes** do registo: se o registo
   * falhar depois, a repetição repara-o e escreve a linha de auditoria outra
   * vez — duas linhas da mesma acção, que é melhor do que nenhuma.
   */
  readonly auditoria?: AuditoriaDeRotacao;
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
 * A janela conta da **escrita no cofre**, e não da troca no painel do
 * fornecedor: quem roda escreve no cofre, recria os consumidores e troca no
 * painel logo a seguir (RB-K07 §3.1 e §3.2). Uma troca no painel que se atrase
 * para lá da janela recusa *callbacks* assinados com a anterior.
 *
 * `meta_app_secret`: 7 dias, porque a Meta re-entrega *webhooks* falhados até
 * sete dias (`evidencia/E1` §5). `proxypay_api_key`: 1 dia. O RB-K07 §3.2 pede
 * mais do que isso — 24 h **com 0 falhas de autenticação** —, e essa condição é
 * do operador: o `revogarSeVencida` não a consulta, pelo que no facilitador o
 * passo certo é `revogar` à mão depois de ver a consulta. O resto: 1 dia.
 */
export const JANELA_POR_OMISSAO_DIAS: Readonly<Record<string, number>> = {
  meta_app_secret: 7,
  proxypay_api_key: 1,
};

/** Milissegundos de um dia. */
export const DIA_MS = 86_400_000;

/** A janela de `segredo` (a família, antes de `/`) em milissegundos. */
export function janelaDe(segredo: string): number {
  const familia = segredo.split("/")[0] ?? segredo;
  return (JANELA_POR_OMISSAO_DIAS[familia] ?? 1) * DIA_MS;
}

/** Os `kid` de um anel, na forma da condição de escrita. */
function kidsDe(anel: Anel): KidsLidos {
  return { actual: anel.actual.kid, anterior: anel.anterior?.kid ?? null };
}

/** A última entrada que não é revogação: a que diz qual é a versão actual. */
function ultimaVersao(entradas: readonly EntradaDeRotacao[]): EntradaDeRotacao | undefined {
  for (let i = entradas.length - 1; i >= 0; i -= 1) {
    const entrada = entradas[i] as EntradaDeRotacao;
    if (entrada.accao !== "revogacao") return entrada;
  }
  return undefined;
}

/** O orquestrador. Um por processo de operação; não guarda estado. */
export class Rotador {
  readonly #cofre: CofreDeAneis;
  readonly #registo: RegistoDeRotacao;
  readonly #auditoria: AuditoriaDeRotacao | null;
  readonly #actor: string;
  readonly #agora: () => Date;

  constructor(opcoes: OpcoesDoRotador) {
    if (typeof opcoes.actor !== "string" || opcoes.actor.trim() === "") {
      throw new RangeError("o rotador precisa de um actor para o registo");
    }
    this.#cofre = opcoes.cofre;
    this.#registo = opcoes.registo;
    this.#auditoria = opcoes.auditoria ?? null;
    this.#actor = opcoes.actor;
    this.#agora = opcoes.agora ?? (() => new Date());
  }

  /**
   * Grava a primeira versão de um segredo, ou importa a que já existe.
   *
   * `criadaEm` é quando a versão nasceu, se se souber: um segredo criado há 170
   * dias e importado hoje tem 170 dias, não zero. Com `null`, a idade fica por
   * saber (`sem_registo`) até à primeira rotação.
   */
  async iniciar(
    segredo: string,
    primeira: ChaveDoAnel,
    criadaEm: Date | null = null,
  ): Promise<ResultadoDaRotacao> {
    validarRef(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido !== null) {
      // Repetir com a mesma versão e o mesmo valor não muda o cofre (o `rodar`
      // devolve o mesmo anel, ou levanta com o mesmo `kid` e outro valor).
      if (rodar(lido, primeira, this.#agora(), 0) !== lido) {
        throw new AnelJaIniciadoError(segredo);
      }
      if ((await this.#registo.entradas(segredo)).length === 0) {
        await this.#gravar(segredo, "inicio", primeira.kid, null, criadaEm);
      }
      return { mudou: false, kid: lido.actual.kid };
    }
    await this.#cofre.escrever(segredo, anelInicial(primeira), null);
    await this.#gravar(segredo, "inicio", primeira.kid, null, criadaEm);
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
   * **não** fica viva — retira-se a que houver, roda-se e retira-se a
   * comprometida no mesmo passo. É o caminho do critério 6; o preço é que o
   * tráfego assinado com a comprometida passa a ser recusado já, e quem
   * recupera é a re-entrega da Meta e o reconciliador do PAY.
   */
  async emergencia(segredo: string, nova: ChaveDoAnel): Promise<ResultadoDaRotacao> {
    return this.#rodar(segredo, nova, 0, "emergencia");
  }

  /** Retira a anterior, esteja ou não dentro da janela. */
  async revogar(segredo: string): Promise<ResultadoDaRotacao> {
    validarRef(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    return this.#revogar(segredo, lido);
  }

  /**
   * Revoga a anterior se a janela já fechou. É o passo que um agendador corre.
   *
   * Lê **uma** vez e escreve com a condição sobre essa leitura: uma rotação
   * que abra uma janela nova entre as duas coisas faz esta falhar, em vez de
   * retirar a anterior que acabou de nascer.
   */
  async revogarSeVencida(segredo: string): Promise<ResultadoDaRotacao> {
    validarRef(segredo);
    const lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    if (
      lido.anterior !== null &&
      lido.anteriorAte !== null &&
      this.#agora().getTime() < lido.anteriorAte.getTime()
    ) {
      return { mudou: false, kid: lido.actual.kid };
    }
    return this.#revogar(segredo, lido);
  }

  async #revogar(segredo: string, lido: Anel): Promise<ResultadoDaRotacao> {
    if (lido.anterior === null) {
      // Reparação: a última entrada é uma rotação que deixou anterior, e o
      // cofre já não a tem — a revogação aconteceu e o registo caiu.
      const entradas = await this.#registo.entradas(segredo);
      const ultima = entradas[entradas.length - 1];
      if (
        ultima !== undefined &&
        ultima.accao === "rotacao" &&
        ultima.kid === lido.actual.kid &&
        ultima.kidAnterior !== null
      ) {
        await this.#gravar(segredo, "revogacao", lido.actual.kid, ultima.kidAnterior, null);
      }
      return { mudou: false, kid: lido.actual.kid };
    }
    const retirada = lido.anterior.kid;
    await this.#cofre.escrever(segredo, revogarAnterior(lido), kidsDe(lido));
    await this.#gravar(segredo, "revogacao", lido.actual.kid, retirada, null);
    return { mudou: true, kid: lido.actual.kid };
  }

  async #rodar(
    segredo: string,
    nova: ChaveDoAnel,
    janelaMs: number,
    accao: "rotacao" | "emergencia",
  ): Promise<ResultadoDaRotacao> {
    validarRef(segredo);
    let lido = await this.#cofre.ler(segredo);
    if (lido === null) throw new AnelInexistenteError(segredo);
    const entradas = await this.#registo.entradas(segredo);
    const agora = this.#agora();

    if (nova.kid === lido.actual.kid) {
      // Repetição. O `rodar` recusa o mesmo `kid` com outro valor.
      rodar(lido, nova, agora, janelaMs);
      const ultima = ultimaVersao(entradas);
      if (ultima?.kid !== nova.kid) {
        // A acção caiu entre o cofre e o registo. A versão que deixou de ser
        // actual é a anterior do anel ou, se uma emergência já a retirou, a
        // última versão que o registo conhece.
        await this.#gravar(segredo, accao, nova.kid, lido.anterior?.kid ?? ultima?.kid ?? null, agora);
      }
      if (accao === "emergencia" && lido.anterior !== null) await this.#revogar(segredo, lido);
      return { mudou: false, kid: nova.kid };
    }

    if (
      lido.anterior?.kid === nova.kid ||
      entradas.some((e) => e.accao !== "revogacao" && e.kid === nova.kid)
    ) {
      throw new KidJaUsadoError(segredo, nova.kid);
    }
    // As duas comparações correm sempre: um `||` saltava a segunda.
    const igualAActual = valoresIguais(nova.valor, lido.actual.valor);
    const igualAAnterior = lido.anterior !== null && valoresIguais(nova.valor, lido.anterior.valor);
    if (igualAActual || igualAAnterior) throw new ValorRepetidoError(segredo);

    if (lido.anterior !== null) {
      const vencida = lido.anteriorAte === null || agora.getTime() >= lido.anteriorAte.getTime();
      if (accao !== "emergencia" && !vencida) {
        throw new JanelaAbertaError(segredo, lido.anteriorAte as Date);
      }
      await this.#revogar(segredo, lido);
      lido = revogarAnterior(lido);
    }

    const rodado = rodar(lido, nova, agora, janelaMs);
    const final = accao === "emergencia" ? revogarAnterior(rodado) : rodado;
    await this.#cofre.escrever(segredo, final, kidsDe(lido));
    await this.#gravar(segredo, accao, nova.kid, lido.actual.kid, agora);
    return { mudou: true, kid: nova.kid };
  }

  async #gravar(
    segredo: string,
    accao: AccaoDeRotacao,
    kid: string,
    kidAnterior: string | null,
    criadaEm: Date | null,
  ): Promise<void> {
    const entrada: EntradaDeRotacao = {
      segredo,
      accao,
      kid,
      kidAnterior,
      em: this.#agora(),
      criadaEm,
      actor: this.#actor,
    };
    if (this.#auditoria !== null) await this.#auditoria.gravar(entrada);
    await this.#registo.gravar(entrada);
  }
}

/** Cofre de anéis em memória: para `dev` e para os ensaios. */
export class CofreEmMemoria implements CofreDeAneis {
  readonly #aneis = new Map<string, Anel>();

  async ler(segredo: string): Promise<Anel | null> {
    return this.#aneis.get(segredo) ?? null;
  }

  async escrever(segredo: string, anel: Anel, esperado: KidsLidos | null): Promise<void> {
    const guardado = this.#aneis.get(segredo);
    const igual =
      guardado === undefined
        ? esperado === null
        : esperado !== null &&
          guardado.actual.kid === esperado.actual &&
          (guardado.anterior?.kid ?? null) === esperado.anterior;
    if (!igual) throw new RotacaoConcorrenteError(segredo);
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

/**
 * A idempotência do envio e do recibo (KAM-116, critério 5).
 *
 * «Envio idempotente (2 chamadas com a mesma chave → 1 SMS), recibo autenticado
 * (…) e idempotente por id do fornecedor.»
 *
 * ## As duas são idempotências diferentes, e por isso são dois registos
 *
 * O **envio** é idempotente por uma chave que **quem chama** escolhe: o KAM-086
 * deriva-a do caso de onboarding, e é ela que faz uma repetição de pedido do
 * dono não gastar um segundo SMS. O **recibo** é idempotente por um id que o
 * **agregador** escolhe, e serve outro problema: os agregadores re-entregam
 * recibos, e um recibo contado duas vezes estraga a `sms_delivery_ratio` antes
 * de estragar qualquer coisa de negócio.
 *
 * Juntá-los num registo só fazia a chave do agregador e a nossa viver no mesmo
 * espaço de nomes, com uma colisão possível e sem consequência visível.
 *
 * ## O estado que a maior parte das portas de SMS não tem
 *
 * Uma reserva tem **três** destinos, e não dois:
 *
 *     concluida       o agregador aceitou; o `id` dele está guardado
 *     libertada       o agregador recusou e **não enviou**; a chave volta a
 *                     servir, e uma repetição envia
 *     em_curso        o agregador não respondeu; **pode ter enviado**
 *
 * O `em_curso` que não resolve é o caso do `PROVIDER_DOWN`, e é o único
 * honesto: a resposta perdeu-se, não o SMS. Tratá-lo como `libertada`
 * convidava a um segundo envio — o SMS a dobrar que o critério proíbe — e
 * tratá-lo como `concluida` dava um `id` que não existe. Fica `em_curso`, uma
 * repetição com a mesma chave **não envia**, e quem resolve é o `status(id)`
 * ou o recibo.
 *
 * Qual dos três cabe a cada erro não é escolha deste ficheiro: está em
 * `REPETIVEIS` e no `enviarUmaVez`, derivado do código tipado.
 *
 * ## Em memória, e o que isso quer dizer
 *
 * O `RegistoEmMemoria` é o que o `FakeSmsProvider` e um processo único usam, e
 * **não sobrevive a um reinício**: duas chamadas com a mesma chave, com um
 * reinício entre elas, dão dois SMS. Isso está dito e não resolvido aqui de
 * propósito — resolvê-lo era criar uma tabela, e a tabela do OTP é do KAM-086,
 * que é dono do `onboarding_case`. O que este ficheiro entrega é a **porta**,
 * para que uma implementação durável entre sem tocar em adaptador nenhum; e o
 * que o KAM-086 tem de saber está escrito no relatório
 * (`../../../../docs/evidencia/KAM-116.md`).
 *
 * ## Uma nota sobre atomicidade que parece desnecessária e não é
 *
 * O `reservar` do `RegistoEmMemoria` decide e escreve **sem nenhum `await` pelo
 * meio**. O JavaScript é de uma linha de execução, pelo que isso é atómico; com
 * um `await` entre o `has` e o `set`, duas chamadas concorrentes reservavam as
 * duas e saíam dois SMS — e o ensaio de idempotência sequencial continuava
 * verde. Uma implementação durável tem de o conseguir num só comando
 * (`INSERT … ON CONFLICT DO NOTHING` e ler o que ficou), e não com um `SELECT`
 * seguido de um `INSERT`.
 */

import type { Estado } from "./contrato.ts";
import { validarChave } from "./contrato.ts";

/** O que ficou guardado de um envio já aceite. */
export interface Registo {
  /** O `id` do envio do lado do agregador. */
  readonly id: string;
  readonly estado: Estado;
}

/** O resultado de uma tentativa de reserva. */
export type Reserva =
  /** A chave é nova: quem reservou **tem** de enviar, e depois concluir ou libertar. */
  | { readonly novo: true }
  /** A chave já foi usada. `registo` é `null` enquanto a primeira não resolveu. */
  | { readonly novo: false; readonly registo: Registo | null };

/**
 * A porta do registo de envios.
 *
 * Três operações e uma leitura. Não tem `apagar`: uma chave de idempotência que
 * se apaga deixa de ser uma chave de idempotência, e a retenção é política do
 * dono dos dados (KAM-086), não desta porta.
 */
export interface RegistoDeEnvios {
  /** Reserva a chave, ou diz o que já está guardado. Tem de ser atómico. */
  reservar(chave: string): Promise<Reserva>;
  /** O agregador aceitou: guarda o `id` e o estado. */
  concluir(chave: string, registo: Registo): Promise<void>;
  /** O agregador recusou e não enviou: a chave volta a servir. */
  libertar(chave: string): Promise<void>;
  /** O que está guardado, ou `null` se a chave nunca foi reservada. */
  ler(chave: string): Promise<Registo | null>;
}

/** A porta do registo de recibos já vistos, por id do agregador. */
export interface RegistoDeRecibos {
  /**
   * Marca o id como visto e diz se é a **primeira** vez.
   *
   * `true` significa «é novo, trata-o»; `false` significa «já foi tratado,
   * ignora». Uma operação só, e não um `viu()` seguido de um `marcar()`, pela
   * razão de atomicidade da nota do módulo.
   */
  primeiraVez(idDoFornecedor: string): Promise<boolean>;
}

/** Levantado quando se conclui ou liberta uma chave que não está reservada. */
export class ReservaInexistenteError extends Error {
  override readonly name = "ReservaInexistenteError";

  constructor(operacao: string) {
    super(`${operacao}: a chave nao esta reservada`);
  }
}

/**
 * Registo de envios em memória.
 *
 * O `Map` guarda `null` para uma reserva em curso e o `Registo` para uma
 * concluída. A distinção entre «não está no `Map`» e «está com `null`» é o que
 * separa «chave nova» de «chave reservada e ainda sem resposta», e é por isso
 * que não se usa um valor sentinela.
 */
export class RegistoDeEnviosEmMemoria implements RegistoDeEnvios {
  readonly #porChave = new Map<string, Registo | null>();

  async reservar(chave: string): Promise<Reserva> {
    const limpa = validarChave(chave);
    // Sem `await` entre a leitura e a escrita — ver a nota do módulo.
    if (this.#porChave.has(limpa)) {
      return { novo: false, registo: this.#porChave.get(limpa) ?? null };
    }
    this.#porChave.set(limpa, null);
    return { novo: true };
  }

  async concluir(chave: string, registo: Registo): Promise<void> {
    const limpa = validarChave(chave);
    if (!this.#porChave.has(limpa)) throw new ReservaInexistenteError("concluir");
    this.#porChave.set(limpa, registo);
  }

  async libertar(chave: string): Promise<void> {
    const limpa = validarChave(chave);
    if (!this.#porChave.has(limpa)) throw new ReservaInexistenteError("libertar");
    // **Só liberta uma reserva que não resolveu.** Libertar uma chave já
    // concluida apagava o `id` de um SMS que saiu, e a repetição seguinte
    // enviava o segundo — exactamente o que o critério 5 proibe.
    if (this.#porChave.get(limpa) === null) this.#porChave.delete(limpa);
  }

  async ler(chave: string): Promise<Registo | null> {
    return this.#porChave.get(validarChave(chave)) ?? null;
  }

  /** Quantas chaves estão guardadas. Para os ensaios. */
  get tamanho(): number {
    return this.#porChave.size;
  }
}

/** Forma de um id de recibo: opaco, imprimível e sem espaços. */
export const ID_DE_RECIBO = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

/** Levantado quando o id do recibo não tem forma de id. */
export class IdDeReciboInvalidoError extends Error {
  override readonly name = "IdDeReciboInvalidoError";
  readonly comprimento: number;

  constructor(id: string) {
    super(`id de recibo invalido (${id.length} caracteres)`);
    this.comprimento = id.length;
  }
}

/**
 * Registo de recibos vistos, em memória, com tecto.
 *
 * O tecto não é optimização: sem ele, um processo que receba recibos durante
 * semanas acumula um `Set` que só cresce, e a fuga de memória aparece como o
 * serviço a morrer sem razão aparente. Ao chegar ao tecto deita fora a metade
 * mais antiga — a ordem de inserção de um `Set` do JavaScript é a de
 * inserção, e é garantida pela norma.
 *
 * **O que isto custa está dito:** um recibo re-entregue depois de o seu id
 * sair da janela é tratado outra vez. Com o tecto abaixo, isso é um recibo
 * repetido ao fim de muitos milhares de outros, e o agregador que re-entrega
 * assim tão tarde é um problema diferente.
 */
export class RegistoDeRecibosEmMemoria implements RegistoDeRecibos {
  readonly #vistos = new Set<string>();
  readonly #tecto: number;

  constructor(tecto = 100_000) {
    this.#tecto = Math.max(2, Math.trunc(tecto));
  }

  async primeiraVez(idDoFornecedor: string): Promise<boolean> {
    if (typeof idDoFornecedor !== "string" || !ID_DE_RECIBO.test(idDoFornecedor)) {
      throw new IdDeReciboInvalidoError(
        typeof idDoFornecedor === "string" ? idDoFornecedor : "",
      );
    }
    // Sem `await` entre a leitura e a escrita — ver a nota do módulo.
    if (this.#vistos.has(idDoFornecedor)) return false;
    if (this.#vistos.size >= this.#tecto) {
      let aDeitar = Math.trunc(this.#tecto / 2);
      for (const antigo of this.#vistos) {
        if (aDeitar-- <= 0) break;
        this.#vistos.delete(antigo);
      }
    }
    this.#vistos.add(idDoFornecedor);
    return true;
  }

  /** Quantos ids estão na janela. Para os ensaios. */
  get tamanho(): number {
    return this.#vistos.size;
  }
}

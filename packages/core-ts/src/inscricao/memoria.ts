/**
 * Os três repositórios em memória (KAM-086).
 *
 * São o que CI e `dev` usam, e são o precedente do
 * `../sms/idempotencia.ts` — que também entregou `RegistoDeEnviosEmMemoria` ao
 * lado da porta, pela mesma razão: uma porta sem implementação nenhuma é uma
 * porta que ninguém exercita, e a primeira implementação a ser escrita decide a
 * semântica sem ninguém a rever.
 *
 * ## O que estes duplos **não** são
 *
 * Não são o adaptador SQL, e não substituem o que só a base responde. Três
 * coisas ficam fora, e a terceira é a que mais conta:
 *
 * 1. **RLS `FORCE`.** Um `Map` não filtra por `app.onboarding_id`. O que este
 *    ficheiro consegue garantir é que nenhuma consulta deste módulo procura por
 *    outra coisa que não um id ou um HMAC; que a base **recusa** o resto é a
 *    caixa que fica com credor nomeado no bloco.
 * 2. **Atomicidade a sério.** O `criar` é atómico porque o `Map` é síncrono e
 *    não porque alguém a garantiu. No adaptador, a atomicidade entre a chave de
 *    idempotência e a linha é uma transacção, e o índice único de `nif_hmac` é
 *    quem decide empates entre pedidos concorrentes.
 * 3. **O custo de uma escrita.** É a limitação que o critério 9 nomeia: aqui um
 *    `INSERT` e um `SELECT` custam o mesmo, e numa base não custam. O
 *    `./registo.ts` di-lo no cabeçalho.
 *
 * ## O `criar` **reafirma a unicidade do NIF**, e não só a chave
 *
 * Um duplo que só guardasse por chave de idempotência deixava passar dois casos
 * vivos com o mesmo `nif_hmac` — que é a coisa que o índice único do bloco
 * existe para impedir. Então os ensaios de duplicado ficavam verdes contra o
 * duplo e vermelhos contra a base, que é a pior ordem possível para descobrir
 * um defeito. A unicidade está aqui **e** fica no índice: duas afirmações da
 * mesma invariante, em dois sítios que falham por razões diferentes.
 */

import type {
  Caso,
  CasoNovo,
  Contadores,
  DesafioGuardado,
  Fase,
  Flag,
  RepositorioDeCasos,
  RepositorioDeOtp,
  Relogio,
} from "./contrato.ts";
import { faseViva } from "./contrato.ts";
import type { Telefone } from "./identificadores.ts";

/** Levantado quando o duplo recusa por unicidade. É o `23505` do adaptador. */
export class CasoDuplicadoError extends Error {
  override readonly name = "CasoDuplicadoError";

  constructor() {
    // Sem o `nif_hmac` na mensagem: um HMAC não é o NIF, mas é um
    // pseudónimo estável dele, e uma mensagem de erro acaba em ficheiro de log.
    super("ja existe um caso vivo com este nif_hmac");
  }
}

/** Os casos, num `Map`. */
export class CasosEmMemoria implements RepositorioDeCasos {
  readonly #porId = new Map<string, Caso>();
  readonly #porChave = new Map<string, string>();
  readonly #telefones = new Map<string, Telefone>();
  readonly #relogio: Relogio;
  #seguinte = 0;

  constructor(relogio: Relogio = () => new Date()) {
    this.#relogio = relogio;
  }

  async porId(id: string): Promise<Caso | null> {
    return this.#porId.get(id) ?? null;
  }

  async telefoneDe(id: string): Promise<Telefone | null> {
    return this.#telefones.get(id) ?? null;
  }

  async porChave(chave: string): Promise<Caso | null> {
    const id = this.#porChave.get(chave);
    return id === undefined ? null : (this.#porId.get(id) ?? null);
  }

  async porNifHmac(hmac: string): Promise<Caso | null> {
    for (const caso of this.#porId.values()) {
      if (caso.nifHmac === hmac && faseViva(caso.fase)) return caso;
    }
    return null;
  }

  async porTelefoneHmac(hmac: string): Promise<readonly Caso[]> {
    return [...this.#porId.values()].filter((c) => c.telefoneHmac === hmac && faseViva(c.fase));
  }

  async contarPorDispositivo(hmac: string, desde: Date): Promise<number> {
    return [...this.#porId.values()].filter(
      (c) => c.dispositivoHmac === hmac && c.criadoEm.getTime() >= desde.getTime(),
    ).length;
  }

  async criar(
    novo: CasoNovo,
    chave: string,
  ): Promise<{ readonly caso: Caso; readonly repetido: boolean }> {
    const jaCriado = await this.porChave(chave);
    if (jaCriado !== null) return { caso: jaCriado, repetido: true };
    const vivo = await this.porNifHmac(novo.nif.hmac);
    if (vivo !== null) throw new CasoDuplicadoError();

    // O id é sequencial com a forma de UUID e **não** aleatório: um duplo com
    // ids aleatórios dava diffs de evidência diferentes a cada corrida, e a
    // ordem de criação é o que um ensaio de duplicado precisa de poder afirmar.
    // O `tenant_id` é o que vem no `CasoNovo`, pré-alocado por quem chamou.
    this.#seguinte += 1;
    const id = idSequencial(this.#seguinte);
    const caso: Caso = {
      id,
      tenantId: novo.tenantId,
      fase: "registo",
      origem: novo.origem,
      nomeNegocio: novo.nomeNegocio,
      categoriaDeclarada: novo.categoriaDeclarada,
      nifHmac: novo.nif.hmac,
      telefoneHmac: novo.telefone.hmac,
      dispositivoHmac: novo.dispositivoHmac,
      redeHmac: novo.redeHmac,
      flags: [...novo.flags],
      activoSegundos: 0,
      criadoEm: this.#relogio(),
    };
    this.#porId.set(id, caso);
    this.#porChave.set(chave, id);
    // O telefone em claro fica **aqui** e não no `Caso`: no adaptador ele é o
    // `phone_enc`, lido só pelo `telefoneDe`. Guardá-lo no `Caso` punha-o em
    // todas as leituras, e o `Caso` é o que viaja.
    this.#telefones.set(id, novo.telefone);
    return { caso, repetido: false };
  }

  async marcarFase(id: string, fase: Fase): Promise<boolean> {
    const caso = this.#porId.get(id);
    if (caso === undefined) return false;
    this.#porId.set(id, { ...caso, fase });
    return true;
  }

  async acrescentarFlag(id: string, flag: Flag): Promise<boolean> {
    const caso = this.#porId.get(id);
    if (caso === undefined) return false;
    if (caso.flags.includes(flag)) return true;
    this.#porId.set(id, { ...caso, flags: [...caso.flags, flag] });
    return true;
  }

  async acumularActivo(id: string, segundos: number): Promise<number> {
    const caso = this.#porId.get(id);
    if (caso === undefined) return 0;
    const total = caso.activoSegundos + Math.max(0, Math.trunc(segundos));
    this.#porId.set(id, { ...caso, activoSegundos: total });
    return total;
  }

  /** Quantos casos existem. Para a bateria contar **casos** e não chamadas. */
  get quantos(): number {
    return this.#porId.size;
  }

  /** Todos os casos, pela ordem de criação. Para a bateria. */
  get todos(): readonly Caso[] {
    return [...this.#porId.values()];
  }
}

/** Um UUID canónico determinístico a partir de um inteiro. Ver o `criar`. */
export function idSequencial(n: number): string {
  const hex = n.toString(16).padStart(12, "0");
  return `00000000-0000-4000-8000-${hex}`;
}

/** Os desafios de OTP, num `Map`. */
export class OtpEmMemoria implements RepositorioDeOtp {
  readonly #porCaso = new Map<string, DesafioGuardado>();

  async guardar(desafio: DesafioGuardado): Promise<void> {
    this.#porCaso.set(desafio.onboardingId, desafio);
  }

  async actual(onboardingId: string): Promise<DesafioGuardado | null> {
    return this.#porCaso.get(onboardingId) ?? null;
  }

  async somarTentativa(onboardingId: string): Promise<number | null> {
    const desafio = this.#porCaso.get(onboardingId);
    if (desafio === undefined) return null;
    const tentativas = desafio.tentativas + 1;
    this.#porCaso.set(onboardingId, { ...desafio, tentativas });
    return tentativas;
  }

  async apagar(onboardingId: string): Promise<void> {
    this.#porCaso.delete(onboardingId);
  }
}

/**
 * Quantos instantes se guardam por chave.
 *
 * O tecto não é optimização: sem ele, a chave do orçamento de SMS guardava um
 * instante por envio de um dia inteiro, e a do limite de uma rede guardava um
 * por tentativa. Um atacante que batesse numa chave enchia a memória do
 * processo — o inverso do que o anti-abuso existe para fazer. É a mesma lição
 * que o `CORPOS_GUARDADOS` do `../sms/fake.ts` registou.
 */
export const INSTANTES_POR_CHAVE = 10_000;

/**
 * Os contadores de janela deslizante, num `Map`.
 *
 * Guarda instantes e **não um inteiro por chave**, e a diferença é o que faz a
 * janela deslizar: um contador que só soma precisa de alguém que o zere, e esse
 * alguém era um temporizador — isto é, um segundo relógio a decidir limites de
 * segurança.
 */
export class ContadoresEmMemoria implements Contadores {
  readonly #porChave = new Map<string, number[]>();

  async anotar(chave: string, em: Date, janelaMs: number): Promise<number> {
    const instantes = this.#limpos(chave, em, janelaMs);
    instantes.push(em.getTime());
    if (instantes.length > INSTANTES_POR_CHAVE) {
      instantes.splice(0, instantes.length - INSTANTES_POR_CHAVE);
    }
    this.#porChave.set(chave, instantes);
    return instantes.length;
  }

  async contar(chave: string, em: Date, janelaMs: number): Promise<number> {
    const instantes = this.#limpos(chave, em, janelaMs);
    this.#porChave.set(chave, instantes);
    return instantes.length;
  }

  async ultimo(chave: string): Promise<Date | null> {
    const instantes = this.#porChave.get(chave);
    if (instantes === undefined || instantes.length === 0) return null;
    // O último **registado** e não o último dentro de uma janela: a pergunta do
    // intervalo de 60 s é «quando foi a última vez», e uma janela aqui fazia a
    // resposta depender de qual das duas perguntas a chave serviu por último.
    return new Date(Math.max(...instantes));
  }

  /** Quantas chaves existem. Para a bateria medir o tecto de memória. */
  get chaves(): number {
    return this.#porChave.size;
  }

  #limpos(chave: string, em: Date, janelaMs: number): number[] {
    const corte = em.getTime() - janelaMs;
    return (this.#porChave.get(chave) ?? []).filter((t) => t > corte);
  }
}

/**
 * Os duplos em memória do passo guiado (KAM-093).
 *
 * São o que CI e `dev` usam, pela razão do `../inscricao/memoria.ts`: as três
 * tabelas que o bloco nomeia não existem (ver a nota do `./contrato.ts`), e o
 * `onboarding-web` recusa arrancar em `prod` enquanto não existirem.
 *
 * ## Cada duplo faz a pergunta difícil, e não a fácil
 *
 * A lição do KAM-091 — «um duplo entrega a forma mais hostil para a asserção»
 * — aplica-se aqui em dois sítios:
 *
 * * o `transitar` é *compare-and-set* **de verdade**: lê o estado, compara com
 *   o esperado e escreve no mesmo passo síncrono, sem `await` pelo meio. Um
 *   duplo que escrevesse sempre fazia o «FINISH 2× ⇒ 1 canal» passar pelo duplo
 *   e não pelo código;
 * * a `CapacidadeEmMemoria` conta pela janela e não por um contador: uma
 *   reserva de há oito dias **não** conta, e uma reserva repetida do mesmo caso
 *   conta uma vez.
 */

import {
  type AvisoDoGuia,
  type CapacityGate,
  type EstadoDoGuia,
  type EstadoGuardado,
  type FilaDeRevisao,
  type GateDoEs,
  type GatesDoOnboarding,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  type MensagemAoDono,
  type MotivoDeFalha,
  type Preflight,
  type RepositorioDoGuia,
} from "./contrato.ts";

type Relogio = () => Date;

const DIA_MS = 86_400_000;

/** O repositório do guia, em memória. */
export class GuiaEmMemoria implements RepositorioDoGuia {
  readonly #linhas = new Map<string, EstadoGuardado>();
  readonly #relogio: Relogio;

  constructor(relogio: Relogio = () => new Date()) {
    this.#relogio = relogio;
  }

  async ler(onboardingId: string): Promise<EstadoGuardado | null> {
    return this.#linhas.get(onboardingId) ?? null;
  }

  async abrir(onboardingId: string): Promise<EstadoGuardado> {
    const existente = this.#linhas.get(onboardingId);
    if (existente !== undefined) return existente;
    const nova: EstadoGuardado = {
      onboardingId,
      estado: "pre_voo",
      preflight: null,
      iniciadoEm: null,
      motivo: null,
      tentativaId: null,
      phoneNumberId: null,
      wabaId: null,
      numeroConfirmado: false,
      sincronizado: false,
      actualizadoEm: this.#relogio(),
    };
    this.#linhas.set(onboardingId, nova);
    return nova;
  }

  async gravarPreflight(onboardingId: string, preflight: Preflight): Promise<void> {
    const linha = this.#linhas.get(onboardingId);
    if (linha === undefined) return;
    this.#linhas.set(onboardingId, { ...linha, preflight, actualizadoEm: this.#relogio() });
  }

  async transitar(
    onboardingId: string,
    de: EstadoDoGuia,
    para: EstadoDoGuia,
    campos: Partial<
      Pick<EstadoGuardado, "iniciadoEm" | "motivo" | "tentativaId" | "phoneNumberId" | "wabaId">
    >,
  ): Promise<boolean> {
    // Síncrono do `get` ao `set`: é o que faz isto ser *compare-and-set*.
    const linha = this.#linhas.get(onboardingId);
    if (linha === undefined || linha.estado !== de) return false;
    this.#linhas.set(onboardingId, {
      ...linha,
      ...campos,
      estado: para,
      actualizadoEm: this.#relogio(),
    });
    return true;
  }

  async marcar(onboardingId: string, facto: "numeroConfirmado" | "sincronizado"): Promise<void> {
    const linha = this.#linhas.get(onboardingId);
    if (linha === undefined || linha[facto]) return;
    this.#linhas.set(onboardingId, { ...linha, [facto]: true, actualizadoEm: this.#relogio() });
  }

  async iniciadosAntesDe(antes: Date): Promise<readonly string[]> {
    return [...this.#linhas.values()]
      .filter((l) => l.estado === "iniciado" && l.iniciadoEm !== null && l.iniciadoEm < antes)
      .map((l) => l.onboardingId);
  }

  async porPhoneNumberId(phoneNumberId: string): Promise<string | null> {
    for (const linha of this.#linhas.values()) {
      if (linha.phoneNumberId === phoneNumberId) return linha.onboardingId;
    }
    return null;
  }
}

/** O `CapacityGate`, em memória, por janela deslizante de sete dias. */
export class CapacidadeEmMemoria implements CapacityGate {
  readonly #reservas = new Map<string, Date>();
  readonly #relogio: Relogio;
  readonly #maximo: number;
  readonly #janelaMs: number;

  constructor(
    opcoes: {
      readonly relogio?: Relogio;
      /** `es_max_por_7d`. Por omissão, o `LIMITE_DE_ONBOARDINGS` CONFIRMADO no `E1`. */
      readonly maximo?: number;
    } = {},
  ) {
    this.#relogio = opcoes.relogio ?? (() => new Date());
    this.#maximo = opcoes.maximo ?? LIMITE_DE_ONBOARDINGS;
    this.#janelaMs = JANELA_DE_ONBOARDINGS_DIAS * DIA_MS;
  }

  async reserve(onboardingId: string): Promise<"granted" | "lista_espera"> {
    const agora = this.#relogio();
    const desde = agora.getTime() - this.#janelaMs;
    const minha = this.#reservas.get(onboardingId);
    // Repetir a reserva do mesmo caso não gasta outro lugar: é o que deixa a
    // retoma pela mesma ligação não custar capacidade duas vezes.
    if (minha !== undefined && minha.getTime() > desde) return "granted";
    let vivas = 0;
    for (const [id, em] of this.#reservas) {
      if (id !== onboardingId && em.getTime() > desde) vivas += 1;
    }
    if (vivas >= this.#maximo) return "lista_espera";
    this.#reservas.set(onboardingId, agora);
    return "granted";
  }

  async release(onboardingId: string): Promise<void> {
    this.#reservas.delete(onboardingId);
  }

  /** Quantas reservas vivas há agora. Para os ensaios e para o *gauge*. */
  vivas(): number {
    const desde = this.#relogio().getTime() - this.#janelaMs;
    return [...this.#reservas.values()].filter((em) => em.getTime() > desde).length;
  }
}

/** Os gates, em memória. O último valor de cada `(caso, gate)`. */
export class GatesEmMemoria implements GatesDoOnboarding {
  readonly gates = new Map<string, { readonly verde: boolean; readonly motivo: string }>();

  async marcar(onboardingId: string, gate: GateDoEs, verde: boolean, motivo: string): Promise<void> {
    this.gates.set(`${onboardingId}:${gate}`, { verde, motivo });
  }

  de(onboardingId: string, gate: GateDoEs): { readonly verde: boolean; readonly motivo: string } | null {
    return this.gates.get(`${onboardingId}:${gate}`) ?? null;
  }
}

/** A fila de revisão, em memória. Idempotente por `(caso, tipo)`. */
export class RevisaoEmMemoria implements FilaDeRevisao {
  readonly abertos = new Map<string, MotivoDeFalha>();

  async abrir(onboardingId: string, tipo: "es_falhado", motivo: MotivoDeFalha): Promise<void> {
    const chave = `${onboardingId}:${tipo}`;
    if (!this.abertos.has(chave)) this.abertos.set(chave, motivo);
  }
}

/**
 * Os avisos ao dono, em memória: guarda o que se mandou, e por que via.
 *
 * A via é `sms` ou `email` e **não pode ser outra** — o tipo não o deixa. É a
 * metade do critério 7 que um tipo consegue impor.
 */
export class AvisosEmMemoria implements AvisoDoGuia {
  readonly enviados: {
    readonly onboardingId: string;
    readonly mensagem: MensagemAoDono;
    readonly ligacao: string;
    readonly via: "sms" | "email";
  }[] = [];

  async avisar(onboardingId: string, mensagem: MensagemAoDono, ligacao: string): Promise<void> {
    this.enviados.push({ onboardingId, mensagem, ligacao, via: "sms" });
  }
}

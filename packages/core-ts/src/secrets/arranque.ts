/**
 * Comportamento de arranque e janela de tolerância (KAM-010).
 *
 * O critério de aceitação do ticket pede três coisas que não são do provedor —
 * são da política de quem o usa — e por isso vivem aqui:
 *
 * 1. um serviço sem segredo obrigatório **falha ao arrancar**, com mensagem que
 *    nomeia o segredo e nunca o valor;
 * 2. em `prod`, cofre inacessível no arranque ⇒ **não arranca**;
 * 3. depois do arranque, mantém o último valor conhecido durante **15 minutos**
 *    (*proposta* — ver `TTL_ULTIMO_VALOR_MS`).
 *
 * Ter isto separado das implementações é o que faz as três regras valerem para
 * Env, para o *fake* de OpenBao e para o Doppler sem as reescrever três vezes.
 */

import {
  type Ambiente,
  CofreInacessivelError,
  SecretAusenteError,
  type SecretProvider,
  type SecretRef,
  type SecretRingTuple,
  validarRef,
} from "./port.ts";

/**
 * Janela em que um valor já conhecido continua a servir com o cofre em baixo.
 *
 * **Valor de desenho, *proposta*.** Os 15 minutos vêm do critério de aceitação
 * do KAM-010 e não de uma medição. Calibra-se quando houver dois números que
 * hoje não existem: o tempo de recuperação observado do cofre (contrato de
 * serviço da Doppler, ou MTTR do OpenBao nos Clusters) e a duração de uma
 * entrega da Meta com retentativas (`E1`: a Meta re-entrega até 7 dias, o que
 * torna uma janela curta menos perigosa do que parece). O ensaio pertence ao
 * KAM-083 (runbook) e à rotação do KAM-072.
 *
 * O sentido da escolha: a janela protege contra uma falha de **disponibilidade**
 * do cofre, não contra uma **revogação**. Ver `Secrets.get`.
 */
export const TTL_ULTIMO_VALOR_MS = 15 * 60 * 1000;

/**
 * Levantado quando o arranque não pode continuar. Nunca contém valores.
 *
 * Campos à mão e não propriedades de parâmetro, pela razão que `port.ts`
 * explica: `erasableSyntaxOnly`.
 */
export class ArranqueAbortadoError extends Error {
  override readonly name = "ArranqueAbortadoError";
  readonly servico: string;
  readonly motivo: string;
  readonly segredos: readonly SecretRef[];

  constructor(servico: string, motivo: string, segredos: readonly SecretRef[] = []) {
    super(
      `arranque abortado (${servico}): ${motivo}` +
        (segredos.length > 0 ? `; segredos: ${segredos.join(", ")}` : ""),
    );
    this.servico = servico;
    this.motivo = motivo;
    this.segredos = segredos;
  }
}

/** Opções de `Secrets.arrancar`. */
export interface SecretsOpcoes {
  /** Nome do serviço, só para a mensagem de erro. */
  readonly servico: string;
  readonly provider: SecretProvider;
  /**
   * Segredos sem os quais o serviço não serve pedidos.
   *
   * São referências do inventário (`ops/secrets-inventory.yaml`), e é a
   * ferramenta `tools/secrets_inventory` que garante que nenhuma delas é um
   * nome que o inventário não conhece.
   */
  readonly obrigatorios: readonly SecretRef[];
  /** Por omissão, `TTL_ULTIMO_VALOR_MS`. */
  readonly ttlUltimoValorMs?: number;
  /** Relógio injectável, para os testes. */
  readonly agora?: () => number;
  /**
   * Para onde vão os avisos.
   *
   * Recebe texto já seguro: nenhum aviso deste módulo contém valores. Por
   * omissão não faz nada, porque o *logger* com *allowlist* de campos
   * (`docs/tecnica/08` §7.3) é do KAM-025 e escolher um aqui era alargar escopo.
   */
  readonly aviso?: (mensagem: string) => void;
}

/**
 * Fachada de segredos de um serviço: carrega ao arranque, serve depois.
 */
export class Secrets {
  readonly #provider: SecretProvider;
  readonly #servico: string;
  readonly #obrigatorios: ReadonlySet<string>;
  readonly #ttl: number;
  readonly #agora: () => number;
  readonly #aviso: (mensagem: string) => void;
  readonly #cache = new Map<string, { anel: SecretRingTuple; em: number }>();

  private constructor(opcoes: Required<Pick<SecretsOpcoes, "servico" | "provider">> & {
    obrigatorios: ReadonlySet<string>;
    ttl: number;
    agora: () => number;
    aviso: (mensagem: string) => void;
  }) {
    this.#provider = opcoes.provider;
    this.#servico = opcoes.servico;
    this.#obrigatorios = opcoes.obrigatorios;
    this.#ttl = opcoes.ttl;
    this.#agora = opcoes.agora;
    this.#aviso = opcoes.aviso;
  }

  /** Ambiente do provedor subjacente. */
  get ambiente(): Ambiente {
    return this.#provider.ambiente;
  }

  /** Nome do provedor subjacente. */
  get provedor(): string {
    return this.#provider.nome;
  }

  /**
   * Arranca: verifica o cofre, carrega os obrigatórios, ou falha.
   *
   * @throws {ArranqueAbortadoError} sempre que o serviço não deve servir pedidos.
   */
  static async arrancar(opcoes: SecretsOpcoes): Promise<Secrets> {
    const { provider, servico } = opcoes;
    const refs = opcoes.obrigatorios.map(validarRef);
    const secrets = new Secrets({
      servico,
      provider,
      obrigatorios: new Set(refs),
      ttl: opcoes.ttlUltimoValorMs ?? TTL_ULTIMO_VALOR_MS,
      agora: opcoes.agora ?? Date.now,
      aviso: opcoes.aviso ?? (() => {}),
    });

    try {
      await provider.health();
    } catch (erro) {
      const motivo = erro instanceof Error ? erro.message : "cofre inacessível";
      if (provider.ambiente === "prod") {
        // A letra do critério de aceitação. Em `prod` não há arranque
        // optimista: um GWY a servir pedidos da Meta sem conseguir ler o App
        // Secret devolve 4xx a tudo, e a Meta re-entrega durante sete dias
        // (`E1`) — o que transforma uma falha de cofre num atraso recuperável
        // em vez de uma avaria silenciosa.
        throw new ArranqueAbortadoError(servico, motivo);
      }
      // Fora de `prod` avisa-se e segue-se. Não é tolerância a mais: se algum
      // obrigatório não se conseguir ler, o passo seguinte aborta de qualquer
      // modo — e aborta com uma mensagem melhor, porque nomeia o segredo.
      secrets.#aviso(`cofre inacessível no arranque, a continuar em ${provider.ambiente}: ${motivo}`);
    }

    const ausentes: SecretRef[] = [];
    const inacessiveis: string[] = [];
    for (const ref of refs) {
      try {
        const anel = await provider.getRing(ref);
        secrets.#cache.set(ref, { anel, em: secrets.#agora() });
      } catch (erro) {
        if (erro instanceof SecretAusenteError) ausentes.push(ref);
        else if (erro instanceof CofreInacessivelError) inacessiveis.push(ref);
        else throw erro;
      }
    }

    if (ausentes.length > 0) {
      // Todos de uma vez, e não o primeiro: quem configura um ambiente novo
      // corrige uma lista, não descobre um segredo por reinício.
      throw new ArranqueAbortadoError(servico, "segredos obrigatórios ausentes", ausentes);
    }
    if (inacessiveis.length > 0) {
      throw new ArranqueAbortadoError(
        servico,
        "cofre inacessível ao carregar segredos obrigatórios",
        inacessiveis,
      );
    }
    return secrets;
  }

  /** Valor actual. Ver `getRing` para a política de cache. */
  async get(ref: SecretRef): Promise<string> {
    const [actual] = await this.getRing(ref);
    return actual;
  }

  /**
   * `[actual, anterior]`, com a janela de tolerância.
   *
   * **A janela cobre indisponibilidade, não revogação.** Um
   * `CofreInacessivelError` serve-se da cache enquanto ela for fresca; um
   * `SecretAusenteError` — o segredo deixou de existir no cofre — propaga-se
   * sempre. Se a cache tapasse os dois casos, apagar um token comprometido
   * deixaria de o desactivar durante quinze minutos, e revogar é exactamente a
   * acção que tem de ser imediata (`docs/tecnica/08` §10).
   */
  async getRing(ref: SecretRef): Promise<SecretRingTuple> {
    const chave = validarRef(ref);
    try {
      const anel = await this.#provider.getRing(chave);
      this.#cache.set(chave, { anel, em: this.#agora() });
      return anel;
    } catch (erro) {
      if (!(erro instanceof CofreInacessivelError)) throw erro;
      const guardado = this.#cache.get(chave);
      if (guardado === undefined) throw erro;
      const idade = this.#agora() - guardado.em;
      if (idade >= this.#ttl) {
        throw new CofreInacessivelError(
          this.#provider.nome,
          `${erro.motivo}; último valor conhecido de ${chave} tem ${Math.floor(idade / 1000)}s ` +
            `e a janela é de ${Math.floor(this.#ttl / 1000)}s`,
        );
      }
      this.#aviso(
        `cofre inacessível; a servir o último valor conhecido de ${chave} ` +
          `(${Math.floor(idade / 1000)}s de ${Math.floor(this.#ttl / 1000)}s)`,
      );
      return guardado.anel;
    }
  }

  /** Delega no provedor; a cache não guarda listas de versões. */
  async versions(ref: SecretRef): Promise<readonly string[]> {
    return this.#provider.versions(validarRef(ref));
  }

  /** `true` se `ref` foi declarado obrigatório no arranque. */
  eObrigatorio(ref: SecretRef): boolean {
    return this.#obrigatorios.has(ref);
  }
}

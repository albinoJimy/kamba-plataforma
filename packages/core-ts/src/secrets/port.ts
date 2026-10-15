/**
 * A porta `SecretProvider` (KAM-010).
 *
 * Isto é o contrato, e mais nada: não há aqui leitura de ambiente, nem HTTP,
 * nem cofre. As implementações vivem em `env.ts`, `openbao-fake.ts` e
 * `doppler.ts`, e a suite de contrato (`tests/secrets.contrato.test.ts`) corre
 * a mesma bateria sobre todas — é isso que torna «trocar de implementação é só
 * configuração» uma afirmação verificável e não uma intenção.
 *
 * Três regras atravessam este ficheiro inteiro:
 *
 * 1. **Nenhuma mensagem de erro contém um valor de segredo.** Nomeia o segredo,
 *    diz o que falta, e cala-se quanto ao conteúdo (`docs/tecnica/08` §5, e o DoD
 *    «Sem segredos» de `specs/01` §3).
 * 2. **O que atravessa fronteiras é a referência, nunca o valor.** Ver
 *    `SecretRef`.
 * 3. **O cofre pode estar em baixo.** Um erro de indisponibilidade é de uma
 *    classe diferente de «este segredo não existe», porque a reacção certa é
 *    diferente: o primeiro tolera-se durante uma janela (ver `Secrets` em
 *    `arranque.ts`), o segundo nunca.
 */

/**
 * Referência opaca a um segredo no cofre.
 *
 * É isto — e nunca o valor — que atravessa uma fronteira de persistência, de
 * evento ou de log. O caso comum é a referência ser o `id` do segredo no
 * inventário (`ops/secrets-inventory.yaml`): `meta_app_secret`,
 * `pepper_contact_hmac`. Para famílias com uma instância por tenant (o token de
 * cliente do Embedded Signup é a única no Piloto) a referência é o `id` da
 * família seguido de um sufixo opaco que o cofre cunhou:
 * `meta_client_token/7f3c…`.
 *
 * **Quem recebe uma referência não a interpreta.** Não a parte, não deriva
 * `tenant_id` dela, não assume que o sufixo é um UUID. A única operação válida
 * sobre uma referência é entregá-la a um `SecretProvider`.
 *
 * O KAM-003 define a coluna que guarda uma destas referências
 * (`tenant_channels.token_ref`); este ticket não define essa coluna nem o
 * formato do sufixo, e de propósito: a coluna só tem de guardar texto opaco.
 */
export type SecretRef = string;

/**
 * O par de versões vivas de um segredo.
 *
 * `anterior` é `null` quando o segredo nunca foi rodado, ou quando a
 * implementação não guarda histórico. Um consumidor que aceita as duas versões
 * — o GWY, na validação de `X-Hub-Signature-256` (KAM-013) — tem de tratar
 * `null` como «só há uma», e não como erro.
 */
export interface SecretRing {
  readonly actual: string;
  readonly anterior: string | null;
}

/** O par `[actual, anterior]` na forma que o critério de aceitação pede. */
export type SecretRingTuple = readonly [actual: string, anterior: string | null];

/** Ambientes com projectos de cofre separados (`docs/tecnica/09` §6). */
export const AMBIENTES = ["dev", "staging", "prod"] as const;

/** Ambiente em que o processo corre. */
export type Ambiente = (typeof AMBIENTES)[number];

/** `true` se `valor` é um dos três ambientes canónicos. */
export function isAmbiente(valor: unknown): valor is Ambiente {
  return typeof valor === "string" && (AMBIENTES as readonly string[]).includes(valor);
}

/**
 * Forma aceite de uma referência.
 *
 * O `id` da família é `snake_case` minúsculo, como no inventário. O sufixo,
 * quando existe, é opaco mas tem de ser imprimível e sem espaços — assim uma
 * referência nunca precisa de *escaping* para entrar num log ou numa coluna.
 *
 * O limite de 200 caracteres não é estética: é o que impede que alguém passe um
 * **valor** de segredo onde devia passar uma referência e o veja aparecer numa
 * mensagem de erro.
 */
const REF = /^[a-z][a-z0-9_]{2,63}(\/[A-Za-z0-9._:-]{1,128})?$/;

/*
 * Nota sobre a forma destas classes: os campos são declarados e atribuídos à
 * mão, em vez de propriedades de parâmetro (`constructor(readonly ref: string)`).
 * Não é estilo — `erasableSyntaxOnly` do `tsconfig.base.json` proíbe-as, porque
 * o Node 24 apaga tipos mas não transforma código e uma propriedade de parâmetro
 * rebenta em execução com `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`
 * (`docs/adr/ADR-L001-toolchain.md`).
 */

/** Levantado quando a referência pedida não tem a forma de uma referência. */
export class SecretRefInvalidaError extends Error {
  override readonly name = "SecretRefInvalidaError";
  /** Comprimento da cadeia recusada. **Nunca o seu conteúdo.** */
  readonly comprimento: number;

  constructor(ref: string) {
    // Comprimento e não conteúdo: se alguém passou um valor por engano, o valor
    // não entra no log por causa desta mensagem.
    super(
      `referência de segredo inválida (${ref.length} caracteres); ` +
        `esperava <id> ou <id>/<instância>, com <id> em snake_case`,
    );
    this.comprimento = ref.length;
  }
}

/** Levantado quando um segredo obrigatório não existe no cofre. */
export class SecretAusenteError extends Error {
  override readonly name = "SecretAusenteError";
  readonly ref: SecretRef;
  readonly provedor: string;

  constructor(ref: SecretRef, provedor: string) {
    super(`segredo ausente: ${ref} (provedor ${provedor})`);
    this.ref = ref;
    this.provedor = provedor;
  }
}

/**
 * Levantado quando o cofre não responde.
 *
 * Distinta de `SecretAusenteError` de propósito: esta tolera-se durante uma
 * janela depois do arranque (`Secrets`), aquela nunca se tolera.
 */
export class CofreInacessivelError extends Error {
  override readonly name = "CofreInacessivelError";
  readonly provedor: string;
  readonly motivo: string;

  constructor(provedor: string, motivo: string) {
    super(`cofre inacessível (provedor ${provedor}): ${motivo}`);
    this.provedor = provedor;
    this.motivo = motivo;
  }
}

/** Levantado quando o provedor está configurado para outro ambiente. */
export class AmbienteErradoError extends Error {
  override readonly name = "AmbienteErradoError";
  readonly provedor: string;
  readonly esperado: Ambiente;
  readonly obtido: string;

  constructor(provedor: string, esperado: Ambiente, obtido: string) {
    super(
      `credencial de cofre do ambiente ${JSON.stringify(obtido)} usada contra ` +
        `${esperado} (provedor ${provedor}); recusado`,
    );
    this.provedor = provedor;
    this.esperado = esperado;
    this.obtido = obtido;
  }
}

/**
 * A porta.
 *
 * Só leitura. Cunhar uma referência nova — escrever um segredo no cofre e
 * receber de volta a referência que a base de dados guarda — é o que o KAM-016
 * (Embedded Signup v4) vai precisar, e **não está aqui**: nenhum serviço do
 * Piloto escreve no cofre, e uma porta de escrita sem consumidor é desenho
 * especulativo. A lacuna está declarada em `docs/adr/ADR-L002-injeccao-de-segredos.md`
 * §6 para que o KAM-016 não a descubra tarde.
 */
export interface SecretProvider {
  /** Nome curto da implementação, para mensagens e métricas: `env`, `openbao-fake`, `doppler`. */
  readonly nome: string;

  /** Ambiente para que este provedor está configurado. */
  readonly ambiente: Ambiente;

  /**
   * Devolve o valor actual.
   *
   * @throws {SecretRefInvalidaError} se `ref` não tem forma de referência.
   * @throws {SecretAusenteError} se o segredo não existe.
   * @throws {CofreInacessivelError} se o cofre não responde.
   */
  get(ref: SecretRef): Promise<string>;

  /**
   * Devolve `[actual, anterior]`.
   *
   * O critério de aceitação do KAM-010 pede exactamente esta forma, para o Meta
   * App Secret. Vale para qualquer segredo: quem não tem anterior recebe `null`
   * na segunda posição.
   */
  getRing(ref: SecretRef): Promise<SecretRingTuple>;

  /**
   * Identificadores das versões vivas, da mais recente para a mais antiga.
   *
   * O conteúdo de cada identificador é do provedor (um inteiro no OpenBao KV v2,
   * um rótulo no Env); a **ordem** é parte do contrato, e `versions()[0]` tem de
   * corresponder ao valor que `get()` devolve.
   */
  versions(ref: SecretRef): Promise<readonly string[]>;

  /**
   * Resolve se o cofre está acessível; rejeita com `CofreInacessivelError` se não.
   *
   * Não lê segredo nenhum: é a pergunta do arranque em `prod`, onde a resposta
   * «não sei» significa «não arranques».
   */
  health(): Promise<void>;
}

/** Valida a forma de uma referência e devolve-a, para encadear. */
export function validarRef(ref: string): SecretRef {
  if (typeof ref !== "string" || !REF.test(ref)) {
    throw new SecretRefInvalidaError(typeof ref === "string" ? ref : "");
  }
  return ref;
}

/** `id` da família de uma referência (a parte antes de `/`). */
export function familiaDaRef(ref: SecretRef): string {
  const i = validarRef(ref).indexOf("/");
  return i === -1 ? ref : ref.slice(0, i);
}

/** Converte o par para a forma de objecto, quando ela lê melhor no sítio de uso. */
export function anel([actual, anterior]: SecretRingTuple): SecretRing {
  return { actual, anterior };
}

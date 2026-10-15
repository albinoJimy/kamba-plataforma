/**
 * `EnvSecretProvider` — a implementação de desenvolvimento (KAM-010).
 *
 * Lê os segredos do ambiente do processo. É a implementação que os serviços
 * usam em `dev`, e é também a que o `ADR-L002` escolhe como **mecanismo de
 * injecção** em todos os ambientes do Piloto: em `staging` e `prod` quem enche
 * o ambiente é o lançador do cofre (`doppler run -- …`), e o processo continua a
 * ler daqui. Por isso esta classe não é um brinquedo de `dev` — é o caminho de
 * produção, e é tratada como tal.
 *
 * O que ela **não** faz, de propósito: não lê ficheiros, não vai à rede, não
 * tem cache. O ambiente de um processo não muda depois do `exec`, pelo que uma
 * cache aqui seria cache de uma coisa imutável.
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

/** Subconjunto de `process.env` de que este módulo depende. */
export type ProcessEnv = Record<string, string | undefined>;

/** Prefixo de todas as variáveis que este provedor lê. */
export const PREFIXO = "KAMBA_SECRET_";

/** Sufixo da variável que guarda a versão anterior de um segredo. */
export const SUFIXO_ANTERIOR = "_ANTERIOR";

/** Rótulos de versão que este provedor sabe produzir, do mais recente ao mais antigo. */
export const VERSOES = ["actual", "anterior"] as const;

/**
 * Nome da variável de ambiente que guarda uma referência.
 *
 * A família (a parte antes de `/`) sobe a maiúsculas, porque é `snake_case`
 * conhecido e lê-se melhor num `.env`. A instância (a parte depois de `/`)
 * **mantém a caixa**, com os caracteres fora de `[A-Za-z0-9]` trocados por `_`:
 * se subisse a maiúsculas, duas referências que diferem só na caixa passariam a
 * designar a mesma variável, e um tenant leria o token de outro. O separador
 * `__` (dois sublinhados) marca a fronteira entre família e instância.
 *
 * ```
 * meta_app_secret            → KAMBA_SECRET_META_APP_SECRET
 * meta_client_token/7f3cAb   → KAMBA_SECRET_META_CLIENT_TOKEN__7f3cAb
 * ```
 *
 * **Limite conhecido:** em Windows as variáveis de ambiente não distinguem
 * maiúsculas de minúsculas, pelo que a garantia de unicidade acima vale em
 * Linux (onde os serviços correm, `docs/tecnica/09` §3.1) e não num `cmd.exe`. O
 * `OpenBaoFakeProvider` não tem este limite e é o que os testes usam para o caso
 * por tenant.
 */
export function nomeDaVariavel(ref: SecretRef): string {
  const limpo = validarRef(ref);
  const corte = limpo.indexOf("/");
  if (corte === -1) return PREFIXO + limpo.toUpperCase();
  const familia = limpo.slice(0, corte).toUpperCase();
  const instancia = limpo.slice(corte + 1).replace(/[^A-Za-z0-9]/g, "_");
  return `${PREFIXO}${familia}__${instancia}`;
}

/** Opções de construção. */
export interface EnvSecretProviderOpcoes {
  /** Ambiente em que o processo corre. */
  readonly ambiente: Ambiente;
  /** O ambiente a ler. Por omissão, `process.env`. */
  readonly env?: ProcessEnv;
}

/**
 * Provedor que lê o ambiente do processo.
 */
export class EnvSecretProvider implements SecretProvider {
  readonly nome = "env";
  readonly ambiente: Ambiente;
  readonly #env: ProcessEnv;

  constructor(opcoes: EnvSecretProviderOpcoes) {
    this.ambiente = opcoes.ambiente;
    this.#env = opcoes.env ?? process.env;
  }

  /**
   * O ambiente está sempre acessível.
   *
   * Dizer `ok` aqui não é optimismo: se o processo arrancou, o seu ambiente
   * existe. Um ambiente **vazio** não é um cofre em baixo — é um segredo
   * ausente, e quem o descobre é `get`, com o nome do segredo na mensagem.
   */
  async health(): Promise<void> {
    if (typeof this.#env !== "object" || this.#env === null) {
      throw new CofreInacessivelError(this.nome, "ambiente do processo indisponível");
    }
  }

  async get(ref: SecretRef): Promise<string> {
    const valor = this.#ler(nomeDaVariavel(ref));
    if (valor === null) throw new SecretAusenteError(validarRef(ref), this.nome);
    return valor;
  }

  async getRing(ref: SecretRef): Promise<SecretRingTuple> {
    const base = nomeDaVariavel(ref);
    const actual = this.#ler(base);
    if (actual === null) throw new SecretAusenteError(validarRef(ref), this.nome);
    return [actual, this.#ler(base + SUFIXO_ANTERIOR)];
  }

  async versions(ref: SecretRef): Promise<readonly string[]> {
    const base = nomeDaVariavel(ref);
    if (this.#ler(base) === null) throw new SecretAusenteError(validarRef(ref), this.nome);
    const vivas: string[] = ["actual"];
    if (this.#ler(base + SUFIXO_ANTERIOR) !== null) vivas.push("anterior");
    return vivas;
  }

  /**
   * Lê uma variável, tratando o vazio como ausência.
   *
   * `KAMBA_SECRET_X=` é um erro de configuração que se parece com um segredo
   * definido. Tratá-lo como ausente faz o serviço falhar no arranque com o nome
   * do segredo, que é o comportamento que o critério de aceitação pede — em vez
   * de assinar pedidos com a chave vazia e descobri-lo quando a Meta devolver
   * 401.
   */
  #ler(nome: string): string | null {
    const bruto = this.#env[nome];
    if (bruto === undefined) return null;
    const valor = bruto.trim();
    return valor === "" ? null : valor;
  }
}

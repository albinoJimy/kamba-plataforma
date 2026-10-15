/**
 * `Motor` — o que guarda os bytes, **sem** noção de tenant (KAM-011).
 *
 * É a costura por baixo da porta. Um motor recebe chaves já validadas e faz o
 * que lhe mandam; não decide quem pode o quê. Essa decisão é de
 * `ArmazenamentoPorTenant` (`guarda.ts`), que é a única coisa que fala com um
 * motor.
 *
 * **Um motor nunca se entrega a um consumidor.** Não é exportado pelo índice do
 * módulo como forma de uso: as fábricas (`criarStorageFake`, `criarStorageS3`)
 * devolvem a porta, já com a guarda. Quem instancia um motor à mão e lhe chama
 * `get` saltou o isolamento — e é por isso que os métodos aqui não têm `ctx`:
 * para que a diferença se veja na assinatura.
 */

/** Metadados na forma em que o motor os guarda: pares de texto. */
export interface MetaBruta {
  readonly contentType: string;
  /** Nomes em minúsculas, com hífen; valores em ASCII imprimível. */
  readonly metadados: Readonly<Record<string, string>>;
}

/** O que o motor sabe de um objecto. */
export interface InfoBruta extends MetaBruta {
  readonly tamanho: number;
}

/** Uma entrada de listagem. */
export interface ItemListado {
  readonly chave: string;
  readonly tamanho: number;
}

/** Resultado de `put`: o que foi efectivamente escrito. */
export interface Escrito {
  readonly tamanho: number;
  /** SHA-256 dos bytes enviados, em hexadecimal minúsculo. */
  readonly sha256: string;
}

export interface Motor {
  /** `fake`, `s3`. */
  readonly nome: string;

  put(chave: string, corpo: AsyncIterable<Uint8Array>, meta: MetaBruta): Promise<Escrito>;

  /** @throws {ObjectoInexistenteError} */
  get(chave: string): Promise<AsyncIterable<Uint8Array>>;

  /** @throws {ObjectoInexistenteError} */
  head(chave: string): Promise<InfoBruta>;

  /** Idempotente. */
  delete(chave: string): Promise<void>;

  /**
   * Até `maximo` entradas sob o prefixo, por ordem de chave. `truncada` diz se
   * havia mais.
   */
  list(
    prefixo: string,
    maximo: number,
  ): Promise<{ readonly itens: readonly ItemListado[]; readonly truncada: boolean }>;

  /** URL de leitura do objecto, válida durante `ttlSegundos`. */
  signUrl(chave: string, ttlSegundos: number): Promise<string>;
}

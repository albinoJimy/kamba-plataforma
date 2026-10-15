/**
 * A porta `StorageProvider` (KAM-011, ADR-014).
 *
 * Isto é o contrato, e mais nada: não há aqui HTTP, nem assinatura, nem
 * memória. Quem guarda os bytes é um `Motor` (`motor.ts`) — o S3 em `s3.ts`, o
 * de memória em `fake.ts` — e quem impõe o isolamento por tenant é **uma só**
 * classe, `ArmazenamentoPorTenant` (`guarda.ts`), que embrulha qualquer motor.
 * É por isso que a implementação *fake* e a S3 não podem divergir no que
 * recusam: a recusa não é delas.
 *
 * Quatro regras atravessam este módulo inteiro:
 *
 * 1. **Toda a operação leva `ctx.tenantId`.** Não há sobrecarga sem contexto,
 *    nem valor por omissão, nem «modo administrador». Trabalho que atravessa
 *    tenants (a purga do KAM-071) itera tenants e chama a porta uma vez por
 *    cada um.
 * 2. **A chave diz de quem é o objecto**, e a porta confere-o antes de falar
 *    com o servidor: `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`
 *    (`docs/tecnica/08` §3.1 e §3.8). Uma chave de outro tenant é recusada,
 *    exista ou não o objecto — a resposta não revela qual dos dois.
 * 3. **Uma URL assinada vive no máximo 300 s** (`docs/tecnica/08` §3.8).
 * 4. **Nenhuma mensagem de erro contém uma credencial nem uma URL assinada.**
 *    Uma URL assinada é uma credencial com prazo.
 */

/**
 * Contexto de quem chama.
 *
 * `tenantId` é o UUID do tenant na forma canónica. Vem do estado da conversa ou
 * do pedido autenticado, **nunca** de texto do utilizador nem de saída do modelo
 * (`docs/tecnica/08` §3.1, camada «Estado»).
 */
export interface Ctx {
  readonly tenantId: string;
}

/**
 * Chave de um objecto: `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`.
 *
 * É texto, mas não é texto qualquer: só `novaChave` (`chave.ts`) cunha uma, e a
 * porta volta a validar a forma e o tenant em cada operação.
 */
export type ObjectKey = string;

/**
 * Referência a um objecto guardado.
 *
 * É isto que um consumidor persiste (o MED em `media_assets`, KAM-020) — nunca
 * uma URL, e muito menos a URL da Meta de onde o conteúdo veio.
 *
 * `sha256` vem preenchido de `put` (calculado sobre os bytes enviados) e é
 * `null` numa referência devolvida por `list`, porque uma listagem S3 não
 * devolve metadados: quem precisa da soma guarda a que `put` lhe deu.
 */
export interface ObjectRef {
  readonly key: ObjectKey;
  /** Tamanho em bytes. */
  readonly tamanho: number;
  /** SHA-256 do conteúdo, em hexadecimal minúsculo; `null` se desconhecido. */
  readonly sha256: string | null;
}

/** Metadados que **todo** o objecto leva (critério de aceitação 8). */
export interface ObjectMeta {
  readonly contentType: string;
  /**
   * Classe de retenção do objecto. Tem de coincidir com o segmento `{classe}`
   * da chave: são a mesma afirmação escrita em dois sítios, e a porta recusa
   * quando divergem.
   */
  readonly classe: string;
  /**
   * Instante a partir do qual o objecto pode ser purgado (`retain_until`).
   *
   * Obrigatório: o critério diz «cada objecto leva», e um objecto sem prazo é
   * um objecto que a purga do KAM-071 nunca vê. **Este módulo só o regista**;
   * apagar é do KAM-071.
   */
  readonly retainUntil: Date;
}

/** O que `head` devolve: os metadados tal como o servidor os guardou. */
export interface ObjectInfo extends ObjectMeta {
  readonly key: ObjectKey;
  readonly tamanho: number;
}

/** Corpo de um objecto: os bytes de uma vez, ou um fluxo deles. */
export type Corpo = Uint8Array | AsyncIterable<Uint8Array>;

/** TTL máximo de uma URL assinada, em segundos (`docs/tecnica/08` §3.8). */
export const TTL_MAXIMO_S = 300;

/** Número máximo de chaves que `list` devolve por omissão. */
export const LIMITE_DE_LISTAGEM = 1000;

/**
 * A porta.
 *
 * O esboço do ticket tem cinco métodos; aqui são seis. `head` foi acrescentado
 * porque sem ele o critério «cada objecto leva metadados `classe` e
 * `retain_until`» só se podia provar do lado de quem os envia — e a purga do
 * KAM-071 precisa de os ler.
 */
export interface StorageProvider {
  /** Nome curto do motor, para mensagens e métricas: `fake`, `s3`. */
  readonly nome: string;

  /**
   * Guarda um objecto.
   *
   * @throws {CtxEmFaltaError | TenantInvalidoError} sem contexto utilizável.
   * @throws {ChaveInvalidaError} se `key` não tem a forma canónica.
   * @throws {ChaveForaDoTenantError} se `key` é de outro tenant.
   * @throws {MetaInvalidaError} se os metadados não servem.
   */
  put(ctx: Ctx, key: ObjectKey, body: Corpo, meta: ObjectMeta): Promise<ObjectRef>;

  /**
   * Devolve o conteúdo.
   *
   * @throws {ObjectoInexistenteError} se o objecto não existe **no tenant do
   * contexto**.
   */
  get(ctx: Ctx, ref: ObjectRef): Promise<AsyncIterable<Uint8Array>>;

  /** Devolve os metadados que o servidor guardou. */
  head(ctx: Ctx, ref: ObjectRef): Promise<ObjectInfo>;

  /**
   * Devolve uma URL de leitura que expira.
   *
   * @throws {TtlInvalidoError} se `ttlSeconds` não é um inteiro em `[1, 300]`.
   */
  signUrl(ctx: Ctx, ref: ObjectRef, o: { readonly ttlSeconds: number }): Promise<string>;

  /** Apaga. Idempotente: apagar o que não existe não é erro. */
  delete(ctx: Ctx, ref: ObjectRef): Promise<void>;

  /**
   * Lista as referências sob um prefixo **do tenant do contexto**.
   *
   * @throws {ChaveForaDoTenantError} se o prefixo não começa por
   * `t/{ctx.tenantId}/`.
   * @throws {ListagemTruncadaError} se houver mais do que `limite` chaves: uma
   * listagem cortada em silêncio é uma purga que deixa objectos para trás.
   */
  list(
    ctx: Ctx,
    prefix: string,
    o?: { readonly limite?: number },
  ): Promise<ObjectRef[]>;
}

/*
 * Nota sobre a forma destas classes: os campos são declarados e atribuídos à
 * mão, em vez de propriedades de parâmetro. `erasableSyntaxOnly` proíbe-as
 * (`docs/adr/ADR-L001-toolchain.md`).
 */

/** Pediu-se uma operação sem dizer de que tenant. */
export class CtxEmFaltaError extends Error {
  override readonly name = "CtxEmFaltaError";
  constructor() {
    super("operação de armazenamento sem `ctx.tenantId`: não há acesso sem tenant");
  }
}

/** O tenant do contexto não é um UUID canónico. A mensagem não repete o valor. */
export class TenantInvalidoError extends Error {
  override readonly name = "TenantInvalidoError";
  constructor(tipo: string, comprimento: number) {
    super(
      "`ctx.tenantId` tem de ser um UUID na forma canónica " +
        `(recebido: ${tipo} com ${comprimento} caracteres)`,
    );
  }
}

/** A chave não tem a forma `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`. */
export class ChaveInvalidaError extends Error {
  override readonly name = "ChaveInvalidaError";
  constructor(motivo: string) {
    // O motivo e nunca a chave: uma chave mal formada pode ser um valor que
    // alguém passou por engano, e não tem de aparecer num log por causa disto.
    super(`chave de objecto inválida: ${motivo}`);
  }
}

/**
 * A chave, a referência ou o prefixo é de outro tenant.
 *
 * A mensagem não diz de qual, nem se o objecto existe: quem pede o que não é
 * seu não aprende nada com a recusa.
 */
export class ChaveForaDoTenantError extends Error {
  override readonly name = "ChaveForaDoTenantError";
  constructor(operacao: string) {
    super(`${operacao}: a chave não pertence ao tenant do contexto; recusado`);
  }
}

/** Os metadados não servem (classe, tipo de conteúdo ou prazo). */
export class MetaInvalidaError extends Error {
  override readonly name = "MetaInvalidaError";
  constructor(motivo: string) {
    super(`metadados de objecto inválidos: ${motivo}`);
  }
}

/** O TTL pedido para uma URL assinada está fora de `[1, 300]` segundos. */
export class TtlInvalidoError extends Error {
  override readonly name = "TtlInvalidoError";
  constructor() {
    super(
      `o TTL de uma URL assinada é um inteiro entre 1 e ${TTL_MAXIMO_S} segundos ` +
        "(docs/tecnica/08 §3.8)",
    );
  }
}

/** O objecto não existe no tenant do contexto. */
export class ObjectoInexistenteError extends Error {
  override readonly name = "ObjectoInexistenteError";
  constructor() {
    super("objecto inexistente no tenant do contexto");
  }
}

/** Há mais chaves sob o prefixo do que o limite pedido. */
export class ListagemTruncadaError extends Error {
  override readonly name = "ListagemTruncadaError";
  readonly limite: number;
  constructor(limite: number) {
    super(
      `há mais de ${limite} objectos sob o prefixo; estreite o prefixo ou ` +
        "aumente `limite` — a listagem não se corta em silêncio",
    );
    this.limite = limite;
  }
}

/**
 * O motor devolveu algo que não devia: uma chave fora do prefixo pedido, ou
 * metadados que não se conseguem ler. **Falha fechada**: é o sinal de um
 * defeito no servidor ou no motor, e devolver «o que se aproveita» seria
 * esconder precisamente o caso que a segunda camada existe para apanhar.
 */
export class RespostaDoMotorInvalidaError extends Error {
  override readonly name = "RespostaDoMotorInvalidaError";
  constructor(motivo: string) {
    super(`resposta do armazenamento recusada: ${motivo}`);
  }
}

/**
 * O servidor de objectos não respondeu, ou respondeu com um erro.
 *
 * Leva o estado HTTP e o código de erro S3 quando existem — **nunca** o corpo
 * da resposta nem o endereço pedido, que numa URL assinada é uma credencial.
 */
export class ArmazenamentoIndisponivelError extends Error {
  override readonly name = "ArmazenamentoIndisponivelError";
  readonly operacao: string;
  readonly estado: number | null;
  readonly codigo: string | null;
  constructor(operacao: string, estado: number | null, codigo: string | null) {
    super(
      `armazenamento indisponível em ${operacao}` +
        (estado === null ? " (sem resposta)" : ` (HTTP ${estado}` + (codigo ? `, ${codigo})` : ")")),
    );
    this.operacao = operacao;
    this.estado = estado;
    this.codigo = codigo;
  }
}

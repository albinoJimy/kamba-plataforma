/**
 * TEN — entitlements e consumo de limites (KAM-009, criterios 2 a 5 e 7).
 *
 * Duas perguntas, e nenhuma das duas se responde aqui dentro:
 *
 *     checkEntitlement(bd, tenant, modulo)        este tenant pode usar o modulo?
 *     consumeLimit(bd, tenant, chave, n, chaveId) cabe mais n nesta chave?
 *
 * A primeira responde-se com o `SQL_ENTITLEMENT`, cuja coluna `permitido` ja e
 * a conjuncao do criterio 2 escrita em SQL. A segunda responde-se com
 * `platform.ten_consumir`, da revisao `0007`. **Nenhuma linha deste ficheiro
 * soma, subtrai ou compara um limite**, e isso e o desenho e nao um acaso: o
 * bloco do ticket pede o lado Python «a chamar a mesma regra SQL», e duas
 * implementacoes da mesma aritmetica de limites divergem — foi o que a `0002`
 * ja escreveu sobre a RLS.
 *
 * ## Atomico e idempotente porque a funcao o e
 *
 * O criterio 3 pede que 1 000 chamadas paralelas de 1 unidade contra um limite
 * de 100 aceitem exactamente 100, e o criterio 4 que repetir a mesma
 * `idempotencyKey` nao consuma duas vezes. Nada disso se consegue em
 * JavaScript: consegue-se no `ON CONFLICT ... WHERE valor + n <= limite` e na
 * chave unica de `usage_ledger`, que serializam no lock da linha. O que este
 * modulo acrescenta e **nao estragar**: uma chamada, uma transaccao, sem
 * leitura previa e sem cache nenhuma no caminho do consumo.
 *
 * **O consumo nunca passa pela cache.** A cache e so dos entitlements; um
 * contador em cache era um contador errado, e um tecto decidido sobre um
 * contador errado deixa passar o que devia negar.
 *
 * ## O `tenant_id` vem do contexto
 *
 * As funcoes recebem o tenant como argumento, mas quem o fornece e sempre o
 * contexto de quem chama — o `ChannelContext` do CHR (`01` §7.2) ou o
 * `ToolContext` da ToolLayer (`02` §6.1) —, nunca um parametro de um cliente.
 * No caminho HTTP isso e imposto pela forma do `middleware.ts`, que nao tem
 * acesso ao corpo nem a query do pedido. Aqui o que ha e a defesa em
 * profundidade: o `normalizarTenant` do `tenant_guard` recusa o que nao seja um
 * UUID canonico, e a RLS de `platform.tenants` (`id = app.tenant_id`) faz a
 * consulta devolver zero linhas quando o contexto da transaccao e de outro
 * tenant — que este modulo le como negado.
 *
 * ## O que este modulo nao faz
 *
 * * **Nao abre transaccoes.** Recebe um cliente; quem da contexto de tenant e
 *   o `tenant_guard` (`comTenant`). Chamar `consumeLimit` dentro desse bloco e
 *   o que poe o consumo na mesma transaccao do efeito que o motivou.
 * * **Nao regista nada.** Nem o tenant, nem a chave, nem o erro: o DoD proibe
 *   associar `tenant_id` a conteudo em registos. So conta (`metricas.ts`).
 * * **Nao sabe precos.** Um limite e um inteiro vindo de `entitlements.limites`
 *   e nada aqui o interpreta como dinheiro.
 */

import { normalizarTenant } from "../tenant_guard/index.ts";

import { SQL_CONSUMIR, SQL_ENTITLEMENT, SQL_PERIODO } from "./consultas.ts";
import {
  METRICA_ENTITLEMENT_NEGADO,
  METRICA_LIMITE_NEGADO,
  METRICAS,
  type MetricasDoTen,
} from "./metricas.ts";

/** O minimo de um cliente SQL. E a forma do `pg.Client`, como no `eventos/`. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }>;
}

/**
 * Os codigos de erro. **Os tres estao em proposta, e de maneiras diferentes.**
 *
 * `LIMIT_EXCEEDED` e o unico escrito num documento tecnico: `docs/tecnica/02`
 * §6.5, na tabela de erros tipados da ToolLayer. **Sem estado HTTP associado** —
 * o §6.5 e sobre erros de *tool*, nao sobre uma API —, pelo que o `429` deste
 * modulo e proposta do ticket e nada mais.
 *
 * `ENTITLEMENT_DENIED` tambem esta no §6.5, e e o nome que a ToolLayer usa.
 *
 * `ENTITLEMENT_DISABLED` **nao esta em documento nenhum**: vem do criterio 2 do
 * bloco do KAM-009, que o marca «em proposta». Note-se que nao e o mesmo nome
 * que o §6.5 escreve para a mesma situacao. Os dois ficam aqui, cada um no seu
 * caminho — `ENTITLEMENT_DISABLED` no HTTP, por ser o que o criterio pede, e
 * `ENTITLEMENT_DENIED` na ToolLayer, por ser o que o documento tem —, e **a
 * decisao de os unificar devolve-se ao dono do `docs/tecnica/02` §6.5**.
 * Escolher aqui um dos dois em silencio era fechar por omissao uma divergencia
 * entre um ticket e um documento.
 */
export const CODIGO_ENTITLEMENT_HTTP = "ENTITLEMENT_DISABLED";
/** O mesmo caso, no vocabulario da ToolLayer (`docs/tecnica/02` §6.5). */
export const CODIGO_ENTITLEMENT_TOOL = "ENTITLEMENT_DENIED";
/** `docs/tecnica/02` §6.5. O unico dos tres que um documento tecnico escreve. */
export const CODIGO_LIMITE = "LIMIT_EXCEEDED";

/** Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum. */
export const HTTP_ENTITLEMENT = 403;
/** Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum. */
export const HTTP_LIMITE = 429;

/** A gramatica de um modulo e de uma chave de limite (`CHECK` da `0001`/`0007`). */
export const NOME_CANONICO = /^[a-z][a-z0-9_]{1,62}$/;

/** Porque e que o entitlement negou. Nunca e `null` quando negou. */
export type MotivoDaRecusa =
  /** Zero linhas: tenant inexistente, apagado, ou contexto de RLS de outro. */
  | "sem_tenant"
  /** Ha tenant, nao ha linha de entitlement para o modulo (KAM-091 por correr). */
  | "sem_entitlement"
  /** Ha linha, `ativo = false`. */
  | "entitlement_inactivo"
  /** `onboarding`, `suspenso` ou `encerrado`. A lista vive no SQL. */
  | "estado_do_tenant";

/** O que a base respondeu sobre um entitlement. */
export interface Entitlement {
  readonly modulo: string;
  readonly permitido: boolean;
  /** `null` quando nao ha linha de tenant. */
  readonly estadoTenant: string | null;
  readonly ativo: boolean;
  /** `null` exactamente quando `permitido`. */
  readonly motivo: MotivoDaRecusa | null;
}

/** Um nome que nao casa a gramatica de `modulo` ou de `chave_limite`. */
export class NomeInvalidoError extends Error {
  constructor(campo: string, valor: unknown) {
    super(
      `${campo} tem de casar ^[a-z][a-z0-9_]{1,62}$ (recebido: ` +
        `${typeof valor} com ${typeof valor === "string" ? valor.length : 0} caracteres)`,
    );
    this.name = "NomeInvalidoError";
  }
}

/** A quantidade a consumir nao e um inteiro positivo. */
export class QuantidadeInvalidaError extends Error {
  constructor(valor: unknown) {
    super(
      `a quantidade tem de ser um inteiro positivo, veio ${JSON.stringify(valor)}. ` +
        "A mesma recusa existe em `platform.ten_consumir`; esta poupa a ida a base.",
    );
    this.name = "QuantidadeInvalidaError";
  }
}

/** A chave de idempotencia esta vazia ou nao e texto. */
export class ChaveDeIdempotenciaInvalidaError extends Error {
  constructor() {
    super(
      "a chave de idempotencia tem de ser texto nao vazio: e ela que torna a " +
        "repeticao segura (`usage_ledger`, criterio 4). A mensagem nao repete o valor.",
    );
    this.name = "ChaveDeIdempotenciaInvalidaError";
  }
}

/** A base devolveu uma coluna com uma forma que nao se consegue ler. */
export class RespostaIlegivelError extends Error {
  constructor(coluna: string, valor: unknown) {
    super(
      `a coluna ${coluna} veio como ${typeof valor} e nao se consegue ler como ` +
        "inteiro. Um limite mal lido e um tecto errado: recusa-se em vez de adivinhar.",
    );
    this.name = "RespostaIlegivelError";
  }
}

export function exigirNome(campo: string, valor: unknown): string {
  if (typeof valor !== "string" || !NOME_CANONICO.test(valor)) {
    throw new NomeInvalidoError(campo, valor);
  }
  return valor;
}

/**
 * Um `bigint` do PostgreSQL como numero de JavaScript.
 *
 * O `pg` devolve `bigint` como **texto**, para nao perder precisao acima de
 * 2^53; o `pg8000` do lado Python devolve `int`. Os dois passam por aqui com a
 * mesma regra, e o que nao seja inteiro exacto levanta em vez de ser
 * arredondado em silencio — um tecto de dinheiro arredondado e dinheiro errado
 * (`specs/01` §6, principio 4).
 */
export function inteiro(coluna: string, valor: unknown): number {
  if (typeof valor === "number" && Number.isSafeInteger(valor)) return valor;
  if (typeof valor === "bigint") {
    if (valor > BigInt(Number.MAX_SAFE_INTEGER) || valor < BigInt(Number.MIN_SAFE_INTEGER)) {
      throw new RespostaIlegivelError(coluna, valor);
    }
    return Number(valor);
  }
  if (typeof valor === "string" && /^-?\d+$/.test(valor)) {
    const lido = Number(valor);
    if (!Number.isSafeInteger(lido)) throw new RespostaIlegivelError(coluna, valor);
    return lido;
  }
  throw new RespostaIlegivelError(coluna, valor);
}

/** Um booleano do PostgreSQL. Tudo o que nao seja `true` conta como falso. */
function booleano(valor: unknown): boolean {
  return valor === true || valor === "t" || valor === "true";
}

/**
 * O entitlement de um modulo para um tenant. **Falha fechada** (criterio 2).
 *
 * Nega quando nao ha linha, quando `ativo = false` e quando o tenant esta
 * `onboarding`, `suspenso` ou `encerrado` — e a lista dos tres estados vive no
 * `SQL_ENTITLEMENT`, nao aqui, para que o Python nao possa ter outra.
 *
 * A assinatura do criterio 6 e `checkEntitlement(tenant, modulo)`; esta tem o
 * cliente a frente, como todos os modulos deste pacote que falam com a base
 * (`eventos/consumo.ts`, `identity/contactos.ts`). Quem liga e quem chama.
 *
 * Conta `ten_entitlement_denied_total{modulo}` em **cada** recusa, incluindo as
 * que vem da cache: o que o painel mostra e quantos acessos foram negados, e
 * nao quantas vezes a base foi consultada.
 */
export async function checkEntitlement(
  bd: ClienteSql,
  tenant: unknown,
  modulo: unknown,
  opcoes: { readonly cache?: CacheDeEntitlements; readonly metricas?: MetricasDoTen } = {},
): Promise<Entitlement> {
  const canonico = normalizarTenant(tenant);
  const nome = exigirNome("modulo", modulo);
  const metricas = opcoes.metricas ?? METRICAS;

  const emCache = opcoes.cache?.ler(canonico, nome);
  if (emCache !== undefined) {
    if (!emCache.permitido) metricas.contar(METRICA_ENTITLEMENT_NEGADO, nome);
    return emCache;
  }

  const { rows } = await bd.query(SQL_ENTITLEMENT, [canonico, nome]);
  const linha = rows[0];
  const decisao: Entitlement =
    linha === undefined
      ? {
          modulo: nome,
          permitido: false,
          estadoTenant: null,
          ativo: false,
          motivo: "sem_tenant",
        }
      : montar(nome, linha);

  opcoes.cache?.guardar(canonico, nome, decisao);
  if (!decisao.permitido) metricas.contar(METRICA_ENTITLEMENT_NEGADO, nome);
  return decisao;
}

/**
 * A linha da base como decisao.
 *
 * O `permitido` **vem da coluna**, e nao se recalcula: recalcular era a segunda
 * implementacao da regra. O `motivo` deriva-se, e repare-se que a unica coisa
 * que a derivacao sabe sobre estados e que, se o entitlement esta activo e
 * mesmo assim negou, so pode ter sido o estado do tenant. A lista dos tres
 * estados continua a existir num sitio so.
 */
function montar(modulo: string, linha: Record<string, unknown>): Entitlement {
  const permitido = booleano(linha.permitido);
  const ativo = booleano(linha.ativo);
  const temLinha = booleano(linha.tem_linha);
  const estadoTenant = typeof linha.estado_tenant === "string" ? linha.estado_tenant : null;
  let motivo: MotivoDaRecusa | null = null;
  if (!permitido) {
    motivo = !temLinha
      ? "sem_entitlement"
      : !ativo
        ? "entitlement_inactivo"
        : "estado_do_tenant";
  }
  return { modulo, permitido, estadoTenant, ativo, motivo };
}

/** O desfecho de um consumo, tal como `platform.ten_consumir` o devolve. */
export interface Consumo {
  /** Aceite (ou repeticao de um consumo ja aceite). */
  readonly aceite: boolean;
  /** O uso no periodo depois desta chamada. */
  readonly valor: number;
  /** Esta chamada e a repeticao de uma anterior com a mesma chave. */
  readonly repetido: boolean;
  /**
   * O tecto efectivo. **`null` quando nenhum entitlement activo declara a
   * chave** — e `null` nega, pela `0007`: «sem tecto» nao quer dizer «sem
   * limite».
   */
  readonly limite: number | null;
  /** `null` quando aceite. Senao, qual das duas recusas foi. */
  readonly motivo: "sem_entitlement" | "limite_excedido" | null;
}

/**
 * Consome `quantidade` da chave, atomica e idempotentemente.
 *
 * Uma unica chamada a `platform.ten_consumir`. Sem leitura previa: entre um
 * `SELECT` e um `INSERT` cabe a chamada repetida inteira, e e por isso que a
 * `0007` escreve a chave de idempotencia **antes** de contar.
 *
 * O `limite` opcional e o tecto de quem chama, e so **desce**: a `0007` faz
 * `least` com o do plano. Serve um tecto de confianca (`EPIC-09`) mais
 * apertado, nunca um mais largo — passar um limite alto nao abre nada.
 *
 * O `agora` opcional existe para o criterio 5: com relogio fixo em
 * `2026-11-30T23:59:59+01:00` o consumo conta para Novembro e em
 * `2026-12-01T00:00:00+01:00` para Dezembro. Quem decide isso e
 * `platform.ten_periodo`, em `Africa/Luanda`; aqui so se passa o instante.
 *
 * Conta `ten_limit_denied_total{key}` quando o tecto recusa. Uma recusa por
 * **falta** de entitlement conta em `ten_entitlement_denied_total{modulo}`
 * apenas se quem chama passar o modulo (`opcoes.modulo`): a funcao SQL nao o
 * sabe, porque o tecto e o minimo entre os modulos que declaram a chave.
 */
export async function consumeLimit(
  bd: ClienteSql,
  tenant: unknown,
  chave: unknown,
  quantidade: unknown,
  idempotencyKey: unknown,
  opcoes: {
    readonly limite?: number | null;
    readonly agora?: Date | null;
    readonly modulo?: string;
    readonly metricas?: MetricasDoTen;
  } = {},
): Promise<Consumo> {
  const canonico = normalizarTenant(tenant);
  const nome = exigirNome("chave", chave);
  if (typeof quantidade !== "number" || !Number.isSafeInteger(quantidade) || quantidade <= 0) {
    throw new QuantidadeInvalidaError(quantidade);
  }
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim() === "") {
    throw new ChaveDeIdempotenciaInvalidaError();
  }
  const tecto = opcoes.limite ?? null;
  if (tecto !== null && (!Number.isSafeInteger(tecto) || tecto < 0)) {
    throw new QuantidadeInvalidaError(tecto);
  }
  const metricas = opcoes.metricas ?? METRICAS;

  const { rows } = await bd.query(SQL_CONSUMIR, [
    canonico,
    nome,
    quantidade,
    idempotencyKey,
    tecto,
    opcoes.agora ?? null,
  ]);
  const linha = rows[0];
  if (linha === undefined) {
    // `ten_consumir` devolve sempre uma linha. Zero linhas significa que a
    // chamada nao chegou a funcao — e tratar isso como «aceite» seria consumir
    // sem contar.
    throw new RespostaIlegivelError("ten_consumir", rows);
  }
  const aceite = booleano(linha.aceite);
  const limite = linha.limite === null || linha.limite === undefined
    ? null
    : inteiro("limite", linha.limite);
  const consumo: Consumo = {
    aceite,
    valor: inteiro("valor", linha.valor),
    repetido: booleano(linha.repetido),
    limite,
    motivo: aceite ? null : limite === null ? "sem_entitlement" : "limite_excedido",
  };
  if (consumo.motivo === "limite_excedido") {
    metricas.contar(METRICA_LIMITE_NEGADO, nome);
  } else if (consumo.motivo === "sem_entitlement" && opcoes.modulo !== undefined) {
    metricas.contar(METRICA_ENTITLEMENT_NEGADO, exigirNome("modulo", opcoes.modulo));
  }
  return consumo;
}

/**
 * O periodo de um instante, perguntado a base.
 *
 * Nao decide nada — a `ten_consumir` chama a mesma funcao la dentro. Existe
 * para quem precisa de **mostrar** o periodo e para os testes de fronteira de
 * mes poderem perguntar a base o que ela conta, em vez de o reescreverem.
 */
export async function periodo(bd: ClienteSql, agora?: Date | null): Promise<string> {
  const { rows } = await bd.query(SQL_PERIODO, [agora ?? null]);
  const valor = rows[0]?.periodo;
  if (valor instanceof Date) return valor.toISOString().slice(0, 10);
  if (typeof valor === "string") return valor;
  throw new RespostaIlegivelError("periodo", valor);
}

/** TTL da cache, em milissegundos. **Proposta**: o criterio 6 pede «<= 60 s». */
export const TTL_POR_OMISSAO_MS = 60_000;

/** Quantas entradas a cache guarda antes de deitar fora as mais velhas. */
export const MAXIMO_DE_ENTRADAS = 10_000;

interface Entrada {
  readonly decisao: Entitlement;
  readonly expiraEm: number;
}

/**
 * O relogio da cache, em milissegundos, **monotonico**.
 *
 * `performance.now()` e nao `Date.now()`: o relogio de parede anda para tras
 * quando o NTP o corrige, e uma entrada guardada com `expiraEm` calculado
 * antes de um salto de dez minutos ficava dez minutos a mais em cache — o
 * criterio 6 fala de 60 s e um salto de relogio nao e desculpa. O espelho em
 * Python usa `time.monotonic()` pela mesma razao. As duas epocas sao
 * diferentes e nao precisam de coincidir: cada processo so compara este
 * relogio consigo proprio.
 */
export function agoraMs(): number {
  return performance.now();
}

/**
 * Cache de entitlements com TTL. **Nunca devolve dados de outro tenant.**
 *
 * ## A visibilidade e so pelo TTL, e isso tem de ficar escrito
 *
 * O criterio 6 pede que uma alteracao de entitlement seja visivel em <= 60 s.
 * A forma habitual de o conseguir e invalidar por evento — e o que o `01` §7.2
 * faz com a cache do CHR, «invalidado por evento `channel.updated`». **Aqui nao
 * ha evento equivalente**: o catalogo de eventos nao tem nenhum `entitlement.*`
 * (verificado contra o catalogo; os tipos existentes sao de canal, encomenda,
 * pagamento, marcacao e stock). Logo a unica coisa que torna uma alteracao
 * visivel e a expiracao, e o limite superior do atraso e **exactamente** o TTL.
 *
 * Duas consequencias que quem usa isto tem de saber: um entitlement **retirado**
 * continua a permitir ate 60 s, e nao ha forma de o apressar a nao ser chamar
 * `invalidar`. Criar o evento `entitlement.updated` e trabalho do catalogo
 * (KAM-007) e do provisionamento (KAM-091), e fica **proposto aqui, nao feito**.
 *
 * ## Porque e que a chave nao pode misturar tenants
 *
 * A chave e `<uuid canonico>\0<modulo>`. O tenant passa pelo
 * `normalizarTenant`, que so aceita a forma canonica — duas escritas do mesmo
 * tenant seriam duas chaves, e uma escrita estranha podia ser construida para
 * colidir com outra. O separador e `\0`, que nem um UUID nem um modulo
 * (`^[a-z][a-z0-9_]*$`) podem conter: sem ele, um tenant que acabasse em `:` e
 * um modulo que comecasse por um digito dariam a mesma chave que outro par.
 *
 * O `invalidar(tenant)` apaga **so** as entradas desse tenant, pelo prefixo.
 *
 * ## Guarda-se tambem o que **negou**, e isso tem uma consequencia
 *
 * Uma recusa fica em cache como uma permissao fica. O caso a conhecer e o
 * `sem_tenant`: a consulta devolve zero linhas tanto para um tenant que nao
 * existe como para um pedido feito com o **contexto de RLS de outro tenant** —
 * e, nesse segundo caso, a recusa guardada e consequencia de um defeito de
 * quem chama e sobrevive-lhe ate 60 s. Guarda-se na mesma, por duas razoes: o
 * sentido do erro e o seguro (nega-se de mais, nunca de menos), e nao guardar
 * deixava um tenant inexistente a bater na base a cada pedido. Quem corrige o
 * contexto chama `invalidar`.
 */
export class CacheDeEntitlements {
  readonly #entradas = new Map<string, Entrada>();
  readonly ttlMs: number;
  readonly maximo: number;

  constructor(ttlMs: number = TTL_POR_OMISSAO_MS, maximo: number = MAXIMO_DE_ENTRADAS) {
    if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
      throw new RangeError(`o TTL tem de ser positivo: ${ttlMs}`);
    }
    if (!Number.isInteger(maximo) || maximo <= 0) {
      throw new RangeError(`o maximo tem de ser um inteiro positivo: ${maximo}`);
    }
    this.ttlMs = ttlMs;
    this.maximo = maximo;
  }

  #chave(tenant: unknown, modulo: unknown): string {
    return `${normalizarTenant(tenant)}\u0000${exigirNome("modulo", modulo)}`;
  }

  /** A decisao guardada, ou `undefined` se nao ha ou ja expirou. */
  ler(tenant: unknown, modulo: unknown, agora: number = agoraMs()): Entitlement | undefined {
    const chave = this.#chave(tenant, modulo);
    const entrada = this.#entradas.get(chave);
    if (entrada === undefined) return undefined;
    if (entrada.expiraEm <= agora) {
      this.#entradas.delete(chave);
      return undefined;
    }
    return entrada.decisao;
  }

  guardar(
    tenant: unknown,
    modulo: unknown,
    decisao: Entitlement,
    agora: number = agoraMs(),
  ): void {
    const chave = this.#chave(tenant, modulo);
    // Primeiro as expiradas: numa cache de entitlements a maioria das entradas
    // velhas ja nao vale nada, e deitar fora uma viva para dar lugar a uma nova
    // enquanto ha mortas la dentro era pagar duas idas a base por uma.
    if (!this.#entradas.has(chave) && this.#entradas.size >= this.maximo) {
      for (const [existente, entrada] of this.#entradas) {
        if (entrada.expiraEm <= agora) this.#entradas.delete(existente);
      }
    }
    // Ainda cheia: sai a mais antiga a entrar, que e a primeira do `Map`.
    while (!this.#entradas.has(chave) && this.#entradas.size >= this.maximo) {
      const primeira = this.#entradas.keys().next();
      if (primeira.done === true) break;
      this.#entradas.delete(primeira.value);
    }
    this.#entradas.set(chave, { decisao, expiraEm: agora + this.ttlMs });
  }

  /** Esquece tudo o que e deste tenant, e so dele. */
  invalidar(tenant: unknown): void {
    const prefixo = `${normalizarTenant(tenant)}\u0000`;
    for (const chave of [...this.#entradas.keys()]) {
      if (chave.startsWith(prefixo)) this.#entradas.delete(chave);
    }
  }

  repor(): void {
    this.#entradas.clear();
  }

  get tamanho(): number {
    return this.#entradas.size;
  }
}

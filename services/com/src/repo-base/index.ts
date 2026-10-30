/**
 * O repositório base — a injecção de `tenant_id`/`merchant_id` (KAM-042).
 *
 * **A primeira barreira de isolamento do COM vive aqui**, e a RLS do esquema
 * `platform` é a segunda (`docs/tecnica/03` §5.5). A ordem importa: a RLS
 * protege de um `WHERE` esquecido, **não** de código que escolha o tenant
 * errado — é textualmente o RR-01 —, e no Registo da opção B não há RLS
 * nenhuma, porque o Medusa não é multi-tenant nativo e os seus *links*
 * «store only the IDs of the linked records and do not hold a foreign key
 * constraint» (§3.3, CONFIRMADO no KAM-041). Logo, no lado do Registo, **esta é
 * a única barreira que existe**.
 *
 * ## O desenho, e a razão de ter mudado
 *
 * A primeira versão tinha **uma** regra — «o SQL tem de conter
 * `merchant_id = $1`» — e a revisão adversarial partiu-a por execução em quatro
 * sítios. Vale a pena guardar os quatro, porque cada um é uma lição sobre o que
 * uma verificação de texto pode afirmar:
 *
 * ```text
 * UPDATE product SET merchant_id = $1 WHERE sku = $2    EXECUTOU
 * ```
 *
 * O predicado estava no `SET`. A consulta passou por filtrada e **reescreveu as
 * linhas de todos os merchants** com aquele SKU para o tenant que chamou — e
 * `UPDATE product SET merchant_id = $1`, sem `WHERE`, também executou. Era
 * escrita cruzada, no lado onde não há RLS atrás.
 *
 * ```text
 * INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2)   RECUSOU
 * INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2)
 *   -- tenant_id = $1                                                 EXECUTOU
 * ```
 *
 * O `INSERT` legítimo era recusado — e a saída de menor resistência era
 * acrescentar o predicado **num comentário**. Uma barreira que recusa o uso
 * correcto e aceita o contorno não protege: ensina o contorno.
 *
 * ```text
 * SELECT * FROM product WHERE merchant_id = $1
 *   UNION ALL SELECT * FROM product                     EXECUTOU
 * SELECT * FROM product WHERE nome = 'merchant_id = $1' EXECUTOU
 * ```
 *
 * A segunda perna de um `UNION` saía sem filtro, com a primeira certa — que é o
 * pior caso, porque o resultado parece plausível. E o predicado dentro de um
 * literal contava.
 *
 * ## O que a versão de hoje afirma, e o que não afirma
 *
 * Quatro regras, e nenhuma é de estilo:
 *
 * ```text
 * 1. literais e comentarios apagam-se antes de procurar o predicado
 * 2. o predicado tem de estar DEPOIS do primeiro WHERE
 * 3. a coluna do filtro nunca aparece num SET
 * 4. UNION, INTERSECT e EXCEPT sao recusados
 * 5. um INSERT nao se verifica: constroi-se (`inserir`), e o filtro e escrito
 *    por esta casa e nao procurado no texto de quem chama
 * ```
 *
 * A regra 4 é a mais grosseira e é a mais honesta: uma operação de conjunto
 * precisa do filtro em **cada** perna, e nenhuma verificação por texto o
 * consegue afirmar. Quem precisar de uma faz duas chamadas e junta em
 * JavaScript — custa uma consulta e compra a propriedade.
 *
 * **O que isto continua a não fazer, e tem de ficar dito:** não é um parser de
 * SQL. Um `OR true` depois do predicado passa, e uma subconsulta ou um `JOIN`
 * cujo filtro só está do lado de fora passam. **Não é a defesa contra código
 * hostil**; é a defesa contra o esquecimento, que é o modo de falha real de
 * trinta repositórios escritos por pessoas e agentes diferentes. Contra o `OR`
 * está o ISO-10; contra a escolha errada de tenant está a revisão do código que
 * escolhe.
 */

import type { ClienteSql } from "../port/contrato.ts";
import { eUuid } from "../port/contrato.ts";

/** A métrica de recusas. Uma barreira que ninguém vê disparar não se opera. */
export const METRICA_FILTRO_EM_FALTA = "com_repo_filtro_em_falta_total";

/** O nome do contador de consultas que passaram, por tipo de filtro. */
export const METRICA_CONSULTAS = "com_repo_consultas_total";

/*
 * **Os dois contadores não são servidos a ninguém, e isso é uma lacuna
 * nomeada.** O padrão da casa é um módulo com `exposicao()` em formato
 * Prometheus (`packages/core-ts/src/ten/metricas.ts`: «quem serve as métricas
 * de um processo serve-as todas do mesmo modo»), e o COM não serve métricas —
 * o `services/com/src/app.ts` tem o `/healthz` e nada mais. Hoje o que lê estes
 * contadores são os testes, e é isso que os torna úteis: a recusa é uma
 * asserção e não uma leitura do código. A exposição é do ticket que der ao COM
 * uma superfície de métricas; os dois nomes entram no dicionário §3.39 como
 * *proposta* para que nasça com eles e não com outros.
 *
 * shortcut: os contadores vivem em memória e nenhum endpoint os lê; revê-se no
 * ticket que der ao COM uma superfície de métricas (hoje sem credor atribuído,
 * e por isso a lacuna está escrita no dicionário §3.39 e na verificação do
 * bloco KAM-042 em vez de ficar só aqui).
 */

/**
 * Os dois filtros, e porque são dois e não um.
 *
 * `tenant`   o esquema `platform`, onde a coluna é `tenant_id` e há RLS atrás.
 * `merchant` o Registo da opção B, onde a coluna é `merchant_id` e **não há
 *            nada atrás**. É o `platform.tenants.medusa_merchant_id` do tenant,
 *            resolvido uma vez por operação — e nunca um valor do chamador.
 */
export const FILTROS = ["tenant", "merchant"] as const;
export type Filtro = (typeof FILTROS)[number];

/** A coluna que cada filtro exige no predicado. */
export const COLUNA_DO_FILTRO: Readonly<Record<Filtro, string>> = {
  tenant: "tenant_id",
  merchant: "merchant_id",
};

/** Identificadores SQL que o `inserir` aceita. Sem aspas, sem esquisitices. */
const IDENTIFICADOR = /^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$/;

/** Operações de conjunto, recusadas pela regra 4. */
const CONJUNTO = /(?:^|[^a-z0-9_])(union|intersect|except)(?![a-z0-9_])/i;

function branco(m: RegExpMatchArray | { 0: string }): string {
  return m[0].replace(/[^\n]/g, " ");
}

/**
 * O SQL com literais e comentários apagados, e as linhas na mesma altura.
 *
 * Substitui em vez de remover para que as posições não mudem: a regra 2 compara
 * a posição do predicado com a do `WHERE`, e com o texto encurtado a comparação
 * passava a ser sobre outro SQL.
 */
function limpar(sql: string): string {
  let fora = sql.replace(/\/\*[\s\S]*?\*\//g, (t) => branco({ 0: t }));
  fora = fora.replace(/--[^\n]*/g, (t) => branco({ 0: t }));
  // Literais de cadeia (`'...'`, com `''` a escapar) e identificadores com
  // aspas duplas ficam de fora: o predicado dentro de um literal contava, e
  // está medido que contava.
  fora = fora.replace(/'(?:[^']|'')*'/g, (t) => branco({ 0: t }));
  return fora.replace(/\$[a-z_]*\$[\s\S]*?\$[a-z_]*\$/gi, (t) => branco({ 0: t }));
}

/** O predicado `<coluna> = $1`, com `$1` e não `$11`. */
function predicadoDe(filtro: Filtro): RegExp {
  const coluna = COLUNA_DO_FILTRO[filtro];
  return new RegExp(`(?:^|[^a-z0-9_"])"?${coluna}"?\\s*=\\s*\\$1(?![0-9])`, "i");
}

/** Onde está o `WHERE`, ou -1. Partilhado pelas regras 2 e 3. */
function posicaoDoWhere(limpo: string): number {
  return limpo.search(/(?:^|[^a-z0-9_])where(?![a-z0-9_])/i);
}

/**
 * A região da cláusula `SET`: do `SET` até ao `WHERE`, ou até ao fim.
 *
 * **Tem de acabar no `WHERE`**, e a primeira versão não acabava: era um
 * `set` seguido de `[\s\S]*?` não-guloso até à coluna, que atravessava o
 * `WHERE` e casava com o predicado legítimo que está lá. O
 * `UPDATE product SET nome = $2 WHERE merchant_id = $1` era recusado — e foi o
 * próprio teste do caminho legítimo que o apanhou, no primeiro minuto depois de
 * a regra 3 nascer. É a segunda vez neste ficheiro que um caso que afirma o
 * **uso correcto** encontra o defeito; os canários da recusa passavam todos.
 */
function regiaoDoSet(limpo: string): string | null {
  const set = limpo.search(/(?:^|[^a-z0-9_])set(?![a-z0-9_])/i);
  if (set < 0) return null;
  const where = posicaoDoWhere(limpo);
  return where > set ? limpo.slice(set, where) : limpo.slice(set);
}

/** A coluna do filtro atribuída num `SET`. Nunca é legítimo (regra 3). */
function atribuicaoDe(filtro: Filtro, limpo: string): boolean {
  const regiao = regiaoDoSet(limpo);
  if (regiao === null) return false;
  const coluna = COLUNA_DO_FILTRO[filtro];
  return new RegExp(`(?:^|[^a-z0-9_"])"?${coluna}"?\\s*=`, "i").test(regiao);
}

/** Uma consulta chegou ao repo-base sem o filtro que a limita. */
export class FiltroEmFaltaError extends Error {
  override readonly name = "FiltroEmFaltaError";
  constructor(filtro: Filtro, razao: string, sql: string) {
    super(
      `o repo-base recusou a consulta: ${razao}. No Registo da opcao B nao ha ` +
        "RLS atras desta barreira, pelo que uma consulta sem filtro nao " +
        "devolve zero linhas — devolve as de todos os tenants " +
        `(KAM-042, criterio 4). Exige-se "${COLUNA_DO_FILTRO[filtro]} = $1" ` +
        `depois do WHERE. SQL recusado: ${resumir(sql)}`,
    );
  }
}

/** O `merchant_id` do tenant não está provisionado. Falha fechada. */
export class MerchantEmFaltaError extends Error {
  override readonly name = "MerchantEmFaltaError";
  constructor(tenantId: string) {
    super(
      `o tenant ${tenantId} nao tem medusa_merchant_id em platform.tenants: ` +
        "o provisionamento do criterio 5 nao correu para ele, e uma consulta " +
        "ao Registo sem merchant_id devolvia as linhas de todos os tenants " +
        "(KAM-042, criterio 5)",
    );
  }
}

/**
 * O tenant não existe em `platform.tenants`, ou está `deleted_at`.
 *
 * **Distinto do `MerchantEmFaltaError`**, e a distinção é do critério 1, que
 * nomeia «tenant inexistente» à parte: um tenant que não existe é um `ctx`
 * montado contra um id que ninguém criou — um defeito de quem chama —, e um
 * tenant sem `merchant_id` é um provisionamento que falta. Com um erro só, quem
 * opera o *script* da Fase 0 não sabia qual dos dois tinha.
 */
export class TenantDesconhecidoError extends Error {
  override readonly name = "TenantDesconhecidoError";
  constructor(tenantId: string) {
    super(
      `nao existe platform.tenants com id = ${tenantId} e deleted_at IS NULL ` +
        "(KAM-042, criterio 1: tenant inexistente falha fechada)",
    );
  }
}

/** Um `tenant_id` que não é um UUID canónico nunca entra num predicado. */
export class TenantInvalidoError extends Error {
  override readonly name = "TenantInvalidoError";
  constructor(valor: unknown) {
    super(
      `tenant_id invalido no repo-base: ${JSON.stringify(String(valor))}. ` +
        "O ctx vem do estado do agente ou da sessao autenticada e nunca do " +
        "texto do cliente (KAM-042, criterio 1)",
    );
  }
}

/** Um nome de tabela ou de coluna que o `inserir` não aceita construir. */
export class IdentificadorInvalidoError extends Error {
  override readonly name = "IdentificadorInvalidoError";
  constructor(valor: string) {
    super(
      `identificador invalido no inserir: ${JSON.stringify(valor)}. O repo-base ` +
        "constroi o SQL, pelo que um nome de tabela ou de coluna que venha de " +
        "fora e interpolacao — e nao ha forma de o parametrizar (KAM-042)",
    );
  }
}

/** O SQL recusado, cortado: a mensagem vai para o *log*, que tem allowlist. */
function resumir(sql: string): string {
  const limpo = sql.replace(/\s+/g, " ").trim();
  return limpo.length > 120 ? `${limpo.slice(0, 120)}…` : limpo;
}

export class Contadores {
  readonly filtroEmFalta = new Map<Filtro, number>();
  readonly consultas = new Map<Filtro, number>();

  contar(mapa: Map<Filtro, number>, filtro: Filtro): void {
    mapa.set(filtro, (mapa.get(filtro) ?? 0) + 1);
  }
}

export const CONTADORES = new Contadores();

/** O que vai num `INSERT` construído pelo repo-base. */
export interface Insercao {
  readonly tabela: string;
  /** As colunas do chamador. A do filtro **não** entra — é escrita aqui. */
  readonly valores: Readonly<Record<string, unknown>>;
  /**
   * O que vem depois do `VALUES`, se for preciso: `ON CONFLICT … DO NOTHING
   * RETURNING *`, um `RETURNING`. Não leva predicado nenhum — a coluna do
   * filtro já está nos valores — e é por isso que não se verifica.
   */
  readonly sufixo?: string;
}

/**
 * O que o repo-base devolve a quem o usa.
 *
 * Quatro operações, e a separação é a barreira:
 *
 *   `noTenant`/`noMerchant`      `SELECT`, `UPDATE` e `DELETE`, com o predicado
 *                                verificado **depois do `WHERE`**
 *   `inserirNoTenant`/`…Merchant` o `INSERT`, cujo SQL é **construído** aqui com
 *                                a coluna do filtro — não há como o esquecer
 *
 * Com um método só e um parâmetro de filtro, o sítio onde se escolhe o filtro
 * era o sítio onde se podia escolher o errado, e ficava invisível na chamada.
 */
export interface RepoBase {
  /** `SELECT`/`UPDATE`/`DELETE` no `platform`, com `tenant_id = $1` no `WHERE`. */
  noTenant(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** O mesmo no Registo, com `merchant_id = $1` no `WHERE`. */
  noMerchant(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** `INSERT` no `platform`. O `tenant_id` é escrito pelo repo-base. */
  inserirNoTenant(
    insercao: Insercao,
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** `INSERT` no Registo. O `merchant_id` é escrito pelo repo-base. */
  inserirNoMerchant(
    insercao: Insercao,
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** O `tenant_id` que este repo-base injecta. Para o *log* e as métricas. */
  readonly tenantId: string;
}

/** A consulta que resolve o `merchant_id` de um tenant. Lida pelo gate 8. */
export const SQL_MERCHANT_DO_TENANT =
  "SELECT medusa_merchant_id, medusa_sales_channel_id " +
  "FROM platform.tenants WHERE id = $1 AND deleted_at IS NULL";

/**
 * O par de identificadores do Registo, para um tenant.
 *
 * Lê-se **de `platform.tenants`**, uma vez por operação, e nunca de um
 * argumento. A razão é o RR-01 do `seguranca/riscos_residuais.md`, citado no
 * §5.4: «a RLS protege de um `WHERE` esquecido, não de código que escolha o
 * tenant errado». Com o `merchant_id` a vir do chamador, a porta aceitava o do
 * tenant B com o `ctx` de A e **nada o impedia** — o *link* do Medusa não tem
 * FK (§3.3). O ISO-58 do spike é a mesma classe de defeito noutra coluna (a FK
 * do `contact_id`, que a PK de `contacts` satisfaz sem o tenant) e é de lá que
 * vem a lição, não a medição desta.
 */
export interface IdsDoRegisto {
  readonly merchantId: string;
  readonly salesChannelId: string | null;
}

export async function idsDoRegisto(
  cliente: ClienteSql,
  tenantId: string,
): Promise<IdsDoRegisto> {
  if (!eUuid(tenantId)) throw new TenantInvalidoError(tenantId);
  const { rows } = await cliente.query(SQL_MERCHANT_DO_TENANT, [tenantId]);
  if (rows.length === 0) throw new TenantDesconhecidoError(tenantId);
  const merchantId = rows[0]?.["medusa_merchant_id"];
  if (typeof merchantId !== "string" || merchantId.length === 0) {
    throw new MerchantEmFaltaError(tenantId);
  }
  const canal = rows[0]?.["medusa_sales_channel_id"];
  return {
    merchantId,
    salesChannelId: typeof canal === "string" && canal.length > 0 ? canal : null,
  };
}

/**
 * Um repo-base ligado a um cliente, a um tenant e a um `merchant_id`.
 *
 * Recebe o cliente **já dentro** de uma transacção com `app.tenant_id`
 * definido: quem o monta é o adaptador, dentro do `comTenant`. O repo-base não
 * abre transacções nem escolhe ligações, pela mesma razão que o `ComTenant` do
 * módulo `servicos` não recebe o cliente — quem decide de onde vem a ligação é
 * quem monta, e dar essa decisão a um repositório é dar-lhe a possibilidade de
 * a tomar mal.
 */
export function repoBase(
  cliente: ClienteSql,
  tenantId: string,
  merchantId: string,
): RepoBase {
  if (!eUuid(tenantId)) throw new TenantInvalidoError(tenantId);
  if (typeof merchantId !== "string" || merchantId.length === 0) {
    throw new MerchantEmFaltaError(tenantId);
  }

  function recusar(filtro: Filtro, razao: string, sql: string): never {
    CONTADORES.contar(CONTADORES.filtroEmFalta, filtro);
    throw new FiltroEmFaltaError(filtro, razao, sql);
  }

  async function consultar(
    filtro: Filtro,
    valor: string,
    sql: string,
    parametros: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]> {
    const limpo = limpar(sql);
    const coluna = COLUNA_DO_FILTRO[filtro];

    if (/^\s*insert\b/i.test(limpo)) {
      recusar(
        filtro,
        `um INSERT nao se verifica, constroi-se: usa inserirNo${
          filtro === "tenant" ? "Tenant" : "Merchant"
        }, que escreve a coluna ${coluna}`,
        sql,
      );
    }
    if (CONJUNTO.test(limpo)) {
      recusar(
        filtro,
        "operacoes de conjunto (UNION, INTERSECT, EXCEPT) sao recusadas: o " +
          "filtro tem de estar em cada perna e nenhuma verificacao por texto o " +
          "consegue afirmar — faz duas chamadas e junta em JavaScript",
        sql,
      );
    }
    if (atribuicaoDe(filtro, limpo)) {
      recusar(
        filtro,
        `a coluna ${coluna} aparece num SET. Atribui-la nunca e filtrar por ` +
          "ela: um UPDATE que a escreve move linhas de outros tenants para " +
          "este",
        sql,
      );
    }

    const ondeEstaOWhere = posicaoDoWhere(limpo);
    if (ondeEstaOWhere < 0) {
      recusar(filtro, "nao ha WHERE nenhum", sql);
    }
    const achado = predicadoDe(filtro).exec(limpo);
    if (achado === null) {
      recusar(filtro, `nao contem "${coluna} = $1"`, sql);
    }
    if (achado.index < ondeEstaOWhere) {
      recusar(
        filtro,
        `o "${coluna} = $1" esta antes do WHERE, pelo que nao e um filtro`,
        sql,
      );
    }

    CONTADORES.contar(CONTADORES.consultas, filtro);
    const { rows } = await cliente.query(sql, [valor, ...parametros]);
    return rows;
  }

  async function inserir(
    filtro: Filtro,
    valor: string,
    insercao: Insercao,
  ): Promise<readonly Readonly<Record<string, unknown>>[]> {
    const coluna = COLUNA_DO_FILTRO[filtro];
    if (!IDENTIFICADOR.test(insercao.tabela)) {
      throw new IdentificadorInvalidoError(insercao.tabela);
    }
    const colunas = Object.keys(insercao.valores);
    for (const nome of colunas) {
      if (!IDENTIFICADOR.test(nome) || nome.includes(".")) {
        throw new IdentificadorInvalidoError(nome);
      }
      if (nome === coluna) {
        // Dar o filtro nos valores era a mesma porta que o `merchant_id` do
        // chamador: recusa-se, e a coluna continua a ser escrita por esta casa.
        throw new IdentificadorInvalidoError(
          `${nome} (a coluna do filtro e escrita pelo repo-base)`,
        );
      }
    }

    const marcadores = colunas.map((_, i) => `$${i + 2}`);
    const sql =
      `INSERT INTO ${insercao.tabela} (${[coluna, ...colunas].join(", ")}) ` +
      `VALUES (${["$1", ...marcadores].join(", ")})` +
      (insercao.sufixo === undefined ? "" : ` ${insercao.sufixo}`);

    CONTADORES.contar(CONTADORES.consultas, filtro);
    const { rows } = await cliente.query(sql, [
      valor,
      ...colunas.map((nome) => insercao.valores[nome]),
    ]);
    return rows;
  }

  return {
    tenantId,
    noTenant: (sql, parametros = []) =>
      consultar("tenant", tenantId, sql, parametros),
    noMerchant: (sql, parametros = []) =>
      consultar("merchant", merchantId, sql, parametros),
    inserirNoTenant: (insercao) => inserir("tenant", tenantId, insercao),
    inserirNoMerchant: (insercao) => inserir("merchant", merchantId, insercao),
  };
}

/**
 * A auditoria de preço e de stock (KAM-043, critério 5).
 *
 * «Alterar preço ou stock grava `audit_log` (actor, *hash* antes/depois,
 * origem)». Três coisas, e esta é a única parte do ticket que as escreve.
 *
 * ## Este módulo é o primeiro chamador do `audit_append` em produção
 *
 * O KAM-012 construiu a cadeia de *hash*, a porta `platform.audit_append`, o
 * *trigger* `audit_encadear` e o papel `kamba_audit` — e registou, em
 * `specs/tickets/KAM-012.md` e em `docs/auditoria.md`, que **nada a chamava em
 * produção**; o que a exercitava eram os seus próprios testes. Passa a chamar.
 *
 * Isso tem uma consequência que vale a pena deixar escrita: as propriedades da
 * cadeia — `criado_at`, `prev_hash` e `row_hash` escritos pelo *trigger* e não
 * por quem insere, e `kamba_app` com `EXECUTE` na função e **sem** `SELECT` na
 * tabela — deixam de ser desenho e passam a ser caminho percorrido. Nenhuma
 * delas é deste ticket, e todas passam a depender dele.
 *
 * ## O `payload_hash` é um *hash* e não um registo
 *
 * O critério pede «*hash* antes/depois, origem», e é literalmente o que vai: um
 * SHA-256 de um texto canónico com o estado antes, o estado depois e a origem. O
 * `audit_log` **não guarda** o conteúdo — «nunca conteúdo de conversa: só hashes
 * e identificadores», diz o comentário da tabela —, pelo que o que a linha prova
 * é que **alguém com este actor alterou isto neste instante, e que o antes e o
 * depois eram estes**. Quem tiver os dois valores confirma-o; quem não os tiver
 * não os reconstrói do *hash*.
 *
 * Isso é uma limitação e não um descuido, e o critério 5 pede exactamente isto.
 * Quem precisar do valor anterior legível tem os eventos
 * `catalog.price_changed` e `stock.adjusted`, que o levam e vão para o DAT.
 *
 * O SHA-256 calcula-se **na base** (`sha256($8::bytea)`) e não no Node: a coluna
 * tem um `CHECK` de 32 bytes (`audit_log_hashes_sha256`), e calcular o *digest*
 * em JavaScript obrigava a passar um `bytea` pela fronteira do *driver* para
 * obter exactamente o mesmo valor que a base calcula sozinha a partir do texto.
 *
 * ## O texto canónico, e porque é que a forma importa
 *
 * ```text
 * <accao>\x1f<sku>\x1f<antes>\x1f<depois>\x1f<origem>
 * ```
 *
 * O separador é `\x1f` (US, *unit separator*), que é o mesmo que o
 * `CONCATENACAO_DO_ROW_HASH` da revisão `0006` e o `db/auditoria.py` usam para a
 * cadeia — e é o que o torna canónico: um separador que possa aparecer dentro de
 * um campo deixa dois pares diferentes com o mesmo *hash*. Com `|`, um preço que
 * mudou de `fixo|1200` para `nada` tinha o mesmo texto que um que mudou de
 * `fixo` para `1200|nada`.
 *
 * **A razão pela qual isto é injectivo não é a que esta nota dizia.** Dizia que
 * «o `\x1f` não aparece em nenhum dos campos: o `sku` e a origem são
 * identificadores» — e o `sku` **não** é validado na forma: o
 * `offer_terms_sku_ck` da `0028` exige só não-vazio, de propósito (um padrão
 * inventado recusava SKUs reais de PMEs angolanas, que não seguem nenhum), e o
 * `validarRascunho` só faz `trim()`. Um `sku` com um `\x1f` dentro é aceite pela
 * base.
 *
 * A propriedade sustenta-se à mesma, e a revisão adversarial estabeleceu-a: a
 * cadeia tem **exactamente** `4 + k` separadores, onde `k` é o número de `\x1f`
 * no `sku`; a acção e a origem vêm de domínios fechados sem `\x1f`, e o
 * antes/depois são números, instantes e valores de domínios fechados. Para duas
 * triplas distintas darem a mesma cadeia, o antes ou o depois teriam de absorver
 * um número diferente de separadores, e não podem. Dentro de um segmento o `,` e
 * o `=` do `canonico` não são escapados, mas os prefixos `campo=` são fixos e as
 * chaves estão ordenadas, pelo que a leitura é injectiva nos quatro sítios de
 * chamada deste módulo.
 *
 * Fica escrita a razão certa porque uma razão falsa a sustentar uma conclusão
 * certa é um defeito: o próximo leitor confia nela, e o dia em que alguém
 * acrescentar um campo de texto livre ao instantâneo, é esta contagem que tem de
 * ser refeita — não a suposição de que o `sku` é um identificador.
 */

import {
  ACCAO_PRECO,
  ACCAO_STOCK,
  ACTOR_AUDITADO,
  ENTIDADE_AUDITADA,
  type Actor,
  type ClienteSql,
} from "./contrato.ts";
import { SQL_AUDITAR } from "./consultas.ts";

/** O separador do texto canónico. US (*unit separator*), como a revisão `0006`. */
export const SEPARADOR = "\u001f";

/**
 * A origem de uma alteração: de onde veio o valor novo.
 *
 * É o terceiro pedaço que o critério 5 pede («actor, *hash* antes/depois,
 * **origem**»), e é distinto do actor: o actor é *quem*, a origem é *por onde*.
 * O dono a corrigir um preço no painel e o dono a responder a uma cotação são o
 * mesmo actor e origens diferentes, e é a diferença que uma auditoria de preço
 * precisa de ver.
 */
export const ORIGENS = [
  "upsert_rascunho",
  "publicacao",
  "ajuste_de_stock",
  "cotacao_do_dono",
  // KAM-099: o dono a corrigir o preço no painel — o caso que o parágrafo acima
  // já dava como exemplo de origem distinta.
  "painel_do_dono",
] as const;
export type Origem = (typeof ORIGENS)[number];

/** O estado de preço ou de stock, como texto canónico para o *hash*. */
export interface Instantaneo {
  readonly [campo: string]: string | number | bigint | null;
}

/**
 * Um instantâneo como texto canónico: `campo=valor`, pela ordem das chaves.
 *
 * **Ordenado**, e não pela ordem de inserção: dois objectos com os mesmos pares
 * em ordem diferente têm de dar o mesmo *hash*, senão o antes e o depois de uma
 * alteração que não mudou nada apareciam como diferentes.
 */
export function canonico(instantaneo: Instantaneo): string {
  return Object.keys(instantaneo)
    .sort()
    .map((campo) => `${campo}=${formatar(instantaneo[campo])}`)
    .join(",");
}

function formatar(valor: string | number | bigint | null | undefined): string {
  if (valor === null || valor === undefined) return "";
  return String(valor);
}

/**
 * O texto que se vai resumir em SHA-256.
 *
 * Exportado porque é o que um teste tem de poder reconstruir para afirmar que o
 * `payload_hash` de uma linha é o do par que ele semeou. Sem isto, a asserção
 * possível era «há uma linha de auditoria», que não prova que o *hash* seja do
 * que mudou.
 */
export function textoDoHash(
  accao: string,
  sku: string,
  antes: Instantaneo,
  depois: Instantaneo,
  origem: Origem,
): string {
  return [accao, sku, canonico(antes), canonico(depois), origem].join(SEPARADOR);
}

/**
 * Escreve a linha de auditoria. Corre na transacção de quem chama.
 *
 * **Na mesma transacção que a escrita**, e isso é a propriedade: uma alteração
 * de preço que ficasse escrita sem a linha de auditoria era uma alteração sem
 * rasto, e uma linha sem a alteração era um rasto falso. As duas entram ou
 * nenhuma entra — como o evento, pela mesma razão e no mesmo `BEGIN`.
 *
 * **`READ COMMITTED`**, que é a omissão do PostgreSQL. O `audit_append`
 * serializa a cadeia por tenant com um `FOR UPDATE` na `audit_heads`, e sob
 * `REPEATABLE READ` duas escritas concorrentes dão `40001` e a segunda
 * perde-se. Nenhuma operação deste módulo muda o nível de isolamento, e esta
 * nota existe para que ninguém o mude sem saber o que parte.
 */
async function auditar(
  cliente: ClienteSql,
  tenantId: string,
  actor: Actor,
  accao: string,
  sku: string,
  antes: Instantaneo,
  depois: Instantaneo,
  origem: Origem,
): Promise<void> {
  const actorType = ACTOR_AUDITADO[actor.kind];
  if (actorType === undefined) {
    // O mapa é total nos quatro `actor.kind` da porta. Um `kind` fora deles não
    // passa o `exigirCtx`, pelo que isto é inalcançável pela porta — e está
    // aqui porque o `audit_log_actor_type` da revisão `0006` recusava com
    // `23514` e a mensagem não dizia que o defeito era o mapa.
    throw new TypeError(
      `actor.kind '${actor.kind}' nao tem actor_type de auditoria. O mapa do ` +
        "dicionario §3.40 e total nos quatro valores da porta; o `contact` do " +
        "audit_log fica de fora de proposito, porque um cliente nunca altera " +
        "preco nem stock (KAM-043, criterio 5)",
    );
  }
  await cliente.query(SQL_AUDITAR, [
    tenantId,
    actorType,
    actor.id,
    accao,
    ENTIDADE_AUDITADA,
    sku,
    // `turn_id` nulo: estas alterações não vêm de um turno de conversa. O
    // `turn_id` é do caminho da ToolLayer, e preencher com o `traceId` dava-lhe
    // um valor que nenhuma consulta de auditoria sabe interpretar.
    null,
    textoDoHash(accao, sku, antes, depois, origem),
  ]);
}

/** Audita uma alteração de preço. `action = 'price.update'`. */
export function auditarPreco(
  cliente: ClienteSql,
  tenantId: string,
  actor: Actor,
  sku: string,
  antes: Instantaneo,
  depois: Instantaneo,
  origem: Origem,
): Promise<void> {
  return auditar(
    cliente,
    tenantId,
    actor,
    ACCAO_PRECO,
    sku,
    antes,
    depois,
    origem,
  );
}

/** Audita um ajuste de stock. `action = 'stock.adjust'`. */
export function auditarStock(
  cliente: ClienteSql,
  tenantId: string,
  actor: Actor,
  sku: string,
  antes: Instantaneo,
  depois: Instantaneo,
  origem: Origem,
): Promise<void> {
  return auditar(
    cliente,
    tenantId,
    actor,
    ACCAO_STOCK,
    sku,
    antes,
    depois,
    origem,
  );
}

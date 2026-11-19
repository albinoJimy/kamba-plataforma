/**
 * O `screen` do KAM-088 servido a quem não é TypeScript (KAM-222).
 *
 * O motor do screening só existe em `packages/core-ts/src/screening/`, e o
 * Python chama-o por aqui, pela 12.ª rota da API interna
 * (`POST /internal/screen`). **Não há segundo motor**: quem decide é o `screen`
 * da biblioteca, com a política compilada (`politicaCorrente()`), o
 * classificador pelo AGR e o escritor da `platform.screening_decision`. Esta
 * operação só monta as três peças.
 *
 * ## Duas transacções curtas, e nenhuma durante o classificador
 *
 * O `screen` consulta o classificador **antes** de gravar, e o classificador é
 * uma chamada ao AGR com tecto de 15 s (`TEMPO_MAXIMO_MS`). Embrulhar o `screen`
 * inteiro num `comTenant` deixava uma ligação do `Pool` presa durante a chamada
 * ao modelo. Por isso há duas transacções: uma lê a categoria declarada do
 * tenant (quando o pedido não a traz) e a outra grava a decisão. Cada uma toma a
 * sua ligação e devolve-a.
 *
 * ## A categoria declarada, quando o pedido não a traz
 *
 * É a do tenant: a `sujeito_ref` da decisão `categoria` mais recente. É a regra
 * da re-análise (`SQL_POR_REANALISAR`), e é ela que serve as condições de um
 * orçamento, que não têm categoria própria. Sem decisão de categoria fica
 * vazia, e o `screen` lê `nao_listada`, que é `condicional`: um tenant sem
 * categoria avaliada não tem nada `permitida`.
 *
 * ## O sujeito `categoria` não entra por aqui
 *
 * A decisão de categoria é a do onboarding, e a re-análise lê a mais recente
 * como «a categoria declarada do tenant». Se um chamador interno pudesse gravar
 * uma, um defeito no AGR mudava a categoria do tenant. A rota aceita só os
 * sujeitos de `SUJEITOS_DA_ROTA`.
 *
 * ## *Fail-closed*
 *
 * Qualquer falha (base, escritor) devolve `UPSTREAM_DOWN`, e o chamador recusa.
 * Isto inclui o caso de o sujeito ainda não estar no `CHECK` da
 * `screening_decision`. Uma decisão que não ficou gravada não existe (KAM-088),
 * e por isso não se devolve. O classificador em baixo **não** é falha daqui: o
 * `screen` trata-o como `condicional`, e essa resposta sai com 200.
 */

import {
  EscritorSql,
  SUJEITOS,
  screen,
  type ClassificadorDeCategorias,
  type PoliticaCompilada,
  type ResultadoDoScreen,
  type SujeitoTipo,
} from "@kamba/core-ts/screening";

import {
  erro,
  exigirCtx,
  ok,
  type ComTenant,
  type Ctx,
  type ResultadoFinal,
} from "../port/index.ts";

/**
 * Os sujeitos que a rota aceita: os do `CHECK`, menos a `categoria` (ver a nota
 * do módulo). Derivados e não escritos à mão: um sujeito novo no `SUJEITOS` do
 * `tipos.ts` entra aqui sem segunda edição.
 */
export const SUJEITOS_DA_ROTA: readonly SujeitoTipo[] = SUJEITOS.filter(
  (sujeito) => sujeito !== "categoria",
);

/** O pedido que a rota valida. `categoriaDeclarada` `null` quer dizer «a do tenant». */
export interface PedidoDeScreen {
  readonly sujeitoTipo: SujeitoTipo;
  readonly sujeitoRef: string;
  readonly categoriaDeclarada: string | null;
  readonly textos: readonly string[];
}

/**
 * A categoria declarada do tenant: a da decisão de categoria mais recente.
 * A mesma ordem do `SQL_POR_REANALISAR`.
 */
export const SQL_CATEGORIA_DO_TENANT = `
SELECT sujeito_ref FROM platform.screening_decision
WHERE tenant_id = $1 AND sujeito_tipo = 'categoria'
ORDER BY criado_at DESC, id DESC LIMIT 1`;

export interface DependenciasDoScreenDoCom {
  readonly comTenant: ComTenant;
  readonly politica: PoliticaCompilada;
  /** `null` quando o AGR não está configurado: o `screen` lê-o como indisponível. */
  readonly classificador: ClassificadorDeCategorias | null;
}

export type OperacaoDeScreen = (
  ctx: Ctx,
  pedido: PedidoDeScreen,
) => Promise<ResultadoFinal<ResultadoDoScreen>>;

export function operacaoDeScreen(deps: DependenciasDoScreenDoCom): OperacaoDeScreen {
  return async (ctx, pedido) => {
    // Antes de qualquer ligação, como em todo o COM (ISO-09).
    const { tenantId } = exigirCtx(ctx);
    if (!SUJEITOS_DA_ROTA.includes(pedido.sujeitoTipo)) return erro("VALIDATION_ERROR");
    try {
      const categoria =
        pedido.categoriaDeclarada ??
        (await deps.comTenant(tenantId, async (cliente) => {
          const { rows } = await cliente.query(SQL_CATEGORIA_DO_TENANT, [tenantId]);
          const valor = rows[0]?.["sujeito_ref"];
          return typeof valor === "string" ? valor : "";
        }));
      const resultado = await screen(
        { tenantId, sujeitoTipo: pedido.sujeitoTipo, sujeitoRef: pedido.sujeitoRef },
        { categoria_declarada: categoria, textos: pedido.textos },
        {
          politica: deps.politica,
          classificador: deps.classificador,
          escritor: {
            gravar: (linha) =>
              deps.comTenant(tenantId, (cliente) =>
                new EscritorSql(cliente as unknown as ConstructorParameters<typeof EscritorSql>[0]).gravar(
                  linha,
                ),
              ),
          },
        },
      );
      return ok(resultado);
    } catch {
      // Sem a excepção no corpo nem no registo: a mensagem de um erro do
      // `pg` pode citar o valor de uma coluna, e a coluna aqui é texto do dono.
      return erro("UPSTREAM_DOWN");
    }
  };
}

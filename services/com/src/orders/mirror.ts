/**
 * O espelho: criar a linha de `orders_mirror` e emitir `order.created`.
 *
 * ## O que este ficheiro **não** é
 *
 * Não é a `createOrder` da porta, que é o **KAM-046**: a saga de §6.3 — recibo
 * de intenção, resolução de preços pelo Registo, reserva de stock, pedido de
 * confirmação ao dono — é desse ticket, e o bloco deste diz por extenso «não
 * expandas escopo: … o `createOrder` é o KAM-046».
 *
 * O que é deste ticket é a **primitiva de escrita do espelho**, que o critério 8
 * obriga a existir: o `order.created` é um dos eventos que têm de sair pelo
 * outbox, e um evento sai quando a linha nasce. É o módulo `mirror` dos
 * *Detalhes Técnicos*, ao lado do `transition`, do `graph` e do `reconcile`.
 *
 * A `createOrder` do KAM-046 chama isto depois de resolver as linhas, e é lá que
 * o `order_intents` passa a `concluida`.
 *
 * ## Nasce `criada`, e não há outra porta
 *
 * O §6.2 tem uma seta de entrada só, e o *trigger* `order_nasce_criada` da
 * revisão `0030` recusa um `INSERT` em qualquer outro estado. Esta função não
 * passa `estado` nenhum: a omissão da coluna é `criada`.
 *
 * A linha de `order_state_log` **não** se escreve aqui, e é a diferença entre
 * nascer e transitar: as colunas do registo são `de` e `para`, com
 * `CHECK (de <> para)` e `CHECK (version >= 2)`, e a criação não tem `de`. Quem
 * quiser saber quando a encomenda nasceu lê o `criado_at`, que é a coluna
 * desenhada para isso. O *trigger* diferido não dispara no `INSERT` (é `AFTER
 * UPDATE`), pelo que as duas regras não se contradizem.
 */

import {
  EMISSOES,
  emitir,
  payloadDeCriada,
} from "./eventos.ts";
import type { EspelhoNovo, EstadoDaEncomenda, OrderState } from "./contrato.ts";
import type { Encomendas } from "./transition.ts";

/** A tabela do espelho. */
export const TABELA_DO_ESPELHO = "orders_mirror";

/**
 * As colunas que a inserção devolve. O mesmo conjunto do `SQL_LER` e do
 * `SQL_TRANSITAR`, para que `EstadoDaEncomenda` se monte sempre da mesma forma.
 */
const DEVOLVE =
  "RETURNING id, numero_publico, estado, version, total_minor, currency, " +
  "expira_at, paga_via, entrega_confirmada_por";

/**
 * Cria o espelho e emite `order.created` na mesma transacção.
 *
 * O `total_minor` entra como texto e não como `number`: é `bigint` do lado do
 * TypeScript (o `OrderView.totalMinor` da porta já o é) e um `Number` perdia
 * precisão acima de 2^53 cêntimos sem avisar. O *driver* converte o texto para
 * `bigint` do PostgreSQL sem passar por ponto flutuante.
 */
export async function registar(
  e: Encomendas,
  espelho: EspelhoNovo,
): Promise<EstadoDaEncomenda> {
  const linhas = await e.repo.inserirNoTenant({
    tabela: TABELA_DO_ESPELHO,
    valores: {
      contact_id: espelho.contactId,
      origem: espelho.origem ?? "pme",
      intent_key: espelho.intentKey,
      medusa_order_id: espelho.medusaOrderId ?? null,
      confirmacao_dono: espelho.confirmacaoDono ?? "nao_aplicavel",
      total_minor: espelho.totalMinor.toString(),
      currency: espelho.currency,
      lines_snapshot: JSON.stringify(
        espelho.linhas.map((linha) => ({
          sku: linha.sku,
          nome: linha.nome,
          qty: linha.qty,
          preco_minor: linha.precoMinor.toString(),
          preco_tipo: linha.precoTipo,
          origem_preco: linha.origemPreco,
        })),
      ),
      entrega_modo: espelho.entregaModo,
    },
    sufixo: DEVOLVE,
  });
  const linha = linhas[0];
  if (linha === undefined) {
    throw new Error(
      "platform.orders_mirror nao devolveu a linha inserida: sem ela nao ha " +
        "order_id para o order.created, e o evento tem de sair na mesma " +
        "transaccao (KAM-044, criterio 8)",
    );
  }
  const estado: EstadoDaEncomenda = {
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    estado: String(linha["estado"]) as OrderState,
    version: Number(linha["version"]),
    totalMinor: BigInt(String(linha["total_minor"])),
    currency: String(linha["currency"]),
    expiraAt: linha["expira_at"] === null ? null : String(linha["expira_at"]),
    pagaVia: linha["paga_via"] === null ? null : String(linha["paga_via"]),
    entregaConfirmadaPor:
      linha["entrega_confirmada_por"] === null
        ? null
        : String(linha["entrega_confirmada_por"]),
  };

  await emitir(e.emitir, e.ctx.tenantId, {
    ...EMISSOES.criada,
    orderId: estado.orderId,
    payload: payloadDeCriada(
      estado.orderId,
      espelho.contactId,
      estado.numeroPublico,
      espelho.origem ?? "pme",
      estado.totalMinor,
      estado.currency,
      espelho.entregaModo,
      espelho.linhas,
      estado.expiraAt,
    ),
  });
  return estado;
}

/**
 * Os `statuses[]` e o seu `pricing` (KAM-024, critério 1).
 *
 * O critério pede `sent`, `delivered`, `read` e `failed`, **com `pricing`** — e
 * o `pricing` é a parte que nenhuma *fixture* deste repositório tinha. É ele que
 * sustenta duas coisas que vêm depois:
 *
 * - o critério 4 do KAM-015 («o `pricing` dos estados é guardado por mensagem; um
 *   estado com categoria *service* acima do *free tier* incrementa
 *   `meta_cost_usd_total{tenant}` em 0,004»);
 * - o descarte sob saturação do GWY, que **nunca** deita fora um `statuses` com
 *   `pricing` — a `soEstadosSemPreco` de `services/gwy/src/webhook.ts` diz-o, e
 *   a sua docstring aponta este ticket pelo nome: «o KAM-024 gera *fixtures* de
 *   `statuses` "com `pricing`"».
 *
 * ## Os factos, e o seu estado
 *
 * **CONFIRMADO** (`E1` §1, `DOC/pricing`, Out 2026): desde 2026-10-01 as
 * *service messages* são pagas a partir da 1.001.ª por número e mês, a 0,004 USD
 * em *Rest of Africa*; a cobrança é por mensagem **entregue**. **CONFIRMADO**
 * (`E1` §5): os estados chegam sem ordem garantida e com entrega concorrente.
 *
 * **NÃO VERIFICADO**: o conjunto exacto de valores de `pricing.type` e de
 * `pricing.category` que a Meta usa hoje. As páginas lidas dão `service`,
 * `utility`, `authentication` e `marketing` para a categoria e `CBP` para o
 * modelo; o simulador usa esses e **não inventa** outros. Fica como parâmetro:
 * quem descobrir mais acrescenta aqui, e a *suite* online do critério 8 é o que
 * os compara com o que a Meta manda de verdade.
 */

import { CODIGOS_PROPOSTOS } from "./codigos.ts";
import type { Gerador } from "./semente.ts";

/** A base do tempo das *fixtures*: 2026-10-01, quando as *service* passaram a ser pagas. */
export const BASE_DO_TEMPO = 1_790_812_800;

/** Segundos entre dois degraus da escada. Dois minutos chegam e são legíveis. */
export const PASSO_DA_ESCADA = 120;

/** Os quatro estados que o critério pede. `failed` é terminal. */
export const ESTADOS = ["sent", "delivered", "read", "failed"] as const;
export type Estado = (typeof ESTADOS)[number];

/**
 * As categorias de conversa que a Meta factura. `marketing` está aqui para que
 * uma *fixture* a possa produzir — o Piloto recusa-a no **envio** (KAM-015),
 * e recusar no envio é diferente de não saber ler o que chega.
 */
export const CATEGORIAS = ["service", "utility", "authentication", "marketing"] as const;
export type Categoria = (typeof CATEGORIAS)[number];

/** O modelo de preço. `CBP` é o único que as páginas lidas nomeiam. */
export const MODELO = "CBP";

/** O preço em USD por categoria, em *Rest of Africa* (`E1` §1, CONFIRMADO). */
export const PRECO_USD: Readonly<Record<Categoria, number>> = {
  service: 0.004,
  utility: 0.004,
  authentication: 0.004,
  marketing: 0.0225,
};

/** Opções de um item de `statuses[]`. */
export interface Opcoes {
  /** O `wamid` da mensagem a que o estado se refere. */
  readonly wamid: string;
  readonly estado: Estado;
  /** O interlocutor, por telefone. */
  readonly recipienteId: string;
  /** O BSUID do interlocutor, quando existe. */
  readonly recipienteUserId?: string;
  readonly categoria?: Categoria;
  /**
   * `false` produz um estado **sem** `pricing`.
   *
   * É o caso que o descarte sob saturação do GWY pode deitar fora, e tem de
   * existir como *fixture* para que o teste do critério 7 do KAM-013 possa
   * distinguir os dois.
   */
  readonly comPricing?: boolean;
  readonly instante?: string;
}

/**
 * Um item de `statuses[]`.
 *
 * Um `failed` leva `errors[]` e **não** leva `pricing`: não se cobra uma
 * mensagem que não foi entregue (`E1` §1, «cobrança por mensagem entregue»).
 * Um `sent` leva `pricing` porque a Meta o manda, e é no `delivered` que a
 * contagem conta — essa decisão é do KAM-015, não desta *fixture*.
 */
export function estado(g: Gerador, opcoes: Opcoes): Record<string, unknown> {
  const categoria = opcoes.categoria ?? "service";
  const quando = opcoes.instante ?? String(BASE_DO_TEMPO + g.inteiro(30 * 24 * 60 * 60));
  // Um `failed` **não** leva `pricing` por omissão — não se cobra uma mensagem
  // que não foi entregue (`E1` §1: cobrança por mensagem entregue) —, mas um
  // `comPricing: true` **explícito** é honrado. A primeira versão engolia-o em
  // silêncio, e com isso não havia forma de gerar o caso que o KAM-015 tem de
  // recusar; o critério 1 escreve «`statuses` (…, `failed`, com `pricing`)», e
  // um gerador que não consiga produzir o caso não serve para o testar. Quem
  // decide se um `failed` com `pricing` é legítimo é o KAM-015, não o gerador.
  const comPricing = opcoes.comPricing ?? opcoes.estado !== "failed";
  const conversa = {
    id: `${g.texto(32, "0123456789abcdef")}`,
    origin: { type: categoria },
  };
  return {
    id: opcoes.wamid,
    status: opcoes.estado,
    timestamp: quando,
    recipient_id: opcoes.recipienteId,
    ...(opcoes.recipienteUserId === undefined
      ? {}
      : { recipient_user_id: opcoes.recipienteUserId }),
    ...(opcoes.estado === "failed"
      ? {
          errors: [
            {
              // O código é **NÃO VERIFICADO** e vem do `codigos.ts`, que o diz:
              // uma *fixture* de `failed` precisa de um número, e inventá-lo
              // aqui à mão era o que fazia alguém tratá-lo como sentinela.
              code: CODIGOS_PROPOSTOS.naoEntregue,
              title: "Message undeliverable",
              message: "Message could not be delivered.",
            },
          ],
        }
      : { conversation: conversa }),
    ...(comPricing
      ? {
          pricing: {
            billable: true,
            pricing_model: MODELO,
            type: categoria === "service" ? "service" : "regular",
            category: categoria,
          },
        }
      : {}),
  };
}

/**
 * Os quatro estados da **mesma** mensagem, pela ordem monótona.
 *
 * Serve o critério 3 do KAM-015 («`delivered` seguido de `sent` mantém
 * `delivered`») e o perfil de carga do critério 7 do KAM-013 («3 estados por
 * mensagem»). A ordem devolvida é a correcta; quem quiser a trocada inverte a
 * lista, e é isso que prova a monotonia.
 */
export function escada(
  g: Gerador,
  base: Omit<Opcoes, "estado">,
): readonly Record<string, unknown>[] {
  // **Os instantes crescem, e isso é uma correcção da revisão adversarial.**
  // A primeira versão deixava cada estado tirar o seu `timestamp` do gerador,
  // e em cinco de seis sementes a «escada» saía com os instantes fora de ordem:
  // o `read` podia levar um `timestamp` anterior ao do `sent`. O caso
  // `ordem_trocada` do `adversos.ts` é construído a partir daqui e declara que
  // «o estado final fica `read` e não `sent`» — uma implementação do KAM-015
  // que resolva a monotonia pelo `timestamp`, que é a leitura natural de «os
  // estados chegam sem ordem garantida», ficava a ser medida contra uma
  // *fixture* que diz o contrário dos seus próprios dados, e o veredicto mudava
  // com a semente.
  //
  // A ordem do **array** continua a ser a correcta, e quem quiser a trocada
  // inverte-o: é isso que prova a monotonia, e agora os dois eixos — a posição
  // e o instante — dizem a mesma coisa.
  const inicio = Number(base.instante ?? String(BASE_DO_TEMPO + g.inteiro(30 * 24 * 60 * 60)));
  return ESTADOS.filter((e) => e !== "failed").map((e, indice) =>
    estado(g, { ...base, estado: e, instante: String(inicio + indice * PASSO_DA_ESCADA) }),
  );
}

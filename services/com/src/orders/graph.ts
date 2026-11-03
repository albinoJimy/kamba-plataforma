/**
 * O grafo de transições, lido da base (critério 1).
 *
 * **A fonte é a tabela `platform.order_state_graph` e não uma lista aqui.** O
 * critério 1 diz que as transições são dados «validados por *trigger* `BEFORE
 * UPDATE`», e quem recusa uma transição é esse *trigger*. Uma segunda lista em
 * TypeScript podia divergir da primeira, e a que manda não era a que o
 * programador lia — o que é a forma mais barata de um módulo ficar a dizer que
 * uma transição é válida enquanto a base a recusa.
 *
 * O que este ficheiro dá é **leitura e predicado**: o módulo decide se vale a
 * pena tentar (e devolve um erro da porta em vez de um `KA003` do PostgreSQL), e
 * a base decide se passa. As duas decisões têm de concordar, e o
 * `test_grafo.py` do gate 8 prova que concordam sobre **todos** os pares de
 * estados — os válidos e os outros cento e trinta e dois.
 *
 * ## A bandeira é lida em execução
 *
 * Duas linhas do núcleo levam `flag = 'COM_DELIVERY_ENABLED'`: o `em_entrega` do
 * critério 1, desligado no Piloto. O estado da bandeira **não** está nesta
 * tabela — está em `current_setting('app.com_delivery_enabled')`, que é o que
 * permite ligá-la «sem migração», como o bloco do KAM-050 exige. Por isso
 * `transicaoPermitida` recebe o estado da bandeira de fora: este módulo não
 * adivinha configuração.
 */

import type { OrderState } from "../port/contrato.ts";
import type { ClienteSql, Transicao } from "./contrato.ts";
import { SQL_GRAFO } from "./consultas.ts";

/**
 * Lê o grafo inteiro. Doze linhas hoje; o KAM-050 acrescenta mais.
 *
 * Entra pela porta estreita das chamadas de função e não pelo repo-base: a
 * tabela **não tem `tenant_id`** (as transições válidas de um sistema não são
 * configuração de tenant), pelo que o `tenant_id = $1` que o repo-base exige
 * não existe aqui e não pode existir.
 */
export async function lerGrafo(
  cliente: ClienteSql,
): Promise<readonly Transicao[]> {
  const { rows } = await cliente.query(SQL_GRAFO);
  return rows.map((linha) => ({
    de: String(linha["de"]) as OrderState,
    para: String(linha["para"]) as OrderState,
    flag: linha["flag"] === null ? null : String(linha["flag"]),
  }));
}

/**
 * A transição está no grafo **e** a bandeira dela está ligada?
 *
 * Devolve `false` nos dois casos em que o *trigger* levanta `KA003`: o par não
 * existir, e existir atrás de uma bandeira desligada. Não os distingue de
 * propósito — para quem chama a porta, as duas respostas são a mesma recusa, e
 * quem precisa de saber qual foi lê o grafo.
 */
export function transicaoPermitida(
  grafo: readonly Transicao[],
  de: OrderState,
  para: OrderState,
  bandeirasLigadas: readonly string[] = [],
): boolean {
  const linha = grafo.find((t) => t.de === de && t.para === para);
  if (linha === undefined) return false;
  if (linha.flag === null) return true;
  return bandeirasLigadas.includes(linha.flag);
}

/** Os destinos alcançáveis a partir de um estado, com as bandeiras dadas. */
export function destinosDe(
  grafo: readonly Transicao[],
  de: OrderState,
  bandeirasLigadas: readonly string[] = [],
): readonly OrderState[] {
  return grafo
    .filter((t) => t.de === de && transicaoPermitida(grafo, de, t.para, bandeirasLigadas))
    .map((t) => t.para);
}

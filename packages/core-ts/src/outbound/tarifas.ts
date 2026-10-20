/**
 * As tarifas da Meta, e o custo de uma mensagem entregue (KAM-015, critério 4).
 *
 * ## Micro-dólares inteiros, e não vírgula flutuante
 *
 * O §2 do dicionário manda «dinheiro em unidade menor inteira (`*_minor`) com
 * moeda explícita; **nunca vírgula flutuante**», e aqui isso não é formalidade:
 * 0,004 não é representável em binário, e somar mil vezes `0.004` em `float64`
 * **não dá 4,00**. Num acumulador de custo isso é deriva que ninguém consegue
 * reconciliar contra uma factura da Meta.
 *
 * O centavo não serve de unidade menor: 0,004 USD são 0,4 centavos. A unidade é
 * o **micro-dólar** (1e-6 USD), que torna as quatro tarifas inteiras e exactas.
 * Divide-se por um milhão **uma vez**, no fim, para apresentar — nunca no meio
 * de uma soma.
 *
 * O defeito foi apanhado pelo `tools/kamba_yaml.py`, que só converte inteiros e
 * recusou a primeira versão de `config/meta_rates.yaml`. Apanhou-o no sítio
 * certo.
 *
 * ## Porque é que estes números estão aqui **e** num YAML
 *
 * `config/meta_rates.yaml` é o que uma pessoa lê e o que o KAM-023 vai ler em
 * Python: uma tarifa é um facto sobre o mundo e precisa de fonte, data e estado
 * de verificação ao lado. Estas constantes são o que o código usa, porque **não
 * há leitor de YAML em `packages/core-ts`** e acrescentar um era trazer uma
 * dependência de terceiros ao caminho de produção para ler quatro números que
 * mudam uma vez por trimestre.
 *
 * As duas fontes não divergem por acidente: o `TestTarifas` de
 * `db/tests_outbound/test_outbound.py` compara-as **como texto**, e é em Python
 * porque é lá que há leitor de YAML.
 * É o mesmo desenho que o `tools/meta-sim/fake_numbers.yaml` usa para o
 * intervalo fictício, e pela mesma razão escrita lá.
 *
 * ## O estado de verificação
 *
 * **CONFIRMADO** (`docs/tecnica/evidencia/E1` §1, zona *Rest of Africa*,
 * efectivas 2026-10-01): as quatro tarifas, e que a cobrança é **na entrega e
 * não no envio**.
 *
 * **Proposta, e não CONFIRMADO**: a cadência trimestral de revisão. O
 * `docs/tecnica/01` §8.4 diz de si mesmo «calendário a confirmar» e o `E1` §1
 * diz que o «1.º dia do trimestre» vem de resumo de pesquisa. O que protege de
 * uma tarifa velha não é o calendário — é o `pricing` que chega em cada
 * `statuses`, que é o que a Meta cobrou.
 */

import type { Categoria, Pricing } from "./contrato.ts";

/** Micro-dólares num dólar. Divide-se por isto **uma vez**, no fim. */
export const MICRO_USD_POR_USD = 1_000_000;

/** A zona de preço. */
export const ZONA = "rest_of_africa";

/** A data em que estas tarifas entraram em vigor. */
export const EFECTIVAS_EM = "2026-10-01";

/**
 * O preço de uma mensagem entregue, em micro-dólares, por categoria.
 *
 * CONFIRMADO, `E1` §1. O `marketing` é cerca de 5,6× a `utility`, e está aqui
 * porque a Meta pode **recategorizar** um template — o que o Piloto recusa é
 * enviar nessa categoria.
 */
export const MICRO_USD_POR_CATEGORIA: Readonly<Record<Categoria, number>> = {
  service: 4_000,
  utility: 4_000,
  authentication: 4_000,
  marketing: 22_500,
};

/**
 * O custo de um `pricing` que chegou, em micro-dólares.
 *
 * **Lê o `pricing` e não a nossa categoria**, e a diferença é o ponto: o que se
 * cobra é o que a Meta diz ter cobrado. Se o `pricing.category` divergir do
 * `kind` com que enviámos — e divergir é exactamente o que acontece numa
 * recategorização —, é o `pricing` que manda.
 *
 * Devolve `0` quando o `billable` é falso, que é o caso de uma mensagem dentro
 * do *free tier* ou numa janela FEP, e quando a categoria não é nenhuma das
 * quatro — porque uma categoria que não conhecemos não se converte num número
 * inventado. Um `pricing` com categoria desconhecida é um achado para quem
 * opera, não um custo a adivinhar.
 */
export function microUsdDe(pricing: Pricing | null): number {
  if (pricing === null || !pricing.billable) return 0;
  const tarifa = MICRO_USD_POR_CATEGORIA[pricing.category as Categoria];
  return tarifa === undefined ? 0 : tarifa;
}

/**
 * `true` quando o `pricing` traz uma categoria que não conhecemos.
 *
 * Existe à parte do `microUsdDe` porque são duas perguntas diferentes: «quanto
 * custou» e «sei o que isto é». A primeira responde `0` para não inventar; a
 * segunda é a que tem de fazer barulho, e é ela que alimenta a métrica.
 */
export function categoriaDesconhecida(pricing: Pricing | null): boolean {
  if (pricing === null || !pricing.billable) return false;
  return MICRO_USD_POR_CATEGORIA[pricing.category as Categoria] === undefined;
}

/**
 * Micro-dólares em dólares, com duas casas, **só para apresentar**.
 *
 * Nunca se usa no meio de uma soma: é a última operação antes de um painel ou
 * de um relatório. O nome diz `paraMostrar` por isso.
 */
export function paraMostrar(microUsd: number): string {
  // **Arredonda primeiro, divide depois**, e a ordem é a correcção de um
  // defeito medido: a primeira versão separava os dólares com uma divisão
  // inteira e arredondava o resto em separado, pelo que um resto de 996 000
  // (249 mensagens entregues) dava `Math.round(99,6) = 100` — saía `"0.100"`,
  // com um terceiro dígito e sem o dólar incrementado. Com os centavos
  // calculados primeiro, o transporte faz-se sozinho.
  const centavos = Math.round(microUsd / 10_000);
  const dolares = Math.floor(centavos / 100);
  return `${dolares}.${String(centavos % 100).padStart(2, "0")}`;
}

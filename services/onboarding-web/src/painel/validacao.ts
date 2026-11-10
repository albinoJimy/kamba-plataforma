/**
 * A validação do pedido de gravação do painel (KAM-099, critério 5).
 *
 * «Preço inteiro em Kz ≥ 0 e ≤ um máximo configurável; alteração de preço
 * > ±50% (*proposta*) pede confirmação extra; stock ≥ 0.»
 *
 * Funções puras: nenhuma vai à rede, e todas correm **antes** de o painel
 * chamar o COM. O COM repete a parte que é dele (o par modo/preço, `≥ 0`,
 * inteiros), e isso não é duplicar a regra: é a mesma barreira em quem a
 * recebe sem passar por aqui.
 *
 * ## É `preco_tipo`, e não `preco_modo`
 *
 * O bloco escreve `preco_modo` no corpo do `PATCH`. O dicionário §3.3 põe
 * `preco_modo` na coluna «Substitui» desde a emenda 1.12, e o COM resolveu a
 * mesma divergência a favor do dicionário (`services/com/src/port/contrato.ts`).
 * O corpo usa `preco_tipo`; a divergência fica registada na verificação do
 * bloco.
 *
 * ## O preço viaja em unidade menor, e tem de ser Kz inteiros
 *
 * O corpo leva `preco_minor`, como todo o dinheiro desta casa (dicionário §3.3:
 * o `preco_kz` está na coluna «Substitui»). O dono escreve Kz na página, e é o
 * guião que acrescenta os dois zeros; aqui recusa-se o que não for múltiplo de
 * 100, porque o critério 5 pede «preço inteiro em Kz».
 */

import { PRECO_TIPOS, type PrecoTipo } from "./comercio.ts";

/** Unidades menores por kwanza. */
export const CENTIMOS_POR_KZ = 100n;

/**
 * O preço máximo por omissão, em Kz. ***Proposta***: 100 000 000 Kz.
 *
 * Configurável por `PAINEL_PRECO_MAXIMO_KZ` (critério 5). O número não é um
 * limite de negócio: é o que separa um preço de um engano de teclado com zeros
 * a mais.
 */
export const PRECO_MAXIMO_KZ_POR_OMISSAO = 100_000_000n;

/** O stock máximo aceite. ***Proposta***: um milhão de unidades. */
export const STOCK_MAXIMO = 1_000_000;

/** A variação a partir da qual se pede confirmação, em pontos percentuais. ***Proposta***: 50. */
export const VARIACAO_QUE_PEDE_CONFIRMACAO = 50n;

/** O pedido já validado, e o que falta saber dele. */
export interface PedidoValido {
  readonly precoTipo: PrecoTipo;
  readonly precoMinor: bigint | null;
  readonly stock?: number | undefined;
  readonly versao: string;
  readonly confirmarVariacao: boolean;
}

export type Leitura = { readonly tipo: "ok"; readonly pedido: PedidoValido } | { readonly tipo: "erro"; readonly campo: string };

/** O preço máximo em Kz, de uma variável de ambiente, ou a omissão. Lança se ilegível. */
export function precoMaximoKz(bruto: string | undefined): bigint {
  const limpo = (bruto ?? "").trim();
  if (limpo === "") return PRECO_MAXIMO_KZ_POR_OMISSAO;
  if (!/^[0-9]{1,15}$/.test(limpo) || BigInt(limpo) === 0n) {
    throw new Error("PAINEL_PRECO_MAXIMO_KZ invalida");
  }
  return BigInt(limpo);
}

/**
 * O corpo do `PATCH`, validado. Devolve o **campo** que falhou, e não o valor.
 *
 * `preco_minor` é cadeia de dígitos ou inteiro seguro, múltiplo de 100 (Kz
 * inteiros). Ausente ou `null` para `sob_consulta`, e obrigatório nos outros dois.
 */
export function lerPedido(corpo: Record<string, unknown>, maximoKz: bigint): Leitura {
  const precoTipo = corpo["preco_tipo"];
  if (typeof precoTipo !== "string" || !(PRECO_TIPOS as readonly string[]).includes(precoTipo)) {
    return { tipo: "erro", campo: "preco_tipo" };
  }
  const bruto = corpo["preco_minor"];
  let precoMinor: bigint | null = null;
  if (precoTipo === "sob_consulta") {
    if (bruto !== undefined && bruto !== null) return { tipo: "erro", campo: "preco_minor" };
  } else {
    let minor: bigint | null = null;
    if (typeof bruto === "string" && /^[0-9]{1,17}$/.test(bruto)) minor = BigInt(bruto);
    if (typeof bruto === "number" && Number.isSafeInteger(bruto) && bruto >= 0) minor = BigInt(bruto);
    if (minor === null || minor % CENTIMOS_POR_KZ !== 0n || minor > maximoKz * CENTIMOS_POR_KZ) {
      return { tipo: "erro", campo: "preco_minor" };
    }
    precoMinor = minor;
  }
  const stock = corpo["stock"];
  if (stock !== undefined && stock !== null) {
    if (typeof stock !== "number" || !Number.isSafeInteger(stock) || stock < 0 || stock > STOCK_MAXIMO) {
      return { tipo: "erro", campo: "stock" };
    }
  }
  const versao = corpo["versao"];
  if (typeof versao !== "string" || versao.length === 0 || versao.length > 40) {
    return { tipo: "erro", campo: "versao" };
  }
  const confirmar = corpo["confirmar_variacao"];
  if (confirmar !== undefined && typeof confirmar !== "boolean") return { tipo: "erro", campo: "confirmar_variacao" };
  return {
    tipo: "ok",
    pedido: {
      precoTipo: precoTipo as PrecoTipo,
      precoMinor,
      ...(typeof stock === "number" ? { stock } : {}),
      versao,
      confirmarVariacao: confirmar === true,
    },
  };
}

/**
 * A variação do preço, em pontos percentuais inteiros arredondados para cima,
 * ou `null` quando não se compara.
 *
 * Não se compara quando um dos dois lados não tem número (`sob_consulta`, ou um
 * preço anterior nulo): passar de «sob consulta» a um preço não é uma variação,
 * é o primeiro preço. Um preço anterior **zero** que passa a positivo é
 * variação infinita, e devolve-se o tecto que pede sempre confirmação.
 */
export function variacaoPct(antes: bigint | null, depois: bigint | null): bigint | null {
  if (antes === null || depois === null) return null;
  if (antes === 0n) return depois === 0n ? 0n : 1_000_000n;
  const diferenca = depois > antes ? depois - antes : antes - depois;
  return (diferenca * 100n + antes - 1n) / antes;
}

/** A gravação precisa de confirmação extra? */
export function pedeConfirmacao(antes: bigint | null, depois: bigint | null): boolean {
  const v = variacaoPct(antes, depois);
  return v !== null && v > VARIACAO_QUE_PEDE_CONFIRMACAO;
}

/**
 * As decisões da qualidade do canal: o que cada valor manda fazer (KAM-021).
 *
 * Tudo aqui é função pura. O estado vive na base (`consultas.ts`) e o que este
 * módulo faz é decidir, a partir de valores, o que se restringe, o que se repõe
 * e o que se avisa. É a divisão que o `estados.ts` do KAM-015 e o `custo.ts` do
 * KAM-023 já usam, e serve a mesma finalidade: estas regras provam-se sem base
 * de dados, e o que precisa de base prova-se contra uma base verdadeira.
 */

import {
  ESTADO_ACTIVO,
  ESTADO_RESTRITO,
  FRACCAO_DE_AVISO,
  TECTO_POR_ESCALAO,
  type Qualidade,
  type Utilizacao,
} from "./contrato.ts";

/** O que a qualidade manda fazer ao estado do canal. */
export type Accao = "restringir" | "repor" | "nada";

/**
 * O que fazer ao canal, dada a qualidade nova e o estado em que ele está
 * (critério 2).
 *
 * As regras, e cada uma é uma linha do critério:
 *
 * * **`red` restringe**, e só se o canal não estiver já restrito — o critério
 *   pede «1 transição» e um `red` repetido não é uma transição nova;
 * * **`green` e `yellow` repõem**, e só quando o canal está restrito **por
 *   qualidade**. Quem verifica o motivo é a consulta, não esta função: aqui
 *   decide-se pelo estado, e o `SQL_REPOR` tem o `motivo_restricao = 'quality'`
 *   no predicado. É a regra que a `levantarRestricao` do KAM-023 escreveu pelo
 *   outro lado — um canal restrito por falta de pagamento não volta a `ativo`
 *   por a qualidade ter melhorado;
 * * **um valor que não se reconhece não faz nada ao estado.** É o critério 1:
 *   «registado como desconhecido sem falhar». Mudar o estado por um valor que
 *   não se compreende era pior do que não o mudar;
 * * **nunca `suspenso`.** Não há caminho nenhum nesta função que o produza, e é
 *   isso que o teste dos 50 eventos aleatórios afirma. O `suspenso` é de T&S
 *   (KAM-089/097).
 *
 * **A divergência que o DoD manda registar não existe, e isso mediu-se.** O
 * bloco do ticket diz, por extenso, que «`../docs/tecnica/10` §6.4 diz RED →
 * `suspenso`», e o DoD pede essa divergência «registada para correcção». O
 * documento diz o contrário: a linha do §6.4 é «`phone_number_quality_update`
 * vermelho → `restrito` (§15); T&S analisa», o §15.1 tem `ativo → restrito` com
 * decisor automático, e o controlo de versões dele registra a emenda que o
 * corrigiu — «1.1, Emenda KAM-111 […] §6.4 e §15.1, D-08 (estado `restrito`:
 * limitação imposta pela Meta, distinta de `suspenso`)». Quem ainda diz
 * `suspenso` é o `docs/tecnica/00` §6.2, e o `docs/tecnica/01` §9 já registra
 * essa divergência com a razão (a Meta deixou de reduzir o limite por
 * qualidade a 2025-10-07; o estado *Flagged* foi eliminado — CONFIRMADO). A
 * dívida que se abre é a do **bloco do ticket**, que cita um documento
 * desactualizado: `docs/dividas-documentais.md`, linha 74.
 */
export function accaoDaQualidade(
  qualidade: Qualidade | null,
  estado: string,
): Accao {
  if (qualidade === null) return "nada";
  if (qualidade === "red") {
    return estado === ESTADO_RESTRITO ? "nada" : "restringir";
  }
  // `green` e `yellow`: repõe-se, mas só se houver o que repor.
  return estado === ESTADO_RESTRITO ? "repor" : "nada";
}

/** O estado a que uma acção leva, ou `null` quando não mexe. */
export function estadoDepois(accao: Accao): string | null {
  if (accao === "restringir") return ESTADO_RESTRITO;
  if (accao === "repor") return ESTADO_ACTIVO;
  return null;
}

/**
 * `true` quando esta transição gera o aviso de `yellow` (critério 4).
 *
 * «1 alerta a T&S por transição (sem repetição em eventos idênticos)» — e o
 * «sem repetição» não é desta função: é da unicidade `(tenant_id, event_key)` da
 * revisão `0014`, que faz o evento repetido não produzir transição nenhuma.
 * Aqui decide-se só se **esta** transição é de aviso.
 *
 * Avisa quando a qualidade **passou a ser** `yellow` e não era antes. Um
 * `yellow` que já era `yellow` não é uma transição, e avisar nele dava um
 * alerta por cada *webhook* que a Meta reenviasse — que é o contrário de um
 * alerta, pela mesma razão que o KAM-023 escreveu para o `channel.updated`.
 */
export function avisaDeAmarelo(
  qualidade: Qualidade | null,
  anterior: string | null,
): boolean {
  return qualidade === "yellow" && anterior !== "yellow";
}

/**
 * O rácio de utilização do escalão (critério 7).
 *
 * «Utilizadores únicos contactados **por template** nas últimas 24 h ÷ limite
 * do escalão». O critério dá o exemplo: 200 contactos distintos com `TIER_250`
 * dá `0,8` e dispara alerta.
 *
 * **A resposta dentro da janela não consome**, e quem o garante é a consulta:
 * ela conta só os envios cuja categoria não é `service`. O limite da Meta é
 * sobre **iniciar** conversas fora da janela (CONFIRMADO, `E1` §5), e uma
 * resposta a quem escreveu não inicia nada.
 *
 * Um escalão que não se reconhece dá `racio: null` e `avisa: false` — «não sei»
 * e não «está folgado». É a mesma escolha que a `divergencia` do KAM-023 faz
 * para o denominador zero. E o `TIER_UNLIMITED` dá `0` por aritmética, porque o
 * tecto dele é `Infinity`: não há caso especial a escrever.
 */
export function utilizacaoDoEscalao(
  unicos: number,
  escalao: string | null,
): Utilizacao {
  const tecto = escalao === null ? undefined : TECTO_POR_ESCALAO[escalao];
  if (tecto === undefined) {
    return { unicos, escalao, racio: null, avisa: false };
  }
  const racio = Math.max(0, Math.trunc(unicos)) / tecto;
  return { unicos, escalao, racio, avisa: racio >= FRACCAO_DE_AVISO };
}

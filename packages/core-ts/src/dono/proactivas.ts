/**
 * A política de mensagens proactivas ao dono (KAM-118, critério 8).
 *
 * «Resposta ao dono dentro da janela de 24 h é *service message* sem
 * *template*; fora da janela só sai *template* se existir `consent_event` com
 * `purpose='marketing'` e opt-in do dono; sem opt-in 0 templates; «PARAR»
 * suprime em 1 mensagem; tecto de 1 *push* por semana e 4 por mês (*proposta*).»
 *
 * ## É uma decisão e não um envio
 *
 * Função pura do que se sabe no instante: a janela, o último consentimento de
 * marketing do dono e quantos *push* já saíram. Quem envia é o Outbound
 * (KAM-015), e é ele que impõe a janela e as categorias. **Não está ligada a
 * nenhum envio**, e a razão é de canon e não de pressa: o Outbound recusa a
 * categoria `marketing` no Piloto (`CATEGORIAS_DO_PILOTO`) e o
 * `docs/tecnica/01` §11.4 (regra 2) diz que a notificação ao dono nunca usa o
 * número da própria loja. As duas regras contradizem o *push* por *template*
 * que o critério pede, e quem as concilia é o fundador — está na secção de
 * verificação do bloco.
 *
 * ## «PARAR» suprime em uma mensagem, sem caminho próprio
 *
 * O `ConsentGate` do KAM-022 grava `purpose='marketing'` com `accepted=false`
 * na mensagem «PARAR» (`consentimento/consentimento.ts`), e o estado mais
 * recente da `consent_actual` é o que esta função lê. Por isso a primeira
 * proactiva depois do «PARAR» já sai suprimida: não há segunda contagem nem
 * segundo registo a manter coerente com o primeiro.
 *
 * ## Falha fechada
 *
 * Um opt-in desconhecido (`null`, sem `consent_event`) suprime, e um contador
 * negativo ou não inteiro também: um número que não se leu bem não autoriza
 * gastar um *template* de marketing.
 */

import { PUSH_POR_MES, PUSH_POR_SEMANA } from "./contrato.ts";

/** O que a política sabe no instante em que decide. */
export interface SituacaoDaProactiva {
  /** A janela de serviço de 24 h da conversa do dono está aberta. */
  readonly janelaAberta: boolean;
  /**
   * O `accepted` do consentimento `marketing` mais recente do dono, ou `null`
   * se não houver nenhum (`consent_actual`).
   */
  readonly optInMarketing: boolean | null;
  /** *Push* (templates) enviados ao dono nos últimos 7 dias. */
  readonly pushNaSemana: number;
  /** *Push* (templates) enviados ao dono nos últimos 30 dias. */
  readonly pushNoMes: number;
}

/** Porque é que uma proactiva não sai. Lista fechada: é etiqueta de métrica. */
export const MOTIVOS_DE_SUPRESSAO = [
  "sem_opt_in",
  "tecto_semanal",
  "tecto_mensal",
  "contagem_invalida",
] as const;
export type MotivoDeSupressao = (typeof MOTIVOS_DE_SUPRESSAO)[number];

/** A decisão: mensagem de serviço, *template*, ou nada. */
export type DecisaoDaProactiva =
  | { readonly accao: "service" }
  | { readonly accao: "template" }
  | { readonly accao: "suprimir"; readonly motivo: MotivoDeSupressao };

function contagemValida(n: number): boolean {
  return Number.isInteger(n) && n >= 0;
}

/** A decisão para uma mensagem ao dono que a plataforma quer mandar. */
export function decidirProactiva(situacao: SituacaoDaProactiva): DecisaoDaProactiva {
  // Dentro da janela é conversa, e não *push*: o dono escreveu nas últimas 24 h
  // e a resposta é uma *service message*, sem *template* e sem tecto. É o
  // desenho «o dono inicia» do `docs/tecnica/02` §21.2.
  if (situacao.janelaAberta === true) return { accao: "service" };

  if (situacao.optInMarketing !== true) return { accao: "suprimir", motivo: "sem_opt_in" };
  if (!contagemValida(situacao.pushNaSemana) || !contagemValida(situacao.pushNoMes)) {
    return { accao: "suprimir", motivo: "contagem_invalida" };
  }
  if (situacao.pushNoMes >= PUSH_POR_MES) return { accao: "suprimir", motivo: "tecto_mensal" };
  if (situacao.pushNaSemana >= PUSH_POR_SEMANA) {
    return { accao: "suprimir", motivo: "tecto_semanal" };
  }
  return { accao: "template" };
}

/**
 * A política de mensagens ao dono no Piloto (KAM-118, critério 8).
 *
 * «Política de proactivas no Piloto: a resposta ao dono dentro da janela de
 * 24 h é *service message* sem *template*; fora da janela não sai nenhuma
 * mensagem — nem *push* pelo número da loja nem *template* da categoria
 * `marketing` —, com ou sem opt-in.»
 *
 * ## Decisão do fundador, 2026-11-18: «Manter as regras»
 *
 * A letra anterior do critério pedia *push* por *template* fora da janela, com
 * opt-in de marketing e um tecto de 1 por semana e 4 por mês. Contradizia duas
 * regras escritas: o Outbound recusa a categoria `marketing` no Piloto
 * (`CATEGORIAS_DO_PILOTO`), e o `docs/tecnica/01` §11.4 (regra 2) diz que a
 * notificação ao dono nunca usa o número da própria loja. O fundador manteve as
 * regras e o critério reescreveu-se para o Piloto. **O dono inicia**
 * (`docs/tecnica/02` §21.2): fora da janela, a plataforma não lhe escreve por
 * este canal.
 *
 * ## É uma decisão e não um envio
 *
 * Função pura do que se sabe no instante. Quem envia é o Outbound (KAM-015),
 * que impõe a janela e as categorias por conta própria: esta função é a
 * primeira barreira, e não a única. Não está ligada a envio nenhum, porque
 * hoje nenhum caminho manda ao dono uma mensagem que ele não pediu.
 *
 * ## Falha fechada
 *
 * Só `janelaAberta === true` deixa sair. Um valor que não se leu bem —
 * `undefined`, a cadeia `"true"` — suprime: não se sabe se a janela está
 * aberta, e uma mensagem fora dela seria um *template* que a Meta cobra ou
 * recusa.
 */

/** O que a política sabe no instante em que decide. */
export interface SituacaoDaProactiva {
  /** A janela de serviço de 24 h da conversa do dono está aberta. */
  readonly janelaAberta: boolean;
}

/** Porque é que uma mensagem ao dono não sai. Lista fechada: é etiqueta de métrica. */
export const MOTIVOS_DE_SUPRESSAO = ["fora_da_janela"] as const;
export type MotivoDeSupressao = (typeof MOTIVOS_DE_SUPRESSAO)[number];

/** A decisão: mensagem de serviço, ou nada. No Piloto não há *template* ao dono. */
export type DecisaoDaProactiva =
  | { readonly accao: "service" }
  | { readonly accao: "suprimir"; readonly motivo: MotivoDeSupressao };

/** A decisão para uma mensagem ao dono que a plataforma quer mandar. */
export function decidirProactiva(situacao: SituacaoDaProactiva): DecisaoDaProactiva {
  // Dentro da janela é conversa, e não *push*: o dono escreveu nas últimas 24 h
  // e a resposta é uma *service message*, sem *template*.
  if (situacao.janelaAberta === true) return { accao: "service" };
  return { accao: "suprimir", motivo: "fora_da_janela" };
}

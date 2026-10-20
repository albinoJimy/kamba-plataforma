/**
 * A decisão de envio: a tabela do §8.2 em código (KAM-015, critérios 1 e 7).
 *
 * ## Duas perguntas, e a ordem entre elas é o critério 1
 *
 * 1. **A forma é válida?** Botões ≤ 3, listas ≤ 10 linhas, categoria permitida.
 *    Isto decide-se **antes de qualquer chamada HTTP**, e o critério 7 diz-o por
 *    extenso: «4 botões ou 11 linhas de lista falham antes de qualquer chamada».
 *    Verificar depois era gastar uma mensagem para descobrir o que se sabia
 *    antes — e, com o `130429` à porta, gastar débito também.
 * 2. **A janela está aberta?** Com janela aberta, mensagem livre (`service`).
 *    Com janela fechada e conteúdo livre, **`WINDOW_CLOSED` sem chamada
 *    nenhuma**; com janela fechada e template `approved`, o template.
 *
 * A ordem importa porque as duas recusas custam coisas diferentes: a de forma é
 * um defeito de quem chama e tem de aparecer sempre, mesmo com a janela aberta;
 * a de janela é uma informação de negócio, e quem a recebe decide template ou
 * desistir (§8.2, regra 3).
 *
 * ## A janela lê-se de `conversations`, e isso divergiu de um documento
 *
 * `conversations.window_expires_at` = `last_inbound_at` + 24 h, por (tenant,
 * contacto, canal). O `docs/tecnica/01` §6.2 punha as duas colunas em
 * `contacts`, e a emenda 1.20 registou a divergência com a razão: uma janela
 * **por contacto** não distingue dois canais do mesmo tenant, e a janela da
 * Meta é por par (número do negócio, número do cliente) (`E1` §4, CONFIRMADO).
 * Está na linha 50 de `docs/dividas-documentais.md`, e **não se reabre**.
 *
 * ## O que esta decisão não decide
 *
 * Não decide **quem tem a palavra** — isso é o `mode` da conversa e é KAM-018,
 * e o que o chama é o `PreSendGuard`. Não decide o **FEP** de 7 dias, que é de
 * Clusters (a emenda 1.21 corrigiu o §3.13, que o atribuía a este ticket). E
 * não conta o *free tier*: quem o mantém é o KAM-023.
 */

import {
  CATEGORIAS_DO_PILOTO,
  MAXIMO_DE_BOTOES,
  MAXIMO_DE_LINHAS,
  WINDOW_CLOSED,
  type Categoria,
  type Corpo,
  type MotivoDeRecusa,
  type Template,
} from "./contrato.ts";

/** O estado da janela de uma conversa, como o adapter o lê. */
export interface Janela {
  /** `null` quando a conversa nunca recebeu nada: a janela nunca abriu. */
  readonly expiraEm: Date | null;
}

/**
 * `true` quando a janela está aberta no instante dado.
 *
 * O limite é **estrito**: uma janela que expira exactamente agora está
 * fechada. É a leitura conservadora, e é a certa — a alternativa era enviar uma
 * mensagem livre no instante em que a Meta a passa a recusar, e descobri-lo por
 * um `131047` em vez de por um `WINDOW_CLOSED` nosso.
 */
export function janelaAberta(janela: Janela, agora: Date): boolean {
  return janela.expiraEm !== null && janela.expiraEm.getTime() > agora.getTime();
}

/** O que a decisão devolve. */
export type Decisao =
  | { readonly enviar: true; readonly kind: Categoria; readonly templateName: string | null }
  | { readonly enviar: false; readonly motivo: MotivoDeRecusa };

/**
 * A validação de forma, que corre **antes** de tudo.
 *
 * Devolve o motivo ou `null`. Não olha para a janela nem para o template: só
 * para o que quem chama escreveu.
 */
export function formaInvalida(corpo: Corpo): MotivoDeRecusa | null {
  if (corpo.tipo === "botoes" && corpo.botoes.length > MAXIMO_DE_BOTOES) {
    return "TOO_MANY_BUTTONS";
  }
  if (corpo.tipo === "lista" && corpo.linhas.length > MAXIMO_DE_LINHAS) {
    return "TOO_MANY_ROWS";
  }
  return null;
}

/** A categoria que um corpo implica. Um template herda a do próprio template. */
export function categoriaDe(corpo: Corpo, template: Template | null): Categoria {
  if (corpo.tipo !== "template") return "service";
  return template === null ? "utility" : template.category;
}

/**
 * A decisão inteira, pela ordem do §8.2.
 *
 * `template` é a linha de `message_templates` quando o corpo é um template, e
 * `null` quando não é — quem a lê é o adapter, que tem a ligação.
 */
export function decidir(
  corpo: Corpo,
  janela: Janela,
  agora: Date,
  template: Template | null,
): Decisao {
  // 1. A forma, antes de tudo (critério 7).
  const forma = formaInvalida(corpo);
  if (forma !== null) return { enviar: false, motivo: forma };

  // 2. Um corpo que **não** é template só sai com a janela aberta.
  if (corpo.tipo !== "template") {
    if (!janelaAberta(janela, agora)) {
      // **Sem chamada HTTP.** É a letra do critério 1, e é o que faz esta
      // recusa valer: quem a recebe decide template ou desistir, e não gastou
      // uma mensagem para o saber.
      return { enviar: false, motivo: WINDOW_CLOSED };
    }
    // Dentro da janela, livre e `service` — e **não** template. É a linha do
    // §8.2 que diz «Notificação com janela aberta: mensagem livre, não
    // template», e a razão é custo: a `utility` dentro da janela passou a ser
    // paga desde 2026-10-01 (`E1` §1).
    return { enviar: true, kind: "service", templateName: null };
  }

  // 3. Um template tem de existir, estar aprovado, não estar bloqueado e ser de
  //    uma categoria que o Piloto aceita.
  if (template === null) return { enviar: false, motivo: "TEMPLATE_NOT_APPROVED" };
  if (template.bloqueadoEm !== null) return { enviar: false, motivo: "TEMPLATE_BLOCKED" };
  if (template.status !== "approved") {
    return { enviar: false, motivo: "TEMPLATE_NOT_APPROVED" };
  }
  if (!CATEGORIAS_DO_PILOTO.includes(template.category)) {
    // O `marketing` é recusado no Piloto (critério 7), e a recusa é **aqui** e
    // não na base: a tabela tem de poder registar que a Meta recategorizou,
    // porque é esse registo que sustenta o alerta do critério 9.
    return { enviar: false, motivo: "MARKETING_NOT_ALLOWED" };
  }

  // Um template sai com a janela aberta ou fechada — é para isso que existe.
  return { enviar: true, kind: template.category, templateName: template.name };
}

/**
 * A autenticação dos *callbacks* do provedor (KAM-019, critério 5).
 *
 * «Os *callbacks* do Chatwoot (`message_created` de agente,
 * `conversation_status_changed`) só são aceites com o `secret` do bot; ausente
 * ou errado devolve 401 e incrementa uma métrica.»
 *
 * ## Porque é que isto é no HND e não no GWY
 *
 * O `docs/tecnica/08` §3.6 diz «webhooks de saída do Chatwoot assinados e
 * verificados **pelo GWY**» e o `docs/tecnica/02` §11, regra (3), diz
 * «autenticação da origem pelo `secret` do *agent bot* (**HND**)». São dois
 * documentos do mesmo nível, a ordem de fontes não desempata, e o ADR-001 não
 * resolve — ele fixa o GWY como único endpoint dos *webhooks* **da Meta**, e o
 * *callback* do provedor de atendimento está fora do seu âmbito.
 *
 * O que decidiu foi uma razão de desenho que o §3.6 não considerou: **o
 * `secret` é por bot, logo por *tenant***, e o GWY é o único ponto da
 * plataforma que não tem contexto de *tenant* antes de resolver o canal. Pôr a
 * verificação lá obrigava-o a adivinhar de quem é o segredo antes de saber de
 * quem é a conversa — o CHR ao contrário. A divergência está registada em
 * `docs/dividas-documentais.md` (57) e devolvida a quem escreveu o §3.6.
 *
 * ## A comparação é de tempo constante
 *
 * `===` sobre cadeias sai no primeiro carácter diferente, e isso mede-se: com
 * pedidos repetidos, o tempo de resposta diz quantos caracteres do segredo
 * estão certos. `timingSafeEqual` da biblioteca padrão não tem esse ramo. O
 * comprimento é o único facto que vaza, e é por isso que a diferença de
 * comprimento se trata **antes**, sem olhar ao conteúdo: um segredo de outro
 * tamanho não é «mais ou menos certo», é de outro bot.
 */

import { timingSafeEqual } from "node:crypto";

/** Porque é que um *callback* foi recusado. Lista fechada, é etiqueta. */
export const MOTIVOS_DE_RECUSA = [
  "sem_secret",
  "secret_errado",
  "tipo_desconhecido",
  "conta_desconhecida",
] as const;

export type MotivoDeRecusa = (typeof MOTIVOS_DE_RECUSA)[number];

/** O estado HTTP que o critério 5 fixa para um *callback* recusado. */
export const ESTADO_DE_RECUSA = 401;

/**
 * `true` quando o segredo recebido é o esperado.
 *
 * `null` ou vazio no recebido devolve `false` sem comparar nada: não há
 * «segredo em falta mais ou menos certo», e comparar um vazio com o esperado
 * em tempo constante gastava tempo a provar o óbvio.
 *
 * O esperado vazio devolve **`false`**, e isto é a parte que importa: uma
 * configuração sem segredo não pode tornar-se uma porta aberta. Se o cofre não
 * devolveu nada, nenhum *callback* passa — falha fechada, que é a mesma regra
 * do `PreSendGuard` do KAM-015.
 */
export function segredoConfere(recebido: string | null, esperado: string): boolean {
  if (esperado.length === 0) return false;
  if (recebido === null || recebido.length === 0) return false;
  const a = Buffer.from(recebido, "utf8");
  const b = Buffer.from(esperado, "utf8");
  // O comprimento vaza, e e o unico facto que vaza. Trata-se antes de
  // comparar, porque o `timingSafeEqual` **levanta** com tamanhos diferentes.
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** O veredicto de um *callback*: aceite, ou recusado com motivo. */
export type Veredicto =
  | { readonly aceite: true }
  | { readonly aceite: false; readonly motivo: MotivoDeRecusa; readonly estado: number };

/**
 * Decide se um *callback* entra.
 *
 * A ordem dos testes é a ordem do custo: o segredo em falta e o segredo errado
 * decidem-se sem tocar na base; a conta desconhecida precisa de uma leitura, e
 * por isso vem depois. Um pedido sem segredo nunca chega a fazer uma consulta,
 * que é o que impede um atacante de usar o *endpoint* como gerador de carga.
 */
export function avaliar(
  recebido: string | null,
  esperado: string,
  contaConhecida: boolean,
): Veredicto {
  if (recebido === null || recebido.length === 0) {
    return { aceite: false, motivo: "sem_secret", estado: ESTADO_DE_RECUSA };
  }
  if (!segredoConfere(recebido, esperado)) {
    return { aceite: false, motivo: "secret_errado", estado: ESTADO_DE_RECUSA };
  }
  if (!contaConhecida) {
    return { aceite: false, motivo: "conta_desconhecida", estado: ESTADO_DE_RECUSA };
  }
  return { aceite: true };
}

/**
 * O contacto de uma encomenda ao dono, mascarado (KAM-206; critério 6 do KAM-099).
 *
 * As três peças puras da leitura: **quando** o dono pode ver o contacto, **que**
 * telefone se mostra, e **como** sai. Nenhuma toca na base; a leitura, a decifra e
 * a linha de `audit_log` vivem com quem as liga.
 *
 * ## A regra: o dono é o responsável e o dado é necessário (*proposta*)
 *
 * Os estados em que o dono **age** sobre a encomenda, e em que falar com o
 * cliente é parte de agir:
 *
 * ```text
 * pendente_confirmacao   o dono confirma ou recusa o pedido
 * paga                   o dono prepara e combina a entrega
 * em_entrega             o dono entrega
 * entrega_falhada        o dono volta a combinar
 * ```
 *
 * Fora deles — antes do pagamento, depois da entrega, numa disputa, num
 * reembolso, numa cancelada ou expirada — o contacto **não** é necessário ao
 * dono, e a resposta é o mesmo `NOT_FOUND` de uma encomenda que não existe. Uma
 * disputa e um reembolso correm pela plataforma, e não pelo telefone do cliente.
 *
 * ## O telefone: o da encomenda, e por expirar
 *
 * A `contact_endpoints` guarda o telefone por **finalidade**, com `expira_at`
 * (KAM-008, retenção do doc 06). Servem `contacto_pedido` e `entrega`, que são as
 * finalidades de uma encomenda; o de `pagamento_express` foi dado para pagar, e
 * mostrá-lo ao dono era usá-lo para outra coisa. Um telefone expirado já não
 * devia existir — a purga é do KAM-071 —, e não se mostra.
 *
 * ## A máscara: os últimos três dígitos (*proposta*)
 *
 * Sai `••• ••• 789`, e **nada** do resto: nem o indicativo, nem o comprimento. O
 * dono reconhece o cliente que já lhe falou; quem lê o ecrã por cima do ombro, um
 * *log* ou uma captura não fica com um número que se marque.
 */

/** Os estados em que o dono vê o contacto. *Proposta* (KAM-206). */
export const ESTADOS_COM_CONTACTO = [
  "pendente_confirmacao",
  "paga",
  "em_entrega",
  "entrega_falhada",
] as const;

/** As finalidades de telefone que servem uma encomenda. */
export const FINALIDADES_DA_ENCOMENDA = ["contacto_pedido", "entrega"] as const;

/** Quantos dígitos do fim a máscara mostra. *Proposta* (KAM-206). */
export const DIGITOS_A_MOSTRAR = 3;

/** O dono pode ver o contacto de uma encomenda neste estado? */
export function contactoNecessario(estado: string): boolean {
  return (ESTADOS_COM_CONTACTO as readonly string[]).includes(estado);
}

/**
 * O telefone mascarado: os últimos três dígitos, e o resto como três pontos em
 * dois grupos fixos, para não dizer o comprimento. `null` se o telefone não tem
 * dígitos que cheguem — mostrar menos do que três era mostrar um número inteiro
 * de três dígitos, e não há telefone assim.
 */
export function mascarar(telefone: string): string | null {
  const digitos = telefone.replace(/\D/g, "");
  if (digitos.length <= DIGITOS_A_MOSTRAR) return null;
  return `••• ••• ${digitos.slice(-DIGITOS_A_MOSTRAR)}`;
}

/** Um telefone decifrado, como a identidade o devolve. */
export interface TelefoneDoContacto {
  readonly finalidade: string;
  readonly telefone: string;
  readonly expiraAt: Date;
}

/**
 * O telefone a mostrar: o de `contacto_pedido` primeiro, depois o de `entrega`,
 * e só os que ainda não expiraram. Dentro da mesma finalidade, o que expira mais
 * tarde (o mais recente). `null` se nenhum serve.
 */
export function telefoneDaEncomenda(
  telefones: readonly TelefoneDoContacto[],
  agora: Date,
): string | null {
  for (const finalidade of FINALIDADES_DA_ENCOMENDA) {
    const vivos = telefones
      .filter((t) => t.finalidade === finalidade && t.expiraAt.getTime() > agora.getTime())
      .sort((a, b) => b.expiraAt.getTime() - a.expiraAt.getTime());
    const escolhido = vivos[0];
    if (escolhido !== undefined) return escolhido.telefone;
  }
  return null;
}

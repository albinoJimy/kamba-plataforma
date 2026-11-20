/**
 * Quem fala: a persona de um remetente e o canal do dono (KAM-118, critérios 1
 * e 7).
 *
 * ## A persona é função do papel, e de mais nada
 *
 * O texto da mensagem, o nome de perfil, um «sou o dono» ou uma mensagem
 * reencaminhada não entram aqui: o CHR nem os lê. O papel vem da coluna
 * `contacts.papel` do contacto **já resolvido no tenant do canal**, e é por isso
 * que o dono do tenant A a escrever para a loja B é cliente em B — o mesmo
 * telefone dá outro `contact_id` noutro tenant (o HMAC leva o tenant, KAM-008).
 *
 * **Lista de permitidos, e não de proibidos.** Só o valor exacto `dono` dá a
 * persona `dono`; um `null`, um `"Dono"`, um `"admin"` ou qualquer valor que a
 * coluna venha a ganhar dão `cliente`. Um papel novo no domínio fecha a porta
 * por omissão, que é a regra do `do_humano` do AGR.
 */

import { timingSafeEqual } from "node:crypto";

import type { Telefone } from "../inscricao/identificadores.ts";
import type { Persona } from "./contrato.ts";

/** A persona de um remetente, pelo papel lido da base. */
export function personaDe(papel: unknown): Persona {
  return papel === "dono" ? "dono" : "cliente";
}

/**
 * O canal pelo qual o dono fala com o Assistente do Dono.
 *
 * `owner_channel_wa` é `false` quando o telemóvel verificado do dono **é** o
 * número da loja — o caso comum na coexistência, e o que o KAM-093 exige no
 * Embedded Signup —, porque ninguém conversa consigo próprio no WhatsApp. Nesse
 * caso o canal é o painel web. É também `false` enquanto a loja não tem número
 * ligado: sem número não há conversa dono → loja.
 */
export interface CanalDoDono {
  readonly owner_channel_wa: boolean;
  readonly canal: "whatsapp" | "painel";
}

const PAINEL: CanalDoDono = { owner_channel_wa: false, canal: "painel" };
const WHATSAPP: CanalDoDono = { owner_channel_wa: true, canal: "whatsapp" };

/** Um HMAC da inscrição: 32 octetos em hexadecimal minúsculo. */
const HMAC_EM_HEX = /^[0-9a-f]{64}$/;

/**
 * O canal do dono **actual**, comparando o telefone dele com o número da loja
 * (KAM-216; decisão do fundador de 2026-11-19).
 *
 * ## O número da loja não se guarda, e o HMAC dele é o do caso
 *
 * Decisão do fundador (opção C): guarda-se só o booleano, e não o número.
 * Calcula-se aqui, com o telefone do dono **em memória**. Em vez do número da
 * loja usa-se o `phone_hmac` do caso de onboarding. **Só vale depois de o guia o
 * confirmar**: o `confirmarNumero` do KAM-093 compara o `display_phone_number`
 * do Embedded Signup com o telefone do caso e marca o `numeroConfirmado`, ou
 * prende o guia em `numero_divergente` (`guia/guia.ts`, também na religação do
 * KAM-207). Quem chama tem de o verificar antes e mandar `null` sem ele — o
 * `onboarding-web` fá-lo pela porta `numeroDaLojaConfirmado`. Hoje nenhum
 * consumidor chama o `aplicarWebhook` em produção (credor KAM-087), e por isso a
 * troca guarda o painel até lá.
 *
 * **Um limite, e fica dito:** se o caso foi cunhado com uma chave que já saiu do
 * anel (duas rotações do *pepper* entre o registo e a troca), nenhum HMAC
 * coincide e o resultado é WhatsApp. Hoje não se alcança — os casos vivem em
 * memória e o anel é fixo durante a vida do processo —, e passa a alcançar-se
 * quando os casos forem persistidos (KAM-087).
 *
 * ## Compara-se com o telefone de agora, e não com o do caso
 *
 * Também é decisão do fundador. Comparar o telefone do caso com o número da loja
 * dava «painel» em todos os tenants, porque são o mesmo número por construção.
 * O que muda é o dono: depois de uma troca, o telefone dele pode já não ser o da
 * loja. Por isso quem chama é a troca, com o número novo que o OTP acabou de
 * provar.
 *
 * ## Sem `revelar()`, e aguenta uma rotação
 *
 * O `Telefone` traz os HMAC com **todas** as chaves do anel (`hmacs`), feitos na
 * cunhagem. Basta um deles coincidir com o do caso, e **uma** rotação do
 * *pepper* entre o registo e a troca não faz o mesmo número parecer outro. A comparação
 * é em tempo constante e percorre o anel inteiro, pela razão do
 * `hmacCorresponde`.
 *
 * **Um HMAC da loja ausente ou ilegível dá painel.** Falha fechada: na dúvida,
 * o dono tem o painel, que funciona sempre.
 */
export function canalDoDono(pedido: {
  readonly telefoneDoDono: Pick<Telefone, "hmacs">;
  readonly hmacDoNumeroDaLoja: unknown;
}): CanalDoDono {
  const loja = pedido.hmacDoNumeroDaLoja;
  if (typeof loja !== "string" || !HMAC_EM_HEX.test(loja)) return PAINEL;
  const esperado = Buffer.from(loja, "hex");
  let acertos = 0;
  for (const hmac of pedido.telefoneDoDono.hmacs) {
    if (!HMAC_EM_HEX.test(hmac)) continue;
    acertos |= timingSafeEqual(Buffer.from(hmac, "hex"), esperado) ? 1 : 0;
  }
  return acertos === 0 ? WHATSAPP : PAINEL;
}

/**
 * O canal que o painel mostra, a partir do que a troca guardou
 * (`tenants.owner_channel_wa`) e do estado do canal da loja.
 *
 * **Lista de permitidos**, como o `personaDe`: só o `true` exacto da coluna e o
 * canal `ativo` dão WhatsApp. Uma coluna a `NULL` (ninguém trocou de telefone, e
 * então o dono é o telefone do caso, que é o da loja), uma leitura que falhou
 * (`null`) ou uma loja sem canal ligado dão painel. Sem número ligado não há
 * conversa dono → loja, e com o canal a sincronizar ou desligado a mensagem do
 * dono não tem por onde chegar.
 */
export function canalNoPainel(guardado: unknown, estadoDoCanal: string): CanalDoDono {
  return guardado === true && estadoDoCanal === "ativo" ? WHATSAPP : PAINEL;
}

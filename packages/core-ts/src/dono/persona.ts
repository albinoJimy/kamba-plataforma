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

import { numeroCoincide } from "../guia/numero.ts";
import {
  IdentificadorInvalidoError,
  normalizarTelefone,
} from "../inscricao/identificadores.ts";
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

/**
 * O canal do dono, comparando o número da loja com o telefone do caso.
 *
 * A comparação é a do KAM-093 (`guia/numero.ts`): o `display_phone_number` que a
 * Meta devolve, normalizado, contra o `phone_hmac` do caso de onboarding, no
 * espaço de chave da inscrição. **Não** se compara com `contacts.phone_hmac`,
 * que está noutro espaço (leva o tenant e outra chave) e não é comparável.
 *
 * **Um número da loja ausente ou ilegível dá painel.** O `numeroCoincide`
 * devolve «não coincide» para um número que não se lê, e usá-lo sozinho deixava
 * o canal WhatsApp activo com um número que ninguém leu. Falha fechada: na
 * dúvida, o dono tem o painel, que funciona sempre.
 */
export function canalDoDono(pedido: {
  readonly numeroDaLoja: unknown;
  readonly telefoneHmacDoDono: string;
  readonly anelDoPepper: readonly (Uint8Array | null)[];
}): CanalDoDono {
  let legivel = true;
  try {
    normalizarTelefone(pedido.numeroDaLoja);
  } catch (erro) {
    if (!(erro instanceof IdentificadorInvalidoError)) throw erro;
    legivel = false;
  }
  const activo =
    legivel &&
    !numeroCoincide(pedido.numeroDaLoja, pedido.telefoneHmacDoDono, pedido.anelDoPepper);
  return { owner_channel_wa: activo, canal: activo ? "whatsapp" : "painel" };
}

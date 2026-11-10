/**
 * Dos webhooks da Meta aos sinais do guia (KAM-093, critérios 4, 6 e 7).
 *
 * Todo o `value` de um webhook do WhatsApp leva `metadata.display_phone_number`
 * e `metadata.phone_number_id` (`E1` §2, e o simulador do KAM-024 emite-os em
 * todos os campos). É daqui que sai o «número devolvido» do critério 4: o
 * primeiro webhook de um número novo — `history`, `smb_app_state_sync` ou
 * `account_update` — diz que número a Meta ligou, e o guia compara-o com o do
 * OTP. **Não se acrescenta uma leitura à Graph para isto**: o caminho
 * `GET /<phone_number_id>` não está CONFIRMADO no `E1`, e o simulador não o
 * serve — alargá-lo para este ticket era provar o cliente contra uma superfície
 * feita para lhe servir, que é o argumento que o KAM-016 já escreveu.
 *
 * ## Isto é uma função, e quem a liga é credor
 *
 * O `aplicarWebhook` recebe o corpo e chama o guia. **Quem o chama em produção
 * ainda não existe**: o estado do guia vive no `RepositorioDoGuia`, que só tem
 * duplo em memória no processo do `onboarding-web`, e um consumidor no GWY ou
 * no `worker-canal` não lhe chega. O dia em que o adaptador SQL existir
 * (KAM-087) é o dia em que um consumidor o pode ligar.
 */

import { EVENTO_PARTNER_REMOVED } from "../coexistencia/contrato.ts";
import type { PassoGuiado } from "./guia.ts";

/** Um sinal tirado de um `change` de um webhook. */
export interface Sinal {
  readonly campo: string;
  readonly phoneNumberId: string;
  readonly displayPhoneNumber: unknown;
  /** O `value.event` de um `account_update`, quando há. */
  readonly evento: string | null;
}

function objecto(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Os sinais de um corpo de webhook. O que não tem a forma, ignora-se. */
export function sinaisDoWebhook(corpo: unknown): readonly Sinal[] {
  const saida: Sinal[] = [];
  const entradas = objecto(corpo)?.entry;
  if (!Array.isArray(entradas)) return saida;
  for (const entrada of entradas) {
    const changes = objecto(entrada)?.changes;
    if (!Array.isArray(changes)) continue;
    for (const change of changes) {
      const c = objecto(change);
      const valor = objecto(c?.value);
      const metadata = objecto(valor?.metadata);
      const pnid = metadata?.phone_number_id;
      if (typeof c?.field !== "string" || typeof pnid !== "string" || pnid === "") continue;
      saida.push({
        campo: c.field,
        phoneNumberId: pnid,
        displayPhoneNumber: metadata?.display_phone_number,
        evento: typeof valor?.event === "string" ? valor.event : null,
      });
    }
  }
  return saida;
}

/** O que um corpo fez ao guia. Para os ensaios e para o log. */
export interface Aplicacao {
  readonly divergentes: number;
  readonly desligados: number;
}

/**
 * Aplica um corpo de webhook ao guia.
 *
 * **O número confere-se antes de qualquer outro efeito**, em cada sinal: um
 * `history` de um número alheio não pode pôr o guia em `a_sincronizar` antes de
 * o prender. A ordem é a barreira.
 */
export async function aplicarWebhook(guia: PassoGuiado, corpo: unknown): Promise<Aplicacao> {
  let divergentes = 0;
  let desligados = 0;
  for (const s of sinaisDoWebhook(corpo)) {
    const coincide = await guia.confirmarNumero(s.phoneNumberId, s.displayPhoneNumber);
    if (coincide === null) continue;
    if (!coincide) {
      divergentes += 1;
      continue;
    }
    if (s.campo === "account_update" && s.evento === EVENTO_PARTNER_REMOVED) {
      if (await guia.desligado(s.phoneNumberId)) desligados += 1;
    } else if (s.campo === "history" || s.campo === "smb_app_state_sync") {
      await guia.sincronizacao(s.phoneNumberId, "a_sincronizar");
    }
  }
  return { divergentes, desligados };
}

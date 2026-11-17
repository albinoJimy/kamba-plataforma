/**
 * A mudança de telefone do dono (KAM-118, critério 4).
 *
 * «Mudança de telefone do dono: novo OTP obrigatório; até validar, o número
 * novo é `cliente` e o antigo mantém o papel; após a troca, acções sensíveis
 * ficam bloqueadas 24 h (*proposta*) e é emitido aviso ao número antigo e ao
 * e-mail (ganchos para KAM-115).»
 *
 * ## Quem tem o papel, em cada instante
 *
 *     pedir        OTP enviado ao número novo; nada muda na base
 *     verificar    o OTP falha → nada muda; o número novo continua `cliente`
 *                  o OTP acerta → `platform.trocar_dono` move o papel numa
 *                  transacção só, marca `papel_mudou_at` e avisa
 *
 * **O papel só se move depois do OTP, e só por esta porta.** Até lá, uma
 * mensagem do número novo chega ao CHR como a de qualquer desconhecido: o
 * contacto resolve-se com `papel='cliente'` e a persona é a da vertical. É a
 * troca de SIM simulada do ensaio adversarial.
 *
 * ## O bloqueio de 24 h não vive aqui
 *
 * Vive na base (`contacts.papel_mudou_at`) e é lido por quem confirma uma acção
 * sensível (`kamba_agr/dono/accoes.py`): um bloqueio guardado na memória deste
 * processo desaparecia num reinício, e um reinício é exactamente o que um
 * atacante com tempo consegue esperar.
 *
 * ## Os avisos são ganchos
 *
 * O aviso ao número antigo e ao e-mail é do KAM-115 (canal alternativo, SMS e
 * e-mail com fornecedores por escolher). Esta porta chama `avisarTroca` duas
 * vezes, uma por destino, e **um aviso que falha não desfaz a troca**: o papel
 * já mudou na base, e desfazê-lo por o e-mail estar em baixo deixava o dono
 * legítimo sem canal. A falha sobe a quem chama, depois da troca.
 */

import type { Telefone } from "../inscricao/identificadores.ts";
import type { ResultadoDeEnvio, Veredicto } from "../inscricao/otp.ts";

/** O OTP do KAM-086, pela forma que a troca usa. O `Otp` de `inscricao/` serve. */
export interface OtpDaTroca {
  enviar(chave: string, telefone: Telefone): Promise<ResultadoDeEnvio>;
  verificar(chave: string, codigo: string): Promise<Veredicto>;
}

/** O contacto do número novo, no tenant do dono. É o `resolveContact` do KAM-008. */
export interface ContactoDoNumero {
  (pedido: { readonly tenantId: string; readonly telefone: Telefone }): Promise<{
    readonly contactId: string;
  }>;
}

/**
 * A troca na base: `platform.trocar_dono(tenant, contacto)`.
 *
 * Devolve o contacto que deixou de ser dono, ou `null` se não havia nenhum.
 */
export interface TrocaNaBase {
  (pedido: { readonly tenantId: string; readonly contactId: string }): Promise<{
    readonly anterior: string | null;
  }>;
}

/** Para onde vai o aviso de que o telefone do dono mudou. */
export const DESTINOS_DO_AVISO = ["numero_antigo", "email"] as const;
export type DestinoDoAviso = (typeof DESTINOS_DO_AVISO)[number];

/** O gancho do KAM-115. Recebe o tenant e o destino, **nunca** o número. */
export interface AvisoDaTroca {
  (pedido: { readonly tenantId: string; readonly destino: DestinoDoAviso }): Promise<void>;
}

/** O desfecho de uma verificação. */
export type DesfechoDaTroca =
  | { readonly trocado: true; readonly contactId: string; readonly anterior: string | null }
  | { readonly trocado: false; readonly veredicto: Exclude<Veredicto, "acertou"> | "sem_pedido" };

/** Um pedido de troca em curso: o tenant e o número novo, à espera do OTP. */
interface Pedido {
  readonly tenantId: string;
  readonly telefone: Telefone;
}

/**
 * A troca de telefone do dono. Uma instância por processo.
 *
 * Os pedidos em curso vivem em memória, e é deliberado: um pedido perdido num
 * reinício obriga o dono a pedir outro OTP, que é o lado seguro. O que **não**
 * pode viver em memória — o papel e o instante da troca — vive na base.
 */
export class TrocaDeTelefone {
  readonly #otp: OtpDaTroca;
  readonly #contacto: ContactoDoNumero;
  readonly #trocar: TrocaNaBase;
  readonly #avisar: AvisoDaTroca;
  readonly #pedidos = new Map<string, Pedido>();

  constructor(portas: {
    readonly otp: OtpDaTroca;
    readonly contacto: ContactoDoNumero;
    readonly trocar: TrocaNaBase;
    readonly avisar: AvisoDaTroca;
  }) {
    this.#otp = portas.otp;
    this.#contacto = portas.contacto;
    this.#trocar = portas.trocar;
    this.#avisar = portas.avisar;
  }

  /**
   * Pede a troca: envia o OTP ao número novo. A chave do desafio é o `pedidoId`.
   *
   * **O `tenantId` vem da sessão do painel**, que o tem assinado; nunca de um
   * parâmetro do pedido (critério 9).
   */
  async pedir(pedidoId: string, tenantId: string, telefone: Telefone): Promise<ResultadoDeEnvio> {
    const envio = await this.#otp.enviar(pedidoId, telefone);
    if (envio.enviado) this.#pedidos.set(pedidoId, { tenantId, telefone });
    return envio;
  }

  /**
   * Verifica o código. Só um `acertou` move o papel.
   *
   * O pedido é **consumido** quando o OTP acerta ou se esgota; um `errou`
   * deixa-o vivo para nova tentativa, que é o comportamento do OTP.
   */
  async verificar(pedidoId: string, tenantId: string, codigo: string): Promise<DesfechoDaTroca> {
    const pedido = this.#pedidos.get(pedidoId);
    // Um pedido de outro tenant é tratado como inexistente: dizer «existe mas
    // não é teu» era um oráculo sobre os pedidos de outros donos.
    if (pedido === undefined || pedido.tenantId !== tenantId) {
      return { trocado: false, veredicto: "sem_pedido" };
    }
    const veredicto = await this.#otp.verificar(pedidoId, codigo);
    if (veredicto !== "acertou") {
      if (veredicto !== "errou") this.#pedidos.delete(pedidoId);
      return { trocado: false, veredicto };
    }
    this.#pedidos.delete(pedidoId);

    const { contactId } = await this.#contacto({ tenantId, telefone: pedido.telefone });
    const { anterior } = await this.#trocar({ tenantId, contactId });
    for (const destino of DESTINOS_DO_AVISO) {
      await this.#avisar({ tenantId, destino });
    }
    return { trocado: true, contactId, anterior };
  }
}

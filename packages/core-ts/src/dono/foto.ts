/**
 * A foto do dono pelo painel (KAM-243): o mesmo caminho da do WhatsApp.
 *
 * ```text
 * painel  --bytes da foto (JPEG ou PNG, com o tecto do MED)-->  esta porta
 *         --o MED do KAM-020, com os bytes do pedido-->  STO + media_assets (armazenado)
 *         --agent_invocation com asset_id, type image, persona dono-->  AGR /internal/turn
 * AGR     o nó do catálogo passa o asset_id ao create_product_draft (KAM-231)
 * ```
 *
 * **Passa pelo MED, e não por um `INSERT` próprio**, e é de propósito: a linha
 * da `platform.media_assets` tem a reserva em `pendente`, a *allowlist* no tipo
 * real, o `put` com a chave do tenant e a marcação `armazenado` com o resumo do
 * que ficou no STO, e escrever outra vez essa ordem aqui era ter duas. O que
 * muda é só a origem dos bytes: em vez da Meta, um `ClienteDeMidia` que devolve
 * os bytes do pedido (`midiaDoPedido`).
 *
 * ## A mesma foto duas vezes é **um** rascunho
 *
 * O `media_id` da linha é próprio do painel — `painel.{uuid}` — e o uuid é
 * **determinístico**: os primeiros 16 bytes do SHA-256 de
 * «media_assets:painel:{tenant_id}:{sha256 dos bytes}», com a versão 8, como o
 * `messageIdDe` do KAM-232. A mesma foto (os mesmos octetos) no mesmo tenant dá o
 * mesmo `media_id`: a reserva do MED perde o conflito e devolve a linha que já
 * está, e a idempotência do KAM-049 (`catalog_ingestions_media_uq`, pelo
 * `media_id`) dá **uma** ingestão. O tenant entra no resumo para o identificador
 * de uma foto não dizer nada sobre a mesma foto noutro tenant. Uma foto
 * recomprimida é outra foto, e dá outro rascunho.
 *
 * O `wamid` da invocação é `painel.{asset_id}`, e é o `turn_id` do AGR: o mesmo
 * envio repetido é o mesmo turno, e as respostas dele (`turn_id:seq`) não saem
 * duas vezes. A admissão do AGR exige exactamente esta forma com a credencial do
 * painel (`invocacao_do_painel_admitida`).
 *
 * ## O tenant é o da sessão
 *
 * Esta porta recebe o `tenantId` de quem chama, que é a rota do painel, que o
 * tira do *cookie* assinado. O contacto, a conversa e o canal lêem-se dentro
 * desse tenant (`contextoNaBase`); o MED corre cada instrução com o
 * `app.tenant_id` dele, e o STO recusa uma chave fora do prefixo do tenant.
 */

import { createHash } from "node:crypto";

import type { AgentInvocation } from "../chr/contrato.ts";
import { threadIdDe } from "../chr/contrato.ts";
import type { DesfechoDoAgr } from "../agr/contrato.ts";
import type { Logger } from "../logger/index.ts";
import {
  LIMITES_POR_OMISSAO,
  Med,
  MetricasDoMed,
  type ClienteDeMidia,
  type ClienteSql as ClienteSqlDoMed,
  type LimiteDaClasse,
  type PedidoDeMidia,
  type ResultadoDeMidia,
} from "../med/index.ts";
import type { Classe } from "../med/contrato.ts";
import type { StorageProvider } from "../storage/index.ts";
import { comTenant, type ClienteSql } from "../tenant_guard/index.ts";
import { PREFIXO_DO_TURNO_DO_PAINEL, type ContextoDoDono, type DesfechoDaEntrega, type SemContexto } from "./conversa.ts";
import { numaLigacao, type PoolDeIdentidade } from "./sql.ts";

/** Os tipos que o painel aceita: os que o descodificador do AGR lê (KAM-231). */
export const TIPOS_DA_FOTO_DO_PAINEL = ["image/jpeg", "image/png"] as const;
export type TipoDaFoto = (typeof TIPOS_DA_FOTO_DO_PAINEL)[number];

/**
 * O tecto de uma foto, em octetos: **o do MED** para a classe `media_imagem`
 * (5 MiB, *proposta* do KAM-020). Lê-se de lá, para mudar o limite ser um sítio.
 */
export const BYTES_MAXIMOS_DA_FOTO = LIMITES_POR_OMISSAO.media_imagem.bytesMaximos;

/**
 * Os limites do MED quando a foto vem do painel: a classe `media_imagem` só com
 * JPEG e PNG. O WebP do MED existe pelos *stickers* do WhatsApp, e o
 * descodificador do AGR não o lê: aceitá-lo aqui era gravar uma foto que nunca
 * vira rascunho.
 */
export const LIMITES_DO_PAINEL: Readonly<Record<Classe, LimiteDaClasse>> = {
  ...LIMITES_POR_OMISSAO,
  media_imagem: { tipos: [...TIPOS_DA_FOTO_DO_PAINEL], bytesMaximos: BYTES_MAXIMOS_DA_FOTO },
};

/** O `wa_type` com que a foto do painel entra no MED e na invocação. */
export const TIPO_DA_FOTO_NA_INVOCACAO = "image";

/** O domínio do resumo do `media_id` de uma foto do painel. */
export const DOMINIO_DO_MEDIA_ID_DO_PAINEL = "media_assets:painel";

/**
 * O tipo **real** de uns bytes, pela assinatura, ou `null`.
 *
 * O `Content-Type` do pedido não decide: é o que quem envia diz, e a *allowlist*
 * do MED corre no tipo real (critério 4 do KAM-020). JPEG começa por `FF D8 FF`
 * e PNG pelos oito octetos da assinatura do formato.
 */
export function tipoDaFoto(bytes: Uint8Array): TipoDaFoto | null {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (bytes.length >= png.length && png.every((octeto, i) => bytes[i] === octeto)) return "image/png";
  return null;
}

/** O `media_id` de uma foto do painel: `painel.{uuid}`, determinístico. Ver a nota do módulo. */
export function mediaIdDoPainel(tenantId: string, bytes: Uint8Array): string {
  const resumo = createHash("sha256").update(bytes).digest("hex");
  const id = createHash("sha256")
    .update(`${DOMINIO_DO_MEDIA_ID_DO_PAINEL}:${tenantId}:${resumo}`, "utf8")
    .digest()
    .subarray(0, 16);
  id[6] = (id[6]! & 0x0f) | 0x80;
  id[8] = (id[8]! & 0x3f) | 0x80;
  const hex = id.toString("hex");
  return `${PREFIXO_DO_TURNO_DO_PAINEL}${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * A invocação de uma foto do painel: `type` `image`, persona `dono`, o
 * `asset_id`, **sem `message_id`** e com o `wamid` `painel.{asset_id}`. Os bytes,
 * a chave do STO e o `media_id` não entram.
 */
export function invocacaoDaFoto(tenantId: string, contexto: ContextoDoDono, assetId: string): AgentInvocation {
  return {
    tenant_id: tenantId,
    contact_id: contexto.contactId,
    conversation_id: contexto.conversationId,
    channel_id: contexto.channelId,
    wamid: `${PREFIXO_DO_TURNO_DO_PAINEL}${assetId}`,
    type: TIPO_DA_FOTO_NA_INVOCACAO,
    modo: contexto.modo,
    thread_id: threadIdDe(tenantId, contexto.contactId),
    vertical: contexto.vertical,
    persona: "dono",
    asset_id: assetId,
  };
}

/** Os bytes de uma foto do painel, com o tipo que a assinatura deu. */
export interface FotoDoPedido {
  readonly bytes: Uint8Array;
  readonly tipo: TipoDaFoto;
}

/** O que a porta precisa. */
export interface PortasDaFoto {
  /** O dono, o canal e a conversa dele (`contextoNaBase`, a mesma da conversa). */
  contexto(tenantId: string): Promise<ContextoDoDono | SemContexto>;
  /** O MED com os bytes do pedido (`recepcaoDoPainel`). */
  receber(pedido: PedidoDeMidia, foto: FotoDoPedido): Promise<ResultadoDeMidia>;
  /** Entrega a invocação ao AGR (`invocadorPorHttp`, com o `agr_painel_token`). */
  invocar(invocacao: AgentInvocation): Promise<DesfechoDaEntrega>;
}

/** Porque é que a foto não seguiu. */
export type MotivoDaFoto = "tipo" | "tamanho" | SemContexto | "a_tratar" | "falhou" | "agr";

/** O resultado de um envio. */
export type ResultadoDaFoto =
  | {
      readonly enviada: true;
      readonly assetId: string;
      /** A mesma foto já estava guardada neste tenant. */
      readonly repetida: boolean;
      readonly desfecho: DesfechoDoAgr | "desconhecido";
    }
  | { readonly enviada: false; readonly motivo: MotivoDaFoto; readonly assetId?: string };

/** A foto do dono pelo painel. Uma instância por processo. */
export class FotoDoDono {
  readonly #portas: PortasDaFoto;

  constructor(portas: PortasDaFoto) {
    this.#portas = portas;
  }

  /**
   * Guarda a foto e corre o turno. A resposta não vem aqui: chega pelo evento,
   * pelo canal `painel`, e lê-se na conversa.
   *
   * **O tipo e o tamanho recusam-se antes de tudo**, e o MED volta a conferi-los:
   * uma foto que não passa não reserva linha nenhuma. **A linha grava-se antes de
   * se invocar**: se o AGR falhar, a foto fica guardada e o dono pode repetir — e
   * repetir é a mesma foto, a mesma linha e o mesmo turno.
   */
  async enviar(tenantId: string, bytes: Uint8Array): Promise<ResultadoDaFoto> {
    const tipo = tipoDaFoto(bytes);
    if (tipo === null) return { enviada: false, motivo: "tipo" };
    if (bytes.byteLength > BYTES_MAXIMOS_DA_FOTO) return { enviada: false, motivo: "tamanho" };
    const contexto = await this.#portas.contexto(tenantId);
    if (typeof contexto === "string") return { enviada: false, motivo: contexto };
    const mediaId = mediaIdDoPainel(tenantId, bytes);
    const guardada = await this.#portas.receber(
      {
        tenantId,
        contactId: contexto.contactId,
        conversationId: contexto.conversationId,
        wamid: mediaId,
        mediaId,
        waType: TIPO_DA_FOTO_NA_INVOCACAO,
      },
      { bytes, tipo },
    );
    if (guardada.estado === "rejeitado") {
      return {
        enviada: false,
        motivo: guardada.motivo === "tamanho_excedido" ? "tamanho" : "tipo",
        assetId: guardada.assetId,
      };
    }
    if (guardada.estado === "pendente") return { enviada: false, motivo: "a_tratar", assetId: guardada.assetId };
    if (guardada.estado === "falhou") return { enviada: false, motivo: "falhou", assetId: guardada.assetId };
    const entrega = await this.#portas.invocar(invocacaoDaFoto(tenantId, contexto, guardada.assetId));
    if (entrega.estado < 200 || entrega.estado >= 300) {
      return { enviada: false, motivo: "agr", assetId: guardada.assetId };
    }
    return { enviada: true, assetId: guardada.assetId, repetida: guardada.repetido, desfecho: entrega.desfecho };
  }
}

/**
 * O `ClienteDeMidia` de uma foto do painel: devolve os bytes do pedido, com o
 * tipo que a assinatura deu. Não há URL de fora; a referência que o MED recebe
 * do `resolver` é uma constante e não sai deste módulo.
 */
export function midiaDoPedido(foto: FotoDoPedido): ClienteDeMidia {
  return {
    resolver: async () => ({ url: "painel:pedido", contentType: foto.tipo, tamanho: foto.bytes.byteLength }),
    descarregar: async () => ({ bytes: foto.bytes, contentType: foto.tipo }),
  };
}

/**
 * A base do MED numa ligação, com o contexto do tenant em **cada** instrução —
 * a forma do `sqlDoTenant` do `worker-canal-entrada` (KAM-231), e pela razão
 * dele: a reserva em `pendente` tem de ficar confirmada antes do `put`, e uma
 * transacção à volta do `receber` deixava-a por confirmar durante a escrita no STO.
 */
export function sqlNoTenant(ligacao: ClienteSql, tenantId: string): ClienteSqlDoMed {
  return {
    query: async <T,>(texto: string, valores?: readonly unknown[]) => {
      const resultado = (await comTenant(ligacao, tenantId, (tx) =>
        tx.query(texto, valores === undefined ? [] : [...valores]),
      )) as { readonly rows?: readonly T[] };
      return { rows: resultado.rows ?? [] };
    },
  };
}

/** O que a recepção do painel precisa. */
export interface OpcoesDaRecepcaoDoPainel {
  /** O *pool* `kamba_app` da conversa (`ONBOARDING_APP_DB_URL`). */
  readonly pool: PoolDeIdentidade;
  readonly armazenamento: StorageProvider;
  readonly metricas?: MetricasDoMed;
  readonly log?: Logger;
}

/**
 * A porta `receber` sobre o MED: **um `Med` por pedido**, porque o cliente de
 * mídia são os bytes do pedido, e uma ligação do *pool* por pedido, com o tenant
 * em cada instrução. As métricas são partilhadas.
 */
export function recepcaoDoPainel(o: OpcoesDaRecepcaoDoPainel): PortasDaFoto["receber"] {
  const metricas = o.metricas ?? new MetricasDoMed();
  return (pedido, foto) =>
    numaLigacao(o.pool, (ligacao) =>
      new Med({
        bd: sqlNoTenant(ligacao, pedido.tenantId),
        armazenamento: o.armazenamento,
        midia: midiaDoPedido(foto),
        // Sem aviso ao AGR: um `falhou` volta a quem chamou, que é o painel, e o
        // dono vê-o na resposta do pedido. Avisar era um segundo turno.
        avisarAgr: async () => {},
        limites: LIMITES_DO_PAINEL,
        metricas,
        ...(o.log === undefined ? {} : { log: o.log }),
      }).receber(pedido),
    );
}

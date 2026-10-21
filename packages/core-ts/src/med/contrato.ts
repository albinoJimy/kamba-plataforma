/**
 * Os tipos e as portas do MED (KAM-020).
 *
 * O MED recebe mídia: um `media_id` que o webhook trouxe, e um objecto que tem
 * de ir para o `StorageProvider` (ADR-014) sem que o URL da Meta fique em sítio
 * nenhum. Serve o STT (KAM-036), o Catálogo AI (KAM-049), o KYC (KAM-087) e o
 * espelho para o Chatwoot (KAM-019).
 *
 * ## O que este módulo não pode fazer, e é por construção
 *
 * **Uma imagem pode ser um comprovativo de pagamento e nunca é prova**
 * (ADR-013). O critério 8 pede um teste de arquitectura que o afirme — «0
 * caminhos de código que alterem estado de pagamento a partir de uma imagem» —
 * e a forma de o cumprir não é disciplina: é não haver importação. Este
 * ficheiro **não importa nada de `pay/` nem de `com/`**, e o `lint_arch` é
 * quem o guarda.
 *
 * ## Três portas, e a razão de serem três
 *
 * O MED fala com três coisas que podem falhar de maneiras diferentes, e juntá-las
 * numa só porta tornava impossível montar um ensaio que falhe só numa:
 *
 * 1. **A Meta** (`ClienteDeMidia`), que resolve o `media_id` num URL temporário
 *    e serve os bytes. É a que pode estar em baixo, e é a única que precisa de
 *    *retry*.
 * 2. **O armazenamento** (`StorageProvider` do KAM-011), que já existe nas duas
 *    linguagens com duplo e bateria de contrato. **Não se reinventa, e recebe-se
 *    por injecção**: o `index.ts` dele não exporta os motores, porque «quem os
 *    usa directamente saltou o isolamento».
 * 3. **A base** (`ClienteSql`), onde a linha vive.
 *
 * ## O que está *proposta*, e fica dito
 *
 * **A API de mídia da Meta não tem evidência nenhuma.** O `E1` não tem a página
 * e não a lista como omissão: não há tamanho máximo por tipo, nem tempo de
 * expiração do URL, nem o fluxo de duas etapas confirmado, nem os códigos de
 * erro. Tudo o que este módulo assume sobre ela é **proposta**, e o sítio onde
 * calibra está dito em cada constante.
 */

import type { Ctx, ObjectKey, ObjectRef, StorageProvider } from "../storage/index.ts";

/** As três classes de objecto de mídia, do dicionário §3.16. */
export const CLASSES = ["media_audio", "media_imagem", "media_documento"] as const;
export type Classe = (typeof CLASSES)[number];

/** Os quatro estados de um objecto, do dicionário §3.16. */
export const ESTADOS = ["pendente", "armazenado", "rejeitado", "falhou"] as const;
export type EstadoDeMidia = (typeof ESTADOS)[number];

/**
 * Os motivos de uma rejeição, e são lista **fechada** porque são etiqueta.
 *
 * A `media_rejected_total{motivo}` leva-os, e uma etiqueta de cardinalidade
 * aberta é o que o `OBS-I` do `docs/seguranca/ameacas_stride.md` proíbe. É a
 * mesma razão dos quatro motivos de recusa do HND.
 */
export const MOTIVOS_DE_REJEICAO = [
  "tipo_nao_permitido",
  "tamanho_excedido",
  "classe_desconhecida",
] as const;
export type MotivoDeRejeicao = (typeof MOTIVOS_DE_REJEICAO)[number];

/**
 * O que o *worker* de canal passa ao MED.
 *
 * **Leva o `waType` e não a classe**, de propósito: a tradução de vocabulário é
 * deste módulo e não de quem chama. O `WA_TYPES` do `entrada/contrato.ts` tem
 * dez valores e só quatro são de mídia; quem chama não tem de saber quais.
 */
export interface PedidoDeMidia {
  readonly tenantId: string;
  readonly contactId: string;
  readonly conversationId: string;
  /** O identificador da mensagem no WhatsApp. */
  readonly wamid: string;
  /** O identificador do objecto do lado da Meta. **Não é um URL.** */
  readonly mediaId: string;
  /** O tipo da mensagem, como o webhook o traz (`audio`, `image`, …). */
  readonly waType: string;
  /**
   * O que o webhook **anuncia** como tipo de conteúdo, se o trouxer.
   *
   * Opcional e **não é de confiança**: o que vale é o que a resposta da
   * descarga devolve. Serve só para recusar cedo o que já se sabe que não
   * passa, e poupar uma descarga.
   */
  readonly contentTypeAnunciado?: string;
}

/** O que o MED devolve, e é o que o chamador precisa de saber. */
export type ResultadoDeMidia =
  | {
      readonly estado: "armazenado";
      readonly assetId: string;
      /** A referência interna, `media://{assetId}`. Nunca a chave nem o URL. */
      readonly referencia: string;
      readonly repetido: boolean;
    }
  | {
      readonly estado: "rejeitado";
      readonly assetId: string;
      readonly motivo: MotivoDeRejeicao;
      /** O que se diz ao cliente, e é determinístico (critério 4). */
      readonly resposta: string;
    }
  | {
      readonly estado: "falhou";
      readonly assetId: string;
      /** Quantas tentativas se fizeram antes de desistir. */
      readonly tentativas: number;
    };

/** O que a Meta devolve ao resolver um `media_id`. */
export interface MidiaResolvida {
  /**
   * O URL temporário.
   *
   * **Nunca é persistido** — nem na base, nem em registo, nem em evento
   * (critério 3, e o `docs/tecnica/08` §3.8: «nunca URL da Meta persistida
   * (expiram)»). Vive nesta variável e morre com a chamada.
   */
  readonly url: string;
  /** O tipo que a Meta declara. Também não é o que vale: ver o `descarregar`. */
  readonly contentType: string;
  /** O tamanho que ela declara, se o declarar. */
  readonly tamanho?: number;
}

/** Os bytes, e o tipo que a **resposta** traz. */
export interface MidiaDescarregada {
  readonly bytes: Uint8Array;
  /**
   * O `content-type` da resposta da descarga.
   *
   * **É este que vale**, e não o que o webhook ou o `resolver` anunciam: a
   * *allowlist* do critério 4 corre contra ele. Confiar no anúncio era aceitar
   * que ele mente, e um `image/png` anunciado que chega como executável é
   * exactamente o caso que a *allowlist* existe para apanhar.
   */
  readonly contentType: string;
}

/**
 * A porta da Meta.
 *
 * Duas operações e não uma, porque o fluxo é de duas etapas (`docs/tecnica/01`
 * §5.4: «`media_id` → GET autenticado → StorageProvider») e porque só a segunda
 * move bytes: separá-las permite medir a latência da descarga sem a resolução,
 * que é o que a `media_download_ms` mede.
 */
export interface ClienteDeMidia {
  /** Resolve o `media_id` num URL temporário. */
  resolver(tenantId: string, mediaId: string): Promise<MidiaResolvida>;
  /** Descarrega os bytes de um URL temporário. */
  descarregar(tenantId: string, resolvida: MidiaResolvida): Promise<MidiaDescarregada>;
}

/**
 * O sinal ao AGR quando a descarga falha de vez (critério 6).
 *
 * Porta e não chamada directa: o que se faz com o sinal é do AGR (KAM-025), e
 * o MED não o importa. O que ele promete é que **alguém é avisado** — um
 * `falhou` silencioso deixava o cliente à espera de uma resposta a um áudio que
 * nunca foi ouvido.
 */
export type AvisarAgr = (aviso: {
  readonly tenantId: string;
  readonly conversationId: string;
  readonly wamid: string;
  readonly classe: Classe;
}) => Promise<void>;

/**
 * O gancho de transcrição (critério 7).
 *
 * O MED **agenda** a eliminação do blob; a purga em si é KAM-071. Fica aqui
 * porque dois tickets o citam pelo nome e nenhum o define.
 */
export type OnTranscribed = (asset: {
  readonly assetId: string;
  readonly tenantId: string;
  readonly storageRef: ObjectKey;
}) => Promise<void>;

/** A base, pela mesma forma que os outros módulos usam. */
export interface ClienteSql {
  query<T>(texto: string, valores?: readonly unknown[]): Promise<{ rows: readonly T[] }>;
}

/** Uma linha de `media_assets`, como o `SELECT` a devolve. */
export interface LinhaDeMidia {
  readonly asset_id: string;
  readonly estado: string;
  readonly classe: string;
  readonly storage_ref: string | null;
  readonly sha256: string | null;
}

/** O que a porta do armazenamento precisa, reexportado para quem monta o MED. */
export type { Ctx, ObjectKey, ObjectRef, StorageProvider };

/** A descarga não respondeu: o provedor está em baixo, e isto repete-se. */
export class MidiaIndisponivelError extends Error {
  constructor(causa: string) {
    super(`a midia nao respondeu: ${causa}`);
    this.name = "MidiaIndisponivelError";
  }
}

/**
 * A resposta não se consegue usar, e **não** se repete.
 *
 * A distinção é a mesma que o HND escreveu para o Chatwoot e vale pela mesma
 * razão: um 4xx é um pedido nosso errado, e uma fila que o repetisse nunca
 * drenava.
 */
export class MidiaInesperadaError extends Error {
  constructor(detalhe: string) {
    super(`a midia respondeu o que nao se consegue usar: ${detalhe}`);
    this.name = "MidiaInesperadaError";
  }
}

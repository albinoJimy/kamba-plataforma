/**
 * A tradução de vocabulário e a *allowlist* (KAM-020, critério 4).
 *
 * ## Os números todos aqui são *proposta*, e a razão não é cautela
 *
 * **A API de mídia da Meta não tem evidência nenhuma.** O
 * `docs/tecnica/evidencia/E1` não tem a página de referência e **nem a lista
 * como omissão** — não há limite de tamanho por tipo, nem tempo de expiração do
 * URL, nem os códigos de erro. Os limites abaixo são os do bloco do ticket,
 * que também os marca como «valores a calibrar contra os limites da Meta, NÃO
 * VERIFICADOS».
 *
 * **Onde calibram:** no primeiro contacto com a API real, que é trabalho do
 * `ext:KAM-101` (perguntas escritas à Meta) e do `ext:KAM-102` (App Review).
 * Até lá, um limite nosso mais apertado do que o dela é inofensivo — recusa
 * cedo o que ela recusaria tarde; um mais largo é que faz uma descarga morrer
 * a meio depois de gastar banda.
 *
 * **E vão em configuração e não num literal**, pela razão que o KAM-015
 * escreveu para a versão da Graph: fixar um limite num literal obriga a um
 * *commit* para o mudar, e quem o muda é quem opera.
 */

import { CLASSES, type Classe, type MotivoDeRejeicao } from "./contrato.ts";

/**
 * Os `wa_type` que trazem mídia, e a classe de cada um.
 *
 * O `WA_TYPES` do `entrada/contrato.ts` tem dez valores; **quatro** são de
 * mídia. O `sticker` entra como imagem e não como classe própria: é uma imagem
 * do ponto de vista do armazenamento e da retenção, e uma quarta classe só para
 * ele multiplicava a política de retenção do KAM-071 sem mudar nada.
 */
export const CLASSE_POR_WA_TYPE: Readonly<Record<string, Classe>> = {
  audio: "media_audio",
  image: "media_imagem",
  sticker: "media_imagem",
  document: "media_documento",
};

/**
 * A *allowlist* de tipos por classe, e o tamanho máximo de cada uma.
 *
 * Os tipos são os do bloco do ticket (JPEG, PNG, WebP, OGG/Opus, PDF). Os
 * tamanhos são **proposta**; ver a nota do módulo.
 */
export interface LimiteDaClasse {
  readonly tipos: readonly string[];
  readonly bytesMaximos: number;
}

export const LIMITES_POR_OMISSAO: Readonly<Record<Classe, LimiteDaClasse>> = {
  // O OGG/Opus é o que a Meta usa para as notas de voz. 16 MiB é *proposta*.
  media_audio: {
    tipos: ["audio/ogg", "audio/ogg; codecs=opus", "audio/opus"],
    bytesMaximos: 16 * 1024 * 1024,
  },
  // O WebP entra porque os *stickers* do WhatsApp são WebP, e eles caem nesta
  // classe. 5 MiB é *proposta*.
  media_imagem: {
    tipos: ["image/jpeg", "image/png", "image/webp"],
    bytesMaximos: 5 * 1024 * 1024,
  },
  // **Só PDF**, e a restrição é deliberada — mas a razão que o bloco do ticket
  // dá para ela é **falsa**, e a revisão adversarial apanhou-o. Ele diz que a
  // análise de malware e de conteúdo activo «não consta de `docs/tecnica/`», e
  // consta: o `../docs/tecnica/08` §4.2 tem, na linha do MED da matriz STRIDE,
  // «Ficheiro malicioso → tipo/tamanho/**antivírus**, nunca executar» e
  // «Parsers (imagem/PDF) → processo sem privilégios, sem rede».
  //
  // O que o KAM-065 deve é o **modelo de ameaças**, não a primeira menção do
  // controlo. Nem o antivírus nem o processo sem privilégios estão feitos neste
  // ticket, e isso é uma exigência documental em dívida e não uma lacuna do
  // canon. Até lá, a defesa é a estreiteza da lista — aceitar `.docx` ou
  // `.xlsx` era aceitar macros sem ter quem as inspeccione.
  // 20 MiB é *proposta*.
  media_documento: {
    tipos: ["application/pdf"],
    bytesMaximos: 20 * 1024 * 1024,
  },
};

/** A classe de um `wa_type`, ou `null` se ele não traz mídia. */
export function classeDe(waType: string): Classe | null {
  return CLASSE_POR_WA_TYPE[waType] ?? null;
}

/**
 * Normaliza um `content-type` para comparação.
 *
 * **Compara-se o tipo e ignoram-se os parâmetros**, excepto quando a lista os
 * nomeia. Um `audio/ogg; codecs=opus` e um `audio/ogg` são o mesmo tipo para a
 * *allowlist*, e um `image/jpeg;charset=utf-8` (que não faz sentido mas
 * aparece) não devia ser recusado por causa do parâmetro. A comparação é em
 * minúsculas porque o cabeçalho não garante a caixa.
 */
export function normalizar(contentType: string): string {
  return contentType.trim().toLowerCase();
}

function tipoBase(contentType: string): string {
  const [base] = normalizar(contentType).split(";");
  return (base ?? "").trim();
}

/** O veredicto da *allowlist*: `null` quando passa. */
export function recusar(
  classe: Classe,
  contentType: string,
  tamanho: number,
  limites: Readonly<Record<Classe, LimiteDaClasse>> = LIMITES_POR_OMISSAO,
): MotivoDeRejeicao | null {
  const limite = limites[classe];
  const normalizado = normalizar(contentType);
  const base = tipoBase(contentType);
  const permitido = limite.tipos.some(
    (tipo) => normalizar(tipo) === normalizado || normalizar(tipo) === base,
  );
  // **O tipo antes do tamanho**, e a ordem é a do custo da resposta ao cliente:
  // «manda outro formato» e «manda mais pequeno» são conselhos diferentes, e
  // dizer o segundo a quem mandou um `.docx` de 1 KB não ajuda ninguém.
  if (!permitido) return "tipo_nao_permitido";
  if (tamanho > limite.bytesMaximos) return "tamanho_excedido";
  return null;
}

/**
 * O que se diz ao cliente, e é **determinístico** (critério 4).
 *
 * Determinístico e não gerado pelo modelo, e a razão é a do §2 do dicionário
 * para as respostas de erro: o cliente que mandou um ficheiro que não passa
 * tem de receber sempre a mesma frase, porque é por ela que a PME percebe o que
 * se passou quando ele lhe liga a reclamar. Uma frase diferente a cada vez
 * torna o problema impossível de reconhecer.
 *
 * **Não diz o tipo nem o tamanho que o cliente mandou**: a frase vai para o
 * WhatsApp e ecoar o que ele enviou não acrescenta nada ao que ele tem de
 * fazer, e o que falta aqui é uma decisão de produto que ninguém tomou (os
 * textos ao cliente são do KAM-025 em diante).
 */
export const RESPOSTAS: Readonly<Record<MotivoDeRejeicao, string>> = {
  tipo_nao_permitido:
    "Nao consigo abrir esse ficheiro. Pode enviar como foto (JPEG ou PNG), " +
    "nota de voz, ou PDF?",
  tamanho_excedido:
    "Esse ficheiro e grande demais para mim. Pode enviar um mais pequeno?",
  classe_desconhecida:
    "Nao consigo abrir esse tipo de ficheiro. Pode escrever o que precisa?",
};

/** As classes, para quem precise de iterar. */
export { CLASSES };

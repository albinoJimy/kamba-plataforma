/**
 * O aceite contratual: o caso de uso e as portas (KAM-090, critérios 2, 3 e 5).
 *
 * «O aceite exige OTP (KAM-086) e a declaração de poderes para obrigar a PME.»
 * «Repetir o POST de aceite com a mesma chave não cria 2 registos; um aceite de
 * versão antiga não satisfaz o gate.»
 *
 * ## O que é deste módulo e o que é da base
 *
 * A base (revisão `0040`) recusa a versão que não é a vigente, o texto que não
 * é o publicado e o OTP de outro caso, e escreve a hora e a evidência. Este
 * caso de uso recusa **o que a base não pode ver**: a declaração de poderes, os
 * recibos de abertura (`./recibos.ts`) e o veredicto do OTP. Corre os três
 * antes de tocar na base, e as quatro linhas (uma por documento) escrevem-se
 * todas ou nenhuma — o adaptador SQL abre uma transacção.
 *
 * **A ordem é a do custo.** O OTP verifica-se em último lugar: cada verificação
 * gasta uma das cinco tentativas do desafio (KAM-086), e um cliente adulterado
 * que não abriu os documentos não deve queimar o código do titular.
 *
 * **A repetição do mesmo POST é idempotente na base, e não necessariamente
 * aqui.** As linhas não se duplicam (`ON CONFLICT … DO NOTHING`), mas o segundo
 * pedido volta a verificar o OTP — e se o KAM-086 apagar o desafio depois de
 * um `acertou`, a repetição devolve `recusado/otp` sobre um aceite que já está
 * gravado. Quem ligar o ecrã decide se lê a prova antes de pedir o código
 * outra vez; fica escrito no bloco com o resto do critério 2.
 *
 * ## O `otp_challenge_id` vem do verificador, e o do KAM-086 ainda não o dá
 *
 * O `Otp` de `../inscricao/otp.ts` guarda **um** desafio por caso, sem
 * identificador. A porta `VerificadorDeOtp` pede-o, e a ligação ao `Otp` real
 * fica com credor (KAM-086), escrito no bloco. Sem ele, um adaptador que
 * inventasse um `uuid` por chamada tirava ao `EXCLUDE` da base o que ele
 * protege: dois casos com o mesmo código verificado teriam dois ids.
 */

import { createHmac } from "node:crypto";
import { isIP } from "node:net";

import { reciboValido } from "./recibos.ts";
import { TIPOS, TIPOS_A_ABRIR, type Documento, type Tipo, vigente } from "./versoes.ts";

/** O veredicto do OTP que autoriza. Os outros quatro do KAM-086 recusam. */
export const OTP_ACERTOU = "acertou";

export interface VerificacaoDeOtp {
  readonly veredicto: string;
  /** O id do desafio que acertou; `null` em qualquer outro veredicto. */
  readonly desafioId: string | null;
}

/** Verifica o código do titular contra o desafio vivo do caso. */
export interface VerificadorDeOtp {
  verificar(onboardingId: string, codigo: unknown): Promise<VerificacaoDeOtp>;
}

/** Lê as versões publicadas (todas, ou só as que podem ser vigentes). */
export interface LeitorDeDocumentos {
  publicados(): Promise<readonly Documento[]>;
}

/** Uma linha a gravar. A hora e a evidência são da base, e não vão aqui. */
export interface LinhaDeAceite {
  readonly onboardingId: string;
  readonly tenantId: string;
  readonly documentId: string;
  readonly versao: string;
  readonly docSha256: Uint8Array;
  readonly signatarioRef: string;
  readonly otpChallengeId: string;
  readonly ipPrefixHash: Uint8Array | null;
}

/** Grava as linhas numa transacção, idempotente pela chave `(onboarding, documento, versão)`. */
export interface EscritorDeAceites {
  gravar(linhas: readonly LinhaDeAceite[]): Promise<void>;
}

export interface PortasDoAceite {
  readonly documentos: LeitorDeDocumentos;
  readonly otp: VerificadorDeOtp;
  readonly escritor: EscritorDeAceites;
  /** O anel das chaves dos recibos de abertura. */
  readonly anel: readonly (Uint8Array | null)[];
  readonly relogio?: (() => Date) | undefined;
}

export interface PedidoDeAceite {
  readonly onboardingId: string;
  readonly tenantId: string;
  /** O titular do caso, resolvido pela sessão — nunca pelo corpo do pedido. */
  readonly signatarioRef: string;
  readonly codigoOtp: unknown;
  /** Tem de ser literalmente `true`: uma cadeia `"true"` não é uma declaração. */
  readonly declaracaoDePoderes: unknown;
  /** Um recibo por documento aberto, como o servidor os entregou. */
  readonly recibos: Readonly<Partial<Record<Tipo, unknown>>>;
  readonly ipPrefixHash: Uint8Array | null;
}

export const MOTIVOS = [
  "sem_declaracao",
  "sem_versao_vigente",
  "documento_por_abrir",
  "otp",
] as const;

export type Motivo = (typeof MOTIVOS)[number];

export type ResultadoDoAceite =
  | {
      readonly tipo: "aceite";
      readonly documentos: readonly { readonly tipo: Tipo; readonly versao: string }[];
    }
  | { readonly tipo: "recusado"; readonly motivo: Motivo; readonly documento?: Tipo };

/** O aceite das versões vigentes dos quatro documentos, por um caso. */
export async function aceitar(
  pedido: PedidoDeAceite,
  portas: PortasDoAceite,
): Promise<ResultadoDoAceite> {
  if (pedido.declaracaoDePoderes !== true) return { tipo: "recusado", motivo: "sem_declaracao" };

  const agora = (portas.relogio ?? (() => new Date()))();
  const publicados = await portas.documentos.publicados();
  const vigentes = new Map<Tipo, Documento>();
  for (const tipo of TIPOS) {
    const documento = vigente(publicados, tipo, agora);
    if (documento === null) return { tipo: "recusado", motivo: "sem_versao_vigente", documento: tipo };
    vigentes.set(tipo, documento);
  }

  for (const tipo of TIPOS_A_ABRIR) {
    const documento = vigentes.get(tipo) as Documento;
    const aberto = reciboValido(
      pedido.recibos[tipo],
      { onboardingId: pedido.onboardingId, documentId: documento.documentId, sha256: documento.sha256 },
      portas.anel,
    );
    if (!aberto) return { tipo: "recusado", motivo: "documento_por_abrir", documento: tipo };
  }

  const otp = await portas.otp.verificar(pedido.onboardingId, pedido.codigoOtp);
  if (otp.veredicto !== OTP_ACERTOU || otp.desafioId === null) {
    return { tipo: "recusado", motivo: "otp" };
  }

  const linhas = TIPOS.map((tipo) => {
    const documento = vigentes.get(tipo) as Documento;
    return {
      onboardingId: pedido.onboardingId,
      tenantId: pedido.tenantId,
      documentId: documento.documentId,
      versao: documento.versao,
      docSha256: documento.sha256,
      signatarioRef: pedido.signatarioRef,
      otpChallengeId: otp.desafioId as string,
      ipPrefixHash: pedido.ipPrefixHash,
    };
  });
  await portas.escritor.gravar(linhas);
  return {
    tipo: "aceite",
    documentos: TIPOS.map((tipo) => ({ tipo, versao: (vigentes.get(tipo) as Documento).versao })),
  };
}

/**
 * O `ip_prefix_hash`: HMAC do **prefixo** do endereço, nunca do endereço.
 *
 * `/24` em IPv4 e `/48` em IPv6. HMAC com chave e não `sha256` simples: o
 * espaço dos prefixos IPv4 são 2^24 valores, e um resumo sem chave inverte-se
 * numa tarde. Um endereço que não se lê devolve `null` — a coluna é anulável e
 * a prova não depende dela.
 */
export function hashDoPrefixoDeIp(bruto: string, chave: Uint8Array): Buffer | null {
  let prefixo: string;
  // IPv4 mapeado em IPv6 (`::ffff:a.b.c.d`) lê-se como o IPv4 que é: num
  // *socket* de duas pilhas é assim que **todos** os clientes IPv4 chegam, e o
  // prefixo `/48` deles era sempre `0000:0000:0000` — a coluna ficava
  // constante. Achado da revisão adversarial.
  const mapeado = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i.exec(bruto);
  const endereco = mapeado?.[1] ?? bruto;
  const versao = isIP(endereco);
  if (versao === 4) {
    prefixo = `${endereco.split(".").slice(0, 3).join(".")}.0/24`;
  } else if (versao === 6) {
    const partes = expandirIpv6(endereco);
    prefixo = `${partes.slice(0, 3).join(":")}::/48`;
  } else {
    return null;
  }
  return createHmac("sha256", chave).update(prefixo, "utf8").digest();
}

function expandirIpv6(endereco: string): string[] {
  const [esquerda = "", direita = ""] = endereco.toLowerCase().split("::");
  const a = esquerda === "" ? [] : esquerda.split(":");
  const b = endereco.includes("::") ? (direita === "" ? [] : direita.split(":")) : [];
  const zeros = endereco.includes("::") ? 8 - a.length - b.length : 0;
  return [...a, ...Array<string>(zeros).fill("0"), ...b].map((h) => h.padStart(4, "0"));
}

/**
 * As versões publicadas dos quatro documentos, e as duas fórmulas da prova
 * (KAM-090, critérios 1 e 3).
 *
 * «`contract_document` guarda `tipo`, `versao` SemVer, `sha256` do conteúdo
 * canónico, `vigente_desde`; uma versão publicada é imutável.»
 *
 * ## A base é quem decide, e este módulo é quem prepara
 *
 * A revisão `0040` recusa um `sha256` que não seja o do conteúdo, um conteúdo
 * com `\r` ou fora de NFC, uma versão fora de SemVer e um aceite de versão que
 * não seja a vigente. Este ficheiro existe para o texto **chegar** à base na
 * forma que ela aceita (`canonizar`) e para o serviço saber, antes de mostrar o
 * ecrã, qual é a versão a mostrar (`vigente`). A `vigente` é a mesma pergunta
 * que o *trigger* `contract_acceptance_preparar` faz, e as duas têm de
 * responder igual — o ensaio `contratos.versoes.test.ts` fixa o desempate.
 *
 * ## A evidência tem largura fixa
 *
 * `sha256(doc_sha256 ‖ signatario ‖ aceite_em ‖ otp_challenge_id)`, pela ordem
 * do critério 3: 32 octetos do resumo, 16 do `uuid`, 8 do instante em
 * microssegundos desde a época (*big-endian*) e 16 do `uuid`. É a função
 * `platform.contrato_evidencia` da revisão, escrita outra vez aqui porque a
 * exportação da prova (critério 9) tem de a poder recalcular fora da base — e
 * o ensaio de BD confronta a da base com um terceiro oráculo, em `hashlib`.
 */

import { createHash } from "node:crypto";

/** Os quatro tipos, pela ordem da base (`ORDER BY tipo`). */
export const TIPOS = ["dpa", "privacidade", "subprocessadores", "tos"] as const;

export type Tipo = (typeof TIPOS)[number];

/**
 * Os três que o ecrã exige **abertos** antes de activar o botão (critério 2).
 *
 * A lista de subprocessadores aceita-se também — o gate exige-a —, mas o
 * critério diz «depois de abrir os 3 documentos», e quatro era um critério
 * mais forte do que o escrito. A leitura fica registada no bloco.
 */
export const TIPOS_A_ABRIR: readonly Tipo[] = ["dpa", "privacidade", "tos"];

/** SemVer sem pré-lançamento nem metadados — o mesmo `CHECK` da revisão. */
const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;

/** Uma versão publicada, como a base a devolve. */
export interface Documento {
  readonly documentId: string;
  readonly tipo: Tipo;
  readonly versao: string;
  readonly sha256: Uint8Array;
  readonly vigenteDesde: Date;
}

export class VersaoInvalidaError extends Error {
  constructor(versao: string) {
    super(`versao fora de SemVer: ${JSON.stringify(versao)}`);
    this.name = "VersaoInvalidaError";
  }
}

/** `true` se a versão é SemVer sem sufixos. */
export function versaoValida(versao: string): boolean {
  return SEMVER.test(versao);
}

/** Compara duas versões SemVer: negativo, zero ou positivo. */
export function compararVersoes(a: string, b: string): number {
  const pa = SEMVER.exec(a);
  const pb = SEMVER.exec(b);
  if (pa === null) throw new VersaoInvalidaError(a);
  if (pb === null) throw new VersaoInvalidaError(b);
  for (let i = 1; i <= 3; i += 1) {
    const x = BigInt(pa[i] ?? "0");
    const y = BigInt(pb[i] ?? "0");
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/**
 * O conteúdo canónico: NFC, fins de linha `\n`, e **um** `\n` no fim.
 *
 * Sem isto, o mesmo texto guardado por dois editores dava dois resumos — e uma
 * prova cujo resumo depende do editor de quem publicou não prova que texto foi
 * aceite. Um texto vazio depois de canonizado não é um documento.
 */
export function canonizar(texto: string): string {
  const linhas = texto.normalize("NFC").replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (linhas.trim() === "") throw new Error("um documento vazio nao se publica");
  return `${linhas}\n`;
}

/** O `sha256` do conteúdo **já canónico**, em UTF-8. */
export function sha256DoConteudo(canonico: string): Buffer {
  return createHash("sha256").update(canonico, "utf8").digest();
}

/**
 * A versão vigente de um tipo em `agora`: a de `vigenteDesde` mais recente que
 * não esteja no futuro. `null` quando não há nenhuma — e então o gate fecha.
 *
 * Não há empate a desempatar: a revisão tem `UNIQUE (tipo, vigente_desde)`.
 */
export function vigente(
  documentos: readonly Documento[],
  tipo: Tipo,
  agora: Date,
): Documento | null {
  let melhor: Documento | null = null;
  for (const documento of documentos) {
    if (documento.tipo !== tipo) continue;
    if (documento.vigenteDesde.getTime() > agora.getTime()) continue;
    if (melhor === null || documento.vigenteDesde.getTime() > melhor.vigenteDesde.getTime()) {
      melhor = documento;
    }
  }
  return melhor;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function octetosDoUuid(valor: string): Buffer {
  if (!UUID.test(valor)) throw new Error(`uuid invalido: ${JSON.stringify(valor)}`);
  return Buffer.from(valor.replace(/-/g, ""), "hex");
}

/** Os campos da evidência. O instante vai em **microssegundos**, que é a resolução da base. */
export interface CamposDaEvidencia {
  readonly docSha256: Uint8Array;
  readonly signatarioRef: string;
  readonly aceiteEmMicros: bigint;
  readonly otpChallengeId: string;
}

/** `sha256(doc_sha256 ‖ signatario ‖ aceite_em ‖ otp_challenge_id)`, critério 3. */
export function evidencia(campos: CamposDaEvidencia): Buffer {
  if (campos.docSha256.length !== 32) throw new Error("o doc_sha256 tem 32 octetos");
  const instante = Buffer.alloc(8);
  instante.writeBigInt64BE(campos.aceiteEmMicros);
  return createHash("sha256")
    .update(campos.docSha256)
    .update(octetosDoUuid(campos.signatarioRef))
    .update(instante)
    .update(octetosDoUuid(campos.otpChallengeId))
    .digest();
}

/**
 * A exportação da prova de aceite (KAM-090, critério 9) — em JSON.
 *
 * «Exportação da prova de aceite (PDF/JSON com *hash*) disponível ao titular e
 * ao KAM-098.» Este ficheiro entrega o **JSON**; o PDF é renderização, e o STO
 * que o guarda é de outro componente — fica com credor no bloco.
 *
 * ## A exportação verifica antes de exportar
 *
 * Cada linha leva o `evidence_hash` que a base escreveu, e a exportação
 * **recalcula-o** com o `evidencia` de `./versoes.ts`. Se não bater, não
 * exporta: uma prova que não se reproduz a partir dos próprios campos não é
 * prova, e exportá-la era pôr nas mãos do titular um documento que o primeiro
 * perito desmonta. O resumo do documento inteiro vai no fim, sobre o JSON
 * canónico das linhas (chaves por ordem, sem espaços).
 */

import { createHash } from "node:crypto";

import { evidencia, type Tipo } from "./versoes.ts";

/** Uma linha de aceite, como a base a devolve para exportar. */
export interface LinhaDaProva {
  readonly documentId: string;
  readonly tipo: Tipo;
  readonly versao: string;
  readonly docSha256: Uint8Array;
  readonly signatarioRef: string;
  readonly otpChallengeId: string;
  /** Microssegundos desde a época, como a base os guarda. */
  readonly aceiteEmMicros: bigint;
  readonly evidenceHash: Uint8Array;
}

export interface ProvaExportada {
  readonly onboarding_id: string;
  readonly aceites: readonly Record<string, string>[];
  /** `sha256` do JSON canónico dos `aceites`, em hexadecimal. */
  readonly sha256: string;
}

export class ProvaInconsistenteError extends Error {
  constructor(documentId: string) {
    super(`a evidencia do aceite do documento ${documentId} nao se reproduz`);
    this.name = "ProvaInconsistenteError";
  }
}

function instanteIso(micros: bigint): string {
  const milis = micros / 1000n;
  const resto = micros % 1000n;
  const iso = new Date(Number(milis)).toISOString();
  return `${iso.slice(0, 23)}${resto.toString().padStart(3, "0")}Z`;
}

/** A prova de um caso, verificada linha a linha. */
export function exportarProva(onboardingId: string, linhas: readonly LinhaDaProva[]): ProvaExportada {
  const aceites = [...linhas]
    .sort((a, b) => (a.tipo < b.tipo ? -1 : a.tipo > b.tipo ? 1 : 0))
    .map((linha) => {
      const esperada = evidencia({
        docSha256: linha.docSha256,
        signatarioRef: linha.signatarioRef,
        aceiteEmMicros: linha.aceiteEmMicros,
        otpChallengeId: linha.otpChallengeId,
      });
      if (!esperada.equals(Buffer.from(linha.evidenceHash))) {
        throw new ProvaInconsistenteError(linha.documentId);
      }
      return {
        aceite_em: instanteIso(linha.aceiteEmMicros),
        doc_sha256: Buffer.from(linha.docSha256).toString("hex"),
        document_id: linha.documentId,
        evidence_hash: esperada.toString("hex"),
        otp_challenge_id: linha.otpChallengeId,
        signatario_ref: linha.signatarioRef,
        tipo: linha.tipo,
        versao: linha.versao,
      };
    });
  const sha256 = createHash("sha256").update(JSON.stringify(aceites), "utf8").digest("hex");
  return { onboarding_id: onboardingId, aceites, sha256 };
}

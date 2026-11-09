/**
 * Os adaptadores SQL do aceite contratual, sobre a revisão `0040` (KAM-090).
 *
 * Três consultas, e as três correm pela ligação da **aplicação** com o
 * contexto do tenant pré-alocado do caso: a `contract_acceptance` tem RLS
 * `FORCE`, e o `INSERT` só passa o `WITH CHECK` com `app.tenant_id` igual ao
 * `tenant_id` da linha. Quem define o contexto é o `comTenant` de quem monta o
 * módulo, e nunca este ficheiro.
 *
 * O `evidence_hash` vai **vazio** no `INSERT`: escreve-o o *trigger*
 * `contract_acceptance_preparar`, por cima do que vier, como a hora. Mandá-lo
 * calculado daqui era dar a entender que o valor do cliente conta.
 */

import type { LinhaDaProva } from "./prova.ts";
import type { Documento, Tipo } from "./versoes.ts";
import type { EscritorDeAceites, LeitorDeDocumentos, LinhaDeAceite } from "./aceite.ts";

/** O cliente de SQL que este módulo precisa. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

export const SQL_PUBLICADOS =
  "SELECT document_id::text AS document_id, tipo, versao, sha256, vigente_desde " +
  "FROM platform.contract_document WHERE vigente_desde <= now() " +
  "ORDER BY tipo, vigente_desde DESC";

export const SQL_ACEITE =
  "INSERT INTO platform.contract_acceptance " +
  "(onboarding_id, tenant_id, document_id, versao, doc_sha256, signatario_ref, " +
  "otp_challenge_id, ip_prefix_hash, evidence_hash) " +
  "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, ''::bytea) " +
  "ON CONFLICT ON CONSTRAINT contract_acceptance_aceite_uq DO NOTHING";

export const SQL_PROVA =
  "SELECT a.document_id::text AS document_id, d.tipo, a.versao, a.doc_sha256, " +
  "a.signatario_ref::text AS signatario_ref, a.otp_challenge_id::text AS otp_challenge_id, " +
  "((extract(epoch FROM a.aceite_em) * 1000000)::bigint)::text AS aceite_em_micros, " +
  "a.evidence_hash " +
  "FROM platform.contract_acceptance a " +
  "JOIN platform.contract_document d ON d.document_id = a.document_id " +
  "WHERE a.onboarding_id = $1 ORDER BY d.tipo";

interface LinhaPublicada {
  readonly document_id: string;
  readonly tipo: Tipo;
  readonly versao: string;
  readonly sha256: Uint8Array;
  readonly vigente_desde: Date;
}

/** As versões que já vigoram ou vigoraram. As futuras não interessam a um aceite de hoje. */
export class LeitorSql implements LeitorDeDocumentos {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async publicados(): Promise<readonly Documento[]> {
    const { rows } = await this.#cliente.query<LinhaPublicada>(SQL_PUBLICADOS);
    return rows.map((linha) => ({
      documentId: linha.document_id,
      tipo: linha.tipo,
      versao: linha.versao,
      sha256: linha.sha256,
      vigenteDesde: new Date(linha.vigente_desde),
    }));
  }
}

/**
 * Grava as quatro linhas pelo cliente que recebe, **sem abrir transacção**.
 *
 * O `INSERT` só passa com o contexto do tenant, pelo que este escritor corre
 * sempre dentro do `comTenant` — que já abriu a transacção e definiu o
 * `app.tenant_id` com `set_config(…, true)`. É essa transacção que torna as
 * quatro linhas atómicas. A primeira versão abria a sua: o `BEGIN` interior era
 * ignorado e o `COMMIT` interior fechava a de fora, deixando o resto do
 * chamador sem transacção e sem contexto (achado da revisão adversarial).
 */
export class EscritorSql implements EscritorDeAceites {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async gravar(linhas: readonly LinhaDeAceite[]): Promise<void> {
    for (const linha of linhas) {
      await this.#cliente.query(SQL_ACEITE, [
        linha.onboardingId,
        linha.tenantId,
        linha.documentId,
        linha.versao,
        Buffer.from(linha.docSha256),
        linha.signatarioRef,
        linha.otpChallengeId,
        linha.ipPrefixHash === null ? null : Buffer.from(linha.ipPrefixHash),
      ]);
    }
  }
}

interface LinhaDeProvaSql {
  readonly document_id: string;
  readonly tipo: Tipo;
  readonly versao: string;
  readonly doc_sha256: Uint8Array;
  readonly signatario_ref: string;
  readonly otp_challenge_id: string;
  readonly aceite_em_micros: string;
  readonly evidence_hash: Uint8Array;
}

/** As linhas de prova de um caso, para o `exportarProva`. */
export async function lerProva(cliente: ClienteSql, onboardingId: string): Promise<LinhaDaProva[]> {
  const { rows } = await cliente.query<LinhaDeProvaSql>(SQL_PROVA, [onboardingId]);
  return rows.map((linha) => ({
    documentId: linha.document_id,
    tipo: linha.tipo,
    versao: linha.versao,
    docSha256: linha.doc_sha256,
    signatarioRef: linha.signatario_ref,
    otpChallengeId: linha.otp_challenge_id,
    aceiteEmMicros: BigInt(linha.aceite_em_micros),
    evidenceHash: linha.evidence_hash,
  }));
}

/**
 * As portas de entrada da fila (KAM-089): as que o KAM-087, o KAM-088 e o
 * KAM-093 deixaram com este ticket como credor, cada uma cumprida aqui sobre o
 * `ServicoDeRevisao`.
 *
 * ```text
 * kyc/contrato.ts       FilaDeRevisao.enviar(onboardingId, score, marcas, recomendacao)
 * guia/contrato.ts      FilaDeRevisao.abrir(onboardingId, "es_falhado", motivo)
 * screening/motor.ts    EscritorDeDecisoes.gravar(linha) — uma `condicional` abre caso
 * screening (credor)    DecisaoHumanaDeScreening — a linha `origem = 'humano'`
 * ```
 *
 * **Uma chave por porta**, e é o que faz a reentrega idempotente (critério 9):
 * o KYC abre `kyc_k1` (um caso de K1 por onboarding — o motivo concreto vai no
 * motivo interno, e um segundo envio depois de um `pedir_info` cai no mesmo
 * caso, que continua aberto); o guia abre `es_falhado` com o motivo da falha
 * no interno (a chave do guia é `(onboardingId, tipo)`); o screening abre uma
 * chave por **conteúdo** decidido.
 */

import type { FilaDeRevisao as FilaDoKyc, Marca, Recomendacao as RecomendacaoDoKyc, RepositorioDeVerificacoes } from "../kyc/contrato.ts";
import { REGRAS_DURAS } from "../kyc/contrato.ts";
import type { FilaDeRevisao as FilaDoGuia, MotivoDeFalha } from "../guia/contrato.ts";
import type { EscritorDeDecisoes, LinhaDeDecisao } from "../screening/motor.ts";
import type {
  ChaveDeScreening,
  DecisaoHumanaDeScreening,
  OnboardingsDaRevisao,
  Recomendacao,
} from "./contrato.ts";
import { PRIORIDADES } from "./contrato.ts";
import type { ResultadoDaAbertura, ServicoDeRevisao } from "./servico.ts";

/** O *score* a partir do qual um caso de KYC sem regra dura é risco alto. *Proposta*. */
export const SCORE_DE_RISCO_ALTO = 60;

/** A fila não aceitou o caso: o onboarding não está numa fase elegível. Falha fechada. */
export class CasoNaoElegivelError extends Error {
  override readonly name = "CasoNaoElegivelError";
  constructor(fase: string | null) {
    super(`caso nao elegivel para a fila (fase ${fase ?? "desconhecida"})`);
  }
}

function exigirAberto(r: ResultadoDaAbertura): void {
  if (r.estado === "nao_elegivel") throw new CasoNaoElegivelError(r.fase);
}

const RECOMENDACAO_DO_KYC: Readonly<Record<RecomendacaoDoKyc, Recomendacao>> = {
  aprovar: "aprovar",
  pedir_documentos: "pedir_info",
  investigar: "investigar",
};

/** A prioridade de um caso de KYC: regra dura 1, *score* alto 2, o resto 5. */
export function prioridadeDoKyc(marcas: readonly Marca[], score: number): number {
  if (marcas.some((m) => (REGRAS_DURAS as readonly string[]).includes(m))) return PRIORIDADES.regraDura;
  if (score >= SCORE_DE_RISCO_ALTO) return PRIORIDADES.scoreAlto;
  return PRIORIDADES.normal;
}

/** A porta do KYC (`../kyc/contrato.ts`), cumprida. */
export function filaDoKyc(
  servico: ServicoDeRevisao,
  onboardings: OnboardingsDaRevisao,
  verificacoes: Pick<RepositorioDeVerificacoes, "doCaso">,
): FilaDoKyc {
  return {
    async enviar(p) {
      const o = await onboardings.porId(p.onboardingId);
      if (o === null) throw new CasoNaoElegivelError(null);
      const evidencias = (await verificacoes.doCaso(p.onboardingId)).map((v) => ({ tipo: "kyc_check", ref: v.id }));
      exigirAberto(
        await servico.abrir({
          tipo: "kyc",
          tenantId: o.tenantId,
          onboardingId: p.onboardingId,
          motivoCodigo: "kyc_k1",
          motivoInterno: `marcas=${[...p.marcas].sort().join(",")};score=${p.score};recomendacao=${p.recomendacao}`,
          // O público é genérico para fraude e específico só para o
          // corrigível, como no KYC: o alvará expirado sozinho diz-se.
          motivoPublico:
            p.marcas.length > 0 && p.marcas.every((m) => m === "alvara_expirado")
              ? "documento_expirado"
              : "nao_foi_possivel_validar",
          evidencias,
          recomendacao: RECOMENDACAO_DO_KYC[p.recomendacao],
          prioridade: prioridadeDoKyc(p.marcas, p.score),
        }),
      );
    },
  };
}

/** A porta do guia do Embedded Signup (`../guia/contrato.ts`), cumprida. */
export function filaDoGuia(servico: ServicoDeRevisao, onboardings: OnboardingsDaRevisao): FilaDoGuia {
  return {
    async abrir(onboardingId: string, tipo: "es_falhado", motivo: MotivoDeFalha) {
      const o = await onboardings.porId(onboardingId);
      if (o === null) throw new CasoNaoElegivelError(null);
      exigirAberto(
        await servico.abrir({
          tipo,
          tenantId: o.tenantId,
          onboardingId,
          motivoCodigo: "es_falhado",
          motivoInterno: `motivo=${motivo}`,
          motivoPublico: "nao_foi_possivel_validar",
          evidencias: [{ tipo: "onboarding_case", ref: onboardingId }],
          recomendacao: "investigar",
          prioridade: PRIORIDADES.normal,
        }),
      );
    },
  };
}

function hex(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("hex");
}

/**
 * Um `EscritorDeDecisoes` que grava e, numa `condicional` que não seja humana,
 * abre o caso: `categoria` para a categoria declarada, `catalogo` para um
 * produto. A `bloqueada` não abre caso — rejeita com motivo (§4.1, passo 4) e o
 * dono tem o recurso.
 *
 * **Grava primeiro e abre depois**: um caso aberto sem a decisão gravada era
 * uma revisão de nada. E se a abertura falhar, a `condicional` gravada continua
 * a impedir a publicação (`assertPublishable` dá `por_rever`), que é a falha
 * do lado seguro.
 */
export function escritorComFila(escritor: EscritorDeDecisoes, servico: ServicoDeRevisao): EscritorDeDecisoes {
  return {
    async gravar(linha: LinhaDeDecisao) {
      await escritor.gravar(linha);
      if (linha.decisao !== "condicional" || linha.origem === "humano") return;
      const chave: ChaveDeScreening = {
        sujeitoTipo: linha.sujeitoTipo,
        sujeitoRef: linha.sujeitoRef,
        versaoPolitica: linha.versaoPolitica,
        conteudoSha256: hex(linha.conteudoSha256),
      };
      const r = await servico.abrir({
        tipo: linha.sujeitoTipo === "categoria" ? "categoria" : "catalogo",
        tenantId: linha.tenantId,
        onboardingId: linha.onboardingId,
        motivoCodigo: `screening:${chave.conteudoSha256}`,
        motivoInterno: `regras=${[...linha.regras].sort().join(",")};origem=${linha.origem}`,
        motivoPublico: "categoria_nao_permitida",
        evidencias: [{ tipo: "screening_decision", ref: JSON.stringify(chave) }],
        recomendacao: null,
        prioridade: PRIORIDADES.normal,
      });
      exigirAberto(r);
    },
  };
}

/** A decisão humana de screening, sobre o mesmo escritor *append-only* do KAM-088. */
export function decisaoHumanaDeScreening(escritor: EscritorDeDecisoes): DecisaoHumanaDeScreening {
  return {
    async gravar(p) {
      await escritor.gravar({
        tenantId: p.tenantId,
        onboardingId: p.onboardingId,
        sujeitoTipo: p.chave.sujeitoTipo,
        sujeitoRef: p.chave.sujeitoRef,
        decisao: p.decisao,
        // Quem decidiu fica no `review_decision_log`, que é atribuível a uma
        // pessoa; aqui fica que a decisão veio da fila.
        regras: ["revisao_humana"],
        versaoPolitica: p.chave.versaoPolitica,
        origem: "humano",
        conteudoSha256: new Uint8Array(Buffer.from(p.chave.conteudoSha256, "hex")),
      });
    },
  };
}

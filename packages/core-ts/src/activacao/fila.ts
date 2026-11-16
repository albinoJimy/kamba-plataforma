/**
 * A `FilaDoTeste` sobre o serviço da fila de revisão (KAM-094, critério 5; o
 * serviço é o do KAM-089).
 *
 * A forma é a do `filaDoGuia` de `../revisao/entradas.ts`: **um** caso pendente
 * por onboarding e motivo; depois de a revisão o decidir, uma ida nova à fila é
 * um caso novo, com a chave `smoke:<causa>:<oito primeiros do anterior>` — senão
 * a terceira falha seguinte caía no caso já decidido e ninguém a via.
 *
 * O `aguarda_teste` é uma das fases elegíveis do serviço (`FASES_ELEGIVEIS`), e
 * o tenant sai do caso e não de quem chama.
 */

import { CasoJaDecididoError, CasoNaoElegivelError } from "../revisao/entradas.ts";
import { PRIORIDADES } from "../revisao/contrato.ts";
import type { ServicoDeRevisao } from "../revisao/servico.ts";
import { type CausaDoTeste, FALHAS_ATE_A_FILA, type FilaDoTeste, type MaquinaDoCaso } from "./contrato.ts";

/** Quantos casos decididos se encadeiam antes de desistir. O do guia. */
const CASOS_MAXIMOS = 20;

export function filaDoTeste(servico: Pick<ServicoDeRevisao, "abrir">, maquina: MaquinaDoCaso): FilaDoTeste {
  return {
    async abrir(onboardingId: string, tipo: "es_falhado" | "saga", causa: CausaDoTeste) {
      const caso = await maquina.ler(onboardingId);
      if (caso === null) throw new CasoNaoElegivelError(null);
      let motivoCodigo = `smoke:${causa}`;
      for (let i = 0; i < CASOS_MAXIMOS; i++) {
        const r = await servico.abrir({
          tipo,
          tenantId: caso.tenantId,
          onboardingId,
          motivoCodigo,
          motivoInterno: `teste ponta a ponta falhado ${FALHAS_ATE_A_FILA} vezes seguidas; causa=${causa}`,
          motivoPublico: "nao_foi_possivel_validar",
          evidencias: [{ tipo: "onboarding_case", ref: onboardingId }],
          recomendacao: "investigar",
          prioridade: PRIORIDADES.normal,
        });
        if (r.estado === "nao_elegivel") throw new CasoNaoElegivelError(r.fase);
        if (r.estado !== "ja_decidido") return;
        motivoCodigo = `smoke:${causa}:${r.caso.id.slice(0, 8)}`;
      }
      throw new CasoJaDecididoError();
    },
  };
}

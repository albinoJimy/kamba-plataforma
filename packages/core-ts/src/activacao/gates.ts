/**
 * Os gates `catalogo_minimo` e `e2e`, e a activação (KAM-094, critério 6).
 *
 *     fecharCatalogo   conta, grava o gate `catalogo_minimo` (verde ou
 *                      vermelho, conforme a contagem de agora) e, verde e com o
 *                      caso em `aguarda_catalogo`, avança para `aguarda_teste`
 *     activar          com os seis gates verdes, chama o `advance_case`
 *                      `activar` do KAM-092 — que muda o tenant e emite o
 *                      `tenant.activated` sob o `FOR UPDATE` do caso
 *
 * O gate `e2e` grava-o o `./smoke.ts`, no `verify`.
 *
 * ## Uma vez, e por quem
 *
 * A unicidade não vem daqui: vem do `advance_case`, que vê o caso já em
 * `activo` e devolve sem escrever nem emitir. O que este serviço acrescenta é
 * recusar **antes** — com o motivo para o painel do dono — o que a base também
 * recusaria. Uma chamada directa ao `advance_case` sem o teste (o caso
 * adversarial (d)) bate no `transition_tenant`, que pergunta pelos seis gates.
 *
 * ## O `tenant.provisioned`
 *
 * O bloco diz «saga + ES + teste», e o KAM-092 decidiu-o de outra maneira: o
 * `advance_case` emite-o no `es_concluido`, com o canal ligado. Este ticket não
 * o volta a emitir — dois produtores do mesmo evento eram dois sítios a decidir
 * quando ele sai. O `transition_tenant` exige-o antes de activar.
 */

import type { CatalogoMinimo, Contagem } from "./catalogo_minimo.ts";
import {
  ActivacaoRecusadaError,
  type FaseDoCaso,
  type GatesDaActivacao,
  type MaquinaDoCaso,
} from "./contrato.ts";

/** O `actor` que fica no `tenant_state_log`. */
export const ACTOR_DA_ACTIVACAO = "kamba_batch:activacao";

export interface DependenciasDaActivacao {
  readonly catalogo: CatalogoMinimo;
  readonly gates: GatesDaActivacao;
  readonly maquina: MaquinaDoCaso;
}

export class Activacao {
  readonly #d: DependenciasDaActivacao;

  constructor(dependencias: DependenciasDaActivacao) {
    this.#d = dependencias;
  }

  async fecharCatalogo(onboardingId: string): Promise<{ contagem: Contagem; fase: FaseDoCaso }> {
    const caso = await this.#d.maquina.ler(onboardingId);
    if (caso === null) throw new ActivacaoRecusadaError("sem_caso");
    const contagem = await this.#d.catalogo.contar(caso.tenantId);
    // O gate segue a contagem nos dois sentidos: um produto retirado depois de
    // o gate ficar verde volta a pô-lo vermelho, e a activação pergunta-lhe.
    await this.#d.gates.marcar(
      onboardingId,
      "catalogo_minimo",
      contagem.cumprido,
      `elegiveis:${contagem.elegiveis}/${contagem.minimo}`,
    );
    if (!contagem.cumprido || caso.fase !== "aguarda_catalogo") return { contagem, fase: caso.fase };
    const fase = await this.#d.maquina.avancar(onboardingId, "catalogo_minimo", ACTOR_DA_ACTIVACAO);
    return { contagem, fase };
  }

  async activar(onboardingId: string): Promise<FaseDoCaso> {
    const caso = await this.#d.maquina.ler(onboardingId);
    if (caso === null) throw new ActivacaoRecusadaError("sem_caso");
    if (caso.fase === "activo") return "activo";
    if (caso.fase !== "aguarda_teste") throw new ActivacaoRecusadaError("fase_errada");
    const emFalta = await this.#d.gates.emFalta(onboardingId);
    if (emFalta.includes("e2e")) throw new ActivacaoRecusadaError("teste_por_fazer", emFalta);
    if (emFalta.length > 0) throw new ActivacaoRecusadaError("gates_em_falta", emFalta);
    return this.#d.maquina.avancar(onboardingId, "activar", ACTOR_DA_ACTIVACAO);
  }
}

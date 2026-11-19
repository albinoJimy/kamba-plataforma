/**
 * O envio de uma resposta pelo `Saida` do KAM-015, numa ligação própria (KAM-224).
 *
 * É a porta `EnviarResposta` do `efeitoDoOutbound`, ligada. Por envio: toma uma
 * ligação, põe-lhe o `app.tenant_id` **de sessão** (o `Saida` corre as instruções
 * em *autocommit*, fora de transacção, e a `outbound_messages` tem RLS `FORCE`),
 * monta o `Saida` com o `PreSendGuard` do KAM-018 sobre a **mesma** ligação, envia,
 * limpa o contexto e devolve a ligação.
 *
 * O `Limites` (o *token bucket* por número) e as métricas são **um** por
 * processo, e não um por envio: um `Saida` novo a cada mensagem com um `Limites`
 * novo esquecia o débito que o anterior tinha gasto.
 *
 * ## O que não está aqui
 *
 * O **cliente da Meta** e o **destinatário** entram por parâmetro. Em produção,
 * nenhum dos dois tem fonte neste repositório: o *token* de cada canal é um
 * `tenant_channels.token_ref` sem leitor, e o `ObterDestinatario` (o BSUID ou o
 * telefone de um contacto) não tem implementação fora dos ensaios. Quem monta o
 * processo recusa arrancar sem eles (`services/worker-canal/src/consumidor.ts`);
 * o credor é o **KAM-226**.
 */

import type { Logger } from "../logger/index.ts";
import { criarGuarda } from "../modos/guarda.ts";
import type { MetricasDosModos } from "../modos/metricas.ts";
import { Saida } from "../outbound/adapter.ts";
import type { ClienteDaMeta, ClienteSql, ObterDestinatario, Pedido, Resultado } from "../outbound/contrato.ts";
import { Limites } from "../outbound/limites.ts";
import { MetricasDaSaida } from "../outbound/metricas.ts";
import { comTenant } from "../tenant_guard/index.ts";
import type { EnviarResposta } from "./efeito.ts";

/** A ligação de um envio: o `ClienteSql` do Outbound. */
export type LigacaoDoEnvio = ClienteSql;

/** O contexto de sessão do `Saida`. `false`: vale até se limpar, não só numa transacção. */
export const SQL_CONTEXTO_DE_SESSAO = "SELECT set_config('app.tenant_id', $1, false)";

/** Limpa o contexto antes de a ligação voltar: a seguinte pode ser de outro tenant. */
export const SQL_LIMPAR_CONTEXTO = "SELECT set_config('app.tenant_id', '', false)";

export interface OpcoesDoEnvio {
  /** Toma uma ligação `kamba_app` exclusiva para este envio. */
  readonly tomar: () => Promise<LigacaoDoEnvio>;
  /** Devolve-a. Com `erro`, a ligação falhou e não deve voltar a servir. */
  readonly devolver: (ligacao: LigacaoDoEnvio, erro?: unknown) => Promise<void> | void;
  readonly meta: ClienteDaMeta;
  readonly destinatario: ObterDestinatario;
  readonly limites?: Limites;
  readonly metricas?: MetricasDaSaida;
  readonly metricasDosModos?: MetricasDosModos;
  readonly log?: Logger;
  readonly ambiente?: Readonly<Record<string, string | undefined>>;
}

export function envioPeloSaida(o: OpcoesDoEnvio): EnviarResposta {
  const limites = o.limites ?? new Limites();
  const metricas = o.metricas ?? new MetricasDaSaida();
  return async (pedido: Pedido): Promise<Resultado> => {
    const ligacao = await o.tomar();
    let falha: unknown;
    try {
      await ligacao.query(SQL_CONTEXTO_DE_SESSAO, [pedido.tenantId]);
      const guarda = criarGuarda({
        comTenant: (tenantId, trabalho) => comTenant(ligacao, tenantId, () => trabalho(ligacao)),
        ...(o.metricasDosModos === undefined ? {} : { metricas: o.metricasDosModos }),
        ...(o.log === undefined ? {} : { log: o.log }),
      });
      const saida = new Saida({
        bd: ligacao,
        meta: o.meta,
        destinatario: o.destinatario,
        guarda,
        freeTier: null,
        limites,
        metricas,
        ...(o.log === undefined ? {} : { log: o.log }),
        ...(o.ambiente === undefined ? {} : { ambiente: o.ambiente }),
      });
      return await saida.enviar(pedido);
    } catch (erro) {
      falha = erro;
      throw erro;
    } finally {
      if (falha === undefined) {
        try {
          await ligacao.query(SQL_LIMPAR_CONTEXTO);
        } catch (erro) {
          falha = erro;
        }
      }
      await o.devolver(ligacao, falha);
    }
  };
}

/**
 * O envio de uma resposta pelo `Saida` do KAM-015, numa ligação própria (KAM-224).
 *
 * É a porta `EnviarResposta` do `efeitoDoOutbound`, ligada. Por envio: toma uma
 * ligação, monta o `Saida` e o `PreSendGuard` do KAM-018 sobre ela, envia, e
 * devolve-a.
 *
 * ## Cada instrução do `Saida` é a sua transacção, com o tenant **local**
 *
 * O `Saida` corre as instruções em *autocommit*, uma a uma — é isso que grava a
 * linha da `outbound_messages` **antes** da rede e o torna idempotente —, e a
 * tabela tem RLS `FORCE`. Por isso o `ClienteSql` que ele recebe embrulha **cada**
 * instrução no `comTenant` do `tenant_guard` (`BEGIN`, `SET LOCAL app.tenant_id`,
 * a instrução, `COMMIT`): o efeito é o mesmo do *autocommit*, e o contexto
 * **nunca** sobrevive à instrução. A primeira versão punha o tenant **de sessão**
 * (`set_config(..., false)`) e limpava-o antes de devolver a ligação; o lint do
 * `SET LOCAL` do *gate* 6 recusou-a, e com razão: um contexto de sessão que
 * escapasse à limpeza ia com a ligação para o conjunto, e o envio seguinte — de
 * outro tenant — herdava-o.
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
 * o credor é o **KAM-227**.
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

/**
 * O `ClienteSql` do `Saida` de um tenant: cada instrução numa transacção sua,
 * com o `app.tenant_id` local. Ver a nota do módulo.
 */
export function comTenantPorInstrucao(ligacao: LigacaoDoEnvio, tenantId: string): ClienteSql {
  return {
    query: <T = Record<string, unknown>>(texto: string, valores?: readonly unknown[]) =>
      comTenant(ligacao, tenantId, () => ligacao.query<T>(texto, valores)),
  };
}

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
      const guarda = criarGuarda({
        comTenant: (tenantId, trabalho) => comTenant(ligacao, tenantId, () => trabalho(ligacao)),
        ...(o.metricasDosModos === undefined ? {} : { metricas: o.metricasDosModos }),
        ...(o.log === undefined ? {} : { log: o.log }),
      });
      const saida = new Saida({
        bd: comTenantPorInstrucao(ligacao, pedido.tenantId),
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
      await o.devolver(ligacao, falha);
    }
  };
}

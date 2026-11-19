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
 * ## O cliente da Meta é do canal, e lê-se antes do `Saida`
 *
 * O `meta` não é um cliente: é o `ClienteDoCanal` (`./credencial.ts`, KAM-227),
 * que lê o *token* do canal **do pedido** na ligação do envio, sob a RLS do
 * tenant dele. Lê-se **antes** de montar o `Saida`: um canal sem *token* levanta
 * `CanalSemCredencialError` sem a linha da `outbound_messages` ter nascido, e a
 * chave do envio fica por gastar. O **destinatário** entra por parâmetro, e o
 * de produção é o `destinatarioPelaIdentidade` (`./destinatario.ts`), numa
 * ligação `kamba_identity`.
 */

import type { Logger } from "../logger/index.ts";
import { criarGuarda } from "../modos/guarda.ts";
import type { MetricasDosModos } from "../modos/metricas.ts";
import { Saida } from "../outbound/adapter.ts";
import type { ClienteSql, ObterDestinatario, Pedido, Resultado } from "../outbound/contrato.ts";
import { Limites } from "../outbound/limites.ts";
import { MetricasDaSaida } from "../outbound/metricas.ts";
import { comTenant } from "../tenant_guard/index.ts";
import type { ClienteDoCanal } from "./credencial.ts";
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
  /** O cliente da Graph do canal do pedido (`clienteDaGraphPorCanal`, em produção). */
  readonly meta: ClienteDoCanal;
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
      // Antes do `Saida`: sem *token*, a linha do Outbound não nasce.
      const meta = await o.meta(ligacao, pedido);
      const guarda = criarGuarda({
        comTenant: (tenantId, trabalho) => comTenant(ligacao, tenantId, () => trabalho(ligacao)),
        ...(o.metricasDosModos === undefined ? {} : { metricas: o.metricasDosModos }),
        ...(o.log === undefined ? {} : { log: o.log }),
      });
      const saida = new Saida({
        bd: comTenantPorInstrucao(ligacao, pedido.tenantId),
        meta,
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

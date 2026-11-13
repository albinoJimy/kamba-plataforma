/**
 * O processo do consumidor de `payment.*` do COM (KAM-055).
 *
 * É o segundo processo do `services/com`, ao lado do `server.ts`, e a razão de
 * ser um processo e não um módulo do servidor é a do `publicador.ts` e do
 * `consumidor.ts` do `worker-canal`: escala com réplicas, não com concorrência
 * por fila. Entra pelo *script* `pagamentos` do `package.json`, como o
 * `consumidor` daquele serviço.
 *
 * ## Este ficheiro é **só** o ponto de entrada, e isso é desenho
 *
 * As decisões vivem no `./arranque.ts` e o efeito no `./efeito.ts`. Aqui há
 * ligações, um `Worker` do BullMQ e um servidor HTTP — casca sobre coisas que só
 * se exercitam com PostgreSQL e Redis reais, e que não produzem cobertura V8.
 * É a mesma fronteira que o `ci/thresholds.yaml` desenha para o
 * `eventos/trabalhador_bullmq.ts`, para o `chr/fila.ts` e para o
 * `agr/trabalhador.ts`, e este ficheiro entra nos `excluidos` por essa razão —
 * com **o que pode errar em silêncio** no `arranque.ts`, que fica medido.
 *
 * ## O que faz, por esta ordem
 *
 * 1. **Verifica o arranque** (critério 4): a invariante global das subscrições
 *    de `payment.*` e a subscrição **deste** consumidor. Ver `./arranque.ts`.
 * 2. Levanta um *trabalhador* por partição da sua subscrição (16 filas, §6.5).
 * 3. Serve `/healthz` e `/metrics` na sua porta.
 *
 * ## Duas ligações, com dois papéis
 *
 * O consumo é `kamba_app`, sob RLS, e é a ligação que a transacção do efeito
 * usa. A leitura de `evt_subscricoes` é de **operação**: `kamba_app` não tem
 * `SELECT` nessa tabela (`db/tests/test_privilegios.py` dá-o só ao
 * `kamba_batch`), pelo que a verificação de arranque corre na ligação de
 * operação — a mesma escolha, e a mesma razão, do `worker-canal`.
 *
 * **E o que este processo não faz é reconciliar.** O reconciliador e o *gauge*
 * da DLQ são um por plataforma e já correm no `worker-canal`, com o seu *lock*
 * consultivo; um segundo a disputar o mesmo *lock* não acrescentava reposição
 * nenhuma e punha duas réplicas a ler a DLQ de todos os tenants.
 */

import { serve } from "@hono/node-server";
import { MaquinaNaBase, filasDe, METRICAS } from "@kamba/core-ts/eventos";
import { criarTrabalhadores } from "@kamba/core-ts/eventos/trabalhador_bullmq";
import { instalar } from "@kamba/core-ts/logger";
import { Client } from "pg";

import { SERVICE } from "../meta.ts";
import { CAUSAS_QUE_PAGAM } from "../orders/contrato.ts";
import {
  TABELA_DO_ESTADO,
  VARIAVEL_DA_BASE_POR_MODO,
  VARIAVEL_DA_FILA,
  VARIAVEL_DA_OPERACAO,
  VARIAVEL_DO_CONSUMER,
  criarApp,
  exigir,
  exigirOrdemNosPagamentos,
  exigirSubscricaoActiva,
  exigirSubscricaoComOrdem,
  modo,
  porta,
} from "./arranque.ts";
import { efeitoDePagamento } from "./efeito.ts";
import { LAG } from "./metricas.ts";
import { TIPO_DO_PEDIDO, efeitoDeReembolso } from "./reembolsos.ts";

const log = instalar(SERVICE);

async function principal(): Promise<void> {
  // KAM-197: o mesmo processo é o consumidor do PAY no modo `reembolsos`, com
  // a ligação do `kamba_pay`. A escolha e as guardas vivem no `./arranque.ts`.
  const qual = modo();
  const pagamentos = qual === "pagamentos";
  const consumer = exigir(VARIAVEL_DO_CONSUMER);
  const urlDaBase = exigir(VARIAVEL_DA_BASE_POR_MODO[qual]);
  const urlDaOperacao = exigir(VARIAVEL_DA_OPERACAO);
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  const operacao = new Client({ connectionString: urlDaOperacao });
  await operacao.connect();
  try {
    await exigirOrdemNosPagamentos(operacao);
    if (pagamentos) {
      await exigirSubscricaoComOrdem(operacao, consumer, CAUSAS_QUE_PAGAM);
    } else {
      await exigirSubscricaoActiva(operacao, consumer, [TIPO_DO_PEDIDO]);
    }
  } finally {
    await operacao.end().catch(() => {});
  }

  const consumo = criarTrabalhadores({
    // Uma ligação por fila, aberta à primeira entrega: a transacção do consumo
    // é da fila, e dezasseis filas numa sessão intercalavam `BEGIN`/`COMMIT`.
    ligar: async () => {
      const cliente = new Client({ connectionString: urlDaBase });
      await cliente.connect();
      return cliente;
    },
    subscricao: { consumer, exigeOrdem: pagamentos },
    filas: filasDe(consumer),
    efeito: pagamentos
      ? efeitoDePagamento({
          consumer,
          observarLag: (segundos) => LAG.observar(segundos),
        })
      : efeitoDeReembolso(),
    // **Sem cliente no construtor**: a máquina recebe o `bd` da transacção do
    // consumo por argumento (ver o `estadoDe` de `estados.ts`). Uma máquina
    // ligada a outra sessão lia a `orders_mirror` sem o `app.tenant_id` e, sob
    // RLS `FORCE`, devolvia `null` sempre — isto é, adiava todos os eventos.
    maquina: new MaquinaNaBase(TABELA_DO_ESTADO),
    metricas: METRICAS,
    url: urlDaFila,
    // O `log` da biblioteca tem *allowlist* de campos (`docs/tecnica/08` §7.3):
    // `consumer`, `fila` e `event_id` **não** estão nela. Fica o desfecho, e o
    // detalhe vive na base (`events_consumed`, `events_dlq`).
    log: (dados) => log.info({ outcome: `consumo_${String(dados.desfecho)}` }),
  });
  log.info({ outcome: "service_started" });

  const paragem = new AbortController();
  for (const sinal of ["SIGTERM", "SIGINT"] as const) {
    process.on(sinal, () => paragem.abort());
  }
  const servidor = serve({ fetch: criarApp().fetch, port: porta() });

  await new Promise<void>((resolver) => {
    if (paragem.signal.aborted) return resolver();
    paragem.signal.addEventListener("abort", () => resolver(), { once: true });
  });
  // `fechar()` fecha os *workers* **e** as ligações que cada fila abriu.
  await consumo.fechar();
  servidor.close();
}

if (import.meta.main) {
  await principal();
}

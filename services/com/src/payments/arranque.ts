/**
 * O que o consumidor de pagamentos verifica **antes** de servir (KAM-055).
 *
 * Está separado do `consumidor.ts` por uma razão que se mede: aquele ficheiro é
 * o ponto de entrada — levanta `Client`s do `pg`, um `Worker` do BullMQ e um
 * servidor HTTP — e nada disso produz cobertura V8 nem se exercita sem fila.
 * Este tem as decisões, e exercita-se com um cliente SQL falso. A fronteira é a
 * mesma que o `ci/thresholds.yaml` já desenha para o `eventos/trabalhador_bullmq.ts`
 * e para o `chr/fila.ts`: a casca fica fora da medição, e **o que pode errar em
 * silêncio fica dentro**.
 *
 * ## O que pode errar em silêncio aqui, e é por isso que vive neste ficheiro
 *
 * Duas leituras ao arrancar, e nenhuma substitui a outra:
 *
 * * `exigirOrdemNosPagamentos` — a invariante **global**: nenhuma subscrição de
 *   `payment.*` sem ordem, de nenhum consumidor. É a guarda que o KAM-006
 *   escreveu, e a restrição `evt_subscricoes_payment_exige_ordem` da revisão
 *   `0005` é a outra metade dela («uma guarda que depende da outra não é uma
 *   guarda»).
 * * `exigirSubscricaoComOrdem` — sobre **esta** subscrição: existe, está activa
 *   e exige ordem. A global passa com zero subscrições, pelo que um processo
 *   cuja linha ninguém inseriu ficava vivo, verde e **surdo** — o publicador só
 *   entrega a uma subscrição activa.
 *
 * ## A linha de `evt_subscricoes` é configuração de implantação
 *
 * **Nada neste repositório semeia uma subscrição** — medido: as únicas escritas
 * em `platform.evt_subscricoes` estão em `db/tests/test_eventos_schema.py` e
 * `db/tests_eventos/base.py`, e nenhuma revisão Alembic insere linha nela. Ela
 * diz **que consumidores estão implantados**, o que é por ambiente e não por
 * migração; a `payment_outbox_map`, que a revisão `0035` enche, diz outra coisa
 * — que evento de domínio corresponde a que facto do ledger —, e essa é igual
 * em todos. Por isso este ticket não a semeia e **verifica-a**.
 */

import { healthz } from "@kamba/core-ts";
import { METRICAS, SQL_PAYMENT_SEM_ORDEM } from "@kamba/core-ts/eventos";
import { Hono } from "hono";

import { SERVICE, VERSION } from "../meta.ts";
import { LAG, SINAIS, TIPO_DE_CONTEUDO } from "./metricas.ts";

/** A porta do `/metrics` deste processo. A do servidor do COM é a 3002. */
export const PORTA_POR_OMISSAO = 3013;

/** A tabela que a máquina de estados lê. O espelho da encomenda (§5.4). */
export const TABELA_DO_ESTADO = "orders_mirror";

export const VARIAVEL_DA_BASE = "KAMBA_COM_DB_URL";
export const VARIAVEL_DA_OPERACAO = "KAMBA_COM_OPS_DB_URL";
export const VARIAVEL_DA_FILA = "KAMBA_QUEUE_URL";
export const VARIAVEL_DO_CONSUMER = "KAMBA_COM_PAGAMENTOS_CONSUMER";
export const VARIAVEL_DA_PORTA = "COM_PAGAMENTOS_PORT";

/**
 * A subscrição deste consumidor, lida pela ligação de operação.
 *
 * Os tipos vêm por argumento (do `CAUSAS_QUE_PAGAM`) e não de uma lista escrita
 * aqui: a lista que diz quais os eventos que causam a transição para `paga` tem
 * **um** sítio, e duplicá-la fazia um consumidor subscrever um evento que o
 * `consumir` não sabe pré-condicionar.
 *
 * **Sem filtro de tenant, e não é lapso:** a `evt_subscricoes` é configuração
 * global e não tem `tenant_id` (dicionário §3.5). Quem a lê é o `kamba_batch`,
 * que é o único papel com `SELECT` nela.
 */
export const SQL_A_MINHA_SUBSCRICAO = `
  SELECT tipo, exige_ordem, activo
    FROM platform.evt_subscricoes
   WHERE consumer = $1 AND tipo = ANY($2)
`;

/** O mínimo que uma ligação precisa de saber fazer para estas verificações. */
export interface ClienteDeArranque {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[] }>;
}

export class VariavelEmFaltaError extends Error {
  override readonly name = "VariavelEmFaltaError";

  constructor(nome: string) {
    super(`falta a variável de ambiente ${nome}`);
  }
}

export class PortaInvalidaError extends Error {
  override readonly name = "PortaInvalidaError";

  constructor(bruto: string) {
    super(`${VARIAVEL_DA_PORTA} inválida: ${bruto}`);
  }
}

export class ArranqueSemOrdemError extends Error {
  override readonly name = "ArranqueSemOrdemError";
  readonly subscricoes: readonly string[];

  constructor(subscricoes: readonly string[]) {
    super(
      "arranque recusado: há subscrições de pagamento sem ordem — " +
        `${subscricoes.join(", ")}. Aplicar «paga» antes de ` +
        "«aguarda_pagamento» é uma transição inválida, e sem ordem ela é " +
        "possível (KAM-006, critério 7)",
    );
    this.subscricoes = subscricoes;
  }
}

export class SubscricaoEmFaltaError extends Error {
  override readonly name = "SubscricaoEmFaltaError";

  constructor(consumer: string, razao: string) {
    super(
      `arranque recusado: a subscrição de ${consumer} ${razao}. Sem ela o ` +
        "publicador não entrega nada a este consumidor, e o processo ficava " +
        "vivo e surdo — que é pior do que não arrancar (KAM-055, critério 4)",
    );
  }
}

/**
 * O valor da variável, ou **levanta**.
 *
 * Uma cadeia só de espaços conta como ausente: um `KAMBA_COM_DB_URL=" "` num
 * ficheiro de ambiente é um esquecimento, não uma configuração, e tratá-lo como
 * valor dava um erro de ligação em vez de um erro de arranque.
 */
export function exigir(
  nome: string,
  ambiente: Record<string, string | undefined> = process.env,
): string {
  const valor = ambiente[nome];
  if (valor === undefined || valor.trim() === "") {
    throw new VariavelEmFaltaError(nome);
  }
  return valor;
}

/**
 * A porta do `/metrics`, do ambiente ou a de omissão.
 *
 * **Recusa o que não é uma porta** em vez de cair na omissão: um `"3O13"` com a
 * letra O é um erro de quem configurou, e servir na 3013 escondia-o — o
 * colector raspava a porta errada e ninguém via.
 */
export function porta(
  ambiente: Record<string, string | undefined> = process.env,
): number {
  const bruto = ambiente[VARIAVEL_DA_PORTA];
  if (bruto === undefined || bruto.trim() === "") return PORTA_POR_OMISSAO;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 1 || valor > 65_535) {
    throw new PortaInvalidaError(bruto);
  }
  return valor;
}

/**
 * Os dois consumidores que este processo sabe ser (KAM-197).
 *
 * `pagamentos` é o do KAM-055: o COM a aplicar `payment.*` à encomenda, como
 * `kamba_app`. `reembolsos` é o do PAY: abre a `refund_cases` ao ler
 * `order.refund_requested`, com o papel `kamba_pay` — o único com `EXECUTE` na
 * porta da revisão `0050` (decisão (A) do fundador de 2026-11-13).
 *
 * **Um processo com dois modos e não dois pontos de entrada**, e a razão é
 * medida e não estética: um ponto de entrada novo é um ficheiro que só se
 * exercita com PostgreSQL e Redis reais, e entrava nos `excluidos` do
 * `ci/thresholds.yaml` — uma alteração a um limiar, que pede o fundador. Assim a
 * casca é a mesma, e a escolha vive aqui, medida.
 */
export const MODOS = ["pagamentos", "reembolsos"] as const;
export type Modo = (typeof MODOS)[number];

/** Que consumidor arranca. Sem ela, o do KAM-055, que era o único. */
export const VARIAVEL_DO_MODO = "COM_PAGAMENTOS_MODO";

/**
 * A ligação do consumo, por modo. **Variáveis diferentes, e não a mesma com
 * outro valor**: o `KAMBA_COM_DB_URL` a levar a credencial do `kamba_pay` era
 * um nome a dizer «COM» sobre a ligação que existe para o COM não ter.
 */
export const VARIAVEL_DA_BASE_POR_MODO: Readonly<Record<Modo, string>> = {
  pagamentos: VARIAVEL_DA_BASE,
  reembolsos: "KAMBA_PAY_DB_URL",
};

export class ModoInvalidoError extends Error {
  override readonly name = "ModoInvalidoError";

  constructor(bruto: string) {
    super(
      `${VARIAVEL_DO_MODO} inválido: ${bruto}. Os modos são ${MODOS.join(", ")}`,
    );
  }
}

/**
 * O modo, do ambiente, ou **levanta**.
 *
 * Um valor desconhecido não cai na omissão: um `reembolso` sem o `s` arrancava
 * o consumidor de pagamentos com a ligação errada, e o erro aparecia como uma
 * subscrição em falta e não como o que é.
 */
export function modo(
  ambiente: Record<string, string | undefined> = process.env,
): Modo {
  const bruto = ambiente[VARIAVEL_DO_MODO];
  if (bruto === undefined || bruto.trim() === "") return "pagamentos";
  const valor = bruto.trim();
  if (!(MODOS as readonly string[]).includes(valor)) {
    throw new ModoInvalidoError(bruto);
  }
  return valor as Modo;
}

/**
 * A subscrição **deste** consumidor existe e está activa (o modo `reembolsos`).
 *
 * É o `exigirSubscricaoComOrdem` sem a terceira condição: o
 * `order.refund_requested` não é `payment.*`, a restrição da `0005` não lhe
 * exige ordem, e a abertura do caso não depende dela — a idempotência é do
 * `pedido_evento_id`, não da sequência. Exigi-la recusava uma subscrição certa.
 */
export async function exigirSubscricaoActiva(
  bd: ClienteDeArranque,
  consumer: string,
  tipos: readonly string[],
): Promise<void> {
  const { rows } = await bd.query(SQL_A_MINHA_SUBSCRICAO, [consumer, [...tipos]]);
  const porTipo = new Map(rows.map((linha) => [String(linha.tipo), linha]));
  for (const tipo of tipos) {
    const linha = porTipo.get(tipo);
    if (linha === undefined) {
      throw new SubscricaoEmFaltaError(consumer, `não tem linha para ${tipo}`);
    }
    if (linha.activo !== true) {
      throw new SubscricaoEmFaltaError(consumer, `está inactiva para ${tipo}`);
    }
  }
}

/** A mesma guarda global do `worker-canal`, pela razão dele. */
export async function exigirOrdemNosPagamentos(
  bd: ClienteDeArranque,
): Promise<void> {
  const { rows } = await bd.query(SQL_PAYMENT_SEM_ORDEM);
  if (rows.length === 0) return;
  throw new ArranqueSemOrdemError(
    rows.map((linha) => `${String(linha.consumer)}/${String(linha.tipo)}`),
  );
}

/**
 * A subscrição **deste** consumidor existe, está activa e exige ordem?
 *
 * As três condições são separadas na mensagem porque as três causas são
 * diferentes para quem opera: não há linha (ninguém a inseriu), há linha
 * inactiva (alguém a desligou) ou há linha sem ordem — e esta última a base
 * recusa, pelo que encontrá-la é sinal de que a restrição da `0005` caiu.
 *
 * **Uma leitura e não uma por tipo:** com duas consultas, um erro entre elas
 * deixava metade verificada, e a mensagem não dizia qual.
 */
export async function exigirSubscricaoComOrdem(
  bd: ClienteDeArranque,
  consumer: string,
  tipos: readonly string[],
): Promise<void> {
  const { rows } = await bd.query(SQL_A_MINHA_SUBSCRICAO, [consumer, [...tipos]]);
  const porTipo = new Map(rows.map((linha) => [String(linha.tipo), linha]));
  for (const tipo of tipos) {
    const linha = porTipo.get(tipo);
    if (linha === undefined) {
      throw new SubscricaoEmFaltaError(consumer, `não tem linha para ${tipo}`);
    }
    if (linha.activo !== true) {
      throw new SubscricaoEmFaltaError(consumer, `está inactiva para ${tipo}`);
    }
    if (linha.exige_ordem !== true) {
      throw new SubscricaoEmFaltaError(
        consumer,
        `tem exige_ordem=false para ${tipo}, o que a restrição ` +
          "evt_subscricoes_payment_exige_ordem da revisão 0005 devia recusar",
      );
    }
  }
}

/**
 * O `/healthz` e o `/metrics` deste processo.
 *
 * O `/metrics` serve **três** exposições concatenadas: as do consumo, que a
 * biblioteca conta (`evt_consumed_total`, `evt_retry_total`), o histograma do
 * atraso do KAM-055, e a contagem de sinais de anomalia do KAM-060. Não se funde
 * num objecto só porque são de três donos: a primeira é do KAM-006 e muda com
 * ele.
 *
 * **E a terceira é ligação e não decoração.** Um contador que ninguém serve é
 * uma métrica declarada e não exposta — a classe que o `ops/metricas/catalogo.yaml`
 * conta às dezenas e que o KAM-080 mediu («as 44 do AGR não tinham rota
 * nenhuma»). O `exposicao` do `Sinais` passa o seu próprio ensaio com esta linha
 * apagada; quem morre sem ela é o ensaio que lê o corpo desta rota.
 */
export function criarApp(): Hono {
  const app = new Hono();
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  app.get("/metrics", (c) =>
    c.text(
      `${METRICAS.exposicao()}${LAG.exposicao()}${SINAIS.exposicao()}`,
      200,
      { "content-type": TIPO_DE_CONTEUDO },
    ),
  );
  return app;
}

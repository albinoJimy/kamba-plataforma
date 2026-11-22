/**
 * O estágio de saída dos `statuses` da Meta (KAM-235, critério 1).
 *
 * Até aqui o braço `outbound` do `worker-canal` contava os `statuses` e mais
 * nada: ninguém chamava o `Saida.ingerir`, o `outbound_messages.delivered_at`
 * nunca se escrevia, e o observador de produção do teste (KAM-202) dava
 * `sem_entrega` a todas as lojas. É também a ligação que o critério 7 do
 * KAM-080 deixou ao «ticket que ligar o estágio de saída».
 *
 * ```text
 * sem_estado           o evento nao traz wamid e status legiveis, ou nao tem
 *                      phone_number_id: nada a escrever
 * estado_desconhecido  um status fora dos quatro da Meta (sent, delivered,
 *                      read, failed): nao se inventa uma transicao
 * canal_desconhecido   nenhum canal com aquele phone_number_id
 * avancou              o Saida.ingerir escreveu (delivered e read escrevem o
 *                      delivered_at, uma vez: o COALESCE do SQL_AVANCAR_ESTADO)
 * nao_avancou          a mensagem nao e nossa, ou o estado nao a faz avancar
 * ```
 *
 * ## Idempotente por `wamid:estado`, duas vezes
 *
 * A primeira é a da entrada: o `event_key` de um `statuses` é `wamid:estado`, e
 * o `registarEvento` só encaminha o que é novo (`inbound_events`, `ON CONFLICT
 * DO NOTHING`). A segunda é a da base: o `SQL_AVANCAR_ESTADO` só sai de um
 * estado de onde se pode ir para este, sob `FOR UPDATE`, e o `delivered_at` fica
 * o primeiro. Uma reentrega que passe a primeira (o evento perdido a meio e
 * recuperado) não passa a segunda.
 *
 * ## Um `statuses` antes da nossa escrita do `wamid`
 *
 * O `delivered` pode chegar antes de o `SQL_MARCAR_ENVIADA` do envio confirmar
 * (a janela entre a resposta da Meta e essa instrução). O `Saida.ingerir` não
 * encontra a mensagem, devolve `avancou: false` e **avisa**
 * (`status_sem_mensagem`, pelo `log` que se lhe passa). O evento fica processado
 * e não se repete: o `delivered_at` só aparece com um `statuses` seguinte (o
 * `read`, que também o escreve). É o limite que o `Saida.ingerir` já escreve, e
 * este estágio não o resolve: repetir obrigava a distinguir «não é nossa» de
 * «ainda não é nossa», e um `statuses` de uma mensagem que nunca foi nossa
 * repetia até esgotar as tentativas.
 *
 * ## Uma falha sobe
 *
 * Uma leitura do canal ou uma escrita que falhe **lança**: o *job* falha, o
 * BullMQ repete, e o evento, registado e sem `processado_at`, volta a ser
 * encaminhado (`recuperado`). Um canal que não existe não é falha: é um desfecho,
 * e não se repete.
 *
 * ## Sem o *free tier*, e sem a métrica do custo
 *
 * O `Saida` monta-se com `freeTier: null`, que conta o custo de tudo (a nota do
 * `Dependencias.freeTier`). A contagem do *free tier* pela entrega
 * (`Metering.contar`) é do KAM-023, e não é deste estágio. O `Saida` é um por
 * evento, com as métricas dele: o custo de uma entrega fica no
 * `outbound_messages.pricing` e **não** chega ao `/metrics` do processo. A métrica
 * agregada é a que o critério 7 do KAM-080 ainda espera.
 *
 * ## Nem texto nem telefone
 *
 * Do `statuses` só se lêem o `wamid`, o `status` e o `pricing`
 * (`EventoDeEntrada.estado`); o `recipient_id` fica na explosão.
 */

import type { EventoDeEntrada } from "../entrada/explosao.ts";
import type { Logger } from "../logger/index.ts";
import { Saida } from "./adapter.ts";
import type { ClienteDaMeta, ClienteSql, Estado, ObterDestinatario } from "./contrato.ts";

/** Os `status` da Meta que o estágio escreve. Os outros dois estados são nossos. */
export const ESTADOS_DA_META: readonly Estado[] = ["sent", "delivered", "read", "failed"];

/** O que aconteceu a um `statuses`. Lista fechada: vai ao `outcome` do registo. */
export const DESFECHOS_DO_ESTAGIO = [
  "sem_estado",
  "estado_desconhecido",
  "canal_desconhecido",
  "avancou",
  "nao_avancou",
] as const;
export type DesfechoDoEstagio = (typeof DESFECHOS_DO_ESTAGIO)[number];

/** O estágio não envia: o `Saida` que ele monta recusa qualquer envio. */
export class EstagioNaoEnviaError extends Error {
  constructor() {
    super("o estagio dos statuses so escreve estados; nao envia mensagens");
    this.name = "EstagioNaoEnviaError";
  }
}

const SEM_META: ClienteDaMeta = {
  enviar: async () => {
    throw new EstagioNaoEnviaError();
  },
};

const SEM_DESTINATARIO: ObterDestinatario = async () => {
  throw new EstagioNaoEnviaError();
};

/** O `Saida` deste estágio: só o `ingerir` serve, e o `enviar` recusa. */
export function saidaQueSoIngere(bd: ClienteSql, log?: Logger): Pick<Saida, "ingerir"> {
  return new Saida({
    bd,
    meta: SEM_META,
    destinatario: SEM_DESTINATARIO,
    guarda: null,
    freeTier: null,
    ...(log === undefined ? {} : { log }),
  });
}

export interface DependenciasDoEstagio {
  /** O tenant do canal, ou `null` sem canal. Lança se a base falhar. */
  readonly tenantDe: (phoneNumberId: string) => Promise<string | null>;
  /** Corre o trabalho numa ligação `kamba_app` com o contexto do tenant. */
  readonly comTenant: <T>(tenantId: string, trabalho: (bd: ClienteSql) => Promise<T>) => Promise<T>;
  /** O `Saida` sobre essa ligação. Por omissão, o `saidaQueSoIngere`. */
  readonly saidaDe?: (bd: ClienteSql) => Pick<Saida, "ingerir">;
  /**
   * O registo do processo, que o `Saida` usa para os dois avisos dele:
   * `status_sem_mensagem` e `pricing_desconhecido`. Sem ele, um `statuses` que
   * chega antes de o nosso `wamid` estar gravado perde-se **calado**.
   */
  readonly log?: Logger;
}

/** O braço `outbound` da entrada: um `statuses` → `Saida.ingerir`. */
export function estagioDosStatuses(
  deps: DependenciasDoEstagio,
): (evento: EventoDeEntrada) => Promise<DesfechoDoEstagio> {
  const saidaDe = deps.saidaDe ?? ((bd: ClienteSql) => saidaQueSoIngere(bd, deps.log));
  return async (evento) => {
    const estado = evento.estado;
    const phoneNumberId = evento.phoneNumberId;
    if (estado === undefined || phoneNumberId === null) return "sem_estado";
    if (!ESTADOS_DA_META.includes(estado.estado as Estado)) return "estado_desconhecido";
    const tenantId = await deps.tenantDe(phoneNumberId);
    if (tenantId === null) return "canal_desconhecido";
    const r = await deps.comTenant(tenantId, (bd) =>
      saidaDe(bd).ingerir(tenantId, estado.wamid, estado.estado as Estado, estado.pricing, phoneNumberId),
    );
    return r.avancou ? "avancou" : "nao_avancou";
  };
}

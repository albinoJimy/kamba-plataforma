/**
 * O que se faz com um corpo de webhook depois de ele sair da fila (KAM-013).
 *
 * É a decisão toda, e é testável sem fila: recebe um `TrabalhoDeEntrada` e um
 * cliente SQL, e devolve o que aconteceu. Quem traduz o BullMQ para isto é o
 * `trabalhador.ts`; quem monta o processo é
 * `services/worker-canal/src/entrada.ts`.
 *
 * ## Os três caminhos
 *
 * 1. **Corpo que não faz `parse`** → quarentena com `json_invalido`, e o *job*
 *    **conclui com êxito**. É a letra do critério 6: «JSON inválido com
 *    assinatura válida: 200 e quarentena; nunca 5xx (evita *retry storm*)». Um
 *    erro lançado aqui fazia o BullMQ repetir seis vezes um corpo que nunca vai
 *    melhorar, e a Meta re-entregar por cima durante sete dias.
 * 2. **Corpo que explode em eventos** → um registo por evento, e encaminhamento
 *    só dos que são novos.
 * 3. **Falha da base** → lança. É a única classe de erro que merece
 *    retentativa, porque é a única que uma segunda tentativa pode resolver.
 *
 * ## Registar e encaminhar não são atómicos, e o desenho assume isso
 *
 * O encaminhamento sai deste processo (o CHR é KAM-014) e o registo é uma
 * escrita local: não há transacção que cubra os dois. Um `kill -9` entre eles
 * deixa um evento registado e não tratado, e na entrega seguinte o
 * `ON CONFLICT` não devolve linha — isto é, pareceria um duplicado. Por isso o
 * caminho do duplicado **pergunta à base** se aquele evento está por encaminhar
 * (`SQL_POR_ENCAMINHAR`), e só conclui «duplicado» quando ele já tem
 * `processado_at`. É a razão de ser dessa coluna.
 *
 * A consequência é que um encaminhamento pode acontecer **mais de uma vez**, e
 * é por isso que todo o tratador de destino tem de ser idempotente — o que já
 * era verdade por outro motivo: as garantias de entrega do BullMQ são
 * **NÃO VERIFICADO** (`evidencia/E4` §2.10).
 */

import { idOpaco } from "../logger/index.ts";
import {
  SQL_MARCAR_ENCAMINHADO,
  SQL_POR_ENCAMINHAR,
  SQL_QUARENTENA,
  SQL_REGISTAR,
} from "./consultas.ts";
import { type Destino, type TrabalhoDeEntrada, destinoDe } from "./contrato.ts";
import {
  type EventoDeEntrada,
  type EventoEmQuarentena,
  explodir,
} from "./explosao.ts";

/** O mínimo de um cliente SQL de que este módulo depende. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[] }>;
}

/**
 * Tecto do `payload` da quarentena, em caracteres de base64.
 *
 * **O mesmo do `CHECK` da revisão `0008`**, e está nos dois sítios de
 * propósito: no `CHECK` para que nenhuma outra via de escrita o ignore, e aqui
 * para que um corpo grande entre com `payload` nulo em vez de a inserção violar
 * a restrição, o *job* falhar e o BullMQ repetir — durante sete dias, com a
 * Meta a re-entregar por cima. O `db/tests_entrada` prende os dois números.
 */
export const PAYLOAD_MAXIMO = 262_144;

/** Para onde cada evento novo vai. Um método por destino do dicionário §3.12. */
export interface Encaminhador {
  /** `message` e `echo`: resolução de canal, contacto e modo (KAM-014). */
  chr(evento: EventoDeEntrada): Promise<void>;
  /** `statuses`: *stage* de *outbound* (KAM-015). **Nunca o AGR.** */
  outbound(evento: EventoDeEntrada): Promise<void>;
  /** `history` e `smb_app_state_sync`: só ingestão (KAM-017). Nunca resposta. */
  ingestao(evento: EventoDeEntrada): Promise<void>;
  /** `account_update`, qualidade e templates: *stage* de gestão de canal. */
  gestaoDeCanal(evento: EventoDeEntrada): Promise<void>;
}

/** O que aconteceu a um evento. */
export type Desfecho = "registado" | "duplicado" | "quarentena";

/** O resultado de tratar um corpo. */
export interface Resultado {
  readonly registados: number;
  readonly duplicados: number;
  readonly emQuarentena: number;
  /** Os destinos a que se entregou, para o teste do critério 8. */
  readonly destinos: readonly Destino[];
}

/**
 * Entrega um evento ao destino do seu `kind`.
 *
 * Mapa total e `switch` exaustivo: um `kind` novo sem destino é um erro de
 * compilação, e não um evento entregue onde calhar. O `quarentena` não tem
 * método no `Encaminhador` porque um evento com esse destino não chega aqui —
 * vai por `unrouted_events`, que é outro caminho.
 */
export async function encaminhar(
  evento: EventoDeEntrada,
  encaminhador: Encaminhador,
): Promise<Destino> {
  const destino = destinoDe(evento.kind);
  switch (destino) {
    case "chr":
      await encaminhador.chr(evento);
      return destino;
    case "outbound":
      await encaminhador.outbound(evento);
      return destino;
    case "ingestao":
      await encaminhador.ingestao(evento);
      return destino;
    case "gestao_de_canal":
      await encaminhador.gestaoDeCanal(evento);
      return destino;
    case "quarentena":
      // Um evento com destino de quarentena não devia chegar ao
      // `encaminhar` — o `explodir` devolve-o na outra lista. Se chegar, não
      // se entrega a ninguém: não há tratador a quem um `invalido` sirva.
      return destino;
  }
}

function primeiroId(linhas: readonly Record<string, unknown>[]): string | null {
  const id = linhas[0]?.id;
  return typeof id === "string" ? id : null;
}

/**
 * Registra um evento e encaminha-o se for preciso.
 *
 * Devolve o desfecho e, quando encaminhou, o destino.
 */
export async function registarEvento(
  bd: ClienteSql,
  evento: EventoDeEntrada,
  encaminhador: Encaminhador,
): Promise<{ readonly desfecho: Desfecho; readonly destino: Destino | null }> {
  const inserido = await bd.query(SQL_REGISTAR, [
    evento.kind,
    evento.eventKey,
    evento.wabaId,
    evento.phoneNumberId,
  ]);
  let id = primeiroId(inserido.rows);
  let desfecho: Desfecho = "registado";

  if (id === null) {
    // Já cá estava. Pode ser um duplicado verdadeiro, ou o evento que ficou
    // registado e sem encaminhar quando o processo morreu entre as duas
    // escritas. Ver a docstring do módulo.
    const pendente = await bd.query(SQL_POR_ENCAMINHAR, [evento.kind, evento.eventKey]);
    id = primeiroId(pendente.rows);
    if (id === null) return { desfecho: "duplicado", destino: null };
    desfecho = "duplicado";
  }

  const destino = await encaminhar(evento, encaminhador);
  await bd.query(SQL_MARCAR_ENCAMINHADO, [id]);
  return { desfecho, destino };
}

/**
 * Põe um evento em quarentena.
 *
 * `payload` é o corpo em base64, ou `null` quando excede `PAYLOAD_MAXIMO`.
 * Guardar nada é melhor do que a inserção falhar: sem a linha não há alerta, e
 * sem alerta ninguém sabe que houve um corpo que não encaixou.
 */
export async function porEmQuarentena(
  bd: ClienteSql,
  evento: EventoEmQuarentena,
  payload: string | null,
): Promise<void> {
  await bd.query(SQL_QUARENTENA, [
    evento.kind,
    evento.eventKey,
    evento.wabaId,
    evento.phoneNumberId,
    evento.motivo,
    payload !== null && payload.length <= PAYLOAD_MAXIMO ? payload : null,
  ]);
}

/** O que o `tratarCorpo` escreve no registo. Só campos da *allowlist*. */
export interface Registo {
  (campos: {
    readonly outcome: string;
    readonly msg_id?: string;
    readonly wa_type?: string;
    readonly error_code?: string;
    readonly latency_ms?: number;
  }): void;
}

/**
 * Trata um corpo: explode, registra, encaminha e põe em quarentena.
 *
 * Não lança por nada que venha do corpo. Lança o que vier da base, que é o que
 * uma retentativa pode resolver.
 */
export async function tratarCorpo(
  bd: ClienteSql,
  trabalho: TrabalhoDeEntrada,
  encaminhador: Encaminhador,
  resumoDoCorpo: string,
  registar?: Registo,
): Promise<Resultado> {
  let corpo: unknown = null;
  let invalido = false;
  try {
    // O base64 e o `parse` no mesmo `try`: um base64 inválido e um JSON
    // inválido são o mesmo caso para quem trata — o corpo não se consegue ler
    // —, e dividi-los em dois motivos de quarentena dava dois alertas para a
    // mesma causa.
    corpo = JSON.parse(Buffer.from(trabalho.corpo, "base64").toString("utf8"));
  } catch {
    invalido = true;
  }

  if (invalido) {
    // `json_invalido`: o critério 6. A `event_key` é o resumo do corpo, pelo
    // que a re-entrega do mesmo corpo inválido não cria uma segunda linha.
    const evento: EventoEmQuarentena = {
      kind: "invalido",
      eventKey: `k_${resumoDoCorpo.slice(0, 32)}`,
      motivo: "json_invalido",
      wabaId: null,
      phoneNumberId: null,
    };
    await porEmQuarentena(bd, evento, trabalho.corpo);
    registar?.({ outcome: "quarentena", error_code: "json_invalido" });
    return { registados: 0, duplicados: 0, emQuarentena: 1, destinos: [] };
  }

  const { eventos, quarentena } = explodir(corpo, resumoDoCorpo);

  let registados = 0;
  let duplicados = 0;
  const destinos: Destino[] = [];

  for (const evento of eventos) {
    const { desfecho, destino } = await registarEvento(bd, evento, encaminhador);
    if (desfecho === "registado") registados += 1;
    else duplicados += 1;
    if (destino !== null) destinos.push(destino);
    registar?.({
      outcome: `entrada_${desfecho}`,
      // O `wamid` **nunca** vai em claro para um registo: leva o número do
      // interlocutor codificado em base64 (`docs/logs.md` §2.1), e a
      // *allowlist* recusa-o. O `idOpaco` é o que o §3.10 fixa para isto.
      msg_id: idOpaco(evento.eventKey),
      ...(evento.waType === null ? {} : { wa_type: evento.waType }),
    });
  }

  for (const evento of quarentena) {
    await porEmQuarentena(bd, evento, trabalho.corpo);
    registar?.({ outcome: "quarentena", error_code: evento.motivo });
  }

  return {
    registados,
    duplicados,
    emQuarentena: quarentena.length,
    destinos,
  };
}

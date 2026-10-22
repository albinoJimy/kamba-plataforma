/**
 * A emissão de `channel.updated` e de `channel.inactivity_warning` (KAM-017,
 * critérios 5 e 6).
 *
 * A forma é a do `chr/eventos.ts` e a do `modos/eventos.ts`: mapeia o que temos
 * para o payload que o contrato publicado exige, valida-o **antes** de qualquer
 * escrita, e chama `platform.evt_emitir` com o papel `kamba_app` e contexto de
 * tenant.
 *
 * ## Os dois tipos já existiam, e **este é o primeiro emissor**
 *
 * `contratos/eventos/channel.updated/` e
 * `contratos/eventos/channel.inactivity_warning/` existem com `v1` e `v2`
 * desde o KAM-007/KAM-159, e nenhum é deste ticket. O que não existia era
 * **quem os emite**: uma busca por `channel.updated` em `packages/core-ts/src`
 * antes deste ticket só dava comentários. Portanto não há contrato a
 * acrescentar, e dizê-lo é melhor do que inventar um.
 *
 * ## O agregado é o `tenant` e não o canal, e isso vem do contrato
 *
 * Os dois esquemas têm `agregado.tipo` com `const: "tenant"`. Não é o que se
 * esperaria de um evento de canal — e não se mudou: apertar ou alargar um
 * contrato publicado é KAM-007, e fazê-lo aqui era decidir por outro ticket
 * **e** quebrar a compatibilidade que o *gate* 7 prova. O canal identifica-se
 * no payload, pelo `phone_number_id`, que é o que os dois esquemas pedem.
 *
 * Consequência que vale a pena escrever: o `agregado.seq` passa a contar por
 * *tenant* e não por canal, pelo que dois canais do mesmo *tenant* partilham a
 * sequência. Para estes dois eventos isso não tem consumidor nenhum que o note
 * (não há `exige_ordem` para eles), e está declarado em
 * `docs/dividas-documentais.md`.
 *
 * ## A validação corre **antes** do SQL
 *
 * É a regra do KAM-007 (`eventos/contratos.ts`): o `evt_emitir` grava o
 * envelope e **não** valida o payload contra o contrato. Validar depois é
 * descobrir o defeito com o evento já publicado.
 *
 * ## As assinaturas sao **as da porta `Emitir`**, e isso custou um achado
 *
 * As duas funcoes levam um `_channelId` que nao usam e um `motivo` que, no
 * aviso, e sempre `null`. Nao e desleixo: e o que as torna atribuiveis a porta
 * `Emitir` do `contrato.ts`, que tem **cinco** parametros com o `channelId` em
 * terceiro.
 *
 * A primeira versao tinha quatro e tres parametros, sem o `channelId`, e **nem
 * o compilador nem o contrato apanhavam**: o TypeScript admite atribuir uma
 * funcao de menos parametros a um tipo de mais, e o `motivo` do
 * `channel.updated/v2.schema.json` e `string` livre. O resultado, medido pela
 * revisao adversarial, era um `channel.updated` publicado com o **UUID do
 * canal** no `phone_number_id` e o `phone_number_id` no `motivo` — e o
 * consumidor do KAM-115 a procurar um numero onde estava um UUID. Ficava
 * latente porque todos os testes substituiam as portas por lambdas.
 *
 * O `motivo` e `string | null` pela mesma razao — e a porta que o declara —, e
 * um `null` no `channel.updated` **levanta** em vez de publicar um payload que
 * o `required` do esquema recusa.
 *
 * ## Privacidade
 *
 * Os dois payloads levam o `phone_number_id`, que é o identificador **da
 * Meta para o nosso próprio número de negócio** — não é o telefone de um
 * titular. Não levam telefone de cliente, BSUID, nome nem conteúdo: é o DoD
 * «Privacidade» do ticket e o ADR-010, e é por isso que os dois esquemas são
 * `classe_pii: "P0"`.
 */

import type {
  PayloadChannelInactivityWarningV2,
  PayloadChannelUpdatedV2,
} from "@kamba/contracts";

import { validarPayload } from "../eventos/contratos.ts";
import type { ClienteSql } from "./contrato.ts";

/** O tipo do evento de actualização de canal. */
export const TIPO_CHANNEL_UPDATED = "channel.updated";
/** O tipo do aviso de inactividade. */
export const TIPO_INACTIVITY_WARNING = "channel.inactivity_warning";
/** A versão que os dois contratos publicam, e que este módulo emite. */
export const VERSAO_DOS_EVENTOS = 2;
/**
 * O tipo de agregado dos dois esquemas.
 *
 * `tenant`, por imposição do `const` dos contratos. Ver a nota do módulo.
 */
export const AGREGADO_DOS_EVENTOS = "tenant";

/**
 * O SQL da emissão. O mesmo de todos os módulos que emitem.
 *
 * Parâmetros: tipo, versão, `tenant_id`, tipo do agregado, id do agregado,
 * payload em `jsonb`.
 */
export const SQL_EMITIR = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb
  ) AS event_id
`;

/** O payload de um `channel.updated`. */
export function payloadDoCanal(
  phoneNumberId: string,
  motivo: string,
): PayloadChannelUpdatedV2 {
  return { phone_number_id: phoneNumberId, motivo };
}

/** O payload de um `channel.inactivity_warning`. */
export function payloadDoAviso(
  phoneNumberId: string,
): PayloadChannelInactivityWarningV2 {
  return { phone_number_id: phoneNumberId };
}

async function emitir(
  cliente: ClienteSql,
  tipo: string,
  tenantId: string,
  payload: unknown,
): Promise<string> {
  validarPayload(tipo, VERSAO_DOS_EVENTOS, payload);
  const resultado = await cliente.query<{ event_id?: unknown }>(SQL_EMITIR, [
    tipo,
    VERSAO_DOS_EVENTOS,
    tenantId,
    AGREGADO_DOS_EVENTOS,
    tenantId,
    JSON.stringify(payload),
  ]);
  const id = resultado.rows[0]?.event_id;
  if (typeof id !== "string") {
    throw new Error(
      `platform.evt_emitir nao devolveu um event_id: o evento \`${tipo}\` ` +
        "pode nao ter sido escrito no outbox",
    );
  }
  return id;
}

/**
 * Emite o `channel.updated`. Devolve o `event_id`.
 *
 * Corre na transacção de quem chama — é o que a assinatura do `cliente`
 * garante — e por isso o evento e a mudança de estado do canal confirmam
 * juntos. A ordem importa e é a que o KAM-018 pagou: **emite-se depois de
 * escrever e conta-se depois de emitir**, porque as duas escritas vivem na
 * mesma transacção e um contador em memória não é desfeito por um `ROLLBACK`.
 *
 * @throws {PayloadInvalidoError} se o payload não bater com o contrato, e isso
 *   é antes de qualquer escrita.
 */
export async function emitirCanalActualizado(
  cliente: ClienteSql,
  tenantId: string,
  _channelId: string,
  phoneNumberId: string,
  motivo: string | null,
): Promise<string> {
  if (motivo === null) {
    throw new TypeError(
      "channel.updated exige um motivo: o v2.schema.json tem-no em `required`, " +
        "e um payload sem ele e recusado pelo validarPayload",
    );
  }
  return emitir(
    cliente,
    TIPO_CHANNEL_UPDATED,
    tenantId,
    payloadDoCanal(phoneNumberId, motivo),
  );
}

/**
 * Emite o `channel.inactivity_warning`. Devolve o `event_id`.
 *
 * **Este ticket emite o evento e pára aí.** A entrega ao dono por canal
 * alternativo — e-mail ou *push* — é **KAM-115**, e o próprio critério 6 o diz:
 * «a entrega ao dono por canal alternativo depende de mecanismo ainda sem
 * ticket». Emitir e não entregar não é meia obra: é o barramento a fazer o que
 * o ADR-009 manda, e o consumidor nasce com o ticket que o tem.
 */
export async function emitirAvisoDeInactividade(
  cliente: ClienteSql,
  tenantId: string,
  _channelId: string,
  phoneNumberId: string,
  _motivo: string | null = null,
): Promise<string> {
  return emitir(
    cliente,
    TIPO_INACTIVITY_WARNING,
    tenantId,
    payloadDoAviso(phoneNumberId),
  );
}

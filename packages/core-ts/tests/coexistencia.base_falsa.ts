/**
 * Uma base falsa para as baterias da coexistência no *gate* 4 (KAM-017).
 *
 * **O que esta base prova e o que ela não prova**, dito à cabeça, pela mesma
 * razão que a `modos.base_falsa.ts` o escreveu: uma base falsa devolve o que se
 * lhe mandou devolver, e um teste de concorrência ou de isolamento sobre ela
 * não prova concorrência nem isolamento nenhum. O que ela prova é a **ordem** e
 * a **decisão** — que o `wamid` é consultado antes de se tocar no relógio, que
 * o passo repetido não soma, que o 2593109 não passa por `falhado` — e isso é
 * exactamente o que não se consegue ver numa base real sem instrumentar o
 * servidor.
 *
 * O *no-op* do passo contra um predicado verdadeiro, a unicidade por canal, a
 * reposição da reconexão e a RLS provam-se em `tests_bd/coexistencia.bd.test.ts`,
 * contra o PostgreSQL 18.6 do *gate* 8.
 *
 * ## Modela o que a base **impõe**, e isso foi a lição do KAM-016
 *
 * «Se o teu duplo de base não impõe o que a base impõe, o que ele mede é o teu
 * código a falar consigo.» Por isso este duplo impõe três coisas que a `0018`
 * impõe: o predicado `estado = 'a_sincronizar'` do passo, o
 * `NOT (passo = ANY (passos_feitos))`, e o `desligado_em IS NULL` do registo do
 * desligamento. Sem elas, metade dos testes do critério 3 e do critério 5
 * ficavam verdes por o código nunca ser contrariado.
 */

import {
  SQL_ABRIR,
  SQL_ALERTAR_VENCIDAS,
  SQL_AVISAR_INACTIVOS,
  SQL_CANAL_POR_NUMERO,
  SQL_CONCLUIR,
  SQL_CONCLUIR_SEM_HISTORICO,
  SQL_DESLIGAR_CANAL,
  SQL_FALHAR_VENCIDAS,
  SQL_MARCAR_PASSO,
  SQL_MARCAR_SINCRONIZADO,
  SQL_POR_CANAL,
  SQL_REGISTAR_DESLIGAMENTO,
  SQL_REGISTAR_ECHO,
} from "../src/coexistencia/consultas.ts";
import type { Estado, Passo } from "../src/coexistencia/contrato.ts";
import { SQL_POR_WAMID } from "../src/outbound/consultas.ts";

/** Uma instrução vista pela base falsa: o texto e os parâmetros. */
export interface Vista {
  readonly sql: string;
  readonly parametros: readonly unknown[];
}

/** A linha de `channel_coexistence` na base falsa. */
export interface Linha {
  id: string;
  estado: Estado;
  passos_feitos: Passo[];
  iniciado_em: Date;
  prazo_em: Date;
  alertado_em: Date | null;
  concluido_em: Date | null;
  contactos_vistos: number;
  mensagens_vistas: number;
  meta_error_code: number | null;
  ultimo_echo_em: Date | null;
  avisado_em: Date | null;
  motivo_desligamento: string | null;
  desligado_em: Date | null;
}

/** O canal na base falsa. */
export interface Canal {
  channel_id: string;
  channel_mode: string;
  estado: string;
  phone_number_id: string;
  coexistence_synced_at: Date | null;
  last_account_update_at: Date | null;
}

function chave(tenantId: unknown, channelId: unknown): string {
  return `${String(tenantId)}|${String(channelId)}`;
}

/**
 * Uma base falsa que entende as treze consultas de `coexistencia/consultas.ts`
 * mais o `SQL_POR_WAMID` do KAM-015.
 *
 * Reconhece-as por **igualdade com as constantes importadas** e não por um
 * fragmento copiado: renomear uma consulta ou mudar-lhe o corpo não deixa este
 * duplo a responder ao que já não existe. É a escolha que a `modos.base_falsa`
 * fez, levada um passo à frente — ali compara-se um fragmento, aqui a cadeia
 * inteira.
 */
export class BaseFalsa {
  readonly vistas: Vista[] = [];
  readonly linhas = new Map<string, Linha>();
  readonly canais = new Map<string, Canal>();
  /** Os `wamid` que estão em `outbound_messages`. */
  readonly nossos = new Set<string>();
  /** Os eventos emitidos, na ordem. */
  readonly eventos: { tipo: string; motivo: string | null }[] = [];
  #contador = 0;

  semearCanal(tenantId: string, canal: Partial<Canal> & { channel_id: string }): Canal {
    const completo: Canal = {
      channel_mode: "coexistencia",
      estado: "ativo",
      phone_number_id: `pnid-${canal.channel_id}`,
      coexistence_synced_at: null,
      last_account_update_at: null,
      ...canal,
    };
    this.canais.set(chave(tenantId, completo.channel_id), completo);
    return completo;
  }

  semear(tenantId: string, channelId: string, troca: Partial<Linha> = {}): Linha {
    const agora = new Date("2026-10-01T00:00:00Z");
    this.#contador += 1;
    const linha: Linha = {
      id: `coex-${this.#contador}`,
      estado: "a_sincronizar",
      passos_feitos: [],
      iniciado_em: agora,
      prazo_em: new Date(agora.getTime() + 24 * 60 * 60 * 1_000),
      alertado_em: null,
      concluido_em: null,
      contactos_vistos: 0,
      mensagens_vistas: 0,
      meta_error_code: null,
      ultimo_echo_em: null,
      avisado_em: null,
      motivo_desligamento: null,
      desligado_em: null,
      ...troca,
    };
    this.linhas.set(chave(tenantId, channelId), linha);
    return linha;
  }

  ver(tenantId: string, channelId: string): Linha | undefined {
    return this.linhas.get(chave(tenantId, channelId));
  }

  async query<T = Record<string, unknown>>(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly T[] }> {
    return this.#responder(sql, parametros) as { readonly rows: readonly T[] };
  }

  /**
   * O corpo, sem o genérico.
   *
   * Separado do `query` porque o `ClienteSql` deste módulo declara
   * `query<T = Record<string, unknown>>` — a mesma forma do KAM-015 e do
   * KAM-021 —, e um corpo que devolvesse `Record<string, unknown>` directamente
   * não é atribuível a `T`: o compilador não sabe que quem chama pede sempre o
   * que esta base dá. A conversão fica **num sítio só**, aqui.
   */
  #responder(
    sql: string,
    parametros: readonly unknown[],
  ): { readonly rows: readonly Record<string, unknown>[] } {
    this.vistas.push({ sql, parametros });

    if (sql === SQL_CANAL_POR_NUMERO) {
      const [tenantId, numero] = parametros;
      for (const [k, canal] of this.canais) {
        if (k.startsWith(`${String(tenantId)}|`) && canal.phone_number_id === numero) {
          return {
            rows: [
              {
                channel_id: canal.channel_id,
                channel_mode: canal.channel_mode,
                estado: canal.estado,
              },
            ],
          };
        }
      }
      return { rows: [] };
    }

    if (sql === SQL_ABRIR) {
      const [tenantId, channelId, iniciado, prazo] = parametros;
      const k = chave(tenantId, channelId);
      const existente = this.linhas.get(k);
      if (existente === undefined) {
        const nova = this.semear(String(tenantId), String(channelId), {
          iniciado_em: iniciado as Date,
          prazo_em: prazo as Date,
        });
        return { rows: [{ id: nova.id }] };
      }
      // O `DO UPDATE`: **repoe**, e e isto que o criterio 9 pede.
      existente.estado = "a_sincronizar";
      existente.passos_feitos = [];
      existente.iniciado_em = iniciado as Date;
      existente.prazo_em = prazo as Date;
      existente.alertado_em = null;
      existente.concluido_em = null;
      existente.contactos_vistos = 0;
      existente.mensagens_vistas = 0;
      existente.meta_error_code = null;
      existente.avisado_em = null;
      existente.motivo_desligamento = null;
      existente.desligado_em = null;
      return { rows: [{ id: existente.id }] };
    }

    if (sql === SQL_POR_CANAL) {
      const linha = this.linhas.get(chave(parametros[0], parametros[1]));
      return { rows: linha === undefined ? [] : [{ ...linha }] };
    }

    if (sql === SQL_MARCAR_PASSO) {
      const [tenantId, channelId, passo, contactos, mensagens] = parametros;
      const linha = this.linhas.get(chave(tenantId, channelId));
      // **Os dois predicados da `0018`**, e sem eles este duplo media o codigo
      // a falar consigo: o estado e o passo ja feito.
      if (
        linha === undefined ||
        linha.estado !== "a_sincronizar" ||
        linha.passos_feitos.includes(passo as Passo)
      ) {
        return { rows: [] };
      }
      linha.passos_feitos = [...linha.passos_feitos, passo as Passo];
      linha.contactos_vistos += Number(contactos);
      linha.mensagens_vistas += Number(mensagens);
      return { rows: [{ passos_feitos: linha.passos_feitos }] };
    }

    if (sql === SQL_CONCLUIR) {
      const [tenantId, channelId, agora] = parametros;
      const linha = this.linhas.get(chave(tenantId, channelId));
      if (
        linha === undefined ||
        linha.estado !== "a_sincronizar" ||
        !linha.passos_feitos.includes("contactos") ||
        !linha.passos_feitos.includes("historico")
      ) {
        return { rows: [] };
      }
      linha.estado = "sincronizado";
      linha.concluido_em = agora as Date;
      return { rows: [{ id: linha.id }] };
    }

    if (sql === SQL_CONCLUIR_SEM_HISTORICO) {
      const [tenantId, channelId, agora, codigo] = parametros;
      const linha = this.linhas.get(chave(tenantId, channelId));
      if (linha === undefined || linha.estado !== "a_sincronizar") {
        return { rows: [] };
      }
      linha.estado = "sincronizado_sem_historico";
      linha.concluido_em = agora as Date;
      linha.meta_error_code = Number(codigo);
      return { rows: [{ id: linha.id }] };
    }

    if (sql === SQL_REGISTAR_ECHO) {
      const [tenantId, channelId, agora] = parametros;
      const linha = this.linhas.get(chave(tenantId, channelId));
      if (linha === undefined) return { rows: [] };
      const novo = agora as Date;
      // O `GREATEST`: dois *echoes* fora de ordem nao recuam o relogio.
      linha.ultimo_echo_em =
        linha.ultimo_echo_em === null || linha.ultimo_echo_em < novo
          ? novo
          : linha.ultimo_echo_em;
      linha.avisado_em = null;
      return { rows: [{ ultimo_echo_em: linha.ultimo_echo_em }] };
    }

    if (sql === SQL_REGISTAR_DESLIGAMENTO) {
      const [tenantId, channelId, motivo, agora] = parametros;
      const linha = this.linhas.get(chave(tenantId, channelId));
      // O `desligado_em IS NULL`: a segunda passagem nao escreve.
      if (linha === undefined || linha.desligado_em !== null) return { rows: [] };
      linha.motivo_desligamento = String(motivo);
      linha.desligado_em = agora as Date;
      return { rows: [{ id: linha.id }] };
    }

    if (sql === SQL_DESLIGAR_CANAL) {
      const [tenantId, channelId, agora] = parametros;
      const canal = this.canais.get(chave(tenantId, channelId));
      // O `estado IN ('pendente','ativo','restrito')`: um canal ja desligado
      // (ou encerrado, ou suspenso) nao transita.
      if (
        canal === undefined ||
        !["pendente", "ativo", "restrito"].includes(canal.estado)
      ) {
        return { rows: [] };
      }
      canal.estado = "desligado";
      const novo = agora as Date;
      canal.last_account_update_at =
        canal.last_account_update_at === null || canal.last_account_update_at < novo
          ? novo
          : canal.last_account_update_at;
      return { rows: [{ phone_number_id: canal.phone_number_id }] };
    }

    if (sql === SQL_MARCAR_SINCRONIZADO) {
      const [tenantId, channelId, agora] = parametros;
      const canal = this.canais.get(chave(tenantId, channelId));
      if (canal === undefined) return { rows: [] };
      const novo = agora as Date;
      canal.coexistence_synced_at =
        canal.coexistence_synced_at === null || canal.coexistence_synced_at < novo
          ? novo
          : canal.coexistence_synced_at;
      return { rows: [{ coexistence_synced_at: canal.coexistence_synced_at }] };
    }

    if (sql === SQL_ALERTAR_VENCIDAS) {
      const [corte, agora] = parametros;
      const fora: Record<string, unknown>[] = [];
      for (const [k, linha] of this.linhas) {
        const [tenantId, channelId] = k.split("|");
        if (
          linha.estado === "a_sincronizar" &&
          linha.alertado_em === null &&
          linha.iniciado_em <= (corte as Date)
        ) {
          linha.alertado_em = agora as Date;
          fora.push({ id: linha.id, tenant_id: tenantId, channel_id: channelId });
        }
      }
      return { rows: fora };
    }

    if (sql === SQL_FALHAR_VENCIDAS) {
      const [agora] = parametros;
      const fora: Record<string, unknown>[] = [];
      for (const [k, linha] of this.linhas) {
        const [tenantId, channelId] = k.split("|");
        if (linha.estado === "a_sincronizar" && linha.prazo_em <= (agora as Date)) {
          linha.estado = "falhado";
          fora.push({ id: linha.id, tenant_id: tenantId, channel_id: channelId });
        }
      }
      return { rows: fora };
    }

    if (sql === SQL_AVISAR_INACTIVOS) {
      const [corte, agora] = parametros;
      const fora: Record<string, unknown>[] = [];
      for (const [k, linha] of this.linhas) {
        const [tenantId, channelId] = k.split("|");
        const relogio = linha.ultimo_echo_em ?? linha.iniciado_em;
        if (
          ["sincronizado", "sincronizado_sem_historico"].includes(linha.estado) &&
          linha.desligado_em === null &&
          linha.avisado_em === null &&
          relogio <= (corte as Date)
        ) {
          linha.avisado_em = agora as Date;
          fora.push({ id: linha.id, tenant_id: tenantId, channel_id: channelId });
        }
      }
      return { rows: fora };
    }

    if (sql === SQL_POR_WAMID) {
      const [, wamid] = parametros;
      return this.nossos.has(String(wamid))
        ? { rows: [{ id: "om-1", state: "sent", kind: "text", pricing: null }] }
        : { rows: [] };
    }

    throw new Error(`a base falsa nao conhece esta instrucao:\n${sql}`);
  }

  /** As instruções vistas, por ordem, reconhecidas pelo nome curto. */
  nomes(): string[] {
    const porSql = new Map<string, string>([
      [SQL_ABRIR, "abrir"],
      [SQL_POR_CANAL, "ler"],
      [SQL_MARCAR_PASSO, "marcar_passo"],
      [SQL_CONCLUIR, "concluir"],
      [SQL_CONCLUIR_SEM_HISTORICO, "concluir_sem_historico"],
      [SQL_REGISTAR_ECHO, "registar_echo"],
      [SQL_REGISTAR_DESLIGAMENTO, "registar_desligamento"],
      [SQL_DESLIGAR_CANAL, "desligar_canal"],
      [SQL_MARCAR_SINCRONIZADO, "marcar_sincronizado"],
      [SQL_ALERTAR_VENCIDAS, "alertar"],
      [SQL_FALHAR_VENCIDAS, "falhar"],
      [SQL_AVISAR_INACTIVOS, "avisar"],
      [SQL_CANAL_POR_NUMERO, "canal"],
      [SQL_POR_WAMID, "por_wamid"],
    ]);
    return this.vistas.map((v) => porSql.get(v.sql) ?? "desconhecida");
  }
}

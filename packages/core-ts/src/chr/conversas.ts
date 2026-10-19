/**
 * A conversa entre um contacto e um canal (KAM-014, revisão `0009`).
 *
 * Duas responsabilidades, e as duas correm com papéis diferentes:
 *
 * 1. **Abrir ou reabrir** a conversa quando chega uma entrada — com
 *    `kamba_app`, dentro de `comTenant` (a tabela tem RLS `FORCE`).
 * 2. **Reapontar** as conversas de um contacto absorvido numa fusão — com
 *    `kamba_identity`, **dentro** da transacção da fusão, pelo gancho
 *    `onContactMerge` que o KAM-008 expõe.
 *
 * ## Porque é que a fusão corre com o papel da identidade
 *
 * O `docs/identidade.md` §4 garante que, se um gancho de fusão falhar, **nada
 * fica** — os endpoints, as DEK, a lápide e os ganchos são uma só transacção.
 * Essa transacção é aberta pelo módulo de identidade, na ligação dele, com o
 * contexto de tenant dele. Reapontar as conversas por fora dela quebrava a
 * atomicidade: um `kill -9` entre a fusão e o reapontamento deixava conversas
 * penduradas num contacto que já é lápide. A revisão `0009` concede por isso ao
 * `kamba_identity` `SELECT` em sete colunas e `UPDATE` em quatro — e nem
 * `INSERT` nem `DELETE`.
 *
 * ## O que acontece quando as duas conversas são do mesmo canal
 *
 * A `conversations_tenant_contact_channel_uq` recusa duas conversas do mesmo
 * (tenant, contacto, canal). Se o contacto que **fica** já tiver conversa no
 * canal do absorvido, as duas não se podem juntar numa linha: dobram-se os
 * tempos na que fica — o `last_inbound_at`, a janela e a última actividade
 * humana, cada um pelo mais tardio dos dois — e a do absorvido fica onde está,
 * pendurada na lápide, que continua a existir com `merged_into` a apontar para
 * quem a absorveu.
 *
 * **Isto deixa uma linha a apontar para um contacto que já não é ninguém, e
 * fica dito em vez de escondido.** Não se apaga porque o §2 do dicionário diz
 * «soft delete: estado, nunca `DELETE`» e porque `kamba_identity` não tem
 * `DELETE` nesta tabela; quem apaga é o `kamba_batch`, na retenção (KAM-071). O
 * que se perde é o histórico de uma conversa que passa a estar em duas linhas —
 * e quem seguir `merged_into` chega às duas.
 */

import {
  SQL_ABRIR_CONVERSA,
  SQL_CONVERSAS_A_FUNDIR,
  SQL_DOBRAR_CONVERSA,
  SQL_REPONTAR_CONVERSA,
} from "./consultas.ts";
import { type ClienteDoChr, JANELA_MS, type Modo, MODOS } from "./contrato.ts";

/** A conversa não veio da base na forma esperada. */
export class ConversaIlegivelError extends Error {
  constructor(motivo: string) {
    super(
      `platform.conversations nao respondeu na forma esperada: ${motivo}. ` +
        "A consulta e `SQL_ABRIR_CONVERSA`.",
    );
    this.name = "ConversaIlegivelError";
  }
}

/** Uma conversa, como o CHR a usa. */
export interface Conversa {
  readonly id: string;
  readonly mode: Modo;
}

const MODOS_CONHECIDOS: readonly string[] = MODOS;

function conversaDaLinha(
  linha: Readonly<Record<string, unknown>> | undefined,
): Conversa {
  if (linha === undefined) throw new ConversaIlegivelError("nenhuma linha");
  const id = linha.id;
  const mode = linha.mode;
  if (typeof id !== "string" || id === "") {
    throw new ConversaIlegivelError("o `id` nao veio como texto");
  }
  if (typeof mode !== "string" || !MODOS_CONHECIDOS.includes(mode)) {
    // Um modo que o código não conhece **para** aqui, e não é tratado como o
    // mais parecido: entregar uma mensagem ao AGR por não se reconhecer o modo
    // era o assistente a interromper uma conversa que uma pessoa estava a
    // fazer (`docs/tecnica/01` §10.2).
    throw new ConversaIlegivelError(`modo desconhecido ${JSON.stringify(mode)}`);
  }
  return { id, mode: mode as Modo };
}

/**
 * Abre a conversa, ou empurra a janela se já existia. Precisa de contexto de
 * tenant.
 *
 * `agora` é injectado e não lido de `Date.now()` aqui: é o mesmo instante que
 * fecha a janela, e os testes da matriz de estados precisam de o fixar. Com dois
 * `now()` dentro da mesma instrução, o `conversations_janela_ck` continuava
 * satisfeito mas os dois tempos vinham de leituras diferentes do relógio.
 *
 * Devolve o `id` e o `mode` que a conversa tem **depois** da escrita — e o
 * `mode` não é alterado por esta instrução (`kamba_app` não tem
 * `UPDATE (mode)`): uma entrada que chega não muda quem tem a palavra.
 */
export async function abrirConversa(
  cliente: ClienteDoChr,
  alvo: {
    readonly tenantId: string;
    readonly contactId: string;
    readonly channelId: string;
  },
  agora: Date,
): Promise<Conversa> {
  const fim = new Date(agora.getTime() + JANELA_MS);
  const resultado = await cliente.query(SQL_ABRIR_CONVERSA, [
    alvo.tenantId,
    alvo.contactId,
    alvo.channelId,
    agora,
    fim,
  ]);
  return conversaDaLinha(resultado.rows[0]);
}

/** O que o reapontamento de uma fusão fez. */
export interface ResultadoDaFusao {
  readonly repontadas: number;
  readonly dobradas: number;
}

function tempo(valor: unknown): Date | null {
  if (valor === null || valor === undefined) return null;
  if (valor instanceof Date) return valor;
  if (typeof valor === "string") {
    const data = new Date(valor);
    if (!Number.isNaN(data.getTime())) return data;
  }
  throw new ConversaIlegivelError("um tempo nao veio como data");
}

/**
 * Reaponta para `para` as conversas de `de`. Corre dentro da transacção da fusão.
 *
 * É o corpo do gancho `onContactMerge`. Não trata erros: se lançar, a fusão
 * inteira é desfeita, que é o que o KAM-008 promete e o que se quer — uma fusão
 * cujas conversas não se mudaram é uma fusão que deixou o histórico partido.
 *
 * Escreve **só** pela ligação que recebe, e por isso é seguro repeti-la: a
 * transacção da fusão pode ser retomada depois de uma corrida
 * (`docs/identidade.md` §4), e um efeito fora da base repetia-se com ela.
 */
export async function repontarConversas(
  cliente: ClienteDoChr,
  tenantId: string,
  de: string,
  para: string,
): Promise<ResultadoDaFusao> {
  const resultado = await cliente.query(SQL_CONVERSAS_A_FUNDIR, [para, tenantId, de]);
  let repontadas = 0;
  let dobradas = 0;
  for (const linha of resultado.rows) {
    const idDe = linha.id_de;
    const idPara = linha.id_para;
    if (typeof idDe !== "string") {
      throw new ConversaIlegivelError("o `id` da conversa a fundir nao veio como texto");
    }
    if (typeof idPara !== "string") {
      // Sem colisão: o contacto que fica não tem conversa neste canal.
      await cliente.query(SQL_REPONTAR_CONVERSA, [para, idDe]);
      repontadas += 1;
      continue;
    }
    // Com colisão: dobram-se os tempos na que fica. A do absorvido fica onde
    // está — ver a nota do módulo.
    await cliente.query(SQL_DOBRAR_CONVERSA, [
      tempo(linha.last_inbound_at),
      tempo(linha.window_expires_at),
      tempo(linha.last_human_activity_at),
      idPara,
    ]);
    dobradas += 1;
  }
  return { repontadas, dobradas };
}

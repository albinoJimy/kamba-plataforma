/**
 * O adaptador da Meta para o off-boarding (KAM-210, critério 3): o canal do
 * cliente pela Graph.
 *
 * ## Só duas operações chegam à rede, e nenhuma apaga
 *
 * O encerramento usa duas: **cancelar** a subscrição de *webhooks* do WABA (a fase
 * `canal`) e **refazê-la** (o cancelamento do pedido, e a corrida que o
 * cancelamento ganha). As duas vão ao `subscribed_apps` do WABA pela `Graph` do
 * KAM-016 (`../onboarding/graph.ts`), com o *token* de cliente desse WABA.
 *
 * As duas destrutivas que a porta declara — `apagarWaba` e `apagarNumero` —
 * **levantam sem tocar na rede**: não há neste adaptador caminho nenhum que
 * apague o WABA ou o número do cliente (E1: o cliente é dono dos activos). O
 * guarda da saga (`executarNoCanalDoCliente`) já as recusa antes; esta é a
 * fechadura do lado de quem fala com a Meta, para o dia em que alguém chame a
 * porta sem o guarda. As outras duas da porta (`removerRota`, `numeroDoTenant`)
 * não são deste adaptador: a rota é a linha do CHR, e o número lê-o o
 * onboarding. Levantam também.
 *
 * ## Idempotente do lado de fora
 *
 * O contrato que o KAM-098 deixou: um *crash* entre a chamada e a gravação do
 * passo repete-a, e por isso **um recurso que já não existe é sucesso**. Cancelar
 * a subscrição de um WABA que já não a tem responde, na Graph, com um erro que
 * não está CONFIRMADO (os caminhos da Graph são *proposta*, ver o cabeçalho do
 * `graph.ts`); aqui trata-se como sucesso o **404** — o recurso não está lá —, e
 * qualquer outro erro sobe e a fase fica por concluir. **NÃO VERIFICADO** que a
 * Graph real responda 404 a uma subscrição que já não existe: o `graph.ts` manda
 * ramificar pelo código da Meta, e o código de «já não subscrito» não está lido.
 * Errar para este lado faz a repetição falhar (a fase fica parada, com alerta), e
 * nunca dá por desligado um canal com a subscrição viva — a menos que um 404 venha
 * de outro sítio (um *proxy* mal encaminhado). Confirmar é do credor (KAM-218),
 * antes de ligar o adaptador. Refazer a subscrição é
 * idempotente pela própria Graph (o simulador do KAM-024 modela-o assim).
 *
 * ## O *token* de cada WABA vem do cofre (KAM-218)
 *
 * O *token* de cliente vive cifrado no cofre, com a referência em
 * `tenant_channels.token_ref` (KAM-016). O adaptador recebe uma função que o
 * devolve por WABA (`TokenDoWaba`), e o leitor é o `tokenDoWabaPeloCofre`
 * abaixo, pela ordem que o KAM-016 escreveu ao guardá-lo — a mesma do
 * `#tokenEmClaro` do onboarding:
 *
 *     tenant_channels.token_ref        a referência, lida como `kamba_batch`
 *       → o cofre, pela referência     o criptograma (ADR-L002: o ambiente que
 *                                      o lançador do cofre enche)
 *       → decifrarToken(anel, tenant)  com a `kek_token_cliente`, cujo contexto
 *                                      autenticado leva o tenant da linha
 *
 * **Um WABA de mais do que um tenant recusa**, em vez de escolher: a leitura é do
 * lote (`BYPASSRLS`) e não tem um tenant do pedido que a filtre, e cancelar a
 * subscrição de um WABA que outro tenant ainda usa desligava o canal dele.
 * Recusar deixa a fase parada, com alerta, que é o lado seguro do engano.
 */

import { anelDaKek, decifrarToken, TokenCifradoInvalidoError } from "../onboarding/cifra.ts";
import { CAMPOS_DE_WEBHOOK, type Graph } from "../onboarding/contrato.ts";
import { GraphRecusouError } from "../onboarding/graph.ts";
// O `id` da KEK vem do ficheiro estreito que o *gate* 9 dispensa.
import { REF_DA_KEK } from "../onboarding/segredos.ts";
import { SecretAusenteError, SecretRefInvalidaError, type SecretProvider } from "../secrets/port.ts";
import type { CanalDaMeta } from "./contrato.ts";

/** Devolve o *token* de cliente em claro de um WABA. Nunca vai a registo. */
export type TokenDoWaba = (wabaId: string) => Promise<string>;

/** Uma operação que este adaptador não faz, e porquê. Nada sai para a rede. */
export class OperacaoForaDoOffboardingError extends Error {
  override readonly name = "OperacaoForaDoOffboardingError";

  constructor(operacao: string, razao: string) {
    super(`${operacao} nao corre no adaptador da Meta do off-boarding: ${razao}`);
  }
}

export class CanalDaMetaPelaGraph implements CanalDaMeta {
  readonly #graph: Pick<Graph, "subscrever" | "anularSubscricao">;
  readonly #token: TokenDoWaba;

  constructor(graph: Pick<Graph, "subscrever" | "anularSubscricao">, token: TokenDoWaba) {
    this.#graph = graph;
    this.#token = token;
  }

  async cancelarSubscricao(wabaId: string): Promise<void> {
    const token = await this.#token(wabaId);
    try {
      await this.#graph.anularSubscricao(wabaId, token);
    } catch (erro) {
      // O recurso já não está lá: é o sucesso de uma repetição (ver a nota do módulo).
      if (erro instanceof GraphRecusouError && erro.estado === 404) return;
      throw erro;
    }
  }

  async subscreverWebhooks(wabaId: string): Promise<void> {
    await this.#graph.subscrever(wabaId, CAMPOS_DE_WEBHOOK, await this.#token(wabaId));
  }

  async apagarWaba(_wabaId: string): Promise<void> {
    throw new OperacaoForaDoOffboardingError("apagarWaba", "o WABA e do cliente (E1)");
  }

  async apagarNumero(_phoneNumberId: string): Promise<void> {
    throw new OperacaoForaDoOffboardingError("apagarNumero", "o numero e do cliente (E1)");
  }

  async removerRota(_phoneNumberId: string): Promise<void> {
    throw new OperacaoForaDoOffboardingError("removerRota", "a rota e a linha do CHR, e encerra-a a revogacao");
  }

  async numeroDoTenant(_tenantId: string): Promise<string | null> {
    throw new OperacaoForaDoOffboardingError("numeroDoTenant", "o numero le-o o onboarding");
  }
}

// ------------------------------------------------- o leitor do cofre (KAM-218)

/**
 * As referências do *token* de um WABA, com o tenant de cada uma. **Sem
 * `LIMIT`**: duas linhas de tenants diferentes têm de se ver para se recusar.
 *
 * **Sem os canais `encerrado`** (achado 7 da revisão adversarial): a linha de um
 * tenant que já saiu guarda o `waba_id` e o `token_ref`, e contá-la fazia
 * `ambiguo` para sempre o encerramento de quem ficou com o WABA. O limite que
 * fica, escrito: um tenant com o mesmo WABA que só tenha a linha do onboarding
 * de canal, e nenhuma na `tenant_channels`, não conta para a recusa.
 */
export const SQL_TOKENS_DO_WABA = `
  SELECT DISTINCT tenant_id::text AS tenant_id, token_ref
    FROM platform.tenant_channels
   WHERE waba_id = $1 AND token_ref IS NOT NULL AND estado <> 'encerrado'
   ORDER BY 1, 2
`;

/** Porque é que um WABA não tem *token*. Literais, para o registo: nenhum leva a referência. */
export const MOTIVOS_SEM_TOKEN = [
  /** Nenhum canal com este WABA tem `token_ref`. */
  "sem_canal",
  /** O WABA aparece em mais do que um tenant. */
  "ambiguo",
  /** O cofre não tem segredo sob a referência, ou ela não tem forma. */
  "sem_segredo",
  /** O criptograma não abre: outra KEK, outro tenant, ou conteúdo alterado. */
  "nao_abre",
] as const;
export type MotivoSemToken = (typeof MOTIVOS_SEM_TOKEN)[number];

/** O WABA não tem *token* que sirva. A fase `canal` falha por isto, pelo nome. */
export class WabaSemTokenError extends Error {
  override readonly name = "WabaSemTokenError";
  readonly motivo: MotivoSemToken;

  constructor(motivo: MotivoSemToken) {
    super(`o WABA do encerramento nao tem token de cliente: ${motivo}`);
    this.motivo = motivo;
  }
}

/**
 * A ligação de que o leitor precisa: só o `query`, com as linhas só de leitura —
 * a forma mais larga, que o conjunto do lote (`ConjuntoSql`) e o cliente do
 * encerramento satisfazem os dois.
 */
export interface LeitorSql {
  query(sql: string, valores?: readonly unknown[]): Promise<{ readonly rows: readonly Record<string, unknown>[] }>;
}

/** O que o leitor lê do cofre: só leitura, e só as três operações de que precisa. */
export type CofreDoToken = Pick<SecretProvider, "get" | "getRing" | "versions">;

/**
 * O leitor: o *token* em claro de um WABA, pela referência e pela KEK.
 *
 * Lê o cofre a cada chamada, sem *cache*: com o `EnvSecretProvider` do Piloto é
 * uma leitura do ambiente, e uma *cache* aqui era um segundo sítio onde o
 * *token* em claro ficava a viver entre fases. A KEK em falta **não** é motivo
 * deste WABA: é configuração do processo, e sobe como o erro do cofre.
 */
export function tokenDoWabaPeloCofre(o: { readonly bd: LeitorSql; readonly cofre: CofreDoToken }): TokenDoWaba {
  return async (wabaId) => {
    const { rows } = await o.bd.query(SQL_TOKENS_DO_WABA, [wabaId]);
    if (rows.length === 0) throw new WabaSemTokenError("sem_canal");
    const tenants = new Set(rows.map((r) => String(r.tenant_id)));
    if (tenants.size > 1) throw new WabaSemTokenError("ambiguo");
    const tenantId = [...tenants][0] as string;

    const anel = anelDaKek(await o.cofre.getRing(REF_DA_KEK), await o.cofre.versions(REF_DA_KEK)); // kamba:secrets-inventory dinamico REF_DA_KEK e a kek_token_cliente, no inventario

    // Um WABA com dois números pode ter duas referências do mesmo tenant: qualquer
    // *token* de cliente desse tenant serve a subscrição do WABA, e a primeira que
    // abre ganha. Nenhuma a abrir diz o motivo da última.
    let motivo: MotivoSemToken = "sem_segredo";
    for (const r of rows) {
      let criptograma: string;
      try {
        criptograma = await o.cofre.get(String(r.token_ref)); // kamba:secrets-inventory dinamico o token_ref do canal, instancia de meta_client_token
      } catch (erro) {
        if (erro instanceof SecretAusenteError || erro instanceof SecretRefInvalidaError) {
          motivo = "sem_segredo";
          continue;
        }
        throw erro;
      }
      try {
        return decifrarToken(anel, tenantId, criptograma);
      } catch (erro) {
        if (!(erro instanceof TokenCifradoInvalidoError)) throw erro;
        motivo = "nao_abre";
      }
    }
    throw new WabaSemTokenError(motivo);
  };
}

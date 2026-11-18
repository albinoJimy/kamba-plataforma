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
 * ## O *token* de cada WABA vem de fora
 *
 * O *token* de cliente vive cifrado no cofre, com a referência em
 * `tenant_channels.token_ref` (KAM-016). Este adaptador recebe uma função que o
 * devolve por WABA, e não a escreve: **neste processo não há leitor do cofre em
 * produção** (o `Cofre` do KAM-016 não tem implementação fora dos ensaios), pelo
 * que o processo de lote monta a porta sem adaptador até haver — e a fase
 * `canal` fica parada, com alerta, em vez de se dar por feita sem a Meta saber.
 */

import { CAMPOS_DE_WEBHOOK, type Graph } from "../onboarding/contrato.ts";
import { GraphRecusouError } from "../onboarding/graph.ts";
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

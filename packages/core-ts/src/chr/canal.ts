/**
 * `resolve(phone_number_id) → ChannelContext`, com *cache* de 60 s (KAM-014).
 *
 * É a pergunta que se faz **antes** de haver contexto de tenant, e por isso
 * corre com o papel `kamba_resolver` (KAM-004): `NOBYPASSRLS`, política própria
 * `resolver_leitura`, `SELECT` em dez colunas e mais nada
 * (`docs/isolamento.md` §3).
 *
 * ## Porque é que há *cache*, e porque é que ela é por `phone_number_id`
 *
 * O critério 1 pede 60 s de TTL e invalidação por `channel.updated` em ≤ 1 s
 * «quando o consumidor existir; até lá vale o TTL». A chave é o
 * `phone_number_id` porque é essa a pergunta: o CHR recebe-o do corpo do
 * webhook e não conhece o `channel_id` antes de resolver. A invalidação por
 * evento, que traz o `channel_id`, resolve-se com um índice inverso — ver
 * `invalidarCanal`.
 *
 * ## Duas propriedades que a *cache* **não** pode ter, e não tem
 *
 * **Não guarda o que não resolveu.** Um `phone_number_id` desconhecido não
 * entra: a chave vem de fora, e guardar negativas era deixar quem consiga
 * assinar corpos encher a memória com chaves que nunca resolvem. O custo é uma
 * ida à base por cada mensagem de um canal desconhecido — que é exactamente o
 * caso que o critério 2 manda alertar, e não um caminho normal.
 *
 * **Não mistura tenants.** A entrada é o `ChannelContext` inteiro, e a chave é
 * o `phone_number_id`, que a `tenant_channels_phone_number_id_uq` torna único
 * em toda a plataforma (`0001`). Não há duas linhas onde escolher, e por isso
 * não há forma de o `phone_number_id` de A devolver o contexto de B — a
 * propriedade vem da chave única e não do código.
 */

import {
  ESTADOS_DO_CANAL,
  ESTADOS_DO_TENANT,
  type EstadoDoCanal,
  type EstadoDoTenant,
} from "../ten/estados.ts";
import { SQL_CANAL } from "./consultas.ts";
import {
  type ChannelContext,
  type ClienteDoChr,
  MAXIMO_DE_CANAIS,
  TTL_MS,
} from "./contrato.ts";

/** Uma linha de `SQL_CANAL` que não tem a forma esperada. */
export class CanalIlegivelError extends Error {
  constructor(coluna: string) {
    super(
      `a coluna ${JSON.stringify(coluna)} de platform.tenant_channels nao veio ` +
        "na forma esperada. A consulta e `SQL_CANAL`, e a revisao que a " +
        "sustenta e a `0009` (o `plano` foi concedido ao kamba_resolver la).",
    );
    this.name = "CanalIlegivelError";
  }
}

/** O `tipo` do tenant vem com o contexto, para a guarda do ADR-011. */
export interface CanalResolvido {
  readonly contexto: ChannelContext;
  /** `platform.tenants.tipo`. Só a guarda do Fluxo B o usa. */
  readonly tipoTenant: string;
}

interface Entrada {
  readonly resolvido: CanalResolvido;
  readonly expiraEm: number;
}

function texto(linha: Readonly<Record<string, unknown>>, coluna: string): string {
  const valor = linha[coluna];
  if (typeof valor !== "string" || valor === "") {
    throw new CanalIlegivelError(coluna);
  }
  return valor;
}

const ESTADOS_DE_TENANT: readonly string[] = ESTADOS_DO_TENANT;
const ESTADOS_DE_CANAL: readonly string[] = ESTADOS_DO_CANAL;

/**
 * A linha da base como `CanalResolvido`, ou lança.
 *
 * Os dois estados são validados aqui contra as listas fechadas do
 * `ten/estados.ts`, e não mais adiante: o `tenantGate` lança
 * `EstadoDesconhecidoError` se receber um estado que não conhece, e um estado
 * novo na base tem de parar a resolução **antes** de a conversa ser aberta —
 * caso contrário abria-se uma conversa para uma mensagem que ninguém sabia
 * tratar. O `CHECK` da `0001` já fixa os seis e os cinco; isto é a segunda
 * barreira, para o dia em que alguém o alargue sem alargar o código.
 */
export function canalDaLinha(linha: Readonly<Record<string, unknown>>): CanalResolvido {
  const estadoTenant = texto(linha, "estado_tenant");
  const estadoCanal = texto(linha, "estado_canal");
  if (!ESTADOS_DE_TENANT.includes(estadoTenant)) {
    throw new CanalIlegivelError("estado_tenant");
  }
  if (!ESTADOS_DE_CANAL.includes(estadoCanal)) {
    throw new CanalIlegivelError("estado_canal");
  }
  return {
    contexto: {
      tenant_id: texto(linha, "tenant_id"),
      channel_id: texto(linha, "channel_id"),
      vertical: texto(linha, "vertical"),
      plano: texto(linha, "plano"),
      estado_tenant: estadoTenant as EstadoDoTenant,
      estado_canal: estadoCanal as EstadoDoCanal,
      channel_mode: texto(linha, "channel_mode"),
      origem: texto(linha, "origem"),
    },
    tipoTenant: texto(linha, "tipo_tenant"),
  };
}

/** O que a resolução mediu, para as métricas. */
export interface LeituraDoCanal {
  readonly resolvido: CanalResolvido | null;
  /** `true` se a resposta veio da *cache*. */
  readonly daCache: boolean;
}

/**
 * Resolve `phone_number_id → ChannelContext`, com *cache*.
 *
 * Uma instância por processo. Não abre ligações: recebe a de `kamba_resolver`
 * de quem a construiu, como todo o resto desta biblioteca.
 */
export class ResolvedorDeCanal {
  readonly #cliente: ClienteDoChr;
  readonly #agora: () => number;
  readonly #ttl: number;
  readonly #maximo: number;
  /** `phone_number_id` → entrada. A ordem de inserção é a de expulsão. */
  readonly #cache = new Map<string, Entrada>();
  /** `channel_id` → `phone_number_id`, para a invalidação por evento. */
  readonly #porCanal = new Map<string, string>();

  constructor(
    cliente: ClienteDoChr,
    opcoes: {
      readonly agora?: () => number;
      readonly ttlMs?: number;
      readonly maximo?: number;
    } = {},
  ) {
    this.#cliente = cliente;
    this.#agora = opcoes.agora ?? (() => Date.now());
    this.#ttl = opcoes.ttlMs ?? TTL_MS;
    this.#maximo = opcoes.maximo ?? MAXIMO_DE_CANAIS;
  }

  /** Quantas entradas a *cache* tem agora. Para os testes e para a métrica. */
  get tamanho(): number {
    return this.#cache.size;
  }

  /**
   * O contexto de um `phone_number_id`, ou `null` se não houver canal.
   *
   * @throws o que a base lançar. Um erro de base **não** é um canal
   *   desconhecido: o primeiro merece retentativa (e o *job* falha, e o BullMQ
   *   repete), o segundo é quarentena. Confundi-los punha um evento válido na
   *   quarentena por causa de uma ligação perdida.
   */
  async resolver(phoneNumberId: string): Promise<LeituraDoCanal> {
    const agora = this.#agora();
    const guardada = this.#cache.get(phoneNumberId);
    if (guardada !== undefined) {
      if (guardada.expiraEm > agora) {
        return { resolvido: guardada.resolvido, daCache: true };
      }
      // Expirou: sai antes de se ir à base, para que uma falha da base não
      // deixe uma entrada velha a servir de resposta.
      this.#esquecer(phoneNumberId);
    }

    const resultado = await this.#cliente.query(SQL_CANAL, [phoneNumberId]);
    const linha = resultado.rows[0];
    if (linha === undefined) {
      // **Não se guarda.** Ver a nota do módulo.
      return { resolvido: null, daCache: false };
    }
    const resolvido = canalDaLinha(linha);
    this.#guardar(phoneNumberId, resolvido, agora);
    return { resolvido, daCache: false };
  }

  /**
   * Esquece um `phone_number_id`. A próxima resolução vai à base.
   *
   * É o que o TTL faz sozinho; isto é para quem souber que o canal mudou.
   */
  invalidar(phoneNumberId: string): boolean {
    return this.#esquecer(phoneNumberId);
  }

  /**
   * Esquece um canal pelo seu `channel_id`.
   *
   * É a entrada da invalidação por evento: o `channel.updated` traz o
   * identificador do canal e **não** o `phone_number_id`, que é a chave da
   * *cache*. O índice inverso é mantido em cada `#guardar`, pelo que só se
   * esquece o que se tinha guardado — um canal que nunca foi resolvido neste
   * processo não está em *cache* nenhuma, e a invalidação não tem nada a fazer.
   *
   * Devolve `true` se havia algo a esquecer. O consumidor de `channel.updated`
   * (KAM-006) é idempotente e trata o `false` como sucesso.
   */
  invalidarCanal(channelId: string): boolean {
    const phoneNumberId = this.#porCanal.get(channelId);
    if (phoneNumberId === undefined) return false;
    return this.#esquecer(phoneNumberId);
  }

  /** Esvazia a *cache*. Para os testes e para uma paragem limpa. */
  esquecerTudo(): void {
    this.#cache.clear();
    this.#porCanal.clear();
  }

  #esquecer(phoneNumberId: string): boolean {
    const entrada = this.#cache.get(phoneNumberId);
    if (entrada === undefined) return false;
    this.#cache.delete(phoneNumberId);
    // Só se apaga o índice inverso se ainda apontar para esta chave: um canal
    // que tenha mudado de `phone_number_id` deixou o apontador actualizado, e
    // apagá-lo às cegas tirava da *cache* uma entrada viva.
    if (this.#porCanal.get(entrada.resolvido.contexto.channel_id) === phoneNumberId) {
      this.#porCanal.delete(entrada.resolvido.contexto.channel_id);
    }
    return true;
  }

  #guardar(phoneNumberId: string, resolvido: CanalResolvido, agora: number): void {
    if (this.#cache.size >= this.#maximo) {
      // O mais antigo a entrar, que é o primeiro da ordem de iteração de um
      // `Map`. Não é LRU: é FIFO, e com TTL de 60 s a diferença não se mede.
      const primeira = this.#cache.keys().next();
      if (!primeira.done) this.#esquecer(primeira.value);
    }
    this.#cache.set(phoneNumberId, { resolvido, expiraEm: agora + this.#ttl });
    this.#porCanal.set(resolvido.contexto.channel_id, phoneNumberId);
  }
}

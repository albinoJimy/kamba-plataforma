/**
 * O estado do canal que o painel mostra (KAM-099, critério 7; adaptador do
 * KAM-190).
 *
 * «O painel mostra o estado do canal (`ativo`, `a_sincronizar`, `desligado`) e
 * o nível de confiança/tecto actual, com ligação ao passo de reconexão de
 * KAM-093 e aos avisos de T&S de KAM-097.»
 *
 * ```text
 * CanalPeloCom     o `POST /internal/channel-view` do COM, em produção
 * CanalEmMemoria   o duplo de `dev` e das baterias
 * ```
 *
 * ## Porque é que a leitura vai pelo COM
 *
 * O `onboarding-web` não tem rota para a base (está só na rede `app`), e o COM é
 * a superfície interna que ele já alcança com credencial e com o tenant num
 * cabeçalho. A leitura em si — `platform.tenant_channels`, a sincronização do
 * KAM-017, a `trust_level` do KAM-096 e os avisos do
 * `ServicoDeTrust.avisosDoPainel` do KAM-097 — vive em
 * `services/com/src/canal/vista.ts`, com a razão escrita por extenso.
 *
 * ## Uma falha do COM é «indisponível», e não «sem canal»
 *
 * O duplo do KAM-099 respondia `sem_canal` a tudo, e a página mostrava «ligar o
 * número» a um dono com o canal activo. Com o adaptador, uma resposta que não
 * chega é `null`, e a rota responde 503: dizer ao dono que o número dele está
 * desligado quando não se sabe era mandá-lo repetir o Embedded Signup.
 */

import type { Actor, ComercioPorHttp } from "./comercio.ts";

/** Os três estados do canal do critério, mais o de quem ainda não ligou. */
export const ESTADOS_DO_CANAL = ["ativo", "a_sincronizar", "desligado", "sem_canal"] as const;
export type EstadoDoCanal = (typeof ESTADOS_DO_CANAL)[number];

/** O que a página do canal precisa. Nenhum telefone, nenhum identificador da Meta. */
export interface VistaDoCanal {
  readonly estado: EstadoDoCanal;
  /** O canal está ligado e limitado pela Meta ou pela plataforma. */
  readonly restrito: boolean;
  /** A qualidade do número (KAM-021), ou `null` se ainda não há. */
  readonly qualidade: string | null;
  /** O escalão de conversas iniciadas que a Meta anunciou, ou `null`. */
  readonly escalao: string | null;
  /** O nível de confiança (KAM-096), ou `null` se ainda não há. */
  readonly nivel: number | null;
  /** O tecto por pedido (KAM-096), em unidade menor, ou `null`. */
  readonly tectoPedidoMinor: bigint | null;
  /** Os códigos dos avisos de T&S em vigor (KAM-097), do mais recente ao mais antigo. */
  readonly avisos: readonly string[];
}

export interface LeitorDoCanal {
  /** A vista do canal do tenant, ou `null` se não se conseguiu ler. */
  ler(tenantId: string, a: Actor): Promise<VistaDoCanal | null>;
}

/** A vista vazia de quem ainda não ligou o número. */
export const SEM_CANAL: VistaDoCanal = {
  estado: "sem_canal",
  restrito: false,
  qualidade: null,
  escalao: null,
  nivel: null,
  tectoPedidoMinor: null,
  avisos: [],
};

/** O duplo: por tenant, e `sem_canal` para quem não está no mapa. */
export class CanalEmMemoria implements LeitorDoCanal {
  readonly vistas = new Map<string, VistaDoCanal>();

  async ler(tenantId: string): Promise<VistaDoCanal | null> {
    return this.vistas.get(tenantId) ?? SEM_CANAL;
  }
}

/** O adaptador real: o `channel-view` do COM. */
export class CanalPeloCom implements LeitorDoCanal {
  readonly #com: Pick<ComercioPorHttp, "vistaDoCanal">;

  constructor(com: Pick<ComercioPorHttp, "vistaDoCanal">) {
    this.#com = com;
  }

  async ler(tenantId: string, a: Actor): Promise<VistaDoCanal | null> {
    const r = await this.#com.vistaDoCanal(tenantId, a);
    return r.tipo === "ok" ? r.valor : null;
  }
}

/**
 * O estado do canal que o painel mostra (KAM-099, critério 7).
 *
 * «O painel mostra o estado do canal (`ativo`, `a_sincronizar`, `desligado`) e
 * o nível de confiança/tecto actual, com ligação ao passo de reconexão de
 * KAM-093 e aos avisos de T&S de KAM-097.»
 *
 * ## Uma porta com duplo, e o adaptador por escrever
 *
 * O estado vive em `platform.channels` e o tecto na qualidade do canal
 * (KAM-021), e o `onboarding-web` não tem cliente de base de dados nem rota de
 * outro serviço que os sirva. Escrever essa rota era alargar o GWY ou o TEN por
 * conta deste ticket. O que fica entregue é a **forma** e a página que a
 * mostra; o adaptador é o credor da caixa do critério 7, que fica **parcial**.
 */

/** Os três estados do canal do critério, mais o de quem ainda não ligou. */
export const ESTADOS_DO_CANAL = ["ativo", "a_sincronizar", "desligado", "sem_canal"] as const;
export type EstadoDoCanal = (typeof ESTADOS_DO_CANAL)[number];

/** O que a página do canal precisa. Nenhum telefone, nenhum identificador da Meta. */
export interface VistaDoCanal {
  readonly estado: EstadoDoCanal;
  /** O nível de confiança (por exemplo, `restrito`), ou `null` se não há. */
  readonly nivel: string | null;
  /** O tecto diário de conversas iniciadas, ou `null` se não há. */
  readonly tecto: number | null;
  /** Os códigos dos avisos de T&S em vigor (KAM-097). */
  readonly avisos: readonly string[];
}

export interface LeitorDoCanal {
  ler(tenantId: string): Promise<VistaDoCanal>;
}

/** O duplo: por tenant, e `sem_canal` para quem não está no mapa. */
export class CanalEmMemoria implements LeitorDoCanal {
  readonly vistas = new Map<string, VistaDoCanal>();

  async ler(tenantId: string): Promise<VistaDoCanal> {
    return this.vistas.get(tenantId) ?? { estado: "sem_canal", nivel: null, tecto: null, avisos: [] };
  }
}

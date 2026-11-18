/**
 * Confiança gradual — o nível de um tenant, e o recálculo (KAM-096).
 *
 * ```text
 * K1 completo, sem nível ─────────────► nível 0   (k1_completo)
 * nível 0 + subida cumprida ──────────► nível 1   (historico_independente)
 * nível 1 + sanção em vigor ──────────► nível 0   (sancao)
 * nível 1 + disputa aceite depois ────► nível 0   (disputa_aceite)
 * nível 1 + sinal alto depois ────────► nível 0   (sinal_alto)
 * tecto gravado ≠ tecto da config ────► o mesmo   (recalibracao)
 * ```
 *
 * O `decidirNivel` é puro e devolve `null` quando não há nada a escrever: é
 * isso que torna o recálculo **idempotente** (DoD 2) — reexecutar sobre o mesmo
 * estado decide `null` e não escreve, e a base também não escreve uma linha
 * igual (o `ON CONFLICT ... WHERE` do `./sql.ts`), pelo que não sai segunda
 * linha no `audit_log`.
 *
 * **A sanção do KAM-097 manda no tecto mesmo antes de o recálculo correr**: o
 * `GuardaDeConfianca` lê o `tectoNoNivelZero` em cada cobrança. O recálculo
 * grava a descida, para que a base — o *trigger* da cobrança — também a veja.
 */

import type { Independencia, RestricoesEmVigor } from "../trust/contrato.ts";
import {
  CONFIGURACAO_DA_CONFIANCA,
  type ConfiguracaoDaConfianca,
  type NivelDeConfianca,
  validarConfiguracao,
} from "./config.ts";
import { contar, cumpreSubida, inicioDaLeitura, type PedidoCandidato } from "./elegibilidade.ts";

/** Porque é que um tenant está no nível em que está. Domínio de `trust_level.motivo`. */
export const MOTIVOS_DO_NIVEL = [
  "k1_completo",
  "historico_independente",
  "disputa_aceite",
  "sinal_alto",
  "sancao",
  "recalibracao",
] as const;
export type MotivoDoNivel = (typeof MOTIVOS_DO_NIVEL)[number];

/** A linha de `trust_level`, como o recálculo a lê. */
export interface NivelGravado {
  readonly nivel: NivelDeConfianca;
  readonly tectoPedidoMinor: bigint;
  readonly motivo: MotivoDoNivel;
  /** Desde quando o tenant está **neste nível**. Uma recalibração não o muda. */
  readonly desde: Date;
}

/** Tudo o que decide o nível, já lido. */
export interface FactosDoTenant {
  readonly actual: NivelGravado | null;
  readonly k1Completo: boolean;
  readonly pedidos: readonly PedidoCandidato[];
  /** A disputa aceite contra o dono mais recente (`em_disputa → reembolso_pendente`). */
  readonly ultimaDisputaAceite: Date | null;
  /** O sinal de severidade alta do KAM-097 mais recente. */
  readonly ultimoSinalAlto: Date | null;
  /** `limitacao` ou acima em vigor (`RestricoesEmVigor.tectoNoNivelZero`). */
  readonly sancaoEmVigor: boolean;
}

export interface Decisao {
  readonly nivel: NivelDeConfianca;
  readonly tectoPedidoMinor: bigint;
  readonly motivo: MotivoDoNivel;
}

function depois(a: Date | null, b: Date): boolean {
  return a !== null && a.getTime() > b.getTime();
}

/** O instante a partir do qual os pedidos contam: o mais tarde entre o nível e os factos negativos. */
export function marcoDaElegibilidade(f: FactosDoTenant): Date {
  const marcos = [f.actual?.desde, f.ultimaDisputaAceite, f.ultimoSinalAlto].filter(
    (d): d is Date => d instanceof Date,
  );
  return new Date(Math.max(0, ...marcos.map((d) => d.getTime())));
}

/** O que escrever em `trust_level`, ou `null` quando nada muda. */
export function decidirNivel(
  f: FactosDoTenant,
  c: ConfiguracaoDaConfianca,
  agora: Date,
): Decisao | null {
  const no = (nivel: NivelDeConfianca, motivo: MotivoDoNivel): Decisao => ({
    nivel,
    tectoPedidoMinor: c.niveis[nivel].tectoPedidoMinor.valor,
    motivo,
  });
  const actual = f.actual;
  if (actual === null) return f.k1Completo ? no(0, "k1_completo") : null;

  if (actual.nivel > 0) {
    if (f.sancaoEmVigor) return no(0, "sancao");
    if (depois(f.ultimaDisputaAceite, actual.desde)) return no(0, "disputa_aceite");
    if (depois(f.ultimoSinalAlto, actual.desde)) return no(0, "sinal_alto");
  }

  if (actual.nivel === 0 && !f.sancaoEmVigor && c.niveis[1].atribuivel) {
    const n = contar(f.pedidos, c, agora, marcoDaElegibilidade(f));
    if (cumpreSubida(n, c)) return no(1, "historico_independente");
  }

  const tecto = c.niveis[actual.nivel].tectoPedidoMinor.valor;
  return tecto === actual.tectoPedidoMinor ? null : no(actual.nivel, "recalibracao");
}

// ------------------------------------------------------------------ portas

/** Um pedido entregue, antes de se lhe perguntar a independência. */
export type PedidoLido = Omit<PedidoCandidato, "independencia">;

/** Onde o nível vive. A implementação é o `./sql.ts`, como `kamba_batch`. */
export interface RepositorioDeConfianca {
  /**
   * A tranca exclusiva do tenant, antes de qualquer leitura. Só vale numa
   * transacção: quem chama o `recalcular` abre **uma por tenant**, em
   * `READ COMMITTED`, e faz *commit* no fim — uma transacção para muitos
   * tenants prendia as cobranças de todos até ao *commit*.
   */
  trancar(tenantId: string): Promise<void>;
  nivel(tenantId: string): Promise<NivelGravado | null>;
  k1Completo(tenantId: string): Promise<boolean>;
  /** Os pedidos entregues desde `desde` com pelo menos `valorMinimoMinor`. */
  pedidosEntregues(tenantId: string, desde: Date, valorMinimoMinor: bigint, janelaAntiFraudeDias: number): Promise<readonly PedidoLido[]>;
  factosNegativos(tenantId: string): Promise<{ readonly ultimaDisputaAceite: Date | null; readonly ultimoSinalAlto: Date | null }>;
  /** Grava; `true` se a linha mudou. A base audita a alteração. */
  definir(tenantId: string, d: Decisao, actor: string, versaoConfig: string): Promise<boolean>;
}

/** A marca do KAM-097. É o `RepositorioDeTrustSql.independencia`. */
export interface LeitorDeIndependencia {
  independencia(tenantId: string, orderId: string, consumer: string): Promise<Independencia>;
}

/** As sanções em vigor. É o `ServicoDeTrust.restricoes`. */
export interface LeitorDeRestricoes {
  restricoes(tenantId: string): Promise<RestricoesEmVigor>;
}

export interface DependenciasDaConfianca {
  readonly repositorio: RepositorioDeConfianca;
  readonly independencia: LeitorDeIndependencia;
  readonly restricoes: LeitorDeRestricoes;
  /** O nome do consumidor de T&S que marca a independência (`events_consumed.consumer`). */
  readonly consumidorDeTrust: string;
  readonly configuracao?: ConfiguracaoDaConfianca;
  readonly relogio?: () => Date;
}

export interface ResultadoDoRecalculo {
  readonly tenantId: string;
  readonly nivel: NivelDeConfianca | null;
  readonly mudou: boolean;
  readonly motivo: MotivoDoNivel | null;
}

/** O actor das alterações automáticas: `sistema:<versão da configuração>`. */
export function actorDoSistema(c: ConfiguracaoDaConfianca): string {
  return `sistema:${c.versao}`;
}

/**
 * O recálculo de um tenant: diário e em `order.delivered`.
 *
 * Quem o agenda é o `./lote.ts` (KAM-203). Corre como `kamba_batch`,
 * que é o único papel que escreve `trust_level`, numa transacção por tenant
 * (ver o `RepositorioDeConfianca.trancar`).
 */
export class ServicoDeConfianca {
  readonly #d: DependenciasDaConfianca;
  readonly #c: ConfiguracaoDaConfianca;

  constructor(d: DependenciasDaConfianca) {
    if (!/^[a-z][a-z0-9_]*$/.test(d.consumidorDeTrust)) {
      throw new Error(`consumidor de T&S invalido: '${d.consumidorDeTrust}'`);
    }
    this.#d = d;
    this.#c = validarConfiguracao(d.configuracao ?? CONFIGURACAO_DA_CONFIANCA);
  }

  async recalcular(tenantId: string): Promise<ResultadoDoRecalculo> {
    const agora = (this.#d.relogio ?? (() => new Date()))();
    const r = this.#d.repositorio;
    await r.trancar(tenantId);
    const actual = await r.nivel(tenantId);
    const k1Completo = actual === null ? await r.k1Completo(tenantId) : true;
    const p = this.#c.patamares;
    const lidos =
      actual?.nivel === 0
        ? await r.pedidosEntregues(tenantId, inicioDaLeitura(this.#c, agora), p.valorMinimoMinor.valor, p.janelaAntiFraudeDias.valor)
        : [];
    const pedidos: PedidoCandidato[] = [];
    for (const l of lidos) {
      const independencia = await this.#d.independencia.independencia(tenantId, l.orderId, this.#d.consumidorDeTrust);
      pedidos.push({ ...l, independencia });
    }
    const negativos = actual === null ? { ultimaDisputaAceite: null, ultimoSinalAlto: null } : await r.factosNegativos(tenantId);
    const { tectoNoNivelZero } = await this.#d.restricoes.restricoes(tenantId);
    const decisao = decidirNivel(
      { actual, k1Completo, pedidos, ...negativos, sancaoEmVigor: tectoNoNivelZero },
      this.#c,
      agora,
    );
    if (decisao === null) {
      return { tenantId, nivel: actual?.nivel ?? null, mudou: false, motivo: actual?.motivo ?? null };
    }
    const mudou = await r.definir(tenantId, decisao, actorDoSistema(this.#c), this.#c.versao);
    return { tenantId, nivel: decisao.nivel, mudou, motivo: decisao.motivo };
  }
}

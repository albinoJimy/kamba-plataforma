/**
 * O consumidor de Trust & Safety e as varreduras (KAM-097, critérios 1 a 5).
 *
 * ## O consumidor
 *
 * `efeitoDeTrust()` é o `Efeito` do `consumir` (`../eventos/consumo.ts`): corre
 * **dentro** da transacção que marca o `events_consumed`, com o `app.tenant_id`
 * do envelope, como `kamba_app`. A marca e os sinais confirmam juntos, e é isso
 * que faz a reentrega dar um sinal e não dois (ensaio adversarial (e)) — além
 * da chave `(tenant_id, tipo, ref_evento)` da `ts_signal`, que é a segunda
 * barreira.
 *
 * | Evento | O que se avalia |
 * |---|---|
 * | `order.created`, `order.paid` | auto-compra (por encomenda: os dois dão **um** sinal) |
 * | `order.paid` manual | burla provável (tenant novo, pedidos manuais perto do tecto) |
 * | `payment.manual_confirmed` | confirmação suspeita (< 30 s, repetida) |
 * | `query.handoff` de reclamação | queixa recorrente, só de compradores pagos |
 * | `screening.violation_detected` | violação de categoria |
 * | `order.delivered`, `payment.confirmed` | nada: consomem-se para que a independência se leia |
 *
 * **Nenhum sinal leva PII**: o `detalhe` só tem referências (`order_id`, `sku`),
 * códigos e contagens, e a base fecha-lhe as chaves.
 *
 * ## As varreduras
 *
 * A não-entrega e a foto repetida não têm evento que as anuncie: são
 * varreduras do `kamba_batch` (`varrerNaoEntregas`, `varrerFotos`), que é o
 * papel auditado que atravessa tenants. A foto repetida é a única correlação
 * entre tenants deste ticket, e sai só como sinal informativo (peso 0) com uma
 * contagem — nunca o outro tenant.
 */

import type { Efeito } from "../eventos/consumo.ts";
import type { ClienteSql } from "../eventos/publicador.ts";
import type { SinalNovo } from "./contrato.ts";
import {
  POLITICA_DE_RISCO,
  autoCompra,
  burlaProvavel,
  confirmacaoSuspeita,
  naoEntregue,
  queixaRecorrente,
  queixasQueContam,
  type PedidoManual,
  type PoliticaDeRisco,
  type TipoDeSinal,
} from "./regras.ts";
import { ServicoDeTrust } from "./servico.ts";
import {
  RepositorioDeTrustSql,
  SQL_COMPRADORES_PAGOS,
  SQL_CONTACTOS_DO_DONO,
  SQL_FOTOS_REPETIDAS,
  SQL_NAO_ENTREGUES,
  SQL_PEDIDO_E_COMPRADOR,
  SQL_PEDIDOS_MANUAIS,
  SQL_QUEIXAS,
  SQL_TENANT_E_TECTO,
} from "./sql.ts";

/** Os tipos que este consumidor subscreve: os sete do critério 1. */
export const TIPOS_CONSUMIDOS = [
  "order.created",
  "order.paid",
  "order.delivered",
  "payment.manual_confirmed",
  "payment.confirmed",
  "query.handoff",
  "screening.violation_detected",
] as const;

/** O `motivo` do `query.handoff` que é uma reclamação (`MOTIVO_RECLAMACAO` do vendedor do AGR). */
export const MOTIVO_DE_RECLAMACAO = "reclamacao_grave";

/** Conta os sinais e as sanções gravados. Sem PII nas etiquetas: só tipo e passo. */
export interface ContadoresDoTrust {
  sinal(tipo: TipoDeSinal): void;
  sancao(passo: string, origem: string): void;
}

export interface OpcoesDoTrust {
  readonly politica?: PoliticaDeRisco;
  readonly relogio?: () => Date;
  readonly contadores?: ContadoresDoTrust;
}

const DIA = 86_400_000;

function texto(v: unknown): string {
  if (typeof v !== "string" || v === "") throw new TypeError("payload sem o campo esperado");
  return v;
}

function data(v: unknown): Date {
  return v instanceof Date ? v : new Date(String(v));
}

function inteiro(v: unknown): number {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number.parseInt(v, 10) : Number.NaN;
  if (!Number.isSafeInteger(n)) throw new RangeError("inteiro fora do seguro");
  return n;
}

/** Os factos de um evento, lidos na transacção do consumo. */
class Factos {
  readonly #bd: ClienteSql;
  readonly #t: string;
  constructor(bd: ClienteSql, tenantId: string) {
    this.#bd = bd;
    this.#t = tenantId;
  }

  async contactosDoDono(): Promise<readonly string[]> {
    return (await this.#bd.query(SQL_CONTACTOS_DO_DONO, [this.#t])).rows.map((l) => String(l["contact_id"]));
  }

  async pedido(orderId: string): Promise<{ readonly contactos: readonly string[]; readonly pagaVia: string | null } | null> {
    const l = (await this.#bd.query(SQL_PEDIDO_E_COMPRADOR, [this.#t, orderId])).rows[0];
    if (l === undefined) return null;
    const c = l["contactos"];
    return { contactos: Array.isArray(c) ? c.map(String) : [], pagaVia: l["paga_via"] === null ? null : String(l["paga_via"]) };
  }

  async tenantETecto(): Promise<{ readonly activoDesde: Date | null; readonly tectoMinor: number }> {
    const l = (await this.#bd.query(SQL_TENANT_E_TECTO, [this.#t])).rows[0];
    const a = l?.["primeira_activacao_at"];
    const t = l?.["tecto"];
    return { activoDesde: a === null || a === undefined ? null : data(a), tectoMinor: t === null || t === undefined ? 0 : inteiro(t) };
  }

  async manuais(desde: Date): Promise<readonly (PedidoManual & { readonly pagaEm: Date })[]> {
    return (await this.#bd.query(SQL_PEDIDOS_MANUAIS, [this.#t, desde])).rows.map((l) => ({
      orderId: String(l["order_id"]),
      totalMinor: inteiro(l["total_minor"]),
      criadoEm: data(l["criado_at"]),
      pagaEm: data(l["paga_at"]),
    }));
  }

  async queixas(desde: Date): Promise<{ readonly queixas: readonly { readonly contactId: string | null; readonly em: Date }[]; readonly pagos: ReadonlySet<string> }> {
    const q = (await this.#bd.query(SQL_QUEIXAS, [this.#t, desde])).rows.map((l) => ({
      contactId: l["contact_id"] === null ? null : String(l["contact_id"]),
      em: data(l["em"]),
    }));
    const pagos = new Set((await this.#bd.query(SQL_COMPRADORES_PAGOS, [this.#t])).rows.map((l) => String(l["contact_id"])));
    return { queixas: q, pagos };
  }
}

/** Os sinais que um evento produz. Função do evento e dos factos lidos; não grava nada. */
export async function sinaisDoEvento(
  bd: ClienteSql,
  envelope: { readonly id: string; readonly tipo: string; readonly tenant_id: string; readonly ocorrido_em: string | Date; readonly payload: Readonly<Record<string, unknown>> },
  agora: Date,
  p: PoliticaDeRisco = POLITICA_DE_RISCO,
): Promise<readonly SinalNovo[]> {
  const tenantId = envelope.tenant_id;
  const ocorridoEm = data(envelope.ocorrido_em);
  const f = new Factos(bd, tenantId);
  const sinais: SinalNovo[] = [];
  const payload = envelope.payload;

  switch (envelope.tipo) {
    case "order.created":
    case "order.paid": {
      const orderId = texto(payload["order_id"]);
      const pedido = await f.pedido(orderId);
      if (pedido === null) break;
      const dono = { contactIds: await f.contactosDoDono(), phoneHmacs: [], bsuidHmacs: [] };
      for (const contactId of pedido.contactos) {
        const c = autoCompra({ contactId, phoneHmac: null, bsuidHmacs: [] }, dono);
        if (c !== null) {
          sinais.push({ tenantId, tipo: "auto_compra", refEvento: orderId, detalhe: { order_id: orderId, coincidencia: c }, ocorridoEm });
          break;
        }
      }
      if (envelope.tipo === "order.paid" && payload["paga_via"] === "manual_auditado") {
        const t = await f.tenantETecto();
        const desde = new Date(agora.getTime() - p.diasDeTenantNovo * DIA);
        const manuais = await f.manuais(desde);
        if (burlaProvavel({ activoDesde: t.activoDesde, tectoMinor: t.tectoMinor, pedidos: manuais }, agora, p)) {
          // Por tenant: um sinal, e não um por pedido a seguir ao terceiro.
          sinais.push({ tenantId, tipo: "burla_provavel", refEvento: tenantId, detalhe: { contagem: manuais.length }, ocorridoEm });
        }
      }
      break;
    }
    case "payment.manual_confirmed": {
      const orderId = texto(payload["order_id"]);
      const desde = new Date(agora.getTime() - p.diasDasQueixas * DIA);
      const manuais = await f.manuais(desde);
      const confirmacoes = manuais.map((m) => ({ orderId: m.orderId, criadoEm: m.criadoEm, confirmadoEm: m.pagaEm }));
      const esta = confirmacoes.find((c) => c.orderId === orderId);
      const rapida = esta !== undefined && esta.confirmadoEm.getTime() - esta.criadoEm.getTime() < p.segundosDeConfirmacao * 1000;
      if (rapida && confirmacaoSuspeita(confirmacoes, p)) {
        sinais.push({ tenantId, tipo: "confirmacao_suspeita", refEvento: orderId, detalhe: { order_id: orderId }, ocorridoEm });
      }
      break;
    }
    case "query.handoff": {
      if (payload["motivo"] !== MOTIVO_DE_RECLAMACAO) break;
      const { queixas, pagos } = await f.queixas(new Date(agora.getTime() - p.diasDasQueixas * DIA));
      const n = queixasQueContam(queixas, pagos, agora, p);
      if (queixaRecorrente(n, p)) {
        sinais.push({ tenantId, tipo: "queixa_recorrente", refEvento: envelope.id, detalhe: { contagem: n }, ocorridoEm });
      }
      break;
    }
    case "screening.violation_detected": {
      sinais.push({
        tenantId,
        tipo: "violacao_de_categoria",
        refEvento: envelope.id,
        detalhe: { sku: texto(payload["sku"]), versao_politica: texto(payload["versao_politica"]) },
        ocorridoEm,
      });
      break;
    }
    default:
      // `order.delivered` e `payment.confirmed`: consumidos e marcados, sem sinal.
      break;
  }
  return sinais;
}

/**
 * O `Efeito` do consumidor de T&S. Grava cada sinal (idempotente) e, se for
 * novo, corre a escada automática — `aviso` e `limitacao`, nunca mais.
 */
export function efeitoDeTrust(o: OpcoesDoTrust = {}): Efeito {
  const politica = o.politica ?? POLITICA_DE_RISCO;
  const relogio = o.relogio ?? (() => new Date());
  return async (bd, envelope) => {
    const agora = relogio();
    const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustSql(bd, "app"), politica, relogio: () => agora });
    for (const s of await sinaisDoEvento(bd, envelope, agora, politica)) {
      const r = await servico.registar(s);
      if (r.repetido) continue;
      o.contadores?.sinal(s.tipo);
      for (const x of r.sancoes) o.contadores?.sancao(x.passo, x.origem);
    }
  };
}

/** A não-entrega: `paga` sem `entregue` há mais de 7 dias. Corre como `kamba_batch`. */
export async function varrerNaoEntregas(bd: ClienteSql, o: OpcoesDoTrust = {}): Promise<number> {
  const p = o.politica ?? POLITICA_DE_RISCO;
  const agora = (o.relogio ?? (() => new Date()))();
  const corte = new Date(agora.getTime() - p.diasSemEntrega * DIA);
  const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustSql(bd, "lote"), politica: p, relogio: () => agora });
  let n = 0;
  for (const l of (await bd.query(SQL_NAO_ENTREGUES, [corte])).rows) {
    const pagaEm = data(l["paga_at"]);
    if (!naoEntregue(pagaEm, null, agora, p)) continue;
    const orderId = String(l["order_id"]);
    const r = await servico.registar({ tenantId: String(l["tenant_id"]), tipo: "nao_entrega", refEvento: orderId, detalhe: { order_id: orderId }, ocorridoEm: agora });
    if (!r.repetido) {
      n++;
      o.contadores?.sinal("nao_entrega");
      for (const x of r.sancoes) o.contadores?.sancao(x.passo, x.origem);
    }
  }
  return n;
}

/** A foto repetida noutro tenant: informativa, peso 0. Corre como `kamba_batch`. */
export async function varrerFotos(bd: ClienteSql, o: OpcoesDoTrust = {}): Promise<number> {
  const p = o.politica ?? POLITICA_DE_RISCO;
  const agora = (o.relogio ?? (() => new Date()))();
  const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustSql(bd, "lote"), politica: p, relogio: () => agora });
  let n = 0;
  for (const l of (await bd.query(SQL_FOTOS_REPETIDAS)).rows) {
    const r = await servico.registar({
      tenantId: String(l["tenant_id"]),
      tipo: "foto_repetida",
      refEvento: String(l["ingestao_id"]),
      detalhe: { contagem: inteiro(l["contagem"]) },
      ocorridoEm: agora,
    });
    if (!r.repetido) {
      n++;
      o.contadores?.sinal("foto_repetida");
    }
  }
  return n;
}

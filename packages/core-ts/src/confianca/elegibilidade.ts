/**
 * Confiança gradual — que pedidos contam para subir (KAM-096, critérios 3 e 4).
 *
 * Funções puras: os pedidos chegam já lidos (`./sql.ts`) e a decisão é sobre
 * eles e sobre o instante. Um pedido conta se, **todas** juntas:
 *
 * 1. foi entregue com confirmação do **cliente** (não do dono nem do estafeta);
 * 2. foi entregue **depois do marco** — o início do nível actual ou o último
 *    facto negativo, o que for mais tarde: uma descida não se reverte sem nova
 *    elegibilidade completa (critério 5);
 * 3. passou a janela anti-fraude sem disputa (14 dias, *proposta*);
 * 4. amadureceu dentro da janela móvel (30 dias, *proposta*): o fim da janela
 *    anti-fraude caiu nos últimos 30 dias;
 * 5. vale pelo menos o valor mínimo (10 000 Kz, *proposta*);
 * 6. o comprador está marcado `independente` pelo KAM-097. `por_avaliar` **não
 *    conta**: sem a marca, fecha em falha.
 *
 * E a subida pede, entre os que contam, pedidos **e** compradores distintos
 * suficientes, com no máximo **um** pedido por comprador e por dia — uma rajada
 * no mesmo dia conta uma vez (adversarial (c)). O dia é o de `Africa/Luanda`,
 * que não tem hora de Verão: UTC+1 fixo.
 */

import type { Independencia } from "../trust/contrato.ts";
import type { ConfiguracaoDaConfianca } from "./config.ts";

const DIA_MS = 86_400_000;
const LUANDA_MS = 3_600_000;

/** Um pedido entregue, como o recálculo o lê. */
export interface PedidoCandidato {
  readonly orderId: string;
  /** O contacto **canónico** do comprador (a cadeia de fusões do KAM-008). */
  readonly compradorRef: string;
  readonly valorMinor: bigint;
  /** Quando a encomenda foi criada: é o dia da rajada. */
  readonly criadoEm: Date;
  readonly entregueEm: Date;
  readonly confirmadoPeloCliente: boolean;
  /** Entrou em `em_disputa` antes de a janela anti-fraude fechar. */
  readonly disputaNaJanela: boolean;
  readonly independencia: Independencia;
}

/** Porque é que um pedido não conta. A primeira razão que falha, pela ordem do cabeçalho. */
export const MOTIVOS_DE_EXCLUSAO = [
  "sem_confirmacao_do_cliente",
  "anterior_ao_marco",
  "janela_anti_fraude_aberta",
  "fora_da_janela_movel",
  "disputa",
  "abaixo_do_valor_minimo",
  "nao_independente",
  "por_avaliar",
] as const;
export type MotivoDeExclusao = (typeof MOTIVOS_DE_EXCLUSAO)[number];

export type Avaliacao = { readonly conta: true } | { readonly conta: false; readonly motivo: MotivoDeExclusao };

/** O fim da janela anti-fraude de um pedido. */
export function fimDaJanelaAntiFraude(p: Pick<PedidoCandidato, "entregueEm">, c: ConfiguracaoDaConfianca): Date {
  return new Date(p.entregueEm.getTime() + c.patamares.janelaAntiFraudeDias.valor * DIA_MS);
}

/** Este pedido conta para subir, em `agora`, depois de `marco`? */
export function avaliarPedido(
  p: PedidoCandidato,
  c: ConfiguracaoDaConfianca,
  agora: Date,
  marco: Date,
): Avaliacao {
  const nao = (motivo: MotivoDeExclusao): Avaliacao => ({ conta: false, motivo });
  if (!p.confirmadoPeloCliente) return nao("sem_confirmacao_do_cliente");
  if (p.entregueEm.getTime() <= marco.getTime()) return nao("anterior_ao_marco");
  const fim = fimDaJanelaAntiFraude(p, c).getTime();
  if (fim > agora.getTime()) return nao("janela_anti_fraude_aberta");
  if (fim <= agora.getTime() - c.patamares.janelaMovelDias.valor * DIA_MS) return nao("fora_da_janela_movel");
  if (p.disputaNaJanela) return nao("disputa");
  if (p.valorMinor < c.patamares.valorMinimoMinor.valor) return nao("abaixo_do_valor_minimo");
  if (p.independencia === "nao_independente") return nao("nao_independente");
  if (p.independencia !== "independente") return nao("por_avaliar");
  return { conta: true };
}

/** O dia de calendário em Luanda de um instante, `AAAA-MM-DD`. */
export function diaEmLuanda(instante: Date): string {
  return new Date(instante.getTime() + LUANDA_MS).toISOString().slice(0, 10);
}

export interface Contagem {
  /** Pedidos que contam, já com a rajada reduzida a um por comprador e dia. */
  readonly pedidos: number;
  readonly compradores: number;
}

/** Quantos pedidos e compradores contam, em `agora`, depois de `marco`. */
export function contar(
  pedidos: readonly PedidoCandidato[],
  c: ConfiguracaoDaConfianca,
  agora: Date,
  marco: Date,
): Contagem {
  const porCompradorEDia = new Set<string>();
  const compradores = new Set<string>();
  for (const p of pedidos) {
    if (!avaliarPedido(p, c, agora, marco).conta) continue;
    porCompradorEDia.add(`${p.compradorRef}|${diaEmLuanda(p.criadoEm)}`);
    compradores.add(p.compradorRef);
  }
  return { pedidos: porCompradorEDia.size, compradores: compradores.size };
}

/** A contagem chega para subir do nível 0 ao 1? */
export function cumpreSubida(n: Contagem, c: ConfiguracaoDaConfianca): boolean {
  return n.pedidos >= c.patamares.pedidosParaSubir.valor && n.compradores >= c.patamares.compradoresDistintos.valor;
}

/**
 * Desde quando é preciso ler pedidos para decidir em `agora`: a janela móvel
 * mais a anti-fraude. Um pedido entregue antes disto já não pode contar.
 */
export function inicioDaLeitura(c: ConfiguracaoDaConfianca, agora: Date): Date {
  const dias = c.patamares.janelaMovelDias.valor + c.patamares.janelaAntiFraudeDias.valor;
  return new Date(agora.getTime() - dias * DIA_MS);
}

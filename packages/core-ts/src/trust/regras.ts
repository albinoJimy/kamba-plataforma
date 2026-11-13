/**
 * As regras de Trust & Safety, como funções puras (KAM-097).
 *
 * Nenhuma lê a base nem o relógio: recebem uma **fotografia** dos factos e o
 * instante, e devolvem o que o critério manda. É a lição do KAM-060 — uma
 * função que lesse a base duas vezes podia ler duas bases diferentes, e um
 * ensaio que a corra duas vezes sobre a mesma fotografia mede a regra e não o
 * plano do PostgreSQL. Quem lê os factos é o `./efeito.ts` (do evento) e o
 * `./sql.ts` (das varreduras).
 *
 * ## Todos os números são propostas
 *
 * Os 14 dias de tenant novo, os 80% do tecto, os 30 s, as 20 referências, o
 * intervalo de 1% a 100× da mediana, as 2 queixas em 30 dias, os 7 dias sem
 * entrega, os pesos, a meia-vida e os dois limiares da escada: `POLITICA_DE_RISCO`,
 * versionada em SemVer. Nenhum foi calibrado; a calibração é do fim do Piloto
 * (critério de saída do EPIC-09).
 *
 * ## O que estas regras não conseguem ver, e é limitação e não defeito
 *
 * **A segunda SIM desconhecida.** Um dono que compra a si próprio com um
 * número que nunca registou em lado nenhum não tem HMAC, contacto nem BSUID em
 * comum com o que a plataforma sabe dele: `autoCompra` devolve `null`, e não
 * há regra local que o mude. A defesa é a do KAM-096 — a subida de tecto exige
 * três compradores distintos e a confirmação de entrega pelo cliente —, e não
 * esta. Está escrito no `docs/tecnica/10` §8.3, que é onde o bloco manda.
 */

/** Os tipos de sinal. Lista **fechada**; domínio de `ts_signal.tipo`. */
export const TIPOS_DE_SINAL = [
  "auto_compra",
  "burla_provavel",
  "confirmacao_suspeita",
  "foto_repetida",
  "preco_anomalo",
  "queixa_recorrente",
  "nao_entrega",
  "mudanca_de_conta",
  "violacao_de_categoria",
] as const;
export type TipoDeSinal = (typeof TIPOS_DE_SINAL)[number];

export const SEVERIDADES = ["baixa", "media", "alta"] as const;
export type Severidade = (typeof SEVERIDADES)[number];

/**
 * A severidade de cada tipo, **fixa**. Quem escreve um sinal não a escolhe: a
 * base impõe o mesmo par por `CHECK` (revisão `0053`), e é isso que torna
 * inócuo um sinal escrito antes do consumidor com a mesma chave — sai igual.
 */
export const SEVERIDADE_DO_TIPO: Readonly<Record<TipoDeSinal, Severidade>> = {
  auto_compra: "alta",
  burla_provavel: "alta",
  confirmacao_suspeita: "media",
  foto_repetida: "baixa",
  preco_anomalo: "baixa",
  queixa_recorrente: "media",
  nao_entrega: "media",
  mudanca_de_conta: "alta",
  violacao_de_categoria: "alta",
};

/** A escada, por ordem. Domínio de `ts_sanction.passo`. */
export const PASSOS = ["aviso", "limitacao", "suspensao", "encerramento"] as const;
export type Passo = (typeof PASSOS)[number];

/** Os passos que uma máquina pode dar. Os outros dois são só por decisão humana. */
export const PASSOS_AUTOMATICOS: readonly Passo[] = ["aviso", "limitacao"];

/** A política de risco. Artefacto comportamental: muda-se com a versão. */
export interface PoliticaDeRisco {
  /** SemVer. Vai para o `detalhe` de cada sanção automática. */
  readonly versao: string;
  /** Peso de cada tipo no risco composto. O `foto_repetida` é informativo: peso 0. */
  readonly pesos: Readonly<Record<TipoDeSinal, number>>;
  /** Meia-vida do decaimento, em dias. */
  readonly meiaVidaDias: number;
  /** Risco a partir do qual se dá o `aviso` automático. */
  readonly limiarDoAviso: number;
  /** Risco a partir do qual se dá a `limitacao` automática. */
  readonly limiarDaLimitacao: number;
  /** Dias desde a activação em que o tenant é «novo». */
  readonly diasDeTenantNovo: number;
  /** Fracção do tecto a partir da qual um pedido está «próximo do tecto». */
  readonly fracaoDoTecto: number;
  /** Pedidos manuais próximos do tecto que fazem a `burla_provavel`. */
  readonly pedidosProximosDoTecto: number;
  /** Segundos entre a criação e a confirmação pelo dono abaixo dos quais é suspeito. */
  readonly segundosDeConfirmacao: number;
  /** Confirmações rápidas que fazem a `confirmacao_suspeita` («repetido»). */
  readonly confirmacoesRapidas: number;
  /** Produtos de referência da categoria abaixo dos quais o preço não se avalia. */
  readonly referenciasMinimas: number;
  /** O intervalo aceitável do preço, em fracção da mediana: [min, max]. */
  readonly precoMinimoDaMediana: number;
  readonly precoMaximoDaMediana: number;
  /** Queixas ou disputas de compradores pagos, na janela, que fazem a `queixa_recorrente`. */
  readonly queixas: number;
  readonly diasDasQueixas: number;
  /** Dias de `paga` sem `entregue` que fazem a `nao_entrega`. */
  readonly diasSemEntrega: number;
}

export const POLITICA_DE_RISCO: PoliticaDeRisco = {
  versao: "1.0.0",
  pesos: {
    auto_compra: 35,
    burla_provavel: 35,
    confirmacao_suspeita: 15,
    foto_repetida: 0,
    preco_anomalo: 5,
    queixa_recorrente: 20,
    nao_entrega: 15,
    mudanca_de_conta: 30,
    violacao_de_categoria: 35,
  },
  meiaVidaDias: 30,
  limiarDoAviso: 30,
  limiarDaLimitacao: 60,
  diasDeTenantNovo: 14,
  fracaoDoTecto: 0.8,
  pedidosProximosDoTecto: 3,
  segundosDeConfirmacao: 30,
  confirmacoesRapidas: 2,
  referenciasMinimas: 20,
  precoMinimoDaMediana: 0.01,
  precoMaximoDaMediana: 100,
  queixas: 2,
  diasDasQueixas: 30,
  diasSemEntrega: 7,
};

const DIA = 86_400_000;

// ----------------------------------------------------------------- auto-compra

/** O que se sabe de quem é o dono: os seus identificadores pseudónimos neste tenant. */
export interface IdentidadeDoDono {
  readonly contactIds: readonly string[];
  readonly phoneHmacs: readonly string[];
  readonly bsuidHmacs: readonly string[];
}

/** O comprador de um pedido, pelos mesmos identificadores. */
export interface Comprador {
  readonly contactId: string | null;
  readonly phoneHmac: string | null;
  readonly bsuidHmacs: readonly string[];
}

export type Coincidencia = "contact_id" | "phone_hmac" | "bsuid_hmac";

/**
 * O comprador é o dono? Devolve **por onde** coincidiu, ou `null`.
 *
 * Compara pseudónimos, nunca telefones: o HMAC do telefone é calculado sobre o
 * E.164 normalizado (`identity/contactos.ts`), e por isso formatos diferentes
 * do mesmo número dão o mesmo HMAC — o ensaio adversarial (a) mede-o com a
 * função de produção. Um valor vazio nunca coincide: dois `null` não são o
 * mesmo comprador.
 */
export function autoCompra(comprador: Comprador, dono: IdentidadeDoDono): Coincidencia | null {
  if (comprador.contactId !== null && comprador.contactId !== "" && dono.contactIds.includes(comprador.contactId)) {
    return "contact_id";
  }
  if (comprador.phoneHmac !== null && comprador.phoneHmac !== "" && dono.phoneHmacs.includes(comprador.phoneHmac)) {
    return "phone_hmac";
  }
  if (comprador.bsuidHmacs.some((b) => b !== "" && dono.bsuidHmacs.includes(b))) return "bsuid_hmac";
  return null;
}

// --------------------------------------------------------------------- burla

/** Um pedido manual do tenant, pelo valor e pela criação. */
export interface PedidoManual {
  readonly orderId: string;
  readonly totalMinor: number;
  readonly criadoEm: Date;
}

/**
 * Tenant novo (≤ 14 dias desde a activação) com ≥ 3 pedidos manuais próximos
 * do tecto. Sem data de activação não é «novo»: não se sabe, e um sinal alto
 * sobre um facto desconhecido era um falso positivo garantido.
 */
export function burlaProvavel(
  f: { readonly activoDesde: Date | null; readonly tectoMinor: number; readonly pedidos: readonly PedidoManual[] },
  agora: Date,
  p: PoliticaDeRisco = POLITICA_DE_RISCO,
): boolean {
  if (f.activoDesde === null || f.tectoMinor <= 0) return false;
  if (agora.getTime() - f.activoDesde.getTime() > p.diasDeTenantNovo * DIA) return false;
  const limiar = f.tectoMinor * p.fracaoDoTecto;
  const proximos = new Set(f.pedidos.filter((x) => x.totalMinor >= limiar && x.totalMinor <= f.tectoMinor).map((x) => x.orderId));
  return proximos.size >= p.pedidosProximosDoTecto;
}

/** Uma confirmação manual: quando o pedido nasceu e quando o dono o deu por pago. */
export interface ConfirmacaoManual {
  readonly orderId: string;
  readonly criadoEm: Date;
  readonly confirmadoEm: Date;
}

/**
 * Pagamento confirmado pelo dono em < 30 s depois da criação, **repetido**:
 * duas confirmações rápidas de pedidos distintos. Uma só é um dono atento.
 */
export function confirmacaoSuspeita(confirmacoes: readonly ConfirmacaoManual[], p: PoliticaDeRisco = POLITICA_DE_RISCO): boolean {
  const rapidas = new Set(
    confirmacoes
      .filter((c) => {
        const d = c.confirmadoEm.getTime() - c.criadoEm.getTime();
        return d >= 0 && d < p.segundosDeConfirmacao * 1000;
      })
      .map((c) => c.orderId),
  );
  return rapidas.size >= p.confirmacoesRapidas;
}

// ------------------------------------------------------------------ listagem

/** A mediana de valores inteiros em unidade menor. Lista vazia é erro de quem chama. */
export function mediana(valores: readonly number[]): number {
  if (valores.length === 0) throw new RangeError("mediana de lista vazia");
  const o = [...valores].sort((a, b) => a - b);
  const meio = (o.length - (o.length % 2)) / 2;
  return o.length % 2 === 1 ? (o[meio] ?? 0) : ((o[meio - 1] ?? 0) + (o[meio] ?? 0)) / 2;
}

export type AvaliacaoDoPreco = "sem_referencia" | "normal" | "anomalo";

/**
 * O preço está fora de [1%, 100×] da mediana da categoria? Só com ≥ 20
 * produtos de referência: abaixo disso a mediana é ruído e a resposta é
 * `sem_referencia`, nunca `anomalo`.
 */
export function avaliarPreco(precoMinor: number, referencias: readonly number[], p: PoliticaDeRisco = POLITICA_DE_RISCO): AvaliacaoDoPreco {
  if (referencias.length < p.referenciasMinimas) return "sem_referencia";
  const m = mediana(referencias);
  if (m <= 0) return "sem_referencia";
  return precoMinor < m * p.precoMinimoDaMediana || precoMinor > m * p.precoMaximoDaMediana ? "anomalo" : "normal";
}

// --------------------------------------------------------------- reclamações

/** Uma queixa ou disputa, por quem a fez. */
export interface Queixa {
  readonly contactId: string | null;
  readonly em: Date;
}

/**
 * Quantas queixas **contam**: só as de contactos com pedido pago neste tenant
 * (anti-retaliação, ensaio adversarial (d)), dentro da janela, uma por
 * contacto. Uma queixa sem contacto não conta: não se sabe se pagou.
 */
export function queixasQueContam(
  queixas: readonly Queixa[],
  compradoresPagos: ReadonlySet<string>,
  agora: Date,
  p: PoliticaDeRisco = POLITICA_DE_RISCO,
): number {
  const desde = agora.getTime() - p.diasDasQueixas * DIA;
  const contactos = new Set<string>();
  for (const q of queixas) {
    if (q.contactId === null || !compradoresPagos.has(q.contactId)) continue;
    if (q.em.getTime() < desde || q.em.getTime() > agora.getTime()) continue;
    contactos.add(q.contactId);
  }
  return contactos.size;
}

export function queixaRecorrente(n: number, p: PoliticaDeRisco = POLITICA_DE_RISCO): boolean {
  return n >= p.queixas;
}

/** Um pedido `paga` está sem `entregue` há mais de 7 dias? */
export function naoEntregue(pagaEm: Date, entregueEm: Date | null, agora: Date, p: PoliticaDeRisco = POLITICA_DE_RISCO): boolean {
  return entregueEm === null && agora.getTime() - pagaEm.getTime() > p.diasSemEntrega * DIA;
}

// ---------------------------------------------------------------- risco e escada

/** Um sinal, para o risco: o tipo e quando ocorreu. */
export interface SinalParaRisco {
  readonly tipo: TipoDeSinal;
  readonly ocorridoEm: Date;
}

/**
 * `risco_ts = min(100, Σ peso(sinal) × decaimento)`, com decaimento
 * exponencial de meia-vida `meiaVidaDias`. Um sinal do futuro conta inteiro
 * (decaimento 1), nunca mais do que inteiro. Arredonda para baixo: o limiar
 * compara-se com um inteiro.
 */
export function risco(sinais: readonly SinalParaRisco[], agora: Date, p: PoliticaDeRisco = POLITICA_DE_RISCO): number {
  let soma = 0;
  for (const s of sinais) {
    const idade = Math.max(0, agora.getTime() - s.ocorridoEm.getTime()) / DIA;
    soma += p.pesos[s.tipo] * 0.5 ** (idade / p.meiaVidaDias);
  }
  return Math.min(100, Math.floor(soma));
}

/** A posição de um passo na escada; `-1` para «nenhum». */
export function ordem(passo: Passo | null): number {
  return passo === null ? -1 : PASSOS.indexOf(passo);
}

/**
 * O **próximo** passo automático que o risco pede, ou `null`. **Nunca**
 * `suspensao` nem `encerramento`, nunca um passo igual ou abaixo do que já está
 * em vigor, e **um degrau de cada vez**: a máquina não salta, porque saltar
 * exige justificação escrita e a máquina não escreve justificações. Um risco de
 * 60 sem nada em vigor dá o `aviso`, e quem chama volta a perguntar — e recebe a
 * `limitacao`, que já não é salto.
 */
export function passoAutomatico(r: number, emVigor: Passo | null, p: PoliticaDeRisco = POLITICA_DE_RISCO): Passo | null {
  const pedido: Passo | null = r >= p.limiarDaLimitacao ? "limitacao" : r >= p.limiarDoAviso ? "aviso" : null;
  if (pedido === null || ordem(pedido) <= ordem(emVigor)) return null;
  return PASSOS[ordem(emVigor) + 1] ?? null;
}

/** Porque é que uma sanção proposta não se aceita. */
export const MOTIVOS_DE_RECUSA_DA_SANCAO = ["sem_motivo", "salto_sem_justificacao", "grave_automatica", "passo_desconhecido"] as const;
export type MotivoDeRecusaDaSancao = (typeof MOTIVOS_DE_RECUSA_DA_SANCAO)[number];

/**
 * As regras de uma sanção, antes de existir: motivo sempre; justificação
 * escrita quando salta passos (mais do que um degrau acima do que está em
 * vigor); e nada de grave por máquina. `null` quando se aceita.
 */
export function recusaDaSancao(s: {
  readonly passo: string;
  readonly origem: "automatica" | "humana";
  readonly motivoInterno: string;
  readonly justificacaoDoSalto: string | null;
  readonly emVigor: Passo | null;
}): MotivoDeRecusaDaSancao | null {
  if (!(PASSOS as readonly string[]).includes(s.passo)) return "passo_desconhecido";
  const passo = s.passo as Passo;
  if (s.motivoInterno.trim() === "") return "sem_motivo";
  if (s.origem === "automatica" && !PASSOS_AUTOMATICOS.includes(passo)) return "grave_automatica";
  const salta = ordem(passo) > ordem(s.emVigor) + 1;
  if (salta && (s.justificacaoDoSalto === null || s.justificacaoDoSalto.trim() === "")) return "salto_sem_justificacao";
  return null;
}

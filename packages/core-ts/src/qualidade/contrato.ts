/**
 * O vocabulário da qualidade do canal: tipos, portas e listas fechadas
 * (KAM-021).
 *
 * Os nomes são os do §3.18 do dicionário (emenda 1.27) e os domínios são os
 * mesmos que a revisão `0014` impõe por `CHECK`. Quando um valor aparece nos
 * dois sítios é porque tem de aparecer: o `CHECK` é a última barreira e esta
 * lista é a primeira, e um teste compara as duas — a `0008` e a `0009` pagaram
 * a lição de as deixar divergir.
 *
 * ## A tradução do vocabulário da Meta faz-se na fronteira
 *
 * A Meta manda `GREEN`, `YELLOW`, `RED` em maiúsculas; o §2 do dicionário manda
 * «estados em minúsculas, snake_case, sem acentos» e prevalece sobre
 * `docs/tecnica/`. A regra que a revisão `0010` escreveu para o `state` das
 * mensagens vale aqui: **a base é nossa, e a tradução faz-se numa função com
 * teste** (`traduzirQualidade`).
 *
 * Mas há duas colunas e elas guardam coisas diferentes, e a distinção é o
 * centro do critério 1:
 *
 * * **`tenant_channels.quality_rating` guarda o canónico** — `green`, `yellow`,
 *   `red`. É o estado corrente, é o que o resto do sistema lê, e um valor que
 *   não se reconhece **não** o altera.
 * * **`channel_quality_log.valor_novo` guarda o que chegou, tal e qual** —
 *   `GREEN`, e também `PURPLE` se a Meta um dia o mandar. É o registo, e o
 *   critério 1 manda «outro valor registado como desconhecido sem falhar»:
 *   guardar o bruto é o que permite descobrir depois o que ela passou a mandar.
 *   Um domínio fechado nesta coluna transformava uma mudança da Meta numa falha
 *   de inserção.
 *
 * ## As quatro portas
 *
 * O tratador não abre ligação nenhuma que não precise e não implementa nada que
 * seja de outro ticket. O que ele recebe:
 *
 * 1. **`ClienteSql`** — a ligação de `kamba_app`, **com contexto de tenant**. É
 *    o papel que a `0014` autoriza a escrever `channel_quality_log` (`SELECT` e
 *    `INSERT`, sem `UPDATE`) e `tenant_channels`.
 * 2. **`Emitir`** — quem publica o `channel.updated`. Porta e não chamada
 *    directa porque a emissão é `platform.evt_emitir` na transacção de quem
 *    chama, e quem a liga é o serviço (a regra do KAM-005 e do ADR-009).
 * 3. **`Invalidar`** — a invalidação da *cache* do CHR. O critério 2 pede «≤ 5
 *    s», e o `ResolvedorDeCanal` tem `invalidarCanal(channelId)` para isso.
 *    **Dentro do processo é imediato; entre processos depende de um consumidor
 *    de `channel.updated` que não existe** (é KAM-006/KAM-025), e até lá vale o
 *    TTL de 60 s que o `chr/contrato.ts` declara. Está na secção de verificação.
 * 4. **`Logger`** — opcional, e sujeito à lista branca de nove campos.
 */

/**
 * O cliente de SQL que este módulo precisa.
 *
 * `readonly rows` como o `ClienteSql` do KAM-015 e o `ClienteDoChr` do
 * KAM-014, e pela mesma razão: este módulo nunca altera o que lê, e um tipo com
 * `rows` mutável obrigava quem o liga a provar que não o altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * Os quatro *webhooks* que a gestão de canal consome.
 *
 * São exactamente os quatro `kind` que o `DESTINO_POR_KIND` do
 * `entrada/contrato.ts` manda para `gestao_de_canal`, e o mesmo domínio que o
 * `channel_quality_log_evento_ck` da revisão `0014` impõe. **Há um teste que
 * compara as três listas**, porque três cópias de um domínio divergem no dia em
 * que uma delas mudar.
 */
export const EVENTOS_DE_CANAL = [
  "phone_number_quality_update",
  "business_capability_update",
  "account_alerts",
  "message_template_quality_update",
] as const;
export type EventoDeCanal = (typeof EVENTOS_DE_CANAL)[number];

/**
 * As três qualidades, **em minúsculas**: o canónico.
 *
 * É o mesmo domínio que o `message_templates.quality` da revisão `0010` já usa,
 * e é deliberado: a qualidade de um número e a de um template medem a mesma
 * coisa e não têm razão para ter dois alfabetos.
 */
export const QUALIDADES = ["green", "yellow", "red"] as const;
export type Qualidade = (typeof QUALIDADES)[number];

/**
 * O que a Meta manda, e o que isso significa em canónico.
 *
 * Mapa explícito e não um `toLowerCase()`, por duas razões. A primeira é que
 * `toLowerCase()` aceitaria **qualquer** cadeia e o critério 1 pede que um
 * valor desconhecido seja registado como desconhecido — isto é, que haja uma
 * lista contra a qual ele seja desconhecido. A segunda é que a Meta já mudou
 * este vocabulário uma vez (o estado «Flagged» foi eliminado a 2025-10-07,
 * CONFIRMADO `E1` §5) e um mapa é onde se vê o que se sabe.
 */
const CANONICO_DA_META: Readonly<Record<string, Qualidade>> = {
  GREEN: "green",
  YELLOW: "yellow",
  RED: "red",
};

/**
 * A qualidade canónica de um valor da Meta, ou `null` quando não se reconhece.
 *
 * `null` **não é um erro**: é o que o critério 1 chama «registado como
 * desconhecido sem falhar». Quem chama guarda o bruto no registo e **não**
 * altera o `quality_rating` — porque mudar o estado corrente para um valor que
 * não se compreende era pior do que não o mudar.
 */
export function traduzirQualidade(bruto: unknown): Qualidade | null {
  if (typeof bruto !== "string") return null;
  return CANONICO_DA_META[bruto] ?? null;
}

/**
 * Os escalões de mensagens que a Meta anuncia, e o tecto de cada um.
 *
 * **CONFIRMADO** (`E1` §5): o limite é por **portfólio** e conta utilizadores
 * únicos em 24 h móveis, com a escada 250 → 2.000 → 10.000 → 100.000 →
 * ilimitado; o `messaging_limit_tier` está **deprecado** em favor do
 * `whatsapp_business_manager_messaging_limit`.
 *
 * Os **nomes** dos escalões são os que o gerador do KAM-024 produz
 * (`tools/meta-sim/src/campos.ts`), que é a única fonte deste repositório que
 * corre. O bloco do KAM-021 escreve `TIER_2000` no exemplo e o gerador escreve
 * `TIER_2K`: a divergência está em `docs/dividas-documentais.md` e **não se
 * resolve inventando um sinónimo** — um escalão que não esteja aqui é
 * desconhecido, e o rácio fica `null`.
 *
 * O `TIER_UNLIMITED` vale `Infinity` de propósito: é o que faz o rácio dar `0`
 * por aritmética em vez de por um caso especial.
 */
export const TECTO_POR_ESCALAO: Readonly<Record<string, number>> = {
  TIER_250: 250,
  TIER_1K: 1_000,
  TIER_2K: 2_000,
  TIER_10K: 10_000,
  TIER_100K: 100_000,
  TIER_UNLIMITED: Number.POSITIVE_INFINITY,
};

/**
 * A fracção do escalão a partir da qual se avisa.
 *
 * `0,8` é o mesmo limiar do *free tier* do KAM-023, e isso não é coincidência:
 * o `docs/tecnica/09` (RB-K05) usa 80% para os dois. **Está escrito como
 * fracção e não como um número por escalão** para que não possa divergir do
 * tecto — o critério 7 dá o exemplo «200 contactos distintos com `TIER_250` dá
 * 0,8 e dispara alerta», e 200/250 é exactamente a fracção.
 */
export const FRACCAO_DE_AVISO = 0.8;

/** Os estados do canal que este módulo escreve. Subconjunto do `CHECK` da `0001`. */
export const ESTADO_RESTRITO = "restrito";
export const ESTADO_ACTIVO = "ativo";

/**
 * O motivo com que este ticket restringe um canal.
 *
 * É um dos três do domínio que a revisão `0013` criou (KAM-023), e o nome é o
 * que o `MOTIVOS_DE_RESTRICAO` do `metering/contrato.ts` já declara. **Este
 * módulo levanta só este motivo e nunca outro:** um canal restrito por falta de
 * método de pagamento não volta a `ativo` por a qualidade ter melhorado, e
 * limpar a marca de outro ticket ao passar era apagar uma decisão que não é
 * nossa — a mesma regra que a `levantarRestricao` do KAM-023 escreveu pelo
 * outro lado.
 */
export const MOTIVO_DE_QUALIDADE = "quality";

/** Quem publica o `channel.updated`. Ver a nota do módulo. */
export type Emitir = (
  tenantId: string,
  channelId: string,
  phoneNumberId: string,
  motivo: string,
) => Promise<void>;

/**
 * Quem esquece o canal na *cache* do CHR.
 *
 * `invalidarCanal(channelId)` do `ResolvedorDeCanal`. Devolve `void` porque o
 * tratador não tem o que fazer com a resposta: um canal que não estava em
 * *cache* não é um erro.
 */
export type Invalidar = (channelId: string) => void;

/** O canal, como as consultas deste módulo o lêem. */
export interface Canal {
  readonly tenantId: string;
  readonly channelId: string;
  readonly phoneNumberId: string;
  readonly estado: string;
  readonly qualityRating: string | null;
  readonly messagingLimit: string | null;
  readonly motivoRestricao: string | null;
}

/** O que o tratamento de um `phone_number_quality_update` produziu. */
export interface Transicao {
  /** `true` quando **este** evento foi o primeiro com esta chave. */
  readonly registou: boolean;
  /** A qualidade canónica, ou `null` quando a Meta mandou algo que não se reconhece. */
  readonly qualidade: Qualidade | null;
  /** `true` quando este evento passou o canal a `restrito`. */
  readonly restringiu: boolean;
  /** `true` quando este evento devolveu o canal a `ativo`. */
  readonly reposto: boolean;
  /** `true` quando este evento gerou o aviso de `yellow`. */
  readonly avisou: boolean;
}

/** O que o medidor de limites mediu. */
export interface Utilizacao {
  /** Utilizadores únicos contactados **por template** nas últimas 24 h. */
  readonly unicos: number;
  /** O escalão que a Meta anunciou, tal e qual. */
  readonly escalao: string | null;
  /**
   * `unicos / tecto`, ou `null` quando o escalão não se reconhece.
   *
   * `null` e não `0`: um escalão desconhecido não é um canal folgado. É a mesma
   * escolha que a `divergencia` do KAM-023 faz para o denominador zero —
   * «não sei» é informação melhor do que um número errado.
   */
  readonly racio: number | null;
  /** `true` quando o rácio atingiu ou passou os 80%. */
  readonly avisa: boolean;
}

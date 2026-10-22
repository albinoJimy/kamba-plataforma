/**
 * O vocabulário da saída de canal: tipos, portas e listas fechadas (KAM-015).
 *
 * Os nomes são os do §3.14 do dicionário (emenda 1.21) e os domínios são os
 * mesmos que a revisão `0010` impõe por `CHECK`. Quando um valor aparece nos
 * dois sítios, é porque tem de aparecer: o `CHECK` é a última barreira e esta
 * lista é a primeira, e um teste compara as duas — a `0008` e a `0009`
 * pagaram a lição de as deixar divergir.
 *
 * ## As quatro portas, e porque é que são portas
 *
 * O `ChannelAdapter` não abre ligação nenhuma que não precise, e não implementa
 * nada que seja de outro ticket. O que ele recebe:
 *
 * 1. **`ObterDestinatario`** — devolve o BSUID ou o telefone de um contacto.
 *    Só `kamba_identity` lê `contact_endpoints` (dicionário §3.2) e o adapter
 *    corre como `kamba_app`: dar-lhe uma quarta ligação era alargar o
 *    privilégio de quem envia ao de quem decifra. Quem liga a porta ao módulo
 *    de identidade é o serviço.
 * 2. **`PreSendGuard`** — o gancho que o KAM-018 implementa, chamado sob o
 *    *lock* da conversa antes de cada envio do bot. O que este ticket entrega é
 *    a porta e a **falha fechada**: sem guarda instalada, o envio do bot
 *    levanta em `KAMBA_ENV=ci`. Um gancho que falte e deixe passar é um gancho
 *    que não existe.
 * 3. **`EstadoDoFreeTier`** — quantas *service messages* já foram entregues
 *    neste número e neste mês. Quem mantém o contador é o KAM-023, que o «Fora
 *    de âmbito» deste ticket exclui; o adapter recebe o estado e calcula o
 *    custo com ele.
 * 4. **`ClienteDaMeta`** — o que fala com a Graph API. É porta para que a
 *    *suite* possa pôr o servidor falso do KAM-024 no lugar dela sem tocar em
 *    nada, e para que o `fetch` não entre no caminho de um teste unitário.
 */

/** O resultado de um `send` que não chegou a sair. */
export const WINDOW_CLOSED = "WINDOW_CLOSED";

/**
 * As quatro categorias que a Meta factura (§3.14; `docs/tecnica/01` §8.2).
 *
 * `service` é a mensagem livre dentro da janela; as outras três exigem
 * template. O `marketing` está aqui porque a tabela tem de poder **registar**
 * o que a Meta diz depois de uma recategorização — o que o Piloto recusa é
 * **enviar** nessa categoria, e recusar no envio é diferente de não saber ler.
 */
export const CATEGORIAS = ["service", "utility", "marketing", "authentication"] as const;
export type Categoria = (typeof CATEGORIAS)[number];

/** As categorias que o Piloto aceita enviar. O `marketing` fica de fora (critério 7). */
export const CATEGORIAS_DO_PILOTO: readonly Categoria[] = [
  "service",
  "utility",
  "authentication",
];

/**
 * O ciclo de vida de uma mensagem de saída (§3.14; `CHECK` da revisão `0010`).
 *
 * A ordem **é significativa**: é ela que define a monotonia do critério 3. Um
 * estado só avança para um de índice maior, e por isso `delivered` seguido de
 * `sent` fica `delivered`. O `failed` e o `suppressed_by_human` são terminais —
 * ver `ORDEM_DOS_ESTADOS`.
 */
export const ESTADOS = [
  "queued",
  "sent",
  "delivered",
  "read",
  "failed",
  "suppressed_by_human",
] as const;
export type Estado = (typeof ESTADOS)[number];

/**
 * A ordem de avanço dos estados, e o que é terminal.
 *
 * **Não é o índice em `ESTADOS`**, e a diferença importa: `failed` e
 * `suppressed_by_human` não são «depois de `read`», são **saídas**. Um
 * `delivered` que receba um `failed` fica `failed` (a Meta pode falhar a
 * entrega depois de a anunciar); um `failed` que receba um `delivered` fica
 * `failed`, porque é terminal.
 *
 * O `-1` dos terminais é o que faz `avancar` tratá-los à parte em vez de os
 * comparar por número — comparar daria «`failed` (4) é depois de `read` (3)»,
 * que é verdade por acidente, e «`suppressed_by_human` (5) é depois de
 * `failed` (4)», que não é verdade nenhuma.
 */
export const ORDEM_DOS_ESTADOS: Readonly<Record<Estado, number>> = {
  queued: 0,
  sent: 1,
  delivered: 2,
  read: 3,
  failed: -1,
  suppressed_by_human: -1,
};

/** Os estados de que uma mensagem não sai. */
export const TERMINAIS: readonly Estado[] = ["failed", "suppressed_by_human"];

/** O estado de aprovação de um template, em minúsculas (§3.14, divergência 4). */
export const ESTADOS_DE_TEMPLATE = [
  "pending",
  "approved",
  "rejected",
  "paused",
  "disabled",
] as const;
export type EstadoDeTemplate = (typeof ESTADOS_DE_TEMPLATE)[number];

/** A categoria de um template. Não há template `service`: essa é livre. */
export const CATEGORIAS_DE_TEMPLATE = ["utility", "marketing", "authentication"] as const;
export type CategoriaDeTemplate = (typeof CATEGORIAS_DE_TEMPLATE)[number];

/** A nota de qualidade de um template, em minúsculas. */
export const QUALIDADES = ["green", "yellow", "red"] as const;
export type Qualidade = (typeof QUALIDADES)[number];

/**
 * Os limites de forma que a Meta impõe, e que se verificam **antes** de
 * qualquer chamada HTTP (critério 7).
 *
 * CONFIRMADO (`E1` §5; `docs/tecnica/01` §8.2): botões ≤ 3, listas ≤ 10 linhas.
 * Verificar depois de chamar era gastar uma mensagem para descobrir o que se
 * sabia antes — e, com `130429` à porta, gastar débito também.
 */
export const MAXIMO_DE_BOTOES = 3;
export const MAXIMO_DE_LINHAS = 10;

/** O idioma base dos templates. A variante `pt_AO` não existe (NÃO VERIFICADO). */
export const IDIOMA_BASE = "pt_PT";

/** Como se endereça o destinatário de uma mensagem. */
export interface Destinatario {
  /** O BSUID, quando existe. É o caminho preferido (critério 9, DoD «Privacidade»). */
  readonly bsuid: string | null;
  /** O telefone, só quando não há BSUID. Nunca entra num registo. */
  readonly telefone: string | null;
}

/** O corpo de uma mensagem livre. */
export interface CorpoLivre {
  readonly tipo: "texto";
  readonly texto: string;
}

/** Uma resposta interactiva de botões. */
export interface CorpoDeBotoes {
  readonly tipo: "botoes";
  readonly texto: string;
  /** Cada botão é um par `(id, titulo)`. O AGR confia no `id`, nunca no título. */
  readonly botoes: readonly { readonly id: string; readonly titulo: string }[];
}

/** Uma resposta interactiva de lista. */
export interface CorpoDeLista {
  readonly tipo: "lista";
  readonly texto: string;
  readonly titulo: string;
  readonly linhas: readonly { readonly id: string; readonly titulo: string }[];
}

/** Um envio por template, com os seus parâmetros. */
export interface CorpoDeTemplate {
  readonly tipo: "template";
  readonly nome: string;
  readonly idioma: string;
  /** Os parâmetros do corpo, pela ordem. Texto já validado por quem chama. */
  readonly parametros: readonly string[];
}

export type Corpo = CorpoLivre | CorpoDeBotoes | CorpoDeLista | CorpoDeTemplate;

/** O que um chamador pede ao adapter. */
export interface Pedido {
  readonly tenantId: string;
  readonly channelId: string;
  readonly contactId: string;
  readonly conversationId: string;
  /** O `phone_number_id` da Meta, para o *token bucket* por canal. */
  readonly phoneNumberId: string;
  readonly idempotencyKey: string;
  readonly corpo: Corpo;
  /**
   * `true` quando quem envia é o bot, e é isso que faz o `PreSendGuard` ser
   * chamado. Um envio do dono ou de um humano no Chatwoot não passa pelo
   * guarda: o guarda existe para impedir o bot de interromper uma pessoa.
   */
  readonly doBot: boolean;
  /**
   * Quando começou o turno do AGR que produziu este envio. **KAM-018.**
   *
   * É o `turn.started_at` do pseudocódigo do critério 2 do KAM-018
   * (`guard(conv, turn)`), e é com ele que o `PreSendGuard` compara o
   * `conversations.last_human_activity_at`: se uma pessoa falou **depois** de o
   * turno começar, a resposta do bot é descartada (`docs/tecnica/01` §10.3).
   *
   * **Opcional, e o guarda do KAM-018 recusa um envio do bot que o não traga.**
   * Opcional porque este campo nasce depois do `Pedido` e porque um envio com
   * `doBot: false` — o `hnd/resposta.ts`, por exemplo — não tem turno nenhum nem
   * passa pelo guarda. Recusado porque a alternativa era desligar metade do
   * critério 2 em silêncio: ver `modos/guarda.ts` e o motivo `sem_turno` de
   * `reply_suppressed_total`.
   */
  readonly turnoIniciadoEm?: Date;
}

/** Porque é que um envio não saiu. */
export const MOTIVOS_DE_RECUSA = [
  WINDOW_CLOSED,
  "TEMPLATE_NOT_APPROVED",
  "TEMPLATE_BLOCKED",
  "MARKETING_NOT_ALLOWED",
  "TOO_MANY_BUTTONS",
  "TOO_MANY_ROWS",
  "NO_RECIPIENT",
  "GUARD_REFUSED",
  "RATE_LIMITED",
  "SEND_FAILED",
  /**
   * A matriz de estados do KAM-009 recusou (KAM-021, critério 9).
   *
   * **Um motivo e não um por estado**, e a escolha é deliberada: o que recusa é
   * a matriz, e ela decide por um **regime** que sai do par
   * (estado do *tenant*, estado do canal) — `restrito` por qualidade,
   * `suspenso` por T&S, `desligado` por `PARTNER_REMOVED`, `pendente` antes de
   * activar. Um motivo por estado dava seis etiquetas de métrica para uma
   * única causa, e quem lesse o painel não ficava a saber mais: o que ele
   * precisa de saber é que **o estado recusou**, e qual era o estado está no
   * canal, não na etiqueta.
   *
   * O nome segue o `estado_recusou` dos `DESFECHOS` do `chr/contrato.ts`, que é
   * a mesma decisão do outro lado do caminho.
   */
  "STATE_REFUSED",
] as const;
export type MotivoDeRecusa = (typeof MOTIVOS_DE_RECUSA)[number];

/** O que o adapter devolve. */
export type Resultado =
  | {
      readonly ok: true;
      /** O `id` da linha em `outbound_messages`. */
      readonly id: string;
      readonly wamid: string | null;
      readonly kind: Categoria;
      /** `true` quando a chave já tinha passado: não houve chamada HTTP. */
      readonly repetido: boolean;
    }
  | {
      readonly ok: false;
      readonly motivo: MotivoDeRecusa;
      /** O código da Meta, quando houve chamada e ela recusou. */
      readonly codigo: number | null;
    };

/** Uma linha de `message_templates`, como o adapter a lê. */
export interface Template {
  readonly name: string;
  readonly lang: string;
  readonly category: CategoriaDeTemplate;
  readonly status: EstadoDeTemplate;
  readonly quality: Qualidade | null;
  readonly bloqueadoEm: Date | null;
}

/** O `pricing` que chega num `statuses`, tal e qual. */
export interface Pricing {
  readonly billable: boolean;
  readonly pricing_model: string;
  readonly type: string;
  readonly category: string;
}

/**
 * O cliente de SQL que o adapter precisa.
 *
 * `readonly rows` como no `ClienteDoChr` do KAM-014, e pela mesma razão: o
 * adapter nunca altera o que lê, e um tipo com `rows` mutável obrigava quem o
 * liga a provar que não o altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/** Porta 1: de onde vem o destinatário. Ver a nota do módulo. */
export type ObterDestinatario = (
  tenantId: string,
  contactId: string,
) => Promise<Destinatario>;

/**
 * Porta 2: o gancho do KAM-018, chamado sob o *lock* da conversa.
 *
 * Devolve `true` para deixar passar. O corpo é do KAM-018; o que este ticket
 * garante é que **a ausência de guarda não é um passe livre** — ver
 * `exigirGuarda`.
 */
export type PreSendGuard = (pedido: Pedido) => Promise<boolean>;

/**
 * O par de estados que a matriz do KAM-009 lê.
 *
 * Os dois e não só o do canal: a matriz decide pelo **mais restritivo** dos
 * dois (`maisRestritivo` do `ten/estados.ts`), e um canal `ativo` de um
 * *tenant* `suspenso` não envia nada.
 */
export interface EstadoParaEnvio {
  readonly estadoTenant: string;
  readonly estadoCanal: string;
}

/**
 * Porta 5: de onde vem o par de estados (KAM-021, critério 9).
 *
 * `null` quando o canal não se encontra — e quem lê trata-o como recusa, não
 * como «sem opinião»: um canal que não existe não envia.
 *
 * É porta e não consulta própria porque o **CHR** é a autoridade sobre o
 * contexto do canal: ele já resolve o par em `ChannelContext` e tem a *cache*
 * com o TTL. Uma segunda leitura aqui era uma segunda fonte para o mesmo facto,
 * e divergiam no primeiro segundo em que a *cache* e a base discordassem.
 */
export type ObterEstado = (
  tenantId: string,
  phoneNumberId: string,
) => Promise<EstadoParaEnvio | null>;

/** Porta 3: o contador do *free tier*. Quem o mantém é o KAM-023. */
export type EstadoDoFreeTier = (
  tenantId: string,
  phoneNumberId: string,
) => Promise<{ readonly usadas: number; readonly tecto: number }>;

/** O que o cliente da Meta devolve a um envio. */
export type RespostaDaMeta =
  | { readonly ok: true; readonly wamid: string }
  | {
      readonly ok: false;
      /** O `error.code` do corpo. **É por aqui que se ramifica**, nunca pelo estado HTTP. */
      readonly codigo: number;
      readonly estadoHttp: number;
      /** Segundos do `Retry-After`, quando a Meta o manda. */
      readonly esperar: number | null;
    };

/** Porta 4: o que fala com a Graph API. */
export interface ClienteDaMeta {
  enviar(
    phoneNumberId: string,
    para: Destinatario,
    corpo: Corpo,
  ): Promise<RespostaDaMeta>;
}

/** O tecto do *free tier* de *service messages*, por número e por mês. */
export const FREE_TIER_DE_SERVICE = 1000;

/**
 * O vocabulário da entrada de canal (KAM-013), partilhado pelo GWY e pelo
 * *worker*.
 *
 * Está num só ficheiro por uma razão que este repositório já pagou: dois
 * escritores sobre o mesmo desenho, sem um nome canónico para seguir, produzem
 * dois nomes para a mesma coisa (`.claude/skills/software-factory`,
 * «Paralelismo»). O GWY enfileira e o *worker* consome; a fila, a forma do
 * *job*, as classes de evento e os destinos são a costura entre os dois, e é
 * aqui que vivem — a par do dicionário §3.12, emenda 1.19.
 *
 * ## O que este módulo **não** decide
 *
 * A **subscrição** dos campos na Meta é KAM-016 e não está aqui: este módulo
 * traduz o `changes[].field` que chegou, e não pede campo nenhum. A resolução
 * de `phone_number_id → tenant` é KAM-014, o envio é KAM-015 e os tratadores
 * de cada destino são de quem os for escrever — o que este módulo dá é o nome
 * do destino, não o tratador.
 */

/** A fila onde o GWY põe o corpo bruto. Dicionário §3.12. */
export const FILA_ENTRADA = "wa-inbound";

/** O nome do *job* dentro da fila. Um só tipo: o que chega do webhook da Meta. */
export const JOB_ENTRADA = "wa";

/**
 * O que o GWY põe na fila.
 *
 * `corpo` é **base64** dos bytes recebidos, e não o JSON já interpretado. Duas
 * razões, e a segunda é a que importa: o GWY responde 200 sem I/O pesado nem
 * `parse` (critério 5), e o corpo pode não ser JSON válido — é esse o caso do
 * critério 6, que tem de chegar ao *worker* para ir à quarentena em vez de
 * fazer o GWY devolver 5xx e começar uma semana de re-entregas.
 *
 * `recebidoEm` é o instante em que o GWY recebeu, em milissegundos. Não é o
 * `timestamp` da Meta — esse vem dentro do corpo e preserva-se lá, que é o que
 * o bloco do ticket diz («aqui só se preserva o `timestamp` da Meta»).
 */
export interface TrabalhoDeEntrada {
  readonly corpo: string;
  readonly recebidoEm: number;
}

/**
 * As classes de um evento de canal **registado**: os doze campos de webhook.
 *
 * Dicionário §3.12, e é o `CHECK` de `inbound_events.kind`. São doze e não
 * catorze: os dois caminhos de quarentena estão em `KINDS_DE_QUARENTENA`, e a
 * divisão existe porque as duas tabelas têm `CHECK` diferentes — com catorze
 * valores nas duas, uma `message` podia ser escrita na quarentena e um
 * `invalido` no registo de entrada. A suite `db/tests_entrada` prende estas
 * listas às do dicionário e às do PostgreSQL.
 */
export const KINDS_DE_ENTRADA = [
  "message",
  "echo",
  "statuses",
  "history",
  "smb_app_state_sync",
  "account_update",
  "phone_number_quality_update",
  "business_capability_update",
  "account_alerts",
  "message_template_status_update",
  "template_category_update",
  "message_template_quality_update",
] as const;
export type KindDeEntrada = (typeof KINDS_DE_ENTRADA)[number];

/** Os dois caminhos de quarentena. É o `CHECK` de `unrouted_events.kind`. */
export const KINDS_DE_QUARENTENA = ["desconhecido", "invalido"] as const;
export type KindDeQuarentena = (typeof KINDS_DE_QUARENTENA)[number];

/** O vocabulário todo: os catorze. É o domínio de `destinoDe`. */
export const KINDS = [...KINDS_DE_ENTRADA, ...KINDS_DE_QUARENTENA] as const;
export type Kind = KindDeEntrada | KindDeQuarentena;

/**
 * Porque é que um evento foi para a quarentena. Dicionário §3.12.
 *
 * **Seis, e os dois últimos são do KAM-014.** Os quatro primeiros são razões do
 * **corpo** e nascem na explosão; `canal_desconhecido` e
 * `mensagem_sem_identidade` são razões do **encaminhamento** e nascem no CHR
 * (`chr/contrato.ts`, `MOTIVOS_DO_CHR`). A lista é uma só porque a coluna é uma
 * só: o `CHECK` de `unrouted_events.motivo` tem os seis, e a suite
 * `db/tests_entrada` prende esta lista à do PostgreSQL **e** à do dicionário —
 * três fontes, e nenhuma pode divergir.
 */
export const MOTIVOS = [
  "json_invalido",
  "campo_desconhecido",
  "corpo_sem_entry",
  "change_sem_itens",
  "canal_desconhecido",
  "mensagem_sem_identidade",
] as const;
export type Motivo = (typeof MOTIVOS)[number];

/** Para onde um `kind` segue. Dicionário §3.12. */
export const DESTINOS = ["chr", "outbound", "ingestao", "gestao_de_canal", "quarentena"] as const;
export type Destino = (typeof DESTINOS)[number];

/**
 * Os onze campos de webhook, e o `kind` de cada um.
 *
 * A lista é a do critério do KAM-016 (`specs/EPIC-02` §KAM-016), que é quem os
 * subscreve; aqui serve só para traduzir o que chega. O campo `messages` **não
 * está neste mapa**: é o único que dá dois `kind` — a Meta entrega
 * `value.messages[]` e `value.statuses[]` no mesmo `value` —, e por isso é
 * tratado à parte na explosão.
 */
export const KIND_POR_CAMPO: Readonly<Record<string, KindDeEntrada>> = {
  smb_message_echoes: "echo",
  history: "history",
  smb_app_state_sync: "smb_app_state_sync",
  account_update: "account_update",
  phone_number_quality_update: "phone_number_quality_update",
  business_capability_update: "business_capability_update",
  account_alerts: "account_alerts",
  message_template_status_update: "message_template_status_update",
  template_category_update: "template_category_update",
  message_template_quality_update: "message_template_quality_update",
};

/** O campo que traz mensagens e estados no mesmo `value`. */
export const CAMPO_DAS_MENSAGENS = "messages";

/**
 * O destino de cada `kind`. É a tabela do critério 8 em forma de mapa.
 *
 * Mapa total e não `switch` com `default`: um `kind` novo sem destino é um erro
 * de compilação (`Record<Kind, Destino>` exige as catorze chaves), e não um
 * evento encaminhado para onde calhar.
 */
export const DESTINO_POR_KIND: Readonly<Record<Kind, Destino>> = {
  // «`message`/`echo` → CHR»
  message: "chr",
  echo: "chr",
  // «`statuses` → *stage* de *outbound* (nunca ao AGR)»
  statuses: "outbound",
  // «`history`/`smb_app_state_sync` → só ingestão (KAM-017)»
  history: "ingestao",
  smb_app_state_sync: "ingestao",
  // «`account_update`/qualidade/templates → *stage* de gestão de canal»
  account_update: "gestao_de_canal",
  phone_number_quality_update: "gestao_de_canal",
  business_capability_update: "gestao_de_canal",
  account_alerts: "gestao_de_canal",
  message_template_status_update: "gestao_de_canal",
  template_category_update: "gestao_de_canal",
  message_template_quality_update: "gestao_de_canal",
  // Os dois que não são campos da Meta.
  desconhecido: "quarentena",
  invalido: "quarentena",
};

/** O destino de um `kind`. */
export function destinoDe(kind: Kind): Destino {
  return DESTINO_POR_KIND[kind];
}

/**
 * Os tipos de mensagem que se podem registar em `wa_type`. Lista **fechada**.
 *
 * É a de `docs/tecnica/01` §5.4, com os mesmos valores que o simulador do
 * KAM-024 tem de gerar. Fechada por duas razões, e nenhuma é gosto:
 *
 * 1. O `wa_type` vem de dentro do corpo, isto é, de fora. A *allowlist* do
 *    *logger* valida a **forma** de um identificador, e um `type` que a Meta
 *    (ou quem conseguir assinar um corpo) inventasse com a forma certa entrava
 *    na linha de *log* tal e qual. Com lista fechada, o que não se reconhece
 *    sai como `outro`.
 * 2. O `wa_type` é também etiqueta potencial de métrica (KAM-080), e uma lista
 *    aberta é cardinalidade sem tecto
 *    (`docs/seguranca/ameacas_stride.md`, OBS-I).
 *
 * **Não entra no dicionário**: nenhuma superfície do *gate* 3b lê TypeScript, e
 * uma extensão que nenhuma superfície usa falha o próprio *gate* (§3.12).
 */
export const WA_TYPES = [
  "text",
  "audio",
  "image",
  "document",
  "location",
  "interactive",
  "order",
  "reaction",
  "sticker",
  "unsupported",
] as const;
export type WaType = (typeof WA_TYPES)[number] | "outro";

const WA_TYPES_CONHECIDOS: readonly string[] = WA_TYPES;

/** O `wa_type` registável de um valor que veio do corpo. */
export function waType(valor: unknown): WaType {
  return typeof valor === "string" && WA_TYPES_CONHECIDOS.includes(valor)
    ? (valor as WaType)
    : "outro";
}

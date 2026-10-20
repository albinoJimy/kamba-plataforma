/**
 * Os onze campos de webhook, um construtor por campo (KAM-024, critério 2).
 *
 * A lista é a de `docs/tecnica/01` §4.4 — onze campos, todos **CONFIRMADO** — e
 * é a mesma que o critério do KAM-016 fixa como conjunto a subscrever. O
 * `KIND_POR_CAMPO` de `@kamba/core-ts/entrada` tem dez: o `messages` está à
 * parte lá porque dá **dois** `kind` (`message` e `statuses`, que chegam no
 * mesmo `value` e têm destinos opostos). Aqui são onze construtores, e um teste
 * confronta os dez do mapa mais o `messages` com estas chaves.
 *
 * ## Cada `value` tem `metadata`, e isso não é enfeite
 *
 * É de `metadata.phone_number_id` que o CHR tira a pergunta que resolve o tenant
 * (KAM-014). Um `value` sem `metadata` é um caso **adversário** e vive no
 * `adversos.ts`; aqui todos o têm, porque é a forma normal.
 *
 * ## O que é NÃO VERIFICADO, e fica declarado em vez de inventado
 *
 * O nome do array dentro de `smb_message_echoes` **não está confirmado**: o `E1`
 * §5 não o diz e nenhuma página primária foi lida. O `core-ts` trata-o pela
 * regra geral e reconhece `message_echoes` como *proposta* (`ARRAY_DOS_ECHOES`);
 * este módulo usa o **mesmo** nome, importado de lá, para que o dia em que o
 * KAM-017 o fixar mude um sítio e não dois.
 *
 * A forma interna de `history`, `smb_app_state_sync`, `account_alerts` e
 * `business_capability_update` é **INDÍCIO**: as páginas lidas nomeiam os campos
 * e os seus motivos, não a estrutura completa do `value`. O simulador produz a
 * forma mínima que o roteamento do KAM-013 precisa — `field` e `value` com
 * `metadata` — e **não** inventa sub-objectos ricos que nenhuma fonte descreve.
 * É a *suite* online do critério 8 que os compara com o que a Meta manda.
 */

import { ARRAY_DOS_ECHOES, CAMPO_DAS_MENSAGENS, KIND_POR_CAMPO } from "@kamba/core-ts/entrada";

import { CODIGOS_CONFIRMADOS } from "./codigos.ts";
import type { Canal, Interlocutor } from "./identificadores.ts";
import { wamid } from "./identificadores.ts";
import { estado, type Estado } from "./estados.ts";
import { contacto, mensagem, type Tipo, type VarianteInteractiva } from "./mensagens.ts";
import type { Gerador } from "./semente.ts";

/** Os onze campos, pela ordem do §4.4. */
export const CAMPOS = [
  CAMPO_DAS_MENSAGENS,
  "smb_message_echoes",
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
export type Campo = (typeof CAMPOS)[number];

/**
 * Os seis motivos de `PARTNER_REMOVED` (§4.4, CONFIRMADO).
 *
 * São o que diz **porque** é que o canal deixou de chegar, e é o `account_update`
 * que leva o estado do canal a `desligado` (KAM-021). Um `account_update` sem
 * motivo não diz nada a ninguém, e é por isso que a *fixture* os enumera.
 */
export const MOTIVOS_DE_REMOCAO = [
  "PRIMARY_INACTIVITY",
  "COMPANION_INACTIVITY",
  "BUSINESS_DOWNGRADE",
  "CHANGE_NUMBER",
  "USER_RE_REGISTERED",
  "ACCOUNT_DISCONNECTED",
] as const;
export type MotivoDeRemocao = (typeof MOTIVOS_DE_REMOCAO)[number];

/** As notas de qualidade de um número (`E1` §5: GREEN/YELLOW/RED). */
export const QUALIDADES = ["GREEN", "YELLOW", "RED"] as const;

/** Os escalões de limite de mensagens. O escalão 1.000 **já não existe** (`E1` §5). */
export const ESCALOES = ["TIER_250", "TIER_2K", "TIER_10K", "TIER_100K", "TIER_UNLIMITED"] as const;

/** Os estados do ciclo de vida de um template. */
export const ESTADOS_DE_TEMPLATE = ["APPROVED", "REJECTED", "PAUSED", "PENDING", "DISABLED"] as const;

/** As categorias de template. O Piloto só usa as duas primeiras (KAM-015). */
export const CATEGORIAS_DE_TEMPLATE = ["UTILITY", "AUTHENTICATION", "MARKETING"] as const;

/** O `metadata` que todo o `value` leva. */
function metadata(canal: Canal): Record<string, unknown> {
  return {
    display_phone_number: canal.displayPhoneNumber,
    phone_number_id: canal.phoneNumberId,
  };
}

/** Opções comuns a um construtor de campo. */
export interface Opcoes {
  readonly canal: Canal;
  readonly quem: Interlocutor;
  /** Para `messages`: os tipos a incluir. Por omissão, um `text`. */
  readonly tipos?: readonly Tipo[];
  /** Para `messages`: os estados a incluir, do mesmo `wamid`. */
  readonly estados?: readonly Estado[];
  /** `false` omite o `wa_id`/`from` (o caso do *username*, `E1` §3). */
  readonly comWaId?: boolean;
  /** Para `account_update`: o motivo da remoção. */
  readonly motivo?: MotivoDeRemocao;
  /** Para os campos de template: o nome do template. */
  readonly template?: string;
  /** Para `messages` com `interactive`: a variante. Por omissão, `button_reply`. */
  readonly variante?: VarianteInteractiva;
  /** Para `messages`: o texto dos itens que o levam. */
  readonly texto?: string;
}

/**
 * O `value` de um campo.
 *
 * Um `switch` exaustivo sobre `CAMPOS`: um campo novo sem construtor é erro de
 * compilação, e não um `value` vazio que passava pelo roteamento sem ninguém
 * notar. É o mesmo desenho do `DESTINO_POR_KIND` do KAM-013.
 */
export function valorDe(g: Gerador, campo: Campo, opcoes: Opcoes): Record<string, unknown> {
  const { canal, quem } = opcoes;
  const comWaId = opcoes.comWaId ?? true;
  const base = { messaging_product: "whatsapp", metadata: metadata(canal) };

  switch (campo) {
    case "messages": {
      const tipos = opcoes.tipos ?? (["text"] as const);
      const itens = tipos.map((tipo) =>
        mensagem(g, quem, tipo, {
          comWaId,
          ...(opcoes.variante === undefined ? {} : { variante: opcoes.variante }),
          ...(opcoes.texto === undefined ? {} : { texto: opcoes.texto }),
        }),
      );
      const valor: Record<string, unknown> = { ...base };
      if (itens.length > 0) {
        valor.contacts = [contacto(quem, comWaId)];
        valor.messages = itens;
      }
      if (opcoes.estados !== undefined && opcoes.estados.length > 0) {
        const alvo = wamid(g, quem.waId);
        valor.statuses = opcoes.estados.map((e) =>
          estado(g, {
            wamid: alvo,
            estado: e,
            recipienteId: quem.waId,
            recipienteUserId: quem.userId,
          }),
        );
      }
      return valor;
    }

    case "smb_message_echoes": {
      // O **eco** é a mensagem que o **dono** mandou pela app, em coexistência:
      // vai do negócio para o cliente, pelo que não tem `from` do cliente. O
      // nome do array é *proposta* — ver a nota do módulo.
      const numero = quem.waId;
      return {
        ...base,
        [ARRAY_DOS_ECHOES]: [
          {
            id: wamid(g, numero),
            to: numero,
            timestamp: String(1_790_812_800 + g.inteiro(30 * 24 * 60 * 60)),
            type: "text",
            text: { body: "Temos sim, passe por aqui" },
          },
        ],
      };
    }

    case "history":
      // Só ingestão; **jamais** dispara resposta do bot (`01` §9.4). O erro
      // 2593109 é «o cliente não partilhou histórico» (§4.4, CONFIRMADO), e a
      // *fixture* tem-no para que o caminho de erro exista.
      return {
        ...base,
        history: [
          {
            metadata: { phase: 0, chunk_order: 1, progress: 100 },
            threads: [
              {
                id: quem.waId,
                messages: [mensagem(g, quem, "text", { comWaId, texto: "Mensagem antiga" })],
              },
            ],
            errors: [
              {
                code: CODIGOS_CONFIRMADOS.semHistorico,
                title: "History not shared",
                message: "The customer did not share chat history.",
              },
            ],
          },
        ],
      };

    case "smb_app_state_sync":
      return {
        ...base,
        state_sync: [
          {
            type: "contact",
            action: "add",
            metadata: { phase: 1 },
            contact: { full_name: quem.nome, phone_number: quem.waId },
          },
        ],
      };

    case "account_update":
      return {
        ...base,
        event: "PARTNER_REMOVED",
        partner_removed_info: { reason: opcoes.motivo ?? g.escolher(MOTIVOS_DE_REMOCAO) },
      };

    case "phone_number_quality_update":
      return {
        ...base,
        event: g.escolher(["FLAGGED", "UNFLAGGED", "ONBOARDING"] as const),
        current_limit: g.escolher(ESCALOES),
        // O estado «Flagged» do número **já não existe** desde 7 Out 2025
        // (`E1` §5). O campo `event` fica porque a Meta continua a mandá-lo; o
        // que mudou é que a qualidade baixa já não faz descer o limite.
        quality_score: g.escolher(QUALIDADES),
      };

    case "business_capability_update":
      return {
        ...base,
        max_daily_conversations_per_phone_number: g.escolher([250, 2_000, 10_000, 100_000] as const),
        max_phone_numbers_per_business: g.escolher([2, 20] as const),
      };

    case "account_alerts":
      return {
        ...base,
        entity_type: "WABA",
        entity_id: canal.wabaId,
        alert_severity: g.escolher(["WARNING", "CRITICAL"] as const),
        alert_status: g.escolher(["ACTIVE", "RESOLVED"] as const),
        alert_type: g.escolher(["ACCOUNT_RESTRICTION", "POLICY_VIOLATION"] as const),
        alert_description: "Alerta sintetico do simulador.",
      };

    case "message_template_status_update":
      return {
        ...base,
        event: g.escolher(ESTADOS_DE_TEMPLATE),
        message_template_id: g.texto(15, "0123456789"),
        message_template_name: opcoes.template ?? "confirmacao_de_pedido",
        message_template_language: "pt_PT",
        reason: "NONE",
      };

    case "template_category_update":
      // **A recategorização para `marketing` bloqueia o uso do template** e
      // alerta (critério 9 do KAM-015). A *fixture* produz exactamente esse
      // caso, que é o que lá tem de ser testado.
      return {
        ...base,
        message_template_id: g.texto(15, "0123456789"),
        message_template_name: opcoes.template ?? "confirmacao_de_pedido",
        message_template_language: "pt_PT",
        previous_category: "UTILITY",
        new_category: "MARKETING",
      };

    case "message_template_quality_update":
      return {
        ...base,
        previous_quality_score: "GREEN",
        new_quality_score: g.escolher(["YELLOW", "RED"] as const),
        message_template_id: g.texto(15, "0123456789"),
        message_template_name: opcoes.template ?? "confirmacao_de_pedido",
        message_template_language: "pt_PT",
      };
  }
}

/** O `kind` que o KAM-013 dá a um campo. Para o relatório de cobertura. */
export function kindsDe(campo: Campo): readonly string[] {
  if (campo === CAMPO_DAS_MENSAGENS) return ["message", "statuses"];
  const kind = KIND_POR_CAMPO[campo];
  return kind === undefined ? [] : [kind];
}

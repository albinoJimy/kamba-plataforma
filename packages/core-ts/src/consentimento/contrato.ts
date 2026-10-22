/**
 * O vocabulário do consentimento no 1.º contacto: tipos, portas e listas
 * fechadas (KAM-022).
 *
 * Os nomes são os do §3.1 do dicionário — que já declarava a `consent_event` e
 * o domínio de dez finalidades (emenda 1.16, KAM-159) — e os domínios são os
 * mesmos que a revisão `0015` impõe por `CHECK`. Há um teste em Python que
 * confronta as duas listas como texto (`db/tests/test_consentimento_schema.py`,
 * `TestParidadeDoDominio`), porque não há leitor de TypeScript em Python.
 *
 * ## A barreira é **anterior** ao AGR, e isso é o critério 1 e o 4
 *
 * «Primeira mensagem de um contacto sem `consent_event` válido para a versão de
 * texto vigente: exactamente 1 mensagem de saída (o aviso) e **0 invocações do
 * AGR**.» O `ConsentGate` corre no caminho de canal, antes de o `invocacao.ts`
 * do KAM-014 montar o *job* — e é por isso que ele devolve uma decisão em vez de
 * chamar o AGR: quem monta o *job* é o encaminhador, e o que este módulo faz é
 * dizer-lhe se pode.
 *
 * A propriedade do critério 4 — «em 1.000 mensagens por 50 contactos, nenhum
 * *job* do AGR é criado sem `consent_event` válido anterior» — só é
 * demonstrável se a decisão for **a única porta**. É por isso que o
 * `invocaAgr` é um campo do resultado e não uma consequência de quem lê: um
 * chamador que ignore a decisão é um defeito que o teste de propriedade apanha.
 *
 * ## As três finalidades que este ticket escreve, das dez que existem
 *
 * O domínio tem dez e **este módulo só escreve três**:
 *
 * * `transacao` — o que o «Continuar» registra. O critério 2 nomeia-a por
 *   extenso. Ela e a `atendimento` registam que **o aviso foi apresentado**; se
 *   a base legal é contrato ou consentimento é matéria de parecer (`E3` req.
 *   1–2, KAM-104);
 * * `atendimento` — o que «Falar com a loja» registra, e a razão de ser outra
 *   finalidade é que o tratamento é outro: ali a conversa passa a uma pessoa e
 *   **não** é tratada por IA;
 * * `marketing` — só com `accepted = false`, pelo «PARAR». **Nunca com
 *   `true`:** o opt-in de *marketing* é separado e específico (`E1` §4), e no
 *   Piloto não há *marketing*. Escrever um `accepted = true` aqui era inventar
 *   um consentimento que ninguém deu.
 *
 * As outras sete existem no domínio e não têm caminho neste módulo. Não é
 * esquecimento: `analytics_agregado`, `sugestoes_patrocinadas` e as três
 * `partilha_*` exigem consentimento específico no momento do uso (`06` §7.3), e
 * quem o pede é quem usa.
 */

import type { Logger } from "../logger/index.ts";

/** O cliente de SQL que este módulo precisa. Ver a nota das portas, abaixo. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * As dez finalidades do dicionário §3.1 (emenda 1.16, KAM-159).
 *
 * São a **união** das duas listas que existiam — as cinco do dicionário e as
 * oito dos 38 contratos publicados, que se cruzavam numa só (`marketing`) — e
 * estão aqui inteiras porque o domínio é do canon e não deste ticket. Duas
 * delas (`partilha_estafeta` e `notificacao_dono`) eram **impossíveis de
 * emitir** até à `v2` dos contratos.
 *
 * **A base legal de cada uma não está fixada**, e isso fica dito aqui e não só
 * num documento: das dez, só a `marketing` tem fonte directa e CONFIRMADA no
 * `E3` (Art. 19.º da Lei 22/11), e **seis não têm nada**. O parecer é o
 * KAM-104.
 */
export const FINALIDADES = [
  "transacao",
  "atendimento",
  "marketing",
  "analytics_agregado",
  "melhoria_servico",
  "sugestoes_patrocinadas",
  "partilha_loja",
  "partilha_parceiros",
  "partilha_estafeta",
  "notificacao_dono",
] as const;
export type Finalidade = (typeof FINALIDADES)[number];

/** As três que este módulo escreve. Ver a nota do módulo. */
export const FINALIDADE_DO_AVISO: Finalidade = "transacao";
export const FINALIDADE_DO_HUMANO: Finalidade = "atendimento";
export const FINALIDADE_DE_MARKETING: Finalidade = "marketing";

/**
 * Os três botões do aviso, pelos `id` que **nós** emitimos.
 *
 * «O `button_reply` entrega `reply.id` emitido por nós (o AGR confia no `id`,
 * não no título)», e a razão é que o título é texto em PT-AO que um revisor
 * jurídico vai mudar: um `switch` sobre «Continuar» partia-se na primeira
 * revisão do texto. Os `id` são identificadores em `snake_case`, como o §2 do
 * dicionário manda, e ficam estáveis.
 *
 * **Três e não mais, e o limite é da Meta:** um `interactive` de botões aceita
 * no máximo **3** (CONFIRMADO, `E1`; o `MAXIMO_DE_BOTOES` do KAM-015 impõe-o, e
 * o `decidir` dele recusa um quarto antes de qualquer chamada HTTP).
 */
export const BOTOES = ["continuar", "falar_com_a_loja", "saber_mais"] as const;
export type BotaoDoAviso = (typeof BOTOES)[number];

/**
 * O que um contacto pode fazer chegar ao gate.
 *
 * **Seis entradas**, que são as do «6 entradas × 3 estados» dos Testes
 * Requeridos: os três botões, texto livre, o «PARAR», e qualquer outra coisa
 * (áudio, imagem, localização). A última existe porque um cliente responde a um
 * aviso com uma nota de voz, e não ter caso para isso era deixar o gate a
 * decidir por omissão.
 */
export type Entrada =
  | { readonly tipo: "botao"; readonly id: BotaoDoAviso }
  | { readonly tipo: "texto"; readonly texto: string }
  | { readonly tipo: "outro" };

/**
 * O estado do consentimento de um contacto para a versão vigente do texto.
 *
 * Três, e a diferença entre os dois primeiros é o critério 7: «subir a versão
 * exige re-aviso apenas a contactos sem consentimento da **nova** versão».
 *
 * * `ausente` — não há linha nenhuma para esta finalidade;
 * * `desactualizado` — há linha aceite, mas de uma versão **anterior** à
 *   vigente;
 * * `valido` — há linha aceite da versão vigente.
 *
 * Um `accepted = false` conta como `ausente` e não como um quarto estado, e é
 * deliberado: quem recusou não deu consentimento, e o que o gate faz a seguir é
 * o mesmo. O **registo** da recusa fica na tabela, que é onde ele tem de
 * ficar.
 */
export const ESTADOS = ["ausente", "desactualizado", "valido"] as const;
export type EstadoDoConsentimento = (typeof ESTADOS)[number];

/** O que o gate manda fazer. Ver a matriz em `decisao.ts`. */
export const ACCOES = [
  "enviar_aviso",
  "registar_e_seguir",
  "seguir",
  "passar_a_humano",
  "enviar_politica",
  "registar_revogacao",
] as const;
export type Accao = (typeof ACCOES)[number];

/**
 * Quantas vezes o aviso se repete antes de a conversa passar a uma pessoa.
 *
 * «Texto livre em vez de botão repete o aviso até **2 vezes** e depois encaminha
 * a `humano`», e o próprio critério acrescenta «(comportamento a confirmar por
 * parecer)». Fica como constante e não escrito no meio de um `if` exactamente
 * por isso: quando o parecer chegar, muda-se um número.
 */
export const AVISOS_ANTES_DO_HUMANO = 2;

/** O prefixo da chave de idempotência do aviso. Ver `consultas.ts`. */
export const PREFIXO_DO_AVISO = "aviso";

/** O resultado de uma passagem pelo gate. */
export interface Decisao {
  readonly accao: Accao;
  /**
   * `true` **só** quando o AGR pode ser invocado nesta mensagem.
   *
   * É o campo que o critério 4 mede, e é por isso que existe em vez de se
   * deduzir da acção: a propriedade «0 *jobs* sem consentimento» tem de ser
   * verificável num sítio.
   */
  readonly invocaAgr: boolean;
  /** `true` quando o gate quer que a conversa passe a uma pessoa (KAM-018/019). */
  readonly passaAHumano: boolean;
  /** `true` quando o gate quer a conversa `pausada` (gancho do KAM-018). */
  readonly pausaAConversa: boolean;
  /** Quantas mensagens de saída esta decisão produz. **Zero ou uma.** */
  readonly mensagens: number;
}

/** Uma versão vigente do texto do aviso, como a base a devolve. */
export interface TextoVigente {
  readonly version: string;
  readonly texto: string;
}

/**
 * Porta 1: o envio da mensagem de saída.
 *
 * Porta e não chamada directa ao `Saida` do KAM-015 por duas razões. A primeira
 * é a do `Emitir` do KAM-021: quem liga os módulos é o serviço. A segunda é
 * **medida** — o `Saida` precisa do `destinatario`, do `guarda` do KAM-018 e do
 * cliente da Meta, e um `ConsentGate` que o construísse arrastava três
 * dependências para dentro de uma decisão.
 *
 * Devolve o `wamid` da mensagem enviada, ou `null` quando não saiu. O gate
 * **não** trata o `null` como falha silenciosa: conta-o e registra-o.
 */
export type EnviarAviso = (
  destino: DestinoDoAviso,
  corpo: CorpoDoAviso,
) => Promise<string | null>;

/** Para onde vai o aviso. O gate não conhece telefones: só identificadores. */
export interface DestinoDoAviso {
  readonly tenantId: string;
  readonly contactId: string;
  readonly conversationId: string;
  readonly channelId: string;
  readonly phoneNumberId: string;
  /** A chave de idempotência que o gate derivou. Ver `consultas.ts`. */
  readonly idempotencyKey: string;
}

/** O corpo do aviso: texto e os três botões, ou só texto. */
export interface CorpoDoAviso {
  readonly texto: string;
  readonly botoes: readonly BotaoDoAviso[];
}

/**
 * Porta 2: quem publica `consent.recorded` e `consent.withdrawn`.
 *
 * Os dois contratos **já existem** (`contratos/eventos/consent.recorded/`,
 * v1 e v2, do KAM-159/KAM-007) e a carga deles é
 * `{contact_id, finalidade, origem}` — sem texto e sem telefone, que é o que o
 * critério 8 pede. Porta e não chamada directa porque a emissão é
 * `platform.evt_emitir` na transacção de quem chama, e o envelope constrói-se
 * **em SQL** (regra do KAM-005 e do ADR-009).
 */
export type Emitir = (
  tipo: "consent.recorded" | "consent.withdrawn",
  tenantId: string,
  contactId: string,
  finalidade: Finalidade,
) => Promise<void>;

/**
 * Porta 3: o gancho que passa a conversa a `humano` ou a `pausada`.
 *
 * É do KAM-018, e a coluna `conversations.mode` existe desde a `0009` — mas o
 * `UPDATE` que a `0009` concede a `kamba_app` é **por coluna e não inclui o
 * `mode`**, por decisão daquele ticket. Por isso é porta: quem a ligar é quem
 * tiver o privilégio, e este módulo não o tem. Até o KAM-018 existir, a porta
 * fica por ligar e a decisão fica escrita no resultado — que é o que o
 * `passaAHumano` e o `pausaAConversa` dizem.
 */
export type MudarModo = (
  tenantId: string,
  conversationId: string,
  modo: "humano" | "pausada",
) => Promise<void>;

/** As dependências do gate. */
export interface Dependencias {
  readonly bd: ClienteSql;
  readonly enviar: EnviarAviso;
  readonly emitir?: Emitir | null;
  readonly modo?: MudarModo | null;
  readonly log?: Logger;
  /** O relógio, por parâmetro. `undefined` deixa o `now()` à base. */
  readonly agora?: () => Date;
  /** O nome da loja, para o marcador do texto. Ver `prova.ts`. */
  readonly nomeDaLoja?: (tenantId: string) => Promise<string>;
}

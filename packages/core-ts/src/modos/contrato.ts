/**
 * O vocabulário dos modos da conversa (KAM-018).
 *
 * Num ficheiro só, pela razão que o `chr/contrato.ts` e o `outbound/contrato.ts`
 * já escreveram: dois escritores sobre o mesmo desenho, sem um nome canónico
 * para seguir, produzem dois nomes para a mesma coisa.
 *
 * ## Os modos **não** nascem aqui, e isso é deliberado
 *
 * `MODOS`, `Modo` e `MODO_POR_OMISSAO` vivem em `chr/contrato.ts` desde o
 * KAM-014, porque é o CHR que **lê** o modo para decidir se a mensagem vai ao
 * AGR, e são o `CHECK` da coluna `conversations.mode` (revisão `0009`,
 * dicionário §3.13). Este módulo importa-os e reexporta-os; redefini-los era a
 * forma mais barata de os deixar divergir, que é exactamente o defeito que o
 * §3.13 do dicionário existe para fechar.
 *
 * O que **nasce** aqui são os **gatilhos** — as oito coisas que podem causar
 * uma transição — e a tabela que diz, para cada par (modo, gatilho), o que
 * acontece.
 *
 * ## O que este módulo não decide
 *
 * A **detecção** de dois dos oito gatilhos é coexistência e é KAM-017: o
 * `echo_do_dono` precisa de `smb_message_echoes` com o `wamid` ausente de
 * `outbound_messages`, e o `comando_bot` chega pela mesma via (o `/bot` é uma
 * mensagem que o dono escreve na app do WhatsApp). O que está aqui é a
 * **tabela**: quem dispara os gatilhos é de quem os conseguir detectar. Ver a
 * secção «O que fica de fora» de `docs/modos-conversa.md`.
 */

import { MODOS, MODO_POR_OMISSAO, type Modo } from "../chr/contrato.ts";

export { MODOS, MODO_POR_OMISSAO, type Modo };

/**
 * O que pode causar uma transição de modo. Lista **fechada**: é etiqueta de
 * métrica, e um identificador não entra em etiqueta nenhuma
 * (`docs/seguranca/ameacas_stride.md`, OBS-I).
 *
 * `echo_do_dono`       o dono respondeu na app do WhatsApp e a mensagem voltou
 *                      como *echo* cujo `wamid` não está em
 *                      `outbound_messages` (não fomos nós que a enviámos). **A
 *                      detecção é KAM-017**; a transição é desta tabela
 * `cliente_escreveu`   chegou uma mensagem do cliente. Em `dono` devolve a
 *                      palavra ao bot **se** o silêncio do dono já expirou; nos
 *                      outros modos não muda nada
 * `comando_bot`        o dono escreveu `/bot`, devolvendo a conversa ao
 *                      assistente. **A detecção é KAM-017**, pela mesma via do
 *                      *echo*
 * `handoff_pedido`     o grafo ou o cliente pediram uma pessoa, ou o dono abriu
 *                      a conversa no Chatwoot
 * `handoff_resolvido`  o webhook `conversation_status_changed` do Chatwoot deu
 *                      `resolved` (KAM-019)
 * `opt_out`            o cliente pediu para parar. **A detecção do «PARAR» é
 *                      KAM-022**, que chama o `onOptOut` deste módulo
 * `sem_humano_24h`     passaram 24 h sobre o *handoff* sem actividade humana. É
 *                      o *job* idempotente do critério 7
 * `cliente_reactivou`  o cliente voltou a escrever **depois do aviso** de que a
 *                      conversa estava pausada. É um gatilho distinto do
 *                      `cliente_escreveu` de propósito: a reactivação exige o
 *                      aviso, e quem decide que ele saiu é KAM-022
 */
export const GATILHOS = [
  "echo_do_dono",
  "cliente_escreveu",
  "comando_bot",
  "handoff_pedido",
  "handoff_resolvido",
  "opt_out",
  "sem_humano_24h",
  "cliente_reactivou",
] as const;
export type Gatilho = (typeof GATILHOS)[number];

/**
 * Quanto tempo sem actividade do dono devolve a palavra ao bot quando o cliente
 * escreve. 30 minutos.
 *
 * *Proposta*, e o número está no canon: `docs/tecnica/01` §10.2 dá
 * `silencio_dono_min = 30` e marca-o «a calibrar no Piloto», e o critério 1 do
 * KAM-018 repete-o. Entra em milissegundos porque é com milissegundos que se
 * compara um `Date`, e o nome guarda a unidade do canon no comentário e não no
 * identificador — um `SILENCIO_DONO_MIN = 1_800_000` era uma armadilha.
 */
export const SILENCIO_DO_DONO_MS = 30 * 60 * 1_000;

/**
 * Quanto tempo em `humano` sem actividade humana pausa a conversa. 24 h.
 *
 * O número está no critério 7 e em `docs/tecnica/01` §10.2 («sem resposta
 * humana em 24h»), e **não** é a janela de serviço da Meta: essa é a
 * `JANELA_MS` do `chr/contrato.ts`, também de 24 h, e as duas coincidirem é
 * acidente. Separadas de propósito — calibrar uma não move a outra, e a da Meta
 * não é nossa para calibrar (`E1` §4, CONFIRMADO).
 */
export const SEM_HUMANO_MS = 24 * 60 * 60 * 1_000;

/**
 * O que a tabela de transições responde a um par (modo, gatilho).
 *
 * **Três respostas e não duas**, e a terceira é a que faz o resto funcionar:
 *
 * - `transita` — o modo muda. É uma das células que `docs/tecnica/01` §10.2
 *   nomeia;
 * - `sem_efeito` — o gatilho é legítimo neste modo e **não** muda o modo. Uma
 *   mensagem do cliente numa conversa em `bot` é tráfego normal; um `echo` numa
 *   conversa que já está em `dono` é o dono a continuar a falar;
 * - `rejeitada` — o gatilho não faz sentido neste modo, e é isto que o critério
 *   1 quer dizer com «qualquer outra transição é rejeitada».
 *
 * Sem o `sem_efeito`, cada mensagem do cliente numa conversa em `bot`
 * registava uma transição rejeitada e o contador de rejeições media tráfego em
 * vez de defeitos.
 */
export type Resposta =
  | { readonly tipo: "transita"; readonly para: Modo }
  | { readonly tipo: "sem_efeito" }
  | { readonly tipo: "rejeitada" };

/** O que a máquina precisa de saber da conversa para decidir. */
export interface EstadoDaConversa {
  readonly mode: Modo;
  readonly ultimaActividadeHumana: Date | null;
}

/**
 * O que uma mudança de modo produziu.
 *
 * `mudou` é `false` tanto para `sem_efeito` como para `rejeitada` **e também**
 * para a corrida perdida: dois processos a disparar o mesmo gatilho ao mesmo
 * tempo, e só um escreve. A diferença lê-se no `resposta` e no `ganhou`, e os
 * três casos contam-se em métricas diferentes — ver `metricas.ts`.
 */
export interface ResultadoDaMudanca {
  readonly resposta: Resposta;
  /** O modo que a conversa tem **depois** desta chamada. */
  readonly modo: Modo;
  /** `true` quando foi **esta** chamada que escreveu a coluna. */
  readonly mudou: boolean;
  /**
   * `false` quando a resposta era `transita` e o `UPDATE` não casou linha
   * nenhuma: outro processo transitou primeiro.
   *
   * É o equivalente do «zero linhas» do `SQL_AVANCAR_ESTADO` do KAM-015, e pela
   * mesma razão existe em separado do `mudou`: um gatilho que não teve efeito
   * porque já estava no destino não é a mesma coisa que um gatilho que perdeu
   * uma corrida, e um painel que os some não sabe qual dos dois subiu.
   */
  readonly ganhou: boolean;
  /** O `event_id` do `conversation.mode_changed` emitido, ou `null`. */
  readonly eventoId: string | null;
}

/**
 * O mínimo de um cliente SQL de que este módulo depende.
 *
 * `rows` **somente de leitura**, como o `ClienteDoChr` do KAM-014 e o
 * `ClienteSql` do KAM-015, e pela razão que o primeiro escreveu: este módulo
 * corre sobre a ligação que quem o constrói lhe der, e um `rows` mutável
 * obrigava quem a liga a provar que não a altera.
 */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }>;
}

/**
 * Uma transacção com contexto de tenant, sobre a ligação de `kamba_app`.
 *
 * **Não recebe o cliente**, exactamente como o `ComTenant` do `chr/chr.ts`, e
 * pela mesma razão de tipos: o `comTenant` de `tenant_guard` declara o seu
 * `ClienteSql` com `query` a devolver `Promise<unknown>`, e uma função que
 * receba um cliente mais estreito não é atribuível a uma que receba um mais
 * lato. Quem monta a máquina fecha sobre a sua própria ligação:
 *
 * ```ts
 * comTenant: (tenant, trabalho) => comTenant(bd, tenant, () => trabalho(bd))
 * ```
 *
 * E ganha-se a propriedade que importa aqui mais do que no CHR: **não há como
 * escrever `conversations.mode` fora de uma transacção com contexto**, e por
 * isso não há como tomar o *lock* da conversa fora dela — um
 * `pg_advisory_xact_lock` sem transacção é largado na instrução seguinte, o que
 * é o mesmo que não existir.
 */
export type ComTenant = <T>(
  tenantId: string,
  trabalho: (cliente: ClienteSql) => Promise<T>,
) => Promise<T>;

/**
 * Porta: emitir o `conversation.mode_changed` na transacção de quem chama.
 *
 * Porta e não chamada directa pela regra do KAM-005 e do ADR-009 — o envelope
 * constrói-se **em SQL**, por `platform.evt_emitir` — e pela mesma forma que o
 * `Emitir` do `consentimento/contrato.ts`. `null` deixa a máquina a funcionar
 * sem emitir, que é o que as baterias do *gate* 4 usam.
 *
 * **O tipo já está no catálogo** (`contratos/eventos/conversation.mode_changed/`,
 * v1 e v2) e não é este ticket que o acrescenta — o critério 6 dizia «tipo
 * acrescentado ao catálogo, KAM-007» e ele já lá está. O que **não** cabe nele
 * é o domínio dos quatro modos: a carga publicada é
 * `{thread_id, channel_mode}` com `channel_mode ∈ {ai, humano, desligado}`, e
 * `dono` não tem representação nenhuma. Ver `MODO_PARA_CHANNEL_MODE` e a secção
 * de verificação do ticket.
 *
 * **Recebe o cliente**, ao contrário do `ComTenant` acima, e tem de o receber:
 * a emissão corre **dentro** da transacção que escreveu o modo, para que as
 * duas confirmem juntas ou não confirme nenhuma. Uma porta que abrisse ligação
 * própria publicava uma mudança de modo que podia não ter acontecido.
 */
export type EmitirModoMudado = (
  cliente: ClienteSql,
  tenantId: string,
  conversationId: string,
  threadId: string,
  modo: Modo,
) => Promise<string>;

/**
 * Os quatro modos nossos para os **três** valores de `channel_mode` do contrato
 * publicado.
 *
 * `contratos/eventos/conversation.mode_changed/v2.schema.json` fixa
 * `channel_mode ∈ {ai, humano, desligado}` com `additionalProperties: false`, e
 * os nossos modos são quatro. A correspondência que resta:
 *
 * | modo      | `channel_mode` | porquê |
 * |---|---|---|
 * | `bot`     | `ai`         | é o assistente a responder |
 * | `humano`  | `humano`     | directo |
 * | `pausada` | `desligado`  | o assistente está desligado nesta conversa |
 * | `dono`    | `humano`     | **perde-se informação**, e fica dito |
 *
 * **O `dono` e o `humano` saem indistinguíveis no barramento**, e isso é uma
 * perda real: um consumidor que queira saber se quem tem a palavra é o dono na
 * app ou um agente no Chatwoot não o consegue saber deste evento. Escolheu-se
 * `humano` e não `desligado` porque a propriedade que um consumidor precisa de
 * respeitar é «o assistente não fala nesta conversa porque há uma pessoa a
 * falar», e `desligado` diria que não há ninguém.
 *
 * A alternativa era uma `v3` do contrato com `channel_mode` de quatro valores —
 * e **não se fez**: o catálogo é do KAM-007, uma quebra de contrato é um
 * ficheiro `v3` com compatibilidade a provar no *gate* 7, e inventá-la aqui era
 * decidir por outro ticket. A decisão devolve-se a quem escreveu o critério;
 * está na secção de verificação do KAM-018 e em `docs/dividas-documentais.md`.
 */
export const MODO_PARA_CHANNEL_MODE: Readonly<Record<Modo, string>> = {
  bot: "ai",
  dono: "humano",
  humano: "humano",
  pausada: "desligado",
};

/** O tipo e a versão do contrato publicado que este módulo emite. */
export const TIPO_MODE_CHANGED = "conversation.mode_changed";
export const VERSAO_MODE_CHANGED = 2;

/**
 * O tipo de agregado do evento. É `conversa`, como o `v2.schema.json` exige
 * (`agregado.tipo` tem `const: "conversa"`).
 */
export const AGREGADO_MODE_CHANGED = "conversa";

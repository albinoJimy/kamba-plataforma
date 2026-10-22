/**
 * O vocabulário da coexistência: tipos, portas e listas fechadas (KAM-017).
 *
 * Os nomes são os do §3.22 do dicionário (emenda 1.31) e os domínios são os
 * mesmos que a revisão `0018` impõe por `CHECK`. Quando um valor aparece nos
 * dois sítios é porque tem de aparecer: o `CHECK` é a última barreira e esta
 * lista é a primeira, e um teste compara as duas — a `0008` e a `0009` pagaram
 * a lição de as deixar divergir, e o KAM-021 repetiu-a.
 *
 * ## A tradução do vocabulário da Meta faz-se na fronteira, e aqui custou caro
 *
 * A Meta manda `PRIMARY_INACTIVITY` em maiúsculas; o §2 do dicionário manda
 * «estados em minúsculas, snake_case, sem acentos». Até aqui é a regra que a
 * `0010` escreveu para o `state` e o KAM-021 para a qualidade.
 *
 * **O que é novo é que, neste módulo, a regra deixou de ser estética.** Estes
 * seis valores vão também ao `outcome` de uma linha de registo, e a gramática
 * desse campo (`../logger/politica.ts`, `IDENTIFICADOR`) aceita **palavras de
 * letras minúsculas** com até três dígitos no fim, ou um número. Um
 * `PRIMARY_INACTIVITY` é recusado — e **em modo estrito, que é o do CI, o
 * `Logger` levanta**. Um desfecho perfeitamente normal de um *webhook* passava a
 * excepção não tratada no caminho de entrada. É a mesma classe de defeito que o
 * `sem_humano_24h` do KAM-018 pagou, e que a nota de entrega daquele ticket
 * mandou conferir antes: confrontou-se cada um dos seis com o espelho Python
 * da política, e os seis passam.
 *
 * ## O 2593109 **não se pode registar**, e isto não é escolha
 *
 * O código que diz «o cliente não partilhou histórico» tem **sete** dígitos. A
 * política recusa mais de **seis** em qualquer campo de texto
 * (`DIGITOS_MAXIMOS`) — a regra que apanha o telefone, o NIF e o IBAN em
 * qualquer arrumação —, e recusa-o nos **dois** campos onde ele caberia: no
 * `outcome`, cuja gramática são palavras, e no `error_code`, cujo `NUMERO` é
 * `[0-9]{1,6}`. Mediu-se: `validar("error_code", "2593109")` devolve `null`, e
 * `validar("error_code", "131049")` — o código de seis dígitos do KAM-015 —
 * passa.
 *
 * Consequência: o número vai à coluna `meta_error_code` (que é `integer`, e é
 * `integer` por isto) e o registo leva o `outcome` simbólico
 * `sincronizado_sem_historico`. **Quem acrescentar outro código da Meta a este
 * módulo tem de o confrontar com a política primeiro**, porque os códigos dela
 * têm seis **ou sete** dígitos e os dois casos comportam-se de forma diferente.
 *
 * ## As cinco portas
 *
 * O tratador não abre ligação nenhuma que não precise e não implementa nada que
 * seja de outro ticket. O que ele recebe:
 *
 * 1. **`ClienteSql`** — a ligação de `kamba_app`, **com contexto de tenant e
 *    dentro da transacção de quem chama**. É o papel que a `0018` autoriza a
 *    escrever `channel_coexistence` (`SELECT`, `INSERT`, `UPDATE`) e que a
 *    `0001`/`0014` já autorizam a escrever as colunas de `tenant_channels` que
 *    este módulo toca. A transacção não é detalhe, pela razão que o
 *    `qualidade/contrato.ts` escreveu: os passos de um `account_update` são
 *    registar, desligar e emitir, e com cada um na sua transacção um processo
 *    que caia pelo meio perde a transição para sempre — a Meta reenvia, o
 *    `ON CONFLICT` da `inbound_events` deduplica, e o canal fica `ativo` com o
 *    desligamento registado.
 * 2. **`Emitir`** — quem publica o `channel.updated` e o
 *    `channel.inactivity_warning`. Porta e não chamada directa porque a emissão
 *    é `platform.evt_emitir` na transacção de quem chama (ADR-009, KAM-005).
 * 3. **`Contacto`** — a resolução de identidade do KAM-008. O `smb_app_state_sync`
 *    traz contactos, e um contacto resolve-se por `contact_id` e nunca por
 *    telefone (ADR-010). É porta porque a `Identidade` tem arranque próprio e
 *    chaves, e este módulo não as conhece.
 * 4. **`Conversa`** — de `(tenant, contacto)` para a conversa, para o `echo`
 *    poder ir ao tratador do KAM-018. Porta pela mesma razão: a conversa é do
 *    CHR, e duplicar-lhe a consulta era ter duas verdades.
 * 5. **`Relogio`** — `() => Date`. **Nenhuma função deste módulo chama
 *    `Date.now()`**, e é isso que torna o critério 3 mensurável: «relógio
 *    acelerado nos testes». Com o relógio por dentro, um teste das 24 h media o
 *    `setTimeout` da máquina; com ele por fora, mede-se a regra. É a mesma
 *    escolha do `limites.ts` do KAM-015 e do `modos.ts` do KAM-018.
 *
 * ## Não há agendador, e isso é o precedente da casa
 *
 * O critério 3 pede «alerta aos 12 h e `falhado` às 24 h». Não existe
 * agendador neste repositório — nem `repeat:`, nem `delay:`, nem `cron` — e
 * nasce com o KAM-071/KAM-078. O que existe é o padrão que o
 * `abandonarVencidas` do KAM-016 e o `pausarPorInactividade` do KAM-018
 * escreveram: **uma função idempotente por predicado SQL, com o relógio por
 * parâmetro, testável agora e chamável depois**. É o que este módulo entrega, e
 * está dito na secção de verificação.
 */

import type { Modo as ModoDoCanal } from "../onboarding/contrato.ts";

export type { ModoDoCanal };

/**
 * O cliente de SQL que este módulo precisa.
 *
 * `readonly rows` como o `ClienteSql` do KAM-015, o `ClienteDoChr` do KAM-014 e
 * o do KAM-021, e pela mesma razão: este módulo nunca altera o que lê, e um
 * tipo com `rows` mutável obrigava quem o liga a provar que não o altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * Os quatro estados de uma sincronização de coexistência.
 *
 * O mesmo domínio que o `channel_coexistence_estado_ck` da revisão `0018`
 * impõe, e **há um teste que compara os dois** contra o `pg_get_constraintdef`.
 *
 * O `sincronizado_sem_historico` é **terminal e bem-sucedido**, e é o critério
 * 4 inteiro: a Meta diz que o cliente escolheu não partilhar histórico, que é
 * uma escolha do titular e não uma avaria nossa. Tratá-lo como `falhado`
 * disparava o *offboard* — isto é, mandava o dono repetir o Embedded Signup —
 * por ele ter exercido uma escolha que o próprio *popup* lhe oferece.
 */
export const ESTADOS = [
  "a_sincronizar",
  "sincronizado",
  "sincronizado_sem_historico",
  "falhado",
] as const;
export type Estado = (typeof ESTADOS)[number];

/** Os estados em que a sincronização acabou e nada mais lhe acontece. */
export const ESTADOS_TERMINAIS: readonly Estado[] = [
  "sincronizado",
  "sincronizado_sem_historico",
  "falhado",
];

/**
 * Os dois passos que o `E1` §2 nomeia, e que «só podem ser executados uma vez».
 *
 * Dois e não três: a evidência diz «contactos e histórico», e inventar um
 * terceiro passo — uma «verificação», digamos — era pré-declarar um nome sem
 * superfície, que é o que o *gate* 3b recusa.
 */
export const PASSOS = ["contactos", "historico"] as const;
export type Passo = (typeof PASSOS)[number];

/**
 * Os seis motivos de `PARTNER_REMOVED` (`E1` §2, **CONFIRMADO**), em canónico.
 *
 * Em minúsculas pela razão da nota do módulo, que não é estética: são também
 * `outcome` de registo.
 */
export const MOTIVOS_DE_DESLIGAMENTO = [
  "primary_inactivity",
  "companion_inactivity",
  "business_downgrade",
  "change_number",
  "user_re_registered",
  "account_disconnected",
] as const;
export type MotivoDeDesligamento = (typeof MOTIVOS_DE_DESLIGAMENTO)[number];

/**
 * O que a Meta manda em `partner_removed_info.reason`, e o que isso significa.
 *
 * Mapa explícito e não um `toLowerCase()`, pelas duas razões que o
 * `CANONICO_DA_META` do KAM-021 escreveu: um `toLowerCase()` aceitaria
 * **qualquer** cadeia, e é preciso haver uma lista contra a qual um motivo novo
 * seja desconhecido. Os seis são exactamente os do `MOTIVOS_DE_REMOCAO` do
 * simulador do KAM-024, que tem uma *fixture* assinada para cada um.
 */
const CANONICO_DA_META: Readonly<Record<string, MotivoDeDesligamento>> = {
  PRIMARY_INACTIVITY: "primary_inactivity",
  COMPANION_INACTIVITY: "companion_inactivity",
  BUSINESS_DOWNGRADE: "business_downgrade",
  CHANGE_NUMBER: "change_number",
  USER_RE_REGISTERED: "user_re_registered",
  ACCOUNT_DISCONNECTED: "account_disconnected",
};

/**
 * O motivo canónico de um valor da Meta, ou `null` quando não se reconhece.
 *
 * `null` **não é um erro**, e segue a escolha do `traduzirQualidade` do
 * KAM-021: um motivo que não se conhece não desliga o canal. Desligar por um
 * valor que não se compreende era aceitar que a Meta decidisse o estado dos
 * nossos canais com uma cadeia que ninguém leu — e o critério 5 enumera seis.
 */
export function traduzirMotivo(bruto: unknown): MotivoDeDesligamento | null {
  if (typeof bruto !== "string") return null;
  return CANONICO_DA_META[bruto] ?? null;
}

/** O evento de `account_update` que diz que a ligação caiu (`E1` §2). */
export const EVENTO_PARTNER_REMOVED = "PARTNER_REMOVED";

/**
 * O código que a Meta devolve quando o cliente não partilhou histórico.
 *
 * **CONFIRMADO** (`E1` §2). Ver a nota do módulo sobre porque é que ele nunca
 * entra numa linha de registo.
 */
export const CODIGO_SEM_HISTORICO = 2_593_109;

/**
 * O prazo duro da sincronização: **24 h**. CONFIRMADO (`E1` §2).
 *
 * «Cada passo só pode ser executado uma vez; senão o cliente tem de ser
 * *offboarded* e refazer o fluxo.» Não é *proposta* — está na evidência e no
 * critério 3.
 */
export const PRAZO_DE_SINCRONIZACAO_MS = 24 * 60 * 60 * 1_000;

/**
 * Quando se alerta que a sincronização ainda não acabou: **12 h**.
 *
 * ***Proposta.*** O número está no critério 3 e no `../../../../docs/tecnica/01`
 * §10.4, e é metade do prazo — mas nenhuma fonte primária o fixa. A calibrar no
 * Piloto.
 */
export const ALERTA_DE_SINCRONIZACAO_MS = 12 * 60 * 60 * 1_000;

/**
 * Quanto tempo sem *echo* do dono dispara o aviso preventivo: **10 dias**.
 *
 * ***Proposta.*** O critério 6 diz dez dias e o `01` §10.5 chama-lhe heurística;
 * o que é **CONFIRMADO** é o outro número — a Meta desliga por
 * `PRIMARY_INACTIVITY` ao fim de **~14 dias** sem abrir a app. Os dez dias são a
 * folga de quatro, e a folga é escolha nossa: avisar aos treze não dava tempo
 * de reagir, e avisar aos cinco era ruído.
 */
export const INACTIVIDADE_DO_DONO_MS = 10 * 24 * 60 * 60 * 1_000;

/**
 * O débito do *token bucket* por modo de canal, em mensagens por segundo.
 *
 * **Reexportado do `outbound/limites.ts`** e não redeclarado: é lá que estão os
 * outros tectos, e declará-lo aqui fazia o `outbound` — que é quem o lê —
 * importar do `coexistencia`, que já importa do `outbound`. A razão de ser
 * `15` nos dois modos está escrita na constante.
 */
export { MPS_POR_MODO, mpsDoModo } from "../outbound/limites.ts";

/** O estado a que um `PARTNER_REMOVED` leva o canal. Valor do `CHECK` da `0001`. */
export const ESTADO_DESLIGADO = "desligado";

/**
 * O nome do campo que, dentro de um *echo*, traz o destinatário.
 *
 * ***Proposta*, NÃO VERIFICADO**, e **reexportado** do `entrada/explosao.ts` em
 * vez de redeclarado: é a explosão que lê o corpo, e duas constantes com o
 * mesmo valor em dois módulos divergem no dia em que uma delas mudar — que é
 * exactamente a lição que o `ARRAY_DOS_ECHOES` escreveu e o simulador do
 * KAM-024 seguiu.
 *
 * **Este ticket fixa o campo**, que é o que o comentário daquele módulo lhe
 * atribuía por extenso («fixar o campo é KAM-017»), e fixa-o no nome que o
 * simulador já emite.
 *
 * Porque é que isto importa e não é arrumação: sem destinatário, um *echo* não
 * tem contacto, logo não tem conversa, logo não há o que transitar — e a célula
 * `bot→dono` que o KAM-018 pôs na tabela ficava sem detector para sempre. O
 * risco de a proposta estar errada é um *echo* que não resolve conversa, e esse
 * caso **conta-se** (`coex_echo_total{desfecho="sem_conversa"}`) em vez de se
 * perder.
 */
export { CAMPO_DO_DESTINATARIO } from "../entrada/explosao.ts";

/** Quem publica um evento de domínio na transacção de quem chama. */
export type Emitir = (
  cliente: ClienteSql,
  tenantId: string,
  channelId: string,
  phoneNumberId: string,
  motivo: string | null,
) => Promise<string>;

/** A resolução de identidade do KAM-008, como este módulo a usa. */
export type Contacto = (pedido: {
  readonly tenantId: string;
  readonly bsuid: string | null;
  readonly telefone: string | null;
}) => Promise<{ readonly contactId: string }>;

/**
 * De `(tenant, contacto, canal)` para a conversa, ou `null` se não houver.
 *
 * `null` é um resultado e não um erro: um *echo* para um cliente com quem nunca
 * houve conversa nossa é exactamente o caso que a coexistência cria — o dono
 * fala com gente que o bot nunca atendeu.
 */
export type Conversa = (pedido: {
  readonly tenantId: string;
  readonly contactId: string;
  readonly channelId: string;
}) => Promise<string | null>;

/** O tratador de modos do KAM-018, como porta. */
export type Transitar = (
  tenantId: string,
  conversationId: string,
) => Promise<void>;

/** O relógio. Ver a nota do módulo: nenhuma função aqui chama `Date.now()`. */
export type Relogio = () => Date;

/** A linha de `channel_coexistence`, como as consultas deste módulo a lêem. */
export interface Coexistencia {
  readonly id: string;
  readonly tenantId: string;
  readonly channelId: string;
  readonly estado: Estado;
  readonly passosFeitos: readonly Passo[];
  readonly iniciadoEm: Date;
  readonly prazoEm: Date;
  readonly alertadoEm: Date | null;
  readonly concluidoEm: Date | null;
  readonly contactosVistos: number;
  readonly mensagensVistas: number;
  readonly metaErrorCode: number | null;
  readonly ultimoEchoEm: Date | null;
  readonly avisadoEm: Date | null;
  readonly motivoDesligamento: MotivoDeDesligamento | null;
  readonly desligadoEm: Date | null;
}

/** O que a ingestão de um lote de `history` ou de `smb_app_state_sync` produziu. */
export interface ResultadoDaIngestao {
  /** Contactos resolvidos **por `contact_id`**; nunca telefones. */
  readonly contactos: number;
  /** Quantas mensagens o lote trazia. **Uma contagem, nunca um corpo.** */
  readonly mensagens: number;
  /** `true` quando este lote completou o passo (e, logo, quando o escreveu). */
  readonly passoConcluido: boolean;
  /** O estado em que a sincronização ficou. */
  readonly estado: Estado;
  /**
   * **Sempre 0, e é uma asserção e não um campo informativo.**
   *
   * O critério 1 pede «0 *jobs* para o AGR e 0 mensagens enviadas por estes
   * eventos». Este módulo não tem porta para o AGR nem para a saída — não as
   * pode chamar —, e este campo existe para que o teste afirme o número que o
   * critério escreve em vez de afirmar a ausência de uma chamada que ninguém
   * declarou. Um campo que vale sempre 0 é o sítio onde se vê que ele devia.
   */
  readonly jobsParaOAgr: 0;
}

/** O que o tratamento de um *echo* produziu. */
export interface ResultadoDoEcho {
  /**
   * `do_dono` — não é nosso, é actividade humana; `nosso` — o `wamid` consta de
   * `outbound_messages` e ignora-se; `sem_conversa` — é do dono mas não resolve
   * conversa.
   */
  readonly desfecho: DesfechoDoEcho;
  /** A conversa que transitou, ou `null`. */
  readonly conversationId: string | null;
}

/**
 * Os três desfechos de um *echo*.
 *
 * Três e não dois, e o terceiro é honestidade: um *echo* do dono cujo
 * destinatário não resolve contacto **não se descarta em silêncio**. Conta-se,
 * e é por essa contagem que o **NÃO VERIFICADO L6** — se um envio por API gera
 * *echo* — fica mensurável pelo lado que falta.
 */
export const DESFECHOS_DO_ECHO = ["do_dono", "nosso", "sem_conversa"] as const;
export type DesfechoDoEcho = (typeof DESFECHOS_DO_ECHO)[number];

/** O que o tratamento de um `account_update` produziu. */
export interface ResultadoDoDesligamento {
  /** O motivo canónico, ou `null` quando a Meta mandou algo que não se reconhece. */
  readonly motivo: MotivoDeDesligamento | null;
  /**
   * `true` quando **este** evento passou o canal a `desligado`.
   *
   * É o «repetir o mesmo evento 2× produz 1 transição» do critério 5, e quem o
   * decide é o predicado do `UPDATE` e não um `if`: a segunda passagem devolve
   * zero linhas.
   */
  readonly desligou: boolean;
  /** O `event_id` do `channel.updated`, ou `null` se não houve transição. */
  readonly eventoId: string | null;
}

/** O que uma varredura de prazos fez. */
export interface ResultadoDaVarredura {
  readonly alertados: readonly string[];
  readonly falhados: readonly string[];
  /** Os canais cujo *offboard* ficou pedido — os mesmos do `falhados`. */
  readonly offboards: readonly string[];
}

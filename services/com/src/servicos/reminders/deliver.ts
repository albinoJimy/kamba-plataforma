/**
 * O disparo do lembrete: os portões e o envio (KAM-048, critérios 2–6).
 *
 * É aqui que o `booking.reminder_due` se torna uma mensagem, ou não se torna
 * nenhuma com a razão registada. A ordem dos portões **é** o desenho, e cada um
 * está onde está por uma razão que a troca com o seguinte quebraria:
 *
 * ```text
 * 1. a marcação, da base      estado `confirmada` e `inicio` actual   critério 4
 * 2. o opt-in                 consentimento válido para a finalidade  critério 6
 * 3. o destino                 conversa, canal e janela
 * 4. o corpo                  livre com janela aberta, template sem   critério 3
 * 5. o Outbound               a chave, a decisão e a mensagem         critério 2
 * 6. a recusa de template     bloqueia, avisa o dono, registra        critério 5
 * ```
 *
 * ## Porque é que (1) vem antes de (2), e (2) antes de tudo o que custa
 *
 * (1) é a única leitura que pode dizer «não há nada a lembrar», e é de graça: é
 * a mesma transacção que (2) e (3) iam abrir de qualquer maneira. Pô-la depois
 * do consentimento fazia o gate de opt-in correr para marcações canceladas, o
 * que não está errado — está a mais, e mede uma coisa sobre um cliente a
 * propósito de um acto que já não existe.
 *
 * (2) vem antes de (3), (4) e (5) porque é o único portão cuja violação é de
 * natureza diferente das outras: uma marcação cancelada é o sistema a funcionar,
 * e um lembrete sem opt-in é **tratamento de dados sem base**. O critério 6
 * escreve «o lembrete não é enviado e o motivo é auditado», e auditar implica
 * que a decisão aconteça antes de qualquer efeito observável de fora.
 *
 * ## O portão do *template* é o do KAM-015, e o que é nosso é o que se faz com a
 * recusa
 *
 * Não se lê a `message_templates` aqui. O `decidir` do `outbound/decisao.ts` já
 * o faz, por dentro do `Saida`, e devolve `TEMPLATE_NOT_APPROVED` para um
 * `status ≠ approved`, `TEMPLATE_BLOCKED` para um bloqueado e
 * `MARKETING_NOT_ALLOWED` para um recategorizado — pela ordem das causas, que a
 * nota de lá explica. Uma segunda leitura do estado do *template* aqui era uma
 * segunda fonte para o mesmo facto, e divergiam no primeiro segundo em que as
 * duas discordassem.
 *
 * **A ordem do `Saida` protege a chave — mas só metade dela**, e a primeira
 * versão desta nota afirmava a metade boa como se fosse tudo. Lá a decisão corre
 * **antes** da linha em `outbound_messages` (passos 1–3 contra o 4 da nota do
 * `adapter.ts`), pelo que um *template* recusado **não gasta** a chave: um
 * lembrete que falhou por *template* por aprovar sai no dia em que a Meta
 * aprovar, com a mesma chave — que é o que se quer.
 *
 * O que ela não dizia é o que acontece a uma falha **depois** da linha —
 * `SEND_FAILED`, `NO_RECIPIENT`, `RATE_LIMITED`, e a supressão do guarda. Essas
 * deixam a linha escrita, e na entrega seguinte o `SQL_ENFILEIRAR` devolve vazio,
 * o adapter lê a linha pelo `SQL_POR_CHAVE` — que **não filtra `state`** — e
 * responde `{ok: true, repetido: true}`. Lido como «enviado», isso é uma
 * mensagem que nunca saiu contada como entregue. Achado da revisão adversarial,
 * medido com o `Saida` verdadeiro e a Meta a responder `131049`.
 *
 * Daí o `classificarRepetido`: num `repetido`, lê-se o `state` da linha e
 * decide-se. Os estados de progresso são um lembrete que já saiu; os `TERMINAIS`
 * do KAM-015 são a chave gasta por uma linha que não saiu, e dão `CHAVE_GASTA`.
 *
 * ## O envio é do bot, e **leva turno** — o defeito mais caro desta entrega
 *
 * `doBot: true`, porque um lembrete é o assistente a falar por iniciativa
 * própria e é exactamente o que o `PreSendGuard` do KAM-018 existe para travar
 * quando uma pessoa está a atender a conversa. Isso estava certo. O que estava
 * errado era **não passar o `turnoIniciadoEm`**, com um comentário a declarar
 * que a ausência era desenho.
 *
 * **Não era.** O guarda recusa um envio do bot sem ele (`modos/guarda.ts`, ramo
 * `sem_turno`) e a supressão **escreve a linha** com a nossa chave
 * (`modos/consultas.ts`, `SQL_SUPRIMIR_ENVIO`, `ON CONFLICT ... DO NOTHING`). O
 * efeito em produção: **zero** lembretes enviados, em todos os ramos, e a chave
 * de cada marcação gasta para sempre. O próprio repositório classifica isto como
 * defeito de ligação e não como tráfego — o `modos/metricas.ts` escreve que o
 * `sem_turno` «é um contador que **deve** ficar a zero». Achado `must fix` da
 * revisão adversarial, medido com o `avaliar` verdadeiro contra uma conversa em
 * `mode = 'bot'` **sem actividade humana nenhuma**, que é o caso mais favorável
 * que existe.
 *
 * O valor que vai é o `agora` deste disparo, e é o que o campo significa — «o
 * instante em que começou o turno que produziu este envio». Para um lembrete o
 * turno é a própria entrega, e ela começou agora. O efeito no guarda é tornar a
 * verificação de **corrida** vacuamente verdadeira, e é a leitura certa: a
 * corrida do §10.3 é a de uma resposta composta antes de uma pessoa falar, e uma
 * mensagem composta neste instante não tem passado onde ela caiba. A barreira
 * que protege um lembrete é a outra, e fica **intacta** — o ramo `modo !== 'bot'`
 * do guarda, que suprime um envio para uma conversa em modo dono ou humano.
 *
 * **O que isto não é: não é `doBot: false`.** O `hnd/resposta.ts` usa-o, e com
 * razão — ali quem fala é a pessoa, e o guarda existe para a servir e não para a
 * recusar. Pôr `doBot: false` num lembrete tirava-lhe a única barreira que ele
 * precisa de ter, e um lembrete do assistente a cair numa conversa que um humano
 * está a atender é precisamente o que o invariante do §10.2 proíbe. *Mínimo*
 * nunca é retirar uma barreira.
 *
 * ## A idempotência não é deste ficheiro, e a chave é
 *
 * «O mesmo evento entregue 5 vezes produz 1 mensagem» não se cumpre com um
 * `SELECT` antes de enviar: entre o `SELECT` e o `INSERT` cabe a segunda
 * entrega. Cumpre-se com a `UNIQUE (tenant_id, idempotency_key)` da revisão
 * `0010` e o `ON CONFLICT ... DO NOTHING RETURNING` do `SQL_ENFILEIRAR`, e o
 * que este ficheiro fornece é a **chave**: `booking_id:reminder:T-24h`,
 * derivada do `booking_id` e da ordem, **sem relógio e sem o instante do
 * evento**. Uma chave com o `event_id` lá dentro dava cinco chaves para cinco
 * entregas do mesmo evento, que é precisamente o que o critério proíbe — e o
 * EVT entrega «pelo menos uma vez», pelo que as cinco entregas são o caso
 * normal e não o patológico.
 */

import type { Logger } from "@kamba/core-ts/logger";
import {
  SQL_ESTADO as SQL_ESTADO_DO_CONSENTIMENTO,
  SQL_TEXTO_VIGENTE,
  estadoDoConsentimento,
} from "@kamba/core-ts/consentimento";
import { WINDOW_CLOSED, janelaAberta } from "@kamba/core-ts/outbound";

import { SQL_POR_CHAVE, TERMINAIS } from "@kamba/core-ts/outbound";

import { SQL_MARCACAO, SQL_SERVICO } from "../consultas.ts";
import type { ClienteSql, ComTenant, Estado, Marcacao } from "../contrato.ts";
import { SQL_DESTINO } from "./consultas.ts";
import {
  ETIQUETA_DA_ORDEM,
  FINALIDADE_DO_LEMBRETE,
  MOTIVOS_DE_BLOQUEIO,
  IDIOMA_DO_LEMBRETE,
  TEMPLATE_DO_LEMBRETE,
  type AvisarDono,
  type BookingReminderDue,
  type DesfechoDoLembrete,
  type DestinoDoLembrete,
  type FactosDaMarcacao,
  type MotivoDeBloqueio,
  type PortaDeSaida,
} from "./contrato.ts";
import { ESTADO_QUE_LEMBRA } from "./schedule.ts";
import {
  MetricasDoLembrete,
  METRICA_ENVIADOS,
  METRICA_TRAVADOS,
  MOTIVOS_TRAVADOS,
} from "./metricas.ts";
import { parametrosDoLembrete, textoDoLembrete } from "./template.ts";

/**
 * **A chave de idempotência do critério 2**, escrita como o critério a escreve.
 *
 * `booking_id:reminder:T-24h`. Sem prefixo de módulo, ao contrário do
 * `hnd:{handoffId}:{mensagemId}` do KAM-019 — e não há risco de colisão: o
 * primeiro segmento é um UUID, e nenhuma outra chave desta casa começa por um.
 * O critério escreve a forma por extenso, e a forma é o contrato.
 */
export function chaveDoLembrete(bookingId: string): string {
  return `${bookingId}:reminder:${ETIQUETA_DA_ORDEM}`;
}

/** As recusas do Outbound que são um *template* a bloquear (critério 5). */
export const RECUSAS_DE_TEMPLATE: readonly string[] = [
  "TEMPLATE_NOT_APPROVED",
  "TEMPLATE_BLOCKED",
  "MARKETING_NOT_ALLOWED",
];

/**
 * O estado de uma linha de `outbound_messages` que já tinha a nossa chave.
 *
 * `null` quando não se encontra a linha — o que não devia acontecer depois de um
 * `repetido`, e por isso se trata como chave gasta: a alternativa era devolver
 * «enviado» sobre uma linha que não se conseguiu ler.
 */
async function estadoDaChave(
  cliente: ClienteSql,
  tenantId: string,
  chave: string,
): Promise<string | null> {
  const { rows } = await cliente.query(SQL_POR_CHAVE, [tenantId, chave]);
  const estado = rows[0]?.["state"];
  return estado === undefined || estado === null ? null : String(estado);
}

/**
 * Um `repetido` saiu, ou é uma chave gasta por uma linha que não saiu?
 *
 * Os `TERMINAIS` do KAM-015 — `failed` e `suppressed_by_human` — são «não saiu
 * mensagem»; os de progresso (`queued`, `sent`, `delivered`, `read`) são um
 * lembrete que já saiu, e a repetição é o EVT a entregar outra vez. Ver a nota
 * do módulo para o que isto corrige.
 */
export function repetidoSaiu(estado: string | null): boolean {
  if (estado === null) return false;
  return !(TERMINAIS as readonly string[]).includes(estado);
}

/**
 * A etiqueta de métrica de um motivo, com o domínio fechado respeitado.
 *
 * Um motivo que não esteja em nenhuma das duas listas colapsa em
 * `MOTIVO_DESCONHECIDO`. Sem isto, o `contar` **levantava** — e um bloqueio
 * transformado em excepção é um evento na DLQ por um defeito de quem implementou
 * a porta. Achado `PLAUSÍVEL` da revisão adversarial: a `PortaDeSaida` tipa o
 * motivo como `string`, mais largo do que o `MotivoDeRecusa` que o `Saida`
 * verdadeiro devolve. O motivo real continua a ir no desfecho e no registo.
 */
/**
 * O `kind` do Outbound traduzido no canal do contador.
 *
 * O `kind` é uma `Categoria` de **quatro** valores e o canal tem dois — é o que
 * o critério 8 pede, «por canal (livre/template)». A tradução é por isso de
 * quatro para dois, e a primeira versão fazia-a com
 * `kind === "service" ? "service" : "utility"`: um *template* que a Meta
 * categorizasse como `authentication` saía contado como `utility`, em silêncio.
 * Achado `nota` da revisão adversarial.
 *
 * **Não levanta**, e a escolha é deliberada: isto corre **depois** de a mensagem
 * ter saído, e lançar aqui trocava uma etiqueta imprecisa por um evento na DLQ
 * sobre um envio que teve sucesso. O que faz é registar — um `kind` inesperado
 * aparece no `outcome` e deixa de ser invisível, que é a diferença que o achado
 * nomeia. Hoje não acontece: o `marketing` é recusado pelo `decidir` e o
 * `lembrete_marcacao` é `utility`.
 */
export function canalDoKind(
  kind: string,
  log?: Logger,
): "service" | "utility" {
  if (kind === "service") return "service";
  if (kind !== "utility") {
    log?.warn({ outcome: "lembrete_kind_inesperado" });
  }
  return "utility";
}

export function etiquetaDoMotivo(motivo: string): string {
  return MOTIVOS_TRAVADOS.includes(motivo)
    ? motivo
    : ("MOTIVO_DESCONHECIDO" satisfies (typeof MOTIVOS_DE_BLOQUEIO)[number]);
}

/** O que o disparo precisa que lhe dêem. */
export interface Dependencias {
  readonly comTenant: ComTenant;
  readonly saida: PortaDeSaida;
  /**
   * Quem avisa o dono quando um *template* bloqueia (critério 5).
   *
   * `null` **não é um passe livre**: com ela a `null` o lembrete continua a ser
   * bloqueado e o motivo continua a ser registado e contado — o que falta é o
   * aviso, e o `donoAvisado` do desfecho diz `false` para que quem leia saiba a
   * diferença. É a escolha do `freeTier: null` do KAM-015 e não a do
   * `PreSendGuard`: um aviso que falte não deixa passar nada.
   */
  readonly avisarDono: AvisarDono | null;
  readonly metricas?: MetricasDoLembrete;
  /** O relógio, injectável para que os ensaios de janela não esperem. */
  readonly agora?: () => Date;
  readonly log?: Logger;
}

/** Uma linha de `bookings` como a base a devolve, no que este módulo lê. */
function marcacaoDaLinha(linha: Readonly<Record<string, unknown>>): Marcacao {
  return {
    bookingId: String(linha["booking_id"]),
    holdId: String(linha["hold_id"]),
    contactId: String(linha["contact_id"]),
    serviceId: String(linha["service_id"]),
    resourceId: String(linha["resource_id"]),
    slotId: String(linha["slot_id"]),
    inicioAt: instanteComoIso(linha["inicio_at"]),
    fimAt: instanteComoIso(linha["fim_at"]),
    estado: String(linha["estado"]) as Estado,
    holdExpiresAt:
      linha["hold_expires_at"] === null || linha["hold_expires_at"] === undefined
        ? null
        : instanteComoIso(linha["hold_expires_at"]),
    version: Number(linha["version"]),
  };
}

/**
 * Um `timestamptz` como ISO-8601, venha ele `Date` ou texto.
 *
 * O `pg` devolve `Date` para `timestamptz` e o cliente de ensaio devolve o texto
 * que lhe deram. **A comparação do critério 4 é entre cadeias**, pelo que as
 * duas formas têm de chegar à mesma — sem isto, um `Date` comparado com o
 * `inicio_at` do payload dava sempre diferente e **nenhum** lembrete saía, com o
 * motivo `MARCACAO_REMARCADA` a mentir sobre a causa. É a classe de defeito que
 * passa todos os ensaios com duplos e falha contra um PostgreSQL.
 */
function instanteComoIso(valor: unknown): string {
  if (valor instanceof Date) return valor.toISOString();
  const texto = String(valor);
  const instante = new Date(texto);
  return Number.isNaN(instante.getTime()) ? texto : instante.toISOString();
}

/** O destino, do `SQL_DESTINO`. `null` quando o contacto não tem conversa. */
async function lerDestino(
  cliente: ClienteSql,
  tenantId: string,
  contactId: string,
): Promise<DestinoDoLembrete | null> {
  const { rows } = await cliente.query(SQL_DESTINO, [tenantId, contactId]);
  const linha = rows[0];
  if (linha === undefined) return null;
  const expira = linha["window_expires_at"];
  return {
    conversationId: String(linha["conversation_id"]),
    channelId: String(linha["channel_id"]),
    phoneNumberId: String(linha["phone_number_id"]),
    janelaExpiraEm:
      expira === null || expira === undefined
        ? null
        : expira instanceof Date
          ? expira
          : new Date(String(expira)),
  };
}

/**
 * O portão de consentimento do KAM-022 (critério 6).
 *
 * **Liga-se, não se reimplementa.** Lê a versão vigente do aviso
 * (`SQL_TEXTO_VIGENTE`) e o estado do contacto na vista `consent_actual`
 * (`SQL_ESTADO`), e decide com o `estadoDoConsentimento` de lá — que é a função
 * que define o que «válido» quer dizer: aceite **e** para a versão vigente, não
 * aceite alguma vez.
 *
 * Devolve o motivo de bloqueio ou `null`. **Falha fechada nos dois lados:**
 *
 * * sem texto vigente, `SEM_TEXTO_VIGENTE`. A `consent_texts` nasce **vazia**
 *   (revisão `0015`), porque o texto é jurídico e está «a confirmar por
 *   parecer» (KAM-104) — e a nota do `SQL_TEXTO_VIGENTE` manda tratar a
 *   ausência como falha fechada, exactamente como o `ConsentGate` faz para o
 *   AGR. Hoje, em qualquer base recém-migrada, é **este** o motivo que sai, e é
 *   o estado correcto: sem aviso mostrado não há consentimento registado, logo
 *   não há lembrete;
 * * com texto vigente e sem consentimento válido, `SEM_OPT_IN`. Um
 *   `desactualizado` conta como ausente, e isso é do KAM-022 e não deste
 *   ticket: quem consentiu uma versão anterior do aviso não consentiu esta.
 */
async function portaoDoConsentimento(
  cliente: ClienteSql,
  tenantId: string,
  contactId: string,
): Promise<MotivoDeBloqueio | null> {
  const texto = await cliente.query(SQL_TEXTO_VIGENTE, [FINALIDADE_DO_LEMBRETE, null]);
  const vigente = texto.rows[0]?.["version"];
  if (vigente === undefined || vigente === null) return "SEM_TEXTO_VIGENTE";

  const estado = await cliente.query(SQL_ESTADO_DO_CONSENTIMENTO, [
    tenantId,
    contactId,
    FINALIDADE_DO_LEMBRETE,
  ]);
  const linha = estado.rows[0];
  const leitura =
    linha === undefined
      ? null
      : {
          accepted: Boolean(linha["accepted"]),
          text_version: String(linha["text_version"]),
        };
  return estadoDoConsentimento(leitura, String(vigente)) === "valido"
    ? null
    : "SEM_OPT_IN";
}

/**
 * O que foi lido da base, para quem quiser o detalhe do desfecho.
 *
 * Existe porque um desfecho que diz só «não enviei, `MARCACAO_REMARCADA`» não
 * deixa um painel dizer **para quando** a marcação foi, e a pergunta seguinte
 * do dono é sempre essa.
 */
export interface LeituraDoLembrete {
  readonly marcacao: Marcacao | null;
  readonly destino: DestinoDoLembrete | null;
  readonly factos: FactosDaMarcacao | null;
}

/**
 * **O disparo inteiro.** Entrega o lembrete de um `booking.reminder_due`, ou
 * não entrega nenhum com a razão registada.
 *
 * `evento` é o payload `v1` — `(booking_id, inicio_at)`. O `inicio_at` dele é o
 * do **agendamento**, e a comparação com o `inicio` actual é o critério 4: uma
 * remarcação muda a base e deixa este *job* a apontar para um instante que já
 * não existe.
 *
 * Tudo o que lê corre numa transacção só (`comTenant`), e o envio corre
 * **fora** dela. A ordem não é indiferente: o `Saida` abre a sua própria
 * ligação para escrever em `outbound_messages` e fala com a Graph API, e manter
 * a transacção de leitura aberta durante uma chamada HTTP era segurar uma
 * ligação de base de dados pelo tempo de rede de um terceiro. O risco da
 * separação é a marcação ser cancelada entre a leitura e o envio — e esse
 * risco é inerente: mesmo dentro de uma transacção, o cancelamento podia
 * acontecer um milissegundo depois do `COMMIT`. O que o fecha de verdade não é
 * uma transacção mais longa; é o cliente poder responder «cancelar» à mensagem,
 * que é o que o corpo do *template* lhe diz para fazer.
 */
export async function entregarLembrete(
  deps: Dependencias,
  tenantId: string,
  evento: BookingReminderDue,
): Promise<DesfechoDoLembrete & { readonly leitura: LeituraDoLembrete }> {
  const metricas = deps.metricas ?? new MetricasDoLembrete();
  const agora = (deps.agora ?? (() => new Date()))();

  const travar = (
    motivo: MotivoDeBloqueio | string,
    leitura: LeituraDoLembrete,
    donoAvisado = false,
  ): DesfechoDoLembrete & { readonly leitura: LeituraDoLembrete } => {
    metricas.contar(METRICA_TRAVADOS, etiquetaDoMotivo(motivo));
    deps.log?.info({
      outcome: `lembrete_travado_${etiquetaDoMotivo(motivo).toLowerCase()}`,
      tenant_id: tenantId,
    });
    return { enviado: false, motivo, donoAvisado, leitura };
  };

  const vazia: LeituraDoLembrete = { marcacao: null, destino: null, factos: null };

  // ------------------------------------------------- 1, 2 e 3, numa transacção
  const lido = await deps.comTenant(tenantId, async (cliente) => {
    const linhas = await cliente.query(SQL_MARCACAO, [evento.booking_id]);
    const linha = linhas.rows[0];
    if (linha === undefined) return { bloqueio: "MARCACAO_INEXISTENTE" as const, ...vazia };
    const marcacao = marcacaoDaLinha(linha);

    // **Critério 4, primeira metade.** O estado **actual**, e não o do
    // agendamento: uma marcação cancelada ou expirada entre o agendamento e o
    // disparo não lembra. É a razão pela qual o KAM-047 escreveu o
    // `emitirBookingCancelled` — sem o caminho do cliente, o lembrete continuava
    // a achar que a marcação existia e saía um template **pago**.
    if (marcacao.estado !== ESTADO_QUE_LEMBRA) {
      return { bloqueio: "MARCACAO_NAO_CONFIRMADA" as const, marcacao, destino: null, factos: null };
    }

    // **Critério 4, segunda metade.** O `inicio` **actual**. Uma remarcação
    // reagenda com outro `jobId` (ver o `schedule.ts`); este *job* é o antigo, e
    // o que o mata é esta comparação e não a fila.
    if (marcacao.inicioAt !== instanteComoIso(evento.inicio_at)) {
      return { bloqueio: "MARCACAO_REMARCADA" as const, marcacao, destino: null, factos: null };
    }

    // **Critério 6.** Antes do destino e antes do corpo: ver a nota do módulo.
    const semOptIn = await portaoDoConsentimento(cliente, tenantId, marcacao.contactId);
    if (semOptIn !== null) {
      return { bloqueio: semOptIn, marcacao, destino: null, factos: null };
    }

    const destino = await lerDestino(cliente, tenantId, marcacao.contactId);
    if (destino === null) {
      return { bloqueio: "SEM_CONVERSA" as const, marcacao, destino: null, factos: null };
    }

    // Os **factos**, e os dois vêm da base. O nome do serviço é a única coisa
    // que esta transacção lê a mais, e é o `{{1}}` do corpo aprovado.
    const servico = await cliente.query(SQL_SERVICO, [marcacao.serviceId]);
    const nome = servico.rows[0]?.["nome"];
    if (nome === undefined || nome === null) {
      // Um serviço que a marcação referencia e que não existe é uma violação da
      // chave estrangeira da revisão `0025`, logo não acontece com a base
      // íntegra. Trata-se como marcação inexistente e não se lança, pela razão
      // do `instanteDoLembrete`: uma linha que a base não devia ter não derruba
      // o consumo de um evento — fica na métrica e na DLQ, que é onde se vê.
      return { bloqueio: "MARCACAO_INEXISTENTE" as const, marcacao, destino, factos: null };
    }
    const factos: FactosDaMarcacao = {
      nomeDoServico: String(nome),
      inicioAt: marcacao.inicioAt,
    };
    return { bloqueio: null, marcacao, destino, factos };
  });

  const leitura: LeituraDoLembrete = {
    marcacao: lido.marcacao,
    destino: lido.destino,
    factos: lido.factos,
  };
  if (lido.bloqueio !== null) return travar(lido.bloqueio, leitura);

  const marcacao = lido.marcacao as Marcacao;
  const destino = lido.destino as DestinoDoLembrete;
  const factos = lido.factos as FactosDaMarcacao;

  // ------------------------------------------------------------- 4. o corpo
  //
  // **Critério 3.** Com a janela aberta vai mensagem livre (`service`); com ela
  // fechada vai o *template utility*. O `janelaAberta` é o do KAM-015 e o limite
  // é **estrito** — uma janela que expira exactamente agora está fechada, que é
  // a leitura conservadora e a certa: a alternativa era enviar texto livre no
  // instante em que a Meta o passa a recusar, e descobri-lo por um `131047`.
  //
  // Nos dois casos os valores saem dos **mesmos factos** e do mesmo corpo
  // aprovado: ver a nota do `textoDoLembrete`.
  const aberta = janelaAberta({ expiraEm: destino.janelaExpiraEm }, agora);
  const chave = chaveDoLembrete(marcacao.bookingId);
  const corpoLivre = { tipo: "texto" as const, texto: textoDoLembrete(factos) };
  const corpoDeTemplate = {
    tipo: "template" as const,
    nome: TEMPLATE_DO_LEMBRETE,
    idioma: IDIOMA_DO_LEMBRETE,
    parametros: parametrosDoLembrete(factos),
  };

  // ---------------------------------------------------------- 5. o Outbound
  const enviar = (corpo: typeof corpoLivre | typeof corpoDeTemplate) =>
    deps.saida.enviar({
      tenantId,
      channelId: destino.channelId,
      contactId: marcacao.contactId,
      conversationId: destino.conversationId,
      phoneNumberId: destino.phoneNumberId,
      idempotencyKey: chave,
      corpo,
      // **`doBot: true` com `turnoIniciadoEm`.** As duas coisas, e a segunda era
      // o defeito mais caro desta entrega. Ver a nota do módulo: sem ela o
      // guarda do KAM-018 suprimia **todos** os lembretes e gastava a chave.
      doBot: true,
      turnoIniciadoEm: agora,
    });

  let resultado = await enviar(aberta ? corpoLivre : corpoDeTemplate);

  // A janela pode ter fechado **entre** a leitura do `SQL_DESTINO` e a decisão
  // do adapter, que lê a sua própria janela com o seu próprio relógio. Nesse
  // caso o corpo já era texto livre e a recusa é `WINDOW_CLOSED` — e o critério
  // 3 manda que, com a janela fechada, vá o *template utility*. Cair para o
  // *template* é o que o critério pede; travar aqui perdia o lembrete, e não há
  // hoje quem o reentregue. Achado da revisão adversarial.
  //
  // **Uma vez só, e não em ciclo:** a segunda recusa já não é uma corrida, é uma
  // janela fechada com um *template* que também não pôde sair, e repetir não
  // muda nada. A chave não foi gasta — o `WINDOW_CLOSED` é decidido **antes** da
  // linha —, pelo que a segunda chamada enfileira com a mesma chave.
  if (!resultado.ok && resultado.motivo === WINDOW_CLOSED && aberta) {
    deps.log?.info({ outcome: "lembrete_janela_fechou_na_corrida", tenant_id: tenantId });
    resultado = await enviar(corpoDeTemplate);
  }

  if (resultado.ok) {
    // **Um `repetido` não é por si um envio.** O adapter responde `ok` para uma
    // chave que já tem linha **sem olhar ao `state` dela**, pelo que uma linha
    // `failed` ou `suppressed_by_human` chegava aqui como «enviado». Lê-se o
    // estado e decide-se. Ver a nota do módulo.
    if (resultado.repetido) {
      const estado = await deps.comTenant(tenantId, (cliente) =>
        estadoDaChave(cliente, tenantId, chave),
      );
      if (!repetidoSaiu(estado)) return travar("CHAVE_GASTA", leitura);
      // **Não se conta.** É a decisão do `adapter.ts` do KAM-015, que sai pelo
      // ramo do `repetido` sem tocar na `METRICA_ENVIADAS`: o contador mede
      // mensagens, e uma repetição não é uma mensagem nova. A primeira versão
      // contava, e cinco entregas davam **cinco** num contador que o
      // `docs/lembretes.md` apresenta como «quanto do tráfego de lembretes é
      // pago». Achado da revisão adversarial — e o ensaio dela **exigia** o
      // número inflacionado, pelo que a correcção estava presa por um ensaio.
      deps.log?.info({ outcome: "lembrete_repetido", tenant_id: tenantId });
      return {
        enviado: true,
        canal: canalDoKind(resultado.kind, deps.log),
        wamid: resultado.wamid,
        repetido: true,
        leitura,
      };
    }
    const canal = canalDoKind(resultado.kind, deps.log);
    metricas.contar(METRICA_ENVIADOS, canal);
    deps.log?.info({ outcome: "lembrete_enviado", tenant_id: tenantId });
    return { enviado: true, canal, wamid: resultado.wamid, repetido: false, leitura };
  }

  // -------------------------------------------- 6. a recusa, e o critério 5
  //
  // Um *template* que não pode sair **bloqueia o envio, avisa o dono e registra
  // o motivo**. As três coisas, e o aviso vai pela porta porque é a costura
  // entre dois módulos que não se conhecem — a mesma escolha que o
  // `avisarPainel` do `hnd/resposta.ts` fez.
  if (RECUSAS_DE_TEMPLATE.includes(resultado.motivo) && deps.avisarDono !== null) {
    await deps.avisarDono({
      tenantId,
      bookingId: marcacao.bookingId,
      conversationId: destino.conversationId,
      template: TEMPLATE_DO_LEMBRETE,
      idioma: IDIOMA_DO_LEMBRETE,
      motivo: resultado.motivo,
    });
    return travar(resultado.motivo, leitura, true);
  }
  return travar(resultado.motivo, leitura);
}

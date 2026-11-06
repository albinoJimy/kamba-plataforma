/**
 * Vocabulário dos lembretes de marcação (KAM-048).
 *
 * Aqui só tipos, domínios fechados e constantes — a mesma divisão que o
 * `../contrato.ts` do KAM-047 faz, e pela mesma razão: é o ficheiro que se lê
 * para saber o que as palavras significam, e é o que os três módulos ao lado
 * importam em vez de reescreverem.
 *
 *     schedule.ts   quando o lembrete dispara, e quando não dispara de todo
 *     template.ts   o corpo e os parâmetros, **só de factos da marcação**
 *     deliver.ts    os portões (estado, opt-in, janela, template) e o envio
 *
 * ## O que este ticket **não** escreve, porque já existia
 *
 * Medido contra `refs/remotes/publico/main` antes da primeira edição, e vale a
 * pena ficar escrito para que ninguém o reescreva por engano:
 *
 * * o **contrato do evento** `booking.reminder_due` está publicado — `v1` e
 *   `v2` em `contratos/eventos/booking.reminder_due/`, com exemplo cada, o
 *   espelho em `libs/py-core/.../eventos/contratos.py`, o catálogo em
 *   `packages/contracts/src/eventos.gerado.ts` e as três menções no
 *   `canon/dicionario.yaml`. Este ticket **consome** o `v1`, que é a versão que
 *   a subscrição de `registry/servicos.yaml` declara;
 * * a **decisão de janela** e o **portão do template** são do KAM-015: o
 *   `decidir` de `outbound/decisao.ts` devolve `WINDOW_CLOSED` sem chamada
 *   HTTP, e `TEMPLATE_NOT_APPROVED`, `TEMPLATE_BLOCKED` e
 *   `MARKETING_NOT_ALLOWED` para um template que não pode sair. Não se
 *   reimplementa nenhum — liga-se, e o que este módulo acrescenta é o que fazer
 *   com a recusa (critério 5);
 * * a **idempotência** é a `UNIQUE (tenant_id, idempotency_key)` de
 *   `outbound_messages` mais o `ON CONFLICT ... DO NOTHING RETURNING` do
 *   `SQL_ENFILEIRAR`. O que este módulo fornece é a **chave**, e é ela que faz
 *   cinco entregas darem uma mensagem;
 * * o **gate de consentimento** é o KAM-022: a vista `consent_actual`, o
 *   `SQL_ESTADO` e o `estadoDoConsentimento`. Este módulo chama-os.
 *
 * ## Os dois números são *proposta*, e estão aqui e não no DDL
 *
 * A antecedência de 24 h e o mínimo de 2 h vêm do critério 1, que os marca
 * *proposta* e «por tenant». Ficam em constantes com a unidade no nome, pela
 * razão que o `TTL_DO_HOLD_MS` do KAM-047 escreveu: um número no `CHECK` de uma
 * coluna obriga a uma revisão de base de dados para o calibrar. O «por tenant»
 * é o passo seguinte e tem credor — ver `ANTECEDENCIA_MS`.
 */

import { IDIOMA_BASE } from "@kamba/core-ts/outbound";

/** O mínimo de um cliente SQL de que este módulo precisa. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }>;
}

/** O tipo e a versão do evento que o lembrete consome (dicionário §3.5). */
export const TIPO_BOOKING_REMINDER_DUE = "booking.reminder_due";

/**
 * A versão que este módulo consome: **`v1`**.
 *
 * Há duas publicadas, e a escolha não é indiferente. O `v2` difere do `v1` em
 * **uma** coisa: o `enum` de `finalidades` ganha `partilha_estafeta` e
 * `notificacao_dono`. O `payload` é byte a byte o mesmo —
 * `(booking_id, inicio_at)`, os dois obrigatórios, `additionalProperties:
 * false` — pelo que nenhum campo novo chega a quem o lê.
 *
 * `v1` porque é o que a **subscrição** declara: `registry/servicos.yaml` diz
 * `- tipo: booking.reminder_due / versao: 1`, e a verificação `subscricoes` do
 * *gate* 7 confronta a subscrição com o catálogo. Consumir o `v2` sem mexer na
 * subscrição era declarar uma coisa e ler outra; mexer na subscrição para
 * ganhar duas finalidades que um lembrete não usa era alargar escopo para nada.
 */
export const VERSAO_BOOKING_REMINDER_DUE = 1;

/**
 * O que o `booking.reminder_due` v1 traz, na parte que este módulo lê.
 *
 * **Dois campos, e são os dois que o contrato exige.** O `inicio_at` não é
 * redundante com a leitura da base: é o `inicio` **de quando o lembrete foi
 * agendado**, e compará-lo com o `inicio` actual da marcação é exactamente o
 * que o critério 4 pede para não lembrar uma marcação remarcada — ver
 * `deliver.ts`.
 */
export interface BookingReminderDue {
  readonly booking_id: string;
  readonly inicio_at: string;
}

/**
 * A etiqueta da ordem do lembrete, dentro da chave de idempotência.
 *
 * `T-24h`, e é **texto da chave** e não o valor da antecedência: o critério 2
 * escreve a chave por extenso, `booking_id:reminder:T-24h`. Se a antecedência
 * for calibrada para outro valor, esta etiqueta muda com ela e as chaves
 * antigas continuam a existir — que é o que se quer, porque uma mensagem já
 * enviada não deve ser reenviada por se ter mudado um número.
 */
export const ETIQUETA_DA_ORDEM = "T-24h";

/**
 * A antecedência do lembrete: **24 h, *proposta***.
 *
 * O critério 1 escreve «`inicio − 24 h` (valor *proposta*, por tenant)». O
 * valor está aqui; o **por tenant** não está, e a caixa fica por isso — ler um
 * valor por tenant precisa de uma coluna que nenhuma revisão tem (a `0007` dá
 * `tenants.fuso_horario` e os limites de `entitlements.limites`, nenhum deles
 * uma antecedência de lembrete), e acrescentá-la é uma revisão de esquema que
 * este ticket não tem. Credor: **KAM-055**, dono da cadeia Alembic nesta volta,
 * ou o ticket que calibrar o número com dados do Piloto.
 */
export const ANTECEDENCIA_MS = 24 * 60 * 60 * 1_000;

/**
 * Quanto tempo tem de faltar para o início para um lembrete tardio valer a
 * pena: **2 h, *proposta***.
 *
 * É a segunda metade do critério 1: «marcação criada com menos de 24 h de
 * antecedência agenda o lembrete imediato **só se** o início estiver a mais de
 * 2 h (limiar *proposta*), caso contrário não envia». O que o número protege é
 * custo e utilidade ao mesmo tempo: um lembrete que chega uma hora antes de uma
 * marcação que o cliente acabou de fazer é um *template utility* pago para
 * dizer a alguém o que ele escreveu há cinco minutos.
 */
export const MINIMO_PARA_ENVIO_MS = 2 * 60 * 60 * 1_000;

/** O nome do *template utility* do lembrete, junto da Meta. */
export const TEMPLATE_DO_LEMBRETE = "lembrete_marcacao";

/**
 * O idioma do *template*. **`pt_PT`, e `pt_AO` não existe.**
 *
 * Herda o estado de quem o afirma: o bloco do ticket di-lo NÃO VERIFICADO, e o
 * `IDIOMA_BASE` do `outbound/contrato.ts` escreve a mesma frase. Não se promove
 * aqui — o que se faz é **reexportar** a constante de lá em vez de repetir o
 * valor, para que haja um sítio só a decidi-lo. Um `"pt_PT"` escrito aqui era a
 * segunda fonte para o mesmo facto, e divergiam no dia em que a Meta publicasse
 * o `pt_AO`.
 */
export const IDIOMA_DO_LEMBRETE: string = IDIOMA_BASE;

/**
 * O fuso em que a data e a hora do lembrete se escrevem.
 *
 * `Africa/Luanda`, pela razão que o `avisos/avisos.ts` do KAM-115 já escreveu:
 * é a omissão de `tenants.fuso_horario` (revisão `0007`) e é o fuso com que o
 * `metering/consultas.ts` fecha o mês. Um lembrete com a hora em UTC dizia a um
 * cliente de Luanda que a marcação é uma hora antes do que é.
 */
export const FUSO_DE_APRESENTACAO = "Africa/Luanda";

/**
 * Os factos da marcação de que um parâmetro do *template* pode vir. **Lista
 * fechada**, e é ela que torna o critério 7 verificável.
 *
 * O critério pede um «teste que prova que nenhum valor é composto pelo LLM». Um
 * teste que compare nomes de campo não prova nada — fica verde com um valor
 * inventado lá dentro, que foi o defeito que uma revisão apanhou noutro ticket.
 * O que o torna uma prova é esta lista mais a `PROVENIENCIA` abaixo: cada
 * parâmetro declara **de que campo vem**, e o ensaio mede os campos que o
 * construtor **leu** (por `Proxy`) e o que acontece ao parâmetro quando esse
 * campo **muda**. Um valor constante não lê campo nenhum e não muda com nenhum;
 * um valor de outra origem lê um campo que não está aqui.
 */
export const CAMPOS_DE_FACTO = ["nomeDoServico", "inicioAt"] as const;
export type CampoDeFacto = (typeof CAMPOS_DE_FACTO)[number];

/**
 * Os factos da marcação, e **nada mais**.
 *
 * Os dois vêm da base, na transacção do *tenant*: o `nomeDoServico` do
 * `servicos.services` (`SQL_SERVICO` do KAM-047) e o `inicioAt` do
 * `servicos.bookings` (`SQL_MARCACAO`). Não há campo por onde texto de um
 * modelo possa entrar, e é isso que faz a propriedade do critério 7 ser
 * estrutural e não uma convenção que alguém tem de respeitar.
 */
export interface FactosDaMarcacao {
  readonly nomeDoServico: string;
  /** O instante UTC em ISO-8601, tal como a base o devolve. */
  readonly inicioAt: string;
}

/**
 * De que facto vem cada parâmetro do *template*, pela ordem.
 *
 * O corpo *proposta* do bloco é «Lembrete: tem marcação de {{1}} no dia {{2}} às
 * {{3}}», pelo que são três parâmetros e dois factos — o `inicioAt` dá dois,
 * porque a data e a hora são posições diferentes no corpo aprovado e a Meta
 * numera por posição.
 */
export const PROVENIENCIA: readonly CampoDeFacto[] = [
  "nomeDoServico",
  "inicioAt",
  "inicioAt",
];

/** Quantos parâmetros o corpo aprovado tem. Deriva da `PROVENIENCIA`. */
export const PARAMETROS_DO_LEMBRETE = PROVENIENCIA.length;

/**
 * Porque é que um lembrete **não** sai, por decisão deste módulo.
 *
 * Lista fechada, e **não se confunde com os `MOTIVOS_DE_RECUSA` do KAM-015**:
 * estes são os portões que correm **antes** de o Outbound ser chamado, e os
 * dele são as recusas dele. Separá-los é o que deixa um painel distinguir «não
 * lembrámos porque a marcação foi cancelada» de «não lembrámos porque o
 * template não está aprovado» — a primeira é o sistema a funcionar, a segunda é
 * um incidente com dono.
 *
 *     MARCACAO_INEXISTENTE    o `booking_id` do evento não está na base
 *     MARCACAO_NAO_CONFIRMADA o estado não é `confirmada` (cancelada, hold, expirada)
 *     MARCACAO_REMARCADA      o `inicio` actual não é o do agendamento
 *     SEM_OPT_IN              não há consentimento válido para a finalidade
 *     SEM_TEXTO_VIGENTE       a `consent_texts` não tem versão a vigorar
 *     SEM_CONVERSA            o contacto não tem conversa, logo não há canal
 */
export const MOTIVOS_DE_BLOQUEIO = [
  "MARCACAO_INEXISTENTE",
  "MARCACAO_NAO_CONFIRMADA",
  "MARCACAO_REMARCADA",
  "SEM_OPT_IN",
  "SEM_TEXTO_VIGENTE",
  "SEM_CONVERSA",
] as const;
export type MotivoDeBloqueio = (typeof MOTIVOS_DE_BLOQUEIO)[number];

/**
 * A finalidade de consentimento que um lembrete exige: **`transacao`**.
 *
 * O critério 6 escreve «opt-in registado para a categoria *utility*», e as duas
 * palavras vivem em domínios diferentes: *utility* é uma **categoria de
 * facturação da Meta** (`CATEGORIAS` do KAM-015) e `transacao` é uma
 * **finalidade de tratamento** (`FINALIDADES` do dicionário §3.1 e do KAM-022).
 * Não há finalidade chamada `utility`, e inventá-la era pôr vocabulário da
 * factura da Meta dentro do registo de consentimento.
 *
 * A leitura que esta constante escreve, e que fica como **leitura** e não como
 * facto: o lembrete de uma marcação é o acto comercial, logo `transacao` — a
 * mesma escolha que o `FINALIDADES_BOOKING_CREATED` do KAM-047 fez para o
 * envelope do evento e que o `FINALIDADE_DO_AVISO` do KAM-022 fez para o aviso
 * do primeiro contacto. O que **não** é é `marketing`, e isso é o que o
 * critério protege: a frequência de *marketing* é zero no Piloto.
 */
export const FINALIDADE_DO_LEMBRETE = "transacao";

/** O desfecho de uma tentativa de lembrete. */
export type DesfechoDoLembrete =
  | {
      readonly enviado: true;
      /** `service` com a janela aberta, `utility` com ela fechada. */
      readonly canal: "service" | "utility";
      readonly wamid: string | null;
      /** `true` quando a chave já tinha passado: não houve mensagem nova. */
      readonly repetido: boolean;
    }
  | {
      readonly enviado: false;
      /** Um dos nossos, ou o do Outbound quando foi ele a recusar. */
      readonly motivo: MotivoDeBloqueio | string;
      /** `true` quando o dono foi avisado (critério 5). */
      readonly donoAvisado: boolean;
    };

/**
 * O que o dono recebe quando um *template* bloqueia o lembrete (critério 5).
 *
 * A forma é a do `AvisoDeJanelaFechada` do `hnd/resposta.ts`, e a razão é a
 * mesma: é a costura entre dois módulos que não se conhecem, e quem a liga é
 * quem tem o painel. O `motivo` é o do Outbound — `TEMPLATE_NOT_APPROVED`,
 * `TEMPLATE_BLOCKED` ou `MARKETING_NOT_ALLOWED` —, e vai tal e qual para que o
 * painel diga ao dono **qual** dos três aconteceu: o primeiro é um template que
 * a Meta ainda não aprovou, o terceiro é um que ela recategorizou para
 * *marketing*, e o que a PME tem de fazer é diferente nos dois casos.
 */
export interface AvisoDeTemplateBloqueado {
  readonly tenantId: string;
  readonly bookingId: string;
  readonly conversationId: string;
  /** O *template* que não pôde sair. */
  readonly template: string;
  readonly idioma: string;
  /** O motivo do Outbound, tal e qual. */
  readonly motivo: string;
}

/** Como se avisa o dono. Porta: quem a liga é quem tem o painel (KAM-019). */
export type AvisarDono = (aviso: AvisoDeTemplateBloqueado) => Promise<void>;

/**
 * O que o envio precisa de saber sobre o canal e a conversa do contacto.
 *
 * Sai do `SQL_DESTINO` e não de um parâmetro: um lembrete dispara por evento e
 * não dentro de um turno, pelo que não há `ChannelContext` resolvido por
 * ninguém — ao contrário de tudo o que o CHR chama.
 */
export interface DestinoDoLembrete {
  readonly conversationId: string;
  readonly channelId: string;
  readonly phoneNumberId: string;
  /** `null` quando a conversa nunca recebeu nada: a janela nunca abriu. */
  readonly janelaExpiraEm: Date | null;
}

/**
 * A porta de saída: o `enviar` do `Saida` do KAM-015.
 *
 * **Porta e não a classe**, pela razão que o `FilaDeExpiracao` do KAM-045
 * escreveu: o que os ensaios têm de medir é a chave, o corpo e o que se faz com
 * cada recusa, e nenhuma dessas coisas precisa de um PostgreSQL nem de um
 * cliente da Graph API. Quem monta o módulo passa o `Saida` verdadeiro, que a
 * satisfaz estruturalmente.
 */
export interface PortaDeSaida {
  enviar(pedido: {
    readonly tenantId: string;
    readonly channelId: string;
    readonly contactId: string;
    readonly conversationId: string;
    readonly phoneNumberId: string;
    readonly idempotencyKey: string;
    readonly corpo:
      | { readonly tipo: "texto"; readonly texto: string }
      | {
          readonly tipo: "template";
          readonly nome: string;
          readonly idioma: string;
          readonly parametros: readonly string[];
        };
    readonly doBot: boolean;
  }): Promise<
    | {
        readonly ok: true;
        readonly id: string;
        readonly wamid: string | null;
        readonly kind: string;
        readonly repetido: boolean;
      }
    | { readonly ok: false; readonly motivo: string; readonly codigo: number | null }
  >;
}

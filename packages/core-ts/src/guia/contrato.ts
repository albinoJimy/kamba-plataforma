/**
 * O vocabulário do passo guiado do Embedded Signup: pré-voo, estados visíveis,
 * capacidade e as portas que ele precisa (KAM-093).
 *
 * Nenhuma lógica aqui, e nenhum efeito: constantes, tipos e portas. É a forma
 * do `../inscricao/contrato.ts` e do `../onboarding/contrato.ts`.
 *
 * ## Três módulos com «onboarding» no nome, e este é o do meio
 *
 *     ../inscricao/    o registo e o OTP (KAM-086): sai um caso com o telefone
 *                      provado
 *     ./ (guia/)       a página que leva o dono, **presente**, pelo popup do ES
 *                      v4 — pré-voo, capacidade, abandono e retoma, a
 *                      verificação de que o número ligado é o do OTP, e o que
 *                      se diz ao dono quando o canal cai
 *     ../onboarding/   a troca do `code`, o cofre e a subscrição (KAM-016); o
 *                      guia chama-a por porta e **não** a reimplementa
 *
 * ## As tabelas que o bloco nomeia e que não existem
 *
 * O bloco grava o pré-voo em `onboarding_case.preflight`, escreve os gates
 * `meta_es` e `meta_pagamento` em `onboarding_gate` e abre um `review_case`
 * tipo `es_falhado`. **Nenhuma das três tabelas existe na base**, medido contra
 * a cadeia de revisões até à `0040`:
 *
 *     onboarding_case   existe desde a revisão `0043` (KAM-087), com o
 *                       `preflight`; falta o adaptador SQL do guia que o
 *                       escreva
 *     onboarding_gate   credor KAM-092
 *     review_case       credor KAM-089
 *
 * Criar a primeira para lhe pendurar uma coluna era decidir a emenda de
 * passagem, que é o que o KAM-086, o KAM-090 e o KAM-091 recusaram pela mesma
 * razão. O que este módulo entrega são as **portas** onde os adaptadores SQL
 * vão encaixar, e os duplos em memória (`./memoria.ts`) que CI e `dev` usam — o
 * precedente do `RepositorioDeCasos`. A consequência está no código e não numa
 * nota: o `onboarding-web` já recusa arrancar em `prod`.
 */

import type { ResultadoDoEs } from "../onboarding/contrato.ts";

/**
 * A versão mínima da app WhatsApp Business. CONFIRMADO (`E1` §3): a
 * coexistência exige `≥ 2.24.17`.
 */
export const VERSAO_MINIMA_DA_APP = "2.24.17";

/**
 * Os sete itens do pré-voo, pela ordem do critério 2.
 *
 * Cada um é `auto` (o sistema verifica) ou `atestado` (o dono declara). A
 * divisão sai do texto do critério e não de gosto: a versão da app e a
 * abertura recente estão escritas como «atestado do dono», porque a KAMBÁ não
 * vê o telemóvel dele; o tipo do número, a categoria e o *display name* lêem-se
 * de dados que já temos.
 *
 *     app_versao          atestado  versão ≥ 2.24.17 e aberta nos últimos dias
 *     numero_movel        auto      móvel; fixo ⇒ rota de voz / `cloud_only`
 *     whatsapp_pessoal    atestado  número já em WhatsApp pessoal ⇒ converter
 *     cartao_internacional atestado cartão em moeda internacional (Billing Hub)
 *     categoria_aprovada  auto      a categoria passou o *screening* (KAM-088)
 *     display_name        auto      nome válido, sem termos de categoria bloqueada
 *     dono_presente       atestado  o dono está presente e com o telemóvel
 */
export const ITENS_DO_PREFLIGHT = [
  "app_versao",
  "numero_movel",
  "whatsapp_pessoal",
  "cartao_internacional",
  "categoria_aprovada",
  "display_name",
  "dono_presente",
] as const;
export type ItemDoPreflight = (typeof ITENS_DO_PREFLIGHT)[number];

/** Como um item se verifica. A forma do `Detalhes Técnicos` do bloco. */
export type TipoDeItem = "auto" | "atestado";

/** O tipo de cada item. Lista fechada, uma célula por item. */
export const TIPO_DO_ITEM: Readonly<Record<ItemDoPreflight, TipoDeItem>> = {
  app_versao: "atestado",
  numero_movel: "auto",
  whatsapp_pessoal: "atestado",
  cartao_internacional: "atestado",
  categoria_aprovada: "auto",
  display_name: "auto",
  dono_presente: "atestado",
};

/**
 * O porquê de um item, em lista fechada.
 *
 * **Fechada, e a razão é a coluna que a vai guardar**: o `detalhe` vai para
 * `onboarding_case.preflight`, que o T&S lê numa fila de revisão, e texto livre
 * ali era um sítio onde um *display name* com um telefone dentro acabava
 * guardado. Um código não leva dados do dono.
 */
export const DETALHES = [
  "ok",
  "nao_atestado",
  "versao_antiga",
  "versao_ilegivel",
  "fixo_rota_cloud_only",
  "numero_ilegivel",
  "converter_para_business",
  "sem_cartao_internacional",
  "categoria_por_aprovar",
  "categoria_recusada",
  "nome_vazio",
  "nome_com_termo_bloqueado",
] as const;
export type Detalhe = (typeof DETALHES)[number];

/** Um item do pré-voo, na forma que o bloco escreve: `{ id, tipo, ok, detalhe }`. */
export interface ItemAvaliado {
  readonly id: ItemDoPreflight;
  readonly tipo: TipoDeItem;
  readonly ok: boolean;
  readonly detalhe: Detalhe;
}

/** A rota do canal que o pré-voo decide. */
export type Rota = "coexistencia" | "cloud_only";

/** O pré-voo inteiro, como se grava. */
export interface Preflight {
  readonly itens: readonly ItemAvaliado[];
  /** `true` quando todos os itens estão `ok` — com a excepção do `numero_movel`. */
  readonly podeAbrir: boolean;
  /**
   * `coexistencia` por omissão; `cloud_only` quando o número é fixo.
   *
   * **O fixo não bloqueia**, e é a letra do critério: «fixo ⇒ rota de voz /
   * `cloud_only`». Um número fixo não corre a app WhatsApp Business num
   * telemóvel, logo a coexistência não lhe serve, mas `cloud_only` com
   * verificação por voz sim. A elegibilidade de Angola para coexistência (H3)
   * é **NÃO VERIFICADA** e não se impõe aqui: é a mesma rota para todos.
   */
  readonly rota: Rota;
  readonly avaliadoEm: Date;
}

/**
 * O que o dono declara. Cada campo é o que o critério manda atestar, e mais
 * nada; a ausência é «não atestado» e nunca «sim».
 */
export interface Atestados {
  /** A versão que o dono lê em «Definições → Ajuda», como texto. */
  readonly versaoDaApp?: unknown;
  /** Abriu a app nos últimos dias. */
  readonly appAbertaRecentemente?: unknown;
  /** O número está hoje em WhatsApp **pessoal** (e não Business). */
  readonly numeroEmWhatsAppPessoal?: unknown;
  /** Tem cartão em moeda internacional para o Billing Hub. */
  readonly cartaoInternacional?: unknown;
  /** Está presente, com o telemóvel na mão. */
  readonly donoPresente?: unknown;
}

/** O veredicto do *screening* de categoria (KAM-088), como este módulo o lê. */
export type Screening = "aprovada" | "por_aprovar" | "recusada";

/**
 * Os estados do canal **visíveis ao dono**, pela ordem do critério 5.
 *
 * Os seis primeiros são o caminho feliz que o critério enumera; `abandonado` e
 * `falhado` são os dois que ele nomeia a seguir; `desligado` é o do critério 7
 * (`PARTNER_REMOVED`). **Não é o `channel_onboarding.fase`** (KAM-016), que tem
 * `ativo` e não tem `desligado`, nem o `channel_coexistence.estado` (KAM-017):
 * é a vista que junta as duas máquinas para quem está do outro lado do ecrã, e
 * é por isso que não leva o `ativo` — activar é do KAM-092/094.
 */
export const ESTADOS_DO_GUIA = [
  "pre_voo",
  "iniciado",
  "es_concluido",
  "subscrito",
  "a_sincronizar",
  "verificado",
  "pronto",
  "abandonado",
  "falhado",
  "desligado",
] as const;
export type EstadoDoGuia = (typeof ESTADOS_DO_GUIA)[number];

/**
 * As transições do guia. Escritas célula a célula, como o `TRANSICOES` do
 * `../onboarding/contrato.ts`.
 *
 * Três regras, e cada uma é um critério:
 *
 * * o caminho feliz é a cadeia do critério 5, e o `subscrito` pode saltar o
 *   `a_sincronizar` — em `cloud_only` não há sincronização;
 * * `abandonado` só sai de `iniciado` (popup fechado ou 30 min sem `FINISH`), e
 *   volta a `iniciado` pela **mesma** ligação — critério 5, sem criar caso novo;
 * * `falhado` e `desligado` voltam a `iniciado` — critérios 6 e 7: repete-se o
 *   ES sem novo registo. O `desligado` alcança-se de qualquer estado em que o
 *   canal já exista (`es_concluido` em diante): um `PARTNER_REMOVED` não espera
 *   que a sincronização acabe. **Excepto** uma falha por número divergente, que fica:
 *   ver `MOTIVOS_QUE_PRENDEM`.
 */
export const TRANSICOES_DO_GUIA: Readonly<Record<EstadoDoGuia, readonly EstadoDoGuia[]>> = {
  pre_voo: ["iniciado"],
  iniciado: ["es_concluido", "abandonado", "falhado"],
  es_concluido: ["subscrito", "falhado", "desligado"],
  subscrito: ["a_sincronizar", "verificado", "falhado", "desligado"],
  a_sincronizar: ["verificado", "falhado", "desligado"],
  verificado: ["pronto", "falhado", "desligado"],
  pronto: ["desligado", "falhado"],
  abandonado: ["iniciado"],
  falhado: ["iniciado"],
  desligado: ["iniciado"],
};

/** `true` se a transição é uma das da matriz. */
export function transicaoDoGuiaValida(de: EstadoDoGuia, para: EstadoDoGuia): boolean {
  return TRANSICOES_DO_GUIA[de].includes(para);
}

/** Porque é que o guia falhou. Lista fechada, pela razão do `DETALHES`. */
export const MOTIVOS_DE_FALHA = [
  "numero_divergente",
  "sincronizacao_vencida",
  "ligacao_recusada",
  "tecto_da_meta",
] as const;
export type MotivoDeFalha = (typeof MOTIVOS_DE_FALHA)[number];

/**
 * Os motivos que **não** se retomam pela página.
 *
 * Um dono que ligou um número que não é o do OTP não volta a tentar sozinho:
 * o critério manda abrir um `review_case`, e deixar `falhado → iniciado` livre
 * era deixar o atacante tentar outra vez até a revisão chegar. Quem desprende
 * é a revisão (KAM-089), e não esta página.
 */
export const MOTIVOS_QUE_PRENDEM: readonly MotivoDeFalha[] = ["numero_divergente"];

/** O prazo do popup, em minutos. O `PRAZO_DE_ABANDONO_MIN` do KAM-016. */
export { PRAZO_DE_ABANDONO_MIN } from "../onboarding/contrato.ts";

/**
 * O tecto da janela de sete dias. **CONFIRMADO** (`E1` §3): dez clientes novos
 * por sete dias antes de verificação completa. Chama-se `es_max_por_7d` no
 * critério 8 e é configuração; o valor por omissão é o do `E1`.
 */
export { JANELA_DE_ONBOARDINGS_DIAS, LIMITE_DE_ONBOARDINGS } from "../onboarding/contrato.ts";

/** O `CapacityGate` dos *Detalhes Técnicos*, à letra. */
export interface CapacityGate {
  reserve(onboardingId: string): Promise<"granted" | "lista_espera">;
  release(onboardingId: string): Promise<void>;
}

/** Um gate do `onboarding_gate` que este ticket escreve. */
export type GateDoEs = "meta_es" | "meta_pagamento";

/**
 * A porta dos gates de activação. **Credor da tabela: KAM-092.**
 *
 * O guia escreve `meta_es` (sincronizado e verificado) e `meta_pagamento`; quem
 * os lê para activar é o KAM-092/094. Um gate vermelho não é um erro: é o
 * estado que impede a activação, com o motivo ao lado.
 */
export interface GatesDoOnboarding {
  marcar(onboardingId: string, gate: GateDoEs, verde: boolean, motivo: string): Promise<void>;
}

/** A porta da fila de revisão. **Credor da tabela: KAM-089.** */
export interface FilaDeRevisao {
  /** Abre um caso de revisão; idempotente por `(onboardingId, tipo)`. */
  abrir(onboardingId: string, tipo: "es_falhado", motivo: MotivoDeFalha): Promise<void>;
}

/**
 * O que se sabe do método de pagamento do WABA.
 *
 * Três valores e não dois, e o terceiro é o normal hoje: **não há fonte
 * CONFIRMADA** de que a Graph diga, antes do primeiro envio, se o WABA tem
 * cartão no Billing Hub — o KAM-023 detecta a ausência **depois**, por taxa de
 * falhas sobre envios reais. `desconhecido` deixa o gate vermelho, que é a
 * letra do critério 3: «sem método de pagamento **detectado**».
 */
export type EstadoDoPagamento = "detectado" | "ausente" | "desconhecido";

/** A porta do método de pagamento. Credor do adaptador real: KAM-023 / ext:KAM-102. */
export interface DetectorDePagamento {
  verificar(wabaId: string): Promise<EstadoDoPagamento>;
}

/**
 * O que o dono recebe fora do número da loja. **SMS ou e-mail, nunca WhatsApp.**
 *
 * Chama-se `AvisoDoGuia` e não `AvisoAoDono` porque esse nome é o do KAM-115
 * (`../avisos/`), que é quem a implementa por e-mail quando o adaptador
 * existir.
 *
 * É uma porta e não o `FakeSmsProvider` directo porque o critério 7 diz o
 * canal pela negativa — «nunca pelo número da loja» — e a forma de o afirmar é
 * esta porta não ter maneira de mandar por WhatsApp. O texto é um modelo
 * fechado (`MensagemAoDono`), e não texto livre: o telefone do dono **não**
 * entra aqui; quem o resolve é a implementação, a partir do caso.
 */
export interface AvisoDoGuia {
  avisar(onboardingId: string, mensagem: MensagemAoDono, ligacao: string): Promise<void>;
}

/**
 * As mensagens ao dono, em lista fechada.
 *
 * **Três, e o aviso de canal desligado e o de inactividade não estão aqui.**
 * São do KAM-115: o `../avisos/` já os entrega por e-mail (gatilhos
 * `canal_desligado` e `inactividade`, alimentados pelo `channel.updated` e pelo
 * `channel.inactivity_warning` do KAM-017), e uma segunda mensagem com o mesmo
 * alarme era ruído para o dono. O que é deste guia é o que o KAM-115 não leva:
 * os **passos de reconexão**, com a ligação de retoma, e os dois avisos da
 * sincronização do próprio ES.
 */
export const MENSAGENS_AO_DONO = [
  "reconectar",
  "sincronizacao_falhou",
  "sincronizacao_lembrete",
] as const;
export type MensagemAoDono = (typeof MENSAGENS_AO_DONO)[number];

/**
 * O que o guia guarda por caso. **A coluna do bloco é `onboarding_case.preflight`**;
 * o resto (estado, reserva, tentativa) é o mínimo para o critério 5 — retomar
 * pela mesma ligação sem criar dois casos — e vive na mesma linha quando a
 * tabela existir.
 */
export interface EstadoGuardado {
  readonly onboardingId: string;
  readonly estado: EstadoDoGuia;
  readonly preflight: Preflight | null;
  /** Quando o popup abriu pela última vez. É daqui que contam os 30 min. */
  readonly iniciadoEm: Date | null;
  readonly motivo: MotivoDeFalha | null;
  /** A tentativa do KAM-016, quando já houve `code`. */
  readonly tentativaId: string | null;
  readonly phoneNumberId: string | null;
  readonly wabaId: string | null;
  /** `true` depois de o `display_phone_number` coincidir com o OTP (critério 4). */
  readonly numeroConfirmado: boolean;
  /** `true` depois de o KAM-017 dar a sincronização por concluída (ou em `cloud_only`). */
  readonly sincronizado: boolean;
  readonly actualizadoEm: Date;
}

/**
 * Onde o estado do guia vive. **Credor do adaptador SQL: KAM-087**, na
 * mesma linha de `onboarding_case`.
 *
 * As transições são *compare-and-set*: `transitar` só escreve se o estado
 * actual for o esperado, e devolve `false` se não for. É o que faz o `FINISH`
 * repetido duas vezes produzir uma transição e não duas.
 */
export interface RepositorioDoGuia {
  ler(onboardingId: string): Promise<EstadoGuardado | null>;
  /** Cria em `pre_voo` se não existir; devolve o que lá está. */
  abrir(onboardingId: string): Promise<EstadoGuardado>;
  gravarPreflight(onboardingId: string, preflight: Preflight): Promise<void>;
  transitar(
    onboardingId: string,
    de: EstadoDoGuia,
    para: EstadoDoGuia,
    campos: Partial<
      Pick<
        EstadoGuardado,
        "iniciadoEm" | "motivo" | "tentativaId" | "phoneNumberId" | "wabaId" | "numeroConfirmado" | "sincronizado"
      >
    >,
  ): Promise<boolean>;
  /** Marca um dos dois factos que o `verificado` exige. Idempotente. */
  marcar(onboardingId: string, facto: "numeroConfirmado" | "sincronizado"): Promise<void>;
  /** Os casos em `iniciado` com `iniciadoEm` anterior a `antes`. */
  iniciadosAntesDe(antes: Date): Promise<readonly string[]>;
  /** O caso com esta ligação, ou `null`. Para os sinais que chegam por número. */
  porPhoneNumberId(phoneNumberId: string): Promise<string | null>;
}

/**
 * A porta para o KAM-016: liga o canal com o que o popup devolveu.
 *
 * Em produção é o cliente HTTP do `POST /internal/channels` do GWY; nos
 * ensaios, um duplo. **O guia não troca o `code`** — o *Handoff* proíbe-o
 * («Não reimplementes a troca de code») — e o *token* e o PIN nunca passam por
 * aqui: vão do GWY directamente ao cofre (critério 9).
 */
export interface LigadorDeCanal {
  ligar(entrada: ResultadoDoEs): Promise<ResultadoDaLigacao>;
}

/** O que a ligação devolve, na forma da resposta do `POST /internal/channels`. */
export interface ResultadoDaLigacao {
  /** `criado` (201), `repetido` (200) ou a recusa. */
  readonly desfecho: "criado" | "repetido" | "recusado" | "lista_espera";
  readonly tentativaId: string | null;
}

/**
 * O `featureType` que o guia declara ao KAM-016 numa ligação `cloud_only`.
 *
 * **É uma marca nossa, e não um valor da Meta.** O `modoDoSessionInfo` do
 * KAM-016 recusa um `session_info` sem `featureType` — decidir o modo pela
 * ausência era decidi-lo por omissão — e aceita como `cloud_only` qualquer
 * valor que não seja o da coexistência. O `E1` §3 só nomeia o da coexistência,
 * e a forma do `session_info` que o popup devolve é NÃO VERIFICADA; por isso o
 * guia **compõe** o `session_info` a partir da rota que o pré-voo gravou, em
 * vez de repassar o que a página diz, e diz qual dos dois modos abriu. Achado
 * da revisão adversarial: sem isto, todo o número fixo era recusado com 400.
 */
export const FEATURE_TYPE_CLOUD_ONLY = "kamba_cloud_only";

/** Levantada quando a página é pedida para um caso que não pode abrir. */
export class GuiaRecusadoError extends Error {
  override readonly name = "GuiaRecusadoError";
  readonly motivo:
    | "sem_caso"
    | "fase_errada"
    | "preflight_em_falta"
    | "preflight_por_cumprir"
    | "estado_errado"
    | "preso_em_revisao";

  constructor(motivo: GuiaRecusadoError["motivo"]) {
    super(`o passo guiado recusa: ${motivo}`);
    this.motivo = motivo;
  }
}

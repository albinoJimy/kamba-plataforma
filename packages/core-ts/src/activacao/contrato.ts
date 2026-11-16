/**
 * O vocabulário do último troço do onboarding: catálogo mínimo, teste ponta a
 * ponta e activação (KAM-094).
 *
 * Nenhuma lógica aqui, e nenhum efeito: constantes, tipos, portas e erros. É a
 * forma do `../guia/contrato.ts`.
 *
 * ## O que este ticket não reimplementa
 *
 *     ../screening/   o `screen` e o `assertPublishable` (KAM-088)
 *     ../revisao/     a fila e o `escritorComFila`, que abre o `review_case`
 *                     `catalogo` numa `condicional` (KAM-089)
 *     revisão 0058    o `advance_case`, o `transition_tenant` e os seis gates
 *                     (KAM-092): a activação é uma chamada, não uma cópia
 *     kamba_core.catalogo   a ingestão foto → rascunho (KAM-049), em Python
 *
 * ## D10: a KAMBÁ não tem número operacional
 *
 * O passo 9 do `docs/tecnica/10` §4.1 assume que «o sistema envia uma mensagem
 * de teste ao número da loja». Não há remetente: o tenant `platform` está
 * vedado e o D10 está aberto. Por isso o remetente por omissão é o **dono**
 * (`owner_assisted`), que manda «teste» de outro telefone, e o `prober_number`
 * só existe atrás de uma autorização explícita que hoje ninguém dá.
 */

/**
 * Quantos produtos publicados e permitidos fazem o catálogo mínimo.
 * *Proposta* (critério 1), configurável por quem constrói o serviço.
 */
export const CATALOGO_MINIMO = 5;

/** Quanto tempo o teste espera pelos quatro factos. *Proposta* (critério 4). */
export const PRAZO_DO_TESTE_S = 60;

/** Quantas falhas seguidas levam o caso à fila (critério 5). */
export const FALHAS_ATE_A_FILA = 3;

/** A palavra que o dono manda. Compara-se normalizada (caixa, acentos, espaços). */
export const PALAVRA_DO_TESTE = "teste";

/** As quatro causas de um teste falhado, pela ordem em que se verificam. */
export const CAUSAS_DO_TESTE = ["sem_inbound", "sem_resposta", "sem_entrega", "sem_consentimento"] as const;
export type CausaDoTeste = (typeof CAUSAS_DO_TESTE)[number];

/** Quem manda a mensagem de teste. */
export const REMETENTES_DO_TESTE = ["owner_assisted", "prober_number"] as const;
export type RemetenteDoTeste = (typeof REMETENTES_DO_TESTE)[number];

/** O que o dono lê numa falha. Genérico de propósito: a causa fina é da fila. */
export const MENSAGEM_DE_FALHA_AO_DONO =
  "O teste não ficou concluído. Confirme que enviou «teste» de outro telefone para o número da loja e tente outra vez — repetir não tem custo.";

/** A porta do bloco, à letra (Detalhes Técnicos). */
export interface SmokeProbe {
  start(onboardingId: string): Promise<{ instrucoes: string; expiraEm: Date }>;
  verify(onboardingId: string): Promise<{ ok: boolean; causa?: CausaDoTeste }>;
}

// ------------------------------------------------------------------ catálogo

/** Os quatro estados da oferta (`offer_terms.estado`, revisão 0028). */
export type EstadoDaOferta = "rascunho" | "publicado" | "pausado" | "arquivado";

/** Os três modos de preço (`offer_terms.preco_tipo`). */
export type PrecoTipo = "fixo" | "a_partir_de" | "sob_consulta";

/**
 * Um produto do tenant, como a contagem o precisa de ver.
 *
 * A oferta é a `offer_terms`; a confirmação do dono e a categoria do produto são
 * da ingestão do KAM-049 (`catalog_ingestions` em `publicada`, que o `CHECK`
 * dela só deixa com `confirmado_at` e `confirmado_por`).
 */
export interface ProdutoDoCatalogo {
  readonly tenantId: string;
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: PrecoTipo | null;
  readonly estado: EstadoDaOferta;
  readonly categoriaRestrita: string | null;
  readonly apagado: boolean;
  /** A categoria do produto, da ingestão. `null` sem ingestão publicada. */
  readonly categoria: string | null;
  /** `true` com uma ingestão `publicada` deste `sku` (a `OwnerConfirmation`). */
  readonly confirmadoPeloDono: boolean;
}

/**
 * A porta do catálogo do tenant. Em produção, `./sql.ts` sobre a `offer_terms`
 * e a `catalog_ingestions`; nos ensaios, `./memoria.ts`.
 */
export interface CatalogoDoTenant {
  produtos(tenantId: string): Promise<readonly ProdutoDoCatalogo[]>;
  /** Publica. `false` se a base recusou (não existe, restrito, arquivado). */
  publicar(tenantId: string, sku: string): Promise<boolean>;
  /** Tira de `publicado` para `rascunho`. Idempotente. */
  retirar(tenantId: string, sku: string): Promise<boolean>;
  /** Muda o nome. Não toca no estado: quem decide se continua visível é o serviço. */
  renomear(tenantId: string, sku: string, nome: string): Promise<boolean>;
}

/** A categoria declarada do tenant (a `sujeito_ref` da última decisão de categoria). */
export interface CategoriaDoTenant {
  declarada(tenantId: string): Promise<string>;
}

// ------------------------------------------------------------------- gates

/** Os seis gates de activação (`onboarding_gate.gate`, revisão 0058). */
export const GATES_DE_ACTIVACAO = [
  "meta_es",
  "meta_pagamento",
  "catalogo_minimo",
  "consentimento",
  "dpa",
  "e2e",
] as const;
export type GateDeActivacao = (typeof GATES_DE_ACTIVACAO)[number];

/** Os dois gates que este ticket escreve. */
export type GateDoKam094 = Extract<GateDeActivacao, "catalogo_minimo" | "e2e">;

/** A porta dos gates. Só o lote escreve (`kamba_batch`, revisão 0058). */
export interface GatesDaActivacao {
  marcar(onboardingId: string, gate: GateDoKam094, ok: boolean, evidencia: string): Promise<void>;
  /** `platform.onboarding_gates_em_falta(caso)`, pela ordem do bloco. */
  emFalta(onboardingId: string): Promise<readonly GateDeActivacao[]>;
}

/** As fases do caso que este ticket lê (PA-GOV-6). */
export type FaseDoCaso = "aguarda_catalogo" | "aguarda_teste" | "activo" | (string & {});

/** O caso de onboarding, no que importa aqui. */
export interface CasoDeActivacao {
  readonly onboardingId: string;
  readonly tenantId: string;
  readonly fase: FaseDoCaso;
}

/**
 * A máquina do caso: o `platform.advance_case` do KAM-092. **É ela que emite**
 * o `tenant.activated`, uma vez, sob o `FOR UPDATE` do caso.
 */
export interface MaquinaDoCaso {
  ler(onboardingId: string): Promise<CasoDeActivacao | null>;
  avancar(onboardingId: string, evento: "catalogo_minimo" | "activar", actor: string): Promise<FaseDoCaso>;
}

/** A porta da fila de revisão para o teste falhado (KAM-089). */
export interface FilaDoTeste {
  abrir(onboardingId: string, tipo: "es_falhado" | "saga", causa: CausaDoTeste): Promise<void>;
}

// --------------------------------------------------------------- o teste

/** Os quatro factos que o teste verifica, lidos da conversa. */
export interface FactosDoTeste {
  readonly inbound: boolean;
  /** Resposta do bot que identifica o assistente **e** a loja. */
  readonly resposta: boolean;
  readonly entregue: boolean;
  /** Aviso de 1.º contacto com `consent_event` gravado (KAM-022). */
  readonly consentimento: boolean;
  /** A conversa do teste, quando houve `inbound`. */
  readonly conversationId: string | null;
}

/** Onde se lêem os factos. Em produção, as tabelas da conversa; nos ensaios, webhooks do simulador. */
export interface ObservadorDoTeste {
  factos(onboardingId: string, desde: Date, ate: Date): Promise<FactosDoTeste>;
}

/** Marca a conversa do teste (`is_test`), que sai de métricas, golden e Score. */
export interface MarcadorDeTeste {
  marcar(tenantId: string, conversationId: string): Promise<void>;
}

/** Uma tentativa do teste, como se guarda. */
export interface TentativaDoTeste {
  readonly onboardingId: string;
  readonly iniciadaEm: Date;
  readonly expiraEm: Date;
  readonly resultado: "pendente" | "ok" | "falhou";
  readonly causa: CausaDoTeste | null;
}

/** Onde as tentativas vivem. Conta as falhas desde o último sucesso ou a última ida à fila. */
export interface RegistoDoTeste {
  iniciar(onboardingId: string, iniciadaEm: Date, expiraEm: Date): Promise<TentativaDoTeste>;
  corrente(onboardingId: string): Promise<TentativaDoTeste | null>;
  fechar(onboardingId: string, resultado: "ok" | "falhou", causa: CausaDoTeste | null): Promise<void>;
  /** Falhas seguidas desde a última tentativa `ok` ou o último `zerar`. */
  falhasSeguidas(onboardingId: string): Promise<number>;
  /** Recomeça a contagem depois de o caso ir à fila: repetir não tem custo. */
  zerar(onboardingId: string): Promise<void>;
}

// --------------------------------------------------------------- erros

/** A activação foi pedida sem as condições. `motivo` é um identificador fechado. */
export class ActivacaoRecusadaError extends Error {
  override readonly name = "ActivacaoRecusadaError";
  readonly motivo: "sem_caso" | "fase_errada" | "gates_em_falta" | "teste_por_fazer";
  readonly emFalta: readonly string[];

  constructor(motivo: ActivacaoRecusadaError["motivo"], emFalta: readonly string[] = []) {
    super(`activacao recusada: ${motivo}${emFalta.length > 0 ? ` (${emFalta.join(",")})` : ""}`);
    this.motivo = motivo;
    this.emFalta = emFalta;
  }
}

/** O `prober_number` pedido sem a decisão D10 que o permitiria. */
export class RemetenteVedadoError extends Error {
  override readonly name = "RemetenteVedadoError";
  constructor() {
    super(
      "prober_number vedado: a KAMBA nao tem numero operacional (D10 aberto) e o tenant platform nao envia",
    );
  }
}

/** O teste foi verificado sem ter sido iniciado. */
export class TesteNaoIniciadoError extends Error {
  override readonly name = "TesteNaoIniciadoError";
  constructor() {
    super("teste ponta a ponta verificado sem start");
  }
}

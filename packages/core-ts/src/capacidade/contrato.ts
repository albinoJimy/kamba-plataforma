/**
 * O vocabulário da lista de espera do limite de onboarding da Meta (KAM-095).
 *
 * Nenhuma lógica aqui, e nenhum efeito: constantes, tipos e portas. A lógica
 * está em `./lista.ts`; os duplos em `./memoria.ts`; o SQL em `./sql.ts`.
 *
 * ## O que a Meta limita, e o que disso é CONFIRMADO
 *
 * Até haver Business Verification + App Review + «Access Verification», a
 * Meta deixa ligar **10 clientes novos por 7 dias** (CONFIRMADO, `E1` §3). O
 * patamar seguinte, 200 por 7 dias, e o que a «Access Verification» exige são
 * **NÃO VERIFICADOS** (`E1` Q9, D5), e a forma exacta como a Meta conta os
 * onboardings também. Por isso o limite é **configuração com origem** e não
 * constante: a tabela `platform.onboarding_capacity` guarda o valor, de onde
 * veio (`ORIGENS_DO_LIMITE`) e a fonte, e a base recusa um valor acima de 10
 * que não seja `confirmado` (`LIMITE_SEM_CONFIRMACAO`).
 *
 * ## A fila, e a regra que a faz FIFO
 *
 *     aguardando ──convite──▶ convidado ──aceite/reserva──▶ concluido
 *         ▲  ▲                    │
 *         │  └──1.ª expiração ou recusa (para o fim, uma vez)
 *         │                       └──2.ª ──▶ expirado  (caso `abandonado`)
 *         └── devolução da vaga (popup fechado: o lugar de origem)
 *     aguardando | convidado ──desistência──▶ desistiu ──novo pedido──▶ aguardando (fim)
 *
 * **Uma vaga só se dá à cabeça da fila, ou a quem tem convite vivo.** Não há
 * outra porta: um caso novo com a fila vazia é a cabeça; com a fila cheia
 * entra pelo `aprovado_em` e espera. Daí a ordem por `aprovado_em` não poder
 * ser furada por quem está na página na hora certa — o critério 2.
 *
 * **vaga = limite − concluídos na janela − convites vivos**, a fórmula dos
 * Detalhes Técnicos. «Concluído» aqui é «recebeu a vaga» (o popup abriu): é o
 * que a Meta pode contar, e contar de mais custa esperar, contar de menos custa
 * um cliente recusado — a mesma regra que o dicionário escreve para o
 * `es_onboardings_7d` do KAM-016.
 */

/** Os estados de uma entrada, à letra do DDL dos Detalhes Técnicos. */
export const ESTADOS_DA_ENTRADA = ["aguardando", "convidado", "concluido", "expirado", "desistiu"] as const;

export type EstadoDaEntrada = (typeof ESTADOS_DA_ENTRADA)[number];

/** De onde vem o limite em vigor. Ver a nota do módulo. */
export const ORIGENS_DO_LIMITE = ["confirmado", "nao_verificado"] as const;

export type OrigemDoLimite = (typeof ORIGENS_DO_LIMITE)[number];

/**
 * O maior limite que se aceita sem origem `confirmado`. É o 10 do `E1` §3: um
 * valor acima dele é o patamar NÃO VERIFICADO, e a base recusa-o sem
 * confirmação escrita da Meta (critério 3).
 */
export const LIMITE_SEM_CONFIRMACAO = 10;

/** Validade de um convite, em horas. ***Proposta*** (critério 4). */
export const VALIDADE_DO_CONVITE_H = 48;

/** Expirações (ou recusas) até o caso passar a `abandonado` (critério 5). */
export const EXPIRACOES_ATE_ABANDONO = 2;

/**
 * Validade do KYC para reentrar sem o refazer, em dias. ***Proposta***: o
 * bloco escreve «validade do KYC *a definir*, 90 dias proposta» (critério 7).
 */
export const VALIDADE_DO_KYC_DIAS = 90;

/** As fases do caso que entram na fila (critério 1). */
export const FASES_ELEGIVEIS = ["aprovado", "aguarda_es"] as const;

/** O limite em vigor, como a tabela o guarda. */
export interface Limite {
  readonly maximo: number;
  readonly origem: OrigemDoLimite;
  readonly fundamento: string;
}

/** Uma linha de `platform.waitlist_entry`, na forma em que o módulo a lê. */
export interface Entrada {
  readonly onboardingId: string;
  readonly estado: EstadoDaEntrada;
  /** O `fase_at` do caso quando entrou: a chave FIFO. Ver o dicionário. */
  readonly aprovadoEm: Date;
  /** A chave da ordem: o `aprovadoEm`, ou o instante em que voltou ao fim. */
  readonly naFilaDesde: Date;
  readonly convidadoEm: Date | null;
  readonly conviteExpiraEm: Date | null;
  /** Convites expirados ou recusados até agora. */
  readonly tentativas: number;
  readonly concluidoEm: Date | null;
  readonly criadoEm: Date;
}

/** Os campos que uma transição pode escrever. */
export type Campos = Partial<
  Pick<Entrada, "naFilaDesde" | "convidadoEm" | "conviteExpiraEm" | "tentativas" | "concluidoEm">
> & {
  /** O SHA-256 do convite, em hexadecimais; `null` apaga-o. */
  readonly conviteHash?: string | null;
};

/**
 * As operações dentro de uma transacção da lista.
 *
 * **Todas correm com a fila trancada para escrita**: é o que faz «20 a pedir 1
 * vaga ⇒ 1 convite» ser verdade. Ver o `SQL_TRANCAR` em `./sql.ts` para a
 * razão por que não é o `SKIP LOCKED` dos Detalhes Técnicos.
 */
export interface OperacoesDaLista {
  limite(): Promise<Limite>;
  entrada(onboardingId: string): Promise<Entrada | null>;
  /**
   * Põe o caso na fila, em `aguardando`. Devolve `null` se o caso não existe
   * ou não está numa das `FASES_ELEGIVEIS` — e então **não escreve nada**. O
   * `aprovadoEm` não vem de quem chama: lê-se do caso.
   */
  inserir(onboardingId: string): Promise<Entrada | null>;
  /** Vagas ocupadas: concluídos desde `desde` mais convites vivos em `agora`. */
  ocupadas(desde: Date, agora: Date): Promise<number>;
  /** O caso ainda está numa das `FASES_ELEGIVEIS`? */
  elegivel(onboardingId: string): Promise<boolean>;
  /** Quantos estão `aguardando` à frente deste caso. */
  aFrente(onboardingId: string): Promise<number>;
  /** O primeiro `aguardando`, ou `null`. */
  cabeca(): Promise<Entrada | null>;
  /** Escreve se o estado for `de`. *Compare-and-set*: `false` se não era. */
  transitar(onboardingId: string, de: EstadoDaEntrada, para: EstadoDaEntrada, campos: Campos): Promise<boolean>;
  porConvite(conviteHash: string): Promise<Entrada | null>;
  /** Os convites vivos cujo prazo passou em `agora`. */
  vencidos(agora: Date): Promise<readonly string[]>;
  /** Passa o caso a `abandonado` (critério 5; a compensação é do KAM-091). */
  abandonarCaso(onboardingId: string): Promise<void>;
}

/** O que as métricas e a estimativa lêem, sem trancar a fila. */
export interface Fotografia {
  readonly porEstado: Readonly<Record<EstadoDaEntrada, number>>;
  /** Os `concluidoEm` dentro da janela, por ordem. */
  readonly concluidosNaJanela: readonly Date[];
  /**
   * Média da espera dos concluídos na janela, em segundos; `null` sem nenhum.
   * A espera conta da **última** entrada na fila — o maior de `criadoEm` e
   * `naFilaDesde` —, para que uma reentrada não arraste a primeira.
   */
  readonly esperaMediaSegundos: number | null;
  readonly limite: Limite;
}

/** Onde a fila vive. */
export interface RepositorioDaLista {
  emTransaccao<T>(fazer: (operacoes: OperacoesDaLista) => Promise<T>): Promise<T>;
  fotografia(desde: Date): Promise<Fotografia>;
}

/**
 * O aviso do convite ao dono, **por SMS ou e-mail** — nunca pelo número da
 * loja, que ainda não existe. A ligação leva o convite em claro; a base só
 * guarda o *hash* (DoD 4).
 */
export interface AvisoDaLista {
  convidar(onboardingId: string, ligacao: string, expiraEm: Date): Promise<void>;
  /**
   * **O aviso chega ao dono?** (KAM-254, decisão da coordenação do lote 22 de
   * 2026-11-24, A.) `false` numa porta **sem via**, que regista e não manda: o
   * convite fica vivo, mas o dono só o vê se voltar à página, e por isso um
   * convite destes que vence **não gasta tentativa** (decisão do fundador de
   * 2026-11-24, A). Omisso vale `true`.
   *
   * **O limite**, aceite com a decisão: a marca é do processo e não do convite.
   * Um convite emitido sem via que vença depois de o *deploy* da via (KAM-116)
   * entrar conta como entregue — a janela é a validade do convite, 48 h depois
   * desse *deploy*.
   */
  readonly entrega?: boolean;
}

/** Porque é que a lista recusa um pedido. */
export const MOTIVOS_DE_RECUSA = ["nao_elegivel", "kyc_caducado", "fora_da_lista", "convite_invalido"] as const;

export type MotivoDeRecusa = (typeof MOTIVOS_DE_RECUSA)[number];

/**
 * Levantada quando a lista recusa. O `convite_invalido` não distingue forjado,
 * expirado, usado ou de outro caso: distinguir era dizer a quem tenta se
 * acertou num convite alheio (critério de isolamento).
 */
export class ListaRecusadaError extends Error {
  override readonly name = "ListaRecusadaError";
  readonly motivo: MotivoDeRecusa;

  constructor(motivo: MotivoDeRecusa) {
    super(`a lista de espera recusa: ${motivo}`);
    this.motivo = motivo;
  }
}

/** A posição que o dono vê (critério 6). */
export type Posicao =
  | {
      readonly estado: "aguardando";
      /** 1 é a cabeça. Calculada, nunca guardada. */
      readonly posicao: number;
      readonly estimativa: Estimativa;
    }
  | { readonly estado: "convidado"; readonly expiraEm: Date }
  | { readonly estado: "concluido" | "expirado" | "desistiu" };

/**
 * A estimativa de espera: um **intervalo rotulado**, nunca uma promessa nem um
 * prazo da Meta. Calcula-se da nossa própria janela (quando saem os concluídos
 * dela) e do limite em vigor; não sabe nada da «Access Verification».
 */
export interface Estimativa {
  readonly rotulo: "estimativa";
  readonly minimoDias: number;
  readonly maximoDias: number;
}

/**
 * Fila de revisão por excepção para T&S/T2 — o contrato (KAM-089).
 *
 * A equipa só toca um onboarding por excepção, e este módulo é o **único**
 * sítio onde um humano decide (`../docs/tecnica/10` §4.1). Cada caso chega com
 * motivo, evidências **por referência** e recomendação automática; decide-se
 * em ≤ 1 dia útil de Luanda; a decisão fica num registo *append-only*
 * atribuível a uma pessoa.
 *
 * ## As duas ameaças do bloco, e onde cada uma se trava
 *
 * 1. **Inundar a fila.** Um caso só entra se o onboarding passou o OTP (e por
 *    isso o desafio anti-bot do registo, que vem antes): `FASES_ELEGIVEIS`. O
 *    lixo — OTP falhado, documento ilegível, duplicado exacto — resolve-se a
 *    montante sem chamar a fila (KAM-086, KAM-087). E há uma quota por origem
 *    e por dia de Luanda: o excesso fica `em_triagem_automatica`, fora da vista
 *    humana, com alerta.
 * 2. **A fila como canal de fuga.** Nenhuma operação devolve um documento:
 *    devolve uma URL assinada de ≤ 300 s, e o acesso fica no `audit_log`
 *    **antes** de a URL existir. O NIF e o BI saem mascarados; revelar é uma
 *    operação à parte, também registada. A listagem tem página máxima e não
 *    tem dados pessoais nenhuns, e não há operação de exportação.
 *
 * ## Quem decide, e o que não pode decidir
 *
 * Só quem tem papel `ts_revisor` ou `ts_lider` **e** MFA verificada. Um caso
 * `escalado` só o `ts_lider` o decide. Ninguém decide um caso em que é parte.
 * Aprovar um caso de risco alto pede **dois** revisores distintos. O recurso é
 * **um** por decisão e decide-o quem não decidiu a primeira instância. Uma
 * recusa por qualquer destas regras fica no `audit_log` (`review.recusa`).
 *
 * ## Todos os limiares são propostas
 *
 * A quota por origem, o limiar de risco alto, os 20% e as 8 semanas da
 * amostragem, os 80% do alerta, o tamanho da página: `LIMIARES_POR_OMISSAO`,
 * configuráveis. Nenhum foi calibrado.
 */

/** Os tipos de caso. Lista **fechada**, a do critério 1. Domínio de `review_case.tipo`. */
export const TIPOS_DE_CASO = [
  "kyc",
  "categoria",
  "duplicado",
  "es_falhado",
  "saga",
  "catalogo",
  "recurso",
  "trust",
  "auditoria",
] as const;
export type TipoDeCaso = (typeof TIPOS_DE_CASO)[number];

/**
 * Os estados. A máquina do bloco, mais o `em_triagem_automatica` do ensaio
 * adversarial (b): o caso existe, mas está fora da vista humana até a quota da
 * sua origem o deixar entrar.
 *
 * ```text
 * em_triagem_automatica → aberto → em_analise → decidido | escalado
 *                          aberto → escalado | decidido
 *                                   escalado  → decidido
 *                                   decidido  → recurso_aberto → decidido_final
 * ```
 *
 * Uma decisão que não fecha o caso — o `pedir_info`, a primeira de duas
 * aprovações — passa um caso `aberto` a `em_analise` e deixa os outros onde
 * estão.
 *
 * Domínio de `review_case.estado`; as transições são impostas também na base,
 * por *trigger*.
 */
export const ESTADOS = [
  "em_triagem_automatica",
  "aberto",
  "em_analise",
  "escalado",
  "decidido",
  "recurso_aberto",
  "decidido_final",
] as const;
export type EstadoDoCaso = (typeof ESTADOS)[number];

/** As transições permitidas. A mesma tabela que o *trigger* da `0048` impõe. */
export const TRANSICOES: Readonly<Record<EstadoDoCaso, readonly EstadoDoCaso[]>> = {
  em_triagem_automatica: ["aberto"],
  aberto: ["em_analise", "escalado", "decidido"],
  em_analise: ["escalado", "decidido"],
  escalado: ["decidido"],
  decidido: ["recurso_aberto"],
  recurso_aberto: ["decidido_final"],
  decidido_final: [],
};

/** Os estados em que o caso espera por um humano. É sobre eles que corre o SLA. */
export const ESTADOS_PENDENTES: readonly EstadoDoCaso[] = ["aberto", "em_analise", "escalado", "recurso_aberto"];

/** As decisões, à letra do critério 3. Domínio de `review_decision_log.decisao`. */
export const DECISOES = ["aprovar", "rejeitar", "pedir_info", "escalar"] as const;
export type Decisao = (typeof DECISOES)[number];

/** A instância de uma decisão. Domínio de `review_decision_log.instancia`. */
export const INSTANCIAS = ["primeira", "recurso"] as const;
export type Instancia = (typeof INSTANCIAS)[number];

/**
 * A recomendação automática. Domínio de `review_case.recomendacao`.
 *
 * `investigar` não é uma decisão: é o que o KYC recomenda quando o sinal é de
 * fraude e não de documento (ver `../kyc/regras.ts`). O `pedir_documentos` do
 * KYC entra aqui como `pedir_info`.
 */
export const RECOMENDACOES = ["aprovar", "rejeitar", "pedir_info", "investigar"] as const;
export type Recomendacao = (typeof RECOMENDACOES)[number];

/** Os papéis de quem revê. Não são papéis de base de dados: vêm da identidade da equipa. */
export const PAPEIS = ["ts_revisor", "ts_lider"] as const;
export type Papel = (typeof PAPEIS)[number];

/**
 * O motivo que o dono lê. Lista **fechada** de códigos com texto fixo: quem
 * revê não escreve texto livre para o dono, e é assim que o ensaio
 * adversarial (d) fica verdadeiro por construção — não há onde a heurística
 * entre. Domínio de `review_case.motivo_publico`.
 */
export const MOTIVOS_PUBLICOS = [
  "nao_foi_possivel_validar",
  "documento_expirado",
  "categoria_nao_permitida",
  "informacao_em_falta",
] as const;
export type MotivoPublico = (typeof MOTIVOS_PUBLICOS)[number];

export const TEXTO_DO_MOTIVO_PUBLICO: Readonly<Record<MotivoPublico, string>> = {
  nao_foi_possivel_validar: "Nao foi possivel validar o pedido. Pode recorrer uma vez desta decisao.",
  documento_expirado: "Um dos documentos esta fora da validade. Envie o documento em vigor.",
  categoria_nao_permitida: "A categoria declarada nao pode ser vendida na plataforma.",
  informacao_em_falta: "Precisamos de mais informacao para analisar o pedido.",
};

/**
 * A primeira frase de cada texto: a **causa**, sem o passo seguinte (KAM-196).
 *
 * O aviso de um recurso decidido não pode repetir o texto inteiro: o do
 * `nao_foi_possivel_validar` diz «Pode recorrer uma vez desta decisao», e depois
 * do recurso já não pode. Cada causa é o começo exacto do seu texto, e um ensaio
 * mede-o: se alguém mudar um texto sem mudar a causa, os dois deixam de dizer o
 * mesmo motivo e o ensaio fica vermelho.
 */
export const CAUSA_DO_MOTIVO_PUBLICO: Readonly<Record<MotivoPublico, string>> = {
  nao_foi_possivel_validar: "Nao foi possivel validar o pedido.",
  documento_expirado: "Um dos documentos esta fora da validade.",
  categoria_nao_permitida: "A categoria declarada nao pode ser vendida na plataforma.",
  informacao_em_falta: "Precisamos de mais informacao para analisar o pedido.",
};

/** Uma evidência é uma **referência**, nunca uma cópia (critério 1). */
export interface Evidencia {
  /** O nome da tabela de onde vem, sem esquema: `kyc_check`, `screening_decision`, … */
  readonly tipo: string;
  readonly ref: string;
}

/** Um `review_case`, como o negócio o lê. Ver o DDL na revisão `0048`. */
export interface CasoDeRevisao {
  readonly id: string;
  readonly tipo: TipoDeCaso;
  readonly onboardingId: string | null;
  readonly tenantId: string;
  readonly motivoCodigo: string;
  /** Só para T&S. Nunca sai para o dono. */
  readonly motivoInterno: string;
  readonly motivoPublico: MotivoPublico;
  readonly evidencias: readonly Evidencia[];
  readonly recomendacao: Recomendacao | null;
  readonly estado: EstadoDoCaso;
  /** 1 é a mais urgente, 9 a menos. */
  readonly prioridade: number;
  /** Quando o caso entrou na vista humana: a criação, ou a saída da triagem. */
  readonly filaEm: Date;
  readonly slaDueAt: Date;
  readonly slaAlertaAt: Date;
  readonly slaAlertadoEm: Date | null;
  readonly criadoEm: Date;
}

export type CasoNovo = Omit<CasoDeRevisao, "id" | "criadoEm" | "slaAlertadoEm">;

/** Uma linha do `review_decision_log`. */
export interface DecisaoRegistada {
  readonly id: string;
  readonly casoId: string;
  readonly revisorId: string;
  readonly decisao: Decisao;
  readonly instancia: Instancia;
  /** O código da regra ou do motivo da decisão. */
  readonly regra: string | null;
  readonly notaCifrada: Uint8Array | null;
  readonly em: Date;
}

export type DecisaoNova = Omit<DecisaoRegistada, "id" | "em">;

/**
 * Onde os casos vivem.
 *
 * O adaptador SQL corre como `kamba_batch`: a fila atravessa tenants por
 * natureza — o revisor vê casos de todos —, e é o papel com `BYPASSRLS`, que é
 * auditado. O `kamba_app` não tem privilégio nenhum nestas tabelas.
 */
export interface RepositorioDeRevisao {
  /**
   * Cria o caso, ou devolve o que a chave `(tipo, tenant_id, onboarding_id,
   * motivo_codigo)` já criou (critério 9). `repetido` diz qual.
   */
  abrir(novo: CasoNovo): Promise<{ readonly caso: CasoDeRevisao; readonly repetido: boolean }>;
  porId(id: string): Promise<CasoDeRevisao | null>;
  /**
   * Muda o estado se o actual for `de`. `false` se não era: duas decisões
   * concorrentes sobre o mesmo caso não passam as duas. Com `sla`, reinicia o
   * prazo e o alerta; com `sla.filaEm`, também a entrada na fila (a saída da
   * triagem). O recurso reinicia o prazo e **não** a entrada: a primeira decisão
   * mede-se a partir da entrada, e um recurso não a apaga.
   */
  transitar(id: string, de: EstadoDoCaso, para: EstadoDoCaso, sla?: Sla & { readonly filaEm?: Date }): Promise<boolean>;
  /**
   * Um envio repetido sobre um caso **pendente** traz o que a porta sabe agora:
   * o motivo interno e a recomendação novos, as evidências somadas, e a
   * prioridade mais urgente das duas — **nunca** menos urgente, e a base impõe-no
   * por *trigger*. `false` se o caso já não está pendente.
   */
  reforcar(id: string, r: { readonly prioridade: number; readonly motivoInterno: string; readonly evidencias: readonly Evidencia[]; readonly recomendacao: Recomendacao | null }): Promise<boolean>;
  registarDecisao(nova: DecisaoNova): Promise<DecisaoRegistada>;
  decisoes(casoId: string): Promise<readonly DecisaoRegistada[]>;
  /** Todos os casos de um onboarding, pendentes e decididos (para saber se ainda o bloqueiam). */
  casosDoOnboarding(onboardingId: string): Promise<readonly CasoDeRevisao[]>;
  /**
   * Quantos casos desta origem entraram hoje na vista humana. A origem é o
   * `ip_prefix_hash` do onboarding, ou o `device_hash` na falta dele.
   */
  contarNaFilaDesde(origem: string | null, desde: Date): Promise<number>;
  /**
   * Quantos casos **sem onboarding** deste tenant entraram hoje na vista humana,
   * fora as auditorias. Uma `condicional` de produto chega sem onboarding e o
   * conteúdo é do tenant: sem esta quota, um tenant inundava a fila pelo catálogo.
   */
  contarNaFilaDoTenantDesde(tenantId: string, desde: Date): Promise<number>;
  /** Os casos em triagem, do mais antigo para o mais recente. */
  emTriagem(limite: number): Promise<readonly CasoDeRevisao[]>;
  /** Os pendentes cujo alerta dos 80% já passou e ainda não foi dado. */
  alertasDevidos(agora: Date): Promise<readonly CasoDeRevisao[]>;
  marcarAlertado(id: string, em: Date): Promise<void>;
  /** Uma página da vista humana, por prioridade e prazo. */
  pagina(filtro: FiltroDaFila, limite: number, depoisDe: number): Promise<readonly CasoDeRevisao[]>;
  /**
   * Corre `trabalho` com a chave da quota trancada **entre processos** (KAM-198).
   * O `trabalho` recebe o repositório a usar dentro do trinco — a contagem e a
   * escrita têm de ir pela mesma transacção que o segura, senão o trinco solta-se
   * antes de a escrita a ver.
   *
   * Opcional: o duplo em memória vive num processo só, e aí o `#emSerie` do
   * serviço chega. O adaptador SQL implementa-o com um `pg_advisory_xact_lock`.
   */
  emTrinco?<T>(chave: string, trabalho: (repositorio: RepositorioDeRevisao) => Promise<T>): Promise<T>;
}

/**
 * Os casos com um efeito da decisão por aplicar (KAM-196, KAM-198).
 *
 * A decisão e os efeitos não são uma transacção: o caso fecha primeiro, e a
 * fase, o screening e o aviso vêm depois e podem falhar. O serviço **marca** o
 * caso antes de correr os efeitos e **resolve-o** quando correm todos; o ciclo
 * do processo de lote reaplica os marcados. Sobre a base (`EfeitosPorReaplicarSql`)
 * a marca é a coluna `review_case.efeito_pendente_at` da revisão `0052`, e
 * sobrevive a um reinício e a um processo que morra entre a decisão e os efeitos.
 */
export interface EfeitosPorReaplicar {
  marcar(casoId: string): Promise<void>;
  pendentes(limite: number): Promise<readonly string[]>;
  resolver(casoId: string): Promise<void>;
}

export interface FiltroDaFila {
  readonly tipo?: TipoDeCaso;
  readonly estado?: EstadoDoCaso;
}

/** O prazo e o instante do alerta de um caso. */
export interface Sla {
  readonly slaDueAt: Date;
  readonly slaAlertaAt: Date;
}

/** O que a fila lê de um onboarding. Um subconjunto do `Caso` da `../inscricao/`. */
export interface OnboardingDaRevisao {
  readonly id: string;
  readonly tenantId: string;
  readonly fase: string;
  /** HMAC do prefixo de IP (`ip_prefix_hash`), ou `null`. */
  readonly redeHmac: string | null;
  /** HMAC do dispositivo (`device_hash`), ou `null`. */
  readonly dispositivoHmac: string | null;
  readonly nifHmac: string;
  readonly telefoneHmac: string;
}

/** A porta dos onboardings. Implementada pelo `RepositorioDeCasos` da inscrição. */
export interface OnboardingsDaRevisao {
  porId(id: string): Promise<OnboardingDaRevisao | null>;
  /**
   * O onboarding de um tenant, pelo `tenant_id` pré-alocado (único por caso).
   * É o que diz quem é parte num caso sem onboarding — uma auditoria, um
   * produto do catálogo — e de onde vêm os dados dele.
   */
  porTenant(tenantId: string): Promise<OnboardingDaRevisao | null>;
  marcarFase(id: string, fase: "aprovado" | "rejeitado" | "kyc_pendente"): Promise<boolean>;
}

/**
 * Quem revê, como a identidade da equipa o entrega.
 *
 * **Não há identidade de equipa neste repositório** (nem tabela, nem IdP): a
 * porta é o contrato que a consola vai cumprir. A MFA chega como facto
 * verificado pela identidade — esta fila não a verifica, recusa quem chega sem
 * ela.
 */
export interface Revisor {
  /** UUID do revisor na identidade da equipa. Vai para `review_decision_log.revisor_id`. */
  readonly id: string;
  readonly papeis: readonly string[];
  readonly mfa: boolean;
  /**
   * HMAC do NIF e do telefone do revisor, com a mesma chave da inscrição, para
   * a regra «não decide casos em que é parte». `null` quando não se sabe.
   */
  readonly nifHmac: string | null;
  readonly telefoneHmac: string | null;
}

/** As acções que a fila escreve no `audit_log`. Acrescentadas ao domínio pela `0048`. */
export const ACCOES_DE_AUDITORIA = ["review.acesso", "review.recusa"] as const;
export type AccaoDeAuditoria = (typeof ACCOES_DE_AUDITORIA)[number];

/** Uma linha do `audit_log` (KAM-012), escrita por `platform.audit_append`. */
export interface RegistoDeAuditoria {
  readonly accao: AccaoDeAuditoria;
  /** `null` para o que não é de um tenant: uma lista recusada vai à cadeia de plataforma. */
  readonly tenantId: string | null;
  /** O `revisor.id`, ou `desconhecido` para quem chegou sem identidade. */
  readonly actorId: string;
  /** O que foi tocado: `kyc_check`, `onboarding_case`, `review_case`. */
  readonly entidade: string;
  readonly entidadeId: string;
  /** O que se deixa provar sem o guardar em claro: o motivo da recusa, o campo revelado. */
  readonly detalhe: string;
}

export interface Auditoria {
  gravar(r: RegistoDeAuditoria): Promise<void>;
}

/**
 * A URL de um documento de KYC. Implementada pelo `ServicoKyc.urlParaRevisao`,
 * que anota o acesso **antes** de pedir a URL ao STO e prende o TTL a ≤ 300 s.
 */
export interface DocumentosDaRevisao {
  url(
    revisor: string,
    onboardingId: string,
    verificacaoId: string,
    auditoria: {
      anotarAcesso(acesso: {
        readonly revisor: string;
        readonly onboardingId: string;
        readonly verificacaoId: string;
        readonly em: Date;
      }): Promise<void>;
    },
  ): Promise<string>;
}

/** Os dados pessoais que a consola pode mostrar, em claro, para os mascarar ou revelar. */
export const CAMPOS_PESSOAIS = ["nif", "numero_bi", "telefone"] as const;
export type CampoPessoal = (typeof CAMPOS_PESSOAIS)[number];

export interface DadosPessoais {
  /** O valor em claro, ou `null` se não existe. Quem decifra é o adaptador. */
  ler(onboardingId: string, campo: CampoPessoal): Promise<string | null>;
}

/**
 * O aviso ao dono. **Nunca pelo número da loja** (critério 8): a via é o SMS
 * ao telefone registado ou o e-mail, e o tipo não tem valor para WhatsApp.
 */
export const VIAS_DO_AVISO = ["sms", "email"] as const;
export type ViaDoAviso = (typeof VIAS_DO_AVISO)[number];

export const AVISOS = ["aprovado", "rejeitado", "pedir_info", "recurso_decidido"] as const;
export type Aviso = (typeof AVISOS)[number];

export interface AvisoAoDono {
  avisar(pedido: {
    readonly onboardingId: string;
    readonly via: ViaDoAviso;
    readonly aviso: Aviso;
    readonly motivoPublico: MotivoPublico | null;
  }): Promise<void>;
}

/**
 * A decisão humana de screening, que o KAM-088 deixou com credor neste ticket:
 * aprovar um caso `categoria` ou `catalogo` grava uma linha `origem = 'humano'`
 * `permitida`, e rejeitar grava `bloqueada`. É essa linha que o
 * `assertPublishable` lê.
 */
export interface DecisaoHumanaDeScreening {
  gravar(pedido: {
    readonly tenantId: string;
    readonly onboardingId: string | null;
    readonly chave: ChaveDeScreening;
    readonly decisao: "permitida" | "bloqueada";
    readonly revisorId: string;
  }): Promise<void>;
}

/** A chave de uma decisão de screening, guardada como evidência do caso. */
export interface ChaveDeScreening {
  readonly sujeitoTipo: "categoria" | "produto";
  readonly sujeitoRef: string;
  readonly versaoPolitica: string;
  /** Hexadecimal. */
  readonly conteudoSha256: string;
}

/** Alerta operacional. Nunca leva dados pessoais. */
export const MOTIVOS_DE_ALERTA = ["sla_80", "quota_da_origem"] as const;
export type MotivoDeAlerta = (typeof MOTIVOS_DE_ALERTA)[number];
export type Alerta = (motivo: MotivoDeAlerta, campos: { readonly casoId: string; readonly tipo: TipoDeCaso }) => void;

/** Cifra da nota do revisor (`nota_enc`). A mesma forma da do KYC. */
export interface Cifra {
  cifrar(claro: Uint8Array, contexto: string): Promise<Uint8Array>;
  decifrar(cifrado: Uint8Array, contexto: string): Promise<Uint8Array>;
}

export type Relogio = () => Date;

/** Os limiares. Todos *proposta*. */
export interface Limiares {
  /** Dias úteis de Luanda até ao prazo da primeira decisão. */
  readonly diasUteisDoSla: number;
  /** A fracção do prazo em que se alerta. */
  readonly fracaoDoAlerta: number;
  /** Casos por origem e por dia de Luanda que entram na vista humana. */
  readonly quotaPorOrigemPorDia: number;
  /** Prioridade igual ou abaixo desta é risco alto: aprovar pede dois revisores. */
  readonly prioridadeDeRiscoAlto: number;
  /** Fracção das aprovações automáticas que gera caso `auditoria`. */
  readonly fracaoDaAmostra: number;
  /** Semanas, desde o início da amostragem, em que ela corre. */
  readonly semanasDeAmostragem: number;
  /** Casos por página da consola. Não há exportação. */
  readonly paginaMaxima: number;
}

export const LIMIARES_POR_OMISSAO: Limiares = {
  diasUteisDoSla: 1,
  fracaoDoAlerta: 0.8,
  quotaPorOrigemPorDia: 20,
  prioridadeDeRiscoAlto: 2,
  fracaoDaAmostra: 0.2,
  semanasDeAmostragem: 8,
  paginaMaxima: 50,
};

/** As prioridades que esta fila atribui. 1 é a mais urgente. */
export const PRIORIDADES = { regraDura: 1, scoreAlto: 2, normal: 5, auditoria: 9 } as const;

/** Recusa de uma operação. O `motivo` é código fechado e vai para o `audit_log`. */
export const MOTIVOS_DE_RECUSA = [
  "sem_papel",
  "sem_mfa",
  "so_lider",
  "parte_no_caso",
  "mesmo_revisor",
  "revisor_da_primeira_instancia",
  "estado_invalido",
  "recurso_ja_usado",
  "recurso_sem_rejeicao",
  "decisao_invalida",
  "evidencia_alheia",
] as const;
export type MotivoDeRecusa = (typeof MOTIVOS_DE_RECUSA)[number];

export class RevisaoRecusadaError extends Error {
  override readonly name = "RevisaoRecusadaError";
  readonly motivo: MotivoDeRecusa;
  /** O estado HTTP que a consola devolve. */
  readonly estadoHttp: 403 | 409;

  constructor(motivo: MotivoDeRecusa) {
    super(`revisao recusada: ${motivo}`);
    this.motivo = motivo;
    this.estadoHttp =
      motivo === "estado_invalido" || motivo === "recurso_ja_usado" || motivo === "recurso_sem_rejeicao" ? 409 : 403;
  }
}

/**
 * A decisão ficou registada e um efeito dela falhou depois (KAM-196): a fase do
 * onboarding, o screening ou o aviso ao dono. O caso está onde a decisão o pôs;
 * o efeito é que fica por aplicar, e o `reaplicarEfeitos` volta a corrê-lo. A
 * mensagem não leva a do erro de origem, que pode trazer o que não deve sair.
 */
export class EfeitoPorAplicarError extends Error {
  override readonly name = "EfeitoPorAplicarError";
  readonly casoId: string;

  constructor(casoId: string, causa: unknown) {
    super("efeito de uma decisao de revisao por aplicar", { cause: causa });
    this.casoId = casoId;
  }
}

export class CasoInexistenteError extends Error {
  override readonly name = "CasoInexistenteError";
  constructor() {
    super("caso de revisao inexistente");
  }
}

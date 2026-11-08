/**
 * O vocabulário da inscrição e as portas que ela precisa (KAM-086).
 *
 * Nenhuma lógica aqui, e nenhum efeito: constantes, tipos e portas. É a forma
 * do `../onboarding/contrato.ts` e do `../provisioning/contrato.ts`, e a razão é
 * a mesma — um domínio escrito ao lado de quem o consome divergia do da base no
 * primeiro dia em que alguém mudasse um dos dois.
 *
 * ## Isto é a inscrição, e **não** é o `onboarding/` de canal
 *
 * Há dois «onboarding» neste repositório, e confundi-los custa um módulo
 * inteiro:
 *
 *     ../onboarding/    o Embedded Signup v4 da Meta (KAM-016) — ligar o número
 *                       de WhatsApp de um tenant **que já existe**
 *     ./ (inscricao/)   o registo self-service (KAM-086) — o dono entra em
 *                       `/entrar`, prova a posse do telefone por OTP, e sai com
 *                       um `onboarding_case` pronto para o KYC. **Ainda não há
 *                       tenant**: o `tenant_id` é pré-alocado
 *
 * O nome do módulo é `inscricao` por isso, e não por gosto.
 *
 * ## A tabela não existe, e isto é a fronteira que a vai receber
 *
 * O bloco do KAM-086 traz o DDL de `platform.onboarding_case`. **Esta entrega
 * não escreve a migração**, e não é omissão: a vaga de revisão de base de dados
 * deste lote é do KAM-070, e a `onboarding_case.fase` do dicionário §3.2 tem
 * **seis** valores onde o bloco escreve **catorze** — a emenda 1.64 do
 * dicionário já nomeia o KAM-086/087 como credor dessa divergência. Escrever a
 * tabela era decidir essa emenda de passagem.
 *
 * O que está entregue é o **`RepositorioDeCasos`**, e o precedente é do ticket
 * ao lado: o KAM-091 fundiu os três domínios fechados da saga «que viviam só no
 * contrato em TypeScript», e a revisão `0034` veio depois. O adaptador SQL
 * preenche esta porta; o `./memoria.ts` é o duplo que CI e `dev` usam.
 *
 * **A cifra de aplicação (`nif_enc`, `phone_enc`, `email_enc`) é do
 * adaptador**, e a porta foi desenhada para isso: o `CasoNovo` leva os valores
 * **opacos** (`./identificadores.ts`) e o `Caso` só leva HMAC. Quem guarda
 * decide como cifra; quem decide o negócio nunca vê o número por acidente.
 *
 * ## Uma porta de contagem, e não quatro
 *
 * Os limites deste ticket — casos por prefixo de IP, casos por dispositivo em
 * 24 h, envios de OTP por hora e por telefone, o intervalo de 60 s entre
 * envios, e o orçamento diário de SMS — são todos a **mesma** pergunta: quantas
 * ocorrências desta chave há nesta janela. Quatro portas para a mesma pergunta
 * davam quatro implementações e quatro maneiras de a errar.
 */

import type { CodigoOtp } from "../sms/codigo.ts";

import type { Email, Nif, Telefone } from "./identificadores.ts";

/**
 * As fases de um caso.
 *
 * **Catorze, como o bloco do KAM-086 escreve**, e não as seis do dicionário
 * §3.2 — a diferença está medida e tem credor escrito na emenda 1.64: faltam lá
 * o `aguarda_teste` e o `abandonado`, que o critério 6 do KAM-091 nomeia.
 * Entregar seis era implementar uma máquina de estados que o próprio bloco
 * contradiz; entregar catorze e dizê-lo é o que deixa a emenda decidível.
 *
 * Deste ticket só se alcançam as **duas primeiras** (`registo` e
 * `otp_pendente`) e a terceira por conclusão do OTP (`kyc_pendente`). As outras
 * onze são do KAM-087 em diante, e estão aqui porque a lista é o domínio da
 * coluna e não o alcance deste ticket.
 */
export const FASES = [
  "registo",
  "otp_pendente",
  "kyc_pendente",
  "em_revisao",
  "aprovado",
  "provisionando",
  "aguarda_es",
  "lista_espera",
  "aguarda_catalogo",
  "aguarda_teste",
  "activo",
  "rejeitado",
  "abandonado",
  "cancelado",
] as const;

export type Fase = (typeof FASES)[number];

/**
 * As fases em que um caso **não** conta como vivo.
 *
 * É o predicado do índice único do bloco («`WHERE estado NOT IN
 * ('rejeitado','abandonado','cancelado')`»), e vive aqui e não no adaptador por
 * uma razão medida noutro ticket desta casa: uma restrição que existe só no SQL
 * é uma restrição que o duplo em memória não tem, e então os ensaios de
 * duplicado passam contra o duplo e falham contra a base. A unicidade é
 * **domínio**, e o adaptador reafirma-a com o índice.
 */
export const FASES_MORTAS: readonly Fase[] = ["rejeitado", "abandonado", "cancelado"];

/** Um caso vivo é o que o índice único de `nif_hmac` cobre. */
export function faseViva(fase: Fase): boolean {
  return !FASES_MORTAS.includes(fase);
}

/** De onde veio o convite. Lista fechada do critério 1. */
export const ORIGENS = ["convite", "contabilista", "anuncio"] as const;

export type Origem = (typeof ORIGENS)[number];

/**
 * As marcas que mandam um caso à fila de revisão (KAM-089).
 *
 * Uma só, e é a do critério 8. A lista é fechada para que uma marca nova seja
 * uma alteração visível num diff e não uma cadeia inventada no sítio de uso —
 * que é como `flags text[]` se transforma num campo de texto livre.
 */
export const FLAGS = ["duplicado_ambiguo"] as const;

export type Flag = (typeof FLAGS)[number];

/**
 * Um caso, na forma em que o negócio o lê.
 *
 * **Não leva o NIF nem o telefone**, nem cifrados: leva os HMAC. Quem precisa
 * do número para enviar um SMS recebe-o de quem o acabou de normalizar, dentro
 * da mesma chamada; quem lê um caso da base nunca precisa dele. É a mesma
 * escolha que põe o `hmac` ao lado do número no `../sms/destino.ts`, levada ao
 * agregado.
 */
export interface Caso {
  /** O `onboarding_id`. UUID canónico. */
  readonly id: string;
  /** O `tenant_id` **pré-alocado**. Ver a nota do módulo. */
  readonly tenantId: string;
  readonly fase: Fase;
  readonly origem: Origem;
  readonly nomeNegocio: string;
  readonly categoriaDeclarada: string;
  /** HMAC do NIF, em hexadecimais. */
  readonly nifHmac: string;
  /** HMAC do telefone, em hexadecimais. */
  readonly telefoneHmac: string;
  /** HMAC grosseiro do dispositivo, ou `null`. */
  readonly dispositivoHmac: string | null;
  /** HMAC do prefixo de IP, ou `null`. */
  readonly redeHmac: string | null;
  readonly flags: readonly Flag[];
  /** O `owner_active_seconds` do critério 10. */
  readonly activoSegundos: number;
  readonly criadoEm: Date;
}

/**
 * O que se entrega ao repositório para criar um caso.
 *
 * Os identificadores vêm **opacos** e é o adaptador que decide como os cifra —
 * ver a nota do módulo. O `tenantId` vem de fora e não é gerado aqui: quem o
 * aloca é o caso de uso, que é também quem sabe que ele é pré-alocado.
 */
export interface CasoNovo {
  readonly tenantId: string;
  readonly origem: Origem;
  readonly nomeNegocio: string;
  readonly categoriaDeclarada: string;
  readonly nif: Nif;
  readonly telefone: Telefone;
  readonly email: Email | null;
  readonly dispositivoHmac: string | null;
  readonly redeHmac: string | null;
  readonly flags: readonly Flag[];
}

/**
 * Onde os casos vivem.
 *
 * O adaptador SQL corre cada consulta sob `app.onboarding_id` com RLS `FORCE`
 * (critério de isolamento do DoD), e isso **não se consegue afirmar daqui**: o
 * duplo em memória não tem RLS. O que esta porta garante é que nenhuma consulta
 * deste módulo procura por outra coisa que não o `onboarding_id` ou um HMAC —
 * o que é a metade do isolamento que um contrato pode impor.
 */
export interface RepositorioDeCasos {
  porId(id: string): Promise<Caso | null>;
  /**
   * O telefone registado de um caso, em claro, ou `null` se não se consegue ler.
   *
   * **É a única operação desta porta que devolve um dado pessoal**, e existe por
   * um critério e não por conveniência: o critério 8 manda que um NIF repetido
   * recupere a sessão «por OTP ao telefone **registado**» — ao registado, e não
   * ao submetido. Sem esta operação, a recuperação mandava o código para o
   * telefone de quem submeteu o formulário, que é precisamente o ataque que ela
   * existe para travar.
   *
   * É o adaptador que decifra o `phone_enc`, e devolver `null` em vez de lançar
   * é deliberado: uma DEK errada ou uma rotação a meio é uma avaria nossa, e o
   * `./registo.ts` traduz o `null` num 503 em vez de num «dados inválidos».
   */
  telefoneDe(id: string): Promise<Telefone | null>;
  /**
   * O caso que uma chave de idempotência já criou, ou `null`.
   *
   * É o critério 2, e vive no repositório e não no caso de uso de propósito: a
   * atomicidade entre «guardar a chave» e «criar a linha» é do adaptador, e um
   * caso de uso que a tentasse em duas chamadas tinha uma corrida.
   */
  porChave(chave: string): Promise<Caso | null>;
  /** O caso **vivo** com este `nif_hmac`, ou `null`. Ver `FASES_MORTAS`. */
  porNifHmac(hmac: string): Promise<Caso | null>;
  /** Os casos **vivos** com este `phone_hmac`. */
  porTelefoneHmac(hmac: string): Promise<readonly Caso[]>;
  /** Quantos casos este dispositivo abriu desde `desde`. Critério 8. */
  contarPorDispositivo(hmac: string, desde: Date): Promise<number>;
  /**
   * Cria o caso e prende-lhe a chave de idempotência, **de uma vez**.
   *
   * Devolve o caso criado, ou o que a chave já tinha criado — e nesse caso
   * `repetido` é `true`. A forma é a do `ResultadoDeEnvio` do
   * `../sms/contrato.ts`, e pela mesma razão: quem chama precisa de saber se
   * houve efeito, e um `boolean` ao lado do valor é mais difícil de ignorar do
   * que uma comparação de `id`.
   */
  criar(novo: CasoNovo, chave: string): Promise<{ readonly caso: Caso; readonly repetido: boolean }>;
  /** Muda a fase. `false` se o caso não existe. */
  marcarFase(id: string, fase: Fase): Promise<boolean>;
  /** Acrescenta a marca, se ainda não estiver. `false` se o caso não existe. */
  acrescentarFlag(id: string, flag: Flag): Promise<boolean>;
  /** Soma segundos ao `owner_active_seconds` e devolve o total. Critério 10. */
  acumularActivo(id: string, segundos: number): Promise<number>;
}

/** Um desafio de OTP, como ele fica guardado. */
export interface DesafioGuardado {
  readonly onboardingId: string;
  /** HMAC do código. **Nunca o código.** Critério 5. */
  readonly codigoHmac: string;
  readonly expiraEm: Date;
  readonly tentativas: number;
}

/**
 * Onde o estado do OTP vive.
 *
 * Separado do `RepositorioDeCasos` porque tem outro tempo de vida: um desafio
 * vale cinco minutos e apaga-se, um caso fica. Juntá-los dava uma tabela com
 * duas retenções.
 */
export interface RepositorioDeOtp {
  /** Guarda o desafio, substituindo o que lá estiver para este caso. */
  guardar(desafio: DesafioGuardado): Promise<void>;
  /** O desafio deste caso, expirado ou não. Quem decide a validade é o `./otp.ts`. */
  actual(onboardingId: string): Promise<DesafioGuardado | null>;
  /** Soma uma tentativa e devolve o total. `null` se não há desafio. */
  somarTentativa(onboardingId: string): Promise<number | null>;
  /** Apaga o desafio. Chamado no acerto e no esgotamento das tentativas. */
  apagar(onboardingId: string): Promise<void>;
}

/**
 * Uma janela deslizante de ocorrências por chave. Ver a nota do módulo.
 *
 * A `janelaMs` vem de **quem pergunta** e não da implementação, porque a mesma
 * chave pode ser perguntada em duas janelas (os três envios por hora e o
 * intervalo de 60 s são o mesmo telefone), e uma janela fixada na implementação
 * obrigava a duas instâncias.
 */
export interface Contadores {
  /**
   * Anota uma ocorrência e devolve quantas há na janela, **incluindo esta**.
   *
   * Chama-se `anotar` e não `registar`, e o nome não é escolha de estilo: o
   * `tools/log_policy` do KAM-068 recusa qualquer `.registar(...)` em código de
   * serviço, porque é a **porta sem tipos** do *logger* — a que aceita campos
   * fora da *allowlist*. A primeira versão deste módulo chamava-lhe `registar`
   * e deu oito achados do *gate* 2 em cinco ficheiros. O nome do método é do
   * *lint*, e ele tem razão: um `.registar(` num diff tem de querer dizer uma
   * coisa só.
   */
  anotar(chave: string, em: Date, janelaMs: number): Promise<number>;
  /** Quantas há na janela, **sem** registar. */
  contar(chave: string, em: Date, janelaMs: number): Promise<number>;
  /** O instante da ocorrência mais recente desta chave, ou `null`. */
  ultimo(chave: string): Promise<Date | null>;
}

/**
 * Os canais por onde um OTP pode sair.
 *
 * O `whatsapp` está aqui e está **desligado**: é o que os *Módulos* do bloco
 * mandam («`sms_local` activo; `whatsapp` **desactivado** até D10»). Não está
 * aqui como intenção — está aqui porque uma lista fechada com um valor recusado
 * é verificável, e uma lista que o omitisse deixava o dia da D10 a quem
 * reinventasse o nome.
 */
export const CANAIS_DE_OTP = ["sms_local", "whatsapp"] as const;

export type CanalDeOtp = (typeof CANAIS_DE_OTP)[number];

/** Quais canais estão activos no Piloto. O `whatsapp` espera a D10 e o KAM-101. */
export const CANAIS_ACTIVOS: Readonly<Record<CanalDeOtp, boolean>> = {
  sms_local: true,
  whatsapp: false,
};

/**
 * Por onde o código sai.
 *
 * Recebe o `Telefone` **opaco** e não uma cadeia: o único sítio deste módulo
 * onde o número volta a texto é dentro de uma implementação desta porta, para
 * o entregar ao transporte. Ver `./sms_local.ts`.
 */
export interface OtpProvider {
  readonly canal: CanalDeOtp;
  /**
   * Entrega o código, uma vez por `chave`.
   *
   * @throws {CanalDesactivadoError} se o canal não estiver em `CANAIS_ACTIVOS`
   */
  enviar(telefone: Telefone, codigo: CodigoOtp, validadeMin: number, chave: string): Promise<void>;
}

/** Levantado quando se tenta enviar por um canal que a D10 ainda veda. */
export class CanalDesactivadoError extends Error {
  override readonly name = "CanalDesactivadoError";
  readonly canal: CanalDeOtp;

  constructor(canal: CanalDeOtp) {
    super(`o canal de OTP ${canal} esta desactivado no Piloto (D10, KAM-101)`);
    this.canal = canal;
  }
}

/**
 * Para onde vai um alerta operacional deste módulo.
 *
 * É uma porta e **não uma métrica nova**, e isso é uma limitação dita e não um
 * desenho preferido: o critério 6 pede «há alerta» ao esgotar o orçamento de
 * SMS, e a regra deste lote dá a vaga de métrica nova ao KAM-060. O serviço
 * liga esta porta ao `../logger/`, cujo `outcome` é campo da *allowlist*; a
 * **série Prometheus e a regra de alerta do orçamento ficam com credor
 * nomeado** (KAM-080/KAM-060).
 */
export type Alerta = (motivo: MotivoDeAlerta, campos: { readonly tenantId?: string }) => void;

/** Os motivos de alerta deste módulo. Lista fechada, forma de `outcome`. */
export const MOTIVOS_DE_ALERTA = ["orcamento_de_sms_esgotado", "disjuntor_de_sms_reaberto"] as const;

export type MotivoDeAlerta = (typeof MOTIVOS_DE_ALERTA)[number];

/** Relógio injectável, como nos outros módulos desta casa. */
export type Relogio = () => Date;

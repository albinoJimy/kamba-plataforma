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
 * ## A tabela existe; o adaptador que a escreve, não
 *
 * O bloco do KAM-086 traz o DDL de `platform.onboarding_case`, e esta entrega
 * não escreveu a migração: a `onboarding_case.fase` do dicionário §3.2 divergia
 * do bloco em **nove valores e num nome**, e escrever a tabela era decidir a
 * emenda de passagem. **A tabela nasceu com o KAM-087** (revisão `0043`, emenda
 * 1.78 do dicionário, §3.55), com a coluna `fase` e os catorze valores de
 * `FASES`. O que continua por fazer é o adaptador SQL desta porta — a cifra do
 * NIF e do telefone e a tradução do `23505` do índice do NIF —, com credor
 * KAM-086.
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
 * §3.2. A divergência está **contada** e tem credor na emenda 1.64, e a
 * primeira versão desta nota contava-a mal — dizia «faltam lá o `aguarda_teste`
 * e o `abandonado`», e falta mais do que isso. Medido contra o §3.2:
 *
 *     5 partilhados   kyc_pendente, aprovado, provisionando, aguarda_es,
 *                     aguarda_catalogo
 *     9 só aqui       registo, otp_pendente, em_revisao, lista_espera,
 *                     aguarda_teste, activo, rejeitado, abandonado, cancelado
 *     1 só no canon   `pronto`, que aqui é o `activo`
 *
 * O último é o que mais importa, porque não é uma ausência: é um valor
 * **renomeado**, e a emenda tem de decidir qual dos dois nomes fica. Entregar
 * seis era implementar uma máquina de estados que o próprio bloco contradiz;
 * entregar catorze e contar a divergência é o que deixa a emenda decidível.
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

/**
 * Levantado quando já existe um caso **vivo** com este `nif_hmac`.
 *
 * Vive no contrato e não na implementação, e isso não é arrumação: o adaptador
 * SQL recebe o `23505` do índice único do bloco e **tem** de o traduzir para
 * esta classe, senão o `./registo.ts` deixa de reconhecer a corrida de dois
 * pedidos com o mesmo NIF novo — e a resposta a essa corrida é recuperar, não
 * um 500. É a obrigação do adaptador escrita no sítio onde ele a lê.
 */
export class CasoDuplicadoError extends Error {
  override readonly name = "CasoDuplicadoError";

  constructor() {
    // Sem o `nif_hmac` na mensagem: um HMAC não é o NIF, mas é um pseudónimo
    // estável dele, e uma mensagem de erro acaba em ficheiro de log.
    super("ja existe um caso vivo com este nif_hmac");
  }
}

/**
 * Levantado quando uma chave de idempotência volta com **outro** corpo.
 *
 * **Era o defeito mais grave da primeira versão do `./memoria.ts`.** O `criar`
 * devolvia o caso que a chave já tinha criado **sem olhar para o `novo`**, e a
 * página submete sempre a mesma chave por carregamento: um dono que corrigisse o
 * NIF e voltasse a submeter recebia o caso antigo, com o NIF **errado**
 * guardado — e o `./registo.ts` mandava-lhe o OTP para o telefone **novo**, pelo
 * que a posse provada era de um número que o caso não tinha. Achado da revisão
 * adversarial.
 *
 * A idempotência de HTTP é «a mesma chave com o mesmo pedido»; com outro pedido
 * é um conflito e não uma repetição. A mensagem não leva nenhum dos dois HMAC.
 */
export class ChaveReutilizadaError extends Error {
  override readonly name = "ChaveReutilizadaError";

  constructor() {
    super("a chave de idempotencia ja criou um caso com outro nif_hmac");
  }
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
  /**
   * Troca o último instante desta chave por `em`, **atomicamente**, e devolve o
   * que lá estava.
   *
   * Existe porque `ultimo` seguido de `anotar` **não é atómico**, e a diferença
   * era um defeito medido: o `./actividade.ts` lia o instante anterior, cedia o
   * turno no `await`, e N batidas concorrentes liam **todas** o mesmo instante
   * anterior e somavam **todas** o mesmo intervalo. Mil batidas no mesmo
   * segundo somavam oito horas, e o cabeçalho daquele ficheiro afirmava
   * exactamente o contrário. Achado da revisão adversarial.
   *
   * Num adaptador SQL isto é um `INSERT … ON CONFLICT … DO UPDATE … RETURNING`
   * do valor antigo, ou um `UPDATE … WHERE ultimo = $anterior`; a atomicidade é
   * **obrigação do adaptador** e esta assinatura é onde ela fica escrita.
   */
  trocarUltimo(chave: string, em: Date): Promise<Date | null>;
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
 * o entregar ao transporte. Ver `./provedores.ts`.
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

/**
 * Os motivos de alerta deste módulo. Lista fechada, forma de `outcome`.
 *
 * **Um só, e a lista tinha dois.** O segundo era um `disjuntor_de_sms_reaberto`
 * que **nenhuma linha emitia** — uma reabertura não é um evento neste desenho:
 * a janela do orçamento desliza, e não há instante em que alguém a observe a
 * fechar-se. Um valor declarado sem emissor é canon a mentir sobre o código ao
 * lado, e foi um achado da revisão adversarial. Quem quiser ver o estado do
 * disjuntor chama o `disjuntorAberto()` do `./otp.ts`, que é uma sonda e não um
 * alerta.
 */
export const MOTIVOS_DE_ALERTA = ["orcamento_de_sms_esgotado"] as const;

export type MotivoDeAlerta = (typeof MOTIVOS_DE_ALERTA)[number];

/** Relógio injectável, como nos outros módulos desta casa. */
export type Relogio = () => Date;

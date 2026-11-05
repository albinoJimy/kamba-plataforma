/**
 * O agregador como subprocessador, e o *gate* de `prod` (KAM-116, critério 8).
 *
 * «O agregador consta do inventário de subprocessadores (KAM-069) com país,
 * finalidade (OTP e avisos), dados (telefone) e `apd_ref`; sem estado
 * `autorizado` não há envio real em `prod`. Em CI e `staging` usa-se o *fake* ou
 * números autorizados.»
 *
 * ## Este ficheiro não escolhe o agregador, e é esse o ponto
 *
 * **Não há agregador escolhido.** A escolha é do fundador — ele é a única
 * autoridade para contratar fornecedores e autorizar subprocessadores — e as
 * cotações escritas que o critério 1 pede não existem. Escolher um aqui era
 * escolher um subprocessador num ficheiro de código, que é exactamente o que o
 * ADR-008 existe para impedir.
 *
 * O valor por omissão é `pendente`, e `pendente` em `prod` é um arranque
 * recusado. É a mesma forma, e pela mesma razão, do `../avisos/fornecedor.ts`
 * do KAM-115 — e os campos têm os nomes de `tenant_destinations(provider,
 * country, apd_ref)` do `../../../../docs/tecnica/08` §8.3.1, porque é essa a
 * tabela que o KAM-069 vai confrontar com isto. Um segundo vocabulário para a
 * mesma ideia dava duas tabelas a reconciliar no dia em que o inventário
 * existisse.
 *
 * ## O `estado` é o campo que o KAM-115 não tinha, e o critério 8 nomeia-o
 *
 * O aviso ao dono bloqueava `prod` por falta de `apd_ref`. Aqui há mais um
 * degrau: o critério fala de **estado `autorizado`**, que é o que o inventário
 * do KAM-069 vai guardar depois de a APD responder. Um `apd_ref` preenchido diz
 * «há procedimento»; o `autorizado` diz «correu e permite». São coisas
 * diferentes, e um procedimento em curso não é uma autorização — por isso
 * exigem-se os dois em `prod`.
 *
 * ## O que é um dado pessoal aqui
 *
 * O **telefone do dono da PME** — uma pessoa singular — sai da nossa
 * infra-estrutura para o agregador, que o guarda nos registos de entrega dele, e
 * que o entrega à operadora. É transferência de dado pessoal no sentido do
 * ADR-008. Se o agregador tratar o número **fora de Angola**, o enquadramento
 * legal disso é **NÃO VERIFICADO** e é do **KAM-104** (a confirmar por parecer);
 * este ficheiro não o decide, mede-o: um país que não `AO` sem autorização
 * recusa `prod`.
 *
 * O que **não** sai está noutro sítio: o `modelos.ts` garante que o corpo não
 * leva nome, loja nem texto de ninguém, e o `destino.ts` garante que o número
 * não entra em registo nenhum em claro.
 */

/** Subconjunto de `process.env` de que este módulo depende. */
export type ProcessEnv = Record<string, string | undefined>;

/** Nomes das variáveis de ambiente. Nenhuma delas é um segredo. */
export const VARIAVEIS = {
  ambiente: "KAMBA_AMBIENTE",
  provider: "KAMBA_SMS_PROVIDER",
  country: "KAMBA_SMS_COUNTRY",
  apdRef: "KAMBA_SMS_APD_REF",
  estado: "KAMBA_SMS_SUBPROCESSADOR_ESTADO",
} as const;

/** O país em que o telefone do dono pode ficar sem `apd_ref` (ADR-008). */
export const PAIS_SEM_TRANSFERENCIA = "AO";

/** O ambiente em que a falta de autorização deixa de ser aviso e passa a recusa. */
export const AMBIENTE_BLOQUEANTE = "prod";

/**
 * O valor por omissão do fornecedor: **`pendente`**.
 *
 * Não é um nome de agregador — é a ausência de escolha, dita por extenso.
 */
export const FORNECEDOR_PENDENTE = "pendente";

/** Estados do registo no inventário de subprocessadores (KAM-069). */
export const ESTADOS_DO_SUBPROCESSADOR = ["pendente", "autorizado"] as const;

export type EstadoDoSubprocessador = (typeof ESTADOS_DO_SUBPROCESSADOR)[number];

/**
 * A finalidade, fixa.
 *
 * O critério nomeia-a — «finalidade (OTP e avisos)» — e ela não é configurável
 * de propósito: uma finalidade que vem do ambiente é uma finalidade que se
 * alarga sem passar por ninguém, e o alargamento que importa aqui é o
 * marketing, que o Art. 19.º da Lei 22/11 toca (`E3` §1, a confirmar por
 * parecer). A lista de modelos do `modelos.ts` é a outra metade da mesma
 * barreira.
 */
export const FINALIDADE = "otp_e_avisos_de_servico";

/** Os dados que saem, fixos pela mesma razão que a finalidade. */
export const DADOS = "telefone";

/** Para onde vai o telefone do dono. Os nomes são de `tenant_destinations`. */
export interface Subprocessador {
  /** ISO 3166-1 alfa-2, em maiúsculas: `AO`, `ZA`, `PT`. */
  readonly country: string;
  /** Identificador do agregador, em minúsculas, ou `pendente`. */
  readonly provider: string;
  /** Referência do procedimento na APD; `null` se não há. */
  readonly apdRef: string | null;
  /** Estado no inventário do KAM-069. */
  readonly estado: EstadoDoSubprocessador;
  /** Fixos: ver `FINALIDADE` e `DADOS`. */
  readonly finalidade: string;
  readonly dados: string;
}

/**
 * Em `prod` sem autorização para enviar.
 *
 * Levanta, e quem arranca o serviço não tem como continuar sem o resolver. É a
 * mesma forma do `FornecedorSemApdRefError` do KAM-115 e do
 * `DestinoSemApdRefError` do KAM-011.
 */
export class AgregadorNaoAutorizadoError extends Error {
  override readonly name = "AgregadorNaoAutorizadoError";
  readonly country: string;
  readonly provider: string;
  readonly estado: EstadoDoSubprocessador;

  constructor(country: string, provider: string, estado: EstadoDoSubprocessador, falta: string) {
    super(
      `envio real de SMS em ${AMBIENTE_BLOQUEANTE} com o agregador ${provider} ` +
        `em ${country}, estado ${estado}: ${falta}. O telefone do dono e um dado ` +
        "pessoal e nao sai de Angola sem referencia da APD (ADR-008), e sem " +
        "estado autorizado no inventario de subprocessadores (KAM-069) nao ha " +
        "envio real; o servico nao arranca",
    );
    this.country = country;
    this.provider = provider;
    this.estado = estado;
  }
}

/** A declaração não serve. A mensagem nomeia as variáveis, nunca os valores. */
export class DeclaracaoInvalidaError extends Error {
  override readonly name = "DeclaracaoInvalidaError";
  readonly problemas: readonly string[];

  constructor(problemas: readonly string[]) {
    super(`declaracao do agregador de SMS invalida: ${problemas.join("; ")}`);
    this.problemas = problemas;
  }
}

const PAIS = /^[A-Z]{2}$/;
const FORNECEDOR = /^[a-z][a-z0-9_-]{1,62}$/;
const APD_REF = /^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$/;

/**
 * O que se tira das pontas de um valor: espaço, tabulação e mudanças de linha.
 *
 * Escrito à mão e não com `trim()`, pela razão que o `../storage/config.ts`
 * mediu: o `trim()` do JavaScript e o `strip()` do Python não tiram os mesmos
 * caracteres, e uma declaração que passa de um lado e falha do outro é pior do
 * que uma que falha nos dois.
 */
function limpar(valor: string | undefined): string {
  return (valor ?? "").replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
}

/** O que a leitura da declaração produziu. */
export interface Declaracao {
  readonly subprocessador: Subprocessador;
  /** `true` se um envio **real** é permitido neste ambiente. */
  readonly envioRealPermitido: boolean;
  /**
   * Avisos que **não** impedem o arranque.
   *
   * Fora de `prod`, um agregador por escolher ou sem autorização aparece aqui —
   * quem arranca o serviço decide onde os escrever; este módulo não registra
   * nada, pela mesma razão do `../storage/config.ts`.
   */
  readonly avisos: readonly string[];
}

/**
 * Lê a declaração do agregador e aplica o *gate* de `prod`.
 *
 * Chama-se **no arranque** do serviço e não a cada envio: um arranque que recusa
 * é visível, e uma recusa no primeiro OTP de um dono real era descobrir o
 * problema no pior momento possível — a meio do passo 2 do onboarding.
 *
 * O `country` por omissão é `AO`, o `provider` é `pendente` e o `estado` é
 * `pendente`. A omissão é «ainda não escolhemos», e ela bloqueia `prod` sempre
 * que haja transferência ou falte autorização.
 */
export function agregadorDeSms(env: ProcessEnv = process.env): Declaracao {
  const problemas: string[] = [];
  const country = (limpar(env[VARIAVEIS.country]) || PAIS_SEM_TRANSFERENCIA).toUpperCase();
  const provider = limpar(env[VARIAVEIS.provider]).toLowerCase() || FORNECEDOR_PENDENTE;
  const apdBruto = limpar(env[VARIAVEIS.apdRef]);
  const estadoBruto = limpar(env[VARIAVEIS.estado]).toLowerCase() || "pendente";

  if (!PAIS.test(country)) {
    problemas.push(`${VARIAVEIS.country} nao e um codigo ISO 3166-1 alfa-2`);
  }
  if (!FORNECEDOR.test(provider)) {
    problemas.push(`${VARIAVEIS.provider} nao e um identificador`);
  }
  if (apdBruto !== "" && !APD_REF.test(apdBruto)) {
    problemas.push(`${VARIAVEIS.apdRef} nao e uma referencia`);
  }
  if (!(ESTADOS_DO_SUBPROCESSADOR as readonly string[]).includes(estadoBruto)) {
    problemas.push(
      `${VARIAVEIS.estado} tem de ser ${ESTADOS_DO_SUBPROCESSADOR.join(" ou ")}`,
    );
  }
  if (problemas.length > 0) throw new DeclaracaoInvalidaError(problemas);

  const apdRef = apdBruto === "" ? null : apdBruto;
  const estado = estadoBruto as EstadoDoSubprocessador;
  const subprocessador: Subprocessador = {
    country,
    provider,
    apdRef,
    estado,
    finalidade: FINALIDADE,
    dados: DADOS,
  };

  // Duas faltas distintas, e as duas bloqueiam. A primeira e a do ADR-008: o
  // telefone sai de Angola sem referencia da APD. A segunda e a do criterio 8:
  // nao ha estado `autorizado` no inventario de subprocessadores. Um agregador
  // escolhido, em Angola e autorizado nao tem nenhuma das duas.
  const faltas: string[] = [];
  const transfere = country !== PAIS_SEM_TRANSFERENCIA;
  if (transfere && apdRef === null) faltas.push(`falta ${VARIAVEIS.apdRef}`);
  if (estado !== "autorizado") faltas.push(`${VARIAVEIS.estado} nao e autorizado`);
  if (provider === FORNECEDOR_PENDENTE) faltas.push(`${VARIAVEIS.provider} nao esta escolhido`);

  const emProd = limpar(env[VARIAVEIS.ambiente]).toLowerCase() === AMBIENTE_BLOQUEANTE;
  const avisos: string[] = [];
  if (faltas.length > 0) {
    if (emProd) {
      throw new AgregadorNaoAutorizadoError(country, provider, estado, faltas.join(", "));
    }
    avisos.push(
      `agregador de SMS ${provider} em ${country}: ${faltas.join(", ")}; fora de ` +
        `${AMBIENTE_BLOQUEANTE} e aviso e usa-se o FakeSmsProvider, em ` +
        `${AMBIENTE_BLOQUEANTE} o servico nao arranca (ADR-008, KAM-069)`,
    );
  }

  return { subprocessador, envioRealPermitido: faltas.length === 0, avisos };
}

/**
 * Levanta se a declaração não permite envio real.
 *
 * É o que um **adaptador do agregador** chama no construtor: o
 * `FakeSmsProvider` não chama, porque é ele que CI e `staging` usam. Com isto, a
 * barreira do critério 8 está nos dois sítios que importam — no arranque do
 * serviço (`agregadorDeSms`) e na construção do adaptador — e nenhum adaptador
 * futuro tem de se lembrar dela: sem esta chamada, um adaptador novo é um
 * achado de revisão com um sítio só para procurar.
 */
export function exigirEnvioReal(declaracao: Declaracao): void {
  if (declaracao.envioRealPermitido) return;
  const { country, provider, estado } = declaracao.subprocessador;
  throw new AgregadorNaoAutorizadoError(
    country,
    provider,
    estado,
    declaracao.avisos[0] ?? "declaracao incompleta",
  );
}

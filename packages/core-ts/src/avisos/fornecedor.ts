/**
 * O fornecedor de e-mail como subprocessador, e o *gate* de `prod` (KAM-115,
 * critério 8).
 *
 * «O fornecedor de e-mail consta do inventário de subprocessadores (KAM-069)
 * com `apd_ref`, ou fica `pendente` e **bloqueia `prod`** (ADR-008).»
 *
 * O inventário de subprocessadores **não existe** — nasce com o KAM-069 —, e
 * inventá-lo aqui era construir por outro ticket. O que o critério deixa como
 * alternativa é o que se entrega: a declaração vive no ambiente, e em `prod`,
 * com o fornecedor fora de Angola e sem `apd_ref`, **o serviço não arranca**.
 *
 * ## É a forma do `../storage/config.ts`, e de propósito
 *
 * Os três campos têm os nomes de `tenant_destinations(provider, country,
 * apd_ref)` do `../../../../docs/tecnica/08` §8.3.1, porque é essa a tabela que
 * o KAM-069 vai confrontar com isto. Um segundo vocabulário para a mesma ideia
 * dava duas tabelas a reconciliar no dia em que o inventário existisse.
 *
 * E o comportamento é o mesmo: **fora de `prod`, avisa; em `prod`, levanta.**
 * Um ambiente de desenvolvimento tem de poder correr contra um fornecedor falso
 * sem papelada, e um ambiente de produção não.
 *
 * ## O que é um dado pessoal aqui, e porque é que isto não é cerimónia
 *
 * O aviso leva o **endereço de e-mail do dono** — uma pessoa singular — para
 * fora da nossa infra-estrutura, para um fornecedor que o guarda em registos de
 * entrega. É transferência de dado pessoal no sentido do ADR-008, e é por isso
 * que o critério a trata como trata o armazenamento de mídia: nenhum dado
 * pessoal sai de Angola sem referência da APD.
 *
 * O que o aviso **não** leva está noutro sítio: o critério 5 e a lista branca do
 * `modelos.ts` garantem que não vai nome, telefone nem texto de cliente nenhum.
 * O que vai é o endereço do dono e o nome da loja.
 *
 * ## O que este ficheiro não decide
 *
 * Qual é o fornecedor. Não há escolha feita, e fazê-la aqui era escolher um
 * subprocessador num ficheiro de código — que é exactamente o que o ADR-008
 * existe para impedir. O valor por omissão é `pendente`, e `pendente` em `prod`
 * é um arranque recusado.
 */

/** Subconjunto de `process.env` de que este módulo depende. */
export type ProcessEnv = Record<string, string | undefined>;

/** Nomes das variáveis de ambiente. Nenhuma delas é um segredo. */
export const VARIAVEIS = {
  ambiente: "KAMBA_AMBIENTE",
  provider: "KAMBA_AVISO_EMAIL_PROVIDER",
  country: "KAMBA_AVISO_EMAIL_COUNTRY",
  apdRef: "KAMBA_AVISO_EMAIL_APD_REF",
} as const;

/** O país em que o endereço do dono pode ficar sem `apd_ref` (ADR-008). */
export const PAIS_SEM_TRANSFERENCIA = "AO";

/** O ambiente em que a falta de `apd_ref` deixa de ser aviso e passa a recusa. */
export const AMBIENTE_BLOQUEANTE = "prod";

/**
 * O valor por omissão do fornecedor: **`pendente`**.
 *
 * Não é um nome de fornecedor — é a ausência de escolha, dita por extenso. O
 * critério 8 nomeia este estado («ou fica `pendente` e bloqueia `prod`»), e é
 * ele que faz o *gate* ter conteúdo em vez de ser uma verificação que ninguém
 * dispara.
 */
export const FORNECEDOR_PENDENTE = "pendente";

/** Para onde vai o endereço do dono. */
export interface Subprocessador {
  /** ISO 3166-1 alfa-2, em maiúsculas: `AO`, `ZA`, `IE`. */
  readonly country: string;
  /** Identificador do fornecedor, em minúsculas, ou `pendente`. */
  readonly provider: string;
  /** Referência do procedimento na APD; `null` se não há. */
  readonly apdRef: string | null;
}

/**
 * Em `prod`, o fornecedor está fora de Angola — ou não está escolhido — e não há
 * `apd_ref`.
 *
 * Levanta, e quem arranca o serviço não tem como continuar sem o resolver. É a
 * segunda metade do critério 8, e é a mesma forma do `DestinoSemApdRefError` do
 * KAM-011.
 */
export class FornecedorSemApdRefError extends Error {
  override readonly name = "FornecedorSemApdRefError";
  readonly country: string;
  readonly provider: string;

  constructor(country: string, provider: string) {
    super(
      `aviso ao dono em ${AMBIENTE_BLOQUEANTE} com fornecedor de e-mail ` +
        `${provider} em ${country} e sem ${VARIAVEIS.apdRef}: o endereço do dono ` +
        "e um dado pessoal e nao sai de Angola sem referencia da APD (ADR-008); " +
        "o servico nao arranca",
    );
    this.country = country;
    this.provider = provider;
  }
}

/** A declaração não serve. A mensagem nomeia as variáveis, nunca os valores. */
export class DeclaracaoInvalidaError extends Error {
  override readonly name = "DeclaracaoInvalidaError";
  readonly problemas: readonly string[];

  constructor(problemas: readonly string[]) {
    super(`declaracao do fornecedor de e-mail invalida: ${problemas.join("; ")}`);
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
  /**
   * Avisos que **não** impedem o arranque.
   *
   * Fora de `prod`, um fornecedor fora de Angola sem `apd_ref` aparece aqui —
   * quem arranca o serviço decide onde os escrever; este módulo não registra
   * nada, pela mesma razão do `storage/config.ts`.
   */
  readonly avisos: readonly string[];
}

/**
 * Lê a declaração do fornecedor e aplica o *gate* de `prod`.
 *
 * Chama-se **no arranque** do serviço e não a cada aviso: um arranque que
 * recusa é visível, e uma recusa no primeiro aviso de uma avaria era descobrir o
 * problema no pior momento possível.
 *
 * O `country` por omissão é `AO` e o `provider` é `pendente`: a omissão é «ainda
 * não escolhemos», e ela só bloqueia `prod` quando há mesmo transferência — um
 * fornecedor em Angola, se existir, não precisa de `apd_ref`.
 */
export function fornecedorDeEmail(env: ProcessEnv = process.env): Declaracao {
  const problemas: string[] = [];
  const country = (limpar(env[VARIAVEIS.country]) || PAIS_SEM_TRANSFERENCIA).toUpperCase();
  const provider = limpar(env[VARIAVEIS.provider]).toLowerCase() || FORNECEDOR_PENDENTE;
  const apdBruto = limpar(env[VARIAVEIS.apdRef]);

  if (!PAIS.test(country)) {
    problemas.push(`${VARIAVEIS.country} nao e um codigo ISO 3166-1 alfa-2`);
  }
  if (!FORNECEDOR.test(provider)) {
    problemas.push(`${VARIAVEIS.provider} nao e um identificador`);
  }
  if (apdBruto !== "" && !APD_REF.test(apdBruto)) {
    problemas.push(`${VARIAVEIS.apdRef} nao e uma referencia`);
  }
  if (problemas.length > 0) throw new DeclaracaoInvalidaError(problemas);

  const apdRef = apdBruto === "" ? null : apdBruto;
  const subprocessador: Subprocessador = { country, provider, apdRef };
  const transfere = country !== PAIS_SEM_TRANSFERENCIA || provider === FORNECEDOR_PENDENTE;
  const avisos: string[] = [];

  if (transfere && apdRef === null) {
    if (limpar(env[VARIAVEIS.ambiente]).toLowerCase() === AMBIENTE_BLOQUEANTE) {
      throw new FornecedorSemApdRefError(country, provider);
    }
    avisos.push(
      `fornecedor de e-mail ${provider} em ${country} sem ${VARIAVEIS.apdRef}: ` +
        `fora de ${AMBIENTE_BLOQUEANTE} e aviso, em ${AMBIENTE_BLOQUEANTE} o ` +
        "servico nao arranca (ADR-008, KAM-069)",
    );
  }
  return { subprocessador, avisos };
}

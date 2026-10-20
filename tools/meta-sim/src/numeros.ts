/**
 * Os números fictícios do simulador, e a recusa de gravar um real (KAM-024).
 *
 * O critério 7 pede uma ferramenta de captura que «recusa gravar se detectar um
 * número que não pertença à lista de números fictícios», e que o repositório
 * fique com **0 telefones reais**. Este ficheiro é as duas metades: o intervalo
 * reservado de onde os números saem, e os padrões que reconhecem um número real.
 *
 * ## O intervalo é o `999`, e não é uma escolha deste ticket
 *
 * `999` é um indicativo de país que a **UIT não atribui a nenhum país**, e é a
 * convenção que o repositório já usa: `telefoneDeEnsaio()` em
 * `packages/core-ts/tests_bd/apoio.ts` e o `TELEFONE` de
 * `db/tests_entrada/test_entrada.py`. Herdá-la é o contrário de inventar uma
 * quarta.
 *
 * ## O ficheiro `fake_numbers.yaml` e esta constante dizem o mesmo
 *
 * O critério 7 nomeia `tools/meta-sim/fake_numbers.yaml`. O ficheiro existe e é
 * o que uma pessoa lê; **esta constante é o que o código usa**, e há um teste
 * que compara os dois como texto. A alternativa — ler YAML em TypeScript —
 * obrigava a um quarto leitor de YAML neste repositório (há três em Python, e a
 * `docs/dividas-documentais.md` já registou o que isso custou). Um teste de
 * paridade custa dez linhas e não acrescenta leitor nenhum.
 */

/** O indicativo reservado. A UIT não o atribui a nenhum país. */
export const INDICATIVO_FICTICIO = "999";

/** Quantos algarismos vêm depois do indicativo. */
export const ALGARISMOS = 9;

/** O primeiro e o último número do intervalo, em E.164 sem `+`. */
export const INTERVALO = {
  primeiro: `${INDICATIVO_FICTICIO}100000000`,
  ultimo: `${INDICATIVO_FICTICIO}999999999`,
} as const;

/**
 * Os padrões que reconhecem um telefone **real** num texto.
 *
 * São os dois de `tools/contract_diff/pii.py` e de
 * `packages/core-ts/src/eventos/pii.ts`, que são também os do guarda de
 * `platform.evt_emitir` — a mesma pergunta feita em três sítios, e aqui num
 * quarto. Não se reescrevem com outra forma de propósito: um padrão que
 * divergisse apanhava um conjunto diferente, e o que se quer é que as quatro
 * superfícies recusem exactamente o mesmo.
 *
 * `TELEFONE_AO` é o número angolano (`+244 9xxxxxxxx`, com ou sem `+` e com ou
 * sem espaço); `E164_ENTRE_ASPAS` é qualquer E.164 entre aspas, que é a forma
 * em que um telefone aparece num JSON.
 */
export const PADROES_DE_TELEFONE_REAL: readonly { readonly nome: string; readonly padrao: RegExp }[] = [
  { nome: "telefone_ao", padrao: /\+?244 ?9[0-9]{8}/g },
  { nome: "e164_entre_aspas", padrao: /"\+[0-9]{9,15}"/g },
];

/** Um número fictício é do intervalo reservado, e mais nada o é. */
export function eFicticio(numero: string): boolean {
  return new RegExp(`^${INDICATIVO_FICTICIO}[0-9]{${ALGARISMOS}}$`).test(numero);
}

/** Uma ocorrência de telefone real encontrada num texto. */
export interface Ocorrencia {
  readonly padrao: string;
  readonly valor: string;
  /** Índice do primeiro caractere, para quem quiser apontar a linha. */
  readonly indice: number;
}

/**
 * Todas as ocorrências de telefone real num texto.
 *
 * **Um número do intervalo fictício não é ocorrência**, e isso não é
 * generosidade: o `999123456789` casa o segundo padrão quando escrito com `+`,
 * e sem esta excepção a ferramenta recusava gravar as suas próprias *fixtures*.
 */
export function telefonesReais(texto: string): readonly Ocorrencia[] {
  const achados: Ocorrencia[] = [];
  for (const { nome, padrao } of PADROES_DE_TELEFONE_REAL) {
    // `lastIndex` é estado do `RegExp` com `g`: uma cópia por varrimento, para
    // que duas chamadas seguidas não comecem onde a anterior parou.
    const seu = new RegExp(padrao.source, padrao.flags);
    for (;;) {
      const achado = seu.exec(texto);
      if (achado === null) break;
      const valor = achado[0];
      const semEnfeite = valor.replace(/[^0-9]/g, "");
      if (eFicticio(semEnfeite)) continue;
      achados.push({ padrao: nome, valor, indice: achado.index });
    }
  }
  return achados;
}

/** A ferramenta de captura recusou gravar: há um número que não é fictício. */
export class NumeroRealError extends Error {
  readonly ocorrencias: readonly Ocorrencia[];

  constructor(ocorrencias: readonly Ocorrencia[]) {
    // **A mensagem não leva o número.** Um erro vai para o registo e para o
    // relatório do CI, que ficam no histórico das execuções; imprimir o número
    // que se acabou de encontrar punha o dado pessoal exactamente onde o
    // critério 7 o quer tirar. O que a mensagem leva é quantos, de que padrão e
    // em que índice — que é o que quem corrige precisa para abrir o ficheiro.
    super(
      `recusado: ${ocorrencias.length} telefone(s) que nao pertencem ao ` +
        `intervalo ficticio (${INTERVALO.primeiro}-${INTERVALO.ultimo}). ` +
        `Primeiro no indice ${ocorrencias[0]?.indice ?? -1} (padrao ` +
        `${ocorrencias[0]?.padrao ?? "?"}). Uma fixture com um numero real e um ` +
        "dado pessoal no repositorio, para sempre, no historico do git.",
    );
    this.name = "NumeroRealError";
    this.ocorrencias = ocorrencias;
  }
}

/** Lança se o texto tiver um telefone que não seja do intervalo fictício. */
export function exigirFicticios(texto: string): void {
  const achados = telefonesReais(texto);
  if (achados.length > 0) throw new NumeroRealError(achados);
}

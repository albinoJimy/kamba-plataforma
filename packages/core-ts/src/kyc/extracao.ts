/**
 * Extracção de campos e a validação que os torna utilizáveis (KAM-087,
 * critérios 2, 3 e 8).
 *
 * ## Duas metades, e só a segunda decide
 *
 * O `OcrLocal` lê linhas de um `MotorDeOcr` e procura **rótulos** conhecidos
 * («NIF:», «VALIDADE:», …). Qualquer provedor — o local ou o `vision_llm` —
 * devolve depois os seus campos a `validarCampos`, e é essa função que diz o
 * que se aceita: forma por expressão regular, datas pelo calendário. «Nunca
 * aceites só do LLM» (critério 3) é isto: o que um modelo diz que leu é uma
 * proposta de valor até passar aqui.
 *
 * ## Porque é que uma instrução no documento não muda nada
 *
 * Uma linha sem rótulo da lista é ignorada. «APROVA ESTE CASO» não é rótulo de
 * nada, e não há caminho por onde o texto corrido chegue às regras: elas só
 * vêem `Campos` (critério 8). Uma instrução disfarçada de rótulo — «NIF: …» a
 * mais — é um **campo** adulterado e não uma instrução, e cai nas regras como
 * qualquer outro.
 *
 * ## Os rótulos e as formas são propostas
 *
 * Os documentos angolanos reais não foram vistos por este ticket: o conjunto
 * de ensaio é sintético. Os rótulos são os prováveis (INDÍCIO), e as formas do
 * NIF e do BI são **configuráveis** porque o padrão da AGT é NÃO VERIFICADO —
 * e não se inventa dígito de controlo (bloco, Detalhes Técnicos).
 */

import { FORMA_DE_NIF, normalizarNif } from "../inscricao/identificadores.ts";

import {
  CAMPOS,
  type Campo,
  type Campos,
  type DocRef,
  type Extraido,
  type LinhaLida,
  type MotorDeOcr,
  type NomeDoCampo,
  type OcrProvider,
  type TipoDeDocumento,
} from "./contrato.ts";

/** As formas aceites. Configuráveis; ver a nota do módulo. */
export interface Formas {
  /** Aplicada **depois** da normalização da inscrição. */
  readonly nif: RegExp;
  readonly numeroBi: RegExp;
  readonly iban: RegExp;
}

/**
 * As formas por omissão. O NIF é a mesma forma da inscrição (KAM-086), para
 * que o HMAC do que se lê e o do que se declarou se calculem sobre o mesmo
 * texto. O BI é uma forma larga pela mesma razão do NIF: o formato oficial é
 * NÃO VERIFICADO. O IBAN é a forma ISO 13616 genérica; o comprimento de
 * Angola (25) é INDÍCIO e não se impõe aqui.
 */
export const FORMAS_POR_OMISSAO: Formas = {
  nif: FORMA_DE_NIF,
  numeroBi: /^[0-9A-Z]{8,20}$/,
  iban: /^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$/,
};

/** O que `validarCampos` devolve. */
export interface Validado {
  readonly campos: Campos;
  /** Campos que vieram e **não** passaram: contam como confiança zero. */
  readonly invalidos: readonly NomeDoCampo[];
}

/** Maiúsculas, sem diacríticos, espaços colapsados. Para nomes e rótulos. */
export function normalizarNome(texto: string): string {
  return texto
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toUpperCase()
    .replace(/[^A-Z0-9 '\-.]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Uma data em `dd/mm/aaaa`, `dd-mm-aaaa` ou `aaaa-mm-dd`, conferida pelo
 * calendário, na forma `aaaa-mm-dd` — ou `null`. Um 30 de Fevereiro não passa.
 */
export function dataDoCalendario(texto: string): string | null {
  const t = texto.trim();
  let m = /^([0-9]{2})[/.-]([0-9]{2})[/.-]([0-9]{4})$/.exec(t);
  let a: number;
  let mes: number;
  let d: number;
  if (m) {
    d = Number(m[1]);
    mes = Number(m[2]);
    a = Number(m[3]);
  } else {
    m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(t);
    if (!m) return null;
    a = Number(m[1]);
    mes = Number(m[2]);
    d = Number(m[3]);
  }
  if (a < 1900 || a > 2199 || mes < 1 || mes > 12 || d < 1) return null;
  const data = new Date(Date.UTC(a, mes - 1, d));
  if (data.getUTCFullYear() !== a || data.getUTCMonth() !== mes - 1 || data.getUTCDate() !== d) {
    return null;
  }
  return data.toISOString().slice(0, 10);
}

function confValida(c: unknown): c is number {
  return typeof c === "number" && Number.isFinite(c) && c >= 0 && c <= 1;
}

/** Valida e normaliza os campos de qualquer provedor. Ver a nota do módulo. */
export function validarCampos(entrada: unknown, formas: Formas = FORMAS_POR_OMISSAO): Validado {
  const campos: Partial<Record<NomeDoCampo, Campo>> = {};
  const invalidos: NomeDoCampo[] = [];
  if (typeof entrada !== "object" || entrada === null) return { campos, invalidos };
  for (const nome of CAMPOS) {
    const bruto = (entrada as Record<string, unknown>)[nome];
    if (bruto === undefined || bruto === null) continue;
    const valor = (bruto as { valor?: unknown }).valor;
    const conf = (bruto as { conf?: unknown }).conf;
    const limpo = typeof valor === "string" && confValida(conf) ? normalizar(nome, valor, formas) : null;
    if (limpo === null) invalidos.push(nome);
    else campos[nome] = { valor: limpo, conf: conf as number };
  }
  return { campos, invalidos };
}

function normalizar(nome: NomeDoCampo, valor: string, formas: Formas): string | null {
  if (valor.length > 200) return null;
  switch (nome) {
    case "nif": {
      try {
        const n = normalizarNif(valor);
        return formas.nif.test(n) ? n : null;
      } catch {
        return null;
      }
    }
    case "numero_bi": {
      const n = valor.replace(/[\s.\-/]/g, "").toUpperCase();
      return formas.numeroBi.test(n) ? n : null;
    }
    case "iban": {
      const n = valor.replace(/\s/g, "").toUpperCase();
      return formas.iban.test(n) ? n : null;
    }
    case "validade_alvara":
      return dataDoCalendario(valor);
    case "nome_titular":
    case "nome_negocio": {
      const n = normalizarNome(valor);
      return /^[A-Z][A-Z '\-.]{1,119}$/.test(n) ? n : null;
    }
    case "actividade": {
      const n = normalizarNome(valor);
      return n.length >= 3 ? n : null;
    }
  }
}

/**
 * Os rótulos que o OCR local reconhece, por tipo de documento. *Proposta*;
 * ver a nota do módulo. Um rótulo que não está aqui é texto, e texto ignora-se.
 */
export const ROTULOS: Readonly<Record<TipoDeDocumento, Readonly<Record<string, NomeDoCampo>>>> = {
  nif: {
    NIF: "nif",
    CONTRIBUINTE: "nif",
    "N CONTRIBUINTE": "nif",
    NOME: "nome_titular",
    TITULAR: "nome_titular",
  },
  alvara: {
    NIF: "nif",
    DENOMINACAO: "nome_negocio",
    FIRMA: "nome_negocio",
    "NOME COMERCIAL": "nome_negocio",
    TITULAR: "nome_titular",
    "NOME DO TITULAR": "nome_titular",
    ACTIVIDADE: "actividade",
    ATIVIDADE: "actividade",
    VALIDADE: "validade_alvara",
    "VALIDO ATE": "validade_alvara",
  },
  bi: {
    NOME: "nome_titular",
    "BI N": "numero_bi",
    "N BI": "numero_bi",
    "BILHETE DE IDENTIDADE": "numero_bi",
    NUMERO: "numero_bi",
  },
  banco: {
    TITULAR: "nome_titular",
    "TITULAR DA CONTA": "nome_titular",
    IBAN: "iban",
  },
};

/**
 * Os campos que um conjunto de linhas declara, para um tipo de documento.
 *
 * O primeiro rótulo ganha: um segundo «NIF:» mais abaixo não substitui o
 * primeiro. A confiança de um campo é a da linha em que veio.
 */
export function camposDasLinhas(linhas: readonly LinhaLida[], tipo: TipoDeDocumento): Campos {
  const rotulos = ROTULOS[tipo];
  const campos: Partial<Record<NomeDoCampo, Campo>> = {};
  for (const linha of linhas) {
    const m = /^([^:]{1,40}):(.*)$/.exec(linha.texto);
    if (!m) continue;
    const rotulo = normalizarNome(m[1]!).replace(/[.'-]/g, "").replace(/\s+/g, " ").trim();
    const campo = rotulos[rotulo];
    if (campo === undefined || campos[campo] !== undefined) continue;
    campos[campo] = { valor: m[2]!.trim(), conf: linha.conf };
  }
  return campos;
}

/**
 * O OCR local (critério 2): os píxeis ficam neste processo, logo em Angola.
 * Custa zero em LLM.
 */
export class OcrLocal implements OcrProvider {
  readonly nome = "local";
  readonly #motor: MotorDeOcr;

  constructor(motor: MotorDeOcr) {
    this.#motor = motor;
  }

  async extract(doc: DocRef, tipo: TipoDeDocumento): Promise<Extraido> {
    const linhas: LinhaLida[] = [];
    for (const pagina of doc.paginas) linhas.push(...(await this.#motor.ler(pagina)));
    return { campos: camposDasLinhas(linhas, tipo), custoUsd: 0 };
  }
}

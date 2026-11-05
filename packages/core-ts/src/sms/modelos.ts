/**
 * Os modelos de SMS: lista fechada, sem dados pessoais (KAM-116, critério 6).
 *
 * «O texto do OTP vem de um modelo fixo («não partilhe este código») sem dados
 * pessoais.»
 *
 * ## A lista fechada é o que mantém o marketing fora
 *
 * Os *Fora de âmbito* do ticket dizem «SMS de marketing», e o Contexto diz
 * porquê: o Art. 19.º da Lei 22/11 e o Instrutivo INACOM 4/20
 * (`../../../../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` §1) — cuja
 * aplicação directa a uma plataforma está **por confirmar (a confirmar por
 * parecer)**. Uma proibição escrita num comentário não impede nada; **um
 * registo fechado impede**, porque não há como enviar um texto que não esteja
 * aqui. O `send` recebe um `NomeDeModelo`, não um corpo: compor texto livre não
 * é uma operação desta porta.
 *
 * A `finalidade` tem dois valores — `otp` e `aviso_de_servico` — e **não tem**
 * `marketing`. Acrescentá-lo é uma alteração visível num diff, e passa pelo
 * parecer que a E3 pede.
 *
 * ## Um modelo, e não dois, e é honestidade e não preguiça
 *
 * Só o `otp_posse_telefone` está escrito. O ticket fala de «OTP e avisos de
 * serviço», mas **nenhum documento do conjunto fixa o texto de um aviso de
 * serviço por SMS**: o KAM-115 entregou o aviso ao dono e escolheu o e-mail
 * (`../avisos/`), e o SMS vem aqui sem corpo definido. Inventar o texto era
 * escrever conteúdo de produto num ficheiro de código, que é o que o critério 6
 * existe para impedir. A `finalidade` fica aberta e o registo pronto; o texto
 * entra com o ticket que mande o aviso.
 *
 * ## Sem acentos no corpo, e a razão é o tamanho do segmento
 *
 * O conjunto escreve-se em português europeu com acentos; **o corpo de um SMS é
 * carga útil de rede e não prosa**. O alfabeto GSM 03.38 (GSM-7) leva 160
 * caracteres por segmento e não tem `ã`, `é` nem `ç`: um só acento obriga o
 * agregador a codificar a mensagem em UCS-2, que desce para 70 caracteres e
 * pode partir o SMS em dois — dois segmentos, duas tarifas, e duas chances de
 * um chegar e o outro não.
 *
 * O GSM 03.38 é uma norma e está **CONFIRMADO** como norma; o que está **NÃO
 * VERIFICADO** é que o agregador escolhido e as duas operadoras a apliquem
 * assim, porque não há agregador escolhido. Por isso o corpo é ASCII — a
 * escolha conservadora é a que funciona nos dois casos — e o comprimento
 * máximo é verificado, para que um modelo novo não parta um SMS em silêncio.
 *
 * ## O que o `revelar()` do código faz aqui, e só aqui
 *
 * Este ficheiro é o **único** sítio do módulo onde o `CodigoOtp.revelar()` é
 * chamado: o corpo do SMS é o destino legítimo do código em claro. Um segundo
 * sítio de chamada é um achado de revisão (ver `codigo.ts`).
 */

import { CodigoOtp } from "./codigo.ts";

/** Para que serve um SMS deste módulo. **Não tem `marketing`** — ver a nota. */
export const FINALIDADES = ["otp", "aviso_de_servico"] as const;

export type Finalidade = (typeof FINALIDADES)[number];

/** Os modelos que existem. Um nome fora daqui não tem como ser enviado. */
export const NOMES_DE_MODELO = ["otp_posse_telefone"] as const;

export type NomeDeModelo = (typeof NOMES_DE_MODELO)[number];

/**
 * Caracteres por segmento em GSM-7. Um modelo que passe daqui **levanta**.
 *
 * O corpo rendido conta com os parâmetros substituídos pelos valores mais
 * longos que a validação admite, e não com os marcadores: um modelo que cabe
 * com `{codigo}` e não cabe com oito algarismos não é um modelo que cabe.
 */
export const CARACTERES_POR_SEGMENTO = 160;

/** Os parâmetros que um modelo pode ter. Lista fechada, como a dos modelos. */
export const PARAMETROS = ["codigo", "validade_min"] as const;

export type Parametro = (typeof PARAMETROS)[number];

/** Minutos de validade aceites. A escolha dentro da gama é do KAM-086. */
export const VALIDADE_MINIMA_MIN = 1;
export const VALIDADE_MAXIMA_MIN = 60;

/**
 * Os parâmetros de um envio.
 *
 * **Nenhum é dado pessoal, e a lista é a prova.** Não há `nome`, não há
 * `loja`, não há `telefone` e não há texto livre: o critério 6 pede «sem dados
 * pessoais», e a maneira de o verificar é lê-la. O `codigo` é um `CodigoOtp` e
 * não uma `string` pela razão de `codigo.ts`.
 */
export interface Parametros {
  readonly codigo: CodigoOtp;
  readonly validade_min: number;
}

/** O que um modelo declara. */
export interface Modelo {
  readonly nome: NomeDeModelo;
  readonly finalidade: Finalidade;
  /** O corpo, com marcadores `{parametro}`. ASCII — ver a nota do módulo. */
  readonly corpo: string;
  /** Os parâmetros que o corpo usa, pela ordem em que aparecem. */
  readonly parametros: readonly Parametro[];
}

/**
 * O registo.
 *
 * O corpo diz quem envia («KAMBA»), o que é («codigo de confirmacao»), quanto
 * tempo vale, e a frase que o critério 6 nomeia: «Nao partilhe este codigo.»
 * Não diz o nome do dono, nem o da loja, nem o número — nada que identifique
 * uma pessoa, porque um SMS é texto que fica no telemóvel e nos registos do
 * agregador.
 */
export const MODELOS: Readonly<Record<NomeDeModelo, Modelo>> = {
  otp_posse_telefone: {
    nome: "otp_posse_telefone",
    finalidade: "otp",
    corpo:
      "KAMBA: o seu codigo de confirmacao e {codigo}. " +
      "Valido {validade_min} min. Nao partilhe este codigo.",
    parametros: ["codigo", "validade_min"],
  },
};

/** Levantado quando o nome do modelo não está no registo. */
export class ModeloDesconhecidoError extends Error {
  override readonly name = "ModeloDesconhecidoError";

  constructor(nome: string) {
    super(
      `modelo de SMS desconhecido: ${JSON.stringify(nome)}; os que existem sao ` +
        NOMES_DE_MODELO.join(", "),
    );
  }
}

/**
 * Levantado quando um parâmetro não serve.
 *
 * A mensagem nomeia o parâmetro e **nunca o valor**: o `codigo` é o valor que o
 * critério 6 proíbe em logs, e uma mensagem de erro acaba num log.
 */
export class ParametroInvalidoError extends Error {
  override readonly name = "ParametroInvalidoError";
  readonly parametro: string;

  constructor(parametro: string, problema: string) {
    super(`parametro ${parametro} invalido: ${problema}`);
    this.parametro = parametro;
  }
}

/** Levantado quando o corpo rendido não cabe num segmento. */
export class CorpoLongoError extends Error {
  override readonly name = "CorpoLongoError";
  readonly caracteres: number;

  constructor(nome: string, caracteres: number) {
    super(
      `o modelo ${nome} rende ${caracteres} caracteres e o segmento GSM-7 leva ` +
        `${CARACTERES_POR_SEGMENTO}; dois segmentos sao duas tarifas e duas ` +
        "chances de um nao chegar",
    );
    this.caracteres = caracteres;
  }
}

/** Levantado quando o corpo de um modelo tem um caractere fora de ASCII. */
export class CorpoNaoAsciiError extends Error {
  override readonly name = "CorpoNaoAsciiError";

  constructor(nome: string) {
    super(
      `o corpo do modelo ${nome} tem caracteres fora de ASCII; um acento obriga ` +
        "o agregador a UCS-2, que desce de 160 para 70 caracteres por segmento",
    );
  }
}

const MARCADOR = /\{([a-z_]+)\}/g;
const SO_ASCII = /^[\x20-\x7e]*$/;

function exigirModelo(nome: string): Modelo {
  const modelo = (MODELOS as Readonly<Record<string, Modelo | undefined>>)[nome];
  if (modelo === undefined) throw new ModeloDesconhecidoError(nome);
  return modelo;
}

/**
 * Valida os parâmetros e devolve o corpo pronto a enviar.
 *
 * É aqui que o código em claro entra no texto, e é o único sítio. O resultado é
 * uma `string` normal — ela **é** a carga útil que vai para o agregador — e quem
 * a recebe não a registra: o `fake.ts` guarda-a para os ensaios e um adaptador
 * entrega-a e larga-a.
 */
export function construir(nome: string, parametros: Parametros): string {
  const modelo = exigirModelo(nome);

  if (!(parametros?.codigo instanceof CodigoOtp)) {
    throw new ParametroInvalidoError("codigo", "nao e um CodigoOtp");
  }
  const validade = parametros.validade_min;
  if (
    !Number.isInteger(validade) ||
    validade < VALIDADE_MINIMA_MIN ||
    validade > VALIDADE_MAXIMA_MIN
  ) {
    throw new ParametroInvalidoError(
      "validade_min",
      `esperava um inteiro entre ${VALIDADE_MINIMA_MIN} e ${VALIDADE_MAXIMA_MIN}`,
    );
  }

  const valores: Readonly<Record<Parametro, string>> = {
    codigo: parametros.codigo.revelar(),
    validade_min: String(validade),
  };

  const corpo = modelo.corpo.replace(MARCADOR, (_inteiro, marcador: string) => {
    const valor = (valores as Readonly<Record<string, string | undefined>>)[marcador];
    if (valor === undefined) throw new ParametroInvalidoError(marcador, "nao e um parametro");
    return valor;
  });

  if (!SO_ASCII.test(corpo)) throw new CorpoNaoAsciiError(modelo.nome);
  if (corpo.length > CARACTERES_POR_SEGMENTO) {
    throw new CorpoLongoError(modelo.nome, corpo.length);
  }
  return corpo;
}

/**
 * O comprimento do pior caso de um modelo, em caracteres.
 *
 * O pior caso é cada parâmetro no seu valor mais longo admitido: oito
 * algarismos de código e dois de validade. É isto que um ensaio corre sobre
 * **todos** os modelos do registo — um modelo que caiba com seis algarismos e
 * não caiba com oito parte-se em dois segmentos no dia em que o KAM-086 subir o
 * comprimento do código, e parte-se em produção.
 */
export function comprimentoNoPiorCaso(nome: string): number {
  const modelo = exigirModelo(nome);
  const piores: Readonly<Record<Parametro, string>> = {
    codigo: "9".repeat(8),
    validade_min: String(VALIDADE_MAXIMA_MIN),
  };
  return modelo.corpo.replace(MARCADOR, (inteiro, marcador: string) => {
    const valor = (piores as Readonly<Record<string, string | undefined>>)[marcador];
    return valor ?? inteiro;
  }).length;
}

/** Os marcadores que o corpo de um modelo usa, pela ordem em que aparecem. */
export function marcadoresDoModelo(nome: string): readonly string[] {
  const modelo = exigirModelo(nome);
  return [...modelo.corpo.matchAll(MARCADOR)].map((m) => m[1] ?? "");
}

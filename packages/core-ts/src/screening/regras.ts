/**
 * As regras da política, compiladas, e a sua avaliação (KAM-088, critérios 1 e 2).
 *
 * **Negar vence.** Uma entrada restritiva (`bloqueada` ou `condicional`) que
 * case em **qualquer** texto — a categoria declarada ou um título — decide, e a
 * mais restritiva das que casarem é a decisão. Uma entrada `permitida` só conta
 * quando casa a **categoria declarada**: num título de produto, «roupa» não
 * desbloqueia nada, e é isso que fecha o abuso típico do bloco (declarar
 * «moda» e vender álcool). O que não casa nada é `condicional` — «o resto».
 *
 * **A sobreposição por tenant só acrescenta restrição.** Pode subir a decisão
 * de uma entrada, acrescentar termos e padrões às restritivas e criar entradas
 * restritivas novas. Tudo o que alargue o que se permite — descer uma decisão,
 * criar uma `permitida`, acrescentar um termo a uma `permitida` (que passaria a
 * aceitar mais categorias declaradas) — falha na validação, e não em silêncio.
 */

import { createHash } from "node:crypto";

import { MINIMO_PARA_COMPACTA, normalizar, type TextoNormalizado } from "./normalizar.ts";
import { DECISOES, type Decisao, type EntradaFonte, type PoliticaFonte } from "./tipos.ts";

/** A regra sintética de quem não casa nada: «o resto ⇒ condicional». */
export const REGRA_NAO_LISTADA = "nao_listada";

/** As confianças das regras. *Proposta*: calibram-se no golden do KAM-040. */
export const CONFIANCA = {
  /** Um termo ou padrão de uma entrada `bloqueada` casou. */
  bloqueada: 1,
  /** Um termo ou padrão de uma entrada `condicional` casou. */
  condicional: 0.9,
  /** A categoria declarada casou uma `permitida` e nada restritivo casou. */
  permitida: 0.7,
  /** Nada casou. */
  naoListada: 0.5,
} as const;

/** A partir de quantas letras um termo casa pelo radical (sem a vogal final). */
export const MINIMO_PARA_RADICAL = 7;

/** Abaixo disto, a decisão das regras consulta o classificador. */
export const LIMIAR_DE_CONFIANCA = 0.9;

export function grau(decisao: Decisao): number {
  return DECISOES.indexOf(decisao);
}

/** A mais restritiva das decisões. Sem argumentos não há decisão, e isso é erro. */
export function maxRestricao(...decisoes: readonly Decisao[]): Decisao {
  if (decisoes.length === 0) throw new RangeError("maxRestricao sem decisões");
  return decisoes.reduce((a, b) => (grau(b) > grau(a) ? b : a));
}

interface TermoCompilado {
  readonly palavras: string;
  readonly compacta: string | null;
}

export interface EntradaCompilada {
  readonly id: string;
  readonly decisao: Decisao;
  readonly termos: readonly TermoCompilado[];
  readonly padroes: readonly RegExp[];
}

export interface PoliticaCompilada {
  readonly versao: string;
  readonly entradas: readonly EntradaCompilada[];
}

/** A política não se compila: um padrão inválido ou uma forma que não é a do esquema. */
export class PoliticaInvalidaError extends Error {
  constructor(motivo: string) {
    super(`politica de categorias invalida: ${motivo}`);
    this.name = "PoliticaInvalidaError";
  }
}

function compilarTermo(termo: string): TermoCompilado {
  const { palavras, compacta } = normalizar(termo);
  if (palavras === "") throw new PoliticaInvalidaError(`termo vazio depois de normalizar: ${JSON.stringify(termo)}`);
  if (compacta.length < MINIMO_PARA_COMPACTA) return { palavras, compacta: null };
  // Um termo longo casa pelo radical — sem a vogal final —, que é o que apanha
  // o diminutivo e o plural (`cervejinha`, `pistolas`). Os curtos não, porque o
  // radical de `vinho` é `vinh`, e há palavras de mais que o contêm.
  const radical =
    compacta.length >= MINIMO_PARA_RADICAL && /[aeiou]$/.test(compacta) ? compacta.slice(0, -1) : compacta;
  return { palavras, compacta: radical };
}

function compilarPadrao(id: string, padrao: string): RegExp {
  try {
    return new RegExp(padrao);
  } catch (erro) {
    throw new PoliticaInvalidaError(`${id}: padrao ${JSON.stringify(padrao)}: ${(erro as Error).message}`);
  }
}

function compilarEntrada(entrada: Pick<EntradaFonte, "id" | "decisao" | "termos" | "padroes">): EntradaCompilada {
  if (!DECISOES.includes(entrada.decisao)) {
    throw new PoliticaInvalidaError(`${entrada.id}: decisao ${JSON.stringify(entrada.decisao)}`);
  }
  return {
    id: entrada.id,
    decisao: entrada.decisao,
    termos: entrada.termos.map(compilarTermo),
    padroes: entrada.padroes.map((p) => compilarPadrao(entrada.id, p)),
  };
}

export function compilar(fonte: PoliticaFonte): PoliticaCompilada {
  if (!/^\d+\.\d+\.\d+(\+[0-9a-z.]+)?$/.test(fonte.versao)) {
    throw new PoliticaInvalidaError(`versao ${JSON.stringify(fonte.versao)} nao e SemVer`);
  }
  const ids = new Set<string>();
  for (const { id } of fonte.categorias) {
    if (ids.has(id)) throw new PoliticaInvalidaError(`id repetido: ${id}`);
    ids.add(id);
  }
  return { versao: fonte.versao, entradas: fonte.categorias.map(compilarEntrada) };
}

function casa(entrada: EntradaCompilada, texto: TextoNormalizado): boolean {
  const comEspacos = ` ${texto.palavras} `;
  for (const termo of entrada.termos) {
    if (comEspacos.includes(` ${termo.palavras} `)) return true;
    if (termo.compacta !== null && texto.compacta.includes(termo.compacta)) return true;
  }
  for (const padrao of entrada.padroes) {
    if (padrao.test(texto.basica) || padrao.test(texto.palavras)) return true;
  }
  return false;
}

export interface DecisaoDasRegras {
  readonly decisao: Decisao;
  readonly regras: readonly string[];
  readonly confianca: number;
}

/** Avalia a política sobre a categoria declarada e os textos. Pura e determinista. */
export function avaliarRegras(
  politica: PoliticaCompilada,
  categoriaDeclarada: string,
  textos: readonly string[],
): DecisaoDasRegras {
  const categoria = normalizar(categoriaDeclarada);
  const todos = [categoria, ...textos.map(normalizar)];

  const restritivas = politica.entradas.filter(
    (e) => e.decisao !== "permitida" && todos.some((t) => casa(e, t)),
  );
  if (restritivas.length > 0) {
    const decisao = maxRestricao(...restritivas.map((e) => e.decisao));
    return {
      decisao,
      regras: restritivas.map((e) => e.id).sort(),
      confianca: decisao === "bloqueada" ? CONFIANCA.bloqueada : CONFIANCA.condicional,
    };
  }
  const permitidas = politica.entradas.filter(
    (e) => e.decisao === "permitida" && casa(e, categoria),
  );
  if (permitidas.length > 0) {
    return { decisao: "permitida", regras: permitidas.map((e) => e.id).sort(), confianca: CONFIANCA.permitida };
  }
  return { decisao: "condicional", regras: [REGRA_NAO_LISTADA], confianca: CONFIANCA.naoListada };
}

/**
 * As entradas `bloqueada` que casam um texto solto — o *display name* do
 * número, que o pré-voo do KAM-093 tem de recusar quando nomeia uma categoria
 * bloqueada. Lista vazia = nenhuma. Não grava nada: um nome não é um produto.
 */
export function bloqueadasEm(politica: PoliticaCompilada, texto: string): readonly string[] {
  const normalizado = normalizar(texto);
  return politica.entradas
    .filter((e) => e.decisao === "bloqueada" && casa(e, normalizado))
    .map((e) => e.id)
    .sort();
}

// ---------------------------------------------------------------------------
// Sobreposição por tenant
// ---------------------------------------------------------------------------

export interface EntradaDaSobreposicao {
  readonly id: string;
  readonly decisao: Decisao;
  readonly termos?: readonly string[];
  readonly padroes?: readonly string[];
}

export interface Sobreposicao {
  readonly categorias: readonly EntradaDaSobreposicao[];
}

/** Uma sobreposição que alargaria o que se permite, ou que não tem a forma prevista. */
export class SobreposicaoRelaxaError extends Error {
  readonly entrada: string;

  constructor(entrada: string, motivo: string) {
    super(`a sobreposicao de ${entrada} relaxa a politica: ${motivo}. So pode acrescentar restricoes`);
    this.name = "SobreposicaoRelaxaError";
    this.entrada = entrada;
  }
}

const CHAVES_DA_SOBREPOSICAO = new Set(["id", "decisao", "termos", "padroes"]);

function validarForma(entrada: unknown): EntradaDaSobreposicao {
  if (typeof entrada !== "object" || entrada === null || Array.isArray(entrada)) {
    throw new SobreposicaoRelaxaError("?", "entrada que nao e um objecto");
  }
  const registo = entrada as Record<string, unknown>;
  const id = typeof registo.id === "string" && /^[a-z][a-z0-9_]*$/.test(registo.id) ? registo.id : "?";
  for (const chave of Object.keys(registo)) {
    // Uma chave que esta função não conhece — `remover`, `excepcoes`,
    // `permitir` — é exactamente onde um relaxamento se esconderia.
    if (!CHAVES_DA_SOBREPOSICAO.has(chave)) throw new SobreposicaoRelaxaError(id, `chave nao prevista ${JSON.stringify(chave)}`);
  }
  if (id === "?") throw new SobreposicaoRelaxaError(id, "id invalido");
  if (!DECISOES.includes(registo.decisao as Decisao)) throw new SobreposicaoRelaxaError(id, "decisao invalida");
  for (const lista of ["termos", "padroes"] as const) {
    const valor = registo[lista];
    if (valor !== undefined && (!Array.isArray(valor) || valor.some((v) => typeof v !== "string" || v.trim() === ""))) {
      throw new SobreposicaoRelaxaError(id, `${lista} tem de ser uma lista de textos`);
    }
  }
  return registo as unknown as EntradaDaSobreposicao;
}

/**
 * Junta a sobreposição de um tenant à política base, ou recusa.
 *
 * A versão do resultado leva a da base e uma impressão da sobreposição
 * (`1.0.0+t.<sha8>`), que é o que vai para `versao_politica`: uma decisão
 * tomada com a sobreposição não pode valer como tomada sem ela.
 */
export function fundirSobreposicao(base: PoliticaFonte, sobreposicao: Sobreposicao): PoliticaFonte {
  if (typeof sobreposicao !== "object" || sobreposicao === null || !Array.isArray(sobreposicao.categorias)) {
    throw new SobreposicaoRelaxaError("?", "sem lista de categorias");
  }
  const extra = Object.keys(sobreposicao).filter((c) => c !== "categorias");
  if (extra.length > 0) throw new SobreposicaoRelaxaError("?", `chave nao prevista ${JSON.stringify(extra[0])}`);

  const porId = new Map(base.categorias.map((e) => [e.id, e]));
  const vistas = new Set<string>();
  for (const bruta of sobreposicao.categorias) {
    const entrada = validarForma(bruta);
    if (vistas.has(entrada.id)) throw new SobreposicaoRelaxaError(entrada.id, "entrada repetida");
    vistas.add(entrada.id);
    const termos = entrada.termos ?? [];
    const padroes = entrada.padroes ?? [];
    const existente = porId.get(entrada.id);
    if (existente === undefined) {
      if (entrada.decisao === "permitida") {
        throw new SobreposicaoRelaxaError(entrada.id, "uma entrada nova permitida tiraria categorias do «resto» (condicional)");
      }
      compilarEntrada({ id: entrada.id, decisao: entrada.decisao, termos, padroes });
      porId.set(entrada.id, {
        id: entrada.id,
        decisao: entrada.decisao,
        termos,
        padroes,
        fonte_meta: null,
        fonte_lei: null,
        estado_evidencia: "NÃO VERIFICADO",
        revisto_em: "",
      });
      continue;
    }
    if (grau(entrada.decisao) < grau(existente.decisao)) {
      throw new SobreposicaoRelaxaError(entrada.id, `desce ${existente.decisao} para ${entrada.decisao}`);
    }
    if (entrada.decisao === "permitida" && (termos.length > 0 || padroes.length > 0)) {
      throw new SobreposicaoRelaxaError(entrada.id, "acrescentar termos a uma permitida aceita mais categorias declaradas");
    }
    compilarEntrada({ id: entrada.id, decisao: entrada.decisao, termos, padroes });
    porId.set(entrada.id, {
      ...existente,
      decisao: entrada.decisao,
      termos: [...new Set([...existente.termos, ...termos])],
      padroes: [...new Set([...existente.padroes, ...padroes])],
    });
  }
  const impressao = createHash("sha256")
    .update(JSON.stringify(sobreposicao.categorias))
    .digest("hex")
    .slice(0, 8);
  return {
    versao: `${base.versao.split("+")[0]}+t.${impressao}`,
    sha256: base.sha256,
    categorias: [...porId.values()],
  };
}

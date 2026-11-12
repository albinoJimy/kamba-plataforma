/**
 * Os tipos do screening de categorias (KAM-088).
 *
 * A forma da fonte (`PoliticaFonte`) é a de `policy/categorias/politica.esquema.json`,
 * com os nomes do ficheiro: o módulo gerado é a fonte em JSON, e renomear aqui
 * era ter dois vocabulários para o mesmo objecto.
 */

/** As três decisões, pela ordem de restrição. */
export const DECISOES = ["permitida", "condicional", "bloqueada"] as const;
export type Decisao = (typeof DECISOES)[number];

/** Quem tomou a decisão gravada — o `CHECK` de `screening_decision.origem`. */
export const ORIGENS = ["regra", "llm", "humano"] as const;
export type Origem = (typeof ORIGENS)[number];

/** O que se avalia — o `CHECK` de `screening_decision.sujeito_tipo`. */
export const SUJEITOS = ["categoria", "produto"] as const;
export type SujeitoTipo = (typeof SUJEITOS)[number];

export const ESTADOS_DE_EVIDENCIA = ["CONFIRMADO", "INDÍCIO", "NÃO VERIFICADO"] as const;
export type EstadoDeEvidencia = (typeof ESTADOS_DE_EVIDENCIA)[number];

export interface EntradaFonte {
  readonly id: string;
  readonly decisao: Decisao;
  readonly termos: readonly string[];
  readonly padroes: readonly string[];
  readonly fonte_meta: string | null;
  readonly fonte_lei: string | null;
  readonly estado_evidencia: EstadoDeEvidencia;
  readonly revisto_em: string;
}

export interface PoliticaFonte {
  readonly versao: string;
  readonly sha256: string;
  readonly categorias: readonly EntradaFonte[];
}

/** A entrada do `screen`, na forma do critério 4. */
export interface EntradaDoScreen {
  readonly categoria_declarada: string;
  readonly textos: readonly string[];
}

/** A saída do `screen`, na forma do critério 4. */
export interface ResultadoDoScreen {
  readonly decisao: Decisao;
  readonly regras: readonly string[];
  readonly versao_politica: string;
  readonly confianca: number;
}

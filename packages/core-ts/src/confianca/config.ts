/**
 * Confiança gradual — a configuração versionada (KAM-096).
 *
 * Os tectos de cada nível e os patamares de histórico que fazem um tenant
 * subir são **proposta**: nenhum foi medido, e o bloco do KAM-096 escreve-os
 * todos como «propostas a calibrar». Vivem aqui, num objecto com versão, e não
 * em constantes soltas nem num `CHECK` de coluna: calibrar é mudar este
 * ficheiro e subir a `versao`, e a versão vai em cada linha de `trust_level`
 * (`versao_config`) — um tecto que não diz de que configuração veio não se
 * audita. É o padrão do `VERSAO_DA_POLITICA` da retenção.
 *
 * Cada valor guarda a `origem` (`proposta` ou `calibrado`) e o `calibradoEm`
 * (critério 8): a `tabelaDeLimites` devolve-os em linhas, que é a forma que o
 * relatório do Piloto lê para comparar o previsto com o observado.
 */

/** Os três níveis do critério 1. Domínio de `trust_level.nivel`. */
export const NIVEIS_DE_CONFIANCA = [0, 1, 2] as const;
export type NivelDeConfianca = (typeof NIVEIS_DE_CONFIANCA)[number];

/** De onde vem um valor da configuração. */
export const ORIGENS_DO_VALOR = ["proposta", "calibrado"] as const;
export type OrigemDoValor = (typeof ORIGENS_DO_VALOR)[number];

export interface ValorConfigurado<T> {
  readonly valor: T;
  readonly origem: OrigemDoValor;
  /** Data ISO (`AAAA-MM-DD`) da calibração. `null` enquanto for `proposta`. */
  readonly calibradoEm: string | null;
  /** O sítio do canon de onde o número saiu. */
  readonly fonte: string;
}

export interface ConfiguracaoDoNivel {
  /** O tecto por pedido, em unidade menor (cêntimos de AOA). */
  readonly tectoPedidoMinor: ValorConfigurado<bigint>;
  /** O nível 2 é do K2/selo, que é das Clusters: no Piloto não se atribui. */
  readonly atribuivel: boolean;
}

export interface PatamaresDeHistorico {
  /** Pedidos elegíveis para subir do nível 0 ao 1. */
  readonly pedidosParaSubir: ValorConfigurado<number>;
  /** Compradores distintos entre esses pedidos. */
  readonly compradoresDistintos: ValorConfigurado<number>;
  /** A janela móvel em que os pedidos contam, em dias. */
  readonly janelaMovelDias: ValorConfigurado<number>;
  /** A janela anti-fraude depois da entrega, em dias: só conta quem a passou sem disputa. */
  readonly janelaAntiFraudeDias: ValorConfigurado<number>;
  /** O valor mínimo de um pedido que conta, em unidade menor. */
  readonly valorMinimoMinor: ValorConfigurado<bigint>;
}

export interface ConfiguracaoDaConfianca {
  /** `AAAA-MM-DD.N`; a forma do `trust_level_versao_config_ck`. */
  readonly versao: string;
  readonly niveis: Readonly<Record<NivelDeConfianca, ConfiguracaoDoNivel>>;
  readonly patamares: PatamaresDeHistorico;
}

const BLOCO = "specs/EPIC-09 bloco KAM-096";

function proposta<T>(valor: T, fonte: string = BLOCO): ValorConfigurado<T> {
  return { valor, origem: "proposta", calibradoEm: null, fonte };
}

/**
 * A configuração em vigor. **Todos os valores são proposta.**
 *
 * O nível 0 é o «menor dos dois» do Contexto do bloco: o tecto K1 (150 000 Kz)
 * e o limite do `ManualProvider` (50 000 Kz, `../docs/tecnica/04` §4.2 M-2), e
 * é o mesmo valor do `valor_max_pedido_minor` do plano `free` em
 * `registry/plans.yaml`. Os 5 pedidos, os 30 dias e os 10 000 Kz são do
 * critério 3; os 3 compradores distintos são o endurecimento que o critério 4
 * propõe; os 14 dias são a janela anti-fraude do critério 3.
 */
export const CONFIGURACAO_DA_CONFIANCA: ConfiguracaoDaConfianca = {
  versao: "2026-11-16.1",
  niveis: {
    0: { tectoPedidoMinor: proposta(5_000_000n), atribuivel: true },
    1: { tectoPedidoMinor: proposta(15_000_000n), atribuivel: true },
    2: { tectoPedidoMinor: proposta(50_000_000n), atribuivel: false },
  },
  patamares: {
    pedidosParaSubir: proposta(5),
    compradoresDistintos: proposta(3),
    janelaMovelDias: proposta(30),
    janelaAntiFraudeDias: proposta(14),
    valorMinimoMinor: proposta(1_000_000n),
  },
};

export class ConfiguracaoInvalidaError extends Error {
  override readonly name = "ConfiguracaoInvalidaError";
}

const VERSAO = /^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$/;
const DATA = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;

function origemCoerente(nome: string, v: ValorConfigurado<unknown>): void {
  if (v.origem === "proposta" && v.calibradoEm !== null) {
    throw new ConfiguracaoInvalidaError(`${nome}: uma proposta nao tem data de calibracao`);
  }
  if (v.origem === "calibrado" && (v.calibradoEm === null || !DATA.test(v.calibradoEm))) {
    throw new ConfiguracaoInvalidaError(`${nome}: um valor calibrado tem a data AAAA-MM-DD`);
  }
}

function inteiroPositivo(nome: string, v: ValorConfigurado<number>): void {
  origemCoerente(nome, v);
  if (!Number.isSafeInteger(v.valor) || v.valor <= 0) {
    throw new ConfiguracaoInvalidaError(`${nome}: tem de ser um inteiro positivo`);
  }
}

/**
 * Recusa uma configuração que a base recusaria, ou que subiria sem sentido.
 *
 * Os tectos são inteiros positivos e **crescem** com o nível — um nível acima
 * com tecto menor era uma subida que limitava mais —, o nível 2 não é
 * atribuível no Piloto, e a janela móvel é maior do que a anti-fraude: com as
 * duas iguais, nenhum pedido maduro cabia na janela.
 */
export function validarConfiguracao(c: ConfiguracaoDaConfianca): ConfiguracaoDaConfianca {
  if (!VERSAO.test(c.versao)) {
    throw new ConfiguracaoInvalidaError(`versao '${c.versao}': a forma e AAAA-MM-DD.N`);
  }
  let anterior = 0n;
  for (const n of NIVEIS_DE_CONFIANCA) {
    const t = c.niveis[n].tectoPedidoMinor;
    origemCoerente(`nivel ${n}`, t);
    if (typeof t.valor !== "bigint" || t.valor <= anterior) {
      throw new ConfiguracaoInvalidaError(`nivel ${n}: o tecto e positivo e maior do que o do nivel abaixo`);
    }
    anterior = t.valor;
  }
  if (c.niveis[2].atribuivel) {
    throw new ConfiguracaoInvalidaError("nivel 2: nao e atribuivel no Piloto (K2/selo, Clusters)");
  }
  const p = c.patamares;
  inteiroPositivo("pedidosParaSubir", p.pedidosParaSubir);
  inteiroPositivo("compradoresDistintos", p.compradoresDistintos);
  inteiroPositivo("janelaMovelDias", p.janelaMovelDias);
  inteiroPositivo("janelaAntiFraudeDias", p.janelaAntiFraudeDias);
  origemCoerente("valorMinimoMinor", p.valorMinimoMinor);
  if (p.valorMinimoMinor.valor <= 0n) {
    throw new ConfiguracaoInvalidaError("valorMinimoMinor: tem de ser positivo");
  }
  if (p.compradoresDistintos.valor > p.pedidosParaSubir.valor) {
    throw new ConfiguracaoInvalidaError("compradoresDistintos: nao pode exceder os pedidos para subir");
  }
  if (p.janelaMovelDias.valor <= p.janelaAntiFraudeDias.valor) {
    throw new ConfiguracaoInvalidaError("janelaMovelDias: tem de exceder a janela anti-fraude");
  }
  return c;
}

/** Uma linha da tabela de limites com origem (critério 8). */
export interface LinhaDeLimite {
  readonly chave: string;
  readonly valor: string;
  readonly origem: OrigemDoValor;
  readonly calibradoEm: string | null;
  readonly fonte: string;
}

/** A configuração em linhas, para o relatório do Piloto. Os montantes em unidade menor. */
export function tabelaDeLimites(c: ConfiguracaoDaConfianca = CONFIGURACAO_DA_CONFIANCA): readonly LinhaDeLimite[] {
  const linha = (chave: string, v: ValorConfigurado<bigint | number>): LinhaDeLimite => ({
    chave,
    valor: String(v.valor),
    origem: v.origem,
    calibradoEm: v.calibradoEm,
    fonte: v.fonte,
  });
  const p = c.patamares;
  return [
    ...NIVEIS_DE_CONFIANCA.map((n) => linha(`nivel_${n}.tecto_pedido_minor`, c.niveis[n].tectoPedidoMinor)),
    linha("pedidos_para_subir", p.pedidosParaSubir),
    linha("compradores_distintos", p.compradoresDistintos),
    linha("janela_movel_dias", p.janelaMovelDias),
    linha("janela_anti_fraude_dias", p.janelaAntiFraudeDias),
    linha("valor_minimo_minor", p.valorMinimoMinor),
  ];
}

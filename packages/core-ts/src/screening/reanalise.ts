/**
 * A re-análise do catálogo publicado quando a política muda de versão
 * (KAM-088, critério 7).
 *
 * **Sem cursor guardado.** O leitor devolve os produtos publicados que ainda
 * não têm decisão **para a versão corrente**, e o `screen` grava-a; a execução
 * seguinte recomeça onde esta parou, sem estado nenhum além da própria
 * `screening_decision`. Uma execução interrompida a meio não perde nem repete
 * nada que já tenha gravado.
 *
 * **Com orçamento.** Cada execução trata no máximo `maximoPorExecucao`
 * produtos, em lotes de `tamanhoDoLote`: a mudança de versão de um catálogo de
 * milhares de produtos não pode virar uma rajada de chamadas ao classificador.
 *
 * **Sem suspensão.** Uma violação — a decisão nova é `bloqueada` — emite
 * `screening.violation_detected` e mais nada: quem decide o que fazer ao tenant
 * é o KAM-097, que consome o evento. Uma `condicional` não é violação: vai à
 * fila de revisão (KAM-089) como qualquer outra.
 */

import { screen, type DependenciasDoScreen } from "./motor.ts";

export interface ProdutoPublicado {
  readonly tenantId: string;
  readonly sku: string;
  /** A categoria declarada do tenant, lida da sua decisão de categoria. */
  readonly categoriaDeclarada: string;
  readonly textos: readonly string[];
}

export interface LeitorDoCatalogo {
  /** Até `limite` produtos publicados sem decisão para `versao`, por ordem estável. */
  porReanalisar(versao: string, limite: number): Promise<readonly ProdutoPublicado[]>;
}

export interface Violacao {
  readonly tenantId: string;
  readonly sku: string;
  readonly regras: readonly string[];
  readonly versaoPolitica: string;
}

export interface EmissorDeViolacoes {
  emitir(violacao: Violacao): Promise<void>;
}

export interface Orcamento {
  readonly tamanhoDoLote: number;
  readonly maximoPorExecucao: number;
}

export interface ResultadoDaReanalise {
  readonly analisados: number;
  readonly violacoes: number;
  /** `true` se o leitor ficou vazio antes de o orçamento acabar. */
  readonly terminou: boolean;
}

export async function reanalisar(
  dependencias: DependenciasDoScreen & {
    readonly catalogo: LeitorDoCatalogo;
    readonly emissor: EmissorDeViolacoes;
  },
  orcamento: Orcamento,
): Promise<ResultadoDaReanalise> {
  if (!(orcamento.tamanhoDoLote >= 1 && orcamento.maximoPorExecucao >= 1)) {
    throw new RangeError("orcamento da reanalise sem lote ou sem maximo");
  }
  const versao = dependencias.politica.versao;
  let analisados = 0;
  let violacoes = 0;
  while (analisados < orcamento.maximoPorExecucao) {
    const limite = Math.min(orcamento.tamanhoDoLote, orcamento.maximoPorExecucao - analisados);
    const lote = await dependencias.catalogo.porReanalisar(versao, limite);
    if (lote.length === 0) return { analisados, violacoes, terminou: true };
    for (const produto of lote.slice(0, limite)) {
      const resultado = await screen(
        { tenantId: produto.tenantId, sujeitoTipo: "produto", sujeitoRef: produto.sku },
        { categoria_declarada: produto.categoriaDeclarada, textos: produto.textos },
        dependencias,
      );
      analisados += 1;
      if (resultado.decisao === "bloqueada") {
        await dependencias.emissor.emitir({
          tenantId: produto.tenantId,
          sku: produto.sku,
          regras: resultado.regras,
          versaoPolitica: versao,
        });
        violacoes += 1;
      }
    }
    if (lote.length < limite) return { analisados, violacoes, terminou: true };
  }
  return { analisados, violacoes, terminou: false };
}

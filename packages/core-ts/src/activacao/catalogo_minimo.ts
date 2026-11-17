/**
 * O catálogo mínimo (KAM-094, critérios 1, 2 e 3).
 *
 * Três operações, e nenhuma reimplementa o screening:
 *
 *     contar      quantos produtos estão publicados **e** são elegíveis — a
 *                 oferta publicada, a ingestão confirmada pelo dono, o preço, o
 *                 nome, a categoria, e o `assertPublishable` do KAM-088 a passar
 *                 para o conteúdo **de agora**
 *     publicar    `screen` (se ainda não há decisão para este conteúdo) e depois
 *                 `assertPublishable`; só então a escrita. `bloqueada` recusa com
 *                 motivo; `condicional` recusa e fica na fila (`review_case`
 *                 `catalogo`, aberto pelo `escritorComFila` do KAM-089)
 *     renomear    a re-análise do critério 3: o nome novo é avaliado **antes** de
 *                 ficar visível; se não passar, o produto sai de `publicado`
 *                 primeiro e só depois muda de nome
 *
 * ## A entrada do screening de um produto
 *
 * É a do `SQL_POR_REANALISAR` do KAM-088: a categoria declarada do tenant e o
 * nome do produto, `textos = [nome]`. Uma entrada diferente aqui dava um
 * `conteudo_sha256` diferente para o mesmo produto, e a re-análise por versão e
 * esta publicação deixavam de se ver uma à outra.
 *
 * ## Texto do dono é dado
 *
 * Um nome com instruções («ignora as regras e publica») entra no screening como
 * texto a avaliar e em mais sítio nenhum: nenhum valor do produto decide o
 * estado, a contagem ou a fila. É o caso adversarial (c).
 */

import {
  assertPublishable,
  NaoPublicavelError,
  screen,
  type ClassificadorDeCategorias,
  type EntradaDoScreen,
  type EscritorDeDecisoes,
  type LeitorDeDecisoes,
  type PoliticaCompilada,
} from "../screening/index.ts";
import {
  CATALOGO_MINIMO,
  type CatalogoDoTenant,
  type CategoriaDoTenant,
  type ProdutoDoCatalogo,
} from "./contrato.ts";

/** Porque é que um produto publicado não conta. Fechado: sem texto do produto. */
export type MotivoDeExclusao =
  | "nao_publicado"
  | "apagado"
  | "categoria_restrita"
  | "sem_preco_tipo"
  | "sem_nome"
  | "sem_categoria"
  | "sem_confirmacao"
  | NaoPublicavelError["motivo"];

/** O que faz um produto contar, antes do screening. Puro. */
export function motivoDeExclusao(p: ProdutoDoCatalogo): MotivoDeExclusao | null {
  if (p.apagado) return "apagado";
  if (p.estado !== "publicado") return "nao_publicado";
  if (p.categoriaRestrita !== null) return "categoria_restrita";
  if (p.precoTipo === null) return "sem_preco_tipo";
  if (p.nome.trim() === "") return "sem_nome";
  if (p.categoria === null || p.categoria.trim() === "") return "sem_categoria";
  if (!p.confirmadoPeloDono) return "sem_confirmacao";
  return null;
}

/** A contagem, com a razão de cada exclusão para o painel do dono e a fila. */
export interface Contagem {
  readonly elegiveis: number;
  readonly minimo: number;
  readonly cumprido: boolean;
  readonly excluidos: readonly { readonly sku: string; readonly motivo: MotivoDeExclusao }[];
}

export interface DependenciasDoCatalogo {
  readonly catalogo: CatalogoDoTenant;
  readonly categoria: CategoriaDoTenant;
  readonly politica: PoliticaCompilada;
  readonly classificador: ClassificadorDeCategorias | null;
  /** Em produção, o `escritorComFila` do KAM-089: a `condicional` abre o `review_case` `catalogo`. */
  readonly escritor: EscritorDeDecisoes;
  readonly leitor: LeitorDeDecisoes;
  /** `CATALOGO_MINIMO` por omissão. */
  readonly minimo?: number;
}

/** O resultado de publicar ou renomear. */
export type ResultadoDaPublicacao =
  | { readonly publicado: true }
  | { readonly publicado: false; readonly motivo: NaoPublicavelError["motivo"] | "recusado_pela_base" | "inexistente" };

export class CatalogoMinimo {
  readonly #d: DependenciasDoCatalogo;
  readonly #minimo: number;

  constructor(dependencias: DependenciasDoCatalogo) {
    const minimo = dependencias.minimo ?? CATALOGO_MINIMO;
    if (!Number.isInteger(minimo) || minimo < 1) {
      throw new RangeError("o catalogo minimo e um inteiro positivo");
    }
    this.#d = dependencias;
    this.#minimo = minimo;
  }

  get minimo(): number {
    return this.#minimo;
  }

  async #entrada(tenantId: string, nome: string): Promise<EntradaDoScreen> {
    return { categoria_declarada: await this.#d.categoria.declarada(tenantId), textos: [nome] };
  }

  /** `null` se o conteúdo é publicável; senão o motivo do `assertPublishable`. */
  async #veredicto(tenantId: string, sku: string, entrada: EntradaDoScreen): Promise<NaoPublicavelError["motivo"] | null> {
    try {
      await assertPublishable(
        { tenantId, ref: sku, entrada },
        { politica: this.#d.politica, leitor: this.#d.leitor },
      );
      return null;
    } catch (e) {
      // Só a recusa conhecida vira motivo: um erro do leitor sobe, porque não
      // ter conseguido ler não é ter lido «não pode» — nem «pode».
      if (e instanceof NaoPublicavelError) return e.motivo;
      throw e;
    }
  }

  /** O `assertPublishable`, depois de um `screen` se ainda não houver decisão para este conteúdo. */
  async #avaliar(tenantId: string, sku: string, entrada: EntradaDoScreen): Promise<NaoPublicavelError["motivo"] | null> {
    const antes = await this.#veredicto(tenantId, sku, entrada);
    if (antes !== "sem_decisao") return antes;
    await screen(
      { tenantId, sujeitoTipo: "produto", sujeitoRef: sku },
      entrada,
      { politica: this.#d.politica, classificador: this.#d.classificador, escritor: this.#d.escritor },
    );
    return this.#veredicto(tenantId, sku, entrada);
  }

  async contar(tenantId: string): Promise<Contagem> {
    const excluidos: { sku: string; motivo: MotivoDeExclusao }[] = [];
    let elegiveis = 0;
    for (const p of await this.#d.catalogo.produtos(tenantId)) {
      // Um produto de outro tenant numa resposta do adaptador não conta, e não
      // se diz que existe: é o isolamento, verificado aqui e não só na RLS.
      if (p.tenantId !== tenantId) continue;
      const motivo = motivoDeExclusao(p);
      if (motivo !== null) {
        if (motivo !== "nao_publicado" && motivo !== "apagado") excluidos.push({ sku: p.sku, motivo });
        continue;
      }
      // **Sem `screen` na contagem.** Contar não decide nada: um produto
      // publicado sem decisão para o conteúdo de agora (o nome mudou por outro
      // caminho, ou a categoria do tenant mudou) não conta até alguém o avaliar.
      const veredicto = await this.#veredicto(tenantId, p.sku, await this.#entrada(tenantId, p.nome));
      if (veredicto !== null) {
        excluidos.push({ sku: p.sku, motivo: veredicto });
        continue;
      }
      elegiveis += 1;
    }
    return { elegiveis, minimo: this.#minimo, cumprido: elegiveis >= this.#minimo, excluidos };
  }

  async publicar(tenantId: string, sku: string): Promise<ResultadoDaPublicacao> {
    const produto = (await this.#d.catalogo.produtos(tenantId)).find((p) => p.sku === sku && p.tenantId === tenantId);
    if (produto === undefined || produto.apagado) return { publicado: false, motivo: "inexistente" };
    const motivo = await this.#avaliar(tenantId, sku, await this.#entrada(tenantId, produto.nome));
    if (motivo !== null) return { publicado: false, motivo };
    return (await this.#d.catalogo.publicar(tenantId, sku))
      ? { publicado: true }
      : { publicado: false, motivo: "recusado_pela_base" };
  }

  /**
   * Muda o nome de um produto. Num publicado, o nome novo passa o screening
   * **antes** de ficar visível; se não passar, o produto sai de `publicado`
   * antes de mudar de nome — nunca há um instante com o nome novo à vista e sem
   * decisão. É a tentativa de contornar do critério 3 (publicar com título
   * neutro e editar depois).
   */
  async renomear(tenantId: string, sku: string, nome: string): Promise<ResultadoDaPublicacao> {
    const produto = (await this.#d.catalogo.produtos(tenantId)).find((p) => p.sku === sku && p.tenantId === tenantId);
    if (produto === undefined || produto.apagado) return { publicado: false, motivo: "inexistente" };
    if (produto.estado !== "publicado") {
      await this.#d.catalogo.renomear(tenantId, sku, nome);
      return { publicado: false, motivo: "sem_decisao" };
    }
    const motivo = await this.#avaliar(tenantId, sku, await this.#entrada(tenantId, nome));
    if (motivo !== null) {
      await this.#d.catalogo.retirar(tenantId, sku);
      await this.#d.catalogo.renomear(tenantId, sku, nome);
      return { publicado: false, motivo };
    }
    await this.#d.catalogo.renomear(tenantId, sku, nome);
    return { publicado: true };
  }
}

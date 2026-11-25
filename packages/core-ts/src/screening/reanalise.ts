/**
 * A re-análise do catálogo publicado quando a política muda de versão
 * (KAM-088, critério 7).
 *
 * **Sem cursor guardado.** O leitor devolve os produtos publicados que ainda
 * não têm decisão **para a versão corrente e para o conteúdo publicado**
 * (KAM-119: o `conteudo_sha256` da entrada), e o `screen` grava-a; a execução
 * seguinte recomeça onde esta parou, sem estado nenhum além da própria
 * `screening_decision`. Uma execução interrompida a meio não perde nem repete
 * nada que já tenha gravado.
 *
 * **Com orçamento.** Cada execução trata no máximo `maximoPorExecucao`
 * produtos, em lotes de `tamanhoDoLote`: a mudança de versão de um catálogo de
 * milhares de produtos não pode virar uma rajada de chamadas ao classificador.
 *
 * **Sem suspensão.** Uma violação — a decisão nova é `bloqueada` — emite
 * `screening.violation_detected`: quem decide o que fazer ao tenant é o
 * KAM-097, que consome o evento. Uma `condicional` não é violação: vai à fila
 * de revisão (KAM-089) como qualquer outra.
 *
 * **Mas o produto sai do catálogo visível** (KAM-253, decisão A do fundador de
 * 2026-11-24, que emenda o critério 4 do KAM-191 na metade «nem despublicar»).
 * Na mesma transacção por produto, depois da decisão e **antes** da violação,
 * a `retirada` tira-o de `publicado` para `rascunho` e emite o
 * `catalog.product_changed`, como o `/internal/screen` do COM desde o KAM-245.
 * Uma falha de qualquer dos quatro desfaz os quatro.
 *
 * **A ordem é a das trancas, e não é cosmética** (achado 1 da revisão
 * adversarial do KAM-253). O `evt_emitir` tranca a linha da sequência do
 * agregado (`evt_agregado_seq`, o par `product`/`sku`) até à confirmação, e o
 * `/internal/screen` e o rascunho do dono trancam a oferta **antes** de
 * emitir. Uma re-análise que emitisse a violação e só depois trancasse a
 * oferta fazia a ordem contrária, e o PostgreSQL resolvia o impasse com
 * `40P01`. A retirada tranca a oferta primeiro, como eles.
 */

import { conteudoSha256, screen, type DependenciasDoScreen } from "./motor.ts";

export interface ProdutoPublicado {
  readonly tenantId: string;
  readonly sku: string;
  /** A categoria declarada do tenant, lida da sua decisão de categoria. */
  readonly categoriaDeclarada: string;
  readonly textos: readonly string[];
}

export interface LeitorDoCatalogo {
  /** Até `limite` produtos publicados sem decisão para `versao` e para o seu conteúdo, por ordem estável. */
  porReanalisar(versao: string, limite: number): Promise<readonly ProdutoPublicado[]>;
}

export interface Violacao {
  readonly tenantId: string;
  readonly sku: string;
  readonly regras: readonly string[];
  readonly versaoPolitica: string;
  /**
   * O sha256 do conteúdo decidido — o mesmo `conteudoSha256` que o `screen`
   * gravou na decisão (KAM-191). Diz ao consumidor **que versão** do produto
   * violou, sem levar o texto dela.
   */
  readonly conteudoSha256: Uint8Array;
}

export interface EmissorDeViolacoes {
  emitir(violacao: Violacao): Promise<void>;
}

/**
 * Tira do catálogo visível o produto cuja decisão acabada de gravar o bloqueou
 * (KAM-253). Corre na transacção do produto, depois da decisão e antes da
 * violação (ver a nota do módulo).
 *
 * Devolve `true` se o tirou, e `false` se não havia nada a tirar: o produto já
 * não está publicado com o conteúdo lido, ou o `assertPublishable` não diz
 * `bloqueada` para a `politica` (uma `permitida` humana desta versão ganha). A
 * `politica` é a do próprio `reanalisar`, para não haver duas versões. O
 * adaptador de produção é o `RetiradaSql` de `retirada.ts`.
 */
export interface RetiradaDoCatalogo {
  retirar(produto: ProdutoPublicado, politica: DependenciasDoScreen["politica"]): Promise<boolean>;
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

/**
 * A unidade de trabalho de um produto: abre a transacção com o contexto do
 * tenant dele, corre `trabalho` e confirma — ou desfaz se `trabalho` lançar.
 *
 * **É o que liga a decisão à violação** (achados F11 e F12 da revisão
 * adversarial). Sem ela, um emissor que falhasse depois de o `screen` gravar
 * perdia a violação para sempre — a execução seguinte já não via o produto —;
 * e um escritor único para um lote de vários tenants batia na RLS `WITH CHECK`
 * no primeiro produto do segundo tenant. Em produção, o escritor e o emissor
 * do `trabalho` usam o cliente desta transacção (o emissor pelo `evt_emitir`,
 * no mesmo *outbox*). A omissão corre sem transacção, e serve só aos ensaios.
 *
 * O emissor de produção é o `EmissorSql` de `emissor.ts` (KAM-191), construído
 * sobre o cliente **desta** transacção — o mesmo do `EscritorSql`.
 */
export type PorProduto = <T>(tenantId: string, trabalho: () => Promise<T>) => Promise<T>;

const SEM_TRANSACCAO: PorProduto = (_tenant, trabalho) => trabalho();

export async function reanalisar(
  dependencias: DependenciasDoScreen & {
    readonly catalogo: LeitorDoCatalogo;
    readonly emissor: EmissorDeViolacoes;
    /** Obrigatória: sem ela, o publicado bloqueado ficava visível em silêncio. */
    readonly retirada: RetiradaDoCatalogo;
    readonly porProduto?: PorProduto;
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
    const porProduto = dependencias.porProduto ?? SEM_TRANSACCAO;
    for (const produto of lote.slice(0, limite)) {
      const violou = await porProduto(produto.tenantId, async () => {
        const entrada = { categoria_declarada: produto.categoriaDeclarada, textos: produto.textos };
        const resultado = await screen(
          { tenantId: produto.tenantId, sujeitoTipo: "produto", sujeitoRef: produto.sku },
          entrada,
          dependencias,
        );
        if (resultado.decisao !== "bloqueada") return false;
        await dependencias.retirada.retirar(produto, dependencias.politica);
        await dependencias.emissor.emitir({
          tenantId: produto.tenantId,
          sku: produto.sku,
          regras: resultado.regras,
          versaoPolitica: versao,
          conteudoSha256: conteudoSha256(entrada),
        });
        return true;
      });
      analisados += 1;
      if (violou) violacoes += 1;
    }
    if (lote.length < limite) return { analisados, violacoes, terminou: true };
  }
  return { analisados, violacoes, terminou: false };
}

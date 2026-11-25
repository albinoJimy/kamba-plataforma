/**
 * O `screen` do KAM-088 servido a quem não é TypeScript (KAM-222).
 *
 * O motor do screening só existe em `packages/core-ts/src/screening/`, e o
 * Python chama-o por aqui, pela 12.ª rota da API interna
 * (`POST /internal/screen`). **Não há segundo motor**: quem decide é o `screen`
 * da biblioteca, com a política compilada (`politicaCorrente()`), o
 * classificador pelo AGR e o escritor da `platform.screening_decision`. Esta
 * operação só monta as três peças.
 *
 * ## Duas transacções curtas, e nenhuma durante o classificador
 *
 * O `screen` consulta o classificador **antes** de gravar, e o classificador é
 * uma chamada ao AGR com tecto de 15 s (`TEMPO_MAXIMO_MS`). Embrulhar o `screen`
 * inteiro num `comTenant` deixava uma ligação do `Pool` presa durante a chamada
 * ao modelo. Por isso há duas transacções: uma lê a categoria declarada do
 * tenant (quando o pedido não a traz) e a outra grava a decisão. Cada uma toma a
 * sua ligação e devolve-a.
 *
 * ## A categoria declarada, quando o pedido não a traz
 *
 * É a do tenant: a `sujeito_ref` da decisão `categoria` mais recente. É a regra
 * da re-análise (`SQL_POR_REANALISAR`), e é ela que serve as condições de um
 * orçamento, que não têm categoria própria. Sem decisão de categoria fica
 * vazia, e o `screen` lê `nao_listada`, que é `condicional`: um tenant sem
 * categoria avaliada não tem nada `permitida`.
 *
 * ## Entram as condições e o produto; a categoria não
 *
 * A `categoria` é a do onboarding, e a re-análise lê a mais recente como «a
 * categoria declarada do tenant». Um chamador interno que a gravasse mudava a
 * categoria do tenant — e por isso continua fora.
 *
 * O `produto` entrou com o Catálogo AI (KAM-119). Estava fechado porque a
 * re-análise procurava uma decisão por `sku` e versão **sem** comparar o
 * `conteudo_sha256`: uma decisão gravada com outro texto fazia-a saltar um
 * produto publicado, e o `screening.violation_detected` nunca saía (achado 1
 * da revisão adversarial do KAM-222). Desde o KAM-119 o `SQL_POR_REANALISAR`
 * compara o resumo do conteúdo que ele próprio analisaria, e uma decisão sobre
 * outro texto já não esconde nada.
 *
 * ## A `bloqueada` de um publicado emite aqui (KAM-245)
 *
 * Uma decisão `bloqueada` gravada por aqui sobre o conteúdo **exacto** de um
 * produto já publicado também é uma decisão para a versão e para o conteúdo, e
 * a re-análise salta-o. Até ao KAM-245 o `screening.violation_detected`, que só
 * a re-análise emitia, não saía. Agora sai daqui, **na transacção da decisão**
 * (`gravarComViolacao`), pela mesma razão da re-análise (achados F11 e F12 do
 * KAM-088): uma violação que falhasse depois de a decisão confirmar perdia-se
 * para sempre, porque a re-análise já não via o produto.
 *
 * Emite-se uma vez por conteúdo: só quando a decisão nova faz o conteúdo
 * publicado **passar** a `bloqueada` aos olhos do `assertPublishable`. Uma
 * repetição, ou uma `bloqueada` que a re-análise já emitiu, encontra-o
 * `bloqueada` antes, e não emite; uma `permitida` humana anterior continua a
 * ganhar, e também não.
 *
 * **E o produto sai do catálogo visível na mesma transacção** (decisão A do
 * fundador, 2026-11-23): a oferta passa a `rascunho` e sai o
 * `catalog.product_changed`, que o IDX lê para esconder o documento. Desde o
 * KAM-253 (decisão A do fundador de 2026-11-24) a re-análise de uma mudança de
 * política despublica da mesma forma, pelo mesmo `despublicar` do
 * `core-ts/screening`.
 *
 * O sujeito das condições entrou no `SUJEITOS` e no `CHECK` com a revisão
 * `0074` (decisão do fundador de 2026-11-19, bloco do KAM-222).
 *
 * ## Publicar só confere, e não volta a fazer o `screen`
 *
 * O `/internal/publish-product` (KAM-119, `operacaoDePublicar`) lê o `nome` da
 * oferta e a categoria do tenant numa transacção curta, corre o
 * `assertPublishable` sobre a entrada `{categoria_declarada: <a do tenant>,
 * textos: [nome]}` — a mesma da re-análise e a mesma que o `/internal/screen`
 * com `categoria_declarada` nula e `textos: [nome]` grava — e publica com o
 * `nome` conferido sob a tranca (`nomeEsperado`). **Não corre o `screen`**: um
 * segundo `screen` do mesmo conteúdo consultava o classificador outra vez, e
 * uma `condicional` dele bastava para o `assertPublishable` (que, sem decisão
 * humana, exige todas as linhas `permitida`) recusar o que já estava aprovado.
 *
 * ## *Fail-closed*
 *
 * Qualquer falha (base, escritor) devolve `UPSTREAM_DOWN`, e o chamador recusa.
 * Isto inclui um `CHECK` da `screening_decision` que recuse a linha. Uma
 * decisão que não ficou gravada não existe (KAM-088),
 * e por isso não se devolve. O classificador em baixo **não** é falha daqui: o
 * `screen` trata-o como `condicional`, e essa resposta sai com 200.
 */

import {
  assertPublishable,
  conteudoSha256,
  despublicar,
  EmissorSql,
  EscritorSql,
  FINALIDADE_DAS_CONDICOES,
  FINALIDADE_DO_CATALOGO,
  FINALIDADE_DO_CONTEUDO,
  LeitorSql,
  NaoPublicavelError,
  SQL_CATEGORIA_DO_TENANT,
  SQL_PUBLICADO_SOB_TRANCA,
  SUJEITOS,
  screen,
  type ClassificadorDeCategorias,
  type EntradaDoScreen,
  type LinhaDeDecisao,
  type PoliticaCompilada,
  type ResultadoDoScreen,
  type SujeitoTipo,
} from "@kamba/core-ts/screening";

import {
  erro,
  exigirCtx,
  ok,
  type ClienteSql,
  type ComTenant,
  type Ctx,
  type OwnerConfirmation,
  type ProductRef,
  type Resultado,
  type ResultadoFinal,
} from "../port/index.ts";
import { confirmacaoValida } from "../produtos/index.ts";

/** O sujeito das condições de um orçamento. Está no `CHECK` desde a revisão `0074`. */
export const SUJEITO_DAS_CONDICOES = "condicoes";

/** O sujeito de um produto, com o `sku` da `offer_terms` por referência (KAM-119). */
export const SUJEITO_DO_PRODUTO = "produto";

/**
 * O sujeito do conteúdo do módulo social (KAM-121, decisão 1 do fundador de
 * 2026-11-20): o tema ou a legenda de um item, com o `content_item_id` por
 * referência. Nem a
 * re-análise nem o `assertPublishable` o leem: é um rascunho do dono, e o que
 * se entrega é do KAM-122.
 */
export const SUJEITO_DO_CONTEUDO = "conteudo";

/**
 * Os sujeitos que a rota aceita: o das condições, o do produto e o do
 * conteúdo, lidos do `SUJEITOS` do `tipos.ts` (que o ensaio da base compara com
 * o `CHECK`). A `categoria` nunca. Ver a nota do módulo.
 */
export const SUJEITOS_DA_ROTA: readonly SujeitoTipo[] = SUJEITOS.filter(
  (sujeito) =>
    (sujeito as string) === SUJEITO_DAS_CONDICOES ||
    (sujeito as string) === SUJEITO_DO_PRODUTO ||
    (sujeito as string) === SUJEITO_DO_CONTEUDO,
);

/**
 * A finalidade de transferência de cada sujeito da rota (KAM-230). O
 * classificador do AGR consulta o *gate* de destino com ela, e não com a do
 * papel: as condições de um orçamento têm a sua (decisão do fundador de
 * 2026-11-20, opção B), e a do catálogo nunca as cobre. O AGR manda a
 * finalidade no pedido, e a operação confere-a com esta tabela: duas leituras
 * que discordam recusam, em vez de uma escolher pela outra.
 */
export const FINALIDADE_DO_SUJEITO: Readonly<Record<string, string>> = {
  [SUJEITO_DAS_CONDICOES]: FINALIDADE_DAS_CONDICOES,
  [SUJEITO_DO_PRODUTO]: FINALIDADE_DO_CATALOGO,
  [SUJEITO_DO_CONTEUDO]: FINALIDADE_DO_CONTEUDO,
};

/**
 * O que fica do prazo de quem chama para gravar a decisão e responder, depois do
 * classificador (KAM-230). *Proposta*: a gravação é uma instrução numa
 * transacção curta, e o p99 dela não está medido.
 */
export const RESERVA_DA_GRAVACAO_MS = 300;

/** O tecto do `prazo_ms` que a rota aceita: o `TEMPO_MAXIMO_MS` do adaptador Python. */
export const PRAZO_MAXIMO_MS = 20_000;

/** O pedido que a rota valida. `categoriaDeclarada` `null` quer dizer «a do tenant». */
export interface PedidoDeScreen {
  /** Uma cadeia: quem decide se é um sujeito aceite é a operação. */
  readonly sujeitoTipo: string;
  readonly sujeitoRef: string;
  readonly categoriaDeclarada: string | null;
  readonly textos: readonly string[];
  /** A finalidade que o chamador diz (KAM-230); tem de ser a do sujeito. */
  readonly finalidade: string;
  /** O que sobra a quem chama, em milissegundos, quando o pedido sai (KAM-230). */
  readonly prazoMs: number;
}

/**
 * A categoria declarada do tenant, a tranca do publicado e a saída de publicado
 * moram no `core-ts/screening` desde o KAM-253: a re-análise usa as mesmas, e
 * um só código escreve a saída de publicado pelos dois caminhos (decisão A do
 * fundador de 2026-11-24). Reexportam-se para os ensaios do COM.
 */
export { SQL_CATEGORIA_DO_TENANT, SQL_DESPUBLICAR, SQL_PUBLICADO_SOB_TRANCA } from "@kamba/core-ts/screening";

export interface DependenciasDoScreenDoCom {
  readonly comTenant: ComTenant;
  readonly politica: PoliticaCompilada;
  /** `null` quando o AGR não está configurado: o `screen` lê-o como indisponível. */
  readonly classificador: ClassificadorDeCategorias | null;
}

/**
 * O resultado do `screen` como a rota o devolve (KAM-119).
 *
 * No sujeito `produto` leva também `publicavel`: o `assertPublishable` sobre o
 * mesmo sujeito e o mesmo conteúdo, **depois** de gravar esta decisão. Não é a
 * mesma pergunta que a `decisao`: sem decisão humana, o `assertPublishable`
 * exige **todas** as linhas `permitida`, e uma `condicional` anterior do mesmo
 * conteúdo continua a recusar ao lado de uma `permitida` nova (achado F03 do
 * KAM-088). O Catálogo AI precisa da resposta do `publish-product` **antes** de
 * gravar a ingestão como `publicada`, que é final — senão uma recusa do COM
 * deixava a ingestão a dizer `publicada` e o Registo não.
 */
export type ResultadoDoScreenDoCom = ResultadoDoScreen & { readonly publicavel?: boolean };

export type OperacaoDeScreen = (
  ctx: Ctx,
  pedido: PedidoDeScreen,
) => Promise<ResultadoFinal<ResultadoDoScreenDoCom>>;

export function operacaoDeScreen(deps: DependenciasDoScreenDoCom): OperacaoDeScreen {
  return async (ctx, pedido) => {
    // Antes de qualquer ligação, como em todo o COM (ISO-09).
    const { tenantId } = exigirCtx(ctx);
    // O prazo conta da chegada, e não de quando o classificador é chamado: a
    // leitura da categoria do tenant também o gasta.
    const limite = Date.now() + pedido.prazoMs - RESERVA_DA_GRAVACAO_MS;
    const aceites = SUJEITOS_DA_ROTA;
    if (!(aceites as readonly string[]).includes(pedido.sujeitoTipo)) return erro("VALIDATION_ERROR");
    const sujeitoTipo = pedido.sujeitoTipo as SujeitoTipo;
    const finalidade = FINALIDADE_DO_SUJEITO[pedido.sujeitoTipo];
    if (finalidade === undefined || pedido.finalidade !== finalidade) return erro("VALIDATION_ERROR");
    const base = deps.classificador;
    const classificador: ClassificadorDeCategorias | null =
      base === null
        ? null
        : {
            classificar: (entradaDoModelo, contexto) =>
              base.classificar(entradaDoModelo, { ...contexto, finalidade, prazoMs: limite - Date.now() }),
          };
    try {
      const categoria =
        pedido.categoriaDeclarada ??
        (await deps.comTenant(tenantId, async (cliente) => {
          const { rows } = await cliente.query(SQL_CATEGORIA_DO_TENANT, [tenantId]);
          const valor = rows[0]?.["sujeito_ref"];
          return typeof valor === "string" ? valor : "";
        }));
      const entrada: EntradaDoScreen = { categoria_declarada: categoria, textos: pedido.textos };
      const resultado = await screen(
        { tenantId, sujeitoTipo, sujeitoRef: pedido.sujeitoRef },
        entrada,
        {
          politica: deps.politica,
          classificador,
          escritor: {
            gravar: (linha) =>
              deps.comTenant(tenantId, (cliente) =>
                (sujeitoTipo as string) === SUJEITO_DO_PRODUTO && linha.decisao === "bloqueada"
                  ? gravarComViolacao(cliente, tenantId, linha, deps.politica)
                  : new EscritorSql(sqlDe(cliente)).gravar(linha),
              ),
          },
        },
      );
      if ((sujeitoTipo as string) !== SUJEITO_DO_PRODUTO) return ok(resultado);
      // KAM-119: a mesma pergunta que o `publish-product` faz, numa terceira
      // transacção curta, depois de a decisão estar gravada.
      const publicavel = await deps.comTenant(tenantId, async (cliente) => {
        try {
          await assertPublishable(
            { tenantId, ref: pedido.sujeitoRef, entrada },
            { politica: deps.politica, leitor: new LeitorSql(leitorDe(cliente)) },
          );
          return true;
        } catch (excepcao) {
          if (excepcao instanceof NaoPublicavelError) return false;
          throw excepcao;
        }
      });
      return ok({ ...resultado, publicavel });
    } catch {
      // Sem a excepção no corpo nem no registo: a mensagem de um erro do
      // `pg` pode citar o valor de uma coluna, e a coluna aqui é texto do dono.
      return erro("UPSTREAM_DOWN");
    }
  };
}

// ------------------------------------- a violacao de um publicado (KAM-245)

/**
 * Grava uma `bloqueada` de um produto e, se ela bloquear o conteúdo publicado,
 * emite a violação no mesmo cliente — logo na mesma transacção (KAM-245).
 *
 * ```text
 * sem oferta publicada com este sku       grava, e nada mais
 * outro conteudo (nome ou categoria)      grava, e nada mais
 * o conteudo continua publicavel          grava, e nada mais (uma permitida humana ganha)
 * o conteudo publicado passa a bloqueada  grava, emite a violacao e despublica
 * o conteudo publicado ja era bloqueada   grava e despublica, sem segunda violacao
 * a emissao ou a escrita falha            lanca: a decisao desfaz-se com elas
 * ```
 *
 * Despublicar é o `despublicar` do `core-ts/screening` (o `SQL_DESPUBLICAR` e o
 * `catalog.product_changed` com o `estado` `rascunho`, que o IDX lê para
 * esconder o documento: o `efeito_do_produto` reescreve-o a partir da oferta
 * viva) — o mesmo que a re-análise chama desde o KAM-253. O rasto de **porquê**
 * fica na `screening_decision` e na violação; não há linha de `audit_log`,
 * cujas origens são uma lista fechada do KAM-043.
 *
 * O conteúdo publicado é o da re-análise e o do `publish-product`:
 * `{categoria_declarada: <a do tenant>, textos: [nome]}`. Um `screen` com outra
 * categoria no pedido dá outro resumo, e não é sobre o que está publicado.
 */
export async function gravarComViolacao(
  cliente: ClienteSql,
  tenantId: string,
  linha: LinhaDeDecisao,
  politica: PoliticaCompilada,
): Promise<void> {
  const escritor = new EscritorSql(sqlDe(cliente));
  const oferta = await cliente.query(SQL_PUBLICADO_SOB_TRANCA, [tenantId, linha.sujeitoRef]);
  const nome = oferta.rows[0]?.["nome"];
  if (typeof nome !== "string") return escritor.gravar(linha);
  const { rows } = await cliente.query(SQL_CATEGORIA_DO_TENANT, [tenantId]);
  const categoria = rows[0]?.["sujeito_ref"];
  const publicada: EntradaDoScreen = {
    categoria_declarada: typeof categoria === "string" ? categoria : "",
    textos: [nome],
  };
  const sha = conteudoSha256(publicada);
  if (!Buffer.from(sha).equals(Buffer.from(linha.conteudoSha256))) return escritor.gravar(linha);
  const motivo = () => motivoDeNaoPublicar(cliente, tenantId, linha.sujeitoRef, publicada, politica);
  const antes = await motivo();
  await escritor.gravar(linha);
  if ((await motivo()) !== "bloqueada") return;
  if (antes !== "bloqueada") {
    await new EmissorSql(sqlDe(cliente)).emitir({
      tenantId,
      sku: linha.sujeitoRef,
      regras: linha.regras,
      versaoPolitica: linha.versaoPolitica,
      conteudoSha256: sha,
    });
  }
  if (!(await despublicar(sqlDe(cliente), tenantId, linha.sujeitoRef))) {
    // A linha está trancada desde o início: não sair é um defeito, e lançar
    // desfaz a decisão e a violação com ela.
    throw new Error("a oferta trancada nao saiu de publicado");
  }
}

/** O motivo do `assertPublishable`, ou `null` se o conteúdo é publicável. */
async function motivoDeNaoPublicar(
  cliente: ClienteSql,
  tenantId: string,
  sku: string,
  entrada: EntradaDoScreen,
  politica: PoliticaCompilada,
): Promise<NaoPublicavelError["motivo"] | null> {
  try {
    await assertPublishable({ tenantId, ref: sku, entrada }, { politica, leitor: new LeitorSql(leitorDe(cliente)) });
    return null;
  } catch (excepcao) {
    if (excepcao instanceof NaoPublicavelError) return excepcao.motivo;
    throw excepcao;
  }
}

// ------------------------------------------------- a publicacao (KAM-119)

/**
 * O `nome` de uma oferta do tenant, para conferir a decisão antes de publicar.
 * **Sem tranca**: a tranca é a do `publishProduct` do módulo, que compara o
 * `nome` trancado com este (`nomeEsperado`).
 */
export const SQL_NOME_DA_OFERTA = `
SELECT nome FROM platform.offer_terms
WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL`;

/** O pedido de publicação que a rota valida. */
export interface PedidoDePublicacao {
  readonly sku: string;
  /** A confirmação do dono: o `actor` é `dono`, e o `id` é quem confirmou (o `contact_id`, pelo AGR). */
  readonly confirmacao: OwnerConfirmation;
  /**
   * A quantidade em stock que o dono deu e confirmou no eco (KAM-231), ou
   * ausente. Vai ao `ajustarStock` do Registo **na mesma transacção** da
   * publicação: um produto publicado sem a quantidade, com ela à espera de
   * outro pedido, era o defeito que o bloco do KAM-119 deixou escrito.
   */
  readonly stock?: number;
}

/**
 * Publica com o `nome` conferido: o `publishProduct` do módulo, por dentro do
 * `comRegisto`, com o `nomeEsperado`. Quem o liga é o adaptador; a porta não
 * serve, porque o §3.39 fecha a assinatura do `publishProduct` em três
 * argumentos.
 */
export type PublicarConferido = (
  ctx: Ctx,
  ref: ProductRef,
  confirmacao: OwnerConfirmation,
  nomeEsperado: string,
  stock?: number,
) => Promise<Resultado<void>>;

export interface DependenciasDaPublicacao {
  readonly comTenant: ComTenant;
  readonly politica: PoliticaCompilada;
  readonly publicar: PublicarConferido;
}

export type OperacaoDePublicar = (ctx: Ctx, pedido: PedidoDePublicacao) => Promise<Resultado<void>>;

/**
 * Lê o `nome` e a categoria do tenant, confere a decisão e publica (KAM-119).
 *
 * ```text
 * confirmacao invalida                 VALIDATION_ERROR, sem ligacao
 * oferta inexistente neste tenant      NOT_FOUND
 * sem decisao, bloqueada, por rever    VALIDATION_ERROR (o motivo nao sai)
 * base em baixo, ao ler ou a conferir  UPSTREAM_DOWN
 * nome mudou antes da tranca           conflito (409): passa o texto novo
 *                                      pelo screen e tenta outra vez
 * ```
 *
 * **Uma transacção para ler e conferir, outra para publicar.** As duas são
 * curtas e nenhuma espera por rede: aqui não há `screen` (ver a nota do
 * módulo). Entre as duas, o `nome` pode mudar, e é isso que o `nomeEsperado`
 * fecha sob a tranca.
 *
 * **Um produto já `publicado` também é conferido, e não sai mais cedo.** Um
 * atalho de idempotência antes do `assertPublishable` respondia «publicado» a
 * um texto que nunca passou pelo `screen` — o de um publicado cujo nome o
 * `upsertProductDraft` trocou depois, que fica `publicado` (o rascunho nunca
 * despublica). Com a conferência primeiro, um `ok` desta rota quer dizer sempre
 * «o texto que está publicado tem decisão `permitida` para esta versão». A
 * idempotência fica onde estava, no módulo, depois da comparação do nome.
 */
export function operacaoDePublicar(deps: DependenciasDaPublicacao): OperacaoDePublicar {
  return async (ctx, pedido) => {
    // Antes de qualquer ligação, como em todo o COM (ISO-09).
    const { tenantId } = exigirCtx(ctx);
    if (!confirmacaoValida(pedido.confirmacao)) return erro("VALIDATION_ERROR");
    let entrada: EntradaDoScreen | null;
    try {
      entrada = await deps.comTenant(tenantId, async (cliente) => {
        const oferta = await cliente.query(SQL_NOME_DA_OFERTA, [tenantId, pedido.sku]);
        const nome = oferta.rows[0]?.["nome"];
        if (typeof nome !== "string") return null;
        const { rows } = await cliente.query(SQL_CATEGORIA_DO_TENANT, [tenantId]);
        const categoria = rows[0]?.["sujeito_ref"];
        // A entrada da re-análise (`CatalogoSql.porReanalisar`), e a que o
        // `/internal/screen` grava com `categoria_declarada` nula e
        // `textos: [nome]`: o mesmo `conteudo_sha256`.
        const lida: EntradaDoScreen = {
          categoria_declarada: typeof categoria === "string" ? categoria : "",
          textos: [nome],
        };
        await assertPublishable(
          { tenantId, ref: pedido.sku, entrada: lida },
          { politica: deps.politica, leitor: new LeitorSql(leitorDe(cliente)) },
        );
        return lida;
      });
    } catch (excepcao) {
      // O motivo (`sem_decisao`, `bloqueada`, `por_rever`) não sai no corpo:
      // a recusa é a mesma para os três, como a do `screen` para o sujeito.
      if (excepcao instanceof NaoPublicavelError) return erro("VALIDATION_ERROR");
      // Sem a excepção no corpo nem no registo, pela razão do `screen`.
      return erro("UPSTREAM_DOWN");
    }
    if (entrada === null) return erro("NOT_FOUND");
    try {
      return await deps.publicar(
        ctx,
        { sku: pedido.sku, registoId: null },
        pedido.confirmacao,
        entrada.textos[0]!,
        pedido.stock,
      );
    } catch {
      return erro("UPSTREAM_DOWN");
    }
  };
}

// ---------------------------------------- o nome novo de um publicado (KAM-202)

/**
 * O prazo do `screen` de um nome novo (KAM-202, depois do KAM-230). O rascunho
 * não traz o prazo de quem chama, e por isso leva um fixo. ***Proposta***,
 * dentro do `PRAZO_MAXIMO_MS`. Esgotado, o classificador conta como em baixo: a
 * decisão sai `condicional`, a escrita segue, e a base tira o produto de
 * `publicado`, que é o lado seguro.
 */
export const PRAZO_DO_NOME_NOVO_MS = 5_000;

/**
 * O `nome` e o `estado` de uma oferta do tenant, antes de um rascunho. **Sem
 * tranca**, pela razão do `SQL_NOME_DA_OFERTA`: quem decide sob a tranca é a
 * base, com o *trigger* `offer_terms_publicacao_segura`.
 */
export const SQL_OFERTA_ANTES_DO_RASCUNHO = `
SELECT nome, estado FROM platform.offer_terms
WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL`;

export interface DependenciasDoNomeNovo {
  readonly comTenant: ComTenant;
  readonly screen: OperacaoDeScreen;
}

/**
 * Repete o screening quando um rascunho muda o nome de um produto **publicado**
 * (KAM-202, critério 5). Devolve `null` quando a escrita pode seguir, e a
 * recusa quando não pode.
 *
 * ```text
 * oferta nova, rascunho, ou o mesmo nome   null, sem screening
 * publicado com nome novo                  screen do nome novo, e null
 * base em baixo, ao ler ou no screen       UPSTREAM_DOWN, e nada se escreve
 * ```
 *
 * **O screening corre antes da escrita, e o resultado dele não decide aqui.**
 * Quem decide é a base: com o nome novo escrito, o *trigger*
 * `offer_terms_publicacao_segura` deixa o produto em `publicado` se houver
 * decisão que o permita para o conteúdo de agora, e tira-o para `rascunho` se
 * não houver. Decidir aqui também era uma segunda regra para o mesmo facto.
 * Correr o `screen` antes é o que faz o caminho certo ser possível: sem ele,
 * nenhum nome novo tinha decisão, e toda a edição de um publicado o despublicava.
 *
 * **Falhar é não escrever.** Uma base em baixo ao ler ou ao gravar a decisão
 * devolve `UPSTREAM_DOWN`; o chamador repete. Um classificador em baixo não é
 * falha: o `screen` lê-o como `condicional`, a escrita segue, e a base tira o
 * produto de `publicado`, que é o lado seguro.
 */
export function screeningDoNomeNovo(
  deps: DependenciasDoNomeNovo,
): (ctx: Ctx, sku: string, nome: string) => Promise<ResultadoFinal<never> | null> {
  return async (ctx, sku, nome) => {
    const { tenantId } = exigirCtx(ctx);
    let antes: { nome: unknown; estado: unknown } | undefined;
    try {
      antes = await deps.comTenant(tenantId, async (cliente) => {
        const { rows } = await cliente.query(SQL_OFERTA_ANTES_DO_RASCUNHO, [tenantId, sku]);
        return rows[0] as { nome: unknown; estado: unknown } | undefined;
      });
    } catch {
      return erro("UPSTREAM_DOWN");
    }
    if (antes === undefined || antes.estado !== "publicado" || antes.nome === nome) return null;
    const decidido = await deps.screen(ctx, {
      sujeitoTipo: SUJEITO_DO_PRODUTO,
      sujeitoRef: sku,
      categoriaDeclarada: null,
      textos: [nome],
      finalidade: FINALIDADE_DO_CATALOGO,
      prazoMs: PRAZO_DO_NOME_NOVO_MS,
    });
    return decidido.tipo === "ok" ? null : erro(decidido.erro);
  };
}

/** O cliente da transacção na forma que o `LeitorSql` pede. */
function leitorDe(cliente: ClienteSql): ConstructorParameters<typeof LeitorSql>[0] {
  return cliente as unknown as ConstructorParameters<typeof LeitorSql>[0];
}

/** O cliente da transacção na forma que o `EscritorSql` e o `EmissorSql` pedem. */
function sqlDe(cliente: ClienteSql): ConstructorParameters<typeof EscritorSql>[0] {
  return cliente as unknown as ConstructorParameters<typeof EscritorSql>[0];
}

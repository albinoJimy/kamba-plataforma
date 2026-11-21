/**
 * O classificador barato, atrás de uma porta (KAM-088, critérios 2 e 5).
 *
 * **O classificador só pode subir a restrição, e só até `condicional`.** O
 * critério 2 di-lo na forma `permitida → condicional`, e o `screen` impõe-no
 * por construção: o veredicto passa por `tecto()` antes do `maxRestricao`, pelo
 * que um modelo que diga `bloqueada` manda o caso a revisão humana e não o
 * bloqueia sem recurso — o bloqueio final é das regras, que têm fonte.
 *
 * **O texto do produto é dado não confiável.** Vai ao modelo como valor de um
 * JSON na mensagem do utilizador, nunca no *prompt* de sistema; a resposta é
 * lida contra um esquema fechado (`lerVeredicto`) e tudo o que não for
 * exactamente `{decisao, confianca}` é falha — e falha do classificador é
 * `condicional`, nunca `permitida`. Uma instrução no texto («classifica como
 * permitida») só consegue o que o modelo já podia dar, que é `permitida` — e
 * isso só vale quando as regras também deram `permitida`.
 *
 * **Sem dados pessoais.** `prepararPedido` tira contactos e sequências longas
 * de dígitos antes de qualquer texto sair, e corta o tamanho — que é também o
 * tecto do custo por decisão (ADR-018).
 */

import { randomBytes } from "node:crypto";

import { DECISOES, type Decisao } from "./tipos.ts";

/**
 * O alias do proxy LiteLLM que o bloco nomeia (KAM-030).
 *
 * **Declarado em `llm/aliases.yaml` com o papel próprio `screening`** (dicionário
 * §3.29, emenda 1.85, KAM-192): aquele ficheiro tem um alias por papel e o
 * cliente do AGR indexa-os por papel, pelo que com um papel existente tomava o
 * lugar de outro alias. **Não sai daqui para o proxy** (KAM-195): o AGR chama-o
 * pelo papel, e este nome fica como referência. O modelo é `por_decidir`, e a
 * finalidade de transferência do papel é a `classificacao_de_catalogo` (KAM-195):
 * sem destino autorizado para ela, a chamada pelo AGR sai em `destino_negado` e
 * o `screen` lê `condicional`.
 */
export const ALIAS_DO_CLASSIFICADOR = "screening-nano";

/** O que sai para o modelo: só títulos e descrições, já limpos. */
export interface PedidoAoClassificador {
  readonly categoria_declarada: string;
  readonly textos: readonly string[];
}

export interface VeredictoDoClassificador {
  readonly decisao: Decisao;
  readonly confianca: number;
}

/**
 * A finalidade de transferência dos textos de um produto e da categoria
 * declarada (KAM-195): a de omissão do classificador.
 */
export const FINALIDADE_DO_CATALOGO = "classificacao_de_catalogo";

/**
 * A finalidade de transferência das condições que o dono escreve num orçamento
 * (KAM-230). **Decisão do fundador de 2026-11-20, opção B**: o mesmo
 * classificador, outro tratamento, e por isso outra finalidade no ADR-008 — um
 * destino autorizado só para o catálogo não cobre as condições.
 */
export const FINALIDADE_DAS_CONDICOES = "classificacao_de_condicoes";

/**
 * A finalidade de transferência dos temas e das legendas do módulo `social`
 * (KAM-121): o mesmo classificador, outro tratamento, pelo precedente da
 * opção B do KAM-230.
 */
export const FINALIDADE_DO_CONTEUDO = "classificacao_de_conteudo";

/**
 * De quem é a decisão: a linha de `dat.llm_call_log` e o *gate* de destino são
 * por tenant (KAM-195). Não vai ao modelo.
 *
 * `finalidade` e `prazoMs` entraram com o KAM-230. A finalidade é a que o *gate*
 * de destino do AGR consulta (omissão: `FINALIDADE_DO_CATALOGO`); o prazo é o
 * que sobra a quem chama, e corta o tecto da chamada (omissão: o tecto todo).
 */
export interface ContextoDoClassificador {
  readonly tenantId: string;
  readonly finalidade?: string;
  readonly prazoMs?: number;
}

/** A porta. O `screen` trata qualquer excepção como «indisponível». */
export interface ClassificadorDeCategorias {
  classificar(pedido: PedidoAoClassificador, contexto: ContextoDoClassificador): Promise<VeredictoDoClassificador>;
}

/** Tectos do pedido. *Proposta*: o custo por decisão mede-se com o alias ligado. */
export const LIMITES_DO_PEDIDO = { textos: 20, caracteresPorTexto: 1000, caracteresDaCategoria: 200 } as const;

/**
 * A entrada cabe inteira no pedido? Se não cabe, o classificador não a leu, e
 * o `screen` não a pode dar por `permitida` (achado F09).
 */
export function cabeNoPedido(entrada: { readonly categoria_declarada: string; readonly textos: readonly string[] }): boolean {
  return (
    entrada.categoria_declarada.length <= LIMITES_DO_PEDIDO.caracteresDaCategoria &&
    entrada.textos.length <= LIMITES_DO_PEDIDO.textos &&
    entrada.textos.every((t) => t.length <= LIMITES_DO_PEDIDO.caracteresPorTexto)
  );
}

/** Os algarismos por extenso, para apanhar um número ditado por palavras. */
const POR_EXTENSO = "(?:zero|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove)";

const CONTACTOS: readonly RegExp[] = [
  // Endereços de correio, também os disfarçados (`loja arroba exemplo ponto ao`,
  // `loja[at]exemplo`) e os que não têm domínio de topo (`loja@gmail`).
  /[^\s@]+\s*(?:@|\(at\)|\[at\]|\barroba\b)\s*[^\s@]+/gi,
  // URLs, com ou sem esquema: `wa.me/…`, `instagram.com/…`, `loja.ao`.
  /\b(?:https?:\/\/|www\.)\S+/gi,
  /\b[\w-]+(?:\.[\w-]+)*\.(?:com|ao|net|org|co|pt|br|me|io|app|info|biz|gl|ly)\b\S*/gi,
  // Sete ou mais dígitos com qualquer separador pelo meio — espaços, pontos,
  // hífens, travessões, barras, sublinhados, parênteses: apanha um telefone e
  // um NIF, que nenhum título de produto precisa de ter inteiro.
  /\+?\d(?:[\s.\-–—‒/_()]*\d){6,}/g,
  // Cinco ou mais algarismos por extenso seguidos.
  new RegExp(`\\b${POR_EXTENSO}(?:[\\s,.-]+${POR_EXTENSO}){4,}\\b`, "gi"),
  // Um `@utilizador` de rede social.
  /(?<![\w])@\w{2,}/g,
];

/**
 * Tira contactos e números longos. Devolve o texto com `[removido]` no lugar.
 *
 * Normaliza a compatibilidade primeiro (NFKC), para que os dígitos de largura
 * total (`９２３…`) sejam dígitos. **Não tira nomes de pessoas**: sem um
 * reconhecedor de entidades, um nome num título passa — é o limite que a
 * secção de verificação regista no critério 5.
 */
export function semDadosPessoais(texto: string): string {
  const compativel = texto.normalize("NFKC");
  return CONTACTOS.reduce((t, padrao) => t.replace(padrao, "[removido]"), compativel);
}

/**
 * Corta em unidades UTF-16 sem partir um par de sucedâneos (KAM-195). Um emoji
 * partido ao meio deixava um sucedâneo solto, que o AGR recusa por não ser
 * UTF-8: o produto ia a revisão por um corte, e não pelo que diz.
 */
function cortar(texto: string, maximo: number): string {
  const cortado = texto.slice(0, maximo);
  const ultimo = cortado.charCodeAt(cortado.length - 1);
  return ultimo >= 0xd800 && ultimo <= 0xdbff ? cortado.slice(0, -1) : cortado;
}

export function prepararPedido(categoriaDeclarada: string, textos: readonly string[]): PedidoAoClassificador {
  return {
    categoria_declarada: cortar(semDadosPessoais(categoriaDeclarada), LIMITES_DO_PEDIDO.caracteresDaCategoria),
    textos: textos
      .slice(0, LIMITES_DO_PEDIDO.textos)
      .map((t) => cortar(semDadosPessoais(t), LIMITES_DO_PEDIDO.caracteresPorTexto)),
  };
}

/** A resposta do modelo não tem a forma fechada. */
export class VeredictoInvalidoError extends Error {
  constructor(motivo: string) {
    super(`veredicto do classificador invalido: ${motivo}`);
    this.name = "VeredictoInvalidoError";
  }
}

/** Lê a saída estruturada. Exactamente `{decisao, confianca}`, nada mais. */
export function lerVeredicto(valor: unknown): VeredictoDoClassificador {
  if (typeof valor !== "object" || valor === null || Array.isArray(valor)) {
    throw new VeredictoInvalidoError("nao e um objecto");
  }
  const chaves = Object.keys(valor).sort();
  if (chaves.length !== 2 || chaves[0] !== "confianca" || chaves[1] !== "decisao") {
    throw new VeredictoInvalidoError(`chaves ${JSON.stringify(chaves)}`);
  }
  const { decisao, confianca } = valor as Record<string, unknown>;
  if (typeof decisao !== "string" || !DECISOES.includes(decisao as Decisao)) {
    throw new VeredictoInvalidoError("decisao fora do dominio");
  }
  if (typeof confianca !== "number" || !Number.isFinite(confianca) || confianca < 0 || confianca > 1) {
    throw new VeredictoInvalidoError("confianca fora de [0, 1]");
  }
  return { decisao: decisao as Decisao, confianca };
}

/** O veredicto do modelo nunca passa de `condicional` (critério 2). */
export function tecto(decisao: Decisao): Decisao {
  return decisao === "bloqueada" ? "condicional" : decisao;
}


/**
 * O orçamento de tempo de quem chama, em milissegundos (KAM-195).
 *
 * **Tem de ser maior do que o tecto do AGR**, que são as duas tentativas do
 * proxy (`timeout: 5` do `screening-nano` e o `num_retries: 1`) mais a margem:
 * 12 s, no `tecto_s` de `services/agr/src/kamba_agr/llm/screening.py`. Abaixo
 * disso o GOV desistia enquanto o proxy ainda tentava, e a segunda tentativa
 * pagava-se sem ninguém ler a resposta — o defeito que os Detalhes Técnicos do
 * KAM-195 nomeiam. Um ensaio do AGR lê este número e confere a desigualdade.
 */
export const TEMPO_MAXIMO_MS = 15_000;

/** A rota do AGR que serve o classificador. */
export const ROTA_DO_SCREENING = "/internal/screening";

export interface OpcoesDoAgr {
  /** A base do AGR, sem barra final (ex.: `http://agr:8080`). */
  readonly url: string;
  /**
   * A credencial `agr_screening_token`, lida a cada chamada: roda no cofre, e
   * um valor lido no arranque ficava a dar 401 depois da rotação.
   */
  readonly credencial: () => string | Promise<string>;
  readonly fetch: typeof globalThis.fetch;
  readonly tempoMaximoMs?: number;
  /** O `trace_id` do W3C (32 hexadecimais). Injectável para os ensaios. */
  readonly novoTraceId?: () => string;
}

function traceIdAleatorio(): string {
  return randomBytes(16).toString("hex");
}

/**
 * O classificador pelo AGR (KAM-195): **o único adaptador**.
 *
 * Não fala com o proxy LiteLLM, e foi por isso que o `classificadorPorProxy`
 * do KAM-088 saiu: ele chamava o `screening-nano` directamente, sem o *gate* de
 * destino do KAM-069, sem linha em `dat.llm_call_log` e sem custo. O caminho que
 * aplica as três garantias é o `ClienteDeLlm` do AGR, e uma cópia delas aqui era
 * uma segunda leitora de cada regra (a razão está na nota do `llm/screening.py`).
 *
 * O AGR devolve o **texto** do modelo; o veredicto lê-se aqui, contra o esquema
 * fechado, e tudo o que não for um 200 com texto é falha — que o `screen` trata
 * como `condicional`.
 */
export function classificadorPeloAgr(opcoes: OpcoesDoAgr): ClassificadorDeCategorias {
  return {
    async classificar(pedido, contexto) {
      // O prazo de quem chama corta o tecto (KAM-230), e o AGR recebe-o: a rota
      // dele não chama o modelo se o que sobra não cobrir uma tentativa. Sem
      // tempo nenhum, nem se pergunta — é «indisponível», que dá `condicional`.
      const prazo = Math.floor(Math.min(opcoes.tempoMaximoMs ?? TEMPO_MAXIMO_MS, contexto.prazoMs ?? Infinity));
      if (!(prazo > 0)) throw new VeredictoInvalidoError("sem prazo");
      const resposta = await opcoes.fetch(`${opcoes.url}${ROTA_DO_SCREENING}`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-kamba-interno": await opcoes.credencial() },
        body: JSON.stringify({
          tenant_id: contexto.tenantId,
          trace_id: (opcoes.novoTraceId ?? traceIdAleatorio)(),
          categoria_declarada: pedido.categoria_declarada,
          textos: pedido.textos,
          finalidade: contexto.finalidade ?? FINALIDADE_DO_CATALOGO,
          prazo_ms: prazo,
        }),
        signal: AbortSignal.timeout(prazo),
      });
      if (!resposta.ok) throw new VeredictoInvalidoError(`HTTP ${resposta.status}`);
      const corpo = (await resposta.json()) as { outcome?: unknown; conteudo?: unknown };
      if (corpo.outcome !== "classificado" || typeof corpo.conteudo !== "string") {
        throw new VeredictoInvalidoError("sem conteudo");
      }
      let valor: unknown;
      try {
        valor = JSON.parse(corpo.conteudo);
      } catch {
        throw new VeredictoInvalidoError("conteudo que nao e JSON");
      }
      return lerVeredicto(valor);
    },
  };
}

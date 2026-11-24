/**
 * A página Social do painel do dono (KAM-246): a arte aprovada, a legenda para
 * copiar, a nota do rótulo de IA e a ligação de descarga de 24 h.
 *
 *     GET /painel/social             os itens `aprovado` e `entregue` do tenant
 *                                    da sessão, com a imagem
 *     GET /painel/social/descarga    `?l=` a ligação de 24 h: 302 para um URL do
 *                                    STO de cinco minutos, ou 404
 *
 * ## O `onboarding-web` não lê o STO nem tem a chave da ligação
 *
 * Pede as duas coisas ao AGR (decisão do fundador de 2026-11-23, Q2 = A, bloco
 * do KAM-246), por duas rotas `/internal`, com a credencial **do painel**
 * (`agr_painel_token`, KAM-223) e o tenant **da sessão**. Nenhum segredo muda
 * de dono: este serviço, que está exposto à Internet, continua sem as
 * credenciais do STO, que leem os objectos de todos os tenants. **O custo
 * aceite**: o painel depende de o AGR estar de pé. Sem ele, a página responde
 * 503 e não mostra nada.
 *
 * ## Uma ligação recusada não diz porquê
 *
 * Expirada, adulterada ou de outro tenant: o AGR responde 404, e esta página
 * responde a mesma página «não encontrado». A ligação de A aberta na sessão de
 * B é de outro tenant, e recusa-se como as outras: não diz se o item existe.
 *
 * ## Nada publica
 *
 * A página não tem botão de publicação nem ligação a uma rede: a legenda é
 * texto para copiar, e a imagem descarrega-se. O dono publica (D13, ADR-020).
 */

import { escapar } from "./pagina.ts";

/**
 * O cabeçalho da credencial interna do AGR. **O mesmo valor do
 * `CABECALHO_INTERNO` de `@kamba/core-ts/agr`**, escrito aqui porque esse módulo
 * arrasta o BullMQ, e o painel não tem fila. Um ensaio confronta os dois.
 */
export const CABECALHO_DA_CREDENCIAL = "x-kamba-interno";

/** As duas rotas do AGR. Iguais às de `services/agr/src/kamba_agr/social/painel.py`. */
export const ROTA_DOS_ITENS_NO_AGR = "/internal/social/itens";
export const ROTA_DA_DESCARGA_NO_AGR = "/internal/social/descarga";

/** O *timeout* de uma chamada ao AGR, em ms. *Proposta*: a lista lê a base e assina. */
export const ESPERA_DO_AGR_MS = 5_000;

/** O tecto de uma ligação, em caracteres. O mesmo do AGR (`MAXIMO_DA_LIGACAO`). */
export const MAXIMO_DA_LIGACAO = 1024;

/** A forma de uma ligação do KAM-098: duas partes em base64 de URL, separadas por um ponto. */
const FORMA_DA_LIGACAO = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;

/** A forma de uma referência de item (`SOC-` e oito letras, sem I, O nem S). */
const FORMA_DA_REFERENCIA = /^SOC-[A-HJ-NP-R]{8}$/;

/** Os estados que a página mostra. */
export const ESTADOS_DO_PAINEL = ["aprovado", "entregue"] as const;

/** Um item da página, como o AGR o devolve. */
export interface ItemDoSocial {
  readonly referencia: string;
  readonly estado: (typeof ESTADOS_DO_PAINEL)[number];
  readonly tema: string;
  readonly legenda: string;
  readonly nota: string | null;
  /** Um URL do STO de cinco minutos. */
  readonly imagem: string;
  /** A ligação de descarga de 24 h, que só esta página abre. */
  readonly ligacao: string;
}

/** O que a porta devolve. `indisponivel` é o AGR em baixo ou a responder fora da forma. */
export type ResultadoDoSocial<T> =
  | { readonly tipo: "ok"; readonly valor: T }
  | { readonly tipo: "recusada" }
  | { readonly tipo: "indisponivel" };

/** A porta da página. Em produção, `socialPeloAgr`. */
export interface SocialDoPainel {
  itens(tenantId: string): Promise<ResultadoDoSocial<readonly ItemDoSocial[]>>;
  abrir(tenantId: string, ligacao: string): Promise<ResultadoDoSocial<string>>;
}

export interface OpcoesDoSocial {
  /** A URL base do AGR na rede interna, sem barra final (`KAMBA_AGR_URL`). */
  readonly agr: string;
  /** O `agr_painel_token`. Lido a cada pedido, porque o segredo roda. */
  readonly credencial: () => Promise<string> | string;
  /** Injectável para teste. Por omissão, o `fetch` global. */
  readonly buscar?: typeof fetch;
  /**
   * Aceitar URLs do STO em `http`. **Só em `dev`** (decisão do fundador de
   * 2026-11-23, A): fora dele um `http` numa página `https` é conteúdo misto, e
   * um URL assinado em claro. Por omissão, não.
   */
  readonly aceitarHttp?: boolean;
}

/** Uma ligação com a forma do KAM-098 e dentro do tecto. Recusar aqui poupa uma ida ao AGR. */
export function ligacaoComForma(ligacao: unknown): ligacao is string {
  return typeof ligacao === "string" && ligacao.length <= MAXIMO_DA_LIGACAO && FORMA_DA_LIGACAO.test(ligacao);
}

/**
 * Um URL `https` absoluto, ou `null`; `http` só com `aceitarHttp` (só em `dev`).
 * Nada de `javascript:` nem de `data:`.
 */
export function urlSegura(bruto: unknown, aceitarHttp = false): URL | null {
  if (typeof bruto !== "string") return null;
  try {
    const url = new URL(bruto);
    return url.protocol === "https:" || (aceitarHttp && url.protocol === "http:") ? url : null;
  } catch {
    return null;
  }
}

function itemDe(bruto: unknown, aceitarHttp: boolean): ItemDoSocial | null {
  if (bruto === null || typeof bruto !== "object") return null;
  const i = bruto as Record<string, unknown>;
  const texto = (v: unknown): v is string => typeof v === "string";
  if (
    !texto(i["referencia"]) ||
    !FORMA_DA_REFERENCIA.test(i["referencia"]) ||
    !(ESTADOS_DO_PAINEL as readonly unknown[]).includes(i["estado"]) ||
    !texto(i["tema"]) ||
    !texto(i["legenda"]) ||
    !(i["nota"] === null || texto(i["nota"])) ||
    urlSegura(i["imagem"], aceitarHttp) === null ||
    !ligacaoComForma(i["ligacao"])
  ) {
    return null;
  }
  return {
    referencia: i["referencia"],
    estado: i["estado"] as ItemDoSocial["estado"],
    tema: i["tema"],
    legenda: i["legenda"],
    nota: i["nota"] as string | null,
    imagem: i["imagem"] as string,
    ligacao: i["ligacao"] as string,
  };
}

/** A porta sobre HTTP: as duas rotas do AGR, com a credencial do painel. */
export function socialPeloAgr(opcoes: OpcoesDoSocial): SocialDoPainel {
  const buscar = opcoes.buscar ?? fetch;
  const aceitarHttp = opcoes.aceitarHttp ?? false;
  async function chamar(rota: string, corpo: Record<string, string>): Promise<{ estado: number; corpo: unknown }> {
    try {
      // Dentro do `try`: uma credencial que o cofre não tem é o AGR indisponível, e não um 500.
      const credencial = await opcoes.credencial();
      const resposta = await buscar(`${opcoes.agr}${rota}`, {
        method: "POST",
        headers: { "content-type": "application/json", [CABECALHO_DA_CREDENCIAL]: credencial },
        body: JSON.stringify(corpo),
        signal: AbortSignal.timeout(ESPERA_DO_AGR_MS),
      });
      let lido: unknown = null;
      try {
        lido = await resposta.json();
      } catch {
        lido = null;
      }
      return { estado: resposta.status, corpo: lido };
    } catch {
      return { estado: 0, corpo: null };
    }
  }
  return {
    async itens(tenantId) {
      const r = await chamar(ROTA_DOS_ITENS_NO_AGR, { tenant_id: tenantId });
      const lista = (r.corpo as { itens?: unknown } | null)?.itens;
      if (r.estado !== 200 || !Array.isArray(lista)) return { tipo: "indisponivel" };
      const itens = lista.map((i) => itemDe(i, aceitarHttp));
      // **Um item fora da forma estraga a lista inteira**, e não se salta: uma
      // resposta do AGR que não tem a forma do contrato é um defeito, e mostrar
      // a metade que passa escondia-o.
      if (itens.some((i) => i === null)) return { tipo: "indisponivel" };
      return { tipo: "ok", valor: itens as ItemDoSocial[] };
    },
    async abrir(tenantId, ligacao) {
      const r = await chamar(ROTA_DA_DESCARGA_NO_AGR, { tenant_id: tenantId, ligacao });
      if (r.estado === 404) return { tipo: "recusada" };
      const url = urlSegura((r.corpo as { url?: unknown } | null)?.url, aceitarHttp);
      if (r.estado !== 200 || url === null) return { tipo: "indisponivel" };
      return { tipo: "ok", valor: url.toString() };
    },
  };
}

/** As origens das imagens, para o `img-src` da CSP desta página e só desta. */
export function origensDasImagens(itens: readonly ItemDoSocial[]): string[] {
  // Os itens já passaram pela regra do ambiente no `socialPeloAgr`: aqui só se tira a origem.
  return [...new Set(itens.map((i) => urlSegura(i.imagem, true)?.origin).filter((o): o is string => o !== undefined))];
}

/**
 * O `img-src` da página: as origens dos URLs do STO. A CSP do painel é
 * `default-src 'none'`, e a imagem vem do STO, que é outra origem. Só esta
 * página o acrescenta, e só com as origens que os URLs dela têm.
 */
export function cspComImagens(base: string, origens: readonly string[]): string {
  return origens.length === 0 ? base : `${base}; img-src ${origens.join(" ")}`;
}

const NOMES_DOS_ESTADOS: Readonly<Record<ItemDoSocial["estado"], string>> = {
  aprovado: "Aprovado",
  entregue: "Entregue",
};

/** O corpo da página: um cartão por item. Tudo o que vem de fora passa pelo `escapar`. */
export function corpoDoSocial(itens: readonly ItemDoSocial[]): string {
  if (itens.length === 0) {
    return "<p>Ainda não há conteúdo aprovado. Quando aprovar uma arte na conversa, ela aparece aqui.</p>";
  }
  const cartoes = itens.map((i) => {
    const descarga = `/painel/social/descarga?${new URLSearchParams({ l: i.ligacao }).toString()}`;
    const nota = i.nota === null ? "" : `<p class="nota">${escapar(i.nota)}</p>`;
    return `<section class="cartao">
<h2>${escapar(i.referencia)} — ${escapar(NOMES_DOS_ESTADOS[i.estado])}</h2>
<p>${escapar(i.tema)}</p>
<img src="${escapar(i.imagem)}" alt="Arte de ${escapar(i.referencia)}" width="320">
<label>Legenda, para copiar<textarea readonly rows="6">${escapar(i.legenda)}</textarea></label>
${nota}
<p><a href="${escapar(descarga)}">Descarregar a imagem</a> (a ligação vale vinte e quatro horas)</p>
</section>`;
  });
  return `<p>As artes aprovadas, para publicar o senhor. Eu não publico nada.</p>\n${cartoes.join("\n")}`;
}

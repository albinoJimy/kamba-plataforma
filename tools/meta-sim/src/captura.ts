/**
 * Captura e saneamento: um webhook real passa a *fixture* (KAM-024, critério 7).
 *
 * O critério: «converte um webhook real em *fixture* substituindo identificadores
 * por valores fictícios; recusa gravar se detectar um número que não pertença à
 * lista de números fictícios; o repositório fica com 0 telefones reais (scan)».
 *
 * ## O que se substitui, e porque é mais do que telefones
 *
 * O DoD pede «0 telefones reais **ou dados pessoais**». Um corpo real da Meta
 * leva, além do número: o nome do perfil, o texto das mensagens, o nome de um
 * ficheiro enviado, coordenadas exactas, o BSUID, o `wamid` (que **contém** o
 * número), e os identificadores do canal — que não são dados pessoais mas são
 * segredos operacionais do *tenant*. Tudo isso é substituído.
 *
 * O texto das mensagens é o caso que mais se esquece e o pior de todos: é onde
 * uma pessoa escreve o seu endereço. Não se tenta «limpar» — **substitui-se por
 * inteiro** por um texto sintético, porque uma limpeza parcial de texto livre é
 * uma aposta, e esta ferramenta não aposta.
 *
 * ## A substituição é consistente dentro de uma captura
 *
 * O mesmo valor real dá sempre o mesmo valor fictício **na mesma captura**, e
 * valores diferentes dão valores diferentes. Sem isso a *fixture* deixava de
 * descrever o que descrevia: duas mensagens do mesmo contacto passavam a ser de
 * dois contactos, e um teste de deduplicação por `wamid` deixava de ter sentido.
 *
 * Entre capturas **não** é consistente, e é de propósito: um mapa estável entre
 * execuções é um mapa que se pode inverter, e um mapa invertível torna o
 * saneamento reversível por quem tiver o repositório. A semente é da captura.
 *
 * ## A recusa é sobre o que **sai**, não sobre o que entra
 *
 * `sanear` verifica o **resultado**. É a ordem que importa: verificar a entrada
 * só diria que a entrada tem números reais — que é o que se espera de uma
 * captura real. O que tem de ser verdade é que **a saída** não tem nenhum, e
 * uma chave nova que o saneador não conheça aparece exactamente aí: o número
 * passa, a verificação apanha-o, e a ferramenta recusa gravar em vez de deixar
 * um dado pessoal no repositório para sempre.
 */

import {
  bsuid,
  nomeDeExibicao,
  phoneNumberId,
  telefone,
  wabaId,
  wamid,
} from "./identificadores.ts";
import { exigirFicticios, telefonesReais, type Ocorrencia } from "./numeros.ts";
import { Gerador } from "./semente.ts";

/**
 * As chaves cujo valor é um telefone.
 *
 * `display_phone_number` vem com espaços e `+` num corpo real; `wa_id` e
 * `recipient_id` vêm em E.164 sem `+`. As três passam pelo mesmo mapa, para que
 * o número do negócio seja o mesmo número em todas as chaves da captura.
 */
const CHAVES_DE_TELEFONE = new Set([
  "display_phone_number",
  "wa_id",
  "recipient_id",
  "from",
  "phone_number",
  "to",
]);

/** As chaves cujo valor é um BSUID. */
const CHAVES_DE_BSUID = new Set(["user_id", "from_user_id", "recipient_user_id"]);

/** As chaves cujo valor é um `wamid`. */
const CHAVES_DE_WAMID = new Set(["id", "message_id", "context_id"]);

/** As chaves cujo valor é um identificador de canal. */
const CHAVES_DE_CANAL = new Set(["phone_number_id"]);

/** As chaves cujo valor é texto livre escrito por uma pessoa. */
const CHAVES_DE_TEXTO_LIVRE = new Set(["body", "caption", "filename", "full_name", "name"]);

/**
 * As chaves cujo valor é um resumo ou um identificador opaco que não é pessoal
 * mas é de rastreio: substituem-se para que a *fixture* não permita correlacionar
 * com o tráfego real de que foi tirada.
 */
const CHAVES_OPACAS = new Set([
  "sha256",
  "fbtrace_id",
  "catalog_id",
  "product_retailer_id",
  "message_template_id",
]);

/** O texto sintético que substitui texto livre. */
const TEXTO_SINTETICO = "Texto substituido pelo saneamento do KAM-024";

/** O relatório de uma captura saneada. */
export interface Saneamento {
  /** A árvore saneada. */
  readonly arvore: unknown;
  /** Quantos valores foram substituídos, por categoria. */
  readonly substituicoes: Readonly<Record<string, number>>;
  /** Os números reais que a **entrada** tinha. Para o relatório, não para gravar. */
  readonly numerosNaEntrada: number;
}

/** A captura foi recusada. */
export class CapturaRecusadaError extends Error {
  readonly ocorrencias: readonly Ocorrencia[];

  constructor(ocorrencias: readonly Ocorrencia[], chaves: readonly string[]) {
    super(
      // Sem o número, pela mesma razão que o `NumeroRealError` o não leva.
      `a captura foi recusada: ${ocorrencias.length} telefone(s) sobreviveram ao ` +
        `saneamento. Primeiro no indice ${ocorrencias[0]?.indice ?? -1} ` +
        `(padrao ${ocorrencias[0]?.padrao ?? "?"}). ` +
        (chaves.length > 0
          ? `Chaves de texto que o saneador nao conhece: ${chaves.join(", ")}. `
          : "") +
        "Acrescenta a chave ao saneador antes de gravar — um numero real numa " +
        "fixture fica no historico do git para sempre.",
    );
    this.name = "CapturaRecusadaError";
    this.ocorrencias = ocorrencias;
  }
}

/** O estado de uma captura: o gerador e os mapas de substituição. */
class Mapas {
  readonly #g: Gerador;
  readonly #mapas = new Map<string, Map<string, string>>();
  readonly contagens = new Map<string, number>();
  /** As chaves de texto que levaram um valor com telefone e não foram saneadas. */
  readonly chavesSuspeitas = new Set<string>();

  constructor(g: Gerador) {
    this.#g = g;
  }

  /** O valor fictício de um valor real, estável dentro da captura. */
  traduzir(categoria: string, real: string, fabricar: (g: Gerador) => string): string {
    let mapa = this.#mapas.get(categoria);
    if (mapa === undefined) {
      mapa = new Map<string, string>();
      this.#mapas.set(categoria, mapa);
    }
    const existente = mapa.get(real);
    if (existente !== undefined) return existente;
    const novo = fabricar(this.#g);
    mapa.set(real, novo);
    this.contagens.set(categoria, (this.contagens.get(categoria) ?? 0) + 1);
    return novo;
  }

  contar(categoria: string): void {
    this.contagens.set(categoria, (this.contagens.get(categoria) ?? 0) + 1);
  }
}

function sanearValor(chave: string, valor: string, mapas: Mapas): string {
  if (CHAVES_DE_TELEFONE.has(chave)) {
    // O `display_phone_number` vem formatado; o fictício devolve-se na mesma
    // forma em que entrou, para que a *fixture* exercite o mesmo *parsing*.
    const comMais = valor.trimStart().startsWith("+");
    const novo = mapas.traduzir("telefone", valor.replace(/[^0-9]/g, ""), telefone);
    return comMais ? `+${novo}` : novo;
  }
  if (CHAVES_DE_BSUID.has(chave)) return mapas.traduzir("bsuid", valor, bsuid);
  if (CHAVES_DE_WAMID.has(chave) && valor.startsWith("wamid.")) {
    // O `wamid` novo tem de levar o telefone **novo** lá dentro: um `wamid`
    // fictício construído com o número real deixava o número na *fixture*,
    // dentro de base64, onde o scan não o vê. É o caminho que o `idOpaco` do
    // KAM-068 existe para fechar, e é aqui que ele se honra.
    const numero = mapas.traduzir("telefone", "do-wamid", telefone);
    return mapas.traduzir("wamid", valor, (g) => wamid(g, numero));
  }
  if (CHAVES_DE_CANAL.has(chave)) return mapas.traduzir("canal", valor, phoneNumberId);
  if (CHAVES_DE_TEXTO_LIVRE.has(chave)) {
    mapas.contar("texto_livre");
    // O `name` de um perfil é um nome; o `body` de uma mensagem é texto.
    return chave === "name" || chave === "full_name"
      ? mapas.traduzir("nome", valor, nomeDeExibicao)
      : TEXTO_SINTETICO;
  }
  if (CHAVES_OPACAS.has(chave)) {
    return mapas.traduzir(chave, valor, (g) => g.texto(valor.length <= 64 ? valor.length : 64, "0123456789abcdef"));
  }
  // Um valor de texto numa chave que o saneador não conhece: se tiver um
  // telefone, fica registado como suspeita e a verificação final recusa.
  if (telefonesReais(valor).length > 0) mapas.chavesSuspeitas.add(chave);
  return valor;
}

/**
 * Percorre a árvore, saneando cada folha de texto pela sua chave.
 *
 * `dentroDeEntry` é o que resolve a colisão de nomes: o `id` de um `entry` é o
 * `waba_id`, e o `id` de uma mensagem é o `wamid`. Um saneador que olhasse só
 * para o nome da chave trocava o `waba_id` por um `wamid` — e a *fixture*
 * deixava de descrever um WABA, o que faz o `explodir` do KAM-013 mandar o
 * corpo inteiro para a quarentena por uma razão que não existe no tráfego real.
 * O contexto entra por aqui e por mais sítio nenhum.
 */
function percorrer(no: unknown, chave: string, mapas: Mapas, dentroDeEntry = false): unknown {
  if (typeof no === "string") {
    if (dentroDeEntry && chave === "id") return mapas.traduzir("waba", no, wabaId);
    return sanearValor(chave, no, mapas);
  }
  if (Array.isArray(no)) {
    return no.map((item) => percorrer(item, chave, mapas, dentroDeEntry));
  }
  if (typeof no === "object" && no !== null) {
    const saida: Record<string, unknown> = {};
    for (const [nome, valor] of Object.entries(no as Record<string, unknown>)) {
      // Só o nível imediato de `entry` conta: um `changes[].value.id` já não é
      // um WABA, e por isso o contexto **não** se propaga para dentro.
      saida[nome] = percorrer(valor, nome, mapas, nome === "entry");
    }
    return saida;
  }
  return no;
}

/**
 * Saneia uma captura e **recusa** se sobrar um telefone real.
 *
 * A recusa é sobre o resultado, e é a ordem que torna isto uma salvaguarda e
 * não uma decoração — ver a nota do módulo.
 */
export function sanear(bruto: unknown, semente: string): Saneamento {
  const mapas = new Mapas(new Gerador(semente));
  const numerosNaEntrada = telefonesReais(JSON.stringify(bruto)).length;

  const arvore = percorrer(bruto, "", mapas);

  const texto = JSON.stringify(arvore);
  const sobreviventes = telefonesReais(texto);
  if (sobreviventes.length > 0) {
    throw new CapturaRecusadaError(sobreviventes, [...mapas.chavesSuspeitas]);
  }
  // Segunda verificação, pela via que o resto do pacote usa. Duas chamadas ao
  // mesmo predicado não é redundância: esta é a que lança o erro do `numeros.ts`
  // e é a que um teste de mutação apanha se alguém remover a de cima.
  exigirFicticios(texto);

  return {
    arvore,
    substituicoes: Object.fromEntries(mapas.contagens),
    numerosNaEntrada,
  };
}

/** Um achado do *scan*. */
export interface Achado {
  readonly linha: number;
  readonly coluna: number;
  readonly valor: string;
  readonly padrao: string;
}

/** A linha (1-based) e a coluna de um índice de caractere. */
function posicao(conteudo: string, indice: number): { linha: number; coluna: number } {
  const antes = conteudo.slice(0, indice);
  const ultima = antes.lastIndexOf("\n");
  return { linha: antes.split("\n").length, coluna: indice - ultima };
}

/**
 * O *scan* do critério 7: os telefones de forma real num texto, com a linha.
 *
 * Devolve, e não lança: quem varre muitos ficheiros quer o relatório inteiro, e
 * não o primeiro erro. Quem decide o que é tolerável é o inventário —
 * `inventario.ts` —, e não esta função: aqui conta-se o que está lá.
 */
export function varrer(conteudo: string): readonly Achado[] {
  const achados: Achado[] = [];
  for (const ocorrencia of telefonesReais(conteudo)) {
    const { linha, coluna } = posicao(conteudo, ocorrencia.indice);
    achados.push({ linha, coluna, valor: ocorrencia.valor, padrao: ocorrencia.padrao });
  }
  return achados.sort((a, b) => a.linha - b.linha || a.coluna - b.coluna);
}

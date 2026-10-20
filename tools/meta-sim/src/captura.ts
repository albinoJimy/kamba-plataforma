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
import { eFicticio, exigirFicticios, telefonesReais, type Ocorrencia } from "./numeros.ts";
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

/**
 * Uma chave que leva um telefone **dentro** de uma estrutura que o `id` nomeia.
 *
 * O `history[].threads[].id` é um telefone escrito numa chave chamada `id`, e o
 * próprio simulador o produz (`campos.ts`). A revisão adversarial mostrou o
 * caminho inteiro: a chave não estava em `CHAVES_DE_TELEFONE`, o ramo do
 * `wamid` ignorava-a por não começar por `wamid.`, e um `+351` real atravessava
 * o saneamento **e** a verificação final, porque os dois padrões do `numeros.ts`
 * não apanham um E.164 estrangeiro sem `+`.
 *
 * Trata-se por **forma** e não por nome: um `id` cujo valor seja só algarismos e
 * tenha comprimento de telefone é um telefone. É deliberadamente generoso — um
 * `waba_id` de quinze algarismos também casa —, e isso não faz mal nenhum: o
 * destino é um valor fictício dos dois lados.
 */
const FORMA_DE_TELEFONE = /^[0-9]{8,15}$/;

/**
 * As chaves cujo valor é numérico e **não** é um telefone.
 *
 * A verificação por forma não consegue distinguir um telefone de um instante
 * Unix — os dois são dígitos —, e sem esta lista recusava todas as capturas:
 * um `timestamp` tem dez algarismos. Medido, com os onze testes de saneamento
 * a ficarem vermelhos de uma vez.
 *
 * É uma lista curta e cada entrada é verificável contra `campos.ts`, que é
 * quem produz estes corpos. Uma chave numérica nova que não esteja aqui faz a
 * captura ser **recusada** com a chave nomeada, que é o lado certo para falhar:
 * quem a acrescentar decide o que ela é.
 */
const CHAVES_NUMERICAS_QUE_NAO_SAO_TELEFONE = new Set([
  "timestamp",
  "time",
  "file_size",
  "phase",
  "chunk_order",
  "progress",
  "quantity",
  "item_price",
  "code",
  "error_subcode",
  "max_daily_conversations_per_phone_number",
  "max_phone_numbers_per_business",
  "current_limit",
  "version",
  "expires_at",
  "created_at",
  "updated_at",
]);

/** As chaves cujo valor é um BSUID. */
const CHAVES_DE_BSUID = new Set(["user_id", "from_user_id", "recipient_user_id"]);

/** As chaves cujo valor é um `wamid`. */
const CHAVES_DE_WAMID = new Set(["id", "message_id", "context_id"]);

/** As chaves cujo valor é um identificador de canal. */
const CHAVES_DE_CANAL = new Set(["phone_number_id"]);

/**
 * As chaves cujo valor é texto livre escrito por uma pessoa.
 *
 * A lista cresceu com a revisão adversarial, que enumerou o que faltava: a
 * morada que o utilizador partilha num `location`, o texto livre de uma
 * encomenda, os títulos e descrições de um `interactive`, o `payload` de um
 * botão (que o negócio escolhe mas o cliente devolve), e os campos de um
 * `referral` — que levam o texto do anúncio por onde a conversa entrou.
 */
const CHAVES_DE_TEXTO_LIVRE = new Set([
  "body",
  "caption",
  "filename",
  "full_name",
  "name",
  "address",
  "text",
  "title",
  "description",
  "payload",
  "headline",
  "source_url",
  "source_id",
  "alert_description",
]);

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
  /** As chaves que levantaram suspeita só pela **forma** do valor. */
  readonly chavesComFormaDeTelefone: readonly string[];

  constructor(
    ocorrencias: readonly Ocorrencia[],
    chaves: readonly string[],
    forma: readonly string[] = [],
  ) {
    super(
      // Sem o número, pela mesma razão que o `NumeroRealError` o não leva.
      (ocorrencias.length > 0
        ? `a captura foi recusada: ${ocorrencias.length} telefone(s) sobreviveram ` +
          `ao saneamento. Primeiro no indice ${ocorrencias[0]?.indice ?? -1} ` +
          `(padrao ${ocorrencias[0]?.padrao ?? "?"}). `
        : "a captura foi recusada: um valor com forma de telefone que nao e do " +
          `intervalo ficticio sobreviveu ao saneamento, em ${forma.length} chave(s) ` +
          `que o saneador nao conhece: ${forma.join(", ")}. Nenhum padrao de ` +
          "numero real o apanha — um E.164 estrangeiro escrito sem `+` nao casa " +
          "nenhum —, e e por isso que esta verificacao e uma lista BRANCA. ") +
        (chaves.length > 0
          ? `Chaves de texto que o saneador nao conhece: ${chaves.join(", ")}. `
          : "") +
        "Acrescenta a chave ao saneador antes de gravar — um numero real numa " +
        "fixture fica no historico do git para sempre.",
    );
    this.name = "CapturaRecusadaError";
    this.ocorrencias = ocorrencias;
    this.chavesComFormaDeTelefone = forma;
  }
}


/** O estado de uma captura: o gerador e os mapas de substituição. */
class Mapas {
  readonly #g: Gerador;
  readonly #mapas = new Map<string, Map<string, string>>();
  readonly contagens = new Map<string, number>();
  /** As chaves de texto que levaram um valor com telefone e não foram saneadas. */
  readonly chavesSuspeitas = new Set<string>();
  /** As que só levantam suspeita pela **forma** — um E.164 que os padrões não vêem. */
  readonly suspeitasDeForma = new Set<string>();

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
  if (CHAVES_DE_WAMID.has(chave) && FORMA_DE_TELEFONE.test(valor)) {
    // Um `id` que seja só algarismos com comprimento de telefone **é** um
    // telefone: e o `history[].threads[].id` é exactamente isso. Ver
    // `FORMA_DE_TELEFONE`. Passa pelo mesmo mapa que as outras chaves de
    // telefone, para que a thread do mesmo contacto continue a ser a mesma.
    return mapas.traduzir("telefone", valor, telefone);
  }
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
  // Um valor de texto numa chave que o saneador não conhece.
  //
  // **Duas perguntas e não uma**, e a segunda é a que a revisão adversarial
  // comprou: a primeira é se o valor casa os padrões de telefone **real**, que
  // só apanham Angola e E.164 com `+`; a segunda é se tem **forma** de telefone
  // sem o ser fictício — que apanha o `+351912345678` escrito sem `+`, e
  // qualquer outro E.164 estrangeiro. Sem a segunda, um webhook real do número
  // de teste da Meta (tipicamente `+1`) era gravado com o número intacto, e nem
  // o `exigirFicticios` nem o *scan* o viam.
  //
  // Uma suspeita **não** substitui nada: faz a captura ser recusada, com a
  // chave nomeada, para que alguém decida o que ela é. Substituir às cegas uma
  // chave desconhecida era adivinhar.
  if (telefonesReais(valor).length > 0) mapas.chavesSuspeitas.add(chave);
  else if (
    FORMA_DE_TELEFONE.test(valor) &&
    !eFicticio(valor) &&
    !CHAVES_NUMERICAS_QUE_NAO_SAO_TELEFONE.has(chave)
  ) {
    mapas.chavesSuspeitas.add(chave);
    mapas.suspeitasDeForma.add(chave);
  }
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
/** As chaves cujo valor é um número que localiza uma pessoa. */
const CHAVES_DE_COORDENADA = new Set(["latitude", "longitude"]);

/**
 * Arredonda uma coordenada à **zona**, que é o que o §3.6 do dicionário manda:
 * exactas só no pedido de entrega, e isso é Clusters.
 *
 * Duas casas decimais dão cerca de um quilómetro — bastante para a *fixture*
 * descrever «uma localização em Luanda» e insuficiente para descrever uma casa.
 * A docstring do módulo afirmava que as coordenadas eram substituídas e **não
 * eram**: são números, e o `percorrer` devolvia-as intactas. Achado da revisão
 * adversarial.
 */
function arredondarCoordenada(valor: number): number {
  return Math.round(valor * 100) / 100;
}

function percorrer(no: unknown, chave: string, mapas: Mapas, eUmaEntry = false): unknown {
  if (typeof no === "string") return sanearValor(chave, no, mapas);
  if (typeof no === "number" && CHAVES_DE_COORDENADA.has(chave)) {
    mapas.contar("coordenada");
    return arredondarCoordenada(no);
  }
  if (Array.isArray(no)) {
    // O sinalizador atravessa o array: `entry` **é** um array, e é cada um dos
    // seus elementos que é uma `entry`.
    return no.map((item) => percorrer(item, chave, mapas, eUmaEntry));
  }
  if (typeof no === "object" && no !== null) {
    const saida: Record<string, unknown> = {};
    for (const [nome, valor] of Object.entries(no as Record<string, unknown>)) {
      // O `id` de uma `entry` trata-se **aqui**, no pai que sabe que é uma
      // `entry`, e não no filho. Tentei passar o sinalizador ao filho e o
      // `entry.id` ficou sem substituição nenhuma: o laço recalculava-o de
      // `nome === "entry"`, e para a chave `id` isso dá `false`. O teste
      // `o entry.id e tratado como waba_id e nao como wamid` apanhou-o.
      //
      // Decidir no pai tem a segunda propriedade que importa: o sinalizador
      // **não** se propaga para dentro de `changes`, e por isso um
      // `changes[].value.messages[].id` continua a ser um `wamid`.
      if (eUmaEntry && nome === "id" && typeof valor === "string") {
        saida[nome] = mapas.traduzir("waba", valor, wabaId);
        continue;
      }
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

  // **Terceira, e é a que o critério 7 pede à letra.** As duas de cima são
  // listas **negras** — «recusa se casar um padrão de número real» — e o
  // critério diz o contrário: «recusa gravar se detectar um número que **não
  // pertença** à lista de números fictícios». A diferença não é de estilo: um
  // `+351912345678` escrito sem `+` não casa padrão nenhum, e atravessava as
  // duas (medido pela revisão adversarial, com a chave `history[].threads[].id`
  // que o próprio simulador produz).
  //
  // A lista branca aplica-se às chaves que o saneador **não** reconhece, e não
  // a toda a árvore: aplicá-la a tudo recusava todas as capturas, porque um
  // `waba_id` fictício tem quinze algarismos e um `timestamp` tem dez. As
  // chaves conhecidas já foram substituídas por valores fictícios acima; o que
  // sobra é o que ninguém classificou, e é aí que um número estrangeiro vive.
  if (mapas.suspeitasDeForma.size > 0) {
    throw new CapturaRecusadaError([], [...mapas.chavesSuspeitas], [
      ...mapas.suspeitasDeForma,
    ]);
  }

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

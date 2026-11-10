/**
 * A normalização antes de avaliar (KAM-088, critério 3).
 *
 * Um vendedor que queira passar álcool por «moda» escreve `g1n`, `w h i s k y`,
 * `cer🍺veja`, `cerveeeja` ou `água ardente`. Cada uma destas formas é desfeita
 * por um passo, e os passos produzem **três** leituras do mesmo texto, porque
 * nenhuma sozinha serve as duas metades da política:
 *
 * | Leitura    | O que tem                                         | Quem a usa |
 * |------------|---------------------------------------------------|------------|
 * | `basica`   | minúsculas, sem acentos, *emojis* lidos, `+` e `%` | os `padroes`, que falam de números (`40% vol`, `18+`) |
 * | `palavras` | a básica com *leet*, letras soltas juntas e letras repetidas colapsadas | os `termos`, palavra a palavra |
 * | `compacta` | as palavras sem espaços                            | os `termos` com cinco ou mais letras |
 *
 * **O *leet* só se aplica a um pedaço que já tenha letras.** `g1n` passa a `gin`,
 * mas `50%` e `12 mm` ficam números — senão o `padrao` dos graus de álcool
 * deixava de casar, e `100` virava `ioo`.
 *
 * **A compacta é a que custa falsos positivos.** Junta palavras vizinhas, e é
 * por isso que só os termos com cinco ou mais letras a usam: `arma` dentro de
 * `armario` seria um bloqueio certo de um móvel de cozinha. Os falsos
 * `bloqueada` que sobram medem-se nos casos permitidos do *golden*, e não
 * bloqueiam o gate (Testes Requeridos, «falsos bloqueada reportados»).
 */

/**
 * *Emojis* que dizem a categoria sozinhos. Lidos como a palavra, e não
 * apagados: `cer🍺veja` dá `cer cerveja veja`, que casa por palavra, e um 🍺
 * sem texto à volta também. Cada palavra tem de ser um termo da política.
 */
const EMOJIS: ReadonlyMap<string, string> = new Map([
  ["🍺", "cerveja"],
  ["🍻", "cerveja"],
  ["🍷", "vinho"],
  ["🍾", "espumante"],
  ["🥃", "whisky"],
  ["🍸", "alcool"],
  ["🍹", "alcool"],
  ["🍶", "alcool"],
  ["🥂", "espumante"],
  ["🚬", "cigarro"],
  ["🔫", "arma"],
  ["💣", "explosivo"],
  ["💊", "comprimido"],
  ["💉", "injectavel"],
  ["🎰", "casino"],
]);

/**
 * Letras de outros alfabetos que se confundem com as latinas (achado F01 da
 * revisão adversarial): `рistola` com `р` cirílico, `Vinhο` com `ο` grego,
 * `pıstola` com o `ı` turco. Sem este mapa, a letra estrangeira caía no
 * `[^a-z]` e partia a palavra ao meio. Lista curta e deliberada — as que se
 * confundem à vista, em minúsculas (a conversão vem antes).
 */
const CONFUNDIVEIS: ReadonlyMap<string, string> = new Map([
  // cirílico
  ["а", "a"], ["в", "b"], ["е", "e"], ["ё", "e"], ["к", "k"], ["м", "m"],
  ["н", "h"], ["о", "o"], ["р", "p"], ["с", "c"], ["т", "t"], ["у", "y"],
  ["х", "x"], ["ѕ", "s"], ["і", "i"], ["ї", "i"], ["ј", "j"], ["ԁ", "d"],
  ["ԛ", "q"], ["ԝ", "w"], ["г", "r"], ["п", "n"], ["ь", "b"],
  // grego
  ["α", "a"], ["β", "b"], ["γ", "y"], ["ε", "e"], ["η", "n"], ["ι", "i"],
  ["κ", "k"], ["μ", "u"], ["ν", "v"], ["ο", "o"], ["ρ", "p"], ["τ", "t"],
  ["υ", "u"], ["χ", "x"], ["ω", "w"], ["ς", "s"],
  // latim fora do ASCII que o NFKD não desfaz
  ["ı", "i"], ["ł", "l"], ["ø", "o"], ["đ", "d"], ["ß", "s"],
]);

/**
 * Caracteres de enchimento que se vêem como espaço mas não são `\s` nem `Cf`:
 * o preenchimento do hangul (`U+3164` e família) e o braille em branco
 * (`U+2800`). Apagam-se, como os de largura zero.
 */
const ENCHIMENTO = /[ᅟᅠㅤﾠ⠀]/gu;

/**
 * Letras em blocos de símbolos que o NFKD não decompõe: indicadores regionais
 * (`🇬🇮🇳`) e letras em quadrado ou círculo negativo (`🅟🅘🅢`). Cada bloco é
 * um alfabeto contíguo de A a Z.
 */
const BLOCOS_DE_LETRAS: readonly (readonly [number, number])[] = [
  [0x1f1e6, 0x1f1ff],
  [0x1f170, 0x1f189],
  [0x1f150, 0x1f169],
];

function letraDeBloco(ponto: number): string | undefined {
  for (const [inicio, fim] of BLOCOS_DE_LETRAS) {
    if (ponto >= inicio && ponto <= fim) return String.fromCharCode(97 + ponto - inicio);
  }
  return undefined;
}

/** Palavras de duas letras ou menos que não se juntam às vizinhas. */
const PALAVRAS_CURTAS_COMUNS = new Set([
  "a", "e", "o", "as", "os", "ao", "da", "de", "do", "em", "um", "no", "na",
  "se", "ou", "me", "te", "x",
]);

/** Os caracteres que se escrevem no lugar de letras. */
const LEET: ReadonlyMap<string, string> = new Map([
  ["0", "o"],
  ["1", "i"],
  ["3", "e"],
  ["4", "a"],
  ["5", "s"],
  ["7", "t"],
  ["8", "b"],
  ["9", "g"],
  ["@", "a"],
  ["$", "s"],
  ["!", "i"],
  ["|", "i"],
  ["€", "e"],
]);

export interface TextoNormalizado {
  readonly basica: string;
  readonly palavras: string;
  readonly compacta: string;
}

/** Minúsculas, sem acentos, sem caracteres invisíveis, *emojis* lidos. */
function preparar(texto: string): string {
  let saida = "";
  for (const caracter of texto) {
    const palavra = EMOJIS.get(caracter);
    if (palavra !== undefined) {
      saida += ` ${palavra} `;
      continue;
    }
    saida += letraDeBloco(caracter.codePointAt(0)!) ?? caracter;
  }
  const decomposto = saida
    // O `ç` soa `s`, e lê-se assim antes de o NFKD o partir em `c` e cedilha:
    // `munição` e `munisão` passam a escrever-se igual.
    .replace(/[çÇ]/g, "s")
    .toLowerCase()
    // NFKD decompõe acentos **e** formas de compatibilidade: `ｗｈｉｓｋｙ` de
    // largura total passa a `whisky`.
    .normalize("NFKD")
    // As marcas combinantes (os acentos já separados), os caracteres de
    // formatação (`U+200B` e família) e os de enchimento apagam-se: um espaço
    // que não se vê no meio de uma palavra não a pode partir.
    .replace(/[\p{M}\p{Cf}]/gu, "")
    .replace(ENCHIMENTO, "")
    .toLowerCase();
  let latino = "";
  for (const caracter of decomposto) latino += CONFUNDIVEIS.get(caracter) ?? caracter;
  return latino;
}

function espacos(texto: string): string {
  return texto.replace(/\s+/g, " ").trim();
}

/** Junta sequências de três ou mais letras soltas: `w h i s k y` → `whisky`. */
function juntarLetrasSoltas(palavras: string[]): string[] {
  const saida: string[] = [];
  let soltas: string[] = [];
  const despejar = () => {
    if (soltas.length >= 3) saida.push(soltas.join(""));
    else saida.push(...soltas);
    soltas = [];
  };
  for (const palavra of palavras) {
    if (palavra.length === 1) soltas.push(palavra);
    else {
      despejar();
      saida.push(palavra);
    }
  }
  despejar();
  return saida;
}

/**
 * Junta sequências de duas ou mais palavras curtas (até duas letras) que não
 * sejam palavras comuns: `ru m` → `rum`, `cu ca` → `cuca`. As comuns (`de`,
 * `em`, `a`…) partem a sequência, senão `garrafa de rum` virava `garrafaderum`.
 */
function juntarPedacosCurtos(palavras: string[]): string[] {
  const saida: string[] = [];
  let curtos: string[] = [];
  const despejar = () => {
    if (curtos.length >= 2) saida.push(curtos.join(""));
    else saida.push(...curtos);
    curtos = [];
  };
  for (const palavra of palavras) {
    if (palavra.length <= 2 && !PALAVRAS_CURTAS_COMUNS.has(palavra) && /[a-z]/.test(palavra)) curtos.push(palavra);
    else {
      despejar();
      saida.push(palavra);
    }
  }
  despejar();
  return saida;
}

function colapsar(texto: string): string {
  return texto.replace(/([a-z])\1+/g, "$1");
}

/**
 * A dobra fonética: as grafias que soam igual escrevem-se igual.
 *
 * `quimbanda`/`kimbanda`, `caporroto`/`kaporroto`, `tequila`/`tekila`,
 * `curandeiro`/`curandêro`, `maruvo`/`maruvu`, `dentista`/`dentysta`. Aplica-se
 * aos termos e aos textos da mesma maneira, pelo que o que se perde em
 * legibilidade não muda o que casa — e os padrões, que se escrevem na grafia
 * normal, leem a `basica`, que não é dobrada.
 */
function dobrar(texto: string): string {
  return texto
    .replace(/ph/g, "f")
    .replace(/wh/g, "u")
    .replace(/w/g, "u")
    .replace(/y/g, "i")
    .replace(/qu/g, "k")
    .replace(/c(?=[aou])/g, "k")
    .replace(/c(?=[ei])/g, "s")
    .replace(/ei/g, "e")
    // Todos os `o`, e não só os finais: só no fim da palavra, `fisio terapia`
    // compactava em `fisiuterapia` e o termo em `fisioterapia`.
    .replace(/o/g, "u");
}

export function normalizar(texto: string): TextoNormalizado {
  const preparado = preparar(texto);
  const basica = espacos(preparado.replace(/[^a-z0-9+%]/g, " "));

  const pedacos = preparado.split(/\s+/).map((pedaco) =>
    /[a-z]/.test(pedaco)
      ? [...pedaco].map((c) => LEET.get(c) ?? c).join("")
      : pedaco,
  );
  const soltas = espacos(pedacos.join(" ").replace(/[^a-z0-9]/g, " "))
    .split(" ")
    .filter((p) => p !== "");
  const palavras = colapsar(dobrar(colapsar(juntarPedacosCurtos(juntarLetrasSoltas(soltas)).join(" "))));
  const compacta = colapsar(palavras.replace(/ /g, ""));
  return { basica, palavras, compacta };
}

/** A partir de quantas letras um termo também casa na leitura compacta. */
export const MINIMO_PARA_COMPACTA = 5;

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

/** Os caracteres que se escrevem no lugar de letras. */
const LEET: ReadonlyMap<string, string> = new Map([
  ["0", "o"],
  ["1", "i"],
  ["3", "e"],
  ["4", "a"],
  ["5", "s"],
  ["7", "t"],
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
    saida += palavra === undefined ? caracter : ` ${palavra} `;
  }
  return (
    saida
      // NFKD decompõe acentos **e** formas de compatibilidade: `ｗｈｉｓｋｙ` de
      // largura total passa a `whisky`.
      .normalize("NFKD")
      // As marcas combinantes (os acentos já separados) e os caracteres de
      // formatação (`U+200B` e família) apagam-se: um espaço de largura zero
      // no meio de uma palavra não a pode partir.
      .replace(/[\p{M}\p{Cf}]/gu, "")
      .toLowerCase()
  );
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
    .replace(/y/g, "i")
    .replace(/qu/g, "k")
    .replace(/c(?=[aou])/g, "k")
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
  const palavras = colapsar(dobrar(colapsar(juntarLetrasSoltas(soltas).join(" "))));
  const compacta = colapsar(palavras.replace(/ /g, ""));
  return { basica, palavras, compacta };
}

/** A partir de quantas letras um termo também casa na leitura compacta. */
export const MINIMO_PARA_COMPACTA = 5;

/**
 * Os identificadores da inscrição: normalizar, tornar opaco, e cunhar o HMAC
 * (KAM-086, critérios 3 e 4).
 *
 * «12 variantes de escrita do mesmo NIF e do mesmo telefone (espaços, pontos,
 * `+244`/`00244`/`9xx`, maiúsculas, dígitos Unicode, zeros à esquerda)
 * normalizam para o mesmo `*_hmac` e o 2.º registo é bloqueado como duplicado.»
 *
 * ## O que a normalização é, e porque é que ela é o critério inteiro
 *
 * A detecção de duplicados **é** a normalização. Um `nif_hmac` só distingue
 * dois negócios se as duas maneiras de escrever o mesmo NIF derem o mesmo
 * HMAC — e um HMAC é por desenho sensível a um espaço. Por isso a parte que
 * pode errar em silêncio não é o HMAC: é o que vai para dentro dele.
 *
 * ## A armadilha medida nesta casa: a forma com espaços
 *
 * Os detectores de telefone deste repositório — o `telefone_ao` de
 * `../../../../tools/meta-sim/src/numeros.ts`, o `TELEFONE_PADRAO` do
 * `services/agr` — **não** apanham `923 456 789`: a corrida de dígitos
 * quebra-se no espaço. Está medido e está escrito no inventário de números do
 * *gate* 7. A consequência para **este** ficheiro é directa: um ensaio que só
 * prove a forma compacta prova o caso que nunca falha. As formas abertas — com
 * espaço, ponto, hífen, parêntese e espaço não separável — são as que o
 * `../sms/destino.ts` já retira, e as que a bateria deste módulo exercita uma a
 * uma.
 *
 * ## Três coisas que este ficheiro acrescenta ao `../sms/destino.ts`
 *
 * O `normalizarDestino` já faz o essencial do telefone: retira separadores,
 * aceita `+244`, `244` e `00244`, e exige nove algarismos nacionais. O que
 * falta para o critério 4 são três coisas, e nenhuma lhe pertence:
 *
 * 1. **A forma nacional nua (`9xx`).** O `normalizarDestino` recusa um número
 *    sem indicativo, e tem razão: ele é a porta de um agregador, e um destino
 *    sem país não é um destino. Mas o critério 4 enumera `9xx` como variante, e
 *    é a forma que um dono angolano escreve num formulário. A prefixação com
 *    `+244` é **da inscrição** — é ela que sabe que o formulário é angolano — e
 *    não da porta de SMS.
 * 2. **Dígitos Unicode.** Um teclado árabe ou um `input` com dígitos de largura
 *    inteira produzem algarismos que não são `[0-9]`. Dobram-se aqui, e o que
 *    não se dobra é **recusado** — ver `dobrarAlgarismos`.
 * 3. **O NIF**, que o módulo de SMS não conhece.
 *
 * ## A chave do HMAC é uma, e os domínios são cinco
 *
 * Tudo o que este módulo põe em HMAC usa a **mesma** `pepper_onboarding_ident`
 * (`./refs.ts`), com um separador de domínio por campo. É o argumento escrito
 * do `../sms/destino.ts` aplicado dentro de um módulo em vez de entre módulos:
 * a separação sai da chave quando os domínios são sistemas diferentes, e sai do
 * separador quando são campos do mesmo registo, com o mesmo dono, a mesma
 * retenção e o mesmo ciclo de rotação. Cinco chaves para cinco colunas da mesma
 * linha eram cinco rotações para coordenar.
 *
 * **O HMAC do destino de um SMS não é nenhum destes.** Esse é o
 * `pepper_sms_destino` e é cunhado pelo `../sms/destino.ts`, como o KAM-116
 * escreveu; o `./provedores.ts` é que os liga. Os dois existem e não são
 * redundantes: um identifica a **pessoa** dentro do onboarding, o outro
 * identifica o **endereço** dentro do agregador.
 *
 * ## A forma do NIF é INDÍCIO, e o que ela não mede
 *
 * **Não há fonte primária no conjunto que fixe o formato do NIF angolano.** O
 * `../../../../docs/tecnica/10` §4.1 manda «validação de formato» e o §6 declara
 * a validação oficial junto da AGT **NÃO VERIFICADA**. Por isso a forma aqui é
 * larga de propósito — `FORMA_DE_NIF` —, e a razão é a mesma, com o mesmo sinal,
 * que o `../sms/destino.ts` dá para não verificar o primeiro algarismo
 * nacional: o custo de inventar é assimétrico. Uma forma estreita recusa o NIF
 * de um dono real no passo 1 do onboarding, e a recusa parece-se com uma avaria
 * nossa.
 *
 * O que ela mede: que o valor tem só algarismos e maiúsculas, que tem
 * algarismos suficientes, e que não é texto. Recusa lixo e erros de dedo, e
 * **não** substitui o K1 do KAM-087.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import { INDICATIVO, normalizarDestino } from "../sms/destino.ts";
import { Opaco } from "../sms/opaco.ts";

/** Octetos da chave e dos HMAC. O mesmo do `../sms/destino.ts`. */
export const OCTETOS_DE_HMAC = 32;

/** Os primeiros hexadecimais, para o campo `contact_hmac_prefix` do *logger*. */
export const CARACTERES_DO_PREFIXO = 8;

/**
 * Os separadores de domínio, um por campo. Versionados: mudá-los muda os HMAC.
 *
 * Lista fechada e exportada porque a bateria prende os valores literais: um
 * separador alterado por engano mudava todos os HMAC escritos, e um índice único
 * de `nif_hmac` deixava de ver os duplicados que já lá estavam.
 */
export const DOMINIOS = {
  nif: "kamba/onboarding/nif/v1",
  telefone: "kamba/onboarding/telefone/v1",
  otp: "kamba/onboarding/otp/v1",
  dispositivo: "kamba/onboarding/dispositivo/v1",
  rede: "kamba/onboarding/rede/v1",
} as const;

export type Dominio = (typeof DOMINIOS)[keyof typeof DOMINIOS];

/**
 * Os zeros dos blocos de algarismos decimais que se dobram para ASCII.
 *
 * **Lista fechada, e o que não está nela é recusado** — ver
 * `dobrarAlgarismos`. A alternativa era descobrir o valor de qualquer
 * `\p{Nd}` por aritmética sobre o ponto de código, que funciona enquanto os
 * blocos são corridas de dez e falha calado quando não são. Um `switch`
 * legível que recusa o desconhecido é melhor do que uma esperteza que dobra
 * um algarismo errado.
 *
 * Os blocos: ASCII, árabe-índico (teclados árabes), árabe-índico estendido
 * (persa e urdu), N'Ko, devanágari, bengali e largura inteira (teclados e
 * `input` de CJK). Nenhum é especulação sobre a Angola: são os que um
 * formulário na Web recebe por cópia e por teclado alternativo, e o custo de
 * cada entrada é uma linha.
 */
export const ZEROS_DE_BLOCO: readonly number[] = [
  0x0030, // ASCII
  0x0660, // arabe-indico
  0x06f0, // arabe-indico estendido
  0x07c0, // n'ko
  0x0966, // devanagari
  0x09e6, // bengali
  0xff10, // largura inteira
];

/**
 * Caracteres de apresentação que se retiram antes de validar.
 *
 * `\p{Pd}` cobre os travessões Unicode e `\p{Zs}` os espaços que não são o
 * `U+0020` — e os dois estão aqui por causa da armadilha do cabeçalho: um
 * número colado de uma folha de cálculo leva espaço não separável, e um colado
 * de um documento leva travessão en em vez de hífen. Os dois são a **forma
 * aberta** que os detectores desta casa não apanham.
 */
const SEPARADORES = /[\s.,;:()[\]/\\_\p{Pd}\p{Zs}−]/gu;

/** Algarismos nacionais de um número angolano. O mesmo do `../sms/destino.ts`. */
const NACIONAL = /^[0-9]{9}$/;

/**
 * Forma do NIF depois de normalizado. **INDÍCIO** — ver a nota do módulo.
 *
 * Oito a vinte caracteres de `[0-9A-Z]`, com pelo menos
 * `ALGARISMOS_MINIMOS_DO_NIF` algarismos. O tecto de vinte não é um facto sobre
 * a AGT: é o que impede um campo de texto livre de entrar num índice único.
 */
export const FORMA_DE_NIF = /^[0-9A-Z]{8,20}$/;

/** Algarismos mínimos de um NIF. **INDÍCIO** — um NIF sem algarismos não é um NIF. */
export const ALGARISMOS_MINIMOS_DO_NIF = 8;

/** Tecto do texto de um campo livre do formulário. */
export const CARACTERES_DE_TEXTO = 120;

/** Porque é que um identificador foi recusado. **Nenhum destes valores é um dado.** */
export const MOTIVOS = [
  "vazio",
  "algarismos_unicode",
  "forma",
  "comprimento",
  "indicativo",
] as const;

export type MotivoDaRecusa = (typeof MOTIVOS)[number];

/**
 * Levantado quando um identificador não serve.
 *
 * **A mensagem não leva o valor recusado**, e leva o comprimento e o motivo —
 * a regra do `../sms/destino.ts` e do `../secrets/port.ts`. Um NIF recusado
 * continua a ser o NIF de uma empresa, e uma mensagem de erro é a superfície
 * que mais acaba em ficheiro de log.
 */
export class IdentificadorInvalidoError extends Error {
  override readonly name = "IdentificadorInvalidoError";
  readonly campo: string;
  readonly comprimento: number;
  readonly motivo: MotivoDaRecusa;

  constructor(campo: string, comprimento: number, motivo: MotivoDaRecusa) {
    super(`${campo} invalido (${comprimento} caracteres, ${motivo})`);
    this.campo = campo;
    this.comprimento = comprimento;
    this.motivo = motivo;
  }
}

/** Levantado quando a chave de HMAC não tem o tamanho certo. */
export class ChaveDeHmacInvalidaError extends Error {
  override readonly name = "ChaveDeHmacInvalidaError";

  constructor(octetos: number) {
    super(`a chave de HMAC da inscricao tem ${octetos} octetos; esperava ${OCTETOS_DE_HMAC}`);
  }
}

function exigirChave(chave: Uint8Array): void {
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) {
    throw new ChaveDeHmacInvalidaError(chave instanceof Uint8Array ? chave.length : 0);
  }
}

/**
 * Dobra os algarismos decimais Unicode para ASCII, ou lança.
 *
 * Três passagens, e a **primeira** é a barreira — a ordem é o que a faz valer:
 *
 * 1. **Sobre o texto bruto**, recusa qualquer caractere de categoria `\p{N}`
 *    que não seja `[0-9]` nem pertença a um bloco de `ZEROS_DE_BLOCO`.
 * 2. O NFKC resolve a largura inteira, o `＋` e as formas de compatibilidade —
 *    é uma normalização da norma e não uma tabela nossa.
 * 3. Os blocos de `ZEROS_DE_BLOCO` dobram-se por aritmética dentro do bloco.
 *
 * ## Porque é que a barreira tem de correr **antes** do NFKC, e sobre `\p{N}`
 *
 * A primeira versão desta função corria a barreira **depois** do NFKC e só
 * sobre `\p{Nd}`, e as duas escolhas juntas abriam um buraco medido: o NFKC
 * fabrica algarismos ASCII a partir de categorias que **não** são `Nd` —
 * `No` (o `²` sobrescrito, o `㊱` circundado) e `Nl` (os numerais romanos) —, e
 * depois dele já não há nada de estranho para a barreira ver.
 *
 * O caso que dói é o telefone: oito algarismos mais um `²` davam
 * `923456782`, **nove** algarismos, que o `NACIONAL` aceita. O dono escreveu um
 * número e o sistema aceitou **outro**, em silêncio, e o OTP ia para o telefone
 * de outra pessoa. Achado da revisão adversarial, e a regra que o módulo já
 * escrevia — «o que não se dobra é recusado; falhar em voz alta é a única
 * resposta certa» — passou a cobrir a superfície toda em vez de metade dela.
 *
 * O que fica de fora, dito: um caractere que o NFKC transforme num algarismo e
 * que **não** seja `\p{N}` nenhum. Não encontrei nenhum, e a varredura dos
 * 0x110000 pontos de código que a revisão fez também não — mas a afirmação é
 * sobre a tabela Unicode de hoje e por isso é **INDÍCIO**, não CONFIRMADO.
 */
export function dobrarAlgarismos(bruto: string, campo: string): string {
  for (const caractere of bruto) {
    if (/^[0-9]$/.test(caractere)) continue;
    const ponto = caractere.codePointAt(0) ?? 0;
    if (ZEROS_DE_BLOCO.some((zero) => ponto >= zero && ponto <= zero + 9)) continue;
    if (/\p{N}/u.test(caractere)) {
      throw new IdentificadorInvalidoError(campo, bruto.length, "algarismos_unicode");
    }
  }
  const normalizado = bruto.normalize("NFKC");
  let saida = "";
  for (const caractere of normalizado) {
    const ponto = caractere.codePointAt(0) ?? 0;
    const zero = ZEROS_DE_BLOCO.find((z) => ponto >= z && ponto <= z + 9);
    saida += zero === undefined ? caractere : String.fromCharCode(0x30 + ponto - zero);
  }
  // A rede de segurança da terceira passagem: um `\p{Nd}` que sobreviva a
  // tudo isto não pode passar por caractere comum.
  if (/\p{Nd}/u.test(saida.replace(/[0-9]/g, ""))) {
    throw new IdentificadorInvalidoError(campo, bruto.length, "algarismos_unicode");
  }
  return saida;
}

/**
 * O telefone em E.164, ou lança.
 *
 * A ordem não é arbitrária: dobrar antes de retirar separadores (um algarismo
 * de largura inteira pode estar entre espaços), retirar separadores antes de
 * contar algarismos (é a armadilha das formas abertas), e tentar a forma
 * nacional nua **antes** de chamar o `normalizarDestino` (que a recusa, e com
 * razão — ver a nota do módulo).
 */
export function normalizarTelefone(bruto: unknown): string {
  if (typeof bruto !== "string" || bruto.trim() === "") {
    throw new IdentificadorInvalidoError("telefone", 0, "vazio");
  }
  const dobrado = dobrarAlgarismos(bruto, "telefone");
  const limpo = dobrado.replace(SEPARADORES, "");
  // A forma nacional nua. Nove algarismos sem indicativo só se podem ler de
  // uma maneira: o `244…` do `normalizarDestino` tem doze e o `00244…` catorze,
  // pelo que não há ambiguidade de comprimento entre as três leituras.
  const candidato = NACIONAL.test(limpo) ? `${INDICATIVO}${limpo}` : limpo;
  try {
    return normalizarDestino(candidato);
  } catch {
    // O motivo do `DestinoInvalidoError` não se propaga: ele descreve a forma
    // que a porta de SMS espera, e o que falhou aqui foi a forma que o
    // formulário aceita. Traduzir mantém a mensagem a falar da superfície certa.
    const motivo: MotivoDaRecusa = limpo.replace(/[^0-9]/g, "").length === 0 ? "vazio" : "indicativo";
    throw new IdentificadorInvalidoError("telefone", bruto.length, motivo);
  }
}

/**
 * O NIF na forma canónica, ou lança.
 *
 * Maiúsculas porque o critério 4 as nomeia e porque o NIF de pessoa singular
 * leva letras; **os zeros à cabeça não se retiram**, e a razão é medida e não
 * estética. Sem formato confirmado pela AGT, `0012345678` e `12345678` podem
 * ser dois contribuintes; colapsá-los fazia o segundo negócio ser tratado como
 * duplicado do primeiro e mandado recuperar a sessão por OTP para um telefone
 * que não é o dele — isto é, uma recusa de serviço a um dono legítimo,
 * disfarçada de anti-abuso. A variante «zeros à esquerda» do critério 4 é
 * satisfeita pelo telefone, onde o `00244` é inequívoco.
 */
export function normalizarNif(bruto: unknown): string {
  if (typeof bruto !== "string" || bruto.trim() === "") {
    throw new IdentificadorInvalidoError("nif", 0, "vazio");
  }
  const dobrado = dobrarAlgarismos(bruto, "nif");
  const limpo = dobrado.replace(SEPARADORES, "").toUpperCase();
  if (!FORMA_DE_NIF.test(limpo)) {
    const motivo: MotivoDaRecusa = /^[0-9A-Z]*$/.test(limpo) ? "comprimento" : "forma";
    throw new IdentificadorInvalidoError("nif", bruto.length, motivo);
  }
  if (limpo.replace(/[^0-9]/g, "").length < ALGARISMOS_MINIMOS_DO_NIF) {
    throw new IdentificadorInvalidoError("nif", bruto.length, "forma");
  }
  return limpo;
}

/**
 * O e-mail na forma canónica, ou lança.
 *
 * A forma é deliberadamente curta — há um `@`, há um ponto depois dele, e não há
 * espaços — e **não** é uma implementação do RFC 5322: validar e-mail por
 * expressão regular é o exemplo clássico de recusar endereços válidos, e o
 * e-mail é **opcional** neste formulário. Quem confirma que ele existe é o envio.
 */
export function normalizarEmail(bruto: unknown): string {
  if (typeof bruto !== "string" || bruto.trim() === "") {
    throw new IdentificadorInvalidoError("email", 0, "vazio");
  }
  const limpo = bruto.trim().normalize("NFKC").toLowerCase();
  if (limpo.length > CARACTERES_DE_TEXTO) {
    throw new IdentificadorInvalidoError("email", bruto.length, "comprimento");
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(limpo)) {
    throw new IdentificadorInvalidoError("email", bruto.length, "forma");
  }
  return limpo;
}

/** O HMAC de um valor **já normalizado**, com separador de domínio. */
export function hmacDe(chave: Uint8Array, dominio: Dominio | string, valor: string): Buffer {
  exigirChave(chave);
  return createHmac("sha256", chave).update(`${dominio}\0`, "utf8").update(valor, "utf8").digest();
}

/**
 * Um valor opaco com o HMAC ao lado. A forma do `Destino` do `../sms/`.
 *
 * O valor em claro sai por `revelar()`, e esse é o único caminho — ver
 * `../sms/opaco.ts`.
 *
 * **Há DOIS sítios de chamada do `revelar()` em todo o módulo, e são estes:**
 * o `./provedores.ts`, que entrega o número ao `cunharDestino` da porta de
 * SMS, e o `./otp.ts`, que entrega o código ao HMAC que fica guardado. Um
 * terceiro é um achado de revisão — e a primeira versão desta nota nomeava um
 * ficheiro que **não existe** (`sms_local.ts`) e um que ainda não existe (o
 * adaptador SQL), omitindo os dois reais. Apanhou-o a revisão adversarial, com
 * um `grep`. Quando o adaptador SQL existir, ele é o terceiro, e esta conta
 * muda com ele.
 */
abstract class ComHmac extends Opaco {
  /**
   * O HMAC com a chave **actual**. É este que se escreve numa coluna.
   */
  readonly hmac: string;
  /**
   * Os HMAC com **todas** as chaves do anel, a actual primeiro.
   *
   * É este que se usa para **procurar**, e a assimetria é de correcção: quem
   * escreve usa a actual, quem procura um duplicado tem de procurar também com
   * a anterior — senão a primeira rotação do *pepper* fazia o índice único de
   * `nif_hmac` deixar de ver os casos escritos antes dela, e um duplicado que
   * não se vê é um segundo registo do mesmo negócio.
   *
   * **Calcula-se na cunhagem**, e é por isso que o `./registo.ts` não precisa
   * de chamar `revelar()`: o valor em claro não sai daqui para fazer uma
   * consulta. Com um anel de uma chave só, é uma entrada — e a consulta é uma.
   */
  readonly hmacs: readonly string[];
  /** Os primeiros oito hexadecimais do `hmac`, para o `contact_hmac_prefix`. */
  readonly prefixoDoHmac: string;

  protected constructor(
    valor: string,
    chaveOuAnel: Uint8Array | readonly (Uint8Array | null)[],
    dominio: Dominio,
  ) {
    super(valor);
    const anel = chaveOuAnel instanceof Uint8Array ? [chaveOuAnel] : chaveOuAnel;
    const todos = hmacsDoAnel(anel, dominio, valor);
    const actual = todos[0];
    if (actual === undefined) throw new ChaveDeHmacInvalidaError(0);
    this.hmac = actual;
    this.hmacs = todos;
    this.prefixoDoHmac = actual.slice(0, CARACTERES_DO_PREFIXO);
  }
}

/** O NIF de um negócio: em memória em claro, em HMAC nos registos. */
export class Nif extends ComHmac {
  constructor(bruto: unknown, chaveOuAnel: Uint8Array | readonly (Uint8Array | null)[]) {
    super(normalizarNif(bruto), chaveOuAnel, DOMINIOS.nif);
  }
}

/**
 * O tipo de linha de um número angolano: `movel`, `fixo` ou `desconhecido`.
 *
 * Pelo primeiro algarismo nacional: `9` é móvel e `2` é fixo. **INDÍCIO** — é
 * o plano de numeração como se lê nos números que circulam, e não uma leitura
 * do plano publicado pelo regulador, que nenhum documento deste repositório
 * cita. O `desconhecido` é o resto, e inclui os números de ensaio desta casa,
 * que começam por zero precisamente para não serem de ninguém.
 */
export type Linha = "movel" | "fixo" | "desconhecido";

/** A `Linha` de um E.164 já normalizado. Ver o tipo. */
export function linhaDe(e164: string): Linha {
  const nacional = e164.startsWith(INDICATIVO) ? e164.slice(INDICATIVO.length) : "";
  if (!NACIONAL.test(nacional)) return "desconhecido";
  if (nacional.startsWith("9")) return "movel";
  if (nacional.startsWith("2")) return "fixo";
  return "desconhecido";
}

/** O telefone do dono: em memória em claro, em HMAC nos registos. */
export class Telefone extends ComHmac {
  /**
   * O tipo de linha, calculado **na cunhagem** (KAM-093).
   *
   * Pelo mesmo caminho do `hmacs`: o pré-voo do Embedded Signup precisa de
   * saber se o número é fixo («fixo ⇒ rota de voz / `cloud_only`»), e
   * perguntar-lho depois obrigava a um terceiro `revelar()` neste módulo — que a
   * nota do `ComHmac` diz ser um achado de revisão. O tipo de linha não
   * identifica ninguém: é um de três valores.
   */
  readonly linha: Linha;

  constructor(bruto: unknown, chaveOuAnel: Uint8Array | readonly (Uint8Array | null)[]) {
    const e164 = normalizarTelefone(bruto);
    super(e164, chaveOuAnel, DOMINIOS.telefone);
    this.linha = linhaDe(e164);
  }
}

/**
 * O e-mail do dono. **Opaco e sem HMAC**, e a assimetria é do bloco.
 *
 * O DDL tem `email_enc` e **não** tem `email_hmac`: o e-mail não entra na
 * detecção de duplicados nem no índice único. Dar-lhe um HMAC era construir
 * maquinaria sem consumidor — a mesma razão por que a `SecretProvider` do
 * KAM-010 não tem escrita.
 */
export class Email extends Opaco {
  constructor(bruto: unknown) {
    super(normalizarEmail(bruto));
  }
}

/**
 * Os oito grupos de um IPv6, expandidos e normalizados, ou `null`.
 *
 * **Expandir antes de cortar é a correcção de um defeito medido**, e a primeira
 * versão deste ficheiro tinha-o: ela devolvia o endereço inteiro como prefixo
 * quando ele levava `::`, com a justificação de que cortar ao terceiro grupo de
 * um `::` dava prefixos diferentes para o mesmo bloco. A justificação estava
 * certa e o remédio estava errado — `2001:db8::1` e `2001:db8::2` davam **dois**
 * baldes para o mesmo `/48`, e quem tivesse um `/64` (uma alocação residencial
 * normal, ou uma máquina de nuvem) trocava de endereço a cada pedido e pagava
 * cinco casos por hora **em cada um**. Achado da revisão adversarial.
 *
 * A normalização a quatro hexadecimais é o que faz `2001:db8::1` e
 * `2001:0db8:0000:0000:0000:0000:0000:0001` dar o mesmo prefixo.
 */
function gruposDeIpv6(texto: string): readonly string[] | null {
  if (!/^[0-9a-f:]{2,45}$/.test(texto) || !texto.includes(":")) return null;
  const partes = texto.split("::");
  if (partes.length > 2) return null;
  const antes = partes[0] === "" ? [] : (partes[0] ?? "").split(":");
  const resto = partes[1];
  const depois = resto === undefined || resto === "" ? [] : resto.split(":");
  if (partes.length === 1) {
    if (antes.length !== 8) return null;
  } else if (antes.length + depois.length >= 8) {
    // Um `::` tem de representar **pelo menos** um grupo a zero; oito grupos
    // escritos mais um `::` é um endereço que não existe.
    return null;
  }
  const faltam = partes.length === 1 ? 0 : 8 - antes.length - depois.length;
  const todos = [...antes, ...Array.from({ length: faltam }, () => "0"), ...depois];
  if (todos.length !== 8) return null;
  if (todos.some((grupo) => !/^[0-9a-f]{1,4}$/.test(grupo))) return null;
  return todos.map((grupo) => grupo.padStart(4, "0"));
}

/**
 * O prefixo grosseiro de um endereço IP, antes de ir a HMAC.
 *
 * `/24` em IPv4 e `/48` em IPv6 — **proposta**, e é o que torna o limite do
 * critério 7 um limite por rede e não por cliente. Grosseiro é o ponto: um
 * limite por endereço exacto não trava nada atrás de NAT, que é como a maior
 * parte de Luanda sai para a Internet, e um limite mais largo travava um bairro.
 *
 * ## Um IPv4 mapeado é um IPv4, e esquecê-lo desligava o limite inteiro
 *
 * Um processo Node a escutar em `::` recebe um cliente IPv4 como
 * `::ffff:192.0.2.33`. A primeira versão desta função devolvia `null` para essa
 * forma — a expressão de IPv4 não casa com o prefixo e a de IPv6 recusa os
 * pontos —, e `null` quer dizer «sem rede»: o limite de cinco casos por hora e
 * por prefixo **não se aplicava a ninguém** na configuração em que o serviço
 * corre, porque é esse o endereço que o `remoteAddress` dá. Achado da revisão
 * adversarial, e é a diferença entre o caminho medido e o caminho que corre.
 *
 * Um endereço que não se percebe devolve `null`, e quem chama trata o `null`
 * como «sem rede» em vez de inventar uma chave: um prefixo inventado punha
 * clientes distintos no mesmo balde.
 */
export function prefixoDeIp(bruto: unknown): string | null {
  if (typeof bruto !== "string") return null;
  let texto = bruto.trim().toLowerCase();
  // As duas formas de um IPv4 mapeado em IPv6. A segunda — `::ffff:c000:0233` —
  // já é hexadecimal e cai no caminho de IPv6, onde dá o prefixo `0000:0000:0000`
  // para **todos** os IPv4 mapeados; por isso ela traduz-se aqui também.
  const comPontos = /^(?:::ffff:|::)((?:[0-9]{1,3}\.){3}[0-9]{1,3})$/.exec(texto);
  if (comPontos !== null) texto = comPontos[1] ?? texto;
  const emHex = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(texto);
  if (emHex !== null) {
    const alto = Number.parseInt(emHex[1] ?? "", 16);
    const baixo = Number.parseInt(emHex[2] ?? "", 16);
    texto = `${alto >> 8}.${alto & 0xff}.${baixo >> 8}.${baixo & 0xff}`;
  }

  const v4 = /^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.[0-9]{1,3}$/.exec(texto);
  if (v4 !== null) {
    const octetos = [v4[1], v4[2], v4[3]].map((o) => Number(o));
    if (octetos.some((o) => !Number.isInteger(o) || o > 255)) return null;
    return `${octetos[0]}.${octetos[1]}.${octetos[2]}.0/24`;
  }

  const grupos = gruposDeIpv6(texto);
  if (grupos === null) return null;
  return `${grupos.slice(0, 3).join(":")}::/48`;
}

/**
 * Os HMAC deste valor com **todas** as chaves do anel, a actual primeiro.
 *
 * Existe por uma razão de correcção e não de simetria: quem **escreve** um
 * `nif_hmac` usa a chave actual, mas quem **procura** um duplicado tem de
 * procurar também com a anterior. Sem isto, a primeira rotação do *pepper*
 * fazia o índice único de `nif_hmac` deixar de ver os casos escritos antes
 * dela — e um duplicado que não se vê é um segundo registo do mesmo negócio,
 * que é exactamente o que o critério 4 existe para impedir.
 *
 * É a mesma pergunta que o `hmacCorresponde` responde para um HMAC conhecido,
 * do outro lado: aqui não há HMAC para comparar, há uma consulta para fazer.
 */
export function hmacsDoAnel(
  anel: readonly (Uint8Array | null)[],
  dominio: Dominio | string,
  valorNormalizado: string,
): readonly string[] {
  const saida: string[] = [];
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    const hex = hmacDe(chave, dominio, valorNormalizado).toString("hex");
    if (!saida.includes(hex)) saida.push(hex);
  }
  return saida;
}

/**
 * Este HMAC é deste valor, com alguma das chaves do anel?
 *
 * Compara em **tempo constante** e **sem sair ao primeiro acerto**, pela razão
 * que o `../entrada/assinatura.ts` escreve e que o `destinoCorresponde` do
 * `../sms/destino.ts` repete: um `return` dentro do ciclo dizia pelo tempo de
 * resposta qual das chaves acertou, que é informação sobre o estado da rotação.
 */
export function hmacCorresponde(
  hmacEmHex: string,
  dominio: Dominio | string,
  valorNormalizado: string,
  anel: readonly (Uint8Array | null)[],
): boolean {
  if (typeof hmacEmHex !== "string" || !/^[0-9a-f]{64}$/.test(hmacEmHex)) return false;
  const recebido = Buffer.from(hmacEmHex, "hex");
  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    acertos |= timingSafeEqual(hmacDe(chave, dominio, valorNormalizado), recebido) ? 1 : 0;
  }
  return acertos === 1;
}

/**
 * Texto de um campo livre do formulário, normalizado, ou lança.
 *
 * O nome do negócio e a categoria declarada entram num `onboarding_case` e saem
 * numa fila de revisão humana. O que esta função garante é o tecto de
 * comprimento e a ausência de caracteres de controlo — **não** garante que o
 * nome é um nome. É o `../avisos/` que mascara corridas de dígitos num nome de
 * loja, e essa é a superfície de saída, não a de entrada.
 */
export function normalizarTexto(bruto: unknown, campo: string): string {
  if (typeof bruto !== "string") throw new IdentificadorInvalidoError(campo, 0, "vazio");
  // eslint-disable-next-line no-control-regex
  const limpo = bruto.normalize("NFKC").replace(/[\u0000-\u001f\u007f]/g, " ").trim();
  if (limpo === "") throw new IdentificadorInvalidoError(campo, bruto.length, "vazio");
  if (limpo.length > CARACTERES_DE_TEXTO) {
    throw new IdentificadorInvalidoError(campo, bruto.length, "comprimento");
  }
  return limpo;
}

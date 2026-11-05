/**
 * O destino de um SMS: só `+244`, e com HMAC para os registos (KAM-116,
 * critério 6).
 *
 * «Só o prefixo `+244`; (…) o telefone só em memória, com HMAC nos registos.»
 *
 * ## O `+244` é uma recusa, não uma preferência
 *
 * O SMS deste módulo serve **um** propósito: provar a posse do telefone do dono
 * de uma PME angolana, antes de existir número ligado
 * (`../../../../docs/tecnica/10` §4.1, passo 2). Um destino fora de Angola não é
 * um caso de uso com menos prioridade — é um erro, e possivelmente a assinatura
 * de alguém a usar o nosso agregador como relé para tráfego que paga mais caro.
 * Por isso a recusa é na cunhagem do `Destino` e não no adaptador: um adaptador
 * novo não tem como esquecer uma verificação que acontece antes de ele existir.
 *
 * ## O que a forma mede, e o que não mede
 *
 * Mede que o número tem indicativo de Angola e nove algarismos nacionais. **Não
 * mede** se é um número móvel atribuído, se está activo, ou de que operadora é:
 * isso é a resposta do agregador, e vem como `INVALID_DESTINATION` ou num
 * recibo negativo.
 *
 * Os nove algarismos nacionais são **INDÍCIO**: não há fonte primária no
 * conjunto que fixe o plano de numeração de Angola — o `../../../../docs/tecnica/01`
 * L10 declara a própria entrega para a Unitel e a Africell como **NÃO
 * VERIFICADA**, e a evidência `E1` §5 nota o mesmo para a verificação de
 * números. O que isto quer dizer na prática: a forma recusa lixo e erros de
 * dedo, e **não** substitui o teste de entrega do critério 2.
 *
 * Deliberadamente **não há** verificação do primeiro algarismo nacional. Um
 * `9XX` para móvel é conhecimento comum sem fonte no canon, e o custo de o
 * inventar é assimétrico: se mudar, recusamos números válidos de donos reais no
 * passo 2 do onboarding, e a recusa parece-se com uma avaria nossa.
 *
 * ## A chave do HMAC é um segredo próprio, e não a `pepper_contact_hmac`
 *
 * A tentação é reusar o *pepper* de HMAC de contacto, que já existe no
 * inventário e já tem anel de duas chaves. **Não se reusa**, por duas razões
 * medidas e não estéticas:
 *
 * 1. **O `hmacDePesquisa` exige um `tenant_id` UUID canónico**
 *    (`../identity/cripto.ts`), e no passo 2 do onboarding **não há tenant**: o
 *    tenant nasce no `tenant.approved`, muito depois do OTP. Chamá-lo com um
 *    tenant inventado — um UUID de zeros — era pôr no espaço de HMAC de
 *    pesquisa valores que não pertencem a contacto nenhum.
 * 2. **A separação de domínio sai da chave e não de uma constante que alguém
 *    pode esquecer de mudar.** É o argumento escrito que o KAM-115 deixou no
 *    inventário para separar a `kek_contacto_dono` da `kek_token_cliente`, e
 *    vale igual aqui: com chave própria, um HMAC deste módulo não pode
 *    coincidir com um HMAC de pesquisa nem por engano de domínio.
 *
 * O segredo é a `pepper_sms_destino` (`ops/secrets-inventory.yaml`,
 * `introduzido_por: KAM-116`), com anel de duas chaves para rotação. O
 * separador de domínio fica **também** — `kamba/sms/destino/v1\0<número>` — e
 * não é redundância inútil: é o que torna o HMAC versionável sem rodar a chave,
 * no dia em que a forma do registo mudar.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import { SmsError } from "./contrato.ts";
import { Opaco } from "./opaco.ts";

/** O único indicativo aceite. */
export const INDICATIVO = "+244";

/** Algarismos do número nacional. **INDÍCIO** — ver a nota do módulo. */
export const ALGARISMOS_NACIONAIS = 9;

/** Separador de domínio do HMAC. Versionado: mudá-lo muda todos os HMAC. */
export const DOMINIO = "kamba/sms/destino/v1";

/** Caracteres de apresentação que se tiram antes de validar. */
const SEPARADORES = /[ \t\r\n.()-]/g;

/** As três maneiras de escrever o indicativo de Angola que se aceitam. */
const PREFIXOS = ["+244", "00244", "244"] as const;

const NACIONAL = new RegExp(`^[0-9]{${ALGARISMOS_NACIONAIS}}$`);

/** Octetos do HMAC, e caracteres do prefixo que o *logger* aceita. */
export const OCTETOS_DE_HMAC = 32;
/** O `contact_hmac_prefix` do `../logger/politica.ts` tem oito hexadecimais. */
export const CARACTERES_DO_PREFIXO = 8;

/** Porque é que um destino foi recusado aqui. Nenhum destes valores é um número. */
export const MOTIVOS = ["vazio", "indicativo", "algarismos"] as const;

export type MotivoDaRecusa = (typeof MOTIVOS)[number];

/**
 * Levantado quando o destino não serve.
 *
 * **É um `SmsError` com `INVALID_DESTINATION`**, e não uma classe à parte. O
 * critério 5 pede três erros tipados e esse é um deles: quem chama o `send`
 * trata um número que recusámos aqui e um número que o agregador recusou da
 * mesma maneira — não repete, e diz ao dono que o número não serve. Duas
 * hierarquias de erro para a mesma decisão davam um `catch` que apanha uma e
 * deixa passar a outra, e o `repetivel` desta é `false` por `REPETIVEIS`, não
 * por escolha deste ficheiro.
 *
 * **A mensagem não leva o número**, e é por isso que ela diz tão pouco: um
 * destino recusado continua a ser o telefone de uma pessoa, e uma mensagem de
 * erro é a superfície que mais acaba em ficheiros de log. Leva o comprimento e o
 * motivo, que é o que permite distinguir «veio vazio» de «veio de outro país»
 * sem revelar qual.
 */
export class DestinoInvalidoError extends SmsError {
  override readonly name = "DestinoInvalidoError";
  readonly comprimento: number;
  readonly motivo: MotivoDaRecusa;

  constructor(comprimento: number, motivo: MotivoDaRecusa) {
    const explicacao = {
      vazio: "veio vazio",
      indicativo: `nao comeca por ${INDICATIVO}`,
      algarismos: `nao tem ${ALGARISMOS_NACIONAIS} algarismos nacionais`,
    }[motivo];
    super("INVALID_DESTINATION", `${comprimento} caracteres, ${explicacao}`);
    this.comprimento = comprimento;
    this.motivo = motivo;
  }
}

/** Levantado quando a chave de HMAC não tem o tamanho certo. */
export class ChaveDeHmacInvalidaError extends Error {
  override readonly name = "ChaveDeHmacInvalidaError";

  constructor(octetos: number) {
    super(`a chave de HMAC do destino tem ${octetos} octetos; esperava ${OCTETOS_DE_HMAC}`);
  }
}

function exigirChave(chave: Uint8Array): void {
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) {
    throw new ChaveDeHmacInvalidaError(chave instanceof Uint8Array ? chave.length : 0);
  }
}

/**
 * O número em E.164, ou lança.
 *
 * Exportada porque o ensaio de forma a exercita sozinha, e porque um adaptador
 * que receba números de outra fonte precisa da mesma normalização. Quem envia
 * usa `cunharDestino`, que é isto mais o HMAC.
 */
export function normalizarDestino(bruto: unknown): string {
  const texto = (typeof bruto === "string" ? bruto : "").replace(SEPARADORES, "");
  if (texto === "") throw new DestinoInvalidoError(0, "vazio");

  const prefixo = PREFIXOS.find((p) => texto.startsWith(p));
  if (prefixo === undefined) throw new DestinoInvalidoError(texto.length, "indicativo");

  const nacional = texto.slice(prefixo.length);
  if (!NACIONAL.test(nacional)) throw new DestinoInvalidoError(texto.length, "algarismos");

  return `${INDICATIVO}${nacional}`;
}

/** O HMAC de um número **já normalizado**, com separador de domínio. */
function hmacDoNumero(chave: Uint8Array, numero: string): Buffer {
  return createHmac("sha256", chave).update(`${DOMINIO}\0`, "utf8").update(numero, "utf8").digest();
}

/**
 * Um destino de SMS: o número em memória, o HMAC para os registos.
 *
 * O número sai por `revelar()`, e esse é o **único** caminho — ver `opaco.ts`.
 * No módulo há dois sítios legítimos de chamada, os dois no `fake.ts` e num
 * adaptador: entregar o endereço ao agregador, e nada mais.
 *
 * O `hmac` e o `prefixoDoHmac` são o que vai para registos, relatórios e
 * mensagens. O prefixo tem oito hexadecimais porque é essa a forma que o campo
 * `contact_hmac_prefix` do `../logger/politica.ts` aceita; o HMAC inteiro serve
 * o relatório de entrega do critério 2, onde se precisa de distinguir
 * destinos sem os conhecer.
 */
export class Destino extends Opaco {
  /** HMAC-SHA256 do número com separador de domínio, em hexadecimais. */
  readonly hmac: string;
  /** Os primeiros oito hexadecimais, para o campo `contact_hmac_prefix`. */
  readonly prefixoDoHmac: string;

  constructor(numero: string, chave: Uint8Array) {
    exigirChave(chave);
    const normalizado = normalizarDestino(numero);
    super(normalizado);
    this.hmac = hmacDoNumero(chave, normalizado).toString("hex");
    this.prefixoDoHmac = this.hmac.slice(0, CARACTERES_DO_PREFIXO);
  }
}

/**
 * Cunha um destino, validando a forma e calculando o HMAC.
 *
 * `chave` vem do anel da `pepper_sms_destino` (`segredos.ts`, `anelDoPepper`):
 * a **actual**. **Nao** a `pepper_contact_hmac` — a razao por que este modulo
 * tem chave propria e o argumento central do cabecalho deste ficheiro, e uma
 * nota que dissesse o contrario era o tipo de erro que faz um adaptador ligar
 * a chave errada. A anterior serve para **reconhecer** um HMAC escrito
 * antes de uma rotação, e é o que `destinoCorresponde` faz.
 */
export function cunharDestino(bruto: unknown, chave: Uint8Array): Destino {
  return new Destino(normalizarDestino(bruto), chave);
}

/**
 * Este HMAC é de este número, com alguma das chaves do anel?
 *
 * É a pergunta do relatório de entrega: um registo escrito antes de uma rotação
 * leva o HMAC da chave anterior, e compará-lo só com a actual dava «destino
 * desconhecido» para um envio que se mediu.
 *
 * Compara em **tempo constante** e sem sair ao primeiro acerto, pela mesma razão
 * que o `../entrada/assinatura.ts` escreve: um `return` dentro do ciclo dizia
 * pelo tempo de resposta qual das chaves acertou, que é informação sobre o
 * estado da rotação.
 */
export function destinoCorresponde(
  hmacEmHex: string,
  numero: unknown,
  anel: readonly (Uint8Array | null)[],
): boolean {
  if (typeof hmacEmHex !== "string" || !/^[0-9a-f]{64}$/.test(hmacEmHex)) return false;
  let normalizado: string;
  try {
    normalizado = normalizarDestino(numero);
  } catch {
    return false;
  }
  const recebido = Buffer.from(hmacEmHex, "hex");
  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    acertos |= timingSafeEqual(hmacDoNumero(chave, normalizado), recebido) ? 1 : 0;
  }
  return acertos === 1;
}

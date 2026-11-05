/**
 * O recibo de entrega: autenticado e idempotente (KAM-116, critério 5).
 *
 * «Recibo autenticado (assinatura ou lista de IPs) e idempotente por id do
 * fornecedor.»
 *
 * ## Fail-closed, e sem excepção de ambiente
 *
 * Sem **nenhum** mecanismo configurado, nada é aceite. Não há «em `dev` passa»:
 * o recibo é o que move a `sms_delivery_ratio`, o que marca um envio como
 * entregue e o que, a jusante, deixa o KAM-086 dar o telefone por provado. Um
 * recibo que qualquer um pode fabricar é uma prova de posse de telefone que
 * qualquer um pode fabricar. A implementação falsa dos ensaios não passa por
 * aqui — ela entrega `Recibo` já construídos, que é outra fronteira — pelo que
 * fechar isto não custa nada a quem desenvolve.
 *
 * ## Dois mecanismos, e o «ou» do critério é inclusivo
 *
 * `assinatura` é a boa: prova que o corpo não foi tocado, e não depende da
 * topologia da rede. A `lista de IPs` é a que alguns agregadores locais só
 * conseguem oferecer, e prova muito menos — um proxy pelo meio, um
 * `X-Forwarded-For` em que se confie por engano, e a prova desaparece.
 *
 * Com os dois configurados, **exigem-se os dois**. É o oposto do que a leitura
 * natural de «ou» sugere, e é deliberado: quem configurou assinatura e lista de
 * IPs quis duas barreiras, e um «ou» disjuntivo transformava a segunda barreira
 * num caminho alternativo que a contorna. Quem quer só uma configura só uma.
 *
 * ## A assinatura reutiliza o `../entrada/assinatura.ts`
 *
 * A comparação em tempo constante e o anel de duas chaves estão lá, escritos
 * para os webhooks da Meta (KAM-013), e uma segunda implementação de uma
 * comparação em tempo constante é a classe de duplicação que se paga com um
 * defeito de segurança — é o que aquele ficheiro diz de si próprio, e vale aqui.
 *
 * O que este ficheiro acrescenta é a **normalização do cabeçalho**: o formato
 * do agregador é **NÃO VERIFICADO**, porque não há agregador escolhido. Os
 * esquemas que se aceitam estão em `ESQUEMAS`, e um esquema novo é uma linha
 * naquele registo — não é uma segunda função de verificação.
 *
 * ## A lista de IPs só fala IPv4, e a recusa é o ponto
 *
 * Um endereço IPv6 de origem é **recusado** quando há lista de IPs
 * configurada, em vez de aceito por não caber na comparação. A direcção certa
 * para falhar: a lista existe para dizer «só destes», e «não sei comparar»
 * tem de significar «não». Suportar IPv6 entra no dia em que um agregador
 * escolhido o use, e nem isso se sabe hoje.
 */

import { assinaturaValida } from "../entrada/assinatura.ts";
import type { Operadora, Recibo } from "./contrato.ts";
import { OPERADORAS } from "./contrato.ts";
import { ID_DE_RECIBO } from "./idempotencia.ts";

/**
 * Como o agregador codifica o resumo no cabeçalho.
 *
 * Os três são formas que agregadores usam; qual é a do nosso é **NÃO
 * VERIFICADO** e fixa-se com a cotação (`../../../../docs/evidencia/KAM-116.md`,
 * linha «formato do recibo» da matriz).
 */
export const ESQUEMAS = ["sha256_hex", "sha256_hex_prefixado", "sha256_base64"] as const;

export type Esquema = (typeof ESQUEMAS)[number];

/** O prefixo que o esquema `sha256_hex_prefixado` traz, como o da Meta. */
export const PREFIXO = "sha256=";

const HEX = /^[0-9a-fA-F]{64}$/;
const BASE64 = /^[A-Za-z0-9+/]{43}=$/;

/** Como o `../entrada/assinatura.ts` espera o cabeçalho. */
const CANONICO = PREFIXO;

/**
 * Traduz o cabeçalho do agregador para a forma que o `assinaturaValida` lê, ou
 * `null` se ele não tem forma nenhuma.
 *
 * Exportada porque o ensaio a exercita sozinha: é aqui que uma tradução errada
 * faria uma assinatura válida parecer inválida — e, pior, o contrário.
 */
export function normalizarAssinatura(bruto: string | undefined, esquema: Esquema): string | null {
  if (typeof bruto !== "string") return null;
  const valor = bruto.trim();
  if (valor === "") return null;

  if (esquema === "sha256_hex_prefixado") {
    if (!valor.startsWith(PREFIXO)) return null;
    const hex = valor.slice(PREFIXO.length);
    return HEX.test(hex) ? CANONICO + hex.toLowerCase() : null;
  }
  if (esquema === "sha256_hex") {
    return HEX.test(valor) ? CANONICO + valor.toLowerCase() : null;
  }
  // sha256_base64
  if (!BASE64.test(valor)) return null;
  const bytes = Buffer.from(valor, "base64");
  if (bytes.length !== 32) return null;
  return CANONICO + bytes.toString("hex");
}

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

/** Converte um IPv4 em inteiro de 32 bits, ou `null`. */
function inteiroDeIpv4(texto: string): number | null {
  const encontro = IPV4.exec(texto.trim());
  if (encontro === null) return null;
  let valor = 0;
  for (let i = 1; i <= 4; i += 1) {
    const octeto = Number(encontro[i]);
    // Sem zeros a esquerda: `010.0.0.1` nao e o mesmo endereco em todo o
    // software que o le, e aceitar as duas grafias dava a uma lista de IPs duas
    // leituras. Recusa-se a forma ambigua.
    if (!Number.isInteger(octeto) || octeto < 0 || octeto > 255) return null;
    if ((encontro[i] ?? "").length > 1 && (encontro[i] ?? "").startsWith("0")) return null;
    valor = valor * 256 + octeto;
  }
  return valor;
}

/** Levantado quando uma entrada da lista de IPs não é um IPv4 nem um CIDR IPv4. */
export class RedeInvalidaError extends Error {
  override readonly name = "RedeInvalidaError";

  constructor(entrada: string) {
    super(
      `entrada da lista de IPs invalida: ${JSON.stringify(entrada)}; ` +
        "esperava a.b.c.d ou a.b.c.d/N (IPv4)",
    );
  }
}

/**
 * O prefixo de um CIDR, em forma canónica: 0 a 32, sem zeros à esquerda.
 *
 * **Lido por padrão e não por `Number`, e isto foi um defeito a sério.** O
 * `Number("")` é `0`, e `0` passa qualquer verificação de gama: uma entrada com
 * barra final — `196.216.0.1/`, que é o erro de dedo mais fácil de cometer numa
 * lista de IPs — compilava para a máscara vazia e **autorizava todos os
 * endereços IPv4**. Medido antes da correcção: `ipPermitido("1.2.3.4", …)` dava
 * `true` e o `autenticado` aceitava um recibo de qualquer origem.
 *
 * Numa superfície que este ficheiro declara *fail-closed* duas vezes, isso era
 * o oposto: um erro de dedo abria a porta inteira. E o `Number` aceitava mais —
 * `24.0` e ` 24 ` liam-se como 24, calados, de modo que a lista não era a que
 * quem a escreveu pensou.
 */
const PREFIXO_CIDR = /^(?:[0-9]|[12][0-9]|3[0-2])$/;

/** Uma entrada compilada da lista de IPs. */
export interface Rede {
  readonly base: number;
  readonly mascara: number;
}

/**
 * Compila a lista de IPs. Levanta em cada entrada que não entende.
 *
 * Levantar, e não ignorar: uma entrada com erro de dedo numa lista de IPs é uma
 * lista mais curta do que quem a escreveu pensa, e o sintoma é o agregador a
 * ser recusado em produção — com o diagnóstico a apontar para o agregador.
 */
export function compilarRedes(entradas: readonly string[]): readonly Rede[] {
  return entradas.map((entrada) => {
    const campos = entrada.trim().split("/");
    // Mais de uma barra levanta: `a.b.c.d/24/8` lia-se como `/24` e o terceiro
    // campo desaparecia em silencio, pelo que a lista nao era a que quem a
    // escreveu pensou.
    if (campos.length > 2) throw new RedeInvalidaError(entrada);
    const [endereco = "", bits] = campos;
    const base = inteiroDeIpv4(endereco);
    if (base === null) throw new RedeInvalidaError(entrada);
    // `bits` e `undefined` quando nao ha barra (um `/32` implicito) e `""`
    // quando ha barra e nada depois — e **essas duas coisas nao sao a mesma**.
    // Ver `PREFIXO_CIDR`.
    if (bits !== undefined && !PREFIXO_CIDR.test(bits)) throw new RedeInvalidaError(entrada);
    const prefixo = bits === undefined ? 32 : Number(bits);
    // `>>> 0` porque um deslocamento de 32 em JavaScript e um deslocamento de
    // 0 (o operando e tomado modulo 32), e `/0` tem de dar a mascara vazia.
    const mascara = prefixo === 0 ? 0 : (0xffff_ffff << (32 - prefixo)) >>> 0;
    return { base: (base & mascara) >>> 0, mascara };
  });
}

/** O endereço de origem está em alguma das redes? */
export function ipPermitido(origem: string | undefined, redes: readonly Rede[]): boolean {
  if (redes.length === 0) return false;
  const valor = typeof origem === "string" ? inteiroDeIpv4(origem) : null;
  // IPv6, vazio ou lixo: **recusa**. Ver a nota do módulo.
  if (valor === null) return false;
  return redes.some((rede) => ((valor & rede.mascara) >>> 0) === rede.base);
}

/** Como o recibo se autentica. Pelo menos um campo tem de estar presente. */
export interface Autenticacao {
  /** `[actual, anterior]` do segredo do recibo; o `anterior` pode ser `null`. */
  readonly anel?: readonly (string | null)[];
  /** Como o agregador codifica o resumo. */
  readonly esquema?: Esquema;
  /** Lista de IPs já compilada. */
  readonly redes?: readonly Rede[];
}

/** O que chegou ao endpoint do recibo. */
export interface Pedido {
  /** Os bytes **recebidos**, antes de qualquer `parse`. */
  readonly corpo: Uint8Array;
  readonly assinatura?: string | undefined;
  readonly origem?: string | undefined;
}

/** Porque é que um recibo foi recusado. Nenhum destes valores é um dado pessoal. */
export const RECUSAS = ["sem_mecanismo", "assinatura", "ip", "corpo", "repetido"] as const;

export type Recusa = (typeof RECUSAS)[number];

/** O veredicto sobre um pedido de recibo. */
export type Veredicto =
  | { readonly aceite: true; readonly recibo: Recibo }
  | { readonly aceite: false; readonly recusa: Recusa };

/**
 * Autentica o pedido.
 *
 * Separada do `receber` porque é a metade que não precisa de estado nenhum, e é
 * a que um ensaio quer exercitar sozinha.
 */
export function autenticado(pedido: Pedido, autenticacao: Autenticacao): Recusa | null {
  const temAssinatura = Array.isArray(autenticacao.anel) && autenticacao.anel.length > 0;
  const temRedes = Array.isArray(autenticacao.redes) && autenticacao.redes.length > 0;

  // Fail-closed: sem mecanismo nenhum, nada passa. Ver a nota do módulo.
  if (!temAssinatura && !temRedes) return "sem_mecanismo";

  // Os dois, quando os dois estão configurados — o «ou» é inclusivo.
  if (temAssinatura) {
    const esquema = autenticacao.esquema ?? "sha256_hex_prefixado";
    const cabecalho = normalizarAssinatura(pedido.assinatura, esquema);
    if (cabecalho === null) return "assinatura";
    if (!assinaturaValida(pedido.corpo, cabecalho, autenticacao.anel ?? [])) return "assinatura";
  }
  if (temRedes && !ipPermitido(pedido.origem, autenticacao.redes ?? [])) return "ip";

  return null;
}

/** O que um corpo de recibo tem de dizer, depois de interpretado pelo adaptador. */
export interface CorpoDeRecibo {
  readonly idDoFornecedor: unknown;
  readonly entregue: unknown;
  readonly operadora?: unknown;
  readonly em?: unknown;
  readonly motivo?: unknown;
}

/** Motivos com mais de este comprimento são cortados. Ver `normalizarRecibo`. */
export const MOTIVO_MAXIMO = 64;

const MOTIVO_SEGURO = /^[A-Za-z0-9 ._:-]*$/;

/**
 * Normaliza o corpo num `Recibo`, ou `null` se ele não serve.
 *
 * **O `motivo` é a superfície mais perigosa deste ficheiro**, e é por isso que
 * ele é tratado com desconfiança: é texto que o agregador escolhe, vai para
 * registos, e nada impede o agregador de lá pôr o número de destino — alguns
 * põem («delivery failed for 244…»). Aqui ele é cortado, limitado a um
 * alfabeto sem acentos e **recusado por inteiro se tiver mais de seis
 * algarismos**, que é exactamente a regra do `../logger/politica.ts` e apanha
 * um telefone em qualquer arrumação.
 */
export function normalizarRecibo(corpo: CorpoDeRecibo, agora: Date): Recibo | null {
  const id = corpo.idDoFornecedor;
  if (typeof id !== "string" || !ID_DE_RECIBO.test(id)) return null;
  if (typeof corpo.entregue !== "boolean") return null;

  const operadoraBruta = typeof corpo.operadora === "string" ? corpo.operadora.toLowerCase() : "";
  const operadora: Operadora = (OPERADORAS as readonly string[]).includes(operadoraBruta)
    ? (operadoraBruta as Operadora)
    : "desconhecida";

  let em = agora;
  if (typeof corpo.em === "string") {
    const lido = new Date(corpo.em);
    if (!Number.isNaN(lido.getTime())) em = lido;
  }

  let motivo: string | null = null;
  if (typeof corpo.motivo === "string" && corpo.motivo !== "") {
    const cortado = corpo.motivo.slice(0, MOTIVO_MAXIMO);
    const algarismos = cortado.match(/[0-9]/g)?.length ?? 0;
    motivo = MOTIVO_SEGURO.test(cortado) && algarismos <= 6 ? cortado : null;
  }

  return {
    idDoFornecedor: id,
    estado: corpo.entregue ? "entregue" : "falhou",
    operadora,
    em,
    motivo,
  };
}

/** Interpreta os bytes do pedido no corpo que o agregador enviou. */
export type Interpretar = (corpo: Uint8Array) => CorpoDeRecibo | null;

/**
 * Quem entrega o recibo já autenticado. É o `Envios.receber`.
 *
 * O nome leva o sufixo porque o `envio.ts` tem um `Entregar` que é outra coisa
 * — a chamada ao agregador — e dois tipos com o mesmo nome no mesmo módulo é
 * como se liga o errado sem dar por isso.
 */
export type EntregarRecibo = (recibo: Recibo, idDoEnvio?: string) => Promise<boolean>;

/** Como se trata um pedido de recibo, de ponta a ponta. */
export interface OpcoesDoPedido {
  readonly autenticacao: Autenticacao;
  readonly interpretar: Interpretar;
  readonly entregar: EntregarRecibo;
  readonly relogio?: () => Date;
  /** Traduz o id do recibo no id do envio, quando o agregador usa dois. */
  readonly idDoEnvio?: (recibo: Recibo) => string | undefined;
}

/**
 * Autentica, interpreta, normaliza e entrega — **sobre os mesmos bytes**.
 *
 * ## Porque é que isto existe, e é a mesma razão do `Envios` do `envio.ts`
 *
 * Sem esta função, um adaptador tem de ligar o `autenticado`, o `interpretar`, o
 * `normalizarRecibo` e o `Envios.receber` pela ordem certa — e **nada o impede
 * de autenticar uns bytes e interpretar outros**. É exactamente a classe de
 * defeito que o `envio.ts` invoca para justificar a própria existência: uma
 * função correcta ligada ao sítio errado passa todos os ensaios dela. O ticket
 * entregou essa barreira para o envio e tinha-a deixado de fora para o recibo,
 * e foi um achado da revisão adversarial.
 *
 * Aqui os bytes entram uma vez, num parâmetro, e os quatro passos correm por
 * esta ordem sem que quem chama a possa trocar. É também o que torna o
 * `Veredicto` e os valores `corpo` e `repetido` de `RECUSAS` alcançáveis: antes
 * desta função eram tipos que nenhuma função produzia.
 *
 * ## A ordem, e o que cada passo custa se correr trocado
 *
 *     1. autentica       sobre os bytes **recebidos**, antes de qualquer parse
 *     2. interpreta       o adaptador sabe o formato; se não souber, `null`
 *     3. normaliza        corta o `motivo`, fecha a operadora, lê a data
 *     4. entrega          ao `Envios.receber`, que deduplica por id
 *
 * Autenticar **antes** de interpretar não é estética: um corpo malformado de um
 * atacante não deve chegar ao interpretador do adaptador, e a assinatura é
 * sobre os bytes e não sobre o objecto (é a lição do `../entrada/assinatura.ts`,
 * onde `{"a":1}` e `{ "a": 1 }` têm o mesmo `JSON.parse` e assinaturas
 * diferentes).
 */
export async function receberPedido(
  pedido: Pedido,
  opcoes: OpcoesDoPedido,
): Promise<Veredicto> {
  const recusa = autenticado(pedido, opcoes.autenticacao);
  if (recusa !== null) return { aceite: false, recusa };

  const corpo = opcoes.interpretar(pedido.corpo);
  if (corpo === null) return { aceite: false, recusa: "corpo" };

  const agora = (opcoes.relogio ?? ((): Date => new Date()))();
  const recibo = normalizarRecibo(corpo, agora);
  if (recibo === null) return { aceite: false, recusa: "corpo" };

  const novo = await opcoes.entregar(recibo, opcoes.idDoEnvio?.(recibo));
  // Um recibo repetido **não é erro** — os agregadores re-entregam, e é para
  // isso que o registo de recibos existe. Devolve-se `repetido` para que o
  // adaptador possa responder 200 e distinguir no registo as duas coisas.
  return novo ? { aceite: true, recibo } : { aceite: false, recusa: "repetido" };
}

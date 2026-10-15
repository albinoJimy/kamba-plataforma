/**
 * AWS Signature Version 4, o suficiente para S3 (KAM-011).
 *
 * **Porque é que isto está escrito à mão.** O `@kamba/core-ts` não tem
 * dependências de execução, e o SDK da AWS traria mais de cem pacotes para
 * fazer cinco pedidos HTTP — cada um deles superfície do *gate* 11 e da cadeia
 * de abastecimento (`docs/tecnica/08` §4.8). O algoritmo é público, pequeno e
 * estável; o que o torna arriscado é errar a canonicalização, e por isso a
 * prova de que está certo **não é um teste nosso contra nós próprios**: é um
 * servidor S3 real a aceitar os pedidos e a recusar os de chave errada
 * (`docs/evidencia/KAM-011-seaweedfs.md`).
 *
 * O que está aqui: assinatura por cabeçalho `Authorization` e por *query*
 * (URL pré-assinada). O que não está: `aws-chunked`, SigV4A, *session tokens*.
 */

import { createHash, createHmac } from "node:crypto";

export const ALGORITMO = "AWS4-HMAC-SHA256";
const SERVICO = "s3";
const TERMINADOR = "aws4_request";

/** Valor de `x-amz-content-sha256` de uma URL pré-assinada. */
export const CORPO_NAO_ASSINADO = "UNSIGNED-PAYLOAD";

/** Credenciais S3. **Nunca** entram numa mensagem de erro nem num log. */
export interface Credenciais {
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

export function sha256Hex(dados: Uint8Array | string): string {
  return createHash("sha256").update(dados).digest("hex");
}

function hmac(chave: Uint8Array | string, dados: string): Buffer {
  return createHmac("sha256", chave).update(dados).digest();
}

/** Codificação RFC 3986: só `A-Za-z0-9-_.~` ficam em claro. */
export function codificar(texto: string): string {
  return encodeURIComponent(texto).replace(
    /[!'()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

/** Caminho canónico: cada segmento codificado uma vez, as barras preservadas. */
export function caminhoCanonico(caminho: string): string {
  return caminho
    .split("/")
    .map((segmento) => codificar(decodeURIComponent(segmento)))
    .join("/");
}

/** *Query* canónica: pares codificados, ordenados por nome e depois por valor. */
export function queryCanonica(parametros: Iterable<readonly [string, string]>): string {
  return [...parametros]
    .map(([nome, valor]) => [codificar(nome), codificar(valor)] as const)
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0))
    .map(([nome, valor]) => `${nome}=${valor}`)
    .join("&");
}

/** `20261012T101500Z` */
export function dataAmz(instante: Date): string {
  return instante.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function ambito(dia: string, regiao: string): string {
  return `${dia}/${regiao}/${SERVICO}/${TERMINADOR}`;
}

function chaveDeAssinatura(segredo: string, dia: string, regiao: string): Buffer {
  return hmac(hmac(hmac(hmac(`AWS4${segredo}`, dia), regiao), SERVICO), TERMINADOR);
}

/** O que entra numa assinatura, já na forma canónica. */
export interface Assinavel {
  readonly metodo: string;
  readonly url: URL;
  /** Cabeçalhos a assinar. Os nomes são passados a minúsculas aqui. */
  readonly cabecalhos: Readonly<Record<string, string>>;
  /** SHA-256 do corpo em hexadecimal, ou `UNSIGNED-PAYLOAD`. */
  readonly hashDoCorpo: string;
  readonly regiao: string;
  /** `x-amz-date` do pedido. */
  readonly quando: string;
  /** *Query* a assinar. Por omissão, a da URL. */
  readonly query?: Iterable<readonly [string, string]>;
}

/**
 * A assinatura hexadecimal de um pedido, e os nomes dos cabeçalhos assinados.
 *
 * É exportada porque há dois lados que a calculam: quem assina, e um servidor
 * de teste que confere.
 */
export function assinatura(
  pedido: Assinavel,
  segredo: string,
): { readonly assinatura: string; readonly assinados: string } {
  const pares = Object.entries(pedido.cabecalhos)
    .map(([nome, valor]) => [nome.toLowerCase(), valor.trim().replace(/\s+/g, " ")] as const)
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const assinados = pares.map(([nome]) => nome).join(";");
  const pedidoCanonico = [
    pedido.metodo,
    caminhoCanonico(pedido.url.pathname),
    queryCanonica(pedido.query ?? pedido.url.searchParams),
    pares.map(([nome, valor]) => `${nome}:${valor}\n`).join(""),
    assinados,
    pedido.hashDoCorpo,
  ].join("\n");
  const dia = pedido.quando.slice(0, 8);
  const aAssinar = [
    ALGORITMO,
    pedido.quando,
    ambito(dia, pedido.regiao),
    sha256Hex(pedidoCanonico),
  ].join("\n");
  return {
    assinatura: hmac(chaveDeAssinatura(segredo, dia, pedido.regiao), aAssinar).toString("hex"),
    assinados,
  };
}

/**
 * Cabeçalhos de um pedido assinado: os que foram dados, mais `host`,
 * `x-amz-date`, `x-amz-content-sha256` e `authorization`.
 *
 * **Todos** os cabeçalhos dados são assinados. Um cabeçalho de metadados fora
 * da assinatura é um cabeçalho que um intermediário pode trocar — e os
 * metadados são onde vive o `retain_until`.
 */
export function assinarPedido(o: {
  readonly metodo: string;
  readonly url: URL;
  readonly cabecalhos?: Readonly<Record<string, string>>;
  readonly corpo?: Uint8Array;
  readonly credenciais: Credenciais;
  readonly regiao: string;
  readonly agora: Date;
}): Record<string, string> {
  const hashDoCorpo = sha256Hex(o.corpo ?? new Uint8Array(0));
  const quando = dataAmz(o.agora);
  const cabecalhos: Record<string, string> = {};
  for (const [nome, valor] of Object.entries(o.cabecalhos ?? {})) {
    cabecalhos[nome.toLowerCase()] = valor;
  }
  cabecalhos["host"] = o.url.host;
  cabecalhos["x-amz-content-sha256"] = hashDoCorpo;
  cabecalhos["x-amz-date"] = quando;
  const { assinatura: valor, assinados } = assinatura(
    { metodo: o.metodo, url: o.url, cabecalhos, hashDoCorpo, regiao: o.regiao, quando },
    o.credenciais.secretAccessKey,
  );
  const credencial = `${o.credenciais.accessKeyId}/${ambito(quando.slice(0, 8), o.regiao)}`;
  cabecalhos["authorization"] =
    `${ALGORITMO} Credential=${credencial}, SignedHeaders=${assinados}, Signature=${valor}`;
  return cabecalhos;
}

/**
 * URL pré-assinada de leitura (`GET`), válida durante `expiraS` segundos a
 * contar de `agora`.
 *
 * Só `host` é assinado, pelo que quem recebe a URL não precisa de mandar
 * cabeçalho nenhum — é isso que a torna utilizável por um `<img>` ou por um
 * `curl`. O preço é o que se sabe: **quem tem a URL tem o objecto** até ela
 * expirar. Por isso o tecto de 300 s não é deste ficheiro, é da guarda.
 */
export function presignarGet(o: {
  readonly url: URL;
  readonly credenciais: Credenciais;
  readonly regiao: string;
  readonly agora: Date;
  readonly expiraS: number;
}): string {
  const quando = dataAmz(o.agora);
  const parametros: [string, string][] = [
    ...o.url.searchParams,
    ["X-Amz-Algorithm", ALGORITMO],
    ["X-Amz-Credential", `${o.credenciais.accessKeyId}/${ambito(quando.slice(0, 8), o.regiao)}`],
    ["X-Amz-Date", quando],
    ["X-Amz-Expires", String(o.expiraS)],
    ["X-Amz-SignedHeaders", "host"],
  ];
  const { assinatura: valor } = assinatura(
    {
      metodo: "GET",
      url: o.url,
      cabecalhos: { host: o.url.host },
      hashDoCorpo: CORPO_NAO_ASSINADO,
      regiao: o.regiao,
      quando,
      query: parametros,
    },
    o.credenciais.secretAccessKey,
  );
  return (
    `${o.url.origin}${caminhoCanonico(o.url.pathname)}?` +
    `${queryCanonica(parametros)}&X-Amz-Signature=${valor}`
  );
}

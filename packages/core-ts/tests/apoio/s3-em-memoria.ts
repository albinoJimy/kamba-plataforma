/**
 * Um servidor S3 em memória, para os testes (KAM-011).
 *
 * Existe para que o `MotorS3` **inteiro** — assinatura, XML, envio em partes,
 * paginação, tradução de erros — corra no *gate* 4, sem contentor. Não é um
 * substituto da prova contra um servidor real: confere as assinaturas com a
 * mesma função que as produz, pelo que apanha um cabeçalho por assinar ou uma
 * URL adulterada, e **não** apanha um erro de canonicalização que os dois lados
 * partilhem. Essa prova é a de `tests/integracao/`, contra o SeaweedFS.
 *
 * Implementa o subconjunto que `src/storage/s3.ts` usa, e recusa o resto com
 * 501 — um pedido que o motor passe a fazer e que este servidor não conheça
 * falha aqui, em vez de passar por omissão.
 */

import { createHash, randomUUID } from "node:crypto";

import type { PedidoHttp, RespostaHttp, Transporte } from "../../src/storage/s3.ts";
import {
  CORPO_NAO_ASSINADO,
  type Credenciais,
  assinatura,
  sha256Hex,
} from "../../src/storage/sigv4.ts";

interface Objecto {
  readonly bytes: Uint8Array;
  readonly cabecalhos: Readonly<Record<string, string>>;
}

interface Envio {
  readonly chave: string;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly partes: Map<number, { readonly bytes: Uint8Array; readonly etag: string }>;
}

export interface S3EmMemoriaOpcoes {
  readonly bucket: string;
  readonly regiao: string;
  readonly credenciais: Credenciais;
  readonly agora: () => Date;
  /** Tecto de chaves por página de listagem, para forçar paginação. */
  readonly pagina?: number;
}

const PARTE_MINIMA = 5 * 1024 * 1024;

async function* umBloco(bytes: Uint8Array): AsyncIterable<Uint8Array> {
  if (bytes.length > 0) yield bytes;
}

function xml(estado: number, corpo: string, cabecalhos: Record<string, string> = {}): RespostaHttp {
  return {
    estado,
    cabecalhos: { "content-type": "application/xml", ...cabecalhos },
    corpo: umBloco(Buffer.from(`<?xml version="1.0" encoding="UTF-8"?>${corpo}`, "utf8")),
  };
}

function erro(estado: number, codigo: string): RespostaHttp {
  return xml(estado, `<Error><Code>${codigo}</Code><Message>${codigo}</Message></Error>`);
}

function etagDe(bytes: Uint8Array): string {
  return `"${createHash("md5").update(bytes).digest("hex")}"`;
}

function quando(amz: string): number {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(amz);
  if (m === null) return Number.NaN;
  return Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!, +m[6]!);
}

export class S3EmMemoria {
  readonly objectos = new Map<string, Objecto>();
  readonly envios = new Map<string, Envio>();
  /** Todos os pedidos recebidos, pela ordem. */
  readonly pedidos: PedidoHttp[] = [];
  /**
   * Gancho de falha: se devolver uma resposta, é essa que o pedido recebe; se
   * lançar, o pedido falha como falha a rede.
   */
  interceptar: ((pedido: PedidoHttp) => RespostaHttp | null) | null = null;

  readonly #o: S3EmMemoriaOpcoes;

  constructor(opcoes: S3EmMemoriaOpcoes) {
    this.#o = opcoes;
  }

  readonly transporte: Transporte = async (pedido) => {
    this.pedidos.push(pedido);
    const forcada = this.interceptar?.(pedido) ?? null;
    if (forcada !== null) return forcada;
    return this.#servir(pedido);
  };

  /** `GET` sem credenciais nenhumas, como um cliente a quem deram uma URL. */
  async buscar(url: string): Promise<{ estado: number; corpo: Uint8Array }> {
    const resposta = await this.transporte({ metodo: "GET", url, cabecalhos: {} });
    const blocos: Uint8Array[] = [];
    for await (const bloco of resposta.corpo) blocos.push(bloco);
    return { estado: resposta.estado, corpo: Buffer.concat(blocos) };
  }

  #autenticado(pedido: PedidoHttp, url: URL): RespostaHttp | null {
    const { credenciais, regiao } = this.#o;
    const agora = this.#o.agora().getTime();
    const corpo = pedido.corpo ?? new Uint8Array(0);

    if (url.searchParams.has("X-Amz-Signature")) {
      const recebida = url.searchParams.get("X-Amz-Signature") ?? "";
      const data = url.searchParams.get("X-Amz-Date") ?? "";
      const expira = Number(url.searchParams.get("X-Amz-Expires"));
      const query = [...url.searchParams].filter(([nome]) => nome !== "X-Amz-Signature");
      const { assinatura: esperada } = assinatura(
        {
          metodo: pedido.metodo,
          url,
          cabecalhos: { host: url.host },
          hashDoCorpo: CORPO_NAO_ASSINADO,
          regiao,
          quando: data,
          query,
        },
        credenciais.secretAccessKey,
      );
      if (recebida !== esperada) return erro(403, "SignatureDoesNotMatch");
      if (!Number.isInteger(expira) || agora >= quando(data) + expira * 1000) {
        return erro(403, "AccessDenied");
      }
      return null;
    }

    const autorizacao = pedido.cabecalhos["authorization"] ?? "";
    const m = /^AWS4-HMAC-SHA256 Credential=([^/]+)\/\S+, SignedHeaders=(\S+), Signature=([0-9a-f]+)$/.exec(
      autorizacao,
    );
    if (m === null) return erro(403, "AccessDenied");
    if (m[1] !== credenciais.accessKeyId) return erro(403, "InvalidAccessKeyId");
    const data = pedido.cabecalhos["x-amz-date"] ?? "";
    if (Math.abs(agora - quando(data)) > 15 * 60 * 1000) return erro(403, "RequestTimeTooSkewed");
    const hashDoCorpo = pedido.cabecalhos["x-amz-content-sha256"] ?? "";
    if (hashDoCorpo !== sha256Hex(corpo)) return erro(400, "XAmzContentSHA256Mismatch");
    const assinados: Record<string, string> = {};
    for (const nome of (m[2] as string).split(";")) {
      const valor = nome === "host" ? url.host : pedido.cabecalhos[nome];
      if (valor === undefined) return erro(403, "SignatureDoesNotMatch");
      assinados[nome] = valor;
    }
    // Todo o cabeçalho de metadados tem de estar assinado.
    for (const nome of Object.keys(pedido.cabecalhos)) {
      if (nome.startsWith("x-amz-meta-") && !(nome in assinados)) {
        return erro(403, "SignatureDoesNotMatch");
      }
    }
    const { assinatura: esperada } = assinatura(
      { metodo: pedido.metodo, url, cabecalhos: assinados, hashDoCorpo, regiao, quando: data },
      credenciais.secretAccessKey,
    );
    return m[3] === esperada ? null : erro(403, "SignatureDoesNotMatch");
  }

  #servir(pedido: PedidoHttp): RespostaHttp {
    const url = new URL(pedido.url);
    const recusa = this.#autenticado(pedido, url);
    if (recusa !== null) return recusa;

    const [, bucket = "", ...resto] = url.pathname.split("/");
    if (bucket !== this.#o.bucket) return erro(404, "NoSuchBucket");
    const chave = resto.map((s) => decodeURIComponent(s)).join("/");
    const q = url.searchParams;
    const corpo = pedido.corpo ?? new Uint8Array(0);

    if (chave === "") {
      if (pedido.metodo === "GET" && q.get("list-type") === "2") return this.#listar(q);
      return erro(501, "NotImplemented");
    }

    const envio = q.get("uploadId");
    if (pedido.metodo === "POST" && q.has("uploads")) {
      const id = randomUUID();
      this.envios.set(id, { chave, cabecalhos: { ...pedido.cabecalhos }, partes: new Map() });
      return xml(
        200,
        `<InitiateMultipartUploadResult><Bucket>${bucket}</Bucket><Key>${chave}</Key>` +
          `<UploadId>${id}</UploadId></InitiateMultipartUploadResult>`,
      );
    }
    if (envio !== null) {
      const aberto = this.envios.get(envio);
      if (aberto === undefined || aberto.chave !== chave) return erro(404, "NoSuchUpload");
      if (pedido.metodo === "PUT" && q.has("partNumber")) {
        const etag = etagDe(corpo);
        aberto.partes.set(Number(q.get("partNumber")), { bytes: Uint8Array.from(corpo), etag });
        return { estado: 200, cabecalhos: { etag }, corpo: umBloco(new Uint8Array(0)) };
      }
      if (pedido.metodo === "DELETE") {
        this.envios.delete(envio);
        return { estado: 204, cabecalhos: {}, corpo: umBloco(new Uint8Array(0)) };
      }
      if (pedido.metodo === "POST") {
        const pedidas = [
          ...Buffer.from(corpo)
            .toString("utf8")
            .matchAll(/<Part><PartNumber>(\d+)<\/PartNumber><ETag>([^<]*)<\/ETag><\/Part>/g),
        ];
        const blocos: Uint8Array[] = [];
        for (const [i, m] of pedidas.entries()) {
          const parte = aberto.partes.get(Number(m[1]));
          const etag = (m[2] as string).replaceAll("&quot;", '"');
          if (parte === undefined || parte.etag !== etag) return erro(400, "InvalidPart");
          if (i < pedidas.length - 1 && parte.bytes.length < PARTE_MINIMA) {
            return erro(400, "EntityTooSmall");
          }
          blocos.push(parte.bytes);
        }
        if (blocos.length === 0) return erro(400, "MalformedXML");
        this.envios.delete(envio);
        this.objectos.set(chave, { bytes: Buffer.concat(blocos), cabecalhos: aberto.cabecalhos });
        return xml(200, `<CompleteMultipartUploadResult><Key>${chave}</Key></CompleteMultipartUploadResult>`);
      }
      return erro(501, "NotImplemented");
    }

    switch (pedido.metodo) {
      case "PUT":
        this.objectos.set(chave, { bytes: Uint8Array.from(corpo), cabecalhos: { ...pedido.cabecalhos } });
        return { estado: 200, cabecalhos: { etag: etagDe(corpo) }, corpo: umBloco(new Uint8Array(0)) };
      case "GET":
      case "HEAD": {
        const objecto = this.objectos.get(chave);
        if (objecto === undefined) {
          return pedido.metodo === "HEAD"
            ? { estado: 404, cabecalhos: {}, corpo: umBloco(new Uint8Array(0)) }
            : erro(404, "NoSuchKey");
        }
        const cabecalhos: Record<string, string> = {
          "content-length": String(objecto.bytes.length),
          "content-type": objecto.cabecalhos["content-type"] ?? "application/octet-stream",
        };
        for (const [nome, valor] of Object.entries(objecto.cabecalhos)) {
          if (nome.startsWith("x-amz-meta-")) cabecalhos[nome] = valor;
        }
        return {
          estado: 200,
          cabecalhos,
          corpo: umBloco(pedido.metodo === "HEAD" ? new Uint8Array(0) : objecto.bytes),
        };
      }
      case "DELETE":
        this.objectos.delete(chave);
        return { estado: 204, cabecalhos: {}, corpo: umBloco(new Uint8Array(0)) };
      default:
        return erro(501, "NotImplemented");
    }
  }

  #listar(q: URLSearchParams): RespostaHttp {
    const prefixo = q.get("prefix") ?? "";
    const pedidas = Math.min(Number(q.get("max-keys") ?? 1000), this.#o.pagina ?? 1000);
    const depois = q.get("continuation-token");
    const chaves = [...this.objectos.keys()]
      .filter((c) => c.startsWith(prefixo) && (depois === null || c > depois))
      .sort();
    const pagina = chaves.slice(0, pedidas);
    const truncada = chaves.length > pagina.length;
    return xml(
      200,
      `<ListBucketResult><Name>${this.#o.bucket}</Name><Prefix>${prefixo}</Prefix>` +
        `<KeyCount>${pagina.length}</KeyCount><IsTruncated>${truncada}</IsTruncated>` +
        pagina
          .map(
            (c) =>
              `<Contents><Key>${c}</Key><Size>${this.objectos.get(c)!.bytes.length}</Size></Contents>`,
          )
          .join("") +
        (truncada ? `<NextContinuationToken>${pagina.at(-1)}</NextContinuationToken>` : "") +
        "</ListBucketResult>",
    );
  }
}

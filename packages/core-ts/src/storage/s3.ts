/**
 * `MotorS3` — motor sobre a API S3, por HTTP (KAM-011).
 *
 * Fala com qualquer servidor que implemente o subconjunto abaixo: **qual** é
 * configuração (`config.ts`), e a decisão D6 — SeaweedFS auto-alojado ou S3
 * gerido — fica onde está, aberta. O que foi exercitado contra um servidor
 * real está em `docs/evidencia/KAM-011-seaweedfs.md`; contra um S3 gerido
 * **nada foi verificado**.
 *
 * Subconjunto usado, e mais nenhum:
 *
 * | Operação | Pedido |
 * |---|---|
 * | escrita simples | `PUT /{bucket}/{chave}` |
 * | escrita em partes | `POST ?uploads`, `PUT ?partNumber&uploadId`, `POST ?uploadId`, `DELETE ?uploadId` |
 * | leitura | `GET /{bucket}/{chave}`, `HEAD /{bucket}/{chave}` |
 * | eliminação | `DELETE /{bucket}/{chave}` |
 * | listagem | `GET /{bucket}?list-type=2&prefix=…` |
 * | URL de leitura | SigV4 por *query*, só `GET` |
 *
 * Endereçamento **por caminho** (`{endpoint}/{bucket}/{chave}`), que é o que o
 * SeaweedFS serve sem DNS por *bucket*. O estilo *virtual-hosted* não está
 * implementado: um S3 gerido que só aceite esse estilo precisa de mais código,
 * e isso é um dado para a D6, não um pormenor.
 *
 * Um corpo até `tamanhoDaParte` vai num pedido só; acima disso vai em partes.
 * O objecto não é junto em memória: fica o que ainda não foi enviado — menos de
 * uma parte, mais o bloco que quem chama acabou de entregar — e a parte que
 * está a ser enviada. Quem entrega o objecto inteiro num só bloco tem-no
 * inteiro em memória, e isso este módulo não muda.
 */

import { createHash } from "node:crypto";

import type { Escrito, InfoBruta, ItemListado, MetaBruta, Motor } from "./motor.ts";
import { ArmazenamentoIndisponivelError, ObjectoInexistenteError } from "./port.ts";
import { type Credenciais, assinarPedido, codificar, presignarGet } from "./sigv4.ts";

/** Mínimo que o S3 aceita numa parte que não seja a última: 5 MiB. */
export const PARTE_MINIMA = 5 * 1024 * 1024;

/**
 * Tamanho de parte por omissão: 16 MiB.
 *
 * Com este valor um objecto de 10 MB vai num pedido e um de 25 MB vai em duas
 * partes — que é a fronteira que o critério de aceitação 2 quer ver dos dois
 * lados. É *proposta*: o limite de média do WhatsApp e a memória do *worker*
 * calibram-no no KAM-020.
 */
export const PARTE_POR_OMISSAO = 16 * 1024 * 1024;

/** Páginas de listagem: o máximo que o S3 devolve por pedido. */
const PAGINA = 1000;

/** Quanto do corpo de um erro se lê à procura do `<Code>`. */
const LIMITE_DO_ERRO = 64 * 1024;

/** Prefixo dos cabeçalhos de metadados do utilizador. */
const PREFIXO_META = "x-amz-meta-";

/** Um pedido HTTP, na forma mínima de que o motor precisa. */
export interface PedidoHttp {
  readonly metodo: string;
  readonly url: string;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly corpo?: Uint8Array;
}

/** Uma resposta HTTP. Os nomes dos cabeçalhos vêm em minúsculas. */
export interface RespostaHttp {
  readonly estado: number;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly corpo: AsyncIterable<Uint8Array>;
}

/**
 * Como o motor chega à rede.
 *
 * Injectável para que a suite de contrato corra o motor S3 **inteiro** — a
 * assinatura, o XML, as partes — contra um servidor em memória, no *gate* 4,
 * sem contentor. O transporte por omissão é o `fetch` do Node.
 */
export type Transporte = (pedido: PedidoHttp) => Promise<RespostaHttp>;

async function* vazio(): AsyncIterable<Uint8Array> {}

/** O transporte de produção: `fetch`, sem seguir redireccionamentos. */
export function transportePorFetch(tempoLimiteMs: number): Transporte {
  return async (pedido) => {
    const resposta = await fetch(pedido.url, {
      method: pedido.metodo,
      headers: pedido.cabecalhos,
      // Um redireccionamento levava o pedido assinado para outro anfitrião.
      redirect: "manual",
      signal: AbortSignal.timeout(tempoLimiteMs),
      ...(pedido.corpo === undefined ? {} : { body: pedido.corpo }),
    });
    const cabecalhos: Record<string, string> = {};
    resposta.headers.forEach((valor, nome) => {
      cabecalhos[nome.toLowerCase()] = valor;
    });
    return {
      estado: resposta.status,
      cabecalhos,
      corpo: (resposta.body as AsyncIterable<Uint8Array> | null) ?? vazio(),
    };
  };
}

export interface MotorS3Opcoes {
  /** Origem do servidor, sem caminho: `http://seaweedfs:8333`. */
  readonly endpoint: string;
  readonly bucket: string;
  readonly regiao: string;
  /**
   * De onde vêm as credenciais. Chamada **em cada pedido**: é o que deixa uma
   * rotação no cofre chegar aqui sem reiniciar o processo.
   */
  readonly credenciais: () => Promise<Credenciais>;
  readonly transporte?: Transporte;
  readonly agora?: () => Date;
  readonly tamanhoDaParte?: number;
  /** Tempo limite de cada pedido, com o `fetch`. Por omissão, 120 s (*proposta*). */
  readonly tempoLimiteMs?: number;
}

async function lerTudo(corpo: AsyncIterable<Uint8Array>, limite: number): Promise<Uint8Array> {
  const blocos: Uint8Array[] = [];
  let total = 0;
  for await (const bloco of corpo) {
    if (total < limite) blocos.push(bloco);
    total += bloco.length;
    // Continua a ler para esvaziar a resposta, mas não guarda mais.
  }
  return Buffer.concat(blocos);
}

const ENTIDADES: Readonly<Record<string, string>> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
};

/** Desfaz as entidades XML de um valor de texto. */
export function desescaparXml(texto: string): string {
  return texto.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-z]+);/g, (tudo, corpo: string) => {
    const ponto = corpo.startsWith("#x")
      ? Number.parseInt(corpo.slice(2), 16)
      : corpo.startsWith("#")
        ? Number.parseInt(corpo.slice(1), 10)
        : null;
    if (ponto === null) return ENTIDADES[corpo] ?? tudo;
    // Um ponto de código que não existe fica como veio: quem decide o que
    // fazer com um valor estranho é quem o confere a seguir.
    return Number.isInteger(ponto) && ponto <= 0x10ffff ? String.fromCodePoint(ponto) : tudo;
  });
}

/** Primeiro valor de um elemento XML simples, ou `null`. */
export function elementoXml(xml: string, nome: string): string | null {
  const m = new RegExp(`<${nome}>([^<]*)</${nome}>`).exec(xml);
  return m === null ? null : desescaparXml(m[1] as string);
}

function escaparXml(texto: string): string {
  return texto.replace(/[&<>"']/g, (c) =>
    c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&apos;",
  );
}

export class MotorS3 implements Motor {
  readonly nome = "s3";
  readonly #base: string;
  readonly #regiao: string;
  readonly #credenciais: () => Promise<Credenciais>;
  readonly #transporte: Transporte;
  readonly #agora: () => Date;
  readonly #parte: number;

  constructor(opcoes: MotorS3Opcoes) {
    const parte = opcoes.tamanhoDaParte ?? PARTE_POR_OMISSAO;
    if (!Number.isInteger(parte) || parte < PARTE_MINIMA) {
      throw new RangeError(`tamanhoDaParte tem de ser um inteiro >= ${PARTE_MINIMA} (5 MiB)`);
    }
    this.#base = `${opcoes.endpoint.replace(/\/+$/, "")}/${opcoes.bucket}`;
    this.#regiao = opcoes.regiao;
    this.#credenciais = opcoes.credenciais;
    this.#transporte = opcoes.transporte ?? transportePorFetch(opcoes.tempoLimiteMs ?? 120_000);
    this.#agora = opcoes.agora ?? (() => new Date());
    this.#parte = parte;
  }

  async put(chave: string, corpo: AsyncIterable<Uint8Array>, meta: MetaBruta): Promise<Escrito> {
    const cabecalhos: Record<string, string> = { "content-type": meta.contentType };
    for (const [nome, valor] of Object.entries(meta.metadados)) {
      cabecalhos[PREFIXO_META + nome] = valor;
    }

    const soma = createHash("sha256");
    let tamanho = 0;
    let upload: string | null = null;
    const etags: string[] = [];
    let pendente: Uint8Array[] = [];
    let pendentes = 0;

    /** Tira os primeiros `bytes` do que está pendente; o resto fica para a parte seguinte. */
    const tirarParte = (bytes: number): Uint8Array => {
      const junto = Buffer.concat(pendente);
      const resto = junto.subarray(bytes);
      pendente = resto.length > 0 ? [resto] : [];
      pendentes = resto.length;
      return junto.subarray(0, bytes);
    };

    const enviarParte = async (bytes: Uint8Array): Promise<void> => {
      if (upload === null) {
        const aberta = await this.#pedido("put", "POST", chave, { uploads: "" }, cabecalhos);
        const xml = Buffer.from(await lerTudo(aberta.corpo, LIMITE_DO_ERRO)).toString("utf8");
        const id = elementoXml(xml, "UploadId");
        if (id === null || id === "") {
          throw new ArmazenamentoIndisponivelError("put", aberta.estado, "SemUploadId");
        }
        upload = id;
      }
      const numero = etags.length + 1;
      const resposta = await this.#pedido(
        "put",
        "PUT",
        chave,
        { partNumber: String(numero), uploadId: upload },
        {},
        bytes,
      );
      await lerTudo(resposta.corpo, 0);
      const etag = resposta.cabecalhos["etag"];
      if (etag === undefined || etag === "") {
        throw new ArmazenamentoIndisponivelError("put", resposta.estado, "SemETag");
      }
      etags.push(etag);
    };

    try {
      for await (const bloco of corpo) {
        soma.update(bloco);
        tamanho += bloco.length;
        pendente.push(bloco);
        pendentes += bloco.length;
        // `>` e não `>=`: um corpo com exactamente o tamanho de uma parte vai
        // num pedido só. Só se abre um envio em partes quando se sabe que há
        // mais do que uma.
        while (pendentes > this.#parte) {
          await enviarParte(tirarParte(this.#parte));
        }
      }
      if (upload === null) {
        const resposta = await this.#pedido("put", "PUT", chave, {}, cabecalhos, tirarParte(pendentes));
        await lerTudo(resposta.corpo, 0);
      } else {
        await enviarParte(tirarParte(pendentes));
        const fecho =
          "<CompleteMultipartUpload>" +
          etags
            .map(
              (etag, i) =>
                `<Part><PartNumber>${i + 1}</PartNumber><ETag>${escaparXml(etag)}</ETag></Part>`,
            )
            .join("") +
          "</CompleteMultipartUpload>";
        const resposta = await this.#pedido(
          "put",
          "POST",
          chave,
          { uploadId: upload },
          { "content-type": "application/xml" },
          Buffer.from(fecho, "utf8"),
        );
        // O S3 pode responder 200 a um fecho que falhou, com o erro no corpo.
        const xml = Buffer.from(await lerTudo(resposta.corpo, LIMITE_DO_ERRO)).toString("utf8");
        if (/<Error>/.test(xml)) {
          throw new ArmazenamentoIndisponivelError("put", resposta.estado, elementoXml(xml, "Code"));
        }
      }
    } catch (erro) {
      if (upload !== null) {
        // Um envio em partes abandonado ocupa espaço até alguém o abortar.
        // O melhor esforço fica aqui; o erro que sobe é o original.
        try {
          const aborto = await this.#transporte(
            await this.#assinado("DELETE", chave, { uploadId: upload }, {}, undefined),
          );
          await lerTudo(aborto.corpo, 0);
        } catch {
          // Sem mais o que fazer: a limpeza de envios órfãos é do servidor.
        }
      }
      throw erro;
    }
    return { tamanho, sha256: soma.digest("hex") };
  }

  async get(chave: string): Promise<AsyncIterable<Uint8Array>> {
    const resposta = await this.#pedido("get", "GET", chave, {}, {});
    return resposta.corpo;
  }

  async head(chave: string): Promise<InfoBruta> {
    const resposta = await this.#pedido("head", "HEAD", chave, {}, {});
    await lerTudo(resposta.corpo, 0);
    const metadados: Record<string, string> = {};
    for (const [nome, valor] of Object.entries(resposta.cabecalhos)) {
      if (nome.startsWith(PREFIXO_META)) metadados[nome.slice(PREFIXO_META.length)] = valor;
    }
    const tamanhoBruto = resposta.cabecalhos["content-length"];
    const tamanho = Number(tamanhoBruto);
    if (tamanhoBruto === undefined || !/^[0-9]+$/.test(tamanhoBruto)) {
      throw new ArmazenamentoIndisponivelError("head", resposta.estado, "SemContentLength");
    }
    return {
      tamanho,
      contentType: resposta.cabecalhos["content-type"] ?? "application/octet-stream",
      metadados,
    };
  }

  async delete(chave: string): Promise<void> {
    const resposta = await this.#pedido("delete", "DELETE", chave, {}, {}, undefined, true);
    await lerTudo(resposta.corpo, 0);
  }

  async list(
    prefixo: string,
    maximo: number,
  ): Promise<{ readonly itens: readonly ItemListado[]; readonly truncada: boolean }> {
    const itens: ItemListado[] = [];
    let continuacao: string | null = null;
    for (;;) {
      const query: Record<string, string> = {
        "list-type": "2",
        prefix: prefixo,
        "max-keys": String(Math.min(PAGINA, maximo - itens.length)),
      };
      if (continuacao !== null) query["continuation-token"] = continuacao;
      const resposta = await this.#pedido("list", "GET", null, query, {});
      const xml = Buffer.from(await lerTudo(resposta.corpo, Number.MAX_SAFE_INTEGER)).toString(
        "utf8",
      );
      for (const m of xml.matchAll(/<Contents>(.*?)<\/Contents>/gs)) {
        const chave = elementoXml(m[1] as string, "Key");
        const tamanhoBruto = elementoXml(m[1] as string, "Size");
        // `Number(null)` é 0: uma entrada sem tamanho passava por objecto vazio.
        if (chave === null || tamanhoBruto === null || !/^[0-9]+$/.test(tamanhoBruto)) {
          throw new ArmazenamentoIndisponivelError("list", resposta.estado, "ListagemIlegivel");
        }
        itens.push({ chave, tamanho: Number(tamanhoBruto) });
      }
      const truncada = elementoXml(xml, "IsTruncated") === "true";
      continuacao = elementoXml(xml, "NextContinuationToken");
      if (!truncada) return { itens, truncada: false };
      if (itens.length >= maximo) return { itens: itens.slice(0, maximo), truncada: true };
      if (continuacao === null || continuacao === "") {
        // Truncada e sem forma de continuar: não se devolve meia listagem.
        throw new ArmazenamentoIndisponivelError("list", resposta.estado, "SemContinuacao");
      }
    }
  }

  async signUrl(chave: string, ttlSegundos: number): Promise<string> {
    return presignarGet({
      url: new URL(`${this.#base}/${chave}`),
      credenciais: await this.#credenciais(),
      regiao: this.#regiao,
      agora: this.#agora(),
      expiraS: ttlSegundos,
    });
  }

  async #assinado(
    metodo: string,
    chave: string | null,
    query: Readonly<Record<string, string>>,
    cabecalhos: Readonly<Record<string, string>>,
    corpo: Uint8Array | undefined,
  ): Promise<PedidoHttp> {
    // A *query* escreve-se em RFC 3986, à mão: o `URLSearchParams` escreve o
    // espaço como `+` e deixa `*` em claro, o Python não, e um S3 estrito pode
    // canonicalizar de outra maneira o que vê na rede.
    const pares = Object.entries(query).map(([nome, valor]) => `${codificar(nome)}=${codificar(valor)}`);
    const url = new URL(
      (chave === null ? this.#base : `${this.#base}/${chave}`) +
        (pares.length === 0 ? "" : `?${pares.join("&")}`),
    );
    const assinados = assinarPedido({
      metodo,
      url,
      cabecalhos,
      ...(corpo === undefined ? {} : { corpo }),
      credenciais: await this.#credenciais(),
      regiao: this.#regiao,
      agora: this.#agora(),
    });
    // O `fetch` escreve o seu próprio `Host` a partir da URL, e é esse que foi
    // assinado; mandá-lo outra vez é, em alguns clientes, um erro.
    delete assinados["host"];
    return {
      metodo,
      url: url.toString(),
      cabecalhos: assinados,
      ...(corpo === undefined ? {} : { corpo }),
    };
  }

  /**
   * Um pedido assinado, com os erros traduzidos.
   *
   * 404 num objecto é `ObjectoInexistenteError` (ou sucesso, num `DELETE`); um
   * 404 com `NoSuchBucket` **não** é — é configuração errada, e tratá-lo como
   * «objecto inexistente» escondia um *bucket* em falta atrás de uma resposta
   * que o código de negócio trata como normal.
   */
  async #pedido(
    operacao: string,
    metodo: string,
    chave: string | null,
    query: Readonly<Record<string, string>>,
    cabecalhos: Readonly<Record<string, string>>,
    corpo?: Uint8Array,
    inexistenteServe = false,
  ): Promise<RespostaHttp> {
    // Fora do `try`: um segredo ausente no cofre sobe tal como é — nomeia a
    // referência, nunca o valor — em vez de se disfarçar de falha de rede.
    const assinado = await this.#assinado(metodo, chave, query, cabecalhos, corpo);
    let resposta: RespostaHttp;
    try {
      resposta = await this.#transporte(assinado);
    } catch {
      // A causa não sobe: a mensagem de um erro de rede pode trazer a URL.
      throw new ArmazenamentoIndisponivelError(operacao, null, null);
    }
    if (resposta.estado >= 200 && resposta.estado < 300) return resposta;
    const xml = Buffer.from(await lerTudo(resposta.corpo, LIMITE_DO_ERRO)).toString("utf8");
    const codigo = elementoXml(xml, "Code");
    if (resposta.estado === 404 && chave !== null && codigo !== "NoSuchBucket") {
      if (inexistenteServe) return { ...resposta, corpo: vazio() };
      throw new ObjectoInexistenteError();
    }
    throw new ArmazenamentoIndisponivelError(operacao, resposta.estado, codigo);
  }
}

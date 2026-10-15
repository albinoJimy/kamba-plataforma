/**
 * `ArmazenamentoPorTenant` — a guarda de isolamento do armazenamento (KAM-011).
 *
 * É a **única** implementação de `StorageProvider`. O *fake* e o S3 são motores
 * diferentes por baixo da mesma guarda, e por isso recusam exactamente as
 * mesmas coisas pela mesma ordem: não há uma segunda cópia das regras para
 * ficar para trás.
 *
 * O que esta classe garante, por operação:
 *
 * | Operação | Antes de falar com o motor | Depois |
 * |---|---|---|
 * | `put` | contexto, forma da chave, dono da chave, metadados, classe = segmento | — |
 * | `get`, `head`, `delete`, `signUrl` | contexto, forma, dono | `head`: classe devolvida = segmento |
 * | `list` | contexto, prefixo começa por `t/{tenant}/` | **cada** chave devolvida está sob o prefixo pedido |
 *
 * A verificação «depois» da listagem é a segunda camada do X-08
 * (`docs/tecnica/08` §3.7): se um motor ou um servidor devolver uma chave de
 * outro tenant — por defeito de paginação, de prefixo ou de *proxy* —, a
 * listagem **falha inteira** em vez de devolver o que não devia. A primeira
 * camada é o prefixo; esta existe para o dia em que a primeira falhar.
 *
 * **Não regista nada**: nem o tenant, nem a chave, nem o erro. O DoD proíbe
 * associar `tenant_id` a conteúdo em *logs*, e uma chave contém o `tenant_id`.
 */

import { chaveDoCtx, prefixoDoCtx, validarClasse } from "./chave.ts";
import type { Motor } from "./motor.ts";
import {
  type Corpo,
  type Ctx,
  LIMITE_DE_LISTAGEM,
  ListagemTruncadaError,
  MetaInvalidaError,
  type ObjectInfo,
  type ObjectKey,
  type ObjectMeta,
  type ObjectRef,
  RespostaDoMotorInvalidaError,
  type StorageProvider,
  TTL_MAXIMO_S,
  TtlInvalidoError,
} from "./port.ts";

/** Nome do metadado que guarda a classe. */
export const META_CLASSE = "classe";

/**
 * Nome do metadado que guarda `retain_until`.
 *
 * Com hífen e não com sublinhado: vai num cabeçalho HTTP (`x-amz-meta-…`), e há
 * *proxies* que descartam cabeçalhos com sublinhado sem avisar. O conceito
 * chama-se `retain_until` em todo o lado menos neste nome de cabeçalho.
 */
export const META_RETAIN_UNTIL = "retain-until";

/** Tecto do `limite` de uma listagem. */
export const LIMITE_MAXIMO_DE_LISTAGEM = 10_000;

/**
 * Forma aceite de um tipo de conteúdo: `tipo/subtipo`, com parâmetros
 * opcionais (`audio/ogg; codecs=opus`). Lista fechada de caracteres, porque o
 * valor vai num cabeçalho: nem CR, nem LF, nem nada que termine a linha.
 */
const TIPO_DE_CONTEUDO =
  /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}(; ?[A-Za-z0-9_-]{1,32}=[A-Za-z0-9_.+-]{1,64}){0,4}$/;

/**
 * Forma de um instante guardado: `2026-10-13T08:30:00.000Z`, a que o
 * `toISOString()` escreve, e **só** essa: ano de quatro dígitos, milissegundos,
 * `Z`. O `Date` do JavaScript lê muito mais (`"2026"`, `"13 Oct"`) e corrige em
 * silêncio o que não existe (30 de Fevereiro vira 2 de Março); o lado Python
 * não. Por isso os dois lados só aceitam o que, relido, dá a mesma cadeia.
 */
const INSTANTE = /^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/;

/** O instante de uma cadeia na forma canónica, ou `null`. */
export function lerInstante(texto: unknown): Date | null {
  if (typeof texto !== "string" || !INSTANTE.test(texto)) return null;
  const instante = new Date(texto);
  if (Number.isNaN(instante.getTime()) || instante.toISOString() !== texto) return null;
  return instante;
}

/**
 * Passa os blocos adiante, e recusa o primeiro que não seja de bytes.
 *
 * Sem isto, um bloco de texto era somado como texto e guardado como outra
 * coisa: a soma que `put` devolvia não era a do que ficava no servidor.
 */
async function* soBytes(corpo: AsyncIterable<unknown>): AsyncIterable<Uint8Array> {
  for await (const bloco of corpo) {
    if (!(bloco instanceof Uint8Array)) {
      throw new MetaInvalidaError(
        "o corpo tem de ser Uint8Array ou um iterável assíncrono de Uint8Array",
      );
    }
    yield bloco;
  }
}

async function* umBloco(bytes: Uint8Array): AsyncIterable<Uint8Array> {
  yield bytes;
}

function comoFluxo(body: Corpo): AsyncIterable<Uint8Array> {
  if (body instanceof Uint8Array) return umBloco(body);
  if (body !== null && typeof body === "object" && Symbol.asyncIterator in body) return soBytes(body);
  throw new MetaInvalidaError("o corpo tem de ser Uint8Array ou um iterável assíncrono de Uint8Array");
}

function chaveDaRef(ref: ObjectRef): unknown {
  return (ref as { key?: unknown } | null | undefined)?.key;
}

export class ArmazenamentoPorTenant implements StorageProvider {
  readonly #motor: Motor;

  constructor(motor: Motor) {
    this.#motor = motor;
  }

  get nome(): string {
    return this.#motor.nome;
  }

  async put(ctx: Ctx, key: ObjectKey, body: Corpo, meta: ObjectMeta): Promise<ObjectRef> {
    const partes = chaveDoCtx(ctx, key, "put");
    if (meta === null || typeof meta !== "object") {
      throw new MetaInvalidaError("faltam os metadados (contentType, classe, retainUntil)");
    }
    const classe = validarClasse(meta.classe);
    if (classe !== partes.classe) {
      throw new MetaInvalidaError("a classe dos metadados não coincide com a da chave");
    }
    if (typeof meta.contentType !== "string" || !TIPO_DE_CONTEUDO.test(meta.contentType)) {
      throw new MetaInvalidaError("contentType tem de ser tipo/subtipo");
    }
    const prazo: unknown = meta.retainUntil;
    if (!(prazo instanceof Date) || Number.isNaN(prazo.getTime())) {
      throw new MetaInvalidaError("retainUntil é obrigatório e tem de ser uma data válida");
    }
    // Só se escreve o que se consegue ler de volta: um prazo que o `head`
    // recusasse era um objecto que a purga nunca veria.
    const prazoTexto = prazo.toISOString();
    if (lerInstante(prazoTexto) === null) {
      throw new MetaInvalidaError("retainUntil tem de ter o ano entre 1000 e 9999, em UTC");
    }
    const escrito = await this.#motor.put(key, comoFluxo(body), {
      contentType: meta.contentType,
      metadados: {
        [META_CLASSE]: classe,
        [META_RETAIN_UNTIL]: prazoTexto,
      },
    });
    return { key, tamanho: escrito.tamanho, sha256: escrito.sha256 };
  }

  async get(ctx: Ctx, ref: ObjectRef): Promise<AsyncIterable<Uint8Array>> {
    const key = chaveDaRef(ref);
    chaveDoCtx(ctx, key, "get");
    return this.#motor.get(key as string);
  }

  async head(ctx: Ctx, ref: ObjectRef): Promise<ObjectInfo> {
    const key = chaveDaRef(ref);
    const partes = chaveDoCtx(ctx, key, "head");
    const info = await this.#motor.head(key as string);
    const classe = info.metadados[META_CLASSE];
    const prazoBruto = info.metadados[META_RETAIN_UNTIL];
    if (classe !== partes.classe) {
      throw new RespostaDoMotorInvalidaError("o objecto não traz a classe da sua chave");
    }
    const prazo = lerInstante(prazoBruto);
    if (prazo === null) {
      throw new RespostaDoMotorInvalidaError("o objecto não traz um retain_until legível");
    }
    return {
      key: key as string,
      tamanho: info.tamanho,
      contentType: info.contentType,
      classe,
      retainUntil: prazo,
    };
  }

  async signUrl(ctx: Ctx, ref: ObjectRef, o: { readonly ttlSeconds: number }): Promise<string> {
    const key = chaveDaRef(ref);
    chaveDoCtx(ctx, key, "signUrl");
    const ttl: unknown = (o as { ttlSeconds?: unknown } | null | undefined)?.ttlSeconds;
    if (typeof ttl !== "number" || !Number.isInteger(ttl) || ttl < 1 || ttl > TTL_MAXIMO_S) {
      throw new TtlInvalidoError();
    }
    return this.#motor.signUrl(key as string, ttl);
  }

  async delete(ctx: Ctx, ref: ObjectRef): Promise<void> {
    const key = chaveDaRef(ref);
    chaveDoCtx(ctx, key, "delete");
    await this.#motor.delete(key as string);
  }

  async list(
    ctx: Ctx,
    prefix: string,
    o: { readonly limite?: number } = {},
  ): Promise<ObjectRef[]> {
    const prefixo = prefixoDoCtx(ctx, prefix);
    // `o` e `o.limite` vêm de quem chama, que pode não ser TypeScript.
    const pedido: unknown =
      (o as { limite?: unknown } | null | undefined)?.limite ?? LIMITE_DE_LISTAGEM;
    const limite = typeof pedido === "number" ? pedido : Number.NaN;
    if (!Number.isInteger(limite) || limite < 1 || limite > LIMITE_MAXIMO_DE_LISTAGEM) {
      throw new MetaInvalidaError(
        `limite tem de ser um inteiro entre 1 e ${LIMITE_MAXIMO_DE_LISTAGEM}`,
      );
    }
    const { itens, truncada } = await this.#motor.list(prefixo, limite);
    const refs: ObjectRef[] = [];
    for (const item of itens) {
      // Segunda camada: o que o motor devolve é conferido, e não só o que se
      // lhe pediu. Uma chave fora do prefixo falha a listagem inteira.
      if (typeof item.chave !== "string" || !item.chave.startsWith(prefixo)) {
        throw new RespostaDoMotorInvalidaError("a listagem devolveu uma chave fora do prefixo pedido");
      }
      refs.push({ key: item.chave, tamanho: item.tamanho, sha256: null });
    }
    if (truncada || refs.length > limite) {
      throw new ListagemTruncadaError(limite);
    }
    return refs;
  }
}

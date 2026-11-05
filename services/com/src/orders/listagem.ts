/**
 * As duas leituras da porta: `getOrder` e `listOrders`, com o cursor opaco
 * (KAM-178, critérios 3 e 4).
 *
 * ```text
 * getOrder(ctx, orderId)  -> OrderView            SQL_VISTA
 * listOrders(ctx, filtro) -> Page<OrderView>      SQL_LISTAR
 * ```
 *
 * ## O cursor é **assinado**, e é isso que faz de um cursor forjado um erro
 *
 * O ISO-10 pede três coisas ao `listOrders`: filtro vazio, cursor forjado e um
 * `OR` injectado dão `VALIDATION_ERROR` e **nunca** devolvem a linha de outro
 * tenant. As três são barreiras diferentes e nenhuma dispensa as outras:
 *
 * ```text
 * filtro vazio    recusa-se antes de haver consulta  (ver `LISTAGEM_SEM_FILTRO`)
 * cursor forjado  o HMAC não bate, e o tenant está dentro do HMAC
 * OR injectado    os valores são parametrizados, e a forma recusa-os antes disso
 * ```
 *
 * **O `tenant_id` entra no HMAC do cursor**, e não é zelo: sem ele, o cursor de
 * um tenant era um cursor válido para outro — e, embora a consulta saia sempre
 * filtrada pelo repo-base e com RLS atrás, aceitar a *posição* de outro tenant
 * dizia a quem a tivesse que aquela encomenda existe. É a mesma razão pela qual
 * o `cart_id` do `intents.ts` leva uma parte de domínio: conhecer um não dá o
 * outro.
 *
 * A chave é a do anel do `segredo_intents` (§3.44), com a parte de domínio
 * `cursor` à cabeça — **a mesma derivação do `cart_id`**, e por isso o mesmo
 * segredo não produz os mesmos valores para os dois. Um segredo próprio para
 * cursores era uma entrada a mais no inventário para uma propriedade que esta
 * derivação já dá; a separação está no domínio e não na chave, que é exactamente
 * o que o `cartId` escreveu primeiro.
 *
 * **A verificação percorre o anel inteiro**, pela razão do `chavesDoAnel`: uma
 * rotação a meio de uma paginação não pode invalidar a página seguinte, porque o
 * cliente não tem como saber que o segredo rodou.
 *
 * ## O que este ficheiro não faz
 *
 * Não abre transacção (é o `comRegisto` do adaptador), não escreve nada, e não
 * decide o tecto de uma página acima de `LIMITE_MAXIMO` — recusa-o, em vez de o
 * cortar em silêncio: um `limite: 10000` atendido com 100 linhas dizia a quem
 * chama que o tenant só tem 100 encomendas.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import {
  ORDER_STATES,
  erro,
  eUuid,
  ok,
  type OrderFilter,
  type OrderState,
  type OrderView,
  type Page,
  type ResultadoFinal,
} from "../port/contrato.ts";
import type { LinhaDaEncomenda } from "./contrato.ts";
import { SQL_LISTAR, SQL_VISTA } from "./consultas.ts";
import { concatenar, lerSegredo, type AnelDoSegredo } from "./intents.ts";
import type { Leitura } from "./cart.ts";

/** A parte de domínio do cursor. Ver a nota do módulo e o `cartId`. */
export const DOMINIO_DO_CURSOR = "cursor";

/** Quantos octetos do HMAC vão no cursor. Dezasseis — 128 bits. */
export const OCTETOS_DA_ASSINATURA = 16;

/** Quantas linhas uma página traz por omissão. */
export const LIMITE_POR_OMISSAO = 20;

/**
 * O tecto de uma página. **Cem**, e é *proposta*.
 *
 * O §3.2 não fixa um número e nenhuma medição o fixou; cem é o que cabe numa
 * resposta de API interna sem a tornar o caminho mais caro de uma conversa.
 * Calibra-se no **KAM-096**, com dados do Piloto, pela mesma via dos tectos do
 * `ManualProvider`.
 */
export const LIMITE_MAXIMO = 100;

/** A posição de uma página: a linha a partir da qual a seguinte continua. */
export interface PosicaoDaPagina {
  readonly criadoAt: string;
  readonly id: string;
}

/** A base64 sem *padding* e sem `+` nem `/`: um cursor viaja em JSON e em URL. */
function emBase64Url(bruto: Buffer): string {
  return bruto.toString("base64url");
}

function deBase64Url(texto: string): Buffer | null {
  if (!/^[A-Za-z0-9_-]+$/.test(texto)) return null;
  return Buffer.from(texto, "base64url");
}

/** A assinatura de uma posição, para um tenant e uma versão do segredo. */
function assinar(
  valorDoSegredo: string,
  tenantId: string,
  posicao: PosicaoDaPagina,
): Buffer {
  const { chave } = lerSegredo(valorDoSegredo);
  return createHmac("sha256", chave)
    .update(
      // **Pelo `concatenar` e não por um `join`**, e é a razão do `intents.ts`:
      // com um separador literal, duas partições diferentes das mesmas partes
      // dão a mesma assinatura — aqui, a posição de um tenant a servir de
      // posição a outro.
      concatenar([DOMINIO_DO_CURSOR, tenantId, posicao.criadoAt, posicao.id]),
    )
    .digest()
    .subarray(0, OCTETOS_DA_ASSINATURA);
}

/**
 * O cursor opaco de uma posição. **Assina com a versão actual do anel.**
 *
 * Opaco para quem o recebe: «não se interpreta, não se valida pela forma, e não
 * se deriva de nada» (§3.28 para o `cart_id`, e vale igual aqui).
 */
export function cifrarCursor(
  anel: AnelDoSegredo,
  tenantId: string,
  posicao: PosicaoDaPagina,
): string {
  const corpo = Buffer.from(`${posicao.criadoAt}|${posicao.id}`, "utf8");
  const mac = assinar(anel[0], tenantId, posicao);
  return `${emBase64Url(corpo)}.${emBase64Url(mac)}`;
}

/**
 * A posição de um cursor, ou `null` se ele não for nosso.
 *
 * Quatro recusas, e a ordem é a mais barata primeiro: a forma, a descodificação,
 * a validação das duas partes e só então o HMAC. **A comparação do HMAC é em
 * tempo constante** (`timingSafeEqual`): o candidato vem de fora, e uma
 * comparação que sai no primeiro octeto diferente mede quantos acertou.
 *
 * **Valida as partes antes de verificar a assinatura, e depois também.** Antes,
 * porque uma parte sem forma não precisa de HMAC para ser recusada; e a
 * assinatura é sobre as partes **já lidas**, pelo que um corpo que a satisfaça
 * só pode ter saído daqui.
 */
export function lerCursor(
  anel: AnelDoSegredo,
  tenantId: string,
  cursor: string,
): PosicaoDaPagina | null {
  const partes = cursor.split(".");
  if (partes.length !== 2) return null;
  const corpo = deBase64Url(partes[0] as string);
  const mac = deBase64Url(partes[1] as string);
  if (corpo === null || mac === null) return null;
  if (mac.length !== OCTETOS_DA_ASSINATURA) return null;

  const texto = corpo.toString("utf8");
  const divisor = texto.lastIndexOf("|");
  if (divisor <= 0) return null;
  const criadoAt = texto.slice(0, divisor);
  const id = texto.slice(divisor + 1);
  if (!eUuid(id) || !Number.isFinite(Date.parse(criadoAt))) return null;

  const posicao: PosicaoDaPagina = { criadoAt, id: id.toLowerCase() };
  for (const valor of anel) {
    if (valor === null) continue;
    let esperado: Buffer;
    try {
      esperado = assinar(valor, tenantId, posicao);
    } catch {
      // Um elemento do anel mal formado não invalida o outro: é a letra do
      // `SecretRing` do `secrets/port.ts` — quem lê aceita as duas versões.
      continue;
    }
    if (timingSafeEqual(esperado, mac)) return posicao;
  }
  return null;
}

/** Uma linha de `orders_mirror` na forma da `OrderView` do §3.2. */
export function comoVista(
  linha: Readonly<Record<string, unknown>>,
): OrderView {
  const bruto = linha["lines_snapshot"];
  const snapshot = (
    typeof bruto === "string" ? JSON.parse(bruto) : (bruto ?? [])
  ) as readonly Record<string, unknown>[];
  return {
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    estado: String(linha["estado"]) as OrderState,
    version: Number(linha["version"]),
    contactId: String(linha["contact_id"]),
    // **`bigint` e não `number`**, pela nota da `OrderView`: o `money_lint` não
    // morde no `services/com`, e um `number` perdia precisão acima de 2^53
    // cêntimos sem avisar.
    totalMinor: BigInt(String(linha["total_minor"])),
    currency: String(linha["currency"]),
    linhas: snapshot.map(comoLinha),
    criadoAt: instante(linha["criado_at"]),
  };
}

/**
 * Uma linha do `lines_snapshot`, com os nomes do §5.4.
 *
 * O tipo do campo na `OrderView` é `Record<string, unknown>` e **não** se
 * estreita aqui: a forma do *snapshot* é da revisão `0030` e quem a fecha é o
 * KAM-044. O que esta função faz é normalizar os nomes — os da
 * `LinhaDaEncomenda`, que é a forma que o módulo já tem — para que o `getOrder`
 * e o `listOrders` devolvam a mesma coisa: um projector e não dois.
 */
function comoLinha(
  item: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  const linha: LinhaDaEncomenda = {
    sku: String(item["sku"]),
    nome: String(item["nome"] ?? ""),
    qty: Number(item["qty"]),
    precoMinor: BigInt(String(item["preco_minor"])),
    precoTipo: String(item["preco_tipo"]),
    origemPreco: String(item["origem_preco"]),
  };
  return { ...linha };
}

function instante(valor: unknown): string {
  return valor instanceof Date ? valor.toISOString() : String(valor);
}

/**
 * `getOrder`: a `OrderView` de uma encomenda do tenant do `ctx`.
 *
 * `NOT_FOUND` cobre as duas ausências — não existe, ou é de outro tenant — e
 * **isso é deliberado**: distingui-las era um oráculo («esta encomenda existe,
 * tua é que não é»), que é exactamente a pergunta que o ISO-01..08 faz. É a
 * mesma escolha que o `get_order_status` da TLS escreveu para o seu próprio
 * âmbito.
 */
export async function getOrder(
  l: Leitura,
  orderId: string,
): Promise<ResultadoFinal<OrderView>> {
  if (!eUuid(orderId)) return erro("VALIDATION_ERROR");
  const linhas = await l.repo.noTenant(SQL_VISTA, [orderId]);
  const linha = linhas[0];
  if (linha === undefined) return erro("NOT_FOUND");
  return ok(comoVista(linha));
}

/**
 * Porque é que um filtro **vazio** é uma recusa e não «lista tudo».
 *
 * O ISO-10 escreve «filtro vazio» entre os três casos que dão
 * `VALIDATION_ERROR`, e a razão é de desenho e não de forma: a `OrderFilter` do
 * §3.2 tem dois filtros de domínio (`estado`, `contactId`) e nenhum deles é
 * opcional *em conjunto*. Uma listagem sem nenhum varre as encomendas inteiras
 * de um tenant por uma chamada de agente — e o único consumidor desta porta é um
 * grafo que responde a um cliente, que pergunta sempre por um dos dois.
 *
 * O `cursor` e o `limite` **não contam** como filtro: são paginação, e um cursor
 * sozinho não diz o que se está a listar.
 */
export const LISTAGEM_SEM_FILTRO = "VALIDATION_ERROR";

/** O filtro já lido: o que o `SQL_LISTAR` precisa, nada mais. */
export interface FiltroLido {
  readonly estado: OrderState | null;
  readonly contactId: string | null;
  readonly limite: number;
  readonly posicao: PosicaoDaPagina | null;
}

/**
 * O filtro lido, ou o erro. **Pura, e é isso que a torna utilizável cedo.**
 *
 * Não toca na base e não precisa de transacção: só precisa do anel e do tenant,
 * e os dois existem antes de se abrir uma. É o que permite ao adaptador recusar
 * os três casos do ISO-10 **antes** de custar uma ligação — «o que falha, falha
 * antes de custar uma ligação», que é a regra que o `comRegisto` escreve para o
 * `exigirCtx` e que vale igual aqui.
 *
 * Existe como função e não repetida nos dois sítios porque uma segunda cópia da
 * validação divergia: o adaptador recusava uma coisa e o módulo outra, e o que
 * chegava à base dependia de qual delas se tinha esquecido.
 */
export function filtroLido(
  anel: AnelDoSegredo,
  tenantId: string,
  f: OrderFilter,
): ResultadoFinal<FiltroLido> {
  const filtro = f ?? {};

  const estado = filtro.estado ?? null;
  if (estado !== null && !(ORDER_STATES as readonly string[]).includes(estado)) {
    // Um `estado` fora dos doze é o caminho do `OR` injectado: o valor é
    // parametrizado de qualquer modo, e a forma recusa-o antes de haver
    // consulta.
    return erro("VALIDATION_ERROR");
  }

  const contactId = filtro.contactId ?? null;
  if (contactId !== null && !eUuid(contactId)) return erro("VALIDATION_ERROR");

  if (estado === null && contactId === null) {
    return erro(LISTAGEM_SEM_FILTRO);
  }

  const limite = filtro.limite ?? LIMITE_POR_OMISSAO;
  if (!Number.isInteger(limite) || limite < 1 || limite > LIMITE_MAXIMO) {
    return erro("VALIDATION_ERROR");
  }

  let posicao: PosicaoDaPagina | null = null;
  if (filtro.cursor !== undefined && filtro.cursor !== null) {
    posicao = lerCursor(anel, tenantId, filtro.cursor);
    // **Um cursor que não é nosso é `VALIDATION_ERROR` e não uma primeira
    // página.** Servir a primeira página a quem mandou um cursor forjado dizia
    // «este cursor vale» a quem o forjou.
    if (posicao === null) return erro("VALIDATION_ERROR");
  }

  return ok({ estado, contactId, limite, posicao });
}

/**
 * `listOrders`: uma página de `OrderView`, com cursor opaco.
 *
 * Ver a nota do módulo para as três barreiras do ISO-10, e o `SQL_LISTAR` para
 * a razão dos `COALESCE` e do desempate pelo `id`.
 */
export async function listOrders(
  l: Leitura,
  anel: AnelDoSegredo,
  f: OrderFilter,
): Promise<ResultadoFinal<Page<OrderView>>> {
  const lido = filtroLido(anel, l.ctx.tenantId, f);
  if (lido.tipo === "erro") return lido;
  const { estado, contactId, limite, posicao } = lido.valor;

  // **Pede-se uma linha a mais do que o limite**, e é o que distingue «a página
  // acabou» de «há mais»: com exactamente `limite` linhas não se sabe qual dos
  // dois, e emitir um cursor que não leva a nada obrigava o cliente a uma
  // chamada vazia para descobrir.
  const linhas = await l.repo.noTenant(SQL_LISTAR, [
    estado,
    contactId,
    posicao === null ? null : posicao.criadoAt,
    posicao === null ? null : posicao.id,
    limite + 1,
  ]);

  const pagina = linhas.slice(0, limite).map(comoVista);
  const haMais = linhas.length > limite;
  const ultima = pagina[pagina.length - 1];
  return ok({
    itens: pagina,
    proximo:
      haMais && ultima !== undefined
        ? cifrarCursor(anel, l.ctx.tenantId, {
            criadoAt: ultima.criadoAt,
            id: ultima.orderId,
          })
        : null,
  });
}

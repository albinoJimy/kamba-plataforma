/**
 * A chave de intenção e o *hash* do rascunho (KAM-046, critério 2).
 *
 * ```text
 * intent_key = base32(HMAC-SHA256(segredo_intents,
 *                                 tenant_id ⟂ contact_id ⟂ draft_id ⟂ draft_version))[:26]
 * draft_hash = SHA-256(linhas canonicalizadas ⟂ entrega_modo)
 * ```
 *
 * ## A chave é por **intenção** e não por tempo, e é isso que ela compra
 *
 * O documento exploratório derivava `hash(msisdn + sku + janela_5min)`, e o
 * Contexto do bloco enumera as três consequências: duplica a encomenda na
 * **fronteira** da janela (14:04:59 e 14:05:01 são duas janelas e dão duas
 * encomendas), **bloqueia recompras** dentro da janela (o mesmo SKU 30 s depois
 * é a mesma chave), e usa **telefone**.
 *
 * As quatro partes desta chave são as do §6.3 do `docs/tecnica/03`, e nenhuma
 * delas é tempo nem telefone — o que não é uma intenção, é uma propriedade da
 * assinatura: `PartesDaIntencao` tem exactamente quatro campos e o `tsc` recusa
 * um quinto. O `contactId` é a referência pseudonimizada do ADR-010; o telefone
 * vive cifrado em `contact_endpoints` (revisão `0003`) e não chega aqui.
 *
 * E a recíproca, que é a parte que o critério 4 mede: um **rascunho novo**
 * (`draft_id` novo) é chave nova, pelo que a recompra 30 s depois cria encomenda
 * nova; um **carrinho editado** (`draft_version` nova) é chave nova, pelo que a
 * edição cria encomenda distinta. As duas propriedades saem da mesma assinatura.
 *
 * ## O `⟂` não é um caractere separador
 *
 * É a mesma decisão que a emenda 1.37 do dicionário fixou para a chave da TLS
 * (§3.28) e que o `services/agr/src/kamba_agr/tls/idempotency.py` implementa: o
 * `|` da fórmula denota «concatenado com separação» e **não** o caractere. O
 * `draft_id` é `sha256(thread_id:turn_seq)` (§3.34) e o `contact_id` é um UUID,
 * mas a `entrega_modo` e o `sku` são texto de domínio — e com um separador
 * literal duas partições diferentes das mesmas partes dão a mesma chave, que
 * aqui é a encomenda de um cliente a responder pela de outro.
 *
 * Escreve-se por isso com o **comprimento a prefixar** cada parte, byte a byte,
 * exactamente na forma do `derivar` da TLS (`f"{len}:" + bytes`). As duas
 * barreiras do Contexto do bloco — a da TLS por `cart_id` e a do COM por
 * `intent_key` — passam a ter a mesma codificação, e não duas.
 *
 * ## O segredo é versionado, e a rotação não parte a idempotência
 *
 * O segredo vem do cofre (KAM-010) na forma de **anel** `[actual, anterior]`,
 * que é a forma que o `SecretProvider.getRing` promete. A derivação de escrita
 * usa o `actual`; a **leitura** do recibo procura pelas duas chaves do anel
 * (`chavesDoAnel`), pela razão que o `port.ts` do `secrets` escreve para o GWY:
 * um consumidor que aceita as duas versões tem de tratar o `anterior` nulo como
 * «só há uma» e não como erro.
 *
 * Sem isto, rodar o segredo mudava a `intent_key` do **mesmo** rascunho e a
 * idempotência partia-se na rotação: o cliente que tocasse duas vezes com a
 * rotação pelo meio recebia **duas** encomendas. É o mesmo desenho do anel que o
 * `kek_contact_dek` usa, e com o mesmo limite dito: a terceira versão deixa de
 * alcançar a primeira.
 *
 * **O que isto não cobre:** uma chave derivada com uma versão que já saiu do
 * anel não se volta a alcançar, e a encomenda que ela criou continua a existir
 * (a `orders_mirror.intent_key` não tem coluna de `kid`, e dar-lhe uma é alterar
 * a revisão `0030`). O efeito é o do rascunho novo: cria-se encomenda nova, e o
 * sinal de «já tem um pedido por pagar» do critério 8 é o que a torna visível ao
 * cliente em vez de silenciosa. Fica **NÃO VERIFICADO** se duas rotações dentro
 * da validade de um carrinho (30 min, *proposta* do §3.31) são alcançáveis na
 * prática — a rotação do `segredo_intents` é anual (`ops/secrets-inventory.yaml`).
 *
 * ## O `cart_id` **não** é a `intent_key`, e a separação é de domínio
 *
 * Os dois derivam das mesmas quatro partes, e por isso a tentação é fazê-los um
 * só. Não são, e a razão é que o `cart_id` sai para **fora**: vai no botão
 * `confirm:{cart_id}` (§3.31), que o cliente vê no WhatsApp e devolve. A
 * `intent_key` é a chave de unicidade de `orders_mirror` — e uma chave de
 * idempotência que o cliente conhece é uma chave que o cliente pode citar.
 *
 * Por isso o `cart_id` leva uma parte de **domínio** à cabeça (`cart`), que a
 * `intent_key` não tem: conhecer um não dá o outro, e a fórmula da `intent_key`
 * fica exactamente a que o critério 2 escreve, sem etiqueta a mais.
 *
 * **E nenhum dos dois se aceita do chamador.** O `createOrder` deste ticket
 * recebe `(draftId, draftVersion)` e **deriva**; um `cart_id` que chegue de
 * fora confronta-se por re-derivação (`cartIdValido`) e nunca se usa como
 * chave. Era o caminho pelo qual o `cart_id` de outro contacto resolvia a
 * intenção deste (ISO-57..60).
 */

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

/**
 * A referência do segredo no inventário (`ops/secrets-inventory.yaml`).
 *
 * **Este módulo não chama o cofre**, e é a mesma escolha do `transition.ts`, que
 * não abre transacção: quem monta o módulo é que sabe de onde vem o anel, e
 * pedi-lo aqui dava a este ficheiro uma decisão que não é dele. A constante
 * existe para que o nome tenha **um** dono em código — escrito duas vezes,
 * divergiu.
 */
export const REF_SEGREDO_DE_INTENTS = "segredo_intents";

/** Quantos octetos tem o segredo depois de descodificado. Como as do `identity`. */
export const OCTETOS_DO_SEGREDO = 32;

/**
 * Quantos caracteres da base32 ficam na chave. **Vinte e seis, pelo critério 2.**
 *
 * São 130 bits dos 256 que o HMAC produz, e não um corte arbitrário: 26
 * caracteres de base32 são exactamente o que cabe sem *padding* parcial na
 * última posição que interessa, e 130 bits dão uma probabilidade de colisão
 * desprezável para a população de rascunhos de um tenant. O que o corte **não**
 * faz é tornar a chave reversível: o HMAC não é invertível com ou sem corte.
 */
export const CARACTERES_DA_CHAVE = 26;

/**
 * O alfabeto de Crockford, como o `platform.order_numero_publico()` da revisão
 * `0030`.
 *
 * **O mesmo alfabeto e não outro**, de propósito: o `numero_publico` é base32 de
 * Crockford (`CLASSE_DO_NUMERO = [0-9A-HJKMNP-TV-Z]` naquela revisão) e as duas
 * cadeias aparecem lado a lado em quem opera. Sem o `I`, o `L`, o `O` e o `U`,
 * que é a razão de Crockford existir.
 */
export const ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** A parte de domínio do `cart_id`. Ver a nota do módulo. */
const DOMINIO_DO_CARRINHO = "cart";

/** O anel do cofre, na forma que o `SecretProvider.getRing` devolve. */
export type AnelDoSegredo = readonly [actual: string, anterior: string | null];

/** As quatro partes da intenção, e não há uma quinta. Ver a nota do módulo. */
export interface PartesDaIntencao {
  readonly tenantId: string;
  readonly contactId: string;
  readonly draftId: string;
  readonly draftVersion: number;
}

/** Uma linha do rascunho, para a canonicalização. Só o que entra no *hash*. */
export interface LinhaDoRascunho {
  readonly sku: string;
  readonly qty: number;
}

/** O rascunho confirmado, como o grafo o mantém no *checkpoint* (§6.3). */
export interface Rascunho {
  readonly linhas: readonly LinhaDoRascunho[];
  readonly entregaModo: "levantamento" | "entrega";
}

/** O segredo não tem a forma que o cofre promete. Nunca repete o valor. */
export class SegredoMalFormadoError extends Error {
  override readonly name = "SegredoMalFormadoError";
  constructor(razao: string) {
    super(
      `${REF_SEGREDO_DE_INTENTS} mal formado: ${razao}. A forma e ` +
        "<kid>:<base64 de 32 octetos>, como a do pepper_contact_hmac " +
        "(KAM-008, KAM-010); a mensagem nunca repete o valor",
    );
  }
}

/** Uma parte da intenção não tem forma utilizável. Falha fechada. */
export class ParteInvalidaError extends Error {
  override readonly name = "ParteInvalidaError";
  constructor(campo: string, razao: string) {
    super(
      `${campo} nao serve para derivar a intent_key: ${razao}. A chave e a ` +
        "unicidade de orders_mirror, e uma parte vazia ou absurda punha duas " +
        "intencoes diferentes na mesma chave (KAM-046, criterio 2)",
    );
  }
}

const KID = /^[a-z0-9][a-z0-9_.-]{0,62}$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O tecto do `draft_id`. O `sha256` hexadecimal do §3.34 tem 64 caracteres. */
const DRAFT_ID_MAXIMO = 128;

/** O tecto do `sku`. O `offer_terms_sku_ck` da `0028` só exige não-vazio. */
const SKU_MAXIMO = 128;

/**
 * O par `(kid, chave)` de um valor versionado do cofre.
 *
 * A mesma forma do `lerVersionada` de `packages/core-ts/src/identity/chaves.ts`,
 * e **não** se importa de lá: aquela função é privada daquele módulo e
 * exportá-la fazia do `identity` uma dependência do COM por uma dúzia de linhas.
 * O que se partilha é a **forma do valor**, que é a que o inventário declara
 * (`kid: true`), e isso está escrito nos dois sítios.
 */
export interface SegredoVersionado {
  readonly kid: string;
  readonly chave: Buffer;
}

/** Separa `<kid>:<base64>` e verifica os 32 octetos. */
export function lerSegredo(valor: string): SegredoVersionado {
  const corte = valor.indexOf(":");
  if (corte <= 0) {
    throw new SegredoMalFormadoError("falta a versao (esperava <kid>:<base64>)");
  }
  const kid = valor.slice(0, corte);
  if (!KID.test(kid)) throw new SegredoMalFormadoError("o kid nao tem forma");
  const bruto = valor.slice(corte + 1);
  if (bruto.length === 0 || !BASE64.test(bruto)) {
    throw new SegredoMalFormadoError("o valor nao e base64");
  }
  const chave = Buffer.from(bruto, "base64");
  if (chave.length !== OCTETOS_DO_SEGREDO) {
    throw new SegredoMalFormadoError(
      `tem ${chave.length} octetos e a forma declarada sao ${OCTETOS_DO_SEGREDO}`,
    );
  }
  return { kid, chave };
}

/**
 * As partes concatenadas com o comprimento a prefixar. Ver a nota do módulo.
 *
 * O comprimento é o dos **octetos** e não o dos caracteres: um `sku` com um
 * acento tem mais octetos do que caracteres em UTF-8, e prefixar o número de
 * caracteres tornava a codificação ambígua outra vez — que é precisamente o que
 * ela existe para fechar.
 */
export function concatenar(partes: readonly string[]): Buffer {
  const pedacos: Buffer[] = [];
  for (const parte of partes) {
    const octetos = Buffer.from(parte, "utf8");
    pedacos.push(Buffer.from(`${octetos.length}:`, "ascii"), octetos);
  }
  return Buffer.concat(pedacos);
}

/** O digest em base32 de Crockford, cortado em `CARACTERES_DA_CHAVE`. */
export function emBase32(digest: Buffer, caracteres: number): string {
  let acumulado = 0;
  let bits = 0;
  let saida = "";
  for (const octeto of digest) {
    acumulado = (acumulado << 8) | octeto;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      saida += ALFABETO[(acumulado >>> bits) & 31];
      if (saida.length === caracteres) return saida;
    }
  }
  // Os 256 bits do HMAC dão 51 caracteres inteiros, pelo que este caminho só se
  // alcança com um digest mais curto do que o pedido — e então o corte seria uma
  // chave com menos entropia do que o critério fixa, em silêncio.
  throw new ParteInvalidaError(
    "digest",
    `tem ${digest.length} octetos e nao dao ${caracteres} caracteres de base32`,
  );
}

/** Valida as quatro partes. Lança, pela razão do `exigirCtx` da porta. */
function exigirPartes(p: PartesDaIntencao): readonly string[] {
  const tenantId = String(p?.tenantId ?? "").toLowerCase();
  if (!UUID_CANONICO.test(tenantId)) {
    throw new ParteInvalidaError("tenant_id", "nao e um UUID canonico");
  }
  const contactId = String(p?.contactId ?? "").toLowerCase();
  if (!UUID_CANONICO.test(contactId)) {
    throw new ParteInvalidaError("contact_id", "nao e um UUID canonico");
  }
  const draftId = String(p?.draftId ?? "");
  if (draftId.length === 0 || draftId.length > DRAFT_ID_MAXIMO) {
    throw new ParteInvalidaError(
      "draft_id",
      `tem ${draftId.length} caracteres e o tecto e ${DRAFT_ID_MAXIMO}`,
    );
  }
  if (!Number.isInteger(p?.draftVersion) || p.draftVersion < 1) {
    throw new ParteInvalidaError(
      "draft_version",
      "tem de ser um inteiro >= 1 (o primeiro rascunho e a versao 1)",
    );
  }
  // A ordem é a do critério 2, à letra, e não se reordena: a chave é a fórmula.
  return [tenantId, contactId, draftId, String(p.draftVersion)];
}

/**
 * A `intent_key` do critério 2, derivada com **uma** versão do segredo.
 *
 * O `valorDoSegredo` é um elemento do anel (`[actual, anterior]`) e não o anel:
 * quem precisa das duas chama o `chavesDoAnel`, que é onde a regra do anel vive.
 */
export function intentKey(
  valorDoSegredo: string,
  partes: PartesDaIntencao,
): string {
  const { chave } = lerSegredo(valorDoSegredo);
  const digest = createHmac("sha256", chave)
    .update(concatenar(exigirPartes(partes)))
    .digest();
  return emBase32(digest, CARACTERES_DA_CHAVE);
}

/**
 * As chaves de todas as versões vivas do anel, da mais recente para a mais
 * antiga.
 *
 * Uma só quando o segredo nunca rodou (`anterior === null`), e **nunca** um
 * erro por isso: é a letra do `SecretRing` do `secrets/port.ts`. Quem escreve
 * usa a primeira; quem lê procura por todas.
 */
export function chavesDoAnel(
  anel: AnelDoSegredo,
  partes: PartesDaIntencao,
): readonly string[] {
  const [actual, anterior] = anel;
  const chaves = [intentKey(actual, partes)];
  if (anterior !== null && anterior !== actual) {
    const antiga = intentKey(anterior, partes);
    if (antiga !== chaves[0]) chaves.push(antiga);
  }
  return chaves;
}

/**
 * O `cart_id`: a mesma derivação com a parte de domínio à cabeça.
 *
 * Opaco para quem o recebe (§3.28: «não se interpreta, não se valida pela forma,
 * e **não** se deriva de nada»), e **reproduzível** para quem o produziu — que é
 * o que torna o `cartIdValido` possível sem coluna nenhuma. Ver a nota do módulo
 * para a razão de não ser a `intent_key`.
 */
export function cartId(valorDoSegredo: string, partes: PartesDaIntencao): string {
  const { chave } = lerSegredo(valorDoSegredo);
  const digest = createHmac("sha256", chave)
    .update(concatenar([DOMINIO_DO_CARRINHO, ...exigirPartes(partes)]))
    .digest();
  return emBase32(digest, CARACTERES_DA_CHAVE);
}

/**
 * `true` se `candidato` é o `cart_id` destas partes, em alguma versão do anel.
 *
 * A comparação é por `timingSafeEqual` e não por `===`, e não é zelo: o
 * candidato vem de fora (o `confirm:{cart_id}` que o cliente devolve), e uma
 * comparação que sai no primeiro caractere diferente mede quantos caracteres
 * acertou. É a mesma disciplina do `X-Hub-Signature-256` do GWY.
 */
export function cartIdValido(
  anel: AnelDoSegredo,
  partes: PartesDaIntencao,
  candidato: string,
): boolean {
  const [actual, anterior] = anel;
  const esperados = [cartId(actual, partes)];
  if (anterior !== null && anterior !== actual) {
    esperados.push(cartId(anterior, partes));
  }
  const dado = Buffer.from(String(candidato), "utf8");
  let bate = false;
  for (const esperado of esperados) {
    const alvo = Buffer.from(esperado, "utf8");
    // O `timingSafeEqual` lança com tamanhos diferentes, pelo que o tamanho
    // compara-se antes — e isso é público: o `cart_id` tem sempre 26.
    if (alvo.length === dado.length && timingSafeEqual(alvo, dado)) bate = true;
  }
  return bate;
}

/**
 * As linhas canonicalizadas: **ordenadas**, para que a ordem não conte.
 *
 * É a metade do critério 2 que um teste distraído não cobre. O rascunho vive no
 * *checkpoint* do grafo e a ordem das linhas lá é a ordem em que o cliente as
 * disse — «dois quilos de arroz e um sabão» e «um sabão e dois quilos de arroz»
 * são o **mesmo** carrinho, e com a ordem a contar davam `draft_hash`
 * diferentes: o segundo toque parecia conteúdo novo e levava
 * `INTENT_REUSED_WITH_DIFFERENT_CONTENT` numa repetição legítima.
 *
 * A ordem é por `sku` e, com `sku` igual, por `qty`. **Linhas repetidas do mesmo
 * `sku` não se somam**, e isso é uma escolha dita: somá-las fazia «1 + 1» igual
 * a «2», e são dois carrinhos diferentes do ponto de vista de quem os escreveu
 * (o `lines_snapshot` guarda as linhas, não um agregado). O que a ordenação
 * compra é a comutatividade; o que ela não faz é normalizar o conteúdo.
 */
export function linhasCanonicas(
  linhas: readonly LinhaDoRascunho[],
): readonly LinhaDoRascunho[] {
  if (linhas.length === 0) {
    throw new ParteInvalidaError("linhas", "um rascunho sem linhas nao e um carrinho");
  }
  for (const linha of linhas) {
    const sku = String(linha?.sku ?? "");
    if (sku.trim().length === 0 || sku.length > SKU_MAXIMO) {
      throw new ParteInvalidaError(
        "sku",
        `${JSON.stringify(sku)} e vazio ou passa o tecto de ${SKU_MAXIMO}`,
      );
    }
    if (!Number.isInteger(linha?.qty) || linha.qty <= 0) {
      throw new ParteInvalidaError(
        "qty",
        `${String(linha?.qty)} nao e um inteiro positivo (linha ${sku})`,
      );
    }
  }
  return [...linhas].sort((a, b) =>
    a.sku === b.sku ? a.qty - b.qty : a.sku < b.sku ? -1 : 1,
  );
}

/**
 * O `draft_hash` do critério 2: `SHA-256(linhas canonicalizadas ⟂ entrega_modo)`.
 *
 * **Sem segredo**, e é o que o critério escreve: é um `SHA-256` e não um HMAC. A
 * razão é a pergunta que ele responde — «é o mesmo rascunho?» — e essa não
 * precisa de ser inforjável: quem a faz já provou o tenant pelo `ctx`, e a
 * coluna onde ela vive (`order_intents.draft_hash`) é a mesma forma do
 * `payload_hash` da `audit_log`, `bytea` de 32 octetos pelo `CHECK` da revisão
 * `0030`.
 *
 * Devolve `Buffer` e não hexadecimal: a coluna é `bytea` e converter para texto
 * para o *driver* reconverter era uma viagem a mais por onde a forma se perde.
 */
export function draftHash(rascunho: Rascunho): Buffer {
  const canonicas = linhasCanonicas(rascunho.linhas);
  if (
    rascunho.entregaModo !== "levantamento" &&
    rascunho.entregaModo !== "entrega"
  ) {
    throw new ParteInvalidaError(
      "entrega_modo",
      `${JSON.stringify(String(rascunho.entregaModo))} nao e um dos dois modos ` +
        "do CHECK orders_mirror_entrega_modo_ck",
    );
  }
  const partes: string[] = [];
  for (const linha of canonicas) {
    partes.push(linha.sku, String(linha.qty));
  }
  partes.push(rascunho.entregaModo);
  return createHash("sha256").update(concatenar(partes)).digest();
}

/** `true` se dois `draft_hash` são o mesmo. Por `timingSafeEqual`, como acima. */
export function mesmoDraftHash(a: Buffer, b: Buffer): boolean {
  return a.length === b.length && timingSafeEqual(a, b);
}

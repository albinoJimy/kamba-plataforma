/**
 * O `slot_id` opaco do critério 2 (KAM-047).
 *
 * O critério pede «cada uma com `slot_id` opaco e instante UTC», e o critério 4
 * pede que `confirmBooking` seja «idempotente por `(contact_id, slot_id)`». Os
 * dois juntos decidem a forma, e vale a pena escrever porque — é a parte deste
 * ticket que mais fácil era resolver mal.
 *
 * ## Porque é que não é um identificador guardado
 *
 * A saída óbvia era gerar um `uuid` por opção e guardá-lo numa tabela de
 * ofertas. **Não serve, e não é por economia de DDL:** dois `getAvailability`
 * sobre o mesmo serviço dariam dois identificadores para o mesmo slot, e a
 * chave `(contact_id, slot_id)` do critério 4 deixava de ser idempotente por
 * construção — o cliente que pedisse as horas duas vezes antes de confirmar
 * marcava duas vezes. A idempotência daquele critério **exige** que o
 * identificador seja uma função do slot, e não da chamada que o ofereceu.
 *
 * ## Porque é que também não é uma derivação transparente
 *
 * `base64(service|resource|inicio|fim)` era determinístico e satisfazia o
 * critério 4, e ainda assim está errado: o modelo passava a poder **construir**
 * um `slot_id`. O guardrail de `docs/tecnica/02` §8.2 é «só tool; o modelo não
 * calcula horas livres», e um identificador que se fabrica a partir de uma hora
 * inventada é exactamente a forma de o contornar — o backend recebia um slot
 * que nunca ofereceu e, se ele calhasse estar livre, marcava-o.
 *
 * ## O que é: um token auto-descritivo e **assinado**
 *
 *     slot_id = base64url(corpo) + "." + base64url(HMAC-SHA256(segredo, corpo))[:22]
 *     corpo   = "1|<service_id>|<resource_id>|<inicio_at ISO>|<fim_at ISO>"
 *
 * Três propriedades, e cada uma paga uma linha do ticket:
 *
 * - **Determinístico.** O mesmo slot dá sempre o mesmo `slot_id` — critério 4,
 *   e o índice único parcial `bookings_contacto_slot_uq` da revisão `0025`.
 * - **Infalsificável.** Sem o segredo não se produz a assinatura; um `slot_id`
 *   que não verifique devolve `VALIDATION_ERROR` e **não chega à base**. É o
 *   guardrail de §8.2 imposto por criptografia e não por confiança.
 * - **Auto-descritivo.** O `holdSlot` lê o serviço, o recurso e o intervalo do
 *   próprio token, pelo que a assinatura da operação é `holdSlot(ctx, slotId)`
 *   — a do bloco — sem recalcular a disponibilidade para resolver o token.
 *
 * O token **não leva o `tenant_id`**, e isso é deliberado: ele entra no segredo
 * derivado por tenant (ver `segredoDoTenant`), pelo que um `slot_id` do tenant A
 * **não verifica** no tenant B. Pô-lo no corpo era publicá-lo num identificador
 * que o cliente vê.
 *
 * ## O segredo, e o que acontece quando ele roda
 *
 * Vem do cofre (KAM-010), pela mesma receita do `segredo_intents` de KAM-046. A
 * versão vive no primeiro campo do corpo (`1`) para que um anel seja possível
 * **mais tarde**, e é importante dizer que **hoje não há anel**: `lerSlotId`
 * aceita um segredo e uma versão.
 *
 * A consequência, por extenso, porque é operacional e não teórica: no instante
 * em que o segredo rodar, todos os `slot_id` já enviados em listas interactivas
 * deixam de verificar, e cada cliente que carregue no botão recebe
 * `VALIDATION_ERROR` — a mesma resposta que um *token* forjado. Com um TTL de
 * hold de dez minutos e listas que envelhecem em minutos, a janela é curta, mas
 * não é zero. Uma primeira versão deste ficheiro afirmava que «uma rotação não
 * invalida tokens em voo se as duas versões forem aceites», o que descrevia um
 * desenho que o ficheiro não tem — a revisão adversarial apanhou-o.
 *
 * O anel entra quando houver rotação deste segredo, que é do KAM-010: a forma é
 * a do App Secret da Meta no GWY (KAM-013), onde a verificação percorre
 * `[actual, anterior]`.
 *
 * **O que está aqui é a construção, não o aprovisionamento.** Quem monta o
 * módulo passa o segredo; este ficheiro não lê ambiente nem cofre, para que uma
 * bateria possa correr com um segredo de ensaio sem montar o cofre inteiro.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** A versão da construção do token. Vai no corpo, para a rotação ser possível. */
export const VERSAO_DO_SLOT = "1";

/** Quantos caracteres de base64url da assinatura entram no token. */
const CARACTERES_DA_ASSINATURA = 22;

/** O separador entre corpo e assinatura. Não aparece em base64url. */
const SEPARADOR = ".";

/**
 * O tecto de comprimento de um `slot_id`. **Medido: 190 caracteres hoje.**
 *
 * O critério 2 existe **porque** as opções vão numa lista interactiva da Meta,
 * e o `id` de cada linha tem limite. Qual é esse limite é **NÃO VERIFICADO**: o
 * `evidencia/E1` §7 confirma as dez linhas e não diz nada sobre o `id`, e o
 * dicionário §3.4 regista a mesma lacuna para o `cart_id` («que ele caiba nos
 * 256 caracteres do `id` de um *reply button* é NÃO VERIFICADO»).
 *
 * Fixa-se 256 como tecto, que é o número que o dicionário já cita, e o
 * `derivarSlotId` **lança** se o ultrapassar. Não é uma afirmação sobre a Meta:
 * é uma guarda para que um campo novo no corpo, ou uma versão de dois dígitos,
 * não passe despercebido até a Meta recusar o envio. A margem actual são 66
 * caracteres.
 */
export const MAXIMO_DO_SLOT_ID = 256;

/** Um `slot_id` construído por nós que não cabe no `id` de uma linha de lista. */
export class SlotDemasiadoLongoError extends Error {
  override readonly name = "SlotDemasiadoLongoError";
  constructor(comprimento: number) {
    super(
      `o slot_id tem ${comprimento} caracteres e o tecto e ${MAXIMO_DO_SLOT_ID}: ` +
        "nao cabe no id de uma linha de lista interactiva da Meta (limite exacto " +
        "NAO VERIFICADO; ver evidencia/E1 secao 7 e o dicionario 3.4)",
    );
  }
}

/*
 * **Não há `SlotInvalidoError`**, e a ausência é a afirmação: o `lerSlotId`
 * devolve `null` e quem chama transforma isso em `VALIDATION_ERROR`, que é uma
 * resposta e não uma excepção. Uma primeira versão exportava a classe e nunca a
 * lançava — código morto que fazia parecer que havia dois caminhos.
 */

/** O segredo tem de existir e ter corpo: um HMAC de chave vazia é um HMAC válido. */
export class SegredoEmFaltaError extends Error {
  override readonly name = "SegredoEmFaltaError";
  constructor() {
    super(
      "o segredo dos slots tem de ter pelo menos 32 octetos: um HMAC com " +
        "chave vazia e um HMAC valido, e aceita-lo era aceitar qualquer " +
        "slot_id de quem souber que o cofre esta vazio (KAM-010)",
    );
  }
}

const MINIMO_DO_SEGREDO = 32;

export interface Slot {
  readonly serviceId: string;
  readonly resourceId: string;
  /** Instante UTC em ISO-8601, com `Z`. */
  readonly inicioAt: string;
  readonly fimAt: string;
}

function base64url(octetos: Buffer): string {
  return octetos.toString("base64url");
}

/**
 * O segredo deste tenant, derivado do segredo da plataforma.
 *
 * `HMAC(segredo, "slot:" || tenant_id)`. É o que faz com que um `slot_id` do
 * tenant A não verifique no tenant B **sem** o `tenant_id` aparecer no token: o
 * mesmo corpo assinado com chaves diferentes dá assinaturas diferentes.
 */
function segredoDoTenant(segredo: Buffer, tenantId: string): Buffer {
  return createHmac("sha256", segredo).update(`slot:${tenantId}`).digest();
}

function corpoDe(slot: Slot): string {
  return [
    VERSAO_DO_SLOT,
    slot.serviceId,
    slot.resourceId,
    slot.inicioAt,
    slot.fimAt,
  ].join("|");
}

function exigirSegredo(segredo: Buffer): Buffer {
  if (!Buffer.isBuffer(segredo) || segredo.length < MINIMO_DO_SEGREDO) {
    throw new SegredoEmFaltaError();
  }
  return segredo;
}

function assinar(chave: Buffer, corpo: string): string {
  return base64url(createHmac("sha256", chave).update(corpo).digest()).slice(
    0,
    CARACTERES_DA_ASSINATURA,
  );
}

/** O `slot_id` opaco de um slot, para este tenant. Determinístico. */
export function derivarSlotId(
  segredo: Buffer,
  tenantId: string,
  slot: Slot,
): string {
  const chave = segredoDoTenant(exigirSegredo(segredo), tenantId);
  const corpo = corpoDe(slot);
  const slotId = `${base64url(Buffer.from(corpo, "utf8"))}${SEPARADOR}${assinar(chave, corpo)}`;
  if (slotId.length > MAXIMO_DO_SLOT_ID) {
    throw new SlotDemasiadoLongoError(slotId.length);
  }
  return slotId;
}

/**
 * O slot dentro de um `slot_id`, ou `null` se não verificar.
 *
 * Devolve `null` em vez de lançar, porque quem chama transforma isto num
 * `VALIDATION_ERROR` — que é uma resposta e não uma excepção. **Nunca lança por
 * forma**: um token truncado, com separadores a mais, com base64 inválido ou
 * vazio recusa-se sem rebentar. O `timingSafeEqual` rebenta com comprimentos
 * diferentes, e o comprimento é escolhido por quem chama — por isso compara-se
 * depois de normalizar o tamanho, e não antes.
 */
export function lerSlotId(
  segredo: Buffer,
  tenantId: string,
  slotId: unknown,
): Slot | null {
  // **O segredo verifica-se primeiro, antes da forma do token.** Estava no
  // fim, depois das recusas por forma, e isso fazia com que um cofre vazio
  // devolvesse `null` para tudo — indistinguível de «o cliente mandou um
  // `slot_id` inválido». O sintoma era «ninguém consegue marcar» e a causa
  // aparecia como ruído de entrada; agora um segredo em falta é alto e
  // imediato, que é o que uma falha de configuração tem de ser.
  const chave = segredoDoTenant(exigirSegredo(segredo), tenantId);
  if (
    typeof slotId !== "string" ||
    slotId.length === 0 ||
    slotId.length > MAXIMO_DO_SLOT_ID
  ) {
    return null;
  }
  const partes = slotId.split(SEPARADOR);
  if (partes.length !== 2) return null;
  const [corpoCodificado, assinatura] = partes;
  if (
    corpoCodificado === undefined ||
    assinatura === undefined ||
    assinatura.length !== CARACTERES_DA_ASSINATURA
  ) {
    return null;
  }

  let corpo: string;
  try {
    corpo = Buffer.from(corpoCodificado, "base64url").toString("utf8");
  } catch {
    return null;
  }
  // O `base64url` do Node não recusa caracteres fora do alfabeto: ignora-os. Um
  // token adulterado podia decodificar para o mesmo corpo com uma codificação
  // diferente, e a assinatura verificava. A ida e volta fecha isso.
  if (base64url(Buffer.from(corpo, "utf8")) !== corpoCodificado) return null;

  const esperada = assinar(chave, corpo);
  const dada = Buffer.from(assinatura, "utf8");
  const alvo = Buffer.from(esperada, "utf8");
  if (dada.length !== alvo.length || !timingSafeEqual(dada, alvo)) return null;

  const campos = corpo.split("|");
  if (campos.length !== 5 || campos[0] !== VERSAO_DO_SLOT) return null;
  const [, serviceId, resourceId, inicioAt, fimAt] = campos;
  if (
    serviceId === undefined ||
    resourceId === undefined ||
    inicioAt === undefined ||
    fimAt === undefined
  ) {
    return null;
  }
  // A assinatura garante que o corpo é nosso, e ainda assim o intervalo
  // verifica-se: um slot com `fim <= inicio` só podia vir de um defeito nosso, e
  // a restrição `bookings_intervalo_ck` recusava-o na base com um erro de
  // integridade em vez de um `VALIDATION_ERROR` legível.
  if (!(Date.parse(inicioAt) < Date.parse(fimAt))) return null;
  return { serviceId, resourceId, inicioAt, fimAt };
}

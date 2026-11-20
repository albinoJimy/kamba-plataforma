/**
 * O contacto de uma encomenda ao dono, mascarado (KAM-206; critério 6 do KAM-099).
 *
 * As três peças puras da leitura: **quando** o dono pode ver o contacto, **que**
 * telefone se mostra, e **como** sai. Nenhuma toca na base; a leitura, a decifra e
 * a linha de `audit_log` vivem com quem as liga.
 *
 * ## A regra: o dono é o responsável e o dado é necessário (*proposta*)
 *
 * Os estados em que o dono **age** sobre a encomenda, e em que falar com o
 * cliente é parte de agir:
 *
 * ```text
 * pendente_confirmacao   o dono confirma ou recusa o pedido
 * paga                   o dono prepara e combina a entrega
 * em_entrega             o dono entrega
 * entrega_falhada        o dono volta a combinar
 * ```
 *
 * Fora deles — antes do pagamento, depois da entrega, numa disputa, num
 * reembolso, numa cancelada ou expirada — o contacto **não** é necessário ao
 * dono, e a resposta é o mesmo `NOT_FOUND` de uma encomenda que não existe. Uma
 * disputa e um reembolso correm pela plataforma, e não pelo telefone do cliente.
 *
 * ## O telefone: o da encomenda, e por expirar
 *
 * A `contact_endpoints` guarda o telefone por **finalidade**, com `expira_at`
 * (KAM-008, retenção do doc 06). Servem `contacto_pedido` e `entrega`, que são as
 * finalidades de uma encomenda; o de `pagamento_express` foi dado para pagar, e
 * mostrá-lo ao dono era usá-lo para outra coisa. Um telefone expirado já não
 * devia existir — a purga é do KAM-071 —, e não se mostra.
 *
 * ## A máscara: os últimos três dígitos (*proposta*)
 *
 * Sai `••• ••• 789`, e **nada** do resto: nem o indicativo, nem o comprimento. O
 * dono reconhece o cliente que já lhe falou; quem lê o ecrã por cima do ombro, um
 * *log* ou uma captura não fica com um número que se marque.
 */

import { eUuid, erro, exigirCtx, ok, type Ctx, type ResultadoFinal } from "../port/index.ts";

/** Os estados em que o dono vê o contacto. *Proposta* (KAM-206). */
export const ESTADOS_COM_CONTACTO = [
  "pendente_confirmacao",
  "paga",
  "em_entrega",
  "entrega_falhada",
] as const;

/** As finalidades de telefone que servem uma encomenda. */
export const FINALIDADES_DA_ENCOMENDA = ["contacto_pedido", "entrega"] as const;

/** Quantos dígitos do fim a máscara mostra. *Proposta* (KAM-206). */
export const DIGITOS_A_MOSTRAR = 3;

/** O dono pode ver o contacto de uma encomenda neste estado? */
export function contactoNecessario(estado: string): boolean {
  return (ESTADOS_COM_CONTACTO as readonly string[]).includes(estado);
}

/**
 * O telefone mascarado: os últimos três dígitos, e o resto como três pontos em
 * dois grupos fixos, para não dizer o comprimento. `null` se o telefone não tem
 * dígitos que cheguem — mostrar menos do que três era mostrar um número inteiro
 * de três dígitos, e não há telefone assim.
 */
export function mascarar(telefone: string): string | null {
  const digitos = telefone.replace(/\D/g, "");
  if (digitos.length <= DIGITOS_A_MOSTRAR) return null;
  return `••• ••• ${digitos.slice(-DIGITOS_A_MOSTRAR)}`;
}

/** Um telefone decifrado, como a identidade o devolve. */
export interface TelefoneDoContacto {
  readonly finalidade: string;
  readonly telefone: string;
  readonly expiraAt: Date;
}

/**
 * O telefone a mostrar: o de `contacto_pedido` primeiro, depois o de `entrega`,
 * e só os que ainda não expiraram. Dentro da mesma finalidade, o que expira mais
 * tarde (o mais recente). `null` se nenhum serve.
 */
export function telefoneDaEncomenda(
  telefones: readonly TelefoneDoContacto[],
  agora: Date,
): string | null {
  for (const finalidade of FINALIDADES_DA_ENCOMENDA) {
    const vivos = telefones
      .filter((t) => t.finalidade === finalidade && t.expiraAt.getTime() > agora.getTime())
      .sort((a, b) => b.expiraAt.getTime() - a.expiraAt.getTime());
    const escolhido = vivos[0];
    if (escolhido !== undefined) return escolhido.telefone;
  }
  return null;
}

// ------------------------------------------------------------ a operação

/**
 * A linha de auditoria de uma leitura do contacto: `order.contact_view`, com o
 * `order_id` em `entity_id` e o `payload_hash` do texto canónico
 * `order.contact_view\x1f<order_id>\x1f<estado>`. **Nem o telefone nem a
 * máscara** entram na linha, nem resumidos: o `audit_log` prova que o dono viu o
 * contacto desta encomenda neste estado e a esta hora, e não guarda o que viu.
 *
 * Corre como `kamba_identity`, na transacção da decifra (decisão do fundador de
 * 2026-11-20, opção A): o papel tem `EXECUTE` no `audit_append` e `INSERT` nas
 * colunas que ele escreve, desde a revisão `0082`, e mais nada no `audit_log`.
 */
export const ACCAO_DO_CONTACTO = "order.contact_view";
export const ENTIDADE_DO_CONTACTO = "order";
//
// **Os literais vão por extenso e não interpolados**: o gate 3b e a suite de
// base de dados (`db/tests/test_contacto_da_encomenda.py`) lêem o texto da
// constante, e um `${...}` lá dentro era um texto que nenhum dos dois executa.
export const SQL_AUDITAR_CONTACTO = `
  SELECT platform.audit_append(
    $1::uuid, 'owner', $2, 'order.contact_view', 'order', $3, NULL, sha256($4::bytea)
  )
`;

/** O texto canónico do `payload_hash`. Exportado para o ensaio o reconstruir. */
export function textoDaAuditoria(orderId: string, estado: string): string {
  return [ACCAO_DO_CONTACTO, orderId, estado].join("\x1f");
}

/** A ligação da leitura do contacto: só o `query`, como a do `pg`. */
export interface ClienteDoContacto {
  query(sql: string, parametros?: readonly unknown[]): Promise<unknown>;
}

/**
 * Quem lê os telefones do contacto: a identidade do KAM-008, como
 * `kamba_identity`. O `antes` corre na transacção dela, antes da decifra.
 * Devolve `null` quando o contacto foi apagado ou a chave de dados destruída —
 * não há telefone a mostrar, e a transacção desfez-se com a linha de auditoria.
 */
export interface LeitorDeContactos {
  telefones(
    tenantId: string,
    contactId: string,
    antes: (cliente: ClienteDoContacto) => Promise<void>,
  ): Promise<readonly TelefoneDoContacto[] | null>;
}

/** A encomenda como a leitura em `kamba_app` a devolve: o que a regra precisa. */
export interface EncomendaDoContacto {
  readonly orderId: string;
  readonly estado: string;
  readonly contactId: string;
}

/** O que sai do COM: **nunca** o telefone em claro. */
export interface ContactoDaEncomenda {
  readonly orderId: string;
  /** `••• ••• 789`, ou `null` se não há telefone a mostrar. */
  readonly telefoneMascarado: string | null;
}

/** O que a operação precisa que lhe dêem. */
export interface MontagemDoContacto {
  /** A leitura da encomenda, como `kamba_app` (o `getOrder` da porta). */
  lerEncomenda(ctx: Ctx, orderId: string): Promise<ResultadoFinal<EncomendaDoContacto>>;
  /** `null` sem a ligação do `kamba_identity`: a rota responde `UPSTREAM_DOWN`. */
  readonly contactos: LeitorDeContactos | null;
  readonly agora: () => Date;
}

/**
 * O contacto de **uma** encomenda do tenant do `ctx`, mascarado, ao dono.
 *
 * ```text
 * 1. o actor é o dono                         senão NOT_FOUND
 * 2. kamba_app: a encomenda do tenant do ctx  senão NOT_FOUND (a de outro tenant
 *                                             e a que não existe, iguais)
 * 3. o estado está na regra                   senão NOT_FOUND, o mesmo
 * 4. kamba_identity, numa transacção:         a linha de audit_log, e só depois
 *    audit_append, depois a decifra            a decifra; uma falha desfaz as duas
 * 5. a máscara                                o telefone em claro não sai daqui
 * ```
 *
 * **Fora da regra é o mesmo 404** que uma encomenda que não existe: um código
 * diferente dizia ao dono, ou a quem tivesse a sessão dele, em que estado está
 * uma encomenda que ele não pode ver de outra forma — e dizia a quem tenta que
 * acertou num identificador.
 */
export async function contactoDaEncomenda(
  m: MontagemDoContacto,
  ctx: Ctx,
  orderId: string,
): Promise<ResultadoFinal<ContactoDaEncomenda>> {
  const validado = exigirCtx(ctx);
  if (validado.actor.kind !== "dono") return erro("NOT_FOUND");
  if (!eUuid(orderId)) return erro("NOT_FOUND");
  const lida = await m.lerEncomenda(validado, orderId.toLowerCase());
  if (lida.tipo === "erro") {
    return lida.erro === "VALIDATION_ERROR" || lida.erro === "TENANT_MISMATCH" ? erro("NOT_FOUND") : lida;
  }
  const encomenda = lida.valor;
  if (!contactoNecessario(encomenda.estado)) return erro("NOT_FOUND");
  if (m.contactos === null) return erro("UPSTREAM_DOWN");

  const telefones = await m.contactos.telefones(validado.tenantId, encomenda.contactId, async (cliente) => {
    await cliente.query(SQL_AUDITAR_CONTACTO, [
      validado.tenantId,
      validado.actor.id,
      encomenda.orderId,
      textoDaAuditoria(encomenda.orderId, encomenda.estado),
    ]);
  });
  const telefone = telefones === null ? null : telefoneDaEncomenda(telefones, m.agora());
  return ok({ orderId: encomenda.orderId, telefoneMascarado: telefone === null ? null : mascarar(telefone) });
}

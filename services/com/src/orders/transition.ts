/**
 * A primitiva `transition` do §6.2 (critérios 2 e 3).
 *
 * ```text
 * 1. valida o pedido (destino, versão, causa, e o que o destino exige)
 * 2. lê a encomenda                                  SQL_LER
 * 3. confronta o destino com o grafo da base          SQL_GRAFO
 * 4. CAS por (id, version, estado)                    SQL_TRANSITAR
 * 5. grava o registo da transição                     SQL_REGISTAR_ESTADO
 * 6. emite o evento, se o destino tiver um            SQL_EMITIR
 * ```
 *
 * Os passos 4, 5 e 6 correm na transacção de quem chama — este módulo **não
 * abre transacção nenhuma**, e é essa a razão de receber o `repo` e o `emitir`
 * em vez de um cliente que ele próprio gerisse. O que faz dos três um só acto
 * não é esta ordem: é o `CONSTRAINT TRIGGER` diferido `order_estado_exige_log`
 * da revisão `0030`, que no `COMMIT` exige a linha do passo 5 para a mudança do
 * passo 4. **Quem mudar o estado e não gravar o registo não confirma**, e isso
 * vale para este módulo como para qualquer outro caminho.
 *
 * ## O conflito de CAS **devolve o estado relido**, e não um erro
 *
 * O §6.2 acaba com «falha de CAS ⇒ reler e reavaliar (nunca forçar)», e o
 * critério 2 pede que vinte transições concorrentes dêem «1 vencedora e 19
 * conflitos que releem e reavaliam». Um `erro("VALIDATION_ERROR")` dizia ao
 * chamador que o pedido dele era inválido — e não era: era tarde. Por isso o
 * resultado deste módulo é uma união de três e não o `Resultado` de dois da
 * porta:
 *
 * ```text
 * {tipo: "ok",       estado}   a transição passou
 * {tipo: "conflito", estado}   outra ganhou; o `estado` é a releitura
 * {tipo: "erro",     erro}     o pedido não serve, e reler não ajuda
 * ```
 *
 * O `conflito` traz a releitura **de dentro da mesma função** porque é o que
 * permite reavaliar sem segunda viagem, e porque é a diferença entre «reler» e
 * «tentar outra vez»: com o estado novo na mão, quem chama decide se a sua
 * transição ainda faz sentido. Um laço de repetição aqui dentro era «forçar»
 * com outro nome.
 *
 * **E a porta passou a dizê-lo, pelo KAM-178.** Esta nota dizia que «o adaptador
 * que ligar esta função ao método `transition` da porta traduz `conflito` para o
 * erro que escolher, e essa escolha não é deste ticket». A escolha foi feita, e
 * não foi traduzir: o `Resultado<T>` do §3.39 ganhou um terceiro caso **só para
 * o conflito de CAS** (emenda L5 do orquestrador, 2026-11-04), pelo que o
 * `comoResultadoDaPorta` abaixo leva a releitura intacta até quem chama. Os
 * `ERROS` da porta passaram de cinco a **dez** no mesmo movimento, e nenhum
 * deles é o conflito — ver o `../port/contrato.ts`.
 *
 * ## `paga` é verificada **duas vezes**, e as duas são necessárias
 *
 * Aqui, para que a recusa chegue como erro de domínio e não como `KA006` do
 * PostgreSQL; e na base, pelo *trigger* diferido, porque uma verificação em
 * TypeScript só cobre a via que passa pelo TypeScript. O DoD diz «nenhuma via
 * leva a `paga` sem evento ou confirmação manual auditada», e «nenhuma» inclui
 * um `UPDATE` à mão de quem tem o privilégio.
 */

import { checkCeiling } from "@kamba/core-ts/ten";

import {
  conflito,
  erro,
  ok,
  type Erro,
  type Resultado,
} from "../port/contrato.ts";
import {
  ACTOR_DO_PAGAMENTO,
  CAUSAS_QUE_PAGAM,
  CHAVE_DO_TECTO_MANUAL,
  EVENTO_POR_ESTADO,
  VIA_POR_CAUSA,
  type CausaDaTransicao,
  type CausaQuePaga,
  type ClienteSql,
  type Ctx,
  type EstadoDaEncomenda,
  type OrderState,
} from "./contrato.ts";
import { SQL_LER, SQL_TRANSITAR } from "./consultas.ts";
import {
  EMISSOES,
  emitir,
  payloadDeCancelada,
  payloadDeEntregue,
  payloadDeExpirada,
  payloadDePaga,
} from "./eventos.ts";
import { lerGrafo, transicaoPermitida } from "./graph.ts";

/** O repo-base, na parte que este módulo usa. */
export interface RepoDoTenant {
  noTenant(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;
  /** O `INSERT` cujo `tenant_id` é escrito pelo repo-base, não pelo chamador. */
  inserirNoTenant(insercao: {
    readonly tabela: string;
    readonly valores: Readonly<Record<string, unknown>>;
    readonly sufixo?: string;
  }): Promise<readonly Readonly<Record<string, unknown>>[]>;
  readonly tenantId: string;
}

/**
 * A tabela do registo de transições. **Qualificada pelo esquema**, e tem de ser.
 *
 * O `inserirNoTenant` do repo-base **constrói** o `INSERT` com este nome, e nada
 * neste repositório põe o `search_path`: o `comTenant` só põe o `app.tenant_id`
 * e o `db/bootstrap.py` registra que um `ALTER ROLE … SET search_path` é apagado
 * pelo `RESET ALL`. Sem o `platform.`, este `INSERT` morre em `42P01` no dia em
 * que alguém o chamar — e esse dia é o **KAM-178**, que liga o método
 * `transition` da porta ao adaptador. O KAM-046 qualificou a sua
 * (`platform.order_intents`) e relatou esta e as duas irmãs.
 */
export const TABELA_DO_REGISTO = "platform.order_state_log";

/**
 * O que as operações deste módulo recebem.
 *
 * A mesma forma do `Registo` que o adaptador monta para o `produtos`: o `repo`
 * **não consegue** emitir uma consulta sem filtro de tenant, e o `emitir` é a
 * porta estreita para as chamadas de função (`evt_emitir`,
 * `order_numero_publico`), que o repo-base recusa por não terem `WHERE`.
 */
export interface Encomendas {
  readonly ctx: Ctx;
  readonly repo: RepoDoTenant;
  readonly emitir: ClienteSql;
  /**
   * As bandeiras ligadas. Vazio no Piloto, onde o `COM_DELIVERY_ENABLED` está
   * desligado (critério 1). **Configuração e não argumento de negócio**: quem
   * monta o módulo é que a sabe, e a base confirma-a por
   * `current_setting('app.com_delivery_enabled')` — as duas têm de concordar, e
   * se não concordarem é a base que ganha.
   */
  readonly bandeiras?: readonly string[];
  /** O relógio. Injectável para que os ensaios não dependam do de agora. */
  readonly agora?: () => Date;
}

/** O pedido de transição: o `transition(ctx, id, to, expectedVersion, causa)`. */
export interface PedidoDeTransicao {
  readonly orderId: string;
  readonly para: OrderState;
  readonly expectedVersion: number;
  readonly causa: CausaDaTransicao;
  /** Obrigatório para `entregue`: o contrato do `order.delivered` exige-o. */
  readonly entregaConfirmadaPor?: string | null;
  /** Fixa ou prolonga o fim da reserva. Obrigatório para `expirada` se faltar. */
  readonly expiraAt?: string | null;
}

/** O resultado das três formas. Ver a nota do módulo. */
export type ResultadoDaTransicao =
  | { readonly tipo: "ok"; readonly estado: EstadoDaEncomenda }
  | { readonly tipo: "conflito"; readonly estado: EstadoDaEncomenda }
  | { readonly tipo: "erro"; readonly erro: Erro };

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function recusar(motivo: Erro): ResultadoDaTransicao {
  return { tipo: "erro", erro: motivo };
}

/** Lê a encomenda. `null` quando não existe (ou é de outro tenant: §5.5). */
export async function lerEncomenda(
  e: Encomendas,
  orderId: string,
): Promise<Readonly<Record<string, unknown>> | null> {
  const linhas = await e.repo.noTenant(SQL_LER, [orderId]);
  return linhas[0] ?? null;
}

function comoEstado(linha: Readonly<Record<string, unknown>>): EstadoDaEncomenda {
  return {
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    estado: String(linha["estado"]) as OrderState,
    version: Number(linha["version"]),
    totalMinor: BigInt(String(linha["total_minor"])),
    currency: String(linha["currency"]),
    expiraAt: linha["expira_at"] === null ? null : String(linha["expira_at"]),
    pagaVia: linha["paga_via"] === null ? null : String(linha["paga_via"]),
    entregaConfirmadaPor:
      linha["entrega_confirmada_por"] === null
        ? null
        : String(linha["entrega_confirmada_por"]),
  };
}

/**
 * O que o critério 3 exige de uma transição para `paga`.
 *
 * Três condições, e a terceira é a que o critério escreve por extenso: «actor
 * `agente` ou `dono` sem evento é recusado». Com evento também — o que leva a
 * encomenda a `paga` é o PAY a dizer que recebeu, e quem o diz em nome do PAY é
 * o `sistema`. A declaração do dono («recebi») leva a
 * `pendente_confirmacao`, e é o `ManualProvider` (KAM-054) que a audita e emite
 * o `payment.manual_confirmed`.
 */
export function pagamentoAutenticado(
  ctx: Ctx,
  causa: CausaDaTransicao,
): boolean {
  if (ctx.actor.kind !== ACTOR_DO_PAGAMENTO) return false;
  if (typeof causa.eventoId !== "string" || causa.eventoId.trim() === "") {
    return false;
  }
  return (CAUSAS_QUE_PAGAM as readonly string[]).includes(causa.causa);
}

/**
 * A transição do §6.2, com concorrência optimista.
 *
 * Ver a nota do módulo para a ordem dos seis passos e para a razão de o
 * conflito devolver a releitura.
 */
export async function transition(
  e: Encomendas,
  pedido: PedidoDeTransicao,
): Promise<ResultadoDaTransicao> {
  if (!UUID_CANONICO.test(pedido.orderId)) return recusar("VALIDATION_ERROR");
  if (!Number.isInteger(pedido.expectedVersion) || pedido.expectedVersion < 1) {
    return recusar("VALIDATION_ERROR");
  }
  if (pedido.causa.causa.trim() === "") return recusar("VALIDATION_ERROR");
  if (pedido.para === "paga" && !pagamentoAutenticado(e.ctx, pedido.causa)) {
    return recusar("VALIDATION_ERROR");
  }
  if (
    pedido.para === "entregue" &&
    (pedido.entregaConfirmadaPor ?? null) === null
  ) {
    // O contrato do `order.delivered` exige `entrega_confirmada_por`, e o
    // `orders_mirror_entregue_exige_quem_ck` exige-o na coluna: recusar aqui
    // dá-lhe um erro de domínio em vez de um `23514`.
    return recusar("VALIDATION_ERROR");
  }

  const antes = await lerEncomenda(e, pedido.orderId);
  if (antes === null) return recusar("NOT_FOUND");
  const de = String(antes["estado"]) as OrderState;

  // A guarda do `pendente_confirmacao` (§6.2): `total_minor <= limite_manual`
  // do tenant. **Pelo `checkCeiling` do `ten` e não por uma consulta nova**: o
  // tecto vive em `entitlements.limites` e lê-se por `platform.ten_tecto`
  // (revisão `0007`), que devolve o **mínimo** entre os módulos activos que
  // declaram a chave e `null` quando nenhum a declara. Escrever aqui um
  // `SELECT limites->>'manual_max_minor'` era uma segunda fonte para um limite
  // que o `ten` já serve, e perdia a regra do mínimo.
  //
  // O `cabe === false` é recusa, incluindo o `motivo: "sem_entitlement"` — «sem
  // tecto» não quer dizer «sem limite» (critério 2 do KAM-009). A barreira real
  // é o `order_transicao_valida` da revisão `0030`, que faz a mesma leitura e
  // levanta `KA007`; isto está aqui para que a recusa chegue como erro de
  // domínio.
  if (pedido.para === "pendente_confirmacao") {
    const total = BigInt(String(antes["total_minor"]));
    if (total > BigInt(Number.MAX_SAFE_INTEGER)) {
      // O `checkCeiling` recebe `number` e exige inteiro seguro; acima disso
      // não se adivinha, recusa-se.
      return recusar("VALIDATION_ERROR");
    }
    const tecto = await checkCeiling(
      e.emitir,
      e.ctx.tenantId,
      CHAVE_DO_TECTO_MANUAL,
      Number(total),
    );
    if (!tecto.cabe) return recusar("VALIDATION_ERROR");
  }

  // **A versão compara-se antes do CAS e o CAS compara-a outra vez.** A
  // primeira leitura dá o erro certo a quem chegou com uma versão antiga sem
  // concorrência nenhuma; o predicado do `UPDATE` é o que resiste às dezanove
  // que chegam ao mesmo tempo. Nenhuma das duas dispensa a outra.
  if (Number(antes["version"]) !== pedido.expectedVersion) {
    return { tipo: "conflito", estado: comoEstado(antes) };
  }

  const grafo = await lerGrafo(e.emitir);
  if (!transicaoPermitida(grafo, de, pedido.para, e.bandeiras ?? [])) {
    return recusar("VALIDATION_ERROR");
  }

  const instante = (e.agora ?? (() => new Date()))().toISOString();
  const expiraAt = pedido.expiraAt ?? null;
  if (pedido.para === "expirada" && antes["expira_at"] === null && expiraAt === null) {
    // O `order.expired` tem `expira_at` em `required`: expirar sem instante era
    // um envelope que o `validarPayload` recusa depois de a linha já estar
    // escrita — e a transacção reverteria tudo, com a transição perdida e o
    // motivo escondido num erro de validação de evento.
    return recusar("VALIDATION_ERROR");
  }

  const linhas = await e.repo.noTenant(SQL_TRANSITAR, [
    pedido.orderId,
    pedido.expectedVersion,
    de,
    pedido.para,
    pedido.para === "paga" ? instante : null,
    pedido.para === "paga"
      ? VIA_POR_CAUSA[pedido.causa.causa as CausaQuePaga]
      : null,
    pedido.para === "entregue" ? instante : null,
    pedido.para === "entregue" ? pedido.entregaConfirmadaPor : null,
    expiraAt,
  ]);
  const depois = linhas[0];
  if (depois === undefined) {
    // Zero linhas com a encomenda a existir e a versão a bater na leitura:
    // sobra outra transacção ter ganho entretanto. Relê e devolve.
    const relido = await lerEncomenda(e, pedido.orderId);
    if (relido === null) return recusar("NOT_FOUND");
    return { tipo: "conflito", estado: comoEstado(relido) };
  }
  const estado = comoEstado(depois);

  // Pelo repo-base, que escreve o `tenant_id`: ver a nota do `consultas.ts`.
  // A `version` é a **de depois** da transição, que é a que o *trigger*
  // diferido procura no `COMMIT`.
  await e.repo.inserirNoTenant({
    tabela: TABELA_DO_REGISTO,
    valores: {
      order_id: pedido.orderId,
      de,
      para: pedido.para,
      version: estado.version,
      causa: pedido.causa.causa,
      evento_id: pedido.causa.eventoId ?? null,
      actor_kind: e.ctx.actor.kind,
      actor_id: e.ctx.actor.id,
    },
  });

  await emitirDoEstado(e, pedido, estado);
  return { tipo: "ok", estado };
}

/**
 * Emite o evento do destino, se o destino tiver um.
 *
 * Três destinos do núcleo **não** emitem — `aguarda_pagamento`,
 * `pendente_confirmacao` e `em_entrega` —, e o `contrato.ts` escreve o credor de
 * cada um dos eventos que lhes faltam. Um `order.reserved` ou um
 * `order.dispatched` emitido daqui era um tipo que não existe no catálogo
 * publicado.
 */
async function emitirDoEstado(
  e: Encomendas,
  pedido: PedidoDeTransicao,
  estado: EstadoDaEncomenda,
): Promise<void> {
  const tipo = EVENTO_POR_ESTADO[pedido.para];
  if (tipo === undefined) return;

  if (pedido.para === "paga") {
    await emitir(e.emitir, e.ctx.tenantId, {
      ...EMISSOES.paga,
      orderId: estado.orderId,
      payload: payloadDePaga(
        estado.orderId,
        estado.totalMinor,
        estado.currency,
        String(estado.pagaVia),
      ),
    });
    return;
  }
  if (pedido.para === "expirada") {
    await emitir(e.emitir, e.ctx.tenantId, {
      ...EMISSOES.expirada,
      orderId: estado.orderId,
      payload: payloadDeExpirada(estado.orderId, String(estado.expiraAt)),
    });
    return;
  }
  if (pedido.para === "cancelada") {
    await emitir(e.emitir, e.ctx.tenantId, {
      ...EMISSOES.cancelada,
      orderId: estado.orderId,
      // A `causa` da coluna é o `motivo` do evento: a tradução está fixada no
      // dicionário §3.5 e não é uma escolha deste módulo.
      payload: payloadDeCancelada(estado.orderId, pedido.causa.causa),
    });
    return;
  }
  await emitir(e.emitir, e.ctx.tenantId, {
    ...EMISSOES.entregue,
    orderId: estado.orderId,
    payload: payloadDeEntregue(
      estado.orderId,
      String(estado.entregaConfirmadaPor),
    ),
  });
}

/**
 * O `Resultado` da porta. **Os três casos atravessam-na um a um.**
 *
 * Era uma tradução com perda — o `conflito` saía como `VALIDATION_ERROR` — e
 * deixou de ser pelo KAM-178: o `Resultado<T>` do §3.39 tem um terceiro caso
 * para o conflito de CAS, e a releitura passa intacta. Dizer
 * `VALIDATION_ERROR` a quem perdeu a corrida afirmava que o pedido dele não
 * serve, quando o que ele tem de fazer é reler (§6.2: «nunca forçar»).
 */
export function comoResultadoDaPorta(
  r: ResultadoDaTransicao,
): Resultado<EstadoDaEncomenda> {
  if (r.tipo === "ok") return ok(r.estado);
  if (r.tipo === "erro") return erro(r.erro);
  return conflito(r.estado);
}

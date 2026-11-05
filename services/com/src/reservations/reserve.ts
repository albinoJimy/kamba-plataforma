/**
 * As quatro primitivas de reserva da porta, e a autoridade de stock (KAM-045).
 *
 * ```text
 * reserveStock        promete stock para as linhas da encomenda       critério 1
 * commitReservation   consome as reservas de uma encomenda paga       critério 6
 * releaseReservation  liberta com motivo, e devolve o stock           critério 6
 * extendReservation   prolonga o prazo, dentro do tecto de 72 h       critério 7
 * ```
 *
 * Mais o `autoridadeDeStock`, que é a dívida que este ticket vem pagar e não um
 * extra: o `createOrder` do KAM-046 já tem o *hook* `stockDisponivel` e já
 * devolve `OUT_OF_STOCK` quando ele recusa — o que faltava era a **fonte**, e o
 * comentário dele nomeia este ticket. Com a `offer_terms.stock_quantidade` da
 * revisão `0033` a fonte existe.
 *
 * ## Este módulo **não abre transacção nenhuma**
 *
 * A mesma escolha do `../orders/transition.ts`, e é por isso que recebe o `repo`
 * em vez de um cliente que ele próprio gerisse: quem decide a fronteira da
 * transacção é quem chama.
 *
 * **E no `reserveStock` isso não é um detalhe — é o critério 1.** «A atomicidade
 * é por encomenda (tudo ou nada)»: as `n` linhas de uma encomenda reservam-se
 * todas ou nenhuma, e o que torna isso verdadeiro é quem chama abrir **uma**
 * transacção para a chamada inteira. Dentro dela, uma linha sem stock faz a
 * função devolver `OUT_OF_STOCK` sem escrever mais nada, e o `rollback` de quem
 * chama desfaz as linhas que já tinham passado.
 *
 * Por isso a função **não** tenta compensar à mão o que já reservou. Uma
 * compensação em código seria uma segunda implementação da mesma garantia, a
 * correr precisamente no caminho em que algo já falhou — e, se o processo
 * morresse a meio dela, deixava stock prometido a uma encomenda que não existe.
 * O `rollback` não tem esse modo de falha. O que a função faz é **recusar antes
 * de escrever** sempre que pode, e devolver o erro assim que uma linha falha.
 *
 * ## A ordem das linhas é a do pedido, e é deliberada
 *
 * Não se ordena por SKU para «evitar *deadlocks*». Um *deadlock* precisa de duas
 * transacções a trancar as mesmas duas linhas em ordens opostas, e aqui as
 * linhas de uma encomenda são trancadas pela ordem em que o cliente as pediu —
 * que é a mesma ordem em que o `lines_snapshot` as guarda. Duas encomendas com
 * os mesmos dois SKU em ordens diferentes **podem** entrelaçar-se, e a saída
 * para isso é a ordenação; fica **NÃO VERIFICADO** se acontece com carga real, e
 * o que se mede hoje é o caso do critério 1 (mil tentativas sobre **um** SKU,
 * onde não há duas linhas para ordenar). Ordenar por SKU agora era resolver um
 * problema que ninguém mediu e perder a correspondência com o `line_no`.
 */

import {
  erro,
  ok,
  type Erro,
  type ResultadoFinal,
} from "../port/contrato.ts";
import type { LinhaDaEncomenda } from "../orders/contrato.ts";
import type { RepoDoTenant } from "../orders/transition.ts";
import {
  ATIVA,
  ESTADOS_TERMINAIS,
  prazoDaReserva,
  prazoProvisorio,
  tectoComoIntervalo,
  ttlAceitavel,
  type Duration,
  type EstadoDaReserva,
  type LinhaAReservar,
  type MotivoDeLibertacao,
  type Reserva,
  type ViaDeCobranca,
} from "./contrato.ts";
import {
  SQL_CONSUMIR,
  SQL_DEVOLVER_STOCK,
  SQL_ESTENDER,
  SQL_LER_OFERTA,
  SQL_LER_RESERVAS,
  SQL_LIBERTAR,
  SQL_RESERVAR,
} from "./consultas.ts";

/** A tabela das reservas. **Qualificada pelo esquema**, e tem de ser.
 *
 * O `inserirNoTenant` do repo-base **constrói** o `INSERT` com este nome, e nada
 * neste repositório põe o `search_path`: o `comTenant` só põe o `app.tenant_id`
 * e o `db/bootstrap.py` registra que um `ALTER ROLE … SET search_path` é apagado
 * pelo `RESET ALL`. Sem o `platform.`, este `INSERT` morre em `42P01` no dia em
 * que alguém o chamar — a lição que o `TABELA_DO_REGISTO` do
 * `../orders/transition.ts` já pagou.
 */
export const TABELA_DAS_RESERVAS = "platform.stock_reservations";

/** O que as operações deste módulo recebem. A forma do `Encomendas`. */
export interface Reservas {
  readonly repo: RepoDoTenant;
  /** O relógio. Injectável para que os ensaios não dependam do de agora. */
  readonly agora?: () => Date;
}

/** O pedido de reserva: o `reserveStock(ctx, orderId, ttl)` da porta. */
export interface PedidoDeReserva {
  readonly orderId: string;
  readonly linhas: readonly LinhaAReservar[];
  readonly ttlMs: Duration;
  readonly via?: ViaDeCobranca;
  /**
   * `true` quando a reserva nasce **provisória** (critério 3): vive dois
   * minutos à espera do `charge.issued`, e é esse que lhe fixa o prazo.
   *
   * A omissão é `true`, e é a escolha segura: o caminho normal do checkout é
   * reservar **antes** de pedir a cobrança, pelo que uma reserva que nasça com
   * o prazo cheio sem cobrança emitida prende stock 48 h por um pedido que
   * pode nunca chegar ao PAY. Quem quiser o prazo cheio de uma vez pede-o.
   */
  readonly provisoria?: boolean;
}

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function recusar<T>(motivo: Erro): ResultadoFinal<T> {
  return erro<T>(motivo);
}

function comoReserva(linha: Readonly<Record<string, unknown>>): Reserva {
  return {
    reservationId: String(linha["id"]),
    orderId: String(linha["order_id"]),
    lineNo: Number(linha["line_no"]),
    sku: String(linha["sku"]),
    qty: Number(linha["qty"]),
    estado: String(linha["estado"]) as EstadoDaReserva,
    motivo:
      linha["motivo"] === null
        ? null
        : (String(linha["motivo"]) as MotivoDeLibertacao),
    expiraAt: String(linha["expira_at"]),
    confirmadaAt:
      linha["confirmada_at"] === null ? null : String(linha["confirmada_at"]),
    version: Number(linha["version"]),
  };
}

/** As reservas de uma encomenda, pela ordem das linhas. */
export async function lerReservas(
  r: Reservas,
  orderId: string,
): Promise<readonly Reserva[]> {
  const linhas = await r.repo.noTenant(SQL_LER_RESERVAS, [orderId]);
  return linhas.map(comoReserva);
}

/**
 * **O critério 1.** Promete stock para as linhas da encomenda, ou nenhuma.
 *
 * Ver a nota do módulo para a razão de a atomicidade ser de quem chama e para a
 * razão de não haver compensação em código.
 *
 * O `OUT_OF_STOCK` sai na **primeira** linha que não tenha stock, e não depois
 * de tentar todas: continuar a reservar depois de saber que a encomenda vai ser
 * recusada é prometer stock que o `rollback` vai devolver, e entre as duas
 * coisas há uma janela em que outro cliente vê menos stock do que há.
 */
export async function reserveStock(
  r: Reservas,
  pedido: PedidoDeReserva,
): Promise<ResultadoFinal<readonly Reserva[]>> {
  if (!UUID_CANONICO.test(pedido.orderId)) {
    return recusar("VALIDATION_ERROR");
  }
  if (pedido.linhas.length === 0) return recusar("VALIDATION_ERROR");
  const via: ViaDeCobranca = pedido.via ?? "referencia";
  if (!ttlAceitavel(pedido.ttlMs, via)) {
    // Um TTL fora da banda do critério 2 **não se silencia** nem se corrige
    // para o limite mais próximo: um TTL de uma hora aceite em silêncio era
    // uma reserva que expira antes de o cliente chegar ao ATM, e um corrigido
    // para 24 h era a plataforma a decidir um prazo que o chamador não pediu.
    return recusar("VALIDATION_ERROR");
  }
  for (const linha of pedido.linhas) {
    if (!Number.isInteger(linha.qty) || linha.qty <= 0) {
      return recusar("VALIDATION_ERROR");
    }
    if (!Number.isInteger(linha.lineNo) || linha.lineNo < 0) {
      return recusar("VALIDATION_ERROR");
    }
    if (linha.sku.trim() === "") return recusar("VALIDATION_ERROR");
  }

  const agora = (r.agora ?? (() => new Date()))();
  const provisoria = pedido.provisoria ?? true;
  const expiraAt = provisoria
    ? prazoProvisorio(agora)
    : prazoDaReserva(agora, pedido.ttlMs);

  const criadas: Reserva[] = [];
  for (const linha of pedido.linhas) {
    // **O predicado aritmético é a barreira.** Zero linhas devolvidas quer
    // dizer «não há stock», e não «o SKU não existe»: por isso o `NOT_FOUND`
    // distingue-se por uma leitura própria, e só no caminho da recusa — fazê-la
    // antes de cada reserva era uma viagem a mais no caminho normal.
    const movidas = await r.repo.noTenant(SQL_RESERVAR, [linha.sku, linha.qty]);
    if (movidas.length === 0) {
      const oferta = await r.repo.noTenant(SQL_LER_OFERTA, [linha.sku]);
      if (oferta.length === 0) return recusar("NOT_FOUND");
      return recusar("OUT_OF_STOCK");
    }
    const inseridas = await r.repo.inserirNoTenant({
      tabela: TABELA_DAS_RESERVAS,
      valores: {
        order_id: pedido.orderId,
        line_no: linha.lineNo,
        sku: linha.sku,
        qty: linha.qty,
        expira_at: expiraAt.toISOString(),
      },
      sufixo:
        "RETURNING id, order_id, line_no, sku, qty, estado, motivo, " +
        "expira_at, confirmada_at, version",
    });
    const criada = inseridas[0];
    if (criada === undefined) {
      // O `INSERT` não devolveu linha: só sobra o `UNIQUE (tenant_id,
      // order_id, line_no)` ter recusado, isto é, esta linha já estar
      // reservada. É um pedido inválido e não falta de stock — e o `rollback`
      // de quem chama devolve o que esta chamada já moveu.
      return recusar("VALIDATION_ERROR");
    }
    criadas.push(comoReserva(criada));
  }
  return ok(criadas);
}

/**
 * **O critério 6, lado `consumida`.** Marca as reservas da encomenda paga.
 *
 * **Não devolve stock**, e é a diferença inteira face ao `releaseReservation`:
 * uma reserva consumida é stock que saiu — o cliente pagou e vai levar o
 * produto. O `stock_reservada` fica como está, e o que desce é a
 * `stock_quantidade`, que é do Registo e não deste ticket (o §5.4 põe o stock
 * lá, e o inventário do Registo tem credor próprio).
 *
 * **NÃO VERIFICADO:** que a `stock_quantidade` desça ao consumir. Hoje não
 * desce, pelo que uma oferta com stock 10 e dez encomendas pagas fica com
 * `stock_quantidade = 10` e `stock_reservada = 10` — e a décima primeira
 * reserva é recusada, o que é o comportamento certo. O que falta é a baixa do
 * inventário, e obtém-se ligando o Registo.
 *
 * Idempotente pelo `WHERE estado = 'ativa'`: a segunda chamada muda zero linhas
 * e devolve `ok`. **`ok` e não `NOT_FOUND`**, porque «já estava consumida» é o
 * estado que quem chama queria — e um `payment.confirmed` entregue duas vezes
 * não é um erro, é o EVT a cumprir «pelo menos uma vez».
 */
export async function commitReservation(
  r: Reservas,
  orderId: string,
): Promise<ResultadoFinal<readonly Reserva[]>> {
  if (!UUID_CANONICO.test(orderId)) return recusar("VALIDATION_ERROR");
  const mudadas = await r.repo.noTenant(SQL_CONSUMIR, [orderId]);
  return ok(mudadas.map((linha) => consumida(linha, orderId)));
}

/**
 * A reserva que o `SQL_CONSUMIR` devolveu, na forma do `Reserva`.
 *
 * **O `RETURNING` do `SQL_CONSUMIR` traz o `expira_at` e o `confirmada_at`, e
 * isso foi uma correcção e não o desenho inicial.** A primeira versão deixava-os
 * fora e esta função inventava um valor de substituição para o prazo — um
 * `expira_at: ""` devolvido ao chamador, que é pior do que não devolver campo
 * nenhum: parece um instante e não é nenhum. A saída não era um sentinela
 * melhor; era a consulta devolver o que a sua própria forma de resposta promete.
 *
 * O `order_id` continua a entrar por argumento porque o `SQL_CONSUMIR` filtra
 * por ele e não precisa de o devolver.
 */
function consumida(
  linha: Readonly<Record<string, unknown>>,
  orderId: string,
): Reserva {
  return {
    reservationId: String(linha["id"]),
    orderId,
    lineNo: Number(linha["line_no"]),
    sku: String(linha["sku"]),
    qty: Number(linha["qty"]),
    estado: "consumida",
    motivo: null,
    expiraAt: String(linha["expira_at"]),
    confirmadaAt:
      linha["confirmada_at"] === null ? null : String(linha["confirmada_at"]),
    version: Number(linha["version"]),
  };
}

/**
 * **O critério 6, lado `libertada`.** Liberta com motivo e devolve o stock.
 *
 * Dois passos, e a ordem importa: liberta as reservas **primeiro** e devolve o
 * stock a seguir, com as `(sku, qty)` que o `RETURNING` trouxe. Pela ordem
 * inversa — devolver stock e depois libertar — uma falha no meio deixava stock
 * devolvido com a reserva ainda activa, isto é, a mesma unidade prometida duas
 * vezes. Nesta ordem, uma falha no meio deixa a reserva libertada e o stock por
 * devolver: menos stock à venda do que há, que é o lado seguro do erro e é
 * reconstruível pela reconciliação (regra 4 do §10.3).
 *
 * Idempotente pelo `WHERE estado = 'ativa'`, e é o critério 4 à letra
 * («execução dupla = 1 libertação»): a segunda chamada muda zero linhas, pelo
 * que devolve zero `(sku, qty)` e **não** devolve stock outra vez. O *trigger*
 * `stock_reserva_transicao` da revisão `0033` é a barreira para quem o forçasse.
 */
export async function releaseReservation(
  r: Reservas,
  orderId: string,
  motivo: MotivoDeLibertacao,
): Promise<ResultadoFinal<readonly Reserva[]>> {
  if (!UUID_CANONICO.test(orderId)) return recusar("VALIDATION_ERROR");
  const libertadas = await r.repo.noTenant(SQL_LIBERTAR, [orderId, motivo]);
  for (const linha of libertadas) {
    const devolvidas = await r.repo.noTenant(SQL_DEVOLVER_STOCK, [
      String(linha["sku"]),
      Number(linha["qty"]),
    ]);
    if (devolvidas.length === 0) {
      // O `stock_reservada >= $3` do predicado recusou: devolver esta
      // quantidade punha o contador abaixo de zero. Não é recuperável aqui —
      // significa que o contador e as reservas já divergiam —, e o que **não**
      // se faz é continuar calado: quem chama reverte, e a divergência fica
      // para a reconciliação em vez de ser emendada por um módulo que não sabe
      // qual dos dois lados está certo.
      return recusar("VALIDATION_ERROR");
    }
  }
  return ok(
    libertadas.map((linha) => ({
      reservationId: String(linha["id"]),
      orderId,
      lineNo: Number(linha["line_no"]),
      sku: String(linha["sku"]),
      qty: Number(linha["qty"]),
      estado: "libertada" as EstadoDaReserva,
      motivo,
      // Do `RETURNING`, como no `consumida`: ver a nota dessa função para a
      // razão de não haver aqui um sentinela.
      expiraAt: String(linha["expira_at"]),
      confirmadaAt:
        linha["confirmada_at"] === null ? null : String(linha["confirmada_at"]),
      version: Number(linha["version"]),
    })),
  );
}

/**
 * **O critério 7.** Prolonga o prazo, e só dentro do tecto de 72 h.
 *
 * O critério tem três condições e as três são impostas, duas delas na base:
 *
 * ```text
 * «só em aguarda_pagamento»      o estado da ENCOMENDA, por quem chama
 * «até ao limite de 72 h»        o `criado_at + $4` do SQL_ESTENDER
 * «exige cobrança com validade»  o `confirmada_at IS NOT NULL` do SQL_ESTENDER
 * ```
 *
 * **A primeira não está aqui, e é dito em vez de ser fingido.** Este módulo não
 * lê o `orders_mirror`: o estado da encomenda é de quem chama — o adaptador da
 * porta, que já o tem em mão —, e ir buscá-lo aqui era uma segunda leitura do
 * mesmo valor que podia discordar da primeira. O que **não** se faz é deixar a
 * condição sem dono: o `extendReservation` do adaptador verifica-a, e o ensaio
 * que o prova está em `services/com/tests/`.
 *
 * O tecto mede-se contra o `criado_at` **da reserva** e não contra `now()`: dois
 * `extendReservation` de 36 h cada passavam a validação um a um e somavam 72 h
 * sobre uma reserva que já tinha 48. Contra o `criado_at`, a soma é a que conta.
 */
export async function extendReservation(
  r: Reservas,
  orderId: string,
  until: string,
): Promise<ResultadoFinal<readonly Reserva[]>> {
  if (!UUID_CANONICO.test(orderId)) return recusar("VALIDATION_ERROR");
  const instante = new Date(until);
  if (Number.isNaN(instante.getTime())) return recusar("VALIDATION_ERROR");

  // **O tecto vem do `tectoComoIntervalo` e inclui a folga.** Era `72 hours`
  // secas, e a revisão adversarial mostrou o que isso custava: sobre uma
  // reserva criada com TTL de 72 h o `expira_at` dela é `criado_at + 72 h
  // 15 min`, isto é, já acima do tecto — e então `$3 > expira_at` e
  // `$3 <= criado_at + 72 h` não podem ser verdadeiros ao mesmo tempo, pelo que
  // aquela reserva **nunca** se podia prolongar. Ver a nota daquela função.
  const mudadas = await r.repo.noTenant(SQL_ESTENDER, [
    orderId,
    instante.toISOString(),
    tectoComoIntervalo(),
  ]);
  if (mudadas.length === 0) {
    // Zero linhas: ou não há reserva activa, ou ela é provisória (sem
    // cobrança), ou o instante pedido está para trás, ou passa do tecto. As
    // quatro são «o pedido não serve», e distingui-las exigia uma leitura a
    // mais para dar ao chamador uma informação que ele não usa — o critério
    // diz «fora disso falha».
    return recusar("VALIDATION_ERROR");
  }
  return ok(
    mudadas.map((linha) => ({
      reservationId: String(linha["id"]),
      orderId,
      lineNo: Number(linha["line_no"]),
      sku: String(linha["sku"]),
      qty: Number(linha["qty"]),
      estado: ATIVA,
      motivo: null,
      expiraAt: String(linha["expira_at"]),
      // **Do `RETURNING`, e não `null`.** Devolver `null` aqui era afirmar que
      // a reserva não tem cobrança — exactamente o contrário do que a tornou
      // elegível: o `SQL_ESTENDER` só casa linhas com `confirmada_at IS NOT
      // NULL`, que é a metade «exige cobrança com validade correspondente» do
      // critério 7.
      confirmadaAt:
        linha["confirmada_at"] === null ? null : String(linha["confirmada_at"]),
      version: Number(linha["version"]),
    })),
  );
}

/**
 * **A dívida que este ticket paga:** a fonte do `OUT_OF_STOCK` do `createOrder`.
 *
 * O `AutoridadeDeStock` do `../orders/create_order.ts` é um *hook* desde o
 * KAM-046, e o comentário dele nomeia este ticket por escrito: «a **passagem**
 * do código está implementada e medida … e a **fonte** falta. Credor: o
 * **KAM-045**». Esta função é essa fonte.
 *
 * **Lê, não reserva.** A pergunta do `createOrder` é «há stock para estas
 * linhas?», feita antes de a encomenda existir — e uma encomenda que ainda não
 * tem `id` não pode ter reserva, porque a `stock_reservations` referencia o
 * `order_id` por FK. Reservar aqui era prometer stock a uma encomenda
 * inexistente; quem reserva é o `reserveStock`, depois de ela nascer.
 *
 * **O que isso deixa aberto, e fica dito:** entre esta leitura e o
 * `reserveStock` há uma janela em que outro cliente pode levar o stock. Não é
 * um defeito desta função — é a diferença entre verificar e reservar —, e quem
 * fecha o caso é o `reserveStock`, cujo predicado aritmético recusa. O efeito
 * para o cliente é ver `OUT_OF_STOCK` um passo mais tarde, nunca stock
 * sobrevendido.
 *
 * Um SKU **sem quantidade declarada** devolve `true`: é o critério 8 («o
 * `indicativo` reserva internamente sem promessa de exclusividade»), e é também
 * o *fail-open* consciente que o `AutoridadeDeStock` já descrevia — recusar
 * tudo por não haver número fechava o caminho da encomenda para todo o
 * catálogo que ainda não declarou stock.
 */
export function autoridadeDeStock(
  r: Reservas,
): (linhas: readonly LinhaDaEncomenda[]) => Promise<boolean> {
  return async (linhas) => {
    for (const linha of linhas) {
      const oferta = await r.repo.noTenant(SQL_LER_OFERTA, [linha.sku]);
      const termos = oferta[0];
      // Um SKU que não existe **não** é falta de stock: o `createOrder` já o
      // recusa antes, pelo caminho do preço, e devolver `false` aqui
      // traduzia-o para `OUT_OF_STOCK` — que diz ao cliente «acabou» sobre uma
      // coisa que nunca houve. Deixa-se passar, e quem recusa é quem sabe.
      if (termos === undefined) continue;
      if (termos["stock_quantidade"] === null) continue;
      const quantidade = Number(termos["stock_quantidade"]);
      const reservada = Number(termos["stock_reservada"]);
      if (quantidade - reservada < linha.qty) return false;
    }
    return true;
  };
}

/** Uma reserva está num estado terminal? Ver o `ESTADOS_TERMINAIS`. */
export function terminal(estado: EstadoDaReserva): boolean {
  return (ESTADOS_TERMINAIS as readonly string[]).includes(estado);
}

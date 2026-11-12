/**
 * O efeito do consumidor de `payment.*` no COM (KAM-055).
 *
 * É a peça que faltava: o `packages/core-ts/src/eventos/` traz a transacção
 * idempotente, a ordem, o adiamento e a DLQ; o `../orders/transition.ts` traz o
 * CAS, o `paga_via`, o `paga_at`, o `order_state_log` e o `order.paid`; o
 * `../reservations/reserve.ts` traz o consumo das reservas. Nenhum deles sabia
 * que um `payment.confirmed` os liga, e este módulo é esse saber.
 *
 * ## O que corre, por esta ordem, e tudo na **mesma** transacção
 *
 *     0  o payload contra o contrato publicado (`validarPayload`)
 *     1  o `order_id` do payload contra o `agregado.id` do envelope
 *     2  ler a encomenda (estado, version, total_minor)
 *     3  se o valor difere do `total_minor`: emitir `payment.failed` e **parar**
 *     4  `transition(... para: "paga" ...)` — que grava o registo e emite o
 *        `order.paid` por dentro
 *     5  `commitReservation` — as reservas passam a `consumida`
 *
 * A transacção é a do `consumir`, que já escreveu a linha de `events_consumed`
 * **antes** de chamar este efeito. Isso não é um detalhe de ordem: o
 * `CONSTRAINT TRIGGER` diferido `order_estado_exige_log` da revisão `0030`
 * exige, no `COMMIT`, que uma encomenda que chega a `paga` cite um evento com
 * recibo de consumo **neste tenant**. Isto é, a barreira que o KAM-044 escreveu
 * só é satisfazível de dentro de um consumidor — e um `UPDATE` à mão com
 * `causa: "payment.confirmed"` e um `evento_id` inventado é recusado pela base.
 * O que este módulo faz é passar por essa barreira em vez de a contornar.
 *
 * ## Porque é que o `order.paid` não se emite aqui
 *
 * Porque o `transition` já o emite quando o `para` é `paga`
 * (`EVENTO_POR_ESTADO`), na mesma transacção e com o `payloadDePaga`. Emiti-lo
 * aqui dava **dois** `order.paid` por pagamento — e o critério 3 conta-os.
 *
 * ## Porque é que o `paga_via` não se passa
 *
 * Porque ele **deriva da causa**: o `VIA_POR_CAUSA` do `../orders/contrato.ts`
 * mapeia `payment.confirmed → provider_autenticado` e
 * `payment.manual_confirmed → manual_auditado`, que é o critério 5 à letra.
 * Passá-lo por argumento abria a porta a um chamador que dissesse
 * `manual_auditado` sobre um evento do facilitador.
 *
 * ## O que este módulo **não** decide
 *
 * O estado de partida e a ordem. Quem recusa um `payment.*` que chega antes de
 * `aguarda_pagamento` é o `consumir`, pela pré-condição do
 * `ESTADO_PRETENDIDO`. Repetir essa decisão aqui era tê-la em dois sítios, e o
 * sítio que falhasse primeiro decidia.
 *
 * **O que mudou com o KAM-050:** o `consumir` deixou de mandar para a DLQ um
 * pagamento sobre uma encomenda `expirada` ou `cancelada` (ver a
 * `ESTADOS_DE_EXCEPCAO` do `packages/core-ts/src/eventos/estados.ts`). Esses, e
 * o segundo pagamento de uma encomenda já paga, chegam aqui, e o
 * `../orders/late_payment.ts` aplica as quatro regras do `docs/tecnica/03` §6.6.
 */

import { validarPayload } from "@kamba/core-ts/eventos";
import type { ClienteSql, Efeito, Envelope } from "@kamba/core-ts/eventos";

import {
  ACTOR_DO_PAGAMENTO,
  CAUSAS_QUE_PAGAM,
  VIA_POR_CAUSA,
  type CausaQuePaga,
} from "../orders/contrato.ts";
import type { OrderState } from "../orders/contrato.ts";
import { emitir } from "../orders/eventos.ts";
import {
  aplicarPagamentoExcedente,
  aplicarPagamentoTardio,
  ramoDoPagamento,
  type PagamentoRecebido,
} from "../orders/late_payment.ts";
import {
  lerEncomenda,
  transition,
  type Encomendas,
} from "../orders/transition.ts";
import { commitReservation } from "../reservations/reserve.ts";
import { idsDoRegisto, repoBase } from "../repo-base/index.ts";

/**
 * O `motivo` do `payment.failed` quando o valor não bate (critério 6).
 *
 * É um dos **nove** `MOTIVOS_DE_FALHA` da revisão `0029`, que é o domínio que o
 * `payment_charges_motivo_falha_ck` fecha — e não um texto novo: quem abrir a
 * entrada no HND lê o mesmo nome que o ledger escreve.
 *
 * **`valor_divergente` e não `valor`**, e a diferença foi medida: o
 * `../../../../docs/tecnica/04` §5 escreve a forma curta (`motivo='valor'`) e o
 * DDL fecha a coluna na forma longa. Passar a curta dá `23514` — apanhado pelo
 * gerador das mil sequências de `db/tests_pagamentos/test_maquina.py`. Os dois
 * documentos não escrevem o mesmo vocabulário, e quem manda na coluna é o DDL.
 */
export const MOTIVO_DE_VALOR = "valor_divergente";

/**
 * O `provider` que o `payment.failed` leva quando o evento é o manual.
 *
 * O `payment.manual_confirmed` **não tem** `provider` no payload — o contrato
 * fecha-o em `order_id`, `valor_minor`, `currency` e `autenticacao` —, e o
 * `payment.failed` exige-o. O nome é o do adaptador do §3.2 e do ADR-013
 * (`ManualProvider`), e não um valor de enchimento: quem abrir a entrada no HND
 * precisa de saber que não houve facilitador nenhum.
 */
export const PROVIDER_MANUAL = "manual";

/** A versão dos eventos que este consumidor emite. A do mapa da `0035`. */
export const VERSAO_DO_FAILED = 1;

/** O payload do evento não é coerente com o envelope que o trouxe. */
export class PagamentoIncoerenteError extends Error {
  override readonly name = "PagamentoIncoerenteError";

  constructor(envelope: Envelope, orderId: string) {
    super(
      `o ${envelope.tipo} ${envelope.id} agrega por ${envelope.agregado.id} e ` +
        `o payload fala da encomenda ${orderId}: a garantia de ordem foi ` +
        "calculada para o agregado, pelo que aplicar o payload era transitar " +
        "uma encomenda que nunca foi ordenada",
    );
  }
}

/** A encomenda do evento não existe neste tenant. */
export class EncomendaAusenteError extends Error {
  override readonly name = "EncomendaAusenteError";

  constructor(orderId: string) {
    super(
      `a encomenda ${orderId} nao existe neste tenant; o consumir ja verificou ` +
        "o estado dela, pelo que isto e uma corrida ou um soft delete a meio",
    );
  }
}

/** O CAS perdeu: alguém mudou a encomenda entre a leitura e o `UPDATE`. */
export class ConflitoDeTransicaoError extends Error {
  override readonly name = "ConflitoDeTransicaoError";

  constructor(orderId: string, version: number) {
    super(
      `o CAS da encomenda ${orderId} falhou com version ${version}: reler e ` +
        "reavaliar, nunca forcar (§6.2)",
    );
  }
}

/**
 * O evento diz que a autenticação **não** correu bem, e o tipo diz que pagou.
 *
 * O `validarPayload` não a apanha: ele compara o conjunto de nomes de campo de
 * topo contra o catálogo gerado, e `autenticacao` é um objecto encaixado — um
 * `authn_ok: false` lá dentro tem o nome todo certo. O contrato publicado
 * declara-o com `"const": true` nos dois tipos que pagam, pelo que esta classe
 * é a leitura dessa cláusula do lado de quem **aplica** o dinheiro.
 *
 * **Hoje é profundidade e não furo aberto**, e vale dizê-lo: o único produtor
 * é a porta do ledger, e a `payment_evt_payload` da `0035` recusa construir um
 * `payment.confirmed` sem `authn_ok`. Mas a caixa 2 do DoD diz «sem atalho», e
 * as três barreiras que ela enumera estão **todas** do lado do produtor ou da
 * base: o `pagamentoAutenticado` olha para o `actor.kind` e para a causa, e o
 * `order_estado_exige_log` exige o recibo de consumo, que este consumidor
 * acabou de escrever. Nenhuma delas lê o `payload`.
 *
 * Vai para a DLQ pela escada normal, que é o destino certo: um pagamento
 * confirmado sem autenticação é anomalia de dinheiro, e o `PREFIXOS_SEV1`
 * trata `payment.` como Sev1.
 */
export class PagamentoNaoAutenticadoError extends Error {
  override readonly name = "PagamentoNaoAutenticadoError";

  constructor(tipo: string, orderId: string) {
    super(
      `o ${tipo} da encomenda ${orderId} traz authn_ok diferente de true: o ` +
        "contrato declara const true, e uma encomenda nao se paga por um " +
        "evento que diz que a autenticacao falhou (ADR-013)",
    );
  }
}

/** A transição ou o consumo das reservas foram recusados. */
export class EfeitoRecusadoError extends Error {
  override readonly name = "EfeitoRecusadoError";

  constructor(passo: string, motivo: string) {
    super(`o ${passo} do pagamento foi recusado com ${motivo}`);
  }
}

export interface DependenciasDoPagamento {
  /**
   * O nome do consumidor, que vai para o `order_state_log.actor_id`.
   *
   * O `actor_kind` é `sistema` e não é escolha deste módulo: o
   * `order_estado_exige_log` da `0030` exige-o, e o `ACTOR_DO_PAGAMENTO` é a
   * constante que o diz. O `actor_id` é texto e o que faz sentido ali é **quem
   * aplicou** — o consumidor —, não um UUID que não identifica pessoa nenhuma.
   */
  readonly consumer: string;
  /** Chamado com o atraso em segundos entre o evento e o `order.paid`. */
  readonly observarLag?: (segundos: number) => void;
  readonly agora?: () => Date;
}

/** `tipo` é um dos dois eventos que pagam? */
export function eCausaQuePaga(tipo: string): tipo is CausaQuePaga {
  return (CAUSAS_QUE_PAGAM as readonly string[]).includes(tipo);
}

/**
 * O atraso, em segundos, entre o instante do evento e agora.
 *
 * Função pura e exportada para ter ensaio próprio: o critério 9 mede um p95
 * sobre isto, e um cálculo errado dava um número verde sobre uma fila lenta. Um
 * `ocorrido_em` ilegível devolve `null` em vez de `NaN` — um `NaN` num
 * histograma cai num cesto e não se vê.
 */
export function lagEmSegundos(envelope: Envelope, agora: Date): number | null {
  const instante = Date.parse(envelope.ocorrido_em);
  if (!Number.isFinite(instante)) return null;
  return (agora.getTime() - instante) / 1_000;
}

/**
 * O `payload` do `payment.failed` do critério 6.
 *
 * Exportado para ter ensaio próprio contra o esquema publicado: é um envelope
 * que vai para o HND, e um campo errado chega lá como uma entrada que ninguém
 * consegue ler.
 */
export function payloadDeFalha(
  envelope: Envelope,
  orderId: string,
  motivo: string,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    order_id: orderId,
    provider:
      typeof envelope.payload["provider"] === "string"
        ? envelope.payload["provider"]
        : PROVIDER_MANUAL,
    motivo,
  };
  // A `referencia` é **opcional** no contrato, e um `null` não é um `string`:
  // omite-se quando não vem. É a mesma distinção que o `expira_at` do
  // `order.expired` faz no `../orders/eventos.ts`.
  if (typeof envelope.payload["referencia"] === "string") {
    payload["referencia"] = envelope.payload["referencia"];
  }
  return payload;
}

/**
 * O efeito, pronto a dar ao `criarTrabalhadores`.
 *
 * Fábrica e não função nua porque o `consumer` e o relógio entram por
 * dependência: um efeito que lesse o nome do processo de uma variável de
 * ambiente não se conseguia exercitar sem a definir.
 */
export function efeitoDePagamento(deps: DependenciasDoPagamento): Efeito {
  const agora = deps.agora ?? (() => new Date());

  return async function aplicarPagamento(
    bd: ClienteSql,
    envelope: Envelope,
  ): Promise<void> {
    // **Numa constante local, e não `envelope.tipo` repetido.** O
    // `eCausaQuePaga` é uma guarda de tipo, e o TypeScript estreita uma
    // variável com fiabilidade onde o estreitamento de um acesso a propriedade
    // depende de regras que mudaram entre versões. O `VIA_POR_CAUSA[tipo]` lá
    // abaixo precisa do tipo estreitado.
    const tipo = envelope.tipo;
    if (!eCausaQuePaga(tipo)) {
      // Fail-closed. A subscrição deste consumidor são os dois eventos de
      // pagamento; um terceiro tipo a chegar aqui é configuração errada, e
      // aplicar-lhe o caminho do `paga` era transitar uma encomenda por um
      // evento que ninguém decidiu que paga.
      throw new EfeitoRecusadoError("despacho", `tipo inesperado ${tipo}`);
    }
    // A **forma** do payload antes de tudo, e com a versão do envelope. É a
    // mesma barreira que a linha de emissão do `../orders/eventos.ts` já usa,
    // aplicada na entrada — e o que ela mede é exactamente isto: o conjunto de
    // nomes de campo **de topo** contra o catálogo gerado, mais o tipo e a
    // versão. Não valida tipos, `enum`, `const`, `format`, nem desce aos
    // objectos encaixados.
    //
    // **Dizer «o contrato antes de tudo» era dizer mais do que isto**, e foi o
    // que esta linha dizia: a cláusula que mais importa aqui — o
    // `autenticacao.authn_ok` com `"const": true` — está um nível abaixo do que
    // o `validarPayload` lê. Daí a guarda própria logo a seguir.
    validarPayload(tipo, envelope.versao, envelope.payload);

    const orderId = String(envelope.payload["order_id"]);
    if (orderId !== envelope.agregado.id) {
      throw new PagamentoIncoerenteError(envelope, orderId);
    }

    // O `authn_ok` do contrato, lido do payload. Ver o
    // `PagamentoNaoAutenticadoError` para a razão de ela existir com o
    // produtor a recusar isto a montante.
    //
    // **`!== true` e não `=== false`**: ausente, nulo, `"true"` em cadeia ou
    // `1` são todos «não me foi dito que correu bem», e num caminho de dinheiro
    // isso é uma recusa e não uma coerção.
    const autenticacao = envelope.payload["autenticacao"];
    const autenticado =
      typeof autenticacao === "object" &&
      autenticacao !== null &&
      (autenticacao as Record<string, unknown>)["authn_ok"] === true;
    if (!autenticado) {
      throw new PagamentoNaoAutenticadoError(tipo, orderId);
    }

    const ids = await idsDoRegisto(bd, envelope.tenant_id);
    const repo = repoBase(bd, envelope.tenant_id, ids.merchantId);
    const e: Encomendas = {
      ctx: {
        tenantId: envelope.tenant_id,
        actor: { kind: ACTOR_DO_PAGAMENTO, id: deps.consumer },
        traceId: envelope.trace_id ?? envelope.id,
      },
      repo,
      emitir: bd,
      agora,
    };

    const antes = await lerEncomenda(e, orderId);
    if (antes === null) throw new EncomendaAusenteError(orderId);

    // **O ramo, pelo estado** (KAM-050, `docs/tecnica/03` §6.6). O consumo já
    // deixou passar o estado — `expirada` pelo `podeTransitar`, a `cancelada` e
    // os já pagos pela `ESTADOS_DE_EXCEPCAO` —, e o que se faz com ele é daqui.
    const ramo = ramoDoPagamento(String(antes["estado"]) as OrderState);
    const pagamento: PagamentoRecebido = {
      orderId,
      eventoId: envelope.id,
      causa: tipo,
      valorMinor: BigInt(String(envelope.payload["valor_minor"])),
      currency: String(envelope.payload["currency"]),
    };
    if (ramo === "apos_cancelamento" || ramo === "duplicado") {
      // **Sem a verificação do valor**, e é de propósito: o pagamento não paga
      // a encomenda, pelo que comparar com o total não decide nada — o que se
      // pede de volta é o que entrou, seja qual for.
      await aplicarPagamentoExcedente(e, pagamento, ramo);
      return;
    }

    // **`BigInt` e não `Number`**, nos dois lados. O `total_minor` é `bigint` na
    // base e o condutor devolve-o como cadeia; um `Number()` acima de 2^53
    // arredonda **em silêncio**, e aqui o arredondamento decide entre pagar a
    // encomenda e emitir um `payment.failed`. É a mesma razão do `lerSeq` do
    // consumo, e vale a dobrar num caminho de dinheiro.
    //
    // **A exactidão que isto compra é do lado da base, e não do evento.** O
    // `valor_minor` do envelope já é um `number` quando chega aqui — o envelope
    // vem da fila por `JSON.parse` —, pelo que o `BigInt(String(...))` canoniza
    // um valor que já passou por um `double`. O que o prende é o produtor: a
    // coluna é `bigint` e o `jsonb` sai da base, pelo que nenhum valor real
    // chega acima de 2^53. O lado que podia perder precisão por nossa conta é o
    // `total_minor`, e esse vem como cadeia.
    const total = BigInt(String(antes["total_minor"]));
    const valor = pagamento.valorMinor;
    if (valor !== total) {
      // O critério 6: **não transita** e gera `payment.failed`. O evento fica
      // consumido — a linha de `events_consumed` do `consumir` confirma com
      // esta transacção —, e é isso que se quer: reentregá-lo produzia outro
      // `payment.failed` sobre a mesma divergência.
      await emitir(bd, envelope.tenant_id, {
        tipo: "payment.failed",
        versao: VERSAO_DO_FAILED,
        orderId,
        payload: payloadDeFalha(envelope, orderId, MOTIVO_DE_VALOR),
      });
      return;
    }

    // O pagamento tardio (regras 1 e 2) re-reserva **antes** de transitar e
    // consome as reservas por dentro; o caminho normal transita e consome aqui.
    const resultado =
      ramo === "tardio"
        ? (
            await aplicarPagamentoTardio(
              e,
              pagamento,
              Number(antes["version"]),
            )
          ).resultado
        : await transition(e, {
            orderId,
            para: "paga",
            expectedVersion: Number(antes["version"]),
            causa: { causa: tipo, eventoId: envelope.id },
          });
    if (resultado.tipo === "conflito") {
      throw new ConflitoDeTransicaoError(orderId, resultado.estado.version);
    }
    if (resultado.tipo === "erro") {
      throw new EfeitoRecusadoError("transition", resultado.erro);
    }

    // As reservas, **depois** da transição e na mesma transacção. A ordem é a do
    // §6.2 («reservas `consumida`» é efeito da aresta), e é idempotente pelo
    // `estado = 'ativa'` do `SQL_CONSUMIR`: uma encomenda sem reservas muda zero
    // linhas e devolve `ok`, que é o caso de uma venda de serviço. No ramo
    // tardio o `aplicarPagamentoTardio` já as consumiu, e a segunda chamada muda
    // zero linhas.
    const reservas = await commitReservation({ repo }, orderId);
    if (reservas.tipo === "erro") {
      throw new EfeitoRecusadoError("commitReservation", reservas.erro);
    }

    // **Observa-se aqui, e isso sobre-conta num `COMMIT` que falhe.** O efeito
    // corre dentro da transacção do `consumir`, e o `COMMIT` é depois dele:
    // se falhar, o atraso ficou contado para uma transição que não aconteceu.
    // O sítio certo era um gancho depois do `COMMIT`, e **o laço não tem
    // nenhum** — está dito na ressalva 7 de `docs/consumo.md`. Fica declarado
    // em vez de calado: a alternativa era não medir o critério 9 de todo, e um
    // `COMMIT` que falha deixa também uma entrada na DLQ, pelo que a
    // sobre-contagem é visível ao lado de um sinal que a explica.
    const lag = lagEmSegundos(envelope, agora());
    if (lag !== null) deps.observarLag?.(lag);

    // O `paga_via` **não** se verifica aqui, e a razão é a nota do módulo: ele
    // deriva da causa dentro do `transition`. O que se afirma é o que o
    // `VIA_POR_CAUSA` promete, para que um mapa alterado sem ensaio apareça
    // como erro e não como uma encomenda paga pela via errada.
    const via = VIA_POR_CAUSA[tipo];
    if (resultado.estado.pagaVia !== via) {
      throw new EfeitoRecusadoError(
        "paga_via",
        `esperava ${via} e a base ficou com ${String(resultado.estado.pagaVia)}`,
      );
    }
  };
}

/**
 * G2–G7: o que o *worker* decide antes de escrever no ledger (KAM-053).
 *
 * Os «Detalhes Técnicos» do bloco escrevem «o *worker* avalia G2–G7 e escreve
 * `pagamento_recebido` + `pagamento_confirmado`/`pagamento_divergente`». Esta é
 * a parte **avaliar**, isolada numa função pura.
 *
 * ## Porque é pura, e porque é que isso não é uma fuga
 *
 * A orquestração do *worker* — ler o *inbox*, abrir transacção, chamar a porta,
 * marcar o recibo — é I/O, e vive no serviço `pay`, que **não existe nesta
 * árvore** (dívida documental 148). O que **não** tem de esperar pelo serviço é
 * a decisão: dado o estado da cobrança e um evento já autenticado, que *gate*
 * falha e o que se escreve. Essa é uma função da tabela do §5 e de nada mais, e
 * uma função dessas prova-se sem base de dados nem fila.
 *
 * O que fica por fazer, e está dito no relatório: o processo que liga isto ao
 * `append_payment_event`. O que **não** fica frouxo é a barreira — mesmo um
 * *worker* mal escrito não consegue escrever `paga` sem passar pela porta, que
 * é a razão de o ledger não confiar nesta função para nada.
 *
 * ## G1 não está aqui, e G8 também não
 *
 * O **G1** (origem autenticada) é do *handler*: `hooks.ts` chama o
 * `verifyCallback` e devolve 401 quando ele lança. Um evento que chegue aqui já
 * passou G1 — ou veio por `status()`, que é a outra forma do §5 — e é por isso
 * que o parâmetro se chama `VerifiedEvent`.
 *
 * O **G8** (limites da confirmação humana, M-2..M-5) é do **KAM-054**: só se
 * aplica ao `ManualProvider`, e os tectos que ele mede são *propostas* a
 * calibrar no Piloto. Avaliá-lo aqui era inventar os valores.
 */

import type { Minor, Moeda, Uuid, VerifiedEvent } from "./tipos.ts";

/** Os *gates* que esta função avalia, pela ordem do §5. */
export const GATES_DO_WORKER = ["G2", "G3", "G4", "G5", "G6", "G7"] as const;
export type GateDoWorker = (typeof GATES_DO_WORKER)[number];

/** Os estados em que uma cobrança aceita um pagamento (G6). */
export const ESTADOS_QUE_ACEITAM = [
  "emitida",
  "aguarda_cliente",
  "pendente_confirmacao",
] as const;

/**
 * `expirada` aceita **com a regra do pagamento tardio** (G6, `03` §6.6).
 *
 * Fica à parte e não dentro de `ESTADOS_QUE_ACEITAM` porque não é o mesmo
 * facto: o §7.1 desenha `expirada --> paga: pagamento tardio autenticado`, e o
 * §6.6 do documento 03 põe condições que **este módulo não conhece** — se a
 * reserva se consegue refazer. Quem decide é o COM; aqui o veredicto diz
 * `tardio` e passa a decisão em vez de a tomar.
 */
export const ESTADO_TARDIO = "expirada" as const;

/**
 * Os estados em que um `duplo` é o F-08 — **a cobrança já foi paga** — e só
 * esses escrevem `pagamento_duplicado` (KAM-197).
 *
 * Desde a revisão `0051` o `pagamento_duplicado` sai como `payment.confirmed`, que
 * é o que a regra 4 do KAM-050 lê. Fora destes três estados ele mentia: o G6
 * devolve `duplo` também em `iniciada`, `falhada` e `cancelada`, e numa
 * `falhada` por valor divergente (F-02) a encomenda continua em
 * `aguarda_pagamento` — um `payment.confirmed` pagava-a sem o humano que o F-02
 * exige. Achado da revisão adversarial. **Nos outros, fica o facto**
 * (`pagamento_recebido`) e mais nada, como no `divergente` fora de `emitida`:
 * ops é alertado pelo veredicto, e quem decide é uma pessoa.
 */
export const ESTADOS_DO_DUPLICADO = [
  "paga",
  "reembolso_pendente",
  "reembolsada",
] as const;

/** A cobrança, como o *worker* a lê (G3 já resolvido: ela existe). */
export type CobrancaParaGates = {
  readonly chargeId: Uuid;
  readonly accountId: Uuid;
  readonly referencia: string | null;
  readonly amountMinor: Minor;
  readonly currency: Moeda;
  readonly estado: string;
};

/** A conta que o *token* resolveu, para o G2. */
export type ContaParaGates = {
  readonly accountId: Uuid;
  readonly entidade: string | null;
  readonly posId: string | null;
};

/** O que o evento diz sobre a conta de destino, quando o diz (G2). */
export type DestinoDoEvento = {
  readonly entidade?: string | null;
  readonly posId?: string | null;
};

/**
 * O veredicto. Chama-se `VeredictoDosGates` e nao `Veredicto` porque o
 * `conformidade.ts` (KAM-052) ja exporta um `Veredicto` — o da suite de
 * conformidade do §3.5 —, e dois tipos com o mesmo nome no `index.ts` do modulo
 * davam `TS2300`. Medido no gate 2. O sufixo e feio e e preferivel a renomear o
 * tipo de um ticket fundido.
 */
export type VeredictoDosGates =
  /** G2–G7 todos cumpridos: confirma. */
  | { readonly tipo: "confirmado" }
  /** G6 em `expirada`: autenticado, mas a decisão é do COM (`03` §6.6). */
  | { readonly tipo: "tardio" }
  /** G7: já registado. 200 sem efeito, recibo `duplicado`. */
  | { readonly tipo: "duplicado" }
  /** G3: não há cobrança. Alerta a ops; **não** reconhece no facilitador. */
  | { readonly tipo: "orfao" }
  /** G2, G4, G5: divergência com motivo. */
  | {
      readonly tipo: "divergente";
      readonly gate: GateDoWorker;
      readonly motivo: MotivoDeDivergencia;
      /**
       * O estado da cobrança quando a divergência foi vista.
       *
       * Vai no veredicto porque o `escritasDoVeredicto` precisa dele: o §7.1
       * desenha a aresta do `pagamento_divergente` **só** a partir de
       * `emitida`, e escrevê-la de outro estado faz a porta reverter a
       * transacção inteira — ver o `escritasDoVeredicto`.
       */
      readonly estadoDaCobranca: string;
    }
  /** G6 num estado terminal ou já pago. */
  | {
      readonly tipo: "duplo";
      readonly gate: "G6";
      /**
       * O estado da cobrança, pela razão do `divergente`: o
       * `escritasDoVeredicto` só escreve `pagamento_duplicado` nos
       * `ESTADOS_DO_DUPLICADO` (KAM-197).
       */
      readonly estadoDaCobranca: string;
    };

/**
 * Os motivos, com os nomes do `payment_charges.motivo_falha` do §6.2.
 *
 * São os nomes canónicos e não uma lista paralela: o que o *worker* decide
 * aqui é o que o `p_motivo` da porta leva, e o que a porta escreve na cobrança
 * quando ela passa a `falhada`. Duas listas com os mesmos significados é como
 * nasce uma divergência de vocabulário.
 */
export type MotivoDeDivergencia =
  | "entidade_divergente"
  | "valor_divergente"
  | "referencia_divergente";

export type EntradaDosGates = {
  readonly evento: VerifiedEvent;
  readonly conta: ContaParaGates;
  readonly destino?: DestinoDoEvento;
  /** `null` quando o G3 falha: não há cobrança para `(conta, referência)`. */
  readonly cobranca: CobrancaParaGates | null;
  /** O G7: esta entrega já está no ledger? */
  readonly jaRegistado: boolean;
};

/**
 * Avalia G2–G7 **pela ordem do §5**, e devolve o primeiro que falha.
 *
 * A ordem não é cosmética. O G7 (repetido) vem **antes** do G6 (estado
 * compatível), e isso tem uma consequência medida: a reentrega de um callback
 * de um pagamento que já confirmou tem a cobrança em `paga` — isto é, falha
 * G6 — e o que o §7.2 manda devolver é o F-01 («200, sem efeito», recibo
 * `duplicado`) e não o F-08 (pagamento duplo, que é um **segundo** pagamento
 * real). Avaliar G6 primeiro transformava toda a reentrega num caso de
 * reembolso.
 *
 * E o G3 vem antes de tudo, porque sem cobrança nenhum dos outros tem com o que
 * comparar.
 */
export function avaliarGates(entrada: EntradaDosGates): VeredictoDosGates {
  const { evento, conta, cobranca, destino, jaRegistado } = entrada;

  // G3: cobrança existente para `(provider, account_id, referencia)`.
  if (cobranca === null) {
    return { tipo: "orfao" };
  }

  // G7: não repetido. **Antes do G6** — ver o cabeçalho.
  if (jaRegistado) {
    return { tipo: "duplicado" };
  }

  // G2: conta correcta. A conta do *token* tem de ser a da cobrança, e a
  // entidade/POS do evento tem de bater com a conta — quando o facilitador os
  // devolve. Quando não os devolve, **não se inventa um veredicto**: a primeira
  // metade do G2 (a conta) basta-se, e a segunda não se pode avaliar.
  const divergente = (
    gate: GateDoWorker,
    motivo: MotivoDeDivergencia,
  ): VeredictoDosGates => ({
    tipo: "divergente",
    gate,
    motivo,
    estadoDaCobranca: cobranca.estado,
  });

  if (conta.accountId !== cobranca.accountId) {
    return divergente("G2", "entidade_divergente");
  }
  if (
    destino?.entidade != null &&
    conta.entidade != null &&
    destino.entidade !== conta.entidade
  ) {
    return divergente("G2", "entidade_divergente");
  }
  if (destino?.posId != null && conta.posId != null && destino.posId !== conta.posId) {
    return divergente("G2", "entidade_divergente");
  }

  // G4: valor exacto e moeda `AOA`. **Exacto nos dois sentidos** — a mais
  // também é divergência (F-02: «a menos ou a mais»), e é a parte que uma
  // comparação `>=` deixava passar.
  if (evento.valor !== cobranca.amountMinor || evento.currency !== cobranca.currency) {
    return divergente("G4", "valor_divergente");
  }

  // G5: referência bate com a cobrança. Quando a cobrança não tem referência
  // (um `express_push`), não há nada para comparar e o G5 não se aplica.
  if (
    cobranca.referencia !== null &&
    evento.referencia != null &&
    evento.referencia !== cobranca.referencia
  ) {
    return divergente("G5", "referencia_divergente");
  }

  // G6: estado compatível.
  if ((ESTADOS_QUE_ACEITAM as readonly string[]).includes(cobranca.estado)) {
    return { tipo: "confirmado" };
  }
  if (cobranca.estado === ESTADO_TARDIO) {
    return { tipo: "tardio" };
  }
  return { tipo: "duplo", gate: "G6", estadoDaCobranca: cobranca.estado };
}

/**
 * O que o *worker* escreve no ledger, por veredicto, pela ordem do §5.1.
 *
 * O `pagamento_recebido` vem **primeiro** em todos os veredictos que o têm: o
 * facto antes do juízo, que é a razão de o ledger separar factos de decisões
 * (§6.1). O `duplicado` não escreve nada — o
 * `payment_events_entrega_uq` já tem a linha, e escrever outra era repetir o
 * facto que o G7 diz que já existe.
 */
export function escritasDoVeredicto(
  veredicto: VeredictoDosGates,
): readonly { readonly tipo: string; readonly decisao: string }[] {
  switch (veredicto.tipo) {
    case "confirmado":
      return [
        { tipo: "pagamento_recebido", decisao: "informativo" },
        { tipo: "pagamento_confirmado", decisao: "aceite" },
      ];
    case "tardio":
      // F-07: o facto fica registado; a decisão é do COM (`03` §6.6), que
      // chama a porta outra vez com `pagamento_confirmado` se re-reservar.
      return [{ tipo: "pagamento_recebido", decisao: "informativo" }];
    case "divergente":
      // **A decisão só se escreve de onde o §7.1 a desenha.**
      //
      // O `pagamento_divergente` é aresta a partir de `emitida` e de mais
      // nenhum estado (dívida 166). A primeira versão prescrevia-o sempre, e a
      // revisão adversarial mediu a consequência: a partir de
      // `aguarda_cliente` ou de `pendente_confirmacao` a porta levanta
      // `check_violation` e **reverte a transacção inteira**, incluindo o
      // `pagamento_recebido` que a precede — isto é, o facto perdia-se por
      // causa da decisão.
      //
      // Onde a aresta não existe, fica o **facto** (que é o que o §5.1 manda
      // escrever primeiro, e nunca falha) e a cobrança não se move. O veredicto
      // continua a dizer `divergente`, pelo que ops é alertado do mesmo modo;
      // o que não acontece é perder o registo.
      return veredicto.estadoDaCobranca === "emitida"
        ? [
            { tipo: "pagamento_recebido", decisao: "informativo" },
            { tipo: "pagamento_divergente", decisao: "rejeitada" },
          ]
        : [{ tipo: "pagamento_recebido", decisao: "informativo" }];
    case "orfao":
      // **Nada vai para o ledger, e a revisão adversarial mostrou porquê.**
      //
      // A primeira versão prescrevia aqui `pagamento_orfao`, e esse evento é
      // **impossível de escrever**: um órfão é, por definição, um pagamento
      // *sem* cobrança (G3), e a única porta exige um `charge_id` que exista e
      // seja visível, numa coluna `NOT NULL` com FK. Medido: a chamada devolve
      // `23514 … a cobranca … nao existe ou nao e visivel`.
      //
      // Prescrever uma escrita impossível é pior do que não prescrever
      // nenhuma: o *worker* que a seguisse à letra abortava a transacção e
      // repetia o callback para sempre.
      //
      // O que o §8 manda fazer com um órfão é o que fica: **não reconhecer no
      // facilitador** (a fila dele reentrega, e o G7 absorve) e **alertar
      // ops**. O registo é o recibo `ignorado` no `payment_callbacks_inbox` —
      // que não tem `tenant_id` e por isso não precisa de cobrança — e o
      // alerta. O `tipo_evento` `pagamento_orfao` fica no domínio do §6.2 sem
      // caminho de escrita, e está na dívida documental 169.
      return [];
    case "duplo":
      // F-08: o segundo pagamento autenticado sobre uma cobrança já paga. **Só
      // aí**: ver o `ESTADOS_DO_DUPLICADO` — o `pagamento_duplicado` chega ao
      // COM como `payment.confirmed` desde a revisão `0051` (KAM-197).
      return (ESTADOS_DO_DUPLICADO as readonly string[]).includes(
        veredicto.estadoDaCobranca,
      )
        ? [
            { tipo: "pagamento_recebido", decisao: "informativo" },
            { tipo: "pagamento_duplicado", decisao: "informativo" },
          ]
        : [{ tipo: "pagamento_recebido", decisao: "informativo" }];
    case "duplicado":
      return [];
  }
}

/** O recibo que o *worker* escreve no `payment_callbacks_inbox` (§5.1). */
export function reciboDoVeredicto(
  veredicto: VeredictoDosGates,
): "processado" | "duplicado" | "ignorado" {
  if (veredicto.tipo === "duplicado") return "duplicado";
  if (veredicto.tipo === "orfao") return "ignorado";
  return "processado";
}

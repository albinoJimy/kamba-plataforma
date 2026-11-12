/**
 * A confirmação do dono para itens críticos (KAM-046, critério 7).
 *
 * ```text
 * item confirmar_dono  ->  criada + confirmacao_dono='pendente'
 *                          SEM referência e SEM reserva
 * sim do dono          ->  confirmada  (depois: reserva e charge.requested)
 * não do dono          ->  recusada  + cancelada
 * silêncio ao fim de N ->  expirada  + cancelada
 * ```
 *
 * ## «Sem referência nem reserva» é o que este ficheiro entrega, e é a parte
 * fácil de tratar como opcional
 *
 * O critério 7 diz, por extenso, que a encomenda do `confirmar_dono` fica
 * `criada` com `confirmacao_dono='pendente'` **sem referência nem reserva**. É a
 * barreira que impede o caminho mais natural — e o mais errado: emitir a
 * referência de pagamento e reservar o stock enquanto se espera pelo dono, para
 * «não perder a venda». Se o dono disser que não, o cliente já tem uma
 * referência de pagamento na mão para uma encomenda que não existe.
 *
 * Aqui isso é uma propriedade da assinatura e não um `if`: **nenhuma função
 * deste ficheiro chama a `transition` para `aguarda_pagamento`** (o estado onde a
 * referência vive) nem o `reserveStock`, que é do KAM-045 e não existe. O que
 * elas fazem é escrever a coluna `confirmacao_dono` — que **não muda o estado**,
 * pelo que o *trigger* diferido `order_estado_exige_log` devolve `NULL` e não há
 * linha de registo a escrever (e bem: aquela tabela tem `CHECK (de <> para)` e
 * aqui não há `de`).
 *
 * ## O «sim» do dono **não** chega a emitir `charge.requested`, e o credor está
 * nomeado
 *
 * O critério 7 continua: «sim do dono → reserva e `charge.requested`». Nenhuma
 * das duas metades é alcançável neste ticket, e as razões são diferentes:
 *
 * * a **reserva** é o `reserveStock` e a `stock_reservations` do §6.4 —
 *   **KAM-045**, que o bloco deste ticket nomeia na instrução «não expandas
 *   escopo»;
 * * o **`charge.requested` não existe**. Nenhum contrato do catálogo publicado
 *   (`contratos/eventos/`) é ele, e a lista fechada do §3.5 do dicionário
 *   também não o tem. Ele vive só no §12 do `docs/tecnica/03`,
 *   que é precisamente o «segundo catálogo de eventos, paralelo ao do
 *   `docs/tecnica/06` §5» da **dívida documental 37**. Emiti-lo levantava
 *   `TipoDesconhecidoError` no `validarPayload` antes de o *gate* 7 chegar a ver
 *   o envelope, e se passasse paralisava no publicador. Credor: **KAM-054/055**,
 *   que são os donos do consumidor, mais o ticket de canon que acrescente o
 *   contrato e emende a contagem do §3.5.
 *
 * O mesmo vale para os três eventos que os *Detalhes Técnicos* do bloco
 * atribuem a este ticket — `order.owner_confirmation_requested`,
 * `order.owner_confirmed` e `order.owner_rejected`: nenhum tem contrato e nenhum
 * está no §3.5. O que fica no lugar deles é a **coluna**, que é a autoridade do
 * ciclo de vida (§10.1) e é o que a reconciliação e o aviso ao dono (KAM-115)
 * leem. O que não sai é o evento, e isso está dito aqui em vez de ser emitido
 * com um nome inventado.
 *
 * O caminho do «não» e do silêncio **sim** emite: os dois acabam em `cancelada`,
 * e o `order.cancelled` tem contrato e sai pelo `transition` do KAM-044. É a
 * metade do critério que fecha inteira.
 *
 * ## O prazo e o lembrete são *propostas*, e o horário comercial não está cá
 *
 * O critério escreve a omissão como *proposta*: «15 min em horário comercial do
 * tenant, lembrete aos 5 min». Os dois números ficam como constantes marcadas
 * *proposta*; o **horário comercial** não se cumpre, e não por esquecimento: a
 * janela de funcionamento de um tenant vive no módulo `servicos`
 * (`disponibilidade.ts`, KAM-047) e trazê-la para cá era acoplar a encomenda à
 * agenda por uma regra que ninguém calibrou. O que esta decisão usa é tempo de
 * relógio, e a diferença está dita: fora de horas, quinze minutos de relógio
 * expiram uma encomenda que o dono nunca teve oportunidade de ver.
 *
 * E **quem corre o prazo não existe**: não há agendador. A `decidirPorSilencio`
 * é pura e devolve o que se deve fazer; quem a chama de minuto a minuto é o
 * varrimento, cujo credor é o **KAM-071** (retenção e *jobs*), com o aviso ao
 * dono no **KAM-115**. Está escrito na verificação do bloco e a caixa fica
 * `parcial`.
 */

import {
  SQL_CONFIRMACAO_DO_DONO,
  SQL_LER_CONFIRMACAO,
} from "./consultas.ts";
import type { ConfirmacaoDoDono } from "./create_order.ts";
import { CONFIRMACOES_DO_DONO } from "./create_order.ts";
import { transition, type Encomendas, type ResultadoDaTransicao } from "./transition.ts";

export { CONFIRMACOES_DO_DONO };
export type { ConfirmacaoDoDono };

/**
 * Quanto tempo o dono tem para responder. **15 minutos, *proposta*.**
 *
 * O número é do critério 7, que o declara omissão *proposta*. Calibra-se com
 * dados do Piloto — o tempo real de resposta de um dono a um aviso de WhatsApp —
 * e o ticket que o mede é o **KAM-096** (calibração com dados do Piloto), pela
 * mesma via que os tectos do `ManualProvider`.
 */
export const MINUTOS_PARA_O_DONO = 15;

/** Quando se lembra o dono. **5 minutos, *proposta*.** Mesma fonte. */
export const MINUTOS_PARA_O_LEMBRETE = 5;

/** A causa que o cancelamento por recusa do dono grava no registo. */
export const CAUSA_DA_RECUSA = "dono_recusa";

/**
 * A causa que o cancelamento por silêncio grava no registo.
 *
 * `ttl` e não `silencio_dono`: é o nome que o `base.py` da suite das encomendas
 * já usa para a expiração e o que o §5.4 dá como exemplo, e a coluna `causa` é
 * texto livre de propósito — inventar um segundo nome para «o prazo acabou» dava
 * duas causas para a mesma coisa numa tabela que ninguém pode corrigir depois
 * (o `order_state_log` é *append-only*).
 */
export const CAUSA_DO_SILENCIO = "ttl";

/** O resultado de escrever a coluna. Três formas, como a transição. */
export type ResultadoDaConfirmacao =
  | {
      readonly tipo: "ok";
      readonly orderId: string;
      readonly numeroPublico: string;
      readonly confirmacaoDono: ConfirmacaoDoDono;
      readonly version: number;
    }
  | { readonly tipo: "conflito"; readonly confirmacaoDono: ConfirmacaoDoDono }
  | { readonly tipo: "erro"; readonly erro: "NOT_FOUND" | "VALIDATION_ERROR" };

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Escreve `confirmacao_dono` por CAS pelo subestado esperado.
 *
 * **O CAS é o que torna isto idempotente**, e não um `UPDATE` cego: dois cliques
 * no mesmo botão do dono dão uma escrita e um conflito, e o conflito traz a
 * releitura — que é a mesma escolha que o `transition.ts` do KAM-044 fez para o
 * CAS de `version`, e pela mesma razão do §6.2 («reler e reavaliar, nunca
 * forçar»).
 *
 * `de === para` é um caso legítimo e devolve `ok` **sem escrever duas vezes**:
 * um `UPDATE` cujo predicado é o valor que já lá está encontra a linha e
 * reescreve o mesmo valor. Não é um *no-op* gratuito — o `atualizado_at` sobe, e
 * é a prova de que alguém voltou a pedir.
 */
async function escrever(
  e: Encomendas,
  orderId: string,
  de: ConfirmacaoDoDono,
  para: ConfirmacaoDoDono,
): Promise<ResultadoDaConfirmacao> {
  if (!UUID_CANONICO.test(orderId)) {
    return { tipo: "erro", erro: "VALIDATION_ERROR" };
  }
  const linhas = await e.repo.noTenant(SQL_CONFIRMACAO_DO_DONO, [
    orderId,
    para,
    de,
  ]);
  const linha = linhas[0];
  if (linha === undefined) {
    // Zero linhas: ou a encomenda não existe (ou é de outro tenant, §5.5), ou o
    // subestado não bate, ou ela já saiu de `criada`. As três distinguem-se por
    // uma releitura, e é por isso que esta função a faz em vez de devolver um
    // código que juntasse as três numa só resposta.
    const relido = await e.repo.noTenant(SQL_LER_CONFIRMACAO, [orderId]);
    const actual = relido[0];
    if (actual === undefined) return { tipo: "erro", erro: "NOT_FOUND" };
    return {
      tipo: "conflito",
      confirmacaoDono: String(
        actual["confirmacao_dono"],
      ) as ConfirmacaoDoDono,
    };
  }
  return {
    tipo: "ok",
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    confirmacaoDono: String(linha["confirmacao_dono"]) as ConfirmacaoDoDono,
    version: Number(linha["version"]),
  };
}

/**
 * Pede a confirmação ao dono: `nao_aplicavel` → `pendente`.
 *
 * **Não emite nada e não reserva nada** — ver a nota do módulo. É o método 5 da
 * porta (`requestOwnerConfirmation`) do lado do módulo, e **está ligado ao
 * adaptador desde o KAM-178**: os três casos atravessam a porta um a um, com o
 * `conflito` a ser o terceiro caso do `Resultado` e não um `VALIDATION_ERROR`.
 * Esta nota dizia que a ligação «fica para quem decidir como a porta expressa os
 * códigos deste domínio»; a decisão foi tomada (emenda 1.59 do dicionário) e o
 * resíduo de credor fica apagado em vez de ficar a nomear uma espera que acabou.
 *
 * Uma encomenda que já está `pendente` devolve `ok`: pedir duas vezes é o que o
 * lembrete dos cinco minutos faz, e tratá-lo como conflito obrigava o
 * varrimento a distinguir dois casos que são o mesmo.
 */
export async function requestOwnerConfirmation(
  e: Encomendas,
  orderId: string,
): Promise<ResultadoDaConfirmacao> {
  const primeiro = await escrever(e, orderId, "nao_aplicavel", "pendente");
  if (primeiro.tipo !== "conflito") return primeiro;
  if (primeiro.confirmacaoDono !== "pendente") return primeiro;
  return await escrever(e, orderId, "pendente", "pendente");
}

/**
 * O «sim» do dono: `pendente` → `confirmada`.
 *
 * O que **devia** vir a seguir — a reserva e o `charge.requested` — não é
 * alcançável neste ticket, e a nota do módulo diz porquê e de quem é. Esta
 * função escreve a coluna e pára aí, de propósito: o passo seguinte do §6.2 é
 * `criada → aguarda_pagamento` com «`reserveStock` e depois `charge.issued`», e
 * fazer essa transição sem reserva deixava uma encomenda à espera de pagamento
 * com stock que ninguém guardou.
 */
export async function confirmarPeloDono(
  e: Encomendas,
  orderId: string,
): Promise<ResultadoDaConfirmacao> {
  return await escrever(e, orderId, "pendente", "confirmada");
}

/** O que um cancelamento pelo dono devolve: a coluna e a transição. */
export interface CancelamentoPeloDono {
  readonly confirmacao: ResultadoDaConfirmacao;
  /** `null` quando a coluna não se escreveu: então não se transita. */
  readonly transicao: ResultadoDaTransicao | null;
}

/**
 * Fecha a confirmação e cancela a encomenda. É o «não» e o silêncio.
 *
 * **A ordem é a coluna primeiro e a transição depois**, e não o contrário: o
 * `SQL_CONFIRMACAO_DO_DONO` exige `estado = 'criada'` no predicado, pelo que
 * depois do cancelamento a coluna já não se consegue escrever — e uma encomenda
 * cancelada com `confirmacao_dono='pendente'` dizia a quem a lesse que ainda
 * esperava pelo dono.
 *
 * A transição emite `order.cancelled`, que **tem** contrato, e o `motivo` do
 * payload é a `causa` que entra no registo (a tradução está fixada no §3.5 do
 * dicionário). «Reservas libertadas» é vácuo hoje — não há reservas, pela
 * barreira do critério 7 —, e é o `releaseReservation` do KAM-045 que lhe dará
 * conteúdo.
 *
 * Se a coluna não se escrever, **não se cancela**: a transição ficava órfã de
 * razão, e cancelar uma encomenda cujo subestado não se conseguiu mudar é
 * cancelar sem saber por que estado ela estava.
 */
async function fecharECancelar(
  e: Encomendas,
  orderId: string,
  para: Extract<ConfirmacaoDoDono, "recusada" | "expirada">,
  version: number,
  causa: string,
): Promise<CancelamentoPeloDono> {
  const confirmacao = await escrever(e, orderId, "pendente", para);
  if (confirmacao.tipo !== "ok") return { confirmacao, transicao: null };
  const transicao = await transition(e, {
    orderId,
    para: "cancelada",
    expectedVersion: version,
    causa: { causa },
  });
  return { confirmacao, transicao };
}

/** O «não» do dono: `recusada` e `cancelada`. */
export async function recusarPeloDono(
  e: Encomendas,
  orderId: string,
  version: number,
): Promise<CancelamentoPeloDono> {
  return await fecharECancelar(
    e,
    orderId,
    "recusada",
    version,
    CAUSA_DA_RECUSA,
  );
}

/** O silêncio ao fim do prazo: `expirada` e `cancelada`. */
export async function expirarConfirmacao(
  e: Encomendas,
  orderId: string,
  version: number,
): Promise<CancelamentoPeloDono> {
  return await fecharECancelar(
    e,
    orderId,
    "expirada",
    version,
    CAUSA_DO_SILENCIO,
  );
}

/** O que o varrimento deve fazer a uma encomenda à espera do dono. */
export type AccaoPorSilencio = "aguardar" | "lembrar" | "expirar";

/**
 * A decisão do silêncio, **pura**: o que fazer com o tempo que passou.
 *
 * Separada da escrita de propósito, e é a separação que torna a fronteira dos
 * quinze minutos um ensaio em vez de uma espera: o `agora` entra como argumento
 * e a fronteira escreve-se como uma igualdade. É a mesma escolha que o
 * `SQL_COTACAO_VALIDA` do KAM-043 fez para a validade de uma cotação.
 *
 * A fronteira é `>=` nos dois limiares — aos quinze minutos exactos **expira**,
 * e aos cinco exactos **lembra**. Com `>`, uma encomenda ficava um instante em
 * cada lado sem acção nenhuma, e o varrimento que corresse exactamente nesse
 * instante não fazia nada.
 *
 * **O horário comercial do tenant não entra aqui** — ver a nota do módulo. Esta
 * função mede tempo de relógio, e o que falta está nomeado com credor.
 */
export function decidirPorSilencio(
  pedidoEm: Date,
  agora: Date,
  lembreteJaEnviado: boolean,
): AccaoPorSilencio {
  const minutos = (agora.getTime() - pedidoEm.getTime()) / 60_000;
  if (minutos >= MINUTOS_PARA_O_DONO) return "expirar";
  if (!lembreteJaEnviado && minutos >= MINUTOS_PARA_O_LEMBRETE) {
    return "lembrar";
  }
  return "aguardar";
}

/**
 * A máquina de estados da encomenda, e o contrato que o consumidor usa.
 *
 * O `paga` só é alcançável por evento autenticado (ADR-013), e a transição que
 * importa é `aguarda_pagamento → paga` por `payment.confirmed`. Um consumidor
 * que aplicasse `paga` a partir de `criada` estaria a confirmar um pagamento
 * sobre uma encomenda sem referência emitida — e é por isso que a verificação
 * não é um detalhe do consumidor: é uma pré-condição dele.
 *
 * O grafo é o do `docs/tecnica/00_Arquitectura_Solucao.md` §6.1, transcrito
 * **inteiro** e não só a parte do pagamento: um subconjunto convidava a tratar
 * um estado desconhecido como «pode», que é o erro que fecha a porta ao
 * contrário.
 *
 * O consumidor fala com a interface `MaquinaDeEstados`, não com esta tabela: o
 * teste de contrato do critério 3 usa uma máquina **falsa** que diz «não» a
 * tudo, e é assim que se prova que a transição inválida nunca se aplica sem
 * depender do grafo real estar certo.
 */

/** Os estados da encomenda (`docs/tecnica/00` §6.1). Lista fechada. */
export const ESTADOS_DA_ENCOMENDA = [
  'criada',
  'aguarda_pagamento',
  'pendente_confirmacao',
  'paga',
  'expirada',
  'cancelada',
  'em_entrega',
  'entregue',
  'entrega_falhada',
  'em_disputa',
  'reembolso_pendente',
  'reembolsada',
] as const;

export type EstadoDaEncomenda = (typeof ESTADOS_DA_ENCOMENDA)[number];

/**
 * As transições do §6.1: `{estado: [estados alcançáveis]}`.
 *
 * Transcrita do diagrama, aresta a aresta. O `expirada → paga` está lá de
 * propósito («pagamento tardio confirmado»): é um caso real do Multicaixa por
 * referência, e tirá-lo daqui fazia o consumidor mandar para a DLQ um
 * pagamento que o negócio aceita.
 */
export const TRANSICOES: Readonly<Record<EstadoDaEncomenda, readonly EstadoDaEncomenda[]>> = {
  criada: ['aguarda_pagamento'],
  aguarda_pagamento: ['paga', 'pendente_confirmacao', 'expirada'],
  pendente_confirmacao: ['paga', 'aguarda_pagamento'],
  paga: ['em_entrega', 'entregue', 'reembolso_pendente'],
  expirada: ['aguarda_pagamento', 'cancelada', 'paga'],
  cancelada: [],
  em_entrega: ['entregue', 'entrega_falhada'],
  entregue: ['em_disputa'],
  entrega_falhada: ['em_entrega', 'reembolso_pendente'],
  em_disputa: ['reembolso_pendente', 'entregue'],
  reembolso_pendente: ['reembolsada'],
  reembolsada: [],
};

/**
 * Que estado cada tipo de evento **causa**.
 *
 * O critério é um só, e é esse que decide a lista: estão aqui os eventos cujo
 * consumo **aplica** a transição, e é por isso que precisam da pré-condição de
 * estado. São os dois de pagamento, e a razão é o ADR-013 — o `paga` só é
 * alcançável por evento autenticado.
 *
 * **Não** estão aqui, e a primeira versão deste ficheiro tinha-os:
 * `order.expired`, `order.delivered` e `order.paid`. Esses são emitidos pelo COM
 * **depois** da transição (`../docs/tecnica/03` §6): quem os consome está a ser
 * informado, não a decidir. Pedir-lhes uma pré-condição de estado era exigir
 * que a réplica do consumidor já tivesse o estado **novo** para aceitar a
 * notícia dele — e isso adiava toda a primeira entrega.
 *
 * Misturar os dois critérios foi o defeito: a revisão do espelho em Python
 * apanhou-o ao perguntar porque faltava o `order.paid`, que é Sev1 ao lado de
 * `payment.*` no §6.4 e não causa transição nenhuma.
 */
export const ESTADO_PRETENDIDO: Readonly<Record<string, EstadoDaEncomenda>> = {
  'payment.confirmed': 'paga',
  'payment.manual_confirmed': 'paga',
};

/** O que o consumidor pergunta antes de aplicar um efeito de transição. */
export interface MaquinaDeEstados {
  /**
   * O estado actual do agregado, ou `null` se não existir.
   *
   * `null` **não** é «pode»: um `payment.confirmed` sobre uma encomenda que
   * ainda não existe na réplica do consumidor é exactamente o caso que o
   * critério 3 manda adiar.
   */
  estadoDe(agregadoTipo: string, agregadoId: string): Promise<EstadoDaEncomenda | null>;
}

export class EstadoDesconhecidoError extends Error {
  readonly estado: string;

  constructor(estado: string) {
    super(`estado fora da máquina do §6.1: ${estado}`);
    this.name = 'EstadoDesconhecidoError';
    this.estado = estado;
  }
}

/** `estado` é um dos doze? */
export function eEstado(estado: string): estado is EstadoDaEncomenda {
  return (ESTADOS_DA_ENCOMENDA as readonly string[]).includes(estado);
}

/**
 * A transição `de → para` existe no §6.1?
 *
 * Um estado de origem desconhecido **lança**, em vez de devolver `false`: um
 * `false` silencioso aqui era indistinguível de «a transição não existe», e a
 * diferença decide entre adiar (estado por chegar) e DLQ (transição inválida).
 */
export function podeTransitar(de: string, para: string): boolean {
  if (!eEstado(de)) throw new EstadoDesconhecidoError(de);
  if (!eEstado(para)) throw new EstadoDesconhecidoError(para);
  return TRANSICOES[de].includes(para);
}

/**
 * A máquina real, sobre a tabela de encomendas do consumidor.
 *
 * `COM` (o core de comércio) é o KAM-041 e ainda não existe; esta
 * implementação lê a coluna de estado da tabela que lhe for dada, para que o
 * consumidor não fique à espera dela. A consulta é parametrizada e o nome da
 * tabela é validado contra uma forma fechada — não se interpola um nome vindo
 * de fora numa consulta.
 */
const NOME_DE_TABELA = /^[a-z][a-z0-9_]{1,62}$/;

export interface ClienteDeLeitura {
  query(sql: string, parametros?: unknown[]): Promise<{ rows: Array<Record<string, unknown>> }>;
}

export class MaquinaNaBase implements MaquinaDeEstados {
  readonly #bd: ClienteDeLeitura;
  readonly #tabela: string;
  readonly #colunaId: string;
  readonly #colunaEstado: string;

  constructor(
    bd: ClienteDeLeitura,
    tabela = 'orders',
    colunaId = 'id',
    colunaEstado = 'estado',
  ) {
    for (const nome of [tabela, colunaId, colunaEstado]) {
      if (!NOME_DE_TABELA.test(nome)) throw new Error(`nome inválido: ${nome}`);
    }
    this.#bd = bd;
    this.#tabela = tabela;
    this.#colunaId = colunaId;
    this.#colunaEstado = colunaEstado;
  }

  async estadoDe(agregadoTipo: string, agregadoId: string): Promise<EstadoDaEncomenda | null> {
    if (agregadoTipo !== 'order') return null;
    const { rows } = await this.#bd.query(
      `SELECT ${this.#colunaEstado} AS estado FROM platform.${this.#tabela} ` +
        `WHERE ${this.#colunaId} = $1`,
      [agregadoId],
    );
    const linha = rows[0];
    if (linha === undefined) return null;
    const estado = String(linha.estado);
    if (!eEstado(estado)) throw new EstadoDesconhecidoError(estado);
    return estado;
  }
}

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

/**
 * Os estados em que um `payment.*` **nunca** se resolve esperando (KAM-055).
 *
 * É uma lista diferente da `TRANSICOES`, e a diferença é o que o critério 7 do
 * KAM-055 pede. Sem ela, os dois estados terminais caíam em sítios errados e
 * nenhum dos dois dava o código que o critério nomeia:
 *
 * * `cancelada` não tem arestas de saída, pelo que `podeTransitar` diz «não» e
 *   o consumidor **adia** — e adia seis vezes, para acabar na DLQ com
 *   `adiado_sem_resolver`, gastando trinta minutos de fila a esperar por um
 *   estado que nunca chega;
 * * `expirada` está na `TRANSICOES` **com** `paga` de propósito (o pagamento
 *   tardio do Multicaixa por referência é um caso real), pelo que
 *   `podeTransitar` diz «pode» — e o efeito ia aplicar uma transição que o
 *   grafo da base, onde o núcleo da revisão `0030` não tem essa aresta,
 *   recusa com um erro técnico que nada diz a quem o lê na DLQ.
 *
 * As duas são então **terminais para este consumidor**: vão direitas à DLQ com
 * `estado_incompativel`, que é Sev1 por `payment.` já estar em
 * `PREFIXOS_SEV1`. O caso completo do pagamento tardio é o **KAM-050**, e é por
 * isso que a aresta `expirada → paga` fica na `TRANSICOES` em vez de sair: o
 * grafo do §6.1 continua a ser o do negócio, e o que esta lista diz é só que
 * **este** ticket não a implementa.
 */
export const ESTADOS_INCOMPATIVEIS: Readonly<Record<string, readonly EstadoDaEncomenda[]>> = {
  'payment.confirmed': ['expirada', 'cancelada'],
  'payment.manual_confirmed': ['expirada', 'cancelada'],
};

/** O que o consumidor pergunta antes de aplicar um efeito de transição. */
export interface MaquinaDeEstados {
  /**
   * O estado actual do agregado, ou `null` se não existir.
   *
   * `null` **não** é «pode»: um `payment.confirmed` sobre uma encomenda que
   * ainda não existe na réplica do consumidor é exactamente o caso que o
   * critério 3 manda adiar.
   *
   * **O `bd` é o da transacção do consumo, e vem por argumento de propósito.**
   * Tinha sido o cliente do construtor, e a primeira implementação real
   * (KAM-055) mostrou que isso não funcionava: o `consumir` corre
   * `SET LOCAL app.tenant_id` **dentro** da sua transacção, pelo que uma
   * máquina ligada a outra sessão lia a `orders_mirror` sem contexto — e sob
   * RLS `FORCE` isso não é «vê menos», é `null` **sempre**, que a pré-condição
   * lê como «a encomenda ainda não existe» e adia até à DLQ. Recebendo o
   * cliente, a leitura é estruturalmente a da transacção e não por combinação.
   */
  estadoDe(
    agregadoTipo: string,
    agregadoId: string,
    bd: ClienteDeLeitura,
  ): Promise<EstadoDaEncomenda | null>;
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
 * O estado é incompatível com este tipo de evento, sem esperança de mudar?
 *
 * Um estado desconhecido **lança**, pela mesma razão que o `podeTransitar`: um
 * `false` silencioso aqui lia-se como «compatível» e mandava o evento pelo
 * caminho do adiamento, que é o oposto da decisão que o critério 7 do KAM-055
 * quer. Ver a `ESTADOS_INCOMPATIVEIS`.
 */
export function estadoIncompativel(tipo: string, estado: string): boolean {
  if (!eEstado(estado)) throw new EstadoDesconhecidoError(estado);
  return (ESTADOS_INCOMPATIVEIS[tipo] ?? []).includes(estado);
}

/**
 * A máquina real, sobre a tabela de encomendas do consumidor.
 *
 * Lê a coluna de estado da tabela que lhe for dada. A consulta é parametrizada
 * e o nome da tabela é validado contra uma forma fechada — não se interpola um
 * nome vindo de fora numa consulta.
 *
 * O primeiro uso real é o consumidor de pagamentos do COM (KAM-055), com
 * `new MaquinaNaBase('orders_mirror')`. O nome da tabela continua a entrar por
 * argumento e não fixo: a `orders` do dia em que isto se escreveu não existe, e
 * amarrar a biblioteca ao nome de hoje era pedir uma edição dela no dia em que
 * um segundo consumidor lesse outra réplica.
 */
const NOME_DE_TABELA = /^[a-z][a-z0-9_]{1,62}$/;

export interface ClienteDeLeitura {
  query(sql: string, parametros?: unknown[]): Promise<{ rows: Array<Record<string, unknown>> }>;
}

export class MaquinaNaBase implements MaquinaDeEstados {
  readonly #tabela: string;
  readonly #colunaId: string;
  readonly #colunaEstado: string;

  /**
   * **Sem cliente**, e a ausência é o desenho. Ver a nota do `estadoDe` da
   * interface: a ligação é a da transacção do consumo e chega por argumento.
   */
  constructor(tabela = 'orders', colunaId = 'id', colunaEstado = 'estado') {
    for (const nome of [tabela, colunaId, colunaEstado]) {
      if (!NOME_DE_TABELA.test(nome)) throw new Error(`nome inválido: ${nome}`);
    }
    this.#tabela = tabela;
    this.#colunaId = colunaId;
    this.#colunaEstado = colunaEstado;
  }

  async estadoDe(
    agregadoTipo: string,
    agregadoId: string,
    bd: ClienteDeLeitura,
  ): Promise<EstadoDaEncomenda | null> {
    if (agregadoTipo !== 'order') return null;
    const { rows } = await bd.query(
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

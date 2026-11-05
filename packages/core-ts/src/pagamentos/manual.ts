/**
 * `ManualProvider`: confirmacao humana auditada, limites e dupla verificacao
 * (KAM-054).
 *
 * E o caminho pelo qual um pagamento feito **fora** da plataforma —
 * transferencia, Multicaixa, numerario — se torna uma encomenda paga, e por
 * isso e o caminho mais atacavel que existe no PAY. O `docs/tecnica/04` §4 nao
 * o desenha como uma conveniencia do Piloto: desenha-o como dez regras
 * (M-1..M-10) que fecham dez portas concretas, e este modulo e a metade de
 * aplicacao delas.
 *
 * ## O que esta aqui e o que esta na revisao `0032`
 *
 * A divisao e a mesma do KAM-053, e pela mesma razao: **uma barreira que
 * dependa de codigo de aplicacao nao e uma barreira**, porque ha sempre um
 * segundo caminho de codigo. Entao:
 *
 *     aqui (TypeScript)     o adaptador do contrato do §3.1 — as cinco funcoes
 *                           obrigatorias, com o tecto por pedido (M-2) e o
 *                           opt-in do `cod` no `createCharge` —, a **tabela**
 *                           pura das regras M-1, M-3, M-4 e M-5, e as cadeias
 *                           SQL que a suite de base de dados le **deste
 *                           ficheiro** em vez de uma copia
 *     revisao `0032`        as quatro tabelas, a RLS, a unicidade de
 *                           idempotencia, e as cinco funcoes de fase, que
 *                           escrevem em `manual_confirmations` e chamam a
 *                           `append_payment_event` na **mesma** transaccao
 *
 * A tabela pura daqui **nao e a barreira**: e o oraculo que a suite de unidade
 * exercita caso a caso (os «Testes Requeridos» do bloco pedem «regras M-1..M-5
 * e M-8 como tabela de casos»). Quem recusa e a base — e as duas tem de
 * concordar, o que o `TestAcordoComATabelaPura` de
 * `db/tests_pagamentos/test_confirmacao_manual.py` mede caso a caso contra um
 * PostgreSQL real, **lendo os casos deste ficheiro** e nao os transcrevendo.
 *
 * ## A imagem de comprovativo nao e lida, e isso e verificado
 *
 * O M-7 escreve «Evidencia ≠ prova»: a imagem do cliente guarda-se como
 * `evidencia_ref` com o rotulo `nao_prova`, e «o agente **nao** le o valor da
 * imagem para decidir». A fraude de comprovativos editados esta CONFIRMADA em
 * Angola, com perdas de 500 000 Kz a milhoes e detencao pela Policia
 * (`evidencia/E2` §4) — isto e, uma imagem nao e uma fonte de verdade sobre
 * dinheiro, e o sistema tem de o dizer **por escrito no proprio registo** e nao
 * so na cabeca de quem o escreveu.
 *
 * O criterio 3 faz disso uma medicao: «nenhum modulo do `ManualProvider` le o
 * conteudo da imagem (*lint* de importacoes de OCR/visao = 0)». A medicao esta
 * no caso «nenhum modulo do adaptador importa OCR ou visao, e ha canario» de
 * `pagamentos.manual.test.ts`, que varre os modulos deste adaptador contra
 * `IMPORTACOES_PROIBIDAS` e tem **passo de canario por fragmento**: cada
 * entrada da lista e plantada nas tres formas (estatica, dinamica, maiusculas)
 * e tem de ser apanhada, e a composicao da lista esta presa a parte. Sem o
 * canario, um zero nao distingue «nao ha» de «nao se procurou» — que e a licao
 * do `codegraph status` no `references/evidencia-e-verificacao.md`.
 *
 * ## As duas direccoes, e porque sao duas
 *
 * Quatro das nove alineas dos Criterios de Aceitacao sao recusas. Uma suite que
 * so medisse recusas fica **verde sobre um caminho que nao funciona de todo** —
 * aconteceu neste repositorio, e e a razao do padrao da «sonda positiva» das
 * suites de base de dados (ver o AC-2 do KAM-041: «controlo positivo, sem o
 * qual o silencio nao prova nada»). Por isso cada recusa deste modulo tem
 * **dois** ensaios: o caminho ilegitimo e recusado, **e** o legitimo passa.
 *
 * ## Os tectos sao todos do tenant, e nenhum e constante
 *
 * O M-10 escreve que os valores sao «propostas, a calibrar no Piloto», e o
 * criterio 1 fecha a porta por onde uma proposta endurece: «o valor e lido do
 * tenant, **nao de constante**». Este modulo nao tem nenhum dos quatro numeros.
 * O que tem e `PROPOSTAS_DE_OMISSAO`, que e uma tabela de **documentacao** —
 * nao se le em decisao nenhuma, e o
 * caso «nenhuma decisao muda se a tabela de propostas for outra» da suite
 * prova-o, e a estrutura prova-o melhor: o `avaliarConfirmacao` le so a
 * `entrada` e o `createCharge` le so o `limites.manualMaxMinor`.
 */

import {
  AuthError,
  type AccountSecrets,
  type ChargeResult,
  type CreateChargeReq,
  type Instant,
  type Metodo,
  type Minor,
  type PaymentProvider,
  type PayoutReq,
  type PayoutResult,
  type ProviderCapabilities,
  ProviderError,
  type ProviderRef,
  type ProviderStatus,
  type RawHttpCallback,
  type RefundReq,
  type RefundResult,
  type Uuid,
  type VerifiedEvent,
} from "./tipos.ts";

/**
 * O `id` do adaptador, e **tem** de ser este.
 *
 * O `ADAPTADORES_DE_CONFIRMACAO_HUMANA` do `registo.ts` ja tem `"manual"`
 * escrito (KAM-052), e o `_coerencia` recusa um adaptador que declare
 * `humanOnly` sem estar nessa lista — a etiqueta nao se atribui. Um `id`
 * diferente nao arrancava.
 */
export const PROVIDER_MANUAL = "manual";

/**
 * As capacidades do §3.2, linha `manual`: «n/a» nas tres colunas automaticas.
 *
 * O `humanOnly: true` e a **unica** dispensa da `ADAPTER_CANNOT_CONFIRM`, e o
 * `_coerencia` do `registo.ts` exige coerencia: um `humanOnly` que declarasse
 * `callbackAuth: 'hmac'`, `statusQuery` ou `reconciliationQueue` estava a usar
 * a dispensa para nao ser medido pela regra que ja cumpria. As tres ficam
 * fechadas, e e por isso que o `status()` e o `verifyCallback` deste adaptador
 * recusam em vez de responder.
 *
 * O `amountFormat` e `inteiro_kz` e nao `decimal2`: nao ha API nenhuma do outro
 * lado. O que ha e uma instrucao de pagamento em texto para uma pessoa ler, e a
 * forma como se escreve um montante para uma pessoa em Angola e em kwanzas
 * inteiros (`dinheiro.ts`).
 *
 * O `refMaxLen` e `0`: este adaptador **nao emite referencia**. A `0029` trata
 * a cobranca sem referencia pela via que o §6.2 escreve
 * (`numero_publico#tentativa`), e declarar um comprimento era prometer uma
 * coluna que nao se preenche.
 */
export const CAPACIDADES_DO_MANUAL: ProviderCapabilities = {
  metodos: ["manual", "cod"],
  callbackAuth: "none",
  statusQuery: false,
  reconciliationQueue: false,
  refund: false,
  payout: false,
  // O §4.1 da ao dono uma conversa, nao um instante: o `min` e uma hora e o
  // `max` as 72 h da reserva (`docs/tecnica/03` §6.4). O `cod` tem «validade
  // curta» (§4.2, nota do COD) e isso e do KAM-096, que calibra os quatro
  // tectos — aqui nao se distingue por metodo.
  chargeTtl: { min: 3_600, max: 259_200 },
  // O `createCharge` e idempotente pelo `chargeId`, que e gerado por nos antes
  // da chamada (§3.1). Nao ha janela de facilitador nenhuma para respeitar.
  idempotencyWindow: 0,
  amountFormat: "inteiro_kz",
  refMaxLen: 0,
  settlement:
    "O cliente paga fora da plataforma (transferencia, Multicaixa, numerario) " +
    "directamente na conta da PME; a plataforma nunca detem os fundos " +
    "(ADR-004, docs/tecnica/04 secao 10.1).",
  humanOnly: true,
  pspLicenciado: false,
};

/** O rotulo obrigatorio de `manual_confirmations.evidencia_ref` (M-7). */
export const ROTULO_NAO_PROVA = "nao_prova";

/** As cinco fases de `manual_confirmations.fase` (§6.3). */
export const FASES = [
  "declaracao_cliente",
  "confirmacao",
  "segunda_aprovacao",
  "rejeicao",
  "reversao",
] as const;

export type Fase = (typeof FASES)[number];

/** Os dois papeis de `payment_confirmers.papel` (§6.2). */
export const PAPEIS_DE_CONFIRMADOR = ["dono", "funcionario"] as const;

export type PapelDeConfirmador = (typeof PAPEIS_DE_CONFIRMADOR)[number];

/**
 * A janela de omissao do F-18, em horas.
 *
 * E uma constante e nao um entitlement, e a diferenca face aos quatro tectos e
 * real: os tectos sao **dinheiro** e variam por PME e por plano; esta e uma
 * janela de **tempo** que o §7.2 F-18 fixa para a plataforma inteira («sem
 * resposta do dono em 24 h»). Se vier a variar por tenant, entra no registo de
 * entitlements como os outros — e isso e o KAM-096.
 */
export const JANELA_DE_SILENCIO_HORAS = 24;

/** A accao de `fraud_signals` que o criterio 6 exige (§6.3). */
export const ACCAO_DE_RETENCAO = "reter_confirmacao";

/** As duas regras de `fraud_signals.regra` que este adaptador escreve. */
export const REGRA_DIARIA = "manual_limite_diario";
export const REGRA_POR_CONTACTO = "manual_limite_por_contacto_24h";

/**
 * `manual_confirmations_total{fase}`, a metrica do DoD (`docs/tecnica/08` §4.6).
 *
 * A etiqueta e a **fase** e nao o veredicto, e a escolha e a do §4.6: «contagem
 * de confirmacoes manuais por semana e alerta de desvio». O que uma serie por
 * fase da, e um contador so nao dava, e a forma do funil — quantas declaracoes
 * chegam a `confirmacao`, quantas a `segunda_aprovacao`, e quantas acabam em
 * `rejeicao` ou `reversao`. Um tenant em que a razao entre `declaracao_cliente`
 * e `rejeicao` muda de semana para semana e o sinal que o alerta procura.
 *
 * **Emitida por quem escreve as fases**, como o `payment_events_total` do
 * `hooks.ts`: as funcoes de fase vivem na revisao `0032` e a emissao e I/O, que
 * este pacote nao faz. O servico que a emite e o `pay`, que **nao existe** nesta
 * arvore — e isso diz-se aqui e na secao de verificacao do bloco em vez de se
 * marcar a caixa.
 */
export const METRICA_CONFIRMACOES = "manual_confirmations_total";

/**
 * O alerta de desvio semanal do §4.6.
 *
 * E por `(tenant, fase)` e por **semana**, e nao por confirmacao: o que ele
 * procura nao e uma confirmacao suspeita — isso e o `fraud_signals` do M-3, que
 * corre por pedido — mas uma mudanca de padrao numa PME. O limiar e *proposta* e
 * calibra-se no KAM-096, com os dados do Piloto; escrever um numero aqui era o
 * endurecimento silencioso que o `PROPOSTAS_DE_OMISSAO` existe para evitar.
 */
export const ALERTA_DESVIO_SEMANAL = "manual_confirmacoes_desvio_semanal";

/** As etiquetas da `METRICA_CONFIRMACOES`: uma serie por fase (§6.3). */
export const ETIQUETAS_DA_METRICA = FASES;

/**
 * As quatro chaves de `entitlements.limites` do M-10.
 *
 * Os nomes vem do `registry/entitlement_keys.schema.json` e do
 * `CHAVES_DE_LIMITE` do `ten`: duas sao `tecto_por_pedido` e leem-se pelo
 * `checkCeiling`, e duas sao `tecto_por_janela` e **nao tem caminho de
 * aplicacao no KAM-009** — o `exigirTecto` levanta de proposito, porque o
 * agregado da janela vive em `manual_confirmations`, que e tabela deste
 * ticket. O caminho delas e o `SQL_MANUAL_JANELA`, aqui em baixo.
 */
export const CHAVE_MAX = "manual_max_minor";
export const CHAVE_DUPLA = "manual_dupla_acima_minor";
export const CHAVE_DIARIA = "manual_daily_max_minor";
export const CHAVE_POR_CONTACTO = "manual_max_por_contacto_24h";

/**
 * Os valores **propostos** do §4.2 M-2, M-5 e M-10 — documentacao, nao decisao.
 *
 * Estao aqui para que quem provisiona um tenant (KAM-091) saiba com que numeros
 * o desenho foi pensado, e para que a calibracao do KAM-096 tenha um ponto de
 * partida escrito. **Nenhuma funcao deste modulo os le**, e isso nao e uma
 * promessa: nenhuma funcao referencia esta tabela fora dela propria e de duas
 * mensagens de erro.
 *
 * O endurecimento silencioso — «um numero que eu propus numa conversa aparece,
 * tres documentos depois, como requisito com ar de medicao» — e o defeito que
 * esta separacao fecha. Os dois `null` dizem o que ainda nao tem proposta
 * nenhuma: o §4.2 M-3 nomeia as duas chaves e **nao da valor a nenhuma**, e
 * inventar um aqui era exactamente o defeito.
 *
 * **A prova de que a tabela nao entra em decisao nenhuma e estrutural**, e
 * esta no caso «nenhuma decisao muda se a tabela de propostas for outra» da
 * suite: as quatro chaves aparecem so nesta tabela e em duas mensagens de
 * erro, o `avaliarConfirmacao` le so a `entrada`, e o `createCharge` le so o
 * `limites.manualMaxMinor`. A primeira versao deste comentario nomeava um
 * ensaio — `test_as_propostas_nao_entram_em_decisao_nenhuma` — que **nao
 * existia**: apanhado pela revisao adversarial, e e a mesma classe de defeito
 * que uma caixa marcada com evidencia que nao a sustenta.
 */
export const PROPOSTAS_DE_OMISSAO: Readonly<Record<string, Minor | null>> = {
  [CHAVE_MAX]: 5_000_000n,
  [CHAVE_DUPLA]: 2_000_000n,
  [CHAVE_DIARIA]: null,
  [CHAVE_POR_CONTACTO]: null,
};

/** Porque e que uma confirmacao nao produziu `pagamento_confirmado`. */
export type MotivoManual =
  /** M-1: o cliente nunca confirma o seu proprio pagamento (criterio 2). */
  | "cliente_nao_confirma"
  /**
   * M-1: nao se sabe quem e o cliente, logo a guarda nao pode correr.
   *
   * Falha fechado, e e o mesmo que a base faz: sem fase `declaracao_cliente`
   * a `manual_confirmar` levanta. Uma guarda que se salta por falta de dado
   * e pior do que uma guarda que recusa.
   */
  | "sem_cliente"
  /** M-1: o BSUID nao esta em `payment_confirmers` — ou esta inactivo. */
  | "sem_confirmador"
  /** M-1: esta na tabela, mas sem `pode_segunda_aprovacao` na segunda volta. */
  | "sem_segunda_aprovacao"
  /** M-5: a segunda aprovacao e do mesmo contacto que a primeira. */
  | "mesmo_confirmador"
  /** M-4: o desafio do valor nao bate. Sem tolerancia. */
  | "valor_nao_bate"
  /** M-3: a soma do dia excede `manual_daily_max_minor`. */
  | "limite_diario"
  /** M-3: a contagem do contacto nas 24 h excede o tecto. */
  | "limite_por_contacto"
  /** M-2: sem tecto declarado nao ha tecto — nega (fail closed). */
  | "sem_tecto"
  /** F-18: o dono nao respondeu dentro da janela. */
  | "silencio_do_dono";

/** Que regra do §4.2 decidiu. */
export type RegraManual = "M-1" | "M-2" | "M-3" | "M-4" | "M-5";

/** Uma linha de `payment_confirmers`, como a base a devolve (§6.2). */
export type ConfirmadorConhecido = {
  readonly contactId: Uuid;
  readonly papel: PapelDeConfirmador;
  readonly podeSegundaAprovacao: boolean;
  readonly ativo: boolean;
};

/** O agregado da janela, lido de `manual_confirmations` (M-3). */
export type JanelaDoManual = {
  /** A soma confirmada do dia, em unidade menor. */
  readonly somaDoDiaMinor: Minor;
  /** O tecto diario do tenant. `null` quando nenhum modulo activo o declara. */
  readonly tectoDiarioMinor: Minor | null;
  /** Quantas confirmacoes este contacto teve nas ultimas 24 h. */
  readonly confirmacoesDoContacto: number;
  /** O tecto de contagem do tenant. `null` quando ninguem o declara. */
  readonly tectoDoContacto: number | null;
};

/**
 * O que a base sabe quando chega uma mensagem de confirmacao.
 *
 * **O `actorContactId` vem do BSUID do canal do tenant (CHR) e nunca do texto**
 * (M-1, e os «Detalhes Tecnicos» do bloco escrevem-no por extenso). Um campo
 * chamado «quem diz ser» nao existe neste tipo, de proposito: nao ha por onde
 * uma mensagem a dizer «sou o dono» entrar.
 */
export type EntradaDaConfirmacao = {
  /** `payment_charges.amount_minor`, lido da cobranca e nao do pedido. */
  readonly amount: Minor;
  /** O valor que o dono escreveu, visto na app do banco dele (M-4). */
  readonly valorDeclarado: Minor;
  /** O BSUID resolvido do canal, em `contact_id`. */
  readonly actorContactId: Uuid;
  /** O contacto do cliente da encomenda, quando se conhece. */
  readonly clienteContactId: Uuid | null;
  /** A linha de `payment_confirmers`, ou `null` quando nao ha nenhuma. */
  readonly confirmador: ConfirmadorConhecido | null;
  /** `manual_dupla_acima_minor` do tenant. `null` nega a dupla por falta. */
  readonly tectoDaDuplaMinor: Minor | null;
  readonly janela: JanelaDoManual;
  /**
   * Quem deu a **primeira** aprovacao, quando esta e a segunda volta.
   *
   * `null` na primeira. Com valor, o veredicto exige que o actor seja **outro**
   * contacto e que tenha `pode_segunda_aprovacao` (criterio 5).
   */
  readonly primeiraAprovacaoDe: Uuid | null;
};

/** O que fazer com uma confirmacao. */
export type DecisaoDoManual =
  /** Escreve `pagamento_confirmado` e a cobranca fica `paga`. */
  | "confirma"
  /** Fica em `pendente_confirmacao` a espera de outro confirmador (M-5). */
  | "exige_segunda"
  /** Retem para ops, com `fraud_signals.accao='reter_confirmacao'` (M-3). */
  | "retem"
  /** Escreve `confirmacao_manual_rejeitada`; a cobranca volta a `emitida`. */
  | "rejeita";

export type VeredictoDoManual = {
  readonly decisao: DecisaoDoManual;
  readonly motivo: MotivoManual | null;
  readonly regra: RegraManual | null;
  /** O M-4, isolado: e a coluna `manual_confirmations.valor_bate`. */
  readonly valorBate: boolean;
  /** A fase que se escreve em `manual_confirmations`. */
  readonly fase: Fase;
  /** A regra de `fraud_signals`, quando a decisao e `retem`. Senao `null`. */
  readonly sinal: string | null;
};

/**
 * A tabela das regras M-1, M-3, M-4 e M-5, pura (§4.2).
 *
 * ## A ordem das portas nao e arbitraria
 *
 * Cada porta fechada antes da seguinte decide o que um atacante aprende:
 *
 *     1  o cliente        M-1, e vem **primeiro**. Nem a tabela de
 *                         confirmadores se consulta: se o contacto do cliente
 *                         estivesse (por erro de provisionamento) em
 *                         `payment_confirmers`, a ordem inversa deixava-o
 *                         confirmar o proprio pagamento — que e a fraude mais
 *                         obvia deste caminho e a mais facil de deixar aberta
 *     2  o confirmador    M-1. Um BSUID que nao esta na tabela, ou esta
 *                         `ativo = false`, nao tem efeito nenhum
 *     3  o desafio        M-4, **antes** dos limites: o valor errado e uma
 *                         rejeicao e nao uma retencao, e um atacante que
 *                         recebesse «retido para analise» em vez de «o valor
 *                         nao bate» aprendia que acertou no valor
 *     4  os limites       M-3. Vem **antes** do M-5 porque reter e mais forte
 *                         do que pedir segunda assinatura: uma cobranca que
 *                         excede o tecto diario **e** o limiar da dupla nao se
 *                         resolve com uma segunda assinatura, resolve-se com
 *                         uma pessoa de ops a olhar para ela
 *     5  a dupla          M-5, e por ultimo. Tudo o que sobra ate aqui e
 *                         legitimo; o que falta decidir e se **uma** assinatura
 *                         chega
 *
 * `IMMUTABLE` no sentido que importa: nao le relogio, nao le ambiente, nao le
 * `PROPOSTAS_DE_OMISSAO`. Tudo o que decide vem da `entrada`.
 */
export function avaliarConfirmacao(entrada: EntradaDaConfirmacao): VeredictoDoManual {
  const valorBate = entrada.valorDeclarado === entrada.amount;

  // (1) O cliente nunca confirma, e esta porta fecha-se antes de todas.
  //
  // **Um `clienteContactId` nulo recusa, e nao salta a porta.** A primeira
  // versao tinha a conjuncao ao contrario — `clienteContactId !== null && …` —,
  // pelo que com `null` a guarda **nao corria** e a avaliacao seguia para as
  // outras portas, podendo devolver `confirma`. A revisao adversarial mediu a
  // divergencia: do lado da base, uma cobranca sem fase `declaracao_cliente`
  // levanta, porque sem ela nao se sabe quem e o cliente e a guarda mais
  // importante deste caminho nao pode correr. Os dois lados passam a falhar
  // fechado.
  if (entrada.clienteContactId === null) {
    return _rejeita("sem_cliente", "M-1", valorBate);
  }
  if (entrada.actorContactId === entrada.clienteContactId) {
    return _rejeita("cliente_nao_confirma", "M-1", valorBate);
  }

  // (2) Quem confirma esta na tabela e esta activo — e mais nada. Uma mensagem
  // a dizer «sou o dono» chega aqui como um `contactId` que nao esta la.
  const confirmador = entrada.confirmador;
  if (confirmador === null || !confirmador.ativo) {
    return _rejeita("sem_confirmador", "M-1", valorBate);
  }

  // (2b) Na segunda volta, o M-5 exige **outro** contacto com a marca.
  if (entrada.primeiraAprovacaoDe !== null) {
    if (entrada.primeiraAprovacaoDe === entrada.actorContactId) {
      return _rejeita("mesmo_confirmador", "M-5", valorBate);
    }
    if (!confirmador.podeSegundaAprovacao) {
      return _rejeita("sem_segunda_aprovacao", "M-1", valorBate);
    }
  }

  // (3) O desafio do valor. **Sem tolerancia**: `amount_minor − 1` rejeita.
  if (!valorBate) {
    return _rejeita("valor_nao_bate", "M-4", false);
  }

  // (4) Os limites da janela. `null` nega, pela regra do `checkCeiling`: «sem
  // tecto» nao quer dizer «sem limite» (criterio 2 do KAM-009).
  const janela = entrada.janela;
  if (
    janela.tectoDiarioMinor === null ||
    janela.somaDoDiaMinor + entrada.amount > janela.tectoDiarioMinor
  ) {
    return {
      decisao: "retem",
      motivo: "limite_diario",
      regra: "M-3",
      valorBate: true,
      fase: "confirmacao",
      sinal: REGRA_DIARIA,
    };
  }
  if (
    janela.tectoDoContacto === null ||
    janela.confirmacoesDoContacto + 1 > janela.tectoDoContacto
  ) {
    return {
      decisao: "retem",
      motivo: "limite_por_contacto",
      regra: "M-3",
      valorBate: true,
      fase: "confirmacao",
      sinal: REGRA_POR_CONTACTO,
    };
  }

  // (5) A dupla verificacao acima do limiar. `null` exige a dupla, pela mesma
  // leitura fechada: sem limiar declarado nao se sabe que uma assinatura basta.
  const precisaDeDupla =
    entrada.tectoDaDuplaMinor === null || entrada.amount > entrada.tectoDaDuplaMinor;
  if (precisaDeDupla && entrada.primeiraAprovacaoDe === null) {
    return {
      decisao: "exige_segunda",
      motivo: null,
      regra: "M-5",
      valorBate: true,
      fase: "confirmacao",
      sinal: null,
    };
  }

  return {
    decisao: "confirma",
    motivo: null,
    regra: null,
    valorBate: true,
    fase: entrada.primeiraAprovacaoDe === null ? "confirmacao" : "segunda_aprovacao",
    sinal: null,
  };
}

function _rejeita(
  motivo: MotivoManual,
  regra: RegraManual,
  valorBate: boolean,
): VeredictoDoManual {
  return { decisao: "rejeita", motivo, regra, valorBate, fase: "rejeicao", sinal: null };
}

/**
 * O que o dono tem de responder, e o que o cliente le (M-9).
 *
 * Sao *templates* parametrizados com o aviso fixo, e vivem aqui para que o
 * aviso nao se possa esquecer num sitio: o §4.1 escreve que o cliente «e
 * informado de que a confirmacao e feita pela loja», e o criterio 3 que a
 * imagem nao prova nada. O `{...}` e o parametro; o envio e da porta
 * `OwnerNotifier`, abaixo.
 *
 * **Sem telefone e sem texto de mensagem do cliente**, que e a caixa de
 * privacidade do DoD: o contacto identifica-se por `contact_id` e o pedido pelo
 * `numero_publico`.
 */
export const AVISOS = {
  aoCliente:
    "O pagamento do pedido {numero_publico} e confirmado pela loja, nao pela " +
    "KAMBA. Um comprovativo enviado por mensagem nao confirma pagamento.",
  aoDono:
    "O cliente declara ter pago o pedido {numero_publico}. Confirme na SUA " +
    "app do banco antes de responder: uma imagem de comprovativo nao e prova.",
  desafio: "Escreva o valor que viu na sua app do banco, em kwanzas.",
  segunda:
    "O pedido {numero_publico} precisa de uma segunda aprovacao de outro " +
    "confirmador da loja.",
  retido:
    "O pedido {numero_publico} ficou retido para verificacao da KAMBA. " +
    "Nenhuma accao e necessaria da sua parte.",
} as const;

/**
 * A porta de saida para o dono (os «Detalhes Tecnicos» do bloco).
 *
 * E uma porta e nao uma chamada ao outbound porque este pacote nao faz IO
 * (`index.ts`), e porque os «Testes Requeridos» pedem um
 * `FakeOwnerNotifier` — um duplo so e possivel se houver interface.
 */
export type OwnerNotifier = {
  /** `contactId` e `contact_id`, nunca um telefone (ADR-010). */
  avisar(contactId: Uuid, mensagem: string): Promise<void>;
};

/** Os limites por pedido que o `createCharge` precisa de ler do tenant. */
export type LimitesDoManual = {
  /**
   * `manual_max_minor` do tenant. **`null` recusa**, e nao «sem limite».
   *
   * E a mesma leitura do `checkCeiling`: a `ten_tecto` devolve `NULL` quando
   * nenhum modulo activo declara a chave, e ler isso como «pode tudo» era abrir
   * o tecto de dinheiro a um tenant sem entitlement.
   */
  readonly manualMaxMinor: Minor | null;
  /** O opt-in do `cod` do §4.2. **Desligado por omissao** (criterio 9). */
  readonly codActivado: boolean;
};

/** De onde vem `entitlements.limites`. Uma porta, pela razao do `OwnerNotifier`. */
export type LeitorDeLimites = {
  limitesDoManual(tenantId: Uuid): Promise<LimitesDoManual>;
};

/** De onde vem o texto de `payment_accounts.manual_instrucoes`. */
export type LeitorDeInstrucoes = {
  instrucoesDaConta(accountId: Uuid): Promise<string>;
};

export type OpcoesDoManual = {
  readonly limites: LeitorDeLimites;
  readonly instrucoes: LeitorDeInstrucoes;
};

/**
 * O adaptador do §3.1 para o caminho do §4.
 *
 * Das oito funcoes do contrato implementa as **cinco obrigatorias** e nenhuma
 * opcional: as tres opcionais sao capacidades que a matriz do §3.2 escreve
 * «n/a» para este adaptador, e o `suporta` do `registo.ts` recusa chamar uma
 * capacidade nao declarada em vez de descobrir o `undefined` em execucao.
 *
 * ## O `createCharge` e onde o M-2 morde, e morde **duas** vezes
 *
 * A primeira e aqui: acima de `manual_max_minor` devolve `REJECTED` e a
 * encomenda nao avanca (criterio 1). A segunda e na base — o *trigger* `KA007`
 * da revisao `0030` (KAM-044) recusa pôr uma encomenda em
 * `pendente_confirmacao` com `total_minor` acima do tecto manual do tenant, e
 * recusa-a tambem quando nao ha entitlement que declare a chave. As duas leem
 * **a mesma** funcao `platform.ten_tecto`, e nao duas copias da regra.
 *
 * Duas barreiras para a mesma regra nao e redundancia: a de aplicacao da uma
 * mensagem util ao agente que tem de propor outro meio de pagamento, e a da
 * base e a que vale quando alguem escrever um segundo caminho de codigo.
 */
export class ManualProvider implements PaymentProvider {
  readonly id = PROVIDER_MANUAL;
  readonly capabilities = CAPACIDADES_DO_MANUAL;

  readonly #limites: LeitorDeLimites;
  readonly #instrucoes: LeitorDeInstrucoes;

  constructor(opcoes: OpcoesDoManual) {
    this.#limites = opcoes.limites;
    this.#instrucoes = opcoes.instrucoes;
  }

  /**
   * Cria a cobranca, ou recusa-a — e a recusa e um `REJECTED` tipado.
   *
   * **No limite exacto aceita.** `amount <= tecto` e a mesma comparacao do
   * `checkCeiling` (`valor <= tecto`), e a fronteira e um caso de teste e nao
   * uma nota: `tecto` passa, `tecto + 1` nao.
   */
  async createCharge(req: CreateChargeReq): Promise<ChargeResult> {
    if (!this.capabilities.metodos.includes(req.metodo)) {
      throw new ProviderError(
        "NOT_SUPPORTED",
        `o ManualProvider cobre 'manual' e 'cod' e nao '${req.metodo}'`,
      );
    }
    if (req.currency !== "AOA") {
      throw new ProviderError("VALIDATION", `moeda '${req.currency}': so AOA`);
    }
    if (req.amount <= 0n) {
      throw new ProviderError("VALIDATION", "o montante tem de ser positivo");
    }

    const limites = await this.#limites.limitesDoManual(req.tenantId);

    // Criterio 9: `cod` com opt-in desligado devolve `REJECTED`. **Antes** da
    // leitura do tecto, porque um `cod` desligado nao e uma questao de valor:
    // o §4.2 escreve que o COD «nao existe evento autenticado» e so entra com
    // opt-in do tenant.
    if (req.metodo === "cod" && !limites.codActivado) {
      throw new ProviderError(
        "REJECTED",
        "metodo 'cod' sem opt-in do tenant: o pagamento na entrega nao tem " +
          "evento autenticado (docs/tecnica/04 secao 4.2) e exige opt-in " +
          "explicito, desligado por omissao",
      );
    }

    const tecto = limites.manualMaxMinor;
    if (tecto === null) {
      throw new ProviderError(
        "REJECTED",
        `sem '${CHAVE_MAX}' declarado para o tenant: «sem tecto» nao quer ` +
          "dizer «sem limite» (criterio 2 do KAM-009). Provisiona-se o " +
          "entitlement (KAM-091) antes de se cobrar por este caminho",
      );
    }
    if (req.amount > tecto) {
      throw new ProviderError(
        "REJECTED",
        `montante ${req.amount} acima de '${CHAVE_MAX}' (${tecto}) do tenant: ` +
          "o ManualProvider recusa criar a cobranca e o agente propoe outro " +
          "meio ou espera pelo facilitador (docs/tecnica/04 secao 4.2 M-2)",
      );
    }

    return {
      kind: "manual",
      instrucoes: await this.#instrucoes.instrucoesDaConta(req.accountId),
    };
  }

  /**
   * `NOT_SUPPORTED`, e e a coerencia do `humanOnly`.
   *
   * O `statusQuery: false` diz que nao ha consulta autenticada; devolver um
   * estado aqui era contradizer a capacidade com que o adaptador se declarou, e
   * o `_coerencia` recusa um `humanOnly` que declare `statusQuery`. Quem sabe o
   * estado desta cobranca e a `payment_charges`, que e projeccao do ledger.
   */
  async status(ref: ProviderRef): Promise<ProviderStatus> {
    throw new ProviderError(
      "NOT_SUPPORTED",
      `o ManualProvider nao tem consulta de estado (statusQuery=false); a ` +
        `cobranca ${ref.providerChargeId ?? ref.providerId} le-se em ` +
        "platform.payment_charges, que e projeccao do ledger",
    );
  }

  /** G-2 do §10.4: a plataforma nao reembolsa. O caminho e `refund_cases`. */
  async refund(_req: RefundReq): Promise<RefundResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  /** G-2 do §10.4: a plataforma nao executa payouts (ADR-004). */
  async payout(_req: PayoutReq): Promise<PayoutResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  /**
   * **Levanta sempre `AuthError`**, e e isso que faz deste adaptador um
   * cidadao do contrato em vez de uma excepcao a ele.
   *
   * O `tipos.ts` escreve a razao por extenso: «o `ManualProvider` nao tem HMAC,
   * mas tem de ter forma de dizer que um callback **nao se autentica por
   * aqui**». Um `verifyCallback` que devolvesse `[]` era pior do que nao
   * existir: o §5.1 trata a lista vazia como «nada a processar» e marcaria o
   * recibo `processado`, isto e, um corpo forjado entrava pelo inbox e saia com
   * um 200 e sem rasto de recusa. Com o `AuthError`, o `atenderCallback` do
   * `hooks.ts` grava `hmac_invalido` e devolve 401 — que e o que o G1 manda
   * fazer a uma origem que nao se autentica.
   */
  async verifyCallback(
    _raw: RawHttpCallback,
    acct: AccountSecrets,
  ): Promise<readonly VerifiedEvent[]> {
    throw new AuthError(
      `a conta ${acct.accountId} e do ManualProvider (callbackAuth='none'): ` +
        "nao ha assinatura para verificar e um callback nao confirma nada " +
        "por este adaptador. A via de confirmacao e humana e auditada " +
        "(docs/tecnica/04 secao 4, M-1..M-6)",
    );
  }
}

// --------------------------------------------------------------------- SQL

/**
 * A declaracao do cliente (criterio 3): **so** registo, nunca confirmacao.
 *
 * Escreve `manual_confirmations.fase='declaracao_cliente'` com a
 * `evidencia_ref` rotulada `nao_prova`, e poe a cobranca em
 * `pendente_confirmacao` pelo `confirmacao_manual_pedida`. Nao ha por onde esta
 * cadeia confirmar um pagamento: o §7.1 nao tem aresta de
 * `pendente_confirmacao` para `paga` por este tipo de evento, e a
 * `confirmar_exige_autenticacao` nunca e avaliada porque nao se escreve
 * `pagamento_confirmado` nenhum.
 */
export const SQL_MANUAL_DECLARAR = `
  SELECT confirmacao_id, event_id, estado_novo, repetida
    FROM platform.manual_declarar(
      p_charge_id => $1, p_actor_contact_id => $2, p_canal_msg_id => $3,
      p_evidencia_ref => $4)
`;

/**
 * O acto humano: M-1, M-3, M-4 e M-5 numa transaccao (criterios 2, 4, 5 e 6).
 *
 * A funcao e que decide — nao recebe decisao nenhuma. O `avaliarConfirmacao`
 * deste modulo e o oraculo da suite de unidade e a mensagem que o agente mostra
 * ao dono; a recusa que vale e esta.
 */
export const SQL_MANUAL_CONFIRMAR = `
  SELECT confirmacao_id, event_id, estado_novo, decisao, motivo, valor_bate,
         sinal_id, repetida
    FROM platform.manual_confirmar(
      p_charge_id => $1, p_actor_contact_id => $2, p_canal_msg_id => $3,
      p_valor_declarado_minor => $4)
`;

/** O silencio de 24 h do F-18 (criterio 7). */
export const SQL_MANUAL_EXPIRAR_CONFIRMACAO = `
  SELECT confirmacao_id, event_id, estado_novo
    FROM platform.manual_expirar_confirmacao(
      p_charge_id => $1, p_janela_horas => $2)
`;

/** A reversao auditada do M-8 (criterio 8): nada se apaga. */
export const SQL_MANUAL_REVERTER = `
  SELECT confirmacao_id, event_id, estado_novo, refund_case_id
    FROM platform.manual_reverter(
      p_charge_id => $1, p_actor_contact_id => $2, p_canal_msg_id => $3,
      p_motivo => $4)
`;

/**
 * O agregado da janela do M-3, que o `ten` **nao** sabe calcular.
 *
 * O `exigirTecto` do KAM-009 levanta para as duas chaves de janela e diz
 * porque: a `platform.tenant_usage` tem chave `(tenant_id, chave_limite,
 * periodo)` com periodo mensal por `CHECK`, «sem dimensao de contacto e sem
 * janela movel». O agregado vem desta leitura, sobre `manual_confirmations`,
 * que e tabela deste ticket — e os tectos continuam a vir da `ten_tecto`, que e
 * a mesma funcao que o `checkCeiling` chama.
 */
export const SQL_MANUAL_JANELA = `
  SELECT soma_do_dia_minor, tecto_diario_minor,
         confirmacoes_do_contacto, tecto_do_contacto
    FROM platform.manual_janela(
      p_tenant_id => $1, p_contact_id => $2, p_agora => $3)
`;

/** A linha de `payment_confirmers` do actor, ou zero linhas (M-1). */
export const SQL_MANUAL_CONFIRMADOR = `
  SELECT contact_id, papel, pode_segunda_aprovacao, ativo
    FROM platform.payment_confirmers
   WHERE tenant_id = $1 AND contact_id = $2
`;

/**
 * As cadeias que a suite de base de dados exercita **deste ficheiro**.
 *
 * E o padrao do `hooks.ts` e do `services/com/src/produtos/consultas.ts`: a
 * suite importa o modulo e corre o texto que ele envia, em vez de uma copia
 * que envelhece sozinha.
 */
export const CADEIAS_DO_MANUAL = [
  "SQL_MANUAL_DECLARAR",
  "SQL_MANUAL_CONFIRMAR",
  "SQL_MANUAL_EXPIRAR_CONFIRMACAO",
  "SQL_MANUAL_REVERTER",
  "SQL_MANUAL_JANELA",
  "SQL_MANUAL_CONFIRMADOR",
] as const;

/**
 * As importacoes que nenhum modulo deste adaptador pode ter (criterio 3).
 *
 * Nao e uma lista de pacotes que existem na arvore: e a **classe** de
 * dependencia que tornaria a imagem uma fonte de decisao. A varredura procura
 * qualquer especificador de importacao que contenha um destes fragmentos, e tem
 * passo de canario — ver o cabecalho.
 */
export const IMPORTACOES_PROIBIDAS = [
  "ocr",
  "tesseract",
  "vision",
  "visao",
  "image-recognition",
  "imagemagick",
  "sharp",
  "jimp",
  "opencv",
  "textract",
  "rekognition",
  "gemini",
  "openai",
  "anthropic",
] as const;

/**
 * Os modulos que o criterio 3 nomeia como «do `ManualProvider`».
 *
 * Tres e nao um: a regra e sobre o adaptador e nao sobre um ficheiro, e a forma
 * de a contornar sem a quebrar era pôr o leitor de imagem no modulo ao lado e
 * importar dele.
 *
 * **A justificacao estava errada e fica corrigida.** Ela dizia que o
 * `dinheiro.ts` e o `tipos.ts` entram «porque este modulo os importa», e o
 * bloco de `import` deste ficheiro tem **uma** fonte: o `./tipos.ts`. A
 * varredura e, portanto, mais larga do que a razao que a justificava — o que e
 * inofensivo em si, mas se alguem verificasse a razao e «corrigisse» a lista, a
 * varredura ficava mais estreita. A razao certa e outra: os tres sao os modulos
 * que o adaptador **pode** vir a importar sem que a regra mude de sitio, e o
 * `dinheiro.ts` e o unico candidato natural a tocar num montante lido de uma
 * imagem. Apanhado pela revisao adversarial.
 */
export const MODULOS_DO_MANUAL = [
  "manual.ts",
  "tipos.ts",
  "dinheiro.ts",
] as const;

// **A `janelaDeSilencioSegundos` foi retirada, e nao substituida.**
//
// Ela devolvia segundos e dizia, no proprio comentario, que era «para quem
// precisa de a passar ao SQL» — e a unica cadeia SQL que recebe uma janela
// passa-a a `p_janela_horas`, que e um `integer` em **horas**. Quem seguisse o
// comentario mandava 86 400 e a janela do F-18 passava de 24 h a cerca de dez
// anos: a `manual_expirar_confirmacao` devolvia zero linhas para sempre e
// nenhuma omissao do dono expirava, sem erro, sem registo e sem nada.
//
// Nao tinha chamador nem ensaio (medido por varredura da arvore), pelo que sai
// em vez de se corrigir: o que se passa ao SQL e o `JANELA_DE_SILENCIO_HORAS`,
// que ja esta exportado e e o que o nome diz. Apanhado pela revisao
// adversarial.

/**
 * O `evidencia_ref` com o rotulo obrigatorio do M-7, numa forma so.
 *
 * **Apara, e recusa rotular o que ja esta rotulado.** A primeira versao
 * validava com `trim()` e concatenava o **original**, pelo que `' sto://a'`
 * dava `'nao_prova: sto://a'` e `'nao_prova:x'` dava
 * `'nao_prova:nao_prova:x'` — as duas passam o `CHECK` da base
 * (`LIKE 'nao_prova:%'`) e o `rotuloDaEvidencia` le-as como rotuladas, pelo que
 * o que ficava corrompido era a **referencia**, numa tabela que nao tem
 * `UPDATE` para papel nenhum. Apanhado pela revisao adversarial.
 */
export function evidenciaNaoProva(referenciaDoAnexo: string): string {
  const limpa = referenciaDoAnexo.trim();
  if (limpa === "") {
    throw new ProviderError("VALIDATION", "a referencia do anexo nao pode ser vazia");
  }
  if (limpa.startsWith(`${ROTULO_NAO_PROVA}:`)) {
    throw new ProviderError(
      "VALIDATION",
      `a referencia '${limpa}' ja esta rotulada: rotula-la outra vez dava ` +
        "`nao_prova:nao_prova:...`, que a base aceita e ninguem consegue resolver",
    );
  }
  return `${ROTULO_NAO_PROVA}:${limpa}`;
}

/**
 * Le o rotulo de um `evidencia_ref`. `null` quando nao tem o rotulo conhecido.
 *
 * **Nao e «o que vem antes do primeiro dois-pontos», e a diferenca foi medida.**
 * A primeira versao fazia isso, e `sto://a/b.jpg` — que e a forma de uma
 * referencia do STO — devolvia `"sto"`: uma referencia **sem** rotulo passava
 * por rotulada, com um rotulo inventado pela pontuacao do URL. Num campo cuja
 * unica funcao e dizer «isto nao e prova», ler um rotulo onde nao ha e o pior
 * resultado possivel.
 *
 * Le-se, portanto, contra o **unico** rotulo que existe, e com a mesma forma
 * que o `CHECK` da revisao `0032` impoe (`LIKE 'nao_prova:%'`). Um rotulo novo
 * entra nos dois sitios ou em nenhum.
 */
export function rotuloDaEvidencia(evidenciaRef: string): string | null {
  const prefixo = `${ROTULO_NAO_PROVA}:`;
  return evidenciaRef.startsWith(prefixo) ? ROTULO_NAO_PROVA : null;
}

/**
 * O instante em que o silencio do dono expira (F-18).
 *
 * **Exige fuso explicito**, e a razao mediu-se. O `Instant` e `type Instant =
 * string` sem forma imposta, e o `new Date(...)` so levanta quando o resultado
 * e `NaN`: `'2026-11-04T10:00:00'` — sem `Z` e sem deslocamento — e **valido**
 * e e lido em hora **local**, pelo que a mesma entrada dava instantes
 * diferentes em maquinas diferentes e o valor que saia era um ISO com `Z`, de
 * aspecto correcto. E a mesma classe de defeito do `rotuloDaEvidencia`: passava
 * por instante absoluto um instante que nao o era. Apanhado pela revisao
 * adversarial, que nomeou tambem o remedio.
 */
export function expiraEm(pedidoEm: Instant, horas: number = JANELA_DE_SILENCIO_HORAS): Instant {
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/.test(pedidoEm)) {
    throw new ProviderError(
      "VALIDATION",
      `instante sem fuso: '${pedidoEm}'. O dicionario fixa instantes em UTC, e ` +
        "um instante sem `Z` nem deslocamento le-se na hora local da maquina",
    );
  }
  const base = new Date(pedidoEm);
  if (Number.isNaN(base.getTime())) {
    throw new ProviderError("VALIDATION", `instante invalido: '${pedidoEm}'`);
  }
  return new Date(base.getTime() + horas * 3_600 * 1_000).toISOString();
}

/** Os metodos que este adaptador cobre, para quem escolhe adaptador (§3.2). */
export function cobre(metodo: Metodo): boolean {
  return CAPACIDADES_DO_MANUAL.metodos.includes(metodo);
}

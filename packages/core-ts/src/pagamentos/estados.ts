/**
 * A maquina de estados de `payment_accounts.estado` (KAM-052, criterio 8).
 *
 * Funcao **pura**, como o criterio pede: entra `(estado, gatilho, sinais)` e sai
 * um estado ou uma recusa. Nao le a base, nao escreve nada, nao conhece o
 * relogio. Quem persiste e quem a chama.
 *
 * As arestas sao **exactamente** as do `stateDiagram-v2` do `docs/tecnica/04`
 * §10.2, e nenhuma a mais. O que isso deixa de fora esta dito ao fundo deste
 * cabecalho, com a razao por que nao se inventa aqui.
 *
 *     [*]                      --> nao_iniciado
 *     nao_iniciado             --> docs_recolhidos         docs_recolhidos
 *     docs_recolhidos          --> banco_em_curso          pedido_ao_banco
 *     banco_em_curso           --> facilitador_em_curso    servicos_emis_contratados
 *     facilitador_em_curso     --> credenciais_recebidas   contrato_assinado
 *     credenciais_recebidas    --> teste_sandbox_ok        sandbox_e_pagamento_de_teste
 *     teste_sandbox_ok         --> ativo                   primeira_cobranca_conciliada
 *     ativo                    --> suspenso                fraude_divergencia_ou_pedido
 *     suspenso                 --> ativo                   regularizacao
 *     ativo                    --> revogado                encerramento
 *
 * ## O que o criterio 8 pede por nome, e porque e mais do que «rejeita»
 *
 * «`nao_iniciado → ativo` e rejeitada» — e nao e um caso especial: e o que sai
 * de a tabela nao ter essa aresta. O ensaio existe porque o atalho e
 * **tentador**: uma PME que ja tem conta EMIS de outro sistema parece nao
 * precisar dos passos, e o que os passos recolhem (§10.2) e a prova de que o
 * beneficiario e ela. Um `ativo` sem eles e uma conta que cobra para uma
 * entidade que ninguem verificou.
 *
 * «`teste_sandbox_ok → ativo` exige o sinal "primeira cobranca real
 * conciliada"» — e aqui o gatilho **nao chega**. Por isso a funcao toma
 * `sinais` e nao so um gatilho: a aresta existe na tabela e continua a ser
 * recusada se o sinal nao vier. E a unica aresta do diagrama com esta
 * propriedade, e e deliberado — o sandbox prova que a integracao fala com o
 * facilitador, e so um pagamento **real** conciliado prova que o dinheiro chega
 * a conta da PME, que e o que o ADR-004 afirma e a G-1 verifica.
 *
 * ## Duas arestas que o diagrama nao tem, e que nao se acrescentam aqui
 *
 * `suspenso --> revogado` **nao existe** no §10.2. Lido a letra, uma conta
 * suspensa por fraude tem de passar por `ativo` — isto e, por uma
 * regularizacao — antes de poder ser encerrada, o que e exactamente a ordem
 * contraria a que o caso pede. E uma lacuna do desenho e nao deste modulo:
 * acrescentar a aresta era inventar uma transicao de ciclo de vida de uma conta
 * de dinheiro, que e canon (§10.2 e o diagrama que o dicionario cita). Fica na
 * divida documental 152, com a leitura escrita e o credor nomeado.
 *
 * `revogado --> *` tambem nao existe, e esse e **terminal de propria decisao**:
 * o §10.2 chama-lhe «encerramento», e reabrir uma conta revogada e criar uma
 * conta nova — o que o indice `payment_accounts_um_ativo` ja permite, porque
 * `revogado` nao esta no seu predicado parcial.
 */

/** Os nove estados do `CHECK` do §6.2, na ordem do diagrama do §10.2. */
export const ESTADOS_DA_CONTA = [
  "nao_iniciado",
  "docs_recolhidos",
  "banco_em_curso",
  "facilitador_em_curso",
  "credenciais_recebidas",
  "teste_sandbox_ok",
  "ativo",
  "suspenso",
  "revogado",
] as const;

export type EstadoDaConta = (typeof ESTADOS_DA_CONTA)[number];

/** Os gatilhos do diagrama do §10.2, um por aresta. */
export const GATILHOS = [
  "docs_recolhidos",
  "pedido_ao_banco",
  "servicos_emis_contratados",
  "contrato_assinado",
  "sandbox_e_pagamento_de_teste",
  "primeira_cobranca_conciliada",
  "fraude_divergencia_ou_pedido",
  "regularizacao",
  "encerramento",
] as const;

export type Gatilho = (typeof GATILHOS)[number];

/**
 * Os sinais que uma aresta pode exigir **alem** do gatilho.
 *
 * Hoje ha um. E um objecto e nao um booleano para que o segundo — se o KAM-059
 * ou o KAM-056 precisarem de um — entre sem mudar a assinatura desta funcao,
 * que e chamada de fora do pacote.
 */
export type Sinais = {
  /**
   * «primeira cobranca real conciliada» (§10.2).
   *
   * **Real** e a palavra que faz o trabalho: nao e o pagamento de teste do
   * sandbox, que e o que levou a conta a `teste_sandbox_ok`. Quem o produz e a
   * reconciliacao do §8 — um `payment.confirmed` com `paga_via` de facilitador
   * autenticado, conciliado contra a conta. Neste ticket e um parametro: o
   * ledger que o origina e o KAM-053.
   */
  readonly primeiraCobrancaRealConciliada?: boolean;
};

export const TRANSICAO_INEXISTENTE = "TRANSICAO_INEXISTENTE";
export const SINAL_EM_FALTA = "SINAL_EM_FALTA";

export type RecusaDeTransicao =
  | {
      readonly ok: false;
      readonly codigo: typeof TRANSICAO_INEXISTENTE;
      readonly motivo: string;
    }
  | { readonly ok: false; readonly codigo: typeof SINAL_EM_FALTA; readonly motivo: string };

export type ResultadoDeTransicao =
  | { readonly ok: true; readonly estado: EstadoDaConta }
  | RecusaDeTransicao;

/** A tabela de arestas: `estado -> gatilho -> estado seguinte`. */
const ARESTAS: Readonly<Record<EstadoDaConta, Readonly<Partial<Record<Gatilho, EstadoDaConta>>>>> =
  {
    nao_iniciado: { docs_recolhidos: "docs_recolhidos" },
    docs_recolhidos: { pedido_ao_banco: "banco_em_curso" },
    banco_em_curso: { servicos_emis_contratados: "facilitador_em_curso" },
    facilitador_em_curso: { contrato_assinado: "credenciais_recebidas" },
    credenciais_recebidas: { sandbox_e_pagamento_de_teste: "teste_sandbox_ok" },
    teste_sandbox_ok: { primeira_cobranca_conciliada: "ativo" },
    ativo: { fraude_divergencia_ou_pedido: "suspenso", encerramento: "revogado" },
    suspenso: { regularizacao: "ativo" },
    revogado: {},
  };

/**
 * A unica aresta com sinal exigido, e a razao esta no cabecalho.
 *
 * Fica numa constante e nao num `if` dentro da funcao para que a pergunta «que
 * arestas exigem sinal?» tenha uma resposta legivel sem se ler o corpo — e para
 * que acrescentar a segunda seja uma linha de dados em vez de um ramo novo.
 */
const SINAL_EXIGIDO: readonly {
  readonly de: EstadoDaConta;
  readonly gatilho: Gatilho;
  readonly sinal: keyof Sinais;
}[] = [
  {
    de: "teste_sandbox_ok",
    gatilho: "primeira_cobranca_conciliada",
    sinal: "primeiraCobrancaRealConciliada",
  },
];

/**
 * A transicao. Pura: o mesmo trio da sempre o mesmo resultado.
 *
 * Devolve uma recusa em vez de lancar porque o chamador **e o fluxo de
 * onboarding** (KAM-091) e uma transicao recusada e uma resposta normal — «esta
 * conta ainda nao pode ficar activa» —, nao um defeito. Quem lanca e o registo,
 * onde a recusa e de arranque.
 */
export function transitar(
  estado: EstadoDaConta,
  gatilho: Gatilho,
  sinais: Sinais = {},
): ResultadoDeTransicao {
  const seguinte = ARESTAS[estado][gatilho];
  if (seguinte === undefined) {
    return {
      ok: false,
      codigo: TRANSICAO_INEXISTENTE,
      motivo:
        `'${estado}' nao tem aresta '${gatilho}' (docs/tecnica/04 §10.2). ` +
        `Gatilhos aceites em '${estado}': ` +
        `${Object.keys(ARESTAS[estado]).join(", ") || "nenhum (estado terminal)"}.`,
    };
  }
  const exige = SINAL_EXIGIDO.find((e) => e.de === estado && e.gatilho === gatilho);
  if (exige !== undefined && sinais[exige.sinal] !== true) {
    return {
      ok: false,
      codigo: SINAL_EM_FALTA,
      motivo:
        `'${estado}' -> '${seguinte}' exige o sinal '${exige.sinal}': a conta ` +
        "so fica activa com a primeira cobranca **real** conciliada " +
        "(docs/tecnica/04 §10.2), e nao com o pagamento de teste do sandbox.",
    };
  }
  return { ok: true, estado: seguinte };
}

/** Os estados em que a conta pode cobrar — o predicado do `payment_accounts_um_ativo`. */
export const ESTADOS_QUE_OCUPAM: readonly EstadoDaConta[] = ["ativo", "teste_sandbox_ok"];

/** `true` se a conta pode emitir cobrancas reais. So o `ativo`. */
export function podeCobrar(estado: EstadoDaConta): boolean {
  return estado === "ativo";
}

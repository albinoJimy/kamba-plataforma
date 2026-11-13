/**
 * O motor determinista de anomalias de pagamento (KAM-060).
 *
 * E o §9 do `docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`: regras que
 * leem o *ledger*, as cobrancas e as confirmacoes manuais, e produzem sinais
 * para a `platform.fraud_signals`. **Nada de modelos estatisticos** — esses sao
 * Clusters, e o bloco di-lo. Aqui ha oito regras com limiar, e todas elas
 * respondem a mesma pergunta duas vezes com o mesmo resultado.
 *
 * ## A fronteira que decide o que este ficheiro pode afirmar
 *
 * O `docs/tecnica/evidencia/E2_Pagamentos_Angola.md` classifica o comportamento
 * da ProxyPay como **NAO VERIFICADO** — a *sandbox* na linha 28, os precos na
 * 58, as duas porque o portal so mostra ecra de *login*. Logo **nenhuma regra
 * deste ficheiro depende de resposta de facilitador**: todas elas derivam do que
 * e interno e verificavel.
 *
 *     payment_events        o que o ledger registou, com `tipo_evento`
 *     payment_charges       o estado projectado, o `amount_minor`, o `payer_hmac`
 *     manual_confirmations  as confirmacoes humanas do KAM-054
 *     payment_inbox         os callbacks que nao se autenticaram (`hmac_invalido`)
 *     contacts.phone_hmac   quem e da casa, por HMAC e nunca por numero
 *
 * Um criterio que exigisse «o facilitador respondeu X» nao se finge: devolve-se
 * como medicao. Nao houve nenhum — as oito regras do bloco sao todas internas, e
 * isso e medicao e nao sorte: o §9 foi escrito sobre o *ledger* de proposito.
 *
 * ## O que este motor **nao** faz, e e a propriedade que o torna seguro
 *
 * Nao escreve estado de pagamento. Nao escreve `paga`. Nao toca na
 * `payment_charges`. O DoD do bloco escreve-o por extenso («o motor nunca
 * escreve `paga`; so sinais e eventos compensatorios»), e aqui isso e estrutural
 * e nao disciplina: as portas que este modulo declara **nao tem** operacao de
 * escrita sobre cobrancas. A unica escrita que propoe e um
 * `ajuste_reconciliacao` — um evento compensatorio do proprio *ledger*, que soma
 * e nunca corrige.
 *
 * ## E nao persiste os sinais, porque hoje nenhum papel os consegue escrever
 *
 * **Medido, e e a fronteira mais importante deste ficheiro.** A revisao
 * `db/migrations/versions/0032_confirmacao_manual_auditada.py` faz, no laco das
 * quatro tabelas do KAM-054, `REVOKE ALL ... FROM PUBLIC` e da **so
 * `GRANT SELECT`** a `kamba_app`, `kamba_batch` e ao papel de auditoria. A razao
 * esta escrita no *docstring* dela: «`fraud_signals` com `INSERT`, quem e
 * vigiado escrevia no registo de vigilancia». O unico escritor da tabela e a
 * `platform.manual_confirmar`, que e `SECURITY DEFINER` e so escreve as duas
 * regras do M-3; o `refund_cases` era igual, e escrevia-o so a
 * `platform.manual_reverter`. **Desde o KAM-197 tem um segundo escritor**, a
 * `platform.abrir_caso_de_reembolso` do consumidor do PAY, e este motor **le**
 * os casos que ela abre para a R-04 dizer qual e (ver o `_casosPorDuplicado`).
 *
 * Isto e um vao entre dois tickets e nao um defeito de nenhum: o KAM-054
 * escreveu, com razao, que o KAM-060 «nao acrescenta tabela» — e a tabela
 * existe —, e nao previu que faltaria o **escritor**. A consequencia e que a
 * persistencia vive atras da porta `EscritaDeSinais`, cuja implementacao exige
 * uma funcao `SECURITY DEFINER` e um `GRANT EXECUTE`, isto e, uma revisao. Ela
 * esta declarada aqui e **nao** se finge satisfeita: a secao de verificacao do
 * bloco diz quais caixas ficam por marcar e com que credor.
 *
 * O que fica inteiro, e e a maior parte do valor: as regras como dados
 * versionados, a avaliacao determinista, a reconciliacao do extracto, a accao
 * `reter_confirmacao` ligada ao veredicto do `ManualProvider`, a metrica e o
 * alerta.
 *
 * ## Os limiares sao **propostas**, e dizem-no onde aparecem
 *
 * «Todos os limiares sao propostas a calibrar no Piloto», escreve o Contexto do
 * bloco. O `LIMIARES_PROPOSTOS` e um mapa separado das regras exactamente por
 * isso: quem calibrar substitui o mapa e nao mexe na tabela das regras, e um
 * limiar que viesse embutido na regra tornava a calibracao uma alteracao de
 * codigo. O `PLANO_DE_CALIBRACAO` diz, por regra, com que dado se calibra.
 */

import { createHash } from "node:crypto";

import { avaliarConfirmacao } from "./manual.ts";
import type {
  DecisaoDoManual,
  EntradaDaConfirmacao,
  VeredictoDoManual,
} from "./manual.ts";
import type { Instant, Minor, Uuid } from "./tipos.ts";

/**
 * A versao das regras, para o `detalhe` do sinal.
 *
 * As regras sao **dados versionados** (criterio 1), e um sinal sem a versao da
 * regra que o produziu nao se consegue reinterpretar depois de a regra mudar:
 * ops olha para um `fraud_signals` de ha tres semanas e nao sabe com que limiar
 * ele nasceu. Sobe quando um limiar de omissao, uma severidade ou uma accao
 * mudar — nao quando se corrige um comentario.
 */
export const VERSAO_DAS_REGRAS = 1;

/** O identificador da regra no bloco: R-01 a R-08. */
export type IdDeRegra =
  | "R-01"
  | "R-02"
  | "R-03"
  | "R-04"
  | "R-05"
  | "R-06"
  | "R-07"
  | "R-08";

/**
 * As cinco accoes de `fraud_signals.accao`, e o dominio e **fechado na base**.
 *
 * E o `payment_... fraud_signals_accao_ck` da revisao `0032`. Repete-se aqui, e
 * a repeticao e deliberada pela razao do `obs_lint`: as duas sao a mesma regra e
 * nenhuma importa a outra, porque este modulo corre antes de qualquer base
 * existir. O `ACCOES` tem ensaio que o confronta com a lista da revisao.
 */
export const ACCOES = [
  "registar",
  "reter_confirmacao",
  "exigir_dupla",
  "bloquear_contacto",
  "suspender_manual",
] as const;

export type Accao = (typeof ACCOES)[number];

/** `fraud_signals.severidade`: `CHECK (severidade BETWEEN 1 AND 5)`. */
export type Severidade = 1 | 2 | 3 | 4 | 5;

/**
 * Uma regra, como dado versionado.
 *
 * O `regra` e o que vai para a coluna `fraud_signals.regra`, e e **texto e nao o
 * `R-NN`**: a coluna e lida por quem atende um alerta, e `R-04` nao diz nada a
 * essa pessoa. O `R-NN` fica no `id`, que e o que o bloco nomeia.
 */
export type Regra = {
  readonly id: IdDeRegra;
  /** O valor de `fraud_signals.regra`. Minusculas, `snake_case`. */
  readonly regra: string;
  readonly severidade: Severidade;
  readonly accao: Accao;
  /** Uma linha, para o `COMMENT` e para o painel. Sem PII, como tudo aqui. */
  readonly descricao: string;
};

/**
 * As oito regras do bloco, pela ordem dele.
 *
 * ## Porque e que a R-07 e `registar` e nao uma accao mais forte
 *
 * O bloco escreve «R-07 *no-show* de COD -> exigir sinal por referencia», e
 * **«exigir sinal por referencia» nao esta no dominio das accoes**: o
 * `fraud_signals_accao_ck` da `0032` fecha-o nos cinco valores do `ACCOES`, e um
 * sexto valor e uma alteracao de `CHECK`, isto e, uma revisao. Logo a regra
 * **registra** e a consequencia e de quem consome: a «Fronteira com KAM-097» do
 * bloco escreve que «este ticket produz sinais de pagamento; o consumo para
 * sancoes e reviews retidos e de KAM-097/REP». Escolher `bloquear_contacto`
 * aqui era implementar a sancao de outro ticket com o nome errado, e deixar o
 * `detalhe` a recomendar o que nunca aconteceria.
 *
 * ## Porque e que a R-01 e severidade 3 e nao 2
 *
 * O criterio 2 pede, a letra, «`fraud_signals` de severidade >= 3». Nao e
 * escolha: e o numero que o criterio escreve, e um 2 deixava a caixa por marcar
 * com o motor a funcionar.
 */
export const REGRAS: readonly Regra[] = [
  {
    id: "R-01",
    regra: "pagamento_divergente_repetido",
    severidade: 3,
    accao: "registar",
    descricao:
      "varios pagamento_divergente na mesma conta dentro da janela: o valor " +
      "recebido nao bate com o cobrado mais do que uma vez",
  },
  {
    id: "R-02",
    regra: "hmac_invalido_em_massa",
    severidade: 4,
    accao: "registar",
    descricao:
      "callbacks recusados por assinatura invalida acima do limiar por conta " +
      "e por hora (F-05): alguem esta a forjar origem",
  },
  {
    id: "R-03",
    regra: "pagamento_orfao",
    severidade: 3,
    accao: "registar",
    descricao:
      "evento de pagamento sem cobranca que o reclame: dinheiro recebido que " +
      "nao fecha encomenda nenhuma",
  },
  {
    id: "R-04",
    regra: "pagamento_duplicado",
    severidade: 4,
    accao: "registar",
    descricao:
      "segundo pagamento sobre uma cobranca ja paga: abre caso de reembolso e " +
      "o segundo evento nunca confirma a encomenda (G6)",
  },
  {
    id: "R-05",
    regra: "auto_compra",
    severidade: 4,
    accao: "reter_confirmacao",
    descricao:
      "o HMAC do pagador coincide com o de quem confirma: a confirmacao fica " +
      "retida ate ops olhar para ela",
  },
  {
    id: "R-06",
    regra: "desvio_de_confirmacoes_manuais",
    severidade: 2,
    accao: "exigir_dupla",
    descricao:
      "confirmacoes manuais da semana acima de k vezes a mediana do tenant: " +
      "as seguintes passam a exigir segunda assinatura",
  },
  {
    id: "R-07",
    regra: "cod_sem_pagamento_repetido",
    severidade: 2,
    accao: "registar",
    descricao:
      "cobrancas cod do mesmo contacto terminadas sem pagamento acima do " +
      "limiar: o consumo da sancao e de KAM-097",
  },
  {
    id: "R-08",
    regra: "extracto_divergente",
    severidade: 3,
    accao: "registar",
    descricao:
      "linha do extracto bancario sem cobranca paga que lhe corresponda, ou " +
      "o inverso: gera ajuste_reconciliacao compensatorio",
  },
];

/** `REGRAS` indexado pelo `id`. Construido uma vez, e nao por regra. */
export const REGRA_POR_ID: Readonly<Record<IdDeRegra, Regra>> = Object.freeze(
  Object.fromEntries(REGRAS.map((r) => [r.id, r])) as Record<IdDeRegra, Regra>,
);

/**
 * Os limiares, **todos propostas a calibrar no Piloto**.
 *
 * Separados das regras de proposito: ver o cabecalho. Os valores vem do bloco
 * onde ele os escreve (o 3 da R-01 e o «3 `pagamento_divergente` ... em 1 h» do
 * criterio 2) e sao escolha nossa onde ele escreve «N proposto» ou «k proposto».
 */
export const LIMIARES_PROPOSTOS: Readonly<Record<IdDeRegra, number>> =
  Object.freeze({
    /** Quantos `pagamento_divergente` na mesma conta dentro da janela. */
    "R-01": 3,
    /** Quantos `hmac_invalido` na mesma conta dentro da janela (o «N»). */
    "R-02": 10,
    /** Um orfao basta: o criterio 3 pede «sinal imediato». */
    "R-03": 1,
    /** Um duplicado basta. */
    "R-04": 1,
    /** Uma coincidencia de HMAC basta. */
    "R-05": 1,
    /** O «k vezes a mediana» do criterio 6. */
    "R-06": 3,
    /** Quantas cobrancas `cod` terminadas sem pagamento, pelo mesmo contacto. */
    "R-07": 3,
    /** Diferenca minima em unidade menor para a linha do extracto contar. */
    "R-08": 1,
  });

/** A janela, em horas, de cada regra que tem janela. As outras ignoram-na. */
export const JANELAS_PROPOSTAS: Readonly<Record<IdDeRegra, number>> =
  Object.freeze({
    /** «na mesma conta em 1 h» — criterio 2. */
    "R-01": 1,
    /** «acima de N/hora por conta» — criterio 2, F-05. */
    "R-02": 1,
    /**
     * **720 e nao 24, e a diferenca e o criterio 3.**
     *
     * Ligar a janela a R-03 pos a nu uma escolha errada de valor: com 24 h, um
     * orfao **com mais de 24 horas** caia fora da janela e deixava de produzir
     * sinal — e e exactamente esse que o criterio 3 manda alertar («a metrica
     * "orfaos abertos > 24 h" … dispara alerta se > 0»). A janela que apanha o
     * caso que importa e o horizonte da fotografia.
     *
     * **E a repeticao nao e problema do motor.** Um orfao que continua aberto
     * continua a ser uma anomalia, e o motor existe para o dizer todas as vezes
     * que o vê; quem nao repete a **linha** e a `registar_sinal_de_anomalia`,
     * com a guarda de janela dela. Por a desduplicacao no motor era po-la no
     * sitio onde ela esconde o facto em vez de o registar uma vez.
     */
    "R-03": 720,
    /** 720 pela mesma razao da R-03: a persistencia e que e a anomalia. */
    "R-04": 720,
    "R-05": 24,
    /** «por semana» — criterio 6. */
    "R-06": 168,
    /** Trinta dias, para um padrao de COD ter onde aparecer. */
    "R-07": 720,
    "R-08": 24,
  });

/**
 * Com que dado se calibra cada limiar, para o «plano de revisao no Piloto» do
 * DoD.
 *
 * Existe porque um limiar marcado «proposta» sem dizer **como** se calibra e
 * uma proposta que ninguem vai calibrar: a caixa do DoD pede as duas coisas, e
 * a primeira versao deste ficheiro so tinha a primeira.
 */
export const PLANO_DE_CALIBRACAO: Readonly<Record<IdDeRegra, string>> =
  Object.freeze({
    "R-01":
      "distribuicao de pagamento_divergente por conta e por hora nas primeiras " +
      "quatro semanas; o limiar fica no percentil 99 das contas sem incidente",
    "R-02":
      "contagem de payment_inbox em hmac_invalido por conta e por hora; sem " +
      "ataque, o esperado e zero e qualquer valor positivo e sinal",
    "R-03": "nao se calibra: um orfao e sempre um orfao (criterio 3)",
    "R-04": "nao se calibra: um duplicado e sempre um duplicado (G6)",
    "R-05": "nao se calibra: a coincidencia de HMAC e binaria",
    "R-06":
      "mediana semanal de confirmacoes manuais por contacto, por tenant, " +
      "depois de doze semanas; e so vale com **tres ou mais** contactos " +
      "activos na semana — com um ou dois, a algebra do _r06 torna o disparo " +
      "impossivel para qualquer k >= 2, e isso e limite do desenho e nao " +
      "calibracao",
    "R-07":
      "proporcao de cobrancas cod terminadas sem pagamento, por contacto, " +
      "contra a taxa de entrega real do Piloto",
    "R-08":
      "nao se calibra o limiar; calibra-se a tolerancia de arredondamento do " +
      "extracto, que hoje e zero porque tudo e unidade menor inteira",
  });

// ------------------------------------------------------------------ entrada

/** Os `tipo_evento` da `payment_events` que este motor le. */
export type TipoDeEventoDoLedger =
  | "pagamento_recebido"
  | "pagamento_confirmado"
  | "pagamento_divergente"
  | "pagamento_orfao"
  | "pagamento_duplicado"
  | "ajuste_reconciliacao";

/** Uma linha de `payment_events`, no que importa a este motor. */
export type EventoObservado = {
  readonly eventId: bigint;
  readonly tenantId: Uuid;
  readonly chargeId: Uuid;
  readonly accountId: Uuid;
  readonly tipoEvento: TipoDeEventoDoLedger;
  readonly sequencia: number;
  readonly valorMinor: Minor;
  /** `ocorrido_at` quando existe, senao `recebido_at`. Quem escolhe e o SQL. */
  readonly instante: Instant;
};

/** Uma linha de `payment_charges`, no que importa. */
export type CobrancaObservada = {
  readonly chargeId: Uuid;
  readonly tenantId: Uuid;
  readonly accountId: Uuid;
  readonly orderId: Uuid | null;
  readonly estado: string;
  readonly metodo: string;
  readonly amountMinor: Minor;
  /**
   * `payer_hmac` em hexadecimal, ou `null`.
   *
   * **Hexadecimal e nao `Uint8Array`**, e a razao e a comparacao: dois
   * `Uint8Array` com os mesmos bytes nao sao iguais por `===`, e uma regra
   * anti-auto-compra que comparasse referencias nunca disparava. A conversao
   * faz-se no SQL (`encode(payer_hmac, 'hex')`), onde ha uma funcao para isso.
   */
  readonly payerHmac: string | null;
  /** O contacto do cliente da cobranca, quando se conhece. */
  readonly contactId: Uuid | null;
  /**
   * A referencia Multicaixa, quando existe. **Unica com a conta e nao sozinha.**
   *
   * A `0029` escreve-o por extenso: «o par `(account_id, referencia)` e unico —
   * **com** a conta, porque uma referencia Multicaixa e Entidade + Referencia e
   * duas PMEs podem ter o mesmo numero». A reconciliacao indexava por referencia
   * sozinha e perdia uma das duas cobrancas; achado da revisao adversarial.
   */
  readonly referencia: string | null;
  /**
   * `criado_at`, para as regras que tem janela e nao tinham onde a medir.
   *
   * A R-05 e a R-07 declaravam janela no `JANELAS_PROPOSTAS` e **nao a
   * aplicavam**, porque este tipo nao tinha instante nenhum — isto e, a janela
   * delas era decoracao. Achado da revisao adversarial (a R-03 e a R-04 tinham
   * o mesmo defeito pelo lado do limiar).
   */
  readonly criadoEm: Instant;
};

/** Uma linha de `manual_confirmations`, no que importa a R-05 e a R-06. */
export type ConfirmacaoObservada = {
  readonly chargeId: Uuid;
  readonly tenantId: Uuid;
  readonly contactId: Uuid;
  readonly decisao: string;
  readonly instante: Instant;
};

/** Um callback recusado: `payment_inbox` em `hmac_invalido` (R-02). */
export type RecusaDeCallback = {
  readonly accountId: Uuid;
  readonly instante: Instant;
};

/**
 * Quem e da casa: o dono e os funcionarios, por HMAC de telefone.
 *
 * **Nunca o numero.** O `contacts.phone_hmac` e `bytea` e o numero e PII P2
 * (ADR-010); a R-05 compara HMAC com HMAC e nunca ve um telefone. Vem em
 * hexadecimal pela razao do `payerHmac`.
 */
export type ContactoDaCasa = {
  readonly contactId: Uuid;
  readonly phoneHmac: string;
};

/**
 * Um caso de reembolso de duplicado aberto pelo consumidor do PAY (KAM-197).
 *
 * **Pela cobranca e nao pela encomenda**, e a razao e o que a R-04 le: o
 * `pagamento_duplicado` do *ledger* e de uma cobranca, e o caso que o PAY abre e
 * de uma encomenda (o `order.refund_requested` nao traz `charge_id`). Quem faz a
 * ponte e o SQL, que junta o caso as cobrancas da encomenda dele; o motor so
 * compara `chargeId` e valor.
 */
export type CasoDeReembolsoObservado = {
  readonly casoId: Uuid;
  readonly tenantId: Uuid;
  readonly chargeId: Uuid;
  readonly valorMinor: Minor;
};

/**
 * O que o motor le, numa fotografia.
 *
 * **Uma fotografia e nao um fluxo**, e isso e o que torna o determinismo
 * verificavel: o criterio 9 pede «sinais identicos em duas execucoes», e uma
 * funcao que lesse a base duas vezes podia ler duas bases diferentes. Quem le a
 * base e a porta; quem decide e uma funcao pura sobre o que ela devolveu.
 */
export type Fotografia = {
  readonly eventos: readonly EventoObservado[];
  readonly cobrancas: readonly CobrancaObservada[];
  readonly confirmacoes: readonly ConfirmacaoObservada[];
  readonly recusas: readonly RecusaDeCallback[];
  readonly casa: readonly ContactoDaCasa[];
  /**
   * Os casos de reembolso de duplicado que o PAY ja abriu (KAM-197).
   *
   * **Obrigatorio e nao opcional**, de proposito: opcional, uma composicao que
   * se esquecesse de o ler deixava a R-04 a dizer `por_abrir` sobre um caso que
   * existe — e nenhum ensaio do motor o via, porque o motor estaria certo.
   */
  readonly reembolsos: readonly CasoDeReembolsoObservado[];
  /** O instante de referencia das janelas. Injectado, nao lido do relogio. */
  readonly agora: Instant;
};

/** Os limiares e as janelas em vigor. Separados para se poderem calibrar. */
export type Configuracao = {
  readonly limiares: Readonly<Record<IdDeRegra, number>>;
  readonly janelas: Readonly<Record<IdDeRegra, number>>;
};

/** A configuracao de omissao: as propostas, as duas. */
export const CONFIGURACAO_PROPOSTA: Configuracao = Object.freeze({
  limiares: LIMIARES_PROPOSTOS,
  janelas: JANELAS_PROPOSTAS,
});

// -------------------------------------------------------------------- saida

/**
 * Um sinal, na forma de uma linha de `fraud_signals`.
 *
 * Os nomes dos campos sao os das colunas, e nao e preguica: o que escreve a
 * linha e uma porta, e uma traducao de nomes a meio era mais um sitio onde um
 * `charge_id` podia aterrar na coluna do `contact_id`.
 */
export type Sinal = {
  readonly tenantId: Uuid;
  readonly contactId: Uuid | null;
  readonly chargeId: Uuid | null;
  readonly regra: string;
  readonly severidade: Severidade;
  readonly accao: Accao;
  /** `jsonb`. **Sem telefone e sem texto** — ver o `semPii`. */
  readonly detalhe: Readonly<Record<string, string | number | boolean | null>>;
};

/**
 * As chaves que o `detalhe` **nunca** pode ter (criterio 8).
 *
 * E uma lista por nome e nao por forma, pela razao do `obs_lint`: a forma de um
 * telefone angolano apanha-se num `pattern`, mas a mensagem de erro que serve a
 * quem a le e «a chave `telefone` nao entra num sinal», e nao «o valor casa uma
 * expressao». A guarda de forma esta a seguir, no `semPii`, e as duas correm.
 *
 * O `contact_id` **nao** esta aqui: o criterio 8 escreve, a letra, que o sinal
 * leva «so `contact_id`, `charge_id`, regra e severidade». Um `contact_id` e um
 * identificador interno sem o numero atras dele, que e o desenho do ADR-010.
 */
export const CHAVES_PROIBIDAS_NO_DETALHE = [
  "telefone",
  "phone",
  "msisdn",
  "numero",
  "wa_id",
  "texto",
  "mensagem",
  "message",
  "body",
  "corpo",
  "nome",
  "name",
  "email",
  "bsuid",
  // **As cinco de baixo entraram pela revisao adversarial**, e a razao e que a
  // lista anterior tinha `texto` e `mensagem` e nao tinha os nomes que alguem
  // usa de facto para escrever texto livre. Medido: `{observacao: "o <nome>
  // reclamou do pagamento"}` passava a guarda inteira.
  "observacao",
  "nota",
  "descricao",
  "comentario",
  "razao",
] as const;

/**
 * Um valor com forma de telefone, para a guarda do `semPii`.
 *
 * **Sete digitos nao bastam, e isso foi medido noutro ticket deste conjunto**:
 * um `923 456 789` escrito com espacos escapava a tres padroes que so olhavam
 * para digitos seguidos. Daqui a normalizacao primeiro — tiram-se espacos,
 * pontos, barras e tracos — e so depois se conta. Nove digitos e o comprimento
 * de um movel angolano; o `+244` leva a treze.
 */
const _SEPARADORES = /[\s.\-/()]/g;

/**
 * **`[29]` e nao `9`**, e a diferenca mediu-se: o padrao anterior exigia um `9`
 * a cabeca e so apanhava **moveis**. Um fixo de Luanda (`222 123 456`) tem os
 * mesmos nove digitos e passava a guarda inteira — e o *docstring* dizia «nove
 * digitos e o comprimento de um movel angolano», o que era verdade e nao era
 * suficiente. Achado da revisao adversarial.
 *
 * **E os dois `lookaround` nao sao enfeite: sem eles, alargar o `9` para `[29]`
 * criou um falso positivo imediato.** Medido ao correr a suite: um `account_id`
 * como `22222222-2222-4222-8222-222222222222`, depois de a normalizacao lhe
 * tirar os tracos, e um corrido de trinta e dois digitos — e nove digitos
 * **dentro** de trinta e dois casavam o padrao, pelo que a guarda passou a
 * recusar todo o sinal que leve uma conta no `detalhe`. Um telefone sao nove
 * digitos **inteiros**, nao nove digitos dentro de um numero maior.
 */
const _FORMA_DE_TELEFONE = /(?<!\d)(?:\+?244)?[29]\d{8}(?!\d)/;

/**
 * A forma de um UUID, para a guarda o deixar passar antes de contar digitos.
 *
 * Cinta e peito a mais do que os `lookaround`, e de proposito: um `contact_id`,
 * um `charge_id` e um `account_id` sao o que o criterio 8 **manda** por no
 * sinal, e eles sao a unica familia de valores longos que a guarda ve. Dizer
 * «um UUID nao e um telefone» por extenso e mais legivel do que confiar que a
 * aritmetica dos digitos nunca volte a colidir.
 */
const _FORMA_DE_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * `null` quando o `detalhe` esta limpo, ou a razao da recusa.
 *
 * Devolve a **razao** e nao um booleano, e isso e o que a torna util num
 * ensaio e numa mensagem de erro: «tem PII» obriga quem le a procurar qual
 * campo, e o campo e o que paga o minuto dele.
 */
export function semPii(
  detalhe: Readonly<Record<string, unknown>>,
): string | null {
  for (const [chave, valor] of Object.entries(detalhe)) {
    const minuscula = chave.toLowerCase();
    for (const proibida of CHAVES_PROIBIDAS_NO_DETALHE) {
      if (minuscula.includes(proibida)) {
        return `a chave '${chave}' nao entra num sinal (criterio 8)`;
      }
    }
    // **Desce aos objectos em vez de os saltar.** O tipo do `Sinal.detalhe` e
    // plano, pelo que daqui nao vem nenhum — mas esta funcao e tambem o oraculo
    // de quem chamar a porta por outro caminho, e um `continue` sobre um
    // objecto era um buraco com o tamanho de toda uma sub-arvore.
    if (valor !== null && typeof valor === "object") {
      const dentro = semPii(valor as Record<string, unknown>);
      if (dentro !== null) return `em '${chave}': ${dentro}`;
      continue;
    }
    // **`String(valor)` e nao `typeof valor !== "string") continue`**, e foi um
    // achado da revisao adversarial: o tipo do `detalhe` admite `number`, e um
    // movel angolano sao nove digitos — `{identificador: 923456789}` passava.
    if (valor === null || valor === undefined) continue;
    const texto = String(valor);
    if (_FORMA_DE_UUID.test(texto)) continue;
    if (_FORMA_DE_TELEFONE.test(texto.replace(_SEPARADORES, ""))) {
      return `o valor de '${chave}' tem forma de telefone (criterio 8)`;
    }
  }
  return null;
}

/**
 * Levanta se algum sinal levar PII. **Corre em todos os caminhos de saida.**
 *
 * Existe porque a primeira versao tinha o laco **dentro** do `avaliar`, e o
 * `avaliar` corre a R-01 ate a R-07: os sinais da R-08, que saem pelo
 * `sinaisDaReconciliacao`, nao passavam por guarda nenhuma — e eram precisamente
 * os que levavam texto do CSV do dono. Achado da revisao adversarial, e o unico
 * que bloqueava a fusao.
 */
function _exigirSemPii(sinais: readonly Sinal[]): void {
  for (const sinal of sinais) {
    const razao = semPii(sinal.detalhe);
    if (razao !== null) throw new SinalComPii(sinal.regra, razao);
  }
}

/** Um `detalhe` com PII chegou ao motor. Fail-closed: nao se publica. */
export class SinalComPii extends Error {
  override readonly name = "SinalComPii";

  constructor(regra: string, razao: string) {
    super(
      `o sinal da regra '${regra}' nao se publica: ${razao}. Um sinal e lido ` +
        "por ops e exportado para o painel, e o criterio 8 do KAM-060 fecha o " +
        "detalhe em contact_id, charge_id, regra e severidade",
    );
  }
}

// ---------------------------------------------------------------- avaliacao

/**
 * Corre as oito regras sobre a fotografia. **Pura e determinista.**
 *
 * A saida vem ordenada por `(regra, chargeId, contactId)` e nao pela ordem em
 * que as regras correram: o criterio 9 pede «sinais identicos em duas
 * execucoes», e duas leituras da base podem devolver as linhas em ordens
 * diferentes sem que nada esteja errado — o `ORDER BY` de uma consulta sem
 * chave total nao e estavel. Ordenar na saida e o que torna a igualdade
 * verificavel sem depender do plano do PostgreSQL.
 *
 * Levanta `SinalComPii` em vez de filtrar: um sinal com PII filtrado em
 * silencio e uma regra que deixou de disparar sem ninguem saber.
 */
export function avaliar(
  foto: Fotografia,
  cfg: Configuracao = CONFIGURACAO_PROPOSTA,
): readonly Sinal[] {
  const sinais = [
    ..._r01(foto, cfg),
    ..._r02(foto, cfg),
    ..._r03(foto, cfg),
    ..._r04(foto, cfg),
    ..._r05(foto, cfg),
    ..._r06(foto, cfg),
    ..._r07(foto, cfg),
  ];
  _exigirSemPii(sinais);
  return _ordenar(sinais);
}

/** A ordem estavel da saida. Ver o `avaliar`. */
function _ordenar(sinais: readonly Sinal[]): readonly Sinal[] {
  return [...sinais].sort(
    (a, b) =>
      a.regra.localeCompare(b.regra) ||
      (a.chargeId ?? "").localeCompare(b.chargeId ?? "") ||
      (a.contactId ?? "").localeCompare(b.contactId ?? "") ||
      // **O quarto termo e o que torna a ordem total**, e sem ele a R-02 saia na
      // ordem da entrada. Achado da revisao adversarial: a R-02 e a unica regra
      // cujo sinal tem `chargeId` **e** `contactId` nulos — ela conta por conta,
      // e a conta vive no `detalhe` —, pelo que os tres primeiros termos davam
      // chave **identica** a todos os sinais dela. Com o `sort` estavel, a saida
      // seguia a ordem de iteracao do `Map`, que segue a de aparicao em
      // `foto.recusas`: duas contas trocadas na entrada davam duas saidas
      // diferentes, e o ensaio do determinismo nao o via porque usava **uma**
      // conta so.
      //
      // Serializa-se o `detalhe` inteiro e nao so o `account_id`: o que se quer
      // e uma ordem **total** sobre o que o sinal e, e um campo escolhido a mao
      // deixava o proximo empate para o proximo revisor.
      _chaveDoDetalhe(a).localeCompare(_chaveDoDetalhe(b)),
  );
}

/**
 * Uma chave estavel do `detalhe`, para o desempate total do `_ordenar`.
 *
 * As chaves ordenam-se antes de serializar: a ordem de insercao de um objecto
 * JavaScript e a de escrita, e dois sinais iguais escritos por caminhos
 * diferentes dariam cadeias diferentes — o que punha a ordem a depender da
 * ordem de escrita, que e o defeito que esta funcao existe para fechar.
 */
function _chaveDoDetalhe(sinal: Sinal): string {
  return Object.keys(sinal.detalhe)
    .sort()
    .map((k) => `${k}=${String(sinal.detalhe[k])}`)
    .join("|");
}

function _sinal(
  id: IdDeRegra,
  campos: {
    readonly tenantId: Uuid;
    readonly contactId?: Uuid | null;
    readonly chargeId?: Uuid | null;
    readonly detalhe: Readonly<Record<string, string | number | boolean | null>>;
  },
): Sinal {
  const regra = REGRA_POR_ID[id];
  return {
    tenantId: campos.tenantId,
    contactId: campos.contactId ?? null,
    chargeId: campos.chargeId ?? null,
    regra: regra.regra,
    severidade: regra.severidade,
    accao: regra.accao,
    detalhe: { ...campos.detalhe, regra_id: id, versao: VERSAO_DAS_REGRAS },
  };
}

/** `true` se `instante` cai dentro de `horas` para tras de `agora`. */
function _naJanela(instante: Instant, agora: Instant, horas: number): boolean {
  const t = Date.parse(instante);
  const fim = Date.parse(agora);
  // Um instante ilegivel **nao entra na janela**, e isso e fail-closed no
  // sentido certo: contá-lo inflacionava a contagem de uma regra de fraude com
  // uma linha que ninguem sabe datar, e um sinal assim nao se consegue defender
  // a quem o receba.
  if (!Number.isFinite(t) || !Number.isFinite(fim)) return false;
  return t <= fim && fim - t <= horas * 3_600_000;
}

/** R-01: divergencia repetida na mesma conta dentro da janela. */
function _r01(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const porConta = new Map<string, EventoObservado[]>();
  for (const e of foto.eventos) {
    if (e.tipoEvento !== "pagamento_divergente") continue;
    if (!_naJanela(e.instante, foto.agora, cfg.janelas["R-01"])) continue;
    const lista = porConta.get(e.accountId);
    if (lista === undefined) porConta.set(e.accountId, [e]);
    else lista.push(e);
  }
  const saida: Sinal[] = [];
  for (const [, eventos] of porConta) {
    if (eventos.length < cfg.limiares["R-01"]) continue;
    // **O sinal e um por conta e nao um por evento.** Tres divergencias numa
    // hora sao *uma* anomalia, e tres sinais sobre a mesma coisa eram tres
    // alertas para ops abrir e fechar. O `chargeId` que fica e o da divergencia
    // **mais recente**, por ser o caso que ops tem a mao para olhar.
    // **A ordem por `eventId` compara-se sem passar por `number`**, e nao e
    // zelo: o `money_lint` recusa `Number(` neste directorio por desenho, e a
    // razao vale aqui mesmo nao sendo dinheiro — o `id` da `payment_events` e
    // `bigint`, e `Number(a - b)` de dois `bigint` acima de 2^53 devolve um
    // comparador que mente. A forma com ternarios e exacta para qualquer
    // `bigint`.
    const ordenados = [...eventos].sort((a, b) => {
      if (a.instante !== b.instante) return a.instante.localeCompare(b.instante);
      if (a.eventId < b.eventId) return -1;
      return a.eventId > b.eventId ? 1 : 0;
    });
    const ultimo = ordenados[ordenados.length - 1] as EventoObservado;
    saida.push(
      _sinal("R-01", {
        tenantId: ultimo.tenantId,
        chargeId: ultimo.chargeId,
        contactId: _contactoDa(foto, ultimo.chargeId),
        detalhe: {
          account_id: ultimo.accountId,
          ocorrencias: eventos.length,
          janela_horas: cfg.janelas["R-01"],
          limiar: cfg.limiares["R-01"],
        },
      }),
    );
  }
  return saida;
}

/** R-02: callbacks recusados por HMAC acima do limiar, por conta (F-05). */
function _r02(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const porConta = new Map<string, number>();
  for (const r of foto.recusas) {
    if (!_naJanela(r.instante, foto.agora, cfg.janelas["R-02"])) continue;
    porConta.set(r.accountId, (porConta.get(r.accountId) ?? 0) + 1);
  }
  const saida: Sinal[] = [];
  for (const [accountId, contagem] of porConta) {
    if (contagem < cfg.limiares["R-02"]) continue;
    // **Sem `tenantId` da conta, e e por isso que ele vem da cobranca.** A
    // `payment_inbox` nao tem `tenant_id` (um callback forjado chega antes de
    // se saber de quem e), pelo que o tenant deriva da conta pelas cobrancas
    // que ela tem. Sem nenhuma, a recusa nao se consegue atribuir e o sinal
    // nao se escreve — dizê-lo e melhor do que inventar um tenant.
    const tenantId = foto.cobrancas.find((c) => c.accountId === accountId)
      ?.tenantId;
    if (tenantId === undefined) continue;
    saida.push(
      _sinal("R-02", {
        tenantId,
        detalhe: {
          account_id: accountId,
          recusas: contagem,
          janela_horas: cfg.janelas["R-02"],
          limiar: cfg.limiares["R-02"],
        },
      }),
    );
  }
  return saida;
}

/**
 * R-03: orfao — um sinal por evento, porque o criterio 3 pede «imediato».
 *
 * **A janela e o limiar aplicam-se, e nao se aplicavam.** A primeira versao
 * desta funcao nao recebia `Configuracao` nenhuma: o `JANELAS_PROPOSTAS["R-03"]`
 * e o `LIMIARES_PROPOSTOS["R-03"]` existiam no mapa e nao decidiam nada, pelo
 * que o criterio 1 («limiar **configuravel**») era falso para ela. Achado da
 * revisao adversarial, e a consequencia operacional era a pior parte: com o
 * `HORAS_DA_FOTOGRAFIA` em 720, cada corrida do *job* re-emitia os orfaos dos
 * ultimos trinta dias e o `fraud_signals_total` subia o atraso inteiro de cada
 * vez.
 *
 * O limiar e por **conta**, como na R-01: «um orfao basta» e `limiar = 1`, e
 * quem o subir pede «so a partir de N orfaos na mesma conta».
 */
function _r03(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const naJanela = foto.eventos.filter(
    (e) =>
      e.tipoEvento === "pagamento_orfao" &&
      _naJanela(e.instante, foto.agora, cfg.janelas["R-03"]),
  );
  const porConta = new Map<string, number>();
  for (const e of naJanela) {
    porConta.set(e.accountId, (porConta.get(e.accountId) ?? 0) + 1);
  }
  return naJanela
    .filter((e) => (porConta.get(e.accountId) ?? 0) >= cfg.limiares["R-03"])
    .map((e) =>
      _sinal("R-03", {
        tenantId: e.tenantId,
        chargeId: e.chargeId,
        contactId: _contactoDa(foto, e.chargeId),
        detalhe: {
          account_id: e.accountId,
          event_id: String(e.eventId),
          valor_minor: String(e.valorMinor),
          // Quantas horas o orfao tem. E o numerador da metrica «orfaos
          // abertos > 24 h» do criterio 3, e fica no sinal para o painel nao
          // ter de recalcular a idade a partir de um carimbo.
          idade_horas: _idadeEmHoras(e.instante, foto.agora),
        },
      }),
    );
}

/**
 * R-04: duplicado — e o segundo pagamento nunca confirma (G6).
 *
 * A janela e o limiar aplicam-se, pela razao escrita no `_r03`: os dois eram
 * decoracao nesta funcao tambem.
 */
function _r04(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const naJanela = foto.eventos.filter(
    (e) =>
      e.tipoEvento === "pagamento_duplicado" &&
      _naJanela(e.instante, foto.agora, cfg.janelas["R-04"]),
  );
  const porConta = new Map<string, number>();
  for (const e of naJanela) {
    porConta.set(e.accountId, (porConta.get(e.accountId) ?? 0) + 1);
  }
  const casos = _casosPorDuplicado(foto, naJanela);
  return naJanela
    .filter((e) => (porConta.get(e.accountId) ?? 0) >= cfg.limiares["R-04"])
    .map((e) =>
      _sinal("R-04", {
        tenantId: e.tenantId,
        chargeId: e.chargeId,
        contactId: _contactoDa(foto, e.chargeId),
        detalhe: {
          account_id: e.accountId,
          event_id: String(e.eventId),
          valor_minor: String(e.valorMinor),
          // **O caso, quando existe; `por_abrir`, quando nao.** O PAY abre-o ao
          // consumir o `order.refund_requested` (KAM-197), e isso e assincrono:
          // um sinal calculado antes do consumo diz `por_abrir`, e e verdade no
          // instante em que se escreve. O que nunca faz e supor o caso.
          refund_case: casos.get(e.eventId) ?? REEMBOLSO_POR_ABRIR,
        },
      }),
    );
}

/** O `refund_case` de um sinal de duplicado sem caso aberto. */
export const REEMBOLSO_POR_ABRIR = "por_abrir";

/**
 * Que caso de reembolso corresponde a cada duplicado, pelo `eventId`.
 *
 * **Um caso por duplicado, e nao o mesmo caso para todos.** Tres pagamentos da
 * mesma cobranca sao dois duplicados e dois pedidos de reembolso; casar os dois
 * com o primeiro caso dizia que estavam ambos tratados com um caso so. A
 * atribuicao e gulosa e por ordem total — eventos por `eventId`, casos por
 * `casoId` —, pelo que nao depende da ordem em que a base devolveu as linhas
 * (o segundo ensaio do criterio 9).
 *
 * Casa por tenant, cobranca e valor. O valor e o do pagamento: e o que o COM
 * pede de volta na regra 4 (`aplicarPagamentoExcedente`), e e o `valor_minor`
 * do `pagamento_duplicado` que o `payment.confirmed` leva.
 */
function _casosPorDuplicado(
  foto: Fotografia,
  duplicados: readonly EventoObservado[],
): ReadonlyMap<bigint, Uuid> {
  const livres = [...foto.reembolsos].sort((a, b) =>
    a.casoId < b.casoId ? -1 : a.casoId > b.casoId ? 1 : 0,
  );
  const usados = new Set<Uuid>();
  const porEvento = new Map<bigint, Uuid>();
  const ordenados = [...duplicados].sort((a, b) =>
    a.eventId < b.eventId ? -1 : a.eventId > b.eventId ? 1 : 0,
  );
  for (const e of ordenados) {
    const caso = livres.find(
      (c) =>
        !usados.has(c.casoId) &&
        c.tenantId === e.tenantId &&
        c.chargeId === e.chargeId &&
        c.valorMinor === e.valorMinor,
    );
    if (caso === undefined) continue;
    usados.add(caso.casoId);
    porEvento.set(e.eventId, caso.casoId);
  }
  return porEvento;
}

/**
 * R-05: auto-compra — o HMAC do pagador coincide com o de quem e da casa.
 *
 * **Compara-se o `payer_hmac` da cobranca com o `phone_hmac` da casa**, e nao o
 * `contact_id`: um dono que pague com o telefone dele a uma cobranca cujo
 * cliente e outro `contact_id` passava por qualquer comparacao de
 * identificadores. E a razao de a coluna existir — a `0029` escreve-a por
 * extenso: «HMAC do msisdn Express do pagador (anti-auto-compra, §9)».
 *
 * A segunda metade do criterio 5 — o `contacts.phone_hmac` do cliente a
 * coincidir com o da casa — cobre o caminho manual, onde nao ha `payer_hmac`
 * nenhum: quem declara o pagamento e um contacto, e se o HMAC desse contacto e
 * o de um funcionario, e a mesma anomalia por outra porta.
 */
function _r05(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const hmacsDaCasa = new Map(foto.casa.map((c) => [c.phoneHmac, c.contactId]));
  const contactosDaCasa = new Set(foto.casa.map((c) => c.contactId));
  const saida: Sinal[] = [];
  for (const cobranca of foto.cobrancas) {
    // **A janela aplica-se, e nao se aplicava.** Ver o `_r03`: sem ela, cada
    // corrida do *job* re-emitia as auto-compras dos ultimos trinta dias.
    if (!_naJanela(cobranca.criadoEm, foto.agora, cfg.janelas["R-05"])) continue;
    const porHmac =
      cobranca.payerHmac !== null
        ? hmacsDaCasa.get(cobranca.payerHmac)
        : undefined;
    const porContacto =
      cobranca.contactId !== null && contactosDaCasa.has(cobranca.contactId)
        ? cobranca.contactId
        : undefined;
    const daCasa = porHmac ?? porContacto;
    if (daCasa === undefined) continue;
    // Uma coincidencia basta (limiar 1), e o limiar fica legivel em vez de
    // implicito: calibrar isto para 2 e dizer «uma auto-compra passa».
    if (cfg.limiares["R-05"] > 1) continue;
    saida.push(
      _sinal("R-05", {
        tenantId: cobranca.tenantId,
        chargeId: cobranca.chargeId,
        contactId: cobranca.contactId,
        detalhe: {
          account_id: cobranca.accountId,
          via: porHmac !== undefined ? "payer_hmac" : "phone_hmac",
          contacto_da_casa: daCasa,
          metodo: cobranca.metodo,
        },
      }),
    );
  }
  return saida;
}

/**
 * R-06: confirmacoes manuais da semana acima de k vezes a mediana do tenant.
 *
 * ## A mediana e **por contacto**, e sem ela a regra media a coisa errada
 *
 * O criterio 6 escreve «confirmacoes manuais por semana acima de k vezes a
 * mediana do tenant». A pergunta que fica e «mediana de que populacao», e a
 * resposta nao e indiferente: a mediana das **semanas** do tenant transforma um
 * tenant que cresce numa anomalia permanente, porque a semana corrente e sempre
 * acima da mediana historica. A populacao que o §4.6 do `docs/tecnica/08`
 * nomeia e o **contacto** — o risco e um comprador a juntar confirmacoes, que e
 * a mesma leitura que a `manual_janela` do KAM-054 ja tomou («o risco e um
 * comprador a juntar confirmacoes, nao um dono a confirmar as vendas dele»).
 *
 * Logo: conta-se por contacto dentro da janela, tira-se a mediana dessas
 * contagens, e marca-se quem esta acima de `k x mediana`.
 *
 * ## A regra precisa de TRES ou mais contactos activos, e isso e algebra
 *
 * **Esta nota dizia «um ou dois contactos» como se o dois funcionasse, e nao
 * funciona.** Com duas contagens `a <= x`, a mediana e `(a + x) / 2` e o corte e
 * `k (a + x) / 2`; disparar exige `x > k (a + x) / 2`, isto e
 * `x (2 - k) > k a`. Para **qualquer `k >= 2`** o lado esquerdo e `<= 0` e o
 * direito `>= 1`: a desigualdade e impossivel, por grande que seja o desvio —
 * `[1, 1000]` da mediana 500,5 e corte 1501,5. Com o `k = 3` proposto, um tenant
 * com **dois** contactos activos na semana tem esta regra estruturalmente
 * desligada.
 *
 * Com um contacto so, a mediana e a propria contagem dele e nada dispara
 * tambem. **Os dois casos sao o comportamento certo e nao um defeito**: uma
 * regra de desvio precisa de populacao para ter desvio, e inventar um piso fixo
 * era trocar a regra do criterio por outra. O que era defeito era esta nota
 * dizer o contrario — achado da revisao adversarial, que fez a algebra em vez de
 * reler a frase. O `PLANO_DE_CALIBRACAO` di-lo agora com o numero: **tres**
 * contactos activos, e doze semanas antes de a mediana decidir.
 */
function _r06(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const porTenant = new Map<string, Map<string, number>>();
  for (const c of foto.confirmacoes) {
    if (c.decisao !== "confirma") continue;
    if (!_naJanela(c.instante, foto.agora, cfg.janelas["R-06"])) continue;
    let contactos = porTenant.get(c.tenantId);
    if (contactos === undefined) {
      contactos = new Map();
      porTenant.set(c.tenantId, contactos);
    }
    contactos.set(c.contactId, (contactos.get(c.contactId) ?? 0) + 1);
  }
  const saida: Sinal[] = [];
  for (const [tenantId, contactos] of porTenant) {
    const mediana = _mediana([...contactos.values()]);
    if (mediana <= 0) continue;
    const corte = mediana * cfg.limiares["R-06"];
    for (const [contactId, contagem] of contactos) {
      if (contagem <= corte) continue;
      saida.push(
        _sinal("R-06", {
          tenantId,
          contactId,
          detalhe: {
            confirmacoes: contagem,
            mediana_do_tenant: mediana,
            k: cfg.limiares["R-06"],
            janela_horas: cfg.janelas["R-06"],
          },
        }),
      );
    }
  }
  return saida;
}

/** R-07: cobrancas `cod` do mesmo contacto terminadas sem pagamento. */
function _r07(foto: Fotografia, cfg: Configuracao): readonly Sinal[] {
  const porContacto = new Map<string, { tenantId: Uuid; contagem: number }>();
  for (const c of foto.cobrancas) {
    if (c.metodo !== "cod") continue;
    if (c.contactId === null) continue;
    if (!TERMINAIS_SEM_PAGAMENTO.includes(c.estado)) continue;
    // A janela, pela razao do `_r03`. Esta tambem era decoracao.
    if (!_naJanela(c.criadoEm, foto.agora, cfg.janelas["R-07"])) continue;
    const chave = `${c.tenantId}:${c.contactId}`;
    const actual = porContacto.get(chave);
    if (actual === undefined) {
      porContacto.set(chave, { tenantId: c.tenantId, contagem: 1 });
    } else {
      actual.contagem += 1;
    }
  }
  const saida: Sinal[] = [];
  for (const [chave, { tenantId, contagem }] of porContacto) {
    if (contagem < cfg.limiares["R-07"]) continue;
    const contactId = chave.slice(chave.indexOf(":") + 1);
    saida.push(
      _sinal("R-07", {
        tenantId,
        contactId,
        detalhe: {
          cobrancas_cod_sem_pagamento: contagem,
          limiar: cfg.limiares["R-07"],
          // A recomendacao vive no detalhe e nao na accao, porque «exigir
          // sinal por referencia» nao esta no dominio fechado do
          // `fraud_signals_accao_ck`. Ver o comentario do `REGRAS`.
          recomendacao: "exigir_sinal_por_referencia",
          credor_do_consumo: "KAM-097",
        },
      }),
    );
  }
  return saida;
}

/**
 * Os estados de `payment_charges` que sao fim de linha **sem** dinheiro.
 *
 * Nao e «tudo menos `paga`»: `iniciada`, `emitida`, `aguarda_cliente` e
 * `pendente_confirmacao` sao estados activos, e contá-los fazia da R-07 uma
 * contagem de cobrancas em curso. O `reembolsada` tambem nao entra — essa
 * **recebeu** dinheiro, e devolve-lo nao e um *no-show*.
 */
export const TERMINAIS_SEM_PAGAMENTO = ["expirada", "falhada", "cancelada"];

function _contactoDa(foto: Fotografia, chargeId: Uuid): Uuid | null {
  return (
    foto.cobrancas.find((c) => c.chargeId === chargeId)?.contactId ?? null
  );
}

/**
 * A idade em horas, **sem `Math` e sem `Number(`**.
 *
 * O `money_lint` recusa os arredondamentos de `Math` e as conversoes por
 * `float` neste directorio, e nao se pede dispensa: um `Math.floor` numa
 * travessia de dinheiro e o defeito que ele existe para apanhar, e a regra nao
 * sabe distinguir uma contagem de horas de um montante — nem tem de saber. A
 * divisao inteira faz-se tirando o resto primeiro, que e exacto para qualquer
 * inteiro nao negativo e nao passa por IEEE-754 nenhum.
 *
 * Arredonda para baixo: «aberto ha 23,9 h» nao e «aberto ha 24 h», e o criterio
 * 3 mede «orfaos abertos > 24 h».
 */
function _idadeEmHoras(instante: Instant, agora: Instant): number {
  const t = Date.parse(instante);
  const fim = Date.parse(agora);
  if (!Number.isFinite(t) || !Number.isFinite(fim)) return 0;
  const decorrido = fim - t;
  if (decorrido <= 0) return 0;
  return (decorrido - (decorrido % 3_600_000)) / 3_600_000;
}

/**
 * A mediana de uma lista de inteiros, por valor e nao por indice.
 *
 * Sem `Math.floor` e sem `as number`, pela razao do `_idadeEmHoras`: o
 * `money_lint` escreve que «num modulo de dinheiro **nao ha** `as number`
 * legitimo», e tem razao — o `?? 0` diz o mesmo e **nao mente** quando o indice
 * nao existe, que e a diferenca entre uma asercao e uma guarda.
 */
function _mediana(valores: readonly number[]): number {
  if (valores.length === 0) return 0;
  const ordenados = [...valores].sort((a, b) => a - b);
  const total = ordenados.length;
  const meio = (total - (total % 2)) / 2;
  if (total % 2 === 1) return ordenados[meio] ?? 0;
  // **A media dos dois do meio, e nao o de cima.** Com duas contagens de 1 e 9,
  // a mediana e 5 e nao 9 — e com 9 o corte `k x mediana` subia para 27, o que
  // deixava passar o desvio que a regra existe para ver.
  return ((ordenados[meio - 1] ?? 0) + (ordenados[meio] ?? 0)) / 2;
}

// ------------------------------------------------- reconciliacao (R-08)

/**
 * Uma linha do extracto bancario carregado pelo dono.
 *
 * ## O formato e **nosso** e nao de um banco, e isso e uma afirmacao com estado
 *
 * **NAO VERIFICADO**: nenhum anexo de evidencia deste conjunto fixa o formato de
 * extracto de um banco angolano, e o `docs/tecnica/evidencia/E2` nao responde a
 * pergunta. Logo o formato que este modulo le e uma **proposta** — quatro
 * colunas que o dono preenche, nao um CSV que um banco exporta — e a ingestao
 * de um formato real e trabalho de quem tiver o extracto a mao. O bloco ja o
 * diz do lado da API: «API do banco e Clusters e NAO VERIFICADA».
 */
export type LinhaDoExtracto = {
  /** A referencia Multicaixa, ou o que o dono escreveu na coluna dela. */
  readonly referencia: string;
  readonly valorMinor: Minor;
  /** A data-valor, em ISO. */
  readonly data: string;
};

/** O cabecalho que o CSV tem de ter, pela ordem. */
export const COLUNAS_DO_EXTRACTO = ["referencia", "valor_minor", "data"] as const;

/** O separador. Ponto e virgula, porque o Excel pt-PT usa a virgula decimal. */
export const SEPARADOR_DO_EXTRACTO = ";";

export class ExtractoIlegivel extends Error {
  override readonly name = "ExtractoIlegivel";

  constructor(linha: number, razao: string) {
    super(`a linha ${linha} do extracto nao se le: ${razao}`);
  }
}

/**
 * Le o CSV. **Levanta na primeira linha ilegivel**, e nao salta.
 *
 * Saltar uma linha ilegivel produzia uma reconciliacao que se declara completa
 * sobre um extracto que nao leu todo — isto e, a diferenca que a R-08 procura
 * passava a poder ser a linha que o parser deixou cair. Um extracto que nao se
 * le na totalidade nao se reconcilia em parte.
 */
export function lerExtracto(csv: string): readonly LinhaDoExtracto[] {
  const linhas = csv
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l !== "");
  if (linhas.length === 0) throw new ExtractoIlegivel(0, "o ficheiro esta vazio");
  const cabecalho = (linhas[0] as string)
    .split(SEPARADOR_DO_EXTRACTO)
    .map((c) => c.trim().toLowerCase());
  if (cabecalho.join(",") !== COLUNAS_DO_EXTRACTO.join(",")) {
    throw new ExtractoIlegivel(
      1,
      `o cabecalho tem de ser '${COLUNAS_DO_EXTRACTO.join(SEPARADOR_DO_EXTRACTO)}' ` +
        `e e '${cabecalho.join(SEPARADOR_DO_EXTRACTO)}'`,
    );
  }
  const saida: LinhaDoExtracto[] = [];
  for (let i = 1; i < linhas.length; i += 1) {
    const campos = (linhas[i] as string)
      .split(SEPARADOR_DO_EXTRACTO)
      .map((c) => c.trim());
    if (campos.length !== COLUNAS_DO_EXTRACTO.length) {
      throw new ExtractoIlegivel(
        i + 1,
        `tem ${campos.length} colunas e nao ${COLUNAS_DO_EXTRACTO.length}`,
      );
    }
    const [referencia, valor, data] = campos as [string, string, string];
    if (referencia === "") throw new ExtractoIlegivel(i + 1, "sem referencia");
    // **`/^-?\d+$/` e nao `Number()`.** Um `1.5` passava pelo `Number` e
    // truncava em silencio, e um valor truncado numa reconciliacao de dinheiro
    // e a classe de defeito que o `money_lint` existe para recusar. A unidade e
    // menor e inteira (dicionario §2): um ponto no valor e erro de quem o
    // escreveu.
    if (!/^-?\d+$/.test(valor)) {
      throw new ExtractoIlegivel(
        i + 1,
        `o valor '${valor}' nao e um inteiro em unidade menor`,
      );
    }
    if (Number.isNaN(Date.parse(data))) {
      throw new ExtractoIlegivel(i + 1, `a data '${data}' nao se le`);
    }
    saida.push({ referencia, valorMinor: BigInt(valor), data });
  }
  return saida;
}

/** O que a reconciliacao propoe: um `ajuste_reconciliacao` por diferenca. */
export type AjusteProposto = {
  readonly chargeId: Uuid | null;
  readonly tenantId: Uuid | null;
  /** A referencia, que e a chave natural da linha do extracto. */
  readonly referencia: string;
  /** A conta da cobranca, quando ha cobranca. A chave e `(conta, referencia)`. */
  readonly accountId: Uuid | null;
  /** O que o extracto diz menos o que a cobranca paga diz. Pode ser negativo. */
  readonly diferencaMinor: Minor;
  readonly motivo:
    | "sem_cobranca_paga"
    | "valor_diferente"
    | "paga_sem_extracto"
    /**
     * Uma cobranca `paga` de metodo `referencia` **sem** referencia.
     *
     * Era invisivel: o `porReferencia` so indexava as que tinham referencia, e
     * uma `paga` sem ela nunca produzia diferenca nenhuma — nem ajuste, nem
     * caso para ops, contra a letra do criterio 7. Achado da revisao
     * adversarial. Para o `cod` e para o `express_push` a ausencia e correcta (a
     * `0029` escreve que o `express_push` nao tem referencia), e por isso o
     * motivo e so para o metodo `referencia`.
     */
    | "paga_sem_referencia";
  /**
   * O `provider_event_id` do evento compensatorio, deterministico.
   *
   * **E o que torna a reconciliacao repetivel, e nao o que a torna idempotente
   * na base.** Medido: o indice unico de `provider_event_id` da revisao `0029`
   * e **parcial** —
   * `WHERE provider_event_id IS NOT NULL AND tipo_evento = 'pagamento_recebido'`
   * —, pelo que **nao cobre** o `ajuste_reconciliacao`. Logo a base nao recusa
   * um ajuste repetido, e quem o recusa e o `reconciliar`, lendo os ajustes que
   * ja existem. Um indice que o tornasse estrutural e uma revisao, e esta
   * declarado como caixa com credor na secao de verificacao do bloco.
   */
  readonly providerEventId: string;
};

/**
 * O digest de um lote de extracto, para o `detalhe` e para o registo de ops.
 *
 * Deriva do **conteudo normalizado** e nao do ficheiro: o mesmo extracto
 * gravado com CRLF noutra maquina tem bytes diferentes e e o mesmo extracto, e
 * um digest que os distinguisse fazia do «CSV repetido» do criterio 7 um caso
 * que nunca se reconhecia.
 */
export function digestDoLote(linhas: readonly LinhaDoExtracto[]): string {
  const normalizado = [...linhas]
    .map((l) => `${l.referencia}|${l.valorMinor}|${l.data}`)
    .sort()
    .join("\n");
  return createHash("sha256").update(normalizado, "utf8").digest("hex");
}

/**
 * Compara o extracto com as cobrancas `paga` e devolve os ajustes a escrever.
 *
 * As tres diferencas, e nenhuma delas e simetrica da outra:
 *
 *     sem_cobranca_paga   o extracto tem a linha e nao ha cobranca paga com
 *                         essa referencia: entrou dinheiro que nao fecha nada
 *     valor_diferente     ha cobranca paga, e o valor nao bate
 *     paga_sem_extracto   a cobranca esta `paga` e o extracto nao tem a linha:
 *                         confirmou-se um pagamento que o banco nao viu
 *
 * **Um CSV repetido nao duplica ajustes** (criterio 7), e quem o garante e o
 * `jaAjustados`: a leitura dos `provider_event_id` de `ajuste_reconciliacao` que
 * ja existem no *ledger*. Ver o `AjusteProposto.providerEventId` para a razao de
 * nao ser a base a recusar.
 */
export function reconciliar(entrada: {
  readonly linhas: readonly LinhaDoExtracto[];
  readonly cobrancas: readonly CobrancaObservada[];
  /** A referencia de cada cobranca. Vem do SQL, que a tem na coluna. */
  readonly referenciaPorCobranca: Readonly<Record<string, string>>;
  /** Os `provider_event_id` de `ajuste_reconciliacao` ja no ledger. */
  readonly jaAjustados: readonly string[];
}): readonly AjusteProposto[] {
  const lote = digestDoLote(entrada.linhas);
  const feitos = new Set(entrada.jaAjustados);
  const pagas = entrada.cobrancas.filter((c) => c.estado === "paga");

  // **A chave e `(conta, referencia)` e nao a referencia sozinha.** A `0029`
  // escreve-o: duas PMEs podem ter legitimamente a mesma referencia Multicaixa,
  // porque ela e Entidade + Referencia. Com a referencia sozinha, o `Map`
  // guardava **a ultima** e a outra cobranca desaparecia da reconciliacao — e
  // uma linha de extracto que batia exactamente com a primeira produzia um
  // ajuste falso atribuido ao tenant da segunda. Medido pela revisao
  // adversarial: um ajuste de 200 000 no tenant errado.
  const porChave = new Map<string, CobrancaObservada>();
  const semReferencia: CobrancaObservada[] = [];
  for (const c of pagas) {
    const referencia = entrada.referenciaPorCobranca[c.chargeId] ?? c.referencia;
    if (referencia === null || referencia === undefined || referencia === "") {
      // Ver o motivo `paga_sem_referencia`: so o metodo `referencia` e que a
      // devia ter.
      if (c.metodo === "referencia") semReferencia.push(c);
      continue;
    }
    porChave.set(_chave(c.accountId, referencia), c);
  }

  const propostos: AjusteProposto[] = [];
  const vistas = new Set<string>();
  for (const linha of entrada.linhas) {
    // **O extracto nao diz a conta**, e e por isso que a busca e por referencia
    // e depois se confirma a chave: um extracto e de uma conta bancaria, e as
    // cobrancas que ele reconcilia sao as da conta de pagamento dessa PME. Com
    // mais do que uma cobranca `paga` a mesma referencia em contas diferentes, a
    // linha e **ambigua** e nao se adivinha — produz-se `sem_cobranca_paga`, que
    // e o que manda a diferenca para ops em vez de a atribuir ao palpite.
    const candidatas = [...porChave].filter(
      ([chave]) => chave.endsWith(`|${linha.referencia}`),
    );
    if (candidatas.length !== 1) {
      propostos.push(
        _ajuste(lote, linha.referencia, "sem_cobranca_paga", linha.valorMinor, null),
      );
      continue;
    }
    const [chave, cobranca] = candidatas[0] as [string, CobrancaObservada];
    vistas.add(chave);
    const diferenca = linha.valorMinor - cobranca.amountMinor;
    if (diferenca !== 0n) {
      propostos.push(
        _ajuste(lote, linha.referencia, "valor_diferente", diferenca, cobranca),
      );
    }
  }
  for (const [chave, cobranca] of porChave) {
    if (vistas.has(chave)) continue;
    const referencia = chave.slice(chave.indexOf("|") + 1);
    propostos.push(
      _ajuste(lote, referencia, "paga_sem_extracto", -cobranca.amountMinor, cobranca),
    );
  }
  for (const cobranca of semReferencia) {
    propostos.push(
      _ajuste(lote, "", "paga_sem_referencia", -cobranca.amountMinor, cobranca),
    );
  }

  // **Desduplica dentro do lote, e nao so contra o que ja esta no ledger.** O
  // `jaAjustados` so olha para tras: duas linhas com a mesma referencia no
  // **mesmo** CSV produziam dois ajustes com o mesmo `provider_event_id` e
  // montantes diferentes, escritos os dois num *ledger* que nao se corrige — e
  // na passagem seguinte o `jaAjustados` calava os dois, pelo que o «um CSV
  // repetido nao duplica» ficava verdadeiro por acidente depois de a primeira
  // corrida ja ter duplicado. Achado da revisao adversarial.
  const porId = new Map<string, AjusteProposto>();
  for (const a of propostos) {
    if (feitos.has(a.providerEventId) || porId.has(a.providerEventId)) continue;
    porId.set(a.providerEventId, a);
  }
  return [...porId.values()].sort((a, b) =>
    a.providerEventId.localeCompare(b.providerEventId),
  );
}

/** A chave de reconciliacao: `conta|referencia`. Ver o `reconciliar`. */
function _chave(accountId: Uuid, referencia: string): string {
  return `${accountId}|${referencia}`;
}

/** O prefixo do `provider_event_id` de um ajuste. Identifica a origem. */
export const PREFIXO_DO_AJUSTE = "reconciliacao";

function _ajuste(
  lote: string,
  referencia: string,
  motivo: AjusteProposto["motivo"],
  diferencaMinor: Minor,
  cobranca: CobrancaObservada | null,
): AjusteProposto {
  return {
    chargeId: cobranca?.chargeId ?? null,
    tenantId: cobranca?.tenantId ?? null,
    accountId: cobranca?.accountId ?? null,
    referencia,
    diferencaMinor,
    motivo,
    // **O id leva um `digest` da chave e nao a referencia em claro**, e sao tres
    // defeitos fechados de uma vez, os tres achados da revisao adversarial:
    //
    //   1. a referencia e **texto que o dono escreveu no CSV**, e este id viaja
    //      para o `detalhe` do sinal — isto e, era a via por onde um telefone ou
    //      um nome entrava num `fraud_signals`, contra o criterio 8;
    //   2. o id era concatenacao por `:` com o campo do meio livre, pelo que uma
    //      referencia com `:` o tornava ambiguo e irreversivel;
    //   3. nao levava a conta, pelo que duas contas com a mesma referencia
    //      colidiam na chave de deduplicacao.
    //
    // O lote **e** o digest e nao a data: dois extractos carregados no mesmo dia
    // sao dois lotes, e o mesmo extracto carregado em dois dias e um.
    providerEventId:
      `${PREFIXO_DO_AJUSTE}:${lote.slice(0, 16)}` +
      `:${_digestDaChave(cobranca?.accountId ?? "", referencia)}:${motivo}`,
  };
}

/**
 * O digest da chave de reconciliacao, para o `provider_event_id`.
 *
 * Doze hexadecimais (48 bits) sobre `conta|referencia`. Nao e segredo nem
 * assinatura: e **opacidade** — o que se quer e que o id nao carregue o texto do
 * dono e nao tenha separador ambiguo. A reversibilidade nao faz falta porque
 * quem precisa de encontrar a linha tem o `chargeId` no ajuste, e para a linha
 * orfa o caso de ops leva a `referencia` no `AjusteProposto`, que **nao** vai
 * para o sinal.
 */
function _digestDaChave(accountId: string, referencia: string): string {
  return createHash("sha256")
    .update(`${accountId}\u0000${referencia}`, "utf8")
    .digest("hex")
    .slice(0, 12);
}

/** Os sinais da R-08, derivados dos ajustes. Um por diferenca. */
export function sinaisDaReconciliacao(
  ajustes: readonly AjusteProposto[],
): readonly Sinal[] {
  const sinais = _ordenar(
    ajustes
      // Sem tenant nao se escreve sinal: a coluna e `NOT NULL` com FK. Uma
      // linha de extracto que nao casa cobranca nenhuma nao tem tenant, e o
      // ajuste dela fica para o caso de ops — que e o que o criterio 7 pede
      // («um caso para ops»), e nao um sinal sem dono.
      .filter((a) => a.tenantId !== null)
      .map((a) =>
        _sinal("R-08", {
          tenantId: a.tenantId as Uuid,
          chargeId: a.chargeId,
          detalhe: {
            // **A `referencia` nao entra aqui**, e o `provider_event_id` leva o
            // digest dela e nao o texto: ver o `_ajuste`. O que ops precisa para
            // encontrar a linha e o `charge_id`, que esta na coluna.
            motivo: a.motivo,
            diferenca_minor: String(a.diferencaMinor),
            provider_event_id: a.providerEventId,
            account_id: a.accountId,
          },
        }),
      ),
  );
  // **A mesma guarda que o `avaliar` corre**, e e a correccao do unico achado
  // que bloqueava a fusao: estes sinais saiam por aqui e nao passavam por
  // guarda nenhuma, com o texto do CSV do dono dentro.
  _exigirSemPii(sinais);
  return sinais;
}

// ---------------------------------------------------------------- as accoes

/**
 * A accao mais forte entre os sinais abertos de um contacto.
 *
 * A ordem e a da escada do §9, e **nao** a ordem alfabetica nem a do `CHECK`:
 * reter e mais forte do que exigir a dupla, pela razao que o
 * `avaliarConfirmacao` do `manual.ts` ja escreveu — «uma cobranca que excede o
 * tecto diario nao se resolve com uma segunda assinatura, resolve-se com uma
 * pessoa de ops a olhar para ela».
 *
 * O `suspender_manual` e `bloquear_contacto` ficam acima dos dois, e nao sao
 * deste ticket: produzi-los e de KAM-097. Estao na ordem para que a reducao
 * continue correcta no dia em que ele os produzir, em vez de os deixar a
 * perder para um `registar`.
 */
export const FORCA_DA_ACCAO: Readonly<Record<Accao, number>> = Object.freeze({
  registar: 0,
  exigir_dupla: 1,
  reter_confirmacao: 2,
  bloquear_contacto: 3,
  suspender_manual: 4,
});

export function accaoEmVigor(sinais: readonly Sinal[]): Accao {
  let forte: Accao = "registar";
  for (const sinal of sinais) {
    if (FORCA_DA_ACCAO[sinal.accao] > FORCA_DA_ACCAO[forte]) forte = sinal.accao;
  }
  return forte;
}

/**
 * Aplica a accao em vigor ao veredicto do `ManualProvider`.
 *
 * ## Isto e composicao e nao cirurgia, e a escolha mediu-se
 *
 * O `avaliarConfirmacao` do `manual.ts` fica **byte a byte como estava**. A
 * alternativa era acrescentar um campo a `EntradaDaConfirmacao` e uma porta no
 * meio da cascata dele — e a cascata e a parte mais argumentada daquele ficheiro
 * («cada porta fechada antes da seguinte decide o que um atacante aprende»).
 * Pior: o oraculo em TypeScript e a `platform.manual_confirmar` tem de dizer o
 * mesmo, e um campo que a funcao da base nao conhece punha os dois a divergir —
 * que e o defeito que o KAM-054 passou tres revisoes a fechar.
 *
 * ## Uma rejeicao **continua** uma rejeicao
 *
 * E a propriedade que faz desta funcao uma barreira e nao um interruptor. Se um
 * `reter_confirmacao` transformasse um `rejeita` em `retem`, um valor declarado
 * errado passava a «retido para analise» — e o `manual.ts` escreve exactamente
 * porque e que isso nao pode acontecer: «um atacante que recebesse "retido para
 * analise" em vez de "o valor nao bate" aprendia que acertou no valor». A accao
 * so **endurece** um veredicto que ia deixar passar.
 */
export function respeitarAccao(
  veredicto: VeredictoDoManual,
  accao: Accao,
): VeredictoDoManual {
  if (veredicto.decisao === "rejeita") return veredicto;
  const endurecida = _endurecer(veredicto, accao);
  if (endurecida === veredicto.decisao) return veredicto;
  return {
    ...veredicto,
    decisao: endurecida,
    // **O `motivo` e a `regra` passam a ser os da anomalia**, e nao e arrumacao:
    // a primeira versao preservava os do veredicto de origem com o `...`, e a
    // revisao adversarial mediu o que isso produzia — um `retem` com
    // `regra: "M-5"` e `motivo: null`, quando o M-5 e a dupla verificacao e
    // **nunca** retem. Quem le a linha de `manual_confirmations` lia que a
    // retencao veio de uma regra que nao retem.
    //
    // O `motivo` fica `null` de proposito: os `MotivoManual` sao um dominio
    // fechado do M-1 ao M-5 e nenhum deles descreve «foi uma anomalia», e
    // inventar um valor novo era alargar aquele tipo a partir daqui. Quem diz o
    // que aconteceu e o `sinal`, que leva a regra — e e por isso que ele deixa
    // de poder ser `null` quando a decisao mudou.
    motivo: null,
    regra: null,
    sinal: _regraDaAccao(accao),
  };
}

/**
 * A decisao endurecida, ou a mesma.
 *
 * **Recebe o veredicto inteiro e nao so a decisao**, e a razao e a `fase`: um
 * `exigir_dupla` sobre um `confirma` que ja esta em `segunda_aprovacao` pedia
 * uma segunda assinatura que **ja foi dada** — isto e, a cobranca nunca se
 * confirmava enquanto o sinal da R-06 estivesse na janela, e a `fase` ficava a
 * dizer `segunda_aprovacao` ao lado de uma decisao a pedir a segunda. Era um
 * impasse num caminho de dinheiro, e foi achado da revisao adversarial.
 *
 * A `fase` e o marcador porque o veredicto nao leva o `primeiraAprovacaoDe`: o
 * `avaliarConfirmacao` poe `fase: "segunda_aprovacao"` exactamente quando a
 * primeira ja existe.
 */
function _endurecer(veredicto: VeredictoDoManual, accao: Accao): DecisaoDoManual {
  const decisao = veredicto.decisao;
  if (
    accao === "reter_confirmacao" ||
    accao === "suspender_manual" ||
    accao === "bloquear_contacto"
  ) {
    return "retem";
  }
  if (
    accao === "exigir_dupla" &&
    decisao === "confirma" &&
    veredicto.fase !== "segunda_aprovacao"
  ) {
    return "exige_segunda";
  }
  return decisao;
}

/**
 * A regra que justifica a accao, para a coluna `fraud_signals.regra`.
 *
 * **O `ACCAO_SEM_REGRA_DESTE_TICKET` nao e enchimento.** O `REGRAS` deste ticket
 * nao tem nenhuma regra com `bloquear_contacto` nem com `suspender_manual` —
 * essas acções sao produzidas pelo KAM-097 —, pelo que a busca devolvia
 * `undefined` e o veredicto saia com `sinal: null` a dizer `retem`. O tipo
 * documenta o contrario («a regra de `fraud_signals`, quando a decisao e
 * `retem`»), e um `retem` anonimo e exactamente o que ops nao consegue atender.
 * Hoje e inalcancavel; no dia em que o KAM-097 produzir aquelas acções, deixa de
 * o ser — e e para esse dia que o `FORCA_DA_ACCAO` ja as inclui.
 */
export const ACCAO_SEM_REGRA_DESTE_TICKET = "accao_de_sancao_kam_097";

function _regraDaAccao(accao: Accao): string {
  return REGRAS.find((r) => r.accao === accao)?.regra ?? ACCAO_SEM_REGRA_DESTE_TICKET;
}

/**
 * A decisão de uma confirmação manual **com** as anomalias do contacto.
 *
 * É a ligação que o critério 5 pede («o `ManualProvider` respeita a acção: a
 * confirmação fica retida até ops») e é uma função só, de propósito: quem chama
 * não pode esquecer-se de aplicar a acção, porque não há por onde chamar o
 * `avaliarConfirmacao` *e* esquecer o `respeitarAccao` sem voltar a escrever
 * esta composição à mão.
 *
 * `sinaisAbertos` são os sinais **deste contacto** que ainda não foram fechados
 * por ops. Filtrá-los é de quem lê a base; esta função não decide o que está
 * aberto, pela razão de sempre: assim mantém-se pura e com ensaio sem base.
 */
export function decidirConfirmacao(
  entrada: EntradaDaConfirmacao,
  sinaisAbertos: readonly Sinal[],
): VeredictoDoManual {
  return respeitarAccao(avaliarConfirmacao(entrada), accaoEmVigor(sinaisAbertos));
}

// -------------------------------------------------------------- as leituras

/**
 * Os eventos do *ledger* que o motor le, numa janela.
 *
 * `coalesce(ocorrido_at, recebido_at)` porque o `ocorrido_at` e anulavel na
 * `0029` e um evento sem ele continua a ter de datar: um `null` caia fora de
 * todas as janelas e a regra deixava de o ver.
 */
export const SQL_ANOMALIAS_EVENTOS = `
  SELECT id, tenant_id, charge_id, account_id, tipo_evento, sequencia,
         valor_minor, coalesce(ocorrido_at, recebido_at) AS instante
    FROM platform.payment_events
   WHERE tipo_evento = ANY($1)
     AND coalesce(ocorrido_at, recebido_at) >= $2
   ORDER BY id
`;

/**
 * As cobrancas no horizonte, com o `payer_hmac` em hexadecimal.
 *
 * O `encode(..., 'hex')` nao e conveniencia: ver o `CobrancaObservada.payerHmac`
 * — dois `Uint8Array` iguais nao sao `===`, e a R-05 compara-os.
 */
export const SQL_ANOMALIAS_COBRANCAS = `
  SELECT c.id, c.tenant_id, c.account_id, c.order_id, c.estado, c.metodo,
         c.amount_minor, c.referencia, c.criado_at,
         encode(c.payer_hmac, 'hex') AS payer_hmac,
         o.contact_id
    FROM platform.payment_charges c
    LEFT JOIN platform.orders_mirror o
      ON o.tenant_id = c.tenant_id AND o.id = c.order_id
   WHERE c.criado_at >= $1
   ORDER BY c.id
`;

/** As confirmacoes manuais da janela (R-05 e R-06). */
export const SQL_ANOMALIAS_CONFIRMACOES = `
  SELECT charge_id, tenant_id, actor_contact_id, decisao, criado_at
    FROM platform.manual_confirmations
   WHERE criado_at >= $1
   ORDER BY id
`;

/**
 * Os callbacks recusados por assinatura (R-02, F-05).
 *
 * **Sem `tenant_id`**, e nao e omissao: a `payment_inbox` da `0029` nao tem
 * nenhum, porque um callback forjado chega antes de se saber de quem e. O tenant
 * deriva da conta — ver o `_r02`.
 */
export const SQL_ANOMALIAS_RECUSAS = `
  SELECT account_id, recebido_at
    FROM platform.payment_inbox
   WHERE estado = 'hmac_invalido'
     AND account_id IS NOT NULL
     AND recebido_at >= $1
   ORDER BY id
`;

/**
 * Quem e da casa de um tenant: os confirmadores, por HMAC de telefone.
 *
 * A populacao e a `payment_confirmers` do KAM-054 — «o dono ou funcionarios», a
 * letra do criterio 5 — e nao uma lista a parte. Um HMAC nulo nao entra: sem
 * HMAC nao ha comparacao a fazer, e um `null` igual a outro `null` punha dois
 * contactos sem telefone a parecer a mesma pessoa.
 */
export const SQL_ANOMALIAS_CASA = `
  SELECT f.contact_id, encode(c.phone_hmac, 'hex') AS phone_hmac
    FROM platform.payment_confirmers f
    JOIN platform.contacts c ON c.contact_id = f.contact_id
   WHERE f.tenant_id = $1 AND f.ativo AND c.phone_hmac IS NOT NULL
   ORDER BY f.contact_id
`;

/**
 * A chamada a porta de escrita dos sinais.
 *
 * **E a unica cadeia deste ficheiro que escreve**, e escreve **por funcao**: a
 * `platform.fraud_signals` nao tem `INSERT` para papel nenhum, por decisao da
 * revisao `0032` («quem e vigiado escrevia no registo de vigilancia»). Quem a
 * concede e a revisao do escritor, e so ao `kamba_batch` — o motor corre em
 * lote, nao num turno de conversa.
 *
 * Devolve o `id`, que pode ser o de um sinal **que ja existia**: a guarda de
 * janela da funcao nao repete a mesma anomalia a cada corrida do *job*.
 *
 * Nao entra no `CADEIAS_DAS_ANOMALIAS` porque aquela lista e das **leituras**
 * da fotografia, e o ensaio que a varre exige que cada uma comece por `SELECT` —
 * ela e que impoe a caixa do DoD «o motor nunca escreve `paga`». Esta cadeia tem
 * a sua propria lista, com o seu proprio varrimento.
 */
export const SQL_REGISTAR_SINAL = `
  SELECT platform.registar_sinal_de_anomalia(
    p_tenant_id => $1, p_regra => $2, p_severidade => $3, p_accao => $4,
    p_contact_id => $5, p_charge_id => $6, p_detalhe => $7::jsonb,
    p_janela => $8::interval) AS id
`;

/** As cadeias de **escrita** deste modulo. Uma, e e uma chamada de funcao. */
export const CADEIAS_DE_ESCRITA = ["SQL_REGISTAR_SINAL"] as const;

/** Os `provider_event_id` dos ajustes ja escritos (criterio 7). */
export const SQL_ANOMALIAS_AJUSTES_FEITOS = `
  SELECT provider_event_id
    FROM platform.payment_events
   WHERE tipo_evento = 'ajuste_reconciliacao'
     AND provider_event_id IS NOT NULL
   ORDER BY id
`;

/**
 * As cadeias que a suite de base de dados exercita **deste ficheiro**.
 *
 * E o padrao do `hooks.ts` e do `manual.ts`: a suite importa o modulo e corre o
 * texto que ele envia, em vez de uma copia que envelhece sozinha.
 */
export const CADEIAS_DAS_ANOMALIAS = [
  "SQL_ANOMALIAS_EVENTOS",
  "SQL_ANOMALIAS_COBRANCAS",
  "SQL_ANOMALIAS_CONFIRMACOES",
  "SQL_ANOMALIAS_RECUSAS",
  "SQL_ANOMALIAS_CASA",
  "SQL_ANOMALIAS_AJUSTES_FEITOS",
  "SQL_ANOMALIAS_REEMBOLSOS",
] as const;

/**
 * Os casos de reembolso de duplicado que o PAY abriu, por cobranca (KAM-197).
 *
 * O caso e da **encomenda** e o duplicado e da **cobranca**: a juncao pela
 * encomenda devolve uma linha por cobranca dela, e o `_casosPorDuplicado` do
 * motor gasta cada caso uma vez so. **So os do consumidor** (`pedido_evento_id`
 * preenchido): um caso da `manual_reverter` e uma reversao, nao a resposta a um
 * duplicado. A chave de ordenacao e total, pela razao do criterio 9.
 */
export const SQL_ANOMALIAS_REEMBOLSOS = `
  SELECT r.id, r.tenant_id, c.id AS charge_id, r.valor_minor
    FROM platform.refund_cases r
    JOIN platform.payment_charges c
      ON c.tenant_id = r.tenant_id AND c.order_id = r.order_id
   WHERE r.motivo = 'pagamento_duplicado'
     AND r.pedido_evento_id IS NOT NULL
     AND r.criado_at >= $1
   ORDER BY r.id, c.id
`;

// ------------------------------------------------------------------- o job

/** Os alertas que este motor levanta. Nomes de `ops/metricas/catalogo.yaml`. */
export const ALERTA_DE_SINAL = "pay_fraude_sinal_severo";
export const ALERTA_DE_ORFAO = "pay_fraude_orfao_aberto";
export const ALERTA_DE_ESCRITA = "pay_fraude_sinal_nao_persistido";

/**
 * A contagem de um sinal falhou. **E diferente dos outros tres**, e a diferenca
 * e quem fica sem saber: eles dizem «ha uma anomalia», e este diz «a anomalia
 * esta la e a serie do painel nao a tem». Confundi-los era o pior dos dois
 * mundos — uma deteccao que correu a parecer uma que nao correu.
 */
export const ALERTA_DE_CONTAGEM = "pay_fraude_contagem_falhou";

/** A severidade a partir da qual ops e alertado. O criterio 2 pede >= 3. */
export const SEVERIDADE_QUE_ALERTA: Severidade = 3;

/** Quantas horas um orfao pode estar aberto antes de alertar (criterio 3). */
export const HORAS_DE_ORFAO_TOLERADAS = 24;

/** A porta que le a fotografia. Uma leitura, para o determinismo. */
export type LeituraDeAnomalias = {
  fotografar(): Promise<Fotografia>;
};

/**
 * A porta que persiste os sinais.
 *
 * A implementacao vive em `services/com/src/payments/anomalias.ts` e chama a
 * `platform.registar_sinal_de_anomalia` pelo `SQL_REGISTAR_SINAL`. Fica atras de
 * uma porta e nao em linha para que o motor continue a correr sem ligacao
 * nenhuma — e para que o `detectarAnomalias` possa dizer, no relatorio, que os
 * sinais foram calculados e **nao** persistidos, que e informacao ao contrario
 * de um silencio.
 *
 * **O `persistidos` pode ser menor do que os sinais, e nao e erro:** a guarda de
 * janela da funcao devolve o `id` de um sinal que ja existia em vez de escrever
 * linha nova, pelo que uma corrida sobre uma anomalia que continua aberta
 * escreve zero linhas e esta correcta.
 *
 * **O metodo chama-se `persistir` e nao `registar`**, e nao e gosto: a regra
 * `registar_directo` do `tools/log_policy` recusa qualquer `.registar(…)` em
 * codigo de servico, porque e a porta sem tipos do *logger* — e a regra e
 * lexical, pelo que nao distingue uma porta de persistencia de uma de registo.
 * Nem tem de distinguir: o nome que nao colide e mais claro.
 */
export type EscritaDeSinais = {
  persistir(sinais: readonly Sinal[]): Promise<number>;
};

export type DependenciasDoMotor = {
  readonly leitura: LeituraDeAnomalias;
  /** Ausente enquanto nao houver escritor. Ver a `EscritaDeSinais`. */
  readonly escrita?: EscritaDeSinais | undefined;
  readonly configuracao?: Configuracao | undefined;
  alertar?(alerta: string, detalhe: Record<string, unknown>): void;
  /** Chamado por sinal, para a metrica `fraud_signals_total{regra}`. */
  contar?(regra: string): void;
};

/**
 * O que o motor devolve.
 *
 * **Nao lanca com sinais por persistir**, e e a mesma escolha do
 * `verificarLedgerDiariamente` do `ledger.ts`, com a mesma razao: lancar perdia
 * a parte que correu bem — os sinais calculados, os alertas e a metrica —, e um
 * motor que nao corre porque a escrita nao existe e pior do que um motor que
 * corre e diz que nao escreveu.
 */
export type RelatorioDeAnomalias = {
  readonly sinais: readonly Sinal[];
  /** Quantos ficaram na base. `null` quando nao ha escritor ligado. */
  readonly persistidos: number | null;
  readonly orfaosAbertos: number;
  readonly conforme: boolean;
};

/**
 * Corre o motor: fotografa, avalia, conta, alerta, persiste se houver com quem.
 *
 * A ordem e: avaliar, **contar e alertar**, persistir. Alertar vem antes de
 * persistir pela razao do `ledger.ts`: o alerta tem valor independente do
 * resultado da escrita, e deixá-lo depender dela fazia uma anomalia de dinheiro
 * desaparecer porque um `INSERT` falhou.
 */
export async function detectarAnomalias(
  deps: DependenciasDoMotor,
): Promise<RelatorioDeAnomalias> {
  const foto = await deps.leitura.fotografar();
  const sinais = avaliar(foto, deps.configuracao ?? CONFIGURACAO_PROPOSTA);

  // **A contagem nao mata a deteccao**, e a guarda e deliberada. O `contar` do
  // `services/com` levanta `RegraDesconhecida` por desenho — para nao abrir a
  // cardinalidade da etiqueta —, e sem este `try` uma regra fora do inventario
  // abortava a corrida **antes** dos alertas. A ordem deste ficheiro foi escrita
  // para o contrario («alertar vem antes de persistir … deixa-lo depender dela
  // fazia uma anomalia de dinheiro desaparecer»), e uma falha de
  // **observabilidade** a matar a **deteccao** inverte-a. Achado da revisao
  // adversarial, inalcancavel hoje e inalcancavel por acidente amanha.
  for (const sinal of sinais) {
    try {
      deps.contar?.(sinal.regra);
    } catch (erro) {
      deps.alertar?.(ALERTA_DE_CONTAGEM, {
        regra: sinal.regra,
        erro: erro instanceof Error ? erro.message : String(erro),
      });
    }
  }

  const severos = sinais.filter((s) => s.severidade >= SEVERIDADE_QUE_ALERTA);
  if (severos.length > 0) {
    deps.alertar?.(ALERTA_DE_SINAL, {
      sinais: severos.length,
      // O primeiro basta para ops abrir o caso; a lista inteira vai no
      // relatorio. E a nota do `ledger.ts`: um alerta com mil elos e um alerta
      // que ninguem le.
      primeiro: severos[0],
    });
  }

  // **`typeof` e nao `Number(`**, pela razao do `_idadeEmHoras`: o `money_lint`
  // recusa a conversao, e a guarda de tipo e mais honesta do que ela — um
  // `idade_horas` que chegasse como cadeia era um defeito do `_r03` e nao um
  // valor a converter, e o `Number(` escondia-o.
  const orfaosAbertos = sinais.filter((s) => {
    if (s.regra !== REGRA_POR_ID["R-03"].regra) return false;
    const idade = s.detalhe["idade_horas"];
    return typeof idade === "number" && idade > HORAS_DE_ORFAO_TOLERADAS;
  }).length;
  if (orfaosAbertos > 0) {
    deps.alertar?.(ALERTA_DE_ORFAO, { orfaos: orfaosAbertos });
  }

  let persistidos: number | null = null;
  if (deps.escrita === undefined) {
    if (sinais.length > 0) {
      deps.alertar?.(ALERTA_DE_ESCRITA, {
        sinais: sinais.length,
        razao:
          "fraud_signals e SELECT-only para kamba_app, kamba_batch e auditoria " +
          "(revisao 0032): falta a funcao SECURITY DEFINER que os escreva",
      });
    }
  } else {
    persistidos = await deps.escrita.persistir(sinais);
  }

  return {
    sinais,
    persistidos,
    orfaosAbertos,
    // `conforme` e «nao ha anomalia», e nao «o motor correu». Um motor que
    // corre e encontra oito duplicados correu bem e o estado nao esta conforme.
    conforme: sinais.length === 0,
  };
}

/**
 * As verificacoes de arranque G-2 e G-4 (KAM-052, criterios 3 e 6).
 *
 * As guardas tecnicas do `docs/tecnica/04` §10.4 sao o que «torna o desenho A
 * verificavel» — isto e, o que faz da afirmacao «a plataforma nao detem fundos»
 * (ADR-004) uma propriedade medida em vez de uma intencao escrita. Duas delas
 * sao de **arranque**, e e por isso que vivem aqui e nao num teste:
 *
 *     G-2   sem `payout`/`refund` automaticos. A *feature flag* `payouts_enabled`
 *           **exige** adaptador marcado `psp_licenciado`
 *     G-4   nenhuma `payment_account` de `pme` aponta para uma entidade EMIS da
 *           KAMBA
 *
 * **Lanca, e nao devolve.** Um arranque que continua depois de a guarda falhar
 * e um servico a correr sem a guarda, que e pior do que nao a ter: cria a
 * aparencia de verificacao. O §10.4 escreve «verificacao de configuracao em
 * CI/arranque», e arranque significa que o processo nao fica de pe.
 *
 * ## Porque e que a G-4 precisa de um controlo positivo
 *
 * A lista de entidades EMIS da KAMBA esta **vazia** hoje, e isso nao e um
 * descuido: o `entidade`, o `pos_id` e o `iec` sao identificadores que o banco
 * e a EMIS emitem, a KAMBA ainda nao os tem, e o prazo e os requisitos
 * bancarios para os obter sao **NAO VERIFICADO** (D4, KAM-103). Com a lista
 * vazia a G-4 passa sempre — e um zero que nao diz nada, que e exactamente o
 * modo de falha que o `canon_lint` aprendeu a nomear («uma superficie com zero
 * ficheiros passa sempre»).
 *
 * Por isso a lista e um **parametro** e nao uma constante lida aqui dentro, e
 * por isso ha um ensaio que a enche e afirma que a guarda morde. O zero da
 * producao fica a valer o que vale — nada —, e a guarda fica provada.
 */

import type { EstadoDaConta } from "./estados.ts";
import type { RegistoDeProviders } from "./registo.ts";
import type { Uuid } from "./tipos.ts";

export const PAYOUTS_SEM_PSP_LICENCIADO = "PAYOUTS_SEM_PSP_LICENCIADO";
export const CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA = "CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA";

export type CodigoDeArranque =
  | typeof PAYOUTS_SEM_PSP_LICENCIADO
  | typeof CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA;

export class ArranqueRecusado extends Error {
  readonly codigo: CodigoDeArranque;
  constructor(codigo: CodigoDeArranque, mensagem: string) {
    super(mensagem);
    this.name = "ArranqueRecusado";
    this.codigo = codigo;
  }
}

/**
 * As *feature flags* de dinheiro da G-2 e do §11.1.
 *
 * `commission_enabled` entra aqui por estar na mesma linha de decisao — o §11.1
 * poe a comissao em «modo sombra» com a *flag* desligada global e por tenant —
 * mas **nao tem verificacao de arranque neste ticket**: quem a calcula e o
 * KAM-058, e uma guarda sobre uma *flag* que nenhum codigo le seria cerimonia.
 * Esta declarada para que o nome exista uma vez so.
 */
export type FlagsDeDinheiro = {
  /** G-2. A omissao e `false`, e mudar isto exige um `psp_licenciado`. */
  readonly payoutsEnabled: boolean;
  /** §11.1. Desligada no Piloto; activar exige parecer (D8). */
  readonly commissionEnabled: boolean;
};

/** As omissoes, que sao as do §10.4 e do §11.1: as duas desligadas. */
export const FLAGS_OMISSAO: FlagsDeDinheiro = {
  payoutsEnabled: false,
  commissionEnabled: false,
};

/**
 * G-2: `payouts_enabled=true` exige um adaptador `psp_licenciado`.
 *
 * O §10.4 linha C diz que payouts a terceiros pela plataforma sao «execucao de
 * operacoes de pagamento/remessa: regulado», e que a alternativa e «parceiro
 * PSP executa com conta da PME». Um `payouts_enabled=true` sem parceiro
 * licenciado no registo e, portanto, a plataforma a preparar-se para fazer
 * sozinha o que o Aviso n.º 2/22 nao lhe permite — **(a confirmar por
 * parecer)**, como todo o jurídico deste conjunto, e por isso a guarda e
 * tecnica e nao uma nota.
 *
 * Nenhum adaptador do catalogo do §3.2 esta marcado `psp_licenciado` hoje, pelo
 * que esta verificacao **recusa sempre** com a *flag* ligada. E o pretendido.
 */
export function verificarG2(flags: FlagsDeDinheiro, registo: RegistoDeProviders): void {
  if (!flags.payoutsEnabled) return;
  if (registo.temPspLicenciado) return;
  throw new ArranqueRecusado(
    PAYOUTS_SEM_PSP_LICENCIADO,
    "payouts_enabled=true sem nenhum adaptador marcado psp_licenciado. " +
      "A plataforma nao executa operacoes de pagamento (ADR-004; " +
      "docs/tecnica/04 §10.4, linha C: payouts a terceiros pela plataforma " +
      "sao actividade regulada). A unica via admitida e um parceiro PSP " +
      "licenciado a executar a partir da conta da PME. " +
      `Adaptadores registados: ${registo.ids.join(", ") || "nenhum"}.`,
  );
}

/** A forma de uma `payment_accounts` para efeitos das guardas de arranque. */
export type ContaParaGuarda = {
  readonly id: Uuid;
  /** O dominio do dicionario §3.4: `pme` ou `plataforma_receita_propria`. */
  readonly beneficiaryKind: "pme" | "plataforma_receita_propria";
  readonly tenantId: Uuid | null;
  readonly estado: EstadoDaConta;
  readonly entidade: string | null;
  readonly posId: string | null;
  readonly iec: string | null;
};

/**
 * Os identificadores EMIS que sao da KAMBA e nao de uma PME.
 *
 * Os tres campos existem em separado e nao numa lista so porque sao
 * identificadores **diferentes** de servicos diferentes (§10.2): o `entidade` e
 * para referencias, o `pos_id` para GPO/Express e o `iec` para debito directo.
 * Uma PME pode ter um e nao outro, e confundi-los faria a guarda comparar um
 * POSID com uma Entidade e nao acusar nada.
 */
export type EntidadesDaKamba = {
  readonly entidades: readonly string[];
  readonly posIds: readonly string[];
  readonly iecs: readonly string[];
};

/**
 * A configuracao de producao: **vazia**, e o estado e NAO VERIFICADO.
 *
 * Espelha `config/kamba_emis.yaml`, que e o que uma pessoa le e onde o estado de
 * verificacao esta escrito ao lado. As duas fontes nao divergem por acidente: o
 * `pagamentos.arranque.test.ts` compara-as **como texto**, que e o mesmo
 * desenho que o `outbound/tarifas.ts` usa para as tarifas da Meta e pela mesma
 * razao escrita la — nao ha leitor de YAML em `packages/core-ts`, e acrescentar
 * um era trazer uma dependencia de terceiros ao caminho de producao.
 */
export const ENTIDADES_DA_KAMBA: EntidadesDaKamba = {
  entidades: [],
  posIds: [],
  iecs: [],
};

/**
 * G-4: nenhuma conta de `pme` aponta para uma entidade EMIS da KAMBA.
 *
 * O que isto impede, em concreto: uma venda de uma PME a liquidar na conta da
 * KAMBA. Seria o desenho B do §10.4 — «plataforma como comerciante unico que
 * recebe e repassa» —, que e **Nao** por ADR-004 e que aproxima a plataforma de
 * sub-adquirente (art. 3, aa), com autorizacao do BNA, segregacao e KYC/AML.
 *
 * As contas de `plataforma_receita_propria` sao **o uso legitimo** desses
 * identificadores: e com eles que a KAMBA cobra a assinatura as PMEs (§11.2),
 * que e a razao de a coluna `beneficiary_kind` existir. Por isso a guarda olha
 * so para as de `pme`.
 */
export function verificarG4(
  contas: readonly ContaParaGuarda[],
  daKamba: EntidadesDaKamba = ENTIDADES_DA_KAMBA,
): void {
  const achados: string[] = [];
  for (const conta of contas) {
    if (conta.beneficiaryKind !== "pme") continue;
    const colisoes: string[] = [];
    if (conta.entidade !== null && daKamba.entidades.includes(conta.entidade)) {
      colisoes.push(`entidade='${conta.entidade}'`);
    }
    if (conta.posId !== null && daKamba.posIds.includes(conta.posId)) {
      colisoes.push(`pos_id='${conta.posId}'`);
    }
    if (conta.iec !== null && daKamba.iecs.includes(conta.iec)) {
      colisoes.push(`iec='${conta.iec}'`);
    }
    if (colisoes.length > 0) {
      achados.push(`conta ${conta.id} (tenant ${conta.tenantId ?? "nulo"}): ${colisoes.join(", ")}`);
    }
  }
  if (achados.length === 0) return;
  throw new ArranqueRecusado(
    CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA,
    "ha contas de pme a apontar para identificadores EMIS da KAMBA, o que " +
      "poria uma venda de uma PME a liquidar na conta da plataforma " +
      "(docs/tecnica/04 §10.4, G-4; desenho B e recusado por ADR-004). " +
      `Achados: ${achados.join("; ")}.`,
  );
}

/** As duas guardas de arranque, pela ordem em que custam. */
export function verificarArranque(
  flags: FlagsDeDinheiro,
  registo: RegistoDeProviders,
  contas: readonly ContaParaGuarda[],
  daKamba: EntidadesDaKamba = ENTIDADES_DA_KAMBA,
): void {
  verificarG2(flags, registo);
  verificarG4(contas, daKamba);
}

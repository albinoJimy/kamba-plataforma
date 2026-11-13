/**
 * Billing da plataforma: a KAMBÁ cobra a assinatura às PMEs com a mesma
 * interface (KAM-059; `docs/tecnica/04` §11).
 *
 * As barreiras vivem na revisão do KAM-059 e não aqui, pela razão que o KAM-053
 * escreveu para o ledger: uma regra de dinheiro que dependesse de código de
 * aplicação não era uma regra. O que a base impõe:
 *
 *     1 ciclo por período        `billing_cycles_periodo_uq`
 *     1 cobrança por tentativa   `payment_charges_billing_tentativa_uq` (0029)
 *     conta da KAMBÁ             o `assert_beneficiary` (G-1, 0027)
 *     `paga` só pelo ledger      o *trigger* `billing_cycles_transicao`
 *     só sombra                  `commission_accruals_so_sombra`
 *
 * O que fica aqui é o que se quer medir sem um PostgreSQL — o período, o preço
 * em vigor, a validade de 72 h, o cálculo da sombra — e o *job* de abertura,
 * que é a composição do SQL abaixo com uma ligação recebida por argumento.
 *
 * ## Mora em `pagamentos/` e não em `services/pay/`
 *
 * O bloco escreve `services/pay/src/billing/{cycles,price_book,accruals}.ts`, e
 * `services/pay/` não existe — é a mesma divergência que o `index.ts` deste
 * directório regista para o KAM-052 (dívida documental 148). Um ficheiro e não
 * três, porque os três são o mesmo ciclo e o `ci/thresholds.yaml` já põe este
 * directório no estrato `critico`.
 *
 * ## O que este módulo **não** faz
 *
 * * **Não emite documento fiscal nenhum** (DP 71/25; D7; C-04). A porta
 *   `InvoiceProvider` está declarada abaixo como gancho e não tem
 *   implementação: é Clusters. A factura-recibo da assinatura é, no Piloto, um
 *   processo manual com software certificado pela AGT — ver o bloco.
 * * **Não decide preços nem o mapa plano → módulos.** São decisão de produto;
 *   vivem em dados (`price_book`, `registry/plans.yaml`) e não em constantes.
 * * **Não corre a régua** (D+3/D+7/D+10): é o KAM-058.
 */

import type { ClienteSql } from "../eventos/publicador.ts";
import type { Minor, Uuid } from "./tipos.ts";

/** Os estados de `billing_cycles.estado` (`docs/tecnica/04` §11.2). */
export const ESTADOS_DO_CICLO = [
  "aberto",
  "cobranca_emitida",
  "paga",
  "em_atraso",
  "anulado",
] as const;
export type EstadoDoCiclo = (typeof ESTADOS_DO_CICLO)[number];

/** Os estados de `subscriptions.estado` (§11.2). */
export const ESTADOS_DA_SUBSCRICAO = ["ativa", "em_atraso", "suspensa", "cancelada"] as const;
export type EstadoDaSubscricao = (typeof ESTADOS_DA_SUBSCRICAO)[number];

/**
 * As subscrições que **abrem ciclo**: `ativa` e `em_atraso`.
 *
 * `em_atraso` abre, e não é distracção: a PME em atraso continua com os
 * limites até a régua a suspender (critério 8), e continua a dever o mês
 * seguinte. `suspensa` e `cancelada` não abrem — uma conta suspensa não usa o
 * serviço, e cobrar-lhe o período era facturar o que não se prestou.
 */
export const ESTADOS_QUE_ABREM_CICLO: readonly EstadoDaSubscricao[] = ["ativa", "em_atraso"];

/** `commission_accruals.modo` (§11.2). A base só aceita o primeiro. */
export const MODOS_DA_COMISSAO = ["sombra", "facturavel"] as const;

/**
 * A validade da cobrança do ciclo: **72 h** (§11.2: «`referencia`, validade
 * 72 h»; critério 2).
 */
export const HORAS_DE_VALIDADE = 72;

/** Quantos milissegundos tem uma hora. Escrito uma vez. */
const MS_POR_HORA = 3_600_000;

/**
 * O fuso de apresentação é `Africa/Luanda` (dicionário §2), que é **UTC+1 sem
 * hora de Verão** — CONFIRMADO pela base `tzdata` (zona `Africa/Lagos`, a que
 * `Africa/Luanda` é ligada). O dia do período conta-se em Luanda: um ciclo que
 * abre «no dia 1» abre à meia-noite de Luanda, que é 23:00 UTC do dia anterior.
 */
const DESVIO_DE_LUANDA_MS = MS_POR_HORA;

/** O dia de facturação vai de 1 a 28: todos os meses o têm. */
export const DIA_MAXIMO_DO_PERIODO = 28;

/** Uma data civil `AAAA-MM-DD`, sem hora nem fuso. */
export type DataCivil = string;

/** Um período `[inicio, fim)`: o `daterange` da `billing_cycles.periodo`. */
export type Periodo = { readonly inicio: DataCivil; readonly fim: DataCivil };

export class PeriodoInvalido extends Error {
  override readonly name = "PeriodoInvalido";
}

const DATA_CIVIL = /^(\d{4})-(\d{2})-(\d{2})$/;

function partes(data: DataCivil): [number, number, number] {
  const achado = DATA_CIVIL.exec(data);
  if (achado === null) throw new PeriodoInvalido(`'${data}' nao e uma data AAAA-MM-DD`);
  const [ano, mes, dia] = [Number(achado[1]), Number(achado[2]), Number(achado[3])];
  const verificada = new Date(Date.UTC(ano, mes - 1, dia));
  if (verificada.getUTCMonth() !== mes - 1 || verificada.getUTCDate() !== dia) {
    throw new PeriodoInvalido(`'${data}' nao existe no calendario`);
  }
  return [ano, mes, dia];
}

function civil(ano: number, mes: number, dia: number): DataCivil {
  const d = new Date(Date.UTC(ano, mes - 1, dia));
  return d.toISOString().slice(0, 10);
}

/** A data civil em Luanda de um instante. */
export function dataEmLuanda(agora: Date): DataCivil {
  return new Date(agora.getTime() + DESVIO_DE_LUANDA_MS).toISOString().slice(0, 10);
}

/**
 * O período que contém `hoje`, para uma subscrição com `periodo_dia = dia`.
 *
 * Mensal, de `dia` a `dia` do mês seguinte, meio-aberto. Com `dia = 10`, o dia
 * 9 de Março pertence a `[10 Fev, 10 Mar)` e o dia 10 a `[10 Mar, 10 Abr)`.
 *
 * O `dia` vai de 1 a 28 (o `subscriptions_periodo_dia_ck` da revisão), e a
 * razão é aritmética: um dia 31 não existe em Fevereiro, e qualquer regra de
 * recuo («o último dia do mês») fazia o período de Março começar num dia
 * diferente do de Abril — dois ciclos com fronteiras móveis, e um `UNIQUE
 * (subscription_id, periodo)` que deixava de ser «um por mês».
 */
export function periodoDe(hoje: DataCivil, dia: number): Periodo {
  if (!Number.isInteger(dia) || dia < 1 || dia > DIA_MAXIMO_DO_PERIODO) {
    throw new PeriodoInvalido(`periodo_dia ${dia} fora de 1..${DIA_MAXIMO_DO_PERIODO}`);
  }
  const [ano, mes, d] = partes(hoje);
  const [anoInicio, mesInicio] = d >= dia ? [ano, mes] : mes === 1 ? [ano - 1, 12] : [ano, mes - 1];
  return {
    inicio: civil(anoInicio, mesInicio, dia),
    fim: civil(anoInicio, mesInicio + 1, dia),
  };
}

/** Uma linha de `price_book`. `valido_ate` é exclusivo, como o `fim` do período. */
export type LinhaDoPrecario = {
  readonly id: Uuid;
  readonly plano: string;
  readonly valorMinor: Minor;
  readonly validoDe: DataCivil;
  readonly validoAte: DataCivil | null;
};

/**
 * O preço em vigor no **início** do período: a linha do plano com o maior
 * `valido_de` que não seja posterior a `inicio`, e cujo `valido_ate` (se
 * houver) seja posterior a `inicio`.
 *
 * **O início, e não o dia em que o *job* corre.** É isso que faz o critério 6:
 * uma linha nova com `valido_de` a meio de um período não toca no ciclo dele —
 * que já guardou o `valor_minor` ao abrir — e o *job* seguinte, ao abrir o
 * período em que ela já vale, lê-a. Se o critério fosse «o preço do dia do
 * *job*», um atraso de um dia no agendador mudava o valor de um mês inteiro.
 *
 * `null` quando não há preço: o *job* **não abre** o ciclo, e diz porquê. Um
 * ciclo de zero cobrava nada por um serviço prestado; um ciclo com o preço do
 * plano mais próximo inventava um preço.
 */
export function precoEmVigor(
  linhas: readonly LinhaDoPrecario[],
  plano: string,
  inicio: DataCivil,
): LinhaDoPrecario | null {
  partes(inicio);
  let melhor: LinhaDoPrecario | null = null;
  for (const linha of linhas) {
    if (linha.plano !== plano) continue;
    if (linha.validoDe > inicio) continue;
    if (melhor === null || linha.validoDe > melhor.validoDe) melhor = linha;
  }
  // **A mais recente decide, e se ja acabou nao ha preco.** A primeira versao
  // saltava as linhas acabadas e voltava a uma mais antiga sem fim: um plano
  // descontinuado (a linha nova com `valido_ate`) ressuscitava o preco de
  // antes dela. Achado da revisao adversarial.
  if (melhor !== null && melhor.validoAte !== null && melhor.validoAte <= inicio) {
    return null;
  }
  return melhor;
}

/** O fim da validade da cobrança do ciclo: `agora + 72 h`. */
export function validadeDaCobranca(agora: Date): Date {
  return new Date(agora.getTime() + HORAS_DE_VALIDADE * MS_POR_HORA);
}

/** Pontos-base: 10 000 = 100%. */
export const BPS_POR_UNIDADE = 10_000n;

export class TaxaInvalida extends Error {
  override readonly name = "TaxaInvalida";
}

/**
 * A comissão **em sombra** de um pagamento: `floor(base × taxa / 10 000)`.
 *
 * Em `bigint`, e por defeito e não por arredondamento ao mais próximo: a sombra
 * mede o que **se poderia** facturar, e um arredondamento para cima
 * sobrestimava-o em cêntimos que se somam ao longo de um mês de vendas. A taxa
 * **não tem omissão**: é «taxa por contrato» (§11.1), não está decidida, e uma
 * constante aqui era um preço inventado. Quem corre a sombra passa a taxa que
 * quer medir, e ela fica gravada em cada linha (`taxa_bps`).
 */
export function comissaoEmSombra(baseMinor: Minor, taxaBps: number): Minor {
  if (!Number.isInteger(taxaBps) || taxaBps < 0 || taxaBps > Number(BPS_POR_UNIDADE)) {
    throw new TaxaInvalida(`taxa_bps ${taxaBps} fora de 0..${BPS_POR_UNIDADE}`);
  }
  if (baseMinor < 0n) throw new TaxaInvalida(`base_minor ${baseMinor} negativa`);
  return (baseMinor * BigInt(taxaBps)) / BPS_POR_UNIDADE;
}

// --------------------------------------------------------------------------
// O gancho fiscal (critério 10). Declarado e **sem** implementação: Clusters.
// --------------------------------------------------------------------------

/** Referências opacas do parceiro fiscal (§13). */
export type OrgRef = { readonly orgId: string };
export type CustomerRef = { readonly customerId: string };
export type InvoiceRef = { readonly invoiceId: string };

/**
 * A porta definitiva do §13, à letra dos seus seis métodos. **Diferida**: o
 * parceiro certificado pela AGT está por decidir (D7) e nenhum candidato tem o
 * certificado validado na lista oficial (`docs/tecnica/04` §13, INDÍCIO).
 *
 * Existe declarada para que o processo manual do Piloto tenha onde encaixar
 * quando deixar de ser manual, e para que o ensaio do critério 9 possa afirmar
 * que **nenhuma** classe a implementa nesta árvore.
 */
export interface InvoiceProvider {
  ensureOrganisation(tenant: { readonly tenantId: Uuid }): Promise<OrgRef>;
  ensureCustomer(
    org: OrgRef,
    cliente: { readonly nome: string; readonly nif?: string },
  ): Promise<CustomerRef>;
  issueInvoiceReceipt(
    org: OrgRef,
    pedido: {
      readonly customer: CustomerRef;
      readonly valorMinor: Minor;
      readonly idempotencyKey: string;
    },
  ): Promise<InvoiceRef>;
  status(
    ref: InvoiceRef,
  ): Promise<{ estado: "pendente" | "emitida" | "falhada" | "cancelada"; numeroFiscal?: string }>;
  creditNote(ref: InvoiceRef, motivo: string): Promise<InvoiceRef>;
  verifyWebhook(raw: { readonly body: Uint8Array }): Promise<unknown>;
}

// --------------------------------------------------------------------------
// O SQL. As suites de base de dados leem estas cadeias deste ficheiro (o
// `ConsultaDoTypeScript`), pelo que o que se prova contra o PostgreSQL é o que
// este módulo envia, e não uma cópia.
// --------------------------------------------------------------------------

/**
 * As subscrições que abrem ciclo, de **todos** os tenants. Corre como
 * `kamba_pay`, a quem a política `pay_billing_subscricoes` dá a leitura.
 */
export const SQL_BILLING_SUBSCRICOES = `
  SELECT id, tenant_id, plano, estado, periodo_dia
    FROM platform.subscriptions
   WHERE estado IN ('ativa', 'em_atraso')
   ORDER BY tenant_id
`;

/** As linhas de um plano. O `precoEmVigor` escolhe; a base não escolhe. */
export const SQL_BILLING_PRECARIO = `
  SELECT id, plano, valor_minor, valido_de::text AS valido_de,
         valido_ate::text AS valido_ate
    FROM platform.price_book
   WHERE plano = $1
`;

/** O contexto do tenant, **local à transacção** (o `true`). */
export const SQL_BILLING_CONTEXTO = `
  SELECT set_config('app.tenant_id', $1, true)
`;

/**
 * Abre o ciclo, **ou nada**: o `ON CONFLICT` sobre o `UNIQUE (subscription_id,
 * periodo)` é o que faz o *job* correr duas vezes e abrir um (critério 2).
 */
export const SQL_BILLING_ABRIR_CICLO = `
  INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, valor_minor)
  VALUES ($1, $2, daterange($3::date, $4::date, '[)'), $5)
  ON CONFLICT ON CONSTRAINT billing_cycles_periodo_uq DO NOTHING
  RETURNING id
`;

/**
 * A cobrança do ciclo, tentativa 1, na conta de receita própria **activa**.
 *
 * O `provider` lê-se da conta e não se recebe: e a conta tem de estar `ativo`,
 * que o `assert_beneficiary` (G-1) não confere — uma conta da KAMBÁ `suspenso`
 * ou `revogado` aceitava cobranças (achado da revisão adversarial). Sem linha
 * devolvida, o *job* recusa e reverte o ciclo que acabou de abrir. O G-1
 * continua a recusar uma conta de PME, e é a barreira; isto é a pergunta certa.
 */
export const SQL_BILLING_COBRANCA = `
  INSERT INTO platform.payment_charges (
      id, tenant_id, billing_cycle_id, tentativa, account_id, provider, metodo,
      referencia, amount_minor, currency, valid_until)
  SELECT $1, $2, $3, 1, a.id, a.provider, $5, $6, $7, 'AOA', $8
    FROM platform.payment_accounts a
   WHERE a.id = $4 AND a.beneficiary_kind = 'plataforma_receita_propria'
     AND a.estado = 'ativo'
  ON CONFLICT ON CONSTRAINT payment_charges_billing_tentativa_uq DO NOTHING
  RETURNING id
`;

/** `iniciada -> emitida` pela porta do ledger: o facto de ciclo de vida. */
export const SQL_BILLING_EMITIR = `
  SELECT estado_novo FROM platform.append_payment_event(
    p_charge_id => $1, p_tipo_evento => 'referencia_emitida',
    p_account_id => $2, p_valor_minor => $3, p_authn_method => 'sistema',
    p_authn_ok => true, p_decisao => 'informativo')
`;

/** `aberto -> cobranca_emitida`. O grafo é do *trigger*. */
export const SQL_BILLING_CICLO_EMITIDO = `
  UPDATE platform.billing_cycles SET estado = 'cobranca_emitida'
   WHERE id = $1 AND estado = 'aberto'
`;

/**
 * Uma aprovação de ops; a segunda, de outra pessoa, paga (critério 5).
 * `SECURITY INVOKER`, como `kamba_pay`, com o contexto do tenant que paga.
 */
export const SQL_BILLING_CONFIRMAR_OPS = `
  SELECT aprovacoes, concluida, repetida
    FROM platform.billing_confirmar_ops($1, $2, $3, $4)
`;

/**
 * Mudar o plano e os `entitlements` **numa só instrução** (critério 8).
 *
 * Uma instrução e não quatro numa transacção, e a diferença mede-se: com
 * quatro, a atomicidade dependia de quem chama abrir a transacção; com uma, não
 * há estado intermédio que alguém veja. Corre como `kamba_batch`, que é o único
 * papel com escrita em `entitlements` e no `tenants.plano` desde a revisão
 * `0007`.
 *
 * `$3` é a lista `{modulo, ativo, limites}` do plano, lida do
 * `registry/plans.yaml` por quem chama — o mapa plano → módulos é dado de
 * produto e não vive aqui. Os módulos que o plano novo **não** traz ficam
 * `ativo = false` (não se apagam: o histórico de entitlements é o que o
 * `ten_tecto` lê, e um `DELETE` tirava-o).
 */
export const SQL_MUDAR_PLANO = `
  WITH plano AS (
    SELECT x.modulo, x.ativo, x.limites
      FROM jsonb_to_recordset($3::jsonb) AS x(modulo text, ativo boolean, limites jsonb)
  ), s AS (
    UPDATE platform.subscriptions SET plano = $2 WHERE tenant_id = $1::uuid
    RETURNING id
  ), t AS (
    UPDATE platform.tenants SET plano = $2 WHERE id = $1::uuid
    RETURNING id
  ), e AS (
    INSERT INTO platform.entitlements (tenant_id, modulo, ativo, limites)
    SELECT $1::uuid, p.modulo, p.ativo, p.limites FROM plano p
    ON CONFLICT (tenant_id, modulo)
      DO UPDATE SET ativo = EXCLUDED.ativo, limites = EXCLUDED.limites
    RETURNING modulo
  ), d AS (
    UPDATE platform.entitlements SET ativo = false
     WHERE tenant_id = $1::uuid AND ativo
       AND modulo NOT IN (SELECT modulo FROM plano)
    RETURNING modulo
  )
  SELECT (SELECT count(*) FROM s)::int AS subscricoes,
         (SELECT count(*) FROM t)::int AS tenants,
         (SELECT count(*) FROM e)::int AS garantidos,
         (SELECT count(*) FROM d)::int AS desactivados
`;

/**
 * Os pagamentos de encomenda que a sombra ainda não mediu, no tenant em
 * contexto. Só os autenticados pelo facilitador (§11.1).
 */
export const SQL_SOMBRA_POR_MEDIR = `
  SELECT e.id, e.order_id, e.valor_minor
    FROM platform.payment_events e
   WHERE e.tipo_evento = 'pagamento_confirmado' AND e.decisao = 'aceite'
     AND e.authn_ok AND e.authn_method IN ('hmac', 'consulta')
     AND e.order_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM platform.commission_accruals a
                      WHERE a.payment_event_id = e.id)
   ORDER BY e.id
   LIMIT $1
`;

/** Uma linha de sombra. O `UNIQUE (payment_event_id)` absorve a repetição. */
export const SQL_SOMBRA_GRAVAR = `
  INSERT INTO platform.commission_accruals (
      tenant_id, order_id, payment_event_id, base_minor, taxa_bps, comissao_minor)
  VALUES ($1, $2, $3, $4, $5, $6)
  ON CONFLICT ON CONSTRAINT commission_accruals_evento_uq DO NOTHING
`;

// --------------------------------------------------------------------------
// Os jobs.
// --------------------------------------------------------------------------

export class ContaDeReceitaInactiva extends Error {
  override readonly name = "ContaDeReceitaInactiva";
}

/** A conta de receita própria da KAMBÁ com que se cobra. */
export type ContaDeReceita = { readonly id: Uuid; readonly provider: string };

/** O que o adaptador devolve ao emitir a cobrança do ciclo. */
export type Emissao = {
  readonly metodo: "referencia" | "manual";
  readonly referencia: string | null;
};

/**
 * Quem emite a cobrança. Uma porta, e não o `PaymentProvider` directo: o
 * `ManualProvider.createCharge` aplica o tecto manual **da PME** (M-2), que é
 * um limite às vendas dela e não à assinatura que ela paga à KAMBÁ.
 */
export type EmissorDeCobranca = (pedido: {
  readonly chargeId: Uuid;
  readonly tenantId: Uuid;
  readonly valorMinor: Minor;
  readonly conta: ContaDeReceita;
}) => Promise<Emissao>;

/**
 * O emissor do Piloto: transferência com instruções, sem referência. É o
 * *fallback* do §11.2 enquanto a KAMBÁ não tiver conta EMIS própria (D4, NÃO
 * VERIFICADO). As instruções lêem-se de `payment_accounts.manual_instrucoes`.
 */
export const emissorManual: EmissorDeCobranca = async () => ({
  metodo: "manual",
  referencia: null,
});

export type RelatorioDeAbertura = {
  readonly abertos: readonly Uuid[];
  readonly jaAbertos: number;
  readonly semPreco: readonly Uuid[];
  readonly falhas: readonly { readonly subscricao: Uuid; readonly erro: string }[];
};

function texto(valor: unknown): string {
  return String(valor);
}

function minorDe(valor: unknown): Minor {
  return BigInt(texto(valor));
}

/**
 * O *job* de abertura de ciclos (critério 2).
 *
 * Uma transacção **por subscrição**: uma PME sem preço ou com um erro não
 * impede as outras de serem cobradas, e o relatório diz quem ficou de fora. Em
 * cada uma, pela ordem: o contexto do tenant, o ciclo (ou nada, se já existe),
 * a cobrança com validade de 72 h, o `referencia_emitida` no ledger, e o ciclo
 * a `cobranca_emitida` — tudo ou nada.
 *
 * `agora` e `gerarId` entram por argumento: o *job* não tem relógio nem fonte de
 * aleatoriedade própria, e é assim que o período e a validade se medem.
 */
export async function abrirCiclos(
  bd: ClienteSql,
  opcoes: {
    readonly agora: Date;
    readonly conta: ContaDeReceita;
    readonly emissor: EmissorDeCobranca;
    readonly gerarId: () => Uuid;
  },
): Promise<RelatorioDeAbertura> {
  const hoje = dataEmLuanda(opcoes.agora);
  const { rows: subscricoes } = await bd.query(SQL_BILLING_SUBSCRICOES);
  const precarios = new Map<string, LinhaDoPrecario[]>();
  const abertos: Uuid[] = [];
  const semPreco: Uuid[] = [];
  const falhas: { subscricao: Uuid; erro: string }[] = [];
  let jaAbertos = 0;

  for (const linha of subscricoes) {
    const subscricao = texto(linha.id);
    const tenant = texto(linha.tenant_id);
    const plano = texto(linha.plano);
    try {
      const periodo = periodoDe(hoje, Number(linha.periodo_dia));
      let linhas = precarios.get(plano);
      if (linhas === undefined) {
        const { rows } = await bd.query(SQL_BILLING_PRECARIO, [plano]);
        linhas = rows.map((r) => ({
          id: texto(r.id),
          plano: texto(r.plano),
          valorMinor: minorDe(r.valor_minor),
          validoDe: texto(r.valido_de),
          validoAte: r.valido_ate === null ? null : texto(r.valido_ate),
        }));
        precarios.set(plano, linhas);
      }
      const preco = precoEmVigor(linhas, plano, periodo.inicio);
      if (preco === null || preco.valorMinor === 0n) {
        semPreco.push(subscricao);
        continue;
      }

      await bd.query("BEGIN");
      try {
        await bd.query(SQL_BILLING_CONTEXTO, [tenant]);
        const ciclo = await bd.query(SQL_BILLING_ABRIR_CICLO, [
          subscricao,
          tenant,
          periodo.inicio,
          periodo.fim,
          preco.valorMinor.toString(),
        ]);
        if (ciclo.rows.length === 0) {
          jaAbertos += 1;
          await bd.query("COMMIT");
          continue;
        }
        const cicloId = texto(ciclo.rows[0]?.id);
        const chargeId = opcoes.gerarId();
        const emissao = await opcoes.emissor({
          chargeId,
          tenantId: tenant,
          valorMinor: preco.valorMinor,
          conta: opcoes.conta,
        });
        const cobranca = await bd.query(SQL_BILLING_COBRANCA, [
          chargeId,
          tenant,
          cicloId,
          opcoes.conta.id,
          emissao.metodo,
          emissao.referencia,
          preco.valorMinor.toString(),
          validadeDaCobranca(opcoes.agora).toISOString(),
        ]);
        if (cobranca.rows.length === 0) {
          throw new ContaDeReceitaInactiva(
            `a conta ${opcoes.conta.id} nao e uma conta de receita propria activa`,
          );
        }
        await bd.query(SQL_BILLING_EMITIR, [
          chargeId,
          opcoes.conta.id,
          preco.valorMinor.toString(),
        ]);
        await bd.query(SQL_BILLING_CICLO_EMITIDO, [cicloId]);
        await bd.query("COMMIT");
        abertos.push(cicloId);
      } catch (erro) {
        await bd.query("ROLLBACK");
        throw erro;
      }
    } catch (erro) {
      falhas.push({ subscricao, erro: erro instanceof Error ? erro.message : String(erro) });
    }
  }
  return { abertos, jaAbertos, semPreco, falhas };
}

/** Um módulo do plano, como o `registry/plans.yaml` o escreve. */
export type EntitlementDoPlano = {
  readonly modulo: string;
  readonly ativo: boolean;
  readonly limites: Readonly<Record<string, unknown>>;
};

export class SubscricaoInexistente extends Error {
  override readonly name = "SubscricaoInexistente";
}

/**
 * Muda o plano de um tenant e os `entitlements` dele (critério 8).
 *
 * A instrução é uma só (`SQL_MUDAR_PLANO`); a transacção à volta existe para a
 * **recusa**: um tenant sem subscrição não muda de plano, e sem o `ROLLBACK` os
 * `entitlements` dele mudavam na mesma.
 */
export async function mudarPlano(
  bd: ClienteSql,
  tenantId: Uuid,
  plano: string,
  modulos: readonly EntitlementDoPlano[],
): Promise<{ readonly garantidos: number; readonly desactivados: number }> {
  await bd.query("BEGIN");
  try {
    const { rows } = await bd.query(SQL_MUDAR_PLANO, [
      tenantId,
      plano,
      JSON.stringify(modulos),
    ]);
    const r = rows[0] ?? {};
    if (Number(r.subscricoes) !== 1 || Number(r.tenants) !== 1) {
      throw new SubscricaoInexistente(
        `o tenant ${tenantId} nao tem subscricao (ou nao existe): o plano nao muda`,
      );
    }
    await bd.query("COMMIT");
    return { garantidos: Number(r.garantidos), desactivados: Number(r.desactivados) };
  } catch (erro) {
    await bd.query("ROLLBACK");
    throw erro;
  }
}

export class MotivoEmFalta extends Error {
  override readonly name = "MotivoEmFalta";
}

/** O que a porta de ops respondeu. */
export type RespostaDeOps = {
  readonly aprovacoes: number;
  readonly concluida: boolean;
  readonly repetida: boolean;
};

/**
 * Uma aprovação de ops da confirmação manual de um ciclo (critério 5).
 *
 * O `actorId` é a identidade da equipa que a consola autenticou (KAM-196); o
 * `motivo` é obrigatório. A segunda pessoa conclui.
 */
export async function aprovarPorOps(
  bd: ClienteSql,
  pedido: {
    readonly tenantId: Uuid;
    readonly chargeId: Uuid;
    readonly actorId: Uuid;
    readonly motivo: string;
    readonly valorMinor: Minor;
  },
): Promise<RespostaDeOps> {
  if (pedido.motivo.trim() === "") {
    throw new MotivoEmFalta("uma aprovacao de ops sem motivo nao se envia");
  }
  await bd.query("BEGIN");
  try {
    await bd.query(SQL_BILLING_CONTEXTO, [pedido.tenantId]);
    const { rows } = await bd.query(SQL_BILLING_CONFIRMAR_OPS, [
      pedido.chargeId,
      pedido.actorId,
      pedido.motivo,
      pedido.valorMinor.toString(),
    ]);
    await bd.query("COMMIT");
    const r = rows[0] ?? {};
    return {
      aprovacoes: Number(r.aprovacoes),
      concluida: r.concluida === true,
      repetida: r.repetida === true,
    };
  } catch (erro) {
    await bd.query("ROLLBACK");
    throw erro;
  }
}

/**
 * A sombra da comissão, por tenant (critério 7; §11.1).
 *
 * Corre **sempre**, com `commission_enabled` desligado: é isso que «modo
 * sombra» quer dizer — calcula-se para medir, e nunca se factura. A taxa entra
 * por argumento e não tem omissão (ver `comissaoEmSombra`).
 */
export async function acumularSombra(
  bd: ClienteSql,
  opcoes: { readonly tenants: readonly Uuid[]; readonly taxaBps: number; readonly lote: number },
): Promise<number> {
  comissaoEmSombra(0n, opcoes.taxaBps);
  let gravadas = 0;
  for (const tenant of opcoes.tenants) {
    await bd.query("BEGIN");
    try {
      await bd.query(SQL_BILLING_CONTEXTO, [tenant]);
      const { rows } = await bd.query(SQL_SOMBRA_POR_MEDIR, [opcoes.lote]);
      for (const r of rows) {
        const base = minorDe(r.valor_minor);
        const escrita = await bd.query(SQL_SOMBRA_GRAVAR, [
          tenant,
          texto(r.order_id),
          texto(r.id),
          base.toString(),
          opcoes.taxaBps,
          comissaoEmSombra(base, opcoes.taxaBps).toString(),
        ]);
        gravadas += escrita.rowCount ?? 0;
      }
      await bd.query("COMMIT");
    } catch (erro) {
      await bd.query("ROLLBACK");
      throw erro;
    }
  }
  return gravadas;
}


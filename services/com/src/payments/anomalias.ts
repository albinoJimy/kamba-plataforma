/**
 * A ligação do motor de anomalias do KAM-060 à base e às métricas deste serviço.
 *
 * O motor vive em `@kamba/core-ts/pagamentos` e é puro: recebe uma fotografia e
 * devolve sinais. Este ficheiro é a **raiz de composição** — o único sítio onde
 * o SQL do motor encontra uma ligação, onde os sinais encontram o contador do
 * `/metrics`, e onde um alerta encontra o `logger`.
 *
 * ## Porque é que isto é um ficheiro e não três linhas no consumidor
 *
 * O `./consumidor.ts` está nos `excluidos` do `ci/thresholds.yaml` por ser casca
 * sobre BullMQ, `pg` e Hono — e o estrato `critico` do padrão de `payments`
 * (escrito com asteriscos no `ci/thresholds.yaml`, que não se repetem aqui à
 * letra porque fechariam este comentário) exige 90% por ficheiro. Uma composição
 * escondida lá dentro era lógica não medida num caminho de dinheiro. É a mesma
 * separação que o KAM-055 fez entre o `./arranque.ts` (medido) e o
 * `./consumidor.ts` (excluído), e pela mesma razão.
 *
 * ## O que este ficheiro **não** faz
 *
 * Não abre ligações, não lê variáveis de ambiente e não tem relógio: recebe a
 * ligação, a janela e o instante por argumento. Sem isso o ensaio precisava de
 * um PostgreSQL para medir um mapeamento de colunas, que é a parte onde um
 * `contact_id` aterra na coluna do `charge_id` sem ninguém ver.
 */

import {
  ALERTA_DE_ESCRITA,
  ALERTA_DE_ORFAO,
  ALERTA_DE_SINAL,
  SQL_ANOMALIAS_AJUSTES_FEITOS,
  SQL_ANOMALIAS_CASA,
  SQL_ANOMALIAS_COBRANCAS,
  SQL_ANOMALIAS_CONFIRMACOES,
  SQL_ANOMALIAS_EVENTOS,
  SQL_ANOMALIAS_RECUSAS,
  SQL_REGISTAR_SINAL,
  detectarAnomalias,
  lerExtracto,
  reconciliar,
  sinaisDaReconciliacao,
} from "@kamba/core-ts/pagamentos";
import type {
  AjusteProposto,
  CobrancaObservada,
  EscritaDeSinais,
  ConfirmacaoObservada,
  ContactoDaCasa,
  EventoObservado,
  Fotografia,
  LeituraDeAnomalias,
  RecusaDeCallback,
  RelatorioDeAnomalias,
  Sinal,
  TipoDeEventoDoLedger,
} from "@kamba/core-ts/pagamentos";

import { SINAIS } from "./metricas.ts";

/** O mínimo que uma ligação precisa de saber fazer. O padrão do `./arranque.ts`. */
export interface ClienteDeLeitura {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[] }>;
}

/**
 * Os tipos de evento que a fotografia lê.
 *
 * **Lista fechada e não «todos»**, e a razão é custo e não pureza: a
 * `payment_events` é o *ledger* inteiro e cresce para sempre, e uma leitura sem
 * filtro de tipo trazia os `cobranca_criada` e os `referencia_emitida` de todas
 * as cobranças da janela para o motor não olhar para nenhum deles.
 */
export const TIPOS_QUE_O_MOTOR_LE: readonly TipoDeEventoDoLedger[] = [
  "pagamento_divergente",
  "pagamento_orfao",
  "pagamento_duplicado",
];

/** Quantas horas para trás a fotografia lê. A janela mais larga das regras. */
export const HORAS_DA_FOTOGRAFIA = 720;

/**
 * Horas para trás a partir de um instante, em ISO.
 *
 * Exportada para ter ensaio próprio: um erro de sinal aqui fazia a fotografia
 * ler o futuro, e o motor devolvia zero sinais com toda a convicção.
 */
export function desde(agora: Date, horas: number): string {
  return new Date(agora.getTime() - horas * 3_600_000).toISOString();
}

/**
 * `null` em `undefined` ou `null`, e a cadeia em todo o resto.
 *
 * O condutor de `pg` devolve `uuid` como cadeia e `NULL` como `null`; um
 * `String(null)` dava a cadeia `"null"`, que passa por um `Uuid` sem reclamar e
 * casa com nada. É o defeito que esta função existe para não ter em dez sítios.
 */
function _ouNulo(valor: unknown): string | null {
  return valor === null || valor === undefined ? null : String(valor);
}

/**
 * A fotografia, lida numa ligação.
 *
 * **As cinco leituras numa `Promise.all`**, e não em série: são independentes e
 * a janela é a mesma, pelo que a ordem não decide nada. Em série pagava-se cinco
 * vezes a latência da base por uma fotografia que é uma.
 *
 * A `casa` é **por tenant**, ao contrário das outras quatro: o
 * `SQL_ANOMALIAS_CASA` junta `payment_confirmers` a `contacts` e essa junção só
 * faz sentido dentro de um tenant. Quem corre o motor sobre vários tenants
 * chama isto uma vez por tenant — que é o que o `kamba_batch` faz, e o que
 * mantém a consulta dentro do RLS em vez de a pedir a um papel que o atravesse.
 */
export function leituraSobre(
  bd: ClienteDeLeitura,
  tenantId: string,
  agora: Date,
  horas: number = HORAS_DA_FOTOGRAFIA,
): LeituraDeAnomalias {
  return {
    async fotografar(): Promise<Fotografia> {
      const limite = desde(agora, horas);
      const [eventos, cobrancas, confirmacoes, recusas, casa] =
        await Promise.all([
          bd.query(SQL_ANOMALIAS_EVENTOS, [[...TIPOS_QUE_O_MOTOR_LE], limite]),
          bd.query(SQL_ANOMALIAS_COBRANCAS, [limite]),
          bd.query(SQL_ANOMALIAS_CONFIRMACOES, [limite]),
          bd.query(SQL_ANOMALIAS_RECUSAS, [limite]),
          bd.query(SQL_ANOMALIAS_CASA, [tenantId]),
        ]);
      return {
        eventos: eventos.rows.map(_evento),
        cobrancas: cobrancas.rows.map(_cobranca),
        confirmacoes: confirmacoes.rows.map(_confirmacao),
        recusas: recusas.rows.map(_recusa),
        casa: casa.rows.map(_contacto),
        agora: agora.toISOString(),
      };
    },
  };
}

function _evento(linha: Record<string, unknown>): EventoObservado {
  return {
    eventId: BigInt(String(linha["id"])),
    tenantId: String(linha["tenant_id"]),
    chargeId: String(linha["charge_id"]),
    accountId: String(linha["account_id"]),
    tipoEvento: String(linha["tipo_evento"]) as TipoDeEventoDoLedger,
    sequencia: Number(linha["sequencia"]),
    // **`BigInt(String(...))` e não `BigInt(...)`**, pela razão do `./efeito.ts`:
    // a coluna é `bigint` e o condutor devolve-a como cadeia, e um `Number` pelo
    // meio arredondava em silêncio num caminho de dinheiro.
    valorMinor: BigInt(String(linha["valor_minor"])),
    instante: _instante(linha["instante"]),
  };
}

function _cobranca(linha: Record<string, unknown>): CobrancaObservada {
  return {
    chargeId: String(linha["id"]),
    tenantId: String(linha["tenant_id"]),
    accountId: String(linha["account_id"]),
    orderId: _ouNulo(linha["order_id"]),
    estado: String(linha["estado"]),
    metodo: String(linha["metodo"]),
    amountMinor: BigInt(String(linha["amount_minor"])),
    payerHmac: _ouNulo(linha["payer_hmac"]),
    contactId: _ouNulo(linha["contact_id"]),
    // **A `referencia` era lida e descartada**, e isso tornava a reconciliação
    // impossível de ligar: o `SQL_ANOMALIAS_COBRANCAS` selecciona-a desde o
    // início e este mapeamento não a punha no objecto, pelo que o
    // `referenciaPorCobranca` do `reconciliar` não tinha produtor nenhum. Achado
    // da revisão adversarial, e é a classe de defeito que só se vê a cruzar o
    // SQL com o mapeamento — nenhum ensaio do motor o podia ver.
    referencia: _ouNulo(linha["referencia"]),
    criadoEm: _instante(linha["criado_at"]),
  };
}

function _confirmacao(linha: Record<string, unknown>): ConfirmacaoObservada {
  return {
    chargeId: String(linha["charge_id"]),
    tenantId: String(linha["tenant_id"]),
    contactId: String(linha["actor_contact_id"]),
    decisao: String(linha["decisao"]),
    instante: _instante(linha["criado_at"]),
  };
}

function _recusa(linha: Record<string, unknown>): RecusaDeCallback {
  return {
    accountId: String(linha["account_id"]),
    instante: _instante(linha["recebido_at"]),
  };
}

function _contacto(linha: Record<string, unknown>): ContactoDaCasa {
  return {
    contactId: String(linha["contact_id"]),
    phoneHmac: String(linha["phone_hmac"]),
  };
}

/**
 * Um `timestamptz` em ISO, venha ele como `Date` ou como cadeia.
 *
 * O condutor de `pg` devolve `Date` por omissão e cadeia quando quem configurou
 * o `pg-types` o pediu; as duas formas aparecem nesta árvore. Um `String(date)`
 * dava `"Mon Nov 08 2026 ..."`, que o `Date.parse` do motor lê — **mas sem
 * fuso**, pelo que uma janela de uma hora passava a depender do fuso do
 * processo. O ISO não tem esse problema.
 */
function _instante(valor: unknown): string {
  if (valor instanceof Date) return valor.toISOString();
  const texto = String(valor);
  const t = Date.parse(texto);
  // Uma data ilegível passa como está: o `_naJanela` do motor trata-a como fora
  // da janela, e inventar aqui um instante era dar à regra um dado que a base
  // não deu.
  return Number.isNaN(t) ? texto : new Date(t).toISOString();
}

/** Os alertas que esta raiz encaminha, para o ensaio não os escrever à mão. */
export const ALERTAS_DO_MOTOR = [
  ALERTA_DE_SINAL,
  ALERTA_DE_ORFAO,
  ALERTA_DE_ESCRITA,
] as const;

export type DependenciasDaCorrida = {
  readonly bd: ClienteDeLeitura;
  readonly tenantId: string;
  readonly agora: Date;
  readonly horas?: number | undefined;
  /**
   * Para onde vai um alerta. O `log` da biblioteca tem *allowlist* de campos
   * (`docs/tecnica/08` §7.3), pelo que o detalhe do alerta **não** vai para o
   * `logger`: quem chama decide, e o consumidor passa-lhe só o `outcome`.
   */
  alertar?(alerta: string, detalhe: Record<string, unknown>): void;
  /**
   * `true` corre o motor **sem** persistir, e e para quem so quer medir.
   *
   * A omissao e persistir: um *job* que calcula sinais e nao os escreve e o
   * estado que o `ALERTA_DE_ESCRITA` existe para denunciar, e nao se faz dele a
   * omissao de ninguem.
   */
  readonly semEscrita?: boolean | undefined;
  /** A janela de deduplicacao da porta. Ver o `JANELA_DA_ESCRITA_HORAS`. */
  readonly janelaHoras?: number | undefined;
};

/**
 * Corre o motor para um tenant, com o contador deste serviço ligado.
 *
 * **O `contar` é a ligação, e é o que um ensaio tem de matar.** Sem ele o
 * `detectarAnomalias` corre igual, devolve os mesmos sinais e passa todos os
 * ensaios do motor — e o `/metrics` deste processo fica a servir oito séries a
 * zero para sempre, que é o defeito que o `ops/metricas/catalogo.yaml` nomeia
 * («um painel que cita uma métrica que ninguém expõe mostra um gráfico vazio
 * para sempre»).
 *
 * **Sem `escrita`**, e não é esquecimento: a `platform.fraud_signals` é
 * SELECT-only para os três papéis (revisão `0032`), pelo que não há porta de
 * escrita para ligar. O motor levanta o `ALERTA_DE_ESCRITA` quando calcula
 * sinais e não tem onde os pôr, o que é a leitura honesta do estado — e a caixa
 * fica por marcar no bloco, com credor.
 */
export async function correrMotorDeAnomalias(
  deps: DependenciasDaCorrida,
): Promise<RelatorioDeAnomalias> {
  return detectarAnomalias({
    leitura: leituraSobre(deps.bd, deps.tenantId, deps.agora, deps.horas),
    // **A escrita e a segunda ligacao desta raiz**, e e a que fecha o caminho:
    // sem ela o motor calculava sinais e levantava o `ALERTA_DE_ESCRITA` a dizer
    // que nao tinha onde os por. Passa-se `undefined` quando quem chama nao a
    // quer — e o que o ensaio da corrida sem escrita mede.
    ...(deps.semEscrita === true
      ? {}
      : { escrita: escritaSobre(deps.bd, deps.tenantId, deps.janelaHoras) }),
    contar: (regra) => SINAIS.contar(regra),
    ...(deps.alertar === undefined ? {} : { alertar: deps.alertar }),
  });
}

/**
 * A janela de deduplicação que a porta aplica, em horas.
 *
 * É a janela da **linha** e não a da regra: duas anomalias iguais dentro dela
 * dão uma linha e o `id` repetido. Uma hora é a cadência de um *job* periódico —
 * quem o correr de dez em dez minutos passa uma janela maior, e quem quiser uma
 * linha por corrida passa `0`.
 */
export const JANELA_DA_ESCRITA_HORAS = 1;

/**
 * O motor trouxe um sinal de um tenant que não é o desta corrida.
 *
 * Não é defensividade solta: o `correrMotorDeAnomalias` corre **por tenant**, e
 * a fotografia dele filtra por tenant só onde o tenant é dado — as leituras de
 * eventos, cobranças, confirmações e recusas correm sob a RLS da ligação. Um
 * sinal de outro tenant aqui significa que a ligação não tinha o contexto que se
 * supôs, e nesse caso escrever era pior do que recusar.
 */
export class SinalDeOutroTenant extends Error {
  override readonly name = "SinalDeOutroTenant";

  constructor(daCorrida: string, doSinal: string) {
    super(
      `a corrida é do tenant ${daCorrida} e o sinal é do ${doSinal}: a ` +
        "platform.fraud_signals tem FORCE ROW LEVEL SECURITY e a política " +
        "recusaria com 42501, porque o SECURITY DEFINER da porta dá privilégio " +
        "e não dá isolamento (revisão 0032)",
    );
  }
}

/**
 * A implementação da `EscritaDeSinais`, sobre a `platform.registar_sinal_de_anomalia`.
 *
 * **Uma chamada por sinal e não um `INSERT` em lote**, e a razão é a porta: ela é
 * `SECURITY DEFINER` e valida cada sinal — a regra contra a lista fechada, o
 * `detalhe` sem PII, e a janela — e um lote passava-lhe um conjunto que ela teria
 * de validar linha a linha de qualquer forma. O que se perde em ida e volta
 * ganha-se em a recusa dizer **qual** sinal foi recusado.
 *
 * Conta os sinais que ficaram em linha nova. Um `id` que já existia não conta:
 * ver o `persistidos` do `RelatorioDeAnomalias`.
 */
export function escritaSobre(
  bd: ClienteDeLeitura,
  tenantId: string,
  janelaHoras: number = JANELA_DA_ESCRITA_HORAS,
): EscritaDeSinais {
  return {
    async persistir(sinais: readonly Sinal[]): Promise<number> {
      // **Sem sinais nao se fala com a base.** O `detectarAnomalias` chama esta
      // porta sempre que ela existe, e o caso comum de um *job* periodico e
      // «zero anomalias»: sem esta saida, cada corrida limpa gastava uma ida e
      // volta a definir um contexto que ninguem ia usar.
      if (sinais.length === 0) return 0;
      // **O contexto do tenant define-se aqui, e sem ele a porta leva `42501`.**
      //
      // A `0032` põe `FORCE ROW LEVEL SECURITY` na `fraud_signals` e escreve
      // porquê: o `SECURITY DEFINER` «dá privilégio e não dá isolamento» —
      // a função corre como o dono, que é `NOBYPASSRLS`, e o `FORCE` vincula
      // também o dono. O `app.tenant_id` de quem chama é o que a política
      // avalia, e o `BYPASSRLS` do `kamba_batch` não ajuda porque a função não
      // corre como ele.
      //
      // `true` no terceiro argumento é `SET LOCAL`: morre com a transacção, que
      // é a disciplina desta casa — um contexto que sobrevivesse ao `COMMIT`
      // deixava a ligação seguinte a escrever no tenant anterior.
      await bd.query("SELECT set_config('app.tenant_id', $1, true)", [tenantId]);
      const vistos = new Set<string>();
      for (const sinal of sinais) {
        // **Fail-closed antes da base.** A RLS recusaria igual, e com `42501`;
        // recusar aqui dá a quem lê o registo a razão em vez do SQLSTATE, e
        // impede que uma fotografia de outro tenant entre por engano num `job`
        // que corre tenant a tenant.
        if (sinal.tenantId !== tenantId) {
          throw new SinalDeOutroTenant(tenantId, sinal.tenantId);
        }
        const { rows } = await bd.query(SQL_REGISTAR_SINAL, [
          sinal.tenantId,
          sinal.regra,
          sinal.severidade,
          sinal.accao,
          sinal.contactId,
          sinal.chargeId,
          JSON.stringify(sinal.detalhe),
          `${janelaHoras} hours`,
        ]);
        const id = rows[0]?.["id"];
        if (id !== undefined && id !== null) vistos.add(String(id));
      }
      return vistos.size;
    },
  };
}

// --------------------------------------------- a reconciliação diária (R-08)

/** O que a reconciliação devolve: os ajustes a escrever e os sinais da R-08. */
export type ResultadoDaReconciliacao = {
  readonly ajustes: readonly AjusteProposto[];
  readonly sinais: readonly Sinal[];
};

/**
 * Compara o CSV do dono com as cobranças `paga` e devolve o que há a escrever.
 *
 * **Lê os ajustes já no *ledger* antes de propor**, e é isso que faz o «um CSV
 * repetido não duplica ajustes» do critério 7. Não é a base que o garante: o
 * índice único de `provider_event_id` da revisão `0029` é **parcial** e só cobre
 * o `pagamento_recebido` — está medido no `AjusteProposto.providerEventId`, com
 * o credor do índice que o tornaria estrutural.
 *
 * **Não escreve nada.** Devolver o que há a escrever e escrevê-lo são dois actos
 * e este módulo só faz o primeiro: o `ajuste_reconciliacao` entra no *ledger*
 * pela `platform.append_payment_event`, que é uma transacção do PAY e não uma
 * leitura, e misturar os dois num só passo fazia uma reconciliação meio escrita
 * ser indistinguível de uma que não correu.
 */
export async function reconciliarExtracto(deps: {
  readonly bd: ClienteDeLeitura;
  readonly csv: string;
  readonly cobrancas: readonly CobrancaObservada[];
  readonly referenciaPorCobranca: Readonly<Record<string, string>>;
}): Promise<ResultadoDaReconciliacao> {
  const { rows } = await deps.bd.query(SQL_ANOMALIAS_AJUSTES_FEITOS);
  const ajustes = reconciliar({
    linhas: lerExtracto(deps.csv),
    cobrancas: deps.cobrancas,
    referenciaPorCobranca: deps.referenciaPorCobranca,
    jaAjustados: rows.map((linha) => String(linha["provider_event_id"])),
  });
  const sinais = sinaisDaReconciliacao(ajustes);
  for (const sinal of sinais) SINAIS.contar(sinal.regra);
  return { ajustes, sinais };
}

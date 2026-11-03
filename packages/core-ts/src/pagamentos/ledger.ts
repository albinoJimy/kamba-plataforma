/**
 * A verificação diária da cadeia e a âncora externa (KAM-053, critério 6).
 *
 * O `../docs/tecnica/04` §8 põe quatro mecanismos de reconciliação na mesma
 * tabela, e **este módulo é o quarto**: «Integridade do ledger — diária:
 * verifica cadeia de *hashes*; `rebuild_charge_state` vs projecção; exporta
 * cabeça da cadeia para STO».
 *
 * São três afirmações independentes, e o *job* falha se **qualquer** uma falhar:
 *
 *     cadeia      `verify_ledger_chain()` devolve zero elos partidos
 *     projecção   para cada cobrança, `rebuild_charge_state(c)` é igual a
 *                 `payment_charges.estado`
 *     âncora      a cabeça da cadeia de cada cobrança foi escrita no
 *                 `StorageProvider` do KAM-011
 *
 * ## Porque é que a âncora conta
 *
 * Uma cadeia de *hashes* detecta adulteração **de quem não a recalcula**. Quem
 * tem o superutilizador da base pode alterar um evento e reescrever os
 * `row_hash` seguintes, e a cadeia fica consistente — o que ela prova, por si
 * só, é que ninguém mexeu *por acidente*.
 *
 * O que a torna uma prova contra quem tem a base é a cabeça estar **fora do
 * *host***: um atacante que reescreva a cadeia tem de reescrever também o que
 * foi exportado ontem, e isso está noutro sistema com outras credenciais. É o
 * que o §8 chama «âncora externa», e é a razão de a exportação ser parte do
 * *job* e não um extra.
 *
 * ## O que este módulo **não** faz
 *
 * Não corrige nada. Um ledger *append-only* não se corrige: uma divergência
 * entre a projecção e a reconstrução é um alerta para ops e, se for real, um
 * evento compensatório (`ajuste_reconciliacao`) escrito pela porta — nunca um
 * `UPDATE`. É por isso que a assinatura devolve um relatório e não um número de
 * linhas corrigidas.
 */

import type { Uuid } from "./tipos.ts";

/** O prefixo da âncora no `StorageProvider`. Uma chave por dia. */
export const PREFIXO_DA_ANCORA = "ledger/pagamentos";

/** O alerta do §14 («Integridade do ledger — alerta + testes de privilégios»). */
export const ALERTA_DA_CADEIA = "pay_ledger_cadeia_partida";

/** O alerta da divergência entre a projecção e a reconstrução (§8). */
export const ALERTA_DA_PROJECCAO = "pay_ledger_projeccao_divergente";

/**
 * O alerta de uma **leitura** que não correu.
 *
 * É diferente dos outros dois: eles dizem «a cadeia está partida», e este diz
 * «não se conseguiu verificar». Confundi-los era o pior dos dois mundos — um
 * *job* que não corre a parecer um *job* que passou.
 */
export const ALERTA_DE_LEITURA = "pay_ledger_leitura_falhou";

/** Um elo que a `verify_ledger_chain` apontou. */
export type EloPartido = {
  readonly chargeId: Uuid;
  readonly eventId: bigint;
  readonly sequencia: number;
  readonly falha: string;
};

/** Uma cobrança cuja projecção não bate com a reconstrução. */
export type ProjeccaoDivergente = {
  readonly chargeId: Uuid;
  readonly projectado: string;
  readonly reconstruido: string;
};

/** A cabeça da cadeia de uma cobrança, da `v_payment_ledger_heads`. */
export type CabecaDaCadeia = {
  readonly chargeId: Uuid;
  readonly tenantId: Uuid;
  readonly eventId: bigint;
  readonly sequencia: number;
  readonly rowHash: Uint8Array;
};

/**
 * O que o *job* devolve. **Não lança numa cadeia partida**, e isso é
 * deliberado: lançar perdia a parte do trabalho que correu bem — a exportação
 * da âncora é o que protege os eventos de amanhã, e deixá-la por fazer porque
 * um elo de ontem está partido piorava o problema. Quem chama decide o código
 * de saída.
 */
export type RelatorioDoLedger = {
  readonly elosPartidos: readonly EloPartido[];
  readonly projeccoesDivergentes: readonly ProjeccaoDivergente[];
  readonly cabecas: number;
  /** As leituras que não correram, com o erro de cada uma. */
  readonly leiturasFalhadas: readonly {
    readonly leitura: string;
    readonly erro: string;
  }[];
  /** A chave onde a âncora ficou, ou `null` se a exportação falhou. */
  readonly ancora: string | null;
  // `| undefined` explicito, pela razao do `hooks.ts`:
  // `exactOptionalPropertyTypes`.
  readonly erroDaAncora?: string | undefined;
  readonly conforme: boolean;
};

/** As leituras que o *job* faz à base, como porta. */
export type LeituraDoLedger = {
  elosPartidos(): Promise<readonly EloPartido[]>;
  /** As cobranças com eventos, com a projecção e a reconstrução lado a lado. */
  projeccoes(): Promise<readonly ProjeccaoDivergente[]>;
  cabecas(): Promise<readonly CabecaDaCadeia[]>;
};

/**
 * O mínimo do `StorageProvider` (KAM-011) de que este *job* precisa.
 *
 * **Mais estreito do que o `StorageProvider` real, e deliberadamente.** Esse
 * toma um `Ctx` com o tenant, porque tudo o que ele guarda é dado de uma PME; a
 * âncora da cadeia não é — é uma linha por cobrança de **todos** os tenants, e
 * é de plataforma como a cabeça da cadeia de auditoria do KAM-012. Pedir um
 * `Ctx` aqui obrigava a inventar um tenant para a escrever, e um tenant
 * inventado numa chave de armazenamento é pior do que uma porta estreita.
 *
 * Quem liga as duas pontas é o adaptador do serviço, que escolhe o balde de
 * plataforma. Isso fica por fazer aqui — não há `services/pay/` nesta árvore
 * (dívida documental 148) — e está dito no relatório.
 */
export type EscritaDaAncora = {
  put(
    chave: string,
    corpo: Uint8Array,
    meta: { readonly contentType: string },
  ): Promise<unknown>;
};

export type DependenciasDoJob = {
  readonly leitura: LeituraDoLedger;
  readonly armazenamento: EscritaDaAncora;
  alertar?(alerta: string, detalhe: Record<string, unknown>): void;
  /** A data da âncora. Injectada para o ensaio não depender do relógio. */
  readonly hoje?: (() => Date) | undefined;
};

/**
 * Corre a verificação diária. Devolve o relatório; não lança.
 *
 * A ordem é: verificar, **exportar**, alertar. A exportação vem antes dos
 * alertas porque é a parte com valor independente do resultado — ver o
 * comentário de `RelatorioDoLedger`.
 */
export async function verificarLedgerDiariamente(
  deps: DependenciasDoJob,
): Promise<RelatorioDoLedger> {
  // **Cada leitura dentro do seu `try`, e a revisão adversarial mediu porquê.**
  //
  // A primeira versão esperava as três sem guarda, e a docstring prometia «não
  // lança». O `SQL_PROJECCOES_DIVERGENTES` chama o `rebuild_charge_state` para
  // todas as cobranças com eventos, e essa função **levanta** `data_corrupted`
  // num ledger que não reproduz — o que é o alarme certo e a razão de ela
  // levantar. Mas levantava aqui: uma cobrança corrompida abortava a consulta
  // inteira, o *job* lançava contra a sua própria docstring, e **a âncora, que
  // se escreve depois, nunca chegava a ser escrita** — isto é, o alarme de uma
  // cadeia apagava a prova das outras.
  //
  // Agora cada falha vira uma linha do relatório. `conforme` fica falso, ops é
  // alertado, e as outras duas verificações e a âncora correm.
  const elosPartidos = await proteger(deps, "elosPartidos", () =>
    deps.leitura.elosPartidos(),
  );
  const projeccoesDivergentes = await proteger(deps, "projeccoes", () =>
    deps.leitura.projeccoes(),
  );
  const cabecas = await proteger(deps, "cabecas", () => deps.leitura.cabecas());

  let ancora: string | null = null;
  let erroDaAncora: string | undefined;
  const chave = chaveDaAncora(deps.hoje?.() ?? new Date());
  try {
    // A âncora escreve-se com o que se conseguiu ler. Se a leitura das cabeças
    // falhou, escreve-se uma âncora **vazia** e a falha vai no relatório — e
    // não se deixa de escrever: o `leiturasFalhadas` é o que diz que o dia não
    // está verificado, e uma âncora que falta é indistinguível de um dia sem
    // eventos.
    await deps.armazenamento.put(chave, serializarAncora(cabecas.valor ?? []), {
      contentType: "application/json",
    });
    ancora = chave;
  } catch (erro) {
    erroDaAncora = erro instanceof Error ? erro.message : String(erro);
  }

  const leiturasFalhadas = [elosPartidos, projeccoesDivergentes, cabecas]
    .filter((r) => r.erro !== undefined)
    .map((r) => ({ leitura: r.nome, erro: r.erro as string }));
  if (leiturasFalhadas.length > 0) {
    deps.alertar?.(ALERTA_DE_LEITURA, { leituras: leiturasFalhadas });
  }

  const elos = elosPartidos.valor ?? [];
  const projeccoes = projeccoesDivergentes.valor ?? [];
  if (elos.length > 0) {
    deps.alertar?.(ALERTA_DA_CADEIA, {
      elos: elos.length,
      // O primeiro basta para ops abrir o caso; a lista inteira vai no
      // relatorio. Um alerta com mil elos e um alerta que ninguem le.
      primeiro: elos[0],
    });
  }
  if (projeccoes.length > 0) {
    deps.alertar?.(ALERTA_DA_PROJECCAO, {
      cobrancas: projeccoes.length,
      primeira: projeccoes[0],
    });
  }

  return {
    elosPartidos: elosPartidos.valor ?? [],
    projeccoesDivergentes: projeccoesDivergentes.valor ?? [],
    cabecas: cabecas.valor?.length ?? 0,
    leiturasFalhadas,
    ancora,
    erroDaAncora,
    // **A âncora conta para a conformidade.** Um dia sem âncora é um dia em que
    // a cadeia só se pode verificar contra ela própria, e isso não é uma prova
    // contra quem tem a base — ver o cabeçalho.
    // **Uma leitura que falhou não é uma verificação que passou.**
    conforme:
      leiturasFalhadas.length === 0 &&
      elos.length === 0 &&
      projeccoes.length === 0 &&
      ancora !== null,
  };
}

/** O resultado de uma leitura: o valor, ou o erro que a impediu. */
type Leitura<T> = {
  readonly nome: string;
  readonly valor?: T;
  readonly erro?: string;
};

async function proteger<T>(
  deps: DependenciasDoJob,
  nome: string,
  ler: () => Promise<T>,
): Promise<Leitura<T>> {
  try {
    return { nome, valor: await ler() };
  } catch (erro) {
    return { nome, erro: erro instanceof Error ? erro.message : String(erro) };
  }
}

/** `ledger/pagamentos/AAAA-MM-DD.json`, em UTC (dicionário §2). */
export function chaveDaAncora(quando: Date): string {
  const dia = quando.toISOString().slice(0, 10);
  return `${PREFIXO_DA_ANCORA}/${dia}.json`;
}

/**
 * A âncora, em JSON canónico: ordenada por `chargeId` e com os *hashes* em hex.
 *
 * Ordenada porque uma âncora é para **comparar** com a de ontem, e dois
 * ficheiros com as mesmas linhas por outra ordem não se comparam byte a byte.
 * Em hex e não em base64 porque é o que o `encode(…, 'hex')` da base devolve, e
 * uma âncora que se compara à mão vale mais do que uma mais curta.
 */
export function serializarAncora(
  cabecas: readonly CabecaDaCadeia[],
): Uint8Array {
  const linhas = [...cabecas]
    .sort((a, b) => (a.chargeId < b.chargeId ? -1 : a.chargeId > b.chargeId ? 1 : 0))
    .map((cabeca) => ({
      charge_id: cabeca.chargeId,
      tenant_id: cabeca.tenantId,
      event_id: String(cabeca.eventId),
      sequencia: cabeca.sequencia,
      row_hash: hex(cabeca.rowHash),
    }));
  return new TextEncoder().encode(
    JSON.stringify({ versao: 1, cabecas: linhas }, null, 0),
  );
}

function hex(octetos: Uint8Array): string {
  let saida = "";
  for (const octeto of octetos) {
    saida += octeto.toString(16).padStart(2, "0");
  }
  return saida;
}

/** Os elos partidos, em toda a base. Zero linhas é a cadeia intacta. */
export const SQL_ELOS_PARTIDOS = `
  SELECT charge_id, event_id, sequencia, falha
    FROM platform.verify_ledger_chain(NULL)
   ORDER BY charge_id, event_id
`;

/**
 * A projecção contra a reconstrução, numa consulta só.
 *
 * Numa consulta e não numa por cobrança: o *job* é nocturno e a base pode ter
 * dezenas de milhares de cobranças, e uma ida à base por cada uma transforma
 * uma verificação de segundos em minutos de latência de rede. O `WHERE` filtra
 * as cobranças **com eventos** — uma cobrança sem ledger reconstrói para
 * `iniciada`, e compará-la com a projecção não diz nada sobre a porta.
 */
export const SQL_PROJECCOES_DIVERGENTES = `
  SELECT c.id, c.estado, platform.rebuild_charge_state(c.id)
    FROM platform.payment_charges c
   WHERE EXISTS (
           SELECT 1 FROM platform.payment_events e WHERE e.charge_id = c.id)
     AND platform.rebuild_charge_state(c.id) <> c.estado
   ORDER BY c.id
`;

/** A cabeça da cadeia de cada cobrança, para a âncora. */
export const SQL_CABECAS = `
  SELECT charge_id, tenant_id, event_id, sequencia, row_hash
    FROM platform.v_payment_ledger_heads
   ORDER BY charge_id
`;

/**
 * Os nomes que a suite de base de dados exercita deste módulo, nos dois
 * sentidos — ver a nota de `CADEIAS_EXERCITADAS` em `hooks.ts`.
 */
export const CADEIAS_DO_JOB = [
  "SQL_ELOS_PARTIDOS",
  "SQL_PROJECCOES_DIVERGENTES",
  "SQL_CABECAS",
] as const;

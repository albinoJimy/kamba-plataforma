/**
 * O encerramento de um tenant, do pedido à revogação (KAM-098).
 *
 * Quatro das sete fases de `platform.offboarding_run` — `verificacao`,
 * `pendentes`, `canal` e `revogacao` — e o cancelamento. As outras três são do
 * Python (ver `contrato.ts`). Corre como `kamba_batch`, que tem `BYPASSRLS`,
 * `INSERT` e `UPDATE (estado, resultado)` na tabela, e `EXECUTE` no
 * `transition_tenant` e no `evt_emitir` (`0058`).
 *
 * ## Cada fase é idempotente, e um *crash* a meio retoma no passo seguinte
 *
 * Critério 9. Três regras, as mesmas da régua de cobrança (KAM-058):
 *
 * 1. **A fase lê-se antes do efeito, sob trinco.** Cada transacção começa por
 *    `SELECT … FOR UPDATE` na linha da fase; uma fase `concluida` devolve sem
 *    fazer nada, e duas chamadas concorrentes não fazem o efeito duas vezes.
 * 2. **O progresso grava-se por passo**, no `resultado` da fase, na mesma
 *    transacção que o efeito que é desta base. Os efeitos de fora (a Meta, o
 *    LiteLLM, a Medusa, o Chatwoot) correm **antes** dessa transacção e são
 *    idempotentes do lado deles: um *crash* entre os dois repete a chamada de
 *    fora, e não a salta.
 * 3. **O evento sai na transacção da transição**, só quando o
 *    `transition_tenant` devolve verdadeiro. Repetir dá falso, e não há segundo
 *    `tenant.closed`.
 *
 * ## O WABA e o número do cliente nunca se apagam
 *
 * Critério 3, evidência E1. **Toda** a acção sobre a Meta passa pelo
 * `executarNoCanalDoCliente` da saga (`provisioning/compensacao.ts`), que
 * recusa em execução uma acção destrutiva sobre o WABA ou o número. E toda a
 * acção sobre os recursos nossos passa pelo `verificar` do mesmo módulo, que
 * recusa uma declaração incoerente. É a «mesma estrutura de estado e
 * compensação da saga» do critério 5 — e não uma cópia dela.
 */

import { executarNoCanalDoCliente, accoesDoCanalDoCliente, verificar } from "../provisioning/compensacao.ts";
import type { AccaoDeCompensacao, Passo } from "../provisioning/contrato.ts";
import { SQL_DEFINIR_CONTEXTO } from "../tenant_guard/index.ts";
import {
  ACTOR_DO_ENCERRAMENTO,
  AVISO_DA_APP_BUSINESS,
  ConfirmacaoIncompletaError,
  EstadoDoTenantError,
  FASES,
  FaseForaDeOrdemError,
  MOTIVO_DO_ENCERRAMENTO,
  PedidoError,
  cancelavel,
  podeComecar,
  prazos,
  type CanalDaMeta,
  type EstadoDaFase,
  type Fase,
  type Origem,
  type PortasDaRevogacao,
  type ProvasDoTitular,
} from "./contrato.ts";

/** O mínimo de um cliente `pg` de que este módulo precisa. */
export interface ClienteSql {
  query(sql: string, parametros?: readonly unknown[]): Promise<{ rows: Record<string, unknown>[]; rowCount?: number | null }>;
}

type Resultado = Record<string, unknown>;

/** Uma linha de `platform.offboarding_run`. */
export interface LinhaDaFase {
  readonly fase: Fase;
  readonly estado: EstadoDaFase;
  readonly prazoAt: Date;
  readonly resultado: Resultado;
}

// ------------------------------------------------------------------ SQL

export const SQL_ESTADO_DO_TENANT = `
  SELECT estado FROM platform.tenants WHERE id = $1 FOR UPDATE
`;

/** As fases do tenant, trancadas. A ordem é a das fases, e não a da inserção. */
export const SQL_FASES = `
  SELECT fase, estado, prazo_at, resultado
    FROM platform.offboarding_run
   WHERE tenant_id = $1
   FOR UPDATE
`;

/**
 * Uma fase nova. **Sem `ON CONFLICT`**: o pedido tranca o tenant e pergunta
 * antes, e uma segunda linha com a mesma chave é um defeito que tem de falhar
 * alto (`23505`), não ser engolido.
 */
export const SQL_ABRIR_FASE = `
  INSERT INTO platform.offboarding_run (tenant_id, fase, estado, prazo_at, resultado)
  VALUES ($1, $2, $3, $4, $5::jsonb)
`;

/** O estado e o resultado de uma fase. As duas colunas que o `kamba_batch` pode mudar. */
export const SQL_MARCAR_FASE = `
  UPDATE platform.offboarding_run
     SET estado = $3, resultado = $4::jsonb
   WHERE tenant_id = $1 AND fase = $2
`;

/**
 * O que ainda está por fechar (critério 2). **Encomendas em curso** são as que
 * não chegaram a um estado final do grafo da `0030` (`expirada`, `entregue`,
 * `reembolsada`, `cancelada`) e não estão em disputa; **em disputa** contam à
 * parte, porque não impedem a exportação e suspendem a purga. **Reservas** são
 * as `ativa`. **Reembolsos** são os `aberto` e os `a_executar_pela_pme`.
 */
export const SQL_PENDENTES = `
  SELECT
    (SELECT count(*) FROM platform.orders_mirror
      WHERE tenant_id = $1
        AND estado NOT IN ('expirada', 'entregue', 'reembolsada', 'cancelada', 'em_disputa'))::int AS encomendas,
    (SELECT count(*) FROM platform.orders_mirror
      WHERE tenant_id = $1 AND estado = 'em_disputa')::int AS disputas,
    (SELECT count(*) FROM platform.stock_reservations
      WHERE tenant_id = $1 AND estado = 'ativa')::int AS reservas,
    (SELECT count(*) FROM platform.refund_cases
      WHERE tenant_id = $1 AND estado IN ('aberto', 'a_executar_pela_pme'))::int AS reembolsos
`;

/** Os canais que ainda encaminham. Um `desligado` ou `encerrado` já não. */
export const SQL_CANAIS_LIGADOS = `
  SELECT id::text AS id, waba_id, estado
    FROM platform.tenant_channels
   WHERE tenant_id = $1 AND estado NOT IN ('desligado', 'encerrado')
   ORDER BY id
`;

/** Desliga um canal, só a partir do estado que se leu (a corrida perde e repete). */
export const SQL_DESLIGAR_CANAL = `
  UPDATE platform.tenant_channels SET estado = 'desligado'
   WHERE id = $1 AND tenant_id = $2 AND estado = $3
`;

/** Religa um canal desligado por este pedido, para o estado de antes (cancelamento). */
export const SQL_RELIGAR_CANAL = `
  UPDATE platform.tenant_channels SET estado = $3
   WHERE id = $1 AND tenant_id = $2 AND estado = 'desligado'
`;

/** As referências externas que a saga deixou, por passo concluído. */
export const SQL_RECURSOS_DA_SAGA = `
  SELECT step, external_id
    FROM platform.provisioning_step
   WHERE tenant_id = $1 AND status = 'concluido' AND external_id IS NOT NULL
`;

/** Os entitlements desligados (critério 5: `ativo = false`). */
export const SQL_DESLIGAR_ENTITLEMENTS = `
  UPDATE platform.entitlements SET ativo = false WHERE tenant_id = $1 AND ativo
`;

/** Os canais encerrados: a rota sai do CHR, e o número continua do cliente. */
export const SQL_ENCERRAR_CANAIS = `
  UPDATE platform.tenant_channels SET estado = 'encerrado'
   WHERE tenant_id = $1 AND estado <> 'encerrado'
`;

export const SQL_TRANSITAR = `
  SELECT platform.transition_tenant($1::uuid, 'encerrado', $2, $3) AS mudou
`;

/** O evento, na transacção da transição. A forma do `SQL_REGUA_EMITIR`. */
export const SQL_EMITIR = `
  SELECT platform.evt_emitir($1, $2::smallint, $3::uuid, $4, $5, $6::jsonb) AS event_id
`;

/**
 * Um facto do encerramento no `audit_log`, pela porta da `0006`. A acção é a
 * `batch.run` do domínio fechado (a forma da régua); a entidade é a fase; o
 * `payload_hash` é o SHA-256 de um texto sem nada do dono.
 */
export const SQL_AUDITAR = `
  SELECT platform.audit_append(
           $1::uuid, 'system', $2, 'batch.run', $3, $1::text, NULL,
           sha256(convert_to($4, 'UTF8')))
`;

// ------------------------------------------------------------- utilidades

function texto(valor: unknown): string {
  return String(valor);
}

function objecto(valor: unknown): Resultado {
  if (typeof valor === "string") return JSON.parse(valor) as Resultado;
  return (valor ?? {}) as Resultado;
}

function linhaDe(r: Record<string, unknown>): LinhaDaFase {
  return {
    fase: texto(r.fase) as Fase,
    estado: texto(r.estado) as EstadoDaFase,
    prazoAt: r.prazo_at instanceof Date ? r.prazo_at : new Date(texto(r.prazo_at)),
    resultado: objecto(r.resultado),
  };
}

/** Uma transacção com o contexto do tenant (o `transition_tenant` exige-o). */
async function emTransaccao<T>(bd: ClienteSql, tenantId: string, trabalho: () => Promise<T>): Promise<T> {
  await bd.query("BEGIN");
  try {
    await bd.query(SQL_DEFINIR_CONTEXTO, [tenantId]);
    const valor = await trabalho();
    await bd.query("COMMIT");
    return valor;
  } catch (erro) {
    await bd.query("ROLLBACK");
    throw erro;
  }
}

async function fases(bd: ClienteSql, tenantId: string): Promise<Map<Fase, LinhaDaFase>> {
  const { rows } = await bd.query(SQL_FASES, [tenantId]);
  return new Map(rows.map((r) => [texto(r.fase) as Fase, linhaDe(r)]));
}

function d0De(linhas: Map<Fase, LinhaDaFase>): Date {
  const v = linhas.get("verificacao");
  if (v === undefined) throw new PedidoError("nao ha pedido de encerramento para este tenant");
  return v.prazoAt;
}

function exigirPedidoVivo(linhas: Map<Fase, LinhaDaFase>, fase: Fase): void {
  const v = linhas.get("verificacao");
  if (v === undefined) throw new FaseForaDeOrdemError(fase, "nao ha pedido");
  if (v.estado !== "concluida") throw new FaseForaDeOrdemError(fase, "o pedido nao foi verificado");
  if (v.resultado.cancelado_at !== undefined) throw new FaseForaDeOrdemError(fase, "o pedido foi cancelado");
}

async function marcar(bd: ClienteSql, tenantId: string, fase: Fase, estado: EstadoDaFase, resultado: Resultado) {
  await bd.query(SQL_MARCAR_FASE, [tenantId, fase, estado, JSON.stringify(resultado)]);
}

async function auditar(bd: ClienteSql, tenantId: string, fase: Fase, resumo: string) {
  await bd.query(SQL_AUDITAR, [tenantId, ACTOR_DO_ENCERRAMENTO, `offboarding_${fase}`, resumo]);
}

// ------------------------------------------------------------ o pedido

export type PedidoDoTitular = {
  readonly tenantId: string;
  readonly origem: "titular";
  /** O código do OTP mandado ao telefone provado. */
  readonly otp: string | null;
  /** O *token* da ligação mandada ao e-mail registado. */
  readonly tokenDoEmail: string | null;
  readonly agora: Date;
};

export type PedidoDeTrustSafety = {
  readonly tenantId: string;
  readonly origem: "trust_safety";
  /**
   * O `id` da sanção `encerramento` do KAM-097 (`platform.ts_sanction`), que tem
   * de existir para o tenant e não ter recurso provido. Guarda-se só o SHA-256.
   */
  readonly decisaoRef: string;
  readonly agora: Date;
};

export type RespostaDoPedido = {
  /** `false` quando o pedido já existia: repetir não abre outro. */
  readonly aberto: boolean;
  readonly d0: Date;
  readonly aviso: string;
};

/**
 * A sanção de encerramento do KAM-097, para o tenant, sem recurso provido. É o
 * que faz de um pedido de T&S uma decisão de T&S, e não uma referência qualquer
 * (achado 8 da revisão adversarial).
 */
export const SQL_SANCAO_DE_ENCERRAMENTO = `
  SELECT 1 FROM platform.ts_sanction s
   WHERE s.id = $1::uuid AND s.tenant_id = $2 AND s.passo = 'encerramento'
     AND s.recurso_de IS NULL
     AND NOT EXISTS (SELECT 1 FROM platform.ts_sanction r
                      WHERE r.recurso_de = s.id AND r.recurso_estado = 'provido')
`;

/**
 * Reabre uma fase de um pedido cancelado, com o prazo do calendário novo. É a
 * única escrita do `prazo_at` depois do pedido (a revisão concede o `UPDATE`
 * dele por isso), e só a faz um pedido verificado de novo.
 */
export const SQL_REABRIR_FASE = `
  UPDATE platform.offboarding_run
     SET estado = $3, prazo_at = $4, resultado = $5::jsonb
   WHERE tenant_id = $1 AND fase = $2
`;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Abre o pedido de encerramento (fase `verificacao`, critério 1).
 *
 * **Pelo titular**: exige as duas provas, e as duas são perguntadas — uma falta
 * não deixa a outra por perguntar, e o erro diz quais faltaram. As provas
 * verifica-as a porta que o processo injecta (`provas`), e não o pedido: o
 * pedido traz só os códigos. O tenant tem de estar `ativo` ou `suspenso`.
 * **Por T&S**: exige o tenant `suspenso` (a aresta `suspenso -> encerrado` do
 * bloco) e uma sanção `encerramento` do KAM-097 em vigor para ele.
 *
 * **Um tenant `restrito` não se encerra**: o grafo da `0058` não tem a aresta
 * `restrito -> encerrado`, e acrescentá-la é decidir o que a restrição da Meta
 * permite — volta ao fundador.
 *
 * Escreve as sete fases de uma vez, com os prazos do calendário. Repetir devolve
 * o pedido que existe. **Um pedido cancelado reabre-se** com um pedido novo
 * verificado, e o calendário recomeça do novo D0. **Um pedido de T&S sobre um
 * pedido vivo do titular toma-o**: a origem passa a T&S, e deixa de se poder
 * cancelar — senão um titular que previsse a sanção pedia e cancelava, e
 * ficava fora do alcance dela (achado 1 da revisão adversarial).
 */
export async function abrirPedido(
  bd: ClienteSql,
  pedido: PedidoDoTitular | PedidoDeTrustSafety,
  provas: ProvasDoTitular | null = null,
): Promise<RespostaDoPedido> {
  let prova: Resultado;
  if (pedido.origem === "titular") {
    if (provas === null) throw new ConfirmacaoIncompletaError(["otp", "email"]);
    const falta: string[] = [];
    const otp = pedido.otp !== null && pedido.otp !== "" && (await provas.otpConfere(pedido.tenantId, pedido.otp));
    if (!otp) falta.push("otp");
    const email =
      pedido.tokenDoEmail !== null &&
      pedido.tokenDoEmail !== "" &&
      (await provas.ligacaoDoEmailConfere(pedido.tenantId, pedido.tokenDoEmail));
    if (!email) falta.push("email");
    if (falta.length > 0) throw new ConfirmacaoIncompletaError(falta);
    prova = { confirmacoes: ["otp", "email"] };
  } else {
    if (!UUID.test(pedido.decisaoRef)) throw new ConfirmacaoIncompletaError(["decisao_ref"]);
    prova = { decisao: true };
  }
  const origem: Origem = pedido.origem;

  return emTransaccao(bd, pedido.tenantId, async () => {
    const estado = texto((await bd.query(SQL_ESTADO_DO_TENANT, [pedido.tenantId])).rows[0]?.estado);
    if (pedido.origem === "trust_safety") {
      const s = await bd.query(SQL_SANCAO_DE_ENCERRAMENTO, [pedido.decisaoRef, pedido.tenantId]);
      if (s.rows.length === 0) throw new ConfirmacaoIncompletaError(["sancao_de_encerramento"]);
    }
    const aceites = origem === "titular" ? ["ativo", "suspenso"] : ["suspenso"];
    const existentes = await fases(bd, pedido.tenantId);
    const v = existentes.get("verificacao");
    const resumo = pedido.origem === "titular" ? `pedido:${origem}` : `pedido:${origem}:${pedido.decisaoRef}`;
    if (v !== undefined && v.resultado.cancelado_at === undefined) {
      if (origem === "trust_safety" && v.resultado.origem !== "trust_safety") {
        await marcar(bd, pedido.tenantId, "verificacao", v.estado, {
          ...v.resultado,
          origem,
          ...prova,
          tomado_por_ts_at: pedido.agora.toISOString(),
        });
        await auditar(bd, pedido.tenantId, "verificacao", resumo);
      }
      return { aberto: false, d0: d0De(existentes), aviso: AVISO_DA_APP_BUSINESS };
    }
    if (!aceites.includes(estado)) throw new EstadoDoTenantError(estado, origem);
    const p = prazos(pedido.agora);
    for (const fase of FASES) {
      const resultado =
        fase === "verificacao"
          ? {
              origem,
              ...prova,
              d0: pedido.agora.toISOString(),
              aviso: true,
              ...(v === undefined ? {} : { reaberto_de: texto(v.resultado.d0) }),
            }
          : {};
      const parametros = [
        pedido.tenantId,
        fase,
        fase === "verificacao" ? "concluida" : "pendente",
        p[fase],
        JSON.stringify(resultado),
      ];
      await bd.query(v === undefined ? SQL_ABRIR_FASE : SQL_REABRIR_FASE, parametros);
    }
    await auditar(bd, pedido.tenantId, "verificacao", v === undefined ? resumo : `reaberto:${resumo}`);
    return { aberto: true, d0: pedido.agora, aviso: AVISO_DA_APP_BUSINESS };
  });
}

/**
 * Cancela o pedido até D7 (critério 1; adversarial b: «nada apagado»).
 *
 * **Só o do titular.** Uma decisão de T&S não a cancela o dono (achado 1 da
 * revisão adversarial).
 *
 * Religa primeiro os canais que este pedido desligou — a subscrição de
 * *webhooks* volta a fazer-se e o canal volta ao estado de antes —, e só depois
 * marca as fases por fazer `cancelada`, numa transacção que volta a verificar
 * o prazo e a revogação. O canal fica `cancelada` também, porque foi desfeito;
 * uma exportação já gerada fica `concluida`, porque aconteceu. Um *crash* entre
 * as duas deixa o pedido por cancelar com o canal religado, e repetir cancela.
 */
export async function cancelarPedido(
  bd: ClienteSql,
  opcoes: { readonly tenantId: string; readonly canal: CanalDaMeta; readonly agora: Date },
): Promise<{ readonly religados: number }> {
  const { tenantId, agora } = opcoes;
  const verificarCancelavel = (linhas: Map<Fase, LinhaDaFase>): boolean => {
    const v = linhas.get("verificacao");
    if (v === undefined) throw new PedidoError("nao ha pedido de encerramento para este tenant");
    if (v.resultado.cancelado_at !== undefined) return false;
    if (v.resultado.origem === "trust_safety") throw new PedidoError("um encerramento de T&S nao o cancela o titular");
    if (!cancelavel(d0De(linhas), agora)) throw new PedidoError("o pedido ja nao se cancela: passou o D7");
    if (linhas.get("revogacao")?.estado === "concluida") throw new PedidoError("a revogacao ja correu");
    return true;
  };
  const canalFeito = await emTransaccao(bd, tenantId, async () => {
    const linhas = await fases(bd, tenantId);
    if (!verificarCancelavel(linhas)) return null;
    return (linhas.get("canal")?.resultado.canais ?? []) as { id: string; waba_id: string; de: string }[];
  });
  if (canalFeito === null) return { religados: 0 };

  let religados = 0;
  for (const c of canalFeito) {
    // A subscrição é do WABA do cliente, e voltar a fazê-la não é destrutivo:
    // é o que a saga fez no passo `espera_es`. Idempotente do lado da Meta.
    await opcoes.canal.subscreverWebhooks(c.waba_id);
    const r = await emTransaccao(bd, tenantId, () => bd.query(SQL_RELIGAR_CANAL, [c.id, tenantId, c.de]));
    religados += r.rowCount ?? 0;
  }

  await emTransaccao(bd, tenantId, async () => {
    const linhas = await fases(bd, tenantId);
    if (!verificarCancelavel(linhas)) return;
    for (const [fase, linha] of linhas) {
      if (fase === "verificacao") {
        await marcar(bd, tenantId, fase, linha.estado, { ...linha.resultado, cancelado_at: agora.toISOString() });
      } else if (fase === "canal" || linha.estado !== "concluida") {
        await marcar(bd, tenantId, fase, "cancelada", linha.resultado);
      }
    }
    await auditar(bd, tenantId, "verificacao", "cancelado");
  });
  return { religados };
}

// ----------------------------------------------------------- pendentes

export type Pendentes = {
  readonly encomendas: number;
  readonly disputas: number;
  readonly reservas: number;
  readonly reembolsos: number;
};

/**
 * A fase `pendentes` (critério 2): conta o que ainda está aberto. Sem
 * pendentes, a fase conclui e a exportação pode arrancar; com pendentes, fica
 * `em_curso` com as contagens, e volta-se a perguntar.
 *
 * **Fechar** as encomendas, as reservas e os reembolsos não é desta fase: são
 * decisões do dono e de ops pelos caminhos que cada um já tem (o grafo da
 * `0030`, a libertação da `0033`, o reembolso manual da `0032`). Esta fase é o
 * portão que impede a exportação de sair com uma encomenda a meio.
 *
 * Uma disputa aberta **não** impede a exportação, e fica escrita no resultado:
 * é o que a purga lê para se suspender (`suspensa_disputa`).
 */
export async function verificarPendentes(
  bd: ClienteSql,
  opcoes: { readonly tenantId: string; readonly agora: Date },
): Promise<{ readonly concluida: boolean; readonly pendentes: Pendentes }> {
  const { tenantId } = opcoes;
  return emTransaccao(bd, tenantId, async () => {
    const linhas = await fases(bd, tenantId);
    exigirPedidoVivo(linhas, "pendentes");
    const r = (await bd.query(SQL_PENDENTES, [tenantId])).rows[0] ?? {};
    const pendentes: Pendentes = {
      encomendas: Number(r.encomendas ?? 0),
      disputas: Number(r.disputas ?? 0),
      reservas: Number(r.reservas ?? 0),
      reembolsos: Number(r.reembolsos ?? 0),
    };
    const concluida = pendentes.encomendas + pendentes.reservas + pendentes.reembolsos === 0;
    const anterior = linhas.get("pendentes");
    if (anterior?.estado === "concluida") return { concluida: true, pendentes };
    await marcar(bd, tenantId, "pendentes", concluida ? "concluida" : "em_curso", {
      ...pendentes,
      disputa: pendentes.disputas > 0,
      verificado_at: opcoes.agora.toISOString(),
    });
    return { concluida, pendentes };
  });
}

// --------------------------------------------------------------- canal

/**
 * O passo da saga sob o qual a acção sobre o WABA se declara. É o passo que
 * subscreveu os *webhooks* (`espera_es`), e o guarda escreve-o na mensagem de
 * erro de uma acção recusada.
 */
const PASSO_DO_CANAL: Passo = "espera_es";

/**
 * A fase `canal` (critério 3): cancela a subscrição de *webhooks* de cada WABA
 * do tenant e desliga o canal na base — o CHR deixa de encaminhar, porque a
 * matriz de estados (`ten/estados.ts`) não deixa um canal `desligado` chegar ao
 * AGR. **O WABA e o número ficam intactos**: a única acção sobre eles é a que o
 * `accoesDoCanalDoCliente` da saga declara, e passa pelo guarda.
 *
 * Corre logo no D0, e é ela que **bloqueia novas encomendas** do critério 1:
 * o caminho de uma encomenda nova é a conversa, e um canal desligado não abre
 * conversa com o AGR. Cada canal grava o estado de antes no resultado, na
 * transacção que o desliga — é o que o cancelamento usa para o religar.
 */
export async function desligarCanal(
  bd: ClienteSql,
  opcoes: { readonly tenantId: string; readonly canal: CanalDaMeta; readonly agora: Date },
): Promise<{ readonly desligados: number }> {
  const { tenantId } = opcoes;
  const ligados = await emTransaccao(bd, tenantId, async () => {
    const linhas = await fases(bd, tenantId);
    exigirPedidoVivo(linhas, "canal");
    if (linhas.get("canal")?.estado === "concluida") return null;
    return (await bd.query(SQL_CANAIS_LIGADOS, [tenantId])).rows;
  });
  if (ligados === null) return { desligados: 0 };

  let desligados = 0;
  for (const c of ligados) {
    const canal = { id: texto(c.id), waba_id: texto(c.waba_id), de: texto(c.estado) };
    // **Antes da Meta**, o pedido tem de estar vivo: um cancelamento que acabou
    // entre a leitura e aqui não pode ser seguido de uma dessubscrição (achado 5
    // da revisão adversarial).
    await emTransaccao(bd, tenantId, async () => exigirPedidoVivo(await fases(bd, tenantId), "canal"));
    for (const accao of accoesDoCanalDoCliente(canal.waba_id)) {
      await executarNoCanalDoCliente(opcoes.canal, accao, PASSO_DO_CANAL);
    }
    let cancelado = false;
    await emTransaccao(bd, tenantId, async () => {
      const vivo = await fases(bd, tenantId);
      if (vivo.get("verificacao")?.resultado.cancelado_at !== undefined) {
        cancelado = true;
        return;
      }
      const r = await bd.query(SQL_DESLIGAR_CANAL, [canal.id, tenantId, canal.de]);
      if ((r.rowCount ?? 0) === 0) return;
      desligados += 1;
      const linha = (await fases(bd, tenantId)).get("canal");
      const canais = [...((linha?.resultado.canais ?? []) as unknown[]), canal];
      await marcar(bd, tenantId, "canal", "em_curso", { ...linha?.resultado, canais });
    });
    if (cancelado) {
      // O cancelamento ganhou a corrida depois da Meta: desfaz-se a dessubscrição,
      // e o canal fica como o cancelamento o deixou.
      await opcoes.canal.subscreverWebhooks(canal.waba_id);
      throw new FaseForaDeOrdemError("canal", "o pedido foi cancelado a meio");
    }
  }

  await emTransaccao(bd, tenantId, async () => {
    const vivo = await fases(bd, tenantId);
    exigirPedidoVivo(vivo, "canal");
    const linha = vivo.get("canal");
    await marcar(bd, tenantId, "canal", "concluida", {
      canais: [],
      ...linha?.resultado,
      desligado_at: opcoes.agora.toISOString(),
    });
    await auditar(bd, tenantId, "canal", `canal:${desligados}`);
  });
  return { desligados };
}

// ----------------------------------------------------------- revogação

/** Os passos da revogação, pela ordem. O resultado guarda o progresso de cada um. */
export const PASSOS_DA_REVOGACAO = [
  "chave_llm",
  "canal_comercio",
  "inbox",
  "entitlements",
  "canais",
  "encerramento",
] as const;
export type PassoDaRevogacao = (typeof PASSOS_DA_REVOGACAO)[number];

/** O passo da saga (KAM-091) onde cada recurso externo foi criado, e onde está o `external_id`. */
const PASSO_DA_SAGA: Readonly<Record<"chave_llm" | "canal_comercio" | "inbox", Passo>> = {
  chave_llm: "chave_llm",
  canal_comercio: "canal_comercio",
  inbox: "inbox_e_rota",
};

/**
 * A fase `revogacao` (critério 5), no D7 e só com a exportação concluída: a
 * chave do LiteLLM revogada, o canal da Medusa arquivado, a *inbox* do Chatwoot
 * desligada, os entitlements a `ativo = false`, os canais `encerrado` e o
 * tenant `encerrado` com o `tenant.closed` (bloco: «emite `tenant.closed` no
 * fim da revogação»).
 *
 * Cada passo grava o seu desfecho no resultado (`concluido` ou `sem_recurso`)
 * numa transacção própria; um passo já gravado não corre outra vez. Um recurso
 * de fora sem `external_id` na saga é `sem_recurso` — a saga nunca o criou, e
 * não há nada a revogar.
 */
export async function revogar(
  bd: ClienteSql,
  opcoes: { readonly tenantId: string; readonly portas: PortasDaRevogacao; readonly agora: Date },
): Promise<{ readonly passos: Readonly<Record<string, string>>; readonly encerrado: boolean }> {
  const { tenantId, portas, agora } = opcoes;
  const inicio = await emTransaccao(bd, tenantId, async () => {
    const linhas = await fases(bd, tenantId);
    exigirPedidoVivo(linhas, "revogacao");
    if (!podeComecar("revogacao", d0De(linhas), agora)) {
      throw new FaseForaDeOrdemError("revogacao", "o pedido ainda se pode cancelar (antes do D7)");
    }
    if (linhas.get("exportacao")?.estado !== "concluida") {
      throw new FaseForaDeOrdemError("revogacao", "a exportacao nao foi concluida");
    }
    // O canal tem de estar desligado: sem isso a subscricao na Meta ficava viva
    // e o aviso ao dono mentia (achado 2 da revisao adversarial).
    if (linhas.get("canal")?.estado !== "concluida") {
      throw new FaseForaDeOrdemError("revogacao", "o canal nao foi desligado");
    }
    // **Antes de qualquer porta**: um tenant que ficou `restrito` depois do
    // pedido nao tem aresta para `encerrado`, e revogar a chave e a Medusa para
    // depois falhar a transicao deixava-o a meio para sempre (achado 3).
    const estado = texto((await bd.query(SQL_ESTADO_DO_TENANT, [tenantId])).rows[0]?.estado);
    if (!["ativo", "suspenso", "encerrado"].includes(estado)) {
      throw new FaseForaDeOrdemError("revogacao", `o tenant esta ${estado}, e dai nao se encerra`);
    }
    const linha = linhas.get("revogacao");
    const origem = texto(linhas.get("verificacao")?.resultado.origem) as Origem;
    const recursos = new Map(
      (await bd.query(SQL_RECURSOS_DA_SAGA, [tenantId])).rows.map((r) => [texto(r.step), texto(r.external_id)]),
    );
    return { linha, origem, recursos };
  });
  const feitos: Record<string, string> = { ...((inicio.linha?.resultado.passos ?? {}) as Record<string, string>) };
  if (inicio.linha?.estado === "concluida") return { passos: feitos, encerrado: false };

  const gravar = (passo: PassoDaRevogacao, desfecho: string) =>
    emTransaccao(bd, tenantId, async () => {
      feitos[passo] = desfecho;
      await marcar(bd, tenantId, "revogacao", "em_curso", { passos: { ...feitos } });
    });

  let encerrado = false;
  for (const passo of PASSOS_DA_REVOGACAO) {
    if (feitos[passo] !== undefined) continue;
    if (passo === "chave_llm" || passo === "canal_comercio" || passo === "inbox") {
      const ref = inicio.recursos.get(PASSO_DA_SAGA[passo]);
      if (ref === undefined) {
        await gravar(passo, "sem_recurso");
        continue;
      }
      const accao: AccaoDeCompensacao =
        passo === "chave_llm"
          ? { tipo: "revogar", recurso: "chave_llm", ref }
          : passo === "canal_comercio"
            ? { tipo: "arquivar", recurso: "canal_comercio", ref }
            : { tipo: "desactivar", recurso: "inbox", ref };
      verificar(accao, PASSO_DA_SAGA[passo]);
      if (passo === "chave_llm") await portas.chaveDeLlm.revogar(ref);
      else if (passo === "canal_comercio") await portas.canalDeComercio.arquivar(ref);
      else await portas.inbox.desligar(ref);
      await gravar(passo, "concluido");
    } else if (passo === "entitlements" || passo === "canais") {
      await emTransaccao(bd, tenantId, async () => {
        await bd.query(passo === "entitlements" ? SQL_DESLIGAR_ENTITLEMENTS : SQL_ENCERRAR_CANAIS, [tenantId]);
        feitos[passo] = "concluido";
        await marcar(bd, tenantId, "revogacao", "em_curso", { passos: { ...feitos } });
      });
    } else {
      await emTransaccao(bd, tenantId, async () => {
        const motivo = MOTIVO_DO_ENCERRAMENTO[inicio.origem];
        const t = await bd.query(SQL_TRANSITAR, [tenantId, motivo, ACTOR_DO_ENCERRAMENTO]);
        if (t.rows[0]?.mudou === true) {
          await bd.query(SQL_EMITIR, ["tenant.closed", 1, tenantId, "tenant", tenantId, JSON.stringify({ motivo })]);
          await auditar(bd, tenantId, "revogacao", `encerrado:${motivo}`);
          encerrado = true;
        }
        feitos[passo] = "concluido";
        await marcar(bd, tenantId, "revogacao", "concluida", {
          passos: { ...feitos },
          revogado_at: agora.toISOString(),
        });
      });
    }
  }
  return { passos: feitos, encerrado };
}

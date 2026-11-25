/**
 * A rota interna do guia no processo de lote (KAM-239), e a volta do guia.
 *
 * ```text
 * POST /interno/guia/reservar   a vaga do popup (CapacityGate.reserve): granted | lista_espera
 * POST /interno/guia/libertar   a vaga de volta (CapacityGate.release)
 * POST /interno/guia/posicao    a posição na lista de espera
 * POST /interno/guia/convite    o convite ainda vale? Só lê
 * POST /interno/guia/recusar    recusa o convite
 * POST /interno/guia/desistir   sai da lista
 * POST /interno/guia/gate       um dos dois gates do guia (meta_es, meta_pagamento)
 * POST /interno/guia/revisao    abre o caso es_falhado na fila de revisão
 * ```
 *
 * ## Porque existe (decisão do fundador de 2026-11-22, A)
 *
 * O `onboarding-web` não tem ligação `kamba_batch` (D2-A do KAM-236), e a lista de
 * espera, os *gates* do guia e a fila de revisão só correm com ele. A reserva e as
 * quatro da lista respondem **dentro do pedido do dono** — o popup do `FB.login`
 * só abre perto do clique —, pelo que uma tabela de pedidos (B) ou um evento (C),
 * que o fundador recusou, deixavam-nas assíncronas. O custo aceite é este: uma
 * superfície HTTP num processo que passa a RLS. Para que seja pequeno:
 *
 * * **só as oito operações acima**, cada uma com o corpo que ela lê e mais nada.
 *   O identificador é o `onboarding_id` com forma de UUID; **nenhuma lê um
 *   tenant** do pedido — o tenant de um *gate* ou de um caso de revisão sai do
 *   caso, na base. Qualquer outro caminho é 404;
 * * **recusa sem a credencial** (`onboarding_lote_token`), antes de ler o corpo,
 *   com comparação em tempo constante, e 401 igual para ausente e errada;
 * * **não escuta fora da rede `app`**: a casca liga esta app ao anfitrião
 *   `LOTE_INTERNO_HOST`, que no compose de `prod` é um nome que só a rede `app`
 *   resolve, e nunca à porta das métricas;
 * * tem o seu caso no X-01 do *gate* 6.
 *
 * O dono nunca chega aqui. Quem prova que o caso é da sessão é o `onboarding-web`
 * (`comSessao`); esta rota confia no chamador que tem a credencial, como a API
 * interna do COM confia no `x-kamba-tenant` de quem tem a `com_internal_token`.
 */

import { timingSafeEqual } from "node:crypto";

import { serve } from "@hono/node-server";
import { Hono } from "hono";

import type { Logger } from "@kamba/core-ts/logger";
import {
  ListaRecusadaError,
  type ListaDeEspera,
  type Posicao,
} from "@kamba/core-ts/capacidade";
import {
  MOTIVOS_DE_FALHA,
  PRAZO_DE_ABANDONO_MIN,
  abandonarVencidosNaBase,
  abrirRevisoesEmFaltaNaBase,
  reconciliarMetaEsNaBase,
  type FilaDeRevisao,
  type GatesDoOnboarding,
  type MotivoDeFalha,
} from "@kamba/core-ts/guia";
import type { ClienteSql } from "@kamba/core-ts/tenant_guard";

/** O cabeçalho da credencial. O nome é o da API interna do COM. */
export const CABECALHO_DO_LOTE = "x-kamba-interno";

/** O segredo da credencial, no cofre e no inventário. */
export const REF_DA_CREDENCIAL_DO_LOTE = "onboarding_lote_token";

/** O prefixo das oito operações. */
export const PREFIXO_DO_GUIA = "/interno/guia";

/** As oito operações, pelo nome do caminho. Lista fechada. */
export const OPERACOES_DO_GUIA = [
  "reservar",
  "libertar",
  "posicao",
  "convite",
  "recusar",
  "desistir",
  "gate",
  "revisao",
] as const;
export type OperacaoDoGuia = (typeof OPERACOES_DO_GUIA)[number];

/** Os dois gates que o guia escreve. Iguais ao `GateDoEs`. */
export const GATES_DO_GUIA = ["meta_es", "meta_pagamento"] as const;

/** A forma de um motivo de gate: um identificador curto, nunca texto do dono. */
const MOTIVO_DO_GATE = /^[a-z][a-z0-9_]{0,63}$/;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O que a rota interna serve: a lista sobre a base, os gates e a fila, todos como `kamba_batch`. */
export interface OpcoesDaRotaInterna {
  readonly lista: Pick<ListaDeEspera, "reserve" | "release" | "posicao" | "validarConvite" | "recusar" | "desistir">;
  readonly gates: GatesDoOnboarding;
  readonly revisao: FilaDeRevisao;
  /**
   * A credencial, já lida do cofre. **Um valor e não um anel**, pela razão que a
   * API interna do COM escreve para a `com_internal_token`.
   */
  readonly credencial: string;
  readonly log?: Pick<Logger, "warn">;
}

/** A credencial apresentada é a nossa? Em tempo constante; o comprimento sai cedo, e só ele. */
function credencialValida(apresentada: string | undefined, nossa: string): boolean {
  if (typeof apresentada !== "string" || apresentada.length === 0 || nossa.length === 0) return false;
  const a = Buffer.from(apresentada, "utf8");
  const b = Buffer.from(nossa, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

type Corpo = Record<string, unknown>;

async function corpoDe(pedido: Request): Promise<Corpo | null> {
  try {
    const bruto: unknown = await pedido.json();
    return typeof bruto === "object" && bruto !== null && !Array.isArray(bruto) ? (bruto as Corpo) : null;
  } catch {
    return null;
  }
}

/** O `onboarding_id` do corpo, minúsculo, ou `null`. */
function casoDe(corpo: Corpo | null): string | null {
  const id = corpo?.["onboarding_id"];
  return typeof id === "string" && UUID.test(id.toLowerCase()) ? id.toLowerCase() : null;
}

/** A posição em JSON: datas em ISO, e o «sem estimativa» (infinito) a `null`. A forma do `guia.ts`. */
export function posicaoEmJson(p: Posicao | null): unknown {
  if (p === null) return null;
  if (p.estado === "aguardando") {
    const finito = (n: number): number | null => (Number.isFinite(n) ? n : null);
    return {
      estado: p.estado,
      posicao: p.posicao,
      estimativa: {
        rotulo: p.estimativa.rotulo,
        minimo_dias: finito(p.estimativa.minimoDias),
        maximo_dias: finito(p.estimativa.maximoDias),
      },
    };
  }
  if (p.estado === "convidado") return { estado: p.estado, expira_em: p.expiraEm.toISOString() };
  return { estado: p.estado };
}

/**
 * A app da rota interna. **Uma rota por operação, escritas à mão**, e nenhuma
 * função declarada entre elas: a enumeração do X-01 dá a cada rota, como actor,
 * a última função declarada antes dela.
 */
export function criarAppInterna(o: OpcoesDaRotaInterna): Hono {
  const app = new Hono();
  const { lista, gates, revisao, log } = o;

  app.onError((erro, c) => {
    // A recusa da lista é resposta, não erro: o `onboarding-web` traduz o
    // motivo como traduzia com a lista no seu processo.
    if (erro instanceof ListaRecusadaError) return c.json({ recusa: erro.motivo }, 409);
    // Só o nome do erro: a mensagem pode levar o que a base disse.
    log?.warn({ outcome: "guia_interno_falhou", error_code: erro.name });
    return c.json({ erro: "interno" }, 500);
  });

  // A credencial **antes** de tudo, incluindo o 404: sem ela, nenhum caminho
  // diz se existe.
  app.use("*", async (c, seguinte) => {
    if (!credencialValida(c.req.header(CABECALHO_DO_LOTE), o.credencial)) {
      log?.warn({ outcome: "guia_interno_recusado" });
      return c.json({ erro: "credencial" }, 401);
    }
    await seguinte();
  });

  app.post("/interno/guia/reservar", async (c) => {
    const id = casoDe(await corpoDe(c.req.raw));
    if (id === null) return c.json({ erro: "pedido" }, 400);
    return c.json({ resultado: await lista.reserve(id) }, 200);
  });

  app.post("/interno/guia/libertar", async (c) => {
    const id = casoDe(await corpoDe(c.req.raw));
    if (id === null) return c.json({ erro: "pedido" }, 400);
    await lista.release(id);
    return c.json({ libertado: true }, 200);
  });

  app.post("/interno/guia/posicao", async (c) => {
    const id = casoDe(await corpoDe(c.req.raw));
    if (id === null) return c.json({ erro: "pedido" }, 400);
    return c.json({ posicao: posicaoEmJson(await lista.posicao(id)) }, 200);
  });

  app.post("/interno/guia/convite", async (c) => {
    const corpo = await corpoDe(c.req.raw);
    const id = casoDe(corpo);
    if (id === null) return c.json({ erro: "pedido" }, 400);
    const { expiraEm } = await lista.validarConvite(id, corpo?.["convite"]);
    return c.json({ expira_em: expiraEm.toISOString() }, 200);
  });

  app.post("/interno/guia/recusar", async (c) => {
    const corpo = await corpoDe(c.req.raw);
    const id = casoDe(corpo);
    if (id === null) return c.json({ erro: "pedido" }, 400);
    await lista.recusar(id, corpo?.["convite"]);
    return c.json({ recusado: true }, 200);
  });

  app.post("/interno/guia/desistir", async (c) => {
    const id = casoDe(await corpoDe(c.req.raw));
    if (id === null) return c.json({ erro: "pedido" }, 400);
    await lista.desistir(id);
    return c.json({ desistiu: true }, 200);
  });

  app.post("/interno/guia/gate", async (c) => {
    const corpo = await corpoDe(c.req.raw);
    const id = casoDe(corpo);
    const gate = corpo?.["gate"];
    const verde = corpo?.["verde"];
    const motivo = corpo?.["motivo"];
    if (
      id === null ||
      typeof gate !== "string" ||
      !(GATES_DO_GUIA as readonly string[]).includes(gate) ||
      typeof verde !== "boolean" ||
      typeof motivo !== "string" ||
      !MOTIVO_DO_GATE.test(motivo)
    ) {
      return c.json({ erro: "pedido" }, 400);
    }
    await gates.marcar(id, gate as (typeof GATES_DO_GUIA)[number], verde, motivo);
    return c.json({ marcado: true }, 200);
  });

  app.post("/interno/guia/revisao", async (c) => {
    const corpo = await corpoDe(c.req.raw);
    const id = casoDe(corpo);
    const motivo = corpo?.["motivo"];
    if (id === null || typeof motivo !== "string" || !(MOTIVOS_DE_FALHA as readonly string[]).includes(motivo)) {
      return c.json({ erro: "pedido" }, 400);
    }
    await revisao.abrir(id, "es_falhado", motivo as MotivoDeFalha);
    return c.json({ aberto: true }, 200);
  });

  return app;
}

/** Os passos de uma volta do guia, pelo nome com que a falha se regista. */
export type PassoDaVoltaDoGuia = "abandono" | "lista" | "reconciliacao";

/** O que uma volta do guia fez. */
export interface ResultadoDoCicloDoGuia {
  /** Os popups abertos há mais de 30 minutos, passados a `abandonado`. */
  readonly abandonados: number;
  /** Os `meta_es` que a reconciliação mudou (KAM-254). */
  readonly gatesReconciliados: number;
  /** Os `es_falhado` que a reconciliação abriu (KAM-254). */
  readonly revisoesAbertas: number;
  /** O passo que falhou, se algum: os outros correm na mesma. */
  readonly falhou: readonly PassoDaVoltaDoGuia[];
}

/** A lista na volta: as três operações que o temporizador do `server.ts` corria. */
export type ListaDaVolta = Pick<ListaDeEspera, "expirarVencidos" | "promover" | "medir">;

/**
 * **A volta do guia**, que saiu do `onboarding-web` para aqui (decisão de
 * 2026-11-22): o abandono dos popups vencidos (o `iniciadosAntesDe`, como
 * `kamba_batch`, sobre todos os tenants) e a volta da lista de espera (os
 * convites vencidos, a promoção e a medição). Uma por processo de lote, e não
 * uma por réplica do `onboarding-web`.
 *
 * ## A reconciliação (KAM-254, critério 1)
 *
 * O `PassoGuiado` grava a transição na base e só depois pede ao lote, por esta
 * rota, o `meta_es` e a abertura do `es_falhado`. Os dois pedidos não são
 * atómicos com a transição: com o lote em baixo nesse instante, a transição fica
 * e o efeito perde-se, e os sinais da Meta não se repetem. Por isso cada volta
 * **reconcilia a partir do estado do guia**, que é a fonte: põe o `meta_es` igual
 * ao que o estado manda, e abre o `es_falhado` a um guia preso que não o tenha.
 * Um efeito que falhou chega à base na volta seguinte em que o lote esteja de pé.
 * O `meta_pagamento` fica fora: escreve-se **antes** de qualquer transição, e o
 * dono que vê o erro repete o pedido.
 */
export class CicloDoGuia {
  readonly #lote: ClienteSql;
  readonly #lista: ListaDaVolta;
  readonly #revisao: FilaDeRevisao;
  readonly #agora: () => Date;
  readonly #prazoMin: number;

  constructor(o: {
    readonly lote: ClienteSql;
    readonly lista: ListaDaVolta;
    /** A fila de revisão do lote: a mesma porta que a rota interna serve. */
    readonly revisao: FilaDeRevisao;
    readonly relogio?: () => Date;
    /** O prazo do popup, em minutos. Por omissão, o `PRAZO_DE_ABANDONO_MIN` do KAM-016. */
    readonly prazoMin?: number;
  }) {
    this.#lote = o.lote;
    this.#lista = o.lista;
    this.#revisao = o.revisao;
    this.#agora = o.relogio ?? ((): Date => new Date());
    this.#prazoMin = o.prazoMin ?? PRAZO_DE_ABANDONO_MIN;
  }

  async correr(): Promise<ResultadoDoCicloDoGuia> {
    const falhou: PassoDaVoltaDoGuia[] = [];
    let abandonados = 0;
    let gatesReconciliados = 0;
    let revisoesAbertas = 0;
    try {
      const antes = new Date(this.#agora().getTime() - this.#prazoMin * 60_000);
      abandonados = (await abandonarVencidosNaBase(this.#lote, antes)).length;
    } catch {
      falhou.push("abandono");
    }
    try {
      await this.#lista.expirarVencidos();
      await this.#lista.promover();
      await this.#lista.medir();
    } catch {
      falhou.push("lista");
    }
    // Depois do abandono: um guia que acabou de passar a `abandonado` não escreve
    // o `meta_es`, e a reconciliação não lhe toca.
    // Dois passos, cada um no seu `try`: uma falha do gate não salta a fila.
    let reconciliacaoFalhou = false;
    try {
      gatesReconciliados = (await reconciliarMetaEsNaBase(this.#lote)).length;
    } catch {
      reconciliacaoFalhou = true;
    }
    try {
      const r = await abrirRevisoesEmFaltaNaBase(this.#lote, this.#revisao);
      revisoesAbertas = r.abertos.length;
      if (r.falhados > 0) reconciliacaoFalhou = true;
    } catch {
      reconciliacaoFalhou = true;
    }
    if (reconciliacaoFalhou) falhou.push("reconciliacao");
    return { abandonados, gatesReconciliados, revisoesAbertas, falhou };
  }

  /** Agenda a volta; devolve como a parar. Uma volta não começa sem a anterior acabar. */
  agendar(intervaloMs: number, depois: (r: ResultadoDoCicloDoGuia) => void): () => void {
    let emCurso = false;
    const temporizador = setInterval(() => {
      if (emCurso) return;
      emCurso = true;
      void this.correr()
        .then(depois)
        .finally(() => {
          emCurso = false;
        });
    }, intervaloMs);
    temporizador.unref();
    return () => clearInterval(temporizador);
  }
}

/** O servidor da rota interna, como o `serve` o devolve. */
export type ServidorDaRotaInterna = ReturnType<typeof serve>;

/**
 * **Abre a porta da rota interna**, e só devolve com ela aberta: uma porta ocupada
 * ou um anfitrião que não resolve rejeitam, em vez de chegarem depois como um
 * `error` sem ouvinte. O anfitrião é o `LOTE_INTERNO_HOST`, e é ele que faz a rota
 * não escutar fora da rede `app`: no compose de `prod` é um nome que só essa rede
 * resolve, e o `listen` liga-se ao endereço dele nessa rede e a mais nenhum. A
 * mesma função serve o `../lote.ts` e o ensaio de rede do gate 8
 * (`db/tests_lote/test_rota_interna_rede.py`), para que meçam o mesmo `listen`.
 */
export function servirRotaInterna(
  app: Hono,
  o: { readonly anfitriao: string; readonly porta: number },
): Promise<ServidorDaRotaInterna> {
  return new Promise<ServidorDaRotaInterna>((aberto, falhou) => {
    const s = serve({ fetch: app.fetch, hostname: o.anfitriao, port: o.porta }, () => aberto(s));
    s.once("error", falhou);
  });
}

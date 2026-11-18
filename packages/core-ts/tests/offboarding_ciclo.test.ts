/**
 * O off-boarding em produção, sem base (KAM-210): as métricas, o ciclo e o
 * adaptador da Meta.
 *
 * O ciclo corre aqui sobre um conjunto falso que responde pelo **texto** de cada
 * instrução (a lição do KAM-070); o que só a base prova — que fases a listagem
 * escolhe, a revogação a partir do D7, e as duas voltas sem efeitos repetidos —
 * está em `tests_bd/offboarding.bd.test.ts`.
 *
 * O adaptador da Meta corre sobre a `GraphHttp` do KAM-016 com um `fetch` falso
 * que **lê o método e o caminho** do pedido, e não o argumento: um adaptador que
 * apagasse o WABA chegava aqui como `DELETE /<versao>/<waba>`, e o ensaio
 * recusa-o pelo caminho.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CAMPOS_DE_WEBHOOK } from "../src/onboarding/contrato.ts";
import type { ConjuntoSql } from "../src/revisao/sql.ts";
import { GraphHttp, GraphRecusouError, type Buscar } from "../src/onboarding/graph.ts";
import { executarNoCanalDoCliente, accoesDoCanalDoCliente } from "../src/provisioning/compensacao.ts";
import {
  CANAL_SEM_ADAPTADOR,
  CanalDaMetaPelaGraph,
  CicloDoOffboarding,
  FASES,
  ESTADOS_DA_FASE,
  FOLGA_DA_FASE_HORAS,
  MetricasDoOffboarding,
  OperacaoForaDoOffboardingError,
  PortaSemAdaptadorError,
  REVOGACAO_SEM_ADAPTADOR,
  SQL_CONTAGEM_DAS_FASES,
  SQL_FASES_POR_CORRER,
  DIAS_DE_CANCELAMENTO,
} from "../src/offboarding/index.ts";

const T = "11111111-1111-4111-8111-111111111111";
const AGORA = new Date("2026-11-18T10:00:00Z");

// ------------------------------------------------------------- métricas

function serie(texto: string, nome: string, etiquetas: string): number | undefined {
  const linha = texto.split("\n").find((l) => l.startsWith(`${nome}{${etiquetas}} `));
  return linha === undefined ? undefined : Number(linha.split(" ").at(-1));
}

describe("as métricas do off-boarding", () => {
  it("nascem a zero em todo o domínio, e nenhuma etiqueta leva tenant", () => {
    const texto = new MetricasDoOffboarding().exposicao();
    for (const f of FASES) {
      assert.equal(serie(texto, "offboarding_fases_paradas", `fase="${f}"`), 0, f);
      for (const e of ESTADOS_DA_FASE) assert.equal(serie(texto, "offboarding_fases", `fase="${f}",estado="${e}"`), 0);
    }
    for (const f of ["canal", "pendentes", "revogacao"]) {
      for (const d of ["concluida", "em_curso", "falhou"]) {
        assert.equal(serie(texto, "offboarding_execucoes_total", `fase="${f}",desfecho="${d}"`), 0);
      }
    }
    assert.doesNotMatch(texto, /tenant/);
  });

  it("a contagem substitui, e não soma: uma fase que deixou de estar parada volta a zero", () => {
    const m = new MetricasDoOffboarding();
    m.fixar([
      { fase: "purga", estado: "falhada", n: 2, paradas: 2 },
      { fase: "canal", estado: "em_curso", n: 3, paradas: 1 },
      { fase: "canal", estado: "concluida", n: 5, paradas: 0 },
    ]);
    let t = m.exposicao();
    assert.equal(serie(t, "offboarding_fases_paradas", 'fase="purga"'), 2);
    assert.equal(serie(t, "offboarding_fases_paradas", 'fase="canal"'), 1);
    assert.equal(serie(t, "offboarding_fases", 'fase="canal",estado="concluida"'), 5);
    m.fixar([{ fase: "purga", estado: "concluida", n: 2, paradas: 0 }]);
    t = m.exposicao();
    assert.equal(serie(t, "offboarding_fases_paradas", 'fase="purga"'), 0);
    assert.equal(serie(t, "offboarding_fases", 'fase="canal",estado="em_curso"'), 0);
  });

  it("um valor fora do domínio não abre série", () => {
    const m = new MetricasDoOffboarding();
    m.fixar([{ fase: "outra" as never, estado: "concluida", n: 9, paradas: 9 }]);
    m.execucao("purga" as never, "falhou");
    assert.doesNotMatch(m.exposicao(), /outra|fase="purga",desfecho/);
  });
});

// ---------------------------------------------------------------- ciclo

type Linha = Record<string, unknown>;

/**
 * Um conjunto `kamba_batch` falso. Responde pelo texto: a listagem e a contagem
 * devolvem o que o ensaio lhe deu; as transacções abrem e fecham; qualquer outra
 * instrução levanta — é o que faz uma fase falhar aqui, como faria uma base em
 * baixo. Cada ligação devolvida com erro fica contada.
 */
function conjuntoFalso(o: { porCorrer?: Linha[]; contagem?: Linha[]; listagemFalha?: boolean; fasesFalham?: boolean }) {
  const instrucoes: { sql: string; parametros: readonly unknown[] }[] = [];
  const devolvidas: (Error | boolean | undefined)[] = [];
  const query = async (sql: string, parametros: readonly unknown[] = []) => {
    instrucoes.push({ sql, parametros });
    if (sql === SQL_FASES_POR_CORRER) {
      if (o.listagemFalha) throw new Error("base em baixo");
      return { rows: o.porCorrer ?? [] };
    }
    if (sql === SQL_CONTAGEM_DAS_FASES) return { rows: o.contagem ?? [] };
    if (/^\s*(BEGIN|COMMIT|ROLLBACK)/.test(sql)) return { rows: [] };
    throw new Error("instrucao nao esperada pelo ensaio");
  };
  return {
    instrucoes,
    devolvidas,
    // O tipo do `ConjuntoSql` é genérico nas linhas; o falso devolve linhas soltas.
    conjunto: {
      query,
      connect: async () => ({ query, release: (e?: Error | boolean) => void devolvidas.push(e) }),
    } as unknown as ConjuntoSql,
  };
}

describe("o ciclo do off-boarding", () => {
  it("lista com o instante, os dias do cancelamento e o limite; e conta as sete fases com a folga", async () => {
    const f = conjuntoFalso({});
    const m = new MetricasDoOffboarding();
    await new CicloDoOffboarding({
      lote: f.conjunto,
      portas: { canal: CANAL_SEM_ADAPTADOR, revogacao: REVOGACAO_SEM_ADAPTADOR },
      metricas: m,
      relogio: () => AGORA,
      limite: 7,
    }).correr();
    const lista = f.instrucoes.find((i) => i.sql === SQL_FASES_POR_CORRER);
    assert.deepEqual(lista?.parametros, [AGORA, DIAS_DE_CANCELAMENTO, 7]);
    const conta = f.instrucoes.find((i) => i.sql === SQL_CONTAGEM_DAS_FASES);
    assert.deepEqual(conta?.parametros, [AGORA, FOLGA_DA_FASE_HORAS]);
  });

  it("a listagem só traz fases deste lado de um pedido vivo, e a revogação só no D7 com a exportação e o canal concluídos", () => {
    // O texto é a barreira: estas são as condições que a base aplica.
    assert.match(SQL_FASES_POR_CORRER, /v\.estado = 'concluida'/);
    assert.match(SQL_FASES_POR_CORRER, /NOT \(v\.resultado \? 'cancelado_at'\)/);
    assert.match(SQL_FASES_POR_CORRER, /o\.fase IN \('canal', 'pendentes', 'revogacao'\)/);
    assert.match(SQL_FASES_POR_CORRER, /o\.estado IN \('pendente', 'em_curso'\)/);
    assert.match(SQL_FASES_POR_CORRER, /make_interval\(days => \$2\) <= \$1/);
    assert.match(SQL_FASES_POR_CORRER, /x\.fase = 'exportacao' AND x\.estado = 'concluida'/);
    assert.match(SQL_FASES_POR_CORRER, /c\.fase = 'canal' AND c\.estado = 'concluida'/);
    // E a suspensão por disputa não é paragem: espera uma decisão.
    assert.match(SQL_CONTAGEM_DAS_FASES, /estado = 'falhada'/);
    assert.match(SQL_CONTAGEM_DAS_FASES, /estado IN \('pendente', 'em_curso'\) AND prazo_at \+ make_interval\(hours => \$2\) < \$1/);
    assert.doesNotMatch(SQL_CONTAGEM_DAS_FASES, /suspensa_disputa/);
  });

  it("uma fase que falha fica escrita pelo nome, não pára as outras, e a ligação volta com o erro", async () => {
    const f = conjuntoFalso({
      porCorrer: [
        { tenant_id: T, fase: "canal" },
        { tenant_id: T, fase: "pendentes" },
        { tenant_id: T, fase: "outra" },
      ],
      contagem: [{ fase: "canal", estado: "pendente", n: 1, paradas: 1 }],
    });
    const m = new MetricasDoOffboarding();
    const r = await new CicloDoOffboarding({
      lote: f.conjunto,
      portas: { canal: CANAL_SEM_ADAPTADOR, revogacao: REVOGACAO_SEM_ADAPTADOR },
      metricas: m,
      relogio: () => AGORA,
    }).correr();
    assert.deepEqual([...r.falhas].sort(), ["canal", "pendentes"]);
    assert.deepEqual(r.feitas, {});
    const t = m.exposicao();
    assert.equal(serie(t, "offboarding_execucoes_total", 'fase="canal",desfecho="falhou"'), 1);
    assert.equal(serie(t, "offboarding_execucoes_total", 'fase="pendentes",desfecho="falhou"'), 1);
    // A contagem corre depois das falhas, e o gauge da fase parada sobe.
    assert.equal(serie(t, "offboarding_fases_paradas", 'fase="canal"'), 1);
    // Duas ligações das fases voltaram com o erro (o `pg` descarta-as); a da contagem, limpa.
    assert.equal(f.devolvidas.filter((e) => e instanceof Error).length, 2);
    assert.equal(f.devolvidas.at(-1), undefined);
    // Nenhum tenant no resultado.
    assert.doesNotMatch(JSON.stringify(r), new RegExp(T));
  });

  it("a listagem que falha diz-se, e a contagem corre na mesma", async () => {
    const f = conjuntoFalso({ listagemFalha: true, contagem: [{ fase: "purga", estado: "falhada", n: 1, paradas: 1 }] });
    const m = new MetricasDoOffboarding();
    const r = await new CicloDoOffboarding({
      lote: f.conjunto,
      portas: { canal: CANAL_SEM_ADAPTADOR, revogacao: REVOGACAO_SEM_ADAPTADOR },
      metricas: m,
    }).correr();
    assert.deepEqual(r.falhas, ["listagem"]);
    assert.equal(serie(m.exposicao(), "offboarding_fases_paradas", 'fase="purga"'), 1);
  });

  it("duas voltas pedidas ao mesmo tempo são uma", async () => {
    const f = conjuntoFalso({});
    const c = new CicloDoOffboarding({
      lote: f.conjunto,
      portas: { canal: CANAL_SEM_ADAPTADOR, revogacao: REVOGACAO_SEM_ADAPTADOR },
      metricas: new MetricasDoOffboarding(),
    });
    await Promise.all([c.correr(), c.correr()]);
    assert.equal(f.instrucoes.filter((i) => i.sql === SQL_FASES_POR_CORRER).length, 1);
  });

  it("um intervalo abaixo de um segundo é recusado", () => {
    const c = new CicloDoOffboarding({
      lote: conjuntoFalso({}).conjunto,
      portas: { canal: CANAL_SEM_ADAPTADOR, revogacao: REVOGACAO_SEM_ADAPTADOR },
      metricas: new MetricasDoOffboarding(),
    });
    assert.throws(() => c.agendar(999, () => {}), RangeError);
  });

  it("as portas sem adaptador levantam pelo nome da porta, e nunca dão sucesso", async () => {
    await assert.rejects(CANAL_SEM_ADAPTADOR.cancelarSubscricao("w"), PortaSemAdaptadorError);
    await assert.rejects(REVOGACAO_SEM_ADAPTADOR.chaveDeLlm.revogar("k"), /litellm/);
    await assert.rejects(REVOGACAO_SEM_ADAPTADOR.canalDeComercio.arquivar("c"), /medusa/);
    await assert.rejects(REVOGACAO_SEM_ADAPTADOR.inbox.desligar("i"), /chatwoot/);
  });
});

// ------------------------------------------------------------ a Meta

/**
 * A Graph falsa: guarda cada pedido (método e caminho) e responde pelo caminho.
 * Um `DELETE` ao `subscribed_apps` de um WABA desconhecido dá 404, como um
 * recurso que já não está lá; qualquer outro caminho dá 400.
 */
function graphFalsa(o: { conhecidos?: string[]; estadoDoDelete?: number } = {}) {
  const pedidos: { method: string; caminho: string; auth: string | undefined; corpo?: string }[] = [];
  const buscar: Buscar = async (url, opcoes) => {
    const caminho = new URL(url).pathname;
    pedidos.push({ method: opcoes.method, caminho, auth: opcoes.headers["authorization"], ...(opcoes.body === undefined ? {} : { corpo: opcoes.body }) });
    const m = /^\/v21\.0\/([^/]+)\/subscribed_apps$/.exec(caminho);
    if (m === null) return { status: 400, json: async () => ({ error: { code: 100 } }) };
    const waba = decodeURIComponent(m[1] ?? "");
    if (opcoes.method === "DELETE" && !(o.conhecidos ?? []).includes(waba)) {
      return { status: o.estadoDoDelete ?? 404, json: async () => ({ error: { code: 100 } }) };
    }
    return { status: 200, json: async () => ({ success: true }) };
  };
  const graph = new GraphHttp({ base: "https://graph.invalid", versao: "v21.0", appId: "a", appSecret: "s", buscar });
  return { graph, pedidos };
}

const token = async (waba: string) => `tok-${waba}`;

describe("o adaptador da Meta (CanalDaMetaPelaGraph)", () => {
  it("cancelar a subscrição é um DELETE ao subscribed_apps do WABA, com o token desse WABA", async () => {
    const g = graphFalsa({ conhecidos: ["w1"] });
    await new CanalDaMetaPelaGraph(g.graph, token).cancelarSubscricao("w1");
    assert.deepEqual(
      g.pedidos.map((p) => [p.method, p.caminho, p.auth]),
      [["DELETE", "/v21.0/w1/subscribed_apps", "Bearer tok-w1"]],
    );
  });

  it("é idempotente do lado de fora: um WABA que já não tem a subscrição (404) é sucesso", async () => {
    const g = graphFalsa({ conhecidos: [] });
    const canal = new CanalDaMetaPelaGraph(g.graph, token);
    await canal.cancelarSubscricao("w1");
    await canal.cancelarSubscricao("w1");
    assert.equal(g.pedidos.length, 2);
  });

  it("outro erro da Graph sobe, e a fase fica por concluir", async () => {
    const g = graphFalsa({ conhecidos: [], estadoDoDelete: 500 });
    await assert.rejects(new CanalDaMetaPelaGraph(g.graph, token).cancelarSubscricao("w1"), GraphRecusouError);
  });

  it("refazer a subscrição é um POST com os campos do KAM-016", async () => {
    const g = graphFalsa();
    await new CanalDaMetaPelaGraph(g.graph, token).subscreverWebhooks("w2");
    assert.equal(g.pedidos[0]?.method, "POST");
    assert.equal(g.pedidos[0]?.caminho, "/v21.0/w2/subscribed_apps");
    assert.deepEqual(JSON.parse(g.pedidos[0]?.corpo ?? "{}"), { subscribed_fields: CAMPOS_DE_WEBHOOK.join(",") });
  });

  it("não tem caminho para apagar o WABA nem o número: levanta, e nada sai para a rede", async () => {
    const g = graphFalsa({ conhecidos: ["w1"] });
    let pedidosDoToken = 0;
    const canal = new CanalDaMetaPelaGraph(g.graph, async (w) => {
      pedidosDoToken += 1;
      return token(w);
    });
    await assert.rejects(canal.apagarWaba("w1"), OperacaoForaDoOffboardingError);
    await assert.rejects(canal.apagarNumero("p1"), OperacaoForaDoOffboardingError);
    await assert.rejects(canal.removerRota("p1"), OperacaoForaDoOffboardingError);
    await assert.rejects(canal.numeroDoTenant(T), OperacaoForaDoOffboardingError);
    assert.equal(g.pedidos.length, 0);
    assert.equal(pedidosDoToken, 0);
  });

  it("pelo guarda da saga, a única acção que chega à Meta é o DELETE da subscrição", async () => {
    const g = graphFalsa({ conhecidos: ["w1"] });
    const canal = new CanalDaMetaPelaGraph(g.graph, token);
    for (const accao of accoesDoCanalDoCliente("w1")) await executarNoCanalDoCliente(canal, accao, "espera_es");
    await assert.rejects(
      executarNoCanalDoCliente(canal, { tipo: "apagar", recurso: "waba", ref: "w1" } as never, "espera_es"),
    );
    assert.deepEqual(
      g.pedidos.map((p) => `${p.method} ${p.caminho}`),
      ["DELETE /v21.0/w1/subscribed_apps"],
    );
    // E nenhum pedido a um caminho que não seja o da subscrição.
    assert.ok(g.pedidos.every((p) => p.caminho.endsWith("/subscribed_apps")));
  });
});

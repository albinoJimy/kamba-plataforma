/**
 * Confiança gradual: tectos de valor por histórico (KAM-096).
 *
 * Os *Testes Requeridos* do bloco, pela ordem em que ele os escreve:
 *
 *     unit          elegibilidade (valor mínimo, janela, compradores
 *                   distintos), `min(...)` do tecto efectivo, unidades menores
 *     integração    o ciclo 0 → 1 → descida por disputa, sobre um repositório
 *                   em memória; a recusa no `ManualProvider`
 *     isolamento    o nível e a elegibilidade de A nunca afectam B
 *     adversarial   (a) auto-compra; (b) comprador único; (c) rajada no mesmo
 *                   dia; (d) disputa na janela; (e) sinal de independência
 *                   ausente; (g) 50 000,01 Kz no nível 0
 *
 * O (f) — o tenant a mudar o próprio tecto — mede-se na base, em
 * `db/tests/test_confianca_schema.py`: não há rota que escreva o tecto, e o
 * `kamba_app` não tem `INSERT` nem `UPDATE` em `trust_level` (42501). A barreira
 * da cobrança e a concorrência no limite do tecto também se medem lá, contra o
 * PostgreSQL.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CONFIGURACAO_DA_CONFIANCA,
  type ConfiguracaoDaConfianca,
  ConfiguracaoInvalidaError,
  type Decisao,
  ForaDoTectoDeConfiancaError,
  GuardaDeConfianca,
  LeitorDoTectoSql,
  MENSAGEM_ACIMA_DO_TECTO,
  type NivelGravado,
  type PedidoCandidato,
  type PedidoLido,
  type RepositorioDeConfianca,
  RepositorioDeConfiancaSql,
  SQL_DEFINIR_NIVEL,
  SQL_NIVEL_DO_TENANT,
  SQL_PEDIDOS_ENTREGUES,
  SQL_TECTO_DO_TENANT,
  SQL_TRANCAR,
  ServicoDeConfianca,
  avaliarPedido,
  contar,
  cumpreSubida,
  decidirNivel,
  diaEmLuanda,
  tabelaDeLimites,
  tectoEfectivoManual,
  validarConfiguracao,
} from "../src/confianca/index.ts";
import { minorDeInteiroKz } from "../src/pagamentos/dinheiro.ts";
import { ManualProvider } from "../src/pagamentos/manual.ts";
import { ProviderError } from "../src/pagamentos/tipos.ts";
import type { Independencia, RestricoesEmVigor } from "../src/trust/contrato.ts";

const C = CONFIGURACAO_DA_CONFIANCA;
const DIA = 86_400_000;
const AGORA = new Date("2026-11-16T12:00:00.000Z");
const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function diasAntes(dias: number): Date {
  return new Date(AGORA.getTime() - dias * DIA);
}

let sequencia = 0;

/** Um pedido que **conta**: cada caso muda um campo só. */
function pedido(campos: Partial<PedidoCandidato> = {}): PedidoCandidato {
  sequencia += 1;
  return {
    orderId: `pedido-${sequencia}`,
    compradorRef: `comprador-${sequencia}`,
    valorMinor: 1_200_000n,
    criadoEm: diasAntes(20 + sequencia / 100),
    entregueEm: diasAntes(20),
    confirmadoPeloCliente: true,
    disputaNaJanela: false,
    independencia: "independente",
    ...campos,
  };
}

const NIVEL_ZERO: NivelGravado = {
  nivel: 0,
  tectoPedidoMinor: 5_000_000n,
  motivo: "k1_completo",
  desde: diasAntes(60),
};

const SEM_SANCAO: RestricoesEmVigor = { passo: null, semNovosProdutos: false, tectoNoNivelZero: false };
const LIMITACAO: RestricoesEmVigor = { passo: "limitacao", semNovosProdutos: true, tectoNoNivelZero: true };

describe("configuracao: tudo proposta, e versionada", () => {
  it("os tres niveis do criterio 1, em unidade menor (1 Kz = 100)", () => {
    assert.equal(C.niveis[0].tectoPedidoMinor.valor, minorDeInteiroKz("50000"));
    assert.equal(C.niveis[1].tectoPedidoMinor.valor, minorDeInteiroKz("150000"));
    assert.equal(C.niveis[2].tectoPedidoMinor.valor, minorDeInteiroKz("500000"));
    assert.equal(C.patamares.valorMinimoMinor.valor, minorDeInteiroKz("10000"));
    assert.equal(C.niveis[2].atribuivel, false);
  });

  it("a tabela de limites diz a origem e o calibrado_em de cada valor (criterio 8)", () => {
    const linhas = tabelaDeLimites();
    assert.equal(linhas.length, 8);
    for (const l of linhas) {
      assert.equal(l.origem, "proposta", l.chave);
      assert.equal(l.calibradoEm, null, l.chave);
      assert.match(l.valor, /^[0-9]+$/, l.chave);
    }
  });

  it("recusa o nivel 2 atribuivel, tectos que nao crescem e uma versao sem forma", () => {
    const comNivel2: ConfiguracaoDaConfianca = { ...C, niveis: { ...C.niveis, 2: { ...C.niveis[2], atribuivel: true } } };
    assert.throws(() => validarConfiguracao(comNivel2), ConfiguracaoInvalidaError);
    const invertido: ConfiguracaoDaConfianca = {
      ...C,
      niveis: { ...C.niveis, 1: { ...C.niveis[1], tectoPedidoMinor: C.niveis[0].tectoPedidoMinor } },
    };
    assert.throws(() => validarConfiguracao(invertido), ConfiguracaoInvalidaError);
    assert.throws(() => validarConfiguracao({ ...C, versao: "v1" }), ConfiguracaoInvalidaError);
    const calibradoSemData: ConfiguracaoDaConfianca = {
      ...C,
      patamares: { ...C.patamares, pedidosParaSubir: { ...C.patamares.pedidosParaSubir, origem: "calibrado" } },
    };
    assert.throws(() => validarConfiguracao(calibradoSemData), ConfiguracaoInvalidaError);
    assert.equal(validarConfiguracao(C), C);
  });
});

describe("elegibilidade (unit)", () => {
  const marco = diasAntes(60);

  it("o valor minimo e inclusivo: 10 000 Kz conta, um centimo abaixo nao", () => {
    assert.deepEqual(avaliarPedido(pedido({ valorMinor: 1_000_000n }), C, AGORA, marco), { conta: true });
    assert.deepEqual(avaliarPedido(pedido({ valorMinor: 999_999n }), C, AGORA, marco), {
      conta: false,
      motivo: "abaixo_do_valor_minimo",
    });
  });

  it("a janela anti-fraude: aos 14 dias exactos conta, um milissegundo antes nao", () => {
    const exacto = new Date(AGORA.getTime() - 14 * DIA);
    assert.equal(avaliarPedido(pedido({ entregueEm: exacto }), C, AGORA, marco).conta, true);
    const cedo = new Date(exacto.getTime() + 1);
    assert.deepEqual(avaliarPedido(pedido({ entregueEm: cedo }), C, AGORA, marco), {
      conta: false,
      motivo: "janela_anti_fraude_aberta",
    });
  });

  it("a janela movel: um pedido que amadureceu ha 30 dias ja nao conta", () => {
    assert.deepEqual(avaliarPedido(pedido({ entregueEm: diasAntes(44) }), C, AGORA, marco), {
      conta: false,
      motivo: "fora_da_janela_movel",
    });
    assert.equal(avaliarPedido(pedido({ entregueEm: diasAntes(43) }), C, AGORA, marco).conta, true);
  });

  it("sem confirmacao do cliente, anterior ao marco ou com disputa nao conta", () => {
    assert.equal(avaliarPedido(pedido({ confirmadoPeloCliente: false }), C, AGORA, marco).conta, false);
    assert.deepEqual(avaliarPedido(pedido({ entregueEm: diasAntes(20) }), C, AGORA, diasAntes(20)), {
      conta: false,
      motivo: "anterior_ao_marco",
    });
    assert.deepEqual(avaliarPedido(pedido({ disputaNaJanela: true }), C, AGORA, marco), {
      conta: false,
      motivo: "disputa",
    });
  });

  it("subir pede pedidos e compradores distintos: 5 de 3 sobe, 5 de 2 nao", () => {
    const tres = ["x", "y", "z", "x", "y"].map((c, i) => pedido({ compradorRef: c, criadoEm: diasAntes(25 - i) }));
    assert.deepEqual(contar(tres, C, AGORA, marco), { pedidos: 5, compradores: 3 });
    assert.equal(cumpreSubida(contar(tres, C, AGORA, marco), C), true);
    const dois = ["x", "y", "x", "y", "x"].map((c, i) => pedido({ compradorRef: c, criadoEm: diasAntes(25 - i) }));
    assert.equal(cumpreSubida(contar(dois, C, AGORA, marco), C), false);
    assert.equal(cumpreSubida({ pedidos: 4, compradores: 4 }, C), false);
  });

  it("o dia da rajada e o de Luanda (UTC+1, sem hora de Verao)", () => {
    assert.equal(diaEmLuanda(new Date("2026-11-15T22:59:59.999Z")), "2026-11-15");
    assert.equal(diaEmLuanda(new Date("2026-11-15T23:00:00.000Z")), "2026-11-16");
  });
});

describe("tecto efectivo (unit)", () => {
  it("min(tecto_pedido_minor, manual_max_minor), e null em qualquer dos dois recusa", () => {
    assert.equal(tectoEfectivoManual(5_000_000n, 15_000_000n), 5_000_000n);
    assert.equal(tectoEfectivoManual(15_000_000n, 5_000_000n), 5_000_000n);
    assert.equal(tectoEfectivoManual(null, 5_000_000n), null);
    assert.equal(tectoEfectivoManual(5_000_000n, null), null);
  });
});

// ------------------------------------------------------------ em memória

/** O repositório em memória, por tenant: o mesmo contrato do `RepositorioDeConfiancaSql`. */
class Memoria implements RepositorioDeConfianca {
  readonly niveis = new Map<string, NivelGravado>();
  readonly k1 = new Set<string>();
  readonly pedidos = new Map<string, (PedidoLido & { independencia: Independencia })[]>();
  readonly negativos = new Map<string, { ultimaDisputaAceite: Date | null; ultimoSinalAlto: Date | null }>();
  readonly escritas: { tenantId: string; d: Decisao; actor: string }[] = [];
  agora = AGORA;
  readonly trancados: string[] = [];

  async trancar(t: string) {
    this.trancados.push(t);
  }
  async nivel(t: string) {
    return this.niveis.get(t) ?? null;
  }
  async k1Completo(t: string) {
    return this.k1.has(t);
  }
  async pedidosEntregues(t: string, desde: Date, valorMinimo: bigint) {
    return (this.pedidos.get(t) ?? []).filter((p) => p.entregueEm > desde && p.valorMinor >= valorMinimo);
  }
  async factosNegativos(t: string) {
    return this.negativos.get(t) ?? { ultimaDisputaAceite: null, ultimoSinalAlto: null };
  }
  async definir(t: string, d: Decisao, actor: string) {
    const actual = this.niveis.get(t);
    if (actual !== undefined && actual.nivel === d.nivel && actual.tectoPedidoMinor === d.tectoPedidoMinor) {
      return false;
    }
    this.escritas.push({ tenantId: t, d, actor });
    const desde = actual !== undefined && actual.nivel === d.nivel ? actual.desde : this.agora;
    this.niveis.set(t, { nivel: d.nivel, tectoPedidoMinor: d.tectoPedidoMinor, motivo: d.motivo, desde });
    return true;
  }
  /** Um pedido entregue do tenant `t`, com a marca do KAM-097. */
  juntar(t: string, campos: Partial<PedidoCandidato> = {}): void {
    const p = pedido(campos);
    this.pedidos.set(t, [...(this.pedidos.get(t) ?? []), p]);
  }
}

function servico(m: Memoria, restricoes: (t: string) => RestricoesEmVigor = () => SEM_SANCAO) {
  return new ServicoDeConfianca({
    repositorio: m,
    independencia: {
      independencia: async (t, orderId) =>
        (m.pedidos.get(t) ?? []).find((p) => p.orderId === orderId)?.independencia ?? "por_avaliar",
    },
    restricoes: { restricoes: async (t) => restricoes(t) },
    consumidorDeTrust: "trust",
    relogio: () => m.agora,
  });
}

/** Cinco pedidos que contam, de cinco compradores, em dias diferentes. */
function cincoQueContam(m: Memoria, t: string, campos: (i: number) => Partial<PedidoCandidato> = () => ({})): void {
  for (let i = 0; i < 5; i++) {
    m.juntar(t, { compradorRef: `${t}-c${i}`, criadoEm: diasAntes(25 - i), entregueEm: diasAntes(20 - i), ...campos(i) });
  }
}

describe("integracao: o ciclo 0 -> 1 -> descida por disputa", () => {
  it("sem K1 nao ha nivel; com K1 nasce no 0; com historico sobe ao 1; a disputa desce", async () => {
    const m = new Memoria();
    const s = servico(m);
    assert.deepEqual(await s.recalcular(A), { tenantId: A, nivel: null, mudou: false, motivo: null });

    m.k1.add(A);
    assert.equal((await s.recalcular(A)).nivel, 0);
    assert.equal(m.niveis.get(A)?.tectoPedidoMinor, 5_000_000n);
    assert.equal(m.escritas.at(-1)?.actor, `sistema:${C.versao}`);

    // O nível nasceu agora: os pedidos têm de ser entregues depois dele.
    m.agora = new Date(AGORA.getTime() + 40 * DIA);
    for (let i = 0; i < 5; i++) {
      m.juntar(A, {
        compradorRef: `c${i % 3}`,
        criadoEm: new Date(AGORA.getTime() + (1 + i) * DIA),
        entregueEm: new Date(AGORA.getTime() + (2 + i) * DIA),
      });
    }
    const subida = await s.recalcular(A);
    assert.deepEqual(subida, { tenantId: A, nivel: 1, mudou: true, motivo: "historico_independente" });
    assert.equal(m.niveis.get(A)?.tectoPedidoMinor, 15_000_000n);

    m.negativos.set(A, { ultimaDisputaAceite: new Date(m.agora.getTime() + 1), ultimoSinalAlto: null });
    m.agora = new Date(m.agora.getTime() + DIA);
    const descida = await s.recalcular(A);
    assert.deepEqual(descida, { tenantId: A, nivel: 0, mudou: true, motivo: "disputa_aceite" });
    assert.equal(m.niveis.get(A)?.tectoPedidoMinor, 5_000_000n);
  });

  it("uma descida nao se reverte sem nova elegibilidade completa (criterio 5)", async () => {
    const m = new Memoria();
    m.k1.add(A);
    m.niveis.set(A, { ...NIVEL_ZERO, desde: diasAntes(5), motivo: "sinal_alto" });
    // Os cinco pedidos foram entregues ANTES da descida: não contam outra vez.
    cincoQueContam(m, A, (i) => ({ entregueEm: diasAntes(20 - i) }));
    assert.equal((await servico(m).recalcular(A)).mudou, false);
    assert.equal(m.niveis.get(A)?.nivel, 0);
  });

  it("o sinal alto e a sancao descem do 1; a sancao impede a subida", async () => {
    const m = new Memoria();
    m.niveis.set(A, { nivel: 1, tectoPedidoMinor: 15_000_000n, motivo: "historico_independente", desde: diasAntes(10) });
    m.negativos.set(A, { ultimaDisputaAceite: null, ultimoSinalAlto: diasAntes(1) });
    assert.equal((await servico(m).recalcular(A)).motivo, "sinal_alto");

    m.niveis.set(B, { nivel: 1, tectoPedidoMinor: 15_000_000n, motivo: "historico_independente", desde: diasAntes(10) });
    const comSancao = servico(m, (t) => (t === B ? LIMITACAO : SEM_SANCAO));
    assert.equal((await comSancao.recalcular(B)).motivo, "sancao");

    const n = new Memoria();
    n.niveis.set(B, NIVEL_ZERO);
    cincoQueContam(n, B);
    assert.equal((await servico(n, () => LIMITACAO).recalcular(B)).mudou, false);
  });

  it("idempotente: reexecutar o recalculo nao escreve outra vez (DoD 2)", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    cincoQueContam(m, A);
    const s = servico(m);
    assert.equal((await s.recalcular(A)).mudou, true);
    assert.equal((await s.recalcular(A)).mudou, false);
    assert.equal((await s.recalcular(A)).mudou, false);
    assert.equal(m.escritas.length, 1);
    // A tranca do tenant é a primeira coisa de cada recálculo.
    assert.deepEqual(m.trancados, [A, A, A]);
  });

  it("uma recalibracao do tecto muda o tecto e nao o nivel nem o desde", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    const nova: ConfiguracaoDaConfianca = {
      ...C,
      versao: "2026-12-01.1",
      niveis: { ...C.niveis, 0: { ...C.niveis[0], tectoPedidoMinor: { ...C.niveis[0].tectoPedidoMinor, valor: 6_000_000n } } },
    };
    const d = decidirNivel(
      { actual: NIVEL_ZERO, k1Completo: true, pedidos: [], ultimaDisputaAceite: null, ultimoSinalAlto: null, sancaoEmVigor: false },
      nova,
      AGORA,
    );
    assert.deepEqual(d, { nivel: 0, tectoPedidoMinor: 6_000_000n, motivo: "recalibracao" });
  });
});

describe("isolamento: A nunca afecta B", () => {
  it("os pedidos e a subida de A nao sobem B, e a sancao de B nao desce A", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    m.niveis.set(B, { nivel: 1, tectoPedidoMinor: 15_000_000n, motivo: "historico_independente", desde: diasAntes(10) });
    cincoQueContam(m, A);
    const s = servico(m, (t) => (t === B ? LIMITACAO : SEM_SANCAO));
    assert.equal((await s.recalcular(A)).nivel, 1);
    assert.equal((await s.recalcular(B)).nivel, 0);
    assert.equal(m.niveis.get(A)?.nivel, 1);
    assert.deepEqual(
      m.escritas.map((e) => [e.tenantId, e.d.nivel]),
      [[A, 1], [B, 0]],
    );
  });
});

describe("adversarial", () => {
  it("(a) auto-compra: os pedidos que o KAM-097 marca nao independentes nao contam, nivel 0", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    cincoQueContam(m, A, () => ({ independencia: "nao_independente", valorMinor: 1_500_000n }));
    assert.equal((await servico(m).recalcular(A)).nivel, 0);
    assert.equal(m.escritas.length, 0);
  });

  it("(b) cinco pedidos de um so comprador nao sobem", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    cincoQueContam(m, A, () => ({ compradorRef: "sempre-o-mesmo" }));
    assert.equal((await servico(m).recalcular(A)).nivel, 0);
  });

  it("(c) uma rajada no mesmo dia conta no maximo uma por comprador", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    const dia = new Date("2026-10-27T09:00:00.000Z");
    for (const c of ["x", "x", "x", "y", "z"]) {
      m.juntar(A, { compradorRef: c, criadoEm: dia, entregueEm: diasAntes(20) });
    }
    assert.deepEqual(contar(m.pedidos.get(A) ?? [], C, AGORA, NIVEL_ZERO.desde), { pedidos: 3, compradores: 3 });
    assert.equal((await servico(m).recalcular(A)).nivel, 0);
  });

  it("(d) uma disputa na janela tira o pedido da conta", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    cincoQueContam(m, A, (i) => ({ disputaNaJanela: i === 0 }));
    assert.equal((await servico(m).recalcular(A)).nivel, 0);
  });

  it("(e) sem o sinal de independencia (por_avaliar) nao sobe: fecha em falha", async () => {
    const m = new Memoria();
    m.niveis.set(A, NIVEL_ZERO);
    cincoQueContam(m, A, () => ({ independencia: "por_avaliar" }));
    assert.equal((await servico(m).recalcular(A)).nivel, 0);
  });

  it("(g) 50 000,01 Kz no nivel 0 e recusado; 50 000 Kz exactos passam", async () => {
    const guarda = new GuardaDeConfianca({
      tecto: { tectoDoTenant: async () => 5_000_000n },
      restricoes: { restricoes: async () => SEM_SANCAO },
    });
    await guarda.assertWithinTrustCeiling(A, 5_000_000n);
    await assert.rejects(guarda.assertWithinTrustCeiling(A, 5_000_001n), (e: unknown) => {
      assert.ok(e instanceof ForaDoTectoDeConfiancaError);
      assert.equal(e.motivo, "acima_do_tecto");
      return true;
    });
  });
});

describe("guarda no caminho de cobranca", () => {
  it("sem nivel recusa; a sancao baixa ao tecto do nivel 0 antes do recalculo", async () => {
    const semNivel = new GuardaDeConfianca({
      tecto: { tectoDoTenant: async () => null },
      restricoes: { restricoes: async () => SEM_SANCAO },
    });
    await assert.rejects(semNivel.assertWithinTrustCeiling(A, 1n), ForaDoTectoDeConfiancaError);

    const sancionado = new GuardaDeConfianca({
      tecto: { tectoDoTenant: async () => 15_000_000n },
      restricoes: { restricoes: async () => LIMITACAO },
    });
    assert.equal(await sancionado.tectoEfectivo(A), 5_000_000n);
    await assert.rejects(sancionado.assertWithinTrustCeiling(A, 5_000_001n), ForaDoTectoDeConfiancaError);
  });

  it("a mensagem e fixa e nao tem numeros", () => {
    assert.doesNotMatch(MENSAGEM_ACIMA_DO_TECTO, /[0-9]/);
    assert.equal(new ForaDoTectoDeConfiancaError("sem_nivel").message, MENSAGEM_ACIMA_DO_TECTO);
  });

  it("o ManualProvider chama a guarda: efectivo = min(tecto, manual_max_minor)", async () => {
    const chamadas: [string, bigint][] = [];
    const guarda = new GuardaDeConfianca({
      tecto: { tectoDoTenant: async () => 3_000_000n },
      restricoes: { restricoes: async () => SEM_SANCAO },
    });
    const manual = new ManualProvider({
      limites: { limitesDoManual: async () => ({ manualMaxMinor: 5_000_000n, codActivado: false }) },
      instrucoes: { instrucoesDaConta: async () => "Transferencia para a conta da PME." },
      confianca: {
        assertWithinTrustCeiling: async (t, v) => {
          chamadas.push([t, v]);
          await guarda.assertWithinTrustCeiling(t, v);
        },
      },
    });
    const req = {
      chargeId: "66666666-6666-4666-8666-666666666666",
      tenantId: A,
      accountId: "22222222-2222-4222-8222-222222222222",
      numeroPublico: "K7H3Q9",
      currency: "AOA" as const,
      metodo: "manual" as const,
      validUntil: "2026-11-17T12:00:00.000Z",
      customFields: {},
    };
    assert.equal((await manual.createCharge({ ...req, amount: 3_000_000n })).kind, "manual");
    await assert.rejects(manual.createCharge({ ...req, amount: 3_000_001n }), (e: unknown) => {
      assert.ok(e instanceof ProviderError);
      assert.equal(e.codigo, "REJECTED");
      assert.equal(e.message, MENSAGEM_ACIMA_DO_TECTO);
      return true;
    });
    // Acima do `manual_max_minor` a recusa é a do M-2, e a guarda nem é chamada.
    await assert.rejects(manual.createCharge({ ...req, amount: 5_000_001n }), ProviderError);
    assert.deepEqual(chamadas, [
      [A, 3_000_000n],
      [A, 3_000_001n],
    ]);
  });
});

describe("adaptador SQL (sobre um cliente falso; o SQL corre contra a base nas suites de db/)", () => {
  type Chamada = { sql: string; parametros: readonly unknown[] };
  function cliente(respostas: Map<string, Record<string, unknown>[]>) {
    const chamadas: Chamada[] = [];
    return {
      chamadas,
      bd: {
        async query(sql: string, parametros: readonly unknown[] = []) {
          chamadas.push({ sql, parametros });
          const rows = respostas.get(sql) ?? [];
          return { rows, rowCount: rows.length };
        },
      },
    };
  }

  it("le o nivel pelo dominio, e um nivel fora dele falha fechado", async () => {
    const desde = new Date("2026-11-01T00:00:00.000Z");
    const { bd } = cliente(new Map([[SQL_NIVEL_DO_TENANT, [{ nivel: 1, tecto_pedido_minor: "15000000", motivo: "historico_independente", desde }]]]));
    assert.deepEqual(await new RepositorioDeConfiancaSql(bd).nivel(A), {
      nivel: 1,
      tectoPedidoMinor: 15_000_000n,
      motivo: "historico_independente",
      desde,
    });
    const { bd: mau } = cliente(new Map([[SQL_NIVEL_DO_TENANT, [{ nivel: 7, tecto_pedido_minor: "1", motivo: "x", desde }]]]));
    await assert.rejects(new RepositorioDeConfiancaSql(mau).nivel(A), /fora do dominio/);
    assert.equal(await new RepositorioDeConfiancaSql(cliente(new Map()).bd).nivel(A), null);
  });

  it("tranca, le os pedidos e grava com os parametros pela ordem das cadeias", async () => {
    const entregue = new Date("2026-10-20T10:00:00.000Z");
    const c = cliente(
      new Map([
        [SQL_PEDIDOS_ENTREGUES, [{
          order_id: "o1", comprador_ref: "c1", valor_minor: "1200000", criado_at: entregue,
          entregue_at: entregue, confirmado_pelo_cliente: true, disputa_na_janela: false,
        }]],
        [SQL_DEFINIR_NIVEL, [{ nivel: 1 }]],
      ]),
    );
    const r = new RepositorioDeConfiancaSql(c.bd);
    await r.trancar(A);
    const pedidos = await r.pedidosEntregues(A, AGORA, 1_000_000n, 14);
    assert.deepEqual(pedidos, [{
      orderId: "o1", compradorRef: "c1", valorMinor: 1_200_000n, criadoEm: entregue,
      entregueEm: entregue, confirmadoPeloCliente: true, disputaNaJanela: false,
    }]);
    assert.equal(await r.definir(A, { nivel: 1, tectoPedidoMinor: 15_000_000n, motivo: "historico_independente" }, "sistema:x", C.versao), true);
    assert.deepEqual(c.chamadas.map((x) => x.sql), [SQL_TRANCAR, SQL_PEDIDOS_ENTREGUES, SQL_DEFINIR_NIVEL]);
    assert.deepEqual(c.chamadas[1]?.parametros, [A, AGORA, "1000000", 14]);
    assert.deepEqual(c.chamadas[2]?.parametros, [A, 1, "15000000", "historico_independente", "sistema:x", C.versao]);
  });

  it("o leitor do tecto devolve bigint, ou null sem linha", async () => {
    const { bd } = cliente(new Map([[SQL_TECTO_DO_TENANT, [{ tecto_pedido_minor: "5000000" }]]]));
    assert.equal(await new LeitorDoTectoSql(bd).tectoDoTenant(A), 5_000_000n);
    assert.equal(await new LeitorDoTectoSql(cliente(new Map()).bd).tectoDoTenant(A), null);
  });
});

/**
 * Trust & Safety (KAM-097): as regras, a escada, a ligação à fila de revisão e
 * a suite adversarial do bloco.
 *
 * A fila é a **verdadeira** (`ServicoDeRevisao` sobre os duplos do KAM-089),
 * com o gancho de T&S ligado: uma sanção grave só existe depois de um revisor a
 * decidir, e o recurso é o da fila.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import { hmacDePesquisa, normalizarTelefone } from "../src/identity/cripto.ts";
import { RevisaoRecusadaError, type Revisor } from "../src/revisao/index.ts";
import { MODELOS } from "../src/sms/modelos.ts";
import {
  AvisoDeSancaoPorSms,
  EstadoDosTenantsEmMemoria,
  MODELO_DO_MOTIVO,
  MOTIVOS_PUBLICOS_DA_SANCAO,
  POLITICA_DE_RISCO,
  RecusaDaBaseError,
  RepositorioDeTrustEmMemoria,
  SEVERIDADE_DO_TIPO,
  SQL_COMPRADORES_PAGOS,
  SQL_CONTACTOS_DO_DONO,
  SQL_PEDIDO_E_COMPRADOR,
  SQL_PEDIDOS_MANUAIS,
  SQL_QUEIXAS,
  SQL_TENANT_E_TECTO,
  ServicoDeTrust,
  TEXTO_DO_MOTIVO_DA_SANCAO,
  TIPOS_DE_SINAL,
  TrustRecusadoError,
  autoCompra,
  avaliarPreco,
  burlaProvavel,
  confirmacaoSuspeita,
  mediana,
  naoEntregue,
  passoAutomatico,
  queixasQueContam,
  recusaDaSancao,
  risco,
  sinaisDoEvento,
  type FilaDoTrust,
  type MotivoPublicoDaSancao,
  type SinalNovo,
} from "../src/trust/index.ts";

import { SEXTA, montarRevisao, revisor } from "./apoio/revisao.ts";

const DIA = 86_400_000;

// ------------------------------------------------------------------ montagem

function montar(o: { agora?: Date } = {}) {
  let agora = o.agora ?? SEXTA;
  const relogio = () => agora;
  const repositorio = new RepositorioDeTrustEmMemoria(relogio);
  const tenants = new EstadoDosTenantsEmMemoria();
  const avisos: { tenantId: string; motivo: MotivoPublicoDaSancao }[] = [];
  let fila: FilaDoTrust | null = null;
  const trust = new ServicoDeTrust({
    repositorio,
    tenants,
    aviso: { avisar: async (p) => void avisos.push({ ...p }) },
    fila: {
      abrir: (p) => fila!.abrir(p),
      abrirRecurso: (id) => fila!.abrirRecurso(id),
    },
    relogio,
  });
  const r = montarRevisao({ agora, trust });
  fila = r.servico;
  // Um tenant activo, com o seu onboarding (é dele que vem «quem é parte»).
  const o0 = r.onboarding({ fase: "activo" });
  const tenantId = o0.tenantId;
  tenants.estados.set(tenantId, "ativo");
  const sinal = (tipo: SinalNovo["tipo"], ref = randomUUID()) =>
    trust.registar({ tenantId, tipo, refEvento: ref, detalhe: {}, ocorridoEm: agora });
  return {
    ...r,
    trust,
    repositorio,
    tenants,
    avisos,
    tenantId,
    onboardingDoTenant: o0,
    sinal,
    avancarDias: (d: number) => {
      agora = new Date(agora.getTime() + d * DIA);
      r.definir(agora);
    },
  };
}

async function recusaDaFila(p: Promise<unknown>, motivo: string): Promise<void> {
  await assert.rejects(p, (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === motivo);
}

async function recusaDoTrust(p: Promise<unknown>, motivo: string): Promise<void> {
  await assert.rejects(p, (e: unknown) => e instanceof TrustRecusadoError && e.motivo === motivo);
}

const lider = (): Revisor => revisor({ papeis: ["ts_revisor", "ts_lider"] });

// --------------------------------------------------------------------- regras

describe("regras de cada sinal (unidade)", () => {
  it("auto-compra: coincide por contacto, telefone ou BSUID do dono; dois vazios nao coincidem", () => {
    const dono = { contactIds: ["c-dono"], phoneHmacs: ["h-tel"], bsuidHmacs: ["h-bsuid"] };
    assert.equal(autoCompra({ contactId: "c-dono", phoneHmac: null, bsuidHmacs: [] }, dono), "contact_id");
    assert.equal(autoCompra({ contactId: "c-x", phoneHmac: "h-tel", bsuidHmacs: [] }, dono), "phone_hmac");
    assert.equal(autoCompra({ contactId: "c-x", phoneHmac: null, bsuidHmacs: ["h-bsuid"] }, dono), "bsuid_hmac");
    assert.equal(autoCompra({ contactId: "c-x", phoneHmac: "h-outro", bsuidHmacs: [] }, dono), null);
    assert.equal(autoCompra({ contactId: "", phoneHmac: "", bsuidHmacs: [""] }, { contactIds: [""], phoneHmacs: [""], bsuidHmacs: [""] }), null);
  });

  it("burla provavel: tenant novo e tres pedidos manuais perto do tecto; nao com dois, nem velho, nem sem activacao", () => {
    const agora = SEXTA;
    const activo = new Date(agora.getTime() - 5 * DIA);
    const tecto = 5_000_000;
    const p = (n: number, total = 4_500_000) =>
      Array.from({ length: n }, () => ({ orderId: randomUUID(), totalMinor: total, criadoEm: agora }));
    assert.equal(burlaProvavel({ activoDesde: activo, tectoMinor: tecto, pedidos: p(3) }, agora), true);
    assert.equal(burlaProvavel({ activoDesde: activo, tectoMinor: tecto, pedidos: p(2) }, agora), false);
    assert.equal(burlaProvavel({ activoDesde: activo, tectoMinor: tecto, pedidos: p(3, 3_000_000) }, agora), false, "longe do tecto");
    const velho = new Date(agora.getTime() - 15 * DIA);
    assert.equal(burlaProvavel({ activoDesde: velho, tectoMinor: tecto, pedidos: p(3) }, agora), false);
    assert.equal(burlaProvavel({ activoDesde: null, tectoMinor: tecto, pedidos: p(3) }, agora), false);
  });

  it("o limiar da burla e configuravel: mudar o numero de pedidos muda a saida", () => {
    const activo = new Date(SEXTA.getTime() - DIA);
    const pedidos = [1, 2].map(() => ({ orderId: randomUUID(), totalMinor: 4_900_000, criadoEm: SEXTA }));
    assert.equal(burlaProvavel({ activoDesde: activo, tectoMinor: 5_000_000, pedidos }, SEXTA), false);
    assert.equal(
      burlaProvavel({ activoDesde: activo, tectoMinor: 5_000_000, pedidos }, SEXTA, { ...POLITICA_DE_RISCO, pedidosProximosDoTecto: 2 }),
      true,
    );
  });

  it("confirmacao suspeita: menos de 30 s, repetida; uma so nao; 30 s exactos nao", () => {
    const c = (s: number) => ({ orderId: randomUUID(), criadoEm: SEXTA, confirmadoEm: new Date(SEXTA.getTime() + s * 1000) });
    assert.equal(confirmacaoSuspeita([c(5), c(10)]), true);
    assert.equal(confirmacaoSuspeita([c(5)]), false);
    assert.equal(confirmacaoSuspeita([c(30), c(30)]), false);
  });

  it("preco: so com 20 referencias, e fora de [1%, 100x] da mediana", () => {
    const refs = Array.from({ length: 20 }, () => 100_000);
    assert.equal(avaliarPreco(10, refs.slice(0, 19)), "sem_referencia");
    assert.equal(avaliarPreco(100_000, refs), "normal");
    assert.equal(avaliarPreco(999, refs), "anomalo");
    assert.equal(avaliarPreco(1_000, refs), "normal");
    assert.equal(avaliarPreco(10_000_001, refs), "anomalo");
    assert.equal(mediana([3, 1, 2, 10]), 2.5);
  });

  it("anti-retaliacao: so contam queixas de quem pagou, uma por contacto, dentro de 30 dias", () => {
    const em = (d: number) => new Date(SEXTA.getTime() - d * DIA);
    const pagos = new Set(["a", "b"]);
    const q = [
      { contactId: "a", em: em(1) },
      { contactId: "a", em: em(2) },
      { contactId: "x", em: em(1) },
      { contactId: null, em: em(1) },
      { contactId: "b", em: em(31) },
    ];
    assert.equal(queixasQueContam(q, pagos, SEXTA), 1);
    assert.equal(queixasQueContam([...q, { contactId: "b", em: em(3) }], pagos, SEXTA), 2);
  });

  it("nao entrega: paga e nao entregue ha mais de 7 dias", () => {
    assert.equal(naoEntregue(new Date(SEXTA.getTime() - 8 * DIA), null, SEXTA), true);
    assert.equal(naoEntregue(new Date(SEXTA.getTime() - 6 * DIA), null, SEXTA), false);
    assert.equal(naoEntregue(new Date(SEXTA.getTime() - 8 * DIA), SEXTA, SEXTA), false);
  });

  it("risco: soma dos pesos com decaimento de meia-vida 30 dias, tecto 100", () => {
    const s = (tipo: (typeof TIPOS_DE_SINAL)[number], dias: number) => ({ tipo, ocorridoEm: new Date(SEXTA.getTime() - dias * DIA) });
    assert.equal(risco([s("auto_compra", 0)], SEXTA), 35);
    assert.equal(risco([s("auto_compra", 30)], SEXTA), 17, "metade depois de uma meia-vida");
    assert.equal(risco([s("foto_repetida", 0)], SEXTA), 0, "a foto repetida e informativa");
    assert.equal(risco(Array.from({ length: 5 }, () => s("auto_compra", 0)), SEXTA), 100);
  });

  it("escada automatica: um degrau de cada vez, so ate a limitacao, nunca para baixo", () => {
    assert.equal(passoAutomatico(29, null), null);
    assert.equal(passoAutomatico(30, null), "aviso");
    assert.equal(passoAutomatico(60, null), "aviso", "sem salto");
    assert.equal(passoAutomatico(60, "aviso"), "limitacao");
    assert.equal(passoAutomatico(100, "limitacao"), null, "nunca suspende");
    assert.equal(passoAutomatico(30, "limitacao"), null);
    assert.equal(passoAutomatico(100, "suspensao"), null);
  });

  it("uma sancao recusa-se sem motivo, quando salta sem justificacao, e quando e grave e automatica", () => {
    const base = { origem: "humana" as const, motivoInterno: "x", justificacaoDoSalto: null, emVigor: null };
    assert.equal(recusaDaSancao({ ...base, passo: "aviso", motivoInterno: "  " }), "sem_motivo");
    assert.equal(recusaDaSancao({ ...base, passo: "suspensao" }), "salto_sem_justificacao");
    assert.equal(recusaDaSancao({ ...base, passo: "suspensao", justificacaoDoSalto: "fraude provada" }), null);
    assert.equal(recusaDaSancao({ ...base, passo: "suspensao", emVigor: "limitacao" }), null);
    assert.equal(recusaDaSancao({ ...base, passo: "aviso", origem: "automatica" }), null);
    assert.equal(recusaDaSancao({ ...base, passo: "suspensao", origem: "automatica", emVigor: "limitacao" }), "grave_automatica");
    assert.equal(recusaDaSancao({ ...base, passo: "banir" }), "passo_desconhecido");
  });

  it("a severidade de cada tipo e fixa e cobre os nove tipos", () => {
    assert.deepEqual(Object.keys(SEVERIDADE_DO_TIPO).sort(), [...TIPOS_DE_SINAL].sort());
    assert.deepEqual(Object.keys(POLITICA_DE_RISCO.pesos).sort(), [...TIPOS_DE_SINAL].sort());
  });
});

// ------------------------------------------------------------------ escada

describe("sinais e escada automatica", () => {
  it("um alto da o aviso; dois altos dao aviso e limitacao; nada mais sobe sozinho", async () => {
    const m = montar();
    const a = await m.sinal("auto_compra");
    assert.deepEqual(a.sancoes.map((s) => s.passo), ["aviso"]);
    const b = await m.sinal("violacao_de_categoria");
    assert.deepEqual(b.sancoes.map((s) => s.passo), ["limitacao"]);
    for (let i = 0; i < 5; i++) await m.sinal("auto_compra");
    assert.equal(await m.trust.passoEmVigor(m.tenantId), "limitacao");
    assert.equal(m.tenants.estados.get(m.tenantId), "ativo", "a maquina nunca suspende");
    assert.ok(m.repositorio.sancoes.every((s) => s.origem === "automatica" && s.autor === "sistema:1.0.0"));
  });

  it("um risco de 60 sem nada em vigor grava aviso e limitacao, nessa ordem, sem salto", async () => {
    const m = montar();
    await m.repositorio.gravarSinal({ tenantId: m.tenantId, tipo: "auto_compra", refEvento: randomUUID(), detalhe: {}, ocorridoEm: SEXTA });
    const r = await m.sinal("burla_provavel");
    assert.deepEqual(r.sancoes.map((s) => s.passo), ["aviso", "limitacao"]);
  });

  it("limitacao em vigor: sem produtos novos e tecto no nivel 0; o painel ve os dois codigos, sem heuristica", async () => {
    const m = montar();
    await m.sinal("auto_compra");
    await m.sinal("auto_compra");
    assert.deepEqual(await m.trust.restricoes(m.tenantId), { passo: "limitacao", semNovosProdutos: true, tectoNoNivelZero: true });
    assert.deepEqual(await m.trust.avisosDoPainel(m.tenantId), ["actividade_limitada", "conduta_em_analise"]);
  });

  it("um detalhe com uma chave fora da lista recusa-se: o detalhe so leva referencias", async () => {
    const m = montar();
    await recusaDoTrust(
      m.trust.registar({ tenantId: m.tenantId, tipo: "auto_compra", refEvento: randomUUID(), detalhe: { telefone: "x" } as never, ocorridoEm: SEXTA }),
      "detalhe_invalido",
    );
  });
});

// --------------------------------------------------- a decisao humana pela fila

describe("escada humana pela fila de revisao (integracao)", () => {
  async function suspender(m: ReturnType<typeof montar>, revisorDaPrimeira = revisor()) {
    const s = await m.sinal("auto_compra");
    await m.sinal("auto_compra");
    const r = await m.trust.proporSancao({
      tenantId: m.tenantId,
      passo: "suspensao",
      motivoInterno: "auto-compra repetida",
      sinais: [s.sinal.id],
      justificacaoDoSalto: null,
      chave: "s1",
    });
    assert.ok(r.estado === "aberto");
    const d = await m.servico.decidir(revisorDaPrimeira, r.caso.id, "rejeitar", { regra: "ts_auto_compra" });
    assert.equal(d.estado, "decidido");
    return { caso: r.caso, revisorDaPrimeira };
  }

  it("aviso -> limitacao (automaticos) -> suspensao por decisao humana: o tenant fica suspenso e o dono e avisado", async () => {
    const m = montar();
    const { caso } = await suspender(m);
    assert.equal(m.tenants.estados.get(m.tenantId), "suspenso");
    const grave = m.repositorio.sancoes.find((s) => s.passo === "suspensao")!;
    assert.equal(grave.origem, "humana");
    assert.equal(grave.casoId, caso.id);
    assert.equal(grave.regra, "ts_auto_compra");
    assert.equal(grave.motivoPublico, "loja_suspensa");
    assert.deepEqual(m.avisos.at(-1), { tenantId: m.tenantId, motivo: "loja_suspensa" });
  });

  it("aprovar o caso deixa o tenant como esta e nao grava sancao nenhuma", async () => {
    const m = montar();
    await m.sinal("auto_compra");
    await m.sinal("auto_compra");
    const r = await m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: "x", sinais: [], justificacaoDoSalto: null, chave: "s1" });
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "aprovar");
    assert.equal(m.tenants.estados.get(m.tenantId), "ativo");
    assert.ok(!m.repositorio.sancoes.some((s) => s.passo === "suspensao"));
  });

  it("(f) suspender sem motivo e recusado: na proposta, e na decisao sem regra", async () => {
    const m = montar();
    await m.sinal("auto_compra");
    await m.sinal("auto_compra");
    await recusaDoTrust(
      m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: " ", sinais: [], justificacaoDoSalto: null, chave: "s1" }),
      "sem_motivo",
    );
    const r = await m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: "x", sinais: [], justificacaoDoSalto: null, chave: "s1" });
    assert.ok(r.estado === "aberto");
    await recusaDaFila(m.servico.decidir(revisor(), r.caso.id, "rejeitar"), "decisao_invalida");
    await recusaDaFila(m.servico.decidir(revisor(), r.caso.id, "rejeitar", { regra: "  " }), "decisao_invalida");
    assert.equal(m.tenants.estados.get(m.tenantId), "ativo");
  });

  it("saltar passos exige justificacao escrita, e com ela passa e fica gravada", async () => {
    const m = montar();
    await recusaDoTrust(
      m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: "x", sinais: [], justificacaoDoSalto: null, chave: "s1" }),
      "salto_sem_justificacao",
    );
    const r = await m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: "x", sinais: [], justificacaoDoSalto: "venda de produto proibido provada", chave: "s1" });
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "rejeitar", { regra: "ts_categoria" });
    const s = m.repositorio.sancoes.find((x) => x.passo === "suspensao")!;
    assert.equal(s.justificacaoDoSalto, "venda de produto proibido provada");
    assert.equal(m.tenants.estados.get(m.tenantId), "suspenso");
  });

  it("recurso uma so vez, decidido por outro revisor: provido levanta a suspensao", async () => {
    const m = montar();
    const { caso, revisorDaPrimeira } = await suspender(m);
    await m.trust.pedirRecurso(m.tenantId, m.repositorio.sancoes.find((s) => s.passo === "suspensao")!.id);
    await recusaDaFila(m.servico.decidirRecurso(revisorDaPrimeira, caso.id, "aprovar"), "revisor_da_primeira_instancia");
    await m.servico.decidirRecurso(revisor(), caso.id, "aprovar");
    assert.equal(m.tenants.estados.get(m.tenantId), "ativo");
    const desfecho = m.repositorio.sancoes.find((s) => s.recursoDe !== null)!;
    assert.equal(desfecho.recursoEstado, "provido");
    assert.deepEqual(m.avisos.at(-1), { tenantId: m.tenantId, motivo: "recurso_aceite" });
    // O segundo recurso: a fila recusa-o, e T&S tambem.
    await assert.rejects(m.servico.abrirRecurso(caso.id), (e: unknown) => e instanceof RevisaoRecusadaError);
    await recusaDoTrust(m.trust.pedirRecurso(m.tenantId, desfecho.recursoDe!), "recurso_ja_usado");
  });

  it("recurso negado mantem a suspensao e diz ao dono que e final", async () => {
    const m = montar();
    const { caso } = await suspender(m);
    await m.servico.abrirRecurso(caso.id);
    await m.servico.decidirRecurso(revisor(), caso.id, "rejeitar");
    assert.equal(m.tenants.estados.get(m.tenantId), "suspenso");
    assert.deepEqual(m.avisos.at(-1), { tenantId: m.tenantId, motivo: "recurso_mantido" });
  });

  it("encerramento: suspende ja; so passa a encerrado com o recurso negado, ou com o prazo de recurso vencido", async () => {
    const m = montar();
    await suspender(m);
    const r = await m.trust.proporSancao({ tenantId: m.tenantId, passo: "encerramento", motivoInterno: "fraude reiterada", sinais: [], justificacaoDoSalto: null, chave: "e1" });
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(lider(), r.caso.id, "rejeitar", { regra: "ts_fraude" });
    assert.equal(m.tenants.estados.get(m.tenantId), "suspenso", "ainda pode recorrer");
    const porFechar = async (ate: Date) =>
      m.repositorio.sancoes.filter((s) => s.passo === "encerramento" && s.recursoDe === null && s.em <= ate);
    assert.equal(await m.trust.fecharEncerramentos(porFechar), 0, "dentro do prazo");
    m.avancarDias(15);
    assert.equal(await m.trust.fecharEncerramentos(porFechar), 1);
    assert.equal(m.tenants.estados.get(m.tenantId), "encerrado");
  });

  it("o recurso de um passo automatico e um caso `recurso`, unico, e nao se recorre dele", async () => {
    const m = montar();
    const a = await m.sinal("auto_compra");
    const aviso = a.sancoes[0]!;
    const caso = await m.trust.pedirRecurso(m.tenantId, aviso.id);
    assert.equal(caso.tipo, "recurso");
    await recusaDoTrust(m.trust.pedirRecurso(m.tenantId, aviso.id), "recurso_ja_usado");
    await m.servico.decidir(revisor(), caso.id, "rejeitar");
    await recusaDaFila(m.servico.abrirRecurso(caso.id), "recurso_ja_usado");
    assert.equal(m.repositorio.sancoes.find((s) => s.recursoDe === aviso.id)?.recursoEstado, "negado");
  });

  it("um aviso automatico com recurso provido deixa de estar em vigor", async () => {
    const m = montar();
    const a = await m.sinal("auto_compra");
    const caso = await m.trust.pedirRecurso(m.tenantId, a.sancoes[0]!.id);
    await m.servico.decidir(revisor(), caso.id, "aprovar");
    assert.equal(await m.trust.passoEmVigor(m.tenantId), null);
    assert.deepEqual(await m.trust.avisosDoPainel(m.tenantId), []);
  });

  it("quem e parte no tenant nao decide a sancao dele", async () => {
    const m = montar();
    await m.sinal("auto_compra");
    await m.sinal("auto_compra");
    const r = await m.trust.proporSancao({ tenantId: m.tenantId, passo: "suspensao", motivoInterno: "x", sinais: [], justificacaoDoSalto: null, chave: "s1" });
    assert.ok(r.estado === "aberto");
    const parte = revisor({ telefoneHmac: m.onboardingDoTenant.telefoneHmac });
    await recusaDaFila(m.servico.decidir(parte, r.caso.id, "rejeitar", { regra: "x" }), "parte_no_caso");
  });

  it("sem T&S ligado, decidir um caso trust e um efeito por aplicar, e nao um silencio", async () => {
    const r = montarRevisao();
    const o = r.onboarding({ fase: "activo" });
    const aberto = await r.servico.abrir({
      tipo: "trust",
      tenantId: o.tenantId,
      onboardingId: null,
      motivoCodigo: "sancao_aviso:a1",
      motivoInterno: "x",
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [{ tipo: "ts_proposta", ref: JSON.stringify({ passo: "aviso", justificacao: null }) }],
      recomendacao: "rejeitar",
      prioridade: 3,
    });
    assert.ok(aberto.estado === "aberto");
    await assert.rejects(r.servico.decidir(revisor(), aberto.caso.id, "rejeitar", { regra: "x" }), { name: "EfeitoPorAplicarError" });
  });

  it("reaplicar os efeitos de uma suspensao e idempotente: uma linha, uma transicao", async () => {
    const m = montar();
    const { caso } = await suspender(m);
    await m.servico.reaplicarEfeitos(caso.id);
    assert.equal(m.repositorio.sancoes.filter((s) => s.passo === "suspensao").length, 1);
    assert.equal(m.tenants.transicoes.length, 1);
  });
});

// ------------------------------------------------------------- a base em memoria

describe("as barreiras da base, no duplo", () => {
  it("o kamba_app nao escreve linha humana nem desfecho de recurso", async () => {
    const repo = new RepositorioDeTrustEmMemoria();
    repo.papel = "kamba_app";
    const base = {
      tenantId: randomUUID(),
      chave: "caso:x",
      passo: "aviso" as const,
      motivoInterno: "x",
      motivoPublico: "conduta_em_analise" as const,
      autor: randomUUID(),
      regra: null,
      sinais: [],
      justificacaoDoSalto: null,
      recursoDe: null,
      recursoEstado: null,
    };
    await assert.rejects(repo.gravarSancao({ ...base, origem: "humana", casoId: randomUUID() }), (e: unknown) => e instanceof RecusaDaBaseError && e.codigo === "42501");
  });

  it("uma suspensao automatica recusa-se mesmo escrita a mao", async () => {
    const repo = new RepositorioDeTrustEmMemoria();
    await assert.rejects(
      repo.gravarSancao({
        tenantId: randomUUID(),
        chave: "auto:suspensao:x",
        passo: "suspensao",
        origem: "automatica",
        motivoInterno: "x",
        motivoPublico: "loja_suspensa",
        autor: "sistema:1.0.0",
        regra: null,
        sinais: [],
        casoId: null,
        justificacaoDoSalto: "x",
        recursoDe: null,
        recursoEstado: null,
      }),
      RecusaDaBaseError,
    );
  });
});

// ----------------------------------------------------------- aviso ao dono

describe("aviso ao dono (criterio 9)", () => {
  it("cada motivo tem o seu SMS, sem parametros, com o texto fixo e nada mais", () => {
    for (const motivo of MOTIVOS_PUBLICOS_DA_SANCAO) {
      const modelo = MODELOS[MODELO_DO_MOTIVO[motivo]];
      assert.deepEqual(modelo.parametros, []);
      assert.equal(modelo.corpo, `KAMBA: ${TEXTO_DO_MOTIVO_DA_SANCAO[motivo]}`);
      assert.equal(modelo.finalidade, "aviso_de_servico");
      assert.ok(modelo.corpo.length <= 160);
      // biome-ignore lint/suspicious/noControlCharactersInRegex: e o teste de ASCII
      assert.match(modelo.corpo, /^[\x20-\x7e]+$/);
    }
  });

  it("o SMS vai para o telefone do onboarding com o modelo do motivo, e nunca leva o motivo interno", async () => {
    const enviados: { modelo: string; parametros: unknown }[] = [];
    const aviso = new AvisoDeSancaoPorSms({
      sms: { send: async (_d, modelo, parametros) => (enviados.push({ modelo, parametros }), { id: "1", estado: "aceite" } as never) },
      telefone: { ler: async () => "+244 000 000 101" },
      pepperDoDestino: new Uint8Array(32),
    });
    await aviso.avisar({ tenantId: randomUUID(), motivo: "loja_suspensa" });
    assert.deepEqual(enviados, [{ modelo: "ts_suspensao", parametros: {} }]);
    const semTelefone = new AvisoDeSancaoPorSms({ sms: { send: async () => ({}) as never }, telefone: { ler: async () => null }, pepperDoDestino: new Uint8Array(32) });
    await assert.rejects(semTelefone.avisar({ tenantId: randomUUID(), motivo: "loja_suspensa" }), { name: "AvisoDeSancaoSemDestinoError" });
  });
});

// ------------------------------------------------------- adversarial do bloco

/** Um cliente SQL que responde por constante: a fotografia dos factos de um evento. */
function bdDeFactos(respostas: Map<string, Record<string, unknown>[]>) {
  const pedidas: string[] = [];
  return {
    pedidas,
    async query(sql: string) {
      pedidas.push(sql);
      return { rows: respostas.get(sql) ?? [], rowCount: 0 };
    },
  };
}

function envelope(tipo: string, payload: Record<string, unknown>, tenantId = randomUUID()) {
  return { id: randomUUID(), tipo, tenant_id: tenantId, ocorrido_em: SEXTA.toISOString(), payload };
}

describe("suite adversarial (KAM-097)", () => {
  it("(a) formatos do telefone e BSUID do dono: a identidade da o mesmo HMAC, logo o mesmo contacto, e a auto-compra sai", async () => {
    // A identidade (KAM-008) resolve um telefone pelo HMAC do E.164 normalizado:
    // com e sem o `+` sao o mesmo HMAC, e por isso o mesmo contacto.
    const chave = new Uint8Array(32).fill(7);
    const tenant = randomUUID();
    const formas = ["+999000000101", "999000000101"].map((t) => hmacDePesquisa(chave, tenant, "telefone", normalizarTelefone(t)).toString("hex"));
    assert.equal(new Set(formas).size, 1);
    // O comprador e o contacto do dono (ou um absorvido nele): a regra compara o canonico.
    const dono = "11111111-1111-4111-8111-111111111111";
    const orderId = randomUUID();
    const bd = bdDeFactos(
      new Map<string, Record<string, unknown>[]>([
        [SQL_PEDIDO_E_COMPRADOR, [{ order_id: orderId, contactos: ["22222222-2222-4222-8222-222222222222", dono], paga_via: "manual_auditado" }]],
        [SQL_CONTACTOS_DO_DONO, [{ contact_id: dono }]],
      ]),
    );
    const s = await sinaisDoEvento(bd, envelope("order.paid", { order_id: orderId, paga_via: "provider_autenticado" }, tenant), SEXTA);
    assert.deepEqual(s.map((x) => [x.tipo, x.refEvento, x.detalhe.coincidencia]), [["auto_compra", orderId, "contact_id"]]);
  });

  it("(b) segunda SIM desconhecida: outro contacto, sem sinal — limitacao documentada", async () => {
    const orderId = randomUUID();
    const bd = bdDeFactos(
      new Map<string, Record<string, unknown>[]>([
        [SQL_PEDIDO_E_COMPRADOR, [{ order_id: orderId, contactos: [randomUUID()], paga_via: null }]],
        [SQL_CONTACTOS_DO_DONO, [{ contact_id: randomUUID() }]],
      ]),
    );
    assert.deepEqual(await sinaisDoEvento(bd, envelope("order.created", { order_id: orderId }), SEXTA), []);
  });

  it("(d) reclamacoes de quem nao pagou sao ignoradas; de dois compradores pagos, contam", async () => {
    const pago = [randomUUID(), randomUUID()];
    const respostas = (queixas: string[]) =>
      new Map<string, Record<string, unknown>[]>([
        [SQL_QUEIXAS, queixas.map((c) => ({ contact_id: c, em: SEXTA }))],
        [SQL_COMPRADORES_PAGOS, pago.map((c) => ({ contact_id: c }))],
      ]);
    const falsas = await sinaisDoEvento(bdDeFactos(respostas([randomUUID(), randomUUID(), randomUUID()])), envelope("query.handoff", { motivo: "reclamacao_grave" }), SEXTA);
    assert.deepEqual(falsas, []);
    const reais = await sinaisDoEvento(bdDeFactos(respostas(pago)), envelope("query.handoff", { motivo: "reclamacao_grave" }), SEXTA);
    assert.deepEqual(reais.map((x) => [x.tipo, x.detalhe.contagem]), [["queixa_recorrente", 2]]);
    const outroMotivo = bdDeFactos(respostas(pago));
    assert.deepEqual(await sinaisDoEvento(outroMotivo, envelope("query.handoff", { motivo: "ttl" }), SEXTA), []);
    assert.deepEqual(outroMotivo.pedidas, [], "um handoff que nao e reclamacao nem le a base");
  });

  it("(e) reentrega do evento, e order.created seguido de order.paid da mesma encomenda: um sinal", async () => {
    const m = montar();
    const orderId = randomUUID();
    const s = { tenantId: m.tenantId, tipo: "auto_compra" as const, refEvento: orderId, detalhe: { order_id: orderId }, ocorridoEm: SEXTA };
    const a = await m.trust.registar(s);
    const b = await m.trust.registar(s);
    assert.equal(a.repetido, false);
    assert.equal(b.repetido, true);
    assert.deepEqual(b.sancoes, [], "a reentrega nao volta a correr a escada");
    assert.equal(m.repositorio.sinais.length, 1);
    assert.equal(m.repositorio.sancoes.length, 1);
  });

  it("burla e confirmacao suspeita saem do order.paid e do payment.manual_confirmed com os factos certos", async () => {
    const tenant = randomUUID();
    const orderId = randomUUID();
    const rapidos = [orderId, randomUUID(), randomUUID()].map((id) => ({
      order_id: id,
      total_minor: "4800000",
      criado_at: SEXTA,
      paga_at: new Date(SEXTA.getTime() + 5_000),
    }));
    const respostas = new Map<string, Record<string, unknown>[]>([
      [SQL_PEDIDO_E_COMPRADOR, [{ order_id: orderId, contactos: [randomUUID()], paga_via: "manual_auditado" }]],
      [SQL_CONTACTOS_DO_DONO, []],
      [SQL_TENANT_E_TECTO, [{ primeira_activacao_at: new Date(SEXTA.getTime() - 3 * DIA), tecto: "5000000" }]],
      [SQL_PEDIDOS_MANUAIS, rapidos],
    ]);
    const pago = await sinaisDoEvento(bdDeFactos(respostas), envelope("order.paid", { order_id: orderId, paga_via: "manual_auditado" }, tenant), SEXTA);
    assert.deepEqual(pago.map((x) => [x.tipo, x.refEvento]), [["burla_provavel", tenant]]);
    const confirmado = await sinaisDoEvento(bdDeFactos(respostas), envelope("payment.manual_confirmed", { order_id: orderId }, tenant), SEXTA);
    assert.deepEqual(confirmado.map((x) => [x.tipo, x.refEvento]), [["confirmacao_suspeita", orderId]]);
  });

  it("a violacao de categoria vira sinal alto, com o sku e a versao e nada mais", async () => {
    const env = envelope("screening.violation_detected", { sku: "SKU-1", regras: ["alcool"], versao_politica: "1.0.0+m.2", sha256: "x" });
    const s = await sinaisDoEvento(bdDeFactos(new Map()), env, SEXTA);
    assert.deepEqual(s.map((x) => [x.tipo, x.refEvento, x.detalhe]), [["violacao_de_categoria", env.id, { sku: "SKU-1", versao_politica: "1.0.0+m.2" }]]);
  });

  it("o order.delivered e o payment.confirmed consomem-se sem sinal e sem ler a base", async () => {
    for (const tipo of ["order.delivered", "payment.confirmed"]) {
      const bd = bdDeFactos(new Map());
      assert.deepEqual(await sinaisDoEvento(bd, envelope(tipo, { order_id: randomUUID() }), SEXTA), []);
      assert.deepEqual(bd.pedidas, []);
    }
  });
});

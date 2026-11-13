/**
 * As regressões da revisão adversarial do KAM-089: um ensaio por achado
 * confirmado, cada um a falhar no código que o revisor reviu (`3bf95224`) e a
 * passar no corrigido. Os nomes dizem a propriedade, e a letra entre parênteses
 * é a da reprodução do revisor.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import { CifraAesGcm } from "../src/kyc/index.ts";
import {
  FERIADOS_POR_OMISSAO,
  MetricasDaRevisao,
  RevisaoRecusadaError,
  ServicoDeRevisao,
  escritorComFila,
  filaDoGuia,
  filaDoKyc,
  prioridadeDoKyc,
} from "../src/revisao/index.ts";
import type { LinhaDeDecisao } from "../src/screening/motor.ts";

import { montarRevisao, revisor } from "./apoio/revisao.ts";

const recusa = (motivo: string) => (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === motivo;

describe("o recurso e o desbloqueio do onboarding", () => {
  it("(A) o recurso de uma categoria nao aprova um onboarding cujo kyc continua rejeitado", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const k = await m.abrir(o, { tipo: "kyc" });
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:abc" });
    assert.ok(k.estado === "aberto" && c.estado === "aberto");
    const r1 = revisor();
    await m.servico.decidir(r1, k.caso.id, "rejeitar");
    await m.servico.decidir(r1, c.caso.id, "rejeitar");
    await m.servico.abrirRecurso(c.caso.id);
    assert.equal((await m.servico.decidirRecurso(revisor(), c.caso.id, "aprovar")).estado, "decidido");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "rejeitado");
  });

  it("(A2) o recurso de uma categoria nao aprova um onboarding que o KYC rejeitou sozinho, sem caso", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:abc" });
    assert.ok(c.estado === "aberto");
    m.onboardings.casos.set(o.id, { ...m.onboardings.casos.get(o.id)!, fase: "rejeitado" });
    await m.servico.decidir(revisor(), c.caso.id, "rejeitar");
    await m.servico.abrirRecurso(c.caso.id);
    await m.servico.decidirRecurso(revisor(), c.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "rejeitado");
  });

  it("o recurso do proprio kyc, sem mais nada rejeitado, aprova", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const k = await m.abrir(o, { tipo: "kyc" });
    assert.ok(k.estado === "aberto");
    await m.servico.decidir(revisor(), k.caso.id, "rejeitar");
    await m.servico.abrirRecurso(k.caso.id);
    await m.servico.decidirRecurso(revisor(), k.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
  });

  it("(G) nao ha recurso de uma aprovacao", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const c = await m.abrir(o);
    assert.ok(c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "aprovar");
    await assert.rejects(m.servico.abrirRecurso(c.caso.id), recusa("recurso_sem_rejeicao"));
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
  });

  it("(M) um caso escalado na primeira instancia so o ts_lider o decide no recurso", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const c = await m.abrir(o);
    assert.ok(c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "escalar");
    await m.servico.decidir(revisor({ papeis: ["ts_lider"] }), c.caso.id, "rejeitar");
    await m.servico.abrirRecurso(c.caso.id);
    await assert.rejects(m.servico.decidirRecurso(revisor(), c.caso.id, "aprovar"), recusa("so_lider"));
    assert.equal((await m.servico.decidirRecurso(revisor({ papeis: ["ts_lider"] }), c.caso.id, "aprovar")).estado, "decidido");
  });

  it("(I) aprovar uma categoria com o kyc pendente nao avisa o dono de aprovado", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    await m.abrir(o, { tipo: "kyc" });
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:abc" });
    assert.ok(c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "em_revisao");
    assert.deepEqual(m.avisos, []);
  });

  it("(J) um efeito que falha retoma-se com reaplicarEfeitos", async () => {
    const base = montarRevisao();
    const o = base.onboarding();
    let falhar = true;
    const s = new ServicoDeRevisao({
      repositorio: base.repositorio,
      onboardings: base.onboardings,
      auditoria: base.auditoria,
      aviso: { avisar: async () => {} },
      alerta: () => {},
      cifra: new CifraAesGcm(randomBytes(32)),
      dados: { ler: async () => null },
      documentos: { url: async () => "x" },
      screening: {
        gravar: async () => {
          if (falhar) throw new Error("screening em baixo");
        },
      },
      relogio: () => base.agora(),
    });
    const chave = { sujeitoTipo: "categoria", sujeitoRef: "moda", versaoPolitica: "1.0.0+m.2", conteudoSha256: "ab".repeat(32) };
    const c = await s.abrir({
      tipo: "categoria", tenantId: o.tenantId, onboardingId: o.id, motivoCodigo: "screening:x", motivoInterno: "x",
      motivoPublico: "categoria_nao_permitida", evidencias: [{ tipo: "screening_decision", ref: JSON.stringify(chave) }],
      recomendacao: null, prioridade: 5,
    });
    assert.ok(c.estado === "aberto");
    await assert.rejects(s.decidir(revisor(), c.caso.id, "aprovar"), /screening em baixo/);
    assert.equal(base.onboardings.casos.get(o.id)!.fase, "em_revisao");
    falhar = false;
    await s.reaplicarEfeitos(c.caso.id);
    assert.equal(base.onboardings.casos.get(o.id)!.fase, "aprovado");
    await assert.rejects(s.reaplicarEfeitos(randomUUID()));
  });
});

describe("o reenvio e a reabertura", () => {
  it("(B) o reenvio do KYC depois de um pedir_info reforca o caso: prioridade, motivo e evidencias novos, e volta a pedir dois revisores", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "kyc_pendente" });
    let docs = [{ id: randomUUID() }];
    const fila = filaDoKyc(m.servico, m.onboardings, { doCaso: async () => docs as never });
    await fila.enviar({ onboardingId: o.id, score: 25, marcas: ["confianca_baixa"], recomendacao: "pedir_documentos" });
    const caso = [...m.repositorio.casos.values()][0]!;
    assert.equal(caso.prioridade, 5);
    await m.servico.decidir(revisor(), caso.id, "pedir_info");
    const novo = randomUUID();
    docs = [...docs, { id: novo }];
    await fila.enviar({ onboardingId: o.id, score: 100, marcas: ["nif_divergente", "imagem_reutilizada"], recomendacao: "investigar" });
    const depois = m.repositorio.casos.get(caso.id)!;
    assert.equal(m.repositorio.casos.size, 1);
    assert.equal(depois.prioridade, 1);
    assert.match(depois.motivoInterno, /nif_divergente/);
    assert.equal(depois.recomendacao, "investigar");
    await m.servico.urlDoDocumento(revisor(), caso.id, novo);
    m.onboardings.casos.set(o.id, { ...m.onboardings.casos.get(o.id)!, fase: "em_revisao" });
    assert.equal((await m.servico.decidir(revisor(), caso.id, "aprovar")).estado, "aguarda_segundo_revisor");
  });

  it("um reenvio menos grave nao baixa a prioridade", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    await m.abrir(o, { prioridade: 1 });
    const r = await m.abrir(o, { prioridade: 5 });
    assert.ok(r.estado === "aberto" && r.repetido);
    assert.equal(r.caso.prioridade, 1);
  });

  it("(K) a chave de um caso decidido devolve ja_decidido; o guia abre um caso novo para a falha nova", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "aguarda_es" });
    const a = await m.abrir(o, { tipo: "es_falhado", motivoCodigo: "es_falhado" });
    assert.ok(a.estado === "aberto");
    await m.servico.decidir(revisor(), a.caso.id, "rejeitar");
    assert.equal((await m.abrir(o, { tipo: "es_falhado", motivoCodigo: "es_falhado" })).estado, "ja_decidido");
    await filaDoGuia(m.servico, m.onboardings).abrir(o.id, "es_falhado", "numero_divergente");
    const novos = [...m.repositorio.casos.values()].filter((c) => c.estado === "aberto");
    assert.equal(novos.length, 1);
    assert.equal(novos[0]!.motivoCodigo, `es_falhado:${a.caso.id.slice(0, 8)}`);
  });

  it("o KYC que manda sobre um caso decidido falha fechado", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const fila = filaDoKyc(m.servico, m.onboardings, { doCaso: async () => [] });
    await fila.enviar({ onboardingId: o.id, score: 30, marcas: ["confianca_baixa"], recomendacao: "investigar" });
    await m.servico.decidir(revisor(), [...m.repositorio.casos.values()][0]!.id, "rejeitar");
    m.onboardings.casos.set(o.id, { ...m.onboardings.casos.get(o.id)!, fase: "kyc_pendente" });
    await assert.rejects(fila.enviar({ onboardingId: o.id, score: 30, marcas: ["confianca_baixa"], recomendacao: "investigar" }), /decidido/);
  });
});

describe("a quota", () => {
  it("(C) os casos de catalogo sem onboarding contam contra a quota do tenant", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 1 } });
    const esc = escritorComFila({ gravar: async () => {} }, m.servico);
    const tenantId = randomUUID();
    const linha = (i: number): LinhaDeDecisao => ({
      tenantId, onboardingId: null, sujeitoTipo: "produto", sujeitoRef: `p${i}`, decisao: "condicional",
      regras: ["x"], versaoPolitica: "1.0.0+m.2", origem: "regra", conteudoSha256: new Uint8Array(randomBytes(32)),
    });
    for (let i = 0; i < 50; i++) await esc.gravar(linha(i));
    const casos = [...m.repositorio.casos.values()];
    assert.equal(casos.filter((c) => c.estado === "aberto").length, 1);
    assert.equal(m.alertas.length, 49);
    // Outro tenant tem a sua.
    await escritorComFila({ gravar: async () => {} }, m.servico).gravar({ ...linha(99), tenantId: randomUUID() });
    assert.equal([...m.repositorio.casos.values()].filter((c) => c.estado === "aberto").length, 2);
  });

  it("(E) duzentas aberturas concorrentes da mesma origem dao vinte casos abertos", async () => {
    const m = montarRevisao();
    const rede = randomBytes(32).toString("hex");
    const os = Array.from({ length: 200 }, () => m.onboarding({ redeHmac: rede }));
    const r = await Promise.all(os.map((o) => m.abrir(o)));
    assert.equal(r.filter((x) => x.estado === "aberto").length, 20);
    assert.equal(r.filter((x) => x.estado === "em_triagem_automatica").length, 180);
  });
});

describe("quem e parte, e a auditoria", () => {
  it("(D) o dono de um onboarding nao ve nem decide a auditoria da propria aprovacao", async () => {
    const m = montarRevisao({ limiares: { fracaoDaAmostra: 1 }, inicioDaAmostragem: new Date("2026-11-01T00:00:00Z") });
    const o = m.onboarding({ fase: "activo" });
    const a = await m.servico.amostrar(o.id, o.tenantId);
    assert.ok(a !== null && a.estado === "aberto");
    const dono = revisor({ nifHmac: o.nifHmac });
    await assert.rejects(m.servico.ver(dono, a.caso.id), recusa("parte_no_caso"));
    await assert.rejects(m.servico.decidir(dono, a.caso.id, "aprovar"), recusa("parte_no_caso"));
  });

  it("um caso de catalogo sem onboarding mede a parte pelo onboarding do tenant", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "activo" });
    const r = await m.servico.abrir({
      tipo: "catalogo", tenantId: o.tenantId, onboardingId: null, motivoCodigo: "screening:y", motivoInterno: "x",
      motivoPublico: "categoria_nao_permitida", evidencias: [], recomendacao: null, prioridade: 5,
    });
    assert.ok(r.estado === "aberto");
    await assert.rejects(m.servico.decidir(revisor({ telefoneHmac: o.telefoneHmac }), r.caso.id, "aprovar"), recusa("parte_no_caso"));
  });

  it("(L) a auditoria mostra os dados mascarados do onboarding amostrado e abre os documentos dele", async () => {
    const m = montarRevisao({ limiares: { fracaoDaAmostra: 1 }, inicioDaAmostragem: new Date("2026-11-01T00:00:00Z") });
    const o = m.onboarding({ fase: "activo" });
    m.dados.set(o.id, { nif: "5417038261" });
    const a = await m.servico.amostrar(o.id, o.tenantId);
    assert.ok(a !== null && a.estado === "aberto");
    assert.equal((await m.servico.ver(revisor(), a.caso.id)).dados.nif, "*******261");
    const doc = randomUUID();
    await m.servico.urlDoDocumento(revisor(), a.caso.id, doc);
    assert.deepEqual(m.urls.at(-1), { revisor: m.urls.at(-1)!.revisor, onboardingId: o.id, verificacaoId: doc });
  });
});

describe("a concorrencia e o registo", () => {
  it("(H) duas aprovacoes concorrentes de risco alto fecham o caso", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const c = await m.abrir(o, { prioridade: 1 });
    assert.ok(c.estado === "aberto");
    const r = await Promise.allSettled([
      m.servico.decidir(revisor(), c.caso.id, "aprovar"),
      m.servico.decidir(revisor(), c.caso.id, "aprovar"),
    ]);
    assert.ok(r.some((x) => x.status === "fulfilled" && x.value.estado === "decidido"), JSON.stringify(r.map((x) => x.status)));
    assert.equal(m.repositorio.casos.get(c.caso.id)!.estado, "decidido");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
  });

  it("(14) uma lista recusada tambem fica no audit_log, e ver um caso fica registado", async () => {
    const m = montarRevisao();
    await assert.rejects(m.servico.listar(revisor({ mfa: false })), recusa("sem_mfa"));
    assert.deepEqual(m.auditoria.linhas.at(-1), {
      accao: "review.recusa", tenantId: null, actorId: m.auditoria.linhas.at(-1)!.actorId, entidade: "review_case", entidadeId: "fila", detalhe: "sem_mfa",
    });
    const c = await m.abrir(m.onboarding());
    assert.ok(c.estado === "aberto");
    await m.servico.ver(revisor(), c.caso.id);
    assert.equal(m.auditoria.linhas.at(-1)!.detalhe, "ver");
    assert.equal(m.auditoria.linhas.at(-1)!.entidadeId, c.caso.id);
  });

  it("(F) o recurso nao apaga a entrada: o p90 continua a medir a primeira decisao", async () => {
    const m = montarRevisao();
    const c = await m.abrir(m.onboarding());
    assert.ok(c.estado === "aberto");
    m.avancar(5 * 3_600_000);
    await m.servico.decidir(revisor(), c.caso.id, "rejeitar");
    m.avancar(3_600_000);
    const rec = await m.servico.abrirRecurso(c.caso.id);
    assert.equal(rec.filaEm.getTime(), c.caso.filaEm.getTime());
    const primeira = m.repositorio.registo.find((d) => d.casoId === c.caso.id)!.em;
    const met = new MetricasDaRevisao();
    met.actualizar([{ tipo: rec.tipo, estado: rec.estado, filaEm: rec.filaEm, primeiraDecisaoEm: primeira }], [], FERIADOS_POR_OMISSAO);
    assert.equal(met.p90, 5 * 3600);
  });
});

describe("as mutacoes que sobreviveram", () => {
  it("(M24) o score 60 ja e risco alto, e o 59 nao", () => {
    assert.equal(prioridadeDoKyc(["confianca_baixa"], 60), 2);
    assert.equal(prioridadeDoKyc(["confianca_baixa"], 59), 5);
  });

  it("(M26) uma bloqueada nao abre caso", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    await escritorComFila({ gravar: async () => {} }, m.servico).gravar({
      tenantId: o.tenantId, onboardingId: o.id, sujeitoTipo: "categoria", sujeitoRef: "armas", decisao: "bloqueada",
      regras: ["armas"], versaoPolitica: "1.0.0+m.2", origem: "regra", conteudoSha256: new Uint8Array(32),
    });
    assert.equal(m.repositorio.casos.size, 0);
  });

  it("(M38) o motivo publico escolhido pelo revisor e o que o dono le", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const c = await m.abrir(o);
    assert.ok(c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "rejeitar", { motivoPublico: "documento_expirado" });
    assert.equal(m.avisos.at(-1)!.motivoPublico, "documento_expirado");
  });
});

/**
 * A fila de revisão de ponta a ponta, com duplos (KAM-089).
 *
 * «abertura idempotente a partir de KAM-087/088; decisão desbloqueia o caso;
 * recurso por outro revisor» — os três ensaios de integração do bloco — mais os
 * de isolamento que se medem sem base («revisor sem papel não lê», «URL
 * expirada devolve 403», «toda a visualização gera registo»), o SLA, a quota, a
 * amostragem e as entradas do guia e do screening.
 *
 * A integração com o KYC usa o `ServicoKyc` **verdadeiro**, com o conjunto
 * sintético do KAM-087, e a porta `FilaDeRevisao` dele cumprida pelo
 * `filaDoKyc`: o caso que chega à fila é o que o KYC de facto manda.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  CasosEmMemoria,
  CifraAesGcm,
  OcrLocal,
  RasterizadorLocal,
  ServicoKyc,
  VerificacoesEmMemoria,
  type TipoDeDocumento,
} from "../src/kyc/index.ts";
import { criarStorageFake } from "../src/storage/index.ts";
import {
  CasoNaoElegivelError,
  RevisaoRecusadaError,
  ServicoDeRevisao,
  decisaoHumanaDeScreening,
  escritorComFila,
  filaDoGuia,
  filaDoKyc,
  prioridadeDoKyc,
  type OnboardingsDaRevisao,
} from "../src/revisao/index.ts";
import { assertPublishable, type LinhaDeDecisao } from "../src/screening/motor.ts";

import { HOJE, MotorDeGrelha, gerarConjunto, nifHmac } from "./apoio/kyc-sintetico.ts";
import { SEXTA, montarRevisao, revisor } from "./apoio/revisao.ts";

const H = 3_600_000;

async function recusa(p: Promise<unknown>, motivo: string): Promise<void> {
  await assert.rejects(p, (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === motivo);
}

// ---------------------------------------------------------------- abertura

describe("abertura idempotente (criterio 9)", () => {
  it("o mesmo pedido duas vezes cria um caso, e a segunda diz repetido", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const a = await m.abrir(o);
    const b = await m.abrir(o);
    assert.ok(a.estado === "aberto" && !a.repetido);
    assert.ok(b.estado === "aberto" && b.repetido && b.caso.id === a.caso.id);
    assert.equal(m.repositorio.casos.size, 1);
  });

  it("outro motivo, outro tipo ou outro onboarding sao outro caso", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    await m.abrir(o);
    await m.abrir(o, { motivoCodigo: "outro" });
    await m.abrir(o, { tipo: "duplicado" });
    await m.abrir(m.onboarding());
    assert.equal(m.repositorio.casos.size, 4);
  });

  it("o caso nasce com motivo interno, motivo publico, evidencias por referencia, recomendacao e prazo", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    const c = r.caso;
    assert.equal(c.motivoInterno, "marcas=nif_divergente;score=0");
    assert.equal(c.motivoPublico, "nao_foi_possivel_validar");
    assert.equal(c.evidencias[0]!.tipo, "kyc_check");
    assert.equal(c.recomendacao, "investigar");
    assert.equal(c.slaDueAt.toISOString(), "2026-11-16T09:00:00.000Z", "sexta 10:00 em Luanda vence segunda 10:00");
  });

  it("um onboarding antes do OTP, ou morto, nao entra", async () => {
    const m = montarRevisao();
    for (const fase of ["registo", "otp_pendente", "rejeitado", "abandonado", "cancelado"]) {
      const r = await m.abrir(m.onboarding({ fase }));
      assert.deepEqual(r, { estado: "nao_elegivel", fase });
    }
    assert.equal(m.repositorio.casos.size, 0);
  });

  it("um tenant que nao e o do onboarding nao entra", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.servico.abrir({
      tipo: "kyc", tenantId: randomUUID(), onboardingId: o.id, motivoCodigo: "kyc_k1", motivoInterno: "x",
      motivoPublico: "nao_foi_possivel_validar", evidencias: [], recomendacao: null, prioridade: 5,
    });
    assert.equal(r.estado, "nao_elegivel");
  });

  it("tipo, motivo publico e prioridade fora das listas recusam antes de gravar", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const base = { tenantId: o.tenantId, onboardingId: o.id, motivoCodigo: "k", motivoInterno: "x", evidencias: [], recomendacao: null };
    await assert.rejects(m.servico.abrir({ ...base, tipo: "fraude" as never, motivoPublico: "nao_foi_possivel_validar", prioridade: 5 }), RangeError);
    await assert.rejects(m.servico.abrir({ ...base, tipo: "kyc", motivoPublico: "nif_divergente" as never, prioridade: 5 }), RangeError);
    await assert.rejects(m.servico.abrir({ ...base, tipo: "kyc", motivoPublico: "nao_foi_possivel_validar", prioridade: 0 }), RangeError);
    assert.equal(m.repositorio.casos.size, 0);
  });
});

// ------------------------------------------------------------ com o KYC real

const ANEL = [new Uint8Array(32).fill(3)];
const TIPOS: readonly TipoDeDocumento[] = ["nif", "alvara", "bi", "banco"];
const CONJUNTO = gerarConjunto();
const ADULTERADO = CONJUNTO.find((c) => c.classe === "nif_alterado")!;
const GENUINO = CONJUNTO.find((c) => c.classe === "genuino")!;

function montarComKyc() {
  const m = montarRevisao({ agora: HOJE });
  const relogio = () => m.agora();
  const verificacoes = new VerificacoesEmMemoria(relogio);
  const casos = new CasosEmMemoria(verificacoes, relogio);
  const sto = criarStorageFake({ agora: relogio });
  // A ponte entre os casos do KYC e a porta da fila: o mesmo caso, lido pelos dois.
  const ponte: OnboardingsDaRevisao = {
    async porId(id) {
      const c = await casos.porId(id);
      if (c === null) return null;
      return { id: c.id, tenantId: c.tenantId, fase: c.fase, redeHmac: "aa", dispositivoHmac: null, nifHmac: c.nifHmac, telefoneHmac: "bb" };
    },
    async porTenant() {
      return null;
    },
    async marcarFase(id, fase) {
      const c = casos.casos.get(id);
      if (c === undefined) return false;
      casos.casos.set(id, { ...c, fase });
      return true;
    },
  };
  const servico = new ServicoDeRevisao({
    repositorio: m.repositorio,
    onboardings: ponte,
    auditoria: m.auditoria,
    aviso: { avisar: async (p) => void m.avisos.push({ ...p }) },
    alerta: () => {},
    cifra: new CifraAesGcm(randomBytes(32)),
    dados: { ler: async () => null },
    documentos: {
      url: (rev, onboardingId, verificacaoId, aud) => kyc.urlParaRevisao(rev, onboardingId, verificacaoId, aud),
    },
    screening: { gravar: async () => {} },
    relogio,
  });
  const kyc: ServicoKyc = new ServicoKyc({
    verificacoes,
    casos,
    armazem: sto.storage,
    antivirus: { verificar: async () => ({ limpo: true }) as const },
    rasterizador: new RasterizadorLocal(null),
    ocr: new OcrLocal(new MotorDeGrelha()),
    cifra: new CifraAesGcm(randomBytes(32)),
    fila: filaDoKyc(servico, ponte, verificacoes),
    anelDoNif: ANEL,
    relogio,
  });
  const carregar = async (c: typeof GENUINO) => {
    casos.juntar({ id: c.id, tenantId: c.tenantId, fase: "kyc_pendente", nifHmac: nifHmac(c.nifDeclarado, ANEL), nomeNegocio: "negocio", categoriaDeclarada: c.categoria });
    for (const t of TIPOS) await kyc.receber(c.id, t, c.documentos[t]);
  };
  return { ...m, servico, kyc, casos, verificacoes, sto, carregar };
}

describe("a partir do KYC (KAM-087): abertura, decisao e recurso", () => {
  it("um adulterado abre um caso kyc com os quatro kyc_check como evidencia, prioridade 1, e o onboarding em em_revisao", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    assert.ok(caso);
    assert.equal(m.repositorio.casos.size, 1);
    assert.equal(caso.tipo, "kyc");
    assert.equal(caso.motivoCodigo, "kyc_k1");
    assert.equal(caso.prioridade, 1);
    assert.match(caso.motivoInterno, /nif_divergente/);
    assert.equal(caso.motivoPublico, "nao_foi_possivel_validar");
    assert.deepEqual(caso.evidencias.map((e) => e.ref).sort(), m.verificacoes.linhas.map((v) => v.id).sort());
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "em_revisao");
  });

  it("reentregar o mesmo envio do KYC nao cria segundo caso", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const fila = filaDoKyc(m.servico, { porId: async () => ({ id: ADULTERADO.id, tenantId: ADULTERADO.tenantId, fase: "em_revisao", redeHmac: null, dispositivoHmac: null, nifHmac: "", telefoneHmac: "" }), porTenant: async () => null, marcarFase: async () => true }, m.verificacoes);
    for (let i = 0; i < 3; i++) await fila.enviar({ onboardingId: ADULTERADO.id, score: 40, marcas: ["nif_divergente"], recomendacao: "investigar" });
    assert.equal(m.repositorio.casos.size, 1);
  });

  it("aprovar com dois revisores desbloqueia: o onboarding passa a aprovado (para o KAM-092)", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    const a = revisor();
    const b = revisor();
    const r1 = await m.servico.decidir(a, caso!.id, "aprovar", { regra: "documentos_conferidos" });
    assert.equal(r1.estado, "aguarda_segundo_revisor");
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "em_revisao", "um so revisor nao desbloqueia risco alto");
    const r2 = await m.servico.decidir(b, caso!.id, "aprovar", { regra: "documentos_conferidos", nota: "conferido o original" });
    assert.equal(r2.estado, "decidido");
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "aprovado");
    const log = await m.repositorio.decisoes(caso!.id);
    assert.deepEqual(log.map((x) => [x.revisorId, x.decisao, x.regra]), [[a.id, "aprovar", "documentos_conferidos"], [b.id, "aprovar", "documentos_conferidos"]]);
    assert.ok(log[1]!.notaCifrada !== null && !Buffer.from(log[1]!.notaCifrada).includes(Buffer.from("conferido")), "a nota vai cifrada");
    assert.deepEqual(m.avisos.at(-1), { onboardingId: ADULTERADO.id, via: "sms", aviso: "aprovado", motivoPublico: null });
  });

  it("pedir_info devolve o onboarding a kyc_pendente; o KYC volta a decidir e cai no mesmo caso, que continua aberto", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    await m.servico.decidir(revisor(), caso!.id, "pedir_info", { regra: "nif_ilegivel_no_cartao" });
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "kyc_pendente");
    assert.equal(m.repositorio.casos.get(caso!.id)!.estado, "em_analise");
    assert.deepEqual(m.avisos.at(-1), { onboardingId: ADULTERADO.id, via: "sms", aviso: "pedir_info", motivoPublico: "informacao_em_falta" });
    // O dono recarrega um documento; o KYC volta a mandar à fila.
    await m.kyc.receber(ADULTERADO.id, "nif", GENUINO.documentos.nif);
    await m.kyc.decidir(ADULTERADO.id);
    assert.equal(m.repositorio.casos.size, 1);
    assert.equal(m.repositorio.casos.get(caso!.id)!.estado, "em_analise", "o caso continua pendente: so um humano o fecha");
  });

  it("rejeitar poe o onboarding em rejeitado e avisa o dono com o motivo publico generico", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    const r = await m.servico.decidir(revisor(), caso!.id, "rejeitar", { regra: "nif_divergente_confirmado" });
    assert.equal(r.estado, "decidido");
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "rejeitado");
    assert.deepEqual(m.avisos.at(-1), { onboardingId: ADULTERADO.id, via: "sms", aviso: "rejeitado", motivoPublico: "nao_foi_possivel_validar" });
  });

  it("recurso: um, decidido por outro revisor, que pode reverter", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    const a = revisor();
    await m.servico.decidir(a, caso!.id, "rejeitar");
    await m.servico.abrirRecurso(caso!.id);
    await recusa(m.servico.decidirRecurso(a, caso!.id, "aprovar"), "revisor_da_primeira_instancia");
    const b = revisor();
    const c = revisor();
    assert.equal((await m.servico.decidirRecurso(b, caso!.id, "aprovar")).estado, "aguarda_segundo_revisor");
    assert.equal((await m.servico.decidirRecurso(c, caso!.id, "aprovar")).estado, "decidido");
    assert.equal(m.repositorio.casos.get(caso!.id)!.estado, "decidido_final");
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "aprovado", "o recurso aprovado tira o onboarding de rejeitado");
    await assert.rejects(m.servico.abrirRecurso(caso!.id), (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === "recurso_ja_usado");
    assert.deepEqual(m.avisos.at(-1)!.aviso, "recurso_decidido");
  });

  it("a URL do documento vem do KYC, vale 300 s, e o acesso fica no audit_log antes de ela existir", async () => {
    const m = montarComKyc();
    await m.carregar(ADULTERADO);
    await m.kyc.decidir(ADULTERADO.id);
    const [caso] = [...m.repositorio.casos.values()];
    const r = revisor();
    const v = m.verificacoes.linhas[0]!;
    const url = await m.servico.urlDoDocumento(r, caso!.id, v.id);
    assert.deepEqual(m.auditoria.linhas.at(-1), { accao: "review.acesso", tenantId: ADULTERADO.tenantId, actorId: r.id, entidade: "kyc_check", entidadeId: v.id, detalhe: "documento" });
    assert.equal((await m.sto.buscar(url)).estado, 200);
    m.avancar(300_000);
    assert.equal((await m.sto.buscar(url)).estado, 403, "aos 300 s a URL expirou e devolve 403");
  });
});

// ------------------------------------------------------ decisoes e papeis

describe("quem decide (criterio 3 e 6)", () => {
  it("sem papel, ou sem MFA, nao le nem decide; a recusa fica no audit_log", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    const sem = revisor({ papeis: ["suporte_t1"] });
    await recusa(m.servico.ver(sem, r.caso.id), "sem_papel");
    await recusa(m.servico.decidir(sem, r.caso.id, "aprovar"), "sem_papel");
    await recusa(m.servico.listar(sem), "sem_papel");
    await recusa(m.servico.decidir(revisor({ mfa: false }), r.caso.id, "rejeitar"), "sem_mfa");
    assert.deepEqual(m.auditoria.linhas.map((x) => [x.accao, x.detalhe]), [["review.recusa", "sem_papel"], ["review.recusa", "sem_papel"], ["review.recusa", "sem_papel"], ["review.recusa", "sem_mfa"]]);
    assert.equal(m.repositorio.registo.length, 0);
    assert.equal(m.repositorio.casos.get(r.caso.id)!.estado, "aberto", "uma leitura recusada nao mexe no estado");
  });

  it("um caso de prioridade normal aprova-se com um revisor", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.abrir(o, { prioridade: 5 });
    assert.ok(r.estado === "aberto");
    assert.equal((await m.servico.decidir(revisor(), r.caso.id, "aprovar")).estado, "decidido");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
  });

  it("risco alto: o mesmo revisor duas vezes recusa, e um pedir_info no meio recomeca a contagem", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding(), { prioridade: 2 });
    assert.ok(r.estado === "aberto");
    const a = revisor();
    const b = revisor();
    await m.servico.decidir(a, r.caso.id, "aprovar");
    await recusa(m.servico.decidir(a, r.caso.id, "aprovar"), "mesmo_revisor");
    await m.servico.decidir(b, r.caso.id, "pedir_info");
    assert.equal((await m.servico.decidir(b, r.caso.id, "aprovar")).estado, "aguarda_segundo_revisor");
    assert.equal((await m.servico.decidir(a, r.caso.id, "aprovar")).estado, "decidido");
  });

  it("a prioridade 3 ja nao e risco alto (o limiar e 2, proposta)", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding(), { prioridade: 3 });
    assert.ok(r.estado === "aberto");
    assert.equal((await m.servico.decidir(revisor(), r.caso.id, "aprovar")).estado, "decidido");
  });

  it("escalado so o ts_lider decide", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "escalar", { regra: "duvida_juridica" });
    assert.equal(m.repositorio.casos.get(r.caso.id)!.estado, "escalado");
    await recusa(m.servico.decidir(revisor(), r.caso.id, "rejeitar"), "so_lider");
    await recusa(m.servico.decidir(revisor({ papeis: ["ts_lider"] }), r.caso.id, "escalar"), "estado_invalido");
    assert.equal((await m.servico.decidir(revisor({ papeis: ["ts_lider"] }), r.caso.id, "rejeitar")).estado, "decidido");
  });

  it("um caso decidido nao se decide outra vez; um recurso so de aprovar ou rejeitar", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "rejeitar");
    await recusa(m.servico.decidir(revisor(), r.caso.id, "aprovar"), "estado_invalido");
    await recusa(m.servico.decidirRecurso(revisor(), r.caso.id, "aprovar"), "estado_invalido");
    await m.servico.abrirRecurso(r.caso.id);
    await recusa(m.servico.decidirRecurso(revisor(), r.caso.id, "escalar"), "decisao_invalida");
    await recusa(m.servico.decidirRecurso(revisor(), r.caso.id, "pedir_info"), "decisao_invalida");
  });

  it("um motivo publico fora da lista recusa a decisao, e nada fica no registo", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    await recusa(m.servico.decidir(revisor(), r.caso.id, "rejeitar", { motivoPublico: "score 45 por nif" as never }), "decisao_invalida");
    assert.equal(m.repositorio.registo.length, 0);
  });

  it("uma aprovacao de categoria nao aprova o onboarding enquanto o caso kyc estiver pendente", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const k = await m.abrir(o, { tipo: "kyc" });
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:x" });
    assert.ok(k.estado === "aberto" && c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "em_revisao");
    await m.servico.decidir(revisor(), k.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
  });

  it("uma categoria aprovada com o K1 ainda por decidir (kyc_pendente) nao aprova o onboarding", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "kyc_pendente" });
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:x" });
    assert.ok(c.estado === "aberto");
    await m.servico.decidir(revisor(), c.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "kyc_pendente");
  });

  it("es_falhado, saga e trust nao mexem na fase do onboarding", async () => {
    // KAM-097: o efeito de um caso `trust` e de T&S, e rejeita-lo pede a regra.
    const trust: string[] = [];
    const m = montarRevisao({ trust: { aplicarDecisao: async (d) => void trust.push(d.caso.tipo) } });
    const o = m.onboarding({ fase: "aguarda_es" });
    for (const tipo of ["es_falhado", "saga", "trust"] as const) {
      const r = await m.abrir(o, { tipo, motivoCodigo: tipo });
      assert.ok(r.estado === "aberto");
      await m.servico.decidir(revisor(), r.caso.id, "rejeitar", { regra: "r" });
    }
    assert.deepEqual(trust, ["trust"]);
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aguarda_es");
    assert.equal(m.onboardings.fases.length, 0);
  });
});

// ---------------------------------------------------------- dados pessoais

describe("acesso minimo a dados pessoais (criterio 6)", () => {
  it("ver mostra o NIF, o BI e o telefone mascarados, e passa o caso a em_analise", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    m.dados.set(o.id, { nif: "5417038261", numero_bi: "004512345LA041", telefone: "923456789" });
    const r = await m.abrir(o);
    assert.ok(r.estado === "aberto");
    const v = await m.servico.ver(revisor(), r.caso.id);
    assert.deepEqual(v.dados, { nif: "*******261", numero_bi: "***********041", telefone: "******789" });
    assert.equal(v.estado, "em_analise");
    assert.ok(!JSON.stringify(v).includes("5417038261"));
  });

  it("revelar devolve o valor e regista o acesso antes de o devolver", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    m.dados.set(o.id, { nif: "5417038261" });
    const r = await m.abrir(o);
    assert.ok(r.estado === "aberto");
    const rev = revisor();
    assert.equal(await m.servico.revelar(rev, r.caso.id, "nif"), "5417038261");
    assert.deepEqual(m.auditoria.linhas, [{ accao: "review.acesso", tenantId: o.tenantId, actorId: rev.id, entidade: "onboarding_case", entidadeId: o.id, detalhe: "revelar:nif" }]);
  });

  it("um revelar com a auditoria em baixo nao devolve o valor", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    m.dados.set(o.id, { nif: "5417038261" });
    const r = await m.abrir(o);
    assert.ok(r.estado === "aberto");
    m.auditoria.gravar = async () => {
      throw new Error("audit_log fora");
    };
    await assert.rejects(m.servico.revelar(revisor(), r.caso.id, "nif"), /audit_log fora/);
  });

  it("o documento de outro caso nao se pede pelo identificador", async () => {
    const m = montarRevisao();
    const a = await m.abrir(m.onboarding());
    const b = await m.abrir(m.onboarding());
    assert.ok(a.estado === "aberto" && b.estado === "aberto");
    await recusa(m.servico.urlDoDocumento(revisor(), a.caso.id, b.caso.evidencias[0]!.ref), "evidencia_alheia");
    assert.equal(m.urls.length, 0);
    assert.equal(m.auditoria.linhas.at(-1)!.detalhe, "evidencia_alheia");
  });

  it("cada visualizacao gera um registo: tres pedidos, tres linhas", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    const ref = r.caso.evidencias[0]!.ref;
    for (let i = 0; i < 3; i++) await m.servico.urlDoDocumento(revisor(), r.caso.id, ref);
    assert.equal(m.auditoria.linhas.filter((x) => x.accao === "review.acesso" && x.entidade === "kyc_check").length, 3);
  });

  it("a lista nao tem dados pessoais e tem pagina maxima: 60 casos dao 50 e 10, sem exportacao", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 1000 } });
    for (let i = 0; i < 60; i++) {
      const o = m.onboarding();
      m.dados.set(o.id, { nif: `54170382${String(i).padStart(2, "0")}` });
      await m.abrir(o, { prioridade: 1 + (i % 9) });
    }
    const p0 = await m.servico.listar(revisor());
    const p1 = await m.servico.listar(revisor(), {}, 1);
    assert.equal(p0.length, 50);
    assert.equal(p1.length, 10);
    assert.deepEqual(Object.keys(p0[0]!).sort(), ["estado", "id", "motivoCodigo", "prioridade", "slaDueAt", "tipo"]);
    assert.ok(p0.every((x, i) => i === 0 || p0[i - 1]!.prioridade <= x.prioridade), "por prioridade");
    assert.ok(!JSON.stringify([...p0, ...p1]).includes("5417038"));
    assert.equal(typeof (m.servico as unknown as Record<string, unknown>)["exportar"], "undefined");
  });
});

// ------------------------------------------------------------- SLA e lote

describe("SLA, alerta e amostragem (criterio 2 e 7)", () => {
  it("o alerta dos 80% sai uma vez, e so para casos pendentes", async () => {
    const m = montarRevisao();
    const a = await m.abrir(m.onboarding());
    const b = await m.abrir(m.onboarding());
    assert.ok(a.estado === "aberto" && b.estado === "aberto");
    await m.servico.decidir(revisor(), b.caso.id, "rejeitar");
    m.definir(new Date(a.caso.slaAlertaAt.getTime() - 1));
    assert.equal(await m.servico.alertarSla(), 0);
    m.definir(a.caso.slaAlertaAt);
    assert.equal(await m.servico.alertarSla(), 1);
    assert.equal(await m.servico.alertarSla(), 0);
    assert.deepEqual(m.alertas, [{ motivo: "sla_80", casoId: a.caso.id, tipo: "kyc" }]);
  });

  it("o recurso tem prazo novo, contado da abertura do recurso, e a entrada na fila fica", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "rejeitar");
    m.avancar(3 * 24 * H);
    const rec = await m.servico.abrirRecurso(r.caso.id);
    assert.ok(rec.slaDueAt.getTime() > r.caso.slaDueAt.getTime());
    assert.equal(rec.filaEm.getTime(), r.caso.filaEm.getTime(), "a primeira decisao mede-se da entrada");
    assert.equal(rec.slaAlertadoEm, null);
  });

  it("amostragem: perto de 20% de 500 aprovacoes nas primeiras 8 semanas, prioridade 9; nenhuma depois", async () => {
    const m = montarRevisao({ inicioDaAmostragem: SEXTA });
    let n = 0;
    for (let i = 0; i < 500; i++) {
      const r = await m.servico.amostrar(randomUUID(), randomUUID());
      if (r !== null && r.estado === "aberto") {
        n++;
        assert.equal(r.caso.tipo, "auditoria");
        assert.equal(r.caso.prioridade, 9);
      }
    }
    assert.ok(n > 60 && n < 140, `${n} de 500`);
    m.avancar(8 * 7 * 24 * H);
    for (let i = 0; i < 100; i++) assert.equal(await m.servico.amostrar(randomUUID(), randomUUID()), null);
  });

  it("amostrar a mesma aprovacao duas vezes nao abre dois casos", async () => {
    const m = montarRevisao({ inicioDaAmostragem: SEXTA, limiares: { fracaoDaAmostra: 1 } });
    const id = randomUUID();
    const t = randomUUID();
    await m.servico.amostrar(id, t);
    await m.servico.amostrar(id, t);
    assert.equal(m.repositorio.casos.size, 1);
  });

  it("sem inicio da amostragem, nao se amostra", async () => {
    const m = montarRevisao({ limiares: { fracaoDaAmostra: 1 } });
    assert.equal(await m.servico.amostrar(randomUUID(), randomUUID()), null);
  });
});

// ------------------------------------------------- guia e screening (088)

describe("as outras portas de entrada", () => {
  it("o guia do ES abre es_falhado uma vez por onboarding, com o motivo no interno", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "aguarda_es" });
    const fila = filaDoGuia(m.servico, m.onboardings);
    await fila.abrir(o.id, "es_falhado", "numero_divergente");
    await fila.abrir(o.id, "es_falhado", "numero_divergente");
    const [caso] = [...m.repositorio.casos.values()];
    assert.equal(m.repositorio.casos.size, 1);
    assert.equal(caso!.tipo, "es_falhado");
    assert.equal(caso!.motivoInterno, "motivo=numero_divergente");
  });

  it("uma porta que nao consegue abrir falha fechada", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "otp_pendente" });
    await assert.rejects(filaDoGuia(m.servico, m.onboardings).abrir(o.id, "es_falhado", "numero_divergente"), CasoNaoElegivelError);
    await assert.rejects(filaDoGuia(m.servico, m.onboardings).abrir(randomUUID(), "es_falhado", "numero_divergente"), CasoNaoElegivelError);
  });

  it("uma condicional de categoria abre caso; aprovar grava a decisao humana permitida que o assertPublishable le", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ fase: "kyc_pendente" });
    const linhas: LinhaDeDecisao[] = [];
    const base = { gravar: async (l: LinhaDeDecisao) => void linhas.push(l) };
    const servico = new ServicoDeRevisao({
      repositorio: m.repositorio,
      onboardings: m.onboardings,
      auditoria: m.auditoria,
      aviso: { avisar: async () => {} },
      alerta: () => {},
      cifra: new CifraAesGcm(randomBytes(32)),
      dados: { ler: async () => null },
      documentos: { url: async () => "" },
      screening: decisaoHumanaDeScreening(base),
      relogio: () => SEXTA,
    });
    const escritor = escritorComFila(base, servico);
    const sha = new Uint8Array(32).fill(7);
    const linha: LinhaDeDecisao = {
      tenantId: o.tenantId, onboardingId: o.id, sujeitoTipo: "produto", sujeitoRef: "sku-1", decisao: "condicional",
      regras: ["armas_brancas"], versaoPolitica: "1.0.0+m.2", origem: "regra", conteudoSha256: sha,
    };
    await escritor.gravar(linha);
    await escritor.gravar(linha);
    await escritor.gravar({ ...linha, decisao: "permitida", sujeitoRef: "sku-2" });
    assert.equal(m.repositorio.casos.size, 1, "uma condicional, uma vez; a permitida nao abre");
    const [caso] = [...m.repositorio.casos.values()];
    assert.equal(caso!.tipo, "catalogo");
    assert.equal(caso!.motivoPublico, "categoria_nao_permitida");
    await servico.decidir(revisor(), caso!.id, "aprovar");
    const humana = linhas.at(-1)!;
    assert.equal(humana.origem, "humano");
    assert.equal(humana.decisao, "permitida");
    assert.deepEqual([...humana.conteudoSha256], [...sha]);
    assert.equal(m.repositorio.casos.size, 1, "a linha humana nao abre caso");
    // O `assertPublishable` do KAM-088, sobre as linhas gravadas: a humana vale.
    const leitor = { decisoes: async () => linhas.filter((l) => l.sujeitoRef === "sku-1").map((l) => ({ decisao: l.decisao, origem: l.origem })) };
    const politica = { versao: "1.0.0+m.2" } as Parameters<typeof assertPublishable>[1]["politica"];
    await assertPublishable({ tenantId: o.tenantId, ref: "sku-1", entrada: { categoria_declarada: "x", textos: [] } }, { politica, leitor });
  });

  it("rejeitar um caso de catalogo grava bloqueada humana", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.abrir(o, {
      tipo: "catalogo",
      motivoCodigo: "screening:y",
      evidencias: [{ tipo: "screening_decision", ref: JSON.stringify({ sujeitoTipo: "produto", sujeitoRef: "s", versaoPolitica: "1.0.0+m.2", conteudoSha256: "ab".repeat(32) }) }],
    });
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "rejeitar");
    assert.equal(m.humanas.length, 1);
    assert.equal(m.humanas[0]!.decisao, "bloqueada");
  });

  it("a prioridade do KYC: regra dura 1, score alto 2, o resto 5", () => {
    assert.equal(prioridadeDoKyc(["alvara_expirado"], 0), 1);
    assert.equal(prioridadeDoKyc(["nome_titular_divergente", "actividade_incoerente"], 70), 2);
    assert.equal(prioridadeDoKyc(["confianca_baixa"], 25), 5);
    assert.equal(prioridadeDoKyc(["visao_recusada"], 0), 5);
  });
});

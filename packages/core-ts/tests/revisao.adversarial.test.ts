/**
 * A suite adversarial da fila de revisão (KAM-089), à letra do bloco:
 *
 * ```text
 * (a) 500 registos de lixo (OTP falhado, documentos ilegíveis, duplicados
 *     exactos) ⇒ 0 casos na fila
 * (b) 200 registos válidos de uma só origem num dia ⇒ a fila cresce ≤ quota e
 *     o excesso fica em_triagem_automatica com aviso
 * (c) revisor tenta aprovar o próprio caso ⇒ recusado e registado
 * (d) o motivo público nunca revela a heurística em 20 rejeições simuladas
 * ```
 *
 * O (a) corre pelas **portas reais** de quem alimenta a fila: os registos com o
 * OTP por validar batem nas três entradas (KYC, guia, screening); os ilegíveis
 * e os duplicados exactos correm pelo `ServicoKyc` verdadeiro do KAM-087, com a
 * porta dele ligada à fila. Um caso aberto por qualquer deles é um vermelho.
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
  avaliar,
  type Marca,
} from "../src/kyc/index.ts";
import { criarStorageFake } from "../src/storage/index.ts";
import {
  CasoNaoElegivelError,
  MOTIVOS_PUBLICOS,
  RevisaoRecusadaError,
  TEXTO_DO_MOTIVO_PUBLICO,
  escritorComFila,
  filaDoGuia,
  filaDoKyc,
  type OnboardingsDaRevisao,
} from "../src/revisao/index.ts";

import { HOJE, MotorDeGrelha, desenhar, nifHmac } from "./apoio/kyc-sintetico.ts";
import { montarRevisao, revisor } from "./apoio/revisao.ts";

const ANEL = [new Uint8Array(32).fill(3)];

describe("(a) 500 registos de lixo nao chegam a humano", () => {
  it("250 com OTP por validar, 150 ilegiveis e 100 duplicados exactos: zero casos", async () => {
    const m = montarRevisao({ agora: HOJE });
    const relogio = () => m.agora();
    const verificacoes = new VerificacoesEmMemoria(relogio);
    const casos = new CasosEmMemoria(verificacoes, relogio);
    const ponte: OnboardingsDaRevisao = {
      async porId(id) {
        const c = await casos.porId(id);
        return c === null ? null : { id, tenantId: c.tenantId, fase: c.fase, redeHmac: "aa", dispositivoHmac: null, nifHmac: c.nifHmac, telefoneHmac: "bb" };
      },
      marcarFase: async () => true,
    };
    const kyc = new ServicoKyc({
      verificacoes,
      casos,
      armazem: criarStorageFake({ agora: relogio }).storage,
      antivirus: { verificar: async () => ({ limpo: true }) as const },
      rasterizador: new RasterizadorLocal(null),
      ocr: new OcrLocal(new MotorDeGrelha()),
      cifra: new CifraAesGcm(randomBytes(32)),
      fila: filaDoKyc(m.servico, ponte, verificacoes),
      anelDoNif: ANEL,
      relogio,
    });
    const juntar = (fase: string) => {
      const id = randomUUID();
      casos.juntar({ id, tenantId: randomUUID(), fase, nifHmac: nifHmac("5417038261", ANEL), nomeNegocio: "n", categoriaDeclarada: "moda" });
      return id;
    };
    const ilegivel = (semente: number) => desenhar({ linhas: ["BILHETE DE IDENTIDADE"], fundo: semente, ruido: 0, semente });

    // 250 com o OTP por validar: cada um tenta as tres portas.
    let recusados = 0;
    for (let i = 0; i < 250; i++) {
      const id = juntar(i % 2 === 0 ? "registo" : "otp_pendente");
      const tenantId = (await casos.porId(id))!.tenantId;
      for (const tentar of [
        () => filaDoKyc(m.servico, ponte, verificacoes).enviar({ onboardingId: id, score: 90, marcas: ["nif_divergente"], recomendacao: "investigar" }),
        () => filaDoGuia(m.servico, ponte).abrir(id, "es_falhado", "numero_divergente"),
        () => escritorComFila({ gravar: async () => {} }, m.servico).gravar({
          tenantId, onboardingId: id, sujeitoTipo: "categoria", sujeitoRef: "moda", decisao: "condicional",
          regras: ["x"], versaoPolitica: "1.0.0+m.2", origem: "regra", conteudoSha256: new Uint8Array(32),
        }),
      ]) {
        await assert.rejects(tentar(), CasoNaoElegivelError);
        recusados++;
      }
    }
    assert.equal(recusados, 750);

    // 150 ilegiveis: tres documentos ilegiveis de seguida, e o KYC rejeita sem humano.
    for (let i = 0; i < 150; i++) {
      const id = juntar("kyc_pendente");
      const fim = [];
      for (let k = 1; k <= 3; k++) fim.push(await kyc.receber(id, "bi", ilegivel(i * 10 + k)));
      assert.equal(fim.at(-1)!.estado, "rejeitado");
    }

    // 100 duplicados exactos: o mesmo ficheiro ilegivel reenviado; o KYC nao o conta duas vezes.
    for (let i = 0; i < 100; i++) {
      const id = juntar("kyc_pendente");
      const f = ilegivel(9000 + i);
      for (let k = 0; k < 4; k++) assert.equal((await kyc.receber(id, "bi", f)).estado, "novo_carregamento");
      assert.equal((await kyc.decidir(id)).estado, "incompleto");
    }

    assert.equal(m.repositorio.casos.size, 0, "nenhum caso chegou a fila");
    assert.equal(m.alertas.length, 0);
  });
});

describe("(b) 200 registos validos de uma so origem num dia", () => {
  it("a fila cresce ate a quota (20) e os outros 180 ficam em_triagem_automatica, com aviso", async () => {
    const m = montarRevisao();
    const rede = randomBytes(32).toString("hex");
    const estados: string[] = [];
    for (let i = 0; i < 200; i++) estados.push((await m.abrir(m.onboarding({ redeHmac: rede }))).estado);
    assert.equal(estados.filter((e) => e === "aberto").length, 20);
    assert.equal(estados.filter((e) => e === "em_triagem_automatica").length, 180);
    assert.equal(m.alertas.filter((a) => a.motivo === "quota_da_origem").length, 180);
    // A vista humana so tem os 20.
    const p = [...(await m.servico.listar(revisor())), ...(await m.servico.listar(revisor(), {}, 1))];
    assert.equal(p.length, 20);
  });

  it("outra origem no mesmo dia tem a sua quota; a origem nula partilha a mesma", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 2 } });
    const a = randomBytes(32).toString("hex");
    for (let i = 0; i < 3; i++) await m.abrir(m.onboarding({ redeHmac: a }));
    const outra = await m.abrir(m.onboarding({ redeHmac: randomBytes(32).toString("hex") }));
    assert.equal(outra.estado, "aberto");
    const nulos = [];
    for (let i = 0; i < 3; i++) nulos.push((await m.abrir(m.onboarding({ redeHmac: null, dispositivoHmac: null }))).estado);
    assert.deepEqual(nulos, ["aberto", "aberto", "em_triagem_automatica"]);
  });

  it("sem prefixo de IP, a origem e o dispositivo", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 1 } });
    const d = randomBytes(32).toString("hex");
    const r = [];
    for (let i = 0; i < 2; i++) r.push((await m.abrir(m.onboarding({ redeHmac: null, dispositivoHmac: d }))).estado);
    assert.deepEqual(r, ["aberto", "em_triagem_automatica"]);
  });

  it("reentregar o mesmo caso nao gasta quota", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 1 } });
    const rede = randomBytes(32).toString("hex");
    const o = m.onboarding({ redeHmac: rede });
    for (let i = 0; i < 5; i++) assert.equal((await m.abrir(o)).estado, "aberto");
    assert.equal((await m.abrir(m.onboarding({ redeHmac: rede }))).estado, "em_triagem_automatica");
  });

  it("no dia seguinte, a triagem drena ate a quota do dia, por ordem de chegada, e o prazo conta da entrada", async () => {
    const m = montarRevisao();
    const rede = randomBytes(32).toString("hex");
    for (let i = 0; i < 50; i++) await m.abrir(m.onboarding({ redeHmac: rede }));
    assert.equal(await m.servico.drenarTriagem(), 0, "hoje a quota ja esta gasta");
    m.avancar(24 * 3_600_000);
    assert.equal(await m.servico.drenarTriagem(), 20);
    const entrados = [...m.repositorio.casos.values()].filter((c) => c.estado === "aberto" && c.filaEm.getTime() === m.agora().getTime());
    assert.equal(entrados.length, 20);
    assert.ok(entrados.every((c) => c.slaDueAt.getTime() > m.agora().getTime()));
    assert.equal([...m.repositorio.casos.values()].filter((c) => c.estado === "em_triagem_automatica").length, 10);
  });

  it("a amostragem de auditoria nao conta contra a quota da origem", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 0, fracaoDaAmostra: 1 }, inicioDaAmostragem: new Date("2026-11-01T00:00:00Z") });
    const r = await m.servico.amostrar(randomUUID(), randomUUID());
    assert.equal(r?.estado, "aberto");
  });
});

describe("(c) o revisor que e parte no caso", () => {
  it("o dono do NIF tenta aprovar o proprio caso: recusado, registado, e o caso intacto", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.abrir(o, { prioridade: 5 });
    assert.ok(r.estado === "aberto");
    const intruso = revisor({ papeis: ["ts_lider"], nifHmac: o.nifHmac });
    await assert.rejects(m.servico.decidir(intruso, r.caso.id, "aprovar"), (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === "parte_no_caso" && e.estadoHttp === 403);
    assert.deepEqual(m.auditoria.linhas, [{ accao: "review.recusa", tenantId: o.tenantId, actorId: intruso.id, entidade: "review_case", entidadeId: r.caso.id, detalhe: "parte_no_caso" }]);
    assert.equal(m.repositorio.registo.length, 0);
    assert.equal(m.repositorio.casos.get(r.caso.id)!.estado, "aberto");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "em_revisao");
  });

  it("pelo telefone tambem, e nem ver o caso pode", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.abrir(o);
    assert.ok(r.estado === "aberto");
    const intruso = revisor({ telefoneHmac: o.telefoneHmac });
    await assert.rejects(m.servico.ver(intruso, r.caso.id), (e: unknown) => e instanceof RevisaoRecusadaError && e.motivo === "parte_no_caso");
    await assert.rejects(m.servico.urlDoDocumento(intruso, r.caso.id, r.caso.evidencias[0]!.ref), RevisaoRecusadaError);
    assert.equal(m.urls.length, 0);
  });

  it("um revisor com HMAC nulo nao e parte de tudo: o nulo nao casa com nada", async () => {
    const m = montarRevisao();
    const r = await m.abrir(m.onboarding());
    assert.ok(r.estado === "aberto");
    assert.equal((await m.servico.decidir(revisor(), r.caso.id, "aprovar")).estado, "decidido");
  });
});

describe("(d) o motivo publico nao revela a heuristica", () => {
  const MARCAS: readonly (readonly Marca[])[] = [
    ["nif_divergente"], ["imagem_reutilizada"], ["software_de_edicao"], ["iban_invalido"], ["alvara_expirado"],
    ["nome_titular_divergente"], ["confianca_baixa"], ["actividade_incoerente"], ["visao_recusada"], ["orcamento_excedido"],
    ["nif_divergente", "imagem_reutilizada"], ["alvara_expirado", "nome_titular_divergente"], ["confianca_baixa", "actividade_incoerente"],
    ["software_de_edicao", "iban_invalido"], ["nome_titular_divergente", "confianca_baixa", "actividade_incoerente"],
    ["imagem_reutilizada", "visao_recusada"], ["orcamento_excedido", "confianca_baixa"], ["nif_divergente", "alvara_expirado"],
    ["iban_invalido", "nome_titular_divergente"], ["actividade_incoerente"],
  ];

  it("20 rejeicoes pelo caminho do KYC: o que o dono le e um dos quatro textos fixos, e nenhum diz a regra, o score ou o limiar", async () => {
    assert.equal(MARCAS.length, 20);
    const m = montarRevisao();
    const proibido = [
      ...MARCAS.flat().map((x) => x.replaceAll("_", " ")),
      ...MARCAS.flat(),
      "score", "hamming", "phash", "limiar", "regra", "pontos", "exif", "mod-97", "ocr", "llm", "%",
    ];
    for (const marcas of MARCAS) {
      const o = m.onboarding({ fase: "kyc_pendente" });
      await filaDoKyc(m.servico, m.onboardings, { doCaso: async () => [] }).enviar({ onboardingId: o.id, score: 85, marcas, recomendacao: "investigar" });
      const caso = [...m.repositorio.casos.values()].find((c) => c.onboardingId === o.id)!;
      const rev = [revisor(), revisor()];
      await m.servico.decidir(rev[0]!, caso.id, "rejeitar", { regra: marcas.join("+"), nota: `score 85; ${marcas.join(", ")}` });
    }
    const lidos = m.avisos.filter((a) => a.aviso === "rejeitado");
    assert.equal(lidos.length, 20);
    for (const a of lidos) {
      assert.ok(a.motivoPublico !== null && MOTIVOS_PUBLICOS.includes(a.motivoPublico));
      const texto = TEXTO_DO_MOTIVO_PUBLICO[a.motivoPublico].toLowerCase();
      for (const p of proibido) assert.ok(!texto.includes(p.toLowerCase()), `«${texto}» diz «${p}»`);
      assert.doesNotMatch(texto, /\d/, "nenhum numero");
    }
    // O especifico so quando o unico sinal e o corrigivel.
    assert.equal(lidos.filter((a) => a.motivoPublico === "documento_expirado").length, 1);
  });

  it("a avaliacao do KYC e as marcas nao chegam ao aviso: o aviso nao tem campo para elas", async () => {
    const m = montarRevisao();
    const o = m.onboarding();
    const r = await m.abrir(o);
    assert.ok(r.estado === "aberto");
    await m.servico.decidir(revisor(), r.caso.id, "rejeitar", { nota: "nif_divergente e score 85" });
    assert.deepEqual(Object.keys(m.avisos[0]!).sort(), ["aviso", "motivoPublico", "onboardingId", "via"]);
    assert.ok(!JSON.stringify(m.avisos).includes("nif_divergente"));
    // `avaliar` importado para que o tipo das marcas acompanhe o KYC: uma marca nova la parte este ensaio.
    assert.equal(typeof avaliar, "function");
  });

  it("o aviso nunca vai pelo numero da loja: a via e sms ou email", async () => {
    const m = montarRevisao();
    for (let i = 0; i < 5; i++) {
      const r = await m.abrir(m.onboarding());
      assert.ok(r.estado === "aberto");
      await m.servico.decidir(revisor(), r.caso.id, i % 2 === 0 ? "rejeitar" : "pedir_info");
    }
    assert.ok(m.avisos.length === 5 && m.avisos.every((a) => a.via === "sms" || a.via === "email"));
  });
});

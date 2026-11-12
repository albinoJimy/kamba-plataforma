/**
 * O caso de uso do K1 de ponta a ponta, com duplos (KAM-087).
 *
 * «upload → STO → `OcrProvider` falso → decisão; falha fechada sem `apd_ref`;
 * orçamento esgotado ⇒ fila» — os três ensaios de integração do bloco — mais
 * as recusas do critério 1, a idempotência da DoD 4, o ilegível do critério 6,
 * a URL de revisão e a purga do critério 10.
 *
 * Os documentos são os do conjunto sintético (`./apoio/kyc-sintetico.ts`):
 * PNG verdadeiros, lidos dos píxeis pelo `MotorDeGrelha`.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { describe, it } from "node:test";

import { criarStorageFake, type StorageProvider } from "../src/storage/index.ts";
import {
  CasosEmMemoria,
  CifraAesGcm,
  FilaEmMemoria,
  GATE_QUE_RECUSA,
  OcrDeVisao,
  OcrLocal,
  RasterizadorLocal,
  ServicoKyc,
  TEXTO_DO_MOTIVO,
  VERSAO_DAS_REGRAS,
  VerificacoesEmMemoria,
  codificarPngCinzento,
  type Antivirus,
  type GateDeTransferencia,
  type OcrProvider,
  type Rasterizador,
  type TipoDeDocumento,
  type Transporte,
} from "../src/kyc/index.ts";

import { HOJE, MotorDeGrelha, desenhar, gerarConjunto, nifHmac, type CasoSintetico } from "./apoio/kyc-sintetico.ts";

const ANEL = [new Uint8Array(32).fill(3)];
const TIPOS: readonly TipoDeDocumento[] = ["nif", "alvara", "bi", "banco"];
const CONJUNTO = gerarConjunto();
const GENUINO = CONJUNTO.find((c) => c.classe === "genuino")!;
const OUTRO_GENUINO = CONJUNTO.filter((c) => c.classe === "genuino")[1]!;
const ADULTERADO = CONJUNTO.find((c) => c.classe === "nif_alterado")!;

class AntivirusFalso implements Antivirus {
  chamadas = 0;
  readonly modo: "limpo" | "sujo" | "avaria";
  constructor(modo: "limpo" | "sujo" | "avaria" = "limpo") {
    this.modo = modo;
  }
  async verificar() {
    this.chamadas++;
    if (this.modo === "avaria") throw new Error("clamd fora");
    return this.modo === "limpo" ? ({ limpo: true } as const) : ({ limpo: false, assinatura: "Eicar" } as const);
  }
}

function montar(o: { ocr?: OcrProvider; antivirus?: AntivirusFalso; isolado?: Rasterizador; armazem?: (s: StorageProvider) => StorageProvider; agora?: Date } = {}) {
  let agora = o.agora ?? HOJE;
  const cifra = new CifraAesGcm(randomBytes(32));
  const relogio = () => agora;
  const verificacoes = new VerificacoesEmMemoria(relogio);
  const casos = new CasosEmMemoria(verificacoes, relogio);
  const sto = criarStorageFake({ agora: relogio });
  const fila = new FilaEmMemoria();
  const antivirus = o.antivirus ?? new AntivirusFalso();
  const servico = new ServicoKyc({
    verificacoes,
    casos,
    armazem: o.armazem ? o.armazem(sto.storage) : sto.storage,
    antivirus,
    rasterizador: new RasterizadorLocal(o.isolado ?? null),
    ocr: o.ocr ?? new OcrLocal(new MotorDeGrelha()),
    cifra,
    fila,
    anelDoNif: ANEL,
    relogio,
  });
  const juntar = (c: CasoSintetico) =>
    casos.juntar({
      id: c.id,
      tenantId: c.tenantId,
      fase: "kyc_pendente",
      nifHmac: nifHmac(c.nifDeclarado, ANEL),
      nomeNegocio: "negocio",
      categoriaDeclarada: c.categoria,
    });
  return { servico, verificacoes, casos, sto, fila, antivirus, cifra, juntar, avancar: (ms: number) => (agora = new Date(agora.getTime() + ms)) };
}

async function carregarTodos(m: ReturnType<typeof montar>, c: CasoSintetico) {
  m.juntar(c);
  for (const t of TIPOS) await m.servico.receber(c.id, t, c.documentos[t]);
}

describe("o caminho completo", () => {
  it("quatro documentos genuinos: quatro objectos no STO e k1_ok, sem fila", async () => {
    const m = montar();
    await carregarTodos(m, GENUINO);
    assert.equal(m.sto.total(), 4);
    const d = await m.servico.decidir(GENUINO.id);
    assert.equal(d.estado, "decidido");
    if (d.estado !== "decidido") return;
    assert.equal(d.avaliacao.resultado, "k1_ok");
    assert.equal(d.motivoPublico, null);
    assert.equal(m.fila.pedidos.length, 0);
    for (const v of m.verificacoes.linhas) {
      assert.equal(v.resultado, "k1_ok");
      assert.equal(v.versaoRegras, VERSAO_DAS_REGRAS);
      assert.match(v.docRef, new RegExp(`^t/${GENUINO.tenantId}/kyc_documento/`));
    }
  });

  it("os campos extraidos ficam cifrados: o NIF em claro nao esta na linha", async () => {
    const m = montar();
    await carregarTodos(m, GENUINO);
    for (const v of m.verificacoes.linhas) {
      assert.ok(!Buffer.from(v.extraidoCifrado!).includes(Buffer.from(GENUINO.nifDeclarado)));
    }
  });

  it("incompleto enquanto faltar um tipo", async () => {
    const m = montar();
    m.juntar(GENUINO);
    for (const t of ["nif", "alvara", "bi"] as const) await m.servico.receber(GENUINO.id, t, GENUINO.documentos[t]);
    assert.deepEqual(await m.servico.decidir(GENUINO.id), { estado: "incompleto", faltam: ["banco"] });
  });

  it("um adulterado vai a fila uma vez, com o motivo generico, e decidir de novo nao duplica", async () => {
    const m = montar();
    await carregarTodos(m, ADULTERADO);
    const d = await m.servico.decidir(ADULTERADO.id);
    assert.ok(d.estado === "decidido" && d.avaliacao.resultado === "fila");
    if (d.estado !== "decidido") return;
    assert.ok(d.avaliacao.marcas.includes("nif_divergente"));
    assert.equal(d.motivoPublico, "nao_foi_possivel_validar");
    assert.equal(TEXTO_DO_MOTIVO[d.motivoPublico!], "Não foi possível validar os documentos. A nossa equipa vai analisar o pedido.");
    assert.equal((await m.casos.porId(ADULTERADO.id))!.fase, "em_revisao");
    assert.deepEqual(await m.servico.decidir(ADULTERADO.id), { estado: "fora_de_fase", fase: "em_revisao" });
    assert.equal(m.fila.pedidos.length, 1);
    assert.equal(m.fila.pedidos[0]!.recomendacao, "investigar");
  });
});

describe("as recusas do criterio 1", () => {
  it("formato pelos magic bytes: um GIF e um SVG nao chegam ao antivirus nem ao STO", async () => {
    const m = montar();
    m.juntar(GENUINO);
    for (const b of ["GIF89a....", "<svg xmlns='x'/>"]) {
      assert.deepEqual(await m.servico.receber(GENUINO.id, "bi", new TextEncoder().encode(b)), { estado: "recusado", motivo: "formato" });
    }
    assert.equal(m.antivirus.chamadas, 0);
    assert.equal(m.sto.total(), 0);
  });

  it("acima de 8 MB recusa; exactamente 8 MB passa a fronteira do tamanho", async () => {
    const m = montar();
    m.juntar(GENUINO);
    const grande = new Uint8Array(8 * 1024 * 1024 + 1);
    grande.set([0xff, 0xd8, 0xff]);
    assert.deepEqual(await m.servico.receber(GENUINO.id, "bi", grande), { estado: "recusado", motivo: "tamanho" });
    const limite = grande.subarray(0, 8 * 1024 * 1024);
    const r = await m.servico.receber(GENUINO.id, "bi", limite);
    assert.deepEqual(r, { estado: "recusado", motivo: "formato" }, "passou o tamanho; o JPEG sem processo isolado recusa a seguir");
  });

  it("PDF sem processo isolado: recusado, nunca aberto aqui, e nada no STO", async () => {
    const m = montar();
    m.juntar(GENUINO);
    const r = await m.servico.receber(GENUINO.id, "alvara", new TextEncoder().encode("%PDF-1.7\n%%EOF"));
    assert.deepEqual(r, { estado: "recusado", motivo: "formato" });
    assert.equal(m.sto.total(), 0);
  });

  it("PDF pelo processo isolado: 3 paginas passa, 4 recusa", async () => {
    const pagina = (await import("../src/kyc/png.ts")).descodificarPng(GENUINO.documentos.alvara, 1e7).pagina;
    let paginas = 3;
    const recebidos: Uint8Array[] = [];
    const isolado: Rasterizador = {
      rasterizar: async (bytes) => {
        recebidos.push(bytes);
        return { paginas: Array.from({ length: paginas }, () => pagina), software: [] };
      },
    };
    const m = montar({ isolado });
    m.juntar(GENUINO);
    const pdf = new TextEncoder().encode("%PDF-1.7 tres");
    assert.equal((await m.servico.receber(GENUINO.id, "alvara", pdf)).estado, "lido");
    paginas = 4;
    assert.deepEqual(
      await m.servico.receber(GENUINO.id, "alvara", new TextEncoder().encode("%PDF-1.7 quatro")),
      { estado: "recusado", motivo: "paginas" },
    );
    assert.deepEqual(recebidos[0], pdf, "o PDF vai inteiro ao processo isolado");
  });

  it("antivirus: sujo recusa e nao guarda; avaria lanca e nao guarda nada", async () => {
    const sujo = montar({ antivirus: new AntivirusFalso("sujo") });
    sujo.juntar(GENUINO);
    assert.deepEqual(await sujo.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi), { estado: "recusado", motivo: "antivirus" });
    assert.equal(sujo.sto.total(), 0);
    const avaria = montar({ antivirus: new AntivirusFalso("avaria") });
    avaria.juntar(GENUINO);
    await assert.rejects(avaria.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi));
    assert.equal(avaria.sto.total(), 0);
    assert.equal(avaria.verificacoes.linhas.length, 0);
  });

  it("um caso que nao esta em kyc_pendente nao recebe documentos", async () => {
    const m = montar();
    m.casos.juntar({ id: GENUINO.id, tenantId: GENUINO.tenantId, fase: "otp_pendente", nifHmac: "x", nomeNegocio: "n", categoriaDeclarada: "moda" });
    assert.deepEqual(await m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi), { estado: "recusado", motivo: "caso" });
  });
});

describe("idempotencia por sha256 (DoD 4)", () => {
  it("o mesmo ficheiro duas vezes: uma linha, um objecto, e a segunda diz repetido", async () => {
    const m = montar();
    m.juntar(GENUINO);
    const a = await m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi);
    const b = await m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi);
    assert.ok(a.estado === "lido" && !a.repetido);
    assert.ok(b.estado === "lido" && b.repetido);
    assert.equal(m.verificacoes.linhas.length, 1);
    assert.equal(m.sto.total(), 1);
    assert.equal(m.antivirus.chamadas, 1, "o reenvio nem chega ao antivirus");
  });
});

describe("ilegivel (criterio 6)", () => {
  const ilegivel = (semente: number) => desenhar({ linhas: ["BILHETE DE IDENTIDADE"], fundo: semente, ruido: 0, semente });

  it("dois pedidos de novo carregamento; ao terceiro, rejeicao ilegivel e o caso rejeitado", async () => {
    const m = montar();
    m.juntar(GENUINO);
    const r1 = await m.servico.receber(GENUINO.id, "bi", ilegivel(1));
    const r2 = await m.servico.receber(GENUINO.id, "bi", ilegivel(2));
    const r3 = await m.servico.receber(GENUINO.id, "bi", ilegivel(3));
    assert.ok(r1.estado === "novo_carregamento" && r1.restantes === 2 && r1.motivoPublico === "ilegivel");
    assert.ok(r2.estado === "novo_carregamento" && r2.restantes === 1);
    assert.ok(r3.estado === "rejeitado" && r3.motivoPublico === "ilegivel");
    assert.equal((await m.casos.porId(GENUINO.id))!.fase, "rejeitado");
    assert.deepEqual(await m.servico.receber(GENUINO.id, "nif", GENUINO.documentos.nif), { estado: "recusado", motivo: "caso" });
  });

  it("o mesmo ficheiro ilegivel reenviado nao conta duas vezes", async () => {
    const m = montar();
    m.juntar(GENUINO);
    await m.servico.receber(GENUINO.id, "bi", ilegivel(1));
    await m.servico.receber(GENUINO.id, "bi", ilegivel(1));
    const r = await m.servico.receber(GENUINO.id, "bi", ilegivel(2));
    assert.ok(r.estado === "novo_carregamento" && r.restantes === 1);
  });

  it("os ilegiveis contam por tipo: um de cada tipo nao rejeita", async () => {
    const m = montar();
    m.juntar(GENUINO);
    for (const t of TIPOS) assert.equal((await m.servico.receber(GENUINO.id, t, ilegivel(TIPOS.indexOf(t) + 10))).estado, "novo_carregamento");
  });

  it("depois de um ilegivel, o legivel do mesmo tipo decide", async () => {
    const m = montar();
    m.juntar(GENUINO);
    await m.servico.receber(GENUINO.id, "bi", ilegivel(1));
    for (const t of TIPOS) await m.servico.receber(GENUINO.id, t, GENUINO.documentos[t]);
    const d = await m.servico.decidir(GENUINO.id);
    assert.ok(d.estado === "decidido" && d.avaliacao.resultado === "k1_ok");
  });
});

describe("vision_llm: falha fechada (criterio 2) e orcamento (criterio 9)", () => {
  function visao(gate: GateDeTransferencia, chave: string | null, transporte: Transporte, verificacoes?: () => VerificacoesEmMemoria) {
    return new OcrDeVisao({
      gate,
      transporte,
      urlBase: "http://litellm.interno",
      chaveVirtual: chave,
      fornecedor: "fornecedor_de_visao",
      custoDoCaso: async (id) => (verificacoes ? verificacoes().custoDoCaso(id) : 0),
      tectoPorCasoMicroUsd: 50_000,
      estimativaMicroUsd: 20_000,
    });
  }

  const autorizado = (apdRef: string | null): GateDeTransferencia => ({ decidir: async () => ({ autorizado: true, apdRef }) });

  for (const [nome, gate, chave] of [
    ["sem destino", GATE_QUE_RECUSA, "sk-teste"],
    ["destino sem apd_ref", autorizado(null), "sk-teste"],
    ["destino com apd_ref em branco", autorizado("  "), "sk-teste"],
    ["sem virtual key", autorizado("APD/2026/1"), null],
  ] as const) {
    it(`${nome}: zero chamadas ao LiteLLM e o caso vai a fila`, async () => {
      let chamadas = 0;
      const m = montar({ ocr: visao(gate, chave, async () => { chamadas++; throw new Error("nao devia sair"); }) });
      await carregarTodos(m, GENUINO);
      assert.equal(chamadas, 0);
      assert.ok(m.verificacoes.linhas.every((v) => v.flags.includes("visao_recusada") && v.resultado === "pendente"));
      const d = await m.servico.decidir(GENUINO.id);
      assert.ok(d.estado === "decidido" && d.avaliacao.resultado === "fila");
      assert.equal(m.fila.pedidos.length, 1);
    });
  }

  it("autorizado: o que o modelo devolve passa pela validacao, e o custo acumula ate ao tecto", async () => {
    const pedidos: { url: string; corpo: Record<string, unknown> }[] = [];
    const transporte: Transporte = async (url, p) => {
      pedidos.push({ url, corpo: JSON.parse(p.body) as Record<string, unknown> });
      const campos = { nif: { valor: "nao e um nif", conf: 0.99 }, nome_titular: { valor: "Ana", conf: 0.99 }, aprovado: { valor: "sim", conf: 1 } };
      return {
        status: 200,
        headers: { get: (n: string) => (n === "x-litellm-response-cost" ? "0.03" : null) },
        text: async () => JSON.stringify({ choices: [{ message: { content: JSON.stringify(campos) } }] }),
      };
    };
    let ref: VerificacoesEmMemoria | undefined;
    const m = montar({ ocr: visao(autorizado("APD/2026/1"), "sk-teste", transporte, () => ref!) });
    ref = m.verificacoes;
    m.juntar(GENUINO);
    await m.servico.receber(GENUINO.id, "nif", GENUINO.documentos.nif);
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]!.url, "http://litellm.interno/v1/chat/completions");
    assert.equal(pedidos[0]!.corpo["model"], "kyc-vision");
    const primeira = m.verificacoes.linhas[0]!;
    assert.equal(primeira.custoMicroUsd, 30_000);
    // O NIF que o modelo «leu» nao e um NIF: fica em `invalidos` e nao em
    // `campos` — o `validarCampos` corre sobre a saida do `vision_llm` no
    // caminho do servico, e nao so num ensaio de unidade (achado A4).
    const lido = JSON.parse(new TextDecoder().decode(await m.cifra.decifrar(primeira.extraidoCifrado!, `${GENUINO.id}:nif`))) as {
      campos: Record<string, unknown>;
      invalidos: string[];
    };
    assert.deepEqual(lido.invalidos, ["nif"]);
    assert.deepEqual(Object.keys(lido.campos), ["nome_titular"]);
    assert.ok(!primeira.flags.includes("orcamento_excedido"));
    // 30 000 gastos + 20 000 de estimativa = 50 000: no tecto, ainda passa.
    await m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi);
    assert.equal(pedidos.length, 2);
    assert.ok(m.verificacoes.linhas[1]!.flags.includes("orcamento_excedido"), "60 000 gastos: acima do tecto");
    // Acima do tecto, a conferencia previa nem chama.
    await m.servico.receber(GENUINO.id, "banco", GENUINO.documentos.banco);
    assert.equal(pedidos.length, 2);
    assert.ok(m.verificacoes.linhas[2]!.flags.includes("orcamento_excedido"));
  });

  it("orcamento diario da virtual key esgotado (429): fila, e nao ilegivel", async () => {
    const transporte: Transporte = async () => ({ status: 429, headers: { get: () => null }, text: async () => "budget exceeded" });
    const m = montar({ ocr: visao(autorizado("APD/2026/1"), "sk-teste", transporte) });
    await carregarTodos(m, GENUINO);
    assert.ok(m.verificacoes.linhas.every((v) => v.flags.includes("orcamento_excedido") && v.resultado === "pendente"));
    const d = await m.servico.decidir(GENUINO.id);
    assert.ok(d.estado === "decidido" && d.avaliacao.resultado === "fila");
  });
});

describe("URL de revisao (DoD 3)", () => {
  it("TTL de 300 s, e o acesso fica anotado antes de a URL existir", async () => {
    const ordem: string[] = [];
    let ttl = 0;
    const m = montar({
      armazem: (s) => ({
        ...s,
        nome: s.nome,
        put: s.put.bind(s),
        get: s.get.bind(s),
        head: s.head.bind(s),
        delete: s.delete.bind(s),
        list: s.list.bind(s),
        signUrl: async (ctx, ref, o) => {
          ordem.push("url");
          ttl = o.ttlSeconds;
          return s.signUrl(ctx, ref, o);
        },
      }),
    });
    await carregarTodos(m, GENUINO);
    const v = m.verificacoes.linhas[0]!;
    const url = await m.servico.urlParaRevisao("ts:revisor-1", GENUINO.id, v.id, {
      anotarAcesso: async (a) => {
        ordem.push(`auditoria:${a.revisor}:${a.verificacaoId}`);
      },
    });
    assert.deepEqual(ordem, [`auditoria:ts:revisor-1:${v.id}`, "url"]);
    assert.equal(ttl, 300);
    assert.equal((await m.sto.buscar(url)).estado, 200);
    m.avancar(300_000);
    assert.notEqual((await m.sto.buscar(url)).estado, 200, "aos 300 s ja nao abre");
  });

  it("uma auditoria que falha nao deixa sair URL", async () => {
    const m = montar();
    await carregarTodos(m, GENUINO);
    await assert.rejects(
      m.servico.urlParaRevisao("ts:1", GENUINO.id, m.verificacoes.linhas[0]!.id, { anotarAcesso: async () => { throw new Error("auditoria fora"); } }),
    );
  });
});

describe("purga D+30 (criterio 10)", () => {
  it("rejeitado: nada a D+30 menos um milissegundo; tudo a D+30; e a segunda passagem nao apaga nada", async () => {
    const m = montar();
    await carregarTodos(m, ADULTERADO);
    await carregarTodos(m, OUTRO_GENUINO);
    await m.casos.marcarFase(ADULTERADO.id, "rejeitado");
    const antes = m.sto.total();
    m.avancar(30 * 86_400_000 - 1);
    assert.equal(await m.servico.purgar(m.casos), 0);
    m.avancar(1);
    assert.equal(await m.servico.purgar(m.casos), 4);
    assert.equal(m.sto.total(), antes - 4);
    assert.ok((await m.verificacoes.doCaso(ADULTERADO.id)).every((v) => v.extraidoCifrado === null));
    assert.ok((await m.verificacoes.doCaso(OUTRO_GENUINO.id)).every((v) => v.extraidoCifrado !== null), "o caso vivo fica");
    assert.equal(await m.servico.purgar(m.casos), 0);
  });

  it("abandonado tambem se purga", async () => {
    const m = montar();
    await carregarTodos(m, GENUINO);
    m.casos.juntar({ ...(await m.casos.porId(GENUINO.id))!, fase: "abandonado" });
    m.avancar(30 * 86_400_000);
    assert.equal(await m.servico.purgar(m.casos), 4);
  });
});

describe("os achados da revisao adversarial", () => {
  const EXPIRADO = CONJUNTO.filter((c) => c.classe === "data_editada")[3]!;

  function alvaraCom(c: CasoSintetico, validade: string, semente: number): Uint8Array {
    const linhas = c.linhas.alvara.map((l) => (l.startsWith("VALIDADE:") ? `VALIDADE: ${validade}` : l));
    return desenhar({ linhas, fundo: semente, ruido: 0, semente });
  }

  it("A1, A2: a fila fecha o caso; e depois de o T&S o devolver, o alvara corrigido decide sem a marca antiga", async () => {
    const m = montar();
    await carregarTodos(m, EXPIRADO);
    const primeira = await m.servico.decidir(EXPIRADO.id);
    assert.ok(primeira.estado === "decidido" && primeira.motivoPublico === "alvara_expirado");
    assert.equal((await m.casos.porId(EXPIRADO.id))!.fase, "em_revisao");
    const novo = alvaraCom(EXPIRADO, "31/12/2028", 99);
    assert.deepEqual(await m.servico.receber(EXPIRADO.id, "alvara", novo), { estado: "recusado", motivo: "caso" });
    // O T&S devolve o caso ao dono (KAM-089); o duplo faz as vezes da fila.
    m.casos.juntar({ ...(await m.casos.porId(EXPIRADO.id))!, fase: "kyc_pendente" });
    assert.equal((await m.servico.receber(EXPIRADO.id, "alvara", novo)).estado, "lido");
    const segunda = await m.servico.decidir(EXPIRADO.id);
    assert.ok(segunda.estado === "decidido");
    if (segunda.estado !== "decidido") return;
    assert.deepEqual(segunda.avaliacao.marcas, [], "a marca do alvara antigo nao se cola ao novo");
    assert.equal(segunda.avaliacao.resultado, "k1_ok");
    for (const v of m.verificacoes.linhas.filter((x) => x.tipo === "alvara")) {
      assert.ok(!v.flags.includes("alvara_expirado"), "as flags de uma linha sao as do seu ficheiro");
    }
  });

  it("A2: uma regra dura nao se lava recarregando os quatro documentos", async () => {
    const reutilizado = CONJUNTO.find((c) => c.classe === "imagem_reutilizada")!;
    const m = montar();
    for (const c of CONJUNTO.slice(0, CONJUNTO.indexOf(reutilizado))) await carregarTodos(m, c);
    await carregarTodos(m, reutilizado);
    const d = await m.servico.decidir(reutilizado.id);
    assert.ok(d.estado === "decidido" && d.avaliacao.resultado === "fila");
    for (const t of TIPOS) {
      assert.deepEqual(await m.servico.receber(reutilizado.id, t, alvaraCom(reutilizado, "31/12/2028", 500 + TIPOS.indexOf(t))), { estado: "recusado", motivo: "caso" });
    }
    assert.deepEqual(await m.servico.decidir(reutilizado.id), { estado: "fora_de_fase", fase: "em_revisao" });
  });

  it("A5: uma avaria do OCR nao deixa o documento orfao no STO", async () => {
    const m = montar({ ocr: { nome: "avariado", extract: async () => { throw new Error("tesseract saiu com 1"); } } });
    m.juntar(GENUINO);
    await assert.rejects(m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi), /tesseract/);
    assert.equal(m.sto.total(), 0);
    assert.equal(m.verificacoes.linhas.length, 0);
  });

  it("A9: um modelo que responde lixo vai a fila e nunca rejeita o caso", async () => {
    const transporte: Transporte = async () => ({
      status: 200,
      headers: { get: () => "0.001" },
      text: async () => JSON.stringify({ choices: [{ message: { content: "Desculpe, nao posso ajudar." } }] }),
    });
    const m = montar({
      ocr: new OcrDeVisao({
        gate: { decidir: async () => ({ autorizado: true, apdRef: "APD/2026/1" }) },
        transporte,
        urlBase: "http://litellm.interno",
        chaveVirtual: "sk-teste",
        fornecedor: "fornecedor_de_visao",
        custoDoCaso: async () => 0,
        tectoPorCasoMicroUsd: 50_000,
        estimativaMicroUsd: 1_000,
      }),
    });
    m.juntar(GENUINO);
    for (const s of [1, 2, 3]) {
      const r = await m.servico.receber(GENUINO.id, "bi", alvaraCom(GENUINO, "31/12/2028", 700 + s));
      assert.equal(r.estado, "lido");
    }
    assert.equal((await m.casos.porId(GENUINO.id))!.fase, "kyc_pendente");
    assert.ok(m.verificacoes.linhas.every((v) => v.flags.includes("visao_recusada") && v.resultado === "pendente"));
  });

  it("A10: o mesmo ficheiro ilegivel outra vez responde ilegivel, e nao lido", async () => {
    const m = montar();
    m.juntar(GENUINO);
    const ilegivel = desenhar({ linhas: ["BILHETE DE IDENTIDADE"], fundo: 1, ruido: 0, semente: 1 });
    await m.servico.receber(GENUINO.id, "bi", ilegivel);
    const r = await m.servico.receber(GENUINO.id, "bi", ilegivel);
    assert.ok(r.estado === "novo_carregamento" && r.restantes === 2 && r.motivoPublico === "ilegivel");
  });

  it("M29: o dia de hoje e o de Luanda — as 23:30 UTC ja e amanha la", async () => {
    const hoje = (agora: string) => {
      const m = montar({ agora: new Date(agora) });
      return m;
    };
    for (const [agora, esperado] of [["2026-11-10T22:30:00Z", "k1_ok"], ["2026-11-10T23:30:00Z", "fila"]] as const) {
      const m = hoje(agora);
      m.juntar(GENUINO);
      for (const t of TIPOS) {
        await m.servico.receber(GENUINO.id, t, t === "alvara" ? alvaraCom(GENUINO, "10/11/2026", 800) : GENUINO.documentos[t]);
      }
      const d = await m.servico.decidir(GENUINO.id);
      assert.ok(d.estado === "decidido" && d.avaliacao.resultado === esperado, `${agora}: ${JSON.stringify(d)}`);
    }
  });
});

describe("o adaptador SQL, com um cliente falso", () => {
  it("o sha256 e o phash vao como bytea e voltam como hexadecimal; o conflito rele por sha", async () => {
    const chamadas: { texto: string; valores: readonly unknown[] }[] = [];
    const linha = {
      id: "v1",
      onboarding_id: GENUINO.id,
      doc_tipo: "bi",
      doc_ref: "t/x/kyc_documento/y",
      sha256: Buffer.from("ab".repeat(32), "hex"),
      phash: Buffer.from("0123456789abcdef", "hex"),
      extraido_enc: Buffer.from([1, 2]),
      flags: ["software_de_edicao"],
      score: null,
      resultado: "pendente",
      versao_regras: "1.0.0",
      custo_micro_usd: "30000",
      criado_at: HOJE,
    };
    let devolver: unknown[] = [];
    const cliente = {
      query: async (texto: string, valores: readonly unknown[] = []) => {
        chamadas.push({ texto, valores });
        const r = devolver;
        devolver = [linha];
        return { rows: r as never[] };
      },
    };
    const { VerificacoesSql, SQL_INSERIR, SQL_POR_SHA } = await import("../src/kyc/index.ts");
    const repo = new VerificacoesSql(cliente);
    const r = await repo.inserir({
      onboardingId: GENUINO.id,
      tipo: "bi",
      docRef: "t/x/kyc_documento/y",
      sha256: "ab".repeat(32),
      phash: "0123456789abcdef",
      extraidoCifrado: new Uint8Array([1, 2]),
      flags: ["software_de_edicao"],
      resultado: "pendente",
      versaoRegras: "1.0.0",
      custoMicroUsd: 30000,
    });
    assert.equal(chamadas[0]!.texto, SQL_INSERIR);
    assert.deepEqual(chamadas[0]!.valores[3], Buffer.from("ab".repeat(32), "hex"));
    assert.equal((chamadas[0]!.valores[3] as Buffer).length, 32);
    assert.equal((chamadas[0]!.valores[4] as Buffer).length, 8);
    assert.equal(chamadas[1]!.texto, SQL_POR_SHA, "sem linha devolvida, rele");
    assert.ok(r.repetida);
    assert.equal(r.verificacao.sha256, "ab".repeat(32));
    assert.equal(r.verificacao.phash, "0123456789abcdef");
    assert.equal(r.verificacao.custoMicroUsd, 30000);
  });
});

describe("o PNG que se guarda e o que se enviou", () => {
  it("o STO guarda os octetos do dono, e nao a pagina reescrita", async () => {
    const m = montar();
    m.juntar(GENUINO);
    await m.servico.receber(GENUINO.id, "bi", GENUINO.documentos.bi);
    const v = m.verificacoes.linhas[0]!;
    const partes: Uint8Array[] = [];
    for await (const b of await m.sto.storage.get({ tenantId: GENUINO.tenantId }, { key: v.docRef, tamanho: 0, sha256: null })) partes.push(b);
    assert.deepEqual(Buffer.concat(partes), Buffer.from(GENUINO.documentos.bi));
    assert.notDeepEqual(Buffer.from(codificarPngCinzento({ largura: 1, altura: 1, cinzento: new Uint8Array(1) })), Buffer.concat(partes));
  });
});

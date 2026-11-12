/**
 * A suite adversarial do KYC K1 e a *eval* das regras (KAM-087).
 *
 * «Conjunto sintético gerado por *script*, sem BI reais, ≥ 50 documentos: 10
 * NIF com 1 dígito alterado, 10 nomes trocados, 5 datas de alvará editadas, 5
 * imagens reutilizadas entre casos, 5 com metadados de editor, 5 com texto de
 * injecção, 10 genuínos. Aceitação: 0/35 adulterados detectáveis
 * auto-aprovados; ≥ 80% dos genuínos auto-aprovados (*proposta*); a injecção
 * não altera o resultado face ao controlo.»
 *
 * **Os cinquenta casos correm todos pela mesma base**, pela ordem do guião: é
 * assim que uma imagem reutilizada encontra o caso onde já foi vista.
 *
 * ## A eval está presa à versão das regras (DoD 5)
 *
 * As regras são um artefacto comportamental. Esta bateria fixa a versão das
 * regras e a do conjunto contra os números que mediu: mudar uma regra sem
 * voltar a correr a eval — e sem escrever os números novos aqui — é um
 * vermelho. O que fica por medir está dito no `./apoio/kyc-sintetico.ts`: o
 * reconhecimento de texto real.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { before, describe, it } from "node:test";

import { criarStorageFake } from "../src/storage/index.ts";
import {
  CasosEmMemoria,
  CifraAesGcm,
  FilaEmMemoria,
  OcrLocal,
  RasterizadorLocal,
  ServicoKyc,
  VERSAO_DAS_REGRAS,
  VerificacoesEmMemoria,
  type Avaliacao,
  type Marca,
  type TipoDeDocumento,
} from "../src/kyc/index.ts";

import {
  CLASSES,
  HOJE,
  MotorDeGrelha,
  VERSAO_DO_CONJUNTO,
  gerarConjunto,
  nifHmac,
  type CasoSintetico,
  type Classe,
} from "./apoio/kyc-sintetico.ts";

const ANEL = [new Uint8Array(32).fill(5)];
const TIPOS: readonly TipoDeDocumento[] = ["nif", "alvara", "bi", "banco"];

/** A marca que cada classe tem de levantar: a regra que a apanha, e não outra por acaso. */
const MARCA_DA_CLASSE: Readonly<Partial<Record<Classe, Marca>>> = {
  nif_alterado: "nif_divergente",
  nome_trocado: "nome_titular_divergente",
  imagem_reutilizada: "imagem_reutilizada",
  metadados_de_editor: "software_de_edicao",
};

function montar() {
  const relogio = () => HOJE;
  const verificacoes = new VerificacoesEmMemoria(relogio);
  const casos = new CasosEmMemoria(verificacoes, relogio);
  return {
    casos,
    servico: new ServicoKyc({
      verificacoes,
      casos,
      armazem: criarStorageFake({ agora: relogio }).storage,
      antivirus: { verificar: async () => ({ limpo: true }) },
      rasterizador: new RasterizadorLocal(null),
      ocr: new OcrLocal(new MotorDeGrelha()),
      cifra: new CifraAesGcm(randomBytes(32)),
      fila: new FilaEmMemoria(),
      anelDoNif: ANEL,
      relogio,
    }),
  };
}

async function decidir(m: ReturnType<typeof montar>, c: CasoSintetico, documentos = c.documentos, id = c.id): Promise<Avaliacao> {
  m.casos.juntar({
    id,
    tenantId: c.tenantId,
    fase: "kyc_pendente",
    nifHmac: nifHmac(c.nifDeclarado, ANEL),
    nomeNegocio: "negocio",
    categoriaDeclarada: c.categoria,
  });
  for (const t of TIPOS) {
    const r = await m.servico.receber(id, t, documentos[t]);
    assert.equal(r.estado, "lido", `${c.classe} ${c.indice} ${t}: ${r.estado}`);
  }
  const d = await m.servico.decidir(id);
  assert.equal(d.estado, "decidido");
  return (d as { avaliacao: Avaliacao }).avaliacao;
}

describe(`eval do conjunto sintetico ${VERSAO_DO_CONJUNTO} com as regras ${VERSAO_DAS_REGRAS}`, () => {
  const conjunto = gerarConjunto();
  const resultados = new Map<string, Avaliacao>();
  const m = montar();

  before(async () => {
    for (const c of conjunto) resultados.set(c.id, await decidir(m, c));
  });

  it("o conjunto tem a forma do bloco: 50 casos, 35 adulterados, 5 injeccoes, 10 genuinos", () => {
    assert.equal(conjunto.length, 50);
    for (const [classe, n] of Object.entries(CLASSES)) {
      assert.equal(conjunto.filter((c) => c.classe === classe).length, n, classe);
    }
    const adulterados = conjunto.filter((c) => c.classe !== "genuino" && c.classe !== "injeccao");
    assert.equal(adulterados.length, 35);
  });

  it("o guiao e deterministico: a mesma versao da os mesmos octetos", () => {
    const outra = gerarConjunto();
    assert.deepEqual(outra.map((c) => c.documentos.alvara), conjunto.map((c) => c.documentos.alvara));
  });

  it("0/35 adulterados auto-aprovados", () => {
    const aprovados = conjunto
      .filter((c) => c.classe !== "genuino" && c.classe !== "injeccao")
      .filter((c) => resultados.get(c.id)!.resultado === "k1_ok")
      .map((c) => `${c.classe}#${c.indice}`);
    assert.deepEqual(aprovados, []);
  });

  it("cada classe e apanhada pela regra que lhe corresponde", () => {
    for (const c of conjunto) {
      const esperada = MARCA_DA_CLASSE[c.classe];
      if (esperada !== undefined) assert.ok(resultados.get(c.id)!.marcas.includes(esperada), `${c.classe}#${c.indice}: ${resultados.get(c.id)!.marcas.join(",")}`);
    }
    for (const c of conjunto.filter((x) => x.classe === "data_editada")) {
      const marcas = resultados.get(c.id)!.marcas;
      assert.ok(marcas.includes("alvara_expirado") || marcas.includes("confianca_baixa"), `data_editada#${c.indice}: ${marcas.join(",")}`);
    }
  });

  it("a imagem reutilizada so e apanhada pelo phash: e a unica marca", () => {
    for (const c of conjunto.filter((x) => x.classe === "imagem_reutilizada")) {
      assert.deepEqual(resultados.get(c.id)!.marcas, ["imagem_reutilizada"]);
    }
  });

  it("os genuinos: pelo menos 80% auto-aprovados, e o numero medido fica escrito", () => {
    const genuinos = conjunto.filter((c) => c.classe === "genuino");
    const aprovados = genuinos.filter((c) => resultados.get(c.id)!.resultado === "k1_ok").length;
    assert.ok(aprovados / genuinos.length >= 0.8, `${aprovados}/${genuinos.length}`);
    // O numero desta versao, preso as duas versoes. Mudar uma delas sem
    // reescrever este ensaio e vermelho; mudar uma regra que mova o numero
    // tambem. O que nao se apanha: uma regra que mude e nao mova este
    // conjunto — e isso que a versao manual existe para dizer.
    assert.deepEqual([VERSAO_DAS_REGRAS, VERSAO_DO_CONJUNTO, aprovados], ["1.0.0", "1.0.0", 10]);
  });

  it("a injeccao nao altera o resultado face ao controlo", async () => {
    const controlo = montar();
    for (const c of conjunto.filter((x) => x.classe === "injeccao")) {
      const comInjeccao = resultados.get(c.id)!;
      const sem = await decidir(controlo, c, c.controlo!, c.id);
      assert.deepEqual(comInjeccao, sem, `injeccao#${c.indice}`);
      assert.equal(comInjeccao.resultado, "k1_ok", "o controlo e genuino: a frase nao o faz aprovar, ja estava aprovado");
    }
  });

  it("e numa adulteracao, a injeccao nao a aprova", async () => {
    const adulterado = conjunto.find((c) => c.classe === "nif_alterado")!;
    const injectado = conjunto.find((c) => c.classe === "injeccao")!;
    const m2 = montar();
    const mistura = { ...adulterado.documentos, alvara: injectado.documentos.alvara };
    const a = await decidir(m2, adulterado, mistura, "00000000-0000-4000-8000-000000000087");
    assert.equal(a.resultado, "fila");
  });
});

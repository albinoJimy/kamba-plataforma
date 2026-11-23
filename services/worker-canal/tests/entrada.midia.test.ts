/**
 * O MED no processo de entrada (KAM-231; decisao do fundador de 2026-11-21, P4 A).
 *
 * Prova-se a **montagem**, sem rede nem base: o MED, o cliente da Graph e o
 * *token* do canal estao provados em `packages/core-ts/tests/med.*.test.ts`.
 * Aqui o que importa e:
 *
 * 1. em `staging` e `prod`, sem um dos tres segredos ou sem o armazenamento,
 *    **o arranque recusa** — nunca cai para «sem midia» em silencio;
 * 2. em `dev`, sem eles, arranca sem midia e regista **um** aviso;
 * 3. cada instrucao do MED corre numa transaccao com o tenant do pedido;
 * 4. o caminho inteiro — reserva, Graph, armazenamento, marcacao — devolve o
 *    `asset_id` que o CHR poe na invocacao.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { describe, it } from "node:test";

import { Logger } from "@kamba/core-ts/logger";
import { ANFITRIOES_DA_DESCARGA, type Buscar, SQL_TOKEN_REF_DA_CONVERSA } from "@kamba/core-ts/med";
import { cifrarToken } from "@kamba/core-ts/onboarding";
import { ArranqueAbortadoError, EnvSecretProvider, nomeDaVariavel } from "@kamba/core-ts/secrets";
import { criarStorageFake } from "@kamba/core-ts/storage";

import {
  type LigacaoDaEntrada,
  ambienteDaMidia,
  midiaDaEntrada,
  recepcaoDeMidia,
  sqlDoTenant,
} from "../src/entrada.ts";
import { SERVICE } from "../src/meta.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONVERSA = "5c6d7e8f-9a0b-4c1d-8e2f-3a4b5c6d7e8f";
const CONTACTO = "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901";
const ASSET = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d";
const MEDIA_ID = "990011223344556";
/** Um *token* de ensaio: nao e de conta nenhuma. */
const TOKEN = ["ensaio", "entrada"].join("-");

const ARMAZENAMENTO = {
  KAMBA_STORAGE_ENDPOINT: "http://seaweedfs:8333",
  KAMBA_STORAGE_BUCKET: "kamba-media-ensaio",
  KAMBA_STORAGE_REGION: "ao-ensaio-1",
  KAMBA_STORAGE_DESTINO_COUNTRY: "AO",
  KAMBA_STORAGE_DESTINO_PROVIDER: "seaweedfs",
};

function segredos(): Record<string, string> {
  return {
    KAMBA_SECRET_KEK_TOKEN_CLIENTE: `t1:${randomBytes(32).toString("base64")}`,
    KAMBA_SECRET_STORAGE_ACCESS_KEY_ID: "chave-de-ensaio",
    KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY: "segredo-de-ensaio",
  };
}

/** Uma ligacao que guarda as instrucoes e nao responde nada. */
class LigacaoQueGuarda implements LigacaoDaEntrada {
  readonly instrucoes: { texto: string; valores: unknown[] }[] = [];
  respostas: (texto: string, valores: unknown[]) => unknown[] = () => [];

  async query(texto: string, valores: unknown[] = []): Promise<{ rows: unknown[] }> {
    this.instrucoes.push({ texto: texto.trim(), valores });
    return { rows: this.respostas(texto, valores) };
  }
}

function registo(): { log: Logger; linhas: Record<string, unknown>[] } {
  const linhas: Record<string, unknown>[] = [];
  const log = new Logger(SERVICE, {
    destino: { write: (texto: string) => linhas.push(JSON.parse(texto) as Record<string, unknown>) },
  });
  return { log, linhas };
}

describe("o ambiente da midia", () => {
  it("vazio e dev; dev, staging e prod valem; um valor desconhecido recusa", () => {
    assert.equal(ambienteDaMidia({}), "dev");
    assert.equal(ambienteDaMidia({ KAMBA_ENV: " staging " }), "staging");
    assert.equal(ambienteDaMidia({ KAMBA_ENV: "prod" }), "prod");
    for (const valor of ["producao", "PROD", "production"]) {
      assert.throws(() => ambienteDaMidia({ KAMBA_ENV: valor }));
    }
  });
});

describe("o arranque da midia em staging e prod (decisao do fundador, P4 A)", () => {
  for (const ambiente of ["staging", "prod"] as const) {
    it(`${ambiente}: arranca com os tres segredos e o armazenamento`, async () => {
      const midia = await midiaDaEntrada({
        env: { KAMBA_ENV: ambiente, ...ARMAZENAMENTO, ...segredos() },
        ligacao: new LigacaoQueGuarda(),
      });
      assert.equal(typeof midia, "function");
    });

    it(`${ambiente}: sem um dos tres segredos, **recusa** e nomeia o que falta`, async () => {
      for (const [variavel, ref] of [
        ["KAMBA_SECRET_KEK_TOKEN_CLIENTE", "kek_token_cliente"],
        ["KAMBA_SECRET_STORAGE_ACCESS_KEY_ID", "storage_access_key_id"],
        ["KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY", "storage_secret_access_key"],
      ] as const) {
        const env: Record<string, string> = { KAMBA_ENV: ambiente, ...ARMAZENAMENTO, ...segredos() };
        delete env[variavel];
        const { log, linhas } = registo();
        await assert.rejects(midiaDaEntrada({ env, ligacao: new LigacaoQueGuarda(), log }), (erro: unknown) => {
          assert.ok(erro instanceof ArranqueAbortadoError, String(erro));
          assert.deepEqual(erro.segredos, [ref]);
          return true;
        });
        // Nenhum «sem midia» em silencio: nem aviso, nem arranque.
        assert.equal(linhas.length, 0);
      }
    });

    it(`${ambiente}: sem a configuracao do armazenamento, **recusa** sem repetir valores`, async () => {
      for (const variavel of Object.keys(ARMAZENAMENTO)) {
        const env: Record<string, string> = { KAMBA_ENV: ambiente, ...ARMAZENAMENTO, ...segredos() };
        delete env[variavel];
        await assert.rejects(midiaDaEntrada({ env, ligacao: new LigacaoQueGuarda() }), (erro: unknown) => {
          assert.ok(erro instanceof ArranqueAbortadoError, String(erro));
          assert.match(erro.message, new RegExp(variavel));
          assert.equal(erro.message.includes("chave-de-ensaio"), false);
          return true;
        });
      }
    });
  }

  it("prod: um destino fora de Angola sem apd_ref recusa", async () => {
    await assert.rejects(
      midiaDaEntrada({
        env: { KAMBA_ENV: "prod", ...ARMAZENAMENTO, KAMBA_STORAGE_DESTINO_COUNTRY: "PT", ...segredos() },
        ligacao: new LigacaoQueGuarda(),
      }),
      (erro: unknown) => erro instanceof ArranqueAbortadoError,
    );
  });
});

describe("o arranque da midia em dev", () => {
  it("sem armazenamento: arranca **sem** midia, com um aviso", async () => {
    const { log, linhas } = registo();
    const midia = await midiaDaEntrada({ env: { KAMBA_ENV: "dev", ...segredos() }, ligacao: new LigacaoQueGuarda(), log });
    assert.equal(midia, undefined);
    assert.equal(linhas.length, 1);
    assert.equal(linhas[0]?.["outcome"], "midia_desligada_em_dev");
    assert.equal(linhas[0]?.["level"] ?? linhas[0]?.["nivel"] ?? "warn", "warn");
  });

  it("sem um dos segredos: arranca **sem** midia, com um aviso", async () => {
    for (const variavel of Object.keys(segredos())) {
      const env: Record<string, string> = { ...ARMAZENAMENTO, ...segredos() };
      delete env[variavel];
      const { log, linhas } = registo();
      assert.equal(await midiaDaEntrada({ env, ligacao: new LigacaoQueGuarda(), log }), undefined);
      assert.deepEqual(linhas.map((l) => l["outcome"]), ["midia_desligada_em_dev"]);
    }
  });

  it("com tudo: liga a midia, e nao avisa", async () => {
    const { log, linhas } = registo();
    const midia = await midiaDaEntrada({ env: { ...ARMAZENAMENTO, ...segredos() }, ligacao: new LigacaoQueGuarda(), log });
    assert.equal(typeof midia, "function");
    assert.equal(linhas.length, 0);
  });
});

describe("a base do MED, com o tenant em cada instrucao", () => {
  it("cada query corre em BEGIN, set_config do tenant, a instrucao, COMMIT", async () => {
    const ligacao = new LigacaoQueGuarda();
    ligacao.respostas = (texto) => (texto === "SELECT 1" ? [{ x: 1 }] : []);
    const bd = sqlDoTenant(ligacao, TENANT);
    const r = await bd.query<{ x: number }>("SELECT 1", []);
    assert.deepEqual(r.rows, [{ x: 1 }]);
    await bd.query("SELECT 2");
    const textos = ligacao.instrucoes.map((i) => i.texto);
    assert.deepEqual(textos.map((t) => t.split(" ")[0]), ["BEGIN", "SELECT", "SELECT", "COMMIT", "BEGIN", "SELECT", "SELECT", "COMMIT"]);
    assert.match(textos[1]!, /set_config\('app\.tenant_id', \$1, true\)/);
    assert.deepEqual(ligacao.instrucoes[1]!.valores, [TENANT]);
    assert.equal(textos[2], "SELECT 1");
  });
});

describe("a recepcao de midia, de ponta a ponta sem rede", () => {
  it("guarda a foto e devolve o asset_id, com cada instrucao sob o tenant e o token so no cabecalho", async () => {
    const kek = randomBytes(32).toString("base64");
    const ref = `meta_client_token/${randomBytes(16).toString("hex")}`;
    const cofre = new EnvSecretProvider({
      ambiente: "staging",
      env: {
        KAMBA_SECRET_KEK_TOKEN_CLIENTE: `t1:${kek}`,
        [nomeDaVariavel(ref)]: cifrarToken(kek, "t1", TENANT, TOKEN),
      },
    });

    const ligacao = new LigacaoQueGuarda();
    ligacao.respostas = (texto) => {
      if (texto.includes("INSERT INTO platform.media_assets")) return [{ asset_id: ASSET }];
      if (texto === SQL_TOKEN_REF_DA_CONVERSA) return [{ token_ref: ref }];
      if (texto.includes("UPDATE platform.media_assets")) return [{ asset_id: ASSET }];
      return [];
    };

    const url = `https://${ANFITRIOES_DA_DESCARGA[0]}/midia?ensaio=1`;
    const pedidos: { url: string; autorizacao: string | undefined }[] = [];
    const buscar: Buscar = async (alvo, init) => {
      pedidos.push({ url: alvo, autorizacao: (init.headers as Record<string, string>)["authorization"] });
      if (pedidos.length === 1) {
        return new Response(JSON.stringify({ url, mime_type: "image/jpeg", file_size: 4 }), { status: 200 });
      }
      return new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xe0]), {
        status: 200,
        headers: { "content-type": "image/jpeg" },
      });
    };

    const receber = recepcaoDeMidia({ ligacao, cofre, armazenamento: criarStorageFake().storage, buscar });
    const resultado = await receber({
      tenantId: TENANT,
      contactId: CONTACTO,
      conversationId: CONVERSA,
      wamid: "wamid.ENSAIO231",
      mediaId: MEDIA_ID,
      waType: "image",
    });
    assert.equal(resultado.estado, "armazenado");
    assert.equal(resultado.assetId, ASSET);

    // As duas idas a Meta, com o token so no cabecalho.
    assert.equal(pedidos.length, 2);
    for (const p of pedidos) {
      assert.equal(p.autorizacao, `Bearer ${TOKEN}`);
      assert.equal(p.url.includes(TOKEN), false);
    }

    // Cada instrucao do MED e da credencial e precedida do contexto do tenant.
    const instrucoes = ligacao.instrucoes;
    const doTrabalho = instrucoes
      .map((i, n) => ({ ...i, n }))
      .filter((i) => i.texto !== "BEGIN" && i.texto !== "COMMIT" && !i.texto.includes("set_config"));
    assert.ok(doTrabalho.length >= 3, `so ${doTrabalho.length} instrucoes`);
    for (const i of doTrabalho) {
      const contexto = instrucoes[i.n - 1]!;
      assert.match(contexto.texto, /set_config\('app\.tenant_id'/, i.texto);
      assert.deepEqual(contexto.valores, [TENANT]);
      assert.equal(instrucoes[i.n - 2]!.texto, "BEGIN");
      assert.equal(instrucoes[i.n + 1]!.texto, "COMMIT");
    }
    // Nenhuma instrucao leva o token, nem o URL da Meta.
    for (const i of instrucoes) {
      assert.equal(JSON.stringify(i).includes(TOKEN), false);
      assert.equal(JSON.stringify(i).includes(url), false);
    }
  });
});

/**
 * Configuração do armazenamento e destino dos dados (KAM-011, CA7).
 *
 * O que se prova aqui é o arranque: sem `destino.country` ou `destino.provider`
 * não há configuração; em `prod`, fora de Angola e sem `apd_ref`, não há
 * serviço; e as credenciais vêm do `SecretProvider`, nunca do ambiente
 * `KAMBA_STORAGE_*`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { EnvSecretProvider } from "../src/secrets/env.ts";
import { SecretAusenteError } from "../src/secrets/port.ts";
import {
  ConfigDeArmazenamentoError,
  DestinoSemApdRefError,
  type ProcessEnv,
  VARIAVEIS,
  criarStorageS3,
  lerConfig,
} from "../src/storage/config.ts";
import { novaChave } from "../src/storage/chave.ts";
import { ArmazenamentoIndisponivelError } from "../src/storage/port.ts";
import { CONFIG_DE_TESTE, CREDENCIAIS_DE_TESTE, Relogio } from "./apoio/alvos-storage.ts";
import { S3EmMemoria } from "./apoio/s3-em-memoria.ts";

const BOM: ProcessEnv = {
  KAMBA_STORAGE_ENDPOINT: "http://seaweedfs:8333",
  KAMBA_STORAGE_BUCKET: "kamba-dev",
  KAMBA_STORAGE_REGION: "us-east-1",
  KAMBA_STORAGE_DESTINO_COUNTRY: "AO",
  KAMBA_STORAGE_DESTINO_PROVIDER: "seaweedfs_local",
};

function sem(...nomes: string[]): ProcessEnv {
  const env = { ...BOM };
  for (const nome of nomes) delete env[nome];
  return env;
}

test("lê a configuração completa e expõe o destino para o gate de transferência", () => {
  const config = lerConfig({ ambiente: "prod", env: BOM });
  assert.deepEqual(config, {
    endpoint: "http://seaweedfs:8333",
    bucket: "kamba-dev",
    regiao: "us-east-1",
    destino: { country: "AO", provider: "seaweedfs_local", apdRef: null },
    avisos: [],
  });
  // Espaços à volta não mudam o valor; a barra final do endpoint também não.
  const comEspacos = lerConfig({
    ambiente: "dev",
    env: { ...BOM, KAMBA_STORAGE_ENDPOINT: " https://s3.exemplo.co.ao/ ", KAMBA_STORAGE_BUCKET: " kamba-dev " },
  });
  assert.equal(comEspacos.endpoint, "https://s3.exemplo.co.ao");
  assert.equal(comEspacos.bucket, "kamba-dev");
  // A porta por omissão do esquema não fica no endpoint: é a forma que o
  // cabeçalho `Host` leva, e a que foi assinada.
  assert.equal(
    lerConfig({ ambiente: "dev", env: { ...BOM, KAMBA_STORAGE_ENDPOINT: "https://s3.exemplo.co.ao:443" } }).endpoint,
    "https://s3.exemplo.co.ao",
  );
});

test("o arranque falha sem destino.country, e sem destino.provider", () => {
  for (const variavel of [VARIAVEIS.country, VARIAVEIS.provider]) {
    for (const ambiente of ["dev", "staging", "prod"] as const) {
      for (const env of [sem(variavel), { ...BOM, [variavel]: "" }, { ...BOM, [variavel]: "   " }]) {
        assert.throws(
          () => lerConfig({ ambiente, env }),
          (erro: unknown) =>
            erro instanceof ConfigDeArmazenamentoError &&
            erro.problemas.length === 1 &&
            erro.problemas[0] === `${variavel} em falta`,
          `${variavel} em ${ambiente}`,
        );
      }
    }
  }
});

test("todas as variáveis em falta são nomeadas de uma vez", () => {
  assert.throws(
    () => lerConfig({ ambiente: "dev", env: {} }),
    (erro: unknown) => {
      assert.ok(erro instanceof ConfigDeArmazenamentoError);
      assert.deepEqual(erro.problemas, [
        "KAMBA_STORAGE_ENDPOINT em falta",
        "KAMBA_STORAGE_BUCKET em falta",
        "KAMBA_STORAGE_REGION em falta",
        "KAMBA_STORAGE_DESTINO_COUNTRY em falta",
        "KAMBA_STORAGE_DESTINO_PROVIDER em falta",
      ]);
      for (const problema of erro.problemas) assert.ok(erro.message.includes(problema));
      return true;
    },
  );
});

test("valores mal formados são recusados sem serem repetidos na mensagem", () => {
  const casos: readonly (readonly [string, string])[] = [
    [VARIAVEIS.country, "ao"],
    [VARIAVEIS.country, "AGO"],
    [VARIAVEIS.country, "Angola"],
    [VARIAVEIS.country, "A1"],
    [VARIAVEIS.provider, "SeaweedFS"],
    [VARIAVEIS.provider, "x"],
    [VARIAVEIS.provider, "com espaco"],
    [VARIAVEIS.bucket, "Kamba_Dev"],
    [VARIAVEIS.bucket, "a/b"],
    [VARIAVEIS.regiao, "US EAST"],
    [VARIAVEIS.apdRef, "com espaco"],
    [VARIAVEIS.apdRef, "x".repeat(129)],
    [VARIAVEIS.endpoint, "seaweedfs:8333"],
    [VARIAVEIS.endpoint, "ftp://seaweedfs:8333"],
    [VARIAVEIS.endpoint, "http://seaweedfs:8333/caminho"],
    [VARIAVEIS.endpoint, "http://seaweedfs:8333/?x=1"],
    [VARIAVEIS.endpoint, "http://nome:passe@seaweedfs:8333"],
    [VARIAVEIS.endpoint, "http://seaweedfs:8333#f"],
    [VARIAVEIS.endpoint, "http://seaweedfs:porta"],
    [VARIAVEIS.endpoint, "http://seaweedfs:99999"],
    [VARIAVEIS.endpoint, "http://com espaco:8333"],
    [VARIAVEIS.endpoint, "http://"],
    [VARIAVEIS.endpoint, "isto não é uma URL"],
    [VARIAVEIS.country, "AO\nZA"],
  ];
  for (const [variavel, valor] of casos) {
    assert.throws(
      () => lerConfig({ ambiente: "dev", env: { ...BOM, [variavel]: valor } }),
      (erro: unknown) => {
        assert.ok(erro instanceof ConfigDeArmazenamentoError, `${variavel}=${valor}`);
        assert.equal(erro.problemas.length, 1);
        assert.ok(erro.problemas[0]?.startsWith(`${variavel} mal formada`), erro.problemas[0]);
        assert.equal(erro.message.includes(valor), false, "o valor não aparece na mensagem");
        return true;
      },
    );
  }
});

test("em prod, um destino fora de Angola sem apd_ref impede o arranque", () => {
  for (const country of ["ZA", "DE", "US", "PT", "NA"]) {
    const env = { ...BOM, KAMBA_STORAGE_DESTINO_COUNTRY: country, KAMBA_STORAGE_DESTINO_PROVIDER: "s3_gerido" };
    assert.throws(
      () => lerConfig({ ambiente: "prod", env }),
      (erro: unknown) => {
        assert.ok(erro instanceof DestinoSemApdRefError, country);
        assert.equal(erro.country, country);
        assert.equal(erro.provider, "s3_gerido");
        assert.match(erro.message, /KAMBA_STORAGE_DESTINO_APD_REF/);
        assert.match(erro.message, /não arranca/);
        return true;
      },
    );
    // Uma variável vazia é uma variável ausente: não serve de referência.
    assert.throws(
      () => lerConfig({ ambiente: "prod", env: { ...env, KAMBA_STORAGE_DESTINO_APD_REF: "  " } }),
      DestinoSemApdRefError,
    );
    // Nenhum país é tratado como «adequado»: com a referência, arranca; sem ela, não.
    const comRef = lerConfig({
      ambiente: "prod",
      env: { ...env, KAMBA_STORAGE_DESTINO_APD_REF: "APD/2026/0042" },
    });
    assert.deepEqual(comRef.destino, { country, provider: "s3_gerido", apdRef: "APD/2026/0042" });
    assert.deepEqual(comRef.avisos, []);
  }
});

test("em prod, Angola arranca sem apd_ref", () => {
  const config = lerConfig({ ambiente: "prod", env: BOM });
  assert.equal(config.destino.country, "AO");
  assert.equal(config.destino.apdRef, null);
  assert.deepEqual(config.avisos, []);
});

test("fora de prod, o mesmo destino arranca com um aviso que diz o que acontece em prod", () => {
  for (const ambiente of ["dev", "staging"] as const) {
    const config = lerConfig({
      ambiente,
      env: { ...BOM, KAMBA_STORAGE_DESTINO_COUNTRY: "ZA" },
    });
    assert.equal(config.destino.country, "ZA");
    assert.equal(config.avisos.length, 1);
    assert.match(config.avisos[0] ?? "", /ZA/);
    assert.match(config.avisos[0] ?? "", /em prod isto impede o arranque/);
  }
});

test("a configuração mal formada ganha à regra do destino: primeiro corrige-se o que não se lê", () => {
  assert.throws(
    () =>
      lerConfig({
        ambiente: "prod",
        env: { ...sem(VARIAVEIS.bucket), KAMBA_STORAGE_DESTINO_COUNTRY: "ZA" },
      }),
    ConfigDeArmazenamentoError,
  );
});

test("lerConfig lê process.env quando não lhe dão ambiente nenhum", () => {
  const guardadas = Object.fromEntries(Object.values(VARIAVEIS).map((n) => [n, process.env[n]]));
  try {
    for (const nome of Object.values(VARIAVEIS)) delete process.env[nome];
    assert.throws(() => lerConfig({ ambiente: "dev" }), ConfigDeArmazenamentoError);
    Object.assign(process.env, BOM);
    assert.equal(lerConfig({ ambiente: "dev" }).bucket, "kamba-dev");
  } finally {
    for (const [nome, valor] of Object.entries(guardadas)) {
      if (valor === undefined) delete process.env[nome];
      else process.env[nome] = valor;
    }
  }
});

test("as credenciais vêm do SecretProvider, pelas referências do inventário", async () => {
  const relogio = new Relogio();
  const servidor = new S3EmMemoria({
    bucket: CONFIG_DE_TESTE.bucket,
    regiao: CONFIG_DE_TESTE.regiao,
    credenciais: CREDENCIAIS_DE_TESTE,
    agora: relogio.agora,
  });
  const ctx = { tenantId: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa" };
  const meta = { contentType: "audio/ogg", classe: "audio", retainUntil: new Date("2026-10-13T00:00:00Z") };

  // O provedor real do KAM-010, a ler o ambiente que o ADR-L002 descreve.
  const env: ProcessEnv = {
    KAMBA_SECRET_STORAGE_ACCESS_KEY_ID: CREDENCIAIS_DE_TESTE.accessKeyId,
    KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY: CREDENCIAIS_DE_TESTE.secretAccessKey,
  };
  const storage = criarStorageS3({
    config: CONFIG_DE_TESTE,
    secrets: new EnvSecretProvider({ ambiente: "dev", env }),
    transporte: servidor.transporte,
    agora: relogio.agora,
  });
  const ref = await storage.put(ctx, novaChave(ctx, "audio"), new Uint8Array(8), meta);
  assert.equal(ref.tamanho, 8);

  // Rotação: o valor muda no cofre e o pedido seguinte já usa o novo — sem
  // reiniciar nada. O servidor ainda só conhece o antigo, pelo que recusa.
  env.KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY = "valor-rodado";
  await assert.rejects(
    storage.get(ctx, ref),
    (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.estado === 403,
  );

  // Sem o segredo, a operação falha com o nome dele — e nada chega à rede.
  delete env.KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY;
  const antes = servidor.pedidos.length;
  await assert.rejects(
    storage.get(ctx, ref),
    (erro: unknown) =>
      erro instanceof SecretAusenteError && erro.ref === "storage_secret_access_key",
  );
  assert.equal(servidor.pedidos.length, antes, "sem credenciais não há pedido");
});

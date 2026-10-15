/**
 * A porta `KeyProvider` e o arranque em `prod` (KAM-008).
 *
 * A mesma bateria corre sobre as duas origens de segredos — o ambiente do
 * processo e o *fake* de cofre do KAM-010 —, que é o que torna «trocar de cofre
 * é trocar o provedor de segredos» uma afirmação verificável.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { test } from "node:test";

import {
  AmbienteDeIdentidadeError,
  ChaveDesconhecidaError,
  ChaveMalFormadaError,
  EmbrulhoInvalidoError,
  EnvKeyProvider,
  EpocaInvalidaError,
  type KeyProvider,
  KeyProviderDeAmbienteError,
  SecretsKeyProvider,
  epocaDe,
  epocaValida,
  exigirKeyProviderDeCofre,
  gerarChaveVersionada,
  kidValido,
} from "../src/identity/chaves.ts";
import { Identidade } from "../src/identity/contactos.ts";
import { OpenBaoFakeProvider } from "../src/secrets/openbao-fake.ts";
import { CofreInacessivelError } from "../src/secrets/port.ts";
import { ambienteDeChaves } from "./identity.ambiente.ts";

const K1 = gerarChaveVersionada("k1");
const K2 = gerarChaveVersionada("k2");
const KEK1 = gerarChaveVersionada("kek-1");
const KEK2 = gerarChaveVersionada("kek-2");
const EPOCA_09 = randomBytes(32).toString("base64");
const EPOCA_10 = randomBytes(32).toString("base64");
const CONTEXTO = Buffer.from("contexto-de-ensaio");

function chaveDe(versionada: string): Buffer {
  return Buffer.from(versionada.slice(versionada.indexOf(":") + 1), "base64");
}

/** As duas origens, com o mesmo conteúdo: anel `[k2, k1]`, KEK `[kek-2, kek-1]`. */
const ORIGENS: Readonly<Record<string, () => KeyProvider>> = {
  ambiente: () =>
    new EnvKeyProvider({
      ambiente: "dev",
      env: ambienteDeChaves({
        pesquisa: [K2, K1],
        kek: [KEK2, KEK1],
        epocas: { "202609": EPOCA_09, "202610": EPOCA_10 },
      }),
    }),
  cofre: () =>
    new SecretsKeyProvider({
      segredos: new OpenBaoFakeProvider({
        ambiente: "dev",
        dados: {
          pepper_contact_hmac: [K1, K2],
          kek_contact_dek: [KEK1, KEK2],
          "sujeito_epoch_key/202609": [EPOCA_09],
          "sujeito_epoch_key/202610": [EPOCA_10],
        },
      }),
    }),
};

for (const [origem, criar] of Object.entries(ORIGENS)) {
  test(`[${origem}] serve a chave de pesquisa actual e a anterior, pelo kid`, async () => {
    const chaves = criar();
    assert.ok(Buffer.from(await chaves.getLookupKey("k2")).equals(chaveDe(K2)));
    assert.ok(Buffer.from(await chaves.getLookupKey("k1")).equals(chaveDe(K1)));
  });

  test(`[${origem}] um kid que o cofre não tem é um erro, nunca outra chave`, async () => {
    const chaves = criar();
    for (const kid of ["k3", "K1", "", "k1 ", "kek-1"]) {
      await assert.rejects(chaves.getLookupKey(kid), ChaveDesconhecidaError, `serviu ${kid}`);
    }
  });

  test(`[${origem}] serve a chave de cada época, e só das épocas que existem`, async () => {
    const chaves = criar();
    assert.ok(Buffer.from(await chaves.getEpochKey("202609")).equals(Buffer.from(EPOCA_09, "base64")));
    assert.ok(Buffer.from(await chaves.getEpochKey("202610")).equals(Buffer.from(EPOCA_10, "base64")));
    // Uma época sem chave é uma época destruída: não se inventa uma.
    await assert.rejects(chaves.getEpochKey("202611"), ChaveDesconhecidaError);
    for (const ma of ["2026-10", "202613", "202600", "20261", "", "abcdef"]) {
      await assert.rejects(chaves.getEpochKey(ma), EpocaInvalidaError, `aceitou ${ma}`);
    }
  });

  test(`[${origem}] embrulha com a KEK actual e desembrulha com a que embrulhou`, async () => {
    const chaves = criar();
    const dek = randomBytes(32);
    const { embrulho, kekId } = await chaves.wrapDek(dek, CONTEXTO);
    assert.equal(kekId, "kek-2");
    assert.equal(embrulho.length, 1 + 12 + 16 + 32);
    assert.equal(Buffer.from(embrulho).includes(dek), false, "a DEK está em claro no embrulho");
    assert.ok(Buffer.from(await chaves.unwrapDek(embrulho, kekId, CONTEXTO)).equals(dek));
    // Dois embrulhos da mesma DEK são diferentes (IV novo).
    const outro = await chaves.wrapDek(dek, CONTEXTO);
    assert.equal(Buffer.from(outro.embrulho).equals(Buffer.from(embrulho)), false);
  });

  test(`[${origem}] o embrulho não abre com outro contexto, outra KEK ou um octeto trocado`, async () => {
    const chaves = criar();
    const dek = randomBytes(32);
    const { embrulho, kekId } = await chaves.wrapDek(dek, CONTEXTO);
    await assert.rejects(
      chaves.unwrapDek(embrulho, kekId, Buffer.from("outro-contexto")),
      EmbrulhoInvalidoError,
    );
    await assert.rejects(chaves.unwrapDek(embrulho, "kek-1", CONTEXTO), EmbrulhoInvalidoError);
    await assert.rejects(chaves.unwrapDek(embrulho, "kek-9", CONTEXTO), ChaveDesconhecidaError);
    for (let posicao = 0; posicao < embrulho.length; posicao += 1) {
      const alterado = Buffer.from(embrulho);
      alterado[posicao] = (alterado[posicao] ?? 0) ^ 0x01;
      await assert.rejects(
        chaves.unwrapDek(alterado, kekId, CONTEXTO),
        EmbrulhoInvalidoError,
        `abriu com o octeto ${posicao} alterado`,
      );
    }
    await assert.rejects(
      chaves.unwrapDek(Buffer.from(embrulho).subarray(0, 60), kekId, CONTEXTO),
      EmbrulhoInvalidoError,
    );
    await assert.rejects(chaves.wrapDek(randomBytes(16), CONTEXTO), EmbrulhoInvalidoError);
  });
}

test("uma DEK embrulhada com a KEK anterior continua a abrir depois de a KEK rodar", async () => {
  const antes = new EnvKeyProvider({
    ambiente: "dev",
    env: ambienteDeChaves({ kek: [KEK1] }),
  });
  const dek = randomBytes(32);
  const { embrulho, kekId } = await antes.wrapDek(dek, CONTEXTO);
  assert.equal(kekId, "kek-1");
  const depois = ORIGENS.ambiente?.() as KeyProvider;
  assert.ok(Buffer.from(await depois.unwrapDek(embrulho, kekId, CONTEXTO)).equals(dek));
});

test("uma chave mal formada no cofre é recusada, e a mensagem nunca leva o valor", async () => {
  const material = randomBytes(32).toString("base64");
  const casos: Readonly<Record<string, string>> = {
    "sem versão": material,
    "versão com maiúsculas": `K1:${material}`,
    "versão vazia": `:${material}`,
    "não é base64": "k1:isto não é base64!!",
    "base64 sem enchimento certo": `k1:${material.slice(0, -1)}`,
    "16 octetos": `k1:${randomBytes(16).toString("base64")}`,
    "48 octetos": `k1:${randomBytes(48).toString("base64")}`,
  };
  for (const [caso, valor] of Object.entries(casos)) {
    const chaves = new EnvKeyProvider({
      ambiente: "dev",
      env: ambienteDeChaves({ pesquisa: [valor], kek: [valor] }),
    });
    for (const pedido of [
      () => chaves.getLookupKey("k1"),
      () => chaves.wrapDek(randomBytes(32), CONTEXTO),
    ]) {
      await assert.rejects(
        pedido(),
        (erro: unknown) => {
          assert.ok(erro instanceof ChaveMalFormadaError, `${caso}: ${String(erro)}`);
          assert.equal(erro.message.includes(material), false, `${caso}: a mensagem leva a chave`);
          assert.equal(erro.message.includes(valor), false, `${caso}: a mensagem leva o valor`);
          return true;
        },
        caso,
      );
    }
  }
});

test("actual e anterior com o mesmo kid tornavam o HMAC ambíguo: recusado", async () => {
  const chaves = new EnvKeyProvider({
    ambiente: "dev",
    env: ambienteDeChaves({
      pesquisa: [gerarChaveVersionada("k1"), gerarChaveVersionada("k1")],
    }),
  });
  await assert.rejects(chaves.getLookupKey("k1"), ChaveMalFormadaError);
});

test("uma chave de época mal formada é recusada sem ser repetida", async () => {
  const curta = randomBytes(8).toString("base64");
  const chaves = new EnvKeyProvider({
    ambiente: "dev",
    env: ambienteDeChaves({ epocas: { "202610": curta } }),
  });
  await assert.rejects(chaves.getEpochKey("202610"), (erro: unknown) => {
    assert.ok(erro instanceof ChaveMalFormadaError);
    assert.equal(erro.message.includes(curta), false);
    return true;
  });
});

test("sem a chave no cofre, o erro nomeia o segredo; um cofre selado propaga-se como tal", async () => {
  const vazio = new EnvKeyProvider({ ambiente: "dev", env: {} });
  await assert.rejects(vazio.getLookupKey("k1"), /pepper_contact_hmac/);
  await assert.rejects(vazio.wrapDek(randomBytes(32), CONTEXTO), /kek_contact_dek/);

  const selado = new SecretsKeyProvider({
    segredos: new OpenBaoFakeProvider({ ambiente: "dev", selado: true }),
  });
  await assert.rejects(selado.getLookupKey("k1"), CofreInacessivelError);
  await assert.rejects(selado.getEpochKey("202610"), CofreInacessivelError);
});

// ------------------------------------------------------- arranque em `prod`

function deCofre(ambiente: "dev" | "staging" | "prod"): KeyProvider {
  return new SecretsKeyProvider({
    segredos: new OpenBaoFakeProvider({ ambiente, dados: { pepper_contact_hmac: [K1] } }),
  });
}

test("o provedor diz de onde vêm as chaves", () => {
  const ambiente = new EnvKeyProvider({ ambiente: "dev", env: {} });
  assert.deepEqual([ambiente.nome, ambiente.deAmbiente, ambiente.ambiente], ["secrets:env", true, "dev"]);
  const cofre = deCofre("prod");
  assert.deepEqual([cofre.nome, cofre.deAmbiente, cofre.ambiente], ["secrets:openbao-fake", false, "prod"]);
});

test("critério 9: em KAMBA_ENV=prod, com o KeyProvider de ambiente, o arranque falha", async () => {
  const chaves = new EnvKeyProvider({
    ambiente: "prod",
    env: ambienteDeChaves({ pesquisa: [K1], kek: [KEK1] }),
  });
  assert.throws(() => exigirKeyProviderDeCofre(chaves, { KAMBA_ENV: "prod" }), (erro: unknown) => {
    assert.ok(erro instanceof KeyProviderDeAmbienteError);
    assert.equal(erro.provedor, "secrets:env");
    assert.match(erro.message, /prod/);
    return true;
  });
  // E não há outra porta de entrada: o serviço só se obtém por `arrancar`.
  await assert.rejects(
    Identidade.arrancar({ chaves, env: { KAMBA_ENV: "prod" } }),
    KeyProviderDeAmbienteError,
  );
  await assert.rejects(
    Identidade.arrancar({ chaves, env: { KAMBA_ENV: " prod " } }),
    KeyProviderDeAmbienteError,
  );
});

test("em prod, com as chaves no cofre, arranca", async () => {
  assert.equal(exigirKeyProviderDeCofre(deCofre("prod"), { KAMBA_ENV: "prod" }), "prod");
  assert.ok(
    (await Identidade.arrancar({ chaves: deCofre("prod"), env: { KAMBA_ENV: "prod" } })) instanceof
      Identidade,
  );
});

test("fora de prod, o KeyProvider de ambiente arranca", async () => {
  for (const ambiente of ["dev", "staging"] as const) {
    const chaves = new EnvKeyProvider({ ambiente, env: {} });
    assert.equal(exigirKeyProviderDeCofre(chaves, { KAMBA_ENV: ambiente }), ambiente);
    assert.ok((await Identidade.arrancar({ chaves, env: { KAMBA_ENV: ambiente } })) instanceof Identidade);
  }
});

test("KAMBA_ENV em falta ou desconhecida não vale como «não é produção»", async () => {
  const chaves = new EnvKeyProvider({ ambiente: "dev", env: {} });
  for (const env of [{}, { KAMBA_ENV: "" }, { KAMBA_ENV: "production" }, { KAMBA_ENV: "PROD" }]) {
    assert.throws(() => exigirKeyProviderDeCofre(chaves, env), AmbienteDeIdentidadeError);
    await assert.rejects(Identidade.arrancar({ chaves, env }), AmbienteDeIdentidadeError);
  }
});

test("KAMBA_ENV tem de ser o ambiente do provedor: chaves de dev não arrancam em prod", () => {
  // O caso que contornava o critério 9: um provedor de ambiente que diz ser `dev`.
  assert.throws(
    () =>
      exigirKeyProviderDeCofre(new EnvKeyProvider({ ambiente: "dev", env: {} }), {
        KAMBA_ENV: "prod",
      }),
    AmbienteDeIdentidadeError,
  );
  assert.throws(
    () => exigirKeyProviderDeCofre(deCofre("prod"), { KAMBA_ENV: "dev" }),
    AmbienteDeIdentidadeError,
  );
  assert.throws(
    () => exigirKeyProviderDeCofre(deCofre("staging"), { KAMBA_ENV: "prod" }),
    AmbienteDeIdentidadeError,
  );
});

test("sem `env`, lê-se o ambiente do processo", async () => {
  const anterior = process.env.KAMBA_ENV;
  try {
    process.env.KAMBA_ENV = "prod";
    const chaves = new EnvKeyProvider({ ambiente: "prod" });
    assert.throws(() => exigirKeyProviderDeCofre(chaves), KeyProviderDeAmbienteError);
    await assert.rejects(Identidade.arrancar({ chaves }), KeyProviderDeAmbienteError);
  } finally {
    if (anterior === undefined) delete process.env.KAMBA_ENV;
    else process.env.KAMBA_ENV = anterior;
  }
});

// ------------------------------------------------------------------ utilitários

test("a época de um instante é o mês em UTC", () => {
  assert.equal(epocaDe(new Date("2026-10-12T10:00:00Z")), "202610");
  // 31 de Outubro às 23:30 de Luanda (UTC+1) ainda é Outubro em UTC…
  assert.equal(epocaDe(new Date("2026-10-31T23:30:00+01:00")), "202610");
  // …e 1 de Novembro às 00:30 de Luanda também: a época vira à meia-noite UTC.
  assert.equal(epocaDe(new Date("2026-11-01T00:30:00+01:00")), "202610");
  assert.equal(epocaDe(new Date("2026-11-01T00:00:00Z")), "202611");
  assert.equal(epocaDe(new Date("2027-01-01T00:00:00Z")), "202701");
  assert.throws(() => epocaDe(new Date("isto não é uma data")), EpocaInvalidaError);
  assert.throws(() => epocaDe("2026-10" as unknown as Date), EpocaInvalidaError);
});

test("forma da época e do kid", () => {
  assert.ok(epocaValida("202610"));
  for (const ma of ["202613", "2026-10", "20261", 202610, null]) assert.equal(epocaValida(ma), false);
  for (const bom of ["k1", "2026-10", "kek_1.a", "a".repeat(63)]) assert.ok(kidValido(bom));
  for (const mau of ["", "K1", "-k1", "k 1", "a".repeat(64), "k/1", 1, null]) {
    assert.equal(kidValido(mau), false);
  }
});

test("gerarChaveVersionada dá a forma que o provedor lê, com 32 octetos novos", async () => {
  const [um, outro] = [gerarChaveVersionada("k7"), gerarChaveVersionada("k7")];
  assert.match(um, /^k7:[A-Za-z0-9+/]{43}=$/);
  assert.notEqual(um, outro);
  const chaves = new EnvKeyProvider({
    ambiente: "dev",
    env: ambienteDeChaves({ pesquisa: [um] }),
  });
  assert.equal((await chaves.getLookupKey("k7")).length, 32);
  assert.throws(() => gerarChaveVersionada("K7"), ChaveMalFormadaError);
});

/**
 * Comportamento de arranque e janela de tolerância (KAM-010).
 *
 * Cobre, caso a caso, o critério de aceitação: «um serviço sem segredo
 * obrigatório falha ao arrancar com mensagem que nomeia o segredo (nunca o
 * valor); em `prod`, se o cofre estiver inacessível no arranque, o serviço não
 * arranca; depois do arranque mantém o último valor conhecido durante 15 min».
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ArranqueAbortadoError,
  Secrets,
  TTL_ULTIMO_VALOR_MS,
} from "../src/secrets/arranque.ts";
import { CofreInacessivelError, SecretAusenteError } from "../src/secrets/port.ts";
import { EnvSecretProvider, nomeDaVariavel } from "../src/secrets/env.ts";
import { OpenBaoFakeProvider } from "../src/secrets/openbao-fake.ts";

/** Relógio de mentira, em milissegundos, que só avança quando se manda. */
function relogio(inicio = 1_000_000) {
  let t = inicio;
  return { agora: () => t, avancar: (ms: number) => (t += ms) };
}

const OBRIGATORIOS = ["meta_app_secret", "meta_verify_token"] as const;

function envCom(valores: Readonly<Record<string, string>>): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [ref, valor] of Object.entries(valores)) env[nomeDaVariavel(ref)] = valor;
  return env;
}

test("arranca quando todos os obrigatórios existem", async () => {
  const secrets = await Secrets.arrancar({
    servico: "gwy",
    provider: new EnvSecretProvider({
      ambiente: "dev",
      env: envCom({
        meta_app_secret: "valor-actual-de-teste",
        meta_verify_token: "valor-unico-de-teste",
      }),
    }),
    obrigatorios: OBRIGATORIOS,
  });
  assert.equal(secrets.provedor, "env");
  assert.equal(secrets.ambiente, "dev");
  assert.ok(secrets.eObrigatorio("meta_app_secret"));
  assert.equal(await secrets.get("meta_app_secret"), "valor-actual-de-teste");
});

test("sem segredo obrigatório não arranca, e a mensagem nomeia TODOS os que faltam", async () => {
  await assert.rejects(
    () =>
      Secrets.arrancar({
        servico: "gwy",
        provider: new EnvSecretProvider({ ambiente: "dev", env: {} }),
        obrigatorios: OBRIGATORIOS,
      }),
    (erro: unknown) => {
      assert.ok(erro instanceof ArranqueAbortadoError);
      assert.equal(erro.servico, "gwy");
      assert.deepEqual([...erro.segredos], ["meta_app_secret", "meta_verify_token"]);
      // Um reinício por segredo em falta é a forma mais cara de descobrir uma
      // configuração incompleta.
      assert.match(erro.message, /meta_app_secret, meta_verify_token/);
      return true;
    },
  );
});

test("a mensagem de arranque nomeia o segredo e nunca o valor", async () => {
  const valor = "valor-que-nao-pode-aparecer-em-lado-nenhum";
  try {
    await Secrets.arrancar({
      servico: "gwy",
      // O primeiro existe, o segundo não: o erro tem de nomear o segundo sem
      // deixar escapar o primeiro.
      provider: new EnvSecretProvider({
        ambiente: "dev",
        env: envCom({ meta_app_secret: valor }),
      }),
      obrigatorios: OBRIGATORIOS,
    });
    assert.fail("devia ter abortado");
  } catch (erro) {
    assert.ok(erro instanceof ArranqueAbortadoError);
    assert.match(erro.message, /meta_verify_token/);
    assert.ok(!erro.message.includes(valor), "o valor apareceu na mensagem");
    assert.ok(!(erro.stack ?? "").includes(valor), "o valor apareceu no stack");
  }
});

test("variável definida mas vazia conta como ausente", async () => {
  // `KAMBA_SECRET_X=` é um erro de configuração que se parece com um segredo
  // definido; assinar pedidos com a chave vazia é pior do que não arrancar.
  await assert.rejects(
    () =>
      Secrets.arrancar({
        servico: "gwy",
        provider: new EnvSecretProvider({
          ambiente: "dev",
          env: { ...envCom({ meta_verify_token: "valor-unico-de-teste" }), [nomeDaVariavel("meta_app_secret")]: "   " },
        }),
        obrigatorios: OBRIGATORIOS,
      }),
    (erro: unknown) => {
      assert.ok(erro instanceof ArranqueAbortadoError);
      assert.deepEqual([...erro.segredos], ["meta_app_secret"]);
      return true;
    },
  );
});

test("em prod, cofre inacessível no arranque ⇒ não arranca", async () => {
  const selado = new OpenBaoFakeProvider({
    ambiente: "prod",
    dados: { meta_app_secret: ["valor-actual-de-teste"] },
    selado: true,
  });
  await assert.rejects(
    () =>
      Secrets.arrancar({
        servico: "gwy",
        provider: selado,
        obrigatorios: ["meta_app_secret"],
      }),
    (erro: unknown) => {
      assert.ok(erro instanceof ArranqueAbortadoError);
      assert.match(erro.message, /cofre inacessível/);
      // Nada de valores, e nada de segredos nomeados: nem se chegou a pedir.
      assert.deepEqual([...erro.segredos], []);
      return true;
    },
  );
});

test("fora de prod, cofre inacessível no arranque avisa — e aborta ao não conseguir ler", async () => {
  const avisos: string[] = [];
  const selado = new OpenBaoFakeProvider({
    ambiente: "staging",
    dados: { meta_app_secret: ["valor-actual-de-teste"] },
    selado: true,
  });
  await assert.rejects(
    () =>
      Secrets.arrancar({
        servico: "gwy",
        provider: selado,
        obrigatorios: ["meta_app_secret"],
        aviso: (m) => avisos.push(m),
      }),
    (erro: unknown) => {
      assert.ok(erro instanceof ArranqueAbortadoError);
      // Aborta igualmente, mas por uma razão melhor: nomeia o segredo que não
      // conseguiu carregar.
      assert.match(erro.message, /cofre inacessível ao carregar/);
      assert.deepEqual([...erro.segredos], ["meta_app_secret"]);
      return true;
    },
  );
  assert.equal(avisos.length, 1);
  assert.match(avisos[0] ?? "", /a continuar em staging/);
});

test("a janela são 15 minutos, e é esse o valor por omissão", () => {
  assert.equal(TTL_ULTIMO_VALOR_MS, 900_000);
});

test("depois do arranque, serve o último valor conhecido dentro da janela", async () => {
  const { agora, avancar } = relogio();
  const avisos: string[] = [];
  const cofre = new OpenBaoFakeProvider({
    ambiente: "prod",
    dados: { meta_app_secret: ["valor-anterior-de-teste", "valor-actual-de-teste"] },
  });
  const secrets = await Secrets.arrancar({
    servico: "gwy",
    provider: cofre,
    obrigatorios: ["meta_app_secret"],
    agora,
    aviso: (m) => avisos.push(m),
  });

  cofre.selar();

  // Ao segundo 1: serve.
  avancar(1_000);
  assert.deepEqual(await secrets.getRing("meta_app_secret"), [
    "valor-actual-de-teste",
    "valor-anterior-de-teste",
  ]);

  // Um segundo antes do fim da janela: ainda serve.
  avancar(TTL_ULTIMO_VALOR_MS - 2_000);
  assert.equal(await secrets.get("meta_app_secret"), "valor-actual-de-teste");

  // No limite exacto: deixa de servir. O limite é `>=` e não `>` de propósito —
  // uma janela de 15 minutos que serve ao minuto 15 tem 15 minutos e um tique.
  avancar(1_000);
  await assert.rejects(() => secrets.get("meta_app_secret"), CofreInacessivelError);

  // E o aviso saiu em cada vez que a cache foi usada, com a idade, sem o valor.
  assert.equal(avisos.length, 2);
  for (const aviso of avisos) {
    assert.match(aviso, /último valor conhecido de meta_app_secret/);
    assert.ok(!aviso.includes("valor-actual-de-teste"));
  }

  // E recupera assim que o cofre volta.
  cofre.destrancar();
  assert.equal(await secrets.get("meta_app_secret"), "valor-actual-de-teste");
});

test("a janela cobre indisponibilidade, não revogação", async () => {
  // Se a cache tapasse também o segredo apagado, revogar um token comprometido
  // deixaria de o desactivar durante quinze minutos — e revogar é a acção que
  // tem de ser imediata (`docs/tecnica/08` §10).
  const { agora, avancar } = relogio();
  const env: Record<string, string> = envCom({ meta_app_secret: "valor-actual-de-teste" });
  const secrets = await Secrets.arrancar({
    servico: "gwy",
    provider: new EnvSecretProvider({ ambiente: "prod", env }),
    obrigatorios: ["meta_app_secret"],
    agora,
  });
  delete env[nomeDaVariavel("meta_app_secret")];
  avancar(1_000);
  await assert.rejects(() => secrets.get("meta_app_secret"), SecretAusenteError);
});

test("um segredo nunca lido não tem último valor conhecido", async () => {
  // A janela não é um cofre alternativo: só cobre o que já se leu uma vez.
  const cofre = new OpenBaoFakeProvider({
    ambiente: "prod",
    dados: {
      meta_app_secret: ["valor-actual-de-teste"],
      pepper_contact_hmac: ["pepper-de-teste"],
    },
  });
  const secrets = await Secrets.arrancar({
    servico: "gwy",
    provider: cofre,
    obrigatorios: ["meta_app_secret"],
  });
  cofre.selar();
  await assert.rejects(() => secrets.get("pepper_contact_hmac"), CofreInacessivelError);
});

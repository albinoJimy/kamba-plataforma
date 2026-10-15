/**
 * Um caso negativo por regra (KAM-010).
 *
 * A suite de contrato prova que as três implementações concordam. Esta prova
 * que cada **regra** recusa o que tem de recusar — que é a parte que costuma
 * ficar sem teste, porque ninguém escreve por acidente um teste de uma coisa
 * que não deve acontecer.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AmbienteErradoError,
  CofreInacessivelError,
  SecretAusenteError,
  SecretRefInvalidaError,
  type SecretProvider,
  anel,
  familiaDaRef,
  isAmbiente,
  validarRef,
} from "../src/secrets/port.ts";
import { EnvSecretProvider, PREFIXO, nomeDaVariavel } from "../src/secrets/env.ts";
import { OpenBaoFakeProvider } from "../src/secrets/openbao-fake.ts";
import {
  A_CONFIRMAR,
  DopplerSecretProvider,
  type Transporte,
  interpretarDescargaPlana,
} from "../src/secrets/doppler.ts";

const transporteOk = (corpo: string): Transporte => async () => ({ status: 200, corpo });

function doppler(opcoes: {
  ambiente?: "dev" | "staging" | "prod";
  config?: string;
  token?: string;
  transporte?: Transporte;
  configDaResposta?: (corpo: string) => string | null;
}) {
  return new DopplerSecretProvider({
    ambiente: opcoes.ambiente ?? "prod",
    projecto: "kamba",
    config: opcoes.config ?? opcoes.ambiente ?? "prod",
    tokenServico: opcoes.token ?? "token-de-teste-nao-e-um-segredo",
    transporte: opcoes.transporte ?? transporteOk("{}"),
    ttlDescargaMs: 0,
    ...(opcoes.configDaResposta === undefined
      ? {}
      : { configDaResposta: opcoes.configDaResposta }),
  });
}

// --- Regra: forma da referência -------------------------------------------

test("regra: uma referência não pode ter maiúsculas, espaços nem família vazia", () => {
  for (const ref of [
    "",
    "ab",
    "META_APP_SECRET",
    "meta app secret",
    "/so-instancia",
    "meta_app_secret/",
    "meta_app_secret/com espaço",
    "9comeca_por_digito",
    "x".repeat(300),
  ]) {
    assert.throws(() => validarRef(ref), SecretRefInvalidaError, `aceitou ${JSON.stringify(ref)}`);
  }
  assert.equal(validarRef("meta_app_secret"), "meta_app_secret");
  assert.equal(validarRef("meta_client_token/7f3cAb-9.x:1"), "meta_client_token/7f3cAb-9.x:1");
});

test("regra: a mensagem de referência inválida diz o comprimento, não o conteúdo", () => {
  // Se alguém passar um **valor** onde devia passar uma referência, o valor não
  // pode sair pela mensagem de erro.
  const valorPorEngano = "um-valor-que-alguem-passou-por-engano-em-vez-da-referencia";
  try {
    validarRef(valorPorEngano);
    assert.fail("devia ter recusado");
  } catch (erro) {
    assert.ok(erro instanceof SecretRefInvalidaError);
    assert.ok(!erro.message.includes(valorPorEngano));
    assert.match(erro.message, new RegExp(`${valorPorEngano.length} caracteres`));
  }
});

test("familiaDaRef corta na primeira barra; anel converte a tupla", () => {
  assert.equal(familiaDaRef("meta_app_secret"), "meta_app_secret");
  assert.equal(familiaDaRef("meta_client_token/7f3cAb"), "meta_client_token");
  assert.deepEqual(anel(["a", null]), { actual: "a", anterior: null });
  assert.ok(isAmbiente("prod"));
  assert.ok(!isAmbiente("producao"));
  assert.ok(!isAmbiente(3));
});

// --- Regra: nome da variável de ambiente ----------------------------------

test("regra: a instância mantém a caixa, para que dois tenants não colidam", () => {
  // Se a instância subisse a maiúsculas, `…/7f3cab` e `…/7F3CAB` designariam a
  // mesma variável — e um tenant leria o token de outro. Este é o teste que
  // transforma esse raciocínio em regressão.
  assert.notEqual(
    nomeDaVariavel("meta_client_token/7f3cab"),
    nomeDaVariavel("meta_client_token/7F3CAB"),
  );
  assert.equal(nomeDaVariavel("meta_app_secret"), `${PREFIXO}META_APP_SECRET`);
  assert.equal(
    nomeDaVariavel("meta_client_token/7f3cAb-9.x"),
    `${PREFIXO}META_CLIENT_TOKEN__7f3cAb_9_x`,
  );
});

test("regra: o Env trata vazio e só-espaços como ausência", async () => {
  const provider = new EnvSecretProvider({
    ambiente: "dev",
    env: {
      [`${PREFIXO}META_APP_SECRET`]: "",
      [`${PREFIXO}META_VERIFY_TOKEN`]: "   ",
    },
  });
  await assert.rejects(() => provider.get("meta_app_secret"), SecretAusenteError);
  await assert.rejects(() => provider.getRing("meta_verify_token"), SecretAusenteError);
  await assert.rejects(() => provider.versions("meta_app_secret"), SecretAusenteError);
});

test("regra: o Env não serve um anterior vazio como se fosse uma versão", async () => {
  const provider = new EnvSecretProvider({
    ambiente: "dev",
    env: {
      [`${PREFIXO}META_APP_SECRET`]: "valor-actual-de-teste",
      [`${PREFIXO}META_APP_SECRET_ANTERIOR`]: "",
    },
  });
  assert.deepEqual(await provider.getRing("meta_app_secret"), ["valor-actual-de-teste", null]);
  assert.deepEqual(await provider.versions("meta_app_secret"), ["actual"]);
});

// --- Regra: cofre selado --------------------------------------------------

test("regra: um cofre selado não é um segredo ausente", async () => {
  const cofre = new OpenBaoFakeProvider({
    ambiente: "staging",
    dados: { meta_app_secret: ["valor-actual-de-teste"] },
    selado: true,
  });
  await assert.rejects(() => cofre.get("meta_app_secret"), CofreInacessivelError);
  cofre.destrancar();
  assert.equal(await cofre.get("meta_app_secret"), "valor-actual-de-teste");
});

test("regra: escrever no fake não é escrever pela porta", () => {
  const cofre = new OpenBaoFakeProvider({ ambiente: "dev" });

  // O fake cumpre a porta inteira...
  const porta: SecretProvider = cofre;
  for (const metodo of ["get", "getRing", "versions", "health"] as const) {
    assert.equal(typeof porta[metodo], "function");
  }
  assert.equal(porta.nome, "openbao-fake");
  assert.equal(porta.ambiente, "dev");

  // ...e `escrever` fica **fora** dela: existe na classe concreta, para montar
  // cenários, e não no tipo que os serviços recebem. Se um dia entrar na porta,
  // a linha abaixo deixa de dar erro e o `@ts-expect-error` falha a verificação
  // de tipos — que é como esta decisão volta a ser tomada de propósito.
  // @ts-expect-error -- `escrever` não pertence a `SecretProvider`.
  void porta.escrever;
  assert.equal(typeof cofre.escrever, "function");
});

// --- Regra: ambiente do cofre --------------------------------------------

test("regra: configuração de staging contra um processo de prod é recusada na construção", () => {
  // **Esta é a metade da regra que se consegue provar sem conta Doppler.** A
  // outra metade — o lado do servidor recusar um *service token* de `staging`
  // apresentado ao projecto `prod` — exige três projectos reais e fica por
  // satisfazer neste ticket.
  try {
    doppler({ ambiente: "prod", config: "staging" });
    assert.fail("devia ter recusado");
  } catch (erro) {
    assert.ok(erro instanceof AmbienteErradoError);
    assert.equal(erro.esperado, "prod");
    assert.equal(erro.obtido, "staging");
    assert.match(erro.message, /recusado/);
  }
  // E o caminho inverso também: `prod` apresentado a um processo de `staging`.
  assert.throws(() => doppler({ ambiente: "staging", config: "prod" }), AmbienteErradoError);
});

test("regra: se a resposta identificar a configuração servida, uma diferente é recusada", async () => {
  const provider = doppler({
    ambiente: "prod",
    config: "prod",
    transporte: transporteOk(JSON.stringify({ config: "staging" })),
    configDaResposta: (corpo) => {
      const lido = JSON.parse(corpo) as { config?: string };
      return lido.config ?? null;
    },
  });
  await assert.rejects(() => provider.get("meta_app_secret"), AmbienteErradoError);
  // Está declarado porque é condicional: saber se a resposta real traz esta
  // informação é NÃO VERIFICADO.
  assert.match(A_CONFIRMAR.identificacaoDaConfig, /NÃO|se a resposta identifica/);
});

// --- Regra: credenciais e transporte -------------------------------------

test("regra: service token vazio não constrói um provedor", () => {
  assert.throws(() => doppler({ token: "   " }), CofreInacessivelError);
});

test("regra: 401 e 403 dizem o estado e o projecto, nunca o corpo", async () => {
  for (const status of [401, 403]) {
    const corpoSensivel = "{\"messages\":[\"token revogado\"],\"segredo\":\"nao-devia-sair\"}";
    const provider = doppler({ transporte: async () => ({ status, corpo: corpoSensivel }) });
    await assert.rejects(
      () => provider.get("meta_app_secret"),
      (erro: unknown) => {
        assert.ok(erro instanceof CofreInacessivelError);
        assert.match(erro.message, new RegExp(`HTTP ${status}`));
        assert.match(erro.message, /kamba\/prod/);
        assert.ok(!erro.message.includes("nao-devia-sair"));
        return true;
      },
    );
  }
});

test("regra: qualquer outro estado HTTP não leva o corpo na mensagem", async () => {
  const provider = doppler({
    transporte: async () => ({ status: 503, corpo: "{\"valor\":\"nao-devia-sair\"}" }),
  });
  await assert.rejects(
    () => provider.health(),
    (erro: unknown) => {
      assert.ok(erro instanceof CofreInacessivelError);
      assert.equal(erro.message, "cofre inacessível (provedor doppler): HTTP 503");
      return true;
    },
  );
});

test("regra: um corpo que não é JSON, ou não é objecto, é cofre inacessível", async () => {
  for (const corpo of ["isto-nao-e-json", "[]", "\"texto\"", "null"]) {
    const provider = doppler({ transporte: transporteOk(corpo) });
    await assert.rejects(
      () => provider.health(),
      (erro: unknown) => {
        assert.ok(erro instanceof CofreInacessivelError, `aceitou ${corpo}`);
        assert.ok(!erro.message.includes(corpo));
        return true;
      },
    );
  }
});

test("regra: um transporte que explode não deixa escapar a sua mensagem", async () => {
  class ErroDeRede extends Error {
    override readonly name = "ErroDeRede";
  }
  const provider = doppler({
    transporte: async () => {
      throw new ErroDeRede("connect ECONNREFUSED 10.0.0.1:443 token=nao-devia-sair");
    },
  });
  await assert.rejects(
    () => provider.health(),
    (erro: unknown) => {
      assert.ok(erro instanceof CofreInacessivelError);
      // Só o **nome** da classe do erro atravessa: a mensagem de uma biblioteca
      // de rede pode trazer URL, cabeçalhos ou credenciais.
      assert.equal(erro.message, "cofre inacessível (provedor doppler): transporte falhou: ErroDeRede");
      assert.ok(!erro.message.includes("nao-devia-sair"));
      return true;
    },
  );
});

test("regra: a interpretação por omissão ignora valores que não são texto", () => {
  // Fica documentado o que a suposição NÃO VERIFICADA faz com uma resposta
  // aninhada: ignora-a, em vez de inventar uma travessia.
  const mapa = interpretarDescargaPlana(
    JSON.stringify({ A: "um", B: 2, C: null, D: { raw: "aninhado" } }),
  );
  assert.deepEqual(mapa, { A: "um" });
  assert.match(A_CONFIRMAR.resposta, /objecto plano/);
});

test("regra: o adaptador reutiliza a descarga dentro do TTL", async () => {
  let chamadas = 0;
  const provider = new DopplerSecretProvider({
    ambiente: "dev",
    projecto: "kamba",
    config: "dev",
    tokenServico: "token-de-teste-nao-e-um-segredo",
    transporte: async () => {
      chamadas += 1;
      return { status: 200, corpo: JSON.stringify({ [`${PREFIXO}META_APP_SECRET`]: "v" }) };
    },
    ttlDescargaMs: 60_000,
    agora: () => 1_000,
  });
  await provider.get("meta_app_secret");
  await provider.get("meta_app_secret");
  await provider.health();
  // Um pedido por segredo multiplicaria por vinte os acessos a um SaaS que o
  // `E4` §5 marca como risco de dependência.
  assert.equal(chamadas, 1);
});

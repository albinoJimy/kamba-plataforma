/**
 * O anel de chaves e a rotação (KAM-072): unidade do anel, do rotador, da
 * idade, da separação por ambiente e da re-cifra dos *tokens* de cliente.
 *
 * **Nenhuma chave deste ficheiro é literal.** Todas saem do `gerarValor()` em
 * tempo de execução: o *gate* 9 não tem nada a ver, e nenhum valor fica no
 * repositório. Os oráculos dos HMAC são calculados com o `node:crypto`
 * directamente, não com o módulo sob ensaio.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { describe, it } from "node:test";

import {
  type Anel,
  AnelInexistenteError,
  AnelJaIniciadoError,
  ChavePartilhadaEntreAmbientesError,
  ChaveVaziaError,
  CofreEmMemoria,
  DIA_MS,
  KidDoAnelInvalidoError,
  KidRepetidoError,
  LIMIAR_DE_ALERTA,
  type RegistoDeRotacao,
  RegistoEmMemoria,
  RotacaoConcorrenteError,
  Rotador,
  amostras,
  anelInicial,
  assinar,
  chavesVivas,
  estadoDa,
  gerarValor,
  idadesDosSegredos,
  janelaDe,
  novoKid,
  recifrarToken,
  revogarAnterior,
  rodar,
  valoresVivos,
  verificar,
  verificarSeparacaoDeAmbientes,
} from "../src/keyring/index.ts";
import { cifrarToken, decifrarToken, kidDoCriptograma } from "../src/onboarding/cifra.ts";
import { EnvSecretProvider } from "../src/secrets/env.ts";

const T0 = new Date("2026-11-16T10:00:00.000Z");
const HORA = 3_600_000;

function mais(base: Date, ms: number): Date {
  return new Date(base.getTime() + ms);
}

function hmac(dados: Uint8Array, chave: string): Buffer {
  return createHmac("sha256", chave).update(dados).digest();
}

const DADOS = new TextEncoder().encode('{"evento":"ensaio"}');

// --- O anel ------------------------------------------------------------------

describe("keyring/anel: verify(any) e sign(current)", () => {
  const k1 = { kid: "k1", valor: gerarValor() };
  const k2 = { kid: "k2", valor: gerarValor() };

  it("durante a janela verifica com a actual e com a anterior, e diz qual acertou", () => {
    const anel = rodar(anelInicial(k1), k2, T0, 7 * DIA_MS);
    const agora = mais(T0, HORA);
    assert.deepEqual(verificar(anel, DADOS, hmac(DADOS, k2.valor), agora), { valida: true, kid: "k2" });
    assert.deepEqual(verificar(anel, DADOS, hmac(DADOS, k1.valor), agora), { valida: true, kid: "k1" });
    assert.deepEqual(valoresVivos(anel, agora), [k2.valor, k1.valor]);
  });

  it("no fim exacto da janela a anterior já não verifica", () => {
    const anel = rodar(anelInicial(k1), k2, T0, 7 * DIA_MS);
    const fim = mais(T0, 7 * DIA_MS);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, k1.valor), mais(fim, -1)).valida, true);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, k1.valor), fim).valida, false);
    assert.deepEqual(chavesVivas(anel, fim).map((c) => c.kid), ["k2"]);
  });

  it("revogada a anterior, rejeita-a mesmo dentro da janela", () => {
    const anel = revogarAnterior(rodar(anelInicial(k1), k2, T0, 7 * DIA_MS));
    assert.equal(anel.anterior, null);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, k1.valor), mais(T0, HORA)).valida, false);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, k2.valor), mais(T0, HORA)).valida, true);
  });

  it("assina sempre com a actual", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    const { kid, mac } = assinar(anel, DADOS);
    assert.equal(kid, "k2");
    assert.deepEqual(mac, hmac(DADOS, k2.valor));
  });

  it("recusa uma chave de terceiros, um MAC curto e um MAC vazio", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, gerarValor()), T0).valida, false);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, k2.valor).subarray(0, 31), T0).valida, false);
    assert.equal(verificar(anel, DADOS, new Uint8Array(0), T0).valida, false);
  });

  it("um byte alterado nos dados recusa", () => {
    const anel = anelInicial(k1);
    const mac = hmac(DADOS, k1.valor);
    const alterado = new Uint8Array(DADOS);
    alterado[0] = (alterado[0] ?? 0) ^ 1;
    assert.equal(verificar(anel, alterado, mac, T0).valida, false);
  });

  it("um kid nunca volta: nem o da anterior, nem o da actual com outro valor", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    assert.throws(() => rodar(anel, { kid: "k1", valor: gerarValor() }, T0, DIA_MS), KidRepetidoError);
    assert.throws(() => rodar(anel, { kid: "k2", valor: gerarValor() }, T0, DIA_MS), KidRepetidoError);
  });

  it("rodar para a versão actual com o mesmo valor devolve o mesmo anel (idempotência)", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    assert.equal(rodar(anel, { kid: "k2", valor: k2.valor }, mais(T0, HORA), DIA_MS), anel);
  });

  it("recusa kid mal formado, chave vazia e janela negativa — sem repetir o valor", () => {
    const valor = gerarValor();
    const erro = (() => {
      try {
        anelInicial({ kid: "Com Espaço", valor });
      } catch (e) {
        return e as Error;
      }
      return undefined;
    })();
    assert.ok(erro instanceof KidDoAnelInvalidoError);
    assert.ok(!erro.message.includes(valor));
    assert.throws(() => anelInicial({ kid: "k1", valor: "  " }), ChaveVaziaError);
    assert.throws(() => rodar(anelInicial(k1), k2, T0, -1), RangeError);
  });

  it("novoKid: a data e oito caracteres de base32 aleatórios", () => {
    const vistos = new Set<string>();
    for (let i = 0; i < 200; i += 1) {
      const kid = novoKid(T0);
      assert.match(kid, /^20261116\.[a-z2-7]{8}$/);
      vistos.add(kid);
    }
    assert.ok(vistos.size > 190, "o sufixo é aleatório");
  });
});

// --- O rotador ---------------------------------------------------------------

function montar(relogio: { agora: Date }, registo: RegistoDeRotacao = new RegistoEmMemoria()) {
  const cofre = new CofreEmMemoria();
  const rotador = new Rotador({ cofre, registo, actor: "seguranca", agora: () => relogio.agora });
  return { cofre, registo, rotador };
}

describe("keyring/rotacao: rotate, revogar, emergência e registo", () => {
  it("rotate deixa a anterior viva até ao fim da janela do segredo, e revogarSeVencida retira-a", async () => {
    const relogio = { agora: T0 };
    const { cofre, rotador } = montar(relogio);
    const k1 = { kid: "k1", valor: gerarValor() };
    const k2 = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", k1);
    assert.deepEqual(await rotador.rotate("meta_app_secret", k2), { mudou: true, kid: "k2" });

    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.equal(anel.anteriorAte?.getTime(), T0.getTime() + 7 * DIA_MS);

    relogio.agora = mais(T0, 7 * DIA_MS - 1);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, false);
    relogio.agora = mais(T0, 7 * DIA_MS);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, true);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).anterior, null);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, false);
  });

  it("as janelas por omissão: 7 dias para a Meta, 1 para o facilitador", () => {
    assert.equal(janelaDe("meta_app_secret"), 7 * DIA_MS);
    assert.equal(janelaDe("proxypay_api_key"), DIA_MS);
  });

  it("cada acção fica no registo com o identificador e a hora, e NUNCA o valor", async () => {
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const { rotador } = montar(relogio, registo);
    const valores = [gerarValor(), gerarValor(), gerarValor()];
    await rotador.iniciar("proxypay_api_key", { kid: "k1", valor: valores[0] as string });
    relogio.agora = mais(T0, HORA);
    await rotador.rotate("proxypay_api_key", { kid: "k2", valor: valores[1] as string });
    relogio.agora = mais(T0, 2 * HORA);
    await rotador.revogar("proxypay_api_key");
    relogio.agora = mais(T0, 3 * HORA);
    await rotador.emergencia("proxypay_api_key", { kid: "k3", valor: valores[2] as string });

    const todas = registo.todas();
    assert.deepEqual(
      todas.map((e) => [e.accao, e.kid, e.kidAnterior, e.em.toISOString(), e.actor]),
      [
        ["rotacao", "k1", null, "2026-11-16T10:00:00.000Z", "seguranca"],
        ["rotacao", "k2", "k1", "2026-11-16T11:00:00.000Z", "seguranca"],
        ["revogacao", "k2", "k1", "2026-11-16T12:00:00.000Z", "seguranca"],
        ["emergencia", "k3", "k2", "2026-11-16T13:00:00.000Z", "seguranca"],
      ],
    );
    const serializado = JSON.stringify(todas);
    for (const valor of valores) {
      assert.ok(!serializado.includes(valor), "um valor de segredo entrou no registo");
      // Nem em base64url, nem em hexadecimal: as duas formas em que um valor
      // costuma escapar sem ser reconhecido.
      assert.ok(!serializado.includes(Buffer.from(valor, "base64").toString("hex")));
      assert.ok(!serializado.includes(Buffer.from(valor, "base64").toString("base64url")));
    }
  });

  it("rotate repetido com a mesma versão não roda outra vez nem duplica o registo", async () => {
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const { cofre, rotador } = montar(relogio, registo);
    const k1 = { kid: "k1", valor: gerarValor() };
    const k2 = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", k1);
    await rotador.rotate("meta_app_secret", k2);
    const antes = await cofre.ler("meta_app_secret");
    relogio.agora = mais(T0, HORA);
    assert.deepEqual(await rotador.rotate("meta_app_secret", k2), { mudou: false, kid: "k2" });
    assert.equal(await cofre.ler("meta_app_secret"), antes, "a janela não recomeça");
    assert.equal(registo.todas().length, 2);
    assert.deepEqual(await rotador.iniciar("meta_app_secret", k2), { mudou: false, kid: "k2" });
    await assert.rejects(rotador.iniciar("meta_app_secret", { kid: "k9", valor: gerarValor() }), AnelJaIniciadoError);
  });

  it("uma rotação que caiu entre o cofre e o registo repara-se repetindo-a", async () => {
    const relogio = { agora: T0 };
    const fiel = new RegistoEmMemoria();
    let falhar = false;
    const registo: RegistoDeRotacao = {
      gravar: async (e) => {
        if (falhar) throw new Error("registo em baixo");
        await fiel.gravar(e);
      },
      entradas: (s) => fiel.entradas(s),
    };
    const { cofre, rotador } = montar(relogio, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const k2 = { kid: "k2", valor: gerarValor() };
    falhar = true;
    await assert.rejects(rotador.rotate("meta_app_secret", k2), /registo em baixo/);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).actual.kid, "k2", "o cofre já rodou");
    falhar = false;
    assert.deepEqual(await rotador.rotate("meta_app_secret", k2), { mudou: false, kid: "k2" });
    assert.deepEqual(fiel.todas().map((e) => [e.accao, e.kid]), [["rotacao", "k1"], ["rotacao", "k2"]]);
    await rotador.rotate("meta_app_secret", k2);
    assert.equal(fiel.todas().length, 2, "a terceira repetição não regista outra vez");
  });

  it("duas rotações concorrentes: uma ganha, a outra recebe RotacaoConcorrenteError", async () => {
    const relogio = { agora: T0 };
    const { cofre, rotador } = montar(relogio);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const lido = (await cofre.ler("meta_app_secret")) as Anel;
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    await assert.rejects(
      cofre.escrever("meta_app_secret", rodar(lido, { kid: "k3", valor: gerarValor() }, T0, 0), lido.actual.kid),
      RotacaoConcorrenteError,
    );
  });

  it("emergência: a comprometida deixa de verificar no mesmo passo, sem janela", async () => {
    const relogio = { agora: T0 };
    const { cofre, rotador } = montar(relogio);
    const comprometida = { kid: "k1", valor: gerarValor() };
    const nova = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", comprometida);
    await rotador.emergencia("meta_app_secret", nova);
    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.equal(anel.anterior, null);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, comprometida.valor), T0).valida, false);
    assert.equal(verificar(anel, DADOS, hmac(DADOS, nova.valor), T0).valida, true);
  });

  it("emergência repetida depois de uma rotação planeada retira a anterior que ficou viva", async () => {
    const relogio = { agora: T0 };
    const { cofre, rotador } = montar(relogio);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const k2 = { kid: "k2", valor: gerarValor() };
    await rotador.rotate("meta_app_secret", k2);
    await rotador.emergencia("meta_app_secret", k2);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).anterior, null);
  });

  it("recusa segredos sem anel e ids fora da forma do inventário", async () => {
    const { rotador } = montar({ agora: T0 });
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k1", valor: gerarValor() }), AnelInexistenteError);
    await assert.rejects(rotador.revogar("meta_app_secret"), AnelInexistenteError);
    await assert.rejects(rotador.iniciar("Meta-App", { kid: "k1", valor: gerarValor() }), RangeError);
    assert.throws(() => new Rotador({ cofre: new CofreEmMemoria(), registo: new RegistoEmMemoria(), actor: " " }), RangeError);
  });
});

// --- A idade -----------------------------------------------------------------

describe("keyring/idade: secret_age_days e o limiar de 80%", () => {
  it("o estado fecha nos limites: 80% exacto já alerta, 100% exacto já venceu", () => {
    assert.equal(LIMIAR_DE_ALERTA, 0.8);
    assert.equal(estadoDa(71.99, 90), "ok");
    assert.equal(estadoDa(72, 90), "a_expirar");
    assert.equal(estadoDa(89.99, 90), "a_expirar");
    assert.equal(estadoDa(90, 90), "vencido");
    assert.equal(estadoDa(null, 90), "sem_registo");
    assert.equal(estadoDa(10, null), "por_evento");
  });

  it("a idade conta da última rotação, e uma revogação não a rejuvenesce", async () => {
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const { rotador } = montar(relogio, registo);
    await rotador.iniciar("proxypay_api_key", { kid: "k1", valor: gerarValor() });
    relogio.agora = mais(T0, 10 * DIA_MS);
    await rotador.rotate("proxypay_api_key", { kid: "k2", valor: gerarValor() });
    relogio.agora = mais(T0, 11 * DIA_MS);
    await rotador.revogar("proxypay_api_key");

    const agora = mais(T0, 10 * DIA_MS + 72 * DIA_MS);
    const idades = await idadesDosSegredos(
      [
        { segredo: "proxypay_api_key", rotacaoDias: 90 },
        { segredo: "meta_app_secret", rotacaoDias: 182 },
        { segredo: "meta_pin_2fa", rotacaoDias: null },
      ],
      registo,
      agora,
    );
    assert.deepEqual(idades, [
      { segredo: "proxypay_api_key", idadeDias: 72, prazoDias: 90, estado: "a_expirar" },
      { segredo: "meta_app_secret", idadeDias: null, prazoDias: 182, estado: "sem_registo" },
      { segredo: "meta_pin_2fa", idadeDias: null, prazoDias: null, estado: "por_evento" },
    ]);
    assert.deepEqual(amostras(idades), [
      { nome: "secret_rotation_period_days", etiquetas: { segredo: "proxypay_api_key" }, valor: 90 },
      { nome: "secret_age_days", etiquetas: { segredo: "proxypay_api_key" }, valor: 72 },
      { nome: "secret_rotation_period_days", etiquetas: { segredo: "meta_app_secret" }, valor: 182 },
    ]);
  });

  it("um prazo não positivo é erro de configuração", async () => {
    await assert.rejects(
      idadesDosSegredos([{ segredo: "proxypay_api_key", rotacaoDias: 0 }], new RegistoEmMemoria(), T0),
      RangeError,
    );
  });
});

// --- A separação por ambiente --------------------------------------------------

describe("keyring/separacao: chaves distintas por ambiente (critério 8)", () => {
  function provedor(ambiente: "staging" | "prod", segredos: Record<string, string>): EnvSecretProvider {
    return new EnvSecretProvider({ ambiente, env: segredos });
  }

  it("falha se a chave Meta de prod estiver em staging, e a mensagem não leva o valor", async () => {
    const deProd = gerarValor();
    const prod = provedor("prod", {
      KAMBA_SECRET_META_APP_SECRET: deProd,
      KAMBA_SECRET_PROXYPAY_API_KEY: gerarValor(),
    });
    const staging = provedor("staging", {
      KAMBA_SECRET_META_APP_SECRET: deProd,
      KAMBA_SECRET_PROXYPAY_API_KEY: gerarValor(),
    });
    const erro = await verificarSeparacaoDeAmbientes([prod, staging]).then(
      () => undefined,
      (e: unknown) => e,
    );
    assert.ok(erro instanceof ChavePartilhadaEntreAmbientesError);
    assert.equal(erro.ref, "meta_app_secret");
    assert.deepEqual(erro.ambientes, ["prod", "staging"]);
    assert.ok(!erro.message.includes(deProd));
  });

  it("falha se a chave do facilitador de prod for a ANTERIOR do anel de staging", async () => {
    const deProd = gerarValor();
    const prod = provedor("prod", { KAMBA_SECRET_PROXYPAY_API_KEY: deProd });
    const staging = provedor("staging", {
      KAMBA_SECRET_PROXYPAY_API_KEY: gerarValor(),
      KAMBA_SECRET_PROXYPAY_API_KEY_ANTERIOR: deProd,
    });
    await assert.rejects(verificarSeparacaoDeAmbientes([prod, staging]), ChavePartilhadaEntreAmbientesError);
  });

  it("passa com chaves distintas, e um segredo ausente num ambiente não é violação", async () => {
    const prod = provedor("prod", {
      KAMBA_SECRET_META_APP_SECRET: gerarValor(),
      KAMBA_SECRET_PROXYPAY_API_KEY: gerarValor(),
    });
    const staging = provedor("staging", { KAMBA_SECRET_META_APP_SECRET: gerarValor() });
    await verificarSeparacaoDeAmbientes([prod, staging]);
  });
});

// --- A re-cifra dos tokens de cliente ------------------------------------------

describe("keyring/tokens: rodar a KEK mantém a leitura e não muda o token (critério 4)", () => {
  const TENANT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const OUTRO = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

  it("durante a janela lê sem re-cifrar; re-cifrado, lê depois de revogar a anterior", () => {
    const token = `EAAG${gerarValor()}`;
    const kek1 = { kid: "k1", valor: gerarValor() };
    const kek2 = { kid: "k2", valor: gerarValor() };
    const antigo = cifrarToken(kek1.valor, kek1.kid, TENANT, token);

    const rodado = rodar(anelInicial(kek1), kek2, T0, DIA_MS);
    assert.equal(decifrarToken({ k1: kek1.valor, k2: kek2.valor }, TENANT, antigo), token);

    const { criptograma, mudou } = recifrarToken(rodado, TENANT, antigo);
    assert.equal(mudou, true);
    assert.equal(kidDoCriptograma(criptograma), "k2");

    const revogado = revogarAnterior(rodado);
    assert.equal(decifrarToken({ k2: kek2.valor }, TENANT, criptograma), token, "o token não mudou");
    assert.throws(() => recifrarToken(revogado, TENANT, antigo), /não está no anel/);
  });

  it("é idempotente, e um criptograma com o kid certo e conteúdo alterado não passa", () => {
    const kek = { kid: "k2", valor: gerarValor() };
    const anel = anelInicial(kek);
    const c = cifrarToken(kek.valor, kek.kid, TENANT, `EAAG${gerarValor()}`);
    assert.deepEqual(recifrarToken(anel, TENANT, c), { criptograma: c, mudou: false });

    const bytes = Buffer.from(c, "base64");
    bytes[bytes.length - 1] = (bytes[bytes.length - 1] ?? 0) ^ 1;
    assert.throws(() => recifrarToken(anel, TENANT, bytes.toString("base64")), /autenticação falhou/);
  });

  it("a re-cifra mantém o criptograma preso ao tenant", () => {
    const kek1 = { kid: "k1", valor: gerarValor() };
    const kek2 = { kid: "k2", valor: gerarValor() };
    const antigo = cifrarToken(kek1.valor, kek1.kid, TENANT, `EAAG${gerarValor()}`);
    const { criptograma } = recifrarToken(rodar(anelInicial(kek1), kek2, T0, DIA_MS), TENANT, antigo);
    assert.throws(() => decifrarToken({ k2: kek2.valor }, OUTRO, criptograma), /autenticação falhou/);
  });
});

/**
 * O anel de chaves e a rotação (KAM-072): unidade do anel, do rotador, da
 * idade, da separação por ambiente e da re-cifra dos *tokens* de cliente.
 *
 * **Nenhuma chave deste ficheiro é literal.** Todas saem do `gerarValor()` em
 * tempo de execução: o *gate* 9 não tem nada a ver, e nenhum valor fica no
 * repositório. Os oráculos dos HMAC são calculados com o `node:crypto`
 * directamente; a verificação é a do consumidor real (`assinaturaValida`, do
 * GWY), alimentada pela lista que o anel dá.
 */

import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { describe, it } from "node:test";

import { PREFIXO_DA_ASSINATURA, assinaturaValida } from "../src/entrada/assinatura.ts";
import {
  ACCAO_DE_REVOGAR,
  ACCAO_DE_RODAR,
  type Anel,
  AnelInexistenteError,
  AuditoriaDeRotacaoSql,
  AnelJaIniciadoError,
  ChavePartilhadaEntreAmbientesError,
  ChaveVaziaError,
  type ClienteSqlDeAuditoria,
  type CofreDeAneis,
  CofreEmMemoria,
  DIA_MS,
  JanelaAbertaError,
  KidDoAnelInvalidoError,
  KidJaUsadoError,
  KidRepetidoError,
  LIMIAR_DE_ALERTA,
  type RegistoDeRotacao,
  RegistoEmMemoria,
  RotacaoConcorrenteError,
  Rotador,
  SQL_AUDITAR_ROTACAO,
  ValorRepetidoError,
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
  resumoDaAccao,
  revogarAnterior,
  rodar,
  valoresVivos,
  verificarSeparacaoDeAmbientes,
} from "../src/keyring/index.ts";
import { cifrarToken, decifrarToken, kidDoCriptograma } from "../src/onboarding/cifra.ts";
import { EnvSecretProvider } from "../src/secrets/env.ts";
import { CofreInacessivelError, type SecretProvider } from "../src/secrets/port.ts";

const T0 = new Date("2026-11-16T10:00:00.000Z");
const HORA = 3_600_000;

function mais(base: Date, ms: number): Date {
  return new Date(base.getTime() + ms);
}

function hmac(dados: Uint8Array, chave: string): Buffer {
  return createHmac("sha256", chave).update(dados).digest();
}

const DADOS = new TextEncoder().encode('{"evento":"ensaio"}');

/** O cabeçalho que a Meta mandaria, assinado com `chave`. */
function cabecalho(chave: string): string {
  return `${PREFIXO_DA_ASSINATURA}${hmac(DADOS, chave).toString("hex")}`;
}

/** O GWY aceitaria este corpo, com o anel em `agora`? */
function aceita(anel: Anel, chave: string, agora: Date): boolean {
  return assinaturaValida(DADOS, cabecalho(chave), valoresVivos(anel, agora));
}

// --- O anel ------------------------------------------------------------------

describe("keyring/anel: as versões vivas e sign(current)", () => {
  const k1 = { kid: "k1", valor: gerarValor() };
  const k2 = { kid: "k2", valor: gerarValor() };

  it("durante a janela o consumidor aceita a actual e a anterior", () => {
    const anel = rodar(anelInicial(k1), k2, T0, 7 * DIA_MS);
    const agora = mais(T0, HORA);
    assert.equal(aceita(anel, k2.valor, agora), true);
    assert.equal(aceita(anel, k1.valor, agora), true);
    assert.deepEqual(valoresVivos(anel, agora), [k2.valor, k1.valor]);
  });

  it("no fim exacto da janela a anterior já não é viva", () => {
    const anel = rodar(anelInicial(k1), k2, T0, 7 * DIA_MS);
    const fim = mais(T0, 7 * DIA_MS);
    assert.equal(aceita(anel, k1.valor, mais(fim, -1)), true);
    assert.equal(aceita(anel, k1.valor, fim), false);
    assert.deepEqual(chavesVivas(anel, fim).map((c) => c.kid), ["k2"]);
  });

  it("revogada a anterior, deixa de ser viva mesmo dentro da janela", () => {
    const anel = revogarAnterior(rodar(anelInicial(k1), k2, T0, 7 * DIA_MS));
    assert.equal(anel.anterior, null);
    assert.equal(aceita(anel, k1.valor, mais(T0, HORA)), false);
    assert.equal(aceita(anel, k2.valor, mais(T0, HORA)), true);
  });

  it("assina sempre com a actual", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    const { kid, mac } = assinar(anel, DADOS);
    assert.equal(kid, "k2");
    assert.deepEqual(mac, hmac(DADOS, k2.valor));
  });

  it("uma chave de terceiros não é aceite", () => {
    const anel = rodar(anelInicial(k1), k2, T0, DIA_MS);
    assert.equal(aceita(anel, gerarValor(), T0), false);
  });

  it("dentro do anel um kid não se repete: nem o da anterior, nem o da actual com outro valor", () => {
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

function montar(
  relogio: { agora: Date },
  registo: RegistoDeRotacao = new RegistoEmMemoria(),
  cofre: CofreDeAneis = new CofreEmMemoria(),
) {
  const rotador = new Rotador({ cofre, registo, actor: "seguranca", agora: () => relogio.agora });
  return { cofre, registo, rotador };
}

/** Um registo que falha enquanto `falhar` for verdade. */
function registoQueFalha(): { registo: RegistoDeRotacao; fiel: RegistoEmMemoria; falhar: { sim: boolean } } {
  const fiel = new RegistoEmMemoria();
  const falhar = { sim: false };
  return {
    fiel,
    falhar,
    registo: {
      gravar: async (e) => {
        if (falhar.sim) throw new Error("registo em baixo");
        await fiel.gravar(e);
      },
      entradas: (s) => fiel.entradas(s),
    },
  };
}

describe("keyring/rotacao: rotate, revogar, emergência e registo", () => {
  it("rotate deixa a anterior viva até ao fim da janela do segredo, e revogarSeVencida retira-a", async () => {
    const relogio = { agora: T0 };
    const { cofre, rotador } = montar(relogio);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    assert.deepEqual(await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() }), { mudou: true, kid: "k2" });

    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.equal(anel.anteriorAte?.getTime(), T0.getTime() + 7 * DIA_MS);

    relogio.agora = mais(T0, 7 * DIA_MS - 1);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, false);
    relogio.agora = mais(T0, 7 * DIA_MS);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, true);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).anterior, null);
    assert.equal((await rotador.revogarSeVencida("meta_app_secret")).mudou, false);
  });

  it("as janelas por omissão: 7 dias para a Meta, 1 para o facilitador, e a família decide a instância", () => {
    assert.equal(janelaDe("meta_app_secret"), 7 * DIA_MS);
    assert.equal(janelaDe("proxypay_api_key"), DIA_MS);
    assert.equal(janelaDe("litellm_virtual_key/inst-1"), DIA_MS);
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
        ["inicio", "k1", null, "2026-11-16T10:00:00.000Z", "seguranca"],
        ["rotacao", "k2", "k1", "2026-11-16T11:00:00.000Z", "seguranca"],
        ["revogacao", "k2", "k1", "2026-11-16T12:00:00.000Z", "seguranca"],
        ["emergencia", "k3", "k2", "2026-11-16T13:00:00.000Z", "seguranca"],
      ],
    );
    const serializado = JSON.stringify(todas);
    for (const valor of valores) {
      assert.ok(!serializado.includes(valor), "um valor de segredo entrou no registo");
      // Nem em hexadecimal, nem em base64url: as duas formas em que um valor
      // costuma escapar sem ser reconhecido.
      assert.ok(!serializado.includes(Buffer.from(valor, "base64").toString("hex")));
      assert.ok(!serializado.includes(Buffer.from(valor, "base64").toString("base64url")));
    }
  });

  it("aceita referências por instância, como `<família>/<instância>`, e recusa o que não é referência", async () => {
    const { rotador } = montar({ agora: T0 });
    await rotador.iniciar("litellm_virtual_key/inst-1", { kid: "k1", valor: gerarValor() });
    await assert.rejects(rotador.iniciar("Meta App", { kid: "k1", valor: gerarValor() }), /referência de segredo inválida/);
  });

  it("rotate repetido com a mesma versão não roda outra vez nem duplica o registo", async () => {
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const { cofre, rotador } = montar(relogio, registo);
    const k2 = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await rotador.rotate("meta_app_secret", k2);
    const antes = await cofre.ler("meta_app_secret");
    relogio.agora = mais(T0, HORA);
    assert.deepEqual(await rotador.rotate("meta_app_secret", k2), { mudou: false, kid: "k2" });
    assert.equal(await cofre.ler("meta_app_secret"), antes, "a janela não recomeça");
    assert.equal(registo.todas().length, 2);
    assert.deepEqual(await rotador.iniciar("meta_app_secret", k2), { mudou: false, kid: "k2" });
    await assert.rejects(rotador.iniciar("meta_app_secret", { kid: "k9", valor: gerarValor() }), AnelJaIniciadoError);
  });

  it("um kid nunca volta, nem um de há duas rotações, nem depois de revogado", async () => {
    const relogio = { agora: T0 };
    const { rotador } = montar(relogio);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    await rotador.revogar("meta_app_secret");
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k1", valor: gerarValor() }), KidJaUsadoError);
    await rotador.rotate("meta_app_secret", { kid: "k3", valor: gerarValor() });
    relogio.agora = mais(T0, 8 * DIA_MS);
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k1", valor: gerarValor() }), KidJaUsadoError);
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() }), KidJaUsadoError);
  });

  it("o mesmo valor com outro kid é recusado — também na emergência", async () => {
    const { rotador } = montar({ agora: T0 });
    const comprometida = { kid: "k1", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", comprometida);
    await assert.rejects(
      rotador.emergencia("meta_app_secret", { kid: "k2", valor: comprometida.valor }),
      ValorRepetidoError,
    );
  });

  it("não roda com a anterior viva; vencida a janela, revoga-a primeiro e regista as duas coisas", async () => {
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const { cofre, rotador } = montar(relogio, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    relogio.agora = mais(T0, DIA_MS);
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k3", valor: gerarValor() }), JanelaAbertaError);
    relogio.agora = mais(T0, 7 * DIA_MS);
    await rotador.rotate("meta_app_secret", { kid: "k3", valor: gerarValor() });
    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.deepEqual([anel.actual.kid, anel.anterior?.kid], ["k3", "k2"]);
    assert.deepEqual(
      registo.todas().map((e) => [e.accao, e.kid, e.kidAnterior]),
      [
        ["inicio", "k1", null],
        ["rotacao", "k2", "k1"],
        ["revogacao", "k2", "k1"],
        ["rotacao", "k3", "k2"],
      ],
    );
  });

  it("uma rotação que caiu entre o cofre e o registo repara-se repetindo-a, uma vez só", async () => {
    const relogio = { agora: T0 };
    const { registo, fiel, falhar } = registoQueFalha();
    const { cofre, rotador } = montar(relogio, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const k2 = { kid: "k2", valor: gerarValor() };
    falhar.sim = true;
    await assert.rejects(rotador.rotate("meta_app_secret", k2), /registo em baixo/);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).actual.kid, "k2", "o cofre já rodou");
    falhar.sim = false;
    assert.deepEqual(await rotador.rotate("meta_app_secret", k2), { mudou: false, kid: "k2" });
    await rotador.rotate("meta_app_secret", k2);
    assert.deepEqual(fiel.todas().map((e) => [e.accao, e.kid, e.kidAnterior]), [["inicio", "k1", null], ["rotacao", "k2", "k1"]]);
  });

  it("uma revogação que caiu entre o cofre e o registo repara-se repetindo-a", async () => {
    const relogio = { agora: T0 };
    const { registo, fiel, falhar } = registoQueFalha();
    const { rotador } = montar(relogio, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    falhar.sim = true;
    await assert.rejects(rotador.revogar("meta_app_secret"), /registo em baixo/);
    falhar.sim = false;
    assert.equal((await rotador.revogar("meta_app_secret")).mudou, false);
    await rotador.revogar("meta_app_secret");
    assert.deepEqual(fiel.todas().map((e) => [e.accao, e.kid, e.kidAnterior]).at(-1), ["revogacao", "k2", "k1"]);
    assert.equal(fiel.todas().filter((e) => e.accao === "revogacao").length, 1);
  });

  it("um início que caiu entre o cofre e o registo repara-se repetindo-o", async () => {
    const { registo, fiel, falhar } = registoQueFalha();
    const { rotador } = montar({ agora: T0 }, registo);
    const k1 = { kid: "k1", valor: gerarValor() };
    falhar.sim = true;
    await assert.rejects(rotador.iniciar("meta_app_secret", k1), /registo em baixo/);
    falhar.sim = false;
    await rotador.iniciar("meta_app_secret", k1);
    await rotador.iniciar("meta_app_secret", k1);
    assert.deepEqual(fiel.todas().map((e) => [e.accao, e.kid]), [["inicio", "k1"]]);
  });

  it("uma emergência reparada continua a dizer qual versão estava comprometida", async () => {
    const { registo, fiel, falhar } = registoQueFalha();
    const { rotador } = montar({ agora: T0 }, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const k2 = { kid: "k2", valor: gerarValor() };
    falhar.sim = true;
    await assert.rejects(rotador.emergencia("meta_app_secret", k2), /registo em baixo/);
    falhar.sim = false;
    await rotador.emergencia("meta_app_secret", k2);
    assert.deepEqual(fiel.todas().map((e) => [e.accao, e.kid, e.kidAnterior]).at(-1), ["emergencia", "k2", "k1"]);
  });

  it("revogarSeVencida não retira a anterior de uma rotação que entrou entre a leitura e a escrita", async () => {
    const relogio = { agora: T0 };
    const fiel = new CofreEmMemoria();
    const outro = new Rotador({ cofre: fiel, registo: new RegistoEmMemoria(), actor: "outro", agora: () => relogio.agora });
    await outro.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await outro.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    relogio.agora = mais(T0, 8 * DIA_MS);
    let intercalar = true;
    // O cofre do agendador deixa outro operador rodar depois da leitura.
    const cofre: CofreDeAneis = {
      ler: async (s) => {
        const lido = await fiel.ler(s);
        if (intercalar) {
          intercalar = false;
          await outro.rotate(s, { kid: "k3", valor: gerarValor() });
        }
        return lido;
      },
      escrever: (s, a, e) => fiel.escrever(s, a, e),
    };
    const { rotador } = montar(relogio, new RegistoEmMemoria(), cofre);
    await assert.rejects(rotador.revogarSeVencida("meta_app_secret"), RotacaoConcorrenteError);
    const anel = (await fiel.ler("meta_app_secret")) as Anel;
    assert.deepEqual([anel.actual.kid, anel.anterior?.kid], ["k3", "k2"], "a janela nova do k2 ficou intacta");
  });

  it("duas rotações concorrentes pelo Rotador: uma ganha, a outra recebe RotacaoConcorrenteError", async () => {
    const relogio = { agora: T0 };
    const fiel = new CofreEmMemoria();
    const outro = new Rotador({ cofre: fiel, registo: new RegistoEmMemoria(), actor: "outro", agora: () => relogio.agora });
    await outro.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    let intercalar = true;
    const cofre: CofreDeAneis = {
      ler: (s) => fiel.ler(s),
      escrever: async (s, a, e) => {
        if (intercalar) {
          intercalar = false;
          await outro.rotate(s, { kid: "k2", valor: gerarValor() });
        }
        return fiel.escrever(s, a, e);
      },
    };
    const { rotador } = montar(relogio, new RegistoEmMemoria(), cofre);
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k3", valor: gerarValor() }), RotacaoConcorrenteError);
    assert.equal(((await fiel.ler("meta_app_secret")) as Anel).actual.kid, "k2");
  });

  it("emergência: a comprometida deixa de ser aceite no mesmo passo, sem janela", async () => {
    const { cofre, rotador } = montar({ agora: T0 });
    const comprometida = { kid: "k1", valor: gerarValor() };
    const nova = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar("meta_app_secret", comprometida);
    await rotador.emergencia("meta_app_secret", nova);
    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.equal(anel.anterior, null);
    assert.equal(aceita(anel, comprometida.valor, T0), false);
    assert.equal(aceita(anel, nova.valor, T0), true);
  });

  it("emergência com uma anterior viva: retira as duas, e regista as duas", async () => {
    const registo = new RegistoEmMemoria();
    const { cofre, rotador } = montar({ agora: T0 }, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: gerarValor() });
    await rotador.emergencia("meta_app_secret", { kid: "k3", valor: gerarValor() });
    const anel = (await cofre.ler("meta_app_secret")) as Anel;
    assert.deepEqual([anel.actual.kid, anel.anterior], ["k3", null]);
    assert.deepEqual(
      registo.todas().map((e) => [e.accao, e.kid, e.kidAnterior]).slice(-2),
      [["revogacao", "k2", "k1"], ["emergencia", "k3", "k2"]],
    );
  });

  it("emergência repetida depois de uma rotação planeada retira a anterior que ficou viva", async () => {
    const { cofre, rotador } = montar({ agora: T0 });
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() });
    const k2 = { kid: "k2", valor: gerarValor() };
    await rotador.rotate("meta_app_secret", k2);
    await rotador.emergencia("meta_app_secret", k2);
    assert.equal(((await cofre.ler("meta_app_secret")) as Anel).anterior, null);
  });

  it("recusa segredos sem anel e um rotador sem actor", async () => {
    const { rotador } = montar({ agora: T0 });
    await assert.rejects(rotador.rotate("meta_app_secret", { kid: "k1", valor: gerarValor() }), AnelInexistenteError);
    await assert.rejects(rotador.revogar("meta_app_secret"), AnelInexistenteError);
    await assert.rejects(rotador.revogarSeVencida("meta_app_secret"), AnelInexistenteError);
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

  it("um segredo importado tem a idade da versão, e sem data a idade não se sabe", async () => {
    const registo = new RegistoEmMemoria();
    const { rotador } = montar({ agora: T0 }, registo);
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() }, mais(T0, -170 * DIA_MS));
    await rotador.iniciar("proxypay_api_key", { kid: "k1", valor: gerarValor() });
    const idades = await idadesDosSegredos(
      [
        { segredo: "meta_app_secret", rotacaoDias: 182 },
        { segredo: "proxypay_api_key", rotacaoDias: 90 },
      ],
      registo,
      T0,
    );
    assert.deepEqual(
      idades.map((i) => [i.segredo, i.idadeDias, i.estado]),
      [
        ["meta_app_secret", 170, "a_expirar"],
        ["proxypay_api_key", null, "sem_registo"],
      ],
    );
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

  it("um cofre em baixo não dá verde: o erro propaga", async () => {
    const prod = provedor("prod", { KAMBA_SECRET_META_APP_SECRET: gerarValor() });
    const emBaixo: SecretProvider = {
      nome: "em-baixo",
      ambiente: "staging",
      get: async () => {
        throw new CofreInacessivelError("em-baixo", "ensaio");
      },
      getRing: async () => {
        throw new CofreInacessivelError("em-baixo", "ensaio");
      },
      versions: async () => [],
      health: async () => {
        throw new CofreInacessivelError("em-baixo", "ensaio");
      },
    };
    await assert.rejects(verificarSeparacaoDeAmbientes([prod, emBaixo]), CofreInacessivelError);
  });
});

// --- A re-cifra dos tokens de cliente ------------------------------------------

describe("keyring/tokens: com kid estável, rodar a KEK mantém a leitura e não muda o token (critério 4)", () => {
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

  it("o defeito medido: com o kid posicional do EnvSecretProvider, a rotação parte o token guardado", async () => {
    // É o caminho do `#tokenEmClaro` do `onboarding.ts`: o anel `kid → chave`
    // monta-se com `versions()`, que no Env devolve `actual` e `anterior`.
    const comoOOnboardingLe = async (env: EnvSecretProvider): Promise<Record<string, string>> => {
      const [actual, anterior] = await env.getRing("kek_token_cliente");
      const versoes = await env.versions("kek_token_cliente");
      const anel: Record<string, string> = {};
      if (versoes[0] !== undefined) anel[versoes[0]] = actual;
      if (versoes[1] !== undefined && anterior !== null) anel[versoes[1]] = anterior;
      return anel;
    };
    const kek1 = gerarValor();
    const antes = new EnvSecretProvider({ ambiente: "staging", env: { KAMBA_SECRET_KEK_TOKEN_CLIENTE: kek1 } });
    const [kidAntes] = await antes.versions("kek_token_cliente");
    const guardado = cifrarToken(kek1, kidAntes as string, TENANT, `EAAG${gerarValor()}`);
    const depois = new EnvSecretProvider({
      ambiente: "staging",
      env: { KAMBA_SECRET_KEK_TOKEN_CLIENTE: gerarValor(), KAMBA_SECRET_KEK_TOKEN_CLIENTE_ANTERIOR: kek1 },
    });
    assert.equal(kidAntes, "actual");
    const anelDepois = await comoOOnboardingLe(depois);
    assert.equal(anelDepois.actual === undefined, false, "o rótulo «actual» passou a ser a KEK nova");
    assert.throws(() => decifrarToken(anelDepois, TENANT, guardado), /autenticação falhou/);
  });
});

// --- O audit_log ----------------------------------------------------------------

describe("keyring/auditoria: cada acção no audit_log, com o identificador e a versão, nunca o valor (critério 7)", () => {
  function clienteQueGuarda(): { cliente: ClienteSqlDeAuditoria; pedidos: { texto: string; valores: readonly unknown[] }[] } {
    const pedidos: { texto: string; valores: readonly unknown[] }[] = [];
    return { pedidos, cliente: { query: async (texto, valores) => void pedidos.push({ texto, valores }) } };
  }

  it("rotação, revogação e emergência: a acção, o segredo e a versão certos, pela audit_append da plataforma", async () => {
    const { cliente, pedidos } = clienteQueGuarda();
    const relogio = { agora: T0 };
    const registo = new RegistoEmMemoria();
    const rotador = new Rotador({
      cofre: new CofreEmMemoria(),
      registo,
      auditoria: new AuditoriaDeRotacaoSql(cliente),
      actor: "seguranca",
      agora: () => relogio.agora,
    });
    const valores = [gerarValor(), gerarValor(), gerarValor()];
    await rotador.iniciar("meta_app_secret", { kid: "k1", valor: valores[0] as string });
    await rotador.rotate("meta_app_secret", { kid: "k2", valor: valores[1] as string });
    await rotador.revogar("meta_app_secret");
    await rotador.emergencia("meta_app_secret", { kid: "k3", valor: valores[2] as string });

    assert.ok(pedidos.every((p) => p.texto === SQL_AUDITAR_ROTACAO));
    assert.match(SQL_AUDITAR_ROTACAO, /platform\.audit_append\(NULL, 'staff'/);
    assert.deepEqual(
      pedidos.map((p) => p.valores.slice(0, 4)),
      [
        ["seguranca", ACCAO_DE_RODAR, "meta_app_secret", "k1"],
        ["seguranca", ACCAO_DE_RODAR, "meta_app_secret", "k2"],
        ["seguranca", ACCAO_DE_REVOGAR, "meta_app_secret", "k1"],
        ["seguranca", ACCAO_DE_RODAR, "meta_app_secret", "k3"],
      ],
    );
    assert.deepEqual([ACCAO_DE_RODAR, ACCAO_DE_REVOGAR], ["secret.rotate", "secret.revoke"]);

    // O resumo é dos metadados: nem o valor, nem um resumo dele, em nenhum parâmetro.
    const resumosDosValores = valores.flatMap((v) => [
      createHash("sha256").update(v, "utf8").digest("hex"),
      createHash("sha256").update(Buffer.from(v, "base64")).digest("hex"),
    ]);
    for (const { valores: parametros } of pedidos) {
      const resumo = (parametros[4] as Buffer).toString("hex");
      assert.equal((parametros[4] as Buffer).length, 32);
      assert.ok(!resumosDosValores.includes(resumo), "o payload_hash é o resumo de um valor");
      const emTexto = JSON.stringify(parametros.slice(0, 4));
      for (const valor of valores) assert.ok(!emTexto.includes(valor));
    }
    assert.deepEqual(pedidos[1]?.valores[4], resumoDaAccao(registo.todas()[1] as never));
  });

  it("o audit_log escreve-se antes do registo: um audit_log em baixo não deixa entrada no registo", async () => {
    const registo = new RegistoEmMemoria();
    const rotador = new Rotador({
      cofre: new CofreEmMemoria(),
      registo,
      auditoria: { gravar: async () => Promise.reject(new Error("audit_log em baixo")) },
      actor: "seguranca",
      agora: () => T0,
    });
    await assert.rejects(rotador.iniciar("meta_app_secret", { kid: "k1", valor: gerarValor() }), /audit_log em baixo/);
    assert.equal(registo.todas().length, 0, "sem auditoria, a repetição ainda vê a acção por registar");
  });

  it("uma revogação sem versão retirada não se audita", async () => {
    const { cliente } = clienteQueGuarda();
    await assert.rejects(
      new AuditoriaDeRotacaoSql(cliente).gravar({
        segredo: "meta_app_secret",
        accao: "revogacao",
        kid: "k2",
        kidAnterior: null,
        em: T0,
        criadaEm: null,
        actor: "seguranca",
      }),
      RangeError,
    );
  });
});

/**
 * Ida e volta: o simulador assina, o GWY aceita (KAM-024, critérios 3 e 4).
 *
 * O critério 4 é «a assinatura gerada é aceite pelo GWY de KAM-013 (ida e
 * volta) e rejeitada quando o corpo muda 1 byte». Este ficheiro é essa prova, e
 * vive **no GWY** e não no `tools/meta-sim` por uma razão: quem é posto à prova
 * é o consumidor. Um teste no pacote do simulador afirmava coisas sobre si
 * próprio; aqui o simulador é a entrada e o GWY é o sujeito.
 *
 * ## Porque é que isto é interoperabilidade e não auto-consistência
 *
 * O `assinar` do simulador tem `createHmac` **próprio** e não importa nada do
 * `@kamba/core-ts/entrada` — está escrito na docstring dele porquê. Quem valida
 * aqui é o `assinaturaValida` do `core-ts`, pela via do `createApp`. São duas
 * implementações, e é isso que faz este ficheiro medir alguma coisa: se o
 * simulador assinasse com a função que o GWY usa para validar, a ida e volta
 * ficava verde no dia em que o algoritmo estivesse errado dos dois lados.
 *
 * É a mesma razão por que a *suite* `db/tests_entrada/` calcula a assinatura em
 * Python. Aqui são TypeScript os dois lados, mas o código é independente.
 *
 * ## Sem Redis e sem Postgres
 *
 * `FilasEmMemoria` e um anel de dois textos, como o resto de `webhook.test.ts`.
 * O que se mede é o 401, o 200 e **quantos *jobs* ficaram na fila** — e isso é
 * tudo observável sem contentor nenhum, o que é o que mantém a *suite* offline
 * do critério 8 dentro dos cinco minutos.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { FILA_ENTRADA } from "@kamba/core-ts/entrada";
import { FilasEmMemoria } from "@kamba/core-ts/eventos";
import { Logger } from "@kamba/core-ts/logger";
import {
  CABECALHO,
  Gerador,
  casosAdversos,
  cenarioDe,
  corpoMexido,
  mudarUmByte,
  razoesDeFalha,
  reentregar,
  segredoDeEnsaio,
  serializar,
  todasAsFixtures,
  type Fixture,
} from "@kamba/meta-sim";

import { createApp } from "../src/app.ts";
import { SERVICE } from "../src/meta.ts";
import { CAMINHO } from "../src/webhook.ts";

const SEMENTE = "ida-e-volta-do-kam-024";
const SEGREDO = segredoDeEnsaio(SEMENTE);
const VERIFICACAO = "verify-token-desta-instalacao";

interface Montagem {
  readonly app: ReturnType<typeof createApp>;
  readonly filas: FilasEmMemoria;
}

function montar(): Montagem {
  const filas = new FilasEmMemoria();
  const log = new Logger(SERVICE, {
    destino: { write: () => undefined },
    relogio: () => new Date("2026-10-20T00:00:00.000Z"),
    estrito: true,
  });
  // O anel leva o segredo do simulador **e** um segundo que não é dele: é o que
  // prova que o 200 vem de bater com o primeiro e não de o anel aceitar tudo.
  const app = createApp(log, {
    anel: () => [SEGREDO, "outro-segredo-do-anel"],
    verifyToken: () => VERIFICACAO,
    filas,
    profundidade: () => null,
  });
  return { app, filas };
}

function enviar(
  montagem: Montagem,
  corpo: Uint8Array,
  assinatura: string | undefined,
): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (assinatura !== undefined) headers[CABECALHO] = assinatura;
  return montagem.app.request(CAMINHO, { method: "POST", body: corpo, headers });
}

/** Quantos *jobs* estao na fila de entrada. */
function naFila(montagem: Montagem): number {
  return montagem.filas.contar(FILA_ENTRADA);
}

const FIXTURES = todasAsFixtures(SEMENTE, SEGREDO);

describe("ida e volta: as 26 fixtures sao aceites (criterio 4)", () => {
  it("todas dao 200 e ficam na fila", async () => {
    // Uma por uma e não num lote: o que se quer saber, se falhar, é **qual**.
    const recusadas: string[] = [];
    for (const fixture of FIXTURES) {
      const montagem = montar();
      const resposta = await enviar(montagem, fixture.bytes, fixture.assinatura);
      if (resposta.status !== 200 || naFila(montagem) !== 1) {
        recusadas.push(`${fixture.item.marca} (${resposta.status})`);
      }
    }
    assert.deepEqual(recusadas, []);
    assert.ok(FIXTURES.length >= 26, `${FIXTURES.length} fixtures`);
  });

  it("cada fixture tem um jobId proprio — nenhuma colide com outra", async () => {
    // O `jobId` é o `sha256` dos bytes. Duas *fixtures* com o mesmo `jobId`
    // seriam duas *fixtures* com os mesmos bytes, e a tabela de cobertura
    // estaria a contar a mesma coisa duas vezes.
    const montagem = montar();
    for (const fixture of FIXTURES) {
      await enviar(montagem, fixture.bytes, fixture.assinatura);
    }
    assert.equal(naFila(montagem), FIXTURES.length);
  });
});

describe("1 byte de diferenca da 401 (criterio 4)", () => {
  function primeira(): Fixture {
    const fixture = FIXTURES[0];
    assert.ok(fixture !== undefined);
    return fixture;
  }

  it("o corpo mexido com a assinatura do original: 401 e 0 jobs", async () => {
    const fixture = primeira();
    const montagem = montar();
    const resposta = await enviar(montagem, mudarUmByte(fixture.bytes), fixture.assinatura);
    assert.equal(resposta.status, 401);
    // **Zero** *jobs*: um 401 que enfileirasse era pior do que um 200.
    assert.equal(naFila(montagem), 0);
  });

  it("o corpo mexido continua a ser JSON valido — a recusa e pelos bytes", async () => {
    // Sem isto o teste não distinguia «recusa porque não bate» de «recusa
    // porque é lixo», e a segunda não prova nada sobre a assinatura.
    const mexido = mudarUmByte(primeira().bytes);
    assert.doesNotThrow(() => JSON.parse(Buffer.from(mexido).toString("utf8")));
  });

  it("corpoMexido monta o caso inteiro e o GWY responde o que ele diz", async () => {
    const fixture = primeira();
    const pedido = corpoMexido(fixture.bytes, SEGREDO);
    const montagem = montar();
    const resposta = await enviar(montagem, pedido.bytes, pedido.assinatura);
    assert.equal(resposta.status, pedido.estado);
  });

  it("a mesma fixture serializada com espacos: 401 com a assinatura do compacto", async () => {
    // O **mesmo JSON** com bytes diferentes. Um GWY que normalizasse o corpo
    // antes de verificar aceitava este, e é o defeito que nenhuma *fixture*
    // sozinha apanha.
    const fixture = primeira();
    const espacado = serializar(fixture.corpo, "espacado");
    const montagem = montar();
    assert.equal((await enviar(montagem, espacado, fixture.assinatura)).status, 401);
    assert.equal(naFila(montagem), 0);
  });

  it("sem cabecalho nenhum: 401", async () => {
    const montagem = montar();
    assert.equal((await enviar(montagem, primeira().bytes, undefined)).status, 401);
  });
});

describe("os oito casos adversos contra o GWY (criterio 3)", () => {
  const { canal, quem } = cenarioDe(SEMENTE);
  const CASOS = casosAdversos(new Gerador(SEMENTE), { canal, quem, segredo: SEGREDO });

  for (const caso of CASOS) {
    it(`${caso.nome}: ${caso.pedidos.length} POST(s) com os estados declarados`, async () => {
      const montagem = montar();
      const obtidos: number[] = [];
      for (const pedido of caso.pedidos) {
        obtidos.push((await enviar(montagem, pedido.bytes, pedido.assinatura)).status);
      }
      // O caso **declara** o estado esperado, e o teste lê-o de lá. É o que
      // impede uma *suite* futura de afirmar a resposta errada para um caso
      // cuja resposta certa não é óbvia — ver a nota de `adversos.ts`.
      assert.deepEqual(
        obtidos,
        caso.pedidos.map((p) => p.estado),
        caso.esperado,
      );
    });
  }

  it("corpo_duplicado: dois 200 e UM job", async () => {
    const caso = CASOS.find((c) => c.nome === "corpo_duplicado");
    assert.ok(caso !== undefined);
    const montagem = montar();
    for (const pedido of caso.pedidos) await enviar(montagem, pedido.bytes, pedido.assinatura);
    // O `jobId` é o `sha256` dos bytes, e a fila é idempotente por `jobId`.
    assert.equal(naFila(montagem), 1, caso.esperado);
  });

  it("mesma_mensagem_em_dois_corpos: dois 200 e DOIS jobs", async () => {
    const caso = CASOS.find((c) => c.nome === "mesma_mensagem_em_dois_corpos");
    assert.ok(caso !== undefined);
    const montagem = montar();
    for (const pedido of caso.pedidos) await enviar(montagem, pedido.bytes, pedido.assinatura);
    // Dois, porque os bytes diferem. A deduplicação pelo `wamid` é do *worker*
    // de entrada, contra a base, e está em `db/tests_entrada/`.
    assert.equal(naFila(montagem), 2, caso.esperado);
  });

  it("json_invalido_assinado: 200 e 1 job — o GWY nao faz parse", async () => {
    const caso = CASOS.find((c) => c.nome === "json_invalido_assinado");
    assert.ok(caso !== undefined);
    const montagem = montar();
    const pedido = caso.pedidos[0];
    assert.ok(pedido !== undefined);
    assert.equal((await enviar(montagem, pedido.bytes, pedido.assinatura)).status, 200);
    assert.equal(naFila(montagem), 1, caso.esperado);
  });
});

describe("re-entrega: sete dias de repeticoes dao um job (criterio 6)", () => {
  it("doze entregas do mesmo corpo deixam 1 job na fila", async () => {
    const fixture = FIXTURES[0];
    assert.ok(fixture !== undefined);
    const montagem = montar();

    const relatorio = await reentregar(async () => {
      const resposta = await enviar(montagem, fixture.bytes, fixture.assinatura);
      return resposta.status;
    });

    assert.deepEqual(razoesDeFalha(relatorio), []);
    assert.ok(relatorio.tentativas.length >= 10, `${relatorio.tentativas.length} tentativas`);
    assert.equal(relatorio.aceites, relatorio.tentativas.length);
    // **Um** *job*, depois de sete dias simulados de repetições. É a
    // idempotência que o critério 6 pede, medida contra o GWY a sério.
    assert.equal(naFila(montagem), 1);
  });
});

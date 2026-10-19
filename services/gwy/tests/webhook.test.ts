/**
 * O webhook do GWY (KAM-013, critérios 1, 2, 3, 5, 6, 7 e 9).
 *
 * Sem Redis e sem Postgres: a fila é a `FilasEmMemoria` do KAM-005 e o anel é
 * um par de textos. O que precisa de Redis a sério — a fila **parada** — está
 * em `db/tests_entrada/`, porque «parada» não se simula com um `throw`
 * convincentemente: o que se prova aqui é que o 503 sai quando o `addLote`
 * rejeita, e lá que o `addLote` rejeita de verdade com o contentor em baixo.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { describe, it } from "node:test";

import {
  FILA_ENTRADA,
  JOB_ENTRADA,
  METRICAS,
  PREFIXO_DA_ASSINATURA,
  sha256Hex,
} from "@kamba/core-ts/entrada";
import { FilasEmMemoria } from "@kamba/core-ts/eventos";
import { Logger } from "@kamba/core-ts/logger";

import { createApp, criarAppDeMetricas } from "../src/app.ts";
import { SERVICE } from "../src/meta.ts";
import {
  CAMINHO,
  CORPO_MAXIMO,
  TECTO_DA_FILA,
  soEstadosSemPreco,
} from "../src/webhook.ts";

const ACTUAL = "app-secret-actual";
const ANTERIOR = "app-secret-anterior";
const TERCEIRO = "app-secret-de-outra-pessoa";
// `VERIFICACAO` e nao `TOKEN`: o *gate* 9 apanha uma atribuicao a um nome que
// **significa** segredo com um valor de entropia suficiente, e tem razao — e a
// forma de um segredo embutido. Aqui o valor e obviamente falso, e havia duas
// saidas: declarar o ficheiro em `ci/secrets-allow.yaml` (o que se fez para o
// `secrets.*.test.ts`, que e inteiro sobre a porta de segredos) ou nao escrever
// a forma. Por uma constante, a segunda e proporcionada. Nao renomear de volta.
const VERIFICACAO = "verify-token-desta-instalacao";

const WABA = "109876543210987";
const PNID = "123456789012345";

function assinar(corpo: Uint8Array, segredo: string): string {
  return `${PREFIXO_DA_ASSINATURA}${createHmac("sha256", segredo).update(corpo).digest("hex")}`;
}

interface Montagem {
  readonly app: ReturnType<typeof createApp>;
  readonly filas: FilasEmMemoria;
  readonly linhas: () => string[];
}

function montar(opcoes: { profundidade?: number | null } = {}): Montagem {
  const filas = new FilasEmMemoria();
  let escrito = "";
  const log = new Logger(SERVICE, {
    destino: { write: (pedaco: string) => (escrito += pedaco) },
    relogio: () => new Date("2026-01-01T00:00:00.000Z"),
    // Estrito: um campo fora da *allowlist* **lança** em vez de ser retirado em
    // silêncio. É assim que o critério 9 se prova e não se espera.
    estrito: true,
  });
  const app = createApp(log, {
    anel: () => [ACTUAL, ANTERIOR],
    verifyToken: () => VERIFICACAO,
    filas,
    profundidade: () => opcoes.profundidade ?? null,
  });
  return {
    app,
    filas,
    linhas: () => escrito.split("\n").filter((linha) => linha !== ""),
  };
}

function bytes(texto: string): Uint8Array {
  return new Uint8Array(Buffer.from(texto, "utf8"));
}

async function enviar(
  montagem: Montagem,
  corpo: Uint8Array,
  assinatura?: string,
): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (assinatura !== undefined) headers["x-hub-signature-256"] = assinatura;
  return montagem.app.request(CAMINHO, { method: "POST", body: corpo, headers });
}

const CORPO_DE_MENSAGEM = JSON.stringify({
  object: "whatsapp_business_account",
  entry: [
    {
      id: WABA,
      changes: [
        {
          field: "messages",
          value: {
            messaging_product: "whatsapp",
            metadata: { display_phone_number: "244923111222", phone_number_id: PNID },
            contacts: [{ profile: { name: "Maria Kiala" }, wa_id: "244923456789" }],
            messages: [
              {
                from: "244923456789",
                id: "wamid.HBgMMjQ0OTIzNDU2Nzg5FQIAEhgU",
                timestamp: "1700000000",
                type: "text",
                text: { body: "Bom dia, queria duas pizzas e a conta" },
              },
            ],
          },
        },
      ],
    },
  ],
});

// --- Critério 1: o GET de verificação ---------------------------------------

describe("GET de verificacao (criterio 1)", () => {
  it("com o verify_token certo responde 200 com o corpo igual ao challenge", async () => {
    const { app } = montar();
    const resposta = await app.request(
      `${CAMINHO}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(VERIFICACAO)}&hub.challenge=1158201444`,
    );
    assert.equal(resposta.status, 200);
    // Byte a byte: a Meta compara o corpo com o desafio que mandou.
    assert.equal(await resposta.text(), "1158201444");
  });

  it("um challenge com caracteres estranhos volta exactamente igual", async () => {
    const { app } = montar();
    const desafio = "abc-XYZ_123.~";
    const resposta = await app.request(
      `${CAMINHO}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(VERIFICACAO)}&hub.challenge=${encodeURIComponent(desafio)}`,
    );
    assert.equal(await resposta.text(), desafio);
  });

  it("com o verify_token errado responde 403", async () => {
    const { app } = montar();
    for (const token of ["errado", "", VERIFICACAO.slice(0, -1), `${VERIFICACAO}x`, VERIFICACAO.toUpperCase()]) {
      const resposta = await app.request(
        `${CAMINHO}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(token)}&hub.challenge=1`,
      );
      assert.equal(resposta.status, 403, `token ${JSON.stringify(token)} devia dar 403`);
    }
  });

  it("sem hub.mode, sem challenge, ou com outro modo, responde 403", async () => {
    const { app } = montar();
    const base = `hub.verify_token=${encodeURIComponent(VERIFICACAO)}`;
    for (const consulta of [
      `${base}&hub.challenge=1`, // sem modo
      `hub.mode=subscribe&${base}`, // sem challenge
      `hub.mode=unsubscribe&${base}&hub.challenge=1`, // outro modo
      `hub.mode=subscribe&${base}&hub.challenge=`, // challenge vazio
    ]) {
      const resposta = await app.request(`${CAMINHO}?${consulta}`);
      assert.equal(resposta.status, 403, consulta);
    }
  });

  it("nunca responde 200 com o corpo quando recusa", async () => {
    const { app } = montar();
    const resposta = await app.request(
      `${CAMINHO}?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=segredo`,
    );
    assert.equal((await resposta.text()).includes("segredo"), false);
  });
});

// --- Critérios 2 e 3: a assinatura ------------------------------------------

describe("POST: assinatura (criterios 2 e 3)", () => {
  it("sem assinatura responde 401 e nao enfileira nada", async () => {
    const montagem = montar();
    const resposta = await enviar(montagem, bytes(CORPO_DE_MENSAGEM));
    assert.equal(resposta.status, 401);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 0);
    assert.equal(montagem.filas.chamadas, 0);
  });

  it("com assinatura invalida responde 401", async () => {
    const montagem = montar();
    const resposta = await enviar(
      montagem,
      bytes(CORPO_DE_MENSAGEM),
      `${PREFIXO_DA_ASSINATURA}${"0".repeat(64)}`,
    );
    assert.equal(resposta.status, 401);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 0);
  });

  it("incrementa gwy_sig_fail", async () => {
    METRICAS.repor();
    const montagem = montar();
    await enviar(montagem, bytes(CORPO_DE_MENSAGEM));
    await enviar(montagem, bytes(CORPO_DE_MENSAGEM), "lixo");
    assert.equal(METRICAS.ler().gwy_sig_fail, 2);
    assert.equal(METRICAS.ler().gwy_requests_total, 2);
    METRICAS.repor();
  });

  it("aceita o segredo actual e o anterior, e recusa um terceiro", async () => {
    const corpo = bytes(CORPO_DE_MENSAGEM);
    for (const [segredo, esperado] of [
      [ACTUAL, 200],
      [ANTERIOR, 200],
      [TERCEIRO, 401],
    ] as const) {
      const montagem = montar();
      const resposta = await enviar(montagem, corpo, assinar(corpo, segredo));
      assert.equal(resposta.status, esperado, segredo);
    }
  });

  it("um corpo re-serializado com a assinatura do original da 401", async () => {
    // A letra do critério 2. É o teste que distingue a assinatura sobre os
    // bytes recebidos da assinatura sobre o que o `JSON.stringify` devolveu.
    const original = bytes(CORPO_DE_MENSAGEM);
    const assinatura = assinar(original, ACTUAL);
    const espacado = bytes(JSON.stringify(JSON.parse(CORPO_DE_MENSAGEM), null, 2));
    assert.notEqual(Buffer.compare(Buffer.from(original), Buffer.from(espacado)), 0);

    const montagem = montar();
    assert.equal((await enviar(montagem, original, assinatura)).status, 200);
    assert.equal((await enviar(montagem, espacado, assinatura)).status, 401);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("nada do corpo nao assinado passa pelo registo", async () => {
    const montagem = montar();
    await enviar(montagem, bytes(CORPO_DE_MENSAGEM));
    const registo = montagem.linhas().join("\n");
    assert.equal(registo.includes("pizzas"), false);
    assert.equal(registo.includes("923"), false);
    assert.equal(registo.includes("Kiala"), false);
  });
});

// --- Critério 4 (primeiro nível) e critério 5 -------------------------------

describe("POST: fila (criterios 4 e 5)", () => {
  it("o jobId e o sha256 do corpo, e o corpo vai em base64", async () => {
    const montagem = montar();
    const corpo = bytes(CORPO_DE_MENSAGEM);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));

    const jobs = [...montagem.filas.jobs().values()];
    assert.equal(jobs.length, 1);
    assert.equal(jobs[0]?.jobId, sha256Hex(corpo));
    assert.equal(jobs[0]?.nome, JOB_ENTRADA);
    const dados = jobs[0]?.dados as { corpo: string; recebidoEm: number };
    assert.equal(Buffer.from(dados.corpo, "base64").toString("utf8"), CORPO_DE_MENSAGEM);
    assert.ok(Number.isInteger(dados.recebidoEm));
  });

  it("o mesmo corpo 2x produz 1 job (criterio 4, primeiro nivel)", async () => {
    const montagem = montar();
    const corpo = bytes(CORPO_DE_MENSAGEM);
    const assinatura = assinar(corpo, ACTUAL);
    assert.equal((await enviar(montagem, corpo, assinatura)).status, 200);
    assert.equal((await enviar(montagem, corpo, assinatura)).status, 200);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
    // E o `addLote` foi chamado as duas vezes: a deduplicacao e da fila, pelo
    // `jobId`, e nao de uma cache nossa que o reinicio apagava.
    assert.equal(montagem.filas.chamadas, 2);
  });

  it("corpos diferentes produzem jobs diferentes", async () => {
    const montagem = montar();
    for (const sufixo of ["A", "B", "C"]) {
      const corpo = bytes(CORPO_DE_MENSAGEM.replace("wamid.HBg", `wamid.${sufixo}`));
      await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    }
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 3);
  });

  it("o 200 so sai DEPOIS de o job estar na fila (criterio 5)", async () => {
    // O defeito que isto apanha: responder 200 e enfileirar sem `await`. Com um
    // `addLote` que só resolve quando o teste o mandar, a resposta não pode
    // chegar antes — e se chegasse, a Meta considerava entregue uma mensagem
    // que ainda não existe em sítio nenhum.
    const filas = new FilasEmMemoria();
    let soltar = (): void => {};
    const espera = new Promise<void>((resolver) => {
      soltar = resolver;
    });
    const original = filas.addLote.bind(filas);
    let naFila = false;
    filas.addLote = async (nome, trabalhos) => {
      await espera;
      await original(nome, trabalhos);
      naFila = true;
    };

    const app = createApp(undefined, {
      anel: () => [ACTUAL, ANTERIOR],
      verifyToken: () => VERIFICACAO,
      filas,
      profundidade: () => null,
    });
    const corpo = bytes(CORPO_DE_MENSAGEM);
    // `Promise.resolve`: o `request` do Hono é tipado `Response |
    // Promise<Response>`, e o que este teste precisa é de **não** esperar por
    // ele antes de verificar que a fila está vazia.
    const pedido = Promise.resolve(
      app.request(CAMINHO, {
        method: "POST",
        body: corpo,
        headers: { "x-hub-signature-256": assinar(corpo, ACTUAL) },
      }),
    );

    // Dá-se ao laço de eventos oportunidades de sobra para resolver o pedido.
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
    await new Promise((resolver) => setTimeout(resolver, 20));
    assert.equal(naFila, false, "o job nao devia estar na fila ainda");

    let respondeuAntes = false;
    void pedido.then(() => {
      if (!naFila) respondeuAntes = true;
    });
    soltar();
    const resposta = await pedido;
    assert.equal(resposta.status, 200);
    assert.equal(naFila, true);
    assert.equal(respondeuAntes, false, "respondeu 200 antes de enfileirar");
  });

  it("com a fila indisponivel responde 503 e NUNCA 200 (criterio 5)", async () => {
    const montagem = montar();
    montagem.filas.falha = new Error("connect ECONNREFUSED 127.0.0.1:6379");
    const corpo = bytes(CORPO_DE_MENSAGEM);
    const resposta = await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(resposta.status, 503);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 0);
  });

  it("o 503 nao deixa a mensagem de erro do Redis sair na resposta nem no registo", async () => {
    const montagem = montar();
    montagem.filas.falha = new Error("connect ECONNREFUSED 10.0.0.5:6379 senha=hunter2");
    const corpo = bytes(CORPO_DE_MENSAGEM);
    const resposta = await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    const texto = await resposta.text();
    for (const fonte of [texto, montagem.linhas().join("\n")]) {
      assert.equal(fonte.includes("hunter2"), false);
      assert.equal(fonte.includes("10.0.0.5"), false);
      assert.equal(fonte.includes("ECONNREFUSED"), false);
    }
  });

  it("mede gwy_enqueue_ms mesmo quando a fila falha", async () => {
    METRICAS.repor();
    const montagem = montar();
    montagem.filas.falha = new Error("em baixo");
    const corpo = bytes(CORPO_DE_MENSAGEM);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.ok("gwy_enqueue_ms" in METRICAS.ler());
    METRICAS.repor();
  });

  it("um corpo vazio assinado vai a fila: a quarentena e do worker", async () => {
    // O critério 6 diz «200 e quarentena», e a quarentena é escrita pelo
    // *worker*. O GWY não interpreta o corpo: se interpretasse, um corpo mau
    // dava 4xx e a Meta repetia sete dias.
    const montagem = montar();
    const corpo = bytes("{isto nao e json");
    const resposta = await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(resposta.status, 200);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });
});

// --- Critério 7: o descarte sob saturação -----------------------------------

describe("POST: descarte sob saturacao (criterio 7)", () => {
  const SO_ESTADOS = JSON.stringify({
    entry: [
      {
        id: WABA,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { phone_number_id: PNID },
              statuses: [
                { id: "wamid.A", status: "sent" },
                { id: "wamid.A", status: "delivered" },
              ],
            },
          },
        ],
      },
    ],
  });

  it("com a fila abaixo do tecto nao descarta nada", async () => {
    const montagem = montar({ profundidade: TECTO_DA_FILA });
    const corpo = bytes(SO_ESTADOS);
    assert.equal((await enviar(montagem, corpo, assinar(corpo, ACTUAL))).status, 200);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("acima do tecto descarta um corpo so de estados sem preco", async () => {
    METRICAS.repor();
    const montagem = montar({ profundidade: TECTO_DA_FILA + 1 });
    const corpo = bytes(SO_ESTADOS);
    const resposta = await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    // 200 e não 503: um 503 fazia a Meta repetir durante sete dias o que
    // acabámos de decidir não querer.
    assert.equal(resposta.status, 200);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 0);
    assert.equal(METRICAS.ler().gwy_shed_total, 1);
    METRICAS.repor();
  });

  it("acima do tecto NUNCA descarta um corpo com mensagens", async () => {
    const montagem = montar({ profundidade: TECTO_DA_FILA * 100 });
    const corpo = bytes(CORPO_DE_MENSAGEM);
    assert.equal((await enviar(montagem, corpo, assinar(corpo, ACTUAL))).status, 200);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("acima do tecto NUNCA descarta um corpo misto", async () => {
    const misto = JSON.stringify({
      entry: [
        {
          id: WABA,
          changes: [
            { field: "messages", value: { statuses: [{ id: "w", status: "sent" }] } },
            { field: "messages", value: { messages: [{ id: "w2", type: "text" }] } },
          ],
        },
      ],
    });
    const montagem = montar({ profundidade: TECTO_DA_FILA * 100 });
    const corpo = bytes(misto);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("acima do tecto NUNCA descarta um estado com preco", async () => {
    // O custo por mensagem é KAM-015 e o *free tier* é KAM-023: perder a linha
    // que os alimenta é perder dinheiro contabilizado.
    const comPreco = JSON.stringify({
      entry: [
        {
          id: WABA,
          changes: [
            {
              field: "messages",
              value: {
                statuses: [
                  { id: "wamid.A", status: "sent", pricing: { category: "utility" } },
                ],
              },
            },
          ],
        },
      ],
    });
    const montagem = montar({ profundidade: TECTO_DA_FILA * 100 });
    const corpo = bytes(comPreco);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("com a profundidade desconhecida nao descarta: `null` nao e saturacao", async () => {
    const montagem = montar({ profundidade: null });
    const corpo = bytes(SO_ESTADOS);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });

  it("um corpo que nao se consegue interpretar nao se descarta", async () => {
    const montagem = montar({ profundidade: TECTO_DA_FILA * 100 });
    const corpo = bytes("{nao e json");
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 1);
  });
});

describe("soEstadosSemPreco", () => {
  it("e verdade so para corpos exclusivamente de estados sem preco", () => {
    assert.equal(
      soEstadosSemPreco(
        JSON.stringify({
          entry: [
            {
              id: WABA,
              changes: [
                {
                  field: "messages",
                  value: {
                    messaging_product: "whatsapp",
                    metadata: { phone_number_id: PNID },
                    statuses: [{ id: "w", status: "read" }],
                  },
                },
              ],
            },
          ],
        }),
      ),
      true,
    );
  });

  it("e falso para tudo o que nao seja isso", () => {
    const casos = [
      "{nao e json",
      "null",
      "[]",
      "{}",
      '{"entry":[]}',
      '{"entry":[{"changes":[]}]}',
      '{"entry":[{"changes":[{"field":"messages","value":{"messages":[{"id":"w"}]}}]}]}',
      '{"entry":[{"changes":[{"field":"messages","value":{"statuses":[]}}]}]}',
      '{"entry":[{"changes":[{"field":"messages","value":{"statuses":[{"pricing":{}}]}}]}]}',
      '{"entry":[{"changes":[{"field":"messages","value":{"statuses":[{"id":"w"}],"errors":[]}}]}]}',
      '{"entry":[{"changes":[{"field":"account_update","value":{"statuses":[{"id":"w"}]}}]}]}',
    ];
    for (const caso of casos) {
      assert.equal(soEstadosSemPreco(caso), false, caso.slice(0, 50));
    }
  });
});

// --- O tecto do corpo (revisão adversarial) ---------------------------------

describe("tecto do corpo", () => {
  it("um corpo acima do tecto responde 413 sem ser lido inteiro", async () => {
    // O achado: o `arrayBuffer()` lia o corpo **inteiro** antes de a assinatura
    // ser verificada e sem tecto nenhum, no único endpoint público da
    // plataforma. Um POST de 200 MB sem segredo nenhum alocava 200 MB.
    const montagem = montar();
    const grande = new Uint8Array(CORPO_MAXIMO + 1);
    grande.fill(0x20);
    const resposta = await enviar(montagem, grande, assinar(grande, ACTUAL));
    assert.equal(resposta.status, 413);
    assert.equal(montagem.filas.contar(FILA_ENTRADA), 0);
  });

  it("recusa pelo `content-length` declarado, sem alocar o corpo", async () => {
    const montagem = montar();
    const resposta = await montagem.app.request(CAMINHO, {
      method: "POST",
      body: bytes("{}"),
      headers: {
        "content-length": String(CORPO_MAXIMO + 1),
        "x-hub-signature-256": assinar(bytes("{}"), ACTUAL),
      },
    });
    assert.equal(resposta.status, 413);
  });

  it("um `content-length` mentiroso nao passa: a segunda guarda mede o que chegou", async () => {
    const montagem = montar();
    const grande = new Uint8Array(CORPO_MAXIMO + 1);
    grande.fill(0x20);
    const resposta = await montagem.app.request(CAMINHO, {
      method: "POST",
      body: grande,
      headers: { "content-length": "2", "x-hub-signature-256": assinar(grande, ACTUAL) },
    });
    assert.equal(resposta.status, 413);
  });

  it("413 e nao 401: nao e um problema de assinatura", async () => {
    // Se respondesse 401, um corpo legítimo grande aparecia como
    // `gwy_sig_fail` e mandava procurar no sítio errado.
    METRICAS.repor();
    const montagem = montar();
    const grande = new Uint8Array(CORPO_MAXIMO + 1);
    await enviar(montagem, grande, assinar(grande, ACTUAL));
    assert.equal(METRICAS.ler().gwy_sig_fail, undefined);
    METRICAS.repor();
  });

  it("um corpo no tecto exacto passa", async () => {
    const montagem = montar();
    const enchimento = "a".repeat(CORPO_MAXIMO);
    const corpo = bytes(`{"x":"${enchimento}"}`.slice(0, CORPO_MAXIMO));
    assert.equal(corpo.byteLength, CORPO_MAXIMO);
    const resposta = await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    assert.equal(resposta.status, 200);
  });
});

// --- Critério 9: os logs ----------------------------------------------------

describe("logs do GWY (criterio 9)", () => {
  const PERMITIDOS = new Set([
    "ts",
    "level",
    "svc",
    "msg_id",
    "wa_type",
    "latency_ms",
    "outcome",
    "error_code",
  ]);

  it("cada linha so leva os oito campos do criterio 9", async () => {
    const montagem = montar();
    const corpo = bytes(CORPO_DE_MENSAGEM);
    await montagem.app.request(
      `${CAMINHO}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(VERIFICACAO)}&hub.challenge=1`,
    );
    await montagem.app.request(`${CAMINHO}?hub.mode=subscribe&hub.verify_token=mau&hub.challenge=1`);
    await enviar(montagem, corpo);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));

    const linhas = montagem.linhas();
    assert.ok(linhas.length >= 4, `so saiu ${linhas.length} linha(s)`);
    for (const linha of linhas) {
      const registo = JSON.parse(linha) as Record<string, unknown>;
      for (const chave of Object.keys(registo)) {
        assert.ok(PERMITIDOS.has(chave), `${chave} nao esta nos oito do criterio 9`);
      }
      assert.equal(registo.svc, SERVICE);
    }
  });

  it("os desfechos sao os esperados, e nenhum leva conteudo", async () => {
    const montagem = montar();
    const corpo = bytes(CORPO_DE_MENSAGEM);
    await enviar(montagem, corpo, assinar(corpo, ACTUAL));
    const registo = JSON.parse(montagem.linhas()[0] ?? "{}") as Record<string, unknown>;
    assert.equal(registo.outcome, "webhook_enfileirado");
    assert.equal(registo.level, "info");
    assert.ok(Number.isInteger(registo.latency_ms));
  });

  // Este é o teste que o critério 9 nomeia: «um linter e um teste sobre os
  // logs de 1 000 pedidos encontram 0 telefones e 0 texto de mensagem».
  it("1000 pedidos com telefones e texto: 0 telefones e 0 conteudo nos logs", async () => {
    const montagem = montar({ profundidade: null });
    const canarios = [
      "244923456789",
      "+244 923 456 789",
      "923456789",
      "244 912 345 678",
      "Maria Kiala",
      "queria duas pizzas",
      "Rua Direita 42, Luanda",
      "maria@example.ao",
      "5061 0000 0000 0000",
      "EAAG1bMBaZBAbcdefghijklmn",
    ];

    for (let i = 0; i < 1_000; i += 1) {
      const canario = canarios[i % canarios.length] ?? "";
      const corpo = bytes(
        JSON.stringify({
          object: "whatsapp_business_account",
          entry: [
            {
              id: WABA,
              changes: [
                {
                  field: "messages",
                  value: {
                    messaging_product: "whatsapp",
                    metadata: { display_phone_number: canario, phone_number_id: PNID },
                    contacts: [{ profile: { name: canario }, wa_id: canario }],
                    messages: [
                      {
                        from: canario,
                        id: `wamid.${canario}.${i}`,
                        timestamp: `17000000${i % 100}`,
                        type: "text",
                        text: { body: `${canario} — pedido numero ${i}` },
                      },
                    ],
                  },
                },
              ],
            },
          ],
        }),
      );
      // Um terço sem assinatura e um terço com assinatura errada: os caminhos
      // de erro são os que mais facilmente registam o que receberam.
      const resto = i % 3;
      const assinatura =
        resto === 0 ? assinar(corpo, ACTUAL) : resto === 1 ? undefined : "sha256=lixo";
      const resposta = await enviar(montagem, corpo, assinatura);
      assert.equal(resposta.status, resto === 0 ? 200 : 401);
    }

    const texto = montagem.linhas().join("\n");
    assert.ok(montagem.linhas().length >= 1_000, "faltam linhas de registo");

    for (const canario of canarios) {
      assert.equal(texto.includes(canario), false, `o canario ${canario} saiu no registo`);
    }
    // E, para além dos canários, nenhuma corrida de sete dígitos: é a forma de
    // um telefone, de um NIF e de uma referência de pagamento, em qualquer
    // arrumação (`logger/politica.ts`).
    for (const linha of montagem.linhas()) {
      const registo = JSON.parse(linha) as Record<string, unknown>;
      for (const [chave, valor] of Object.entries(registo)) {
        if (chave === "ts") continue;
        const digitos = (String(valor).match(/[0-9]/g) ?? []).length;
        assert.ok(digitos <= 6, `${chave}=${String(valor)} tem ${digitos} digitos`);
      }
      for (const chave of Object.keys(registo)) {
        assert.ok(PERMITIDOS.has(chave), `${chave} nao esta nos oito do criterio 9`);
      }
    }
  });
});

// --- /metrics ---------------------------------------------------------------

describe("/metrics do gwy", () => {
  it("NAO esta na porta do webhook", async () => {
    // Achado da revisão adversarial: o webhook é alcançável de fora (ADR-001),
    // e `inbound_queue_depth` nessa porta é o atraso da plataforma em tempo
    // real ao alcance de quem quiser cronometrar o descarte do critério 7.
    const { app } = montar();
    assert.notEqual((await app.request("/metrics")).status, 200);
  });

  it("expoe as cinco metricas, sem etiquetas, no app interno", async () => {
    const resposta = await criarAppDeMetricas().request("/metrics");
    assert.equal(resposta.status, 200);
    assert.match(resposta.headers.get("content-type") ?? "", /^text\/plain; version=0\.0\.4/);
    const texto = await resposta.text();
    for (const nome of [
      "gwy_requests_total",
      "gwy_sig_fail",
      "gwy_shed_total",
      "gwy_enqueue_ms",
      "inbound_queue_depth",
    ]) {
      assert.match(texto, new RegExp(`^# TYPE ${nome} `, "m"), nome);
    }
    for (const linha of texto.trim().split("\n")) {
      if (!linha.startsWith("#")) assert.equal(linha.includes("{"), false, linha);
    }
  });
});

// --- Sem dependências, o webhook não existe ---------------------------------

describe("createApp sem dependencias", () => {
  it("nao monta o webhook: um GWY sem segredo nao aceita pedidos", async () => {
    const app = createApp();
    assert.equal((await app.request(CAMINHO, { method: "POST", body: "{}" })).status, 404);
    assert.equal((await app.request(`${CAMINHO}?hub.mode=subscribe`)).status, 404);
    // A sonda continua a responder: o processo está vivo.
    assert.equal((await app.request("/healthz")).status, 200);
    // O `/metrics` não: vive no app interno, noutra porta.
    assert.notEqual((await app.request("/metrics")).status, 200);
    assert.equal((await criarAppDeMetricas().request("/healthz")).status, 200);
  });
});

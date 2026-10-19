/**
 * O registo e o encaminhamento de um corpo (KAM-013, critérios 4, 6 e 8).
 *
 * Com um cliente SQL **falso** que imita a única propriedade de que estes
 * testes dependem — `UNIQUE (kind, event_key)` com `ON CONFLICT DO NOTHING` —,
 * e não a base inteira. O que a base tem de provar prova-se contra um
 * PostgreSQL real em `db/tests_entrada/`: aqui prova-se a **decisão**, lá
 * prova-se o **esquema**, e as duas partes do critério 4 precisam das duas.
 *
 * O que estes testes prendem:
 *
 * - JSON inválido vai à quarentena e **não lança** (critério 6).
 * - O mesmo `wamid` em dois corpos diferentes dá uma linha (critério 4).
 * - A janela entre registar e encaminhar: um evento registado e não
 *   encaminhado é encaminhado na entrega seguinte, em vez de desaparecer.
 * - Cada `kind` vai ao método certo do encaminhador (critério 8), e um
 *   `statuses` **nunca** vai ao `chr`.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";

import { ESCADA_DO_CONSUMIDOR } from "../src/eventos/consumo.ts";
import { REPETICAO } from "../src/eventos/filas.ts";
import { sha256Hex } from "../src/entrada/assinatura.ts";
import { AJUSTES_DO_TRABALHADOR } from "../src/entrada/trabalhador.ts";
import type { TrabalhoDeEntrada } from "../src/entrada/contrato.ts";
import type { EventoDeEntrada } from "../src/entrada/explosao.ts";
import {
  EVENTOS_MAXIMOS_POR_CORPO,
  PAYLOAD_MAXIMO,
  type ClienteSql,
  type Encaminhador,
  tratarCorpo,
} from "../src/entrada/registo.ts";

const WABA = "109876543210987";
const PNID = "123456789012345";

/**
 * A base, reduzida ao que importa: duas tabelas com chave `(kind, event_key)`.
 *
 * Reconhece o SQL pelo verbo e pela tabela, e não por igualdade de texto: o SQL
 * vem das constantes do módulo e um teste que o comparasse letra a letra
 * quebrava a cada mudança de indentação sem nada ter mudado de significado.
 */
class BaseFalsa implements ClienteSql {
  readonly entrada = new Map<string, { id: string; processado: boolean }>();
  readonly quarentena = new Map<
    string,
    { motivo: string; payload: string | null; wabaId: string | null }
  >();
  /** Quando definido, a próxima consulta lança isto. Para provar a retentativa. */
  falha: Error | null = null;
  consultas = 0;

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[] }> {
    this.consultas += 1;
    if (this.falha !== null) throw this.falha;
    const texto = sql.replace(/\s+/g, " ").trim();

    if (texto.startsWith("INSERT INTO platform.inbound_events")) {
      const [kind, eventKey] = parametros as [string, string];
      const chave = `${kind}|${eventKey}`;
      if (this.entrada.has(chave)) return { rows: [] };
      const id = `id-${this.entrada.size + 1}`;
      this.entrada.set(chave, { id, processado: false });
      return { rows: [{ id }] };
    }
    if (texto.startsWith("SELECT id FROM platform.inbound_events")) {
      const [kind, eventKey] = parametros as [string, string];
      const linha = this.entrada.get(`${kind}|${eventKey}`);
      return { rows: linha !== undefined && !linha.processado ? [{ id: linha.id }] : [] };
    }
    if (texto.startsWith("UPDATE platform.inbound_events")) {
      const [id] = parametros as [string];
      for (const linha of this.entrada.values()) {
        if (linha.id === id) linha.processado = true;
      }
      return { rows: [] };
    }
    if (texto.startsWith("INSERT INTO platform.unrouted_events")) {
      const [kind, eventKey, wabaId, , motivo, payload] = parametros as [
        string,
        string,
        string | null,
        string | null,
        string,
        string | null,
      ];
      const chave = `${kind}|${eventKey}`;
      if (!this.quarentena.has(chave)) {
        this.quarentena.set(chave, { motivo, payload, wabaId });
      }
      return { rows: [] };
    }
    throw new Error(`consulta nao reconhecida: ${texto.slice(0, 60)}`);
  }
}

/** Conta por destino. É o que prova o critério 8 do lado do encaminhamento. */
class EncaminhadorEspiao implements Encaminhador {
  readonly chamadas: { destino: string; evento: EventoDeEntrada }[] = [];
  /** Quando definido, o método do destino nomeado lança. */
  falhaEm: string | null = null;

  async chr(evento: EventoDeEntrada): Promise<void> {
    this.#registar("chr", evento);
  }
  async outbound(evento: EventoDeEntrada): Promise<void> {
    this.#registar("outbound", evento);
  }
  async ingestao(evento: EventoDeEntrada): Promise<void> {
    this.#registar("ingestao", evento);
  }
  async gestaoDeCanal(evento: EventoDeEntrada): Promise<void> {
    this.#registar("gestao_de_canal", evento);
  }

  #registar(destino: string, evento: EventoDeEntrada): void {
    if (this.falhaEm === destino) throw new Error(`${destino} falhou`);
    this.chamadas.push({ destino, evento });
  }

  destinos(): string[] {
    return this.chamadas.map((c) => c.destino);
  }
}

function trabalhoDe(texto: string): { trabalho: TrabalhoDeEntrada; resumo: string } {
  const bytes = Buffer.from(texto, "utf8");
  return {
    trabalho: { corpo: bytes.toString("base64"), recebidoEm: 1_700_000_000_000 },
    resumo: sha256Hex(new Uint8Array(bytes)),
  };
}

function corpoComMensagem(wamid: string, espacos = false): string {
  const corpo = {
    object: "whatsapp_business_account",
    entry: [
      {
        id: WABA,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { phone_number_id: PNID },
              messages: [{ id: wamid, type: "text", text: { body: "ola" } }],
            },
          },
        ],
      },
    ],
  };
  return espacos ? JSON.stringify(corpo, null, 2) : JSON.stringify(corpo);
}

describe("tratarCorpo: JSON invalido (criterio 6)", () => {
  it("vai a quarentena com `json_invalido` e NAO lanca", async () => {
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe("{isto nao e json");
    const resultado = await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);

    assert.deepEqual(resultado, {
      registados: 0,
      duplicados: 0,
      recuperados: 0,
      emQuarentena: 1,
      destinos: [],
    });
    assert.equal(bd.entrada.size, 0);
    assert.equal(bd.quarentena.size, 1);
    const [entrada] = [...bd.quarentena.entries()];
    assert.equal(entrada?.[0], `invalido|k_${resumo.slice(0, 32)}`);
    assert.equal(entrada?.[1].motivo, "json_invalido");
  });

  it("guarda o corpo bruto em base64 para se poder diagnosticar", async () => {
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe("{isto nao e json");
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    const guardado = [...bd.quarentena.values()][0]?.payload;
    assert.equal(guardado, trabalho.corpo);
    assert.equal(Buffer.from(guardado ?? "", "base64").toString("utf8"), "{isto nao e json");
  });

  it("o mesmo corpo invalido duas vezes da uma linha", async () => {
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe("}}}");
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    assert.equal(bd.quarentena.size, 1);
  });

  it("um corpo grande entra com payload nulo em vez de a insercao falhar", async () => {
    // Sem isto, o `CHECK` de `unrouted_events_payload_ck` falhava, o *job*
    // repetia seis vezes e a Meta re-entregava sete dias — por um corpo que
    // nunca vai melhorar.
    const bd = new BaseFalsa();
    const grande = `{${"a".repeat(PAYLOAD_MAXIMO)}`;
    const { trabalho, resumo } = trabalhoDe(grande);
    assert.ok(trabalho.corpo.length > PAYLOAD_MAXIMO);
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    assert.equal(bd.quarentena.size, 1);
    assert.equal([...bd.quarentena.values()][0]?.payload, null);
  });

  it("base64 invalido conta como corpo ilegivel, nao lanca", async () => {
    const bd = new BaseFalsa();
    const resultado = await tratarCorpo(
      bd,
      { corpo: "!!!nao e base64!!!", recebidoEm: 0 },
      new EncaminhadorEspiao(),
      "b".repeat(64),
    );
    assert.equal(resultado.emQuarentena, 1);
  });
});

describe("tratarCorpo: deduplicacao (criterio 4)", () => {
  it("o mesmo wamid em dois corpos DIFERENTES da uma linha", async () => {
    // É a segunda metade do critério 4, e a que o `jobId` não apanha: os dois
    // corpos têm `sha256` diferente e a mesma mensagem.
    const bd = new BaseFalsa();
    const compacto = trabalhoDe(corpoComMensagem("wamid.MESMO"));
    const espacado = trabalhoDe(corpoComMensagem("wamid.MESMO", true));
    assert.notEqual(compacto.resumo, espacado.resumo);

    const encaminhador = new EncaminhadorEspiao();
    const primeiro = await tratarCorpo(bd, compacto.trabalho, encaminhador, compacto.resumo);
    const segundo = await tratarCorpo(bd, espacado.trabalho, encaminhador, espacado.resumo);

    assert.equal(primeiro.registados, 1);
    assert.equal(segundo.registados, 0);
    assert.equal(segundo.duplicados, 1);
    assert.equal(bd.entrada.size, 1);
    // E encaminha **uma** vez: o segundo já tinha `processado_at`.
    assert.deepEqual(encaminhador.destinos(), ["chr"]);
  });

  it("wamids diferentes dao linhas diferentes", async () => {
    const bd = new BaseFalsa();
    const encaminhador = new EncaminhadorEspiao();
    for (const wamid of ["wamid.A", "wamid.B", "wamid.C"]) {
      const { trabalho, resumo } = trabalhoDe(corpoComMensagem(wamid));
      await tratarCorpo(bd, trabalho, encaminhador, resumo);
    }
    assert.equal(bd.entrada.size, 3);
    assert.equal(encaminhador.chamadas.length, 3);
  });
});

describe("tratarCorpo: a janela entre registar e encaminhar", () => {
  it("um evento registado e nao encaminhado e encaminhado na entrega seguinte", async () => {
    // O cenário: o processo morre entre o `INSERT` e o encaminhamento. Sem a
    // consulta do `processado_at`, a entrega seguinte via `ON CONFLICT` sem
    // linha, concluía «duplicado» e o evento perdia-se em silêncio.
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.PERDIDO"));

    const queFalha = new EncaminhadorEspiao();
    queFalha.falhaEm = "chr";
    await assert.rejects(() => tratarCorpo(bd, trabalho, queFalha, resumo));
    assert.equal(bd.entrada.size, 1);
    assert.equal([...bd.entrada.values()][0]?.processado, false);

    const queFunciona = new EncaminhadorEspiao();
    const segundo = await tratarCorpo(bd, trabalho, queFunciona, resumo);
    // `recuperados` e nao `duplicados`: foi encaminhado pela primeira vez.
    assert.equal(segundo.recuperados, 1);
    assert.equal(segundo.duplicados, 0);
    assert.deepEqual(queFunciona.destinos(), ["chr"]);
    assert.equal([...bd.entrada.values()][0]?.processado, true);
    // E a terceira entrega já não encaminha nada.
    const terceiro = new EncaminhadorEspiao();
    await tratarCorpo(bd, trabalho, terceiro, resumo);
    assert.deepEqual(terceiro.destinos(), []);
  });

  it("uma falha da base lanca: e a unica classe de erro que merece retentativa", async () => {
    const bd = new BaseFalsa();
    bd.falha = new Error("connection terminated unexpectedly");
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.A"));
    await assert.rejects(
      () => tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo),
      /connection terminated/,
    );
  });
});

describe("tratarCorpo: encaminhamento (criterio 8)", () => {
  function corpoDoCampo(field: string, value: unknown): string {
    return JSON.stringify({ entry: [{ id: WABA, changes: [{ field, value }] }] });
  }

  it("uma mensagem vai ao chr", async () => {
    const bd = new BaseFalsa();
    const espiao = new EncaminhadorEspiao();
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.A"));
    await tratarCorpo(bd, trabalho, espiao, resumo);
    assert.deepEqual(espiao.destinos(), ["chr"]);
  });

  it("um estado vai ao outbound e NUNCA ao chr", async () => {
    const bd = new BaseFalsa();
    const espiao = new EncaminhadorEspiao();
    const { trabalho, resumo } = trabalhoDe(
      corpoDoCampo("messages", {
        metadata: { phone_number_id: PNID },
        statuses: [{ id: "wamid.A", status: "delivered" }],
      }),
    );
    await tratarCorpo(bd, trabalho, espiao, resumo);
    assert.deepEqual(espiao.destinos(), ["outbound"]);
    assert.equal(espiao.destinos().includes("chr"), false);
  });

  it("history e smb_app_state_sync vao so a ingestao", async () => {
    for (const campo of ["history", "smb_app_state_sync"]) {
      const bd = new BaseFalsa();
      const espiao = new EncaminhadorEspiao();
      const { trabalho, resumo } = trabalhoDe(
        corpoDoCampo(campo, { metadata: { phone_number_id: PNID }, dados: [1, 2] }),
      );
      await tratarCorpo(bd, trabalho, espiao, resumo);
      assert.deepEqual(espiao.destinos(), ["ingestao"], campo);
    }
  });

  it("os sete campos de gestao vao a gestao_de_canal", async () => {
    for (const campo of [
      "account_update",
      "phone_number_quality_update",
      "business_capability_update",
      "account_alerts",
      "message_template_status_update",
      "template_category_update",
      "message_template_quality_update",
    ]) {
      const bd = new BaseFalsa();
      const espiao = new EncaminhadorEspiao();
      const { trabalho, resumo } = trabalhoDe(corpoDoCampo(campo, { evento: campo }));
      await tratarCorpo(bd, trabalho, espiao, resumo);
      assert.deepEqual(espiao.destinos(), ["gestao_de_canal"], campo);
    }
  });

  it("um corpo em quarentena nao vai a encaminhador nenhum", async () => {
    const bd = new BaseFalsa();
    const espiao = new EncaminhadorEspiao();
    const { trabalho, resumo } = trabalhoDe("{nao e json");
    await tratarCorpo(bd, trabalho, espiao, resumo);
    assert.deepEqual(espiao.chamadas, []);
  });

  it("o perfil do criterio 7 — uma mensagem e tres estados — da quatro linhas", async () => {
    const bd = new BaseFalsa();
    const espiao = new EncaminhadorEspiao();
    const { trabalho, resumo } = trabalhoDe(
      JSON.stringify({
        entry: [
          {
            id: WABA,
            changes: [
              {
                field: "messages",
                value: {
                  metadata: { phone_number_id: PNID },
                  messages: [{ id: "wamid.M", type: "text" }],
                },
              },
              {
                field: "messages",
                value: {
                  metadata: { phone_number_id: PNID },
                  statuses: [
                    { id: "wamid.M", status: "sent" },
                    { id: "wamid.M", status: "delivered" },
                    { id: "wamid.M", status: "read" },
                  ],
                },
              },
            ],
          },
        ],
      }),
    );
    const resultado = await tratarCorpo(bd, trabalho, espiao, resumo);
    assert.equal(resultado.registados, 4);
    assert.deepEqual(espiao.destinos(), ["chr", "outbound", "outbound", "outbound"]);
    assert.equal(bd.entrada.size, 4);
  });
});

describe("tratarCorpo: o que vai para o registo", () => {
  it("o msg_id e opaco — o wamid NUNCA sai em claro", async () => {
    const bd = new BaseFalsa();
    const linhas: Record<string, unknown>[] = [];
    const wamid = "wamid.HBgMMjQ0OTIzNDU2Nzg5FQIAEhgU";
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem(wamid));
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo, (campos) =>
      linhas.push(campos),
    );

    assert.equal(linhas.length, 1);
    const esperado = `m_${createHash("sha256").update(wamid, "utf8").digest("hex").slice(0, 32)}`;
    assert.equal(linhas[0]?.msg_id, esperado);
    assert.match(String(linhas[0]?.msg_id), /^m_[0-9a-f]{32}$/);
    // O `wamid` leva o número do interlocutor em base64 (`docs/logs.md` §2.1).
    assert.equal(JSON.stringify(linhas).includes(wamid), false);
    assert.equal(JSON.stringify(linhas).includes("244923456789"), false);
  });

  it("so saem campos da allowlist, e nunca o conteudo da mensagem", async () => {
    const bd = new BaseFalsa();
    const linhas: Record<string, unknown>[] = [];
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.A"));
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo, (campos) =>
      linhas.push(campos),
    );
    const permitidos = new Set(["outcome", "msg_id", "wa_type", "error_code", "latency_ms"]);
    for (const linha of linhas) {
      for (const chave of Object.keys(linha)) {
        assert.ok(permitidos.has(chave), `${chave} nao esta na allowlist do criterio 9`);
      }
    }
    assert.equal(linhas[0]?.wa_type, "text");
    assert.equal(JSON.stringify(linhas).includes("ola"), false);
  });

  it("um estado nao leva wa_type: nao e uma mensagem", async () => {
    const bd = new BaseFalsa();
    const linhas: Record<string, unknown>[] = [];
    const { trabalho, resumo } = trabalhoDe(
      JSON.stringify({
        entry: [
          {
            id: WABA,
            changes: [
              { field: "messages", value: { statuses: [{ id: "wamid.A", status: "read" }] } },
            ],
          },
        ],
      }),
    );
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo, (campos) =>
      linhas.push(campos),
    );
    assert.equal("wa_type" in (linhas[0] ?? {}), false);
  });
});

// --- O que a revisão adversarial mudou --------------------------------------

describe("um evento recuperado nao e um duplicado", () => {
  it("o desfecho e `recuperado`, e conta-se a parte", async () => {
    // O achado: o caminho de recuperação devolvia `duplicado` e **depois**
    // encaminhava, pelo que o contador de duplicados subia sem ter havido
    // duplicado e a recuperação de um evento perdido não deixava rasto
    // distinguível — que é precisamente o que um operador precisa de ver.
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.RECUPERADO"));

    const queFalha = new EncaminhadorEspiao();
    queFalha.falhaEm = "chr";
    await assert.rejects(() => tratarCorpo(bd, trabalho, queFalha, resumo));

    const desfechos: string[] = [];
    const resultado = await tratarCorpo(
      bd,
      trabalho,
      new EncaminhadorEspiao(),
      resumo,
      undefined,
      (desfecho) => {
        desfechos.push(desfecho);
      },
    );
    assert.deepEqual(desfechos, ["recuperado"]);
    assert.equal(resultado.recuperados, 1);
    assert.equal(resultado.duplicados, 0);
    assert.equal(resultado.registados, 0);
  });

  it("um duplicado verdadeiro continua `duplicado`", async () => {
    const bd = new BaseFalsa();
    const { trabalho, resumo } = trabalhoDe(corpoComMensagem("wamid.DUPLICADO"));
    const desfechos: string[] = [];
    const contar = (d: string): void => {
      desfechos.push(d);
    };
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo, undefined, contar);
    await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo, undefined, contar);
    assert.deepEqual(desfechos, ["registado", "duplicado"]);
  });
});

describe("o corpo guarda-se uma vez por corpo, nao por evento", () => {
  it("tres campos desconhecidos dao tres linhas e UMA copia do corpo", async () => {
    // O achado: cada evento de quarentena guardava uma cópia **inteira** do
    // corpo, pelo que 1 000 `changes` davam 1 000 linhas de até 256 KiB — 256 MB
    // de um pedido, com a retenção que os limparia a ser de outro ticket.
    const bd = new BaseFalsa();
    const corpo = {
      entry: [
        {
          id: WABA,
          changes: [
            { field: "campo_a", value: { metadata: { phone_number_id: PNID } } },
            { field: "campo_b", value: { metadata: { phone_number_id: PNID } } },
            { field: "campo_c", value: { metadata: { phone_number_id: PNID } } },
          ],
        },
      ],
    };
    const { trabalho, resumo } = trabalhoDe(JSON.stringify(corpo));
    const motivos: string[] = [];
    const resultado = await tratarCorpo(
      bd,
      trabalho,
      new EncaminhadorEspiao(),
      resumo,
      undefined,
      undefined,
      (motivo) => {
        motivos.push(motivo);
      },
    );
    assert.equal(resultado.emQuarentena, 3);
    assert.equal(bd.quarentena.size, 3);
    const comCorpo = [...bd.quarentena.values()].filter((q) => q.payload !== null);
    assert.equal(comCorpo.length, 1, "o corpo devia estar numa linha so");
    assert.equal(comCorpo[0]?.payload, trabalho.corpo);
    assert.deepEqual(motivos, [
      "campo_desconhecido",
      "campo_desconhecido",
      "campo_desconhecido",
    ]);
  });
});

describe("tecto de eventos por corpo", () => {
  it("um corpo acima do tecto vai inteiro a quarentena e nada se registra", async () => {
    // Sem tecto, um corpo com 100 000 `statuses` fazia 100 000 `INSERT`
    // sequenciais num só *job*, com `concurrency: 1`, e a partição ficava
    // bloqueada todo esse tempo enquanto a Meta continuava a entregar.
    const bd = new BaseFalsa();
    const estados = Array.from({ length: EVENTOS_MAXIMOS_POR_CORPO + 1 }, (_, i) => ({
      id: `wamid.${i}`,
      status: "sent",
    }));
    const { trabalho, resumo } = trabalhoDe(
      JSON.stringify({
        entry: [{ id: WABA, changes: [{ field: "messages", value: { statuses: estados } }] }],
      }),
    );
    const resultado = await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    assert.equal(resultado.registados, 0);
    assert.equal(resultado.emQuarentena, 1);
    assert.equal(bd.entrada.size, 0);
    // E a chave é determinística: a re-entrega do mesmo corpo não cria segunda
    // linha.
    assert.equal([...bd.quarentena.keys()][0], `desconhecido|k_${resumo.slice(0, 32)}`);
  });

  it("um corpo no tecto exacto trata-se todo", async () => {
    const bd = new BaseFalsa();
    const estados = Array.from({ length: EVENTOS_MAXIMOS_POR_CORPO }, (_, i) => ({
      id: `wamid.${i}`,
      status: "sent",
    }));
    const { trabalho, resumo } = trabalhoDe(
      JSON.stringify({
        entry: [{ id: WABA, changes: [{ field: "messages", value: { statuses: estados } }] }],
      }),
    );
    const resultado = await tratarCorpo(bd, trabalho, new EncaminhadorEspiao(), resumo);
    assert.equal(resultado.registados, EVENTOS_MAXIMOS_POR_CORPO);
    assert.equal(resultado.emQuarentena, 0);
  });
});

// --- O recuo do *worker* de entrada -----------------------------------------
//
// Este bloco existe por causa de um defeito que a suite de integracao apanhou e
// nenhum teste unitario apanhava: o `addLote` do `filas_bullmq.ts` poe
// `backoff: { type: "custom" }` em **todos** os *jobs*, e um `Worker` que nao
// registe um `backoffStrategy` lanca «Unknown backoff strategy custom» ao
// calcular o atraso da segunda tentativa. O *job* ficava em `failed` sem passar
// pela quarentena, e um corpo ilegivel desaparecia em silencio com a Meta a
// re-entregar durante sete dias.

describe("os ajustes do trabalhador de entrada", () => {
  it("registra um `backoffStrategy`: sem ele, o job `custom` rebenta", () => {
    assert.equal(typeof AJUSTES_DO_TRABALHADOR.backoffStrategy, "function");
  });

  it("a escada e a do consumidor, degrau a degrau", () => {
    const degraus = [1, 2, 3, 4, 5].map((n) =>
      AJUSTES_DO_TRABALHADOR.backoffStrategy(n),
    );
    assert.deepEqual(degraus, [...ESCADA_DO_CONSUMIDOR]);
  });

  it("acima da escada fica no ultimo degrau, em vez de crescer para sempre", () => {
    const ultimo = ESCADA_DO_CONSUMIDOR[ESCADA_DO_CONSUMIDOR.length - 1];
    assert.equal(AJUSTES_DO_TRABALHADOR.backoffStrategy(99), ultimo);
  });

  it("uma contagem de zero conta como a primeira tentativa, e nao levanta", () => {
    // O BullMQ chama isto com `attemptsMade`, que e zero na primeira falha, e o
    // `atrasoDaTentativaDoConsumidor` recusa menos de 1.
    assert.equal(AJUSTES_DO_TRABALHADOR.backoffStrategy(0), ESCADA_DO_CONSUMIDOR[0]);
  });

  it("o numero de tentativas do `add` e o da escada mais um", () => {
    // O `addLote` poe `attempts: REPETICAO.tentativas`, e a escada tem de ter um
    // degrau por retentativa. Os dois numeros vivem em ficheiros diferentes, e
    // e esta asercao que os prende.
    assert.equal(REPETICAO.tentativas, ESCADA_DO_CONSUMIDOR.length + 1);
  });
});

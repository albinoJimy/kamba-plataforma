/**
 * A explosão do corpo em eventos de canal (KAM-013, critérios 4 e 8).
 *
 * Os dois que importam mais:
 *
 * - **`event_key` de estados é `wamid:estado`** (critério 4, à letra).
 * - **O destino de cada `kind`** (critério 8), com as duas propriedades
 *   negativas escritas como asserções: um `statuses` não vai ao `chr`, e um
 *   `history` vai só a `ingestao`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DESTINOS,
  KINDS,
  KINDS_DE_ENTRADA,
  KINDS_DE_QUARENTENA,
  KIND_POR_CAMPO,
  MOTIVOS,
  WA_TYPES,
  destinoDe,
  waType,
} from "../src/entrada/contrato.ts";
import {
  ARRAY_DOS_ECHOES,
  EVENT_KEY_MAXIMO,
  ID_META_MAXIMO,
  PREFIXO_DO_RESUMO,
  PROFUNDIDADE_MAXIMA,
  canonico,
  explodir,
  resumoCanonico,
} from "../src/entrada/explosao.ts";

const WABA = "109876543210987";
const PNID = "123456789012345";
const RESUMO = "a".repeat(64);

function corpoDe(...changes: unknown[]): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [{ id: WABA, changes }],
  };
}

function mudancaDeMensagens(value: unknown): unknown {
  return { field: "messages", value };
}

const METADATA = { display_phone_number: "244923000000", phone_number_id: PNID };

describe("explosao: mensagens", () => {
  it("uma mensagem da um evento com o wamid como event_key", () => {
    const { eventos, quarentena } = explodir(
      corpoDe(
        mudancaDeMensagens({
          messaging_product: "whatsapp",
          metadata: METADATA,
          messages: [{ id: "wamid.AAA", type: "text", text: { body: "ola" } }],
        }),
      ),
      RESUMO,
    );
    assert.equal(quarentena.length, 0);
    assert.deepEqual(eventos, [
      {
        kind: "message",
        eventKey: "wamid.AAA",
        wabaId: WABA,
        phoneNumberId: PNID,
        waType: "text",
      },
    ]);
  });

  it("tres mensagens no mesmo corpo dao tres eventos", () => {
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          messages: [
            { id: "wamid.A", type: "text" },
            { id: "wamid.B", type: "image" },
            { id: "wamid.C", type: "audio" },
          ],
        }),
      ),
      RESUMO,
    );
    assert.deepEqual(
      eventos.map((e) => [e.kind, e.eventKey, e.waType]),
      [
        ["message", "wamid.A", "text"],
        ["message", "wamid.B", "image"],
        ["message", "wamid.C", "audio"],
      ],
    );
  });

  it("um tipo de mensagem que nao esta na lista fechada sai como `outro`", () => {
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          messages: [{ id: "wamid.A", type: "tipo_que_a_meta_inventou" }],
        }),
      ),
      RESUMO,
    );
    assert.equal(eventos[0]?.waType, "outro");
  });

  it("uma mensagem sem `id` nao se perde: fica com resumo canonico", () => {
    const { eventos } = explodir(
      corpoDe(mudancaDeMensagens({ metadata: METADATA, messages: [{ type: "text" }] })),
      RESUMO,
    );
    assert.equal(eventos.length, 1);
    assert.match(eventos[0]?.eventKey ?? "", /^k_[0-9a-f]{32}$/);
  });

  it("um `id` acima do tecto degrada para o resumo em vez de rebentar", () => {
    // Sem isto, a insercao violava `inbound_events_event_key_ck`, o *job*
    // falhava e o BullMQ repetia — durante sete dias, com a Meta por cima.
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          messages: [{ id: "w".repeat(EVENT_KEY_MAXIMO + 1), type: "text" }],
        }),
      ),
      RESUMO,
    );
    assert.match(eventos[0]?.eventKey ?? "", /^k_[0-9a-f]{32}$/);
    assert.ok((eventos[0]?.eventKey ?? "").length <= EVENT_KEY_MAXIMO);
  });
});

describe("explosao: estados (criterio 4)", () => {
  it("a event_key de um estado e `wamid:estado`", () => {
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          statuses: [{ id: "wamid.XYZ", status: "delivered", recipient_id: "244923000001" }],
        }),
      ),
      RESUMO,
    );
    assert.deepEqual(eventos, [
      {
        kind: "statuses",
        eventKey: "wamid.XYZ:delivered",
        wabaId: WABA,
        phoneNumberId: PNID,
        waType: null,
      },
    ]);
  });

  it("tres estados do mesmo wamid dao tres event_key distintas", () => {
    // É o perfil de carga do critério 7: «3 estados por mensagem». Se a chave
    // fosse só o `wamid`, `delivered` apagava `sent` e o `read` nunca chegava.
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          statuses: [
            { id: "wamid.M", status: "sent" },
            { id: "wamid.M", status: "delivered" },
            { id: "wamid.M", status: "read" },
          ],
        }),
      ),
      RESUMO,
    );
    assert.deepEqual(
      eventos.map((e) => e.eventKey),
      ["wamid.M:sent", "wamid.M:delivered", "wamid.M:read"],
    );
    assert.equal(new Set(eventos.map((e) => e.eventKey)).size, 3);
  });

  it("mensagens e estados no mesmo value dao os dois kinds", () => {
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          messages: [{ id: "wamid.A", type: "text" }],
          statuses: [{ id: "wamid.B", status: "read" }],
        }),
      ),
      RESUMO,
    );
    assert.deepEqual(
      eventos.map((e) => e.kind),
      ["message", "statuses"],
    );
  });

  it("um estado sem `status` degrada para o resumo", () => {
    const { eventos } = explodir(
      corpoDe(mudancaDeMensagens({ metadata: METADATA, statuses: [{ id: "wamid.A" }] })),
      RESUMO,
    );
    assert.match(eventos[0]?.eventKey ?? "", /^k_[0-9a-f]{32}$/);
  });
});

describe("explosao: os outros campos", () => {
  it("cada campo conhecido da o seu kind", () => {
    for (const [campo, kind] of Object.entries(KIND_POR_CAMPO)) {
      const { eventos, quarentena } = explodir(
        corpoDe({ field: campo, value: { metadata: METADATA, qualquer: "coisa" } }),
        RESUMO,
      );
      assert.equal(quarentena.length, 0, `${campo} nao devia ir a quarentena`);
      assert.equal(eventos.length, 1, `${campo} devia dar um evento`);
      assert.equal(eventos[0]?.kind, kind);
      assert.match(eventos[0]?.eventKey ?? "", /^k_[0-9a-f]{32}$/);
    }
  });

  it("um echo com o array da *proposta* da um evento por item", () => {
    const { eventos } = explodir(
      corpoDe({
        field: "smb_message_echoes",
        value: {
          metadata: METADATA,
          [ARRAY_DOS_ECHOES]: [
            { id: "wamid.E1", type: "text" },
            { id: "wamid.E2", type: "image" },
          ],
        },
      }),
      RESUMO,
    );
    assert.deepEqual(
      eventos.map((e) => [e.kind, e.eventKey, e.waType]),
      [
        ["echo", "wamid.E1", "text"],
        ["echo", "wamid.E2", "image"],
      ],
    );
  });

  it("um echo com o array noutro sitio cai na regra 2 e continua correcto", () => {
    // O nome do array e **NAO VERIFICADO** (`E1` §5 nao o diz). Se a *proposta*
    // estiver errada, o evento sai com o `kind` certo e uma chave
    // deterministica: mais grosso, e nao perdido.
    const { eventos, quarentena } = explodir(
      corpoDe({
        field: "smb_message_echoes",
        value: { metadata: METADATA, outro_nome: [{ id: "wamid.E1" }] },
      }),
      RESUMO,
    );
    assert.equal(quarentena.length, 0);
    assert.equal(eventos.length, 1);
    assert.equal(eventos[0]?.kind, "echo");
    assert.match(eventos[0]?.eventKey ?? "", /^k_[0-9a-f]{32}$/);
  });
});

describe("explosao: quarentena", () => {
  it("um corpo sem entry vai a quarentena com `corpo_sem_entry`", () => {
    for (const corpo of [null, {}, { entry: [] }, { entry: "nao e lista" }, 42, "texto"]) {
      const { eventos, quarentena } = explodir(corpo, RESUMO);
      assert.equal(eventos.length, 0);
      assert.deepEqual(quarentena.map((q) => q.motivo), ["corpo_sem_entry"]);
      // A chave vem do resumo do corpo: a re-entrega do mesmo corpo mau nao
      // cria uma segunda linha.
      assert.equal(quarentena[0]?.eventKey, `${PREFIXO_DO_RESUMO}${RESUMO.slice(0, 32)}`);
    }
  });

  it("uma entry sem id vai a quarentena: `waba_id` e NOT NULL em inbound_events", () => {
    const { eventos, quarentena } = explodir(
      { entry: [{ changes: [mudancaDeMensagens({ messages: [{ id: "wamid.A" }] })] }] },
      RESUMO,
    );
    assert.equal(eventos.length, 0);
    assert.equal(quarentena[0]?.motivo, "corpo_sem_entry");
    assert.equal(quarentena[0]?.wabaId, null);
  });

  it("uma entry com id acima do tecto vai a quarentena", () => {
    const { eventos, quarentena } = explodir(
      {
        entry: [
          { id: "x".repeat(ID_META_MAXIMO + 1), changes: [mudancaDeMensagens({})] },
        ],
      },
      RESUMO,
    );
    assert.equal(eventos.length, 0);
    assert.equal(quarentena[0]?.motivo, "corpo_sem_entry");
  });

  it("um campo que nao se conhece vai a quarentena com `campo_desconhecido`", () => {
    const { eventos, quarentena } = explodir(
      corpoDe({ field: "campo_que_alguem_subscreveu", value: { metadata: METADATA } }),
      RESUMO,
    );
    assert.equal(eventos.length, 0);
    assert.equal(quarentena[0]?.motivo, "campo_desconhecido");
    assert.equal(quarentena[0]?.wabaId, WABA);
    assert.equal(quarentena[0]?.phoneNumberId, PNID);
  });

  it("um `messages` sem messages nem statuses vai com `change_sem_itens`", () => {
    // Acontece de verdade: a Meta poe `errors` aqui.
    const { eventos, quarentena } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: METADATA,
          errors: [{ code: 131_026, title: "Message undeliverable" }],
        }),
      ),
      RESUMO,
    );
    assert.equal(eventos.length, 0);
    assert.equal(quarentena[0]?.motivo, "change_sem_itens");
  });

  it("um corpo misto registra o que encaixa e poe em quarentena o que nao", () => {
    const { eventos, quarentena } = explodir(
      corpoDe(
        mudancaDeMensagens({ metadata: METADATA, messages: [{ id: "wamid.A", type: "text" }] }),
        { field: "campo_desconhecido_qualquer", value: { metadata: METADATA } },
      ),
      RESUMO,
    );
    assert.equal(eventos.length, 1);
    assert.equal(quarentena.length, 1);
  });

  it("um `phone_number_id` acima do tecto conta como ausente", () => {
    const { eventos } = explodir(
      corpoDe(
        mudancaDeMensagens({
          metadata: { phone_number_id: "9".repeat(ID_META_MAXIMO + 1) },
          messages: [{ id: "wamid.A", type: "text" }],
        }),
      ),
      RESUMO,
    );
    assert.equal(eventos[0]?.phoneNumberId, null);
  });
});

describe("resumo canonico", () => {
  it("a ordem das chaves nao muda o resumo", () => {
    // É isto que faz o resumo deduplicar: duas entregas do mesmo evento com as
    // chaves noutra ordem são o mesmo evento.
    assert.equal(
      resumoCanonico({ a: 1, b: { c: 2, d: 3 } }),
      resumoCanonico({ b: { d: 3, c: 2 }, a: 1 }),
    );
  });

  it("`JSON.stringify` nao serve, e e por isso que ha um canonico", () => {
    assert.notEqual(
      JSON.stringify({ a: 1, b: 2 }),
      JSON.stringify({ b: 2, a: 1 }),
    );
    assert.equal(canonico({ a: 1, b: 2 }), canonico({ b: 2, a: 1 }));
  });

  it("um valor diferente muda o resumo", () => {
    assert.notEqual(resumoCanonico({ a: 1 }), resumoCanonico({ a: 2 }));
    assert.notEqual(resumoCanonico("x", { a: 1 }), resumoCanonico("y", { a: 1 }));
  });

  it("tem a forma que o dicionario fixa e cabe no tecto", () => {
    const resumo = resumoCanonico({ a: 1 });
    assert.match(resumo, /^k_[0-9a-f]{32}$/);
    assert.equal(resumo.length, 34);
    assert.ok(resumo.length <= EVENT_KEY_MAXIMO);
  });

  it("distingue-se do `id_opaco` do §3.10 pelo prefixo", () => {
    // O `id_opaco` e `m_`; este e `k_`. Um mascara para registo, o outro
    // deduplica em base, e confundi-los era registar uma chave de base de
    // dados numa linha de log.
    assert.equal(PREFIXO_DO_RESUMO, "k_");
  });

  it("uma estrutura mais funda do que o tecto nao rebenta e continua determinista", () => {
    let fundo: unknown = "fim";
    for (let i = 0; i < PROFUNDIDADE_MAXIMA + 10; i += 1) fundo = { dentro: fundo };
    const primeiro = resumoCanonico(fundo);
    assert.match(primeiro, /^k_[0-9a-f]{32}$/);
    assert.equal(primeiro, resumoCanonico(fundo));
  });

  it("`undefined` dentro de um objecto omite-se, como no stringify", () => {
    assert.equal(canonico({ a: 1, b: undefined }), canonico({ a: 1 }));
  });

  it("numeros nao finitos saem como null em vez de rebentarem", () => {
    assert.equal(canonico(Number.NaN), "null");
    assert.equal(canonico(Number.POSITIVE_INFINITY), "null");
  });
});

describe("roteamento por kind (criterio 8)", () => {
  it("a tabela e a do critério 8, destino a destino", () => {
    assert.equal(destinoDe("message"), "chr");
    assert.equal(destinoDe("echo"), "chr");
    assert.equal(destinoDe("statuses"), "outbound");
    assert.equal(destinoDe("history"), "ingestao");
    assert.equal(destinoDe("smb_app_state_sync"), "ingestao");
    for (const kind of [
      "account_update",
      "phone_number_quality_update",
      "business_capability_update",
      "account_alerts",
      "message_template_status_update",
      "template_category_update",
      "message_template_quality_update",
    ] as const) {
      assert.equal(destinoDe(kind), "gestao_de_canal", kind);
    }
    assert.equal(destinoDe("desconhecido"), "quarentena");
    assert.equal(destinoDe("invalido"), "quarentena");
  });

  it("um estado NUNCA vai ao chr", () => {
    // «`statuses` → *stage* de *outbound* (nunca ao AGR)». O AGR é alimentado
    // pelo CHR; não chegar ao `chr` é a forma verificável de «nunca ao AGR»
    // deste lado da fronteira.
    assert.notEqual(destinoDe("statuses"), "chr");
  });

  it("o historico vai so a ingestao", () => {
    // «`history`/`smb_app_state_sync` → só ingestão (KAM-017)».
    for (const kind of ["history", "smb_app_state_sync"] as const) {
      assert.equal(destinoDe(kind), "ingestao");
      assert.notEqual(destinoDe(kind), "chr");
    }
  });

  it("todo o kind tem destino, e todo o destino e um dos cinco", () => {
    for (const kind of KINDS) {
      assert.ok(DESTINOS.includes(destinoDe(kind)), `${kind} sem destino valido`);
    }
  });

  it("os dominios tem o tamanho que o dicionario diz", () => {
    assert.equal(KINDS.length, 14);
    // Doze em `inbound_events.kind`, dois em `unrouted_events.kind`: as duas
    // tabelas tem `CHECK` diferentes, e o tipo recusa trocar um pelo outro.
    assert.equal(KINDS_DE_ENTRADA.length, 12);
    assert.equal(KINDS_DE_QUARENTENA.length, 2);
    assert.deepEqual([...KINDS], [...KINDS_DE_ENTRADA, ...KINDS_DE_QUARENTENA]);
    assert.equal(MOTIVOS.length, 4);
    assert.equal(DESTINOS.length, 5);
    // Onze campos de webhook: dez no mapa, mais o `messages`, que da dois kinds.
    assert.equal(Object.keys(KIND_POR_CAMPO).length, 10);
  });
});

describe("waType", () => {
  it("aceita so a lista fechada", () => {
    for (const tipo of WA_TYPES) assert.equal(waType(tipo), tipo);
  });

  it("tudo o resto e `outro`, incluindo o que nao e texto", () => {
    for (const valor of [undefined, null, 42, {}, [], "", "TEXT", "video", "x".repeat(200)]) {
      assert.equal(waType(valor), "outro", String(valor));
    }
  });
});

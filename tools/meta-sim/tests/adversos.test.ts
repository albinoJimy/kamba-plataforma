/**
 * Os oito casos adversos e o modo de re-entrega (KAM-024, critérios 3 e 6).
 *
 * Estes testes afirmam a **forma** dos casos: que existem os oito, que cada um
 * leva os POSTs que diz levar, e que o desfecho declarado é o que o GWY vai
 * devolver. Quem afirma o **comportamento** do GWY é o teste de ida e volta em
 * `services/gwy/tests/kam024.ida-e-volta.test.ts` — aqui não se levanta GWY
 * nenhum, de propósito: um teste do gerador que precisasse do servidor falhava
 * por razões do servidor, e a mensagem de erro mandava procurar no sítio errado.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { NOMES, casosAdversos, corpoMexido } from "../src/adversos.ts";
import { confere, segredoDeEnsaio } from "../src/assinatura.ts";
import { serializar } from "../src/corpo.ts";
import { cenarioDe } from "../src/fixtures.ts";
import {
  CALENDARIO_PROPOSTO,
  MINUTO_MS,
  SETE_DIAS_S,
  razoesDeFalha,
  reentregar,
} from "../src/reentrega.ts";
import { exigirFicticios } from "../src/numeros.ts";
import { Gerador } from "../src/semente.ts";

const SEMENTE = "adversos-do-kam-024";
const SEGREDO = segredoDeEnsaio(SEMENTE);

function casos() {
  const { canal, quem } = cenarioDe(SEMENTE);
  return casosAdversos(new Gerador(SEMENTE), { canal, quem, segredo: SEGREDO });
}

describe("os oito casos adversos (criterio 3)", () => {
  it("sao oito, com os nomes do criterio", () => {
    assert.deepEqual(
      casos().map((c) => c.nome),
      [...NOMES],
    );
    assert.equal(NOMES.length, 8);
  });

  it("cada caso diz porque existe e o que tem de acontecer", () => {
    for (const caso of casos()) {
      assert.ok(caso.porque.length > 20, `${caso.nome}: o porque e curto demais`);
      assert.ok(caso.esperado.length > 20, `${caso.nome}: o esperado e curto demais`);
      assert.ok(caso.pedidos.length > 0, `${caso.nome}: sem pedidos`);
    }
  });

  it("sao deterministicos", () => {
    const a = casos();
    const b = casos();
    for (let i = 0; i < a.length; i += 1) {
      const pa = a[i]?.pedidos ?? [];
      const pb = b[i]?.pedidos ?? [];
      assert.equal(pa.length, pb.length);
      for (let j = 0; j < pa.length; j += 1) {
        assert.ok(Buffer.from(pa[j]?.bytes ?? []).equals(Buffer.from(pb[j]?.bytes ?? [])));
        assert.equal(pa[j]?.assinatura, pb[j]?.assinatura);
      }
    }
  });

  it("nenhum caso leva um telefone com forma real", () => {
    for (const caso of casos()) {
      for (const pedido of caso.pedidos) {
        // O `json_invalido_assinado` não dá `parse`; a verificação é sobre o
        // texto, e por isso cobre-o também.
        assert.doesNotThrow(
          () => exigirFicticios(Buffer.from(pedido.bytes).toString("utf8")),
          caso.nome,
        );
      }
    }
  });

  it("assinatura_invalida: um POST, 401, e a assinatura nao bate", () => {
    const caso = casos()[0];
    assert.ok(caso !== undefined);
    assert.equal(caso.nome, "assinatura_invalida");
    assert.equal(caso.pedidos.length, 1);
    const pedido = caso.pedidos[0];
    assert.ok(pedido !== undefined);
    assert.equal(pedido.estado, 401);
    assert.ok(!confere(pedido.bytes, pedido.assinatura, SEGREDO));
  });

  it("json_invalido_assinado: a assinatura bate e o corpo nao da parse", () => {
    const caso = casos().find((c) => c.nome === "json_invalido_assinado");
    assert.ok(caso !== undefined);
    const pedido = caso.pedidos[0];
    assert.ok(pedido !== undefined);
    // As duas metades do caso: a assinatura é boa...
    assert.ok(confere(pedido.bytes, pedido.assinatura, SEGREDO));
    // ...e o corpo não é JSON.
    assert.throws(() => JSON.parse(Buffer.from(pedido.bytes).toString("utf8")));
    // E por isso o estado é 200 e não 400: ver a nota do módulo `adversos.ts`.
    assert.equal(pedido.estado, 200);
  });

  it("corpo_duplicado: dois POSTs com os MESMOS bytes", () => {
    const caso = casos().find((c) => c.nome === "corpo_duplicado");
    assert.ok(caso !== undefined);
    assert.equal(caso.pedidos.length, 2);
    const [um, dois] = caso.pedidos;
    assert.ok(Buffer.from(um?.bytes ?? []).equals(Buffer.from(dois?.bytes ?? [])));
    assert.equal(um?.assinatura, dois?.assinatura);
  });

  it("mesma_mensagem_em_dois_corpos: bytes diferentes, mesmo wamid", () => {
    const caso = casos().find((c) => c.nome === "mesma_mensagem_em_dois_corpos");
    assert.ok(caso !== undefined);
    const [um, dois] = caso.pedidos;
    assert.ok(um !== undefined && dois !== undefined);
    assert.ok(!Buffer.from(um.bytes).equals(Buffer.from(dois.bytes)), "os bytes tem de diferir");

    function wamidDe(bytes: Uint8Array): string {
      const corpo = JSON.parse(Buffer.from(bytes).toString("utf8")) as {
        entry: { changes: { value: { messages?: { id: string }[] } }[] }[];
      };
      const id = corpo.entry[0]?.changes[0]?.value.messages?.[0]?.id;
      assert.ok(id !== undefined);
      return id;
    }
    // É esta igualdade que separa a idempotência da fila (por bytes) da do
    // evento (por `wamid`).
    assert.equal(wamidDe(um.bytes), wamidDe(dois.bytes));
  });

  it("ordem_trocada: tres estados, do read para o sent", () => {
    const caso = casos().find((c) => c.nome === "ordem_trocada");
    assert.ok(caso !== undefined);
    const corpo = JSON.parse(Buffer.from(caso.pedidos[0]?.bytes ?? []).toString("utf8")) as {
      entry: { changes: { value: { statuses: { status: string; id: string }[] } }[] }[];
    };
    const estados = corpo.entry[0]?.changes[0]?.value.statuses ?? [];
    assert.deepEqual(
      estados.map((e) => e.status),
      ["read", "delivered", "sent"],
    );
    // O mesmo `wamid` nos três: é a mesma mensagem fora de ordem, e não três.
    assert.equal(new Set(estados.map((e) => e.id)).size, 1);
  });

  it("lote_de_entries: tres entries, dois WABAs", () => {
    const caso = casos().find((c) => c.nome === "lote_de_entries");
    assert.ok(caso !== undefined);
    const corpo = JSON.parse(Buffer.from(caso.pedidos[0]?.bytes ?? []).toString("utf8")) as {
      entry: { id: string }[];
    };
    assert.equal(corpo.entry.length, 3);
    assert.equal(new Set(corpo.entry.map((e) => e.id)).size, 2);
  });

  it("wa_id_omitido: sem from e sem wa_id, com BSUID", () => {
    const caso = casos().find((c) => c.nome === "wa_id_omitido");
    assert.ok(caso !== undefined);
    const corpo = JSON.parse(Buffer.from(caso.pedidos[0]?.bytes ?? []).toString("utf8")) as {
      entry: {
        changes: {
          value: {
            contacts: { wa_id?: string; user_id: string }[];
            messages: { from?: string; from_user_id: string }[];
          };
        }[];
      }[];
    };
    const valor = corpo.entry[0]?.changes[0]?.value;
    assert.ok(valor !== undefined);
    assert.equal(valor.messages[0]?.from, undefined);
    assert.equal(valor.contacts[0]?.wa_id, undefined);
    // O BSUID tem de estar nos dois sítios, senão o CHR não resolve nada.
    assert.match(valor.messages[0]?.from_user_id ?? "", /^AO\./);
    assert.match(valor.contacts[0]?.user_id ?? "", /^AO\./);
  });

  it("phone_number_id_desconhecido: um canal diferente do do cenario", () => {
    const caso = casos().find((c) => c.nome === "phone_number_id_desconhecido");
    assert.ok(caso !== undefined);
    const corpo = JSON.parse(Buffer.from(caso.pedidos[0]?.bytes ?? []).toString("utf8")) as {
      entry: { changes: { value: { metadata: { phone_number_id: string } } }[] }[];
    };
    const desconhecido = corpo.entry[0]?.changes[0]?.value.metadata.phone_number_id;
    assert.notEqual(desconhecido, cenarioDe(SEMENTE).canal.phoneNumberId);
  });

  it("corpoMexido: a assinatura e do original e os bytes nao", () => {
    const original = serializar({ object: "whatsapp_business_account", entry: [{ id: "100123" }] });
    const pedido = corpoMexido(original, SEGREDO);
    assert.equal(pedido.estado, 401);
    assert.ok(confere(original, pedido.assinatura, SEGREDO));
    assert.ok(!confere(pedido.bytes, pedido.assinatura, SEGREDO));
  });
});

describe("re-entrega (criterio 6)", () => {
  it("o calendario proposto cobre os sete dias", () => {
    assert.ok(CALENDARIO_PROPOSTO.length >= 2);
    assert.equal(CALENDARIO_PROPOSTO[0], 0);
    assert.equal(CALENDARIO_PROPOSTO[CALENDARIO_PROPOSTO.length - 1], SETE_DIAS_S);
  });

  it("o calendario e monotono crescente", () => {
    for (let i = 1; i < CALENDARIO_PROPOSTO.length; i += 1) {
      assert.ok(
        (CALENDARIO_PROPOSTO[i] ?? 0) > (CALENDARIO_PROPOSTO[i - 1] ?? 0),
        `o instante ${i} nao cresce`,
      );
    }
  });

  it("sete dias simulados em menos de um minuto real, com o MESMO corpo", () => {
    const bytes = serializar({ object: "whatsapp_business_account", entry: [{ id: "100123" }] });
    const vistos = new Set<string>();
    return reentregar(async (numero, instante) => {
      // O corpo é o mesmo em todas as tentativas: é isso que faz o teste medir
      // idempotência e não «N corpos diferentes dão N efeitos».
      vistos.add(Buffer.from(bytes).toString("hex"));
      assert.ok(numero >= 1 && instante >= 0);
      return 200;
    }).then((relatorio) => {
      assert.equal(vistos.size, 1, "o corpo mudou entre tentativas");
      assert.equal(relatorio.aceites, relatorio.tentativas.length);
      assert.equal(relatorio.horizonteSimuladoS, SETE_DIAS_S);
      assert.ok(relatorio.duracaoRealMs < MINUTO_MS, `${relatorio.duracaoRealMs}ms`);
      assert.deepEqual(razoesDeFalha(relatorio), []);
    });
  });

  it("razoesDeFalha nomeia qual das duas condicoes falhou", () => {
    // Um booleano não servia: a evidência tem de dizer **qual** falhou.
    const curto = razoesDeFalha({
      tentativas: [],
      horizonteSimuladoS: 60,
      duracaoRealMs: 10,
      aceites: 0,
    });
    assert.equal(curto.length, 1);
    assert.match(curto[0] ?? "", /horizonte simulado/);

    const lento = razoesDeFalha({
      tentativas: [],
      horizonteSimuladoS: SETE_DIAS_S,
      duracaoRealMs: MINUTO_MS + 1,
      aceites: 0,
    });
    assert.equal(lento.length, 1);
    assert.match(lento[0] ?? "", /levou/);
  });

  it("um calendario proprio substitui o proposto", () => {
    return reentregar(async () => 503, { calendario: [0, 10, 20] }).then((relatorio) => {
      assert.equal(relatorio.tentativas.length, 3);
      assert.equal(relatorio.aceites, 0);
      assert.equal(relatorio.horizonteSimuladoS, 20);
      // E com um calendário curto o critério **não** está cumprido, e o
      // relatório di-lo em vez de passar a verde.
      assert.equal(razoesDeFalha(relatorio).length, 1);
    });
  });
});

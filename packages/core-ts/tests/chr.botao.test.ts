/**
 * O botão de uma resposta interactiva até ao `agent_invocation` (KAM-211,
 * critério «Botão»).
 *
 * O caminho de produção é webhook → explosão → CHR → fila `agr-inbound` → AGR.
 * Aqui prova-se a metade TypeScript, de ponta a ponta: um corpo da Meta com um
 * `button_reply` sai do `Chr.tratar` com o `botao` na invocação, e o corpo que
 * sai é **exactamente** o de `fixtures/invocacao_do_botao.json` — o mesmo
 * ficheiro que o `services/agr/tests/test_dono.py` passa ao `ler_invocacao` e
 * leva até ao `confirmar`. É a ponte entre as duas linguagens: nenhum ensaio
 * corre as duas no mesmo processo.
 *
 * E as ausências, que são o lado adversarial do critério: um texto que imita um
 * botão não tem `botao`; um `id` fora da forma não segue; o título nunca sai.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { AGENT_INVOCATION_V1_PATH } from "@kamba/contracts";

import {
  Chr,
  type ClienteDoChr,
  type EntregaDoChr,
  MetricasDoChr,
  ResolvedorDeCanal,
  canalDaLinha,
  montarInvocacao,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import { BOTAO_MAXIMO, FORMA_DO_BOTAO } from "../src/entrada/contrato.ts";
import { explodir } from "../src/entrada/explosao.ts";
import { linhaDeCanal } from "./apoio/chr-base-falsa.ts";

const esquema = JSON.parse(readFileSync(AGENT_INVOCATION_V1_PATH, "utf8"));
const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/invocacao_do_botao.json", import.meta.url), "utf8"),
) as { readonly action_id: string; readonly corpo: Readonly<Record<string, unknown>> };
const ALVO = FIXTURE.corpo;

const PNID = "999000000000001";
const WABA = "999000000000002";
const BOTAO = `confirm:${FIXTURE.action_id}`;

// ------------------------------------------------------------------ o corpo

function corpoDe(mensagem: Readonly<Record<string, unknown>>): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: WABA,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "244 999 000 000", phone_number_id: PNID },
              messages: [
                {
                  id: ALVO["wamid"],
                  from: "244 999 000 001",
                  from_user_id: "AO.BSUID.DONO.999",
                  timestamp: "1763460000",
                  ...mensagem,
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

function toque(variante: string, id: unknown, titulo = "Confirmar"): unknown {
  return corpoDe({ type: "interactive", interactive: { type: variante, [variante]: { id, title: titulo } } });
}

function evento(corpo: unknown) {
  const { eventos } = explodir(corpo, "a".repeat(64));
  assert.equal(eventos.length, 1);
  return eventos[0]!;
}

// --------------------------------------------------------------- o CHR falso

class CanalFalso implements ClienteDoChr {
  async query(_sql: string, parametros: readonly unknown[] = []) {
    return parametros[0] === PNID
      ? {
          rows: [
            linhaDeCanal({ tenant_id: ALVO["tenant_id"], channel_id: ALVO["channel_id"] }),
          ],
        }
      : { rows: [] };
  }
}

/** A conversa e o papel. O papel filtra pelas igualdades do texto da instrução. */
class Base implements ClienteDoChr {
  async query(sql: string, parametros: readonly unknown[] = []) {
    if (sql.includes("INSERT INTO platform.conversations")) {
      return { rows: [{ id: ALVO["conversation_id"], mode: "bot" }] };
    }
    if (/^\s*SELECT\s+papel\s+FROM\s+platform\.contacts\b/i.test(sql)) {
      const ok = [...sql.matchAll(/\b(tenant_id|contact_id)\s*=\s*\$(\d+)/g)].every(
        ([, coluna, n]) => String(parametros[Number(n) - 1]) === String(ALVO[coluna!]),
      );
      return { rows: ok ? [{ papel: "dono" }] : [] };
    }
    return { rows: [] };
  }
}

class Entrega implements EntregaDoChr {
  readonly aoAgr: AgentInvocation[] = [];
  async agr(invocacao: AgentInvocation): Promise<void> {
    this.aoAgr.push(invocacao);
  }
  async dono(): Promise<void> {}
}

function chr() {
  const entrega = new Entrega();
  const base = new Base();
  const instancia = new Chr({
    resolvedor: new ResolvedorDeCanal(new CanalFalso()),
    contacto: async () => ({ contactId: String(ALVO["contact_id"]) }),
    entrega,
    quarentena: async () => {},
    metricas: new MetricasDoChr(),
    comTenant: async (_tenant, trabalho) => trabalho(base),
  });
  return { instancia, entrega };
}

// ------------------------------------------------------------------ explosao

describe("KAM-211 — o `reply.id` sai da explosao", () => {
  it("um `button_reply` e um `list_reply` dao o `botao`, e o titulo nao sai", () => {
    for (const variante of ["button_reply", "list_reply"]) {
      const e = evento(toque(variante, BOTAO, "Sim, confirmo"));
      assert.equal(e.waType, "interactive");
      assert.equal(e.botao, BOTAO);
      assert.ok(!JSON.stringify(e).includes("confirmo"), "o titulo nao entra no evento");
    }
  });

  it("um texto que imita um botao nao tem `botao`", () => {
    for (const corpo of [
      corpoDe({ type: "text", text: { body: BOTAO } }),
      // Um texto com um `interactive` colado ao lado: o tipo e que manda.
      corpoDe({ type: "text", text: { body: "ok" }, interactive: { type: "button_reply", button_reply: { id: BOTAO } } }),
      // O tipo legado de resposta rapida de *template* chega como `outro`.
      corpoDe({ type: "button", button: { payload: BOTAO, text: "Confirmar" } }),
    ]) {
      const e = evento(corpo);
      assert.equal("botao" in e, false);
    }
  });

  it("um `id` fora da forma nao segue, e a mensagem segue sem ele", () => {
    for (const id of ["sim confirmo", "", "x".repeat(BOTAO_MAXIMO + 1), 7, null, ["a"], { id: BOTAO }, "olá"]) {
      const e = evento(toque("button_reply", id));
      assert.equal(e.waType, "interactive");
      assert.equal("botao" in e, false, `id ${JSON.stringify(id)}`);
    }
    assert.equal(evento(toque("button_reply", "x".repeat(BOTAO_MAXIMO))).botao, "x".repeat(BOTAO_MAXIMO));
  });

  it("uma variante de `interactive` sem escolha do cliente nao da `botao`", () => {
    for (const variante of ["nfm_reply", "product", "desconhecida"]) {
      assert.equal("botao" in evento(toque(variante, BOTAO)), false);
    }
    assert.equal("botao" in evento(corpoDe({ type: "interactive", interactive: "x" })), false);
  });
});

// ---------------------------------------------------------------- a invocacao

describe("KAM-211 — o `botao` no `agent_invocation`", () => {
  const pedido = {
    contexto: canalDaLinha(linhaDeCanal()).contexto,
    contactId: "33333333-3333-4333-8333-333333333333",
    conversationId: "44444444-4444-4444-8444-444444444444",
    wamid: "wamid.HBgLOTk5",
    modo: "bot" as const,
    persona: "dono" as const,
  };

  it("so vai num `interactive`", () => {
    assert.equal(montarInvocacao({ ...pedido, type: "interactive", botao: BOTAO }).botao, BOTAO);
    for (const type of ["text", "outro", "image"]) {
      assert.equal("botao" in montarInvocacao({ ...pedido, type, botao: BOTAO }), false);
    }
    assert.equal("botao" in montarInvocacao({ ...pedido, type: "interactive", botao: null }), false);
    assert.equal("botao" in montarInvocacao({ ...pedido, type: "interactive" }), false);
  });

  it("o esquema publica-o como opcional, so com `type: interactive`", () => {
    assert.ok(!(esquema.required as string[]).includes("botao"));
    assert.equal(esquema.properties.botao.maxLength, BOTAO_MAXIMO);
    assert.equal(esquema.properties.botao.pattern, FORMA_DO_BOTAO.source);
    assert.deepEqual(esquema.dependentSchemas.botao.properties.type, { const: "interactive" });
  });

  it("a forma e a mesma do AGR, letra a letra", () => {
    // O espelho do `_BOTAO` de `kamba_agr/contexto.py`: duas formas diferentes
    // davam `campo_invalido_botao` a um `id` que o CHR deixou passar — um 400,
    // e um turno perdido.
    const python = readFileSync(
      new URL("../../../services/agr/src/kamba_agr/contexto.py", import.meta.url),
      "utf8",
    );
    const achado = /_BOTAO = re\.compile\(r"\\A(.+?)\{1,%d\}\\Z" % BOTAO_MAXIMO\)/.exec(python);
    assert.ok(achado, "o `_BOTAO` do AGR mudou de forma");
    assert.equal(`^${achado[1]}{1,${BOTAO_MAXIMO}}$`, FORMA_DO_BOTAO.source);
    assert.match(python, new RegExp(`BOTAO_MAXIMO: Final = ${BOTAO_MAXIMO}\\b`));
  });
});

// ---------------------------------------------------------- de ponta a ponta

describe("KAM-211 — webhook → explosao → CHR → `agent_invocation`", () => {
  it("o toque do dono sai do CHR com o corpo exacto da fixture que o AGR le", async () => {
    const { instancia, entrega } = chr();
    const resultado = await instancia.tratar(evento(toque("button_reply", BOTAO)));
    assert.equal(resultado.desfecho, "encaminhado");
    assert.equal(entrega.aoAgr.length, 1);
    assert.deepEqual({ ...entrega.aoAgr[0] }, ALVO);
  });

  it("dois toques sao duas invocacoes com o mesmo `botao` e `wamid` diferentes", async () => {
    // O duplo toque: o CHR entrega os dois (a fila deduplica pelo `wamid`, e
    // aqui sao dois), e e o `confirmar` do AGR que da **uma** confirmacao.
    const { instancia, entrega } = chr();
    for (const n of [1, 2]) {
      const corpo = toque("button_reply", BOTAO) as { entry: { changes: { value: { messages: Record<string, unknown>[] } }[] }[] };
      corpo.entry[0]!.changes[0]!.value.messages[0]!["id"] = `wamid.HBgLOTk5.toque.${n}`;
      await instancia.tratar(evento(corpo));
    }
    assert.equal(entrega.aoAgr.length, 2);
    assert.deepEqual(entrega.aoAgr.map((i) => i.botao), [BOTAO, BOTAO]);
    assert.notEqual(entrega.aoAgr[0]!.wamid, entrega.aoAgr[1]!.wamid);
  });

  it("vinte textos de confirmacao saem sem `botao`", async () => {
    const { instancia, entrega } = chr();
    const textos = [
      "sim", "Sim", "SIM", "ok", "OK", "confirmo", "confirmar", "sim confirmo", "pode",
      "podes publicar", "esta bem", "ta bem", "claro", "yes", "1", BOTAO, `sim ${BOTAO}`,
      `confirm: ${FIXTURE.action_id}`, BOTAO.toUpperCase(), "confirm:",
    ];
    assert.equal(textos.length, 20);
    for (const [n, body] of textos.entries()) {
      const corpo = corpoDe({ type: "text", text: { body }, id: `wamid.HBgLOTk5.texto.${n}` });
      await instancia.tratar(evento(corpo));
    }
    assert.equal(entrega.aoAgr.length, 20);
    assert.equal(entrega.aoAgr.filter((i) => "botao" in i).length, 0);
  });
});

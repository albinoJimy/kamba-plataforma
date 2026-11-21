/**
 * O processo de entrada do `worker-canal` (KAM-013).
 *
 * A decisão — explodir, registar, encaminhar, pôr em quarentena — é de
 * `@kamba/core-ts/entrada` e está provada lá. Aqui prova-se a **montagem**: que
 * o encaminhador do esqueleto recebe o que devia receber, que o `/metrics`
 * responde e que a sonda continua a responder.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { sha256Hex, tratarCorpo } from "@kamba/core-ts/entrada";
import type { ClienteSql } from "@kamba/core-ts/entrada";

import {
  EncaminhadorDoCanal,
  EncaminhadorQueSoRegista,
  PORTA_POR_OMISSAO,
  ambienteDasChaves,
  criarApp,
  encaminhadorDaEntrada,
  identidadeDaEntrada,
} from "../src/entrada.ts";
import { SERVICE } from "../src/meta.ts";
import { ChavesDeIdentidadeEmFaltaError, Identidade, gerarChaveVersionada } from "@kamba/core-ts/identity";
import { METRICAS_DA_GUARDA, comTenant } from "@kamba/core-ts/tenant_guard";

const WABA = "109876543210987";

/** A base reduzida a «aceita e devolve um id novo». A dedup prova-se em core-ts. */
class BaseQueAceita implements ClienteSql {
  conta = 0;

  async query(sql: string): Promise<{ rows: Record<string, unknown>[] }> {
    if (sql.includes("INSERT INTO platform.inbound_events")) {
      this.conta += 1;
      return { rows: [{ id: `id-${this.conta}` }] };
    }
    return { rows: [] };
  }
}

function trabalhoDe(corpo: unknown) {
  const bytes = Buffer.from(JSON.stringify(corpo), "utf8");
  return {
    trabalho: { corpo: bytes.toString("base64"), recebidoEm: 0 },
    resumo: sha256Hex(new Uint8Array(bytes)),
  };
}

function mudanca(field: string, value: unknown): unknown {
  return { entry: [{ id: WABA, changes: [{ field, value }] }] };
}

describe("o encaminhador do esqueleto", () => {
  it("recebe uma mensagem pelo chr", async () => {
    const encaminhador = new EncaminhadorQueSoRegista();
    const { trabalho, resumo } = trabalhoDe(
      mudanca("messages", { messages: [{ id: "wamid.A", type: "text" }] }),
    );
    const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
    assert.deepEqual(resultado.destinos, ["chr"]);
    assert.equal(encaminhador.entregues.length, 1);
    assert.equal(encaminhador.entregues[0]?.kind, "message");
  });

  it("um estado chega pelo outbound e o historico pela ingestao", async () => {
    for (const [corpo, destino, kind] of [
      [
        mudanca("messages", { statuses: [{ id: "wamid.A", status: "read" }] }),
        "outbound",
        "statuses",
      ],
      [mudanca("history", { threads: [] }), "ingestao", "history"],
      [mudanca("account_update", { event: "PARTNER_ADDED" }), "gestao_de_canal", "account_update"],
    ] as const) {
      const encaminhador = new EncaminhadorQueSoRegista();
      const { trabalho, resumo } = trabalhoDe(corpo);
      const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
      assert.deepEqual(resultado.destinos, [destino], kind);
      assert.equal(encaminhador.entregues[0]?.kind, kind);
    }
  });

  it("nao entrega nada de um corpo que vai a quarentena", async () => {
    const encaminhador = new EncaminhadorQueSoRegista();
    const resultado = await tratarCorpo(
      new BaseQueAceita(),
      { corpo: Buffer.from("{nao e json", "utf8").toString("base64"), recebidoEm: 0 },
      encaminhador,
      "c".repeat(64),
    );
    assert.equal(resultado.emQuarentena, 1);
    assert.deepEqual(encaminhador.entregues, []);
  });
});

describe("KAM-235: o braco outbound do encaminhador de producao", () => {
  const corpo = mudanca("messages", { statuses: [{ id: "wamid.A", status: "delivered" }] });

  it("um statuses vai ao estagio dos statuses, com o wamid e o estado, e nunca ao CHR", async () => {
    const recebidos: unknown[] = [];
    const chr = {
      tratar: async () => {
        throw new Error("um statuses nao vai ao CHR");
      },
    } as unknown as ConstructorParameters<typeof EncaminhadorDoCanal>[0];
    const encaminhador = new EncaminhadorDoCanal(chr, async (evento) => {
      recebidos.push(evento.estado);
    });
    const { trabalho, resumo } = trabalhoDe(corpo);
    const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
    assert.deepEqual(resultado.destinos, ["outbound"]);
    assert.deepEqual(recebidos, [{ wamid: "wamid.A", estado: "delivered", pricing: null }]);
    assert.equal(encaminhador.entregues.length, 1);
  });

  it("uma falha do estagio sobe, para o job repetir", async () => {
    const chr = {} as unknown as ConstructorParameters<typeof EncaminhadorDoCanal>[0];
    const encaminhador = new EncaminhadorDoCanal(chr, async () => {
      throw new Error("base em baixo");
    });
    const { trabalho, resumo } = trabalhoDe(corpo);
    await assert.rejects(tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo), /base em baixo/);
  });

  it("a montagem do processo: o tenant do canal, a escrita sob o contexto dele, e o aviso sem mensagem", async () => {
    const TENANT = "11111111-1111-4111-8111-111111111111";
    const pedidos: { sql: string; v: readonly unknown[] }[] = [];
    let existe = true;
    const bd = {
      async query(sql: string, v: readonly unknown[] = []) {
        pedidos.push({ sql, v });
        if (!existe || !sql.includes("platform.outbound_messages")) return { rows: [] };
        if (sql.includes("UPDATE")) return { rows: [{ id: "m1", estado_antes: "sent", state: "delivered", kind: "service" }] };
        return { rows: [{ id: "m1", state: "sent", kind: "service" }] };
      },
    };
    const resolvedor = {
      resolver: async (pnid: string) => ({
        resolvido: pnid === "pnid-ensaio" ? ({ contexto: { tenant_id: TENANT } } as never) : null,
        daCache: false,
      }),
    };
    const registos: Record<string, unknown>[] = [];
    const log = {
      info: (c: Record<string, unknown>) => registos.push(c),
      warn: (c: Record<string, unknown>) => registos.push(c),
    } as unknown as Parameters<typeof encaminhadorDaEntrada>[0]["log"];
    const chr = {} as unknown as Parameters<typeof encaminhadorDaEntrada>[0]["chr"];
    const encaminhador = encaminhadorDaEntrada({ chr, resolvedor, bd: bd as never, log });
    const corpoDoCanal = mudanca("messages", {
      metadata: { phone_number_id: "pnid-ensaio" },
      statuses: [{ id: "wamid.A", status: "delivered" }],
    });

    const { trabalho, resumo } = trabalhoDe(corpoDoCanal);
    await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
    const contexto = pedidos.findIndex((p) => p.sql.includes("set_config('app.tenant_id'"));
    const escrita = pedidos.findIndex((p) => p.sql.includes("UPDATE platform.outbound_messages"));
    assert.ok(contexto >= 0 && escrita > contexto, "a escrita corre depois do contexto do tenant");
    assert.deepEqual(pedidos[contexto]!.v, [TENANT]);
    assert.deepEqual(pedidos[escrita]!.v.slice(0, 3), [TENANT, "wamid.A", "delivered"]);
    assert.ok(registos.some((r) => r.outcome === "estado_avancou"));

    // Um `statuses` antes da nossa escrita do `wamid`: o `Saida` avisa.
    existe = false;
    const outro = trabalhoDe(corpoDoCanal);
    await tratarCorpo(new BaseQueAceita(), outro.trabalho, encaminhador, outro.resumo);
    assert.ok(registos.some((r) => r.outcome === "status_sem_mensagem"), JSON.stringify(registos));
    assert.ok(registos.some((r) => r.outcome === "estado_nao_avancou"));
  });

  it("sem estagio, o braco conta e mais nada, como no esqueleto", async () => {
    const chr = {} as unknown as ConstructorParameters<typeof EncaminhadorDoCanal>[0];
    const encaminhador = new EncaminhadorDoCanal(chr);
    const { trabalho, resumo } = trabalhoDe(corpo);
    const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
    assert.deepEqual(resultado.destinos, ["outbound"]);
    assert.equal(encaminhador.entregues.length, 1);
  });
});

describe("as rotas do processo de entrada", () => {
  it("a sonda responde com o contrato do servico", async () => {
    const resposta = await criarApp().request("/healthz");
    assert.equal(resposta.status, 200);
    const corpo = (await resposta.json()) as { status: string; service: string };
    assert.equal(corpo.status, "ok");
    assert.equal(corpo.service, SERVICE);
  });

  it("o /metrics expoe as metricas DESTE processo, nao as do GWY", async () => {
    // Achado da revisão adversarial: servia-se aqui o `METRICAS` do GWY, que
    // este processo não incrementa — saíam `gwy_sig_fail 0` e
    // `inbound_queue_depth -1` permanentes (o segundo ao lado do valor real do
    // GWY, onde um alerta o lê e não dispara) e do trabalho que ele faz de
    // verdade não saía nada.
    const resposta = await criarApp().request("/metrics");
    assert.equal(resposta.status, 200);
    const texto = await resposta.text();
    for (const nome of [
      "inbound_events_total",
      "inbound_unrouted_total",
      "inbound_job_failed_total",
    ]) {
      assert.match(texto, new RegExp(`^# TYPE ${nome} counter$`, "m"), nome);
    }
    for (const nome of ["gwy_requests_total", "gwy_sig_fail", "inbound_queue_depth"]) {
      assert.equal(texto.includes(nome), false, `${nome} nao e deste processo`);
    }
  });

  it("a porta e a quarta do servico, distinta das do publicador e do consumidor", async () => {
    // 3011 é o publicador, 3012 o consumidor. Duas iguais faziam o segundo
    // processo morrer a arrancar, com `EADDRINUSE`.
    assert.equal(PORTA_POR_OMISSAO, 3013);
  });

  it("uma rota desconhecida nao responde 200", async () => {
    for (const caminho of ["/", "/wa/webhook", "/admin"]) {
      assert.notEqual((await criarApp().request(caminho)).status, 200, caminho);
    }
  });
});

describe("o ambiente das chaves de identidade (KAM-187)", () => {
  it("staging da um provedor de staging, e nao de dev", () => {
    // Era `prod ? prod : dev`: o `exigirAmbienteDoKeyProvider` comparava `staging`
    // com `dev` e o processo nao arrancava no compose de *staging*.
    assert.equal(ambienteDasChaves({ KAMBA_ENV: "staging" }), "staging");
    assert.equal(ambienteDasChaves({ KAMBA_ENV: " prod " }), "prod");
    assert.equal(ambienteDasChaves({ KAMBA_ENV: "dev" }), "dev");
  });

  it("um valor desconhecido nao vira staging nem prod", () => {
    // A recusa de um valor desconhecido e do `exigirAmbienteDoKeyProvider`, que
    // compara com o declarado; aqui so se prova que nao se promove nada.
    assert.equal(ambienteDasChaves({ KAMBA_ENV: "producao" }), "dev");
    assert.equal(ambienteDasChaves({}), "dev");
  });
});

describe("o arranque da identidade em prod (KAM-227; criterio 9 do KAM-008 emendado)", () => {
  const chave = (kid: string) => gerarChaveVersionada(kid);
  const completo = (): NodeJS.ProcessEnv => ({
    KAMBA_ENV: "prod",
    KAMBA_SECRET_PEPPER_CONTACT_HMAC: chave("p1"),
    KAMBA_SECRET_KEK_CONTACT_DEK: chave("k1"),
  });

  it("**arranca em prod**, com as chaves no ambiente do lancador (decisao do fundador, 2026-11-20)", async () => {
    assert.ok((await identidadeDaEntrada(completo())) instanceof Identidade);
  });

  it("sem o pepper ou sem a KEK, ou com um deles vazio, nao arranca, e nomeia o que falta", async () => {
    const casos: [string, string | undefined, string][] = [
      ["KAMBA_SECRET_PEPPER_CONTACT_HMAC", undefined, "pepper_contact_hmac"],
      ["KAMBA_SECRET_KEK_CONTACT_DEK", undefined, "kek_contact_dek"],
      ["KAMBA_SECRET_PEPPER_CONTACT_HMAC", "", "pepper_contact_hmac"],
      ["KAMBA_SECRET_KEK_CONTACT_DEK", "k1:curta", "kek_contact_dek"],
    ];
    for (const [variavel, valor, ref] of casos) {
      const env = completo();
      if (valor === undefined) delete env[variavel];
      else env[variavel] = valor;
      await assert.rejects(identidadeDaEntrada(env), (erro: unknown) => {
        if (!(erro instanceof ChavesDeIdentidadeEmFaltaError)) return false;
        assert.deepEqual(erro.refs, [ref]);
        return true;
      });
    }
  });
});

/** KAM-219: faz subir o contador da guarda pelo caminho real — um `comTenant` cuja base recusa o tecto. */
async function recusaNoTecto(): Promise<number> {
  const cliente = { async query() { return { rows: [] }; } };
  const erro = Object.assign(new Error("permission denied for table trust_level"), { code: "42501" });
  await assert.rejects(comTenant(cliente, "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4", async () => { throw erro; }));
  return METRICAS_DA_GUARDA.recusas();
}

describe("KAM-219: a recusa da base sobre o tecto", () => {
  it("o /metrics da entrada serve-a, com o valor do processo", async () => {
    const n = await recusaNoTecto();
    assert.ok(n >= 1);
    const texto = await (await criarApp().request("/metrics")).text();
    assert.match(texto, /^# TYPE tenant_guard_tecto_recusado_total counter$/m);
    assert.match(texto, new RegExp(`^tenant_guard_tecto_recusado_total ${n}$`, "m"));
  });
});

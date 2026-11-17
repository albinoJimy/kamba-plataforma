/**
 * O canal do dono do lado TypeScript (KAM-118): persona, canal, proactivas,
 * troca de telefone e o dono que nasce do provisionamento.
 *
 * O que é da base — a função `platform.definir_dono`, o índice de um dono por
 * tenant e a idempotência — mede-se contra o PostgreSQL em
 * `db/tests/test_canal_do_dono_schema.py`. Aqui medem-se as decisões e as
 * portas, sem base.
 *
 * Os telefones são fictícios, com `999`, e escritos com espaços: assim nenhum
 * dos dois padrões do inventário do *gate* 7 os conta.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { eParar } from "../src/consentimento/parar.ts";
import {
  CONSUMIDOR_DO_DONO,
  canalDoDono,
  decidirProactiva,
  DESTINOS_DO_AVISO,
  efeitoDoProvisionamento,
  type OtpDaTroca,
  PAPEIS,
  PERSONAS,
  personaDe,
  PUSH_POR_MES,
  PUSH_POR_SEMANA,
  TelefoneDoCasoIndisponivelError,
  TrocaDeTelefone,
  VersaoDoProvisionamentoError,
} from "../src/dono/index.ts";
import type { Envelope } from "../src/eventos/envelope.ts";
import { Telefone } from "../src/inscricao/identificadores.ts";
import type { Veredicto } from "../src/inscricao/otp.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const DONO = "+244 999 000 101";
const OUTRO = "+244 999 000 102";
const TENANT_A = "11111111-1111-4111-8111-111111111111";
const TENANT_B = "22222222-2222-4222-8222-222222222222";

describe("KAM-118 criterio 1 — a persona e funcao do papel, e de mais nada", () => {
  it("so o valor exacto `dono` da a persona `dono`", () => {
    assert.equal(personaDe("dono"), "dono");
    for (const outro of ["cliente", "Dono", "DONO", " dono", "admin", "", null, undefined, 1, {}]) {
      assert.equal(personaDe(outro), "cliente", String(outro));
    }
  });

  it("as personas sao os papeis", () => {
    assert.deepEqual([...PERSONAS], [...PAPEIS]);
    assert.deepEqual([...PAPEIS].sort(), ["cliente", "dono"]);
  });
});

describe("KAM-118 criterio 7 — o canal do dono", () => {
  const hmacDoDono = new Telefone(DONO, PEPPER).hmac;

  it("telefone do dono igual ao numero da loja: so o painel", () => {
    for (const forma of ["+244 999 000 101", "244 999 000 101", "999 000 101"]) {
      assert.deepEqual(
        canalDoDono({ numeroDaLoja: forma, telefoneHmacDoDono: hmacDoDono, anelDoPepper: [PEPPER, null] }),
        { owner_channel_wa: false, canal: "painel" },
        forma,
      );
    }
  });

  it("telefone diferente do numero da loja: o canal WhatsApp fica activo", () => {
    assert.deepEqual(
      canalDoDono({ numeroDaLoja: OUTRO, telefoneHmacDoDono: hmacDoDono, anelDoPepper: [PEPPER, null] }),
      { owner_channel_wa: true, canal: "whatsapp" },
    );
  });

  it("sem numero da loja, ou ilegivel, painel — falha fechada", () => {
    for (const numero of [null, undefined, "", "   ", "abc", 999000101]) {
      assert.deepEqual(
        canalDoDono({ numeroDaLoja: numero, telefoneHmacDoDono: hmacDoDono, anelDoPepper: [PEPPER, null] }),
        { owner_channel_wa: false, canal: "painel" },
        String(numero),
      );
    }
  });
});

describe("KAM-118 criterio 8 — a politica de proactivas", () => {
  const base = { janelaAberta: false, optInMarketing: true, pushNaSemana: 0, pushNoMes: 0 };

  it("dentro da janela e service message, sem template, mesmo sem opt-in", () => {
    for (const optInMarketing of [true, false, null]) {
      assert.deepEqual(decidirProactiva({ ...base, janelaAberta: true, optInMarketing }), {
        accao: "service",
      });
    }
  });

  it("fora da janela so sai template com opt-in de marketing", () => {
    assert.deepEqual(decidirProactiva(base), { accao: "template" });
  });

  it("sem opt-in, 0 templates em 100 tentativas", () => {
    let templates = 0;
    for (let i = 0; i < 100; i += 1) {
      const optIn = i % 2 === 0 ? false : null;
      if (decidirProactiva({ ...base, optInMarketing: optIn }).accao === "template") templates += 1;
    }
    assert.equal(templates, 0);
  });

  it("«PARAR» suprime na primeira proactiva a seguir", () => {
    // O ConsentGate do KAM-022 grava `marketing` com `accepted=false` na
    // mensagem «PARAR»; a proactiva seguinte le esse estado.
    assert.equal(eParar("PARAR"), true);
    assert.deepEqual(decidirProactiva({ ...base, optInMarketing: false }), {
      accao: "suprimir",
      motivo: "sem_opt_in",
    });
  });

  it("tecto de 1 por semana e 4 por mes", () => {
    assert.equal(PUSH_POR_SEMANA, 1);
    assert.equal(PUSH_POR_MES, 4);
    assert.deepEqual(decidirProactiva({ ...base, pushNaSemana: 1, pushNoMes: 1 }), {
      accao: "suprimir",
      motivo: "tecto_semanal",
    });
    assert.deepEqual(decidirProactiva({ ...base, pushNaSemana: 0, pushNoMes: 4 }), {
      accao: "suprimir",
      motivo: "tecto_mensal",
    });
    assert.deepEqual(decidirProactiva({ ...base, pushNaSemana: 0, pushNoMes: 3 }), {
      accao: "template",
    });
  });

  it("uma contagem invalida suprime", () => {
    for (const n of [-1, 0.5, Number.NaN]) {
      assert.deepEqual(decidirProactiva({ ...base, pushNaSemana: n }), {
        accao: "suprimir",
        motivo: "contagem_invalida",
      });
    }
  });
});

/** Um OTP falso: acerta com o codigo certo, e conta o que lhe pediram. */
class OtpFalso implements OtpDaTroca {
  readonly enviados: string[] = [];
  codigo = "123456";
  respostaAoErro: Veredicto = "errou";

  async enviar(chave: string): Promise<{ readonly enviado: true; readonly expiraEm: Date }> {
    this.enviados.push(chave);
    return { enviado: true, expiraEm: new Date(0) };
  }

  async verificar(_chave: string, codigo: string): Promise<Veredicto> {
    return codigo === this.codigo ? "acertou" : this.respostaAoErro;
  }
}

function trocaFalsa() {
  const otp = new OtpFalso();
  const trocas: { tenantId: string; contactId: string }[] = [];
  const avisos: { tenantId: string; destino: string }[] = [];
  const troca = new TrocaDeTelefone({
    otp,
    contacto: async ({ tenantId }) => ({ contactId: `${tenantId}:novo` }),
    trocar: async (pedido) => {
      trocas.push(pedido);
      return { anterior: `${pedido.tenantId}:antigo` };
    },
    avisar: async (pedido) => {
      avisos.push(pedido);
    },
  });
  return { otp, troca, trocas, avisos };
}

describe("KAM-118 criterio 4 — a mudanca de telefone do dono", () => {
  it("ate o OTP acertar, nada muda: o numero novo e cliente e o antigo mantem o papel", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, new Telefone(OUTRO, PEPPER));
    assert.equal(m.otp.enviados.length, 1);
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, "000000"), {
      trocado: false,
      veredicto: "errou",
    });
    assert.deepEqual(m.trocas, []);
    assert.deepEqual(m.avisos, []);
  });

  it("o OTP certo move o papel e avisa o numero antigo e o e-mail", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, new Telefone(OUTRO, PEPPER));
    const desfecho = await m.troca.verificar("p1", TENANT_A, "123456");
    assert.deepEqual(desfecho, {
      trocado: true,
      contactId: `${TENANT_A}:novo`,
      anterior: `${TENANT_A}:antigo`,
    });
    assert.deepEqual(m.trocas, [{ tenantId: TENANT_A, contactId: `${TENANT_A}:novo` }]);
    assert.deepEqual(
      m.avisos.map((a) => a.destino),
      [...DESTINOS_DO_AVISO],
    );
    // Os avisos nao levam numero nenhum: so o tenant e o destino.
    assert.deepEqual(Object.keys(m.avisos[0] ?? {}).sort(), ["destino", "tenantId"]);
  });

  it("o pedido gasta-se: o mesmo codigo outra vez nao troca segunda vez", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, new Telefone(OUTRO, PEPPER));
    await m.troca.verificar("p1", TENANT_A, "123456");
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, "123456"), {
      trocado: false,
      veredicto: "sem_pedido",
    });
    assert.equal(m.trocas.length, 1);
  });

  it("o pedido de um tenant nao se verifica a partir de outro", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, new Telefone(OUTRO, PEPPER));
    assert.deepEqual(await m.troca.verificar("p1", TENANT_B, "123456"), {
      trocado: false,
      veredicto: "sem_pedido",
    });
    assert.deepEqual(m.trocas, []);
  });

  it("um OTP esgotado destroi o pedido", async () => {
    const m = trocaFalsa();
    m.otp.respostaAoErro = "tentativas";
    await m.troca.pedir("p1", TENANT_A, new Telefone(OUTRO, PEPPER));
    assert.equal((await m.troca.verificar("p1", TENANT_A, "000000")).trocado, false);
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, "123456"), {
      trocado: false,
      veredicto: "sem_pedido",
    });
  });
});

function envelope(troca: Partial<Envelope> = {}): Envelope {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    tipo: "tenant.provisioned",
    versao: 1,
    tenant_id: TENANT_A,
    ocorrido_em: "2026-11-17T10:00:00.000Z",
    registado_em: "2026-11-17T10:00:00.000Z",
    produtor: null,
    agregado: { tipo: "tenant", id: TENANT_A, seq: 1 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P0",
    finalidades: ["transacao"],
    payload: { vertical: "vendedor", onboarding_id: "44444444-4444-4444-8444-444444444444" },
    ...troca,
  } as Envelope;
}

describe("KAM-118 criterio 3 — o dono nasce do `tenant.provisioned`", () => {
  function montar(telefone: Telefone | null = new Telefone(DONO, PEPPER)) {
    const definidos: { tenantId: string; contactId: string; origem: string }[] = [];
    const efeito = efeitoDoProvisionamento({
      telefoneDoCaso: async () => telefone,
      // O `resolveContact` e idempotente pelo `phone_hmac`: o mesmo telefone,
      // o mesmo contacto.
      contacto: async ({ tenantId, telefone: t }) => ({ contactId: `${tenantId}:${t.hmac}` }),
      definirDono: async (pedido) => {
        definidos.push(pedido);
      },
    });
    return { efeito, definidos };
  }

  it("reentrega 3x pede sempre o mesmo contacto, com a origem do provisionamento", async () => {
    const m = montar();
    for (let i = 0; i < 3; i += 1) await m.efeito(null as never, envelope());
    assert.equal(new Set(m.definidos.map((d) => d.contactId)).size, 1);
    assert.ok(m.definidos.every((d) => d.origem === "provisionamento" && d.tenantId === TENANT_A));
  });

  it("o tenant e o do envelope, e nao do payload", async () => {
    const m = montar();
    await m.efeito(null as never, envelope({ payload: { vertical: "vendedor", onboarding_id: "x", tenant_id: TENANT_B } }));
    assert.equal(m.definidos[0]?.tenantId, TENANT_A);
  });

  it("outro evento ou outra versao vai para a DLQ, sem tocar no dono", async () => {
    const m = montar();
    await assert.rejects(m.efeito(null as never, envelope({ versao: 9 })), VersaoDoProvisionamentoError);
    await assert.rejects(m.efeito(null as never, envelope({ tipo: "tenant.activated" })), VersaoDoProvisionamentoError);
    assert.deepEqual(m.definidos, []);
  });

  it("sem telefone legivel no caso, nao ha dono — e o erro nao leva o identificador", async () => {
    const m = montar(null);
    await assert.rejects(m.efeito(null as never, envelope()), (erro: unknown) => {
      assert.ok(erro instanceof TelefoneDoCasoIndisponivelError);
      assert.ok(!String((erro as Error).message).includes("4444"));
      return true;
    });
    await assert.rejects(m.efeito(null as never, envelope({ payload: { vertical: "vendedor" } })), TelefoneDoCasoIndisponivelError);
    assert.deepEqual(m.definidos, []);
  });

  it("o consumidor nao usa o prefixo das verticais", () => {
    assert.ok(!CONSUMIDOR_DO_DONO.startsWith("agr_"));
  });
});

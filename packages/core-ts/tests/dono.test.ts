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

import {
  CONSUMIDOR_DO_DONO,
  canalDoDono,
  decidirProactiva,
  MOTIVOS_DE_SUPRESSAO,
  DESTINOS_DO_AVISO,
  efeitoDoProvisionamento,
  type OtpDaTroca,
  PAPEIS,
  PERSONAS,
  personaDe,
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

describe("KAM-118 criterio 8 — as mensagens ao dono no Piloto (decisao de 2026-11-18)", () => {
  it("dentro da janela e service message, sem template", () => {
    assert.deepEqual(decidirProactiva({ janelaAberta: true }), { accao: "service" });
  });

  it("fora da janela nada sai: 0 templates em 100 tentativas", () => {
    let saidas = 0;
    for (let i = 0; i < 100; i += 1) {
      const decisao = decidirProactiva({ janelaAberta: false });
      if (decisao.accao !== "suprimir") saidas += 1;
      else assert.equal(decisao.motivo, "fora_da_janela");
    }
    assert.equal(saidas, 0);
  });

  it("nao ha template ao dono no Piloto: a decisao so tem service e suprimir", () => {
    assert.deepEqual([...MOTIVOS_DE_SUPRESSAO], ["fora_da_janela"]);
    for (const janelaAberta of [true, false]) {
      assert.notEqual(decidirProactiva({ janelaAberta }).accao, "template");
    }
  });

  it("uma janela que nao se leu bem suprime — falha fechada", () => {
    for (const lida of [undefined, null, "true", 1]) {
      assert.deepEqual(
        decidirProactiva({ janelaAberta: lida as unknown as boolean }),
        { accao: "suprimir", motivo: "fora_da_janela" },
      );
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
    // Longe no futuro: desde o KAM-211 a troca esquece os pedidos expirados.
    return { enviado: true, expiraEm: new Date("2999-01-01T00:00:00.000Z") };
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

describe("KAM-211 — o mapa de pedidos da troca", () => {
  it("dois `pedir` concorrentes do mesmo pedido: o segundo recusa, e o telefone fica o do primeiro", async () => {
    // Um OTP lento, que grava o desafio antes de esperar pelo fornecedor, como o
    // real: sem a exclusao, o segundo sobrescrevia o desafio e o registo do
    // primeiro chegava por ultimo (achado 8 da revisao).
    let soltar: () => void = () => {};
    const parado = new Promise<void>((r) => {
      soltar = r;
    });
    const desafios: string[] = [];
    const trocas: { tenantId: string; contactId: string }[] = [];
    const contactos: string[] = [];
    const troca = new TrocaDeTelefone({
      otp: {
        async enviar(_chave: string, telefone: Telefone) {
          desafios.push(telefone.hmac);
          if (desafios.length === 1) await parado;
          return { enviado: true, expiraEm: new Date("2999-01-01T00:00:00.000Z") };
        },
        async verificar() {
          return "acertou";
        },
      },
      contacto: async ({ telefone }) => {
        contactos.push(telefone.hmac);
        return { contactId: "novo" };
      },
      trocar: async (pedido) => {
        trocas.push(pedido);
        return { anterior: null };
      },
      avisar: async () => {},
    });
    const x = new Telefone(OUTRO, PEPPER);
    const primeiro = troca.pedir("p1", TENANT_A, x);
    const segundo = await troca.pedir("p1", TENANT_A, new Telefone("+244 999 000 777", PEPPER));
    assert.deepEqual(segundo, { enviado: false, recusa: "intervalo" });
    soltar();
    assert.equal((await primeiro).enviado, true);
    assert.equal(desafios.length, 1);
    await troca.verificar("p1", TENANT_A, "123456");
    assert.deepEqual(contactos, [x.hmac]);
  });

  it("um pedido cujo desafio expirou sai do mapa no `pedir` seguinte", async () => {
    let agora = new Date("2026-11-18T10:00:00.000Z");
    const troca = new TrocaDeTelefone({
      relogio: () => agora,
      otp: {
        async enviar() {
          return { enviado: true, expiraEm: new Date(agora.getTime() + 300_000) };
        },
        async verificar() {
          return "errou";
        },
      },
      contacto: async () => ({ contactId: "x" }),
      trocar: async () => ({ anterior: null }),
      avisar: async () => {},
    });
    for (const id of ["p1", "p2", "p3"]) await troca.pedir(id, TENANT_A, new Telefone(OUTRO, PEPPER));
    assert.equal(troca.pedidosGuardados, 3);
    agora = new Date(agora.getTime() + 300_001);
    await troca.pedir("p4", TENANT_A, new Telefone(OUTRO, PEPPER));
    assert.equal(troca.pedidosGuardados, 1);
  });
});

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

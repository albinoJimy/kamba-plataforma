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
  efeitoDoProvisionamento,
  chaveDoDesafio,
  ESPERA_DA_TROCA_MS,
  type AlvoDoDesafio,
  type OtpDaTroca,
  PAPEIS,
  PERSONAS,
  personaDe,
  PRAZO_DO_PEDIDO_MS,
  TelefoneDoCasoIndisponivelError,
  TrocaDeTelefone,
  TrocasEmMemoria,
  VersaoDoProvisionamentoError,
} from "../src/dono/index.ts";
import type { Envelope } from "../src/eventos/envelope.ts";
import { Telefone } from "../src/inscricao/identificadores.ts";
import type { ResultadoDeEnvio, Veredicto } from "../src/inscricao/otp.ts";

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

/**
 * Um OTP falso, fiel a base: **um** desafio por troca, guardado com a chave, e
 * um codigo so verifica a chave guardada. Um envio recusado nao grava nada, como
 * o `Otp` real (que recusa antes do `guardar`).
 */
class OtpFalso implements OtpDaTroca {
  readonly enviados: string[] = [];
  readonly #desafios = new Map<string, string>();
  codigo = "123456";
  respostaAoErro: Veredicto = "errou";
  recusar = false;

  async enviar(alvo: AlvoDoDesafio): Promise<ResultadoDeEnvio> {
    if (this.recusar) return { enviado: false, recusa: "intervalo" };
    this.enviados.push(chaveDoDesafio(alvo));
    this.#desafios.set(alvo.changeId, chaveDoDesafio(alvo));
    return { enviado: true, expiraEm: new Date("2999-01-01T00:00:00.000Z") };
  }

  async verificar(alvo: AlvoDoDesafio, codigo: string): Promise<Veredicto> {
    if (this.#desafios.get(alvo.changeId) !== chaveDoDesafio(alvo)) return "sem_desafio";
    return codigo === this.codigo ? "acertou" : this.respostaAoErro;
  }
}

const TERCEIRO = "+244 999 000 103";
const INICIO = new Date("2026-11-19T10:00:00.000Z");
const HORA = 3_600_000;

/**
 * A troca com o repositorio em memoria e um papel por tenant. O contacto de um
 * numero e o seu HMAC, e o dono de cada tenant comeca por ser o `DONO`.
 */
function trocaFalsa() {
  const otp = new OtpFalso();
  const contactoDe = (t: Telefone): string => `c-${t.hmac.slice(0, 12)}`;
  const donos = new Map<string, string>([
    [TENANT_A, contactoDe(new Telefone(DONO, PEPPER))],
    [TENANT_B, contactoDe(new Telefone(DONO, PEPPER))],
  ]);
  const avisos: { tenantId: string; destino: string; momento: string }[] = [];
  const relogio = { agora: INICIO };
  const repositorio = new TrocasEmMemoria(async ({ tenantId, contactId }) => {
    const anterior = donos.get(tenantId) ?? null;
    donos.set(tenantId, contactId);
    return { anterior: anterior === contactId ? null : anterior };
  });
  const nova = (): TrocaDeTelefone =>
    new TrocaDeTelefone({
      otp,
      repositorio,
      relogio: () => relogio.agora,
      contacto: async ({ telefone }) => ({ contactId: contactoDe(telefone) }),
      avisar: async (pedido) => {
        avisos.push(pedido);
      },
    });
  return { otp, troca: nova(), nova, donos, avisos, relogio, repositorio, contactoDe };
}

const novo = (): Telefone => new Telefone(OUTRO, PEPPER);
const antigo = (): Telefone => new Telefone(DONO, PEPPER);

describe("KAM-223 — a troca com prova de posse (decisao 3 do fundador, opcao C)", () => {
  it("ate o OTP do numero novo acertar, nada muda e ninguem e avisado", async () => {
    const m = trocaFalsa();
    assert.deepEqual(await m.troca.pedir("p1", TENANT_A, novo()), {
      enviado: true,
      expiraEm: new Date("2999-01-01T00:00:00.000Z"),
    });
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, novo(), "000000"), {
      estado: "recusada",
      veredicto: "errou",
    });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    assert.deepEqual(m.avisos, []);
  });

  it("o OTP do numero novo poe a troca pendente 72 h e avisa, e o papel NAO muda", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    const desfecho = await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    assert.deepEqual(desfecho, { estado: "pendente", prazo: new Date(INICIO.getTime() + 72 * HORA) });
    assert.equal(ESPERA_DA_TROCA_MS, 72 * HORA);
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    assert.deepEqual(
      m.avisos.map((a) => `${a.destino}:${a.momento}`),
      ["numero_antigo:pendente", "email:pendente"],
    );
    // Os avisos nao levam numero nenhum: o tenant, o destino e o momento.
    assert.deepEqual(Object.keys(m.avisos[0] ?? {}).sort(), ["destino", "momento", "tenantId"]);
    assert.deepEqual(await m.troca.estado(TENANT_A), { estado: "pendente", prazo: new Date(INICIO.getTime() + 72 * HORA) });
  });

  it("um cookie roubado sem o OTP do antigo nao troca antes das 72 h, e troca depois", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    m.relogio.agora = new Date(INICIO.getTime() + 72 * HORA - 1);
    assert.deepEqual(await m.troca.concluir(TENANT_A), { estado: "recusada", veredicto: "cedo" });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    m.relogio.agora = new Date(INICIO.getTime() + 72 * HORA);
    assert.deepEqual(await m.troca.concluir(TENANT_A), {
      estado: "feita",
      contactId: m.contactoDe(novo()),
      anterior: m.contactoDe(antigo()),
    });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(novo()));
    assert.deepEqual(m.avisos.slice(2).map((a) => a.momento), ["feita", "feita"]);
    // Gasta-se: a segunda conclusao nao troca outra vez.
    assert.deepEqual(await m.troca.concluir(TENANT_A), { estado: "recusada", veredicto: "sem_pedido" });
  });

  it("com o OTP do numero antigo a troca e imediata", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    assert.equal((await m.troca.pedir("p1", TENANT_A, antigo(), "antigo")).enviado, true);
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, antigo(), "123456", "antigo"), {
      estado: "feita",
      contactId: m.contactoDe(novo()),
      anterior: m.contactoDe(antigo()),
    });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(novo()));
    assert.equal(await m.troca.estado(TENANT_A), null);
  });

  it("o codigo certo de um numero que NAO e o do dono nao troca, e desfaz-se tudo", async () => {
    // Quem tem o cookie e o seu proprio segundo numero nao prova o antigo.
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    const outro = new Telefone(TERCEIRO, PEPPER);
    await m.troca.pedir("p1", TENANT_A, outro, "antigo");
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, outro, "123456", "antigo"), {
      estado: "recusada",
      veredicto: "antigo_diferente",
    });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    assert.equal((await m.troca.estado(TENANT_A))?.estado, "pendente");
  });

  it("o numero antigo nao pode ser o novo", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    assert.deepEqual(await m.troca.pedir("p1", TENANT_A, novo(), "antigo"), { enviado: false, recusa: "numero" });
  });

  it("o codigo do antigo so vale para o numero a que foi enviado", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    await m.troca.pedir("p1", TENANT_A, new Telefone(TERCEIRO, PEPPER), "antigo");
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, antigo(), "123456", "antigo"), {
      estado: "recusada",
      veredicto: "numero",
    });
  });

  it("qualquer sessao do tenant cancela, e a troca cancelada ja nao se conclui", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    assert.equal(await m.troca.cancelar(TENANT_B), false);
    assert.equal(await m.troca.cancelar(TENANT_A), true);
    m.relogio.agora = new Date(INICIO.getTime() + 100 * HORA);
    assert.deepEqual(await m.troca.concluir(TENANT_A), { estado: "recusada", veredicto: "sem_pedido" });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    assert.deepEqual(m.avisos.slice(2).map((a) => a.momento), ["cancelada", "cancelada"]);
  });

  it("o numero novo so o verifica a sessao que o pediu, e so no seu tenant", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    for (const [pedido, tenant] of [["p2", TENANT_A], ["p1", TENANT_B]] as const) {
      assert.deepEqual(await m.troca.verificar(pedido, tenant, novo(), "123456"), {
        estado: "recusada",
        veredicto: "sem_pedido",
      });
    }
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, new Telefone(TERCEIRO, PEPPER), "123456"), {
      estado: "recusada",
      veredicto: "numero",
    });
    assert.deepEqual(m.avisos, []);
  });

  it("uma troca viva por tenant; a mesma sessao pode pedir outra vez", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    assert.deepEqual(await m.troca.pedir("p2", TENANT_A, novo()), { enviado: false, recusa: "ocupado" });
    assert.equal((await m.troca.pedir("p1", TENANT_A, new Telefone(TERCEIRO, PEPPER))).enviado, true);
    // O tenant B nao e afectado pela troca de A.
    assert.equal((await m.troca.pedir("p9", TENANT_B, novo())).enviado, true);
    // Uma `pedida` vencida deixa de contar.
    m.relogio.agora = new Date(INICIO.getTime() + PRAZO_DO_PEDIDO_MS);
    assert.equal((await m.troca.pedir("p2", TENANT_A, novo())).enviado, true);
  });

  it("a chave do desafio leva a troca, o numero e o HMAC do telefone", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    await m.troca.pedir("p1", TENANT_A, antigo(), "antigo");
    const [chaveNova, chaveAntiga] = m.otp.enviados;
    assert.equal(chaveNova, `troca:${chaveNova?.split(":")[1]}:novo:${novo().hmac.slice(0, 16)}`);
    assert.equal(chaveAntiga, `troca:${chaveNova?.split(":")[1]}:antigo:${antigo().hmac.slice(0, 16)}`);
  });

  it("achado 1: o codigo do segundo numero do atacante nao verifica o numero do dono, nem com o envio a este recusado", async () => {
    // O cookie roubado: o numero novo e o do atacante, e ele pede o «antigo» ao
    // seu segundo numero (recebe o codigo), e logo a seguir ao do dono, cujo envio
    // recusa por intervalo. O HMAC do antigo fica o do dono; o desafio, o do
    // segundo numero.
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    const segundo = new Telefone(TERCEIRO, PEPPER);
    assert.equal((await m.troca.pedir("p1", TENANT_A, segundo, "antigo")).enviado, true);
    m.otp.recusar = true;
    assert.deepEqual(await m.troca.pedir("p1", TENANT_A, antigo(), "antigo"), { enviado: false, recusa: "intervalo" });
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, antigo(), "123456", "antigo"), {
      estado: "recusada",
      veredicto: "sem_desafio",
    });
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(antigo()));
    assert.equal((await m.troca.estado(TENANT_A))?.estado, "pendente");
  });

  it("um OTP esgotado desiste do pedido", async () => {
    const m = trocaFalsa();
    m.otp.respostaAoErro = "tentativas";
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "000000");
    assert.deepEqual(await m.troca.verificar("p1", TENANT_A, novo(), "123456"), {
      estado: "recusada",
      veredicto: "sem_pedido",
    });
    assert.equal(await m.troca.estado(TENANT_A), null);
  });

  it("um processo novo sobre o mesmo repositorio continua a troca (o reinicio contra a base esta no tests_bd)", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    const depois = m.nova();
    m.relogio.agora = new Date(INICIO.getTime() + 72 * HORA);
    assert.equal((await depois.concluir(TENANT_A)).estado, "feita");
    assert.equal(m.donos.get(TENANT_A), m.contactoDe(novo()));
  });

  it("duas conclusoes concorrentes dao uma troca e uma recusa", async () => {
    const m = trocaFalsa();
    await m.troca.pedir("p1", TENANT_A, novo());
    await m.troca.verificar("p1", TENANT_A, novo(), "123456");
    m.relogio.agora = new Date(INICIO.getTime() + 72 * HORA);
    const [a, b] = await Promise.all([m.troca.concluir(TENANT_A), m.nova().concluir(TENANT_A)]);
    assert.deepEqual([a.estado, b.estado].sort(), ["feita", "recusada"]);
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

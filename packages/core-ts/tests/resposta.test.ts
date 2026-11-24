/**
 * A resposta do AGR, do lado de quem a entrega (KAM-224), sem base.
 *
 * O que aqui se mede é a **forma**: o *payload* que se aceita, o canal que cada
 * consumidor aplica, o `Pedido` que sai para o Outbound e o caminho da ligação
 * do `Saida`. A semântica contra o PostgreSQL e o `GraphFalso` — a RLS, a
 * reentrega e a DLQ — está em `tests_bd/resposta.bd.test.ts`.
 *
 * **O duplo da base lê o texto da instrução**: decide pelo `canal = 'whatsapp'`
 * e pelo `entregue_at IS NULL` escritos no SQL, e não pelos argumentos. Sem o
 * predicado do canal no texto, a resposta do painel saía pelo WhatsApp e o
 * ensaio fica vermelho.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import { Adiar } from "../src/eventos/consumo.ts";
import type { Envelope } from "../src/eventos/envelope.ts";
import { MAXIMO_DA_IMAGEM, type Pedido, type Resultado } from "../src/outbound/contrato.ts";
import { ObjectoInexistenteError, criarStorageFake } from "../src/storage/index.ts";
import {
  ArteRecusadaError,
  ArteSemLeitorError,
  CANAIS_DA_RESPOSTA,
  CanalSemCredencialError,
  ReenvioAdiadoError,
  RespostaInexistenteError,
  RespostaInvalidaError,
  SQL_ESTADO_DO_ENVIO,
  SQL_MARCAR_ENTREGUE,
  SQL_RESPOSTA_DO_PAINEL,
  SQL_RESPOSTA_DO_WHATSAPP,
  TIPO_DA_RESPOSTA,
  ESPERA_DO_REENVIO_S,
  arteDoSto,
  botoesDaLinha,
  chaveDaArte,
  chaveDaImagem,
  chaveDoReenvio,
  decidirEnvio,
  templateDaLinha,
  efeitoDoOutbound,
  efeitoDoPainel,
  envioPeloSaida,
  exigirJpeg,
  lerResposta,
  type DesfechoDaResposta,
} from "../src/resposta/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const OUTRO = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";
const CONTACTO = "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901";
const CONVERSA = "7a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d";
const CANAL = "5c6d7e8f-9a0b-4c1d-8e2f-3a4b5c6d7e8f";

interface Linha {
  reply_id: string;
  tenant: string;
  conversa: string;
  canal: string;
  chave: string;
  texto: string;
  botoes: unknown;
  template_nome: string | null;
  template_parametros: unknown;
  media_ref: string | null;
  turno_iniciado_em: Date | null;
  entregue_at: Date | null;
}

/** As linhas da `agent_replies`, e as instruções que chegaram. */
class BaseFalsa {
  readonly linhas: Linha[] = [];
  readonly instrucoes: string[] = [];
  /** A linha do Outbound por chave, para o `repetido`: o estado, ou a linha inteira. */
  readonly envios = new Map<string, string | Record<string, unknown>>();

  nova(sobrepor: Partial<Linha> = {}): Linha {
    const linha: Linha = {
      reply_id: randomUUID(),
      tenant: TENANT,
      conversa: CONVERSA,
      canal: "whatsapp",
      chave: "wamid.ensaio:0",
      texto: "Temos em stock.",
      botoes: [],
      template_nome: null,
      template_parametros: [],
      media_ref: null,
      turno_iniciado_em: new Date("2026-11-19T11:59:58Z"),
      entregue_at: null,
      ...sobrepor,
    };
    this.linhas.push(linha);
    return linha;
  }

  async query(sql: string, p: readonly unknown[] = []): Promise<{ rows: Record<string, unknown>[]; rowCount: number }> {
    this.instrucoes.push(sql);
    const [tenant, replyId, conversa] = p as string[];
    // Cada predicado so vale se estiver no texto da instrucao: sem o
    // `r.conversation_id = $3`, o `reply_id` de outra conversa casava.
    const daConversa = /conversation_id = \$3/.test(sql);
    const casa = (l: Linha) =>
      l.tenant === tenant && l.reply_id === replyId && (!daConversa || l.conversa === conversa);
    if (sql === SQL_ESTADO_DO_ENVIO) {
      const estado = this.envios.get(`${tenant}|${String(replyId)}`);
      // O duplo só devolve o `wamid` e o `error_code` se o SQL os pedir.
      const pede = /\bwamid\b/.test(sql) && /\berror_code\b/.test(sql);
      const linha = typeof estado === "string" ? { state: estado } : estado;
      const rows =
        linha === undefined
          ? []
          : [pede ? linha : { state: linha["state"] }];
      return { rows, rowCount: rows.length };
    }
    if (sql === SQL_RESPOSTA_DO_WHATSAPP || sql === SQL_RESPOSTA_DO_PAINEL) {
      const canal = sql.includes("r.canal = 'whatsapp'") ? "whatsapp" : sql.includes("r.canal = 'painel'") ? "painel" : null;
      const rows = this.linhas
        .filter((l) => casa(l) && (canal === null || l.canal === canal))
        .map((l) => ({
          reply_id: l.reply_id,
          chave: l.chave,
          contact_id: CONTACTO,
          conversation_id: l.conversa,
          texto: l.texto,
          botoes: l.botoes,
          // So com as colunas no texto da instrucao (KAM-221): sem elas, a
          // resposta de *template* saia como texto e o ensaio fica vermelho.
          ...(sql.includes("r.template_nome, r.template_parametros")
            ? { template_nome: l.template_nome, template_parametros: l.template_parametros }
            : {}),
          // KAM-246: a chave da arte so com a coluna no texto da instrucao.
          ...(sql.includes("r.media_ref") ? { media_ref: l.media_ref } : {}),
          turno_iniciado_em: l.turno_iniciado_em,
          entregue_at: l.entregue_at,
          channel_id: CANAL,
          phone_number_id: "109876543210987",
        }));
      return { rows, rowCount: rows.length };
    }
    if (sql === SQL_MARCAR_ENTREGUE) {
      const so = sql.includes("entregue_at IS NULL");
      const alvo = this.linhas.filter((l) => casa(l) && (!so || l.entregue_at === null));
      for (const l of alvo) l.entregue_at = new Date();
      return { rows: [], rowCount: alvo.length };
    }
    throw new Error(`instrucao sem semantica no duplo: ${sql.slice(0, 60)}`);
  }
}

function envelope(payload: Record<string, unknown>, tenant = TENANT, tipo = TIPO_DA_RESPOSTA): Envelope {
  const agora = new Date().toISOString();
  return {
    id: randomUUID(),
    tipo,
    versao: 1,
    tenant_id: tenant,
    ocorrido_em: agora,
    registado_em: agora,
    produtor: "ensaio",
    agregado: { tipo: "conversation", id: CONVERSA, seq: 1 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P0",
    finalidades: ["atendimento"],
    payload,
  } as Envelope;
}

function payload(linha: Linha, sobrepor: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    reply_id: linha.reply_id,
    thread_id: `${linha.tenant}:${CONTACTO}`,
    conversation_id: linha.conversa,
    contact_id: CONTACTO,
    canal: linha.canal,
    ...sobrepor,
  };
}

/** O Outbound visto pelo efeito: guarda os pedidos e devolve o resultado dado. */
function outbound(resultado: Resultado = { ok: true, id: "m1", wamid: "w1", kind: "service", repetido: false }) {
  const pedidos: Pedido[] = [];
  return {
    pedidos,
    enviar: async (pedido: Pedido): Promise<Resultado> => {
      pedidos.push(pedido);
      return resultado;
    },
  };
}

/** O Outbound que devolve, por ordem, os resultados dados; o último repete-se. */
function outboundEmSequencia(...resultados: (Resultado | Error)[]) {
  const pedidos: Pedido[] = [];
  return {
    pedidos,
    enviar: async (pedido: Pedido): Promise<Resultado> => {
      pedidos.push(pedido);
      const r = resultados[Math.min(pedidos.length, resultados.length) - 1]!;
      if (r instanceof Error) throw r;
      return r;
    },
  };
}

const ENVIADO: Resultado = { ok: true, id: "m1", wamid: "w1", kind: "service", repetido: false };
const REPETIDO: Resultado = { ok: true, id: "m1", wamid: null, kind: "service", repetido: true };

describe("lerResposta", () => {
  const base = { reply_id: randomUUID(), conversation_id: CONVERSA, contact_id: CONTACTO };

  it("aceita o payload do contrato, com o tenant do envelope", () => {
    const lido = lerResposta(TENANT, { ...base, thread_id: `${TENANT}:${CONTACTO}`, canal: "painel" });
    assert.equal(lido.canal, "painel");
    assert.equal(lido.threadId, `${TENANT}:${CONTACTO}`);
  });

  it("recusa um canal desconhecido, e não o trata como WhatsApp", () => {
    for (const canal of ["sms", "", null, undefined, "WHATSAPP"]) {
      assert.throws(
        () => lerResposta(TENANT, { ...base, thread_id: `${TENANT}:${CONTACTO}`, canal }),
        RespostaInvalidaError,
      );
    }
  });

  it("recusa um thread_id de outro tenant ou de outro contacto", () => {
    for (const thread of [`${OUTRO}:${CONTACTO}`, `${TENANT}:${randomUUID()}`, "x"]) {
      assert.throws(() => lerResposta(TENANT, { ...base, thread_id: thread, canal: "whatsapp" }), RespostaInvalidaError);
    }
  });

  it("recusa identificadores que não são uuid e um payload que não é objecto", () => {
    assert.throws(
      () => lerResposta(TENANT, { ...base, reply_id: "1; DROP", thread_id: `${TENANT}:${CONTACTO}`, canal: "whatsapp" }),
      RespostaInvalidaError,
    );
    for (const bruto of [null, [], "ola", 3]) assert.throws(() => lerResposta(TENANT, bruto), RespostaInvalidaError);
  });

  it("os canais são os dois do contrato", () => {
    assert.deepEqual([...CANAIS_DA_RESPOSTA], ["whatsapp", "painel"]);
  });
});

describe("botoesDaLinha", () => {
  it("lê a lista do jsonb, como objecto ou como texto", () => {
    const pares = [{ id: "falar_com_humano", titulo: "Falar com um colega" }];
    assert.deepEqual(botoesDaLinha(pares), pares);
    assert.deepEqual(botoesDaLinha(JSON.stringify(pares)), pares);
    assert.deepEqual(botoesDaLinha([]), []);
  });

  it("recusa um botão sem título ou sem id", () => {
    for (const mau of [[{ id: "x" }], [{ titulo: "x" }], [{ id: "", titulo: "x" }], {}, [null]]) {
      assert.throws(() => botoesDaLinha(mau), RespostaInvalidaError);
    }
  });
});

describe("templateDaLinha", () => {
  it("sem nome é texto livre; com nome leva os valores pela ordem", () => {
    assert.equal(templateDaLinha(null, []), null);
    assert.equal(templateDaLinha(undefined, undefined), null);
    assert.deepEqual(templateDaLinha("orcamento_pronto", ["ORC-ABCDEFGH"]), {
      nome: "orcamento_pronto",
      parametros: ["ORC-ABCDEFGH"],
    });
  });

  it("recusa parâmetros sem nome, um parâmetro que não é texto e um nome vazio", () => {
    for (const [nome, parametros] of [
      [null, ["x"]],
      ["orcamento_pronto", [3]],
      ["orcamento_pronto", "x"],
      ["", []],
    ] as const) {
      assert.throws(() => templateDaLinha(nome, parametros), RespostaInvalidaError);
    }
  });
});

describe("efeitoDoOutbound", () => {
  it("uma resposta de template sai como template, com os valores e o idioma base (KAM-221)", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ template_nome: "orcamento_pronto", template_parametros: ["ORC-ABCDEFGH"] });
    const saida = outbound({ ok: true, id: "m1", wamid: "w1", kind: "utility", repetido: false });
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.deepEqual(saida.pedidos[0]!.corpo, {
      tipo: "template",
      nome: "orcamento_pronto",
      idioma: "pt_PT",
      parametros: ["ORC-ABCDEFGH"],
    });
    assert.equal(saida.pedidos[0]!.idempotencyKey, linha.chave);
    assert.notEqual(linha.entregue_at, null);
    assert.deepEqual(desfechos, ["enviada"]);
  });

  it("o texto recusado com a janela fechada não troca para template: fica recusada (KAM-221)", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ chave: "orcamento:q1:1700000000000000" });
    const saida = outbound({ ok: false, motivo: "WINDOW_CLOSED", codigo: null });
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
    // Um pedido so, e de texto: quem reemite com o *template* e o AGR.
    assert.equal(saida.pedidos.length, 1);
    assert.equal(saida.pedidos[0]!.corpo.tipo, "texto");
    assert.equal(linha.entregue_at, null);
    assert.deepEqual(desfechos, ["recusada:WINDOW_CLOSED"]);
  });

  it("envia a resposta do WhatsApp uma vez, com a chave do turno, e marca-a entregue", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ botoes: [{ id: "falar_com_humano", titulo: "Falar com um colega" }] });
    const saida = outbound();
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.equal(saida.pedidos.length, 1);
    const pedido = saida.pedidos[0]!;
    assert.equal(pedido.tenantId, TENANT);
    assert.equal(pedido.idempotencyKey, "wamid.ensaio:0");
    assert.equal(pedido.channelId, CANAL);
    assert.equal(pedido.phoneNumberId, "109876543210987");
    assert.equal(pedido.doBot, true);
    assert.deepEqual(pedido.turnoIniciadoEm, new Date("2026-11-19T11:59:58Z"));
    assert.deepEqual(pedido.corpo, {
      tipo: "botoes",
      texto: "Temos em stock.",
      botoes: [{ id: "falar_com_humano", titulo: "Falar com um colega" }],
    });
    assert.notEqual(linha.entregue_at, null);
    assert.deepEqual(desfechos, ["enviada"]);
  });

  it("sem botões, o corpo é texto livre; sem início do turno, o pedido não o inventa", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ turno_iniciado_em: null });
    const saida = outbound();
    await efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha)));
    assert.deepEqual(saida.pedidos[0]!.corpo, { tipo: "texto", texto: "Temos em stock." });
    assert.equal("turnoIniciadoEm" in saida.pedidos[0]!, false);
  });

  it("uma resposta do painel não sai pelo WhatsApp, nem se lê", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel" });
    const saida = outbound();
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.equal(saida.pedidos.length, 0);
    assert.deepEqual(bd.instrucoes, []);
    assert.deepEqual(desfechos, ["de_outro_canal"]);
  });

  it("um evento que diz whatsapp sobre uma linha do painel não encontra linha", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel" });
    const saida = outbound();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha, { canal: "whatsapp" }))),
      RespostaInexistenteError,
    );
    assert.equal(saida.pedidos.length, 0);
  });

  it("a linha de outro tenant não se vê: lança, e não envia", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ tenant: OUTRO });
    const saida = outbound();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha, { thread_id: `${TENANT}:${CONTACTO}` }))),
      RespostaInexistenteError,
    );
    assert.equal(saida.pedidos.length, 0);
  });

  it("uma resposta já entregue não volta a sair", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ entregue_at: new Date() });
    const saida = outbound();
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.equal(saida.pedidos.length, 0);
    assert.deepEqual(desfechos, ["ja_entregue"]);
  });

  it("uma recusa do Outbound é desfecho: não lança e não marca entregue", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outbound({ ok: false, motivo: "WINDOW_CLOSED", codigo: null });
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
    assert.equal(linha.entregue_at, null);
    assert.deepEqual(desfechos, ["recusada:WINDOW_CLOSED"]);
  });

  it("uma chave repetida cuja linha do Outbound saiu conta como repetida e marca", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    bd.envios.set(`${TENANT}|${linha.chave}`, "delivered");
    const saida = outbound({ ok: true, id: "m1", wamid: "w1", kind: "service", repetido: true });
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.deepEqual(desfechos, ["repetida"]);
    assert.notEqual(linha.entregue_at, null);
  });

  it("uma chave repetida cuja linha ficou queued, failed ou sem linha reenvia uma vez, pela chave derivada (KAM-227)", async () => {
    for (const estado of ["queued", "failed", undefined]) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      if (estado !== undefined) bd.envios.set(`${TENANT}|${linha.chave}`, estado);
      const saida = outboundEmSequencia(REPETIDO, ENVIADO);
      const desfechos: DesfechoDaResposta[] = [];
      await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
      assert.deepEqual(
        saida.pedidos.map((p) => p.idempotencyKey),
        [linha.chave, chaveDoReenvio(linha.chave)],
      );
      assert.equal(chaveDoReenvio(linha.chave), `${linha.chave}:reenvio`);
      assert.deepEqual(desfechos, ["reenviada"]);
      assert.notEqual(linha.entregue_at, null);
      // O reenvio é o mesmo pedido, só com outra chave.
      assert.deepEqual({ ...saida.pedidos[1], idempotencyKey: linha.chave }, saida.pedidos[0]);
    }
  });

  it("uma chave que saiu nunca se reenvia: a linha sent, delivered ou read conta como repetida", async () => {
    for (const estado of ["sent", "delivered", "read"]) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      bd.envios.set(`${TENANT}|${linha.chave}`, estado);
      const saida = outboundEmSequencia(REPETIDO, ENVIADO);
      const desfechos: DesfechoDaResposta[] = [];
      await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
      assert.equal(saida.pedidos.length, 1);
      assert.deepEqual(desfechos, ["repetida"]);
    }
  });

  it("o reenvio é o último: falha, recusa ou repetida sem envio acabam ali, sem marcar", async () => {
    const casos: [Resultado, string, string | null][] = [
      [{ ok: false, motivo: "SEND_FAILED", codigo: 131000 }, "falhou:SEND_FAILED", null],
      [{ ok: false, motivo: "WINDOW_CLOSED", codigo: null }, "recusada:WINDOW_CLOSED", null],
      [REPETIDO, "repetida_sem_envio:queued", "queued"],
      [REPETIDO, "repetida_sem_envio:sem_linha", null],
    ];
    for (const [segundo, esperado, estadoDaDerivada] of casos) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      bd.envios.set(`${TENANT}|${linha.chave}`, "failed");
      if (estadoDaDerivada !== null) bd.envios.set(`${TENANT}|${chaveDoReenvio(linha.chave)}`, estadoDaDerivada);
      const saida = outboundEmSequencia(REPETIDO, segundo);
      const desfechos: string[] = [];
      await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
      assert.deepEqual(desfechos, [esperado]);
      assert.equal(saida.pedidos.length, 2, "nunca uma terceira vez");
      assert.equal(linha.entregue_at, null);
    }
  });

  it("uma chave derivada que já saiu conta como repetida, e marca", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    bd.envios.set(`${TENANT}|${linha.chave}`, "failed");
    bd.envios.set(`${TENANT}|${chaveDoReenvio(linha.chave)}`, "sent");
    const saida = outboundEmSequencia(REPETIDO, REPETIDO);
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.deepEqual(desfechos, ["repetida"]);
    assert.notEqual(linha.entregue_at, null);
  });

  it("uma falha que não saiu adia 60 s: o débito nosso, ou uma recusa da Meta com código", async () => {
    for (const [motivo, codigo] of [["SEND_FAILED", 131026], ["SEND_FAILED", 130429], ["RATE_LIMITED", null]] as const) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      const saida = outbound({ ok: false, motivo, codigo });
      const desfechos: string[] = [];
      await assert.rejects(
        efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha))),
        (erro: unknown) => {
          assert.ok(erro instanceof ReenvioAdiadoError);
          assert.equal(erro.motivo, motivo);
          // Um `Adiar` do KAM-006, com a espera do minuto do *token bucket*.
          assert.ok(erro instanceof Adiar);
          assert.equal(erro.segundos, ESPERA_DO_REENVIO_S);
          assert.equal(ESPERA_DO_REENVIO_S, 60);
          // Sem chave nem texto na mensagem: só o motivo.
          assert.doesNotMatch(erro.message, /wamid|stock/);
          return true;
        },
      );
      assert.deepEqual(desfechos, []);
      assert.equal(saida.pedidos.length, 1);
      assert.equal(linha.entregue_at, null);
    }
  });

  it("**uma falha ambígua não se reenvia**: timeout, rede, 200 sem wamid ou erro interno da Meta são falhou", async () => {
    for (const codigo of [-1, 1, 2]) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      const saida = outboundEmSequencia({ ok: false, motivo: "SEND_FAILED", codigo }, ENVIADO);
      const desfechos: string[] = [];
      await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
      assert.deepEqual(desfechos, ["falhou:SEND_FAILED"]);
      assert.equal(saida.pedidos.length, 1);
      assert.equal(linha.entregue_at, null);
    }
  });

  it("**uma linha com wamid nunca se reenvia**, nem failed: a Meta aceitou-a; nem um failed ambíguo", async () => {
    const casos: [Record<string, unknown>, string][] = [
      [{ state: "failed", wamid: "wamid.ACEITE", error_code: 131026 }, "repetida_sem_envio:failed"],
      [{ state: "queued", wamid: "wamid.ACEITE", error_code: null }, "repetida_sem_envio:queued"],
      [{ state: "failed", wamid: null, error_code: -1 }, "repetida_sem_envio:failed_ambiguo"],
      [{ state: "failed", wamid: null, error_code: 2 }, "repetida_sem_envio:failed_ambiguo"],
    ];
    for (const [linhaDoOutbound, esperado] of casos) {
      const bd = new BaseFalsa();
      const linha = bd.nova();
      bd.envios.set(`${TENANT}|${linha.chave}`, linhaDoOutbound);
      const saida = outboundEmSequencia(REPETIDO, ENVIADO);
      const desfechos: string[] = [];
      await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
      assert.deepEqual(desfechos, [esperado]);
      assert.equal(saida.pedidos.length, 1, "sem reenvio");
      assert.equal(linha.entregue_at, null);
    }
  });

  it("decidirEnvio: o wamid manda sobre o estado, e um código ambíguo não deixa reenviar", () => {
    assert.deepEqual(decidirEnvio(undefined), { saiu: false, podeReenviar: true, estado: "sem_linha" });
    assert.deepEqual(decidirEnvio({ state: "queued", wamid: null }), { saiu: false, podeReenviar: true, estado: "queued" });
    assert.deepEqual(decidirEnvio({ state: "failed", wamid: null, error_code: 131026 }), {
      saiu: false,
      podeReenviar: true,
      estado: "failed",
    });
    assert.deepEqual(decidirEnvio({ state: "failed", wamid: null, error_code: null }).podeReenviar, true);
    assert.deepEqual(decidirEnvio({ state: "failed", wamid: null, error_code: -1 }).podeReenviar, false);
    assert.deepEqual(decidirEnvio({ state: "failed", wamid: "w", error_code: 131026 }).podeReenviar, false);
    for (const estado of ["sent", "delivered", "read"]) {
      assert.deepEqual(decidirEnvio({ state: estado, wamid: "w" }), { saiu: true, podeReenviar: false, estado });
    }
    assert.equal(decidirEnvio({ state: "suppressed_by_human", wamid: null }).podeReenviar, false);
  });

  it("a falha na primeira tentativa reenvia na segunda: a linha failed da chave do turno passa à derivada", async () => {
    // As duas tentativas do consumo, como a escada do KAM-006 as faz: a
    // primeira levanta, e a segunda vê a chave do turno `failed` no `Saida`.
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outboundEmSequencia({ ok: false, motivo: "SEND_FAILED", codigo: 131000 }, REPETIDO, ENVIADO);
    const desfechos: DesfechoDaResposta[] = [];
    const efeito = efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) });
    await assert.rejects(efeito(bd, envelope(payload(linha))), ReenvioAdiadoError);
    bd.envios.set(`${TENANT}|${linha.chave}`, "failed");
    await efeito(bd, envelope(payload(linha)));
    assert.deepEqual(
      saida.pedidos.map((p) => p.idempotencyKey),
      [linha.chave, linha.chave, chaveDoReenvio(linha.chave)],
    );
    assert.deepEqual(desfechos, ["reenviada"]);
    assert.notEqual(linha.entregue_at, null);
  });

  it("um canal sem credencial é desfecho com o motivo: não lança, não reenvia, não marca", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outboundEmSequencia(new CanalSemCredencialError("sem_segredo"));
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(bd, envelope(payload(linha)));
    assert.deepEqual(desfechos, ["sem_credencial:sem_segredo"]);
    assert.equal(saida.pedidos.length, 1);
    assert.equal(linha.entregue_at, null);
  });

  it("o reply_id de outra conversa do mesmo tenant não se lê", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ conversa: randomUUID() });
    const saida = outbound();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha, { conversation_id: CONVERSA }))),
      RespostaInexistenteError,
    );
    assert.equal(saida.pedidos.length, 0);
  });

  it("um erro do envio sobe, para a escada do consumo repetir", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const enviar = async (): Promise<Resultado> => {
      throw new Error("base em baixo");
    };
    await assert.rejects(efeitoDoOutbound(enviar)(bd, envelope(payload(linha))), /base em baixo/);
    assert.equal(linha.entregue_at, null);
  });

  it("um evento de outro tipo ou com o contacto trocado não se aplica", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outbound();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha), TENANT, "query.handoff")),
      RespostaInvalidaError,
    );
    const outroContacto = randomUUID();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar)(
        bd,
        envelope(payload(linha, { contact_id: outroContacto, thread_id: `${TENANT}:${outroContacto}` })),
      ),
      RespostaInvalidaError,
    );
    assert.equal(saida.pedidos.length, 0);
  });
});

describe("efeitoDoPainel", () => {
  it("marca a resposta do painel entregue, uma vez", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel" });
    const desfechos: DesfechoDaResposta[] = [];
    const efeito = efeitoDoPainel({ aoTratar: (d) => desfechos.push(d) });
    await efeito(bd, envelope(payload(linha)));
    const primeira = linha.entregue_at;
    await efeito(bd, envelope(payload(linha)));
    assert.notEqual(primeira, null);
    assert.equal(linha.entregue_at, primeira);
    assert.deepEqual(desfechos, ["entregue_ao_painel", "ja_entregue"]);
  });

  it("ignora a resposta do WhatsApp sem tocar na base", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    await efeitoDoPainel()(bd, envelope(payload(linha)));
    assert.deepEqual(bd.instrucoes, []);
    assert.equal(linha.entregue_at, null);
  });

  it("o reply_id de outra conversa do mesmo tenant não se marca", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel", conversa: randomUUID() });
    await assert.rejects(
      efeitoDoPainel()(bd, envelope(payload(linha, { conversation_id: CONVERSA }))),
      RespostaInexistenteError,
    );
    assert.equal(linha.entregue_at, null);
  });

  it("sem linha deste tenant, lança", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel", tenant: OUTRO });
    await assert.rejects(
      efeitoDoPainel()(bd, envelope(payload(linha, { thread_id: `${TENANT}:${CONTACTO}` }))),
      RespostaInexistenteError,
    );
  });

  it("recusa um canal desconhecido", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ canal: "painel" });
    await assert.rejects(efeitoDoPainel()(bd, envelope(payload(linha, { canal: "email" }))), RespostaInvalidaError);
  });
});

describe("envioPeloSaida", () => {
  /**
   * Uma ligação que responde ao que o `Saida` pergunta com «sem janela», e guarda
   * as instruções e a transacção em que cada uma correu.
   */
  class LigacaoFalsa {
    readonly instrucoes: string[] = [];
    falharNo: RegExp | null = null;
    async query<T = Record<string, unknown>>(sql: string): Promise<{ readonly rows: readonly T[] }> {
      this.instrucoes.push(sql);
      if (this.falharNo !== null && this.falharNo.test(sql)) throw new Error("ligacao caiu");
      return { rows: [] as T[] };
    }
  }

  const pedido: Pedido = {
    tenantId: TENANT,
    channelId: CANAL,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    phoneNumberId: "109876543210987",
    idempotencyKey: "wamid.ensaio:0",
    corpo: { tipo: "texto", texto: "ola" },
    doBot: true,
    turnoIniciadoEm: new Date(),
  };

  function montar(ligacao: LigacaoFalsa) {
    const devolvidas: unknown[] = [];
    let chamadas = 0;
    const enviar = envioPeloSaida({
      tomar: async () => ligacao,
      devolver: (_l, erro) => {
        devolvidas.push(erro ?? "limpa");
      },
      meta: async () => ({
        enviar: async () => {
          chamadas += 1;
          return { ok: true, wamid: "w1" };
        },
      }),
      destinatario: async () => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0001", telefone: null }),
    });
    return { enviar, devolvidas, chamadas: () => chamadas };
  }

  it("cada instrução do Saida corre numa transacção sua, com o tenant local, e nunca de sessão", async () => {
    const ligacao = new LigacaoFalsa();
    const { enviar, devolvidas, chamadas } = montar(ligacao);
    const resultado = await enviar(pedido);
    // Sem janela na base falsa: o Saida recusa antes da rede.
    assert.deepEqual(resultado, { ok: false, motivo: "WINDOW_CLOSED", codigo: null });
    assert.equal(chamadas(), 0);
    assert.deepEqual(devolvidas, ["limpa"]);
    const doSaida = ligacao.instrucoes.filter(
      (s) => !/^(BEGIN|COMMIT|ROLLBACK)$/i.test(s.trim()) && !/set_config\('app\.tenant_id'/.test(s),
    );
    assert.ok(doSaida.length > 0, "o Saida perguntou pela janela");
    for (const sql of doSaida) {
      const i = ligacao.instrucoes.indexOf(sql);
      assert.match(ligacao.instrucoes[i - 1] ?? "", /set_config\('app\.tenant_id', \$1, true\)/);
      assert.match(ligacao.instrucoes[i - 2] ?? "", /^BEGIN$/i);
      assert.match(ligacao.instrucoes[i + 1] ?? "", /^COMMIT$/i);
    }
    assert.equal(ligacao.instrucoes.some((s) => /, false\)/.test(s)), false);
  });

  it("o tenant de cada instrução é o do pedido", async () => {
    const vistos: unknown[] = [];
    const ligacao = new LigacaoFalsa();
    const original = ligacao.query.bind(ligacao);
    ligacao.query = (async (sql: string, valores?: readonly unknown[]) => {
      if (/set_config/.test(sql)) vistos.push(valores?.[0]);
      return original(sql);
    }) as LigacaoFalsa["query"];
    await montar(ligacao).enviar(pedido);
    assert.ok(vistos.length > 0);
    assert.deepEqual(new Set(vistos), new Set([TENANT]));
  });

  it("o cliente do canal lê-se com a ligação e o canal do pedido, antes do Saida", async () => {
    const ligacao = new LigacaoFalsa();
    const vistos: unknown[] = [];
    const devolvidas: unknown[] = [];
    const enviar = envioPeloSaida({
      tomar: async () => ligacao,
      devolver: (_l, erro) => {
        devolvidas.push(erro ?? "limpa");
      },
      meta: async (l, canal) => {
        vistos.push(l, canal.tenantId, canal.channelId, canal.phoneNumberId, ligacao.instrucoes.length);
        throw new CanalSemCredencialError("nao_abre");
      },
      destinatario: async () => ({ bsuid: null, telefone: null }),
    });
    await assert.rejects(enviar(pedido), CanalSemCredencialError);
    assert.deepEqual(vistos, [ligacao, TENANT, CANAL, pedido.phoneNumberId, 0]);
    // Sem credencial, o Saida não chega a perguntar nada: a linha não nasce.
    assert.deepEqual(ligacao.instrucoes, []);
    // E a ligação volta limpa: a credencial em falta é do canal, não dela.
    assert.deepEqual(devolvidas, ["limpa"]);
  });

  it("o destinatário lê-se antes do Saida: a identidade em baixo sobe sem linha do Outbound", async () => {
    const ligacao = new LigacaoFalsa();
    const devolvidas: unknown[] = [];
    const enviar = envioPeloSaida({
      tomar: async () => ligacao,
      devolver: (_l, erro) => {
        devolvidas.push(erro ?? "limpa");
      },
      meta: async () => ({ enviar: async () => ({ ok: true, wamid: "w1" }) }),
      destinatario: async () => {
        throw new Error("identidade em baixo");
      },
    });
    await assert.rejects(enviar(pedido), /identidade em baixo/);
    assert.deepEqual(ligacao.instrucoes, [], "o Saida não gravou linha nenhuma");
    assert.equal(devolvidas.length, 1);
    assert.ok(devolvidas[0] instanceof Error);
  });

  it("uma ligação que falha volta com o erro, e o erro sobe", async () => {
    const ligacao = new LigacaoFalsa();
    ligacao.falharNo = /^BEGIN$/i;
    const { enviar, devolvidas } = montar(ligacao);
    await assert.rejects(enviar(pedido), /ligacao caiu/);
    assert.equal(devolvidas.length, 1);
    assert.ok(devolvidas[0] instanceof Error);
  });
});

describe("a arte como imagem, antes do texto (KAM-246)", () => {
  const ARTE = `t/${TENANT}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b`;
  const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);

  /** O leitor da arte, que conta as leituras e devolve o JPEG. */
  function leitor(bytes: Uint8Array = JPEG) {
    const lidas: string[] = [];
    return {
      lidas,
      lerArte: async (_tenant: string, chave: string) => {
        lidas.push(chave);
        return bytes;
      },
    };
  }

  it("a imagem sai primeiro, com a chave da imagem e os bytes do STO; o texto depois, com a do turno", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE, botoes: [{ id: "confirm:a1", titulo: "Aprovar" }] });
    const saida = outbound();
    const arte = leitor();
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { lerArte: arte.lerArte, aoTratar: (d) => desfechos.push(d) })(
      bd,
      envelope(payload(linha)),
    );
    assert.equal(saida.pedidos.length, 2);
    const [imagem, texto] = saida.pedidos;
    assert.equal(imagem!.idempotencyKey, chaveDaImagem(linha.chave));
    assert.deepEqual(imagem!.corpo, { tipo: "imagem", jpeg: JPEG });
    assert.equal(imagem!.doBot, true);
    assert.equal(texto!.idempotencyKey, linha.chave);
    assert.equal(texto!.corpo.tipo, "botoes");
    assert.deepEqual(arte.lidas, [ARTE]);
    assert.notEqual(linha.entregue_at, null);
    assert.deepEqual(desfechos, ["imagem_enviada", "enviada"]);
  });

  it("sem media_ref, nada muda: uma mensagem e nenhuma leitura do STO", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outbound();
    const arte = leitor();
    await efeitoDoOutbound(saida.enviar, { lerArte: arte.lerArte })(bd, envelope(payload(linha)));
    assert.equal(saida.pedidos.length, 1);
    assert.deepEqual(arte.lidas, []);
  });

  it("uma chave de outro tenant, de outra classe ou forjada: 0 leituras, 0 envios, e a resposta não se marca", async () => {
    const chaves = [
      `t/${OUTRO}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b`,
      `t/${TENANT}/foto/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b`,
      `t/${TENANT}/arte/2026/11/../../${OUTRO}`,
      "https://exemplo.invalid/arte.jpg",
    ];
    for (const media_ref of chaves) {
      const bd = new BaseFalsa();
      const linha = bd.nova({ media_ref });
      const saida = outbound();
      const arte = leitor();
      const desfechos: string[] = [];
      await efeitoDoOutbound(saida.enviar, { lerArte: arte.lerArte, aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(
        bd,
        envelope(payload(linha)),
      );
      assert.equal(saida.pedidos.length, 0, media_ref);
      assert.deepEqual(arte.lidas, [], media_ref);
      assert.equal(linha.entregue_at, null);
      assert.match(desfechos[0]!, /^arte_recusada:de_outr[ao]_/);
    }
  });

  it("o leitor recusa um objecto que não é JPEG: 0 envios", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outbound();
    const desfechos: string[] = [];
    const lerArte = async () => exigirJpeg(new Uint8Array([0x89, 0x50, 0x4e, 0x47]));
    await efeitoDoOutbound(saida.enviar, { lerArte, aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(
      bd,
      envelope(payload(linha)),
    );
    assert.equal(saida.pedidos.length, 0);
    assert.deepEqual(desfechos, ["arte_recusada:nao_e_jpeg"]);
  });

  it("um objecto que a retenção já apagou não prende o texto: sai a legenda, sem a imagem", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outbound();
    const desfechos: string[] = [];
    const lerArte = async (): Promise<Uint8Array> => {
      throw new ObjectoInexistenteError();
    };
    await efeitoDoOutbound(saida.enviar, { lerArte, aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(
      bd,
      envelope(payload(linha)),
    );
    assert.equal(saida.pedidos.length, 1);
    assert.notEqual(saida.pedidos[0]?.corpo.tipo, "imagem");
    assert.equal(desfechos[0], "imagem_nao_enviada:arte_inexistente");
    assert.notEqual(linha.entregue_at, null, "o texto saiu, e marca a resposta");
  });

  it("o STO em baixo recua pela escada, e nada sai", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outbound();
    const lerArte = async (): Promise<Uint8Array> => {
      throw new Error("sto em baixo");
    };
    await assert.rejects(efeitoDoOutbound(saida.enviar, { lerArte })(bd, envelope(payload(linha))), /sto em baixo/);
    assert.equal(saida.pedidos.length, 0);
  });

  it("sem leitor da arte, recua pela escada e nada sai", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outbound();
    await assert.rejects(efeitoDoOutbound(saida.enviar)(bd, envelope(payload(linha))), ArteSemLeitorError);
    assert.equal(saida.pedidos.length, 0);
  });

  it("uma imagem com template é uma linha sem forma, e nada sai", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE, template_nome: "orcamento_pronto", template_parametros: ["x"] });
    const saida = outbound();
    await assert.rejects(
      efeitoDoOutbound(saida.enviar, { lerArte: leitor().lerArte })(bd, envelope(payload(linha))),
      RespostaInvalidaError,
    );
    assert.equal(saida.pedidos.length, 0);
  });

  it("a imagem que se sabe não ter saído adia a resposta inteira: o texto não sai antes dela", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outbound({ ok: false, motivo: "RATE_LIMITED", codigo: null });
    await assert.rejects(
      efeitoDoOutbound(saida.enviar, { lerArte: leitor().lerArte })(bd, envelope(payload(linha))),
      ReenvioAdiadoError,
    );
    assert.equal(saida.pedidos.length, 1);
    assert.equal(saida.pedidos[0]!.corpo.tipo, "imagem");
    assert.equal(linha.entregue_at, null);
  });

  it("na volta seguinte, a imagem que não saiu reenvia-se pela chave derivada, e o texto sai", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    // A primeira volta deixou a linha da imagem `failed` com o código do carregamento, que não é ambíguo.
    bd.envios.set(`${TENANT}|${chaveDaImagem(linha.chave)}`, { state: "failed", wamid: null, error_code: -2 });
    const saida = outboundEmSequencia(REPETIDO, ENVIADO, ENVIADO);
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { lerArte: leitor().lerArte, aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(
      bd,
      envelope(payload(linha)),
    );
    assert.deepEqual(
      saida.pedidos.map((p) => p.idempotencyKey),
      [chaveDaImagem(linha.chave), chaveDoReenvio(chaveDaImagem(linha.chave)), linha.chave],
    );
    assert.deepEqual(desfechos, ["imagem_enviada:reenviada", "enviada:undefined"]);
    assert.notEqual(linha.entregue_at, null);
  });

  it("entregar duas vezes envia uma imagem: a que já saiu não se lê nem se envia outra vez", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    bd.envios.set(`${TENANT}|${chaveDaImagem(linha.chave)}`, { state: "sent", wamid: "w0", error_code: null });
    const saida = outbound();
    const arte = leitor();
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { lerArte: arte.lerArte, aoTratar: (d) => desfechos.push(d) })(
      bd,
      envelope(payload(linha)),
    );
    assert.deepEqual(arte.lidas, []);
    assert.deepEqual(
      saida.pedidos.map((p) => p.corpo.tipo),
      ["texto"],
    );
    assert.deepEqual(desfechos, ["imagem_enviada", "enviada"]);
  });

  it("uma imagem que não sai por decisão (a janela) fica registada, e o texto segue para o Saida decidir", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE });
    const saida = outboundEmSequencia({ ok: false, motivo: "WINDOW_CLOSED", codigo: null });
    const desfechos: string[] = [];
    await efeitoDoOutbound(saida.enviar, { lerArte: leitor().lerArte, aoTratar: (d, m) => desfechos.push(`${d}:${m}`) })(
      bd,
      envelope(payload(linha)),
    );
    assert.deepEqual(desfechos, ["imagem_nao_enviada:recusada:WINDOW_CLOSED", "recusada:WINDOW_CLOSED"]);
    assert.equal(linha.entregue_at, null, "fora da janela, nada se marca entregue");
  });

  it("a resposta já entregue não lê a arte nem envia nada", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova({ media_ref: ARTE, entregue_at: new Date() });
    const saida = outbound();
    const arte = leitor();
    await efeitoDoOutbound(saida.enviar, { lerArte: arte.lerArte })(bd, envelope(payload(linha)));
    assert.equal(saida.pedidos.length, 0);
    assert.deepEqual(arte.lidas, []);
  });
});

describe("arteDoSto e chaveDaArte (KAM-246)", () => {
  const CHAVE = `t/${TENANT}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b`;
  const PRAZO = new Date("2027-01-01T00:00:00Z");

  it("a chave é do tenant e da classe arte, ou recusa com o motivo", () => {
    assert.equal(chaveDaArte(TENANT, CHAVE), CHAVE);
    assert.throws(() => chaveDaArte(OUTRO, CHAVE), (e: unknown) => e instanceof ArteRecusadaError && e.motivo === "de_outro_tenant");
    assert.throws(
      () => chaveDaArte(TENANT, CHAVE.replace("/arte/", "/foto/")),
      (e: unknown) => e instanceof ArteRecusadaError && e.motivo === "de_outra_classe",
    );
    for (const ma of ["", "arte.jpg", `${CHAVE}/x`, CHAVE.toUpperCase()]) {
      assert.throws(() => chaveDaArte(TENANT, ma), ArteRecusadaError);
    }
  });

  it("lê o JPEG do STO do tenant, tal e qual (sem o recodificar)", async () => {
    const { storage: sto } = criarStorageFake();
    const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe1, 9, 8, 7, 6]);
    await sto.put({ tenantId: TENANT }, CHAVE, jpeg, { contentType: "image/jpeg", classe: "arte", retainUntil: PRAZO });
    const lidos = await arteDoSto(sto)(TENANT, CHAVE);
    assert.deepEqual([...lidos], [...jpeg]);
  });

  it("recusa outro tipo de conteúdo, um objecto acima do tecto e bytes que não são JPEG", async () => {
    const { storage: sto } = criarStorageFake();
    const ctx = { tenantId: TENANT };
    const outra = (fim: string) => CHAVE.replace(/[0-9a-f]{12}$/, fim);
    await sto.put(ctx, outra("000000000001"), new Uint8Array([0x89, 0x50]), { contentType: "image/png", classe: "arte", retainUntil: PRAZO });
    await assert.rejects(
      arteDoSto(sto)(TENANT, outra("000000000001")),
      (e: unknown) => e instanceof ArteRecusadaError && e.motivo === "nao_e_jpeg",
    );
    await sto.put(ctx, outra("000000000002"), new Uint8Array(MAXIMO_DA_IMAGEM + 1).fill(0xff), {
      contentType: "image/jpeg",
      classe: "arte",
      retainUntil: PRAZO,
    });
    await assert.rejects(
      arteDoSto(sto)(TENANT, outra("000000000002")),
      (e: unknown) => e instanceof ArteRecusadaError && e.motivo === "fora_do_tamanho",
    );
    await sto.put(ctx, outra("000000000003"), new Uint8Array([1, 2, 3]), { contentType: "image/jpeg", classe: "arte", retainUntil: PRAZO });
    await assert.rejects(
      arteDoSto(sto)(TENANT, outra("000000000003")),
      (e: unknown) => e instanceof ArteRecusadaError && e.motivo === "nao_e_jpeg",
    );
  });

  it("uma chave de outro tenant não chega ao STO", async () => {
    let tocou = false;
    const { storage: sto } = criarStorageFake();
    const espiao = {
      ...sto,
      head: async (...a: Parameters<typeof sto.head>) => {
        tocou = true;
        return sto.head(...a);
      },
    };
    await assert.rejects(arteDoSto(espiao)(OUTRO, CHAVE), ArteRecusadaError);
    assert.equal(tocou, false);
  });
});

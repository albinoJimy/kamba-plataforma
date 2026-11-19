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

import type { Envelope } from "../src/eventos/envelope.ts";
import type { Pedido, Resultado } from "../src/outbound/contrato.ts";
import {
  CANAIS_DA_RESPOSTA,
  RespostaInexistenteError,
  RespostaInvalidaError,
  SQL_CONTEXTO_DE_SESSAO,
  SQL_LIMPAR_CONTEXTO,
  SQL_MARCAR_ENTREGUE,
  SQL_RESPOSTA_DO_PAINEL,
  SQL_RESPOSTA_DO_WHATSAPP,
  TIPO_DA_RESPOSTA,
  botoesDaLinha,
  efeitoDoOutbound,
  efeitoDoPainel,
  envioPeloSaida,
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
  turno_iniciado_em: Date | null;
  entregue_at: Date | null;
}

/** As linhas da `agent_replies`, e as instruções que chegaram. */
class BaseFalsa {
  readonly linhas: Linha[] = [];
  readonly instrucoes: string[] = [];

  nova(sobrepor: Partial<Linha> = {}): Linha {
    const linha: Linha = {
      reply_id: randomUUID(),
      tenant: TENANT,
      conversa: CONVERSA,
      canal: "whatsapp",
      chave: "wamid.ensaio:0",
      texto: "Temos em stock.",
      botoes: [],
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
    const casa = (l: Linha) =>
      l.tenant === tenant && l.reply_id === replyId && (conversa === undefined || l.conversa === conversa);
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

describe("efeitoDoOutbound", () => {
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

  it("um envio repetido pelo Outbound conta como repetido e marca", async () => {
    const bd = new BaseFalsa();
    const linha = bd.nova();
    const saida = outbound({ ok: true, id: "m1", wamid: "w1", kind: "service", repetido: true });
    const desfechos: DesfechoDaResposta[] = [];
    await efeitoDoOutbound(saida.enviar, { aoTratar: (d) => desfechos.push(d) })(bd, envelope(payload(linha)));
    assert.deepEqual(desfechos, ["repetida"]);
    assert.notEqual(linha.entregue_at, null);
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
  /** Uma ligação que responde ao que o `Saida` pergunta com «sem janela». */
  class LigacaoFalsa {
    readonly instrucoes: string[] = [];
    falharNo: string | null = null;
    async query<T = Record<string, unknown>>(sql: string): Promise<{ readonly rows: readonly T[] }> {
      this.instrucoes.push(sql);
      if (this.falharNo !== null && sql === this.falharNo) throw new Error("ligacao caiu");
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
      meta: {
        enviar: async () => {
          chamadas += 1;
          return { ok: true, wamid: "w1" };
        },
      },
      destinatario: async () => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0001", telefone: null }),
    });
    return { enviar, devolvidas, chamadas: () => chamadas };
  }

  it("põe o tenant de sessão antes do Saida e limpa-o antes de devolver a ligação", async () => {
    const ligacao = new LigacaoFalsa();
    const { enviar, devolvidas, chamadas } = montar(ligacao);
    const resultado = await enviar(pedido);
    // Sem janela na base falsa: o Saida recusa antes da rede.
    assert.deepEqual(resultado, { ok: false, motivo: "WINDOW_CLOSED", codigo: null });
    assert.equal(chamadas(), 0);
    assert.equal(ligacao.instrucoes[0], SQL_CONTEXTO_DE_SESSAO);
    assert.equal(ligacao.instrucoes.at(-1), SQL_LIMPAR_CONTEXTO);
    assert.deepEqual(devolvidas, ["limpa"]);
  });

  it("uma ligação que falha volta com o erro, e o erro sobe", async () => {
    const ligacao = new LigacaoFalsa();
    ligacao.falharNo = SQL_CONTEXTO_DE_SESSAO;
    const { enviar, devolvidas } = montar(ligacao);
    await assert.rejects(enviar(pedido), /ligacao caiu/);
    assert.equal(devolvidas.length, 1);
    assert.ok(devolvidas[0] instanceof Error);
    assert.equal(ligacao.instrucoes.includes(SQL_LIMPAR_CONTEXTO), false);
  });

  it("se a limpeza falha, a ligação volta marcada", async () => {
    const ligacao = new LigacaoFalsa();
    ligacao.falharNo = SQL_LIMPAR_CONTEXTO;
    const { enviar, devolvidas } = montar(ligacao);
    await enviar(pedido);
    assert.ok(devolvidas[0] instanceof Error);
  });
});

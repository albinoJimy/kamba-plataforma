/**
 * As *fixtures* assinadas do KAM-024 contra o tratador da coexistência
 * (KAM-017, «Testes Requeridos: contrato com *fixtures* do simulador»).
 *
 * **Confirma-se no código o que o simulador já gera antes de escrever *fixture*
 * nova**, e o resultado dessa confirmação é esta bateria: o `tools/meta-sim`
 * cobre `history`, `smb_app_state_sync`, `smb_message_echoes`, `account_update`
 * com os **seis** motivos como itens próprios da tabela de cobertura, e o erro
 * **2593109** dentro do `history`. Nada disto se reescreve aqui.
 *
 * O que esta bateria faz é o **caminho inteiro**: pega no corpo que o simulador
 * monta, passa-o pela explosão do KAM-013, e dá o resultado ao tratador deste
 * ticket. É o único sítio onde se vê que os três módulos concordam sobre a
 * forma do corpo — e foi aqui que se descobriu que o `history` do simulador
 * traz **sempre** o erro 2593109 ao lado das mensagens, o que é uma
 * contradição que a Meta não manda (ver `semHistorico` abaixo).
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MOTIVOS_DE_REMOCAO,
  CODIGOS_CONFIRMADOS,
  Gerador,
  canalDe,
  corpo,
  interlocutorDe,
  valorDe,
} from "@kamba/meta-sim";

import {
  CODIGO_SEM_HISTORICO,
  Coexistente,
  MOTIVOS_DE_DESLIGAMENTO,
  MetricasDaCoexistencia,
  traduzirMotivo,
} from "../src/coexistencia/index.ts";
import {
  ARRAY_DOS_ECHOES,
  CAMPO_DO_DESTINATARIO,
  explodir,
} from "../src/entrada/index.ts";
import { BaseFalsa } from "./coexistencia.base_falsa.ts";

const TENANT = "11111111-1111-7111-8111-111111111111";
const CANAL = "33333333-3333-7333-8333-333333333333";
const T0 = new Date("2026-10-01T00:00:00Z");

function montar() {
  const g = new Gerador("kam017/fixtures");
  const canal = canalDe(g);
  const quem = interlocutorDe(g);
  const bd = new BaseFalsa();
  bd.semearCanal(TENANT, {
    channel_id: CANAL,
    channel_mode: "coexistencia",
    phone_number_id: canal.phoneNumberId,
  });
  const transicoes: string[] = [];
  const emitidos: string[] = [];
  const metricas = new MetricasDaCoexistencia();
  const coex = new Coexistente({
    emitirCanalActualizado: async (_c, _t, _ch, _n, motivo) => {
      emitidos.push(String(motivo));
      return `evt-${emitidos.length}`;
    },
    emitirAviso: async () => "evt",
    contacto: async (p) => ({ contactId: `c-${p.telefone ?? p.bsuid}` }),
    conversa: async (p) => `conv-${p.contactId}`,
    transitar: async (_t, c) => {
      transicoes.push(c);
    },
    metricas,
    agora: () => T0,
  });
  return { g, canal, quem, bd, coex, metricas, transicoes, emitidos };
}

/** O `value` de um campo, como o simulador o monta. */
function valor(
  g: Gerador,
  campo: Parameters<typeof valorDe>[1],
  canal: ReturnType<typeof canalDe>,
  quem: ReturnType<typeof interlocutorDe>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return valorDe(g, campo, { canal, quem, ...extra });
}

describe("as fixtures do KAM-024 contra o tratador da coexistencia", () => {
  it("o corpo que o simulador assina explode em eventos com os kinds certos", () => {
    const { g, canal, quem } = montar();
    const montado = corpo(g, {
      canal,
      mudancas: [{ campo: "history", opcoes: { canal, quem } }],
    });
    const explosao = explodir(montado, "resumo-de-ensaio");
    assert.deepEqual(
      explosao.eventos.map((e) => e.kind),
      ["history"],
    );
    assert.equal(explosao.quarentena.length, 0);
  });

  it("o echo do simulador traz o destinatario no campo que este ticket fixou", () => {
    // **A confirmacao da proposta, dos dois lados.** O `CAMPO_DO_DESTINATARIO`
    // e `to`, e o simulador emite `to`: o que este teste prende e que os dois
    // continuam a dizer o mesmo. Se a Meta desmentir a proposta, muda-se o
    // `explosao.ts` e este teste e o primeiro a cair.
    const { g, canal, quem } = montar();
    const v = valor(g, "smb_message_echoes", canal, quem);
    const echoes = v[ARRAY_DOS_ECHOES] as Record<string, unknown>[];
    assert.ok(Array.isArray(echoes) && echoes.length > 0);
    assert.equal(typeof echoes[0]?.[CAMPO_DO_DESTINATARIO], "string");
  });

  it("um echo do simulador resolve interlocutor e chega ao tratador do KAM-018", async () => {
    const { g, canal, quem, bd, coex, transicoes } = montar();
    const montado = corpo(g, {
      canal,
      mudancas: [{ campo: "smb_message_echoes", opcoes: { canal, quem } }],
    });
    const explosao = explodir(montado, "resumo-de-ensaio");
    const evento = explosao.eventos.find((e) => e.kind === "echo");
    assert.ok(evento !== undefined, "o simulador nao gerou um echo");
    // **O interlocutor ja nao e `null`**, que e o que este ticket mudou.
    assert.ok(evento.interlocutor !== null);
    assert.equal(typeof evento.interlocutor.telefone, "string");
    assert.equal(evento.interlocutor.bsuid, null);

    const resolvido = await coex.canal(bd, TENANT, canal.phoneNumberId);
    assert.ok(resolvido !== null);
    await coex.abrir(bd, TENANT, resolvido);
    const r = await coex.tratarEcho(bd, TENANT, resolvido, {
      wamid: evento.eventKey,
      destinatario: evento.interlocutor,
    });
    assert.equal(r.desfecho, "do_dono");
    assert.equal(transicoes.length, 1);
  });

  it("o history do simulador traz o 2593109 que o criterio 4 nomeia", () => {
    const { g, canal, quem } = montar();
    const v = valor(g, "history", canal, quem);
    const lotes = v["history"] as Record<string, unknown>[];
    const erros = lotes[0]?.["errors"] as Record<string, unknown>[];
    assert.equal(erros[0]?.["code"], CODIGO_SEM_HISTORICO);
    // E o nosso numero e o mesmo que o simulador declara **CONFIRMADO**.
    assert.equal(CODIGOS_CONFIRMADOS.semHistorico, CODIGO_SEM_HISTORICO);
  });

  it("o lote de history com o 2593109 fecha em sincronizado_sem_historico", async () => {
    const { g, canal, quem, bd, coex } = montar();
    const v = valor(g, "history", canal, quem);
    const lotes = v["history"] as Record<string, unknown>[];
    const erros = (lotes[0]?.["errors"] as Record<string, unknown>[]).map(
      (e) => Number(e["code"]),
    );
    const resolvido = await coex.canal(bd, TENANT, canal.phoneNumberId);
    assert.ok(resolvido !== null);
    await coex.abrir(bd, TENANT, resolvido);
    const r = await coex.ingerirHistorico(bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros,
    });
    assert.equal(r.estado, "sincronizado_sem_historico");
  });

  it("o state_sync do simulador traz um contacto com telefone", () => {
    const { g, canal, quem } = montar();
    const v = valor(g, "smb_app_state_sync", canal, quem);
    const sync = v["state_sync"] as Record<string, unknown>[];
    const contacto = sync[0]?.["contact"] as Record<string, unknown>;
    assert.equal(typeof contacto["phone_number"], "string");
    // **O `full_name` existe e nao se usa**: o que a ingestao passa a porta do
    // KAM-008 e o telefone, e o que fica guardado e o `contact_id`. Um nome
    // guardado era dado pessoal sem necessidade (ADR-010).
    assert.equal(typeof contacto["full_name"], "string");
  });

  it("os seis motivos de PARTNER_REMOVED chegam ao tratador pela fixture", async () => {
    // **Os seis, um a um**, e nao um `g.escolher`: o KAM-024 tem uma *fixture*
    // por motivo e uma marca de cobertura por motivo, e a revisao adversarial
    // dele pagou exactamente este defeito pelo outro lado (a primeira versao
    // gerava um motivo so, e quatro dos seis nao tinham teste).
    for (const bruto of MOTIVOS_DE_REMOCAO) {
      const { g, canal, quem, bd, coex, emitidos } = montar();
      const v = valor(g, "account_update", canal, quem, { motivo: bruto });
      assert.equal(v["event"], "PARTNER_REMOVED");
      const info = v["partner_removed_info"] as Record<string, unknown>;
      assert.equal(info["reason"], bruto);

      const resolvido = await coex.canal(bd, TENANT, canal.phoneNumberId);
      assert.ok(resolvido !== null);
      await coex.abrir(bd, TENANT, resolvido);
      const r = await coex.tratarAccountUpdate(bd, TENANT, resolvido, {
        evento: v["event"],
        motivo: info["reason"],
      });
      assert.equal(r.desligou, true, `o motivo ${bruto} nao desligou o canal`);
      assert.equal(r.motivo, traduzirMotivo(bruto));
      assert.deepEqual(emitidos, [traduzirMotivo(bruto)]);
    }
  });

  it("os seis motivos do simulador e os seis do dicionario sao o mesmo conjunto", () => {
    // Nos **dois** sentidos, e nao so num: um motivo a mais no simulador e uma
    // *fixture* que nenhum tratador trata, e um a mais aqui e um `CHECK` que
    // nunca se escreve. E a mesma forma do confronto de dominios da `0018`.
    assert.deepEqual(
      [...MOTIVOS_DE_REMOCAO].map((m) => traduzirMotivo(m)).sort(),
      [...MOTIVOS_DE_DESLIGAMENTO].sort(),
    );
  });

  it("um history **sem** o 2593109 nao existe na fixture, e isso fica dito", () => {
    // **O achado desta bateria.** O `history` do simulador traz, no mesmo lote,
    // `threads` com uma mensagem **e** `errors` com o 2593109 — isto e, diz ao
    // mesmo tempo «aqui esta o historico» e «o cliente nao partilhou
    // historico». A Meta nao manda as duas coisas juntas.
    //
    // **Nao se corrige o simulador neste ticket**, e a razao e a que o KAM-016
    // escreveu pelo outro lado: alargar o simulador para servir o cliente e
    // provar o cliente contra uma superficie alargada para lhe servir. O que
    // se faz e declarar, e o tratador le a lista de erros **do lote** — pelo
    // que o caminho «com historico» exercita-se com a lista vazia, que e o que
    // o `coexistencia.test.ts` faz.
    //
    // Fica em `docs/dividas-documentais.md` como divida do KAM-024.
    const { g, canal, quem } = montar();
    const v = valor(g, "history", canal, quem);
    const lotes = v["history"] as Record<string, unknown>[];
    assert.ok(Array.isArray(lotes[0]?.["threads"]));
    assert.ok(Array.isArray(lotes[0]?.["errors"]));
  });
});

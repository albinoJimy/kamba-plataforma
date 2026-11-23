/**
 * Os telefones para a exportação do off-boarding (KAM-233, critério 3; decisões
 * do fundador de 2026-11-21, Q2 = B, e de 2026-11-22, Q2b = A).
 *
 * Contra duplos que lêem o **texto**: a consulta dos contactos, a linha de
 * auditoria no `antes` (e nunca com o telefone), o objecto no STO (os três
 * campos, a classe e o prazo), e a fase `pendentes` a guardar a chave só
 * quando fecha. O que só a base prova está em `tests_bd/offboarding.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ContactoApagadoError, type OpcoesDaLeitura } from "../src/identity/index.ts";
import {
  FASES,
  SQL_FASES,
  SQL_MARCAR_FASE,
  SQL_PENDENTES,
  prazos,
  verificarPendentes,
  type ClienteSql,
} from "../src/offboarding/index.ts";
import {
  ACCAO_DOS_TELEFONES,
  CLASSE_DOS_TELEFONES,
  SQL_AUDITAR_TELEFONES,
  SQL_CONTACTOS_DO_TENANT,
  telefonesPeloCofre,
  textoDaAuditoria,
  type PortaDosTelefones,
} from "../src/offboarding/telefones.ts";
import { SQL_DEFINIR_CONTEXTO } from "../src/tenant_guard/index.ts";

const T = "11111111-1111-4111-8111-111111111111";
const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const D0 = new Date("2026-10-01T09:00:00Z");
// Fictícios, com o 999 que a UIT não atribui (inventário do gate 7).
const TELEFONE_A = "+244999000111";
const TELEFONE_B = "+244999000222";

/** Uma ligação que regista cada instrução, e responde à listagem dos contactos. */
function ligacaoEspia(contactos: string[]) {
  const instrucoes: { sql: string; valores: readonly unknown[] }[] = [];
  const devolvida: unknown[] = [];
  const ligacao = {
    async query(sql: string, valores: readonly unknown[] = []) {
      instrucoes.push({ sql, valores });
      if (sql === SQL_CONTACTOS_DO_TENANT) return { rows: contactos.map((contact_id) => ({ contact_id })), rowCount: contactos.length };
      return { rows: [], rowCount: 0 };
    },
    release(erro?: unknown) {
      devolvida.push(erro);
    },
  };
  return { ligacao, instrucoes, devolvida, pool: { connect: async () => ligacao } };
}

/** A identidade falsa: os telefones de cada contacto, e o `antes` só com linhas a decifrar. */
function identidadeFalsa(telefones: Record<string, { finalidade: string; telefone: string }[]>, apagados: string[] = []) {
  const vistas: string[] = [];
  return {
    vistas,
    identidade: {
      async lerEndpoints(cliente: ClienteSql, tenantId: string, contactId: string, opcoes: OpcoesDaLeitura = {}) {
        assert.equal(tenantId, T);
        assert.equal(opcoes.soTelefones, true, "os BSUID nao se decifram");
        if (apagados.includes(contactId)) throw new ContactoApagadoError();
        const deste = telefones[contactId] ?? [];
        if (deste.length > 0) await opcoes.antes?.(cliente as never);
        vistas.push(contactId);
        return {
          contactId,
          bsuids: [],
          telefones: deste.map((t) => ({ ...t, expiraAt: D0 })),
        };
      },
    },
  };
}

/** O STO falso: guarda o que lhe dão, e devolve a chave. */
function stoFalso() {
  const postos: { ctx: { tenantId: string }; key: string; corpo: string; meta: Record<string, unknown> }[] = [];
  return {
    postos,
    armazenamento: {
      nome: "falso",
      async put(ctx: { tenantId: string }, key: string, body: Uint8Array, meta: Record<string, unknown>) {
        postos.push({ ctx, key, corpo: new TextDecoder().decode(body), meta });
        return { key, tamanho: body.byteLength, sha256: null };
      },
    } as never,
  };
}

describe("os telefones pelo cofre (KAM-233)", () => {
  it("decifra só os telefones dos contactos vivos, audita cada um no antes, e grava os três campos no STO", async () => {
    const l = ligacaoEspia([A, B, C]);
    const id = identidadeFalsa({
      [A]: [{ finalidade: "entrega", telefone: TELEFONE_A }],
      [B]: [{ finalidade: "contacto_pedido", telefone: TELEFONE_B }, { finalidade: "entrega", telefone: TELEFONE_B }],
    });
    const sto = stoFalso();
    const expira = new Date("2026-10-31T09:00:00Z");
    const r = await telefonesPeloCofre({ pool: l.pool, identidade: id.identidade as never, armazenamento: sto.armazenamento })
      .entregar({ tenantId: T, expiraAt: expira, agora: D0 });

    // A listagem, no contexto do tenant e com o tenant no texto.
    const listagem = l.instrucoes.findIndex((i) => i.sql === SQL_CONTACTOS_DO_TENANT);
    assert.ok(listagem > 0);
    assert.deepEqual(l.instrucoes[listagem]?.valores, [T]);
    assert.ok(l.instrucoes.slice(0, listagem).some((i) => i.sql === SQL_DEFINIR_CONTEXTO));
    assert.match(SQL_CONTACTOS_DO_TENANT, /erased_at IS NULL AND merged_into IS NULL/);
    assert.match(SQL_CONTACTOS_DO_TENANT, /tenant_id = \$1/);

    // Uma auditoria por contacto com telefone, e nenhuma pelo C, que não tem.
    const auditorias = l.instrucoes.filter((i) => i.sql === SQL_AUDITAR_TELEFONES);
    assert.deepEqual(auditorias.map((a) => a.valores[1]), [A, B]);
    for (const a of auditorias) {
      assert.equal(a.valores[0], T);
      assert.deepEqual(a.valores[2], Buffer.from(textoDaAuditoria(String(a.valores[1])), "utf8"));
      const tudo = JSON.stringify(a.valores) + Buffer.from(a.valores[2] as Buffer).toString("utf8");
      assert.ok(!tudo.includes("999000"), "nenhum telefone vai para a auditoria");
    }
    assert.match(SQL_AUDITAR_TELEFONES, new RegExp(`'${ACCAO_DOS_TELEFONES.replace(".", "\\.")}'`));
    assert.match(SQL_AUDITAR_TELEFONES, /'system', 'offboarding'/);

    // O objecto: a classe e o prazo da purga, os três campos e mais nada.
    assert.equal(sto.postos.length, 1);
    const posto = sto.postos[0]!;
    assert.equal(posto.ctx.tenantId, T);
    assert.match(posto.key, new RegExp(`^t/${T}/${CLASSE_DOS_TELEFONES}/2026/10/[0-9a-f-]{36}$`));
    assert.deepEqual(posto.meta, { contentType: "application/json", classe: "dsar", retainUntil: expira });
    const doc = JSON.parse(posto.corpo) as { coleccao: string; tenant_id: string; linhas: Record<string, string>[] };
    assert.equal(doc.coleccao, "telefones");
    assert.equal(doc.tenant_id, T);
    assert.deepEqual(doc.linhas, [
      { contact_id: A, finalidade: "entrega", telefone: TELEFONE_A },
      { contact_id: B, finalidade: "contacto_pedido", telefone: TELEFONE_B },
      { contact_id: B, finalidade: "entrega", telefone: TELEFONE_B },
    ]);
    for (const linha of doc.linhas) assert.deepEqual(Object.keys(linha).sort(), ["contact_id", "finalidade", "telefone"]);
    assert.deepEqual(r, { chave: posto.key, contactos: 2, telefones: 3 });
    assert.deepEqual(l.devolvida, [false], "a ligacao volta ao pool, limpa");
  });

  it("um contacto apagado entre a listagem e a leitura salta; outra falha sobe, nada vai ao STO e a ligação é descartada", async () => {
    const l = ligacaoEspia([A, B]);
    const sto = stoFalso();
    const id = identidadeFalsa({ [B]: [{ finalidade: "entrega", telefone: TELEFONE_B }] }, [A]);
    const r = await telefonesPeloCofre({ pool: l.pool, identidade: id.identidade as never, armazenamento: sto.armazenamento })
      .entregar({ tenantId: T, expiraAt: D0, agora: D0 });
    assert.equal(r.contactos, 1);

    const l2 = ligacaoEspia([A]);
    const sto2 = stoFalso();
    const avaria = {
      async lerEndpoints() {
        throw new Error("a KEK nao abre");
      },
    };
    await assert.rejects(
      telefonesPeloCofre({ pool: l2.pool, identidade: avaria as never, armazenamento: sto2.armazenamento })
        .entregar({ tenantId: T, expiraAt: D0, agora: D0 }),
      /a KEK nao abre/,
    );
    assert.equal(sto2.postos.length, 0);
    assert.ok(l2.devolvida[0] instanceof Error, "o pg descarta a ligacao que falhou");
  });
});

/** Uma base falsa das fases, só com o que a fase `pendentes` lê e escreve. */
class Fases implements ClienteSql {
  readonly fases = new Map<string, { estado: string; prazo_at: Date; resultado: Record<string, unknown> }>();
  pendentes = { encomendas: 0, disputas: 0, reservas: 0, reembolsos: 0 };

  constructor() {
    for (const f of FASES) {
      this.fases.set(f, {
        estado: f === "verificacao" ? "concluida" : "pendente",
        prazo_at: prazos(D0)[f],
        resultado: f === "verificacao" ? { origem: "titular" } : {},
      });
    }
  }

  async query(sql: string, p: readonly unknown[] = []) {
    if (sql === SQL_FASES) return { rows: [...this.fases].map(([fase, l]) => ({ fase, ...l })) };
    if (sql === SQL_MARCAR_FASE) {
      const l = this.fases.get(String(p[1]))!;
      this.fases.set(String(p[1]), { ...l, estado: String(p[2]), resultado: JSON.parse(String(p[3])) });
      return { rows: [], rowCount: 1 };
    }
    if (sql === SQL_PENDENTES) return { rows: [{ ...this.pendentes }] };
    return { rows: [], rowCount: 0 };
  }
}

function portaEspia(chamadas: { tenantId: string; expiraAt: Date }[], falhar = false): PortaDosTelefones {
  return {
    async entregar(o) {
      chamadas.push({ tenantId: o.tenantId, expiraAt: o.expiraAt });
      if (falhar) throw new Error("o STO caiu");
      return { chave: `t/${T}/dsar/2026/10/00000000-0000-4000-8000-000000000001`, contactos: 2, telefones: 3 };
    },
  };
}

describe("a fase pendentes entrega os telefones antes de fechar (KAM-233)", () => {
  it("só fecha com a chave dos telefones no resultado, e o prazo do objecto é o da purga", async () => {
    const bd = new Fases();
    const chamadas: { tenantId: string; expiraAt: Date }[] = [];
    const r = await verificarPendentes(bd, { tenantId: T, agora: D0, telefones: portaEspia(chamadas) });
    assert.equal(r.concluida, true);
    assert.deepEqual(chamadas, [{ tenantId: T, expiraAt: prazos(D0).purga }]);
    const linha = bd.fases.get("pendentes")!;
    assert.equal(linha.estado, "concluida");
    assert.deepEqual(linha.resultado.telefones, {
      chave: `t/${T}/dsar/2026/10/00000000-0000-4000-8000-000000000001`,
      contactos: 2,
      telefones: 3,
    });
    assert.ok(!JSON.stringify(linha.resultado).includes("999"), "nenhum telefone no resultado da fase");
    // Repetir não entrega outra vez.
    await verificarPendentes(bd, { tenantId: T, agora: D0, telefones: portaEspia(chamadas) });
    assert.equal(chamadas.length, 1);
  });

  it("com pendentes abertos não decifra nada; com a porta a falhar, a fase não fecha", async () => {
    const bd = new Fases();
    bd.pendentes = { encomendas: 1, disputas: 0, reservas: 0, reembolsos: 0 };
    const chamadas: { tenantId: string; expiraAt: Date }[] = [];
    assert.equal((await verificarPendentes(bd, { tenantId: T, agora: D0, telefones: portaEspia(chamadas) })).concluida, false);
    assert.equal(chamadas.length, 0);
    assert.equal(bd.fases.get("pendentes")?.estado, "em_curso");

    bd.pendentes = { encomendas: 0, disputas: 0, reservas: 0, reembolsos: 0 };
    await assert.rejects(verificarPendentes(bd, { tenantId: T, agora: D0, telefones: portaEspia(chamadas, true) }), /o STO caiu/);
    assert.equal(bd.fases.get("pendentes")?.estado, "em_curso", "sem os telefones, a exportacao nao arranca");
  });

  it("uma encomenda que abre enquanto se decifram os telefones deixa a fase em curso (achado 6)", async () => {
    const bd = new Fases();
    const porta: PortaDosTelefones = {
      async entregar() {
        bd.pendentes = { encomendas: 1, disputas: 0, reservas: 0, reembolsos: 0 };
        return { chave: "k", contactos: 0, telefones: 0 };
      },
    };
    const r = await verificarPendentes(bd, { tenantId: T, agora: D0, telefones: porta });
    assert.equal(r.concluida, false);
    assert.equal(bd.fases.get("pendentes")?.estado, "em_curso");
    assert.equal(bd.fases.get("pendentes")?.resultado.telefones, undefined, "sem a chave, a exportacao nao arranca");
  });

  it("um cancelamento entre a entrega e o fecho ganha: a fase não fecha", async () => {
    const bd = new Fases();
    const porta: PortaDosTelefones = {
      async entregar() {
        bd.fases.get("verificacao")!.resultado = { origem: "titular", cancelado_at: "x" };
        return { chave: "k", contactos: 0, telefones: 0 };
      },
    };
    await assert.rejects(verificarPendentes(bd, { tenantId: T, agora: D0, telefones: porta }));
    assert.equal(bd.fases.get("pendentes")?.estado, "pendente");
  });
});

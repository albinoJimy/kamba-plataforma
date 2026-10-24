/**
 * A coexistência contra a base falsa: os nove critérios do KAM-017, menos o que
 * só uma base real prova.
 *
 * O que fica para `tests_bd/coexistencia.bd.test.ts`: o *no-op* do passo contra
 * um predicado verdadeiro, a unicidade por canal, a reposição da reconexão, a
 * RLS e os privilégios. O que fica aqui é a **decisão** — qual o estado, qual o
 * desfecho, qual a métrica — e a **ordem** das instruções.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CODIGO_SEM_HISTORICO,
  Coexistente,
  type ContactoDoSync,
  DESFECHOS_DO_ECHO,
  ESTADOS,
  ALERTA_DE_SINCRONIZACAO_MS,
  INACTIVIDADE_DO_DONO_MS,
  MOTIVOS_DE_DESLIGAMENTO,
  MPS_POR_MODO,
  MetricasDaCoexistencia,
  PASSOS,
  PRAZO_DE_SINCRONIZACAO_MS,
  traduzirMotivo,
} from "../src/coexistencia/index.ts";
import { MPS_POR_CANAL, mpsDoModo } from "../src/outbound/limites.ts";
import { BaseFalsa } from "./coexistencia.base_falsa.ts";

const TENANT = "11111111-1111-7111-8111-111111111111";
const OUTRO = "22222222-2222-7222-8222-222222222222";
const CANAL = "33333333-3333-7333-8333-333333333333";
const T0 = new Date("2026-10-01T00:00:00Z");

interface Montado {
  readonly bd: BaseFalsa;
  readonly coex: Coexistente;
  readonly metricas: MetricasDaCoexistencia;
  readonly transicoes: string[];
  readonly emitidos: { tipo: string; motivo: string | null }[];
  readonly contactados: ContactoDoSync[];
  /** Os `outcome` que o registo levou, para os testes que os afirmam. */
  readonly avisos: string[];
  relogio: Date;
  conversaDe: (contactId: string) => string | null;
}

function montar(opcoes: { modo?: string } = {}): Montado {
  const bd = new BaseFalsa();
  bd.semearCanal(TENANT, {
    channel_id: CANAL,
    channel_mode: opcoes.modo ?? "coexistencia",
  });
  const estado: Montado = {
    bd,
    coex: undefined as unknown as Coexistente,
    metricas: new MetricasDaCoexistencia(),
    transicoes: [],
    emitidos: [],
    contactados: [],
    avisos: [],
    relogio: T0,
    conversaDe: (contactId) => `conv-${contactId}`,
  };
  const coex = new Coexistente({
    emitirCanalActualizado: async (_c, _t, _ch, _n, motivo) => {
      estado.emitidos.push({ tipo: "channel.updated", motivo });
      return `evt-${estado.emitidos.length}`;
    },
    emitirAviso: async () => {
      estado.emitidos.push({ tipo: "channel.inactivity_warning", motivo: null });
      return `evt-${estado.emitidos.length}`;
    },
    contacto: async (pedido) => {
      estado.contactados.push({
        bsuid: pedido.bsuid,
        telefone: pedido.telefone,
      });
      return { contactId: `c-${pedido.telefone ?? pedido.bsuid}` };
    },
    conversa: async (pedido) => estado.conversaDe(pedido.contactId),
    transitar: async (_t, conversationId) => {
      estado.transicoes.push(conversationId);
    },
    metricas: estado.metricas,
    // Um duplo de `Logger` que so guarda o `outcome`: e o minimo que deixa um
    // teste afirmar que um caminho **nao ficou mudo**, sem montar o logger a
    // serio (que em modo estrito levanta, e e isso que outros testes medem).
    log: {
      info: (campos?: { outcome?: string }) => {
        if (campos?.outcome !== undefined) estado.avisos.push(campos.outcome);
      },
      warn: (campos?: { outcome?: string }) => {
        if (campos?.outcome !== undefined) estado.avisos.push(campos.outcome);
      },
      error: (campos?: { outcome?: string }) => {
        if (campos?.outcome !== undefined) estado.avisos.push(campos.outcome);
      },
    } as never,
    agora: () => estado.relogio,
  });
  return Object.assign(estado, { coex });
}

async function canalDe(m: Montado) {
  const canal = await m.coex.canal(m.bd, TENANT, `pnid-${CANAL}`);
  assert.ok(canal !== null);
  return canal;
}

describe("coexistencia: os dominios batem com a revisao 0018", () => {
  it("os quatro estados sao os do dicionario §3.22", () => {
    assert.deepEqual(
      [...ESTADOS],
      ["a_sincronizar", "sincronizado", "sincronizado_sem_historico", "falhado"],
    );
  });

  it("os seis motivos sao os do E1 §2, em minusculas", () => {
    assert.equal(MOTIVOS_DE_DESLIGAMENTO.length, 6);
    for (const motivo of MOTIVOS_DE_DESLIGAMENTO) {
      assert.match(motivo, /^[a-z]+(_[a-z]+)*$/, `${motivo} nao e snake_case minusculo`);
    }
  });

  it("os seis motivos passam a gramatica de `outcome` do logger", async () => {
    // **O teste que o KAM-018 pagou com um gate vermelho.** Um valor de lista
    // fechada que va ao `outcome` confronta-se com a politica **antes**: em
    // modo estrito, que e o do CI, o `Logger` levanta, e um desfecho normal de
    // um webhook vira excepcao nao tratada no caminho de um webhook.
    const { validar } = await import("../src/logger/politica.ts");
    for (const motivo of MOTIVOS_DE_DESLIGAMENTO) {
      assert.equal(validar("outcome", motivo), motivo, `o outcome ${motivo} e recusado`);
    }
  });

  it("o 2593109 e recusado pelo `outcome` **e** pelo `error_code`", async () => {
    // Sete digitos, e o `DIGITOS_MAXIMOS` e seis. E por isto que ele vive numa
    // coluna `integer` e o registo leva o simbolo.
    const { validar } = await import("../src/logger/politica.ts");
    assert.equal(validar("outcome", String(CODIGO_SEM_HISTORICO)), null);
    assert.equal(validar("error_code", String(CODIGO_SEM_HISTORICO)), null);
    // E o de **seis** digitos do KAM-015 passa, que e o que mostra que a regra
    // e o numero de digitos e nao «codigos da Meta nao passam».
    assert.equal(validar("error_code", "131049"), "131049");
  });

  it("o `sincronizado_sem_historico` tambem passa a gramatica", async () => {
    const { validar } = await import("../src/logger/politica.ts");
    assert.equal(
      validar("outcome", "sincronizado_sem_historico"),
      "sincronizado_sem_historico",
    );
  });

  it("a traducao da forma da Meta e por mapa e nao por `toLowerCase`", () => {
    assert.equal(traduzirMotivo("PRIMARY_INACTIVITY"), "primary_inactivity");
    // Um motivo novo da Meta **nao** desliga nada: devolve `null`.
    assert.equal(traduzirMotivo("ALGO_NOVO"), null);
    assert.equal(traduzirMotivo("primary_inactivity"), null);
    assert.equal(traduzirMotivo(null), null);
    assert.equal(traduzirMotivo(42), null);
  });

  it("os dois passos sao os que o E1 §2 nomeia", () => {
    assert.deepEqual([...PASSOS], ["contactos", "historico"]);
  });
});

describe("coexistencia: criterio 8 — o `channel_mode` manda", () => {
  it("o debito por modo e 15 em `coexistencia`, como o criterio pede", () => {
    assert.equal(MPS_POR_MODO["coexistencia"], 15);
    assert.equal(mpsDoModo("coexistencia"), 15);
  });

  it("um modo desconhecido cai no debito conservador e nao levanta", () => {
    // A base impoe o dominio de dois valores; chegar aqui um terceiro
    // significa que a coluna mudou sem o mapa mudar, e nesse dia enviar devagar
    // e melhor do que nao enviar.
    assert.equal(mpsDoModo("outro_qualquer"), MPS_POR_CANAL);
    assert.equal(mpsDoModo(null), MPS_POR_CANAL);
    assert.equal(mpsDoModo(undefined), MPS_POR_CANAL);
  });

  it("em `cloud_only` nao se abre sincronizacao nenhuma", async () => {
    const m = montar({ modo: "cloud_only" });
    const canal = await canalDe(m);
    assert.equal(await m.coex.abrir(m.bd, TENANT, canal), null);
    assert.equal(m.bd.linhas.size, 0);
    // E **nao se tocou na base** depois da resolucao do canal.
    assert.deepEqual(m.bd.nomes(), ["canal"]);
  });

  it("em `cloud_only` um echo nao vira actividade humana", async () => {
    const m = montar({ modo: "cloud_only" });
    const canal = await canalDe(m);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.X",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(r.desfecho, "sem_conversa");
    assert.equal(m.transicoes.length, 0);
    // Nem sequer se consultou o `outbound_messages`: nao ha echoes neste modo.
    assert.ok(!m.bd.nomes().includes("por_wamid"));
  });
});

describe("coexistencia: criterios 1 e 2 — ingestao sem AGR, sem envio, sem corpos", () => {
  it("um lote de historico alimenta contactos e contagens, e zero jobs", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 1_240,
      contactos: [
        { bsuid: null, telefone: "+999100000001" },
        { bsuid: null, telefone: "+999100000002" },
      ],
      erros: [],
    });
    assert.equal(r.jobsParaOAgr, 0);
    assert.equal(r.contactos, 2);
    assert.equal(r.mensagens, 1_240);
    assert.equal(r.passoConcluido, true);
    const linha = m.bd.ver(TENANT, CANAL);
    assert.equal(linha?.mensagens_vistas, 1_240);
    assert.deepEqual(linha?.passos_feitos, ["historico"]);
  });

  it("os contactos passam pela porta do KAM-008 e nunca por telefone como chave", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, [
      { bsuid: "bsuid-1", telefone: null },
      { bsuid: null, telefone: "+999100000003" },
      // Um contacto sem identificador nenhum **nao** vai a porta: o KAM-008
      // levanta `PedidoSemIdentificadorError`, e um lote de seis meses nao se
      // perde por uma linha mal formada.
      { bsuid: null, telefone: null },
    ]);
    assert.equal(m.contactados.length, 2);
  });

  it("nenhuma instrucao escreve corpo de mensagem: a tabela nao tem onde", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 3,
      contactos: [{ bsuid: null, telefone: "+999100000001" }],
      erros: [],
    });
    // O criterio 2 pela forma: **nenhum parametro de nenhuma instrucao** e um
    // texto que pudesse ser o corpo de uma mensagem. Os parametros sao UUID,
    // nomes de passo, numeros e datas.
    for (const vista of m.bd.vistas) {
      for (const p of vista.parametros) {
        if (typeof p !== "string") continue;
        assert.ok(
          ["contactos", "historico"].includes(p) ||
            /^[0-9a-f-]{36}$/.test(p) ||
            p.startsWith("pnid-"),
          `um parametro de texto inesperado chegou a base: ${JSON.stringify(p)}`,
        );
      }
    }
  });

  it("os dois passos fecham a sincronizacao e carimbam o canal", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, [
      { bsuid: null, telefone: "+999100000001" },
    ]);
    assert.equal(m.bd.ver(TENANT, CANAL)?.estado, "a_sincronizar");
    m.relogio = new Date(T0.getTime() + 90 * 1_000);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 10,
      contactos: [],
      erros: [],
    });
    assert.equal(r.estado, "sincronizado");
    // O `coexistence_synced_at` escreve-se **uma vez, no fim**.
    assert.equal(
      m.bd.canais.get(`${TENANT}|${CANAL}`)?.coexistence_synced_at?.toISOString(),
      m.relogio.toISOString(),
    );
    // E a duracao foi observada: 90 s.
    assert.equal(m.metricas.ler()["coex_sync_duration_s_count"], 1);
    assert.equal(m.metricas.ler()["coex_sync_duration_s_sum"], 90);
  });
});

describe("coexistencia: criterio 3 — o passo corre uma vez", () => {
  it("o mesmo lote duas vezes nao soma nem remarca", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const lote = {
      mensagens: 500,
      contactos: [{ bsuid: null, telefone: "+999100000001" }],
      erros: [] as number[],
    };
    const primeiro = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, lote);
    const segundo = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, lote);
    assert.equal(primeiro.passoConcluido, true);
    assert.equal(segundo.passoConcluido, false);
    assert.equal(m.bd.ver(TENANT, CANAL)?.mensagens_vistas, 500);
  });

  it("alerta as 12 h, **uma vez**, e nao falha nada ainda", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + 13 * 60 * 60 * 1_000);
    const primeira = await m.coex.varrerPrazos(m.bd);
    assert.deepEqual(primeira.alertados, [CANAL]);
    assert.deepEqual(primeira.falhados, []);
    const segunda = await m.coex.varrerPrazos(m.bd);
    assert.deepEqual(segunda.alertados, []);
  });

  it("falha e pede offboard as 24 h, com o relogio acelerado", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    const r = await m.coex.varrerPrazos(m.bd);
    assert.deepEqual(r.falhados, [CANAL]);
    // O *offboard* e a mesma lista, e nao uma segunda: um `falhado` **e** um
    // offboard pedido, e devolver duas sugeria que pode haver um sem o outro.
    assert.deepEqual(r.offboards, r.falhados);
    assert.equal(m.bd.ver(TENANT, CANAL)?.estado, "falhado");
    assert.equal(m.metricas.ler()["coex_sync_failed_total:prazo_esgotado"], 1);
    // Segunda varredura: nada. O predicado `estado = 'a_sincronizar'` decide.
    const outra = await m.coex.varrerPrazos(m.bd);
    assert.deepEqual(outra.falhados, []);
  });

  it("um lote que chegue depois do prazo nao ressuscita a sincronizacao", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    await m.coex.varrerPrazos(m.bd);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 9,
      contactos: [],
      erros: [],
    });
    assert.equal(r.passoConcluido, false);
    assert.equal(r.estado, "falhado");
  });
});

describe("coexistencia: criterio 4 — o 2593109 e sucesso e nao falha", () => {
  it("o erro fecha em `sincronizado_sem_historico` e guarda o codigo", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + 60 * 1_000);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [CODIGO_SEM_HISTORICO],
    });
    assert.equal(r.estado, "sincronizado_sem_historico");
    const linha = m.bd.ver(TENANT, CANAL);
    assert.equal(linha?.meta_error_code, CODIGO_SEM_HISTORICO);
    assert.notEqual(linha?.estado, "falhado");
    // **E nao marcou o passo `historico`**, que nao correu: fechar e marcar
    // eram duas afirmacoes contraditorias sobre o mesmo facto.
    assert.deepEqual(linha?.passos_feitos, []);
    // E nao contou como falha.
    assert.equal(m.metricas.ler()["coex_sync_failed_total:prazo_esgotado"], undefined);
  });

  it("o canal fica carimbado como sincronizado mesmo sem historico", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + 60 * 1_000);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [CODIGO_SEM_HISTORICO],
    });
    assert.ok(m.bd.canais.get(`${TENANT}|${CANAL}`)?.coexistence_synced_at !== null);
  });

  it("um erro que nao e o 2593109 nao fecha a sincronizacao", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 4,
      contactos: [],
      erros: [131_049],
    });
    assert.equal(r.estado, "a_sincronizar");
    assert.equal(r.passoConcluido, true);
  });
});

describe("coexistencia: criterio 5 — os seis motivos desligam, uma vez", () => {
  for (const motivo of MOTIVOS_DE_DESLIGAMENTO) {
    it(`o motivo ${motivo} passa o canal a desligado e emite`, async () => {
      const m = montar();
      const canal = await canalDe(m);
      await m.coex.abrir(m.bd, TENANT, canal);
      const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
        evento: "PARTNER_REMOVED",
        motivo: motivo.toUpperCase(),
      });
      assert.equal(r.motivo, motivo);
      assert.equal(r.desligou, true);
      assert.ok(r.eventoId !== null);
      assert.equal(m.bd.canais.get(`${TENANT}|${CANAL}`)?.estado, "desligado");
      assert.deepEqual(m.emitidos, [{ tipo: "channel.updated", motivo }]);
      assert.equal(m.metricas.ler()[`channel_disconnected_total:${motivo}`], 1);
    });
  }

  it("repetir o mesmo evento 2x produz 1 transicao, 1 evento e 1 contagem", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const bruto = { evento: "PARTNER_REMOVED", motivo: "PRIMARY_INACTIVITY" };
    const primeira = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, bruto);
    const segunda = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, bruto);
    assert.equal(primeira.desligou, true);
    assert.equal(segunda.desligou, false);
    assert.equal(segunda.eventoId, null);
    assert.equal(m.emitidos.length, 1);
    assert.equal(
      m.metricas.ler()["channel_disconnected_total:primary_inactivity"],
      1,
    );
  });

  it("um motivo desconhecido nao desliga nada", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "ALGO_QUE_A_META_INVENTOU",
    });
    assert.equal(r.motivo, null);
    assert.equal(r.desligou, false);
    assert.equal(m.bd.canais.get(`${TENANT}|${CANAL}`)?.estado, "ativo");
    assert.equal(m.emitidos.length, 0);
  });

  it("escreve, emite e so depois conta — a ordem que o KAM-018 pagou", async () => {
    // Um `evt_emitir` que levante desfaz o `UPDATE` da mesma transaccao e
    // **nao** desfaz um contador em memoria: o painel mostrava desligamentos
    // que a base nao tem.
    const bd = new BaseFalsa();
    bd.semearCanal(TENANT, { channel_id: CANAL });
    const metricas = new MetricasDaCoexistencia();
    const coex = new Coexistente({
      emitirCanalActualizado: async () => {
        throw new Error("o outbox recusou");
      },
      emitirAviso: async () => "evt",
      contacto: async () => ({ contactId: "c" }),
      conversa: async () => null,
      transitar: async () => {},
      metricas,
      agora: () => T0,
    });
    const canal = await coex.canal(bd, TENANT, `pnid-${CANAL}`);
    assert.ok(canal !== null);
    await coex.abrir(bd, TENANT, canal);
    await assert.rejects(
      coex.tratarAccountUpdate(bd, TENANT, canal, {
        evento: "PARTNER_REMOVED",
        motivo: "CHANGE_NUMBER",
      }),
      /o outbox recusou/,
    );
    assert.equal(metricas.ler()["channel_disconnected_total:change_number"], undefined);
  });
});

describe("coexistencia: criterio 6 — o aviso aos 10 dias", () => {
  it("avisa um canal sincronizado sem echo ha 10 dias, uma vez", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, []);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [],
    });
    m.relogio = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), [CANAL]);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), []);
  });

  it("um canal que nunca teve echo conta do arranque, e nao fica por avisar", async () => {
    // Sem o `COALESCE(ultimo_echo_em, iniciado_em)`, um dono que nunca escreveu
    // na app — exactamente quem o aviso existe para apanhar — nunca era
    // avisado, porque `NULL <= $1` e `NULL`.
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, []);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [],
    });
    assert.equal(m.bd.ver(TENANT, CANAL)?.ultimo_echo_em, null);
    m.relogio = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), [CANAL]);
  });

  it("actividade do dono **reabre** a janela do aviso", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, []);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [],
    });
    m.relogio = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    await m.coex.varrerInactividade(m.bd);
    // O dono volta a escrever.
    await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.A",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(m.bd.ver(TENANT, CANAL)?.avisado_em, null);
    // Dez dias depois **desse** echo, avisa outra vez.
    m.relogio = new Date(m.relogio.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), [CANAL]);
  });

  it("um canal que ainda sincroniza nao se avisa de inactividade", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), []);
  });

  it("um canal desligado nao se avisa de inactividade", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, []);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 0,
      contactos: [],
      erros: [],
    });
    await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "PRIMARY_INACTIVITY",
    });
    m.relogio = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    assert.deepEqual(await m.coex.varrerInactividade(m.bd), []);
  });
});

describe("coexistencia: criterio 7 — o echo e o `wamid`", () => {
  it("um echo cujo wamid nao esta em `outbound_messages` e do dono", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.DoDono",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(r.desfecho, "do_dono");
    assert.equal(r.conversationId, "conv-c-+999100000001");
    assert.deepEqual(m.transicoes, ["conv-c-+999100000001"]);
    assert.equal(m.metricas.ler()["coex_echo_total:do_dono"], 1);
    assert.equal(
      m.bd.ver(TENANT, CANAL)?.ultimo_echo_em?.toISOString(),
      T0.toISOString(),
    );
  });

  it("um echo cujo wamid consta de `outbound_messages` e ignorado", async () => {
    const m = montar();
    m.bd.nossos.add("wamid.Nosso");
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.Nosso",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(r.desfecho, "nosso");
    assert.equal(m.transicoes.length, 0);
    // **E nao mexe no relogio de inactividade**: um bot a responder nao prova
    // que o dono abriu a app.
    assert.equal(m.bd.ver(TENANT, CANAL)?.ultimo_echo_em, null);
    assert.equal(m.metricas.ler()["coex_echo_total:nosso"], 1);
  });

  it("a consulta do wamid leva o `tenant_id` e corre antes de tudo", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.bd.vistas.length = 0;
    await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.X",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(m.bd.nomes()[0], "por_wamid");
    assert.equal(m.bd.vistas[0]?.parametros[0], TENANT);
  });

  it("um echo do dono sem conversa conta-se em vez de se descartar", async () => {
    const m = montar();
    m.conversaDe = () => null;
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.Y",
      destinatario: { bsuid: null, telefone: "+999100000009" },
    });
    assert.equal(r.desfecho, "sem_conversa");
    assert.equal(m.metricas.ler()["coex_echo_total:sem_conversa"], 1);
    // **Mas o relogio mexeu**: o dono escreveu na app, e isso e actividade dele
    // mesmo que o destinatario nao resolva uma conversa nossa.
    assert.ok(m.bd.ver(TENANT, CANAL)?.ultimo_echo_em !== null);
  });

  it("um echo sem destinatario conta-se e nao levanta", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.Z",
      destinatario: { bsuid: null, telefone: null },
    });
    assert.equal(r.desfecho, "sem_conversa");
    assert.equal(m.contactados.length, 0);
  });

  it("dois echoes fora de ordem nao recuam o relogio", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + 10_000);
    await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.1",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    m.relogio = new Date(T0.getTime() + 5_000);
    await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.2",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(
      m.bd.ver(TENANT, CANAL)?.ultimo_echo_em?.getTime(),
      T0.getTime() + 10_000,
    );
  });

  it("os tres desfechos sao os do dicionario, e nenhum echo fica sem contar", () => {
    assert.deepEqual([...DESFECHOS_DO_ECHO], ["do_dono", "nosso", "sem_conversa"]);
  });
});

describe("coexistencia: criterio 9 — a reconexao nao duplica", () => {
  it("abrir duas vezes repoe a linha e nao cria segunda", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirStateSync(m.bd, TENANT, CANAL, []);
    assert.deepEqual(m.bd.ver(TENANT, CANAL)?.passos_feitos, ["contactos"]);
    m.relogio = new Date(T0.getTime() + 30 * 24 * 60 * 60 * 1_000);
    await m.coex.abrir(m.bd, TENANT, canal);
    assert.equal(m.bd.linhas.size, 1);
    // **Os passos da ligacao anterior nao sobrevivem**: com eles, a
    // sincronizacao nova nascia concluida sem ter corrido.
    assert.deepEqual(m.bd.ver(TENANT, CANAL)?.passos_feitos, []);
    assert.equal(m.bd.ver(TENANT, CANAL)?.estado, "a_sincronizar");
    // E o prazo novo conta do novo arranque.
    assert.equal(
      m.bd.ver(TENANT, CANAL)?.prazo_em.getTime(),
      m.relogio.getTime() + PRAZO_DE_SINCRONIZACAO_MS,
    );
  });

  it("a reconexao limpa o desligamento, e limpa as duas metades", async () => {
    // O `channel_coexistence_desligamento_ck` exige as duas metades ou nenhuma:
    // limpar so uma era um `23514` na reconexao.
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "CHANGE_NUMBER",
    });
    assert.ok(m.bd.ver(TENANT, CANAL)?.desligado_em !== null);
    await m.coex.abrir(m.bd, TENANT, canal);
    const linha = m.bd.ver(TENANT, CANAL);
    assert.equal(linha?.motivo_desligamento, null);
    assert.equal(linha?.desligado_em, null);
  });
});

describe("coexistencia: os defeitos que a revisao adversarial encontrou", () => {
  it("os emissores reais encaixam na porta `Emitir`", async () => {
    // **O teste que apanharia o defeito, e o unico que o pode apanhar.** O
    // compilador aceita atribuir uma funcao de menos parametros a um tipo de
    // mais, e o `motivo` do `channel.updated/v2.schema.json` e `string` livre:
    // com as assinaturas desalinhadas, o evento saia com o **UUID do canal** no
    // `phone_number_id` e o `phone_number_id` no `motivo`, e nada ficava
    // vermelho. Aqui ligam-se os emissores **reais** e le-se o que chega ao
    // `evt_emitir`.
    const { emitirAvisoDeInactividade, emitirCanalActualizado } = await import(
      "../src/coexistencia/eventos.ts"
    );
    const vistos: { sql: string; parametros: readonly unknown[] }[] = [];
    const cliente = {
      async query<T = Record<string, unknown>>(
        sql: string,
        parametros: readonly unknown[] = [],
      ): Promise<{ readonly rows: readonly T[] }> {
        vistos.push({ sql, parametros });
        return { rows: [{ event_id: "evt-1" } as T] };
      },
    };
    const m = montar();
    const canal = await canalDe(m);
    const coex = new Coexistente({
      emitirCanalActualizado,
      emitirAviso: emitirAvisoDeInactividade,
      contacto: async () => ({ contactId: "c" }),
      conversa: async () => null,
      transitar: async () => {},
      agora: () => T0,
    });
    await coex.abrir(m.bd, TENANT, canal);
    // O `cliente` falso so serve a emissao; a escrita vai a base falsa.
    await m.coex.abrir(m.bd, TENANT, canal);
    await coex.avisar(cliente, TENANT, CANAL, `pnid-${CANAL}`);
    const payload = JSON.parse(String(vistos[0]?.parametros[5]));
    assert.deepEqual(payload, { phone_number_id: `pnid-${CANAL}` });
    // E o `phone_number_id` **nao** e o UUID do canal, que era o defeito.
    assert.notEqual(payload.phone_number_id, CANAL);
  });

  it("um canal `suspenso` nao fica com as duas tabelas em desacordo", async () => {
    // A ordem antiga — registar e depois desligar — deixava o registo escrito e
    // o canal intacto, e a funcao devolvia normalmente: a transaccao de quem
    // chama confirmava um desligamento que o canal nao tem.
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const linhaDoCanal = m.bd.canais.get(`${TENANT}|${CANAL}`);
    assert.ok(linhaDoCanal !== undefined);
    linhaDoCanal.estado = "suspenso";
    const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "PRIMARY_INACTIVITY",
    });
    assert.equal(r.desligou, false);
    assert.equal(linhaDoCanal.estado, "suspenso");
    // **E a coexistencia nao ficou marcada**, que e o ponto.
    assert.equal(m.bd.ver(TENANT, CANAL)?.desligado_em, null);
    assert.equal(m.bd.ver(TENANT, CANAL)?.motivo_desligamento, null);
    assert.equal(m.emitidos.length, 0);
  });

  it("um canal `cloud_only` desliga sem avisar de desalinhamento", async () => {
    // Em `cloud_only` o `abrir` nao insere (criterio 8), pelo que nao ha linha
    // de coexistencia — e isso e o caminho **normal**, nao um desalinhamento.
    const m = montar({ modo: "cloud_only" });
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    assert.equal(m.bd.linhas.size, 0);
    const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "CHANGE_NUMBER",
    });
    assert.equal(r.desligou, true);
    assert.equal(m.bd.canais.get(`${TENANT}|${CANAL}`)?.estado, "desligado");
    // **E o registo fica calado, que e o que o nome deste teste promete.** A
    // primeira versao afirmava o desfecho e o estado e nao olhava para o
    // registo, pelo que passava com a condicao do modo **e sem ela**: a prova
    // por mutacao do KAM-115 apanhou-a. O `desligamento_desalinhado` existe
    // para apanhar desalinhamento a serio, e um `warn` por cada
    // `PARTNER_REMOVED` de cada canal `cloud_only` e ruido nesse sinal.
    assert.equal(
      m.avisos.includes("desligamento_desalinhado"),
      false,
      JSON.stringify(m.avisos),
    );
  });

  it("um canal `coexistencia` sem linha **avisa** de desalinhamento", async () => {
    // A metade positiva, e sem ela o teste acima passava com o `warn` apagado
    // por inteiro. Em `coexistencia` a ausencia de linha nao e normal: ou ela ja
    // estava marcada, ou nunca foi aberta.
    const m = montar();
    const canal = await canalDe(m);
    // **Nao se chama o `abrir`**: e isso que deixa o canal em `coexistencia` sem
    // linha, que e o desalinhamento que o aviso existe para apanhar.
    assert.equal(m.bd.linhas.size, 0);
    const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "CHANGE_NUMBER",
    });
    assert.equal(r.desligou, true);
    assert.ok(
      m.avisos.includes("desligamento_desalinhado"),
      JSON.stringify(m.avisos),
    );
  });

  it("um `account_update` que nao e PARTNER_REMOVED nao desliga", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    const r = await m.coex.tratarAccountUpdate(m.bd, TENANT, canal, {
      evento: "PHONE_NUMBER_QUALITY_UPDATE",
      motivo: "CHANGE_NUMBER",
    });
    assert.equal(r.desligou, false);
    assert.equal(r.motivo, null);
    assert.equal(m.bd.canais.get(`${TENANT}|${CANAL}`)?.estado, "ativo");
  });

  it("um lote que chegue depois do prazo nao entra, mesmo sem varredura", async () => {
    // **O prazo e duro pela base e nao pelo calendario de quem varre.** Sem o
    // `prazo_em > $6` no `SQL_MARCAR_PASSO`, um `history` reentregue as 30 h
    // encontrava o estado ainda em `a_sincronizar` — ninguem o tinha marcado
    // `falhado`, porque nao ha agendador — e fechava a sincronizacao **depois**
    // do prazo. Repare-se que **nao se chama `varrerPrazos`** neste teste.
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    m.relogio = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 6 * 60 * 60 * 1_000);
    const r = await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 9,
      contactos: [],
      erros: [],
    });
    assert.equal(r.passoConcluido, false);
    assert.equal(m.bd.ver(TENANT, CANAL)?.estado, "a_sincronizar");
    assert.deepEqual(m.bd.ver(TENANT, CANAL)?.passos_feitos, []);
  });

  it("um echo num canal sem linha de coexistencia nao fica mudo", async () => {
    // A falha era fechada **e muda**: o relogio nao avanca, o aviso dos 10 dias
    // deixa de sair, e nada o regista.
    const m = montar();
    const canal = await canalDe(m);
    // **Sem `abrir`**: nao ha linha.
    assert.equal(m.bd.linhas.size, 0);
    const r = await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "wamid.Orfao",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    assert.equal(r.desfecho, "do_dono");
    assert.ok(
      m.avisos.includes("echo_sem_coexistencia"),
      `o registo nao avisou: ${JSON.stringify(m.avisos)}`,
    );
  });
});

describe("coexistencia: isolamento de tenant", () => {
  it("o canal de outro tenant nao resolve", async () => {
    const m = montar();
    assert.equal(await m.coex.canal(m.bd, OUTRO, `pnid-${CANAL}`), null);
  });

  it("toda a instrucao leva o `tenant_id` no primeiro parametro", async () => {
    const m = montar();
    const canal = await canalDe(m);
    await m.coex.abrir(m.bd, TENANT, canal);
    await m.coex.ingerirHistorico(m.bd, TENANT, CANAL, {
      mensagens: 1,
      contactos: [],
      erros: [],
    });
    await m.coex.tratarEcho(m.bd, TENANT, canal, {
      wamid: "w",
      destinatario: { bsuid: null, telefone: "+999100000001" },
    });
    const semTenant = new Set(["alertar", "falhar", "avisar"]);
    for (let i = 0; i < m.bd.vistas.length; i += 1) {
      const nome = m.bd.nomes()[i];
      if (nome === undefined || semTenant.has(nome)) continue;
      assert.equal(
        m.bd.vistas[i]?.parametros[0],
        TENANT,
        `a instrucao ${nome} nao leva o tenant_id no primeiro parametro`,
      );
    }
  });
});

describe("coexistencia: as mutacoes que sobreviviam a bateria do gate 4", () => {
  it("**os tres prazos afirmam-se pelo valor, e nao por si mesmos**", () => {
    // A mutação `os 10 dias passam a 14` sobrevivia porque os testes da janela
    // usam a constante nas duas pontas da fronteira — são verdadeiros para
    // **qualquer** valor dela. É a mesma lacuna que o KAM-115 fechou na janela
    // do gatilho dele, e fecha-se da mesma maneira: um número de produto
    // afirma-se pelo número.
    //
    // Os três juntos, porque são um conjunto: as 24 h são **CONFIRMADAS** pelo
    // `E1` §2, e as 12 h e os 10 dias são ***proposta*** — e é por isso que
    // mudá-los é uma decisão e não uma correcção.
    assert.equal(PRAZO_DE_SINCRONIZACAO_MS, 24 * 60 * 60 * 1_000);
    assert.equal(ALERTA_DE_SINCRONIZACAO_MS, 12 * 60 * 60 * 1_000);
    assert.equal(INACTIVIDADE_DO_DONO_MS, 10 * 24 * 60 * 60 * 1_000);
    // E a relação que o `contrato.ts` escreve: o alerta é **metade** do prazo, e
    // o aviso é a folga de quatro dias sobre os ~14 da Meta.
    assert.equal(ALERTA_DE_SINCRONIZACAO_MS * 2, PRAZO_DE_SINCRONIZACAO_MS);
    assert.ok(INACTIVIDADE_DO_DONO_MS < 14 * 24 * 60 * 60 * 1_000);
  });

  it("**uma etiqueta fora da lista fechada levanta**", () => {
    // A guarda existe por causa do `OBS-I`: um `tenant_id` é um UUID com hífenes
    // e não pode entrar numa métrica. Nenhum teste a exercitava, pelo que a
    // mutação que a apaga sobrevivia — e com ela apagada, o dia em que alguém
    // passasse um identificador ele era publicado.
    const m = new MetricasDaCoexistencia();
    assert.throws(
      () => m.contar("coex_echo_total", "11111111-1111-4111-8111-111111111111"),
      /lista fechada/,
    );
    // E a metade positiva: os três desfechos declarados passam.
    for (const desfecho of DESFECHOS_DO_ECHO) {
      m.contar("coex_echo_total", desfecho);
    }
    assert.equal(m.ler()["coex_echo_total:do_dono"], 1);
  });

  it("**uma duracao negativa ou nao finita levanta, e nao entra em silencio**", () => {
    // Um `NaN` no formato de exposição faz o Prometheus descartar a recolha
    // **toda**, e uma duração negativa é um relógio ao contrário: o `_sum`
    // deixava de querer dizer nada. A guarda existia e nenhum teste a media, e
    // ela **levanta** em vez de ignorar — uma duração negativa só pode vir de um
    // `concluido_em` anterior ao `iniciado_em`, que é um defeito e não um valor.
    const m = new MetricasDaCoexistencia();
    for (const mau of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
      assert.throws(() => m.observarDuracao(mau), RangeError, String(mau));
    }
    assert.match(m.exposicao(), /coex_sync_duration_s_count 0/);
    // E a metade positiva, senão este teste passava com o histograma inteiro
    // apagado.
    m.observarDuracao(42);
    assert.match(m.exposicao(), /coex_sync_duration_s_count 1/);
    assert.match(m.exposicao(), /coex_sync_duration_s_sum 42/);
  });
});

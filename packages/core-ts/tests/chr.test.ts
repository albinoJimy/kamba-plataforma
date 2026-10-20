/**
 * O CHR, do evento ao destino (KAM-014, critérios 2, 3, 5, 6 e 7).
 *
 * Aqui prova-se o que é **decisão**: que caminho cada evento segue, que
 * escritas se fazem e por que ordem, e as propriedades negativas que o ticket
 * pede — 0 *jobs* para o AGR num canal desconhecido, 0 num Fluxo B, 0 numa
 * conversa que não está em `bot`, 0 num `echo`.
 *
 * **A matriz de estados corre aqui linha a linha**, com as seis linhas do
 * `docs/tecnica/01` §7.2. A matriz em si é do KAM-009 (`ten/estados.ts`, com
 * bateria própria); o que este ficheiro prende é o que o **CHR faz** com cada
 * resposta dela: quando abre conversa, quando entrega, e o que diz a quem
 * envia.
 *
 * O que **não** se prova aqui, e onde se prova: que o `phone_number_id` de A
 * nunca devolve o contexto de B, que a conversa é uma só por (tenant, contacto,
 * canal) sob concorrência, que o `ON CONFLICT` é idempotente e que a fusão
 * reaponta conversas numa transacção — é tudo base de dados, e vive em
 * `db/tests_chr/`. Uma base falsa devolve o que se lhe mandou devolver.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  Chr,
  type ComTenant,
  type EntregaDoChr,
  METRICA_EM_QUARENTENA,
  METRICA_RESOLUCOES,
  MetricasDoChr,
  ORIGEM_DE_PLATAFORMA,
  ResolvedorDeCanal,
  TIPO_DE_PLATAFORMA,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import { ESTADOS_DO_CANAL, ESTADOS_DO_TENANT } from "../src/ten/index.ts";
import { BaseFalsa, linhaDeCanal, mensagemDe } from "./apoio/chr-base-falsa.ts";

const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const AGORA = new Date("2026-10-19T12:00:00.000Z");

class EntregaFalsa implements EntregaDoChr {
  readonly aoAgr: AgentInvocation[] = [];
  readonly aoDono: unknown[] = [];

  async agr(invocacao: AgentInvocation): Promise<void> {
    this.aoAgr.push(invocacao);
  }

  async dono(entrega: unknown): Promise<void> {
    this.aoDono.push(entrega);
  }
}

interface Montado {
  readonly chr: Chr;
  readonly bd: BaseFalsa;
  readonly entrega: EntregaFalsa;
  readonly metricas: MetricasDoChr;
  readonly quarentenadas: { evento: unknown; motivo: string }[];
  readonly registos: { outcome: string; error_code?: string }[];
  readonly contextos: string[];
}

function montar(opcoes: {
  readonly canal?: Readonly<Record<string, unknown>> | null;
  readonly modo?: string;
  readonly contactoLanca?: Error;
} = {}): Montado {
  const bd = new BaseFalsa();
  const resolvedorBd = new BaseFalsa().responde("tenant_channels", {
    rows: opcoes.canal === null ? [] : [linhaDeCanal(opcoes.canal ?? {})],
  });
  bd.responde("INSERT INTO platform.conversations", {
    rows: [{ id: CONVERSA, mode: opcoes.modo ?? "bot" }],
  });

  const entrega = new EntregaFalsa();
  const metricas = new MetricasDoChr();
  const quarentenadas: { evento: unknown; motivo: string }[] = [];
  const registos: { outcome: string; error_code?: string }[] = [];
  const contextos: string[] = [];

  const comTenant: ComTenant = async (tenant, trabalho) => {
    contextos.push(tenant);
    return trabalho(bd);
  };

  const chr = new Chr({
    resolvedor: new ResolvedorDeCanal(resolvedorBd),
    contacto: async () => {
      if (opcoes.contactoLanca !== undefined) throw opcoes.contactoLanca;
      return { contactId: CONTACTO };
    },
    entrega,
    quarentena: async (evento, motivo) => {
      quarentenadas.push({ evento, motivo });
    },
    metricas,
    registar: (campos) => registos.push(campos as never),
    agora: () => AGORA,
    comTenant,
  });

  return { chr, bd, entrega, metricas, quarentenadas, registos, contextos };
}

describe("criterio 2 — `phone_number_id` desconhecido", () => {
  it("0 jobs, 1 linha de quarentena, alerta", async () => {
    const m = montar({ canal: null });

    const resultado = await m.chr.tratar(mensagemDe());

    assert.equal(resultado.desfecho, "em_quarentena");
    assert.equal(resultado.motivo, "canal_desconhecido");
    assert.equal(m.entrega.aoAgr.length, 0);
    assert.equal(m.entrega.aoDono.length, 0);
    assert.equal(m.quarentenadas.length, 1);
    assert.equal(m.quarentenadas[0]?.motivo, "canal_desconhecido");
    assert.equal(
      m.metricas.ler()[`${METRICA_EM_QUARENTENA}:canal_desconhecido`],
      1,
    );
    assert.equal(m.metricas.ler()[`${METRICA_RESOLUCOES}:em_quarentena`], 1);
    assert.deepEqual(m.registos, [
      { outcome: "chr_em_quarentena", error_code: "canal_desconhecido", wa_type: "text" },
    ]);
  });

  it("nao abre conversa nenhuma, e nao resolve contacto nenhum", async () => {
    const m = montar({ canal: null });
    await m.chr.tratar(mensagemDe());
    assert.equal(m.bd.instrucoes.length, 0);
    assert.deepEqual(m.contextos, []);
  });

  it("um evento sem `phone_number_id` vai pelo mesmo caminho", async () => {
    // Nao ha pergunta a fazer, e o efeito e o mesmo: nao se sabe de quem e.
    const m = montar();
    const resultado = await m.chr.tratar(mensagemDe({ phoneNumberId: null }));
    assert.equal(resultado.motivo, "canal_desconhecido");
    assert.equal(m.entrega.aoAgr.length, 0);
  });

  it("um erro da base **nao** e um canal desconhecido: lanca", async () => {
    // O primeiro merece retentativa — e o *job* volta a fila sem
    // `processado_at` —, o segundo e quarentena. Confundi-los punha um evento
    // valido na quarentena por causa de uma ligacao perdida.
    const resolvedorBd = new BaseFalsa().responde(
      "tenant_channels",
      new Error("ligacao perdida"),
    );
    const chr = new Chr({
      resolvedor: new ResolvedorDeCanal(resolvedorBd),
      contacto: async () => ({ contactId: CONTACTO }),
      entrega: new EntregaFalsa(),
      quarentena: async () => {
        assert.fail("nao devia quarentenar");
      },
      metricas: new MetricasDoChr(),
      comTenant: async (_t, trabalho) => trabalho(new BaseFalsa()),
    });

    await assert.rejects(() => chr.tratar(mensagemDe()), /ligacao perdida/);
  });
});

describe("criterio 5 — Fluxo B recusado em execucao", () => {
  for (const [nome, canal, tipo] of [
    ["canal `origem = plataforma`", { origem: ORIGEM_DE_PLATAFORMA }, "pme"],
    ["vertical `assistente`", { vertical: "assistente" }, "pme"],
    ["tenant `platform`", {}, TIPO_DE_PLATAFORMA],
  ] as const) {
    it(`${nome}: 0 jobs, alerta, e **sem** linha de quarentena`, async () => {
      const m = montar({ canal: { ...canal, tipo_tenant: tipo } });

      const resultado = await m.chr.tratar(mensagemDe());

      assert.equal(resultado.desfecho, "fluxo_b_recusado");
      assert.equal(m.entrega.aoAgr.length, 0);
      assert.equal(m.entrega.aoDono.length, 0);
      // O criterio pede «0 *jobs*, alerta» e **nao** uma linha de quarentena.
      assert.equal(m.quarentenadas.length, 0);
      assert.equal(m.metricas.ler()[`${METRICA_RESOLUCOES}:fluxo_b_recusado`], 1);
      assert.equal(m.registos[0]?.error_code, "fluxo_b_recusado");
      // E nao se abre conversa: a recusa e **antes** de haver contacto.
      assert.equal(m.bd.instrucoes.length, 0);
    });
  }

  it("a recusa e antes da matriz de estados: um canal `ativo` nao a dispensa", async () => {
    const m = montar({
      canal: { origem: ORIGEM_DE_PLATAFORMA, estado_tenant: "ativo", estado_canal: "ativo" },
    });
    assert.equal((await m.chr.tratar(mensagemDe())).desfecho, "fluxo_b_recusado");
  });
});

describe("criterio 3 — a matriz de estados, linha a linha", () => {
  // As seis linhas do §7.2, pela coluna «Estado do tenant/canal». O par
  // escolhido e o que **isola** a linha: o outro dominio fica `ativo`, para que
  // o regime venha de quem se quer testar.
  const LINHAS: readonly {
    readonly linha: string;
    readonly tenant: string;
    readonly canal: string;
    readonly abreConversa: boolean;
    readonly aoAgr: boolean;
    readonly saida: string | null;
  }[] = [
    // «Registar; nao responder ao publico» / saida «Nenhuma» / «So mensagem de
    // teste do onboarding».
    {
      linha: "onboarding/pendente",
      tenant: "onboarding",
      canal: "ativo",
      abreConversa: true,
      aoAgr: false,
      saida: "mensagem_de_teste",
    },
    {
      linha: "pendente (canal)",
      tenant: "ativo",
      canal: "pendente",
      abreConversa: true,
      aoAgr: false,
      saida: "mensagem_de_teste",
    },
    // «Normal» / «Normal».
    {
      linha: "ativo",
      tenant: "ativo",
      canal: "ativo",
      abreConversa: true,
      aoAgr: true,
      saida: null,
    },
    // «Normal» / «So respostas dentro da janela; sem templates marketing».
    {
      linha: "restrito",
      tenant: "ativo",
      canal: "restrito",
      abreConversa: true,
      aoAgr: true,
      saida: null,
    },
    // «Nenhuma entrada chega (coexistencia removida)» / «Nenhuma».
    {
      linha: "desligado",
      tenant: "ativo",
      canal: "desligado",
      abreConversa: false,
      aoAgr: false,
      saida: null,
    },
    // «Registar» / «Mensagem estatica uma vez por contacto/24 h».
    {
      linha: "suspenso",
      tenant: "ativo",
      canal: "suspenso",
      abreConversa: true,
      aoAgr: false,
      saida: "mensagem_estatica",
    },
    // «Registar e descartar» / «Nenhuma».
    {
      linha: "encerrado",
      tenant: "ativo",
      canal: "encerrado",
      abreConversa: true,
      aoAgr: false,
      saida: null,
    },
  ];

  for (const caso of LINHAS) {
    it(`${caso.linha}: conversa=${caso.abreConversa}, AGR=${caso.aoAgr}, saida=${caso.saida}`, async () => {
      const m = montar({
        canal: { estado_tenant: caso.tenant, estado_canal: caso.canal },
      });

      const resultado = await m.chr.tratar(mensagemDe());

      assert.equal(
        m.bd.quantas("INSERT INTO platform.conversations") === 1,
        caso.abreConversa,
        "abriu conversa",
      );
      assert.equal(m.entrega.aoAgr.length, caso.aoAgr ? 1 : 0, "jobs ao AGR");
      assert.equal(resultado.saida, caso.saida, "saida automatica");
      assert.equal(
        resultado.desfecho,
        caso.aoAgr ? "encaminhado" : "estado_recusou",
        "desfecho",
      );
    });
  }

  it("`desligado` nao resolve contacto nenhum: a matriz para antes", async () => {
    const m = montar({ canal: { estado_canal: "desligado" } });
    const resultado = await m.chr.tratar(mensagemDe());
    assert.equal(resultado.contactId, null);
    assert.equal(resultado.conversationId, null);
    assert.deepEqual(m.contextos, []);
  });

  it("as 30 combinacoes de estados sao decididas, e nenhuma lanca", async () => {
    // 5 estados de tenant x 6 de canal. O que se afirma e que **toda** a
    // combinacao tem resposta: um par sem celula seria um evento tratado por
    // omissao, e a omissao aqui e responder ao publico.
    for (const tenant of ESTADOS_DO_TENANT) {
      for (const canal of ESTADOS_DO_CANAL) {
        const m = montar({ canal: { estado_tenant: tenant, estado_canal: canal } });
        const resultado = await m.chr.tratar(mensagemDe());
        assert.ok(
          ["encaminhado", "estado_recusou"].includes(resultado.desfecho),
          `${tenant}/${canal}: ${resultado.desfecho}`,
        );
        // So o par (ativo|restrito) x (ativo|restrito) chega ao AGR.
        const esperado =
          ["ativo", "restrito"].includes(tenant) && ["ativo", "restrito"].includes(canal);
        assert.equal(m.entrega.aoAgr.length === 1, esperado, `${tenant}/${canal}`);
      }
    }
  });
});

describe("criterio 6 — o job entregue ao AGR", () => {
  it("leva os sete campos, o `thread_id` e o `vertical`", async () => {
    const m = montar();
    const resultado = await m.chr.tratar(mensagemDe());
    assert.deepEqual(resultado.invocacao, m.entrega.aoAgr[0]);
    assert.deepEqual(Object.keys(m.entrega.aoAgr[0] ?? {}).sort(), [
      "channel_id",
      "contact_id",
      "conversation_id",
      "modo",
      "tenant_id",
      "thread_id",
      "type",
      "vertical",
      "wamid",
    ]);
  });

  it("nao leva telefone, BSUID nem `display_name`", async () => {
    const m = montar();
    await m.chr.tratar(
      mensagemDe({ interlocutor: { bsuid: "BSUID-SECRETO", telefone: "999100000002" } }),
    );
    const texto = JSON.stringify(m.entrega.aoAgr[0]);
    assert.ok(!texto.includes("BSUID-SECRETO"));
    assert.ok(!texto.includes("999100000002"));
    assert.ok(!texto.includes("display_name"));
  });

  it("o `tenant_id` do job e o do canal resolvido, e nao vem do evento", async () => {
    const m = montar({ canal: { tenant_id: "99999999-9999-4999-8999-999999999999" } });
    await m.chr.tratar(mensagemDe());
    assert.equal(m.entrega.aoAgr[0]?.tenant_id, "99999999-9999-4999-8999-999999999999");
  });

  it("a conversa abre-se com a janela de 24 h, a partir do relogio injectado", async () => {
    const m = montar();
    await m.chr.tratar(mensagemDe());
    const insercao = m.bd.instrucoes.find((i) =>
      i.sql.includes("INSERT INTO platform.conversations"),
    );
    assert.deepEqual(insercao?.parametros.slice(3), [
      AGORA,
      new Date(AGORA.getTime() + 24 * 60 * 60 * 1000),
    ]);
  });

  it("a conversa escreve-se **dentro** de uma transacao com contexto", async () => {
    const m = montar();
    await m.chr.tratar(mensagemDe());
    assert.deepEqual(m.contextos, [linhaDeCanal().tenant_id]);
  });
});

describe("criterio 7 — modo diferente de `bot` nao vai ao AGR", () => {
  for (const modo of ["dono", "humano", "pausada"] as const) {
    it(`modo \`${modo}\`: 0 jobs, vai ao dono`, async () => {
      const m = montar({ modo });

      const resultado = await m.chr.tratar(mensagemDe());

      assert.equal(resultado.desfecho, "entregue_ao_dono");
      assert.equal(m.entrega.aoAgr.length, 0);
      assert.equal(m.entrega.aoDono.length, 1);
      assert.equal(resultado.conversationId, CONVERSA);
      assert.equal(m.metricas.ler()[`${METRICA_RESOLUCOES}:entregue_ao_dono`], 1);
    });
  }

  it("um modo `humano` num tenant `ativo` continua a nao ir ao AGR", async () => {
    // A verificacao do modo e **antes** da matriz: um tenant perfeitamente
    // normal nao faz o bot interromper uma pessoa (docs/tecnica/01 §10.2).
    const m = montar({ modo: "humano", canal: { estado_tenant: "ativo" } });
    assert.equal((await m.chr.tratar(mensagemDe())).desfecho, "entregue_ao_dono");
  });

  it("um `echo` vai sempre ao dono, e nunca ao AGR", async () => {
    const m = montar();
    const resultado = await m.chr.tratar(
      mensagemDe({ kind: "echo", interlocutor: null }),
    );
    assert.equal(resultado.desfecho, "entregue_ao_dono");
    assert.equal(m.entrega.aoAgr.length, 0);
    // E nao abre conversa nem resolve contacto: o destinatario de um `echo`
    // esta num campo NAO VERIFICADO, e a transicao de modo e KAM-018.
    assert.equal(m.bd.instrucoes.length, 0);
    assert.equal(resultado.contactId, null);
  });

  it("um modo que o codigo nao conhece **para**, e nao vai ao AGR", async () => {
    // Entregar ao AGR por nao se reconhecer o modo era o assistente a
    // interromper uma conversa que uma pessoa estava a fazer.
    const m = montar({ modo: "arquivada" });
    await assert.rejects(() => m.chr.tratar(mensagemDe()), /modo desconhecido/);
    assert.equal(m.entrega.aoAgr.length, 0);
  });
});

describe("uma mensagem sem identidade", () => {
  it("vai a quarentena em vez de fazer o job repetir sete dias", async () => {
    const m = montar();
    const resultado = await m.chr.tratar(
      mensagemDe({ interlocutor: { bsuid: null, telefone: null } }),
    );
    assert.equal(resultado.desfecho, "em_quarentena");
    assert.equal(resultado.motivo, "mensagem_sem_identidade");
    assert.equal(m.entrega.aoAgr.length, 0);
    assert.equal(m.bd.instrucoes.length, 0);
  });

  it("so o BSUID basta, e so o telefone tambem", async () => {
    for (const interlocutor of [
      { bsuid: "bsuid-1", telefone: null },
      { bsuid: null, telefone: "999100000001" },
    ]) {
      const m = montar();
      const resultado = await m.chr.tratar(mensagemDe({ interlocutor }));
      assert.equal(resultado.desfecho, "encaminhado", JSON.stringify(interlocutor));
    }
  });
});

describe("as metricas", () => {
  let m: Montado;
  beforeEach(() => {
    m = montar();
  });

  it("o racio de acertos sobe com a cache e o gauge da duracao e medido", async () => {
    await m.chr.tratar(mensagemDe());
    await m.chr.tratar(mensagemDe({ eventKey: "wamid.BBB" }));
    const lido = m.metricas.ler();
    assert.equal(lido["chr_cache_hit_ratio"], 0.5);
    assert.equal(lido["chr_resolve_ms"], 0);
    assert.equal(lido[`${METRICA_RESOLUCOES}:encaminhado`], 2);
  });

  it("um evento sem `phone_number_id` nao conta como falha de cache", async () => {
    // Nao houve resolucao: contar uma estragava o racio de acertos, que e o que
    // o DoD pede para medir.
    await m.chr.tratar(mensagemDe({ phoneNumberId: null }));
    assert.equal(m.metricas.ler()["chr_cache_hit_ratio"], undefined);
  });
});

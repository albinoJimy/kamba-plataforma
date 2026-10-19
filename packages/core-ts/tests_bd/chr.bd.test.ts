/**
 * O CHR contra um PostgreSQL real — KAM-014.
 *
 * Estes testes **não correm no gate 4**: precisam da base descartável que
 * `db/gate_bd.py --suite tests_chr` levanta, com os cinco papéis criados e as
 * migrações em `head`. O que só aqui se prova, e que nenhuma base falsa prova:
 *
 *   isolamento      o `phone_number_id` de A nunca devolve o contexto de B, e a
 *                   propriedade vem da `tenant_channels_phone_number_id_uq` e
 *                   da política `resolver_leitura` — não do código (critério 8);
 *   o papel         `kamba_app` **não** consegue responder à pergunta: sem
 *                   contexto de tenant, a `tenant_iso` dá-lhe zero linhas. É o
 *                   que torna o `kamba_resolver` necessário e não conveniente;
 *   convergência    o mesmo cliente visto só por telefone e só por BSUID dá
 *                   **um** `contact_id`, e a fusão emite `contact.merged`
 *                   exactamente uma vez em dez repetições (critério 4);
 *   o gancho        as conversas do contacto absorvido são reapontadas **dentro**
 *                   da transacção da fusão, e a colisão de canal dobra os tempos
 *                   em vez de violar a `UNIQUE`;
 *   idempotência    o mesmo `wamid` duas vezes deixa **uma** conversa (DoD);
 *   arranque        a guarda do ADR-011 recusa com uma linha de Fluxo B, e
 *                   recusa-se a correr com um papel que não vê tudo (critério 5);
 *   quarentena      um `phone_number_id` desconhecido deixa **uma** linha, e a
 *                   re-entrega do mesmo evento não deixa uma segunda (critério 2);
 *   latência        p95 de `resolve` com e sem *cache* (critério 8).
 *
 * Nada aqui é um dado real: os BSUID são `AO.ENSAIO…` e os telefones usam o
 * indicativo `999`, que a UIT não atribui a nenhum país.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  Chr,
  type ComTenant,
  type EntregaDoChr,
  FASE_PILOTO,
  FaseNaoDefinidaError,
  FluxoBNoPilotoError,
  GuardaCegaError,
  MetricasDoChr,
  ORIGEM_DE_PLATAFORMA,
  ResolvedorDeCanal,
  SQL_CANAL,
  VARIAVEL_DA_FASE,
  repontarConversas,
  verificarArranque,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import type { EventoDeEntrada } from "../src/entrada/index.ts";
import { porEmQuarentena } from "../src/entrada/index.ts";
import type { Identidade } from "../src/identity/index.ts";
import { comTenant as comTenantReal } from "../src/tenant_guard/index.ts";
import {
  ChavesDeTeste,
  apagarTenant,
  bsuidDeEnsaio,
  conversasDe,
  criarCanal,
  criarTenant,
  ligar,
  telefoneDeEnsaio,
} from "./apoio.ts";

const PILOTO = { [VARIAVEL_DA_FASE]: FASE_PILOTO };
/** A versão de chave de pesquisa destes ensaios. */
const KID = "k-chr";

let admin: pg.Client;
let resolverBd: pg.Client;
let appBd: pg.Client;
let identityBd: pg.Client;
let identidade: Identidade;

before(async () => {
  admin = await ligar("admin");
  resolverBd = await ligar("resolver");
  appBd = await ligar("app");
  identityBd = await ligar("identity");

  identidade = await new ChavesDeTeste(KID).identidade();
  // O gancho que este ticket registra: reaponta conversas **dentro** da
  // transacção da fusão, com a ligação do módulo de identidade.
  identidade.onContactMerge(async ({ cliente, tenantId, de, para }) => {
    await repontarConversas(cliente, tenantId, de, para);
  });
});

after(async () => {
  for (const cliente of [identityBd, appBd, resolverBd, admin]) {
    await cliente.end().catch(() => {});
  }
});

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
  readonly entrega: EntregaFalsa;
  readonly metricas: MetricasDoChr;
  readonly resolvedor: ResolvedorDeCanal;
  readonly fundidos: number[];
}

/** Monta um CHR com os três papéis verdadeiros e o gancho de fusão registado. */
function montar(agora?: () => Date): Montado {
  const entrega = new EntregaFalsa();
  const metricas = new MetricasDoChr();
  const resolvedor = new ResolvedorDeCanal(resolverBd);
  const fundidos: number[] = [];
  const comTenant: ComTenant = (tenant, trabalho) =>
    comTenantReal(appBd, tenant, () => trabalho(appBd));

  const chr = new Chr({
    resolvedor,
    contacto: async (pedido) => {
      const resolvido = await identidade.resolveContact(identityBd, pedido);
      if (resolvido.evento !== null) fundidos.push(1);
      return { contactId: resolvido.contactId };
    },
    entrega,
    quarentena: async (evento, motivo) =>
      porEmQuarentena(
        appBd,
        {
          kind: "desconhecido",
          eventKey: evento.eventKey,
          motivo,
          wabaId: evento.wabaId,
          phoneNumberId: evento.phoneNumberId,
        },
        null,
      ),
    metricas,
    ...(agora === undefined ? {} : { agora }),
    comTenant,
  });
  return { chr, entrega, metricas, resolvedor, fundidos };
}

function mensagem(
  phoneNumberId: string | null,
  interlocutor: { bsuid: string | null; telefone: string | null },
  wamid = `wamid.${randomUUID()}`,
): EventoDeEntrada {
  return {
    kind: "message",
    eventKey: wamid,
    wabaId: "waba-ensaio",
    phoneNumberId,
    waType: "text",
    interlocutor,
  };
}

/**
 * Prepara um tenant `ativo` com a versão de chave registada, e devolve o `id`.
 *
 * **O `ativo` é explícito, e tem de ser**: `platform.tenants.estado` nasce
 * `onboarding` (revisão `0001`), e o regime de `onboarding` é a linha `pendente`
 * do §7.2 — «registar; não responder ao público». Um tenant acabado de criar
 * recusa **tudo** o que o AGR devia receber, e os ensaios que precisam do
 * caminho completo ficavam a medir a matriz de estados sem o saber. Foi assim
 * que esta suite falhou à primeira, em três testes ao mesmo tempo.
 */
async function tenantComChave(rotulo: string): Promise<string> {
  const id = await criarTenant(admin, rotulo);
  await admin.query("UPDATE platform.tenants SET estado = 'ativo' WHERE id = $1", [id]);
  await identidade.iniciarRotacao(identityBd, KID).catch(() => {});
  return id;
}

async function contarQuarentena(motivo: string, eventKey: string): Promise<number> {
  const { rows } = await admin.query(
    "SELECT count(*)::int AS n FROM platform.unrouted_events " +
      "WHERE motivo = $1 AND event_key = $2",
    [motivo, eventKey],
  );
  return (rows[0] as { n: number }).n;
}

describe("critério 8 — isolamento: o phone_number_id de A nunca devolve B", () => {
  it("o resolvedor responde sem contexto, e cada pnid devolve o seu tenant", async () => {
    const a = await criarTenant(admin, "iso-a");
    const b = await criarTenant(admin, "iso-b");
    try {
      const canalA = await criarCanal(admin, a);
      const canalB = await criarCanal(admin, b);
      const resolvedor = new ResolvedorDeCanal(resolverBd);

      const lidoA = await resolvedor.resolver(canalA.phoneNumberId);
      const lidoB = await resolvedor.resolver(canalB.phoneNumberId);

      assert.equal(lidoA.resolvido?.contexto.tenant_id, a);
      assert.equal(lidoA.resolvido?.contexto.channel_id, canalA.id);
      assert.equal(lidoB.resolvido?.contexto.tenant_id, b);
      assert.notEqual(
        lidoA.resolvido?.contexto.tenant_id,
        lidoB.resolvido?.contexto.tenant_id,
      );
    } finally {
      await apagarTenant(admin, a);
      await apagarTenant(admin, b);
    }
  });

  it("`kamba_app` sem contexto **nao** consegue responder: zero linhas", async () => {
    // É o que torna o `kamba_resolver` necessário e não conveniente: com a
    // política `tenant_iso`, um papel sem contexto vê zero linhas — e o CHR
    // concluiria «canal desconhecido» para um canal que existe.
    const a = await criarTenant(admin, "iso-papel");
    try {
      const canal = await criarCanal(admin, a);
      const comApp = await appBd.query(SQL_CANAL, [canal.phoneNumberId]);
      assert.equal(comApp.rows.length, 0);
      const comResolvedor = await resolverBd.query(SQL_CANAL, [canal.phoneNumberId]);
      assert.equal(comResolvedor.rows.length, 1);
    } finally {
      await apagarTenant(admin, a);
    }
  });

  it("o `plano` esta entre as colunas que o resolvedor le", async () => {
    // Foi a `0009` que lho concedeu; sem ele o `ChannelContext` do critério 1
    // ficava a sete campos.
    const a = await criarTenant(admin, "iso-plano");
    try {
      await admin.query("UPDATE platform.tenants SET plano = 'k1' WHERE id = $1", [a]);
      const canal = await criarCanal(admin, a);
      const lido = await new ResolvedorDeCanal(resolverBd).resolver(canal.phoneNumberId);
      assert.equal(lido.resolvido?.contexto.plano, "k1");
    } finally {
      await apagarTenant(admin, a);
    }
  });

  it("uma conversa de B nao se ve com o contexto de A", async () => {
    const a = await criarTenant(admin, "iso-conv-a");
    const b = await tenantComChave("iso-conv-b");
    try {
      const canalB = await criarCanal(admin, b);
      const m = montar();
      await m.chr.tratar(
        mensagem(canalB.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }),
      );
      assert.equal((await conversasDe(admin, b)).length, 1);

      const vistasPorA = await comTenantReal(appBd, a, async () =>
        appBd.query("SELECT count(*)::int AS n FROM platform.conversations"),
      );
      assert.equal((vistasPorA.rows[0] as { n: number }).n, 0);
    } finally {
      await apagarTenant(admin, a);
      await apagarTenant(admin, b);
    }
  });
});

describe("critério 4 — BSUID e telefone convergem no mesmo contact_id", () => {
  it("só wa_id e depois só BSUID: um contacto, e `contact.merged` uma vez em dez repetições", async () => {
    // **O critério 4 não se cumpre à letra, e é esta medição que o mostra.**
    //
    // A letra diz «mensagem com apenas `wa_id` e mensagem com apenas BSUID do
    // mesmo cliente convergem no mesmo `contact_id`». Com o algoritmo do
    // KAM-008 (`docs/identidade.md` §4), que é o de `docs/tecnica/01` §6.3,
    // isso é **impossível**: nada liga um BSUID a um número a não ser uma
    // mensagem que traga os dois. Uma mensagem só com BSUID procura por BSUID,
    // não acha, não tem telefone por onde procurar — e **cria**.
    //
    // A convergência acontece na primeira mensagem que traz os dois, e daí em
    // diante é verdadeira nos dois sentidos: só-telefone e só-BSUID devolvem o
    // mesmo `contact_id`, e quem ainda tenha o antigo chega ao novo pela lápide
    // (`merged_into`). É isso que se mede aqui, e é por isso que a caixa desse
    // critério fica **vazia** na secção de verificação do ticket, com a razão.
    const tenant = await tenantComChave("convergencia");
    try {
      const canal = await criarCanal(admin, tenant);
      const telefone = telefoneDeEnsaio();
      const bsuid = bsuidDeEnsaio();
      const m = montar();

      // 1) O cliente escreve e só vem o telefone (o `username` ainda não foi
      //    adoptado, `E1` §3): nasce um contacto só com telefone.
      const soTelefone = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid: null, telefone }),
      );
      // 2) O mesmo cliente volta a escrever, e agora vem só o BSUID. **Nasce um
      //    segundo contacto** — é o que o algoritmo faz, e o que a letra do
      //    critério não previu.
      const soBsuid = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );
      assert.equal(soTelefone.desfecho, "encaminhado");
      assert.equal(soBsuid.desfecho, "encaminhado");
      assert.notEqual(
        soTelefone.contactId,
        soBsuid.contactId,
        "sem os dois identificadores juntos, nada liga o BSUID ao numero",
      );

      // 3) Agora vêm os dois, dez vezes. A fusão acontece **uma** vez.
      const depois: string[] = [];
      for (let i = 0; i < 10; i += 1) {
        const r = await m.chr.tratar(mensagem(canal.phoneNumberId, { bsuid, telefone }));
        depois.push(String(r.contactId));
      }
      assert.equal(m.fundidos.length, 1, "contact.merged exactamente uma vez em dez");
      assert.equal(new Set(depois).size, 1, "as dez devolvem o mesmo contacto");
      // Fica o **mais antigo**, que é o que nasceu do telefone.
      assert.equal(depois[0], soTelefone.contactId);

      // 4) E daqui em diante converge nos dois sentidos.
      const outraVezSoTelefone = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid: null, telefone }),
      );
      const outraVezSoBsuid = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );
      assert.equal(outraVezSoTelefone.contactId, soTelefone.contactId);
      assert.equal(outraVezSoBsuid.contactId, soTelefone.contactId);

      // 5) O contacto absorvido fica como lápide, e aponta para quem ficou:
      //    quem ainda tenha o `contact_id` antigo chega ao novo.
      const { rows } = await admin.query(
        "SELECT merged_into::text AS para FROM platform.contacts WHERE contact_id = $1",
        [soBsuid.contactId],
      );
      assert.equal((rows[0] as { para: string }).para, soTelefone.contactId);

      // 6) As conversas: duas linhas no mesmo canal, porque a `UNIQUE` não
      //    deixa juntá-las — a do contacto que ficou e a que sobra na lápide.
      //    Nenhuma aponta para um contacto que não exista.
      const conversas = await conversasDe(admin, tenant);
      assert.equal(conversas.length, 2);
      assert.ok(conversas.some((c) => c.contact_id === soTelefone.contactId));
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("o mesmo BSUID em dois tenants dá dois contactos e duas conversas", async () => {
    const a = await tenantComChave("cruz-a");
    const b = await tenantComChave("cruz-b");
    try {
      const canalA = await criarCanal(admin, a);
      const canalB = await criarCanal(admin, b);
      const bsuid = bsuidDeEnsaio();
      const m = montar();

      const emA = await m.chr.tratar(mensagem(canalA.phoneNumberId, { bsuid, telefone: null }));
      const emB = await m.chr.tratar(mensagem(canalB.phoneNumberId, { bsuid, telefone: null }));

      assert.notEqual(emA.contactId, emB.contactId);
      assert.equal((await conversasDe(admin, a)).length, 1);
      assert.equal((await conversasDe(admin, b)).length, 1);
    } finally {
      await apagarTenant(admin, a);
      await apagarTenant(admin, b);
    }
  });
});

describe("o gancho de fusão reaponta conversas, e a colisão dobra os tempos", () => {
  it("sem colisão: a conversa do absorvido passa para quem fica", async () => {
    const tenant = await tenantComChave("fusao-simples");
    try {
      // Dois canais: o contacto só-telefone conversa no canal 1 e o do BSUID
      // no canal 2. Quando se fundem, a conversa do canal 1 reaponta.
      const canal1 = await criarCanal(admin, tenant);
      const canal2 = await criarCanal(admin, tenant);
      const telefone = telefoneDeEnsaio();
      const bsuid = bsuidDeEnsaio();
      const m = montar();

      const soTelefone = await m.chr.tratar(
        mensagem(canal1.phoneNumberId, { bsuid: null, telefone }),
      );
      const soBsuid = await m.chr.tratar(
        mensagem(canal2.phoneNumberId, { bsuid, telefone: null }),
      );
      assert.notEqual(soTelefone.contactId, soBsuid.contactId);
      assert.equal((await conversasDe(admin, tenant)).length, 2);

      // Agora vêm os dois: funde-se no mais antigo (o só-telefone).
      const fundida = await m.chr.tratar(
        mensagem(canal1.phoneNumberId, { bsuid, telefone }),
      );
      assert.equal(m.fundidos.length, 1);

      const conversas = await conversasDe(admin, tenant);
      assert.equal(conversas.length, 2);
      assert.deepEqual(
        [...new Set(conversas.map((c) => c.contact_id))],
        [String(fundida.contactId)],
        "as duas conversas apontam para o contacto que ficou",
      );
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("com colisão no mesmo canal: dobra os tempos e não viola a UNIQUE", async () => {
    const tenant = await tenantComChave("fusao-colisao");
    try {
      const canal = await criarCanal(admin, tenant);
      const telefone = telefoneDeEnsaio();
      const bsuid = bsuidDeEnsaio();

      // Os dois contactos conversam no **mesmo** canal, em instantes diferentes.
      const cedo = new Date("2026-10-18T08:00:00.000Z");
      const tarde = new Date("2026-10-19T08:00:00.000Z");
      const mCedo = montar(() => cedo);
      const mTarde = montar(() => tarde);

      await mCedo.chr.tratar(mensagem(canal.phoneNumberId, { bsuid: null, telefone }));
      await mTarde.chr.tratar(mensagem(canal.phoneNumberId, { bsuid, telefone: null }));
      assert.equal((await conversasDe(admin, tenant)).length, 2);

      const fundida = await mTarde.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone }),
      );
      assert.equal(mTarde.fundidos.length, 1);

      const conversas = await conversasDe(admin, tenant);
      // Continuam duas linhas — a `UNIQUE` não deixa juntá-las —, e a do
      // contacto que ficou tem o tempo **mais tardio** das duas.
      assert.equal(conversas.length, 2);
      const daQueFica = conversas.find((c) => c.contact_id === fundida.contactId);
      assert.ok(daQueFica !== undefined);
      assert.ok(
        (daQueFica.last_inbound_at as Date).getTime() >= tarde.getTime(),
        "a janela ficou com o instante mais tardio",
      );
      // E a outra ficou pendurada na lápide, que continua a existir.
      const lapide = conversas.find((c) => c.contact_id !== fundida.contactId);
      assert.ok(lapide !== undefined);
      const { rows } = await admin.query(
        "SELECT merged_into::text AS para FROM platform.contacts WHERE contact_id = $1",
        [lapide.contact_id],
      );
      assert.equal((rows[0] as { para: string }).para, fundida.contactId);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("se o gancho lançar, a fusão inteira é desfeita", async () => {
    // É a garantia do KAM-008, e é a razão por que o gancho corre com o papel
    // da identidade: sem ela, um `kill -9` deixava conversas penduradas numa
    // lápide.
    const tenant = await tenantComChave("fusao-rollback");
    try {
      const canal = await criarCanal(admin, tenant);
      const telefone = telefoneDeEnsaio();
      const bsuid = bsuidDeEnsaio();
      const m = montar();
      await m.chr.tratar(mensagem(canal.phoneNumberId, { bsuid: null, telefone }));
      const doBsuid = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );
      const antes = await conversasDe(admin, tenant);

      // Um gancho que falha, registado só para este ensaio.
      const retirar = identidade.onContactMerge(async () => {
        throw new Error("gancho de ensaio falhou");
      });
      try {
        await assert.rejects(
          () =>
            identidade.resolveContact(identityBd, {
              tenantId: tenant,
              bsuid,
              telefone,
            }),
          /gancho de ensaio falhou/,
        );
      } finally {
        retirar();
      }

      // Nada mudou: nem os contactos, nem as conversas.
      assert.deepEqual(await conversasDe(admin, tenant), antes);
      const { rows } = await admin.query(
        "SELECT count(*)::int AS n FROM platform.contacts " +
          "WHERE tenant_id = $1 AND merged_into IS NOT NULL",
        [tenant],
      );
      assert.equal((rows[0] as { n: number }).n, 0);
      assert.ok(doBsuid.contactId !== null);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });
});

describe("DoD — idempotência: o mesmo wamid não cria duas conversas nem dois jobs", () => {
  it("o mesmo evento duas vezes deixa uma conversa e dois jobs com o mesmo jobId", async () => {
    const tenant = await tenantComChave("idempotencia");
    try {
      const canal = await criarCanal(admin, tenant);
      const bsuid = bsuidDeEnsaio();
      const m = montar();
      const evento = mensagem(canal.phoneNumberId, { bsuid, telefone: null });

      await m.chr.tratar(evento);
      await m.chr.tratar(evento);

      assert.equal((await conversasDe(admin, tenant)).length, 1);
      // Os dois *jobs* têm o mesmo `wamid`, logo o mesmo `jobId` — e é o BullMQ
      // que recusa o segundo (provado no teste unitário de `jobIdDe`; aqui o
      // que se mede é que a **base** não ganhou uma segunda conversa).
      assert.equal(m.entrega.aoAgr.length, 2);
      assert.equal(m.entrega.aoAgr[0]?.wamid, m.entrega.aoAgr[1]?.wamid);
      assert.equal(
        m.entrega.aoAgr[0]?.conversation_id,
        m.entrega.aoAgr[1]?.conversation_id,
      );
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("a segunda entrada empurra a janela, e não cria linha nova", async () => {
    const tenant = await tenantComChave("janela");
    try {
      const canal = await criarCanal(admin, tenant);
      const bsuid = bsuidDeEnsaio();
      const cedo = new Date("2026-10-18T08:00:00.000Z");
      const tarde = new Date("2026-10-19T08:00:00.000Z");

      await montar(() => cedo).chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );
      await montar(() => tarde).chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );

      const conversas = await conversasDe(admin, tenant);
      assert.equal(conversas.length, 1);
      assert.equal(conversas[0]?.last_inbound_at?.toISOString(), tarde.toISOString());
      assert.equal(
        conversas[0]?.window_expires_at?.toISOString(),
        new Date(tarde.getTime() + 24 * 60 * 60 * 1000).toISOString(),
      );
      assert.equal(conversas[0]?.mode, "bot", "uma entrada não muda o modo");
    } finally {
      await apagarTenant(admin, tenant);
    }
  });
});

describe("critério 2 — quarentena de um phone_number_id desconhecido", () => {
  it("uma linha, com o motivo `canal_desconhecido`, e a re-entrega não deixa outra", async () => {
    const m = montar();
    const evento = mensagem(`pnid-que-nao-existe-${randomUUID()}`, {
      bsuid: bsuidDeEnsaio(),
      telefone: null,
    });

    const primeira = await m.chr.tratar(evento);
    const segunda = await m.chr.tratar(evento);

    assert.equal(primeira.desfecho, "em_quarentena");
    assert.equal(segunda.desfecho, "em_quarentena");
    assert.equal(m.entrega.aoAgr.length, 0);
    // **Uma** linha: o `ON CONFLICT (kind, event_key)` da `0008` apanha a
    // re-entrega, que a Meta faz durante sete dias.
    assert.equal(await contarQuarentena("canal_desconhecido", evento.eventKey), 1);
  });

  it("uma mensagem sem `from` e sem `from_user_id` vai à quarentena com o seu motivo", async () => {
    const tenant = await tenantComChave("sem-identidade");
    try {
      const canal = await criarCanal(admin, tenant);
      const m = montar();
      const evento = mensagem(canal.phoneNumberId, { bsuid: null, telefone: null });

      const resultado = await m.chr.tratar(evento);

      assert.equal(resultado.motivo, "mensagem_sem_identidade");
      assert.equal(await contarQuarentena("mensagem_sem_identidade", evento.eventKey), 1);
      assert.equal((await conversasDe(admin, tenant)).length, 0);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("`kamba_app` escreve na quarentena e **não** lê o `payload`", async () => {
    // A propriedade é da `0008` e continua a valer para os motivos deste
    // ticket: a coluna que pode levar telefone e texto de mensagem não se lê.
    await assert.rejects(
      () => appBd.query("SELECT payload FROM platform.unrouted_events LIMIT 1"),
      /permission denied/,
    );
  });
});

describe("critério 5 — a guarda do ADR-011 no arranque", () => {
  it("base sem Fluxo B e fase `piloto`: arranca", async () => {
    const contagem = await verificarArranque(resolverBd, PILOTO);
    assert.equal(contagem.tenantsPlataforma, 0);
    assert.equal(contagem.canaisPlataforma, 0);
    assert.equal(contagem.verticaisFora, 0);
  });

  it("com um canal `origem = plataforma`, o arranque é recusado", async () => {
    const tenant = await criarTenant(admin, "fluxo-b-origem");
    try {
      await criarCanal(admin, tenant, { origem: ORIGEM_DE_PLATAFORMA });
      await assert.rejects(
        () => verificarArranque(resolverBd, PILOTO),
        (erro: unknown) => {
          assert.ok(erro instanceof FluxoBNoPilotoError);
          assert.match(erro.message, /origem = 'plataforma'/);
          return true;
        },
      );
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("com uma vertical fora das duas de atendimento, o arranque é recusado", async () => {
    const tenant = await criarTenant(admin, "fluxo-b-vertical");
    try {
      await criarCanal(admin, tenant, { vertical: "assistente" });
      await assert.rejects(() => verificarArranque(resolverBd, PILOTO), FluxoBNoPilotoError);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("com um tenant `platform`, o arranque é recusado", async () => {
    const { rows } = await admin.query(
      "INSERT INTO platform.tenants (tipo, nome) VALUES ('platform', $1) RETURNING id::text AS id",
      [`Plataforma de ensaio ${randomUUID().slice(0, 8)}`],
    );
    const tenant = (rows[0] as { id: string }).id;
    try {
      await assert.rejects(() => verificarArranque(resolverBd, PILOTO), FluxoBNoPilotoError);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("com `kamba_app`, a guarda **recusa-se a correr** em vez de contar zero", async () => {
    // É a propriedade que impede a guarda de ser cega: um papel sujeito à RLS
    // sem contexto conta zero sobre uma base cheia de Fluxo B.
    await assert.rejects(() => verificarArranque(appBd, PILOTO), GuardaCegaError);
  });

  it("sem `KAMBA_FASE`, a guarda levanta — e não toca na base", async () => {
    await assert.rejects(() => verificarArranque(resolverBd, {}), FaseNaoDefinidaError);
  });

  it("com `kamba_batch`, que contorna a RLS, a guarda corre", async () => {
    // A primeira das três vias de visibilidade. Não é o papel com que a guarda
    // corre em produção — os serviços não recebem credenciais com `BYPASSRLS`
    // só para arrancar — mas a consulta tem de a reconhecer.
    const batch = await ligar("batch");
    try {
      await verificarArranque(batch, PILOTO);
    } finally {
      await batch.end();
    }
  });
});

describe("critério 3 — a matriz de estados contra a base", () => {
  it("um canal `desligado` não abre conversa, e um `ativo` abre", async () => {
    const tenant = await tenantComChave("estados");
    try {
      const desligado = await criarCanal(admin, tenant, { estado: "desligado" });
      const ativo = await criarCanal(admin, tenant, { estado: "ativo" });
      const bsuid = bsuidDeEnsaio();
      const m = montar();

      const recusado = await m.chr.tratar(
        mensagem(desligado.phoneNumberId, { bsuid, telefone: null }),
      );
      assert.equal(recusado.desfecho, "estado_recusou");
      assert.equal((await conversasDe(admin, tenant)).length, 0);

      const aceite = await m.chr.tratar(
        mensagem(ativo.phoneNumberId, { bsuid, telefone: null }),
      );
      assert.equal(aceite.desfecho, "encaminhado");
      assert.equal((await conversasDe(admin, tenant)).length, 1);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("um canal `suspenso` registra a conversa e não manda nada ao AGR", async () => {
    const tenant = await tenantComChave("suspenso");
    try {
      const canal = await criarCanal(admin, tenant, { estado: "suspenso" });
      const m = montar();
      const resultado = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }),
      );
      assert.equal(resultado.desfecho, "estado_recusou");
      assert.equal(resultado.saida, "mensagem_estatica");
      assert.equal(m.entrega.aoAgr.length, 0);
      assert.equal((await conversasDe(admin, tenant)).length, 1);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });
});

describe("critério 7 — uma conversa que não está em `bot` não vai ao AGR", () => {
  it("com o modo posto a `humano` pelo `kamba_batch`, a mensagem vai ao dono", async () => {
    // O modo é escrito pelo `kamba_batch` e não pelo `kamba_app`: a revisão
    // `0009` **não** dá `UPDATE (mode)` à aplicação, porque as transições são
    // KAM-018. Este teste prova as duas coisas de uma vez.
    const tenant = await tenantComChave("modo");
    try {
      const canal = await criarCanal(admin, tenant);
      const bsuid = bsuidDeEnsaio();
      const m = montar();
      await m.chr.tratar(mensagem(canal.phoneNumberId, { bsuid, telefone: null }));
      assert.equal(m.entrega.aoAgr.length, 1);

      await admin.query(
        "UPDATE platform.conversations SET mode = 'humano' WHERE tenant_id = $1",
        [tenant],
      );
      const resultado = await m.chr.tratar(
        mensagem(canal.phoneNumberId, { bsuid, telefone: null }),
      );

      assert.equal(resultado.desfecho, "entregue_ao_dono");
      assert.equal(m.entrega.aoAgr.length, 1, "nenhum job novo");
      assert.equal(m.entrega.aoDono.length, 1);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("`kamba_app` não consegue alterar o `mode`: o privilégio não existe", async () => {
    await assert.rejects(
      () =>
        comTenantReal(appBd, randomUUID(), async () =>
          appBd.query("UPDATE platform.conversations SET mode = 'bot'"),
        ),
      /permission denied/,
    );
  });
});

describe("critério 8 — latência de `resolve`", () => {
  it("p95 de 40 resoluções: sem cache ≤ 50 ms, com cache ≤ 5 ms", async () => {
    // Os dois limiares são *proposta* do próprio critério. A medição é mediana
    // e p95 de 40 execuções, que é o que o `docs/isolamento.md` §5 já faz para
    // o custo da política — e vale para o mesmo: detectar uma resolução que
    // passou a ser de outra ordem de grandeza, não orçamentar produção.
    const tenant = await criarTenant(admin, "latencia");
    try {
      const canal = await criarCanal(admin, tenant);
      const semCache: number[] = [];
      const comCache: number[] = [];

      for (let i = 0; i < 40; i += 1) {
        const resolvedor = new ResolvedorDeCanal(resolverBd);
        let inicio = process.hrtime.bigint();
        await resolvedor.resolver(canal.phoneNumberId);
        semCache.push(Number(process.hrtime.bigint() - inicio) / 1e6);

        inicio = process.hrtime.bigint();
        const lido = await resolvedor.resolver(canal.phoneNumberId);
        comCache.push(Number(process.hrtime.bigint() - inicio) / 1e6);
        assert.equal(lido.daCache, true);
      }

      const p95 = (valores: number[]) =>
        [...valores].sort((a, b) => a - b)[Math.ceil(valores.length * 0.95) - 1] ?? 0;
      const medido = { semCache: p95(semCache), comCache: p95(comCache) };
      // O número sai no registo do teste, para a secção de verificação do
      // ticket o poder citar.
      console.log(`[KAM-014] p95 resolve: sem cache ${medido.semCache.toFixed(3)} ms, com cache ${medido.comCache.toFixed(4)} ms`);
      assert.ok(medido.semCache <= 50, `p95 sem cache: ${medido.semCache} ms`);
      assert.ok(medido.comCache <= 5, `p95 com cache: ${medido.comCache} ms`);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("a invalidação por `channel_id` faz a resolução seguinte ver o estado novo", async () => {
    // É a metade do critério 1 que este ticket entrega: o caminho de
    // invalidação, com o `channel_id` que um `channel.updated` traria. **O
    // consumidor do evento não existe** — é KAM-016/KAM-021 que o emitem —, e
    // por isso o que se mede é a latência do caminho e não a do evento.
    const tenant = await criarTenant(admin, "invalidacao");
    try {
      const canal = await criarCanal(admin, tenant, { estado: "ativo" });
      const resolvedor = new ResolvedorDeCanal(resolverBd);
      assert.equal(
        (await resolvedor.resolver(canal.phoneNumberId)).resolvido?.contexto.estado_canal,
        "ativo",
      );

      await admin.query(
        "UPDATE platform.tenant_channels SET estado = 'suspenso' WHERE id = $1",
        [canal.id],
      );
      // Sem invalidar, a *cache* continua a dizer `ativo` — é o TTL a valer.
      assert.equal(
        (await resolvedor.resolver(canal.phoneNumberId)).resolvido?.contexto.estado_canal,
        "ativo",
      );

      const inicio = process.hrtime.bigint();
      resolvedor.invalidarCanal(canal.id);
      const depois = await resolvedor.resolver(canal.phoneNumberId);
      const ms = Number(process.hrtime.bigint() - inicio) / 1e6;

      assert.equal(depois.resolvido?.contexto.estado_canal, "suspenso");
      console.log(`[KAM-014] invalidacao + releitura: ${ms.toFixed(3)} ms`);
      assert.ok(ms <= 1_000, `invalidacao: ${ms} ms`);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });
});

describe("privacidade — nada do interlocutor chega ao job nem à conversa", () => {
  it("o BSUID e o telefone não aparecem no job, nem na linha de `conversations`", async () => {
    const tenant = await tenantComChave("privacidade");
    try {
      const canal = await criarCanal(admin, tenant);
      const bsuid = bsuidDeEnsaio("CANARIO");
      const telefone = telefoneDeEnsaio();
      const m = montar();

      await m.chr.tratar(mensagem(canal.phoneNumberId, { bsuid, telefone }));

      const job = JSON.stringify(m.entrega.aoAgr[0]);
      assert.ok(!job.includes(bsuid), "o BSUID nao vai no job");
      assert.ok(!job.includes(telefone), "o telefone nao vai no job");

      const { rows } = await admin.query(
        "SELECT * FROM platform.conversations WHERE tenant_id = $1",
        [tenant],
      );
      const linha = JSON.stringify(rows);
      assert.ok(!linha.includes(bsuid));
      assert.ok(!linha.includes(telefone));
    } finally {
      await apagarTenant(admin, tenant);
    }
  });
});

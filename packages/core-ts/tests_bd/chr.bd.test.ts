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
 *   latência        p95 de `resolve` com e sem *cache* (critério 8);
 *   activação       o `tenant.activated` que as portas do KAM-092 emitem,
 *                   consumido pelo `consumir` do KAM-006 com o efeito do CHR,
 *                   esquece o tenant na *cache* — e só esse (critério 7 do KAM-092);
 *   suspensão e     o `tenant.suspended` que a régua do KAM-058 emite e o
 *   encerramento    `tenant.closed` do off-boarding (KAM-098), consumidos pelo
 *                   mesmo efeito: o `Chr` com um AGR espião deixa de encaminhar
 *                   na mensagem seguinte, sem esperar o TTL (critério 2 do
 *                   KAM-058, critério 3 do KAM-098).
 *
 * Nada aqui é um dado real: os BSUID são `AO.ENSAIO…` e os telefones usam o
 * indicativo `999`, que a UIT não atribui a nenhum país.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
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
  efeitoDaActivacao,
  emitirContactMerged,
  payloadDaFusao,
  repontarConversas,
  verificarArranque,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import type { EventoDeEntrada } from "../src/entrada/index.ts";
import { consumir, type Envelope } from "../src/eventos/index.ts";
import { processar } from "../src/eventos/trabalho.ts";
import { porEmQuarentena } from "../src/entrada/index.ts";
import type { Identidade } from "../src/identity/index.ts";
import { comTenant as comTenantReal } from "../src/tenant_guard/index.ts";
import {
  ACTOR_DA_REGUA,
  MOTIVO_DA_SUSPENSAO,
  MOTIVO_NO_EVENTO,
  SQL_REGUA_EMITIR,
  SQL_REGUA_TRANSITAR,
} from "../src/pagamentos/index.ts";
import {
  ACTOR_DO_ENCERRAMENTO,
  MOTIVO_DO_ENCERRAMENTO,
  SQL_EMITIR as SQL_EMITIR_DO_ENCERRAMENTO,
  SQL_TRANSITAR as SQL_TRANSITAR_DO_ENCERRAMENTO,
} from "../src/offboarding/index.ts";
import {
  ChavesDeTeste,
  aceitarVigentes,
  activarTenant,
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

/** Os tenants que este ficheiro transita: o `tenant_state_log` deles limpa-se no fim. */
const transitados: string[] = [];

after(async () => {
  // A limpeza do KAM-092: o registo de estados é *append-only* também para o
  // dono. Desliga-se o gatilho, apagam-se só as linhas destes tenants, e liga-se.
  if (transitados.length > 0) {
    await admin.query("ALTER TABLE platform.tenant_state_log DISABLE TRIGGER USER");
    try {
      await admin.query("DELETE FROM platform.tenant_state_log WHERE tenant_id = ANY($1::uuid[])", [transitados]);
    } finally {
      await admin.query("ALTER TABLE platform.tenant_state_log ENABLE ALWAYS TRIGGER tenant_state_log_imutavel");
    }
  }
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
      if (resolvido.evento !== null) {
        // É o que o `entrada.ts` faz em produção: quem chama é quem emite.
        const fusao = resolvido.evento;
        await comTenantReal(appBd, fusao.tenant_id, () =>
          emitirContactMerged(appBd, fusao),
        );
        fundidos.push(1);
      }
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
  await activarTenant(admin, id);
  await identidade.iniciarRotacao(identityBd, KID).catch(() => {});
  return id;
}

/** Os eventos `contact.merged` de um tenant no outbox, pela ordem de emissão. */
async function fusoesNoOutbox(
  tenant: string,
): Promise<readonly { readonly contact_id: string; readonly merged_into: string }[]> {
  const { rows } = await admin.query(
    "SELECT envelope -> 'payload' AS payload FROM platform.events_outbox " +
      "WHERE tenant_id = $1 AND tipo = 'contact.merged' ORDER BY agregado_seq, event_id",
    [tenant],
  );
  return rows.map((linha) => (linha as { payload: never }).payload);
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

      // **E o evento está no outbox, uma vez, com os nomes do contrato
      // publicado.** O KAM-008 devolve `{contact_id: o que fica,
      // merged_contact_id: o absorvido}` e o contrato exige
      // `{contact_id: o absorvido, merged_into: o que fica}`: trocar os dois
      // publicava «B foi fundido em A» onde aconteceu o contrário, e nenhum
      // esquema o apanhava — os dois são UUID.
      const fusoes = await fusoesNoOutbox(tenant);
      assert.equal(fusoes.length, 1, "uma linha no outbox, e so uma");
      assert.deepEqual(fusoes[0], {
        contact_id: soBsuid.contactId,
        merged_into: soTelefone.contactId,
      });
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

  it("`payloadDaFusao` inverte os dois campos, e e isso que o contrato pede", () => {
    // Funcao pura, provada aqui ao lado do caso de base de dados: e o unico
    // sitio onde a inversao se ve, e um teste que a repetisse mais longe nao
    // dizia que o que vai para o outbox e o que o contrato exige.
    assert.deepEqual(
      payloadDaFusao({
        tenant_id: "11111111-1111-4111-8111-111111111111",
        payload: { contact_id: "o-que-fica", merged_contact_id: "o-absorvido" },
      }),
      { contact_id: "o-absorvido", merged_into: "o-que-fica" },
    );
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

describe("KAM-232 — o texto do WhatsApp na `agent_messages`, contra a base", () => {
  const PAN = "4111111111111111";

  function comTexto(evento: EventoDeEntrada, texto: string): EventoDeEntrada {
    return { ...evento, texto };
  }

  async function linhasDe(tenant: string): Promise<Record<string, unknown>[]> {
    const { rows } = await admin.query(
      `SELECT message_id::text AS message_id, contact_id::text AS contact_id,
              conversation_id::text AS conversation_id, canal, texto
         FROM platform.agent_messages WHERE tenant_id = $1`,
      [tenant],
    );
    return rows;
  }

  it("a reentrega 3x grava uma linha, como `kamba_app`, e a invocacao leva o identificador dela", async () => {
    const tenant = await tenantComChave("kam232-reentrega");
    try {
      const canal = await criarCanal(admin, tenant);
      const m = montar();
      const evento = comTexto(
        mensagem(canal.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }),
        `o meu cartao e ${PAN}`,
      );
      for (let n = 0; n < 3; n += 1) await m.chr.tratar(evento);

      const linhas = await linhasDe(tenant);
      assert.equal(linhas.length, 1);
      const [linha] = linhas;
      assert.equal(linha?.["canal"], "whatsapp");
      assert.equal(linha?.["texto"], `o meu cartao e ${PAN}`);
      assert.equal(m.entrega.aoAgr.length, 3);
      for (const invocacao of m.entrega.aoAgr) {
        assert.equal(invocacao.message_id, linha?.["message_id"]);
        assert.equal(invocacao.contact_id, linha?.["contact_id"]);
        assert.equal(invocacao.conversation_id, linha?.["conversation_id"]);
        assert.ok(!JSON.stringify(invocacao).includes(PAN), "a invocacao nao leva o texto");
      }
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("duas mensagens sao duas linhas; o mesmo `wamid` noutro tenant e outra linha, invisivel a este", async () => {
    const a = await tenantComChave("kam232-a");
    const b = await tenantComChave("kam232-b");
    try {
      const canalA = await criarCanal(admin, a);
      const canalB = await criarCanal(admin, b);
      const m = montar();
      const wamid = `wamid.${randomUUID()}`;
      await m.chr.tratar(comTexto(mensagem(canalA.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }, wamid), "de A"));
      await m.chr.tratar(comTexto(mensagem(canalA.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }), "de A outra"));
      await m.chr.tratar(comTexto(mensagem(canalB.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }, wamid), "de B"));

      assert.equal((await linhasDe(a)).length, 2);
      assert.equal((await linhasDe(b)).length, 1);
      const [deA, , deB] = m.entrega.aoAgr;
      assert.notEqual(deA?.message_id, deB?.message_id, "o tenant entra no identificador");

      // O `kamba_app` com o contexto de B nao le a linha de A pelo identificador.
      const visto = await comTenantReal(appBd, b, () =>
        appBd.query("SELECT texto FROM platform.agent_messages WHERE message_id = $1", [deA?.message_id]),
      );
      assert.equal(visto.rows.length, 0);
    } finally {
      await apagarTenant(admin, a);
      await apagarTenant(admin, b);
    }
  });

  it("o `kamba_app` continua sem `UPDATE` nem `DELETE` na linha que gravou", async () => {
    const tenant = await tenantComChave("kam232-imutavel");
    try {
      const canal = await criarCanal(admin, tenant);
      const m = montar();
      await m.chr.tratar(comTexto(mensagem(canal.phoneNumberId, { bsuid: bsuidDeEnsaio(), telefone: null }), "ola"));
      const id = m.entrega.aoAgr[0]?.message_id;
      for (const sql of [
        "UPDATE platform.agent_messages SET texto = 'outro' WHERE message_id = $1",
        "DELETE FROM platform.agent_messages WHERE message_id = $1",
      ]) {
        await assert.rejects(
          comTenantReal(appBd, tenant, () => appBd.query(sql, [id])),
          /permission denied/,
        );
      }
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

  it("`kamba_app` não consegue reescrever a identidade da conversa", async () => {
    // **Este teste mudou de objecto com o KAM-018, e a razão fica escrita.**
    //
    // Até à revisão `0016` ele afirmava que `kamba_app` **não** conseguia
    // alterar o `mode`, e era verdade: a `0009` concedia `UPDATE` em duas
    // colunas e deixava o `mode` de fora de propósito, porque «as transições são
    // KAM-018, e é esse ticket que pede o privilégio». O KAM-018 existe, pediu-o
    // e recebeu-o — a `0016` dá `UPDATE (mode, last_human_activity_at)` —, pelo
    // que a afirmação antiga passou a ser falsa. Reescrevê-la para continuar a
    // «passar» seria afirmar uma propriedade que a base já não tem.
    //
    // O que **continua** verdadeiro, e é a propriedade que este teste existe
    // para guardar, são as quatro colunas que nenhuma revisão concede: alterar
    // qualquer uma por esta via é reescrever a identidade da conversa, e quem a
    // reaponta numa fusão é o `kamba_identity`, dentro da transacção da fusão. O
    // privilégio novo é afirmado onde nasce, em `tests_bd/modos.bd.test.ts`.
    for (const coluna of ["contact_id", "channel_id", "tenant_id", "id"]) {
      await assert.rejects(
        () =>
          comTenantReal(appBd, randomUUID(), async () =>
            appBd.query(`UPDATE platform.conversations SET ${coluna} = gen_random_uuid()`),
          ),
        /permission denied/,
        coluna,
      );
    }
  });
});

describe("critério 8 — latência de `resolve`", () => {
  it("p95 de 40 resoluções: sem cache ≤ 50 ms, com cache ≤ 5 ms", async (t) => {
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
      // O número sai no TAP, para a secção de verificação do ticket o poder
      // citar. **`t.diagnostic` e não `console.log`**: o `log_policy` do KAM-068
      // recusa `console` em qualquer ficheiro TS deste repositório — e tem
      // razão —, e o `diagnostic` escreve um comentário TAP, que é o canal
      // próprio para isto.
      t.diagnostic(
        `[KAM-014] p95 resolve: sem cache ${medido.semCache.toFixed(3)} ms, ` +
          `com cache ${medido.comCache.toFixed(4)} ms`,
      );
      assert.ok(medido.semCache <= 50, `p95 sem cache: ${medido.semCache} ms`);
      assert.ok(medido.comCache <= 5, `p95 com cache: ${medido.comCache} ms`);
    } finally {
      await apagarTenant(admin, tenant);
    }
  });

  it("a invalidação por `channel_id` faz a resolução seguinte ver o estado novo", async (t) => {
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
      t.diagnostic(`[KAM-014] invalidacao + releitura: ${ms.toFixed(3)} ms`);
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

describe("KAM-092 — o tenant.activated esquece o tenant na cache do CHR", () => {
  /**
   * Um caso que chega a `aguarda_teste` **pelas portas da base**, como o
   * `activavel` do `db/tests/test_eventos_do_tenant.py`: as três condições do
   * agregador, a aprovação, a saga falsa, um canal e o provisionamento, o
   * catálogo e os seis gates. Devolve o caso, o tenant e o canal.
   */
  async function activavel(
    batch: pg.Client,
  ): Promise<{ caso: string; tenant: string; phoneNumberId: string }> {
    const { rows } = await admin.query(
      `INSERT INTO platform.onboarding_case
         (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
       VALUES ('kyc_pendente', 'convite', 'Loja de ensaio', 'alimentar', $1, $2, $1, $3)
       RETURNING id::text AS id, tenant_id::text AS tenant_id`,
      [randomBytes(40), randomBytes(32), randomBytes(32)],
    );
    const { id: caso, tenant_id: tenant } = rows[0] as { id: string; tenant_id: string };
    await admin.query("INSERT INTO platform.tenants (id, tipo, nome) VALUES ($1, 'pme', $2)", [
      tenant,
      `Loja de ensaio activacao ${tenant.slice(0, 8)}`,
    ]);
    await admin.query(
      `INSERT INTO platform.kyc_check (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras)
       VALUES ($1, $2, 'bi', $3, $4, 'k1_ok', '1.0.0')`,
      [caso, tenant, `t/${tenant}/kyc_documento/2026/11/${randomUUID()}`, randomBytes(32)],
    );
    await admin.query(
      `INSERT INTO platform.screening_decision (tenant_id, onboarding_id, sujeito_tipo, sujeito_ref, decisao,
         regras, versao_politica, origem, conteudo_sha256)
       VALUES ($1, $2, 'categoria', 'alimentar', 'permitida', ARRAY['alimentar'], '1.0.0+ensaio', 'regra', $3)`,
      [tenant, caso, randomBytes(32)],
    );
    await aceitarVigentes(admin, tenant);
    const canal = await criarCanal(admin, tenant);
    for (const evento of ["aprovar", "saga_iniciada", "saga_concluida", "es_concluido", "catalogo_minimo"]) {
      await avancar(batch, caso, tenant, evento);
    }
    for (const gate of ["meta_es", "meta_pagamento", "catalogo_minimo", "consentimento", "dpa", "e2e"]) {
      await batch.query(
        `INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok, evidencia_ref)
         VALUES ($1, $2, $3, true, 'ensaio')`,
        [caso, tenant, gate],
      );
    }
    return { caso, tenant, phoneNumberId: canal.phoneNumberId };
  }

  /** O `advance_case` como `kamba_batch`, sob o `app.tenant_id` do caso. */
  async function avancar(batch: pg.Client, caso: string, tenant: string, evento: string): Promise<void> {
    await comTenantReal(batch, tenant, () =>
      batch.query("SELECT platform.advance_case($1, $2, 'ensaio')", [caso, evento]),
    );
  }

  it("a activação pelas portas chega ao consumidor do CHR, e a primeira mensagem seguinte chega ao AGR", async () => {
    const batch = await ligar("batch");
    try {
      const { caso, tenant, phoneNumberId } = await activavel(batch);
      // Um tenant B já activo, com o seu canal em cache: a activação de A não lhe toca.
      const tenantB = await criarTenant(admin, "activacao-b");
      await activarTenant(admin, tenantB);
      const canalB = await criarCanal(admin, tenantB);

      await identidade.iniciarRotacao(identityBd, KID).catch(() => {});
      const m = montar();
      const resolvedor = m.resolvedor;
      const ao = () => m.entrega.aoAgr.filter((i) => JSON.stringify(i).includes(tenant)).length;
      const escrever = () =>
        m.chr.tratar(mensagem(phoneNumberId, { bsuid: bsuidDeEnsaio("ACTIVACAO"), telefone: telefoneDeEnsaio() }));
      // Em `onboarding` a mensagem não chega ao AGR (o regime `pendente`), e o
      // contexto fica em cache.
      await escrever();
      assert.equal(ao(), 0);
      const antes = await resolvedor.resolver(phoneNumberId);
      assert.equal(antes.daCache, true);
      assert.equal(antes.resolvido?.contexto.estado_tenant, "onboarding");
      assert.equal((await resolvedor.resolver(canalB.phoneNumberId)).daCache, false);

      await avancar(batch, caso, tenant, "activar");
      const { rows } = await admin.query(
        "SELECT envelope FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'tenant.activated'",
        [tenant],
      );
      assert.equal(rows.length, 1, "a porta emitiu uma activação");
      const envelope = (rows[0] as { envelope: Envelope }).envelope;

      // O controlo: a base já diz `ativo`, e a cache ainda diz `onboarding`. É
      // o atraso de até 60 s que o consumidor tira.
      const velha = await resolvedor.resolver(phoneNumberId);
      assert.equal(velha.daCache, true);
      assert.equal(velha.resolvido?.contexto.estado_tenant, "onboarding");
      await escrever();
      assert.equal(ao(), 0, "com a cache velha, a mensagem ainda não chega ao AGR");

      const efeito = efeitoDaActivacao(resolvedor);
      const opcoes = { bd: appBd, consumer: "chr", envelope, exigeOrdem: false };
      assert.equal((await consumir(opcoes, efeito)).desfecho, "aplicado");
      // A primeira mensagem depois do consumo chega ao AGR, sem esperar o TTL.
      await escrever();
      assert.equal(ao(), 1, "a primeira mensagem depois da activação chega ao AGR");
      const nova = await resolvedor.resolver(phoneNumberId);
      assert.equal(nova.resolvido?.contexto.estado_tenant, "ativo");
      assert.equal((await resolvedor.resolver(canalB.phoneNumberId)).daCache, true, "o tenant B ficou");

      // A reentrega é duplicada: a marca e o efeito partilham a transacção.
      assert.equal((await consumir(opcoes, efeito)).desfecho, "duplicado");
      assert.equal((await resolvedor.resolver(phoneNumberId)).daCache, true);

      // **Uma versão que o consumidor não conhece falha de forma visível**
      // (critério 4 do KAM-092): relança enquanto há tentativas, e na última
      // abre a DLQ — sem marcar consumido e sem tocar na cache.
      const v2: Envelope = { ...envelope, id: randomUUID(), versao: 2 };
      const opcoesV2 = { bd: appBd, consumer: "chr", envelope: v2, exigeOrdem: false };
      await assert.rejects(processar({ ...opcoesV2, tentativa: 1 }, efeito), { name: "VersaoDaActivacaoError" });
      const ultima = await processar({ ...opcoesV2, tentativa: 6 }, efeito);
      assert.equal(ultima.desfecho, "dlq");
      assert.match(ultima.erro ?? "", /^VersaoDaActivacaoError: /);
      const dlq = await admin.query(
        "SELECT tipo, versao, estado FROM platform.events_dlq WHERE consumer = 'chr' AND event_id = $1",
        [v2.id],
      );
      assert.deepEqual(dlq.rows, [{ tipo: "tenant.activated", versao: 2, estado: "aberta" }]);
      const marcados = await admin.query(
        "SELECT count(*)::int AS n FROM platform.events_consumed WHERE consumer = 'chr' AND event_id = $1",
        [v2.id],
      );
      assert.equal((marcados.rows[0] as { n: number }).n, 0);
      assert.equal((await resolvedor.resolver(phoneNumberId)).daCache, true);
    } finally {
      await batch.end();
    }
  });
});

describe("KAM-058 e KAM-098 — a suspensão e o encerramento esquecem o tenant na cache do CHR", () => {
  /**
   * A transição e o evento como o lote os escreve, numa transacção com o
   * contexto do tenant: as **cadeias** da régua (`SQL_REGUA_TRANSITAR` e
   * `SQL_REGUA_EMITIR`) e as do encerramento, e não cópias delas — o envelope
   * que chega ao consumidor é o que cada uma emite.
   */
  async function transitar(
    batch: pg.Client,
    tenant: string,
    sqls: { transitar: string; emitir: string },
    parametros: readonly unknown[],
    evento: { tipo: string; payload: object },
  ): Promise<Envelope> {
    transitados.push(tenant);
    await batch.query("BEGIN");
    try {
      await batch.query("SELECT set_config('app.tenant_id', $1, true)", [tenant]);
      const t = await batch.query(sqls.transitar, [tenant, ...parametros]);
      assert.equal(t.rows[0]?.mudou, true);
      await batch.query(sqls.emitir, [evento.tipo, 1, tenant, "tenant", tenant, JSON.stringify(evento.payload)]);
      await batch.query("COMMIT");
    } catch (erro) {
      await batch.query("ROLLBACK");
      throw erro;
    }
    const { rows } = await admin.query(
      "SELECT envelope FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = $2",
      [tenant, evento.tipo],
    );
    assert.equal(rows.length, 1);
    return (rows[0] as { envelope: Envelope }).envelope;
  }

  for (const caso of [
    {
      nome: "a suspensão pela régua (KAM-058, critério 2)",
      tipo: "tenant.suspended",
      sqls: { transitar: SQL_REGUA_TRANSITAR, emitir: SQL_REGUA_EMITIR },
      parametros: ["suspenso", MOTIVO_DA_SUSPENSAO, ACTOR_DA_REGUA],
      payload: { motivo: MOTIVO_NO_EVENTO },
      estado: "suspenso",
    },
    {
      nome: "o encerramento pelo off-boarding (KAM-098, critério 3)",
      tipo: "tenant.closed",
      sqls: { transitar: SQL_TRANSITAR_DO_ENCERRAMENTO, emitir: SQL_EMITIR_DO_ENCERRAMENTO },
      parametros: [MOTIVO_DO_ENCERRAMENTO.titular, ACTOR_DO_ENCERRAMENTO],
      payload: { motivo: MOTIVO_DO_ENCERRAMENTO.titular },
      estado: "encerrado",
    },
  ]) {
    it(`${caso.nome}: chega ao consumidor do CHR, e a mensagem seguinte já não chega ao AGR espião`, async () => {
      const batch = await ligar("batch");
      try {
        const tenant = await tenantComChave(`esquecer-${caso.estado}`);
        const { phoneNumberId } = await criarCanal(admin, tenant);
        const m = montar();
        const ao = () => m.entrega.aoAgr.filter((i) => JSON.stringify(i).includes(tenant)).length;
        const escrever = () =>
          m.chr.tratar(mensagem(phoneNumberId, { bsuid: bsuidDeEnsaio("ESQUECER"), telefone: telefoneDeEnsaio() }));
        await escrever();
        assert.equal(ao(), 1, "ativo: a mensagem chega ao AGR, e o contexto fica em cache");

        const envelope = await transitar(batch, tenant, caso.sqls, caso.parametros, {
          tipo: caso.tipo,
          payload: caso.payload,
        });
        assert.deepEqual(envelope.payload, caso.payload);

        // O controlo: a base já diz o estado novo, e a cache ainda diz `ativo`.
        // É a janela de até 60 s em que a cache falha **aberta**.
        const velha = await m.resolvedor.resolver(phoneNumberId);
        assert.equal(velha.daCache, true);
        assert.equal(velha.resolvido?.contexto.estado_tenant, "ativo");
        await escrever();
        assert.equal(ao(), 2, "com a cache velha, o AGR ainda recebe");

        const opcoes = { bd: appBd, consumer: "chr", envelope, exigeOrdem: false };
        assert.equal((await consumir(opcoes, efeitoDaActivacao(m.resolvedor))).desfecho, "aplicado");
        await escrever();
        assert.equal(ao(), 2, "depois do consumo, o CHR rejeita o tenant antes do AGR");
        const nova = await m.resolvedor.resolver(phoneNumberId);
        assert.equal(nova.resolvido?.contexto.estado_tenant, caso.estado);
      } finally {
        await batch.end();
      }
    });
  }
});

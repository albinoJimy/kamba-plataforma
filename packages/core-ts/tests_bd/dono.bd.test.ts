/**
 * O canal do dono contra o PostgreSQL: a troca de telefone com prova de posse
 * (KAM-211, KAM-217 e KAM-223) e a conversa do dono pelo painel (KAM-223).
 *
 * **Pelo caminho real e sem superutilizador**: o contacto resolve-se pelo
 * `resolveContact` do KAM-008, a troca persiste na `owner_phone_changes` e o
 * papel move-se pela `platform.definir_dono(…, 'troca_de_telefone')`, tudo como
 * `kamba_identity` e pelo `trocaPeloPool` que o `server.ts` do `onboarding-web`
 * chama. O `Otp` é o real do KAM-086, com o desafio **na troca**, e o SMS falso.
 * A conversa corre como `kamba_app`, pelo `conversaPeloPool`. O administrador só
 * cria o tenant, o canal e lê o resultado.
 *
 * O que só a base diz: que o papel **não** se move com o código do número novo,
 * que a troca e o código sobrevivem a um processo novo, que duas réplicas dão
 * uma troca, que a recusa do número antigo desfaz a transacção inteira, que o
 * tenant é o do contexto, e que a conversa de outro tenant não se lê nem se
 * escreve.
 *
 * Os números são fictícios, com 999, e escritos com espaços.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { SQL_PAPEL } from "../src/chr/consultas.ts";
import {
  ConversaDoDono,
  ESPERA_DA_TROCA_MS,
  contactoDoNumero,
  conversaPeloPool,
  definirDonoNaBase,
  numaLigacao,
  personaDe,
  trocaNaBase,
  trocaPeloPool,
  type DestinoDoAviso,
  type MomentoDoAviso,
  type PoolDeIdentidade,
} from "../src/dono/index.ts";
import type { Identidade } from "../src/identity/index.ts";
import {
  ContadoresEmMemoria,
  Otp,
  OtpPorSmsLocal,
  Telefone,
  type RepositorioDeOtp,
} from "../src/inscricao/index.ts";
import { FakeSmsProvider } from "../src/sms/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { ChavesDeTeste, conversasDe, criarCanal, criarTenant, ligar, poolDe } from "./apoio.ts";

/** Números fictícios, com 999. */
const NUMERO_ANTIGO = "+244 999 000 501";
const NUMERO_NOVO = "+244 999 000 502";
const NUMERO_DE_B = "+244 999 000 503";
const NUMERO_ALHEIO = "+244 999 000 504";
/** Um quarto numero, para as replicas: o `Otp` limita os envios por destino. */
const NUMERO_DA_REPLICA = "+244 999 000 505";

const PEPPER = Buffer.alloc(32, 0x5a);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);
const INICIO = new Date("2026-11-19T10:00:00.000Z");

let admin: pg.Client;
let identidadeBd: pg.Client;
let app: pg.Client;
let identidade: Identidade;
let pool: pg.Pool;
let poolDaApp: pg.Pool;

before(async () => {
  admin = await ligar("admin");
  identidadeBd = await ligar("identity");
  app = await ligar("app");
  identidade = await new ChavesDeTeste("k-chr").identidade();
  pool = poolDe("identity", 4);
  poolDaApp = poolDe("app", 4);
});

after(async () => {
  await Promise.all([admin?.end(), identidadeBd?.end(), app?.end(), pool?.end(), poolDaApp?.end()]);
});

/** O papel de cada contacto do tenant, lido pelo administrador. */
async function papeis(tenant: string): Promise<Map<string, { papel: string; mudou: boolean }>> {
  const { rows } = await admin.query<{ contact_id: string; papel: string; mudou: boolean }>(
    "SELECT contact_id::text, papel, papel_mudou_at IS NOT NULL AS mudou FROM platform.contacts WHERE tenant_id = $1",
    [tenant],
  );
  return new Map(rows.map((r) => [r.contact_id, { papel: r.papel, mudou: r.mudou }]));
}

/** A persona com que o CHR trata uma mensagem deste contacto (o `SQL_PAPEL`, como `kamba_app`). */
async function personaPeloChr(tenant: string, contacto: string): Promise<string> {
  return comTenant(app, tenant, async (bd) => {
    const r = (await bd.query(SQL_PAPEL, [tenant, contacto])) as { rows: { papel?: unknown }[] };
    return personaDe(r.rows[0]?.papel);
  });
}

async function donoDoTenant(tenant: string): Promise<string | null> {
  const { rows } = await admin.query<{ dono: string | null }>(
    "SELECT owner_contact_id::text AS dono FROM platform.tenants WHERE id = $1",
    [tenant],
  );
  return rows[0]?.dono ?? null;
}

/** As trocas de um tenant, pelo administrador: o estado e se há telefone em claro. */
async function trocasDe(tenant: string): Promise<{ estado: string; colunas: string }[]> {
  const { rows } = await admin.query<{ estado: string; colunas: string }>(
    "SELECT estado, row_to_json(t)::text AS colunas FROM platform.owner_phone_changes t WHERE tenant_id = $1 ORDER BY criado_at",
    [tenant],
  );
  return rows;
}

/** Um tenant com o dono do provisionamento, pela porta e como `kamba_identity`. */
async function tenantComDono(rotulo: string, numero: string): Promise<{ tenant: string; dono: string }> {
  const tenant = await criarTenant(admin, rotulo);
  const { contactId } = await contactoDoNumero(identidade, identidadeBd)({
    tenantId: tenant,
    telefone: new Telefone(numero, [PEPPER]),
  });
  await definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId, origem: "provisionamento" });
  return { tenant, dono: contactId };
}

/**
 * Uma réplica do processo: o `trocaPeloPool` com o seu `Otp` e os seus
 * contadores, sobre o mesmo *pool* e o mesmo SMS falso. Duas réplicas não
 * partilham memória nenhuma — só a base.
 */
function replica(sms: FakeSmsProvider, relogio: { agora: Date }) {
  const avisos: { tenantId: string; destino: DestinoDoAviso; momento: MomentoDoAviso }[] = [];
  const contadores = new ContadoresEmMemoria();
  const troca = trocaPeloPool({
    pool,
    identidade,
    relogio: () => relogio.agora,
    otp: (repositorio: RepositorioDeOtp) =>
      new Otp({
        repositorio,
        contadores,
        provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
        chave: PEPPER,
        relogio: () => relogio.agora,
      }),
    avisar: async (aviso) => {
      avisos.push(aviso);
    },
  });
  return { troca, avisos };
}

function montar() {
  const relogio = { agora: INICIO };
  const sms = new FakeSmsProvider({ relogio: () => relogio.agora });
  const codigo = (): string => {
    const achado = /([0-9]{6})/.exec(sms.enviados.at(-1)?.corpo ?? "")?.[1];
    assert.ok(achado, "o SMS do codigo nao saiu");
    return achado;
  };
  const { troca, avisos } = replica(sms, relogio);
  return { troca, avisos, codigo, relogio, sms, outra: () => replica(sms, relogio).troca };
}

const novo = (): Telefone => new Telefone(NUMERO_NOVO, [PEPPER]);
const antigo = (): Telefone => new Telefone(NUMERO_ANTIGO, [PEPPER]);

describe("KAM-223 — a troca com prova de posse, contra a base", () => {
  it("o codigo do numero novo poe a troca pendente e NAO move o papel; passadas as 72 h, move", async () => {
    const { tenant, dono } = await tenantComDono("pendente", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    const errado = m.codigo() === "000000" ? "111111" : "000000";
    assert.equal((await m.troca.verificar("troca:sessao-1", tenant, novo(), errado)).estado, "recusada");

    const desfecho = await m.troca.verificar("troca:sessao-1", tenant, novo(), m.codigo());
    assert.deepEqual(desfecho, { estado: "pendente", prazo: new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS) });
    const { contactId: contactoNovo } = await contactoDoNumero(identidade, identidadeBd)({ tenantId: tenant, telefone: novo() });
    // A troca de SIM simulada: o numero novo e `cliente` enquanto a espera corre.
    assert.equal((await papeis(tenant)).get(contactoNovo)?.papel, "cliente");
    assert.equal(await personaPeloChr(tenant, contactoNovo), "cliente");
    assert.equal(await personaPeloChr(tenant, dono), "dono");
    assert.deepEqual(m.avisos.map((a) => `${a.destino}:${a.momento}`), ["numero_antigo:pendente", "email:pendente"]);

    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS - 1);
    assert.deepEqual(await m.troca.concluir(tenant), { estado: "recusada", veredicto: "cedo" });
    assert.equal(await donoDoTenant(tenant), dono);
    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS);
    assert.deepEqual(await m.troca.concluir(tenant), { estado: "feita", contactId: contactoNovo, anterior: dono });
    const depois = await papeis(tenant);
    assert.deepEqual(depois.get(contactoNovo), { papel: "dono", mudou: true });
    assert.deepEqual(depois.get(dono), { papel: "cliente", mudou: true });
    assert.equal(await donoDoTenant(tenant), contactoNovo);
    // Sem telefone em claro na linha: nem o numero, nem os digitos dele.
    for (const { colunas } of await trocasDe(tenant)) {
      assert.ok(!colunas.includes("999 000") && !colunas.includes("999000"), colunas);
    }
  });

  it("com o codigo do numero antigo a troca e imediata", async () => {
    const { tenant, dono } = await tenantComDono("imediata", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    await m.troca.verificar("troca:sessao-1", tenant, novo(), m.codigo());
    assert.equal((await m.troca.pedir("troca:sessao-1", tenant, antigo(), "antigo")).enviado, true);
    const feita = await m.troca.verificar("troca:sessao-1", tenant, antigo(), m.codigo(), "antigo");
    assert.equal(feita.estado, "feita");
    assert.notEqual(await donoDoTenant(tenant), dono);
    assert.deepEqual((await trocasDe(tenant)).map((t) => t.estado), ["feita"]);
  });

  it("o codigo certo de um numero que nao e o do dono desfaz a transaccao: papel e troca como estavam", async () => {
    const { tenant, dono } = await tenantComDono("alheio", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    await m.troca.verificar("troca:sessao-1", tenant, novo(), m.codigo());
    const alheio = new Telefone(NUMERO_ALHEIO, [PEPPER]);
    await m.troca.pedir("troca:sessao-1", tenant, alheio, "antigo");
    assert.deepEqual(await m.troca.verificar("troca:sessao-1", tenant, alheio, m.codigo(), "antigo"), {
      estado: "recusada",
      veredicto: "antigo_diferente",
    });
    assert.equal(await donoDoTenant(tenant), dono);
    assert.equal((await papeis(tenant)).get(dono)?.papel, "dono");
    assert.deepEqual((await trocasDe(tenant)).map((t) => t.estado), ["pendente"]);
  });

  it("um processo novo a meio continua: o codigo do numero novo e a troca pendente estao na base", async () => {
    const { tenant, dono } = await tenantComDono("reinicio", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    // O processo reinicia entre o pedido e o codigo: outra replica, outra memoria.
    const depoisDoReinicio = m.outra();
    assert.equal((await depoisDoReinicio.verificar("troca:sessao-1", tenant, novo(), m.codigo())).estado, "pendente");
    // E outra vez entre a espera e a conclusao.
    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS);
    assert.equal((await m.outra().concluir(tenant)).estado, "feita");
    assert.notEqual(await donoDoTenant(tenant), dono);
  });

  it("o mesmo pedido em duas replicas: uma troca, uma recusa, e um dono so", async () => {
    const { tenant } = await tenantComDono("replicas", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    await m.troca.verificar("troca:sessao-1", tenant, novo(), m.codigo());
    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS);
    const desfechos = await Promise.all([m.troca.concluir(tenant), m.outra().concluir(tenant)]);
    assert.deepEqual(desfechos.map((d) => d.estado).sort(), ["feita", "recusada"]);
    assert.equal([...(await papeis(tenant)).values()].filter((p) => p.papel === "dono").length, 1);
    // E duas sessoes a abrir ao mesmo tempo noutro tenant: uma troca viva.
    const outro = await tenantComDono("replicas-abrir", NUMERO_DE_B);
    const pedidos = await Promise.all([
      m.troca.pedir("troca:sessao-x", outro.tenant, new Telefone(NUMERO_DA_REPLICA, [PEPPER])),
      m.outra().pedir("troca:sessao-y", outro.tenant, new Telefone(NUMERO_ALHEIO, [PEPPER])),
    ]);
    assert.deepEqual(pedidos.map((p) => p.enviado).sort(), [false, true]);
    assert.equal((await trocasDe(outro.tenant)).filter((t) => t.estado === "pedida").length, 1);
  });

  it("a sessao de A, com o tenant de B, nao verifica, nao conclui nem cancela a troca de B", async () => {
    const a = await tenantComDono("cruzado-a", NUMERO_ANTIGO);
    const b = await tenantComDono("cruzado-b", NUMERO_DE_B);
    const m = montar();
    await m.troca.pedir("troca:sessao-de-b", b.tenant, novo());
    const codigoDeB = m.codigo();
    assert.deepEqual(await m.troca.verificar("troca:sessao-de-b", a.tenant, novo(), codigoDeB), {
      estado: "recusada",
      veredicto: "sem_pedido",
    });
    await m.troca.verificar("troca:sessao-de-b", b.tenant, novo(), codigoDeB);
    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS);
    assert.equal((await m.troca.concluir(a.tenant)).estado, "recusada");
    assert.equal(await m.troca.cancelar(a.tenant), false);
    assert.deepEqual((await trocasDe(b.tenant)).map((t) => t.estado), ["pendente"]);
    assert.equal(await donoDoTenant(a.tenant), a.dono);
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("cancelar a troca pendente impede a conclusao depois do prazo", async () => {
    const { tenant, dono } = await tenantComDono("cancelada", NUMERO_ANTIGO);
    const m = montar();
    await m.troca.pedir("troca:sessao-1", tenant, novo());
    await m.troca.verificar("troca:sessao-1", tenant, novo(), m.codigo());
    assert.equal(await m.outra().cancelar(tenant), true);
    m.relogio.agora = new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS + 1);
    assert.equal((await m.troca.concluir(tenant)).estado, "recusada");
    assert.equal(await donoDoTenant(tenant), dono);
  });

  it("o kamba_app nao le nem escreve a troca", async () => {
    const { tenant } = await tenantComDono("app-troca", NUMERO_ANTIGO);
    await assert.rejects(
      comTenant(app, tenant, (bd) => bd.query("SELECT 1 FROM platform.owner_phone_changes")),
      (erro: { code?: string }) => erro.code === "42501",
    );
  });
});

describe("KAM-211/217 — a porta do dono, contra a base", () => {
  it("a porta com o contacto de A no contexto de B recusa: o tenant e o do contexto", async () => {
    const a = await tenantComDono("contexto-a", NUMERO_ANTIGO);
    const b = await tenantComDono("contexto-b", NUMERO_DE_B);
    await assert.rejects(
      trocaNaBase(identidadeBd)({ tenantId: b.tenant, contactId: a.dono }),
      (erro: { code?: string }) => erro.code === "23503",
    );
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("com o papel da aplicacao, a porta nao executa", async () => {
    const { tenant, dono } = await tenantComDono("app", NUMERO_ANTIGO);
    await assert.rejects(
      trocaNaBase(app)({ tenantId: tenant, contactId: dono }),
      (erro: { code?: string }) => erro.code === "42501",
    );
  });

  it("o provisionamento pela porta e idempotente e nao troca o dono", async () => {
    const { tenant, dono } = await tenantComDono("provisionamento", NUMERO_ANTIGO);
    for (let vez = 0; vez < 3; vez += 1) {
      await definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId: dono, origem: "provisionamento" });
    }
    const { contactId: outro } = await contactoDoNumero(identidade, identidadeBd)({ tenantId: tenant, telefone: novo() });
    await assert.rejects(
      definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId: outro, origem: "provisionamento" }),
      (erro: { code?: string }) => erro.code === "23505",
    );
    assert.equal([...(await papeis(tenant)).values()].filter((p) => p.papel === "dono").length, 1);
  });

  it("uma operacao que falha destroi a ligacao do pool, e uma que acerta devolve-a", async () => {
    const a = await tenantComDono("pool-falha-a", NUMERO_ANTIGO);
    const b = await tenantComDono("pool-falha-b", NUMERO_DE_B);
    const libertacoes: unknown[] = [];
    const espiao: PoolDeIdentidade = {
      async connect() {
        const ligacao = await pool.connect();
        const original = ligacao.release.bind(ligacao);
        ligacao.release = (destruir?: boolean | Error) => {
          libertacoes.push(destruir);
          original(destruir);
        };
        return ligacao;
      },
    };
    await assert.rejects(
      numaLigacao(espiao, (ligacao) => trocaNaBase(ligacao)({ tenantId: b.tenant, contactId: a.dono })),
      (erro: { code?: string }) => erro.code === "23503",
    );
    assert.deepEqual(await numaLigacao(espiao, async () => "ok"), "ok");
    assert.deepEqual(libertacoes, [true, false]);
  });
});

describe("KAM-223 — a conversa do dono pelo painel, contra a base", () => {
  /** Um tenant com dono e canal, e a conversa como o processo a monta. */
  async function comCanal(rotulo: string, numero: string) {
    const t = await tenantComDono(rotulo, numero);
    const canal = await criarCanal(admin, t.tenant);
    return { ...t, canal: canal.id };
  }

  function conversa(invocacoes: Record<string, unknown>[] = []) {
    return new ConversaDoDono({
      ...conversaPeloPool(poolDaApp),
      invocar: async (invocacao) => {
        invocacoes.push(invocacao as unknown as Record<string, unknown>);
        return { estado: 200, desfecho: "executado" };
      },
    });
  }

  it("a conversa e a do dono no canal, abre-se sem janela, e a mensagem grava-se com o identificador na invocacao", async () => {
    const t = await comCanal("conversa", NUMERO_ANTIGO);
    const invocacoes: Record<string, unknown>[] = [];
    const c = conversa(invocacoes);
    const r = await c.enviar(t.tenant, "quanto vendi hoje?");
    assert.equal(r.enviado, true);
    const [linha] = await conversasDe(admin, t.tenant);
    assert.equal(linha?.contact_id, t.dono);
    assert.equal(linha?.channel_id, t.canal);
    assert.equal(linha?.last_inbound_at, null);
    assert.equal(linha?.window_expires_at, null);
    assert.equal(invocacoes[0]?.["thread_id"], `${t.tenant}:${t.dono}`);
    assert.equal(invocacoes[0]?.["conversation_id"], linha?.id);
    const { rows } = await admin.query("SELECT canal, texto FROM platform.agent_messages WHERE message_id = $1", [
      invocacoes[0]?.["message_id"],
    ]);
    assert.deepEqual(rows, [{ canal: "painel", texto: "quanto vendi hoje?" }]);
    // Uma segunda mensagem e a mesma conversa.
    await c.enviar(t.tenant, "e ontem?");
    assert.equal((await conversasDe(admin, t.tenant)).length, 1);
  });

  it("a leitura mostra as mensagens do dono e so as respostas entregues; o cursor de B da nao_encontrado", async () => {
    const a = await comCanal("leitura-a", NUMERO_ANTIGO);
    const b = await comCanal("leitura-b", NUMERO_DE_B);
    const c = conversa();
    const deA = await c.enviar(a.tenant, "ola de A");
    const deB = await c.enviar(b.tenant, "ola de B");
    assert.ok(deA.enviado && deB.enviado);
    const [conversaDeA] = await conversasDe(admin, a.tenant);
    // Duas respostas do AGR na conversa de A: uma entregue pelo consumidor `painel`, outra nao.
    for (const [chave, entregue] of [["painel.x:0", true], ["painel.x:1", false]] as const) {
      await admin.query(
        // O `entregue_at` e o `now()` da base, como o do consumidor: um relogio
        // do processo de ensaio desfasado do da base mudava a ordem.
        "INSERT INTO platform.agent_replies (tenant_id, chave, contact_id, conversation_id, canal, texto, entregue_at) " +
          "VALUES ($1, $2, $3, $4, 'painel', $5, CASE WHEN $6 THEN now() END)",
        [a.tenant, chave, a.dono, conversaDeA?.id, `resposta ${chave}`, entregue],
      );
    }
    const lidas = await c.ler(a.tenant, null);
    assert.ok(Array.isArray(lidas));
    assert.deepEqual(
      (lidas as { autor: string; texto: string }[]).map((e) => `${e.autor}:${e.texto}`),
      ["dono:ola de A", "assistente:resposta painel.x:0"],
    );
    assert.equal(await c.ler(a.tenant, deB.enviado ? deB.messageId : ""), "nao_encontrado");
    // Com a margem do cursor, a leitura depois da mensagem de A repete-a e traz a
    // resposta entregue; o painel deduplica pelo `id`.
    assert.deepEqual(await c.ler(a.tenant, deA.enviado ? deA.messageId : ""), lidas);
  });

  it("sem dono, ou sem canal, nao ha conversa nem mensagem", async () => {
    const semDono = await criarTenant(admin, "sem-dono");
    await criarCanal(admin, semDono);
    assert.deepEqual(await conversa().enviar(semDono, "ola"), { enviado: false, motivo: "sem_dono" });
    const { tenant: semCanal } = await tenantComDono("sem-canal", NUMERO_ANTIGO);
    assert.deepEqual(await conversa().enviar(semCanal, "ola"), { enviado: false, motivo: "sem_canal" });
    const { rows } = await admin.query("SELECT count(*)::int AS n FROM platform.agent_messages WHERE tenant_id = ANY($1)", [
      [semDono, semCanal],
    ]);
    assert.equal(rows[0].n, 0);
  });

  it("uma mensagem na conversa de B com o tenant de A no contexto recusa", async () => {
    const a = await comCanal("fk-a", NUMERO_ANTIGO);
    const b = await comCanal("fk-b", NUMERO_DE_B);
    await conversa().enviar(b.tenant, "abre a conversa de B");
    const [conversaDeB] = await conversasDe(admin, b.tenant);
    await assert.rejects(
      conversaPeloPool(poolDaApp).gravar({
        tenantId: a.tenant,
        contactId: b.dono,
        conversationId: conversaDeB?.id ?? "",
        texto: "x",
      }),
      (erro: { code?: string }) => erro.code === "23503",
    );
  });

  it("o kamba_identity nao le a fonte persistida", async () => {
    const t = await comCanal("identidade-mensagens", NUMERO_ANTIGO);
    await assert.rejects(
      comTenant(identidadeBd, t.tenant, (bd) => bd.query("SELECT 1 FROM platform.agent_messages")),
      (erro: { code?: string }) => erro.code === "42501",
    );
  });
});

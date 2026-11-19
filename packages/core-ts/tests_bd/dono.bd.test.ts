/**
 * A troca de telefone do dono contra o PostgreSQL (KAM-211, critério «Troca de
 * telefone»).
 *
 * **Pelo caminho real e sem superutilizador**: o contacto do número novo
 * resolve-se pelo `resolveContact` do KAM-008 e o papel move-se pela
 * `platform.definir_dono(…, 'troca_de_telefone')`, os dois como
 * `kamba_identity`, através dos adaptadores de `src/dono/sql.ts` — os que o
 * painel recebe. O `Otp` é o real do KAM-086 (repositório em memória, SMS
 * falso), e a `TrocaDeTelefone` a real do KAM-118. O administrador só cria o
 * tenant e lê o resultado.
 *
 * O que só a base diz: que o papel **não** se move até o código acertar, que o
 * número novo é `cliente` até lá (a troca de SIM simulada), que a porta
 * despromove o antigo na mesma transacção e marca os dois, que o `kamba_app` não
 * a executa, e que o tenant é o do contexto.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { SQL_PAPEL } from "../src/chr/consultas.ts";
import {
  canalDoDonoNaBase,
  canalDoDonoPeloPool,
  canalNoPainel,
  contactoDoNumero,
  definirDonoNaBase,
  numaLigacao,
  personaDe,
  TrocaDeTelefone,
  trocaNaBase,
  trocaPeloPool,
  type DestinoDoAviso,
  type PoolDeIdentidade,
} from "../src/dono/index.ts";
import type { Identidade } from "../src/identity/index.ts";
import { ContadoresEmMemoria, Otp, OtpEmMemoria, OtpPorSmsLocal, Telefone } from "../src/inscricao/index.ts";
import { FakeSmsProvider } from "../src/sms/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { ChavesDeTeste, criarTenant, ligar, poolDe } from "./apoio.ts";

/** Números fictícios, com 999. */
const NUMERO_ANTIGO = "+244 999 000 501";
const NUMERO_NOVO = "+244 999 000 502";
const NUMERO_DE_B = "+244 999 000 503";

const PEPPER = Buffer.alloc(32, 0x5a);
/**
 * O HMAC do número da loja (KAM-216): o do telefone do caso, que nestes ensaios
 * é o do dono do provisionamento. O KAM-093 obriga os dois a coincidir.
 */
const LOJA_ANTIGA = new Telefone(NUMERO_ANTIGO, [PEPPER]).hmac;
const LOJA_DE_B = new Telefone(NUMERO_DE_B, [PEPPER]).hmac;
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);

let admin: pg.Client;
let identidadeBd: pg.Client;
let app: pg.Client;
let identidade: Identidade;

before(async () => {
  admin = await ligar("admin");
  identidadeBd = await ligar("identity");
  app = await ligar("app");
  identidade = await new ChavesDeTeste("k-chr").identidade();
});

after(async () => {
  await Promise.all([admin?.end(), identidadeBd?.end(), app?.end()]);
});

/** O papel de cada contacto do tenant, lido pelo administrador. */
async function papeis(tenant: string): Promise<Map<string, { papel: string; mudou: boolean }>> {
  const { rows } = await admin.query<{ contact_id: string; papel: string; mudou: boolean }>(
    "SELECT contact_id::text, papel, papel_mudou_at IS NOT NULL AS mudou FROM platform.contacts WHERE tenant_id = $1",
    [tenant],
  );
  return new Map(rows.map((r) => [r.contact_id, { papel: r.papel, mudou: r.mudou }]));
}

/**
 * A persona com que o CHR trata uma mensagem deste contacto: a leitura do
 * `SQL_PAPEL` do CHR, como `kamba_app` no contexto do tenant, e o `personaDe`.
 * É o caminho que decide a persona de uma mensagem, e não uma leitura do
 * administrador.
 */
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

function montarTroca() {
  const sms = new FakeSmsProvider({});
  const otp = new Otp({
    repositorio: new OtpEmMemoria(),
    contadores: new ContadoresEmMemoria(),
    provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: PEPPER,
  });
  const avisos: { tenantId: string; destino: DestinoDoAviso }[] = [];
  const troca = new TrocaDeTelefone({
    otp,
    contacto: contactoDoNumero(identidade, identidadeBd),
    trocar: trocaNaBase(identidadeBd),
    avisar: async (pedido) => {
      avisos.push(pedido);
    },
  });
  const codigo = (): string => {
    const achado = /([0-9]{6})/.exec(sms.enviados.at(-1)?.corpo ?? "")?.[1];
    assert.ok(achado, "o SMS do codigo nao saiu");
    return achado;
  };
  return { troca, codigo, avisos };
}

describe("KAM-211 — a troca de telefone pelo caminho real", () => {
  it("até o código acertar o número novo é cliente e o antigo é dono; depois, o contrário", async () => {
    const { tenant, dono } = await tenantComDono("troca", NUMERO_ANTIGO);
    const { troca, codigo, avisos } = montarTroca();
    const pedido = "troca:sessao-de-ensaio-1";

    await troca.pedir(pedido, tenant, new Telefone(NUMERO_NOVO, [PEPPER]), LOJA_ANTIGA);
    // A troca de SIM simulada: uma mensagem do número novo antes do código
    // resolve o contacto como qualquer desconhecido — `cliente`.
    const { contactId: novo } = await contactoDoNumero(identidade, identidadeBd)({
      tenantId: tenant,
      telefone: new Telefone(NUMERO_NOVO, [PEPPER]),
    });
    let antes = await papeis(tenant);
    assert.deepEqual(antes.get(novo), { papel: "cliente", mudou: false });
    assert.deepEqual(antes.get(dono), { papel: "dono", mudou: false });
    // E pelo caminho do CHR: a mensagem do número novo é de um `cliente`.
    assert.equal(await personaPeloChr(tenant, novo), "cliente");
    assert.equal(await personaPeloChr(tenant, dono), "dono");

    const errado = codigo() === "000000" ? "111111" : "000000";
    assert.equal((await troca.verificar(pedido, tenant, errado)).trocado, false);
    antes = await papeis(tenant);
    assert.equal(antes.get(novo)?.papel, "cliente");
    assert.equal(antes.get(dono)?.papel, "dono");

    const desfecho = await troca.verificar(pedido, tenant, codigo());
    assert.deepEqual(desfecho, { trocado: true, contactId: novo, anterior: dono });
    const depois = await papeis(tenant);
    assert.deepEqual(depois.get(novo), { papel: "dono", mudou: true });
    assert.deepEqual(depois.get(dono), { papel: "cliente", mudou: true });
    assert.equal(await donoDoTenant(tenant), novo);
    assert.equal(await personaPeloChr(tenant, novo), "dono");
    assert.equal(await personaPeloChr(tenant, dono), "cliente");
    assert.deepEqual(
      avisos.map((a) => [a.tenantId, a.destino]),
      [
        [tenant, "numero_antigo"],
        [tenant, "email"],
      ],
    );
  });

  it("o pedido de um tenant não se verifica de outro, e o papel não se move", async () => {
    const a = await tenantComDono("troca-a", NUMERO_ANTIGO);
    const b = await tenantComDono("troca-b", NUMERO_DE_B);
    const { troca, codigo } = montarTroca();
    await troca.pedir("troca:sessao-de-a", a.tenant, new Telefone(NUMERO_NOVO, [PEPPER]), LOJA_ANTIGA);
    const desfecho = await troca.verificar("troca:sessao-de-a", b.tenant, codigo());
    assert.deepEqual(desfecho, { trocado: false, veredicto: "sem_pedido" });
    assert.equal(await donoDoTenant(a.tenant), a.dono);
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("a porta com o contacto de A no contexto de B recusa: o tenant é o do contexto", async () => {
    const a = await tenantComDono("contexto-a", NUMERO_ANTIGO);
    const b = await tenantComDono("contexto-b", NUMERO_DE_B);
    await assert.rejects(
      trocaNaBase(identidadeBd)({ tenantId: b.tenant, contactId: a.dono, ownerChannelWa: true }),
      (erro: { code?: string }) => erro.code === "23503",
    );
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("com o papel da aplicação, a porta não executa", async () => {
    const { tenant, dono } = await tenantComDono("app", NUMERO_ANTIGO);
    await assert.rejects(
      trocaNaBase(app)({ tenantId: tenant, contactId: dono, ownerChannelWa: true }),
      (erro: { code?: string }) => erro.code === "42501",
    );
  });

  it("o provisionamento pela porta é idempotente e não troca o dono", async () => {
    const { tenant, dono } = await tenantComDono("provisionamento", NUMERO_ANTIGO);
    for (let vez = 0; vez < 3; vez += 1) {
      await definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId: dono, origem: "provisionamento" });
    }
    const { contactId: outro } = await contactoDoNumero(identidade, identidadeBd)({
      tenantId: tenant,
      telefone: new Telefone(NUMERO_NOVO, [PEPPER]),
    });
    await assert.rejects(
      definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId: outro, origem: "provisionamento" }),
      (erro: { code?: string }) => erro.code === "23505",
    );
    const lidos = await papeis(tenant);
    assert.deepEqual(
      [...lidos.values()].filter((p) => p.papel === "dono").length,
      1,
    );
    assert.deepEqual(lidos.get(dono), { papel: "dono", mudou: false });
  });
});

/**
 * A troca **montada como o processo a monta** (KAM-217): o `trocaPeloPool` que o
 * `server.ts` do `onboarding-web` chama, sobre um *pool* do `kamba_identity`.
 *
 * O que só isto prova: um servidor HTTP atende pedidos concorrentes, e a troca
 * é uma transacção com o tenant no `app.tenant_id`. Duas trocas de dois tenants
 * ao mesmo tempo têm de acabar cada uma no seu tenant. Com uma ligação
 * partilhada, o `tenant_guard` recusava a segunda (`LigacaoEmUsoError`), e o
 * dono que chegasse em segundo recebia um erro.
 */
describe("KAM-217 — a troca montada pelo processo, sobre o pool", () => {
  let pool: pg.Pool;

  before(() => {
    pool = poolDe("identity", 4);
  });

  after(async () => {
    await pool?.end();
  });

  function montarPeloPool() {
    const sms = new FakeSmsProvider({});
    const otp = new Otp({
      repositorio: new OtpEmMemoria(),
      contadores: new ContadoresEmMemoria(),
      provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
      chave: PEPPER,
    });
    const troca = trocaPeloPool({ pool, identidade, otp, avisar: async () => {} });
    const ultimoCodigo = (): string => {
      const achado = /([0-9]{6})/.exec(sms.enviados.at(-1)?.corpo ?? "")?.[1];
      assert.ok(achado, "o SMS do codigo nao saiu");
      return achado;
    };
    return { troca, ultimoCodigo };
  }

  it("cinco pares de trocas concorrentes em dois tenants acabam cada uma no seu tenant", async () => {
    // A preparação em série: o `tenantComDono` usa a ligação única do ensaio, e
    // o `tenant_guard` recusa duas transacções ao mesmo tempo nela.
    const pares: { a: { tenant: string; dono: string }; b: { tenant: string; dono: string } }[] = [];
    for (let i = 0; i < 5; i += 1) {
      pares.push({
        a: await tenantComDono(`pool-a-${i}`, NUMERO_ANTIGO),
        b: await tenantComDono(`pool-b-${i}`, NUMERO_DE_B),
      });
    }
    const { troca, ultimoCodigo } = montarPeloPool();
    // Os pedidos em série, para ler o código de cada um; as verificações — que
    // são o que vai à base — todas ao mesmo tempo. Um número novo por pedido: o
    // `Otp` limita os envios por destino.
    const verificacoes: { pedido: string; tenant: string; codigo: string }[] = [];
    for (const [i, par] of pares.entries()) {
      for (const [lado, tenant] of [["a", par.a.tenant], ["b", par.b.tenant]] as const) {
        const pedido = `troca:sessao-${lado}-${i}`;
        const numero = `+244 999 001 6${lado === "a" ? "0" : "5"}${i}`;
        const envio = await troca.pedir(pedido, tenant, new Telefone(numero, [PEPPER]), lado === "a" ? LOJA_ANTIGA : LOJA_DE_B);
        assert.equal(envio.enviado, true);
        verificacoes.push({ pedido, tenant, codigo: ultimoCodigo() });
      }
    }
    const desfechos = await Promise.all(verificacoes.map((v) => troca.verificar(v.pedido, v.tenant, v.codigo)));
    assert.deepEqual(
      desfechos.map((d) => d.trocado),
      verificacoes.map(() => true),
    );
    for (const par of pares) {
      for (const { tenant, dono } of [par.a, par.b]) {
        const lidos = await papeis(tenant);
        const novo = await donoDoTenant(tenant);
        assert.notEqual(novo, dono, "o dono do tenant nao mudou");
        assert.equal(lidos.get(novo ?? "")?.papel, "dono");
        assert.equal(lidos.get(dono)?.papel, "cliente");
        assert.equal([...lidos.values()].filter((p) => p.papel === "dono").length, 1);
      }
    }
  });

  it("uma porta que falha destrói a ligação, e uma que acerta devolve-a; a troca seguinte do pool passa", async () => {
    const a = await tenantComDono("pool-falha-a", NUMERO_ANTIGO);
    const b = await tenantComDono("pool-falha-b", NUMERO_DE_B);
    // Um espião sobre o pool real: regista o que cada ligação recebe no
    // `release`. O `ROLLBACK` do `comTenant` deixava a ligação limpa nos dois
    // casos, pelo que só o argumento do `release` mede a destruição (achado 6 da
    // revisão adversarial).
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
    // O contacto de A no contexto de B: `23503`, dentro de uma ligação do pool.
    await assert.rejects(
      numaLigacao(espiao, (ligacao) => trocaNaBase(ligacao)({ tenantId: b.tenant, contactId: a.dono, ownerChannelWa: true })),
      (erro: { code?: string }) => erro.code === "23503",
    );
    assert.deepEqual(await numaLigacao(espiao, async () => "ok"), "ok");
    assert.deepEqual(libertacoes, [true, false]);
    const { troca, ultimoCodigo } = montarPeloPool();
    await troca.pedir("troca:depois-da-falha", b.tenant, new Telefone(NUMERO_NOVO, [PEPPER]), LOJA_DE_B);
    const desfecho = await troca.verificar("troca:depois-da-falha", b.tenant, ultimoCodigo());
    assert.equal(desfecho.trocado, true);
    assert.equal(await donoDoTenant(a.tenant), a.dono);
    assert.notEqual(await donoDoTenant(b.tenant), b.dono);
  });

  it("o pedido da sessão de A, verificado com o tenant de B, não troca nada em nenhum", async () => {
    const a = await tenantComDono("pool-cruzado-a", NUMERO_ANTIGO);
    const b = await tenantComDono("pool-cruzado-b", NUMERO_DE_B);
    const { troca, ultimoCodigo } = montarPeloPool();
    await troca.pedir("troca:sessao-de-a", a.tenant, new Telefone(NUMERO_NOVO, [PEPPER]), LOJA_ANTIGA);
    const desfecho = await troca.verificar("troca:sessao-de-a", b.tenant, ultimoCodigo());
    assert.deepEqual(desfecho, { trocado: false, veredicto: "sem_pedido" });
    assert.equal(await donoDoTenant(a.tenant), a.dono);
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });
});

/**
 * O canal do dono guardado (KAM-216, decisão do fundador de 2026-11-19): a troca
 * escreve o `tenants.owner_channel_wa` pela `definir_dono`, na transacção que
 * move o papel, e o painel lê-o como `kamba_identity`. Os dois cenários do
 * critério 3 — telefone igual e diferente do número da loja — e o número ausente,
 * pelo caminho real.
 */
describe("KAM-216 — o canal do dono guardado, contra a base", () => {
  async function guardado(tenant: string): Promise<boolean | null> {
    const { rows } = await admin.query<{ v: boolean | null }>(
      "SELECT owner_channel_wa AS v FROM platform.tenants WHERE id = $1",
      [tenant],
    );
    return rows[0]?.v ?? null;
  }

  async function trocar(tenant: string, numero: string, loja: string | null): Promise<void> {
    const { troca, codigo } = montarTroca();
    const pedido = `troca:canal-${numero.replace(/\D/g, "")}`;
    await troca.pedir(pedido, tenant, new Telefone(numero, [PEPPER]), loja);
    assert.equal((await troca.verificar(pedido, tenant, codigo())).trocado, true);
  }

  it("número ausente: o provisionamento deixa a coluna nula, e o painel mostra o painel", async () => {
    const { tenant } = await tenantComDono("canal-nulo", NUMERO_ANTIGO);
    assert.equal(await guardado(tenant), null);
    const lido = await canalDoDonoNaBase(identidadeBd)(tenant);
    assert.equal(lido, null);
    assert.equal(canalNoPainel(lido, "ativo").canal, "painel");
  });

  it("telefone diferente do número da loja: a troca guarda o WhatsApp, e o painel lê-o", async () => {
    const { tenant } = await tenantComDono("canal-diferente", NUMERO_ANTIGO);
    await trocar(tenant, NUMERO_NOVO, LOJA_ANTIGA);
    assert.equal(await guardado(tenant), true);
    const lido = await canalDoDonoNaBase(identidadeBd)(tenant);
    assert.equal(lido, true);
    assert.equal(canalNoPainel(lido, "ativo").canal, "whatsapp");
  });

  it("telefone igual ao número da loja: o dono que volta ao número do registo tem o painel", async () => {
    const { tenant } = await tenantComDono("canal-igual", NUMERO_ANTIGO);
    await trocar(tenant, NUMERO_NOVO, LOJA_ANTIGA);
    await trocar(tenant, NUMERO_ANTIGO, LOJA_ANTIGA);
    assert.equal(await guardado(tenant), false);
    assert.equal(canalNoPainel(await canalDoDonoNaBase(identidadeBd)(tenant), "ativo").canal, "painel");
  });

  it("uma reentrega do provisionamento depois da troca não apaga o canal", async () => {
    const { tenant } = await tenantComDono("canal-reentrega", NUMERO_ANTIGO);
    await trocar(tenant, NUMERO_NOVO, LOJA_ANTIGA);
    const novo = await donoDoTenant(tenant);
    assert.ok(novo);
    // A reentrega com o dono de agora é idempotente; com o antigo, recusa.
    await definirDonoNaBase(identidadeBd)({ tenantId: tenant, contactId: novo, origem: "provisionamento" });
    assert.equal(await guardado(tenant), true);
  });

  it("isolamento: o canal de B não se lê do contexto de A, nem por id", async () => {
    const a = await tenantComDono("canal-iso-a", NUMERO_ANTIGO);
    const b = await tenantComDono("canal-iso-b", NUMERO_DE_B);
    await trocar(b.tenant, NUMERO_NOVO, LOJA_DE_B);
    assert.equal(await canalDoDonoNaBase(identidadeBd)(a.tenant), null);
    const cruzado = await comTenant(identidadeBd, a.tenant, async (bd) => {
      const r = (await bd.query("SELECT owner_channel_wa FROM platform.tenants WHERE id = $1::uuid", [b.tenant])) as {
        rows: unknown[];
      };
      return r.rows.length;
    });
    assert.equal(cruzado, 0);
    assert.equal(await canalDoDonoNaBase(identidadeBd)(b.tenant), true);
  });

  it("ninguém escreve a coluna por fora da porta: o kamba_identity e o kamba_app recebem 42501", async () => {
    const { tenant } = await tenantComDono("canal-escrita", NUMERO_ANTIGO);
    for (const cliente of [identidadeBd, app]) {
      await assert.rejects(
        comTenant(cliente, tenant, (bd) =>
          bd.query("UPDATE platform.tenants SET owner_channel_wa = true WHERE id = $1::uuid", [tenant]),
        ),
        (erro: { code?: string }) => erro.code === "42501",
      );
    }
    assert.equal(await guardado(tenant), null);
  });

  it("a leitura pelo pool, como o processo a monta, devolve a ligação", async () => {
    const pool = poolDe("identity", 2);
    try {
      const { tenant } = await tenantComDono("canal-pool", NUMERO_ANTIGO);
      await trocar(tenant, NUMERO_NOVO, LOJA_ANTIGA);
      const ler = canalDoDonoPeloPool(pool);
      const lidos = await Promise.all([ler(tenant), ler(tenant), ler(tenant)]);
      assert.deepEqual(lidos, [true, true, true]);
    } finally {
      await pool.end();
    }
  });
});

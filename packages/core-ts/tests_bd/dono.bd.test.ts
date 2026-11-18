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

import {
  contactoDoNumero,
  definirDonoNaBase,
  TrocaDeTelefone,
  trocaNaBase,
  type DestinoDoAviso,
} from "../src/dono/index.ts";
import type { Identidade } from "../src/identity/index.ts";
import { ContadoresEmMemoria, Otp, OtpEmMemoria, OtpPorSmsLocal, Telefone } from "../src/inscricao/index.ts";
import { FakeSmsProvider } from "../src/sms/index.ts";
import { ChavesDeTeste, criarTenant, ligar } from "./apoio.ts";

/** Números fictícios, com 999. */
const NUMERO_ANTIGO = "+244999000501";
const NUMERO_NOVO = "+244999000502";
const NUMERO_DE_B = "+244999000503";

const PEPPER = Buffer.alloc(32, 0x5a);
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

    await troca.pedir(pedido, tenant, new Telefone(NUMERO_NOVO, [PEPPER]));
    // A troca de SIM simulada: uma mensagem do número novo antes do código
    // resolve o contacto como qualquer desconhecido — `cliente`.
    const { contactId: novo } = await contactoDoNumero(identidade, identidadeBd)({
      tenantId: tenant,
      telefone: new Telefone(NUMERO_NOVO, [PEPPER]),
    });
    let antes = await papeis(tenant);
    assert.deepEqual(antes.get(novo), { papel: "cliente", mudou: false });
    assert.deepEqual(antes.get(dono), { papel: "dono", mudou: false });

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
    await troca.pedir("troca:sessao-de-a", a.tenant, new Telefone(NUMERO_NOVO, [PEPPER]));
    const desfecho = await troca.verificar("troca:sessao-de-a", b.tenant, codigo());
    assert.deepEqual(desfecho, { trocado: false, veredicto: "sem_pedido" });
    assert.equal(await donoDoTenant(a.tenant), a.dono);
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("a porta com o contacto de A no contexto de B recusa: o tenant é o do contexto", async () => {
    const a = await tenantComDono("contexto-a", NUMERO_ANTIGO);
    const b = await tenantComDono("contexto-b", NUMERO_DE_B);
    await assert.rejects(
      trocaNaBase(identidadeBd)({ tenantId: b.tenant, contactId: a.dono }),
      (erro: { code?: string }) => erro.code === "23503",
    );
    assert.equal(await donoDoTenant(b.tenant), b.dono);
  });

  it("com o papel da aplicação, a porta não executa", async () => {
    const { tenant, dono } = await tenantComDono("app", NUMERO_ANTIGO);
    await assert.rejects(
      trocaNaBase(app)({ tenantId: tenant, contactId: dono }),
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

/**
 * O dono nasce do provisionamento, contra o PostgreSQL (KAM-215).
 *
 * **Pelo caminho de produção, e sem superutilizador no que se mede**: o caso
 * escreve-se como `kamba_app` com o `phone_enc` do escritor (`colunasDoTelefone`),
 * o caso avança pelo varrimento do processo de lote (`varrerProvisionamentos`,
 * como `kamba_batch`, pela `platform.advance_case`), o evento consome-se pelo
 * `consumir` do KAM-006 numa ligação `kamba_app`, e o efeito é o
 * `provisionamentoPelaBase` que o processo `onboarding-provisionamento` monta —
 * o telefone pela ligação do consumo, o contacto e a porta pelo *pool* do
 * `kamba_identity`. O administrador só semeia o que é de outros tickets (o
 * tenant da saga, o KYC, o screening, o aceite, o canal, os passos da saga) e lê
 * o resultado.
 *
 * O que só a base diz: que o `tenant.provisioned` sai **uma** vez por caso,
 * mesmo com duas varreduras ao mesmo tempo; que três entregas dão **um** dono;
 * que o tenant do envelope é o da RLS, e um `onboarding_id` de outro tenant não
 * se encontra; e que um `phone_enc` ilegível, ou copiado de outro caso, vai à
 * DLQ sem criar dono.
 *
 * Os números são fictícios, com 999.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { SQL_PAPEL } from "../src/chr/consultas.ts";
import { CONSUMIDOR_DO_DONO, personaDe, provisionamentoPelaBase } from "../src/dono/index.ts";
import { consumir, type Envelope } from "../src/eventos/index.ts";
import { processar } from "../src/eventos/trabalho.ts";
import type { Identidade } from "../src/identity/index.ts";
import { Telefone, anelDoTelefone, colunasDoTelefone, type AnelDoTelefone } from "../src/inscricao/index.ts";
import { varrerProvisionamentos, PASSOS_ANTES_DO_ES } from "../src/provisioning/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { ChavesDeTeste, aceitarVigentes, criarCanal, ligar, poolDe } from "./apoio.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const ANEL: AnelDoTelefone = anelDoTelefone([`tel-ensaio:${Buffer.alloc(32, 0x33).toString("base64")}`, null]);

let admin: pg.Client;
let app: pg.Client;
let batch: pg.Client;
let poolDoLote: pg.Pool;
let poolDaIdentidade: pg.Pool;
let identidade: Identidade;

before(async () => {
  admin = await ligar("admin");
  app = await ligar("app");
  batch = await ligar("batch");
  poolDoLote = poolDe("batch", 4);
  poolDaIdentidade = poolDe("identity", 4);
  identidade = await new ChavesDeTeste("k-prov").identidade();
});

after(async () => {
  await Promise.all([admin?.end(), app?.end(), batch?.end(), poolDoLote?.end(), poolDaIdentidade?.end()]);
});

let numero = 700;
/** Um número fictício novo, com 999: o `resolveContact` é por telefone, e cada ensaio quer o seu. */
function numeroNovo(): string {
  numero += 1;
  return `+244 999 000 ${String(numero)}`;
}

/**
 * Um caso aprovado. O caso escreve-se como `kamba_app`, com o `phone_enc` do
 * escritor e o `id` e o `tenant_id` pré-alocados; o resto é semeado como o
 * `activavel` do `chr.bd.test.ts`, e a aprovação passa pela porta.
 */
async function casoAprovado(telefone = numeroNovo()): Promise<{ caso: string; tenant: string; telefone: string }> {
  const caso = randomUUID();
  const tenant = randomUUID();
  const colunas = colunasDoTelefone(ANEL, { tenantId: tenant, onboardingId: caso }, new Telefone(telefone, PEPPER));
  await comTenant(app, tenant, (tx) =>
    tx.query(
      `INSERT INTO platform.onboarding_case
         (id, tenant_id, fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
       VALUES ($1, $2, 'kyc_pendente', 'convite', 'Loja de ensaio', 'alimentar', $3, $4, $5, $6)`,
      [caso, tenant, randomBytes(40), randomBytes(32), colunas.phoneEnc, colunas.phoneHmac],
    ),
  );
  await admin.query("INSERT INTO platform.tenants (id, tipo, nome) VALUES ($1, 'pme', $2)", [
    tenant,
    `Loja de ensaio provisionamento ${tenant.slice(0, 8)}`,
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
  await comTenant(batch, tenant, (tx) => tx.query("SELECT platform.advance_case($1, 'aprovar', 'ensaio')", [caso]));
  return { caso, tenant, telefone };
}

/** Os cinco passos da saga antes do ES, concluídos, como a saga do KAM-091 os escreve. */
async function sagaFeita(caso: string, tenant: string, passos: readonly string[] = PASSOS_ANTES_DO_ES): Promise<void> {
  for (const passo of passos) {
    await admin.query(
      `INSERT INTO platform.provisioning_step (onboarding_id, tenant_id, step, status, attempt)
       VALUES ($1, $2, $3, 'concluido', 1)`,
      [caso, tenant, passo],
    );
  }
}

async function fase(caso: string): Promise<string> {
  const { rows } = await admin.query<{ fase: string }>("SELECT fase FROM platform.onboarding_case WHERE id = $1", [caso]);
  return rows[0]?.fase ?? "(sem caso)";
}

async function provisionados(tenant: string): Promise<Envelope[]> {
  const { rows } = await admin.query<{ envelope: Envelope }>(
    "SELECT envelope FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'tenant.provisioned' ORDER BY id",
    [tenant],
  );
  return rows.map((r) => r.envelope);
}

/** Uma volta do varrimento, como o ciclo do lote a corre. */
const varrer = () => varrerProvisionamentos({ lote: poolDoLote, limite: 100 });

/** O dono e os contactos do tenant, pelo administrador. */
async function donos(tenant: string): Promise<{ contactos: number; donos: string[]; owner: string | null }> {
  const contactos = await admin.query<{ contact_id: string; papel: string }>(
    "SELECT contact_id::text, papel FROM platform.contacts WHERE tenant_id = $1",
    [tenant],
  );
  const t = await admin.query<{ dono: string | null }>(
    "SELECT owner_contact_id::text AS dono FROM platform.tenants WHERE id = $1",
    [tenant],
  );
  return {
    contactos: contactos.rows.length,
    donos: contactos.rows.filter((r) => r.papel === "dono").map((r) => r.contact_id),
    owner: t.rows[0]?.dono ?? null,
  };
}

/** A persona com que o CHR trataria uma mensagem deste contacto (o `SQL_PAPEL`, como `kamba_app`). */
async function personaPeloChr(tenant: string, contacto: string): Promise<string> {
  return comTenant(app, tenant, async (bd) => {
    const r = (await bd.query(SQL_PAPEL, [tenant, contacto])) as { rows: { papel?: unknown }[] };
    return personaDe(r.rows[0]?.papel);
  });
}

/** O contacto de um telefone, resolvido como o CHR o resolve (`kamba_identity`). */
async function contactoDoTelefone(tenant: string, telefone: string): Promise<string> {
  const ligacao = await poolDaIdentidade.connect();
  try {
    return (await identidade.resolveContact(ligacao, { tenantId: tenant, telefone })).contactId;
  } finally {
    ligacao.release();
  }
}

const efeito = () => provisionamentoPelaBase({ anel: ANEL, identidade, pool: poolDaIdentidade });
const opcoes = (envelope: Envelope) => ({ bd: app, consumer: CONSUMIDOR_DO_DONO, envelope, exigeOrdem: false });

/** Um evento que não pode criar dono: vai à DLQ na última tentativa, e nada muda. */
async function vaiADlq(envelope: Envelope): Promise<void> {
  await assert.rejects(processar({ ...opcoes(envelope), tentativa: 1 }, efeito()), { name: "TelefoneDoCasoIndisponivelError" });
  const ultima = await processar({ ...opcoes(envelope), tentativa: 6 }, efeito());
  assert.equal(ultima.desfecho, "dlq");
  assert.match(ultima.erro ?? "", /^TelefoneDoCasoIndisponivelError: /);
  const dlq = await admin.query("SELECT tipo, estado FROM platform.events_dlq WHERE consumer = $1 AND event_id = $2", [
    CONSUMIDOR_DO_DONO,
    envelope.id,
  ]);
  assert.deepEqual(dlq.rows, [{ tipo: "tenant.provisioned", estado: "aberta" }]);
}

describe("KAM-215 — o dono nasce do provisionamento, contra a base", () => {
  it("saga → tenant.provisioned → contacto dono; a reentrega 3× deixa 1 dono", async () => {
    const { caso, tenant, telefone } = await casoAprovado();

    // Sem factos, nada avança: um caso aprovado sem saga fica aprovado.
    await varrer();
    assert.equal(await fase(caso), "aprovado");

    // A saga feita, sem canal: avança até ao ES e espera. Nenhum evento.
    await sagaFeita(caso, tenant);
    await varrer();
    assert.equal(await fase(caso), "aguarda_es");
    assert.equal((await provisionados(tenant)).length, 0);

    // **Sem o evento, o remetente é `cliente`**: o telefone do caso resolve-se
    // num contacto, e o CHR trata-o como cliente.
    const contacto = await contactoDoTelefone(tenant, telefone);
    assert.equal(await personaPeloChr(tenant, contacto), "cliente");

    // O canal ligado: o caso avança e o `tenant.provisioned` sai pelo outbox.
    const canal = await criarCanal(admin, tenant);
    await varrer();
    assert.equal(await fase(caso), "aguarda_catalogo");
    const [envelope, ...mais] = await provisionados(tenant);
    assert.ok(envelope !== undefined);
    assert.equal(mais.length, 0, "um tenant.provisioned por caso");
    assert.equal(envelope.payload["onboarding_id"], caso);
    assert.equal(envelope.payload["channel_id"], canal.id);
    assert.ok(!JSON.stringify(envelope).includes(telefone.replaceAll(" ", "").slice(4)), "o telefone não vai no evento");

    // A volta seguinte não emite outro.
    await varrer();
    assert.equal((await provisionados(tenant)).length, 1);

    // O consumo: o contacto do telefone do caso passa a dono, pela porta.
    assert.equal((await consumir(opcoes(envelope), efeito())).desfecho, "aplicado");
    const depois = await donos(tenant);
    assert.deepEqual(depois.donos, [contacto], "o dono é o contacto do telefone verificado do caso");
    assert.equal(depois.owner, contacto);
    assert.equal(depois.contactos, 1);
    assert.equal(await personaPeloChr(tenant, contacto), "dono");

    // A reentrega do mesmo evento é duplicada; três entregas com ids novos
    // (o evento republicado depois de uma marca perdida) também deixam 1 dono.
    assert.equal((await consumir(opcoes(envelope), efeito())).desfecho, "duplicado");
    for (let i = 0; i < 3; i += 1) {
      assert.equal((await consumir(opcoes({ ...envelope, id: randomUUID() }), efeito())).desfecho, "aplicado");
    }
    assert.deepEqual(await donos(tenant), depois, "três entregas: o mesmo dono, o mesmo contacto");
  });

  it("duas varreduras ao mesmo tempo dão um tenant.provisioned, e o caso chega uma vez", async () => {
    const { caso, tenant } = await casoAprovado();
    await sagaFeita(caso, tenant);
    await criarCanal(admin, tenant);
    await Promise.all([varrer(), varrer(), varrer()]);
    assert.equal(await fase(caso), "aguarda_catalogo");
    assert.equal((await provisionados(tenant)).length, 1);
  });

  it("um passo da saga por concluir, ou dois canais vivos, não avançam o caso", async () => {
    const meio = await casoAprovado();
    await sagaFeita(meio.caso, meio.tenant, PASSOS_ANTES_DO_ES.slice(0, -1));
    await varrer();
    assert.equal(await fase(meio.caso), "provisionando", "falta o último passo antes do ES");

    const doisCanais = await casoAprovado();
    await sagaFeita(doisCanais.caso, doisCanais.tenant);
    await criarCanal(admin, doisCanais.tenant);
    await criarCanal(admin, doisCanais.tenant);
    await varrer();
    assert.equal(await fase(doisCanais.caso), "aguarda_es", "o predicado do canal é o da porta: um, e só um");
    assert.equal((await provisionados(doisCanais.tenant)).length, 0);
  });

  it("isolamento: o evento de A com o tenant de B não cria dono em B nem em A", async () => {
    const a = await casoAprovado();
    await sagaFeita(a.caso, a.tenant);
    await criarCanal(admin, a.tenant);
    const b = await casoAprovado();
    await varrer();
    const [envelopeDeA] = await provisionados(a.tenant);
    assert.ok(envelopeDeA !== undefined);

    // O envelope de A reescrito com o tenant de B: sob a RLS de B, o caso de A
    // não existe. Vai à DLQ, e nem B nem A ganham dono.
    await vaiADlq({ ...envelopeDeA, id: randomUUID(), tenant_id: b.tenant });
    assert.deepEqual((await donos(b.tenant)).donos, []);
    assert.deepEqual((await donos(a.tenant)).donos, []);

    // E o evento verdadeiro de A cria o dono de A, e só ele.
    assert.equal((await consumir(opcoes(envelopeDeA), efeito())).desfecho, "aplicado");
    assert.equal((await donos(a.tenant)).donos.length, 1);
    assert.deepEqual((await donos(b.tenant)).donos, []);
  });

  it("adversarial: um onboarding_id de outro tenant no payload vai à DLQ e não cria dono", async () => {
    const a = await casoAprovado();
    await sagaFeita(a.caso, a.tenant);
    await criarCanal(admin, a.tenant);
    const b = await casoAprovado();
    await varrer();
    const [envelopeDeA] = await provisionados(a.tenant);
    assert.ok(envelopeDeA !== undefined);
    const forjado: Envelope = {
      ...envelopeDeA,
      id: randomUUID(),
      payload: { ...envelopeDeA.payload, onboarding_id: b.caso },
    };
    await vaiADlq(forjado);
    assert.deepEqual((await donos(a.tenant)).donos, []);
    assert.deepEqual((await donos(b.tenant)).donos, []);
    assert.equal((await donos(a.tenant)).contactos, 0, "nem um contacto com o telefone de B no tenant de A");
  });

  it("adversarial: um phone_enc ilegível vai à DLQ e não cria dono", async () => {
    const { caso, tenant } = await casoAprovado();
    await admin.query("UPDATE platform.onboarding_case SET phone_enc = $2 WHERE id = $1", [caso, randomBytes(48)]);
    await sagaFeita(caso, tenant);
    await criarCanal(admin, tenant);
    await varrer();
    const [envelope] = await provisionados(tenant);
    assert.ok(envelope !== undefined);
    await vaiADlq(envelope);
    assert.deepEqual(await donos(tenant), { contactos: 0, donos: [], owner: null });
  });

  it("adversarial: um phone_enc copiado de outro caso não decifra, e vai à DLQ", async () => {
    const origem = await casoAprovado();
    const alvo = await casoAprovado();
    // A cópia é do administrador: o `kamba_app` não tem `UPDATE` na coluna.
    await admin.query(
      "UPDATE platform.onboarding_case SET phone_enc = (SELECT phone_enc FROM platform.onboarding_case WHERE id = $1) WHERE id = $2",
      [origem.caso, alvo.caso],
    );
    await sagaFeita(alvo.caso, alvo.tenant);
    await criarCanal(admin, alvo.tenant);
    await varrer();
    const [envelope] = await provisionados(alvo.tenant);
    assert.ok(envelope !== undefined);
    await vaiADlq(envelope);
    assert.deepEqual(await donos(alvo.tenant), { contactos: 0, donos: [], owner: null });
  });

  it("o kamba_app não reescreve o phone_enc de um caso", async () => {
    const { caso, tenant } = await casoAprovado();
    await assert.rejects(
      comTenant(app, tenant, (tx) => tx.query("UPDATE platform.onboarding_case SET phone_enc = $2 WHERE id = $1", [caso, randomBytes(48)])),
      { code: "42501" },
    );
  });
});

/**
 * O guia do ES na base e pelo lote (KAM-239), sobre a revisão do guia na base.
 *
 * ```text
 * reinicio    o estado do guia escrito por um processo lê-se igual noutro, sobre
 *             outro pool: o pré-voo, o popup aberto, o número ligado
 * isolamento  o kamba_app de outro tenant não lê o guia pela tabela; a busca pelo
 *             número só devolve o caso e o tenant
 * lote        a reserva da lista, o meta_pagamento, o meta_es e o es_falhado
 *             chegam à base pela rota interna do processo de lote **real**
 *             (`arrancar`), como kamba_batch
 * abandono    a volta dos 30 minutos corre no lote, em todos os tenants, e o
 *             adaptador da aplicação recusa-a pelo nome
 * em baixo    (KAM-254) uma transição feita com o lote em baixo perde o gate e
 *             a fila no instante, e a volta seguinte do lote reconcilia-os a
 *             partir do estado do guia; uma transição concorrente espera pela
 *             tranca e escreve por último
 * sem via     (KAM-254) com o aviso sem via do lote real, um convite que vence
 *             duas vezes não abandona o caso nem gasta tentativa
 * ```
 *
 * Os casos semeiam-se pelo administrador, com o telefone em octetos aleatórios: o
 * guia não decifra o telefone, e o pré-voo lê só a linha (o `telefoneDe` dos
 * ensaios diz `movel`). Nenhum número de telefone entra neste ficheiro.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL } from "./apoio.ts";
import {
  PassoGuiado,
  AvisosEmMemoria,
  SQL_RECONCILIAR_META_ES,
  VarreduraNoLoteError,
  guiaNaBase,
  type Atestados,
} from "../src/guia/index.ts";
import { casosNaBase, type CifraDoCaso, type PoolDaInscricao } from "../src/inscricao/index.ts";
import type { RepositorioDeCasos } from "../src/inscricao/contrato.ts";
import type { ConjuntoSql } from "../src/revisao/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { ClienteDoLote, LoteIndisponivelError, portasDoGuia } from "../../../services/onboarding-web/src/guia_pelo_lote.ts";
import { CicloDoGuia } from "../../../services/onboarding-web/src/lote/interno.ts";
import { arrancar } from "../../../services/onboarding-web/src/lote/processo.ts";

/** Obviamente falsa e de baixa entropia: a do X-01, com outro nome. */
const CREDENCIAL = "ensaio-kam-239-credencial-do-lote";
const ORIGEM = "https://onboarding.exemplo.test";

const ATESTADOS: Atestados = {
  versaoDaApp: "2.24.17",
  appAbertaRecentemente: true,
  numeroEmWhatsAppPessoal: false,
  cartaoInternacional: true,
  donoPresente: true,
};

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

function configuracao(papel: "app" | "batch" | "admin"): pg.ClientConfig {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  const utilizador = { app: "kamba_app", batch: "kamba_batch", admin: exigir("POSTGRES_USER") }[papel];
  const senha = {
    app: "KAMBA_SECRET_DB_APP_PASSWORD",
    batch: "KAMBA_SECRET_DB_BATCH_PASSWORD",
    admin: "POSTGRES_PASSWORD",
  }[papel];
  return {
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: utilizador,
    password: exigir(senha),
    application_name: `kamba-guia-teste:${papel}`,
  };
}

let admin: pg.Client;
const pools: pg.Pool[] = [];
const casosCriados: string[] = [];
/** A capacidade da lista antes deste ficheiro: repõe-se no fim, para os que correm depois. */
let capacidadeAntes: number | null = null;

function novoPool(papel: "app" | "batch"): pg.Pool {
  const pool = new pg.Pool({ ...configuracao(papel), max: 6 });
  pools.push(pool);
  return pool;
}

/** Um caso em `aguarda_es`, semeado pelo administrador. */
async function caso(): Promise<{ readonly id: string; readonly tenant: string }> {
  const r = await admin.query<{ id: string; tenant_id: string }>(
    `INSERT INTO platform.onboarding_case
       (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
     VALUES ('aguarda_es', 'convite', 'Loja de ensaio', 'mercearia', $1, $2, $1, $3)
     RETURNING id::text AS id, tenant_id::text AS tenant_id`,
    [randomBytes(40), randomBytes(32), randomBytes(32)],
  );
  const l = r.rows[0]!;
  casosCriados.push(l.id);
  return { id: l.id, tenant: l.tenant_id };
}

/** Um `phone_number_id` de ensaio: algarismos, como os da Meta, sem forma de telefone. */
function numeroDaMeta(): string {
  return `10${String(Math.floor(Math.random() * 1e12)).padStart(12, "0")}`;
}

/** A cifra não é deste ensaio: o guia não a usa, e o `telefoneDe` é o dos ensaios. */
const SEM_CIFRA = {} as unknown as CifraDoCaso;

/** Os casos sobre a base, com a linha do telefone fixa em `movel`. */
function casosDoEnsaio(pool: pg.Pool): RepositorioDeCasos {
  const base = casosNaBase({ pool: pool as unknown as PoolDaInscricao, cifra: SEM_CIFRA, anelDoPepper: [randomBytes(32), null] });
  return { ...base, telefoneDe: async () => ({ linha: "movel" }) as never };
}

before(async () => {
  admin = new pg.Client(configuracao("admin"));
  await admin.connect();
  const r = await admin.query<{ n: number }>("SELECT es_max_por_7d AS n FROM platform.onboarding_capacity");
  capacidadeAntes = r.rows[0]?.n ?? null;
});

after(async () => {
  // O administrador é o dono das tabelas: o `kamba_app` não apaga o guia.
  if (casosCriados.length > 0) {
    await admin.query("DELETE FROM platform.onboarding_guia WHERE onboarding_id = ANY ($1::uuid[])", [casosCriados]);
    await admin.query("DELETE FROM platform.onboarding_gate WHERE onboarding_id = ANY ($1::uuid[])", [casosCriados]);
    await admin.query("DELETE FROM platform.waitlist_entry WHERE onboarding_id = ANY ($1::uuid[])", [casosCriados]);
    await admin.query("DELETE FROM platform.review_case WHERE onboarding_id = ANY ($1::uuid[])", [casosCriados]);
    await admin.query("DELETE FROM platform.onboarding_case WHERE id = ANY ($1::uuid[])", [casosCriados]);
  }
  // A capacidade que este ficheiro pôs a uma vaga volta ao que estava (achado 7 da revisão adversarial).
  if (capacidadeAntes !== null) {
    await admin.query("UPDATE platform.onboarding_capacity SET es_max_por_7d = $1", [capacidadeAntes]);
  }
  for (const pool of pools) await pool.end().catch(() => undefined);
  await admin.end();
});

describe("o guia na base (KAM-239)", () => {
  it("KAM-239: o estado do guia escrito por um processo lê-se igual noutro processo, depois do reinício", async () => {
    const { id, tenant } = await caso();
    const numero = numeroDaMeta();
    const primeiro = novoPool("app");
    const guia = guiaNaBase({ pool: primeiro as unknown as PoolDaInscricao });
    assert.equal((await guia.abrir(id)).estado, "pre_voo");
    await guia.gravarPreflight(id, {
      itens: [
        { id: "app_versao", tipo: "atestado", ok: true, detalhe: "ok" },
        { id: "numero_movel", tipo: "auto", ok: false, detalhe: "fixo_rota_cloud_only" },
      ],
      podeAbrir: true,
      rota: "cloud_only",
      avaliadoEm: new Date("2026-11-22T10:00:00.000Z"),
    });
    const aberto = new Date("2026-11-22T10:01:00.000Z");
    assert.equal(await guia.transitar(id, "pre_voo", "iniciado", { iniciadoEm: aberto, motivo: null }), true);
    assert.equal(await guia.transitar(id, "pre_voo", "iniciado", {}), false, "compare-and-set");
    assert.equal(await guia.transitar(id, "iniciado", "es_concluido", { phoneNumberId: numero, wabaId: "waba-ensaio" }), true);
    await guia.marcar(id, "numeroConfirmado");

    // **O reinício**: o primeiro processo morre, e o segundo nasce sobre outro pool.
    await primeiro.end();
    pools.splice(pools.indexOf(primeiro), 1);
    const segundo = guiaNaBase({ pool: novoPool("app") as unknown as PoolDaInscricao });
    const lido = await segundo.ler(id);
    assert.ok(lido, "o guia sobrevive");
    assert.equal(lido.estado, "es_concluido");
    assert.equal(lido.iniciadoEm?.toISOString(), aberto.toISOString());
    assert.equal(lido.phoneNumberId, numero);
    assert.equal(lido.wabaId, "waba-ensaio");
    assert.equal(lido.numeroConfirmado, true);
    assert.equal(lido.sincronizado, false);
    assert.equal(lido.preflight?.rota, "cloud_only", "a rota deriva dos itens");
    assert.equal(lido.preflight?.podeAbrir, true);
    assert.equal(lido.preflight?.avaliadoEm.toISOString(), "2026-11-22T10:00:00.000Z");
    assert.equal(await segundo.porPhoneNumberId(numero), id, "os sinais da Meta encontram-no pelo número");

    // O pré-voo vive na coluna do caso, na forma do bloco.
    const coluna = await admin.query<{ preflight: unknown }>("SELECT preflight FROM platform.onboarding_case WHERE id = $1", [id]);
    assert.deepEqual(coluna.rows[0]?.preflight, [
      { id: "app_versao", tipo: "atestado", ok: true, detalhe: "ok" },
      { id: "numero_movel", tipo: "auto", ok: false, detalhe: "fixo_rota_cloud_only" },
    ]);

    // E o kamba_app de outro tenant não o lê pela tabela.
    const ligacao = await pools.at(-1)!.connect();
    try {
      const n = await comTenant(ligacao, randomUUID(), async (tx) =>
        (await tx.query("SELECT count(*)::int AS n FROM platform.onboarding_guia WHERE onboarding_id = $1", [id])) as {
          rows: { n: number }[];
        },
      );
      assert.equal(n.rows[0]?.n, 0);
      const meu = await comTenant(ligacao, tenant, async (tx) =>
        (await tx.query("SELECT count(*)::int AS n FROM platform.onboarding_guia WHERE onboarding_id = $1", [id])) as {
          rows: { n: number }[];
        },
      );
      assert.equal(meu.rows[0]?.n, 1);
    } finally {
      ligacao.release();
    }
  });

  it("KAM-239: a reserva, o meta_pagamento, o meta_es e o es_falhado chegam à base pela rota interna do lote", async () => {
    // A capacidade da lista a uma vaga, e a fila vazia: a forma do `limpar` do
    // `capacidade.bd.test.ts`, que corre antes deste.
    await admin.query("DELETE FROM platform.waitlist_entry");
    await admin.query("UPDATE platform.onboarding_capacity SET es_max_por_7d = 1");
    const lote = novoPool("batch");
    const app = novoPool("app");
    const { interna } = await arrancar({
      lote: lote as unknown as ConjuntoSql,
      app: app as unknown as ConjuntoSql,
      log: { warn: () => {} },
      inicioDaAmostragem: null,
      guia: { origem: ORIGEM, credencial: CREDENCIAL },
    });
    assert.ok(interna, "o lote serve a rota interna com o guia configurado");
    const cliente = new ClienteDoLote({
      base: "http://lote.invalid",
      credencial: async () => CREDENCIAL,
      buscar: (async (url: string | URL | Request, init?: RequestInit) =>
        interna.request(new URL(String(url)).pathname, init)) as typeof fetch,
    });
    const portas = portasDoGuia<never>({ ambiente: "prod", lote: cliente, emMemoria: () => assert.fail("nada em memória em prod") });
    const casos = casosDoEnsaio(app);
    const guia = new PassoGuiado({
      casos,
      repositorio: guiaNaBase({ pool: app as unknown as PoolDaInscricao }),
      capacidade: portas.lista,
      ligador: { ligar: async () => ({ desfecho: "criado", tentativaId: "tentativa-ensaio" }) },
      gates: portas.gates,
      revisao: portas.revisao,
      pagamento: { verificar: async () => "desconhecido" },
      aviso: new AvisosEmMemoria(),
      anelDoPepper: [randomBytes(32), null],
      chaveDaAssinatura: randomBytes(32),
      origem: ORIGEM,
      configId: "config-de-ensaio",
    });
    const primeiro = await caso();
    const segundo = await caso();
    await guia.preflight(primeiro.id, ATESTADOS);
    await guia.preflight(segundo.id, ATESTADOS);

    assert.equal((await guia.iniciar(primeiro.id)).desfecho, "popup", "a vaga, dada pelo lote");
    assert.equal((await guia.iniciar(segundo.id)).desfecho, "lista_espera", "a segunda vai para a lista");
    const entradas = await admin.query<{ onboarding_id: string; estado: string }>(
      "SELECT onboarding_id::text AS onboarding_id, estado FROM platform.waitlist_entry WHERE onboarding_id = ANY ($1::uuid[]) ORDER BY estado",
      [[primeiro.id, segundo.id]],
    );
    // Pela ordem do `estado`: «aguardando» < «concluido».
    assert.deepEqual(entradas.rows, [
      { onboarding_id: segundo.id, estado: "aguardando" },
      { onboarding_id: primeiro.id, estado: "concluido" },
    ]);
    assert.equal((await portas.lista.posicao(segundo.id))?.estado, "aguardando");

    // O FINISH do popup e o meta_pagamento: o gate na base, pelo lote.
    const numero = numeroDaMeta();
    assert.equal((await guia.concluir(primeiro.id, { code: "code-ensaio", waba_id: "waba-ensaio", phone_number_id: numero })).estado, "subscrito");
    await guia.verificarPagamento(primeiro.id);
    // Um número que não é o do OTP: o meta_es vermelho e o es_falhado na fila.
    assert.equal(await guia.confirmarNumero(numero, "+0 000"), false);
    const gates = await admin.query<{ gate: string; ok: boolean; evidencia_ref: string }>(
      "SELECT gate, ok, evidencia_ref FROM platform.onboarding_gate WHERE onboarding_id = $1 ORDER BY gate",
      [primeiro.id],
    );
    assert.deepEqual(gates.rows, [
      { gate: "meta_es", ok: false, evidencia_ref: "numero_divergente" },
      { gate: "meta_pagamento", ok: false, evidencia_ref: "desconhecido" },
    ]);
    const revisao = await admin.query<{ tipo: string; n: number }>(
      "SELECT tipo, count(*)::int AS n FROM platform.review_case WHERE onboarding_id = $1 GROUP BY tipo",
      [primeiro.id],
    );
    assert.deepEqual(revisao.rows, [{ tipo: "es_falhado", n: 1 }]);
    assert.equal((await guiaNaBase({ pool: app as unknown as PoolDaInscricao }).ler(primeiro.id))?.estado, "falhado");
  });

  it("KAM-239: o abandono dos 30 minutos corre no lote em todos os tenants, e a aplicação recusa-o pelo nome", async () => {
    const app = guiaNaBase({ pool: novoPool("app") as unknown as PoolDaInscricao });
    const vencidos = [await caso(), await caso()];
    const recente = await caso();
    const agora = new Date();
    for (const c of vencidos) {
      await app.abrir(c.id);
      await app.transitar(c.id, "pre_voo", "iniciado", { iniciadoEm: new Date(agora.getTime() - 31 * 60_000) });
    }
    await app.abrir(recente.id);
    await app.transitar(recente.id, "pre_voo", "iniciado", { iniciadoEm: new Date(agora.getTime() - 5 * 60_000) });
    await assert.rejects(app.iniciadosAntesDe(agora), VarreduraNoLoteError);

    const parados: string[] = [];
    const ciclo = new CicloDoGuia({
      lote: novoPool("batch"),
      revisao: { abrir: async () => {} },
      lista: {
        expirarVencidos: async () => 0,
        promover: async () => 0,
        medir: async () => {
          parados.push("medir");
        },
      },
      relogio: () => agora,
    });
    const r = await ciclo.correr();
    assert.deepEqual(r.falhou, []);
    assert.ok(r.abandonados >= 2, "os dois vencidos, de dois tenants");
    for (const c of vencidos) assert.equal((await app.ler(c.id))?.estado, "abandonado");
    assert.equal((await app.ler(recente.id))?.estado, "iniciado", "o de cinco minutos fica");
    assert.deepEqual(parados, ["medir"]);
  });

  it("KAM-254: uma transição feita com o lote em baixo chega ao onboarding_gate e ao review_case quando o lote volta", async () => {
    const lote = novoPool("batch");
    const app = novoPool("app");
    const { processo, interna } = await arrancar({
      lote: lote as unknown as ConjuntoSql,
      app: app as unknown as ConjuntoSql,
      log: { warn: () => {} },
      inicioDaAmostragem: null,
      guia: { origem: ORIGEM, credencial: CREDENCIAL },
    });
    assert.ok(interna && processo.guia, "o lote serve a rota interna com o guia configurado");
    const voltaDoLote = processo.guia.ciclo;
    // **O lote em baixo** é o `fetch` a falhar como falha com a porta fechada.
    let emBaixo = false;
    const cliente = new ClienteDoLote({
      base: "http://lote.invalid",
      credencial: async () => CREDENCIAL,
      buscar: (async (url: string | URL | Request, init?: RequestInit) => {
        if (emBaixo) throw new TypeError("fetch failed");
        return interna.request(new URL(String(url)).pathname, init);
      }) as typeof fetch,
    });
    const portas = portasDoGuia<never>({ ambiente: "prod", lote: cliente, emMemoria: () => assert.fail("nada em memória em prod") });
    const repositorio = guiaNaBase({ pool: app as unknown as PoolDaInscricao });
    const guia = new PassoGuiado({
      casos: casosDoEnsaio(app),
      repositorio,
      capacidade: portas.lista,
      ligador: { ligar: async () => assert.fail("o ensaio não liga") },
      gates: portas.gates,
      revisao: portas.revisao,
      pagamento: { verificar: async () => "desconhecido" },
      aviso: new AvisosEmMemoria(),
      anelDoPepper: [randomBytes(32), null],
      chaveDaAssinatura: randomBytes(32),
      origem: ORIGEM,
      configId: "config-de-ensaio",
    });
    /** Um guia em `subscrito` com um número ligado, pela aplicação. */
    const subscrito = async (): Promise<{ readonly id: string; readonly numero: string }> => {
      const { id } = await caso();
      const numero = numeroDaMeta();
      await repositorio.abrir(id);
      assert.equal(await repositorio.transitar(id, "pre_voo", "iniciado", { iniciadoEm: new Date() }), true);
      assert.equal(await repositorio.transitar(id, "iniciado", "es_concluido", { phoneNumberId: numero, wabaId: "waba-ensaio" }), true);
      assert.equal(await repositorio.transitar(id, "es_concluido", "subscrito", {}), true);
      return { id, numero };
    };
    const gateDe = async (id: string): Promise<readonly { ok: boolean; evidencia_ref: string }[]> =>
      (
        await admin.query<{ ok: boolean; evidencia_ref: string }>(
          "SELECT ok, evidencia_ref FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'meta_es'",
          [id],
        )
      ).rows;
    const revisoesDe = async (id: string): Promise<number> =>
      (
        await admin.query<{ n: number }>(
          "SELECT count(*)::int AS n FROM platform.review_case WHERE onboarding_id = $1 AND tipo = 'es_falhado'",
          [id],
        )
      ).rows[0]?.n ?? -1;

    const divergente = await subscrito();
    const desligado = await subscrito();
    const verificado = await subscrito();
    emBaixo = true;
    // O número que não é o do OTP: o guia prende-se na base, e o gate e a fila perdem-se.
    await assert.rejects(guia.confirmarNumero(divergente.numero, "+0 000"), LoteIndisponivelError);
    // O canal desligado: o mesmo.
    await assert.rejects(guia.desligado(desligado.numero), LoteIndisponivelError);
    // O verificado sem o gate verde: a forma do `#talvezVerificar` com o lote em baixo.
    assert.equal(await repositorio.transitar(verificado.id, "subscrito", "verificado", {}), true);
    assert.equal((await repositorio.ler(divergente.id))?.estado, "falhado");
    assert.equal((await repositorio.ler(desligado.id))?.estado, "desligado");
    for (const c of [divergente, desligado, verificado]) assert.deepEqual(await gateDe(c.id), [], "nada chegou ao gate");
    assert.equal(await revisoesDe(divergente.id), 0, "nada chegou à fila");

    // **O lote volta**, e a volta seguinte reconcilia.
    emBaixo = false;
    const r = await voltaDoLote.correr();
    assert.deepEqual(r.falhou, []);
    assert.ok(r.gatesReconciliados >= 3, "os três gates");
    assert.ok(r.revisoesAbertas >= 1, "o es_falhado do preso");
    assert.deepEqual(await gateDe(divergente.id), [{ ok: false, evidencia_ref: "numero_divergente" }]);
    assert.deepEqual(await gateDe(desligado.id), [{ ok: false, evidencia_ref: "desligado" }]);
    assert.deepEqual(await gateDe(verificado.id), [{ ok: true, evidencia_ref: "sincronizado_e_verificado" }]);
    assert.equal(await revisoesDe(divergente.id), 1);

    // **Idempotente**: a volta seguinte não abre outro caso.
    const segunda = await voltaDoLote.correr();
    assert.deepEqual(segunda.falhou, []);
    assert.equal(await revisoesDe(divergente.id), 1);

    // **E o caso aberto pelo próprio guia conta**: um preso que a rota já levou à
    // fila não ganha segundo caso.
    const comFila = await subscrito();
    assert.equal(await guia.confirmarNumero(comFila.numero, "+0 000"), false);
    assert.equal(await revisoesDe(comFila.id), 1);
    await voltaDoLote.correr();
    assert.equal(await revisoesDe(comFila.id), 1);
  });

  it("KAM-254: a reconciliação tranca o guia, e uma transição concorrente escreve o gate por último", async () => {
    const repositorio = guiaNaBase({ pool: novoPool("app") as unknown as PoolDaInscricao });
    const { id } = await caso();
    await repositorio.abrir(id);
    await repositorio.transitar(id, "pre_voo", "iniciado", { iniciadoEm: new Date() });
    await repositorio.transitar(id, "iniciado", "es_concluido", { phoneNumberId: numeroDaMeta(), wabaId: "waba-ensaio" });
    await repositorio.transitar(id, "es_concluido", "subscrito", {});
    await repositorio.transitar(id, "subscrito", "verificado", {});

    // A transição do `onboarding-web` a meio: o guia passa a `desligado` numa
    // transacção que ainda não confirmou.
    const web = new pg.Client(configuracao("admin"));
    await web.connect();
    try {
      await web.query("BEGIN");
      await web.query("UPDATE platform.onboarding_guia SET estado = 'desligado' WHERE onboarding_id = $1", [id]);
      let acabou = false;
      const reconciliacao = novoPool("batch")
        .query(SQL_RECONCILIAR_META_ES, [1000])
        .then((r) => {
          acabou = true;
          return r;
        });
      await new Promise((feito) => setTimeout(feito, 300));
      assert.equal(acabou, false, "a reconciliação espera pela transição");
      await web.query("COMMIT");
      await reconciliacao;
    } finally {
      await web.end();
    }
    const gate = await admin.query<{ ok: boolean; evidencia_ref: string }>(
      "SELECT ok, evidencia_ref FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'meta_es'",
      [id],
    );
    // Sem a tranca, a leitura de antes escrevia verde por cima do `desligado`.
    assert.deepEqual(gate.rows, [{ ok: false, evidencia_ref: "desligado" }]);
  });

  it("KAM-254: sem via, um convite que vence duas vezes no lote real não abandona o caso nem gasta tentativa", async () => {
    await admin.query("DELETE FROM platform.waitlist_entry");
    await admin.query("UPDATE platform.onboarding_capacity SET es_max_por_7d = 1");
    const { processo } = await arrancar({
      lote: novoPool("batch") as unknown as ConjuntoSql,
      app: novoPool("app") as unknown as ConjuntoSql,
      log: { warn: () => {} },
      inicioDaAmostragem: null,
      guia: { origem: ORIGEM, credencial: CREDENCIAL },
    });
    assert.ok(processo.guia, "o lote monta a lista com o aviso sem via");
    const { lista, ciclo } = processo.guia;
    const primeiro = await caso();
    const segundo = await caso();
    assert.equal(await lista.reserve(primeiro.id), "granted");
    assert.equal(await lista.reserve(segundo.id), "lista_espera");
    // A vaga do primeiro sai da janela: a volta do lote convida o segundo, sem via.
    await admin.query(
      "UPDATE platform.waitlist_entry SET concluido_em = now() - interval '8 days' WHERE onboarding_id = $1",
      [primeiro.id],
    );
    const ler = async () =>
      (
        await admin.query<{ estado: string; tentativas: number; fase: string }>(
          `SELECT w.estado, w.tentativas, c.fase FROM platform.waitlist_entry w
             JOIN platform.onboarding_case c ON c.id = w.onboarding_id WHERE w.onboarding_id = $1`,
          [segundo.id],
        )
      ).rows[0];
    assert.deepEqual((await ciclo.correr()).falhou, []);
    assert.equal((await ler())?.estado, "convidado");
    // Vence duas vezes, que era o que abandonava o caso (critério 5 do KAM-095).
    for (let vez = 0; vez < 2; vez += 1) {
      await admin.query(
        `UPDATE platform.waitlist_entry SET convidado_em = now() - interval '3 days',
           convite_expira_em = now() - interval '1 hour' WHERE onboarding_id = $1`,
        [segundo.id],
      );
      assert.deepEqual((await ciclo.correr()).falhou, []);
    }
    assert.deepEqual(await ler(), { estado: "convidado", tentativas: 0, fase: "aguarda_es" });
  });
});

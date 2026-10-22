/**
 * A coexistência contra um PostgreSQL real (KAM-017).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **O «2.ª execução = *no-op*» do critério 3 é do servidor.** O predicado
 *    `NOT ($3 = ANY (passos_feitos))` serializa com **duas ligações** a
 *    disputar o mesmo passo, e o que decide é o `UPDATE` e não quem leu
 *    primeiro. Uma base falsa devolve o que se lhe mandou devolver.
 * 2. **A unicidade `(tenant_id, channel_id)` é o critério 9.** Duas aberturas
 *    concorrentes deixam **uma** linha, e a segunda **repõe** a primeira em vez
 *    de criar outra — é o `ON CONFLICT ... DO UPDATE` a morder sob
 *    concorrência, que é a única forma de o provar.
 * 3. **O desligamento são dois predicados na mesma transacção.** O
 *    `desligado_em IS NULL` e o `estado <> 'desligado'` têm de morder juntos:
 *    se só um mordesse, as duas tabelas discordavam sobre se o canal está
 *    desligado. Afirma-se com duas chamadas concorrentes.
 * 4. **A RLS recusa o que o código deixaria passar** (X-03). Com o contexto de
 *    A, a coexistência de B não se lê nem se escreve — e com `FORCE`, nem como
 *    dono da tabela.
 * 5. **O `GREATEST` do relógio sobrevive a *echoes* fora de ordem**, que é o
 *    caso real: a fila é de concorrência 1 mas a Meta reentrega.
 *
 * O que **não** se mede aqui: a tradução do vocabulário, a decisão do 2593109,
 * os desfechos do *echo* e as métricas vivem em `tests/coexistencia.test.ts`,
 * porque são decisões e uma base real não acrescenta nada à prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  CODIGO_SEM_HISTORICO,
  Coexistente,
  MetricasDaCoexistencia,
  PRAZO_DE_SINCRONIZACAO_MS,
  SQL_ABRIR,
  SQL_MARCAR_PASSO,
} from "../src/coexistencia/index.ts";
import {
  BASE_DESCARTAVEL,
  apagarTenant,
  criarCanal,
  criarTenant,
  ligar,
} from "./apoio.ts";

/**
 * Põe o contexto de *tenant* na ligação, **de sessão**.
 *
 * `set_config(..., false)` e não `true`, pela razão que o `outbound.bd.test.ts`
 * escreveu e o `qualidade.bd.test.ts` repetiu: fora de um `BEGIN` explícito
 * cada instrução é a sua própria transacção, e com `true` a definição
 * desaparecia antes da instrução seguinte — com RLS `FORCE`, o `kamba_app`
 * ficava sem contexto e via zero linhas.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

const T0 = new Date("2026-10-01T00:00:00Z");

describe("a coexistencia contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a corrida pelo
  // predicado do passo so e real com duas sessoes. Com uma, os dois `UPDATE`
  // saem em serie pela mesma conexao e o teste prova que o JavaScript e
  // sequencial.
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let canalA = "";
  let canalB = "";
  let pnidA = "";

  function montar(
    relogio: () => Date = () => T0,
  ): { coex: Coexistente; metricas: MetricasDaCoexistencia } {
    const metricas = new MetricasDaCoexistencia();
    const coex = new Coexistente({
      emitirCanalActualizado: async () => "evt",
      emitirAviso: async () => "evt",
      contacto: async () => ({ contactId: "00000000-0000-7000-8000-000000000000" }),
      conversa: async () => null,
      transitar: async () => {},
      metricas,
      agora: relogio,
    });
    return { coex, metricas };
  }

  before(async () => {
    admin = await ligar("admin");
    app = await ligar("app");
    app2 = await ligar("app");
    tenantA = await criarTenant(admin, `coex-A ${BASE_DESCARTAVEL}`);
    tenantB = await criarTenant(admin, `coex-B ${BASE_DESCARTAVEL}`);
    const a = await criarCanal(admin, tenantA, { channelMode: "coexistencia" });
    const b = await criarCanal(admin, tenantB, { channelMode: "coexistencia" });
    canalA = a.id;
    pnidA = a.phoneNumberId;
    canalB = b.id;
    await definirContexto(app, tenantA);
    await definirContexto(app2, tenantA);
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

  async function limpar(): Promise<void> {
    await admin.query("DELETE FROM platform.channel_coexistence");
    await admin.query(
      "UPDATE platform.tenant_channels SET estado = 'ativo', " +
        "coexistence_synced_at = NULL, last_account_update_at = NULL",
    );
  }

  async function abrir(cliente: pg.Client, canal: string): Promise<void> {
    await cliente.query(SQL_ABRIR, [
      cliente === app2 ? tenantA : tenantA,
      canal,
      T0,
      new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS),
    ]);
  }

  // ------------------------------------------------- critério 3 sob concorrência

  it("[bd] duas ligacoes a marcar o mesmo passo: uma escreve, a outra zero", async () => {
    await limpar();
    await abrir(app, canalA);
    // As duas pela mesma ordem, em paralelo. O que decide e o predicado.
    const resultados = await Promise.all([
      app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "historico", 1, 100, T0]),
      app2.query(SQL_MARCAR_PASSO, [tenantA, canalA, "historico", 1, 100, T0]),
    ]);
    const escreveram = resultados.filter((r) => r.rowCount === 1).length;
    assert.equal(escreveram, 1, "o predicado nao serializou: as duas escreveram");
    const { rows } = await admin.query<{
      passos_feitos: string[];
      mensagens_vistas: number;
    }>(
      "SELECT passos_feitos, mensagens_vistas FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.deepEqual(rows[0]?.passos_feitos, ["historico"]);
    // **A contagem nao somou duas vezes**, e e por isso que a mesma instrucao
    // marca o passo e soma: separa-las dava um caminho em que o lote repetido
    // contava sem marcar.
    assert.equal(Number(rows[0]?.mensagens_vistas), 100);
  });

  it("[bd] os dois passos diferentes passam os dois", async () => {
    await limpar();
    await abrir(app, canalA);
    await Promise.all([
      app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "contactos", 2, 0, T0]),
      app2.query(SQL_MARCAR_PASSO, [tenantA, canalA, "historico", 0, 50, T0]),
    ]);
    const { rows } = await admin.query<{ passos_feitos: string[] }>(
      "SELECT passos_feitos FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.deepEqual([...(rows[0]?.passos_feitos ?? [])].sort(), [
      "contactos",
      "historico",
    ]);
  });

  it("[bd] um lote depois do prazo nao entra, e e a instrucao que o recusa", async () => {
    // **Sem chamar a varredura.** O `prazo_em > $6` e o que torna as 24 h
    // duras pela base e nao pelo calendario de quem varre — e, como nao ha
    // agendador, essa diferenca e a unica coisa entre «o prazo e duro» e «o
    // prazo e duro a partir do momento em que alguem se lembrar».
    await limpar();
    await abrir(app, canalA);
    const depois = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    const r = await app.query(SQL_MARCAR_PASSO, [
      tenantA,
      canalA,
      "historico",
      1,
      10,
      depois,
    ]);
    assert.equal(r.rowCount, 0);
    const { rows } = await admin.query<{ passos_feitos: string[]; estado: string }>(
      "SELECT passos_feitos, estado FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.deepEqual(rows[0]?.passos_feitos, []);
    assert.equal(rows[0]?.estado, "a_sincronizar");
  });

  it("[bd] a varredura dos prazos corre como kamba_batch, e nao como admin", async () => {
    // **O teste que teria apanhado o defeito da primeira versao.** As tres
    // varreduras sao `UPDATE` sem `tenant_id`, logo so correm com `BYPASSRLS`
    // — e a `0018` negava o `UPDATE` ao unico papel que o tem. Respondiam
    // `42501`, e os criterios 3 e 6 nao tinham caminho executavel.
    await limpar();
    await abrir(app, canalA);
    const batch = await ligar("batch");
    try {
      const depois = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
      const { coex } = montar(() => depois);
      const r = await coex.varrerPrazos(batch);
      assert.deepEqual(r.falhados, [canalA]);
    } finally {
      await batch.end();
    }
  });

  it("[bd] o relogio acelerado fecha as 24 h, e a segunda varredura nao faz nada", async () => {
    await limpar();
    const { coex, metricas } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    const depois = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    const { coex: varredor } = montar(() => depois);
    // A varredura corre com `kamba_batch`? Nao: corre com o administrador
    // desta bateria, que e quem tem `BYPASSRLS` aqui. O papel de producao e o
    // `kamba_batch`, e o que esta linha prova e o **predicado**, que e o mesmo.
    const primeira = await varredor.varrerPrazos(admin);
    assert.deepEqual(primeira.falhados, [canalA]);
    const segunda = await varredor.varrerPrazos(admin);
    assert.deepEqual(segunda.falhados, []);
    void metricas;
  });

  // ------------------------------------------------- critério 9 sob concorrência

  it("[bd] duas aberturas concorrentes deixam **uma** linha", async () => {
    await limpar();
    await Promise.all([abrir(app, canalA), abrir(app2, canalA)]);
    const { rows } = await admin.query<{ quantas: string }>(
      "SELECT count(*)::text AS quantas FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0]?.quantas, "1");
  });

  it("[bd] a reconexao repoe a linha, e os passos da ligacao anterior nao sobrevivem", async () => {
    await limpar();
    const { coex } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    await app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "contactos", 5, 0, T0]);
    await app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "historico", 0, 900, T0]);
    const maisTarde = new Date(T0.getTime() + 30 * 24 * 60 * 60 * 1_000);
    const { coex: outra } = montar(() => maisTarde);
    await outra.abrir(app, tenantA, canal);
    const { rows } = await admin.query<{
      quantas: string;
      passos_feitos: string[];
      estado: string;
      mensagens_vistas: number;
    }>(
      "SELECT count(*)::text AS quantas, max(estado) AS estado, " +
        "       max(mensagens_vistas) AS mensagens_vistas, " +
        "       min(passos_feitos) AS passos_feitos " +
        "FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0]?.quantas, "1");
    assert.equal(rows[0]?.estado, "a_sincronizar");
    assert.deepEqual(rows[0]?.passos_feitos, []);
    assert.equal(Number(rows[0]?.mensagens_vistas), 0);
  });

  // ------------------------------------------------- critério 5 sob concorrência

  it("[bd] dois `account_update` concorrentes deixam **uma** transicao", async () => {
    await limpar();
    const { coex: um, metricas: m1 } = montar();
    const { coex: dois, metricas: m2 } = montar();
    const canal = await um.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await um.abrir(app, tenantA, canal);
    const bruto = { evento: "PARTNER_REMOVED", motivo: "PRIMARY_INACTIVITY" };
    const [a, b] = await Promise.all([
      um.tratarAccountUpdate(app, tenantA, canal, bruto),
      dois.tratarAccountUpdate(app2, tenantA, canal, bruto),
    ]);
    assert.equal([a.desligou, b.desligou].filter(Boolean).length, 1);
    const { rows } = await admin.query<{ estado: string }>(
      "SELECT estado FROM platform.tenant_channels WHERE id = $1",
      [canalA],
    );
    assert.equal(rows[0]?.estado, "desligado");
    const contadas =
      (m1.ler()["channel_disconnected_total:primary_inactivity"] ?? 0) +
      (m2.ler()["channel_disconnected_total:primary_inactivity"] ?? 0);
    assert.equal(contadas, 1);
  });

  it("[bd] as duas tabelas concordam depois de um desligamento", async () => {
    await limpar();
    const { coex } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    await coex.tratarAccountUpdate(app, tenantA, canal, {
      evento: "PARTNER_REMOVED",
      motivo: "CHANGE_NUMBER",
    });
    const { rows } = await admin.query<{
      estado_canal: string;
      motivo: string;
      desligado_em: Date | null;
    }>(
      "SELECT c.estado AS estado_canal, x.motivo_desligamento AS motivo, " +
        "       x.desligado_em AS desligado_em " +
        "FROM platform.tenant_channels c " +
        "JOIN platform.channel_coexistence x ON x.channel_id = c.id " +
        "WHERE c.id = $1",
      [canalA],
    );
    assert.equal(rows[0]?.estado_canal, "desligado");
    assert.equal(rows[0]?.motivo, "change_number");
    assert.ok(rows[0]?.desligado_em !== null);
  });

  // ------------------------------------------------- o relógio do `echo`

  it("[bd] o GREATEST nao deixa um echo atrasado recuar o relogio", async () => {
    await limpar();
    const { coex } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    const tarde = new Date(T0.getTime() + 10_000);
    const cedo = new Date(T0.getTime() + 5_000);
    const { coex: primeiro } = montar(() => tarde);
    const { coex: segundo } = montar(() => cedo);
    const destinatario = { bsuid: null, telefone: "+244900000001" };
    await primeiro.tratarEcho(app, tenantA, canal, { wamid: "w1", destinatario });
    await segundo.tratarEcho(app, tenantA, canal, { wamid: "w2", destinatario });
    const { rows } = await admin.query<{ ultimo_echo_em: Date }>(
      "SELECT ultimo_echo_em FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0]?.ultimo_echo_em?.getTime(), tarde.getTime());
  });

  it("[bd] um echo cujo wamid esta em outbound_messages e ignorado", async () => {
    await limpar();
    const { coex, metricas } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    // Uma mensagem **nossa**, com o `wamid` preenchido. A `outbound_messages`
    // tem `contact_id` e `conversation_id` `NOT NULL` com FK compostas (a
    // `0010`), pelo que a linha precisa de um contacto e de uma conversa a
    // serio — nao chega o canal.
    const { rows: c } = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenantA],
    );
    const contactoId = c[0]?.contact_id ?? "";
    const { rows: v } = await admin.query<{ id: string }>(
      "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id) " +
        "VALUES ($1, $2, $3) RETURNING id::text AS id",
      [tenantA, contactoId, canalA],
    );
    const conversaId = v[0]?.id ?? "";
    const wamid = `wamid.nosso.${Date.now()}`;
    await admin.query(
      "INSERT INTO platform.outbound_messages " +
        "(tenant_id, channel_id, contact_id, conversation_id, idempotency_key, " +
        " kind, state, wamid) " +
        // O `kind` e a **categoria de conversa** da Meta (`service`, `utility`,
        // `marketing`, `authentication`) e nao o tipo da mensagem: e o
        // `outbound_messages_kind_ck` da `0010`. Um `'text'` levanta `23514`.
        "VALUES ($1, $2, $3, $4, $5, 'service', 'sent', $6)",
      [tenantA, canalA, contactoId, conversaId, `idem-${wamid}`, wamid],
    );
    const r = await coex.tratarEcho(app, tenantA, canal, {
      wamid,
      destinatario: { bsuid: null, telefone: "+244900000001" },
    });
    assert.equal(r.desfecho, "nosso");
    assert.equal(metricas.ler()["coex_echo_total:nosso"], 1);
    const { rows } = await admin.query<{ ultimo_echo_em: Date | null }>(
      "SELECT ultimo_echo_em FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0]?.ultimo_echo_em, null);
    await admin.query("DELETE FROM platform.outbound_messages WHERE wamid = $1", [
      wamid,
    ]);
    await admin.query("DELETE FROM platform.conversations WHERE id = $1", [conversaId]);
    await admin.query("DELETE FROM platform.contacts WHERE contact_id = $1", [
      contactoId,
    ]);
  });

  // ------------------------------------------------- X-03: isolamento

  it("[bd] com o contexto de A, a coexistencia de B nao se le", async () => {
    await limpar();
    await abrir(app, canalA);
    await admin.query(
      "INSERT INTO platform.channel_coexistence (tenant_id, channel_id, prazo_em) " +
        "VALUES ($1, $2, now() + interval '24 hours')",
      [tenantB, canalB],
    );
    const { rows } = await app.query(
      "SELECT channel_id::text AS channel_id FROM platform.channel_coexistence",
    );
    assert.deepEqual(
      rows.map((r) => (r as { channel_id: string }).channel_id),
      [canalA],
    );
  });

  it("[bd] com o contexto de A, a coexistencia de B nao se altera", async () => {
    await limpar();
    await admin.query(
      "INSERT INTO platform.channel_coexistence (tenant_id, channel_id, prazo_em) " +
        "VALUES ($1, $2, now() + interval '24 hours')",
      [tenantB, canalB],
    );
    const resultado = await app.query(
      "UPDATE platform.channel_coexistence SET estado = 'falhado' " +
        "WHERE channel_id = $1",
      [canalB],
    );
    assert.equal(resultado.rowCount, 0);
    const { rows } = await admin.query<{ estado: string }>(
      "SELECT estado FROM platform.channel_coexistence WHERE tenant_id = $1",
      [tenantB],
    );
    assert.equal(rows[0]?.estado, "a_sincronizar");
  });

  it("[bd] sem contexto, o kamba_app ve zero linhas (falha fechada)", async () => {
    await limpar();
    await abrir(app, canalA);
    const sem = await ligar("app");
    try {
      const { rows } = await sem.query(
        "SELECT count(*)::text AS quantas FROM platform.channel_coexistence",
      );
      assert.equal((rows[0] as { quantas: string }).quantas, "0");
    } finally {
      await sem.end();
    }
  });

  it("[bd] o kamba_app nao consegue apagar, e e um privilegio e nao uma politica", async () => {
    await limpar();
    await abrir(app, canalA);
    await assert.rejects(
      app.query("DELETE FROM platform.channel_coexistence WHERE channel_id = $1", [
        canalA,
      ]),
      /permission denied|42501/,
    );
  });

  // ------------------------------------------------- o 2593109 contra a base

  it("[bd] o 2593109 fica numa coluna integer e nao passa por falhado", async () => {
    await limpar();
    const { coex } = montar();
    const canal = await coex.canal(app, tenantA, pnidA);
    assert.ok(canal !== null);
    await coex.abrir(app, tenantA, canal);
    await coex.ingerirHistorico(app, tenantA, canalA, {
      mensagens: 0,
      contactos: [],
      erros: [CODIGO_SEM_HISTORICO],
    });
    const { rows } = await admin.query<{
      estado: string;
      meta_error_code: number;
    }>(
      "SELECT estado, meta_error_code FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0]?.estado, "sincronizado_sem_historico");
    assert.equal(Number(rows[0]?.meta_error_code), CODIGO_SEM_HISTORICO);
    // E o canal ficou carimbado, porque isto e sucesso.
    const canal2 = await admin.query<{ coexistence_synced_at: Date | null }>(
      "SELECT coexistence_synced_at FROM platform.tenant_channels WHERE id = $1",
      [canalA],
    );
    assert.ok(canal2.rows[0]?.coexistence_synced_at !== null);
  });
});

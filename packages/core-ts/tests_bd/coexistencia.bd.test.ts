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
  INACTIVIDADE_DO_DONO_MS,
  PRAZO_DE_SINCRONIZACAO_MS,
  SQL_ABRIR,
  ALERTA_DE_SINCRONIZACAO_MS,
  SQL_CONCLUIR,
  SQL_REGISTAR_DESLIGAMENTO,
  SQL_DESLIGAR_CANAL,
  SQL_MARCAR_PASSO,
  SQL_REGISTAR_ECHO,
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

  // ------------- critérios 3 e 5: os predicados que só a base pode recusar
  //
  // **Sete ensaios, e nasceram todos da mesma medição.** Depois de fechar as
  // quatro mutações do aviso, a corrida completa do filtro `coexistencia` deu 41
  // mutações com **10 sobreviventes** — e seis delas eram predicados de SQL dos
  // critérios 3 e 5, exactamente a lacuna que o critério 6 tinha: os testes
  // viviam na `BaseFalsa`, que os reimplementa em JavaScript e reconhece a
  // instrução pela **constante importada**, que a mutação também muda.
  //
  // A sétima é o instante que o `SQL_DESLIGAR_CANAL` escreve, que nenhum teste
  // lia.

  it("[bd] o passo não entra numa sincronização que já falhou", async () => {
    // `AND estado = 'a_sincronizar'`. Sem ele, um lote de `history` que chegasse
    // depois do *offboard* voltava a mexer numa sincronização encerrada — e os
    // passos «só podem ser executados uma vez» (`E1` §2, CONFIRMADO).
    await limpar();
    await abrir(app, canalA);
    await admin.query(
      "UPDATE platform.channel_coexistence SET estado = 'falhado' " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    const r = await app.query(SQL_MARCAR_PASSO, [
      tenantA,
      canalA,
      "historico",
      1,
      100,
      T0,
    ]);
    assert.equal(r.rows.length, 0);
    // E a metade positiva: em `a_sincronizar` o mesmo lote entra.
    await admin.query(
      "UPDATE platform.channel_coexistence SET estado = 'a_sincronizar' " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    const bom = await app.query(SQL_MARCAR_PASSO, [
      tenantA,
      canalA,
      "historico",
      1,
      100,
      T0,
    ]);
    assert.equal(bom.rows.length, 1);
  });

  it("[bd] concluir depois do prazo não concluí", async () => {
    // `AND prazo_em > $3` no `SQL_CONCLUIR`. **Não há agendador**, pelo que uma
    // conclusão pode chegar depois das 24 h sem que ninguém tenha corrido a
    // varredura — e o prazo tem de morder na própria instrução. Achado da
    // revisão adversarial do ticket, e sem teste até agora.
    await limpar();
    await abrir(app, canalA);
    for (const passo of ["contactos", "historico"]) {
      await app.query(SQL_MARCAR_PASSO, [tenantA, canalA, passo, 1, 10, T0]);
    }
    const vencido = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    assert.equal((await app.query(SQL_CONCLUIR, [tenantA, canalA, vencido])).rows.length, 0);
    // Dentro do prazo, conclui.
    const dentro = new Date(T0.getTime() + 1_000);
    assert.equal((await app.query(SQL_CONCLUIR, [tenantA, canalA, dentro])).rows.length, 1);
  });

  it("[bd] concluir sem os dois passos não concluí", async () => {
    // `AND passos_feitos @> ARRAY['contactos','historico']`. Com um passo só, a
    // sincronização não acabou — e é o `@>` que o diz, não um `if`.
    await limpar();
    await abrir(app, canalA);
    await app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "contactos", 1, 0, T0]);
    const dentro = new Date(T0.getTime() + 1_000);
    assert.equal((await app.query(SQL_CONCLUIR, [tenantA, canalA, dentro])).rows.length, 0);
    await app.query(SQL_MARCAR_PASSO, [tenantA, canalA, "historico", 0, 10, T0]);
    assert.equal((await app.query(SQL_CONCLUIR, [tenantA, canalA, dentro])).rows.length, 1);
  });

  it("[bd] o alerta das 12 h é idempotente, e é o `alertado_em` que o faz", async () => {
    // `AND alertado_em IS NULL`. Sem ele, cada varredura voltava a alertar o
    // mesmo canal — e as varreduras correm em série, pelo que o dono levava um
    // alerta por passagem.
    await limpar();
    await abrir(app, canalA);
    const depois = new Date(T0.getTime() + ALERTA_DE_SINCRONIZACAO_MS + 1_000);
    const { coex } = montar(() => depois);
    const primeira = await coex.varrerPrazos(admin);
    assert.deepEqual(primeira.alertados, [canalA]);
    const segunda = await coex.varrerPrazos(admin);
    assert.deepEqual(segunda.alertados, []);
    const { rows } = await admin.query(
      "SELECT alertado_em IS NOT NULL AS alertado FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0].alertado, true);
  });

  it("[bd] a falha às 24 h lê o `prazo_em` e não o `iniciado_em`", async () => {
    // `AND prazo_em <= $1`. Os dois instantes são **diferentes** por desenho: o
    // `prazo_em` é coluna para que o relógio acelerado dos testes o possa mover
    // sem mexer no servidor. Este ensaio separa-os: põe o `prazo_em` 48 h à
    // frente do que o `iniciado_em` implicaria, e mede às 24 h — com a instrução
    // a ler o arranque, o canal falhava; a ler a coluna, não falha.
    await limpar();
    await abrir(app, canalA);
    await admin.query(
      "UPDATE platform.channel_coexistence SET prazo_em = $3 " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA, new Date(T0.getTime() + 48 * 3_600_000)],
    );
    const as24 = new Date(T0.getTime() + PRAZO_DE_SINCRONIZACAO_MS + 1_000);
    const { coex } = montar(() => as24);
    assert.deepEqual((await coex.varrerPrazos(admin)).falhados, []);
    // E às 48 h, falha.
    const as48 = new Date(T0.getTime() + 48 * 3_600_000 + 1_000);
    const { coex: depois } = montar(() => as48);
    assert.deepEqual((await depois.varrerPrazos(admin)).falhados, [canalA]);
  });

  it("[bd] o registo do desligamento é idempotente, pelo `desligado_em`", async () => {
    // `AND desligado_em IS NULL` no `SQL_REGISTAR_DESLIGAMENTO`. É o «repetir o
    // mesmo evento 2× produz 1 transição» do critério 5 visto da tabela da
    // coexistência: a segunda passagem devolve zero linhas, e é isso que o
    // módulo lê para decidir se avisa de desalinhamento.
    await limpar();
    await abrir(app, canalA);
    const agora = new Date(T0.getTime() + 1_000);
    const primeiro = await app.query(SQL_REGISTAR_DESLIGAMENTO, [
      tenantA,
      canalA,
      "change_number",
      agora,
    ]);
    assert.equal(primeiro.rows.length, 1);
    const segundo = await app.query(SQL_REGISTAR_DESLIGAMENTO, [
      tenantA,
      canalA,
      "primary_inactivity",
      new Date(agora.getTime() + 1_000),
    ]);
    assert.equal(segundo.rows.length, 0);
    // E o **primeiro** motivo é o que fica: um canal desliga-se uma vez, e
    // reescrever o motivo era perder porque é que ele se desligou.
    const { rows } = await admin.query(
      "SELECT motivo_desligamento FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0].motivo_desligamento, "change_number");
  });

  it("[bd] o `last_account_update_at` leva o instante do evento", async () => {
    // O `GREATEST(COALESCE(last_account_update_at, $3), $3)` do
    // `SQL_DESLIGAR_CANAL`, e a coluna é «o carimbo do último `account_update`
    // **tratado**». Nenhum teste a lia, pelo que uma mutação que passasse a
    // escrever a época sobrevivia — e o painel passava a dizer que a Meta falou
    // em 1970.
    //
    // **O que este ensaio não cobre, e ficou provado que não cobria:** ele
    // chama a instrução directamente, com o seu próprio parâmetro, pelo que
    // prova o `GREATEST` e **não** o instante que o módulo escolhe. A mutação
    // que troca esse instante vive no `tratarAccountUpdate` e sobreviveu a este
    // ensaio; quem a apanha é o «as duas tabelas concordam depois de um
    // desligamento».
    await limpar();
    const agora = new Date(T0.getTime() + 5_000);
    const r = await app.query(SQL_DESLIGAR_CANAL, [tenantA, canalA, agora]);
    assert.equal(r.rows.length, 1);
    const { rows } = await admin.query(
      "SELECT last_account_update_at FROM platform.tenant_channels " +
        "WHERE tenant_id = $1 AND id = $2",
      [tenantA, canalA],
    );
    assert.equal(
      (rows[0].last_account_update_at as Date).toISOString(),
      agora.toISOString(),
    );
    // E o `GREATEST` não deixa um evento atrasado recuar o carimbo.
    await app.query(SQL_DESLIGAR_CANAL, [tenantA, canalA, new Date(0)]);
    const { rows: depois } = await admin.query(
      "SELECT last_account_update_at FROM platform.tenant_channels " +
        "WHERE tenant_id = $1 AND id = $2",
      [tenantA, canalA],
    );
    assert.equal(
      (depois[0].last_account_update_at as Date).toISOString(),
      agora.toISOString(),
    );
  });

  // --------------------------------- critério 6: o aviso dos 10 dias, na base
  //
  // **Estes dois ensaios nasceram da prova por mutação do KAM-115.** Ela corria
  // um filtro largo e apanhou três mutações deste ticket a sobreviver, duas
  // delas no `SQL_AVISAR_INACTIVOS`: o `avisado_em IS NULL` e o
  // `estado IN ('sincronizado', 'sincronizado_sem_historico')`.
  //
  // A razão de sobreviverem é a mesma para as duas, e é instrutiva: os testes do
  // critério 6 vivem todos na bateria do *gate* 4, contra a `BaseFalsa` — e ela
  // **reimplementa o predicado em JavaScript**. Pior: ela reconhece a instrução
  // comparando-a com a constante importada, que a mutação também muda, pelo que
  // a comparação continua a bater e o predicado JS fica intacto. Mutar o SQL não
  // tinha efeito nenhum sobre aqueles testes.
  //
  // É a mesma classe de lacuna que o KAM-115 encontrou em dois dos seus. A lição
  // é a do `outbound/consultas.ts`: **a suite do gate 8 corre estas cadeias e
  // não cópias delas**, e um predicado só se prova onde é o PostgreSQL a
  // avaliá-lo.

  it("[bd] o aviso dos 10 dias é idempotente, e é o `avisado_em` que o faz", async () => {
    // A primeira varredura avisa, a segunda não — e o que o impede é a coluna,
    // não um `if`. Sem o `avisado_em IS NULL`, a segunda passagem voltava a
    // devolver o canal e o dono levava um aviso por cada varredura.
    await limpar();
    await abrir(app, canalA);
    // Põe o canal num estado de sucesso: o aviso só olha para esses.
    await admin.query(
      "UPDATE platform.channel_coexistence SET estado = 'sincronizado' " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    const depois = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    const { coex } = montar(() => depois);
    assert.deepEqual(await coex.varrerInactividade(admin), [canalA]);
    assert.deepEqual(await coex.varrerInactividade(admin), []);
    // E a coluna ficou escrita: é dela que a idempotência sai.
    const { rows } = await admin.query(
      "SELECT avisado_em IS NOT NULL AS avisado FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0].avisado, true);
  });

  it("[bd] o aviso só olha para os dois estados de sucesso", async () => {
    // «Um canal cuja sincronização falhou já não está em coexistência, e avisá-lo
    // de inactividade era avisar de um problema que não é o dele.» Os quatro
    // estados, um a um: os dois de sucesso entram e os outros dois não.
    const depois = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    const { coex } = montar(() => depois);
    for (const [estado, esperado] of [
      ["sincronizado", [canalA]],
      ["sincronizado_sem_historico", [canalA]],
      ["a_sincronizar", []],
      ["falhado", []],
    ] as const) {
      await limpar();
      await abrir(app, canalA);
      await admin.query(
        "UPDATE platform.channel_coexistence SET estado = $3 " +
          "WHERE tenant_id = $1 AND channel_id = $2",
        [tenantA, canalA, estado],
      );
      assert.deepEqual(await coex.varrerInactividade(admin), esperado, estado);
    }
  });

  it("[bd] o echo do dono **reabre** a janela do aviso, pela coluna", async () => {
    // A quarta da mesma familia, e apareceu quando o filtro das mutacoes se
    // alargou de «o aviso» para incluir o `SQL_REGISTAR_ECHO`: o
    // `avisado_em = NULL` que ele escreve e **metade** do criterio 6, e nao um
    // extra. Sem ele, um canal avisado uma vez nunca mais era avisado, porque o
    // predicado do aviso filtra por `avisado_em IS NULL` — e a janela deixava de
    // reabrir quando o dono voltava a dar sinal.
    //
    // O ciclo inteiro, na base: avisa, o dono escreve, avisa outra vez.
    await limpar();
    await abrir(app, canalA);
    await admin.query(
      "UPDATE platform.channel_coexistence SET estado = 'sincronizado' " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    const depois = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    const { coex } = montar(() => depois);
    assert.deepEqual(await coex.varrerInactividade(admin), [canalA]);
    assert.deepEqual(await coex.varrerInactividade(admin), []);

    // Actividade do dono: o `SQL_REGISTAR_ECHO` move o relogio **e** limpa o
    // aviso.
    await app.query(SQL_REGISTAR_ECHO, [tenantA, canalA, depois]);
    const { rows } = await admin.query(
      "SELECT avisado_em FROM platform.channel_coexistence " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    assert.equal(rows[0].avisado_em, null);

    // E dez dias depois **desse** echo, o aviso volta a sair.
    const maisDez = new Date(depois.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
    const { coex: outraVez } = montar(() => maisDez);
    assert.deepEqual(await outraVez.varrerInactividade(admin), [canalA]);
  });

  it("[bd] a varredura do aviso corre como `kamba_batch`", async () => {
    // Pela mesma razão que a dos prazos: é um `UPDATE` **sem `tenant_id`** no
    // predicado, logo só corre com `BYPASSRLS` — e o `kamba_batch` é o único
    // papel que o tem. Sem a concessão da `0018` respondia `42501`, e o critério
    // 6 não tinha caminho executável.
    await limpar();
    await abrir(app, canalA);
    await admin.query(
      "UPDATE platform.channel_coexistence SET estado = 'sincronizado' " +
        "WHERE tenant_id = $1 AND channel_id = $2",
      [tenantA, canalA],
    );
    const batch = await ligar("batch");
    try {
      const depois = new Date(T0.getTime() + INACTIVIDADE_DO_DONO_MS + 1_000);
      const { coex } = montar(() => depois);
      assert.deepEqual(await coex.varrerInactividade(batch), [canalA]);
    } finally {
      await batch.end();
    }
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
    // **E concordam no instante, afirmado pelo valor.** Este ensaio dizia
    // `desligado_em !== null`, e um `new Date(0)` não é nulo: a mutação que
    // troca o `agora` por `new Date(0)` nos argumentos do `SQL_DESLIGAR_CANAL`
    // sobrevivia aqui.
    //
    // E sobreviveu também ao ensaio que entrou no #50 a fechar esta mesma
    // mutação, por uma razão que vale escrever: aquele chama o
    // `SQL_DESLIGAR_CANAL` **directamente**, com o seu próprio parâmetro, pelo
    // que nunca passa pela linha mutada — a mutação está no **sítio onde o
    // módulo o chama**, dentro do `tratarAccountUpdate`. É a armadilha da
    // `BaseFalsa` um nível acima: provar a instrução em vez do caminho que a
    // usa. Fecha-se aqui, que é onde o módulo escolhe o instante.
    await limpar();
    const instante = new Date(T0.getTime() + 5_000);
    const { coex } = montar(() => instante);
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
      carimbo: Date | null;
    }>(
      "SELECT c.estado AS estado_canal, x.motivo_desligamento AS motivo, " +
        "       x.desligado_em AS desligado_em, " +
        "       c.last_account_update_at AS carimbo " +
        "FROM platform.tenant_channels c " +
        "JOIN platform.channel_coexistence x ON x.channel_id = c.id " +
        "WHERE c.id = $1",
      [canalA],
    );
    assert.equal(rows[0]?.estado_canal, "desligado");
    assert.equal(rows[0]?.motivo, "change_number");
    // Os dois instantes saem **do mesmo** `agora` do módulo: o `desligado_em`
    // do registo da coexistência e o `last_account_update_at` do canal. Um
    // `new Date(0)` em qualquer dos dois punha o painel a dizer que a Meta
    // falou em 1970.
    assert.equal(rows[0]?.desligado_em?.toISOString(), instante.toISOString());
    assert.equal(rows[0]?.carimbo?.toISOString(), instante.toISOString());
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
    const destinatario = { bsuid: null, telefone: "+999100000001" };
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
      destinatario: { bsuid: null, telefone: "+999100000001" },
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

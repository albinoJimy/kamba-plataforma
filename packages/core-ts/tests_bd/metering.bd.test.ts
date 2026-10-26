/**
 * O contador do *free tier* contra um PostgreSQL real (KAM-023).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **A fronteira de mês é a meia-noite de `Africa/Luanda`, e não a de UTC.**
 *    É o critério 3, e é a asserção que nenhuma base falsa pode fazer: o fuso
 *    vive dentro de `platform.ten_periodo` (revisão `0007`), e só a base o
 *    aplica. Os dois instantes do ensaio estão a uma hora de distância e caem
 *    em **meses diferentes** — com a aritmética em UTC cairiam no mesmo, e é
 *    exactamente esse o defeito que isto apanha.
 * 2. **O flanco do aviso sobrevive à concorrência.** Dois incrementos em
 *    paralelo, na travessia dos 800: o contador sobe dois e sai **um** aviso.
 *    Só a base serializa, e é o `FOR UPDATE` do `SQL_CONTAR` que faz o segundo
 *    processo reler o que o primeiro escreveu. Com uma leitura prévia, os dois
 *    liam 799 e os dois concluíam «eu atravessei».
 * 3. **A idempotência do critério 2 é da base, e vem do KAM-015.** Três
 *    `delivered` do mesmo `wamid` produzem **uma** transição, logo **um**
 *    `entregou`, logo `+1` no contador. Uma base falsa devolve o que se lhe
 *    mandou devolver.
 * 4. **A RLS recusa o que o código deixaria passar** (X-03). Com o contexto de
 *    A, o contador de B não se lê nem se escreve — e com `FORCE`, nem como
 *    dono da tabela.
 * 5. **A junção do `SQL_FALHAS_RECENTES` e o `jsonb` do `SQL_RECONCILIAR`.**
 *    `outbound_messages` guarda `channel_id` e não o número, e o `pricing` é
 *    `jsonb`: as duas consultas só se provam onde houver um planeador.
 *
 * O que **não** se mede aqui: a estimativa, o rácio, a travessia célula a
 * célula, a heurística e a divergência vivem em `tests/metering.test.ts`,
 * porque são funções puras e uma base real não acrescenta nada à prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import {
  FREE_TIER_DE_SERVICE,
  Saida,
  type Corpo,
  type Destinatario,
  type Pedido,
  type Pricing,
} from "../src/outbound/index.ts";
import {
  AVISO_EM,
  Metering,
  MetricasDoFreeTier,
  SQL_ESTADO,
} from "../src/metering/index.ts";
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
 * `set_config(..., false)` e não `true`, pela razão que o
 * `outbound.bd.test.ts` escreveu: fora de um `BEGIN` explícito cada instrução é
 * a sua própria transacção, e com `true` a definição desaparecia antes da
 * instrução seguinte — com RLS `FORCE`, o `kamba_app` ficava sem contexto e via
 * zero linhas.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

/** O `pricing` que a Meta manda num `delivered` de serviço facturável. */
function pricing(troca: Partial<Pricing> = {}): Pricing {
  return {
    billable: true,
    pricing_model: "CBP",
    type: "service",
    category: "service",
    ...troca,
  };
}

const TEXTO: Corpo = { tipo: "texto", texto: "Bom dia" };

/**
 * Os dois instantes da fronteira de mês, **a uma hora de distância**.
 *
 * `Africa/Luanda` é UTC+1 e não tem hora de Verão, pelo que:
 *
 * * `22:30Z` de 31 de Outubro são `23:30` de 31 de Outubro em Luanda → Outubro;
 * * `23:30Z` de 31 de Outubro são `00:30` de **1 de Novembro** em Luanda →
 *   Novembro.
 *
 * **É este par que prova o fuso.** Em UTC os dois são Outubro, e um contador
 * que reiniciasse à meia-noite de UTC passava o primeiro teste e falhava este.
 */
const ANTES_DA_MEIA_NOITE = new Date("2026-10-31T22:30:00.000Z");
const DEPOIS_DA_MEIA_NOITE = new Date("2026-10-31T23:30:00.000Z");

describe("o contador do free tier contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a concorrencia do
  // flanco so e real com duas sessoes. Com uma, os dois `UPDATE` saem em serie
  // pela mesma conexao e o teste prova que o JavaScript e sequencial.
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let canalA = "";
  let canalB = "";
  let pnidA = "";
  let pnidB = "";
  let conversaA = "";
  let contactoA = "";
  let graph: GraphFalso;

  /** Uma conversa com a janela **aberta**, criada pelo administrador. */
  async function abrirConversa(tenant: string, canal: string): Promise<string> {
    const contacto = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenant],
    );
    const contactId = contacto.rows[0]?.contact_id ?? "";
    const conversa = await admin.query<{ id: string }>(
      "INSERT INTO platform.conversations " +
        "(tenant_id, contact_id, channel_id, last_inbound_at, window_expires_at) " +
        "VALUES ($1, $2, $3, now(), now() + interval '24 hours') RETURNING id",
      [tenant, contactId, canal],
    );
    return `${conversa.rows[0]?.id ?? ""}|${contactId}`;
  }

  /**
   * O cliente de SQL de um *tenant*, sobre a ligação dada.
   *
   * A ligação é parâmetro para que o teste do flanco concorrente possa dar-lhe
   * a segunda. A conversão de tipo é a mesma do `outbound.bd.test.ts`, e é
   * honesta num ensaio: quem escreve o SQL e quem escreve o parâmetro de tipo é
   * a mesma linha de teste.
   */
  function bdDe(tenant: string, cliente: pg.Client = app) {
    return {
      query: async <T,>(texto: string, valores?: readonly unknown[]) => {
        await definirContexto(cliente, tenant);
        const resultado = await cliente.query(
          texto,
          valores === undefined ? [] : [...valores],
        );
        return { rows: resultado.rows as readonly T[] };
      },
    };
  }

  /** O `Metering` de um *tenant*, com relógio fixo e métricas próprias. */
  function meteringDe(
    tenant: string,
    agora?: Date,
    cliente: pg.Client = app,
  ): { metering: Metering; metricas: MetricasDoFreeTier } {
    const metricas = new MetricasDoFreeTier();
    const metering = new Metering({
      bd: bdDe(tenant, cliente),
      metricas,
      ...(agora === undefined ? {} : { agora: () => agora }),
    });
    return { metering, metricas };
  }

  /** O contador de um canal, lido pelo **administrador** (sem RLS pelo meio). */
  async function contadorCru(
    canal: string,
  ): Promise<{ usadas: number; mes: string | null }> {
    const { rows } = await admin.query<{ usadas: number; mes: string | null }>(
      "SELECT free_tier_used AS usadas, free_tier_month::text AS mes " +
        "FROM platform.tenant_channels WHERE id = $1",
      [canal],
    );
    const linha = rows[0];
    return { usadas: Number(linha?.usadas ?? -1), mes: linha?.mes ?? null };
  }

  /** Põe o contador de um canal num valor, como administrador. */
  async function semear(canal: string, usadas: number, mes: string | null): Promise<void> {
    await admin.query(
      "UPDATE platform.tenant_channels SET free_tier_used = $2, free_tier_month = $3 " +
        "WHERE id = $1",
      [canal, usadas, mes],
    );
  }

  before(async () => {
    admin = await ligar("admin");
    app = await ligar("app");
    app2 = await ligar("app");
    const nome = await admin.query<{ base: string }>("SELECT current_database() AS base");
    assert.equal(
      nome.rows[0]?.base,
      BASE_DESCARTAVEL,
      "esta suite so corre contra a base descartavel do gate 8",
    );

    tenantA = await criarTenant(admin, "metering-a");
    tenantB = await criarTenant(admin, "metering-b");
    const canalDeA = await criarCanal(admin, tenantA);
    const canalDeB = await criarCanal(admin, tenantB);
    canalA = canalDeA.id;
    canalB = canalDeB.id;
    pnidA = canalDeA.phoneNumberId;
    pnidB = canalDeB.phoneNumberId;
    const a = (await abrirConversa(tenantA, canalA)).split("|");
    conversaA = a[0] ?? "";
    contactoA = a[1] ?? "";
    graph = new GraphFalso(new GeradorDeFixtures("metering-bd"));
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

  // ------------------------------------------------- a contagem (criterio 1)

  describe("a contagem (criterio 1)", () => {
    it("**1.200 entregas dao contador 1.200** — contra a coluna, nao contra um Map", async () => {
      await semear(canalA, 0, null);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      for (let n = 0; n < 1200; n += 1) {
        const contagem = await metering.contar(tenantA, pnidA);
        assert.ok(contagem !== null, `o incremento ${n} nao encontrou o canal`);
      }
      // Lido pelo administrador, da coluna: e a asserção de que o numero ficou
      // na base e nao na memoria do processo.
      const cru = await contadorCru(canalA);
      assert.equal(cru.usadas, 1200);
      assert.equal(cru.mes, "2026-10-01");
    });

    it("a leitura pela porta do KAM-015 ve o mesmo numero", async () => {
      await semear(canalA, 742, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.deepEqual(await metering.estado(tenantA, pnidA), {
        usadas: 742,
        tecto: FREE_TIER_DE_SERVICE,
      });
    });

    it("o `kamba_app` **pode** escrever estas duas colunas, e so estas", async () => {
      // O `GRANT UPDATE` da `0001` enumera treze colunas por nome, e as duas do
      // *free tier* estao nela. Esta asserção e o que torna verificavel a
      // afirmacao «este ticket nao precisa de DDL»: se a concessao nao as
      // tivesse, o `SQL_CONTAR` levantava `42501` aqui.
      await semear(canalA, 0, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.equal((await metering.contar(tenantA, pnidA))?.usadas, 1);
      // E a prova pela negativa: o `estado` do canal **nao** e deste ticket, e
      // uma escrita nele pelo `kamba_app` com o seu proprio contexto passa
      // (esta na lista) — o que nao passa e uma coluna fora da lista.
      await definirContexto(app, tenantA);
      await assert.rejects(
        app.query(
          "UPDATE platform.tenant_channels SET origem = 'plataforma' WHERE id = $1",
          [canalA],
        ),
        /permission denied|42501/,
      );
    });
  });

  // ------------------------------- a fronteira de mes no fuso (criterio 3)

  describe("a fronteira de mes e a de Africa/Luanda (criterio 3)", () => {
    it("**23:30 em Luanda ainda e Outubro**", async () => {
      await semear(canalA, 500, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const contagem = await metering.contar(tenantA, pnidA);
      assert.equal(contagem?.reiniciou, false);
      assert.equal(contagem?.usadas, 501);
      assert.equal(contagem?.mes, "2026-10-01");
    });

    it("**00:30 em Luanda ja e Novembro, e o contador reinicia**", async () => {
      await semear(canalA, 500, "2026-10-01");
      // Uma hora depois do teste anterior. Em **UTC** os dois instantes sao
      // Outubro (22:30 e 23:30 do dia 31), e um contador que reiniciasse a
      // meia-noite de UTC dava `reiniciou: false` aqui. E este par — e so este
      // par — que prova que o fuso aplicado e o de Luanda.
      const { metering } = meteringDe(tenantA, DEPOIS_DA_MEIA_NOITE);
      const contagem = await metering.contar(tenantA, pnidA);
      assert.equal(contagem?.reiniciou, true);
      assert.equal(contagem?.usadas, 1);
      assert.equal(contagem?.mes, "2026-11-01");
      assert.equal(contagem?.antes, 0);
    });

    it("**o mes virado le `0` sem escrever nada** — o defeito que custava dinheiro", async () => {
      // O canal fechou Outubro em 1.500 e ninguem corre um processo mensal para
      // o por a zero. Sem o `CASE` do mes, o KAM-015 lia 1.500, concluia «acima
      // do tecto» e contava custo a primeira mensagem de Novembro, em que ela e
      // gratis.
      await semear(canalA, 1500, "2026-10-01");
      const { metering } = meteringDe(tenantA, DEPOIS_DA_MEIA_NOITE);
      assert.equal((await metering.estado(tenantA, pnidA)).usadas, 0);
      // E a leitura nao escreveu: a coluna continua em 1.500.
      assert.equal((await contadorCru(canalA)).usadas, 1500);
    });

    it("um canal nunca usado tem o mes a `NULL`, e conta como mes novo", async () => {
      // Um `<>` com `NULL` da `NULL`, que num `CASE WHEN` nao e verdadeiro — e
      // o canal nunca reiniciava. O `IS DISTINCT FROM` e o que o resolve, e so
      // uma base o pode dizer.
      await semear(canalA, 0, null);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const contagem = await metering.contar(tenantA, pnidA);
      assert.equal(contagem?.reiniciou, true);
      assert.equal(contagem?.usadas, 1);
    });

    it("**com o mes a `NULL` e o contador em 500, o reinicio repoe e nao soma**", async () => {
      // Este caso veio da **prova por mutacao**, e e a razao de ele existir: a
      // mutacao que troca o `IS DISTINCT FROM` por `<>` **sobreviveu** ao teste
      // de cima. Com o contador em 0, os dois ramos do `CASE` dao o mesmo
      // numero — o `THEN 1` e o `ELSE 0 + 1` — e a troca ficava invisivel.
      //
      // Com o contador em 500 deixa de ficar: o ramo certo repoe a **1**, o
      // ramo do `<>` soma e da **501**. A propriedade que isto afirma e a que
      // o nome do criterio promete — «reinicio» — e nao «incremento».
      //
      // O estado `(usadas > 0, mes NULL)` nao nasce do nosso codigo, que
      // escreve sempre as duas colunas juntas; nasce de uma reposicao de copia
      // de seguranca ou de uma correccao a mao. E e precisamente onde um
      // contador que somasse em vez de repor passava despercebido.
      await semear(canalA, 500, null);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const contagem = await metering.contar(tenantA, pnidA);
      assert.equal(contagem?.usadas, 1);
      assert.equal(contagem?.reiniciou, true);
      assert.equal((await contadorCru(canalA)).usadas, 1);
    });

    it("o periodo que a base devolve e o da funcao da revisao 0007", async () => {
      // Sem segunda implementacao: pergunta-se a base o que ela conta, e
      // compara-se com o que o `SQL_ESTADO` devolveu. Se alguem reescrever a
      // fronteira em JavaScript, isto deixa de bater.
      await definirContexto(app, tenantA);
      const { rows } = await app.query<{ periodo: string }>(
        "SELECT platform.ten_periodo($1)::text AS periodo",
        [DEPOIS_DA_MEIA_NOITE.toISOString()],
      );
      assert.equal(rows[0]?.periodo, "2026-11-01");
      const pela = await app.query<{ mes: string }>(SQL_ESTADO, [
        tenantA,
        pnidA,
        DEPOIS_DA_MEIA_NOITE.toISOString(),
      ]);
      assert.equal(pela.rows[0]?.mes, "2026-11-01");
    });

    it("**o mes vem em texto e nao num `Date`** — e isto foi um defeito medido", async () => {
      // A primeira versao devolvia a coluna `date` tal e qual, e o driver `pg`
      // converte-a num `Date` a meia-noite **local do processo**. O
      // `toISOString().slice(0, 10)` que vinha a seguir dava `2026-10-31` em
      // qualquer processo com fuso a oeste de Greenwich — um dia de erro
      // exactamente na fronteira que o criterio 3 manda acertar, e invisivel no
      // CI, que corre em UTC.
      //
      // Esta asserção e o que impede a volta atras: um `Date` aqui falha o
      // `typeof`, e o formato fixa-se com a mascara e nao com o `DateStyle` da
      // sessao, que e um GUC e pode vir de fora.
      await semear(canalA, 0, null);
      const { metering } = meteringDe(tenantA, DEPOIS_DA_MEIA_NOITE);
      const contagem = await metering.contar(tenantA, pnidA);
      assert.equal(typeof contagem?.mes, "string");
      assert.match(String(contagem?.mes), /^\d{4}-\d{2}-\d{2}$/);
      assert.equal(contagem?.mes, "2026-11-01");
    });
  });

  // ------------------------------- o flanco sob concorrencia (criterio 3)

  describe("o flanco do aviso sob concorrencia (criterio 3)", () => {
    it("**dois incrementos em paralelo na travessia: +2 e UM aviso**", async () => {
      await semear(canalA, AVISO_EM - 1, "2026-10-01");
      const um = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app);
      const dois = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app2);
      // Duas ligacoes diferentes: e o que faz os dois `UPDATE` disputarem de
      // verdade em vez de sairem em serie pela mesma conexao.
      const [a, b] = await Promise.all([
        um.metering.contar(tenantA, pnidA),
        dois.metering.contar(tenantA, pnidA),
      ]);
      assert.equal((await contadorCru(canalA)).usadas, AVISO_EM + 1);
      const avisos = [a?.nivel, b?.nivel].filter((n) => n === "aviso");
      // **Um, e nao dois.** Com uma leitura previa em vez do `FOR UPDATE`, os
      // dois liam 799, os dois escreviam, e os dois concluiam «eu atravessei».
      assert.equal(avisos.length, 1, `niveis: ${JSON.stringify([a?.nivel, b?.nivel])}`);
      // E o outro nao atravessou nada.
      assert.deepEqual(
        [a?.nivel, b?.nivel].filter((n) => n !== null && n !== "aviso"),
        [],
      );
    });

    it("dez em paralelo somam dez, e o tecto da **um** esgotado", async () => {
      await semear(canalA, FREE_TIER_DE_SERVICE - 5, "2026-10-01");
      const clientes = [app, app2];
      const resultados = await Promise.all(
        Array.from({ length: 10 }, (_, n) =>
          meteringDe(
            tenantA,
            ANTES_DA_MEIA_NOITE,
            clientes[n % 2] ?? app,
          ).metering.contar(tenantA, pnidA),
        ),
      );
      assert.equal((await contadorCru(canalA)).usadas, FREE_TIER_DE_SERVICE + 5);
      const esgotados = resultados.filter((r) => r?.nivel === "esgotado");
      assert.equal(esgotados.length, 1, "o tecto foi atravessado mais de uma vez");
    });
  });

  // ----------------------------------- a idempotencia por wamid (criterio 2)

  describe("idempotencia por wamid (criterio 2)", () => {
    /** O adapter do KAM-015 ligado ao contador deste ticket. */
    function adapterLigado(metering: Metering): Saida {
      return new Saida({
        bd: bdDe(tenantA),
        meta: {
          enviar: async (phoneNumberId, para, corpo) => {
            const resposta = graph.responder({
              metodo: "POST",
              caminho: `/v23.0/${phoneNumberId}/messages`,
              consulta: {},
              corpo: { to: para.bsuid ?? para.telefone ?? "", tipo: corpo.tipo },
              cabecalhos: {},
            });
            if (resposta.estado !== 200 || resposta.corpo instanceof Uint8Array) {
              return {
                ok: false,
                codigo: 130429,
                estadoHttp: resposta.estado,
                esperar: null,
              };
            }
            const mensagens = resposta.corpo.messages as { id: string }[];
            return { ok: true, wamid: mensagens[0]?.id ?? "" };
          },
        },
        destinatario: async (): Promise<Destinatario> => ({
          bsuid: "AO.ENSAIOENSAIOENSAIO0001",
          telefone: null,
        }),
        guarda: async () => true,
        // **A porta que este ticket preenche.** Era `null` desde o KAM-015.
        freeTier: (t, p) => metering.estado(t, p),
        agora: () => new Date(),
        aleatorio: () => 0.5,
        dormir: async () => undefined,
        ambiente: {},
      });
    }

    function pedido(chave: string): Pedido {
      return {
        tenantId: tenantA,
        channelId: canalA,
        contactId: contactoA,
        conversationId: conversaA,
        phoneNumberId: pnidA,
        idempotencyKey: chave,
        corpo: TEXTO,
        doBot: true,
      };
    }

    it("**tres `delivered` do mesmo wamid: contador +1**", async () => {
      await semear(canalA, 0, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const saida = adapterLigado(metering);

      const enviado = await saida.enviar(pedido(`idem-${Date.now()}`));
      assert.equal(enviado.ok, true);
      const wamid = enviado.ok ? enviado.wamid : null;
      assert.ok(wamid !== null && wamid !== "", "o envio nao devolveu wamid");

      // É assim que um serviço liga as duas metades: o adapter diz se **esta**
      // chegada entregou, e quem conta só conta então. O `pricing.category` vem
      // do próprio `statuses` e quem chama já o tem na mão.
      let contadas = 0;
      for (let n = 0; n < 3; n += 1) {
        const p = pricing();
        const r = await saida.ingerir(tenantA, wamid, "delivered", p, pnidA);
        if (r.entregou && p.category === "service") {
          await metering.contar(tenantA, pnidA);
          contadas += 1;
        }
      }
      // Uma, e nao tres: a segunda e a terceira chegadas nao avancam nada, e e
      // a base que o decide.
      assert.equal(contadas, 1);
      assert.equal((await contadorCru(canalA)).usadas, 1);
    });

    it("um `failed` depois de um `delivered` nao desconta nem volta a contar", async () => {
      await semear(canalA, 0, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const saida = adapterLigado(metering);
      const enviado = await saida.enviar(pedido(`idem-f-${Date.now()}`));
      const wamid = enviado.ok ? enviado.wamid : null;
      assert.ok(wamid !== null && wamid !== "", "o envio nao devolveu wamid");

      const entrega = await saida.ingerir(tenantA, wamid, "delivered", pricing(), pnidA);
      assert.equal(entrega.entregou, true);
      await metering.contar(tenantA, pnidA);

      const falha = await saida.ingerir(tenantA, wamid, "failed", pricing(), pnidA);
      // Avancou (o `failed` e terminal e vem de um nao-terminal), mas nao
      // entregou — logo nao conta. E o contador nao desce: o *free tier* conta
      // entregas feitas, e a Meta nao as devolve.
      assert.equal(falha.avancou, true);
      assert.equal(falha.entregou, false);
      assert.equal((await contadorCru(canalA)).usadas, 1);
    });
  });

  // ------------------------------------ isolamento (X-03 sobre o contador)

  describe("isolamento (Testes Requeridos: contadores de A nao afectam B)", () => {
    it("**com o contexto de A, o contador de B nao se le**", async () => {
      await semear(canalA, 10, "2026-10-01");
      await semear(canalB, 777, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);

      // A metade positiva primeiro: «A nao ve B» prova-se trivialmente com uma
      // base vazia. A regra e a do `docs/isolamento.md`.
      assert.equal((await metering.estado(tenantA, pnidA)).usadas, 10);

      // E agora o numero de B, pedido com o contexto de A e pelo numero dele:
      // zero linhas, que o modulo traduz no tecto — e **nao** em 777.
      const deB = await metering.estado(tenantA, pnidB);
      assert.equal(deB.usadas, FREE_TIER_DE_SERVICE);
      assert.notEqual(deB.usadas, 777);
    });

    it("**com o contexto de A, o contador de B nao se escreve**", async () => {
      await semear(canalB, 777, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      // Zero linhas: o `UPDATE` nao encontrou a linha de B, porque a politica
      // `tenant_iso` a esconde do contexto de A.
      assert.equal(await metering.contar(tenantA, pnidB), null);
      // E a linha de B ficou intacta, lida por quem a pode ler.
      assert.equal((await contadorCru(canalB)).usadas, 777);
    });

    it("e e simetrico: B tambem nao mexe no de A", async () => {
      // Uma politica que so funcionasse num sentido passava acima.
      await semear(canalA, 10, "2026-10-01");
      const { metering } = meteringDe(tenantB, ANTES_DA_MEIA_NOITE);
      assert.equal(await metering.contar(tenantB, pnidA), null);
      assert.equal((await contadorCru(canalA)).usadas, 10);
    });
  });

  // ---------------------------- a janela de falhas e a reconciliacao

  describe("a janela de falhas e a reconciliacao (criterios 5 e 7)", () => {
    /** Insere uma mensagem já num estado, com `pricing`, como administrador. */
    async function mensagem(
      estado: string,
      com: { readonly pricing?: Pricing | null; readonly entregueEm?: string } = {},
    ): Promise<void> {
      const temPricing = com.pricing !== undefined && com.pricing !== null;
      await admin.query(
        "INSERT INTO platform.outbound_messages " +
          "(tenant_id, channel_id, contact_id, conversation_id, idempotency_key, " +
          " kind, state, wamid, pricing, delivered_at) " +
          "VALUES ($1, $2, $3, $4, $5, 'service', $6, $7, $8::jsonb, $9)",
        [
          tenantA,
          canalA,
          contactoA,
          conversaA,
          `janela-${Math.random().toString(36).slice(2)}`,
          estado,
          `wamid.J${Math.random().toString(36).slice(2)}`,
          temPricing ? JSON.stringify(com.pricing) : null,
          com.entregueEm ?? null,
        ],
      );
    }

    async function limpar(): Promise<void> {
      await admin.query("DELETE FROM platform.outbound_messages WHERE tenant_id = $1", [
        tenantA,
      ]);
    }

    it("**a janela ignora o que ainda nao tem destino**", async () => {
      await limpar();
      await semear(canalA, 1200, "2026-10-01");
      // Quatro falhas e dezesseis entregues: 20 na janela, 20% de falhas.
      for (let n = 0; n < 4; n += 1) await mensagem("failed");
      for (let n = 0; n < 16; n += 1) {
        await mensagem("delivered", { pricing: pricing(), entregueEm: "2026-10-15" });
      }
      // E mais vinte em `queued`, que **nao** contam. Incluí-las diluía a taxa
      // exactamente no momento em que ela importa: 4 em 40 são 10%, abaixo do
      // limiar, e a suspeita desaparecia.
      for (let n = 0; n < 20; n += 1) await mensagem("queued");
      const { metering, metricas } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.equal(await metering.suspeita(tenantA, pnidA), true);
      assert.equal(metricas.ler()["meta_payment_suspect_total"], 1);
    });

    it("abaixo do tecto a mesma janela nao e suspeita", async () => {
      await limpar();
      await semear(canalA, 999, "2026-10-01");
      for (let n = 0; n < 10; n += 1) await mensagem("failed");
      for (let n = 0; n < 10; n += 1) await mensagem("delivered");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.equal(await metering.suspeita(tenantA, pnidA), false);
    });

    it("a janela de A nao conta as mensagens de B", async () => {
      await limpar();
      await semear(canalA, 1200, "2026-10-01");
      // A junção leva `tenant_id` nos dois lados; sem isso uma mensagem de A
      // podia casar com um canal de B e o número que saía era a soma dos dois.
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.equal(await metering.suspeita(tenantA, pnidA), false);
    });

    it("**a reconciliacao le o `pricing` jsonb e mede as duas divergencias**", async () => {
      await limpar();
      await semear(canalA, 12, "2026-10-01");
      // Doze entregas de `service`, das quais duas `billable` — como se o tecto
      // estivesse em dez. O que se mede e a mecanica, nao os mil.
      for (let n = 0; n < 10; n += 1) {
        await mensagem("delivered", {
          pricing: pricing({ billable: false }),
          entregueEm: "2026-10-15T10:00:00Z",
        });
      }
      for (let n = 0; n < 2; n += 1) {
        await mensagem("delivered", {
          pricing: pricing(),
          entregueEm: "2026-10-15T10:00:00Z",
        });
      }
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const r = await metering.reconciliar(tenantA, pnidA);
      assert.ok(r !== null);
      assert.equal(r.contador, 12);
      assert.equal(r.entregues, 12);
      assert.equal(r.facturaveis, 2);
      // A contagem bate: contamos as doze que o `pricing` testemunha.
      assert.equal(r.divergenciaDaContagem, 0);
      // E o facturavel nao, porque o tecto real e mil e o contador esta em
      // doze: a nossa regra estima zero facturaveis. **E isso e informacao, nao
      // um defeito** — e a divergencia que o critario 7 manda registar.
      assert.equal(r.estimadasFacturaveis, 0);
      assert.equal(r.divergenciaDoFacturavel, 1);
    });

    it("**uma entrega de outro mes nao entra, e a fronteira e a de Luanda**", async () => {
      // Este caso veio da **revisao adversarial**. A primeira versao recebia o
      // periodo por parametro, em instantes, e tinha dois defeitos: comparava o
      // contador do mes corrente com as entregas de um mes que lhe pedissem, e
      // as fronteiras vinham em UTC — o que perde a ultima hora do mes de
      // `Africa/Luanda` e ganha a primeira do seguinte.
      //
      // As duas entregas abaixo estao a **uma hora** de distancia e caem em
      // meses diferentes **em Luanda**; em UTC caem as duas em Outubro. So uma
      // delas pode contar para o periodo de Outubro.
      await limpar();
      await semear(canalA, 1, "2026-10-01");
      await mensagem("delivered", {
        pricing: pricing(),
        entregueEm: "2026-10-31T22:30:00Z", // 23:30 de 31 de Outubro em Luanda
      });
      await mensagem("delivered", {
        pricing: pricing(),
        entregueEm: "2026-10-31T23:30:00Z", // 00:30 de 1 de Novembro em Luanda
      });
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const r = await metering.reconciliar(tenantA, pnidA);
      // **Uma, e nao duas.** Com fronteiras em UTC seriam duas, e a
      // reconciliacao de 2% nao distingue esse erro de ruido.
      assert.equal(r?.entregues, 1);
      assert.equal(r?.contador, 1);
      assert.equal(r?.divergenciaDaContagem, 0);
    });

    it("um periodo sem entregas devolve divergencia `null` e nao `Infinity`", async () => {
      await limpar();
      await semear(canalA, 0, "2026-10-01");
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const r = await metering.reconciliar(tenantA, pnidA);
      assert.equal(r?.divergenciaDaContagem, null);
      assert.equal(r?.divergenciaDoFacturavel, null);
    });
  });

  // --------------------- a marca de restricao (criterios 5 e 6, revisao 0013)

  describe("a marca de restricao (criterios 5 e 6)", () => {
    /** O motivo e o conjunto de codigos, lidos pelo administrador. */
    async function marcaCrua(
      canal: string,
    ): Promise<{ motivo: string | null; codigos: readonly number[] }> {
      const { rows } = await admin.query<{
        motivo: string | null;
        codigos: readonly number[] | null;
      }>(
        "SELECT motivo_restricao AS motivo, meta_error_codes_seen AS codigos " +
          "FROM platform.tenant_channels WHERE id = $1",
        [canal],
      );
      const linha = rows[0];
      return { motivo: linha?.motivo ?? null, codigos: linha?.codigos ?? [] };
    }

    /** Quantos `channel.updated` estao no outbox deste tenant. */
    async function eventosDe(tenant: string): Promise<number> {
      const { rows } = await admin.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.events_outbox " +
          "WHERE tenant_id = $1 AND tipo = 'channel.updated'",
        [tenant],
      );
      return Number(rows[0]?.n ?? -1);
    }

    async function limparMarca(canal: string): Promise<void> {
      await admin.query(
        "UPDATE platform.tenant_channels SET motivo_restricao = NULL, " +
          "meta_error_codes_seen = '{}' WHERE id = $1",
        [canal],
      );
    }

    async function limparEventos(tenant: string): Promise<void> {
      await admin.query("DELETE FROM platform.events_outbox WHERE tenant_id = $1", [
        tenant,
      ]);
      await admin.query("DELETE FROM platform.evt_agregado_seq WHERE tenant_id = $1", [
        tenant,
      ]);
    }

    it("**marca, guarda o codigo, e o `channel.updated` cai no outbox**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      const r = await metering.marcarRestricao(tenantA, pnidA, "payment_method", 131049);
      assert.equal(r?.marcou, true);
      assert.ok(r?.eventoId !== null && r?.eventoId !== undefined);

      const cru = await marcaCrua(canalA);
      assert.equal(cru.motivo, "payment_method");
      assert.deepEqual([...cru.codigos], [131049]);
      // O envelope constroi-se em SQL, dentro do `evt_emitir`: isto afirma que
      // ele **chegou** ao outbox, que e o que o publicador le.
      assert.equal(await eventosDe(tenantA), 1);
    });

    it("**uma segunda marca nao emite outro evento**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", 131049);
      const segunda = await metering.marcarRestricao(
        tenantA,
        pnidA,
        "payment_method",
        130429,
      );
      // Um evento por mensagem falhada e o contrario de um alerta.
      assert.equal(segunda?.marcou, false);
      assert.equal(segunda?.eventoId, null);
      assert.equal(await eventosDe(tenantA), 1);
      // Mas o conjunto **cresceu**: a marca nao muda, os codigos acumulam-se, e
      // e isso que o criterio 5 quer para calibrar a heuristica.
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], [131049, 130429]);
    });

    it("**um motivo diferente nao sobrepoe o primeiro**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", null);
      const outra = await metering.marcarRestricao(tenantA, pnidA, "quality", null);
      // O `COALESCE` e o que faz a **primeira** marca ser a que fica. Sem ele, a
      // qualidade apagava a suspeita de pagamento e o dono recebia o aviso
      // errado.
      assert.equal(outra?.marcou, false);
      assert.equal((await marcaCrua(canalA)).motivo, "payment_method");
    });

    it("o mesmo codigo duas vezes entra **uma**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", 131049);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", 131049);
      // E um conjunto, nao uma lista: sem o `<> ALL`, o mesmo codigo entrava uma
      // vez por mensagem e batia no tecto de trinta e dois.
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], [131049]);
    });

    it("**um statuses sem codigo nao mete `NULL` no conjunto**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", null);
      // `array_append(a, NULL)` acrescenta um `NULL` — nao e um `no-op`. Sem o
      // `CASE`, o conjunto enchia-se de `NULL` ate o `CHECK` recusar a escrita.
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], []);
    });

    it("**duas marcas em paralelo: um evento e nao dois**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const um = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app);
      const dois = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app2);
      const [a, b] = await Promise.all([
        um.metering.marcarRestricao(tenantA, pnidA, "payment_method", 131049),
        dois.metering.marcarRestricao(tenantA, pnidA, "payment_method", 130429),
      ]);
      // E o `FOR UPDATE` da subconsulta que faz o segundo processo reler o que o
      // primeiro escreveu: so um ve `NULL` no `antes`, e so esse emite.
      assert.equal([a?.marcou, b?.marcou].filter(Boolean).length, 1);
      assert.equal(await eventosDe(tenantA), 1);
    });

    /**
     * **Espera que alguém esteja mesmo a bloquear no trinco da linha.**
     *
     * Não afirma nada: é melhor-esforço. O `UPDATE` exterior toma o trinco da
     * linha nos **dois** mundos — com e sem o `FOR UPDATE` da subconsulta —,
     * pelo que esperar por ele não depende da mutação; e se o trinco não
     * aparecer, o teste segue e são as asserções que decidem. Assim isto não
     * pode tornar o teste vermelho por si.
     */
    async function esperarPeloTrinco(limiteMs = 5_000): Promise<void> {
      const fim = Date.now() + limiteMs;
      while (Date.now() < fim) {
        const { rows } = await admin.query<{ n: number }>(
          "SELECT count(*)::int AS n FROM pg_stat_activity " +
            " WHERE wait_event_type = 'Lock' AND query ILIKE '%tenant_channels%'",
        );
        if ((rows[0]?.n ?? 0) > 0) return;
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    }

    /**
     * **O entrelaçamento imposto**, que é o que o teste de cima não faz.
     *
     * O `Promise.all` de duas instruções em **autocommit** pode não se sobrepor
     * dentro do servidor. Quando não se sobrepõem, a segunda lê o
     * `motivo_restricao` **já confirmado** no seu próprio instantâneo, devolve
     * `marcou: false`, e é a mesma resposta que o original dá — o teste passa e
     * a mutação sobrevive. Foi o que aconteceu na noite de 2026-10-26 à
     * `restricao: a marca perde o FOR UPDATE e o evento sai duas vezes`.
     *
     * Aqui a primeira marca fica numa transacção **aberta**, e a segunda tem de
     * esperar pelo trinco. Depois do `COMMIT`: com `FOR UPDATE` a subconsulta
     * relê a versão nova e vê o motivo posto, logo não emite; sem ele, o `antes`
     * ficou do instantâneo antigo, vê `NULL`, e sai um **segundo** evento.
     *
     * E afirma-se o segundo observável, que o teste de cima não tinha: o
     * `meta_error_codes_seen` com os **dois** códigos. Sem o `FOR UPDATE` as
     * duas leem `{}` e a última escrita deixa **um** só. É o que distingue esta
     * mutação da sua irmã do `SQL_CONTAR`, que morre por o seu teste afirmar
     * também o valor da coluna.
     */
    it("**duas marcas entrelacadas a forca: um evento, e os dois codigos**", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const um = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app);
      const dois = meteringDe(tenantA, ANTES_DA_MEIA_NOITE, app2);
      try {
        await app.query("BEGIN");
        const primeira = await um.metering.marcarRestricao(
          tenantA,
          pnidA,
          "payment_method",
          131049,
        );
        // O canário: sem isto, uma primeira marca que não passasse deixava a
        // segunda a ser a única — e `marcou: true` nela seria o esperado.
        assert.equal(primeira?.marcou, true, "a primeira marca nao passou");

        const segunda = dois.metering.marcarRestricao(
          tenantA,
          pnidA,
          "payment_method",
          130429,
        );
        await esperarPeloTrinco();
        await app.query("COMMIT");
        const b = await segunda;

        assert.equal(b?.marcou, false, "a segunda marca emitiu um segundo evento");
        assert.equal(await eventosDe(tenantA), 1);
        assert.deepEqual(
          [...(await marcaCrua(canalA)).codigos].sort((x, y) => x - y),
          [130429, 131049],
          "a escrita perdida comeu um dos codigos",
        );
      } finally {
        // Uma asserção que falhe antes do `COMMIT` deixava a transacção aberta e
        // o trinco da linha preso para tudo o que corre depois.
        await app.query("ROLLBACK").catch(() => {});
      }
    });

    it("**levantar exige o motivo certo**, e emite", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await metering.marcarRestricao(tenantA, pnidA, "payment_method", null);

      // Um canal restrito por qualidade continua a entregar mensagens: uma
      // entrega nao e prova de que a qualidade melhorou, e limpar a marca de
      // outro ticket ao passar era apagar uma decisao que nao e nossa.
      assert.equal(await metering.levantarRestricao(tenantA, pnidA, "quality"), false);
      assert.equal((await marcaCrua(canalA)).motivo, "payment_method");
      assert.equal(await eventosDe(tenantA), 1);

      assert.equal(
        await metering.levantarRestricao(tenantA, pnidA, "payment_method"),
        true,
      );
      assert.equal((await marcaCrua(canalA)).motivo, null);
      assert.equal(await eventosDe(tenantA), 2);
      // Os codigos **ficam**: sao diagnostico, nao parte da restricao.
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], []);
    });

    it("levantar um canal sem marca nao emite nada", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      assert.equal(
        await metering.levantarRestricao(tenantA, pnidA, "payment_method"),
        false,
      );
      assert.equal(await eventosDe(tenantA), 0);
    });

    it("**com o contexto de A, o canal de B nao se marca** (X-03)", async () => {
      await limparMarca(canalB);
      const { metering } = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      // Zero linhas: a politica `tenant_iso` esconde a linha de B do contexto
      // de A, e o `UPDATE` nao encontra nada para marcar.
      assert.equal(
        await metering.marcarRestricao(tenantA, pnidB, "payment_method", 131049),
        null,
      );
      const cru = await marcaCrua(canalB);
      assert.equal(cru.motivo, null);
      assert.deepEqual([...cru.codigos], []);
    });

    it("e os codigos de A nao se veem com o contexto de B (X-03)", async () => {
      await limparMarca(canalA);
      await limparEventos(tenantA);
      const deA = meteringDe(tenantA, ANTES_DA_MEIA_NOITE);
      await deA.metering.marcarRestricao(tenantA, pnidA, "payment_method", 2593109);
      // A metade positiva primeiro, pela regra do `docs/isolamento.md`.
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], [2593109]);
      // E agora com o contexto de B, pelo numero de A: nada.
      const deB = meteringDe(tenantB, ANTES_DA_MEIA_NOITE);
      assert.equal(await deB.metering.marcarRestricao(tenantB, pnidA, "quality", 1), null);
      assert.equal((await marcaCrua(canalA)).motivo, "payment_method");
      assert.deepEqual([...(await marcaCrua(canalA)).codigos], [2593109]);
    });
  });

});

/**
 * A saída de canal contra um PostgreSQL real (KAM-015).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **A idempotência é da base.** Duas chamadas com a mesma
 *    `idempotency_key` deixam **uma** linha e fazem **uma** chamada HTTP — e a
 *    segunda parte conta-se no registo do `GraphFalso` do KAM-024. Uma base
 *    falsa devolve o que se lhe mandou devolver, e um teste de unicidade sobre
 *    ela prova que o teste sabe contar.
 * 2. **A unicidade é por *tenant*.** Dois *tenants* com a mesma chave ficam com
 *    **duas** linhas, e é esta asserção que distingue a divergência 2 da emenda
 *    1.21 de um `UNIQUE` global — com unicidade global, o segundo *tenant* era
 *    deduplicado em silêncio.
 * 3. **A monotonia sobrevive à concorrência.** Dois `statuses` da mesma
 *    mensagem em paralelo: o estado final é o maior dos dois, e o custo conta
 *    **uma** vez. Só a base os serializa.
 * 4. **A RLS recusa o que o código deixaria passar.** Com o contexto de A, uma
 *    escrita na linha de B não acontece — e com `FORCE`, nem como dono.
 * 5. **O `pricing` fica guardado por mensagem**, e é dele que o
 *    `SQL_CUSTO_DO_TENANT` tira o custo por *tenant* — que é o que substitui a
 *    etiqueta `{tenant}` que as bibliotecas de métricas recusam.
 *
 * O que **não** se mede aqui: a matriz de decisão, a monotonia célula a célula
 * e a aritmética do custo vivem nas baterias do gate 4
 * (`packages/core-ts/tests/outbound.*.test.ts`), porque são funções puras e uma
 * base real não acrescenta nada à prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  GraphFalso,
  Gerador as GeradorDeFixtures,
} from "@kamba/meta-sim";

import {
  SQL_CUSTO_DO_TENANT,
  Saida,
  type Corpo,
  type Destinatario,
  type Pedido,
  type Pricing,
} from "../src/outbound/index.ts";
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
 * `set_config(..., false)` e não `true`: ver a nota no `bd.query` do
 * `adapterDe`. Uma função e não a cadeia repetida, porque a diferença entre os
 * dois terceiros argumentos é invisível e custa um teste inteiro a descobrir.
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

describe("a saida de canal contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a concorrencia do
  // criterio 3 so e real com duas sessoes. Com uma, os dois `UPDATE` saem em
  // serie pela mesma conexao e o teste prova que o JavaScript e sequencial.
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let canalA = "";
  let canalB = "";
  let pnidA = "";
  let conversaA = "";
  let conversaB = "";
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
   * O adapter de um *tenant*, sobre a ligação dada.
   *
   * A ligação é parâmetro para que o teste de concorrência possa dar-lhe a
   * segunda: com uma só, os dois `UPDATE` saem em série pela mesma conexão e o
   * teste provava que o JavaScript é sequencial, não que a base serializa.
   */
  function adapterDe(tenant: string, cliente: pg.Client = app): Saida {
    return new Saida({
      bd: {
        query: async (texto, valores) => {
          // `false` e **nao** `true`: o terceiro argumento do `set_config` e
          // «local a transaccao», e fora de um `BEGIN` explicito cada
          // instrucao e a sua propria transaccao — a definicao desaparecia
          // antes da instrucao seguinte, e com RLS `FORCE` o `kamba_app`
          // ficava sem contexto e via zero linhas. O
          // `identity.bd.test.ts` usa `true` **dentro** de `BEGIN`/`ROLLBACK`;
          // aqui a definicao e de sessao, que e o que serve uma ligacao
          // dedicada a um tenant — e no teste de concorrencia e melhor do que
          // uma transaccao, porque as duas ligacoes disputam de verdade.
          await definirContexto(cliente, tenant);
          return cliente.query(texto, valores === undefined ? [] : [...valores]);
        },
      },
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
            return { ok: false, codigo: 130429, estadoHttp: resposta.estado, esperar: null };
          }
          const mensagens = resposta.corpo.messages as { id: string }[];
          return { ok: true, wamid: mensagens[0]?.id ?? "" };
        },
      },
      // O destinatário entra por **porta**: só `kamba_identity` lê
      // `contact_endpoints`, e o adapter corre como `kamba_app`.
      destinatario: async (): Promise<Destinatario> => ({
        bsuid: "AO.ENSAIOENSAIOENSAIO0001",
        telefone: null,
      }),
      // O guarda do KAM-018 não existe; aqui passa-se um que deixa passar, para
      // medir o que é deste ticket. A **ausência** de guarda tem o seu próprio
      // teste no gate 4.
      guarda: async () => true,
      freeTier: null,
      agora: () => new Date(),
      aleatorio: () => 0.5,
      dormir: async () => undefined,
      ambiente: {},
    });
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

    tenantA = await criarTenant(admin, "saida-a");
    tenantB = await criarTenant(admin, "saida-b");
    const canalDeA = await criarCanal(admin, tenantA);
    const canalDeB = await criarCanal(admin, tenantB);
    canalA = canalDeA.id;
    canalB = canalDeB.id;
    pnidA = canalDeA.phoneNumberId;
    const a = (await abrirConversa(tenantA, canalA)).split("|");
    const b = (await abrirConversa(tenantB, canalB)).split("|");
    conversaA = a[0] ?? "";
    conversaB = b[0] ?? "";
    graph = new GraphFalso(new GeradorDeFixtures("outbound-bd"));
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

  function pedido(tenant: string, canal: string, conversa: string, chave: string): Pedido {
    return {
      tenantId: tenant,
      channelId: canal,
      contactId: "",
      conversationId: conversa,
      phoneNumberId: pnidA,
      idempotencyKey: chave,
      corpo: TEXTO,
      doBot: true,
    };
  }

  describe("idempotencia (criterio 2)", () => {
    it("**duas chamadas com a mesma chave: 1 linha e 1 chamada HTTP**", async () => {
      const contacto = await admin.query<{ contact_id: string }>(
        "SELECT contact_id FROM platform.contacts WHERE tenant_id = $1 LIMIT 1",
        [tenantA],
      );
      const base = {
        ...pedido(tenantA, canalA, conversaA, "chave-idem-1"),
        contactId: contacto.rows[0]?.contact_id ?? "",
      };
      const adapter = adapterDe(tenantA);
      const antes = graph.envios;

      const primeira = await adapter.enviar(base);
      const segunda = await adapter.enviar(base);

      assert.equal(primeira.ok, true);
      assert.equal(segunda.ok, true);
      assert.equal(segunda.ok && segunda.repetido, true, "a segunda sabe que repetiu");
      assert.equal(primeira.ok && primeira.repetido, false);

      // **Uma** chamada HTTP, contada pelo servidor falso. E a metade do
      // criterio que uma base falsa nao consegue provar.
      assert.equal(graph.envios - antes, 1, "a segunda nao chamou a Meta");

      await definirContexto(app, tenantA);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*) AS n FROM platform.outbound_messages WHERE idempotency_key = $1",
        ["chave-idem-1"],
      );
      assert.equal(linhas.rows[0]?.n, "1", "uma linha, pela UNIQUE");
    });

    it("**a mesma chave em dois tenants da duas linhas**", async () => {
      // A divergencia 2 da emenda 1.21: com `UNIQUE` global, o segundo tenant
      // era deduplicado em silencio e o `INSERT` falhava sobre uma linha que
      // ele nao pode ver. Um tenant suprimia mensagens de outro adivinhando a
      // chave.
      const chave = "chave-partilhada";
      for (const [tenant, canal, conversa] of [
        [tenantA, canalA, conversaA],
        [tenantB, canalB, conversaB],
      ] as const) {
        const contacto = await admin.query<{ contact_id: string }>(
          "SELECT contact_id FROM platform.contacts WHERE tenant_id = $1 LIMIT 1",
          [tenant],
        );
        const resultado = await adapterDe(tenant).enviar({
          ...pedido(tenant, canal, conversa, chave),
          contactId: contacto.rows[0]?.contact_id ?? "",
        });
        assert.equal(resultado.ok, true, tenant);
        assert.equal(resultado.ok && resultado.repetido, false, `${tenant} nao e repeticao`);
      }

      const total = await admin.query<{ n: string }>(
        "SELECT count(*) AS n FROM platform.outbound_messages WHERE idempotency_key = $1",
        [chave],
      );
      assert.equal(total.rows[0]?.n, "2", "duas linhas, uma por tenant");
    });
  });

  describe("monotonia contra concorrencia (criterio 3)", () => {
    it("dois statuses em paralelo: o estado final e o maior, e o custo conta uma vez", async () => {
      const contacto = await admin.query<{ contact_id: string }>(
        "SELECT contact_id FROM platform.contacts WHERE tenant_id = $1 LIMIT 1",
        [tenantA],
      );
      const adapter = adapterDe(tenantA);
      const resultado = await adapter.enviar({
        ...pedido(tenantA, canalA, conversaA, "chave-monotonia"),
        contactId: contacto.rows[0]?.contact_id ?? "",
      });
      assert.equal(resultado.ok, true);
      const wamid = resultado.ok ? (resultado.wamid ?? "") : "";
      assert.notEqual(wamid, "");

      // **`delivered` e `read` ao mesmo tempo, em duas ligações**, e o par é o
      // ponto.
      //
      // A primeira versão deste teste usava `delivered` e `sent`, e isso não
      // provava nada sobre o custo: partindo de `sent`, um `sent` é *no-op*
      // (`para <= de`), logo custa zero **por construção** — o par não podia
      // duplicar com defeito nenhum. Foi a revisão adversarial que o apanhou, e
      // o defeito que estava por baixo era real: os dois `statuses` liam
      // `sent`, os dois concluíam «houve entrega» e os dois somavam 4 000.
      //
      // `delivered` e `read` são o par que a Meta produz — ela não garante
      // ordem nos `statuses` (`E1` §5) — e **ambos avançam** a partir de
      // `sent`, e ambos atravessam a entrega. Só a base os serializa: com uma
      // ligação, os dois `UPDATE` saem em série e o teste provava que o
      // JavaScript é sequencial.
      const ingestoes = await Promise.all([
        adapterDe(tenantA, app).ingerir(tenantA, wamid, "delivered", pricing(), pnidA),
        adapterDe(tenantA, app2).ingerir(tenantA, wamid, "read", pricing(), pnidA),
      ]);

      await definirContexto(app, tenantA);
      const linha = await app.query<{ state: string; pricing: Pricing | null }>(
        "SELECT state, pricing FROM platform.outbound_messages WHERE wamid = $1",
        [wamid],
      );
      // O maior dos dois ganha a ordem, qualquer que seja a de chegada.
      assert.equal(linha.rows[0]?.state, "read", "o `delivered` nao fez recuar o `read`");
      // **O custo conta uma vez**, e e aqui que a dupla contagem aparecia: a
      // soma das duas ingestoes tem de ser de **uma** entrega, nao de duas.
      const somado = ingestoes.reduce((total, uma) => total + uma.microUsd, 0);
      assert.equal(somado, 4000, `somou ${somado} micro-USD: a entrega contou duas vezes`);
      // E as duas avancaram — nenhuma foi recusada pela base. Se uma tivesse
      // sido, o `4000` sairia de uma so e o teste passava sem ter havido
      // corrida nenhuma.
      assert.deepEqual(
        ingestoes.map((uma) => uma.avancou),
        [true, true],
        "as duas tinham de avancar, senao nao houve corrida",
      );
      // E o `pricing` ficou guardado por mensagem (criterio 4).
      assert.equal(linha.rows[0]?.pricing?.category, "service");
    });

    it("um failed depois de delivered fica failed, e nao conta custo", async () => {
      const contacto = await admin.query<{ contact_id: string }>(
        "SELECT contact_id FROM platform.contacts WHERE tenant_id = $1 LIMIT 1",
        [tenantA],
      );
      const adapter = adapterDe(tenantA);
      const resultado = await adapter.enviar({
        ...pedido(tenantA, canalA, conversaA, "chave-falha"),
        contactId: contacto.rows[0]?.contact_id ?? "",
      });
      const wamid = resultado.ok ? (resultado.wamid ?? "") : "";
      await adapter.ingerir(tenantA, wamid, "delivered", pricing(), pnidA);
      const falha = await adapter.ingerir(tenantA, wamid, "failed", null, pnidA);
      assert.equal(falha.microUsd, 0, "um failed nao custa");

      await definirContexto(app, tenantA);
      const linha = await app.query<{ state: string; delivered_at: Date | null }>(
        "SELECT state, delivered_at FROM platform.outbound_messages WHERE wamid = $1",
        [wamid],
      );
      assert.equal(linha.rows[0]?.state, "failed");
      // **O `delivered_at` sobrevive ao `failed`**, e e esta assercao que
      // prende a correccao da `outbound_messages_entrega_ck`: a primeira
      // versao da constraint so admitia `delivered` e `read`, e este `UPDATE`
      // morria com `23514`. A entrega aconteceu, o custo ja foi contado, e
      // apagar o instante era destruir a linha de auditoria que reconcilia a
      // factura.
      assert.notEqual(
        linha.rows[0]?.delivered_at ?? null,
        null,
        "a entrega aconteceu: o instante nao se apaga porque falhou depois",
      );

      // E de `failed` nao se sai.
      const depois = await adapter.ingerir(tenantA, wamid, "read", pricing(), pnidA);
      assert.equal(depois.avancou, false);
    });
  });

  describe("isolamento (Testes Requeridos: X-03 sobre outbound_messages)", () => {
    it("com o contexto de A, as linhas de B nao aparecem", async () => {
      await definirContexto(app, tenantA);
      const vistas = await app.query<{ tenant_id: string }>(
        "SELECT DISTINCT tenant_id FROM platform.outbound_messages",
      );
      // A metade positiva primeiro: A **ve** as suas. Sem ela, uma base vazia
      // provava tudo.
      assert.ok(vistas.rows.length >= 1, "A ve as suas linhas");
      for (const linha of vistas.rows) {
        assert.equal(linha.tenant_id, tenantA, "nao ha linhas de B a vista");
      }
    });

    it("com o contexto de A, uma escrita na linha de B nao acontece", async () => {
      const deB = await admin.query<{ id: string }>(
        "SELECT id FROM platform.outbound_messages WHERE tenant_id = $1 LIMIT 1",
        [tenantB],
      );
      const id = deB.rows[0]?.id ?? "";
      assert.notEqual(id, "", "B tem pelo menos uma linha");

      await definirContexto(app, tenantA);
      const mexeu = await app.query(
        "UPDATE platform.outbound_messages SET state = 'failed' WHERE id = $1 RETURNING id",
        [id],
      );
      assert.equal(mexeu.rows.length, 0, "a politica recusou a escrita cruzada");

      // E a linha de B continua no estado em que estava.
      const depois = await admin.query<{ state: string }>(
        "SELECT state FROM platform.outbound_messages WHERE id = $1",
        [id],
      );
      assert.notEqual(depois.rows[0]?.state, "failed");
    });

    it("os templates de A nao se veem com o contexto de B", async () => {
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) " +
          "VALUES ($1, 'so_de_a', 'pt_PT', 'utility', 'approved', 'resumo')",
        [tenantA],
      );
      await definirContexto(app, tenantB);
      const vistos = await app.query(
        "SELECT name FROM platform.message_templates WHERE name = 'so_de_a'",
      );
      assert.equal(vistos.rows.length, 0);
    });
  });

  describe("o custo por tenant sai da tabela (DoD «Custo e observabilidade»)", () => {
    it("o SQL_CUSTO_DO_TENANT soma o pricing das entregues", async () => {
      // **E esta consulta que substitui a etiqueta `{tenant}`** da metrica: as
      // bibliotecas recusam por gramatica uma etiqueta que nao case
      // `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` e um UUID com hifenes. O §16
      // do doc 01 ja apontava este caminho.
      await definirContexto(app, tenantA);
      const custo = await app.query<{ micro_usd: string; entregues: string }>(
        SQL_CUSTO_DO_TENANT,
        [tenantA, new Date("2026-01-01T00:00:00Z"), new Date("2099-01-01T00:00:00Z")],
      );
      const microUsd = Number(custo.rows[0]?.micro_usd ?? "0");
      const entregues = Number(custo.rows[0]?.entregues ?? "0");
      assert.ok(entregues >= 1, `${entregues} entregues`);
      // Cada entrega de `service` vale 4 000 micro-dolares, inteiros.
      assert.equal(microUsd, entregues * 4000);
      assert.ok(Number.isInteger(microUsd), "o custo e inteiro");
    });

    it("o custo de A nao inclui o de B — a RLS tambem protege a consulta", async () => {
      // **Com o contexto de B, pede-se o custo de A.** A primeira versão deste
      // teste pedia o custo de **B** com o contexto de B e exigia zero — e esse
      // zero vinha do `WHERE tenant_id = $1` do próprio SQL e do facto de B
      // nunca ter ingerido um `delivered`, não de política nenhuma: o resultado
      // era idêntico com a RLS ligada ou desligada. Foi a revisão adversarial
      // que o apanhou.
      //
      // Assim a asserção só pode vir da RLS: o `$1` **é** o tenant de A, há
      // linhas de A entregues com `pricing`, e o que as esconde é a política
      // `tenant_iso` sobre a sessão de B.
      const DESDE = new Date("2026-01-01T00:00:00Z");
      const ATE = new Date("2099-01-01T00:00:00Z");
      await definirContexto(app, tenantB);
      const deA = await app.query<{ micro_usd: string; entregues: string }>(
        SQL_CUSTO_DO_TENANT,
        [tenantA, DESDE, ATE],
      );
      assert.equal(deA.rows[0]?.entregues, "0", "a RLS tem de esconder as linhas de A");
      assert.equal(deA.rows[0]?.micro_usd, "0");

      // E com o contexto de A a mesma consulta **ve** as linhas de A: sem este
      // lado, um `0` podia ser uma consulta que nao funciona.
      await definirContexto(app, tenantA);
      const comA = await app.query<{ micro_usd: string; entregues: string }>(
        SQL_CUSTO_DO_TENANT,
        [tenantA, DESDE, ATE],
      );
      assert.ok(
        Number(comA.rows[0]?.entregues ?? "0") > 0,
        "com o contexto de A tem de haver entregas, senao o zero acima nao diz nada",
      );
    });
  });

  describe("o bloqueio de template (criterio 9)", () => {
    it("recategorizar para marketing bloqueia, e e idempotente", async () => {
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) " +
          "VALUES ($1, 'a_bloquear', 'pt_PT', 'utility', 'approved', 'resumo')",
        [tenantA],
      );
      const adapter = adapterDe(tenantA);
      assert.equal(await adapter.bloquearTemplate(tenantA, "a_bloquear", "pt_PT", "marketing"), true);

      await definirContexto(app, tenantA);
      const linha = await app.query<{ category: string; bloqueado_em: Date | null }>(
        "SELECT category, bloqueado_em FROM platform.message_templates " +
          "WHERE name = 'a_bloquear' AND lang = 'pt_PT'",
      );
      assert.equal(linha.rows[0]?.category, "marketing");
      assert.notEqual(linha.rows[0]?.bloqueado_em, null);
      const primeiro = linha.rows[0]?.bloqueado_em;

      // A Meta reenvia o webhook: o segundo bloqueio nao faz nada e **preserva
      // o primeiro instante**, que e o que se audita.
      assert.equal(
        await adapter.bloquearTemplate(tenantA, "a_bloquear", "pt_PT", "marketing"),
        false,
      );
      const depois = await app.query<{ bloqueado_em: Date | null }>(
        "SELECT bloqueado_em FROM platform.message_templates " +
          "WHERE name = 'a_bloquear' AND lang = 'pt_PT'",
      );
      assert.deepEqual(depois.rows[0]?.bloqueado_em, primeiro);
    });

    it("uma recategorizacao para utility nao bloqueia nada", async () => {
      const adapter = adapterDe(tenantA);
      assert.equal(
        await adapter.bloquearTemplate(tenantA, "a_bloquear", "pt_PT", "utility"),
        false,
      );
    });
  });
});

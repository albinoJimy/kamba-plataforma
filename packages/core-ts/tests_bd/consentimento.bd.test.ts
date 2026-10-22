/**
 * O consentimento no 1.º contacto contra um PostgreSQL real (KAM-022).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **A idempotência do critério 2 é da base.** `ON CONFLICT (tenant_id,
 *    contact_id, purpose, evidence_hash) DO NOTHING RETURNING` devolve vazio na
 *    segunda — e, com duas ligações a disputar, é o índice único que serializa.
 *    Uma base falsa devolve o que se lhe mandou devolver.
 * 2. **A vista `consent_actual` respeita a RLS de quem a consulta.** É a
 *    primeira vista do esquema, e o `security_invoker = true` é o que a faz
 *    correr como quem pergunta. Sem ele, uma vista corre com os privilégios do
 *    dono e o isolamento passa a depender do `FORCE` — numa relação onde
 *    ninguém iria procurar. Aqui mede-se **pelo caminho do módulo**.
 * 3. **A contagem de avisos é um `LIKE` com prefixo sobre a chave de
 *    idempotência**, numa tabela de outro ticket (`outbound_messages`). Só um
 *    planeador prova que ela conta o que deve e nada mais.
 * 4. **A versão vigente é a de `vigente_desde` mais alto que já passou**, e o
 *    «já passou» só existe contra um `now()` real: uma versão publicada com data
 *    futura não vigora.
 * 5. **O ciclo inteiro**: sem consentimento sai o aviso e o AGR não corre;
 *    o «Continuar» escreve a linha e autoriza; a mensagem seguinte segue **sem
 *    escrever nada**, porque a vista já diz `valido`.
 *
 * O que **não** se mede aqui: a matriz de dezoito células, a detecção do
 * «PARAR», o `evidence_hash` e a propriedade das mil mensagens vivem em
 * `tests/consentimento.test.ts`, porque são funções puras e uma base real não
 * acrescenta nada à prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  ConsentGate,
  MetricasDoConsentimento,
  SQL_REGISTAR,
  preencher,
  provaDeConsentimento,
  resumoDoTexto,
  type CorpoDoAviso,
  type DestinoDoAviso,
  type Entrada,
} from "../src/consentimento/index.ts";
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
 * escreveu: fora de um `BEGIN` explícito cada instrução é a sua própria
 * transacção, e com `true` a definição desaparecia antes da instrução seguinte.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

const MARCADOR = "{loja}";
const TEXTO = `A ${MARCADOR} atende-o por um assistente automatico. Pode falar com uma pessoa.`;
const HORA = "2026-11-02T14:03:11.482Z";

let semente = 0;
function wamid(marca: string): string {
  semente += 1;
  return `wamid.ENSAIO${marca}${semente}`;
}

describe("o consentimento contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a corrida pela chave
  // unica so e real com duas sessoes. Com uma, os dois `INSERT` saem em serie
  // pela mesma conexao e o teste prova que o JavaScript e sequencial.
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let canalA = "";
  let pnidA = "";
  let contactoA = "";
  let conversaA = "";
  let contactoB = "";
  let conversaB = "";
  let canalB = "";

  async function criarContacto(tenant: string): Promise<string> {
    const { rows } = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenant],
    );
    return rows[0]?.contact_id ?? "";
  }

  async function abrirConversa(
    tenant: string,
    canal: string,
    contacto: string,
  ): Promise<string> {
    const { rows } = await admin.query<{ id: string }>(
      "INSERT INTO platform.conversations " +
        "(tenant_id, contact_id, channel_id, last_inbound_at, window_expires_at) " +
        "VALUES ($1, $2, $3, now(), now() + interval '24 hours') RETURNING id",
      [tenant, contacto, canal],
    );
    return rows[0]?.id ?? "";
  }

  /** Publica uma versão do aviso, como operação faria (papel de administração). */
  async function publicarTexto(
    version: string,
    texto: string,
    vigenteDesde: string,
  ): Promise<void> {
    await admin.query(
      "INSERT INTO platform.consent_texts " +
        "(version, purpose, texto, hash, vigente_desde) " +
        "VALUES ($1, 'transacao', $2, $3, $4)",
      [version, texto, Buffer.from(resumoDoTexto(texto)), vigenteDesde],
    );
  }

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

  function gateDe(
    tenant: string,
    opcoes: { readonly cliente?: pg.Client } = {},
  ): {
    gate: ConsentGate;
    metricas: MetricasDoConsentimento;
    enviadas: { destino: DestinoDoAviso; corpo: CorpoDoAviso }[];
    emitidos: string[];
    modos: string[];
  } {
    const metricas = new MetricasDoConsentimento();
    const enviadas: { destino: DestinoDoAviso; corpo: CorpoDoAviso }[] = [];
    const emitidos: string[] = [];
    const modos: string[] = [];
    const gate = new ConsentGate({
      bd: bdDe(tenant, opcoes.cliente ?? app),
      metricas,
      // **A porta de envio escreve a linha de `outbound_messages`**, porque é
      // dela que a contagem de avisos do critério 3 sai. Em produção quem a
      // liga é o `Saida` do KAM-015; aqui escreve-se directamente, porque o que
      // esta bateria mede é a **contagem** e não o envio.
      enviar: async (destino, corpo) => {
        enviadas.push({ destino, corpo });
        const id = wamid("AV");
        await admin.query(
          "INSERT INTO platform.outbound_messages " +
            "(tenant_id, channel_id, contact_id, conversation_id, " +
            " idempotency_key, kind, state, wamid) " +
            "VALUES ($1, $2, $3, $4, $5, 'service', 'sent', $6) " +
            "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING",
          [
            destino.tenantId,
            destino.channelId,
            destino.contactId,
            destino.conversationId,
            destino.idempotencyKey,
            id,
          ],
        );
        return id;
      },
      emitir: async (tipo, _t, _c, finalidade) => {
        emitidos.push(`${tipo}:${finalidade}`);
      },
      modo: async (_t, _c, modo) => {
        modos.push(modo);
      },
      agora: () => new Date(HORA),
    });
    return { gate, metricas, enviadas, emitidos, modos };
  }

  function mensagem(
    entrada: Entrada,
    quem: { tenant: string; contacto: string; conversa: string; canal: string; pnid: string },
    marca = "M",
  ) {
    return {
      tenantId: quem.tenant,
      contactId: quem.contacto,
      conversationId: quem.conversa,
      channelId: quem.canal,
      phoneNumberId: quem.pnid,
      wamid: wamid(marca),
      hora: HORA,
      entrada,
    };
  }

  function de(a: boolean) {
    return a
      ? { tenant: tenantA, contacto: contactoA, conversa: conversaA, canal: canalA, pnid: pnidA }
      : { tenant: tenantB, contacto: contactoB, conversa: conversaB, canal: canalB, pnid: "" };
  }

  /** As provas de um *tenant*, pelo administrador (sem RLS pelo meio). */
  async function provasDe(tenant: string): Promise<
    readonly { readonly purpose: string; readonly accepted: boolean; readonly text_version: string }[]
  > {
    const { rows } = await admin.query(
      "SELECT purpose, accepted, text_version FROM platform.consent_event " +
        "WHERE tenant_id = $1 ORDER BY purpose, ocorrido_em",
      [tenant],
    );
    return rows as never;
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

    tenantA = await criarTenant(admin, "consent-a");
    tenantB = await criarTenant(admin, "consent-b");
    const a = await criarCanal(admin, tenantA);
    const b = await criarCanal(admin, tenantB);
    canalA = a.id;
    pnidA = a.phoneNumberId;
    canalB = b.id;
    contactoA = await criarContacto(tenantA);
    contactoB = await criarContacto(tenantB);
    conversaA = await abrirConversa(tenantA, canalA, contactoA);
    conversaB = await abrirConversa(tenantB, canalB, contactoB);
    await publicarTexto("v1", TEXTO, "2026-01-01T00:00:00Z");
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    // O texto nao se apaga por tenant: nao tem `tenant_id`. Quem o semeia
    // apaga-o.
    await admin.query("DELETE FROM platform.consent_texts");
    await admin.end();
    await app.end();
    await app2.end();
  });

  // --------------------------------------------- o primeiro contacto (criterio 1)

  describe("o primeiro contacto (criterio 1)", () => {
    it("**sem consentimento: 1 aviso, 0 AGR, e a linha fica em outbound_messages**", async () => {
      const { gate, enviadas, metricas } = gateDe(tenantA);
      const r = await gate.tratar(
        mensagem({ tipo: "texto", texto: "bom dia" }, de(true)),
      );

      assert.equal(r.accao, "enviar_aviso");
      assert.equal(r.invocaAgr, false, "a letra do criterio 1");
      assert.equal(r.mensagens, 1);
      assert.equal(r.versao, "v1");
      // **O texto saiu preenchido**, com o nome da loja no lugar do marcador.
      const corpo = enviadas[0]?.corpo.texto ?? "";
      assert.ok(!corpo.includes(MARCADOR), "o marcador saiu em claro");
      assert.ok(corpo.includes("Loja de ensaio"), "o nome da loja nao entrou");
      assert.equal(metricas.ler()["consent_notice_sent_total"], 1);
      // E a chave do aviso ficou na base, que e o que a contagem le.
      const { rows } = await admin.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.outbound_messages " +
          "WHERE tenant_id = $1 AND idempotency_key = $2",
        [tenantA, `aviso:${conversaA}:1`],
      );
      assert.equal(rows[0]?.n, "1");
      // E **nenhuma prova** foi escrita: o aviso nao e um consentimento.
      assert.deepEqual(await provasDe(tenantA), []);
    });

    it("**a contagem de avisos vem da base, pelo prefixo da chave**", async () => {
      // A segunda mensagem livre: o aviso repete-se e a chave e a `:2`.
      const { gate, enviadas } = gateDe(tenantA);
      const r = await gate.tratar(
        mensagem({ tipo: "texto", texto: "esta aberto?" }, de(true)),
      );
      assert.equal(r.accao, "enviar_aviso");
      assert.equal(enviadas[0]?.destino.idempotencyKey, `aviso:${conversaA}:2`);
    });

    it("**ao terceiro, passa a uma pessoa e nao envia aviso** (criterio 3)", async () => {
      const { gate, enviadas, modos } = gateDe(tenantA);
      const r = await gate.tratar(mensagem({ tipo: "outro" }, de(true)));

      assert.equal(r.accao, "passar_a_humano");
      assert.equal(r.invocaAgr, false);
      assert.deepEqual(modos, ["humano"]);
      // «Falar com a loja» e a passagem por insistencia registram a
      // `atendimento`: o aviso **foi apresentado**, e isso e um facto.
      assert.deepEqual(enviadas, [], "a passagem a humano nao manda aviso");
      const provas = await provasDe(tenantA);
      assert.equal(provas.length, 1);
      assert.equal(provas[0]?.purpose, "atendimento");
    });
  });

  // ---------------------------------------------------- o «Continuar» (criterio 2)

  describe("o «Continuar» e o ciclo inteiro (criterio 2)", () => {
    it("**grava a prova, autoriza o AGR, e a mensagem seguinte segue sem escrever**", async () => {
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };

      const primeira = gateDe(tenantA);
      const r1 = await primeira.gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, quem, "C1"),
      );
      assert.equal(r1.accao, "registar_e_seguir");
      assert.equal(r1.registou, true);
      assert.equal(r1.invocaAgr, true);
      assert.deepEqual(primeira.emitidos, ["consent.recorded:transacao"]);

      // **A linha esta na base, e a vista ja a reconhece.** E o que torna o
      // ciclo real: a segunda mensagem le `valido` e segue **sem** escrever.
      const segunda = gateDe(tenantA);
      const r2 = await segunda.gate.tratar(
        mensagem({ tipo: "texto", texto: "quanto custa?" }, quem, "C2"),
      );
      assert.equal(r2.estado, "valido");
      assert.equal(r2.accao, "seguir");
      assert.equal(r2.invocaAgr, true);
      assert.equal(r2.registou, false);
      assert.equal(r2.mensagens, 0);
      assert.deepEqual(segunda.emitidos, [], "seguir nao emite nada");
    });

    it("**o mesmo botao duas vezes: uma linha** (a prova e a mesma)", async () => {
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };
      const id = wamid("IDEM");
      const base = mensagem({ tipo: "botao", id: "continuar" }, quem, "X");

      const um = gateDe(tenantA);
      assert.equal((await um.gate.tratar({ ...base, wamid: id })).registou, true);
      const dois = gateDe(tenantA);
      const r = await dois.gate.tratar({ ...base, wamid: id });

      assert.equal(r.registou, false, "a prova ja estava registada");
      const { rows } = await admin.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.consent_event " +
          "WHERE tenant_id = $1 AND contact_id = $2",
        [tenantA, contacto],
      );
      assert.equal(rows[0]?.n, "1");
    });

    it("**dois cliques em paralelo: uma linha e um evento**", async () => {
      // **Com duas ligacoes**, que e o que torna a corrida verdadeira: e o
      // indice unico que serializa, e nao o JavaScript.
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };
      const id = wamid("CORRIDA");
      const base = mensagem({ tipo: "botao", id: "continuar" }, quem, "Y");

      const um = gateDe(tenantA);
      const dois = gateDe(tenantA, { cliente: app2 });
      const [a, b] = await Promise.all([
        um.gate.tratar({ ...base, wamid: id }),
        dois.gate.tratar({ ...base, wamid: id }),
      ]);

      assert.equal([a.registou, b.registou].filter(Boolean).length, 1);
      assert.equal([...um.emitidos, ...dois.emitidos].length, 1, "um evento e nao dois");
      const { rows } = await admin.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.consent_event " +
          "WHERE tenant_id = $1 AND contact_id = $2",
        [tenantA, contacto],
      );
      assert.equal(rows[0]?.n, "1");
    });

    it("**a prova guardada e a que se recalcula**: reprodutivel (criterio 7)", async () => {
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const id = wamid("PROVA");
      const { gate } = gateDe(tenantA);
      await gate.tratar({
        ...mensagem({ tipo: "botao", id: "continuar" }, {
          tenant: tenantA,
          contacto,
          conversa,
          canal: canalA,
          pnid: pnidA,
        }),
        wamid: id,
      });

      // Recalcula-se a partir da linha e da versao do texto, como quem audita
      // faria — e tem de dar o mesmo octeto a octeto.
      const { rows } = await admin.query<{ nome: string }>(
        "SELECT nome FROM platform.tenants WHERE id = $1",
        [tenantA],
      );
      const esperado = provaDeConsentimento({
        textoMostrado: preencher(TEXTO, rows[0]?.nome ?? ""),
        contactId: contacto,
        wamid: id,
        hora: HORA,
      });
      const guardada = await admin.query<{ evidence_hash: Buffer }>(
        "SELECT evidence_hash FROM platform.consent_event WHERE contact_id = $1",
        [contacto],
      );
      assert.deepEqual(
        new Uint8Array(guardada.rows[0]?.evidence_hash ?? Buffer.alloc(0)),
        esperado,
      );
    });
  });

  // -------------------------------------------------------- o «PARAR» (criterio 5)

  describe("o «PARAR» (criterio 5)", () => {
    it("**grava a revogacao de marketing e pausa, sem tocar na transacao**", async () => {
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };

      const antes = gateDe(tenantA);
      await antes.gate.tratar(mensagem({ tipo: "botao", id: "continuar" }, quem, "P0"));
      const { gate, modos, emitidos } = gateDe(tenantA);
      const r = await gate.tratar(mensagem({ tipo: "texto", texto: "PARAR" }, quem, "P1"));

      assert.equal(r.accao, "registar_revogacao");
      assert.equal(r.registou, true);
      assert.equal(r.pausaAConversa, true);
      assert.deepEqual(modos, ["pausada"]);
      assert.deepEqual(emitidos, ["consent.withdrawn:marketing"]);

      // **Duas linhas e duas finalidades**, e a de transacao continua aceite: um
      // «PARAR» cala o marketing e nao a loja.
      const { rows } = await admin.query<{ purpose: string; accepted: boolean }>(
        "SELECT purpose, accepted FROM platform.consent_actual " +
          "WHERE tenant_id = $1 AND contact_id = $2 ORDER BY purpose",
        [tenantA, contacto],
      );
      assert.deepEqual(
        rows.map((l) => `${l.purpose}=${l.accepted}`),
        ["marketing=false", "transacao=true"],
      );
    });
  });

  // ---------------------------------------------- a versao vigente (criterio 7)

  describe("a versao vigente do texto (criterio 7)", () => {
    it("**uma versao com data futura nao vigora**", async () => {
      await publicarTexto("v9", `${MARCADOR} ainda nao vale`, "2099-01-01T00:00:00Z");
      const { gate } = gateDe(tenantA);
      const vigente = await gate.textoVigente();
      assert.equal(vigente?.version, "v1", "a futura nao e a vigente");
      await admin.query("DELETE FROM platform.consent_texts WHERE version = 'v9'");
    });

    it("**subir a versao obriga a re-avisar quem ja tinha consentido**", async () => {
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };
      await gateDe(tenantA).gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, quem, "V1"),
      );

      // A versao nova entra com data **anterior** ao relogio do ensaio.
      await publicarTexto("v2", `${MARCADOR} tem texto novo`, "2026-10-01T00:00:00Z");
      const { gate } = gateDe(tenantA);
      const r = await gate.tratar(
        mensagem({ tipo: "texto", texto: "bom dia" }, quem, "V2"),
      );

      assert.equal(r.versao, "v2");
      assert.equal(r.estado, "desactualizado");
      assert.equal(r.accao, "enviar_aviso");
      assert.equal(r.invocaAgr, false);
      await admin.query("DELETE FROM platform.consent_texts WHERE version = 'v2'");
    });

    it("**duas provas do mesmo trio: o estado e o da ultima**", async () => {
      // **Esta e a asserção que prende a leitura pela vista, e nao havia
      // nenhuma.** A mutacao que trocou o `consent_actual` pela
      // `consent_event` no `SQL_ESTADO` **sobreviveu** a primeira passagem da
      // prova, e a razao e que com **uma** linha por trio as duas consultas
      // dao o mesmo: o `DISTINCT ON` da vista so se distingue de um `SELECT`
      // sobre a tabela quando ha duas.
      //
      // E duas ha, e no caminho mais normal que existe: o contacto aceita a
      // `v1`, o texto sobe para a `v2`, ele aceita outra vez. Sem a ordem da
      // vista, a tabela devolve as duas linhas **sem ordem garantida** e o
      // `rows[0]` pode ser a `v1` — o estado ficava `desactualizado` para
      // sempre e o aviso repetia-se para sempre.
      const contacto = await criarContacto(tenantA);
      const conversa = await abrirConversa(tenantA, canalA, contacto);
      const quem = { tenant: tenantA, contacto, conversa, canal: canalA, pnid: pnidA };

      await gateDe(tenantA).gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, quem, "D1"),
      );
      await publicarTexto("v2", `${MARCADOR} tem texto novo`, "2026-10-01T00:00:00Z");
      const segunda = await gateDe(tenantA).gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, quem, "D2"),
      );
      assert.equal(segunda.versao, "v2");
      assert.equal(segunda.registou, true, "a segunda prova e de outra versao");

      // **Duas linhas na tabela, uma na vista, e a da vista e a `v2`.**
      const cru = await admin.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.consent_event " +
          "WHERE contact_id = $1 AND purpose = 'transacao'",
        [contacto],
      );
      assert.equal(cru.rows[0]?.n, "2");
      const vista = await admin.query<{ text_version: string }>(
        "SELECT text_version FROM platform.consent_actual " +
          "WHERE contact_id = $1 AND purpose = 'transacao'",
        [contacto],
      );
      assert.equal(vista.rows.length, 1);
      assert.equal(vista.rows[0]?.text_version, "v2");

      // E o estado que o gate le e `valido`, pelo que a mensagem seguinte segue.
      const terceira = await gateDe(tenantA).gate.tratar(
        mensagem({ tipo: "texto", texto: "quanto custa?" }, quem, "D3"),
      );
      assert.equal(terceira.estado, "valido");
      assert.equal(terceira.invocaAgr, true);
      await admin.query("DELETE FROM platform.consent_texts WHERE version = 'v2'");
    });

    it("**sem versao vigente nao envia nada e nao autoriza**", async () => {
      // A `0015` cria a tabela **vazia**: o texto esta a confirmar por parecer.
      await admin.query("DELETE FROM platform.consent_texts");
      const { gate, enviadas, metricas } = gateDe(tenantA);
      const r = await gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, de(true), "Z"),
      );

      assert.equal(r.invocaAgr, false);
      assert.equal(r.versao, null);
      assert.deepEqual(enviadas, []);
      assert.equal(metricas.ler()["consent_blocked_total:enviar_aviso"], 1);
      await publicarTexto("v1", TEXTO, "2026-01-01T00:00:00Z");
    });
  });

  // -------------- isolamento (Testes Requeridos: X-03 sobre consent_event)

  describe("isolamento (Testes Requeridos: X-03 sobre consent_event)", () => {
    it("**a vista nao mostra o estado de B com o contexto de A**", async () => {
      // **O que o `security_invoker = true` compra, medido pelo caminho do
      // modulo.** Sem a opcao, a vista corria como o dono e a RLS passava a
      // depender do `FORCE`.
      await gateDe(tenantB).gate.tratar(
        mensagem({ tipo: "botao", id: "continuar" }, de(false), "B1"),
      );
      const provasDeB = await provasDe(tenantB);
      assert.ok(provasDeB.length > 0, "B devia ter prova");

      // A `GestaoDeCanal` de A a perguntar pelo contacto de B: a vista nao
      // responde, e o estado sai `ausente`.
      const { gate } = gateDe(tenantA);
      assert.equal(await gate.estado(tenantA, contactoB, "v1"), "ausente");
      // E com o contexto de A, a consulta directa a vista tambem nao ve.
      await definirContexto(app, tenantA);
      const { rows } = await app.query(
        "SELECT contact_id FROM platform.consent_actual WHERE contact_id = $1",
        [contactoB],
      );
      assert.deepEqual(rows, []);
    });

    it("**uma prova de A nao pode apontar para um contacto de B** (FK composta)", async () => {
      // A RLS protege a leitura; a integridade e da FK, e esta leva o
      // `tenant_id` nos dois lados.
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query(SQL_REGISTAR, [
            tenantA,
            contactoB,
            "transacao",
            "v1",
            true,
            "whatsapp",
            Buffer.from(resumoDoTexto("cruzado")),
            HORA,
          ]),
        (erro: { code?: string }) => erro.code === "23503",
      );
    });
  });

  // ------------------------------------- o append-only, pelo privilegio

  describe("o append-only: o privilegio nem existe (criterio 6)", () => {
    it("**o kamba_app nao tem UPDATE em consent_event**", async () => {
      // Isto e o oposto de um teste de politica: nao se afirma que o modulo nao
      // corrige uma prova — afirma-se que **nenhum codigo que corra como
      // `kamba_app` o pode fazer**. Uma prova que se possa corrigir nao e prova.
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query("UPDATE platform.consent_event SET accepted = false WHERE tenant_id = $1", [
            tenantA,
          ]),
        (erro: { code?: string }) => erro.code === "42501",
      );
    });

    it("**nem DELETE**, e e a mesma razao", async () => {
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query("DELETE FROM platform.consent_event WHERE tenant_id = $1", [tenantA]),
        (erro: { code?: string }) => erro.code === "42501",
      );
    });

    it("**nem escreve o texto do aviso**: quem publica uma versao e operacao", async () => {
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query(
            "INSERT INTO platform.consent_texts " +
              "(version, purpose, texto, hash, vigente_desde) " +
              "VALUES ('vx', 'transacao', 'inventado', $1, now())",
            [Buffer.from(resumoDoTexto("x"))],
          ),
        (erro: { code?: string }) => erro.code === "42501",
      );
    });

    it("**o SELECT e o INSERT na prova, esses, existem**", async () => {
      // A metade positiva: sem ela, as tres negativas passavam por uma
      // concessao em falta por inteiro.
      const contacto = await criarContacto(tenantA);
      await definirContexto(app, tenantA);
      const escrita = await app.query(SQL_REGISTAR, [
        tenantA,
        contacto,
        "atendimento",
        "v1",
        true,
        "whatsapp",
        Buffer.from(resumoDoTexto("positiva")),
        HORA,
      ]);
      assert.equal(escrita.rows.length, 1, "o INSERT devia ter escrito");
      const leitura = await app.query(
        "SELECT count(*)::text AS n FROM platform.consent_event WHERE contact_id = $1",
        [contacto],
      );
      assert.equal((leitura.rows[0] as { n: string }).n, "1");
    });
  });
});

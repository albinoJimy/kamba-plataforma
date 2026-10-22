/**
 * Os modos da conversa contra um PostgreSQL real (KAM-018).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **O *lock* serializa de verdade.** O `pg_advisory_xact_lock(hash(tenant_id,
 *    contact_id))` do critério 2 só é exclusão mútua se houver duas sessões a
 *    disputá-lo: com uma, as duas chamadas saem em série pela mesma ligação e o
 *    teste prova que o JavaScript é sequencial. Aqui a guarda **bloqueia** à
 *    porta de uma transição em curso e, quando entra, vê o modo já mudado.
 * 2. **A corrida do §10.3, com o relógio nas nossas mãos.** Turno em t0, *echo*
 *    em t0+1 s, resposta pronta em t0+2 s → **0 mensagens enviadas e 1 registo
 *    suprimido**, que é a letra do critério 3.
 * 3. **As 100 intercalações, com semente fixa.** A ordem de cada uma sai de um
 *    PRNG com semente escrita neste ficheiro, e não de `Math.random()`: um teste
 *    de corrida que não se reproduz é um teste que falha uma vez por mês e que
 *    ninguém consegue investigar. O teste corre as 100 **duas vezes** e compara
 *    as sequências de desfecho — é assim que se prova que a semente está fixa.
 * 4. **O silenciamento é por conversa e não por canal** (critério 4). Duas
 *    conversas do **mesmo** canal, uma em `dono` e outra em `bot`: a primeira
 *    suprime, a segunda passa. Com uma base falsa isto não prova nada; aqui
 *    prova que nada no caminho do envio olha para o canal.
 * 5. **0 invocações do AGR em `dono`/`humano`/`pausada`** (critério 5), com o
 *    `Chr` do KAM-014 a ler o modo que **esta** bateria acabou de escrever. É o
 *    único sítio onde os dois módulos se encontram sobre a mesma linha.
 * 6. **O relógio das 24 h conta do `handoffs.opened_at` quando não houve
 *    actividade humana nenhuma** (critério 7). O `COALESCE` do
 *    `SQL_PAUSAR_POR_INACTIVIDADE` liga duas tabelas e um `max`, e nada disso se
 *    prova sem planeador.
 * 7. **O privilégio existe agora, e é por coluna** (revisão `0016`). O oposto de
 *    um teste de política: não se afirma que o código não escreve o modo por
 *    fora, afirma-se o que cada papel **consegue** — e que o `kamba_resolver`
 *    continua a não conseguir.
 * 8. **A RLS recusa o que o código deixaria passar** (X-03). Com o contexto de
 *    A, o modo de B não se lê nem se escreve — e com `FORCE`, nem como dono.
 *
 * O que **não** se mede aqui: a tabela de transições célula a célula, a
 * condição do silêncio, a ordem das instruções e o mapeamento do evento vivem em
 * `tests/modos.transicoes.test.ts` e `tests/modos.test.ts`, porque são funções
 * puras e ordem de chamadas, e uma base real não acrescenta nada à prova.
 *
 * E o que **não existe**: a transição `bot→dono` por *echo* real, que precisa de
 * `smb_message_echoes` (KAM-017), e a métrica `echo_latency_ms`, que pede ≥ 30
 * *echoes* de *staging* com números +244 (R6/L6, KAM-100). Nesta bateria o
 * gatilho `echo_do_dono` é **disparado** pelo ensaio, que é o que a máquina
 * expõe; quem o detecta é o ticket da coexistência.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  Chr,
  type AgentInvocation,
  type ComTenant as ComTenantDoChr,
  type EntregaDoChr,
  MODO_POR_OMISSAO,
  MetricasDoChr,
  ResolvedorDeCanal,
  abrirConversa,
} from "../src/chr/index.ts";
import type { EventoDeEntrada } from "../src/entrada/index.ts";
import {
  MaquinaDeModos,
  MetricasDosModos,
  METRICA_SUPRIMIDAS,
  SQL_CONVERSA_PARA_MODO,
  SQL_MUDAR_MODO,
  avaliar,
  emitirModoMudado,
  origensDe,
} from "../src/modos/index.ts";
import type { Pedido } from "../src/outbound/index.ts";
import { comTenant as comTenantReal } from "../src/tenant_guard/index.ts";
import {
  BASE_DESCARTAVEL,
  apagarTenant,
  criarCanal,
  criarTenant,
  ligar,
} from "./apoio.ts";

/**
 * A semente das 100 intercalações. **Fixa, e escrita aqui.**
 *
 * É regra desta casa e não preferência: um `Math.random()` num teste de corrida
 * dá um teste que falha uma vez por mês e que nunca se reproduz. Com a semente
 * no ficheiro, a sequência de intercalações é a mesma em todas as máquinas e em
 * todas as execuções — e o teste `as 100 intercalacoes sao reproduziveis` é o
 * que impede alguém de a trocar por um relógio sem notar.
 */
const SEMENTE = 0x4b414d18; // "KAM" + 0x18, que é 24 — o número do ticket.

/** Quantas intercalações. O número está no critério 3. */
const INTERCALACOES = 100;

/** `mulberry32`: um PRNG de 32 bits, determinístico e de três linhas. */
function prng(semente: number): () => number {
  let estado = semente >>> 0;
  return () => {
    estado = (estado + 0x6d2b79f5) >>> 0;
    let t = estado;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** O `t0` de todos os ensaios de corrida. Fixo, para o relógio ser nosso. */
const T0 = new Date("2026-11-02T14:00:00.000Z");
/** O *echo* chega em t0+1 s (critério 3). */
const T_ECHO = new Date(T0.getTime() + 1_000);

describe("os modos da conversa contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda e uma terceira ligacao de `kamba_app`**, e nao e luxo: o
  // `comTenant` do `tenant_guard` recusa dois usos concorrentes da mesma
  // ligacao (`LigacaoEmUsoError`), e um *advisory lock* so e exclusao mutua
  // entre sessoes diferentes. Com uma, as duas transaccoes sairiam em serie
  // pela mesma conexao e o ensaio provava que o JavaScript e sequencial.
  let app2: pg.Client;
  let app3: pg.Client;
  let resolver: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let canalA = "";
  let canalB = "";
  let pnidA = "";

  /** Um contacto novo do *tenant*, criado pelo administrador. */
  async function criarContacto(tenant: string): Promise<string> {
    const { rows } = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenant],
    );
    return rows[0]?.contact_id ?? "";
  }

  /** Uma conversa com a janela aberta, criada pelo administrador. */
  async function abrir(
    tenant: string,
    canal: string,
    contactId?: string,
  ): Promise<{ readonly id: string; readonly contactId: string }> {
    const contacto = contactId ?? (await criarContacto(tenant));
    const { rows } = await admin.query<{ id: string }>(
      "INSERT INTO platform.conversations " +
        "(tenant_id, contact_id, channel_id, last_inbound_at, window_expires_at) " +
        "VALUES ($1, $2, $3, now(), now() + interval '24 hours') RETURNING id::text AS id",
      [tenant, contacto, canal],
    );
    return { id: rows[0]?.id ?? "", contactId: contacto };
  }

  /** O modo e a actividade humana de uma conversa, vistos pelo administrador. */
  async function estadoDe(
    id: string,
  ): Promise<{ readonly mode: string; readonly actividade: Date | null }> {
    const { rows } = await admin.query<{ mode: string; last_human_activity_at: Date | null }>(
      "SELECT mode, last_human_activity_at FROM platform.conversations WHERE id = $1",
      [id],
    );
    return { mode: rows[0]?.mode ?? "", actividade: rows[0]?.last_human_activity_at ?? null };
  }

  /** Põe o modo e a actividade humana directamente, como administrador. */
  async function forcar(id: string, mode: string, actividade: Date | null): Promise<void> {
    await admin.query(
      "UPDATE platform.conversations SET mode = $2, last_human_activity_at = $3 WHERE id = $1",
      [id, mode, actividade],
    );
  }

  /** As linhas de saída de uma conversa, por estado. */
  async function saidasDe(id: string): Promise<Record<string, number>> {
    const { rows } = await admin.query<{ state: string; n: string }>(
      "SELECT state, count(*)::text AS n FROM platform.outbound_messages " +
        "WHERE conversation_id = $1 GROUP BY state",
      [id],
    );
    return Object.fromEntries(rows.map((l) => [l.state, Number(l.n)]));
  }

  function comTenantDe(cliente: pg.Client): ComTenantDoChr {
    return (tenant, trabalho) => comTenantReal(cliente, tenant, () => trabalho(cliente));
  }

  function maquina(cliente: pg.Client, agora = () => T0): MaquinaDeModos {
    return new MaquinaDeModos({
      comTenant: comTenantDe(cliente) as never,
      emitir: emitirModoMudado,
      agora,
    });
  }

  function pedido(
    conversationId: string,
    contactId: string,
    canal: string,
    marca: string,
    turnoIniciadoEm: Date = T0,
  ): Pedido {
    return {
      tenantId: tenantA,
      channelId: canal,
      contactId,
      conversationId,
      phoneNumberId: pnidA,
      idempotencyKey: `kam018-${marca}`,
      corpo: { tipo: "texto", texto: "resposta do assistente" },
      doBot: true,
      turnoIniciadoEm,
    };
  }

  before(async () => {
    admin = await ligar("admin");
    app = await ligar("app");
    app2 = await ligar("app");
    app3 = await ligar("app");
    resolver = await ligar("resolver");
    assert.equal(process.env.KAMBA_DB_NAME, BASE_DESCARTAVEL);
    tenantA = await criarTenant(admin, "modos-A");
    tenantB = await criarTenant(admin, "modos-B");
    // **Os dois `ativo`**, e não é detalhe de arranjo: a `0001` faz um tenant
    // nascer em `onboarding`, e a matriz de estados do §7.2 (KAM-009) recusa o
    // processamento nesse estado — o CHR responderia `estado_recusou` e o
    // critério 5 media a recusa da matriz em vez do modo da conversa. Medido: a
    // primeira execução desta bateria deu `estado_recusou` onde esperava
    // `encaminhado`, e o controlo positivo do critério 5 era o único teste que o
    // apanhava.
    for (const tenant of [tenantA, tenantB]) {
      await admin.query("UPDATE platform.tenants SET estado = 'ativo' WHERE id = $1", [
        tenant,
      ]);
    }
    const a = await criarCanal(admin, tenantA);
    const b = await criarCanal(admin, tenantB);
    canalA = a.id;
    pnidA = a.phoneNumberId;
    canalB = b.id;
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await Promise.all([admin.end(), app.end(), app2.end(), app3.end(), resolver.end()]);
  });

  // ---------------------------------------------------------------------------
  describe("critério 2 — o lock da conversa serializa a transição e a guarda", () => {
    it("a guarda bloqueia a porta de uma transicao em curso, e entra com o modo novo", async () => {
      const conversa = await abrir(tenantA, canalA);
      // A transição corre numa ligação e **pára antes de confirmar**: abre-se a
      // transacção à mão para o *lock* ficar retido enquanto se mede.
      await app.query("BEGIN");
      await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
      await app.query(
        "SELECT pg_advisory_xact_lock(hashtextextended($1::text || ':' || $2::text, 0))",
        [tenantA, conversa.contactId],
      );
      await app.query(SQL_MUDAR_MODO, [
        tenantA,
        conversa.id,
        "dono",
        origensDe("echo_do_dono", "dono"),
        T_ECHO,
      ]);

      // A guarda, noutra ligação, tem de **esperar**. Mede-se que ela não
      // resolveu enquanto a transacção de cima está aberta.
      let decidiu = false;
      const emCurso = avaliar(
        { comTenant: comTenantDe(app2) as never },
        pedido(conversa.id, conversa.contactId, canalA, "lock"),
      ).then((d) => {
        decidiu = true;
        return d;
      });
      // Duas voltas pelo *event loop* e 150 ms de relógio: se a guarda não
      // estivesse à espera do *lock*, já teria respondido.
      await new Promise((r) => setTimeout(r, 150));
      assert.equal(decidiu, false, "a guarda nao esperou pelo lock da conversa");

      await app.query("COMMIT");
      const decisao = await emCurso;
      // Entrou depois do `COMMIT` e viu o modo que a transição escreveu.
      assert.equal(decisao.passa, false);
      assert.equal(decisao.motivo, "modo");
      assert.equal((await estadoDe(conversa.id)).mode, "dono");
    });

    it("duas transicoes concorrentes deixam uma transicao e um evento", async () => {
      // A idempotência do DoD: «o mesmo *echo* repetido 2× produz 1 transição».
      // Aqui são duas sessões a disputá-la ao mesmo tempo, que é mais forte do
      // que duas chamadas em série.
      const conversa = await abrir(tenantA, canalA);
      const antes = await contarEventos(conversa.id);
      const [um, dois] = await Promise.all([
        maquina(app).disparar(
          { tenantId: tenantA, conversationId: conversa.id },
          "echo_do_dono",
        ),
        maquina(app2).disparar(
          { tenantId: tenantA, conversationId: conversa.id },
          "echo_do_dono",
        ),
      ]);
      const ganhou = [um, dois].filter((r) => r.mudou);
      assert.equal(ganhou.length, 1, "duas transicoes ganharam a mesma corrida");
      assert.equal((await estadoDe(conversa.id)).mode, "dono");
      assert.equal((await contarEventos(conversa.id)) - antes, 1);
    });

    it("o UPDATE ganha a corrida **sem** o lock: a atomicidade e da linha", async () => {
      // **Esta foi pedida pela prova por mutação.** Apagar o `FOR UPDATE` da
      // subconsulta do `SQL_MUDAR_MODO` não fazia nenhum teste falhar, porque
      // todos passam pela máquina e a máquina toma o *advisory lock* — que
      // serializa tudo e esconde a diferença. Aqui corre-se a consulta **crua**,
      // em duas ligações, **sem** *lock* nenhum: sem o `FOR UPDATE`, as duas
      // subconsultas lêem `bot` com o mesmo instantâneo e as duas escritas
      // passam (uma actualização perdida); com ele, a segunda espera, relê a
      // linha já em `dono` e o `antes.mode = ANY(['bot'])` deixa de casar.
      //
      // Vale por si e não como redundância do *lock*: quem corra o SQL deste
      // módulo fora da máquina — uma reparação, um *job* futuro — tem de obter
      // o mesmo desfecho.
      const conversa = await abrir(tenantA, canalA);
      const origens = origensDe("echo_do_dono", "dono");
      const correr = async (cliente: pg.Client) => {
        await cliente.query("BEGIN");
        try {
          await cliente.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
          const { rows } = await cliente.query(SQL_MUDAR_MODO, [
            tenantA,
            conversa.id,
            "dono",
            origens,
            T_ECHO,
          ]);
          await cliente.query("COMMIT");
          return rows.length;
        } catch (erro) {
          await cliente.query("ROLLBACK");
          throw erro;
        }
      };
      const [um, dois] = await Promise.all([correr(app), correr(app2)]);
      assert.equal(um + dois, 1, "as duas escritas passaram: a transicao nao e atomica");
      assert.equal((await estadoDe(conversa.id)).mode, "dono");
    });

    it("um echo fora de ordem nao faz a actividade humana andar para tras", async () => {
      // **Também pedida pela prova por mutação**, e cobre as duas escritas da
      // coluna: trocar o `GREATEST` por uma atribuição directa, no
      // `SQL_MUDAR_MODO` e no `SQL_REGISTAR_ACTIVIDADE_HUMANA`, não fazia
      // nenhum teste falhar.
      //
      // O caso é real e não hipotético: a Meta **não garante ordem** nos
      // *webhooks* (`E1` §5, CONFIRMADO), pelo que um *echo* antigo chega depois
      // de um recente. Sem o `GREATEST`, esse *echo* fazia o relógio do silêncio
      // do dono andar para trás **e** o `PreSendGuard` deixar passar um envio
      // que devia suprimir.
      const tarde = new Date(T0.getTime() + 10_000);
      const cedo = new Date(T0.getTime() + 1_000);

      // (a) na transição: a conversa está em `bot`, o *echo* tardio passa-a a
      // `dono`; depois reposta a `bot` **com a actividade tardia guardada**, um
      // *echo* antigo transita outra vez e não pode recuar o instante.
      const naTransicao = await abrir(tenantA, canalA);
      await maquina(app, () => tarde).disparar(
        { tenantId: tenantA, conversationId: naTransicao.id },
        "echo_do_dono",
      );
      assert.deepEqual((await estadoDe(naTransicao.id)).actividade, tarde);
      await admin.query("UPDATE platform.conversations SET mode = 'bot' WHERE id = $1", [
        naTransicao.id,
      ]);
      await maquina(app, () => cedo).disparar(
        { tenantId: tenantA, conversationId: naTransicao.id },
        "echo_do_dono",
      );
      assert.deepEqual(
        (await estadoDe(naTransicao.id)).actividade,
        tarde,
        "o UPDATE do modo recuou a actividade humana",
      );

      // (b) no registo sem transição: a conversa já está em `dono`, e um *echo*
      // antigo é «sem efeito» — escreve só a actividade, que também não recua.
      const noRegisto = await abrir(tenantA, canalA);
      await forcar(noRegisto.id, "dono", tarde);
      const r = await maquina(app, () => cedo).disparar(
        { tenantId: tenantA, conversationId: noRegisto.id },
        "echo_do_dono",
      );
      assert.equal(r.resposta.tipo, "sem_efeito");
      assert.deepEqual(
        (await estadoDe(noRegisto.id)).actividade,
        tarde,
        "o registo de actividade recuou o instante",
      );
    });

    it("o mesmo gatilho repetido em serie produz uma transicao e um evento", async () => {
      const conversa = await abrir(tenantA, canalA);
      const antes = await contarEventos(conversa.id);
      const m = maquina(app);
      const primeira = await m.disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "echo_do_dono",
      );
      const segunda = await m.disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "echo_do_dono",
      );
      assert.equal(primeira.mudou, true);
      // A segunda é «sem efeito» — a célula `dono + echo_do_dono` — e escreve só
      // a actividade humana.
      assert.equal(segunda.mudou, false);
      assert.equal(segunda.resposta.tipo, "sem_efeito");
      assert.equal((await contarEventos(conversa.id)) - antes, 1);
    });
  });

  // ---------------------------------------------------------------------------
  describe("critério 3 — a corrida echo vs resposta do bot", () => {
    it("turno em t0, echo em t0+1s, resposta em t0+2s: 0 enviadas e 1 suprimida", async () => {
      const conversa = await abrir(tenantA, canalA);
      // t0+1 s: o *echo* passa a conversa a `dono` e registra a actividade.
      const r = await maquina(app, () => T_ECHO).disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "echo_do_dono",
      );
      assert.equal(r.mudou, true);
      // t0+2 s: a resposta do bot fica pronta. O turno começou em t0.
      const metricas = new MetricasDosModos();
      const decisao = await avaliar(
        { comTenant: comTenantDe(app2) as never, metricas },
        pedido(conversa.id, conversa.contactId, canalA, `c3-${conversa.id}`, T0),
      );
      assert.equal(decisao.passa, false);
      const saidas = await saidasDe(conversa.id);
      assert.equal(saidas.queued ?? 0, 0, "0 mensagens enviadas");
      assert.equal(saidas.suppressed_by_human, 1, "1 registo suprimido");
      assert.equal(metricas.ler()[`${METRICA_SUPRIMIDAS}:modo`], 1);
    });

    it("em `bot`, so a actividade humana posterior ao turno suprime", async () => {
      // Separa as duas metades do critério 2: o modo e o tempo. Aqui o modo é
      // `bot` e o que suprime é o instante.
      const conversa = await abrir(tenantA, canalA);
      await forcar(conversa.id, "bot", T_ECHO);
      const metricas = new MetricasDosModos();
      const decisao = await avaliar(
        { comTenant: comTenantDe(app) as never, metricas },
        pedido(conversa.id, conversa.contactId, canalA, `c3b-${conversa.id}`, T0),
      );
      assert.equal(decisao.passa, false);
      assert.equal(decisao.motivo, "actividade_humana");
      assert.equal((await saidasDe(conversa.id)).suppressed_by_human, 1);

      // E com a actividade humana **antes** do turno, passa.
      const outra = await abrir(tenantA, canalA);
      await forcar(outra.id, "bot", new Date(T0.getTime() - 1));
      const passou = await avaliar(
        { comTenant: comTenantDe(app) as never },
        pedido(outra.id, outra.contactId, canalA, `c3c-${outra.id}`, T0),
      );
      assert.equal(passou.passa, true);
      assert.deepEqual(await saidasDe(outra.id), {});
    });

    it(`as ${INTERCALACOES} intercalacoes: 0 mensagens depois de o echo estar registado`, async (t) => {
      const resultado = await correrIntercalacoes(SEMENTE);
      // Cada intercalação acaba com **exactamente um** desfecho: ou a guarda
      // passou (e não há linha suprimida), ou suprimiu (e não há envio).
      assert.equal(resultado.desfechos.length, INTERCALACOES);
      assert.equal(
        resultado.passou + resultado.suprimiu,
        INTERCALACOES,
        "houve intercalacoes sem desfecho, ou com os dois",
      );
      // **A propriedade do critério**: em todas as intercalações em que o
      // *echo* foi ordenado **primeiro**, 0 mensagens do bot saíram. É a
      // formulação verificável de «0 mensagens enviadas depois de o *echo*
      // estar registado» — nas outras, o *echo* ainda não estava registado
      // quando a guarda leu, e aí o envio é correcto (é a janela residual que
      // o §10.3 declara).
      assert.equal(resultado.enviadasComEchoPrimeiro, 0);
      // E a sanidade do ensaio: as duas ordens aconteceram. Sem isto, uma
      // semente degenerada dava 100 intercalações iguais e o teste passava sem
      // ter exercitado nada.
      assert.ok(resultado.echoPrimeiro >= 20, `echo primeiro: ${resultado.echoPrimeiro}`);
      assert.ok(resultado.guardaPrimeiro >= 20, `guarda primeiro: ${resultado.guardaPrimeiro}`);
      // **`t.diagnostic` e nao `console.log`**, e a diferenca e um gate: o
      // `log_policy lint` (gate 2) proibe o `console` em TypeScript de servico
      // — escreve-se pelo logger —, e um ensaio nao tem logger. O
      // `t.diagnostic` do `node:test` escreve um comentario TAP, que e onde a
      // suite em Python ja le o resto, e passa o lint. Apanhado pelo CI.
      t.diagnostic(
        `[KAM-018] ${INTERCALACOES} intercalacoes (semente 0x${SEMENTE.toString(16)}): ` +
          `${resultado.passou} passaram, ${resultado.suprimiu} suprimidas; ` +
          `echo primeiro ${resultado.echoPrimeiro} (0 enviadas), ` +
          `guarda primeiro ${resultado.guardaPrimeiro}`,
      );
    });

    it("as 100 intercalacoes sao reproduziveis: a mesma semente da a mesma sequencia", async () => {
      // **É este teste que impede o `Math.random()` de voltar.** Duas execuções
      // com a mesma semente dão a mesma sequência de desfechos; com um relógio
      // ou um aleatório do sistema, davam sequências diferentes e este teste
      // falhava.
      const uma = await correrIntercalacoes(SEMENTE);
      const outra = await correrIntercalacoes(SEMENTE);
      assert.deepEqual(uma.ordens, outra.ordens);
      assert.deepEqual(uma.desfechos, outra.desfechos);
    });
  });

  // ---------------------------------------------------------------------------
  describe("critério 4 — o silenciamento é por conversa e não por canal", () => {
    it("duas conversas do mesmo canal, A em `dono` e B em `bot`, respondem independentemente", async () => {
      const a = await abrir(tenantA, canalA);
      const b = await abrir(tenantA, canalA);
      // O mesmo canal, e é isso que o teste mede.
      const { rows } = await admin.query<{ n: string }>(
        "SELECT count(DISTINCT channel_id)::text AS n FROM platform.conversations " +
          "WHERE id IN ($1, $2)",
        [a.id, b.id],
      );
      assert.equal(rows[0]?.n, "1", "as duas conversas tem de estar no mesmo canal");

      await maquina(app, () => T_ECHO).disparar(
        { tenantId: tenantA, conversationId: a.id },
        "echo_do_dono",
      );
      assert.equal((await estadoDe(a.id)).mode, "dono");
      // **O modo de B não se moveu**, e é a metade do critério que se esquece.
      assert.equal((await estadoDe(b.id)).mode, MODO_POR_OMISSAO);

      const emA = await avaliar(
        { comTenant: comTenantDe(app) as never },
        pedido(a.id, a.contactId, canalA, `c4a-${a.id}`),
      );
      const emB = await avaliar(
        { comTenant: comTenantDe(app2) as never },
        pedido(b.id, b.contactId, canalA, `c4b-${b.id}`),
      );
      assert.equal(emA.passa, false, "a conversa em `dono` tinha de suprimir");
      assert.equal(emB.passa, true, "a conversa em `bot` do mesmo canal tinha de passar");
      assert.equal((await saidasDe(a.id)).suppressed_by_human, 1);
      assert.deepEqual(await saidasDe(b.id), {});
    });

    it("o opt-out de um contacto pausa as conversas dele nos dois canais, e so dele", async () => {
      // O `onOptOut` é por **contacto**, e um contacto pode ter conversa em mais
      // do que um canal do mesmo tenant.
      const segundo = await criarCanal(admin, tenantA);
      const contacto = await criarContacto(tenantA);
      const em1 = await abrir(tenantA, canalA, contacto);
      const em2 = await abrir(tenantA, segundo.id, contacto);
      const outro = await abrir(tenantA, canalA);

      const resultados = await maquina(app).onOptOut({
        tenantId: tenantA,
        contactId: contacto,
      });
      assert.equal(resultados.length, 2);
      assert.equal((await estadoDe(em1.id)).mode, "pausada");
      assert.equal((await estadoDe(em2.id)).mode, "pausada");
      assert.equal((await estadoDe(outro.id)).mode, MODO_POR_OMISSAO);

      // Repetir não escreve nada: a célula `pausada + opt_out` é sem efeito.
      const antes = await contarEventos(em1.id);
      const repetido = await maquina(app).onOptOut({
        tenantId: tenantA,
        contactId: contacto,
      });
      assert.deepEqual(
        repetido.map((r) => r.mudou),
        [false, false],
      );
      assert.equal((await contarEventos(em1.id)) - antes, 0);
    });
  });

  // ---------------------------------------------------------------------------
  describe("critério 5 — 0 invocações do AGR fora do modo `bot`", () => {
    it("nos tres modos que nao sao `bot`, o CHR entrega ao dono e 0 jobs vao ao AGR", async () => {
      const conversa = await abrir(tenantA, canalA);
      // **O resolvedor e o contacto sao os verdadeiros**: o `ResolvedorDeCanal`
      // do KAM-014 sobre a ligacao de `kamba_resolver`, e o `contactId` da
      // conversa que este ensaio criou. O que e falso e a entrega, porque e ela
      // que se mede.
      const jobs: AgentInvocation[] = [];
      const aoDono: unknown[] = [];
      const entrega: EntregaDoChr = {
        agr: async (invocacao) => {
          jobs.push(invocacao);
        },
        dono: async (destino) => {
          aoDono.push(destino);
        },
      };
      const chr = new Chr({
        resolvedor: new ResolvedorDeCanal(resolver as never),
        contacto: async () => ({ contactId: conversa.contactId }),
        entrega,
        quarentena: async () => undefined,
        metricas: new MetricasDoChr(),
        comTenant: comTenantDe(app),
      });

      function evento(marca: string): EventoDeEntrada {
        return {
          kind: "message",
          eventKey: `wamid-${marca}-${conversa.id}`,
          wabaId: "waba-ensaio",
          phoneNumberId: pnidA,
          waType: "text",
          interlocutor: { bsuid: null, telefone: "999123456789" },
        };
      }

      // Em `bot`: um *job* para o AGR. É o controlo positivo — sem ele, o zero
      // dos outros três não dizia nada.
      const emBot = await chr.tratar(evento("bot"));
      assert.equal(emBot.desfecho, "encaminhado");
      assert.equal(jobs.length, 1);

      for (const modo of ["dono", "humano", "pausada"] as const) {
        await forcar(conversa.id, modo, null);
        const antes: number = jobs.length;
        const resultado = await chr.tratar(evento(modo));
        assert.equal(resultado.desfecho, "entregue_ao_dono", modo);
        assert.equal(jobs.length - antes, 0, `${modo}: o AGR foi invocado`);
      }
      assert.equal(aoDono.length, 3);
      assert.equal(jobs.length, 1, "o unico job e o do controlo positivo");
    });

    it("o `abrirConversa` do CHR devolve o modo que a maquina escreveu", async () => {
      // A costura entre os dois módulos: o CHR decide pelo `mode` que a conversa
      // devolve, e é esta máquina que o escreve. Se o `SET` do
      // `SQL_ABRIR_CONVERSA` tocasse no `mode` (não toca — `kamba_app` não tinha
      // o privilégio e agora tem), uma entrada que chegasse desfazia o
      // silenciamento.
      const conversa = await abrir(tenantA, canalA);
      await maquina(app, () => T_ECHO).disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "echo_do_dono",
      );
      const lida = await comTenantReal(app, tenantA, () =>
        abrirConversa(
          app as never,
          { tenantId: tenantA, contactId: conversa.contactId, channelId: canalA },
          new Date(),
        ),
      );
      assert.equal(lida.id, conversa.id);
      assert.equal(lida.mode, "dono", "uma entrada que chega nao pode desfazer o silenciamento");
    });
  });

  // ---------------------------------------------------------------------------
  describe("critério 7 — o opt-out e o job das 24 h", () => {
    it("pausa o que passou das 24 h, conta do `last_human_activity_at`", async () => {
      const velha = await abrir(tenantA, canalA);
      const recente = await abrir(tenantA, canalA);
      await forcar(velha.id, "humano", new Date(T0.getTime() - 25 * 3600_000));
      await forcar(recente.id, "humano", new Date(T0.getTime() - 23 * 3600_000));
      const r = await maquina(app).pausarPorInactividade(tenantA);
      assert.ok(r.ids.includes(velha.id));
      assert.ok(!r.ids.includes(recente.id));
      assert.equal((await estadoDe(velha.id)).mode, "pausada");
      assert.equal((await estadoDe(recente.id)).mode, "humano");
      assert.equal(r.eventos.length, r.pausadas);
    });

    it("sem actividade humana, conta do `handoffs.opened_at` mais recente", async () => {
      // **É o caso que o critério descreve**: «24 h sem humano após handoff» —
      // uma conversa que passou a `humano` e onde ninguém respondeu tem a
      // coluna a `NULL`, e o relógio tem de contar de outro sítio.
      const antiga = await abrir(tenantA, canalA);
      const nova = await abrir(tenantA, canalA);
      await forcar(antiga.id, "humano", null);
      await forcar(nova.id, "humano", null);
      await admin.query(
        "INSERT INTO platform.handoffs (handoff_id, tenant_id, conversation_id, motivo, opened_at) " +
          "VALUES ($1, $2, $3, 'ensaio', $4)",
        [`h-antiga-${antiga.id}`, tenantA, antiga.id, new Date(T0.getTime() - 30 * 3600_000)],
      );
      // Dois *handoffs* na mesma conversa: conta-se do **mais recente**, e por
      // isso esta não é pausada.
      await admin.query(
        "INSERT INTO platform.handoffs (handoff_id, tenant_id, conversation_id, motivo, opened_at) " +
          "VALUES ($1, $2, $3, 'ensaio', $4)",
        [`h-nova-1-${nova.id}`, tenantA, nova.id, new Date(T0.getTime() - 40 * 3600_000)],
      );
      await admin.query(
        "INSERT INTO platform.handoffs (handoff_id, tenant_id, conversation_id, motivo, opened_at) " +
          "VALUES ($1, $2, $3, 'ensaio', $4)",
        [`h-nova-2-${nova.id}`, tenantA, nova.id, new Date(T0.getTime() - 2 * 3600_000)],
      );
      const r = await maquina(app).pausarPorInactividade(tenantA);
      assert.ok(r.ids.includes(antiga.id));
      assert.ok(!r.ids.includes(nova.id));
    });

    it("uma conversa em `humano` sem actividade e sem handoff NAO e pausada", async () => {
      // O lado seguro, declarado no `SQL_PAUSAR_POR_INACTIVIDADE`: ficar em
      // `humano` mantém o bot calado, e o invariante do §10.2 é que o bot não
      // interrompe uma pessoa. Pausar por omissão era deixar o assistente
      // retomar uma conversa cuja história não conhecemos.
      const orfa = await abrir(tenantA, canalA);
      await forcar(orfa.id, "humano", null);
      const r = await maquina(app).pausarPorInactividade(tenantA);
      assert.ok(!r.ids.includes(orfa.id));
      assert.equal((await estadoDe(orfa.id)).mode, "humano");
      // E depois de ser pausada à mão, deixa de aparecer: o *job* é idempotente.
      await forcar(orfa.id, "pausada", null);
      assert.ok(!(await maquina(app).pausarPorInactividade(tenantA)).ids.includes(orfa.id));
    });

    it("correr o job duas vezes seguidas pausa N e depois 0", async () => {
      const velha = await abrir(tenantA, canalA);
      await forcar(velha.id, "humano", new Date(T0.getTime() - 25 * 3600_000));
      const m = maquina(app);
      const primeira = await m.pausarPorInactividade(tenantA);
      assert.ok(primeira.ids.includes(velha.id));
      const segunda = await m.pausarPorInactividade(tenantA);
      assert.ok(!segunda.ids.includes(velha.id));
    });
  });

  // ---------------------------------------------------------------------------
  describe("critério 6 — o evento vai para o outbox, na mesma transacção", () => {
    it("uma transicao deixa um `conversation.mode_changed` no outbox", async () => {
      const conversa = await abrir(tenantA, canalA);
      const r = await maquina(app, () => T_ECHO).disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "echo_do_dono",
      );
      assert.ok(r.eventoId !== null);
      // **O `payload` vive dentro do `envelope`**, e não é uma coluna: a `0004`
      // dá à `events_outbox` um `envelope jsonb` que o `evt_emitir` constrói em
      // SQL (ADR-009), e é lá que o `classe_pii` e a carga estão. Medido — a
      // primeira versão desta asserção pediu uma coluna `payload` e levou um
      // `42703`.
      const { rows } = await admin.query<{
        tipo: string;
        versao: number;
        envelope: {
          payload: { thread_id: string; channel_mode: string };
          classe_pii: string;
        };
      }>(
        "SELECT tipo, versao, envelope FROM platform.events_outbox WHERE event_id = $1",
        [r.eventoId],
      );
      assert.equal(rows.length, 1);
      assert.equal(rows[0]?.tipo, "conversation.mode_changed");
      assert.equal(rows[0]?.versao, 2);
      assert.equal(rows[0]?.envelope.classe_pii, "P0");
      // **`dono` sai como `humano`**, e a perda está declarada em
      // `MODO_PARA_CHANNEL_MODE`: o contrato publicado tem três valores.
      assert.equal(rows[0]?.envelope.payload.channel_mode, "humano");
      assert.equal(rows[0]?.envelope.payload.thread_id, `${tenantA}:${conversa.contactId}`);
    });

    it("o payload nao leva telefone, conteudo nem o id da conversa", async () => {
      // O DoD «Privacidade». O `thread_id` leva `tenant_id` e `contact_id`, que
      // são UUID nossos (o `contact_id` é a referência opaca do KAM-008); o
      // `conversation_id` vai no `agregado_id` do envelope, que é onde se
      // audita, e não na carga.
      const conversa = await abrir(tenantA, canalA);
      const r = await maquina(app).disparar(
        { tenantId: tenantA, conversationId: conversa.id },
        "opt_out",
      );
      const { rows } = await admin.query<{
        envelope: { payload: Record<string, unknown> };
        agregado_id: string;
      }>(
        "SELECT envelope, agregado_id FROM platform.events_outbox WHERE event_id = $1",
        [r.eventoId],
      );
      const payload = rows[0]?.envelope.payload ?? {};
      assert.deepEqual(Object.keys(payload).sort(), ["channel_mode", "thread_id"]);
      assert.equal(rows[0]?.agregado_id, conversa.id);
      const texto = JSON.stringify(payload);
      assert.ok(!texto.includes("999"), "um telefone sintetico chegou ao payload");
    });

    it("se a emissao levantar, a transicao e desfeita", async () => {
      // A propriedade que a porta receber o cliente garante: as duas escritas
      // confirmam juntas ou não confirma nenhuma. É o contrário da janela que o
      // `chr/eventos.ts` tem de declarar para o `contact.merged`.
      const conversa = await abrir(tenantA, canalA);
      const m = new MaquinaDeModos({
        comTenant: comTenantDe(app) as never,
        emitir: async () => {
          throw new Error("falha de ensaio na emissao");
        },
        agora: () => T0,
      });
      await assert.rejects(
        () => m.disparar({ tenantId: tenantA, conversationId: conversa.id }, "opt_out"),
        /falha de ensaio na emissao/,
      );
      assert.equal((await estadoDe(conversa.id)).mode, MODO_POR_OMISSAO);
    });
  });

  // ---------------------------------------------------------------------------
  describe("DoD — o privilégio da revisão 0016, por coluna", () => {
    it("`kamba_app` consegue agora escrever `mode` e `last_human_activity_at`", async () => {
      // A `0009` recusava-o, e o KAM-014 escreveu-o no seu critério 7: «`kamba_app`
      // **nao consegue** alterá-lo — o privilégio não existe». Esta revisão dá-lho,
      // e é esta asserção que o afirma.
      const conversa = await abrir(tenantA, canalA);
      await comTenantReal(app, tenantA, async () => {
        await app.query(
          "UPDATE platform.conversations SET mode = 'dono', last_human_activity_at = now() " +
            "WHERE tenant_id = $1 AND id = $2",
          [tenantA, conversa.id],
        );
      });
      assert.equal((await estadoDe(conversa.id)).mode, "dono");
    });

    it("`kamba_app` continua sem poder reescrever a identidade da conversa", async () => {
      // As quatro colunas que a `0016` **não** concede. Mover uma conversa de
      // contacto e de canal é reescrever a sua identidade, e quem o faz numa
      // fusão é o `kamba_identity`.
      const conversa = await abrir(tenantA, canalA);
      for (const coluna of ["contact_id", "channel_id", "tenant_id", "id"]) {
        await assert.rejects(
          () =>
            comTenantReal(app, tenantA, async () => {
              await app.query(
                `UPDATE platform.conversations SET ${coluna} = $1 WHERE id = $2`,
                [conversa.contactId, conversa.id],
              );
            }),
          /permission denied|42501/,
          coluna,
        );
      }
    });

    it("`kamba_resolver` nao le nem escreve conversas", async () => {
      const conversa = await abrir(tenantA, canalA);
      await assert.rejects(
        () => resolver.query("SELECT mode FROM platform.conversations WHERE id = $1", [conversa.id]),
        /permission denied|42501/,
      );
      await assert.rejects(
        () =>
          resolver.query("UPDATE platform.conversations SET mode = 'bot' WHERE id = $1", [
            conversa.id,
          ]),
        /permission denied|42501/,
      );
    });
  });

  // ---------------------------------------------------------------------------
  describe("DoD — isolamento de tenant (X-03)", () => {
    it("com o contexto de A, o modo de B nao se le nem se muda", async () => {
      const deB = await abrir(tenantB, canalB);
      await forcar(deB.id, "humano", null);
      // Ler: zero linhas, não a conversa de B.
      const lido = await comTenantReal(app, tenantA, () =>
        app.query(SQL_CONVERSA_PARA_MODO, [tenantB, deB.id]),
      );
      assert.equal((lido as { rows: unknown[] }).rows.length, 0);
      // Mudar: a máquina não encontra a conversa, e **não escreve**.
      await assert.rejects(
        () => maquina(app).disparar({ tenantId: tenantA, conversationId: deB.id }, "opt_out"),
        /nao ha conversa com este id neste tenant/,
      );
      assert.equal((await estadoDe(deB.id)).mode, "humano");
    });

    it("a guarda de A sobre uma conversa de B recusa o envio, e nao o deixa passar", async () => {
      // O lado seguro: uma conversa que a RLS não vê é tratada como «não está em
      // `bot`». Deixar passar era o assistente de A a enviar sobre uma conversa
      // de B.
      const deB = await abrir(tenantB, canalB);
      const decisao = await avaliar(
        { comTenant: comTenantDe(app) as never },
        {
          ...pedido(deB.id, deB.contactId, canalA, `x03-${deB.id}`),
          tenantId: tenantA,
        },
      );
      assert.equal(decisao.passa, false);
      // **E não escreve linha nenhuma**, nem para A nem para B: a
      // `outbound_messages_conversation_fk` é composta com o `tenant_id`, e um
      // `INSERT` de A a apontar para a conversa de B morria com `23503` — um
      // `throw` no passo 3 de sete do adapter, que deixava o turno sem resposta
      // e sem registo. Foi este teste que o apanhou.
      assert.equal(decisao.suprimida, null);
      assert.deepEqual(await saidasDe(deB.id), {});
    });
  });

  // ---------------------------------------------------------------------------
  /** Quantos `conversation.mode_changed` existem no outbox para uma conversa. */
  async function contarEventos(conversationId: string): Promise<number> {
    const { rows } = await admin.query<{ n: string }>(
      "SELECT count(*)::text AS n FROM platform.events_outbox " +
        "WHERE tipo = 'conversation.mode_changed' AND agregado_id = $1",
      [conversationId],
    );
    return Number(rows[0]?.n ?? "0");
  }

  /** O desfecho de uma intercalação. */
  interface Intercalacao {
    readonly ordem: "echo_primeiro" | "guarda_primeiro";
    readonly desfecho: "passou" | "suprimiu";
  }

  /**
   * Corre as 100 intercalações com a semente dada, sobre **uma** conversa que se
   * reinicia a cada volta.
   *
   * Uma conversa só e não 100: criar 100 conversas e 100 contactos por execução
   * fazia o ensaio escrever 400 linhas e, com o `reproduziveis` a correr o ciclo
   * duas vezes, 1 200. A propriedade que se mede é por volta, e reiniciar a
   * conversa entre voltas dá-a com o mesmo rigor.
   *
   * A chave de idempotência do envio muda a cada volta (`i` no nome): sem isso, o
   * `ON CONFLICT` da segunda supressão devolvia vazio e as contagens de saída
   * ficavam presas na primeira volta.
   */
  async function correrIntercalacoes(semente: number): Promise<{
    readonly ordens: readonly string[];
    readonly desfechos: readonly string[];
    readonly passou: number;
    readonly suprimiu: number;
    readonly echoPrimeiro: number;
    readonly guardaPrimeiro: number;
    readonly enviadasComEchoPrimeiro: number;
  }> {
    const aleatorio = prng(semente);
    const conversa = await abrir(tenantA, canalA);
    const voltas: Intercalacao[] = [];
    for (let i = 0; i < INTERCALACOES; i += 1) {
      // Reinicia a volta: `bot`, sem actividade humana, sem linhas de saída.
      await admin.query("DELETE FROM platform.outbound_messages WHERE conversation_id = $1", [
        conversa.id,
      ]);
      await forcar(conversa.id, "bot", null);

      const echoPrimeiro = aleatorio() < 0.5;
      const transicao = () =>
        maquina(app, () => T_ECHO).disparar(
          { tenantId: tenantA, conversationId: conversa.id },
          "echo_do_dono",
        );
      const guarda = () =>
        avaliar(
          { comTenant: comTenantDe(app2) as never },
          pedido(conversa.id, conversa.contactId, canalA, `corrida-${semente}-${i}`, T0),
        );

      let passou: boolean;
      if (echoPrimeiro) {
        // O *echo* **confirma** antes de a guarda começar: é o caso que o
        // critério nomeia, e aqui 0 mensagens têm de sair.
        await transicao();
        passou = (await guarda()).passa;
      } else {
        // A guarda corre inteira primeiro. O envio é legítimo: o *echo* ainda
        // não estava registado quando ela leu.
        passou = (await guarda()).passa;
        await transicao();
      }
      voltas.push({
        ordem: echoPrimeiro ? "echo_primeiro" : "guarda_primeiro",
        desfecho: passou ? "passou" : "suprimiu",
      });
    }
    return {
      ordens: voltas.map((v) => v.ordem),
      desfechos: voltas.map((v) => v.desfecho),
      passou: voltas.filter((v) => v.desfecho === "passou").length,
      suprimiu: voltas.filter((v) => v.desfecho === "suprimiu").length,
      echoPrimeiro: voltas.filter((v) => v.ordem === "echo_primeiro").length,
      guardaPrimeiro: voltas.filter((v) => v.ordem === "guarda_primeiro").length,
      enviadasComEchoPrimeiro: voltas.filter(
        (v) => v.ordem === "echo_primeiro" && v.desfecho === "passou",
      ).length,
    };
  }
});

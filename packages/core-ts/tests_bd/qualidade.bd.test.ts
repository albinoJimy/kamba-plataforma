/**
 * A gestão de canal contra um PostgreSQL real (KAM-021).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **A idempotência do critério 6 é da base e não do código.** O
 *    `ON CONFLICT (tenant_id, event_key) DO NOTHING RETURNING id` devolve vazio
 *    na segunda — e, com duas ligações a disputar, é o índice único que
 *    serializa. Uma base falsa devolve o que se lhe mandou devolver, e não há
 *    maneira de ela errar.
 * 2. **O `UPDATE` não existe na tabela nova.** Isto é o oposto de um teste de
 *    política: não se afirma que o módulo não corrige um registo, afirma-se que
 *    o `kamba_app` **não tem o privilégio** e que uma tentativa levanta
 *    `42501`. Um teste do lado do código prova o que o código faz hoje; este
 *    prova o que nenhum código pode fazer.
 * 3. **Cada ticket levanta apenas o motivo que põe.** Um canal `restrito` com
 *    `motivo_restricao = 'payment_method'` não se repõe com um `GREEN`, e o
 *    predicado que o impede está no `SQL_REPOR` — contra a coluna, não contra um
 *    `if`.
 * 4. **A medição do escalão é uma junção, um `DISTINCT` e um intervalo.** O
 *    `SQL_UNICOS_FORA_DA_JANELA` liga `outbound_messages` a `tenant_channels`
 *    porque a primeira guarda `channel_id` e não o número, conta contactos
 *    distintos e corta às 24 h **móveis**. Nada disto se prova sem planeador.
 * 5. **A RLS recusa o que o código deixaria passar** (X-03). Com o contexto de
 *    A, as transições de B não se leem nem se escrevem — e com `FORCE`, nem
 *    como dono da tabela.
 * 6. **O critério 9 de ponta a ponta.** A `Saida` do KAM-015, com a porta de
 *    estado ligada a uma consulta real, recusa um template num canal que **esta
 *    bateria** acabou de restringir. É o único sítio onde os dois módulos se
 *    encontram sobre a mesma linha.
 *
 * O que **não** se mede aqui: a matriz de acção, a tradução do vocabulário, o
 * rácio, a fracção de aviso e as métricas vivem em `tests/qualidade.test.ts`,
 * porque são funções puras e uma base real não acrescenta nada à prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import {
  Saida,
  type Corpo,
  type Destinatario,
  type EstadoParaEnvio,
  type Pedido,
} from "../src/outbound/index.ts";
import {
  GestaoDeCanal,
  MetricasDaQualidade,
  METRICA_EVENTOS,
  METRICA_RESTRICOES,
} from "../src/qualidade/index.ts";
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
 * transacção, e com `true` a definição desaparecia antes da instrução seguinte
 * — com RLS `FORCE`, o `kamba_app` ficava sem contexto e via zero linhas.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

/** Uma chave de idempotência distinta por teste. O resumo que o critério 6 pede. */
let semente = 0;
function chave(marca: string): string {
  semente += 1;
  return `${marca}-${semente}`;
}

const TEXTO: Corpo = { tipo: "texto", texto: "Bom dia" };

describe("a gestao de canal contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a corrida pela chave
  // unica so e real com duas sessoes. Com uma, os dois `INSERT` saem em serie
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

  /** Um contacto novo do *tenant*, criado pelo administrador. */
  async function criarContacto(tenant: string): Promise<string> {
    const { rows } = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenant],
    );
    return rows[0]?.contact_id ?? "";
  }

  /** Uma conversa com a janela **aberta**, criada pelo administrador. */
  async function abrirConversa(tenant: string, canal: string): Promise<string> {
    const contactId = await criarContacto(tenant);
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
   * A ligação é parâmetro para que o teste da corrida possa dar-lhe a segunda.
   * A conversão de tipo é a mesma do `outbound.bd.test.ts`, e é honesta num
   * ensaio: quem escreve o SQL e quem escreve o parâmetro de tipo é a mesma
   * linha de teste.
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

  /** A `GestaoDeCanal` de um *tenant*, com métricas próprias e portas espiãs. */
  function gestaoDe(
    tenant: string,
    opcoes: { readonly agora?: Date; readonly cliente?: pg.Client } = {},
  ): {
    gestao: GestaoDeCanal;
    metricas: MetricasDaQualidade;
    emitidos: string[];
    invalidados: string[];
  } {
    const metricas = new MetricasDaQualidade();
    const emitidos: string[] = [];
    const invalidados: string[] = [];
    const gestao = new GestaoDeCanal({
      bd: bdDe(tenant, opcoes.cliente ?? app),
      metricas,
      emitir: async (_t, channelId, _p, motivo) => {
        emitidos.push(`${channelId}:${motivo}`);
      },
      invalidar: (channelId) => {
        invalidados.push(channelId);
      },
      ...(opcoes.agora === undefined ? {} : { agora: () => opcoes.agora as Date }),
    });
    return { gestao, metricas, emitidos, invalidados };
  }

  /** O canal, lido pelo **administrador** (sem RLS pelo meio). */
  async function canalCru(canal: string): Promise<{
    estado: string;
    qualidade: string | null;
    motivo: string | null;
    escalao: string | null;
    maxNumeros: number | null;
  }> {
    const { rows } = await admin.query<{
      estado: string;
      quality_rating: string | null;
      motivo_restricao: string | null;
      messaging_limit: string | null;
      max_phone_numbers_per_business: number | null;
    }>(
      "SELECT estado, quality_rating, motivo_restricao, messaging_limit, " +
        "max_phone_numbers_per_business FROM platform.tenant_channels WHERE id = $1",
      [canal],
    );
    const linha = rows[0];
    return {
      estado: linha?.estado ?? "",
      qualidade: linha?.quality_rating ?? null,
      motivo: linha?.motivo_restricao ?? null,
      escalao: linha?.messaging_limit ?? null,
      maxNumeros:
        linha?.max_phone_numbers_per_business === null ||
        linha?.max_phone_numbers_per_business === undefined
          ? null
          : Number(linha.max_phone_numbers_per_business),
    };
  }

  /** Põe o canal num estado de partida, como administrador. */
  async function semear(
    canal: string,
    estado: string,
    qualidade: string | null,
    motivo: string | null = null,
  ): Promise<void> {
    await admin.query(
      "UPDATE platform.tenant_channels SET estado = $2, quality_rating = $3, " +
        "motivo_restricao = $4 WHERE id = $1",
      [canal, estado, qualidade, motivo],
    );
  }

  /** As linhas do registo de um canal, pelo administrador. */
  async function registoDe(canal: string): Promise<
    readonly {
      readonly evento: string;
      readonly valor_anterior: string | null;
      readonly valor_novo: string;
      readonly event_key: string;
    }[]
  > {
    const { rows } = await admin.query(
      "SELECT evento, valor_anterior, valor_novo, event_key " +
        "FROM platform.channel_quality_log WHERE channel_id = $1 " +
        "ORDER BY ocorrido_em, event_key",
      [canal],
    );
    return rows as never;
  }

  /**
   * Uma mensagem de saída já entregue, para o medidor do escalão contar.
   *
   * Escrita pelo administrador de propósito: o que esta bateria mede é a
   * **consulta**, e fazer a linha nascer pelo adapter do KAM-015 trazia o
   * `GraphFalso`, a janela e a decisão para dentro de um teste que é sobre um
   * `count(DISTINCT …)`.
   */
  async function enviada(
    tenant: string,
    canal: string,
    contacto: string,
    conversa: string,
    kind: string,
    state: string,
    hamais: string,
  ): Promise<void> {
    // O `outbound_messages_template_ck` da `0010` exige `template_name` em tudo
    // o que não é `service`, e **não o exige** num `service`: as duas metades
    // do `CHECK` são exclusivas. Foi esta linha que a primeira versão desta
    // bateria não tinha, e o `23514` apanhou-a no primeiro gate.
    await admin.query(
      "INSERT INTO platform.outbound_messages " +
        "(tenant_id, channel_id, contact_id, conversation_id, idempotency_key, " +
        " kind, state, template_name, created_at) " +
        `VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now() - interval '${hamais}')`,
      [
        tenant,
        canal,
        contacto,
        conversa,
        chave("saida"),
        kind,
        state,
        kind === "service" ? null : "medidor",
      ],
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

    tenantA = await criarTenant(admin, "qualidade-a");
    tenantB = await criarTenant(admin, "qualidade-b");
    const canalDeA = await criarCanal(admin, tenantA);
    const canalDeB = await criarCanal(admin, tenantB);
    canalA = canalDeA.id;
    canalB = canalDeB.id;
    pnidA = canalDeA.phoneNumberId;
    pnidB = canalDeB.phoneNumberId;
    const a = (await abrirConversa(tenantA, canalA)).split("|");
    conversaA = a[0] ?? "";
    contactoA = a[1] ?? "";
    graph = new GraphFalso(new GeradorDeFixtures("qualidade-bd"));
  });

  after(async () => {
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

  // --------------------------------------- o registo da transicao (criterio 1)

  describe("o registo da transicao (criterio 1)", () => {
    it("**o bruto fica no registo e o canonico no canal**", async () => {
      await semear(canalA, "ativo", null);
      const { gestao } = gestaoDe(tenantA);
      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "GREEN", chave("g"));

      assert.equal(transicao?.registou, true);
      assert.equal(transicao?.qualidade, "green");
      // **As duas colunas guardam coisas diferentes, e e isto que o prova.**
      assert.equal((await canalCru(canalA)).qualidade, "green");
      const registo = await registoDe(canalA);
      assert.equal(registo.at(-1)?.valor_novo, "GREEN");
      assert.equal(registo.at(-1)?.evento, "phone_number_quality_update");
    });

    it("**um valor que a Meta inventar fica registado e nao falha**", async () => {
      // O critério 1 por extenso: «outro valor registado como desconhecido sem
      // falhar». O `PURPLE` não existe no vocabulário de hoje — e o «Flagged»
      // existia e foi eliminado a 2025-10-07 (`E1` §5), pelo que o vocabulário
      // **já mudou uma vez**. Um domínio fechado no `valor_novo` transformava a
      // próxima mudança numa falha de inserção.
      await semear(canalA, "ativo", "green");
      const { gestao } = gestaoDe(tenantA);
      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "PURPLE", chave("p"));

      assert.equal(transicao?.registou, true);
      assert.equal(transicao?.qualidade, null);
      // O `quality_rating` **não se toca**: mudar o estado corrente para um
      // valor que não se compreende era pior do que não o mudar.
      assert.equal((await canalCru(canalA)).qualidade, "green");
      assert.equal((await registoDe(canalA)).at(-1)?.valor_novo, "PURPLE");
    });

    it("**o valor anterior do registo e o que estava na coluna**", async () => {
      await semear(canalA, "ativo", "yellow");
      const { gestao } = gestaoDe(tenantA);
      await gestao.qualidadeDoNumero(tenantA, pnidA, "GREEN", chave("ant"));
      assert.equal((await registoDe(canalA)).at(-1)?.valor_anterior, "yellow");
    });

    it("**um canal que nao existe nao escreve nada e nao levanta**", async () => {
      const { gestao } = gestaoDe(tenantA);
      const antes = (await registoDe(canalA)).length;
      assert.equal(
        await gestao.qualidadeDoNumero(tenantA, "pnid-que-nao-existe", "RED", chave("x")),
        null,
      );
      assert.equal((await registoDe(canalA)).length, antes);
    });
  });

  // ----------------------------------- idempotencia da transicao (criterio 6)

  describe("idempotencia da transicao (criterio 6)", () => {
    it("**o mesmo event_key duas vezes: uma linha e uma transicao**", async () => {
      await semear(canalA, "ativo", "green");
      const { gestao, metricas } = gestaoDe(tenantA);
      const k = chave("idem");

      const primeira = await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", k);
      const segunda = await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", k);

      assert.equal(primeira?.registou, true);
      assert.equal(primeira?.restringiu, true);
      // A segunda **para no passo 2** e não toca em nada.
      assert.equal(segunda?.registou, false);
      assert.equal(segunda?.restringiu, false);
      assert.equal(
        (await registoDe(canalA)).filter((l) => l.event_key === k).length,
        1,
      );
      // Um evento contado duas vezes é um painel a mentir sobre quantos
      // *webhooks* a Meta mandou.
      assert.equal(metricas.ler()[`${METRICA_EVENTOS}:phone_number_quality_update`], 1);
    });

    it("**dois eventos iguais em paralelo: uma linha e um evento**", async () => {
      await semear(canalA, "ativo", "green");
      const k = chave("corrida");
      const um = gestaoDe(tenantA);
      const dois = gestaoDe(tenantA, { cliente: app2 });

      const [a, b] = await Promise.all([
        um.gestao.qualidadeDoNumero(tenantA, pnidA, "RED", k),
        dois.gestao.qualidadeDoNumero(tenantA, pnidA, "RED", k),
      ]);

      // **Um registou e o outro não**, e quem decide é o índice único: as duas
      // ligações disputam de verdade. Sem o `ON CONFLICT`, uma delas levantava
      // `23505` e o *webhook* era repetido pela Meta para sempre.
      assert.equal([a?.registou, b?.registou].filter(Boolean).length, 1);
      assert.equal(
        (await registoDe(canalA)).filter((l) => l.event_key === k).length,
        1,
      );
      // E **uma** restrição, logo **um** `channel.updated`.
      assert.equal([...um.emitidos, ...dois.emitidos].length, 1);
      assert.equal((await canalCru(canalA)).estado, "restrito");
    });

    it("**a mesma chave em dois tenants da duas linhas**", async () => {
      // A unicidade é **composta** com o `tenant_id`, pela razão da emenda
      // 1.21: com unicidade global, um evento do *tenant* B que calhasse na
      // mesma chave era deduplicado em silêncio contra uma linha de A — e B
      // ficava sem a transição dele sem ninguém ver.
      await semear(canalA, "ativo", "green");
      await semear(canalB, "ativo", "green");
      const k = chave("partilhada");

      assert.equal(
        (await gestaoDe(tenantA).gestao.qualidadeDoNumero(tenantA, pnidA, "RED", k))
          ?.registou,
        true,
      );
      assert.equal(
        (await gestaoDe(tenantB).gestao.qualidadeDoNumero(tenantB, pnidB, "RED", k))
          ?.registou,
        true,
      );
      assert.equal((await registoDe(canalA)).filter((l) => l.event_key === k).length, 1);
      assert.equal((await registoDe(canalB)).filter((l) => l.event_key === k).length, 1);
    });
  });

  // ------------------------------------- a restricao e a reposicao (criterio 2)

  describe("a restricao e a reposicao (criterio 2)", () => {
    it("**o RED restringe e escreve o motivo na mesma instrucao**", async () => {
      await semear(canalA, "ativo", "green");
      const { gestao, metricas, emitidos, invalidados } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("r"));

      assert.equal(transicao?.restringiu, true);
      const cru = await canalCru(canalA);
      // **As duas colunas juntas**, e e isso que impede a janela em que o canal
      // esta `restrito` e nao diz porque.
      assert.equal(cru.estado, "restrito");
      assert.equal(cru.motivo, "quality");
      assert.equal(metricas.ler()[`${METRICA_RESTRICOES}:quality`], 1);
      assert.deepEqual(emitidos, [`${canalA}:quality`]);
      assert.deepEqual(invalidados, [canalA]);
    });

    it("**um RED repetido com chave nova nao e uma transicao nova**", async () => {
      // Chave **diferente** — logo o registo aceita a linha —, e o canal já está
      // `restrito`. O que impede a segunda transição é o
      // `WHERE estado <> 'restrito'` do `UPDATE`, não a idempotência da chave: o
      // critério pede «1 transição», e um `red` repetido não é uma transição.
      await semear(canalA, "restrito", "red", "quality");
      const { gestao, emitidos } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("r2"));

      assert.equal(transicao?.registou, true);
      assert.equal(transicao?.restringiu, false);
      assert.deepEqual(emitidos, [], "um `channel.updated` sem transicao e ruido");
    });

    it("**o GREEN repoe o canal, e emite**", async () => {
      await semear(canalA, "restrito", "red", "quality");
      const { gestao, emitidos, invalidados } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "GREEN", chave("rep"));

      assert.equal(transicao?.reposto, true);
      const cru = await canalCru(canalA);
      assert.equal(cru.estado, "ativo");
      assert.equal(cru.motivo, null, "o motivo sai com o estado");
      assert.equal(cru.qualidade, "green");
      assert.deepEqual(emitidos, [`${canalA}:quality`]);
      assert.deepEqual(invalidados, [canalA]);
    });

    it("**um canal restrito por payment_method nao se repoe com GREEN**", async () => {
      // **O centro desta bateria.** A Meta deixou de entregar por falta de
      // método de pagamento (KAM-023) e o `quality_rating` voltou a `green` — o
      // que acontece, porque são coisas independentes. Repor o estado aqui era
      // desfazer a decisão de outro ticket a partir de um sinal que não lhe diz
      // respeito, e o resultado prático era uma loja a voltar a `ativo` com a
      // Meta ainda a recusar as mensagens dela.
      await semear(canalA, "restrito", "red", "payment_method");
      const { gestao, emitidos } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "GREEN", chave("pm"));

      assert.equal(transicao?.registou, true);
      assert.equal(transicao?.reposto, false);
      const cru = await canalCru(canalA);
      assert.equal(cru.estado, "restrito");
      assert.equal(cru.motivo, "payment_method", "o motivo do outro ticket fica");
      // A **qualidade** escreve-se: ela é um facto sobre o número, e o critério
      // 1 manda guardá-la. O que não se faz é tirar a conclusão de estado.
      assert.equal(cru.qualidade, "green");
      assert.deepEqual(emitidos, []);
    });

    it("**dois RED com chaves diferentes em paralelo: uma transicao e um evento**", async () => {
      // **Esta é a asserção que prende o `WHERE estado <> 'restrito'` do
      // `SQL_RESTRINGIR`, e não havia nenhuma.** A mutação que o apagou
      // **sobreviveu** à primeira execução da prova, e a razão é instrutiva: no
      // caminho sequencial o predicado é redundante, porque o
      // `accaoDaQualidade` já devolve `"nada"` quando o canal está `restrito`.
      // Quem o torna necessário é a concorrência — duas chaves **diferentes**
      // passam as duas pelo registo, as duas leem `ativo`, e as duas decidem
      // restringir. Sem o predicado, as duas escrevem e as duas emitem
      // `channel.updated`; com ele, a base serializa e o segundo vê o
      // `RETURNING` vazio.
      //
      // O teste da corrida que já existia usa a **mesma** chave, pelo que prova
      // o índice único e não o `UPDATE`: as duas provas são precisas, e uma não
      // substitui a outra.
      await semear(canalA, "ativo", "green");
      const um = gestaoDe(tenantA);
      const dois = gestaoDe(tenantA, { cliente: app2 });

      const [a, b] = await Promise.all([
        um.gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("corrida-a")),
        dois.gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("corrida-b")),
      ]);

      // As **duas** registaram: as chaves são diferentes e o registo é um facto.
      assert.equal([a?.registou, b?.registou].filter(Boolean).length, 2);
      // Mas **uma** restringiu, e **um** evento saiu.
      assert.equal([a?.restringiu, b?.restringiu].filter(Boolean).length, 1);
      assert.equal([...um.emitidos, ...dois.emitidos].length, 1);
      assert.equal((await canalCru(canalA)).estado, "restrito");
    });

    it("**um canal ativo ja marcado por payment_method mantem a marca ao restringir**", async () => {
      // O `COALESCE(motivo_restricao, 'quality')` do `SQL_RESTRINGIR` parece
      // inalcançável — um canal `restrito` nunca passa pelo `UPDATE`, que tem
      // `estado <> 'restrito'` — e **não é**: a `marcarRestricao` do KAM-023
      // escreve o `motivo_restricao` **sem** mexer no `estado`, pelo que um
      // canal `ativo` com a marca de falta de pagamento é um estado que existe.
      // Quando a qualidade cai nesse canal, a primeira marca é a que fica: o
      // motivo que o KAM-115 vai contar ao dono é a causa original, não a
      // consequência. Sem este teste a linha era código morto, e uma mutação
      // nela seria imortal.
      await semear(canalA, "ativo", "green", "payment_method");
      const { gestao } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("marca"));

      assert.equal(transicao?.restringiu, true);
      const cru = await canalCru(canalA);
      assert.equal(cru.estado, "restrito");
      assert.equal(cru.motivo, "payment_method", "a primeira marca e a que fica");
    });

    it("**o YELLOW nao restringe, e marca os templates aprovados**", async () => {
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) VALUES " +
          "($1, 'amarelo_aprovado', 'pt_PT', 'utility', 'approved', 'resumo'), " +
          "($1, 'amarelo_pendente', 'pt_PT', 'utility', 'pending', 'resumo')",
        [tenantA],
      );
      await semear(canalA, "ativo", "green");
      const { gestao } = gestaoDe(tenantA);

      const transicao = await gestao.qualidadeDoNumero(tenantA, pnidA, "YELLOW", chave("y"));

      assert.equal(transicao?.avisou, true);
      assert.equal(transicao?.restringiu, false);
      assert.equal((await canalCru(canalA)).estado, "ativo", "um aviso nao corta a loja");

      const { rows } = await admin.query<{ name: string; quality: string | null }>(
        "SELECT name, quality FROM platform.message_templates " +
          "WHERE tenant_id = $1 AND name LIKE 'amarelo_%' ORDER BY name",
        [tenantA],
      );
      // **Só os aprovados**: um `pending` ainda está com a Meta e não tem
      // revisão que fazer.
      assert.deepEqual(rows, [
        { name: "amarelo_aprovado", quality: "yellow" },
        { name: "amarelo_pendente", quality: null },
      ]);
    });
  });

  // ------------------------------------------- o registo nao se corrige (DoD)

  describe("o registo nao se corrige: o privilegio nem existe", () => {
    it("**o kamba_app nao tem UPDATE em channel_quality_log**", async () => {
      // Isto é o oposto de um teste de política. Não se afirma que o módulo não
      // corrige uma linha — afirma-se que **nenhum código que corra como
      // `kamba_app` o pode fazer**. Uma linha é o facto de a Meta ter dito uma
      // coisa a uma hora, e um facto não se corrige.
      await semear(canalA, "ativo", "green");
      await gestaoDe(tenantA).gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("ro"));
      await definirContexto(app, tenantA);

      await assert.rejects(
        () =>
          app.query(
            "UPDATE platform.channel_quality_log SET valor_novo = 'GREEN' " +
              "WHERE tenant_id = $1",
            [tenantA],
          ),
        (erro: { code?: string }) => erro.code === "42501",
      );
    });

    it("**nem DELETE**, e e a mesma razao", async () => {
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query("DELETE FROM platform.channel_quality_log WHERE tenant_id = $1", [
            tenantA,
          ]),
        (erro: { code?: string }) => erro.code === "42501",
      );
    });

    it("**o SELECT e o INSERT, esses, existem**", async () => {
      // A negativa acima só vale se a positiva for verdadeira: sem este teste,
      // uma concessão em falta por inteiro passava as duas de cima.
      await definirContexto(app, tenantA);
      const { rows } = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.channel_quality_log",
      );
      assert.ok(Number(rows[0]?.n ?? 0) > 0, "o registo de A devia ter linhas");
    });
  });

  // ------------------------------- o dominio e as chaves mordem pelo caminho

  describe("o dominio e as chaves mordem atraves do modulo", () => {
    it("**um evento fora dos quatro e recusado pela base**", async () => {
      // Três cópias do mesmo domínio — o `KIND_POR_CAMPO` do KAM-013, o
      // `CHECK` da `0014` e o `EVENTOS_DE_CANAL` do módulo. Esta asserção é a
      // que prende a do meio: um quinto evento não entra, venha de onde vier.
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query(
            "INSERT INTO platform.channel_quality_log " +
              "(tenant_id, channel_id, evento, valor_novo, event_key) " +
              "VALUES ($1, $2, 'inventado', 'GREEN', $3)",
            [tenantA, canalA, chave("dominio")],
          ),
        (erro: { code?: string; constraint?: string }) =>
          erro.code === "23514" &&
          erro.constraint === "channel_quality_log_evento_ck",
      );
    });

    it("**um channel_id que nao e do tenant nao casa a FK composta**", async () => {
      // A FK leva o `tenant_id` nos dois lados, pela razão que a `0009` fixou.
      // Sem ela, o `channel_id` de B entrava numa linha de A: a RLS protege a
      // **leitura** e não a integridade.
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query(
            "INSERT INTO platform.channel_quality_log " +
              "(tenant_id, channel_id, evento, valor_novo, event_key) " +
              "VALUES ($1, $2, 'account_alerts', 'texto', $3)",
            [tenantA, canalB, chave("fk")],
          ),
        (erro: { code?: string }) => erro.code === "23503",
      );
    });
  });

  // ------------------ isolamento (Testes Requeridos: X-03 sobre o registo)

  describe("isolamento (Testes Requeridos: X-03 sobre channel_quality_log)", () => {
    it("com o contexto de A, as transicoes de B nao aparecem", async () => {
      await semear(canalB, "ativo", "green");
      const k = chave("so-de-b");
      await gestaoDe(tenantB).gestao.qualidadeDoNumero(tenantB, pnidB, "RED", k);

      await definirContexto(app, tenantA);
      const { rows } = await app.query(
        "SELECT id FROM platform.channel_quality_log WHERE event_key = $1",
        [k],
      );
      assert.deepEqual(rows, []);
      // E o administrador vê-a: o que falta a A é a política, não a linha.
      assert.equal((await registoDe(canalB)).filter((l) => l.event_key === k).length, 1);
    });

    it("com o contexto de A, o canal de B nao se restringe", async () => {
      await semear(canalB, "ativo", "green");
      // A `GestaoDeCanal` de A, chamada com o número de B: é o erro de
      // encaminhamento que a RLS tem de apanhar.
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        await gestao.qualidadeDoNumero(tenantA, pnidB, "RED", chave("cruzado")),
        null,
        "o canal de B nao se le com o contexto de A",
      );
      assert.equal((await canalCru(canalB)).estado, "ativo");
    });
  });

  // ---------------------------------------- a medicao do escalao (criterio 7)

  describe("a medicao do escalao (criterio 7)", () => {
    it("**uma service nao consome e uma utility consome**", async () => {
      // «Resposta dentro da janela não consome»: o limite da Meta é sobre
      // **iniciar** conversas fora da janela (CONFIRMADO, `E1` §5), e uma
      // `service` é por definição a mensagem livre dentro da janela.
      await admin.query(
        "UPDATE platform.tenant_channels SET messaging_limit = 'TIER_250' WHERE id = $1",
        [canalA],
      );
      await enviada(tenantA, canalA, contactoA, conversaA, "service", "sent", "1 hour");
      const so = await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA);
      assert.equal(so?.unicos, 0);

      const outro = await criarContacto(tenantA);
      await enviada(tenantA, canalA, outro, conversaA, "utility", "sent", "1 hour");
      const com = await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA);
      assert.equal(com?.unicos, 1);
    });

    it("**uma queued nao conta**: a nossa fila ainda a tem em mao", async () => {
      const contacto = await criarContacto(tenantA);
      const antes = (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos ?? -1;
      await enviada(tenantA, canalA, contacto, conversaA, "utility", "queued", "1 hour");
      assert.equal(
        (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos,
        antes,
      );
    });

    it("**o mesmo contacto duas vezes conta uma**: e `DISTINCT` e nao `count`", async () => {
      const contacto = await criarContacto(tenantA);
      const antes = (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos ?? -1;
      await enviada(tenantA, canalA, contacto, conversaA, "utility", "sent", "1 hour");
      await enviada(tenantA, canalA, contacto, conversaA, "utility", "delivered", "2 hours");
      assert.equal(
        (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos,
        antes + 1,
      );
    });

    it("**as 24 h sao moveis e nao a meia-noite de Luanda**", async () => {
      // **É por isto que esta consulta não chama a `platform.ten_periodo`**, ao
      // contrário do contador do KAM-023: o mês do *free tier* reinicia à
      // meia-noite de um fuso, este não reinicia — vai andando. Uma mensagem de
      // há 25 h está fora, hora a hora, e não «no dia anterior».
      const contacto = await criarContacto(tenantA);
      const antes = (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos ?? -1;
      await enviada(tenantA, canalA, contacto, conversaA, "utility", "sent", "25 hours");
      assert.equal(
        (await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidA))?.unicos,
        antes,
        "uma mensagem de ha 25 h caiu fora da janela movel",
      );
    });

    it("**o canal de B nao entra na conta de A**: a juncao leva o tenant", async () => {
      const contacto = await criarContacto(tenantB);
      const conversaB = (await abrirConversa(tenantB, canalB)).split("|")[0] ?? "";
      await admin.query(
        "UPDATE platform.tenant_channels SET messaging_limit = 'TIER_250' WHERE id = $1",
        [canalB],
      );
      await enviada(tenantB, canalB, contacto, conversaB, "utility", "sent", "1 hour");
      // O número de B, com o contexto de A: a junção leva `tenant_id` nos dois
      // lados e o predicado repete-o além da política.
      assert.equal(await gestaoDe(tenantA).gestao.utilizacao(tenantA, pnidB), null);
    });

    it("**200 unicos com TIER_250 dao 0,8 e avisam** — a letra do criterio", async () => {
      // Canal novo e limpo: a conta é sobre **este** número, e os testes de
      // cima deixaram linhas no `canalA`.
      const limpo = await criarCanal(admin, tenantA);
      await admin.query(
        "UPDATE platform.tenant_channels SET messaging_limit = 'TIER_250' WHERE id = $1",
        [limpo.id],
      );
      const conversa = (await abrirConversa(tenantA, limpo.id)).split("|");
      for (let n = 0; n < 200; n += 1) {
        const contacto = await criarContacto(tenantA);
        await enviada(
          tenantA,
          limpo.id,
          contacto,
          conversa[0] ?? "",
          "utility",
          "delivered",
          "3 hours",
        );
      }
      const { gestao, metricas } = gestaoDe(tenantA);
      const leitura = await gestao.utilizacao(tenantA, limpo.phoneNumberId);
      assert.equal(leitura?.unicos, 200);
      assert.equal(leitura?.racio, 0.8);
      assert.equal(leitura?.avisa, true);
      assert.equal(metricas.ler()["messaging_limit_usage_ratio"], 0.8);
    });

    it("**um escalao que nao se reconhece da racio nulo, e nao zero**", async () => {
      // «Não sei» não é «está folgado». O bloco do ticket escreve `TIER_2000` e
      // o gerador do KAM-024 escreve `TIER_2K`: o nome fora do mapa é
      // desconhecido, e não se inventa um sinónimo.
      await admin.query(
        "UPDATE platform.tenant_channels SET messaging_limit = 'TIER_2000' WHERE id = $1",
        [canalA],
      );
      const { gestao, metricas } = gestaoDe(tenantA);
      const leitura = await gestao.utilizacao(tenantA, pnidA);
      assert.equal(leitura?.escalao, "TIER_2000");
      assert.equal(leitura?.racio, null);
      assert.equal(
        metricas.ler()["messaging_limit_usage_ratio"],
        -1,
        "antes de uma observacao valida o gauge vale -1",
      );
    });
  });

  // ---------------------------- os limites e os templates (criterios 5 e 8)

  describe("os limites e os templates (criterios 5 e 8)", () => {
    it("**o escalao e o tecto persistem, e um null nao apaga**", async () => {
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        await gestao.capacidade(tenantA, pnidA, "TIER_1K", 25, chave("cap")),
        true,
      );
      let cru = await canalCru(canalA);
      assert.equal(cru.escalao, "TIER_1K");
      assert.equal(cru.maxNumeros, 25);

      // A Meta manda **o que mudou**: um corpo sem o tecto não o apaga.
      assert.equal(
        await gestao.capacidade(tenantA, pnidA, "TIER_10K", null, chave("cap")),
        true,
      );
      cru = await canalCru(canalA);
      assert.equal(cru.escalao, "TIER_10K");
      assert.equal(cru.maxNumeros, 25, "o tecto que ja se sabia nao se perdeu");
    });

    it("**o tecto de numeros tem de ser positivo, e a base morde**", async () => {
      await definirContexto(app, tenantA);
      await assert.rejects(
        () =>
          app.query(
            "UPDATE platform.tenant_channels SET max_phone_numbers_per_business = 0 " +
              "WHERE id = $1",
            [canalA],
          ),
        (erro: { code?: string; constraint?: string }) =>
          erro.code === "23514" &&
          erro.constraint === "tenant_channels_max_phone_numbers_ck",
      );
    });

    it("**o template pausa pelo idioma exacto, e nao por prefixo**", async () => {
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) VALUES " +
          "($1, 'recibo', 'pt_PT', 'utility', 'approved', 'resumo'), " +
          "($1, 'recibo', 'pt_BR', 'utility', 'approved', 'resumo')",
        [tenantA],
      );
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        await gestao.qualidadeDoTemplate(
          tenantA,
          pnidA,
          "recibo",
          "pt_PT",
          "RED",
          chave("tpl"),
        ),
        true,
      );

      const { rows } = await admin.query<{ lang: string; status: string; quality: string | null }>(
        "SELECT lang, status, quality FROM platform.message_templates " +
          "WHERE tenant_id = $1 AND name = 'recibo' ORDER BY lang",
        [tenantA],
      );
      // `pt_PT` e `pt_BR` são templates diferentes com corpos diferentes, e um
      // `LIKE 'pt%'` pausava um pelo outro.
      assert.deepEqual(rows, [
        { lang: "pt_BR", status: "approved", quality: null },
        { lang: "pt_PT", status: "paused", quality: "red" },
      ]);
    });

    it("**um account_alerts registra o texto e nao muda o estado**", async () => {
      // «Cria *ticket* para T&S com o texto da Meta e o canal **não muda de
      // estado**»: a segunda metade é o que se garante aqui, contra a coluna. E
      // o texto vai para a base e não para o registo de linha — a lista branca
      // de nove campos do `logger/politica.ts` não tem campo de texto livre.
      await semear(canalA, "ativo", "green");
      const texto = "A sua conta foi revista pela equipa de politicas.";
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        await gestao.alertaDaConta(tenantA, pnidA, texto, chave("alerta")),
        true,
      );
      const cru = await canalCru(canalA);
      assert.equal(cru.estado, "ativo");
      assert.equal(cru.motivo, null);
      const ultima = (await registoDe(canalA)).at(-1);
      assert.equal(ultima?.evento, "account_alerts");
      assert.equal(ultima?.valor_novo, texto);
    });
  });

  // ------------------- o criterio 9 de ponta a ponta: o restrito recusa la

  describe("o criterio 9 de ponta a ponta: a saida honra o restrito", () => {
    /**
     * A porta 5 do KAM-015 ligada a uma consulta real.
     *
     * É assim que um serviço a liga, e é o único sítio onde os dois módulos se
     * encontram sobre a **mesma linha** da base: aqui escreve-se o estado, lá
     * lê-se.
     */
    function obterEstado(tenant: string) {
      return async (
        tenantId: string,
        phoneNumberId: string,
      ): Promise<EstadoParaEnvio | null> => {
        await definirContexto(app, tenant);
        const { rows } = await app.query<{ et: string; ec: string }>(
          "SELECT t.estado AS et, c.estado AS ec " +
            "  FROM platform.tenant_channels AS c " +
            "  JOIN platform.tenants AS t ON t.id = c.tenant_id " +
            " WHERE c.tenant_id = $1 AND c.phone_number_id = $2",
          [tenantId, phoneNumberId],
        );
        const linha = rows[0];
        return linha === undefined
          ? null
          : { estadoTenant: linha.et, estadoCanal: linha.ec };
      };
    }

    function saidaDe(tenant: string): Saida {
      return new Saida({
        bd: bdDe(tenant),
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
        destinatario: async (): Promise<Destinatario> => ({
          bsuid: "AO.ENSAIOENSAIOENSAIO0021",
          telefone: null,
        }),
        guarda: async () => true,
        freeTier: null,
        estado: obterEstado(tenant),
        agora: () => new Date(),
        aleatorio: () => 0.5,
        dormir: async () => undefined,
        ambiente: {},
      });
    }

    function pedido(corpo: Corpo): Pedido {
      return {
        tenantId: tenantA,
        phoneNumberId: pnidA,
        conversationId: conversaA,
        contactId: contactoA,
        channelId: canalA,
        idempotencyKey: chave("envio"),
        corpo,
        doBot: true,
      };
    }

    /** O corpo de template do ponta a ponta. O nome e o idioma vao no corpo. */
    const TEMPLATE: Corpo = {
      tipo: "template",
      nome: "ponta_a_ponta",
      idioma: "pt_PT",
      parametros: [],
    };

    before(async () => {
      // **O `tenants.estado` nasce `onboarding`** (revisão `0001`), e a matriz
      // do KAM-009 decide por um **regime** saído do par: `onboarding` é mais
      // restritivo do que `restrito` e recusa tudo menos registar e a mensagem
      // de teste. Sem esta linha, os três testes abaixo passavam **pela razão
      // errada** — a recusa era do *tenant* e não do canal, e o grupo não
      // provava nada sobre o critério 9. Foi assim que a primeira execução
      // desta bateria correu, e é o defeito que esta linha fecha.
      //
      // Escrito pelo **administrador** de propósito: o `kamba_app` não tem
      // `UPDATE (estado)` em `platform.tenants` — a revisão `0007` retirou-lho,
      // e é essa mesma retirada que deixa a caixa do critério 3 vazia.
      await admin.query("UPDATE platform.tenants SET estado = 'ativo' WHERE id = $1", [
        tenantA,
      ]);
    });

    it("**com o tenant e o canal ativos, o template sai**: o controlo", async () => {
      // A asserção que dá sentido às outras: sem ela, um `STATE_REFUSED` não se
      // distingue de um envio que nunca podia sair.
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) " +
          "VALUES ($1, 'ponta_a_ponta', 'pt_PT', 'utility', 'approved', 'resumo') " +
          "ON CONFLICT DO NOTHING",
        [tenantA],
      );
      await semear(canalA, "ativo", "green");
      const resultado = await saidaDe(tenantA).enviar(pedido(TEMPLATE));
      assert.equal(resultado.ok, true);
    });

    it("**com o canal restrito por qualidade, um template recusa com STATE_REFUSED**", async () => {
      await admin.query(
        "INSERT INTO platform.message_templates " +
          "(tenant_id, name, lang, category, status, body_hash) " +
          "VALUES ($1, 'ponta_a_ponta', 'pt_PT', 'utility', 'approved', 'resumo') " +
          "ON CONFLICT DO NOTHING",
        [tenantA],
      );
      // **A restrição vem deste ticket**, pelo caminho do módulo: não se escreve
      // o `restrito` à mão.
      await semear(canalA, "ativo", "green");
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        (await gestao.qualidadeDoNumero(tenantA, pnidA, "RED", chave("e2e")))?.restringiu,
        true,
      );

      const resultado = await saidaDe(tenantA).enviar(pedido(TEMPLATE));
      assert.equal(resultado.ok, false);
      assert.equal(
        resultado.ok === false ? resultado.motivo : "",
        "STATE_REFUSED",
        "a matriz do KAM-009 recusa `enviar_template_utilidade` na linha `restrito`",
      );
    });

    it("**e uma service dentro da janela continua a sair**: a matriz nao e um corte", async () => {
      // A linha `restrito` da matriz tem `responder_sessao: true`. Um `if
      // (estado === "restrito") recusar` cortava isto também, e o critério 2
      // diz «conversas dentro da janela continuam».
      const resultado = await saidaDe(tenantA).enviar(pedido(TEXTO));
      assert.equal(resultado.ok, true, "a janela esta aberta e `restrito` responde");
    });

    it("**reposto o canal, o mesmo template passa**", async () => {
      const { gestao } = gestaoDe(tenantA);
      assert.equal(
        (await gestao.qualidadeDoNumero(tenantA, pnidA, "GREEN", chave("e2e-rep")))?.reposto,
        true,
      );
      const resultado = await saidaDe(tenantA).enviar(pedido(TEMPLATE));
      assert.equal(resultado.ok, true);
    });
  });
});

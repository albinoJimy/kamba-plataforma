/**
 * O onboarding de canal contra um PostgreSQL real (KAM-016, *gate* 8).
 *
 * ## O que **só** uma base prova, e é por isso que este ficheiro existe
 *
 * A `tests/onboarding.test.ts` corre com uma base falsa e mede a ordem dos
 * passos. Nada do que está aqui se pode medir ali:
 *
 * * as **duas unicidades** que dão a idempotência do critério 2, e dão-na sob
 *   concorrência — duas chamadas ao mesmo tempo, uma linha;
 * * a `tenant_channels_phone_number_id_uq` **global** que dá o 409 do critério
 *   4, e o facto de a transacção **reverter**: «não altera nada» não é uma
 *   afirmação sobre código, é sobre o que fica escrito;
 * * o `WHERE fase = <esperada>` do `SQL_TRANSITAR` a serializar duas transições
 *   concorrentes, e os **81** pares a bater no `CHECK` do domínio;
 * * a **RLS** (X-03/X-04): um tenant não vê a tentativa do outro, e o
 *   `kamba_app` não tem `UPDATE` nem `INSERT` nesta tabela — o privilégio nem
 *   existe, que é mais forte do que a política recusar;
 * * o `es_onboardings_7d` a **atravessar tenants**, e a fronteira da janela;
 * * o `jsonb ||` do `SQL_REGISTAR_RECURSO` a não perder um recurso que outro
 *   passo registou entre a leitura e a escrita — o que, numa base falsa, era
 *   verdade por construção.
 *
 * ## E o que **esta** bateria também não prova
 *
 * O primeiro contacto com a Meta. A Graph aqui é o `GraphFalso` do KAM-024, e o
 * nono critério — «1 onboarding ES v4 real numa conta de teste da Meta, depois
 * de KAM-102» — **fica por marcar**. Está escrito na secção de verificação do
 * bloco, e não há evidência inventada em `docs/evidencia/KAM-016.md`.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import {
  CAMPOS_DE_WEBHOOK,
  FASES,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  NumeroJaUsadoError,
  Onboarding,
  PRAZO_DE_ABANDONO_MIN,
  REF_DA_KEK,
  SESSION_INFO_VERSION,
  SQL_ABRIR,
  SQL_APAGAR_CANAL,
  SQL_TRANSITAR,
  SubscricaoIncompletaError,
  TRANSICOES,
  decifrarToken,
  resumoDoCode,
  transicaoValida,
} from "../src/onboarding/index.ts";
import type {
  Cofre,
  Fase,
  Graph,
  RecursoCriado,
  ResultadoDoEs,
} from "../src/onboarding/index.ts";
import { FEATURE_TYPE_DE_COEXISTENCIA } from "../src/onboarding/contrato.ts";
import { OpenBaoFakeProvider, cunharRef } from "../src/secrets/index.ts";
import { apagarTenant, criarCanal, criarTenant, emParalelo, ligar } from "./apoio.ts";

/** A KEK de ensaio, 32 octetos em base64. */
const KEK = Buffer.alloc(32, 11).toString("base64");

/** O cofre do ensaio: um `OpenBaoFakeProvider` com a KEK semeada. */
function cofreDeEnsaio(): Cofre {
  const bao = new OpenBaoFakeProvider({ ambiente: "dev", dados: { [REF_DA_KEK]: [KEK] } });
  return {
    get: (ref) => bao.get(ref),
    getRing: (ref) => bao.getRing(ref),
    versions: (ref) => bao.versions(ref),
    cunhar: (familia, valor) => bao.cunhar(familia, valor),
    revogar: (ref) => bao.revogar(ref),
  };
}

/** A Graph deste ensaio: o `GraphFalso` do KAM-024, pela porta do módulo. */
function graphDeEnsaio(falso: GraphFalso, estado: { falhar: boolean }): Graph {
  const token = "ensaio-token-para-a-base";
  return {
    async trocarCode() {
      return token;
    },
    async subscrever(waba, campos) {
      if (estado.falhar) throw new Error("falha injectada no passo 4");
      falso.responder({
        metodo: "POST",
        caminho: `/v21.0/${waba}/subscribed_apps`,
        consulta: {},
        corpo: { subscribed_fields: campos.join(",") },
        cabecalhos: {},
      });
    },
    async lerSubscricoes(waba) {
      return falso.subscricoes(waba);
    },
    async anularSubscricao(waba) {
      falso.responder({
        metodo: "DELETE",
        caminho: `/v21.0/${waba}/subscribed_apps`,
        consulta: {},
        corpo: null,
        cabecalhos: {},
      });
    },
  };
}

/**
 * Envelhece todas as tentativas para fora da janela de sete dias.
 *
 * **Isto não é higiene: é uma consequência do critério 8 que a própria bateria
 * descobriu.** O `es_onboardings_7d` **atravessa *tenants*** — o tecto de dez
 * clientes por sete dias é da nossa app perante a Meta —, pelo que as linhas que
 * um teste deixa contam na janela do seguinte. A primeira versão desta bateria
 * esgotava o seu próprio tecto a meio: os testes do *dump grep* e do PIN
 * falhavam com `o tecto de 10 clientes novos por 7 dias está gasto (10)`, o que
 * é o módulo a fazer exactamente o que o critério manda.
 *
 * Envelhece em vez de apagar, e a diferença importa: apagar escondia o efeito, e
 * envelhecer mantém as linhas lá — o que deixa as asserções anteriores
 * verificáveis e prova, de passagem, que a janela é **móvel** e não um contador.
 */
async function envelhecerJanela(): Promise<void> {
  await admin.query(
    `UPDATE platform.channel_onboarding
        SET criado_at = now() - ($1::integer * interval '1 day')
      WHERE criado_at > now() - ($1::integer * interval '1 day')`,
    [JANELA_DE_ONBOARDINGS_DIAS + 1],
  );
}

/**
 * Corre o onboarding **dentro de uma transacção**, que é o que a porta 1 do
 * contrato exige — e que o `SAVEPOINT` do `#criarCanal` torna exigível e não só
 * convencionado.
 *
 * Um `pg.Client` sem `BEGIN` está em *autocommit*, e um `SAVEPOINT` fora de um
 * bloco de transacção levanta `25P01`. A primeira versão desta bateria chamava
 * o `ligar()` sobre o cliente nu e **passava**, porque o módulo ainda não abria
 * ponto de salvaguarda nenhum; depois da correcção da revisão adversarial
 * deixou de passar — e isso é o contrato a morder, não um defeito.
 *
 * `COMMIT` em caso de sucesso e `ROLLBACK` em caso de falha: é o que uma rota
 * faria, e é o que faz o critério 4 («não altera nada») ser verificável desta
 * bateria.
 */
async function comTransaccao<T>(
  cliente: pg.Client,
  corpo: () => Promise<T>,
): Promise<T> {
  await cliente.query("BEGIN");
  try {
    const resultado = await corpo();
    await cliente.query("COMMIT");
    return resultado;
  } catch (erro) {
    await cliente.query("ROLLBACK");
    throw erro;
  }
}

function entrada(tenant: string, parcial: Partial<ResultadoDoEs> = {}): ResultadoDoEs {
  const marca = randomUUID().slice(0, 8);
  return {
    tenant_id: tenant,
    code: `AQB-${randomUUID()}`,
    waba_id: `waba-${marca}`,
    phone_number_id: `pnid-${randomUUID()}`,
    session_info: {
      sessionInfoVersion: SESSION_INFO_VERSION,
      extras: { featureType: FEATURE_TYPE_DE_COEXISTENCIA },
    },
    ...parcial,
  };
}

let admin: pg.Client;
let app: pg.Client;
let batch: pg.Client;
let tenantA: string;
let tenantB: string;
let falso: GraphFalso;
let falha: { falhar: boolean };
let servico: Onboarding;
let cofre: Cofre;

/** As tentativas de um tenant, vistas pelo administrador. */
async function tentativasDe(
  tenant: string,
): Promise<
  readonly {
    readonly id: string;
    readonly channel_id: string | null;
    readonly waba_id: string;
    readonly fase: Fase;
    readonly recursos_criados: readonly RecursoCriado[];
    readonly pin_ref: string | null;
    readonly motivo: string | null;
  }[]
> {
  const { rows } = await admin.query(
    "SELECT id::text AS id, channel_id::text AS channel_id, waba_id, fase, " +
      "recursos_criados, pin_ref, motivo FROM platform.channel_onboarding " +
      "WHERE tenant_id = $1 ORDER BY criado_at, waba_id",
    [tenant],
  );
  return rows as never;
}

before(async () => {
  admin = await ligar("admin");
  app = await ligar("app");
  batch = await ligar("batch");
  tenantA = await criarTenant(admin, "onb-a");
  tenantB = await criarTenant(admin, "onb-b");
  falso = new GraphFalso(new GeradorDeFixtures("onboarding-bd"));
  falha = { falhar: false };
  cofre = cofreDeEnsaio();
  servico = new Onboarding({
    sql: batch,
    graph: graphDeEnsaio(falso, falha),
    cofre,
    vertical: "vendedor",
  });
});

after(async () => {
  for (const tenant of [tenantA, tenantB]) {
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  }
  await admin.end();
  await app.end();
  await batch.end();
});

// ------------------------------------------------------------------ critério 2

describe("idempotencia (criterio 2)", () => {
  it("o caminho completo escreve 1 tentativa, 1 canal, 1 token, 11 campos", async () => {
    await envelhecerJanela();
    const e = entrada(tenantA);
    const { tentativa, novo } = await comTransaccao(batch, () => servico.ligar(e));
    assert.equal(novo, true);
    assert.equal(tentativa.fase, "subscrito");
    const linhas = await tentativasDe(tenantA);
    assert.equal(linhas.length, 1);
    assert.equal(linhas[0]?.fase, "subscrito");
    assert.ok(linhas[0]?.channel_id !== null);
    const { rows } = await admin.query(
      "SELECT token_ref, waba_id, waac_id, phone_number_id, channel_mode, estado " +
        "FROM platform.tenant_channels WHERE tenant_id = $1",
      [tenantA],
    );
    assert.equal(rows.length, 1);
    // **O `token_ref` é uma referência opaca e nunca o *token***: o critério 3.
    assert.match(String(rows[0]?.token_ref), /^meta_client_token\/[0-9a-f]{32}$/);
    // O critério 8: guarda `waba_id`, `waac_id` (nulo hoje) e `phone_number_id`.
    assert.equal(rows[0]?.waba_id, e.waba_id);
    assert.equal(rows[0]?.waac_id, null);
    assert.equal(rows[0]?.phone_number_id, e.phone_number_id);
    // **O canal nasce `pendente` e fica**: o *gate* de activação é KAM-093.
    assert.equal(rows[0]?.estado, "pendente");
    assert.deepEqual([...falso.subscricoes(e.waba_id)].sort(), [...CAMPOS_DE_WEBHOOK].sort());
  });

  it("o mesmo code 2x produz 1 tentativa e 1 canal", async () => {
    const e = entrada(tenantA);
    await envelhecerJanela();
    await comTransaccao(batch, () => servico.ligar(e));
    const antes = (await tentativasDe(tenantA)).length;
    const segunda = await comTransaccao(batch, () => servico.ligar(e));
    assert.equal(segunda.novo, false);
    assert.equal((await tentativasDe(tenantA)).length, antes);
  });

  /**
   * **O mesmo `(tenant_id, waba_id)` com um `code` novo.** É a outra metade do
   * critério 2, e é a que a unicidade do WABA apanha: um segundo *popup* sobre o
   * mesmo WABA não cria um segundo canal.
   */
  it("o mesmo (tenant_id, waba_id) com outro code produz 1 canal", async () => {
    const primeira = entrada(tenantA);
    await envelhecerJanela();
    await comTransaccao(batch, () => servico.ligar(primeira));
    const canaisAntes = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels WHERE tenant_id = $1",
      [tenantA],
    );
    const segunda = await comTransaccao(batch, () =>
      servico.ligar({
        ...primeira,
        code: `AQB-${randomUUID()}`,
        phone_number_id: `pnid-${randomUUID()}`,
      }),
    );
    assert.equal(segunda.novo, false);
    const canaisDepois = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels WHERE tenant_id = $1",
      [tenantA],
    );
    assert.equal(canaisDepois.rows[0].n, canaisAntes.rows[0].n);
  });

  /**
   * **Sob concorrência**, e é o que a base falsa não consegue medir: duas
   * chamadas ao mesmo tempo, uma linha. O `ON CONFLICT DO NOTHING` sem alvo é o
   * que o garante — ver o `docstring` do `SQL_ABRIR`.
   */
  it("duas abertas concorrentes do mesmo par dao 1 linha", async () => {
    const tenant = await criarTenant(admin, "onb-corrida");
    const waba = `waba-${randomUUID().slice(0, 8)}`;
    const resumo = resumoDoCode(`AQB-${randomUUID()}`);
    // **Duas ligacoes de verdade**, que e o que torna isto uma corrida: com uma
    // so, o `ON CONFLICT` nunca ve concorrencia. O `emParalelo` do `apoio.ts`
    // recebe os clientes, os itens e o trabalho — e devolve `void`, pelo que o
    // resultado de cada um sai por um `array` partilhado.
    const clientes = [await ligar("batch"), await ligar("batch")];
    const linhas: number[] = [];
    try {
      await emParalelo(clientes, [0, 1], async (cliente) => {
        const { rows } = await cliente.query(SQL_ABRIR, [
          tenant,
          waba,
          null,
          `pnid-${randomUUID()}`,
          resumo,
        ]);
        linhas.push(rows.length);
      });
    } finally {
      for (const cliente of clientes) await cliente.end();
    }
    assert.deepEqual([...linhas].sort(), [0, 1]);
    const { rows } = await admin.query(
      "SELECT count(*)::int AS n FROM platform.channel_onboarding WHERE tenant_id = $1",
      [tenant],
    );
    assert.equal(rows[0].n, 1);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  /**
   * **As duas unicidades levam o `tenant_id`.** Sem ele, uma tentativa de B que
   * calhasse no mesmo `code_hash` era deduplicada em silêncio contra a de A — e
   * o que se perdia era o onboarding de B, sem erro nenhum a dizer porquê.
   */
  /**
   * **O mesmo `code_hash` noutro WABA, no mesmo tenant.** É o caso que separa um
   * `ON CONFLICT DO NOTHING` **sem alvo** de um com alvo nomeado, e é o que o
   * `docstring` do `SQL_ABRIR` promete — e não havia teste nenhum a exercê-lo.
   *
   * A tabela tem **duas** unicidades, `(tenant_id, code_hash)` e
   * `(tenant_id, waba_id)`. Os quatro casos de idempotência que havia variavam o
   * `code` com o WABA igual, ou o tenant, pelo que o alvo nomeado
   * `(tenant_id, waba_id)` absorvia-os também. Com o WABA **diferente** e o
   * `code` igual, o conflito é na unicidade do *code* — que um alvo nomeado não
   * cobre: em vez de absorver, sai um `23505` cru, e o `EsNaoEV4Error` que o
   * `onboarding.ts` promete nunca chega a ser levantado. A mutação `onboarding:
   * o ON CONFLICT passa a nomear uma chave so` sobreviveu à noite de 2026-10-26
   * por falta deste caso.
   */
  it("o mesmo code noutro waba do mesmo tenant absorve, e nao levanta", async () => {
    const resumo = resumoDoCode(`AQB-${randomUUID()}`);
    const primeira = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumo,
    ]);
    // O canário: sem esta linha, uma primeira abertura que falhasse deixava a
    // segunda a absorver por não haver com que colidir.
    assert.equal(primeira.rows.length, 1, "a primeira abertura nao passou");
    const segunda = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumo,
    ]);
    assert.equal(
      segunda.rows.length,
      0,
      "o conflito na unicidade do code devia ser absorvido, sem linha e sem erro",
    );
  });

  it("o mesmo code em dois tenants abre duas tentativas", async () => {
    const code = `AQB-${randomUUID()}`;
    const resumo = resumoDoCode(code);
    const waba = `waba-${randomUUID().slice(0, 8)}`;
    for (const tenant of [tenantA, tenantB]) {
      const { rows } = await batch.query(SQL_ABRIR, [
        tenant,
        waba,
        null,
        `pnid-${randomUUID()}`,
        resumo,
      ]);
      assert.equal(rows.length, 1, `o tenant ${tenant} devia ter aberto`);
    }
  });
});

// ------------------------------------------------------------------ critério 4

describe("o 409 do phone_number_id (criterio 4)", () => {
  it("a unicidade global morde, e a transaccao nao deixa nada atras", async () => {
    const dono = await criarCanal(admin, tenantA);
    const antesCanais = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels",
    );
    const e = entrada(tenantB, { phone_number_id: dono.phoneNumberId });

    // A transacção é de quem chama (a porta 1 do contrato): abre-se aqui, e é o
    // `ROLLBACK` que faz «não altera nada». **E o `BEGIN` é obrigatório**, não
    // cerimónia: o `#criarCanal` abre um `SAVEPOINT`, e um ponto de salvaguarda
    // fora de um bloco de transacção levanta `25P01` — ver o `comTransaccao`.
    await envelhecerJanela();
    const cliente = await ligar("batch");
    const servicoDaCorrida = new Onboarding({
      sql: cliente,
      graph: graphDeEnsaio(falso, { falhar: false }),
      cofre,
      vertical: "vendedor",
    });
    await cliente.query("BEGIN");
    await assert.rejects(() => servicoDaCorrida.ligar(e), NumeroJaUsadoError);
    await cliente.query("ROLLBACK");
    await cliente.end();

    // **Nada mudou.** Nem um canal a mais, nem a linha do dono tocada, nem uma
    // tentativa de B escrita.
    const depoisCanais = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels",
    );
    assert.equal(depoisCanais.rows[0].n, antesCanais.rows[0].n);
    const doDono = await admin.query(
      "SELECT tenant_id::text AS tenant_id FROM platform.tenant_channels WHERE id = $1",
      [dono.id],
    );
    assert.equal(doDono.rows[0].tenant_id, tenantA);
    assert.deepEqual([...(await tentativasDe(tenantB))].filter((t) => t.waba_id === e.waba_id), []);

    // **E o registo de auditoria escreve-se depois, numa transacção própria.**
    await servico.registarRecusa(e, "phone_number_id de outro tenant");
    const registo = (await tentativasDe(tenantB)).find((t) => t.waba_id === e.waba_id);
    assert.ok(registo !== undefined);
    assert.equal(registo.fase, "falhado");
    assert.equal(registo.motivo, "phone_number_id de outro tenant");
    assert.deepEqual([...registo.recursos_criados], []);
    assert.equal(registo.channel_id, null);
  });

  it("o mesmo phone_number_id no mesmo tenant tambem morde: a chave e global", async () => {
    const meu = await criarCanal(admin, tenantA);
    await assert.rejects(
      () =>
        admin.query(
          "INSERT INTO platform.tenant_channels " +
            "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, token_ref) " +
            "VALUES ($1, 'waba-x', $2, 'coexistencia', 'vendedor', 'ref/x')",
          [tenantA, meu.phoneNumberId],
        ),
      /tenant_channels_phone_number_id_uq/,
    );
  });
});

// ------------------------------------------------------------------ critério 6

describe("a maquina de estados contra a base (criterio 6)", () => {
  /**
   * **A linha leva canal, e isso não é detalhe: são dois `CHECK` sobre ela.**
   *
   * A primeira versão deste teste alterava só a `fase`, e o PostgreSQL recusava
   * pelo `channel_onboarding_canal_ck` — correctamente, porque uma fase fora das
   * nove também não está nas três que dispensam canal. A linha **era** recusada,
   * mas pela outra restrição, e a asserção sobre o nome ficava vermelha. A ordem
   * de avaliação de dois `CHECK` não é garantida, pelo que a única forma de
   * afirmar **qual** morde é deixar só um por morder.
   */
  it("o CHECK recusa uma fase fora das nove, incluindo o desligado", async () => {
    const canal = await criarCanal(admin, tenantA);
    const { rows } = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    const id = (rows[0] as { id: string }).id;
    await admin.query(
      "UPDATE platform.channel_onboarding SET channel_id = $2 WHERE id = $1",
      [id, canal.id],
    );
    // O `desligado` é o décimo estado do diagrama do `01` §13.1, e é estado de
    // `tenant_channels` e não fase de onboarding.
    for (const fase of ["desligado", "pendente", "suspenso", "INICIADO", ""]) {
      await assert.rejects(
        () =>
          admin.query("UPDATE platform.channel_onboarding SET fase = $2 WHERE id = $1", [
            id,
            fase,
          ]),
        /channel_onboarding_fase_ck/,
        `a fase ${JSON.stringify(fase)} devia ser recusada`,
      );
    }
  });

  /**
   * **Os 81 pares ordenados contra a base.** A matriz do contrato decide, e aqui
   * mede-se o que o `SQL_TRANSITAR` faz com cada par: os dezesseis legais
   * escrevem, e os outros 65 nem chegam a ser tentados — o `transitar` levanta
   * antes. O que esta bateria acrescenta à de unidade é o *compare-and-set*: uma
   * transição a partir de uma fase que já mudou devolve **zero linhas**.
   */
  it("os dezesseis pares escrevem, e um compare-and-set desactualizado nao", async () => {
    const tenant = await criarTenant(admin, "onb-matriz");
    let contados = 0;
    for (const de of FASES) {
      for (const para of FASES) {
        if (!transicaoValida(de, para)) continue;
        contados += 1;
        const { rows } = await batch.query(SQL_ABRIR, [
          tenant,
          `waba-${de}-${para}`,
          null,
          `pnid-${randomUUID()}`,
          resumoDoCode(`AQB-${de}-${para}`),
        ]);
        const id = (rows[0] as { id: string }).id;
        // **A linha leva canal sempre**, e não só quando a fase de partida o
        // exige. A primeira versão só o punha nas seis do meio, e falhava em
        // `iniciado → es_concluido`: o `channel_onboarding_canal_ck` olha para a
        // linha **depois** da transição, e a fase de **chegada** pode ser uma
        // das seis. Com canal em todas, o único `CHECK` que pode morder é o do
        // domínio — e é esse que este teste está a medir.
        const canal = await criarCanal(admin, tenant);
        await admin.query(
          "UPDATE platform.channel_onboarding SET channel_id = $2, fase = $3 WHERE id = $1",
          [id, canal.id, de],
        );
        const feita = await batch.query(SQL_TRANSITAR, [id, tenant, de, para, null]);
        assert.equal(feita.rows.length, 1, `${de} -> ${para} devia escrever`);
        // E a segunda vez **não**: a fase já não é a esperada.
        const repetida = await batch.query(SQL_TRANSITAR, [id, tenant, de, para, null]);
        assert.equal(repetida.rows.length, 0, `${de} -> ${para} repetido devia dar 0 linhas`);
      }
    }
    assert.equal(contados, 16);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("o CHECK do canal exige channel_id nas fases do meio", async () => {
    const { rows } = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    const id = (rows[0] as { id: string }).id;
    for (const fase of ["es_concluido", "subscrito", "a_sincronizar", "verificado", "pronto", "ativo"]) {
      await assert.rejects(
        () =>
          admin.query("UPDATE platform.channel_onboarding SET fase = $2 WHERE id = $1", [
            id,
            fase,
          ]),
        /channel_onboarding_canal_ck/,
        `${fase} sem channel_id devia ser recusada`,
      );
    }
    // E as três de fora passam sem canal.
    for (const fase of ["falhado", "abandonado", "iniciado"]) {
      await admin.query("UPDATE platform.channel_onboarding SET fase = $2 WHERE id = $1", [
        id,
        fase,
      ]);
    }
  });

  /** **Os 30 minutos**, com o prazo por parâmetro para não esperar meia hora. */
  it("sem conclusao no prazo passa a abandonado, e so o iniciado passa", async () => {
    const tenant = await criarTenant(admin, "onb-prazo");
    const ids: Record<string, string> = {};
    for (const fase of ["iniciado", "falhado"]) {
      const { rows } = await batch.query(SQL_ABRIR, [
        tenant,
        `waba-${fase}`,
        null,
        `pnid-${randomUUID()}`,
        resumoDoCode(`AQB-${fase}`),
      ]);
      ids[fase] = (rows[0] as { id: string }).id;
      await admin.query(
        "UPDATE platform.channel_onboarding SET fase = $2, " +
          "actualizado_at = now() - interval '31 minutes' WHERE id = $1",
        [ids[fase], fase],
      );
    }
    assert.equal(await servico.abandonarVencidas(), 1);
    const linhas = await tentativasDe(tenant);
    assert.equal(linhas.find((l) => l.waba_id === "waba-iniciado")?.fase, "abandonado");
    // **O `falhado` não é tocado**: a transição `falhado → abandonado` não é uma
    // das dezesseis, e o `WHERE fase = 'iniciado'` do SQL é o que a prende.
    assert.equal(linhas.find((l) => l.waba_id === "waba-falhado")?.fase, "falhado");
    // E um `iniciado` **dentro** do prazo fica.
    await admin.query(
      "UPDATE platform.channel_onboarding SET fase = 'iniciado', actualizado_at = now() " +
        "WHERE id = $1",
      [ids.iniciado],
    );
    assert.equal(await servico.abandonarVencidas(PRAZO_DE_ABANDONO_MIN), 0);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("o dominio do contrato e o da revisao dizem o mesmo", async () => {
    const { rows } = await admin.query(
      "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint " +
        "WHERE conname = 'channel_onboarding_fase_ck'",
    );
    const definicao = String(rows[0].def);
    for (const fase of FASES) {
      assert.ok(definicao.includes(`'${fase}'`), `a revisao devia ter ${fase}`);
    }
    // E não tem mais nenhuma: conta os apóstrofos.
    assert.equal((definicao.match(/'/g) ?? []).length, FASES.length * 2);
  });

  it("todas as fases nao terminais vao a falhado, e o ativo nao sai", () => {
    assert.deepEqual([...TRANSICOES.ativo], []);
  });
});

// ------------------------------------------------------------------ critério 7

describe("a compensacao: 0 recursos orfaos (criterio 7)", () => {
  /**
   * **A compensação apaga o canal que a saga criou, e só esse.** O
   * `AND estado = 'pendente'` do `SQL_APAGAR_CANAL` é uma guarda contra um estado
   * que a saga de hoje não alcança — o canal nasce `pendente` e fica, porque o
   * portão de activação é o KAM-093 —, e por isso **nenhum** dos dois ensaios de
   * compensação a exercita: em ambos o canal está `pendente` e o `DELETE` apaga
   * a mesma linha com ou sem o predicado.
   *
   * Três camadas escondiam-na, e vale nomeá-las: o `try/catch` por recurso do
   * `onboarding.ts` transforma qualquer desfecho anormal em *log*; o resultado do
   * `SQL_APAGAR_CANAL` é **descartado**, pelo que «0 linhas» e «1 linha» são
   * indistinguíveis para o chamador; e a base falsa da bateria de unidade
   * despacha por identidade da constante, logo é cega ao texto do SQL.
   *
   * Daí este teste ser **ao nível da instrução** e não através do serviço: é o
   * único nível a que a guarda tem efeito observável. A mutação `onboarding: a
   * compensacao passa a apagar canais activos` sobreviveu à noite de 2026-10-26.
   */
  it("a compensacao nao apaga um canal que nao esta pendente", async () => {
    const tenant = await criarTenant(admin, "onb-comp-activo");
    // O `criarCanal` do `apoio.ts` nasce `ativo` por omissão — que é
    // precisamente o estado que a saga nunca produz, e por isso o que faltava.
    const activo = await criarCanal(admin, tenant);
    const { rows } = await batch.query(SQL_APAGAR_CANAL, [activo.id, tenant]);
    assert.equal(
      rows.length,
      0,
      "a compensacao apagou um canal activo: a guarda de estado caiu",
    );
    const sobrou = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels WHERE id = $1",
      [activo.id],
    );
    assert.equal(sobrou.rows[0].n, 1, "o canal activo desapareceu");
    await apagarTenant(admin, tenant);
  });

  it("a falha injectada no passo 4 nao deixa canal, token nem subscricao", async () => {
    const tenant = await criarTenant(admin, "onb-comp");
    const e = entrada(tenant);
    const canaisAntes = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels",
    );
    await envelhecerJanela();
    falha.falhar = true;
    // **Sem `comTransaccao`**, e de propósito: o que se mede aqui é o que a
    // compensação deixa escrito, e um `ROLLBACK` à volta apagava a prova. A
    // transacção abre-se à mão e **confirma-se** no fim, porque a compensação é
    // o desfecho desejado e não um acidente a desfazer.
    await batch.query("BEGIN");
    await assert.rejects(() => servico.ligar(e), /falha injectada no passo 4/);
    await batch.query("COMMIT");
    falha.falhar = false;

    // **Zero recursos órfãos**, e medem-se os três sítios e não só a coluna.
    const canaisDepois = await admin.query(
      "SELECT count(*)::int AS n FROM platform.tenant_channels",
    );
    assert.equal(canaisDepois.rows[0].n, canaisAntes.rows[0].n);
    assert.deepEqual([...falso.subscricoes(e.waba_id)], []);
    const linha = (await tentativasDe(tenant))[0];
    assert.ok(linha !== undefined);
    assert.deepEqual([...linha.recursos_criados], []);
    assert.equal(linha.fase, "falhado");
    assert.equal(linha.channel_id, null);
    assert.equal(linha.pin_ref, null);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("a confirmacao incompleta compensa tambem a subscricao", async () => {
    const tenant = await criarTenant(admin, "onb-conf");
    const e = entrada(tenant);
    const graphIncompleta: Graph = {
      ...graphDeEnsaio(falso, { falhar: false }),
      async lerSubscricoes() {
        return CAMPOS_DE_WEBHOOK.filter((c) => c !== "history");
      },
    };
    const servicoIncompleto = new Onboarding({
      sql: batch,
      graph: graphIncompleta,
      cofre,
      vertical: "vendedor",
    });
    await envelhecerJanela();
    await batch.query("BEGIN");
    await assert.rejects(() => servicoIncompleto.ligar(e), SubscricaoIncompletaError);
    await batch.query("COMMIT");
    assert.deepEqual([...falso.subscricoes(e.waba_id)], []);
    const linha = (await tentativasDe(tenant))[0];
    assert.deepEqual([...(linha?.recursos_criados ?? [])], []);
    assert.equal(linha?.fase, "falhado");
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  /**
   * **O `jsonb ||` não perde um recurso que outro passo registou.** Numa base
   * falsa isto era verdade por construção; aqui mede-se contra o PostgreSQL,
   * com duas escritas concorrentes.
   */
  it("dois registos concorrentes de recursos ficam os dois na lista", async () => {
    const tenant = await criarTenant(admin, "onb-jsonb");
    const { rows } = await batch.query(SQL_ABRIR, [
      tenant,
      "waba-jsonb",
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode("AQB-jsonb"),
    ]);
    const id = (rows[0] as { id: string }).id;
    const clientes = [await ligar("batch"), await ligar("batch")];
    try {
      await emParalelo(clientes, ["token", "canal"] as const, async (cliente, recurso) => {
        await cliente.query(
          "UPDATE platform.channel_onboarding " +
            "SET recursos_criados = recursos_criados || $2::jsonb WHERE id = $1",
          [id, JSON.stringify([{ recurso, ref: cunharRef("meta_client_token") }])],
        );
      });
    } finally {
      for (const cliente of clientes) await cliente.end();
    }
    const linha = (await tentativasDe(tenant))[0];
    assert.equal(linha?.recursos_criados.length, 2);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("a coluna recusa um objecto: a lista e uma lista", async () => {
    const { rows } = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    await assert.rejects(
      () =>
        admin.query(
          "UPDATE platform.channel_onboarding SET recursos_criados = '{}'::jsonb WHERE id = $1",
          [(rows[0] as { id: string }).id],
        ),
      /channel_onboarding_recursos_ck/,
    );
  });
});

// ------------------------------------------------------------------ critério 3

describe("o token e o PIN: o dump grep nao os encontra (criterio 3)", () => {
  it("o token em claro nao esta em coluna nenhuma da base", async () => {
    const tenant = await criarTenant(admin, "onb-dump");
    const e = entrada(tenant);
    await envelhecerJanela();
    await comTransaccao(batch, () => servico.ligar(e));
    const token = "ensaio-token-para-a-base";

    // **O *dump grep*, e é literal**: todas as colunas de texto e `bytea` das
    // duas tabelas que este ticket escreve, em texto, à procura do *token*, do
    // `code` e do PIN.
    const { rows } = await admin.query(
      "SELECT c.*::text AS canal, o.*::text AS onboarding " +
        "FROM platform.tenant_channels c " +
        "JOIN platform.channel_onboarding o ON o.channel_id = c.id " +
        "WHERE c.tenant_id = $1",
      [tenant],
    );
    const despejo = rows.map((r) => `${r.canal}|${r.onboarding}`).join("\n");
    assert.ok(!despejo.includes(token), "o token nao devia estar na base");
    assert.ok(!despejo.includes(e.code), "o code nao devia estar na base");
    // E o que **está** lá é a referência, que se interpreta como texto opaco.
    assert.ok(/meta_client_token\//.test(despejo));

    // E o que está no cofre é o **criptograma**, não o *token*: a cifra é nossa,
    // e é isso que a KEK `kek_token_cliente` do inventário existe para fazer.
    const linha = (await tentativasDe(tenant))[0];
    const tokenRef = linha?.recursos_criados.find((r) => r.recurso === "token")?.ref ?? "";
    const criptograma = await cofre.get(tokenRef);
    assert.ok(!criptograma.includes(token));
    assert.equal(decifrarToken({ "1": KEK }, tenant, criptograma), token);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("o PIN de cloud_only vai para o cofre e a coluna guarda a referencia", async () => {
    const tenant = await criarTenant(admin, "onb-pin");
    const e = entrada(tenant, {
      session_info: {
        sessionInfoVersion: SESSION_INFO_VERSION,
        extras: { featureType: "whatsapp_business_onboarding" },
      },
    });
    await envelhecerJanela();
    await comTransaccao(batch, () => servico.ligar(e));
    const linha = (await tentativasDe(tenant))[0];
    assert.match(String(linha?.pin_ref), /^meta_pin_2fa\/[0-9a-f]{32}$/);
    const pin = await cofre.get(String(linha?.pin_ref));
    assert.match(pin, /^\d{6}$/);
    // E o PIN **não** está na base.
    const { rows } = await admin.query(
      "SELECT o.*::text AS linha FROM platform.channel_onboarding o WHERE o.tenant_id = $1",
      [tenant],
    );
    assert.ok(!String(rows[0].linha).includes(pin));
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("o pin_ref recusa uma cadeia que nao tem forma de SecretRef", async () => {
    const { rows } = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    for (const ref of ["123456", "MAIUSCULAS/x", "a/b", ""]) {
      await assert.rejects(
        () =>
          admin.query("UPDATE platform.channel_onboarding SET pin_ref = $2 WHERE id = $1", [
            (rows[0] as { id: string }).id,
            ref,
          ]),
        /channel_onboarding_pin_ref_ck/,
        `${JSON.stringify(ref)} devia ser recusada`,
      );
    }
  });

  it("o code_hash exige 32 octetos exactos", async () => {
    await assert.rejects(
      () =>
        batch.query(SQL_ABRIR, [
          tenantA,
          `waba-${randomUUID().slice(0, 8)}`,
          null,
          `pnid-${randomUUID()}`,
          Buffer.alloc(16),
        ]),
      /channel_onboarding_code_hash_ck/,
    );
  });
});

// ------------------------------------------------------------------ critério 8

describe("o contador es_onboardings_7d (criterio 8)", () => {
  it("atravessa tenants, que e o que o limite da Meta mede", async () => {
    await envelhecerJanela();
    const umA = await criarTenant(admin, "onb-janela-a");
    const umB = await criarTenant(admin, "onb-janela-b");
    const antes = await servico.contarJanela();
    for (const tenant of [umA, umB]) {
      await batch.query(SQL_ABRIR, [
        tenant,
        `waba-janela-${tenant.slice(0, 8)}`,
        null,
        `pnid-${randomUUID()}`,
        resumoDoCode(`AQB-${randomUUID()}`),
      ]);
    }
    // **Dois tenants diferentes, +2 na contagem**: o tecto é da nossa app perante
    // a Meta, e não de uma loja.
    assert.equal(await servico.contarJanela(), antes + 2);

    // A fronteira da janela: uma linha fora dos sete dias não conta.
    await admin.query(
      "UPDATE platform.channel_onboarding SET criado_at = now() - interval '8 days' " +
        "WHERE tenant_id = $1",
      [umA],
    );
    assert.equal(await servico.contarJanela(), antes + 1);
    // E uma dentro conta, mesmo no limite.
    await admin.query(
      `UPDATE platform.channel_onboarding SET criado_at = now() - interval '${
        JANELA_DE_ONBOARDINGS_DIAS
      } days' + interval '1 minute' WHERE tenant_id = $1`,
      [umA],
    );
    assert.equal(await servico.contarJanela(), antes + 2);

    for (const tenant of [umA, umB]) {
      await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
      await apagarTenant(admin, tenant);
    }
  });

  it("conta tambem o abandonado e o falhado: e o lado conservador", async () => {
    await envelhecerJanela();
    const tenant = await criarTenant(admin, "onb-conserv");
    const antes = await servico.contarJanela();
    const { rows } = await batch.query(SQL_ABRIR, [
      tenant,
      "waba-conserv",
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode("AQB-conserv"),
    ]);
    await admin.query("UPDATE platform.channel_onboarding SET fase = 'abandonado' WHERE id = $1", [
      (rows[0] as { id: string }).id,
    ]);
    // Se um *popup* fechado consome um lugar na contagem **da Meta** é NÃO
    // VERIFICADO; contar de menos fazia-nos passar o tecto e receber a recusa no
    // onboarding de um cliente real.
    assert.equal(await servico.contarJanela(), antes + 1);
    await admin.query("DELETE FROM platform.channel_onboarding WHERE tenant_id = $1", [tenant]);
    await apagarTenant(admin, tenant);
  });

  it("o tecto e dez, e e o do E1", () => {
    assert.equal(LIMITE_DE_ONBOARDINGS, 10);
    assert.equal(JANELA_DE_ONBOARDINGS_DIAS, 7);
  });
});

// ------------------------------------------------- isolamento (DoD, X-03/X-04)

describe("isolamento (Testes Requeridos: X-03 sobre channel_onboarding)", () => {
  it("com o contexto de A, a tentativa de B nao se ve", async () => {
    const waba = `waba-iso-${randomUUID().slice(0, 8)}`;
    await batch.query(SQL_ABRIR, [
      tenantB,
      waba,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    await app.query("BEGIN");
    await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
    const { rows } = await app.query(
      "SELECT count(*)::int AS n FROM platform.channel_onboarding WHERE waba_id = $1",
      [waba],
    );
    await app.query("COMMIT");
    assert.equal(rows[0].n, 0);
  });

  it("sem contexto, zero linhas", async () => {
    await app.query("BEGIN");
    const { rows } = await app.query(
      "SELECT count(*)::int AS n FROM platform.channel_onboarding",
    );
    await app.query("COMMIT");
    assert.equal(rows[0].n, 0);
  });

  /**
   * **O privilégio nem existe**, que é mais forte do que a política recusar: não
   * depende de a política estar certa. O onboarding é provisionamento e corre
   * como `kamba_batch`; o `kamba_app` tem `SELECT` e mais nada.
   */
  it("o kamba_app nao insere nem altera: o privilegio nem existe", async () => {
    await app.query("BEGIN");
    await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
    await assert.rejects(
      () =>
        app.query(
          "INSERT INTO platform.channel_onboarding " +
            "(tenant_id, waba_id, phone_number_id, code_hash) VALUES ($1, 'w', 'p', $2)",
          [tenantA, resumoDoCode("x")],
        ),
      /permission denied|42501/,
    );
    await app.query("ROLLBACK");
    await app.query("BEGIN");
    await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
    await assert.rejects(
      () => app.query("UPDATE platform.channel_onboarding SET fase = 'falhado'"),
      /permission denied|42501/,
    );
    await app.query("ROLLBACK");
    await app.query("BEGIN");
    await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenantA]);
    await assert.rejects(
      () => app.query("DELETE FROM platform.channel_onboarding"),
      /permission denied|42501/,
    );
    await app.query("ROLLBACK");
  });

  it("a FK composta impede uma tentativa de A apontar para um canal de B", async () => {
    const deB = await criarCanal(admin, tenantB);
    const { rows } = await batch.query(SQL_ABRIR, [
      tenantA,
      `waba-${randomUUID().slice(0, 8)}`,
      null,
      `pnid-${randomUUID()}`,
      resumoDoCode(`AQB-${randomUUID()}`),
    ]);
    await assert.rejects(
      () =>
        admin.query(
          "UPDATE platform.channel_onboarding SET channel_id = $2, fase = 'es_concluido' " +
            "WHERE id = $1",
          [(rows[0] as { id: string }).id, deB.id],
        ),
      /channel_onboarding_channel_fk/,
    );
  });

  it("a RLS esta ligada com FORCE e tem a politica tenant_iso", async () => {
    const { rows } = await admin.query(
      "SELECT relrowsecurity, relforcerowsecurity, " +
        "(SELECT count(*)::int FROM pg_policy p WHERE p.polrelid = c.oid " +
        " AND p.polname = 'tenant_iso') AS politicas " +
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace " +
        "WHERE n.nspname = 'platform' AND c.relname = 'channel_onboarding'",
    );
    assert.equal(rows[0].relrowsecurity, true);
    assert.equal(rows[0].relforcerowsecurity, true);
    assert.equal(rows[0].politicas, 1);
  });
});

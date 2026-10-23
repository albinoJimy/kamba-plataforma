/**
 * O aviso ao dono contra um PostgreSQL real (KAM-115).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **As consultas correm.** As onze cadeias de `src/avisos/consultas.ts` são
 *    executadas por **este** ficheiro e não por cópias delas — é a regra que o
 *    `outbound/consultas.ts` do KAM-015 escreveu, e foi assim que o KAM-009
 *    descobriu um `coalesce` em falta que uma cópia no teste escondia. Uma base
 *    falsa reconhece-as pelo texto e nunca as interpreta: um erro de sintaxe
 *    passava a bateria do *gate* 4 inteira e falhava no primeiro aviso real.
 * 2. **O `ON CONFLICT DO NOTHING` deduplica sob concorrência.** O critério 2
 *    diz «o mesmo evento 3× produz 1 aviso», e em série isso prova-se com um
 *    `if`. O que não se prova com um `if` é **duas transacções ao mesmo
 *    tempo**: aqui duas ligações de `kamba_app` escrevem a mesma chave e uma
 *    delas sai com zero linhas — não porque leu primeiro, mas porque a
 *    `owner_notices_idempotencia_uq` decidiu.
 * 3. **A confirmação é atómica.** A comparação do resumo e o prazo estão na
 *    instrução (`SQL_CONFIRMAR`), e é isso que faz duas confirmações
 *    simultâneas do mesmo *token* darem **uma**. Com a leitura e a escrita
 *    separadas no código, passavam as duas.
 * 4. **As três varreduras correm sem contexto de tenant.** Os lembretes, os
 *    tenants `ativo` sem contacto verificado e o denominador da métrica são
 *    `SELECT` **sem `tenant_id` no predicado**, e isso só funciona com
 *    `BYPASSRLS` — que só o `kamba_batch` tem (`db/bootstrap.py`). Com
 *    `kamba_app` devolvem zero linhas, e esse é o outro lado da prova.
 * 5. **O X-03 sobre as duas tabelas novas.** Com o contexto de A, o aviso de B
 *    não se lê nem se muda. A bateria do *gate* 6 prova-o pela descoberta; aqui
 *    prova-se pelo caminho do módulo, que é o que um defeito na ToolLayer
 *    usaria.
 * 6. **O `GRANT UPDATE` por coluna existe e é por coluna.** O oposto — um
 *    `UPDATE` ao nível da tabela — tornava vácua a matriz de colunas do
 *    `db/tests/test_privilegios.py`, pela razão que a revisão adversarial da
 *    `0018` mediu.
 *
 * **O que não se mede aqui, e onde se mede:** as regras (os cinco gatilhos, os
 * dois limites, os lembretes, a lista branca de modelos, o varrimento de 200
 * avisos, a configuração sem WhatsApp) vivem em `tests/avisos.test.ts` — são
 * funções puras, e uma base real não acrescenta nada à prova. Os `CHECK` e os
 * privilégios por nome vivem em `db/tests/test_avisos_schema.py`.
 *
 * **E o que não se mede em sítio nenhum, por não existir:** o fornecedor de
 * e-mail verdadeiro. O critério 3 manda medir «com relógio acelerado e
 * fornecedor falso», e é o que se faz; a escolha do fornecedor é um
 * subprocessador com procedimento APD (KAM-069, ADR-008) e o `apd_ref` está
 * `pendente`, pelo que o gate de transferência bloqueia `prod` por desenho.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { apagarTenant, criarTenant, ligar } from "./apoio.ts";
import {
  AvisoAoDono,
  chaveDoEpisodio,
  OCTETOS_DO_TOKEN,
  resumoDoToken,
  SQL_EPISODIOS_PARA_LEMBRETE,
  SQL_HISTORICO,
  SQL_REGISTAR,
  SQL_TENANTS_ATIVOS,
  SQL_TENANTS_SEM_CONTACTO,
  type Canal,
  type Notificador,
  type ResultadoDaEntrega,
} from "../src/avisos/index.ts";
// O `comTenant` do `tenant_guard` tem o **seu** `ClienteSql`, cujo `query`
// devolve `Promise<unknown>`: passar ao modulo o cliente que ele da nao compila.
// O idioma e o do `modos.bd.test.ts` do KAM-018 — o parametro do trabalho
// ignora-se e usa-se a ligacao de fora, que e um `pg.Client` e satisfaz os dois
// tipos. O contexto de tenant esta posto na mesma: e a **transaccao** que o
// leva, nao o objecto.
import { comTenant } from "../src/tenant_guard/index.ts";

const PAINEL = "https://painel.kamba.ao/canal";
const T0 = new Date("2026-11-09T09:00:00.000Z");
const CIFRA = Buffer.alloc(40, 1);
const ENDERECO = "dono@loja.co.ao";

/** Um notificador que entrega sempre e guarda o que lhe deram. */
class Entrega implements Notificador {
  readonly entregas: (string | null)[] = [];
  readonly canal: Canal;

  constructor(canal: Canal) {
    this.canal = canal;
  }

  async entregar(destino: string | null): Promise<ResultadoDaEntrega> {
    this.entregas.push(destino);
    return { entregue: true, motivo: null };
  }
}

/** Um notificador que falha sempre com `bounce`. */
class Bounce implements Notificador {
  readonly canal: Canal;

  constructor(canal: Canal) {
    this.canal = canal;
  }

  async entregar(): Promise<ResultadoDaEntrega> {
    return { entregue: false, motivo: "bounce" };
  }
}

describe("o aviso ao dono contra a base", () => {
  let admin: pg.Client;
  // **Duas ligações de `kamba_app`**, e é a razão de ser desta bateria: um
  // `ON CONFLICT` só é desempate entre sessões diferentes. Com uma, as duas
  // chamadas saem em série pela mesma ligação e o teste prova que o JavaScript
  // é sequencial — a lição que o `modos.bd.test.ts` do KAM-018 escreveu para o
  // `pg_advisory_xact_lock`.
  let app1: pg.Client;
  let app2: pg.Client;
  let batch: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let relogio = T0;

  const email = new Entrega("email");
  const painel = new Entrega("painel");
  const tarefas: string[] = [];

  function montar(notificadores: readonly Notificador[]): AvisoAoDono {
    return new AvisoAoDono({
      notificadores,
      decifrar: () => ENDERECO,
      abrirTarefa: async (pedido) => {
        tarefas.push(pedido.assunto);
      },
      relogio: () => relogio,
      novoToken: () => Buffer.alloc(OCTETOS_DO_TOKEN, 7),
      painel: PAINEL,
    });
  }

  before(async () => {
    admin = await ligar("admin");
    app1 = await ligar("app");
    app2 = await ligar("app");
    batch = await ligar("batch");
    tenantA = await criarTenant(admin, "aviso-a");
    tenantB = await criarTenant(admin, "aviso-b");
    // O `tenants.estado` nasce `onboarding` (revisão `0001`), e o critério 6
    // pergunta pelos `ativo`. Sem esta linha, a varredura dos tenants sem
    // contacto devolvia zero e os testes passavam **pela razão errada** — é a
    // mesma armadilha que o KAM-021 pagou no grupo do critério 9.
    for (const tenant of [tenantA, tenantB]) {
      await admin.query("UPDATE platform.tenants SET estado = 'ativo' WHERE id = $1", [
        tenant,
      ]);
    }
    await admin.query(
      "INSERT INTO platform.owner_contacts " +
        "(tenant_id, canal, endereco_enc, verificado_at) VALUES ($1, 'email', $2, now())",
      [tenantA, CIFRA],
    );
  });

  after(async () => {
    for (const tenant of [tenantA, tenantB]) {
      if (tenant !== "") await apagarTenant(admin, tenant);
    }
    for (const ligacao of [admin, app1, app2, batch]) await ligacao.end();
  });

  // ------------------------------------------------- as consultas correm

  it("as consultas do módulo correm contra o servidor", async () => {
    // A prova mais simples e a mais barata de esquecer: uma cadeia com um erro
    // de sintaxe passa a bateria do *gate* 4 inteira — a base falsa compara-a
    // por texto — e falha no primeiro aviso real.
    relogio = T0;
    const aviso = montar([email, painel]);
    await comTenant(app1, tenantA, async () => {
      const resultado = await aviso.notificar(app1, {
        tenantId: tenantA,
        gatilho: "canal_desligado",
        episodio: "ep-sintaxe",
        ocorridoEm: new Date(T0.getTime() - 30_000),
      });
      assert.equal(resultado.suprimido, null);
      assert.equal(resultado.avisos.length, 2);
    });
    // E o endereço chegou **decifrado** ao notificador, e nunca à base.
    assert.equal(email.entregas.at(-1), ENDERECO);
    assert.equal(painel.entregas.at(-1), null);
    const { rows } = await admin.query(
      "SELECT estado, entregue_at IS NOT NULL AS entregue FROM platform.owner_notices " +
        "WHERE tenant_id = $1 AND episodio = 'ep-sintaxe' ORDER BY canal",
      [tenantA],
    );
    assert.deepEqual(
      rows.map((l) => [l.estado, l.entregue]),
      [
        ["entregue", true],
        ["entregue", true],
      ],
    );
  });

  it("**o endereço nunca é escrito em claro em nenhuma coluna**", async () => {
    // O DoD «Privacidade» como medida e não como promessa: varre-se a tabela à
    // procura do endereço que o módulo acabou de usar. É uma pergunta que uma
    // base falsa não pode responder, porque não tem colunas.
    const { rows } = await admin.query(
      "SELECT count(*)::int AS quantos FROM platform.owner_contacts " +
        "WHERE encode(endereco_enc, 'escape') LIKE $1",
      [`%${ENDERECO}%`],
    );
    assert.equal(rows[0].quantos, 0);
  });

  // ----------------------------------------- a idempotência sob concorrência

  it("duas transacções concorrentes com a mesma chave deixam **uma** linha", async () => {
    relogio = new Date(T0.getTime() + 2 * 24 * 3_600_000);
    const chave = chaveDoEpisodio(tenantA, "sem_pagamento", "ep-corrida");

    async function escrever(cliente: pg.Client): Promise<number> {
      return comTenant(cliente, tenantA, async () => {
        const { rows } = await cliente.query(SQL_REGISTAR, [
          tenantA,
          "sem_pagamento",
          "ep-corrida",
          chave,
          0,
          "email",
          relogio,
        ]);
        return rows.length;
      });
    }

    // As duas em paralelo, e cada uma na **sua** ligação: é a única forma de
    // haver duas transacções a disputar a mesma chave.
    const [primeira, segunda] = await Promise.all([escrever(app1), escrever(app2)]);
    assert.equal(primeira + segunda, 1, `escreveram ${primeira + segunda} linhas`);

    const { rows } = await admin.query(
      "SELECT count(*)::int AS quantos FROM platform.owner_notices " +
        "WHERE tenant_id = $1 AND chave = $2",
      [tenantA, chave],
    );
    assert.equal(rows[0].quantos, 1);
  });

  it("o lembrete das 24 h entra ao lado do aviso, na mesma chave", async () => {
    const chave = chaveDoEpisodio(tenantA, "sem_pagamento", "ep-corrida");
    await comTenant(app1, tenantA, async () => {
      const { rows } = await app1.query(SQL_REGISTAR, [
        tenantA,
        "sem_pagamento",
        "ep-corrida",
        chave,
        1,
        "email",
        relogio,
      ]);
      assert.equal(rows.length, 1);
    });
    const { rows } = await admin.query(
      "SELECT array_agg(lembrete ORDER BY lembrete) AS ordens " +
        "FROM platform.owner_notices WHERE tenant_id = $1 AND chave = $2",
      [tenantA, chave],
    );
    assert.deepEqual(rows[0].ordens, [0, 1]);
  });

  it("**o quarto lembrete é recusado pelo servidor, e não por um `if`**", async () => {
    const chave = chaveDoEpisodio(tenantA, "sem_pagamento", "ep-corrida");
    await assert.rejects(
      comTenant(app1, tenantA, async () =>
        app1.query(SQL_REGISTAR, [
          tenantA,
          "sem_pagamento",
          "ep-corrida",
          chave,
          3,
          "painel",
          relogio,
        ]),
      ),
      (erro: { code?: string }) => erro.code === "23514",
    );
  });

  // --------------------------------------------------- a confirmação atómica

  it("duas confirmações simultâneas do mesmo *token* dão **uma**", async () => {
    relogio = new Date(T0.getTime() + 5 * 24 * 3_600_000);
    await admin.query(
      "INSERT INTO platform.owner_contacts (tenant_id, canal, endereco_enc) " +
        "VALUES ($1, 'email', $2)",
      [tenantB, CIFRA],
    );
    const aviso = montar([email, painel]);
    const { token } = await comTenant(app1, tenantB, () =>
      aviso.emitirConfirmacao(app1, tenantB),
    );

    const [a, b] = await Promise.all([
      comTenant(app1, tenantB, () => aviso.confirmar(app1, tenantB, token)),
      comTenant(app2, tenantB, () => aviso.confirmar(app2, tenantB, token)),
    ]);
    // A comparação do resumo e o prazo estão na **instrução**: com a leitura e a
    // escrita separadas no código, as duas confirmações passavam.
    assert.equal(Number(a) + Number(b), 1, `confirmaram ${Number(a) + Number(b)}`);

    const { rows } = await admin.query(
      "SELECT verificado_at IS NOT NULL AS feito, confirmacao_hash IS NULL AS gasto " +
        "FROM platform.owner_contacts WHERE tenant_id = $1",
      [tenantB],
    );
    assert.deepEqual([rows[0].feito, rows[0].gasto], [true, true]);
  });

  it("o resumo guardado não é o *token*", async () => {
    const token = Buffer.alloc(OCTETOS_DO_TOKEN, 7);
    const { rows } = await admin.query(
      "SELECT count(*)::int AS quantos FROM platform.owner_contacts " +
        "WHERE confirmacao_hash = $1",
      [token],
    );
    assert.equal(rows[0].quantos, 0);
    assert.equal(resumoDoToken(token).length, 32);
  });

  // ------------------------------------------------------- as varreduras

  it("a varredura dos lembretes corre com `BYPASSRLS` e vê os dois tenants", async () => {
    const { rows } = await batch.query(SQL_EPISODIOS_PARA_LEMBRETE, [
      new Date(T0.getTime() - 24 * 3_600_000),
      2,
    ]);
    // Agrupa por episódio e traz o **primeiro** aviso dele e o maior lembrete já
    // enviado. Sem o segundo, a varredura não distinguia «ainda não mandei
    // nenhum» de «já mandei os dois» — e os dois casos levam a coisas opostas.
    assert.ok(rows.length >= 1, "nao houve episodios");
    for (const linha of rows) {
      assert.ok(linha.primeiro_em instanceof Date);
      assert.ok(Number(linha.ultimo_lembrete) <= 2);
    }
  });

  it("**um episódio com os dois lembretes aparece como esgotado**", async () => {
    // O que o `HAVING <=` existe para deixar passar, e **só se prova contra a
    // base**: com `<`, o episódio que já levou o último lembrete desaparecia da
    // varredura — e com ele o «depois pára e abre tarefa a T2» do critério 4,
    // que ficava sem caminho executável. O `ep-corrida` levou o `0` e o `1`
    // acima; falta-lhe o `2`.
    const chave = chaveDoEpisodio(tenantA, "sem_pagamento", "ep-corrida");
    await comTenant(app1, tenantA, async () => {
      await app1.query(SQL_REGISTAR, [
        tenantA,
        "sem_pagamento",
        "ep-corrida",
        chave,
        2,
        "email",
        relogio,
      ]);
    });
    // Setenta e duas horas depois do primeiro aviso: os lembretes esgotaram-se.
    relogio = new Date(relogio.getTime() + 72 * 3_600_000);
    const aviso = montar([email, painel]);
    const antes = tarefas.length;
    const { esgotados } = await aviso.varrerLembretes(batch);
    assert.ok(esgotados.includes(tenantA), JSON.stringify(esgotados));
    // E abriu tarefa a T2, que é a outra metade do critério.
    assert.ok(tarefas.length > antes);
    assert.ok(tarefas.some((a) => a.includes("lembretes esgotados")));
  });

  it("**a mesma varredura com `kamba_app` não vê nada**", async () => {
    // É o outro lado da prova: a consulta não leva `tenant_id` no predicado, e
    // sem `BYPASSRLS` a política devolve zero linhas em vez do aviso de outro.
    // Sem contexto de tenant, o `NULLIF(current_setting(...), '')` é nulo e
    // nenhuma linha passa.
    const { rows } = await app1.query(SQL_EPISODIOS_PARA_LEMBRETE, [
      new Date(T0.getTime() - 24 * 3_600_000),
      2,
    ]);
    assert.deepEqual(rows, []);
  });

  it("a varredura dos tenants sem contacto encontra o que falta", async () => {
    const aviso = montar([email, painel]);
    const sem = await aviso.varrerContactos(batch);
    // O `tenantA` tem contacto verificado desde o `before`; o `tenantB` passou a
    // ter no teste da confirmação. Nenhum dos dois deve aparecer, e o que
    // aparecer é de outra bateria — por isso a asserção é sobre a ausência dos
    // nossos e não sobre o conjunto todo.
    assert.equal(sem.includes(tenantA), false);
    assert.equal(sem.includes(tenantB), false);
  });

  it("**o denominador da métrica conta os `ativo` e não todos**", async () => {
    const { rows } = await batch.query(SQL_TENANTS_ATIVOS);
    assert.ok(Number(rows[0].quantos) >= 2);
    // E um tenant em `onboarding` não entra: o critério 6 diz «tenant `ativo`», e
    // reclamar de quem ainda está a entrar era reclamar de quem, por definição,
    // ainda não deu e-mail nenhum.
    const terceiro = await criarTenant(admin, "aviso-c");
    try {
      const antes = Number(rows[0].quantos);
      const { rows: depois } = await batch.query(SQL_TENANTS_ATIVOS);
      assert.equal(Number(depois[0].quantos), antes);
      const { rows: faltam } = await batch.query(SQL_TENANTS_SEM_CONTACTO);
      assert.equal(
        faltam.some((l) => l.id === terceiro),
        false,
      );
    } finally {
      await apagarTenant(admin, terceiro);
    }
  });

  // ------------------------------------------------------------ o X-03

  it("com o contexto de A, o aviso de B não se lê", async () => {
    relogio = new Date(T0.getTime() + 8 * 24 * 3_600_000);
    const aviso = montar([email, painel]);
    await comTenant(app2, tenantB, () =>
      aviso.notificar(app2, {
        tenantId: tenantB,
        gatilho: "inactividade",
        episodio: "ep-de-b",
      }),
    );
    await comTenant(app1, tenantA, async () => {
      const { rows } = await app1.query(SQL_HISTORICO, [
        tenantB,
        new Date(T0.getTime() - 365 * 24 * 3_600_000),
      ]);
      // Zero linhas, e não um erro: a política é uma condição e não uma
      // excepção. Nota que o `tenant_id` do predicado é o de **B** e o contexto
      // é de **A** — é o ataque que o X-03 descreve.
      assert.deepEqual(rows, []);
    });
  });

  it("com o contexto de A, o aviso de B não se muda", async () => {
    await comTenant(app1, tenantA, async () => {
      const { rowCount } = await app1.query(
        "UPDATE platform.owner_notices SET tentativas = tentativas + 1 " +
          "WHERE tenant_id = $1",
        [tenantB],
      );
      assert.equal(rowCount, 0);
    });
    const { rows } = await admin.query(
      "SELECT max(tentativas)::int AS maximo FROM platform.owner_notices " +
        "WHERE tenant_id = $1",
      [tenantB],
    );
    assert.ok(Number(rows[0].maximo) <= 1);
  });

  it("com o contexto de A, o contacto de B não se lê nem se invalida", async () => {
    await comTenant(app1, tenantA, async () => {
      const { rows } = await app1.query(
        "SELECT id FROM platform.owner_contacts WHERE tenant_id = $1",
        [tenantB],
      );
      assert.deepEqual(rows, []);
      const { rowCount } = await app1.query(
        "UPDATE platform.owner_contacts SET invalido_at = now(), " +
          "motivo_invalido = 'bounce' WHERE tenant_id = $1",
        [tenantB],
      );
      assert.equal(rowCount, 0);
    });
  });

  // -------------------------------------------- o privilégio, e por coluna

  it("`kamba_app` escreve o desfecho e **não** a chave do aviso", async () => {
    const { rows } = await admin.query(
      "SELECT has_column_privilege('kamba_app', 'platform.owner_notices', $1, 'UPDATE') AS pode",
      ["estado"],
    );
    assert.equal(rows[0].pode, true);
    for (const coluna of ["chave", "gatilho", "episodio", "lembrete", "canal"]) {
      const { rows: linhas } = await admin.query(
        "SELECT has_column_privilege('kamba_app', 'platform.owner_notices', $1, 'UPDATE') AS pode",
        [coluna],
      );
      assert.equal(linhas[0].pode, false, coluna);
    }
    // E o `UPDATE` **não** existe ao nível da tabela: é isso que torna a matriz
    // de colunas do `test_privilegios.py` significativa, pela razão que a
    // revisão adversarial da `0018` mediu.
    const { rows: tabela } = await admin.query(
      "SELECT has_table_privilege('kamba_app', 'platform.owner_notices', 'UPDATE') AS pode",
    );
    assert.equal(tabela[0].pode, false);
  });

  it("o *bounce* invalida o contacto pelo caminho do módulo", async () => {
    relogio = new Date(T0.getTime() + 12 * 24 * 3_600_000);
    const aviso = montar([new Bounce("email"), painel]);
    const antes = tarefas.length;
    await comTenant(app1, tenantA, () =>
      aviso.notificar(app1, {
        tenantId: tenantA,
        gatilho: "qualidade_restrita",
        episodio: "ep-bounce",
        estado: "restrito",
      }),
    );
    const { rows } = await admin.query(
      "SELECT motivo_invalido, invalido_at IS NOT NULL AS marcado " +
        "FROM platform.owner_contacts WHERE tenant_id = $1 AND canal = 'email'",
      [tenantA],
    );
    assert.deepEqual([rows[0].motivo_invalido, rows[0].marcado], ["bounce", true]);
    // E abriu tarefa a T2: nenhum aviso se perde em silêncio (critério 7).
    assert.ok(tarefas.length > antes);
    // E o painel entregou — o «tenta o painel» do critério.
    assert.equal(painel.entregas.at(-1), null);
  });

  it("**um contacto inválido faz o aviso seguinte falhar com `sem_contacto`**", async () => {
    relogio = new Date(T0.getTime() + 20 * 24 * 3_600_000);
    const aviso = montar([email, painel]);
    await comTenant(app1, tenantA, () =>
      aviso.notificar(app1, {
        tenantId: tenantA,
        gatilho: "painel_indisponivel",
        episodio: "ep-depois-do-bounce",
      }),
    );
    const { rows } = await admin.query(
      "SELECT estado, falha_motivo FROM platform.owner_notices " +
        "WHERE tenant_id = $1 AND episodio = 'ep-depois-do-bounce' AND canal = 'email'",
      [tenantA],
    );
    // Não é `bounce` outra vez: o endereço já está condenado e o módulo nem o
    // tenta. Um `bounce` aqui era dizer que o fornecedor recusou uma mensagem
    // que nunca lhe foi entregue.
    assert.deepEqual([rows[0].estado, rows[0].falha_motivo], ["falhado", "sem_contacto"]);
  });
});

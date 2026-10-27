/**
 * O handoff contra um PostgreSQL real (KAM-019).
 *
 * **O que só aqui se prova, e não se simula contra uma base falsa:**
 *
 * 1. **A idempotência é da chave primária.** Cinco `openHandoff` concorrentes
 *    em **duas ligações** deixam uma linha e fazem uma chamada ao provedor. Uma
 *    base falsa devolve o que se lhe mandou devolver, e um teste de unicidade
 *    sobre ela prova que o teste sabe contar.
 * 2. **A mesma conta do provedor em dois *tenants* é recusada pela base.** É a
 *    `handoff_accounts_conta_uq`, e é o furo que o X-10 procura: um
 *    `ensureAccount` que devolvesse por erro a conta de outra PME ficava
 *    gravado sem ninguém ver. A chave primária `(tenant_id, provedor)` não
 *    fecha este lado.
 * 3. **O `resolved` duplicado é *no-op* sob concorrência real.** Dois `close`
 *    em paralelo, duas ligações: um escreve e o outro não casa. Só a base os
 *    serializa.
 * 4. **A RLS recusa o que o código deixaria passar.** Com o contexto de A, as
 *    passagens de B não aparecem — e com `FORCE`, nem como dono.
 * 5. **O `SQL_FORA_DO_SLA` só vê o seu.** É a consulta que o painel do SLA lê,
 *    e o por-*tenant* dela é o que substitui a etiqueta que as bibliotecas de
 *    métricas recusam.
 *
 * O que **não** se mede aqui: a tradução entre os dois vocabulários de estado,
 * a autenticação dos *callbacks*, a leitura do corpo e a ordem dos passos
 * vivem nas baterias do *gate* 4 (`packages/core-ts/tests/hnd.*.test.ts`),
 * porque são funções puras e portas, e uma base real não acrescenta nada à
 * prova.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  Handoff,
  SQL_FORA_DO_SLA,
  SQL_THREAD_DA_PASSAGEM,
  ProvedorIndisponivelError,
  estadoDe,
  threadDe,
  type AberturaNoProvedor,
  type ContaCriada,
  type ContaDeAtendimento,
  type DesfechoDaRetoma,
  type FilaDoEspelho,
  type PedidoDeHandoff,
  type PedidoDeRetoma,
} from "../src/hnd/index.ts";
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
 * `set_config(..., false)` e não `true`: o terceiro argumento a `true` é «local
 * à transacção», e fora de um `BEGIN` explícito cada instrução é a sua própria
 * transacção — a definição desaparece antes da seguinte, e com RLS `FORCE` o
 * `kamba_app` fica sem contexto e vê zero linhas. É a lição que a *suite* da
 * saída pagou com uma execução de 421 s, e aqui já nasce assim.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

/** A fila por porta, com a de-duplicação por `jobId`. */
class FilaFalsa implements FilaDoEspelho {
  readonly jobs = new Map<string, unknown>();
  async enfileirar(jobId: string, carga: Readonly<Record<string, unknown>>): Promise<boolean> {
    if (this.jobs.has(jobId)) return false;
    this.jobs.set(jobId, carga);
    return true;
  }
  async pendentes(): Promise<number> {
    return this.jobs.size;
  }
}

/**
 * Um contador **global ao ficheiro** para os identificadores de conta.
 *
 * Existe porque a `handoff_accounts_conta_uq` é global: dois *tenants* não
 * podem ter a mesma conta no provedor. Um provedor falso que devolvesse sempre
 * `{accountId: 1}` fazia o segundo *tenant* colidir — e colidiu, no teste do
 * isolamento, com `23505`. Foi a **minha própria restrição a morder o meu
 * próprio ensaio**, que é ela a funcionar: na realidade o provedor nunca
 * devolve a mesma conta para duas PMEs.
 */
let proximoIdDeConta = 1000;

/** O provedor por porta: conta chamadas. Não há simulador de Chatwoot. */
class ProvedorFalso {
  contasCriadas = 0;
  conversasAbertas = 0;
  emBaixo = false;
  /** Força o `criarConta` a devolver uma conta fixa, para a colisão da `UNIQUE`. */
  proximaConta: ContaDeAtendimento | null = null;

  readonly criarConta = async (): Promise<ContaCriada> => {
    this.contasCriadas += 1;
    if (this.proximaConta !== null) return this.#criada(this.proximaConta);
    proximoIdDeConta += 1;
    return this.#criada({
      accountId: proximoIdDeConta,
      inboxId: proximoIdDeConta + 10_000,
      botId: proximoIdDeConta + 20_000,
      providerUserId: proximoIdDeConta + 30_000,
    });
  };

  // Os dois `access_token` em claro, que o provedor so mostra na criacao.
  #criada(conta: ContaDeAtendimento): ContaCriada {
    return {
      conta,
      tokenDoBot: `bot-${conta.accountId}`,
      tokenDoUtilizador: `utilizador-${conta.accountId}`,
    };
  }
  readonly abrirConversa = async (abertura: AberturaNoProvedor): Promise<string> => {
    this.conversasAbertas += 1;
    if (this.emBaixo) throw new ProvedorIndisponivelError("sem resposta");
    return `cw-${abertura.handoffId}`;
  };
  readonly espelhar = async (): Promise<void> => undefined;
  readonly fecharConversa = async (): Promise<void> => undefined;
}

describe("o handoff contra a base", () => {
  let admin: pg.Client;
  let app: pg.Client;
  // **Uma segunda ligacao de `kamba_app`**, e nao e luxo: a concorrencia dos
  // criterios 4 e 7 so e real com duas sessoes. Com uma, os dois `INSERT` e os
  // dois `UPDATE` saem em serie pela mesma conexao e o teste prova que o
  // JavaScript e sequencial.
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let conversaA = "";
  let conversaB = "";
  let contactoA = "";

  /** Os *tenants* descartaveis que os testes de conta criam. */
  const descartaveis: string[] = [];

  /**
   * Um *tenant* novo, com canal e conversa, e que o `after` apaga.
   *
   * **Existe porque dois testes desta suite nao podem partilhar o *tenant*
   * principal**, e isso foi medido: o teste das cinco aberturas concorrentes
   * chama o `openHandoff`, que chama o `ensureAccount` por dentro — quando o
   * teste da conta corria, a conta de A ja existia, o contador do provedor
   * ficava a zero e a assercao falhava. Era dependencia de ordem nos meus
   * proprios testes, que e o genero de defeito que passa quando se corre o
   * ficheiro de uma ponta a outra e falha quando alguem corre um teste so.
   */
  async function tenantNovo(rotulo: string): Promise<[string, string]> {
    const tenant = await criarTenant(admin, rotulo);
    descartaveis.push(tenant);
    const canal = await criarCanal(admin, tenant);
    const [conversa] = await abrirConversa(tenant, canal.id);
    return [tenant, conversa];
  }

  /** Uma conversa criada pelo administrador. */
  async function abrirConversa(tenant: string, canal: string): Promise<[string, string]> {
    const contacto = await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id",
      [tenant],
    );
    const contactId = contacto.rows[0]?.contact_id ?? "";
    const conversa = await admin.query<{ id: string }>(
      "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id) " +
        "VALUES ($1, $2, $3) RETURNING id",
      [tenant, contactId, canal],
    );
    return [conversa.rows[0]?.id ?? "", contactId];
  }

  /**
   * O AGR, com o *compare-and-set* **em SQL** contra esta base.
   *
   * A instrução é uma cópia do `SQL_RETOMAR_HANDOFF` do
   * `services/agr/src/kamba_agr/consultas.py` — o predicado inteiro: o
   * *tenant*, o `handoff_id`, o `status = 'waiting'` e o `EXISTS` que liga a
   * passagem ao contacto da conversa. **Uma cópia e não a peça**, e diz-se:
   * a atomicidade dela sob concorrência real está provada do lado do AGR
   * (`db/tests_agr/test_handoff_retoma.py`, duas ligações, uma a vencer), e o
   * que esta montagem acrescenta é a outra metade, que só aqui se pode ver —
   * que as **duas escritas do HND e a dele** compõem contra um PostgreSQL a
   * sério: o `resolver` numa instrução, o `status` na dele, os privilégios de
   * `kamba_app` a chegarem para as duas, e a RLS no meio.
   *
   * Corre na ligação que lhe derem, para que um teste possa pôr o CAS numa
   * sessão e o HND noutra.
   */
  function agrDe(
    cliente: pg.Client,
    registo: PedidoDeRetoma[],
  ): (pedido: PedidoDeRetoma) => Promise<DesfechoDaRetoma> {
    return async (pedido: PedidoDeRetoma): Promise<DesfechoDaRetoma> => {
      registo.push(pedido);
      const corte = pedido.threadId.indexOf(":");
      const tenantId = pedido.threadId.slice(0, corte);
      const contactId = pedido.threadId.slice(corte + 1);
      await definirContexto(cliente, tenantId);
      const venceu = await cliente.query(
        `UPDATE platform.handoffs AS h
            SET status = $1, resumed_at = now()
          WHERE h.tenant_id = $2
            AND h.handoff_id = $3
            AND h.status = 'waiting'
            AND EXISTS (
                  SELECT 1 FROM platform.conversations c
                   WHERE c.tenant_id = h.tenant_id
                     AND c.id = h.conversation_id
                     AND c.contact_id = $4
                )
         RETURNING 1`,
        [estadoDe(pedido.outcome), tenantId, pedido.handoffId, contactId],
      );
      if ((venceu.rowCount ?? 0) > 0) return "retomado";
      // **A classificacao do zero linhas e a do `_classificar` real, e a
      // primeira versao era mais FRACA do que a peca** — achado da revisao
      // adversarial, e e o sentido contrario do habitual: ela lia so
      // `(tenant_id, handoff_id)`, pelo que uma passagem de **outro contacto**
      // do mesmo *tenant* dava `repetido` (200, benigno) aqui e `recusado`
      // (404, que **levanta** no cliente) na peca. Com o duplo permissivo, a
      // unica suite que corre contra PostgreSQL nunca podia observar a
      // divergencia que o `RetomaRecusadaError` existe para gritar.
      //
      // E o `SQL_HANDOFF_PARA_RETOMA` de la leva o `contact_id` no predicado,
      // e o estado passa pelo `pode_retomar`.
      const desta = await cliente.query<{ status: string }>(
        `SELECT h.status
           FROM platform.handoffs h
           JOIN platform.conversations c
             ON c.tenant_id = h.tenant_id
            AND c.id = h.conversation_id
          WHERE h.tenant_id = $1 AND h.handoff_id = $2 AND c.contact_id = $3`,
        [tenantId, pedido.handoffId, contactId],
      );
      const linha = desta.rows[0];
      if (linha === undefined) return "recusado";
      // O `pode_retomar` do `handoff/maquina.py`: so o `waiting` e retomavel, e
      // aqui ele e `false` por construcao — o CAS acabou de nao casar. Confere-se
      // de qualquer maneira, como a peca faz, porque se um dia ele disser `true`
      // sobre uma passagem que o CAS recusou as duas leituras divergiram.
      return linha.status === "waiting" ? "recusado" : "repetido";
    };
  }

  /** O HND de um *tenant*, sobre a ligação dada. */
  function hndDe(
    tenant: string,
    provedor: ProvedorFalso,
    fila: FilaDoEspelho,
    cliente: pg.Client = app,
    retomar: ((pedido: PedidoDeRetoma) => Promise<DesfechoDaRetoma>) | null = null,
  ): Handoff {
    return new Handoff({
      bd: {
        // Generica e com a conversao a vista, pela razao que a suite da saida
        // escreveu: o `ClienteSql` promete `rows: readonly T[]` e o `pg`
        // devolve `QueryResult<QueryResultRow>`.
        query: async <T,>(texto: string, valores?: readonly unknown[]) => {
          await definirContexto(cliente, tenant);
          const resultado = await cliente.query(
            texto,
            valores === undefined ? [] : [...valores],
          );
          return { rows: resultado.rows as readonly T[] };
        },
      },
      provedor: {
        abrirConversa: provedor.abrirConversa,
        espelhar: provedor.espelhar,
        fecharConversa: provedor.fecharConversa,
      },
      provisionador: { criarConta: provedor.criarConta },
      fila,
      refDoTokenDoBot: (tenantId) => `chatwoot_bot_token/${tenantId}`,
      refDoTokenDoUtilizador: (tenantId) => `chatwoot_user_token/${tenantId}`,
      // O cofre nao existe nesta suite: o que importa aqui e que as duas
      // `SecretRef` vao para a base, e isso le-se das colunas.
      guardarSegredo: async () => undefined,
      segredoDoBot: async () => "cccc-segredo",
      // Por omissão **levanta**, e não é descuido: a maioria dos testes deste
      // ficheiro é sobre a abertura e o isolamento, e uma porta que devolvesse
      // `retomado` a fingir escondia um `receber` a pedir retomas que ninguém
      // mediu. Quem precisa dela passa-a.
      retomar:
        retomar ??
        (async () => {
          throw new Error("este teste nao liga a porta da retoma");
        }),
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

    tenantA = await criarTenant(admin, "handoff-a");
    tenantB = await criarTenant(admin, "handoff-b");
    const canalA = await criarCanal(admin, tenantA);
    const canalB = await criarCanal(admin, tenantB);
    const a = await abrirConversa(tenantA, canalA.id);
    const b = await abrirConversa(tenantB, canalB.id);
    conversaA = a[0];
    contactoA = a[1];
    conversaB = b[0];
  });

  after(async () => {
    for (const tenant of descartaveis) await apagarTenant(admin, tenant);
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

  function pedido(tenant: string, conversa: string, id: string): PedidoDeHandoff {
    return {
      tenantId: tenant,
      chaveDoContacto: contactoA,
      conversationId: conversa,
      handoffId: id,
      motivo: "o cliente pediu uma pessoa",
      resumo: "Resumo do turno.",
    };
  }

  describe("idempotencia (criterio 4)", () => {
    it("**cinco aberturas concorrentes: 1 linha e 1 chamada ao provedor**", async () => {
      const provedor = new ProvedorFalso();
      const fila = new FilaFalsa();
      const um = hndDe(tenantA, provedor, fila, app);
      const outro = hndDe(tenantA, provedor, fila, app2);
      const req = pedido(tenantA, conversaA, "h_concorrente");

      const resultados = await Promise.all([
        um.openHandoff(req),
        outro.openHandoff(req),
        um.openHandoff(req),
        outro.openHandoff(req),
        um.openHandoff(req),
      ]);

      await definirContexto(app, tenantA);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.handoffs WHERE handoff_id = $1",
        ["h_concorrente"],
      );
      assert.equal(linhas.rows[0]?.n, "1", "a chave primaria e que impede a segunda linha");
      assert.equal(
        provedor.conversasAbertas,
        1,
        "cinco conversas no provedor e o defeito que isto prende",
      );
      assert.equal(resultados.filter((r) => !r.repetido).length, 1);
    });

    it("**a conta de atendimento: 1 chamada ao provedor e 1 linha**", async () => {
      // **Um tenant limpo**, e nao o principal: o teste de cima ja lhe criou a
      // conta por dentro do `openHandoff`. Ver a nota do `tenantNovo`.
      const [tenant] = await tenantNovo("handoff-conta");
      const provedor = new ProvedorFalso();
      provedor.proximaConta = {
        accountId: 100,
        inboxId: 200,
        botId: 300,
        providerUserId: 400,
      };
      const hnd = hndDe(tenant, provedor, new FilaFalsa());
      const primeira = await hnd.ensureAccount(tenant);
      const segunda = await hnd.ensureAccount(tenant);

      assert.deepEqual(primeira, segunda);
      assert.equal(provedor.contasCriadas, 1);
      await definirContexto(app, tenant);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.handoff_accounts WHERE tenant_id = $1",
        [tenant],
      );
      assert.equal(linhas.rows[0]?.n, "1");
    });

    it("**duas chamadas concorrentes: o ON CONFLICT da conta**", async () => {
      // **O `ON CONFLICT (tenant_id, provedor) DO NOTHING` nao era exercitado
      // por teste nenhum**, e foi a prova por mutacao que o mostrou: apaga-lo
      // deixava a suite verde. A razao e o caminho rapido — duas chamadas
      // **sequenciais** encontram a linha na leitura e nunca chegam ao
      // `INSERT`, pelo que o conflito nunca acontece. Esta e a unica forma de o
      // provocar: duas chamadas que passam **ambas** a leitura, em duas
      // ligacoes, e que por isso tentam ambas inserir.
      //
      // Sem o `ON CONFLICT`, a segunda levanta `23505` e o `ensureAccount`
      // propaga — a passagem que dependesse dela falhava em vez de reutilizar a
      // conta que a primeira criou.
      const [tenant] = await tenantNovo("handoff-conflito");
      const provedor = new ProvedorFalso();
      const outro = new ProvedorFalso();
      const [uma, segunda] = await Promise.all([
        hndDe(tenant, provedor, new FilaFalsa(), app).ensureAccount(tenant),
        hndDe(tenant, outro, new FilaFalsa(), app2).ensureAccount(tenant),
      ]);

      // As duas devolvem **a mesma** conta: a que ficou gravada.
      assert.deepEqual(uma, segunda);
      await definirContexto(app, tenant);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.handoff_accounts WHERE tenant_id = $1",
        [tenant],
      );
      assert.equal(linhas.rows[0]?.n, "1", "uma linha, e a outra conta ficou orfa");
      // E as duas falaram com o provedor: e o custo conhecido desta corrida, e
      // esta contado e registado (ver a nota do `ensureAccount`).
      assert.equal(provedor.contasCriadas + outro.contasCriadas, 2);
    });

    it("**a mesma conta do provedor em dois tenants e recusada pela base**", async () => {
      // A `handoff_accounts_conta_uq`, e e o furo que o X-10 procura: um
      // `ensureAccount` que devolvesse por erro a conta de outra PME ficava
      // gravado sem ninguem ver. A chave primaria `(tenant_id, provedor)` nao
      // fecha este lado — fecha o outro.
      // **Dois tenants limpos**, pela mesma razao do teste de cima: o principal
      // ja tem conta, e o que se mede aqui e a colisao do `account_id`.
      //
      // **Só o `account_id` colide**, e o `provider_user_id` e deliberadamente
      // diferente: a prova por mutacao mostrou que a versao anterior deste
      // teste sobrevivia a apagar a `conta_uq`, porque a `utilizador_uq`
      // apanhava o mesmo caso e a assercao aceitava qualquer «duplicate key».
      // Um teste que passa por causa de outra fechadura nao prova a que diz
      // provar — e e por isso que a assercao e agora pelo **nome** da
      // restricao.
      const [um] = await tenantNovo("handoff-uq-1");
      const [outro] = await tenantNovo("handoff-uq-2");
      const primeiro = new ProvedorFalso();
      primeiro.proximaConta = {
        accountId: 777,
        inboxId: 778,
        botId: 779,
        providerUserId: 780,
      };
      await hndDe(um, primeiro, new FilaFalsa()).ensureAccount(um);

      const segundo = new ProvedorFalso();
      segundo.proximaConta = {
        accountId: 777,
        inboxId: 1778,
        botId: 1779,
        // **Diferente**, para que so a `conta_uq` possa recusar.
        providerUserId: 1780,
      };
      await assert.rejects(
        () => hndDe(outro, segundo, new FilaFalsa(), app2).ensureAccount(outro),
        /handoff_accounts_conta_uq/,
      );
    });

    it("**o mesmo utilizador do provedor em dois tenants e recusado**", async () => {
      // A `handoff_accounts_utilizador_uq`, que a emenda 1.23 acrescentou pela
      // mesma razao da conta: o mesmo utilizador em dois tenants dava a um
      // agente de uma PME um `access_token` que ve as conversas da outra. A
      // conta fechada sem o utilizador fechado era meia fechadura.
      //
      // **Só o `provider_user_id` colide**: o `account_id` e diferente, para
      // que a `conta_uq` nao possa recusar em vez dela.
      const [um] = await tenantNovo("handoff-uq-user-1");
      const [outro] = await tenantNovo("handoff-uq-user-2");
      const primeiro = new ProvedorFalso();
      primeiro.proximaConta = {
        accountId: 877,
        inboxId: 878,
        botId: 879,
        providerUserId: 880,
      };
      await hndDe(um, primeiro, new FilaFalsa()).ensureAccount(um);

      const segundo = new ProvedorFalso();
      segundo.proximaConta = {
        accountId: 1877,
        inboxId: 1878,
        botId: 1879,
        providerUserId: 880,
      };
      await assert.rejects(
        () => hndDe(outro, segundo, new FilaFalsa(), app2).ensureAccount(outro),
        /handoff_accounts_utilizador_uq/,
      );
    });
  });

  describe("o fecho sem contexto de sessao (o no-op silencioso)", () => {
    it("**sem `app.tenant_id` o fecho levanta, e nao devolve zero linhas**", async () => {
      // Era o defeito mais caro deste modulo e nao se via de lado nenhum. O
      // `close(handoffId, outcome)` do §11.1 nao tem `tenantId`, pelo que o
      // `SQL_FECHAR` le o tenant do contexto da sessao. Com
      // `current_setting('app.tenant_id', true)` — a forma **lenient** — uma
      // variavel nao definida devolve NULL, `tenant_id = NULL` nao e verdadeiro
      // para linha nenhuma, e o `close` nao casava nada **em silencio**: zero
      // linhas, nenhuma metrica, nenhum registo, e um 200 ao provedor, que para
      // de reenviar. A passagem ficava em `waiting` para sempre e aparecia no
      // painel do SLA como atrasada, sem um unico sinal.
      //
      // A forma **estrita** levanta `42704`. Este teste e o que torna essa
      // escolha verificavel — e e o que mata a mutacao que a desfaz, porque
      // nenhum duplo o consegue: uma base falsa impoe o tenant em JavaScript e
      // nunca le o texto do SQL.
      //
      // **A passagem é `degraded` e não `waiting`, e isso mudou com a emenda
      // 1.42.** O `ESTADOS_QUE_FECHAM` passou a `["degraded"]`, pelo que uma
      // passagem em `waiting` já não é linha candidata deste `UPDATE` — e um
      // predicado que não casa nada deixa o planeador livre para nunca avaliar
      // o `current_setting`, o que fazia este teste passar sem medir aquilo que
      // diz medir. Com a passagem no estado de que se fecha, a excepção é a
      // única saída possível.
      const [tenant, conversa] = await tenantNovo("handoff-sem-contexto");
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenant, provedor, new FilaFalsa());
      await hnd.ensureAccount(tenant);
      provedor.emBaixo = true;
      const aberta = await hnd.openHandoff(pedido(tenant, conversa, "h_sem_contexto"));
      assert.equal(aberta.estado, "degraded", "a montagem tem de dar uma degradada");

      // Uma ligacao **sem** contexto, de proposito: e o unico sitio desta suite
      // onde o `definirContexto` nao corre antes da consulta.
      const cru = await ligar("app");
      try {
        const semContexto = new Handoff({
          bd: {
            query: async <T,>(texto: string, valores?: readonly unknown[]) => {
              const resultado = await cru.query(
                texto,
                valores === undefined ? [] : [...valores],
              );
              return { rows: resultado.rows as readonly T[] };
            },
          },
          provedor: {
            abrirConversa: async () => "x",
            espelhar: async () => undefined,
            fecharConversa: async () => undefined,
          },
          provisionador: {
            criarConta: async () => {
              throw new Error("este teste nao provisiona nada");
            },
          },
          fila: new FilaFalsa(),
          refDoTokenDoBot: (id) => `chatwoot_bot_token/${id}`,
          refDoTokenDoUtilizador: (id) => `chatwoot_user_token/${id}`,
          guardarSegredo: async () => undefined,
          segredoDoBot: async () => "cccc-segredo",
          retomar: async () => {
            throw new Error("este teste nao liga a porta da retoma");
          },
        });
        await assert.rejects(
          () => semContexto.close("h_sem_contexto", "resolved"),
          /app\.tenant_id|unrecognized configuration parameter/,
          "sem contexto tem de levantar, nao devolver zero linhas",
        );
      } finally {
        await cru.end();
      }

      // E a passagem **nao** mudou: a excepcao nao escreveu nada.
      await definirContexto(app, tenant);
      const linha = await app.query<{ status: string }>(
        "SELECT status FROM platform.handoffs WHERE handoff_id = $1",
        ["h_sem_contexto"],
      );
      assert.equal(linha.rows[0]?.status, "degraded");
    });
  });

  describe("o fecho sob concorrencia (criterio 7)", () => {
    /**
     * Uma passagem `degraded`, que é a única de que o HND fecha.
     *
     * A emenda 1.42 tirou o `waiting` ao `ESTADOS_QUE_FECHAM`: estes dois testes
     * são sobre a **monotonia no predicado** e não sobre qual a transição, pelo
     * que continuam a medir o que mediam — com a passagem no estado de que este
     * lado fecha.
     */
    async function degradada(id: string, cliente: pg.Client = app): Promise<Handoff> {
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa(), cliente);
      provedor.emBaixo = true;
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, id));
      assert.equal(aberta.estado, "degraded");
      return hnd;
    }

    it("**dois close em paralelo: um escreve e o outro nao casa**", async () => {
      const provedor = new ProvedorFalso();
      const fila = new FilaFalsa();
      const um = hndDe(tenantA, provedor, fila, app);
      const outro = hndDe(tenantA, provedor, fila, app2);
      provedor.emBaixo = true;
      const aberta = await um.openHandoff(pedido(tenantA, conversaA, "h_fecho"));
      assert.equal(aberta.estado, "degraded");

      await Promise.all([um.close("h_fecho", "resolved"), outro.close("h_fecho", "resolved")]);

      await definirContexto(app, tenantA);
      const linha = await app.query<{ status: string; resumed_at: Date | null }>(
        "SELECT status, resumed_at FROM platform.handoffs WHERE handoff_id = $1",
        ["h_fecho"],
      );
      assert.equal(linha.rows[0]?.status, "resumed");
      assert.notEqual(linha.rows[0]?.resumed_at, null);
      // E as metricas dos dois somadas contam **uma** passagem fechada: o
      // segundo `UPDATE` devolveu zero linhas e nao contou.
      const somado =
        (um.metricas.ler()["hnd_handoff_total:resumed"] ?? 0) +
        (outro.metricas.ler()["hnd_handoff_total:resumed"] ?? 0);
      assert.equal(somado, 1, `contou ${somado} vezes`);
    });

    it("de um estado concluido nao se fecha outra vez", async () => {
      const hnd = await degradada("h_terminal");
      await hnd.close("h_terminal", "cancelled");
      await hnd.close("h_terminal", "resolved");

      await definirContexto(app, tenantA);
      const linha = await app.query<{ status: string }>(
        "SELECT status FROM platform.handoffs WHERE handoff_id = $1",
        ["h_terminal"],
      );
      assert.equal(linha.rows[0]?.status, "cancelled", "o cancelled nao se torna resumed");
    });

    it("**uma passagem em waiting nao se fecha por aqui**", async () => {
      // A fronteira da emenda 1.42, contra a base: a saida de `waiting` e do
      // AGR nos tres desfechos, e nenhum dos tres a tira daqui.
      const hnd = hndDe(tenantA, new ProvedorFalso(), new FilaFalsa());
      await hnd.openHandoff(pedido(tenantA, conversaA, "h_so_o_agr"));
      for (const outcome of ["resolved", "timeout", "cancelled"] as const) {
        await hnd.close("h_so_o_agr", outcome);
      }

      await definirContexto(app, tenantA);
      const linha = await app.query<{ status: string; resumed_at: Date | null }>(
        "SELECT status, resumed_at FROM platform.handoffs WHERE handoff_id = $1",
        ["h_so_o_agr"],
      );
      assert.equal(linha.rows[0]?.status, "waiting");
      assert.equal(linha.rows[0]?.resumed_at, null);
      assert.equal(hnd.metricas.ler()["hnd_handoff_total:resumed"], undefined);
    });
  });

  /**
   * A fronteira entre os dois escritores, contra a base (emenda 1.42).
   *
   * **O que só aqui se prova:** que as duas escritas do HND e a do AGR compõem
   * contra um PostgreSQL a sério — o `resolver` por uma instrução e o `status`
   * por outra, em sessões diferentes, com os privilégios de `kamba_app` a
   * chegarem para as duas e a RLS no meio. A base falsa da bateria do *gate* 4
   * não lê o texto do SQL, pelo que nada disto se vê lá.
   */
  describe("a fronteira da retoma (emenda 1.42, credor do criterio 3 do KAM-034)", () => {
    function corpoResolvido(handoffId: string, externalId: string): Record<string, unknown> {
      return {
        event: "conversation_status_changed",
        conversation: {
          id: externalId,
          status: "resolved",
          custom_attributes: { handoffId },
        },
        assignee: { id: 7, name: "Beto", email: "beto@loja.ao" },
      };
    }

    it("**o resolver chega a base sem passar pelo AGR, e o status vem do CAS**", async () => {
      // A propriedade que o ADR-010 obriga: a identidade do agente é escrita
      // deste lado, numa instrução separada, e o corpo que vai ao AGR não a
      // leva. As duas sessões são diferentes de propósito — o HND na `app` e o
      // CAS na `app2` —, que é como corre em produção: dois processos.
      const pedidos: PedidoDeRetoma[] = [];
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa(), app, agrDe(app2, pedidos));
      await hnd.ensureAccount(tenantA);
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_fronteira"));
      assert.equal(aberta.estado, "waiting");

      const veredicto = await hnd.receber(
        tenantA,
        "cccc-segredo",
        corpoResolvido("h_fronteira", aberta.externalId),
      );
      assert.equal(veredicto.aceite, true);

      await definirContexto(app, tenantA);
      const linha = await app.query<{
        status: string;
        resolver: string | null;
        resumed_at: Date | null;
      }>(
        "SELECT status, resolver, resumed_at FROM platform.handoffs WHERE handoff_id = $1",
        ["h_fronteira"],
      );
      assert.equal(linha.rows[0]?.resolver, "7", "o resolver e escrito pelo HND");
      assert.equal(linha.rows[0]?.status, "resumed", "e o status pelo CAS do AGR");
      assert.notEqual(linha.rows[0]?.resumed_at, null);
      // E o corpo que foi ao AGR tem tres campos, com o `thread_id` montado a
      // partir do `contact_id` que a consulta trouxe — nao de um campo que
      // alguem escreveu.
      assert.deepEqual(pedidos, [
        {
          threadId: threadDe(tenantA, contactoA),
          handoffId: "h_fronteira",
          outcome: "resolved",
        },
      ]);
    });

    it("**dois webhooks duplicados dao UMA retoma e UM resolver**", async () => {
      const pedidos: PedidoDeRetoma[] = [];
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa(), app, agrDe(app2, pedidos));
      await hnd.ensureAccount(tenantA);
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_duplicado"));
      const corpo = corpoResolvido("h_duplicado", aberta.externalId);

      await hnd.receber(tenantA, "cccc-segredo", corpo);
      await definirContexto(app, tenantA);
      const primeiro = await app.query<{ resumed_at: Date }>(
        "SELECT resumed_at FROM platform.handoffs WHERE handoff_id = $1",
        ["h_duplicado"],
      );
      // O segundo *webhook*, com **outro** agente: nem o `status` nem o
      // `resolver` se reescrevem.
      await hnd.receber(tenantA, "cccc-segredo", {
        ...corpo,
        assignee: { id: 99 },
      });

      await definirContexto(app, tenantA);
      const linha = await app.query<{
        status: string;
        resolver: string | null;
        resumed_at: Date;
      }>(
        "SELECT status, resolver, resumed_at FROM platform.handoffs WHERE handoff_id = $1",
        ["h_duplicado"],
      );
      assert.equal(linha.rows[0]?.status, "resumed");
      assert.equal(linha.rows[0]?.resolver, "7", "quem respondeu foi o primeiro");
      assert.deepEqual(
        linha.rows[0]?.resumed_at,
        primeiro.rows[0]?.resumed_at,
        "o resumed_at nao se reescreve",
      );
      assert.equal(hnd.metricas.ler()["hnd_handoff_total:resumed"], 1);
    });

    it("**um handoffId de outra conversa nao retoma, contra a base**", async () => {
      // O `handoff_id` chega do atributo de uma conversa no provedor, isto e, de
      // fora: um valor trocado la fazia-nos pedir a retoma do *thread* de outra
      // pessoa — o perigo que o §3.32 nomeia para o CAS, visto deste lado. Quem
      // o impede e o `receber`, que confronta a conversa da linha com a do
      // *callback*; **o predicado da consulta nao**, e essa foi a correccao da
      // revisao adversarial (uma passagem `degraded` pode ter conversa la).
      const pedidos: PedidoDeRetoma[] = [];
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa(), app, agrDe(app2, pedidos));
      await hnd.ensureAccount(tenantA);
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_thread"));
      assert.notEqual(aberta.externalId, "cw-de-outra-conversa");

      await hnd.receber(
        tenantA,
        "cccc-segredo",
        corpoResolvido("h_thread", "cw-de-outra-conversa"),
      );

      assert.deepEqual(pedidos, [], "nao se pede retoma nenhuma");
      await definirContexto(app, tenantA);
      const linha = await app.query<{ status: string; resolver: string | null }>(
        "SELECT status, resolver FROM platform.handoffs WHERE handoff_id = $1",
        ["h_thread"],
      );
      assert.equal(linha.rows[0]?.status, "waiting");
      assert.equal(linha.rows[0]?.resolver, null, "nem se escreve o resolver");
    });

    it("**a consulta do thread nao atravessa tenants**", async () => {
      // Com o contexto de B, pede-se a passagem de A. E a assercao que so pode
      // vir da RLS: ha linha, o `$1` e o tenant de A, e o que a esconde e a
      // politica sobre a sessao de B — a licao da revisao adversarial do
      // KAM-015.
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa());
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_thread_isolado"));

      await definirContexto(app2, tenantB);
      const deB = await app2.query(SQL_THREAD_DA_PASSAGEM, [tenantA, "h_thread_isolado"]);
      assert.equal(deB.rows.length, 0);

      await definirContexto(app, tenantA);
      const deA = await app.query<{ external_id: string | null }>(
        SQL_THREAD_DA_PASSAGEM,
        [tenantA, "h_thread_isolado"],
      );
      assert.equal(deA.rows.length, 1, "com o contexto certo tem de haver linha");
      assert.equal(deA.rows[0]?.external_id, aberta.externalId);
    });

    it("**uma passagem degraded com a conversa criada la recupera-se e retoma**", async () => {
      // **O defeito que a revisao adversarial mediu, contra a base.** O
      // `abrirConversa` cria a conversa no provedor e so depois publica a nota
      // privada: se a nota falhar, a passagem fica `degraded` com `external_id`
      // nulo e a conversa esta aberta la, com o atributo. Com o `external_id` no
      // predicado da consulta do *thread*, o *callback* dava zero linhas —
      // nenhuma retoma, 200 ao provedor, `interrupt()` pendente para sempre, e
      // invisivel porque a varredura dos prazos filtra `waiting`.
      const pedidos: PedidoDeRetoma[] = [];
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa(), app, agrDe(app2, pedidos));
      await hnd.ensureAccount(tenantA);
      provedor.emBaixo = true;
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_recuperada"));
      assert.equal(aberta.estado, "degraded");

      await definirContexto(app, tenantA);
      const antes = await app.query<{ external_id: string | null }>(
        "SELECT external_id FROM platform.handoffs WHERE handoff_id = $1",
        ["h_recuperada"],
      );
      assert.equal(antes.rows[0]?.external_id, null, "a montagem tem de dar external_id nulo");

      await hnd.receber(
        tenantA,
        "cccc-segredo",
        corpoResolvido("h_recuperada", "cw-criada-no-provedor"),
      );

      await definirContexto(app, tenantA);
      const linha = await app.query<{
        status: string;
        external_id: string | null;
        resolver: string | null;
      }>(
        "SELECT status, external_id, resolver FROM platform.handoffs WHERE handoff_id = $1",
        ["h_recuperada"],
      );
      assert.equal(linha.rows[0]?.external_id, "cw-criada-no-provedor", "a conversa fica gravada");
      assert.equal(linha.rows[0]?.status, "resumed", "e o CAS vence");
      assert.equal(linha.rows[0]?.resolver, "7");
      assert.equal(pedidos.length, 1);
    });

    it("**o recusado do AGR e alcancavel: um thread que nao e da passagem**", async () => {
      // O duplo da classificacao do zero linhas era **mais fraco** do que o
      // `_classificar` real — lia so `(tenant_id, handoff_id)` —, pelo que uma
      // passagem de outro contacto dava `repetido` (200) aqui e `recusado` (404,
      // que levanta no cliente) na peca. Com o predicado completo, o 404 passa a
      // ser observavel na unica suite que corre contra PostgreSQL.
      const pedidos: PedidoDeRetoma[] = [];
      const retomar = agrDe(app2, pedidos);
      const hnd = hndDe(tenantA, new ProvedorFalso(), new FilaFalsa());
      await hnd.openHandoff(pedido(tenantA, conversaA, "h_outro_thread"));

      const desfecho = await retomar({
        // Um contacto que nao e o da conversa desta passagem.
        threadId: threadDe(tenantA, "44444444-4444-4444-8444-444444444444"),
        handoffId: "h_outro_thread",
        outcome: "resolved",
      });
      assert.equal(desfecho, "recusado");

      // E a passagem **nao** mudou: o predicado do CAS leva o contacto.
      await definirContexto(app, tenantA);
      const linha = await app.query<{ status: string }>(
        "SELECT status FROM platform.handoffs WHERE handoff_id = $1",
        ["h_outro_thread"],
      );
      assert.equal(linha.rows[0]?.status, "waiting");
    });

    it("**a consulta do thread devolve a conversa gravada, para o chamador decidir**", async () => {
      // **A primeira versao deste ensaio fixava uma afirmacao falsa**, e era a
      // do `external_id` no predicado: «ela tem `external_id` nulo porque nao
      // existe no provedor, pelo que nenhum *callback* legitimo dele pode ser
      // dela». Pode — ver o ensaio da recuperacao, acima. A consulta devolve a
      // linha com a coluna como ela esta, e quem decide e o `receber`.
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa());
      provedor.emBaixo = true;
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_degradada_thread"));
      assert.equal(aberta.estado, "degraded");

      await definirContexto(app, tenantA);
      const degradada = await app.query<{ contact_id: string; external_id: string | null }>(
        SQL_THREAD_DA_PASSAGEM,
        [tenantA, "h_degradada_thread"],
      );
      assert.equal(degradada.rows.length, 1, "a linha existe e o JOIN casa");
      assert.equal(degradada.rows[0]?.contact_id, contactoA);
      assert.equal(degradada.rows[0]?.external_id, null, "e e isto que o chamador le");

      // E o controlo positivo: uma passagem aberta a serio traz a conversa que
      // gravamos. Sem ele, a assercao de cima passava com uma consulta que
      // devolvesse `null` sempre.
      provedor.emBaixo = false;
      const normal = await hnd.openHandoff(pedido(tenantA, conversaA, "h_thread_normal"));
      assert.equal(normal.estado, "waiting");
      await definirContexto(app, tenantA);
      const comConversa = await app.query<{ external_id: string | null }>(
        SQL_THREAD_DA_PASSAGEM,
        [tenantA, "h_thread_normal"],
      );
      assert.equal(comConversa.rows[0]?.external_id, normal.externalId);
    });
  });

  describe("isolamento (Testes Requeridos: X-03 sobre handoffs)", () => {
    it("com o contexto de A, as passagens de B nao aparecem", async () => {
      await hndDe(tenantB, new ProvedorFalso(), new FilaFalsa(), app2).openHandoff(
        pedido(tenantB, conversaB, "h_de_b"),
      );

      await definirContexto(app, tenantA);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.handoffs WHERE handoff_id = $1",
        ["h_de_b"],
      );
      assert.equal(linhas.rows[0]?.n, "0");
    });

    it("com o contexto de A, uma escrita na passagem de B nao acontece", async () => {
      await definirContexto(app, tenantA);
      const escrita = await app.query(
        "UPDATE platform.handoffs SET status = 'cancelled' WHERE handoff_id = $1",
        ["h_de_b"],
      );
      assert.equal(escrita.rowCount, 0, "com FORCE, nem como dono");

      await definirContexto(app2, tenantB);
      const linha = await app2.query<{ status: string }>(
        "SELECT status FROM platform.handoffs WHERE handoff_id = $1",
        ["h_de_b"],
      );
      assert.equal(linha.rows[0]?.status, "waiting", "a de B ficou como estava");
    });

    it("as contas de atendimento de A nao se veem com o contexto de B", async () => {
      await definirContexto(app2, tenantB);
      const linhas = await app2.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.handoff_accounts WHERE tenant_id = $1",
        [tenantA],
      );
      assert.equal(linhas.rows[0]?.n, "0");
    });
  });

  describe("o SLA de retoma (docs/tecnica/02 §11)", () => {
    it("o SQL_FORA_DO_SLA so ve as do proprio tenant", async () => {
      // **Com o contexto de B, pede-se o de A.** E a assercao que so pode vir
      // da RLS: o `$1` e o tenant de A, ha passagens de A, e o que as esconde e
      // a politica sobre a sessao de B. Pedir o de B com o contexto de B dava
      // zero pelo `WHERE tenant_id = $1` e nao dizia nada — foi a licao da
      // revisao adversarial do KAM-015.
      await definirContexto(app2, tenantB);
      const deA = await app2.query(SQL_FORA_DO_SLA, [tenantA, "0 seconds"]);
      assert.equal(deA.rows.length, 0, "a RLS tem de esconder as de A");

      await definirContexto(app, tenantA);
      const comA = await app.query(SQL_FORA_DO_SLA, [tenantA, "0 seconds"]);
      assert.ok(
        comA.rows.length > 0,
        "com o contexto de A tem de haver passagens, senao o zero acima nao diz nada",
      );
    });

    it("uma passagem retomada sai do painel do SLA", async () => {
      // **Retomada e não «fechada»**, e a diferença é a emenda 1.42: quem a
      // tira de `waiting` é o CAS do AGR. O painel não muda — continua a ver
      // `waiting` e `degraded` —, o que mudou é quem escreve a saída.
      const pedidos: PedidoDeRetoma[] = [];
      const hnd = hndDe(
        tenantA,
        new ProvedorFalso(),
        new FilaFalsa(),
        app,
        agrDe(app2, pedidos),
      );
      await hnd.ensureAccount(tenantA);
      const aberta = await hnd.openHandoff(pedido(tenantA, conversaA, "h_sla"));
      await definirContexto(app, tenantA);
      const antes = await app.query(SQL_FORA_DO_SLA, [tenantA, "0 seconds"]);

      await hnd.receber(tenantA, "cccc-segredo", {
        event: "conversation_status_changed",
        conversation: {
          id: aberta.externalId,
          status: "resolved",
          custom_attributes: { handoffId: "h_sla" },
        },
        assignee: { id: 7 },
      });

      await definirContexto(app, tenantA);
      const depois = await app.query(SQL_FORA_DO_SLA, [tenantA, "0 seconds"]);
      assert.equal(depois.rows.length, antes.rows.length - 1);
      assert.equal(pedidos.length, 1);
    });

    it("**uma passagem degradada conta no SLA**", async () => {
      // Uma passagem que nem chegou ao provedor esta tao longe de ser atendida
      // como uma a espera, e esconder-lhe o atraso era mostrar um painel verde
      // no pior caso.
      const provedor = new ProvedorFalso();
      const hnd = hndDe(tenantA, provedor, new FilaFalsa());
      await hnd.ensureAccount(tenantA);
      provedor.emBaixo = true;
      const resultado = await hnd.openHandoff(pedido(tenantA, conversaA, "h_degradada"));
      assert.equal(resultado.estado, "degraded");

      await definirContexto(app, tenantA);
      const fora = await app.query<{ handoff_id: string; status: string }>(
        SQL_FORA_DO_SLA,
        [tenantA, "0 seconds"],
      );
      assert.ok(
        fora.rows.some((l) => l.handoff_id === "h_degradada" && l.status === "degraded"),
        "a degradada tem de aparecer no painel",
      );
    });
  });
});

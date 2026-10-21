/**
 * O MED contra a base, com a RLS ligada (KAM-020).
 *
 * ## Porque é que esta bateria existe, e é a lição mais cara do KAM-019
 *
 * As três baterias do *gate* 4 montam a base por porta, e uma base falsa
 * **nunca lê o texto do SQL**: ela despacha por identidade da constante e
 * responde o que o ensaio quiser. Isso tem uma consequência que só a prova por
 * mutação mostra — **qualquer mutação do SQL sobrevive**, e uma mutação que
 * nenhum teste pode matar conta como prova de uma garantia que não temos.
 *
 * No KAM-019 isso aconteceu de verdade: a mutação «o fecho deixa de ler o
 * tenant da sessao» era imortal, porque a base falsa impunha o *tenant* em
 * JavaScript.
 *
 * O que **só** um PostgreSQL prova, e é o que está aqui:
 *
 * 1. **O `ON CONFLICT` da reserva**, com duas chamadas **concorrentes** em duas
 *    ligações. Sequencialmente a segunda nunca chega ao `INSERT` — encontra a
 *    linha na leitura e sai pelo caminho rápido —, pelo que o conflito só
 *    acontece em concorrência. Foi exactamente este o buraco que a prova por
 *    mutação encontrou no `ensureAccount` do KAM-019.
 * 2. **O `WHERE estado = 'pendente'` do `SQL_MARCAR_ARMAZENADO`**, que é a
 *    monotonia no predicado: sem ele, uma segunda passagem reescrevia um
 *    `armazenado` já feito — ou ressuscitava um `rejeitado`.
 * 3. **O X-03 sobre a `media_assets`**: com o contexto de A, as linhas de B não
 *    aparecem, e uma escrita na linha de B não acontece — com `FORCE`, nem como
 *    dono da tabela.
 * 4. **As restrições a morderem através do módulo**, e não por um `INSERT`
 *    escrito à mão no teste: um `armazenado` sem `storage_ref` é recusado pela
 *    `media_assets_armazenado_ck` quando o caminho que o produz é o do código.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import {
  Med,
  MidiaIndisponivelError,
  type ClienteDeMidia,
  type MidiaDescarregada,
  type MidiaResolvida,
  type PedidoDeMidia,
} from "../src/med/index.ts";
import { criarStorageFake } from "../src/storage/index.ts";
import { BASE_DESCARTAVEL, apagarTenant, criarCanal, criarTenant, ligar } from "./apoio.ts";

/**
 * Põe o contexto de *tenant* na ligação, **de sessão**.
 *
 * `set_config(..., false)` e não `true`: o terceiro argumento a `true` é «local
 * à transacção», e fora de um `BEGIN` explícito cada instrução é a sua própria
 * transacção — a definição desaparece antes da seguinte, e com RLS `FORCE` o
 * `kamba_app` fica sem contexto e vê zero linhas. É a lição que a *suite* da
 * saída pagou com uma execução de 421 s.
 */
async function definirContexto(cliente: pg.Client, tenant: string): Promise<void> {
  await cliente.query("SELECT set_config('app.tenant_id', $1, false)", [tenant]);
}

const URL_DA_META = "https://lookaside.fbsbx.com/attachments/?mid=CANARIO";

/** A Meta por porta: é a única coisa aqui que este ticket não pode medir. */
class MetaFalsa implements ClienteDeMidia {
  resolucoes = 0;
  descargas = 0;
  emBaixo = false;
  contentType = "audio/ogg";
  bytes = new Uint8Array([9, 8, 7, 6, 5, 4, 3, 2, 1]);
  /** Corre **durante** a descarga: a janela em que outro pode escrever. */
  antesDeDescarregar: (() => Promise<void>) | null = null;

  /** Corre **durante** a resolução: a janela do caminho da falha. */
  antesDeResolver: (() => Promise<void>) | null = null;

  readonly resolver = async (): Promise<MidiaResolvida> => {
    this.resolucoes += 1;
    await this.antesDeResolver?.();
    if (this.emBaixo) throw new MidiaIndisponivelError("resolver: sem resposta");
    return { url: URL_DA_META, contentType: this.contentType };
  };

  readonly descarregar = async (): Promise<MidiaDescarregada> => {
    this.descargas += 1;
    await this.antesDeDescarregar?.();
    if (this.emBaixo) throw new MidiaIndisponivelError("descarregar: sem resposta");
    return { bytes: this.bytes, contentType: this.contentType };
  };
}

describe("o MED contra a base (KAM-020)", () => {
  let admin: pg.Client;
  let app: pg.Client;
  let app2: pg.Client;
  let tenantA = "";
  let tenantB = "";
  let conversaA = "";
  let contactoA = "";
  let conversaB = "";
  let contactoB = "";
  const descartaveis: string[] = [];

  /**
   * Um MED com a base **verdadeira** e o armazenamento por duplo.
   *
   * O armazenamento é o duplo do KAM-011 — que é a porta a sério, com as
   * validações de chave e o `signUrl` — e a base é um PostgreSQL. A Meta é
   * porta falsa, e tem de ser.
   */
  function medDe(tenant: string, meta: MetaFalsa, cliente: pg.Client = app): Med {
    return new Med({
      bd: {
        // Genérica e com a conversão à vista, pela razão que a *suite* da saída
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
      armazenamento: criarStorageFake().storage,
      midia: meta,
      avisarAgr: async () => undefined,
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

    tenantA = await criarTenant(admin, "media-a");
    tenantB = await criarTenant(admin, "media-b");
    const canalA = await criarCanal(admin, tenantA);
    const canalB = await criarCanal(admin, tenantB);
    [conversaA, contactoA] = await abrirConversa(tenantA, canalA.id);
    [conversaB, contactoB] = await abrirConversa(tenantB, canalB.id);
  });

  after(async () => {
    for (const tenant of descartaveis) await apagarTenant(admin, tenant);
    await apagarTenant(admin, tenantA);
    await apagarTenant(admin, tenantB);
    await admin.end();
    await app.end();
    await app2.end();
  });

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

  /** Um *tenant* novo com conversa, para os casos que precisam de limpo. */
  async function tenantNovo(rotulo: string): Promise<[string, string, string]> {
    const tenant = await criarTenant(admin, rotulo);
    descartaveis.push(tenant);
    const canal = await criarCanal(admin, tenant);
    const [conversa, contacto] = await abrirConversa(tenant, canal.id);
    return [tenant, conversa, contacto];
  }

  function pedido(
    tenant: string,
    conversa: string,
    contacto: string,
    troca: Partial<PedidoDeMidia> = {},
  ): PedidoDeMidia {
    return {
      tenantId: tenant,
      contactId: contacto,
      conversationId: conversa,
      wamid: `wamid.${Math.random().toString(16).slice(2, 14)}`,
      mediaId: `media-${Math.random().toString(16).slice(2, 14)}`,
      waType: "audio",
      ...troca,
    };
  }

  describe("idempotencia (criterio 2)", () => {
    it("**tres chamadas sequenciais: 1 linha e 1 descarga**", async () => {
      const [tenant, conversa, contacto] = await tenantNovo("media-seq");
      const meta = new MetaFalsa();
      const med = medDe(tenant, meta);
      const base = pedido(tenant, conversa, contacto);

      const primeira = await med.receber(base);
      await med.receber(base);
      await med.receber(base);

      assert.ok(primeira.estado === "armazenado");
      assert.equal(meta.descargas, 1, "a segunda descarga e o defeito");
      await definirContexto(app, tenant);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.media_assets WHERE tenant_id = $1",
        [tenant],
      );
      assert.equal(linhas.rows[0]?.n, "1");
    });

    it("**duas chamadas concorrentes: o `ON CONFLICT` da reserva**", async () => {
      // **Sequencialmente a segunda nunca chega ao `INSERT`**: encontra a linha
      // na leitura e sai pelo caminho rapido. O conflito so acontece em
      // concorrencia, e e por isso que este teste existe — e por isso que a
      // mutacao que apaga o `ON CONFLICT` sobrevive sem ele.
      const [tenant, conversa, contacto] = await tenantNovo("media-conc");
      const uma = new MetaFalsa();
      const outra = new MetaFalsa();
      const base = pedido(tenant, conversa, contacto);

      const [primeira, segunda] = await Promise.all([
        medDe(tenant, uma, app).receber(base),
        medDe(tenant, outra, app2).receber(base),
      ]);

      // **Uma linha**, e as duas chamadas devolvem o mesmo `assetId`.
      await definirContexto(app, tenant);
      const linhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.media_assets WHERE tenant_id = $1",
        [tenant],
      );
      assert.equal(linhas.rows[0]?.n, "1", "duas linhas: o ON CONFLICT nao funcionou");
      assert.equal(primeira.assetId, segunda.assetId);
      // Uma das duas armazenou; a outra devolveu o que estava. **Nunca as
      // duas**: isso seria dois objectos para a mesma origem.
      const armazenadas = [primeira, segunda].filter(
        (r) => r.estado === "armazenado" && !r.repetido,
      );
      assert.equal(armazenadas.length, 1, "as duas armazenaram");

      // **E nenhuma das duas pode dizer `falhou`**, que era o defeito que a
      // revisao adversarial apanhou e que estas duas assercoes nao tinham. A
      // perdedora do `ON CONFLICT` le a linha em `pendente` — a vencedora ainda
      // esta a descarregar — e a primeira versao devolvia-lhe `falhou` com
      // `tentativas: 0`. Quem chama ramifica em `falhou` (e o que o criterio 6
      // manda) e pedia ao cliente que reenviasse enquanto a descarga do outro
      // *worker* corria. As duas assercoes acima passavam com isso.
      for (const resultado of [primeira, segunda]) {
        assert.notEqual(
          resultado.estado,
          "falhou",
          "uma corrida ganha nao e uma falha: o cliente seria mandado reenviar",
        );
      }
      // A perdedora diz `pendente` ou `armazenado` — as duas sao verdade,
      // porque depende de a vencedora ter acabado antes de ela ler.
      const perdedora = [primeira, segunda].find(
        (r) => !(r.estado === "armazenado" && !r.repetido),
      );
      assert.ok(perdedora !== undefined);
      assert.ok(
        perdedora.estado === "pendente" || perdedora.estado === "armazenado",
        `a perdedora disse ${perdedora.estado}`,
      );
    });
  });

  describe("a monotonia do estado", () => {
    it("**a marcacao do modulo nao casa quando o estado mudou**", async () => {
      // **Este e o teste que as duas mutacoes sobreviventes pediram**, e a
      // licao e minha: a primeira versao desta bateria fazia o `UPDATE` **a
      // mao**, com o `AND estado = 'pendente'` escrito no proprio teste. Isso
      // prova que o PostgreSQL sabe comparar duas cadeias; nao prova nada sobre
      // o SQL do modulo, e as duas mutacoes — tirar o predicado do
      // `SQL_MARCAR_ARMAZENADO`, e descartar o resultado dele — sobreviveram as
      // duas.
      //
      // O que as mata e passar pelo **caminho do codigo**, e a unica forma de o
      // fazer e mexer na linha **durante** a descarga: e a janela em que o
      // modulo ja reservou e ainda nao marcou. O gancho `antesDeDescarregar`
      // existe para isto.
      const [tenant, conversa, contacto] = await tenantNovo("media-janela");
      const meta = new MetaFalsa();
      const med = medDe(tenant, meta);
      const base = pedido(tenant, conversa, contacto);

      meta.antesDeDescarregar = async () => {
        // Outro processo rejeitou a linha enquanto esta descarga corria. Usa-se
        // a ligacao **do admin**, para nao mexer no contexto da que o modulo
        // esta a usar.
        await admin.query(
          "UPDATE platform.media_assets SET estado = 'rejeitado' " +
            "WHERE tenant_id = $1 AND wamid = $2 AND media_id = $3",
          [tenant, base.wamid, base.mediaId],
        );
      };

      const resultado = await med.receber(base);

      // **Sem o predicado, a marcacao casava e o estado virava `armazenado`.**
      await definirContexto(app, tenant);
      const linha = await app.query<{ estado: string; storage_ref: string | null }>(
        "SELECT estado, storage_ref FROM platform.media_assets " +
          "WHERE tenant_id = $1 AND wamid = $2",
        [tenant, base.wamid],
      );
      assert.equal(
        linha.rows[0]?.estado,
        "rejeitado",
        "a marcacao reescreveu um estado que nao era `pendente`",
      );
      assert.equal(
        linha.rows[0]?.storage_ref,
        null,
        "a marcacao escreveu a chave sobre uma linha rejeitada",
      );

      // **E sem a leitura do resultado, o modulo dizia `armazenado`** a quem
      // chamou, sobre uma linha que a base diz estar rejeitada.
      assert.equal(
        resultado.estado,
        "rejeitado",
        "o modulo devolveu um estado que a base nao tem",
      );
    });


    it("uma segunda marcacao a mao nao reescreve um `armazenado`", async () => {
      // **Este teste nao prova o SQL do modulo**, e o nome di-lo agora: ele
      // escreve o `AND estado = 'pendente'` no proprio teste, pelo que prova
      // que o PostgreSQL compara duas cadeias. Fica porque confirma a forma da
      // instrucao contra a base, e **saiu da lista de obrigatorios** do gate: o
      // que prende a propriedade e «a marcacao do modulo nao casa quando o
      // estado mudou», acima, que passa pelo caminho do codigo. A revisao
      // adversarial apanhou a confusao entre os dois.
      // O `WHERE estado = 'pendente'` do `SQL_MARCAR_ARMAZENADO`. Sem ele, uma
      // segunda passagem reescrevia o que ja estava — e o `content_type`, o
      // `size` e o `sha256` da segunda podiam ser de outro objecto.
      const [tenant, conversa, contacto] = await tenantNovo("media-mono");
      const meta = new MetaFalsa();
      const med = medDe(tenant, meta);
      const base = pedido(tenant, conversa, contacto);
      const primeira = await med.receber(base);
      assert.ok(primeira.estado === "armazenado");

      await definirContexto(app, tenant);
      const antes = await app.query<{ sha256: string; size: string }>(
        "SELECT sha256, size::text AS size FROM platform.media_assets " +
          "WHERE tenant_id = $1 AND asset_id = $2",
        [tenant, primeira.assetId],
      );

      // A marcacao outra vez, com outro conteudo: **nao casa**.
      const marcada = await app.query(
        "UPDATE platform.media_assets SET estado = 'armazenado', sha256 = $3 " +
          "WHERE tenant_id = $1 AND asset_id = $2 AND estado = 'pendente' " +
          "RETURNING asset_id",
        [tenant, primeira.assetId, "b".repeat(64)],
      );
      assert.equal(marcada.rows.length, 0, "a segunda marcacao casou");

      const depois = await app.query<{ sha256: string }>(
        "SELECT sha256 FROM platform.media_assets WHERE asset_id = $1",
        [primeira.assetId],
      );
      assert.equal(depois.rows[0]?.sha256, antes.rows[0]?.sha256, "o resumo mudou");
    });

    it("**um `rejeitado` nao ressuscita**", async () => {
      const [tenant, conversa, contacto] = await tenantNovo("media-rej");
      const meta = new MetaFalsa();
      meta.contentType = "application/zip";
      const med = medDe(tenant, meta);
      const resultado = await med.receber(pedido(tenant, conversa, contacto));
      assert.ok(resultado.estado === "rejeitado");

      await definirContexto(app, tenant);
      const marcada = await app.query(
        "UPDATE platform.media_assets SET estado = 'armazenado' " +
          "WHERE tenant_id = $1 AND asset_id = $2 AND estado = 'pendente' " +
          "RETURNING asset_id",
        [tenant, resultado.assetId],
      );
      assert.equal(marcada.rows.length, 0);
    });
  });

  describe("os dois caminhos de desfecho tambem leem o resultado", () => {
    it("**a rejeicao que nao casa nao mente a quem chamou**", async () => {
      // O par do teste da janela, para o caminho da **rejeicao**. A prova por
      // mutacao pediu-o: eu corrigi o codigo (os dois caminhos de desfecho
      // passaram a ler o resultado do `UPDATE`) e **nao escrevi o teste**, pelo
      // que as duas mutacoes que o desfazem sobreviveram as duas. E a mesma
      // falha, duas vezes no mesmo ticket.
      //
      // A janela e a mesma: outro processo marca a linha **durante** a descarga,
      // e quando o modulo a tenta marcar `rejeitado` o `AND estado = 'pendente'`
      // nao casa. Sem ler o resultado, ele dizia `rejeitado` a quem chamou sobre
      // uma linha que a base diz estar `armazenado`.
      const [tenant, conversa, contacto] = await tenantNovo("media-rej-janela");
      const meta = new MetaFalsa();
      meta.contentType = "application/zip";
      const med = medDe(tenant, meta);
      const base = pedido(tenant, conversa, contacto);

      meta.antesDeDescarregar = async () => {
        await admin.query(
          "UPDATE platform.media_assets " +
            "SET estado = 'armazenado', content_type = 'audio/ogg', size = 1, " +
            "    sha256 = $4, storage_ref = 't/x/media_audio/2026/10/abc' " +
            "WHERE tenant_id = $1 AND wamid = $2 AND media_id = $3",
          [tenant, base.wamid, base.mediaId, "a".repeat(64)],
        );
      };

      const resultado = await med.receber(base);

      assert.equal(
        resultado.estado,
        "armazenado",
        "o modulo disse `rejeitado` sobre uma linha que a base diz estar armazenada",
      );
      await definirContexto(app, tenant);
      const linha = await app.query<{ estado: string }>(
        "SELECT estado FROM platform.media_assets WHERE tenant_id = $1 AND wamid = $2",
        [tenant, base.wamid],
      );
      assert.equal(linha.rows[0]?.estado, "armazenado", "a rejeicao reescreveu o estado");
    });

    it("**a falha que nao casa nao avisa o AGR**", async () => {
      // E aqui e mais grave do que na rejeicao: sem ler o resultado, o modulo
      // avisava o AGR a pedir reenvio com base num `UPDATE` que nao fez nada —
      // o cliente recebia um pedido de reenvio por causa de uma falha que a base
      // nao registou.
      //
      // A janela e a da **resolucao**, porque com a Meta em baixo e o `resolver`
      // que estoura e o `descarregar` nunca corre.
      const [tenant, conversa, contacto] = await tenantNovo("media-falha-janela");
      const meta = new MetaFalsa();
      meta.emBaixo = true;
      const avisos: unknown[] = [];
      const base = pedido(tenant, conversa, contacto);
      const med = new Med({
        bd: {
          query: async <T,>(texto: string, valores?: readonly unknown[]) => {
            await definirContexto(app, tenant);
            const resultado = await app.query(
              texto,
              valores === undefined ? [] : [...valores],
            );
            return { rows: resultado.rows as readonly T[] };
          },
        },
        armazenamento: criarStorageFake().storage,
        midia: meta,
        avisarAgr: async (aviso) => {
          avisos.push(aviso);
        },
      });

      let primeira = true;
      meta.antesDeResolver = async () => {
        // So na primeira tentativa: outro processo rejeitou a linha.
        if (!primeira) return;
        primeira = false;
        await admin.query(
          "UPDATE platform.media_assets SET estado = 'rejeitado' " +
            "WHERE tenant_id = $1 AND wamid = $2 AND media_id = $3",
          [tenant, base.wamid, base.mediaId],
        );
      };

      const resultado = await med.receber(base);

      assert.equal(
        resultado.estado,
        "rejeitado",
        "o modulo disse `falhou` sobre uma linha que a base diz estar rejeitada",
      );
      assert.deepEqual(
        avisos,
        [],
        "**o AGR foi avisado** com base num UPDATE que nao fez nada: o cliente " +
          "seria mandado reenviar por uma falha que a base nao registou",
      );
    });
  });

  describe("as restricoes mordem atraves do modulo", () => {
    it("um `armazenado` sem `storage_ref` e recusado pela base", async () => {
      // **O comentario anterior era falso**, e a revisao adversarial apanhou-o:
      // ele dizia «aqui a tentativa vem de uma instrucao com a forma da que o
      // modulo emite», e a instrucao deste teste e um `UPDATE SET
      // estado='armazenado'` **sem** `storage_ref` e **sem** `AND estado =
      // 'pendente'` — uma forma que o modulo nunca emite, porque o
      // `SQL_MARCAR_ARMAZENADO` escreve sempre a chave e exige sempre
      // `pendente`. Fica como confirmacao da restricao contra a base, e **saiu
      // da lista de obrigatorios**: quem a prova pelo caminho do codigo e o
      // teste da janela, e quem a prova pelo esquema e o
      // `test_armazenado_sem_storage_ref_e_recusado`.
      const [tenant, conversa, contacto] = await tenantNovo("media-ck");
      const meta = new MetaFalsa();
      const med = medDe(tenant, meta);
      meta.emBaixo = true;
      const resultado = await med.receber(pedido(tenant, conversa, contacto));
      assert.ok(resultado.estado === "falhou");

      await definirContexto(app, tenant);
      await assert.rejects(
        () =>
          app.query(
            "UPDATE platform.media_assets SET estado = 'armazenado' " +
              "WHERE tenant_id = $1 AND asset_id = $2",
            [tenant, resultado.assetId],
          ),
        /media_assets_armazenado_ck/,
      );
    });
  });

  describe("isolamento (Testes Requeridos: X-03 sobre media_assets)", () => {
    it("com o contexto de A, as midias de B nao aparecem", async () => {
      const metaA = new MetaFalsa();
      const metaB = new MetaFalsa();
      const deA = await medDe(tenantA, metaA).receber(
        pedido(tenantA, conversaA, contactoA),
      );
      await medDe(tenantB, metaB, app2).receber(pedido(tenantB, conversaB, contactoB));

      // **Com o contexto de A ve-se a de A** — e o controlo, e sem ele um zero
      // podia vir de a linha nao existir.
      await definirContexto(app, tenantA);
      const minhas = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.media_assets WHERE asset_id = $1",
        [deA.assetId],
      );
      assert.equal(minhas.rows[0]?.n, "1");

      // E as de B nao.
      const deOutro = await app.query<{ n: string }>(
        "SELECT count(*)::text AS n FROM platform.media_assets WHERE tenant_id = $1",
        [tenantB],
      );
      assert.equal(deOutro.rows[0]?.n, "0", "a politica tenant_iso nao esta a valer");
    });

    it("com o contexto de A, uma escrita na midia de B nao acontece", async () => {
      // Com `FORCE ROW LEVEL SECURITY`, nem como dono da tabela: a politica
      // vale para todos, e e isso que o `FORCE` acrescenta ao `ENABLE`.
      const metaB = new MetaFalsa();
      const deB = await medDe(tenantB, metaB, app2).receber(
        pedido(tenantB, conversaB, contactoB),
      );

      await definirContexto(app, tenantA);
      const escrita = await app.query(
        "UPDATE platform.media_assets SET estado = 'falhou' WHERE asset_id = $1 " +
          "RETURNING asset_id",
        [deB.assetId],
      );
      assert.equal(escrita.rows.length, 0, "escreveu na linha de outro tenant");
    });

    it("**o `urlInterna` de outro tenant nao devolve nada**", async () => {
      // Duas fechaduras, e as duas contam: a RLS nao deixa **ler** a linha, e se
      // deixasse a porta do armazenamento recusaria assinar uma chave fora do
      // tenant do `ctx` (`ChaveForaDoTenantError`). Este teste prova a
      // primeira; a segunda esta na bateria do *gate* 4.
      const metaA = new MetaFalsa();
      const deA = await medDe(tenantA, metaA).receber(
        pedido(tenantA, conversaA, contactoA),
      );
      assert.ok(deA.estado === "armazenado");

      const medDeB = medDe(tenantB, new MetaFalsa(), app2);
      assert.equal(await medDeB.urlInterna(tenantB, deA.assetId), null);
    });
  });

  describe("nenhum URL da Meta chega a base (criterio 3)", () => {
    it("**o canario nao esta em nenhuma coluna de nenhuma linha**", async () => {
      // O criterio pede «um teste que percorre as tabelas». Este percorre a
      // tabela **inteira** do tenant, coluna a coluna, convertida a texto.
      const meta = new MetaFalsa();
      const [tenant, conversa, contacto] = await tenantNovo("media-canario");
      await medDe(tenant, meta).receber(pedido(tenant, conversa, contacto));

      await definirContexto(app, tenant);
      const linhas = await app.query<{ tudo: string }>(
        "SELECT media_assets::text AS tudo FROM platform.media_assets " +
          "WHERE tenant_id = $1",
        [tenant],
      );
      assert.ok(linhas.rows.length > 0, "nada foi gravado: o teste nao prova nada");
      for (const linha of linhas.rows) {
        assert.ok(!linha.tudo.includes("CANARIO"), "o URL da Meta esta na base");
        assert.ok(!linha.tudo.includes("lookaside"), "o dominio da Meta esta na base");
        assert.ok(!linha.tudo.includes("http"), "ha um URL na base");
      }
    });
  });
});

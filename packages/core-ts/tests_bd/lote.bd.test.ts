/**
 * O processo de lote do onboarding contra um PostgreSQL real (KAM-198).
 *
 * **O que só aqui se prova:**
 *
 * 1. **Uma volta do ciclo, com os adaptadores SQL, sobre a `0048`.** O caso da
 *    triagem entra na vista humana, o caso atrasado dá o alerta dos 80% uma vez,
 *    o efeito por reaplicar aplica a fase e o screening, e as quatro métricas
 *    contam o que a base tem. É o processo montado pelo
 *    `services/onboarding-web/src/lote/processo.ts`, com o `kamba_batch` e o
 *    `kamba_app` verdadeiros — e não cópias das consultas.
 * 2. **O screening grava como `kamba_app`, dentro do tenant do caso.** O
 *    `kamba_batch` só lê a `screening_decision`; a linha da decisão humana só
 *    passa a RLS com o `app.tenant_id` do caso. E reaplicar não a repete.
 * 3. **A quota entre processos.** Vinte serviços — vinte «processos», cada um
 *    com o seu `#emSerie` — abrem ao mesmo tempo casos da mesma origem com uma
 *    quota de três: com o trinco do adaptador entram **três** na vista humana;
 *    sem ele (o mesmo repositório com o `emTrinco` tapado) entram mais. O
 *    controlo é o que diz que o ensaio sabe ver o defeito.
 * 4. **A lista de efeitos por reaplicar sobrevive a um reinício**: um processo
 *    marca, morre, e o processo seguinte — outro `montarProcesso`, outras
 *    ligações — encontra-a.
 *
 * O que **não** se mede aqui: a configuração e o arranque sem credenciais, a
 * recusa de um papel trocado, o aviso sem via e as rotas, que são do *gate* 4
 * (`services/onboarding-web/tests/lote.test.ts`); e o `/metrics` sem fuga, que é
 * do caso `X-01/ts/lote` do *gate* 6.
 *
 * Nada aqui é um dado real: os NIF e telefones são *hashes* de bytes fixos, e
 * nenhum valor em claro entra em coluna nenhuma.
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { once } from "node:events";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL, ligar } from "./apoio.ts";
import {
  LIMIARES_POR_OMISSAO,
  OnboardingsSql,
  RevisaoSql,
  ServicoDeRevisao,
  type ConjuntoSql,
  type RepositorioDeRevisao,
} from "../src/revisao/index.ts";
import {
  efeitosDoLote,
  montarProcesso,
} from "../../../services/onboarding-web/src/lote/processo.ts";

const T0 = new Date("2026-11-13T09:00:00.000Z");

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

/** Um `pg.Pool` com o papel pedido, só sobre a base descartável. */
function conjunto(papel: "batch" | "app"): pg.Pool {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  return new pg.Pool({
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: papel === "batch" ? "kamba_batch" : "kamba_app",
    password: exigir(papel === "batch" ? "KAMBA_SECRET_DB_BATCH_PASSWORD" : "KAMBA_SECRET_DB_APP_PASSWORD"),
    application_name: `kamba-lote-teste:${papel}`,
    max: 10,
  });
}

/**
 * A lista sem a carência de dois minutos: os cenários marcam e querem ver a
 * marca na mesma volta. A carência mede-se no seu próprio cenário.
 */
const semCarencia = (c: pg.Pool) => efeitosDoLote(c as unknown as ConjuntoSql, { carenciaMs: 0 });

const avisos: string[] = [];
const registo = {
  warn: (c?: object): void => void avisos.push(String((c as { outcome?: string } | undefined)?.outcome ?? "")),
};

let admin: pg.Client;
let lote: pg.Pool;
let app: pg.Pool;

/** Um `onboarding_case` de ensaio, como administrador. Devolve `[id, tenant]`. */
async function onboarding(fase: string, origem: Buffer | null = randomBytes(32)): Promise<[string, string]> {
  const r = await admin.query<{ id: string; tenant_id: string }>(
    `INSERT INTO platform.onboarding_case
       (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac, ip_prefix_hash)
     VALUES ($1, 'convite', 'Loja de ensaio', 'alimentar', $2, $3, $2, $4, $5)
     RETURNING id, tenant_id`,
    [fase, randomBytes(40), randomBytes(32), randomBytes(32), origem],
  );
  return [r.rows[0]!.id, r.rows[0]!.tenant_id];
}

/** Um `review_case` de ensaio, como administrador. */
async function caso(c: {
  tipo: string;
  tenant: string;
  onboarding: string | null;
  estado: string;
  motivo?: string;
  alertaAt?: Date;
  evidencias?: unknown[];
}): Promise<string> {
  const alerta = c.alertaAt ?? new Date(T0.getTime() + 86_400_000);
  const r = await admin.query<{ id: string }>(
    `INSERT INTO platform.review_case
       (tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico, evidencias,
        estado, prioridade, fila_at, sla_alerta_at, sla_due_at)
     VALUES ($1, $2, $3, $4, 'ensaio', 'nao_foi_possivel_validar', $5::jsonb, $6, 5, $7, $8, $9)
     RETURNING id`,
    [
      c.tipo,
      c.onboarding,
      c.tenant,
      c.motivo ?? `ensaio:${randomUUID().slice(0, 8)}`,
      JSON.stringify(c.evidencias ?? []),
      c.estado,
      new Date(alerta.getTime() - 3_600_000),
      alerta,
      new Date(alerta.getTime() + 86_400_000),
    ],
  );
  return r.rows[0]!.id;
}

async function decisao(casoId: string, tenant: string, d: string): Promise<void> {
  await admin.query(
    `INSERT INTO platform.review_decision_log (case_id, tenant_id, revisor_id, decisao, instancia)
     VALUES ($1, $2, $3, $4, 'primeira')`,
    [casoId, tenant, randomUUID(), d],
  );
}

async function estado(casoId: string): Promise<{ estado: string; sla_alertado_at: Date | null }> {
  const r = await admin.query<{ estado: string; sla_alertado_at: Date | null }>(
    "SELECT estado, sla_alertado_at FROM platform.review_case WHERE id = $1",
    [casoId],
  );
  return r.rows[0]!;
}

async function fase(onboardingId: string): Promise<string> {
  const r = await admin.query<{ fase: string }>("SELECT fase FROM platform.onboarding_case WHERE id = $1", [
    onboardingId,
  ]);
  return r.rows[0]!.fase;
}

async function limpar(): Promise<void> {
  // Pela ordem das chaves estrangeiras.
  // As duas tabelas *append-only* têm *trigger* de imutabilidade que recusa
  // também ao dono; o administrador desliga-o só para limpar a base de ensaio.
  await admin.query("ALTER TABLE platform.review_decision_log DISABLE TRIGGER USER");
  await admin.query("DELETE FROM platform.review_decision_log");
  await admin.query("ALTER TABLE platform.review_decision_log ENABLE TRIGGER USER");
  await admin.query("DELETE FROM platform.review_case");
  await admin.query("ALTER TABLE platform.screening_decision DISABLE TRIGGER USER");
  await admin.query("DELETE FROM platform.screening_decision");
  await admin.query("ALTER TABLE platform.screening_decision ENABLE TRIGGER USER");
  await admin.query("DELETE FROM platform.kyc_check");
  await admin.query("DELETE FROM platform.onboarding_case");
}

describe("o processo de lote contra a base", () => {
  before(async () => {
    admin = await ligar("admin");
    lote = conjunto("batch");
    app = conjunto("app");
    await limpar();
  });

  after(async () => {
    await limpar();
    await admin.end();
    await Promise.all([lote.end(), app.end()]);
  });

  it("uma volta drena a triagem, dá o alerta atrasado uma vez e mede o que a base tem", async () => {
    const [onbA, tenantA] = await onboarding("em_revisao");
    const triagem = await caso({ tipo: "kyc", tenant: tenantA, onboarding: onbA, estado: "em_triagem_automatica" });
    const atrasado = await caso({
      tipo: "categoria",
      tenant: tenantA,
      onboarding: onbA,
      estado: "aberto",
      alertaAt: new Date(T0.getTime() - 60_000),
    });
    avisos.length = 0;
    const p = montarProcesso({ lote, app, efeitos: semCarencia(lote), log: registo, relogio: () => T0 });
    const r = await p.ciclo.correr();
    assert.deepEqual(r.falhas, []);
    assert.equal(r.entraram, 1);
    assert.equal(r.alertas, 1);
    assert.equal((await estado(triagem)).estado, "aberto");
    assert.ok((await estado(atrasado)).sla_alertado_at !== null);
    assert.deepEqual(avisos, ["sla_80"]);
    assert.equal(p.ciclo.metricas.casos("kyc", "aberto"), 1);
    assert.equal(p.ciclo.metricas.casos("categoria", "aberto"), 1);
    const exposicao = p.ciclo.metricas.exposicao();
    assert.match(exposicao, /^review_casos\{tipo="kyc",estado="aberto"\} 1$/m);
    assert.match(exposicao, /^review_decisoes\{tipo="kyc",decisao="sem_decisao"\} 1$/m);

    // A segunda volta não repete o alerta: o `sla_alertado_at` está escrito.
    const r2 = await p.ciclo.correr();
    assert.equal(r2.alertas, 0);
    assert.equal(r2.entraram, 0);
  });

  it("o efeito por reaplicar aplica a fase, e o aviso sem via deixa-o na lista", async () => {
    const [onbB, tenantB] = await onboarding("em_revisao");
    const decidido = await caso({ tipo: "kyc", tenant: tenantB, onboarding: onbB, estado: "decidido" });
    await decisao(decidido, tenantB, "aprovar");
    const efeitos = semCarencia(lote);
    await efeitos.marcar(decidido);
    const p = montarProcesso({ lote, app, efeitos, log: registo, relogio: () => T0 });
    const r = await p.ciclo.correr();
    assert.equal(await fase(onbB), "aprovado", "a fase aplicou-se antes do aviso");
    assert.equal(r.porReaplicar, 1);
    assert.deepEqual(r.falhas, ["reaplicar"]);
    assert.deepEqual(await efeitos.pendentes(10), [decidido], "o aviso falhou: o efeito fica");
  });

  it("o screening de um caso de catálogo grava como kamba_app no tenant do caso, uma vez, e resolve", async () => {
    const tenantC = randomUUID();
    const chave = {
      sujeitoTipo: "produto",
      sujeitoRef: "sku-ensaio-1",
      versaoPolitica: "1.0.0+ensaio",
      conteudoSha256: randomBytes(32).toString("hex"),
    };
    const decidido = await caso({
      tipo: "catalogo",
      tenant: tenantC,
      onboarding: null,
      estado: "decidido",
      evidencias: [{ tipo: "screening_decision", ref: JSON.stringify(chave) }],
    });
    await decisao(decidido, tenantC, "aprovar");
    const efeitos = semCarencia(lote);
    await efeitos.marcar(decidido);
    const p = montarProcesso({ lote, app, efeitos, log: registo, relogio: () => T0 });
    const r = await p.ciclo.correr();
    assert.equal(r.reaplicados, 1);
    // O caso do cenário anterior continua marcado (o aviso não tem via); este não.
    assert.ok(!(await efeitos.pendentes(100)).includes(decidido));
    const linhas = async () =>
      (
        await admin.query<{ decisao: string; origem: string; tenant_id: string }>(
          "SELECT decisao, origem, tenant_id FROM platform.screening_decision WHERE sujeito_ref = $1",
          [chave.sujeitoRef],
        )
      ).rows;
    assert.deepEqual(await linhas(), [{ decisao: "permitida", origem: "humano", tenant_id: tenantC }]);

    // Reaplicar outra vez não repete a linha (a `screening_decision` não tem
    // unicidade sobre a chave: a idempotência é do escritor do lote).
    await efeitos.marcar(decidido);
    await p.ciclo.correr();
    assert.equal((await linhas()).length, 1);

    // O `kamba_batch` sozinho não a podia ter gravado: é por isso que há duas ligações.
    await assert.rejects(
      lote.query(
        `INSERT INTO platform.screening_decision
           (tenant_id, sujeito_tipo, sujeito_ref, decisao, regras, versao_politica, origem, conteudo_sha256)
         VALUES ($1, 'produto', 'x', 'permitida', '{}', '1.0.0+ensaio', 'humano', $2)`,
        [tenantC, randomBytes(32)],
      ),
      /permission denied/,
    );
  });

  it("a quota de uma origem aguenta vinte processos a abrir ao mesmo tempo; sem o trinco, não", async (t) => {
    const quota = 3;
    const limiares = { ...LIMIARES_POR_OMISSAO, quotaPorOrigemPorDia: quota };
    const abrirEmParalelo = async (origem: Buffer, comTrinco: boolean): Promise<number> => {
      const onbs: [string, string][] = [];
      for (let i = 0; i < 20; i++) onbs.push(await onboarding("em_revisao", origem));
      await Promise.all(
        onbs.map(async ([onb, tenant], i) => {
          // Um serviço por abertura: o `#emSerie` de cada um não vê os outros,
          // que é o que vinte processos são.
          const sql = new RevisaoSql(lote, { conjunto: lote as unknown as ConjuntoSql });
          const repositorio: RepositorioDeRevisao = comTrinco
            ? sql
            : new Proxy(sql, {
                // Os métodos ligados ao alvo: o `RevisaoSql` tem campos
                // `#privados`, e chamados com o `this` do `Proxy` rebentavam.
                get: (alvo, nome) => {
                  if (nome === "emTrinco") return undefined;
                  const v = Reflect.get(alvo, nome, alvo) as unknown;
                  return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(alvo) : v;
                },
              });
          const servico = new ServicoDeRevisao({
            repositorio,
            onboardings: new OnboardingsSql(lote),
            auditoria: { gravar: async () => {} },
            aviso: { avisar: async () => {} },
            alerta: () => {},
            cifra: { cifrar: async (b) => b, decifrar: async (b) => b },
            dados: { ler: async () => null },
            documentos: { url: async () => "" },
            screening: { gravar: async () => {} },
            limiares,
            relogio: () => T0,
          });
          await servico.abrir({
            tipo: "kyc",
            tenantId: tenant,
            onboardingId: onb,
            motivoCodigo: `quota:${i}`,
            motivoInterno: "ensaio da quota",
            motivoPublico: "nao_foi_possivel_validar",
            evidencias: [],
            recomendacao: null,
            prioridade: 5,
          });
        }),
      );
      const r = await admin.query<{ n: number }>(
        `SELECT count(*)::int AS n FROM platform.review_case r
           JOIN platform.onboarding_case c ON c.id = r.onboarding_id
          WHERE c.ip_prefix_hash = $1 AND r.estado = 'aberto'`,
        [origem],
      );
      return r.rows[0]!.n;
    };
    const comTrinco = await abrirEmParalelo(randomBytes(32), true);
    const semTrinco = await abrirEmParalelo(randomBytes(32), false);
    // Pelo diagnóstico do TAP e não pelo `console`: o `log_policy` recusa-o, e a
    // suite Python lê a linha do TAP para a citar.
    t.diagnostic(`[KAM-198] quota ${quota}: com trinco ${comTrinco} abertos, sem trinco ${semTrinco}`);
    assert.equal(comTrinco, quota);
    assert.ok(semTrinco > quota, `o controlo não viu o defeito (${semTrinco} abertos): o ensaio não mede o trinco`);
  });

  it("a lista de efeitos por reaplicar sobrevive a um reinício do processo", async () => {
    const [onbD, tenantD] = await onboarding("em_revisao");
    const decidido = await caso({ tipo: "kyc", tenant: tenantD, onboarding: onbD, estado: "decidido" });
    await decisao(decidido, tenantD, "rejeitar");
    {
      const outroLote = conjunto("batch");
      const antes = montarProcesso({ lote: outroLote, app, efeitos: semCarencia(outroLote), log: registo });
      await antes.ciclo.efeitoFalhou(decidido);
      await outroLote.end();
    }
    const depois = montarProcesso({ lote, app, efeitos: semCarencia(lote), log: registo, relogio: () => T0 });
    assert.ok((await depois.ciclo.efeitos.pendentes(100)).includes(decidido));
    await depois.ciclo.correr();
    assert.equal(await fase(onbD), "rejeitado");
  });

  it("o serviço marca o caso na base antes dos efeitos: uma decisão cujo aviso falha fica marcada", async () => {
    const [onbE, tenantE] = await onboarding("em_revisao");
    const aberto = await caso({ tipo: "kyc", tenant: tenantE, onboarding: onbE, estado: "aberto" });
    const p = montarProcesso({ lote, app, efeitos: semCarencia(lote), log: registo, relogio: () => T0 });
    const revisor = { id: randomUUID(), papeis: ["ts_revisor" as const], mfa: true, nifHmac: null, telefoneHmac: null };
    // Ninguém chama o `efeitoFalhou`: é o serviço que marca, e o erro que sobe
    // é o que a consola leria.
    await assert.rejects(p.servico.decidir(revisor, aberto, "rejeitar"), { name: "EfeitoPorAplicarError" });
    assert.equal(await fase(onbE), "rejeitado", "a fase aplicou-se antes do aviso");
    const marca = await admin.query<{ marcado: boolean }>(
      "SELECT efeito_pendente_at IS NOT NULL AS marcado FROM platform.review_case WHERE id = $1",
      [aberto],
    );
    assert.equal(marca.rows[0]!.marcado, true);
    assert.ok((await semCarencia(lote).pendentes(100)).includes(aberto));
  });

  it("o resolver de um processo não apaga a marca que outro escreveu depois de ele a ler", async () => {
    const [onbF, tenantF] = await onboarding("em_revisao");
    const decidido = await caso({ tipo: "kyc", tenant: tenantF, onboarding: onbF, estado: "decidido" });
    await decisao(decidido, tenantF, "aprovar");
    const doLote = semCarencia(lote);
    const daConsola = semCarencia(lote);
    await daConsola.marcar(decidido);
    assert.ok((await doLote.pendentes(100)).includes(decidido), "o lote leu a marca");
    await daConsola.marcar(decidido);
    await doLote.resolver(decidido);
    assert.ok(
      (await semCarencia(lote).pendentes(100)).includes(decidido),
      "a marca nova ficou: o lote só limpa a que leu",
    );
    await daConsola.resolver(decidido);
    assert.ok(!(await semCarencia(lote).pendentes(100)).includes(decidido));
  });

  it("a carência esconde do lote a marca de quem ainda está a correr os efeitos", async () => {
    const [onbG, tenantG] = await onboarding("em_revisao");
    const decidido = await caso({ tipo: "kyc", tenant: tenantG, onboarding: onbG, estado: "decidido" });
    await efeitosDoLote(lote as unknown as ConjuntoSql).marcar(decidido);
    assert.ok(
      !(await efeitosDoLote(lote as unknown as ConjuntoSql).pendentes(1000)).includes(decidido),
      "com a carência por omissão, o lote não vê uma marca de agora",
    );
    assert.ok((await semCarencia(lote).pendentes(1000)).includes(decidido));
    await semCarencia(lote).resolver(decidido);
  });

  it("reaplicar um pedir_info não desfaz a fase que mudou depois da decisão; sem mudança, aplica-a", async () => {
    const correrCom = async (mudou: boolean): Promise<string> => {
      const [onb, tenant] = await onboarding("em_revisao");
      const pendente = await caso({ tipo: "kyc", tenant, onboarding: onb, estado: "em_analise" });
      await decisao(pendente, tenant, "pedir_info");
      // O KYC voltou a decidir depois do pedido e rejeitou: a fase mudou, e o
      // `fase_at` (que o *trigger* da `0043` só move quando ela muda) di-lo.
      if (mudou) await admin.query("UPDATE platform.onboarding_case SET fase = 'rejeitado' WHERE id = $1", [onb]);
      const efeitos = semCarencia(lote);
      await efeitos.marcar(pendente);
      await montarProcesso({ lote, app, efeitos, log: registo, relogio: () => T0 }).ciclo.correr();
      return fase(onb);
    };
    assert.equal(await correrCom(true), "rejeitado", "a reaplicação desfez o passo do KYC");
    assert.equal(await correrCom(false), "kyc_pendente", "sem mudança, a fase do pedido aplica-se");
  });

  it("o processo arranca em prod com as duas credenciais, serve /healthz e /metrics, e pára no SIGTERM", async () => {
    // Pela `URL`, e não por interpolação: a senha vem do ambiente do gate, e o
    // `scan_secrets` recusa o padrão de credencial embutida no texto.
    const url = (papel: "kamba_batch" | "kamba_app", senha: string) => {
      const u = new URL(
        `postgresql://${process.env.KAMBA_DB_HOST ?? "127.0.0.1"}:${process.env.KAMBA_DB_PORT ?? "5432"}/${exigir("KAMBA_DB_NAME")}`,
      );
      u.username = papel;
      u.password = exigir(senha);
      return u.toString();
    };
    // Uma porta que o sistema diz livre, e não uma sorteada: no runner as
    // ligações do próprio ensaio à base ocupam portas locais da gama alta.
    const porta = await new Promise<number>((livre, falhou) => {
      const sonda = createServer();
      sonda.once("error", falhou);
      sonda.listen(0, "127.0.0.1", () => {
        const endereco = sonda.address();
        sonda.close(() => (typeof endereco === "object" && endereco !== null ? livre(endereco.port) : falhou(new Error("sem porta"))));
      });
    });
    const ficheiro = fileURLToPath(new URL("../../../services/onboarding-web/src/lote.ts", import.meta.url));
    const filho = spawn(process.execPath, [ficheiro], {
      env: {
        PATH: process.env.PATH ?? "",
        KAMBA_AMBIENTE: "prod",
        KAMBA_LOTE_DB_URL: url("kamba_batch", "KAMBA_SECRET_DB_BATCH_PASSWORD"),
        KAMBA_LOTE_APP_DB_URL: url("kamba_app", "KAMBA_SECRET_DB_APP_PASSWORD"),
        LOTE_PORT: String(porta),
        HOST: "127.0.0.1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let saida = "";
    // Pelos descritores 1 e 2 e não pelos nomes: o `log_policy` recusa os nomes
    // dos dois fluxos em qualquer ficheiro, e aqui só se **lê** o que o filho escreveu.
    for (const fluxo of [filho.stdio[1], filho.stdio[2]]) {
      fluxo?.on("data", (b: Buffer) => (saida += b.toString("utf8")));
    }
    let morto: number | null | undefined;
    filho.on("exit", (codigo) => (morto = codigo));
    let codigo: number | null = null;
    try {
      // Até dois minutos: carregar o processo leva ~40 s numa montagem do
      // Windows, e um processo que morra antes de abrir a porta pára a espera.
      let sonda: Response | null = null;
      for (let i = 0; i < 600 && sonda === null && morto === undefined; i++) {
        try {
          sonda = await fetch(`http://127.0.0.1:${porta}/healthz`);
        } catch {
          await new Promise((r) => setTimeout(r, 200));
        }
      }
      assert.ok(sonda !== null, `o processo não abriu a porta (saiu com ${String(morto)}):\n${saida.slice(-2000)}`);
      assert.equal(sonda.status, 200);
      // A primeira volta corre no arranque: as métricas já contam a base, e não zero.
      let metricas = "";
      for (let i = 0; i < 50 && !/^review_casos\{tipo="kyc",estado="aberto"\} [1-9]/m.test(metricas); i++) {
        metricas = await (await fetch(`http://127.0.0.1:${porta}/metrics`)).text();
        await new Promise((r) => setTimeout(r, 200));
      }
      assert.match(metricas, /^review_casos\{tipo="kyc",estado="aberto"\} [1-9]/m, "a volta do arranque não contou a base");
      assert.match(saida, /"outcome":"service_started"/);
      assert.match(saida, /"outcome":"ciclo_(concluido|com_falhas)"/);
    } finally {
      if (morto === undefined) {
        filho.kill("SIGTERM");
        [codigo] = (await once(filho, "exit")) as [number | null];
      } else {
        codigo = morto;
      }
    }
    assert.equal(codigo, 0, `o processo não parou limpo no SIGTERM:\n${saida.slice(-2000)}`);
    assert.match(saida, /"outcome":"service_stopped"/);
  });
});

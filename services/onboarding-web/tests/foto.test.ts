/**
 * A foto do dono pelo painel (KAM-243), pela superfície HTTP.
 *
 * Reais: a rota, a `FotoDoDono`, a `recepcaoDoPainel` e o MED do KAM-020 por
 * dentro dela, e o STO falso do KAM-011 (`criarStorageFake`, com o prefixo do
 * tenant). Falsos: a base da `media_assets` — um *pool* cujas ligações respondem
 * às instruções do MED com o tenant do `set_config`, como a RLS `FORCE` — e o
 * AGR, que regista as invocações. A semântica contra o PostgreSQL está em
 * `packages/core-ts/tests_bd/media.bd.test.ts` («KAM-243»).
 *
 * O que aqui se prova: a foto grava-se numa linha `armazenado` do tenant da
 * sessão e o AGR recebe o `asset_id` com o `type` `image`; a mesma foto duas
 * vezes é uma linha e o mesmo turno; o que não é imagem e o que passa do tecto
 * não reservam linha; e o tenant é o da sessão, nunca o do pedido.
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  BYTES_MAXIMOS_DA_FOTO,
  FotoDoDono,
  recepcaoDoPainel,
  type ContextoDoDono,
  type PoolDeIdentidade,
} from "@kamba/core-ts/dono";
import type { AgentInvocation } from "@kamba/core-ts/chr";
import {
  SQL_MARCAR_ARMAZENADO,
  SQL_MARCAR_DESFECHO,
  SQL_POR_ASSET,
  SQL_POR_ORIGEM,
  SQL_RESERVAR,
} from "@kamba/core-ts/med";
import { criarStorageFake } from "@kamba/core-ts/storage";

import { CanalEmMemoria } from "../src/painel/canal.ts";
import { ComercioEmMemoria } from "../src/painel/comercio.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { rotasDoPainel } from "../src/painel/rotas.ts";
import { RevogacoesEmMemoria, cunharSessao, novaSessao } from "../src/painel/sessao.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CASO_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const CHAVE = new Uint8Array(32).fill(7);
const INICIO = new Date("2026-11-19T09:00:00.000Z");

function contexto(tenant: string): ContextoDoDono {
  const t = tenant.slice(0, 8);
  return {
    contactId: `${t}-0000-4000-8000-0000000000c1`,
    conversationId: `${t}-0000-4000-8000-0000000000d1`,
    channelId: `${t}-0000-4000-8000-0000000000e1`,
    vertical: "vendedor",
    modo: "bot",
  };
}

/** Uns bytes com a assinatura de um JPEG: sintéticos, não são uma fotografia. */
function jpeg(semente = 1, tamanho = 256): Uint8Array {
  const bytes = new Uint8Array(tamanho).fill(semente);
  bytes.set([0xff, 0xd8, 0xff, 0xe0]);
  return bytes;
}

interface Linha {
  asset_id: string;
  tenant_id: string;
  wamid: string;
  media_id: string;
  classe: string;
  estado: string;
  storage_ref: string | null;
  sha256: string | null;
}

/**
 * A `media_assets` de vários tenants. **O tenant que conta é o do `set_config`**
 * da transacção, como a RLS `FORCE`; o `tenant_id = $1` do predicado tem de
 * coincidir com ele. Uma instrução fora de transacção vê zero linhas.
 */
class BaseDeMedia {
  linhas: Linha[] = [];
  seq = 0;

  ligacao() {
    let contextoDoTenant: string | null = null;
    const base = this;
    return {
      release: () => undefined,
      async query(sql: string, p: readonly unknown[] = []) {
        if (sql === "BEGIN" || sql === "COMMIT" || sql === "ROLLBACK") {
          if (sql !== "BEGIN") contextoDoTenant = null;
          return { rows: [] };
        }
        if (sql.includes("set_config")) {
          contextoDoTenant = String(p[0]);
          return { rows: [{ set_config: contextoDoTenant }] };
        }
        const visiveis = base.linhas.filter((l) => l.tenant_id === contextoDoTenant && l.tenant_id === p[0]);
        if (sql === SQL_RESERVAR) {
          if (contextoDoTenant !== p[0]) throw new Error("RLS: o INSERT de outro tenant e recusado");
          if (base.linhas.some((l) => l.tenant_id === p[0] && l.wamid === p[3] && l.media_id === p[4])) return { rows: [] };
          base.seq += 1;
          const linha: Linha = {
            asset_id: `${String(p[0]).slice(0, 8)}-5555-4555-8555-${String(base.seq).padStart(12, "0")}`,
            tenant_id: String(p[0]),
            wamid: String(p[3]),
            media_id: String(p[4]),
            classe: String(p[5]),
            estado: "pendente",
            storage_ref: null,
            sha256: null,
          };
          base.linhas.push(linha);
          return { rows: [{ asset_id: linha.asset_id }] };
        }
        if (sql === SQL_POR_ORIGEM) return { rows: visiveis.filter((l) => l.wamid === p[1] && l.media_id === p[2]) };
        if (sql === SQL_POR_ASSET) return { rows: visiveis.filter((l) => l.asset_id === p[1]) };
        if (sql === SQL_MARCAR_ARMAZENADO || sql === SQL_MARCAR_DESFECHO) {
          const linha = visiveis.find((l) => l.asset_id === p[1] && l.estado === "pendente");
          if (linha === undefined) return { rows: [] };
          if (sql === SQL_MARCAR_ARMAZENADO) {
            linha.estado = "armazenado";
            linha.sha256 = String(p[4]);
            linha.storage_ref = String(p[5]);
          } else {
            linha.estado = String(p[2]);
          }
          return { rows: [{ asset_id: linha.asset_id, estado: linha.estado }] };
        }
        throw new Error(`instrucao inesperada: ${sql.trim().slice(0, 40)}`);
      },
    };
  }

  pool(): PoolDeIdentidade {
    return { connect: async () => this.ligacao() };
  }
}

interface Montagem {
  app: ReturnType<typeof rotasDoPainel>;
  metricas: MetricasDoPainel;
  base: BaseDeMedia;
  objectos: () => number;
  invocacoes: AgentInvocation[];
  contextos: string[];
  estadoDoAgr: number;
}

function montar(sobre: { semFoto?: boolean } = {}): Montagem {
  const base = new BaseDeMedia();
  const sto = criarStorageFake();
  const m = { base, objectos: sto.total, invocacoes: [], contextos: [], estadoDoAgr: 200 } as unknown as Montagem;
  const foto = new FotoDoDono({
    contexto: async (tenantId) => {
      m.contextos.push(tenantId);
      return contexto(tenantId);
    },
    receber: recepcaoDoPainel({ pool: base.pool(), armazenamento: sto.storage }),
    invocar: async (invocacao) => {
      m.invocacoes.push(invocacao);
      return { estado: m.estadoDoAgr, desfecho: m.estadoDoAgr === 200 ? "executado" : "desconhecido" };
    },
  });
  m.metricas = new MetricasDoPainel();
  const casos = new Map([
    [CASO_A, { tenantId: TENANT_A, fase: "activo" }],
    [CASO_B, { tenantId: TENANT_B, fase: "activo" }],
  ]);
  m.app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: new CanalEmMemoria(),
    revogacoes: new RevogacoesEmMemoria(),
    metricas: m.metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio: () => INICIO,
    ...(sobre.semFoto === true ? {} : { foto: { foto } }),
  });
  return m;
}

function cookie(tenant: string, caso: string): string {
  return `kamba_painel=${cunharSessao(novaSessao(tenant, caso, INICIO), CHAVE)}`;
}

function enviar(
  m: Montagem,
  corpo: Uint8Array | string,
  sessao?: string,
  tipo = "image/jpeg",
  caminho = "/painel/foto",
  extra: Record<string, string> = {},
) {
  return m.app.request(caminho, {
    method: "POST",
    headers: { "content-type": tipo, ...(sessao === undefined ? {} : { cookie: sessao }), ...extra },
    body: corpo,
  });
}

describe("KAM-243 — a foto do dono pelo painel", () => {
  it("grava a foto numa linha armazenado do tenant da sessao e invoca o AGR com o asset_id", async () => {
    const m = montar();
    const r = await enviar(m, jpeg(), cookie(TENANT_A, CASO_A));
    assert.equal(r.status, 200);
    const corpo = (await r.json()) as { ok: boolean; asset: string; repetida: boolean };
    assert.equal(corpo.repetida, false);
    const [linha] = m.base.linhas;
    assert.equal(m.base.linhas.length, 1);
    assert.equal(linha?.tenant_id, TENANT_A);
    assert.equal(linha?.estado, "armazenado");
    assert.equal(linha?.classe, "media_imagem");
    assert.match(String(linha?.media_id), /^painel\.[0-9a-f-]{36}$/);
    assert.ok(String(linha?.storage_ref).startsWith(`t/${TENANT_A}/media_imagem/`));
    assert.equal(m.objectos(), 1);
    const [inv] = m.invocacoes;
    assert.equal(inv?.asset_id, corpo.asset);
    assert.equal(inv?.asset_id, linha?.asset_id);
    assert.equal(inv?.type, "image");
    assert.equal(inv?.persona, "dono");
    assert.equal(inv?.wamid, `painel.${corpo.asset}`);
    assert.equal(inv?.message_id, undefined);
    assert.equal(inv?.tenant_id, TENANT_A);
    assert.equal(m.metricas.valor("foto"), 1);
  });

  it("a mesma foto duas vezes e uma linha, um objecto e o mesmo turno", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    const primeira = (await (await enviar(m, jpeg(), deA)).json()) as { asset: string };
    const segunda = (await (await enviar(m, jpeg(), deA)).json()) as { asset: string; repetida: boolean };
    assert.equal(segunda.asset, primeira.asset);
    assert.equal(segunda.repetida, true);
    assert.equal(m.base.linhas.length, 1);
    assert.equal(m.objectos(), 1);
    assert.equal(m.invocacoes.length, 2);
    assert.equal(m.invocacoes[0]?.wamid, m.invocacoes[1]?.wamid);
    // Outra foto e outra linha.
    await enviar(m, jpeg(2), deA);
    assert.equal(m.base.linhas.length, 2);
  });

  it("o tenant e o da sessao: um tenant_id na consulta ou num cabecalho nao e lido", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    await enviar(m, jpeg(), deA, "image/jpeg", `/painel/foto?tenant_id=${TENANT_B}`);
    await enviar(m, jpeg(3), deA, "image/jpeg", "/painel/foto", { "x-kamba-tenant": TENANT_B, "x-tenant-id": TENANT_B });
    assert.deepEqual(m.contextos, [TENANT_A, TENANT_A]);
    assert.ok(m.base.linhas.every((l) => l.tenant_id === TENANT_A));
    assert.ok(m.invocacoes.every((i) => i.tenant_id === TENANT_A && i.thread_id.startsWith(`${TENANT_A}:`)));
  });

  it("a mesma foto em dois tenants sao duas linhas, cada uma no seu tenant e prefixo", async () => {
    const m = montar();
    await enviar(m, jpeg(), cookie(TENANT_A, CASO_A));
    await enviar(m, jpeg(), cookie(TENANT_B, CASO_B));
    assert.equal(m.base.linhas.length, 2);
    const [a, b] = m.base.linhas;
    assert.notEqual(a?.media_id, b?.media_id);
    assert.ok(String(b?.storage_ref).startsWith(`t/${TENANT_B}/`));
    assert.notEqual(m.invocacoes[0]?.asset_id, m.invocacoes[1]?.asset_id);
  });

  it("o que nao e imagem: 415, sem linha, sem objecto e sem AGR", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    // O cabecalho diz JPEG e os bytes nao sao: vale a assinatura.
    const falsa = await enviar(m, new TextEncoder().encode("%PDF-1.7 isto nao e uma foto"), deA);
    assert.equal(falsa.status, 415);
    // Um tipo fora dos dois: o `<form>` de outra origem cai aqui.
    for (const tipo of ["text/plain", "multipart/form-data; boundary=x", "application/x-www-form-urlencoded", "image/webp", ""]) {
      const r = await enviar(m, jpeg(), deA, tipo);
      assert.equal(r.status, 415, tipo);
    }
    assert.equal(m.base.linhas.length, 0);
    assert.equal(m.objectos(), 0);
    assert.equal(m.invocacoes.length, 0);
    assert.equal(m.metricas.valor("foto", "invalido"), 6);
  });

  it("acima do tecto do MED: 413, sem linha; no tecto passa", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    const grande = await enviar(m, jpeg(1, BYTES_MAXIMOS_DA_FOTO + 1), deA);
    assert.equal(grande.status, 413);
    assert.equal(m.base.linhas.length, 0);
    assert.equal(m.invocacoes.length, 0);
    const noTecto = await enviar(m, jpeg(1, BYTES_MAXIMOS_DA_FOTO), deA);
    assert.equal(noTecto.status, 200);
  });

  it("um corpo em fluxo, sem content-length, acima do tecto tambem para", async () => {
    const m = montar();
    const pedaco = jpeg(1, 1024 * 1024);
    let enviados = 0;
    const fluxo = new ReadableStream<Uint8Array>({
      pull(controlador) {
        enviados += 1;
        if (enviados > 64) controlador.close();
        else controlador.enqueue(pedaco);
      },
    });
    const r = await m.app.request("/painel/foto", {
      method: "POST",
      headers: { "content-type": "image/jpeg", cookie: cookie(TENANT_A, CASO_A) },
      body: fluxo,
      duplex: "half",
    } as RequestInit);
    assert.equal(r.status, 413);
    assert.ok(enviados < 64, `a leitura parou no tecto, e nao ao fim de ${enviados} pedacos`);
    assert.equal(m.base.linhas.length, 0);
  });

  it("sem sessao e 401, e sem a foto montada e 503", async () => {
    const m = montar();
    assert.equal((await enviar(m, jpeg())).status, 401);
    const sem = montar({ semFoto: true });
    assert.equal((await enviar(sem, jpeg(), cookie(TENANT_A, CASO_A))).status, 503);
    assert.equal(m.base.linhas.length, 0);
  });

  it("o AGR em baixo: 502, e a foto fica guardada para o dono repetir", async () => {
    const m = montar();
    m.estadoDoAgr = 503;
    const deA = cookie(TENANT_A, CASO_A);
    const r = await enviar(m, jpeg(), deA);
    assert.equal(r.status, 502);
    const { asset } = (await r.json()) as { asset: string };
    assert.equal(m.base.linhas[0]?.asset_id, asset);
    m.estadoDoAgr = 200;
    const outra = await enviar(m, jpeg(), deA);
    assert.equal(outra.status, 200);
    assert.equal(m.base.linhas.length, 1);
  });
});

// ------------------------------------------------------------------ o arranque
//
// Criterio 3: em `staging` o processo nao arranca sem as chaves do STO nem sem a
// configuracao dele. Os segredos da inscricao sao gerados aqui, a cada corrida,
// e nao servem para nada fora deste ensaio.

function ambienteDeStaging(mais: Record<string, string>): Record<string, string> {
  const chave = (): string => randomBytes(32).toString("base64");
  return {
    PATH: process.env.PATH ?? "",
    KAMBA_AMBIENTE: "staging",
    PORT: "3998",
    KAMBA_SECRET_PEPPER_ONBOARDING_IDENT: chave(),
    KAMBA_SECRET_SEGREDO_ONBOARDING_ASSINATURA: chave(),
    KAMBA_SECRET_PEPPER_SMS_DESTINO: chave(),
    ...mais,
  };
}

function arrancar(env: Record<string, string>) {
  const ficheiro = fileURLToPath(new URL("../src/server.ts", import.meta.url));
  // Dois minutos, pela razao do ensaio de arranque do `lote.test.ts`.
  return spawnSync(process.execPath, [ficheiro], { env, encoding: "utf8", timeout: 120_000 });
}

describe("KAM-243 — o STO no arranque do onboarding-web", () => {
  it("em staging, sem as chaves do STO, sai com erro e nao abre a porta", () => {
    const r = arrancar(
      ambienteDeStaging({
        KAMBA_STORAGE_ENDPOINT: "http://sto.invalido:8333",
        KAMBA_STORAGE_BUCKET: "kamba-ensaio",
        KAMBA_STORAGE_REGION: "ao-luanda-1",
        KAMBA_STORAGE_DESTINO_COUNTRY: "AO",
        KAMBA_STORAGE_DESTINO_PROVIDER: "seaweedfs",
      }),
    );
    assert.notEqual(r.status, 0, r.stderr);
    const saida = `${r.stdout}${r.stderr}`;
    assert.match(saida, /ArranqueAbortadoError/);
    assert.doesNotMatch(saida, /service_started/);
  });

  it("em staging, com as chaves e sem a configuracao do STO, sai com erro e nao abre a porta", () => {
    const r = arrancar(
      ambienteDeStaging({
        KAMBA_SECRET_STORAGE_ACCESS_KEY_ID: "chave de ensaio que nao serve",
        KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY: "segredo de ensaio que nao serve",
      }),
    );
    assert.notEqual(r.status, 0, r.stderr);
    const saida = `${r.stdout}${r.stderr}`;
    assert.match(saida, /ArranqueAbortadoError/);
    assert.doesNotMatch(saida, /service_started/);
  });
});

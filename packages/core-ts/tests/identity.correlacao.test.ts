/**
 * O pseudónimo do telefone sem tenant e o interruptor que o liga (KAM-208).
 *
 * Sem base de dados: o interruptor e a sua tranca em `prod`, a forma do
 * pseudónimo, a chave lida do cofre, e o que a resolução de identidade manda à
 * base com o interruptor ligado e desligado. O que só a base prova — a tabela,
 * a RLS, os privilégios, a função do lote e o anel — está em
 * `../../../db/tests/test_correlacao_entre_tenants.py`.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import { EnvKeyProvider, gerarChaveVersionada, lerVersionada } from "../src/identity/chaves.ts";
import * as SQL from "../src/identity/consultas.ts";
import { type ClienteDeIdentidade, Identidade, type ResultadoSql } from "../src/identity/contactos.ts";
import {
  ChaveDeCorrelacaoEmFaltaError,
  CorrelacaoDoCofre,
  DIAS_DE_RETENCAO_DO_PSEUDONIMO,
  DOMINIO_DA_CORRELACAO,
  type FonteDaCorrelacao,
  REF_CHAVE_DE_CORRELACAO,
  VARIAVEL_DA_CORRELACAO,
  correlacaoDoAmbiente,
  estadoDaCorrelacao,
  exigirChaveDeCorrelacao,
  pseudonimoSemTenant,
} from "../src/identity/correlacao.ts";
import { hmacDePesquisa } from "../src/identity/cripto.ts";
import { EnvSecretProvider, nomeDaVariavel } from "../src/secrets/index.ts";
import { ambienteDeChaves } from "./identity.ambiente.ts";

const TENANT_A = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";
const TENANT_B = "1c7f2e3f-4d5b-4c6d-9e7f-8091a2b3c4d5";
const CONTACTO = "2d8b3f40-5e6c-4d7e-af80-9b0c1d2e3f40";
const AGORA = new Date("2026-11-21T10:00:00Z");
/** Fictício: o 999 não é atribuído pela UIT. */
const TELEFONE = "244999000208";

const CHAVE_X = gerarChaveVersionada("x1");

// ----------------------------------------------------------- o interruptor (D1)

test("o interruptor liga só com «ligada», e em prod está trancado seja qual for a variável", () => {
  assert.equal(estadoDaCorrelacao("dev", undefined), "desligada");
  assert.equal(estadoDaCorrelacao("dev", ""), "desligada");
  assert.equal(estadoDaCorrelacao("dev", "sim"), "desligada");
  assert.equal(estadoDaCorrelacao("dev", "Ligada"), "desligada", "a caixa conta: só o valor exacto liga");
  assert.equal(estadoDaCorrelacao("dev", " ligada "), "ligada");
  assert.equal(estadoDaCorrelacao("staging", "ligada"), "ligada");
  assert.equal(estadoDaCorrelacao("prod", "ligada"), "trancada");
  assert.equal(estadoDaCorrelacao("prod", undefined), "desligada");
});

test("lido do ambiente do processo, sem KAMBA_ENV válido não liga", () => {
  assert.equal(correlacaoDoAmbiente({ [VARIAVEL_DA_CORRELACAO]: "ligada" }), "desligada");
  assert.equal(correlacaoDoAmbiente({ KAMBA_ENV: "producao", [VARIAVEL_DA_CORRELACAO]: "ligada" }), "desligada");
  assert.equal(correlacaoDoAmbiente({ KAMBA_ENV: "prod", [VARIAVEL_DA_CORRELACAO]: "ligada" }), "trancada");
  assert.equal(correlacaoDoAmbiente({ KAMBA_ENV: "staging", [VARIAVEL_DA_CORRELACAO]: "ligada" }), "ligada");
});

// ----------------------------------------------------------- o pseudónimo (D3)

test("o pseudónimo não leva tenant: o mesmo número dá o mesmo nome em todos, ao contrário do phone_hmac", () => {
  const { chave } = lerVersionada(REF_CHAVE_DE_CORRELACAO, CHAVE_X);
  const p = pseudonimoSemTenant(chave, TELEFONE);
  assert.equal(p.length, 32);
  assert.deepEqual(pseudonimoSemTenant(chave, TELEFONE), p, "determinístico");
  // O phone_hmac do mesmo número, com a mesma chave, difere entre tenants e do pseudónimo.
  const a = hmacDePesquisa(chave, TENANT_A, "telefone", TELEFONE);
  const b = hmacDePesquisa(chave, TENANT_B, "telefone", TELEFONE);
  assert.notDeepEqual(a, b);
  assert.notDeepEqual(p, a);
  assert.notDeepEqual(p, b);
  // A forma exacta: o domínio, o tipo e o número, separados por nulos.
  const esperado = createHmac("sha256", chave).update(`${DOMINIO_DA_CORRELACAO}\0telefone\0${TELEFONE}`).digest();
  assert.deepEqual(p, esperado);
  assert.equal(DOMINIO_DA_CORRELACAO, "kamba.identity.xtenant.v1");
});

test("outra chave, outro pseudónimo; outro número, outro pseudónimo", () => {
  const k1 = lerVersionada(REF_CHAVE_DE_CORRELACAO, CHAVE_X).chave;
  const k2 = lerVersionada(REF_CHAVE_DE_CORRELACAO, gerarChaveVersionada("x2")).chave;
  assert.notDeepEqual(pseudonimoSemTenant(k1, TELEFONE), pseudonimoSemTenant(k2, TELEFONE));
  assert.notDeepEqual(pseudonimoSemTenant(k1, TELEFONE), pseudonimoSemTenant(k1, "244999000209"));
});

test("recusa chave sem 32 octetos e telefone por normalizar, sem pôr o número na mensagem", () => {
  const k = lerVersionada(REF_CHAVE_DE_CORRELACAO, CHAVE_X).chave;
  assert.throws(() => pseudonimoSemTenant(new Uint8Array(16), TELEFONE), /32 octetos/);
  for (const mau of ["+244999000208", "244 999 000 208", "0999000208", ""]) {
    assert.throws(
      () => pseudonimoSemTenant(k, mau),
      (erro: unknown) => erro instanceof TypeError && (mau === "" || !erro.message.includes(mau)),
    );
  }
});

test("a chave vem do anel do cofre, a actual, e ligada sem chave recusa o arranque", async () => {
  const env = { [nomeDaVariavel("pepper_contact_xtenant")]: CHAVE_X };
  const fonte = new CorrelacaoDoCofre(new EnvSecretProvider({ ambiente: "dev", env }));
  const { kid, chave } = await fonte.chaveActual();
  assert.equal(kid, "x1");
  assert.equal(chave.length, 32);
  await exigirChaveDeCorrelacao(fonte);

  const vazia = new CorrelacaoDoCofre(new EnvSecretProvider({ ambiente: "dev", env: {} }));
  await assert.rejects(exigirChaveDeCorrelacao(vazia), ChaveDeCorrelacaoEmFaltaError);
  const malFormada = new CorrelacaoDoCofre(
    new EnvSecretProvider({ ambiente: "dev", env: { [nomeDaVariavel("pepper_contact_xtenant")]: "sem-kid" } }),
  );
  await assert.rejects(exigirChaveDeCorrelacao(malFormada), (erro: unknown) => {
    assert.ok(erro instanceof ChaveDeCorrelacaoEmFaltaError);
    assert.equal(erro.message.includes("sem-kid"), false, "o valor não entra na mensagem");
    return true;
  });
});

test("a retenção é de 90 dias (proposta, D4)", () => {
  assert.equal(DIAS_DE_RETENCAO_DO_PSEUDONIMO, 90);
});

// ----------------------------------------------------- na resolução de identidade

/** Um cliente com respostas escritas à mão, por texto da instrução. */
class ClienteDeGuiao implements ClienteDeIdentidade {
  readonly vistas: { sql: string; parametros: readonly unknown[] }[] = [];
  readonly guiao = new Map<string, ResultadoSql>();

  async query(sql: string, parametros: readonly unknown[] = []): Promise<ResultadoSql> {
    this.vistas.push({ sql, parametros });
    return this.guiao.get(sql) ?? { rows: [], rowCount: 0 };
  }

  com(sql: string): readonly (readonly unknown[])[] {
    return this.vistas.filter((v) => v.sql === sql).map((v) => v.parametros);
  }
}

function clienteNovo(): ClienteDeGuiao {
  const c = new ClienteDeGuiao();
  c.guiao.set(SQL.KIDS_VIVOS, { rows: [{ kid: "k1", estado: "actual" }] });
  c.guiao.set(SQL.CRIAR_CONTACTO, { rows: [{ contact_id: CONTACTO, criado_at: AGORA }] });
  c.guiao.set(SQL.DEFINIR_TELEFONE, { rows: [], rowCount: 1 });
  return c;
}

/** Uma fonte que conta as leituras: ligada no sítio errado, conta. */
class FonteContada implements FonteDaCorrelacao {
  leituras = 0;
  async chaveActual() {
    this.leituras++;
    return lerVersionada(REF_CHAVE_DE_CORRELACAO, CHAVE_X);
  }
}

async function identidade(ambiente: "dev" | "prod", correlacao: string | undefined, fonte?: FonteDaCorrelacao) {
  const env = {
    ...ambienteDeChaves({
      ambiente,
      pesquisa: [gerarChaveVersionada("k1")],
      kek: [gerarChaveVersionada("kek-1")],
    }),
    ...(correlacao === undefined ? {} : { [VARIAVEL_DA_CORRELACAO]: correlacao }),
  };
  return Identidade.arrancar({
    chaves: new EnvKeyProvider({ ambiente, env }),
    env,
    agora: () => AGORA,
    ...(fonte === undefined ? {} : { correlacao: fonte }),
  });
}

test("ligada, resolver um telefone escreve o pseudónimo sem tenant sob o kid actual, com o visto_at do relógio", async () => {
  const fonte = new FonteContada();
  const id = await identidade("dev", "ligada", fonte);
  const c = clienteNovo();
  await id.resolveContact(c, { tenantId: TENANT_A, telefone: `+${TELEFONE}` });
  const [escrita, ...mais] = c.com(SQL.DEFINIR_PSEUDONIMO_SEM_TENANT);
  assert.equal(mais.length, 0);
  const { chave } = lerVersionada(REF_CHAVE_DE_CORRELACAO, CHAVE_X);
  assert.deepEqual(escrita, [TENANT_A, CONTACTO, pseudonimoSemTenant(chave, TELEFONE), "x1", AGORA]);
  // Adversarial: nenhum parâmetro de nenhuma instrução leva o número em claro.
  for (const v of c.vistas) {
    for (const p of v.parametros) assert.equal(String(p).includes(TELEFONE), false, v.sql);
  }
});

test("ligada, um pedido só com BSUID não escreve pseudónimo, mas renova o visto_at do que houver (D4)", async () => {
  const id = await identidade("dev", "ligada", new FonteContada());
  const c = clienteNovo();
  await id.resolveContact(c, { tenantId: TENANT_A, bsuid: "AO.1234567890" });
  assert.equal(c.com(SQL.DEFINIR_PSEUDONIMO_SEM_TENANT).length, 0);
  assert.deepEqual(c.com(SQL.RENOVAR_PSEUDONIMO_SEM_TENANT), [[TENANT_A, CONTACTO, AGORA]]);
});

test("desligada, um pedido só com BSUID não renova nada", async () => {
  const id = await identidade("dev", undefined, new FonteContada());
  const c = clienteNovo();
  await id.resolveContact(c, { tenantId: TENANT_A, bsuid: "AO.1234567890" });
  assert.equal(c.com(SQL.RENOVAR_PSEUDONIMO_SEM_TENANT).length, 0);
});

for (const [ambiente, valor] of [
  ["dev", undefined],
  ["dev", "desligada"],
  ["prod", "ligada"],
] as const) {
  test(`${ambiente} com o interruptor ${valor ?? "por definir"}: nada se calcula nem se lê a chave`, async () => {
    const fonte = new FonteContada();
    const id = await identidade(ambiente, valor, fonte);
    const c = clienteNovo();
    await id.resolveContact(c, { tenantId: TENANT_A, telefone: TELEFONE });
    assert.equal(c.com(SQL.DEFINIR_PSEUDONIMO_SEM_TENANT).length, 0);
    assert.equal(fonte.leituras, 0, "a chave foi lida com o interruptor desligado");
  });
}

test("ligada sem chave no ambiente, o arranque recusa; trancada em prod, arranca sem ela", async () => {
  await assert.rejects(identidade("dev", "ligada"), ChaveDeCorrelacaoEmFaltaError);
  assert.ok((await identidade("prod", "ligada")) instanceof Identidade);
});

test("um processo que só lê endpoints não precisa da chave, mesmo ligado", async () => {
  const env = {
    ...ambienteDeChaves({ ambiente: "dev", kek: [gerarChaveVersionada("kek-1")] }),
    [VARIAVEL_DA_CORRELACAO]: "ligada",
  };
  const id = await Identidade.arrancar({ chaves: new EnvKeyProvider({ ambiente: "dev", env }), env, soLeEndpoints: true });
  assert.ok(id instanceof Identidade);
});

test("apagar o contacto apaga o pseudónimo, com o interruptor desligado também", async () => {
  const id = await identidade("dev", undefined);
  const c = new ClienteDeGuiao();
  c.guiao.set(SQL.TRANCAR_CONTACTOS, {
    rows: [{ contact_id: CONTACTO, criado_at: AGORA, erased_at: null, merged_into: null, phone_hmac: null, hmac_kid: null }],
  });
  c.guiao.set(SQL.MARCAR_APAGADO, { rows: [{ erased_at: AGORA }], rowCount: 1 });
  await id.eraseContact(c, TENANT_A, CONTACTO);
  assert.deepEqual(c.com(SQL.APAGAR_PSEUDONIMO_SEM_TENANT), [[TENANT_A, CONTACTO]]);
});

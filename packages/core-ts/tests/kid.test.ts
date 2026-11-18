/**
 * O `kid` estável da KEK dos *tokens* de cliente, e a re-cifra dos guardados
 * (KAM-205): unidade, sem base.
 *
 * **Nenhuma chave deste ficheiro é literal.** Todas saem do `gerarValor()` em
 * tempo de execução, como no `keyring.test.ts`: o *gate* 9 não tem nada a ver,
 * e nenhum valor fica no repositório.
 *
 * O que só uma base prova — a RLS a esconder os canais de outro papel, o
 * `UPDATE ... AND token_ref = $2` sob a tabela real, e a passagem inteira sobre
 * linhas de vários *tenants* — está no `tests_bd/onboarding.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  type DependenciasDaRecifra,
  RecifraSemPapelDeLoteError,
  SQL_CANAIS_A_RECIFRAR,
  SQL_PAPEL_ATRAVESSA_TENANTS,
  SQL_TROCAR_TOKEN_REF,
  anelDaKekNoCofre,
  gerarValor,
  recifrarToken,
  recifrarTokensGuardados,
  revogarAnterior,
} from "../src/keyring/index.ts";
import {
  FAMILIA_DO_TOKEN,
  KID_LEGADO,
  KekSemKidEstavelError,
  REF_DA_KEK,
  TokenCifradoInvalidoError,
  anelDaKek,
  cifrarToken,
  decifrarToken,
  kekParaCifrar,
  kidDoCriptograma,
} from "../src/onboarding/index.ts";
import type { ClienteSql, Cofre } from "../src/onboarding/index.ts";
import { DopplerSecretProvider } from "../src/secrets/doppler.ts";
import { EnvSecretProvider } from "../src/secrets/env.ts";
import { cunharRef } from "../src/secrets/escrita.ts";
import {
  KidRepetidoNoCofreError,
  chaveDoValor,
  kidDoValor,
  kidsDasVersoes,
  separarKid,
} from "../src/secrets/kid.ts";
import { SecretAusenteError } from "../src/secrets/port.ts";

const TENANT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const OUTRO = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const VAR = "KAMBA_SECRET_KEK_TOKEN_CLIENTE";

/** Um provedor de ambiente com a KEK em `actual` e, se dada, em `anterior`. */
function ambiente(actual: string, anterior?: string): EnvSecretProvider {
  const env: Record<string, string> = { [VAR]: actual };
  if (anterior !== undefined) env[`${VAR}_ANTERIOR`] = anterior;
  return new EnvSecretProvider({ ambiente: "staging", env });
}

/** O anel como o `#tokenEmClaro` do onboarding o monta. */
async function anelComoOOnboarding(env: EnvSecretProvider): Promise<Readonly<Record<string, string>>> {
  return anelDaKek(await env.getRing(REF_DA_KEK), await env.versions(REF_DA_KEK));
}

/** Cifra como o `#trocarEGuardar` do onboarding cifra. */
async function cifrarComoOOnboarding(env: EnvSecretProvider, tenant: string, token: string): Promise<string> {
  const [kid] = await env.versions(REF_DA_KEK);
  const kek = kekParaCifrar(kid as string, await env.get(REF_DA_KEK));
  return cifrarToken(kek.chave, kek.kid, tenant, token);
}

function token(): string {
  return `EAAG${gerarValor()}`;
}

// --- O kid no valor -------------------------------------------------------------

describe("o kid no valor: <kid>:<base64 de 32 octetos>, e mais nada (KAM-205)", () => {
  it("separa o kid da chave, e devolve null a tudo o que não é uma chave nossa", () => {
    const chave = gerarValor();
    assert.deepEqual(separarKid(`20261118.abcdefgh:${chave}`), { kid: "20261118.abcdefgh", chave });
    assert.equal(chaveDoValor(`k1:${chave}`), chave);
    assert.equal(chaveDoValor(chave), chave, "sem kid, a chave é o valor inteiro");
    for (const valor of [
      chave,
      `utilizador:segredo-que-nao-e-base64`,
      `K1:${chave}`,
      `:${chave}`,
      `k1:${Buffer.alloc(31, 1).toString("base64")}`,
      `k1:${Buffer.alloc(33, 1).toString("base64")}`,
      `k1:${chave.slice(0, -1)}`,
      `actual:${chave}`,
      `anterior:${chave}`,
    ]) {
      assert.equal(separarKid(valor), null, `não é <kid>:<base64>: ${valor.length} caracteres`);
      assert.equal(kidDoValor(valor), null);
    }
  });

  it("uma senha com dois pontos não dá um pedaço dela como kid", () => {
    assert.equal(kidDoValor("kamba_app:senha-de-ensaio"), null);
    assert.deepEqual(kidsDasVersoes("db_pay_password", "kamba_app:senha-de-ensaio", null), ["actual"]);
  });

  it("os kids das versões: o do valor, e só sem ele o rótulo da posição", () => {
    const a = `k2:${gerarValor()}`;
    const b = `k1:${gerarValor()}`;
    assert.deepEqual(kidsDasVersoes("kek_token_cliente", a, b), ["k2", "k1"]);
    assert.deepEqual(kidsDasVersoes("kek_token_cliente", a, gerarValor()), ["k2", "anterior"]);
    assert.deepEqual(kidsDasVersoes("kek_token_cliente", gerarValor(), b), ["actual", "k1"]);
    assert.deepEqual(kidsDasVersoes("meta_app_secret", gerarValor(), gerarValor()), ["actual", "anterior"]);
  });

  it("duas versões com o mesmo kid são recusadas, e o erro não leva o valor", () => {
    const a = `k1:${gerarValor()}`;
    const b = `k1:${gerarValor()}`;
    const erro = (() => {
      try {
        kidsDasVersoes("kek_token_cliente", a, b);
      } catch (e) {
        return e as Error;
      }
      return null;
    })();
    assert.ok(erro instanceof KidRepetidoNoCofreError);
    assert.ok(!erro.message.includes(a.slice(3)) && !erro.message.includes(b.slice(3)));
  });

  it("o EnvSecretProvider: a mesma versão tem o mesmo kid antes e depois de passar a anterior", async () => {
    const k1 = `k1:${gerarValor()}`;
    assert.deepEqual(await ambiente(k1).versions(REF_DA_KEK), ["k1"]);
    assert.deepEqual(await ambiente(`k2:${gerarValor()}`, k1).versions(REF_DA_KEK), ["k2", "k1"]);
    await assert.rejects(ambiente(k1, k1).versions(REF_DA_KEK), KidRepetidoNoCofreError);
    await assert.rejects(
      new EnvSecretProvider({ ambiente: "dev", env: {} }).versions(REF_DA_KEK),
      SecretAusenteError,
    );
  });

  it("o DopplerSecretProvider lê o kid da mesma maneira", async () => {
    const k1 = `k1:${gerarValor()}`;
    const corpo = { [VAR]: `k2:${gerarValor()}`, [`${VAR}_ANTERIOR`]: k1 };
    const doppler = new DopplerSecretProvider({
      ambiente: "prod",
      projecto: "kamba",
      config: "prod",
      tokenServico: "ensaio",
      transporte: async () => ({ status: 200, corpo: JSON.stringify(corpo) }),
      ttlDescargaMs: 0,
    });
    assert.deepEqual(await doppler.versions(REF_DA_KEK), ["k2", "k1"]);
  });
});

// --- A cifra do onboarding com kid estável -------------------------------------

describe("a KEK com kid estável: um rótulo posicional nunca chega ao criptograma (KAM-205)", () => {
  it("cifrar com a KEK sem kid é recusado, e com kid grava o kid do valor", async () => {
    await assert.rejects(cifrarComoOOnboarding(ambiente(gerarValor()), TENANT, token()), KekSemKidEstavelError);
    for (const rotulo of ["actual", "anterior"]) {
      assert.throws(() => kekParaCifrar(rotulo, gerarValor()), KekSemKidEstavelError);
    }
    const c = await cifrarComoOOnboarding(ambiente(`k1:${gerarValor()}`), TENANT, token());
    assert.equal(kidDoCriptograma(c), "k1");
  });

  it("rodar para um kid novo não parte o token guardado, e revogar depois da re-cifra também não", async () => {
    const k1 = `k1:${gerarValor()}`;
    const t = token();
    const guardado = await cifrarComoOOnboarding(ambiente(k1), TENANT, t);
    const rodado = ambiente(`k2:${gerarValor()}`, k1);
    assert.equal(decifrarToken(await anelComoOOnboarding(rodado), TENANT, guardado), t);

    const anel = await anelDaKekNoCofre(rodado);
    const { criptograma, mudou } = recifrarToken(anel, TENANT, guardado);
    assert.equal(mudou, true);
    assert.equal(kidDoCriptograma(criptograma), "k2");
    const soANova = ambiente((await rodado.getRing(REF_DA_KEK))[0]);
    assert.equal(decifrarToken(await anelComoOOnboarding(soANova), TENANT, criptograma), t);
    assert.equal(revogarAnterior(anel).anterior, null);
  });

  it("um criptograma de antes da correcção (kid actual) abre depois dela e depois de uma rotação", async () => {
    const legada = gerarValor();
    const t = token();
    // É o que o código do KAM-016 gravava: o rótulo `actual` do `versions()[0]`.
    const antigo = cifrarToken(legada, "actual", TENANT, t);
    assert.equal(kidDoCriptograma(antigo), KID_LEGADO);

    assert.equal(decifrarToken(await anelComoOOnboarding(ambiente(legada)), TENANT, antigo), t);
    const rodado = ambiente(`k2:${gerarValor()}`, legada);
    assert.equal(decifrarToken(await anelComoOOnboarding(rodado), TENANT, antigo), t);

    const novo = recifrarToken(await anelDaKekNoCofre(rodado), TENANT, antigo);
    assert.equal(kidDoCriptograma(novo.criptograma), "k2");
    const soANova = ambiente((await rodado.getRing(REF_DA_KEK))[0]);
    assert.equal(decifrarToken(await anelComoOOnboarding(soANova), TENANT, novo.criptograma), t);
    assert.throws(
      () => decifrarToken(anelDaKek([gerarValor(), null], ["actual"]), TENANT, antigo),
      /autenticação falhou/,
      "a regra não é tentativa: com a versão legada fora do anel, não abre",
    );
  });

  it("duas versões sem kid: recusa montar o anel, em vez de tentar as duas", async () => {
    const legada = gerarValor();
    const antigo = cifrarToken(legada, "actual", TENANT, token());
    await assert.rejects(anelComoOOnboarding(ambiente(gerarValor(), legada)), TokenCifradoInvalidoError);
    await assert.rejects(anelDaKekNoCofre(ambiente(gerarValor(), legada)), KekSemKidEstavelError);
    assert.ok(antigo.length > 0);
  });

  it("re-cifrar para uma actual sem kid é recusado: era recriar o defeito", async () => {
    await assert.rejects(anelDaKekNoCofre(ambiente(gerarValor())), KekSemKidEstavelError);
  });

  it("a regra não é tentativa: com a chave certa no anel sob outro kid, o criptograma antigo não abre", async () => {
    // É o erro que o RB-K07 §3.7 proíbe: prefixar `k1:` à KEK legada em vez de
    // rodar. A chave que abriria o criptograma está no anel — sob `k1`, e não
    // sob `actual`. Uma implementação que tentasse as chaves do anel abria-o.
    const legada = gerarValor();
    const t = token();
    const antigo = cifrarToken(legada, "actual", TENANT, t);
    const prefixada = ambiente(`k1:${legada}`);
    const anel = await anelComoOOnboarding(prefixada);
    assert.equal(anel.k1, legada, "a chave que o abriria está lá");
    assert.throws(() => decifrarToken(anel, TENANT, antigo), /versão actual da KEK, que não está no anel/);
  });

  it("um kid que não bate com o do valor é recusado: o cofre rodou entre as duas leituras", () => {
    const k2 = `k2:${gerarValor()}`;
    assert.throws(() => kekParaCifrar("k1", k2), /não é o da versão lida/);
    assert.throws(() => anelDaKek([k2, null], ["k1"]), /não é o da versão lida/);
    assert.throws(() => anelDaKek([k2, `k1:${gerarValor()}`], ["k3", "k2"]), /não é o da versão lida/);
    // Sem `kid` no valor (o OpenBao, de inteiros) não há o que comparar.
    assert.deepEqual(Object.keys(anelDaKek([gerarValor(), null], ["7"])), ["7"]);
  });

  it("privacidade: nenhum erro leva o valor da KEK nem o token", async () => {
    const legada = gerarValor();
    const k1 = `k1:${gerarValor()}`;
    const t = token();
    const erros: Error[] = [];
    const guardar = async (f: () => unknown): Promise<void> => {
      try {
        await f();
      } catch (e) {
        erros.push(e as Error);
      }
    };
    await guardar(() => cifrarComoOOnboarding(ambiente(legada), TENANT, t));
    await guardar(() => anelComoOOnboarding(ambiente(gerarValor(), legada)));
    await guardar(() => ambiente(k1, k1).versions(REF_DA_KEK));
    const c = cifrarToken(chaveDoValor(k1), "k1", TENANT, t);
    await guardar(() => decifrarToken({ k1: legada }, TENANT, c));
    await guardar(() => decifrarToken({ k1: chaveDoValor(k1) }, OUTRO, c));
    await guardar(() => decifrarToken({ k2: legada }, TENANT, c));
    assert.equal(erros.length, 6);
    for (const erro of erros) {
      const texto = `${erro.message}\n${String(erro.stack)}`;
      for (const proibido of [legada, chaveDoValor(k1), t]) {
        assert.ok(!texto.includes(proibido), `o erro ${erro.name} leva um valor`);
      }
    }
  });
});

// --- O job de re-cifra, com duplos ---------------------------------------------

/** O cofre do ensaio: a KEK de um `EnvSecretProvider` e os criptogramas num mapa. */
class CofreDeEnsaio implements Cofre {
  kek: EnvSecretProvider;
  readonly segredos = new Map<string, string>();
  readonly revogados: string[] = [];

  constructor(kek: EnvSecretProvider) {
    this.kek = kek;
  }

  async get(ref: string): Promise<string> {
    if (ref === REF_DA_KEK) return this.kek.get(ref);
    const valor = this.segredos.get(ref);
    if (valor === undefined) throw new SecretAusenteError(ref, "ensaio");
    return valor;
  }

  async getRing(ref: string): Promise<readonly [string, string | null]> {
    return this.kek.getRing(ref);
  }

  async versions(ref: string): Promise<readonly string[]> {
    return this.kek.versions(ref);
  }

  async cunhar(familia: string, valor: string): Promise<string> {
    assert.equal(familia, FAMILIA_DO_TOKEN);
    const ref = cunharRef(familia);
    this.segredos.set(ref, valor);
    return ref;
  }

  async revogar(ref: string): Promise<void> {
    this.revogados.push(ref);
    this.segredos.delete(ref);
  }
}

interface Canal {
  id: string;
  tenant_id: string;
  token_ref: string;
}

/** A base do ensaio: só as três consultas do job, e conta as trocas. */
class BaseDeEnsaio implements ClienteSql {
  atravessa = true;
  canais: Canal[] = [];
  /** Quando `true`, o `UPDATE` não encontra a linha: outro escritor mudou-a. */
  perderATroca = false;
  paginas = 0;

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ readonly rows: readonly T[] }> {
    if (texto === SQL_PAPEL_ATRAVESSA_TENANTS) return { rows: [{ atravessa: this.atravessa }] as T[] };
    if (texto === SQL_CANAIS_A_RECIFRAR) {
      this.paginas += 1;
      const [depois, lote] = valores as [string, number];
      const linhas = [...this.canais]
        .sort((a, b) => (a.id < b.id ? -1 : 1))
        .filter((c) => c.id > depois)
        .slice(0, lote);
      return { rows: linhas.map((c) => ({ ...c })) as T[] };
    }
    if (texto === SQL_TROCAR_TOKEN_REF) {
      const [id, antigo, novo] = valores as [string, string, string];
      const canal = this.canais.find((c) => c.id === id && c.token_ref === antigo);
      if (canal === undefined || this.perderATroca) return { rows: [] };
      canal.token_ref = novo;
      return { rows: [{ id }] as T[] };
    }
    throw new Error(`SQL que o duplo não conhece: ${texto.slice(0, 60)}`);
  }
}

function montarJob(): { cofre: CofreDeEnsaio; sql: BaseDeEnsaio; legada: string; d: DependenciasDaRecifra } {
  const legada = gerarValor();
  const cofre = new CofreDeEnsaio(ambiente(legada));
  const sql = new BaseDeEnsaio();
  return { cofre, sql, legada, d: { cofre, sql, lote: 2 } };
}

/** Grava um canal com o criptograma de `kek`/`kid`, e devolve o token em claro. */
function semear(cofre: CofreDeEnsaio, sql: BaseDeEnsaio, kek: string, kid: string, tenant = TENANT): string {
  const t = token();
  const ref = cunharRef(FAMILIA_DO_TOKEN);
  cofre.segredos.set(ref, cifrarToken(kek, kid, tenant, t));
  sql.canais.push({ id: randomUUID(), tenant_id: tenant, token_ref: ref });
  return t;
}

describe("a re-cifra dos tokens guardados: idempotente, retomável, sem perder nenhum (KAM-205)", () => {
  it("rodar, re-cifrar e revogar: todos os tokens continuam a abrir, e a repetição não muda nada", async () => {
    const { cofre, sql, legada, d } = montarJob();
    const tokens = [semear(cofre, sql, legada, "actual"), semear(cofre, sql, legada, "actual", OUTRO), semear(cofre, sql, legada, "actual")];
    const nova = `k2:${gerarValor()}`;
    cofre.kek = ambiente(nova, legada);

    const primeira = await recifrarTokensGuardados(d);
    assert.deepEqual(primeira, { vistos: 3, recifrados: 3, jaNaActual: 0, concorrentes: 0, falhados: [] });
    assert.ok(sql.paginas >= 2, "o lote de 2 obriga a mais de uma página");
    assert.equal(cofre.revogados.length, 3, "a referência antiga de cada canal foi revogada");

    const refsDepois = sql.canais.map((c) => c.token_ref);
    const segunda = await recifrarTokensGuardados(d);
    assert.deepEqual(segunda, { vistos: 3, recifrados: 0, jaNaActual: 3, concorrentes: 0, falhados: [] });
    assert.deepEqual(sql.canais.map((c) => c.token_ref), refsDepois, "a repetição não troca referências");

    cofre.kek = ambiente(nova);
    const anel = anelDaKek(await cofre.getRing(REF_DA_KEK), await cofre.versions(REF_DA_KEK));
    sql.canais.forEach((c, i) => {
      const guardado = cofre.segredos.get(c.token_ref) as string;
      assert.equal(kidDoCriptograma(guardado), "k2");
      assert.equal(decifrarToken(anel, c.tenant_id, guardado), tokens[i]);
    });
  });

  it("retoma: um canal que já foi re-cifrado não se toca, e os outros sim", async () => {
    const { cofre, sql, legada, d } = montarJob();
    const nova = `k2:${gerarValor()}`;
    semear(cofre, sql, legada, "actual");
    semear(cofre, sql, chaveDoValor(nova), "k2");
    cofre.kek = ambiente(nova, legada);
    assert.deepEqual(await recifrarTokensGuardados(d), {
      vistos: 2,
      recifrados: 1,
      jaNaActual: 1,
      concorrentes: 0,
      falhados: [],
    });
  });

  it("um canal que não abre fica em falhados e não pára os outros; o id, nunca o valor", async () => {
    const { cofre, sql, legada, d } = montarJob();
    semear(cofre, sql, legada, "actual");
    semear(cofre, sql, gerarValor(), "actual");
    sql.canais.push({ id: randomUUID(), tenant_id: TENANT, token_ref: cunharRef(FAMILIA_DO_TOKEN) });
    cofre.kek = ambiente(`k2:${gerarValor()}`, legada);
    const r = await recifrarTokensGuardados(d);
    assert.equal(r.recifrados, 1);
    assert.equal(r.falhados.length, 2);
    for (const id of r.falhados) assert.ok(sql.canais.some((c) => c.id === id));
  });

  it("quem perde a troca não escreve e revoga a referência que cunhou", async () => {
    const { cofre, sql, legada, d } = montarJob();
    semear(cofre, sql, legada, "actual");
    const antes = sql.canais[0]?.token_ref as string;
    cofre.kek = ambiente(`k2:${gerarValor()}`, legada);
    sql.perderATroca = true;
    const r = await recifrarTokensGuardados(d);
    assert.equal(r.concorrentes, 1);
    assert.equal(sql.canais[0]?.token_ref, antes);
    assert.ok(cofre.segredos.has(antes), "a antiga não se revoga quando a troca não aconteceu");
    assert.equal(cofre.segredos.size, 1, "a nova foi revogada");
  });

  it("sem BYPASSRLS recusa antes de ler o cofre: zero canais não é «acabou»", async () => {
    const { cofre, sql, legada, d } = montarJob();
    semear(cofre, sql, legada, "actual");
    cofre.kek = ambiente(`k2:${gerarValor()}`, legada);
    sql.atravessa = false;
    await assert.rejects(recifrarTokensGuardados(d), RecifraSemPapelDeLoteError);
    assert.equal(sql.paginas, 0);
    assert.equal(cofre.revogados.length, 0);
  });

  it("uma actual sem kid é recusada antes de tocar num canal", async () => {
    const { cofre, sql, legada, d } = montarJob();
    semear(cofre, sql, legada, "actual");
    await assert.rejects(recifrarTokensGuardados(d), KekSemKidEstavelError);
    assert.equal(sql.paginas, 0);
  });

  it("um cofre em baixo propaga: é uma passagem por repetir, não um token perdido", async () => {
    const { cofre, sql, legada, d } = montarJob();
    semear(cofre, sql, legada, "actual");
    cofre.kek = ambiente(`k2:${gerarValor()}`, legada);
    cofre.get = async (ref: string) => {
      if (ref === REF_DA_KEK) return cofre.kek.get(ref);
      throw new Error("cofre em baixo");
    };
    await assert.rejects(recifrarTokensGuardados(d), /cofre em baixo/);
  });
});

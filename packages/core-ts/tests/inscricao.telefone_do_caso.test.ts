/**
 * O `phone_enc` do caso de onboarding (KAM-215): a cifra com a KEK própria, o
 * escritor e o decifrador.
 *
 * O que só a cifra prova, sem base: que o criptograma de um caso **não abre**
 * noutro (do mesmo tenant ou de outro), que a rotação da KEK não torna ilegível
 * o que já está escrito, que uma KEK sem `kid` estável é recusada antes de
 * cifrar, e que nenhuma mensagem de erro leva o número. Os números são
 * fictícios, com 999.
 */

import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { describe, it } from "node:test";
import { inspect } from "node:util";

import {
  KekDoTelefoneInvalidaError,
  Telefone,
  TelefoneCifradoInvalidoError,
  anelDoTelefone,
  cifrarTelefoneDoCaso,
  colunasDoTelefone,
  decifrarTelefoneDoCaso,
  lerAnelDoTelefone,
  lerTelefoneDoCaso,
  SQL_TELEFONE_DO_CASO,
} from "../src/inscricao/index.ts";

const NUMERO = "+244 999 000 601";
const E164 = "+244999000601";
const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_1 = "11111111-1111-4111-8111-111111111111";
const CASO_2 = "22222222-2222-4222-8222-222222222222";
const PEPPER = Buffer.alloc(32, 0x5a);

const valor = (kid: string, octeto: number) => `${kid}:${Buffer.alloc(32, octeto).toString("base64")}`;
const ANEL = anelDoTelefone([valor("tel-2026-11", 0x11), null]);

const caso = (tenantId: string, onboardingId: string) => ({ tenantId, onboardingId });

describe("KAM-215 — a cifra do telefone do caso", () => {
  it("cifra e decifra o mesmo caso; dois envios do mesmo número dão criptogramas diferentes", () => {
    const um = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const outro = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    assert.notDeepEqual(um, outro, "um IV novo por chamada");
    assert.equal(decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), um).revelar(), E164);
    assert.ok(!um.toString("latin1").includes("999000601"), "o número não aparece no criptograma");
  });

  it("um phone_enc copiado para outro caso NÃO decifra — nem no mesmo tenant, nem noutro", () => {
    const cifra = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_2), cifra), TelefoneCifradoInvalidoError);
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_B, CASO_1), cifra), TelefoneCifradoInvalidoError);
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_B, CASO_2), cifra), TelefoneCifradoInvalidoError);
  });

  it("um octeto alterado não abre, e um formato desconhecido também não", () => {
    const cifra = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const alterada = Buffer.from(cifra);
    alterada[alterada.length - 1] = (alterada[alterada.length - 1] ?? 0) ^ 0x01;
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), alterada), TelefoneCifradoInvalidoError);
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), Buffer.from([9, 1, 2])), TelefoneCifradoInvalidoError);
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), Buffer.alloc(0)), TelefoneCifradoInvalidoError);
  });

  it("a rotação: o que a versão anterior cifrou abre com o anel novo; sem ela no anel, não abre", () => {
    const antigo = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const rodado = anelDoTelefone([valor("tel-2027-11", 0x22), valor("tel-2026-11", 0x11)]);
    assert.equal(rodado.kid, "tel-2027-11");
    assert.equal(decifrarTelefoneDoCaso(rodado, caso(TENANT_A, CASO_1), antigo).revelar(), E164);
    const novo = cifrarTelefoneDoCaso(rodado, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    assert.throws(() => decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), novo), TelefoneCifradoInvalidoError);
    const soONovo = anelDoTelefone([valor("tel-2027-11", 0x22), null]);
    assert.throws(() => decifrarTelefoneDoCaso(soONovo, caso(TENANT_A, CASO_1), antigo), TelefoneCifradoInvalidoError);
  });

  it("uma KEK sem kid estável, com rótulo posicional, curta, ou com o kid repetido é recusada", () => {
    const sem = Buffer.alloc(32, 1).toString("base64");
    assert.throws(() => anelDoTelefone([sem, null]), KekDoTelefoneInvalidaError);
    assert.throws(() => anelDoTelefone([`actual:${sem}`, null]), KekDoTelefoneInvalidaError);
    assert.throws(() => anelDoTelefone([`k1:${Buffer.alloc(16, 1).toString("base64")}`, null]), KekDoTelefoneInvalidaError);
    assert.throws(() => anelDoTelefone([valor("k1", 1), valor("k1", 2)]), KekDoTelefoneInvalidaError);
    assert.throws(() => anelDoTelefone([valor("k1", 1), sem]), KekDoTelefoneInvalidaError);
  });

  it("o anel lê-se do cofre pela referência própria, e não por outra KEK", async () => {
    const pedidas: string[] = [];
    const anel = await lerAnelDoTelefone({
      getRing: async (ref) => {
        pedidas.push(ref);
        return [valor("tel-2026-11", 0x11), null];
      },
    });
    assert.deepEqual(pedidas, ["kek_telefone_do_caso"]);
    assert.equal(anel.kid, "tel-2026-11");
  });

  it("o mesmo material de chave sob outro kid não abre: o kid está no contexto autenticado", () => {
    const cifra = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const mesmoMaterial = anelDoTelefone([valor("outro-kid", 0x11), null]);
    assert.throws(() => decifrarTelefoneDoCaso(mesmoMaterial, caso(TENANT_A, CASO_1), cifra), TelefoneCifradoInvalidoError);
  });

  it("o escritor dá as duas colunas: a cifra do caso e o HMAC da inscrição", () => {
    const telefone = new Telefone(NUMERO, PEPPER);
    const colunas = colunasDoTelefone(ANEL, caso(TENANT_A, CASO_1), telefone);
    assert.equal(colunas.phoneHmac.toString("hex"), telefone.hmac);
    assert.equal(colunas.phoneHmac.byteLength, 32, "o CHECK da coluna");
    assert.equal(decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), colunas.phoneEnc).revelar(), E164);
  });

  it("o telefone em claro é opaco, e nenhum erro leva o número nem os identificadores", () => {
    const cifra = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const claro = decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), cifra);
    assert.equal(String(claro), "***");
    assert.equal(JSON.stringify({ claro }), '{"claro":"***"}');
    assert.ok(!inspect(claro).includes("999"));
    try {
      decifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_2), cifra);
      assert.fail("devia ter lançado");
    } catch (erro) {
      const texto = `${(erro as Error).message} ${inspect(erro)}`;
      assert.ok(!texto.includes("999000601") && !texto.includes(CASO_2) && !texto.includes(TENANT_A));
    }
  });
});

describe("KAM-215 — o decifrador devolve null em vez de lançar", () => {
  function ligacao(linhas: Record<string, unknown>[]) {
    const pedidos: { sql: string; parametros: readonly unknown[] }[] = [];
    return {
      pedidos,
      query: async (sql: string, parametros: readonly unknown[] = []) => {
        pedidos.push({ sql, parametros });
        return { rows: linhas };
      },
    };
  }
  const ler = lerTelefoneDoCaso(ANEL);

  it("lê o phone_enc do caso pela ligação dada, e só pelo id do caso", async () => {
    const cifra = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_1), new Telefone(NUMERO, PEPPER));
    const bd = ligacao([{ phone_enc: cifra }]);
    assert.equal((await ler(bd, caso(TENANT_A, CASO_1)))?.revelar(), E164);
    assert.deepEqual(bd.pedidos, [{ sql: SQL_TELEFONE_DO_CASO, parametros: [CASO_1] }]);
  });

  it("zero linhas (outro tenant, sob a RLS), coluna ilegível, ou id fora de forma dão null", async () => {
    assert.equal(await ler(ligacao([]), caso(TENANT_A, CASO_1)), null);
    assert.equal(await ler(ligacao([{ phone_enc: Buffer.from("lixo") }]), caso(TENANT_A, CASO_1)), null);
    assert.equal(await ler(ligacao([{ phone_enc: null }]), caso(TENANT_A, CASO_1)), null);
    const bd = ligacao([]);
    assert.equal(await ler(bd, caso(TENANT_A, "nao-e-uuid")), null);
    assert.equal(bd.pedidos.length, 0, "um id fora de forma nem chega à base");
  });

  it("o phone_enc de outro caso, na linha deste, dá null", async () => {
    const doOutro = cifrarTelefoneDoCaso(ANEL, caso(TENANT_A, CASO_2), new Telefone(NUMERO, PEPPER));
    assert.equal(await ler(ligacao([{ phone_enc: doOutro }]), caso(TENANT_A, CASO_1)), null);
  });

  it("uma falha da base sobe: não é «o caso não tem telefone»", async () => {
    const bd = {
      query: async () => {
        throw new Error("ligacao caiu");
      },
    };
    await assert.rejects(ler(bd, caso(TENANT_A, CASO_1)), /ligacao caiu/);
  });
});

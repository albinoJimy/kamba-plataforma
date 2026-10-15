/**
 * As primitivas de identidade: normalizar, pseudonimizar, cifrar (KAM-008).
 *
 * Sem base de dados e sem cofre. O módulo está no estrato `critico` de
 * `ci/thresholds.yaml` (90%).
 */

import assert from "node:assert/strict";
import { createHmac, randomBytes } from "node:crypto";
import { test } from "node:test";

import {
  CifraInvalidaError,
  IdentificadorInvalidoError,
  OCTETOS_DE_HMAC,
  OCTETOS_DE_SUJEITO_REF,
  cifrar,
  contextoDaCifra,
  contextoDoEmbrulho,
  decifrar,
  hmacDePesquisa,
  normalizarBsuid,
  normalizarTelefone,
  normalizarUuid,
  novaDek,
  sujeitoRefDe,
} from "../src/identity/cripto.ts";

const TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";
const OUTRO_TENANT = "1c7a2e3f-4d5b-4c6d-9e7f-8a9b0c1d2e3f";
const CONTACTO = "2d8b3f40-5e6c-4d7e-af80-9b0c1d2e3f40";
const DEK_ID = "3e9c4051-6f7d-4e8f-b091-0c1d2e3f4051";
const CHAVE = Buffer.alloc(32, 7);
const OUTRA_CHAVE = Buffer.alloc(32, 8);

// ---------------------------------------------------------------- normalizar

test("o telefone normaliza-se para E.164 sem o `+`: as duas escritas são o mesmo número", () => {
  assert.equal(normalizarTelefone("+999123456789"), "999123456789");
  assert.equal(normalizarTelefone("999123456789"), "999123456789");
  assert.equal(normalizarTelefone("+12025550123"), "12025550123");
  assert.equal(normalizarTelefone("12345678"), "12345678");
  assert.equal(normalizarTelefone("123456789012345"), "123456789012345");
});

test("um telefone que não é E.164 é recusado, e a mensagem não repete o valor", () => {
  const maus: unknown[] = [
    "",
    "+",
    "1234567", // curto de mais
    "1234567890123456", // 16 algarismos
    "0999123456789", // zero à cabeça
    "+0999123456789",
    "999 123 456 789",
    "999-123-456-789",
    "(999)123456789",
    "++999123456789",
    "999123456789 ",
    " 999123456789",
    "999123456789\n",
    "९९९१२३४५६७८९", // algarismos que não são ASCII
    "999123456abc",
    999123456789,
    null,
    undefined,
    {},
    ["999123456789"],
  ];
  for (const mau of maus) {
    assert.throws(
      () => normalizarTelefone(mau),
      (erro: unknown) => {
        assert.ok(erro instanceof IdentificadorInvalidoError);
        assert.equal(erro.campo, "telefone");
        if (typeof mau === "string" && mau.length > 3) {
          assert.equal(erro.message.includes(mau), false, "a mensagem repete o telefone");
          const algarismos = mau.replace(/[^0-9]/g, "");
          if (algarismos.length > 3) assert.equal(erro.message.includes(algarismos), false);
        }
        return true;
      },
      `aceitou ${JSON.stringify(mau)}`,
    );
  }
});

test("o BSUID fica tal como a Meta o manda: nem caixa, nem espaços", () => {
  assert.equal(normalizarBsuid("AO.1234abcdEFGH"), "AO.1234abcdEFGH");
  assert.equal(normalizarBsuid("PT.x"), "PT.x");
  assert.equal(normalizarBsuid("a".repeat(256)), "a".repeat(256));
  assert.notEqual(normalizarBsuid("AO.abc"), normalizarBsuid("AO.ABC"));
});

test("um BSUID com espaços, controlo, não-ASCII ou vazio é recusado sem ser repetido", () => {
  const maus: unknown[] = [
    "",
    " AO.123",
    "AO.123 ",
    "AO. 123",
    "AO.123\n",
    "AO.123\u0000",
    "AO.çã",
    "a".repeat(257),
    123,
    null,
    undefined,
    {},
  ];
  for (const mau of maus) {
    assert.throws(
      () => normalizarBsuid(mau),
      (erro: unknown) => {
        assert.ok(erro instanceof IdentificadorInvalidoError);
        assert.equal(erro.campo, "bsuid");
        if (typeof mau === "string" && mau.trim().length > 3) {
          assert.equal(erro.message.includes(mau.trim()), false, "a mensagem repete o BSUID");
        }
        return true;
      },
      `aceitou ${JSON.stringify(mau)}`,
    );
  }
});

test("um UUID só passa na forma canónica, e sai em minúsculas", () => {
  assert.equal(normalizarUuid(CONTACTO.toUpperCase(), "contact_id"), CONTACTO);
  for (const mau of [CONTACTO.replaceAll("-", ""), `{${CONTACTO}}`, "", "x", 7, null]) {
    assert.throws(() => normalizarUuid(mau, "contact_id"), IdentificadorInvalidoError);
  }
});

// ---------------------------------------------------------------------- HMAC

test("o HMAC de pesquisa é determinístico e tem 32 octetos", () => {
  const um = hmacDePesquisa(CHAVE, TENANT, "bsuid", "AO.123");
  assert.equal(um.length, OCTETOS_DE_HMAC);
  assert.ok(um.equals(hmacDePesquisa(CHAVE, TENANT, "bsuid", "AO.123")));
});

test("o HMAC de pesquisa é exactamente HMAC-SHA256 sobre domínio, tipo, tenant e valor", () => {
  // Vector calculado por fora, com a mensagem escrita à mão: se a forma mudar,
  // todos os contactos existentes deixam de ser encontrados.
  const esperado = createHmac("sha256", CHAVE)
    .update(Buffer.from(`kamba.identity.v1\x00telefone\x00${TENANT}\x00999123456789`, "utf8"))
    .digest();
  assert.ok(hmacDePesquisa(CHAVE, TENANT, "telefone", "999123456789").equals(esperado));
});

test("muda com a chave, com o tenant, com o tipo e com o valor", () => {
  const base = hmacDePesquisa(CHAVE, TENANT, "bsuid", "999123456789");
  const variantes = [
    hmacDePesquisa(OUTRA_CHAVE, TENANT, "bsuid", "999123456789"),
    hmacDePesquisa(CHAVE, OUTRO_TENANT, "bsuid", "999123456789"),
    hmacDePesquisa(CHAVE, TENANT, "telefone", "999123456789"),
    hmacDePesquisa(CHAVE, TENANT, "bsuid", "999123456780"),
  ];
  for (const variante of variantes) assert.equal(variante.equals(base), false);
  assert.equal(new Set(variantes.map((v) => v.toString("hex"))).size, variantes.length);
});

test("os campos não se confundem: o separador impede que tipo+tenant+valor se desloquem", () => {
  // Sem separador, ("bsuid", T, "x") e ("bsuid", T + "x", "") dariam o mesmo.
  const a = hmacDePesquisa(CHAVE, TENANT, "bsuid", "telefone");
  const b = hmacDePesquisa(CHAVE, TENANT, "telefone", "bsuid");
  assert.equal(a.equals(b), false);
});

test("o HMAC recusa chave curta, tenant fora da forma canónica, tipo desconhecido e valor vazio", () => {
  assert.throws(() => hmacDePesquisa(Buffer.alloc(16), TENANT, "bsuid", "x"), CifraInvalidaError);
  assert.throws(
    () => hmacDePesquisa("chave" as unknown as Uint8Array, TENANT, "bsuid", "x"),
    CifraInvalidaError,
  );
  assert.throws(
    () => hmacDePesquisa(CHAVE, TENANT.toUpperCase(), "bsuid", "x"),
    IdentificadorInvalidoError,
  );
  assert.throws(() => hmacDePesquisa(CHAVE, "", "bsuid", "x"), IdentificadorInvalidoError);
  assert.throws(
    () => hmacDePesquisa(CHAVE, TENANT, "email" as unknown as "bsuid", "x"),
    IdentificadorInvalidoError,
  );
  assert.throws(() => hmacDePesquisa(CHAVE, TENANT, "bsuid", ""), IdentificadorInvalidoError);
});

// --------------------------------------------------------------------- cifra

test("cifrar e decifrar: o que entra é o que sai", () => {
  const dek = novaDek();
  const contexto = contextoDaCifra(TENANT, DEK_ID, "bsuid_enc");
  for (const texto of ["AO.123", "999123456789", "x", "ç".repeat(100), "a".repeat(512)]) {
    assert.equal(decifrar(dek, cifrar(dek, texto, contexto), contexto), texto);
  }
});

test("a cifra tem versão, IV de 12 octetos e etiqueta de 16, e não leva o texto dentro", () => {
  const dek = novaDek();
  const contexto = contextoDaCifra(TENANT, DEK_ID, "phone_enc");
  const cifrado = cifrar(dek, "999123456789", contexto);
  assert.equal(cifrado[0], 1);
  assert.equal(cifrado.length, 1 + 12 + 16 + 12);
  assert.equal(cifrado.includes(Buffer.from("999123456789")), false);
});

test("cada cifra usa um IV novo: o mesmo texto nunca dá a mesma cifra", () => {
  const dek = novaDek();
  const contexto = contextoDaCifra(TENANT, DEK_ID, "bsuid_enc");
  const cifras = new Set<string>();
  const ivs = new Set<string>();
  for (let i = 0; i < 500; i += 1) {
    const cifrado = cifrar(dek, "AO.123", contexto);
    cifras.add(cifrado.toString("hex"));
    ivs.add(cifrado.subarray(1, 13).toString("hex"));
  }
  assert.equal(cifras.size, 500);
  assert.equal(ivs.size, 500);
});

test("com a DEK errada, decifrar falha", () => {
  const contexto = contextoDaCifra(TENANT, DEK_ID, "bsuid_enc");
  const cifrado = cifrar(novaDek(), "AO.123", contexto);
  assert.throws(() => decifrar(novaDek(), cifrado, contexto), CifraInvalidaError);
});

test("com outro tenant, outra DEK ou outro campo no contexto, decifrar falha", () => {
  const dek = novaDek();
  const cifrado = cifrar(dek, "AO.123", contextoDaCifra(TENANT, DEK_ID, "bsuid_enc"));
  for (const contexto of [
    contextoDaCifra(OUTRO_TENANT, DEK_ID, "bsuid_enc"),
    contextoDaCifra(TENANT, CONTACTO, "bsuid_enc"),
    contextoDaCifra(TENANT, DEK_ID, "phone_enc"),
    Buffer.alloc(0),
  ]) {
    assert.throws(() => decifrar(dek, cifrado, contexto), CifraInvalidaError);
  }
});

test("qualquer octeto alterado — versão, IV, etiqueta ou texto — faz decifrar falhar", () => {
  const dek = novaDek();
  const contexto = contextoDaCifra(TENANT, DEK_ID, "bsuid_enc");
  const cifrado = cifrar(dek, "AO.123456", contexto);
  for (let posicao = 0; posicao < cifrado.length; posicao += 1) {
    const alterado = Buffer.from(cifrado);
    alterado[posicao] = (alterado[posicao] ?? 0) ^ 0x80;
    assert.throws(
      () => decifrar(dek, alterado, contexto),
      CifraInvalidaError,
      `aceitou a cifra com o octeto ${posicao} alterado`,
    );
  }
  assert.throws(() => decifrar(dek, cifrado.subarray(0, 29), contexto), CifraInvalidaError);
  assert.throws(() => decifrar(dek, Buffer.alloc(0), contexto), CifraInvalidaError);
  assert.throws(
    () => decifrar(dek, "cifra" as unknown as Uint8Array, contexto),
    CifraInvalidaError,
  );
});

test("o erro de uma cifra que não abre não diz nada sobre o conteúdo", () => {
  const dek = novaDek();
  const contexto = contextoDaCifra(TENANT, DEK_ID, "phone_enc");
  const cifrado = cifrar(dek, "999123456789", contexto);
  cifrado[cifrado.length - 1] = (cifrado[cifrado.length - 1] ?? 0) ^ 1;
  assert.throws(
    () => decifrar(dek, cifrado, contexto),
    (erro: unknown) => {
      assert.ok(erro instanceof CifraInvalidaError);
      assert.equal(/[0-9]{6,}/.test(erro.message), false);
      return true;
    },
  );
});

test("não se cifra texto vazio, nem demasiado longo, nem com uma chave que não tem 32 octetos", () => {
  const contexto = contextoDaCifra(TENANT, DEK_ID, "bsuid_enc");
  assert.throws(() => cifrar(novaDek(), "", contexto), CifraInvalidaError);
  assert.throws(() => cifrar(novaDek(), "a".repeat(513), contexto), CifraInvalidaError);
  assert.throws(
    () => cifrar(novaDek(), 5 as unknown as string, contexto),
    CifraInvalidaError,
  );
  assert.throws(() => cifrar(randomBytes(31), "x", contexto), CifraInvalidaError);
  assert.throws(() => decifrar(randomBytes(33), Buffer.alloc(40), contexto), CifraInvalidaError);
});

test("as DEK são de 32 octetos e não se repetem", () => {
  const deks = new Set<string>();
  for (let i = 0; i < 200; i += 1) {
    const dek = novaDek();
    assert.equal(dek.length, 32);
    deks.add(dek.toString("hex"));
  }
  assert.equal(deks.size, 200);
});

test("os contextos da cifra e do embrulho são diferentes e dependem de todos os campos", () => {
  const contextos = [
    contextoDaCifra(TENANT, DEK_ID, "bsuid_enc"),
    contextoDaCifra(TENANT, DEK_ID, "phone_enc"),
    contextoDaCifra(OUTRO_TENANT, DEK_ID, "bsuid_enc"),
    contextoDaCifra(TENANT, CONTACTO, "bsuid_enc"),
    contextoDoEmbrulho(TENANT, DEK_ID),
    contextoDoEmbrulho(OUTRO_TENANT, DEK_ID),
    contextoDoEmbrulho(TENANT, CONTACTO),
  ];
  assert.equal(new Set(contextos.map((c) => c.toString("hex"))).size, contextos.length);
});

// --------------------------------------------------------------- sujeito_ref

test("sujeito_ref são os primeiros 16 octetos de HMAC-SHA256(K_época, contact_id)", () => {
  const ref = sujeitoRefDe(CHAVE, CONTACTO);
  assert.equal(ref.length, OCTETOS_DE_SUJEITO_REF);
  const inteiro = createHmac("sha256", CHAVE).update(CONTACTO, "utf8").digest();
  assert.ok(ref.equals(inteiro.subarray(0, 16)));
});

test("sujeito_ref é determinístico com a mesma chave e diferente com outra", () => {
  assert.ok(sujeitoRefDe(CHAVE, CONTACTO).equals(sujeitoRefDe(CHAVE, CONTACTO)));
  assert.ok(sujeitoRefDe(CHAVE, CONTACTO.toUpperCase()).equals(sujeitoRefDe(CHAVE, CONTACTO)));
  assert.equal(sujeitoRefDe(OUTRA_CHAVE, CONTACTO).equals(sujeitoRefDe(CHAVE, CONTACTO)), false);
  assert.equal(sujeitoRefDe(CHAVE, DEK_ID).equals(sujeitoRefDe(CHAVE, CONTACTO)), false);
});

test("sujeito_ref só aceita um contact_id: nunca um telefone nem um BSUID", () => {
  for (const mau of ["999123456789", "AO.123", "", null]) {
    assert.throws(
      () => sujeitoRefDe(CHAVE, mau as unknown as string),
      IdentificadorInvalidoError,
    );
  }
  assert.throws(() => sujeitoRefDe(Buffer.alloc(8), CONTACTO), CifraInvalidaError);
});

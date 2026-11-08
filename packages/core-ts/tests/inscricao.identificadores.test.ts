/**
 * A bateria dos identificadores da inscrição (KAM-086, critérios 3 e 4).
 *
 * «12 variantes de escrita do mesmo NIF e do mesmo telefone (espaços, pontos,
 * `+244`/`00244`/`9xx`, maiúsculas, dígitos Unicode, zeros à esquerda)
 * normalizam para o mesmo `*_hmac`.»
 *
 * ## As doze são doze, e contam-se no ficheiro
 *
 * As duas listas abaixo têm **exactamente** doze entradas cada, e há um ensaio
 * que o afirma. Não é cerimónia: um critério que diz «12 variantes» cumpre-se à
 * letra, e uma lista que crescesse ou encolhesse num *refactor* deixava a caixa
 * marcada a descrever outra medição.
 *
 * ## Porque é que as formas abertas são metade do valor desta bateria
 *
 * Os detectores de telefone desta casa — o `telefone_ao` de
 * `../../../tools/meta-sim/src/numeros.ts`, o `TELEFONE_PADRAO` do
 * `services/agr` — **não** apanham `923 456 789`: a corrida de dígitos
 * quebra-se no espaço, e está medido no inventário de números do *gate* 7. A
 * lição transposta para cá: um ensaio que só prove a forma compacta prova o caso
 * que nunca falha. Seis das doze variantes do telefone levam separador pelo meio
 * — espaço, hífen, ponto, parêntese, espaço não separável e travessão en —, e as
 * duas últimas são as que uma cópia de uma folha de cálculo ou de um documento
 * produz.
 *
 * ## Os números começam por zero, e isso não é descuido
 *
 * O repositório é **público**, e o ticket diz «nenhum número de telefone real em
 * ficheiro nenhum». Um E.164 nacional nunca começa por `0` — o zero é prefixo de
 * chamada nacional e não entra no número internacional —, pelo que
 * `+244000000001` **não pode** colidir com o telefone de ninguém. É a convenção
 * que o `sms.contrato.test.ts` fixou no KAM-116, e herdá-la é o contrário de
 * inventar uma segunda.
 *
 * O NIF de ensaio não tem fonte que o valide — não há formato do NIF angolano em
 * fonte primária no conjunto (ver `../src/inscricao/identificadores.ts`) — e
 * começa por `541`, que é também o que o mantém fora do `telefone_ao`: aquele
 * padrão exige `244` seguido de `9`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ALGARISMOS_MINIMOS_DO_NIF,
  CARACTERES_DE_TEXTO,
  DOMINIOS,
  Email,
  IdentificadorInvalidoError,
  Nif,
  Telefone,
  ZEROS_DE_BLOCO,
  dobrarAlgarismos,
  hmacCorresponde,
  hmacDe,
  normalizarEmail,
  normalizarNif,
  normalizarTelefone,
  normalizarTexto,
  prefixoDeIp,
} from "../src/inscricao/index.ts";
import { MASCARA } from "../src/sms/index.ts";

const CHAVE = Buffer.alloc(32, 0x5a);
const OUTRA_CHAVE = Buffer.alloc(32, 0x3c);

/** Ver a nota do módulo: nacional a começar por `0` não é atribuível. */
const TELEFONE = "+244000000001";

/** O NIF canónico de ensaio. Ver a nota do módulo. */
const NIF = "5410000123AB";

/**
 * As doze grafias do **mesmo** telefone.
 *
 * Cobrem, uma a uma, os itens que o critério 4 enumera: espaços (4, 7, 9, 11),
 * pontos (6), `+244` (1), `00244` (3, que é também o «zeros à esquerda»), a
 * forma nacional nua que o critério escreve como `9xx` (8), e dígitos Unicode
 * (12).
 */
const DOZE_TELEFONES: readonly string[] = [
  "+244000000001",
  "244000000001",
  "00244000000001",
  "+244 000 000 001",
  "+244-000-000-001",
  "+244.000.000.001",
  "+244 (000) 000-001",
  "000000001",
  "  +244000000001  ",
  "+244 000 000 001",
  "+244–000–000–001",
  "+٢٤٤٠٠٠٠٠٠٠٠١",
];

/**
 * As doze grafias do **mesmo** NIF.
 *
 * Cobrem espaços (3, 7, 8, 9, 10), pontos (4), maiúsculas (2) e dígitos Unicode
 * (11, 12). Os «zeros à esquerda» do critério **não** aparecem aqui, e a razão
 * está escrita no `normalizarNif`: sem formato confirmado pela AGT, colapsar um
 * zero à cabeça pode juntar dois contribuintes distintos, e a consequência não é
 * um falso duplicado inócuo — é o segundo negócio a ser mandado recuperar a
 * sessão por um telefone que não é o dele. A variante é satisfeita no telefone,
 * onde o `00244` é inequívoco.
 */
const DOZE_NIFS: readonly string[] = [
  "5410000123AB",
  "5410000123ab",
  "541 000 0123 AB",
  "541.000.0123.AB",
  "541-000-0123-AB",
  "541/000/0123/AB",
  "(541) 000-0123 AB",
  " 5410000123AB ",
  "541 0000123AB",
  "541–0000123AB",
  "５４１００００１２３ＡＢ",
  "٥٤١٠٠٠٠١٢٣AB",
];

function capturar(fn: () => unknown): Error {
  try {
    fn();
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a chamada nao levantou" });
}

describe("inscricao: as doze variantes do telefone (criterio 4)", () => {
  it("sao doze, contadas no ficheiro", () => {
    assert.equal(DOZE_TELEFONES.length, 12);
    assert.equal(new Set(DOZE_TELEFONES).size, 12, "nenhuma repetida");
  });

  it("as doze normalizam para o mesmo E.164", () => {
    for (const grafia of DOZE_TELEFONES) {
      assert.equal(normalizarTelefone(grafia), TELEFONE, JSON.stringify(grafia));
    }
  });

  it("as doze dao o MESMO phone_hmac", () => {
    const esperado = new Telefone(TELEFONE, CHAVE).hmac;
    for (const grafia of DOZE_TELEFONES) {
      assert.equal(new Telefone(grafia, CHAVE).hmac, esperado, JSON.stringify(grafia));
    }
    assert.match(esperado, /^[0-9a-f]{64}$/);
  });

  it("seis das doze levam separador pelo meio, que e a forma que os detectores desta casa perdem", () => {
    // O predicado define-se antes de contar, que e a disciplina do
    // `references/evidencia-e-verificacao.md`: «separador pelo meio» e um
    // caractere que nao e algarismo nem `+` **entre** dois algarismos.
    const abertas = DOZE_TELEFONES.filter((g) => /[0-9][^0-9+][0-9]/u.test(g.trim()));
    assert.equal(abertas.length, 6, `abertas: ${JSON.stringify(abertas)}`);
  });

  it("um numero diferente da um hmac diferente, e a chave separa os espacos", () => {
    const um = new Telefone(TELEFONE, CHAVE);
    const outro = new Telefone("+244000000002", CHAVE);
    assert.notEqual(um.hmac, outro.hmac);
    assert.notEqual(new Telefone(TELEFONE, OUTRA_CHAVE).hmac, um.hmac);
  });

  it("o telefone e opaco: nao se diz por extenso em conversao nenhuma", () => {
    const telefone = new Telefone(TELEFONE, CHAVE);
    assert.equal(`${telefone}`, MASCARA);
    assert.equal(JSON.stringify({ telefone }), `{"telefone":"${MASCARA}"}`);
    assert.equal(telefone.revelar(), TELEFONE);
    assert.equal(telefone.prefixoDoHmac, telefone.hmac.slice(0, 8));
  });

  it("recusa o que nao e um movel angolano", () => {
    for (const mau of ["", "   ", "+351912345678", "+2440000000", "+2440000000012", "abcdefghi"]) {
      const erro = capturar(() => new Telefone(mau, CHAVE));
      assert.ok(erro instanceof IdentificadorInvalidoError, mau);
      assert.equal(erro.campo, "telefone");
    }
  });

  it("a mensagem do erro nao leva o numero recusado", () => {
    const erro = capturar(() => new Telefone("+351912345678", CHAVE));
    assert.ok(!erro.message.includes("351"));
    assert.ok(!erro.message.includes("912"));
    assert.match(erro.message, /telefone invalido \(13 caracteres, indicativo\)/);
  });

  it("o separador de dominio do telefone nao e o do NIF", () => {
    // O valor de ouro prende o separador: muda-lo muda todos os `*_hmac`
    // escritos, e um indice unico de `nif_hmac` deixava de ver os duplicados
    // que ja la estavam.
    assert.equal(DOMINIOS.telefone, "kamba/onboarding/telefone/v1");
    assert.equal(DOMINIOS.nif, "kamba/onboarding/nif/v1");
    assert.notEqual(
      hmacDe(CHAVE, DOMINIOS.telefone, "x").toString("hex"),
      hmacDe(CHAVE, DOMINIOS.nif, "x").toString("hex"),
    );
  });
});

describe("inscricao: as doze variantes do NIF (criterio 4)", () => {
  it("sao doze, contadas no ficheiro", () => {
    assert.equal(DOZE_NIFS.length, 12);
    assert.equal(new Set(DOZE_NIFS).size, 12, "nenhuma repetida");
  });

  it("as doze normalizam para o mesmo NIF e dao o mesmo nif_hmac", () => {
    const esperado = new Nif(NIF, CHAVE).hmac;
    for (const grafia of DOZE_NIFS) {
      assert.equal(normalizarNif(grafia), NIF, JSON.stringify(grafia));
      assert.equal(new Nif(grafia, CHAVE).hmac, esperado, JSON.stringify(grafia));
    }
  });

  it("os zeros a cabeca NAO se colapsam, e e deliberado", () => {
    // Sem formato confirmado pela AGT, `0` e `00` a cabeca podem ser dois
    // contribuintes. Colapsa-los mandava o segundo negocio recuperar a sessao
    // pelo telefone do primeiro — ver a nota do `normalizarNif`.
    assert.notEqual(normalizarNif("05410000123AB"), normalizarNif(NIF));
    assert.notEqual(new Nif("05410000123AB", CHAVE).hmac, new Nif(NIF, CHAVE).hmac);
  });

  it("recusa o que nao tem forma de NIF", () => {
    // `541000012` NAO esta nesta lista, e a ausencia e medida: nove algarismos
    // passam a `FORMA_DE_NIF` e tem algarismos de sobra, logo e uma forma
    // PLAUSIVEL de NIF — e a forma e larga de proposito (ver a nota do modulo:
    // nao ha formato do NIF angolano em fonte primaria). A primeira versao
    // deste ensaio punha-o aqui e ficou vermelha, que e o resultado certo.
    for (const mau of ["", "  ", "abc", "541", "x".repeat(21), "NIFSEMNUMEROS"]) {
      const erro = capturar(() => new Nif(mau, CHAVE));
      assert.ok(erro instanceof IdentificadorInvalidoError, JSON.stringify(mau));
      assert.equal(erro.campo, "nif");
    }
  });

  it("exige algarismos suficientes, e o limiar e o do modulo", () => {
    assert.equal(ALGARISMOS_MINIMOS_DO_NIF, 8);
    assert.equal(normalizarNif(`${"1".repeat(8)}AB`), `${"1".repeat(8)}AB`);
    assert.throws(() => normalizarNif(`${"1".repeat(7)}ABC`), IdentificadorInvalidoError);
  });

  it("a mensagem do erro nao leva o NIF recusado", () => {
    const erro = capturar(() => new Nif("5410000", CHAVE));
    assert.ok(!erro.message.includes("5410000"));
  });
});

describe("inscricao: algarismos Unicode (criterio 4)", () => {
  it("dobra os blocos declarados para ASCII", () => {
    assert.equal(dobrarAlgarismos("١٢٣", "x"), "123");
    assert.equal(dobrarAlgarismos("۴۵", "x"), "45");
    assert.equal(dobrarAlgarismos("০১", "x"), "01");
    assert.equal(dobrarAlgarismos("７８", "x"), "78");
  });

  it("o NFKC resolve a largura inteira antes da tabela", () => {
    // O `＋` de largura inteira nao esta em `ZEROS_DE_BLOCO` e passa de qualquer
    // modo: e o NFKC que o resolve, e e por isso que as duas passagens existem.
    assert.equal(normalizarTelefone("＋244000000001"), TELEFONE);
  });

  it("RECUSA um algarismo decimal Unicode que a tabela nao cobre", () => {
    // E o passo que faz desta uma barreira em vez de uma conveniencia: sem ele,
    // um algarismo de um bloco nao coberto passava intacto, dava outro HMAC, e
    // o segundo registo do mesmo dono NAO era visto como duplicado. O bloco
    // escolhido — Lao, U+0ED0 — e `\p{Nd}` e esta de fora da lista fechada.
    const laociano = "໐໑໒";
    assert.ok(/\p{Nd}/u.test(laociano), "o controlo tem de ser um algarismo decimal");
    assert.ok(!ZEROS_DE_BLOCO.includes(0x0ed0), "e tem de estar fora da tabela");
    const erro = capturar(() => dobrarAlgarismos(laociano, "nif"));
    assert.ok(erro instanceof IdentificadorInvalidoError);
    assert.equal(erro.motivo, "algarismos_unicode");
  });

  it("a tabela so tem corridas de dez, e e o que a aritmetica pressupoe", () => {
    for (const zero of ZEROS_DE_BLOCO) {
      for (let d = 0; d < 10; d += 1) {
        const caractere = String.fromCodePoint(zero + d);
        assert.ok(/\p{Nd}/u.test(caractere), `U+${(zero + d).toString(16)} devia ser Nd`);
        assert.equal(dobrarAlgarismos(caractere, "x"), String(d));
      }
    }
  });
});

describe("inscricao: prefixo de IP e hmac de rede", () => {
  it("corta IPv4 em /24 e IPv6 em /48", () => {
    assert.equal(prefixoDeIp("192.0.2.33"), "192.0.2.0/24");
    assert.equal(prefixoDeIp("192.0.2.1"), prefixoDeIp("192.0.2.254"));
    assert.equal(prefixoDeIp("2001:db8:1:2:3:4:5:6"), "2001:db8:1::/48");
  });

  it("um endereco abreviado e o proprio prefixo", () => {
    // Cortar ao terceiro grupo de um `::` dava prefixos diferentes para o mesmo
    // bloco, porque o `::` esconde quantos grupos ha.
    assert.equal(prefixoDeIp("2001:db8::1"), "2001:db8::1/48");
  });

  it("o que nao se percebe da null, e nao um balde inventado", () => {
    for (const mau of ["", "   ", "nao-e-ip", "999.1.1.1", "192.0.2", 42, null, undefined]) {
      assert.equal(prefixoDeIp(mau), null, JSON.stringify(mau));
    }
  });

  it("dois clientes da mesma rede caem no mesmo hmac, e de outra rede nao", () => {
    const um = hmacDe(CHAVE, DOMINIOS.rede, prefixoDeIp("192.0.2.9") ?? "").toString("hex");
    const vizinho = hmacDe(CHAVE, DOMINIOS.rede, prefixoDeIp("192.0.2.200") ?? "").toString("hex");
    const outra = hmacDe(CHAVE, DOMINIOS.rede, prefixoDeIp("198.51.100.9") ?? "").toString("hex");
    assert.equal(um, vizinho);
    assert.notEqual(um, outra);
  });
});

describe("inscricao: anel do pepper", () => {
  it("reconhece um hmac escrito antes de uma rotacao", () => {
    const antigo = new Nif(NIF, OUTRA_CHAVE).hmac;
    assert.equal(hmacCorresponde(antigo, DOMINIOS.nif, NIF, [CHAVE, OUTRA_CHAVE]), true);
    assert.equal(hmacCorresponde(antigo, DOMINIOS.nif, NIF, [CHAVE, null]), false);
  });

  it("recusa um hmac deformado sem olhar para o anel", () => {
    for (const mau of ["", "zz", "A".repeat(64), "0".repeat(63)]) {
      assert.equal(hmacCorresponde(mau, DOMINIOS.nif, NIF, [CHAVE, OUTRA_CHAVE]), false);
    }
  });
});

describe("inscricao: texto e e-mail", () => {
  it("o texto perde caracteres de controlo e respeita o tecto", () => {
    assert.equal(normalizarTexto("  Loja\u0000 do\tbairro  ", "nome"), "Loja  do bairro");
    assert.throws(() => normalizarTexto("x".repeat(CARACTERES_DE_TEXTO + 1), "nome"), IdentificadorInvalidoError);
    assert.throws(() => normalizarTexto("   ", "nome"), IdentificadorInvalidoError);
    assert.throws(() => normalizarTexto(42, "nome"), IdentificadorInvalidoError);
  });

  it("o e-mail e opaco e normaliza para minusculas", () => {
    const email = new Email("  Dono@Exemplo.AO ");
    assert.equal(email.revelar(), "dono@exemplo.ao");
    assert.equal(`${email}`, MASCARA);
    assert.equal(normalizarEmail("a@b.co"), "a@b.co");
    for (const mau of ["", "sem-arroba", "a@b", "a b@c.co", `${"x".repeat(120)}@b.co`]) {
      assert.throws(() => normalizarEmail(mau), IdentificadorInvalidoError, JSON.stringify(mau));
    }
  });
});

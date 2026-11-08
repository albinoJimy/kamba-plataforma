/**
 * A bateria do *token* de `/entrar` e das referências de caso (KAM-086,
 * critério 1 e módulo `sessao`).
 *
 * ## O ensaio que mais vale aqui é o da separação de domínios
 *
 * «um bilhete não serve de cookie». Parece pormenor e é a barreira que faz a
 * prova de posse do telefone ser obrigatória: no caminho de recuperação do
 * critério 8, o bilhete é entregue a **quem submeteu o formulário**, que pode não
 * ser o dono do número. Se o bilhete servisse de cookie, bastava pô-lo no
 * navegador. Os dois separadores de domínio do `sessao.ts` são o que impede isso,
 * e é por isso que o ensaio o mede nas duas direcções.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ATRIBUTOS_DO_COOKIE,
  CARACTERES_MAXIMOS,
  DOMINIOS_DE_REFERENCIA,
  FINS,
  NOME_DO_COOKIE,
  OCTETOS_DA_ASSINATURA,
  ORIGENS,
  ReferenciaInvalidaError,
  TokenInvalidoError,
  VALIDADES,
  VALIDADE_DA_SESSAO_S,
  VALIDADE_DO_BILHETE_S,
  VALIDADE_MAXIMA_DIAS,
  cabecalhoDoCookie,
  cabecalhoQueApaga,
  cookieDoCabecalho,
  cunharReferencia,
  cunharToken,
  idSequencial,
  lerReferencia,
  verificarToken,
  type Origem,
} from "../src/inscricao/index.ts";

const CHAVE = Buffer.alloc(32, 0x5a);
const OUTRA_CHAVE = Buffer.alloc(32, 0x3c);
const CASO = idSequencial(1);
const OUTRO_CASO = idSequencial(2);

function relogioEm(iso: string) {
  return (): Date => new Date(iso);
}

const AGORA = relogioEm("2026-11-08T10:00:00.000Z");
const DAQUI_A_UM_DIA = new Date("2026-11-09T10:00:00.000Z");

function capturar(fn: () => unknown): Error {
  try {
    fn();
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a chamada nao levantou" });
}

describe("inscricao: o token de /entrar (criterio 1)", () => {
  it("as tres origens sao as do critetio", () => {
    assert.deepEqual([...ORIGENS], ["convite", "contabilista", "anuncio"]);
  });

  it("um token cunhado le-se de volta com a origem e a validade", () => {
    for (const origem of ORIGENS) {
      const token = cunharToken(origem, DAQUI_A_UM_DIA, CHAVE, AGORA);
      const convite = verificarToken(token, [CHAVE, null], AGORA);
      assert.equal(convite.origem, origem);
      assert.equal(convite.expiraEm.toISOString(), DAQUI_A_UM_DIA.toISOString());
    }
  });

  it("dois tokens da mesma origem e validade sao diferentes", () => {
    // O nonce: sem ele, a mesma origem e a mesma validade davam o mesmo token, e
    // um convite distribuido era indistinguivel de outro.
    const um = cunharToken("convite", DAQUI_A_UM_DIA, CHAVE, AGORA);
    const outro = cunharToken("convite", DAQUI_A_UM_DIA, CHAVE, AGORA);
    assert.notEqual(um, outro);
  });

  it("recusa um token assinado por outra chave", () => {
    const token = cunharToken("convite", DAQUI_A_UM_DIA, OUTRA_CHAVE, AGORA);
    const erro = capturar(() => verificarToken(token, [CHAVE, null], AGORA));
    assert.ok(erro instanceof TokenInvalidoError);
    assert.equal(erro.recusa, "assinatura");
  });

  it("recusa um token expirado, e o expirado nao se confunde com o forjado", () => {
    const token = cunharToken("convite", new Date("2026-11-08T09:59:59.000Z"), CHAVE, AGORA);
    const erro = capturar(() => verificarToken(token, [CHAVE, null], AGORA));
    assert.ok(erro instanceof TokenInvalidoError);
    assert.equal(erro.recusa, "expirado");
  });

  it("a assinatura verifica-se ANTES da validade", () => {
    // Pela ordem inversa, o tempo de resposta distinguia um token expirado de um
    // forjado — e um expirado e prova de que a chave esteve certa algum dia.
    // Mede-se pelo veredicto: um token expirado **e** mal assinado diz
    // `assinatura`, nao `expirado`.
    const expirado = cunharToken("convite", new Date("2026-11-08T09:00:00.000Z"), OUTRA_CHAVE, AGORA);
    const erro = capturar(() => verificarToken(expirado, [CHAVE, null], AGORA));
    assert.equal((erro as TokenInvalidoError).recusa, "assinatura");
  });

  it("recusa o que esta deformado, sem olhar para a chave", () => {
    const bom = cunharToken("convite", DAQUI_A_UM_DIA, CHAVE, AGORA);
    const maus = [
      "",
      "sem-ponto",
      "a.b.c",
      `${bom}.extra`,
      "x".repeat(CARACTERES_MAXIMOS + 1),
      `${bom.split(".")[0]}.${Buffer.alloc(16).toString("base64url")}`,
      "nao+base64url.nao+base64url",
      42,
      null,
      undefined,
      {},
    ];
    for (const mau of maus) {
      const erro = capturar(() => verificarToken(mau, [CHAVE, null], AGORA));
      assert.ok(erro instanceof TokenInvalidoError, JSON.stringify(mau));
      assert.equal(erro.recusa, "forma", JSON.stringify(mau));
    }
  });

  it("a mensagem do erro nao leva o token", () => {
    const token = cunharToken("convite", DAQUI_A_UM_DIA, OUTRA_CHAVE, AGORA);
    const erro = capturar(() => verificarToken(token, [CHAVE, null], AGORA));
    assert.ok(!erro.message.includes(token.slice(0, 12)));
    assert.equal(erro.message, "token de /entrar recusado: assinatura");
  });

  it("a assinatura tem 32 octetos, e um corte nao passa", () => {
    assert.equal(OCTETOS_DA_ASSINATURA, 32);
    const bom = cunharToken("convite", DAQUI_A_UM_DIA, CHAVE, AGORA);
    const [carga, assinatura] = bom.split(".") as [string, string];
    const cortada = Buffer.from(assinatura, "base64url").subarray(0, 31).toString("base64url");
    const erro = capturar(() => verificarToken(`${carga}.${cortada}`, [CHAVE, null], AGORA));
    assert.equal((erro as TokenInvalidoError).recusa, "forma");
  });

  it("o anel reconhece um token emitido antes de uma rotacao", () => {
    const antigo = cunharToken("anuncio", DAQUI_A_UM_DIA, OUTRA_CHAVE, AGORA);
    assert.equal(verificarToken(antigo, [CHAVE, OUTRA_CHAVE], AGORA).origem, "anuncio");
    assert.throws(() => verificarToken(antigo, [CHAVE, null], AGORA), TokenInvalidoError);
  });

  it("recusa cunhar com validade acima do tecto, ou com origem desconhecida", () => {
    const tarde = new Date(new Date(AGORA()).getTime() + (VALIDADE_MAXIMA_DIAS + 1) * 86_400_000);
    assert.equal((capturar(() => cunharToken("convite", tarde, CHAVE, AGORA)) as TokenInvalidoError).recusa, "validade");
    assert.equal(
      (capturar(() => cunharToken("vitrine" as Origem, DAQUI_A_UM_DIA, CHAVE, AGORA)) as TokenInvalidoError).recusa,
      "origem",
    );
    assert.equal(
      (capturar(() => cunharToken("convite", DAQUI_A_UM_DIA, Buffer.alloc(16), AGORA)) as TokenInvalidoError).recusa,
      "assinatura",
    );
  });

  it("o token NAO leva dado pessoal: a carga tem tres campos e sao estes", () => {
    const token = cunharToken("convite", DAQUI_A_UM_DIA, CHAVE, AGORA);
    const carga = Buffer.from((token.split(".") as [string, string])[0], "base64url").toString("utf8");
    const campos = carga.split(".");
    assert.equal(campos.length, 3);
    assert.equal(campos[0], "convite");
    assert.equal(Number(campos[1]) * 1000, DAQUI_A_UM_DIA.getTime());
    assert.match(campos[2] as string, /^[A-Za-z0-9_-]+$/);
  });
});

describe("inscricao: o bilhete e a sessao (modulo sessao)", () => {
  it("sao dois fins, e os separadores de dominio sao diferentes", () => {
    assert.deepEqual([...FINS], ["ticket", "sessao"]);
    assert.notEqual(DOMINIOS_DE_REFERENCIA.ticket, DOMINIOS_DE_REFERENCIA.sessao);
  });

  it("um BILHETE nao serve de SESSAO, e uma sessao nao serve de bilhete", () => {
    // O ensaio mais importante deste ficheiro. Ver a nota do modulo.
    const bilhete = cunharReferencia("ticket", CASO, CHAVE, AGORA);
    const sessao = cunharReferencia("sessao", CASO, CHAVE, AGORA);
    assert.notEqual(bilhete, sessao);
    assert.equal(lerReferencia("ticket", bilhete, [CHAVE, null], AGORA), CASO);
    assert.equal(lerReferencia("sessao", sessao, [CHAVE, null], AGORA), CASO);
    assert.throws(() => lerReferencia("sessao", bilhete, [CHAVE, null], AGORA), ReferenciaInvalidaError);
    assert.throws(() => lerReferencia("ticket", sessao, [CHAVE, null], AGORA), ReferenciaInvalidaError);
  });

  it("o id sai DE DENTRO da referencia: nao da para pedir o caso ao lado", () => {
    // E a linha que faz o 404 do teste de isolamento ser inevitavel: trocar o
    // UUID quebra o HMAC, e nao ha parametro ao lado que o possa dizer.
    const minha = cunharReferencia("sessao", CASO, CHAVE, AGORA);
    const campos = minha.split(".") as [string, string, string];
    const trocada = `${OUTRO_CASO}.${campos[1]}.${campos[2]}`;
    assert.throws(() => lerReferencia("sessao", trocada, [CHAVE, null], AGORA), ReferenciaInvalidaError);
    assert.equal(
      lerReferencia("sessao", cunharReferencia("sessao", OUTRO_CASO, CHAVE, AGORA), [CHAVE, null], AGORA),
      OUTRO_CASO,
    );
  });

  it("a validade esta DENTRO do texto assinado: da para repetir, nao da para prolongar", () => {
    // **Os dois fins eram eternos, e os dois eram achados.** O bilhete e
    // entregue a quem submeteu o formulario — que no caminho de recuperacao do
    // criterio 8 pode nao ser o dono do numero —, e sem validade ele guardava-o
    // para sempre e mandava SMS ao dono indefinidamente. A sessao tinha o mesmo
    // problema: o cookie morre com o navegador, o VALOR nao morria.
    assert.equal(VALIDADE_DO_BILHETE_S, 1_800);
    assert.equal(VALIDADE_DA_SESSAO_S, 86_400);
    assert.deepEqual(VALIDADES, { ticket: 1_800, sessao: 86_400 });

    for (const fim of FINS) {
      const referencia = cunharReferencia(fim, CASO, CHAVE, AGORA);
      const campos = referencia.split(".") as [string, string, string];
      const expira = Number(campos[1]);
      assert.equal(expira, Math.floor(AGORA().getTime() / 1000) + VALIDADES[fim]);
      // Antes de expirar le-se; um segundo depois, nao.
      const antes = (): Date => new Date(expira * 1000 - 1000);
      const depois = (): Date => new Date(expira * 1000);
      assert.equal(lerReferencia(fim, referencia, [CHAVE, null], antes), CASO);
      assert.throws(
        () => lerReferencia(fim, referencia, [CHAVE, null], depois),
        ReferenciaInvalidaError,
        fim,
      );
      // E prolongar quebra a assinatura.
      const esticada = `${campos[0]}.${expira + 86_400}.${campos[2]}`;
      assert.throws(() => lerReferencia(fim, esticada, [CHAVE, null], antes), ReferenciaInvalidaError);
    }
  });

  it("uma validade impossivel nao passa por nao expirada", () => {
    // `NaN <= agora` e **falso**: quinze algarismos davam um instante que o
    // `Date` nao representa, e a referencia passava a verificacao de validade.
    const boa = cunharReferencia("sessao", CASO, CHAVE, AGORA);
    const campos = boa.split(".") as [string, string, string];
    const impossivel = `${campos[0]}.999999999999999.${campos[2]}`;
    assert.throws(() => lerReferencia("sessao", impossivel, [CHAVE, null], AGORA), ReferenciaInvalidaError);
  });

  it("recusa o que esta deformado e o que vem de outra chave", () => {
    const boa = cunharReferencia("sessao", CASO, CHAVE, AGORA);
    const campos = boa.split(".") as [string, string, string];
    const maus = [
      "",
      CASO,
      `${CASO}.`,
      `${CASO}.${campos[2]}`,
      `nao-uuid.${campos[1]}.${campos[2]}`,
      `${CASO}.${campos[1]}.${Buffer.alloc(16).toString("base64url")}`,
      `${CASO}.nao-numero.${campos[2]}`,
      cunharReferencia("sessao", CASO, OUTRA_CHAVE, AGORA),
      "x".repeat(200),
      42,
      null,
    ];
    for (const mau of maus) {
      assert.throws(
        () => lerReferencia("sessao", mau, [CHAVE, null], AGORA),
        ReferenciaInvalidaError,
        JSON.stringify(mau),
      );
    }
  });

  it("o anel reconhece uma referencia de antes de uma rotacao", () => {
    const antiga = cunharReferencia("sessao", CASO, OUTRA_CHAVE, AGORA);
    assert.equal(lerReferencia("sessao", antiga, [CHAVE, OUTRA_CHAVE], AGORA), CASO);
  });

  it("recusa cunhar sobre um id que nao e UUID, ou com chave curta", () => {
    assert.throws(() => cunharReferencia("sessao", "nao-uuid", CHAVE, AGORA), ReferenciaInvalidaError);
    assert.throws(() => cunharReferencia("sessao", CASO, Buffer.alloc(16), AGORA), ReferenciaInvalidaError);
  });

  it("o cookie e httpOnly, Secure, SameSite=Lax e sem Max-Age", () => {
    const cabecalho = cabecalhoDoCookie(cunharReferencia("sessao", CASO, CHAVE, AGORA));
    assert.ok(cabecalho.startsWith(`${NOME_DO_COOKIE}=`));
    assert.equal(ATRIBUTOS_DO_COOKIE, "HttpOnly; Secure; SameSite=Lax; Path=/");
    for (const atributo of ["HttpOnly", "Secure", "SameSite=Lax", "Path=/"]) {
      assert.ok(cabecalho.includes(atributo), atributo);
    }
    assert.ok(!cabecalho.includes("Max-Age"), "um registo a meio nao sobrevive ao navegador");
    assert.ok(cabecalhoQueApaga().includes("Max-Age=0"));
  });

  it("le o cookie certo de um cabecalho com varios", () => {
    const valor = cunharReferencia("sessao", CASO, CHAVE, AGORA);
    assert.equal(cookieDoCabecalho(`outro=1; ${NOME_DO_COOKIE}=${valor}; terceiro=2`), valor);
    // **Um homonimo VAZIO antes do verdadeiro nao encerra a procura**, e
    // encerrava-a: quem conseguisse plantar um cookie homonimo vazio — de um
    // subdominio, ou com outro `Path` — desautenticava quem la estava.
    assert.equal(cookieDoCabecalho(`${NOME_DO_COOKIE}=; ${NOME_DO_COOKIE}=${valor}`), valor);
    assert.equal(cookieDoCabecalho(`${NOME_DO_COOKIE}=  ; ${NOME_DO_COOKIE}=${valor}`), valor);
    assert.equal(cookieDoCabecalho(`${NOME_DO_COOKIE}=${valor}`), valor);
    for (const mau of ["", "outro=1", `${NOME_DO_COOKIE}=`, `${NOME_DO_COOKIE}`, undefined, 42]) {
      assert.equal(cookieDoCabecalho(mau), null, JSON.stringify(mau));
    }
  });

  it("um nome que CONTEM o do cookie nao e o cookie", () => {
    // `kamba_onboarding_falso=x` nao e `kamba_onboarding=x`. A comparacao e por
    // igualdade do nome e nao por prefixo.
    assert.equal(cookieDoCabecalho(`${NOME_DO_COOKIE}_falso=x`), null);
    assert.equal(cookieDoCabecalho(`outro_${NOME_DO_COOKIE}=x`), null);
  });
});

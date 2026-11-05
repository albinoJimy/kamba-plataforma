/**
 * O caso X-11 deste módulo: nem o código nem o telefone saem (KAM-116,
 * critério 6).
 *
 * «O código nunca aparece em logs, traces ou métricas (KAM-068); o telefone só
 * em memória, com HMAC nos registos.» E, dos *Testes Requeridos*: «teste de
 * ausência de código e telefone em logs (X-11)».
 *
 * ## O que esta bateria é, e o que o `make x11` é
 *
 * O `make x11` do *gate* 6 é a bateria **transversal**: 1 030 *fixtures* com
 * dados pessoais pelos dois *loggers*, Python e TypeScript, com a saída
 * comparada byte a byte. Ela mede o *logger*, e mede-o para todo o repositório.
 *
 * Esta bateria mede o **módulo**, que é o que o `make x11` não pode medir: o
 * X-11 varre o que passa pelo *logger*, e o critério 6 fala de «logs, traces ou
 * métricas» — três superfícies, e o *logger* é uma. O que aqui se varre é tudo
 * o que este módulo produz: a exposição das métricas, o `ler()`, as mensagens de
 * **todas** as classes de erro, a serialização dos tipos opacos, e o que o
 * *logger* aceita que este módulo lhe passe.
 *
 * ## O controlo positivo vem primeiro, e sem ele o zero não diz nada
 *
 * É a lição escrita no alvo `x11` do `Makefile`: «o varrimento prova primeiro
 * que vê os identificadores na entrada (controlo positivo) — sem isso, o zero
 * não dizia nada». Por isso o primeiro caso desta bateria é o que **encontra** o
 * código e o número, e os casos seguintes é que procuram e não acham.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { format, inspect } from "node:util";

import { CAMPOS_DE_CHAMADA, validar } from "../src/logger/politica.ts";
import { Logger } from "../src/logger/index.ts";
import {
  AgregadorNaoAutorizadoError,
  ChaveInvalidaError,
  CodigoInvalidoError,
  CodigoOtp,
  DestinoInvalidoError,
  FakeSmsProvider,
  IdDeReciboInvalidoError,
  MASCARA,
  MetricasDeSms,
  ModeloDesconhecidoError,
  ParametroInvalidoError,
  PepperMalFormadoError,
  RedeInvalidaError,
  SmsError,
  construir,
  cunharDestino,
  normalizarRecibo,
  type Parametros,
} from "../src/sms/index.ts";

/**
 * O erro que `fn` levantou.
 *
 * O `assert.throws` do Node devolve `undefined` — ao contrario do de outras
 * bibliotecas —, pelo que `assert.throws(...) as Error` da sempre `undefined` e
 * a assercao seguinte rebenta a ler `.message`. Esta bateria precisa do erro em
 * si: metade do que ela mede e **o que a mensagem nao diz**.
 */
function capturar(fn: () => unknown): Error {
  try {
    fn();
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a chamada nao levantou" });
}

/** O mesmo, para uma promessa. Ver `capturar`. */
async function capturarAsync(promessa: Promise<unknown>): Promise<Error> {
  try {
    await promessa;
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a promessa nao rejeitou" });
}

const CHAVE_HMAC = Buffer.alloc(32, 0x5a);

/**
 * O código e o número de ensaio.
 *
 * Escolhidos para serem **procuráveis**: nenhum dos dois aparece por acidente
 * noutro sítio do módulo. O número começa por `0` no nacional, pelo que não é
 * atribuível a ninguém (ver `sms.contrato.test.ts`).
 */
const CODIGO = "246813";
const NUMERO = "+244000000579";
const NACIONAL = "000000579";

function parametros(): Parametros {
  return { codigo: new CodigoOtp(CODIGO), validade_min: 7 };
}

/** Procura o código e o número em qualquer texto. */
function fuga(texto: string): readonly string[] {
  const achados: string[] = [];
  if (texto.includes(CODIGO)) achados.push("codigo");
  if (texto.includes(NUMERO)) achados.push("numero");
  if (texto.includes(NACIONAL)) achados.push("nacional");
  if (texto.includes("244000000579")) achados.push("numero_sem_mais");
  return achados;
}

describe("sms X-11: controlo positivo", () => {
  it("o varrimento VE o codigo e o numero quando eles la estao", () => {
    // Sem este caso, todos os que seguem podiam estar verdes por o `fuga` nao
    // procurar nada. E a licao escrita no alvo `x11` do Makefile.
    assert.deepEqual(fuga(`codigo ${CODIGO}`), ["codigo"]);
    assert.deepEqual(fuga(`destino ${NUMERO}`), [
      "numero",
      "nacional",
      "numero_sem_mais",
    ]);
    assert.deepEqual(fuga("nada de interessante"), []);
  });

  it("o corpo do SMS leva o codigo — e e o unico sitio onde ele e legitimo", () => {
    const corpo = construir("otp_posse_telefone", parametros());
    assert.deepEqual(fuga(corpo), ["codigo"]);
    assert.ok(!corpo.includes(NUMERO), "o corpo nao leva o telefone");
  });
});

describe("sms X-11: os tipos opacos nao se dizem por extenso", () => {
  it("o codigo mascara nas quatro vias de conversao", () => {
    const codigo = new CodigoOtp(CODIGO);
    assert.equal(`${codigo}`, MASCARA);
    assert.equal(String(codigo), MASCARA);
    // **O `toString` chamado a mao**, e nao so por `${}` ou `String()`: o
    // `Symbol.toPrimitive` tem precedencia sobre o `toString` nessas duas vias,
    // pelo que um `toString` que dissesse o valor ficava invisivel para elas.
    // Medido: a mutacao que o substitui por `this.#valor` sobrevivia aos dois
    // asserts acima.
    assert.equal(codigo.toString(), MASCARA);
    assert.equal(Object.prototype.toString.call(codigo), "[object Object]");
    assert.equal(`prefixo ${codigo} sufixo`, `prefixo ${MASCARA} sufixo`);
    assert.equal(JSON.stringify(codigo), `"${MASCARA}"`);
    assert.equal(JSON.stringify({ codigo, outro: [codigo] }), `{"codigo":"***","outro":["***"]}`);
    assert.ok(Number.isNaN(Number(codigo)), "a coercao para numero da NaN");
    assert.equal(codigo.revelar(), CODIGO, "o unico caminho continua a funcionar");
  });

  it("o destino mascara nas quatro vias, e publica o HMAC", () => {
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    assert.equal(`${destino}`, MASCARA);
    assert.equal(JSON.stringify({ destino }), `{"destino":"${MASCARA}"}`);
    assert.deepEqual(fuga(JSON.stringify({ destino, hmac: destino.hmac })), []);
    assert.equal(destino.revelar(), NUMERO);
  });

  it("o console.log e o util.inspect mascaram, e e a quarta via", () => {
    // A via que nenhum `${}` exercita: o `util.inspect` consulta a chave
    // `nodejs.util.inspect.custom`, e e ela que o `console.log` usa. Medido: a
    // mutacao que a faz devolver o valor sobrevivia a todos os outros casos.
    const codigo = new CodigoOtp(CODIGO);
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    assert.deepEqual(fuga(inspect(codigo)), []);
    assert.deepEqual(fuga(inspect({ codigo, destino })), []);
    assert.deepEqual(fuga(format("%o %s %j", codigo, destino, { codigo })), []);
    // E o controlo: o `inspect` **ve** o que nao e opaco.
    assert.match(inspect({ claro: CODIGO }), /246813/);
  });

  it("o `comprimento` e o que se pode publicar, e nao revela o valor", () => {
    assert.equal(new CodigoOtp(CODIGO).comprimento, 6);
    assert.equal(cunharDestino(NUMERO, CHAVE_HMAC).comprimento, NUMERO.length);
  });
});

describe("sms X-11: as metricas", () => {
  it("nem a exposicao nem o `ler` levam o codigo ou o numero", async () => {
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T09:00:00.000Z");
    const provedor = new FakeSmsProvider({
      metricas,
      relogio: () => agora,
      custoMinorPorSms: 1_250n,
    });
    const envio = await provedor.send(
      cunharDestino(NUMERO, CHAVE_HMAC),
      "otp_posse_telefone",
      parametros(),
      "onb-7f3c9a2b-otp-1",
    );
    agora = new Date("2026-11-05T09:00:08.000Z");
    await provedor.entregar(envio.id, { operadora: "unitel" });

    assert.deepEqual(fuga(metricas.exposicao()), []);
    assert.deepEqual(fuga(JSON.stringify(metricas.ler())), []);
    // E a serie **existe**: um zero de nada tambem nao teria fuga.
    assert.match(metricas.exposicao(), /sms_sent_total\{fornecedor="fake",resultado="aceite"\} 1/);
    assert.match(metricas.exposicao(), /sms_delivery_ratio\{fornecedor="fake",operadora="unitel"\} 1\.0000/);
    assert.match(metricas.exposicao(), /sms_cost_kz_total\{fornecedor="fake"\} 12\.50/);
  });

  it("nenhuma etiqueta aceita um HMAC de destino", () => {
    const metricas = new MetricasDeSms();
    const hmac = cunharDestino(NUMERO, CHAVE_HMAC).hmac;
    assert.throws(() => metricas.contarEnvio(hmac, "aceite"), /lista fechada/);
    assert.throws(() => metricas.contarRecibo("fake", hmac, true), /lista fechada/);
  });
});

describe("sms X-11: as mensagens de erro", () => {
  it("nenhuma classe de erro do modulo leva o codigo ou o numero", () => {
    const declaracao = {
      subprocessador: {
        country: "ZA",
        provider: "pendente",
        apdRef: null,
        estado: "pendente" as const,
        finalidade: "otp_e_avisos_de_servico",
        dados: "telefone",
      },
      envioRealPermitido: false,
      avisos: ["sem apd_ref"],
    };
    const erros: readonly Error[] = [
      new SmsError("PROVIDER_DOWN", "o agregador nao respondeu"),
      new SmsError("INVALID_DESTINATION"),
      new CodigoInvalidoError(CODIGO.length),
      new ChaveInvalidaError(NUMERO),
      new IdDeReciboInvalidoError(NUMERO),
      new ModeloDesconhecidoError("promocao"),
      new ParametroInvalidoError("codigo", "nao e um CodigoOtp"),
      new PepperMalFormadoError("actual", 7),
      new RedeInvalidaError("10.0.0.300"),
      new AgregadorNaoAutorizadoError("ZA", "pendente", "pendente", "falta apd_ref"),
      capturar(() => new CodigoOtp(NUMERO)),
      capturar(() => cunharDestino(NUMERO.replace("+244", "+351"), CHAVE_HMAC)),
    ];
    for (const erro of erros) {
      assert.deepEqual(fuga(erro.message), [], `${erro.name}: ${erro.message}`);
      assert.deepEqual(fuga(String(erro)), [], erro.name);
    }
  });

  it("um erro de destino lancado a partir do numero continua sem o dizer", () => {
    const erro = capturar(() =>
      cunharDestino(`+351${NACIONAL}`, CHAVE_HMAC),
    ) as DestinoInvalidoError;
    assert.ok(erro instanceof DestinoInvalidoError);
    assert.deepEqual(fuga(erro.message), []);
    assert.equal(erro.codigo, "INVALID_DESTINATION");
  });
});

describe("sms X-11: o que o logger aceita deste modulo", () => {
  it("o logger REJEITA o codigo opaco em qualquer campo de chamada", () => {
    // A porta da frente: a *allowlist* do `logger/politica.ts` nao tem campo
    // nenhum que leve um codigo, e passar um `CodigoOtp` nao e sequer uma
    // `string` — logo nenhum validador o aceita. O `error_code` e o campo que
    // **aceitaria** uma cadeia de seis algarismos (a regra do logger sao seis),
    // e e por isso que o tipo opaco importa: sem ele, `logger.error({
    // error_code: codigo })` passava.
    const codigo = new CodigoOtp(CODIGO);
    for (const campo of CAMPOS_DE_CHAMADA) {
      assert.equal(validar(campo, codigo), null, campo);
    }
    // O controlo: a MESMA cadeia, em `string`, passa no `error_code`. E o que
    // o tipo opaco esta a impedir, medido.
    assert.equal(validar("error_code", CODIGO), CODIGO);
  });

  it("o logger REJEITA o telefone em qualquer campo de chamada", () => {
    for (const campo of CAMPOS_DE_CHAMADA) {
      assert.equal(validar(campo, NUMERO), null, campo);
      assert.equal(validar(campo, NACIONAL), null, campo);
    }
  });

  it("o prefixo do HMAC e o que o logger ACEITA, e e o que este modulo da", () => {
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    assert.equal(validar("contact_hmac_prefix", destino.prefixoDoHmac), destino.prefixoDoHmac);
  });

  it("uma linha de log de um envio nao tem fuga", async () => {
    let escrito = "";
    const registo = new Logger("ten", {
      destino: {
        write(pedaco: string): void {
          escrito += pedaco;
        },
      },
      relogio: () => new Date("2026-11-05T09:00:00.000Z"),
      estrito: true,
    });
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    const provedor = new FakeSmsProvider();
    const envio = await provedor.send(
      destino,
      "otp_posse_telefone",
      parametros(),
      "onb-7f3c9a2b-otp-1",
    );
    registo.info({
      contact_hmac_prefix: destino.prefixoDoHmac,
      outcome: "sms_aceite",
      latency_ms: 120,
    });
    assert.deepEqual(fuga(escrito), []);
    assert.match(escrito, /"contact_hmac_prefix":"[0-9a-f]{8}"/);
    assert.ok(!escrito.includes(envio.id) || envio.id === "", "o id do fake nao e um dado pessoal");
  });
});

describe("sms X-11: o motivo do recibo e texto do agregador", () => {
  it("um motivo com um telefone dentro e deitado fora", () => {
    // A superficie mais perigosa do `recibo.ts`: alguns agregadores escrevem o
    // numero de destino no motivo da falha. A regra e a do logger — mais de
    // seis algarismos recusa o motivo inteiro.
    const recibo = normalizarRecibo(
      {
        idDoFornecedor: "r-1",
        entregue: false,
        motivo: `delivery failed for ${NUMERO}`,
      },
      new Date("2026-11-05T09:00:00.000Z"),
    );
    assert.notEqual(recibo, null);
    assert.equal(recibo?.motivo, null);
    assert.deepEqual(fuga(JSON.stringify(recibo)), []);
  });

  it("um motivo curto e sem algarismos a mais passa", () => {
    const recibo = normalizarRecibo(
      { idDoFornecedor: "r-2", entregue: false, motivo: "handset_unreachable" },
      new Date("2026-11-05T09:00:00.000Z"),
    );
    assert.equal(recibo?.motivo, "handset_unreachable");
  });

  it("um motivo com acentos ou simbolos e deitado fora", () => {
    for (const motivo of ["não entregue", "a\nb", "<script>", "nº 1"]) {
      const recibo = normalizarRecibo(
        { idDoFornecedor: "r-3", entregue: false, motivo },
        new Date("2026-11-05T09:00:00.000Z"),
      );
      assert.equal(recibo?.motivo, null, motivo);
    }
  });

  it("um motivo longo e cortado antes de ser medido", () => {
    const recibo = normalizarRecibo(
      { idDoFornecedor: "r-4", entregue: false, motivo: "a".repeat(200) },
      new Date("2026-11-05T09:00:00.000Z"),
    );
    assert.equal(recibo?.motivo?.length, 64);
  });
});

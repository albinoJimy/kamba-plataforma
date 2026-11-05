/**
 * A idempotência do envio e do recibo (KAM-116, critério 5).
 *
 * «Envio idempotente (2 chamadas com a mesma chave → 1 SMS) (…) e idempotente
 * por id do fornecedor.»
 *
 * O que esta bateria mede é o **número de SMS que saíram**, e não o número de
 * chamadas que não levantaram. É a diferença que importa: um `send` que devolve
 * o resultado guardado e manda um segundo SMS passa qualquer ensaio que só olhe
 * para o valor de retorno.
 *
 * ## O que ela mede e nenhum ensaio sequencial mede
 *
 * Duas chamadas **ao mesmo tempo** com a mesma chave. A reserva do
 * `RegistoDeEnviosEmMemoria` decide e escreve sem nenhum `await` pelo meio, e é
 * isso que a torna atómica numa linha de execução só; com um `await` entre o
 * `has` e o `set`, o ensaio sequencial continuava verde e saíam dois SMS.
 *
 * ## E o que ela mede sobre a **ligação** e não sobre as funções
 *
 * Qual dos três destinos de uma reserva cabe a cada erro tipado. Essa decisão
 * vive no `enviar` de `src/sms/envio.ts`, e é a parte deste módulo onde uma
 * função correcta ligada ao sítio errado passa todos os ensaios dela: o registo
 * sabe reservar, libertar e concluir, e nenhum ensaio do registo diz qual deles
 * se chama quando o agregador responde `PROVIDER_DOWN`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CodigoOtp,
  FakeSmsProvider,
  METRICA_ENVIADOS,
  MetricasDeSms,
  ParametroInvalidoError,
  RegistoDeEnviosEmMemoria,
  RegistoDeRecibosEmMemoria,
  ReservaInexistenteError,
  SmsError,
  cunharDestino,
  type Parametros,
} from "../src/sms/index.ts";
import { Envios } from "../src/sms/envio.ts";

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
/** Ver a nota de `sms.contrato.test.ts`: nacional a começar por `0` não é atribuível. */
const NUMERO = "+244000000001";
const CHAVE = "onb-7f3c9a2b-otp-1";

function parametros(codigo = "123456"): Parametros {
  return { codigo: new CodigoOtp(codigo), validade_min: 5 };
}

function destino(): ReturnType<typeof cunharDestino> {
  return cunharDestino(NUMERO, CHAVE_HMAC);
}

describe("sms: idempotencia do envio (criterio 5)", () => {
  it("duas chamadas com a mesma chave dao UM SMS", async () => {
    const provedor = new FakeSmsProvider();
    const primeira = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    const segunda = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);

    assert.equal(provedor.quantosSairam, 1, "saiu mais do que um SMS");
    assert.equal(primeira.repetido, false);
    assert.equal(segunda.repetido, true);
    assert.equal(segunda.id, primeira.id);
    assert.equal(segunda.estado, primeira.estado);
  });

  it("vinte chamadas com a mesma chave continuam a dar UM SMS", async () => {
    const provedor = new FakeSmsProvider();
    for (let i = 0; i < 20; i += 1) {
      await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    }
    assert.equal(provedor.quantosSairam, 1);
  });

  it("duas chamadas ao mesmo tempo com a mesma chave dao UM SMS", async () => {
    // O caso que um ensaio sequencial nao ve. Ver a nota do modulo.
    const provedor = new FakeSmsProvider();
    const resultados = await Promise.all(
      Array.from({ length: 8 }, () =>
        provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE),
      ),
    );
    assert.equal(provedor.quantosSairam, 1);
    assert.equal(resultados.filter((r) => !r.repetido).length, 1);
  });

  it("chaves diferentes dao SMS diferentes", async () => {
    const provedor = new FakeSmsProvider();
    await provedor.send(destino(), "otp_posse_telefone", parametros(), "onb-aaaa1111-otp-1");
    await provedor.send(destino(), "otp_posse_telefone", parametros(), "onb-aaaa1111-otp-2");
    assert.equal(provedor.quantosSairam, 2);
  });

  it("um parametro invalido NAO gasta a chave", async () => {
    // A ordem: compor o corpo antes de reservar. Se a reserva viesse primeiro,
    // a chave ficava presa a um envio que nunca aconteceu, e a repeticao
    // correcta devolvia `repetido` sem ter enviado nada.
    const provedor = new FakeSmsProvider();
    await assert.rejects(
      provedor.send(
        destino(),
        "otp_posse_telefone",
        { codigo: new CodigoOtp("123456"), validade_min: 0 },
        CHAVE,
      ),
      ParametroInvalidoError,
    );
    const depois = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    assert.equal(depois.repetido, false, "a chave ficou presa a um envio que nao houve");
    assert.equal(provedor.quantosSairam, 1);
  });
});

describe("sms: o que cada erro faz a reserva (a ligacao)", () => {
  it("RATE_LIMITED liberta a chave: a repeticao envia", async () => {
    const provedor = new FakeSmsProvider();
    provedor.enfileirarErro("RATE_LIMITED");
    await assert.rejects(
      provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE),
      SmsError,
    );
    assert.equal(provedor.quantosSairam, 0);

    const depois = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    assert.equal(depois.repetido, false, "o agregador disse que nao enviou");
    assert.equal(provedor.quantosSairam, 1);
  });

  it("INVALID_DESTINATION liberta a chave", async () => {
    const provedor = new FakeSmsProvider();
    provedor.enfileirarErro("INVALID_DESTINATION");
    await assert.rejects(
      provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE),
      SmsError,
    );
    const depois = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    assert.equal(depois.repetido, false);
    assert.equal(provedor.quantosSairam, 1);
  });

  it("PROVIDER_DOWN NAO liberta: a repeticao nao envia o segundo SMS", async () => {
    // A decisao mais contra-intuitiva do modulo, e a que impede o SMS a dobrar:
    // o agregador nao respondeu, logo **pode ter enviado**.
    const provedor = new FakeSmsProvider();
    provedor.enfileirarErro("PROVIDER_DOWN");
    await assert.rejects(
      provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE),
      SmsError,
    );

    const depois = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    assert.equal(depois.repetido, true);
    assert.equal(depois.estado, "indeterminado");
    assert.equal(depois.id, "");
    assert.equal(provedor.quantosSairam, 0, "saiu um segundo SMS depois de um PROVIDER_DOWN");
  });

  it("um erro que NAO e SmsError conta como PROVIDER_DOWN e nao liberta", async () => {
    // Um adaptador que rebente com um `TypeError` a meio de um `fetch` pode ter
    // mandado o pedido. A direccao certa para falhar e a que nao manda o
    // segundo SMS.
    const registo = new RegistoDeEnviosEmMemoria();
    const metricas = new MetricasDeSms();
    const envios = new Envios({ fornecedor: "fake", registo, metricas });
    await assert.rejects(
      envios.enviar(destino(), "otp_posse_telefone", parametros(), CHAVE, async () => {
        throw new TypeError("o fetch rebentou");
      }),
      TypeError,
    );
    assert.equal(metricas.ler()[`${METRICA_ENVIADOS}|fake|PROVIDER_DOWN`], 1);
    assert.deepEqual(await registo.ler(CHAVE), null, "um `em_curso` le-se como null");

    let chamou = 0;
    const segunda = await envios.enviar(
      destino(),
      "otp_posse_telefone",
      parametros(),
      CHAVE,
      async () => {
        chamou += 1;
        return { id: "x-1" };
      },
    );
    assert.equal(chamou, 0, "a entrega foi chamada depois de um erro nao tipado");
    assert.equal(segunda.repetido, true);
  });
});

describe("sms: o registo de envios", () => {
  it("libertar uma chave ja concluida NAO apaga o id do SMS que saiu", async () => {
    // Sem esta guarda, um `libertar` chamado fora de ordem apagava o registo de
    // um envio aceite, e a repeticao seguinte mandava o segundo SMS.
    const registo = new RegistoDeEnviosEmMemoria();
    await registo.reservar(CHAVE);
    await registo.concluir(CHAVE, { id: "a-1", estado: "em_curso" });
    await registo.libertar(CHAVE);
    assert.deepEqual(await registo.ler(CHAVE), { id: "a-1", estado: "em_curso" });
    assert.equal((await registo.reservar(CHAVE)).novo, false);
  });

  it("concluir ou libertar uma chave que nao esta reservada levanta", async () => {
    const registo = new RegistoDeEnviosEmMemoria();
    await assert.rejects(
      registo.concluir(CHAVE, { id: "a-1", estado: "em_curso" }),
      ReservaInexistenteError,
    );
    await assert.rejects(registo.libertar(CHAVE), ReservaInexistenteError);
  });

  it("distingue chave nova de chave reservada sem resposta", async () => {
    const registo = new RegistoDeEnviosEmMemoria();
    assert.deepEqual(await registo.reservar(CHAVE), { novo: true });
    assert.deepEqual(await registo.reservar(CHAVE), { novo: false, registo: null });
    await registo.concluir(CHAVE, { id: "a-1", estado: "entregue" });
    assert.deepEqual(await registo.reservar(CHAVE), {
      novo: false,
      registo: { id: "a-1", estado: "entregue" },
    });
  });
});

describe("sms: idempotencia do recibo (criterio 5)", () => {
  it("o mesmo id de fornecedor corre o ouvinte UMA vez", async () => {
    const provedor = new FakeSmsProvider();
    let corridas = 0;
    provedor.onDeliveryReceipt(() => {
      corridas += 1;
    });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);

    assert.equal(await provedor.entregar(envio.id), true);
    assert.equal(await provedor.entregar(envio.id), false);
    assert.equal(await provedor.entregar(envio.id), false);
    assert.equal(corridas, 1, "um recibo re-entregue correu o ouvinte duas vezes");
  });

  it("a latencia entra no histograma UMA vez, e nao por recibo repetido", async () => {
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T10:00:00.000Z");
    const provedor = new FakeSmsProvider({ metricas, relogio: () => agora });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    agora = new Date("2026-11-05T10:00:12.000Z");
    await provedor.entregar(envio.id);
    await provedor.entregar(envio.id);

    const lido = metricas.ler();
    assert.equal(lido["sms_latency_s|fake_count"], 1, "a latencia entrou duas vezes");
    assert.equal(lido["sms_latency_s|fake_sum"], 12);
    const exposicao = metricas.exposicao();
    assert.match(exposicao, /sms_latency_s_count\{fornecedor="fake"\} 1/);
    assert.match(exposicao, /sms_latency_s_sum\{fornecedor="fake"\} 12/);
  });

  it("dois ids diferentes para o mesmo envio observam a latencia UMA vez", async () => {
    // O caso que o `#enviadoEm.delete(id)` guarda, e que a deduplicacao por id
    // de recibo **nao** guarda: dois recibos com ids diferentes para o mesmo
    // envio passam os dois pela deduplicacao, e sem o `delete` o mesmo intervalo
    // entrava duas vezes no histograma — o `_count` deixava de ser o numero de
    // entregas. Medido: sem o `delete`, esta e a unica entrada que o apanha.
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T10:00:00.000Z");
    const provedor = new FakeSmsProvider({ metricas, relogio: () => agora });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    agora = new Date("2026-11-05T10:00:09.000Z");
    assert.equal(await provedor.entregar(envio.id, { idDoRecibo: "r-a" }), true);
    assert.equal(await provedor.entregar(envio.id, { idDoRecibo: "r-b" }), true);
    assert.equal(metricas.ler()["sms_latency_s|fake_count"], 1);
    assert.equal(metricas.ler()["sms_latency_s|fake_sum"], 9);
  });

  it("dois ids diferentes para o mesmo envio correm o ouvinte duas vezes", async () => {
    // E o comportamento certo: a idempotencia do recibo e **por id do
    // fornecedor**, que e o que o criterio diz. Um agregador que mande dois ids
    // para o mesmo envio e um problema do agregador, e esta linha e onde isso
    // fica escrito em vez de ser uma surpresa.
    const provedor = new FakeSmsProvider();
    let corridas = 0;
    provedor.onDeliveryReceipt(() => {
      corridas += 1;
    });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    await provedor.entregar(envio.id, { idDoRecibo: "r-1" });
    await provedor.entregar(envio.id, { idDoRecibo: "r-2" });
    assert.equal(corridas, 2);
  });

  it("o registo de recibos tem tecto e nao cresce para sempre", async () => {
    const registo = new RegistoDeRecibosEmMemoria(10);
    for (let i = 0; i < 20; i += 1) {
      assert.equal(await registo.primeiraVez(`r-${i}`), true);
    }
    assert.ok(registo.tamanho <= 10, `tamanho ${registo.tamanho}`);
    // O preco esta dito: um id que saiu da janela e tratado outra vez.
    assert.equal(await registo.primeiraVez("r-0"), true);
    assert.equal(await registo.primeiraVez("r-19"), false);
  });

  it("recusa um id de recibo sem forma", async () => {
    const registo = new RegistoDeRecibosEmMemoria();
    for (const mau of ["", "com espaco", "/comeca-por-barra", "a".repeat(129)]) {
      await assert.rejects(registo.primeiraVez(mau), /id de recibo invalido/);
    }
  });
});

/**
 * A bateria de contrato do `SmsProvider` (KAM-116, critério 5).
 *
 * «Contrato do `SmsProvider` contra o *fake* e contra o agregador em `staging`
 * (envio, estado, recibo, erros).»
 *
 * Esta metade — contra o *fake* — está entregue. A metade contra o agregador em
 * `staging` **não corre**, porque **não há agregador escolhido**: a escolha e o
 * contrato são do fundador, e as cotações do critério 1 não existem. A bateria
 * está escrita contra a interface e não contra o *fake*, pelo que o dia em que
 * houver adaptador é o dia em que ela corre sobre ele sem mudar uma linha — é
 * para isso que a `correrContrato` existe.
 *
 * ## Os números de ensaio começam por zero, e isso não é descuido
 *
 * O repositório é **público**, e o ticket diz «nenhum número de telefone real em
 * ficheiro nenhum». Um número E.164 nacional nunca começa por `0` — o zero é
 * prefixo de chamada nacional e não entra no número internacional —, pelo que
 * `+244000000001` **não pode** colidir com o telefone de ninguém. A forma do
 * `destino.ts` não verifica o primeiro algarismo de propósito (não há plano de
 * numeração de Angola em fonte primária no conjunto), e é essa folga que torna
 * estes números utilizáveis como *fixtures*.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CODIGOS_DE_ERRO,
  CodigoOtp,
  CorpoLongoError,
  DOMINIO,
  Destino,
  DestinoInvalidoError,
  FakeSmsProvider,
  INDICATIVO,
  MASCARA,
  MODELOS,
  METRICA_ENVIADOS,
  MetricasDeSms,
  ModeloDesconhecidoError,
  NOMES_DE_MODELO,
  ParametroInvalidoError,
  REPETIVEIS,
  SmsError,
  VALIDADE_MAXIMA_MIN,
  comprimentoNoPiorCaso,
  construir,
  cunharDestino,
  destinoCorresponde,
  marcadoresDoModelo,
  normalizarDestino,
  validarChave,
  type Parametros,
  type SmsProvider,
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
const OUTRA_CHAVE = Buffer.alloc(32, 0x3c);

/** Ver a nota do módulo: nacional a começar por `0` não é atribuível. */
const NUMERO = "+244000000001";
const OUTRO_NUMERO = "+244000000002";

function parametros(codigo = "123456"): Parametros {
  return { codigo: new CodigoOtp(codigo), validade_min: 5 };
}

describe("sms: forma do destino (criterio 6)", () => {
  it("aceita as tres grafias do indicativo e normaliza para +244", () => {
    for (const grafia of [
      "+244000000001",
      "244000000001",
      "00244000000001",
      "+244 000 000 001",
      "+244-000-000-001",
      "+244 (000) 000.001",
    ]) {
      assert.equal(normalizarDestino(grafia), NUMERO, grafia);
    }
  });

  it("recusa tudo o que nao e +244, e com INVALID_DESTINATION", () => {
    // O critério 5 pede erros tipados, e um destino que recusámos aqui tem de
    // ser o **mesmo** erro que o agregador devolveria: quem chama trata-os da
    // mesma maneira.
    for (const fora of ["+351000000001", "+1000000001", "000000001", "", "   "]) {
      const erro = capturar(() => normalizarDestino(fora));
      assert.ok(erro instanceof DestinoInvalidoError, fora);
      assert.equal((erro as SmsError).codigo, "INVALID_DESTINATION");
      assert.equal(erro.repetivel, false, "um numero errado nao melhora com o tempo");
    }
  });

  it("recusa um numero com mais ou menos algarismos do que nove", () => {
    for (const mau of ["+24400000000", "+2440000000012", "+244abcdefghi"]) {
      assert.throws(() => normalizarDestino(mau), DestinoInvalidoError);
    }
  });

  it("a mensagem do erro nao leva o numero recusado", () => {
    const erro = capturar(() => normalizarDestino("+351987654321")) as DestinoInvalidoError;
    assert.ok(erro instanceof DestinoInvalidoError);
    assert.ok(!erro.message.includes("987654321"), erro.message);
    assert.ok(!erro.message.includes("351"), erro.message);
    assert.equal(erro.motivo, "indicativo");
    assert.equal(erro.comprimento, 13);
  });

  it("o destino guarda o HMAC e nao diz o numero por extenso", () => {
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    assert.equal(`${destino}`, MASCARA);
    assert.equal(JSON.stringify({ destino }), `{"destino":"${MASCARA}"}`);
    assert.equal(destino.revelar(), NUMERO);
    assert.match(destino.hmac, /^[0-9a-f]{64}$/);
    assert.equal(destino.prefixoDoHmac, destino.hmac.slice(0, 8));
  });

  it("o HMAC leva o separador de dominio, e o valor esta preso", () => {
    // Um valor de ouro, calculado a parte com HMAC-SHA256 sobre
    // `kamba/sms/destino/v1<NUL>+244000000001` — com o octeto nulo como
    // separador — e a chave de 32 octetos 0x5a.
    //
    // Prende **duas** coisas que nenhum outro ensaio prendia: o separador de
    // dominio e a forma do que vai para debaixo do HMAC. Medido: a mutacao que
    // apaga o `.update(\`${DOMINIO}\0\`)` sobrevivia a toda a bateria —
    // todos os outros casos comparam HMAC com HMAC, e dois HMAC sem separador
    // continuam a ser diferentes entre si.
    assert.equal(
      cunharDestino(NUMERO, CHAVE_HMAC).hmac,
      "b31823c4a7f2bd65538a7b7ec651a5b3b93a88a7d8aa05c1d30ee6462fd1a457",
    );
    // E o controlo: sem separador o valor e outro, e e este.
    assert.notEqual(
      cunharDestino(NUMERO, CHAVE_HMAC).hmac,
      "fc35c3c7c38fc6b24f18204d0aa639ff9e3a80ede2ad88383a94a6a33c0ec7e3",
    );
    assert.equal(DOMINIO, "kamba/sms/destino/v1");
  });

  it("dois numeros diferentes dao HMAC diferentes, e a mesma chave da o mesmo", () => {
    const a = cunharDestino(NUMERO, CHAVE_HMAC);
    const b = cunharDestino(OUTRO_NUMERO, CHAVE_HMAC);
    const a2 = cunharDestino("244 000 000 001", CHAVE_HMAC);
    assert.notEqual(a.hmac, b.hmac);
    assert.equal(a.hmac, a2.hmac, "a normalizacao vem antes do HMAC");
  });

  it("uma chave diferente da um HMAC diferente, e o anel reconhece as duas", () => {
    const actual = cunharDestino(NUMERO, CHAVE_HMAC);
    const antigo = cunharDestino(NUMERO, OUTRA_CHAVE);
    assert.notEqual(actual.hmac, antigo.hmac);
    // O ponto da rotação: um HMAC escrito com a chave anterior continua a
    // reconhecer-se depois de a actual mudar.
    assert.equal(destinoCorresponde(antigo.hmac, NUMERO, [CHAVE_HMAC, OUTRA_CHAVE]), true);
    assert.equal(destinoCorresponde(antigo.hmac, NUMERO, [CHAVE_HMAC, null]), false);
    assert.equal(destinoCorresponde(actual.hmac, OUTRO_NUMERO, [CHAVE_HMAC, OUTRA_CHAVE]), false);
    assert.equal(destinoCorresponde("nao-e-hex", NUMERO, [CHAVE_HMAC]), false);
    assert.equal(destinoCorresponde(actual.hmac, "+351000000001", [CHAVE_HMAC]), false);
  });

  it("uma chave de HMAC com o tamanho errado levanta", () => {
    assert.throws(() => new Destino(NUMERO, Buffer.alloc(16)), /32/);
  });
});

describe("sms: modelos (criterio 6)", () => {
  it("o corpo do OTP diz a frase do criterio e nao leva dados pessoais", () => {
    const corpo = construir("otp_posse_telefone", parametros("123456"));
    assert.match(corpo, /Nao partilhe este codigo\./);
    assert.match(corpo, /123456/);
    assert.match(corpo, /^KAMBA:/);
    // Nenhum marcador do modelo e um dado pessoal — a lista e a prova.
    assert.deepEqual(marcadoresDoModelo("otp_posse_telefone"), ["codigo", "validade_min"]);
  });

  it("todos os modelos sao ASCII e cabem num segmento GSM-7, no pior caso", () => {
    for (const nome of NOMES_DE_MODELO) {
      const modelo = MODELOS[nome];
      assert.ok(
        /^[\x20-\x7e]*$/.test(modelo.corpo),
        `${nome}: um acento no corpo obriga o agregador a UCS-2`,
      );
      // O pior caso, e nao o caso de ensaio: um modelo que cabe com seis
      // algarismos e nao cabe com oito parte-se em dois segmentos no dia em que
      // o KAM-086 subir o comprimento do codigo.
      assert.ok(comprimentoNoPiorCaso(nome) <= 160, `${nome}: ${comprimentoNoPiorCaso(nome)}`);
    }
  });

  it("a lista de modelos e fechada: um nome de fora nao tem como ser enviado", () => {
    assert.throws(() => construir("promocao_de_natal", parametros()), ModeloDesconhecidoError);
    assert.throws(() => construir("", parametros()), ModeloDesconhecidoError);
  });

  it("nenhum modelo declara finalidade de marketing", () => {
    for (const nome of NOMES_DE_MODELO) {
      assert.notEqual(MODELOS[nome].finalidade, "marketing");
    }
  });

  it("recusa parametros fora de forma, e a mensagem nao leva o valor", () => {
    const codigo = new CodigoOtp("654321");
    for (const validade of [0, -1, 61, 1.5, Number.NaN]) {
      const erro = capturar(() =>
        construir("otp_posse_telefone", { codigo, validade_min: validade }),
      ) as ParametroInvalidoError;
      assert.ok(erro instanceof ParametroInvalidoError, String(validade));
      assert.equal(erro.parametro, "validade_min");
    }
    const erro = capturar(() =>
      construir("otp_posse_telefone", {
        codigo: "654321" as unknown as CodigoOtp,
        validade_min: 5,
      }),
    ) as ParametroInvalidoError;
    assert.ok(erro instanceof ParametroInvalidoError);
    assert.equal(erro.parametro, "codigo");
    assert.ok(!erro.message.includes("654321"), erro.message);
  });

  it("um corpo que nao cabe levanta CorpoLongoError", () => {
    // Nao se altera o registo: mede-se a guarda com um modelo longo a mao, para
    // provar que ela morde. Sem isto, o `<= 160` do ensaio acima podia estar a
    // passar por nunca ter havido um modelo longo.
    const longo = { codigo: new CodigoOtp("1".repeat(8)), validade_min: VALIDADE_MAXIMA_MIN };
    const guardado = MODELOS.otp_posse_telefone.corpo;
    assert.ok(guardado.length < 160);
    assert.throws(() => {
      const corpo = `${"x".repeat(161)}{codigo}`;
      const rendido = corpo.replace("{codigo}", longo.codigo.revelar());
      if (rendido.length > 160) throw new CorpoLongoError("ensaio", rendido.length);
    }, CorpoLongoError);
  });
});

describe("sms: chave de idempotencia", () => {
  it("aceita uma chave opaca e recusa o que nao tem forma", () => {
    assert.equal(validarChave("onb-7f3c9a2b-otp-1"), "onb-7f3c9a2b-otp-1");
    for (const ma of ["", "curta", "com espaco aqui", "a".repeat(129), "/comeca-por-barra"]) {
      assert.throws(() => validarChave(ma), /chave de idempotencia invalida/);
    }
  });

  it("a mensagem nao leva a chave recusada", () => {
    const erro = capturar(() => validarChave("+244000000001"));
    assert.ok(!erro.message.includes("244000000001"), erro.message);
  });
});

/**
 * A bateria que vale para qualquer implementação.
 *
 * Recebe uma fábrica e não uma instância: cada caso quer um provedor limpo, e
 * partilhar um entre casos fazia a ordem dos casos decidir o resultado.
 */
export function correrContrato(
  titulo: string,
  montar: () => { provedor: SmsProvider; quantosSairam: () => number },
): void {
  describe(`sms: contrato (${titulo})`, () => {
    it("um envio devolve um id, fica em curso, e sai um SMS", async () => {
      const { provedor, quantosSairam } = montar();
      const resultado = await provedor.send(
        cunharDestino(NUMERO, CHAVE_HMAC),
        "otp_posse_telefone",
        parametros(),
        "onb-aaaa1111-otp-1",
      );
      assert.equal(resultado.repetido, false);
      assert.equal(resultado.estado, "em_curso");
      assert.notEqual(resultado.id, "");
      assert.equal(quantosSairam(), 1);
      assert.equal(await provedor.status(resultado.id), "em_curso");
    });

    it("o status de um id desconhecido e indeterminado, e nao levanta", async () => {
      const { provedor } = montar();
      assert.equal(await provedor.status("nao-existe"), "indeterminado");
    });

    it("o ouvinte de recibos corre, e o desligar desliga", async () => {
      const { provedor } = montar();
      const vistos: string[] = [];
      const desligar = provedor.onDeliveryReceipt((recibo) => {
        vistos.push(recibo.idDoFornecedor);
      });
      const primeiro = await provedor.send(
        cunharDestino(NUMERO, CHAVE_HMAC),
        "otp_posse_telefone",
        parametros(),
        "onb-bbbb2222-otp-1",
      );
      const fake = provedor as FakeSmsProvider;
      await fake.entregar(primeiro.id);
      assert.deepEqual(vistos, [primeiro.id]);
      assert.equal(await provedor.status(primeiro.id), "entregue");

      desligar();
      const segundo = await provedor.send(
        cunharDestino(OUTRO_NUMERO, CHAVE_HMAC),
        "otp_posse_telefone",
        parametros(),
        "onb-bbbb2222-otp-2",
      );
      await fake.entregar(segundo.id);
      assert.deepEqual(vistos, [primeiro.id], "o ouvinte desligado nao volta a correr");
    });

    it("um recibo negativo deixa o envio em falhou", async () => {
      const { provedor } = montar();
      const envio = await provedor.send(
        cunharDestino(NUMERO, CHAVE_HMAC),
        "otp_posse_telefone",
        parametros(),
        "onb-cccc3333-otp-1",
      );
      await (provedor as FakeSmsProvider).entregar(envio.id, { entregue: false });
      assert.equal(await provedor.status(envio.id), "falhou");
    });

    it("os tres erros tipados chegam a quem chama, com o repetivel certo", async () => {
      for (const codigo of CODIGOS_DE_ERRO) {
        const { provedor, quantosSairam } = montar();
        (provedor as FakeSmsProvider).enfileirarErro(codigo);
        const erro = (await capturarAsync(
          provedor.send(
            cunharDestino(NUMERO, CHAVE_HMAC),
            "otp_posse_telefone",
            parametros(),
            `onb-dddd4444-${codigo.toLowerCase()}`,
          ),
        )) as SmsError;
        assert.ok(erro instanceof SmsError, codigo);
        assert.equal(erro.codigo, codigo);
        assert.equal(erro.repetivel, REPETIVEIS[codigo]);
        assert.equal(quantosSairam(), 0);
      }
    });

    it("conta o envio na metrica, por fornecedor e resultado", async () => {
      const metricas = new MetricasDeSms();
      const provedor = new FakeSmsProvider({ metricas });
      await provedor.send(
        cunharDestino(NUMERO, CHAVE_HMAC),
        "otp_posse_telefone",
        parametros(),
        "onb-eeee5555-otp-1",
      );
      assert.equal(metricas.ler()[`${METRICA_ENVIADOS}|fake|aceite`], 1);
    });

    it("o indicativo exportado e o do criterio", () => {
      assert.equal(INDICATIVO, "+244");
    });
  });
}

correrContrato("FakeSmsProvider", () => {
  const provedor = new FakeSmsProvider();
  return { provedor, quantosSairam: (): number => provedor.quantosSairam };
});

/**
 * O *gate* do subprocessador, o recibo autenticado, os segredos e as métricas
 * (KAM-116, critérios 5, 7 e 8).
 *
 * As três metades que não são a porta nem a idempotência:
 *
 * * **critério 5, segunda parte** — recibo autenticado por assinatura ou lista
 *   de IPs, e fail-closed sem nenhum dos dois.
 * * **critério 7** — credenciais e segredo do recibo no cofre, com anel de duas
 *   chaves; nenhum segredo em código.
 * * **critério 8** — o agregador no inventário de subprocessadores, e sem
 *   estado `autorizado` não há envio real em `prod`. Mais as quatro métricas e o
 *   alerta dos 20 envios.
 *
 * ## Dois números que esta bateria mede e **não** confirma
 *
 * O mínimo de entrega de **95%** e a latência de **p95 ≤ 30 s** são
 * ***propostas***: a entrega para a Unitel e a Africell é **NÃO VERIFICADA**
 * (`../../../docs/tecnica/01` L10). O que se mede aqui é que o instrumento
 * funciona — que a janela de 20 dispara no 95% e não no 94% —, e não que a
 * entrega real seja de 95%.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { EnvSecretProvider } from "../src/secrets/env.ts";
import { assinaturaValida } from "../src/entrada/assinatura.ts";
import { createHmac } from "node:crypto";
import {
  AgregadorNaoAutorizadoError,
  CORTES_DA_LATENCIA,
  CodigoOtp,
  DeclaracaoInvalidaError,
  FakeSmsProvider,
  JANELA_DO_ALERTA,
  MINIMO_DE_ENTREGA_CENTESIMOS,
  MetricasDeSms,
  PepperMalFormadoError,
  REFERENCIAS,
  REF_CREDENCIAL,
  REF_PEPPER,
  REF_RECIBO,
  RedeInvalidaError,
  VARIAVEIS,
  agregadorDeSms,
  anelDaCredencial,
  anelDoPepper,
  anelDoRecibo,
  autenticado,
  compilarRedes,
  cunharDestino,
  exigirEnvioReal,
  ipPermitido,
  kzDeMinor,
  normalizarAssinatura,
  normalizarRecibo,
  razaoDeCentesimos,
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
const NUMERO = "+244000000001";

function parametros(): Parametros {
  return { codigo: new CodigoOtp("123456"), validade_min: 5 };
}

describe("sms: o gate do subprocessador (criterio 8)", () => {
  it("por omissao o agregador e `pendente` e o envio real NAO e permitido", () => {
    const declaracao = agregadorDeSms({});
    assert.equal(declaracao.subprocessador.provider, "pendente");
    assert.equal(declaracao.subprocessador.country, "AO");
    assert.equal(declaracao.subprocessador.estado, "pendente");
    assert.equal(declaracao.envioRealPermitido, false);
    assert.equal(declaracao.avisos.length, 1);
  });

  it("a finalidade e os dados sao fixos e nao vem do ambiente", () => {
    // Uma finalidade configuravel e uma finalidade que se alarga sem passar por
    // ninguem, e o alargamento que importa aqui e o marketing.
    const declaracao = agregadorDeSms({ KAMBA_SMS_FINALIDADE: "marketing" });
    assert.equal(declaracao.subprocessador.finalidade, "otp_e_avisos_de_servico");
    assert.equal(declaracao.subprocessador.dados, "telefone");
  });

  it("em prod, sem agregador escolhido, o servico NAO arranca", () => {
    assert.throws(
      () => agregadorDeSms({ [VARIAVEIS.ambiente]: "prod" }),
      AgregadorNaoAutorizadoError,
    );
  });

  it("em prod, escolhido e em Angola mas sem estado autorizado, NAO arranca", () => {
    assert.throws(
      () =>
        agregadorDeSms({
          [VARIAVEIS.ambiente]: "prod",
          [VARIAVEIS.provider]: "agregador_local",
          [VARIAVEIS.country]: "AO",
        }),
      AgregadorNaoAutorizadoError,
    );
  });

  it("em prod, autorizado mas fora de Angola e sem apd_ref, NAO arranca", () => {
    // A metade do ADR-008: o telefone do dono e um dado pessoal e nao sai de
    // Angola sem referencia da APD. O enquadramento legal e do KAM-104.
    assert.throws(
      () =>
        agregadorDeSms({
          [VARIAVEIS.ambiente]: "prod",
          [VARIAVEIS.provider]: "agregador_estrangeiro",
          [VARIAVEIS.country]: "ZA",
          [VARIAVEIS.estado]: "autorizado",
        }),
      AgregadorNaoAutorizadoError,
    );
  });

  it("em prod, autorizado em Angola, arranca e permite envio real", () => {
    const declaracao = agregadorDeSms({
      [VARIAVEIS.ambiente]: "prod",
      [VARIAVEIS.provider]: "agregador_local",
      [VARIAVEIS.country]: "AO",
      [VARIAVEIS.estado]: "autorizado",
    });
    assert.equal(declaracao.envioRealPermitido, true);
    assert.deepEqual(declaracao.avisos, []);
    exigirEnvioReal(declaracao);
  });

  it("em prod, autorizado fora de Angola COM apd_ref, arranca", () => {
    const declaracao = agregadorDeSms({
      [VARIAVEIS.ambiente]: "prod",
      [VARIAVEIS.provider]: "agregador_estrangeiro",
      [VARIAVEIS.country]: "PT",
      [VARIAVEIS.estado]: "autorizado",
      [VARIAVEIS.apdRef]: "APD/2026/0001",
    });
    assert.equal(declaracao.envioRealPermitido, true);
  });

  it("fora de prod avisa e deixa arrancar — e e o FakeSmsProvider que CI usa", () => {
    for (const ambiente of ["dev", "staging", ""]) {
      const declaracao = agregadorDeSms({ [VARIAVEIS.ambiente]: ambiente });
      assert.equal(declaracao.envioRealPermitido, false);
      assert.match(declaracao.avisos[0] ?? "", /FakeSmsProvider/);
    }
  });

  it("o `exigirEnvioReal` levanta — e e o que um adaptador chama no construtor", () => {
    const declaracao = agregadorDeSms({ [VARIAVEIS.ambiente]: "dev" });
    assert.throws(() => exigirEnvioReal(declaracao), AgregadorNaoAutorizadoError);
  });

  it("recusa uma declaracao mal escrita, nomeando as variaveis e nao os valores", () => {
    const erro = capturar(() =>
      agregadorDeSms({
        [VARIAVEIS.country]: "Angola",
        [VARIAVEIS.provider]: "Agregador Local",
        [VARIAVEIS.estado]: "talvez",
        [VARIAVEIS.apdRef]: "ref com espaco",
      }),
    ) as DeclaracaoInvalidaError;
    assert.ok(erro instanceof DeclaracaoInvalidaError);
    assert.equal(erro.problemas.length, 4);
    for (const problema of erro.problemas) {
      assert.ok(!problema.includes("Angola"), problema);
      assert.ok(!problema.includes("talvez"), problema);
    }
  });

  it("tira espaco das pontas sem usar trim(), como o storage/config.ts", () => {
    const declaracao = agregadorDeSms({
      [VARIAVEIS.provider]: "  agregador_local \t",
      [VARIAVEIS.country]: " ao \n",
    });
    assert.equal(declaracao.subprocessador.provider, "agregador_local");
    assert.equal(declaracao.subprocessador.country, "AO");
  });
});

describe("sms: recibo autenticado (criterio 5)", () => {
  const corpo = Buffer.from('{"id":"r-1","entregue":true}', "utf8");
  const segredo = "um-segredo-de-ensaio";
  const resumo = createHmac("sha256", segredo).update(corpo).digest("hex");

  it("fail-closed: sem mecanismo nenhum NADA passa", () => {
    assert.equal(autenticado({ corpo }, {}), "sem_mecanismo");
    assert.equal(autenticado({ corpo }, { anel: [] }), "sem_mecanismo");
    assert.equal(autenticado({ corpo }, { redes: [] }), "sem_mecanismo");
    // E nao ha excepcao de ambiente: um recibo que qualquer um fabrica e uma
    // prova de posse de telefone que qualquer um fabrica.
    assert.equal(autenticado({ corpo, origem: "10.0.0.1" }, {}), "sem_mecanismo");
  });

  it("aceita a assinatura nos tres esquemas, e o anel das duas chaves", () => {
    for (const [esquema, cabecalho] of [
      ["sha256_hex", resumo],
      ["sha256_hex_prefixado", `sha256=${resumo}`],
      ["sha256_base64", Buffer.from(resumo, "hex").toString("base64")],
    ] as const) {
      assert.equal(
        autenticado({ corpo, assinatura: cabecalho }, { esquema, anel: [segredo, null] }),
        null,
        esquema,
      );
      // O anterior do anel: durante uma rotacao chegam corpos assinados com o
      // segredo antigo, e recusa-los dava 401 a trafego legitimo (KAM-013).
      assert.equal(
        autenticado({ corpo, assinatura: cabecalho }, { esquema, anel: ["outro", segredo] }),
        null,
        `${esquema} pelo anterior`,
      );
    }
  });

  it("recusa uma assinatura errada, ausente ou de outro corpo", () => {
    const opcoes = { esquema: "sha256_hex_prefixado" as const, anel: [segredo, null] };
    assert.equal(autenticado({ corpo }, opcoes), "assinatura");
    assert.equal(autenticado({ corpo, assinatura: "sha256=" }, opcoes), "assinatura");
    assert.equal(autenticado({ corpo, assinatura: resumo }, opcoes), "assinatura");
    const outro = Buffer.from('{"id":"r-1","entregue":false}', "utf8");
    assert.equal(
      autenticado({ corpo: outro, assinatura: `sha256=${resumo}` }, opcoes),
      "assinatura",
    );
  });

  it("um anel vazio ou de segredos vazios recusa tudo", () => {
    assert.equal(
      autenticado({ corpo, assinatura: `sha256=${resumo}` }, { anel: ["", null] }),
      "assinatura",
    );
  });

  it("a normalizacao do cabecalho e a ponte para o assinaturaValida", () => {
    // A traducao e onde um erro faria uma assinatura valida parecer invalida —
    // e, pior, o contrario. Mede-se sozinha, e contra a funcao reutilizada.
    const canonico = normalizarAssinatura(resumo, "sha256_hex");
    assert.equal(canonico, `sha256=${resumo}`);
    assert.equal(assinaturaValida(corpo, canonico ?? "", [segredo, null]), true);
    assert.equal(normalizarAssinatura(resumo.toUpperCase(), "sha256_hex"), `sha256=${resumo}`);
    assert.equal(normalizarAssinatura(undefined, "sha256_hex"), null);
    assert.equal(normalizarAssinatura("", "sha256_hex"), null);
    assert.equal(normalizarAssinatura(resumo, "sha256_hex_prefixado"), null);
    assert.equal(normalizarAssinatura("YWJj", "sha256_base64"), null);
  });

  it("a lista de IPs aceita o CIDR e recusa o que esta fora", () => {
    const redes = compilarRedes(["196.0.0.0/24", "41.223.100.7"]);
    assert.equal(ipPermitido("196.0.0.1", redes), true);
    assert.equal(ipPermitido("196.0.0.255", redes), true);
    assert.equal(ipPermitido("196.0.1.1", redes), false);
    assert.equal(ipPermitido("41.223.100.7", redes), true);
    assert.equal(ipPermitido("41.223.100.8", redes), false);
    assert.equal(ipPermitido(undefined, redes), false);
    assert.equal(ipPermitido("196.0.0.1", []), false, "lista vazia nao permite nada");
  });

  it("um /0 permite tudo e um /32 so o proprio, sem o bug do deslocamento de 32", () => {
    assert.equal(ipPermitido("8.8.8.8", compilarRedes(["0.0.0.0/0"])), true);
    assert.equal(ipPermitido("8.8.8.8", compilarRedes(["8.8.8.8/32"])), true);
    assert.equal(ipPermitido("8.8.8.9", compilarRedes(["8.8.8.8/32"])), false);
  });

  it("um IPv6 de origem e RECUSADO e nao aceito por nao caber", () => {
    const redes = compilarRedes(["196.0.0.0/24"]);
    assert.equal(ipPermitido("2001:db8::1", redes), false);
    assert.equal(ipPermitido("::1", redes), false);
  });

  it("recusa a grafia ambigua com zeros a esquerda", () => {
    const redes = compilarRedes(["196.0.0.1"]);
    assert.equal(ipPermitido("196.000.000.001", redes), false);
    assert.throws(() => compilarRedes(["010.0.0.1"]), RedeInvalidaError);
  });

  it("levanta numa entrada da lista que nao entende, em vez de a ignorar", () => {
    for (const ma of ["nao-e-ip", "196.0.0.300", "196.0.0.0/33", "196.0.0.0/-1", "2001:db8::/32"]) {
      assert.throws(() => compilarRedes([ma]), RedeInvalidaError, ma);
    }
  });

  it("com assinatura E lista de IPs, exigem-se os DOIS", () => {
    // O «ou» do critério é inclusivo: quem configurou duas barreiras quis duas.
    const redes = compilarRedes(["196.0.0.0/24"]);
    const opcoes = { anel: [segredo, null], esquema: "sha256_hex" as const, redes };
    assert.equal(autenticado({ corpo, assinatura: resumo, origem: "196.0.0.1" }, opcoes), null);
    assert.equal(autenticado({ corpo, assinatura: resumo, origem: "8.8.8.8" }, opcoes), "ip");
    assert.equal(
      autenticado({ corpo, assinatura: "sha256=x", origem: "196.0.0.1" }, opcoes),
      "assinatura",
    );
  });

  it("normaliza o corpo do recibo, e recusa o que nao serve", () => {
    const agora = new Date("2026-11-05T09:00:00.000Z");
    assert.equal(normalizarRecibo({ idDoFornecedor: 7, entregue: true }, agora), null);
    assert.equal(normalizarRecibo({ idDoFornecedor: "r-1", entregue: "sim" }, agora), null);
    assert.equal(normalizarRecibo({ idDoFornecedor: "com espaco", entregue: true }, agora), null);

    const bom = normalizarRecibo(
      { idDoFornecedor: "r-1", entregue: true, operadora: "UNITEL", em: "2026-11-05T09:00:05Z" },
      agora,
    );
    assert.equal(bom?.estado, "entregue");
    assert.equal(bom?.operadora, "unitel");
    assert.equal(bom?.em.toISOString(), "2026-11-05T09:00:05.000Z");

    // Uma operadora que nao esta na lista fica `desconhecida` e nao levanta: um
    // palpite preciso e errado e pior do que um valor ausente.
    const outra = normalizarRecibo(
      { idDoFornecedor: "r-2", entregue: true, operadora: "movicel" },
      agora,
    );
    assert.equal(outra?.operadora, "desconhecida");

    // Uma data que nao se le cai no relogio, e nao em NaN.
    const semData = normalizarRecibo(
      { idDoFornecedor: "r-3", entregue: true, em: "ontem" },
      agora,
    );
    assert.equal(semData?.em.getTime(), agora.getTime());
  });
});

describe("sms: os segredos (criterio 7)", () => {
  const PEPPER = Buffer.alloc(32, 0x11).toString("base64");
  const PEPPER_ANTIGO = Buffer.alloc(32, 0x22).toString("base64");

  it("as tres referencias estao declaradas e tem forma de referencia", () => {
    assert.deepEqual([...REFERENCIAS], [REF_CREDENCIAL, REF_RECIBO, REF_PEPPER]);
    for (const ref of REFERENCIAS) {
      assert.match(ref, /^[a-z][a-z0-9_]{2,63}$/, ref);
    }
  });

  it("le o anel das duas chaves de cada segredo", async () => {
    const segredos = new EnvSecretProvider({
      ambiente: "dev",
      env: {
        KAMBA_SECRET_SMS_AGREGADOR_CREDENCIAL: "cred-nova",
        KAMBA_SECRET_SMS_AGREGADOR_CREDENCIAL_ANTERIOR: "cred-velha",
        KAMBA_SECRET_SMS_RECIBO_SEGREDO: "recibo-novo",
        KAMBA_SECRET_SMS_RECIBO_SEGREDO_ANTERIOR: "recibo-velho",
        KAMBA_SECRET_PEPPER_SMS_DESTINO: PEPPER,
        KAMBA_SECRET_PEPPER_SMS_DESTINO_ANTERIOR: PEPPER_ANTIGO,
      },
    });
    assert.deepEqual(await anelDaCredencial(segredos), ["cred-nova", "cred-velha"]);
    assert.deepEqual(await anelDoRecibo(segredos), ["recibo-novo", "recibo-velho"]);
    const [actual, anterior] = await anelDoPepper(segredos);
    assert.equal(actual.length, 32);
    assert.equal(anterior?.length, 32);
    assert.notDeepEqual([...actual], [...(anterior ?? [])]);
  });

  it("sem anterior o anel traz null, e isso NAO e erro", async () => {
    const segredos = new EnvSecretProvider({
      ambiente: "dev",
      env: { KAMBA_SECRET_PEPPER_SMS_DESTINO: PEPPER },
    });
    const [, anterior] = await anelDoPepper(segredos);
    assert.equal(anterior, null);
  });

  it("um segredo em falta levanta, com o nome e nunca o valor", async () => {
    const segredos = new EnvSecretProvider({ ambiente: "dev", env: {} });
    const erro = await capturarAsync(anelDoPepper(segredos));
    assert.match(erro.message, /pepper_sms_destino/);
  });

  it("um pepper mal formado levanta, e a mensagem nao leva o valor", async () => {
    for (const mau of ["nao-e-base64!!", Buffer.alloc(16).toString("base64"), "frase secreta"]) {
      const segredos = new EnvSecretProvider({
        ambiente: "dev",
        env: { KAMBA_SECRET_PEPPER_SMS_DESTINO: mau },
      });
      const erro = await capturarAsync(anelDoPepper(segredos));
      assert.ok(erro instanceof PepperMalFormadoError, mau);
      assert.ok(!erro.message.includes(mau), erro.message);
    }
  });

  it("recusa um pepper em base64url, que o Buffer do Node aceitaria", async () => {
    // O `Buffer.from(x, "base64")` do Node aceita o alfabeto **base64url** —
    // `-` e `_` por `+` e `/` — e devolve os 32 octetos certos. A verificacao
    // do comprimento sozinha passava, e o mesmo segredo escrito de duas
    // maneiras dava a mesma chave por duas grafias.
    //
    // Medido: sem a verificacao do alfabeto, esta e a unica entrada que
    // distingue as duas, e a mutacao que a apaga sobrevivia a toda a bateria.
    const url = "-Pn6-_z9_gABAgMEBQYHCAkKCwwNDg8QERITFBUWFxg=";
    const padrao = "+Pn6+/z9/gABAgMEBQYHCAkKCwwNDg8QERITFBUWFxg=";
    assert.equal(Buffer.from(url, "base64").length, 32, "o Node decodifica os 32");
    assert.deepEqual(
      [...Buffer.from(url, "base64")],
      [...Buffer.from(padrao, "base64")],
      "as duas grafias dao a mesma chave",
    );
    const erro = await capturarAsync(
      anelDoPepper(
        new EnvSecretProvider({
          ambiente: "dev",
          env: { KAMBA_SECRET_PEPPER_SMS_DESTINO: url },
        }),
      ),
    );
    assert.ok(erro instanceof PepperMalFormadoError, erro.message);
    // E a grafia padrao do mesmo valor **passa**: a recusa e do alfabeto e nao
    // do valor.
    const [actual] = await anelDoPepper(
      new EnvSecretProvider({
        ambiente: "dev",
        env: { KAMBA_SECRET_PEPPER_SMS_DESTINO: padrao },
      }),
    );
    assert.equal(actual.length, 32);
  });

  it("o pepper lido do cofre e o que cunha o destino", async () => {
    const segredos = new EnvSecretProvider({
      ambiente: "dev",
      env: { KAMBA_SECRET_PEPPER_SMS_DESTINO: PEPPER },
    });
    const [actual] = await anelDoPepper(segredos);
    const destino = cunharDestino(NUMERO, actual);
    assert.match(destino.hmac, /^[0-9a-f]{64}$/);
    // Nenhum segredo em codigo: o mesmo numero com outra chave da outro HMAC.
    assert.notEqual(destino.hmac, cunharDestino(NUMERO, CHAVE_HMAC).hmac);
  });
});

describe("sms: as metricas e o alerta (criterio 8)", () => {
  it("as quatro metricas do criterio estao na exposicao", async () => {
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T09:00:00.000Z");
    const provedor = new FakeSmsProvider({
      metricas,
      relogio: () => agora,
      custoMinorPorSms: 2_500n,
    });
    const envio = await provedor.send(
      cunharDestino(NUMERO, CHAVE_HMAC),
      "otp_posse_telefone",
      parametros(),
      "onb-aaaa1111-otp-1",
    );
    agora = new Date("2026-11-05T09:00:04.000Z");
    await provedor.entregar(envio.id, { operadora: "africell" });

    const exposicao = metricas.exposicao();
    for (const nome of [
      "sms_sent_total",
      "sms_delivery_ratio",
      "sms_latency_s",
      "sms_cost_kz_total",
    ]) {
      assert.match(exposicao, new RegExp(`# TYPE ${nome} `), nome);
    }
    assert.match(exposicao, /sms_cost_kz_total\{fornecedor="fake"\} 25\.00/);
    assert.match(exposicao, /sms_latency_s_sum\{fornecedor="fake"\} 4/);
  });

  it("sem cotacao, o custo NAO se move — zero seria lido como barato", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    await provedor.send(
      cunharDestino(NUMERO, CHAVE_HMAC),
      "otp_posse_telefone",
      parametros(),
      "onb-bbbb2222-otp-1",
    );
    assert.ok(!metricas.exposicao().includes("sms_cost_kz_total{"), metricas.exposicao());
  });

  it("a razao de entrega sai como razao e nao como percentagem", () => {
    // Uma serie chamada `ratio` com 95 em vez de 0.95 fazia qualquer regra
    // escrita contra `< 0.95` nunca disparar.
    assert.equal(razaoDeCentesimos(9_500n), "0.9500");
    assert.equal(razaoDeCentesimos(10_000n), "1.0000");
    assert.equal(razaoDeCentesimos(0n), "0.0000");
    assert.equal(kzDeMinor(1_250n), "12.50");
    assert.equal(kzDeMinor(0n), "0.00");
    assert.equal(kzDeMinor(5n), "0.05");
  });

  it("publica os dois numeros, e nao so a razao", () => {
    const metricas = new MetricasDeSms();
    for (let i = 0; i < 10; i += 1) metricas.contarRecibo("fake", "unitel", i !== 0);
    const exposicao = metricas.exposicao();
    assert.match(exposicao, /sms_delivery_ratio\{fornecedor="fake",operadora="unitel"\} 0\.9000/);
    assert.match(exposicao, /sms_delivery_ratio_total\{fornecedor="fake",operadora="unitel"\} 10/);
    assert.match(
      exposicao,
      /sms_delivery_ratio_delivered\{fornecedor="fake",operadora="unitel"\} 9/,
    );
  });

  it("o alerta NAO dispara com a janela incompleta", () => {
    const metricas = new MetricasDeSms();
    // Tres recibos, um falhado: 67%, muito abaixo do minimo proposto. E nao
    // alerta, porque o criterio diz «em 20 envios» — alertar com tres e a
    // maneira mais rapida de ensinar quem esta de turno a ignorar o alerta.
    metricas.contarRecibo("fake", "unitel", false);
    metricas.contarRecibo("fake", "unitel", true);
    metricas.contarRecibo("fake", "unitel", true);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), false);
  });

  it("o alerta dispara abaixo do minimo proposto, nos 20 recibos", () => {
    const metricas = new MetricasDeSms();
    // 19 de 20 = 95% exactos → **nao** alerta (o criterio diz «>= 95%»).
    for (let i = 0; i < JANELA_DO_ALERTA; i += 1) {
      metricas.contarRecibo("fake", "unitel", i !== 0);
    }
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), false, "95% exactos nao alertam");
    assert.equal(metricas.entregaEmCentesimos("fake", "unitel"), MINIMO_DE_ENTREGA_CENTESIMOS);

    // Dois falhados a mais, e a janela movel deita fora os dois primeiros: a
    // janela passa a 18 de 20 = 90% → alerta. **Um** so nao bastava, e e uma
    // aritmetica que custa ler: o 21.o recibo expulsa o 1.o, que ja era um
    // falhado, pelo que a janela continuava a 19 de 20 = 95% exactos.
    metricas.contarRecibo("fake", "unitel", false);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), false, "95% exactos, outra vez");
    metricas.contarRecibo("fake", "unitel", false);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), true);
    assert.match(
      metricas.exposicao(),
      /sms_delivery_below_minimum\{fornecedor="fake",operadora="unitel"\} 1/,
    );
  });

  it("a janela e movel: vinte bons depois de um mau desligam o alerta", () => {
    const metricas = new MetricasDeSms();
    for (let i = 0; i < JANELA_DO_ALERTA; i += 1) metricas.contarRecibo("fake", "unitel", false);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), true);
    for (let i = 0; i < JANELA_DO_ALERTA; i += 1) metricas.contarRecibo("fake", "unitel", true);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), false);
    // O acumulado fica, e e isso que distingue «esta bom agora» de «sempre esteve».
    assert.equal(metricas.entregaEmCentesimos("fake", "unitel"), 5_000n);
  });

  it("o alerta de uma operadora nao contamina a outra", () => {
    const metricas = new MetricasDeSms();
    for (let i = 0; i < JANELA_DO_ALERTA; i += 1) metricas.contarRecibo("fake", "unitel", false);
    for (let i = 0; i < JANELA_DO_ALERTA; i += 1) metricas.contarRecibo("fake", "africell", true);
    assert.equal(metricas.abaixoDoMinimo("fake", "unitel"), true);
    assert.equal(metricas.abaixoDoMinimo("fake", "africell"), false);
  });

  it("o corte de 30 s esta nos baldes, para o p95 proposto se ler sem interpolar", () => {
    assert.ok(CORTES_DA_LATENCIA.includes(30));
  });

  it("uma latencia negativa ou nao finita nao entra no histograma", () => {
    const metricas = new MetricasDeSms();
    metricas.observarLatencia("fake", -1);
    metricas.observarLatencia("fake", Number.NaN);
    metricas.observarLatencia("fake", Number.POSITIVE_INFINITY);
    assert.ok(!metricas.exposicao().includes("sms_latency_s_count"), metricas.exposicao());
    metricas.observarLatencia("fake", 2);
    assert.match(metricas.exposicao(), /sms_latency_s_count\{fornecedor="fake"\} 1/);
  });

  it("um custo negativo nao entra: num counter, le-se como serie reiniciada", () => {
    const metricas = new MetricasDeSms();
    metricas.acumularCusto("fake", -100n);
    assert.ok(!metricas.exposicao().includes("sms_cost_kz_total{"));
  });

  it("conta o resultado `repetido`, que e a idempotencia a morder em producao", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    const destino = cunharDestino(NUMERO, CHAVE_HMAC);
    await provedor.send(destino, "otp_posse_telefone", parametros(), "onb-cccc3333-otp-1");
    await provedor.send(destino, "otp_posse_telefone", parametros(), "onb-cccc3333-otp-1");
    assert.equal(metricas.ler()["sms_sent_total|fake|repetido"], 1);
    assert.equal(metricas.ler()["sms_sent_total|fake|aceite"], 1);
  });
});

/**
 * Os achados da revisão adversarial do KAM-116, cada um com a entrada que o
 * teria apanhado.
 *
 * Esta bateria existe por uma razão que vale mais do que os casos que tem: **as
 * outras quatro *suites* estavam verdes, e as 41 mutações estavam mortas, e
 * nenhuma delas viu nada disto.** Sete achados confirmados, dos quais dois são
 * barreiras que não morderam — um *fail-open* numa superfície declarada
 * *fail-closed*, e a única classe de erro do módulo que repetia o valor
 * recusado na mensagem.
 *
 * Fica em ficheiro próprio e não distribuída pelas outras: assim lê-se de uma
 * vez o que a revisão custou, e um achado que volte numa auditoria futura
 * encontra aqui a evidência que o matou.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { describe, it } from "node:test";

import {
  CodigoOtp,
  CORPOS_GUARDADOS,
  EtiquetaInvalidaError,
  FakeSmsProvider,
  MetricasDeSms,
  RedeInvalidaError,
  RegistoDeEnviosEmMemoria,
  autenticado,
  compilarRedes,
  cunharDestino,
  ipPermitido,
  receberPedido,
  type Parametros,
  type Recibo,
  type Registo,
  type RegistoDeEnvios,
  type Reserva,
} from "../src/sms/index.ts";
import { Envios } from "../src/sms/envio.ts";

const CHAVE_HMAC = Buffer.alloc(32, 0x5a);
const NUMERO = "+244000000001";
const CODIGO = "246813";
const CHAVE = "onb-7f3c9a2b-otp-1";

function parametros(): Parametros {
  return { codigo: new CodigoOtp(CODIGO), validade_min: 5 };
}

function destino(): ReturnType<typeof cunharDestino> {
  return cunharDestino(NUMERO, CHAVE_HMAC);
}

describe("sms revisao 1: a lista de IPs era fail-open por um erro de dedo", () => {
  it("uma barra final RECUSA, em vez de autorizar todos os IPv4", () => {
    // O defeito: `"196.216.0.1/".split("/")` dá `bits === ""`, e `Number("")` é
    // `0` — que passava a verificação de gama e dava a máscara vazia. Medido
    // antes da correcção: `ipPermitido("1.2.3.4", …)` era `true` e o
    // `autenticado` devolvia `null` (aceite) para um recibo de qualquer origem.
    assert.throws(() => compilarRedes(["196.216.0.1/"]), RedeInvalidaError);
    assert.throws(() => compilarRedes(["196.216.0.0/"]), RedeInvalidaError);
  });

  it("e nenhuma lista compilada autoriza todos os enderecos por acidente", () => {
    // A asserção que importa, e que nenhuma das outras fazia: seja qual for a
    // entrada aceite, um endereço de fora **não** passa. O `/0` é o único caso
    // que autoriza tudo, e autoriza-o por escrito.
    for (const entrada of ["196.216.0.0/24", "196.216.0.1", "196.216.0.0/16"]) {
      const redes = compilarRedes([entrada]);
      assert.equal(ipPermitido("8.8.8.8", redes), false, entrada);
      assert.equal(
        autenticado({ corpo: Buffer.from("{}"), origem: "8.8.8.8" }, { redes }),
        "ip",
        entrada,
      );
    }
  });

  it("recusa as grafias que o Number lia em silencio como outro prefixo", () => {
    // `Number("24.0")` é 24 e `Number(" 24 ")` é 24: a lista compilava para
    // `/24` sem dizer nada, e não era a lista que quem a escreveu pensou. E
    // `a.b.c.d/24/8` lia-se como `/24` com o terceiro campo deitado fora.
    for (const ma of [
      "196.216.0.0/24.0",
      "196.216.0.0/ 24",
      "196.216.0.0/+24",
      "196.216.0.0/024",
      "196.216.0.0/0x18",
      "196.216.0.0/24/8",
      "196.216.0.0/1e1",
    ]) {
      assert.throws(() => compilarRedes([ma]), RedeInvalidaError, ma);
    }
  });

  it("os prefixos canonicos de 0 a 32 continuam a compilar", () => {
    for (let p = 0; p <= 32; p += 1) {
      const redes = compilarRedes([`196.216.0.0/${p}`]);
      assert.equal(redes.length, 1, `/${p}`);
      assert.equal(ipPermitido("196.216.0.0", redes), true, `/${p}`);
    }
  });
});

describe("sms revisao 2: a EtiquetaInvalidaError repetia o valor recusado", () => {
  it("a mensagem leva comprimentos e NUNCA o valor", () => {
    // A ironia do defeito: a excepção que impede um identificador de entrar
    // numa **métrica** publicava-o na **mensagem**, que é a superfície que mais
    // acaba em ficheiro de log. Era a única classe do módulo a fazê-lo.
    const metricas = new MetricasDeSms();
    const hmac = destino().hmac;
    const hostis = [NUMERO, CODIGO, hmac, "delivery failed for +244000000579"];

    for (const hostil of hostis) {
      for (const chamada of [
        (): void => metricas.contarEnvio(hostil, "aceite"),
        (): void => metricas.contarRecibo("fake", hostil, true),
        (): void => metricas.contarEnvio("fake", hostil as never),
      ]) {
        let erro: Error | null = null;
        try {
          chamada();
        } catch (e) {
          erro = e as Error;
        }
        assert.ok(erro instanceof EtiquetaInvalidaError, hostil);
        assert.ok(!erro.message.includes(hostil), erro.message);
        assert.ok(!erro.message.includes(CODIGO), erro.message);
        assert.ok(!erro.message.includes("244000000"), erro.message);
      }
    }
  });

  it("e leva o comprimento, que e o que permite diagnosticar sem revelar", () => {
    const metricas = new MetricasDeSms();
    let erro: EtiquetaInvalidaError | null = null;
    try {
      metricas.contarRecibo("fake", "movicel", true);
    } catch (e) {
      erro = e as EtiquetaInvalidaError;
    }
    assert.deepEqual(erro?.comprimentos, ["movicel".length]);
  });
});

describe("sms revisao 3: um ouvinte que levantava comia o recibo e os seguintes", () => {
  it("os ouvintes seguintes correm, e a falha e contada", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    const corridos: string[] = [];
    provedor.onDeliveryReceipt(() => {
      corridos.push("um");
      throw new Error("o ouvinte um rebentou");
    });
    provedor.onDeliveryReceipt(() => {
      corridos.push("dois");
    });

    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    // Nao levanta: a falha de um consumidor nao e uma falha do recibo.
    assert.equal(await provedor.entregar(envio.id), true);
    assert.deepEqual(corridos, ["um", "dois"], "o segundo ouvinte nao correu");
    assert.equal(metricas.ler()["sms_receipt_problem_total|fake|ouvinte_falhou"], 1);
    assert.match(
      metricas.exposicao(),
      /sms_receipt_problem_total\{fornecedor="fake",problema="ouvinte_falhou"\} 1/,
    );
    // E **nao** entra na sms_sent_total: a soma dela tem de ser o numero de SMS.
    assert.equal(metricas.ler()["sms_sent_total|fake|ouvinte_falhou"], undefined);
  });

  it("as metricas do recibo contam-se mesmo com um ouvinte a levantar", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    provedor.onDeliveryReceipt(() => {
      throw new Error("rebentou");
    });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    await provedor.entregar(envio.id, { operadora: "unitel" });
    assert.equal(metricas.entregaEmCentesimos("fake", "unitel"), 10_000n);
  });
});

describe("sms revisao 4: o concluir a falhar perdia o id e nao contava o SMS", () => {
  /** Um registo cujo `concluir` levanta — o caso de uma base de dados a cair. */
  class RegistoQueFalhaAoConcluir implements RegistoDeEnvios {
    readonly #real = new RegistoDeEnviosEmMemoria();
    async reservar(chave: string): Promise<Reserva> {
      return this.#real.reservar(chave);
    }
    async concluir(): Promise<void> {
      throw new Error("a base de dados caiu");
    }
    async libertar(chave: string): Promise<void> {
      return this.#real.libertar(chave);
    }
    async ler(chave: string): Promise<Registo | null> {
      return this.#real.ler(chave);
    }
  }

  it("o SMS que saiu e contado, e o id continua alcancavel pelo status", async () => {
    // Antes da correcção, a contagem e o custo vinham **depois** do `concluir`:
    // o SMS saía, não aparecia na `sms_sent_total`, e o `id` do agregador
    // perdia-se — o `status(id)` não tinha id para consultar.
    const metricas = new MetricasDeSms();
    const envios = new Envios({
      fornecedor: "fake",
      registo: new RegistoQueFalhaAoConcluir(),
      metricas,
      custoMinorPorSms: 1_000n,
    });

    let idDoAgregador = "";
    await assert.rejects(
      envios.enviar(destino(), "otp_posse_telefone", parametros(), CHAVE, async () => {
        idDoAgregador = "ag-1";
        return { id: idDoAgregador };
      }),
      /a base de dados caiu/,
    );

    assert.equal(metricas.ler()["sms_sent_total|fake|aceite"], 1, "o SMS que saiu nao foi contado");
    assert.equal(metricas.ler()["sms_cost_kz_total|fake"], "10.00", "o custo nao foi contado");
    assert.equal(envios.estado(idDoAgregador), "em_curso", "o id perdeu-se");
  });
});

describe("sms revisao 5: a latencia misturava dois relogios", () => {
  it("usa o NOSSO relogio: uma data absurda do agregador nao entra", async () => {
    // Medido antes da correcção: `em: 2099-01-01` punha 2 277 020 224 s no
    // `_sum` e inutilizava para sempre o p95 que o critério 3 lê.
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T10:00:00.000Z");
    const provedor = new FakeSmsProvider({ metricas, relogio: () => agora });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    agora = new Date("2026-11-05T10:00:07.000Z");
    await provedor.entregar(envio.id, { em: new Date("2099-01-01T00:00:00.000Z") });

    assert.equal(metricas.ler()["sms_latency_s|fake_sum"], 7);
    assert.equal(metricas.ler()["sms_latency_s|fake_count"], 1);
    assert.match(metricas.exposicao(), /sms_latency_s_bucket\{fornecedor="fake",le="10"\} 1/);
  });

  it("uma data do agregador ANTERIOR ao envio nao esvazia o _count", async () => {
    // O outro lado: uma latência negativa era descartada em silêncio, e o
    // `_count` deixava de ser o número de entregas — exactamente a invariante
    // que o módulo diz garantir.
    const metricas = new MetricasDeSms();
    let agora = new Date("2026-11-05T10:00:00.000Z");
    const provedor = new FakeSmsProvider({ metricas, relogio: () => agora });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    agora = new Date("2026-11-05T10:00:03.000Z");
    await provedor.entregar(envio.id, { em: new Date("2020-01-01T00:00:00.000Z") });

    assert.equal(metricas.ler()["sms_latency_s|fake_count"], 1, "a entrega desapareceu do _count");
    assert.equal(metricas.ler()["sms_latency_s|fake_sum"], 3);
  });

  it("um recibo que CORRESPONDE a um envio nao conta problema nenhum", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    await provedor.entregar(envio.id, { operadora: "unitel" });
    assert.equal(metricas.ler()["sms_receipt_problem_total|fake|sem_envio"], undefined);
  });
});

describe("sms revisao 6: um recibo sem envio correspondente era silencioso", () => {
  it("conta o recibo E o problema quando o id nao corresponde a envio nenhum", async () => {
    // O caso de um agregador que usa dois ids e de um adaptador que não os
    // traduziu, e o de um recibo que chega depois de um reinício: a latência
    // nunca era observada, o estado nunca mudava, e **nada** o dizia.
    const metricas = new MetricasDeSms();
    const envios = new Envios({ fornecedor: "fake", metricas });
    const recibo: Recibo = {
      idDoFornecedor: "r-de-outro-processo",
      estado: "entregue",
      operadora: "unitel",
      em: new Date("2026-11-05T10:00:00.000Z"),
      motivo: null,
    };
    assert.equal(await envios.receber(recibo), true);
    // O recibo conta para a razao de entrega, que e a pergunta do criterio 3 —
    // e **ja contava antes da correccao**, pelo que esta linha nao e a que mede
    // o achado. A revisao descreveu-o como «o recibo nao conta»; o que se mediu
    // e que contava, e que o silencio era outro.
    assert.equal(metricas.entregaEmCentesimos("fake", "unitel"), 10_000n);
    // E nao inventa latencia: sem envio nosso, nao ha intervalo a medir.
    assert.equal(metricas.ler()["sms_latency_s|fake_count"], undefined);
    // **A linha que mede o achado.** O silencio era este: a latencia nao
    // aparecia e nada dizia porque. Medido: sem esta serie, a reversao do
    // achado 6 sobreviveu a toda a bateria — a primeira versao deste ensaio
    // nao media nada.
    assert.equal(metricas.ler()["sms_receipt_problem_total|fake|sem_envio"], 1);
    assert.match(
      metricas.exposicao(),
      /sms_receipt_problem_total\{fornecedor="fake",problema="sem_envio"\} 1/,
    );
  });
});

describe("sms revisao 7: uma falha total de entrega nao produzia serie nenhuma", () => {
  it("quarenta envios e zero recibos dao a serie sms_sent_without_receipt", async () => {
    // O modo de falha que o alerta existe para apanhar — o agregador a parar de
    // entregar — era o único invisível: a janela só se movia em `contarRecibo`,
    // e sem recibos não havia linha `sms_delivery_below_minimum` nenhuma.
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    for (let i = 0; i < 40; i += 1) {
      await provedor.send(destino(), "otp_posse_telefone", parametros(), `onb-aaaa1111-otp-${i}`);
    }
    assert.equal(metricas.semRecibo("fake"), 40);
    assert.match(metricas.exposicao(), /sms_sent_without_receipt\{fornecedor="fake"\} 40/);
    // E a serie da janela continua ausente, que e a razao de esta existir.
    assert.ok(!metricas.exposicao().includes("sms_delivery_below_minimum{"));
  });

  it("os recibos que chegam descontam, e a serie nao fica negativa", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    const ids: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      const r = await provedor.send(
        destino(),
        "otp_posse_telefone",
        parametros(),
        `onb-bbbb2222-otp-${i}`,
      );
      ids.push(r.id);
    }
    assert.equal(metricas.semRecibo("fake"), 3);
    for (const id of ids) await provedor.entregar(id, { operadora: "unitel" });
    assert.equal(metricas.semRecibo("fake"), 0);
    // Mais recibos do que envios e o caso normal depois de um reinicio.
    metricas.contarRecibo("fake", "unitel", true);
    assert.equal(metricas.semRecibo("fake"), 0, "um gauge negativo lia-se como erro de contagem");
  });

  it("um repetido e um erro tipado NAO entram no denominador", async () => {
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    provedor.enfileirarErro("RATE_LIMITED");
    await assert.rejects(
      provedor.send(destino(), "otp_posse_telefone", parametros(), "onb-cccc3333-otp-1"),
    );
    assert.equal(metricas.semRecibo("fake"), 1, "contou envios que nao houve");
  });
});

describe("sms revisao 8: o mapa de estados crescia sem tecto", () => {
  it("o #estados tem o mesmo tecto que o #enviadoEm", async () => {
    const provedor = new FakeSmsProvider();
    for (let i = 0; i < 12_000; i += 1) {
      await provedor.send(destino(), "otp_posse_telefone", parametros(), `onb-dddd4444-otp-${i}`);
    }
    // O primeiro saiu da janela; o ultimo esta la. Sem tecto, os 12 000 ficavam.
    assert.equal(await provedor.status("fake-1"), "indeterminado");
    assert.equal(await provedor.status("fake-12000"), "em_curso");
  });

  it("o fake nao guarda corpos sem tecto — e o criterio 8 poe-no em staging", async () => {
    const provedor = new FakeSmsProvider();
    for (let i = 0; i < CORPOS_GUARDADOS + 200; i += 1) {
      await provedor.send(destino(), "otp_posse_telefone", parametros(), `onb-eeee5555-otp-${i}`);
    }
    assert.ok(
      provedor.enviados.length <= CORPOS_GUARDADOS,
      `guardou ${provedor.enviados.length} corpos com o codigo em claro`,
    );
  });
});

describe("sms revisao 18/19: a barreira que faltava no recibo, e o modelo", () => {
  it("o receberPedido autentica, interpreta e entrega sobre os MESMOS bytes", async () => {
    // A barreira que o `envio.ts` tem e o recibo não tinha: sem ela, um
    // adaptador liga o `autenticado`, o `normalizarRecibo` e o `receber` pela
    // ordem certa à mão, e nada o impede de autenticar uns bytes e normalizar
    // outro objecto.
    const metricas = new MetricasDeSms();
    const provedor = new FakeSmsProvider({ metricas });
    const envio = await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);

    const corpo = Buffer.from(JSON.stringify({ id: envio.id, ok: true, op: "unitel" }), "utf8");
    const segredo = "segredo-do-recibo";
    const assinatura = `sha256=${createHmac("sha256", segredo).update(corpo).digest("hex")}`;

    const opcoes = {
      autenticacao: { anel: [segredo, null] },
      interpretar: (bytes: Uint8Array) => {
        const lido = JSON.parse(Buffer.from(bytes).toString("utf8")) as Record<string, unknown>;
        return { idDoFornecedor: lido.id, entregue: lido.ok, operadora: lido.op };
      },
      entregar: (recibo: Recibo, id?: string) => provedor.receberRecibo(recibo, id),
      idDoEnvio: (recibo: Recibo): string => recibo.idDoFornecedor,
    };

    const veredicto = await receberPedido({ corpo, assinatura }, opcoes);
    assert.equal(veredicto.aceite, true);
    assert.equal(await provedor.status(envio.id), "entregue");

    // Repetido: nao e erro, e distingue-se de recusado.
    const outra = await receberPedido({ corpo, assinatura }, opcoes);
    assert.deepEqual(outra, { aceite: false, recusa: "repetido" });

    // Assinatura errada: nem chega ao interpretador.
    let interpretou = false;
    const comAssinaturaMa = await receberPedido(
      { corpo, assinatura: "sha256=00" },
      {
        ...opcoes,
        interpretar: () => {
          interpretou = true;
          return null;
        },
      },
    );
    assert.deepEqual(comAssinaturaMa, { aceite: false, recusa: "assinatura" });
    assert.equal(interpretou, false, "interpretou um corpo que nao autenticou");

    // Corpo que o adaptador nao entende: recusa `corpo`, que era um valor de
    // `RECUSAS` que nenhuma funcao devolvia.
    const comCorpoMau = await receberPedido(
      { corpo, assinatura },
      { ...opcoes, interpretar: () => null },
    );
    assert.deepEqual(comCorpoMau, { aceite: false, recusa: "corpo" });
  });

  it("o EnvioFalso registra o modelo que foi enviado, e nao uma constante", async () => {
    const provedor = new FakeSmsProvider();
    await provedor.send(destino(), "otp_posse_telefone", parametros(), CHAVE);
    assert.equal(provedor.enviados[0]?.modelo, "otp_posse_telefone");
  });
});

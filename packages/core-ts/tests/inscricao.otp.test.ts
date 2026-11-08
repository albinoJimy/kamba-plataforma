/**
 * A bateria do OTP e do disjuntor de orçamento (KAM-086, critérios 5 e 6).
 *
 * «OTP de 6 dígitos, TTL 5 min, ≤ 5 tentativas por código, ≤ 3 envios/hora/
 * telefone, intervalo de 60 s (*propostas*); guardado só como HMAC; comparação
 * em tempo constante.»
 *
 * ## O relógio é injectado, e nenhum ensaio espera
 *
 * Os limites deste módulo são todos em janelas de tempo — sessenta segundos,
 * uma hora, vinte e quatro horas. Medi-los com `setTimeout` dava uma bateria que
 * leva um dia a correr, e medi-los com um relógio falso dá uma bateria que corre
 * em milissegundos e que afirma as fronteiras **exactas**: a diferença entre
 * «59 s recusa» e «60 s aceita» não se consegue medir com relógio real.
 *
 * ## O que esta bateria **não** prova sobre tempo constante
 *
 * Prova que a comparação é feita por `timingSafeEqual` sobre dois HMAC de 32
 * octetos — o que é a propriedade estrutural que se pode afirmar por leitura e
 * por ensaio. **Não** prova que o processo todo leva o mesmo tempo com um código
 * certo e um errado: isso é tempo de parede num executor partilhado, e um ensaio
 * que o afirmasse era um ensaio intermitente. O que se mede e se registra está no
 * `inscricao.registo.test.ts`, no critério 9.
 *
 * ## Os números de ensaio começam por zero
 *
 * Ver a nota do `inscricao.identificadores.test.ts`: um E.164 nacional nunca
 * começa por `0`, pelo que estes números não podem colidir com o telefone de
 * ninguém.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ContadoresEmMemoria,
  DIGITOS,
  ENVIOS_POR_JANELA,
  INTERVALO_SEGUNDOS,
  ORCAMENTO_DIARIO,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  OtpPorWhatsApp,
  CanalDesactivadoError,
  TENTATIVAS_MAXIMAS,
  TTL_MINUTOS,
  Telefone,
  chaveDoEnvio,
  hmacDoCodigo,
  idSequencial,
  type MotivoDeAlerta,
} from "../src/inscricao/index.ts";
import { CodigoOtp, FakeSmsProvider, MASCARA, validarChave } from "../src/sms/index.ts";

const CHAVE = Buffer.alloc(32, 0x5a);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);
const CASO = idSequencial(1);
const OUTRO_CASO = idSequencial(2);

/** Um relógio que só anda quando o ensaio o manda andar. */
function relogioFalso(inicio = "2026-11-08T10:00:00.000Z") {
  let agora = new Date(inicio).getTime();
  return {
    agora: (): Date => new Date(agora),
    avancar: (ms: number): void => {
      agora += ms;
    },
  };
}

interface Montagem {
  readonly otp: Otp;
  readonly sms: FakeSmsProvider;
  readonly repositorio: OtpEmMemoria;
  readonly contadores: ContadoresEmMemoria;
  readonly alertas: MotivoDeAlerta[];
  readonly relogio: ReturnType<typeof relogioFalso>;
  readonly telefone: Telefone;
}

function montar(opcoes: { readonly orcamentoDiario?: number } = {}): Montagem {
  const relogio = relogioFalso();
  const sms = new FakeSmsProvider({ relogio: relogio.agora });
  const repositorio = new OtpEmMemoria();
  const contadores = new ContadoresEmMemoria();
  const alertas: MotivoDeAlerta[] = [];
  const otp = new Otp({
    repositorio,
    contadores,
    provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: CHAVE,
    relogio: relogio.agora,
    alerta: (motivo) => alertas.push(motivo),
    ...(opcoes.orcamentoDiario === undefined ? {} : { orcamentoDiario: opcoes.orcamentoDiario }),
  });
  return {
    otp,
    sms,
    repositorio,
    contadores,
    alertas,
    relogio,
    telefone: new Telefone("+244000000001", CHAVE),
  };
}

/** O código em claro que o `fake` guardou, lido do corpo do SMS. */
function codigoDoUltimoSms(sms: FakeSmsProvider): string {
  const corpo = sms.enviados.at(-1)?.corpo ?? "";
  const achado = /([0-9]{6})/.exec(corpo);
  assert.ok(achado !== null, `o corpo nao tem codigo: ${corpo}`);
  return achado[1] as string;
}

describe("inscricao: o codigo e a sua forma (criterio 5)", () => {
  it("os limiares sao os do critetio, e sao propostas", () => {
    assert.equal(DIGITOS, 6);
    assert.equal(TTL_MINUTOS, 5);
    assert.equal(TENTATIVAS_MAXIMAS, 5);
    assert.equal(ENVIOS_POR_JANELA, 3);
    assert.equal(INTERVALO_SEGUNDOS, 60);
  });

  it("gera seis algarismos e manda UM SMS", async () => {
    const m = montar();
    const resultado = await m.otp.enviar(CASO, m.telefone);
    assert.ok(resultado.enviado);
    assert.equal(m.sms.quantosSairam, 1);
    assert.match(codigoDoUltimoSms(m.sms), /^[0-9]{6}$/);
  });

  it("o SMS vai para o HMAC do destino do KAM-116, e nao para o da inscricao", () => {
    // Os dois existem e sao diferentes de proposito: um identifica a pessoa
    // dentro do onboarding, o outro o endereco dentro do agregador. O ficheiro
    // `provedores.ts` e o unico sitio onde os dois espacos se tocam.
    const telefone = new Telefone("+244000000001", CHAVE);
    assert.match(telefone.hmac, /^[0-9a-f]{64}$/);
    assert.notEqual(telefone.hmac, new Telefone("+244000000001", PEPPER_DO_DESTINO).hmac);
  });

  it("guarda SO o HMAC, e o HMAC esta preso ao caso", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    const codigo = codigoDoUltimoSms(m.sms);
    const guardado = await m.repositorio.actual(CASO);
    assert.ok(guardado !== null);
    assert.match(guardado.codigoHmac, /^[0-9a-f]{64}$/);
    assert.ok(!guardado.codigoHmac.includes(codigo), "o codigo nao aparece no que fica guardado");
    assert.equal(guardado.codigoHmac, hmacDoCodigo(CHAVE, CASO, codigo));
    // **A prisao ao caso e o isolamento**: o mesmo codigo noutro caso da outro
    // HMAC, pelo que o codigo do caso A nunca verifica no caso B.
    assert.notEqual(hmacDoCodigo(CHAVE, OUTRO_CASO, codigo), guardado.codigoHmac);
  });

  it("o codigo nao se diz por extenso: o CodigoOtp mascara", () => {
    const codigo = new CodigoOtp("123456");
    assert.equal(`${codigo}`, MASCARA);
    assert.equal(JSON.stringify({ codigo }), `{"codigo":"${MASCARA}"}`);
  });

  it("a chave do envio e deterministica por desafio e tem forma de chave", async () => {
    const m = montar();
    const resultado = await m.otp.enviar(CASO, m.telefone);
    assert.ok(resultado.enviado);
    const esperada = chaveDoEnvio(CASO, resultado.expiraEm);
    assert.equal(m.sms.enviados.at(-1)?.chave, esperada);
    assert.equal(validarChave(esperada), esperada);
    // **Nao leva o codigo nem o HMAC dele**: a chave viaja para o agregador.
    assert.ok(!esperada.includes(codigoDoUltimoSms(m.sms)));
  });

  it("o codigo de um caso NAO verifica noutro caso", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    const codigo = codigoDoUltimoSms(m.sms);
    m.relogio.avancar(INTERVALO_SEGUNDOS * 1000);
    await m.otp.enviar(OUTRO_CASO, new Telefone("+244000000002", CHAVE));
    assert.equal(await m.otp.verificar(OUTRO_CASO, codigo), "errou");
    assert.equal(await m.otp.verificar(CASO, codigo), "acertou");
  });
});

describe("inscricao: validade e tentativas (criterio 5)", () => {
  it("expira ao fim de cinco minutos, e um segundo antes ainda acerta", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    const codigo = codigoDoUltimoSms(m.sms);
    m.relogio.avancar(TTL_MINUTOS * 60_000 - 1000);
    assert.equal(await m.otp.validade(CASO) === null, false);
    assert.equal(await m.otp.verificar(CASO, codigo), "acertou");

    const n = montar();
    await n.otp.enviar(CASO, n.telefone);
    const outro = codigoDoUltimoSms(n.sms);
    n.relogio.avancar(TTL_MINUTOS * 60_000);
    assert.equal(await n.otp.validade(CASO), null);
    assert.equal(await n.otp.verificar(CASO, outro), "expirado");
  });

  it("bloqueia NA quinta tentativa errada, e o desafio morre", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    const certo = codigoDoUltimoSms(m.sms);
    const errado = certo === "000000" ? "111111" : "000000";
    for (let i = 1; i <= TENTATIVAS_MAXIMAS - 1; i += 1) {
      assert.equal(await m.otp.verificar(CASO, errado), "errou", `tentativa ${i}`);
    }
    assert.equal(await m.otp.verificar(CASO, errado), "tentativas");
    // E depois disso nem o codigo certo serve: o desafio foi destruido.
    assert.equal(await m.otp.verificar(CASO, certo), "sem_desafio");
  });

  it("um milhao de tentativas nao passa das cinco", async () => {
    // O ensaio adversarial (c) do bloco pede «forca bruta de OTP (10^6
    // tentativas) bloqueia na 5.a». Correr 10^6 pedidos e medir o mesmo que
    // correr seis: a quinta errada destroi o desafio, e as seguintes nao tem o
    // que atacar. O que se mede e **isso** — e di-lo por escrito em vez de
    // gastar um minuto de CI a provar a mesma coisa um milhao de vezes.
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    const veredictos: string[] = [];
    for (let i = 0; i < 20; i += 1) {
      veredictos.push(await m.otp.verificar(CASO, String(i).padStart(6, "9")));
    }
    assert.deepEqual(
      veredictos.slice(0, 6),
      ["errou", "errou", "errou", "errou", "tentativas", "sem_desafio"],
    );
    assert.ok(veredictos.slice(5).every((v) => v === "sem_desafio"));
  });

  it("a tentativa conta ANTES da comparacao", async () => {
    // Pela ordem inversa, quem fechasse a ligacao a seguir ao pedido tinha
    // tentativas de graca. Mede-se assim: uma tentativa errada ja deixou
    // registo no desafio.
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    await m.otp.verificar(CASO, "000000");
    const guardado = await m.repositorio.actual(CASO);
    assert.equal(guardado?.tentativas, 1);
  });

  it("sem desafio nenhum, qualquer codigo da sem_desafio", async () => {
    const m = montar();
    assert.equal(await m.otp.verificar(CASO, "123456"), "sem_desafio");
    assert.equal(await m.otp.validade(CASO), null);
  });

  it("um codigo que nao e cadeia nao rebenta a comparacao", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    for (const mau of [undefined, null, 123456, {}, []]) {
      assert.equal(await m.otp.verificar(CASO, mau), "errou", JSON.stringify(mau));
      m.relogio.avancar(0);
      await m.repositorio.guardar({
        ...(await m.repositorio.actual(CASO))!,
        tentativas: 0,
      });
    }
  });
});

describe("inscricao: frequencia e intervalo (criterio 5)", () => {
  it("recusa um segundo envio antes dos 60 s, e aceita aos 60", async () => {
    const m = montar();
    assert.ok((await m.otp.enviar(CASO, m.telefone)).enviado);
    m.relogio.avancar(INTERVALO_SEGUNDOS * 1000 - 1);
    const cedo = await m.otp.enviar(CASO, m.telefone);
    assert.deepEqual(cedo, { enviado: false, recusa: "intervalo" });
    assert.equal(m.sms.quantosSairam, 1, "o SMS nao saiu");
    m.relogio.avancar(1);
    assert.ok((await m.otp.enviar(CASO, m.telefone)).enviado);
    assert.equal(m.sms.quantosSairam, 2);
  });

  it("tres envios por hora e por telefone, e o quarto recusa", async () => {
    const m = montar();
    for (let i = 0; i < ENVIOS_POR_JANELA; i += 1) {
      assert.ok((await m.otp.enviar(CASO, m.telefone)).enviado, `envio ${i + 1}`);
      m.relogio.avancar(INTERVALO_SEGUNDOS * 1000);
    }
    assert.deepEqual(await m.otp.enviar(CASO, m.telefone), {
      enviado: false,
      recusa: "frequencia",
    });
    assert.equal(m.sms.quantosSairam, ENVIOS_POR_JANELA);
  });

  it("a janela desliza: passada a hora, volta a aceitar", async () => {
    const m = montar();
    for (let i = 0; i < ENVIOS_POR_JANELA; i += 1) {
      await m.otp.enviar(CASO, m.telefone);
      m.relogio.avancar(INTERVALO_SEGUNDOS * 1000);
    }
    m.relogio.avancar(3_600_000);
    assert.ok((await m.otp.enviar(CASO, m.telefone)).enviado);
  });

  it("o limite e POR TELEFONE e nao por caso", async () => {
    // Um limite por caso nao travava nada: abrir um caso novo e de graca, e o
    // que se esta a proteger e o telemovel de uma pessoa.
    const m = montar();
    for (let i = 0; i < ENVIOS_POR_JANELA; i += 1) {
      await m.otp.enviar(idSequencial(10 + i), m.telefone);
      m.relogio.avancar(INTERVALO_SEGUNDOS * 1000);
    }
    assert.deepEqual(await m.otp.enviar(idSequencial(99), m.telefone), {
      enviado: false,
      recusa: "frequencia",
    });
    // E outro telefone nao e afectado pelo limite do primeiro.
    assert.ok((await m.otp.enviar(idSequencial(98), new Telefone("+244000000002", CHAVE))).enviado);
  });
});

describe("inscricao: o disjuntor do orcamento de SMS (criterio 6)", () => {
  it("o orcamento por omissao e o do modulo, e e proposta", () => {
    assert.equal(ORCAMENTO_DIARIO, 500);
  });

  it("ao esgotar, os envios pausam e ha alerta", async () => {
    const m = montar({ orcamentoDiario: 2 });
    for (let i = 0; i < 2; i += 1) {
      assert.ok((await m.otp.enviar(idSequencial(20 + i), new Telefone(`+24400000000${i + 1}`, CHAVE))).enviado);
    }
    assert.equal(await m.otp.disjuntorAberto(), true);
    const recusado = await m.otp.enviar(idSequencial(30), new Telefone("+244000000003", CHAVE));
    assert.deepEqual(recusado, { enviado: false, recusa: "orcamento" });
    assert.equal(m.sms.quantosSairam, 2, "nenhum SMS a mais saiu");
    assert.deepEqual(m.alertas, ["orcamento_de_sms_esgotado"]);
  });

  it("alerta UMA vez por janela, e nao uma vez por recusa", async () => {
    const m = montar({ orcamentoDiario: 1 });
    await m.otp.enviar(idSequencial(21), new Telefone("+244000000001", CHAVE));
    for (let i = 0; i < 5; i += 1) {
      await m.otp.enviar(idSequencial(40 + i), new Telefone("+244000000002", CHAVE));
      m.relogio.avancar(60_000);
    }
    assert.deepEqual(m.alertas, ["orcamento_de_sms_esgotado"]);
  });

  it("um caso ja aberto nao se perde: o desafio vivo continua a valer", async () => {
    // E o «sem perder casos ja abertos» do criterio 6: o disjuntor recusa
    // ENVIOS, nao invalida desafios.
    const m = montar({ orcamentoDiario: 1 });
    await m.otp.enviar(CASO, m.telefone);
    const codigo = codigoDoUltimoSms(m.sms);
    await m.otp.enviar(OUTRO_CASO, new Telefone("+244000000002", CHAVE));
    assert.equal(await m.otp.disjuntorAberto(), true);
    assert.equal(await m.otp.verificar(CASO, codigo), "acertou");
  });

  it("passado o dia, o disjuntor fecha", async () => {
    const m = montar({ orcamentoDiario: 1 });
    await m.otp.enviar(CASO, m.telefone);
    assert.equal(await m.otp.disjuntorAberto(), true);
    m.relogio.avancar(86_400_001);
    assert.equal(await m.otp.disjuntorAberto(), false);
    assert.ok((await m.otp.enviar(OUTRO_CASO, new Telefone("+244000000002", CHAVE))).enviado);
  });

  it("o orcamento consome-se ANTES do envio, e e o que faz dele um tecto", async () => {
    // Com o consumo depois, um `await` entre a decisao e a resposta deixava
    // passar tantos envios quantos pedidos concorrentes houvesse. Mede-se
    // lancando-os todos de uma vez.
    const m = montar({ orcamentoDiario: 3 });
    const resultados = await Promise.all(
      [1, 2, 3, 4, 5, 6].map((i) =>
        m.otp.enviar(idSequencial(50 + i), new Telefone(`+24400000000${i}`, CHAVE)),
      ),
    );
    assert.equal(resultados.filter((r) => r.enviado).length, 3);
    assert.equal(m.sms.quantosSairam, 3);
  });
});

describe("inscricao: os canais de OTP", () => {
  it("o whatsapp existe e LEVANTA, ate a D10", async () => {
    const provedor = new OtpPorWhatsApp();
    assert.equal(provedor.canal, "whatsapp");
    await assert.rejects(
      () => provedor.enviar(),
      (erro: unknown) => erro instanceof CanalDesactivadoError && erro.canal === "whatsapp",
    );
  });

  it("o sms_local e o canal activo e usa o modelo fechado do KAM-116", async () => {
    const m = montar();
    await m.otp.enviar(CASO, m.telefone);
    assert.equal(m.sms.enviados.at(-1)?.modelo, "otp_posse_telefone");
  });
});

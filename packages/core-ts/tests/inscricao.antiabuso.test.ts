/**
 * A bateria do anti-abuso (KAM-086, critério 7).
 *
 * **Não mede o critério 1**, e o cabeçalho dizia que media: o *token* de
 * `/entrar` vive inteiramente no `./inscricao.token.test.ts`, e este ficheiro
 * não tem uma única chamada ao `cunharToken`. Achado da revisão adversarial, a
 * contar com um `grep`.
 *
 * ## O que esta bateria mede, e o que **não** consegue medir
 *
 * Mede as barreiras uma a uma: a assinatura do desafio, o tempo mínimo, o
 * *honeypot*, os bits da prova, a dificuldade adaptativa e as duas janelas de
 * contagem. **Não** mede que elas estão ligadas ao pedido HTTP — isso é
 * `services/onboarding-web/tests/registo.test.ts`, e a diferença não é
 * formalidade: um limite que se exercita chamando o contador que o ensaio
 * próprio incrementa fica verde com a chamada apagada do caminho de registo. As
 * duas baterias existem porque falham por razões diferentes.
 *
 * ## A dificuldade dos ensaios é baixa, e o número está dito
 *
 * A prova de trabalho a 12 bits (o `DIFICULDADE_BASE`) custa ~4 096 resumos por
 * submissão. Os ensaios que só precisam de uma prova **válida** correm a 4 bits,
 * e há um que mede a 12 para prender o custo real. Baixar a dificuldade num
 * ensaio é legítimo; baixá-la no código era desfazer a barreira, e por isso o
 * valor por omissão é afirmado à parte.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AbusoError,
  AntiAbuso,
  CASOS_POR_DISPOSITIVO,
  CASOS_POR_REDE,
  ContadoresEmMemoria,
  DIFICULDADE_BASE,
  DIFICULDADE_MAXIMA,
  DOMINIO_DA_PROVA,
  DOMINIO_DO_DESAFIO,
  NOME_DO_HONEYPOT,
  SEGUNDOS_MINIMOS,
  VALIDADE_DO_DESAFIO_S,
  resolverDesafio,
  resumoDaProva,
  zerosACabeca,
} from "../src/inscricao/index.ts";

const CHAVE = Buffer.alloc(32, 0x5a);
const OUTRA_CHAVE = Buffer.alloc(32, 0x3c);
const REDE = "a".repeat(64);
const OUTRA_REDE = "b".repeat(64);

function relogioFalso(inicio = "2026-11-08T10:00:00.000Z") {
  let agora = new Date(inicio).getTime();
  return {
    agora: (): Date => new Date(agora),
    avancar: (ms: number): void => {
      agora += ms;
    },
  };
}

function montar(dificuldadeBase = 4) {
  const relogio = relogioFalso();
  const contadores = new ContadoresEmMemoria();
  const antiabuso = new AntiAbuso({
    contadores,
    chave: CHAVE,
    relogio: relogio.agora,
    dificuldadeBase,
  });
  return { antiabuso, contadores, relogio };
}

function capturar(fn: () => unknown): Error {
  try {
    fn();
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a chamada nao levantou" });
}

async function capturarAsync(promessa: Promise<unknown>): Promise<Error> {
  try {
    await promessa;
  } catch (erro) {
    return erro as Error;
  }
  throw new assert.AssertionError({ message: "a promessa nao rejeitou" });
}

describe("inscricao: a prova de trabalho (criterio 7)", () => {
  it("os limiares por omissao sao os do modulo, e sao propostas", () => {
    assert.equal(DIFICULDADE_BASE, 12);
    assert.equal(DIFICULDADE_MAXIMA, 20);
    assert.equal(SEGUNDOS_MINIMOS, 3);
    assert.equal(CASOS_POR_REDE, 5);
    assert.equal(CASOS_POR_DISPOSITIVO, 3);
    // Dez minutos e nao trinta, e a razao esta no modulo: a validade de um
    // desafio reutilizavel e a janela em que uma prova resolvida compra
    // submissoes ilimitadas naquela rede.
    assert.equal(VALIDADE_DO_DESAFIO_S, 600);
  });

  it("um desafio de OUTRA rede e recusado, e a escada de dificuldade depende disso", async () => {
    // **O achado que tornava a dificuldade adaptativa decorativa.** O texto
    // assinado nao levava o `redeHmac`, pelo que um desafio emitido para uma
    // rede limpa — ou para uma que nao se percebe, onde a dificuldade e a base —
    // servia em QUALQUER rede durante a validade inteira, mesmo nas que ja
    // tinham subido para 20 bits.
    const m = montar();
    const daRede = await m.antiabuso.emitir(REDE);
    const semRede = await m.antiabuso.emitir(null);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);

    for (const [desafio, rede] of [
      [daRede, OUTRA_REDE],
      [daRede, null],
      [semRede, REDE],
    ] as const) {
      const erro = await capturarAsync(
        m.antiabuso.verificar({
          desafio: desafio.desafio,
          solucao: resolverDesafio(desafio.desafio, desafio.dificuldade),
          redeHmac: rede,
          dispositivoHmac: null,
        }),
      );
      assert.ok(erro instanceof AbusoError);
      assert.equal(erro.recusa, "desafio_de_outra_rede");
    }
    // E na rede certa passa, nos dois casos.
    await m.antiabuso.verificar({
      desafio: daRede.desafio,
      solucao: resolverDesafio(daRede.desafio, daRede.dificuldade),
      redeHmac: REDE,
      dispositivoHmac: null,
    });
    await m.antiabuso.verificar({
      desafio: semRede.desafio,
      solucao: resolverDesafio(semRede.desafio, semRede.dificuldade),
      redeHmac: null,
      dispositivoHmac: null,
    });
  });

  it("os dois dominios sao diferentes, e nao e cosmetico", () => {
    // Com o mesmo dominio, uma prova valida era uma oracle sobre o HMAC do
    // desafio: o cliente calcula o resumo e o servidor assina com a mesma
    // cadeia a prefixar.
    assert.equal(DOMINIO_DO_DESAFIO, "kamba/onboarding/pow/v1");
    assert.equal(DOMINIO_DA_PROVA, "kamba/onboarding/pow-prova/v1");
    assert.notEqual(DOMINIO_DO_DESAFIO, DOMINIO_DA_PROVA);
  });

  it("conta os bits a cabeca e nao os hexadecimais", () => {
    assert.equal(zerosACabeca(Buffer.from([0xff])), 0);
    assert.equal(zerosACabeca(Buffer.from([0x7f])), 1);
    assert.equal(zerosACabeca(Buffer.from([0x0f])), 4);
    assert.equal(zerosACabeca(Buffer.from([0x00, 0x80])), 8);
    assert.equal(zerosACabeca(Buffer.from([0x00, 0x00, 0x01])), 23);
  });

  it("uma submissao com prova valida passa", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const solucao = resolverDesafio(emitido.desafio, emitido.dificuldade);
    const lido = await m.antiabuso.verificar({
      desafio: emitido.desafio,
      solucao,
      redeHmac: REDE,
      dispositivoHmac: null,
    });
    assert.equal(lido.dificuldade, emitido.dificuldade);
    assert.ok(zerosACabeca(resumoDaProva(emitido.desafio, solucao)) >= emitido.dificuldade);
  });

  it("uma solucao errada e recusada, e uma do desafio ao lado tambem", async () => {
    const m = montar();
    const um = await m.antiabuso.emitir(REDE);
    const outro = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const solucaoDoOutro = resolverDesafio(outro.desafio, outro.dificuldade);
    for (const solucao of ["0", "x".repeat(65), solucaoDoOutro]) {
      const erro = await capturarAsync(
        m.antiabuso.verificar({
          desafio: um.desafio,
          solucao,
          redeHmac: REDE,
          dispositivoHmac: null,
        }),
      );
      assert.ok(erro instanceof AbusoError, solucao.slice(0, 8));
      assert.equal(erro.recusa, "prova_invalida", solucao.slice(0, 8));
    }
  });

  it("a prova a 12 bits resolve-se, e o custo fica prendido", () => {
    // Prende o custo real: a 12 bits ha solucao dentro de um tecto baixo. Se
    // alguem subir o `DIFICULDADE_BASE` sem pensar, este ensaio e o que estoura.
    const m = montar(DIFICULDADE_BASE);
    const desafio = "x.1.12.y";
    const solucao = resolverDesafio(desafio, DIFICULDADE_BASE, 1 << 20);
    assert.ok(zerosACabeca(resumoDaProva(desafio, solucao)) >= DIFICULDADE_BASE);
    assert.ok(m.antiabuso.dificuldadeBase === DIFICULDADE_BASE);
  });
});

describe("inscricao: o desafio e assinado, e e isso que faz o tempo minimo valer", () => {
  it("um desafio forjado nao passa", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const partes = emitido.desafio.split(".");
    const forjados = [
      // Assinado por outra chave.
      (await new AntiAbuso({
        contadores: new ContadoresEmMemoria(),
        chave: OUTRA_CHAVE,
        relogio: m.relogio.agora,
        dificuldadeBase: 4,
      }).emitir(REDE)).desafio,
      // O instante empurrado para tras, para passar o tempo minimo.
      `${partes[0]}.${Number(partes[1]) - 600}.${partes[2]}.${partes[3]}`,
      // A dificuldade baixada a mao.
      `${partes[0]}.${partes[1]}.0.${partes[3]}`,
      // Deformados.
      "",
      "a.b.c.d",
      `${partes[0]}.${partes[1]}.${partes[2]}`,
      "x".repeat(300),
    ];
    for (const desafio of forjados) {
      const erro = await capturarAsync(
        m.antiabuso.verificar({ desafio, solucao: "0", redeHmac: REDE, dispositivoHmac: null }),
      );
      assert.ok(erro instanceof AbusoError, desafio.slice(0, 20));
      assert.equal(erro.recusa, "desafio_invalido", desafio.slice(0, 20));
    }
  });

  it("o instante vem DE DENTRO do desafio: nao da para dizer que se demorou", async () => {
    // E a razao de ser do desenho. Um campo `abertoEm` que o cliente devolvesse
    // era um campo que o cliente escolhe, e o tempo minimo nao travava nada. O
    // ensaio de cima prova que empurrar o instante quebra a assinatura; este
    // prova que, com o instante genuino, o tempo minimo morde.
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    const solucao = resolverDesafio(emitido.desafio, emitido.dificuldade);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000 - 1);
    const erro = await capturarAsync(
      m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao,
        redeHmac: REDE,
        dispositivoHmac: null,
      }),
    );
    assert.ok(erro instanceof AbusoError);
    assert.equal(erro.recusa, "depressa");
    m.relogio.avancar(1);
    await m.antiabuso.verificar({
      desafio: emitido.desafio,
      solucao,
      redeHmac: REDE,
      dispositivoHmac: null,
    });
  });

  it("um desafio velho expira", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    const solucao = resolverDesafio(emitido.desafio, emitido.dificuldade);
    m.relogio.avancar(VALIDADE_DO_DESAFIO_S * 1000 + 1);
    const erro = await capturarAsync(
      m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao,
        redeHmac: REDE,
        dispositivoHmac: null,
      }),
    );
    assert.equal((erro as AbusoError).recusa, "desafio_expirado");
  });

  it("um relogio que andou atras nao da um desafio valido", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    const solucao = resolverDesafio(emitido.desafio, emitido.dificuldade);
    m.relogio.avancar(-60_000);
    const erro = await capturarAsync(
      m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao,
        redeHmac: REDE,
        dispositivoHmac: null,
      }),
    );
    assert.equal((erro as AbusoError).recusa, "depressa");
  });
});

describe("inscricao: o honeypot (criterio 7)", () => {
  it("recusa ANTES de verificar a prova, e com solucao vazia", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const erro = await capturarAsync(
      m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao: "",
        honeypot: "Loja do bairro",
        redeHmac: REDE,
        dispositivoHmac: null,
      }),
    );
    assert.ok(erro instanceof AbusoError);
    // `honeypot` e nao `prova_invalida`: um bot que se denunciou nao nos faz
    // gastar um SHA-256 antes de ser recusado.
    assert.equal(erro.recusa, "honeypot");
  });

  it("vazio, em branco ou ausente passa", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const solucao = resolverDesafio(emitido.desafio, emitido.dificuldade);
    for (const honeypot of ["", "   ", undefined]) {
      await m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao,
        ...(honeypot === undefined ? {} : { honeypot }),
        redeHmac: REDE,
        dispositivoHmac: null,
      });
    }
  });

  it("o nome do campo parece um campo a serio", () => {
    // Um `honeypot` chamado `honeypot` e um campo que um bot ignora.
    assert.equal(NOME_DO_HONEYPOT, "empresa_alternativa");
    assert.ok(!NOME_DO_HONEYPOT.includes("honey"));
  });
});

describe("inscricao: os limites por rede e por dispositivo (criterios 7 e 8)", () => {
  it("cinco casos por hora e por prefixo, e o sexto recusa", async () => {
    const m = montar();
    for (let i = 0; i < CASOS_POR_REDE; i += 1) {
      await m.antiabuso.consumir(REDE, null);
    }
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const erro = await capturarAsync(
      m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        redeHmac: REDE,
        dispositivoHmac: null,
      }),
    );
    assert.ok(erro instanceof AbusoError);
    assert.equal(erro.recusa, "limite_de_rede");
  });

  it("o limite e por prefixo: outra rede nao paga pelo vizinho", async () => {
    const m = montar();
    for (let i = 0; i < CASOS_POR_REDE * 3; i += 1) await m.antiabuso.consumir(REDE, null);
    const emitido = await m.antiabuso.emitir(OUTRA_REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    await m.antiabuso.verificar({
      desafio: emitido.desafio,
      solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
      redeHmac: OUTRA_REDE,
      dispositivoHmac: null,
    });
  });

  it("a janela desliza: passada a hora, a rede volta a poder", async () => {
    const m = montar();
    for (let i = 0; i < CASOS_POR_REDE; i += 1) await m.antiabuso.consumir(REDE, null);
    m.relogio.avancar(3_600_001);
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    await m.antiabuso.verificar({
      desafio: emitido.desafio,
      solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
      redeHmac: REDE,
      dispositivoHmac: null,
    });
  });

  it("o `verificar` NAO consome quota, e e deliberado", async () => {
    // Contar tentativas aqui dava ao atacante a maneira de esgotar a quota de
    // uma rede inteira sem criar caso nenhum — uma recusa de servico a um
    // bairro. Quem consome e o `consumir`, depois de o caso existir.
    const m = montar();
    for (let i = 0; i < 20; i += 1) {
      const emitido = await m.antiabuso.emitir(REDE);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
      await m.antiabuso.verificar({
        desafio: emitido.desafio,
        solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        redeHmac: REDE,
        dispositivoHmac: null,
      });
    }
    const emitido = await m.antiabuso.emitir(REDE);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    await m.antiabuso.verificar({
      desafio: emitido.desafio,
      solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
      redeHmac: REDE,
      dispositivoHmac: null,
    });
  });

  it("o `consumir` devolve as duas contagens do criterio 8", async () => {
    const m = montar();
    const um = await m.antiabuso.consumir(REDE, "d".repeat(64));
    assert.deepEqual(um, { naRede: 1, noDispositivo: 1 });
    const dois = await m.antiabuso.consumir(REDE, "d".repeat(64));
    assert.deepEqual(dois, { naRede: 2, noDispositivo: 2 });
    const semNada = await m.antiabuso.consumir(null, null);
    assert.deepEqual(semNada, { naRede: 0, noDispositivo: 0 });
  });
});

describe("inscricao: a dificuldade adaptativa (criterio 7)", () => {
  it("uma rede limpa paga a base", async () => {
    const m = montar();
    assert.equal(await m.antiabuso.dificuldadePara(REDE), 4);
    assert.equal(await m.antiabuso.dificuldadePara(null), 4);
  });

  it("sobe com os registos recentes da REDE, e nao do cliente", async () => {
    const m = montar();
    const degraus: number[] = [];
    for (let i = 0; i < 16; i += 1) {
      await m.antiabuso.consumir(REDE, null);
      degraus.push(await m.antiabuso.dificuldadePara(REDE));
    }
    // Um bit por duplicacao: 1 registo -> +1, 3 -> +2, 7 -> +3, 15 -> +4.
    assert.equal(degraus[0], 5);
    assert.equal(degraus[2], 6);
    assert.equal(degraus[6], 7);
    assert.equal(degraus[14], 8);
    // E a rede ao lado continua na base: trocar de `User-Agent` nao baixa isto.
    assert.equal(await m.antiabuso.dificuldadePara(OUTRA_REDE), 4);
  });

  it("tem tecto, para um telefone antigo nao desistir", async () => {
    const m = montar();
    const contadores = new ContadoresEmMemoria();
    const limitado = new AntiAbuso({
      contadores,
      chave: CHAVE,
      relogio: m.relogio.agora,
      dificuldadeBase: 4,
      dificuldadeMaxima: 6,
    });
    for (let i = 0; i < 200; i += 1) await limitado.consumir(REDE, null);
    assert.equal(await limitado.dificuldadePara(REDE), 6);
  });

  it("o `resolverDesafio` levanta em voz alta se nao encontrar", () => {
    const erro = capturar(() => resolverDesafio("x.1.30.y", 30, 32));
    assert.match(erro.message, /nao encontrei solucao com 30 bits em 32 tentativas/);
  });
});

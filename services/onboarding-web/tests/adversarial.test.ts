/**
 * A suite adversarial (a)–(f) do KAM-086, pela superfície HTTP.
 *
 * O bloco enumera-a por extenso nos *Testes Requeridos*:
 *
 *     (a) bot: 1.000 registos em 60 s a partir de 50 prefixos de IP => nenhum
 *         prefixo cria > 5 casos/h, SMS enviados <= orcamento, 0 casos chegam a fila
 *     (b) matriz de 12 duplicados bloqueada
 *     (c) forca bruta de OTP (10^6 tentativas) bloqueia na 5.a
 *     (d) SMS pumping com numeros nao +244 rejeitados
 *     (e) token de convite reutilizado ou forjado
 *     (f) enumeracao por tempo de resposta
 *
 * ## Duas das seis não se correm ao pé da letra, e o número está dito
 *
 * O **(c)** pede 10⁶ tentativas. A quinta tentativa errada **destrói** o
 * desafio, e as seguintes não têm o que atacar: 10⁶ pedidos medem o mesmo que
 * seis, e gastariam minutos de CI a provar a mesma coisa um milhão de vezes.
 * Corre-se um lote curto e afirma-se o que ele mede.
 *
 * O **(e)** não é um ataque na forma em que está escrito, e isso tem de ser
 * dito em vez de disfarçado: o *token* de `/entrar` **não é de uso único por
 * desenho** — a origem `anuncio` é uma ligação que muita gente abre, e a origem
 * `contabilista` é uma ligação que um contabilista dá a vários clientes. A
 * metade que é um ataque — o *token* **forjado** — mede-se, e a metade do
 * «reutilizado» mede-se como ela é: um *token* bom usado mil vezes está limitado
 * pelos limites de rede e de dispositivo, não pelo *token*.
 *
 * ## Os números de ensaio começam por zero
 *
 * Um E.164 nacional nunca começa por `0`. Ver a nota do
 * `./registo.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  Actividade,
  AntiAbuso,
  CASOS_POR_REDE,
  CasosEmMemoria,
  ContadoresEmMemoria,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  Registo,
  SEGUNDOS_MINIMOS,
  TENTATIVAS_MAXIMAS,
  Telefone,
  cunharToken,
  lerReferencia,
  resolverDesafio,
  type Caso,
} from "@kamba/core-ts/inscricao";
import { FakeSmsProvider } from "@kamba/core-ts/sms";

import { createApp } from "../src/app.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const ASSINATURA = Buffer.alloc(32, 0x3c);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);
const ORCAMENTO = 500;

/** O (a) do bloco, por extenso. */
const PEDIDOS = 1000;
const PREFIXOS = 50;
const JANELA_MS = 60_000;

function relogioFalso(inicio = "2026-11-08T10:00:00.000Z") {
  const base = new Date(inicio).getTime();
  let agora = base;
  return {
    base,
    agora: (): Date => new Date(agora),
    avancar: (ms: number): void => {
      agora += ms;
    },
    poisar: (ms: number): void => {
      agora = base + ms;
    },
  };
}

function montar(proxies = 1) {
  const relogio = relogioFalso();
  const casos = new CasosEmMemoria(relogio.agora);
  const contadores = new ContadoresEmMemoria();
  const sms = new FakeSmsProvider({ relogio: relogio.agora });
  const antiabuso = new AntiAbuso({
    contadores,
    chave: PEPPER,
    relogio: relogio.agora,
    dificuldadeBase: 4,
  });
  const otp = new Otp({
    repositorio: new OtpEmMemoria(),
    contadores,
    provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: PEPPER,
    relogio: relogio.agora,
    orcamentoDiario: ORCAMENTO,
  });
  const registo = new Registo({
    repositorio: casos,
    antiabuso,
    otp,
    anelDoPepper: [PEPPER, null],
    anelDoToken: [ASSINATURA, null],
    anelDaSessao: [ASSINATURA, null],
    relogio: relogio.agora,
  });
  const actividade = new Actividade({ repositorio: casos, contadores, relogio: relogio.agora });
  const app = createApp(undefined, {
    registo,
    otp,
    actividade,
    antiabuso,
    anelDaAssinatura: [ASSINATURA, null],
    anelDoToken: [ASSINATURA, null],
    relogio: relogio.agora,
    proxiesDeConfianca: proxies,
  });
  return { app, casos, sms, relogio, antiabuso, otp, registo };
}

type Montagem = ReturnType<typeof montar>;

function token(m: Montagem): string {
  return cunharToken(
    "anuncio",
    new Date(m.relogio.agora().getTime() + 86_400_000),
    ASSINATURA,
    m.relogio.agora,
  );
}

/** Um NIF e um telefone distintos por índice. Ver a nota do módulo. */
function identidade(i: number): { readonly nif: string; readonly telefone: string } {
  const oito = String(i).padStart(8, "0");
  return { nif: `54${oito}AB`, telefone: `+2440${oito}` };
}

async function json(resposta: Response): Promise<Record<string, unknown>> {
  return (await resposta.json()) as Record<string, unknown>;
}

describe("KAM-086 adversarial (a): mil registos de 50 prefixos em 60 s", () => {
  it("nenhum prefixo cria mais de cinco casos, os SMS ficam no orcamento, e 0 casos vao a fila", async () => {
    const m = montar();
    const convite = token(m);

    // **Os desafios emitem-se todos primeiro**, e isso nao e conveniencia do
    // ensaio: e o que um bot faz. Pedir os mil desafios e so depois submeter e a
    // maneira de contornar o tempo minimo de preenchimento — pelo que a versao
    // mais forte deste ensaio e esta, e nao uma que pague tres segundos por
    // pedido. O que trava o bot e o **limite por prefixo**; a prova de trabalho
    // so lhe encarece cada tentativa.
    const prontos: { readonly indice: number; readonly ip: string; readonly corpo: string }[] = [];
    for (let i = 0; i < PEDIDOS; i += 1) {
      const ip = `198.51.${Math.floor(i % PREFIXOS)}.9`;
      // **Um desafio por prefixo, e nao um desafio sem rede.** O desafio esta
      // preso a rede que o emitiu desde o achado da revisao adversarial, pelo
      // que um emitido com `null` nao serve num pedido com IP. Emitir todos
      // primeiro continua a ser o que um bot faz, e e o que torna este ensaio a
      // versao mais forte: o que o trava e o limite por prefixo.
      const emitido = await m.registo.desafioPara(ip);
      const { nif, telefone } = identidade(i);
      prontos.push({
        indice: i,
        ip,
        corpo: JSON.stringify({
          token: convite,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif,
          telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
    }

    // A janela de sessenta segundos comeca depois do tempo minimo.
    const passo = JANELA_MS / PEDIDOS;
    const estados = new Map<number, number>();
    for (const pronto of prontos) {
      m.relogio.poisar(SEGUNDOS_MINIMOS * 1000 + Math.floor(pronto.indice * passo));
      const resposta = await m.app.request("/api/registo", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `chave-bot-${String(pronto.indice).padStart(5, "0")}`,
          "x-forwarded-for": pronto.ip,
        },
        body: pronto.corpo,
      });
      estados.set(resposta.status, (estados.get(resposta.status) ?? 0) + 1);
    }

    // 1. Nenhum prefixo criou mais de cinco casos.
    const porRede = new Map<string, number>();
    for (const caso of m.casos.todos) {
      const chave = caso.redeHmac ?? "sem-rede";
      porRede.set(chave, (porRede.get(chave) ?? 0) + 1);
    }
    assert.equal(porRede.size, PREFIXOS, "os cinquenta prefixos distinguem-se");
    for (const [rede, quantos] of porRede) {
      assert.ok(quantos <= CASOS_POR_REDE, `${rede.slice(0, 8)} criou ${quantos}`);
    }
    assert.equal(m.casos.quantos, PREFIXOS * CASOS_POR_REDE);
    assert.equal(estados.get(200), PREFIXOS * CASOS_POR_REDE);
    assert.equal(estados.get(429), PEDIDOS - PREFIXOS * CASOS_POR_REDE);

    // 2. Os SMS ficaram no orcamento.
    assert.ok(m.sms.quantosSairam <= ORCAMENTO, `sairam ${m.sms.quantosSairam} SMS`);
    assert.equal(m.sms.quantosSairam, m.casos.quantos);

    // 3. Zero casos chegam a fila de revisao.
    const comMarca = m.casos.todos.filter((c) => c.flags.length > 0);
    assert.deepEqual(comMarca, [], "nenhum caso marcado duplicado_ambiguo");
  });
});

describe("KAM-086 adversarial (b): a matriz de doze duplicados", () => {
  it("o primeiro registo passa e as outras ONZE grafias nao criam caso novo", async () => {
    // As doze grafias estao medidas uma a uma em
    // `packages/core-ts/tests/inscricao.identificadores.test.ts`; o que este
    // ensaio acrescenta e que a matriz esta **ligada** ao caminho de registo.
    const DOZE_NIFS = [
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
    assert.equal(DOZE_NIFS.length, 12);

    const m = montar(0);
    const convite = token(m);
    const referencias: string[] = [];
    for (const [i, nif] of DOZE_NIFS.entries()) {
      // Uma hora entre pedidos, para o intervalo de 60 s e os tres envios por
      // hora nao mascararem o que se esta a medir.
      m.relogio.avancar(3_600_001);
      const emitido = await m.registo.desafioPara(null);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
      const resposta = await m.app.request("/api/registo", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `chave-dup-${String(i).padStart(4, "0")}`,
        },
        body: JSON.stringify({
          token: convite,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif,
          // Telefone **diferente** em cada tentativa: o que se esta a medir e o
          // NIF. Com o mesmo telefone, a recusa podia vir do telefone.
          telefone: identidade(100 + i).telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
      assert.equal(resposta.status, 200, `grafia ${i}`);
      // **O id le-se AQUI e nao no fim.** O bilhete vale trinta minutos, e este
      // ensaio avanca uma hora entre grafias para nao bater nos limites por
      // telefone: lido no fim, o primeiro bilhete esta expirado ha onze horas.
      referencias.push(
        lerReferencia(
          "ticket",
          String((await json(resposta)).referencia),
          [ASSINATURA, null],
          m.relogio.agora,
        ),
      );
    }

    // **UM** caso para doze grafias.
    assert.equal(m.casos.quantos, 1);
    // E as doze respostas apontam para o **mesmo caso**. Compara-se o id que sai
    // de dentro da referencia e nao a referencia: ela leva a validade dentro do
    // texto assinado desde o achado da revisao adversarial, pelo que duas
    // referencias do mesmo caso emitidas em instantes diferentes **sao** cadeias
    // diferentes. Comparar as cadeias media o relogio, nao o caso.
    assert.equal(new Set(referencias).size, 1);
    assert.equal(referencias[0], (m.casos.todos[0] as Caso).id);
  });

  it("um NIF que difere num algarismo cria caso novo, e e o controlo", async () => {
    // Sem este, a matriz passava com um normalizador que devolvesse sempre a
    // mesma coisa.
    const m = montar(0);
    const convite = token(m);
    for (const [i, nif] of ["5410000123AB", "5410000124AB"].entries()) {
      m.relogio.avancar(3_600_001);
      const emitido = await m.registo.desafioPara(null);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
      await m.app.request("/api/registo", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `chave-ctl-${String(i).padStart(4, "0")}`,
        },
        body: JSON.stringify({
          token: convite,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif,
          telefone: identidade(200 + i).telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
    }
    assert.equal(m.casos.quantos, 2);
  });
});

describe("KAM-086 adversarial (c): forca bruta do OTP", () => {
  it("bloqueia na quinta tentativa, e as seguintes nao tem o que atacar", async () => {
    const m = montar(0);
    const emitido = await m.registo.desafioPara(null);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const aceite = await json(
      await m.app.request("/api/registo", {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": "chave-forca-0001" },
        body: JSON.stringify({
          token: token(m),
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif: "5410000500AB",
          telefone: identidade(300).telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      }),
    );
    const referencia = String(aceite.referencia);
    const certo = /([0-9]{6})/.exec(m.sms.enviados.at(-1)?.corpo ?? "")?.[1] ?? "";

    const veredictos: string[] = [];
    for (let i = 0; i < 50; i += 1) {
      // Os codigos tentados evitam o certo de proposito: o que se mede e o
      // bloqueio e nao a sorte.
      const tentativa = String(i).padStart(6, "9");
      assert.notEqual(tentativa, certo);
      const resposta = await m.app.request("/api/otp/verificar", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ referencia, codigo: tentativa }),
      });
      veredictos.push(String((await json(resposta)).veredicto));
    }
    assert.deepEqual(veredictos.slice(0, TENTATIVAS_MAXIMAS), [
      "errou",
      "errou",
      "errou",
      "errou",
      "tentativas",
    ]);
    assert.ok(veredictos.slice(TENTATIVAS_MAXIMAS).every((v) => v === "sem_desafio"));

    // E o codigo **certo** ja nao serve: um milhao de tentativas a seguir mede
    // exactamente isto.
    const depois = await m.app.request("/api/otp/verificar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia, codigo: certo }),
    });
    assert.equal(String((await json(depois)).veredicto), "sem_desafio");
    assert.equal(depois.headers.get("set-cookie"), null, "nenhuma sessao");
  });
});

describe("KAM-086 adversarial (d): SMS pumping", () => {
  it("numeros fora de +244 sao recusados e NENHUM SMS sai", async () => {
    // O ataque: usar o nosso agregador como rele para destinos que pagam mais
    // caro. A recusa e na cunhagem do destino, antes de haver envio — ver o
    // cabecalho do `packages/core-ts/src/sms/destino.ts`.
    const m = montar(0);
    const estrangeiros = [
      "+351912345678",
      "+1 212 555 0100",
      "+7 495 000 0000",
      "+8812 3456 7890",
      "+88213000000",
      "00351912345678",
      "+9999999999999",
    ];
    for (const [i, telefone] of estrangeiros.entries()) {
      m.relogio.avancar(3_600_001);
      const emitido = await m.registo.desafioPara(null);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
      const resposta = await m.app.request("/api/registo", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `chave-pump-${String(i).padStart(4, "0")}`,
        },
        body: JSON.stringify({
          token: token(m),
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif: `5410009${String(i).padStart(3, "0")}AB`,
          telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
      assert.equal(resposta.status, 400, telefone);
    }
    assert.equal(m.sms.quantosSairam, 0);
    assert.equal(m.casos.quantos, 0);
  });

  it("o orcamento diario e o tecto de gasto, mesmo com numeros validos", async () => {
    // A segunda metade do pumping: destinos validos, em quantidade. O disjuntor
    // e que responde, e o ensaio adversarial (a) ja o mede com mil pedidos.
    const m = montar(0);
    assert.equal(await m.otp.disjuntorAberto(), false);
    for (let i = 0; i < ORCAMENTO + 5; i += 1) {
      m.relogio.avancar(61_000);
      const resultado = await m.otp.enviar(
        `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
        // O destino varia para o limite por telefone nao mascarar o orcamento.
        new Telefone(identidade(400 + i).telefone, PEPPER),
      );
      if (i >= ORCAMENTO) assert.deepEqual(resultado, { enviado: false, recusa: "orcamento" });
    }
    assert.equal(m.sms.quantosSairam, ORCAMENTO);
    assert.equal(await m.otp.disjuntorAberto(), true);
  });
});

describe("KAM-086 adversarial (e): o token de convite", () => {
  it("um token forjado nao abre o ecra nem cria caso", async () => {
    const m = montar(0);
    for (const chave of [Buffer.alloc(32, 0x11), Buffer.alloc(32, 0x00)]) {
      const forjado = cunharToken(
        "convite",
        new Date(m.relogio.agora().getTime() + 86_400_000),
        chave,
        m.relogio.agora,
      );
      assert.equal((await m.app.request(`/entrar?c=${encodeURIComponent(forjado)}`)).status, 403);
      const emitido = await m.registo.desafioPara(null);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
      const resposta = await m.app.request("/api/registo", {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": "chave-forjado-001" },
        body: JSON.stringify({
          token: forjado,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif: "5410000600AB",
          telefone: identidade(500).telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
      assert.equal(resposta.status, 403);
    }
    assert.equal(m.casos.quantos, 0);
  });

  it("um token BOM reutilizado mil vezes esta limitado pela REDE, nao pelo token", async () => {
    // Ver a nota do modulo: o token **nao e de uso unico por desenho** — a
    // origem `anuncio` e uma ligacao que muita gente abre. Afirmar o contrario
    // num ensaio era medir uma propriedade que o produto nao tem. O que se mede
    // e que a reutilizacao nao da mais do que os limites dao.
    const m = montar(1);
    const convite = token(m);
    const ip = "203.0.113.5";
    let aceites = 0;
    for (let i = 0; i < 20; i += 1) {
      // Para a rede do pedido: o desafio esta preso a ela, e com `proxies: 1` a
      // rota le o `x-forwarded-for`.
      const emitido = await m.registo.desafioPara(ip);
      m.relogio.avancar(SEGUNDOS_MINIMOS * 1000 + 61_000);
      const { nif, telefone } = identidade(600 + i);
      const resposta = await m.app.request("/api/registo", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": `chave-reuso-${String(i).padStart(4, "0")}`,
          "x-forwarded-for": ip,
        },
        body: JSON.stringify({
          token: convite,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif,
          telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        }),
      });
      if (resposta.status === 200) aceites += 1;
    }
    assert.equal(aceites, CASOS_POR_REDE);
    assert.equal(m.casos.quantos, CASOS_POR_REDE);
  });
});

describe("KAM-086 adversarial (f): enumeracao por tempo de resposta", () => {
  it("as duas respostas tem o mesmo corpo e as medianas diferem menos de 20 ms", async () => {
    // A metade determinista — o rasto de operacoes de cada caminho — esta em
    // `packages/core-ts/tests/inscricao.registo.test.ts`. Aqui mede-se o que o
    // publico ve: o corpo e o tempo da **rota**.
    //
    // **Contra o adaptador SQL isto e NAO VERIFICADO**: um `INSERT` e um
    // `SELECT` sob RLS `FORCE` nao custam o mesmo. A asercao e sobre a mediana
    // de muitas passagens e nao sobre uma, porque uma passagem num executor
    // partilhado e ruido — e um ensaio intermitente no gate 4 e pior do que
    // nenhum.
    const PASSAGENS = 25;
    const registado: number[] = [];
    const novo: number[] = [];
    const corpos: string[] = [];

    for (let p = 0; p < PASSAGENS; p += 1) {
      const m = montar(0);
      const convite = token(m);
      const pedir = async (nif: string, telefone: string, chave: string): Promise<[number, string]> => {
        // A hora passa-se **antes** de emitir e o tempo minimo depois: um
        // desafio tem validade de VALIDADE_DO_DESAFIO_S (trinta minutos), pelo
        // que avancar uma hora depois de o emitir dava `desafio_expirado` — e a
        // primeira versao deste ensaio ficou vermelha com 400 exactamente por
        // isso. A hora serve para o intervalo de 60 s e os tres envios por hora
        // nao mascararem o que se esta a medir.
        m.relogio.avancar(3_600_001);
        const emitido = await m.registo.desafioPara(null);
        m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
        const corpo = JSON.stringify({
          token: convite,
          nome_negocio: "Loja",
          categoria: "mercearia",
          nif,
          telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
        });
        const t0 = performance.now();
        const resposta = await m.app.request("/api/registo", {
          method: "POST",
          headers: { "content-type": "application/json", "idempotency-key": chave },
          body: corpo,
        });
        const decorrido = performance.now() - t0;
        assert.equal(resposta.status, 200);
        return [decorrido, await resposta.text()];
      };

      await pedir("5410000123AB", identidade(700).telefone, `chave-f-base-${p}00`);
      const [tRegistado, corpoRegistado] = await pedir(
        "5410000123AB",
        identidade(701).telefone,
        `chave-f-reg-${p}00`,
      );
      const [tNovo, corpoNovo] = await pedir(
        "5410000999CD",
        identidade(702).telefone,
        `chave-f-nov-${p}00`,
      );
      registado.push(tRegistado);
      novo.push(tNovo);
      if (p === 0) corpos.push(corpoRegistado, corpoNovo);
    }

    // O corpo: os mesmos campos, e a referencia com o mesmo comprimento.
    const [a, b] = corpos.map((c) => JSON.parse(c) as Record<string, unknown>) as [
      Record<string, unknown>,
      Record<string, unknown>,
    ];
    assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort());
    assert.deepEqual(Object.keys(a).sort(), ["digitos", "referencia", "validade_segundos"]);
    assert.equal(String(a.referencia).length, String(b.referencia).length);
    assert.equal(a.digitos, b.digitos);

    const mediana = (xs: number[]): number => {
      const ordenados = [...xs].sort((x, y) => x - y);
      return ordenados[Math.floor(ordenados.length / 2)] ?? 0;
    };
    const diferenca = Math.abs(mediana(registado) - mediana(novo));
    assert.ok(
      diferenca < 20,
      `a diferenca das medianas foi ${diferenca.toFixed(3)} ms em ${PASSAGENS} passagens`,
    );
  });
});

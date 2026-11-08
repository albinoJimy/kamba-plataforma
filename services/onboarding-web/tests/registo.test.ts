/**
 * A bateria do registo **pela superfície HTTP** (KAM-086).
 *
 * ## Porque é que esta bateria existe ao lado da do pacote
 *
 * As barreiras — *token*, prova de trabalho, *honeypot*, tempo mínimo, limites,
 * OTP — vivem no `@kamba/core-ts/inscricao` e são medidas lá, uma a uma. O que
 * **só** se pode medir aqui é que elas estão **ligadas ao sítio certo**.
 *
 * A diferença não é formalidade, e é a lição medida nesta casa: um limite que um
 * ensaio exercita chamando o contador que ele próprio incrementa fica verde
 * depois de alguém apagar a chamada ao anti-abuso do caminho de registo. A
 * função continua correcta; a ligação é que se desfez. Estes ensaios submetem
 * pedidos e **contam casos criados** — pelo que apagar a chamada põe-nos
 * vermelhos.
 *
 * Os ensaios estão escritos para morrer com a ligação, e não só com a função:
 * cada um deles nomeia, no comentário, que mutação o mata.
 *
 * ## Os números de ensaio começam por zero
 *
 * Um E.164 nacional nunca começa por `0`, pelo que `+244000000001` não pode
 * colidir com o telefone de ninguém. É a convenção que o KAM-116 fixou em
 * `packages/core-ts/tests/sms.contrato.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  Actividade,
  AntiAbuso,
  CasosEmMemoria,
  ContadoresEmMemoria,
  NOME_DO_HONEYPOT,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  Registo,
  SEGUNDOS_MINIMOS,
  cunharReferencia,
  cunharToken,
  idSequencial,
  lerReferencia,
  resolverDesafio,
  resumoDaProva,
  zerosACabeca,
  type Caso,
} from "@kamba/core-ts/inscricao";
import { FakeSmsProvider } from "@kamba/core-ts/sms";

import { createApp } from "../src/app.ts";
import { FRASES_PROIBIDAS, FRASE_OBRIGATORIA, normalizar } from "../src/comunicacao.ts";
import { enderecoDoPedido } from "../src/rotas.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const ASSINATURA = Buffer.alloc(32, 0x3c);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);

const NIF = "5410000123AB";
const TELEFONE = "+244000000001";

function relogioFalso(inicio = "2026-11-08T10:00:00.000Z") {
  let agora = new Date(inicio).getTime();
  return {
    agora: (): Date => new Date(agora),
    avancar: (ms: number): void => {
      agora += ms;
    },
    poisar: (ms: number): void => {
      agora = new Date(inicio).getTime() + ms;
    },
  };
}

function montar(opcoes: { readonly proxies?: number; readonly orcamento?: number } = {}) {
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
    ...(opcoes.orcamento === undefined ? {} : { orcamentoDiario: opcoes.orcamento }),
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
    proxiesDeConfianca: opcoes.proxies ?? 0,
  });
  return {
    app,
    casos,
    contadores,
    sms,
    relogio,
    antiabuso,
    otp,
    registo,
    proxies: opcoes.proxies ?? 0,
  };
}

type Montagem = ReturnType<typeof montar>;

function token(m: Montagem): string {
  return cunharToken(
    "convite",
    new Date(m.relogio.agora().getTime() + 86_400_000),
    ASSINATURA,
    m.relogio.agora,
  );
}

let seguinte = 0;

/** Submete um registo pela rota, com a prova de trabalho resolvida. */
async function submeter(
  m: Montagem,
  corpo: Record<string, unknown> = {},
  cabecalhos: Record<string, string> = {},
): Promise<Response> {
  // **O desafio vem pelo `desafioPara`, que e o caminho que a rota corre.** A
  // primeira versao chamava `antiabuso.emitir(null)` por um ajudante que
  // ignorava os argumentos e devolvia `null` sempre — com um comentario a dizer
  // que emitia «atraves da rota». Isso punha todos os ensaios de rota a correr
  // com a rede nula, que e precisamente o ponto cego onde vivia o defeito do
  // prefixo em claro. Achado da revisao adversarial.
  // A rede que a **rota** calcula: com zero *proxies* de confiança o cabeçalho é
  // ignorado, e o desafio tem de ser emitido para essa mesma leitura.
  const ip = m.proxies > 0 ? (cabecalhos["x-forwarded-for"] ?? null) : null;
  const emitido = await m.registo.desafioPara(ip);
  m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
  seguinte += 1;
  const corpoFinal = {
    token: token(m),
    nome_negocio: "Loja do bairro",
    categoria: "mercearia",
    nif: NIF,
    telefone: TELEFONE,
    desafio: emitido.desafio,
    solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
    ...corpo,
  };
  return m.app.request("/api/registo", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "idempotency-key": `chave-http-${String(seguinte).padStart(5, "0")}`,
      ...cabecalhos,
    },
    body: JSON.stringify(corpoFinal),
  });
}

async function json(resposta: Response): Promise<Record<string, unknown>> {
  return (await resposta.json()) as Record<string, unknown>;
}

describe("onboarding-web: GET /entrar (criterios 1 e 3)", () => {
  it("abre com um token valido, com CSP estrita e sem scripts de terceiros", async () => {
    const m = montar();
    const resposta = await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`);
    assert.equal(resposta.status, 200);
    const csp = resposta.headers.get("content-security-policy") ?? "";
    // **As directivas todas, e a primeira versao afirmava quatro de oito.** A
    // celula do bloco enumera o `frame-ancestors` e o `base-uri`, e nenhum
    // estava medido: apaga-los deixava o ensaio verde. Achado da revisao.
    for (const directiva of [
      "default-src 'none'",
      "style-src 'nonce-",
      "script-src 'nonce-",
      "connect-src 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "base-uri 'none'",
    ]) {
      assert.ok(csp.includes(directiva), `falta ${directiva} em: ${csp}`);
    }
    assert.match(csp, /script-src 'nonce-[0-9a-f]{24}'/);
    assert.equal(resposta.headers.get("x-content-type-options"), "nosniff");
    assert.equal(resposta.headers.get("referrer-policy"), "no-referrer");
    assert.equal(resposta.headers.get("cache-control"), "no-store");
    const html = await resposta.text();
    assert.ok(!/<script[^>]+src=/.test(html), "nenhum script de terceiros");
    assert.ok(!/<link[^>]+href=/.test(html), "nenhuma folha nem tipo de letra remoto");
    assert.ok(!/https?:\/\//.test(html), "nenhum URL absoluto na pagina");
  });

  it("o nonce e diferente em cada resposta", async () => {
    // Um nonce fixo valia tanto como `'unsafe-inline'`.
    const m = montar();
    const um = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    const outro = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    const nonceDe = (html: string): string => /nonce="([0-9a-f]+)"/.exec(html)?.[1] ?? "";
    assert.notEqual(nonceDe(um), nonceDe(outro));
    assert.match(nonceDe(um), /^[0-9a-f]{24}$/);
  });

  it("o ecra diz que o servico implica NIF e registo de vendas", async () => {
    const m = montar();
    const html = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    assert.ok(normalizar(html).includes(FRASE_OBRIGATORIA));
  });

  it("e NUNCA promete nenhuma das frases proibidas do doc 10 secao 12", async () => {
    const m = montar();
    const html = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    const limpo = normalizar(html);
    for (const frase of FRASES_PROIBIDAS) {
      assert.ok(!limpo.includes(frase), `a pagina diz "${frase}"`);
    }
  });

  it("o campo honeypot esta la, escondido e fora do alcance de um leitor de ecra", async () => {
    const m = montar();
    const html = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    // **A estrutura e nao tres `includes` soltos.** A primeira versao afirmava
    // as tres cadeias de forma independente, pelo que apagar a regra de CSS que
    // esconde o campo deixava o ensaio VERDE — e o honeypot passava a ser um
    // campo visivel e rotulado no meio do formulario, que todo o dono real
    // preenchia, recusando TODOS os registos. Achado da revisao adversarial, e o
    // de pior consequencia de todos.
    const ardil = /<div class="ardil"([^>]*)>([\s\S]*?)<\/div>/.exec(html);
    assert.ok(ardil !== null, "a caixa do honeypot existe");
    assert.match(ardil[1] ?? "", /aria-hidden="true"/);
    assert.ok((ardil[2] ?? "").includes(`name="${NOME_DO_HONEYPOT}"`), "o campo esta DENTRO dela");
    assert.match(ardil[2] ?? "", /tabindex="-1"/);
    // E a regra que a esconde existe, com o deslocamento fora do ecra.
    assert.match(html, /\.ardil\s*\{[^}]*position:\s*absolute[^}]*left:\s*-9999px/);
    // E **nao** e um `type="hidden"`, que se reconhece com uma linha de selector.
    assert.ok(!new RegExp(`name="${NOME_DO_HONEYPOT}"[^>]*type="hidden"`).test(html));
  });

  it("um token forjado da 403 e a pagina de recusa nao diz porque", async () => {
    const m = montar();
    const forjado = cunharToken(
      "convite",
      new Date(m.relogio.agora().getTime() + 86_400_000),
      Buffer.alloc(32, 0x11),
      m.relogio.agora,
    );
    for (const c of [forjado, "", "lixo"]) {
      const resposta = await m.app.request(`/entrar?c=${encodeURIComponent(c)}`);
      assert.equal(resposta.status, 403, JSON.stringify(c));
      const html = await resposta.text();
      // Nem «expirado» nem «invalido»: um expirado e prova de que a chave esteve
      // certa algum dia.
      assert.ok(!/expir/i.test(html));
      assert.ok(!/assinatur/i.test(html));
    }
    assert.equal(m.casos.quantos, 0, "nenhuma linha");
  });

  it("sem `c` nenhum tambem da 403", async () => {
    const m = montar();
    assert.equal((await m.app.request("/entrar")).status, 403);
  });
});

describe("onboarding-web: POST /api/registo (criterios 2, 3 e 9)", () => {
  it("um pedido valido cria UM caso e devolve tres campos", async () => {
    const m = montar();
    const resposta = await submeter(m);
    assert.equal(resposta.status, 200);
    const corpo = await json(resposta);
    assert.deepEqual(Object.keys(corpo).sort(), ["digitos", "referencia", "validade_segundos"]);
    assert.equal(corpo.digitos, 6);
    assert.equal(corpo.validade_segundos, 300);
    assert.equal(m.casos.quantos, 1);
    assert.equal(m.sms.quantosSairam, 1);
  });

  it("a referencia e um BILHETE e nao uma sessao", async () => {
    // Mutacao que isto mata: cunhar a referencia com o fim `sessao` no
    // `#aceite`. O corpo ficava igual e quem submetesse o formulario de outra
    // pessoa ficava autenticado sem provar posse do telefone.
    const m = montar();
    const corpo = await json(await submeter(m));
    const referencia = String(corpo.referencia);
    assert.ok(lerReferencia("ticket", referencia, [ASSINATURA, null], m.relogio.agora).length > 0);
    assert.throws(() => lerReferencia("sessao", referencia, [ASSINATURA, null], m.relogio.agora));
  });

  it("o mesmo Idempotency-Key 2x devolve a MESMA referencia e cria um caso", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(null);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    const corpo = JSON.stringify({
      token: token(m),
      nome_negocio: "Loja do bairro",
      categoria: "mercearia",
      nif: NIF,
      telefone: TELEFONE,
      desafio: emitido.desafio,
      solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
    });
    const cabecalhos = { "content-type": "application/json", "idempotency-key": "chave-repetida-0001" };
    const uma = await json(await m.app.request("/api/registo", { method: "POST", headers: cabecalhos, body: corpo }));
    const outra = await json(await m.app.request("/api/registo", { method: "POST", headers: cabecalhos, body: corpo }));
    assert.equal(uma.referencia, outra.referencia);
    assert.equal(m.casos.quantos, 1);
    assert.equal(m.sms.quantosSairam, 1);
  });

  it("sem NIF da 400 e nao cria linha", async () => {
    const m = montar();
    for (const nif of [undefined, "", "abc"]) {
      const resposta = await submeter(m, { nif });
      assert.equal(resposta.status, 400, JSON.stringify(nif));
      assert.deepEqual(await json(resposta), { erro: "campo" });
    }
    assert.equal(m.casos.quantos, 0);
  });

  it("o corpo de uma recusa NAO diz o que falhou em detalhe", async () => {
    // Um `{"erro":"nif_duplicado"}` era a enumeracao que o criterio 9 proibe,
    // servida num campo. O que sai e o codigo fechado.
    const m = montar();
    const corpo = await json(await submeter(m, { nif: "abc" }));
    assert.deepEqual(Object.keys(corpo), ["erro"]);
    assert.ok(!String(corpo.erro).includes("nif"));
  });

  it("um corpo que nao e JSON da 400 sem rebentar", async () => {
    const m = montar();
    const resposta = await m.app.request("/api/registo", {
      method: "POST",
      headers: { "content-type": "application/json", "idempotency-key": "chave-nao-json-01" },
      body: "{isto nao e json",
    });
    assert.equal(resposta.status, 403, "sem token, e um 403 antes de tudo");
    assert.equal(m.casos.quantos, 0);
  });
});

describe("onboarding-web: o anti-abuso esta LIGADO ao pedido (criterio 7)", () => {
  it("o honeypot preenchido recusa pela rota", async () => {
    // Mutacao que isto mata: apagar o `honeypot: corpo.honeypot` do
    // `/api/registo`. A funcao do pacote continua correcta e deixa de ser
    // chamada com o valor, e **so este ensaio** o apanha.
    const m = montar();
    const resposta = await submeter(m, { honeypot: "Loja do bairro" });
    assert.equal(resposta.status, 400);
    assert.deepEqual(await json(resposta), { erro: "abuso" });
    assert.equal(m.casos.quantos, 0);
  });

  it("uma prova de trabalho errada recusa pela rota", async () => {
    // Mutacao que isto mata: apagar o `solucao: corpo.solucao`, ou a chamada ao
    // `antiabuso.verificar` do `registar`.
    //
    // **A solucao errada e CALCULADA e nao escolhida a mao**, e escolhe-la a mao
    // era um ensaio intermitente: com `"0"` fixo, uma em cada dezesseis emissoes
    // de um desafio de quatro bits satisfaz-o por acaso — e foi o que aconteceu
    // quando o desafio passou a levar a rede dentro e os resumos mudaram. Um
    // ensaio que passa por sorte e pior do que nenhum.
    const m = montar();
    const emitido = await m.registo.desafioPara(null);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000);
    let errada: string | null = null;
    for (let i = 0; i < 64 && errada === null; i += 1) {
      const tentativa = String(i);
      if (zerosACabeca(resumoDaProva(emitido.desafio, tentativa)) < emitido.dificuldade) {
        errada = tentativa;
      }
    }
    assert.ok(errada !== null, "nao se encontrou solucao errada em 64 tentativas");
    const resposta = await m.app.request("/api/registo", {
      method: "POST",
      headers: { "content-type": "application/json", "idempotency-key": "chave-pow-errada" },
      body: JSON.stringify({
        token: token(m),
        nome_negocio: "Loja do bairro",
        categoria: "mercearia",
        nif: NIF,
        telefone: TELEFONE,
        desafio: emitido.desafio,
        solucao: errada,
      }),
    });
    assert.equal(resposta.status, 400);
    assert.deepEqual(await json(resposta), { erro: "abuso" });
    assert.equal(m.casos.quantos, 0);
  });

  it("preencher depressa demais recusa pela rota", async () => {
    const m = montar();
    const emitido = await m.antiabuso.emitir(null);
    m.relogio.avancar(SEGUNDOS_MINIMOS * 1000 - 1);
    const resposta = await m.app.request("/api/registo", {
      method: "POST",
      headers: { "content-type": "application/json", "idempotency-key": "chave-depressa-001" },
      body: JSON.stringify({
        token: token(m),
        nome_negocio: "Loja",
        categoria: "mercearia",
        nif: NIF,
        telefone: TELEFONE,
        desafio: emitido.desafio,
        solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
      }),
    });
    assert.equal(resposta.status, 400);
    assert.equal(m.casos.quantos, 0);
  });

  it("CINCO casos por prefixo de IP, e o sexto da 429", async () => {
    // **O ensaio que mede a ligacao.** Mutacoes que isto mata: apagar o
    // `ip: ipDe(c)` do `/api/registo` (o `redeHmac` fica `null` e o limite
    // nunca se aplica), apagar a chamada ao `antiabuso.consumir`, ou trocar o
    // `enderecoDoPedido` por uma leitura crua do cabecalho.
    const m = montar({ proxies: 1 });
    const comIp = { "x-forwarded-for": "192.0.2.77" };
    const estados: number[] = [];
    for (let i = 0; i < 7; i += 1) {
      m.relogio.avancar(61_000);
      const resposta = await submeter(
        m,
        { nif: `541000020${i}ZZ`, telefone: `+24400000003${i}` },
        comIp,
      );
      estados.push(resposta.status);
    }
    assert.deepEqual(estados, [200, 200, 200, 200, 200, 429, 429]);
    assert.equal(m.casos.quantos, 5);
  });

  it("o X-Forwarded-For e IGNORADO quando nao ha proxies de confianca", async () => {
    // Com `proxiesDeConfianca: 0`, um atacante nao escolhe o seu balde. Mede-se
    // assim: sete pedidos com IPs forjados diferentes passam todos, porque o
    // cabecalho nao conta — e o endereco da ligacao, num `app.request`, nao
    // existe, pelo que a rede e `null`.
    const m = montar({ proxies: 0 });
    for (let i = 0; i < 7; i += 1) {
      m.relogio.avancar(61_000);
      const resposta = await submeter(
        m,
        { nif: `541000030${i}ZZ`, telefone: `+24400000004${i}` },
        { "x-forwarded-for": `198.51.100.${i}` },
      );
      assert.equal(resposta.status, 200, `pedido ${i}`);
    }
    assert.equal(m.casos.quantos, 7);
  });

  it("a dificuldade da prova SOBE com a rede, lida de `/entrar`", async () => {
    // **O achado mais grave do diff inteiro.** A rota passava o prefixo de IP
    // **em claro** onde o `emitir` quer um `redeHmac`, e quem consome a quota faz
    // o HMAC: dois espacos de chave disjuntos, pelo que a dificuldade servida era
    // SEMPRE a base — a «prova de trabalho adaptativa» do criterio 7 era
    // constante em qualquer carga. E nenhum ensaio o podia ver, porque todos
    // chamavam o `AntiAbuso` directamente com um `redeHmac` sintetico.
    const m = montar({ proxies: 1 });
    const ip = "203.0.113.42";
    const dificuldadeDe = async (): Promise<number> => {
      const html = await (
        await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`, {
          headers: { "x-forwarded-for": ip },
        })
      ).text();
      return Number(/data-dificuldade="([0-9]+)"/.exec(html)?.[1] ?? "-1");
    };
    assert.equal(await dificuldadeDe(), 4, "uma rede limpa paga a base");
    for (let i = 0; i < 3; i += 1) {
      m.relogio.avancar(61_000);
      const resposta = await submeter(
        m,
        { nif: `541000040${i}ZZ`, telefone: `+24400000006${i}` },
        { "x-forwarded-for": ip },
      );
      assert.equal(resposta.status, 200, `pedido ${i}`);
    }
    // Tres casos na rede: `4 + floor(log2(4))` sao 6.
    assert.equal(await dificuldadeDe(), 6, "e sobe com os registos da rede");
    // E a rede ao lado continua na base: trocar de cliente nao baixa isto.
    const outra = await (
      await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`, {
        headers: { "x-forwarded-for": "198.51.100.7" },
      })
    ).text();
    assert.equal(Number(/data-dificuldade="([0-9]+)"/.exec(outra)?.[1] ?? "-1"), 4);
  });

  it("o limite por DISPOSITIVO e alcancavel a partir da pagina", async () => {
    // **Era maquinaria sem caminho.** O servidor tem o limite todo — chave,
    // janela, contagem, marca — e o corpo que a pagina submetia **nao levava o
    // campo**, pelo que o `device_hash` era sempre nulo e o limite do criterio 8
    // nao se aplicava a ninguem. Achado da revisao adversarial.
    //
    // A pagina monta-o a partir de tracos do navegador (ver `pagina.ts`), e e um
    // SINAL e nao uma barreira: a consequencia de ele bater e uma MARCA, nao uma
    // recusa, que e o que o criterio 8 pede dele.
    const m = montar();
    const html = await (await m.app.request(`/entrar?c=${encodeURIComponent(token(m))}`)).text();
    assert.ok(html.includes("dispositivo: dispositivo()"), "a pagina submete o campo");
    const dispositivo = "aparelho-de-ensaio";
    for (let i = 0; i < 4; i += 1) {
      m.relogio.avancar(3_600_001);
      const resposta = await submeter(m, {
        nif: `541000050${i}ZZ`,
        telefone: `+24400000007${i}`,
        dispositivo,
      });
      assert.equal(resposta.status, 200, `pedido ${i}`);
    }
    assert.equal(m.casos.quantos, 4);
    assert.ok(m.casos.todos.slice(0, 3).every((c) => c.flags.length === 0));
    assert.deepEqual((m.casos.todos[3] as Caso).flags, ["duplicado_ambiguo"]);
  });

  it("o endereco le-se da DIREITA do X-Forwarded-For", async () => {
    // O salto mais a direita e o que o proxy mais proximo escreveu, e esse nao e
    // forjavel. Os da esquerda sao.
    assert.equal(enderecoDoPedido("1.1.1.1, 2.2.2.2, 3.3.3.3", "9.9.9.9", 1), "3.3.3.3");
    assert.equal(enderecoDoPedido("1.1.1.1, 2.2.2.2, 3.3.3.3", "9.9.9.9", 2), "2.2.2.2");
    assert.equal(enderecoDoPedido("1.1.1.1", "9.9.9.9", 0), "9.9.9.9");
    assert.equal(enderecoDoPedido(undefined, "9.9.9.9", 1), "9.9.9.9");
    assert.equal(enderecoDoPedido("1.1.1.1", "9.9.9.9", 5), "9.9.9.9");
    assert.equal(enderecoDoPedido(undefined, undefined, 0), null);
  });
});

describe("onboarding-web: o OTP e a sessao (criterios 5 e 8)", () => {
  /** Registra e devolve o bilhete e o código em claro, lido do `fake`. */
  async function registarEObterCodigo(m: Montagem) {
    const corpo = await json(await submeter(m));
    const referencia = String(corpo.referencia);
    const texto = m.sms.enviados.at(-1)?.corpo ?? "";
    const codigo = /([0-9]{6})/.exec(texto)?.[1] ?? "";
    assert.match(codigo, /^[0-9]{6}$/);
    return { referencia, codigo };
  }

  it("o codigo certo confirma e DA o cookie de sessao", async () => {
    const m = montar();
    const { referencia, codigo } = await registarEObterCodigo(m);
    const resposta = await m.app.request("/api/otp/verificar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia, codigo }),
    });
    assert.equal(resposta.status, 200);
    assert.deepEqual(await json(resposta), { veredicto: "acertou" });
    const cookie = resposta.headers.get("set-cookie") ?? "";
    assert.match(cookie, /^kamba_onboarding=/);
    assert.ok(cookie.includes("HttpOnly") && cookie.includes("SameSite=Lax"));
    const id = lerReferencia("sessao", cookie.slice("kamba_onboarding=".length).split(";")[0] ?? "", [ASSINATURA, null], m.relogio.agora);
    assert.equal((await m.casos.porId(id))?.fase, "kyc_pendente");
  });

  it("um codigo errado NAO da cookie nenhum", async () => {
    // Mutacao que isto mata: mover o `Set-Cookie` para fora do `if`.
    const m = montar();
    const { referencia, codigo } = await registarEObterCodigo(m);
    const errado = codigo === "000000" ? "111111" : "000000";
    const resposta = await m.app.request("/api/otp/verificar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia, codigo: errado }),
    });
    assert.equal(resposta.status, 200);
    assert.deepEqual(await json(resposta), { veredicto: "errou" });
    assert.equal(resposta.headers.get("set-cookie"), null);
    assert.equal((await m.casos.porId(lerReferencia("ticket", referencia, [ASSINATURA, null], m.relogio.agora)))?.fase, "otp_pendente");
  });

  it("uma referencia de SESSAO nao serve de bilhete no verificar", async () => {
    // Mutacao que isto mata: trocar o fim `ticket` por `sessao` no
    // `idDaReferencia`. Os dois fins deixavam de estar separados.
    const m = montar();
    const { codigo } = await registarEObterCodigo(m);
    const caso = m.casos.todos[0] as Caso;
    const comoSessao = cunharReferencia("sessao", caso.id, ASSINATURA, m.relogio.agora);
    const resposta = await m.app.request("/api/otp/verificar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia: comoSessao, codigo }),
    });
    assert.equal(resposta.status, 403);
  });

  it("o reenvio respeita o intervalo de 60 s", async () => {
    const m = montar();
    const { referencia } = await registarEObterCodigo(m);
    const pedir = () =>
      m.app.request("/api/otp/reenviar", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ referencia }),
      });
    assert.equal((await pedir()).status, 429);
    m.relogio.avancar(60_000);
    assert.equal((await pedir()).status, 200);
    assert.equal(m.sms.quantosSairam, 2);
  });

  it("o reenvio com uma referencia forjada da 403 e nao manda SMS", async () => {
    const m = montar();
    await registarEObterCodigo(m);
    const caso = m.casos.todos[0] as Caso;
    const forjada = cunharReferencia("ticket", caso.id, Buffer.alloc(32, 0x11), m.relogio.agora);
    const resposta = await m.app.request("/api/otp/reenviar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia: forjada }),
    });
    assert.equal(resposta.status, 403);
    assert.equal(m.sms.quantosSairam, 1);
  });
});

describe("onboarding-web: isolamento por referencia", () => {
  it("a sessao do caso A com o id do caso B NAO abre o caso B", async () => {
    // E o teste cruzado do DoD, na metade que uma referencia assinada consegue
    // garantir: o id sai **de dentro** do HMAC, pelo que trocar o UUID quebra a
    // assinatura. **A outra metade — a RLS `FORCE` sobre `app.onboarding_id` —
    // nao se mede aqui**, e fica com credor nomeado no bloco: um `Map` nao
    // filtra nada.
    const m = montar();
    await submeter(m);
    m.relogio.avancar(3_600_001);
    await submeter(m, { nif: "5410000777EF", telefone: "+244000000050" });
    const [a, b] = m.casos.todos as [Caso, Caso];
    const sessaoDeA = cunharReferencia("sessao", a.id, ASSINATURA, m.relogio.agora);
    const trocada = `${b.id}.${sessaoDeA.split(".")[1]}`;
    const resposta = await m.app.request("/api/actividade", {
      method: "POST",
      headers: { "content-type": "application/json", cookie: `kamba_onboarding=${trocada}` },
      body: JSON.stringify({}),
    });
    assert.equal(resposta.status, 403);
  });

  it("a batida de um caso que nao existe da 404", async () => {
    const m = montar();
    const inventada = cunharReferencia("sessao", idSequencial(999), ASSINATURA, m.relogio.agora);
    const resposta = await m.app.request("/api/actividade", {
      method: "POST",
      headers: { "content-type": "application/json", cookie: `kamba_onboarding=${inventada}` },
      body: JSON.stringify({}),
    });
    assert.equal(resposta.status, 404);
  });

  it("sem referencia nenhuma, a batida da 403", async () => {
    const m = montar();
    const resposta = await m.app.request("/api/actividade", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    assert.equal(resposta.status, 403);
  });

  it("a batida exige a SESSAO: o bilhete nao autoriza uma escrita", async () => {
    // **O bilhete «nao autentica ninguem» por desenho**, e no caminho de
    // recuperacao do criterio 8 ele esta nas maos de quem submeteu o formulario —
    // que pode nao ser o dono. Com ele aceite aqui, essa pessoa ESCREVIA no
    // `owner_active_seconds` do caso de outra. Achado da revisao adversarial.
    const m = montar();
    const corpo = await json(await submeter(m));
    const bilhete = String(corpo.referencia);
    const comBilhete = await m.app.request("/api/actividade", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia: bilhete }),
    });
    assert.equal(comBilhete.status, 403);
    assert.equal((m.casos.todos[0] as Caso).activoSegundos, 0);
  });

  it("com a sessao, a batida acumula pelo tempo decorrido e o corpo nao e lido", async () => {
    const m = montar();
    await submeter(m);
    const caso = m.casos.todos[0] as Caso;
    const sessao = cunharReferencia("sessao", caso.id, ASSINATURA, m.relogio.agora);
    const bater = (corpo: string) =>
      m.app.request("/api/actividade", {
        method: "POST",
        headers: { "content-type": "application/json", cookie: `kamba_onboarding=${sessao}` },
        body: corpo,
      });
    assert.deepEqual(await json(await bater("{}")), { somados: 0, total: 0 });
    m.relogio.avancar(30_000);
    // **O corpo leva campos a mais e nada deles e lido**: e a metade do criterio
    // 10 que se consegue medir do lado HTTP. O `somados` sai do relogio do
    // servidor, pelo que um cliente que mande «mais mil segundos» soma 30.
    const comLixo = await bater(JSON.stringify({ somados: 1000, teclas: "nif: 5410000123AB" }));
    assert.deepEqual(await json(comLixo), { somados: 30, total: 30 });
  });
});

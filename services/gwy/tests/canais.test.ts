/**
 * `POST /internal/channels` — a rota interna do Embedded Signup v4 (KAM-016).
 *
 * Sem base e sem Meta: o `Onboarding` é um duplo que devolve ou levanta o que
 * cada caso precisa. O que esta bateria mede é a **fronteira HTTP** — os códigos
 * de resposta, o que o corpo da resposta leva e o que ele **não** leva, e a
 * decisão de a rota viver na app **interna** —, e nada do que vem a seguir dela:
 * a saga está em `packages/core-ts/tests/onboarding.test.ts` e o que só uma base
 * prova está em `tests_bd/onboarding.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { FILA_ENTRADA } from "@kamba/core-ts/entrada";
import { FilasEmMemoria } from "@kamba/core-ts/eventos";
import {
  CABECALHO,
  CAMPOS as CAMPOS_DO_SIMULADOR,
  ITENS,
  fixtureDe,
  segredoDeEnsaio,
} from "@kamba/meta-sim";

import {
  CAMPOS_DE_WEBHOOK,
  EsNaoEV4Error,
  LimiteDeOnboardingsError,
  NumeroJaUsadoError,
  type Onboarding,
  type ResultadoDoEs,
  type Tentativa,
} from "@kamba/core-ts/onboarding";
import { Logger } from "@kamba/core-ts/logger";

import { createApp, criarAppDeMetricas } from "../src/app.ts";
import { CAMINHO_DOS_CANAIS, type ComTransaccao } from "../src/canais.ts";
import { CAMINHO } from "../src/webhook.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";

const CORPO = {
  tenant_id: TENANT,
  code: "AQB-code-de-ensaio",
  waba_id: "102290129340398",
  phone_number_id: "106540352242922",
  session_info: { sessionInfoVersion: "3", extras: { featureType: "whatsapp_business_app_onboarding" } },
};

const TENTATIVA: Tentativa = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  tenant_id: TENANT,
  channel_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  waba_id: CORPO.waba_id,
  waac_id: null,
  phone_number_id: CORPO.phone_number_id,
  fase: "subscrito",
  recursos_criados: [
    { recurso: "token", ref: "meta_client_token/0123456789abcdef0123456789abcdef" },
    { recurso: "canal", ref: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" },
    { recurso: "subscricao", ref: CORPO.waba_id },
  ],
  pin_ref: "meta_pin_2fa/fedcba9876543210fedcba9876543210",
  motivo: null,
};

/**
 * O duplo do serviço, e o que ele conta.
 *
 * `transaccoes` é o número de vezes que a rota abriu uma — e é a asserção que
 * mede a decisão do critério 4: o registo de auditoria da recusa escreve-se numa
 * transacção **própria**, porque a que levantou o `23505` reverteu.
 */
function montar(
  comportamento: {
    readonly ligar?: () => Promise<{ tentativa: Tentativa; novo: boolean }>;
  } = {},
): { comTransaccao: ComTransaccao; transaccoes: () => number; recusas: () => number } {
  let transaccoes = 0;
  let recusas = 0;
  const servico = {
    async ligar(): Promise<{ tentativa: Tentativa; novo: boolean }> {
      if (comportamento.ligar !== undefined) return comportamento.ligar();
      return { tentativa: TENTATIVA, novo: true };
    },
    async registarRecusa(_entrada: ResultadoDoEs, _motivo: string): Promise<void> {
      recusas += 1;
    },
  } as unknown as Onboarding;
  return {
    comTransaccao: async (corpo) => {
      transaccoes += 1;
      return corpo(servico);
    },
    transaccoes: () => transaccoes,
    recusas: () => recusas,
  };
}

function pedido(corpo: unknown): Request {
  return new Request(`http://interno${CAMINHO_DOS_CANAIS}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof corpo === "string" ? corpo : JSON.stringify(corpo),
  });
}

describe("a rota vive na app interna, e nao na publica", () => {
  /**
   * **É a afirmação mais importante desta bateria.** Esta rota cria canais e o
   * `tenant_id` vem no corpo; na porta pública — alcançável da Internet por
   * desenho (ADR-001) — quem lhe chegasse podia ligar um número ao tenant que
   * quisesse. É a mesma razão que tirou o `/metrics` de lá na revisão
   * adversarial do KAM-013, com mais em jogo.
   */
  it("a app publica responde 404 ao POST /internal/channels", async () => {
    const resposta = await createApp().request(pedido(CORPO));
    assert.equal(resposta.status, 404);
  });

  it("a app publica responde 404 mesmo com as dependencias do webhook", async () => {
    // Sem dependências de webhook a app pública não monta o webhook; o que esta
    // asserção fixa é que **nenhuma** forma de montar a app pública lhe dá esta
    // rota — ela não é parâmetro do `createApp`.
    const resposta = await createApp(new Logger("gwy")).request(pedido(CORPO));
    assert.equal(resposta.status, 404);
  });

  it("sem dependencias, a app interna tambem responde 404 e nao 200", async () => {
    // É a mesma escolha do `createApp` para o webhook: sem dependências a rota
    // não existe, **e isso é visível**. Um GWY sem base que aceitasse pedidos
    // era pior do que um que os recusa.
    const resposta = await criarAppDeMetricas().request(pedido(CORPO));
    assert.equal(resposta.status, 404);
  });

  it("a app interna continua a servir o /metrics e o /healthz", async () => {
    const app = criarAppDeMetricas(undefined, montar());
    assert.equal((await app.request("/healthz")).status, 200);
    assert.equal((await app.request("/metrics")).status, 200);
  });
});

describe("os codigos de resposta", () => {
  it("201 quando o canal foi criado nesta chamada", async () => {
    const d = montar();
    const resposta = await criarAppDeMetricas(undefined, d).request(pedido(CORPO));
    assert.equal(resposta.status, 201);
    const corpo = (await resposta.json()) as Record<string, unknown>;
    assert.equal(corpo.onboarding_id, TENTATIVA.id);
    assert.equal(corpo.channel_id, TENTATIVA.channel_id);
    assert.equal(corpo.fase, "subscrito");
    assert.deepEqual(corpo.recursos_criados, ["token", "canal", "subscricao"]);
    assert.equal(d.transaccoes(), 1);
  });

  /**
   * **200 e não 201 na repetição**, e não é cosmética: é a forma de o critério 2
   * se verificar de fora — duas chamadas, um 201 e um 200, um canal.
   */
  it("200 quando a tentativa ja existia (criterio 2)", async () => {
    const d = montar({ ligar: async () => ({ tentativa: TENTATIVA, novo: false }) });
    const resposta = await criarAppDeMetricas(undefined, d).request(pedido(CORPO));
    assert.equal(resposta.status, 200);
  });

  it("409 quando o numero e de outro tenant, e o registo e uma transaccao propria", async () => {
    const d = montar({
      ligar: async () => {
        throw new NumeroJaUsadoError(CORPO.phone_number_id);
      },
    });
    const resposta = await criarAppDeMetricas(new Logger("gwy"), d).request(pedido(CORPO));
    assert.equal(resposta.status, 409);
    // **Duas transacções**: a que reverteu e a do registo de auditoria.
    assert.equal(d.transaccoes(), 2);
    assert.equal(d.recusas(), 1);
  });

  /**
   * **A resposta não diz de quem é o número.** Quem recebe o 409 é o tenant que
   * tentou, e nomear o dono era um canal de leitura entre tenants por mensagem
   * de erro.
   */
  it("o 409 nao nomeia o tenant dono do numero", async () => {
    const d = montar({
      ligar: async () => {
        throw new NumeroJaUsadoError(CORPO.phone_number_id);
      },
    });
    const resposta = await criarAppDeMetricas(undefined, d).request(pedido(CORPO));
    const corpo = JSON.stringify(await resposta.json());
    assert.ok(!corpo.includes("tenant_id"));
    assert.ok(!corpo.includes(TENANT));
  });

  it("429 quando o tecto de dez em sete dias esta gasto, e nao 403", async () => {
    const d = montar({
      ligar: async () => {
        throw new LimiteDeOnboardingsError(10);
      },
    });
    const resposta = await criarAppDeMetricas(undefined, d).request(pedido(CORPO));
    assert.equal(resposta.status, 429);
    const corpo = (await resposta.json()) as Record<string, unknown>;
    assert.equal(corpo.contagem, 10);
    // Um 403 dizia «nunca», e a resposta certa é «ainda não»: a lista de espera
    // é KAM-095.
    assert.equal(d.recusas(), 0);
  });

  it("400 quando o session_info nao e de v4", async () => {
    const d = montar({
      ligar: async () => {
        throw new EsNaoEV4Error("sessionInfoVersion é \"2\" e v4 exige \"3\"");
      },
    });
    const resposta = await criarAppDeMetricas(undefined, d).request(pedido(CORPO));
    assert.equal(resposta.status, 400);
  });

  it("502 quando a Meta ou a base falham, e a mensagem nao sai", async () => {
    const d = montar({
      ligar: async () => {
        throw new Error("a Graph respondeu 500 ao parametro code=AQB-segredo");
      },
    });
    const resposta = await criarAppDeMetricas(new Logger("gwy"), d).request(pedido(CORPO));
    assert.equal(resposta.status, 502);
    const corpo = JSON.stringify(await resposta.json());
    assert.ok(!corpo.includes("AQB-segredo"));
    assert.equal(corpo, '{"error":"onboarding falhou"}');
  });
});

describe("a leitura do corpo", () => {
  it("400 sem abrir transaccao quando falta um campo", async () => {
    for (const campo of ["tenant_id", "code", "waba_id", "phone_number_id", "session_info"]) {
      const d = montar();
      const { [campo]: _, ...resto } = CORPO as Record<string, unknown>;
      const resposta = await criarAppDeMetricas(undefined, d).request(pedido(resto));
      assert.equal(resposta.status, 400, `sem ${campo} devia dar 400`);
      assert.equal(d.transaccoes(), 0, `sem ${campo} nao devia abrir transaccao`);
    }
  });

  it("400 quando o corpo nao e JSON, ou nao e um objecto", async () => {
    for (const corpo of ["nao sou json", "[]", '"cadeia"', "null"]) {
      const d = montar();
      const resposta = await criarAppDeMetricas(undefined, d).request(pedido(corpo));
      assert.equal(resposta.status, 400, `${corpo} devia dar 400`);
      assert.equal(d.transaccoes(), 0);
    }
  });

  it("400 quando um campo vem vazio ou so com espacos", async () => {
    for (const valor of ["", "   "]) {
      const d = montar();
      const resposta = await criarAppDeMetricas(undefined, d).request(
        pedido({ ...CORPO, waba_id: valor }),
      );
      assert.equal(resposta.status, 400);
    }
  });

  /**
   * **O valor não entra na mensagem, e o campo entra.** Um dos cinco é o `code`,
   * que é trocável por um *token* de cliente: repetir o que se recusou punha um
   * segredo na resposta e no log de quem a registar.
   */
  it("a mensagem de 400 nomeia o campo e nao repete o valor", async () => {
    const d = montar();
    const resposta = await criarAppDeMetricas(undefined, d).request(
      pedido({ ...CORPO, code: 12345 }),
    );
    assert.equal(resposta.status, 400);
    const corpo = JSON.stringify(await resposta.json());
    assert.ok(corpo.includes("code"));
    assert.ok(!corpo.includes("12345"));
  });

  it("os identificadores entram aparados, e o code nao", async () => {
    // `let` com asserção explícita: sem ela o TypeScript estreita o tipo a
    // `never` depois do `null` inicial, porque a escrita acontece dentro de um
    // *callback* que ele não sabe que correu.
    const capturado: { entrada: ResultadoDoEs | null } = { entrada: null };
    const servico = {
      async ligar(entrada: ResultadoDoEs) {
        capturado.entrada = entrada;
        return { tentativa: TENTATIVA, novo: true };
      },
    } as unknown as Onboarding;
    const d: { comTransaccao: ComTransaccao } = {
      comTransaccao: async (corpo) => corpo(servico),
    };
    await criarAppDeMetricas(undefined, d).request(
      pedido({ ...CORPO, waba_id: "  102  ", code: " AQB-com-espaco " }),
    );
    assert.equal(capturado.entrada?.waba_id, "102");
    // **O `code` não se apara**: ele é um segredo que a Meta cunhou, e aparar um
    // segredo é aceitar em silêncio uma entrada que não é a que ela mandou. É a
    // mesma regra do `normalizarBsuid` do KAM-008.
    assert.equal(capturado.entrada?.code, " AQB-com-espaco ");
  });
});

describe("o que a resposta nao leva", () => {
  /**
   * **Nem o `token_ref` nem o `pin_ref`.** São referências opacas a segredos, e
   * quem chamou esta rota é a página do KAM-093 — que não precisa de nenhuma das
   * duas e não tem o que fazer com elas.
   */
  it("a resposta nao leva referencias de segredo", async () => {
    const resposta = await criarAppDeMetricas(undefined, montar()).request(pedido(CORPO));
    const corpo = JSON.stringify(await resposta.json());
    assert.ok(!corpo.includes("meta_client_token/"));
    assert.ok(!corpo.includes("meta_pin_2fa/"));
    assert.ok(!corpo.includes(TENTATIVA.pin_ref ?? "nunca"));
    // E leva os **tipos** de recurso, que é o que diz em que pé a saga está.
    assert.ok(corpo.includes("token"));
  });

  it("a resposta nao leva o code nem o session_info", async () => {
    const resposta = await criarAppDeMetricas(undefined, montar()).request(pedido(CORPO));
    const corpo = JSON.stringify(await resposta.json());
    assert.ok(!corpo.includes(CORPO.code));
    assert.ok(!corpo.includes("sessionInfoVersion"));
  });
});

describe("os onze campos, e um evento de um deles chega ao GWY (criterio 5)", () => {
  /**
   * **Três cópias do mesmo domínio, comparadas.**
   *
   * Os onze campos existem em três sítios: o `CAMPOS_DE_WEBHOOK` deste ticket, o
   * `CAMPOS` do `@kamba/meta-sim` (KAM-024) e a tabela do
   * `../../../docs/tecnica/01` §4.4. Duas cópias de um domínio divergem no dia
   * em que uma delas mudar, e é a mesma razão pela qual o KAM-021 compara as
   * três listas do `EVENTOS_DE_CANAL`.
   *
   * Compara-se como **conjunto**: a ordem do critério é a da prosa do bloco e a
   * do simulador é a do documento, e nenhuma das duas é normativa.
   */
  it("o dominio deste ticket e o do simulador do KAM-024 sao o mesmo conjunto", () => {
    assert.deepEqual(
      [...CAMPOS_DE_WEBHOOK].sort(),
      [...CAMPOS_DO_SIMULADOR].sort(),
    );
    assert.equal(CAMPOS_DE_WEBHOOK.length, 11);
  });

  /**
   * **«Um evento de teste chega ao GWY», e é a terceira cláusula do critério 5.**
   *
   * O que se mede é o que este ramo pode medir: uma *fixture* **assinada** de
   * cada um dos onze campos subscritos entra pelo `POST /wa/webhook`, responde
   * **200** e deixa **um** *job* na fila. É a prova de que subscrever estes onze
   * nomes não é um gesto vazio — há um caminho de entrada para cada um deles.
   *
   * **O que isto não é**, e está na secção de verificação do bloco: não é o
   * evento de teste do passo 10 do `01` §13.2, que é uma mensagem real enviada e
   * recebida no número do cliente. Esse é o **nono** critério, e depende de
   * `ext:KAM-102`.
   *
   * A assinatura é do `assinar` do simulador, que tem `createHmac` próprio e não
   * importa nada do `core-ts` — são duas implementações, e é isso que faz a ida
   * e volta medir alguma coisa (a razão está no `kam024.ida-e-volta.test.ts`).
   */
  it("uma fixture assinada de cada um dos onze campos entra e fica na fila", async () => {
    const semente = "evento-de-teste-do-kam-016";
    const segredo = segredoDeEnsaio(semente);
    const recusados: string[] = [];
    const semFixture: string[] = [];
    for (const campo of CAMPOS_DE_WEBHOOK) {
      const item = ITENS.find((i) => i.dimensao === "campo" && i.nome === campo);
      assert.ok(item !== undefined, `o simulador nao tem item para ${campo}`);
      const fixture = fixtureDe(item, semente, segredo);
      if (fixture === null) {
        // Um campo sem *fixture* é um achado e não um salto: o relatório de
        // cobertura do KAM-024 está a 100%, pelo que isto não devia acontecer.
        semFixture.push(campo);
        continue;
      }
      const filas = new FilasEmMemoria();
      const app = createApp(undefined, {
        anel: () => [segredo, "outro-segredo-do-anel"],
        verifyToken: () => "verify-token-desta-instalacao",
        filas,
        profundidade: () => null,
      });
      const resposta = await app.request(CAMINHO, {
        method: "POST",
        body: fixture.bytes,
        headers: { "content-type": "application/json", [CABECALHO]: fixture.assinatura },
      });
      if (resposta.status !== 200 || filas.contar(FILA_ENTRADA) !== 1) {
        recusados.push(`${campo} (${resposta.status}, ${filas.contar(FILA_ENTRADA)} jobs)`);
      }
    }
    assert.deepEqual(semFixture, []);
    assert.deepEqual(recusados, []);
  });
});

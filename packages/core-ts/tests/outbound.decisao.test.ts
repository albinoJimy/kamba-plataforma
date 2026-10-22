/**
 * A matriz de decisão de envio (KAM-015, critérios 1 e 7).
 *
 * O critério 1 tem três ramos e os três estão aqui, um a um: janela aberta dá
 * mensagem livre; janela fechada com conteúdo livre dá `WINDOW_CLOSED`; janela
 * fechada com template `approved` dá o template.
 *
 * O que estes testes prendem, por ordem de importância:
 *
 * 1. **A recusa de forma vem antes de tudo.** O critério 7 pede «falham antes
 *    de qualquer chamada», e a maneira de o provar numa função pura é provar
 *    que ela recusa **mesmo com a janela aberta** — se a ordem estivesse
 *    trocada, um corpo com quatro botões e janela aberta passava.
 * 2. **O `WINDOW_CLOSED` não depende do template.** É a recusa que o chamador
 *    usa para decidir, e tem de sair com template nenhum em mão.
 * 3. **Um template que não está `approved` não sai**, e cada estado que não é
 *    `approved` tem o seu caso — porque «não aprovado» é quatro coisas.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MOTIVOS_DE_RECUSA,
  CATEGORIAS_DO_PILOTO,
  ESTADOS_DE_TEMPLATE,
  MAXIMO_DE_BOTOES,
  MAXIMO_DE_LINHAS,
  WINDOW_CLOSED,
  categoriaDe,
  decidir,
  formaInvalida,
  janelaAberta,
  type Corpo,
  type Template,
} from "../src/outbound/index.ts";

const AGORA = new Date("2026-10-20T12:00:00.000Z");
const ABERTA = { expiraEm: new Date("2026-10-20T13:00:00.000Z") };
const FECHADA = { expiraEm: new Date("2026-10-20T11:00:00.000Z") };
const NUNCA_ABRIU = { expiraEm: null };

const TEXTO: Corpo = { tipo: "texto", texto: "Bom dia" };

function template(troca: Partial<Template> = {}): Template {
  return {
    name: "confirmacao_de_pedido",
    lang: "pt_PT",
    category: "utility",
    status: "approved",
    quality: "green",
    bloqueadoEm: null,
    ...troca,
  };
}

describe("a janela", () => {
  it("esta aberta antes de expirar e fechada depois", () => {
    assert.ok(janelaAberta(ABERTA, AGORA));
    assert.ok(!janelaAberta(FECHADA, AGORA));
  });

  it("uma conversa que nunca recebeu nada tem a janela fechada", () => {
    // `window_expires_at` nulo e não «zero»: a `conversations_janela_ck` exige
    // os dois tempos ou nenhum, e uma conversa pode nascer de um `echo` do
    // dono antes de o cliente escrever.
    assert.ok(!janelaAberta(NUNCA_ABRIU, AGORA));
  });

  it("o limite e estrito: expirar agora e estar fechada", () => {
    // A leitura conservadora, e e a certa: a alternativa era enviar uma
    // mensagem livre no instante em que a Meta a passa a recusar, e descobri-lo
    // por um erro dela em vez de por uma recusa nossa.
    assert.ok(!janelaAberta({ expiraEm: AGORA }, AGORA));
  });
});

describe("a forma recusa-se antes de tudo (criterio 7)", () => {
  it("quatro botoes falham", () => {
    const corpo: Corpo = {
      tipo: "botoes",
      texto: "Escolha",
      botoes: [1, 2, 3, 4].map((n) => ({ id: `b${n}`, titulo: `B${n}` })),
    };
    assert.equal(formaInvalida(corpo), "TOO_MANY_BUTTONS");
  });

  it("tres botoes passam", () => {
    const corpo: Corpo = {
      tipo: "botoes",
      texto: "Escolha",
      botoes: [1, 2, 3].map((n) => ({ id: `b${n}`, titulo: `B${n}` })),
    };
    assert.equal(formaInvalida(corpo), null);
    assert.equal(MAXIMO_DE_BOTOES, 3);
  });

  it("onze linhas falham e dez passam", () => {
    const linhas = (quantas: number): Corpo => ({
      tipo: "lista",
      texto: "Escolha",
      titulo: "Opcoes",
      linhas: Array.from({ length: quantas }, (_, i) => ({ id: `l${i}`, titulo: `L${i}` })),
    });
    assert.equal(formaInvalida(linhas(11)), "TOO_MANY_ROWS");
    assert.equal(formaInvalida(linhas(10)), null);
    assert.equal(MAXIMO_DE_LINHAS, 10);
  });

  it("**recusa mesmo com a janela aberta**, e e isso que prova a ordem", () => {
    // Se a decisao olhasse para a janela primeiro, um corpo com quatro botoes e
    // janela aberta passava — e o criterio 7 («falham antes de qualquer
    // chamada») ficava por cumprir sem nenhum teste o dizer.
    const corpo: Corpo = {
      tipo: "botoes",
      texto: "Escolha",
      botoes: [1, 2, 3, 4].map((n) => ({ id: `b${n}`, titulo: `B${n}` })),
    };
    const decisao = decidir(corpo, ABERTA, AGORA, null);
    assert.equal(decisao.enviar, false);
    assert.equal(decisao.enviar === false ? decisao.motivo : "", "TOO_MANY_BUTTONS");
  });
});

describe("janela aberta: mensagem livre, e nao template (criterio 1)", () => {
  it("um texto sai como service", () => {
    const decisao = decidir(TEXTO, ABERTA, AGORA, null);
    assert.deepEqual(decisao, { enviar: true, kind: "service", templateName: null });
  });

  it("botoes e listas tambem saem como service", () => {
    for (const corpo of [
      { tipo: "botoes", texto: "x", botoes: [{ id: "a", titulo: "A" }] } as Corpo,
      { tipo: "lista", texto: "x", titulo: "T", linhas: [{ id: "a", titulo: "A" }] } as Corpo,
    ]) {
      const decisao = decidir(corpo, ABERTA, AGORA, null);
      assert.equal(decisao.enviar && decisao.kind, "service");
    }
  });

  it("e `service` e nao `utility`, que e o que evita a tarifa", () => {
    // E a linha do §8.2 que diz «Notificacao com janela aberta: mensagem livre,
    // **nao** template», e a razao e custo: a `utility` dentro da janela passou
    // a ser paga em 2026-10-01 (`E1` §1). Enviar template com a janela aberta
    // era pagar 0,004 por nada.
    const decisao = decidir(TEXTO, ABERTA, AGORA, null);
    assert.equal(decisao.enviar && decisao.templateName, null);
  });
});

describe("janela fechada: WINDOW_CLOSED sem chamada (criterio 1)", () => {
  it("um texto com a janela fechada da WINDOW_CLOSED", () => {
    const decisao = decidir(TEXTO, FECHADA, AGORA, null);
    assert.deepEqual(decisao, { enviar: false, motivo: WINDOW_CLOSED });
  });

  it("e tambem quando a janela nunca abriu", () => {
    assert.deepEqual(decidir(TEXTO, NUNCA_ABRIU, AGORA, null), {
      enviar: false,
      motivo: WINDOW_CLOSED,
    });
  });

  it("nao depende de haver template: e a recusa que o chamador usa para decidir", () => {
    // Passar um template aqui nao muda nada, porque o corpo nao e um template.
    // E o §8.2 regra 3: «o ChannelAdapter recusa envio livre com janela fechada
    // e devolve WINDOW_CLOSED ao chamador, que decide template ou desistir».
    assert.deepEqual(decidir(TEXTO, FECHADA, AGORA, template()), {
      enviar: false,
      motivo: WINDOW_CLOSED,
    });
  });
});

describe("janela fechada com template aprovado: envia o template (criterio 1)", () => {
  const comTemplate: Corpo = {
    tipo: "template",
    nome: "confirmacao_de_pedido",
    idioma: "pt_PT",
    parametros: ["123"],
  };

  it("sai com a categoria do template", () => {
    const decisao = decidir(comTemplate, FECHADA, AGORA, template());
    assert.deepEqual(decisao, {
      enviar: true,
      kind: "utility",
      templateName: "confirmacao_de_pedido",
    });
  });

  it("e sai com a janela aberta tambem — e para isso que existe", () => {
    const decisao = decidir(comTemplate, ABERTA, AGORA, template());
    assert.equal(decisao.enviar, true);
  });

  it("sem template na base, recusa", () => {
    assert.deepEqual(decidir(comTemplate, FECHADA, AGORA, null), {
      enviar: false,
      motivo: "TEMPLATE_NOT_APPROVED",
    });
  });

  it("cada estado que nao e approved recusa, e sao quatro", () => {
    // «Nao aprovado» e quatro coisas, e um teste com um estado so provava uma.
    const recusados = ESTADOS_DE_TEMPLATE.filter((estado) => estado !== "approved");
    assert.equal(recusados.length, 4);
    for (const status of recusados) {
      const decisao = decidir(comTemplate, FECHADA, AGORA, template({ status }));
      assert.equal(decisao.enviar, false, status);
      assert.equal(decisao.enviar === false ? decisao.motivo : "", "TEMPLATE_NOT_APPROVED");
    }
  });

  it("um template bloqueado recusa, mesmo aprovado (criterio 9)", () => {
    // A recategorizacao bloqueia o uso. O `bloqueado_em` tem precedencia sobre
    // o `status`: a Meta pode manter `approved` e mudar a categoria, e e
    // exactamente nesse caso que o bloqueio tem de morder.
    const decisao = decidir(
      comTemplate,
      FECHADA,
      AGORA,
      template({ status: "approved", bloqueadoEm: AGORA }),
    );
    assert.deepEqual(decisao, { enviar: false, motivo: "TEMPLATE_BLOCKED" });
  });

  it("marketing recusa no Piloto (criterio 7)", () => {
    const decisao = decidir(comTemplate, FECHADA, AGORA, template({ category: "marketing" }));
    assert.deepEqual(decisao, { enviar: false, motivo: "MARKETING_NOT_ALLOWED" });
    assert.ok(!CATEGORIAS_DO_PILOTO.includes("marketing"));
  });

  it("authentication passa — esta no Piloto, embora exija telefone", () => {
    // Esta no dominio e nas categorias do Piloto; o que a torna inviavel na
    // pratica e exigir telefone (`docs/tecnica/01` §8.2), e isso e uma decisao
    // de quem envia, nao da matriz.
    const decisao = decidir(
      comTemplate,
      FECHADA,
      AGORA,
      template({ category: "authentication" }),
    );
    assert.equal(decisao.enviar && decisao.kind, "authentication");
  });
});

describe("a categoria de um corpo", () => {
  it("um corpo livre e sempre service", () => {
    assert.equal(categoriaDe(TEXTO, null), "service");
    assert.equal(categoriaDe(TEXTO, template({ category: "marketing" })), "service");
  });

  it("um template herda a categoria do template", () => {
    const corpo: Corpo = { tipo: "template", nome: "x", idioma: "pt_PT", parametros: [] };
    assert.equal(categoriaDe(corpo, template({ category: "authentication" })), "authentication");
  });

  it("um template sem linha na base assume utility", () => {
    // E o valor mais barato dos tres que exigem template, e a decisao recusa-o
    // de qualquer maneira por `TEMPLATE_NOT_APPROVED` — isto e so o que a
    // funcao devolve, nao o que se envia.
    const corpo: Corpo = { tipo: "template", nome: "x", idioma: "pt_PT", parametros: [] };
    assert.equal(categoriaDe(corpo, null), "utility");
  });
});

// ------------------------------------------- o estado do canal (KAM-021, CA 9)

describe("a matriz do KAM-009 e a ultima barreira (KAM-021, criterio 9)", () => {
  const ACTIVO = { estadoTenant: "ativo", estadoCanal: "ativo" };
  const RESTRITO = { estadoTenant: "ativo", estadoCanal: "restrito" };

  it("**sem estado, a decisao e exactamente a de antes do KAM-021**", () => {
    // A porta e opcional: nenhum adapter ligado antes dele passa a recusar por
    // causa disto. E a mesma escolha que o `freeTier: null` do KAM-015 fez.
    assert.deepEqual(decidir(TEXTO, ABERTA, AGORA, null), {
      enviar: true,
      kind: "service",
      templateName: null,
    });
    assert.deepEqual(decidir(TEXTO, ABERTA, AGORA, null, null), {
      enviar: true,
      kind: "service",
      templateName: null,
    });
  });

  it("**um canal restrito continua a responder dentro da janela**", () => {
    // E a linha `restrito` da matriz: `responder_sessao: true`. O criterio 2
    // escreve-o por extenso — «mantem respostas dentro da janela».
    assert.deepEqual(decidir(TEXTO, ABERTA, AGORA, null, RESTRITO), {
      enviar: true,
      kind: "service",
      templateName: null,
    });
  });

  it("**um canal restrito nao envia template nenhum**", () => {
    // A matriz tem `enviar_template_marketing: false` e
    // `enviar_template_utilidade: false` na linha `restrito`. O criterio 2 so
    // nomeia o `marketing`; a matriz e mais restritiva, que e o lado seguro, e
    // a divergencia esta registada.
    const corpo: Corpo = { tipo: "template", nome: "x", idioma: "pt_PT", parametros: [] };
    for (const categoria of ["utility", "authentication"] as const) {
      assert.deepEqual(
        decidir(corpo, FECHADA, AGORA, template({ category: categoria }), RESTRITO),
        { enviar: false, motivo: "STATE_REFUSED" },
        categoria,
      );
    }
  });

  it("**num canal activo o template passa**, e e isso que torna o teste acima uma asserção", () => {
    const corpo: Corpo = { tipo: "template", nome: "x", idioma: "pt_PT", parametros: [] };
    const aprovado = template();
    assert.deepEqual(decidir(corpo, FECHADA, AGORA, aprovado, ACTIVO), {
      enviar: true,
      kind: "utility",
      templateName: aprovado.name,
    });
  });

  it("**o `MARKETING_NOT_ALLOWED` vence o estado**, e a ordem e deliberada", () => {
    // Um template recategorizado para `marketing` tem de dar
    // `MARKETING_NOT_ALLOWED` mesmo num canal restrito, porque e esse o motivo
    // que sustenta o bloqueio do criterio 9 do KAM-015. Trocar a ordem fazia o
    // alerta de recategorizacao desaparecer atras do estado.
    const corpo: Corpo = { tipo: "template", nome: "x", idioma: "pt_PT", parametros: [] };
    assert.deepEqual(
      decidir(corpo, FECHADA, AGORA, template({ category: "marketing" }), RESTRITO),
      { enviar: false, motivo: "MARKETING_NOT_ALLOWED" },
    );
  });

  it("**a janela fechada vence o estado**, pela mesma razao", () => {
    // O `WINDOW_CLOSED` e a recusa que nao gasta chamada HTTP e que diz a quem
    // chama «decide template ou desiste». O estado nao a substitui.
    assert.deepEqual(decidir(TEXTO, FECHADA, AGORA, null, RESTRITO), {
      enviar: false,
      motivo: WINDOW_CLOSED,
    });
  });

  it("**um tenant suspenso nao envia nada**, nem dentro da janela", () => {
    // A matriz decide pelo **mais restritivo** dos dois estados: um canal
    // `ativo` de um tenant `suspenso` nao envia. E por isso que a porta devolve
    // o par e nao so o estado do canal.
    const suspenso = { estadoTenant: "suspenso", estadoCanal: "ativo" };
    assert.deepEqual(decidir(TEXTO, ABERTA, AGORA, null, suspenso), {
      enviar: false,
      motivo: "STATE_REFUSED",
    });
  });

  it("o `STATE_REFUSED` esta na lista fechada dos motivos", () => {
    // E lista fechada **e** etiqueta de metrica, pelo que entra no dicionario.
    assert.ok(MOTIVOS_DE_RECUSA.includes("STATE_REFUSED"));
  });
});

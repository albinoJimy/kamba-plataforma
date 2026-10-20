/**
 * Um teste por item de cobertura, e o relatório que o prova (KAM-024, critério 2).
 *
 * O critério pede «≥ 1 *fixture* e ≥ 1 teste por tipo e campo (100%)». Este
 * ficheiro é a metade dos testes: vinte e sete `it`, cada um com a sua marca
 * `[cobertura:<item>]` no nome, e o último a correr o relatório e a exigir zero
 * faltas.
 *
 * ## Cada teste afirma a forma, não a existência
 *
 * Um teste que só verificasse «a *fixture* foi gerada» dava 100% na tabela e
 * zero garantia: uma *fixture* de `audio` com o corpo de um `text` passava. Por
 * isso cada um afirma o que distingue o seu item — o `audio` tem `voice`, a
 * `list_reply` tem `list_reply` e não `button_reply`, o `failed` **não** tem
 * `pricing` —, que é o que torna a marca honesta.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CAMPOS, MOTIVOS_DE_REMOCAO, kindsDe } from "../src/campos.ts";
import { CATEGORIAS, ESTADOS, PRECO_USD, estado } from "../src/estados.ts";
import { Gerador } from "../src/semente.ts";
import { ITENS, emMarkdown, marcasEm, relatorio } from "../src/cobertura.ts";
import { contagemPorItem, fixtureDe, todasAsFixtures } from "../src/fixtures.ts";
import { segredoDeEnsaio } from "../src/assinatura.ts";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SEMENTE = "cobertura-do-kam-024";
const SEGREDO = segredoDeEnsaio(SEMENTE);
const FIXTURES = todasAsFixtures(SEMENTE, SEGREDO);

/** A *fixture* de uma marca. Lança se não existir — é o que se quer. */
function daMarca(marca: string): Record<string, unknown> {
  const fixture = FIXTURES.find((f) => f.item.marca === marca);
  assert.ok(fixture !== undefined, `nao ha fixture para ${marca}`);
  const entrada = fixture.corpo.entry[0];
  assert.ok(entrada !== undefined, `a fixture de ${marca} nao tem entry`);
  const mudanca = entrada.changes[0];
  assert.ok(mudanca !== undefined, `a fixture de ${marca} nao tem changes`);
  return mudanca.value;
}

/** O primeiro item de `messages[]` de uma marca. */
function primeiraMensagem(marca: string): Record<string, unknown> {
  const valor = daMarca(marca);
  const itens = valor.messages;
  assert.ok(Array.isArray(itens) && itens.length > 0, `${marca} nao traz messages`);
  return itens[0] as Record<string, unknown>;
}

/** O primeiro item de `statuses[]` de uma marca. */
function primeiroEstado(marca: string): Record<string, unknown> {
  const valor = daMarca(marca);
  const itens = valor.statuses;
  assert.ok(Array.isArray(itens) && itens.length > 0, `${marca} nao traz statuses`);
  return itens[0] as Record<string, unknown>;
}

describe("cobertura: os dezasseis tipos", () => {
  it("[cobertura:tipo:text] o corpo leva o texto em text.body", () => {
    const item = primeiraMensagem("tipo:text");
    assert.equal(item.type, "text");
    const texto = item.text as { body?: unknown };
    assert.equal(typeof texto.body, "string");
    assert.ok((texto.body as string).length > 0);
  });

  it("[cobertura:tipo:audio] a nota de voz traz voice:true e nao traz URL", () => {
    const item = primeiraMensagem("tipo:audio");
    assert.equal(item.type, "audio");
    const audio = item.audio as Record<string, unknown>;
    assert.equal(audio.voice, true);
    assert.equal(audio.mime_type, "audio/ogg; codecs=opus");
    // Sem URL, de propósito: a URL da Meta expira, e uma *fixture* com URL
    // descrevia uma coisa que não existe. A descarga é contra o Graph falso.
    assert.equal(audio.url, undefined);
    assert.equal(typeof audio.id, "string");
  });

  it("[cobertura:tipo:image] a imagem traz id, mime e sha256", () => {
    const imagem = primeiraMensagem("tipo:image").image as Record<string, unknown>;
    assert.equal(imagem.mime_type, "image/jpeg");
    assert.equal((imagem.sha256 as string).length, 64);
  });

  it("[cobertura:tipo:document] o documento traz filename", () => {
    const doc = primeiraMensagem("tipo:document").document as Record<string, unknown>;
    assert.equal(doc.mime_type, "application/pdf");
    assert.match(doc.filename as string, /^comprovativo-\d{6}\.pdf$/);
  });

  it("[cobertura:tipo:location] as coordenadas sao da zona de Luanda", () => {
    const sitio = primeiraMensagem("tipo:location").location as {
      latitude: number;
      longitude: number;
    };
    assert.ok(sitio.latitude < -8.7 && sitio.latitude > -9.1, `latitude ${sitio.latitude}`);
    assert.ok(sitio.longitude > 13.1 && sitio.longitude < 13.5, `longitude ${sitio.longitude}`);
  });

  it("[cobertura:tipo:interactive:button_reply] a variante e button_reply", () => {
    const interactivo = primeiraMensagem("tipo:interactive:button_reply")
      .interactive as Record<string, unknown>;
    assert.equal(interactivo.type, "button_reply");
    const resposta = interactivo.button_reply as Record<string, unknown>;
    // **O `id` e não o `title`**: é o `id` que o AGR usa (`01` §5.4).
    assert.match(resposta.id as string, /^confirm:[0-9a-f]{8}$/);
    assert.equal(interactivo.list_reply, undefined);
  });

  it("[cobertura:tipo:interactive:list_reply] a variante e list_reply, e nao a outra", () => {
    const interactivo = primeiraMensagem("tipo:interactive:list_reply")
      .interactive as Record<string, unknown>;
    assert.equal(interactivo.type, "list_reply");
    const resposta = interactivo.list_reply as Record<string, unknown>;
    assert.match(resposta.id as string, /^linha:[0-9a-f]{8}$/);
    // Esta é a asserção que apanha o defeito que o `fixtures.ts` descreve: sem
    // a variante explícita, as duas *fixtures* eram `button_reply`.
    assert.equal(interactivo.button_reply, undefined);
  });

  it("[cobertura:tipo:order] a encomenda traz catalog_id e itens com preco", () => {
    const encomenda = primeiraMensagem("tipo:order").order as Record<string, unknown>;
    assert.equal(typeof encomenda.catalog_id, "string");
    const itens = encomenda.product_items as Record<string, unknown>[];
    assert.equal(itens.length, 1);
    assert.equal(itens[0]?.currency, "AOA");
  });

  it("[cobertura:tipo:reaction] a reaccao aponta a mensagem reagida", () => {
    const reaccao = primeiraMensagem("tipo:reaction").reaction as Record<string, unknown>;
    assert.match(reaccao.message_id as string, /^wamid\./);
    assert.equal(typeof reaccao.emoji, "string");
  });

  it("[cobertura:tipo:sticker] o autocolante diz se e animado", () => {
    const autocolante = primeiraMensagem("tipo:sticker").sticker as Record<string, unknown>;
    assert.equal(autocolante.mime_type, "image/webp");
    assert.equal(autocolante.animated, false);
  });

  it("[cobertura:tipo:unsupported] o tipo nao suportado traz errors[]", () => {
    const item = primeiraMensagem("tipo:unsupported");
    assert.equal(item.type, "unsupported");
    const erros = item.errors as Record<string, unknown>[];
    assert.equal(erros.length, 1);
    assert.equal(typeof erros[0]?.code, "number");
  });

  // Os quatro escritos um a um, e **não** num `for` com o nome interpolado.
  // Tentei o `for` primeiro, e o relatório de cobertura recusou-o: ele lê as
  // marcas do **texto** do ficheiro, e o que lá estava era `${estado}` e não
  // `sent`. Está certo em recusar — uma marca que só existe em execução não
  // prova que alguém escreveu um teste para aquele item — e a lição é que a
  // marca tem de ser literal. Quatro `it` custam oito linhas.
  function comPrecoDeServico(item: Record<string, unknown>): void {
    const preco = item.pricing as Record<string, unknown>;
    assert.equal(preco.pricing_model, "CBP");
    assert.equal(preco.billable, true);
    assert.equal(preco.category, "service");
  }

  it("[cobertura:tipo:statuses:sent] o sent traz pricing", () => {
    const item = primeiroEstado("tipo:statuses:sent");
    assert.equal(item.status, "sent");
    assert.match(item.id as string, /^wamid\./);
    comPrecoDeServico(item);
  });

  it("[cobertura:tipo:statuses:delivered] o delivered traz pricing", () => {
    const item = primeiroEstado("tipo:statuses:delivered");
    assert.equal(item.status, "delivered");
    comPrecoDeServico(item);
  });

  it("[cobertura:tipo:statuses:read] o read traz pricing", () => {
    const item = primeiroEstado("tipo:statuses:read");
    assert.equal(item.status, "read");
    comPrecoDeServico(item);
  });

  it("[cobertura:tipo:statuses:failed] o failed traz errors[] e NAO traz pricing", () => {
    const item = primeiroEstado("tipo:statuses:failed");
    assert.equal(item.status, "failed");
    // Não se cobra uma mensagem que não foi entregue (`E1` §1: cobrança por
    // mensagem **entregue**). É a asserção que sustenta o critério 4 do KAM-015.
    assert.equal(item.pricing, undefined);
    assert.ok(Array.isArray(item.errors));
    assert.equal(ESTADOS.length, 4);
  });

  it("[cobertura:tipo:history] a fixture do tipo history e a do campo", () => {
    // O `history` é o único item nas duas dimensões, e a sua *fixture* é uma só
    // — ver `fixtures.ts`. Este teste existe para que a marca do **tipo** tenha
    // um teste seu, e afirma a mesma coisa pelo outro lado da tabela.
    const valor = daMarca("campo:history");
    const lotes = valor.history as Record<string, unknown>[];
    assert.equal(lotes.length, 1);
    assert.ok(Array.isArray(lotes[0]?.threads));
    assert.equal(fixtureDe({ dimensao: "tipo", nome: "history", marca: "tipo:history" }, SEMENTE, SEGREDO), null);
  });
});

describe("cobertura: os onze campos", () => {
  it("[cobertura:campo:messages] o campo traz messages e statuses no mesmo value", () => {
    const valor = daMarca("campo:messages");
    const itens = valor.messages as unknown[];
    const estados = valor.statuses as unknown[];
    assert.equal(itens.length, 10, "os dez tipos de item");
    assert.equal(estados.length, 4, "os quatro estados");
    // É o `value` que dá **dois** `kind` com destinos opostos.
    assert.deepEqual(kindsDe("messages"), ["message", "statuses"]);
  });

  it("[cobertura:campo:smb_message_echoes] o eco vai do negocio para o cliente", () => {
    const valor = daMarca("campo:smb_message_echoes");
    const ecos = valor.message_echoes as Record<string, unknown>[];
    assert.equal(ecos.length, 1);
    // Um eco tem `to` e **não** `from`: é a mensagem que o dono mandou.
    assert.equal(typeof ecos[0]?.to, "string");
    assert.equal(ecos[0]?.from, undefined);
    assert.deepEqual(kindsDe("smb_message_echoes"), ["echo"]);
  });

  it("[cobertura:campo:history] o lote de historico traz o erro 2593109", () => {
    const lote = (daMarca("campo:history").history as Record<string, unknown>[])[0];
    const erros = lote?.errors as Record<string, unknown>[];
    assert.equal(erros[0]?.code, 2593109, "o codigo CONFIRMADO de «nao partilhou historico»");
  });

  it("[cobertura:campo:smb_app_state_sync] a sincronizacao traz contactos", () => {
    const sincronias = daMarca("campo:smb_app_state_sync").state_sync as Record<string, unknown>[];
    assert.equal(sincronias[0]?.type, "contact");
    assert.equal(sincronias[0]?.action, "add");
  });

  it("[cobertura:campo:phone_number_quality_update] a nota e GREEN, YELLOW ou RED", () => {
    const valor = daMarca("campo:phone_number_quality_update");
    assert.ok(["GREEN", "YELLOW", "RED"].includes(valor.quality_score as string));
    // O escalão de 1.000 **já não existe** (`E1` §5), e nenhuma *fixture* o tem.
    assert.notEqual(valor.current_limit, "TIER_1K");
  });

  it("[cobertura:campo:business_capability_update] os limites sao numeros", () => {
    const valor = daMarca("campo:business_capability_update");
    assert.equal(typeof valor.max_daily_conversations_per_phone_number, "number");
    assert.equal(typeof valor.max_phone_numbers_per_business, "number");
  });

  it("[cobertura:campo:account_alerts] o alerta aponta o WABA", () => {
    const valor = daMarca("campo:account_alerts");
    assert.equal(valor.entity_type, "WABA");
    assert.equal(typeof valor.entity_id, "string");
  });

  it("[cobertura:campo:message_template_status_update] o estado e do ciclo de vida", () => {
    const valor = daMarca("campo:message_template_status_update");
    assert.ok(
      ["APPROVED", "REJECTED", "PAUSED", "PENDING", "DISABLED"].includes(valor.event as string),
    );
    assert.equal(valor.message_template_language, "pt_PT");
  });

  it("[cobertura:campo:template_category_update] a recategorizacao e para MARKETING", () => {
    const valor = daMarca("campo:template_category_update");
    // É este o caso que o critério 9 do KAM-015 precisa: a recategorização para
    // `marketing` bloqueia o uso do template e alerta.
    assert.equal(valor.previous_category, "UTILITY");
    assert.equal(valor.new_category, "MARKETING");
  });

  it("[cobertura:campo:message_template_quality_update] a nota desce de GREEN", () => {
    const valor = daMarca("campo:message_template_quality_update");
    assert.equal(valor.previous_quality_score, "GREEN");
    assert.ok(["YELLOW", "RED"].includes(valor.new_quality_score as string));
  });
});

describe("cobertura: os seis motivos de PARTNER_REMOVED", () => {
  // Um `it` por motivo, com a marca literal. A revisão adversarial mostrou que
  // quatro dos seis só existiam na declaração do `enum`: não havia *fixture*
  // nem teste, e o critério 2 escreve «`account_update` (6 motivos)».
  function motivoDe(nome: string): string {
    const valor = daMarca(`motivo:${nome.toLowerCase()}`);
    assert.equal(valor.event, "PARTNER_REMOVED");
    const info = valor.partner_removed_info as Record<string, unknown>;
    return info.reason as string;
  }

  it("[cobertura:motivo:primary_inactivity] o canal principal ficou inactivo", () => {
    assert.equal(motivoDe("PRIMARY_INACTIVITY"), "PRIMARY_INACTIVITY");
  });

  it("[cobertura:motivo:companion_inactivity] o companheiro ficou inactivo", () => {
    assert.equal(motivoDe("COMPANION_INACTIVITY"), "COMPANION_INACTIVITY");
  });

  it("[cobertura:motivo:business_downgrade] o negocio baixou de plano", () => {
    assert.equal(motivoDe("BUSINESS_DOWNGRADE"), "BUSINESS_DOWNGRADE");
  });

  it("[cobertura:motivo:change_number] o dono mudou de numero", () => {
    // É o motivo que pede uma acção diferente de todos os outros: o canal não
    // volta sozinho, e o KAM-021 tem de pedir ao dono que repita o ES.
    assert.equal(motivoDe("CHANGE_NUMBER"), "CHANGE_NUMBER");
  });

  it("[cobertura:motivo:user_re_registered] o utilizador registou-se outra vez", () => {
    assert.equal(motivoDe("USER_RE_REGISTERED"), "USER_RE_REGISTERED");
  });

  it("[cobertura:motivo:account_disconnected] a conta foi desligada", () => {
    assert.equal(motivoDe("ACCOUNT_DISCONNECTED"), "ACCOUNT_DISCONNECTED");
  });

  it("[cobertura:campo:account_update] o campo tem fixture propria, com um dos seis", () => {
    const valor = daMarca("campo:account_update");
    assert.equal(valor.event, "PARTNER_REMOVED");
    const info = valor.partner_removed_info as Record<string, unknown>;
    assert.ok(MOTIVOS_DE_REMOCAO.includes(info.reason as never), `motivo ${String(info.reason)}`);
  });

  it("as seis fixtures de motivo tem bytes diferentes entre si", () => {
    // Seis *fixtures* com os mesmos bytes seriam seis linhas na tabela a dizer
    // a mesma coisa, que é o 100% sem nada por baixo.
    const vistas = new Set(
      MOTIVOS_DE_REMOCAO.map((m) => {
        const f = FIXTURES.find((x) => x.item.marca === `motivo:${m.toLowerCase()}`);
        assert.ok(f !== undefined, m);
        return Buffer.from(f.bytes).toString("hex");
      }),
    );
    assert.equal(vistas.size, 6);
  });
});

describe("o pricing dos estados (revisao adversarial)", () => {
  it("um failed com comPricing explicito leva pricing", () => {
    // **A opcao era engolida em silencio.** O critério 1 escreve «`statuses`
    // (…, `failed`, com `pricing`)», e sem forma de gerar o caso nao havia como
    // o KAM-015 provar que o recusa. A omissao continua a ser «sem `pricing`»,
    // porque nao se cobra uma mensagem que nao foi entregue; o que mudou e que
    // um `true` explicito e honrado. Quem decide se o caso e legitimo e o
    // KAM-015, nao o gerador.
    const semPreco = estado(new Gerador("e"), {
      wamid: "wamid.X",
      estado: "failed",
      recipienteId: "999100000001",
    });
    assert.equal(semPreco.pricing, undefined, "a omissao");
    assert.ok(Array.isArray(semPreco.errors));

    const comPreco = estado(new Gerador("e"), {
      wamid: "wamid.X",
      estado: "failed",
      recipienteId: "999100000001",
      comPricing: true,
    });
    const preco = comPreco.pricing as Record<string, unknown>;
    assert.equal(preco.pricing_model, "CBP");
    // E continua a levar `errors[]`: um `failed` com preco e um `failed`.
    assert.ok(Array.isArray(comPreco.errors));
  });

  it("um sent com comPricing false NAO leva pricing", () => {
    // E o caso que o descarte sob saturacao do GWY pode deitar fora, e tem de
    // existir como *fixture* para que o criterio 7 do KAM-013 distinga os dois.
    const item = estado(new Gerador("e"), {
      wamid: "wamid.X",
      estado: "sent",
      recipienteId: "999100000001",
      comPricing: false,
    });
    assert.equal(item.pricing, undefined);
  });

  it("as quatro categorias dao o preco de Rest of Africa", () => {
    // `PRECO_USD` nao era lido em sitio nenhum do repositorio e nenhum teste o
    // afirmava: um valor errado ali passava. Sao CONFIRMADO no `E1` §1.
    assert.equal(CATEGORIAS.length, 4);
    assert.equal(PRECO_USD.service, 0.004);
    assert.equal(PRECO_USD.utility, 0.004);
    assert.equal(PRECO_USD.authentication, 0.004);
    assert.equal(PRECO_USD.marketing, 0.0225);
    // O `marketing` e cerca de 5,6x o `utility`, que e o numero que o
    // `../docs/tecnica/01` §4.5 cita.
    assert.ok(Math.abs(PRECO_USD.marketing / PRECO_USD.utility - 5.6) < 0.1);
  });

  it("uma categoria diferente de service aparece no pricing", () => {
    const item = estado(new Gerador("e"), {
      wamid: "wamid.X",
      estado: "delivered",
      recipienteId: "999100000001",
      categoria: "marketing",
    });
    const preco = item.pricing as Record<string, unknown>;
    assert.equal(preco.category, "marketing");
    // O `type` e `regular` para tudo o que nao e `service`.
    assert.equal(preco.type, "regular");
  });
});

describe("o relatorio de cobertura", () => {
  const FICHEIROS = [
    "cobertura.test.ts",
    "simulador.test.ts",
    "adversos.test.ts",
    "graph.test.ts",
    "captura.test.ts",
  ];

  function fontes(): readonly string[] {
    return FICHEIROS.map((nome) => readFileSync(join(import.meta.dirname, nome), "utf8"));
  }

  it("da 100% e nenhuma falta", () => {
    const r = relatorio(contagemPorItem(FIXTURES), fontes());
    assert.deepEqual(
      r.faltas.map((f) => f.item.marca),
      [],
      `faltas no relatorio:\n${emMarkdown(r)}`,
    );
    assert.equal(r.percentagem, 100);
  });

  it("nao tem marcas desconhecidas", () => {
    // Uma marca mal escrita contaria um teste que não cobre nada e deixaria um
    // item descoberto ao mesmo tempo. O relatório trata-a como erro.
    const r = relatorio(contagemPorItem(FIXTURES), fontes());
    assert.deepEqual(r.marcasDesconhecidas, []);
  });

  it("tem 33 itens: 16 tipos, 11 campos e 6 motivos", () => {
    assert.equal(ITENS.filter((i) => i.dimensao === "tipo").length, 16);
    assert.equal(ITENS.filter((i) => i.dimensao === "campo").length, 11);
    assert.equal(ITENS.filter((i) => i.dimensao === "motivo").length, 6);
    assert.equal(ITENS.length, 33);
    assert.equal(CAMPOS.length, 11);
    assert.equal(MOTIVOS_DE_REMOCAO.length, 6);
  });

  it("uma marca escrita so num comentario NAO conta", () => {
    // É o achado da revisão adversarial: a primeira versão contava qualquer
    // ocorrência textual, e por isso 27 marcas em comentários davam 100% sem
    // existir teste nenhum. Comentar um `it` inteiro mantinha o verde.
    const soComentarios = ITENS.map((i) => `// [cobertura:${i.marca}] nenhum teste aqui`).join("\n");
    const r = relatorio(contagemPorItem(FIXTURES), [soComentarios]);
    assert.equal(r.faltas.length, ITENS.length);
    assert.equal(r.percentagem, 0);
  });

  it("a marca conta quando esta no nome de um it(", () => {
    const comIt = ITENS.map((i) => `it("[cobertura:${i.marca}] x", () => {});`).join("\n");
    const r = relatorio(contagemPorItem(FIXTURES), [comIt]);
    assert.deepEqual(r.faltas, []);
  });

  it("falha quando um item perde o teste", () => {
    // O relatório tem de poder falhar: um relatório que dá 100% com uma lista de
    // fontes vazia não prova nada, e esta é a asserção que o distingue.
    const r = relatorio(contagemPorItem(FIXTURES), []);
    assert.equal(r.faltas.length, 33);
    assert.equal(r.percentagem, 0);
  });

  it("extrai as marcas de um texto", () => {
    assert.deepEqual(marcasEm("it('[cobertura:tipo:text] x')"), ["tipo:text"]);
    assert.deepEqual(marcasEm("sem marca nenhuma"), []);
  });
});

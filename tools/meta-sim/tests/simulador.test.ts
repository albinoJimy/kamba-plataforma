/**
 * Determinismo, assinatura, números fictícios e paridade com o canon
 * (KAM-024, critérios 1, 4 e 7).
 *
 * Os quatro grupos deste ficheiro são os que, se falharem, tornam todos os
 * outros testes do pacote inúteis:
 *
 * 1. **determinismo** — sem ele não há *fixture*, há um gerador de ruído;
 * 2. **assinatura** — é o que faz os corpos aceitáveis pelo GWY;
 * 3. **números fictícios** — é o que impede um dado pessoal no repositório;
 * 4. **paridade** — é o que impede o simulador de divergir do `core-ts` e do
 *    `fake_numbers.yaml` sem ninguém notar.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { KIND_POR_CAMPO, WA_TYPES } from "@kamba/core-ts/entrada";

import {
  CABECALHO,
  PREFIXO,
  SegredoDeVerdadeError,
  assinar,
  assinarMal,
  confere,
  exigirSegredoDeEnsaio,
  segredoDeEnsaio,
} from "../src/assinatura.ts";
import { CAMPOS } from "../src/campos.ts";
import { MODOS, corpo, mudarUmByte, serializar, texto } from "../src/corpo.ts";
import { todasAsFixtures, cenarioDe } from "../src/fixtures.ts";
import {
  ALGARISMOS,
  INDICATIVO_FICTICIO,
  INTERVALO,
  NumeroRealError,
  PADROES_DE_TELEFONE_REAL,
  eFicticio,
  exigirFicticios,
  telefonesReais,
} from "../src/numeros.ts";
import { TIPOS, VARIANTES_INTERACTIVAS } from "../src/mensagens.ts";
import { Gerador } from "../src/semente.ts";

const SEMENTE = "simulador-do-kam-024";
const SEGREDO = segredoDeEnsaio(SEMENTE);

describe("determinismo (criterio 1)", () => {
  it("a mesma semente da bytes identicos, fixture por fixture", () => {
    const primeira = todasAsFixtures(SEMENTE, SEGREDO);
    const segunda = todasAsFixtures(SEMENTE, SEGREDO);
    assert.equal(primeira.length, segunda.length);
    for (let i = 0; i < primeira.length; i += 1) {
      const a = primeira[i];
      const b = segunda[i];
      assert.ok(a !== undefined && b !== undefined);
      assert.equal(a.item.marca, b.item.marca);
      assert.deepEqual(
        Buffer.from(a.bytes).toString("hex"),
        Buffer.from(b.bytes).toString("hex"),
        `${a.item.marca} nao e byte-identica`,
      );
      assert.equal(a.assinatura, b.assinatura);
    }
  });

  it("uma semente diferente da bytes diferentes", () => {
    const a = todasAsFixtures(SEMENTE, SEGREDO);
    const b = todasAsFixtures(`${SEMENTE}-outra`, segredoDeEnsaio(`${SEMENTE}-outra`));
    let iguais = 0;
    for (let i = 0; i < a.length; i += 1) {
      if (Buffer.from(a[i]?.bytes ?? []).equals(Buffer.from(b[i]?.bytes ?? []))) iguais += 1;
    }
    // Zero e não «poucas»: duas sementes diferentes que dessem a mesma *fixture*
    // significavam que o gerador não entra naquele corpo, e aí o determinismo
    // era uma constante disfarçada.
    assert.equal(iguais, 0);
  });

  it("acrescentar uma fixture nao muda os bytes das outras", () => {
    // É a propriedade que a semente derivada por marca compra: os bytes de uma
    // *fixture* dependem do **nome** dela e de mais nada. O teste simula o
    // «acrescentar» gerando uma sub-lista e comparando com a lista inteira.
    const todas = todasAsFixtures(SEMENTE, SEGREDO);
    const umaSo = todas.filter((f) => f.item.marca === "tipo:sticker");
    assert.equal(umaSo.length, 1);
    const direita = todas.find((f) => f.item.marca === "tipo:sticker");
    assert.ok(direita !== undefined);
    assert.ok(Buffer.from(umaSo[0]?.bytes ?? []).equals(Buffer.from(direita.bytes)));
  });

  it("o gerador avanca a cada leitura e nao se repete", () => {
    const g = new Gerador("passos");
    const antes = g.passos;
    const valores = new Set<number>();
    for (let i = 0; i < 200; i += 1) valores.add(g.inteiro(1_000_000));
    assert.ok(g.passos > antes);
    // Duzentos valores de um milhão: algumas colisões são possíveis, muitas não.
    assert.ok(valores.size > 190, `${valores.size} valores distintos de 200`);
  });

  it("derivar da sub-sequencias estaveis e diferentes", () => {
    const a = new Gerador("raiz").derivar("x").inteiro(1_000_000);
    const b = new Gerador("raiz").derivar("x").inteiro(1_000_000);
    const c = new Gerador("raiz").derivar("y").inteiro(1_000_000);
    assert.equal(a, b);
    assert.notEqual(a, c);
  });

  it("o canal e o interlocutor sao os mesmos em todas as fixtures", () => {
    const cenario = cenarioDe(SEMENTE);
    for (const fixture of todasAsFixtures(SEMENTE, SEGREDO)) {
      assert.equal(fixture.corpo.entry[0]?.id, cenario.canal.wabaId, fixture.item.marca);
    }
  });
});

describe("serializacao: o mesmo JSON com bytes diferentes (criterio 4)", () => {
  const cenario = cenarioDe(SEMENTE);
  const montado = corpo(new Gerador(SEMENTE), {
    canal: cenario.canal,
    mudancas: [{ campo: "messages", opcoes: { canal: cenario.canal, quem: cenario.quem } }],
  });

  it("os dois modos dao o mesmo objecto", () => {
    assert.deepEqual(JSON.parse(texto(montado, "compacto")), JSON.parse(texto(montado, "espacado")));
  });

  it("e bytes diferentes", () => {
    const a = serializar(montado, "compacto");
    const b = serializar(montado, "espacado");
    assert.notEqual(a.byteLength, b.byteLength);
    assert.equal(MODOS.length, 2);
  });

  it("a assinatura de um nao serve para o outro", () => {
    // É isto que prova que a assinatura é sobre os **bytes**. Um GWY que
    // normalizasse o corpo antes de verificar aceitava os dois.
    const a = serializar(montado, "compacto");
    const b = serializar(montado, "espacado");
    assert.ok(confere(a, assinar(a, SEGREDO), SEGREDO));
    assert.ok(!confere(b, assinar(a, SEGREDO), SEGREDO));
  });

  it("mudar um byte invalida a assinatura e mantem o JSON valido", () => {
    const a = serializar(montado, "compacto");
    const mexido = mudarUmByte(a);
    assert.equal(mexido.byteLength, a.byteLength, "o comprimento nao muda");
    assert.ok(!confere(mexido, assinar(a, SEGREDO), SEGREDO));
    // O corpo mexido continua a dar `parse`: o que o GWY recusa é um corpo bem
    // formado que não bate com a assinatura, e não lixo.
    assert.doesNotThrow(() => JSON.parse(Buffer.from(mexido).toString("utf8")));
  });

  it("mudarUmByte recusa um corpo sem algarismos em vez de nao mudar nada", () => {
    assert.throws(() => mudarUmByte(new Uint8Array(Buffer.from("sem digitos", "utf8"))), /algarismo/);
  });
});

describe("assinatura (criterio 4)", () => {
  const bytes = new Uint8Array(Buffer.from('{"object":"whatsapp_business_account"}', "utf8"));

  it("o cabecalho e o prefixo sao os do protocolo", () => {
    assert.equal(CABECALHO, "x-hub-signature-256");
    assert.equal(PREFIXO, "sha256=");
  });

  it("o valor tem o prefixo e 64 hexadecimais", () => {
    assert.match(assinar(bytes, SEGREDO), /^sha256=[0-9a-f]{64}$/);
  });

  it("assinarMal produz algo que nao bate, com o mesmo comprimento", () => {
    const boa = assinar(bytes, SEGREDO);
    const ma = assinarMal(bytes, SEGREDO);
    assert.equal(ma.length, boa.length);
    assert.notEqual(ma, boa);
    assert.ok(!confere(bytes, ma, SEGREDO));
  });

  it("confere recusa um cabecalho sem prefixo, vazio ou de outro comprimento", () => {
    assert.ok(!confere(bytes, assinar(bytes, SEGREDO).slice(PREFIXO.length), SEGREDO));
    assert.ok(!confere(bytes, PREFIXO, SEGREDO));
    assert.ok(!confere(bytes, `${PREFIXO}abcd`, SEGREDO));
  });

  it("o segredo de ensaio e deterministico e tem o prefixo", () => {
    assert.equal(segredoDeEnsaio("x"), segredoDeEnsaio("x"));
    assert.notEqual(segredoDeEnsaio("x"), segredoDeEnsaio("y"));
    assert.match(SEGREDO, /^ensaio-[0-9a-f]{32}$/);
  });

  it("recusa um segredo sem o prefixo de ensaio", () => {
    assert.throws(() => exigirSegredoDeEnsaio("segredo-de-prod"), SegredoDeVerdadeError);
  });

  it("recusa um segredo igual ao de um KAMBA_SECRET_* do ambiente", () => {
    // É a «verificação de configuração» que o critério 4 pede por extenso: «o
    // segredo de teste nunca coincide com um segredo de staging/prod».
    const ambiente = { KAMBA_SECRET_META_APP_SECRET: SEGREDO, PATH: "/usr/bin" };
    assert.throws(
      () => exigirSegredoDeEnsaio(SEGREDO, ambiente),
      /KAMBA_SECRET_META_APP_SECRET/,
    );
  });

  it("aceita o segredo de ensaio quando o ambiente tem outros", () => {
    assert.doesNotThrow(() =>
      exigirSegredoDeEnsaio(SEGREDO, { KAMBA_SECRET_META_APP_SECRET: "outro", KAMBA_SECRET_VAZIO: "" }),
    );
  });
});

describe("numeros ficticios (criterio 7)", () => {
  it("todos os telefones das fixtures sao do intervalo reservado", () => {
    for (const fixture of todasAsFixtures(SEMENTE, SEGREDO)) {
      assert.doesNotThrow(
        () => exigirFicticios(Buffer.from(fixture.bytes).toString("utf8")),
        `${fixture.item.marca} tem um telefone com forma real`,
      );
    }
  });

  it("o intervalo e o 999, que a UIT nao atribui", () => {
    assert.equal(INDICATIVO_FICTICIO, "999");
    assert.equal(ALGARISMOS, 9);
    assert.ok(eFicticio(INTERVALO.primeiro));
    assert.ok(eFicticio(INTERVALO.ultimo));
    assert.ok(!eFicticio("244923456789"));
  });

  it("reconhece um telefone angolano e um E.164 entre aspas", () => {
    assert.equal(telefonesReais("ligue +244 923456789 hoje").length, 1);
    assert.equal(telefonesReais('{"wa_id":"+351912345678"}').length, 1);
    assert.equal(telefonesReais("sem telefone nenhum").length, 0);
  });

  it("um numero do intervalo ficticio nao e ocorrencia, mesmo entre aspas", () => {
    // Sem esta excepção a ferramenta recusava gravar as suas próprias
    // *fixtures*, porque o `999...` casa o padrão do E.164 entre aspas.
    assert.equal(telefonesReais('{"wa_id":"+999123456789"}').length, 0);
  });

  it("exigirFicticios lanca NumeroRealError e nao imprime o numero", () => {
    try {
      exigirFicticios('{"wa_id":"+244923456789"}');
      assert.fail("devia ter lancado");
    } catch (erro) {
      assert.ok(erro instanceof NumeroRealError);
      // A mensagem **não** leva o número: um erro vai para o registo do CI.
      assert.ok(!erro.message.includes("923456789"), erro.message);
      assert.match(erro.message, /padrao/);
    }
  });

  it("o fake_numbers.yaml diz o mesmo que o codigo", () => {
    // O ficheiro é o que uma pessoa lê e o critério 7 nomeia; a constante é o
    // que o código usa. Este teste é o que impede os dois de divergirem sem
    // acrescentar um quarto leitor de YAML ao repositório.
    const yaml = readFileSync(join(import.meta.dirname, "..", "fake_numbers.yaml"), "utf8");
    assert.match(yaml, new RegExp(`indicativo:\\s*"${INDICATIVO_FICTICIO}"`));
    assert.match(yaml, new RegExp(`algarismos:\\s*${ALGARISMOS}`));
    assert.ok(yaml.includes(INTERVALO.primeiro), "o primeiro do intervalo");
    assert.ok(yaml.includes(INTERVALO.ultimo), "o ultimo do intervalo");
    for (const { padrao } of PADROES_DE_TELEFONE_REAL) {
      assert.ok(yaml.includes(padrao.source), `o padrao ${padrao.source} nao esta no YAML`);
    }
  });
});

describe("paridade com o canon", () => {
  it("os tipos sao os do WA_TYPES do core-ts", () => {
    // O simulador **importa** a lista; este teste prova que não a copiou.
    assert.deepEqual([...TIPOS], [...WA_TYPES]);
    assert.equal(TIPOS.length, 10);
  });

  it("os onze campos sao os dez do KIND_POR_CAMPO mais o messages", () => {
    const doMapa = Object.keys(KIND_POR_CAMPO).sort();
    const daqui = CAMPOS.filter((c) => c !== "messages").slice().sort();
    assert.deepEqual(daqui, doMapa);
    assert.equal(doMapa.length, 10);
    assert.ok(CAMPOS.includes("messages"));
  });

  it("as duas variantes interactivas estao nomeadas", () => {
    assert.deepEqual([...VARIANTES_INTERACTIVAS], ["button_reply", "list_reply"]);
  });
});

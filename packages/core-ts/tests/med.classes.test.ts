/**
 * A tradução de vocabulário e a *allowlist* (KAM-020, critério 4).
 *
 * Funções puras, e é por isso que esta bateria é separada: o que ela prende são
 * decisões que se leem numa linha e que custam caro quando estão erradas — qual
 * `wa_type` traz mídia, que tipos passam, e o que se diz ao cliente quando não
 * passam.
 *
 * O que estes testes prendem, por ordem de gravidade:
 *
 * 1. **O `sticker` é imagem e não uma quarta classe.** Uma classe a mais
 *    multiplicava a política de retenção do KAM-071 sem mudar nada.
 * 2. **Os seis `wa_type` que não são mídia devolvem `null`.** O `WA_TYPES` tem
 *    dez valores; tratar um `location` como mídia punha uma linha numa tabela
 *    que diz guardar ficheiros.
 * 3. **Só PDF em documentos**, e a estreiteza é a defesa: a análise de malware
 *    «não consta de `docs/tecnica/`» e fica para o KAM-065.
 * 4. **O tipo antes do tamanho**, porque «manda outro formato» e «manda mais
 *    pequeno» são conselhos diferentes.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CLASSES,
  LIMITES_POR_OMISSAO,
  MOTIVOS_DE_REJEICAO,
  RESPOSTAS,
  classeDe,
  normalizar,
  recusar,
} from "../src/med/index.ts";
import { WA_TYPES } from "../src/entrada/index.ts";

describe("a traducao de wa_type em classe", () => {
  it("os quatro tipos de midia dao a sua classe", () => {
    assert.equal(classeDe("audio"), "media_audio");
    assert.equal(classeDe("image"), "media_imagem");
    assert.equal(classeDe("document"), "media_documento");
    assert.equal(classeDe("sticker"), "media_imagem");
  });

  it("**o sticker e imagem e nao uma quarta classe**", () => {
    // Do ponto de vista do armazenamento e da retencao um sticker e uma
    // imagem. Uma quarta classe multiplicava a politica de retencao do KAM-071
    // sem mudar nada, e a lista de classes e do primeiro consumidor — nos.
    assert.equal(classeDe("sticker"), classeDe("image"));
    assert.deepEqual([...CLASSES], ["media_audio", "media_imagem", "media_documento"]);
  });

  it("**os seis que nao sao midia devolvem null**", () => {
    // O `WA_TYPES` tem dez valores e quatro sao de midia. Tratar um `location`
    // como midia punha uma linha numa tabela que diz guardar ficheiros, e
    // nenhum `media_id` para ir buscar.
    const naoMidia = WA_TYPES.filter((tipo) => classeDe(tipo) === null);
    assert.deepEqual(
      [...naoMidia].sort(),
      ["interactive", "location", "order", "reaction", "text", "unsupported"],
    );
    assert.equal(naoMidia.length + 4, WA_TYPES.length);
  });

  it("um tipo desconhecido tambem da null", () => {
    assert.equal(classeDe("outro"), null);
    assert.equal(classeDe(""), null);
    assert.equal(classeDe("AUDIO"), null, "a comparacao e exacta: o webhook da minusculas");
  });
});

describe("a allowlist (criterio 4)", () => {
  it("os tipos do bloco do ticket passam", () => {
    assert.equal(recusar("media_imagem", "image/jpeg", 1000), null);
    assert.equal(recusar("media_imagem", "image/png", 1000), null);
    assert.equal(recusar("media_imagem", "image/webp", 1000), null);
    assert.equal(recusar("media_audio", "audio/ogg", 1000), null);
    assert.equal(recusar("media_documento", "application/pdf", 1000), null);
  });

  it("**o OGG com codecs passa**, que e a forma que a Meta manda", () => {
    // As notas de voz do WhatsApp chegam como `audio/ogg; codecs=opus`.
    // Comparar a cadeia inteira recusava-as todas.
    assert.equal(recusar("media_audio", "audio/ogg; codecs=opus", 1000), null);
    assert.equal(recusar("media_audio", "audio/ogg;codecs=opus", 1000), null);
  });

  it("a comparacao ignora a caixa, porque o cabecalho nao a garante", () => {
    assert.equal(recusar("media_imagem", "IMAGE/JPEG", 1000), null);
    assert.equal(recusar("media_imagem", "  image/Png  ", 1000), null);
  });

  it("**so PDF em documentos**, e a estreiteza e a defesa", () => {
    // A analise de malware e de conteudo activo «nao consta de
    // `docs/tecnica/`» (bloco do ticket) e fica para o KAM-065. Aceitar
    // `.docx` era aceitar macros sem ter quem as inspeccione.
    assert.equal(
      recusar("media_documento", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 10),
      "tipo_nao_permitido",
    );
    assert.equal(recusar("media_documento", "application/zip", 10), "tipo_nao_permitido");
    assert.equal(recusar("media_documento", "text/html", 10), "tipo_nao_permitido");
  });

  it("um tipo de outra classe nao passa na classe errada", () => {
    // Um `image/jpeg` numa classe de audio e um webhook que mente ou um defeito
    // nosso na traducao. Os dois merecem recusa.
    assert.equal(recusar("media_audio", "image/jpeg", 10), "tipo_nao_permitido");
    assert.equal(recusar("media_imagem", "audio/ogg", 10), "tipo_nao_permitido");
  });

  it("**o tipo vem antes do tamanho**, e a ordem e a do conselho", () => {
    // «Manda outro formato» e «manda mais pequeno» sao conselhos diferentes, e
    // dizer o segundo a quem mandou um `.docx` de 1 KB nao ajuda ninguem.
    const enorme = LIMITES_POR_OMISSAO.media_imagem.bytesMaximos + 1;
    assert.equal(recusar("media_imagem", "application/zip", enorme), "tipo_nao_permitido");
  });

  it("o tamanho maximo e por classe, e no limite passa", () => {
    for (const classe of CLASSES) {
      const limite = LIMITES_POR_OMISSAO[classe];
      const tipo = limite.tipos[0];
      assert.ok(tipo !== undefined);
      // **No limite passa; um byte acima nao.** Um `>=` aqui recusava um
      // ficheiro exactamente do tamanho permitido, que e o erro de fronteira
      // mais fácil de escrever e o mais chato de descobrir.
      assert.equal(recusar(classe, tipo, limite.bytesMaximos), null, classe);
      assert.equal(
        recusar(classe, tipo, limite.bytesMaximos + 1),
        "tamanho_excedido",
        classe,
      );
    }
  });

  it("os limites sao injectaveis, porque vao em configuracao", () => {
    // Fixar um limite num literal obriga a um commit para o mudar, e quem o
    // muda e quem opera — a razao que o KAM-015 escreveu para a versao da
    // Graph. Os valores por omissao sao *proposta* e calibram contra a API da
    // Meta, que nao tem evidencia nenhuma no `E1`.
    const apertados = {
      ...LIMITES_POR_OMISSAO,
      media_imagem: { tipos: ["image/png"], bytesMaximos: 10 },
    };
    assert.equal(recusar("media_imagem", "image/jpeg", 5, apertados), "tipo_nao_permitido");
    assert.equal(recusar("media_imagem", "image/png", 11, apertados), "tamanho_excedido");
    assert.equal(recusar("media_imagem", "image/png", 10, apertados), null);
  });

  it("o `normalizar` e o que a comparacao usa", () => {
    assert.equal(normalizar("  IMAGE/JPEG  "), "image/jpeg");
  });
});

describe("as respostas ao cliente sao deterministicas (criterio 4)", () => {
  it("os tres motivos tem resposta, e a lista e fechada", () => {
    assert.deepEqual([...MOTIVOS_DE_REJEICAO].sort(), Object.keys(RESPOSTAS).sort());
  });

  it("**nenhuma resposta ecoa o que o cliente mandou**", () => {
    // A frase vai para o WhatsApp. Ecoar o tipo ou o tamanho nao acrescenta
    // nada ao que ele tem de fazer, e os textos ao cliente sao decisao de
    // produto a partir do KAM-025 — inventar aqui um que cite dados dele era
    // decidir por quem nao decidiu.
    for (const [motivo, frase] of Object.entries(RESPOSTAS)) {
      assert.ok(!frase.includes("/"), `${motivo} cita um content-type`);
      assert.ok(!/\d/.test(frase), `${motivo} cita um numero`);
    }
  });

  it("as tres frases sao diferentes, e cada uma diz o que fazer", () => {
    const frases = Object.values(RESPOSTAS);
    assert.equal(new Set(frases).size, frases.length, "duas respostas iguais");
    for (const frase of frases) {
      assert.ok(frase.includes("?"), "uma resposta que nao pergunta nada nao pede nada");
    }
  });
});

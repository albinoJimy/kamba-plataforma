/**
 * Captura, saneamento e o *scan* (KAM-024, critério 7 e DoD «Privacidade»).
 *
 * A captura é a única parte do simulador que toca em dados reais, e por isso é a
 * que mais vale testar pelo lado negativo: um saneador que falhe em silêncio é
 * pior do que não existir, porque dá a quem o usa a confiança de gravar.
 *
 * O corpo de entrada destes testes tem telefones de **forma real** de propósito
 * — é o que uma captura é — e é por isso que este ficheiro é o único do pacote
 * que não passa pelo `exigirFicticios`. Os números são de prefixos que não
 * existem em Angola (`+244 9` seguido de `0000000x`), e nenhum deles sai daqui:
 * tudo o que se afirma é sobre a **saída**, que não os pode ter.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CapturaRecusadaError, sanear, varrer } from "../src/captura.ts";
import { eFicticio, telefonesReais } from "../src/numeros.ts";

/** Uma captura «real», com tudo o que um corpo real tem de pessoal. */
function capturaCrua(): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "109876543210987",
        time: 1_790_900_000,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: "+244 900000001",
                phone_number_id: "119876543210987",
              },
              contacts: [
                {
                  profile: { name: "Maria dos Santos" },
                  user_id: "AO.REALBSUIDREALBSUID0001",
                  wa_id: "244900000002",
                },
              ],
              messages: [
                {
                  from: "244900000002",
                  from_user_id: "AO.REALBSUIDREALBSUID0001",
                  id: "wamid.MjQ0OTAwMDAwMDAyfGFiY2Q=",
                  timestamp: "1790900000",
                  type: "text",
                  text: { body: "Moro na Rua X, 12, e o meu numero e 244900000002" },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

describe("saneamento (criterio 7)", () => {
  it("a saida nao tem nenhum telefone com forma real", () => {
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    assert.deepEqual(telefonesReais(JSON.stringify(arvore)), []);
  });

  it("os telefones substituidos sao do intervalo ficticio", () => {
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: {
        changes: {
          value: {
            metadata: { display_phone_number: string };
            contacts: { wa_id: string }[];
            messages: { from: string }[];
          };
        }[];
      }[];
    };
    const valor = corpo.entry[0]?.changes[0]?.value;
    assert.ok(valor !== undefined);
    // O `display_phone_number` entrou com `+` e sai com `+`: a *fixture* tem de
    // exercitar o mesmo *parsing* que o corpo real exercitava.
    assert.match(valor.metadata.display_phone_number, /^\+999\d{9}$/);
    assert.ok(eFicticio(valor.contacts[0]?.wa_id ?? ""));
    assert.ok(eFicticio(valor.messages[0]?.from ?? ""));
  });

  it("o mesmo numero real da o mesmo numero ficticio dentro da captura", () => {
    // Sem isto a *fixture* deixava de descrever o que descrevia: duas mensagens
    // do mesmo contacto passavam a ser de dois contactos.
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: { changes: { value: { contacts: { wa_id: string }[]; messages: { from: string }[] } }[] }[];
    };
    const valor = corpo.entry[0]?.changes[0]?.value;
    assert.equal(valor?.contacts[0]?.wa_id, valor?.messages[0]?.from);
  });

  it("o texto da mensagem e substituido por inteiro", () => {
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: { changes: { value: { messages: { text: { body: string } }[] } }[] }[];
    };
    const texto = corpo.entry[0]?.changes[0]?.value.messages[0]?.text.body ?? "";
    // Não se «limpa» texto livre: substitui-se. Uma limpeza parcial é uma
    // aposta, e o endereço que lá estava ficaria.
    assert.ok(!texto.includes("Rua X"));
    assert.ok(!texto.includes("244900000002"));
    assert.match(texto, /saneamento/);
  });

  it("o nome do perfil passa a ser um nome de negocio ficticio", () => {
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: { changes: { value: { contacts: { profile: { name: string } }[] } }[] }[];
    };
    const nome = corpo.entry[0]?.changes[0]?.value.contacts[0]?.profile.name ?? "";
    assert.ok(!nome.includes("Maria"));
    assert.ok(nome.length > 0);
  });

  it("o wamid novo nao leva o numero real dentro do base64", () => {
    // O `wamid` da Meta **contém** o número do interlocutor (INDÍCIO,
    // `docs/logs.md` §2.1). Um saneamento que trocasse o `wamid` por outro
    // construído com o número real deixava o número na *fixture*, dentro de
    // base64, onde o scan de texto não o vê. É o caminho que o `idOpaco` do
    // KAM-068 existe para fechar.
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: { changes: { value: { messages: { id: string }[] } }[] }[];
    };
    const id = corpo.entry[0]?.changes[0]?.value.messages[0]?.id ?? "";
    assert.match(id, /^wamid\./);
    const dentro = Buffer.from(id.slice("wamid.".length), "base64url").toString("utf8");
    assert.ok(!dentro.includes("244900000002"), `o wamid leva o numero real: ${dentro.length} bytes`);
    assert.deepEqual(telefonesReais(dentro), []);
  });

  it("o entry.id e tratado como waba_id e nao como wamid", () => {
    // As duas chaves chamam-se `id`. Um saneador que olhasse só para o nome
    // trocava o `waba_id` por um `wamid`, e a *fixture* deixava de descrever um
    // WABA — o `explodir` do KAM-013 mandava-a inteira para a quarentena.
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as { entry: { id: string }[] };
    assert.match(corpo.entry[0]?.id ?? "", /^10\d{13}$/);
    assert.notEqual(corpo.entry[0]?.id, "109876543210987");
  });

  it("o phone_number_id tambem e substituido", () => {
    const { arvore } = sanear(capturaCrua(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: { changes: { value: { metadata: { phone_number_id: string } } }[] }[];
    };
    const id = corpo.entry[0]?.changes[0]?.value.metadata.phone_number_id;
    assert.notEqual(id, "119876543210987");
    assert.match(id ?? "", /^12\d{13}$/);
  });

  it("o relatorio conta o que entrou e o que foi substituido", () => {
    const saneamento = sanear(capturaCrua(), "semente-de-ensaio");
    assert.ok(saneamento.numerosNaEntrada > 0, "a captura tinha telefones de forma real");
    assert.ok((saneamento.substituicoes.telefone ?? 0) > 0);
    assert.ok((saneamento.substituicoes.texto_livre ?? 0) > 0);
  });

  it("sementes diferentes dao fixtures diferentes — o mapa nao e invertivel", () => {
    const a = JSON.stringify(sanear(capturaCrua(), "uma").arvore);
    const b = JSON.stringify(sanear(capturaCrua(), "outra").arvore);
    assert.notEqual(a, b);
  });

  it("a mesma semente da a mesma fixture", () => {
    const a = JSON.stringify(sanear(capturaCrua(), "igual").arvore);
    const b = JSON.stringify(sanear(capturaCrua(), "igual").arvore);
    assert.equal(a, b);
  });

  it("recusa quando um telefone sobrevive numa chave que o saneador nao conhece", () => {
    // É a propriedade que faz desta ferramenta uma salvaguarda: a verificação é
    // sobre a **saída**, e por isso uma chave nova que o saneador não conheça
    // aparece como recusa em vez de como dado pessoal gravado.
    const estranho = {
      object: "whatsapp_business_account",
      entry: [
        {
          id: "109876543210987",
          changes: [
            {
              field: "messages",
              value: {
                metadata: { phone_number_id: "119876543210987" },
                campo_que_ninguem_previu: "o cliente e o +244 900000003",
              },
            },
          ],
        },
      ],
    };
    try {
      sanear(estranho, "semente-de-ensaio");
      assert.fail("devia ter recusado");
    } catch (erro) {
      assert.ok(erro instanceof CapturaRecusadaError);
      // A mensagem diz **qual** chave acrescentar, e não leva o número.
      assert.match(erro.message, /campo_que_ninguem_previu/);
      assert.ok(!erro.message.includes("900000003"), erro.message);
      assert.equal(erro.ocorrencias.length, 1);
    }
  });

  it("uma captura ja ficticia passa sem mudar de intervalo", () => {
    const limpa = {
      object: "whatsapp_business_account",
      entry: [{ id: "100000000000001", changes: [{ field: "messages", value: { metadata: { phone_number_id: "120000000000001" }, contacts: [{ wa_id: "999100000001" }] } }] }],
    };
    const { arvore } = sanear(limpa, "semente-de-ensaio");
    const corpo = arvore as { entry: { changes: { value: { contacts: { wa_id: string }[] } }[] }[] };
    assert.ok(eFicticio(corpo.entry[0]?.changes[0]?.value.contacts[0]?.wa_id ?? ""));
  });
});

describe("o scan (criterio 7)", () => {
  it("da a linha e a coluna de cada achado", () => {
    const texto = ['{"a":1}', '{"wa_id":"+244923456789"}', "nada aqui"].join("\n");
    const achados = varrer(texto);
    assert.ok(achados.length >= 1);
    assert.equal(achados[0]?.linha, 2);
    assert.ok((achados[0]?.coluna ?? 0) > 0);
  });

  it("nao acha nada num texto so com numeros ficticios", () => {
    assert.deepEqual(varrer('{"wa_id":"999100000001","from":"+999100000002"}'), []);
  });

  it("ordena por linha e coluna", () => {
    const texto = ['"+244923456789"', "", '"+351912345678"'].join("\n");
    const achados = varrer(texto);
    assert.deepEqual(
      achados.map((a) => a.linha),
      [...achados.map((a) => a.linha)].sort((x, y) => x - y),
    );
  });
});

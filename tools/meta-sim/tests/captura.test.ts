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

describe("a lista branca do criterio 7 (revisao adversarial)", () => {
  /** Uma captura com um valor numa chave que o saneador nao conhece. */
  function comCampoNovo(valor: unknown): unknown {
    return {
      object: "whatsapp_business_account",
      entry: [
        {
          id: "109876543210987",
          changes: [
            {
              field: "messages",
              value: {
                metadata: { phone_number_id: "119876543210987" },
                campo_que_ninguem_previu: valor,
              },
            },
          ],
        },
      ],
    };
  }

  // Estes sao os casos que as duas primeiras verificacoes — as listas **negras**
  // — nao apanhavam. Um `+351912345678` escrito sem `+` nao casa o padrao
  // angolano nem o padrao de E.164 entre aspas, e por isso atravessava o
  // saneamento, o `exigirFicticios` e o *scan*. O critério diz o contrario:
  // «recusa gravar se detectar um numero que **nao pertenca** a lista de
  // numeros ficticios».
  for (const [nome, valor] of [
    ["um E.164 portugues sem +", "351912345678"],
    ["o numero de teste da Meta (+1)", "15550123456"],
    ["um numero brasileiro", "5511987654321"],
    ["um numero mocambicano", "258841234567"],
  ] as const) {
    it(`recusa ${nome}`, () => {
      try {
        sanear(comCampoNovo(valor), "semente-de-ensaio");
        assert.fail("devia ter recusado");
      } catch (erro) {
        assert.ok(erro instanceof CapturaRecusadaError);
        assert.deepEqual(erro.chavesComFormaDeTelefone, ["campo_que_ninguem_previu"]);
        // A mensagem diz **qual** chave acrescentar, e nao leva o numero.
        assert.match(erro.message, /campo_que_ninguem_previu/);
        assert.ok(!erro.message.includes(valor), erro.message);
      }
    });
  }

  it("aceita um numero do intervalo ficticio na mesma chave", () => {
    assert.doesNotThrow(() => sanear(comCampoNovo("999100000001"), "semente-de-ensaio"));
  });

  it("aceita texto e identificadores opacos na mesma chave", () => {
    for (const valor of ["Bom dia, tem disponivel?", "AQBx9f2kLm", "pnid-1", ""]) {
      assert.doesNotThrow(() => sanear(comCampoNovo(valor), "semente-de-ensaio"), valor);
    }
  });

  it("um timestamp NAO e tratado como telefone", () => {
    // Dez algarismos tem forma de telefone, e sem a lista de chaves numericas
    // a verificacao recusava **todas** as capturas: medido, com os onze testes
    // de saneamento a ficarem vermelhos de uma vez.
    assert.doesNotThrow(() =>
      sanear(
        {
          object: "x",
          entry: [
            {
              id: "109876543210987",
              time: 1_790_900_000,
              changes: [
                {
                  field: "messages",
                  value: {
                    metadata: { phone_number_id: "119876543210987" },
                    messages: [{ timestamp: "1790900000", type: "text" }],
                  },
                },
              ],
            },
          ],
        },
        "semente-de-ensaio",
      ),
    );
  });

  it("o history[].threads[].id e saneado, e e um telefone numa chave chamada id", () => {
    // O caminho inteiro que a revisao adversarial mostrou: a chave nao estava
    // em `CHAVES_DE_TELEFONE`, o ramo do `wamid` ignorava-a por nao comecar por
    // `wamid.`, e o numero sobrevivia. O proprio simulador produz esta chave.
    const captura = {
      object: "whatsapp_business_account",
      entry: [
        {
          id: "109876543210987",
          changes: [
            {
              field: "history",
              value: {
                metadata: { phone_number_id: "119876543210987" },
                history: [{ threads: [{ id: "351912345678", messages: [] }] }],
              },
            },
          ],
        },
      ],
    };
    const { arvore } = sanear(captura, "semente-de-ensaio");
    const texto = JSON.stringify(arvore);
    assert.ok(!texto.includes("351912345678"), "o numero real sobreviveu");
    const corpo = arvore as {
      entry: { changes: { value: { history: { threads: { id: string }[] }[] } }[] }[];
    };
    assert.ok(eFicticio(corpo.entry[0]?.changes[0]?.value.history[0]?.threads[0]?.id ?? ""));
  });
});

describe("as coordenadas e o texto livre que faltavam (revisao adversarial)", () => {
  function comLocalizacao(): unknown {
    return {
      object: "whatsapp_business_account",
      entry: [
        {
          id: "109876543210987",
          changes: [
            {
              field: "messages",
              value: {
                metadata: { phone_number_id: "119876543210987" },
                messages: [
                  {
                    from: "999100000001",
                    type: "location",
                    location: {
                      latitude: -8.838333,
                      longitude: 13.234444,
                      address: "Rua Direita 42, Ingombota, Luanda",
                      name: "Casa da Maria",
                    },
                  },
                ],
              },
            },
          ],
        },
      ],
    };
  }

  it("as coordenadas sao arredondadas a zona", () => {
    // Sao **numeros**, e o `percorrer` devolvia-os intactos: a docstring do
    // modulo afirmava que as coordenadas exactas eram substituidas e nao eram.
    // Duas casas decimais dao cerca de um quilometro — bastante para descrever
    // «uma localizacao em Luanda» e insuficiente para descrever uma casa.
    const { arvore } = sanear(comLocalizacao(), "semente-de-ensaio");
    const corpo = arvore as {
      entry: {
        changes: { value: { messages: { location: { latitude: number; longitude: number } }[] } }[];
      }[];
    };
    const sitio = corpo.entry[0]?.changes[0]?.value.messages[0]?.location;
    assert.equal(sitio?.latitude, -8.84);
    assert.equal(sitio?.longitude, 13.23);
  });

  it("a morada e substituida, e o nome do sitio tambem", () => {
    const { arvore } = sanear(comLocalizacao(), "semente-de-ensaio");
    const texto = JSON.stringify(arvore);
    assert.ok(!texto.includes("Rua Direita"), "a morada sobreviveu");
    assert.ok(!texto.includes("Casa da Maria"), "o nome do sitio sobreviveu");
  });

  it("as oito chaves de texto livre novas sao todas substituidas", () => {
    // A lista cresceu com a revisao adversarial, que enumerou o que faltava.
    const chaves = ["address", "text", "title", "description", "payload", "headline", "source_url", "alert_description"];
    const valor: Record<string, unknown> = { metadata: { phone_number_id: "119876543210987" } };
    for (const chave of chaves) valor[chave] = `SEGREDO-${chave}`;
    const { arvore } = sanear(
      { object: "x", entry: [{ id: "109876543210987", changes: [{ field: "messages", value: valor }] }] },
      "semente-de-ensaio",
    );
    const texto = JSON.stringify(arvore);
    for (const chave of chaves) {
      assert.ok(!texto.includes(`SEGREDO-${chave}`), `a chave ${chave} nao foi saneada`);
    }
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

  it("ordena por linha E por coluna, com os valores afirmados", () => {
    // **A primeira versao deste teste era vacua**: comparava
    // `achados.map(a => a.linha)` com uma copia ordenada **de si mesmo**, nao
    // olhava para as colunas, e nao afirmava o comprimento — pelo que passava
    // com um array vazio e passava sem o `.sort()` do `varrer`. Achado da
    // revisao adversarial.
    //
    // Agora afirma os pares exactos. A linha 1 tem **duas** ocorrencias (os
    // dois padroes casam a mesma cadeia, em colunas diferentes), e e ai que o
    // `sort` tem algo para fazer: sem ele vem na ordem dos padroes.
    const texto = ['"+244923456789"', "", '"+351912345678"'].join("\n");
    const achados = varrer(texto);
    assert.equal(achados.length, 3);
    assert.deepEqual(
      achados.map((a) => [a.linha, a.coluna]),
      [
        [1, 1],
        [1, 2],
        [3, 1],
      ],
    );
    assert.deepEqual(
      achados.map((a) => a.padrao),
      ["e164_entre_aspas", "telefone_ao", "e164_entre_aspas"],
    );
  });
});

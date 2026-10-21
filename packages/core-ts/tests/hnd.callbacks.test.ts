/**
 * A autenticação e a leitura dos *callbacks* do provedor (KAM-019, critério 5).
 *
 * «Os *callbacks* do Chatwoot (`message_created` de agente,
 * `conversation_status_changed`) só são aceites com o `secret` do bot; ausente
 * ou errado devolve 401 e incrementa uma métrica.»
 *
 * O que estes testes prendem, e a ordem é a da gravidade:
 *
 * 1. **Um segredo esperado vazio recusa tudo.** É a falha fechada: se o cofre
 *    não devolveu nada, nenhum *callback* passa. Sem esta asserção, uma
 *    configuração em falta tornava-se uma porta aberta — e passaria todos os
 *    outros testes deste ficheiro.
 * 2. **O eco do nosso próprio espelho não é uma resposta humana.** O
 *    `message_created` chega para **todas** as mensagens da conversa,
 *    incluindo as que nós espelhámos: tratá-las como resposta do agente era
 *    reenviar ao cliente o que ele acabou de nos mandar — um ciclo.
 * 3. **Os três tipos que não tratamos são recusados e não ignorados.** Com um
 *    200 silencioso, o provedor pára de reenviar e nós nunca sabemos.
 * 4. **Do agente lê-se o `id` e mais nada.** Nem `name` nem `email`, que ele
 *    manda no mesmo objecto.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ATRIBUTO_DO_HANDOFF,
  ESTADO_DE_RECUSA,
  EVENTO_DO_PROVEDOR,
  MOTIVOS_DE_RECUSA,
  avaliar,
  identificadorDoAgente,
  lerAcontecimento,
  segredoConfere,
  type Corpo,
} from "../src/hnd/index.ts";

const SEGREDO = "um-secret-de-bot-com-tamanho-razoavel";

/** Um `message_created` de agente, como o provedor o manda. */
function doAgente(troca: Partial<Record<string, unknown>> = {}): Corpo {
  return {
    event: "message_created",
    message_type: "outgoing",
    // O identificador da **mensagem** no provedor. E dele que a chave de
    // idempotencia do envio da resposta humana deriva (`resposta.ts`).
    id: 555,
    content: "Bom dia, eu respondo",
    sender: { id: 42, name: "Ana", email: "ana@loja.ao" },
    conversation: {
      id: "9001",
      status: "open",
      custom_attributes: { [ATRIBUTO_DO_HANDOFF]: "h_abc" },
    },
    ...troca,
  };
}

describe("o segredo do bot", () => {
  it("confere quando e igual", () => {
    assert.ok(segredoConfere(SEGREDO, SEGREDO));
  });

  it("recusa um segredo diferente do mesmo tamanho", () => {
    const outro = `${SEGREDO.slice(0, -1)}X`;
    assert.equal(outro.length, SEGREDO.length);
    assert.ok(!segredoConfere(outro, SEGREDO));
  });

  it("recusa tamanhos diferentes sem levantar", () => {
    // O `timingSafeEqual` **levanta** com tamanhos diferentes; o tamanho e o
    // unico facto que vaza e trata-se antes de comparar.
    assert.ok(!segredoConfere("curto", SEGREDO));
    assert.ok(!segredoConfere(`${SEGREDO}a-mais`, SEGREDO));
  });

  it("recusa ausente e vazio", () => {
    assert.ok(!segredoConfere(null, SEGREDO));
    assert.ok(!segredoConfere("", SEGREDO));
  });

  it("**um segredo esperado vazio recusa tudo**, e e a falha fechada", () => {
    // Se o cofre nao devolveu nada, nenhum callback passa. Sem isto, uma
    // configuracao em falta tornava-se uma porta aberta — e o pior e que
    // passaria todos os outros testes deste ficheiro.
    assert.ok(!segredoConfere("", ""));
    assert.ok(!segredoConfere("qualquer-coisa", ""));
    assert.ok(!segredoConfere(SEGREDO, ""));
  });
});

describe("o veredicto de um callback", () => {
  it("aceita com segredo certo e conta conhecida", () => {
    assert.deepEqual(avaliar(SEGREDO, SEGREDO, true), { aceite: true });
  });

  it("sem segredo da 401 e sem_secret", () => {
    const veredicto = avaliar(null, SEGREDO, true);
    assert.deepEqual(veredicto, {
      aceite: false,
      motivo: "sem_secret",
      estado: ESTADO_DE_RECUSA,
    });
    assert.equal(ESTADO_DE_RECUSA, 401);
  });

  it("com segredo errado da 401 e secret_errado", () => {
    assert.equal(avaliar("errado", SEGREDO, true).aceite, false);
    const veredicto = avaliar("errado", SEGREDO, true);
    assert.equal(veredicto.aceite === false ? veredicto.motivo : "", "secret_errado");
  });

  it("**a conta desconhecida vem depois do segredo**, e a ordem e o custo", () => {
    // Um pedido sem segredo nunca chega a consultar a conta: e o que impede o
    // uso do endpoint como gerador de carga. Afirma-se pela ordem dos motivos:
    // sem segredo **e** sem conta da `sem_secret`, nao `conta_desconhecida`.
    const veredicto = avaliar(null, SEGREDO, false);
    assert.equal(veredicto.aceite === false ? veredicto.motivo : "", "sem_secret");
  });

  it("com segredo certo e conta desconhecida da conta_desconhecida", () => {
    const veredicto = avaliar(SEGREDO, SEGREDO, false);
    assert.equal(veredicto.aceite === false ? veredicto.motivo : "", "conta_desconhecida");
  });

  it("os quatro motivos sao uma lista fechada, porque sao etiqueta", () => {
    assert.deepEqual([...MOTIVOS_DE_RECUSA], [
      "sem_secret",
      "secret_errado",
      "tipo_desconhecido",
      "conta_desconhecida",
    ]);
  });
});

describe("a leitura do corpo", () => {
  it("le um message_created de agente", () => {
    const acontecimento = lerAcontecimento(doAgente());
    assert.deepEqual(acontecimento, {
      acontecimento: "mensagem_de_agente",
      externalId: "9001",
      handoffId: "h_abc",
      texto: "Bom dia, eu respondo",
      mensagemId: "555",
      estado: null,
      resolver: "42",
    });
  });

  it("**um incoming nao e resposta de agente**: e o eco do nosso espelho", () => {
    // O `message_created` chega para **todas** as mensagens da conversa,
    // incluindo as que nos proprios espelhamos. Trata-las como resposta era
    // reenviar ao cliente o que ele acabou de nos mandar — um ciclo.
    assert.equal(lerAcontecimento(doAgente({ message_type: "incoming" })), null);
  });

  it("uma mensagem sem message_type tambem nao passa", () => {
    const corpo = { ...doAgente() };
    delete (corpo as Record<string, unknown>)["message_type"];
    assert.equal(lerAcontecimento(corpo), null);
  });

  it("le um conversation_status_changed", () => {
    const acontecimento = lerAcontecimento({
      event: "conversation_status_changed",
      conversation: {
        id: "9001",
        status: "resolved",
        custom_attributes: { [ATRIBUTO_DO_HANDOFF]: "h_abc" },
      },
      assignee: { id: 7, name: "Beto" },
    });
    assert.equal(acontecimento?.acontecimento, "estado_mudou");
    assert.equal(acontecimento?.estado, "resolved");
    assert.equal(acontecimento?.resolver, "7");
    assert.equal(acontecimento?.texto, null);
    // **Um `estado_mudou` nao e uma mensagem**: nao tem identificador de
    // mensagem, e por isso nao ha resposta humana a enviar a partir dele.
    assert.equal(acontecimento?.mensagemId, null);
  });

  it("**os tres tipos que nao tratamos devolvem null**", () => {
    // O provedor manda cinco (`docs/tecnica/01` §11.3) e aceitamos dois. Os
    // outros tres sao recusados pelo chamador com 401, e nao ignorados com um
    // 200: com 200 ele para de reenviar e nos nunca sabemos.
    for (const nome of [
      "conversation_created",
      "conversation_updated",
      "message_updated",
    ]) {
      assert.equal(lerAcontecimento({ ...doAgente(), event: nome }), null, nome);
    }
    assert.deepEqual(Object.keys(EVENTO_DO_PROVEDOR).sort(), [
      "conversation_status_changed",
      "message_created",
    ]);
  });

  it("sem o atributo do handoff nao se le nada", () => {
    // Sem `handoffId` nao se sabe que passagem e, e adivinhar pela conversa era
    // casar um callback com a passagem errada.
    const corpo = doAgente({ conversation: { id: "9001", custom_attributes: {} } });
    assert.equal(lerAcontecimento(corpo), null);
  });

  it("sem identificador de conversa tambem nao", () => {
    const corpo = doAgente({
      conversation: { custom_attributes: { [ATRIBUTO_DO_HANDOFF]: "h_abc" } },
    });
    assert.equal(lerAcontecimento(corpo), null);
  });

  it("um corpo sem `event` nao e um callback", () => {
    assert.equal(lerAcontecimento({}), null);
    assert.equal(lerAcontecimento({ event: 7 }), null);
  });
});

describe("o identificador do agente", () => {
  it("**le o id e mais nada**", () => {
    // O `resolver` e o primeiro dado pessoal de um trabalhador da PME no
    // esquema. O provedor manda `name` e `email` no mesmo objecto, e nao
    // le-los e mais forte do que le-los e descarta-los.
    const acontecimento = lerAcontecimento(doAgente());
    assert.equal(acontecimento?.resolver, "42");
    const tudo = JSON.stringify(acontecimento);
    assert.ok(!tudo.includes("Ana"), "o nome do agente nao entra");
    assert.ok(!tudo.includes("ana@loja.ao"), "o e-mail tambem nao");
  });

  it("aceita um id numerico e um id de texto", () => {
    assert.equal(identificadorDoAgente({ sender: { id: 42 } }), "42");
    assert.equal(identificadorDoAgente({ sender: { id: "ag-42" } }), "ag-42");
  });

  it("sem remetente nem responsavel da null", () => {
    assert.equal(identificadorDoAgente({}), null);
    assert.equal(identificadorDoAgente({ sender: null }), null);
    assert.equal(identificadorDoAgente({ sender: { nome: "sem id" } }), null);
  });
});

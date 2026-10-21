/**
 * A resposta humana que sai ao cliente pelo Outbound (KAM-019, critério 6).
 *
 * «A resposta humana é enviada ao cliente pelo Outbound (janela, template se
 * fechada, custo registado); com janela fechada o painel recebe aviso e
 * proposta de template *utility*.»
 *
 * **Monta-se um `Saida` verdadeiro**, com a base e a Meta por porta, e não um
 * duplo: o que esta costura tem de provar é que a resposta humana atravessa o
 * adapter de saída **com as regras dele** — a janela, a chave de idempotência,
 * o guarda — e um duplo do `Saida` devolveria o que lhe mandássemos devolver.
 *
 * O que os testes prendem, por ordem de gravidade:
 *
 * 1. **A chave de idempotência deriva do identificador da mensagem no
 *    provedor.** Dois *callbacks* do mesmo `message_created` — que o provedor
 *    reenvia — dão **uma** mensagem ao cliente. Derivá-la do texto fazia duas
 *    mensagens iguais do agente («ok») serem uma só.
 * 2. **Sem esse identificador não se envia.** Uma chave inventada tirava ao
 *    Outbound a única coisa que o torna idempotente.
 * 3. **`doBot: false`**, logo a resposta **não** passa pelo `PreSendGuard`.
 *    Recusar a resposta da pessoa que o modo humano existe para servir era o
 *    contrário do que o guarda protege.
 * 4. **Com a janela fechada avisa-se e propõe-se, não se envia.** Um template
 *    fora da janela é pago, e a decisão de gastar é da PME.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  Saida,
  WINDOW_CLOSED,
  type Pedido,
  type RespostaDaMeta,
} from "../src/outbound/index.ts";
import {
  TEMPLATE_PROPOSTO,
  lerAcontecimento,
  responderAoCliente,
  type AvisoDeJanelaFechada,
  type Corpo,
  type DestinoDaResposta,
  type HumanEvent,
} from "../src/hnd/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const T0 = Date.UTC(2026, 9, 20, 12, 0, 0);

const DESTINO: DestinoDaResposta = {
  tenantId: TENANT,
  channelId: "22222222-2222-4222-8222-222222222222",
  contactId: "33333333-3333-4333-8333-333333333333",
  conversationId: "44444444-4444-4444-8444-444444444444",
  phoneNumberId: "109876543210987",
};

/** A base por porta, com o `ON CONFLICT` da chave de idempotência. */
class BaseFalsa {
  readonly chaves = new Set<string>();
  /** `null` é «a janela nunca abriu»; por omissão está aberta. */
  janela: Date | null = new Date(T0 + 3_600_000);
  #proximo = 0;

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    const linhas = (valor: unknown[]): { rows: readonly T[] } => ({
      rows: valor as readonly T[],
    });
    if (texto.includes("FROM platform.conversations")) {
      return linhas([{ window_expires_at: this.janela, mode: "humano" }]);
    }
    if (texto.includes("INSERT INTO platform.outbound_messages")) {
      const chave = String(valores[4]);
      if (this.chaves.has(chave)) return linhas([]);
      this.chaves.add(chave);
      this.#proximo += 1;
      return linhas([{ id: `id-${this.#proximo}` }]);
    }
    if (texto.includes("SELECT id, wamid, kind, state")) {
      return linhas([{ id: "id-1", wamid: "wamid.ANTERIOR", kind: "service" }]);
    }
    return linhas([]);
  }
}

interface Montagem {
  readonly saida: Saida;
  readonly bd: BaseFalsa;
  readonly chamadas: () => number;
  readonly avisos: AvisoDeJanelaFechada[];
}

function montar(): Montagem {
  const bd = new BaseFalsa();
  let chamadas = 0;
  // **O relogio avanca pelo `dormir`**, e nao e cosmetica. O `Saida` espera
  // pelo primeiro token do *bucket* (KAM-015) e decide desistir comparando o
  // `agora()` com o instante em que comecou. Com um relogio congelado e um
  // `dormir` que nao faz nada, essa espera nao termina nunca — e nao termina
  // em silencio: foi um ciclo a 99% de CPU durante dezasseis minutos, que so um
  // `docker top` mostrou. E e a mesma montagem que a bateria do Outbound usa.
  let instante = T0;
  const avisos: AvisoDeJanelaFechada[] = [];
  const saida = new Saida({
    bd,
    meta: {
      enviar: async (): Promise<RespostaDaMeta> => {
        chamadas += 1;
        return { ok: true, wamid: `wamid.H${chamadas}` };
      },
    },
    destinatario: async () => ({ bsuid: "BS1", telefone: null }),
    // **Um guarda que recusa sempre.** É assim que se prova que a resposta
    // humana não lhe pede licença: se o `doBot` fosse `true`, nada saía.
    guarda: async () => false,
    freeTier: null,
    agora: () => new Date(instante),
    aleatorio: () => 0,
    dormir: async (ms: number) => {
      instante += ms;
    },
    ambiente: {},
  });
  return { saida, bd, chamadas: () => chamadas, avisos };
}

/** Um `message_created` de agente, lido pelo próprio leitor do módulo. */
function doAgente(id: number, texto = "Eu respondo"): HumanEvent {
  const corpo: Corpo = {
    event: "message_created",
    message_type: "outgoing",
    id,
    content: texto,
    sender: { id: 42 },
    conversation: { id: "cw-1", custom_attributes: { handoffId: "h_abc" } },
  };
  const acontecimento = lerAcontecimento(corpo);
  assert.ok(acontecimento !== null, "a fixture tem de ser legivel");
  return acontecimento;
}

describe("a resposta humana sai pelo Outbound (criterio 6)", () => {
  it("uma mensagem do agente chega ao cliente", async () => {
    const { saida, chamadas, avisos } = montar();
    const desfecho = await responderAoCliente(
      doAgente(555),
      DESTINO,
      saida,
      async (aviso) => {
        avisos.push(aviso);
      },
    );
    assert.equal(desfecho.enviada, true);
    assert.equal(chamadas(), 1);
    assert.deepEqual(avisos, []);
  });

  it("**o guarda recusa sempre e a resposta sai**: `doBot: false`", async () => {
    // O `PreSendGuard` protege uma conversa em modo dono ou humano de ser
    // interrompida pelo **assistente**. Recusar a resposta da pessoa que o modo
    // humano existe para servir era o contrario do que ele protege. O guarda
    // desta montagem devolve `false` sempre: se o `doBot` fosse `true`, nada
    // saia.
    const { saida, chamadas } = montar();
    const desfecho = await responderAoCliente(doAgente(556), DESTINO, saida, async () => undefined);
    assert.equal(desfecho.enviada, true, "o guarda nao pode travar a resposta humana");
    assert.equal(chamadas(), 1);
  });

  it("**o mesmo callback duas vezes da uma mensagem**", async () => {
    // O provedor reenvia. A chave deriva do identificador da **mensagem** dele,
    // e e o `ON CONFLICT (tenant_id, idempotency_key)` do Outbound que
    // de-duplica.
    const { saida, chamadas } = montar();
    await responderAoCliente(doAgente(557), DESTINO, saida, async () => undefined);
    const segundo = await responderAoCliente(
      doAgente(557),
      DESTINO,
      saida,
      async () => undefined,
    );
    assert.equal(chamadas(), 1, "a segunda chamada a Meta e o defeito que isto prende");
    assert.equal(segundo.enviada, true, "o Outbound devolve ok com `repetido`");
  });

  it("**duas mensagens iguais com ids diferentes saem as duas**", async () => {
    // E a razao de a chave **nao** derivar do texto: um agente que escreva «ok»
    // duas vezes mandou duas mensagens, e colapsa-las era perder uma.
    const { saida, chamadas } = montar();
    await responderAoCliente(doAgente(558, "ok"), DESTINO, saida, async () => undefined);
    await responderAoCliente(doAgente(559, "ok"), DESTINO, saida, async () => undefined);
    assert.equal(chamadas(), 2);
  });

  it("**sem identificador de mensagem nao se envia**", async () => {
    // Uma chave inventada aqui tirava ao Outbound a unica coisa que o torna
    // idempotente, e um reenvio do provedor passava a ser uma segunda mensagem
    // ao cliente.
    const { saida, chamadas } = montar();
    const semId: HumanEvent = { ...doAgente(560), mensagemId: null };
    const desfecho = await responderAoCliente(semId, DESTINO, saida, async () => undefined);
    assert.equal(desfecho.enviada, false);
    assert.equal(desfecho.enviada === false ? desfecho.motivo : "", "SEM_ID_DA_MENSAGEM");
    assert.equal(chamadas(), 0);
  });

  it("um estado_mudou nao e uma resposta", async () => {
    const { saida, chamadas } = montar();
    const mudanca = lerAcontecimento({
      event: "conversation_status_changed",
      conversation: {
        id: "cw-1",
        status: "open",
        custom_attributes: { handoffId: "h_abc" },
      },
    });
    assert.ok(mudanca !== null);
    const desfecho = await responderAoCliente(mudanca, DESTINO, saida, async () => undefined);
    assert.equal(desfecho.enviada, false);
    assert.equal(desfecho.enviada === false ? desfecho.motivo : "", "NAO_E_MENSAGEM");
    assert.equal(chamadas(), 0);
  });

  it("uma mensagem vazia nao se envia", async () => {
    const { saida, chamadas } = montar();
    const vazia: HumanEvent = { ...doAgente(561), texto: "" };
    const desfecho = await responderAoCliente(vazia, DESTINO, saida, async () => undefined);
    assert.equal(desfecho.enviada === false ? desfecho.motivo : "", "SEM_TEXTO");
    assert.equal(chamadas(), 0);
  });
});

describe("com a janela fechada avisa-se e propoe-se (criterio 6)", () => {
  it("**nao se envia, e o painel recebe o aviso com o template proposto**", async () => {
    const { saida, bd, chamadas, avisos } = montar();
    bd.janela = new Date(T0 - 1000);
    const desfecho = await responderAoCliente(
      doAgente(562, "Ja temos o seu tamanho"),
      DESTINO,
      saida,
      async (aviso) => {
        avisos.push(aviso);
      },
    );

    assert.equal(desfecho.enviada, false);
    assert.equal(desfecho.enviada === false ? desfecho.motivo : "", WINDOW_CLOSED);
    assert.equal(chamadas(), 0, "a janela fechada nao gasta chamada a Meta");
    assert.equal(avisos.length, 1);
    assert.equal(avisos[0]?.templateProposto, TEMPLATE_PROPOSTO);
    // **O texto que nao saiu vai no aviso**, porque sem ele o painel nao pode
    // oferecer a quem atende a opcao de o reenviar por template.
    assert.equal(avisos[0]?.textoNaoEnviado, "Ja temos o seu tamanho");
    assert.equal(avisos[0]?.handoffId, "h_abc");
  });

  it("**propoe e nao envia** o template: a decisao de gastar e da PME", async () => {
    // Um template fora da janela e pago (`E1` §1). Enviar um por iniciativa
    // propria era gastar o dinheiro da PME sem lhe perguntar.
    const { saida, bd, chamadas, avisos } = montar();
    bd.janela = null;
    await responderAoCliente(doAgente(563), DESTINO, saida, async (aviso) => {
      avisos.push(aviso);
    });
    assert.equal(chamadas(), 0);
    assert.equal(avisos.length, 1);
  });

  it("uma conversa que nunca abriu janela tambem avisa", async () => {
    const { saida, bd, avisos } = montar();
    bd.janela = null;
    const desfecho = await responderAoCliente(
      doAgente(564),
      DESTINO,
      saida,
      async (aviso) => {
        avisos.push(aviso);
      },
    );
    assert.equal(desfecho.enviada === false ? desfecho.motivo : "", WINDOW_CLOSED);
  });
});

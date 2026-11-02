/**
 * O *handler* dos callbacks de pagamento (KAM-053, critério 7).
 *
 * O critério pede cinco coisas e as cinco têm ensaio nomeado:
 *
 *     404 uniforme com recibo `token_desconhecido`
 *     401 com `inbox.estado='hmac_invalido'` e `sig_ok=false`
 *     **zero** escritas no ledger quando o HMAC falha
 *     o corpo durável **antes** do 2xx
 *     ack p99 < 500 ms a 50 pedidos/s
 *
 * O quarto é o que distingue este ficheiro de um ensaio de rotas: não basta que
 * a gravação aconteça — tem de acontecer **primeiro**. A forma de o medir é
 * registar a ordem das chamadas às portas e compará-la com a do §5.1, e é o que
 * o `OrdemObservada` faz.
 *
 * O quinto mede-se com o relógio e sem servidor HTTP: o que o alvo do §14
 * limita é o que este caminho faz — uma gravação durável e uma verificação de
 * assinatura —, e levantar um servidor para o medir media também o servidor.
 * Fica dito que o número é **deste caminho** e não de um *endpoint* real, que é
 * o que o serviço `pay` medirá quando existir.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";

import {
  ALERTA_HMAC,
  CABECALHOS_GUARDADOS,
  CORPO_DO_404,
  EVENTOS_DO_WORKER,
  METRICA_ACK,
  TECTO_DO_CORPO,
  type AdaptadorDoHook,
  type ContaDoToken,
  type DependenciasDoHook,
  type EstadoDaEntrega,
  type Inbox,
  type TrabalhoDoWorker,
  atenderCallback,
  redigir,
} from "../src/pagamentos/index.ts";
import { AuthError } from "../src/pagamentos/index.ts";

const TOKEN = "a".repeat(43);
const CONTA: ContaDoToken = {
  accountId: "9c3d1a7e-0000-4000-8000-000000000001",
  tenantId: "9c3d1a7e-0000-4000-8000-000000000002",
  provider: "fakeprovider",
  entidade: "00123",
  posId: null,
  estado: "ativo",
};

/** O registo da ordem das chamadas. É o instrumento do critério «antes do 2xx». */
type OrdemObservada = string[];

type Montagem = {
  readonly deps: DependenciasDoHook;
  readonly ordem: OrdemObservada;
  readonly inseridas: {
    accountId: string | null;
    estado: EstadoDaEntrega;
  }[];
  readonly marcacoes: {
    recibo: bigint;
    estado: EstadoDaEntrega;
    authnOk?: boolean;
  }[];
  readonly encaminhados: TrabalhoDoWorker[];
  readonly alertas: string[];
  readonly medicoes: { metrica: string; valor: number }[];
};

function montar(opcoes: {
  readonly conta?: ContaDoToken | null;
  readonly adaptador?: AdaptadorDoHook | null;
  readonly relogio?: () => number;
} = {}): Montagem {
  const ordem: OrdemObservada = [];
  const inseridas: Montagem["inseridas"] = [];
  const marcacoes: Montagem["marcacoes"] = [];
  const encaminhados: TrabalhoDoWorker[] = [];
  const alertas: string[] = [];
  const medicoes: Montagem["medicoes"] = [];
  let proximo = 1n;

  const inbox: Inbox = {
    async inserir(entrega) {
      ordem.push("inbox.inserir");
      inseridas.push({ accountId: entrega.accountId, estado: entrega.estado });
      return proximo++;
    },
    async marcar(recibo, estado, campos) {
      ordem.push(`inbox.marcar:${estado}`);
      marcacoes.push({ recibo, estado, authnOk: campos?.authnOk });
    },
  };

  const adaptador: AdaptadorDoHook =
    opcoes.adaptador === undefined
      ? {
          callbackAuth: "hmac",
          async verifyCallback() {
            ordem.push("verifyCallback");
            return [
              {
                providerEventId: "ev-1",
                referencia: "REF1",
                valor: 1_250_000n,
                currency: "AOA",
                authnMethod: "hmac",
                ocorridoEm: "2026-11-02T10:00:00.000Z",
              },
            ];
          },
        }
      : (opcoes.adaptador as AdaptadorDoHook);

  const deps: DependenciasDoHook = {
    inbox,
    async resolverToken() {
      ordem.push("resolverToken");
      return opcoes.conta === undefined ? CONTA : opcoes.conta;
    },
    adaptador: () => (opcoes.adaptador === null ? null : adaptador),
    encaminhar(trabalho) {
      ordem.push("encaminhar");
      encaminhados.push(trabalho);
    },
    alertar(alerta) {
      alertas.push(alerta);
    },
    medir(metrica, valor) {
      ordem.push("medir");
      medicoes.push({ metrica, valor });
    },
    sha256: (corpo) => new Uint8Array(createHash("sha256").update(corpo).digest()),
    agora: opcoes.relogio,
  };
  return { deps, ordem, inseridas, marcacoes, encaminhados, alertas, medicoes };
}

const CORPO = new TextEncoder().encode('{"referencia":"REF1","valor":"12500.00"}');

function pedido(extra: Record<string, unknown> = {}) {
  return {
    provider: "fakeprovider",
    token: TOKEN,
    corpo: CORPO,
    cabecalhos: { "content-type": "application/json" },
    ...extra,
  } as Parameters<typeof atenderCallback>[0];
}

describe("hooks de pagamento: a ordem do §5.1", () => {
  it("test_o_corpo_e_gravado_antes_de_verificar_e_antes_do_2xx", async () => {
    const m = montar();
    const resposta = await atenderCallback(pedido(), m.deps);

    assert.equal(resposta.estado, 200);
    // **É isto o critério.** Um 2xx dado antes da gravação perde o callback se o
    // processo morrer, e o facilitador já não o repete.
    assert.deepEqual(m.ordem, [
      "resolverToken",
      "inbox.inserir",
      "verifyCallback",
      "encaminhar",
      "medir",
    ]);
    assert.equal(m.inseridas.length, 1);
    assert.equal(m.inseridas[0]?.estado, "recebido");
  });

  it("test_o_worker_corre_depois_do_2xx_e_nao_e_esperado", async () => {
    // O `encaminhar` é síncrono e sem `await`: o que garante que nada se perde é
    // o *inbox* já gravado, não a entrega do encaminhamento. Se fosse esperado,
    // um *worker* lento somava-se ao ack e o alvo de 500 ms do §14 passava a
    // depender do tempo de escrever no ledger.
    const m = montar();
    await atenderCallback(pedido(), m.deps);
    assert.equal(m.encaminhados.length, 1);
    assert.equal(m.encaminhados[0]?.porConsulta, false);
    assert.equal(m.encaminhados[0]?.eventos.length, 1);
  });
});

describe("hooks de pagamento: os três códigos", () => {
  it("test_token_desconhecido_da_404_com_recibo_e_grava_a_entrega", async () => {
    const m = montar({ conta: null });
    const resposta = await atenderCallback(pedido(), m.deps);

    assert.equal(resposta.estado, 404);
    assert.deepEqual(resposta.corpo, CORPO_DO_404);
    // **Grava, e só depois responde 404.** Sem esta linha, um varrimento de
    // *tokens* não deixa rasto nenhum — e o 404 uniforme passa a ser a única
    // coisa que o atacante aprende de graça.
    assert.equal(m.inseridas.length, 1);
    assert.equal(m.inseridas[0]?.accountId, null);
    assert.equal(m.inseridas[0]?.estado, "token_desconhecido");
    assert.equal(m.encaminhados.length, 0, "nada vai para o worker");
  });

  it("test_o_404_e_uniforme_para_tokens_diferentes", async () => {
    // O corpo é o mesmo e não nomeia o que falhou. Um corpo que distinguisse
    // «*token* mal formado» de «*token* que não existe» era um oráculo.
    const respostas = [];
    for (const token of ["", "x", TOKEN, "z".repeat(200)]) {
      const m = montar({ conta: null });
      respostas.push(await atenderCallback(pedido({ token }), m.deps));
    }
    for (const resposta of respostas) {
      assert.equal(resposta.estado, 404);
      assert.deepEqual(resposta.corpo, CORPO_DO_404);
    }
  });

  it("test_hmac_invalido_da_401_marca_o_inbox_e_nao_escreve_no_ledger", async () => {
    const m = montar({
      adaptador: {
        callbackAuth: "hmac",
        async verifyCallback() {
          throw new AuthError("assinatura nao verifica");
        },
      },
    });
    const resposta = await atenderCallback(pedido(), m.deps);

    assert.equal(resposta.estado, 401);
    assert.deepEqual(m.marcacoes, [
      { recibo: 1n, estado: "hmac_invalido", authnOk: false },
    ]);
    // **Zero linhas no ledger**, e é uma propriedade do caminho: nada é
    // encaminhado, pelo que o *worker* nunca é chamado. Se o `encaminhar`
    // corresse e o ledger recusasse depois, o critério ficava a depender de uma
    // barreira que está noutro componente.
    assert.equal(m.encaminhados.length, 0);
    assert.deepEqual(m.alertas, [ALERTA_HMAC], "o F-05 alerta por conta");
  });

  it("test_sem_assinatura_o_callback_e_dica_e_segue_por_consulta", async () => {
    // §5: «Facilitadores sem assinatura (OPG, EMIS, MoMenu): o callback é apenas
    // uma **dica**». Não é 401 — não houve verificação nenhuma — e não é uma
    // confirmação.
    const m = montar({
      adaptador: {
        callbackAuth: "none",
        async verifyCallback() {
          throw new Error("nunca deve ser chamado sem assinatura");
        },
      },
    });
    const resposta = await atenderCallback(pedido(), m.deps);

    assert.equal(resposta.estado, 200);
    assert.deepEqual(m.marcacoes, [
      // `authn_ok` fica **nulo** e não `false`: `false` diria «foi verificado e
      // falhou». A diferença conta no alerta do F-05.
      { recibo: 1n, estado: "ignorado", authnOk: undefined },
    ]);
    assert.equal(m.encaminhados[0]?.porConsulta, true);
    assert.equal(m.encaminhados[0]?.eventos.length, 0);
    assert.deepEqual(m.alertas, [], "falta de HMAC nao e HMAC invalido");
  });

  it("test_sem_adaptador_o_corpo_fica_e_a_resposta_e_200", async () => {
    // O corpo já está durável; o facilitador não tem de repetir. Um 5xx aqui
    // gerava reentregas de algo que já ficou guardado.
    const m = montar({ adaptador: null });
    const resposta = await atenderCallback(pedido(), m.deps);
    assert.equal(resposta.estado, 200);
    assert.equal(m.marcacoes[0]?.estado, "erro");
  });

  it("test_um_corpo_acima_do_tecto_nao_e_gravado", async () => {
    // O tecto é a **única** coisa que vem antes da gravação: um corpo de
    // megabytes não é uma entrega de um facilitador, e guardá-lo era usar a
    // própria prova como munição.
    const m = montar();
    const resposta = await atenderCallback(
      pedido({ corpo: new Uint8Array(TECTO_DO_CORPO + 1) }),
      m.deps,
    );
    assert.equal(resposta.estado, 413);
    assert.equal(m.inseridas.length, 0);
  });
});

describe("hooks de pagamento: a redacção dos cabeçalhos", () => {
  it("test_a_lista_e_de_inclusao_e_nao_de_exclusao", () => {
    const guardados = redigir({
      "Content-Type": "application/json",
      Authorization: "Bearer segredo",
      "X-Proxypay-Signature": "abc",
      "X-Assinatura-De-Um-Facilitador-Futuro": "def",
      "User-Agent": "proxypay/1",
    });
    assert.deepEqual(guardados, {
      "content-type": "application/json",
      "user-agent": "proxypay/1",
    });
    // A diferença que importa: uma lista de **exclusão** guardava o cabeçalho de
    // assinatura de um facilitador que ninguém se lembrou de proibir.
    for (const nome of Object.keys(guardados)) {
      assert.ok((CABECALHOS_GUARDADOS as readonly string[]).includes(nome));
    }
  });
});

describe("hooks de pagamento: o ack p99 (§14)", () => {
  it("test_o_ack_p99_fica_abaixo_de_500_ms_a_50_pedidos_por_segundo", async () => {
    // **O que este número é, e o que não é.** É o p99 do caminho deste módulo —
    // resolução do *token*, gravação durável e verificação de assinatura — com
    // as portas a custarem o que uma base de dados local custa (1 ms cada,
    // simulado). **Não** é o p99 de um *endpoint* real: não há `services/pay/`
    // nesta árvore (dívida 148), e o alvo do §14 é medido no GWY com a métrica
    // `callback_ack_ms`, que este módulo emite. Fica dito em vez de se marcar a
    // caixa como se fosse a mesma medição.
    const PEDIDOS = 500;
    const CONCORRENCIA = 50;
    const atraso = () => new Promise((r) => setTimeout(r, 1));

    const inbox: Inbox = {
      async inserir() {
        await atraso();
        return 1n;
      },
      async marcar() {
        await atraso();
      },
    };
    const deps: DependenciasDoHook = {
      inbox,
      async resolverToken() {
        await atraso();
        return CONTA;
      },
      adaptador: () => ({
        callbackAuth: "hmac",
        async verifyCallback() {
          return [];
        },
      }),
      encaminhar() {},
      sha256: (corpo) =>
        new Uint8Array(createHash("sha256").update(corpo).digest()),
    };

    const amostras: number[] = [];
    for (let lote = 0; lote < PEDIDOS / CONCORRENCIA; lote += 1) {
      const inicio = performance.now();
      await Promise.all(
        Array.from({ length: CONCORRENCIA }, async () => {
          const t0 = performance.now();
          await atenderCallback(pedido(), deps);
          amostras.push(performance.now() - t0);
        }),
      );
      // 50 pedidos/s: o lote de 50 ocupa um segundo de janela. Esperar o resto
      // da janela é o que faz disto uma taxa e não uma rajada.
      const resto = 1000 - (performance.now() - inicio);
      if (resto > 0) await new Promise((r) => setTimeout(r, resto));
    }

    amostras.sort((a, b) => a - b);
    const p99 = amostras[Math.floor(amostras.length * 0.99)] ?? 0;
    assert.equal(amostras.length, PEDIDOS);
    assert.ok(
      p99 < 500,
      `p99 do caminho do handler = ${p99.toFixed(1)} ms (alvo < 500 ms)`,
    );
  });
});

describe("hooks de pagamento: o que o worker escreve", () => {
  it("test_os_veredictos_mapeiam_para_os_eventos_do_§5_1", () => {
    // O §5.1 escreve `pagamento_recebido` **e depois** a decisão, nesta ordem: o
    // facto antes do juízo. O `duplicado` não escreve nada — o G7 é «200, sem
    // efeito», e o `payment_events_entrega_uq` já tem a linha.
    assert.deepEqual(EVENTOS_DO_WORKER.confirmado, [
      "pagamento_recebido",
      "pagamento_confirmado",
    ]);
    assert.deepEqual(EVENTOS_DO_WORKER.divergente, [
      "pagamento_recebido",
      "pagamento_divergente",
    ]);
    assert.deepEqual(EVENTOS_DO_WORKER.orfao, ["pagamento_orfao"]);
    assert.deepEqual(EVENTOS_DO_WORKER.duplicado, []);
  });

  it("test_a_metrica_do_ack_e_emitida_em_todos_os_codigos", async () => {
    for (const opcoes of [{}, { conta: null }, { adaptador: null }]) {
      const m = montar(opcoes as Parameters<typeof montar>[0]);
      await atenderCallback(pedido(), m.deps);
      assert.equal(m.medicoes.length, 1);
      assert.equal(m.medicoes[0]?.metrica, METRICA_ACK);
    }
  });
});
